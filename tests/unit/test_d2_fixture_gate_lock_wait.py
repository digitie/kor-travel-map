"""D2 fixture helper의 쓰기 action은 전역 Feature 쓰기 gate를 **길게 기다려** 먼저 잡는다.

2026-11-12 prod D2(t1112b, Map aa38c30a)는 spec 2/2가 통과한 뒤 ``purge``에서 죽었다.
``feature.purge_manual_feature`` 안의 ``ops.lock_scoped_feature_write_protocol(true)``가
``pg_advisory_xact_lock(1369104691,115)``을 기다렸는데, 세션 ``lock_timeout``이 0이라
gate 함수가 그것을 **1초**로 바꿔 잡았다. 같은 시각 큐 적재
(``feature_notice_krforest_landslide_forecast_issues_job``)가 쓰기 단계에서 gate를 쥐고
있었으므로 55P03(lock timeout)으로 실패했고 lane은 ``purge-failed`` BLOCKED가 됐다.

provider 적재는 같은 경합을 ``execute_with_lock_wait``로 푼다(T-LOAD-LOCK-WAIT). helper의
``seed``·``cleanup``·``purge``도 **DB를 건드리기 전에** 그 경로로 gate를 먼저 잡아야 한다.
뒤따르는 procedure의 gate 획득은 같은 transaction의 재진입이라 즉시 통과한다.
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "scripts" / "admin_feature_live_fixture.py"
RUN_ID = "live-20261112042038-248d061ffd5b"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = _load("admin_feature_live_fixture_gate_wait", _FIXTURE)


class _GateTaken(Exception):
    """gate를 잡는 호출에 닿았다 — 그 뒤는 이 테스트의 관심 밖이다."""


class _NoDbBeforeGate:
    """gate 전에 어떤 문장이라도 실행하면 실패하는 session 대역."""

    def __init__(self) -> None:
        self.info: dict[str, object] = {}

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("gate를 잡기 전에 DB 문장을 실행했다")

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("gate를 잡기 전에 DB 문장을 실행했다")

    async def scalars(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("gate를 잡기 전에 DB 문장을 실행했다")


_ACTIONS: dict[str, Callable[[Any, str], Awaitable[Any]]] = {
    "seed": fixture._seed,
    "cleanup": fixture._cleanup,
    "purge": fixture._purge_api_owned,
}


@pytest.mark.parametrize("action", sorted(_ACTIONS))
def test_write_action_takes_the_gate_first_with_a_long_bounded_wait(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_execute_with_lock_wait(
        session: Any, statement: str, wait_ms: int, *, label: str, params: Any = None
    ) -> None:
        calls.append((statement, wait_ms))
        raise _GateTaken

    monkeypatch.setattr(fixture, "execute_with_lock_wait", fake_execute_with_lock_wait)

    with pytest.raises(_GateTaken):
        asyncio.run(_ACTIONS[action](_NoDbBeforeGate(), RUN_ID))

    assert len(calls) == 1
    statement, wait_ms = calls[0]
    assert "ops.lock_scoped_feature_write_protocol(true)" in statement
    # 1초(gate 함수의 기본)가 아니라 몇 분 — 그러나 무한은 아니다.
    assert 120_000 <= wait_ms <= 1_800_000
