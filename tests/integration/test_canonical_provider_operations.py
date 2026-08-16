"""C3e-A1 canonical provider operation lifecycle 통합 회귀.

T-VN-33 cutover WIP 커밋(``2e76b80c``, 메시지 자체가 "do not merge")이 2,227줄 27건
짜리였던 이 파일에서 2,178줄을 지워 115줄만 남겼고, 복원되지 않았다
(``git show --numstat 2e76b80c -- <이 파일>`` → ``66  2178``). 삭제된 27개 test
함수명을 그 커밋 트리에 전수 ``git grep``하면 **코드 hit은 0**이고, 2건만
``docs/reports/admin-ops-c3e-canonical-operations-2026-07-15.md``의 서술 언급으로
남아 있었다 — 이관이 아니라 소멸이었다. 그 회귀가 덮던 코드는 지금도 살아 있다:
``feature_operation_sensors`` / ``feature_operation_tracking`` /
``feature_operation_repo``.

identity가 pair(provider + dataset_key)에서 triple(provider_dataset_id + sync_scope
+ operation_key)로 옮겨졌으므로(ADR-088) 지어낸 자연키
(``ProviderDatasetOperationKey("provider", "dataset")``)는 더 이상 만들 수 없다 —
실행 레코드가 ``provider_sync.provider_dataset_operation_scopes``를 FK로 참조한다.
그래서 membership은 시드에서 고른다(``tests/integration/_membership_seed.py``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from dagster import AssetKey, DagsterRunStatus
from kortravelmap.dagster.assets import _exact_sync_membership
from kortravelmap.dagster.feature_operation_sensors import (
    _OPERATION_KEY_TAG,
    _TRIGGER_KIND_TAG,
    FeatureOperationReconcileCursor,
    _apply_run_record,
    _reconcile_tick,
)
from kortravelmap.dagster.feature_operation_tracking import (
    _ADMIN_MANUAL_TRIGGER_TAG,
    EXECUTION_SCOPES_TAG,
    FeatureOperationExecutionGuard,
    FeatureOperationGuardUnavailable,
    _guard_from_context_async,
    append_failed_multi_member_attempt,
    ensure_authoritative_feature_operation_guard,
    ensure_tracked_multi_member_asset,
    finish_tracked_feature_membership,
    run_tracked_feature_asset,
)
from kortravelmap.dagster.kma_weather import _exact_kma_sync_membership
from kortravelmap.dagster.schedules import (
    FEATURE_LOAD_SCHEDULE_SPECS,
    FeatureLoadScheduleSpec,
    _feature_load_definition_tags,
    _feature_load_schedule_tags,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.feature_operation import (
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationMembership,
    TriggerKind,
)
from kortravelmap.infra.feature_operation_repo import (
    append_dagster_feature_attempt_event as _append_dagster_feature_attempt_event,
)
from kortravelmap.infra.feature_operation_repo import (
    ensure_dagster_feature_operation as _ensure_dagster_feature_operation,
)
from kortravelmap.infra.feature_operation_repo import (
    finish_dagster_feature_membership as _finish_dagster_feature_membership,
)
from kortravelmap.infra.feature_operation_repo import (
    list_feature_operation_memberships,
    list_reconcilable_dagster_feature_runs,
    resolve_feature_operation_dataset_membership,
    resolve_feature_operation_memberships,
)
from kortravelmap.infra.feature_operation_repo import (
    reconcile_dagster_feature_run as _reconcile_dagster_feature_run,
)
from kortravelmap.infra.jobs_repo import (
    claim_next_import_job,
    enqueue_unpaired_import_job,
    heartbeat_import_job,
    record_import_job_event,
    recover_stale_running_jobs,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    cancel_queued_pipeline_cancellation_member,
    create_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
)
from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationInvariantError,
)
from kortravelmap.providers.feature_operation_registry import (
    resolve_feature_operation_handler,
)
from kortravelmap.providers.kma import (
    KMA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
)
from kortravelmap.providers.knps import KNPS_PLACE_DATASETS
from kortravelmap.providers.knps import PROVIDER_NAME as KNPS_PROVIDER_NAME

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration._membership_seed import (
    MULTI_MEMBER_OPERATION,
    SINGLE_MEMBER_OPERATION,
    launch_tags,
    membership_for_dataset,
    memberships_for_operation,
)
from tests.integration.conftest import as_dagster_runtime

pytestmark = pytest.mark.integration

@pytest.fixture(autouse=True)
def _provider_operation_clients_use_dagster_login(
    monkeypatch: pytest.MonkeyPatch,
    dagster_runtime_engine: AsyncEngine,
) -> None:
    """이 모듈의 provider client만 실제 Dagster LOGIN으로 생성한다.

    class 자체를 lambda로 바꾸면 아래의 ``AsyncKorTravelMapClient`` subclass
    regression이 깨진다. 생성자만 바꿔 concrete/subclass 표면은 그대로 둔다.
    """

    original_init = AsyncKorTravelMapClient.__init__

    def _init(self: AsyncKorTravelMapClient, _ignored_engine: AsyncEngine) -> None:
        original_init(self, dagster_runtime_engine)

    monkeypatch.setattr(AsyncKorTravelMapClient, "__init__", _init)


async def ensure_dagster_feature_operation(
    session: AsyncSession, **kwargs: Any
) -> Any:
    """Provider command은 실제 Dagster executor identity로만 실행한다."""
    async with as_dagster_runtime(session) as runtime_session:
        return await _ensure_dagster_feature_operation(runtime_session, **kwargs)


async def finish_dagster_feature_membership(
    session: AsyncSession, **kwargs: Any
) -> Any:
    async with as_dagster_runtime(session) as runtime_session:
        return await _finish_dagster_feature_membership(runtime_session, **kwargs)


async def append_dagster_feature_attempt_event(
    session: AsyncSession, **kwargs: Any
) -> Any:
    async with as_dagster_runtime(session) as runtime_session:
        return await _append_dagster_feature_attempt_event(runtime_session, **kwargs)


async def reconcile_dagster_feature_run(
    session: AsyncSession, **kwargs: Any
) -> Any:
    async with as_dagster_runtime(session) as runtime_session:
        return await _reconcile_dagster_feature_run(runtime_session, **kwargs)


#: attempt event를 member 행 identity로 되찾는 조인. ``ops.import_job_events``의
#: provider/dataset_key/sync_scope 열은 0091_tvn33_cutover_fence에서 DROP됐고,
#: member identity 정본은 ``ops.import_job_datasets``다.
_ATTEMPT_EVENTS_SQL = """
SELECT event.event_id, event.job_id, event.import_job_dataset_id,
       event.payload, pg_typeof(event.payload)::text AS payload_type,
       event.occurred_at,
       member.provider_dataset_id, member.sync_scope, member.operation_key
FROM ops.import_job_events AS event
JOIN ops.import_jobs AS child ON child.job_id = event.job_id
JOIN ops.import_job_datasets AS member
  ON member.job_id = event.job_id
 AND member.import_job_dataset_id = event.import_job_dataset_id
WHERE child.parent_job_id = CAST(:root_id AS uuid)
  AND event.code = 'feature_operation.attempt'
ORDER BY event.occurred_at, event.event_id
"""

#: member 행(=canonical identity)까지 붙인 child 조회.
_CHILD_MEMBERS_SQL = """
SELECT job.job_id, member.import_job_dataset_id,
       member.provider_dataset_id, member.sync_scope, member.operation_key,
       job.status, job.progress, job.current_stage,
       job.created_at, job.started_at, job.finished_at
FROM ops.import_jobs AS job
JOIN ops.import_job_datasets AS member ON member.job_id = job.job_id
WHERE job.parent_job_id = CAST(:root_id AS uuid)
  AND job.kind = 'provider_feature_load'
ORDER BY member.provider_dataset_id, member.sync_scope, member.operation_key
"""

#: root는 ``ops.import_job_datasets`` 행이 없으므로 LEFT JOIN + NULLS FIRST로
#: root를 첫 행에 고정한다.
_TREE_WITH_MEMBERS_SQL = """
SELECT job.job_id, job.parent_job_id, member.provider_dataset_id,
       member.sync_scope, member.operation_key, job.status, job.progress,
       job.current_stage, job.dagster_run_status, job.trigger_kind,
       job.created_at, job.started_at, job.finished_at
FROM ops.import_jobs AS job
LEFT JOIN ops.import_job_datasets AS member ON member.job_id = job.job_id
WHERE job.job_id = CAST(:root_id AS uuid)
   OR job.parent_job_id = CAST(:root_id AS uuid)
ORDER BY job.parent_job_id NULLS FIRST,
         member.provider_dataset_id, member.sync_scope
"""

_ACTIVE_TREE_COUNT_SQL = """
SELECT count(*) FROM ops.import_jobs
WHERE (job_id=CAST(:root_id AS uuid) OR parent_job_id=CAST(:root_id AS uuid))
  AND status IN ('queued','running')
