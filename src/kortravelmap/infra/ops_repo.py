"""``kortravelmap.infra.ops_repo`` — 운영 화면용 read-only 조회.

T-207d ``/ops/*`` 라우터가 쓰는 목록/집계 쿼리다. 기존 ``jobs_repo``는 작업
lifecycle 전이를 책임지고, 이 모듈은 admin UI/운영 API가 필요한 관측용 row를
시간 역순 keyset cursor로 조회한다.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "OpsImportJob",
    "OpsImportJobEvent",
    "OpsImportJobEventPage",
    "OpsImportJobPage",
    "OpsConsistencyReport",
    "OpsConsistencyReportPage",
    "OpsIntegrityIssue",
    "OpsIntegrityIssuePage",
    "OpsIntegrityIssueCounts",
    "get_ops_import_job",
    "list_ops_import_job_events",
    "list_ops_import_jobs",
    "get_latest_consistency_report",
    "list_ops_consistency_reports",
    "list_ops_integrity_issues",
    "get_ops_integrity_issue_counts",
]

_MAX_PAGE_SIZE: Final[int] = 200


@dataclass(frozen=True)
class OpsImportJob:
    """``ops.import_jobs`` 운영 목록/상세 row."""

    job_id: str
    kind: str
    load_batch_id: str | None
    parent_job_id: str | None
    payload: dict[str, Any]
    status: str
    progress: int
    current_stage: str | None
    source_checksum: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None


@dataclass(frozen=True)
class OpsImportJobPage:
    """Keyset cursor 기반 import job 목록."""

    items: tuple[OpsImportJob, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class OpsImportJobEvent:
    """``ops.import_job_events`` 운영 event row."""

    event_id: str
    job_id: str
    provider: str | None
    dataset_key: str | None
    feature_id: str | None
    stage: str | None
    level: str
    code: str | None
    message: str
    payload: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class OpsImportJobEventPage:
    """Keyset cursor 기반 import job event 목록."""

    items: tuple[OpsImportJobEvent, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class OpsConsistencyReport:
    """``ops.feature_consistency_reports`` 운영 row."""

    report_id: str
    batch_id: str
    started_at: datetime
    finished_at: datetime | None
    severity_max: str
    cases: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass(frozen=True)
class OpsConsistencyReportPage:
    """Keyset cursor 기반 consistency report 목록."""

    items: tuple[OpsConsistencyReport, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class OpsIntegrityIssue:
    """``ops.data_integrity_violations`` 운영 issue row."""

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
    resolved_at: datetime | None


@dataclass(frozen=True)
class OpsIntegrityIssuePage:
    """Keyset cursor 기반 data integrity issue 목록."""

    items: tuple[OpsIntegrityIssue, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class OpsIntegrityIssueCounts:
    """운영 issue 집계."""

    open_total: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    by_type: dict[str, int]


def _limit(value: int) -> int:
    return max(1, min(int(value), _MAX_PAGE_SIZE))


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        value = json.loads(value)
    if not value:
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _encode_cursor(kind: str, *, at: datetime, key: str) -> str:
    raw = json.dumps(
        {"v": 1, "kind": kind, "at": at.isoformat(), "key": key},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None, *, kind: str) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
        payload = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {kind} cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid {kind} cursor")
    if payload.get("v") != 1 or payload.get("kind") != kind:
        raise ValueError(f"invalid {kind} cursor")
    try:
        at = datetime.fromisoformat(str(payload["at"]))
        key = str(payload["key"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {kind} cursor") from exc
    return at, key


_IMPORT_JOB_COLUMNS: Final[str] = (
    "job_id, kind, load_batch_id, parent_job_id, payload, status, progress, "
    "current_stage, source_checksum, error_message, created_at, started_at, "
    "finished_at, heartbeat_at"
)

_LIST_IMPORT_JOBS_SQL: Final[str] = f"""
SELECT {_IMPORT_JOB_COLUMNS}
FROM ops.import_jobs
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (CAST(:kind AS text) IS NULL OR kind = CAST(:kind AS text))
  AND (
    CAST(:load_batch_id AS uuid) IS NULL
    OR load_batch_id = CAST(:load_batch_id AS uuid)
  )
  AND (
    CAST(:parent_job_id AS uuid) IS NULL
    OR parent_job_id = CAST(:parent_job_id AS uuid)
  )
  AND (
    CAST(:cursor_created_at AS timestamptz) IS NULL
    OR (created_at, job_id) < (
        CAST(:cursor_created_at AS timestamptz),
        CAST(:cursor_job_id AS uuid)
    )
  )
