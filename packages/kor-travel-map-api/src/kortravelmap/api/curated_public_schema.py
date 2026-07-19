"""공개 curated feature의 strict DTO와 fail-closed projection.

저장소의 ``CuratedFeature``는 admin 감사와 provider 원문을 함께 보유한다. 공개
응답은 이 모듈에서 사람이 소비할 필드만 새 객체로 조립해 그 내부 구조가 공개
계약으로 우연히 승격되는 것을 막는다(T-VN-05R, ADR-073).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Annotated, Any, Literal, TypeAlias
from urllib.parse import urlsplit

from kortravelmap.infra.curated_repo import CuratedFeature
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, RootModel

from kortravelmap.api.response import Meta

_PHONE_PATTERN = r"^\+?[0-9][0-9() -]{2,30}$"
_PHONE_RE = re.compile(_PHONE_PATTERN)
_HHMM_RE = re.compile(r"^([01]\d|2[0-3])[0-5]\d$")
PublicPhone: TypeAlias = Annotated[str, Field(pattern=_PHONE_PATTERN)]


class _StrictPublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicCuratedAddress(_StrictPublicModel):
    """표시용 주소만 포함하는 공개 주소 계약."""

    road: str | None = None
    legal: str | None = None
    admin: str | None = None
    zipcode: str | None = Field(default=None, pattern=r"^\d{5}$")
    sido_name: str | None = None
    sigungu_name: str | None = None


class PublicCuratedOpeningTime(_StrictPublicModel):
    day: int = Field(ge=0, le=6)
    time: str = Field(pattern=r"^([01]\d|2[0-3])[0-5]\d$")


class PublicCuratedOpeningPeriod(_StrictPublicModel):
    open: PublicCuratedOpeningTime
    close: PublicCuratedOpeningTime | None = None


class PublicCuratedSpecialOpeningDay(_StrictPublicModel):
    date: date
    is_closed: bool = False
    periods: list[PublicCuratedOpeningPeriod] | None = None
    exceptional_hours: bool = True


class PublicCuratedOpeningHours(_StrictPublicModel):
    """자유 텍스트 없이 구조화된 KST 영업시간만 노출한다."""

    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    open_now: bool | None = None
    periods: list[PublicCuratedOpeningPeriod] = Field(default_factory=list)
    special_days: list[PublicCuratedSpecialOpeningDay] = Field(default_factory=list)


class PublicCuratedReviewLinks(_StrictPublicModel):
    """검토된 리뷰 서비스의 HTTP(S) 링크."""

    naver: AnyHttpUrl | None = None
    kakao: AnyHttpUrl | None = None
    google: AnyHttpUrl | None = None
    tripadvisor: AnyHttpUrl | None = None


class PublicCuratedPlaceFacilityInfo(_StrictPublicModel):
    """공개 표시 가치가 확인된 place 시설 필드.

    provider identity와 concierge 영상·transcript·evidence 미러는 의도적으로
    선언하지 않는다. 새 필드는 공개 계약 검토 후에만 이 모델과 projector 양쪽에
    추가한다.
    """

    description: str | None = None
    gemini_enriched_description: str | None = None
    category_label: str | None = None
    wheelchair: bool | None = None
    fclty_type: str | None = None
    homepage_url: AnyHttpUrl | None = None
    trrsrt_se: str | None = None
    prkplce_se: str | None = None
    prkcmprt: int | None = None
    parkingchrge_info: str | None = None
    stret_intrcn: str | None = None
    stret_lt: float | None = None
    stor_number: int | None = None
    appn_year: int | None = None
    institution_nm: str | None = None
    instt_nm: str | None = None
    reference_date: str | None = None
    forest_type: str | None = None
    provider_category: str | None = None
    region_name: str | None = None
    direction: str | None = None
    highway_name: str | None = None
    beach_kind: str | None = None
    image_url: AnyHttpUrl | None = None
    icao_code: str | None = None
    name_english: str | None = None
    brand_code: str | None = None
    lpg_yn: bool | None = None
    service_slug: str | None = None
    category: str | None = None
    subtype_name: str | None = None
    sales_method_name: str | None = None
    source_category: str | None = None
    region: str | None = None
    management_agency: str | None = None
    media_title: str | None = None
    operating_time: str | None = None
    operator: str | None = None
    hole_count: str | None = None


class PublicCuratedPlaceDetail(_StrictPublicModel):
    feature_id: str
    place_kind: str = "place"
    phones: list[PublicPhone] = Field(default_factory=list, max_length=3)
    reviews_link: PublicCuratedReviewLinks = Field(
        default_factory=PublicCuratedReviewLinks
    )
    business_hours: PublicCuratedOpeningHours | None = None
    facility_info: PublicCuratedPlaceFacilityInfo = Field(
        default_factory=PublicCuratedPlaceFacilityInfo
    )
    license_date: date | None = None
    biz_number: str | None = None


class PublicCuratedEventDetail(_StrictPublicModel):
    feature_id: str
    event_kind: str = "festival"
    starts_on: date | None = None
    ends_on: date | None = None
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    opening_hours: PublicCuratedOpeningHours | None = None
    venue_name: str | None = None
    tel: PublicPhone | None = None
    content_id: str | None = None
    content_type_id: str | None = None
    area_code: str | None = None
    sigungu_code: str | None = None


class PublicCuratedNoticeDetail(_StrictPublicModel):
    feature_id: str
    notice_type: str
    severity: int | None = Field(default=None, ge=0, le=5)
    valid_start_time: datetime | None = None
    valid_end_time: datetime | None = None
    source_agency: str | None = None
    officer_name: str | None = None


class PublicCuratedAreaDetail(_StrictPublicModel):
    feature_id: str
    area_kind: str = "area"
    boundary_source: str | None = None
    area_square_meters: float | None = Field(default=None, ge=0)
    regulation_scope: str | None = None
    administrative_office: str | None = None
    description: str | None = None


class PublicCuratedRouteDetail(_StrictPublicModel):
    feature_id: str
    route_type: str = "route"
    geometry_source: str | None = None
    geometry_status: str | None = None
    total_distance_meters: float | None = Field(default=None, ge=0)
    expected_duration_minutes: int | None = Field(default=None, ge=1)
    difficulty: str | None = None
    begin_name: str | None = None
    begin_address: str | None = None
    end_name: str | None = None
    end_address: str | None = None


class PublicCuratedFeatureBase(_StrictPublicModel):
    curated_feature_id: str
    theme_slug: str
    theme_name: str
    theme_group: str
    feature_id: str
    feature_name: str
    feature_category: str
    lon: float | None = None
    lat: float | None = None
    sido_code: str | None = None
    sigungu_code: str | None = None
    legal_dong_code: str | None = None
    address: PublicCuratedAddress
    source_name: str
    source_url: AnyHttpUrl | None = None
    display_title: str | None = None
    display_summary: str | None = None
    curation_relation: str
    reuse_policy: str
    content_version: int
    updated_at: datetime


class PublicCuratedPlaceFeatureView(PublicCuratedFeatureBase):
    feature_kind: Literal["place"]
    detail: PublicCuratedPlaceDetail


class PublicCuratedEventFeatureView(PublicCuratedFeatureBase):
    feature_kind: Literal["event"]
    detail: PublicCuratedEventDetail


class PublicCuratedNoticeFeatureView(PublicCuratedFeatureBase):
    feature_kind: Literal["notice"]
    detail: PublicCuratedNoticeDetail


class PublicCuratedAreaFeatureView(PublicCuratedFeatureBase):
    feature_kind: Literal["area"]
    detail: PublicCuratedAreaDetail


class PublicCuratedRouteFeatureView(PublicCuratedFeatureBase):
    feature_kind: Literal["route"]
    detail: PublicCuratedRouteDetail


class PublicCuratedPriceFeatureView(PublicCuratedFeatureBase):
    feature_kind: Literal["price"]
    detail: None = None


class PublicCuratedWeatherFeatureView(PublicCuratedFeatureBase):
    feature_kind: Literal["weather"]
    detail: None = None


PublicCuratedFeatureUnion: TypeAlias = Annotated[
    PublicCuratedPlaceFeatureView
    | PublicCuratedEventFeatureView
    | PublicCuratedNoticeFeatureView
    | PublicCuratedAreaFeatureView
    | PublicCuratedRouteFeatureView
    | PublicCuratedPriceFeatureView
    | PublicCuratedWeatherFeatureView,
    Field(discriminator="feature_kind"),
]


class PublicCuratedFeatureView(RootModel[PublicCuratedFeatureUnion]):
    """``feature_kind``가 판별자인 공개 feature union."""


class PublicCuratedFeaturesData(_StrictPublicModel):
    items: list[PublicCuratedFeatureView]


class PublicCuratedFeaturesResponse(_StrictPublicModel):
    data: PublicCuratedFeaturesData
    meta: Meta


class PublicCuratedFeatureResponse(_StrictPublicModel):
    data: PublicCuratedFeatureView
    meta: Meta


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    result = value.strip()
    return result or None


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(Decimal(value.strip()))
        except (InvalidOperation, ValueError):
            return None
    else:
        return None
    return result if isfinite(result) else None


def _date(value: object) -> date | None:
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    text = _text(value)
    if text is None:
        return None
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo is not None else None


def _http_url(value: object) -> str | None:
    text = _text(value)
    if text is None:
        return None
    parsed = urlsplit(text)
    return text if parsed.scheme in {"http", "https"} and parsed.hostname else None


def _phone(value: object) -> str | None:
    text = _text(value)
    return text if text is not None and _PHONE_RE.fullmatch(text) else None


def _opening_time(value: object) -> PublicCuratedOpeningTime | None:
    raw = _mapping(value)
    day = _int(raw.get("day"))
    time = _text(raw.get("time"))
    if day is None or not 0 <= day <= 6 or time is None or not _HHMM_RE.fullmatch(time):
        return None
    return PublicCuratedOpeningTime(day=day, time=time)


def _opening_period(value: object) -> PublicCuratedOpeningPeriod | None:
    raw = _mapping(value)
    opened = _opening_time(raw.get("open"))
    if opened is None:
        return None
    closed = _opening_time(raw.get("close"))
    return PublicCuratedOpeningPeriod(open=opened, close=closed)


def _opening_hours(value: object) -> PublicCuratedOpeningHours | None:
    if not isinstance(value, Mapping):
        return None
    periods = (
        [
            period
            for item in value.get("periods", [])
            if (period := _opening_period(item)) is not None
        ]
        if isinstance(value.get("periods"), list)
        else []
    )
    special_days: list[PublicCuratedSpecialOpeningDay] = []
    raw_special_days = value.get("special_days")
    if isinstance(raw_special_days, list):
        for item in raw_special_days:
            raw = _mapping(item)
            special_date = _date(raw.get("date"))
            if special_date is None:
                continue
            raw_periods = raw.get("periods")
            special_periods = (
                [
                    period
                    for raw_period in raw_periods
                    if (period := _opening_period(raw_period)) is not None
                ]
                if isinstance(raw_periods, list)
                else None
            )
            special_days.append(
                PublicCuratedSpecialOpeningDay(
                    date=special_date,
                    is_closed=_bool(raw.get("is_closed")) or False,
                    periods=special_periods,
                    exceptional_hours=(
                        exceptional
                        if (exceptional := _bool(raw.get("exceptional_hours")))
                        is not None
                        else True
                    ),
                )
            )
    return PublicCuratedOpeningHours(
        open_now=_bool(value.get("open_now")),
        periods=periods,
        special_days=special_days,
    )


def _address(value: object) -> PublicCuratedAddress:
    raw = _mapping(value)
    zipcode = _text(raw.get("zipcode"))
    return PublicCuratedAddress(
        road=_text(raw.get("road")),
        legal=_text(raw.get("legal")),
        admin=_text(raw.get("admin")),
        zipcode=(
            zipcode
            if zipcode is not None and re.fullmatch(r"\d{5}", zipcode)
            else None
        ),
        sido_name=_text(raw.get("sido_name")),
        sigungu_name=_text(raw.get("sigungu_name")),
    )


def _review_links(value: object) -> PublicCuratedReviewLinks:
    raw = _mapping(value)
    return PublicCuratedReviewLinks.model_validate(
        {
            service: url
            for service in ("naver", "kakao", "google", "tripadvisor")
            if (url := _http_url(raw.get(service))) is not None
        }
    )


_FACILITY_TEXT_FIELDS = (
    "description",
    "gemini_enriched_description",
    "category_label",
    "fclty_type",
    "trrsrt_se",
    "prkplce_se",
    "parkingchrge_info",
    "stret_intrcn",
    "institution_nm",
    "instt_nm",
    "reference_date",
    "forest_type",
    "provider_category",
    "region_name",
    "direction",
    "highway_name",
    "beach_kind",
    "icao_code",
    "name_english",
    "brand_code",
    "service_slug",
    "category",
    "subtype_name",
    "sales_method_name",
    "source_category",
    "region",
    "management_agency",
    "media_title",
    "operating_time",
    "operator",
    "hole_count",
)
_FACILITY_URL_FIELDS = ("homepage_url", "image_url")
_FACILITY_INT_FIELDS = ("prkcmprt", "stor_number", "appn_year")
_FACILITY_NUMBER_FIELDS = ("stret_lt",)
_FACILITY_BOOL_FIELDS = ("wheelchair", "lpg_yn")


def _facility_info(value: object) -> PublicCuratedPlaceFacilityInfo:
    raw = _mapping(value)
    projected: dict[str, str | bool | int | float] = {}
    for field in _FACILITY_TEXT_FIELDS:
        if (text := _text(raw.get(field))) is not None:
            projected[field] = text
    for field in _FACILITY_URL_FIELDS:
        if (url := _http_url(raw.get(field))) is not None:
            projected[field] = url
    for field in _FACILITY_INT_FIELDS:
        if (integer := _int(raw.get(field))) is not None:
            projected[field] = integer
    for field in _FACILITY_NUMBER_FIELDS:
        if (number := _number(raw.get(field))) is not None:
            projected[field] = number
    for field in _FACILITY_BOOL_FIELDS:
        if (boolean := _bool(raw.get(field))) is not None:
            projected[field] = boolean
    return PublicCuratedPlaceFacilityInfo.model_validate(projected)


def _optional_text_fields(
    raw: Mapping[str, Any], fields: tuple[str, ...]
) -> dict[str, str]:
    return {
        field: value
        for field in fields
        if (value := _text(raw.get(field))) is not None
    }


def _place_detail(row: CuratedFeature) -> PublicCuratedPlaceDetail:
    raw = _mapping(row.detail)
    raw_phones = raw.get("phones")
    phones = (
        [phone for item in raw_phones if (phone := _phone(item)) is not None][:3]
        if isinstance(raw_phones, list)
        else []
    )
    return PublicCuratedPlaceDetail(
        feature_id=row.feature_id,
        place_kind=_text(raw.get("place_kind")) or "place",
        phones=phones,
        reviews_link=_review_links(raw.get("reviews_link")),
        business_hours=_opening_hours(raw.get("business_hours")),
        facility_info=_facility_info(raw.get("facility_info")),
        license_date=_date(raw.get("license_date")),
        biz_number=_text(raw.get("biz_number")),
    )


def _event_detail(row: CuratedFeature) -> PublicCuratedEventDetail:
    raw = _mapping(row.detail)
    return PublicCuratedEventDetail(
        feature_id=row.feature_id,
        event_kind=_text(raw.get("event_kind")) or "festival",
        starts_on=_date(raw.get("starts_on")),
        ends_on=_date(raw.get("ends_on")),
        opening_hours=_opening_hours(raw.get("opening_hours")),
        tel=_phone(raw.get("tel")),
        **_optional_text_fields(
            raw,
            ("venue_name", "content_id", "content_type_id", "area_code", "sigungu_code"),
        ),
    )


def _notice_detail(row: CuratedFeature) -> PublicCuratedNoticeDetail:
    raw = _mapping(row.detail)
    severity = _int(raw.get("severity"))
    return PublicCuratedNoticeDetail(
        feature_id=row.feature_id,
        notice_type=_text(raw.get("notice_type")) or "notice",
        severity=severity if severity is not None and 0 <= severity <= 5 else None,
        valid_start_time=_datetime(raw.get("valid_start_time")),
        valid_end_time=_datetime(raw.get("valid_end_time")),
        **_optional_text_fields(raw, ("source_agency", "officer_name")),
    )


def _area_detail(row: CuratedFeature) -> PublicCuratedAreaDetail:
    raw = _mapping(row.detail)
    area = _number(raw.get("area_square_meters"))
    return PublicCuratedAreaDetail(
        feature_id=row.feature_id,
        area_kind=_text(raw.get("area_kind")) or "area",
        area_square_meters=area if area is not None and area >= 0 else None,
        **_optional_text_fields(
            raw,
            ("boundary_source", "regulation_scope", "administrative_office", "description"),
        ),
    )


def _route_detail(row: CuratedFeature) -> PublicCuratedRouteDetail:
    raw = _mapping(row.detail)
    distance = _number(raw.get("total_distance_meters"))
    duration = _int(raw.get("expected_duration_minutes"))
    return PublicCuratedRouteDetail(
        feature_id=row.feature_id,
        route_type=_text(raw.get("route_type")) or "route",
        total_distance_meters=distance if distance is not None and distance >= 0 else None,
        expected_duration_minutes=duration if duration is not None and duration >= 1 else None,
        **_optional_text_fields(
            raw,
            (
                "geometry_source",
                "geometry_status",
                "difficulty",
                "begin_name",
                "begin_address",
                "end_name",
                "end_address",
            ),
        ),
    )


def public_curated_feature_view(
    row: CuratedFeature,
) -> PublicCuratedFeatureView | None:
    """admin row를 공개 union으로 투영한다. 알 수 없는 kind는 공개하지 않는다."""

    common: dict[str, Any] = {
        "curated_feature_id": row.curated_feature_id,
        "theme_slug": row.theme_slug,
        "theme_name": row.theme_name,
        "theme_group": row.theme_group,
        "feature_id": row.feature_id,
        "feature_name": row.feature_name,
        "feature_category": row.feature_category,
        "lon": row.lon,
        "lat": row.lat,
        "sido_code": row.sido_code,
        "sigungu_code": row.sigungu_code,
        "legal_dong_code": row.legal_dong_code,
        "address": _address(row.address),
        "source_name": row.source_name,
        "source_url": _http_url(row.source_url),
        "display_title": row.display_title,
        "display_summary": row.display_summary,
        "curation_relation": row.curation_relation,
        "reuse_policy": row.reuse_policy,
        "content_version": row.content_version,
        "updated_at": row.updated_at,
    }
    if row.feature_kind == "place":
        root: PublicCuratedFeatureUnion = PublicCuratedPlaceFeatureView(
            feature_kind="place", detail=_place_detail(row), **common
        )
    elif row.feature_kind == "event":
        root = PublicCuratedEventFeatureView(
            feature_kind="event", detail=_event_detail(row), **common
        )
    elif row.feature_kind == "notice":
        root = PublicCuratedNoticeFeatureView(
            feature_kind="notice", detail=_notice_detail(row), **common
        )
    elif row.feature_kind == "area":
        root = PublicCuratedAreaFeatureView(
            feature_kind="area", detail=_area_detail(row), **common
        )
    elif row.feature_kind == "route":
        root = PublicCuratedRouteFeatureView(
            feature_kind="route", detail=_route_detail(row), **common
        )
    elif row.feature_kind == "price":
        root = PublicCuratedPriceFeatureView(feature_kind="price", **common)
    elif row.feature_kind == "weather":
        root = PublicCuratedWeatherFeatureView(feature_kind="weather", **common)
    else:
        return None
    return PublicCuratedFeatureView(root=root)
