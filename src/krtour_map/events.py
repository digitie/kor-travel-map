from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from kraddr.base import Address, PlaceCategoryCode

from krtour_map.dagster import (
    DagsterEtlExecution,
    DagsterEtlRun,
    EtlJobSpec,
    EtlRunIdentity,
    schedule_requires_any_env,
)
from krtour_map.db import FeatureDbLoadResult, load_feature_rows
from krtour_map.enums import FeatureKind, SourceRole
from krtour_map.files import (
    FeatureFileSource,
    FileFetcher,
    RustfsFileStore,
    upload_feature_file_sources_to_rustfs,
)
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import Coordinate, EventDetail, Feature, RawDataRef, SourceLink, SourceRecord

VISITKOREA_PROVIDER = "python-visitkorea-api"
VISITKOREA_FESTIVAL_DATASET_KEY = "visitkorea_festival_events"
VISITKOREA_FESTIVAL_SOURCE_TYPE = "festival"
VISITKOREA_FESTIVAL_EVENT_KIND = "festival"
VISITKOREA_FESTIVAL_CATEGORY = PlaceCategoryCode.TOURISM.value
VISITKOREA_FESTIVAL_MARKER_ICON = "theatre"
VISITKOREA_FESTIVAL_MARKER_COLOR = "#E85D04"
VISITKOREA_FESTIVAL_FULL_SCAN_INTERVAL_DAYS = 1
VISITKOREA_FESTIVAL_FULL_SCAN_START_DATE = date(2000, 1, 1)
VISITKOREA_FESTIVAL_DEFAULT_PAGE_SIZE = 1000


@dataclass(frozen=True)
class SkippedFestivalItem:
    source_entity_id: str | None
    reason: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class VisitKoreaFestivalEtlResult:
    dataset_key: str
    scanned_pages: int
    features: tuple[Feature, ...]
    event_details: tuple[EventDetail, ...]
    source_records: tuple[SourceRecord, ...]
    source_links: tuple[SourceLink, ...]
    feature_file_sources: tuple[FeatureFileSource, ...] = ()
    skipped_items: tuple[SkippedFestivalItem, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.features)


@dataclass(frozen=True)
class VisitKoreaFestivalDbEtlResult:
    collection: VisitKoreaFestivalEtlResult
    load: FeatureDbLoadResult

    @property
    def item_count(self) -> int:
        return self.collection.item_count


@dataclass(frozen=True)
class VisitKoreaFestivalLoadResources:
    client: Any
    session: Any
    rustfs_store: RustfsFileStore | None = None
    file_fetcher: FileFetcher | None = None


def collect_visitkorea_festival_events(
    client: Any,
    *,
    event_start_date: str | date | datetime,
    event_end_date: str | date | datetime | None = None,
    area_code: str | None = None,
    sigungu_code: str | None = None,
    page_size: int = VISITKOREA_FESTIVAL_DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
) -> VisitKoreaFestivalEtlResult:
    """Collect every festival page through the public `python-visitkorea-api` client.

    This library intentionally does not wrap the provider client. It calls the stable
    public `search_festival` endpoint through the provider's own `iter_pages` helper,
    then converts typed provider items into feature/event/source contracts.
    """

    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")

    features: list[Feature] = []
    event_details: list[EventDetail] = []
    source_records: list[SourceRecord] = []
    source_links: list[SourceLink] = []
    feature_file_sources: list[FeatureFileSource] = []
    skipped_items: list[SkippedFestivalItem] = []
    scanned_pages = 0

    pages = client.iter_pages(
        client.search_festival,
        event_start_date,
        event_end_date=event_end_date,
        area_code=area_code,
        sigungu_code=sigungu_code,
        page_no=1,
        num_of_rows=page_size,
        max_pages=max_pages,
    )

    for page in pages:
        scanned_pages += 1
        page_collected_at = collected_at or getattr(page, "collected_at", None)
        for item in page.items:
            bundle = visitkorea_festival_item_to_feature_bundle(
                item,
                collected_at=page_collected_at,
            )
            if isinstance(bundle, SkippedFestivalItem):
                skipped_items.append(bundle)
                continue
            feature, event_detail, source_record, source_link = bundle
            features.append(feature)
            event_details.append(event_detail)
            source_records.append(source_record)
            source_links.append(source_link)
            feature_file_sources.extend(
                visitkorea_festival_item_to_file_sources(
                    item,
                    feature=feature,
                    source_record_key=source_record.key(),
                    raw=_raw_mapping(item),
                )
            )

    return VisitKoreaFestivalEtlResult(
        dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
        scanned_pages=scanned_pages,
        features=tuple(features),
        event_details=tuple(event_details),
        source_records=tuple(source_records),
        source_links=tuple(source_links),
        feature_file_sources=tuple(feature_file_sources),
        skipped_items=tuple(skipped_items),
    )


