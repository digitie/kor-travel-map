from __future__ import annotations

import asyncio
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from kraddr.base import Address, PlaceCategoryCode

from krtour_map.addressing import (
    AddressMatchReport,
    ReverseGeocoder,
    enrich_address_from_coordinate,
)
from krtour_map.dagster import (
    DagsterEtlExecution,
    DagsterEtlRun,
    EtlJobSpec,
    EtlRunIdentity,
    schedule_requires_any_env,
)
from krtour_map.db import FeatureDbLoadResult, load_feature_rows
from krtour_map.enums import FeatureKind, ForecastStyle, SourceRole, WeatherDomain
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import (
    Coordinate,
    EventDetail,
    Feature,
    FeatureUrls,
    PlaceDetail,
    RawDataRef,
    SourceLink,
    SourceRecord,
    WeatherValue,
)

DATAGOKR_PROVIDER = "python-datagokr-api"
DATAGOKR_DEFAULT_PAGE_SIZE = 1000
DATAGOKR_STANDARD_FULL_SCAN_INTERVAL_DAYS = 1

DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY = "datagokr_public_museum_art_galleries"
DATAGOKR_PARKING_LOT_DATASET_KEY = "datagokr_public_parking_lots"
DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY = "datagokr_public_tourist_attractions"
DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY = "datagokr_public_cultural_festivals"
DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY = "datagokr_agri_weather_stations"
DATAGOKR_KWATER_SLUICE_HOUR_DATASET_KEY = "datagokr_kwater_sluice_hourly"

DATAGOKR_AGRI_WEATHER_STATION_CATEGORY = "agri_weather_station"
DATAGOKR_KWATER_SLUICE_NORMALIZATION_VERSION = "datagokr-kwater-sluice-v1"

DATAGOKR_STANDARD_DATASET_KEYS = (
    DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
    DATAGOKR_PARKING_LOT_DATASET_KEY,
    DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY,
    DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
)

KWATER_SLUICE_METRICS: dict[str, tuple[str, str, str]] = {
    "lowlevel": ("dam_water_level", "댐수위", "EL.m"),
    "rf": ("rainfall", "강우량", "mm"),
    "inflowqy": ("inflow", "유입량", "m3/sec"),
    "totdcwtrqy": ("total_discharge", "총방류량", "m3/sec"),
    "rsvwtqy": ("reservoir_storage", "저수량", "million_m3"),
    "rsvwtrt": ("reservoir_rate", "저수율", "%"),
}


@dataclass(frozen=True)
class DataGoKrDatasetSpec:
    dataset_key: str
    standard_id: str
    endpoint: str
    client_attr: str
    source_type: str
    feature_kind: FeatureKind
    category: str
    marker_icon: str
    marker_color: str
    place_kind: str | None = None
    event_kind: str | None = None


DATAGOKR_DATASET_SPECS: dict[str, DataGoKrDatasetSpec] = {
    DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY: DataGoKrDatasetSpec(
        dataset_key=DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
        standard_id="15017323",
        endpoint="tn_pubr_public_museum_artgr_info_api",
        client_attr="museum_art",
        source_type="museum_art_gallery",
        feature_kind=FeatureKind.PLACE,
        category=PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM.value,
        marker_icon="museum",
        marker_color="#7C3AED",
        place_kind="museum_art_gallery",
    ),
    DATAGOKR_PARKING_LOT_DATASET_KEY: DataGoKrDatasetSpec(
        dataset_key=DATAGOKR_PARKING_LOT_DATASET_KEY,
        standard_id="15012896",
        endpoint="tn_pubr_prkplce_info_api",
        client_attr="parking",
        source_type="parking_lot",
        feature_kind=FeatureKind.PLACE,
        category=PlaceCategoryCode.TRANSPORT_PARKING.value,
        marker_icon="parking",
        marker_color="#2563EB",
        place_kind="parking_lot",
    ),
    DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY: DataGoKrDatasetSpec(
        dataset_key=DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY,
        standard_id="15021141",
        endpoint="tn_pubr_public_trrsrt_api",
        client_attr="tourist_attraction",
        source_type="tourist_attraction",
        feature_kind=FeatureKind.PLACE,
        category=PlaceCategoryCode.TOURISM.value,
        marker_icon="attraction",
        marker_color="#15803D",
        place_kind="tourist_attraction",
    ),
    DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY: DataGoKrDatasetSpec(
        dataset_key=DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
        standard_id="15013104",
        endpoint="tn_pubr_public_cltur_fstvl_api",
        client_attr="festival",
        source_type="cultural_festival",
        feature_kind=FeatureKind.EVENT,
        category=PlaceCategoryCode.TOURISM.value,
        marker_icon="theatre",
        marker_color="#E85D04",
        event_kind="standard_cultural_festival",
    ),
}

