"""큐 요청의 일시 실패 재발행·상한·실패 원인 기록 (감사 2026-11-23 §1.3 P1·§4 #15, alembic 456).

- 일시 DB 실패(lock timeout 등)는 executor가 종결하지 않고 넘긴다 — 새 연결로 backoff 재발행.
- 시작 전 실패(launch 실패)의 재발행은 횟수 상한과 backoff를 갖고, 상한을 넘으면 ``failed``.
- 결정적 실패의 종결은 언제나 import job event에 분류·원인·실패 단계·Dagster run id를 남긴다.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import kortravelmap.client as client_mod
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.cache_target_stream import make_active_cache_target_source
from kortravelmap.infra.cache_target_event_repo import (
    capture_cache_target_refresh_members_by_keys,
)
from kortravelmap.infra.cache_target_stream_repo import apply_cache_target_source
from kortravelmap.infra.failure_summary import summarize_failure
from kortravelmap.infra.feature_update_executor import (
    FEATURE_UPDATE_EXECUTION_FAILED_EVENT_CODE,
    FEATURE_UPDATE_RETRIES_EXHAUSTED_EVENT_CODE,
    FEATURE_UPDATE_RETRY_SCHEDULED_EVENT_CODE,
    FEATURE_UPDATE_RUN_FAILED_EVENT_CODE,
    FeatureUpdateTransientFailure,
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
)
from kortravelmap.infra.feature_update_repo import (
    FEATURE_UPDATE_MAX_RETRIES,
    FeatureUpdateRequest,
    enqueue_feature_update_request,
    fail_update_request_after_retries,
    get_update_request,
    peek_update_requests,
    reschedule_update_request_after_failure,
    start_update_request,
)
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from kortravelmap.infra.transaction_limits import transaction_deadline
from tests.integration._db_cleanup import truncate_committed_test_rows

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_TRUNCATE_SQL = """
TRUNCATE
    ops.feature_update_requests,
    ops.import_job_events,
    ops.import_jobs,
    ops.poi_cache_target_feature_links,
    ops.poi_cache_targets
