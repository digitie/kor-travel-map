"""``/admin`` 인증 감사 기록과 public API key 관리 라우터."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from kortravelmap.infra.auth_event_repo import (
    AdminAuthEventOutcome,
    AdminAuthEventRow,
    AdminAuthEventType,
    list_admin_auth_events,
    record_admin_auth_event,
)
from kortravelmap.infra.public_api_keys import (
    PublicApiKeyRow,
    create_public_api_key,
    list_public_api_keys,
    revoke_public_api_key,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import AdminProxyContext, require_admin_frontend
from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = ["router"]

router = APIRouter(prefix="/admin", tags=["admin-auth"])


class AdminAuthEventCreateRequest(BaseModel):
    """Next.js login/logout API가 남기는 감사 이벤트."""

    model_config = ConfigDict(extra="forbid")

    event_type: AdminAuthEventType
    outcome: AdminAuthEventOutcome
    attempted_username: str | None = Field(default=None, max_length=80)
    actor: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=120)
    next_path: str | None = Field(default=None, max_length=2048)
    client_ip: str | None = Field(default=None, max_length=128)
    user_agent: str | None = Field(default=None, max_length=512)
    request_id: str | None = Field(default=None, max_length=128)


class AdminAuthEventRecord(BaseModel):
    """``ops.admin_auth_events`` HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    auth_event_id: str
    event_type: AdminAuthEventType
    outcome: AdminAuthEventOutcome
    attempted_username: str | None = None
    actor: str | None = None
    reason: str | None = None
    next_path: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    created_at: datetime


class AdminAuthEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: AdminAuthEventRecord


class AdminAuthEventListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminAuthEventRecord]


class AdminAuthEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminAuthEventData
    meta: Meta


class AdminAuthEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: AdminAuthEventListData
    meta: Meta


PublicApiKeyState = Literal["active", "revoked"]


class PublicApiKeyRecord(BaseModel):
    """저장된 public API key 메타데이터. 원문 key는 포함하지 않는다."""

    model_config = ConfigDict(extra="forbid")

    public_api_key_id: str
    key_hint: str = Field(min_length=6, max_length=12)
    state: PublicApiKeyState
    created_at: datetime
    label: str | None = None
    created_by: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None


class PublicApiKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=80)


class PublicApiKeyCreateData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        min_length=32,
        max_length=32,
        pattern=r"^[0-9A-Za-z]{32}$",
        description="생성 직후 한 번만 반환되는 VWorld 형식 public API key",
    )
    item: PublicApiKeyRecord


class PublicApiKeyListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicApiKeyRecord]


class PublicApiKeyCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: PublicApiKeyCreateData
    meta: Meta


class PublicApiKeyListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: PublicApiKeyListData
    meta: Meta


class PublicApiKeyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: PublicApiKeyRecord
    meta: Meta


def _auth_record(row: AdminAuthEventRow) -> AdminAuthEventRecord:
    return AdminAuthEventRecord(
        auth_event_id=row.auth_event_id,
        event_type=row.event_type,
        outcome=row.outcome,
        attempted_username=row.attempted_username,
        actor=row.actor,
        reason=row.reason,
        next_path=row.next_path,
        client_ip=row.client_ip,
        user_agent=row.user_agent,
        request_id=row.request_id,
        created_at=row.created_at,
    )


def _key_record(row: PublicApiKeyRow) -> PublicApiKeyRecord:
    return PublicApiKeyRecord(
        public_api_key_id=row.public_api_key_id,
        key_hint=row.key_hint,
        state=row.state,
        created_at=row.created_at,
        label=row.label,
        created_by=row.created_by,
        revoked_at=row.revoked_at,
        revoked_by=row.revoked_by,
    )


@router.post("/auth-events", response_model=AdminAuthEventResponse)
async def create_admin_auth_event(
    body: AdminAuthEventCreateRequest,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminAuthEventResponse:
    """Next.js login/logout API가 기록하는 admin 인증 감사 이벤트."""

    started_at = perf_counter()
    item = await record_admin_auth_event(
        session,
        event_type=body.event_type,
        outcome=body.outcome,
        attempted_username=body.attempted_username,
        actor=body.actor or context.actor,
        reason=body.reason,
        next_path=body.next_path,
        client_ip=body.client_ip,
        user_agent=body.user_agent,
        request_id=body.request_id,
    )
    await session.commit()
    return AdminAuthEventResponse(
        data=AdminAuthEventData(item=_auth_record(item)),
        meta=make_meta(started_at=started_at),
    )


@router.get("/auth-events", response_model=AdminAuthEventListResponse)
async def get_admin_auth_events(
    _context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
    event_type: Annotated[AdminAuthEventType | None, Query()] = None,
    outcome: Annotated[AdminAuthEventOutcome | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> AdminAuthEventListResponse:
    """최근 로그인/로그아웃 감사 이벤트 목록."""

    started_at = perf_counter()
    items = await list_admin_auth_events(
        session,
        event_type=event_type,
        outcome=outcome,
        limit=page_size,
    )
    return AdminAuthEventListResponse(
        data=AdminAuthEventListData(items=[_auth_record(item) for item in items]),
        meta=make_meta(started_at=started_at, page_size=page_size),
    )


@router.get("/public-api-keys", response_model=PublicApiKeyListResponse)
async def get_public_api_keys(
    _context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> PublicApiKeyListResponse:
    """저장된 public API key 목록. 원문 key는 반환하지 않는다."""

    started_at = perf_counter()
    items = await list_public_api_keys(session, limit=page_size)
    return PublicApiKeyListResponse(
        data=PublicApiKeyListData(items=[_key_record(item) for item in items]),
        meta=make_meta(started_at=started_at, page_size=page_size),
    )


@router.post("/public-api-keys", response_model=PublicApiKeyCreateResponse)
async def post_public_api_key(
    body: PublicApiKeyCreateRequest,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PublicApiKeyCreateResponse:
    """새 public API key를 생성한다. key 원문은 이 응답에서만 노출한다."""

    started_at = perf_counter()
    result = await create_public_api_key(
        session,
        label=body.label,
        created_by=context.actor,
    )
    await session.commit()
    return PublicApiKeyCreateResponse(
        data=PublicApiKeyCreateData(key=result.key, item=_key_record(result.item)),
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/public-api-keys/{public_api_key_id}/revoke",
    response_model=PublicApiKeyResponse,
)
async def post_revoke_public_api_key(
    public_api_key_id: str,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PublicApiKeyResponse:
    """active public API key를 폐기한다."""

    started_at = perf_counter()
    item = await revoke_public_api_key(
        session,
        public_api_key_id,
        revoked_by=context.actor,
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"active public API key not found: {public_api_key_id}",
        )
    await session.commit()
    return PublicApiKeyResponse(
        data=_key_record(item),
        meta=make_meta(started_at=started_at),
    )
