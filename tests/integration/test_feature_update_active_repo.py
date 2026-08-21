"""C45X canonical active scope와 queued dispatch intent 통합 검증 (#686)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from kortravelmap.api import feature_update_service as service_mod
from kortravelmap.api.feature_update_schema import (
    FeatureUpdateRequestCreateRequest,
    FeatureUpdateRequestCreateResponse,
)
from kortravelmap.api.feature_update_service import (
    FeatureUpdateIdempotencyConflict,
    create_feature_update_request,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.feature_update_active_repo import (
    FeatureUpdateDispatchConflict,
    find_active_provider_dataset_request,
    is_active_provider_dataset_unique_violation,
    request_feature_update_dispatch,
)
from kortravelmap.infra.feature_update_repo import (
    enqueue_feature_update_request,
    peek_next_update_request,
)
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.settings import KorTravelMapSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]

_PROVIDER = "python-kma-api"
_DATASET = "kma_short_forecast"

#: catalog에서 (dataset, sync_scope, operation) triple 하나를 고르는 SQL.
#:
#: T-VN-33 이후 provider_dataset scope의 identity는 자연키 쌍이 아니라
#: ``provider_dataset_id + sync_scope + operation_key``이고, 세 열 모두
#: ``provider_dataset_operation_scopes``를 FK로 참조한다 — 임의의 문자열로는
#: 요청을 만들 수 없다. 0089가 seed한 실제 triple을 읽어 쓴다.
_OPERATION_SCOPE_SQL = """
SELECT scope.provider_dataset_id, scope.operation_key
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
WHERE dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND scope.sync_scope = :sync_scope
  AND dataset.is_active
  AND operation.is_enabled
ORDER BY scope.operation_key
LIMIT 1
"""

#: 활성 request가 아직 점유하지 않은 triple 하나 (feature_ids/bbox scope 요청용).
_FREE_MEMBERSHIP_SQL = """
SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
WHERE dataset.is_active AND operation.is_enabled
  AND NOT EXISTS (
      SELECT 1
      FROM ops.feature_update_request_datasets AS member
      JOIN ops.feature_update_requests AS request
        ON request.request_id = member.request_id
      JOIN ops.import_jobs AS job ON job.job_id = request.job_id
      WHERE member.provider_dataset_id = scope.provider_dataset_id
        AND member.sync_scope = scope.sync_scope
        AND member.operation_key = scope.operation_key
        AND job.status IN ('queued', 'running')
  )
