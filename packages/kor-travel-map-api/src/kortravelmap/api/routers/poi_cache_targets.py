"""``/admin/poi-cache-targets`` 운영 라우터 (ADR-045 T-207f)."""

from __future__ import annotations

import re
from datetime import datetime
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from kortravelmap.core.cache_target_stream import (
    validate_cache_target_external_system,
    validate_cache_target_key,
)
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    PoiCacheTargetConflict,
    delete_poi_cache_target,
    get_dataset_projection_revision,
    get_poi_cache_target_by_key,
    list_poi_cache_targets,
    upsert_poi_cache_target,
)
from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_serializer,
)
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import require_admin_destructive_enabled
from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = [
    "router",
    "PoiCacheTargetRecord",
    "PoiCacheTargetUpsertRequest",
    "PoiCacheTargetMutationResponse",
    "PoiCacheTargetResponse",
    "PoiCacheTargetListResponse",
]

OnConflict = Literal["reject", "move"]
ScopeMode = Literal["center_radius", "sigungu_by_radius"]
RefreshPolicy = Literal[
    "provider_default",
    "follow_system",
    "allow_targeted",
    "disabled",
]
TargetedPolicy = Literal["follow_system", "allow_targeted", "disabled"]
ProviderOverrideKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
MetadataLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
_ExternalSystemPath = Annotated[
    str,
    AfterValidator(validate_cache_target_external_system),
    Path(
        min_length=1,
        max_length=112,
        description="Trimmed Unicode NFC canonical external system identity.",
    ),
]
_TargetKeyPath = Annotated[
    str,
    AfterValidator(validate_cache_target_key),
    Path(
        min_length=1,
        max_length=512,
        description="Trimmed Unicode NFC canonical cache target identity.",
    ),
]

_RELAY_OWNED_EXTERNAL_SYSTEM = "pinvi"


def _validate_optional_external_system(value: str | None) -> str | None:
    return value if value is None else validate_cache_target_external_system(value)


_ExternalSystemQuery = Annotated[
    str | None,
    AfterValidator(_validate_optional_external_system),
    Query(
        min_length=1,
        max_length=112,
        description="Trimmed Unicode NFC canonical external system identity.",
    ),
]

router = APIRouter(
    prefix="/admin/poi-cache-targets",
    tags=["admin-poi-cache-targets"],
)


class CoordinateBody(BaseModel):
    """WGS84 좌표. 모든 외부 인터페이스는 lon/lat 순서를 사용한다."""

    model_config = ConfigDict(extra="forbid")

    lon: float = Field(ge=124.0, le=132.0)
    lat: float = Field(ge=33.0, le=39.5)


