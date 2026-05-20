from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from kraddr.base import Address, PlaceCategoryCode

from krtour_map.addressing import (
    AddressMatchReport,
    ReverseGeocoder,
    enrich_address_from_coordinate,
)
from krtour_map.db import FeatureDbLoadResult, load_feature_rows
from krtour_map.enums import FeatureKind, ForecastStyle, SourceRole, WeatherDomain
from krtour_map.etl import page_items
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import (
    Coordinate,
    Feature,
    PlaceDetail,
    PricePoint,
    PriceValue,
    RawDataRef,
    SourceLink,
    SourceRecord,
    WeatherValue,
)

KREX_PROVIDER = "python-krex-api"
KREX_REST_AREA_DATASET_KEY = "krex_rest_areas"
KREX_REST_AREA_FUEL_PRICE_DATASET_KEY = "krex_rest_area_fuel_prices"
KREX_REST_AREA_WEATHER_DATASET_KEY = "krex_rest_area_weather"
KREX_REST_AREA_SOURCE_TYPE = "rest_area"
KREX_REST_AREA_PRICE_SOURCE_TYPE = "rest_area_fuel_price"
KREX_REST_AREA_CATEGORY = PlaceCategoryCode.TRANSPORT_REST_AREA.value
KREX_REST_AREA_FULL_SCAN_INTERVAL_DAYS = 30
KREX_REST_AREA_PRICE_INTERVAL_HOURS = 6
KREX_REST_AREA_WEATHER_INTERVAL_MINUTES = 60
KREX_PRICE_RETENTION_DAYS = 3650


@dataclass(frozen=True)
class SkippedHighwayItem:
    dataset_key: str
    source_entity_id: str | None
    reason: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class HighwayRestAreaBundle:
    feature: Feature
    place_detail: PlaceDetail
    source_record: SourceRecord
    source_link: SourceLink
    address_match_report: AddressMatchReport


@dataclass(frozen=True)
class HighwayFeatureEtlResult:
    dataset_key: str
    features: tuple[Feature, ...]
    place_details: tuple[PlaceDetail, ...]
    source_records: tuple[SourceRecord, ...]
    source_links: tuple[SourceLink, ...]
    price_points: tuple[PricePoint, ...] = ()
    price_values: tuple[PriceValue, ...] = ()
    weather_values: tuple[WeatherValue, ...] = ()
    address_match_reports: tuple[AddressMatchReport, ...] = ()
    skipped_items: tuple[SkippedHighwayItem, ...] = ()
    scanned_pages: int = 0

    @property
    def item_count(self) -> int:
        return len(self.features) + len(self.price_values) + len(self.weather_values)


@dataclass(frozen=True)
class HighwayFeatureDbEtlResult:
    collection: HighwayFeatureEtlResult
    load: FeatureDbLoadResult

    @property
    def item_count(self) -> int:
        return self.collection.item_count


def collect_krex_rest_area_features(
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    scanned_pages: int = 0,
) -> HighwayFeatureEtlResult:
    features: list[Feature] = []
    place_details: list[PlaceDetail] = []
    source_records: list[SourceRecord] = []
    source_links: list[SourceLink] = []
    reports: list[AddressMatchReport] = []
    skipped: list[SkippedHighwayItem] = []
    for item in items:
        bundle = krex_rest_area_to_feature_bundle(
            item,
            collected_at=collected_at,
            reverse_geocoder=reverse_geocoder,
        )
        if isinstance(bundle, SkippedHighwayItem):
            skipped.append(bundle)
            continue
        features.append(bundle.feature)
        place_details.append(bundle.place_detail)
        source_records.append(bundle.source_record)
        source_links.append(bundle.source_link)
        reports.append(bundle.address_match_report)
    return HighwayFeatureEtlResult(
        dataset_key=KREX_REST_AREA_DATASET_KEY,
        features=tuple(features),
        place_details=tuple(place_details),
        source_records=tuple(source_records),
        source_links=tuple(source_links),
        address_match_reports=tuple(reports),
        skipped_items=tuple(skipped),
        scanned_pages=scanned_pages,
    )


async def async_collect_krex_rest_area_features(
    client: Any,
    *,
    page_size: int = 1000,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> HighwayFeatureEtlResult:
    restarea = getattr(client, "restarea", None)
    method = getattr(restarea, "list_all", None)
    if not callable(method):
        raise ValueError("python-krex-api client must expose restarea.list_all")
    items: list[Any] = []
    scanned_pages = 0
    page_no = 1
    while True:
        page = await method(page_no=page_no, num_of_rows=page_size)
        scanned_pages += 1
        items.extend(page_items(page))
        if max_pages is not None and scanned_pages >= max_pages:
            break
        if not getattr(page, "has_next_page", False):
            break
        page_no = getattr(page, "next_page_no", None) or page_no + 1
    return collect_krex_rest_area_features(
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
        scanned_pages=scanned_pages,
    )


def krex_rest_area_to_feature_bundle(
    item: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> HighwayRestAreaBundle | SkippedHighwayItem:
    raw = _raw_mapping(item)
    name = _text(item, raw, "name", "service_area_name", "restAreaNm")
    source_key = _rest_area_source_key(item, raw)
    if source_key is None:
        return SkippedHighwayItem(KREX_REST_AREA_DATASET_KEY, None, "missing rest area key", raw)
    if name is None:
        return SkippedHighwayItem(
            KREX_REST_AREA_DATASET_KEY,
            source_key,
            "missing rest area name",
            raw,
        )
    coordinate = _coordinate(item, raw)
    enrichment = enrich_address_from_coordinate(
        address=_address(item, raw),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=KREX_REST_AREA_DATASET_KEY,
        source_entity_id=source_key,
    )
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=KREX_PROVIDER,
        source_type=KREX_REST_AREA_SOURCE_TYPE,
        source_natural_key=source_key,
        kind=FeatureKind.PLACE,
        category=KREX_REST_AREA_CATEGORY,
        legal_dong_code=enrichment.address.legal_dong_code,
    )
    source_record = SourceRecord(
        provider=KREX_PROVIDER,
        dataset_key=KREX_REST_AREA_DATASET_KEY,
        source_entity_type=KREX_REST_AREA_SOURCE_TYPE,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        source_version=_text(item, raw, "reference_date", "referenceDate"),
        raw_name=name,
        raw_address=enrichment.address.display_address,
        raw_longitude=Decimal(str(coordinate.longitude)) if coordinate is not None else None,
        raw_latitude=Decimal(str(coordinate.latitude)) if coordinate is not None else None,
        raw_data=dict(raw),
        fetched_at=collected_at,
        imported_at=collected_at or _now_kst(),
    )
    detail = {
        "selected_source": {
            "provider": KREX_PROVIDER,
            "dataset_key": KREX_REST_AREA_DATASET_KEY,
            "source_type": KREX_REST_AREA_SOURCE_TYPE,
            "source_entity_id": source_key,
        },
        "rest_area": _without_none(
            {
                "route_name": _text(item, raw, "route_name", "routeNm"),
                "direction": _text(item, raw, "direction"),
                "has_gas_station": getattr(item, "has_gas_station", None),
                "has_lpg_station": getattr(item, "has_lpg_station", None),
                "has_ev_charger": getattr(item, "has_ev_charger", None),
                "phone_number": _text(item, raw, "phone_number", "phoneNumber"),
                "reference_date": _text(item, raw, "reference_date", "referenceDate"),
            }
        ),
        "raw": dict(raw),
    }
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coordinate,
        address=enrichment.address,
        category=KREX_REST_AREA_CATEGORY,
        marker_icon="restaurant",
        marker_color="#805AD5",
        detail=detail,
        raw_refs=[
            RawDataRef(
                provider=KREX_PROVIDER,
                dataset_key=KREX_REST_AREA_DATASET_KEY,
                source_entity_id=source_key,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected_at,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    place_detail = PlaceDetail(
        feature_id=feature_id,
        place_kind="highway_rest_area",
        phones=[phone] if (phone := _text(item, raw, "phone_number", "phoneNumber")) else [],
        facility_info=detail["rest_area"],
        payload=detail,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record.key(),
        source_role=SourceRole.PRIMARY,
        match_method="krex_rest_area_key",
        confidence=100,
        is_primary_source=True,
    )
    return HighwayRestAreaBundle(
        feature=feature,
        place_detail=place_detail,
        source_record=source_record,
        source_link=source_link,
        address_match_report=enrichment.report,
    )


def collect_krex_rest_area_prices(
    items: Iterable[Any],
    *,
    feature_id_by_service_area_key: Mapping[str, str],
    observed_at: datetime | None = None,
) -> HighwayFeatureEtlResult:
    price_points: dict[str, PricePoint] = {}
    price_values: list[PriceValue] = []
    skipped: list[SkippedHighwayItem] = []
    for item in items:
        raw = _raw_mapping(item)
        service_key = _rest_area_source_key(item, raw)
        if service_key is None:
            skipped.append(
                SkippedHighwayItem(
                    KREX_REST_AREA_FUEL_PRICE_DATASET_KEY,
                    None,
                    "missing service area key",
                    raw,
                )
            )
            continue
        feature_id = feature_id_by_service_area_key.get(service_key)
        if feature_id is None:
            skipped.append(
                SkippedHighwayItem(
                    KREX_REST_AREA_FUEL_PRICE_DATASET_KEY,
                    service_key,
                    "missing feature mapping",
                    raw,
                )
            )
            continue
        price_points[feature_id] = PricePoint(
            feature_id=feature_id,
            price_category="fuel",
            retention_days=KREX_PRICE_RETENTION_DAYS,
        )
        when = observed_at or _now_kst()
        for attr, item_key in (
            ("gasoline_price", "gasoline"),
            ("diesel_price", "diesel"),
            ("lpg_price", "lpg"),
        ):
            value = getattr(item, attr, None)
            if value is None:
                value = raw.get(attr)
            if value in (None, ""):
                continue
            price_values.append(
                PriceValue(
                    feature_id=feature_id,
                    item_key=item_key,
                    observed_at=when,
                    value=Decimal(str(value)),
                    payload_hash=make_payload_hash({"item_key": item_key, "raw": raw}, length=32),
                )
            )
    return HighwayFeatureEtlResult(
        dataset_key=KREX_REST_AREA_FUEL_PRICE_DATASET_KEY,
        features=(),
        place_details=(),
        source_records=(),
        source_links=(),
        price_points=tuple(price_points.values()),
        price_values=tuple(price_values),
        skipped_items=tuple(skipped),
    )


def collect_krex_rest_area_weather_values(
    items: Iterable[Any],
    *,
    feature_id_by_unit_code: Mapping[str, str],
    collected_at: datetime | None = None,
) -> HighwayFeatureEtlResult:
    values: list[WeatherValue] = []
    skipped: list[SkippedHighwayItem] = []
    for item in items:
        raw = _raw_mapping(item)
        unit_code = _text(item, raw, "unit_code", "unitCode")
        if unit_code is None:
            skipped.append(
                SkippedHighwayItem(
                    KREX_REST_AREA_WEATHER_DATASET_KEY,
                    None,
                    "missing unit code",
                    raw,
                )
            )
            continue
        feature_id = feature_id_by_unit_code.get(unit_code)
        if feature_id is None:
            skipped.append(
                SkippedHighwayItem(
                    KREX_REST_AREA_WEATHER_DATASET_KEY,
                    unit_code,
                    "missing feature mapping",
                    raw,
                )
            )
            continue
        values.extend(_weather_values(feature_id, item, raw, collected_at=collected_at))
    return HighwayFeatureEtlResult(
        dataset_key=KREX_REST_AREA_WEATHER_DATASET_KEY,
        features=(),
        place_details=(),
        source_records=(),
        source_links=(),
        weather_values=tuple(values),
        skipped_items=tuple(skipped),
    )


def load_highway_result(session: Any, result: HighwayFeatureEtlResult) -> FeatureDbLoadResult:
    return load_feature_rows(
        session,
        feature_items=result.features,
        source_record_items=result.source_records,
        source_link_items=result.source_links,
        place_detail_items=result.place_details,
        price_point_items=result.price_points,
        price_value_items=result.price_values,
        weather_value_items=result.weather_values,
    )


def _weather_values(
    feature_id: str,
    item: Any,
    raw: Mapping[str, Any],
    *,
    collected_at: datetime | None,
) -> tuple[WeatherValue, ...]:
    observed_at = getattr(item, "observed_at", None)
    result: list[WeatherValue] = []
    for attr, metric_key, unit in (
        ("temperature", "temperature_c", "C"),
        ("humidity", "humidity_pct", "%"),
        ("wind_speed", "wind_speed_ms", "m/s"),
        ("rainfall", "rainfall_mm", "mm"),
        ("snow", "snow_cm", "cm"),
        ("weather", "weather_text", None),
    ):
        value = getattr(item, attr, None)
        if value is None:
            value = raw.get(attr)
        if value in (None, ""):
            continue
        number = _decimal_or_none(value)
        result.append(
            WeatherValue(
                feature_id=feature_id,
                provider=KREX_PROVIDER,
                weather_domain=WeatherDomain.REST_AREA_WEATHER,
                forecast_style=ForecastStyle.OBSERVED,
                metric_key=metric_key,
                observed_at=observed_at,
                source_metric_key=attr,
                value_number=number,
                value_text=None if number is not None else str(value),
                unit=unit,
                collected_at=collected_at or _now_kst(),
                payload=dict(raw),
            )
        )
    return tuple(result)


def _rest_area_source_key(item: Any, raw: Mapping[str, Any]) -> str | None:
    return _join_key(
        _text(item, raw, "service_area_code", "serviceAreaCode"),
        _text(item, raw, "service_area_code2", "serviceAreaCode2"),
        _text(item, raw, "name", "service_area_name", "restAreaNm"),
        _text(item, raw, "route_name", "routeNm"),
        _text(item, raw, "direction"),
    )


def _coordinate(item: Any, raw: Mapping[str, Any]) -> Coordinate | None:
    coordinate = getattr(item, "coordinate", None)
    if isinstance(coordinate, Coordinate):
        return coordinate
    if isinstance(coordinate, Mapping):
        return Coordinate.model_validate(coordinate)
    lat = _float_or_none(getattr(item, "lat", None) or raw.get("latitude") or raw.get("lat"))
    lon = _float_or_none(
        getattr(item, "lon", None) or raw.get("longitude") or raw.get("lon")
    )
    if lat is None or lon is None:
        return None
    if not 33.0 <= lat <= 39.5 or not 124.0 <= lon <= 132.0:
        return None
    return Coordinate(lat=lat, lon=lon)


def _address(item: Any, raw: Mapping[str, Any]) -> Address:
    address = getattr(item, "address", None)
    if isinstance(address, Address):
        return address
    if isinstance(address, Mapping):
        return Address.from_mapping(address) or Address(address=_text(item, raw, "address"))
    return Address(address=_text(item, raw, "address", "rdnmadr", "lnmadr"))


def _raw_mapping(item: Any) -> Mapping[str, Any]:
    raw = getattr(item, "raw", None)
    if isinstance(raw, Mapping):
        return raw
    if hasattr(item, "model_dump"):
        dumped = item.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    if isinstance(item, Mapping):
        return item
    return {}


def _text(item: Any, raw: Mapping[str, Any], *attrs_or_keys: str) -> str | None:
    for key in attrs_or_keys:
        value = getattr(item, key, None)
        if value in (None, ""):
            value = raw.get(key)
        if value not in (None, ""):
            text = str(value).strip()
            if text:
                return text
    return None


def _join_key(*parts: str | None) -> str | None:
    values = [part for part in parts if part]
    return "|".join(values) if values else None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except Exception:  # noqa: BLE001 - provider metrics are loose strings.
        return None


def _without_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", {}, [])}


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