"""


async def _mois_bulk_membership(
    session: AsyncSession,
) -> tuple[str, ProviderDatasetOperationMembership]:
    row = (
        await session.execute(
            text(
                """
                SELECT scope.operation_key, scope.provider_dataset_id, scope.sync_scope
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE dataset.provider = 'python-mois-api'
                  AND dataset.dataset_key = 'mois_license_features_bulk'
                  AND scope.operation_kind = 'refresh'
                ORDER BY scope.operation_key
                LIMIT 1
                """
            )
        )
    ).one()
    return (
        str(row.operation_key),
        ProviderDatasetOperationMembership(
            provider_dataset_id=int(row.provider_dataset_id),
            sync_scope=str(row.sync_scope),
            operation_key=str(row.operation_key),
        ),
    )


class _RecordingOperationClient:
    """실제 client/repo 결과를 변조 없이 기록하는 test probe."""

    def __init__(self, client: AsyncKorTravelMapClient) -> None:
        self.client = client
        self.ensure_mutations: list[Any] = []
        self.finish_mutations: list[Any] = []
        self.attempt_events: list[Any] = []

    async def ensure_dagster_feature_operation(self, **kwargs: Any) -> Any:
        mutation = await self.client.ensure_dagster_feature_operation(**kwargs)
        self.ensure_mutations.append(mutation)
        return mutation

    async def finish_dagster_feature_membership(self, **kwargs: Any) -> Any:
        mutation = await self.client.finish_dagster_feature_membership(**kwargs)
        self.finish_mutations.append(mutation)
        return mutation

    async def append_dagster_feature_attempt_event(self, **kwargs: Any) -> Any:
        event = await self.client.append_dagster_feature_attempt_event(**kwargs)
        self.attempt_events.append(event)
        return event


def _tracking_guard(
    client: _RecordingOperationClient,
    *,
    operation_key: str,
    memberships: tuple[ProviderDatasetOperationMembership, ...],
    run_id: str,
    trigger_kind: TriggerKind = "manual",
    extra_tags: Mapping[str, str] | None = None,
) -> FeatureOperationExecutionGuard:
    """frozen membership snapshot을 든 실행 guard를 실제 dataclass로 만든다.

    trigger tag를 항상 함께 싣는다 — ``_trigger_kind()``가 trigger tag 없으면
    ``"schedule"``로 추론하므로, ``trigger_kind="manual"``인 guard에 operation tag만
    실으면 ``ensure_authoritative_feature_operation_guard``가 ``trigger_mismatch``로
    죽는다.

    이 helper는 guard dataclass를 **이미 만들어진 상태로** 조립한다. 그래서 어떤
    selection이 frozen되는가(=resource init의 결정)는 여기서 검증되지 않는다 —
    그 축은 ``_resource_init_context``로 ``_guard_from_context_async``를 그대로
    태우는 회귀가 맡는다.

    ``extra_tags``는 guard가 든 값과 run tag를 어긋나게 만들어 I/O 직전 재검증
    경로를 시험할 때 쓴다.
    """

    created_at = datetime(2026, 7, 16, 1, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    binding = resolve_feature_operation_handler(operation_key)
    run = SimpleNamespace(
        job_name=binding.job_name,
        run_id=run_id,
        run_config={},
        tags={
            **launch_tags(operation_key=operation_key, trigger_kind=trigger_kind),
            **dict(extra_tags or {}),
        },
        asset_selection=None,
        resolved_op_selection=None,
        status=SimpleNamespace(value="STARTED"),
    )
    record = SimpleNamespace(
        dagster_run=run,
        create_timestamp=created_at,
        start_time=started_at.timestamp(),
    )
    instance = SimpleNamespace(
        run=run,
        get_run_record_by_id=lambda _run_id: record,
    )
    return FeatureOperationExecutionGuard(
        client=client,  # type: ignore[arg-type]
        instance=instance,
        operation_key=operation_key,
        memberships=memberships,
        dagster_run_id=run_id,
        trigger_kind=trigger_kind,
    )


def _schedule_spec(job_name: str) -> FeatureLoadScheduleSpec:
    """프로덕션 schedule spec을 이름으로 집는다 — 없으면 죽는다."""
    for spec in FEATURE_LOAD_SCHEDULE_SPECS:
        if spec.job_name == job_name:
            return spec
    raise AssertionError(f"feature-load schedule spec이 없다: {job_name!r}")


def _resource_init_context(
    client: AsyncKorTravelMapClient,
    *,
    run_id: str,
    tags: Mapping[str, str],
) -> Any:
    """``feature_operation_guard_resource``가 받는 ``InitResourceContext`` 모양.

    guard가 실제로 어떤 selection을 frozen하는지는 resource init에서 결정되므로,
    여기서만 그 경로를 정확히 재현할 수 있다. 이미 만들어진 guard dataclass를
    손으로 조립하면(``_tracking_guard``) 그 결정 자체가 검증 밖으로 빠진다.
    """
    created_at = datetime(2026, 7, 16, 1, tzinfo=UTC)
    run = SimpleNamespace(
        run_id=run_id,
        job_name="integration-run",
        run_config={},
        asset_selection=None,
        tags=dict(tags),
        status=SimpleNamespace(value="STARTED"),
    )
    record = SimpleNamespace(
        dagster_run=run,
        create_timestamp=created_at,
        start_time=(created_at + timedelta(seconds=1)).timestamp(),
    )
    return SimpleNamespace(
        run=run,
        instance=SimpleNamespace(run=run, get_run_record_by_id=lambda _run_id: record),
        resources=SimpleNamespace(kor_travel_map_client=client),
    )


def _tracking_context(
    guard: FeatureOperationExecutionGuard,
    *,
    retry_number: int,
) -> Any:
    assert guard.operation_key is not None
    binding = resolve_feature_operation_handler(guard.operation_key)
    asset_key = AssetKey(binding.asset_keys[0])
    return SimpleNamespace(
        resources=SimpleNamespace(
            feature_operation_guard=guard,
            kor_travel_map_client=guard.client,
        ),
        instance=guard.instance,
        run=guard.instance.run,
        run_id=guard.dagster_run_id,
        selected_asset_keys={asset_key},
        asset_key=asset_key,
        job_name=binding.job_name,
        retry_number=retry_number,
    )


def _event_payload(value: object) -> dict[str, object]:
    if isinstance(value, str):
        decoded = json.loads(value)
        assert isinstance(decoded, dict)
        return decoded
    assert isinstance(value, dict)
    return value


async def _delete_committed_feature_tree(
    engine: AsyncEngine,
    *,
    root_id: str,
    cancellation_id: str | None = None,
) -> None:
    async with AsyncSession(engine) as cleanup, cleanup.begin():
        await cleanup.execute(
            text(
                "UPDATE ops.import_jobs SET cancellation_id=NULL, "
                "cancellation_requested_at=NULL, cancellation_requested_by=NULL, "
                "cancellation_reason=NULL "
                "WHERE job_id=CAST(:root_id AS uuid) "
                "OR parent_job_id=CAST(:root_id AS uuid)"
            ),
            {"root_id": root_id},
        )
        # ``ops.import_job_events``는 (job_id, import_job_dataset_id)로
        # ``ops.import_job_datasets``를 ON DELETE RESTRICT로 참조한다. import_jobs를
        # 지우면 datasets cascade가 동시에 걸려 23503으로 죽으므로 event를 먼저 지운다.
        await cleanup.execute(
            text(
                "DELETE FROM ops.import_job_events "
                "WHERE job_id IN ("
                "  SELECT job_id FROM ops.import_jobs "
                "  WHERE job_id = CAST(:root_id AS uuid) "
                "     OR parent_job_id = CAST(:root_id AS uuid)"
                ")"
            ),
            {"root_id": root_id},
        )
        if cancellation_id is not None:
            for statement in (
                "DELETE FROM ops.pipeline_cancellation_members "
                "WHERE cancellation_id=CAST(:cancellation_id AS uuid)",
                "DELETE FROM ops.pipeline_cancellation_runs "
                "WHERE cancellation_id=CAST(:cancellation_id AS uuid)",
                "DELETE FROM ops.pipeline_cancellations "
                "WHERE cancellation_id=CAST(:cancellation_id AS uuid)",
            ):
                await cleanup.execute(
                    text(statement),
                    {"cancellation_id": cancellation_id},
                )
        await cleanup.execute(
            text(
                "DELETE FROM ops.import_jobs "
                "WHERE parent_job_id=CAST(:root_id AS uuid)"
            ),
            {"root_id": root_id},
        )
        await cleanup.execute(
            text(
                "DELETE FROM ops.import_jobs WHERE job_id=CAST(:root_id AS uuid)"
            ),
            {"root_id": root_id},
        )


def _tracking_record(
    *,
    operation_key: str,
    run_id: str,
    status: DagsterRunStatus,
    created_at: datetime,
    started_at: datetime | None,
    finished_at: datetime | None,
    storage_id: int = 1,
    trigger_kind: TriggerKind = "schedule",
) -> Any:
    """sensor가 읽는 Dagster run record.

    ``_apply_run_record``는 tags/status/timestamp만 읽는다 — job_name/run_config/
    asset_selection은 관측 대상이 아니지만 원본 모양을 유지한다.
    """

    binding = resolve_feature_operation_handler(operation_key)
    return SimpleNamespace(
        storage_id=storage_id,
        dagster_run=SimpleNamespace(
            run_id=run_id,
            job_name=binding.job_name,
            status=status,
            run_config={},
            tags=launch_tags(operation_key=operation_key, trigger_kind=trigger_kind),
            asset_selection=frozenset(
                AssetKey.from_user_string(key) for key in binding.asset_keys
            ),
        ),
        create_timestamp=created_at,
        start_time=started_at.timestamp() if started_at is not None else None,
        end_time=finished_at.timestamp() if finished_at is not None else None,
    )


class _PeriodicDagsterInstance:
    def __init__(self, records: list[Any]) -> None:
        self._records = {
            record.dagster_run.run_id: record for record in records
        }

    def get_run_record_by_id(self, run_id: str) -> Any | None:
        return self._records.get(run_id)

    def get_run_records(self, **_kwargs: Any) -> list[Any]:
        return []


class _PeriodicLog:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str, *args: object) -> None:
        self.errors.append(message % args if args else message)


class _PeriodicContext:
    def __init__(self, records: list[Any]) -> None:
        self.instance = _PeriodicDagsterInstance(records)
        self.cursor = FeatureOperationReconcileCursor().to_json()
        self.log = _PeriodicLog()
        self.updated_cursors: list[str] = []

    def update_cursor(self, cursor: str) -> None:
        self.updated_cursors.append(cursor)


def _membership_of(row: Any) -> ProviderDatasetOperationMembership:
    return ProviderDatasetOperationMembership(
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=str(row.sync_scope),
        operation_key=str(row.operation_key),
    )


def _triple(row: Any) -> tuple[int, str, str]:
    return (
        int(row.provider_dataset_id),
        str(row.sync_scope),
        str(row.operation_key),
    )


def _membership_triple(
    membership: ProviderDatasetOperationMembership,
) -> tuple[int, str, str]:
    return (
        membership.provider_dataset_id,
        membership.sync_scope,
        membership.operation_key,
    )


async def test_operation_memberships_are_read_from_db_binding(
    migrated_session: AsyncSession,
) -> None:
    operation_key, expected = await _mois_bulk_membership(migrated_session)

    memberships = await list_feature_operation_memberships(
        migrated_session,
        operation_key=operation_key,
    )
    scheduled_memberships = await resolve_feature_operation_memberships(
        migrated_session,
        operation_key=operation_key,
    )
    runtime_membership = await resolve_feature_operation_dataset_membership(
        migrated_session,
        operation_key=operation_key,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    )

    assert expected in memberships
    assert scheduled_memberships == memberships
    assert runtime_membership == expected


async def test_ensure_attempt_and_finish_use_only_canonical_membership(
    migrated_session: AsyncSession,
) -> None:
    operation_key, membership = await _mois_bulk_membership(migrated_session)
    run_id = f"tvn33-operation-{uuid4()}"
    started_at = datetime(2026, 8, 7, tzinfo=UTC)

    created = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=run_id,
        trigger_kind="manual",
        selected_memberships=(membership,),
        operation_key=operation_key,
        engine_created_at=started_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    event = await append_dagster_feature_attempt_event(
        migrated_session,
        dagster_run_id=run_id,
        membership=membership,
        attempt_number=1,
        outcome="failed",
        error={"code": "TEST_FAILURE"},
    )
    finished = await finish_dagster_feature_membership(
        migrated_session,
        dagster_run_id=run_id,
        membership=membership,
    )

    assert created.operation.operation_key == operation_key
    assert created.operation.members[0].membership == membership
    assert event.import_job_dataset_id == created.operation.members[0].import_job_dataset_id
    assert finished.outcome == "applied"
    assert finished.operation.members[0].membership == membership
    # member 완료는 그 member의 job만 닫고 root의 진행률을 민다. root의 terminal
    # 전이는 Dagster terminal handoff(``reconcile_dagster_feature_run``)만 한다 —
    # 여기서 root까지 done으로 보면 handoff 없이 끝난 run이 완료로 보인다.
    assert finished.operation.members[0].status == "done"
    assert finished.operation.progress == 100
    assert finished.operation.status == "running"


async def test_marker_block_keeps_canonical_child_count_unchanged(
    migrated_engine: AsyncEngine,
) -> None:
    client = AsyncKorTravelMapClient(migrated_engine)
    run_id = f"run-c3e-b2-marker-{uuid4()}"
    created_at = datetime(2026, 7, 16, 2, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    async with AsyncSession(migrated_engine) as seed:
        memberships = await memberships_for_operation(seed, limit=2)
    assert len(memberships) == 2
    initial = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="manual",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    root_id = initial.operation.root_job_id
    cancellation_id: str | None = None

    async def _child_count() -> int:
        async with AsyncSession(migrated_engine) as probe:
            value = await probe.scalar(
                text(
                    "SELECT count(*) FROM ops.import_jobs "
                    "WHERE parent_job_id=CAST(:root_id AS uuid) "
                    "AND kind='provider_feature_load'"
                ),
                {"root_id": root_id},
            )
        return int(value or 0)

    try:
        before_marker = await _child_count()
        async with AsyncSession(migrated_engine) as session, session.begin():
            scope = await resolve_pipeline_cancellation_scope(
                session,
                kind="import_job",
                execution_id=root_id,
            )
            assert scope is not None
            detail = await create_pipeline_cancellation_attempt(
                session,
                scope=scope,
                requested_by="admin:b2-acceptance",
                reason="provider I/O barrier",
            )
            cancellation_id = detail.attempt.cancellation_id
        after_marker = await _child_count()
        blocked = await client.ensure_dagster_feature_operation(
            dagster_run_id=run_id,
            trigger_kind="manual",
            selected_memberships=memberships,
            operation_key=MULTI_MEMBER_OPERATION,
            engine_created_at=created_at,
            engine_started_at=started_at,
            observed_status="STARTED",
        )
        after_blocked_ensure = await _child_count()

        assert initial.outcome == "applied"
        assert blocked.outcome == "blocked"
        assert blocked.block_reason == "cancellation"
        assert (
            before_marker
            == after_marker
            == after_blocked_ensure
            == len(memberships)
        )
    finally:
        await _delete_committed_feature_tree(
            migrated_engine,
            root_id=root_id,
            cancellation_id=cancellation_id,
        )


async def test_real_db_single_retry_and_shared_wrapper_are_idempotent(
    migrated_engine: AsyncEngine,
) -> None:
    base_client = AsyncKorTravelMapClient(migrated_engine)
    async with AsyncSession(migrated_engine) as seed:
        memberships = await memberships_for_operation(
            seed, operation_key=SINGLE_MEMBER_OPERATION
        )
    # single-member wrapper 경로(``_single_membership_for_asset``)의 전제를
    # 암묵이 아니라 단언으로 박는다.
    assert len(memberships) == 1
    membership = memberships[0]
    retry_probe = _RecordingOperationClient(base_client)
    retry_guard = _tracking_guard(
        retry_probe,
        operation_key=SINGLE_MEMBER_OPERATION,
        memberships=memberships,
        run_id=f"run-c3e-b2-single-retry-{uuid4()}",
    )
    retry_root_id: str | None = None
    shared_root_id: str | None = None

    async def _fail(_context: object) -> None:
        raise RuntimeError("retry")

    async def _succeed(_context: object) -> str:
        return "done"

    try:
        with pytest.raises(RuntimeError, match="retry"):
            await run_tracked_feature_asset(
                _tracking_context(retry_guard, retry_number=0),
                _fail,
            )
        retry_root_id = retry_probe.ensure_mutations[0].operation.root_job_id
        assert (
            await run_tracked_feature_asset(
                _tracking_context(retry_guard, retry_number=1),
                _succeed,
            )
            == "done"
        )
        assert [item.outcome for item in retry_probe.ensure_mutations] == [
            "applied",
            "noop",
        ]
        assert [item.outcome for item in retry_probe.finish_mutations] == ["applied"]
        member = retry_probe.ensure_mutations[0].operation.members[0]
        assert member.membership == membership
        assert [
            event.import_job_dataset_id for event in retry_probe.attempt_events
        ] == [member.import_job_dataset_id]

        async with AsyncSession(migrated_engine) as probe:
            attempts = (
                await probe.execute(
                    text(_ATTEMPT_EVENTS_SQL),
                    {"root_id": retry_root_id},
                )
            ).all()
        assert [_triple(row) for row in attempts] == [_membership_triple(membership)]
        assert [_event_payload(row.payload) for row in attempts] == [
            {
                "attempt_number": 1,
                "outcome": "failed",
                "error": {
                    "code": "FEATURE_OPERATION_ASSET_ATTEMPT_FAILED",
                    "type": "RuntimeError",
                },
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
            }
        ]

        shared_probe = _RecordingOperationClient(base_client)
        shared_guard = _tracking_guard(
            shared_probe,
            operation_key=SINGLE_MEMBER_OPERATION,
            memberships=memberships,
            run_id=f"run-c3e-b2-shared-{uuid4()}",
        )
        await run_tracked_feature_asset(
            _tracking_context(shared_guard, retry_number=0),
            _succeed,
        )
        shared_root_id = shared_probe.ensure_mutations[0].operation.root_job_id
        await run_tracked_feature_asset(
            _tracking_context(shared_guard, retry_number=0),
            _succeed,
        )
        assert [item.outcome for item in shared_probe.ensure_mutations] == [
            "applied",
            "noop",
        ]
        assert [item.outcome for item in shared_probe.finish_mutations] == [
            "applied",
            "noop",
        ]
        assert all(
            len(item.operation.members) == 1
            for item in (
                *shared_probe.ensure_mutations,
                *shared_probe.finish_mutations,
            )
        )
    finally:
        if retry_root_id is not None:
            await _delete_committed_feature_tree(
                migrated_engine,
                root_id=retry_root_id,
            )
        if shared_root_id is not None:
            await _delete_committed_feature_tree(
                migrated_engine,
                root_id=shared_root_id,
            )


async def test_real_db_mcst_same_run_retry_preserves_pair_and_attempts(
    migrated_engine: AsyncEngine,
) -> None:
    probe = _RecordingOperationClient(AsyncKorTravelMapClient(migrated_engine))
    async with AsyncSession(migrated_engine) as seed:
        memberships = await memberships_for_operation(seed, limit=2)
    assert len(memberships) == 2
    done_membership, failed_membership = memberships
    guard = _tracking_guard(
        probe,
        operation_key=MULTI_MEMBER_OPERATION,
        memberships=memberships,
        run_id=f"run-c3e-b2-mcst-{uuid4()}",
    )
    root_id: str | None = None
    try:
        first_context = _tracking_context(guard, retry_number=0)
        assert await ensure_tracked_multi_member_asset(first_context) is guard
        root_id = probe.ensure_mutations[0].operation.root_job_id
        await finish_tracked_feature_membership(guard, done_membership)
        await append_failed_multi_member_attempt(
            first_context,
            guard,
            failed_membership,
            RuntimeError("first attempt"),
        )

        second_context = _tracking_context(guard, retry_number=1)
        assert await ensure_tracked_multi_member_asset(second_context) is guard
        await finish_tracked_feature_membership(guard, done_membership)
        await append_failed_multi_member_attempt(
            second_context,
            guard,
            failed_membership,
            RuntimeError("second attempt"),
        )
        assert [item.outcome for item in probe.ensure_mutations] == [
            "applied",
            "noop",
        ]
        assert [item.outcome for item in probe.finish_mutations] == [
            "applied",
            "noop",
        ]
        failed_member = next(
            member
            for member in probe.ensure_mutations[0].operation.members
            if member.membership == failed_membership
        )
        assert [event.import_job_dataset_id for event in probe.attempt_events] == [
            failed_member.import_job_dataset_id,
            failed_member.import_job_dataset_id,
        ]
        async with AsyncSession(migrated_engine) as session:
            stored_attempts = (
                await session.execute(
                    text(_ATTEMPT_EVENTS_SQL),
                    {"root_id": root_id},
                )
            ).all()
        assert [_triple(row) for row in stored_attempts] == [
            _membership_triple(failed_membership),
            _membership_triple(failed_membership),
        ]
        assert [_event_payload(row.payload) for row in stored_attempts] == [
            {
                "attempt_number": 1,
                "outcome": "failed",
                "error": {
                    "code": "FEATURE_OPERATION_ASSET_ATTEMPT_FAILED",
                    "type": "RuntimeError",
                },
                "provider_dataset_id": failed_membership.provider_dataset_id,
                "sync_scope": failed_membership.sync_scope,
                "operation_key": failed_membership.operation_key,
            },
            {
                "attempt_number": 2,
                "outcome": "failed",
                "error": {
                    "code": "FEATURE_OPERATION_ASSET_ATTEMPT_FAILED",
                    "type": "RuntimeError",
                },
                "provider_dataset_id": failed_membership.provider_dataset_id,
                "sync_scope": failed_membership.sync_scope,
                "operation_key": failed_membership.operation_key,
            },
        ]
    finally:
        if root_id is not None:
            await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_b2_single_wrapper_success_is_closed_by_b3_terminal_record(
    migrated_engine: AsyncEngine,
) -> None:
    operation_key = SINGLE_MEMBER_OPERATION
    run_id = f"run-c3e-i-single-{uuid4()}"
    created_at = datetime(2026, 7, 16, 1, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    base_client = AsyncKorTravelMapClient(migrated_engine)
    async with AsyncSession(migrated_engine) as seed:
        memberships = await memberships_for_operation(
            seed, operation_key=operation_key
        )
    assert len(memberships) == 1
    # guard가 freeze한 selection과 sensor가 DB에서 다시 읽는 selection이 같아야
    # terminal handoff가 identity conflict 없이 root를 닫는다.
    assert memberships == await base_client.resolve_feature_operation_memberships(
        operation_key=operation_key
    )
    probe = _RecordingOperationClient(base_client)
    guard = _tracking_guard(
        probe,
        operation_key=operation_key,
        memberships=memberships,
        run_id=run_id,
        trigger_kind="manual",
    )
    root_id: str | None = None

    async def _succeed(_context: object) -> str:
        return "loaded"

    try:
        result = await run_tracked_feature_asset(
            _tracking_context(guard, retry_number=0),
            _succeed,
        )
        root_id = probe.ensure_mutations[0].operation.root_job_id
        async with AsyncSession(migrated_engine) as before_session:
            member_before = (
                await before_session.execute(
                    text(
                        "SELECT job.job_id, member.provider_dataset_id, "
                        "member.sync_scope, member.operation_key, job.created_at, "
                        "job.started_at, job.finished_at "
                        "FROM ops.import_jobs AS job "
                        "JOIN ops.import_job_datasets AS member "
                        "  ON member.job_id = job.job_id "
                        "WHERE job.parent_job_id=CAST(:root_id AS uuid) "
                        "AND job.kind='provider_feature_load'"
                    ),
                    {"root_id": root_id},
                )
            ).one()
        assert member_before.finished_at is not None
        terminal_finished_at = member_before.finished_at + timedelta(seconds=1)

        outcome = await _apply_run_record(
            _tracking_record(
                operation_key=operation_key,
                run_id=run_id,
                status=DagsterRunStatus.SUCCESS,
                created_at=created_at,
                started_at=started_at,
                finished_at=terminal_finished_at,
                trigger_kind="manual",
            ),
            probe.client,
        )

        async with AsyncSession(migrated_engine) as after_session:
            rows = (
                await after_session.execute(
                    text(_TREE_WITH_MEMBERS_SQL),
                    {"root_id": root_id},
                )
            ).all()
            active_count = await after_session.scalar(
                text(_ACTIVE_TREE_COUNT_SQL),
                {"root_id": root_id},
            )

        root, member = rows
        assert result == "loaded"
        assert outcome == "applied"
        assert int(active_count or 0) == 0
        assert {root.status, member.status} == {"done"}
        assert {root.progress, member.progress} == {100}
        assert {root.current_stage, member.current_stage} == {"completed"}
        assert root.dagster_run_status == "SUCCESS"
        assert root.trigger_kind == "manual"
        assert root.created_at == member.created_at == created_at
        assert root.started_at == member.started_at == started_at
        assert root.finished_at == terminal_finished_at
        assert member.job_id == member_before.job_id
        assert _triple(member) == _triple(member_before)
        assert _triple(member) == _membership_triple(memberships[0])
        assert member.finished_at == member_before.finished_at
    finally:
        cleanup_root_id = root_id
        if cleanup_root_id is None and probe.ensure_mutations:
            cleanup_root_id = probe.ensure_mutations[0].operation.root_job_id
        if cleanup_root_id is not None:
            await _delete_committed_feature_tree(
                migrated_engine,
                root_id=cleanup_root_id,
            )


async def test_b2_mcst_partial_attempt_is_preserved_by_b3_failure_record(
    migrated_engine: AsyncEngine,
) -> None:
    operation_key = MULTI_MEMBER_OPERATION
    run_id = f"run-c3e-i-mcst-{uuid4()}"
    created_at = datetime(2026, 7, 16, 1, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    probe = _RecordingOperationClient(AsyncKorTravelMapClient(migrated_engine))
    # limit 없이 전부(13건) 얼린다 — sensor가 DB에서 전체를 다시 읽으므로 부분집합을
    # freeze하면 terminal이 'failed'가 아니라 'tracking_invariant'로 빠져 이 테스트가
    # 검사하려는 경로 자체가 바뀐다.
    async with AsyncSession(migrated_engine) as seed_session:
        memberships = await memberships_for_operation(seed_session)
    assert len(memberships) > 1
    done_member, failed_member = memberships[:2]
    guard = _tracking_guard(
        probe,
        operation_key=operation_key,
        memberships=memberships,
        run_id=run_id,
        trigger_kind="manual",
    )
    context = _tracking_context(guard, retry_number=0)
    root_id: str | None = None
    raw_error = "raw-upstream-detail-42"

    try:
        assert await ensure_tracked_multi_member_asset(context) is guard
        root_id = probe.ensure_mutations[0].operation.root_job_id
        await finish_tracked_feature_membership(guard, done_member)
        await append_failed_multi_member_attempt(
            context,
            guard,
            failed_member,
            RuntimeError(raw_error),
        )

        async with AsyncSession(migrated_engine) as before_session:
            children_before = (
                await before_session.execute(
                    text(_CHILD_MEMBERS_SQL),
                    {"root_id": root_id},
                )
            ).all()
            attempt_before = (
                await before_session.execute(
                    text(_ATTEMPT_EVENTS_SQL),
                    {"root_id": root_id},
                )
            ).one()
        children_before_by_membership = {
            _triple(row): row for row in children_before
        }
        assert len(children_before) == len(memberships)
        assert len(children_before_by_membership) == len(children_before)
        assert set(children_before_by_membership) == {
            _membership_triple(member) for member in memberships
        }
        done_before = children_before_by_membership[_membership_triple(done_member)]
        assert done_before.finished_at is not None
        terminal_finished_at = max(
            done_before.finished_at,
            attempt_before.occurred_at,
        ) + timedelta(seconds=1)

        outcome = await _apply_run_record(
            _tracking_record(
                operation_key=operation_key,
                run_id=run_id,
                status=DagsterRunStatus.FAILURE,
                created_at=created_at,
                started_at=started_at,
                finished_at=terminal_finished_at,
                trigger_kind="manual",
            ),
            probe.client,
        )

        async with AsyncSession(migrated_engine) as after_session:
            root = (
                await after_session.execute(
                    text(
                        "SELECT job_id, status, progress, current_stage, "
                        "dagster_run_status, trigger_kind, operation_key, "
                        "created_at, started_at, finished_at "
                        "FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid)"
                    ),
                    {"root_id": root_id},
                )
            ).one()
            children = (
                await after_session.execute(
                    text(_CHILD_MEMBERS_SQL),
                    {"root_id": root_id},
                )
            ).all()
            attempt_after = (
                await after_session.execute(
                    text(_ATTEMPT_EVENTS_SQL),
                    {"root_id": root_id},
                )
            ).one()
            active_count = await after_session.scalar(
                text(_ACTIVE_TREE_COUNT_SQL),
                {"root_id": root_id},
            )

        children_after_by_membership = {_triple(row): row for row in children}
        done_after = children_after_by_membership[_membership_triple(done_member)]
        failed_after = children_after_by_membership[
            _membership_triple(failed_member)
        ]
        expected_attempt = {
            "attempt_number": 1,
            "outcome": "failed",
            "error": {
                "code": "FEATURE_OPERATION_ASSET_ATTEMPT_FAILED",
                "type": "RuntimeError",
            },
            "provider_dataset_id": failed_member.provider_dataset_id,
            "sync_scope": failed_member.sync_scope,
            "operation_key": failed_member.operation_key,
        }

        assert outcome == "applied"
        assert int(active_count or 0) == 0
        assert len(children) == len(memberships)
        assert root.status == "failed"
        assert root.current_stage == "failed"
        assert root.dagster_run_status == "FAILURE"
        assert root.trigger_kind == "manual"
        assert root.operation_key == operation_key
        assert root.progress == 100 // len(memberships)
        assert root.finished_at == terminal_finished_at
        assert done_after.job_id == done_before.job_id
        assert _triple(done_after) == _triple(done_before)
        assert done_after.status == "done"
        assert done_after.progress == 100
        assert done_after.current_stage == "completed"
        assert done_after.finished_at == done_before.finished_at
        assert len([row for row in children if row.status == "failed"]) == (
            len(memberships) - 1
        )
        assert {
            row.current_stage for row in children if row.status == "failed"
        } == {"failed"}
        assert set(children_after_by_membership) == set(children_before_by_membership)
        for triple, before in children_before_by_membership.items():
            after = children_after_by_membership[triple]
            assert after.job_id == before.job_id
            assert after.created_at == before.created_at
            assert after.started_at == before.started_at
            if before.status == "done":
                assert after.finished_at == before.finished_at
            else:
                assert before.status == "running"
                assert before.finished_at is None
                assert after.status == "failed"
                assert after.current_stage == "failed"
                assert after.finished_at == terminal_finished_at
        assert failed_after.job_id == attempt_after.job_id
        assert failed_after.finished_at == terminal_finished_at
        assert attempt_after.event_id == attempt_before.event_id
        assert attempt_after.job_id == attempt_before.job_id
        assert _triple(attempt_after) == _membership_triple(failed_member)
        assert (
            attempt_after.import_job_dataset_id
            == failed_after.import_job_dataset_id
        )
        assert attempt_after.payload_type == attempt_before.payload_type == "jsonb"
        assert _event_payload(attempt_after.payload) == expected_attempt
        assert _event_payload(attempt_before.payload) == expected_attempt
        assert attempt_after.occurred_at == attempt_before.occurred_at
        assert raw_error not in json.dumps(
            _event_payload(attempt_after.payload), ensure_ascii=False
        )
    finally:
        cleanup_root_id = root_id
        if cleanup_root_id is None and probe.ensure_mutations:
            cleanup_root_id = probe.ensure_mutations[0].operation.root_job_id
        if cleanup_root_id is not None:
            await _delete_committed_feature_tree(
                migrated_engine,
                root_id=cleanup_root_id,
            )


async def test_feature_operation_lifecycle_is_idempotent_and_never_reverses(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    created_at = datetime(2026, 7, 15, 1, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=2)
    finished_at = started_at + timedelta(seconds=3)
    run_id = f"run-c3e-lifecycle-{uuid4()}"
    # 불변식은 provider 다양성이 아니라 member 다수성에 걸려 있다. 지금은 한 run의
    # 모든 membership이 같은 operation_key여야 하므로(_require_operation_memberships)
    # 같은 operation의 서로 다른 dataset membership 2개로 다시 정의한다.
    memberships = await memberships_for_operation(migrated_session, limit=2)

    queued = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    assert queued.outcome == "applied"
    assert queued.operation.status == "queued"
    assert len(queued.operation.members) == 2

    started = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_memberships=tuple(reversed(memberships)),
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    assert started.operation.status == "running"
    assert started.operation.dagster_run_status == "STARTED"
    assert {member.status for member in started.operation.members} == {"running"}

    late_queued = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    assert late_queued.outcome == "noop"
    assert late_queued.operation.status == "running"
    assert late_queued.operation.dagster_run_status == "STARTED"

    for membership in memberships:
        completed = await finish_dagster_feature_membership(
            migrated_session,
            dagster_run_id=run_id,
            membership=membership,
        )
    assert completed.operation.progress == 100

    terminal = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id=run_id,
        trigger_kind="schedule",
        terminal_status="SUCCESS",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=started_at,
        engine_finished_at=finished_at,
        error=None,
    )
    assert terminal.operation.status == "done"
    assert terminal.operation.progress == 100
    assert terminal.operation.finished_at == finished_at


async def test_selection_conflict_rolls_back_without_attaching_pair(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 2, tzinfo=UTC)
    run_id = f"run-c3e-conflict-{uuid4()}"
    # 두 membership이 같은 operation_key여야 _require_operation_memberships를 통과해
    # selection freeze 위반(_raise_identity_conflict)까지 도달한다.
    first, second = await memberships_for_operation(migrated_session, limit=2)
    await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=run_id,
        trigger_kind="manual",
        selected_memberships=(first,),
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )

    with pytest.raises(FeatureOperationInvariantConflict) as excinfo:
        await ensure_dagster_feature_operation(
            migrated_session,
            dagster_run_id=run_id,
            trigger_kind="manual",
            selected_memberships=(first, second),
            operation_key=MULTI_MEMBER_OPERATION,
            engine_created_at=created_at,
            engine_started_at=None,
            observed_status="QUEUED",
        )
    assert "selected_memberships" in excinfo.value.details
    child_count = await migrated_session.scalar(
        text(
            """
            SELECT count(*) FROM ops.import_jobs AS child
            JOIN ops.import_jobs AS root ON root.job_id = child.parent_job_id
            WHERE root.dagster_run_id = :run_id
              AND child.kind = 'provider_feature_load'
            """
        ),
        {"run_id": run_id},
    )
    assert child_count == 1


async def test_same_run_concurrent_ensure_creates_one_complete_tree(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-c3e-concurrent-{uuid4()}"
    created_at = datetime(2026, 7, 15, 2, tzinfo=UTC)
    async with AsyncSession(migrated_engine) as seed_session:
        memberships = await memberships_for_operation(seed_session, limit=3)
    assert len(memberships) == 3
    start = asyncio.Event()

    async def ensure_once() -> Any:
        await start.wait()
        async with AsyncSession(migrated_engine) as session, session.begin():
            return await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="sensor",
                selected_memberships=tuple(reversed(memberships)),
                operation_key=MULTI_MEMBER_OPERATION,
                engine_created_at=created_at,
                engine_started_at=None,
                observed_status="QUEUED",
            )

    tasks = (asyncio.create_task(ensure_once()), asyncio.create_task(ensure_once()))
    start.set()
    first, second = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
    root_id = first.operation.root_job_id
    try:
        assert second.operation.root_job_id == root_id
        assert {first.outcome, second.outcome} == {"applied", "noop"}
        async with AsyncSession(migrated_engine) as probe:
            counts = (
                await probe.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE parent_job_id IS NULL) AS roots, "
                        "count(*) FILTER (WHERE parent_job_id IS NOT NULL) AS children "
                        "FROM ops.import_jobs WHERE dagster_run_id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            ).one()
            member_rows = await probe.scalar(
                text(
                    "SELECT count(*) FROM ops.import_job_datasets AS member "
                    "JOIN ops.import_jobs AS job ON job.job_id=member.job_id "
                    "WHERE job.dagster_run_id=:run_id"
                ),
                {"run_id": run_id},
            )
        assert int(counts.roots) == 1
        assert int(counts.children) == len(memberships)
        # membership 행이 별도 테이블이므로 import_jobs 행 수만 세면 "child는 있는데
        # membership 행이 중복/누락"이 통과한다 — member 행도 따로 센다.
        assert int(member_rows or 0) == len(memberships)
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


@pytest.mark.parametrize("winner", ["marker", "started_ensure"])
async def test_started_ensure_and_cancellation_marker_barrier_has_no_escape(
    migrated_engine: AsyncEngine,
    winner: str,
) -> None:
    run_id = f"run-c3e-marker-race-{winner}-{uuid4()}"
    created_at = datetime(2026, 7, 15, 3, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        memberships = await memberships_for_operation(setup, limit=2)
        queued = await ensure_dagster_feature_operation(
            setup,
            dagster_run_id=run_id,
            trigger_kind="manual",
            selected_memberships=memberships,
            operation_key=MULTI_MEMBER_OPERATION,
            engine_created_at=created_at,
            engine_started_at=None,
            observed_status="QUEUED",
        )
    root_id = queued.operation.root_job_id
    first_write_done = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def mark_and_hold(*, entered: asyncio.Event | None = None) -> Any:
        async with AsyncSession(migrated_engine) as session, session.begin():
            if entered is not None:
                entered.set()
            scope = await resolve_pipeline_cancellation_scope(
                session, kind="import_job", execution_id=root_id
            )
            assert scope is not None
            detail = await create_pipeline_cancellation_attempt(
                session,
                scope=scope,
                requested_by="admin:race",
                reason=winner,
            )
            first_write_done.set()
            await release_first.wait()
            return detail

    async def start_and_hold(*, entered: asyncio.Event | None = None) -> Any:
        async with AsyncSession(migrated_engine) as session, session.begin():
            if entered is not None:
                entered.set()
            mutation = await ensure_dagster_feature_operation(
                session,
                dagster_run_id=run_id,
                trigger_kind="manual",
                selected_memberships=memberships,
                operation_key=MULTI_MEMBER_OPERATION,
                engine_created_at=created_at,
                engine_started_at=started_at,
                observed_status="STARTED",
            )
            first_write_done.set()
            await release_first.wait()
            return mutation

    if winner == "marker":
        first_task = asyncio.create_task(mark_and_hold())
        await first_write_done.wait()
        second_task = asyncio.create_task(start_and_hold(entered=second_entered))
    else:
        first_task = asyncio.create_task(start_and_hold())
        await first_write_done.wait()
        second_task = asyncio.create_task(mark_and_hold(entered=second_entered))
    await second_entered.wait()
    await asyncio.sleep(0)
    assert not second_task.done()
    release_first.set()
    first_result, second_result = await asyncio.wait_for(
        asyncio.gather(first_task, second_task), timeout=5
    )
    if winner == "marker":
        detail, mutation = first_result, second_result
        assert mutation.outcome == "blocked"
        assert mutation.block_reason == "cancellation"
        expected_status = "queued"
    else:
        mutation, detail = first_result, second_result
        assert mutation.operation.status == "running"
        expected_status = "running"

    cancellation_id = detail.attempt.cancellation_id
    try:
        assert len(detail.members) == len(memberships) + 1
        assert {member.initial_status for member in detail.members} == {
            expected_status
        }
        assert all(member.requires_run_termination for member in detail.members)
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT status, cancellation_id FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid)"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        assert len(rows) == len(memberships) + 1
        assert {row.status for row in rows} == {expected_status}
        assert {str(row.cancellation_id) for row in rows} == {cancellation_id}
    finally:
        await _delete_committed_feature_tree(
            migrated_engine,
            root_id=root_id,
            cancellation_id=cancellation_id,
        )


async def test_terminal_sensor_direct_cancel_is_idempotent_with_real_client(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-c3e-sensor-direct-cancel-{uuid4()}"
    created_at = datetime(2026, 7, 16, 1, tzinfo=UTC)
    finished_at = created_at + timedelta(seconds=1)
    record = _tracking_record(
        operation_key=SINGLE_MEMBER_OPERATION,
        run_id=run_id,
        status=DagsterRunStatus.CANCELED,
        created_at=created_at,
        started_at=None,
        finished_at=finished_at,
    )
    client = AsyncKorTravelMapClient(migrated_engine)
    async with AsyncSession(migrated_engine) as seed_session:
        memberships = await memberships_for_operation(
            seed_session, operation_key=SINGLE_MEMBER_OPERATION
        )

    first = await _apply_run_record(record, client)
    second = await _apply_run_record(record, client)

    async with AsyncSession(migrated_engine) as probe:
        rows = (
            await probe.execute(
                text(
                    "SELECT job_id, parent_job_id, status, current_stage, "
                    "dagster_run_status, finished_at "
                    "FROM ops.import_jobs WHERE dagster_run_id=:run_id "
                    "ORDER BY parent_job_id NULLS FIRST, job_id"
                ),
                {"run_id": run_id},
            )
        ).all()
        member_rows = (
            await probe.execute(
                text(
                    "SELECT member.provider_dataset_id, member.sync_scope, "
                    "member.operation_key FROM ops.import_job_datasets AS member "
                    "JOIN ops.import_jobs AS job ON job.job_id=member.job_id "
                    "WHERE job.dagster_run_id=:run_id"
                ),
                {"run_id": run_id},
            )
        ).all()
    root_id = str(rows[0].job_id)
    try:
        assert first == "applied"
        assert second == "blocked"
        assert rows[0].parent_job_id is None
        assert len(rows) == len(memberships) + 1
        assert {row.status for row in rows} == {"cancelled"}
        assert {row.current_stage for row in rows} == {"cancelled"}
        assert rows[0].dagster_run_status == "CANCELED"
        assert {row.finished_at for row in rows} == {finished_at}
        # 2회차 적용이 member identity를 다시 쓰지 않았다.
        assert {_triple(row) for row in member_rows} == {
            _membership_triple(member) for member in memberships
        }
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_terminal_sensor_respects_existing_cancellation_marker(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-c3e-sensor-marker-{uuid4()}"
    created_at = datetime(2026, 7, 16, 2, tzinfo=UTC)
    operation_key = SINGLE_MEMBER_OPERATION
    client = AsyncKorTravelMapClient(migrated_engine)
    memberships = await client.resolve_feature_operation_memberships(
        operation_key=operation_key
    )
    assert len(memberships) == 1
    queued = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_memberships=memberships,
        operation_key=operation_key,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    root_id = queued.operation.root_job_id
    async with AsyncSession(migrated_engine) as marker_session, marker_session.begin():
        scope = await resolve_pipeline_cancellation_scope(
            marker_session,
            kind="import_job",
            execution_id=root_id,
        )
        assert scope is not None
        detail = await create_pipeline_cancellation_attempt(
            marker_session,
            scope=scope,
            requested_by="admin:sensor-test",
            reason="marker must own terminal",
        )
    cancellation_id = detail.attempt.cancellation_id
    record = _tracking_record(
        operation_key=operation_key,
        run_id=run_id,
        status=DagsterRunStatus.CANCELED,
        created_at=created_at,
        started_at=None,
        finished_at=created_at + timedelta(seconds=1),
    )

    outcome = await _apply_run_record(record, client)

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT status, current_stage, dagster_run_status, "
                        "cancellation_id FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, job_id"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        assert outcome == "blocked"
        assert len(rows) == len(memberships) + 1
        assert {row.status for row in rows} == {"queued"}
        assert {row.current_stage for row in rows} == {"queued"}
        assert rows[0].dagster_run_status == "QUEUED"
        assert {str(row.cancellation_id) for row in rows} == {cancellation_id}
    finally:
        await _delete_committed_feature_tree(
            migrated_engine,
            root_id=root_id,
            cancellation_id=cancellation_id,
        )


async def test_terminal_sensor_preserves_partial_success_and_duplicate_delivery(
    migrated_engine: AsyncEngine,
) -> None:
    operation_key = MULTI_MEMBER_OPERATION
    run_id = f"run-c3e-sensor-partial-{uuid4()}"
    created_at = datetime(2026, 7, 16, 3, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = started_at + timedelta(seconds=2)
    client = AsyncKorTravelMapClient(migrated_engine)
    memberships = await client.resolve_feature_operation_memberships(
        operation_key=operation_key
    )
    await _apply_run_record(
        _tracking_record(
            operation_key=operation_key,
            run_id=run_id,
            status=DagsterRunStatus.STARTED,
            created_at=created_at,
            started_at=started_at,
            finished_at=None,
        ),
        client,
    )
    first_membership = memberships[0]
    completed = await client.finish_dagster_feature_membership(
        dagster_run_id=run_id,
        membership=first_membership,
    )
    root_id = completed.operation.root_job_id
    terminal_record = _tracking_record(
        operation_key=operation_key,
        run_id=run_id,
        status=DagsterRunStatus.FAILURE,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
    )

    first = await _apply_run_record(terminal_record, client)
    second = await _apply_run_record(terminal_record, client)

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(_TREE_WITH_MEMBERS_SQL),
                    {"root_id": root_id},
                )
            ).all()
        root = rows[0]
        children = rows[1:]
        assert first == "applied"
        assert second == "blocked"
        assert len(children) == len(memberships)
        assert root.status == "failed"
        assert root.dagster_run_status == "FAILURE"
        assert root.progress == 100 // len(memberships)
        assert [row.status for row in children].count("done") == 1
        assert [row.status for row in children].count("failed") == (
            len(memberships) - 1
        )
        done = next(row for row in children if row.status == "done")
        assert _membership_of(done) == first_membership
        assert done.current_stage == "completed"
        assert {row.current_stage for row in children if row.status == "failed"} == {
            "failed"
        }
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_periodic_reconcile_real_client_closes_partial_active_page_and_commits_cursor(
    migrated_engine: AsyncEngine,
) -> None:
    operation_key = MULTI_MEMBER_OPERATION
    run_id = f"run-c3e-periodic-partial-{uuid4()}"
    created_at = datetime(2026, 7, 15, 5, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = started_at + timedelta(seconds=2)
    client = AsyncKorTravelMapClient(migrated_engine)
    memberships = await client.resolve_feature_operation_memberships(
        operation_key=operation_key
    )
    started = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_memberships=memberships,
        operation_key=operation_key,
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    root_id = started.operation.root_job_id
    first_membership = memberships[0]
    await client.finish_dagster_feature_membership(
        dagster_run_id=run_id,
        membership=first_membership,
    )
    context = _PeriodicContext(
        [
            _tracking_record(
                operation_key=operation_key,
                run_id=run_id,
                status=DagsterRunStatus.FAILURE,
                created_at=created_at,
                started_at=started_at,
                finished_at=finished_at,
            )
        ]
    )

    await _reconcile_tick(context, client)

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(_TREE_WITH_MEMBERS_SQL),
                    {"root_id": root_id},
                )
            ).all()
        root = rows[0]
        children = rows[1:]
        committed = FeatureOperationReconcileCursor.from_json(
            context.updated_cursors[0]
        )
        assert root.status == "failed"
        assert root.dagster_run_status == "FAILURE"
        assert root.progress == 100 // len(memberships)
        assert [row.status for row in children].count("done") == 1
        assert [row.status for row in children].count("failed") == (
            len(memberships) - 1
        )
        done = next(row for row in children if row.status == "done")
        assert _membership_of(done) == first_membership
        assert len(context.updated_cursors) == 1
        assert committed.database is None
        assert context.log.errors == []
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_periodic_reconcile_marker_after_page_read_preserves_base(
    migrated_engine: AsyncEngine,
) -> None:
    operation_key = SINGLE_MEMBER_OPERATION
    run_id = f"run-c3e-periodic-marker-race-{uuid4()}"
    created_at = datetime(2026, 7, 15, 6, tzinfo=UTC)
    finished_at = created_at + timedelta(seconds=1)

    class MarkerAfterPageClient(AsyncKorTravelMapClient):
        cancellation_id: str | None = None

        async def list_reconcilable_dagster_feature_runs(
            self,
            *,
            cursor: Any,
            page_size: int = 200,
        ) -> Any:
            page = await super().list_reconcilable_dagster_feature_runs(
                cursor=cursor,
                page_size=page_size,
            )
            if self.cancellation_id is None:
                async with AsyncSession(migrated_engine) as session, session.begin():
                    scope = await resolve_pipeline_cancellation_scope(
                        session,
                        kind="import_job",
                        execution_id=root_id,
                    )
                    assert scope is not None
                    detail = await create_pipeline_cancellation_attempt(
                        session,
                        scope=scope,
                        requested_by="admin:periodic-race",
                        reason="marker wins after active page read",
                    )
                    self.cancellation_id = detail.attempt.cancellation_id
            return page

    client = MarkerAfterPageClient(migrated_engine)
    memberships = await client.resolve_feature_operation_memberships(
        operation_key=operation_key
    )
    queued = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_memberships=memberships,
        operation_key=operation_key,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    root_id = queued.operation.root_job_id
    context = _PeriodicContext(
        [
            _tracking_record(
                operation_key=operation_key,
                run_id=run_id,
                status=DagsterRunStatus.CANCELED,
                created_at=created_at,
                started_at=None,
                finished_at=finished_at,
            )
        ]
    )

    await _reconcile_tick(context, client)

    try:
        assert client.cancellation_id is not None
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT status, current_stage, dagster_run_status, "
                        "cancellation_id FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, job_id"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        assert len(rows) == len(memberships) + 1
        assert {row.status for row in rows} == {"queued"}
        assert {row.current_stage for row in rows} == {"queued"}
        assert rows[0].dagster_run_status == "QUEUED"
        assert {str(row.cancellation_id) for row in rows} == {
            client.cancellation_id
        }
        assert len(context.updated_cursors) == 1
        assert context.log.errors == []
    finally:
        await _delete_committed_feature_tree(
            migrated_engine,
            root_id=root_id,
            cancellation_id=client.cancellation_id,
        )


@pytest.mark.parametrize("winner", ["marker", "terminal"])
async def test_terminal_reconcile_and_marker_race_has_single_lock_order_winner(
    migrated_engine: AsyncEngine,
    winner: str,
) -> None:
    run_id = f"run-c3e-terminal-marker-race-{winner}-{uuid4()}"
    created_at = datetime(2026, 7, 15, 7, tzinfo=UTC)
    finished_at = created_at + timedelta(seconds=1)
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        memberships = await memberships_for_operation(
            setup, operation_key=SINGLE_MEMBER_OPERATION
        )
        queued = await ensure_dagster_feature_operation(
            setup,
            dagster_run_id=run_id,
            trigger_kind="schedule",
            selected_memberships=memberships,
            operation_key=SINGLE_MEMBER_OPERATION,
            engine_created_at=created_at,
            engine_started_at=None,
            observed_status="QUEUED",
        )
    root_id = queued.operation.root_job_id
    first_write_done = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def mark_and_hold(*, entered: asyncio.Event | None = None) -> Any:
        async with AsyncSession(migrated_engine) as session, session.begin():
            if entered is not None:
                entered.set()
            scope = await resolve_pipeline_cancellation_scope(
                session,
                kind="import_job",
                execution_id=root_id,
            )
            assert scope is not None
            detail = await create_pipeline_cancellation_attempt(
                session,
                scope=scope,
                requested_by="admin:terminal-race",
                reason=winner,
            )
            first_write_done.set()
            await release_first.wait()
            return detail

    async def terminal_and_hold(*, entered: asyncio.Event | None = None) -> Any:
        async with AsyncSession(migrated_engine) as session, session.begin():
            if entered is not None:
                entered.set()
            mutation = await reconcile_dagster_feature_run(
                session,
                dagster_run_id=run_id,
                trigger_kind="schedule",
                terminal_status="CANCELED",
                selected_memberships=memberships,
                operation_key=SINGLE_MEMBER_OPERATION,
                engine_created_at=created_at,
                engine_started_at=None,
                engine_finished_at=finished_at,
                error={"kind": "terminal-marker-race"},
            )
            first_write_done.set()
            await release_first.wait()
            return mutation

    if winner == "marker":
        first_task = asyncio.create_task(mark_and_hold())
        await first_write_done.wait()
        second_task = asyncio.create_task(
            terminal_and_hold(entered=second_entered)
        )
    else:
        first_task = asyncio.create_task(terminal_and_hold())
        await first_write_done.wait()
        second_task = asyncio.create_task(mark_and_hold(entered=second_entered))
    await second_entered.wait()
    await asyncio.sleep(0)
    assert not second_task.done()
    release_first.set()
    first_result, second_result = await asyncio.wait_for(
        asyncio.gather(first_task, second_task),
        timeout=5,
    )
    if winner == "marker":
        detail, mutation = first_result, second_result
        assert mutation.outcome == "blocked"
        assert mutation.block_reason == "cancellation"
        expected_status = "queued"
        expected_raw_status = "QUEUED"
    else:
        mutation, detail = first_result, second_result
        assert mutation.outcome == "applied"
        expected_status = "cancelled"
        expected_raw_status = "CANCELED"
    cancellation_id = detail.attempt.cancellation_id

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT status, dagster_run_status, cancellation_id "
                        "FROM ops.import_jobs WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, job_id"
                    ),
                    {"root_id": root_id},
                )
            ).all()
        assert len(rows) == 2
        assert {row.status for row in rows} == {expected_status}
        assert rows[0].dagster_run_status == expected_raw_status
        assert {str(row.cancellation_id) for row in rows} == {cancellation_id}
    finally:
        await _delete_committed_feature_tree(
            migrated_engine,
            root_id=root_id,
            cancellation_id=cancellation_id,
        )


async def test_terminal_sensor_selection_mismatch_closes_active_tree(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-c3e-sensor-selection-mismatch-{uuid4()}"
    created_at = datetime(2026, 7, 16, 4, tzinfo=UTC)
    finished_at = created_at + timedelta(seconds=1)
    operation_key = MULTI_MEMBER_OPERATION
    client = AsyncKorTravelMapClient(migrated_engine)
    memberships = await client.resolve_feature_operation_memberships(
        operation_key=operation_key
    )
    # drift가 성립하려면 얼린 selection이 관측 selection의 진부분집합이어야 한다.
    assert len(memberships) > 1
    stored = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_memberships=memberships[:1],
        operation_key=operation_key,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="NOT_STARTED",
    )
    root_id = stored.operation.root_job_id

    outcome = await _apply_run_record(
        _tracking_record(
            operation_key=operation_key,
            run_id=run_id,
            status=DagsterRunStatus.SUCCESS,
            created_at=created_at,
            started_at=None,
            finished_at=finished_at,
        ),
        client,
    )

    try:
        async with AsyncSession(migrated_engine) as probe:
            rows = (
                await probe.execute(
                    text(
                        "SELECT parent_job_id, status, current_stage, "
                        "dagster_run_status FROM ops.import_jobs "
                        "WHERE job_id=CAST(:root_id AS uuid) "
                        "OR parent_job_id=CAST(:root_id AS uuid) "
                        "ORDER BY parent_job_id NULLS FIRST, job_id"
                    ),
                    {"root_id": root_id},
                )
            ).all()
            tracking_log_count = await probe.scalar(
                text(
                    "SELECT count(*) FROM ops.system_log "
                    "WHERE event='feature_operation.tracking_invariant' "
                    "AND detail->>'dagster_run_id'=:run_id"
                ),
                {"run_id": run_id},
            )
            tracking_detail = (
                await probe.execute(
                    text(
                        "SELECT detail FROM ops.system_log "
                        "WHERE event='feature_operation.tracking_invariant' "
                        "AND detail->>'dagster_run_id'=:run_id "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"run_id": run_id},
                )
            ).scalar_one()
        assert outcome == "applied"
        assert len(rows) == 2
        assert {row.status for row in rows} == {"failed"}
        assert {row.current_stage for row in rows} == {"tracking_invariant"}
        assert rows[0].dagster_run_status == "SUCCESS"
        assert int(tracking_log_count or 0) == 1
        # SUCCESS terminal은 non_done_members만으로도 tracking_invariant가 된다.
        # 이 회귀가 지키는 축은 그것이 아니라 **selection drift**이므로 mismatch에
        # selected_memberships가 실제로 들어 있음을 못박는다.
        assert tracking_detail["mismatches"]["selected_memberships"]["actual"] == [
            {
                "provider_dataset_id": memberships[0].provider_dataset_id,
                "sync_scope": memberships[0].sync_scope,
                "operation_key": memberships[0].operation_key,
            }
        ]
        assert tracking_detail["mismatches"]["selected_memberships"]["expected"] == [
            {
                "provider_dataset_id": member.provider_dataset_id,
                "sync_scope": member.sync_scope,
                "operation_key": member.operation_key,
            }
            for member in memberships
        ]
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_generic_claim_and_stale_recovery_ignore_feature_operations(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 3, tzinfo=UTC)
    # 두 ensure가 반드시 **동일한** tuple을 써야 한다 — 다르면 identity conflict다.
    memberships = await memberships_for_operation(migrated_session, limit=1)
    await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-owned",
        trigger_kind="sensor",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    assert await claim_next_import_job(migrated_session) is None

    started_at = created_at + timedelta(seconds=1)
    await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-owned",
        trigger_kind="sensor",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    assert await recover_stale_running_jobs(migrated_session, stale_after=None) == 0
    # 0을 돌려줬다는 것만으로는 트리가 살아남았음을 못 박지 못한다.
    running_count = await migrated_session.scalar(
        text(
            "SELECT count(*) FROM ops.import_jobs "
            "WHERE dagster_run_id='run-c3e-owned' AND status='running'"
        )
    )
    assert int(running_count or 0) == len(memberships) + 1


async def test_active_root_sweep_uses_keyset_and_wraps_at_end(
    migrated_session: AsyncSession,
) -> None:
    memberships = await memberships_for_operation(migrated_session, limit=2)
    assert len(memberships) == 2
    for index, membership in enumerate(memberships):
        await ensure_dagster_feature_operation(
            migrated_session,
            dagster_run_id=f"run-c3e-page-{index}",
            trigger_kind="system",
            selected_memberships=(membership,),
            operation_key=MULTI_MEMBER_OPERATION,
            engine_created_at=datetime(2026, 7, 15, 4 + index, tzinfo=UTC),
            engine_started_at=None,
            observed_status="QUEUED",
        )
    first = await list_reconcilable_dagster_feature_runs(
        migrated_session, cursor=None, page_size=1
    )
    assert len(first.items) == 1
    assert first.next_cursor is not None
    second = await list_reconcilable_dagster_feature_runs(
        migrated_session, cursor=first.next_cursor, page_size=1
    )
    assert len(second.items) == 1
    assert second.next_cursor is None
    # keyset은 created_at 오름차순이다 — 크기만이 아니라 순서까지 못박는다.
    assert first.items[0].dagster_run_id == "run-c3e-page-0"
    assert second.items[0].dagster_run_id == "run-c3e-page-1"


async def test_reserved_feature_tree_rejects_generic_writers(
    migrated_session: AsyncSession,
) -> None:
    memberships = await memberships_for_operation(migrated_session, limit=2)
    assert len(memberships) == 2
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-reserved",
        trigger_kind="manual",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=datetime(2026, 7, 15, 6, tzinfo=UTC),
        engine_started_at=None,
        observed_status="QUEUED",
    )
    root_id = operation.operation.root_job_id
    child, sibling = (
        operation.operation.members[0],
        operation.operation.members[1],
    )

    with pytest.raises(FeatureOperationInvariantConflict):
        await enqueue_unpaired_import_job(
            migrated_session,
            kind="generic_child",
            parent_job_id=root_id,
        )
    with pytest.raises(FeatureOperationInvariantConflict):
        await heartbeat_import_job(migrated_session, root_id, progress=10)
    with pytest.raises(FeatureOperationInvariantConflict):
        # 형제 member의 identity를 이 job의 event로 밀어넣기.
        await record_import_job_event(
            migrated_session,
            child.job_id,
            level="info",
            message="mismatched membership",
            import_job_dataset_id=sibling.import_job_dataset_id,
        )
    with pytest.raises(FeatureOperationInvariantConflict):
        # dataset member job의 event는 membership 없이 못 쓴다.
        await record_import_job_event(
            migrated_session,
            child.job_id,
            level="info",
            message="membership-less member event",
            import_job_dataset_id=None,
        )


async def test_attempt_event_inherits_pair_without_mutating_member_identity(
    migrated_session: AsyncSession,
) -> None:
    memberships = await memberships_for_operation(migrated_session, limit=1)
    membership = memberships[0]
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-attempt-audit",
        trigger_kind="manual",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=datetime(2026, 7, 15, 6, tzinfo=UTC),
        engine_started_at=None,
        observed_status="QUEUED",
    )
    member = operation.operation.members[0]

    event = await append_dagster_feature_attempt_event(
        migrated_session,
        dagster_run_id="run-c3e-attempt-audit",
        membership=membership,
        attempt_number=1,
        outcome="retryable_failure",
        error={"code": "timeout"},
    )
    stored = (
        await migrated_session.execute(
            text(
                "SELECT provider_dataset_id, sync_scope, operation_key "
                "FROM ops.import_job_datasets "
                "WHERE job_id=CAST(:job_id AS uuid)"
            ),
            {"job_id": member.job_id},
        )
    ).one()

    assert event.job_id == member.job_id
    assert event.import_job_dataset_id == member.import_job_dataset_id
    assert (
        event.payload["provider_dataset_id"],
        event.payload["sync_scope"],
        event.payload["operation_key"],
    ) == _membership_triple(membership)
    assert _triple(stored) == _membership_triple(membership)


async def test_run_backed_queued_cancellation_freezes_one_run_and_all_members(
    migrated_session: AsyncSession,
) -> None:
    memberships = await memberships_for_operation(migrated_session, limit=2)
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-queued-cancel",
        trigger_kind="manual",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=datetime(2026, 7, 15, 7, tzinfo=UTC),
        engine_started_at=None,
        observed_status="QUEUED",
    )
    scope = await resolve_pipeline_cancellation_scope(
        migrated_session,
        kind="import_job",
        execution_id=operation.operation.root_job_id,
    )
    assert scope is not None
    assert len(scope.members) == 3
    assert all(member.requires_run_termination for member in scope.members)

    detail = await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=scope,
        requested_by="admin:test",
        reason="queued feature cancellation",
    )
    assert len(detail.runs) == 1
    assert detail.runs[0].result == "pending"
    assert all(member.requires_run_termination for member in detail.members)

    with pytest.raises(PipelineCancellationInvariantError):
        await cancel_queued_pipeline_cancellation_member(
            migrated_session,
            cancellation_id=detail.attempt.cancellation_id,
            job_id=detail.members[0].job_id,
        )


async def test_feature_identity_trigger_blocks_update_delete_and_bad_parent(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 8, tzinfo=UTC)
    memberships = await memberships_for_operation(migrated_session, limit=1)
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-identity-trigger",
        trigger_kind="manual",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    root_id = operation.operation.root_job_id
    child_id = operation.operation.members[0].job_id

    # 살아 있는 DB 가드만 넣는다. 성공하는 문장을 루프에 섞으면 savepoint가 release되며
    # 트리가 부서져 뒤 문장들이 0행 매칭으로 조용히 통과한다.
    #
    # subject_removed(=DB 가드가 더 이상 없는 절, 실측):
    #   * ``UPDATE ops.import_jobs SET trigger_kind='system'`` — 0091의
    #     ``_replace_pre_tvn33_ownership_guards``가 옛
    #     ``ck_import_jobs_feature_operation_identity_immutable``을 DROP했고, 대체
    #     트리거는 kind/dataset_membership_mode/root_id/root_kind/payload만 본다.
    #   * ``UPDATE ops.import_jobs SET operation_key=...`` (root) — 역시 통과한다.
    #   * member를 카탈로그에 실재하는 다른 operation scope로 옮기는 UPDATE — 통과.
    #   이것들을 지금 지키는 것은 DB가 아니라 응용이다
    #   (``_raise_identity_conflict`` / reconcile의 tracking_invariant 경로). 그 커버는
    #   ``test_every_terminal_identity_mismatch_closes_tracking_invariant``가 맡는다.
    statements: tuple[tuple[str, dict[str, Any]], ...] = (
        (
            "UPDATE ops.import_jobs SET kind='provider_load' "
            "WHERE job_id=CAST(:id AS uuid)",
            {"id": root_id},
        ),
        (
            "UPDATE ops.import_jobs SET dataset_membership_mode='single' "
            "WHERE job_id=CAST(:id AS uuid)",
            {"id": root_id},
        ),
        (
            "UPDATE ops.import_jobs SET dagster_run_id='other-run' "
            "WHERE job_id=CAST(:id AS uuid)",
            {"id": child_id},
        ),
        (
            "UPDATE ops.import_jobs SET created_at=CAST(:created_at AS timestamptz) "
            "WHERE job_id=CAST(:id AS uuid)",
            {"id": child_id, "created_at": created_at + timedelta(seconds=1)},
        ),
        (
            "UPDATE ops.import_jobs SET parent_job_id=NULL "
            "WHERE job_id=CAST(:id AS uuid)",
            {"id": child_id},
        ),
        (
            "UPDATE ops.import_job_datasets SET operation_key='no_such_operation' "
            "WHERE job_id=CAST(:id AS uuid)",
            {"id": child_id},
        ),
        (
            "UPDATE ops.import_job_datasets SET sync_scope='no_such_scope' "
            "WHERE job_id=CAST(:id AS uuid)",
            {"id": child_id},
        ),
        (
            "DELETE FROM ops.import_jobs WHERE job_id=CAST(:id AS uuid)",
            {"id": root_id},
        ),
    )
    for statement, params in statements:
        with pytest.raises(IntegrityError):
            async with migrated_session.begin_nested():
                await migrated_session.execute(text(statement), params)

    for bad_run_id, bad_created_at in (
        ("other-run", created_at),
        ("run-c3e-identity-trigger", created_at + timedelta(seconds=1)),
    ):
        with pytest.raises(IntegrityError):
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        """
                        INSERT INTO ops.import_jobs (
                          kind, parent_job_id, payload, status, dagster_run_id,
                          dataset_membership_mode, created_at
                        ) VALUES (
                          'provider_feature_load', CAST(:root_id AS uuid), '{}'::jsonb,
                          'queued', :run_id, 'single',
                          CAST(:created_at AS timestamptz)
                        )
                        """
                    ),
                    {
                        "root_id": root_id,
                        "run_id": bad_run_id,
                        "created_at": bad_created_at,
                    },
                )

    root_after = (
        await migrated_session.execute(
            text(
                "SELECT kind, dagster_run_id, operation_key, created_at "
                "FROM ops.import_jobs WHERE job_id=CAST(:id AS uuid)"
            ),
            {"id": root_id},
        )
    ).one()
    assert root_after.kind == "provider_feature_load_run"
    assert root_after.dagster_run_id == "run-c3e-identity-trigger"
    assert root_after.operation_key == MULTI_MEMBER_OPERATION
    assert root_after.created_at == created_at


@pytest.mark.parametrize("terminal_status", ["SUCCESS", "FAILURE", "CANCELED"])
async def test_every_terminal_identity_mismatch_closes_tracking_invariant(
    migrated_session: AsyncSession,
    terminal_status: str,
) -> None:
    created_at = datetime(2026, 7, 15, 9, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    # registry_version이 사라졌고 reconcile은 membership 전원이 들어온 operation_key와
    # 같기를 강제하므로(_require_operation_memberships), operation_key와
    # selected_memberships는 이제 항상 함께 어긋난다.
    stored_memberships = await memberships_for_operation(migrated_session, limit=1)
    incoming_memberships = await memberships_for_operation(
        migrated_session, operation_key=SINGLE_MEMBER_OPERATION
    )
    operation = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=f"run-c3e-mismatch-{terminal_status.lower()}",
        trigger_kind="sensor",
        selected_memberships=stored_memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    result = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id=operation.operation.dagster_run_id,
        trigger_kind="manual",
        terminal_status=terminal_status,
        selected_memberships=incoming_memberships,
        operation_key=SINGLE_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=started_at,
        engine_finished_at=started_at + timedelta(seconds=1),
        error=None,
    )

    assert result.operation.status == "failed"
    assert result.operation.current_stage == "tracking_invariant"
    assert result.operation.dagster_run_status == terminal_status
    assert {member.status for member in result.operation.members} == {"failed"}
    log = (
        await migrated_session.execute(
            text(
                """
                SELECT detail FROM ops.system_log
                WHERE event = 'feature_operation.tracking_invariant'
                  AND detail->>'dagster_run_id' = :run_id
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"run_id": operation.operation.dagster_run_id},
        )
    ).scalar_one()
    expected_mismatch_keys = {
        "operation_key",
        "selected_memberships",
        "trigger_kind",
    }
    if terminal_status == "SUCCESS":
        expected_mismatch_keys.add("non_done_members")
    assert set(log["mismatches"]) == expected_mismatch_keys
    assert log["mismatches"]["operation_key"] == {
        "expected": SINGLE_MEMBER_OPERATION,
        "actual": MULTI_MEMBER_OPERATION,
    }
    assert log["mismatches"]["trigger_kind"] == {
        "expected": "manual",
        "actual": "sensor",
    }
    assert log["mismatches"]["selected_memberships"] == {
        "expected": [
            {
                "provider_dataset_id": member.provider_dataset_id,
                "sync_scope": member.sync_scope,
                "operation_key": member.operation_key,
            }
            for member in incoming_memberships
        ],
        "actual": [
            {
                "provider_dataset_id": member.provider_dataset_id,
                "sync_scope": member.sync_scope,
                "operation_key": member.operation_key,
            }
            for member in stored_memberships
        ],
    }
    # 실패 처리가 저장된 identity를 덮어쓰지 않았다.
    assert result.operation.operation_key == MULTI_MEMBER_OPERATION
    assert (
        tuple(member.membership for member in result.operation.members)
        == stored_memberships
    )


