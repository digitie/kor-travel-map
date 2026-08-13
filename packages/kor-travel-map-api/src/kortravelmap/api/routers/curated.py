"""``/v1/curated-*`` + ``/v1/admin/curated-*`` API (T-223c-1)."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
from collections.abc import Awaitable
from datetime import date, datetime
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from kortravelmap.infra import curated_repo
from kortravelmap.settings import KorTravelMapSettings
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import AdminProxyContext, require_admin_frontend
from kortravelmap.api.curated_public_schema import (
    PublicCuratedFeatureResponse,
    PublicCuratedFeaturesData,
    PublicCuratedFeaturesResponse,
    PublicCuratedFeatureView,
    public_curated_feature_view,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    current_domain_command,
    domain_command_transaction,
    idempotent_domain_command,
)
from kortravelmap.api.feature_ref import resolve_feature_ref_or_error
from kortravelmap.api.http_revision import parse_revision_header, revision_etag
from kortravelmap.api.response import Meta, make_meta

__all__ = ["admin_router", "router"]

router = APIRouter(tags=["curated"])
admin_router = APIRouter(prefix="/admin", tags=["admin-curated"])

CurationStatus = Literal["candidate", "curated", "rejected", "archived"]
CurationRelation = Literal[
    "primary_stop",
    "food_stop",
    "cafe_stop",
    "bookstore_stop",
    "nearby_option",
    "accessibility_support",
    "pet_support",
    "family_support",
    "theme_area_anchor",
]
ReusePolicy = Literal["allowed", "blocked", "manual_review"]
ThemeVisibility = Literal["admin_only", "public"]
SourceKind = Literal["openapi", "filedata", "standard", "internal", "manual"]
UpdateCycle = Literal[
    "realtime",
    "daily",
    "weekly",
    "monthly",
    "annual",
    "one_time",
    "unknown",
]
ProviderStatus = Literal[
    "implemented",
    "provider_needed",
    "manual_only",
    "deprecated",
]
RuleAction = Literal["candidate", "ignore"]

PLACE_SEARCH_LIMIT = 5
KAKAO_LOCAL_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
NAVER_LOCAL_SEARCH_URL = "https://openapi.naver.com/v1/search/local.json"
GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_FIELD_MASK = (
    "places.displayName,places.formattedAddress,places.location,places.primaryTypeDisplayName"
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _omitted_patch_value() -> Any:
    """PATCH 생략값: schema는 optional/non-null, explicit null은 validation 실패."""

    return None


class CuratedThemeView(BaseModel):
    """curated theme view."""

    model_config = ConfigDict(extra="forbid")

    theme_id: UUID
    theme_slug: str
    theme_name: str
    theme_description: str
    theme_group: str
    visibility: ThemeVisibility
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    row_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    archived_at: datetime | None = None
    owner_kind: Literal["operator", "provider_dataset"] | None = None
    owner_provider_dataset_id: int | None = None


class CuratedSourceView(BaseModel):
    """curated source metadata view."""

    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    provider_dataset_id: int
    provider: str
    dataset_key: str
    source_name: str
    source_url: str | None = None
    source_kind: SourceKind
    license: str | None = None
    update_cycle: UpdateCycle
    last_source_modified_at: date | None = None
    last_checked_at: datetime | None = None
    next_expected_at: date | None = None
    row_count: int | None = None
    freshness_note: str | None = None
    provider_status: ProviderStatus
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    row_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    observation_revision: str = Field(pattern=r"^[1-9][0-9]*$")
    archived_at: datetime | None = None
    representation_etag: str


class CuratedSourceRuleView(BaseModel):
    """curated source rule view."""

    model_config = ConfigDict(extra="forbid")

    rule_id: UUID
    theme_id: UUID
    theme_slug: str
    source_id: UUID
    provider_dataset_id: int
    provider: str
    dataset_key: str
    place_kind: str | None = None
    category: str | None = None
    region_scope: dict[str, Any]
    detail_selector: dict[str, Any] | None = None
    default_action: RuleAction
    priority: int
    enabled: bool
    metadata: dict[str, Any]
    row_revision: str
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CuratedFeatureView(BaseModel):
    """admin/operator curated feature overlay view."""

    model_config = ConfigDict(extra="forbid")

    curated_feature_id: str
    theme_id: str
    theme_slug: str
    theme_name: str
    theme_group: str
    feature_id: str
    feature_name: str
    feature_category: str
    feature_kind: str
    lon: float | None = None
    lat: float | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    legal_dong_code: str | None = None
    address: dict[str, Any]
    detail: dict[str, Any]
    source_id: str
    provider_dataset_id: int
    provider: str
    dataset_key: str
    source_name: str
    source_url: str | None = None
    source_record_key: str | None = None
    curation_status: str
    selection_origin: str
    selected_by: str | None = None
    selected_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    rank_score: float
    display_title: str | None = None
    display_summary: str | None = None
    curation_relation: str
    reuse_policy: str
    content_version: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class CuratedThemesData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CuratedThemeView]


class CuratedSourcesData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CuratedSourceView]


class CuratedSourceRulesData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CuratedSourceRuleView]


class CuratedFeaturesData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CuratedFeatureView]


class CuratedThemesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedThemesData
    meta: Meta


class CuratedThemeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedThemeView
    meta: Meta


class CuratedSourcesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedSourcesData
    meta: Meta


class CuratedSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedSourceView
    meta: Meta


class CuratedSourceRulesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedSourceRulesData
    meta: Meta


class CuratedSourceRuleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedSourceRuleView
    meta: Meta


class CuratedFeaturesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedFeaturesData
    meta: Meta


class CuratedFeatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedFeatureView
    meta: Meta


class CuratedFeatureDetailFeatureSnapshotView(BaseModel):
    """detail-snapshot item의 feature 투영 (T-VN-H07D).

    소비자 PinVi가 이 안에서 `name`/`lon`/`lat`/`address`를 직접 읽는다
    (`services/admin_pois.py` label/coord/address 추출기, `api/v1/search.py`의
    `feature_snapshot["name"]` SQL 술어). 생성부가 고정 key로 만들므로 typed view로 고정한다.
    `address`/`detail`은 provider 원본 투영이라 free-form으로 남긴다.
    """

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    name: str
    category: str
    kind: str
    lon: float | None
    lat: float | None
    sido_code: str | None
    sigungu_code: str | None
    legal_dong_code: str | None
    address: dict[str, Any]
    detail: dict[str, Any]


class CuratedFeatureDetailItemView(BaseModel):
    """curated feature detail item.

    T-VN-H07D: `day_index`/`memo`/`source_record_key`는 생성부가 **항상** 내보내는 key인데
    default 때문에 스펙상 optional로 표기됐다. snapshot view와 같은 규약(모든 key는 항상 존재,
    값만 nullable)으로 맞춰 default를 제거한다.
    """

    model_config = ConfigDict(extra="forbid")

    curated_feature_item_id: str
    feature_id: str
    relation: CurationRelation
    sort_order: int
    day_index: int | None
    memo: str | None
    feature_snapshot: CuratedFeatureDetailFeatureSnapshotView
    source_record_key: str | None


class CuratedFeatureDetailThemeView(BaseModel):
    """detail-snapshot theme payload (T-VN-H07D — 소비자 PinVi가 category fallback으로 읽는다)."""

    model_config = ConfigDict(extra="forbid")

    theme_slug: str
    theme_name: str


class CuratedFeatureDetailContentView(BaseModel):
    """detail-snapshot plan-level payload (T-VN-H07D).

    PinVi curated import(`services/notice_plan.py`)가 plan title/category/summary/destination을
    여기서 읽는다. 모든 key는 항상 존재하며(생성부가 고정 key로 만든다) 값만 nullable이다.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str | None
    destination_name: str | None
    region_code: str | None
    category: str
    curation_status: CurationStatus
    reuse_policy: ReusePolicy


