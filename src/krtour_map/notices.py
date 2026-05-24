from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from kraddr.base import Address

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
    NOTICE_TYPE_COASTAL_ISOLATION,
    NOTICE_TYPE_EARTHQUAKE,
    NOTICE_TYPE_HEAT_WAVE,
    NOTICE_TYPE_HEAVY_RAIN,
    NOTICE_TYPE_HEAVY_SNOW,
    NOTICE_TYPE_LANDSLIDE,
    NOTICE_TYPE_ROAD_CLOSURE,
    NOTICE_TYPE_ROADWORK,
    NOTICE_TYPE_SAFETY,
    NOTICE_TYPE_TRAFFIC,
    NOTICE_TYPE_TRAFFIC_ACCIDENT,
    NOTICE_TYPE_WEATHER_ALERT,
    Coordinate,
    Feature,
    NoticeDetail,
    RawDataRef,
    SourceLink,
    SourceRecord,
    normalize_notice_type,
)

KREX_TRAFFIC_NOTICE_DATASET_KEY = "krex_traffic_notices"
KMA_WEATHER_ALERT_NOTICE_DATASET_KEY = "kma_weather_alerts"
KRFOREST_SAFETY_NOTICE_DATASET_KEY = "forest_safety_notices"
KHOA_COASTAL_NOTICE_DATASET_KEY = "khoa_coastal_notices"

KREX_TRAFFIC_NOTICE_INTERVAL_MINUTES = 5
KMA_WEATHER_ALERT_NOTICE_INTERVAL_MINUTES = 10
KRFOREST_SAFETY_NOTICE_INTERVAL_MINUTES = 30
KHOA_COASTAL_NOTICE_INTERVAL_MINUTES = 60

KREX_NOTICE_PROVIDER = "python-krex-api"
KMA_NOTICE_PROVIDER = "python-kma-api"
KRFOREST_NOTICE_PROVIDER = "python-krforest-api"
KHOA_NOTICE_PROVIDER = "python-khoa-api"


@dataclass(frozen=True)
class NoticeDatasetSpec:
    dataset_key: str
    provider: str
    source_entity_type: str
    default_notice_type: str
    title: str
    interval_minutes: int
    tags: tuple[str, ...]


@dataclass(frozen=True)
class SkippedNoticeItem:
    dataset_key: str
    source_entity_id: str | None
    reason: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class NoticeFeatureBundle:
    feature: Feature
    notice_detail: NoticeDetail
    source_record: SourceRecord
    source_link: SourceLink
    address_match_report: AddressMatchReport


@dataclass(frozen=True)
class NoticeFeatureEtlResult:
    dataset_key: str
    provider: str
    source_entity_type: str
    features: tuple[Feature, ...]
    notice_details: tuple[NoticeDetail, ...]
    source_records: tuple[SourceRecord, ...]
    source_links: tuple[SourceLink, ...]
    address_match_reports: tuple[AddressMatchReport, ...] = ()
    skipped_items: tuple[SkippedNoticeItem, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.features)


@dataclass(frozen=True)
class NoticeFeatureDbEtlResult:
    collection: NoticeFeatureEtlResult
    load: FeatureDbLoadResult

    @property
    def item_count(self) -> int:
        return self.collection.item_count


@dataclass(frozen=True)
class NoticeLoadResources:
    items: Iterable[Any]
    session: Any | None = None
    reverse_geocoder: ReverseGeocoder | None = None
    kraddr_geo_store: Any | None = None
    kraddr_geo_database_path: str | None = None
    kraddr_geo_store_kwargs: Mapping[str, Any] | None = None
    kraddr_geo_fallback: bool = True
    kraddr_geo_max_distance_m: float | None = 50.0


