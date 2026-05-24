from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from kraddr.base import Address, PlaceCategoryCode

from krtour_map.addressing import (
    AddressMatchReport,
    ReverseGeocoder,
    enrich_address_from_coordinate,
    resolve_reverse_geocoder,
)
from krtour_map.dagster import (
    DagsterEtlExecution,
    DagsterEtlRun,
    EtlJobSpec,
    EtlRunIdentity,
    schedule_requires_any_env,
)
from krtour_map.db import FeatureDbLoadResult, load_feature_rows
from krtour_map.enums import FeatureKind, SourceRole
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import (
    ROUTE_TYPE_ACCESSIBLE_WALK,
    ROUTE_TYPE_CYCLING,
    ROUTE_TYPE_DRIVE_COURSE,
    ROUTE_TYPE_HIKING_TRAIL,
    ROUTE_TYPE_TOURISM_ROAD,
    ROUTE_TYPE_TREKKING,
    ROUTE_TYPE_WALKING_COURSE,
    Coordinate,
    EventDetail,
    Feature,
    FeatureOpeningHours,
    FeatureUrls,
    OpeningPeriod,
    OpeningTime,
    PlaceDetail,
    RawDataRef,
    RouteDetail,
    SourceLink,
    SourceRecord,
)
from krtour_map.standard_data.catalog import (
    DATA_GO_KR_STANDARD_PROVIDER,
    STANDARD_CULTURAL_FESTIVALS,
    STANDARD_MUSEUMS,
    STANDARD_PARKING_LOTS,
    STANDARD_TOURISM_ROADS,
    STANDARD_TOURIST_SITES,
    StandardDatasetSpec,
    standard_dataset_spec,
    standard_dataset_specs,
)
from krtour_map.standard_data.client import StandardDataClient

STANDARD_ROUTE_CATEGORY = PlaceCategoryCode.TOURISM_ACTIVITY_TREKKING.value
STANDARD_MUSEUM_CATEGORY = PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM.value
STANDARD_ART_MUSEUM_CATEGORY = PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART_MUSEUM.value
STANDARD_PARKING_CATEGORY = PlaceCategoryCode.TRANSPORT_PARKING.value
STANDARD_TOURIST_SITE_CATEGORY = PlaceCategoryCode.TOURISM.value
STANDARD_CULTURAL_FESTIVAL_CATEGORY = PlaceCategoryCode.TOURISM.value


@dataclass(frozen=True)
class SkippedStandardDataRecord:
    dataset_key: str
    source_entity_id: str | None
    reason: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class StandardDataFeatureBundle:
    feature: Feature
    source_record: SourceRecord
    source_link: SourceLink
    address_match_report: AddressMatchReport
    place_detail: PlaceDetail | None = None
    event_detail: EventDetail | None = None
    route_detail: RouteDetail | None = None


@dataclass(frozen=True)
class StandardDataFeatureEtlResult:
    dataset_key: str
    scanned_pages: int
    features: tuple[Feature, ...]
    source_records: tuple[SourceRecord, ...]
    source_links: tuple[SourceLink, ...]
    place_details: tuple[PlaceDetail, ...] = ()
    event_details: tuple[EventDetail, ...] = ()
    route_details: tuple[RouteDetail, ...] = ()
    address_match_reports: tuple[AddressMatchReport, ...] = ()
    skipped_items: tuple[SkippedStandardDataRecord, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.features)


@dataclass(frozen=True)
class StandardDataFeatureDbEtlResult:
    collection: StandardDataFeatureEtlResult
    load: FeatureDbLoadResult

    @property
    def item_count(self) -> int:
        return self.collection.item_count


@dataclass(frozen=True)
class StandardDataLoadResources:
    client: StandardDataClient | None = None
    session: Any | None = None
    items: Iterable[Mapping[str, Any]] | None = None
    reverse_geocoder: ReverseGeocoder | None = None
    kraddr_geo_store: Any | None = None
    kraddr_geo_database_path: str | None = None
    kraddr_geo_store_kwargs: Mapping[str, Any] | None = None
    kraddr_geo_fallback: bool = True
    kraddr_geo_max_distance_m: float | None = 50.0