async def test_terminal_finish_cannot_precede_stored_engine_start(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 10, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=10)
    memberships = await memberships_for_operation(migrated_session, limit=1)
    await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-invalid-finish",
        trigger_kind="manual",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    reconciled = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id="run-c3e-invalid-finish",
        trigger_kind="manual",
        terminal_status="FAILURE",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=None,
        engine_finished_at=created_at + timedelta(seconds=5),
        error=None,
    )
    assert reconciled.operation.status == "failed"
    assert reconciled.operation.current_stage == "tracking_invariant"
    assert reconciled.operation.started_at == started_at
    assert reconciled.operation.finished_at is None
    assert {member.status for member in reconciled.operation.members} == {"failed"}
    assert all(member.finished_at is None for member in reconciled.operation.members)


async def test_terminal_created_time_drift_closes_without_invented_finish(
    migrated_session: AsyncSession,
) -> None:
    stored_created_at = datetime(2026, 7, 15, 11, tzinfo=UTC)
    memberships = await memberships_for_operation(migrated_session, limit=1)
    ensured = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-created-time-drift",
        trigger_kind="sensor",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=stored_created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    reconciled = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id=ensured.operation.dagster_run_id,
        trigger_kind="sensor",
        terminal_status="CANCELED",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=stored_created_at - timedelta(hours=1),
        engine_started_at=None,
        engine_finished_at=stored_created_at - timedelta(minutes=30),
        error=None,
    )

    assert reconciled.operation.status == "failed"
    assert reconciled.operation.current_stage == "tracking_invariant"
    assert reconciled.operation.dagster_run_status == "CANCELED"
    assert reconciled.operation.started_at is None
    assert reconciled.operation.finished_at is None
    assert {member.status for member in reconciled.operation.members} == {"failed"}
    active_count = await migrated_session.scalar(
        text(_ACTIVE_TREE_COUNT_SQL),
        {"root_id": ensured.operation.root_job_id},
    )
    assert int(active_count) == 0


