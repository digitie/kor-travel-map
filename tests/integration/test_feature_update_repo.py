"""``feature_update_repo`` — feature update request lifecycle (ADR-045 T-206b).

검증 범위:
- preview는 scope만 해석하고 DB row/import job을 만들지 않는다.
- enqueue는 ``ops.feature_update_requests``와 ``ops.import_jobs``를 같은 transaction에
  생성한다.
- peek/start/finish는 canonical import job 단일 lifecycle을 사용하고, 취소는 C3d만 소유한다.
- 목록은 D-10 keyset cursor로 중복 없이 페이지를 넘긴다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.core.feature_operation import FeatureOperationInvariantConflict
from kortravelmap.infra.advisory_lock import advisory_lock
from kortravelmap.infra.feature_update_repo import (  # noqa: PLC2701 - EXPLAIN 대상 SQL
    _LIST_PROVIDER_DATASET_REQUESTS_SQL,
    FEATURE_UPDATE_JOB_KIND,
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestPreview,
    advance_update_request_generation_after_pre_start_failure,
    enqueue_feature_update_request,
    feature_update_scope_advisory_key,
    finish_update_request,
    get_update_request,
    heartbeat_feature_update_request_job,
    list_update_requests,
    lock_feature_update_execution_guard,
    peek_next_update_request,
    peek_update_requests,
    preview_feature_update_request,
    requeue_update_request_after_lock_contention,
    set_update_request_matched_scope,
    start_update_request,
)
from kortravelmap.infra.jobs_repo import (
    claim_next_import_job,
    enqueue_unpaired_import_job,
    heartbeat_import_job,
    recover_stale_running_jobs,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    create_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


async def _count_rows(session: AsyncSession, table: str) -> int:
    return int((await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


async def _job_row(session: AsyncSession, job_id: str) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT kind, payload, status, progress, current_stage,
                       dagster_run_id, cancellation_id, error_message
                FROM ops.import_jobs
                WHERE job_id = :job_id
                """
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


def _plan_nodes(plan: Any) -> list[dict[str, Any]]:
    document = plan[0] if isinstance(plan, list) else plan
    pending = [document["Plan"]]
    nodes: list[dict[str, Any]] = []
    while pending:
        node = pending.pop()
        nodes.append(node)
        pending.extend(node.get("Plans", ()))
    return nodes


@pytest.mark.parametrize(
    ("providers", "dataset_keys", "message"),
    [
        ("python-mois-api", None, "providers must contain at most 32 strings"),
        ([123], None, "providers items must be strings"),
        ([""], None, "providers items must contain 1..128"),
        (["provider" * 17], None, "providers items must contain 1..128"),
        (["python-mois-api", "python-mois-api"], None, "items must be unique"),
        ([f"provider-{index}" for index in range(33)], None, "at most 32"),
        (None, [f"dataset-{index}" for index in range(65)], "at most 64"),
    ],
)
def test_scope_advisory_key_rejects_malformed_filters(
    providers: Any,
    dataset_keys: Any,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        feature_update_scope_advisory_key(
            scope_type="feature_ids",
            scope={"type": "feature_ids", "feature_ids": []},
            providers=providers,
            dataset_keys=dataset_keys,
        )


def test_scope_advisory_key_canonicalizes_filter_whitespace() -> None:
    common = {
        "scope_type": "feature_ids",
        "scope": {"type": "feature_ids", "feature_ids": []},
    }

    assert feature_update_scope_advisory_key(
        **common,
        providers=["\tpython-mois-api\u3000"],
        dataset_keys=[" mois_license_features_bulk "],
    ) == feature_update_scope_advisory_key(
        **common,
        providers=["python-mois-api"],
        dataset_keys=["mois_license_features_bulk"],
    )


def test_scope_advisory_key_canonicalizes_set_scope_order_and_rejects_duplicates() -> None:
    assert feature_update_scope_advisory_key(
        scope_type="feature_ids",
        scope={"type": "feature_ids", "feature_ids": ["feature-b", "feature-a"]},
    ) == feature_update_scope_advisory_key(
        scope_type="feature_ids",
        scope={"type": "feature_ids", "feature_ids": ["feature-a", "feature-b"]},
    )
    with pytest.raises(ValueError, match="unique"):
        feature_update_scope_advisory_key(
            scope_type="feature_ids",
            scope={"type": "feature_ids", "feature_ids": ["feature-a", "feature-a"]},
        )
    with pytest.raises(ValueError, match="must not repeat"):
        feature_update_scope_advisory_key(
            scope_type="provider_dataset",
            scope={
                "type": "provider_dataset",
                "provider": "python-mois-api",
                "dataset_key": "mois_license_features_bulk",
            },
            providers=["python-mois-api"],
        )


async def test_preview_returns_plan_without_writes(
    migrated_session: AsyncSession,
) -> None:
    preview = await preview_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-mois-api"],
    )

    assert isinstance(preview, FeatureUpdateRequestPreview)
    assert preview.scope_type == "feature_ids"
    assert preview.providers == ("python-mois-api",)
    assert preview.matched_scope == {"feature_count": 0, "sigungu_codes": []}
    assert await _count_rows(migrated_session, "ops.feature_update_requests") == 0
    assert await _count_rows(migrated_session, "ops.import_jobs") == 0


