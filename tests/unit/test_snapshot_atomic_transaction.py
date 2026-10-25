"""선택A의 동일 session/outer commit 경계. 실제 PG 효과는 별도 통합 시험이다."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _snapshot_atomic as target
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotExecutorToken,
    SnapshotMember,
    SnapshotRecoveryCorruption,
)
from kortravelmap.infra.provider_snapshot_result import (
    SnapshotApplyResult,
    encode_snapshot_apply_result,
)
from tests.unit.test_provider_snapshot_artifact import _PINS


class _Transaction:
    def __init__(self, events, *, commit_error=None):
        self.events = events
        self.commit_error = commit_error
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        self.events.append("begin")
        return self

    async def __aexit__(self, kind, exc, tb):
        if kind is not None:
            self.rolled_back = True
            self.events.append("rollback")
        else:
            self.events.append("commit")
            if self.commit_error is not None:
                raise self.commit_error
            self.committed = True


class _Session:
    def __init__(self, events, *, commit_error=None):
        self.tx = _Transaction(events, commit_error=commit_error)
        self.execute = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def begin(self):
        return self.tx


def _case(monkeypatch, *, commit_error=None):
    events = []
    session = _Session(events, commit_error=commit_error)
    client = object.__new__(AsyncKorTravelMapClient)
    client._transaction_bound = False
    client._session_factory = Mock(return_value=session)
    token = SnapshotExecutorToken(uuid4(), 3, uuid4())
    member = SnapshotMember(uuid4(), uuid4(), uuid4())
    result = SnapshotApplyResult(
        FeatureLoadResult(
            bundles_total=2,
            source_records_inserted=2,
            curation_input_member_count=2,
            curation_input_set_hash="d" * 64,
        ),
        retired=0,
    )
    observed = RecoveredProviderSnapshot(
        token.snapshot_id,
        None,
        b"frozen-input",
        "a" * 64,
        b"frozen-context",
        "b" * 64,
        "prepared",
        None,
        None,
        None,
        datetime(2026, 10, 26, tzinfo=UTC),
        "running",
        "running",
        False,
        None,
    )
    fresh = replace(
        observed,
        status="applied",
        applied_result=result,
        applied_result_bytes=encode_snapshot_apply_result(result.load, retired=0),
    )
    receipt = b"canonical-receipt-checked-by-database"
    work = target.SnapshotPostprocessWork(receipt, AsyncMock())

    async def apply(same):
        assert same is session
        assert not session.tx.committed
        events.append("apply")
        return result

    async def read(same, identity, *, expected_pins):
        assert same is session
        assert identity is member
        assert expected_pins is _PINS
        assert not session.tx.committed
        events.append("read-uncommitted")
        return fresh

    def prepare(same):
        assert same is fresh
        assert not session.tx.committed
        events.append("prepare-original")
        return work

    async def post(original, same, current, raw, callback):
        assert original is client
        assert same is session
        assert current is token
        assert raw is receipt
        assert callback is work.work
        assert not session.tx.committed
        events.append("postprocess")
        return receipt

    read_mock = AsyncMock(side_effect=read)
    post_mock = AsyncMock(side_effect=post)
    monkeypatch.setattr(target, "read_provider_snapshot_for_member", read_mock)
    monkeypatch.setattr(target, "run_snapshot_postprocess_in_session", post_mock)
    limits = AsyncMock()
    monkeypatch.setattr(target, "apply_bounded_transaction_limits", limits)
    return (
        client,
        session,
        token,
        member,
        observed,
        fresh,
        result,
        work,
        apply,
        prepare,
        events,
        read_mock,
        post_mock,
        limits,
    )


async def _run(case, **changes):
    client, _, token, member, observed, _, _, _, apply, prepare, *_ = case
    args = dict(
        client=client,
        observed=observed,
        token=token,
        member=member,
        pins=_PINS,
        apply=apply,
        prepare=prepare,
    )
    args.update(changes)
    return await target.run_snapshot_apply_postprocess(**args)


async def test_apply_read_prepare_and_postprocess_share_one_session_before_only_commit(monkeypatch):
    case = _case(monkeypatch)
    result = await _run(case)
    assert result == target.SnapshotAtomicCompletion(case[6], case[7].receipt_candidate)
    assert case[10] == [
        "begin",
        "apply",
        "read-uncommitted",
        "prepare-original",
        "postprocess",
        "commit",
    ]
    assert case[1].tx.committed
    assert not case[1].tx.rolled_back
    case[13].assert_awaited_once_with(case[1])
    assert (
        str(case[1].execute.await_args.args[0]) == "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
    )
    case[0]._session_factory.assert_called_once_with()


@pytest.mark.parametrize("stage", ["apply", "read", "prepare", "postprocess"])
@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
async def test_failure_at_each_stage_rolls_back_without_commit_or_completion(
    monkeypatch, stage, cancel
):
    case = _case(monkeypatch)
    error = asyncio.CancelledError() if cancel else RuntimeError("owned stage fault")
    changes = {}
    if stage == "apply":
        changes["apply"] = AsyncMock(side_effect=error)
    elif stage == "read":
        case[11].side_effect = error
    elif stage == "prepare":
        changes["prepare"] = Mock(side_effect=error)
    else:
        case[12].side_effect = error
    with pytest.raises(type(error)) as raised:
        await _run(case, **changes)
    assert raised.value is error
    assert case[1].tx.rolled_back
    assert not case[1].tx.committed
    assert "commit" not in case[10]
    if stage != "postprocess":
        case[12].assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        {"snapshot_id": uuid4()},
        {"artifact_sha256": "c" * 64},
        {"context_sha256": "e" * 64},
        {"status": "prepared"},
        {"applied_result": None},
        {"applied_result_bytes": None},
        {"postprocess_receipt": b"already-completed"},
        {"root_status": "done"},
        {"child_status": "done"},
        {"cancellation_present": True},
    ],
)
async def test_changed_fresh_identity_or_phase_rejects_and_rolls_back_before_work(
    monkeypatch, change
):
    case = _case(monkeypatch)
    case[11].side_effect = None
    case[11].return_value = replace(case[5], **change)
    with pytest.raises(SnapshotRecoveryCorruption, match="original result"):
        await _run(case)
    assert case[1].tx.rolled_back
    case[12].assert_not_awaited()


async def test_missing_fresh_row_is_corruption_not_implicit_retry(monkeypatch):
    case = _case(monkeypatch)
    case[11].side_effect = None
    case[11].return_value = None
    with pytest.raises(SnapshotRecoveryCorruption):
        await _run(case)
    assert case[1].tx.rolled_back
    case[12].assert_not_awaited()


async def test_foreign_prepare_work_is_rejected_before_postprocess(monkeypatch):
    case = _case(monkeypatch)
    with pytest.raises(SnapshotRecoveryCorruption, match="canonical postprocess"):
        await _run(case, prepare=Mock(return_value=object()))
    assert case[1].tx.rolled_back
    case[12].assert_not_awaited()


async def test_commit_response_loss_propagates_once_without_internal_reapply(monkeypatch):
    error = RuntimeError("owned commit response lost")
    case = _case(monkeypatch, commit_error=error)
    with pytest.raises(RuntimeError) as raised:
        await _run(case)
    assert raised.value is error
    assert case[10].count("apply") == case[10].count("postprocess") == case[10].count("commit") == 1
    assert not case[1].tx.committed
    case[0]._session_factory.assert_called_once_with()


@pytest.mark.parametrize("kind", ["bound", "not-prepared", "wrong-token"])
async def test_invalid_entry_never_opens_transaction(monkeypatch, kind):
    case = _case(monkeypatch)
    changes = {}
    if kind == "bound":
        case[0]._transaction_bound = True
    elif kind == "not-prepared":
        changes["observed"] = replace(case[4], status="applied")
    else:
        changes["token"] = SnapshotExecutorToken(uuid4(), 3, uuid4())
    with pytest.raises((RuntimeError, SnapshotRecoveryCorruption)):
        await _run(case, **changes)
    case[0]._session_factory.assert_not_called()