NOTICE_DATASET_SPECS = (
    NoticeDatasetSpec(
        dataset_key=KREX_TRAFFIC_NOTICE_DATASET_KEY,
        provider=KREX_NOTICE_PROVIDER,
        source_entity_type="traffic_notice",
        default_notice_type=NOTICE_TYPE_TRAFFIC,
        title="KREX traffic notices",
        interval_minutes=KREX_TRAFFIC_NOTICE_INTERVAL_MINUTES,
        tags=("feature:notice", "domain:traffic", "schedule:5min"),
    ),
    NoticeDatasetSpec(
        dataset_key=KMA_WEATHER_ALERT_NOTICE_DATASET_KEY,
        provider=KMA_NOTICE_PROVIDER,
        source_entity_type="weather_alert",
        default_notice_type=NOTICE_TYPE_WEATHER_ALERT,
        title="KMA weather warning notices",
        interval_minutes=KMA_WEATHER_ALERT_NOTICE_INTERVAL_MINUTES,
        tags=("feature:notice", "domain:weather", "schedule:10min"),
    ),
    NoticeDatasetSpec(
        dataset_key=KRFOREST_SAFETY_NOTICE_DATASET_KEY,
        provider=KRFOREST_NOTICE_PROVIDER,
        source_entity_type="safety_notice",
        default_notice_type=NOTICE_TYPE_SAFETY,
        title="Forest safety notices",
        interval_minutes=KRFOREST_SAFETY_NOTICE_INTERVAL_MINUTES,
        tags=("feature:notice", "domain:safety", "schedule:30min"),
    ),
    NoticeDatasetSpec(
        dataset_key=KHOA_COASTAL_NOTICE_DATASET_KEY,
        provider=KHOA_NOTICE_PROVIDER,
        source_entity_type="coastal_notice",
        default_notice_type=NOTICE_TYPE_COASTAL_ISOLATION,
        title="KHOA coastal and sea-parting notices",
        interval_minutes=KHOA_COASTAL_NOTICE_INTERVAL_MINUTES,
        tags=("feature:notice", "domain:coastal", "schedule:60min"),
    ),
)


def notice_dataset_specs() -> tuple[NoticeDatasetSpec, ...]:
    return NOTICE_DATASET_SPECS


def notice_dataset_spec(dataset_key: str) -> NoticeDatasetSpec:
    for spec in NOTICE_DATASET_SPECS:
        if spec.dataset_key == dataset_key:
            return spec
    raise ValueError(f"unknown notice dataset_key: {dataset_key}")


