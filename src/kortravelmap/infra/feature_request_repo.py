"""T-VN-M04 범용 Feature request queue의 좁은 SECURITY DEFINER adapter.

Feature request 본문과 Map admin 승인 본문은 relation DML로 우회하지 않는다. 이
module은 procedure input/output을 typed result로 바꾸는 자리만 소유한다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, NoReturn, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.infra.feature_identity import candidate_feature_uuid
from kortravelmap.infra.feature_subtype import SubtypeDetailError, write_subtype
from kortravelmap.infra.feature_update_active_repo import _driver_constraint_identity

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FeatureRequest",
    "FeatureRequestCreated",
    "FeatureRequestExactConflict",
    "FeatureRequestError",
    "FeatureRequestStateConflict",
    "FeatureRequestValidationError",
    "approve_feature_request",
    "get_feature_request",
    "list_feature_requests",
    "reject_feature_request",
    "submit_feature_request",
]


class FeatureRequestError(RuntimeError):
    """queue procedure 결과가 repository 계약을 위반했다."""


class FeatureRequestValidationError(ValueError):
    """allow-list된 queue/approval input validation failure."""


class FeatureRequestStateConflict(ValueError):
    """이미 terminal인 request를 다시 전이하려는 충돌이다."""


@dataclass(frozen=True)
class FeatureRequest:
    request_id: UUID
    request_payload: Mapping[str, Any]
    status: str
    submitted_at: datetime
    submission_command_id: int
    resolved_at: datetime | None
    resolved_by_actor: str | None
    resolved_feature_id: str | None
    rejection_reason: str | None


@dataclass(frozen=True)
class FeatureRequestCreated:
    feature_id: str
    feature_uuid: str
    row_revision: int


@dataclass(frozen=True)
class FeatureRequestExactConflict:
    existing_feature_uuid: str
    row_revision: int


_SUBMIT_SQL: Final = """
CALL feature.submit_feature_request(
    CAST(:request_id AS uuid), CAST(:request_payload AS jsonb), CAST(:command_id AS bigint),
    NULL::text, NULL::timestamptz
)
"""
# T-VN-39: OUT이 다섯에서 넷으로 줄었다 — legacy 문자열 축(`o_feature_id text`)이
# 사라지고 uuid 하나만 남는다. PG의 CALL은 OUT까지 세어 프로시저를 찾으므로 자리표시자
# 수가 어긋나면 42883으로 **승인 전량이 실패**한다.
_APPROVE_SQL: Final = """
CALL feature.approve_feature_request_with_initial_state(
    CAST(:request_id AS uuid), CAST(:feature_payload AS jsonb), CAST(:command_id AS bigint),
    NULL::text, NULL::uuid, NULL::bigint, NULL::uuid
)
"""
_REJECT_SQL: Final = """
CALL feature.reject_feature_request(
    CAST(:request_id AS uuid), CAST(:reason AS text), CAST(:command_id AS bigint), NULL::text
)
"""
_READ_SQL: Final = """
SELECT * FROM feature.read_feature_request(CAST(:request_id AS uuid))
"""
_LIST_SQL: Final = """
SELECT * FROM feature.list_feature_requests(CAST(:status AS text), CAST(:limit AS integer))
"""
# T-VN-39 `_SHADOW_DROP`: `features.feature_uuid` 컬럼은 없다. 출력 이름은
# 호출부 계약이라 유지하고 원천만 정본 키로 옮긴다.
_EXACT_CONFLICT_FEATURE_SQL: Final = """
SELECT CAST(feature_id AS text) AS feature_uuid, row_revision
FROM feature.features
WHERE feature_id = CAST(:feature_uuid AS uuid)
"""


def _procedure_error(error: DBAPIError) -> NoReturn:
    """DB diagnostic 원문을 HTTP까지 보내지 않는 M04 closed mapper."""

    sqlstate, constraint = _driver_constraint_identity(error)
    if constraint == "ck_feature_request_pending":
        raise FeatureRequestStateConflict("Feature 요청이 이미 처리되었습니다.") from error
    if sqlstate in {"23514", "23505", "22003", "22P02"}:
        raise FeatureRequestValidationError(
            "Feature 요청 값이 올바르지 않습니다."
        ) from error
    raise FeatureRequestError(
        "Feature 요청 writer가 내부 계약을 위반했습니다."
    ) from error


async def submit_feature_request(
    session: AsyncSession,
    *,
    request_id: UUID,
    request_payload: Mapping[str, Any],
    command_id: int,
) -> tuple[str, datetime]:
    if command_id < 1:
        raise FeatureRequestError("open domain command가 필요합니다.")
    try:
        row = (
            (
                await session.execute(
                    text(_SUBMIT_SQL),
                    {
                        "request_id": str(request_id),
                        "request_payload": json.dumps(request_payload, ensure_ascii=False),
                        "command_id": command_id,
                    },
                )
            )
            .mappings()
            .one()
        )
    except DBAPIError as error:
        _procedure_error(error)
    status = row.get("o_status")
    submitted_at = row.get("o_submitted_at")
    if not isinstance(status, str) or not isinstance(submitted_at, datetime):
        raise FeatureRequestError("Feature request submission receipt가 불완전합니다.")
    return status, submitted_at


async def get_feature_request(
    session: AsyncSession, *, request_id: UUID
) -> FeatureRequest | None:
    try:
        row = (
            (await session.execute(text(_READ_SQL), {"request_id": str(request_id)}))
            .mappings()
            .one_or_none()
        )
    except DBAPIError as error:
        _procedure_error(error)
    if row is None:
        return None
    payload = row.get("request_payload")
    submitted_at = row.get("submitted_at")
    if not isinstance(payload, Mapping) or not isinstance(submitted_at, datetime):
        raise FeatureRequestError("Feature request queue read receipt가 불완전합니다.")
    raw_feature_id = row.get("resolved_feature_id")
    return FeatureRequest(
        request_id=UUID(str(row["request_id"])),
        request_payload=payload,
        status=str(row["status"]),
        submitted_at=submitted_at,
        submission_command_id=int(row["submission_command_id"]),
        resolved_at=row.get("resolved_at")
        if isinstance(row.get("resolved_at"), datetime)
        else None,
        resolved_by_actor=str(row["resolved_by_actor"])
        if row.get("resolved_by_actor") is not None
        else None,
        resolved_feature_id=str(raw_feature_id) if raw_feature_id is not None else None,
        rejection_reason=str(row["rejection_reason"])
        if row.get("rejection_reason") is not None
        else None,
    )


def _row_to_request(row: Mapping[str, Any]) -> FeatureRequest:
    payload = row.get("request_payload")
    submitted_at = row.get("submitted_at")
    if not isinstance(payload, Mapping) or not isinstance(submitted_at, datetime):
        raise FeatureRequestError("Feature request queue read receipt가 불완전합니다.")
    raw_feature_id = row.get("resolved_feature_id")
    return FeatureRequest(
        request_id=UUID(str(row["request_id"])),
        request_payload=payload,
        status=str(row["status"]),
        submitted_at=submitted_at,
        submission_command_id=int(row["submission_command_id"]),
        resolved_at=(
            row.get("resolved_at")
            if isinstance(row.get("resolved_at"), datetime)
            else None
        ),
        resolved_by_actor=(
            str(row["resolved_by_actor"])
            if row.get("resolved_by_actor") is not None
            else None
        ),
        resolved_feature_id=str(raw_feature_id) if raw_feature_id is not None else None,
        rejection_reason=(
            str(row["rejection_reason"])
            if row.get("rejection_reason") is not None
            else None
        ),
    )


async def list_feature_requests(
    session: AsyncSession, *, status: str | None, limit: int
) -> tuple[FeatureRequest, ...]:
    try:
        rows = (
            await session.execute(text(_LIST_SQL), {"status": status, "limit": limit})
        ).mappings().all()
    except DBAPIError as error:
        _procedure_error(error)
    return tuple(_row_to_request(cast(Mapping[str, Any], row)) for row in rows)


async def approve_feature_request(
    session: AsyncSession,
    *,
    request: FeatureRequest,
    category: str,
    marker_color: str,
    marker_icon: str,
    command_id: int,
) -> FeatureRequestCreated | FeatureRequestExactConflict:
    if request.status != "pending":
        raise FeatureRequestStateConflict("Feature 요청이 이미 처리되었습니다.")
    if command_id < 1:
        raise FeatureRequestValidationError("open domain command가 필요합니다.")
    payload = request.request_payload
    kind = payload.get("kind")
    name = payload.get("name")
    lon = payload.get("lon")
    lat = payload.get("lat")
    if not isinstance(kind, str) or not isinstance(name, str):
        raise FeatureRequestValidationError("승인 Feature 값이 올바르지 않습니다.")
    if not all(isinstance(value, str) for value in (category, marker_color, marker_icon)):
        raise FeatureRequestValidationError("승인 Feature 값이 올바르지 않습니다.")
    # ADR-098 결정 6: 요청 승인은 alias를 발급하지 않으므로 legacy ``f_*``를 만들
    # 이유가 없다. 사이드카 payload allow-list에 ``feature_uuid`` 키가 없고
    # ``feature_id``는 uuid 캐스팅 + UUIDv7 검사를 거친다 — 정본 키 하나만 보낸다.
    feature_uuid = candidate_feature_uuid()
    feature_payload = {
        "feature_id": feature_uuid,
        "kind": kind,
        "name": name,
        "category": category,
        "lon": lon,
        "lat": lat,
        "coord_precision_digits": 6,
        "marker_color": marker_color,
        "marker_icon": marker_icon,
    }
    try:
        row = (
            (
                await session.execute(
                    text(_APPROVE_SQL),
                    {
                        "request_id": str(request.request_id),
                        "feature_payload": json.dumps(feature_payload, ensure_ascii=False),
                        "command_id": command_id,
                    },
                )
            )
            .mappings()
            .one()
        )
    except DBAPIError as error:
        _procedure_error(error)
    outcome = row.get("o_outcome")
    if outcome == "exact_conflict":
        winner = row.get("o_existing_feature_id")
        if not isinstance(winner, UUID):
            raise FeatureRequestError("Feature request exact conflict winner가 없습니다.")
        existing = (
            (
                await session.execute(
                    text(_EXACT_CONFLICT_FEATURE_SQL),
                    {"feature_uuid": str(winner)},
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            existing is None
            # T-VN-39: 위 SQL이 정본 키를 `CAST(... AS text)`로 내보내므로 이 값은
            # **문자열**이고 `winner`는 프로시저가 준 `uuid.UUID`다. 표기를 맞추지
            # 않으면 `str != UUID`가 **항상 참**이라 exact_conflict 분기가 언제나
            # 실패한다 — 축은 같고 표기만 달랐다.
            or str(existing.get("feature_uuid")) != str(winner)
            or not isinstance(existing.get("row_revision"), int)
            or existing["row_revision"] < 1
        ):
            raise FeatureRequestError(
                "Feature request exact conflict winner receipt가 불완전합니다."
            )
        return FeatureRequestExactConflict(
            existing_feature_uuid=str(winner),
            row_revision=existing["row_revision"],
        )
    if outcome != "created":
        raise FeatureRequestError("Feature request approval writer outcome이 올바르지 않습니다.")
    # T-VN-39: `o_feature_id`가 곧 uuid다 — 두 축을 따로 받던 자리가 하나로 접힌다.
    revision = row.get("o_row_revision")
    observed_id = row.get("o_feature_id")
    if not isinstance(revision, int) or not isinstance(observed_id, UUID):
        raise FeatureRequestError("Feature request approval receipt가 불완전합니다.")
    if str(observed_id) != str(feature_uuid) or revision < 1:
        raise FeatureRequestError("Feature request approval identity receipt가 일치하지 않습니다.")
    try:
        await write_subtype(
            session,
            feature_id=feature_uuid,
            kind=kind,
            detail=None,
        )
    except SubtypeDetailError as error:
        raise FeatureRequestValidationError(
            "Feature subtype 값이 올바르지 않습니다."
        ) from error
    return FeatureRequestCreated(
        feature_id=feature_uuid,
        feature_uuid=str(observed_id),
        row_revision=revision,
    )


async def reject_feature_request(
    session: AsyncSession, *, request_id: UUID, reason: str, command_id: int
) -> None:
    if not reason.strip() or command_id < 1:
        raise FeatureRequestValidationError("거절 사유와 open domain command가 필요합니다.")
    try:
        row = (
            (
                await session.execute(
                    text(_REJECT_SQL),
                    {"request_id": str(request_id), "reason": reason, "command_id": command_id},
                )
            )
            .mappings()
            .one()
        )
    except DBAPIError as error:
        _procedure_error(error)
    if row.get("o_status") != "rejected":
        raise FeatureRequestError("Feature request rejection receipt가 올바르지 않습니다.")
