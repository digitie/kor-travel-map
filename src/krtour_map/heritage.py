from __future__ import annotations

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
from krtour_map.etl import tuple_from_async_iterable
from krtour_map.files import (
    FeatureFileSource,
    FileFetcher,
    RustfsFileStore,
    upload_feature_file_sources_to_rustfs,
)
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import (
    AreaDetail,
    Coordinate,
    EventDetail,
    Feature,
    FeatureFile,
    PlaceDetail,
    RawDataRef,
    SourceLink,
    SourceRecord,
)

KRHERITAGE_PROVIDER = "python-krheritage-api"
KRHERITAGE_HERITAGE_DATASET_KEY = "search_list"
KRHERITAGE_EVENT_DATASET_KEY = "event_list"
KRHERITAGE_GIS_SPCA_DATASET_KEY = "gis_spca"
KRHERITAGE_GIS_3070426_DATASET_KEY = "gis_3070426"
KRHERITAGE_HERITAGE_SOURCE_TYPE = "heritage"
KRHERITAGE_EVENT_SOURCE_TYPE = "heritage_event"
KRHERITAGE_HERITAGE_FULL_SCAN_INTERVAL_DAYS = 7
KRHERITAGE_EVENT_FULL_SCAN_INTERVAL_DAYS = 1
KRHERITAGE_DEFAULT_PAGE_SIZE = 100
KRHERITAGE_EVENT_DEFAULT_MONTHS_BACK = 1
KRHERITAGE_EVENT_DEFAULT_MONTHS_AHEAD = 12

KRHERITAGE_CULTURAL_CATEGORY = PlaceCategoryCode.TOURISM_HERITAGE_HISTORIC_SITE.value
KRHERITAGE_NATURAL_CATEGORY = PlaceCategoryCode.TOURISM_NATURE.value
KRHERITAGE_INTANGIBLE_CATEGORY = (
    PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL.value
)
KRHERITAGE_EVENT_CATEGORY = PlaceCategoryCode.TOURISM.value

KRHERITAGE_AREA_TYPE_CODES = frozenset(
    {
        "13",  # legacy historic site
        "14",  # legacy historic scenic/scenic variants in older APIs
        "27",  # historic site
        "28",  # historic scenic
        "29",  # scenic site
        "35",  # local memorial
        "40",  # buried heritage
    }
)
KRHERITAGE_INTANGIBLE_TYPE_CODES = frozenset({"16", "31", "34"})
KRHERITAGE_NATURAL_TYPE_CODES = frozenset({"15", "28", "29", "30", "35"})


@dataclass(frozen=True)
class SkippedKrHeritageItem:
    source_entity_id: str | None
    reason: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class KrHeritageFeatureBundle:
    feature: Feature
    source_record: SourceRecord
    source_link: SourceLink
    address_match_report: AddressMatchReport
    place_detail: PlaceDetail | None = None
    area_detail: AreaDetail | None = None
    feature_file_sources: tuple[FeatureFileSource, ...] = ()


@dataclass(frozen=True)
class KrHeritageFeatureEtlResult:
    dataset_key: str
    features: tuple[Feature, ...]
    source_records: tuple[SourceRecord, ...]
    source_links: tuple[SourceLink, ...]
    place_details: tuple[PlaceDetail, ...] = ()
    area_details: tuple[AreaDetail, ...] = ()
    feature_file_sources: tuple[FeatureFileSource, ...] = ()
    address_match_reports: tuple[AddressMatchReport, ...] = ()
    skipped_items: tuple[SkippedKrHeritageItem, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.features)


@dataclass(frozen=True)
class KrHeritageEventBundle:
    feature: Feature
    event_detail: EventDetail
    source_record: SourceRecord
    source_link: SourceLink
    address_match_report: AddressMatchReport
    feature_file_sources: tuple[FeatureFileSource, ...] = ()


@dataclass(frozen=True)
class KrHeritageEventEtlResult:
    dataset_key: str
    features: tuple[Feature, ...]
    event_details: tuple[EventDetail, ...]
    source_records: tuple[SourceRecord, ...]
    source_links: tuple[SourceLink, ...]
    feature_file_sources: tuple[FeatureFileSource, ...] = ()
    address_match_reports: tuple[AddressMatchReport, ...] = ()
    skipped_items: tuple[SkippedKrHeritageItem, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.features)


@dataclass(frozen=True)
class KrHeritageFeatureDbEtlResult:
    collection: KrHeritageFeatureEtlResult | KrHeritageEventEtlResult
    load: FeatureDbLoadResult

    @property
    def item_count(self) -> int:
        return self.collection.item_count


@dataclass(frozen=True)
class KrHeritageFeatureLoadResources:
    client: Any | None = None
    session: Any | None = None
    heritage_items: Iterable[Any] | None = None
    event_items: Iterable[Any] | None = None
    rustfs_store: RustfsFileStore | None = None
    file_fetcher: FileFetcher | None = None
    reverse_geocoder: ReverseGeocoder | None = None
    kraddr_geo_store: Any | None = None
    kraddr_geo_database_path: str | None = None
    kraddr_geo_store_kwargs: Mapping[str, Any] | None = None
    kraddr_geo_fallback: bool = True
    kraddr_geo_max_distance_m: float | None = 50.0


def krheritage_natural_key(item: Any) -> str | None:
    """Return the stable 국가유산청 composite key from a provider model."""

    raw = _raw_mapping(item)
    key_obj = getattr(item, "key", None)
    kdcd = _optional_text(
        getattr(key_obj, "ccba_kdcd", None)
        or getattr(item, "ccba_kdcd", None)
        or getattr(item, "ccbaKdcd", None)
        or _first(raw, "ccbaKdcd", "ccba_kdcd", "ccba_kdcd_cd")
    )
    asno = _optional_text(
        getattr(key_obj, "ccba_asno", None)
        or getattr(item, "ccba_asno", None)
        or getattr(item, "ccbaAsno", None)
        or _first(raw, "ccbaAsno", "ccba_asno")
    )
    ctcd = _optional_text(
        getattr(key_obj, "ccba_ctcd", None)
        or getattr(item, "ccba_ctcd", None)
        or getattr(item, "ccbaCtcd", None)
        or _first(raw, "ccbaCtcd", "ccba_ctcd")
    )
    if kdcd is None or asno is None or ctcd is None:
        return None
    return f"{kdcd}-{asno}-{ctcd}"