DATAGOKR_DATASET_ALIASES = {
    "museum_art": DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
    "museum_art_gallery": DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
    "museums": DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
    "parking": DATAGOKR_PARKING_LOT_DATASET_KEY,
    "parking_lot": DATAGOKR_PARKING_LOT_DATASET_KEY,
    "parking_lots": DATAGOKR_PARKING_LOT_DATASET_KEY,
    "tourist_attraction": DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY,
    "tourist_attractions": DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY,
    "tourist_site": DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY,
    "festival": DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
    "festivals": DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
    "cultural_festival": DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
}


@dataclass(frozen=True)
class SkippedDataGoKrItem:
    dataset_key: str
    source_entity_id: str | None
    reason: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class DataGoKrFeatureBundle:
    feature: Feature
    source_record: SourceRecord
    source_link: SourceLink
    address_match_report: AddressMatchReport
    place_detail: PlaceDetail | None = None
    event_detail: EventDetail | None = None


@dataclass(frozen=True)
class DataGoKrStandardEtlResult:
    dataset_key: str
    scanned_pages: int
    features: tuple[Feature, ...]
    source_records: tuple[SourceRecord, ...]
    source_links: tuple[SourceLink, ...]
    place_details: tuple[PlaceDetail, ...] = ()
    event_details: tuple[EventDetail, ...] = ()
    address_match_reports: tuple[AddressMatchReport, ...] = ()
    skipped_items: tuple[SkippedDataGoKrItem, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.features)


@dataclass(frozen=True)
class DataGoKrStandardDbEtlResult:
    collection: DataGoKrStandardEtlResult
    load: FeatureDbLoadResult

    @property
    def item_count(self) -> int:
        return self.collection.item_count


@dataclass(frozen=True)
class DataGoKrStandardLoadResources:
    client: Any
    session: Any | None = None
    reverse_geocoder: ReverseGeocoder | None = None


def collect_datagokr_standard_features(
    client: Any,
    dataset_key: str,
    *,
    page_size: int = DATAGOKR_DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    filters: Mapping[str, Any] | None = None,
) -> DataGoKrStandardEtlResult:
    """Collect one data.go.kr standard dataset and convert rows into TripMate features."""

    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")
    spec = datagokr_dataset_spec(dataset_key)
    service = getattr(client, spec.client_attr, None)
    if service is None:
        raise ValueError(f"DataGoKr client must provide {spec.client_attr!r} service")
    iter_pages = getattr(service, "iter_pages", None)
    if not callable(iter_pages):
        raise ValueError(f"DataGoKr {spec.client_attr!r} service must provide iter_pages")

    features_result: list[Feature] = []
    source_records_result: list[SourceRecord] = []
    source_links_result: list[SourceLink] = []
    place_details: list[PlaceDetail] = []
    event_details: list[EventDetail] = []
    address_match_reports: list[AddressMatchReport] = []
    skipped_items: list[SkippedDataGoKrItem] = []
    scanned_pages = 0

    page_kwargs: dict[str, Any] = {
        "num_of_rows": page_size,
        "max_pages": max_pages,
    }
    if filters:
        page_kwargs.update(filters)

    for page in _collect_provider_pages(iter_pages(**page_kwargs)):
        scanned_pages += 1
        page_collected_at = collected_at or _page_collected_at(page)
        for item in getattr(page, "items", ()):
            bundle = datagokr_item_to_feature_bundle(
                item,
                dataset_key=spec.dataset_key,
                collected_at=page_collected_at,
                reverse_geocoder=reverse_geocoder,
            )
            if isinstance(bundle, SkippedDataGoKrItem):
                skipped_items.append(bundle)
                continue
            features_result.append(bundle.feature)
            source_records_result.append(bundle.source_record)
            source_links_result.append(bundle.source_link)
            address_match_reports.append(bundle.address_match_report)
            if bundle.place_detail is not None:
                place_details.append(bundle.place_detail)
            if bundle.event_detail is not None:
                event_details.append(bundle.event_detail)

    return DataGoKrStandardEtlResult(
        dataset_key=spec.dataset_key,
        scanned_pages=scanned_pages,
        features=tuple(features_result),
        source_records=tuple(source_records_result),
        source_links=tuple(source_links_result),
        place_details=tuple(place_details),
        event_details=tuple(event_details),
        address_match_reports=tuple(address_match_reports),
        skipped_items=tuple(skipped_items),
    )


def collect_datagokr_public_museum_art_galleries(
    client: Any,
    **kwargs: Any,
) -> DataGoKrStandardEtlResult:
    return collect_datagokr_standard_features(
        client,
        DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
        **kwargs,
    )


def collect_datagokr_public_parking_lots(client: Any, **kwargs: Any) -> DataGoKrStandardEtlResult:
    return collect_datagokr_standard_features(client, DATAGOKR_PARKING_LOT_DATASET_KEY, **kwargs)


def collect_datagokr_public_tourist_attractions(
    client: Any,
    **kwargs: Any,
) -> DataGoKrStandardEtlResult:
    return collect_datagokr_standard_features(
        client,
        DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY,
        **kwargs,
    )