async def test_terminal_detects_divergent_root_and_child_start_times(
    migrated_session: AsyncSession,
) -> None:
    created_at = datetime(2026, 7, 15, 12, tzinfo=UTC)
    incoming_started_at = created_at + timedelta(seconds=10)
    stored_child_started_at = created_at + timedelta(seconds=12)
    memberships = await memberships_for_operation(migrated_session, limit=1)
    ensured = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id="run-c3e-divergent-child-start",
        trigger_kind="sensor",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=None,
        observed_status="QUEUED",
    )
    child_id = ensured.operation.members[0].job_id
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET started_at = :started_at "
            "WHERE job_id = CAST(:job_id AS uuid)"
        ),
        {"job_id": child_id, "started_at": stored_child_started_at},
    )

    reconciled = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id=ensured.operation.dagster_run_id,
        trigger_kind="sensor",
        terminal_status="FAILURE",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=incoming_started_at,
        engine_finished_at=created_at + timedelta(seconds=13),
        error=None,
    )

    assert reconciled.operation.status == "failed"
    assert reconciled.operation.current_stage == "tracking_invariant"
    assert reconciled.operation.started_at is None
    assert reconciled.operation.finished_at is None
    assert reconciled.operation.members[0].started_at == stored_child_started_at
    assert reconciled.operation.members[0].finished_at is None


@pytest.mark.parametrize("stored_child_status", ["failed", "cancelled"])
async def test_success_preserves_terminal_non_done_child_and_fails_root_tracking(
    migrated_session: AsyncSession,
    stored_child_status: str,
) -> None:
    created_at = datetime(2026, 7, 15, 13, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = created_at + timedelta(seconds=5)
    memberships = await memberships_for_operation(migrated_session, limit=1)
    run_id = f"run-c3e-success-{stored_child_status}"
    ensured = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=run_id,
        trigger_kind="sensor",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    child_id = ensured.operation.members[0].job_id
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs "
            "SET status=:status, current_stage=:status, finished_at=:finished_at "
            "WHERE job_id=CAST(:job_id AS uuid)"
        ),
        {
            "job_id": child_id,
            "status": stored_child_status,
            "finished_at": finished_at,
        },
    )

    reconciled = await reconcile_dagster_feature_run(
        migrated_session,
        dagster_run_id=ensured.operation.dagster_run_id,
        trigger_kind="sensor",
        terminal_status="SUCCESS",
        selected_memberships=memberships,
        operation_key=MULTI_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=started_at,
        engine_finished_at=finished_at,
        error=None,
    )

    assert reconciled.operation.status == "failed"
    assert reconciled.operation.current_stage == "tracking_invariant"
    assert reconciled.operation.dagster_run_status == "SUCCESS"
    assert reconciled.operation.finished_at == finished_at
    assert reconciled.operation.members[0].status == stored_child_status
    assert reconciled.operation.members[0].finished_at == finished_at
    # root가 왜 실패했는지의 근거가 로그로 남았다.
    non_done_log_count = await migrated_session.scalar(
        text(
            """
            SELECT count(*) FROM ops.system_log
            WHERE event = 'feature_operation.tracking_invariant'
              AND detail->>'dagster_run_id' = :run_id
              AND detail #> '{mismatches,non_done_members}' IS NOT NULL
            """
        ),
        {"run_id": run_id},
    )
    assert int(non_done_log_count or 0) == 1