RESTART IDENTITY CASCADE
"""

_MEMBERSHIP_SQL = """
WITH dataset AS (
    INSERT INTO provider_sync.provider_datasets (
        provider, dataset_key, display_name, source_kind, is_active, capabilities
    )
    SELECT :provider, :dataset_key, :provider, 'system', true,
           jsonb_build_object('schema_version', 1,
                              'produces', '[]'::jsonb,
                              'extensions', '{}'::jsonb)
    ON CONFLICT (provider, dataset_key) DO UPDATE SET display_name = EXCLUDED.display_name
    RETURNING provider_dataset_id
),
operation AS (
    INSERT INTO provider_sync.provider_dataset_operations (
        provider_dataset_id, operation_key, operation_kind, is_enabled, config
    )
    SELECT provider_dataset_id, 'feature_update', 'refresh', true, '{}'::jsonb FROM dataset
    ON CONFLICT (provider_dataset_id, operation_key, operation_kind) DO NOTHING
    RETURNING provider_dataset_id
)
SELECT provider_dataset_id FROM dataset
"""

_SCOPE_SQL = """
INSERT INTO provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id, sync_scope, operation_key, operation_kind
) VALUES (:provider_dataset_id, 'dataset_wide', 'feature_update', 'refresh')
ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO NOTHING
"""

_EVENTS_SQL = """
SELECT level, code, message, payload
FROM ops.import_job_events
WHERE job_id = CAST(:job_id AS uuid)
ORDER BY occurred_at, event_id
"""


class _LockTimeout(Exception):
    """asyncpg ``LockNotAvailableError``의 모양 — SQLSTATE만 본다."""

    sqlstate = "55P03"


@pytest.fixture(autouse=True)
async def _cleanup(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    yield
    async with AsyncSession(migrated_engine) as session, session.begin():
        await truncate_committed_test_rows(session, _TRUNCATE_SQL)


async def _membership(session: AsyncSession, dataset_key: str) -> ImportJobDatasetTarget:
    provider_dataset_id = int(
        (
            await session.execute(
                text(_MEMBERSHIP_SQL),
                {"provider": "python-retry-api", "dataset_key": dataset_key},
            )
        ).scalar_one()
    )
    await session.execute(text(_SCOPE_SQL), {"provider_dataset_id": provider_dataset_id})
    return ImportJobDatasetTarget(
        provider_dataset_id=provider_dataset_id,
        sync_scope="dataset_wide",
        operation_key="feature_update",
    )


async def _enqueue(engine: AsyncEngine, dataset_key: str) -> FeatureUpdateRequest:
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        membership = await _membership(session, dataset_key)
        request = await enqueue_feature_update_request(
            session,
            scope={
                "type": "provider_dataset",
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
            },
            dataset_memberships=[membership],
        )
    assert isinstance(request, FeatureUpdateRequest)
    return request


async def _events(engine: AsyncEngine, job_id: str) -> list[dict[str, Any]]:
    async with AsyncSession(engine) as session:
        rows = (await session.execute(text(_EVENTS_SQL), {"job_id": job_id})).all()
    events = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
        events.append(
            {"level": row.level, "code": row.code, "message": row.message, "payload": payload}
        )
    return events


async def _db_now(session: AsyncSession) -> Any:
    return (await session.execute(text("SELECT now()"))).scalar_one()


# ---------------------------------------------------------------- repo: 재발행·상한


async def test_reschedule_backs_off_and_hides_the_request_until_due(
    migrated_engine: AsyncEngine,
) -> None:
    request = await _enqueue(migrated_engine, "reschedule-backoff")
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session, session.begin():
        now = await _db_now(session)
        rescheduled = await reschedule_update_request_after_failure(
            session,
            request.request_id,
            expected_generation=request.generation,
            owner_dagster_run_id="run-launch-failed",
        )
        assert rescheduled is not None
        assert rescheduled.status == "queued"
        assert rescheduled.dagster_run_id is None
        assert rescheduled.generation == request.generation + 1
        assert rescheduled.retry_count == 1
        assert rescheduled.next_dispatch_at is not None
        # 첫 재발행은 기준 60초 × [0.5, 1.0) jitter.
        wait = rescheduled.next_dispatch_at - now
        assert timedelta(seconds=29) <= wait <= timedelta(seconds=61)
        # 그 전에는 큐 sensor가 집지 않는다.
        assert [item.request_id for item in await peek_update_requests(session)] == []
        await session.execute(
            text(
                "UPDATE ops.feature_update_requests SET next_dispatch_at = now() "
                "WHERE request_id = CAST(:request_id AS uuid)"
            ),
            {"request_id": request.request_id},
        )
        assert [item.request_id for item in await peek_update_requests(session)] == [
            request.request_id
        ]


async def test_reschedule_respects_the_cap_and_then_fails_the_queued_request(
    migrated_engine: AsyncEngine,
) -> None:
    request = await _enqueue(migrated_engine, "reschedule-cap")
    generation = request.generation
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session, session.begin():
        for attempt in range(1, FEATURE_UPDATE_MAX_RETRIES + 1):
            rescheduled = await reschedule_update_request_after_failure(
                session,
                request.request_id,
                expected_generation=generation,
                owner_dagster_run_id=f"run-{attempt}",
            )
            assert rescheduled is not None
            assert rescheduled.retry_count == attempt
            generation = rescheduled.generation
        exhausted = await reschedule_update_request_after_failure(
            session,
            request.request_id,
            expected_generation=generation,
            owner_dagster_run_id="run-final",
        )
        assert exhausted is None
        failed = await fail_update_request_after_retries(
            session,
            request.request_id,
            expected_generation=generation,
            owner_dagster_run_id="run-final",
            error_message="재발행 상한",
        )
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error_message == "재발행 상한"
        assert failed.finished_at is not None


async def test_reschedule_running_only_for_its_owner_and_only_when_allowed(
    migrated_engine: AsyncEngine,
) -> None:
    request = await _enqueue(migrated_engine, "reschedule-running")
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session, session.begin():
        started = await start_update_request(
            session,
            request.request_id,
            dagster_run_id="run-owner",
            expected_generation=request.generation,
        )
        assert started is not None
        for owner, include_running in (("run-other", True), ("run-owner", False)):
            assert (
                await reschedule_update_request_after_failure(
                    session,
                    request.request_id,
                    expected_generation=started.generation,
                    owner_dagster_run_id=owner,
                    include_running=include_running,
                )
                is None
            )
        rescheduled = await reschedule_update_request_after_failure(
            session,
            request.request_id,
            expected_generation=started.generation,
            owner_dagster_run_id="run-owner",
        )
        assert rescheduled is not None
        assert rescheduled.status == "queued"
        assert rescheduled.started_at is None
        stored = await get_update_request(session, request.request_id)
        assert stored == rescheduled


# ---------------------------------------------------------------- executor + client


async def test_transient_db_failure_is_handed_back_unterminated_then_rescheduled(
    migrated_engine: AsyncEngine,
) -> None:
    request = await _enqueue(migrated_engine, "executor-lock-timeout")
    client = AsyncKorTravelMapClient(migrated_engine)

    async def runner(
        _session: AsyncSession, _scope: ProviderDatasetRefreshScope
    ) -> ProviderDatasetRefreshResult:
        raise _LockTimeout("canceling statement due to lock timeout")

    with pytest.raises(FeatureUpdateTransientFailure) as raised:
        await client.execute_feature_update_request(
            request.request_id, runner=runner, dagster_run_id="run-lock"
        )
    failure = raised.value
    assert failure.summary.db_failure == "lock_timeout"
    assert failure.stage is not None
    assert failure.stage.startswith("refreshing:")

    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        stored = await get_update_request(session, request.request_id)
    assert stored is not None
    assert stored.status == "running"  # 종결하지 않았다
    assert stored.dagster_run_id == "run-lock"

    outcome = await client.reschedule_update_request_after_failure(
        request.request_id,
        owner_dagster_run_id="run-lock",
        expected_request_generation=stored.generation,
        failure=failure.summary,
        stage=failure.stage,
    )
    assert outcome is not None
    assert outcome.rescheduled is True
    assert outcome.request.status == "queued"
    assert outcome.request.retry_count == 1

    events = [
        event
        for event in await _events(migrated_engine, request.job_id)
        if event["code"] == FEATURE_UPDATE_RETRY_SCHEDULED_EVENT_CODE
    ]
    assert len(events) == 1
    [event] = events
    assert event["level"] == "warning"
    assert event["payload"]["failure_class"] == "transient_db"
    assert event["payload"]["db_failure"] == "lock_timeout"
    assert event["payload"]["dagster_run_id"] == "run-lock"
    assert event["payload"]["retry_count"] == 1
    assert event["payload"]["stage"].startswith("refreshing:")
    assert "lock timeout" in event["message"]


async def test_deterministic_failure_records_a_terminal_event_with_the_cause(
    migrated_engine: AsyncEngine,
) -> None:
    request = await _enqueue(migrated_engine, "executor-deterministic")
    client = AsyncKorTravelMapClient(migrated_engine)

    class _QuotaError(Exception):
        failure_kind = "quota"

    async def runner(
        _session: AsyncSession, _scope: ProviderDatasetRefreshScope
    ) -> ProviderDatasetRefreshResult:
        try:
            raise _QuotaError("LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR serviceKey=SECRET")
        except _QuotaError as exc:
            raise RuntimeError("provider refresh asset execution failed") from exc

    result = await client.execute_feature_update_request(
        request.request_id, runner=runner, dagster_run_id="run-quota"
    )

    assert result is not None
    assert result.status == "failed"
    assert result.error_message is not None
    assert result.error_message.startswith(
        "RuntimeError: provider refresh asset execution failed ← 원인 _QuotaError:"
    )
    assert "SECRET" not in result.error_message
    events = [
        event
        for event in await _events(migrated_engine, request.job_id)
        if event["code"] == FEATURE_UPDATE_EXECUTION_FAILED_EVENT_CODE
    ]
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["status"] == "failed"
    assert payload["failure_class"] == "execution"
    assert payload["failure_kind"] == "quota"
    assert payload["dagster_run_id"] == "run-quota"
    assert payload["stage"].startswith("refreshing:")
    assert "SECRET" not in json.dumps(payload)


async def test_failure_sensor_path_backs_off_pre_start_failures_up_to_the_cap(
    migrated_engine: AsyncEngine,
) -> None:
    """launch 실패(시작 전)는 상한까지 backoff 재발행, 그다음 ``failed``와 소진 event."""

    request = await _enqueue(migrated_engine, "sensor-pre-start")
    client = AsyncKorTravelMapClient(migrated_engine)
    generation = request.generation
    for attempt in range(1, FEATURE_UPDATE_MAX_RETRIES + 1):
        retried = await client.fail_update_request(
            request.request_id,
            owner_dagster_run_id=f"run-launch-{attempt}",
            expected_request_generation=generation,
            error_message="Dagster feature update worker failed — OSError: Too many open files",
            failure_payload={"source": "dagster_run_failure", "error_type": "OSError"},
        )
        assert retried is not None
        assert retried.status == "queued"
        assert retried.retry_count == attempt
        assert retried.next_dispatch_at is not None
        generation = retried.generation

    final = await client.fail_update_request(
        request.request_id,
        owner_dagster_run_id="run-launch-final",
        expected_request_generation=generation,
        error_message="Dagster feature update worker failed — OSError: Too many open files",
        failure_payload={"source": "dagster_run_failure"},
    )
    assert final is not None
    assert final.status == "failed"
    assert final.error_message is not None
    assert final.error_message.startswith(
        f"재발행 상한 {FEATURE_UPDATE_MAX_RETRIES}회 소진(누적 {FEATURE_UPDATE_MAX_RETRIES}회)"
    )
    codes = [event["code"] for event in await _events(migrated_engine, request.job_id)]
    assert codes.count(FEATURE_UPDATE_RETRY_SCHEDULED_EVENT_CODE) == FEATURE_UPDATE_MAX_RETRIES
    assert codes.count(FEATURE_UPDATE_RETRIES_EXHAUSTED_EVENT_CODE) == 1


async def _claim(engine: AsyncEngine, request_id: str, *, generation: int, run_id: str) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        started = await start_update_request(
            session, request_id, dagster_run_id=run_id, expected_generation=generation
        )
    assert started is not None
    assert started.status == "running"


async def test_failure_sensor_path_reschedules_a_claimed_transient_failure_up_to_its_cap(
    migrated_engine: AsyncEngine,
) -> None:
    """claim 뒤 일시 DB 실패 — op가 재발행을 기록하지 못하고 죽은 run — 는 failure sensor가
    재발행한다. 상한은 sensor가 실패 단계로 고른 값(provider 갱신 단계 2회)이다(#1544 리뷰).

    종전에는 이 분기가 기본 상한 5회를 써서 쿼터가 좁은 상류를 세 번 더 처음부터 불렀다.
    """
    request = await _enqueue(migrated_engine, "sensor-claimed-transient")
    client = AsyncKorTravelMapClient(migrated_engine)
    payload = {
        "source": "dagster_run_failure",
        "failure_class": "transient_db",
        "stage": "refreshing:1:dataset_wide",
    }
    generation = request.generation
    for attempt in (1, 2):
        run_id = f"run-claimed-{attempt}"
        await _claim(migrated_engine, request.request_id, generation=generation, run_id=run_id)
        retried = await client.fail_update_request(
            request.request_id,
            owner_dagster_run_id=run_id,
            expected_request_generation=generation,
            error_message="Dagster feature update worker failed — Failure: 재발행 기록 실패",
            failure_payload=payload,
            max_retries=2,
        )
        assert retried is not None
        assert retried.status == "queued"
        assert retried.dagster_run_id is None
        assert retried.retry_count == attempt
        assert retried.next_dispatch_at is not None
        generation = retried.generation

    await _claim(migrated_engine, request.request_id, generation=generation, run_id="run-final")
    final = await client.fail_update_request(
        request.request_id,
        owner_dagster_run_id="run-final",
        expected_request_generation=generation,
        error_message="Dagster feature update worker failed — Failure: 재발행 기록 실패",
        failure_payload=payload,
        max_retries=2,
    )
    assert final is not None
    assert final.status == "failed"
    assert final.retry_count == 2
    assert final.error_message is not None
    assert final.error_message.startswith("재발행 상한 2회 소진(누적 2회)")

    events = await _events(migrated_engine, request.job_id)
    scheduled = [e for e in events if e["code"] == FEATURE_UPDATE_RETRY_SCHEDULED_EVENT_CODE]
    exhausted = [e for e in events if e["code"] == FEATURE_UPDATE_RETRIES_EXHAUSTED_EVENT_CODE]
    assert [event["payload"]["retry_count"] for event in scheduled] == [1, 2]
    assert {event["payload"]["max_retries"] for event in scheduled} == {2}
    assert {event["payload"]["stage"] for event in scheduled} == {"refreshing:1:dataset_wide"}
    assert len(exhausted) == 1
    assert exhausted[0]["payload"]["dagster_run_id"] == "run-final"
    assert exhausted[0]["payload"]["max_retries"] == 2


async def test_provider_stage_cap_counts_launch_failure_retries_too(
    migrated_engine: AsyncEngine,
) -> None:
    """provider 단계 상한(2회)은 누적 ``retry_count``에 건다(#1551 결정).

    launch 실패 재발행도 센다. launch 실패로 3회 재발행된 요청은 provider 단계 첫 일시 실패에서
    재발행 없이 닫힌다. 종결 메시지는 상한과 실제 누적을 함께 적는다 — 종전에는 ``재발행 2회
    소진``이라 적어 실제 재발행 수(3회)와 어긋났다.
    """
    request = await _enqueue(migrated_engine, "provider-cap-cumulative")
    client = AsyncKorTravelMapClient(migrated_engine)
    generation = request.generation
    for attempt in (1, 2, 3):
        retried = await client.fail_update_request(
            request.request_id,
            owner_dagster_run_id=f"run-launch-{attempt}",
            expected_request_generation=generation,
            error_message="Dagster feature update worker failed — launch failed",
            failure_payload={"source": "dagster_run_failure"},
        )
        assert retried is not None
        assert retried.status == "queued"
        generation = retried.generation

    await _claim(migrated_engine, request.request_id, generation=generation, run_id="run-provider")
    outcome = await client.reschedule_update_request_after_failure(
        request.request_id,
        owner_dagster_run_id="run-provider",
        expected_request_generation=generation,
        failure=summarize_failure(_LockTimeout("lock timeout")),
        stage="refreshing:1:dataset_wide",
        max_retries=2,
    )

    assert outcome is not None
    assert outcome.rescheduled is False
    assert outcome.request.status == "failed"
    assert outcome.request.retry_count == 3
    assert outcome.request.error_message is not None
    assert outcome.request.error_message.startswith("재발행 상한 2회 소진(누적 3회): ")


async def _enqueue_cache_target_request(engine: AsyncEngine, prefix: str) -> FeatureUpdateRequest:
    """활성 target 하나와 갱신을 끈 target 하나를 가리키는 cache target key 요청."""
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        membership = await _membership(session, f"{prefix}-dataset")
        for key, enabled in ((f"{prefix}-active", True), (f"{prefix}-disabled", False)):
            await upsert_poi_cache_target(
                session,
                external_system="external-app",
                target_key=key,
                lon=126.9780,
                lat=37.5665,
                radius_km=1.0,
                update_enabled=enabled,
            )
        request = await enqueue_feature_update_request(
            session,
            scope={
                "type": "cache_target_keys",
                "external_system": "external-app",
                "target_keys": [f"{prefix}-active", f"{prefix}-disabled"],
            },
            dataset_memberships=[membership],
        )
    assert isinstance(request, FeatureUpdateRequest)
    return request


async def _target_failed_at(engine: AsyncEngine, prefix: str) -> dict[str, Any]:
    async with AsyncSession(engine) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT target_key, last_failed_at FROM ops.poi_cache_targets "
                    "WHERE target_key LIKE :prefix ORDER BY target_key"
                ),
                {"prefix": f"{prefix}-%"},
            )
        ).all()
    return {str(row.target_key): row.last_failed_at for row in rows}


@pytest.mark.parametrize("closure", ["retries_exhausted", "terminalization_failed", "run_failed"])
async def test_closures_outside_the_executor_stamp_the_cache_targets_failed_at(
    migrated_engine: AsyncEngine,
    closure: str,
) -> None:
    """재발행 소진·``FeatureUpdateTerminalizationFailed``·RUN_FAILED 종결도 target 실패 시각을
    찍는다 — executor 종결처럼 활성 target만(#1544 리뷰)."""
    prefix = f"stamp-{closure.replace('_', '-')}"
    request = await _enqueue_cache_target_request(migrated_engine, prefix)
    client = AsyncKorTravelMapClient(migrated_engine)
    await _claim(migrated_engine, request.request_id, generation=request.generation, run_id="run-1")

    if closure == "retries_exhausted":
        outcome = await client.reschedule_update_request_after_failure(
            request.request_id,
            owner_dagster_run_id="run-1",
            expected_request_generation=request.generation,
            failure=summarize_failure(_LockTimeout("lock timeout")),
            max_retries=0,
        )
        assert outcome is not None
        assert outcome.rescheduled is False
        closed = outcome.request
    elif closure == "terminalization_failed":
        failed = await client.fail_update_request_after_failure(
            request.request_id,
            owner_dagster_run_id="run-1",
            expected_request_generation=request.generation,
            failure=summarize_failure(RuntimeError("provider exploded")),
            stage="refreshing:1:dataset_wide",
        )
        assert failed is not None
        closed = failed
    else:
        failed = await client.fail_update_request(
            request.request_id,
            owner_dagster_run_id="run-1",
            expected_request_generation=request.generation,
            error_message="Dagster feature update worker failed — run killed",
            failure_payload={"source": "dagster_run_failure"},
        )
        assert failed is not None
        closed = failed
    assert closed.status == "failed"

    stamps = await _target_failed_at(migrated_engine, prefix)
    assert stamps[f"{prefix}-active"] is not None
    assert stamps[f"{prefix}-disabled"] is None


_RELAY_TARGET_KEY = "relay-target"


async def _enqueue_relay_member_request(engine: AsyncEngine, system: str) -> FeatureUpdateRequest:
    """relay member를 캡처한 cache target key 요청 — 실행 claim처럼 source tuple을 고정한다.

    ``enqueue_feature_update_request``만으로는 member가 없어 relay ``failed`` 단계가 아무것도 쓰지
    않고 끝난다(stream·member가 없으면 곧바로 돌아온다) — 그런 요청으로는 relay 단언이 빈 성공이다
    (#1551 리뷰). stream·source head를 만들고 member를 캡처한다.
    """
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        membership = await _membership(session, f"{system}-dataset")
        applied = await apply_cache_target_source(
            session,
            consumer_id=f"{system}-consumer",
            source_event_id=str(uuid4()),
            idempotency_key=str(uuid4()),
            external_system=system,
            target_key=_RELAY_TARGET_KEY,
            restore_epoch=1,
            source_generation=1,
            source=make_active_cache_target_source(
                lon="126.978", lat="37.5665", radius_km="1", update_enabled=True
            ),
            occurred_at=datetime(2026, 11, 24, 1, tzinfo=UTC),
            create_only=True,
        )
        assert applied.target is not None
        request = await enqueue_feature_update_request(
            session,
            scope={
                "type": "cache_target_keys",
                "external_system": system,
                "target_keys": [_RELAY_TARGET_KEY],
            },
            dataset_memberships=[membership],
        )
        members = await capture_cache_target_refresh_members_by_keys(
            session,
            request_id=request.request_id,
            external_system=system,
            target_keys=[_RELAY_TARGET_KEY],
        )
        assert [member.target_key for member in members] == [_RELAY_TARGET_KEY]
    return request


async def _relay_statuses(engine: AsyncEngine, request_id: str) -> list[tuple[str, str | None]]:
    """이 요청의 PinVi relay status event(outbox) — ``(status, error_code)`` 순서대로."""
    async with AsyncSession(engine) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload ->> 'status' AS status, payload ->> 'error_code' AS error_code "
                    "FROM ops.poi_cache_target_outbox_events "
                    "WHERE refresh_request_id = CAST(:request_id AS uuid) "
                    "  AND event_type = 'refresh_request.status_changed' "
                    "ORDER BY relay_order"
                ),
                {"request_id": request_id},
            )
        ).all()
    return [(str(row.status), row.error_code) for row in rows]