ORDER BY scope.provider_dataset_id, scope.sync_scope, scope.operation_key
LIMIT 1
"""


async def _operation_scope(
    session: AsyncSession,
    *,
    sync_scope: str,
    provider: str = _PROVIDER,
    dataset_key: str = _DATASET,
) -> ImportJobDatasetTarget:
    """catalog에서 canonical membership 1건을 읽는다."""
    row = (
        await session.execute(
            text(_OPERATION_SCOPE_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
            },
        )
    ).one()
    return ImportJobDatasetTarget(
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=sync_scope,
        operation_key=str(row.operation_key),
    )


async def _canonical_membership(session: AsyncSession) -> ImportJobDatasetTarget:
    """활성 request가 점유하지 않은 triple을 골라 membership으로 만든다."""
    row = (await session.execute(text(_FREE_MEMBERSHIP_SQL))).one()
    return ImportJobDatasetTarget(
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=str(row.sync_scope),
        operation_key=str(row.operation_key),
    )


def _scope(member: ImportJobDatasetTarget) -> dict[str, object]:
    """membership과 정확히 일치하는 canonical provider_dataset scope."""
    return {
        "type": "provider_dataset",
        "provider_dataset_id": member.provider_dataset_id,
        "sync_scope": member.sync_scope,
        "operation_key": member.operation_key,
    }


async def _create_isolated_migrated_engine(
    pg_container: Any,
) -> tuple[str, AsyncEngine]:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"active_scope_race_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        await admin_engine.dispose()

    # T-VN-34 이후 fresh DB는 **먼저 배포와 같은 principal graph**를 갖춰야 upgrade가
    # 선다. 0097은 state routine을 만들기 전에 ``SET ROLE
    # ktm_feature_state_procedure_owner``로 내려간다(권한을 owner 자격에서만 쓰게
    # 하는 ADR-090 경로). 그 role에 schema ``feature``의 CREATE를 주는 것은
    # migration이 아니라 bootstrap이므로, bootstrap 없이 올리면 superuser DSN이어도
    # ``permission denied for schema feature``로 죽는다 — SET ROLE 이후의 권한 판정은
    # superuser 우회를 받지 못한다.
    #
    # 여기서만 다른 경로로 올리면 경합을 재는 대상 schema가 배포와 달라지므로,
    # conftest·다른 자기-DB 테스트가 쓰는 공유 helper를 그대로 쓴다.
    from tests.integration._tvn34_migration_bootstrap import (
        upgrade_head_with_tvn_m01_phase,
    )

    await upgrade_head_with_tvn_m01_phase(
        Config(str(_ROOT / "alembic.ini")), target_dsn
    )
    # 테스트 본문은 계속 컨테이너 admin 자격으로 붙는다 — 검증 대상은 ACL이 아니라
    # active-scope 경합이고, migration이 남긴 소유권과 무관하게 읽고 써야 한다.
    return target_dsn, make_async_engine(target_dsn)


async def _isolated_membership(dsn: str, *, sync_scope: str) -> ImportJobDatasetTarget:
    """격리 DB catalog에서 membership 1건을 읽고 연결을 즉시 정리한다.

    테스트 본문이 쓰는 engine을 건드리지 않도록 전용 engine을 쓰고 바로 dispose한다
    (남은 연결이 있으면 teardown의 ``DROP DATABASE``가 실패한다).
    """
    engine = make_async_engine(dsn)
    try:
        async with AsyncSession(engine) as session:
            return await _operation_scope(session, sync_scope=sync_scope)
    finally:
        await engine.dispose()


async def _drop_isolated_database(pg_container: Any, dsn: str) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = make_url(dsn).database
    admin_engine = make_async_engine(admin_dsn)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
    finally:
        await admin_engine.dispose()


async def test_active_identity_uses_job_effective_scope_and_constraint_metadata(
    migrated_session: AsyncSession,
) -> None:
    targeted = await _operation_scope(migrated_session, sync_scope="target_grids")
    first = await enqueue_feature_update_request(
        migrated_session,
        scope=_scope(targeted),
        dataset_memberships=[targeted],
    )
    # T-VN-33: 실행 scope는 별도 열이 아니라 immutable membership이 든다.
    assert first.scope["sync_scope"] == "target_grids"
    assert [member.sync_scope for member in first.dataset_memberships] == [
        "target_grids"
    ]

    found = await find_active_provider_dataset_request(
        migrated_session,
        provider_dataset_id=targeted.provider_dataset_id,
        sync_scope="target_grids",
        operation_key=targeted.operation_key,
    )
    assert found is not None
    assert found.request_id == first.request_id

    with pytest.raises(IntegrityError) as exc_info:
        async with migrated_session.begin_nested():
            await enqueue_feature_update_request(
                migrated_session,
                scope=_scope(targeted),
                dataset_memberships=[targeted],
            )
    assert is_active_provider_dataset_unique_violation(exc_info.value)

    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.pipeline_cancellations (
              cancellation_id, root_kind, root_id, status, requested_by
            ) VALUES (
              '68000000-0000-4000-8000-000000000001',
              'import_job', CAST(:job_id AS uuid), 'in_progress', 'test'
            )
            """
        ),
        {"job_id": first.job_id},
    )
    await migrated_session.execute(
        text(
            """
            UPDATE ops.import_jobs
               SET cancellation_id = '68000000-0000-4000-8000-000000000001',
                   cancellation_requested_at = now(),
                   cancellation_requested_by = 'test'
             WHERE job_id = CAST(:job_id AS uuid)
            """
        ),
        {"job_id": first.job_id},
    )
    cancellation_marked = await find_active_provider_dataset_request(
        migrated_session,
        provider_dataset_id=targeted.provider_dataset_id,
        sync_scope="target_grids",
        operation_key=targeted.operation_key,
    )
    assert cancellation_marked is not None
    assert cancellation_marked.cancellation_id == "68000000-0000-4000-8000-000000000001"

    dataset_wide = await _operation_scope(migrated_session, sync_scope="dataset_wide")
    other = await enqueue_feature_update_request(
        migrated_session,
        scope=_scope(dataset_wide),
        dataset_memberships=[dataset_wide],
    )
    assert other.request_id != first.request_id
    assert [member.sync_scope for member in other.dataset_memberships] == [
        "dataset_wide"
    ]