@pytest.mark.parametrize("operation", ["preview", "enqueue"])
@pytest.mark.parametrize(
    "invalid_policy",
    [
        ["refresh_existing"],
        {"unknown": True},
        {"mode": "replace_all"},
        {"include_inactive": "true"},
        {"force_provider_call": []},
    ],
)
async def test_preview_and_enqueue_reject_noncanonical_update_policy(
    migrated_session: AsyncSession,
    operation: str,
    invalid_policy: Any,
) -> None:
    if operation == "preview":
        with pytest.raises(ValueError, match="(?i)policy"):
            await preview_feature_update_request(
                migrated_session,
                scope={"type": "feature_ids", "feature_ids": []},
                update_policy=invalid_policy,
            )
    else:
        with pytest.raises(ValueError, match="(?i)policy"):
            await enqueue_feature_update_request(
                migrated_session,
                scope={"type": "feature_ids", "feature_ids": []},
                update_policy=invalid_policy,
            )

    assert await _count_rows(migrated_session, "ops.feature_update_requests") == 0
    assert await _count_rows(migrated_session, "ops.import_jobs") == 0


@pytest.mark.parametrize("operation", ["preview", "enqueue"])
@pytest.mark.parametrize("priority", [-1, 1001, True, 1.5])
async def test_preview_and_enqueue_reject_invalid_priority(
    migrated_session: AsyncSession,
    operation: str,
    priority: Any,
) -> None:
    call = (
        preview_feature_update_request
        if operation == "preview"
        else enqueue_feature_update_request
    )
    with pytest.raises(ValueError, match="priority"):
        await call(
            migrated_session,
            scope={"type": "feature_ids", "feature_ids": []},
            priority=priority,
        )

    assert await _count_rows(migrated_session, "ops.feature_update_requests") == 0
    assert await _count_rows(migrated_session, "ops.import_jobs") == 0


@pytest.mark.parametrize("operation", ["preview", "enqueue"])
async def test_preview_and_enqueue_reject_redundant_direct_filters(
    migrated_session: AsyncSession,
    operation: str,
) -> None:
    call = (
        preview_feature_update_request
        if operation == "preview"
        else enqueue_feature_update_request
    )
    with pytest.raises(ValueError, match="must not repeat"):
        await call(
            migrated_session,
            scope={
                "type": "provider_dataset",
                "provider": "python-mois-api",
                "dataset_key": "mois_license_features_bulk",
            },
            providers=["python-mois-api"],
            dataset_keys=["mois_license_features_bulk"],
        )

    assert await _count_rows(migrated_session, "ops.feature_update_requests") == 0
    assert await _count_rows(migrated_session, "ops.import_jobs") == 0


async def test_preview_and_enqueue_canonicalize_update_policy_none_values(
    migrated_session: AsyncSession,
) -> None:
    raw_policy = {
        "mode": "refresh_existing",
        "include_inactive": True,
        "force_provider_call": False,
        "dedup_after_load": True,
        "consistency_check_after_load": False,
        "prevent_provider_reactivation": None,
    }
    expected_policy = {
        "mode": "refresh_existing",
        "include_inactive": True,
        "force_provider_call": False,
        "dedup_after_load": True,
        "consistency_check_after_load": False,
    }

    preview = await preview_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        update_policy=raw_policy,
    )
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        update_policy=raw_policy,
    )

    assert preview.update_policy == expected_policy
    assert request.update_policy == expected_policy
    job = await _job_row(migrated_session, request.job_id)
    assert _json_obj(job["payload"]) == {}


