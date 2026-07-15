"""``feature_update_repo`` — feature update request lifecycle (ADR-045 T-206b).

검증 범위:
- dry-run은 scope만 해석하고 DB row/import job을 만들지 않는다.
- enqueue는 ``ops.feature_update_requests``와 ``ops.import_jobs``를 같은 transaction에
  생성한다.
- claim/start/finish/cancel은 request와 연결 import job 상태를 함께 갱신한다.
- 목록은 D-10 keyset cursor로 중복 없이 페이지를 넘긴다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.infra.advisory_lock import advisory_lock
from kortravelmap.infra.feature_update_repo import (
    FEATURE_UPDATE_JOB_KIND,
    FEATURE_UPDATE_QUEUE_ADVISORY_KEY,
    FeatureUpdateLockBusy,
    FeatureUpdateQueueLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestPreview,
    advance_update_request_generation_after_pre_start_failure,
    cancel_update_request,
    claim_next_update_request,
    enqueue_feature_update_request,
    feature_update_scope_advisory_key,
    finish_update_request,
    get_update_request,
    list_update_requests,
    peek_next_update_request,
    peek_update_requests,
    requeue_update_request_after_lock_contention,
    start_update_request,
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
    return int(
        (
            await session.execute(text(f"SELECT count(*) FROM {table}"))
        ).scalar_one()
    )


async def _job_row(session: AsyncSession, job_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                SELECT kind, payload, status, progress, current_stage,
                       dagster_run_id, error_message
                FROM ops.import_jobs
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id},
        )
    ).mappings().one()
    return dict(row)


async def test_dry_run_returns_preview_without_writes(
    migrated_session: AsyncSession,
) -> None:
    preview = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-mois-api"],
        dry_run=True,
        operator="local-admin",
    )

    assert isinstance(preview, FeatureUpdateRequestPreview)
    assert preview.scope_type == "feature_ids"
    assert preview.providers == ("python-mois-api",)
    assert preview.matched_scope == {"feature_count": 0, "sigungu_codes": []}
    assert await _count_rows(migrated_session, "ops.feature_update_requests") == 0
    assert await _count_rows(migrated_session, "ops.import_jobs") == 0


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

    job = await _job_row(migrated_session, request.job_id)
    payload = _json_obj(job["payload"])
    assert job["kind"] == FEATURE_UPDATE_JOB_KIND
    assert job["status"] == "queued"
    assert payload["request_id"] == request.request_id
    assert payload["scope_type"] == "feature_ids"
    assert payload["providers"] == ["python-mois-api"]


async def test_claim_uses_priority_and_starts_linked_job(
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

    claimed = await claim_next_update_request(migrated_session)
    assert claimed is not None
    assert claimed.request_id == high.request_id
    assert claimed.status == "running"
    assert claimed.job_id is not None
    assert (await _job_row(migrated_session, claimed.job_id))["status"] == "running"
    assert (
        await _job_row(migrated_session, claimed.job_id)
    )["current_stage"] == "claimed"

    claimed_next = await claim_next_update_request(migrated_session)
    assert claimed_next is not None
    assert claimed_next.request_id == low.request_id
    assert await claim_next_update_request(migrated_session) is None


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

    claimed = await claim_next_update_request(migrated_session)
    assert claimed is not None
    assert claimed.request_id == high.request_id


async def test_claim_raises_when_queue_lock_is_held(
    migrated_engine: AsyncEngine,
    migrated_session: AsyncSession,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as holder,
        holder.begin(),
        advisory_lock(holder, FEATURE_UPDATE_QUEUE_ADVISORY_KEY),
    ):
        with pytest.raises(FeatureUpdateQueueLockBusy):
            await claim_next_update_request(migrated_session)

    still_queued = await get_update_request(migrated_session, request.request_id)
    assert still_queued is not None
    assert still_queued.status == "queued"


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


async def test_start_finish_and_cancel_update_linked_import_job(
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
        migrated_session, request.request_id, dagster_run_id="run-1"
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
        expected_dagster_run_id="run-1",
    )
    assert done is not None
    assert done.status == "done"
    job = await _job_row(migrated_session, request.job_id)
    assert job["status"] == "done"
    assert job["dagster_run_id"] == "run-1"
    assert job["progress"] == 100
    assert await finish_update_request(
        migrated_session, request.request_id, status="failed"
    ) is None

    to_cancel = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(to_cancel, FeatureUpdateRequest)
    assert to_cancel.job_id is not None
    cancelled = await cancel_update_request(
        migrated_session,
        to_cancel.request_id,
        error_message="operator cancelled",
    )
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    job = await _job_row(migrated_session, to_cancel.job_id)
    assert job["status"] == "cancelled"
    assert job["error_message"] == "operator cancelled"


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
        expected_updated_at=request.updated_at,
    )

    assert advanced is not None
    assert advanced.status == "queued"
    assert advanced.dagster_run_id is None
    assert advanced.updated_at > request.updated_at
    job_before_stale = await _job_row(migrated_session, request.job_id)
    stale = await advance_update_request_generation_after_pre_start_failure(
        migrated_session,
        request.request_id,
        expected_updated_at=request.updated_at,
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
        expected_updated_at=running_request.updated_at,
    )
    terminal = await cancel_update_request(
        migrated_session,
        terminal_request.request_id,
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
    assert marked.cancellation_id is not None

    for before, generation in (
        (running, running_request.updated_at),
        (terminal, terminal_request.updated_at),
        (marked, marked_request.updated_at),
    ):
        changed = await advance_update_request_generation_after_pre_start_failure(
            migrated_session,
            before.request_id,
            expected_updated_at=generation,
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
            "SET updated_at = updated_at + INTERVAL '1 second' "
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
        expected_updated_at=request.updated_at,
    )
    started = await start_update_request(
        migrated_session,
        request.request_id,
        dagster_run_id="run-owner",
        expected_updated_at=newer.updated_at,
    )
    assert stale_start is None
    assert started is not None
    wrong_owner = await start_update_request(
        migrated_session,
        request.request_id,
        dagster_run_id="run-other",
    )
    stored = await get_update_request(migrated_session, request.request_id)
    job = await _job_row(migrated_session, request.job_id)

    assert wrong_owner is None
    assert stored == started
    assert job["status"] == "running"
    assert job["dagster_run_id"] == "run-owner"


async def test_start_rolls_back_request_when_linked_job_owner_mismatches(
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

    with pytest.raises(RuntimeError, match="import job was not"):
        await start_update_request(
            migrated_session,
            request.request_id,
            dagster_run_id="run-owner",
            expected_updated_at=request.updated_at,
        )

    stored = await get_update_request(migrated_session, request.request_id)
    job = await _job_row(migrated_session, request.job_id)
    assert stored == request
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
    )
    assert old_generation is not None
    requeued = await requeue_update_request_after_lock_contention(
        migrated_session,
        request.request_id,
    )
    assert requeued is not None

    expected_status = "queued"
    expected_run_id: str | None = None
    if start_new_generation:
        new_generation = await start_update_request(
            migrated_session,
            request.request_id,
            dagster_run_id="run-new",
        )
        assert new_generation is not None
        expected_status = "running"
        expected_run_id = "run-new"

    stale_failure = await finish_update_request(
        migrated_session,
        request.request_id,
        status="failed",
        expected_dagster_run_id="run-old",
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
            migrated_session, request.request_id, status="running"
        )


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

    page2 = await list_update_requests(
        migrated_session, limit=2, cursor=page1.next_cursor
    )
    assert len(page2.items) == 1
    assert page2.next_cursor is None

    seen_ids = {item.request_id for item in page1.items + page2.items}
    assert seen_ids == {
        item.request_id for item in created if isinstance(item, FeatureUpdateRequest)
    }

    queued_page = await list_update_requests(
        migrated_session, status="queued", limit=10
    )
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


async def test_invalid_cursor_raises(migrated_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="invalid feature update request cursor"):
        await list_update_requests(migrated_session, cursor="not-base64")