def collect_standard_data_features(
    dataset_key: str,
    records: Iterable[Mapping[str, Any]],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    scanned_pages: int = 0,
) -> StandardDataFeatureEtlResult:
    spec = standard_dataset_spec(dataset_key)
    features: list[Feature] = []
    source_records: list[SourceRecord] = []
    source_links: list[SourceLink] = []
    place_details: list[PlaceDetail] = []
    event_details: list[EventDetail] = []
    route_details: list[RouteDetail] = []
    address_reports: list[AddressMatchReport] = []
    skipped_items: list[SkippedStandardDataRecord] = []

    for record in records:
        bundle = standard_data_record_to_feature_bundle(
            spec,
            record,
            collected_at=collected_at,
            reverse_geocoder=reverse_geocoder,
        )
        if isinstance(bundle, SkippedStandardDataRecord):
            skipped_items.append(bundle)
            continue
        features.append(bundle.feature)
        source_records.append(bundle.source_record)
        source_links.append(bundle.source_link)
        address_reports.append(bundle.address_match_report)
        if bundle.place_detail is not None:
            place_details.append(bundle.place_detail)
        if bundle.event_detail is not None:
            event_details.append(bundle.event_detail)
        if bundle.route_detail is not None:
            route_details.append(bundle.route_detail)

    return StandardDataFeatureEtlResult(
        dataset_key=dataset_key,
        scanned_pages=scanned_pages,
        features=tuple(features),
        source_records=tuple(source_records),
        source_links=tuple(source_links),
        place_details=tuple(place_details),
        event_details=tuple(event_details),
        route_details=tuple(route_details),
        address_match_reports=tuple(address_reports),
        skipped_items=tuple(skipped_items),
    )


async def async_collect_standard_data_features(
    client: StandardDataClient,
    dataset_key: str,
    *,
    page_size: int = 1000,
    max_pages: int | None = None,
    max_items: int | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    **params: Any,
) -> StandardDataFeatureEtlResult:
    records: list[Mapping[str, Any]] = []
    scanned_pages = 0
    async for page in client.iter_pages(
        dataset_key,
        num_of_rows=page_size,
        max_pages=max_pages,
        max_items=max_items,
        **params,
    ):
        scanned_pages += 1
        records.extend(page.items)
        if collected_at is None:
            collected_at = page.collected_at
    return collect_standard_data_features(
        dataset_key,
        records,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
        scanned_pages=scanned_pages,
    )


def load_standard_data_result(
    session: Any,
    result: StandardDataFeatureEtlResult,
) -> FeatureDbLoadResult:
    return load_feature_rows(
        session,
        feature_items=result.features,
        source_record_items=result.source_records,
        source_link_items=result.source_links,
        place_detail_items=result.place_details,
        event_detail_items=result.event_details,
        route_detail_items=result.route_details,
    )


async def async_collect_and_load_standard_data_features(
    session: Any,
    client: StandardDataClient,
    dataset_key: str,
    *,
    page_size: int = 1000,
    max_pages: int | None = None,
    max_items: int | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
    **params: Any,
) -> StandardDataFeatureDbEtlResult:
    collection = await async_collect_standard_data_features(
        client,
        dataset_key,
        page_size=page_size,
        max_pages=max_pages,
        max_items=max_items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
        **params,
    )
    return StandardDataFeatureDbEtlResult(
        collection=collection,
        load=load_standard_data_result(session, collection),
    )


def load_standard_data_features(
    resource: Any,
    run: DagsterEtlRun,
) -> StandardDataFeatureEtlResult | StandardDataFeatureDbEtlResult:
    """TripMate Dagster op body for data.go.kr standard feature ETL."""

    resources = _resolve_standard_data_resources(resource)
    config = run.op_config
    dataset_key = str(config.get("dataset_key") or run.dataset_key)
    page_size = _optional_int(config.get("page_size")) or 1000
    max_pages = _optional_int(config.get("max_pages"))
    max_items = _optional_int(config.get("max_items"))

    if resources.items is not None:
        collection = collect_standard_data_features(
            dataset_key,
            resources.items,
            collected_at=run.collected_at,
            reverse_geocoder=resources.reverse_geocoder,
        )
    else:
        client = resources.client or StandardDataClient.aio()
        collection = _run_async(
            async_collect_standard_data_features(
                client,
                dataset_key,
                page_size=page_size,
                max_pages=max_pages,
                max_items=max_items,
                collected_at=run.collected_at,
                reverse_geocoder=resources.reverse_geocoder,
            )
        )

    if resources.session is None:
        return collection
    return StandardDataFeatureDbEtlResult(
        collection=collection,
        load=load_standard_data_result(resources.session, collection),
    )