ORDER BY created_at DESC, job_id DESC
LIMIT :limit
"""

_GET_IMPORT_JOB_SQL: Final[str] = f"""
SELECT {_IMPORT_JOB_COLUMNS}
FROM ops.import_jobs
WHERE job_id = CAST(:job_id AS uuid)
"""

_IMPORT_JOB_EVENT_COLUMNS: Final[str] = (
    "event_id, job_id, provider, dataset_key, feature_id, stage, level, code, "
    "message, payload, occurred_at"
)

_LIST_IMPORT_JOB_EVENTS_SQL: Final[str] = f"""
SELECT {_IMPORT_JOB_EVENT_COLUMNS}
FROM ops.import_job_events
WHERE (
    CAST(:job_id AS uuid) IS NULL
    OR job_id = CAST(:job_id AS uuid)
  )
  AND (CAST(:level AS text) IS NULL OR level = CAST(:level AS text))
  AND (CAST(:provider AS text) IS NULL OR provider = CAST(:provider AS text))
  AND (
    CAST(:dataset_key AS text) IS NULL
    OR dataset_key = CAST(:dataset_key AS text)
  )
  AND (
    CAST(:cursor_occurred_at AS timestamptz) IS NULL
    OR (occurred_at, event_id) < (
        CAST(:cursor_occurred_at AS timestamptz),
        CAST(:cursor_event_id AS uuid)
    )
  )
ORDER BY occurred_at DESC, event_id DESC
LIMIT :limit
"""

_CONSISTENCY_COLUMNS: Final[str] = (
    "report_id, batch_id, started_at, finished_at, severity_max, cases, summary"
)

_LIST_CONSISTENCY_SQL: Final[str] = f"""
SELECT {_CONSISTENCY_COLUMNS}
FROM ops.feature_consistency_reports
WHERE (
    CAST(:severity_max AS text) IS NULL
    OR severity_max = CAST(:severity_max AS text)
  )
  AND (
    CAST(:cursor_started_at AS timestamptz) IS NULL
    OR (started_at, report_id) < (
        CAST(:cursor_started_at AS timestamptz),
        CAST(:cursor_report_id AS uuid)
    )
  )
ORDER BY started_at DESC, report_id DESC
LIMIT :limit
"""

_LATEST_CONSISTENCY_SQL: Final[str] = f"""
SELECT {_CONSISTENCY_COLUMNS}
FROM ops.feature_consistency_reports
ORDER BY started_at DESC, report_id DESC
LIMIT 1
"""

_ISSUE_COLUMNS: Final[str] = (
    "issue_id, provider, dataset_key, source_record_key, feature_id, "
    "violation_type, severity, message, payload, status, detected_at, resolved_at"
)

_LIST_ISSUES_SQL: Final[str] = f"""
SELECT {_ISSUE_COLUMNS}
FROM ops.data_integrity_violations
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (CAST(:severity AS text) IS NULL OR severity = CAST(:severity AS text))
  AND (
    CAST(:violation_type AS text) IS NULL
    OR violation_type = CAST(:violation_type AS text)
  )
  AND (CAST(:provider AS text) IS NULL OR provider = CAST(:provider AS text))
  AND (CAST(:dataset_key AS text) IS NULL OR dataset_key = CAST(:dataset_key AS text))
  AND (CAST(:feature_id AS text) IS NULL OR feature_id = CAST(:feature_id AS text))
  AND (
    CAST(:q_like AS text) IS NULL
    OR message ILIKE CAST(:q_like AS text)
    OR feature_id ILIKE CAST(:q_like AS text)
    OR source_record_key ILIKE CAST(:q_like AS text)
  )
  AND (
    CAST(:bbox_min_lon AS double precision) IS NULL
    OR EXISTS (
        SELECT 1
        FROM feature.features AS f
        WHERE f.feature_id = data_integrity_violations.feature_id
          AND f.coord OPERATOR(x_extension.&&) x_extension.ST_MakeEnvelope(
              CAST(:bbox_min_lon AS double precision),
              CAST(:bbox_min_lat AS double precision),
              CAST(:bbox_max_lon AS double precision),
              CAST(:bbox_max_lat AS double precision), 4326)
    )
  )
  AND (
    CAST(:cursor_detected_at AS timestamptz) IS NULL
    OR (detected_at, issue_id) < (
        CAST(:cursor_detected_at AS timestamptz),
        CAST(:cursor_issue_id AS uuid)
    )
  )
