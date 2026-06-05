"""``ops.data_integrity_violations`` repository (ADR-045 T-205c).

정합성 위반/주소 매칭 이슈/미디어 실패 같은 운영 검토 항목을 "이슈 1건 = 1행"으로
저장한다. 배치 집계 테이블인 ``feature_consistency_reports``와 달리, 이 테이블은
admin UI에서 acknowledge/resolve/ignore할 수 있는 큐다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DataIntegrityViolation",
    "DataIntegrityViolationStateConflict",
    "create_data_integrity_violation",
    "get_data_integrity_violation",
    "list_data_integrity_violations",
    "set_data_integrity_violation_status",
]

_SEVERITIES: Final[frozenset[str]] = frozenset(
    {"info", "warning", "error", "critical"}
)
_STATUSES: Final[frozenset[str]] = frozenset(
    {"open", "acknowledged", "resolved", "ignored"}
)
_RESOLVED_STATUSES: Final[frozenset[str]] = frozenset({"resolved", "ignored"})
_MAX_LIST_LIMIT: Final[int] = 500

_RETURN_COLUMNS: Final[str] = (
    "violation_key, provider, dataset_key, source_record_key, feature_id, "
    "violation_type, severity, message, payload, status, detected_at, resolved_at"
)
_RETURN_COLUMNS_V: Final[str] = (
    "v.violation_key, v.provider, v.dataset_key, v.source_record_key, v.feature_id, "
    "v.violation_type, v.severity, v.message, v.payload, v.status, v.detected_at, "
    "v.resolved_at"
)


@dataclass(frozen=True)
class DataIntegrityViolation:
    """``ops.data_integrity_violations`` row."""

    violation_key: str
    provider: str | None
    dataset_key: str | None
    source_record_key: str | None
    feature_id: str | None
    violation_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    status: str
    detected_at: datetime
    resolved_at: datetime | None


class DataIntegrityViolationStateConflict(ValueError):
    """data integrity issue가 요청한 상태 전이를 허용하지 않을 때 발생."""

    def __init__(
        self,
        *,
        violation_key: str,
        current_status: str,
        target_status: str,
    ) -> None:
        self.violation_key = violation_key
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            "data integrity violation "
            f"{violation_key!r}는 {target_status!r} 전이를 허용하지 않음: "
            f"status={current_status!r}"
        )


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _row_to_violation(row: Any) -> DataIntegrityViolation:
    return DataIntegrityViolation(
        violation_key=str(row.violation_key),
        provider=row.provider,
        dataset_key=row.dataset_key,
        source_record_key=row.source_record_key,
        feature_id=row.feature_id,
        violation_type=str(row.violation_type),
        severity=str(row.severity),
        message=str(row.message),
        payload=_json_dict(row.payload),
        status=str(row.status),
        detected_at=row.detected_at,
        resolved_at=row.resolved_at,
    )


def _validate_violation(
    *,
    violation_type: str,
    severity: str,
    message: str,
) -> None:
    if not violation_type:
        raise ValueError("violation_type must be non-empty")
    if severity not in _SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(_SEVERITIES)}")
    if not message:
        raise ValueError("message must be non-empty")


_INSERT_SQL: Final[str] = f"""
INSERT INTO ops.data_integrity_violations (
    provider, dataset_key, source_record_key, feature_id, violation_type,
    severity, message, payload
) VALUES (
    :provider, :dataset_key, :source_record_key, :feature_id, :violation_type,
    :severity, :message, CAST(:payload AS jsonb)
)
RETURNING {_RETURN_COLUMNS}
"""

_GET_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.data_integrity_violations
WHERE violation_key = :violation_key
"""

_SET_STATUS_SQL: Final[str] = f"""
WITH locked AS (
    SELECT violation_key, status
    FROM ops.data_integrity_violations
    WHERE violation_key = :violation_key
    FOR UPDATE
),
updated AS (
    UPDATE ops.data_integrity_violations AS v
    SET status = :status,
        resolved_at = CASE
            WHEN locked.status = :status THEN v.resolved_at
            WHEN :status = ANY(CAST(:resolved_statuses AS text[])) THEN now()
            ELSE NULL
        END,
        payload = CASE
            WHEN CAST(:resolution_payload AS jsonb) = '{{}}'::jsonb THEN v.payload
            ELSE v.payload || jsonb_build_object(
                'resolution',
                CAST(:resolution_payload AS jsonb)
            )
        END
    FROM locked
    WHERE v.violation_key = locked.violation_key
      AND (
        locked.status = :status
        OR locked.status <> ALL(CAST(:resolved_statuses AS text[]))
      )
    RETURNING {_RETURN_COLUMNS_V}
)
SELECT {_RETURN_COLUMNS}
FROM updated
"""

_LIST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.data_integrity_violations
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (CAST(:severity AS text) IS NULL OR severity = CAST(:severity AS text))
  AND (CAST(:violation_type AS text) IS NULL
       OR violation_type = CAST(:violation_type AS text))
  AND (CAST(:feature_id AS text) IS NULL OR feature_id = CAST(:feature_id AS text))
  AND (CAST(:provider AS text) IS NULL OR provider = CAST(:provider AS text))
  AND (CAST(:dataset_key AS text) IS NULL OR dataset_key = CAST(:dataset_key AS text))
ORDER BY detected_at DESC, violation_key DESC
LIMIT :limit
"""


async def create_data_integrity_violation(
    session: AsyncSession,
    *,
    violation_type: str,
    severity: str,
    message: str,
    provider: str | None = None,
    dataset_key: str | None = None,
    source_record_key: str | None = None,
    feature_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> DataIntegrityViolation:
    """정합성/운영 이슈 1건을 생성한다. commit은 호출자 책임."""
    _validate_violation(
        violation_type=violation_type,
        severity=severity,
        message=message,
    )
    row = (
        await session.execute(
            text(_INSERT_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_record_key": source_record_key,
                "feature_id": feature_id,
                "violation_type": violation_type,
                "severity": severity,
                "message": message,
                "payload": json.dumps(
                    dict(payload) if payload else {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )
    ).one()
    return _row_to_violation(row)


async def get_data_integrity_violation(
    session: AsyncSession,
    violation_key: str,
) -> DataIntegrityViolation | None:
    """violation key로 이슈 1건 조회."""
    row = (
        await session.execute(
            text(_GET_SQL),
            {"violation_key": violation_key},
        )
    ).one_or_none()
    return _row_to_violation(row) if row is not None else None


async def set_data_integrity_violation_status(
    session: AsyncSession,
    violation_key: str,
    *,
    status: str,
    resolution_payload: Mapping[str, Any] | None = None,
) -> DataIntegrityViolation | None:
    """이슈 상태를 변경한다. ``resolved``/``ignored``는 ``resolved_at``을 찍는다."""
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {sorted(_STATUSES)}")
    row = (
        await session.execute(
            text(_SET_STATUS_SQL),
            {
                "violation_key": violation_key,
                "status": status,
                "resolved_statuses": list(_RESOLVED_STATUSES),
                "resolution_payload": json.dumps(
                    dict(resolution_payload) if resolution_payload else {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )
    ).one_or_none()
    if row is not None:
        return _row_to_violation(row)
    existing = await get_data_integrity_violation(session, violation_key)
    if existing is None:
        return None
    raise DataIntegrityViolationStateConflict(
        violation_key=existing.violation_key,
        current_status=existing.status,
        target_status=status,
    )


async def list_data_integrity_violations(
    session: AsyncSession,
    *,
    status: str | None = None,
    severity: str | None = None,
    violation_type: str | None = None,
    feature_id: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    limit: int = 200,
) -> tuple[DataIntegrityViolation, ...]:
    """운영 이슈 목록 조회."""
    rows = (
        await session.execute(
            text(_LIST_SQL),
            {
                "status": status,
                "severity": severity,
                "violation_type": violation_type,
                "feature_id": feature_id,
                "provider": provider,
                "dataset_key": dataset_key,
                "limit": max(1, min(limit, _MAX_LIST_LIMIT)),
            },
        )
    ).all()
    return tuple(_row_to_violation(row) for row in rows)
