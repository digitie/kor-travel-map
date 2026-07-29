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
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DataIntegrityViolation",
    "DataIntegrityViolationStateConflict",
    "create_data_integrity_violation",
    "get_data_integrity_violation",
    "list_data_integrity_violations",
    "set_data_integrity_violation_status",
    "sync_integrity_findings",
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
    "issue_id, provider, dataset_key, source_record_key, feature_id, "
    "violation_type, severity, message, payload, status, detected_at, "
    "last_seen_at, resolved_at"
)
_RETURN_COLUMNS_V: Final[str] = (
    "v.issue_id, v.provider, v.dataset_key, v.source_record_key, v.feature_id, "
    "v.violation_type, v.severity, v.message, v.payload, v.status, v.detected_at, "
    "v.last_seen_at, v.resolved_at"
)


@dataclass(frozen=True)
class DataIntegrityViolation:
    """``ops.data_integrity_violations`` row."""

    issue_id: str
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
    last_seen_at: datetime
    resolved_at: datetime | None


class DataIntegrityViolationStateConflict(ValueError):
    """data integrity issue가 요청한 상태 전이를 허용하지 않을 때 발생."""

    def __init__(
        self,
        *,
        issue_id: str,
        current_status: str,
        target_status: str,
    ) -> None:
        self.issue_id = issue_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            "data integrity violation "
            f"{issue_id!r}는 {target_status!r} 전이를 허용하지 않음: "
            f"status={current_status!r}"
        )


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _row_to_violation(row: Any) -> DataIntegrityViolation:
    return DataIntegrityViolation(
        issue_id=str(row.issue_id),
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
        last_seen_at=row.last_seen_at,
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
WHERE issue_id = :issue_id
"""

_SET_STATUS_SQL: Final[str] = f"""
WITH locked AS (
    SELECT issue_id, status
    FROM ops.data_integrity_violations
    WHERE issue_id = :issue_id
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
    WHERE v.issue_id = locked.issue_id
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
ORDER BY last_seen_at DESC, issue_id DESC
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
    issue_id: str,
) -> DataIntegrityViolation | None:
    """violation key로 이슈 1건 조회."""
    row = (
        await session.execute(
            text(_GET_SQL),
            {"issue_id": issue_id},
        )
    ).one_or_none()
    return _row_to_violation(row) if row is not None else None


async def set_data_integrity_violation_status(
    session: AsyncSession,
    issue_id: str,
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
                "issue_id": issue_id,
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
    existing = await get_data_integrity_violation(session, issue_id)
    if existing is None:
        return None
    raise DataIntegrityViolationStateConflict(
        issue_id=existing.issue_id,
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


_UPSERT_FINDINGS_BATCH_SQL: Final[str] = """
INSERT INTO ops.data_integrity_violations (
    provider, dataset_key, source_record_key, feature_id, violation_type,
    severity, message, payload
)
SELECT * FROM unnest(
    CAST(:providers AS text[]),
    CAST(:datasets AS text[]),
    CAST(:source_record_keys AS text[]),
    CAST(:feature_ids AS text[]),
    CAST(:violation_types AS text[]),
    CAST(:severities AS text[]),
    CAST(:messages AS text[]),
    CAST(:payloads AS jsonb[])
)
ON CONFLICT ((payload ->> 'dedupe_key'))
WHERE status IN ('open', 'acknowledged') AND payload ? 'dedupe_key'
DO UPDATE SET
    source_record_key = EXCLUDED.source_record_key,
    feature_id = EXCLUDED.feature_id,
    message = EXCLUDED.message,
    severity = EXCLUDED.severity,
    last_seen_at = statement_timestamp(),
    payload = ops.data_integrity_violations.payload
        || jsonb_strip_nulls(EXCLUDED.payload)
        || jsonb_build_object(
            'occurrence_count',
            COALESCE(
                (ops.data_integrity_violations.payload ->> 'occurrence_count')::bigint,
                1
            ) + 1
        )
RETURNING issue_id
"""



async def sync_integrity_findings(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    findings: Sequence[Mapping[str, Any]],
) -> int:
    """finding 집합을 **단일 statement로** 기록한다 (T-VN-H30A). commit은 호출자 책임.

    반환: upsert한 건수.

    왜 batch인가 — ``ops.data_integrity_violations``에는 statement 단위 트리거
    (``trg_data_integrity_violations_ops_live_revision``)가 걸려 있어 statement마다
    ``ops_live`` revision 단일 행을 갱신한다. finding 하나당 INSERT를 돌리면 그 hot row에
    배타 락을 N번 잡고 트랜잭션 끝까지 쥐게 되어, ``/admin/issues`` 쓰기를 막고 동시 run을
    직렬화하며 admin PATCH와 데드락까지 만든다. 전체를 한 statement로 접으면 트리거는
    1회만 발화한다.

    **자동 close(sweep)는 일부러 없다.** 1차 설계에는 "이번 run이 보고하지 않는 finding을
    닫는" sweep이 있었는데 적대 리뷰가 실측으로 세 가지를 재현했다.

    - ``_load()``는 provider에 따라 **배치마다** 호출된다(MOIS는 1000건 단위로 ~977회).
      배치 단위 sweep은 "이 배치에 없는 것"을 닫으므로 한 run이 자기 finding의 대부분을
      스스로 resolved 처리한다.
    - sweep이 행을 부분 unique index 밖으로 밀어내므로 다음 run의 INSERT가 충돌하지 않고
      **새 행**을 만든다 — 막으려던 단조 증가를 오히려 재생산한다.
    - ``bundles=[]``인 ``_load()``는 OpiNet 일일 스킵·MOIS 무레코드 fallback의 제어 흐름
      sentinel이라, 빈 finding 집합이 큐 전체를 닫는다.

    그래서 지금은 "닫히지 않는다"를 알려진 한계로 두고, run marker(적재 run id/시각을
    payload에 남기고 그보다 오래된 것만 닫기) 기반 재설계를 ``T-VN-H32``로 분리했다.
    """
    ordered_findings = sorted(
        findings,
        key=lambda finding: str(finding["payload"]["dedupe_key"]),
    )
    for finding in ordered_findings:
        if finding.get("provider") != provider:
            raise ValueError("finding provider가 sync 범위와 다르다.")
        if finding.get("dataset_key") != dataset_key:
            raise ValueError("finding dataset_key가 sync 범위와 다르다.")
        # batch 경로에도 같은 검증을 건다. 없으면 잘못된 severity가 DB CHECK까지 가서
        # unnest statement 전체를 실패시키고, 상위의 광범위 except가 삼켜
        # **그 run의 finding 전부**를 잃는다.
        _validate_violation(
            violation_type=str(finding["violation_type"]),
            severity=str(finding["severity"]),
            message=str(finding["message"]),
        )

    upserted = 0
    if ordered_findings:
        result = await session.execute(
            text(_UPSERT_FINDINGS_BATCH_SQL),
            {
                "providers": [f.get("provider") for f in ordered_findings],
                "datasets": [f.get("dataset_key") for f in ordered_findings],
                "source_record_keys": [
                    f.get("source_record_key") for f in ordered_findings
                ],
                "feature_ids": [f.get("feature_id") for f in ordered_findings],
                "violation_types": [f["violation_type"] for f in ordered_findings],
                "severities": [f["severity"] for f in ordered_findings],
                "messages": [f["message"] for f in ordered_findings],
                "payloads": [
                    json.dumps(f["payload"], ensure_ascii=False)
                    for f in ordered_findings
                ],
            },
        )
        upserted = len(result.scalars().all())

    return upserted
