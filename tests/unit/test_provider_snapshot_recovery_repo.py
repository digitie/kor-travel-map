"""SDK0 복구 관측과 caller TX 경계. 실제 PostgreSQL/430 설치 수용은 아니다."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import provider_snapshot_recovery_repo as repo
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.infra.provider_snapshot_artifact import (
    UnsupportedSnapshotArtifact,
    encode_provider_snapshot_artifact,
)
from kortravelmap.infra.provider_snapshot_result import (
    InvalidSnapshotApplyResult,
    encode_snapshot_apply_result,
)
from tests.unit.test_provider_snapshot_artifact import _PINS, _input

_NOW = datetime(2026, 10, 25, tzinfo=UTC)


def _session(row):
    session = MagicMock(spec=AsyncSession)
    session.in_transaction.return_value = True
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = row
    result.mappings.return_value.one.return_value = row
    result.scalar_one.return_value = {
        "status": "applying",
        "apply_txid": 123,
        "snapshot_observation_generation": "original-generation",
        "additional": ["preserved"],
    }
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.fixture
async def saved():
    import hashlib

    bundles, geo = await _input(resolved=True)
    payload = encode_provider_snapshot_artifact(bundles, geo, pins=_PINS)
    context = b"opaque-context"
    # 서로 다른 counter를 사용하여 일부 필드 누락/재계산을 감춘 기본0과 구분한다.
    values = {
        key: n + 1
        for n, key in enumerate(FeatureLoadResult.__dataclass_fields__)
        if key != "curation_input_set_hash"
    }
    values["curation_input_set_hash"] = "d" * 64
    original = encode_snapshot_apply_result(FeatureLoadResult(**values), retired=17)
    from kortravelmap.infra.provider_snapshot_artifact import decode_provider_snapshot_artifact

    return {
        "snapshot_id": uuid4(),
        "artifact_payload": payload,
        "artifact_sha256": hashlib.sha256(payload).hexdigest(),
        "observation_context": context,
        "context_sha256": hashlib.sha256(context).hexdigest(),
        "native_input_digest": decode_provider_snapshot_artifact(
            payload, expected_pins=_PINS
        ).native_input_digest,
        "snapshot_status": "applied",
        "applied_result": original,
        "postprocess_receipt": None,
        "lease_expires_at": _NOW,
        "root_status": "running",
        "child_status": "running",
        "cancellation_present": False,
        "attempt_id": uuid4(),
        "attempt_owner": uuid4(),
        "manifest_digest": "e" * 64,
        "kernel_status": "completed",
        "kernel_input_digest": "f" * 64,
        "kernel_lease_expires_at": _NOW,
    }


def _member():
    return repo.SnapshotMember(uuid4(), uuid4(), uuid4())


def _token():
    return repo.SnapshotExecutorToken(uuid4(), 1, uuid4())


async def test_unknown_commit_recovery_returns_all_original_result_without_writes(saved):
    session = _session(saved)
    observed = await repo.read_provider_snapshot_for_member(session, _member(), expected_pins=_PINS)
    assert observed.artifact_payload is saved["artifact_payload"]
    assert observed.applied_result_bytes is saved["applied_result"]
    assert observed.kernel_binding.status == "completed"
    assert observed.applied_result.retired == 17
    assert (
        encode_snapshot_apply_result(
            observed.applied_result.load, retired=observed.applied_result.retired
        )
        == saved["applied_result"]
    )
    assert observed.artifact_sha256 == saved["artifact_sha256"]
    assert observed.observation_context == b"opaque-context"
    assert observed.artifact.bundles[0].source_record.source_record_key
    session.execute.assert_awaited_once()
    assert str(session.execute.await_args.args[0]).startswith(
        "SELECT * FROM ops.read_provider_snapshot_for_member("
    )
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.begin.assert_not_called()


async def test_only_absent_member_is_none_not_a_corrupt_fallback():
    session = _session(None)
    assert (
        await repo.read_provider_snapshot_for_member(session, _member(), expected_pins=_PINS)
        is None
    )
    session.execute.assert_awaited_once()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_sha256", "0" * 64),
        ("context_sha256", "0" * 64),
        ("native_input_digest", "0" * 64),
        ("observation_context", b""),
        ("observation_context", b"x" * 8193),
        ("snapshot_status", "future"),
        ("snapshot_status", "prepared"),
        ("postprocess_receipt", b"unexpected"),
        ("applied_result", None),
        ("root_status", "future"),
        ("cancellation_present", 1),
        ("lease_expires_at", datetime(2026, 10, 25)),
        ("snapshot_id", "not-a-uuid"),
    ],
)
async def test_corrupt_database_observation_never_becomes_unregistered(saved, field, value):
    session = _session({**saved, field: value})
    with pytest.raises(repo.SnapshotRecoveryCorruption):
        await repo.read_provider_snapshot_for_member(session, _member(), expected_pins=_PINS)
    session.execute.assert_awaited_once()


async def test_canonical_result_corruption_is_not_recomputed(saved):
    session = _session({**saved, "applied_result": b'{"bundles_total":1}'})
    with pytest.raises(InvalidSnapshotApplyResult):
        await repo.read_provider_snapshot_for_member(session, _member(), expected_pins=_PINS)


async def test_changed_expected_code_pins_rejected(saved):
    with pytest.raises(UnsupportedSnapshotArtifact):
        await repo.read_provider_snapshot_for_member(
            _session(saved), _member(), expected_pins=replace(_PINS, code_revision="c" * 40)
        )


async def test_prepared_and_child_sealed_recovery_state_preserved(saved):
    prepared = {**saved, "snapshot_status": "prepared", "applied_result": None}
    observed = await repo.read_provider_snapshot_for_member(
        _session(prepared), _member(), expected_pins=_PINS
    )
    assert observed.applied_result is None
    sealed = {
        **saved,
        "snapshot_status": "child_sealed",
        "postprocess_receipt": b"receipt",
        "child_status": "done",
        "root_status": "failed",
        "cancellation_present": True,
    }
    observed = await repo.read_provider_snapshot_for_member(
        _session(sealed), _member(), expected_pins=_PINS
    )
    # read는 실패/취소를 되살리지 않는다. 반환값이 이어서 실행할 권위도 아니다.
    assert observed.root_status == "failed"
    assert observed.cancellation_present
    assert observed.status == "child_sealed"
    with pytest.raises(repo.SnapshotRecoveryCorruption):
        await repo.read_provider_snapshot_for_member(
            _session({**sealed, "child_status": "running"}), _member(), expected_pins=_PINS
        )


async def test_registration_duplicate_nonce_never_becomes_executor_authority(saved):
    row = {"snapshot_id": saved["snapshot_id"], "created": False, "generation": None, "fence": None}
    observed = await repo.register_provider_snapshot_artifact(
        _session(row),
        _member(),
        artifact_payload=saved["artifact_payload"],
        observation_context=saved["observation_context"],
        expected_pins=_PINS,
        lease_seconds=30,
    )
    assert not observed.created
    assert observed.token is None
    with pytest.raises(repo.SnapshotRecoveryCorruption):
        await repo.register_provider_snapshot_artifact(
            _session({**row, "generation": 1, "fence": uuid4()}),
            _member(),
            artifact_payload=saved["artifact_payload"],
            observation_context=saved["observation_context"],
            expected_pins=_PINS,
            lease_seconds=30,
        )


async def test_register_new_and_claim_return_only_sd_fence(saved):
    fence = uuid4()
    row = {"snapshot_id": saved["snapshot_id"], "created": True, "generation": 1, "fence": fence}
    registered = await repo.register_provider_snapshot_artifact(
        _session(row),
        _member(),
        artifact_payload=saved["artifact_payload"],
        observation_context=saved["observation_context"],
        expected_pins=_PINS,
        lease_seconds=30,
    )
    assert registered.token.fence == fence
    claim = _session(
        {"generation": 2, "fence": uuid4(), "lease_expires_at": _NOW, "snapshot_status": "applied"}
    )
    lease = await repo.claim_provider_snapshot_executor(
        claim,
        saved["snapshot_id"],
        artifact_sha256=saved["artifact_sha256"],
        context_sha256=saved["context_sha256"],
        lease_seconds=30,
    )
    assert lease.token.generation == 2
    assert lease.status == "applied"
    # 시각이 만료된 듯 보여도 client가 새 token을 만들거나 재claim하지 않는다.
    assert lease.expires_at == _NOW
    assert claim.execute.await_args.args[1]["generation"] is None
    with pytest.raises(ValueError, match="another snapshot"):
        await repo.claim_provider_snapshot_executor(
            claim,
            saved["snapshot_id"],
            artifact_sha256=saved["artifact_sha256"],
            context_sha256=saved["context_sha256"],
            lease_seconds=30,
            previous=_token(),
        )


async def test_all_commands_require_existing_caller_transaction_before_sql(saved):
    session = _session(saved)
    session.in_transaction.return_value = False
    token, member = _token(), _member()
    commands = [
        repo.read_provider_snapshot_for_member(session, member, expected_pins=_PINS),
        repo.register_provider_snapshot_artifact(
            session,
            member,
            artifact_payload=saved["artifact_payload"],
            observation_context=b"context",
            expected_pins=_PINS,
            lease_seconds=30,
        ),
        repo.claim_provider_snapshot_executor(
            session,
            token.snapshot_id,
            artifact_sha256="a" * 64,
            context_sha256="b" * 64,
            lease_seconds=30,
        ),
        repo.bind_provider_snapshot_plan(
            session,
            token,
            attempt_id=uuid4(),
            owner=uuid4(),
            manifest_digest="a" * 64,
            kernel_input_digest="b" * 64,
        ),
        repo.begin_provider_snapshot_apply(
            session,
            token,
            attempt_id=uuid4(),
            owner=uuid4(),
            manifest_digest="a" * 64,
            artifact_sha256="b" * 64,
        ),
        repo.finish_provider_snapshot_apply(
            session, token, original_result=saved["applied_result"]
        ),
        repo.seal_provider_snapshot_member(
            session,
            token,
            artifact_sha256="a" * 64,
            context_sha256="b" * 64,
            result_sha256="c" * 64,
            postprocess_sha256="d" * 64,
        ),
    ]
    for command in commands:
        with pytest.raises(RuntimeError, match="caller-owned"):
            await command
    session.execute.assert_not_called()
    session.begin.assert_not_called()


async def test_bind_begin_finish_seal_delegate_same_session_and_keep_original_bytes(saved):
    session = _session({"o_observed_at": _NOW, "o_replayed": True})
    token, attempt, owner = _token(), uuid4(), uuid4()
    await repo.bind_provider_snapshot_plan(
        session,
        token,
        attempt_id=attempt,
        owner=owner,
        manifest_digest="a" * 64,
        kernel_input_digest="b" * 64,
    )
    await repo.begin_provider_snapshot_apply(
        session,
        token,
        attempt_id=attempt,
        owner=owner,
        manifest_digest="a" * 64,
        artifact_sha256=saved["artifact_sha256"],
    )
    await repo.finish_provider_snapshot_apply(
        session, token, original_result=saved["applied_result"]
    )
    seal = await repo.seal_provider_snapshot_member(
        session,
        token,
        artifact_sha256=saved["artifact_sha256"],
        context_sha256=saved["context_sha256"],
        result_sha256="c" * 64,
        postprocess_sha256="d" * 64,
    )
    calls = session.execute.await_args_list
    assert len(calls) == 4
    assert calls[2].args[1]["result"] is saved["applied_result"]
    assert calls[1].args[1]["artifact"] == saved["artifact_sha256"]
    assert ":manifest,:artifact" in str(calls[1].args[0])
    assert seal.replayed
    assert seal.observed_at == _NOW
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.begin.assert_not_called()


async def test_finish_rejects_partial_result_before_database_call():
    session = _session(None)
    with pytest.raises(InvalidSnapshotApplyResult):
        await repo.finish_provider_snapshot_apply(session, _token(), original_result=b"{}")
    session.execute.assert_not_called()


@pytest.mark.parametrize("bad", [True, 0, -1, 2**63])
async def test_invalid_generation_cannot_issue_command(bad):
    session = _session(None)
    token = replace(_token(), generation=bad)
    with pytest.raises(repo.SnapshotRecoveryCorruption):
        await repo.bind_provider_snapshot_plan(
            session,
            token,
            attempt_id=uuid4(),
            owner=uuid4(),
            manifest_digest="a" * 64,
            kernel_input_digest="b" * 64,
        )
    session.execute.assert_not_called()


@pytest.mark.parametrize(
    "missing",
    [
        "attempt_id",
        "attempt_owner",
        "manifest_digest",
        "kernel_status",
        "kernel_input_digest",
        "kernel_lease_expires_at",
    ],
)
async def test_partial_existing_plan_cannot_be_replaced_by_new_plan(saved, missing):
    with pytest.raises(repo.SnapshotRecoveryCorruption, match="partial kernel"):
        await repo.read_provider_snapshot_for_member(
            _session({**saved, missing: None}), _member(), expected_pins=_PINS
        )


async def test_unbound_prepared_state_and_cancelled_plan_are_distinct(saved):
    keys = (
        "attempt_id",
        "attempt_owner",
        "manifest_digest",
        "kernel_status",
        "kernel_input_digest",
        "kernel_lease_expires_at",
    )
    row = {**saved, **dict.fromkeys(keys), "snapshot_status": "prepared", "applied_result": None}
    observed = await repo.read_provider_snapshot_for_member(
        _session(row), _member(), expected_pins=_PINS
    )
    assert observed.kernel_binding is None
    row = {
        **saved,
        "snapshot_status": "prepared",
        "applied_result": None,
        "kernel_status": "cancelled",
    }
    observed = await repo.read_provider_snapshot_for_member(
        _session(row), _member(), expected_pins=_PINS
    )
    assert observed.kernel_binding.attempt_id == saved["attempt_id"]
    assert observed.kernel_binding.status == "cancelled"
    with pytest.raises(repo.SnapshotRecoveryCorruption, match="completed kernel"):
        await repo.read_provider_snapshot_for_member(
            _session({**saved, "kernel_status": "ready"}), _member(), expected_pins=_PINS
        )


async def test_real_asyncpg_uuid_values_are_normalized_without_database(saved):
    from asyncpg.pgproto.pgproto import UUID as AsyncpgUUID

    snapshot_id = AsyncpgUUID(str(saved["snapshot_id"]))
    assert isinstance(snapshot_id, type(saved["snapshot_id"]))
    assert type(snapshot_id) is not type(saved["snapshot_id"])
    observed = await repo.read_provider_snapshot_for_member(
        _session({**saved, "snapshot_id": snapshot_id}), _member(), expected_pins=_PINS
    )
    assert type(observed.snapshot_id) is type(saved["snapshot_id"])
    assert observed.snapshot_id == saved["snapshot_id"]


async def test_begin_preserves_additional_kernel_and_observation_fields():
    session = _session(None)
    value = await repo.begin_provider_snapshot_apply(
        session,
        _token(),
        attempt_id=uuid4(),
        owner=uuid4(),
        manifest_digest="a" * 64,
        artifact_sha256="b" * 64,
    )
    assert value is session.execute.return_value.scalar_one.return_value
    assert value["snapshot_observation_generation"] == "original-generation"
    assert value["additional"] == ["preserved"]
    session.commit.assert_not_called()
