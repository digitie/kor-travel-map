"""``krtour.map.infra.log_repo`` — 운영 로그 surface 적재/조회 (T-212c).

운영 화면이 보여줄 두 로그 stream을 ``ops`` schema에 기록하고 시간 역순 keyset
cursor로 조회한다.

- ``ops.system_log`` — 적재/지오코딩/오프라인 업로드/admin 동작의 구조화 로그
  (``level`` + ``source`` + ``event`` + ``message`` + JSONB ``detail``).
- ``ops.api_call_log`` — opt-in API 호출 로그(메서드/경로/상태/지연).

``ops_repo``의 base64 urlsafe JSON cursor(``{v, kind, at, key}``)와 ``LIMIT
page_size+1`` keyset 패턴을 그대로 따른다. INSERT는 commit하지 않는다 — commit은
호출자(미들웨어/라우터) 책임이다(ADR-004 raw SQL).
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
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SystemLogRow",
    "SystemLogPage",
    "ApiCallLogRow",
    "ApiCallLogPage",
    "LOG_LEVELS",
    "record_system_log",
    "record_api_call",
    "list_system_logs",
    "list_api_call_logs",
]

LOG_LEVELS: Final[frozenset[str]] = frozenset(
    {"debug", "info", "warning", "error", "critical"}
)

_MAX_PAGE_SIZE: Final[int] = 200


@dataclass(frozen=True)
class SystemLogRow:
    """``ops.system_log`` row."""

    system_log_id: str
    level: str
    source: str
    event: str
    message: str
    detail: dict[str, Any]
    request_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class SystemLogPage:
    """Keyset cursor 기반 system log 목록."""

    items: tuple[SystemLogRow, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class ApiCallLogRow:
    """``ops.api_call_log`` row."""

    api_call_log_id: str
    method: str
    path: str
    status_code: int
    duration_ms: int
    request_id: str | None
    error_code: str | None
    created_at: datetime


@dataclass(frozen=True)
class ApiCallLogPage:
    """Keyset cursor 기반 api call log 목록."""

    items: tuple[ApiCallLogRow, ...]
    next_cursor: str | None


def _limit(value: int) -> int:
    return max(1, min(int(value), _MAX_PAGE_SIZE))


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _encode_cursor(kind: str, *, at: datetime, key: str) -> str:
    raw = json.dumps(
        {"v": 1, "kind": kind, "at": at.isoformat(), "key": key},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None, *, kind: str
) -> tuple[datetime | None, str | None]:
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


_SYSTEM_LOG_COLUMNS: Final[str] = (
    "system_log_id, level, source, event, message, detail, request_id, created_at"
)

_INSERT_SYSTEM_LOG_SQL: Final[str] = f"""
INSERT INTO ops.system_log (level, source, event, message, detail, request_id)
VALUES (
    :level, :source, :event, :message, CAST(:detail AS jsonb), :request_id
)
RETURNING {_SYSTEM_LOG_COLUMNS}
"""

_LIST_SYSTEM_LOGS_SQL: Final[str] = f"""
SELECT {_SYSTEM_LOG_COLUMNS}
FROM ops.system_log
WHERE (CAST(:level AS text) IS NULL OR level = CAST(:level AS text))
  AND (CAST(:source AS text) IS NULL OR source = CAST(:source AS text))
  AND (CAST(:q_like AS text) IS NULL OR message ILIKE CAST(:q_like AS text))
  AND (
    CAST(:cursor_created_at AS timestamptz) IS NULL
    OR (created_at, system_log_id) < (
        CAST(:cursor_created_at AS timestamptz),
        CAST(:cursor_key AS uuid)
    )
  )
ORDER BY created_at DESC, system_log_id DESC
LIMIT :limit
"""

_API_CALL_LOG_COLUMNS: Final[str] = (
    "api_call_log_id, method, path, status_code, duration_ms, request_id, "
    "error_code, created_at"
)

_INSERT_API_CALL_LOG_SQL: Final[str] = f"""
INSERT INTO ops.api_call_log (
    method, path, status_code, duration_ms, request_id, error_code
) VALUES (
    :method, :path, :status_code, :duration_ms, :request_id, :error_code
)
RETURNING {_API_CALL_LOG_COLUMNS}
"""

_LIST_API_CALL_LOGS_SQL: Final[str] = f"""
SELECT {_API_CALL_LOG_COLUMNS}
FROM ops.api_call_log
WHERE (CAST(:method AS text) IS NULL OR method = CAST(:method AS text))
  AND (
    CAST(:min_status AS integer) IS NULL
    OR status_code >= CAST(:min_status AS integer)
  )
  AND (CAST(:path_like AS text) IS NULL OR path ILIKE CAST(:path_like AS text))
  AND (
    CAST(:cursor_created_at AS timestamptz) IS NULL
    OR (created_at, api_call_log_id) < (
        CAST(:cursor_created_at AS timestamptz),
        CAST(:cursor_key AS uuid)
    )
  )
