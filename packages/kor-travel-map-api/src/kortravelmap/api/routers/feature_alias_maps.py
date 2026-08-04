"""``/v1/service/feature-alias-maps`` — alias-map DB-to-DB 이관 read 표면 (T-VN-32C).

consumer-rollout-v1 T-VN-32 "32C: PinVi를 UUID+alias contract로 선전환(검증된
alias map DB-to-DB 이관) → 양 저장소 checksum 일치"의 Map 측 서비스 표면이다.
ADR-068 결정 3의 "alias lookup은 전환·복구 경계에서만 제공"이 허용하는 바로 그
경계 — 런타임 조회 표면이 아니라 이관·복구 window 전용 bulk read다.

- ``GET /v1/service/feature-alias-maps`` — canonical 순서(alias NFC UTF-8
  byte 오름차순) keyset 페이지. PinVi가 전체를 순회해 자신의 DB로 이관한다.
- ``GET /v1/service/feature-alias-maps/checksum`` — 저장소 전체 merkle root
  (`feature-alias-map-v1` 계약, `contracts/feature-alias-map-v1-golden.json`).
  PinVi는 받은 행으로 root를 **독립 재계산**해 이 값과 대조하고, 불일치면
  적용하지 않는다 (fail-close).

read 전용이므로 feature_operation_registry 등록 대상이 아니다(registry는
write 표면 소관). 분류·배선은 route_policy가 SERVICE로 게이트한다.
"""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from kortravelmap.core.feature_alias_map import FEATURE_ALIAS_MAP_VERSION
from kortravelmap.infra.feature_alias_map_repo import (
    FEATURE_ALIAS_MAP_PAGE_MAX_LIMIT,
    FeatureAliasMapIntegrityError,
    compute_feature_alias_map_checksum,
    fetch_feature_alias_map_page,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import require_service_token
from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, ProblemDetail, make_meta

__all__ = ["service_router"]

service_router = APIRouter(
    prefix="/service/feature-alias-maps",
    tags=["service-feature-alias-maps"],
    dependencies=[Depends(require_service_token)],
)


class FeatureAliasMapRowOut(BaseModel):
    """alias-map row — ``feature-alias-map-v1`` leaf의 exact 3필드."""

    model_config = ConfigDict(extra="forbid")

    alias: str
    feature_uuid: str
    alias_kind: Literal["legacy_feature_id"]


class FeatureAliasMapPageData(BaseModel):
    """canonical 순서 keyset 페이지."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["feature-alias-map-v1"]
    rows: list[FeatureAliasMapRowOut]
    has_more: bool
    next_after_alias: str | None = Field(
        default=None,
        description="has_more일 때 다음 요청의 after_alias (마지막 row의 alias).",
    )


class FeatureAliasMapPageResponse(BaseModel):
    """``GET /service/feature-alias-maps`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureAliasMapPageData
    meta: Meta


class FeatureAliasMapChecksumData(BaseModel):
    """저장소 전체 alias-map checksum."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["feature-alias-map-v1"]
    alias_count: int
    merkle_root: str


class FeatureAliasMapChecksumResponse(BaseModel):
    """``GET /service/feature-alias-maps/checksum`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureAliasMapChecksumData
    meta: Meta


_INTEGRITY_RESPONSES: dict[int | str, dict[str, Any]] = {
    500: {
        "model": ProblemDetail,
        "description": (
            "FEATURE_ALIAS_MAP_INTEGRITY — 저장 행이 canonical/파생 계약 위반 "
            "(DB 층 보장 붕괴, 이관 중단)"
        ),
    },
}


def _integrity_http_exception(exc: FeatureAliasMapIntegrityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "FEATURE_ALIAS_MAP_INTEGRITY",
            "message": str(exc),
            "details": {},
        },
    )


@service_router.get(
    "",
    response_model=FeatureAliasMapPageResponse,
    summary="alias-map canonical keyset 페이지 (이관 전용 service read)",
    responses=_INTEGRITY_RESPONSES,
)
async def get_feature_alias_map_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    after_alias: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=256,
            description="keyset 시작점(exclusive) — 직전 페이지 next_after_alias.",
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=FEATURE_ALIAS_MAP_PAGE_MAX_LIMIT),
    ] = FEATURE_ALIAS_MAP_PAGE_MAX_LIMIT,
) -> FeatureAliasMapPageResponse:
    started_at = perf_counter()
    try:
        page = await fetch_feature_alias_map_page(
            session, after_alias=after_alias, limit=limit
        )
    except FeatureAliasMapIntegrityError as exc:
        raise _integrity_http_exception(exc) from exc
    rows = [
        FeatureAliasMapRowOut(
            alias=row.alias,
            feature_uuid=row.feature_uuid,
            # 하드코딩 금지 (적대 리뷰 F4-①) — kind가 추가되면 표면이 거짓말하게 된다.
            alias_kind=row.alias_kind,
        )
        for row in page.rows
    ]
    return FeatureAliasMapPageResponse(
        data=FeatureAliasMapPageData(
            schema_version=FEATURE_ALIAS_MAP_VERSION,
            rows=rows,
            has_more=page.has_more,
            next_after_alias=rows[-1].alias if page.has_more and rows else None,
        ),
        meta=make_meta(request, started_at=started_at),
    )


@service_router.get(
    "/checksum",
    response_model=FeatureAliasMapChecksumResponse,
    summary="alias-map 전체 merkle root (양 저장소 checksum 대조)",
    responses=_INTEGRITY_RESPONSES,
)
async def get_feature_alias_map_checksum(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureAliasMapChecksumResponse:
    started_at = perf_counter()
    try:
        checksum = await compute_feature_alias_map_checksum(session)
    except FeatureAliasMapIntegrityError as exc:
        raise _integrity_http_exception(exc) from exc
    return FeatureAliasMapChecksumResponse(
        data=FeatureAliasMapChecksumData(
            schema_version=FEATURE_ALIAS_MAP_VERSION,
            alias_count=checksum.alias_count,
            merkle_root=checksum.merkle_root,
        ),
        meta=make_meta(request, started_at=started_at),
    )
