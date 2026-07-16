"""Feature update request HTTP schema.

라우터 경로와 독립적으로 admin 및 ops pipeline API가 공유하는 요청/응답 계약이다.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Annotated, Any, Literal
from uuid import UUID

from kortravelmap.core.sync_scope import MAX_EXTERNAL_SYSTEM_NAME_LENGTH
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
    with_config,
)
from typing_extensions import TypedDict

from kortravelmap.api.response import Meta

__all__ = [
    "BboxScope",
    "CacheTargetKeysScope",
    "CenterRadiusScope",
    "FeatureIdsScope",
    "FeatureUpdatePolicy",
    "FeatureUpdateRequestCreateRequest",
    "FeatureUpdateRequestCreatedRecord",
    "FeatureUpdateRequestCreateResponse",
    "FeatureUpdateRequestDetailResponse",
    "FeatureUpdateRequestListData",
    "FeatureUpdateRequestListResponse",
    "FeatureUpdateRequestMutationResponse",
    "FeatureUpdateRequestPreviewRequest",
    "FeatureUpdateRequestPreviewRecord",
    "FeatureUpdateRequestPreviewResponse",
    "FeatureUpdateRequestRecord",
    "FeatureUpdateRequestRunNowRequest",
    "FeatureUpdateScope",
    "FeatureUpdateState",
    "ProviderDatasetScope",
    "RunMode",
    "ScopeType",
    "SigunguByRadiusScope",
]

FeatureUpdateState = Literal["queued", "running", "done", "failed", "cancelled"]
RunMode = Literal["queued", "now"]
ScopeType = Literal[
    "feature_ids",
    "center_radius",
    "sigungu_by_radius",
    "bbox",
    "provider_dataset",
    "cache_target_keys",
]
ScopeMode = Literal["center_radius", "sigungu_by_radius"]
SigunguRadiusMatch = Literal["intersects"]
FeatureUpdatePolicyMode = Literal["refresh_existing"]
NonEmptyString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
ExternalSystemName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_EXTERNAL_SYSTEM_NAME_LENGTH,
    ),
]
FeatureIdString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
TargetKeyString = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
AuditReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
MAX_PROVIDER_FILTERS = 32
MAX_DATASET_FILTERS = 64
MAX_SCOPE_FEATURE_IDS = 1000
MAX_SCOPE_TARGET_KEYS = 500
MAX_RADIUS_KM = 500.0


def _strict_json_number(value: Any) -> float:
    """JSON int/float만 받고 bool·문자열 coercion은 금지한다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a JSON number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("value must be a finite JSON number") from exc
    if not isfinite(number):
        raise ValueError("value must be finite")
    return number


Longitude = Annotated[
    float,
    Field(ge=-180, le=180, allow_inf_nan=False),
    BeforeValidator(_strict_json_number),
]
Latitude = Annotated[
    float,
    Field(ge=-90, le=90, allow_inf_nan=False),
    BeforeValidator(_strict_json_number),
]
RadiusKm = Annotated[
    float,
    Field(gt=0, le=MAX_RADIUS_KM, allow_inf_nan=False),
    BeforeValidator(_strict_json_number),
]
RequestPriority = Annotated[int, Field(strict=True, ge=0, le=1000)]


class FeatureUpdatePoint(BaseModel):
    """WGS84 lon/lat 좌표."""

    model_config = ConfigDict(extra="forbid")

    lon: Longitude
    lat: Latitude


class FeatureIdsScope(BaseModel):
    """특정 feature id 목록 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["feature_ids"]
    feature_ids: list[FeatureIdString] = Field(
        max_length=MAX_SCOPE_FEATURE_IDS,
        json_schema_extra={"uniqueItems": True},
    )

    @model_validator(mode="after")
    def _validate_unique_feature_ids(self) -> FeatureIdsScope:
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("feature_ids items must be unique")
        return self


class CenterRadiusScope(BaseModel):
    """좌표 중심 반경 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["center_radius"]
    center: FeatureUpdatePoint
    radius_km: RadiusKm


class SigunguByRadiusScope(BaseModel):
    """kor-travel-geo가 계산한 반경 교차 시군구 기준 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["sigungu_by_radius"]
    center: FeatureUpdatePoint
    radius_km: RadiusKm
    match: SigunguRadiusMatch = "intersects"


class BboxScope(BaseModel):
    """WGS84 bbox 안 feature 갱신 scope."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["bbox"]
    min_lon: Longitude
    min_lat: Latitude
    max_lon: Longitude
    max_lat: Latitude

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
    external_system: ExternalSystemName
    target_keys: list[TargetKeyString] = Field(
        max_length=MAX_SCOPE_TARGET_KEYS,
        json_schema_extra={"uniqueItems": True},
    )
    radius_km: RadiusKm | None = None
    scope_mode: ScopeMode = "center_radius"

    @model_validator(mode="after")
    def _validate_unique_target_keys(self) -> CacheTargetKeysScope:
        if len(self.target_keys) != len(set(self.target_keys)):
            raise ValueError("target_keys items must be unique")
        return self


FeatureUpdateScope = Annotated[
    FeatureIdsScope
    | CenterRadiusScope
    | SigunguByRadiusScope
    | BboxScope
    | ProviderDatasetScope
    | CacheTargetKeysScope,
    Field(discriminator="type"),
]


