"""``/admin/features`` 운영 feature 라우터 (ADR-045 T-207c)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from math import isfinite
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from kortravelmap.dto import EventDetail, PlaceDetail
from kortravelmap.infra import curation_repo, feature_identity, price_repo, weather_repo
from kortravelmap.infra.admin_feature_repo import (
    AdminFeatureDetail,
    AdminFeatureDetailFeature,
    AdminFeatureDetailFile,
    AdminFeatureDetailIssue,
    AdminFeatureDetailOverride,
    AdminFeatureDetailSource,
    AdminFeaturePage,
    AdminFeatureRow,
    AdminFeatureStateConflict,
    AdminFeatureStateNotFound,
    AdminFeatureStatePreconditionFailed,
    AdminFeatureStateTransition,
    AdminFeatureStateTransitionAudit,
    AdminFeatureStateTransitionAuditPage,
    AdminFeatureStateValidationError,
    AdminManualFeatureCreated,
    AdminManualFeatureExactDuplicate,
    AdminManualFeatureIdentityConflict,
    AdminManualFeatureInvariantError,
    AdminManualFeatureValidationError,
    FeatureFieldOverrideCommand,
    FeatureFieldOverrideNotFound,
    FeatureFieldOverridePreconditionFailed,
    FeatureFieldOverrideValidationError,
    admin_feature_card_target_exists,
    admin_features_in_bbox,
    author_admin_feature_field_overrides,
    cluster_admin_features_in_bbox,
    create_admin_feature_with_field_overrides,
    get_admin_feature_detail,
    get_feature_row_revision,
    list_admin_feature_state_transitions,
    list_admin_features,
    patch_admin_feature_with_field_overrides,
    reactivate_admin_feature_state,
    revoke_admin_feature_field_overrides,
    transition_admin_feature_state,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from kortravelmap.api.auth import (
    AdminManualFeatureCreateContext,
    AdminProxyContext,
    require_admin_destructive_enabled,
    require_admin_frontend,
    require_admin_manual_feature_create,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    current_domain_command,
    domain_command_transaction,
    idempotent_domain_command,
)
from kortravelmap.api.feature_ref import resolve_feature_ref_or_error
from kortravelmap.api.http_revision import parse_revision_header, revision_etag
from kortravelmap.api.identity_projection import response_feature_id, uuid_substituted_row
from kortravelmap.api.response import ClusterUnit, Meta, make_meta
from kortravelmap.api.routers.curations import (
    AdminCurationItemView,
    curation_item_response_feature_id,
)
from kortravelmap.api.routers.features import (
    FeaturePriceResponse,
    FeatureWeatherResponse,
    PriceCardData,
    PricePointOut,
    WeatherCardData,
    WeatherMetricOut,
    WeatherSummaryOut,
)

__all__ = [
    "router",
    "AdminFeatureRecord",
    "AdminFeaturesListResponse",
    "AdminFeatureStatePatchRequest",
    "AdminFeatureStateRetireRequest",
    "AdminFeatureReactivateRequest",
    "AdminFeatureStateResponse",
    "AdminFeatureStateTransitionsResponse",
    "AdminFeatureCreateRequest",
    "AdminManualFeatureCanonicalJSONResponse",
    "AdminManualFeatureCreateResponse",
    "AdminFeaturePatchRequest",
]


router = APIRouter(prefix="/admin/features", tags=["admin-features"])

_PHONE_RE = re.compile(r"^\+?[0-9][0-9()\-\s]{6,24}$")
_HTTP_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")

#: kind별 detail 정본 모델 (T-VN-35 — subtype 컬럼 계약과 같은 원천).
_DETAIL_MODEL_BY_KIND: dict[str, type[BaseModel]] = {
    "place": PlaceDetail,
    "event": EventDetail,
}

AdminFeatureSort = Literal[
    "name",
    "updated_at",
    "created_at",
    "kind",
    "provider",
    "issue_count",
]
SortOrder = Literal["asc", "desc"]


class AdminManualFeatureCanonicalJSONResponse(JSONResponse):
    """M01 terminal/replay가 jsonb key order와 무관하게 같은 bytes를 내도록 한다."""

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


class AdminFeatureIssueRecord(BaseModel):
    """Admin feature 목록 issue summary."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str | None = None
    violation_type: str | None = None
    severity: str | None = None
    message: str | None = None
    detected_at: datetime | None = None


class AdminFeatureRecord(BaseModel):
    """``GET /admin/features`` item."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(
        description=(
            "feature 참조 (opaque string). T-VN-32C 값 전환 이후 UUID 정본 "
            "문자열을 담는다 — 형식(legacy f_*/UUID)에 의존하지 말 것."
        ),
    )
    feature_uuid: str | None = Field(
        default=None,
        description=(
            "UUID 정본 identity 명시 필드 (ADR-068). T-VN-32C 이후 "
            "feature_id와 같은 값이다."
        ),
    )
    kind: str
    name: str = Field(min_length=1)
    category: str
    lifecycle_state: Literal["active", "retired"]
    publication_state: Literal["draft", "published", "suppressed"]
    quality_state: Literal["valid", "quarantined"]
    lon: float | None = None
    lat: float | None = None
    address_label: str
    primary_provider: str | None = None
    primary_dataset_key: str | None = None
    issue_count: int
    issues: list[AdminFeatureIssueRecord]
    created_at: datetime
    updated_at: datetime


class AdminFeaturesListData(BaseModel):
    """Admin feature 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[AdminFeatureRecord]


class AdminFeaturesListResponse(BaseModel):
    """``GET /admin/features`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeaturesListData
    meta: Meta


class AdminFeatureMapItem(BaseModel):
    """Admin 지도용 base Feature 경량 표현."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    kind: str
    name: str
    category: str
    lon: float | None
    lat: float | None
    marker_icon: str | None = None
    marker_color: str | None = None
    lifecycle_state: Literal["active", "retired"]
    publication_state: Literal["draft", "published", "suppressed"]
    quality_state: Literal["valid", "quarantined"]
    geometry: dict[str, Any] | None = None
    area_square_meters: float | None = None
    price_summary: list[PricePointOut] | None = None
    weather_summary: WeatherSummaryOut | None = None


class AdminFeatureCluster(BaseModel):
    """Admin base Feature의 canonical 행정구역 rollup."""

    model_config = ConfigDict(extra="forbid")

    cluster_key: str
    feature_count: int
    lon: float
    lat: float


class AdminInBoundsCoverage(BaseModel):
    """Admin in-bounds 결과 상한과 반환 건수."""

    model_config = ConfigDict(extra="forbid")

    returned: int
    limit: int


