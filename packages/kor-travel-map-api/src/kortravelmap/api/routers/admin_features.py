"""``/admin/features`` 운영 feature 라우터 (ADR-045 T-207c)."""

from __future__ import annotations

import re
from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from kortravelmap.core import make_feature_id
from kortravelmap.infra import curation_repo, price_repo, weather_repo
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
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
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
from kortravelmap.api.http_revision import parse_revision_header, revision_etag
from kortravelmap.api.response import ClusterUnit, Meta, make_meta
from kortravelmap.api.routers.curations import AdminCurationItemView
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

    feature_id: str
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


class AdminFeatureCreateRequest(AdminFeatureBaseMutation):
    """``POST /admin/features`` body."""

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

    feature_id: str
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
    return AdminFeatureRecord(
        feature_id=row.feature_id,
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


def _override(row: FeatureOverride | None) -> AdminFeatureOverrideRecord | None:
    if row is None:
        return None
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
            feature_id=row.feature_id,
            previous_status=row.previous_status,
            status=row.status,
            override_created=row.override_created,
            override=_override(row.override),
        ),
        meta=make_meta(started_at=started_at),
    )


def _change_record(row: FeatureChangeRequest) -> AdminFeatureChangeRequestRecord:
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
    return AdminFeatureDetailFeatureRecord.model_validate(row, from_attributes=True)


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
                AdminCurationItemView.model_validate(item, from_attributes=True)
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


def _create_feature_id(body: AdminFeatureCreateRequest) -> str:
    if body.feature_id:
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
    items = [AdminFeatureMapItem(**row) for row in raw_items[:max_items]]
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
    await _admin_feature_exists_or_404(session, feature_id)
    card = await weather_repo.build_admin_weather_card(
        session,
        feature_id=feature_id,
        asof=asof,
    )
    return FeatureWeatherResponse(
        data=WeatherCardData(
            feature_id=card.feature_id,
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
    await _admin_feature_exists_or_404(session, feature_id)
    card = await price_repo.build_price_card(
        session,
        feature_id=feature_id,
        asof=asof,
        history_limit=history_limit,
    )
    return FeaturePriceResponse(
        data=PriceCardData(
            feature_id=card.feature_id,
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
        q=q,
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
    revision = await get_feature_row_revision(session, feature_id)
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    _set_feature_etag(response, revision)
    return AdminFeatureRevisionResponse(
        data=AdminFeatureRevisionData(
            feature_id=feature_id,
            row_revision=revision,
        )
    )


@router.get(
    "/{feature_id}",
    response_model=AdminFeatureDetailResponse,
    responses={404: {"description": "feature 없음"}},
)
async def get_feature_detail_route(
    feature_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminFeatureDetailResponse:
    started_at = perf_counter()
    row = await get_admin_feature_detail(session, feature_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {feature_id!r}",
        )
    curations = await curation_repo.list_curation_items_by_feature_ids(
        session, feature_ids=[feature_id], public_only=False
    )
    return _detail_response(
        row,
        started_at=started_at,
        curations=curations.get(feature_id, ()),
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
    expected_revision = _require_if_match_revision(request)
    async with domain_command_transaction(session):
        try:
            result = await submit_feature_change_request(
                session,
                action="update",
                feature_id=feature_id,
                payload=_payload(body),
                review_mode=_review_mode(settings),
                reason=body.reason,
                requested_by=context.actor,
                expected_row_revision=expected_revision,
            )
        except FeaturePreconditionFailed as exc:
            raise _precondition_failed(exc) from exc
        except FeatureChangeConflict as exc:
            raise _change_error(exc) from exc
        new_revision = await get_feature_row_revision(session, feature_id)
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
    expected_revision = _require_if_match_revision(request)
    async with domain_command_transaction(session):
        try:
            result = await submit_feature_change_request(
                session,
                action="delete",
                feature_id=feature_id,
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
        new_revision = await get_feature_row_revision(session, feature_id)
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
    async with domain_command_transaction(session):
        try:
            result = await deactivate_feature(
                session,
                feature_id,
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