def test_feature_load_schedule_tags_carry_trigger_kind() -> None:
    """schedule launch는 trigger tag를 **찍는다** — 안 찍는다는 진술은 거짓이다.

    ``_feature_load_schedule_tags``가 만드는 dict는 ScheduleDefinition의 ``tags``와
    coalescing schedule의 ``RunRequest(tags=...)`` 양쪽에 그대로 실린다. 그래서
    schedule로 뜬 run에는 ``kor_travel_map.trigger_kind``가 항상 있다.

    trigger tag가 없는 실재 모양은 job 정의 tag만 상속하는 job 단위 수동 launch다 —
    ``_feature_load_definition_tags``는 operation_key(+ 런타임 상한)만 찍는다.
    """
    specs = {spec.job_name: spec for spec in FEATURE_LOAD_SCHEDULE_SPECS}
    assert specs, "feature-load schedule spec이 비었다"
    for spec in specs.values():
        assert _feature_load_schedule_tags(spec)[_TRIGGER_KIND_TAG] == "schedule"
        assert _TRIGGER_KIND_TAG not in _feature_load_definition_tags(spec)
        assert _feature_load_definition_tags(spec)[_OPERATION_KEY_TAG] == spec.job_name


async def test_run_without_trigger_tag_is_tracked_not_silently_dropped(
    migrated_engine: AsyncEngine,
) -> None:
    """trigger tag 없는 run(job 단위 수동 launch)도 **추적된다**.

    ``_trigger_kind()``는 trigger tag가 없으면 operation tag만 보고 ``"schedule"``을
    돌려준다. 그 fallback이 사라지면 ``_guard_from_context_async``가
    ``operation_key=None`` 인 guard를 만들고, ``ensure``와
    ``ensure_authoritative_feature_operation_guard``는 그 guard에서 아무것도 쓰지 않고
    그대로 돌아온다. 그러면 **추적 레코드가 하나도 생기지 않는다** — root도 member도.
    (run이 통째로 조용히 지나가는 것은 아니다. sync state를 쓰는 asset은
    ``assets._exact_sync_membership``과 ``kma_weather._exact_kma_sync_membership``에서
    ``operation_key_missing``으로 죽는다. 하지만 그 raise는 추적 행을 만들어 주지
    않으므로, 어느 쪽이든 이 run의 추적은 사라진다.)

    그래서 여기서는 guard 하나를 검증하는 게 아니라 resource init 경로를 그대로
    태우고 **DB에 행이 생겼는지**를 본다. fallback을 ``return None``으로 바꾸면
    root 조회가 0건이 되어 이 단언이 깨진다(mutation으로 실증).
    """
    client = AsyncKorTravelMapClient(migrated_engine)
    run_id = f"run-c3e-no-trigger-tag-{uuid4()}"
    tags = {_OPERATION_KEY_TAG: SINGLE_MEMBER_OPERATION}
    assert _TRIGGER_KIND_TAG not in tags

    guard = await _guard_from_context_async(
        _resource_init_context(client, run_id=run_id, tags=tags)
    )

    assert guard.operation_key == SINGLE_MEMBER_OPERATION, (
        "trigger tag가 없다는 이유로 guard가 추적을 포기했다"
    )
    assert guard.trigger_kind == "schedule"
    await guard.ensure()

    async with AsyncSession(migrated_engine) as check:
        root_id = await check.scalar(
            text(
                "SELECT job_id FROM ops.import_jobs "
                "WHERE kind = 'provider_feature_load_run' AND dagster_run_id = :run_id"
            ),
            {"run_id": run_id},
        )
        assert root_id is not None, "추적 root가 만들어지지 않았다 — run이 통째로 미추적이다"
        members = (
            await check.execute(text(_CHILD_MEMBERS_SQL), {"root_id": str(root_id)})
        ).all()
    assert [
        ProviderDatasetOperationMembership(
            provider_dataset_id=int(row.provider_dataset_id),
            sync_scope=str(row.sync_scope),
            operation_key=str(row.operation_key),
        )
        for row in members
    ] == list(guard.memberships)