class CuratedFeatureDetailSourceView(BaseModel):
    """detail-snapshot source payload (T-VN-H07D)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    source_name: str
    source_url: str | None


class CuratedFeatureDetailSnapshotView(BaseModel):
    """curated feature detail snapshot.

    T-VN-H07D: `theme`/`content`/`source`는 과거 free-form ``dict[str, Any]``이라 OpenAPI에
    `{"type": "object"}`로만 노출됐고, 소비자(PinVi)가 실제로 의존하는 plan-level 필드를 계약으로
    고정할 방법이 없었다. 생성부가 고정 key로 만드는 값이므로 typed view로 전환한다.
    ``items[].feature_snapshot``도 소비자가 내부 key(`name`/`lon`/`lat`/`address`)를 실제로
    읽으므로 함께 typed view로 고정한다.
    """

    model_config = ConfigDict(extra="forbid")

    curated_feature_id: str
    version: int
    etag: str
    updated_at: datetime
    theme: CuratedFeatureDetailThemeView
    content: CuratedFeatureDetailContentView
    source: CuratedFeatureDetailSourceView
    items: list[CuratedFeatureDetailItemView]


class CuratedFeatureDetailSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedFeatureDetailSnapshotView
    meta: Meta


class PlaceSearchHitView(BaseModel):
    """external place-search normalized hit."""

    model_config = ConfigDict(extra="allow")

    provider: str
    name: str | None = None
    address: str | None = None
    road_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    category: str | None = None


class CuratedPlaceSearchData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    google: list[PlaceSearchHitView]
    kakao: list[PlaceSearchHitView]
    naver: list[PlaceSearchHitView]
    errors: dict[str, str]


class CuratedPlaceSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CuratedPlaceSearchData
    meta: Meta


class RuleApplyData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    inserted_or_updated: int


class RuleApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: RuleApplyData
    meta: Meta


class CuratedThemeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_slug: str = Field(min_length=1, max_length=128)
    theme_name: str = Field(min_length=1, max_length=200)
    theme_description: str = ""
    theme_group: str = Field(min_length=1, max_length=64)
    visibility: ThemeVisibility = "admin_only"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CuratedThemePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_slug: str = Field(
        default_factory=_omitted_patch_value, min_length=1, max_length=128
    )
    theme_name: str = Field(
        default_factory=_omitted_patch_value, min_length=1, max_length=200
    )
    theme_description: str = Field(default_factory=_omitted_patch_value)
    theme_group: str = Field(
        default_factory=_omitted_patch_value, min_length=1, max_length=64
    )
    visibility: ThemeVisibility = Field(default_factory=_omitted_patch_value)
    metadata: dict[str, Any] = Field(default_factory=_omitted_patch_value)


class CuratedThemeArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=100)


class CuratedSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_dataset_id: int = Field(gt=0)
    source_name: str = Field(min_length=1, max_length=200)
    source_url: str | None = None
    source_kind: SourceKind
    license: str | None = None
    update_cycle: UpdateCycle = "unknown"
    freshness_note: str | None = None
    provider_status: ProviderStatus = "implemented"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CuratedSourcePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(
        default_factory=_omitted_patch_value, min_length=1, max_length=200
    )
    source_url: str | None = None
    source_kind: SourceKind = Field(default_factory=_omitted_patch_value)
    license: str | None = None
    update_cycle: UpdateCycle = Field(default_factory=_omitted_patch_value)
    freshness_note: str | None = None
    provider_status: ProviderStatus = Field(default_factory=_omitted_patch_value)
    metadata: dict[str, Any] = Field(default_factory=_omitted_patch_value)


class CuratedSourceArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=100)


class CuratedSourceRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: UUID
    source_id: UUID
    place_kind: str | None = None
    category: str | None = None
    region_scope: dict[str, Any] = Field(default_factory=dict)
    detail_selector: dict[str, Any] | None = None
    default_action: RuleAction = "candidate"
    priority: int = Field(default=0, ge=-2147483648, le=2147483647)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CuratedSourceRulePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_kind: str | None = None
    category: str | None = None
    region_scope: dict[str, Any] = Field(default_factory=_omitted_patch_value)
    detail_selector: dict[str, Any] | None = None
    default_action: RuleAction = Field(default_factory=_omitted_patch_value)
    priority: int = Field(
        default_factory=_omitted_patch_value, ge=-2147483648, le=2147483647
    )
    enabled: bool = Field(default_factory=_omitted_patch_value)
    metadata: dict[str, Any] = Field(default_factory=_omitted_patch_value)


class CuratedSourceRuleArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=100)


class CuratedFeatureCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: str
    feature_id: str = Field(min_length=1)
    source_id: str
    source_record_key: str | None = None
    curation_status: CurationStatus = "candidate"
    rejection_reason: str | None = None
    rank_score: float = 0.0
    display_title: str | None = None
    display_summary: str | None = None
    curation_relation: CurationRelation = "nearby_option"
    reuse_policy: ReusePolicy = "manual_review"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def reject_reserved_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "merge_projection_detached" in value:
            raise ValueError("merge_projection_detached metadata는 내부 전용입니다.")
        return value


class CuratedFeaturePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curation_status: CurationStatus | None = None
    theme_id: str | None = None
    source_record_key: str | None = None
    rank_score: float | None = None
    display_title: str | None = None
    display_summary: str | None = None
    curation_relation: CurationRelation | None = None
    reuse_policy: ReusePolicy | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("metadata")
    @classmethod
    def reject_reserved_metadata(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is not None and "merge_projection_detached" in value:
            raise ValueError("merge_projection_detached metadata는 내부 전용입니다.")
        return value


class CuratedFeatureStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ADR-066 D-2 (T-VN-20): 감사 actor는 인증 principal에서만 파생한다. body의
    # actor 필드는 제거했다 — 옛 caller가 보내면 extra="forbid"로 422다. curated
    # select/unselect는 admin frontend 전용이고 PinVi는 호출하지 않는다.
    reason: str | None = None


def _theme_view(row: curated_repo.CuratedTheme) -> CuratedThemeView:
    payload = dict(row.__dict__)
    payload["row_revision"] = str(row.row_revision)
    return CuratedThemeView.model_validate(payload)


def _source_view(row: curated_repo.CuratedSource) -> CuratedSourceView:
    payload = dict(row.__dict__)
    payload["row_revision"] = str(row.row_revision)
    payload["observation_revision"] = str(row.observation_revision)
    representation_hash = hashlib.sha256(
        json.dumps(
            payload,
            default=str,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    payload["representation_etag"] = f'"sha256:{representation_hash}"'
    return CuratedSourceView.model_validate(payload)


def _rule_view(row: curated_repo.CuratedSourceRule) -> CuratedSourceRuleView:
    payload = dict(row.__dict__)
    payload["row_revision"] = str(row.row_revision)
    return CuratedSourceRuleView.model_validate(payload)


def _feature_view(row: curated_repo.CuratedFeature) -> CuratedFeatureView:
    # T-VN-32C PR-2 — admin curated 뷰도 feature 참조를 UUID 정본으로 통일한다
    # (admin features 목록과 같은 규약 — 프론트 왕복은 write-측 경계 해석이
    # 수용). splat 원본 row의 legacy 값은 내부 키로만 쓴다.
    payload = dict(row.__dict__)
    uuid_text = payload.pop("feature_uuid", None)
    if not uuid_text:
        raise ValueError(
            "CuratedFeature.feature_uuid 결측 — read projection 누락 (T-VN-32C)"
        )
    payload["feature_id"] = uuid_text
    return CuratedFeatureView(**payload)


def _public_feature_view(
    row: curated_repo.CuratedFeature,
) -> PublicCuratedFeatureView | None:
    """테스트/호출부가 공유하는 공개 projection 진입점."""

    return public_curated_feature_view(row)


def _snapshot_view(
    row: curated_repo.CuratedFeatureDetailSnapshot,
) -> CuratedFeatureDetailSnapshotView:
    return CuratedFeatureDetailSnapshotView(
        curated_feature_id=row.curated_feature_id,
        version=row.version,
        etag=row.etag,
        updated_at=row.updated_at,
        # T-VN-H07D: 생성부(`curated_repo._feature_detail_snapshot`)가 고정 key로 만든 payload를
        # typed view로 검증한다. key가 어긋나면 여기서 fail-closed된다(etag 계산 대상인 repo
        # payload dict 자체는 바꾸지 않아 기존 etag/캐시 계약은 그대로다).
        theme=CuratedFeatureDetailThemeView(**row.theme),
        content=CuratedFeatureDetailContentView(**row.content),
        source=CuratedFeatureDetailSourceView(**row.source),
        items=[CuratedFeatureDetailItemView(**item.__dict__) for item in row.items],
    )


def _integrity_error(exc: IntegrityError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"curated row constraint violation: {exc.orig}",
    )


def _rule_command_error(exc: DBAPIError) -> HTTPException:
    message = str(exc.orig)
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "40001":
        raise exc
    if "rule revision mismatch" in message:
        return HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="curated source rule revision이 변경됐습니다.",
        )
    if sqlstate == "P0002":
        return HTTPException(status_code=404, detail="curated source rule 없음")
    if sqlstate == "23505":
        return HTTPException(status_code=409, detail="curated source rule identity conflict")
    if "archived rule" in message:
        return HTTPException(status_code=409, detail=message)
    if sqlstate in {"22P02", "23502", "23503", "23514", "22023"}:
        return HTTPException(status_code=422, detail=message)
    if sqlstate == "42501":
        return HTTPException(status_code=403, detail="curated source rule command 권한이 없습니다.")
    raise exc


def _theme_command_error(exc: DBAPIError) -> HTTPException:
    message = str(exc.orig)
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "40001":
        raise exc
    if "theme revision mismatch" in message:
        return HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="curated theme revision이 변경됐습니다.",
        )
    if sqlstate == "P0002":
        return HTTPException(status_code=404, detail="curated theme 없음")
    if sqlstate == "23505":
        return HTTPException(status_code=409, detail="curated theme identity conflict")
    if "archived theme" in message or "already archived" in message:
        return HTTPException(status_code=409, detail=message)
    if sqlstate in {"22P02", "23502", "23503", "23514", "22023"}:
        return HTTPException(status_code=422, detail=message)
    if sqlstate == "42501":
        return HTTPException(status_code=403, detail="curated theme command 권한이 없습니다.")
    raise exc


def _source_command_error(exc: DBAPIError) -> HTTPException:
    message = str(exc.orig)
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "40001":
        raise exc
    if "source revision mismatch" in message:
        return HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="curated source revision이 변경됐습니다.",
        )
    if sqlstate == "P0002":
        return HTTPException(status_code=404, detail="curated source 없음")
    if sqlstate == "23505":
        return HTTPException(status_code=409, detail="curated source identity conflict")
    if "archived source" in message or "already archived" in message:
        return HTTPException(status_code=409, detail=message)
    if sqlstate in {"22P02", "23502", "23503", "23514", "22023"}:
        return HTTPException(status_code=422, detail=message)
    if sqlstate == "42501":
        return HTTPException(status_code=403, detail="curated source command 권한이 없습니다.")
    raise exc


_CATALOG_ETAG_RESPONSE_HEADER = {
    "ETag": {
        "description": "현재 retained catalog row_revision strong entity tag.",
        "schema": {"type": "string"},
    }
}
_CATALOG_IF_MATCH_OPENAPI_PARAMETER = {
    "name": "If-Match",
    "in": "header",
    "required": True,
    "description": "직전 단건 GET/성공 응답의 catalog row_revision strong ETag.",
    "schema": {"type": "string"},
}


def _secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None


def _clean_place_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = html.unescape(_HTML_TAG_RE.sub("", value)).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _naver_wgs84_coord(value: Any) -> float | None:
    coord = _float_or_none(value)
    if coord is None:
        return None
    if abs(coord) > 180:
        return coord / 10_000_000
    return coord


def _google_display_text(value: Any) -> str | None:
    if isinstance(value, dict):
        return _clean_place_text(value.get("text"))
    return _clean_place_text(value)


async def _search_kakao_places(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    query: str,
) -> list[PlaceSearchHitView]:
    response = await client.get(
        KAKAO_LOCAL_KEYWORD_URL,
        headers={"Authorization": f"KakaoAK {api_key}"},
        params={"query": query, "size": PLACE_SEARCH_LIMIT},
    )
    response.raise_for_status()
    payload = response.json()
    raw_items = payload.get("documents") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return []

    hits: list[PlaceSearchHitView] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        hits.append(
            PlaceSearchHitView(
                provider="kakao",
                name=_clean_place_text(item.get("place_name")),
                address=_clean_place_text(item.get("address_name")),
                road_address=_clean_place_text(item.get("road_address_name")),
                latitude=_float_or_none(item.get("y")),
                longitude=_float_or_none(item.get("x")),
                category=_clean_place_text(item.get("category_name")),
            )
        )
    return hits


async def _search_naver_places(
    client: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str,
    query: str,
) -> list[PlaceSearchHitView]:
    response = await client.get(
        NAVER_LOCAL_SEARCH_URL,
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
        params={"query": query, "display": PLACE_SEARCH_LIMIT},
    )
    response.raise_for_status()
    payload = response.json()
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return []

    hits: list[PlaceSearchHitView] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        hits.append(
            PlaceSearchHitView(
                provider="naver",
                name=_clean_place_text(item.get("title")),
                address=_clean_place_text(item.get("address")),
                road_address=_clean_place_text(item.get("roadAddress")),
                latitude=_naver_wgs84_coord(item.get("mapy")),
                longitude=_naver_wgs84_coord(item.get("mapx")),
                category=_clean_place_text(item.get("category")),
            )
        )
    return hits


async def _search_google_places(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    query: str,
) -> list[PlaceSearchHitView]:
    response = await client.post(
        GOOGLE_PLACES_TEXT_SEARCH_URL,
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
        },
        json={
            "textQuery": query,
            "languageCode": "ko",
            "regionCode": "KR",
            "maxResultCount": PLACE_SEARCH_LIMIT,
        },
    )
    response.raise_for_status()
    payload = response.json()
    raw_items = payload.get("places") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return []

    hits: list[PlaceSearchHitView] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        location = item.get("location")
        primary_type = item.get("primaryTypeDisplayName")
        hits.append(
            PlaceSearchHitView(
                provider="google",
                name=_google_display_text(item.get("displayName")),
                address=_clean_place_text(item.get("formattedAddress")),
                road_address=None,
                latitude=_float_or_none(location.get("latitude"))
                if isinstance(location, dict)
                else None,
                longitude=_float_or_none(location.get("longitude"))
                if isinstance(location, dict)
                else None,
                category=_google_display_text(primary_type),
            )
        )
    return hits


async def _capture_place_search(
    provider: str,
    awaitable: Awaitable[list[PlaceSearchHitView]],
) -> tuple[str, list[PlaceSearchHitView], str | None]:
    try:
        return provider, await awaitable, None
    except httpx.HTTPStatusError as exc:
        return provider, [], f"HTTP {exc.response.status_code}"
    except httpx.HTTPError:
        return provider, [], "호출 실패"
    except ValueError:
        return provider, [], "응답 파싱 실패"


async def _direct_place_search(query: str) -> CuratedPlaceSearchData:
    settings = KorTravelMapSettings()
    google_key = _secret_value(settings.google_places_api_key)
    kakao_key = _secret_value(settings.kakao_local_rest_api_key)
    naver_client_id = _secret_value(settings.naver_search_client_id)
    naver_client_secret = _secret_value(settings.naver_search_client_secret)

    google: list[PlaceSearchHitView] = []
    kakao: list[PlaceSearchHitView] = []
    naver: list[PlaceSearchHitView] = []
    errors: dict[str, str] = {}

    if google_key is None:
        errors["google"] = "KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY env가 없습니다."
    if kakao_key is None:
        errors["kakao"] = "KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY env가 없습니다."
    if naver_client_id is None or naver_client_secret is None:
        errors["naver"] = (
            "KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID/SECRET env가 없습니다."
        )

    tasks: list[Awaitable[tuple[str, list[PlaceSearchHitView], str | None]]] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        if google_key is not None:
            tasks.append(
                _capture_place_search(
                    "google",
                    _search_google_places(client, api_key=google_key, query=query),
                )
            )
        if kakao_key is not None:
            tasks.append(
                _capture_place_search(
                    "kakao",
                    _search_kakao_places(client, api_key=kakao_key, query=query),
                )
            )
        if naver_client_id is not None and naver_client_secret is not None:
            tasks.append(
                _capture_place_search(
                    "naver",
                    _search_naver_places(
                        client,
                        client_id=naver_client_id,
                        client_secret=naver_client_secret,
                        query=query,
                    ),
                )
            )
        results = await asyncio.gather(*tasks) if tasks else []

    for provider, hits, error in results:
        if error is not None:
            errors[provider] = error
        elif provider == "google":
            google = hits
        elif provider == "kakao":
            kakao = hits
        elif provider == "naver":
            naver = hits

    return CuratedPlaceSearchData(
        query=query,
        google=google,
        kakao=kakao,
        naver=naver,
        errors=errors,
    )


async def _feature_or_404(
    session: AsyncSession,
    curated_feature_id: str,
    *,
    include_archived: bool = False,
    public_only: bool = False,
) -> curated_repo.CuratedFeature:
    row = await curated_repo.get_curated_feature(
        session,
        curated_feature_id=curated_feature_id,
        include_archived=include_archived,
        public_only=public_only,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return row


async def _list_curated_themes_response(
    session: Annotated[AsyncSession, Depends(get_session)],
    *,
    visibility: ThemeVisibility | None,
    theme_group: str | None,
    limit: int,
) -> CuratedThemesResponse:
    started_at = perf_counter()
    rows = await curated_repo.list_curated_themes(
        session,
        visibility=visibility,
        theme_group=theme_group,
        limit=limit,
    )
    return CuratedThemesResponse(
        data=CuratedThemesData(items=[_theme_view(row) for row in rows]),
        meta=make_meta(started_at=started_at),
    )


@router.get("/curated-themes", response_model=CuratedThemesResponse)
async def list_curated_themes_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_group: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedThemesResponse:
    return await _list_curated_themes_response(
        session,
        visibility="public",
        theme_group=theme_group,
        limit=limit,
    )


@router.get("/curated-sources", response_model=CuratedSourcesResponse)
async def list_curated_sources_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    provider_dataset_id: Annotated[int | None, Query(gt=0)] = None,
    provider_status: Annotated[ProviderStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedSourcesResponse:
    started_at = perf_counter()
    rows = await curated_repo.list_curated_sources(
        session,
        provider_dataset_id=provider_dataset_id,
        provider_status=provider_status,
        limit=limit,
    )
    return CuratedSourcesResponse(
        data=CuratedSourcesData(items=[_source_view(row) for row in rows]),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/curated-features",
    response_model=PublicCuratedFeaturesResponse,
    response_model_exclude_none=True,
)
async def list_curated_features_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_slug: Annotated[str | None, Query()] = None,
    region_code: Annotated[str | None, Query()] = None,
    sido_code: Annotated[str | None, Query()] = None,
    sigungu_code: Annotated[str | None, Query()] = None,
    min_lon: Annotated[float | None, Query()] = None,
    min_lat: Annotated[float | None, Query()] = None,
    max_lon: Annotated[float | None, Query()] = None,
    max_lat: Annotated[float | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    feature_name: Annotated[str | None, Query()] = None,
    display_title: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> PublicCuratedFeaturesResponse:
    started_at = perf_counter()
    try:
        page = await curated_repo.list_curated_features(
            session,
            theme_slug=theme_slug,
            curation_status="curated",
            region_code=region_code,
            sido_code=sido_code,
            sigungu_code=sigungu_code,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            q=q,
            feature_name=feature_name,
            display_title=display_title,
            page_size=page_size,
            cursor=cursor,
            public_only=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PublicCuratedFeaturesResponse(
        data=PublicCuratedFeaturesData(
            items=[item for row in page.items if (item := _public_feature_view(row)) is not None]
        ),
        meta=make_meta(started_at=started_at, next_cursor=page.next_cursor),
    )


@router.get(
    "/curated-features/{curated_feature_id}",
    response_model=PublicCuratedFeatureResponse,
    response_model_exclude_none=True,
)
async def get_curated_feature_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PublicCuratedFeatureResponse:
    started_at = perf_counter()
    # 공개 표면 — underlying feature가 공개 projection에 없으면 404 (ADR-067).
    row = await _feature_or_404(session, curated_feature_id, public_only=True)
    view = _public_feature_view(row)
    if view is None:
        raise HTTPException(status_code=404, detail="지원하지 않는 공개 feature kind")
    return PublicCuratedFeatureResponse(
        data=view,
        meta=make_meta(started_at=started_at),
    )


@admin_router.get("/features/curated", response_model=CuratedFeaturesResponse)
@admin_router.get(
    "/curated-features",
    response_model=CuratedFeaturesResponse,
    include_in_schema=False,
)
async def list_admin_curated_features_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_id: Annotated[str | None, Query()] = None,
    theme_slug: Annotated[str | None, Query()] = None,
    source_id: Annotated[str | None, Query()] = None,
    provider_dataset_id: Annotated[int | None, Query(gt=0)] = None,
    curation_status: Annotated[CurationStatus | None, Query()] = None,
    region_code: Annotated[str | None, Query()] = None,
    sido_code: Annotated[str | None, Query()] = None,
    sigungu_code: Annotated[str | None, Query()] = None,
    min_lon: Annotated[float | None, Query()] = None,
    min_lat: Annotated[float | None, Query()] = None,
    max_lon: Annotated[float | None, Query()] = None,
    max_lat: Annotated[float | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    feature_name: Annotated[str | None, Query()] = None,
    display_title: Annotated[str | None, Query()] = None,
    display_titles: Annotated[list[str] | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    distinct_by_feature: Annotated[bool, Query()] = False,
) -> CuratedFeaturesResponse:
    started_at = perf_counter()
    try:
        page = await curated_repo.list_curated_features(
            session,
            theme_id=theme_id,
            theme_slug=theme_slug,
            source_id=source_id,
            provider_dataset_id=provider_dataset_id,
            curation_status=curation_status,
            region_code=region_code,
            sido_code=sido_code,
            sigungu_code=sigungu_code,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            q=q,
            feature_name=feature_name,
            display_title=display_title,
            display_titles=display_titles,
            include_archived=include_archived,
            page_size=page_size,
            cursor=cursor,
            distinct_by_feature=distinct_by_feature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CuratedFeaturesResponse(
        data=CuratedFeaturesData(items=[_feature_view(row) for row in page.items]),
        meta=make_meta(started_at=started_at, next_cursor=page.next_cursor),
    )


@admin_router.get(
    "/features/curated/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
)
@admin_router.get(
    "/curated-features/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
async def get_admin_curated_feature_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    row = await _feature_or_404(session, curated_feature_id, include_archived=True)
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get(
    "/features/curated/{curated_feature_id}/detail-snapshot",
    response_model=CuratedFeatureDetailSnapshotResponse,
)
async def get_admin_curated_feature_detail_snapshot_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureDetailSnapshotResponse:
    started_at = perf_counter()
    row = await curated_repo.get_curated_feature_detail_snapshot(
        session,
        curated_feature_id=curated_feature_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureDetailSnapshotResponse(
        data=_snapshot_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get(
    "/features/curated/{curated_feature_id}/place-search",
    response_model=CuratedPlaceSearchResponse,
)
@admin_router.get(
    "/curated-features/{curated_feature_id}/place-search",
    response_model=CuratedPlaceSearchResponse,
    include_in_schema=False,
)
async def search_admin_curated_feature_places_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(min_length=1)] = None,
) -> CuratedPlaceSearchResponse:
    started_at = perf_counter()
    feature = await _feature_or_404(session, curated_feature_id, include_archived=True)
    query = (q or feature.display_title or feature.feature_name or feature.source_name).strip()
    if not query:
        raise HTTPException(status_code=400, detail="검색어 q가 필요합니다")
    data = await _direct_place_search(query)
    return CuratedPlaceSearchResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


@admin_router.post("/features/curated", response_model=CuratedFeatureResponse)
@admin_router.post(
    "/curated-features",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
@idempotent_domain_command("admin.curated-feature.create")
async def create_admin_curated_feature_route(
    body: CuratedFeatureCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    payload = body.model_dump()
    # T-VN-32C PR-2 — 값 전환 후 admin이 응답에서 복사한 UUID 참조를 legacy
    # 정본 키로 경계 해석한다 (미존재는 404, 형식 오류 422 — W5).
    identity = await resolve_feature_ref_or_error(session, payload["feature_id"])
    payload["feature_id"] = identity.feature_id
    curation_status = payload["curation_status"]
    try:
        async with domain_command_transaction(session):
            row = await curated_repo.create_curated_feature(
                session,
                **payload,
                selection_origin="admin",
                selected_by=context.actor if curation_status == "curated" else None,
                rejected_by=context.actor if curation_status == "rejected" else None,
                actor=context.actor,
            )
    except IntegrityError as exc:
        raise _integrity_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.patch(
    "/features/curated/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
)
@admin_router.patch(
    "/curated-features/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
@idempotent_domain_command("admin.curated-feature.patch")
async def patch_admin_curated_feature_route(
    curated_feature_id: str,
    body: CuratedFeaturePatchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    try:
        async with domain_command_transaction(session):
            row = await curated_repo.update_curated_feature(
                session,
                curated_feature_id=curated_feature_id,
                updates=body.model_dump(exclude_unset=True),
                actor=context.actor,
            )
    except IntegrityError as exc:
        raise _integrity_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.delete(
    "/features/curated/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
)
@admin_router.delete(
    "/curated-features/{curated_feature_id}",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
@idempotent_domain_command("admin.curated-feature.delete")
async def delete_admin_curated_feature_route(
    curated_feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    async with domain_command_transaction(session):
        row = await curated_repo.archive_curated_feature(
            session,
            curated_feature_id=curated_feature_id,
            actor=context.actor,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.post(
    "/features/curated/{curated_feature_id}/select",
    response_model=CuratedFeatureResponse,
)
@admin_router.post(
    "/curated-features/{curated_feature_id}/select",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
@idempotent_domain_command("admin.curated-feature.select")
async def select_admin_curated_feature_route(
    curated_feature_id: str,
    body: CuratedFeatureStatusRequest,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    async with domain_command_transaction(session):
        row = await curated_repo.set_curated_feature_status(
            session,
            curated_feature_id=curated_feature_id,
            curation_status="curated",
            actor=context.actor,
            reason=body.reason,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.post(
    "/features/curated/{curated_feature_id}/unselect",
    response_model=CuratedFeatureResponse,
)
@admin_router.post(
    "/curated-features/{curated_feature_id}/unselect",
    response_model=CuratedFeatureResponse,
    include_in_schema=False,
)
@idempotent_domain_command("admin.curated-feature.unselect")
async def unselect_admin_curated_feature_route(
    curated_feature_id: str,
    body: CuratedFeatureStatusRequest,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedFeatureResponse:
    started_at = perf_counter()
    async with domain_command_transaction(session):
        row = await curated_repo.set_curated_feature_status(
            session,
            curated_feature_id=curated_feature_id,
            curation_status="rejected",
            actor=context.actor,
            reason=body.reason,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="curated feature 없음")
    return CuratedFeatureResponse(
        data=_feature_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get("/curated-themes", response_model=CuratedThemesResponse)
async def list_admin_curated_themes_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    visibility: Annotated[ThemeVisibility | None, Query()] = None,
    theme_group: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedThemesResponse:
    return await _list_curated_themes_response(
        session,
        visibility=visibility,
        theme_group=theme_group,
        limit=limit,
    )


@admin_router.post(
    "/curated-themes",
    response_model=CuratedThemeResponse,
    status_code=status.HTTP_201_CREATED,
    responses={201: {"headers": _CATALOG_ETAG_RESPONSE_HEADER}},
)
@idempotent_domain_command("admin.curated-theme.create")
async def create_admin_curated_theme_route(
    body: CuratedThemeCreateRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedThemeResponse:
    started_at = perf_counter()
    try:
        async with domain_command_transaction(session):
            command = current_domain_command()
            row = await curated_repo.create_curated_theme_command(
                session,
                **body.model_dump(),
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _theme_command_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedThemeResponse(
        data=_theme_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get(
    "/curated-themes/{theme_id}",
    response_model=CuratedThemeResponse,
    responses={200: {"headers": _CATALOG_ETAG_RESPONSE_HEADER}},
)
async def get_admin_curated_theme_route(
    theme_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedThemeResponse:
    started_at = perf_counter()
    row = await curated_repo.get_curated_theme(session, theme_id=str(theme_id))
    if row is None:
        raise HTTPException(status_code=404, detail="curated theme 없음")
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedThemeResponse(
        data=_theme_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.patch(
    "/curated-themes/{theme_id}",
    response_model=CuratedThemeResponse,
    responses={
        200: {"headers": _CATALOG_ETAG_RESPONSE_HEADER},
        412: {"description": "stale theme If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_CATALOG_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curated-theme.patch")
async def patch_admin_curated_theme_route(
    request: Request,
    theme_id: UUID,
    body: CuratedThemePatchRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedThemeResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            command = current_domain_command()
            row = await curated_repo.patch_curated_theme_command(
                session,
                theme_id=str(theme_id),
                expected_revision=expected_revision,
                updates=body.model_dump(exclude_unset=True),
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _theme_command_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated theme 없음")
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedThemeResponse(
        data=_theme_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.delete(
    "/curated-themes/{theme_id}",
    response_model=CuratedThemeResponse,
    responses={
        200: {"headers": _CATALOG_ETAG_RESPONSE_HEADER},
        412: {"description": "stale theme If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_CATALOG_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curated-theme.archive")
async def archive_admin_curated_theme_route(
    request: Request,
    theme_id: UUID,
    body: CuratedThemeArchiveRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedThemeResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            command = current_domain_command()
            row = await curated_repo.archive_curated_theme_command(
                session,
                theme_id=str(theme_id),
                expected_revision=expected_revision,
                command_id=command.command_id,
                reason_code=body.reason_code,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _theme_command_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated theme 없음")
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedThemeResponse(
        data=_theme_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get("/curated-sources", response_model=CuratedSourcesResponse)
async def list_admin_curated_sources_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    provider_dataset_id: Annotated[int | None, Query(gt=0)] = None,
    provider_status: Annotated[ProviderStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedSourcesResponse:
    return await list_curated_sources_route(
        session=session,
        provider_dataset_id=provider_dataset_id,
        provider_status=provider_status,
        limit=limit,
    )


@admin_router.post(
    "/curated-sources",
    response_model=CuratedSourceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={201: {"headers": _CATALOG_ETAG_RESPONSE_HEADER}},
)
@idempotent_domain_command("admin.curated-source.create")
async def create_admin_curated_source_route(
    body: CuratedSourceCreateRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceResponse:
    started_at = perf_counter()
    try:
        async with domain_command_transaction(session):
            command = current_domain_command()
            row = await curated_repo.create_curated_source_command(
                session,
                **body.model_dump(),
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _source_command_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedSourceResponse(
        data=_source_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get(
    "/curated-sources/{source_id}",
    response_model=CuratedSourceResponse,
    responses={304: {"description": "representation ETag 일치"}},
)
async def get_admin_curated_source_route(
    request: Request,
    source_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceResponse | Response:
    started_at = perf_counter()
    row = await curated_repo.get_curated_source(session, source_id=str(source_id))
    if row is None:
        raise HTTPException(status_code=404, detail="curated source 없음")
    view = _source_view(row)
    if request.headers.get("if-none-match") == view.representation_etag:
        return Response(status_code=304, headers={"ETag": view.representation_etag})
    response.headers["ETag"] = view.representation_etag
    return CuratedSourceResponse(
        data=view,
        meta=make_meta(started_at=started_at),
    )


@admin_router.patch(
    "/curated-sources/{source_id}",
    response_model=CuratedSourceResponse,
    responses={
        200: {"headers": _CATALOG_ETAG_RESPONSE_HEADER},
        412: {"description": "stale source If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_CATALOG_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curated-source.patch")
async def patch_admin_curated_source_route(
    request: Request,
    source_id: UUID,
    body: CuratedSourcePatchRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            command = current_domain_command()
            row = await curated_repo.patch_curated_source_command(
                session,
                source_id=str(source_id),
                expected_revision=expected_revision,
                updates=body.model_dump(exclude_unset=True),
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _source_command_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated source 없음")
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedSourceResponse(
        data=_source_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.delete(
    "/curated-sources/{source_id}",
    response_model=CuratedSourceResponse,
    responses={
        200: {"headers": _CATALOG_ETAG_RESPONSE_HEADER},
        412: {"description": "stale source If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_CATALOG_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curated-source.archive")
async def archive_admin_curated_source_route(
    request: Request,
    source_id: UUID,
    body: CuratedSourceArchiveRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            command = current_domain_command()
            row = await curated_repo.archive_curated_source_command(
                session,
                source_id=str(source_id),
                expected_revision=expected_revision,
                command_id=command.command_id,
                reason_code=body.reason_code,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _source_command_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated source 없음")
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedSourceResponse(
        data=_source_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get(
    "/curated-source-rules",
    response_model=CuratedSourceRulesResponse,
)
async def list_admin_curated_source_rules_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    theme_id: Annotated[UUID | None, Query()] = None,
    theme_slug: Annotated[str | None, Query()] = None,
    source_id: Annotated[UUID | None, Query()] = None,
    provider_dataset_id: Annotated[int | None, Query(gt=0)] = None,
    enabled: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> CuratedSourceRulesResponse:
    started_at = perf_counter()
    rows = await curated_repo.list_curated_source_rules(
        session,
        theme_id=str(theme_id) if theme_id is not None else None,
        theme_slug=theme_slug,
        source_id=str(source_id) if source_id is not None else None,
        provider_dataset_id=provider_dataset_id,
        enabled=enabled,
        limit=limit,
    )
    return CuratedSourceRulesResponse(
        data=CuratedSourceRulesData(items=[_rule_view(row) for row in rows]),
        meta=make_meta(started_at=started_at),
    )


@admin_router.post(
    "/curated-source-rules",
    response_model=CuratedSourceRuleResponse,
    status_code=status.HTTP_201_CREATED,
    responses={201: {"headers": _CATALOG_ETAG_RESPONSE_HEADER}},
)
@idempotent_domain_command("admin.curated-source-rule.create")
async def create_admin_curated_source_rule_route(
    body: CuratedSourceRuleCreateRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceRuleResponse:
    started_at = perf_counter()
    try:
        async with domain_command_transaction(session):
            command = current_domain_command()
            row = await curated_repo.create_curated_source_rule_command(
                session,
                **body.model_dump(mode="json"),
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _rule_command_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedSourceRuleResponse(
        data=_rule_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.get(
    "/curated-source-rules/{rule_id}",
    response_model=CuratedSourceRuleResponse,
    responses={200: {"headers": _CATALOG_ETAG_RESPONSE_HEADER}},
)
async def get_admin_curated_source_rule_route(
    rule_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceRuleResponse:
    started_at = perf_counter()
    row = await curated_repo.get_curated_source_rule(session, rule_id=str(rule_id))
    if row is None:
        raise HTTPException(status_code=404, detail="curated source rule 없음")
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedSourceRuleResponse(
        data=_rule_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.patch(
    "/curated-source-rules/{rule_id}",
    response_model=CuratedSourceRuleResponse,
    responses={
        200: {"headers": _CATALOG_ETAG_RESPONSE_HEADER},
        412: {"description": "stale rule If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_CATALOG_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curated-source-rule.patch")
async def patch_admin_curated_source_rule_route(
    request: Request,
    rule_id: UUID,
    body: CuratedSourceRulePatchRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceRuleResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            command = current_domain_command()
            row = await curated_repo.patch_curated_source_rule_command(
                session,
                rule_id=str(rule_id),
                expected_revision=expected_revision,
                updates=body.model_dump(exclude_unset=True),
                command_id=command.command_id,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _rule_command_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated source rule 없음")
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedSourceRuleResponse(
        data=_rule_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.delete(
    "/curated-source-rules/{rule_id}",
    response_model=CuratedSourceRuleResponse,
    responses={
        200: {"headers": _CATALOG_ETAG_RESPONSE_HEADER},
        412: {"description": "stale rule If-Match"},
        428: {"description": "If-Match 누락"},
    },
    openapi_extra={"parameters": [_CATALOG_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.curated-source-rule.archive")
async def archive_admin_curated_source_rule_route(
    request: Request,
    rule_id: UUID,
    body: CuratedSourceRuleArchiveRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CuratedSourceRuleResponse:
    started_at = perf_counter()
    expected_revision = parse_revision_header(request, "If-Match", required=True)
    assert expected_revision is not None
    try:
        async with domain_command_transaction(session):
            command = current_domain_command()
            row = await curated_repo.archive_curated_source_rule_command(
                session,
                rule_id=str(rule_id),
                expected_revision=expected_revision,
                command_id=command.command_id,
                reason_code=body.reason_code,
                principal=command.actor,
            )
    except DBAPIError as exc:
        raise _rule_command_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="curated source rule 없음")
    response.headers["ETag"] = revision_etag(row.row_revision)
    return CuratedSourceRuleResponse(
        data=_rule_view(row),
        meta=make_meta(started_at=started_at),
    )


@admin_router.post(
    "/curated-source-rules/{rule_id}/apply",
    response_model=RuleApplyResponse,
)
@idempotent_domain_command("admin.curated-source-rule.apply")
async def apply_admin_curated_source_rule_route(
    rule_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RuleApplyResponse:
    started_at = perf_counter()
    async with domain_command_transaction(session):
        result = await curated_repo.apply_curated_source_rule(session, rule_id=rule_id)
    return RuleApplyResponse(
        data=RuleApplyData(
            rule_id=result.rule_id,
            inserted_or_updated=result.inserted_or_updated,
        ),
        meta=make_meta(started_at=started_at),
    )