def collect_datagokr_public_cultural_festivals(
    client: Any,
    **kwargs: Any,
) -> DataGoKrStandardEtlResult:
    return collect_datagokr_standard_features(
        client,
        DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
        **kwargs,
    )


def datagokr_item_to_feature_bundle(
    item: Any,
    *,
    dataset_key: str,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> DataGoKrFeatureBundle | SkippedDataGoKrItem:
    spec = datagokr_dataset_spec(dataset_key)
    raw = _raw_mapping(item)
    source_key = _source_key(spec, item, raw)
    if source_key is None:
        return SkippedDataGoKrItem(spec.dataset_key, None, "missing source key", raw)
    name = _name(spec, item, raw)
    if name is None:
        return SkippedDataGoKrItem(spec.dataset_key, source_key, "missing name", raw)

    coordinate = _coordinate_from_item(item, raw)
    address_enrichment = enrich_address_from_coordinate(
        address=_address_from_item(spec, item, raw),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=spec.dataset_key,
        source_entity_id=source_key,
    )
    address = address_enrichment.address
    category = _category(spec, item, raw)
    collected = collected_at or _now_kst()
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=DATAGOKR_PROVIDER,
        source_type=spec.source_type,
        source_natural_key=source_key,
        kind=spec.feature_kind,
        category=category,
        legal_dong_code=address.legal_dong_code,
    )
    source_record = SourceRecord(
        provider=DATAGOKR_PROVIDER,
        dataset_key=spec.dataset_key,
        source_entity_type=spec.source_type,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        raw_name=name,
        raw_address=address.display_address,
        raw_longitude=Decimal(str(coordinate.longitude)) if coordinate is not None else None,
        raw_latitude=Decimal(str(coordinate.latitude)) if coordinate is not None else None,
        raw_data=dict(raw),
        fetched_at=collected,
        imported_at=collected,
    )
    source_record_key = source_record.key()
    detail_payload = _detail_payload(spec, item, raw, source_key=source_key)
    feature = Feature(
        feature_id=feature_id,
        kind=spec.feature_kind,
        name=name,
        coord=coordinate,
        address=address,
        category=category,
        urls=_feature_urls(spec, item, raw),
        marker_icon=spec.marker_icon,
        marker_color=spec.marker_color,
        detail=detail_payload,
        raw_refs=[
            RawDataRef(
                provider=DATAGOKR_PROVIDER,
                dataset_key=spec.dataset_key,
                source_entity_id=source_key,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method=f"{spec.source_type}_source_key",
        confidence=100,
        is_primary_source=True,
    )
    if spec.feature_kind == FeatureKind.EVENT:
        return DataGoKrFeatureBundle(
            feature=feature,
            event_detail=EventDetail(
                feature_id=feature_id,
                event_kind=spec.event_kind or spec.source_type,
                starts_on=_festival_start_date(item, raw),
                ends_on=_festival_end_date(item, raw),
                venue_name=_text(item, "opar", raw_keys=("opar",)) or address.display_address,
                tel=_text(item, "phone_number", raw_keys=("phoneNumber", "phone_number")),
                content_id=source_key,
                payload=detail_payload,
            ),
            source_record=source_record,
            source_link=source_link,
            address_match_report=address_enrichment.report,
        )
    return DataGoKrFeatureBundle(
        feature=feature,
        place_detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=spec.place_kind or spec.source_type,
            phones=_phones(spec, item, raw),
            facility_info=_facility_info(spec, item, raw),
            license_date=_license_date(spec, item, raw),
            payload=detail_payload,
        ),
        source_record=source_record,
        source_link=source_link,
        address_match_report=address_enrichment.report,
    )


def load_datagokr_standard_result(
    session: Any,
    result: DataGoKrStandardEtlResult,
) -> FeatureDbLoadResult:
    """Load a collected data.go.kr standard result into the feature DB session."""

    return load_feature_rows(
        session,
        feature_items=result.features,
        source_record_items=result.source_records,
        source_link_items=result.source_links,
        place_detail_items=result.place_details,
        event_detail_items=result.event_details,
    )


def collect_and_load_datagokr_standard_features(
    session: Any,
    client: Any,
    dataset_key: str,
    *,
    page_size: int = DATAGOKR_DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    filters: Mapping[str, Any] | None = None,
) -> DataGoKrStandardDbEtlResult:
    collection = collect_datagokr_standard_features(
        client,
        dataset_key,
        page_size=page_size,
        max_pages=max_pages,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
        filters=filters,
    )
    return DataGoKrStandardDbEtlResult(
        collection=collection,
        load=load_datagokr_standard_result(session, collection),
    )


def load_datagokr_standard_features(
    resource: Any,
    run: DagsterEtlRun,
) -> DataGoKrStandardEtlResult | DataGoKrStandardDbEtlResult:
    client, session, reverse_geocoder = _resolve_datagokr_resources(resource)
    dataset_key = datagokr_dataset_key(run.op_config.get("dataset_key") or run.dataset_key)
    page_size = _optional_int(run.op_config.get("page_size")) or DATAGOKR_DEFAULT_PAGE_SIZE
    max_pages = _optional_int(run.op_config.get("max_pages"))
    filters = _filters_config(run.op_config.get("filters"))
    if session is None:
        return collect_datagokr_standard_features(
            client,
            dataset_key,
            page_size=page_size,
            max_pages=max_pages,
            collected_at=run.collected_at,
            reverse_geocoder=reverse_geocoder,
            filters=filters,
        )
    return collect_and_load_datagokr_standard_features(
        session,
        client,
        dataset_key,
        page_size=page_size,
        max_pages=max_pages,
        collected_at=run.collected_at,
        reverse_geocoder=reverse_geocoder,
        filters=filters,
    )


def collect_datagokr_agri_weather_stations(
    client: Any,
    *,
    page_size: int = 100,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    filters: Mapping[str, Any] | None = None,
) -> DataGoKrStandardEtlResult:
    """Collect agricultural weather stations and convert them into weather features."""

    service = getattr(getattr(client, "agri_weather", None), "observation_stations", None)
    if service is None:
        raise ValueError("DataGoKr client must provide agri_weather.observation_stations")
    iter_pages = getattr(service, "iter_pages", None)
    if not callable(iter_pages):
        raise ValueError("DataGoKr agri_weather.observation_stations must provide iter_pages")

    page_kwargs: dict[str, Any] = {"num_of_rows": page_size, "max_pages": max_pages}
    if filters:
        page_kwargs.update(filters)

    features_result: list[Feature] = []
    source_records_result: list[SourceRecord] = []
    source_links_result: list[SourceLink] = []
    address_match_reports: list[AddressMatchReport] = []
    skipped_items: list[SkippedDataGoKrItem] = []
    scanned_pages = 0
    for page in _collect_provider_pages(iter_pages(**page_kwargs)):
        scanned_pages += 1
        page_collected_at = collected_at or _page_collected_at(page)
        for item in getattr(page, "items", ()):
            bundle = datagokr_agri_weather_station_to_feature_bundle(
                item,
                collected_at=page_collected_at,
                reverse_geocoder=reverse_geocoder,
            )
            if isinstance(bundle, SkippedDataGoKrItem):
                skipped_items.append(bundle)
                continue
            features_result.append(bundle.feature)
            source_records_result.append(bundle.source_record)
            source_links_result.append(bundle.source_link)
            address_match_reports.append(bundle.address_match_report)

    return DataGoKrStandardEtlResult(
        dataset_key=DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY,
        scanned_pages=scanned_pages,
        features=tuple(features_result),
        source_records=tuple(source_records_result),
        source_links=tuple(source_links_result),
        address_match_reports=tuple(address_match_reports),
        skipped_items=tuple(skipped_items),
    )


def datagokr_agri_weather_station_to_feature_bundle(
    item: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> DataGoKrFeatureBundle | SkippedDataGoKrItem:
    raw = _raw_mapping(item)
    source_key = _text(item, "obsr_spot_code", raw_keys=("Obsr_Spot_Code",))
    if source_key is None:
        return SkippedDataGoKrItem(
            DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY,
            None,
            "missing observation station code",
            raw,
        )
    name = _text(item, "obsr_spot_nm", raw_keys=("Obsr_Spot_Nm",))
    if name is None:
        return SkippedDataGoKrItem(
            DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY,
            source_key,
            "missing observation station name",
            raw,
        )

    coordinate = _coordinate_from_agri_station(item, raw)
    address_enrichment = enrich_address_from_coordinate(
        address=Address.from_text(
            _text(item, "instl_adres", raw_keys=("Instl_Adres",))
        )
        or Address(),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY,
        source_entity_id=source_key,
    )
    address = address_enrichment.address
    collected = collected_at or _now_kst()
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=DATAGOKR_PROVIDER,
        source_type="agri_weather_station",
        source_natural_key=source_key,
        kind=FeatureKind.WEATHER,
        category=DATAGOKR_AGRI_WEATHER_STATION_CATEGORY,
        legal_dong_code=address.legal_dong_code,
    )
    source_record = SourceRecord(
        provider=DATAGOKR_PROVIDER,
        dataset_key=DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY,
        source_entity_type="agri_weather_station",
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        raw_name=name,
        raw_address=address.display_address,
        raw_longitude=Decimal(str(coordinate.longitude)) if coordinate is not None else None,
        raw_latitude=Decimal(str(coordinate.latitude)) if coordinate is not None else None,
        raw_data=dict(raw),
        fetched_at=collected,
        imported_at=collected,
    )
    detail_payload = {
        "provider": DATAGOKR_PROVIDER,
        "dataset_key": DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY,
        "standard_id": "15073274",
        "endpoint": "1390802/AgriWeather/getObsrSpotList",
        "observation_station_code": source_key,
        "do_se_code": _text(item, "do_se_code", raw_keys=("Do_Se_Code",)),
        "mgc_code": _text(item, "mgc_code", raw_keys=("Mgc_Code",)),
        "climate_zone_code": _text(item, "clmt_zone_code", raw_keys=("Clmt_Zone_Code",)),
        "communication_method_code": _text(
            item,
            "comm_mthd_code",
            raw_keys=("Comm_Mthd_Code",),
        ),
        "altitude_m": _optional_float(getattr(item, "instl_al", None) or _first(raw, "Instl_Al")),
        "observation_begin_date": _text(
            item,
            "obsr_begin_datetm",
            raw_keys=("Obsr_Begin_Datetm",),
        ),
    }
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.WEATHER,
        name=name,
        coord=coordinate,
        address=address,
        category=DATAGOKR_AGRI_WEATHER_STATION_CATEGORY,
        marker_icon="weather",
        marker_color="#0E7490",
        detail={key: value for key, value in detail_payload.items() if value not in (None, "")},
        raw_refs=[
            RawDataRef(
                provider=DATAGOKR_PROVIDER,
                dataset_key=DATAGOKR_AGRI_WEATHER_STATION_DATASET_KEY,
                source_entity_id=source_key,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record.key(),
        source_role=SourceRole.PRIMARY,
        match_method="agri_weather_station_code",
        confidence=100,
        is_primary_source=True,
    )
    return DataGoKrFeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
        address_match_report=address_enrichment.report,
    )


def kwater_sluice_record_to_weather_values(
    feature_id: str,
    item: Any,
    *,
    observed_year: int,
    collected_at: datetime | None = None,
    source_record_key: str | None = None,
) -> tuple[WeatherValue, ...]:
    """Normalize one K-water sluice operation row into WeatherValue metrics."""

    raw = _raw_mapping(item)
    observed_at = _kwater_observed_at(
        _text(item, "obsrdt", raw_keys=("obsrdt",)),
        observed_year=observed_year,
    )
    values: list[WeatherValue] = []
    for source_key, (metric_key, metric_name, unit) in KWATER_SLUICE_METRICS.items():
        value = getattr(item, source_key, None)
        if value in (None, ""):
            value = _first(raw, source_key)
        value_number = _decimal_or_none(value)
        if value_number is None:
            continue
        values.append(
            WeatherValue(
                feature_id=feature_id,
                provider=DATAGOKR_PROVIDER,
                weather_domain=WeatherDomain.HYDRO_WEATHER,
                forecast_style=ForecastStyle.OBSERVED,
                metric_key=metric_key,
                observed_at=observed_at,
                source_metric_key=source_key,
                source_metric_name=metric_name,
                metric_name=metric_name,
                value_number=value_number,
                unit=unit,
                normalization_version=DATAGOKR_KWATER_SLUICE_NORMALIZATION_VERSION,
                payload={
                    "dataset_key": DATAGOKR_KWATER_SLUICE_HOUR_DATASET_KEY,
                    "damcode": _text(item, "damcode", raw_keys=("damcode",)),
                    "obsrdt": _text(item, "obsrdt", raw_keys=("obsrdt",)),
                    "raw": dict(raw),
                },
                collected_at=collected_at or _now_kst(),
                source_record_key=source_record_key,
            )
        )
    return tuple(values)


def datagokr_standard_full_scan_identity(
    _session: Any,
    _dataset_key: str,
    execution: DagsterEtlExecution,
) -> EtlRunIdentity:
    logical_date = execution.logical_datetime_kst.date()
    return EtlRunIdentity(
        run_key=f"{logical_date:%Y%m%d}-full-scan",
        run_type=execution.run_type,
        trigger_date=logical_date,
    )


def datagokr_dataset_key(value: object) -> str:
    text = _optional_str(value)
    if text is None:
        raise ValueError("dataset_key is required")
    normalized = text.strip().lower()
    return DATAGOKR_DATASET_ALIASES.get(normalized, normalized)


def datagokr_dataset_spec(value: object) -> DataGoKrDatasetSpec:
    dataset_key = datagokr_dataset_key(value)
    try:
        return DATAGOKR_DATASET_SPECS[dataset_key]
    except KeyError as exc:
        raise ValueError(f"Unsupported data.go.kr standard dataset: {value}") from exc


def _job_spec(spec: DataGoKrDatasetSpec) -> EtlJobSpec:
    return EtlJobSpec(
        job_name=f"{spec.dataset_key}_full_scan",
        op_name="collect_datagokr_standard_features",
        dataset_key=spec.dataset_key,
        description=(
            f"Collect data.go.kr standard dataset {spec.standard_id} through "
            "python-datagokr-api and normalize rows into TripMate features."
        ),
        tags=(
            f"provider:{DATAGOKR_PROVIDER}",
            f"data_go_kr:{spec.standard_id}",
            f"source:{spec.source_type}",
            f"feature:{spec.feature_kind.value}",
            "full_scan",
            "schedule:daily",
            "pagination:all-pages",
        ),
        loader=load_datagokr_standard_features,
        success_message=f"{spec.dataset_key} full scan completed.",
        failure_message=f"{spec.dataset_key} full scan failed.",
        identity_resolver=datagokr_standard_full_scan_identity,
        schedule_enabled=schedule_requires_any_env("DATA_GO_KR_SERVICE_KEY"),
    )


datagokr_museum_art_gallery_full_scan_job_spec = _job_spec(
    DATAGOKR_DATASET_SPECS[DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY]
)
datagokr_parking_lot_full_scan_job_spec = _job_spec(
    DATAGOKR_DATASET_SPECS[DATAGOKR_PARKING_LOT_DATASET_KEY]
)
datagokr_tourist_attraction_full_scan_job_spec = _job_spec(
    DATAGOKR_DATASET_SPECS[DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY]
)
datagokr_cultural_festival_full_scan_job_spec = _job_spec(
    DATAGOKR_DATASET_SPECS[DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY]
)
datagokr_standard_full_scan_job_specs = (
    datagokr_museum_art_gallery_full_scan_job_spec,
    datagokr_parking_lot_full_scan_job_spec,
    datagokr_tourist_attraction_full_scan_job_spec,
    datagokr_cultural_festival_full_scan_job_spec,
)


def _name(spec: DataGoKrDatasetSpec, item: Any, raw: Mapping[str, Any]) -> str | None:
    if spec.dataset_key == DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY:
        return _text(item, "fclty_nm", raw_keys=("fcltyNm", "fclty_nm"))
    if spec.dataset_key == DATAGOKR_PARKING_LOT_DATASET_KEY:
        return _text(item, "prkplce_nm", raw_keys=("prkplceNm", "prkplce_nm"))
    if spec.dataset_key == DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY:
        return _text(item, "trrsrt_nm", raw_keys=("trrsrtNm", "trrsrt_nm"))
    return _text(item, "fstvl_nm", raw_keys=("fstvlNm", "fstvl_nm"))


def _source_key(spec: DataGoKrDatasetSpec, item: Any, raw: Mapping[str, Any]) -> str | None:
    if spec.dataset_key == DATAGOKR_PARKING_LOT_DATASET_KEY:
        parking_no = _text(item, "prkplce_no", raw_keys=("prkplceNo", "prkplce_no"))
        if parking_no is not None:
            return parking_no
    if spec.dataset_key == DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY:
        return _natural_key(
            _name(spec, item, raw),
            _text(item, "fstvl_start_date", raw_keys=("fstvlStartDate", "fstvl_start_date")),
            _text(item, "fstvl_end_date", raw_keys=("fstvlEndDate", "fstvl_end_date")),
            _text(item, "opar", raw_keys=("opar",)),
            _address_text(item, raw),
            _text(item, "instt_code", raw_keys=("instt_code",)),
        )
    return _natural_key(
        _name(spec, item, raw),
        _address_text(item, raw),
        _text(item, "instt_code", raw_keys=("instt_code",)),
        _text(item, "instt_nm", raw_keys=("instt_nm",)),
    )


def _natural_key(*parts: Any) -> str | None:
    values = [_optional_str(part) for part in parts]
    compact = [" ".join(value.split()) for value in values if value]
    return "|".join(compact) if compact else None


def _category(spec: DataGoKrDatasetSpec, item: Any, raw: Mapping[str, Any]) -> str:
    if spec.dataset_key != DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY:
        return spec.category
    type_name = _text(item, "fclty_type", raw_keys=("fcltyType", "fclty_type")) or ""
    name = _name(spec, item, raw) or ""
    haystack = f"{type_name} {name}"
    if "미술" in haystack:
        return PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART_MUSEUM.value
    return spec.category


def _address_from_item(spec: DataGoKrDatasetSpec, item: Any, raw: Mapping[str, Any]) -> Address:
    if spec.dataset_key == DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY:
        address = _address_text(item, raw) or _text(item, "opar", raw_keys=("opar",))
        return Address.from_text(address) or Address()
    return Address.from_text(_address_text(item, raw)) or Address()


def _address_text(item: Any, raw: Mapping[str, Any]) -> str | None:
    return (
        _text(item, "rdnmadr", raw_keys=("rdnmadr",))
        or _text(item, "lnmadr", raw_keys=("lnmadr",))
    )


def _coordinate_from_item(item: Any, raw: Mapping[str, Any]) -> Coordinate | None:
    lat = _optional_float(getattr(item, "latitude", None) or _first(raw, "latitude"))
    lon = _optional_float(getattr(item, "longitude", None) or _first(raw, "longitude"))
    if lat is None or lon is None:
        return None
    return Coordinate(lat=lat, lon=lon)


def _coordinate_from_agri_station(item: Any, raw: Mapping[str, Any]) -> Coordinate | None:
    lat = _optional_float(getattr(item, "instl_la", None) or _first(raw, "Instl_La"))
    lon = _optional_float(getattr(item, "instl_lo", None) or _first(raw, "Instl_Lo"))
    if lat is None or lon is None:
        return None
    return Coordinate(lat=lat, lon=lon)


def _feature_urls(spec: DataGoKrDatasetSpec, item: Any, raw: Mapping[str, Any]) -> FeatureUrls:
    if spec.dataset_key not in (
        DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY,
        DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY,
    ):
        return FeatureUrls()
    homepage_url = _url_or_none(_text(item, "homepage_url", raw_keys=("homepageUrl",)))
    if homepage_url is None:
        return FeatureUrls()
    try:
        return FeatureUrls.model_validate({"homepage": homepage_url})
    except ValueError:
        return FeatureUrls()


def _phones(spec: DataGoKrDatasetSpec, item: Any, raw: Mapping[str, Any]) -> list[str]:
    fields = (
        ("oper_phone_number", ("operPhoneNumber",)),
        ("phone_number", ("phoneNumber",)),
    )
    values: list[str] = []
    for attr, raw_keys in fields:
        text = _text(item, attr, raw_keys=raw_keys)
        if text and text not in values:
            values.append(text)
    if spec.dataset_key == DATAGOKR_PARKING_LOT_DATASET_KEY:
        phone = _text(item, "phone_number", raw_keys=("phoneNumber",))
        return [phone] if phone else []
    return values[:3]


def _license_date(spec: DataGoKrDatasetSpec, item: Any, raw: Mapping[str, Any]) -> date | None:
    if spec.dataset_key == DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY:
        return _date_or_none(getattr(item, "appn_date", None) or _first(raw, "appnDate"))
    return None


def _facility_info(spec: DataGoKrDatasetSpec, item: Any, raw: Mapping[str, Any]) -> dict[str, Any]:
    if spec.dataset_key == DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY:
        keys = (
            ("facility_type", "fclty_type", ("fcltyType",)),
            ("facility_info", "fclty_info", ("fcltyInfo",)),
            ("weekday_open", "weekday_oper_open_hhmm", ("weekdayOperOpenHhmm",)),
            ("weekday_close", "weekday_oper_colse_hhmm", ("weekdayOperColseHhmm",)),
            ("holiday_open", "holiday_oper_open_hhmm", ("holidayOperOpenHhmm",)),
            ("holiday_close", "holiday_close_open_hhmm", ("holidayCloseOpenHhmm",)),
            ("closed_info", "rstde_info", ("rstdeInfo",)),
            ("adult_charge", "adult_chrge", ("adultChrge",)),
            ("youth_charge", "yngbgs_chrge", ("yngbgsChrge",)),
            ("child_charge", "child_chrge", ("childChrge",)),
        )
    elif spec.dataset_key == DATAGOKR_PARKING_LOT_DATASET_KEY:
        keys = (
            ("parking_type", "prkplce_type", ("prkplceType",)),
            ("parking_section", "prkplce_se", ("prkplceSe",)),
            ("capacity", "prkcmprt", ("prkcmprt",)),
            ("oper_day", "oper_day", ("operDay",)),
            ("charge_info", "parkingchrge_info", ("parkingchrgeInfo",)),
            ("basic_time", "basic_time", ("basicTime",)),
            ("basic_charge", "basic_charge", ("basicCharge",)),
            ("payment_method", "metpay", ("metpay",)),
            ("disabled_zone_yn", "pwdbs_ppk_zone_yn", ("pwdbsPpkZoneYn",)),
        )
    else:
        keys = (
            ("tourist_type", "trrsrt_se", ("trrsrtSe",)),
            ("area_square_meters", "ar", ("ar",)),
            ("convenience_facility", "cnvnnc_fclty", ("cnvnncFclty",)),
            ("lodging_info", "stayng_info", ("stayngInfo",)),
            ("amusement_facility", "mvm_amsmt_fclty", ("mvmAmsmtFclty",)),
            ("culture_facility", "recrt_cltur_fclty", ("recrtClturFclty",)),
            ("hospitality_facility", "hospitality_fclty", ("hospitalityFclty",)),
            ("support_facility", "sport_fclty", ("sportFclty",)),
            ("capacity", "aceptnc_co", ("aceptncCo",)),
            ("parking_count", "prkplce_co", ("prkplceCo",)),
        )
    result: dict[str, Any] = {}
    for key, attr, raw_keys in keys:
        value = getattr(item, attr, None)
        if value in (None, ""):
            value = _first(raw, *raw_keys)
        if value not in (None, ""):
            result[key] = value
    return result


def _detail_payload(
    spec: DataGoKrDatasetSpec,
    item: Any,
    raw: Mapping[str, Any],
    *,
    source_key: str,
) -> dict[str, Any]:
    payload = {
        "provider": DATAGOKR_PROVIDER,
        "dataset_key": spec.dataset_key,
        "standard_id": spec.standard_id,
        "endpoint": spec.endpoint,
        "source_type": spec.source_type,
        "source_key": source_key,
        "reference_date": _text(item, "reference_date", raw_keys=("referenceDate",)),
        "institution_name": _text(
            item,
            "institution_nm",
            raw_keys=("institutionNm", "institution_nm", "instt_nm"),
        ),
        "provider_institution_name": _text(item, "instt_nm", raw_keys=("instt_nm",)),
    }
    if spec.dataset_key == DATAGOKR_MUSEUM_ART_GALLERY_DATASET_KEY:
        payload.update(
            {
                "introduction": _text(item, "fclty_intrcn", raw_keys=("fcltyIntrcn",)),
                "transport_info": _text(item, "trnsport_info", raw_keys=("trnsportInfo",)),
                "extra_charge_info": _text(item, "etc_chrge_info", raw_keys=("etcChrgeInfo",)),
            }
        )
    elif spec.dataset_key == DATAGOKR_TOURIST_ATTRACTION_DATASET_KEY:
        payload.update(
            {
                "introduction": _text(item, "trrsrt_intrcn", raw_keys=("trrsrtIntrcn",)),
                "appointed_date": _text(item, "appn_date", raw_keys=("appnDate",)),
            }
        )
    elif spec.dataset_key == DATAGOKR_CULTURAL_FESTIVAL_DATASET_KEY:
        payload.update(
            {
                "venue": _text(item, "opar", raw_keys=("opar",)),
                "festival_content": _text(item, "fstvl_co", raw_keys=("fstvlCo",)),
                "organizer": _text(item, "mnnst_nm", raw_keys=("mnnstNm",)),
                "host": _text(item, "auspc_instt_nm", raw_keys=("auspcInsttNm",)),
                "supporter": _text(item, "suprt_instt_nm", raw_keys=("suprtInsttNm",)),
                "related_info": _text(item, "relate_info", raw_keys=("relateInfo",)),
            }
        )
    return {key: value for key, value in payload.items() if value not in (None, "")}


def _festival_start_date(item: Any, raw: Mapping[str, Any]) -> date | None:
    return _date_or_none(
        getattr(item, "fstvl_start_date", None) or _first(raw, "fstvlStartDate")
    )


def _festival_end_date(item: Any, raw: Mapping[str, Any]) -> date | None:
    return _date_or_none(getattr(item, "fstvl_end_date", None) or _first(raw, "fstvlEndDate"))


def _raw_mapping(item: Any) -> Mapping[str, Any]:
    raw = getattr(item, "raw", None)
    if isinstance(raw, Mapping):
        return raw
    if hasattr(item, "model_dump"):
        dumped = item.model_dump(mode="json", by_alias=True)
        if isinstance(dumped, Mapping):
            return dumped
    if isinstance(item, Mapping):
        return item
    return {}


def _page_collected_at(page: Any) -> datetime | None:
    collected_at = getattr(page, "collected_at", None)
    if isinstance(collected_at, datetime):
        return collected_at
    context = getattr(page, "context", None)
    context_collected_at = getattr(context, "collected_at", None)
    return context_collected_at if isinstance(context_collected_at, datetime) else None


def _resolve_datagokr_resources(
    resource: Any,
) -> tuple[Any, Any | None, ReverseGeocoder | None]:
    if isinstance(resource, Mapping):
        client = resource.get("client") or resource.get("datagokr_client")
        session = resource.get("session") or resource.get("feature_session")
        reverse_geocoder = resource.get("reverse_geocoder")
    else:
        client = getattr(resource, "client", None) or getattr(resource, "datagokr_client", None)
        session = getattr(resource, "session", None) or getattr(resource, "feature_session", None)
        reverse_geocoder = getattr(resource, "reverse_geocoder", None)
        if client is None:
            client = resource
    if client is None:
        raise ValueError("DataGoKr standard ETL resource must provide a public provider client")
    return client, session, reverse_geocoder


def _filters_config(value: object) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    raise TypeError("filters config must be a mapping")


def _collect_provider_pages(pages: Any) -> tuple[Any, ...] | Any:
    if hasattr(pages, "__aiter__"):
        return _run_async(lambda: _collect_async_pages(pages))
    return pages


async def _collect_async_pages(pages: Any) -> tuple[Any, ...]:
    collected: list[Any] = []
    async for page in pages:
        collected.append(page)
    return tuple(collected)


def _run_async(awaitable_factory: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable_factory())
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(awaitable_factory())).result()


def _first(raw: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(item: Any, *attrs: str, raw_keys: tuple[str, ...]) -> str | None:
    for attr in attrs:
        value = getattr(item, attr, None)
        if value not in (None, ""):
            return _optional_str(value)
    return _optional_str(_first(_raw_mapping(item), *raw_keys))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date | datetime):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _url_or_none(value: Any) -> str | None:
    text = _optional_str(value)
    if text is None:
        return None
    if text.startswith(("http://", "https://")):
        return text
    return None


def _date_or_none(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text)


def _kwater_observed_at(value: str | None, *, observed_year: int) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("시", "").strip()
    try:
        month_day, hour_text = normalized.split()
        month_text, day_text = month_day.split("-")
        return datetime.combine(
            date(observed_year, int(month_text), int(day_text)),
            time(hour=int(hour_text)),
        )
    except (TypeError, ValueError):
        return None


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