class AdminFeaturesInBoundsData(BaseModel):
    """Admin 지도 item/cluster envelope data."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["items", "clusters"]
    items: list[AdminFeatureMapItem]
    clusters: list[AdminFeatureCluster]
    truncated: bool
    coverage: AdminInBoundsCoverage


class AdminFeaturesInBoundsResponse(BaseModel):
    """``GET /admin/features/in-bounds`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeaturesInBoundsData
    meta: Meta


class AdminFeatureStatePatchRequest(BaseModel):
    """공개 의도·품질을 원자적으로 바꾸는 상태 command.

    lifecycle는 provider 재등장과 typed override가 얽힌 별도 재활성 command만
    바꿀 수 있다. retire와 축 patch를 한 요청에 섞으면 audit tuple의 의미가
    불명확해지므로 discriminated union으로 물리적으로 막는다.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["patch"]
    publication_state: Literal["draft", "published", "suppressed"] | None = None
    quality_state: Literal["valid", "quarantined"] | None = None
    reason_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def _requires_axis(self) -> AdminFeatureStatePatchRequest:
        if self.publication_state is None and self.quality_state is None:
            raise ValueError("state patch에는 publication_state 또는 quality_state가 필요합니다.")
        return self


class AdminFeatureStateRetireRequest(BaseModel):
    """lifecycle retire와 publication suppress를 한 DB command로 묶는 요청."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["retire"]
    reason_code: str = Field(min_length=1)


class AdminFeatureReactivateRequest(BaseModel):
    """retired lifecycle override를 해제할 현재 provider evidence.

    재활성화는 임의의 ``active`` patch가 아니다. provider dataset/head/link를 모두
    검증한 단일 명령만 lifecycle를 active로 되돌릴 수 있다.
    """

    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1)
    provider_dataset_id: int = Field(ge=1)
    source_entity_key: str = Field(min_length=1)
    source_record_key: str = Field(min_length=1)


AdminFeatureStateRequest = Annotated[
    AdminFeatureStatePatchRequest | AdminFeatureStateRetireRequest,
    Body(discriminator="action"),
]


async def require_destructive_enabled_for_retire(request: Request) -> None:
    """retire action에만 파괴적 admin kill-switch를 건다.

    T-VN-34 이전에는 이 동작이 전용 라우트(``POST /{feature_id}/deactivate``)였고
    그 라우트가 ``require_admin_destructive_enabled``를 **route-level dependency**로
    걸었다. 상태 전이가 한 라우트로 합쳐지면서 게이트가 사라졌는데(회귀), 라우트
    전체에 다시 걸면 무해한 publication/quality patch까지 403이 된다.

    **핸들러 안에서 검사하면 안 된다** — endpoint 파라미터 의존성(``get_session``)이
    먼저 해석돼 DB에 붙는다. kill-switch는 DB가 없어도 성립해야 하므로 body만 보는
    route-level dependency로 둔다. body는 Starlette가 캐시하므로 이후 파싱과
    중복 읽기가 되지 않는다.
    """

    try:
        payload = await request.json()
    except ValueError:
        return  # 형식 오류는 아래 body 검증이 422로 처리한다.
    if isinstance(payload, dict) and payload.get("action") == "retire":
        require_admin_destructive_enabled(request)


class AdminFeatureStateData(BaseModel):
    """한 상태 명령의 commit 후 full tuple + immutable audit identity."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    lifecycle_state: Literal["active", "retired"]
    publication_state: Literal["draft", "published", "suppressed"]
    quality_state: Literal["valid", "quarantined"]
    row_revision: int = Field(ge=1)
    audit_transition_id: int


class AdminFeatureStateResponse(BaseModel):
    """``PATCH /admin/features/{feature_id}/state`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureStateData
    meta: Meta


class AdminFeatureFieldOverrideAuthorRequest(BaseModel):
    """registry allow-list에 등록된 scalar/geometry effective field 변경.

    path별 value kind·Feature kind·nullability는 runtime dictionary가 아니라 DB
    registry가 검증한다. API는 JSON transport 형태만 검증하고 임의 SQL 식별자나
    legacy whole-row payload를 받지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1)
    values: dict[str, Any] = Field(default_factory=dict)
    geometry_wkt: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _requires_distinct_paths(self) -> AdminFeatureFieldOverrideAuthorRequest:
        if not self.values and not self.geometry_wkt:
            raise ValueError("field override에는 적어도 하나의 field 값이 필요합니다.")
        overlap = set(self.values) & set(self.geometry_wkt)
        if overlap:
            raise ValueError(
                "scalar와 geometry field path는 겹칠 수 없습니다: "
                + ", ".join(sorted(overlap))
            )
        if any(not path.strip() for path in {*self.values, *self.geometry_wkt}):
            raise ValueError("field_path는 비어 있을 수 없습니다.")
        return self


class AdminFeatureFieldOverrideRevokeRequest(BaseModel):
    """active override를 latest typed provider base로 복원하는 command."""

    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1)
    field_paths: list[str] = Field(min_length=1)

    @field_validator("field_paths")
    @classmethod
    def _validate_field_paths(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("field_paths는 중복 없는 비어 있지 않은 path 목록이어야 합니다.")
        return normalized


class AdminFeatureFieldOverrideData(BaseModel):
    """author/revoke typed procedure의 commit receipt."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    row_revision: int = Field(ge=1)
    command_id: int = Field(ge=1)
    applied_field_count: int = Field(ge=1)


class AdminFeatureFieldOverrideResponse(BaseModel):
    """``POST /admin/features/{feature_id}/field-overrides*`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureFieldOverrideData
    meta: Meta


class AdminManualFeatureCreateData(BaseModel):
    """검증된 수동 Feature 생성 command의 commit receipt."""

    model_config = ConfigDict(extra="forbid")

    feature_id: UUID
    creation_origin: Literal["manual_admin"]
    row_revision: int = Field(ge=1)
    command_id: int = Field(ge=1)
    applied_field_count: int = Field(ge=1)


class AdminManualFeatureCreateResponse(BaseModel):
    """``POST /admin/features``의 manual-v1 성공 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminManualFeatureCreateData
    meta: Meta


class AdminFeatureCoordInput(BaseModel):
    """Feature mutation 좌표 입력."""

    model_config = ConfigDict(extra="forbid")

    lon: float = Field(ge=124.0, le=132.0)
    lat: float = Field(ge=33.0, le=39.5)