ORDER BY created_at DESC, api_call_log_id DESC
LIMIT :limit
"""


def _row_to_system_log(row: Any) -> SystemLogRow:
    return SystemLogRow(
        system_log_id=str(row.system_log_id),
        level=str(row.level),
        source=str(row.source),
        event=str(row.event),
        message=str(row.message),
        detail=_json_dict(row.detail),
        request_id=row.request_id,
        created_at=row.created_at,
    )


def _row_to_api_call_log(row: Any) -> ApiCallLogRow:
    return ApiCallLogRow(
        api_call_log_id=str(row.api_call_log_id),
        method=str(row.method),
        path=str(row.path),
        status_code=int(row.status_code),
        duration_ms=int(row.duration_ms),
        request_id=row.request_id,
        error_code=row.error_code,
        created_at=row.created_at,
    )


async def record_system_log(
    session: AsyncSession,
    *,
    level: str,
    source: str,
    event: str,
    message: str,
    detail: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> SystemLogRow:
    """운영 system log 1건을 기록한다. commit은 호출자 책임."""
    if level not in LOG_LEVELS:
        raise ValueError(f"level must be one of {sorted(LOG_LEVELS)}")
    row = (
        await session.execute(
            text(_INSERT_SYSTEM_LOG_SQL),
            {
                "level": level,
                "source": source,
                "event": event,
                "message": message,
                "detail": json.dumps(
                    dict(detail) if detail else {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "request_id": request_id,
            },
        )
    ).one()
    return _row_to_system_log(row)


async def record_api_call(
    session: AsyncSession,
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    request_id: str | None = None,
    error_code: str | None = None,
) -> ApiCallLogRow:
    """API 호출 1건을 기록한다. commit은 호출자 책임."""
    row = (
        await session.execute(
            text(_INSERT_API_CALL_LOG_SQL),
            {
                "method": method,
                "path": path,
                "status_code": int(status_code),
                "duration_ms": int(duration_ms),
                "request_id": request_id,
                "error_code": error_code,
            },
        )
    ).one()
    return _row_to_api_call_log(row)


async def list_system_logs(
    session: AsyncSession,
    *,
    level: str | None = None,
    source: str | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> SystemLogPage:
    """``ops.system_log``를 ``created_at DESC, system_log_id DESC`` cursor로 조회."""
    page_size = _limit(limit)
    cursor_created_at, cursor_key = _decode_cursor(cursor, kind="system_logs")
    q_like = f"%{q}%" if q else None
    rows = (
        await session.execute(
            text(_LIST_SYSTEM_LOGS_SQL),
            {
                "level": level,
                "source": source,
                "q_like": q_like,
                "cursor_created_at": cursor_created_at,
                "cursor_key": cursor_key,
                "limit": page_size + 1,
            },
        )
    ).all()
    items = tuple(_row_to_system_log(row) for row in rows[:page_size])
    next_cursor = (
        _encode_cursor(
            "system_logs", at=items[-1].created_at, key=items[-1].system_log_id
        )
        if len(rows) > page_size and items
        else None
    )
    return SystemLogPage(items=items, next_cursor=next_cursor)


async def list_api_call_logs(
    session: AsyncSession,
    *,
    method: str | None = None,
    min_status: int | None = None,
    path: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> ApiCallLogPage:
    """``ops.api_call_log``을 ``created_at DESC, api_call_log_id DESC`` cursor로 조회."""
    page_size = _limit(limit)
    cursor_created_at, cursor_key = _decode_cursor(cursor, kind="api_call_logs")
    path_like = f"%{path}%" if path else None
    rows = (
        await session.execute(
            text(_LIST_API_CALL_LOGS_SQL),
            {
                "method": method,
                "min_status": min_status,
                "path_like": path_like,
                "cursor_created_at": cursor_created_at,
                "cursor_key": cursor_key,
                "limit": page_size + 1,
            },
        )
    ).all()
    items = tuple(_row_to_api_call_log(row) for row in rows[:page_size])
    next_cursor = (
        _encode_cursor(
            "api_call_logs", at=items[-1].created_at, key=items[-1].api_call_log_id
        )
        if len(rows) > page_size and items
        else None
    )
    return ApiCallLogPage(items=items, next_cursor=next_cursor)
