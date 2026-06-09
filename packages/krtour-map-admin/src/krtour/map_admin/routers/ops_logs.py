"""``/ops/{system-logs,api-call-logs}`` 운영 로그 조회 라우터 (T-212c).

``ops.system_log`` / ``ops.api_call_log``를 시간 역순 keyset cursor로 조회한다.
적재는 ``krtour.map.infra.log_repo`` + ``api_call_log`` 미들웨어(app.py)가 담당하고
본 라우터는 read-only. DA-D-03 ``{data, meta}`` envelope.
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from krtour.map.infra.log_repo import (
    ApiCallLogRow,
    SystemLogRow,
    list_api_call_logs,
    list_system_logs,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map_admin.db import get_session
from krtour.map_admin.response import Meta, make_meta

__all__ = [
    "router",
    "SystemLogRecord",
    "ApiCallLogRecord",
    "SystemLogsResponse",
    "ApiCallLogsResponse",
]


router = APIRouter(prefix="/ops", tags=["ops"])

LogLevel = Literal["debug", "info", "warning", "error", "critical"]


class SystemLogRecord(BaseModel):
    """``ops.system_log`` HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    log_id: str
    level: str
    source: str
    event: str
    message: str
    detail: dict[str, Any]
    request_id: str | None = None
    created_at: datetime


class ApiCallLogRecord(BaseModel):
    """``ops.api_call_log`` HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    log_id: str
    method: str
    path: str
    status_code: int
    duration_ms: int
    request_id: str | None = None
    error_code: str | None = None
    created_at: datetime


class SystemLogsListData(BaseModel):
    """system log 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[SystemLogRecord]


class ApiCallLogsListData(BaseModel):
    """api call log 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[ApiCallLogRecord]


class SystemLogsResponse(BaseModel):
    """``GET /ops/system-logs`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: SystemLogsListData
    meta: Meta


class ApiCallLogsResponse(BaseModel):
    """``GET /ops/api-call-logs`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: ApiCallLogsListData
    meta: Meta


def _system_log(row: SystemLogRow) -> SystemLogRecord:
    return SystemLogRecord(
        log_id=row.system_log_key,
        level=row.level,
        source=row.source,
        event=row.event,
        message=row.message,
        detail=row.detail,
        request_id=row.request_id,
        created_at=row.created_at,
    )


def _api_call_log(row: ApiCallLogRow) -> ApiCallLogRecord:
    return ApiCallLogRecord(
        log_id=row.api_call_log_key,
        method=row.method,
        path=row.path,
        status_code=row.status_code,
        duration_ms=row.duration_ms,
        request_id=row.request_id,
        error_code=row.error_code,
        created_at=row.created_at,
    )


@router.get("/system-logs", response_model=SystemLogsResponse)
async def get_system_logs(
    session: Annotated[AsyncSession, Depends(get_session)],
    level: Annotated[LogLevel | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> SystemLogsResponse:
    """``ops.system_log`` 운영 로그 목록."""
    started_at = perf_counter()
    try:
        page = await list_system_logs(
            session,
            level=level,
            source=source,
            q=q,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SystemLogsResponse(
        data=SystemLogsListData(items=[_system_log(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get("/api-call-logs", response_model=ApiCallLogsResponse)
async def get_api_call_logs(
    session: Annotated[AsyncSession, Depends(get_session)],
    method: Annotated[str | None, Query()] = None,
    min_status: Annotated[int | None, Query(ge=100, le=599)] = None,
    path: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> ApiCallLogsResponse:
    """``ops.api_call_log`` 호출 로그 목록."""
    started_at = perf_counter()
    try:
        page = await list_api_call_logs(
            session,
            method=method,
            min_status=min_status,
            path=path,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApiCallLogsResponse(
        data=ApiCallLogsListData(items=[_api_call_log(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )
