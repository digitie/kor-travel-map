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
from krtour_map.etl import page_collected_at, page_items
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import (
    ROUTE_TYPE_ACCESSIBLE_WALK,
    ROUTE_TYPE_FOREST_TRAIL,
    ROUTE_TYPE_HIKING_TRAIL,
    ROUTE_TYPE_TREKKING,
    AreaDetail,
    Coordinate,
    Feature,
    FeatureUrls,
    PlaceDetail,
    RawDataRef,
    RouteDetail,
    SourceLink,
    SourceRecord,
    WeatherValue,
)

KRFOREST_PROVIDER = "python-krforest-api"
KRFOREST_RECREATION_FOREST_DATASET_KEY = "forest_recreation_forests"
KRFOREST_ARBORETUM_DATASET_KEY = "forest_arboretums"
KRFOREST_TRAIL_DATASET_KEY = "forest_trails"
KRFOREST_MOUNTAIN_WEATHER_DATASET_KEY = "forest_mountain_weather"
KRFOREST_RECREATION_FOREST_SOURCE_TYPE = "recreation_forest"
KRFOREST_ARBORETUM_SOURCE_TYPE = "arboretum"
KRFOREST_TRAIL_SOURCE_TYPE = "forest_trail"
KRFOREST_RECREATION_FOREST_FULL_SCAN_INTERVAL_DAYS = 30
KRFOREST_TRAIL_FULL_SCAN_INTERVAL_DAYS = 90
KRFOREST_MOUNTAIN_WEATHER_INTERVAL_MINUTES = 60

FOREST_RECREATION_CATEGORY = PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY.value
FOREST_ARBORETUM_CATEGORY = PlaceCategoryCode.TOURISM_BOTANICAL_GARDEN.value
FOREST_TRAIL_CATEGORY = (
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL.value
)
FOREST_NATIONAL_PARK_CATEGORY = (
    PlaceCategoryCode.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK.value
)


@dataclass(frozen=True)
class SkippedForestItem:
    dataset_key: str
    source_entity_id: str | None
    reason: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ForestFeatureBundle:
    feature: Feature
    source_record: SourceRecord
    source_link: SourceLink
    address_match_report: AddressMatchReport
    place_detail: PlaceDetail | None = None
    area_detail: AreaDetail | None = None
    route_detail: RouteDetail | None = None


@dataclass(frozen=True)
class ForestFeatureEtlResult:
    dataset_key: str
    features: tuple[Feature, ...]
    source_records: tuple[SourceRecord, ...]
    source_links: tuple[SourceLink, ...]
    place_details: tuple[PlaceDetail, ...] = ()
    area_details: tuple[AreaDetail, ...] = ()
    route_details: tuple[RouteDetail, ...] = ()
    weather_values: tuple[WeatherValue, ...] = ()
    address_match_reports: tuple[AddressMatchReport, ...] = ()
    skipped_items: tuple[SkippedForestItem, ...] = ()
    scanned_pages: int = 0

    @property
    def item_count(self) -> int:
        return len(self.features)


@dataclass(frozen=True)
class ForestFeatureDbEtlResult:
    collection: ForestFeatureEtlResult
    load: FeatureDbLoadResult

    @property
    def item_count(self) -> int:
        return self.collection.item_count


def collect_krforest_recreation_features(
    items: Iterable[Any],
    *,
    dataset_key: str = KRFOREST_RECREATION_FOREST_DATASET_KEY,
    source_type: str = KRFOREST_RECREATION_FOREST_SOURCE_TYPE,
    category: str = FOREST_RECREATION_CATEGORY,
    place_kind: str = "recreation_forest",
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    scanned_pages: int = 0,
) -> ForestFeatureEtlResult:
    return _collect_forest_feature_bundles(
        (
            _forest_place_item_to_bundle(
                item,
                dataset_key=dataset_key,
                source_type=source_type,
                category=category,
                place_kind=place_kind,
                collected_at=collected_at,
                reverse_geocoder=reverse_geocoder,
            )
            for item in items
        ),
        dataset_key=dataset_key,
        scanned_pages=scanned_pages,
    )