async def test_enqueue_creates_request_and_import_job(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-mois-api"],
        dataset_keys=["mois_license_features_bulk"],
        update_policy={"mode": "refresh_existing"},
        priority=80,
        operator="local-admin",
        reason="test queue",
    )

    assert isinstance(request, FeatureUpdateRequest)
    assert request.status == "queued"
    assert request.priority == 80
    assert request.job_id is not None
    assert request.matched_scope == {"feature_count": 0, "sigungu_codes": []}
    assert request.generation == 1

    job = await _job_row(migrated_session, request.job_id)
    payload = _json_obj(job["payload"])
    assert job["kind"] == FEATURE_UPDATE_JOB_KIND
    assert job["status"] == "queued"
    assert payload == {}


async def test_generic_job_lifecycle_cannot_claim_or_mutate_feature_update_job(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    generic = await enqueue_unpaired_import_job(
        migrated_session,
        kind="generic-test-job",
    )

    claimed = await claim_next_import_job(migrated_session)
    assert claimed is not None
    assert claimed.job_id == generic.job_id
    assert (await _job_row(migrated_session, request.job_id))["status"] == "queued"

    started = await start_update_request(
        migrated_session,
        request.request_id,
        dagster_run_id="run-generic-feature-update",
        expected_generation=request.generation,
    )
    assert started is not None
    assert await recover_stale_running_jobs(migrated_session, stale_after=None) == 1
    assert (await _job_row(migrated_session, request.job_id))["status"] == "running"

    with pytest.raises(FeatureOperationInvariantConflict):
        await heartbeat_import_job(
            migrated_session,
            request.job_id,
            progress=20,
            current_stage="generic-bypass",
        )
    assert await heartbeat_feature_update_request_job(
        migrated_session,
        request.job_id,
        expected_generation=started.generation,
        owner_dagster_run_id="run-generic-feature-update",
        progress=20,
        current_stage="provider-refresh",
    )
    heartbeat_events = (
        await migrated_session.execute(
            text(
                "SELECT code, stage, payload FROM ops.import_job_events "
                "WHERE job_id = :job_id AND code = 'job.heartbeat'"
            ),
            {"job_id": request.job_id},
        )
    ).mappings().all()
    assert len(heartbeat_events) == 1
    heartbeat_event = heartbeat_events[0]
    assert heartbeat_event["stage"] == "provider-refresh"
    assert _json_obj(heartbeat_event["payload"]) == {
        "status": "running",
        "progress": 20,
    }


async def test_peek_next_update_request_does_not_claim(
    migrated_session: AsyncSession,
) -> None:
    low = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        priority=10,
    )
    high = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        priority=90,
    )
    assert isinstance(low, FeatureUpdateRequest)
    assert isinstance(high, FeatureUpdateRequest)

    peeked = await peek_next_update_request(migrated_session)
    assert peeked is not None
    assert peeked.request_id == high.request_id
    assert peeked.status == "queued"
    assert peeked.job_id is not None
    assert (await _job_row(migrated_session, peeked.job_id))["status"] == "queued"

    peeked_batch = await peek_update_requests(migrated_session, limit=2)
    assert [item.request_id for item in peeked_batch] == [
        high.request_id,
        low.request_id,
    ]
    assert all(item.status == "queued" for item in peeked_batch)


async def test_enqueue_now_raises_when_scope_lock_is_held(
    migrated_engine: AsyncEngine,
    migrated_session: AsyncSession,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    scope = {"type": "feature_ids", "feature_ids": ["feature-1", "feature-2"]}
    lock_key = feature_update_scope_advisory_key(
        scope_type="feature_ids",
        scope=scope,
        providers=["python-a-api"],
        dataset_keys=["dataset-a"],
    )

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as holder,
        holder.begin(),
        advisory_lock(holder, lock_key),
    ):
        with pytest.raises(FeatureUpdateLockBusy) as exc_info:
            await enqueue_feature_update_request(
                migrated_session,
                scope=scope,
                providers=["python-a-api"],
                dataset_keys=["dataset-a"],
                run_mode="now",
            )

    assert exc_info.value.retry_after_seconds == 15
    assert await _count_rows(migrated_session, "ops.feature_update_requests") == 0
    assert await _count_rows(migrated_session, "ops.import_jobs") == 0