async def test_guard_rejects_run_whose_live_manifest_tag_moved(
    migrated_engine: AsyncEngine,
) -> None:
    """I/O 직전 재검증은 실행 manifest 선언이 바뀐 run을 거부한다.

    guard는 resource init에서 manifest를 frozen하고, provider I/O 직전에 실제 run
    tag를 다시 읽어 대조한다. operation_key/trigger_kind만 대조하고 manifest 선언을
    빼면, 선언이 바뀐 run이 frozen selection 그대로 진행해 실행 대상과 DB member가
    갈린다.
    """
    base_client = AsyncKorTravelMapClient(migrated_engine)
    async with AsyncSession(migrated_engine) as setup:
        memberships = await memberships_for_operation(
            setup, operation_key=SINGLE_MEMBER_OPERATION
        )
    probe = _RecordingOperationClient(base_client)
    guard = _tracking_guard(
        probe,
        operation_key=SINGLE_MEMBER_OPERATION,
        memberships=memberships,
        run_id=f"run-c3e-manifest-moved-{uuid4()}",
        extra_tags={
            EXECUTION_SCOPES_TAG: json.dumps(
                [
                    {
                        "provider": "python-mois-api",
                        "dataset_key": "mois_license_features_bulk",
                        "sync_scope": "dataset_wide",
                    }
                ]
            )
        },
    )
    # guard 자신은 선언 없이(=operation 전체) frozen된 상태다.
    assert guard.declared_scopes is None

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        await ensure_authoritative_feature_operation_guard(
            _tracking_context(guard, retry_number=0),
            boundary="test_manifest_moved",
        )

    assert excinfo.value.reason == "execution_scopes_mismatch"
    assert not probe.ensure_mutations, "거부해야 할 run이 operation을 전진시켰다"


async def test_multi_dataset_operation_run_freezes_only_its_declared_dataset(
    migrated_engine: AsyncEngine,
) -> None:
    """dataset 5개를 묶은 operation의 run이 자기 dataset 1개만 frozen한다(KNPS).

    ``feature_place_knps_points_job``은 dataset 5개에 걸쳐 있지만 asset은 run 1회에
    ``knps_point_dataset_key`` 하나만 적재한다. run이 실행 manifest를 선언하지 않으면
    guard가 member 5개를 running으로 만들어 놓고 4개가 끝나지 않아, terminal
    reconcile이 operation을 ``tracking_invariant``로 떨어뜨린다.

    그래서 schedule spec이 실행 scope를 선언하고 guard가 그 선언만 frozen한다.
    이 테스트는 프로덕션 schedule tag를 그대로 써서 그 경로를 밟는다 — 테스트가
    자기 tag를 지어내면 선언이 사라져도 조용히 통과한다.
    """
    client = AsyncKorTravelMapClient(migrated_engine)
    spec = _schedule_spec("feature_place_knps_points_job")
    tags = _feature_load_schedule_tags(spec)
    assert EXECUTION_SCOPES_TAG in tags, "schedule이 실행 manifest를 선언하지 않았다"

    async with AsyncSession(migrated_engine) as setup:
        executable = await memberships_for_operation(
            setup, operation_key="feature_place_knps_points_job"
        )
        declared = await membership_for_dataset(
            setup,
            provider=KNPS_PROVIDER_NAME,
            # dataset key는 운영자 설정에서 오므로(``knps_schedule_binding``) 테스트가
            # 사본을 들지 않고 spec이 선언한 값을 그대로 쓴다.
            dataset_key=spec.execution_scopes[0].dataset_key,
            operation_key="feature_place_knps_points_job",
            sync_scope="dataset_wide",
        )
    # 전제: 이 operation은 정말로 dataset 여러 개를 묶는다.
    assert len(executable) == 5

    run_id = f"run-c3e-knps-manifest-{uuid4()}"
    guard = await _guard_from_context_async(
        _resource_init_context(client, run_id=run_id, tags=tags)
    )

    assert guard.memberships == (declared,)
    await guard.ensure()

    # guard를 통과해 asset 본문까지 간다 — 예전에는 여기서
    # ``operation_requires_exactly_one_membership``으로 죽었다.
    body_calls: list[str] = []

    async def _body(ctx: Any) -> str:
        body_calls.append(ctx.job_name)
        return "loaded"

    result = await run_tracked_feature_asset(
        _tracking_context(guard, retry_number=0), _body
    )
    assert result == "loaded"
    assert body_calls == ["feature_place_knps_points_job"]

    async with AsyncSession(migrated_engine) as check:
        root_id = str(
            await check.scalar(
                text(
                    "SELECT job_id FROM ops.import_jobs "
                    "WHERE kind = 'provider_feature_load_run' "
                    "AND dagster_run_id = :run_id"
                ),
                {"run_id": run_id},
            )
        )
        members = (
            await check.execute(text(_CHILD_MEMBERS_SQL), {"root_id": root_id})
        ).all()
        root_status = await check.scalar(
            text("SELECT status FROM ops.import_jobs WHERE job_id = CAST(:id AS uuid)"),
            {"id": root_id},
        )
    # 실행하지 않을 dataset 4개는 애초에 running으로 만들어지지 않았다.
    assert len(members) == 1
    assert int(members[0].provider_dataset_id) == declared.provider_dataset_id
    # asset이 끝난 시점에 미완료 member는 0이다 — 고아 running member가 없다.
    assert [row.status for row in members] == ["done"]
    # root는 아직 running이다. 이건 고아가 아니라 설계다 — root의 terminal 전이는
    # Dagster run이 끝난 뒤 reconcile sensor가 소유한다
    # (``test_reconcile_sensor_uses_the_same_manifest_as_the_run``이 그 마무리를 건다).
    assert root_status == "running"


async def test_asset_sync_state_accepts_a_narrowed_manifest_but_not_a_foreign_dataset(
    migrated_engine: AsyncEngine,
) -> None:
    """``_exact_sync_membership``의 drift 검사는 부분집합이다 — 그리고 거기까지다.

    이 게이트는 sync-state cursor를 쓸 exact member를 고르는 자리다. 검사를
    "manifest == 실행 가능 집합"으로 두면, dataset 5개를 묶은 KNPS operation의 run은
    manifest가 1건이므로 **모든 적재가 여기서** ``membership_snapshot_changed``로
    죽는다(``_load`` → ``_record_feature_sync_success`` → 이 함수).

    부분집합으로 완화한 대신 좁히기는 그대로여야 한다. 그래서 두 축을 함께 건다:
    선언한 dataset은 통과하고, 같은 operation의 **다른** dataset은 manifest 밖으로
    거부된다. 뒤 단언이 없으면 완화가 "아무 dataset이나 통과"로 미끄러져도 앞
    단언만으로는 잡히지 않는다.
    """
    client = AsyncKorTravelMapClient(migrated_engine)
    spec = _schedule_spec("feature_place_knps_points_job")
    tags = _feature_load_schedule_tags(spec)
    declared_key = spec.execution_scopes[0].dataset_key

    async with AsyncSession(migrated_engine) as setup:
        executable = await memberships_for_operation(
            setup, operation_key="feature_place_knps_points_job"
        )
        declared = await membership_for_dataset(
            setup,
            provider=KNPS_PROVIDER_NAME,
            dataset_key=declared_key,
            operation_key="feature_place_knps_points_job",
            sync_scope="dataset_wide",
        )
    # 전제: manifest(1건)와 실행 가능 집합(5건)이 정말로 다르다.
    assert len(executable) > 1

    guard = await _guard_from_context_async(
        _resource_init_context(
            client, run_id=f"run-c3e-knps-sync-state-{uuid4()}", tags=tags
        )
    )
    assert guard.memberships == (declared,)
    context = _tracking_context(guard, retry_number=0)

    resolved = await _exact_sync_membership(
        context,
        client,
        boundary="feature_sync_state",
        provider=KNPS_PROVIDER_NAME,
        dataset_key=declared_key,
    )
    assert resolved == declared

    foreign_key = next(
        key for key in sorted(KNPS_PLACE_DATASETS) if key != declared_key
    )
    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        await _exact_sync_membership(
            context,
            client,
            boundary="feature_sync_state",
            provider=KNPS_PROVIDER_NAME,
            dataset_key=foreign_key,
        )
    assert excinfo.value.reason == "membership_outside_guard_snapshot"


@asynccontextmanager
async def _operation_disabled_in_catalog(
    engine: AsyncEngine,
    *,
    operation_key: str,
) -> AsyncIterator[None]:
    """운영자 토글과 같은 경로로 operation을 잠시 disable한다.

    ``provider_dataset_operations.is_enabled``는 canonical resolver 2종
    (``_OPERATION_MEMBERSHIPS_SQL`` / ``_OPERATION_DATASET_MEMBERSHIP_SQL``)의 술어에
    직접 들어간다 — 즉 이 한 줄이 카탈로그 drift의 실제 채널이다. 진입 시 전부
    enabled임을 확인하고 나갈 때 그대로 되돌린다(단정 실패로 빠져나가도 복구된다).
    """
    disable = text(
        "UPDATE provider_sync.provider_dataset_operations SET is_enabled = :value "
        "WHERE operation_key = :operation_key AND operation_kind = 'refresh'"
    )
    async with AsyncSession(engine) as setup, setup.begin():
        already_disabled = await setup.scalar(
            text(
                "SELECT count(*) FROM provider_sync.provider_dataset_operations "
                "WHERE operation_key = :operation_key AND operation_kind = 'refresh' "
                "AND NOT is_enabled"
            ),
            {"operation_key": operation_key},
        )
        assert already_disabled == 0, (
            f"시드 전제가 깨졌다: {operation_key!r}에 이미 disabled refresh operation이 있다"
        )
        await setup.execute(disable, {"value": False, "operation_key": operation_key})
    try:
        yield
    finally:
        async with AsyncSession(engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                disable, {"value": True, "operation_key": operation_key}
            )


