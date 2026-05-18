from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from kraddr.base import Address

from krtour_map.addressing import (
    AddressMatchReport,
    ReverseGeocoder,
    enrich_address_from_coordinate,
)
from krtour_map.db import FeatureDbLoadResult, load_feature_rows
from krtour_map.enums import FeatureKind, SourceRole
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import (
    Coordinate,
    Feature,
    FeatureOpeningHours,
    PlaceDetail,
    PricePoint,
    PriceValue,
    RawDataRef,
    SourceLink,
    SourceRecord,
)

OPINET_PROVIDER = "python-opinet-api"
OPINET_STATION_DETAIL_DATASET_KEY = "opinet_fuel_station_details"
OPINET_STATION_SOURCE_TYPE = "fuel_station"
OPINET_STATION_CATEGORY = "fuel"
OPINET_STATION_MARKER_ICON = "fuel"
OPINET_STATION_MARKER_COLOR = "#2E7D32"
OPINET_PRICE_CATEGORY = "fuel"
OPINET_PRICE_RETENTION_DAYS = 3650


@dataclass(frozen=True)
class OpinetStationFeatureBundle:
    feature: Feature
    place_detail: PlaceDetail
    price_point: PricePoint
    price_values: tuple[PriceValue, ...]
    source_record: SourceRecord
    source_link: SourceLink
    address_match_report: AddressMatchReport


