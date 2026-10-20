"""ADR-112 결정 2·4 — 서버 쪽 상한과 abandon의 다섯 분기를 실제 DB에서 본다.

- 서버 쪽 상한: reconcile sensor가 여는 트랜잭션마다 ``set_config('statement_timeout'/
  'lock_timeout', ..., true)``가 걸려 **Postgres가 statement를 취소**한다. client 쪽
  ``asyncio.timeout``만 남으면 서버의 statement는 계속 돈다 — 그 차이를 효과로 본다.
- SERIALIZABLE SUCCESS reconcile에서도 상한을 isolation 문 **다음**에 건다(먼저면 25001).
- ``abandon_dagster_feature_run``은 DB 상태(root 없음·취소 marker·terminal·Dagster active·
  Dagster terminal/없음)에 따라 다르게 움직인다.

gate 표지(결정 5)의 실제 procedure 검사는 같은 isolated DB를 쓰는
``test_feature_write_gate_lock_budget.py``에 있다.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from kortravelmap.dagster.feature_operation_sensors import (
    FEATURE_OPERATION_TICK_BUDGET_SECONDS,
    _classify_failure,
    _Tick,
)
from kortravelmap.dagster.retry_common import pg_error_info
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.pipeline_cancellation_repo import (
    _PIPELINE_LINEAGE_MUTATION_LOCK_KEY,
    create_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
)
from tests.integration._membership_seed import SINGLE_MEMBER_OPERATION
from tests.integration.test_canonical_provider_operations import (
    _TREE_WITH_MEMBERS_SQL,
    _delete_committed_feature_tree,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_REMAINING_SECONDS = 8.0
"""검사용 page 마감까지 남은 시간. statement_timeout=5초, lock_timeout=4초가 된다."""


@pytest.fixture(autouse=True)
def _clients_use_dagster_login(
    monkeypatch: pytest.MonkeyPatch, dagster_runtime_engine: AsyncEngine
) -> None:
    """이 모듈의 client는 실제 Dagster LOGIN(provider executor)으로 만든다."""
    original_init = AsyncKorTravelMapClient.__init__

    def _init(self: AsyncKorTravelMapClient, _ignored_engine: AsyncEngine) -> None:
        original_init(self, dagster_runtime_engine)

    monkeypatch.setattr(AsyncKorTravelMapClient, "__init__", _init)


class _Log:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str, *args: object) -> None:
        self.errors.append(message % args if args else message)

    def info(self, message: str, *args: object) -> None:
        pass


def _tick_with_remaining(seconds: float) -> _Tick:
    """DB page 마감까지 ``seconds``가 남은 tick(sensor가 쓰는 것과 같은 호출 경로)."""
    context = SimpleNamespace(log=_Log())
    started = time.monotonic() - (FEATURE_OPERATION_TICK_BUDGET_SECONDS - seconds)
    return _Tick(context=context, started=started)  # type: ignore[arg-type]


async def _started_root(
    client: AsyncKorTravelMapClient, *, run_id: str, created_at: datetime
) -> tuple[str, Any]:
    memberships = await client.resolve_feature_operation_memberships(
        operation_key=SINGLE_MEMBER_OPERATION
    )
    started = await client.ensure_dagster_feature_operation(
        dagster_run_id=run_id,
        trigger_kind="schedule",
        selected_memberships=memberships,
        operation_key=SINGLE_MEMBER_OPERATION,
        engine_created_at=created_at,
        engine_started_at=created_at + timedelta(seconds=1),
        observed_status="STARTED",
    )
    return started.operation.root_job_id, memberships


async def _tree(engine: AsyncEngine, root_id: str) -> list[Any]:
    async with AsyncSession(engine) as probe:
        return list(
            (await probe.execute(text(_TREE_WITH_MEMBERS_SQL), {"root_id": root_id})).all()
        )


async def _abandoned_logs(engine: AsyncEngine, run_id: str) -> list[Any]:
    async with AsyncSession(engine) as probe:
        rows = list(
            (
                await probe.execute(
                    text(
                        "SELECT level, source, event, message, detail FROM ops.system_logs "
                        "WHERE event = 'feature_operation.reconcile_abandoned' "
                        "AND detail ->> 'dagster_run_id' = :run_id"
                    ),
                    {"run_id": run_id},
                )
            ).all()
        )
    return [
        SimpleNamespace(
            level=row.level,
            source=row.source,
            event=row.event,
            message=row.message,
            detail=json.loads(row.detail) if isinstance(row.detail, str) else row.detail,
        )
        for row in rows
    ]


# --- 결정 2: 서버 쪽 상한 -----------------------------------------------------------------


async def test_the_server_cancels_a_slow_statement_within_the_page_budget(
    migrated_engine: AsyncEngine,
) -> None:
    """statement가 오래 돌면 Postgres가 page 마감 안에서 취소한다(57014).

    변이: ``set_config('statement_timeout', …, true)``를 빼면 client 쪽 timeout(남은 시간+3초)만
    남아 오류가 57014가 아니게 되고, 서버의 statement는 계속 돈다 — 이 검사가 빨개진다.
    """
    run_id = f"run-adr112-statement-{uuid4()}"
    created_at = datetime(2026, 10, 21, 1, tzinfo=UTC)
    client = AsyncKorTravelMapClient(migrated_engine)
    root_id, memberships = await _started_root(client, run_id=run_id, created_at=created_at)
    function = f"adr112_slow_{uuid4().hex}"
    async with migrated_engine.begin() as admin:
        await admin.execute(
            text(
                f"""
                CREATE FUNCTION ops.{function}() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                  IF NEW.dagster_run_id = '{run_id}' THEN
                    PERFORM pg_catalog.pg_sleep(30);
                  END IF;
                  RETURN NEW;
                END
                $$
                """
            )
        )
        await admin.execute(
            text(
                f"CREATE TRIGGER {function} BEFORE UPDATE ON ops.import_jobs "
                f"FOR EACH ROW EXECUTE FUNCTION ops.{function}()"
            )
        )
    try:
        tick = _tick_with_remaining(_REMAINING_SECONDS)
        began = time.monotonic()
        with pytest.raises(DBAPIError) as caught:
            await tick.call(
                tick.database_deadline,
                lambda: client.reconcile_dagster_feature_run(
                    dagster_run_id=run_id,
                    trigger_kind="schedule",
                    terminal_status="FAILURE",
                    selected_memberships=memberships,
                    operation_key=SINGLE_MEMBER_OPERATION,
                    engine_created_at=created_at,
                    engine_started_at=created_at + timedelta(seconds=1),
                    engine_finished_at=created_at + timedelta(seconds=5),
                    error=None,
                ),
            )
        elapsed = time.monotonic() - began

        assert pg_error_info(caught.value).sqlstate == "57014"
        assert _classify_failure(caught.value, at_head=False)["closable"] is False
        assert elapsed < _REMAINING_SECONDS
        # 서버에 남아 도는 statement가 없다.
        async with migrated_engine.connect() as probe:
            lingering = await probe.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                    "WHERE state = 'active' AND query LIKE '%provider_feature_operation_terminal%' "
                    "AND pid <> pg_backend_pid()"
                )
            )
        assert lingering == 0
        assert (await _tree(migrated_engine, root_id))[0].status == "running"
    finally:
        async with migrated_engine.begin() as admin:
            await admin.execute(text(f"DROP TRIGGER IF EXISTS {function} ON ops.import_jobs"))
            await admin.execute(text(f"DROP FUNCTION IF EXISTS ops.{function}()"))
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_a_lock_wait_ends_at_the_server_lock_timeout_as_lock_wait(
    migrated_engine: AsyncEngine,
) -> None:
    """lineage lock을 다른 연결이 쥐고 있으면 lock_timeout(남은 시간 − 4초)에 55P03으로 끝난다."""
    run_id = f"run-adr112-lock-{uuid4()}"
    created_at = datetime(2026, 10, 21, 2, tzinfo=UTC)
    client = AsyncKorTravelMapClient(migrated_engine)
    memberships = await client.resolve_feature_operation_memberships(
        operation_key=SINGLE_MEMBER_OPERATION
    )
    async with migrated_engine.connect() as holder:
        await holder.execute(
            text("SELECT pg_advisory_lock(:key)"),
            {"key": advisory_lock_key(_PIPELINE_LINEAGE_MUTATION_LOCK_KEY)},
        )
        try:
            tick = _tick_with_remaining(_REMAINING_SECONDS)
            began = time.monotonic()
            with pytest.raises(DBAPIError) as caught:
                await tick.call(
                    tick.database_deadline,
                    lambda: client.ensure_dagster_feature_operation(
                        dagster_run_id=run_id,
                        trigger_kind="schedule",
                        selected_memberships=memberships,
                        operation_key=SINGLE_MEMBER_OPERATION,
                        engine_created_at=created_at,
                        engine_started_at=None,
                        observed_status="QUEUED",
                    ),
                )
            elapsed = time.monotonic() - began
        finally:
            await holder.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": advisory_lock_key(_PIPELINE_LINEAGE_MUTATION_LOCK_KEY)},
            )
            await holder.commit()

    assert pg_error_info(caught.value).sqlstate == "55P03"
    assert _classify_failure(caught.value, at_head=True)["category"] == "lock_wait"
    assert elapsed < _REMAINING_SECONDS - 2


async def test_a_serializable_success_reconcile_accepts_the_budget_after_isolation(
    migrated_engine: AsyncEngine,
) -> None:
    """SUCCESS reconcile(SERIALIZABLE)도 상한 아래에서 끝난다 — set_config가 isolation 문 다음이다.

    변이: 상한을 isolation 문 앞에 두면 ``SET TRANSACTION ISOLATION LEVEL``이 25001로 거부된다.
    """
    run_id = f"run-adr112-serializable-{uuid4()}"
    created_at = datetime(2026, 10, 21, 3, tzinfo=UTC)
    client = AsyncKorTravelMapClient(migrated_engine)
    root_id, memberships = await _started_root(client, run_id=run_id, created_at=created_at)
    try:
        finished = None
        for membership in memberships:
            finished = await client.finish_dagster_feature_membership(
                dagster_run_id=run_id, membership=membership
            )
        assert finished is not None
        last = max(m.finished_at for m in finished.operation.members if m.finished_at)
        tick = _tick_with_remaining(30)
        mutation = await tick.call(
            tick.database_deadline,
            lambda: client.reconcile_dagster_feature_run(
                dagster_run_id=run_id,
                trigger_kind="schedule",
                terminal_status="SUCCESS",
                selected_memberships=memberships,
                operation_key=SINGLE_MEMBER_OPERATION,
                engine_created_at=created_at,
                engine_started_at=created_at + timedelta(seconds=1),
                engine_finished_at=last + timedelta(seconds=1),
                error=None,
            ),
        )
        assert mutation.operation.status == "done"
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


# --- 결정 4: abandon의 분기 ---------------------------------------------------------------


async def test_abandon_without_a_root_leaves_one_durable_log_row(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-adr112-noroot-{uuid4()}"
    client = AsyncKorTravelMapClient(migrated_engine)
    first_failed_at = datetime(2026, 10, 21, 4, tzinfo=UTC)

    result = await client.abandon_dagster_feature_run(
        dagster_run_id=run_id,
        dagster_status="FAILURE",
        engine_finished_at=None,
        failure={"category": "observation", "closable": True},
        first_failed_at=first_failed_at,
    )

    assert result.outcome == "recorded_without_root"
    assert result.root_job_id is None
    (row,) = await _abandoned_logs(migrated_engine, run_id)
    assert row.level == "error"
    assert row.source == "feature_operation"
    assert row.message.startswith("feature_operation.reconcile_abandoned:")
    assert row.detail["first_failed_at"] == first_failed_at.isoformat()
    assert row.detail["failure"] == {"category": "observation", "closable": True}


async def test_abandon_leaves_a_root_under_cancellation_to_the_coordinator(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-adr112-marker-{uuid4()}"
    created_at = datetime(2026, 10, 21, 5, tzinfo=UTC)
    client = AsyncKorTravelMapClient(migrated_engine)
    root_id, _ = await _started_root(client, run_id=run_id, created_at=created_at)
    async with AsyncSession(migrated_engine) as marker_session, marker_session.begin():
        scope = await resolve_pipeline_cancellation_scope(
            marker_session, kind="import_job", execution_id=root_id
        )
        assert scope is not None
        detail = await create_pipeline_cancellation_attempt(
            marker_session, scope=scope, requested_by="admin:adr112", reason="marker"
        )
    try:
        result = await client.abandon_dagster_feature_run(
            dagster_run_id=run_id,
            dagster_status="FAILURE",
            engine_finished_at=created_at + timedelta(minutes=1),
            failure="operator",
            first_failed_at=None,
        )
        assert result.outcome == "cancellation"
        assert (await _tree(migrated_engine, root_id))[0].status == "running"
        assert await _abandoned_logs(migrated_engine, run_id) == []
    finally:
        await _delete_committed_feature_tree(
            migrated_engine, root_id=root_id, cancellation_id=detail.attempt.cancellation_id
        )


async def test_abandon_does_nothing_to_a_terminal_root_or_a_running_run(
    migrated_engine: AsyncEngine,
) -> None:
    run_id = f"run-adr112-terminal-{uuid4()}"
    created_at = datetime(2026, 10, 21, 6, tzinfo=UTC)
    client = AsyncKorTravelMapClient(migrated_engine)
    root_id, memberships = await _started_root(client, run_id=run_id, created_at=created_at)
    try:
        running = await client.abandon_dagster_feature_run(
            dagster_run_id=run_id,
            dagster_status="STARTED",
            engine_finished_at=None,
            failure="operator",
            first_failed_at=None,
        )
        assert running.outcome == "run_active"
        assert (await _tree(migrated_engine, root_id))[0].status == "running"

        await client.reconcile_dagster_feature_run(
            dagster_run_id=run_id,
            trigger_kind="schedule",
            terminal_status="FAILURE",
            selected_memberships=memberships,
            operation_key=SINGLE_MEMBER_OPERATION,
            engine_created_at=created_at,
            engine_started_at=created_at + timedelta(seconds=1),
            engine_finished_at=created_at + timedelta(seconds=9),
            error=None,
        )
        terminal = await client.abandon_dagster_feature_run(
            dagster_run_id=run_id,
            dagster_status="FAILURE",
            engine_finished_at=None,
            failure="operator",
            first_failed_at=None,
        )
        assert terminal.outcome == "terminal"
        assert await _abandoned_logs(migrated_engine, run_id) == []
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


@pytest.mark.parametrize("dagster_status", ["SUCCESS", "FAILURE", None])
async def test_abandon_closes_an_active_root_whose_run_ended_or_vanished(
    migrated_engine: AsyncEngine, dagster_status: str | None
) -> None:
    """Dagster SUCCESS여도 ``failed``로 닫는다(O4). run이 없으면 dagster_run_status는 NULL."""
    run_id = f"run-adr112-close-{uuid4()}"
    created_at = datetime(2026, 10, 21, 7, tzinfo=UTC)
    client = AsyncKorTravelMapClient(migrated_engine)
    root_id, _ = await _started_root(client, run_id=run_id, created_at=created_at)
    finished_at = created_at + timedelta(minutes=3)
    try:
        result = await client.abandon_dagster_feature_run(
            dagster_run_id=run_id,
            dagster_status=dagster_status,
            engine_finished_at=finished_at if dagster_status is not None else None,
            failure={"category": "closable_sqlstate", "sqlstate": "23502"},
            first_failed_at=created_at + timedelta(minutes=5),
        )

        assert result.outcome == "closed"
        root, *children = await _tree(migrated_engine, root_id)
        assert root.status == "failed"
        assert root.dagster_run_status == dagster_status
        assert {child.status for child in children} == {"failed"}
        if dagster_status is not None:
            assert root.finished_at == finished_at
        (row,) = await _abandoned_logs(migrated_engine, run_id)
        assert row.detail["root_job_id"] == root_id
        assert row.detail["action"] == "re-run the dataset"
        # 닫은 root는 DB page 대상이 아니다(짧은 읽기도 같은 술어).
        assert await client.is_reconcilable_dagster_feature_run(dagster_run_id=run_id) is False
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_a_closed_root_with_a_mistimed_finish_is_still_closed(
    migrated_engine: AsyncEngine,
) -> None:
    """종료 시각이 시작보다 앞서면(불변식이 깨진 run) 그 시각은 버리고 닫는다."""
    run_id = f"run-adr112-mistimed-{uuid4()}"
    created_at = datetime(2026, 10, 21, 8, tzinfo=UTC)
    client = AsyncKorTravelMapClient(migrated_engine)
    root_id, _ = await _started_root(client, run_id=run_id, created_at=created_at)
    try:
        result = await client.abandon_dagster_feature_run(
            dagster_run_id=run_id,
            dagster_status="FAILURE",
            engine_finished_at=created_at - timedelta(hours=1),
            failure="operator",
            first_failed_at=None,
        )
        assert result.outcome == "closed"
        root, *_children = await _tree(migrated_engine, root_id)
        assert root.status == "failed"
        assert root.finished_at is None
    finally:
        await _delete_committed_feature_tree(migrated_engine, root_id=root_id)


async def test_the_completion_sweep_asks_the_server_to_watch_its_connection(
    migrated_engine: AsyncEngine,
) -> None:
    """completion sweep의 트랜잭션은 ``client_connection_check_interval``을 건다."""
    from kortravelmap.infra.transaction_limits import (
        apply_transaction_limits,
        connection_check_interval,
    )

    async with AsyncSession(migrated_engine) as session, session.begin():
        with connection_check_interval(10):
            await apply_transaction_limits(session)
        value = await session.scalar(text("SHOW client_connection_check_interval"))
    assert value == "10s"
    await asyncio.sleep(0)
