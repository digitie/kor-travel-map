"""ADR115 범위·epoch 커널. 호출자 transaction을 소유하거나 기존 writer를 활성화하지 않는다.

지원 manifest는 명시 Feature revision/source head뿐이다. claim/redirect/catalog/membership
closure 완결성이 없는 plan을 이 모듈만으로 승인하거나 production enable하면 안 된다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_REGIONS = 256
_MAX_MEMBERS = 8192
_KEY = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, order=True)
class ScopedWriteRegion:
    """주소가 아닌 provider 완전 coverage의 version/key."""

    scope_version: int
    region_key: str

    def __post_init__(self) -> None:
        if type(self.scope_version) is not int or not 1 <= self.scope_version <= 2147483647:
            raise ValueError("invalid scope version")
        if not isinstance(self.region_key, str) or not _KEY.fullmatch(self.region_key):
            raise ValueError("invalid region key")


@dataclass(frozen=True)
class ScopedWriteDependency:
    """계획 때 관측한 대상 revision. 소실/추가 phantom 전체 검증의 대체물이 아니다."""

    ordinal: int
    dependency_kind: Literal["feature", "source_head"]
    dependency_key: str
    expected_value: str

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or not 0 <= self.ordinal < _MAX_MEMBERS:
            raise ValueError("invalid manifest ordinal")
        if self.dependency_kind not in ("feature", "source_head"):
            raise ValueError("unsupported dependency kind")
        for value in (self.dependency_key, self.expected_value):
            if not isinstance(value, str) or not 1 <= len(value.encode()) <= 128:
                raise ValueError("invalid bounded dependency")
        if self.dependency_kind == "feature":
            try:
                valid_id = str(UUID(self.dependency_key)) == self.dependency_key
            except ValueError:
                valid_id = False
            if not valid_id or not re.fullmatch(r"[1-9][0-9]{0,18}", self.expected_value):
                raise ValueError("invalid feature dependency")


def _transaction(session: AsyncSession) -> None:
    if not session.in_transaction():
        raise ValueError("explicit caller transaction required")


def _digest(value: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError("invalid digest")


async def lock_scoped_feature_write_protocol(session: AsyncSession, *, exclusive: bool) -> None:
    """단일 xact gate. 공유→배타 승격은 DB가 23514로 거부한다."""
    _transaction(session)
    if type(exclusive) is not bool:
        raise ValueError("explicit protocol mode required")
    await session.execute(
        text("SELECT ops.lock_scoped_feature_write_protocol(:exclusive)"), {"exclusive": exclusive}
    )


async def claim_scoped_feature_write(
    session: AsyncSession,
    *,
    attempt_id: UUID,
    owner: UUID,
    dataset_id: int,
    idempotency_key: str,
    regions: Iterable[ScopedWriteRegion],
    input_digest: str,
    expected_members: int,
    lease_seconds: int = 180,
    exclusive_protocol: bool = False,
) -> dict[str, Any]:
    """짧은 별도 transaction으로 예약한다. 함수 자체는 commit하지 않는다."""
    _transaction(session)
    _digest(input_digest)
    if type(dataset_id) is not int or dataset_id < 1:
        raise ValueError("invalid dataset")
    if not isinstance(idempotency_key, str) or not _KEY.fullmatch(idempotency_key):
        raise ValueError("invalid idempotency key")
    if type(expected_members) is not int or not 0 <= expected_members <= _MAX_MEMBERS:
        raise ValueError("invalid manifest count")
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 900:
        raise ValueError("invalid lease")
    if (
        type(exclusive_protocol) is not bool
        or not isinstance(attempt_id, UUID)
        or not isinstance(owner, UUID)
    ):
        raise ValueError("invalid owner or mode")
    bounded = []
    for region in regions:
        if not isinstance(region, ScopedWriteRegion) or len(bounded) == _MAX_REGIONS:
            raise ValueError("invalid bounded region plan")
        bounded.append(region)
    if len(set(bounded)) != len(bounded):
        raise ValueError("duplicate region")
    result = await session.scalar(
        text("""
        SELECT ops.claim_scoped_feature_write(:attempt,:owner,:dataset,:key,
            CAST(:regions AS jsonb),:digest,:members,:lease,:exclusive)
    """),
        {
            "attempt": attempt_id,
            "owner": owner,
            "dataset": dataset_id,
            "key": idempotency_key,
            "regions": json.dumps([asdict(r) for r in sorted(bounded)]),
            "digest": input_digest,
            "members": expected_members,
            "lease": lease_seconds,
            "exclusive": exclusive_protocol,
        },
    )
    return cast("dict[str, Any]", result)


async def append_scoped_feature_write_manifest(
    session: AsyncSession,
    *,
    attempt_id: UUID,
    owner: UUID,
    members: Iterable[ScopedWriteDependency],
) -> int:
    """공식 호출당 최대 256개만 적재한다. 전체 UUID 목록을 모으지 않는다."""
    _transaction(session)
    rows = []
    for member in members:
        if not isinstance(member, ScopedWriteDependency) or len(rows) == 256:
            raise ValueError("invalid bounded manifest batch")
        rows.append(asdict(member))
    if not rows:
        raise ValueError("empty manifest batch")
    payload = json.dumps(rows, allow_nan=False)
    if len(payload.encode()) > 131072:
        raise ValueError("manifest batch byte budget exceeded")
    value = await session.scalar(
        text(
            "SELECT ops.append_scoped_feature_write_manifest"
            "(:attempt,:owner,CAST(:members AS jsonb))"
        ),
        {"attempt": attempt_id, "owner": owner, "members": payload},
    )
    assert type(value) is int
    return value


async def seal_scoped_feature_write_manifest(
    session: AsyncSession, *, attempt_id: UUID, owner: UUID
) -> str:
    _transaction(session)
    return str(
        await session.scalar(
            text("SELECT ops.seal_scoped_feature_write_manifest(:attempt,:owner)"),
            {"attempt": attempt_id, "owner": owner},
        )
    )


async def begin_scoped_feature_write(
    session: AsyncSession,
    *,
    attempt_id: UUID,
    owner: UUID,
    manifest_digest: str,
) -> dict[str, Any]:
    """적용 TX 첫 진입. 반환 뒤 실제 DML과 finish를 같은 TX에서 수행한다."""
    _transaction(session)
    _digest(manifest_digest)
    return cast(
        "dict[str, Any]",
        await session.scalar(
            text("SELECT ops.begin_scoped_feature_write(:attempt,:owner,:digest)"),
            {"attempt": attempt_id, "owner": owner, "digest": manifest_digest},
        ),
    )


async def finish_scoped_feature_write(
    session: AsyncSession,
    *,
    attempt_id: UUID,
    owner: UUID,
    result_digest: str,
) -> dict[str, Any]:
    _transaction(session)
    _digest(result_digest)
    return cast(
        "dict[str, Any]",
        await session.scalar(
            text("SELECT ops.finish_scoped_feature_write(:attempt,:owner,:digest)"),
            {"attempt": attempt_id, "owner": owner, "digest": result_digest},
        ),
    )


async def cancel_scoped_feature_write(
    session: AsyncSession, *, attempt_id: UUID, owner: UUID
) -> bool:
    _transaction(session)
    return bool(
        await session.scalar(
            text("SELECT ops.cancel_scoped_feature_write(:attempt,:owner)"),
            {"attempt": attempt_id, "owner": owner},
        )
    )
