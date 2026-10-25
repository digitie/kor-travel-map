"""호출자 TX 안의 snapshot 복구 SD gateway. SDK 호출·commit·실행 권위 추측은 없다."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from kortravelmap.infra.provider_snapshot_artifact import (
    DecodedSnapshotArtifact,
    SnapshotArtifactPins,
    decode_provider_snapshot_artifact,
)
from kortravelmap.infra.provider_snapshot_result import (
    SnapshotApplyResult,
    decode_snapshot_apply_result,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_STATUSES = frozenset({"prepared", "applied", "postprocessed", "child_sealed"})
_JOB_STATUSES = frozenset({"queued", "running", "done", "failed", "cancelled"})


class SnapshotRecoveryCorruption(ValueError):
    """존재한 입력/결과가 손상됐다. 부재나 재적재 가능 상태로 바꾸지 않는다."""


@dataclass(frozen=True)
class SnapshotMember:
    """정본 root/child/member 식별자. 이 값만으로 DB 실행 권한이 생기지 않는다."""

    root_id: UUID
    child_id: UUID
    member_id: UUID


@dataclass(frozen=True)
class SnapshotExecutorToken:
    """SD가 돌려준 현재 token 전달값. DB가 매 명령에서 fence를 다시 판정한다."""

    snapshot_id: UUID
    generation: int
    fence: UUID


@dataclass(frozen=True)
class SnapshotRegistration:
    """중복 등록은 token을 반환하지 않는다. 복구 read/typed claim을 따로 수행한다."""

    snapshot_id: UUID
    created: bool
    token: SnapshotExecutorToken | None


@dataclass(frozen=True)
class SnapshotExecutorLease:
    token: SnapshotExecutorToken
    expires_at: datetime
    status: str


@dataclass(frozen=True)
class SnapshotKernelBinding:
    """기존 정본 attempt의 읽기 관측. 새 owner/fence 발급이나 lease 갱신은 아니다."""

    attempt_id: UUID
    owner: UUID
    manifest_digest: str
    status: str
    input_digest: str
    lease_expires_at: datetime


@dataclass(frozen=True)
class RecoveredProviderSnapshot:
    """원 입력·원 결과의 관측값. nonce/collector 완료/재실행 허가를 뜻하지 않는다."""

    snapshot_id: UUID
    artifact: DecodedSnapshotArtifact
    artifact_payload: bytes
    artifact_sha256: str
    observation_context: bytes
    context_sha256: str
    status: str
    applied_result: SnapshotApplyResult | None
    applied_result_bytes: bytes | None
    postprocess_receipt: bytes | None
    lease_expires_at: datetime
    root_status: str
    child_status: str
    cancellation_present: bool
    kernel_binding: SnapshotKernelBinding | None


@dataclass(frozen=True)
class SnapshotMemberSeal:
    observed_at: datetime
    replayed: bool


def _uuid(value: Any) -> UUID:
    if type(value) is not UUID:
        raise SnapshotRecoveryCorruption("canonical UUID required")
    return value


def _digest(value: Any) -> str:
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise SnapshotRecoveryCorruption("exact SHA256 required")
    return value


def _bytes(value: Any, limit: int) -> bytes:
    if type(value) is not bytes or not 1 <= len(value) <= limit:
        raise SnapshotRecoveryCorruption("bounded nonempty bytes required")
    return value


def _clock(value: Any) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotRecoveryCorruption("aware database clock required")
    return value


def _status(value: Any) -> str:
    if type(value) is not str or value not in _STATUSES:
        raise SnapshotRecoveryCorruption("unknown snapshot status")
    return value


def _token_params(token: SnapshotExecutorToken) -> dict[str, Any]:
    if type(token) is not SnapshotExecutorToken or type(token.generation) is not int:
        raise SnapshotRecoveryCorruption("exact executor token required")
    if not 1 <= token.generation <= 2**63 - 1:
        raise SnapshotRecoveryCorruption("executor generation outside bigint")
    return {
        "snapshot": _uuid(token.snapshot_id),
        "generation": token.generation,
        "fence": _uuid(token.fence),
    }


def _member_params(member: SnapshotMember) -> dict[str, Any]:
    if type(member) is not SnapshotMember:
        raise SnapshotRecoveryCorruption("canonical member required")
    return {
        "root": _uuid(member.root_id),
        "child": _uuid(member.child_id),
        "member": _uuid(member.member_id),
    }


def _transaction(session: AsyncSession) -> None:
    # SQLAlchemy autobegin에 transaction 소유권을 맡기지 않는다.
    if not session.in_transaction():
        raise RuntimeError("snapshot gateway requires a caller-owned transaction")


def _lease_seconds(value: int) -> int:
    if type(value) is not int or not 5 <= value <= 300:
        raise ValueError("snapshot lease must be 5..300 seconds")
    return value


def _checked_hash(raw: Any, sha: Any, limit: int) -> bytes:
    checked = _bytes(raw, limit)
    if hashlib.sha256(checked).hexdigest() != _digest(sha):
        raise SnapshotRecoveryCorruption("stored bytes do not match their SHA256")
    return checked


def _kernel_binding(row: Any) -> SnapshotKernelBinding | None:
    keys = (
        "attempt_id",
        "attempt_owner",
        "manifest_digest",
        "kernel_status",
        "kernel_input_digest",
        "kernel_lease_expires_at",
    )
    values = tuple(row[key] for key in keys)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise SnapshotRecoveryCorruption("partial kernel binding is forbidden")
    if type(row["kernel_status"]) is not str or row["kernel_status"] not in {
        "preparing",
        "ready",
        "applying",
        "completed",
        "cancelled",
    }:
        raise SnapshotRecoveryCorruption("unknown kernel status")
    return SnapshotKernelBinding(
        _uuid(row["attempt_id"]),
        _uuid(row["attempt_owner"]),
        _digest(row["manifest_digest"]),
        row["kernel_status"],
        _digest(row["kernel_input_digest"]),
        _clock(row["kernel_lease_expires_at"]),
    )


async def read_provider_snapshot_for_member(
    session: AsyncSession,
    member: SnapshotMember,
    *,
    expected_pins: SnapshotArtifactPins,
) -> RecoveredProviderSnapshot | None:
    """최초 SDK 호출 전 읽는다. None만 미등록이며 손상은 예외로 닫는다."""
    _transaction(session)
    row = (
        (
            await session.execute(
                text("SELECT * FROM ops.read_provider_snapshot_for_member(:root,:child,:member)"),
                _member_params(member),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    # SD의 동일 statement snapshot을 그대로 해석한다. 별도 재조회로 상태를 섞지 않는다.
    raw = _checked_hash(row["artifact_payload"], row["artifact_sha256"], 1_048_576)
    artifact = decode_provider_snapshot_artifact(raw, expected_pins=expected_pins)
    if _digest(row["native_input_digest"]) != artifact.native_input_digest:
        raise SnapshotRecoveryCorruption("stored native digest differs from canonical input")
    context = _checked_hash(row["observation_context"], row["context_sha256"], 8192)
    status = _status(row["snapshot_status"])
    result_raw = row["applied_result"]
    receipt = row["postprocess_receipt"]
    if (status == "prepared") != (result_raw is None):
        raise SnapshotRecoveryCorruption("snapshot status and saved result disagree")
    if (status in {"prepared", "applied"}) != (receipt is None):
        raise SnapshotRecoveryCorruption("snapshot status and postprocess receipt disagree")
    result = None if result_raw is None else decode_snapshot_apply_result(result_raw)
    if receipt is not None:
        receipt = _bytes(receipt, 4096)
    binding = _kernel_binding(row)
    if status != "prepared" and (binding is None or binding.status != "completed"):
        raise SnapshotRecoveryCorruption("saved apply result requires its completed kernel attempt")
    root_status, child_status = row["root_status"], row["child_status"]
    if (
        type(root_status) is not str
        or root_status not in _JOB_STATUSES
        or type(child_status) is not str
        or child_status not in _JOB_STATUSES
        or type(row["cancellation_present"]) is not bool
        or ((status == "child_sealed") != (child_status == "done"))
    ):
        raise SnapshotRecoveryCorruption("invalid member state observation")
    return RecoveredProviderSnapshot(
        snapshot_id=_uuid(row["snapshot_id"]),
        artifact=artifact,
        artifact_payload=raw,
        artifact_sha256=_digest(row["artifact_sha256"]),
        observation_context=context,
        context_sha256=_digest(row["context_sha256"]),
        status=status,
        applied_result=result,
        applied_result_bytes=result_raw,
        postprocess_receipt=receipt,
        lease_expires_at=_clock(row["lease_expires_at"]),
        root_status=root_status,
        child_status=child_status,
        cancellation_present=row["cancellation_present"],
        kernel_binding=binding,
    )


async def register_provider_snapshot_artifact(
    session: AsyncSession,
    member: SnapshotMember,
    *,
    artifact_payload: bytes,
    observation_context: bytes,
    expected_pins: SnapshotArtifactPins,
    lease_seconds: int,
) -> SnapshotRegistration:
    """정본 입력을 등록한다. 관측 context의 의미 검증은 Dagster 계층 책임이다."""
    _transaction(session)
    artifact = decode_provider_snapshot_artifact(artifact_payload, expected_pins=expected_pins)
    params = _member_params(member)
    params.update(
        payload=artifact_payload,
        context=_bytes(observation_context, 8192),
        native=artifact.native_input_digest,
        seconds=_lease_seconds(lease_seconds),
    )
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM ops.register_provider_snapshot_artifact("
                    ":root,:child,:member,:payload,:context,:native,:seconds)"
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    snapshot_id = _uuid(row["snapshot_id"])
    if type(row["created"]) is not bool:
        raise SnapshotRecoveryCorruption("registration creation flag required")
    if not row["created"]:
        if row["generation"] is not None or row["fence"] is not None:
            raise SnapshotRecoveryCorruption("duplicate registration must not grant a token")
        return SnapshotRegistration(snapshot_id, False, None)
    if type(row["generation"]) is not int or row["generation"] != 1:
        raise SnapshotRecoveryCorruption("initial generation must be exactly one")
    token = SnapshotExecutorToken(snapshot_id, 1, _uuid(row["fence"]))
    return SnapshotRegistration(snapshot_id, True, token)


async def claim_provider_snapshot_executor(
    session: AsyncSession,
    snapshot_id: UUID,
    *,
    artifact_sha256: str,
    context_sha256: str,
    lease_seconds: int,
    previous: SnapshotExecutorToken | None = None,
) -> SnapshotExecutorLease:
    """회수/갱신 판정은 SD 소유다. client clock으로 lease 유효성을 추측하지 않는다."""
    _transaction(session)
    params: dict[str, Any] = {
        "snapshot": _uuid(snapshot_id),
        "artifact": _digest(artifact_sha256),
        "context": _digest(context_sha256),
        "seconds": _lease_seconds(lease_seconds),
        "generation": None,
        "fence": None,
    }
    if previous is not None:
        old = _token_params(previous)
        if old["snapshot"] != snapshot_id:
            raise ValueError("previous token belongs to another snapshot")
        params.update(generation=old["generation"], fence=old["fence"])
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM ops.claim_provider_snapshot_executor("
                    ":snapshot,:artifact,:context,:seconds,:generation,:fence)"
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    token = SnapshotExecutorToken(snapshot_id, row["generation"], _uuid(row["fence"]))
    _token_params(token)
    return SnapshotExecutorLease(
        token, _clock(row["lease_expires_at"]), _status(row["snapshot_status"])
    )


async def bind_provider_snapshot_plan(
    session: AsyncSession,
    token: SnapshotExecutorToken,
    *,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
    kernel_input_digest: str,
) -> None:
    _transaction(session)
    params = _token_params(token)
    params.update(
        attempt=_uuid(attempt_id),
        owner=_uuid(owner),
        manifest=_digest(manifest_digest),
        kernel_input=_digest(kernel_input_digest),
    )
    await session.execute(
        text(
            "SELECT ops.bind_provider_snapshot_plan("
            ":snapshot,:generation,:fence,:attempt,:owner,:manifest,:kernel_input)"
        ),
        params,
    )


async def begin_provider_snapshot_apply(
    session: AsyncSession,
    token: SnapshotExecutorToken,
    *,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
    artifact_sha256: str,
) -> None:
    """원 입력 SHA를 받는7인자 SD를 호출한다. TX 시작·commit은 하지 않는다."""
    _transaction(session)
    params = _token_params(token)
    params.update(
        attempt=_uuid(attempt_id),
        owner=_uuid(owner),
        manifest=_digest(manifest_digest),
        artifact=_digest(artifact_sha256),
    )
    await session.execute(
        text(
            "SELECT ops.begin_provider_snapshot_apply("
            ":snapshot,:generation,:fence,:attempt,:owner,:manifest,:artifact)"
        ),
        params,
    )


async def finish_provider_snapshot_apply(
    session: AsyncSession,
    token: SnapshotExecutorToken,
    *,
    original_result: bytes,
) -> None:
    """원래 canonical 결과만 저장한다. commit 응답 유실 뒤 DML을 재실행하지 않는다."""
    _transaction(session)
    decode_snapshot_apply_result(original_result)
    params = _token_params(token)
    params["result"] = original_result
    await session.execute(
        text("SELECT ops.finish_provider_snapshot_apply(:snapshot,:generation,:fence,:result)"),
        params,
    )


async def seal_provider_snapshot_member(
    session: AsyncSession,
    token: SnapshotExecutorToken,
    *,
    artifact_sha256: str,
    context_sha256: str,
    result_sha256: str,
    postprocess_sha256: str,
) -> SnapshotMemberSeal:
    _transaction(session)
    params = _token_params(token)
    params.update(
        artifact=_digest(artifact_sha256),
        context=_digest(context_sha256),
        result=_digest(result_sha256),
        postprocess=_digest(postprocess_sha256),
    )
    row = (
        (
            await session.execute(
                text(
                    "CALL ops.seal_provider_snapshot_member("
                    ":snapshot,:artifact,:context,:generation,:fence,:result,:postprocess,NULL,NULL)"
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    if type(row["o_replayed"]) is not bool:
        raise SnapshotRecoveryCorruption("seal replay flag required")
    return SnapshotMemberSeal(_clock(row["o_observed_at"]), row["o_replayed"])
