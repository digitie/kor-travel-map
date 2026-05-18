from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, TypeAlias

from kraddr.base import (
    Address,
    PlaceCategory,
    PlaceCategoryCode,
    PlaceCoordinate,
    get_category,
    is_known_category_code,
    mapbox_maki_icon_or_none,
)
from kraddr.base import (
    category_label as kraddr_category_label,
)
from kraddr.base import (
    category_path as kraddr_category_path,
)
from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from krtour_map.enums import (
    FeatureKind,
    FeatureStatus,
    ForecastStyle,
    SourceRole,
    TimelineBucket,
    WeatherDomain,
)
from krtour_map.ids import make_source_record_key
from krtour_map.providers import normalize_provider_name


def kst_now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))


class KrtourModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


Coordinate: TypeAlias = PlaceCoordinate


class FeatureUrls(KrtourModel):
    homepage: AnyUrl | None = None
    sns1: AnyUrl | None = None
    sns2: AnyUrl | None = None
    review_naver: AnyUrl | None = None
    review_kakao: AnyUrl | None = None
    review_google: AnyUrl | None = None


class RawDataRef(KrtourModel):
    provider: str
    dataset_key: str
    source_entity_id: str
    source_role: SourceRole | str = SourceRole.PRIMARY
    fetched_at: datetime | None = None
    payload_hash: str | None = None

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return normalize_provider_name(value)


class Feature(KrtourModel):
    feature_id: str
    kind: FeatureKind | str
    name: str = Field(..., min_length=1)
    coord: Coordinate | None = None
    address: Address = Field(default_factory=Address)
    category: str = Field(..., min_length=1)
    urls: FeatureUrls = Field(default_factory=FeatureUrls)
    marker_icon: str = Field(..., min_length=1)
    marker_color: str = Field(..., min_length=1)
    parent_feature_id: str | None = None
    sibling_group_id: str | None = None
    detail: dict[str, Any] | None = None
    raw_refs: list[RawDataRef] = Field(default_factory=list)
    status: FeatureStatus | str = FeatureStatus.ACTIVE
    created_at: datetime = Field(default_factory=kst_now)
    updated_at: datetime = Field(default_factory=kst_now)
    deleted_at: datetime | None = None

    @field_validator("coord")
    @classmethod
    def validate_korean_coordinate(cls, value: Coordinate | None) -> Coordinate | None:
        if value is None:
            return None
        if not 124.0 <= value.longitude <= 132.0:
            raise ValueError("coord.longitude must be within the Korean map bounds")
        if not 33.0 <= value.latitude <= 39.5:
            raise ValueError("coord.latitude must be within the Korean map bounds")
        return value

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> str:
        if isinstance(value, PlaceCategoryCode):
            return value.value
        return str(value)

    @property
    def category_info(self) -> PlaceCategory | None:
        if not is_known_category_code(self.category):
            return None
        return get_category(self.category)

    @property
    def category_path(self) -> tuple[str, ...]:
        if not is_known_category_code(self.category):
            return ()
        return kraddr_category_path(self.category)

    @property
    def category_label(self) -> str:
        if not is_known_category_code(self.category):
            return self.category
        return kraddr_category_label(self.category)

    @property
    def mapbox_maki_icon(self) -> str | None:
        return mapbox_maki_icon_or_none(self.category)


class FeaturePatch(KrtourModel):
    name: str | None = None
    coord: Coordinate | None = None
    address: Address | None = None
    category: str | None = None
    urls: FeatureUrls | None = None
    marker_icon: str | None = None
    marker_color: str | None = None
    parent_feature_id: str | None = None
    sibling_group_id: str | None = None
    detail: dict[str, Any] | None = None
    raw_refs: list[RawDataRef] | None = None
    status: FeatureStatus | str | None = None


class SourceRecord(KrtourModel):
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    raw_payload_hash: str
    source_version: str | None = None
    raw_name: str | None = None
    raw_address: str | None = None
    raw_longitude: Decimal | None = None
    raw_latitude: Decimal | None = None
    raw_data: dict[str, Any] | None = None
    fetched_at: datetime | None = None
    imported_at: datetime = Field(default_factory=kst_now)
    expires_at: datetime | None = None
    source_record_key: str | None = None

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return normalize_provider_name(value)

    def key(self) -> str:
        return self.source_record_key or make_source_record_key(
            provider=self.provider,
            dataset_key=self.dataset_key,
            source_entity_type=self.source_entity_type,
            source_entity_id=self.source_entity_id,
            raw_payload_hash=self.raw_payload_hash,
        )


class SourceLink(KrtourModel):
    feature_id: str
    source_record_key: str
    source_role: SourceRole | str = SourceRole.ENRICHMENT
    match_method: str
    confidence: int = Field(..., ge=0, le=100)
    is_primary_source: bool = False
    created_at: datetime = Field(default_factory=kst_now)


