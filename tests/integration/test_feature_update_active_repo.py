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

from alembic import command
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
from kortravelmap.settings import KorTravelMapSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_PROVIDER = "python-kma-api"
_DATASET = "kma_short_forecast"


def _scope(sync_scope: str | None = None) -> dict[str, object]:
    scope: dict[str, object] = {
        "type": "provider_dataset",
        "provider": _PROVIDER,
        "dataset_key": _DATASET,
    }
    if sync_scope is not None:
        scope["sync_scope"] = sync_scope
    return scope


def _upgrade_head(dsn: str) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(config, "head")


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
    await asyncio.to_thread(_upgrade_head, target_dsn)
    return target_dsn, make_async_engine(target_dsn)


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
    first = await enqueue_feature_update_request(
        migrated_session,
        scope=_scope(),
        effective_sync_scope="target_grids",
    )
    assert first.scope.get("sync_scope") is None
    assert first.effective_sync_scope == "target_grids"

    found = await find_active_provider_dataset_request(
        migrated_session,
        provider=_PROVIDER,
        dataset_key=_DATASET,
        sync_scope="target_grids",
    )
    assert found is not None
    assert found.request_id == first.request_id

    with pytest.raises(IntegrityError) as exc_info:
        async with migrated_session.begin_nested():
            await enqueue_feature_update_request(
                migrated_session,
                scope=_scope(),
                effective_sync_scope="target_grids",
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
        provider=_PROVIDER,
        dataset_key=_DATASET,
        sync_scope="target_grids",
    )
    assert cancellation_marked is not None
    assert cancellation_marked.cancellation_id == "68000000-0000-4000-8000-000000000001"

    other = await enqueue_feature_update_request(
        migrated_session,
        scope=_scope(),
        effective_sync_scope="dataset_wide",
    )
    assert other.request_id != first.request_id
    assert other.effective_sync_scope == "dataset_wide"


async def test_concurrent_service_create_reuses_one_canonical_active_request(
    pg_container: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn, isolated_engine = await _create_isolated_migrated_engine(pg_container)
    try:
        body = FeatureUpdateRequestCreateRequest.model_validate(
            {
                "scope": {
                    "type": "provider_dataset",
                    "provider": _PROVIDER,
                    "dataset_key": _DATASET,
                },
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
                        WHERE job.kind = 'feature_update_request'
                          AND job.provider = :provider
                          AND job.dataset_key = :dataset_key
                          AND job.sync_scope = 'target_grids'
                        """
                    ),
                    {"provider": _PROVIDER, "dataset_key": _DATASET},
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
        body = FeatureUpdateRequestCreateRequest.model_validate(
            {
                "scope": {
                    "type": "provider_dataset",
                    "provider": _PROVIDER,
                    "dataset_key": _DATASET,
                },
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
    with pytest.raises(ValueError, match="explicit effective_sync_scope"):
        await enqueue_feature_update_request(migrated_session, scope=_scope())

    with pytest.raises(ValueError, match="explicit requested sync_scope"):
        await enqueue_feature_update_request(
            migrated_session,
            scope=_scope("target_grids"),
            effective_sync_scope="dataset_wide",
        )

    for invalid_scope in (
        "legacy-alias",
        "external_system:",
        "external_system:system ",
        "external_system:\tsystem",
        f"external_system:{'x' * 113}",
    ):
        with pytest.raises(ValueError, match="effective_sync_scope"):
            await enqueue_feature_update_request(
                migrated_session,
                scope=_scope(),
                effective_sync_scope=invalid_scope,
            )

    max_length_scope = f"external_system:{'x' * 112}"
    accepted = await enqueue_feature_update_request(
        migrated_session,
        scope=_scope(),
        effective_sync_scope=max_length_scope,
    )
    assert accepted.effective_sync_scope == max_length_scope

    with pytest.raises(ValueError, match="unsupported sync_scope"):
        await find_active_provider_dataset_request(
            migrated_session,
            provider=_PROVIDER,
            dataset_key=_DATASET,
            sync_scope="legacy-alias",
        )

    with pytest.raises(ValueError, match="only valid for provider_dataset"):
        await enqueue_feature_update_request(
            migrated_session,
            scope={"type": "feature_ids", "feature_ids": []},
            effective_sync_scope="dataset_wide",
        )


async def test_dispatch_promotion_is_idempotent_and_prioritized(
    migrated_session: AsyncSession,
) -> None:
    ordinary = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        priority=100,
    )
    promoted_source = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "bbox", "min_lon": 126, "min_lat": 37, "max_lon": 127, "max_lat": 38},
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
        run_mode="now",
    )
    assert request.dispatch_requested_at is not None


async def test_dispatch_conflict_exposes_current_lifecycle(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
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