async def test_concurrent_service_create_reuses_one_canonical_active_request(
    pg_container: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn, isolated_engine = await _create_isolated_migrated_engine(pg_container)
    try:
        targeted = await _isolated_membership(dsn, sync_scope="target_grids")
        body = FeatureUpdateRequestCreateRequest.model_validate(
            {
                "scope": _scope(targeted),
                "run_mode": "queued",
                "reason": "c45x-concurrent-create",
            }
        )
        settings = KorTravelMapSettings(
            _env_file=None,
            kor_travel_geo_base_url=None,
        )
        original_find_active = service_mod.find_active_provider_dataset_request
        initial_lookup_count = 0
        initial_lookup_barrier = asyncio.Condition()

        async def _find_active_after_barrier(*args: Any, **kwargs: Any) -> Any:
            nonlocal initial_lookup_count
            result = await original_find_active(*args, **kwargs)
            if result is not None:
                return result
            async with initial_lookup_barrier:
                initial_lookup_count += 1
                if initial_lookup_count == 2:
                    initial_lookup_barrier.notify_all()
                else:
                    await initial_lookup_barrier.wait_for(lambda: initial_lookup_count >= 2)
            return None

        monkeypatch.setattr(
            service_mod,
            "find_active_provider_dataset_request",
            _find_active_after_barrier,
        )

        async def _create(idempotency_key: UUID) -> FeatureUpdateRequestCreateResponse:
            async def _allow_plan(_pairs: frozenset[tuple[str, str]]) -> None:
                return None

            async with AsyncSession(isolated_engine, expire_on_commit=False) as session:
                return await create_feature_update_request(
                    body,
                    session,
                    idempotency_key=idempotency_key,
                    operator="integration-c45x-race",
                    status_url_prefix=service_mod.DEFAULT_STATUS_URL_PREFIX,
                    settings=settings,
                    resolved_plan_guard=_allow_plan,
                )

        first_key = uuid4()
        second_key = uuid4()
        first, second = await asyncio.wait_for(
            asyncio.gather(_create(first_key), _create(second_key)),
            timeout=15,
        )
        assert first.data.request_id == second.data.request_id
        assert first.data.job_id == second.data.job_id
        assert initial_lookup_count == 2
        assert sorted((first.reused_active_request, second.reused_active_request)) == [
            False,
            True,
        ]
        first_replay, second_replay = await asyncio.gather(
            _create(first_key),
            _create(second_key),
        )
        assert first_replay.idempotent_replay is True
        assert second_replay.idempotent_replay is True
        assert first_replay.reused_active_request is first.reused_active_request
        assert second_replay.reused_active_request is second.reused_active_request
        async with isolated_engine.connect() as connection:
            mapping_counts = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*) AS ledger_rows,
                               count(DISTINCT request_id) AS mapped_requests
                        FROM ops.feature_update_request_idempotency
                        WHERE actor = 'integration-c45x-race'
                          AND idempotency_key IN (
                            CAST(:first_key AS uuid), CAST(:second_key AS uuid)
                          )
                        """
                    ),
                    {"first_key": str(first_key), "second_key": str(second_key)},
                )
            ).one()
        assert (mapping_counts.ledger_rows, mapping_counts.mapped_requests) == (2, 1)
        reused_key = first_key if first.reused_active_request else second_key
        async with isolated_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.import_jobs AS job
                    SET status = 'done', finished_at = now()
                    FROM ops.feature_update_requests AS request
                    WHERE request.request_id = CAST(:request_id AS uuid)
                      AND job.job_id = request.job_id
                    """
                ),
                {"request_id": str(first.data.request_id)},
            )
        terminal_replay = await _create(reused_key)
        assert terminal_replay.idempotent_replay is True
        assert terminal_replay.reused_active_request is True
        assert terminal_replay.data.status == "done"

        async with isolated_engine.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          count(*) AS total_jobs,
                          count(*) FILTER (WHERE job.status IN ('queued', 'running'))
                            AS active_jobs,
                          count(*) FILTER (
                            WHERE NOT EXISTS (
                              SELECT 1
                              FROM ops.feature_update_requests AS request
                              WHERE request.job_id = job.job_id
                            )
                          ) AS unlinked_jobs
                        FROM ops.import_jobs AS job
                        JOIN ops.import_job_datasets AS member
                          ON member.job_id = job.job_id
                        WHERE job.kind = 'feature_update_request'
                          AND member.provider_dataset_id = :provider_dataset_id
                          AND member.sync_scope = 'target_grids'
                          AND member.operation_key = :operation_key
                        """
                    ),
                    {
                        "provider_dataset_id": targeted.provider_dataset_id,
                        "operation_key": targeted.operation_key,
                    },
                )
            ).one()
        assert counts.total_jobs == 1
        assert counts.active_jobs == 0
        assert counts.unlinked_jobs == 0
    finally:
        await isolated_engine.dispose()
        await _drop_isolated_database(pg_container, dsn)


async def test_service_idempotency_serializes_replay_and_rejects_mismatch(
    pg_container: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn, isolated_engine = await _create_isolated_migrated_engine(pg_container)
    try:
        targeted = await _isolated_membership(dsn, sync_scope="target_grids")
        body = FeatureUpdateRequestCreateRequest.model_validate(
            {
                "scope": _scope(targeted),
                "run_mode": "queued",
                "reason": "durable-idempotency",
            }
        )
        settings = KorTravelMapSettings(
            _env_file=None,
            kor_travel_geo_base_url=None,
        )
        idempotency_key = uuid4()
        first_guard_entered = asyncio.Event()
        release_first_guard = asyncio.Event()

        async def _create(
            request_body: FeatureUpdateRequestCreateRequest,
            *,
            actor: str = "integration-idempotency",
            hold_resolved_plan_guard: bool = False,
            backend_pid_future: asyncio.Future[int] | None = None,
        ) -> FeatureUpdateRequestCreateResponse:
            async def _allow_plan(_pairs: frozenset[tuple[str, str]]) -> None:
                if hold_resolved_plan_guard:
                    first_guard_entered.set()
                    await release_first_guard.wait()
                return

            async with isolated_engine.connect() as connection:
                backend_pid = int(
                    (
                        await connection.execute(text("SELECT pg_backend_pid()"))
                    ).scalar_one()
                )
                await connection.rollback()
                if backend_pid_future is not None:
                    backend_pid_future.set_result(backend_pid)
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                ) as session:
                    return await create_feature_update_request(
                        request_body,
                        session,
                        idempotency_key=idempotency_key,
                        operator=actor,
                        status_url_prefix=service_mod.DEFAULT_STATUS_URL_PREFIX,
                        settings=settings,
                        resolved_plan_guard=_allow_plan,
                    )

        loop = asyncio.get_running_loop()
        first_pid_future: asyncio.Future[int] = loop.create_future()
        second_pid_future: asyncio.Future[int] = loop.create_future()
        first_task: asyncio.Task[FeatureUpdateRequestCreateResponse] | None = None
        second_task: asyncio.Task[FeatureUpdateRequestCreateResponse] | None = None
        try:
            first_task = asyncio.create_task(
                _create(
                    body,
                    hold_resolved_plan_guard=True,
                    backend_pid_future=first_pid_future,
                )
            )
            await asyncio.wait_for(first_guard_entered.wait(), timeout=10)
            first_pid = await asyncio.wait_for(first_pid_future, timeout=10)
            second_task = asyncio.create_task(
                _create(body, backend_pid_future=second_pid_future)
            )
            second_pid = await asyncio.wait_for(second_pid_future, timeout=10)

            lock_id = advisory_lock_key(
                f"feature-update-idempotency:integration-idempotency:{idempotency_key}"
            )
            unsigned_lock_id = lock_id % (2**64)
            lock_classid = unsigned_lock_id >> 32
            lock_objid = unsigned_lock_id & 0xFFFFFFFF
            second_waiting_on_advisory_lock = False
            first_holds_advisory_lock = False
            async with isolated_engine.connect() as observer:
                for _ in range(200):
                    lock_state = (
                        await observer.execute(
                            text(
                                """
                                SELECT
                                  EXISTS (
                                    SELECT 1 FROM pg_locks
                                    WHERE pid = :first_pid
                                      AND locktype = 'advisory'
                                      AND classid::bigint = :lock_classid
                                      AND objid::bigint = :lock_objid
                                      AND objsubid = 1
                                      AND granted
                                  ) AS first_holds,
                                  EXISTS (
                                    SELECT 1 FROM pg_locks
                                    WHERE pid = :second_pid
                                      AND locktype = 'advisory'
                                      AND classid::bigint = :lock_classid
                                      AND objid::bigint = :lock_objid
                                      AND objsubid = 1
                                      AND NOT granted
                                  ) AS second_waits
                                """
                            ),
                            {
                                "first_pid": first_pid,
                                "second_pid": second_pid,
                                "lock_classid": lock_classid,
                                "lock_objid": lock_objid,
                            },
                        )
                    ).one()
                    first_holds_advisory_lock = bool(lock_state.first_holds)
                    second_waiting_on_advisory_lock = bool(lock_state.second_waits)
                    if first_holds_advisory_lock and second_waiting_on_advisory_lock:
                        break
                    await asyncio.sleep(0.01)
            assert not second_task.done()
            release_first_guard.set()
            first, replay = await asyncio.wait_for(
                asyncio.gather(first_task, second_task),
                timeout=15,
            )
            assert first_holds_advisory_lock is True
            assert second_waiting_on_advisory_lock is True
            assert first.data.request_id == replay.data.request_id
            assert first.idempotent_replay is False
            assert replay.idempotent_replay is True
        finally:
            release_first_guard.set()
            tasks = [task for task in (first_task, second_task) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        async with isolated_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.import_jobs AS job
                    SET status = 'done', finished_at = now()
                    FROM ops.feature_update_requests AS request
                    WHERE request.request_id = CAST(:request_id AS uuid)
                      AND job.job_id = request.job_id
                    """
                ),
                {"request_id": str(first.data.request_id)},
            )
        terminal_replay, other_actor = await asyncio.gather(
            _create(body),
            _create(body, actor="integration-other-actor"),
        )
        assert terminal_replay.idempotent_replay is True
        assert terminal_replay.data.status == "done"
        assert other_actor.idempotent_replay is False
        assert other_actor.data.request_id != first.data.request_id

        mismatch = body.model_copy(update={"reason": "different-body"})
        with pytest.raises(FeatureUpdateIdempotencyConflict):
            await _create(mismatch)

        rollback_key = uuid4()

        async def _reject_plan(_pairs: frozenset[tuple[str, str]]) -> None:
            raise RuntimeError("precheck rejected before mapping")

        async with AsyncSession(isolated_engine, expire_on_commit=False) as session:
            with pytest.raises(RuntimeError, match="precheck rejected"):
                await create_feature_update_request(
                    body,
                    session,
                    idempotency_key=rollback_key,
                    operator="integration-other-actor",
                    status_url_prefix=service_mod.DEFAULT_STATUS_URL_PREFIX,
                    settings=settings,
                    resolved_plan_guard=_reject_plan,
                )
        async with isolated_engine.connect() as connection:
            rolled_back_count = await connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM ops.feature_update_request_idempotency
                    WHERE actor = 'integration-other-actor'
                      AND idempotency_key = CAST(:idempotency_key AS uuid)
                    """
                ),
                {"idempotency_key": str(rollback_key)},
            )
        assert rolled_back_count == 0

        async def _allow_plan(_pairs: frozenset[tuple[str, str]]) -> None:
            return None

        async with AsyncSession(isolated_engine, expire_on_commit=False) as session:
            rollback_retry = await create_feature_update_request(
                body,
                session,
                idempotency_key=rollback_key,
                operator="integration-other-actor",
                status_url_prefix=service_mod.DEFAULT_STATUS_URL_PREFIX,
                settings=settings,
                resolved_plan_guard=_allow_plan,
            )
        assert rollback_retry.reused_active_request is True
        assert rollback_retry.idempotent_replay is False

        async with isolated_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE ops.import_jobs AS job
                    SET status = 'done', finished_at = now()
                    FROM ops.feature_update_requests AS request
                    WHERE request.request_id = CAST(:request_id AS uuid)
                      AND job.job_id = request.job_id
                    """
                ),
                {"request_id": str(other_actor.data.request_id)},
            )

        async def _row_counts() -> tuple[int, int, int]:
            async with isolated_engine.connect() as connection:
                row = (
                    await connection.execute(
                        text(
                            """
                            SELECT
                              (SELECT count(*) FROM ops.feature_update_requests)
                                AS request_count,
                              (SELECT count(*) FROM ops.import_jobs
                               WHERE kind = 'feature_update_request') AS job_count,
                              (SELECT count(*)
                               FROM ops.feature_update_request_idempotency)
                                AS ledger_count
                            """
                        )
                    )
                ).one()
            return (row.request_count, row.job_count, row.ledger_count)

        before_atomic_failure = await _row_counts()
        atomic_key = uuid4()
        original_create_mapping = service_mod.create_feature_update_request_idempotency

        async def _fail_after_enqueue(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("mapping insert failed after enqueue")

        monkeypatch.setattr(
            service_mod,
            "create_feature_update_request_idempotency",
            _fail_after_enqueue,
        )
        async with AsyncSession(isolated_engine, expire_on_commit=False) as session:
            with pytest.raises(RuntimeError, match="mapping insert failed"):
                await create_feature_update_request(
                    body,
                    session,
                    idempotency_key=atomic_key,
                    operator="integration-atomic-rollback",
                    status_url_prefix=service_mod.DEFAULT_STATUS_URL_PREFIX,
                    settings=settings,
                    resolved_plan_guard=_allow_plan,
                )
        assert await _row_counts() == before_atomic_failure

        monkeypatch.setattr(
            service_mod,
            "create_feature_update_request_idempotency",
            original_create_mapping,
        )
        async with AsyncSession(isolated_engine, expire_on_commit=False) as session:
            atomic_retry = await create_feature_update_request(
                body,
                session,
                idempotency_key=atomic_key,
                operator="integration-atomic-rollback",
                status_url_prefix=service_mod.DEFAULT_STATUS_URL_PREFIX,
                settings=settings,
                resolved_plan_guard=_allow_plan,
            )
        assert atomic_retry.idempotent_replay is False
        assert atomic_retry.reused_active_request is False
        after_atomic_retry = await _row_counts()
        assert after_atomic_retry == tuple(value + 1 for value in before_atomic_failure)

        async with isolated_engine.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          count(*) AS ledger_rows,
                          count(DISTINCT request_id) AS mapped_requests
                        FROM ops.feature_update_request_idempotency
                        WHERE idempotency_key = CAST(:idempotency_key AS uuid)
                        """
                    ),
                    {"idempotency_key": str(idempotency_key)},
                )
            ).one()
        assert (counts.ledger_rows, counts.mapped_requests) == (2, 2)
    finally:
        await isolated_engine.dispose()
        await _drop_isolated_database(pg_container, dsn)


async def test_direct_writer_requires_canonical_effective_scope(
    migrated_session: AsyncSession,
) -> None:
    """direct writer는 exact canonical membership 없이는 요청을 만들 수 없다.

    T-VN-33에서 ``effective_sync_scope`` 인자는 사라졌다 — 실행 scope는 요청
    시점에 고정하는 immutable membership(``provider_dataset_id + sync_scope +
    operation_key``)이 든다. 종전 인자가 지키던 계약(정규 scope만 · 요청 scope와
    실행 scope 불일치 금지 · 자유 alias 금지)은 그대로 membership 축에서 검증한다.
    """
    targeted = await _operation_scope(migrated_session, sync_scope="target_grids")
    dataset_wide = await _operation_scope(migrated_session, sync_scope="dataset_wide")

    # membership 없는 provider_dataset scope — 실행 대상이 확정되지 않는다.
    with pytest.raises(ValueError, match="exactly one canonical membership"):
        await enqueue_feature_update_request(
            migrated_session, scope=_scope(targeted)
        )

    # 요청 scope와 membership이 다른 scope를 가리키면 거부한다.
    with pytest.raises(ValueError, match="must match its canonical membership"):
        await enqueue_feature_update_request(
            migrated_session,
            scope=_scope(targeted),
            dataset_memberships=[dataset_wide],
        )

    # 자유 alias/blank는 membership 생성 단계에서 막힌다.
    for invalid_scope in (
        "legacy-alias",
        "external_system:",
        "external_system:system ",
        "external_system:\tsystem",
        f"external_system:{'x' * 113}",
    ):
        with pytest.raises(ValueError, match="sync_scope"):
            ImportJobDatasetTarget(
                provider_dataset_id=targeted.provider_dataset_id,
                sync_scope=invalid_scope,
                operation_key=targeted.operation_key,
            )

    # 정규형이어도 catalog에 없는 triple은 실행 대상이 아니다.
    with pytest.raises(ValueError, match="active dataset"):
        await enqueue_feature_update_request(
            migrated_session,
            scope={"type": "feature_ids", "feature_ids": []},
            dataset_memberships=[
                ImportJobDatasetTarget(
                    provider_dataset_id=targeted.provider_dataset_id,
                    sync_scope=f"external_system:{'x' * 112}",
                    operation_key=targeted.operation_key,
                )
            ],
        )

    accepted = await enqueue_feature_update_request(
        migrated_session,
        scope=_scope(targeted),
        dataset_memberships=[targeted],
    )
    assert [member.sync_scope for member in accepted.dataset_memberships] == [
        "target_grids"
    ]

    with pytest.raises(ValueError, match="unsupported sync_scope"):
        await find_active_provider_dataset_request(
            migrated_session,
            provider_dataset_id=targeted.provider_dataset_id,
            sync_scope="legacy-alias",
            operation_key=targeted.operation_key,
        )

    # membership이 아예 없는 요청도 거부한다 (scope 종류와 무관).
    with pytest.raises(ValueError, match="at least one dataset membership"):
        await enqueue_feature_update_request(
            migrated_session,
            scope={"type": "feature_ids", "feature_ids": []},
            dataset_memberships=[],
        )


async def test_dispatch_promotion_is_idempotent_and_prioritized(
    migrated_session: AsyncSession,
) -> None:
    ordinary = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        dataset_memberships=[await _canonical_membership(migrated_session)],
        priority=100,
    )
    promoted_source = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "bbox", "min_lon": 126, "min_lat": 37, "max_lon": 127, "max_lat": 38},
        dataset_memberships=[await _canonical_membership(migrated_session)],
        priority=1,
    )

    promoted = await request_feature_update_dispatch(migrated_session, promoted_source.request_id)
    promoted_again = await request_feature_update_dispatch(
        migrated_session, promoted_source.request_id
    )

    assert promoted.request_id == promoted_source.request_id
    assert promoted.dispatch_requested_at is not None
    assert promoted_again.dispatch_requested_at == promoted.dispatch_requested_at
    assert ordinary.dispatch_requested_at is None
    assert (await peek_next_update_request(migrated_session)).request_id == promoted.request_id


async def test_run_mode_now_sets_dispatch_intent_at_insert(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        dataset_memberships=[await _canonical_membership(migrated_session)],
        run_mode="now",
    )
    assert request.dispatch_requested_at is not None


async def test_dispatch_conflict_exposes_current_lifecycle(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        dataset_memberships=[await _canonical_membership(migrated_session)],
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET status = 'failed', finished_at = now() "
            "WHERE job_id = CAST(:job_id AS uuid)"
        ),
        {"job_id": request.job_id},
    )

    with pytest.raises(FeatureUpdateDispatchConflict) as exc_info:
        await request_feature_update_dispatch(migrated_session, request.request_id)
    assert exc_info.value.request_id == request.request_id
    assert exc_info.value.current_status == "failed"

    with pytest.raises(FeatureUpdateDispatchConflict) as missing_info:
        await request_feature_update_dispatch(
            migrated_session, "00000000-0000-4000-8000-000000000000"
        )
    assert missing_info.value.current_status == "not_found"


async def test_active_lookup_does_not_match_sibling_operation_on_same_scope(
    migrated_session: AsyncSession,
) -> None:
    """active 조회는 membership triple로 판정한다 — 형제 operation을 잡으면 안 된다.

    ``ops.feature_update_request_datasets``의 세 열이 모두 NOT NULL이고 DB trigger도
    triple로 경합을 본다. 조회만 pair로 좁히면 operation A의 active request가
    operation B의 요청에 걸려, 상위 ``_assert_reusable_active_request``의 triple
    비교가 불일치를 내며 **정당한 요청에 409**를 준다 — Python 가드가 자기가 흉내
    내는 DB 가드보다 엄격해지는 상태다.
    """
    targeted = await _operation_scope(migrated_session, sync_scope="target_grids")
    sibling_operation_key = f"{targeted.operation_key}.sibling"
    await migrated_session.execute(
        text(
            "INSERT INTO provider_sync.provider_dataset_operations "
            "(provider_dataset_id, operation_key, operation_kind) "
            "VALUES (:provider_dataset_id, :operation_key, 'refresh')"
        ),
        {
            "provider_dataset_id": targeted.provider_dataset_id,
            "operation_key": sibling_operation_key,
        },
    )
    await migrated_session.execute(
        text(
            "INSERT INTO provider_sync.provider_dataset_operation_scopes "
            "(provider_dataset_id, sync_scope, operation_key, operation_kind) "
            "VALUES (:provider_dataset_id, 'target_grids', :operation_key, 'refresh')"
        ),
        {
            "provider_dataset_id": targeted.provider_dataset_id,
            "operation_key": sibling_operation_key,
        },
    )
    sibling = ImportJobDatasetTarget(
        provider_dataset_id=targeted.provider_dataset_id,
        sync_scope="target_grids",
        operation_key=sibling_operation_key,
    )

    active = await enqueue_feature_update_request(
        migrated_session,
        scope=_scope(targeted),
        dataset_memberships=[targeted],
    )

    same = await find_active_provider_dataset_request(
        migrated_session,
        provider_dataset_id=targeted.provider_dataset_id,
        sync_scope="target_grids",
        operation_key=targeted.operation_key,
    )
    assert same is not None
    assert same.request_id == active.request_id

    other = await find_active_provider_dataset_request(
        migrated_session,
        provider_dataset_id=sibling.provider_dataset_id,
        sync_scope="target_grids",
        operation_key=sibling.operation_key,
    )
    assert other is None, (
        "형제 operation의 active request를 자기 것으로 잡으면 거짓 409가 난다"
    )