def load_visitkorea_festival_result(
    session: Any,
    result: VisitKoreaFestivalEtlResult,
    *,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    collected_at: datetime | None = None,
) -> FeatureDbLoadResult:
    """Load a collected VisitKorea festival result into the feature DB session."""

    feature_files = ()
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


def collect_and_load_visitkorea_festival_events(
    session: Any,
    client: Any,
    *,
    event_start_date: str | date | datetime,
    event_end_date: str | date | datetime | None = None,
    area_code: str | None = None,
    sigungu_code: str | None = None,
    page_size: int = VISITKOREA_FESTIVAL_DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
) -> VisitKoreaFestivalDbEtlResult:
    """Collect every VisitKorea festival page and stage the normalized rows in DB."""

    collection = collect_visitkorea_festival_events(
        client,
        event_start_date=event_start_date,
        event_end_date=event_end_date,
        area_code=area_code,
        sigungu_code=sigungu_code,
        page_size=page_size,
        max_pages=max_pages,
        collected_at=collected_at,
    )
    return VisitKoreaFestivalDbEtlResult(
        collection=collection,
        load=load_visitkorea_festival_result(
            session,
            collection,
            rustfs_store=rustfs_store,
            file_fetcher=file_fetcher,
            collected_at=collected_at,
        ),
    )


