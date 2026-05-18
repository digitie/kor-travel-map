from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from kraddr.base import PlaceCategoryCode

from krtour_map.dagster import (
    DagsterEtlExecution,
    DagsterEtlRun,
    EtlJobSpec,
    EtlRunIdentity,
    schedule_requires_any_env,
)
from krtour_map.enums import FeatureKind, SourceRole
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import (
    Address,
    Coordinate,
    EventDetail,
    Feature,
    FeatureUrls,
    RawDataRef,
    SourceLink,
    SourceRecord,
    kst_now,
)

VISITKOREA_PROVIDER = "python-visitkorea-api"
VISITKOREA_FESTIVAL_DATASET_KEY = "visitkorea_festival_events"
VISITKOREA_FESTIVAL_SOURCE_TYPE = "festival"
VISITKOREA_FESTIVAL_EVENT_KIND = "festival"
VISITKOREA_FESTIVAL_CATEGORY = PlaceCategoryCode.TOURISM.value
VISITKOREA_FESTIVAL_MARKER_ICON = "theatre"
VISITKOREA_FESTIVAL_MARKER_COLOR = "#E85D04"
VISITKOREA_FESTIVAL_FULL_SCAN_INTERVAL_DAYS = 1
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
    skipped_items: tuple[SkippedFestivalItem, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.features) + len(self.skipped_items)


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
    """Collect all VisitKorea festival pages and normalize them as event features."""

    if page_size < 1:
        raise ValueError("page_size must be positive")
    collected = collected_at or kst_now()
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

    scanned_pages = 0
    features: list[Feature] = []
    event_details: list[EventDetail] = []
    source_records: list[SourceRecord] = []
    source_links: list[SourceLink] = []
    skipped: list[SkippedFestivalItem] = []

    for page in pages:
        scanned_pages += 1
        page_collected_at = getattr(page, "collected_at", None) or collected
        for item in page.items:
            bundle = visitkorea_festival_item_to_feature_bundle(
                item,
                collected_at=page_collected_at,
            )
            if isinstance(bundle, SkippedFestivalItem):
                skipped.append(bundle)
                continue
            feature, event_detail, source_record, source_link = bundle
            features.append(feature)
            event_details.append(event_detail)
            source_records.append(source_record)
            source_links.append(source_link)

    return VisitKoreaFestivalEtlResult(
        dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
        scanned_pages=scanned_pages,
        features=tuple(features),
        event_details=tuple(event_details),
        source_records=tuple(source_records),
        source_links=tuple(source_links),
        skipped_items=tuple(skipped),
    )


def visitkorea_festival_item_to_feature_bundle(
    item: Any,
    *,
    collected_at: datetime | None = None,
) -> tuple[Feature, EventDetail, SourceRecord, SourceLink] | SkippedFestivalItem:
    """Normalize one `python-visitkorea-api` TourItem into feature DB DTOs."""

    raw = dict(getattr(item, "raw", {}) or {})
    source_entity_id = _text(getattr(item, "content_id", None)) or _text(
        _first(raw, "contentid", "contentId")
    )
    title = _text(getattr(item, "title", None)) or _text(_first(raw, "title"))
    if not source_entity_id:
        return SkippedFestivalItem(None, "missing_content_id", raw)
    if not title:
        return SkippedFestivalItem(source_entity_id, "missing_title", raw)

    collected = collected_at or kst_now()
    payload_hash = make_payload_hash(raw)
    coord = _coordinate_from_item(item)
    address = _address_from_item(item)
    legal_dong_code = address.legal_dong_code
    feature_id = make_feature_id(
        provider=VISITKOREA_PROVIDER,
        source_type=VISITKOREA_FESTIVAL_SOURCE_TYPE,
        source_natural_key=source_entity_id,
        kind=FeatureKind.EVENT,
        category=VISITKOREA_FESTIVAL_CATEGORY,
        legal_dong_code=legal_dong_code,
    )
    starts_on = _tour_date(
        _first(raw, "eventstartdate", "eventStartDate", "event_start_date")
    )
    ends_on = _tour_date(_first(raw, "eventenddate", "eventEndDate", "event_end_date"))
    detail_payload = _event_detail_payload(item, raw)
    raw_ref = RawDataRef(
        provider=VISITKOREA_PROVIDER,
        dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
        source_entity_id=source_entity_id,
        source_role=SourceRole.PRIMARY,
        fetched_at=collected,
        payload_hash=payload_hash,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name=title,
        coord=coord,
        address=address,
        category=VISITKOREA_FESTIVAL_CATEGORY,
        urls=FeatureUrls(),
        marker_icon=VISITKOREA_FESTIVAL_MARKER_ICON,
        marker_color=VISITKOREA_FESTIVAL_MARKER_COLOR,
        detail=detail_payload,
        raw_refs=[raw_ref],
        created_at=collected,
        updated_at=collected,
    )
    event_detail = EventDetail(
        feature_id=feature_id,
        event_kind=VISITKOREA_FESTIVAL_EVENT_KIND,
        starts_on=starts_on,
        ends_on=ends_on,
        venue_name=address.display_address,
        tel=_text(getattr(item, "tel", None)),
        content_id=source_entity_id,
        content_type_id=_text(getattr(item, "content_type_id", None)),
        area_code=_text(getattr(item, "area_code", None)),
        sigungu_code=_text(getattr(item, "sigungu_code", None)),
        payload=detail_payload,
    )
    source_record = SourceRecord(
        provider=VISITKOREA_PROVIDER,
        dataset_key=VISITKOREA_FESTIVAL_DATASET_KEY,
        source_entity_type=VISITKOREA_FESTIVAL_SOURCE_TYPE,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_name=title,
        raw_address=address.display_address,
        raw_longitude=Decimal(str(coord.lon)) if coord is not None else None,
        raw_latitude=Decimal(str(coord.lat)) if coord is not None else None,
        raw_data=raw,
        fetched_at=collected,
        imported_at=collected,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record.key(),
        source_role=SourceRole.PRIMARY,
        match_method="visitkorea_content_id",
        confidence=100,
        is_primary_source=True,
        created_at=collected,
    )
    return feature, event_detail, source_record, source_link


