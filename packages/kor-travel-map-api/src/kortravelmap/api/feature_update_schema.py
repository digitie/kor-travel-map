"""Feature update request HTTP schema.

라우터 경로와 독립적으로 admin 및 ops pipeline API가 공유하는 요청/응답 계약이다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from kortravelmap.api.response import Meta

__all__ = [
    "BboxScope",
    "CacheTargetKeysScope",
    "CenterRadiusScope",
    "FeatureIdsScope",
    "FeatureUpdatePolicy",
    "FeatureUpdateRequestCancelRequest",
    "FeatureUpdateRequestCreateRequest",
    "FeatureUpdateRequestCreateResponse",
    "FeatureUpdateRequestDetailResponse",
    "FeatureUpdateRequestListData",
    "FeatureUpdateRequestListResponse",
    "FeatureUpdateRequestRecord",
    "FeatureUpdateRequestRunNowRequest",
    "FeatureUpdateScope",
    "FeatureUpdateState",
    "ProviderDatasetScope",
    "RunMode",
    "SigunguByRadiusScope",
]

FeatureUpdateState = Literal["queued", "running", "done", "failed", "cancelled"]
RunMode = Literal["queued", "now"]
ScopeMode = Literal["center_radius", "sigungu_by_radius"]
SigunguRadiusMatch = Literal["intersects", "contains_center", "feature_sigungu"]
FeatureUpdatePolicyMode = Literal["refresh_existing"]
NonEmptyString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
FeatureIdString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
TargetKeyString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
MAX_PROVIDER_FILTERS = 32
MAX_DATASET_FILTERS = 64
MAX_SCOPE_FEATURE_IDS = 1000
MAX_SCOPE_TARGET_KEYS = 500
MAX_RADIUS_KM = 500.0


class FeatureUpdatePoint(BaseModel):
    """WGS84 lon/lat 좌표."""

    model_config = ConfigDict(extra="forbid")

    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class FeatureIdsScope(BaseModel):
    """특정 feature id 목록 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["feature_ids"]
    feature_ids: list[FeatureIdString] = Field(max_length=MAX_SCOPE_FEATURE_IDS)


class CenterRadiusScope(BaseModel):
    """좌표 중심 반경 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["center_radius"]
    center: FeatureUpdatePoint
    radius_km: float = Field(gt=0, le=MAX_RADIUS_KM)


class SigunguByRadiusScope(BaseModel):
    """kor-travel-geo가 계산한 반경 교차 시군구 기준 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["sigungu_by_radius"]
    center: FeatureUpdatePoint
    radius_km: float = Field(gt=0, le=MAX_RADIUS_KM)
    match: SigunguRadiusMatch = "intersects"


class BboxScope(BaseModel):
    """WGS84 bbox 안 feature 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["bbox"]
    min_lon: float = Field(ge=-180, le=180)
    min_lat: float = Field(ge=-90, le=90)
    max_lon: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def _validate_order(self) -> BboxScope:
        if self.min_lon > self.max_lon or self.min_lat > self.max_lat:
            raise ValueError("bbox min values must be less than or equal to max values")
        return self


class ProviderDatasetScope(BaseModel):
    """특정 provider/dataset 자체 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["provider_dataset"]
    provider: NonEmptyString
    dataset_key: NonEmptyString
    sync_scope: NonEmptyString | None = None


class CacheTargetKeysScope(BaseModel):
    """외부 POI/cache target key 목록 기반 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["cache_target_keys"]
    external_system: NonEmptyString
    target_keys: list[TargetKeyString] = Field(max_length=MAX_SCOPE_TARGET_KEYS)
    radius_km: float | None = Field(default=None, gt=0, le=MAX_RADIUS_KM)
    scope_mode: ScopeMode = "center_radius"


FeatureUpdateScope = Annotated[
    FeatureIdsScope
    | CenterRadiusScope
    | SigunguByRadiusScope
    | BboxScope
    | ProviderDatasetScope
    | CacheTargetKeysScope,
    Field(discriminator="type"),
]


class FeatureUpdatePolicy(BaseModel):
    """Provider refresh 실행 정책 override."""

    model_config = ConfigDict(extra="forbid")

    mode: FeatureUpdatePolicyMode | None = None
    include_inactive: bool | None = None
    force_provider_call: bool | None = None
    dedup_after_load: bool | None = None
    consistency_check_after_load: bool | None = None
    prevent_provider_reactivation: bool | None = None


class FeatureUpdateRequestCreateRequest(BaseModel):
    """feature update request 생성 요청."""

    model_config = ConfigDict(extra="forbid")

    scope: FeatureUpdateScope = Field(description="feature update scope payload.")
    providers: list[NonEmptyString] = Field(
        default_factory=list,
        max_length=MAX_PROVIDER_FILTERS,
    )
    dataset_keys: list[NonEmptyString] = Field(
        default_factory=list,
        max_length=MAX_DATASET_FILTERS,
    )
    update_policy: FeatureUpdatePolicy = Field(default_factory=FeatureUpdatePolicy)
    run_mode: RunMode = "queued"
    priority: int = Field(default=50, ge=0, le=1000)
    dry_run: bool = False
    operator: str | None = None
    reason: str | None = None


class FeatureUpdateRequestRecord(BaseModel):
    """feature update request 행/preview의 HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    scope_type: str
    scope: dict[str, Any]
    providers: list[str]
    dataset_keys: list[str]
    update_policy: dict[str, Any]
    run_mode: RunMode
    priority: int
    status: str
    dry_run: bool
    matched_scope: dict[str, Any]
    job_id: str | None = None
    dagster_run_id: str | None = None
    operator: str | None = None
    reason: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
    status_url: str | None = None


class FeatureUpdateRequestCreateResponse(BaseModel):
    """생성/취소/run-now 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureUpdateRequestRecord
    meta: Meta


class FeatureUpdateRequestDetailResponse(BaseModel):
    """feature update request 단건 조회 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureUpdateRequestRecord
    meta: Meta


class FeatureUpdateRequestListData(BaseModel):
    """feature update request 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureUpdateRequestRecord]


class FeatureUpdateRequestListResponse(BaseModel):
    """feature update request 목록 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureUpdateRequestListData
    meta: Meta


class FeatureUpdateRequestCancelRequest(BaseModel):
    """취소 요청 body."""

    model_config = ConfigDict(extra="forbid")

    error_message: str | None = Field(
        default=None,
        description="취소 사유. 미지정 시 기본 메시지를 저장한다.",
    )


class FeatureUpdateRequestRunNowRequest(BaseModel):
    """기존 request payload를 run_mode=now로 재큐잉할 때의 override."""

    model_config = ConfigDict(extra="forbid")

    priority: int | None = Field(default=None, ge=0, le=1000)
    operator: str | None = None
    reason: str | None = None