def standard_data_full_scan_identity(
    _session: Any,
    dataset_key: str,
    execution: DagsterEtlExecution,
) -> EtlRunIdentity:
    logical_date = execution.logical_datetime_kst.date()
    return EtlRunIdentity(
        run_key=f"{dataset_key}-{logical_date:%Y%m%d}-full-scan",
        run_type=execution.run_type,
        trigger_date=logical_date,
    )


def standard_data_full_scan_job_spec(dataset_key: str) -> EtlJobSpec:
    spec = standard_dataset_spec(dataset_key)
    return EtlJobSpec(
        job_name=f"{spec.dataset_key}_full_scan",
        op_name="collect_standard_data_features",
        dataset_key=spec.dataset_key,
        description=(
            f"Collect {spec.title} from data.go.kr and normalize it into "
            f"{spec.feature_kind} features."
        ),
        tags=(
            f"provider:{DATA_GO_KR_STANDARD_PROVIDER}",
            f"dataset:{spec.dataset_key}",
            f"feature:{spec.feature_kind}",
            "source:standard-data",
            "full_scan",
            f"schedule:{spec.official_refresh_cycle}",
            "pagination:all-pages",
        ),
        loader=load_standard_data_features,
        success_message=f"{spec.title} full scan completed.",
        failure_message=f"{spec.title} full scan failed.",
        identity_resolver=standard_data_full_scan_identity,
        schedule_enabled=schedule_requires_any_env(
            "DATAGOKR_API_KEY",
            "DATA_GO_KR_SERVICE_KEY",
            "PUBLIC_DATA_SERVICE_KEY",
            "SERVICE_KEY",
        ),
    )


def standard_data_full_scan_job_specs() -> tuple[EtlJobSpec, ...]:
    return tuple(
        standard_data_full_scan_job_spec(spec.dataset_key) for spec in standard_dataset_specs()
    )


def standard_data_record_to_feature_bundle(
    spec: StandardDatasetSpec,
    record: Mapping[str, Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> StandardDataFeatureBundle | SkippedStandardDataRecord:
    if spec.dataset_key == STANDARD_TOURISM_ROADS:
        return _route_bundle(spec, record, collected_at, reverse_geocoder)
    if spec.dataset_key == STANDARD_MUSEUMS:
        return _place_bundle(
            spec,
            record,
            name_keys=("fcltyNm",),
            category=_museum_category(record),
            marker_icon="museum",
            marker_color="#5B6CFF",
            place_kind="museum_art_gallery",
            collected_at=collected_at,
            reverse_geocoder=reverse_geocoder,
        )
    if spec.dataset_key == STANDARD_PARKING_LOTS:
        return _place_bundle(
            spec,
            record,
            name_keys=("prkplceNm",),
            category=STANDARD_PARKING_CATEGORY,
            marker_icon="parking",
            marker_color="#4A5568",
            place_kind="parking_lot",
            collected_at=collected_at,
            reverse_geocoder=reverse_geocoder,
        )
    if spec.dataset_key == STANDARD_TOURIST_SITES:
        return _place_bundle(
            spec,
            record,
            name_keys=("trrsrtNm",),
            category=STANDARD_TOURIST_SITE_CATEGORY,
            marker_icon="attraction",
            marker_color="#2B6CB0",
            place_kind="tourist_site",
            collected_at=collected_at,
            reverse_geocoder=reverse_geocoder,
        )
    if spec.dataset_key == STANDARD_CULTURAL_FESTIVALS:
        return _event_bundle(spec, record, collected_at, reverse_geocoder)
    return SkippedStandardDataRecord(spec.dataset_key, None, "unsupported dataset", record)


def _route_bundle(
    spec: StandardDatasetSpec,
    record: Mapping[str, Any],
    collected_at: datetime | None,
    reverse_geocoder: ReverseGeocoder | None,
) -> StandardDataFeatureBundle | SkippedStandardDataRecord:
    name = _text(record, "stretNm")
    source_key = _route_source_key(record)
    if source_key is None:
        return SkippedStandardDataRecord(spec.dataset_key, None, "missing route key", record)
    if name is None:
        return SkippedStandardDataRecord(spec.dataset_key, source_key, "missing route name", record)

    address = _address_from_road_endpoints(record)
    enrichment = enrich_address_from_coordinate(
        address=address,
        coordinate=None,
        raw=record,
        reverse_geocoder=reverse_geocoder,
        source_label=spec.dataset_key,
        source_entity_id=source_key,
    )
    raw_payload_hash = make_payload_hash(record, length=32)
    feature_id = make_feature_id(
        provider=DATA_GO_KR_STANDARD_PROVIDER,
        source_type=spec.source_entity_type,
        source_natural_key=source_key,
        kind=FeatureKind.ROUTE,
        category=STANDARD_ROUTE_CATEGORY,
        legal_dong_code=enrichment.address.legal_dong_code,
    )
    source_record = _source_record(
        spec,
        record,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        raw_name=name,
        raw_address=enrichment.address.display_address,
        coordinate=None,
        collected_at=collected_at,
    )
    route_type = _route_type(record)
    route_payload = {
        "type": route_type,
        "introduction": _text(record, "stretIntrcn"),
        "length": _text(record, "stretLt"),
        "required_time": _text(record, "reqreTime"),
        "begin_spot_name": _text(record, "beginSpotNm"),
        "begin_road_address": _text(record, "beginRdnmadr"),
        "begin_jibun_address": _text(record, "beginLnmadr"),
        "end_spot_name": _text(record, "endSpotNm"),
        "end_road_address": _text(record, "endRdnmadr"),
        "end_jibun_address": _text(record, "endLnmadr", "endLatitude"),
        "course_text": _text(record, "coursInfo"),
        "geometry_status": "missing_route_geometry",
    }
    feature = _feature(
        feature_id=feature_id,
        kind=FeatureKind.ROUTE,
        name=name,
        category=STANDARD_ROUTE_CATEGORY,
        marker_icon="trailhead",
        marker_color="#2F855A",
        coordinate=None,
        address=enrichment.address,
        detail={
            **_base_detail(spec, record, source_key),
            "route": route_payload,
        },
        dataset_key=spec.dataset_key,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        collected_at=collected_at,
    )
    route_detail = RouteDetail(
        feature_id=feature_id,
        route_type=route_type,
        geometry_source=spec.dataset_key,
        geometry_status="missing_route_geometry",
        total_distance_meters=_distance_meters(_text(record, "stretLt")),
        expected_duration_minutes=_duration_minutes(_text(record, "reqreTime")),
        begin_name=_text(record, "beginSpotNm"),
        begin_address=_text(record, "beginRdnmadr", "beginLnmadr"),
        end_name=_text(record, "endSpotNm"),
        end_address=_text(record, "endRdnmadr", "endLnmadr", "endLatitude"),
        payload={**_base_detail(spec, record, source_key), "route": route_payload},
    )
    return _bundle(
        feature,
        source_record,
        "standard_data_route_key",
        enrichment.report,
        route_detail=route_detail,
    )


def _place_bundle(
    spec: StandardDatasetSpec,
    record: Mapping[str, Any],
    *,
    name_keys: tuple[str, ...],
    category: str,
    marker_icon: str,
    marker_color: str,
    place_kind: str,
    collected_at: datetime | None,
    reverse_geocoder: ReverseGeocoder | None,
) -> StandardDataFeatureBundle | SkippedStandardDataRecord:
    name = _text(record, *name_keys)
    source_key = _place_source_key(spec, record, name_keys=name_keys)
    if source_key is None:
        return SkippedStandardDataRecord(spec.dataset_key, None, "missing place key", record)
    if name is None:
        return SkippedStandardDataRecord(spec.dataset_key, source_key, "missing place name", record)

    coordinate = _coordinate(record)
    enrichment = enrich_address_from_coordinate(
        address=_address_from_record(record),
        coordinate=coordinate,
        raw=record,
        reverse_geocoder=reverse_geocoder,
        source_label=spec.dataset_key,
        source_entity_id=source_key,
    )
    raw_payload_hash = make_payload_hash(record, length=32)
    feature_id = make_feature_id(
        provider=DATA_GO_KR_STANDARD_PROVIDER,
        source_type=spec.source_entity_type,
        source_natural_key=source_key,
        kind=FeatureKind.PLACE,
        category=category,
        legal_dong_code=enrichment.address.legal_dong_code,
    )
    source_record = _source_record(
        spec,
        record,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        raw_name=name,
        raw_address=enrichment.address.display_address,
        coordinate=coordinate,
        collected_at=collected_at,
    )
    detail = _place_detail_payload(spec, record, source_key)
    feature = _feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        category=category,
        marker_icon=marker_icon,
        marker_color=marker_color,
        coordinate=coordinate,
        address=enrichment.address,
        urls=_urls_from_record(record),
        detail=detail,
        dataset_key=spec.dataset_key,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        collected_at=collected_at,
    )
    place_detail = PlaceDetail(
        feature_id=feature_id,
        place_kind=place_kind,
        phones=_phones(record),
        business_hours=_opening_hours(record),
        facility_info=_facility_info(spec, record),
        payload=detail,
    )
    return _bundle(
        feature,
        source_record,
        "standard_data_place_key",
        enrichment.report,
        place_detail=place_detail,
    )


def _event_bundle(
    spec: StandardDatasetSpec,
    record: Mapping[str, Any],
    collected_at: datetime | None,
    reverse_geocoder: ReverseGeocoder | None,
) -> StandardDataFeatureBundle | SkippedStandardDataRecord:
    name = _text(record, "fstvlNm")
    source_key = _festival_source_key(record)
    if source_key is None:
        return SkippedStandardDataRecord(spec.dataset_key, None, "missing event key", record)
    if name is None:
        return SkippedStandardDataRecord(spec.dataset_key, source_key, "missing event name", record)

    coordinate = _coordinate(record)
    enrichment = enrich_address_from_coordinate(
        address=_address_from_record(record),
        coordinate=coordinate,
        raw=record,
        reverse_geocoder=reverse_geocoder,
        source_label=spec.dataset_key,
        source_entity_id=source_key,
    )
    raw_payload_hash = make_payload_hash(record, length=32)
    feature_id = make_feature_id(
        provider=DATA_GO_KR_STANDARD_PROVIDER,
        source_type=spec.source_entity_type,
        source_natural_key=source_key,
        kind=FeatureKind.EVENT,
        category=STANDARD_CULTURAL_FESTIVAL_CATEGORY,
        legal_dong_code=enrichment.address.legal_dong_code,
    )
    source_record = _source_record(
        spec,
        record,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        raw_name=name,
        raw_address=enrichment.address.display_address,
        coordinate=coordinate,
        collected_at=collected_at,
    )
    detail = {
        **_base_detail(spec, record, source_key),
        "festival": {
            "venue": _text(record, "opar"),
            "content": _text(record, "fstvlCo"),
            "organizer": _text(record, "mnnstNm"),
            "host": _text(record, "auspcInsttNm"),
            "supporters": _text(record, "suprtInsttNm"),
            "related_info": _text(record, "relateInfo"),
        },
    }
    feature = _feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name=name,
        category=STANDARD_CULTURAL_FESTIVAL_CATEGORY,
        marker_icon="theatre",
        marker_color="#DD6B20",
        coordinate=coordinate,
        address=enrichment.address,
        urls=_urls_from_record(record),
        detail=detail,
        dataset_key=spec.dataset_key,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        collected_at=collected_at,
    )
    event_detail = EventDetail(
        feature_id=feature_id,
        event_kind="cultural_festival",
        starts_on=_date_or_none(_text(record, "fstvlStartDate")),
        ends_on=_date_or_none(_text(record, "fstvlEndDate")),
        venue_name=_text(record, "opar"),
        tel=_text(record, "phoneNumber"),
        content_id=source_key,
        payload=detail,
    )
    return _bundle(
        feature,
        source_record,
        "standard_data_event_key",
        enrichment.report,
        event_detail=event_detail,
    )