@with_config(ConfigDict(extra="forbid"))
class FeatureUpdatePolicy(TypedDict, total=False):
    """존재하는 key만 직렬화하는 strict provider refresh 정책."""

    mode: FeatureUpdatePolicyMode
    include_inactive: StrictBool
    force_provider_call: StrictBool
    dedup_after_load: StrictBool
    consistency_check_after_load: StrictBool
    prevent_provider_reactivation: StrictBool


class _FeatureUpdateRequestPlan(BaseModel):
    """영속 요청과 미리보기가 공유하는 실행 계획."""

    model_config = ConfigDict(extra="forbid")

    scope: FeatureUpdateScope = Field(description="feature update scope payload.")
    providers: list[NonEmptyString] = Field(
        default_factory=list,
        max_length=MAX_PROVIDER_FILTERS,
        json_schema_extra={"uniqueItems": True},
    )
    dataset_keys: list[NonEmptyString] = Field(
        default_factory=list,
        max_length=MAX_DATASET_FILTERS,
        json_schema_extra={"uniqueItems": True},
    )
    update_policy: FeatureUpdatePolicy = Field(default_factory=FeatureUpdatePolicy)
    run_mode: RunMode = "queued"
    priority: RequestPriority = 50

    @model_validator(mode="after")
    def _validate_unique_filters(self) -> _FeatureUpdateRequestPlan:
        if len(self.providers) != len(set(self.providers)):
            raise ValueError("providers items must be unique")
        if len(self.dataset_keys) != len(set(self.dataset_keys)):
            raise ValueError("dataset_keys items must be unique")
        if self.scope.type == "provider_dataset" and (
            self.providers or self.dataset_keys
        ):
            raise ValueError(
                "provider_dataset scope must not repeat providers or dataset_keys filters"
            )
        return self


class FeatureUpdateRequestCreateRequest(_FeatureUpdateRequestPlan):
    """DB와 import job을 반드시 생성하는 feature update 요청."""

    reason: AuditReason | None = None


class FeatureUpdateRequestPreviewRequest(_FeatureUpdateRequestPlan):
    """DB write 없이 scope 해석 결과만 계산하는 요청."""


class FeatureUpdateRequestRecord(BaseModel):
    """DB에 저장된 feature update request의 HTTP 표현."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    scope_type: ScopeType
    scope: FeatureUpdateScope
    requested_sync_scope: str | None = Field(
        description="운영자가 provider_dataset 요청에 명시한 원본 sync scope.",
    )
    effective_sync_scope: str | None = Field(
        description="실행과 활성 작업 유일성에 실제 적용되는 정규화된 sync scope.",
    )
    providers: list[str]
    dataset_keys: list[str]
    update_policy: FeatureUpdatePolicy
    run_mode: RunMode
    priority: int
    status: FeatureUpdateState
    matched_scope: dict[str, Any]
    job_id: UUID
    dagster_run_id: str | None
    dispatch_requested_at: datetime | None = Field(
        description="같은 canonical 작업의 즉시 dispatch가 요청된 최초 시각.",
    )
    operator: str | None
    reason: AuditReason | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    generation: int = Field(ge=1)
    status_url: str

    @model_validator(mode="after")
    def _validate_scope_type(self) -> FeatureUpdateRequestRecord:
        if self.scope_type != self.scope.type:
            raise ValueError("scope_type must equal scope.type")
        return self


class FeatureUpdateRequestCreatedRecord(FeatureUpdateRequestRecord):
    """생성 API가 영속 요청을 반환했음을 나타내는 판별형."""

    result_kind: Literal["request"]


class FeatureUpdateRequestPreviewRecord(BaseModel):
    """DB write 없이 scope 해석 결과만 반환하는 preview 표현."""

    model_config = ConfigDict(extra="forbid")

    result_kind: Literal["preview"]
    scope_type: ScopeType
    scope: FeatureUpdateScope
    providers: list[str]
    dataset_keys: list[str]
    update_policy: FeatureUpdatePolicy
    run_mode: RunMode
    priority: int
    matched_scope: dict[str, Any]

    @model_validator(mode="after")
    def _validate_scope_type(self) -> FeatureUpdateRequestPreviewRecord:
        if self.scope_type != self.scope.type:
            raise ValueError("scope_type must equal scope.type")
        return self


class FeatureUpdateRequestCreateResponse(BaseModel):
    """새 요청 또는 동일한 활성 canonical 요청 재사용 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureUpdateRequestCreatedRecord
    reused_active_request: bool
    meta: Meta


class FeatureUpdateRequestPreviewResponse(BaseModel):
    """비영속 scope 미리보기 응답."""

    model_config = ConfigDict(extra="forbid")

    data: FeatureUpdateRequestPreviewRecord
    meta: Meta


class FeatureUpdateRequestMutationResponse(BaseModel):
    """기존 canonical 요청의 상태나 dispatch 의도를 바꾸는 mutation 응답."""

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


class FeatureUpdateRequestRunNowRequest(BaseModel):
    """기존 canonical request에 우선 dispatch를 요청하는 빈 명령 body."""

    model_config = ConfigDict(extra="forbid")
