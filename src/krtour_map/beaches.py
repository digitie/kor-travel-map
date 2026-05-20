from __future__ import annotations

from collections.abc import Mapping
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
from krtour_map.dagster import (
    DagsterEtlExecution,
    DagsterEtlRun,
    EtlJobSpec,
    EtlRunIdentity,
    schedule_requires_any_env,
)
from krtour_map.db import FeatureDbLoadResult, load_feature_rows
from krtour_map.enums import FeatureKind, SourceRole
from krtour_map.etl import page_collected_at, page_items
from krtour_map.files import (
    FeatureFileSource,
    FileFetcher,
    RustfsFileStore,
    upload_feature_file_sources_to_rustfs,
)
from krtour_map.ids import make_feature_id, make_payload_hash
from krtour_map.models import (
    Coordinate,
    Feature,
    FeatureFile,
    FeatureUrls,
    PlaceDetail,
    RawDataRef,
    SourceLink,
    SourceRecord,
)

KHOA_PROVIDER = "python-khoa-api"
KHOA_OCEANS_BEACH_INFO_DATASET_KEY = "khoa_oceans_beach_info"
KHOA_OCEANS_BEACH_INFO_SOURCE_TYPE = "beach"
KHOA_OCEANS_BEACH_INFO_CATEGORY = PlaceCategoryCode.TOURISM_NATURE_BEACH.value
KHOA_OCEANS_BEACH_INFO_MARKER_ICON = "beach"
KHOA_OCEANS_BEACH_INFO_MARKER_COLOR = "#0077B6"
KHOA_OCEANS_BEACH_INFO_DEFAULT_PAGE_SIZE = 100
KHOA_OCEANS_BEACH_INFO_FULL_SCAN_INTERVAL_DAYS = 1


@dataclass(frozen=True)
class SkippedBeachItem:
    source_entity_id: str | None
    reason: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class KhoaBeachInfoFeatureBundle:
    feature: Feature
    place_detail: PlaceDetail
    source_record: SourceRecord
    source_link: SourceLink
    address_match_report: AddressMatchReport
    feature_file_sources: tuple[FeatureFileSource, ...] = ()


@dataclass(frozen=True)
class KhoaBeachInfoEtlResult:
    dataset_key: str
    scanned_pages: int
    features: tuple[Feature, ...]
    place_details: tuple[PlaceDetail, ...]
    source_records: tuple[SourceRecord, ...]
    source_links: tuple[SourceLink, ...]
    feature_file_sources: tuple[FeatureFileSource, ...] = ()
    address_match_reports: tuple[AddressMatchReport, ...] = ()
    skipped_items: tuple[SkippedBeachItem, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.features)


@dataclass(frozen=True)
class KhoaBeachInfoDbEtlResult:
    collection: KhoaBeachInfoEtlResult
    load: FeatureDbLoadResult

    @property
    def item_count(self) -> int:
        return self.collection.item_count


@dataclass(frozen=True)
class KhoaBeachInfoLoadResources:
    client: Any
    session: Any
    rustfs_store: RustfsFileStore | None = None
    file_fetcher: FileFetcher | None = None
    reverse_geocoder: ReverseGeocoder | None = None