class PoiCacheTargetProviderOverride(BaseModel):
    """target별 provider/dataset targeted update override."""

    model_config = ConfigDict(extra="forbid")

    targeted_policy: TargetedPolicy | None = None
    min_interval_seconds: int | None = Field(default=None, ge=1, le=86_400)
    max_requests_per_minute: int | None = Field(default=None, ge=1, le=60_000)
    max_requests_per_hour: int | None = Field(default=None, ge=1, le=1_000_000)
    max_requests_per_day: int | None = Field(default=None, ge=1, le=10_000_000)
    max_concurrent: int | None = Field(default=None, ge=1, le=100)
    note: str | None = Field(default=None, max_length=512)

    @model_serializer
    def _serialize(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.targeted_policy is not None:
            payload["targeted_policy"] = self.targeted_policy
        if self.min_interval_seconds is not None:
            payload["min_interval_seconds"] = self.min_interval_seconds
        if self.max_requests_per_minute is not None:
            payload["max_requests_per_minute"] = self.max_requests_per_minute
        if self.max_requests_per_hour is not None:
            payload["max_requests_per_hour"] = self.max_requests_per_hour
        if self.max_requests_per_day is not None:
            payload["max_requests_per_day"] = self.max_requests_per_day
        if self.max_concurrent is not None:
            payload["max_concurrent"] = self.max_concurrent
        if self.note is not None:
            payload["note"] = self.note
        return payload


class PoiCacheTargetMetadata(BaseModel):
    """target 운영 메타데이터. 임의 key 대신 명시 필드만 받는다."""

    model_config = ConfigDict(extra="forbid")

    external_poi_id: str | None = Field(
        default=None,
        max_length=256,
        # accept-only 구 키 alias (응답은 external_poi_id만 직렬화, #546).
        validation_alias=AliasChoices(
            "external_poi_id", "pinvi_poi_id", "tripmate_poi_id"
        ),
    )
    external_ref: str | None = Field(default=None, max_length=256)
    source_url: str | None = Field(default=None, max_length=2048)
    labels: list[MetadataLabel] = Field(default_factory=list, max_length=32)
    note: str | None = Field(default=None, max_length=1000)

    @model_serializer
    def _serialize(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.external_poi_id is not None:
            payload["external_poi_id"] = self.external_poi_id
        if self.external_ref is not None:
            payload["external_ref"] = self.external_ref
        if self.source_url is not None:
            payload["source_url"] = self.source_url
        if self.labels:
            payload["labels"] = self.labels
        if self.note is not None:
            payload["note"] = self.note
        return payload


class PoiCacheTargetUpsertRequest(BaseModel):
    """cache target 등록/갱신 요청."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    coord: CoordinateBody
    coord_precision_digits: int = Field(default=6, ge=3, le=8)
    radius_km: float = Field(default=5.0, gt=0, le=100)
    name: str | None = Field(default=None, max_length=200)
    scope_mode: ScopeMode = "center_radius"
    update_enabled: bool = True
    refresh_policy: RefreshPolicy = "provider_default"
    provider_overrides: dict[ProviderOverrideKey, PoiCacheTargetProviderOverride] = Field(
        default_factory=dict, max_length=64
    )
    metadata_: PoiCacheTargetMetadata = Field(
        default_factory=PoiCacheTargetMetadata,
        alias="metadata",
    )
    on_conflict: OnConflict = "reject"


class PoiCacheTargetRecord(BaseModel):
    """``ops.poi_cache_targets``의 HTTP 표현."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    target_id: str
    entity_tag: str
    external_system: str
    target_key: str
    name: str | None = None
    coord: CoordinateBody
    coord_precision_digits: int
    coord_key: str
    radius_km: float
    scope_mode: str
    update_enabled: bool
    refresh_policy: str
    provider_overrides: dict[ProviderOverrideKey, PoiCacheTargetProviderOverride] = Field(
        max_length=64
    )
    metadata_: PoiCacheTargetMetadata = Field(alias="metadata")
    last_seen_at: datetime
    last_requested_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_failed_at: datetime | None = None
    next_eligible_refresh_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    status_url: str
    nearby_url: str


class PoiCacheTargetMeta(BaseModel):
    """단건 조회 메타데이터."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int
    request_id: str = ""


class PoiCacheTargetMutationMeta(PoiCacheTargetMeta):
    """live projection과 인과적으로 연결된 쓰기 응답 메타데이터."""

    dataset_projection_revision: int = Field(ge=0)


class PoiCacheTargetResponse(BaseModel):
    """단건 응답."""

    model_config = ConfigDict(extra="forbid")

    data: PoiCacheTargetRecord
    meta: PoiCacheTargetMeta


class PoiCacheTargetMutationResponse(BaseModel):
    """PUT/DELETE 단건 응답. revision receipt는 항상 존재한다."""

    model_config = ConfigDict(extra="forbid")

    data: PoiCacheTargetRecord
    meta: PoiCacheTargetMutationMeta


class PoiCacheTargetListData(BaseModel):
    """POI/cache target 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[PoiCacheTargetRecord]


class PoiCacheTargetListResponse(BaseModel):
    """목록 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: PoiCacheTargetListData
    meta: Meta


def _provider_overrides_payload(
    overrides: dict[ProviderOverrideKey, PoiCacheTargetProviderOverride],
) -> dict[str, dict[str, object]]:
    return {
        key: value.model_dump(mode="json", exclude_none=True) for key, value in overrides.items()
    }


def _metadata_payload(metadata: PoiCacheTargetMetadata) -> dict[str, object]:
    return metadata.model_dump(mode="json")


def _record_from_target(target: PoiCacheTarget) -> PoiCacheTargetRecord:
    return PoiCacheTargetRecord(
        target_id=target.target_id,
        entity_tag=target.entity_tag,
        external_system=target.external_system,
        target_key=target.target_key,
        name=target.name,
        coord=CoordinateBody(lon=target.lon, lat=target.lat),
        coord_precision_digits=target.coord_precision_digits,
        coord_key=target.coord_key,
        radius_km=target.radius_km,
        scope_mode=target.scope_mode,
        update_enabled=target.update_enabled,
        refresh_policy=target.refresh_policy,
        provider_overrides=target.provider_overrides,
        metadata_=target.metadata,
        last_seen_at=target.last_seen_at,
        last_requested_at=target.last_requested_at,
        last_refreshed_at=target.last_refreshed_at,
        last_failed_at=target.last_failed_at,
        next_eligible_refresh_at=target.next_eligible_refresh_at,
        deleted_at=target.deleted_at,
        created_at=target.created_at,
        updated_at=target.updated_at,
        status_url=(
            f"/v1/admin/poi-cache-targets/{target.external_system}/{target.target_key}"
        ),
        nearby_url=(
            "/v1/features/nearby/by-target?"
            f"external_system={target.external_system}&target_key={target.target_key}"
        ),
    )


def _response(
    target: PoiCacheTarget,
    *,
    started_at: float,
) -> PoiCacheTargetResponse:
    return PoiCacheTargetResponse(
        data=_record_from_target(target),
        meta=PoiCacheTargetMeta(duration_ms=max(0, int((perf_counter() - started_at) * 1000))),
    )


def _mutation_response(
    target: PoiCacheTarget,
    *,
    started_at: float,
    dataset_projection_revision: int,
) -> PoiCacheTargetMutationResponse:
    return PoiCacheTargetMutationResponse(
        data=_record_from_target(target),
        meta=PoiCacheTargetMutationMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            dataset_projection_revision=dataset_projection_revision,
        ),
    )


def _target_etag(target: PoiCacheTarget) -> str:
    return target.entity_tag


def _set_target_etag(response: Response, target: PoiCacheTarget) -> None:
    response.headers["ETag"] = _target_etag(target)


_ENTITY_TAG_PATTERN = re.compile(
    r'^"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
    r':([1-9][0-9]*)"$'
)
_MAX_LOCK_VERSION = 9_223_372_036_854_775_807


def _expected_target_identity(request: Request) -> tuple[str, int]:
    """DELETE ``If-Match``를 server canonical UUID+version ETag로 검증한다."""
    values = request.headers.getlist("if-match")
    if not values:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "PRECONDITION_REQUIRED",
                "message": "If-Match header가 필요합니다.",
            },
        )
    if len(values) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="If-Match는 정확히 하나의 header line이어야 합니다.",
        )
    value = values[0]
    matched = _ENTITY_TAG_PATTERN.fullmatch(value)
    if matched is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="If-Match는 server canonical UUID+version strong ETag여야 합니다.",
        )
    try:
        target_id = str(UUID(matched.group(1)))
        lock_version = int(matched.group(2))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="If-Match는 server canonical UUID+version strong ETag여야 합니다.",
        ) from exc
    canonical = f'"{target_id}:{lock_version}"'
    if value != canonical or lock_version > _MAX_LOCK_VERSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="If-Match는 server canonical UUID+version strong ETag여야 합니다.",
        )
    return target_id, lock_version


_ETAG_RESPONSE_HEADER = {
    "ETag": {
        "description": "현재 target UUID와 server-owned version의 strong entity tag.",
        "schema": {
            "type": "string",
            "example": '"00000000-0000-0000-0000-000000000000:1"',
        },
    }
}
_IF_MATCH_OPENAPI_PARAMETER = {
    "name": "If-Match",
    "in": "header",
    "required": True,
    "description": "직전 GET/PUT body의 entity_tag와 같은 UUID+version strong ETag.",
    "schema": {"type": "string"},
}


def _unprocessable(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _require_manual_target_writer(external_system: str) -> None:
    """PinVi target state는 source generation/outbox 경계 밖에서 바꾸지 않는다."""

    if external_system == _RELAY_OWNED_EXTERNAL_SYSTEM:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CACHE_TARGET_SOURCE_PROTOCOL_REQUIRED",
                "message": (
                    "PinVi cache target은 admin 수동 resource로 변경할 수 없습니다. "
                    "ServiceToken source protocol을 사용하세요."
                ),
            },
        )


@router.put(
    "/{external_system}/{target_key}",
    response_model=PoiCacheTargetMutationResponse,
    summary="POI/cache target 등록 또는 갱신",
    responses={
        200: {
            "description": "등록 또는 갱신 완료",
            "headers": _ETAG_RESPONSE_HEADER,
        },
        409: {"description": "같은 key의 좌표 conflict"},
    },
)
async def put_poi_cache_target(
    external_system: _ExternalSystemPath,
    target_key: _TargetKeyPath,
    body: PoiCacheTargetUpsertRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    response: Response,
) -> PoiCacheTargetMutationResponse:
    started_at = perf_counter()
    _require_manual_target_writer(external_system)
    try:
        async with session.begin():
            target = await upsert_poi_cache_target(
                session,
                external_system=external_system,
                target_key=target_key,
                name=body.name,
                lon=body.coord.lon,
                lat=body.coord.lat,
                radius_km=body.radius_km,
                coord_precision_digits=body.coord_precision_digits,
                scope_mode=body.scope_mode,
                update_enabled=body.update_enabled,
                refresh_policy=body.refresh_policy,
                provider_overrides=_provider_overrides_payload(body.provider_overrides),
                metadata=_metadata_payload(body.metadata_),
                on_conflict=body.on_conflict,
            )
            revision = await get_dataset_projection_revision(session)
    except PoiCacheTargetConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise _unprocessable(exc) from exc
    _set_target_etag(response, target)
    return _mutation_response(
        target,
        started_at=started_at,
        dataset_projection_revision=revision,
    )


@router.get(
    "",
    response_model=PoiCacheTargetListResponse,
    summary="POI/cache target 목록",
)
async def list_poi_cache_target_records(
    session: Annotated[AsyncSession, Depends(get_session)],
    external_system: _ExternalSystemQuery = None,
    update_enabled: Annotated[bool | None, Query()] = None,
    include_deleted: Annotated[bool, Query()] = False,
    page_size: Annotated[int, Query(ge=1, le=500)] = 200,
    cursor: Annotated[str | None, Query()] = None,
) -> PoiCacheTargetListResponse:
    started_at = perf_counter()
    try:
        page = await list_poi_cache_targets(
            session,
            external_system=external_system,
            update_enabled=update_enabled,
            include_deleted=include_deleted,
            limit=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise _unprocessable(exc) from exc
    return PoiCacheTargetListResponse(
        data=PoiCacheTargetListData(
            items=[_record_from_target(target) for target in page.items],
        ),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/{external_system}/{target_key}",
    response_model=PoiCacheTargetResponse,
    summary="POI/cache target 단건 조회",
    responses={
        200: {"description": "단건 조회 완료", "headers": _ETAG_RESPONSE_HEADER},
        404: {"description": "target 없음"},
    },
)
async def get_poi_cache_target_record(
    external_system: _ExternalSystemPath,
    target_key: _TargetKeyPath,
    session: Annotated[AsyncSession, Depends(get_session)],
    response: Response,
    include_deleted: Annotated[bool, Query()] = False,
) -> PoiCacheTargetResponse:
    started_at = perf_counter()
    target = await get_poi_cache_target_by_key(
        session,
        external_system=external_system,
        target_key=target_key,
        include_deleted=include_deleted,
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"POI/cache target 없음: {external_system!r}/{target_key!r}",
        )
    _set_target_etag(response, target)
    return _response(target, started_at=started_at)


@router.delete(
    "/{external_system}/{target_key}",
    response_model=PoiCacheTargetMutationResponse,
    summary="POI/cache target soft delete",
    dependencies=[Depends(require_admin_destructive_enabled)],
    responses={
        200: {"description": "soft delete 완료", "headers": _ETAG_RESPONSE_HEADER},
        404: {"description": "target 없음"},
        412: {"description": "If-Match target UUID 또는 version 불일치"},
        422: {"description": "If-Match가 canonical UUID+version strong ETag가 아님"},
        428: {"description": "If-Match 누락"},
        403: {"description": "파괴적 admin 작업 비활성"},
        409: {"description": "PinVi target은 ServiceToken source protocol 전용"},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
async def delete_poi_cache_target_record(
    external_system: _ExternalSystemPath,
    target_key: _TargetKeyPath,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    response: Response,
) -> PoiCacheTargetMutationResponse:
    started_at = perf_counter()
    _require_manual_target_writer(external_system)
    expected_target_id, expected_lock_version = _expected_target_identity(request)
    async with session.begin():
        result = await delete_poi_cache_target(
            session,
            external_system=external_system,
            target_key=target_key,
            expected_target_id=expected_target_id,
            expected_lock_version=expected_lock_version,
        )
        if result.status == "not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"POI/cache target 없음: {external_system!r}/{target_key!r}",
            )
        if result.status == "precondition_failed":
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail={
                    "code": "PRECONDITION_FAILED",
                    "message": "If-Match target UUID/version이 현재 active target과 다릅니다.",
                },
            )
        target = result.target
        if target is None:  # pragma: no cover - dataclass invariant guard
            raise RuntimeError("deleted POI/cache target result is missing target")
        revision = await get_dataset_projection_revision(session)
    _set_target_etag(response, target)
    return _mutation_response(
        target,
        started_at=started_at,
        dataset_projection_revision=revision,
    )