def collect_krheritage_heritage_features(
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageFeatureEtlResult:
    features: list[Feature] = []
    source_records_result: list[SourceRecord] = []
    source_links_result: list[SourceLink] = []
    place_details: list[PlaceDetail] = []
    area_details: list[AreaDetail] = []
    feature_file_sources: list[FeatureFileSource] = []
    address_match_reports: list[AddressMatchReport] = []
    skipped_items: list[SkippedKrHeritageItem] = []

    for item in items:
        bundle = krheritage_heritage_item_to_feature_bundle(
            item,
            collected_at=collected_at,
            reverse_geocoder=reverse_geocoder,
        )
        if isinstance(bundle, SkippedKrHeritageItem):
            skipped_items.append(bundle)
            continue
        features.append(bundle.feature)
        source_records_result.append(bundle.source_record)
        source_links_result.append(bundle.source_link)
        if bundle.place_detail is not None:
            place_details.append(bundle.place_detail)
        if bundle.area_detail is not None:
            area_details.append(bundle.area_detail)
        feature_file_sources.extend(bundle.feature_file_sources)
        address_match_reports.append(bundle.address_match_report)

    return KrHeritageFeatureEtlResult(
        dataset_key=KRHERITAGE_HERITAGE_DATASET_KEY,
        features=tuple(features),
        source_records=tuple(source_records_result),
        source_links=tuple(source_links_result),
        place_details=tuple(place_details),
        area_details=tuple(area_details),
        feature_file_sources=tuple(feature_file_sources),
        address_match_reports=tuple(address_match_reports),
        skipped_items=tuple(skipped_items),
    )


async def async_collect_krheritage_heritage_features(
    items: Iterable[Any] | Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageFeatureEtlResult:
    """Async boundary for krheritage heritage typed models."""

    return collect_krheritage_heritage_features(
        await tuple_from_async_iterable(items),
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def krheritage_heritage_item_to_feature_bundle(
    item: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageFeatureBundle | SkippedKrHeritageItem:
    raw = _raw_mapping(item)
    source_key = krheritage_natural_key(item)
    if source_key is None:
        return SkippedKrHeritageItem(None, "missing heritage composite key", raw)

    name = _heritage_name(item, raw)
    if name is None:
        return SkippedKrHeritageItem(source_key, "missing heritage name", raw)

    coordinate = _coordinate_from_item(item, raw)
    address_enrichment = enrich_address_from_coordinate(
        address=_address_from_heritage_item(item, raw),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=KRHERITAGE_HERITAGE_DATASET_KEY,
        source_entity_id=source_key,
    )
    address = address_enrichment.address
    heritage_type_code = _heritage_type_code(item, raw)
    heritage_domain = _heritage_domain(item, raw, heritage_type_code=heritage_type_code)
    kind = _heritage_feature_kind(item, raw, heritage_type_code=heritage_type_code)
    category = _heritage_category(item, raw, heritage_domain=heritage_domain)
    marker_icon = _heritage_marker_icon(kind=kind, heritage_domain=heritage_domain)
    marker_color = _heritage_marker_color(heritage_domain)
    collected = collected_at or _now_kst()
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=KRHERITAGE_PROVIDER,
        source_type=KRHERITAGE_HERITAGE_SOURCE_TYPE,
        source_natural_key=source_key,
        kind=kind,
        category=category,
        legal_dong_code=address.legal_dong_code,
    )
    source_record = SourceRecord(
        provider=KRHERITAGE_PROVIDER,
        dataset_key=KRHERITAGE_HERITAGE_DATASET_KEY,
        source_entity_type=KRHERITAGE_HERITAGE_SOURCE_TYPE,
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
    detail_payload = _heritage_detail_payload(
        item,
        raw,
        source_key=source_key,
        kind=kind,
        category=category,
        heritage_domain=heritage_domain,
        heritage_type_code=heritage_type_code,
        address_match_report=address_enrichment.report,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=kind,
        name=name,
        coord=coordinate,
        address=address,
        category=category,
        marker_icon=marker_icon,
        marker_color=marker_color,
        detail=detail_payload,
        raw_refs=[
            RawDataRef(
                provider=KRHERITAGE_PROVIDER,
                dataset_key=KRHERITAGE_HERITAGE_DATASET_KEY,
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
        match_method="krheritage_composite_key",
        confidence=100,
        is_primary_source=True,
    )
    place_detail = None
    area_detail = None
    if kind == FeatureKind.AREA:
        area_detail = AreaDetail(
            feature_id=feature_id,
            area_kind=_area_kind(item, raw, heritage_type_code=heritage_type_code),
            boundary_source=_boundary_source(item, raw),
            area_square_meters=_decimal_or_none(
                _first(raw, "area", "area_sqm", "areaSquareMeters", "area_square_meters")
                or getattr(item, "area_square_meters", None)
            ),
            regulation_scope=_text(
                item,
                "regulation_scope",
                raw_keys=("regulationScope", "regulation_scope", "protectZone", "protect_zone"),
            ),
            administrative_office=_text(
                item,
                "administrator",
                "admin",
                raw_keys=("ccbaAdmin", "administrator", "admin", "ccbaPoss"),
            ),
            description=_text(item, "content", "description", raw_keys=("content", "description")),
            geometry=_geometry_from_item(item, raw),
            payload=detail_payload,
        )
    else:
        place_detail = PlaceDetail(
            feature_id=feature_id,
            place_kind=_place_kind(heritage_domain),
            phones=[],
            facility_info=_heritage_facility_info(item, raw, heritage_domain=heritage_domain),
            license_date=_date_or_none(
                getattr(item, "designated_date", None)
                or getattr(item, "designated_at", None)
                or _first(raw, "ccbaAsdt", "designated_date", "designated_at", "designationDate")
            ),
            payload=detail_payload,
        )
    return KrHeritageFeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
        address_match_report=address_enrichment.report,
        place_detail=place_detail,
        area_detail=area_detail,
        feature_file_sources=krheritage_heritage_item_to_file_sources(
            item,
            feature=feature,
            source_record_key=source_record_key,
            raw=raw,
        ),
    )


def krheritage_heritage_item_to_file_sources(
    item: Any,
    *,
    feature: Feature,
    source_record_key: str,
    raw: Mapping[str, Any] | None = None,
) -> tuple[FeatureFileSource, ...]:
    return _krheritage_media_file_sources(
        item,
        feature=feature,
        source_record_key=source_record_key,
        dataset_key=KRHERITAGE_HERITAGE_DATASET_KEY,
        source_key=krheritage_natural_key(item),
        raw=raw,
        main_candidates=(
            "image_url",
            "imageUrl",
            "mainImage",
            "ccimgeFileNm",
        ),
        main_field="imageUrl",
    )


def collect_krheritage_events(
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageEventEtlResult:
    features: list[Feature] = []
    event_details: list[EventDetail] = []
    source_records_result: list[SourceRecord] = []
    source_links_result: list[SourceLink] = []
    feature_file_sources: list[FeatureFileSource] = []
    address_match_reports: list[AddressMatchReport] = []
    skipped_items: list[SkippedKrHeritageItem] = []

    for item in items:
        bundle = krheritage_event_item_to_feature_bundle(
            item,
            collected_at=collected_at,
            reverse_geocoder=reverse_geocoder,
        )
        if isinstance(bundle, SkippedKrHeritageItem):
            skipped_items.append(bundle)
            continue
        features.append(bundle.feature)
        event_details.append(bundle.event_detail)
        source_records_result.append(bundle.source_record)
        source_links_result.append(bundle.source_link)
        feature_file_sources.extend(bundle.feature_file_sources)
        address_match_reports.append(bundle.address_match_report)

    return KrHeritageEventEtlResult(
        dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
        features=tuple(features),
        event_details=tuple(event_details),
        source_records=tuple(source_records_result),
        source_links=tuple(source_links_result),
        feature_file_sources=tuple(feature_file_sources),
        address_match_reports=tuple(address_match_reports),
        skipped_items=tuple(skipped_items),
    )


async def async_collect_krheritage_events(
    items: Iterable[Any] | Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageEventEtlResult:
    """Async boundary for krheritage event typed models."""

    return collect_krheritage_events(
        await tuple_from_async_iterable(items),
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def krheritage_event_item_to_feature_bundle(
    item: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageEventBundle | SkippedKrHeritageItem:
    raw = _raw_mapping(item)
    source_id = _text(item, "sn", "source_id", raw_keys=("sn", "SN", "source_id"))
    if source_id is None:
        return SkippedKrHeritageItem(None, "missing event source id", raw)
    title = _heritage_event_title(item, raw)
    if title is None:
        return SkippedKrHeritageItem(source_id, "missing event title", raw)

    coordinate = _coordinate_from_item(item, raw)
    address_enrichment = enrich_address_from_coordinate(
        address=_address_from_event_item(item, raw),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=KRHERITAGE_EVENT_DATASET_KEY,
        source_entity_id=source_id,
    )
    address = address_enrichment.address
    collected = collected_at or _now_kst()
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=KRHERITAGE_PROVIDER,
        source_type=KRHERITAGE_EVENT_SOURCE_TYPE,
        source_natural_key=source_id,
        kind=FeatureKind.EVENT,
        category=KRHERITAGE_EVENT_CATEGORY,
        legal_dong_code=address.legal_dong_code,
    )
    source_record = SourceRecord(
        provider=KRHERITAGE_PROVIDER,
        dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
        source_entity_type=KRHERITAGE_EVENT_SOURCE_TYPE,
        source_entity_id=source_id,
        raw_payload_hash=raw_payload_hash,
        raw_name=title,
        raw_address=address.display_address,
        raw_longitude=Decimal(str(coordinate.longitude)) if coordinate is not None else None,
        raw_latitude=Decimal(str(coordinate.latitude)) if coordinate is not None else None,
        raw_data=dict(raw),
        fetched_at=collected,
        imported_at=collected,
    )
    source_record_key = source_record.key()
    detail_payload = _event_detail_payload(item, raw, source_id=source_id)
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name=title,
        coord=coordinate,
        address=address,
        category=KRHERITAGE_EVENT_CATEGORY,
        marker_icon="theatre",
        marker_color="#DD6B20",
        detail=detail_payload,
        raw_refs=[
            RawDataRef(
                provider=KRHERITAGE_PROVIDER,
                dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
                source_entity_id=source_id,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    event_detail = EventDetail(
        feature_id=feature_id,
        event_kind="heritage_event",
        starts_on=_date_or_none(
            _first(raw, "startDate", "start_date")
            or getattr(item, "start_date", None)
            or getattr(item, "starts_on", None)
        ),
        ends_on=_date_or_none(
            _first(raw, "endDate", "end_date")
            or getattr(item, "end_date", None)
            or getattr(item, "ends_on", None)
        ),
        venue_name=_text(item, "site_name", "place", raw_keys=("siteName", "site_name", "place")),
        tel=_text(item, "tel_name", "tel", raw_keys=("telName", "tel")),
        content_id=source_id,
        payload=detail_payload,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="krheritage_event_id",
        confidence=100,
        is_primary_source=True,
    )
    return KrHeritageEventBundle(
        feature=feature,
        event_detail=event_detail,
        source_record=source_record,
        source_link=source_link,
        address_match_report=address_enrichment.report,
        feature_file_sources=krheritage_event_item_to_file_sources(
            item,
            feature=feature,
            source_record_key=source_record_key,
            raw=raw,
        ),
    )


def krheritage_event_item_to_file_sources(
    item: Any,
    *,
    feature: Feature,
    source_record_key: str,
    raw: Mapping[str, Any] | None = None,
) -> tuple[FeatureFileSource, ...]:
    raw_mapping = raw or _raw_mapping(item)
    return _krheritage_media_file_sources(
        item,
        feature=feature,
        source_record_key=source_record_key,
        dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
        source_key=_optional_text(_first(raw_mapping, "sn", "SN")),
        raw=raw,
        main_candidates=("main_image", "image_url", "mainImage", "imageUrl"),
        main_field="mainImage",
    )


def _krheritage_media_file_sources(
    item: Any,
    *,
    feature: Feature,
    source_record_key: str,
    dataset_key: str,
    source_key: str | None,
    raw: Mapping[str, Any] | None,
    main_candidates: tuple[str, ...],
    main_field: str,
) -> tuple[FeatureFileSource, ...]:
    raw_mapping = raw or _raw_mapping(item)
    sources: list[FeatureFileSource] = []
    seen_urls: set[str] = set()

    main_url = _url_or_none(_text(item, *main_candidates, raw_keys=main_candidates))
    if main_url is not None:
        _append_media_source(
            sources,
            seen_urls,
            feature=feature,
            source_record_key=source_record_key,
            dataset_key=dataset_key,
            source_url=main_url,
            file_type="image",
            role="primary",
            display_order=len(sources),
            payload={
                "source_key": source_key,
                "krheritage_media_type": "image",
                "krheritage_field": main_field,
                "license": _first(raw_mapping, "imageNuri", "image_nuri", "useScope"),
            },
        )

    for node in _iter_krheritage_media_nodes(item, raw_mapping):
        for candidate in _media_candidates(node):
            _append_media_source(
                sources,
                seen_urls,
                feature=feature,
                source_record_key=source_record_key,
                dataset_key=dataset_key,
                source_url=candidate["url"],
                file_type=candidate["file_type"],
                role=candidate["role"],
                display_order=len(sources),
                payload={
                    "source_key": source_key,
                    "krheritage_media_type": candidate["file_type"],
                    "krheritage_field": candidate["field"],
                    **candidate["payload"],
                },
            )
    return tuple(sources)


def _append_media_source(
    sources: list[FeatureFileSource],
    seen_urls: set[str],
    *,
    feature: Feature,
    source_record_key: str,
    dataset_key: str,
    source_url: str,
    file_type: str,
    role: str,
    display_order: int,
    payload: Mapping[str, Any],
) -> None:
    url = _url_or_none(source_url)
    if url is None or url in seen_urls:
        return
    seen_urls.add(url)
    sources.append(
        FeatureFileSource(
            feature_id=feature.feature_id,
            source_url=url,
            file_type=file_type,
            role=role,
            display_order=display_order,
            alt_text=feature.name,
            provider=KRHERITAGE_PROVIDER,
            dataset_key=dataset_key,
            source_record_key=source_record_key,
            payload=_without_none(payload),
        )
    )


def _iter_krheritage_media_nodes(item: Any, raw: Mapping[str, Any]) -> Iterable[Any]:
    yield raw
    for attr_or_key in (
        "media_images",
        "images",
        "image_list",
        "media_videos",
        "videos",
        "narrations",
        "audio",
        "documents",
        "files",
        "media",
    ):
        value = getattr(item, attr_or_key, None)
        if value in (None, ""):
            value = raw.get(attr_or_key)
        yield from _iter_media_values(value)


def _iter_media_values(value: Any) -> Iterable[Any]:
    if value in (None, ""):
        return
    if isinstance(value, Mapping):
        yield value
        for key in (
            "items",
            "item",
            "images",
            "videos",
            "narrations",
            "documents",
            "files",
            "media",
        ):
            if key in value:
                yield from _iter_media_values(value[key])
        return
    if isinstance(value, list | tuple | set):
        for item in value:
            yield from _iter_media_values(item)
        return
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            yield from _iter_media_values(dumped)
            return
    yield value


def _media_candidates(node: Any) -> tuple[dict[str, Any], ...]:
    mapping = _media_mapping(node)
    if not mapping:
        return ()
    candidates: list[dict[str, Any]] = []
    for file_type, role, keys in (
        (
            "image",
            "gallery",
            ("image_url", "imageUrl", "mainImage", "thumbUrl", "thumbnailUrl", "url"),
        ),
        (
            "video",
            "video",
            ("video_url", "videoUrl", "movieUrl", "vodUrl", "youtubeUrl"),
        ),
        (
            "audio",
            "audio",
            ("audio_url", "audioUrl", "narrationUrl", "soundUrl"),
        ),
        (
            "document",
            "document",
            ("document_url", "documentUrl", "docUrl", "pdfUrl", "fileUrl"),
        ),
    ):
        for key in keys:
            url = _url_or_none(mapping.get(key))
            if url is None:
                continue
            inferred_type = _infer_file_type(url, fallback=file_type)
            candidates.append(
                {
                    "url": url,
                    "file_type": inferred_type,
                    "role": role if inferred_type == file_type else inferred_type,
                    "field": key,
                    "payload": _media_payload(mapping),
                }
            )
    return tuple(candidates)


def _media_mapping(node: Any) -> Mapping[str, Any]:
    if isinstance(node, Mapping):
        return node
    if hasattr(node, "model_dump"):
        dumped = node.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    values = {}
    for key in (
        "image_url",
        "imageUrl",
        "video_url",
        "videoUrl",
        "audio_url",
        "audioUrl",
        "document_url",
        "documentUrl",
        "title",
        "description",
        "license",
        "lang",
        "transcript",
        "duration_sec",
    ):
        value = getattr(node, key, None)
        if value not in (None, ""):
            values[key] = value
    return values


def _media_payload(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return _without_none(
        {
            "title": _first(mapping, "title", "name"),
            "description": _first(mapping, "description", "alt", "caption"),
            "license": _first(mapping, "license", "imageNuri", "useScope"),
            "lang": _first(mapping, "lang", "language"),
            "transcript": _first(mapping, "transcript"),
            "duration_sec": _first(mapping, "duration_sec", "durationSec"),
        }
    )


def _infer_file_type(url: str, *, fallback: str) -> str:
    lower = url.lower().split("?", 1)[0]
    if lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
        return "image"
    if lower.endswith((".mp4", ".mov", ".m4v", ".webm")):
        return "video"
    if lower.endswith((".mp3", ".m4a", ".wav", ".ogg")):
        return "audio"
    if lower.endswith((".pdf", ".hwp", ".hwpx", ".doc", ".docx", ".ppt", ".pptx")):
        return "document"
    return fallback


def load_krheritage_heritage_result(
    session: Any,
    result: KrHeritageFeatureEtlResult,
    *,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    collected_at: datetime | None = None,
) -> FeatureDbLoadResult:
    feature_files: tuple[FeatureFile, ...] = ()
    if rustfs_store is not None:
        feature_files = upload_feature_file_sources_to_rustfs(
            rustfs_store,
            result.feature_file_sources,
            fetch_url=file_fetcher,
            collected_at=collected_at,
        )
    return load_feature_rows(
        session,
        feature_items=result.features,
        source_record_items=result.source_records,
        source_link_items=result.source_links,
        place_detail_items=result.place_details,
        area_detail_items=result.area_details,
        feature_file_items=feature_files,
    )


def load_krheritage_event_result(
    session: Any,
    result: KrHeritageEventEtlResult,
    *,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    collected_at: datetime | None = None,
) -> FeatureDbLoadResult:
    feature_files: tuple[FeatureFile, ...] = ()
    if rustfs_store is not None:
        feature_files = upload_feature_file_sources_to_rustfs(
            rustfs_store,
            result.feature_file_sources,
            fetch_url=file_fetcher,
            collected_at=collected_at,
        )
    return load_feature_rows(
        session,
        feature_items=result.features,
        source_record_items=result.source_records,
        source_link_items=result.source_links,
        event_detail_items=result.event_details,
        feature_file_items=feature_files,
    )


def collect_and_load_krheritage_heritage_features(
    session: Any,
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageFeatureDbEtlResult:
    collection = collect_krheritage_heritage_features(
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )
    return KrHeritageFeatureDbEtlResult(
        collection=collection,
        load=load_krheritage_heritage_result(
            session,
            collection,
            rustfs_store=rustfs_store,
            file_fetcher=file_fetcher,
            collected_at=collected_at,
        ),
    )


async def async_collect_and_load_krheritage_heritage_features(
    session: Any,
    items: Iterable[Any] | Any,
    *,
    collected_at: datetime | None = None,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageFeatureDbEtlResult:
    collection = await async_collect_krheritage_heritage_features(
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )
    return KrHeritageFeatureDbEtlResult(
        collection=collection,
        load=load_krheritage_heritage_result(
            session,
            collection,
            rustfs_store=rustfs_store,
            file_fetcher=file_fetcher,
            collected_at=collected_at,
        ),
    )


def collect_and_load_krheritage_events(
    session: Any,
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageFeatureDbEtlResult:
    collection = collect_krheritage_events(
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )
    return KrHeritageFeatureDbEtlResult(
        collection=collection,
        load=load_krheritage_event_result(
            session,
            collection,
            rustfs_store=rustfs_store,
            file_fetcher=file_fetcher,
            collected_at=collected_at,
        ),
    )


async def async_collect_and_load_krheritage_events(
    session: Any,
    items: Iterable[Any] | Any,
    *,
    collected_at: datetime | None = None,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KrHeritageFeatureDbEtlResult:
    collection = await async_collect_krheritage_events(
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )
    return KrHeritageFeatureDbEtlResult(
        collection=collection,
        load=load_krheritage_event_result(
            session,
            collection,
            rustfs_store=rustfs_store,
            file_fetcher=file_fetcher,
            collected_at=collected_at,
        ),
    )


def load_krheritage_heritage_features(
    resource: Any,
    run: DagsterEtlRun,
) -> KrHeritageFeatureEtlResult | KrHeritageFeatureDbEtlResult:
    resources = _resolve_krheritage_resources(resource)
    items = resources.heritage_items
    if items is None:
        if resources.client is None:
            raise ValueError("KR heritage ETL requires heritage_items or a public client")
        items = _iter_heritage_items_from_client(resources.client, run.op_config)
    if resources.session is None:
        return collect_krheritage_heritage_features(
            items,
            collected_at=run.collected_at,
            reverse_geocoder=resources.reverse_geocoder,
        )
    return collect_and_load_krheritage_heritage_features(
        resources.session,
        items,
        collected_at=run.collected_at,
        rustfs_store=resources.rustfs_store,
        file_fetcher=resources.file_fetcher,
        reverse_geocoder=resources.reverse_geocoder,
    )


def load_krheritage_events(
    resource: Any,
    run: DagsterEtlRun,
) -> KrHeritageEventEtlResult | KrHeritageFeatureDbEtlResult:
    resources = _resolve_krheritage_resources(resource)
    items = resources.event_items
    if items is None:
        if resources.client is None:
            raise ValueError("KR heritage event ETL requires event_items or a public client")
        items = _iter_event_items_from_client(resources.client, run.op_config)
    if resources.session is None:
        return collect_krheritage_events(
            items,
            collected_at=run.collected_at,
            reverse_geocoder=resources.reverse_geocoder,
        )
    return collect_and_load_krheritage_events(
        resources.session,
        items,
        collected_at=run.collected_at,
        rustfs_store=resources.rustfs_store,
        file_fetcher=resources.file_fetcher,
        reverse_geocoder=resources.reverse_geocoder,
    )


def krheritage_heritage_full_scan_identity(
    _session: Any,
    _dataset_key: str,
    execution: DagsterEtlExecution,
) -> EtlRunIdentity:
    logical_date = execution.logical_datetime_kst.date()
    return EtlRunIdentity(
        run_key=f"{logical_date:%Y%m%d}-heritage-full-scan",
        run_type=execution.run_type,
        trigger_date=logical_date,
    )


def krheritage_event_full_scan_identity(
    _session: Any,
    _dataset_key: str,
    execution: DagsterEtlExecution,
) -> EtlRunIdentity:
    logical_date = execution.logical_datetime_kst.date()
    return EtlRunIdentity(
        run_key=f"{logical_date:%Y%m%d}-event-full-scan",
        run_type=execution.run_type,
        trigger_date=logical_date,
    )


krheritage_heritage_full_scan_job_spec = EtlJobSpec(
    job_name="krheritage_heritage_full_scan",
    op_name="collect_krheritage_heritage_features",
    dataset_key=KRHERITAGE_HERITAGE_DATASET_KEY,
    description=(
        "Collect Korea Heritage Administration heritage detail models through "
        "python-krheritage-api public clients and normalize them into place/area features."
    ),
    tags=(
        f"provider:{KRHERITAGE_PROVIDER}",
        "feature:place",
        "feature:area",
        "source:heritage",
        "full_scan",
        "schedule:weekly",
        "files:rustfs",
    ),
    loader=load_krheritage_heritage_features,
    success_message="KR heritage place/area feature full scan completed.",
    failure_message="KR heritage place/area feature full scan failed.",
    identity_resolver=krheritage_heritage_full_scan_identity,
    schedule_enabled=schedule_requires_any_env(
        "KHERITAGE_API_KEY",
        "KRHERITAGE_API_KEY",
        "DATA_GO_KR_SERVICE_KEY",
    ),
)

krheritage_event_full_scan_job_spec = EtlJobSpec(
    job_name="krheritage_event_full_scan",
    op_name="collect_krheritage_events",
    dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
    description=(
        "Collect Korea Heritage Administration event models through python-krheritage-api "
        "public clients and normalize them into event features."
    ),
    tags=(
        f"provider:{KRHERITAGE_PROVIDER}",
        "feature:event",
        "source:heritage_event",
        "full_scan",
        "schedule:daily",
        "files:rustfs",
    ),
    loader=load_krheritage_events,
    success_message="KR heritage event feature full scan completed.",
    failure_message="KR heritage event feature full scan failed.",
    identity_resolver=krheritage_event_full_scan_identity,
    schedule_enabled=schedule_requires_any_env(
        "KHERITAGE_API_KEY",
        "KRHERITAGE_API_KEY",
        "DATA_GO_KR_SERVICE_KEY",
    ),
)


def _resolve_krheritage_resources(resource: Any) -> KrHeritageFeatureLoadResources:
    if isinstance(resource, KrHeritageFeatureLoadResources):
        if resource.reverse_geocoder is not None:
            return resource
        return replace(resource, reverse_geocoder=resolve_reverse_geocoder(resource))
    if isinstance(resource, Mapping):
        return KrHeritageFeatureLoadResources(
            client=resource.get("client") or resource.get("krheritage_client"),
            session=resource.get("session") or resource.get("feature_session"),
            heritage_items=resource.get("heritage_items"),
            event_items=resource.get("event_items"),
            rustfs_store=resource.get("rustfs_store") or resource.get("feature_file_store"),
            file_fetcher=resource.get("file_fetcher"),
            reverse_geocoder=resolve_reverse_geocoder(resource),
        )
    return KrHeritageFeatureLoadResources(
        client=getattr(resource, "client", None)
        or getattr(resource, "krheritage_client", None)
        or resource,
        session=getattr(resource, "session", None) or getattr(resource, "feature_session", None),
        heritage_items=getattr(resource, "heritage_items", None),
        event_items=getattr(resource, "event_items", None),
        rustfs_store=getattr(resource, "rustfs_store", None)
        or getattr(resource, "feature_file_store", None),
        file_fetcher=getattr(resource, "file_fetcher", None),
        reverse_geocoder=resolve_reverse_geocoder(resource),
    )


def _iter_heritage_items_from_client(client: Any, config: Mapping[str, object]) -> Iterable[Any]:
    for method_name in ("iter_heritage_details", "iter_all_details"):
        method = getattr(client, method_name, None)
        if callable(method):
            return method(**_client_scan_kwargs(config))
    heritage = getattr(client, "heritage", None)
    method = getattr(heritage, "iter_all_details", None)
    if callable(method):
        return method(**_client_scan_kwargs(config))
    search = getattr(client, "search", None)
    method = getattr(search, "iter_all_details", None)
    if callable(method):
        return method(**_client_scan_kwargs(config))
    sync = getattr(client, "sync", None)
    method = getattr(sync, "iter_all_details", None)
    if callable(method):
        return method(**_client_scan_kwargs(config))
    raise ValueError(
        "python-krheritage-api client must expose iter_heritage_details, "
        "iter_all_details, search.iter_all_details, or sync.iter_all_details"
    )


def _iter_event_items_from_client(client: Any, config: Mapping[str, object]) -> Iterable[Any]:
    event_service = getattr(client, "event", None)
    method = getattr(event_service, "iter_months", None)
    if callable(method):
        return method(**_client_scan_kwargs(config))
    method = getattr(event_service, "by_month", None)
    if callable(method):
        year = _optional_int(config.get("search_year")) or _now_kst().year
        month = _optional_int(config.get("search_month")) or _now_kst().month
        return method(year=year, month=month)
    method = getattr(client, "iter_events", None)
    if callable(method):
        return method(**_client_scan_kwargs(config))
    raise ValueError(
        "python-krheritage-api client must expose event.iter_months, event.by_month, "
        "or iter_events for heritage event ETL"
    )


def _client_scan_kwargs(config: Mapping[str, object]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    alias_map = {
        "ccbaKdcd": "ccba_kdcd",
        "ccbaCtcd": "ccba_ctcd",
        "ccbaAsno": "ccba_asno",
        "stCcbaAsdt": "st_ccba_asdt",
        "stCcbaAedt": "st_ccba_aedt",
        "ccbaCndt": "ccba_cndt",
        "ccbaMnm1": "ccba_mnm1",
    }
    for source_key, target_key in alias_map.items():
        value = config.get(source_key)
        if value is not None:
            kwargs[target_key] = value
    for key in (
        "page_size",
        "max_pages",
        "ccba_kdcd",
        "ccba_ctcd",
        "ccba_asno",
        "st_ccba_asdt",
        "st_ccba_aedt",
        "ccba_cndt",
        "ccba_mnm1",
        "search_year",
        "search_month",
        "months_back",
        "months_ahead",
    ):
        value = config.get(key)
        if value is not None:
            kwargs[key] = value
    return kwargs


def _heritage_name(item: Any, raw: Mapping[str, Any]) -> str | None:
    return _text(
        item,
        "name_ko",
        "name",
        "ccba_mnm1",
        "ccbaMnm1",
        raw_keys=("ccbaMnm1", "ccba_mnm1", "name_ko", "name"),
    )


def _heritage_event_title(item: Any, raw: Mapping[str, Any]) -> str | None:
    title = _text(
        item,
        "title",
        "sub_title",
        "subTitle",
        raw_keys=("title", "subTitle", "sub_title", "subTitle1"),
    )
    if title:
        subtitle2 = _optional_text(
            getattr(item, "sub_title2", None) or _first(raw, "subTitle2", "sub_title2")
        )
        return f"{title} {subtitle2}".strip() if subtitle2 else title
    return None


def _heritage_type_code(item: Any, raw: Mapping[str, Any]) -> str | None:
    value = (
        getattr(item, "heritage_type_code", None)
        or getattr(item, "formal_code", None)
        or getattr(getattr(item, "key", None), "heritage_type", None)
        or getattr(item, "ccba_kdcd", None)
        or getattr(item, "ccbaKdcd", None)
        or _first(raw, "formal_cd", "formalCode", "ccbaKdcd", "ccba_kdcd")
    )
    enum_value = getattr(value, "value", value)
    return _optional_text(enum_value)


def _heritage_domain(
    item: Any,
    raw: Mapping[str, Any],
    *,
    heritage_type_code: str | None,
) -> str:
    domain = _text(item, "heritage_domain", "domain", raw_keys=("heritage_domain", "domain"))
    if domain in {"cultural", "natural", "intangible"}:
        return domain
    if heritage_type_code in KRHERITAGE_INTANGIBLE_TYPE_CODES:
        return "intangible"
    if heritage_type_code in KRHERITAGE_NATURAL_TYPE_CODES:
        return "natural"
    return "cultural"


def _heritage_feature_kind(
    item: Any,
    raw: Mapping[str, Any],
    *,
    heritage_type_code: str | None,
) -> FeatureKind:
    kind = _text(item, "feature_kind", raw_keys=("feature_kind",))
    if kind in {FeatureKind.PLACE, FeatureKind.AREA}:
        return FeatureKind(kind)
    if _geometry_from_item(item, raw) is not None:
        return FeatureKind.AREA
    if heritage_type_code in KRHERITAGE_AREA_TYPE_CODES:
        return FeatureKind.AREA
    return FeatureKind.PLACE


def _heritage_category(
    item: Any,
    raw: Mapping[str, Any],
    *,
    heritage_domain: str,
) -> str:
    category = _text(item, "kraddr_category", raw_keys=("kraddr_category",))
    if category:
        return category
    name = (_heritage_name(item, raw) or "").lower()
    type_name = (
        _text(item, "heritage_type_name", "ccma_name", raw_keys=("ccmaName", "ccma_name"))
        or ""
    ).lower()
    text = f"{name} {type_name}"
    if any(keyword in text for keyword in ("사찰", "사지", "불국사", "석탑", "목탑")):
        return PlaceCategoryCode.TOURISM_HERITAGE_TEMPLE.value
    if any(keyword in text for keyword in ("궁", "궁궐", "왕릉", "릉", "종묘")):
        return PlaceCategoryCode.TOURISM_HERITAGE_PALACE_ROYAL_TOMB.value
    if any(keyword in text for keyword in ("민속마을", "한옥", "고택")):
        return PlaceCategoryCode.TOURISM_HERITAGE_HANOK_FOLK_VILLAGE.value
    if heritage_domain == "natural":
        return KRHERITAGE_NATURAL_CATEGORY
    if heritage_domain == "intangible":
        return KRHERITAGE_INTANGIBLE_CATEGORY
    return KRHERITAGE_CULTURAL_CATEGORY


def _heritage_marker_icon(*, kind: FeatureKind, heritage_domain: str) -> str:
    if heritage_domain == "natural":
        return "park"
    if heritage_domain == "intangible":
        return "theatre"
    if kind == FeatureKind.AREA:
        return "monument"
    return "monument"


def _heritage_marker_color(heritage_domain: str) -> str:
    if heritage_domain == "natural":
        return "#2F855A"
    if heritage_domain == "intangible":
        return "#DD6B20"
    return "#6B46C1"


def _place_kind(heritage_domain: str) -> str:
    if heritage_domain == "natural":
        return "natural_heritage"
    if heritage_domain == "intangible":
        return "intangible_heritage"
    return "heritage"


def _area_kind(
    item: Any,
    raw: Mapping[str, Any],
    *,
    heritage_type_code: str | None,
) -> str:
    value = _text(item, "area_kind", raw_keys=("area_kind", "areaKind"))
    if value:
        return value
    if heritage_type_code in {"40"}:
        return "buried_heritage_area"
    if heritage_type_code in KRHERITAGE_NATURAL_TYPE_CODES:
        return "natural_heritage_area"
    return "heritage_area"


def _boundary_source(item: Any, raw: Mapping[str, Any]) -> str | None:
    return _text(
        item,
        "boundary_source",
        raw_keys=("boundary_source", "boundarySource", "dataset_key", "datasetKey"),
    ) or (
        KRHERITAGE_GIS_3070426_DATASET_KEY
        if _geometry_from_item(item, raw) is not None
        else None
    )


def _heritage_facility_info(
    item: Any,
    raw: Mapping[str, Any],
    *,
    heritage_domain: str,
) -> dict[str, Any]:
    return _without_none(
        {
            "heritage_domain": heritage_domain,
            "heritage_type_code": _heritage_type_code(item, raw),
            "heritage_type_name": _text(
                item,
                "heritage_type_name",
                "ccma_name",
                "category",
                raw_keys=("ccmaName", "ccma_name", "category"),
            ),
            "designation_number": _text(
                item,
                "designation_number",
                "crltsno_nm",
                raw_keys=("crltsnoNm", "designation_number"),
            ),
            "quantity": _text(item, "quantity", "ccba_quan", raw_keys=("ccbaQuan", "quantity")),
            "owner": _text(item, "owner", "ccba_poss", raw_keys=("ccbaPoss", "owner")),
            "administrator": _text(
                item,
                "administrator",
                "ccba_admin",
                "manager",
                raw_keys=("ccbaAdmin", "administrator", "manager"),
            ),
            "license": _text(item, "license", raw_keys=("imageNuri", "useScope", "license")),
        }
    )


def _heritage_detail_payload(
    item: Any,
    raw: Mapping[str, Any],
    *,
    source_key: str,
    kind: FeatureKind,
    category: str,
    heritage_domain: str,
    heritage_type_code: str | None,
    address_match_report: AddressMatchReport,
) -> dict[str, Any]:
    return {
        "selected_source": {
            "provider": KRHERITAGE_PROVIDER,
            "dataset_key": KRHERITAGE_HERITAGE_DATASET_KEY,
            "source_type": KRHERITAGE_HERITAGE_SOURCE_TYPE,
            "source_entity_id": source_key,
        },
        "selected_coordinate": _selected_coordinate(item, raw),
        "category_confidence": 90 if category != KRHERITAGE_CULTURAL_CATEGORY else 80,
        "category_mapping": {
            "heritage_domain": heritage_domain,
            "heritage_type_code": heritage_type_code,
            "kraddr_category": category,
        },
        "match_level": address_match_report.match_level,
        "visible_status": "visible",
        "visible": True,
        "heritage": _without_none(
            {
                "domain": heritage_domain,
                "type_code": heritage_type_code,
                "type_name": _text(
                    item,
                    "heritage_type_name",
                    "ccma_name",
                    "category",
                    raw_keys=("ccmaName", "ccma_name", "category"),
                ),
                "designation_number": _text(
                    item,
                    "designation_number",
                    "crltsno_nm",
                    raw_keys=("crltsnoNm", "designation_number"),
                ),
                "designation_date": _iso_date(
                    _date_or_none(
                        getattr(item, "designated_date", None)
                        or getattr(item, "designated_at", None)
                        or _first(
                            raw,
                            "ccbaAsdt",
                            "designated_date",
                            "designated_at",
                            "designationDate",
                        )
                    )
                ),
                "quantity": _text(item, "quantity", "ccba_quan", raw_keys=("ccbaQuan", "quantity")),
                "owner": _text(item, "owner", "ccba_poss", raw_keys=("ccbaPoss", "owner")),
                "administrator": _text(
                    item,
                    "administrator",
                    "ccba_admin",
                    "manager",
                    raw_keys=("ccbaAdmin", "administrator", "manager"),
                ),
                "content": _text(
                    item,
                    "content",
                    "description",
                    raw_keys=("content", "description"),
                ),
                "license": _text(item, "license", raw_keys=("imageNuri", "useScope", "license")),
                "feature_kind_rule": str(kind),
            }
        ),
        "address_codes": {
            "enriched_legal_dong_code": address_match_report.legal_dong_code_after,
            "match_level": address_match_report.match_level,
            "match_confidence": address_match_report.confidence,
            "code_source": address_match_report.code_source,
            "notes": list(address_match_report.notes),
        },
    }


def _event_detail_payload(
    item: Any,
    raw: Mapping[str, Any],
    *,
    source_id: str,
) -> dict[str, Any]:
    return {
        "selected_source": {
            "provider": KRHERITAGE_PROVIDER,
            "dataset_key": KRHERITAGE_EVENT_DATASET_KEY,
            "source_type": KRHERITAGE_EVENT_SOURCE_TYPE,
            "source_entity_id": source_id,
        },
        "start_date": _first(raw, "startDate", "start_date")
        or _iso_date(_date_or_none(getattr(item, "starts_on", None))),
        "end_date": _first(raw, "endDate", "end_date")
        or _iso_date(_date_or_none(getattr(item, "ends_on", None))),
        "site_name": _text(item, "site_name", "place", raw_keys=("siteName", "site_name", "place")),
        "address": _text(item, "address", raw_keys=("address",)),
        "tel_name": _text(item, "tel_name", raw_keys=("telName", "tel_name")),
        "contents": _text(item, "contents", "content", raw_keys=("contents", "content")),
        "main_image": _text(item, "main_image", raw_keys=("mainImage", "main_image")),
    }


def _address_from_heritage_item(item: Any, raw: Mapping[str, Any]) -> Address:
    address = _text(
        item,
        "address",
        "location_text",
        "location_address",
        "ccba_lcad",
        raw_keys=("ccbaLcad", "address", "location_text", "location_address"),
    )
    region = _text(item, "region_name", "ccba_ctcd_nm", raw_keys=("ccbaCtcdNm", "region_name"))
    sigungu = _text(item, "sigungu_name", "ccsi_name", raw_keys=("ccsiName", "sigungu_name"))
    fallback = " ".join(part for part in (region, sigungu) if part)
    return Address(address=address or fallback or None)


def _address_from_event_item(item: Any, raw: Mapping[str, Any]) -> Address:
    address = _text(item, "address", raw_keys=("address",))
    return Address(address=address)


def _coordinate_from_item(item: Any, raw: Mapping[str, Any]) -> Coordinate | None:
    coordinate = getattr(item, "coordinate", None)
    if isinstance(coordinate, Coordinate):
        return coordinate
    if isinstance(coordinate, Mapping):
        return Coordinate.model_validate(coordinate)
    lon = _optional_float(
        getattr(item, "lon", None)
        or getattr(item, "lng", None)
        or getattr(item, "longitude", None)
        or _first(raw, "longitude", "lon", "lng", "mapX")
    )
    lat = _optional_float(
        getattr(item, "lat", None)
        or getattr(item, "latitude", None)
        or _first(raw, "latitude", "lat", "mapY")
    )
    if lon is None or lat is None:
        return None
    if lon == 0 or lat == 0:
        return None
    if not 124.0 <= lon <= 132.0 or not 33.0 <= lat <= 39.5:
        return None
    return Coordinate(lat=lat, lon=lon)


def _selected_coordinate(item: Any, raw: Mapping[str, Any]) -> dict[str, Any] | None:
    coordinate = _coordinate_from_item(item, raw)
    if coordinate is None:
        return None
    return {
        "source": KRHERITAGE_PROVIDER,
        "crs": "EPSG:4326",
        "lon": coordinate.longitude,
        "lat": coordinate.latitude,
    }


def _geometry_from_item(item: Any, raw: Mapping[str, Any]) -> dict[str, Any] | None:
    value = getattr(item, "geometry", None) or _first(raw, "geometry", "geojson")
    if isinstance(value, Mapping):
        return dict(value)
    return None


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


def _first(raw: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(item: Any, *attrs: str, raw_keys: tuple[str, ...]) -> str | None:
    for attr in attrs:
        value = getattr(item, attr, None)
        text = _optional_text(value)
        if text is not None:
            return text
    return _optional_text(_first(_raw_mapping(item), *raw_keys))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(getattr(value, "value", value)).strip()
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
    except (InvalidOperation, ValueError):
        return None


def _date_or_none(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = _optional_text(value)
    if text is None:
        return None
    digits = "".join(char for char in text if char.isdigit())
    if len(digits) >= 8:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    if len(digits) == 4:
        return date(int(digits), 1, 1)
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _url_or_none(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    if text.startswith(("http://", "https://")):
        return text
    return None


def _without_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