def collect_khoa_oceans_beach_info(
    client: Any,
    *,
    sido_names: tuple[str, ...] | list[str] | None = None,
    page_size: int = KHOA_OCEANS_BEACH_INFO_DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KhoaBeachInfoEtlResult:
    """`python-khoa-api` public beach-info paginator 결과를 feature 행으로 변환합니다."""

    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")

    iter_pages = getattr(client, "iter_oceans_beach_info_pages", None)
    if not callable(iter_pages):
        raise ValueError(
            "KHOA beach ETL requires python-khoa-api with iter_oceans_beach_info_pages"
        )

    features: list[Feature] = []
    place_details: list[PlaceDetail] = []
    source_records: list[SourceRecord] = []
    source_links: list[SourceLink] = []
    feature_file_sources: list[FeatureFileSource] = []
    address_match_reports: list[AddressMatchReport] = []
    skipped_items: list[SkippedBeachItem] = []
    scanned_pages = 0

    page_kwargs: dict[str, Any] = {
        "num_of_rows": page_size,
        "max_pages": max_pages,
    }
    if sido_names is not None:
        page_kwargs["sido_names"] = sido_names

    for page in iter_pages(**page_kwargs):
        scanned_pages += 1
        page_collected_at = collected_at or _page_collected_at(page)
        for item in page.items:
            bundle = khoa_beach_info_item_to_feature_bundle(
                item,
                collected_at=page_collected_at,
                reverse_geocoder=reverse_geocoder,
            )
            if isinstance(bundle, SkippedBeachItem):
                skipped_items.append(bundle)
                continue
            features.append(bundle.feature)
            place_details.append(bundle.place_detail)
            source_records.append(bundle.source_record)
            source_links.append(bundle.source_link)
            feature_file_sources.extend(bundle.feature_file_sources)
            address_match_reports.append(bundle.address_match_report)

    return KhoaBeachInfoEtlResult(
        dataset_key=KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
        scanned_pages=scanned_pages,
        features=tuple(features),
        place_details=tuple(place_details),
        source_records=tuple(source_records),
        source_links=tuple(source_links),
        feature_file_sources=tuple(feature_file_sources),
        address_match_reports=tuple(address_match_reports),
        skipped_items=tuple(skipped_items),
    )


async def async_collect_khoa_oceans_beach_info(
    client: Any,
    *,
    sido_names: tuple[str, ...] | list[str] | None = None,
    page_size: int = KHOA_OCEANS_BEACH_INFO_DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KhoaBeachInfoEtlResult:
    """Async KHOA beach-info collection through the provider public client."""

    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")

    iter_pages = getattr(client, "aiter_oceans_beach_info_pages", None) or getattr(
        client,
        "iter_oceans_beach_info_pages",
        None,
    )
    if not callable(iter_pages):
        raise ValueError(
            "KHOA beach ETL requires python-khoa-api with aiter_oceans_beach_info_pages"
        )

    page_kwargs: dict[str, Any] = {
        "num_of_rows": page_size,
        "max_pages": max_pages,
    }
    if sido_names is not None:
        page_kwargs["sido_names"] = sido_names

    pages = iter_pages(**page_kwargs)
    features: list[Feature] = []
    place_details: list[PlaceDetail] = []
    source_records: list[SourceRecord] = []
    source_links: list[SourceLink] = []
    feature_file_sources: list[FeatureFileSource] = []
    address_match_reports: list[AddressMatchReport] = []
    skipped_items: list[SkippedBeachItem] = []
    scanned_pages = 0

    async for page in _aiter_pages(pages):
        scanned_pages += 1
        page_collected = collected_at or page_collected_at(page)
        for item in page_items(page):
            bundle = khoa_beach_info_item_to_feature_bundle(
                item,
                collected_at=page_collected,
                reverse_geocoder=reverse_geocoder,
            )
            if isinstance(bundle, SkippedBeachItem):
                skipped_items.append(bundle)
                continue
            features.append(bundle.feature)
            place_details.append(bundle.place_detail)
            source_records.append(bundle.source_record)
            source_links.append(bundle.source_link)
            feature_file_sources.extend(bundle.feature_file_sources)
            address_match_reports.append(bundle.address_match_report)

    return KhoaBeachInfoEtlResult(
        dataset_key=KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
        scanned_pages=scanned_pages,
        features=tuple(features),
        place_details=tuple(place_details),
        source_records=tuple(source_records),
        source_links=tuple(source_links),
        feature_file_sources=tuple(feature_file_sources),
        address_match_reports=tuple(address_match_reports),
        skipped_items=tuple(skipped_items),
    )


def load_khoa_oceans_beach_info_result(
    session: Any,
    result: KhoaBeachInfoEtlResult,
    *,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    collected_at: datetime | None = None,
) -> FeatureDbLoadResult:
    """수집된 KHOA 해수욕장정보 feature 행을 열린 feature DB session에 적재합니다."""

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
        feature_file_items=feature_files,
    )


def collect_and_load_khoa_oceans_beach_info(
    session: Any,
    client: Any,
    *,
    sido_names: tuple[str, ...] | list[str] | None = None,
    page_size: int = KHOA_OCEANS_BEACH_INFO_DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KhoaBeachInfoDbEtlResult:
    """KHOA 해수욕장정보 전체 페이지를 수집하고 feature DB에 staged write합니다."""

    collection = collect_khoa_oceans_beach_info(
        client,
        sido_names=sido_names,
        page_size=page_size,
        max_pages=max_pages,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )
    return KhoaBeachInfoDbEtlResult(
        collection=collection,
        load=load_khoa_oceans_beach_info_result(
            session,
            collection,
            rustfs_store=rustfs_store,
            file_fetcher=file_fetcher,
            collected_at=collected_at,
        ),
    )


async def async_collect_and_load_khoa_oceans_beach_info(
    session: Any,
    client: Any,
    *,
    sido_names: tuple[str, ...] | list[str] | None = None,
    page_size: int = KHOA_OCEANS_BEACH_INFO_DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    collected_at: datetime | None = None,
    rustfs_store: RustfsFileStore | None = None,
    file_fetcher: FileFetcher | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KhoaBeachInfoDbEtlResult:
    """Async collect KHOA beach pages and stage normalized rows in DB."""

    collection = await async_collect_khoa_oceans_beach_info(
        client,
        sido_names=sido_names,
        page_size=page_size,
        max_pages=max_pages,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )
    return KhoaBeachInfoDbEtlResult(
        collection=collection,
        load=load_khoa_oceans_beach_info_result(
            session,
            collection,
            rustfs_store=rustfs_store,
            file_fetcher=file_fetcher,
            collected_at=collected_at,
        ),
    )


def khoa_beach_info_item_to_feature_bundle(
    item: Any,
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> KhoaBeachInfoFeatureBundle | SkippedBeachItem:
    """KHOA `OceanBeachInfo` DTO 하나를 place feature bundle로 변환합니다."""

    raw = _raw_mapping(item)
    source_key = _source_key(item, raw)
    name = _text(item, "name", raw_keys=("staNm", "name"))
    if source_key is None:
        return SkippedBeachItem(None, "missing source_key", raw)
    if name is None:
        return SkippedBeachItem(source_key, "missing name", raw)

    coordinate = _coordinate_from_item(item)
    address_enrichment = enrich_address_from_coordinate(
        address=_address_from_item(item),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
        source_entity_id=source_key,
    )
    address = address_enrichment.address
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=KHOA_PROVIDER,
        source_type=KHOA_OCEANS_BEACH_INFO_SOURCE_TYPE,
        source_natural_key=source_key,
        kind=FeatureKind.PLACE,
        category=KHOA_OCEANS_BEACH_INFO_CATEGORY,
        legal_dong_code=address.legal_dong_code,
    )
    source_record = SourceRecord(
        provider=KHOA_PROVIDER,
        dataset_key=KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
        source_entity_type=KHOA_OCEANS_BEACH_INFO_SOURCE_TYPE,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        raw_name=name,
        raw_address=address.display_address,
        raw_longitude=Decimal(str(coordinate.longitude)) if coordinate is not None else None,
        raw_latitude=Decimal(str(coordinate.latitude)) if coordinate is not None else None,
        raw_data=dict(raw),
        fetched_at=collected_at,
        imported_at=collected_at or _now_kst(),
    )
    source_record_key = source_record.key()
    detail_payload = _beach_detail_payload(item, raw)
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coordinate,
        address=address,
        category=KHOA_OCEANS_BEACH_INFO_CATEGORY,
        urls=_feature_urls(item),
        marker_icon=KHOA_OCEANS_BEACH_INFO_MARKER_ICON,
        marker_color=KHOA_OCEANS_BEACH_INFO_MARKER_COLOR,
        detail=detail_payload,
        raw_refs=[
            RawDataRef(
                provider=KHOA_PROVIDER,
                dataset_key=KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
                source_entity_id=source_key,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected_at,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    place_detail = PlaceDetail(
        feature_id=feature_id,
        place_kind=KHOA_OCEANS_BEACH_INFO_SOURCE_TYPE,
        phones=[phone]
        if (phone := _text(item, "emergency_contact", raw_keys=("linkTel",)))
        else [],
        facility_info=_facility_info(item, raw),
        payload=detail_payload,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="khoa_oceans_beach_source_key",
        confidence=100,
        is_primary_source=True,
    )
    file_sources = khoa_beach_info_item_to_file_sources(
        item,
        feature=feature,
        source_record_key=source_record_key,
        raw=raw,
    )
    return KhoaBeachInfoFeatureBundle(
        feature=feature,
        place_detail=place_detail,
        source_record=source_record,
        source_link=source_link,
        address_match_report=address_enrichment.report,
        feature_file_sources=file_sources,
    )


def khoa_beach_info_item_to_file_sources(
    item: Any,
    *,
    feature: Feature,
    source_record_key: str,
    raw: Mapping[str, Any] | None = None,
) -> tuple[FeatureFileSource, ...]:
    """KHOA 해수욕장 이미지 URL을 RustFS 적재 후보로 변환합니다."""

    raw_mapping = raw or _raw_mapping(item)
    image_url = _url_or_none(_text(item, "image_url", raw_keys=("beachImg", "image_url")))
    if image_url is None:
        return ()
    return (
        FeatureFileSource(
            feature_id=feature.feature_id,
            source_url=image_url,
            file_type="image",
            role="primary",
            display_order=0,
            alt_text=feature.name,
            provider=KHOA_PROVIDER,
            dataset_key=KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
            source_record_key=source_record_key,
            payload={
                "source_key": _source_key(item, raw_mapping),
                "khoa_field": "beachImg",
                "raw_value": _first(raw_mapping, "beachImg", "image_url"),
            },
        ),
    )


def load_khoa_oceans_beach_info(
    resource: Any,
    run: DagsterEtlRun,
) -> KhoaBeachInfoEtlResult | KhoaBeachInfoDbEtlResult:
    """TripMate Dagster op이 호출할 KHOA 해수욕장정보 loader body."""

    config = run.op_config
    client, session, rustfs_store, file_fetcher, reverse_geocoder = _resolve_khoa_beach_resources(
        resource
    )
    sido_names = _sido_names_config(config)
    page_size = (
        _optional_int(config.get("page_size"))
        or KHOA_OCEANS_BEACH_INFO_DEFAULT_PAGE_SIZE
    )
    max_pages = _optional_int(config.get("max_pages"))
    if session is not None:
        return collect_and_load_khoa_oceans_beach_info(
            session,
            client,
            sido_names=sido_names,
            page_size=page_size,
            max_pages=max_pages,
            collected_at=run.collected_at,
            rustfs_store=rustfs_store,
            file_fetcher=file_fetcher,
            reverse_geocoder=reverse_geocoder,
        )
    return collect_khoa_oceans_beach_info(
        client,
        sido_names=sido_names,
        page_size=page_size,
        max_pages=max_pages,
        collected_at=run.collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def khoa_oceans_beach_info_full_scan_identity(
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


khoa_oceans_beach_info_full_scan_job_spec = EtlJobSpec(
    job_name="khoa_oceans_beach_info_full_scan",
    op_name="collect_khoa_oceans_beach_info",
    dataset_key=KHOA_OCEANS_BEACH_INFO_DATASET_KEY,
    description=(
        "Collect all Ministry of Oceans beach-info pages through python-khoa-api "
        "and normalize them into beach place features."
    ),
    tags=(
        f"provider:{KHOA_PROVIDER}",
        "feature:place",
        "source:beach",
        "full_scan",
        "schedule:daily",
        "pagination:all-pages",
        "files:rustfs",
    ),
    loader=load_khoa_oceans_beach_info,
    success_message="KHOA oceans beach info full scan completed.",
    failure_message="KHOA oceans beach info full scan failed.",
    identity_resolver=khoa_oceans_beach_info_full_scan_identity,
    schedule_enabled=schedule_requires_any_env(
        "KHOA_DATA_GO_KR_SERVICE_KEY",
        "KHOA_SERVICE_KEY",
        "DATA_GO_KR_SERVICE_KEY",
        "PUBLIC_DATA_SERVICE_KEY",
    ),
)


def _source_key(item: Any, raw: Mapping[str, Any]) -> str | None:
    value = getattr(item, "source_key", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    sido_name = _text(item, "sido_name", raw_keys=("sidoNm", "SIDO_NM", "sido_name"))
    gugun_name = _text(item, "gugun_name", raw_keys=("gugunNm", "gugun_name")) or ""
    name = _text(item, "name", raw_keys=("staNm", "name"))
    if sido_name is None or name is None:
        return None
    return "|".join((sido_name, gugun_name, name))


def _coordinate_from_item(item: Any) -> Coordinate | None:
    coordinate = getattr(item, "coordinate", None)
    if isinstance(coordinate, Coordinate):
        return coordinate
    if isinstance(coordinate, Mapping):
        return Coordinate.model_validate(coordinate)
    lat = _optional_float(getattr(item, "lat", None))
    lon = _optional_float(getattr(item, "lon", None))
    if lat is None or lon is None:
        raw = _raw_mapping(item)
        lat = _optional_float(_first(raw, "lat", "latitude"))
        lon = _optional_float(_first(raw, "lon", "longitude"))
    if lat is None or lon is None:
        return None
    return Coordinate(lat=lat, lon=lon)


def _address_from_item(item: Any) -> Address:
    sido_name = _text(item, "sido_name", raw_keys=("sidoNm", "SIDO_NM", "sido_name"))
    gugun_name = _text(item, "gugun_name", raw_keys=("gugunNm", "gugun_name"))
    address = " ".join(part for part in (sido_name, gugun_name) if part)
    return Address(address=address or None)


def _feature_urls(item: Any) -> FeatureUrls:
    link_url = _url_or_none(_text(item, "link_url", raw_keys=("linkAddr", "link_url")))
    if link_url is None:
        return FeatureUrls()
    try:
        return FeatureUrls.model_validate({"homepage": link_url})
    except ValueError:
        return FeatureUrls()


def _beach_detail_payload(item: Any, raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sido_name": _text(item, "sido_name", raw_keys=("sidoNm", "SIDO_NM", "sido_name")),
        "gugun_name": _text(item, "gugun_name", raw_keys=("gugunNm", "gugun_name")),
        "beach_width_m": _optional_float(
            getattr(item, "beach_width_m", None) or _first(raw, "beachWid")
        ),
        "beach_length_m": _optional_float(
            getattr(item, "beach_length_m", None) or _first(raw, "beachLen")
        ),
        "beach_kind": _text(item, "beach_kind", raw_keys=("beachKnd", "beach_kind")),
        "link_url": _text(item, "link_url", raw_keys=("linkAddr", "link_url")),
        "link_name": _text(item, "link_name", raw_keys=("linkNm", "link_name")),
        "image_url": _text(item, "image_url", raw_keys=("beachImg", "image_url")),
        "emergency_contact": _text(
            item,
            "emergency_contact",
            raw_keys=("linkTel", "emergency_contact"),
        ),
        "source_num": _text(item, "num", raw_keys=("num",)),
    }


def _facility_info(item: Any, raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sido_name": _text(item, "sido_name", raw_keys=("sidoNm", "SIDO_NM", "sido_name")),
        "gugun_name": _text(item, "gugun_name", raw_keys=("gugunNm", "gugun_name")),
        "beach_width_m": _optional_float(
            getattr(item, "beach_width_m", None) or _first(raw, "beachWid")
        ),
        "beach_length_m": _optional_float(
            getattr(item, "beach_length_m", None) or _first(raw, "beachLen")
        ),
        "beach_kind": _text(item, "beach_kind", raw_keys=("beachKnd", "beach_kind")),
        "emergency_contact": _text(
            item,
            "emergency_contact",
            raw_keys=("linkTel", "emergency_contact"),
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


def _page_collected_at(page: Any) -> datetime | None:
    collected_at = getattr(page, "collected_at", None)
    if isinstance(collected_at, datetime):
        return collected_at
    context = getattr(page, "context", None)
    context_collected_at = getattr(context, "collected_at", None)
    return context_collected_at if isinstance(context_collected_at, datetime) else None


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


def _url_or_none(value: Any) -> str | None:
    text = _optional_str(value)
    if text is None:
        return None
    if text.startswith(("http://", "https://")):
        return text
    return None


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


def _sido_names_config(config: Mapping[str, object]) -> tuple[str, ...] | None:
    value = config.get("sido_names")
    if value is None:
        return None
    if isinstance(value, str):
        names = tuple(part.strip() for part in value.split(",") if part.strip())
    elif isinstance(value, list | tuple):
        names = tuple(str(part).strip() for part in value if str(part).strip())
    else:
        raise TypeError("sido_names must be a comma-separated string or sequence")
    return names or None


def _resolve_khoa_beach_resources(
    resource: Any,
) -> tuple[Any, Any | None, RustfsFileStore | None, FileFetcher | None, ReverseGeocoder | None]:
    if isinstance(resource, Mapping):
        client = resource.get("client") or resource.get("khoa_client")
        session = resource.get("session") or resource.get("feature_session")
        rustfs_store = resource.get("rustfs_store") or resource.get("feature_file_store")
        file_fetcher = resource.get("file_fetcher")
        reverse_geocoder = resource.get("reverse_geocoder")
    else:
        client = getattr(resource, "client", None) or getattr(resource, "khoa_client", None)
        session = getattr(resource, "session", None) or getattr(resource, "feature_session", None)
        rustfs_store = getattr(resource, "rustfs_store", None) or getattr(
            resource,
            "feature_file_store",
            None,
        )
        file_fetcher = getattr(resource, "file_fetcher", None)
        reverse_geocoder = getattr(resource, "reverse_geocoder", None)
        if client is None:
            client = resource
    if client is None:
        raise ValueError("KHOA beach ETL resource must provide a public provider client")
    return client, session, rustfs_store, file_fetcher, reverse_geocoder


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))


async def _aiter_pages(pages: Any):
    if hasattr(pages, "__aiter__"):
        async for page in pages:
            yield page
        return
    for page in pages:
        yield page
