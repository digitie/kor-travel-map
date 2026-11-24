"""큐 요청의 일시 실패 재발행·상한·실패 원인 기록 (감사 2026-11-23 §1.3 P1·§4 #15, alembic 456).

- 일시 DB 실패(lock timeout 등)는 executor가 종결하지 않고 넘긴다 — 새 연결로 backoff 재발행.
- 시작 전 실패(launch 실패)의 재발행은 횟수 상한과 backoff를 갖고, 상한을 넘으면 ``failed``.
- 결정적 실패의 종결은 언제나 import job event에 분류·원인·실패 단계·Dagster run id를 남긴다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.feature_update_executor import (
    FEATURE_UPDATE_EXECUTION_FAILED_EVENT_CODE,
    FEATURE_UPDATE_RETRIES_EXHAUSTED_EVENT_CODE,
    FEATURE_UPDATE_RETRY_SCHEDULED_EVENT_CODE,
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
from tests.integration._db_cleanup import truncate_committed_test_rows

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_TRUNCATE_SQL = """
TRUNCATE
    ops.feature_update_requests,
    ops.import_job_events,
    ops.import_jobs
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
    assert final.error_message.startswith(f"재발행 {FEATURE_UPDATE_MAX_RETRIES}회 소진")
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
    assert final.error_message.startswith("재발행 2회 소진")

    events = await _events(migrated_engine, request.job_id)
    scheduled = [e for e in events if e["code"] == FEATURE_UPDATE_RETRY_SCHEDULED_EVENT_CODE]
    exhausted = [e for e in events if e["code"] == FEATURE_UPDATE_RETRIES_EXHAUSTED_EVENT_CODE]
    assert [event["payload"]["retry_count"] for event in scheduled] == [1, 2]
    assert {event["payload"]["max_retries"] for event in scheduled} == {2}
    assert {event["payload"]["stage"] for event in scheduled} == {"refreshing:1:dataset_wide"}
    assert len(exhausted) == 1
    assert exhausted[0]["payload"]["dagster_run_id"] == "run-final"
    assert exhausted[0]["payload"]["max_retries"] == 2