def _minute_of_week(day: int, time_value: str) -> int:
    hour = int(time_value[:2])
    minute = int(time_value[2:])
    return day * 24 * 60 + hour * 60 + minute


class OpeningTime(KrtourModel):
    """Google Places-style weekday/time point for feature opening hours."""

    day: int = Field(..., ge=0, le=6)
    time: str = Field(..., pattern=r"^(?:[01]\d|2[0-3])[0-5]\d$")

    @computed_field
    @property
    def parsed_time(self) -> time:
        return time(hour=int(self.time[:2]), minute=int(self.time[2:]))


class OpeningPeriod(KrtourModel):
    """One continuous opening interval.

    `close=None` is reserved for the Google Places 24/7 signature:
    open Sunday 00:00 with no close time.
    """

    open: OpeningTime
    close: OpeningTime | None = None

    @model_validator(mode="after")
    def validate_period(self) -> OpeningPeriod:
        if self.close is None:
            if self.open.day == 0 and self.open.time == "0000":
                return self
            raise ValueError("close can be omitted only for a 24/7 period")

        start = _minute_of_week(self.open.day, self.open.time)
        end = _minute_of_week(self.close.day, self.close.time)
        if self.close.day == self.open.day and end <= start:
            raise ValueError("same-day close time must be after open time")
        return self

    @computed_field
    @property
    def duration_minutes(self) -> int:
        if self.close is None:
            return 7 * 24 * 60
        start = _minute_of_week(self.open.day, self.open.time)
        end = _minute_of_week(self.close.day, self.close.time)
        if end <= start:
            end += 7 * 24 * 60
        return end - start


class SpecialOpeningDay(KrtourModel):
    date: date
    is_closed: bool = False
    periods: list[OpeningPeriod] | None = None
    exceptional_hours: bool = True

    @model_validator(mode="after")
    def validate_special_day(self) -> SpecialOpeningDay:
        if self.is_closed and self.periods:
            raise ValueError("closed special days cannot define opening periods")
        if not self.is_closed and not self.periods:
            raise ValueError("open special days must define at least one opening period")
        return self


class FeatureOpeningHours(KrtourModel):
    timezone: str = "Asia/Seoul"
    open_now: bool | None = None
    periods: list[OpeningPeriod] = Field(default_factory=list)
    special_days: list[SpecialOpeningDay] = Field(default_factory=list)
    weekday_text: list[str] = Field(default_factory=list)


class EventDetail(KrtourModel):
    feature_id: str
    event_kind: str = "festival"
    starts_on: date | None = None
    ends_on: date | None = None
    timezone: str = "Asia/Seoul"
    opening_hours: FeatureOpeningHours | None = None
    venue_name: str | None = None
    tel: str | None = None
    content_id: str | None = None
    content_type_id: str | None = None
    area_code: str | None = None
    sigungu_code: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dates(self) -> EventDetail:
        if (
            self.starts_on is not None
            and self.ends_on is not None
            and self.ends_on < self.starts_on
        ):
            raise ValueError("ends_on must be greater than or equal to starts_on")
        return self


class WeatherValue(KrtourModel):
    feature_id: str
    provider: str
    weather_domain: WeatherDomain | str
    forecast_style: ForecastStyle | str
    timeline_bucket: TimelineBucket | str | None = None
    metric_key: str = Field(..., min_length=1)
    issued_at: datetime | None = None
    valid_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    observed_at: datetime | None = None
    source_metric_key: str | None = None
    source_metric_name: str | None = None
    metric_name: str | None = None
    value_number: Decimal | None = None
    value_text: str | None = None
    unit: str | None = None
    severity: str | None = None
    normalization_version: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=kst_now)
    source_record_key: str | None = None

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return normalize_provider_name(value)

    def identity(self) -> tuple[Any, ...]:
        return (
            self.feature_id,
            self.provider,
            str(self.weather_domain),
            str(self.forecast_style),
            self.metric_key,
            self.issued_at,
            self.valid_at,
            self.observed_at,
        )


class PricePoint(KrtourModel):
    feature_id: str
    price_category: str
    retention_days: int = Field(default=3650, ge=1)


class PriceValue(KrtourModel):
    feature_id: str
    item_key: str
    observed_at: datetime
    value: Decimal
    currency: str = Field(default="KRW", min_length=3, max_length=3)
    payload_hash: str | None = None


class ProviderSyncState(KrtourModel):
    provider: str
    dataset_key: str
    sync_scope: str = "global"
    status: str = "active"
    cursor: dict[str, Any] | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_run_after: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=kst_now)

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return normalize_provider_name(value)

    def identity(self) -> tuple[str, str, str]:
        return (self.provider, self.dataset_key, self.sync_scope)


class FeatureSummary(KrtourModel):
    feature_id: str
    kind: str
    name: str
    category: str
    provider_count: int
    status: str