def _source_record(
    spec: StandardDatasetSpec,
    record: Mapping[str, Any],
    *,
    source_entity_id: str,
    raw_payload_hash: str,
    raw_name: str | None,
    raw_address: str | None,
    coordinate: Coordinate | None,
    collected_at: datetime | None,
) -> SourceRecord:
    return SourceRecord(
        provider=DATA_GO_KR_STANDARD_PROVIDER,
        dataset_key=spec.dataset_key,
        source_entity_type=spec.source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=raw_payload_hash,
        source_version=_text(record, "referenceDate"),
        raw_name=raw_name,
        raw_address=raw_address,
        raw_longitude=Decimal(str(coordinate.longitude)) if coordinate is not None else None,
        raw_latitude=Decimal(str(coordinate.latitude)) if coordinate is not None else None,
        raw_data=dict(record),
        fetched_at=collected_at,
        imported_at=collected_at or _now_kst(),
    )


def _feature(
    *,
    feature_id: str,
    kind: FeatureKind,
    name: str,
    category: str,
    marker_icon: str,
    marker_color: str,
    coordinate: Coordinate | None,
    address: Address,
    detail: dict[str, Any],
    dataset_key: str,
    source_entity_id: str,
    raw_payload_hash: str,
    collected_at: datetime | None,
    urls: FeatureUrls | None = None,
) -> Feature:
    return Feature(
        feature_id=feature_id,
        kind=kind,
        name=name,
        coord=coordinate,
        address=address,
        category=category,
        urls=urls or FeatureUrls(),
        marker_icon=marker_icon,
        marker_color=marker_color,
        detail=detail,
        raw_refs=[
            RawDataRef(
                provider=DATA_GO_KR_STANDARD_PROVIDER,
                dataset_key=dataset_key,
                source_entity_id=source_entity_id,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected_at,
                payload_hash=raw_payload_hash,
            )
        ],
    )


