"""ADR-112 결정 2 — sensor가 여는 트랜잭션마다 서버 쪽 상한이 걸린다.

실제 서버 효과(57014·55P03)는 ``tests/integration/test_reconcile_retry.py``가 본다. 여기서는
client의 sensor 경로 메서드가 **빠짐없이** 트랜잭션 첫머리(명시 isolation 문 다음)에
상한을 거는지, 보조 트랜잭션(invariant conflict 기록)까지 포함해 본다.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import kortravelmap.client as client_module
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.feature_operation import FeatureOperationInvariantConflict
from kortravelmap.infra.transaction_limits import (
    TransactionBudget,
    apply_transaction_limits,
    connection_check_interval,
    transaction_deadline,
)

_SET_LIMITS = "set_config('statement_timeout'"
_ISOLATION = "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Session:
    def __init__(self) -> None:
        self.executed: list[str] = []
        # AsyncSession.info처럼 — 권위 finish가 무장 대기를 여기에 싣는다(433 WI-1).
        self.info: dict[str, object] = {}

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, statement: object, params: object = None) -> None:
        self.executed.append(str(statement))


class _SessionFactory:
    def __init__(self) -> None:
        self.sessions: list[_Session] = []

    def __call__(self) -> _Session:
        session = _Session()
        self.sessions.append(session)
        return session


def test_budget_follows_the_owner_decision() -> None:
    """statement = 남은 − 3초, lock = min(5초, 남은 − 4초)(2026-10-21 소유자 결정)."""
    assert TransactionBudget.from_remaining(40) == TransactionBudget(37_000, 5_000)
    assert TransactionBudget.from_remaining(8) == TransactionBudget(5_000, 4_000)
    # 바닥값 — 0은 Postgres에서 "상한 없음"이다.
    assert TransactionBudget.from_remaining(1) == TransactionBudget(1_000, 500)


async def test_nothing_is_sent_without_a_deadline() -> None:
    session = _Session()

    assert await apply_transaction_limits(session) is None  # type: ignore[arg-type]
    assert session.executed == []

    with connection_check_interval(10):
        await apply_transaction_limits(session)  # type: ignore[arg-type]
    assert session.executed == [
        "SELECT set_config('client_connection_check_interval', :interval, true)"
    ]


async def _stub(*_args: Any, **_kwargs: Any) -> Any:
    return None


_NOW = datetime(2026, 7, 21, tzinfo=UTC)
_CALLS: dict[str, tuple[str, Callable[[AsyncKorTravelMapClient], Awaitable[Any]]]] = {
    "ensure": (
        "repo_ensure_dagster_feature_operation",
        lambda c: c.ensure_dagster_feature_operation(
            dagster_run_id="r",
            trigger_kind="schedule",
            selected_memberships=(),
            operation_key="k",
            engine_created_at=_NOW,
            engine_started_at=None,
            observed_status="QUEUED",
        ),
    ),
    "reconcile_failure": (
        "repo_reconcile_dagster_feature_run",
        lambda c: c.reconcile_dagster_feature_run(
            dagster_run_id="r",
            trigger_kind="schedule",
            terminal_status="FAILURE",
            selected_memberships=(),
            operation_key="k",
            engine_created_at=_NOW,
            engine_started_at=None,
            engine_finished_at=_NOW,
            error=None,
        ),
    ),
    "list": (
        "repo_list_reconcilable_feature_runs",
        lambda c: c.list_reconcilable_dagster_feature_runs(cursor=None),
    ),
    "list_memberships": (
        "repo_list_feature_operation_memberships",
        lambda c: c.list_feature_operation_memberships(operation_key="k"),
    ),
    "resolve_memberships": (
        "repo_resolve_feature_operation_memberships",
        lambda c: c.resolve_feature_operation_memberships(operation_key="k"),
    ),
    "resolve_dataset_membership": (
        "repo_resolve_operation_dataset_member",
        lambda c: c.resolve_feature_operation_dataset_membership(
            operation_key="k", provider="p", dataset_key="d"
        ),
    ),
    "is_reconcilable": (
        "repo_is_reconcilable_dagster_feature_run",
        lambda c: c.is_reconcilable_dagster_feature_run(dagster_run_id="r"),
    ),
    "abandon": (
        "repo_abandon_dagster_feature_run",
        lambda c: c.abandon_dagster_feature_run(
            dagster_run_id="r",
            dagster_status=None,
            engine_finished_at=None,
            failure="operator",
            first_failed_at=None,
        ),
    ),
    "stalled": (
        "repo_record_reconcile_stalled",
        lambda c: c.record_feature_operation_reconcile_stalled(
            scope="head",
            dagster_run_id="r",
            dagster_status=None,
            first_failed_at=_NOW,
            last_failure={},
            alerted_at=None,
            action="a",
        ),
    ),
}


def _client(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncKorTravelMapClient, _SessionFactory]:
    engine = create_async_engine("postgresql+asyncpg://user:pw@127.0.0.1:1/none")
    client = AsyncKorTravelMapClient(engine)
    factory = _SessionFactory()
    monkeypatch.setattr(client, "_session_factory", factory)
    return client, factory


@pytest.mark.parametrize("name", sorted(_CALLS))
async def test_every_sensor_path_transaction_carries_the_limits(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    repo_name, call = _CALLS[name]
    monkeypatch.setattr(client_module, repo_name, _stub)
    client, factory = _client(monkeypatch)

    with transaction_deadline(time.monotonic() + 20):
        await call(client)

    (session,) = factory.sessions
    assert _SET_LIMITS in session.executed[0]


async def test_read_committed_reconcile_sets_the_limits_after_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_module, "repo_reconcile_dagster_feature_run", _stub)
    client, factory = _client(monkeypatch)

    with transaction_deadline(time.monotonic() + 20):
        await client.reconcile_dagster_feature_run(
            dagster_run_id="r",
            trigger_kind="schedule",
            terminal_status="SUCCESS",
            selected_memberships=(),
            operation_key="k",
            engine_created_at=_NOW,
            engine_started_at=None,
            engine_finished_at=_NOW,
            error=None,
        )

    (session,) = factory.sessions
    assert session.executed[0] == _ISOLATION
    assert _SET_LIMITS in session.executed[1]


async def test_the_conflict_record_transaction_also_carries_the_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _conflict(*_args: Any, **_kwargs: Any) -> Any:
        raise FeatureOperationInvariantConflict("x", dagster_run_id="r")

    monkeypatch.setattr(client_module, "repo_ensure_dagster_feature_operation", _conflict)
    monkeypatch.setattr(client_module, "record_feature_operation_invariant_conflict", _stub)
    client, factory = _client(monkeypatch)

    with (
        transaction_deadline(time.monotonic() + 20),
        pytest.raises(FeatureOperationInvariantConflict),
    ):
        await _CALLS["ensure"][1](client)

    assert len(factory.sessions) == 2
    assert all(_SET_LIMITS in session.executed[0] for session in factory.sessions)