async def test_start_and_finish_update_linked_import_job(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        run_mode="now",
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None

    started = await start_update_request(
        migrated_session,
        request.request_id,
        dagster_run_id="run-1",
        expected_generation=request.generation,
    )
    assert started is not None
    assert started.status == "running"
    assert started.dagster_run_id == "run-1"
    job = await _job_row(migrated_session, request.job_id)
    assert job["status"] == "running"
    assert job["current_stage"] == "started"

    done = await finish_update_request(
        migrated_session,
        request.request_id,
        status="done",
        owner_dagster_run_id="run-1",
        expected_generation=started.generation,
    )
    assert done is not None
    assert done.status == "done"
    job = await _job_row(migrated_session, request.job_id)
    assert job["status"] == "done"
    assert job["dagster_run_id"] == "run-1"
    assert job["progress"] == 100
    assert (
        await finish_update_request(
            migrated_session,
            request.request_id,
            status="failed",
            owner_dagster_run_id="run-1",
            expected_generation=started.generation,
        )
        is None
    )


async def test_pre_start_failure_advances_only_matching_queued_generation(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None

    advanced = await advance_update_request_generation_after_pre_start_failure(
        migrated_session,
        request.request_id,
        expected_generation=request.generation,
    )

    assert advanced is not None
    assert advanced.status == "queued"
    assert advanced.dagster_run_id is None
    assert advanced.generation == request.generation + 1
    job_before_stale = await _job_row(migrated_session, request.job_id)
    stale = await advance_update_request_generation_after_pre_start_failure(
        migrated_session,
        request.request_id,
        expected_generation=request.generation,
    )
    stored = await get_update_request(migrated_session, request.request_id)

    assert stale is None
    assert stored == advanced
    assert await _job_row(migrated_session, request.job_id) == job_before_stale


async def test_pre_start_failure_generation_does_not_mutate_other_states(
    migrated_session: AsyncSession,
) -> None:
    running_request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    terminal_request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    marked_request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(running_request, FeatureUpdateRequest)
    assert isinstance(terminal_request, FeatureUpdateRequest)
    assert isinstance(marked_request, FeatureUpdateRequest)

    running = await start_update_request(
        migrated_session,
        running_request.request_id,
        dagster_run_id="run-owner",
        expected_generation=running_request.generation,
    )
    terminal_running = await start_update_request(
        migrated_session,
        terminal_request.request_id,
        dagster_run_id="run-terminal",
        expected_generation=terminal_request.generation,
    )
    assert terminal_running is not None
    terminal = await finish_update_request(
        migrated_session,
        terminal_request.request_id,
        status="failed",
        owner_dagster_run_id="run-terminal",
        expected_generation=terminal_running.generation,
        error_message="terminal fixture",
    )
    scope = await resolve_pipeline_cancellation_scope(
        migrated_session,
        kind="update_request",
        execution_id=marked_request.request_id,
    )
    assert running is not None
    assert terminal is not None
    assert scope is not None
    await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=scope,
        requested_by="admin:test",
        reason="marker fixture",
    )
    marked = await get_update_request(migrated_session, marked_request.request_id)
    assert marked is not None
    marked_job = await _job_row(migrated_session, marked_request.job_id)
    assert marked_job["cancellation_id"] is not None

    for before, generation in (
        (running, running_request.generation),
        (terminal, terminal_request.generation),
        (marked, marked_request.generation),
    ):
        changed = await advance_update_request_generation_after_pre_start_failure(
            migrated_session,
            before.request_id,
            expected_generation=generation,
        )
        after = await get_update_request(migrated_session, before.request_id)
        assert changed is None
        assert after == before


async def test_start_is_generation_and_owner_cas(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    await migrated_session.execute(
        text(
            "UPDATE ops.feature_update_requests "
            "SET generation = generation + 1 "
            "WHERE request_id = :request_id"
        ),
        {"request_id": request.request_id},
    )
    newer = await get_update_request(migrated_session, request.request_id)
    assert newer is not None

    stale_start = await start_update_request(
        migrated_session,
        request.request_id,
        dagster_run_id="run-stale",
        expected_generation=request.generation,
    )
    started = await start_update_request(
        migrated_session,
        request.request_id,
        dagster_run_id="run-owner",
        expected_generation=newer.generation,
    )
    assert stale_start is None
    assert started is not None
    wrong_owner = await start_update_request(
        migrated_session,
        request.request_id,
        dagster_run_id="run-other",
        expected_generation=started.generation,
    )
    stored = await get_update_request(migrated_session, request.request_id)
    job = await _job_row(migrated_session, request.job_id)

    assert wrong_owner is None
    assert stored == started
    assert job["status"] == "running"
    assert job["dagster_run_id"] == "run-owner"

    assert (
        await lock_feature_update_execution_guard(
            migrated_session,
            request.request_id,
            expected_generation=started.generation + 1,
            owner_dagster_run_id="run-owner",
        )
        is None
    )
    assert (
        await lock_feature_update_execution_guard(
            migrated_session,
            request.request_id,
            expected_generation=started.generation,
            owner_dagster_run_id="run-other",
        )
        is None
    )
    owned = await lock_feature_update_execution_guard(
        migrated_session,
        request.request_id,
        expected_generation=started.generation,
        owner_dagster_run_id="run-owner",
    )
    assert owned == started

    assert (
        await set_update_request_matched_scope(
            migrated_session,
            request.request_id,
            matched_scope={"feature_count": 7},
            expected_generation=started.generation + 1,
            owner_dagster_run_id="run-owner",
        )
        is None
    )
    assert (
        await set_update_request_matched_scope(
            migrated_session,
            request.request_id,
            matched_scope={"feature_count": 7},
            expected_generation=started.generation,
            owner_dagster_run_id="run-other",
        )
        is None
    )
    checkpointed = await set_update_request_matched_scope(
        migrated_session,
        request.request_id,
        matched_scope={"feature_count": 7},
        expected_generation=started.generation,
        owner_dagster_run_id="run-owner",
    )
    assert checkpointed is not None
    assert checkpointed.matched_scope == {"feature_count": 7}

    assert not await heartbeat_feature_update_request_job(
        migrated_session,
        request.job_id,
        expected_generation=started.generation + 1,
        owner_dagster_run_id="run-owner",
        progress=50,
    )
    assert not await heartbeat_feature_update_request_job(
        migrated_session,
        request.job_id,
        expected_generation=started.generation,
        owner_dagster_run_id="run-other",
        progress=50,
    )
    assert await heartbeat_feature_update_request_job(
        migrated_session,
        request.job_id,
        expected_generation=started.generation,
        owner_dagster_run_id="run-owner",
        progress=50,
    )
    assert (
        await finish_update_request(
            migrated_session,
            request.request_id,
            status="failed",
            owner_dagster_run_id="run-other",
            expected_generation=started.generation,
        )
        is None
    )
    still_owned = await get_update_request(migrated_session, request.request_id)
    assert still_owned is not None
    assert still_owned.status == "running"
    assert still_owned.dagster_run_id == "run-owner"


async def test_start_rejects_linked_job_owner_mismatch_without_partial_write(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET status = 'running', "
            "dagster_run_id = 'run-other' WHERE job_id = :job_id"
        ),
        {"job_id": request.job_id},
    )

    rejected = await start_update_request(
        migrated_session,
        request.request_id,
        dagster_run_id="run-owner",
        expected_generation=request.generation,
    )

    stored = await get_update_request(migrated_session, request.request_id)
    job = await _job_row(migrated_session, request.job_id)
    assert rejected is None
    assert stored is not None
    assert stored.status == "running"
    assert stored.dagster_run_id == "run-other"
    assert stored.generation == request.generation
    assert job["status"] == "running"
    assert job["dagster_run_id"] == "run-other"


@pytest.mark.parametrize("start_new_generation", [False, True])
async def test_stale_failure_run_cannot_finish_requeued_request_or_job(
    migrated_session: AsyncSession,
    *,
    start_new_generation: bool,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None

    old_generation = await start_update_request(
        migrated_session,
        request.request_id,
        dagster_run_id="run-old",
        expected_generation=request.generation,
    )
    assert old_generation is not None
    requeued = await requeue_update_request_after_lock_contention(
        migrated_session,
        request.request_id,
        expected_generation=old_generation.generation,
        caller_dagster_run_id="run-old",
    )
    assert requeued is not None
    assert requeued.generation == old_generation.generation + 1
    job_after_requeue = await _job_row(migrated_session, request.job_id)
    assert (
        await requeue_update_request_after_lock_contention(
            migrated_session,
            request.request_id,
            expected_generation=old_generation.generation,
            caller_dagster_run_id="run-old",
        )
        is None
    )
    assert await get_update_request(migrated_session, request.request_id) == requeued
    assert await _job_row(migrated_session, request.job_id) == job_after_requeue

    expected_status = "queued"
    expected_run_id: str | None = None
    if start_new_generation:
        new_generation = await start_update_request(
            migrated_session,
            request.request_id,
            dagster_run_id="run-new",
            expected_generation=requeued.generation,
        )
        assert new_generation is not None
        expected_status = "running"
        expected_run_id = "run-new"

    stale_failure = await finish_update_request(
        migrated_session,
        request.request_id,
        status="failed",
        owner_dagster_run_id="run-old",
        expected_generation=old_generation.generation,
        error_message="old run failed after requeue",
    )

    assert stale_failure is None
    stored = await get_update_request(migrated_session, request.request_id)
    assert stored is not None
    assert stored.status == expected_status
    assert stored.dagster_run_id == expected_run_id
    assert stored.error_message is None
    job = await _job_row(migrated_session, request.job_id)
    assert job["status"] == expected_status
    assert job["dagster_run_id"] == expected_run_id
    assert job["error_message"] is None


async def test_finish_invalid_status_raises(migrated_session: AsyncSession) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)
    with pytest.raises(ValueError, match="status must be one of"):
        await finish_update_request(
            migrated_session,
            request.request_id,
            status="running",
            owner_dagster_run_id="run-invalid-status",
            expected_generation=request.generation,
        )


@pytest.mark.parametrize("owner", [None, "", " ", " run-owner", "run-owner "])
async def test_feature_update_lifecycle_rejects_missing_or_untrimmed_owner(
    migrated_session: AsyncSession,
    owner: Any,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )

    with pytest.raises(ValueError, match="trimmed non-empty"):
        await start_update_request(
            migrated_session,
            request.request_id,
            dagster_run_id=owner,
            expected_generation=request.generation,
        )

    stored = await get_update_request(migrated_session, request.request_id)
    assert stored == request


async def test_list_update_requests_uses_keyset_cursor(
    migrated_session: AsyncSession,
) -> None:
    created = [
        await enqueue_feature_update_request(
            migrated_session,
            scope={"type": "feature_ids", "feature_ids": []},
            priority=priority,
        )
        for priority in (10, 20, 30)
    ]
    assert all(isinstance(item, FeatureUpdateRequest) for item in created)

    page1 = await list_update_requests(migrated_session, limit=2)
    assert len(page1.items) == 2
    assert page1.next_cursor is not None

    page2 = await list_update_requests(migrated_session, limit=2, cursor=page1.next_cursor)
    assert len(page2.items) == 1
    assert page2.next_cursor is None

    seen_ids = {item.request_id for item in page1.items + page2.items}
    assert seen_ids == {
        item.request_id for item in created if isinstance(item, FeatureUpdateRequest)
    }

    queued_page = await list_update_requests(migrated_session, status="queued", limit=10)
    assert len(queued_page.items) == 3


async def test_list_update_requests_filters_by_scope_provider_dataset_and_time(
    migrated_session: AsyncSession,
) -> None:
    target = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-a-api"],
        dataset_keys=["dataset-a"],
    )
    other_provider = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-b-api"],
        dataset_keys=["dataset-a"],
    )
    other_scope = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "bbox", "min_lon": 126, "min_lat": 37, "max_lon": 127, "max_lat": 38},
        providers=["python-a-api"],
        dataset_keys=["dataset-b"],
    )
    assert isinstance(target, FeatureUpdateRequest)
    assert isinstance(other_provider, FeatureUpdateRequest)
    assert isinstance(other_scope, FeatureUpdateRequest)

    page = await list_update_requests(
        migrated_session,
        scope_type="feature_ids",
        provider="python-a-api",
        dataset_key="dataset-a",
        created_from=target.created_at,
        created_to=target.created_at,
        limit=10,
    )

    assert [item.request_id for item in page.items] == [target.request_id]

    provider_dataset = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "provider_dataset",
            "provider": "python-c-api",
            "dataset_key": "dataset-c",
        },
        effective_sync_scope="dataset_wide",
    )
    assert isinstance(provider_dataset, FeatureUpdateRequest)

    provider_dataset_page = await list_update_requests(
        migrated_session,
        scope_type="provider_dataset",
        provider="python-c-api",
        dataset_key="dataset-c",
        limit=10,
    )

    assert [item.request_id for item in provider_dataset_page.items] == [
        provider_dataset.request_id
    ]


