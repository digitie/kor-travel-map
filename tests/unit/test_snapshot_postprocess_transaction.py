"""전용 TX의 commit/오류/불명확 응답 경계. 실제 PG 효과는 별도 통합 시험이다."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _snapshot_postprocess as target
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotExecutorToken

_TOKEN = SnapshotExecutorToken(uuid4(), 1, uuid4())
_RECEIPT = b"canonical-DB-checked-candidate"


class _TX:
    def __init__(self, *, lost=False):
        self.lost = lost
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, kind, exc, tb):
        if kind is not None:
            self.rolled_back = True
        elif self.lost:
            raise RuntimeError("commit response lost")
        else:
            self.committed = True


class _Session:
    def __init__(self, *, lost=False):
        self.tx = _TX(lost=lost)
        self.connection = AsyncMock(return_value=object())
        self.execute = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def begin(self):
        return self.tx


def _setup(monkeypatch, *, saved=None, lost=False):
    session = _Session(lost=lost)
    client = object.__new__(AsyncKorTravelMapClient)
    client._transaction_bound = False
    client._session_factory = Mock(return_value=session)
    client._engine = object()
    begin, finish = AsyncMock(return_value=saved), AsyncMock()
    monkeypatch.setattr(target, "begin_provider_snapshot_postprocess", begin)
    monkeypatch.setattr(target, "finish_provider_snapshot_postprocess", finish)
    monkeypatch.setattr(target, "apply_transaction_limits", AsyncMock())
    return client, session, begin, finish


async def test_all_effects_use_original_connection_and_commit_after_mark(monkeypatch):
    client, session, begin, finish = _setup(monkeypatch)
    seen = []

    async def work(bound):
        assert bound is not client
        assert bound._transaction_bound is True
        assert bound._session_factory.kw["bind"] is session.connection.return_value
        assert bound._session_factory.kw["join_transaction_mode"] == "rollback_only"
        with pytest.raises(RuntimeError, match="original connection"):
            bound._engine.connect()
        assert not session.tx.committed
        finish.assert_not_awaited()
        seen.append(bound)

    result = await client.run_provider_snapshot_postprocess(_TOKEN, _RECEIPT, work)
    assert result is _RECEIPT
    assert len(seen) == 1
    begin.assert_awaited_once_with(session, _TOKEN, _RECEIPT)
    finish.assert_awaited_once_with(session, _TOKEN, _RECEIPT)
    assert session.tx.committed
    assert client._transaction_bound is False
    assert str(session.execute.await_args_list[0].args[0]).endswith("READ COMMITTED")


async def test_already_postprocessed_skips_all_effects_and_connections(monkeypatch):
    client, session, _, finish = _setup(monkeypatch, saved=_RECEIPT)
    work = AsyncMock()
    assert await client.run_provider_snapshot_postprocess(_TOKEN, _RECEIPT, work) == _RECEIPT
    work.assert_not_awaited()
    finish.assert_not_awaited()
    session.connection.assert_not_awaited()


@pytest.mark.parametrize("cancel", [False, True])
async def test_partial_effect_failure_or_cancel_rolls_back_and_does_not_mark(monkeypatch, cancel):
    client, session, _, finish = _setup(monkeypatch)
    error = asyncio.CancelledError() if cancel else RuntimeError("partial findings failure")
    with pytest.raises(type(error)) as caught:
        await client.run_provider_snapshot_postprocess(
            _TOKEN, _RECEIPT, AsyncMock(side_effect=error)
        )
    assert caught.value is error
    assert session.tx.rolled_back
    assert not session.tx.committed
    finish.assert_not_awaited()


async def test_unknown_commit_never_returns_completion_or_replays_effects_automatically(
    monkeypatch,
):
    client, session, _, finish = _setup(monkeypatch, lost=True)
    work = AsyncMock()
    with pytest.raises(RuntimeError, match="commit response lost"):
        await client.run_provider_snapshot_postprocess(_TOKEN, _RECEIPT, work)
    finish.assert_awaited_once()
    work.assert_awaited_once()
    assert not session.tx.committed
    # caller의 fresh SDK0 read가 완료를 확인한 경우만 새 호출의 stored fastpath를 사용할 수 있다.
    other, _, _, other_finish = _setup(monkeypatch, saved=_RECEIPT)
    assert await other.run_provider_snapshot_postprocess(_TOKEN, _RECEIPT, work) == _RECEIPT
    work.assert_awaited_once()
    other_finish.assert_not_awaited()


async def test_bound_client_cannot_open_another_outer_transaction(monkeypatch):
    client, _, _, _ = _setup(monkeypatch)
    client._transaction_bound = True
    with pytest.raises(RuntimeError, match="own transaction"):
        await client.run_provider_snapshot_postprocess(_TOKEN, _RECEIPT, AsyncMock())
    client._session_factory.assert_not_called()


async def test_no_candidate_stops_before_transaction(monkeypatch):
    client, _, _, _ = _setup(monkeypatch)
    with pytest.raises(ValueError, match="bounded"):
        await client.run_provider_snapshot_postprocess(_TOKEN, b"", AsyncMock())
    client._session_factory.assert_not_called()