def load_visitkorea_festival_events(client: Any, run: DagsterEtlRun) -> VisitKoreaFestivalEtlResult:
    """Dagster loader body for a daily full scan.

    TripMate owns the actual Dagster op/job/schedule. It should pass a configured
    `python-visitkorea-api` client as the first argument.
    """

    config = run.op_config
    return collect_visitkorea_festival_events(
        client,
        event_start_date=config.get("event_start_date") or run.trigger_date,
        event_end_date=config.get("event_end_date"),
        area_code=_optional_str(config.get("area_code")),
        sigungu_code=_optional_str(config.get("sigungu_code")),
        page_size=int(config.get("page_size", VISITKOREA_FESTIVAL_DEFAULT_PAGE_SIZE)),
        max_pages=_optional_int(config.get("max_pages")),
        collected_at=run.collected_at,
    )


def visitkorea_festival_full_scan_identity(
    _client: Any,
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
    description="Daily full scan of VisitKorea searchFestival2 into event features.",
    tags=(
        "provider:python-visitkorea-api",
        "feature:event",
        "full_scan",
        "schedule:daily",
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
    map_x = getattr(item, "map_x", None)
    map_y = getattr(item, "map_y", None)
    if map_x is None or map_y is None:
        return None
    return Coordinate(lat=map_y, lon=map_x)


def _address_from_item(item: Any) -> Address:
    addr1 = _text(getattr(item, "addr1", None))
    addr2 = _text(getattr(item, "addr2", None))
    address_text = " ".join(part for part in (addr1, addr2) if part)
    return Address(
        address=address_text or None,
        postal_code=_text(getattr(item, "zipcode", None)),
    )


def _event_detail_payload(item: Any, raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider": VISITKOREA_PROVIDER,
        "dataset_key": VISITKOREA_FESTIVAL_DATASET_KEY,
        "content_id": _text(getattr(item, "content_id", None)),
        "content_type_id": _text(getattr(item, "content_type_id", None)),
        "area_code": _text(getattr(item, "area_code", None)),
        "sigungu_code": _text(getattr(item, "sigungu_code", None)),
        "cat1": _text(getattr(item, "cat1", None)),
        "cat2": _text(getattr(item, "cat2", None)),
        "cat3": _text(getattr(item, "cat3", None)),
        "first_image": _text(getattr(item, "first_image", None)),
        "first_image2": _text(getattr(item, "first_image2", None)),
        "tel": _text(getattr(item, "tel", None)),
        "event_start_date": _text(_first(raw, "eventstartdate", "eventStartDate")),
        "event_end_date": _text(_first(raw, "eventenddate", "eventEndDate")),
    }


def _tour_date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text)


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_str(value: Any) -> str | None:
    return _text(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