def collect_krforest_spatial_features(
    items: Iterable[Any],
    *,
    dataset_key: str = KRFOREST_TRAIL_DATASET_KEY,
    source_type: str = KRFOREST_TRAIL_SOURCE_TYPE,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> ForestFeatureEtlResult:
    return _collect_forest_feature_bundles(
        (
            _forest_spatial_item_to_bundle(
                item,
                dataset_key=dataset_key,
                source_type=source_type,
                collected_at=collected_at,
                reverse_geocoder=reverse_geocoder,
            )
            for item in items
        ),
        dataset_key=dataset_key,
    )


async def async_collect_krforest_recreation_features(
    client: Any,
    *,
    page_size: int = 1000,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> ForestFeatureEtlResult:
    method = getattr(getattr(client, "travel", None), "standard_recreation_forests", None)
    iter_pages = getattr(client, "iter_pages", None)
    if not callable(method) or not callable(iter_pages):
        raise ValueError(
            "python-krforest-api client must expose travel.standard_recreation_forests"
        )
    items: list[Any] = []
    scanned_pages = 0
    async for page in iter_pages(method, num_of_rows=page_size, max_pages=max_pages):
        scanned_pages += 1
        items.extend(page_items(page))
        if collected_at is None:
            collected_at = page_collected_at(page)
    return collect_krforest_recreation_features(
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
        scanned_pages=scanned_pages,
    )


async def async_collect_krforest_arboretum_features(
    client: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> ForestFeatureEtlResult:
    method = getattr(getattr(client, "travel", None), "recreation_forest_arboretums", None)
    if not callable(method):
        raise ValueError(
            "python-krforest-api client must expose travel.recreation_forest_arboretums"
        )
    return collect_krforest_recreation_features(
        await method(),
        dataset_key=KRFOREST_ARBORETUM_DATASET_KEY,
        source_type=KRFOREST_ARBORETUM_SOURCE_TYPE,
        category=FOREST_ARBORETUM_CATEGORY,
        place_kind="arboretum",
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )


async def async_collect_krforest_trail_features(
    client: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> ForestFeatureEtlResult:
    travel = getattr(client, "travel", None)
    trail_method = getattr(travel, "forest_trail_file_features", None)
    dulle_method = getattr(travel, "dulle_trail_features", None)
    items: list[Any] = []
    if callable(trail_method):
        items.extend(await trail_method())
    if callable(dulle_method):
        items.extend(await dulle_method())
    if not items:
        raise ValueError("python-krforest-api client must expose forest trail feature methods")
    return collect_krforest_spatial_features(
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def collect_krforest_mountain_weather_values(
    items: Iterable[Any],
    *,
    feature_id_by_source_key: Mapping[str, str],
    collected_at: datetime | None = None,
) -> ForestFeatureEtlResult:
    weather_values: list[WeatherValue] = []
    skipped: list[SkippedForestItem] = []
    for item in items:
        raw = _raw_mapping(item)
        source_key = _source_key(item, raw)
        if source_key is None:
            skipped.append(
                SkippedForestItem(
                    KRFOREST_MOUNTAIN_WEATHER_DATASET_KEY,
                    None,
                    "missing key",
                    raw,
                )
            )
            continue
        feature_id = feature_id_by_source_key.get(source_key)
        if feature_id is None:
            skipped.append(
                SkippedForestItem(
                    KRFOREST_MOUNTAIN_WEATHER_DATASET_KEY,
                    source_key,
                    "missing feature mapping",
                    raw,
                )
            )
            continue
        weather_values.extend(
            _weather_values_from_raw(
                feature_id,
                raw,
                source_record_key=None,
                collected_at=collected_at,
            )
        )
    return ForestFeatureEtlResult(
        dataset_key=KRFOREST_MOUNTAIN_WEATHER_DATASET_KEY,
        features=(),
        source_records=(),
        source_links=(),
        weather_values=tuple(weather_values),
        skipped_items=tuple(skipped),
    )


def load_krforest_result(session: Any, result: ForestFeatureEtlResult) -> FeatureDbLoadResult:
    return load_feature_rows(
        session,
        feature_items=result.features,
        source_record_items=result.source_records,
        source_link_items=result.source_links,
        place_detail_items=result.place_details,
        area_detail_items=result.area_details,
        route_detail_items=result.route_details,
        weather_value_items=result.weather_values,
    )


def _collect_forest_feature_bundles(
    bundles: Iterable[ForestFeatureBundle | SkippedForestItem],
    *,
    dataset_key: str,
    scanned_pages: int = 0,
) -> ForestFeatureEtlResult:
    features: list[Feature] = []
    source_records: list[SourceRecord] = []
    source_links: list[SourceLink] = []
    place_details: list[PlaceDetail] = []
    area_details: list[AreaDetail] = []
    route_details: list[RouteDetail] = []
    reports: list[AddressMatchReport] = []
    skipped: list[SkippedForestItem] = []
    for bundle in bundles:
        if isinstance(bundle, SkippedForestItem):
            skipped.append(bundle)
            continue
        features.append(bundle.feature)
        source_records.append(bundle.source_record)
        source_links.append(bundle.source_link)
        reports.append(bundle.address_match_report)
        if bundle.place_detail is not None:
            place_details.append(bundle.place_detail)
        if bundle.area_detail is not None:
            area_details.append(bundle.area_detail)
        if bundle.route_detail is not None:
            route_details.append(bundle.route_detail)
    return ForestFeatureEtlResult(
        dataset_key=dataset_key,
        features=tuple(features),
        source_records=tuple(source_records),
        source_links=tuple(source_links),
        place_details=tuple(place_details),
        area_details=tuple(area_details),
        route_details=tuple(route_details),
        address_match_reports=tuple(reports),
        skipped_items=tuple(skipped),
        scanned_pages=scanned_pages,
    )


def _forest_place_item_to_bundle(
    item: Any,
    *,
    dataset_key: str,
    source_type: str,
    category: str,
    place_kind: str,
    collected_at: datetime | None,
    reverse_geocoder: ReverseGeocoder | None,
) -> ForestFeatureBundle | SkippedForestItem:
    raw = _raw_mapping(item)
    source_key = _source_key(item, raw)
    name = _text(item, raw, "name", "rcrfrstNm", "fcltyNm", "name_ko")
    if source_key is None:
        return SkippedForestItem(dataset_key, None, "missing forest source key", raw)
    if name is None:
        return SkippedForestItem(dataset_key, source_key, "missing forest name", raw)
    coordinate = _coordinate(item, raw)
    enrichment = enrich_address_from_coordinate(
        address=_address(item, raw),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=dataset_key,
        source_entity_id=source_key,
    )
    return _forest_bundle(
        item,
        raw,
        dataset_key=dataset_key,
        source_type=source_type,
        source_key=source_key,
        kind=FeatureKind.PLACE,
        name=name,
        category=category,
        marker_icon="park",
        marker_color="#2F855A",
        coordinate=coordinate,
        address=enrichment.address,
        report=enrichment.report,
        detail_kind=place_kind,
        collected_at=collected_at,
    )


def _forest_spatial_item_to_bundle(
    item: Any,
    *,
    dataset_key: str,
    source_type: str,
    collected_at: datetime | None,
    reverse_geocoder: ReverseGeocoder | None,
) -> ForestFeatureBundle | SkippedForestItem:
    raw = _raw_mapping(item)
    source_key = _source_key(item, raw)
    name = _text(item, raw, "name", "trail_name", "mntnNm") or _text(
        item,
        raw,
        "dataset_name",
    )
    if source_key is None:
        return SkippedForestItem(dataset_key, None, "missing forest spatial source key", raw)
    if name is None:
        return SkippedForestItem(dataset_key, source_key, "missing forest spatial name", raw)
    geometry = getattr(item, "geometry", None)
    geometry_type = (_text(item, raw, "geometry_type") or "").lower()
    kind = FeatureKind.AREA if "polygon" in geometry_type else FeatureKind.ROUTE
    category = FOREST_NATIONAL_PARK_CATEGORY if "국립공원" in name else FOREST_TRAIL_CATEGORY
    coordinate = _coordinate(item, raw)
    enrichment = enrich_address_from_coordinate(
        address=_address(item, raw),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=dataset_key,
        source_entity_id=source_key,
    )
    bundle = _forest_bundle(
        item,
        raw,
        dataset_key=dataset_key,
        source_type=source_type,
        source_key=source_key,
        kind=kind,
        name=name,
        category=category,
        marker_icon="trailhead" if kind == FeatureKind.ROUTE else "park",
        marker_color="#276749",
        coordinate=coordinate,
        address=enrichment.address,
        report=enrichment.report,
        detail_kind="forest_trail",
        collected_at=collected_at,
    )
    if isinstance(bundle, SkippedForestItem):
        return bundle
    if kind == FeatureKind.AREA:
        return ForestFeatureBundle(
            feature=bundle.feature,
            source_record=bundle.source_record,
            source_link=bundle.source_link,
            address_match_report=bundle.address_match_report,
            area_detail=AreaDetail(
                feature_id=bundle.feature.feature_id,
                area_kind="forest_area",
                boundary_source=dataset_key,
                geometry=dict(geometry) if isinstance(geometry, Mapping) else None,
                payload=bundle.feature.detail or {},
            ),
        )
    geometry_payload = dict(geometry) if isinstance(geometry, Mapping) else None
    return ForestFeatureBundle(
        feature=bundle.feature,
        source_record=bundle.source_record,
        source_link=bundle.source_link,
        address_match_report=bundle.address_match_report,
        route_detail=RouteDetail(
            feature_id=bundle.feature.feature_id,
            route_type=_forest_route_type(item, raw, name),
            geometry_source=dataset_key,
            geometry_status=(
                "provided" if geometry_payload is not None else "missing_route_geometry"
            ),
            geometry=geometry_payload,
            payload=bundle.feature.detail or {},
        ),
    )


def _forest_bundle(
    item: Any,
    raw: Mapping[str, Any],
    *,
    dataset_key: str,
    source_type: str,
    source_key: str,
    kind: FeatureKind,
    name: str,
    category: str,
    marker_icon: str,
    marker_color: str,
    coordinate: Coordinate | None,
    address: Address,
    report: AddressMatchReport,
    detail_kind: str,
    collected_at: datetime | None,
) -> ForestFeatureBundle | SkippedForestItem:
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=KRFOREST_PROVIDER,
        source_type=source_type,
        source_natural_key=source_key,
        kind=kind,
        category=category,
        legal_dong_code=address.legal_dong_code,
    )
    source_record = SourceRecord(
        provider=KRFOREST_PROVIDER,
        dataset_key=dataset_key,
        source_entity_type=source_type,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        source_version=_text(item, raw, "reference_date", "referenceDate"),
        raw_name=name,
        raw_address=address.display_address,
        raw_longitude=Decimal(str(coordinate.longitude)) if coordinate is not None else None,
        raw_latitude=Decimal(str(coordinate.latitude)) if coordinate is not None else None,
        raw_data=dict(raw),
        fetched_at=collected_at,
        imported_at=collected_at or _now_kst(),
    )
    detail = {
        "selected_source": {
            "provider": KRFOREST_PROVIDER,
            "dataset_key": dataset_key,
            "source_type": source_type,
            "source_entity_id": source_key,
        },
        "forest": _without_none(
            {
                "kind": detail_kind,
                "dataset_id": _text(item, raw, "dataset_id"),
                "dataset_name": _text(item, raw, "dataset_name"),
                "forest_type": _text(item, raw, "forest_type", "rcrfrstType"),
                "area": _text(item, raw, "area"),
                "capacity": _text(item, raw, "capacity"),
                "entrance_fee": _text(item, raw, "entrance_fee"),
                "main_facilities": _text(item, raw, "main_facilities"),
                "homepage_url": _text(item, raw, "homepage_url"),
                "phone_number": _text(item, raw, "phone_number"),
                "reference_date": _text(item, raw, "reference_date", "referenceDate"),
            }
        ),
        "raw": dict(raw),
    }
    feature = Feature(
        feature_id=feature_id,
        kind=kind,
        name=name,
        coord=coordinate,
        address=address,
        category=category,
        urls=_urls(item, raw),
        marker_icon=marker_icon,
        marker_color=marker_color,
        detail=detail,
        raw_refs=[
            RawDataRef(
                provider=KRFOREST_PROVIDER,
                dataset_key=dataset_key,
                source_entity_id=source_key,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected_at,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record.key(),
        source_role=SourceRole.PRIMARY,
        match_method="krforest_source_key",
        confidence=100,
        is_primary_source=True,
    )
    place_detail = None
    if kind == FeatureKind.PLACE:
        place_detail = PlaceDetail(
            feature_id=feature_id,
            place_kind=detail_kind,
            phones=[phone] if (phone := _text(item, raw, "phone_number", "phoneNumber")) else [],
            facility_info=detail["forest"],
            payload=detail,
        )
    return ForestFeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
        address_match_report=report,
        place_detail=place_detail,
    )


def _weather_values_from_raw(
    feature_id: str,
    raw: Mapping[str, Any],
    *,
    source_record_key: str | None,
    collected_at: datetime | None,
) -> tuple[WeatherValue, ...]:
    values: list[WeatherValue] = []
    for raw_key, metric_key, unit in (
        ("temperature", "temperature_c", "C"),
        ("tmprt", "temperature_c", "C"),
        ("humidity", "humidity_pct", "%"),
        ("hm", "humidity_pct", "%"),
        ("wind_speed", "wind_speed_ms", "m/s"),
        ("ws", "wind_speed_ms", "m/s"),
        ("rainfall", "rainfall_mm", "mm"),
        ("rn", "rainfall_mm", "mm"),
    ):
        value = raw.get(raw_key)
        number = _decimal_or_none(value)
        if number is None:
            continue
        values.append(
            WeatherValue(
                feature_id=feature_id,
                provider=KRFOREST_PROVIDER,
                weather_domain=WeatherDomain.FOREST_MOUNTAIN_WEATHER,
                forecast_style=ForecastStyle.OBSERVED,
                metric_key=metric_key,
                source_metric_key=raw_key,
                value_number=number,
                unit=unit,
                collected_at=collected_at or _now_kst(),
                source_record_key=source_record_key,
                payload=dict(raw),
            )
        )
    return tuple(values)


def _source_key(item: Any, raw: Mapping[str, Any]) -> str | None:
    return _join_key(
        _text(item, raw, "institution_id", "dataset_id", "id", "mtnCode", "mntnCd"),
        _text(item, raw, "name", "dataset_name", "rcrfrstNm", "mntnNm"),
        _text(item, raw, "reference_date", "referenceDate", "year"),
    )


def _forest_route_type(item: Any, raw: Mapping[str, Any], name: str) -> str:
    text = " ".join(
        value
        for value in (
            name,
            _text(item, raw, "dataset_name"),
            _text(item, raw, "trail_type", "route_type", "forest_type"),
        )
        if value
    )
    if "무장애" in text or "장애물없는" in text:
        return ROUTE_TYPE_ACCESSIBLE_WALK
    if "트레킹" in text or "트래킹" in text or "둘레" in text:
        return ROUTE_TYPE_TREKKING
    if "등산" in text or "산행" in text or "탐방로" in text:
        return ROUTE_TYPE_HIKING_TRAIL
    return ROUTE_TYPE_FOREST_TRAIL


def _coordinate(item: Any, raw: Mapping[str, Any]) -> Coordinate | None:
    coordinate = getattr(item, "coordinate", None)
    if isinstance(coordinate, Coordinate):
        return coordinate
    if isinstance(coordinate, Mapping):
        return Coordinate.model_validate(coordinate)
    lat = _float_or_none(getattr(item, "lat", None) or raw.get("latitude") or raw.get("lat"))
    lon = _float_or_none(
        getattr(item, "lon", None)
        or getattr(item, "lng", None)
        or raw.get("longitude")
        or raw.get("lon")
        or raw.get("lng")
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


def _urls(item: Any, raw: Mapping[str, Any]) -> FeatureUrls:
    url = _url_or_none(_text(item, raw, "homepage_url", "homepageUrl"))
    if url is None:
        return FeatureUrls()
    try:
        return FeatureUrls(homepage=url)
    except ValueError:
        return FeatureUrls()


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
    except Exception:  # noqa: BLE001 - metrics arrive as provider strings.
        return None


def _url_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return text
    if "." in text and " " not in text:
        return f"https://{text}"
    return None


def _without_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", {}, [])}


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