ORDER BY detected_at DESC, issue_id DESC
LIMIT :limit
"""

_ISSUE_COUNTS_SQL: Final[str] = """
WITH base AS (
  SELECT status, severity, violation_type
  FROM ops.data_integrity_violations
)
SELECT
  COALESCE((
    SELECT jsonb_object_agg(status, n)
    FROM (SELECT status, count(*) AS n FROM base GROUP BY status) AS s
  ), '{}'::jsonb) AS by_status,
  COALESCE((
    SELECT jsonb_object_agg(severity, n)
    FROM (
      SELECT severity, count(*) AS n
      FROM base
      WHERE status IN ('open', 'acknowledged')
      GROUP BY severity
    ) AS s
  ), '{}'::jsonb) AS by_severity,
  COALESCE((
    SELECT jsonb_object_agg(violation_type, n)
    FROM (
      SELECT violation_type, count(*) AS n
      FROM base
      WHERE status IN ('open', 'acknowledged')
      GROUP BY violation_type
    ) AS s
  ), '{}'::jsonb) AS by_type,
  (
    SELECT count(*)
    FROM base
    WHERE status IN ('open', 'acknowledged')
  ) AS open_total
"""


def _row_to_import_job(row: Any) -> OpsImportJob:
    return OpsImportJob(
        job_id=str(row.job_id),
        kind=str(row.kind),
        load_batch_id=str(row.load_batch_id) if row.load_batch_id else None,
        parent_job_id=str(row.parent_job_id) if row.parent_job_id else None,
        payload=_json_dict(row.payload),
        status=str(row.status),
        progress=int(row.progress),
        current_stage=row.current_stage,
        source_checksum=row.source_checksum,
        error_message=row.error_message,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        heartbeat_at=row.heartbeat_at,
    )


def _row_to_import_job_event(row: Any) -> OpsImportJobEvent:
    return OpsImportJobEvent(
        event_id=str(row.event_id),
        job_id=str(row.job_id),
        provider=row.provider,
        dataset_key=row.dataset_key,
        feature_id=row.feature_id,
        stage=row.stage,
        level=str(row.level),
        code=row.code,
        message=str(row.message),
        payload=_json_dict(row.payload),
        occurred_at=row.occurred_at,
    )


def _row_to_consistency(row: Any) -> OpsConsistencyReport:
    return OpsConsistencyReport(
        report_id=str(row.report_id),
        batch_id=str(row.batch_id),
        started_at=row.started_at,
        finished_at=row.finished_at,
        severity_max=str(row.severity_max),
        cases=_json_list(row.cases),
        summary=_json_dict(row.summary),
    )


def _row_to_issue(row: Any) -> OpsIntegrityIssue:
    return OpsIntegrityIssue(
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
        resolved_at=row.resolved_at,
    )


async def list_ops_import_jobs(
    session: AsyncSession,
    *,
    status: str | None = None,
    kind: str | None = None,
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> OpsImportJobPage:
    """``ops.import_jobs``를 ``created_at DESC, job_id DESC`` cursor로 조회한다."""
    page_size = _limit(limit)
    cursor_created_at, cursor_job_id = _decode_cursor(cursor, kind="import_jobs")
    rows = (
        await session.execute(
            text(_LIST_IMPORT_JOBS_SQL),
            {
                "status": status,
                "kind": kind,
                "load_batch_id": load_batch_id,
                "parent_job_id": parent_job_id,
                "cursor_created_at": cursor_created_at,
                "cursor_job_id": cursor_job_id,
                "limit": page_size + 1,
            },
        )
    ).all()
    items = tuple(_row_to_import_job(row) for row in rows[:page_size])
    next_cursor = (
        _encode_cursor("import_jobs", at=items[-1].created_at, key=items[-1].job_id)
        if len(rows) > page_size and items
        else None
    )
    return OpsImportJobPage(items=items, next_cursor=next_cursor)


async def get_ops_import_job(
    session: AsyncSession,
    job_id: str,
) -> OpsImportJob | None:
    """``ops.import_jobs`` 단건 조회."""
    row = (
        await session.execute(text(_GET_IMPORT_JOB_SQL), {"job_id": job_id})
    ).one_or_none()
    return _row_to_import_job(row) if row is not None else None


async def list_ops_import_job_events(
    session: AsyncSession,
    job_id: str | None = None,
    *,
    level: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> OpsImportJobEventPage:
    """``ops.import_job_events``를 ``occurred_at DESC, event_id DESC``로 조회한다."""
    page_size = _limit(limit)
    cursor_occurred_at, cursor_event_id = _decode_cursor(
        cursor, kind="import_job_events"
    )
    rows = (
        await session.execute(
            text(_LIST_IMPORT_JOB_EVENTS_SQL),
            {
                "job_id": job_id,
                "level": level,
                "provider": provider,
                "dataset_key": dataset_key,
                "cursor_occurred_at": cursor_occurred_at,
                "cursor_event_id": cursor_event_id,
                "limit": page_size + 1,
            },
        )
    ).all()
    items = tuple(_row_to_import_job_event(row) for row in rows[:page_size])
    next_cursor = (
        _encode_cursor(
            "import_job_events",
            at=items[-1].occurred_at,
            key=items[-1].event_id,
        )
        if len(rows) > page_size and items
        else None
    )
    return OpsImportJobEventPage(items=items, next_cursor=next_cursor)


async def list_ops_consistency_reports(
    session: AsyncSession,
    *,
    severity_max: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> OpsConsistencyReportPage:
    """최근 consistency report 목록을 조회한다."""
    page_size = _limit(limit)
    cursor_started_at, cursor_report_id = _decode_cursor(
        cursor, kind="consistency_reports"
    )
    rows = (
        await session.execute(
            text(_LIST_CONSISTENCY_SQL),
            {
                "severity_max": severity_max,
                "cursor_started_at": cursor_started_at,
                "cursor_report_id": cursor_report_id,
                "limit": page_size + 1,
            },
        )
    ).all()
    items = tuple(_row_to_consistency(row) for row in rows[:page_size])
    next_cursor = (
        _encode_cursor(
            "consistency_reports", at=items[-1].started_at, key=items[-1].report_id
        )
        if len(rows) > page_size and items
        else None
    )
    return OpsConsistencyReportPage(items=items, next_cursor=next_cursor)


async def get_latest_consistency_report(
    session: AsyncSession,
) -> OpsConsistencyReport | None:
    """가장 최근 consistency report 1건 조회."""
    row = (await session.execute(text(_LATEST_CONSISTENCY_SQL))).one_or_none()
    return _row_to_consistency(row) if row is not None else None


async def list_ops_integrity_issues(
    session: AsyncSession,
    *,
    status: str | None = "open",
    severity: str | None = None,
    violation_type: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    feature_id: str | None = None,
    q: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> OpsIntegrityIssuePage:
    """``ops.data_integrity_violations`` issue 목록을 조회한다.

    ``q``는 message/feature_id/source_record_key의 부분일치(ILIKE),
    ``bbox``는 연결 feature 좌표가 ``(min_lon, min_lat, max_lon, max_lat)``
    안에 드는 이슈만 남긴다(ADR-012: STORED ``coord`` 4326 GiST ``&&``, feature_id가
    없는 이슈는 제외). 둘 다 ``None``이면 필터하지 않는다.
    """
    page_size = _limit(limit)
    cursor_detected_at, cursor_issue_id = _decode_cursor(
        cursor, kind="integrity_issues"
    )
    q_like = f"%{q}%" if q else None
    bbox_min_lon, bbox_min_lat, bbox_max_lon, bbox_max_lat = (
        bbox if bbox is not None else (None, None, None, None)
    )
    rows = (
        await session.execute(
            text(_LIST_ISSUES_SQL),
            {
                "status": status,
                "severity": severity,
                "violation_type": violation_type,
                "provider": provider,
                "dataset_key": dataset_key,
                "feature_id": feature_id,
                "q_like": q_like,
                "bbox_min_lon": bbox_min_lon,
                "bbox_min_lat": bbox_min_lat,
                "bbox_max_lon": bbox_max_lon,
                "bbox_max_lat": bbox_max_lat,
                "cursor_detected_at": cursor_detected_at,
                "cursor_issue_id": cursor_issue_id,
                "limit": page_size + 1,
            },
        )
    ).all()
    items = tuple(_row_to_issue(row) for row in rows[:page_size])
    next_cursor = (
        _encode_cursor(
            "integrity_issues", at=items[-1].detected_at, key=items[-1].issue_id
        )
        if len(rows) > page_size and items
        else None
    )
    return OpsIntegrityIssuePage(items=items, next_cursor=next_cursor)


async def get_ops_integrity_issue_counts(
    session: AsyncSession,
) -> OpsIntegrityIssueCounts:
    """열린 운영 issue 집계."""
    row = (await session.execute(text(_ISSUE_COUNTS_SQL))).one()
    by_status = {str(k): int(v) for k, v in _json_dict(row.by_status).items()}
    by_severity = {str(k): int(v) for k, v in _json_dict(row.by_severity).items()}
    by_type = {str(k): int(v) for k, v in _json_dict(row.by_type).items()}
    return OpsIntegrityIssueCounts(
        open_total=int(row.open_total),
        by_status=by_status,
        by_severity=by_severity,
        by_type=by_type,
    )