def _bundle(
    feature: Feature,
    source_record: SourceRecord,
    match_method: str,
    report: AddressMatchReport,
    *,
    place_detail: PlaceDetail | None = None,
    event_detail: EventDetail | None = None,
    route_detail: RouteDetail | None = None,
) -> StandardDataFeatureBundle:
    return StandardDataFeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=SourceLink(
            feature_id=feature.feature_id,
            source_record_key=source_record.key(),
            source_role=SourceRole.PRIMARY,
            match_method=match_method,
            confidence=100,
            is_primary_source=True,
        ),
        address_match_report=report,
        place_detail=place_detail,
        event_detail=event_detail,
        route_detail=route_detail,
    )


def _base_detail(
    spec: StandardDatasetSpec,
    record: Mapping[str, Any],
    source_key: str,
) -> dict[str, Any]:
    return {
        "selected_source": {
            "provider": DATA_GO_KR_STANDARD_PROVIDER,
            "dataset_key": spec.dataset_key,
            "dataset_id": spec.dataset_id,
            "source_type": spec.source_entity_type,
            "source_entity_id": source_key,
            "portal_url": spec.portal_url,
        },
        "reference_date": _text(record, "referenceDate"),
        "institution": {
            "code": _text(record, "instt_code"),
            "name": _text(record, "instt_nm", "institutionNm"),
        },
        "raw": dict(record),
    }


def _place_detail_payload(
    spec: StandardDatasetSpec,
    record: Mapping[str, Any],
    source_key: str,
) -> dict[str, Any]:
    detail = _base_detail(spec, record, source_key)
    detail["place"] = {
        "type": _text(record, "fcltyType", "prkplceSe", "prkplceType", "trrsrtSe"),
        "description": _text(record, "fcltyIntrcn", "trrsrtIntrcn"),
        "transport_info": _text(record, "trnsportInfo"),
        "fee": _fee_payload(record),
        "parking_fee": _parking_fee_payload(record),
        "designation_date": _text(record, "appnDate"),
        "capacity": _text(record, "aceptncCo"),
        "parking_capacity": _text(record, "prkplceCo", "prkcmprt"),
    }
    return detail


def _facility_info(spec: StandardDatasetSpec, record: Mapping[str, Any]) -> dict[str, Any]:
    if spec.dataset_key == STANDARD_MUSEUMS:
        return {
            "facility_info": _text(record, "fcltyInfo"),
            "closed_days": _text(record, "rstdeInfo"),
            "operator_phone": _text(record, "operPhoneNumber"),
            "operator_name": _text(record, "operInstitutionNm"),
            "transport_info": _text(record, "trnsportInfo"),
        }
    if spec.dataset_key == STANDARD_PARKING_LOTS:
        return {
            "parking_lot_no": _text(record, "prkplceNo"),
            "parking_section": _text(record, "prkplceSe"),
            "parking_type": _text(record, "prkplceType"),
            "capacity": _text(record, "prkcmprt"),
            "operation_days": _text(record, "operDay"),
            "charge_info": _text(record, "parkingchrgeInfo"),
            "disabled_parking_zone": _text(record, "pwdbsPpkZoneYn"),
        }
    if spec.dataset_key == STANDARD_TOURIST_SITES:
        return {
            "tourist_site_type": _text(record, "trrsrtSe"),
            "area_square_meters": _text(record, "ar"),
            "public_facility": _text(record, "cnvnncFclty"),
            "lodging": _text(record, "stayngInfo"),
            "sports_and_recreation": _text(record, "mvmAmsmtFclty"),
            "culture_facility": _text(record, "recrtClturFclty"),
            "hospitality": _text(record, "hospitalityFclty"),
            "support_facility": _text(record, "sportFclty"),
        }
    return {}