class AdminManualFeatureCreateCoordInput(AdminFeatureCoordInput):
    """수동 생성에서만 coercion과 non-finite 값을 거부하는 좌표 입력."""

    @field_validator("lon", "lat", mode="before")
    @classmethod
    def _require_finite_json_number(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("좌표는 JSON number여야 합니다.")
        if not isfinite(float(value)):
            raise ValueError("좌표는 finite JSON number여야 합니다.")
        return value


class AdminFeatureBaseMutation(BaseModel):
    """place/event feature 추가·수정 공통 입력."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, pattern=r"^\d{8}$")
    coord: AdminFeatureCoordInput | None = None
    coord_precision_digits: int | None = Field(default=None, ge=3, le=8)
    # ``geom``은 받지 않는다 — admin mutation은 place/event만 다루고, geometry
    # 정본은 route/area subtype뿐이다(ADR-086). 종전엔 필드를 받아 change
    # request payload에 넣기까지 했지만 적용 단계에서 **아무 데도 쓰지 않았다** —
    # 받아 놓고 버리는 필드는 계약이 아니라 거짓말이다.
    address: dict[str, Any] | None = None
    legal_dong_code: str | None = Field(default=None, pattern=r"^\d{10}$")
    road_name_code: str | None = Field(default=None, pattern=r"^\d{7,12}$")
    road_address_management_no: str | None = Field(
        default=None,
        pattern=r"^\d{20,26}$",
    )
    admin_dong_code: str | None = Field(default=None, pattern=r"^\d{7,10}$")
    sido_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    sigungu_code: str | None = Field(default=None, pattern=r"^\d{5}$")
    urls: dict[str, Any] | None = None
    marker_icon: str | None = Field(default=None, min_length=1)
    marker_color: str | None = Field(default=None, pattern=r"^P-(0[1-9]|1[0-6])$")
    parent_feature_id: str | None = None
    sibling_group_id: str | None = None
    detail: dict[str, Any] | None = None

    @field_validator("urls")
    @classmethod
    def _validate_urls(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if not value:
            return value
        for key in ("homepage", "source"):
            raw = value.get(key)
            if raw is None or raw == "":
                continue
            if not isinstance(raw, str) or not _HTTP_URL_RE.match(raw):
                raise ValueError(f"urls.{key}는 http(s) URL이어야 합니다.")
        return value

    @field_validator("detail")
    @classmethod
    def _validate_detail(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if not value:
            return value
        phone = value.get("phone")
        if phone not in (None, "") and (
            not isinstance(phone, str) or not _PHONE_RE.match(phone)
        ):
            raise ValueError("detail.phone은 전화번호 형식이어야 합니다.")
        for key in ("starts_at", "ends_at"):
            raw = value.get(key)
            if raw in (None, ""):
                continue
            if not isinstance(raw, str):
                raise ValueError(f"detail.{key}는 ISO datetime 문자열이어야 합니다.")
            try:
                datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    f"detail.{key}는 ISO datetime 문자열이어야 합니다."
                ) from exc
        return value


_DETAIL_VALIDATION_PLACEHOLDER_ID = "f_validation_placeholder"


def _reject_detail_not_matching_kind(kind: str, detail: dict[str, Any] | None) -> None:
    """detail이 kind 계약에 맞는지 **경계에서 미리** 확인한다 (T-VN-35, ADR-086).

    정본 판정은 write 경계(``feature_subtype.subtype_params``)가 갖는다 — 여기서
    값을 고쳐 넣지 않는 이유가 그것이다. 종전 구현은 정규화한 detail을
    ``object.__setattr__``로 되꽂았는데, 그건 pydantic의 ``__pydantic_fields_set__``
    을 건드리지 않아 뒤이은 ``model_dump(exclude_unset=True)``에서 **통째로
    빠졌다** — 즉 정규화가 실제로는 한 번도 payload에 반영되지 않았다.

    이 함수의 값어치는 다른 데 있다: 검토(review) 모드에서 잘못된 detail이
    **접수될 때** 422로 막힌다는 것. 그러지 않으면 승인 시점에야 터져서 그
    change request는 영구히 승인 불가가 된다.
    """
    model = _DETAIL_MODEL_BY_KIND.get(kind)
    if model is None:
        return
    payload = dict(detail or {})
    payload.setdefault("feature_id", _DETAIL_VALIDATION_PLACEHOLDER_ID)
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"detail이 kind={kind} 계약과 맞지 않습니다: {exc}") from exc


# ``detail``은 kind별 typed subtype으로 저장되므로(T-VN-35, ADR-086) 생성
# 요청은 DTO 정본으로 검증·정규화한다 — 계약 문서에 내부 근거를 싣지 않도록
# docstring이 아니라 여기 주석으로 남긴다.
class AdminFeatureCreateRequest(AdminFeatureBaseMutation):
    """``POST /admin/features`` body.

    ``detail``은 kind 계약(place/event)에 맞아야 한다 — DTO에 없는 키는
    거부되므로 provider 원문은 ``detail.payload`` 아래 둔다. 생략하면 kind
    기본값으로 채운다. 맞지 않으면 422다.
    """

    kind: Literal["place", "event"]
    # exact-key NFKC/trim 뒤의 1..200자·UTF-8 512 byte 제한은 DB named
    # validation이 판정한다. raw 값의 앞뒤 공백은 저장 입력으로 보존하므로 여기서
    # raw 길이를 재면 정상화 뒤 유효한 값을 과도하게 거부한다.
    name: str
    category: str = Field(pattern=r"^\d{8}$")
    coord: AdminManualFeatureCreateCoordInput
    marker_icon: str = Field(min_length=1)
    marker_color: str = Field(pattern=r"^P-(0[1-9]|1[0-6])$")
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _detail_matches_kind(self) -> AdminFeatureCreateRequest:
        # detail 미전송도 허용한다 — write 경계가 DTO 기본값으로 채운다.
        _reject_detail_not_matching_kind(self.kind, self.detail)
        return self


class AdminFeaturePatchRequest(AdminFeatureBaseMutation):
    """``PATCH /admin/features/{feature_id}`` body."""

    reason: str = Field(min_length=1)
    operator: str | None = Field(
        default=None,
        deprecated=True,
        description=(
            "[deprecated·ignored] 감사 actor는 인증 principal에서만 파생한다 "
            "(ADR-066 D-2, T-VN-20). PinVi 호환을 위해 수용하되 값은 무시하며, "
            "PinVi는 전송 중단 예정 (docs/integration-map.md)."
        ),
    )

    @model_validator(mode="after")
    def _at_least_one_patch_field(self) -> AdminFeaturePatchRequest:
        values = self.model_dump(exclude={"reason", "operator"}, exclude_unset=True)
        if not values:
            raise ValueError("수정할 feature field가 1개 이상 필요")
        return self


class AdminFeatureDeleteRequest(BaseModel):
    """``DELETE /admin/features/{feature_id}`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    operator: str | None = Field(
        default=None,
        deprecated=True,
        description=(
            "[deprecated·ignored] 감사 actor는 인증 principal에서만 파생한다 "
            "(ADR-066 D-2, T-VN-20). PinVi 호환을 위해 수용하되 값은 무시하며, "
            "PinVi는 전송 중단 예정 (docs/integration-map.md)."
        ),
    )


class AdminFeatureDetailFeatureRecord(BaseModel):
    """Admin feature 상세 core snapshot."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(
        description=(
            "feature 참조 (opaque string). T-VN-32C 값 전환 이후 UUID 정본 "
            "문자열을 담는다 — 형식(legacy f_*/UUID)에 의존하지 말 것."
        ),
    )
    feature_uuid: str | None = Field(
        default=None,
        description=(
            "UUID 정본 identity 명시 필드 (ADR-068). T-VN-32C 이후 "
            "feature_id와 같은 값이다."
        ),
    )
    kind: str
    name: str
    category: str
    lifecycle_state: Literal["active", "retired"]
    publication_state: Literal["draft", "published", "suppressed"]
    quality_state: Literal["valid", "quarantined"]
    lon: float | None = None
    lat: float | None = None
    coord_precision_digits: int | None = None
    area_square_meters: float | None = None
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    raw_refs: list[dict[str, Any]]
    legal_dong_code: str | None = None
    road_name_code: str | None = None
    road_address_management_no: str | None = None
    admin_dong_code: str | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    marker_icon: str | None = None
    marker_color: str | None = None
    parent_feature_id: str | None = None
    sibling_group_id: str | None = None
    row_revision: int = Field(
        ge=1,
        description="correction If-Match에 사용할 server-owned revision.",
    )
    created_at: datetime
    updated_at: datetime


class AdminFeatureDetailSourceRecord(BaseModel):
    """Admin feature 상세 source/link row."""

    model_config = ConfigDict(extra="forbid")

    source_entity_key: str
    source_record_key: str
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    source_role: str
    match_method: str
    confidence: int
    raw_payload_hash: str
    raw_data: dict[str, Any]
    fetched_at: datetime
    imported_at: datetime
    observed_at: datetime
    expires_at: datetime | None = None
    linked_at: datetime


class AdminFeatureDetailIssueRecord(BaseModel):
    """Admin feature 상세 issue row."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str
    provider: str | None = None
    dataset_key: str | None = None
    source_record_key: str | None = None
    violation_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    status: str
    detected_at: datetime
    resolved_at: datetime | None = None


class AdminFeatureDetailOverrideRecord(BaseModel):
    """Admin feature 상세 override row."""

    model_config = ConfigDict(extra="forbid")

    override_id: str
    source_record_key: str | None = None
    field_path: str
    source_value: Any
    override_value: Any
    prevent_provider_reactivation: bool
    status: str
    reason: str | None = None
    created_by: str | None = None
    created_at: datetime


class AdminFeatureStateTransitionAuditRecord(BaseModel):
    """DB append-only Feature 상태 전이 감사 1건.

    admin detail은 현재 tuple과 이 timeline을 함께 주므로 운영 화면이 합성된
    legacy status를 추론할 필요가 없다.
    """

    model_config = ConfigDict(extra="forbid")

    transition_id: int
    from_lifecycle_state: Literal["active", "retired"] | None = None
    from_publication_state: Literal["draft", "published", "suppressed"] | None = None
    from_quality_state: Literal["valid", "quarantined"] | None = None
    to_lifecycle_state: Literal["active", "retired"]
    to_publication_state: Literal["draft", "published", "suppressed"]
    to_quality_state: Literal["valid", "quarantined"]
    transition_kind: str
    reason_code: str
    principal: str
    causation_ref: str | None = None
    provider_dataset_id: int | None = None
    source_entity_key: str | None = None
    source_record_key: str | None = None
    occurred_at: datetime
    row_revision: int = Field(ge=1)


class AdminFeatureStateTransitionsData(BaseModel):
    """feature별 append-only state audit keyset page."""

    model_config = ConfigDict(extra="forbid")

    items: list[AdminFeatureStateTransitionAuditRecord]


class AdminFeatureStateTransitionsResponse(BaseModel):
    """``GET /admin/features/{feature_id}/state/transitions`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureStateTransitionsData
    meta: Meta


class AdminFeatureDetailFileRecord(BaseModel):
    """Admin feature 상세 file metadata row."""

    model_config = ConfigDict(extra="forbid")

    file_id: str
    file_type: str
    storage_backend: str
    bucket: str
    object_key: str
    source_url: str | None = None
    public_url: str | None = None
    content_type: str | None = None
    byte_size: int | None = None
    checksum_sha256: str | None = None
    width: int | None = None
    height: int | None = None
    role: str
    display_order: int
    alt_text: str | None = None
    provider: str | None = None
    dataset_key: str | None = None
    source_record_key: str | None = None
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AdminFeatureDetailData(BaseModel):
    """``GET /admin/features/{feature_id}`` data."""

    model_config = ConfigDict(extra="forbid")

    feature: AdminFeatureDetailFeatureRecord
    sources: list[AdminFeatureDetailSourceRecord]
    issues: list[AdminFeatureDetailIssueRecord]
    overrides: list[AdminFeatureDetailOverrideRecord]
    state_transitions: list[AdminFeatureStateTransitionAuditRecord]
    files: list[AdminFeatureDetailFileRecord]
    curations: list[AdminCurationItemView]


class AdminFeatureDetailResponse(BaseModel):
    """``GET /admin/features/{feature_id}`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureDetailData
    meta: Meta


class AdminFeatureRevisionData(BaseModel):
    """correction precondition용 feature core revision snapshot."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    row_revision: int = Field(ge=1)


class AdminFeatureRevisionResponse(BaseModel):
    """동적 aggregate를 제외한 stable revision representation."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureRevisionData


def _issue_record(issue: dict[str, Any]) -> AdminFeatureIssueRecord:
    return AdminFeatureIssueRecord(
        issue_id=issue.get("issue_id"),
        violation_type=issue.get("violation_type"),
        severity=issue.get("severity"),
        message=issue.get("message"),
        detected_at=issue.get("detected_at"),
    )


def _record(row: AdminFeatureRow) -> AdminFeatureRecord:
    # T-VN-32C PR-2 — 응답 feature_id 값은 UUID 정본. 목록 cursor는 repo가 치환
    # 전 legacy 축으로 encode한다 (sort keyset 무변경).
    return AdminFeatureRecord(
        feature_id=response_feature_id(row),
        feature_uuid=row.feature_uuid,
        kind=row.kind,
        name=row.name,
        category=row.category,
        lifecycle_state=row.lifecycle_state,
        publication_state=row.publication_state,
        quality_state=row.quality_state,
        lon=row.lon,
        lat=row.lat,
        address_label=row.address_label,
        primary_provider=row.primary_provider,
        primary_dataset_key=row.primary_dataset_key,
        issue_count=row.issue_count,
        issues=[_issue_record(issue) for issue in row.issues],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _map_item(row: dict[str, Any]) -> AdminFeatureMapItem:
    """지도 item 조립 — 응답 feature_id를 UUID 정본으로 치환한다 (T-VN-32C PR-2).

    ``AdminFeatureMapItem``은 경량 표현이라 ``feature_uuid`` 병행 필드를 두지
    않는다(feature_id와 같은 값) — projection 보조 컬럼은 splat 전에 뺀다.
    """
    substituted = uuid_substituted_row(row)
    substituted.pop("feature_uuid", None)
    return AdminFeatureMapItem(**substituted)


def _detail_feature(
    row: AdminFeatureDetailFeature,
) -> AdminFeatureDetailFeatureRecord:
    # T-VN-32C PR-2 — feature record의 응답 feature_id만 UUID 정본으로 치환.
    # parent_feature_id/sibling_group_id는 2차 참조라 legacy 유지 (PR-2 범위 밖).
    record = AdminFeatureDetailFeatureRecord.model_validate(row, from_attributes=True)
    return record.model_copy(update={"feature_id": response_feature_id(row)})


def _detail_source(row: AdminFeatureDetailSource) -> AdminFeatureDetailSourceRecord:
    return AdminFeatureDetailSourceRecord.model_validate(row, from_attributes=True)


def _detail_issue(row: AdminFeatureDetailIssue) -> AdminFeatureDetailIssueRecord:
    return AdminFeatureDetailIssueRecord.model_validate(row, from_attributes=True)


def _detail_override(
    row: AdminFeatureDetailOverride,
) -> AdminFeatureDetailOverrideRecord:
    return AdminFeatureDetailOverrideRecord.model_validate(row, from_attributes=True)


def _state_transition_audit(
    row: AdminFeatureStateTransitionAudit,
) -> AdminFeatureStateTransitionAuditRecord:
    return AdminFeatureStateTransitionAuditRecord.model_validate(
        row,
        from_attributes=True,
    )


def _detail_file(row: AdminFeatureDetailFile) -> AdminFeatureDetailFileRecord:
    return AdminFeatureDetailFileRecord.model_validate(row, from_attributes=True)


def _detail_response(
    row: AdminFeatureDetail,
    *,
    started_at: float,
    curations: tuple[curation_repo.CurationItem, ...] = (),
) -> AdminFeatureDetailResponse:
    # T-VN-32C — feature record·curation item의 응답 feature 참조만 UUID 치환.
    # sources/issues/overrides/files/state transition 레코드의 feature_id는
    # 내부 DB 참조(감사·lineage 레코드)라 legacy 유지.
    return AdminFeatureDetailResponse(
        data=AdminFeatureDetailData(
            feature=_detail_feature(row.feature),
            sources=[_detail_source(item) for item in row.sources],
            issues=[_detail_issue(item) for item in row.issues],
            overrides=[_detail_override(item) for item in row.overrides],
            state_transitions=[
                _state_transition_audit(item) for item in row.state_transitions
            ],
            files=[_detail_file(item) for item in row.files],
            curations=[
                AdminCurationItemView.model_validate(
                    item, from_attributes=True
                ).model_copy(
                    update={"feature_id": curation_item_response_feature_id(item)}
                )
                for item in curations
            ],
        ),
        meta=make_meta(started_at=started_at),
    )


def _payload(body: AdminFeatureBaseMutation) -> dict[str, Any]:
    raw = body.model_dump(
        exclude={"reason", "operator", "idempotency_key"},
        exclude_unset=True,
    )
    coord = raw.get("coord")
    if isinstance(coord, dict):
        raw["coord"] = {"lon": coord["lon"], "lat": coord["lat"]}
    return raw


def _manual_feature_create_validation_error(
    *,
    field: str,
    constraint: str | None = None,
) -> HTTPException:
    """수동 생성의 Python/DB validation을 한 안정된 problem detail로 합친다."""

    details: dict[str, Any] = {
        "errors": [
            {
                "field": field,
                "message": "요청 값이 수동 Feature 생성 계약과 맞지 않습니다.",
            }
        ]
    }
    if constraint is not None:
        details["constraint"] = constraint
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "VALIDATION_ERROR",
            "message": "수동 Feature 생성 요청 값이 올바르지 않습니다.",
            "details": details,
        },
    )


def _manual_feature_create_internal_error() -> HTTPException:
    """M01 내부/미분류 DB fault를 driver 세부 정보 없이 공개한다."""

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "INTERNAL_SERVER_ERROR",
            "message": "수동 Feature 생성 중 내부 오류가 발생했습니다.",
            "details": {},
        },
    )


async def _resolve_mutation_identity_refs(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    manual_create: bool = False,
) -> None:
    """mutation payload의 feature 참조를 legacy 정본 키로 해석한다 (T-VN-32C PR-2).

    값 전환 후 admin 프론트가 응답에서 복사한 UUID를 body로 되돌린다 — 해석
    없이는 legacy FK 컬럼이 조용히 오염되거나(W2: IntegrityError 500 지연
    폭발), UUID 타입 컬럼은 형식 검증을 통과해 버린다(W3). payload를 제자리
    수정한다.
    """
    parent = payload.get("parent_feature_id")
    if parent is not None:
        try:
            identity = await feature_identity.resolve_feature_identity(session, parent)
        except feature_identity.FeatureIdentityRefError as exc:
            if manual_create:
                raise AdminManualFeatureValidationError(
                    field="parent_feature_id"
                ) from exc
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if identity is None:
            if manual_create:
                raise AdminManualFeatureValidationError(field="parent_feature_id")
            raise HTTPException(
                status_code=422,
                detail=f"parent_feature_id를 해석할 수 없습니다: {parent!r}",
            )
        payload["parent_feature_id"] = identity.feature_id
    sibling = payload.get("sibling_group_id")
    if sibling is not None and await feature_identity.feature_uuid_in_use(
        session, sibling
    ):
        if manual_create:
            raise AdminManualFeatureValidationError(field="sibling_group_id")
        raise HTTPException(
            status_code=422,
            detail=(
                "sibling_group_id가 feature UUID 정본과 충돌합니다 — feature "
                "참조가 아니라 sibling group 식별자를 전달해야 합니다."
            ),
        )


# ── If-Match row-revision 낙관적 동시성 (T-VN-13, D-10-3) ─────────────────────
def _set_feature_etag(response: Response, revision: int) -> None:
    response.headers["ETag"] = revision_etag(revision)


def _state_response(
    row: AdminFeatureStateTransition,
    *,
    feature_id: str,
    started_at: float,
) -> AdminFeatureStateResponse:
    """DB procedure 결과를 HTTP state command receipt로 고정한다."""
    return AdminFeatureStateResponse(
        data=AdminFeatureStateData(
            feature_id=feature_id,
            lifecycle_state=row.lifecycle_state,
            publication_state=row.publication_state,
            quality_state=row.quality_state,
            row_revision=row.row_revision,
            audit_transition_id=row.audit_transition_id,
        ),
        meta=make_meta(started_at=started_at),
    )


def _field_override_response(
    row: FeatureFieldOverrideCommand,
    *,
    feature_id: str,
    started_at: float,
) -> AdminFeatureFieldOverrideResponse:
    """typed override procedure receipt를 public command response로 고정한다."""

    return AdminFeatureFieldOverrideResponse(
        data=AdminFeatureFieldOverrideData(
            feature_id=feature_id,
            row_revision=row.row_revision,
            command_id=row.command_id,
            applied_field_count=row.applied_field_count,
        ),
        meta=make_meta(started_at=started_at),
    )


def _manual_feature_create_response(
    row: AdminManualFeatureCreated,
    *,
    started_at: float,
) -> AdminManualFeatureCreateResponse:
    """수동 생성 commit receipt를 UUID-only HTTP 응답으로 고정한다."""

    return AdminManualFeatureCreateResponse(
        data=AdminManualFeatureCreateData(
            feature_id=UUID(row.feature_uuid),
            creation_origin=row.creation_origin,
            row_revision=row.row_revision,
            command_id=row.command_id,
            applied_field_count=row.applied_field_count,
        ),
        meta=make_meta(started_at=started_at),
    )


def _require_if_match_revision(request: Request) -> int:
    """correction 요청의 ``If-Match``를 row_revision으로 파싱한다.

    누락 → 428, 정확히 한 physical header line의 canonical strong ETag가 아니면
    → 422. bare/weak/wildcard/list/0/선행 0/BIGINT 초과는 모두 거부한다.
    """
    revision = parse_revision_header(request, "If-Match", required=True)
    assert revision is not None
    return revision


def _state_precondition_failed(
    exc: AdminFeatureStatePreconditionFailed,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail={
            "code": "PRECONDITION_FAILED",
            "message": (
                "If-Match row_revision이 현재 feature 행과 다릅니다: "
                f"expected={exc.expected}."
            ),
        },
    )


_ETAG_RESPONSE_HEADER = {
    "ETag": {
        "description": "현재 feature의 server-owned row_revision strong entity tag.",
        "schema": {"type": "string"},
    }
}
_MANUAL_CREATE_RESPONSE_HEADERS = {
    **_ETAG_RESPONSE_HEADER,
    "Location": {
        "description": "생성된 canonical UUID Feature의 상대 admin URI.",
        "schema": {"type": "string"},
    },
    "X-Request-ID": {
        "description": (
            "최초 실행의 요청 ID. exact replay도 최초 요청과 같은 값을 반환한다."
        ),
        "schema": {"type": "string"},
    },
    "Idempotency-Replayed": {
        "description": "exact Idempotency-Key replay일 때만 `true`.",
        "schema": {"type": "string", "enum": ["true"]},
    },
}
_IF_MATCH_OPENAPI_PARAMETER = {
    "name": "If-Match",
    "in": "header",
    "required": True,
    "description": "직전 GET body/ETag의 row_revision strong ETag (correction 낙관적 동시성).",
    "schema": {"type": "string"},
}
_ADMIN_CLUSTER_DRILL_DOWN: dict[ClusterUnit, ClusterUnit | None] = {
    "sido": "sigungu",
    "sigungu": "eupmyeondong",
    "eupmyeondong": None,
}


def _resolve_admin_cluster_unit(
    cluster_unit: ClusterUnit | None,
    zoom: int | None,
) -> ClusterUnit | None:
    if cluster_unit is not None:
        return cluster_unit
    if zoom is None or zoom >= 14:
        return None
    if zoom <= 7:
        return "sido"
    if zoom <= 10:
        return "sigungu"
    return "eupmyeondong"


async def _admin_feature_exists_or_404(
    session: AsyncSession,
    feature_id: str,
) -> None:
    if not await admin_feature_card_target_exists(session, feature_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )


@router.get(
    "/in-bounds",
    response_model=AdminFeaturesInBoundsResponse,
    summary="Admin bbox 안 base Feature item/cluster",
)
async def list_admin_features_in_bounds(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    min_lon: Annotated[float, Query(description="bbox 최소 경도 (WGS84).")],
    min_lat: Annotated[float, Query(description="bbox 최소 위도.")],
    max_lon: Annotated[float, Query(description="bbox 최대 경도.")],
    max_lat: Annotated[float, Query(description="bbox 최대 위도.")],
    lifecycle_filter: Annotated[
        list[Literal["active", "retired"]] | None,
        Query(alias="lifecycle_state", description="lifecycle 축 반복 필터."),
    ] = None,
    publication_filter: Annotated[
        list[Literal["draft", "published", "suppressed"]] | None,
        Query(alias="publication_state", description="publication 축 반복 필터."),
    ] = None,
    quality_filter: Annotated[
        list[Literal["valid", "quarantined"]] | None,
        Query(alias="quality_state", description="quality 축 반복 필터."),
    ] = None,
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터.")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터."),
    ] = None,
    provider: Annotated[
        list[str] | None,
        Query(description="primary provider 반복 필터."),
    ] = None,
    zoom: Annotated[int | None, Query(ge=0, le=24)] = None,
    cluster_unit: Annotated[ClusterUnit | None, Query()] = None,
    max_items: Annotated[int, Query(ge=1, le=2000)] = 1000,
    include_geometry: Annotated[
        bool,
        Query(description="item mode에서 route/area GeoJSON을 포함한다."),
    ] = False,
) -> AdminFeaturesInBoundsResponse:
    started_at = perf_counter()
    if min_lon > max_lon or min_lat > max_lat:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="bbox min 좌표가 max보다 큽니다.",
        )
    resolved_unit = _resolve_admin_cluster_unit(cluster_unit, zoom)
    try:
        if resolved_unit is not None:
            raw_clusters = await cluster_admin_features_in_bbox(
                session,
                min_lon=min_lon,
                min_lat=min_lat,
                max_lon=max_lon,
                max_lat=max_lat,
                cluster_unit=resolved_unit,
                lifecycle_states=lifecycle_filter,
                publication_states=publication_filter,
                quality_states=quality_filter,
                kinds=kind,
                categories=category,
                providers=provider,
                limit=max_items + 1,
            )
            truncated = len(raw_clusters) > max_items
            # cluster row에는 feature_id가 없어 T-VN-32C 치환 대상이 아니다.
            clusters = [
                AdminFeatureCluster(**row) for row in raw_clusters[:max_items]
            ]
            return AdminFeaturesInBoundsResponse(
                data=AdminFeaturesInBoundsData(
                    mode="clusters",
                    items=[],
                    clusters=clusters,
                    truncated=truncated,
                    coverage=AdminInBoundsCoverage(
                        returned=len(clusters),
                        limit=max_items,
                    ),
                ),
                meta=make_meta(
                    request,
                    started_at=started_at,
                    cluster_unit=resolved_unit,
                    cluster_drill_down_unit=_ADMIN_CLUSTER_DRILL_DOWN[resolved_unit],
                ),
            )
        raw_items = await admin_features_in_bbox(
            session,
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            lifecycle_states=lifecycle_filter,
            publication_states=publication_filter,
            quality_states=quality_filter,
            kinds=kind,
            categories=category,
            providers=provider,
            include_geometry=include_geometry,
            limit=max_items + 1,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    truncated = len(raw_items) > max_items
    items = [_map_item(row) for row in raw_items[:max_items]]
    return AdminFeaturesInBoundsResponse(
        data=AdminFeaturesInBoundsData(
            mode="items",
            items=items,
            clusters=[],
            truncated=truncated,
            coverage=AdminInBoundsCoverage(returned=len(items), limit=max_items),
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get(
    "/{feature_id}/weather",
    response_model=FeatureWeatherResponse,
    summary="Admin feature weather card",
    responses={404: {"description": "feature 없음"}},
)
async def get_admin_feature_weather(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    feature_id: str,
) -> FeatureWeatherResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    await _admin_feature_exists_or_404(session, canonical_id)
    card = await weather_repo.build_admin_weather_card(
        session,
        feature_id=canonical_id,
    )
    return FeatureWeatherResponse(
        data=WeatherCardData(
            # T-VN-32C PR-2 — 단건 card 응답의 feature_id는 UUID 정본
            # (features.py 단건 card와 동일 규약; repo 내부 조회는 legacy 축).
            feature_id=identity.feature_uuid,
            source_styles=card.source_styles,
            metrics=[
                WeatherMetricOut.model_validate(metric, from_attributes=True)
                for metric in card.metrics
            ],
            latest_at=card.latest_at,
            is_stale=card.is_stale,
            selected_at=card.selected_at,
            refresh_after=card.refresh_after,
        ),
        meta=make_meta(request, started_at=started_at),
    )


@router.get(
    "/{feature_id}/price",
    response_model=FeaturePriceResponse,
    summary="Admin feature price card",
    responses={404: {"description": "feature 없음"}},
)
async def get_admin_feature_price(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    feature_id: str,
    history_limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> FeaturePriceResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    await _admin_feature_exists_or_404(session, canonical_id)
    card = await price_repo.build_price_card(
        session,
        feature_id=canonical_id,
        history_limit=history_limit,
    )
    return FeaturePriceResponse(
        data=PriceCardData(
            # T-VN-32C PR-2 — 단건 card 응답의 feature_id는 UUID 정본
            # (features.py 단건 card와 동일 규약; repo 내부 조회는 legacy 축).
            feature_id=identity.feature_uuid,
            current=[
                PricePointOut.model_validate(point, from_attributes=True)
                for point in card.current
            ],
            history=[
                PricePointOut.model_validate(point, from_attributes=True)
                for point in card.history
            ],
            latest_at=card.latest_at,
            is_stale=card.is_stale,
        ),
        meta=make_meta(request, started_at=started_at),
    )
@router.get("", response_model=AdminFeaturesListResponse)
async def list_features(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(description="name/address/feature/source 검색")] = None,
    kind: Annotated[list[str] | None, Query(description="feature kind 반복 필터")] = None,
    category: Annotated[
        list[str] | None,
        Query(description="category code 반복 필터"),
    ] = None,
    lifecycle_filter: Annotated[
        list[Literal["active", "retired"]] | None,
        Query(alias="lifecycle_state", description="lifecycle 축 반복 필터."),
    ] = None,
    publication_filter: Annotated[
        list[Literal["draft", "published", "suppressed"]] | None,
        Query(alias="publication_state", description="publication 축 반복 필터."),
    ] = None,
    quality_filter: Annotated[
        list[Literal["valid", "quarantined"]] | None,
        Query(alias="quality_state", description="quality 축 반복 필터."),
    ] = None,
    provider_dataset_id: Annotated[
        int | None,
        Query(ge=1, description="primary provider dataset canonical ID 필터"),
    ] = None,
    has_coord: Annotated[bool | None, Query()] = None,
    has_issue: Annotated[bool | None, Query()] = None,
    issue_type: Annotated[list[str] | None, Query()] = None,
    updated_from: Annotated[datetime | None, Query()] = None,
    updated_to: Annotated[datetime | None, Query()] = None,
    include_ended: Annotated[
        bool,
        Query(
            description="종료된 notice(수집 feed 소멸·해제로 valid_end_time 채워진 것) 포함 여부. "
            "기본 false — 수집에 없는 notice는 과거 자료로 노출하지 않는다.",
        ),
    ] = False,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    sort: Annotated[AdminFeatureSort, Query()] = "name",
    order: Annotated[SortOrder | None, Query()] = None,
) -> AdminFeaturesListResponse:
    started_at = perf_counter()
    effective_order: SortOrder = (
        "desc" if order is None and sort == "issue_count" else order or "asc"
    )
    try:
        page: AdminFeaturePage = await list_admin_features(
            session,
            q=q,
            kinds=kind,
            categories=category,
            lifecycle_states=lifecycle_filter,
            publication_states=publication_filter,
            quality_states=quality_filter,
            provider_dataset_id=provider_dataset_id,
            has_coord=has_coord,
            has_issue=has_issue,
            issue_types=issue_type,
            updated_from=updated_from,
            updated_to=updated_to,
            include_ended=include_ended,
            page_size=page_size,
            cursor=cursor,
            sort=sort,
            order=effective_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AdminFeaturesListResponse(
        data=AdminFeaturesListData(items=[_record(item) for item in page.items]),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/{feature_id}/revision",
    response_model=AdminFeatureRevisionResponse,
    responses={
        404: {"description": "feature 없음"},
        200: {"headers": _ETAG_RESPONSE_HEADER},
    },
)
async def get_feature_revision_route(
    feature_id: str,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureRevisionResponse:
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    revision = await get_feature_row_revision(session, canonical_id)
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    _set_feature_etag(response, revision)
    # T-VN-32C 치환 제외 — correction If-Match 흐름의 path 참조 echo(해석된
    # legacy 정본 키)를 그대로 되돌린다 (echo 예외).
    return AdminFeatureRevisionResponse(
        data=AdminFeatureRevisionData(
            feature_id=canonical_id,
            row_revision=revision,
        )
    )


@router.get(
    "/{feature_id}/state/transitions",
    response_model=AdminFeatureStateTransitionsResponse,
    summary="Admin feature state audit timeline",
    responses={
        404: {"description": "feature 없음"},
        422: {"description": "audit cursor/page_size 오류"},
    },
)
async def list_feature_state_transitions_route(
    feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    before_transition_id: Annotated[int | None, Query(gt=0)] = None,
) -> AdminFeatureStateTransitionsResponse:
    """append-only state transition을 newest-first identity keyset으로 읽는다."""
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    if await get_feature_row_revision(session, canonical_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    try:
        page: AdminFeatureStateTransitionAuditPage = (
            await list_admin_feature_state_transitions(
                session,
                canonical_id,
                limit=page_size,
                before_transition_id=before_transition_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return AdminFeatureStateTransitionsResponse(
        data=AdminFeatureStateTransitionsData(
            items=[_state_transition_audit(item) for item in page.items],
        ),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=(
                str(page.next_cursor) if page.next_cursor is not None else None
            ),
        ),
    )


@router.get(
    "/{feature_id}",
    response_model=AdminFeatureDetailResponse,
    description=(
        "feature 참조는 legacy `f_*` id와 UUID 정본(canonical hyphenated) 양쪽을 "
        "수용한다 (ADR-068 경계 alias 해석, T-VN-32B dual — admin `{feature_id}` "
        "경로 공통)."
    ),
    responses={
        404: {"description": "feature 참조 해석 불가 또는 없음"},
        422: {"description": "feature 참조 형식 오류(빈 문자열/공백 패딩/길이 초과)"},
    },
)
async def get_feature_detail_route(
    feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureDetailResponse:
    started_at = perf_counter()
    # T-VN-32B 경계 alias 해석 — 이후 내부 조회는 해석된 정본 키로만 한다.
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    row = await get_admin_feature_detail(session, canonical_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    curations = await curation_repo.list_curation_items_by_feature_ids(
        session, feature_ids=[canonical_id], public_only=False
    )
    return _detail_response(
        row,
        started_at=started_at,
        curations=curations.get(canonical_id, ()),
    )


@router.post(
    "",
    response_model=AdminManualFeatureCreateResponse,
    response_class=AdminManualFeatureCanonicalJSONResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "수동 Feature 생성 전용 scope 없음"},
        409: {"description": "수동 Feature exact identity가 이미 존재함"},
        422: {"description": "typed field registry 또는 create input 오류"},
        503: {"description": "수동 Feature 생성 cutover 준비 전"},
        201: {"headers": _MANUAL_CREATE_RESPONSE_HEADERS},
    },
)
@idempotent_domain_command("admin.feature.create.manual-v1")
async def create_feature_route(
    body: AdminFeatureCreateRequest,
    request: Request,
    response: Response,
    context: Annotated[
        AdminManualFeatureCreateContext,
        Depends(require_admin_manual_feature_create),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminManualFeatureCreateResponse:
    started_at = perf_counter()
    payload = _payload(body)
    try:
        await _resolve_mutation_identity_refs(
            session,
            payload,
            manual_create=True,
        )
        async with domain_command_transaction(session):
            result = await create_admin_feature_with_field_overrides(
                session,
                payload=payload,
                reason_code=body.reason,
                operator=context.actor,
                command_id=current_domain_command().command_id,
            )
    except AdminManualFeatureIdentityConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "FEATURE_IDENTITY_CONFLICT",
                "message": "수동 Feature canonical identity가 충돌합니다.",
                "details": {
                    "constraint": exc.constraint,
                    "feature_id": exc.feature_uuid,
                },
            },
        ) from exc
    except AdminManualFeatureValidationError as exc:
        raise _manual_feature_create_validation_error(
            field=exc.field,
            constraint=exc.constraint,
        ) from exc
    except (AdminManualFeatureInvariantError, DBAPIError, ValueError) as exc:
        raise _manual_feature_create_internal_error() from exc
    if isinstance(result, AdminManualFeatureExactDuplicate):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MANUAL_FEATURE_EXACT_DUPLICATE",
                "message": "같은 수동 Feature가 이미 존재합니다.",
                "details": {
                    "constraint": result.constraint,
                    "existing_feature_id": result.existing_feature_uuid,
                },
            },
        )
    _set_feature_etag(response, result.row_revision)
    response.headers["Location"] = f"/v1/admin/features/{result.feature_uuid}"
    return _manual_feature_create_response(result, started_at=started_at)


@router.patch(
    "/{feature_id}/state",
    response_model=AdminFeatureStateResponse,
    dependencies=[Depends(require_destructive_enabled_for_retire)],
    responses={
        403: {"description": "파괴적 admin 작업 비활성 (retire action)"},
        404: {"description": "feature 없음"},
        409: {"description": "현재 tuple/source override가 요청 전이를 허용하지 않음"},
        412: {"description": "If-Match row_revision 불일치"},
        422: {"description": "state action/body 또는 If-Match strong ETag 오류"},
        428: {"description": "If-Match 누락"},
        200: {"headers": _ETAG_RESPONSE_HEADER},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.feature.state")
async def patch_feature_state_route(
    feature_id: str,
    body: AdminFeatureStateRequest,
    request: Request,
    response: Response,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureStateResponse:
    """retire 또는 publication/quality patch를 한 axis transition으로 commit한다."""
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    expected_revision = _require_if_match_revision(request)
    async with domain_command_transaction(session):
        try:
            transition = await transition_admin_feature_state(
                session,
                canonical_id,
                action=body.action,
                publication_state=(
                    body.publication_state
                    if isinstance(body, AdminFeatureStatePatchRequest)
                    else None
                ),
                quality_state=(
                    body.quality_state
                    if isinstance(body, AdminFeatureStatePatchRequest)
                    else None
                ),
                expected_row_revision=expected_revision,
                reason_code=body.reason_code,
                operator=context.actor,
            )
        except AdminFeatureStatePreconditionFailed as exc:
            raise _state_precondition_failed(exc) from exc
        except AdminFeatureStateNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except AdminFeatureStateConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except (AdminFeatureStateValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
    if transition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    _set_feature_etag(response, transition.row_revision)
    return _state_response(
        transition,
        feature_id=identity.feature_uuid,
        started_at=started_at,
    )

@router.post(
    "/{feature_id}/state/reactivate",
    response_model=AdminFeatureStateResponse,
    responses={
        404: {"description": "feature 또는 current source evidence 없음"},
        409: {"description": "retired override/source evidence가 재활성화를 허용하지 않음"},
        412: {"description": "If-Match row_revision 불일치"},
        422: {"description": "body 또는 If-Match strong ETag 오류"},
        428: {"description": "If-Match 누락"},
        200: {"headers": _ETAG_RESPONSE_HEADER},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.feature.state.reactivate")
async def reactivate_feature_state_route(
    feature_id: str,
    body: AdminFeatureReactivateRequest,
    request: Request,
    response: Response,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureStateResponse:
    """검증된 current provider observation으로만 lifecycle retire를 해제한다."""
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    expected_revision = _require_if_match_revision(request)
    async with domain_command_transaction(session):
        try:
            transition = await reactivate_admin_feature_state(
                session,
                canonical_id,
                expected_row_revision=expected_revision,
                reason_code=body.reason_code,
                operator=context.actor,
                provider_dataset_id=body.provider_dataset_id,
                source_entity_key=body.source_entity_key,
                source_record_key=body.source_record_key,
            )
        except AdminFeatureStatePreconditionFailed as exc:
            raise _state_precondition_failed(exc) from exc
        except AdminFeatureStateNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except AdminFeatureStateConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except (AdminFeatureStateValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
    if transition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 또는 current source evidence 없음: {feature_id!r}",
        )
    _set_feature_etag(response, transition.row_revision)
    return _state_response(
        transition,
        feature_id=identity.feature_uuid,
        started_at=started_at,
    )


@router.post(
    "/{feature_id}/field-overrides",
    response_model=AdminFeatureFieldOverrideResponse,
    responses={
        404: {"description": "feature 없음"},
        412: {"description": "If-Match row_revision 불일치"},
        422: {"description": "registry field/value 또는 request 오류"},
        428: {"description": "If-Match 누락"},
        200: {"headers": _ETAG_RESPONSE_HEADER},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.feature.override.author")
async def author_feature_field_overrides_route(
    feature_id: str,
    body: AdminFeatureFieldOverrideAuthorRequest,
    request: Request,
    response: Response,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureFieldOverrideResponse:
    """registry typed effective field를 author하고 exact command receipt를 돌려준다."""

    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    expected_revision = _require_if_match_revision(request)
    async with domain_command_transaction(session):
        try:
            result = await author_admin_feature_field_overrides(
                session,
                identity.feature_id,
                expected_row_revision=expected_revision,
                reason_code=body.reason_code,
                operator=context.actor,
                command_id=current_domain_command().command_id,
                values=body.values,
                geometry_wkt=body.geometry_wkt,
            )
        except FeatureFieldOverridePreconditionFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail={"code": "PRECONDITION_FAILED", "message": str(exc)},
            ) from exc
        except FeatureFieldOverrideNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (FeatureFieldOverrideValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
    _set_feature_etag(response, result.row_revision)
    return _field_override_response(
        result,
        feature_id=identity.feature_uuid,
        started_at=started_at,
    )


@router.post(
    "/{feature_id}/field-overrides/revoke",
    response_model=AdminFeatureFieldOverrideResponse,
    responses={
        404: {"description": "feature 또는 active override 없음"},
        412: {"description": "If-Match row_revision 불일치"},
        422: {"description": "registry field/base 또는 request 오류"},
        428: {"description": "If-Match 누락"},
        200: {"headers": _ETAG_RESPONSE_HEADER},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.feature.override.revoke")
async def revoke_feature_field_overrides_route(
    feature_id: str,
    body: AdminFeatureFieldOverrideRevokeRequest,
    request: Request,
    response: Response,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureFieldOverrideResponse:
    """active field override를 provider base value로 원자 복원한다."""

    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    expected_revision = _require_if_match_revision(request)
    async with domain_command_transaction(session):
        try:
            result = await revoke_admin_feature_field_overrides(
                session,
                identity.feature_id,
                expected_row_revision=expected_revision,
                reason_code=body.reason_code,
                operator=context.actor,
                command_id=current_domain_command().command_id,
                field_paths=body.field_paths,
            )
        except FeatureFieldOverridePreconditionFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail={"code": "PRECONDITION_FAILED", "message": str(exc)},
            ) from exc
        except FeatureFieldOverrideNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (FeatureFieldOverrideValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
    _set_feature_etag(response, result.row_revision)
    return _field_override_response(
        result,
        feature_id=identity.feature_uuid,
        started_at=started_at,
    )


@router.patch(
    "/{feature_id}",
    response_model=AdminFeatureFieldOverrideResponse,
    responses={
        404: {"description": "feature 없음"},
        409: {"description": "변경 불가"},
        412: {"description": "If-Match row_revision 불일치"},
        422: {"description": "If-Match가 row_revision strong ETag가 아님"},
        428: {"description": "If-Match 누락"},
        200: {"headers": _ETAG_RESPONSE_HEADER},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.feature.patch")
async def patch_feature_route(
    feature_id: str,
    body: AdminFeaturePatchRequest,
    request: Request,
    response: Response,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureFieldOverrideResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    expected_revision = _require_if_match_revision(request)
    patch_payload = _payload(body)
    await _resolve_mutation_identity_refs(session, patch_payload)
    async with domain_command_transaction(session):
        try:
            result = await patch_admin_feature_with_field_overrides(
                session,
                feature_id=canonical_id,
                payload=patch_payload,
                expected_row_revision=expected_revision,
                reason_code=body.reason,
                operator=context.actor,
                command_id=current_domain_command().command_id,
            )
        except FeatureFieldOverridePreconditionFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail={"code": "PRECONDITION_FAILED", "message": str(exc)},
            ) from exc
        except FeatureFieldOverrideNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (FeatureFieldOverrideValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
    _set_feature_etag(response, result.row_revision)
    return _field_override_response(
        result,
        feature_id=identity.feature_uuid,
        started_at=started_at,
    )


@router.delete(
    "/{feature_id}",
    response_model=AdminFeatureStateResponse,
    responses={
        404: {"description": "feature 없음"},
        409: {"description": "삭제 불가"},
        412: {"description": "If-Match row_revision 불일치"},
        422: {"description": "If-Match가 row_revision strong ETag가 아님"},
        428: {"description": "If-Match 누락"},
        200: {"headers": _ETAG_RESPONSE_HEADER},
    },
    openapi_extra={"parameters": [_IF_MATCH_OPENAPI_PARAMETER]},
)
@idempotent_domain_command("admin.feature.delete")
async def delete_feature_route(
    feature_id: str,
    body: AdminFeatureDeleteRequest,
    request: Request,
    response: Response,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureStateResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    expected_revision = _require_if_match_revision(request)
    async with domain_command_transaction(session):
        try:
            transition = await transition_admin_feature_state(
                session,
                canonical_id,
                action="retire",
                publication_state=None,
                quality_state=None,
                expected_row_revision=expected_revision,
                reason_code=body.reason,
                operator=context.actor,
            )
        except AdminFeatureStatePreconditionFailed as exc:
            raise _state_precondition_failed(exc) from exc
        except AdminFeatureStateNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except AdminFeatureStateConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except (AdminFeatureStateValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
    _set_feature_etag(response, transition.row_revision)
    return _state_response(
        transition,
        feature_id=identity.feature_uuid,
        started_at=started_at,
    )