async def test_provider_dataset_list_filter_uses_typed_and_gin_seed_indexes(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
              job_id, kind, payload, status, provider, dataset_key, sync_scope,
              trigger_kind
            )
            SELECT
              ('51000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              'feature_update_request', '{}'::jsonb, 'done',
              CASE WHEN seed.n <= 200 THEN 'target-provider'
                   ELSE 'direct-provider-' || seed.n::text END,
              CASE WHEN seed.n % 20 = 0 THEN 'target-dataset'
                   ELSE 'direct-dataset-' || seed.n::text END,
              'dataset_wide',
              'update_request'
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
              ('52000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              'feature_update_request', '{}'::jsonb, 'done',
              NULL, NULL, NULL, 'update_request'
            FROM generate_series(1, 4000) AS seed(n)
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_update_requests (
              request_id, scope_type, scope, providers, dataset_keys,
              run_mode, job_id
            )
            SELECT
              ('61000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              'provider_dataset',
              jsonb_build_object(
                'type', 'provider_dataset',
                'provider', CASE WHEN seed.n <= 200 THEN 'target-provider'
                                 ELSE 'direct-provider-' || seed.n::text END,
                'dataset_key', CASE WHEN seed.n % 20 = 0 THEN 'target-dataset'
                                    ELSE 'direct-dataset-' || seed.n::text END
              ),
              '{}'::text[], '{}'::text[], 'queued',
              ('51000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
              ('62000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              'feature_ids', '{"type":"feature_ids","feature_ids":[]}'::jsonb,
              CASE WHEN seed.n <= 200 THEN ARRAY['target-provider']::text[]
                   ELSE ARRAY['array-provider-' || seed.n::text]::text[] END,
              CASE WHEN seed.n % 20 = 0 THEN ARRAY['target-dataset']::text[]
                   ELSE ARRAY['array-dataset-' || seed.n::text]::text[] END,
              'queued',
              ('52000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid
            FROM generate_series(1, 4000) AS seed(n)
            """
        )
    )
    await migrated_session.execute(text("ANALYZE ops.import_jobs"))
    await migrated_session.execute(text("ANALYZE ops.feature_update_requests"))

    plan = (
        await migrated_session.execute(
            text(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                + _LIST_PROVIDER_DATASET_REQUESTS_SQL
            ),
            {
                "status": None,
                "scope_type": None,
                "provider": "target-provider",
                "provider_filter": ["target-provider"],
                "dataset_key": "target-dataset",
                "dataset_key_filter": ["target-dataset"],
                "created_from": None,
                "created_to": None,
                "cursor_created_at": None,
                "cursor_request_id": None,
                "limit_plus_one": 51,
            },
        )
    ).scalar_one()
    nodes = _plan_nodes(plan)
    executed_sequential = [
        node
        for node in nodes
        if node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") in {"import_jobs", "feature_update_requests"}
        and float(node.get("Actual Loops", 0)) > 0
    ]
    assert executed_sequential == []
    used_indexes = {
        str(node["Index Name"])
        for node in nodes
        if node.get("Index Name") is not None
    }
    assert "idx_import_jobs_provider_dataset_created" in used_indexes
    assert "idx_feature_update_providers_gin" in used_indexes
    assert "idx_feature_update_dataset_keys_gin" in used_indexes


async def test_invalid_cursor_raises(migrated_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="invalid feature update request cursor"):
        await list_update_requests(migrated_session, cursor="not-base64")