def visitkorea_festival_item_to_feature_bundle(
    item: Any,
    *,
    collected_at: datetime | None = None,
) -> tuple[Feature, EventDetail, SourceRecord, SourceLink] | SkippedFestivalItem:
    raw = _raw_mapping(item)
    content_id = _text(item, "content_id", raw_keys=("contentid", "contentId", "content_id"))
    title = _text(item, "title", raw_keys=("title",))

    if not content_id:
        return SkippedFestivalItem(None, "missing content_id", raw)
    if not title:
        return SkippedFestivalItem(content_id, "missing title", raw)

    coordinate = _coordinate_from_item(item)
    address = _address_from_item(item)
    raw_payload_hash = make_payload_hash(raw, length=32)
    content_type_id = _text(
        item,
        "content_type_id",
        raw_keys=("contenttypeid", "contentTypeId", "content_type_id"),
    )
    starts_on = _tour_date(_first(raw, "eventstartdate", "eventStartDate", "event_start_date"))
    ends_on = _tour_date(_first(raw, "eventenddate", "eventEndDate", "event_end_date"))
    collected = collected_at

    feature_id = make_feature_id(
        provider=VISITKOREA_PROVIDER,
        source_type=VISITKOREA_FESTIVAL_SOURCE_TYPE,
        source_natural_key=content_id,
        kind=FeatureKind.EVENT,
        category=VISITKOREA_FESTIVAL_CATEGORY,
        legal_dong_code=address.legal_dong_code,
    )
    source_record = SourceRecord(
        provider=VISITKOREA_PROVIDER,
        dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
        source_entity_type=VISITKOREA_FESTIVAL_SOURCE_TYPE,
        source_entity_id=content_id,
        raw_payload_hash=raw_payload_hash,
        raw_name=title,
        raw_address=address.display_address,
        raw_longitude=Decimal(str(coordinate.longitude)) if coordinate is not None else None,
        raw_latitude=Decimal(str(coordinate.latitude)) if coordinate is not None else None,
        raw_data=raw,
        fetched_at=collected,
        imported_at=collected or _now_kst(),
    )
    source_record_key = source_record.key()
    detail_payload = _event_detail_payload(item, raw)
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name=title,
        coord=coordinate,
        address=address,
        category=VISITKOREA_FESTIVAL_CATEGORY,
        marker_icon=VISITKOREA_FESTIVAL_MARKER_ICON,
        marker_color=VISITKOREA_FESTIVAL_MARKER_COLOR,
        detail=detail_payload,
        raw_refs=[
            RawDataRef(
                provider=VISITKOREA_PROVIDER,
                dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
                source_entity_id=content_id,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    event_detail = EventDetail(
        feature_id=feature_id,
        event_kind=VISITKOREA_FESTIVAL_EVENT_KIND,
        starts_on=starts_on,
        ends_on=ends_on,
        venue_name=address.display_address,
        tel=_text(item, "tel", raw_keys=("tel",)),
        content_id=content_id,
        content_type_id=content_type_id,
        area_code=_text(item, "area_code", raw_keys=("areacode", "areaCode", "area_code")),
        sigungu_code=_text(
            item,
            "sigungu_code",
            raw_keys=("sigungucode", "sigunguCode", "sigungu_code"),
        ),
        payload=detail_payload,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="visitkorea_content_id",
        confidence=100,
        is_primary_source=True,
    )
    return feature, event_detail, source_record, source_link


def visitkorea_festival_item_to_file_sources(
    item: Any,
    *,
    feature: Feature,
    source_record_key: str,
    raw: Mapping[str, Any] | None = None,
) -> tuple[FeatureFileSource, ...]:
    """Return VisitKorea festival image sources that should be mirrored to RustFS."""

    raw_mapping = raw or _raw_mapping(item)
    content_id = _text(item, "content_id", raw_keys=("contentid", "contentId", "content_id"))
    fields = (
        (
            "first_image",
            ("firstimage", "firstImage", "first_image"),
            "primary",
            0,
        ),
        (
            "first_image2",
            ("firstimage2", "firstImage2", "first_image2"),
            "thumbnail",
            1,
        ),
    )
    sources: list[FeatureFileSource] = []
    seen_urls: set[str] = set()
    for attr, raw_keys, role, display_order in fields:
        source_url = _text(item, attr, raw_keys=raw_keys)
        if source_url is None or source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        sources.append(
            FeatureFileSource(
                feature_id=feature.feature_id,
                source_url=source_url,
                file_type="image",
                role=role,
                display_order=display_order,
                alt_text=feature.name,
                provider=VISITKOREA_PROVIDER,
                dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
                source_record_key=source_record_key,
                payload={
                    "content_id": content_id,
                    "visitkorea_field": attr,
                    "raw_value": _first(raw_mapping, *raw_keys),
                },
            )
        )
    return tuple(sources)


def load_visitkorea_festival_events(
    resource: Any,
    run: DagsterEtlRun,
) -> VisitKoreaFestivalEtlResult | VisitKoreaFestivalDbEtlResult:
    """Dagster-side loader body for TripMate to call from its execution graph."""

    config = run.op_config
    client, session, rustfs_store, file_fetcher = _resolve_visitkorea_resources(resource)
    kwargs = {
        "event_start_date": _date_config(config, "event_start_date")
        or VISITKOREA_FESTIVAL_FULL_SCAN_START_DATE,
        "event_end_date": _date_config(config, "event_end_date"),
        "area_code": _optional_str(config.get("area_code")),
        "sigungu_code": _optional_str(config.get("sigungu_code")),
        "page_size": _optional_int(config.get("page_size"))
        or VISITKOREA_FESTIVAL_DEFAULT_PAGE_SIZE,
        "max_pages": _optional_int(config.get("max_pages")),
        "collected_at": run.collected_at,
    }
    if session is not None:
        return collect_and_load_visitkorea_festival_events(
            session,
            client,
            **kwargs,
            rustfs_store=rustfs_store,
            file_fetcher=file_fetcher,
        )
    return collect_visitkorea_festival_events(
        client,
        **kwargs,
    )


def visitkorea_festival_full_scan_identity(
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


visitkorea_festival_full_scan_job_spec = EtlJobSpec(
    job_name="visitkorea_festival_full_scan",
    op_name="collect_visitkorea_festival_events",
    dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
    description=(
        "Collect all VisitKorea festival pages once per day and normalize them "
        "into event features."
    ),
    tags=(
        f"provider:{VISITKOREA_PROVIDER}",
        "feature:event",
        "source:festival",
        "full_scan",
        "schedule:daily",
        "pagination:all-pages",
    ),
    loader=load_visitkorea_festival_events,
    success_message="VisitKorea festival full scan completed.",
    failure_message="VisitKorea festival full scan failed.",
    identity_resolver=visitkorea_festival_full_scan_identity,
    schedule_enabled=schedule_requires_any_env(
        "KTO_DATA_GO_KR_SERVICE_KEY",
        "DATA_GO_KR_SERVICE_KEY",
        "KTO_SERVICE_KEY",
        "KRTOURAPI_SERVICE_KEY",
        "TOURAPI_SERVICE_KEY",
    ),
)


def _coordinate_from_item(item: Any) -> Coordinate | None:
    coordinate = getattr(item, "coordinate", None)
    if coordinate is not None:
        return coordinate

    map_x = _optional_float(getattr(item, "map_x", None))
    map_y = _optional_float(getattr(item, "map_y", None))
    if map_x is None or map_y is None:
        raw = _raw_mapping(item)
        map_x = _optional_float(_first(raw, "mapx", "mapX", "map_x"))
        map_y = _optional_float(_first(raw, "mapy", "mapY", "map_y"))
    if map_x is None or map_y is None:
        return None
    return Coordinate(lat=map_y, lon=map_x)


def _address_from_item(item: Any) -> Address:
    addr1 = _text(item, "addr1", raw_keys=("addr1",))
    addr2 = _text(item, "addr2", raw_keys=("addr2",))
    zipcode = _text(item, "zipcode", raw_keys=("zipcode", "zipCode"))
    address = " ".join(part for part in (addr1, addr2) if part)
    return Address(address=address or None, postal_code=zipcode)


def _event_detail_payload(item: Any, raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_start_date": _first(raw, "eventstartdate", "eventStartDate", "event_start_date"),
        "event_end_date": _first(raw, "eventenddate", "eventEndDate", "event_end_date"),
        "cat1": _text(item, "cat1", raw_keys=("cat1",)),
        "cat2": _text(item, "cat2", raw_keys=("cat2",)),
        "cat3": _text(item, "cat3", raw_keys=("cat3",)),
        "l_dong_regn_cd": _text(
            item,
            "l_dong_regn_cd",
            raw_keys=("ldongregncd", "lDongRegnCd", "l_dong_regn_cd"),
        ),
        "l_dong_signgu_cd": _text(
            item,
            "l_dong_signgu_cd",
            raw_keys=("ldongsigngucd", "lDongSignguCd", "l_dong_signgu_cd"),
        ),
        "first_image": _text(
            item,
            "first_image",
            raw_keys=("firstimage", "firstImage", "first_image"),
        ),
        "first_image2": _text(
            item,
            "first_image2",
            raw_keys=("firstimage2", "firstImage2", "first_image2"),
        ),
    }


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


def _tour_date(value: Any) -> date | None:
    text = _optional_str(value)
    if text is None:
        return None
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text)


def _date_config(config: Mapping[str, object], key: str) -> str | date | datetime | None:
    value = config.get(key)
    if value is None:
        return None
    if isinstance(value, str | date | datetime):
        return value
    raise TypeError(f"{key} must be a date, datetime, or ISO date string")


def _resolve_visitkorea_resources(
    resource: Any,
) -> tuple[Any, Any | None, RustfsFileStore | None, FileFetcher | None]:
    if isinstance(resource, Mapping):
        client = resource.get("client") or resource.get("visitkorea_client")
        session = resource.get("session") or resource.get("feature_session")
        rustfs_store = resource.get("rustfs_store") or resource.get("feature_file_store")
        file_fetcher = resource.get("file_fetcher")
    else:
        client = getattr(resource, "client", None) or getattr(resource, "visitkorea_client", None)
        session = getattr(resource, "session", None) or getattr(resource, "feature_session", None)
        rustfs_store = getattr(resource, "rustfs_store", None) or getattr(
            resource,
            "feature_file_store",
            None,
        )
        file_fetcher = getattr(resource, "file_fetcher", None)
        if client is None:
            client = resource
    if client is None:
        raise ValueError("VisitKorea ETL resource must provide a public provider client")
    return client, session, rustfs_store, file_fetcher


def _first(raw: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(item: Any, attr: str, *, raw_keys: tuple[str, ...]) -> str | None:
    value = getattr(item, attr, None)
    if value in (None, ""):
        value = _first(_raw_mapping(item), *raw_keys)
    return _optional_str(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
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


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