def opinet_station_detail_to_feature_bundle(
    detail: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> OpinetStationFeatureBundle:
    """Normalize a stable `python-opinet-api` station detail model into feature rows."""

    normalized = _normalized_station_detail(detail)
    raw = _raw_mapping(normalized)
    station_id = _required_text(normalized, "provider_station_id")
    station_name = _required_text(normalized, "provider_station_name")
    coordinate = _coordinate_from_station(normalized)
    address_enrichment = enrich_address_from_coordinate(
        address=_address_from_station(normalized),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=OPINET_STATION_DETAIL_DATASET_KEY,
        source_entity_id=station_id,
    )
    address = address_enrichment.address
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=OPINET_PROVIDER,
        source_type=OPINET_STATION_SOURCE_TYPE,
        source_natural_key=station_id,
        kind=FeatureKind.PLACE,
        category=OPINET_STATION_CATEGORY,
        legal_dong_code=getattr(address, "legal_dong_code", None),
    )
    source_record = SourceRecord(
        provider=OPINET_PROVIDER,
        dataset_key=OPINET_STATION_DETAIL_DATASET_KEY,
        source_entity_type=OPINET_STATION_SOURCE_TYPE,
        source_entity_id=station_id,
        raw_payload_hash=raw_payload_hash,
        raw_name=station_name,
        raw_address=address.display_address,
        raw_longitude=Decimal(str(coordinate.longitude)),
        raw_latitude=Decimal(str(coordinate.latitude)),
        raw_data=raw,
        fetched_at=collected_at,
        imported_at=collected_at or _now_kst(),
    )
    source_record_key = source_record.key()
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=station_name,
        coord=coordinate,
        address=address,
        category=OPINET_STATION_CATEGORY,
        marker_icon=OPINET_STATION_MARKER_ICON,
        marker_color=OPINET_STATION_MARKER_COLOR,
        detail=_station_detail_payload(normalized),
        raw_refs=[
            RawDataRef(
                provider=OPINET_PROVIDER,
                dataset_key=OPINET_STATION_DETAIL_DATASET_KEY,
                source_entity_id=station_id,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected_at,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    place_detail = PlaceDetail(
        feature_id=feature_id,
        place_kind=_place_kind(normalized),
        phones=[tel] if (tel := _optional_text(getattr(normalized, "tel", None))) else [],
        business_hours=_opening_hours_from_station(normalized),
        facility_info=_facility_info(normalized),
        payload=_station_detail_payload(normalized),
    )
    price_values = tuple(
        price_value
        for price in getattr(normalized, "prices", ())
        if (price_value := _price_value(feature_id, price)) is not None
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="opinet_station_id",
        confidence=100,
        is_primary_source=True,
    )
    return OpinetStationFeatureBundle(
        feature=feature,
        place_detail=place_detail,
        price_point=PricePoint(
            feature_id=feature_id,
            price_category=OPINET_PRICE_CATEGORY,
            retention_days=OPINET_PRICE_RETENTION_DAYS,
        ),
        price_values=price_values,
        source_record=source_record,
        source_link=source_link,
        address_match_report=address_enrichment.report,
    )


def load_opinet_station_detail(
    session: Any,
    detail: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> FeatureDbLoadResult:
    """Stage a normalized OpiNet station detail bundle in the feature DB session."""

    bundle = opinet_station_detail_to_feature_bundle(
        detail,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )
    return load_feature_rows(
        session,
        feature_items=[bundle.feature],
        source_record_items=[bundle.source_record],
        source_link_items=[bundle.source_link],
        place_detail_items=[bundle.place_detail],
        price_point_items=[bundle.price_point],
        price_value_items=bundle.price_values,
    )


def _normalized_station_detail(detail: Any) -> Any:
    to_normalized = getattr(detail, "to_normalized", None)
    if callable(to_normalized):
        return to_normalized()
    return detail


def _coordinate_from_station(station: Any) -> Coordinate:
    coordinate = getattr(station, "coordinate", None)
    if coordinate is not None:
        return coordinate
    return Coordinate(
        lat=float(station.lat),
        lon=float(station.lon),
    )


def _address_from_station(station: Any) -> Address:
    road = _optional_text(getattr(station, "address_road", None))
    jibun = _optional_text(getattr(station, "address_jibun", None))
    return Address.from_mapping({"road_address": road, "jibun_address": jibun}) or Address(
        address=road or jibun
    )


def _opening_hours_from_station(station: Any) -> FeatureOpeningHours | None:
    value = getattr(station, "business_hours", None)
    if value is None:
        value = getattr(station, "opening_hours", None)
    if value is None:
        return None
    if isinstance(value, FeatureOpeningHours):
        return value
    if isinstance(value, Mapping):
        return FeatureOpeningHours.model_validate(value)
    if hasattr(value, "model_dump"):
        return FeatureOpeningHours.model_validate(value.model_dump(mode="json"))
    return None


def _station_detail_payload(station: Any) -> dict[str, Any]:
    return {
        "provider_station_id": _optional_text(getattr(station, "provider_station_id", None)),
        "provider_endpoint": _optional_text(getattr(station, "provider_endpoint", None)),
        "brand_code": _enum_text(getattr(station, "brand_code", None)),
        "sub_brand_code": _enum_text(getattr(station, "sub_brand_code", None)),
        "station_type": _enum_text(getattr(station, "station_type", None)),
        "sigun_code": _optional_text(getattr(station, "sigun_code", None)),
        "katec_x": getattr(station, "katec_x", None),
        "katec_y": getattr(station, "katec_y", None),
        "has_maintenance": getattr(station, "has_maintenance", None),
        "has_carwash": getattr(station, "has_carwash", None),
        "has_cvs": getattr(station, "has_cvs", None),
        "is_kpetro": getattr(station, "is_kpetro", None),
    }


def _facility_info(station: Any) -> dict[str, Any]:
    return {
        "brand_code": _enum_text(getattr(station, "brand_code", None)),
        "sub_brand_code": _enum_text(getattr(station, "sub_brand_code", None)),
        "station_type": _enum_text(getattr(station, "station_type", None)),
        "sigun_code": _optional_text(getattr(station, "sigun_code", None)),
        "maintenance": bool(getattr(station, "has_maintenance", False)),
        "car_wash": bool(getattr(station, "has_carwash", False)),
        "cvs": bool(getattr(station, "has_cvs", False)),
        "kpetro": bool(getattr(station, "is_kpetro", False)),
    }


def _place_kind(station: Any) -> str:
    station_type = getattr(station, "station_type", None)
    station_type_name = _optional_text(getattr(station_type, "name", None))
    station_type_value = _enum_text(station_type)
    station_type_text = " ".join(
        text.lower() for text in (station_type_name, station_type_value) if text
    )
    if "both" in station_type_text or station_type_value == "C":
        return "fuel_lpg_station"
    if "lpg" in station_type_text or station_type_value == "Y":
        return "lpg_station"
    return "fuel_station"


def _price_value(feature_id: str, price: Any) -> PriceValue | None:
    value = getattr(price, "price", None)
    observed_at = _trade_datetime(price)
    if value is None or observed_at is None:
        return None
    raw = _raw_mapping(price)
    item_key = _enum_text(getattr(price, "fuel_type", None)) or _optional_text(
        getattr(price, "provider_product_code", None)
    )
    if item_key is None:
        return None
    return PriceValue(
        feature_id=feature_id,
        item_key=item_key,
        observed_at=observed_at,
        value=Decimal(str(value)),
        payload_hash=make_payload_hash(raw, length=32),
    )


def _trade_datetime(price: Any) -> datetime | None:
    trade_datetime = getattr(price, "trade_datetime", None)
    if callable(trade_datetime):
        return trade_datetime()
    trade_date = getattr(price, "trade_date", None)
    trade_time = getattr(price, "trade_time", None)
    if not isinstance(trade_date, date) or not isinstance(trade_time, time):
        return None
    return datetime.combine(trade_date, trade_time, tzinfo=_now_kst().tzinfo)


def _raw_mapping(item: Any) -> dict[str, Any]:
    raw = getattr(item, "raw", None)
    if isinstance(raw, Mapping):
        return dict(raw)
    if hasattr(item, "model_dump"):
        dumped = item.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    if isinstance(item, Mapping):
        return dict(item)
    return {}


def _required_text(item: Any, attr: str) -> str:
    value = _optional_text(getattr(item, attr, None))
    if value is None:
        raise ValueError(f"{attr} is required")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _enum_text(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", value)
    return _optional_text(enum_value)


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
