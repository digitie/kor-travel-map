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

from kortravelmap.core import make_feature_id
from kortravelmap.infra.feature_identity import candidate_feature_uuid
from kortravelmap.infra.feature_subtype import SubtypeDetailError, write_subtype

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
_APPROVE_SQL: Final = """
CALL feature.approve_feature_request_with_initial_state(
    CAST(:request_id AS uuid), CAST(:feature_payload AS jsonb), CAST(:command_id AS bigint),
    NULL::text, NULL::text, NULL::uuid, NULL::bigint, NULL::uuid
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
_EXACT_CONFLICT_FEATURE_SQL: Final = """
SELECT feature_uuid, row_revision
FROM feature.features
WHERE feature_uuid = CAST(:feature_uuid AS uuid)
"""


def _procedure_error(error: DBAPIError) -> NoReturn:
    """DB diagnostic 원문을 HTTP까지 보내지 않는 M04 closed mapper."""

    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    constraint = getattr(
        getattr(getattr(error, "orig", None), "diag", None), "constraint_name", None
    )
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
    feature_uuid = candidate_feature_uuid()
    feature_id = make_feature_id(
        bjd_code=None,
        kind=kind,
        category="manual_request_v1",
        source_type="user_request",
        source_natural_key=f"feature-request::{request.request_id}",
        content_hash=None,
    )
    feature_payload = {
        "feature_id": feature_id,
        "feature_uuid": feature_uuid,
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
        winner = row.get("o_existing_feature_uuid")
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
            or existing.get("feature_uuid") != winner
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
    observed_uuid = row.get("o_feature_uuid")
    revision = row.get("o_row_revision")
    observed_id = row.get("o_feature_id")
    if (
        not isinstance(observed_uuid, UUID)
        or not isinstance(revision, int)
        or not isinstance(observed_id, str)
    ):
        raise FeatureRequestError("Feature request approval receipt가 불완전합니다.")
    if str(observed_uuid) != str(feature_uuid) or observed_id != feature_id or revision < 1:
        raise FeatureRequestError("Feature request approval identity receipt가 일치하지 않습니다.")
    try:
        await write_subtype(
            session,
            feature_id=feature_id,
            feature_uuid=str(observed_uuid),
            kind=kind,
            detail=None,
        )
    except SubtypeDetailError as error:
        raise FeatureRequestValidationError(
            "Feature subtype 값이 올바르지 않습니다."
        ) from error
    return FeatureRequestCreated(
        feature_id=feature_id,
        feature_uuid=str(observed_uuid),
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