async def test_catalog_drift_after_freezing_stops_the_sync_state_write(
    migrated_engine: AsyncEngine,
) -> None:
    """guard가 manifest를 frozen한 뒤 카탈로그가 바뀌면 cursor를 쓰지 않는다.

    운영자가 operation을 disable하거나 dataset을 ``is_active=false``로 내리면 canonical
    resolver가 그 member를 더 이상 돌려주지 않는다. 이미 실행 중인 run은 frozen
    manifest를 들고 있으므로, 그 상태로 진행하면 **카탈로그가 더 이상 인정하지 않는
    행에 sync cursor가 적힌다** — 다음 run이 그 cursor를 근거로 적재를 건너뛴다.

    이 회귀는 그 drift를 실제 DB에서 만든다. stub으로 executable 집합만 비워도 같은
    분기를 밟지만, 그러면 "무엇이 그 집합을 비우는가"(=``is_enabled`` 술어)가 검증
    밖으로 빠진다.

    같은 drift의 두 번째 결과도 함께 건다: 그 뒤에 뜨는 새 run은 애초에 guard를 만들지
    못하고 ``operation_has_no_enabled_memberships``로 죽는다. 이 검사가 없으면 새 run이
    **빈 manifest**로 조용히 진행해 아무 member도 추적하지 않은 채 성공으로 닫힌다.
    """
    operation_key = "feature_place_knps_points_job"
    client = AsyncKorTravelMapClient(migrated_engine)
    spec = _schedule_spec(operation_key)
    tags = _feature_load_schedule_tags(spec)
    declared_key = spec.execution_scopes[0].dataset_key

    guard = await _guard_from_context_async(
        _resource_init_context(
            client, run_id=f"run-c3e-knps-drift-{uuid4()}", tags=tags
        )
    )
    context = _tracking_context(guard, retry_number=0)

    async def _resolve() -> ProviderDatasetOperationMembership:
        return await _exact_sync_membership(
            context,
            client,
            boundary="feature_sync_state",
            provider=KNPS_PROVIDER_NAME,
            dataset_key=declared_key,
        )

    # 통제군: drift 전에는 같은 호출이 통과한다.
    assert await _resolve() == guard.memberships[0]

    async with _operation_disabled_in_catalog(
        migrated_engine, operation_key=operation_key
    ):
        with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
            await _resolve()
        assert excinfo.value.reason == "membership_snapshot_changed"

        with pytest.raises(FeatureOperationGuardUnavailable) as init_excinfo:
            await _guard_from_context_async(
                _resource_init_context(
                    client,
                    run_id=f"run-c3e-knps-drift-after-{uuid4()}",
                    tags=tags,
                )
            )
        assert init_excinfo.value.reason == "operation_has_no_enabled_memberships"

    # 카탈로그가 복구되면 같은 호출이 다시 통과한다 — 거부 사유가 drift 그 자체였고,
    # 이 테스트가 시드를 disabled인 채로 남기지 않았음을 함께 못 박는다.
    assert await _resolve() == guard.memberships[0]


async def test_manual_job_launch_inherits_the_manifest_from_definition_tags(
    migrated_engine: AsyncEngine,
) -> None:
    """job 정의 tag만 물려받는 run도 좁혀진 manifest를 갖는다.

    admin UI "지금 실행"은 schedule을 거치지 않고 job을 launch하며 schedule tag를
    받지 않는다(``kor_travel_map.trigger_kind``도 없고
    ``kor_travel_map.admin_manual_trigger=admin-ui``가 붙는다 — API 회귀
    ``test_schedule_command_knps_manual_launch_persists_resolved_config_and_tags``).
    그 run의 실행 manifest 선언은 job 정의 tag에서만 올 수 있다.

    선언이 정의 tag에 없으면 이 run만 manifest가 operation 전체(5건)로 넓어져,
    guard가 실행하지도 않을 member 4개를 running으로 만들고 terminal reconcile이
    operation을 ``tracking_invariant``로 떨어뜨린다. 그래서 여기서는 schedule tag를
    쓰지 않고 **정의 tag만** 실어 그 채널 하나를 직접 건다.
    """
    client = AsyncKorTravelMapClient(migrated_engine)
    spec = _schedule_spec("feature_place_knps_points_job")
    tags = {
        **_feature_load_definition_tags(spec),
        _ADMIN_MANUAL_TRIGGER_TAG: "admin-ui",
    }
    assert _TRIGGER_KIND_TAG not in tags

    async with AsyncSession(migrated_engine) as setup:
        executable = await memberships_for_operation(
            setup, operation_key="feature_place_knps_points_job"
        )
        declared = await membership_for_dataset(
            setup,
            provider=KNPS_PROVIDER_NAME,
            dataset_key=spec.execution_scopes[0].dataset_key,
            operation_key="feature_place_knps_points_job",
            sync_scope="dataset_wide",
        )
    assert len(executable) > 1

    run_id = f"run-c3e-knps-manual-{uuid4()}"
    guard = await _guard_from_context_async(
        _resource_init_context(client, run_id=run_id, tags=tags)
    )

    assert guard.trigger_kind == "manual"
    assert guard.memberships == (declared,), (
        "정의 tag에 실행 manifest 선언이 없어 수동 run이 operation 전체를 잡았다"
    )
    await guard.ensure()

    async with AsyncSession(migrated_engine) as check:
        root_id = str(
            await check.scalar(
                text(
                    "SELECT job_id FROM ops.import_jobs "
                    "WHERE kind = 'provider_feature_load_run' "
                    "AND dagster_run_id = :run_id"
                ),
                {"run_id": run_id},
            )
        )
        members = (
            await check.execute(text(_CHILD_MEMBERS_SQL), {"root_id": root_id})
        ).all()
    assert [int(row.provider_dataset_id) for row in members] == [
        declared.provider_dataset_id
    ]


async def test_declaration_absent_from_the_catalog_is_rejected_at_resource_init(
    migrated_engine: AsyncEngine,
) -> None:
    """선언은 좁히기만 할 수 있다 — 카탈로그에 없는 대상을 만들어낼 수 없다.

    ``knps_trails``는 실재하는 dataset이지만 ``feature_geometry_knps_records_job``에
    결박돼 있다(``0089_tvn33_expand_seed``). point operation 아래에서 그것을 선언하면
    canonical resolver가 행을 하나도 찾지 못한다. 그때 조용히 무시하거나 operation
    전체로 넓히면, run이 실행할 대상과 DB member가 갈린다.
    """
    client = AsyncKorTravelMapClient(migrated_engine)
    tags = {
        _OPERATION_KEY_TAG: "feature_place_knps_points_job",
        _TRIGGER_KIND_TAG: "schedule",
        EXECUTION_SCOPES_TAG: json.dumps(
            [
                {
                    "provider": KNPS_PROVIDER_NAME,
                    "dataset_key": "knps_trails",
                    "sync_scope": "dataset_wide",
                }
            ]
        ),
    }
    run_id = f"run-c3e-knps-foreign-decl-{uuid4()}"

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        await _guard_from_context_async(
            _resource_init_context(client, run_id=run_id, tags=tags)
        )

    assert excinfo.value.reason == "execution_scope_not_in_catalog"
    async with AsyncSession(migrated_engine) as check:
        root_id = await check.scalar(
            text(
                "SELECT job_id FROM ops.import_jobs "
                "WHERE kind = 'provider_feature_load_run' AND dagster_run_id = :run_id"
            ),
            {"run_id": run_id},
        )
    assert root_id is None, "거부해야 할 run이 추적 root를 만들었다"


@pytest.mark.parametrize(
    ("job_name", "dataset_key"),
    [
        (
            "feature_weather_kma_ultra_short_nowcast_job",
            KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
        ),
        (
            "feature_weather_kma_ultra_short_forecast_job",
            KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
        ),
        ("feature_weather_kma_short_forecast_job", KMA_SHORT_FORECAST_DATASET_KEY),
    ],
)
async def test_multi_scope_dataset_run_freezes_only_the_executable_scope(
    job_name: str,
    dataset_key: str,
    migrated_engine: AsyncEngine,
) -> None:
    """scope가 둘인 dataset의 run이 실행 가능한 scope 하나만 frozen한다(KMA 격자).

    ``0089_tvn33_expand_seed``는 refreshable dataset 전부에 ``dataset_wide``를 넣고
    격자 dataset에만 ``target_grids``를 더 넣는다. 그런데 ``dataset_wide``는
    ``_run_kma_weather_asset``과 queue runner ``_kma_grid_sync_scope``가 둘 다
    ``ValueError``로 거부한다 — 실행 경로가 없다. 그래서 run은 ``target_grids``만
    선언하고, ``_exact_kma_sync_membership``의 "manifest 1건" 게이트가 그 선언 위에서
    성립한다.

    격자 3종을 **모두** 태운다. 예전에는 단기예보 job 하나만 태워서, 다른 두 schedule
    선언이 엉뚱한 dataset을 가리켜도(예: 초단기실황 schedule이 초단기예보 dataset을
    선언) 3단 게이트 전부가 통과했다. 그 상태로 실행하면 manifest가 남의 dataset
    member로 frozen되고, ``_exact_kma_sync_membership``이 그 member를 그대로 써서
    **다른 dataset의 sync cursor에 기록**한다 — dataset_key 역산 fallback이 없으므로
    조용히 어긋난다.

    그래서 기대 dataset key는 spec에서 읽지 않고 provider 상수로 못 박는다. spec에서
    읽으면 선언이 바뀌어도 기대값이 같이 따라가 이 회귀가 아무것도 검증하지 않는다.
    """
    client = AsyncKorTravelMapClient(migrated_engine)
    spec = _schedule_spec(job_name)
    tags = _feature_load_schedule_tags(spec)
    assert [scope.dataset_key for scope in spec.execution_scopes] == [dataset_key], (
        "KMA schedule 선언이 자기 dataset을 가리키지 않는다"
    )

    async with AsyncSession(migrated_engine) as setup:
        executable = await memberships_for_operation(setup, operation_key=job_name)
        target_grids = await membership_for_dataset(
            setup,
            provider="python-kma-api",
            dataset_key=dataset_key,
            operation_key=job_name,
            sync_scope="target_grids",
        )
    # 전제: 같은 dataset에 scope가 2개다(그래서 dataset만으로는 지목되지 않는다).
    assert len(executable) == 2
    assert {member.sync_scope for member in executable} == {
        "dataset_wide",
        "target_grids",
    }
    assert len({member.provider_dataset_id for member in executable}) == 1

    run_id = f"run-c3e-kma-manifest-{uuid4()}"
    guard = await _guard_from_context_async(
        _resource_init_context(client, run_id=run_id, tags=tags)
    )
    assert guard.memberships == (target_grids,), (
        "frozen manifest가 이 job의 dataset이 아니다 — 남의 dataset cursor에 기록된다"
    )
    await guard.ensure()

    resolved = await _exact_kma_sync_membership(
        _tracking_context(guard, retry_number=0),
        client,
        expected_sync_scope="target_grids",
    )
    assert resolved == target_grids

    async with AsyncSession(migrated_engine) as check:
        root_id = str(
            await check.scalar(
                text(
                    "SELECT job_id FROM ops.import_jobs "
                    "WHERE kind = 'provider_feature_load_run' "
                    "AND dagster_run_id = :run_id"
                ),
                {"run_id": run_id},
            )
        )
        members = (
            await check.execute(text(_CHILD_MEMBERS_SQL), {"root_id": root_id})
        ).all()
    assert [str(row.sync_scope) for row in members] == ["target_grids"]


async def test_reconcile_sensor_uses_the_same_manifest_as_the_run(
    migrated_engine: AsyncEngine,
) -> None:
    """sensor가 run과 같은 manifest를 쓴다 — 아니면 terminal에서 selection이 갈린다.

    sensor는 run 밖에서 관측하므로 guard가 frozen한 selection을 알 방법이 run tag
    뿐이다. sensor가 operation의 실행 가능 scope 전체를 넘기면
    ``reconcile_dagster_feature_run``이 stored selection과 다르다고 판정해 성공한
    run을 ``failed``/``tracking_invariant``로 뒤집는다.
    """
    client = AsyncKorTravelMapClient(migrated_engine)
    spec = _schedule_spec("feature_place_knps_points_job")
    tags = _feature_load_schedule_tags(spec)
    run_id = f"run-c3e-knps-sensor-{uuid4()}"

    guard = await _guard_from_context_async(
        _resource_init_context(client, run_id=run_id, tags=tags)
    )
    await guard.ensure()
    async def _body(_ctx: Any) -> str:
        return "loaded"

    await run_tracked_feature_asset(_tracking_context(guard, retry_number=0), _body)

    created_at = datetime(2026, 7, 16, 1, tzinfo=UTC)
    record = SimpleNamespace(
        storage_id=1,
        dagster_run=SimpleNamespace(
            run_id=run_id,
            job_name=spec.job_name,
            run_config={},
            asset_selection=None,
            status=DagsterRunStatus.SUCCESS,
            tags=tags,
        ),
        create_timestamp=created_at,
        start_time=(created_at + timedelta(seconds=1)).timestamp(),
        end_time=(created_at + timedelta(seconds=5)).timestamp(),
    )

    outcome = await _apply_run_record(record, client)

    assert outcome == "applied"
    async with AsyncSession(migrated_engine) as check:
        row = (
            await check.execute(
                text(
                    "SELECT status, current_stage FROM ops.import_jobs "
                    "WHERE kind = 'provider_feature_load_run' "
                    "AND dagster_run_id = :run_id"
                ),
                {"run_id": run_id},
            )
        ).one()
    assert (row.status, row.current_stage) == ("done", "completed")