async def _relay_target_failed_at(engine: AsyncEngine, system: str) -> Any:
    async with AsyncSession(engine) as session:
        return (
            await session.execute(
                text(
                    "SELECT last_failed_at FROM ops.poi_cache_targets "
                    "WHERE external_system = :system AND target_key = :key"
                ),
                {"system": system, "key": _RELAY_TARGET_KEY},
            )
        ).scalar_one()


async def test_failure_followups_survive_an_import_job_event_failure(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """relay ``failed``·target 실패 시각은 import job event와 다른 transaction이다.

    종전에는 relay ``failed``가 import job event INSERT와 한 transaction이라, event 쪽이 실패하면
    상태만 ``failed``로 commit되고 relay는 영구 유실됐다(#1544 리뷰). member를 캡처한 요청으로
    outbox에 ``failed`` 행이 실제로 commit됐는지 본다 — member가 없으면 relay 단계가 아무것도
    쓰지 않아 이 단언이 빈 성공이 된다(#1551 리뷰).
    """
    system = "retry-relay-split"
    request = await _enqueue_relay_member_request(migrated_engine, system)
    client = AsyncKorTravelMapClient(migrated_engine)
    await _claim(migrated_engine, request.request_id, generation=request.generation, run_id="run-1")

    async def broken_event(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("import job event insert rejected")

    monkeypatch.setattr(client_mod, "record_update_request_failure_events", broken_event)
    monkeypatch.setattr(client_mod, "_FEATURE_UPDATE_FOLLOWUP_RETRY_DELAY_SECONDS", 0.0)

    failed = await client.fail_update_request(
        request.request_id,
        owner_dagster_run_id="run-1",
        expected_request_generation=request.generation,
        error_message="Dagster feature update worker failed — run killed",
        failure_payload={"source": "dagster_run_failure"},
    )

    assert failed is not None
    assert failed.status == "failed"
    assert await _relay_statuses(migrated_engine, request.request_id) == [
        ("failed", FEATURE_UPDATE_RUN_FAILED_EVENT_CODE)
    ]
    assert await _relay_target_failed_at(migrated_engine, system) is not None
    codes = [event["code"] for event in await _events(migrated_engine, request.job_id)]
    assert FEATURE_UPDATE_RUN_FAILED_EVENT_CODE not in codes


@pytest.mark.parametrize(
    ("cutoff", "attempt_seconds", "min_attempt_seconds"),
    [
        # 서버 쪽: 시도 마감 2초 → statement_timeout 바닥값 1초가 head 대기를 끊는다.
        ("server", 2.0, 1.0),
        # client 쪽: 시도 마감(0.8초)이 statement_timeout(1초)보다 먼저 온다 — asyncio.timeout이
        # 끊고, 같은 session으로 다음 단계가 이어져야 한다.
        ("client", 0.8, 0.5),
    ],
)
async def test_relay_followup_is_bounded_after_the_stream_helper_clears_lock_timeout(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    cutoff: str,
    attempt_seconds: float,
    min_attempt_seconds: float,
) -> None:
    """relay 단계의 source head 대기는 ``lock_timeout``으로 묶이지 않는다 — 시도 마감이 끊는다.

    relay stream lock helper(``lock_stream_row_or_conflict``)는 stream lock을 잡은 뒤 그
    transaction의 ``lock_timeout``을 0(무제한)으로 되돌린다. 그 뒤의 head ``FOR UPDATE``는 다른
    transaction이 head를 쥐고 있으면 끝없이 기다린다. 시도마다 건 ``statement_timeout``과
    ``asyncio.timeout``이 그 대기를 끊고, 다음 단계(target 실패 시각·import job event)는 그대로
    쓴다(#1551 리뷰).
    """
    system = f"retry-relay-head-{cutoff}"
    request = await _enqueue_relay_member_request(migrated_engine, system)
    client = AsyncKorTravelMapClient(migrated_engine)
    await _claim(migrated_engine, request.request_id, generation=request.generation, run_id="run-1")
    monkeypatch.setattr(client_mod, "_FEATURE_UPDATE_FOLLOWUP_ATTEMPT_SECONDS", attempt_seconds)
    monkeypatch.setattr(
        client_mod, "_FEATURE_UPDATE_FOLLOWUP_MIN_ATTEMPT_SECONDS", min_attempt_seconds
    )
    monkeypatch.setattr(client_mod, "_FEATURE_UPDATE_FOLLOWUP_RETRY_DELAY_SECONDS", 0.0)

    async with AsyncSession(migrated_engine) as holder, holder.begin():
        await holder.execute(
            text(
                "SELECT target_id FROM ops.poi_cache_target_source_heads "
                "WHERE external_system = :system AND target_key = :key FOR UPDATE"
            ),
            {"system": system, "key": _RELAY_TARGET_KEY},
        )
        started_at = time.monotonic()
        failed = await asyncio.wait_for(
            client.fail_update_request(
                request.request_id,
                owner_dagster_run_id="run-1",
                expected_request_generation=request.generation,
                error_message="Dagster feature update worker failed — run killed",
                failure_payload={"source": "dagster_run_failure"},
            ),
            timeout=30,
        )
        elapsed = time.monotonic() - started_at

    assert failed is not None
    assert failed.status == "failed"
    # relay 두 시도(각 attempt_seconds 이하) + 나머지 두 단계.
    assert elapsed < 2 * attempt_seconds + 3
    # head를 쥔 동안 relay는 쓰지 못했다 — 상태 전이는 이미 commit돼 있다.
    assert await _relay_statuses(migrated_engine, request.request_id) == []
    assert await _relay_target_failed_at(migrated_engine, system) is not None
    codes = [event["code"] for event in await _events(migrated_engine, request.job_id)]
    assert codes.count(FEATURE_UPDATE_RUN_FAILED_EVENT_CODE) == 1


async def test_failure_sensor_deadline_bounds_the_state_transition_lock_wait(
    migrated_engine: AsyncEngine,
) -> None:
    """failure sensor가 건 마감(ADR-112)은 상태 전이 transaction에도 서버 쪽 상한을 건다.

    종전에는 상태 전이가 엔진 기본 ``lock_timeout``으로 돌아, request·job 행을 다른 transaction이
    쥐면 행마다 30초(Dagster 엔진)씩 기다렸다(#1551 리뷰). 마감 6초면 ``lock_timeout``은
    min(5초, 6 − 4초) = 2초다.
    """
    request = await _enqueue(migrated_engine, "sensor-deadline-transition")
    client = AsyncKorTravelMapClient(migrated_engine)
    await _claim(migrated_engine, request.request_id, generation=request.generation, run_id="run-1")

    async with AsyncSession(migrated_engine) as holder, holder.begin():
        await holder.execute(
            text(
                "SELECT request_id FROM ops.feature_update_requests "
                "WHERE request_id = CAST(:request_id AS uuid) FOR UPDATE"
            ),
            {"request_id": request.request_id},
        )
        started_at = time.monotonic()
        with (
            transaction_deadline(time.monotonic() + 6.0),
            pytest.raises(DBAPIError) as raised,
        ):
            await asyncio.wait_for(
                client.fail_update_request(
                    request.request_id,
                    owner_dagster_run_id="run-1",
                    expected_request_generation=request.generation,
                    error_message="Dagster feature update worker failed — run killed",
                    failure_payload={"source": "dagster_run_failure"},
                ),
                timeout=30,
            )
        elapsed = time.monotonic() - started_at

    assert getattr(raised.value.orig, "sqlstate", None) == "55P03"
    assert elapsed < 5
    async with AsyncSession(migrated_engine) as session:
        stored = await get_update_request(session, request.request_id)
    assert stored is not None
    assert stored.status == "running"


async def test_failure_followups_are_bounded_while_a_lock_is_held(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """상태 전이 뒤 후처리는 lock을 끝없이 기다리지 않는다 — 시도마다 마감에서 유도한 상한.

    target 행을 다른 transaction이 쥔 동안 RUN_FAILED 종결을 반영한다. target 실패 시각 단계는
    ``lock_timeout``(시도 마감 1.5초 → 바닥값 0.5초)에서 포기하고, 다음 단계(import job event)는
    그대로 쓴다. 상한이 없으면 이 호출은
    lock이 풀릴 때까지 기다린다(#1544 리뷰).
    """
    prefix = "followup-bounded"
    request = await _enqueue_cache_target_request(migrated_engine, prefix)
    client = AsyncKorTravelMapClient(migrated_engine)
    await _claim(migrated_engine, request.request_id, generation=request.generation, run_id="run-1")
    monkeypatch.setattr(client_mod, "_FEATURE_UPDATE_FOLLOWUP_ATTEMPT_SECONDS", 1.5)
    monkeypatch.setattr(client_mod, "_FEATURE_UPDATE_FOLLOWUP_RETRY_DELAY_SECONDS", 0.0)

    async with AsyncSession(migrated_engine) as holder, holder.begin():
        await holder.execute(
            text(
                "SELECT target_id FROM ops.poi_cache_targets "
                "WHERE target_key = :key FOR UPDATE"
            ),
            {"key": f"{prefix}-active"},
        )
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        failed = await asyncio.wait_for(
            client.fail_update_request(
                request.request_id,
                owner_dagster_run_id="run-1",
                expected_request_generation=request.generation,
                error_message="Dagster feature update worker failed — run killed",
                failure_payload={"source": "dagster_run_failure"},
            ),
            timeout=30,
        )
        elapsed = loop.time() - started_at

    assert failed is not None
    assert failed.status == "failed"
    assert elapsed < 10
    assert (await _target_failed_at(migrated_engine, prefix))[f"{prefix}-active"] is None
    codes = [event["code"] for event in await _events(migrated_engine, request.job_id)]
    assert codes.count(FEATURE_UPDATE_RUN_FAILED_EVENT_CODE) == 1