def collect_notice_features(
    items: Iterable[Any],
    *,
    dataset_key: str,
    provider: str,
    source_entity_type: str,
    default_notice_type: str,
    source_agency: str | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> NoticeFeatureEtlResult:
    features: list[Feature] = []
    notice_details: list[NoticeDetail] = []
    source_records: list[SourceRecord] = []
    source_links: list[SourceLink] = []
    reports: list[AddressMatchReport] = []
    skipped: list[SkippedNoticeItem] = []
    for item in items:
        bundle = notice_item_to_feature_bundle(
            item,
            dataset_key=dataset_key,
            provider=provider,
            source_entity_type=source_entity_type,
            default_notice_type=default_notice_type,
            source_agency=source_agency,
            collected_at=collected_at,
            reverse_geocoder=reverse_geocoder,
        )
        if isinstance(bundle, SkippedNoticeItem):
            skipped.append(bundle)
            continue
        features.append(bundle.feature)
        notice_details.append(bundle.notice_detail)
        source_records.append(bundle.source_record)
        source_links.append(bundle.source_link)
        reports.append(bundle.address_match_report)
    return NoticeFeatureEtlResult(
        dataset_key=dataset_key,
        provider=provider,
        source_entity_type=source_entity_type,
        features=tuple(features),
        notice_details=tuple(notice_details),
        source_records=tuple(source_records),
        source_links=tuple(source_links),
        address_match_reports=tuple(reports),
        skipped_items=tuple(skipped),
    )


def collect_notice_dataset_features(
    dataset_key: str,
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> NoticeFeatureEtlResult:
    spec = notice_dataset_spec(dataset_key)
    return collect_notice_features(
        items,
        dataset_key=spec.dataset_key,
        provider=spec.provider,
        source_entity_type=spec.source_entity_type,
        default_notice_type=spec.default_notice_type,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def collect_krex_traffic_notice_features(
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> NoticeFeatureEtlResult:
    return collect_notice_dataset_features(
        KREX_TRAFFIC_NOTICE_DATASET_KEY,
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def collect_kma_weather_alert_notice_features(
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> NoticeFeatureEtlResult:
    return collect_notice_dataset_features(
        KMA_WEATHER_ALERT_NOTICE_DATASET_KEY,
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def collect_krforest_safety_notice_features(
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> NoticeFeatureEtlResult:
    return collect_notice_dataset_features(
        KRFOREST_SAFETY_NOTICE_DATASET_KEY,
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def collect_khoa_coastal_notice_features(
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> NoticeFeatureEtlResult:
    return collect_notice_dataset_features(
        KHOA_COASTAL_NOTICE_DATASET_KEY,
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def notice_item_to_feature_bundle(
    item: Any,
    *,
    dataset_key: str,
    provider: str,
    source_entity_type: str,
    default_notice_type: str,
    source_agency: str | None = None,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> NoticeFeatureBundle | SkippedNoticeItem:
    raw = _raw_mapping(item)
    source_key = _source_key(item, raw)
    if source_key is None:
        return SkippedNoticeItem(dataset_key, None, "missing source key", raw)
    title = _title(item, raw, default_notice_type)
    coordinate = _coordinate(item, raw)
    address_enrichment = enrich_address_from_coordinate(
        address=_address(item, raw),
        coordinate=coordinate,
        raw=raw,
        reverse_geocoder=reverse_geocoder,
        source_label=dataset_key,
        source_entity_id=source_key,
    )
    notice_type = classify_notice_type(item, raw, default=default_notice_type)
    category = f"notice.{notice_type}"
    marker = notice_marker_style(notice_type)
    raw_payload_hash = make_payload_hash(raw, length=32)
    feature_id = make_feature_id(
        provider=provider,
        source_type=source_entity_type,
        source_natural_key=source_key,
        kind=FeatureKind.NOTICE,
        category=category,
        legal_dong_code=address_enrichment.address.legal_dong_code,
    )
    valid_start = _datetime_value(
        item,
        raw,
        "valid_start_time",
        "valid_from",
        "start_time",
        "start_at",
        "started_at",
        "effective_at",
        "occurred_at",
        "tmFc",
    )
    valid_end = _datetime_value(
        item,
        raw,
        "valid_end_time",
        "valid_until",
        "end_time",
        "end_at",
        "ended_at",
        "expires_at",
        "tmEf",
    )
    source_record = SourceRecord(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_key,
        raw_payload_hash=raw_payload_hash,
        source_version=_text(
            item,
            raw,
            "version",
            "updated_at",
            "modified_at",
            "reference_date",
            "referenceDate",
        ),
        raw_name=title,
        raw_address=address_enrichment.address.display_address,
        raw_longitude=Decimal(str(coordinate.longitude)) if coordinate is not None else None,
        raw_latitude=Decimal(str(coordinate.latitude)) if coordinate is not None else None,
        raw_data=dict(raw),
        fetched_at=collected_at,
        imported_at=collected_at or _now_kst(),
    )
    detail_payload = {
        "selected_source": {
            "provider": provider,
            "dataset_key": dataset_key,
            "source_entity_type": source_entity_type,
            "source_entity_id": source_key,
        },
        "notice": {
            "notice_type": notice_type,
            "source_agency": source_agency
            or _text(item, raw, "source_agency", "agency", "agency_name", "sourceAgency"),
            "severity": _severity(item, raw, notice_type),
            "valid_start_time": valid_start.isoformat() if valid_start else None,
            "valid_end_time": valid_end.isoformat() if valid_end else None,
            "summary": _summary(item, raw),
        },
        "address_match": {
            "match_level": address_enrichment.report.match_level,
            "confidence": address_enrichment.report.confidence,
            "notes": list(address_enrichment.report.notes),
        },
        "raw": dict(raw),
    }
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.NOTICE,
        name=title,
        coord=coordinate,
        address=address_enrichment.address,
        category=category,
        marker_icon=marker["marker_icon"],
        marker_color=marker["marker_color"],
        detail=detail_payload,
        raw_refs=[
            RawDataRef(
                provider=provider,
                dataset_key=dataset_key,
                source_entity_id=source_key,
                source_role=SourceRole.PRIMARY,
                fetched_at=collected_at,
                payload_hash=raw_payload_hash,
            )
        ],
    )
    notice_detail = NoticeDetail(
        feature_id=feature_id,
        notice_type=notice_type,
        severity=detail_payload["notice"]["severity"],
        valid_start_time=valid_start,
        valid_end_time=valid_end,
        source_agency=detail_payload["notice"]["source_agency"],
        officer_name=_text(item, raw, "officer_name", "officer", "manager"),
        payload=detail_payload,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record.key(),
        source_role=SourceRole.PRIMARY,
        match_method="notice_source_key",
        confidence=100,
        is_primary_source=True,
    )
    return NoticeFeatureBundle(
        feature=feature,
        notice_detail=notice_detail,
        source_record=source_record,
        source_link=source_link,
        address_match_report=address_enrichment.report,
    )


def classify_notice_type(
    item: Any,
    raw: Mapping[str, Any],
    *,
    default: str = NOTICE_TYPE_SAFETY,
) -> str:
    explicit = _text(
        item,
        raw,
        "notice_type",
        "noticeType",
        "type",
        "kind",
        "category",
        "event_type",
        "eventType",
        "incident_type",
        "incidentType",
        "alert_type",
        "alertType",
        "warn_var",
        "warnVar",
        "warnVarNm",
    )
    if explicit:
        normalized = normalize_notice_type(explicit)
        if normalized != explicit or normalized in _KNOWN_NOTICE_TYPES:
            return normalized

    text = " ".join(
        value
        for value in (
            explicit,
            _title(item, raw, default),
            _summary(item, raw),
            _text(item, raw, "message", "content", "description", "reason", "road_name"),
        )
        if value
    ).lower()
    if any(token in text for token in ("사고", "accident", "crash", "추돌")):
        return NOTICE_TYPE_TRAFFIC_ACCIDENT
    if any(token in text for token in ("공사", "작업", "roadwork", "construction")):
        return NOTICE_TYPE_ROADWORK
    if any(token in text for token in ("통제", "차단", "closure", "closed", "우회")):
        return NOTICE_TYPE_ROAD_CLOSURE
    if any(token in text for token in ("호우", "heavy rain", "rain warning")):
        return NOTICE_TYPE_HEAVY_RAIN
    if any(token in text for token in ("대설", "폭설", "heavy snow", "snow warning")):
        return NOTICE_TYPE_HEAVY_SNOW
    if any(token in text for token in ("폭염", "heat wave", "heatwave")):
        return NOTICE_TYPE_HEAT_WAVE
    if any(token in text for token in ("지진", "earthquake")):
        return NOTICE_TYPE_EARTHQUAKE
    if any(token in text for token in ("산사태", "landslide")):
        return NOTICE_TYPE_LANDSLIDE
    if any(token in text for token in ("갈라짐", "바다갈라짐", "sea parting", "coastal")):
        return NOTICE_TYPE_COASTAL_ISOLATION
    if any(token in text for token in ("기상", "특보", "주의보", "경보", "weather")):
        return NOTICE_TYPE_WEATHER_ALERT
    if any(token in text for token in ("교통", "도로", "traffic", "road")):
        return NOTICE_TYPE_TRAFFIC
    if any(token in text for token in ("안전", "위험", "재난", "safety", "disaster")):
        return NOTICE_TYPE_SAFETY
    return normalize_notice_type(default)


def notice_marker_style(notice_type: str) -> dict[str, str]:
    normalized = normalize_notice_type(notice_type)
    styles = {
        NOTICE_TYPE_TRAFFIC: {"marker_icon": "roadblock", "marker_color": "#d97706"},
        NOTICE_TYPE_TRAFFIC_ACCIDENT: {"marker_icon": "car", "marker_color": "#dc2626"},
        NOTICE_TYPE_ROAD_CLOSURE: {"marker_icon": "roadblock", "marker_color": "#b91c1c"},
        NOTICE_TYPE_ROADWORK: {"marker_icon": "roadblock", "marker_color": "#f59e0b"},
        NOTICE_TYPE_WEATHER_ALERT: {"marker_icon": "warning", "marker_color": "#2563eb"},
        NOTICE_TYPE_HEAVY_RAIN: {"marker_icon": "water", "marker_color": "#0284c7"},
        NOTICE_TYPE_HEAVY_SNOW: {"marker_icon": "snow", "marker_color": "#64748b"},
        NOTICE_TYPE_HEAT_WAVE: {"marker_icon": "fire-station", "marker_color": "#ea580c"},
        NOTICE_TYPE_SAFETY: {"marker_icon": "warning", "marker_color": "#7c3aed"},
        NOTICE_TYPE_EARTHQUAKE: {"marker_icon": "danger", "marker_color": "#9333ea"},
        NOTICE_TYPE_LANDSLIDE: {"marker_icon": "landslide", "marker_color": "#854d0e"},
        NOTICE_TYPE_COASTAL_ISOLATION: {"marker_icon": "water", "marker_color": "#0891b2"},
    }
    return styles.get(normalized, {"marker_icon": "warning", "marker_color": "#475569"})


def load_notice_result(session: Any, result: NoticeFeatureEtlResult) -> FeatureDbLoadResult:
    return load_feature_rows(
        session,
        feature_items=result.features,
        source_record_items=result.source_records,
        source_link_items=result.source_links,
        notice_detail_items=result.notice_details,
    )


def collect_and_load_notice_features(
    session: Any,
    dataset_key: str,
    items: Iterable[Any],
    *,
    collected_at: datetime | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> NoticeFeatureDbEtlResult:
    collection = collect_notice_dataset_features(
        dataset_key,
        items,
        collected_at=collected_at,
        reverse_geocoder=reverse_geocoder,
    )
    return NoticeFeatureDbEtlResult(
        collection=collection,
        load=load_notice_result(session, collection),
    )


def load_notice_features(
    resource: Any,
    run: DagsterEtlRun,
) -> NoticeFeatureEtlResult | NoticeFeatureDbEtlResult:
    items, session, reverse_geocoder = _resolve_notice_resources(resource)
    if session is None:
        return collect_notice_dataset_features(
            run.dataset_key,
            items,
            collected_at=run.collected_at,
            reverse_geocoder=reverse_geocoder,
        )
    return collect_and_load_notice_features(
        session,
        run.dataset_key,
        items,
        collected_at=run.collected_at,
        reverse_geocoder=reverse_geocoder,
    )


def notice_interval_identity(
    _session: Any,
    dataset_key: str,
    execution: DagsterEtlExecution,
) -> EtlRunIdentity:
    logical = execution.logical_datetime_kst
    return EtlRunIdentity(
        run_key=f"{dataset_key}-{logical:%Y%m%dT%H%M}",
        run_type=execution.run_type,
        trigger_date=logical.date(),
    )


def notice_job_specs() -> tuple[EtlJobSpec, ...]:
    return tuple(_notice_job_spec(spec) for spec in NOTICE_DATASET_SPECS)


def _notice_job_spec(spec: NoticeDatasetSpec) -> EtlJobSpec:
    env_names = {
        KREX_NOTICE_PROVIDER: (
            "KREX_SERVICE_KEY",
            "DATA_GO_KR_SERVICE_KEY",
            "PUBLIC_DATA_SERVICE_KEY",
        ),
        KMA_NOTICE_PROVIDER: (
            "KMA_SERVICE_KEY",
            "DATA_GO_KR_SERVICE_KEY",
            "PUBLIC_DATA_SERVICE_KEY",
        ),
        KRFOREST_NOTICE_PROVIDER: (
            "KRFOREST_SERVICE_KEY",
            "DATA_GO_KR_SERVICE_KEY",
            "PUBLIC_DATA_SERVICE_KEY",
        ),
        KHOA_NOTICE_PROVIDER: (
            "KHOA_SERVICE_KEY",
            "DATA_GO_KR_SERVICE_KEY",
            "PUBLIC_DATA_SERVICE_KEY",
        ),
    }.get(spec.provider, ())
    return EtlJobSpec(
        job_name=f"{spec.dataset_key}_interval_scan",
        op_name="collect_notice_features",
        dataset_key=spec.dataset_key,
        description=(
            f"Collect {spec.title} every {spec.interval_minutes} minutes and store "
            "them as notice features with notice_type."
        ),
        tags=(f"provider:{spec.provider}", *spec.tags),
        loader=load_notice_features,
        success_message=f"{spec.title} notice ETL completed.",
        failure_message=f"{spec.title} notice ETL failed.",
        identity_resolver=notice_interval_identity,
        schedule_enabled=schedule_requires_any_env(*env_names) if env_names else None,
    )


_KNOWN_NOTICE_TYPES = {
    NOTICE_TYPE_TRAFFIC,
    NOTICE_TYPE_TRAFFIC_ACCIDENT,
    NOTICE_TYPE_ROAD_CLOSURE,
    NOTICE_TYPE_ROADWORK,
    NOTICE_TYPE_WEATHER_ALERT,
    NOTICE_TYPE_HEAVY_RAIN,
    NOTICE_TYPE_HEAVY_SNOW,
    NOTICE_TYPE_HEAT_WAVE,
    NOTICE_TYPE_SAFETY,
    NOTICE_TYPE_EARTHQUAKE,
    NOTICE_TYPE_LANDSLIDE,
    NOTICE_TYPE_COASTAL_ISOLATION,
}


def _resolve_notice_resources(
    resource: Any,
) -> tuple[Iterable[Any], Any | None, ReverseGeocoder | None]:
    if isinstance(resource, Mapping):
        items = resource.get("items")
        session = resource.get("session") or resource.get("feature_session")
        reverse_geocoder = resolve_reverse_geocoder(resource)
    else:
        items = getattr(resource, "items", None)
        session = getattr(resource, "session", None) or getattr(resource, "feature_session", None)
        reverse_geocoder = resolve_reverse_geocoder(resource)
    if items is None:
        raise ValueError("notice ETL resource must provide items from provider public clients")
    return items, session, reverse_geocoder


def _source_key(item: Any, raw: Mapping[str, Any]) -> str | None:
    value = _text(
        item,
        raw,
        "source_entity_id",
        "notice_id",
        "noticeId",
        "incident_id",
        "incidentId",
        "event_id",
        "eventId",
        "id",
        "seq",
        "tmFc",
    )
    if value:
        return value
    if raw:
        return f"hash:{make_payload_hash(raw, length=24)}"
    return None


def _title(item: Any, raw: Mapping[str, Any], default_notice_type: str) -> str:
    return (
        _text(
            item,
            raw,
            "title",
            "name",
            "subject",
            "message",
            "event",
            "eventName",
            "incident",
            "incidentName",
            "road_name",
            "roadName",
        )
        or normalize_notice_type(default_notice_type).replace("_", " ").title()
    )


def _summary(item: Any, raw: Mapping[str, Any]) -> str | None:
    return _text(
        item,
        raw,
        "summary",
        "message",
        "content",
        "description",
        "reason",
        "memo",
        "remark",
        "headline",
    )


def _coordinate(item: Any, raw: Mapping[str, Any]) -> Coordinate | None:
    coordinate = getattr(item, "coordinate", None) or raw.get("coordinate")
    if isinstance(coordinate, Coordinate):
        return coordinate
    if isinstance(coordinate, Mapping):
        try:
            return Coordinate.model_validate(coordinate)
        except ValueError:
            return None
    lat = _float_or_none(
        _value(item, raw, "lat", "latitude", "y", "coord_y", "coordY", "la", "tmY")
    )
    lon = _float_or_none(
        _value(item, raw, "lon", "lng", "longitude", "x", "coord_x", "coordX", "lo", "tmX")
    )
    if lat is None or lon is None:
        return None
    if not 33.0 <= lat <= 39.5 or not 124.0 <= lon <= 132.0:
        return None
    return Coordinate(lat=lat, lon=lon)


def _address(item: Any, raw: Mapping[str, Any]) -> Address:
    address = getattr(item, "address", None) or raw.get("address")
    if isinstance(address, Address):
        return address
    if isinstance(address, Mapping):
        return Address.from_mapping(address) or Address()
    return Address(
        address=_text(
            item,
            raw,
            "address",
            "addr",
            "road_address",
            "roadAddress",
            "location",
            "area_name",
            "areaName",
        )
    )


def _severity(item: Any, raw: Mapping[str, Any], notice_type: str) -> int | None:
    value = _value(
        item,
        raw,
        "severity",
        "level",
        "alert_level",
        "alertLevel",
        "warn_level",
        "warnLevel",
    )
    parsed = _int_or_none(value)
    if parsed is not None:
        return max(0, min(5, parsed))
    text = " ".join(
        value
        for value in (
            _title(item, raw, notice_type),
            _summary(item, raw),
            _text(item, raw, "status", "status_name", "statusName", "warnStress"),
        )
        if value
    )
    if any(token in text for token in ("대피", "위험", "경보", "emergency")):
        return 4
    if any(token in text for token in ("주의보", "주의", "advisory", "warning")):
        return 3
    if notice_type in {
        NOTICE_TYPE_TRAFFIC_ACCIDENT,
        NOTICE_TYPE_ROAD_CLOSURE,
        NOTICE_TYPE_HEAVY_RAIN,
        NOTICE_TYPE_HEAVY_SNOW,
        NOTICE_TYPE_HEAT_WAVE,
        NOTICE_TYPE_EARTHQUAKE,
        NOTICE_TYPE_LANDSLIDE,
    }:
        return 3
    return 2


def _datetime_value(item: Any, raw: Mapping[str, Any], *keys: str) -> datetime | None:
    value = _value(item, raw, *keys)
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if value in (None, ""):
        return None
    text = str(value).strip()
    for fmt in ("%Y%m%d%H%M", "%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            from zoneinfo import ZoneInfo

            return datetime.strptime(text, fmt).replace(tzinfo=ZoneInfo("Asia/Seoul"))
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        from zoneinfo import ZoneInfo

        return parsed.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return parsed.astimezone()


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


def _text(item: Any, raw: Mapping[str, Any], *keys: str) -> str | None:
    value = _value(item, raw, *keys)
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _value(item: Any, raw: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = getattr(item, key, None)
        if value in (None, ""):
            value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _now_kst() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul"))