def _opening_hours(record: Mapping[str, Any]) -> FeatureOpeningHours | None:
    periods: list[OpeningPeriod] = []
    for days, open_key, close_key in (
        ((0, 1, 2, 3, 4), "weekdayOperOpenHhmm", "weekdayOperColseHhmm"),
        ((5,), "satOperOperOpenHhmm", "satOperCloseHhmm"),
        ((6,), "holidayOperOpenHhmm", "holidayCloseOpenHhmm"),
    ):
        open_time = _hhmm(_text(record, open_key))
        close_time = _hhmm(_text(record, close_key))
        if open_time is None or close_time is None:
            continue
        for day in days:
            try:
                periods.append(
                    OpeningPeriod(
                        open=OpeningTime(day=day, time=open_time),
                        close=OpeningTime(day=day, time=close_time),
                    )
                )
            except ValueError:
                continue
    return FeatureOpeningHours(periods=periods) if periods else None


def _hhmm(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 3:
        digits = f"0{digits}"
    if len(digits) != 4:
        return None
    return digits


def _phones(record: Mapping[str, Any]) -> list[str]:
    phones: list[str] = []
    for key in ("phoneNumber", "operPhoneNumber"):
        value = _text(record, key)
        if value and value not in phones:
            phones.append(value)
    return phones[:3]


def _urls_from_record(record: Mapping[str, Any]) -> FeatureUrls:
    url = _url_or_none(_text(record, "homepageUrl"))
    if url is None:
        return FeatureUrls()
    try:
        return FeatureUrls(homepage=url)
    except ValueError:
        return FeatureUrls()


def _coordinate(record: Mapping[str, Any]) -> Coordinate | None:
    lat = _float_or_none(_text(record, "latitude"))
    lon = _float_or_none(_text(record, "longitude"))
    if lat is None or lon is None:
        return None
    if not 33.0 <= lat <= 39.5 or not 124.0 <= lon <= 132.0:
        return None
    return Coordinate(lat=lat, lon=lon)


def _address_from_record(record: Mapping[str, Any]) -> Address:
    road = _text(record, "rdnmadr")
    jibun = _text(record, "lnmadr")
    return Address.from_mapping({"road_address": road, "jibun_address": jibun}) or Address(
        address=road or jibun
    )


def _address_from_road_endpoints(record: Mapping[str, Any]) -> Address:
    road = _text(record, "beginRdnmadr") or _text(record, "endRdnmadr")
    jibun = _text(record, "beginLnmadr") or _text(record, "endLnmadr", "endLatitude")
    return Address.from_mapping({"road_address": road, "jibun_address": jibun}) or Address(
        address=road or jibun
    )


def _route_source_key(record: Mapping[str, Any]) -> str | None:
    return _join_key(
        _text(record, "stretNm"),
        _text(record, "beginRdnmadr", "beginLnmadr"),
        _text(record, "endRdnmadr", "endLnmadr", "endLatitude"),
        _text(record, "referenceDate"),
        _text(record, "instt_code"),
    )


def _place_source_key(
    spec: StandardDatasetSpec,
    record: Mapping[str, Any],
    *,
    name_keys: tuple[str, ...],
) -> str | None:
    if spec.dataset_key == STANDARD_PARKING_LOTS:
        key = _text(record, "prkplceNo")
        if key:
            return key
    return _join_key(
        _text(record, *name_keys),
        _text(record, "rdnmadr"),
        _text(record, "lnmadr"),
        _text(record, "latitude"),
        _text(record, "longitude"),
        _text(record, "referenceDate"),
        _text(record, "instt_code"),
    )


def _festival_source_key(record: Mapping[str, Any]) -> str | None:
    return _join_key(
        _text(record, "fstvlNm"),
        _text(record, "opar"),
        _text(record, "fstvlStartDate"),
        _text(record, "fstvlEndDate"),
        _text(record, "latitude"),
        _text(record, "longitude"),
        _text(record, "instt_code"),
    )


def _route_type(record: Mapping[str, Any]) -> str:
    text = " ".join(
        value
        for value in (
            _text(record, "stretNm"),
            _text(record, "stretIntrcn"),
            _text(record, "coursInfo"),
        )
        if value
    )
    normalized = text.lower()
    if "무장애" in text or "장애물없는" in text or "barrier" in normalized:
        return ROUTE_TYPE_ACCESSIBLE_WALK
    if "등산" in text or "산행" in text or "탐방로" in text or "mountain" in normalized:
        return ROUTE_TYPE_HIKING_TRAIL
    if "트레킹" in text or "트래킹" in text or "둘레" in text or "올레" in text:
        return ROUTE_TYPE_TREKKING
    if "자전거" in text or "cycling" in normalized or "bike" in normalized:
        return ROUTE_TYPE_CYCLING
    if "드라이브" in text or "drive" in normalized:
        return ROUTE_TYPE_DRIVE_COURSE
    if "산책" in text or "걷기" in text or "도보" in text or "walking" in normalized:
        return ROUTE_TYPE_WALKING_COURSE
    return ROUTE_TYPE_TOURISM_ROAD


def _resolve_standard_data_resources(resource: Any) -> StandardDataLoadResources:
    if isinstance(resource, StandardDataLoadResources):
        if resource.reverse_geocoder is not None:
            return resource
        return replace(resource, reverse_geocoder=resolve_reverse_geocoder(resource))
    if isinstance(resource, Mapping):
        return StandardDataLoadResources(
            client=resource.get("client"),
            session=resource.get("session") or resource.get("db_session"),
            items=resource.get("items") if isinstance(resource.get("items"), Iterable) else None,
            reverse_geocoder=resolve_reverse_geocoder(resource),
        )
    return StandardDataLoadResources(
        client=getattr(resource, "client", None),
        session=getattr(resource, "session", None) or getattr(resource, "db_session", None),
        items=getattr(resource, "items", None),
        reverse_geocoder=resolve_reverse_geocoder(resource),
    )


def _run_async(coro: Any) -> Any:
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(f"standard data ETL cannot run nested asyncio loop {loop!r}")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _join_key(*parts: str | None) -> str | None:
    values = [part.strip() for part in parts if part and part.strip()]
    return "|".join(values) if values else None


def _museum_category(record: Mapping[str, Any]) -> str:
    text = (_text(record, "fcltyNm", "fcltyType") or "").lower()
    if "미술" in text or "art" in text:
        return STANDARD_ART_MUSEUM_CATEGORY
    return STANDARD_MUSEUM_CATEGORY


def _fee_payload(record: Mapping[str, Any]) -> dict[str, str]:
    return _without_none(
        {
            "adult": _text(record, "adultChrge"),
            "youth": _text(record, "yngbgsChrge"),
            "child": _text(record, "childChrge"),
            "etc": _text(record, "etcChrgeInfo"),
        }
    )


def _parking_fee_payload(record: Mapping[str, Any]) -> dict[str, str]:
    return _without_none(
        {
            "charge_info": _text(record, "parkingchrgeInfo"),
            "basic_time": _text(record, "basicTime"),
            "basic_charge": _text(record, "basicCharge"),
            "add_unit_time": _text(record, "addUnitTime"),
            "add_unit_charge": _text(record, "addUnitCharge"),
            "daily_ticket": _text(record, "dayCmmtkt"),
            "monthly_ticket": _text(record, "monthCmmtkt"),
            "payment": _text(record, "metpay"),
        }
    )


def _without_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", {}, [])}


def _text(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            text = str(value).strip()
            if text:
                return text
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


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _date_or_none(value: str | None) -> date | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) == 8:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    return None


def _duration_minutes(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    hours = 0
    minutes = 0
    hour_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:시간|hr|hour)", text, re.IGNORECASE)
    minute_match = re.search(r"(\d+)\s*(?:분|min|minute)", text, re.IGNORECASE)
    if hour_match:
        hours = int(Decimal(hour_match.group(1)) * 60)
    if minute_match:
        minutes = int(minute_match.group(1))
    if hours or minutes:
        return hours + minutes
    digits = re.sub(r"[^0-9.]", "", text)
    if not digits:
        return None
    try:
        number = Decimal(digits)
    except InvalidOperation:
        return None
    return int(number) if number > 0 else None


def _distance_meters(value: str | None) -> Decimal | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if match is None:
        return None
    try:
        number = Decimal(match.group(0))
    except InvalidOperation:
        return None
    lower = text.lower()
    if "km" in lower or "㎞" in text:
        return number * Decimal("1000")
    if "m" in lower or "미터" in text:
        return number
    return number * Decimal("1000")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
