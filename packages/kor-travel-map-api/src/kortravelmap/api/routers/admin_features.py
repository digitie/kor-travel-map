"""``/admin/features`` 운영 feature 라우터 (ADR-045 T-207c)."""

from __future__ import annotations

import re
from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from kortravelmap.core import make_feature_id
from kortravelmap.dto import EventDetail, PlaceDetail
from kortravelmap.infra import curation_repo, feature_identity, price_repo, weather_repo
from kortravelmap.infra.admin_feature_repo import (
    AdminFeatureDetail,
    AdminFeatureDetailFeature,
    AdminFeatureDetailFile,
    AdminFeatureDetailIssue,
    AdminFeatureDetailOverride,
    AdminFeatureDetailSource,
    AdminFeatureDetailVersion,
    AdminFeaturePage,
    AdminFeatureRow,
    FeatureChangeConflict,
    FeatureChangeRequest,
    FeatureDeactivateResult,
    FeatureOverride,
    FeaturePreconditionFailed,
    FeatureStateConflict,
    admin_feature_card_target_exists,
    admin_features_in_bbox,
    apply_feature_change_request,
    cluster_admin_features_in_bbox,
    deactivate_feature,
    get_admin_feature_detail,
    get_feature_row_revision,
    list_admin_features,
    list_feature_change_requests,
    reject_feature_change_request,
    submit_feature_change_request,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import (
    AdminProxyContext,
    require_admin_destructive_enabled,
    require_admin_frontend,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
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
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "router",
    "AdminFeatureRecord",
    "AdminFeaturesListResponse",
    "AdminFeatureDeactivateRequest",
    "AdminFeatureDeactivateResponse",
    "AdminFeatureCreateRequest",
    "AdminFeaturePatchRequest",
    "AdminFeatureChangeResponse",
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
    "status",
    "provider",
    "issue_count",
]
SortOrder = Literal["asc", "desc"]
FeatureMutationReviewMode = Literal["require_review", "immediate"]


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
    name: str
    category: str
    status: str
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


AdminFeatureOperationalStatus = Literal[
    "draft",
    "active",
    "inactive",
    "hidden",
    "broken",
]


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
    status: AdminFeatureOperationalStatus
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


class AdminFeatureOverrideRecord(BaseModel):
    """생성/갱신된 feature override."""

    model_config = ConfigDict(extra="forbid")

    override_id: str
    feature_id: str
    field_path: str
    override_value: Any
    prevent_provider_reactivation: bool
    reason: str | None = None
    created_by: str | None = None
    created_at: datetime


class AdminFeatureDeactivateRequest(BaseModel):
    """``POST /admin/features/{feature_id}/deactivate`` body."""

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
    prevent_provider_reactivation: bool = True


class AdminFeatureDeactivateData(BaseModel):
    """Feature deactivate 결과 data."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    previous_status: str
    status: str
    override_created: bool
    override: AdminFeatureOverrideRecord | None = None


class AdminFeatureDeactivateResponse(BaseModel):
    """``POST /admin/features/{feature_id}/deactivate`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureDeactivateData
    meta: Meta


class AdminFeatureCoordInput(BaseModel):
    """Feature mutation 좌표 입력."""

    model_config = ConfigDict(extra="forbid")

    lon: float = Field(ge=124.0, le=132.0)
    lat: float = Field(ge=33.0, le=39.5)


class AdminFeatureBaseMutation(BaseModel):
    """place/event feature 추가·수정 공통 입력."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, pattern=r"^\d{8}$")
    coord: AdminFeatureCoordInput | None = None
    coord_precision_digits: int | None = Field(default=None, ge=3, le=8)
    geom: str | None = None
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


def _normalized_detail_for_kind(
    kind: str, detail: dict[str, Any] | None
) -> dict[str, Any] | None:
    """kind별 detail을 DTO 정본으로 **검증·정규화**한다 (T-VN-35, ADR-084).

    subtype 컬럼은 필수 필드(place_kind/event_kind)를 NOT NULL로 요구한다.
    DTO(`PlaceDetail`/`EventDetail`)가 그 shape의 정본이고 기본값도 갖고
    있으므로, 경계에서 한 번 통과시켜 **완전한 detail**을 만든다 — 그러면
    repo가 불완전한 shape을 볼 일이 없고(종전엔 `ValueError`→500), 잘못된
    값은 여기서 422가 된다. 검증 규칙이 DTO 한 곳에만 존재한다는 성질도
    유지된다.
    """
    model = _DETAIL_MODEL_BY_KIND.get(kind)
    if model is None:
        return detail
    payload = dict(detail or {})
    payload.setdefault("feature_id", _DETAIL_VALIDATION_PLACEHOLDER_ID)
    try:
        validated = model.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"detail이 kind={kind} 계약과 맞지 않습니다: {exc}") from exc
    normalized = validated.model_dump(mode="json")
    normalized.pop("feature_id", None)
    return normalized


# ``detail``은 kind별 typed subtype으로 저장되므로(T-VN-35, ADR-084) 생성
# 요청은 DTO 정본으로 검증·정규화한다 — 계약 문서에 내부 근거를 싣지 않도록
# docstring이 아니라 여기 주석으로 남긴다.
class AdminFeatureCreateRequest(AdminFeatureBaseMutation):
    """``POST /admin/features`` body.

    ``detail``은 kind 계약(place/event)에 맞아야 하며, 생략하면 기본값으로
    채운다. 맞지 않으면 422다.
    """

    feature_id: str | None = Field(
        default=None,
        description=(
            "기존 provider feature와 겹치는 사용자 version을 만들 때 명시한다. "
            "미지정 시 user_request 자연키로 새 feature_id를 생성한다."
        ),
    )
    kind: Literal["place", "event"]
    name: str = Field(min_length=1)
    category: str = Field(pattern=r"^\d{8}$")
    marker_icon: str = Field(min_length=1)
    marker_color: str = Field(pattern=r"^P-(0[1-9]|1[0-6])$")
    status: Literal["draft", "active", "inactive", "hidden"] = "active"
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
    idempotency_key: str | None = Field(
        default=None,
        description="feature_id 미지정 시 source_natural_key로 쓰는 caller-provided key.",
    )

    @model_validator(mode="after")
    def _normalize_detail(self) -> AdminFeatureCreateRequest:
        # 생성은 detail 미전송도 허용한다 — DTO 기본값으로 완전한 shape을
        # 만들어 subtype NOT NULL 계약을 경계에서 충족시킨다.
        object.__setattr__(
            self, "detail", _normalized_detail_for_kind(self.kind, self.detail)
        )
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


class AdminFeatureChangeRequestRecord(BaseModel):
    """feature add/update/delete request 응답 data."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    feature_id: str
    action: Literal["add", "update", "delete"]
    status: Literal["pending", "applied", "rejected"]
    review_mode: FeatureMutationReviewMode
    base_row_revision: int | None = Field(
        default=None,
        description="update/delete 요청 제출 시 확인한 feature row_revision.",
    )
    payload: dict[str, Any]
    reason: str | None = None
    requested_by: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    applied_at: datetime | None = None
    created_at: datetime


class AdminFeatureChangeData(BaseModel):
    """단건 feature change response data."""

    model_config = ConfigDict(extra="forbid")

    request: AdminFeatureChangeRequestRecord


class AdminFeatureChangeResponse(BaseModel):
    """feature add/update/delete/approve/reject 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureChangeData
    meta: Meta


class AdminFeatureChangeListData(BaseModel):
    """feature change request list data."""

    model_config = ConfigDict(extra="forbid")

    items: list[AdminFeatureChangeRequestRecord]
    review_mode: FeatureMutationReviewMode


class AdminFeatureChangeListResponse(BaseModel):
    """``GET /admin/features/change-requests`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: AdminFeatureChangeListData
    meta: Meta


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
    status: str
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
    data_origin: str
    data_version: int
    row_revision: int = Field(
        ge=1,
        description="correction If-Match에 사용할 server-owned revision.",
    )
    user_change_kind: str | None = None
    user_change_status: str | None = None
    user_change_request_id: str | None = None
    user_deleted_at: datetime | None = None
    user_deleted_by: str | None = None
    user_change_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class AdminFeatureDetailSourceRecord(BaseModel):
    """Admin feature 상세 source/link row."""

    model_config = ConfigDict(extra="forbid")

    source_entity_key: str
    source_record_key: str
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    source_version: str | None = None
    source_role: str
    match_method: str
    confidence: int
    is_primary_source: bool
    raw_name: str | None = None
    raw_address: str | None = None
    raw_longitude: float | None = None
    raw_latitude: float | None = None
    raw_payload_hash: str
    raw_data: dict[str, Any]
    fetched_at: datetime
    imported_at: datetime
    last_seen_at: datetime
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


class AdminFeatureDetailVersionRecord(BaseModel):
    """Admin feature 상세 version row."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    version: int
    origin: str
    change_kind: str
    payload: dict[str, Any]
    request_id: str | None = None
    created_by: str | None = None
    created_at: datetime


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
    versions: list[AdminFeatureDetailVersionRecord]
    change_requests: list[AdminFeatureChangeRequestRecord]
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


class AdminFeatureReviewActionRequest(BaseModel):
    """approve/reject body."""

    model_config = ConfigDict(extra="forbid")

    operator: str | None = Field(
        default=None,
        deprecated=True,
        description=(
            "[deprecated·ignored] 감사 actor는 인증 principal에서만 파생한다 "
            "(ADR-066 D-2, T-VN-20). PinVi 호환을 위해 수용하되 값은 무시하며, "
            "PinVi는 전송 중단 예정 (docs/integration-map.md)."
        ),
    )
    reason: str | None = None


def _settings() -> ApiSettings:
    return ApiSettings()


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
        status=row.status,
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


def _override(row: FeatureOverride | None) -> AdminFeatureOverrideRecord | None:
    if row is None:
        return None
    # T-VN-32C 치환 제외 — override는 감사 레코드라 내부 DB 참조(legacy) 유지.
    return AdminFeatureOverrideRecord(
        override_id=row.override_id,
        feature_id=row.feature_id,
        field_path=row.field_path,
        override_value=row.override_value,
        prevent_provider_reactivation=row.prevent_provider_reactivation,
        reason=row.reason,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _deactivate_response(
    row: FeatureDeactivateResult,
    *,
    started_at: float,
) -> AdminFeatureDeactivateResponse:
    return AdminFeatureDeactivateResponse(
        data=AdminFeatureDeactivateData(
            # T-VN-32C 치환 제외 — write 결과 레코드의 대상 참조(legacy 정본 키) 유지.
            feature_id=row.feature_id,
            previous_status=row.previous_status,
            status=row.status,
            override_created=row.override_created,
            override=_override(row.override),
        ),
        meta=make_meta(started_at=started_at),
    )


def _change_record(row: FeatureChangeRequest) -> AdminFeatureChangeRequestRecord:
    # T-VN-32C 치환 제외 — change request의 feature_id는 요청·감사 레코드에 기록된
    # 내부 DB 참조(legacy 정본 키)를 그대로 보여준다.
    return AdminFeatureChangeRequestRecord(
        request_id=row.request_id,
        feature_id=row.feature_id,
        action=row.action,
        status=row.state,
        review_mode=row.review_mode,
        base_row_revision=row.base_row_revision,
        payload=row.payload,
        reason=row.reason,
        requested_by=row.requested_by,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        applied_at=row.applied_at,
        created_at=row.created_at,
    )


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


def _detail_version(
    row: AdminFeatureDetailVersion,
) -> AdminFeatureDetailVersionRecord:
    return AdminFeatureDetailVersionRecord.model_validate(row, from_attributes=True)


def _detail_file(row: AdminFeatureDetailFile) -> AdminFeatureDetailFileRecord:
    return AdminFeatureDetailFileRecord.model_validate(row, from_attributes=True)


def _detail_response(
    row: AdminFeatureDetail,
    *,
    started_at: float,
    curations: tuple[curation_repo.CurationItem, ...] = (),
) -> AdminFeatureDetailResponse:
    # T-VN-32C — feature record·curation item의 응답 feature 참조만 UUID 치환.
    # sources/issues/overrides/versions/files/change_requests 레코드의 feature_id는
    # 내부 DB 참조(감사·lineage 레코드)라 legacy 유지.
    return AdminFeatureDetailResponse(
        data=AdminFeatureDetailData(
            feature=_detail_feature(row.feature),
            sources=[_detail_source(item) for item in row.sources],
            issues=[_detail_issue(item) for item in row.issues],
            overrides=[_detail_override(item) for item in row.overrides],
            versions=[_detail_version(item) for item in row.versions],
            change_requests=[_change_record(item) for item in row.change_requests],
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


def _change_response(
    row: FeatureChangeRequest,
    *,
    started_at: float,
) -> AdminFeatureChangeResponse:
    return AdminFeatureChangeResponse(
        data=AdminFeatureChangeData(request=_change_record(row)),
        meta=make_meta(started_at=started_at),
    )


def _review_mode(settings: ApiSettings) -> FeatureMutationReviewMode:
    mode = settings.feature_change_review_mode
    if mode not in {"require_review", "immediate"}:
        return "require_review"
    return cast(FeatureMutationReviewMode, mode)


def _payload(body: AdminFeatureBaseMutation) -> dict[str, Any]:
    raw = body.model_dump(exclude={"reason", "operator"}, exclude_unset=True)
    coord = raw.get("coord")
    if isinstance(coord, dict):
        raw["coord"] = {"lon": coord["lon"], "lat": coord["lat"]}
    return raw


async def _resolve_mutation_identity_refs(
    session: AsyncSession, payload: dict[str, Any]
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
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if identity is None:
            raise HTTPException(
                status_code=422,
                detail=f"parent_feature_id를 해석할 수 없습니다: {parent!r}",
            )
        payload["parent_feature_id"] = identity.feature_id
    sibling = payload.get("sibling_group_id")
    if sibling is not None and await feature_identity.feature_uuid_in_use(
        session, sibling
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "sibling_group_id가 feature UUID 정본과 충돌합니다 — feature "
                "참조가 아니라 sibling group 식별자를 전달해야 합니다."
            ),
        )


def _create_feature_id(body: AdminFeatureCreateRequest) -> str:
    if body.feature_id:
        # T-VN-32C PR-2 (W1) — 값 전환 후 응답에서 복사한 UUID가 신규 legacy
        # PK로 조용히 각인되는 유령 행 생성을 차단한다. 신규 feature_id는
        # legacy 표기만 허용한다(UUID는 시스템이 발급).
        if feature_identity.is_canonical_uuid_ref(body.feature_id):
            raise HTTPException(
                status_code=422,
                detail=(
                    "feature_id에 UUID를 지정할 수 없습니다 — 신규 feature의 "
                    "legacy id는 f_* 표기여야 하며 UUID는 시스템이 발급합니다."
                ),
            )
        return body.feature_id
    coord_key = "global"
    if body.coord is not None:
        coord_key = f"{body.coord.lon:.6f},{body.coord.lat:.6f}"
    natural_key = body.idempotency_key or f"{body.name}:{coord_key}"
    return make_feature_id(
        bjd_code=body.legal_dong_code,
        kind=body.kind,
        category=body.category,
        source_type="user_request",
        source_natural_key=natural_key,
    )


def _change_error(exc: FeatureChangeConflict) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if "feature 없음" in str(exc)
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=status_code, detail=str(exc))


# ── If-Match row-revision 낙관적 동시성 (T-VN-13, D-10-3) ─────────────────────
def _set_feature_etag(response: Response, revision: int) -> None:
    response.headers["ETag"] = revision_etag(revision)


def _require_if_match_revision(request: Request) -> int:
    """correction 요청의 ``If-Match``를 row_revision으로 파싱한다.

    누락 → 428, 정확히 한 physical header line의 canonical strong ETag가 아니면
    → 422. bare/weak/wildcard/list/0/선행 0/BIGINT 초과는 모두 거부한다.
    """
    revision = parse_revision_header(request, "If-Match", required=True)
    assert revision is not None
    return revision


def _precondition_failed(exc: FeaturePreconditionFailed) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail={
            "code": "PRECONDITION_FAILED",
            "message": (
                "If-Match row_revision이 현재 feature 행과 다릅니다: "
                f"current={exc.current}."
            ),
        },
    )


_ETAG_RESPONSE_HEADER = {
    "ETag": {
        "description": "현재 feature의 server-owned row_revision strong entity tag.",
        "schema": {"type": "string"},
    }
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
    feature_status: Annotated[
        list[AdminFeatureOperationalStatus] | None,
        Query(
            alias="status",
            description=(
                "운영 상태 반복 필터. 미지정 시 삭제 전 draft/active/inactive/hidden/"
                "broken 전체."
            ),
        ),
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
                statuses=feature_status,
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
            statuses=feature_status,
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
    asof: Annotated[datetime | None, Query()] = None,
) -> FeatureWeatherResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    await _admin_feature_exists_or_404(session, canonical_id)
    card = await weather_repo.build_admin_weather_card(
        session,
        feature_id=canonical_id,
        asof=asof,
    )
    return FeatureWeatherResponse(
        data=WeatherCardData(
            # T-VN-32C PR-2 — 단건 card 응답의 feature_id는 UUID 정본
            # (features.py 단건 card와 동일 규약; repo 내부 조회는 legacy 축).
            feature_id=identity.feature_uuid,
            asof=card.asof,
            source_styles=card.source_styles,
            metrics=[
                WeatherMetricOut.model_validate(metric, from_attributes=True)
                for metric in card.metrics
            ],
            latest_at=card.latest_at,
            is_stale=card.is_stale,
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
    asof: Annotated[datetime | None, Query()] = None,
    history_limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> FeaturePriceResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    await _admin_feature_exists_or_404(session, canonical_id)
    card = await price_repo.build_price_card(
        session,
        feature_id=canonical_id,
        asof=asof,
        history_limit=history_limit,
    )
    return FeaturePriceResponse(
        data=PriceCardData(
            # T-VN-32C PR-2 — 단건 card 응답의 feature_id는 UUID 정본
            # (features.py 단건 card와 동일 규약; repo 내부 조회는 legacy 축).
            feature_id=identity.feature_uuid,
            asof=card.asof,
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
    feature_status: Annotated[
        list[str] | None,
        Query(alias="status", description="feature status 반복 필터. 기본 active."),
    ] = None,
    provider: Annotated[
        list[str] | None,
        Query(description="primary provider 반복 필터"),
    ] = None,
    dataset_key: Annotated[
        list[str] | None,
        Query(description="primary dataset_key 반복 필터"),
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
            statuses=feature_status if feature_status is not None else ("active",),
            providers=provider,
            dataset_keys=dataset_key,
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
    "/change-requests",
    response_model=AdminFeatureChangeListResponse,
)
async def list_feature_change_request_route(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[ApiSettings, Depends(_settings)],
    status_filter: Annotated[
        list[Literal["pending", "applied", "rejected"]] | None,
        Query(alias="status"),
    ] = None,
    action: Annotated[
        list[Literal["add", "update", "delete"]] | None,
        Query(),
    ] = None,
    q: Annotated[str | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AdminFeatureChangeListResponse:
    started_at = perf_counter()
    rows = await list_feature_change_requests(
        session,
        states=status_filter,
        actions=action,
        # T-VN-32C PR-2 (S8) — UUID 표기 검색어를 legacy 정본 키로 정규화.
        q=await feature_identity.legacy_id_for_filter(session, q),
        limit=page_size,
    )
    return AdminFeatureChangeListResponse(
        data=AdminFeatureChangeListData(
            items=[_change_record(row) for row in rows],
            review_mode=_review_mode(settings),
        ),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=None,
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


@router.post("", response_model=AdminFeatureChangeResponse)
@idempotent_domain_command("admin.feature.create")
async def create_feature_route(
    body: AdminFeatureCreateRequest,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[ApiSettings, Depends(_settings)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    feature_id = _create_feature_id(body)
    payload = _payload(body)
    payload["feature_id"] = feature_id
    await _resolve_mutation_identity_refs(session, payload)
    async with domain_command_transaction(session):
        try:
            result = await submit_feature_change_request(
                session,
                action="add",
                feature_id=feature_id,
                payload=payload,
                review_mode=_review_mode(settings),
                reason=body.reason,
                requested_by=context.actor,
            )
        except FeatureChangeConflict as exc:
            raise _change_error(exc) from exc
    return _change_response(result, started_at=started_at)


@router.patch(
    "/{feature_id}",
    response_model=AdminFeatureChangeResponse,
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
    settings: Annotated[ApiSettings, Depends(_settings)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    expected_revision = _require_if_match_revision(request)
    patch_payload = _payload(body)
    await _resolve_mutation_identity_refs(session, patch_payload)
    async with domain_command_transaction(session):
        try:
            result = await submit_feature_change_request(
                session,
                action="update",
                feature_id=canonical_id,
                payload=patch_payload,
                review_mode=_review_mode(settings),
                reason=body.reason,
                requested_by=context.actor,
                expected_row_revision=expected_revision,
            )
        except FeaturePreconditionFailed as exc:
            raise _precondition_failed(exc) from exc
        except FeatureChangeConflict as exc:
            raise _change_error(exc) from exc
        new_revision = await get_feature_row_revision(session, canonical_id)
    if new_revision is not None:
        _set_feature_etag(response, new_revision)
    return _change_response(result, started_at=started_at)


@router.delete(
    "/{feature_id}",
    response_model=AdminFeatureChangeResponse,
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
    settings: Annotated[ApiSettings, Depends(_settings)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    expected_revision = _require_if_match_revision(request)
    async with domain_command_transaction(session):
        try:
            result = await submit_feature_change_request(
                session,
                action="delete",
                feature_id=canonical_id,
                payload={},
                review_mode=_review_mode(settings),
                reason=body.reason,
                requested_by=context.actor,
                expected_row_revision=expected_revision,
            )
        except FeaturePreconditionFailed as exc:
            raise _precondition_failed(exc) from exc
        except FeatureChangeConflict as exc:
            raise _change_error(exc) from exc
        new_revision = await get_feature_row_revision(session, canonical_id)
    if new_revision is not None:
        _set_feature_etag(response, new_revision)
    return _change_response(result, started_at=started_at)


@router.post(
    "/change-requests/{request_id}/approve",
    response_model=AdminFeatureChangeResponse,
    responses={
        404: {"description": "request 없음"},
        409: {"description": "승인 불가"},
        412: {"description": "If-Match row_revision 불일치"},
        200: {"headers": _ETAG_RESPONSE_HEADER},
    },
)
@idempotent_domain_command("admin.feature-change.approve")
async def approve_feature_change_request_route(
    request_id: str,
    body: AdminFeatureReviewActionRequest,
    response: Response,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    async with domain_command_transaction(session):
        try:
            result = await apply_feature_change_request(
                session,
                request_id,
                operator=context.actor,
            )
        except FeaturePreconditionFailed as exc:
            raise _precondition_failed(exc) from exc
        except FeatureChangeConflict as exc:
            raise _change_error(exc) from exc
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"feature change request 없음: {request_id!r}",
            )
        new_revision = await get_feature_row_revision(session, result.feature_id)
    if new_revision is not None:
        _set_feature_etag(response, new_revision)
    return _change_response(result, started_at=started_at)


@router.post(
    "/change-requests/{request_id}/reject",
    response_model=AdminFeatureChangeResponse,
    responses={404: {"description": "request 없음"}},
)
@idempotent_domain_command("admin.feature-change.reject")
async def reject_feature_change_request_route(
    request_id: str,
    body: AdminFeatureReviewActionRequest,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureChangeResponse:
    started_at = perf_counter()
    async with domain_command_transaction(session):
        result = await reject_feature_change_request(
            session,
            request_id,
            operator=context.actor,
            reason=body.reason,
        )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pending feature change request 없음: {request_id!r}",
        )
    return _change_response(result, started_at=started_at)


@router.post(
    "/{feature_id}/deactivate",
    response_model=AdminFeatureDeactivateResponse,
    dependencies=[Depends(require_admin_destructive_enabled)],
    responses={
        404: {"description": "feature 없음"},
        409: {"description": "feature 상태 전이 불가"},
        403: {"description": "파괴적 admin 작업 비활성"},
    },
)
@idempotent_domain_command("admin.feature.deactivate")
async def deactivate_feature_route(
    feature_id: str,
    body: AdminFeatureDeactivateRequest,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureDeactivateResponse:
    started_at = perf_counter()
    identity = await resolve_feature_ref_or_error(session, feature_id)
    canonical_id = identity.feature_id
    async with domain_command_transaction(session):
        try:
            result = await deactivate_feature(
                session,
                canonical_id,
                reason=body.reason,
                operator=context.actor,
                prevent_provider_reactivation=body.prevent_provider_reactivation,
            )
        except FeatureStateConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    return _deactivate_response(result, started_at=started_at)
