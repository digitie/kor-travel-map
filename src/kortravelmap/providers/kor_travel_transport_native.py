"""Transport 저장 projection의 순수 복원·명시 presence·초기 적격성 진단.

기존 두 converter만 재호출한다. 최초 범위는 동일 raw 재관측이며 변경 raw는 EX다.
DB/current head/Geo stamp/전체 closure를 증명하거나 collector에 apply 권한을 주지 않는다.
호출자는 await 동안 입력 DTO와 그 내부 가변 객체를 독점 소유해야 한다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast

from kortravelmap.core.feature_projection import within_place_projection_budget
from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Address,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.providers.kor_travel_transport import (
    DATASET_KEY_AIRPORTS,
    DATASET_KEY_REST_AREAS,
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
    TransportAirport,
    TransportCoordinate,
    TransportRestArea,
)
from kortravelmap.providers.krairport import AirportMetadataItem, airports_to_bundles
from kortravelmap.providers.krex import KrexRestAreaItem, rest_areas_to_bundles

AIRPORT_NAME_NORMALIZER_REVISION = "transport-airport-name-v1"
REST_AREA_SCALAR_NORMALIZER_REVISION = "transport-rest-area-name-phones-v1"
_AIRPORT_KEYS = frozenset(
    {"code", "name_korean", "name_english", "icao_code", "municipality", "latitude", "longitude"}
)
_REST_KEYS = frozenset(
    {"natural_key", "name", "route_name", "direction", "lon", "lat", "phone_number"}
)
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class TransportGeoEvidence:
    """호출자의 명시 Geo 비교 증거. 실제 DB token/stamp 권한 증명은 아니다."""

    mode: Literal["not_requested", "resolved"]
    version_token: str | None = None
    data_token: str | None = None
    address: Address | None = None
    stamp_digest: str | None = None

    def __post_init__(self) -> None:
        if not within_place_projection_budget(
            (self.version_token, self.data_token, self.address, self.stamp_digest)
        ):
            raise ValueError("invalid Transport Geo budget")
        if self.mode == "not_requested":
            valid = all(
                value is None
                for value in (self.version_token, self.data_token, self.address, self.stamp_digest)
            )
        elif self.mode == "resolved":
            valid = (
                all(
                    type(value) is str and 0 < len(value) <= 256 and value == value.strip()
                    for value in (self.version_token, self.data_token)
                )
                and type(self.address) is Address
                and type(self.stamp_digest) is str
                and _DIGEST.fullmatch(self.stamp_digest) is not None
            )
        else:
            valid = False
        if not valid:
            raise ValueError("incomplete Transport Geo evidence")


@dataclass(frozen=True)
class TransportScalarEligibility:
    """진단 결과이며 DB evidence·apply 권위나 전체 snapshot 성공이 아니다."""

    eligible: bool
    reason: str

    @property
    def requires_database_verification(self) -> bool:
        return True

    @property
    def collector_ready(self) -> bool:
        return False


def _presence(dataset: str) -> ProviderFieldPresence:
    if dataset == DATASET_KEY_AIRPORTS:
        return ProviderFieldPresence(
            normalizer_revision=AIRPORT_NAME_NORMALIZER_REVISION,
            supplied_fields=frozenset({"core.name"}),
        )
    if dataset == DATASET_KEY_REST_AREAS:
        return ProviderFieldPresence(
            normalizer_revision=REST_AREA_SCALAR_NORMALIZER_REVISION,
            supplied_fields=frozenset({"core.name", "place.phones"}),
        )
    raise ValueError("unsupported Transport dataset")


def _coordinate(lon: object, lat: object) -> None:
    if (lon is None) != (lat is None):
        raise ValueError("incomplete Transport coordinate pair")
    for value, bound in ((lon, 180), (lat, 90)):
        if value is not None and (
            type(value) is not float or not math.isfinite(value) or abs(value) > bound
        ):
            raise ValueError("invalid Transport coordinate")


def _bounded_item(item: TransportAirport | TransportRestArea) -> None:
    # asdict/deepcopy/model_dump 없이 고정 개수 필드만 직접 꺼낸 뒤 공통 예산을 검사한다.
    values: tuple[object, ...]
    if type(item) is TransportAirport:
        coord = item.coordinate
        if coord is not None and type(coord) is not TransportCoordinate:
            raise ValueError("noncanonical Transport coordinate")
        if coord is not None and (type(coord.lon) is not float or type(coord.lat) is not float):
            raise ValueError("invalid Transport coordinate components")
        values = (item.code, item.name_korean, item.name_english, item.icao_code, item.municipality)
        lon, lat = (coord.lon, coord.lat) if coord is not None else (None, None)
        required = (item.code, item.name_english)
    elif type(item) is TransportRestArea:
        values = (item.natural_key, item.name, item.route_name, item.direction, item.phone_number)
        lon, lat = item.lon, item.lat
        required = (item.natural_key, item.name)
        if any(
            flag is not None and type(flag) is not bool
            for flag in (item.has_gas_station, item.has_lpg_station, item.has_ev_charger)
        ):
            raise ValueError("invalid Transport ignored flag type")
    else:
        raise ValueError("noncanonical Transport item")
    if type(item.raw) is not dict or not within_place_projection_budget(
        (*values, lon, lat, item.raw)
    ):
        raise ValueError("invalid Transport item budget")
    if any(type(value) is not str for value in required) or any(
        value is not None and type(value) is not str for value in values
    ):
        raise ValueError("invalid Transport item text")
    _coordinate(lon, lat)


async def transport_item_to_native_bundle(
    item: TransportAirport | TransportRestArea,
    *,
    fetched_at: datetime,
    geo: TransportGeoEvidence,
) -> FeatureBundle:
    """정본 dataclass → 기존 converter → 새 명시 presence. HTTP/DB 호출은 없다."""
    _bounded_item(item)
    # 기존 Protocol의 settable 표기와 달리 실제 converter는 frozen DTO 속성을 읽기만 한다.
    if type(geo) is not TransportGeoEvidence or not within_place_projection_budget((geo.address,)):
        raise ValueError("invalid Transport Geo evidence")
    if (
        type(fetched_at) is not datetime
        or fetched_at.tzinfo is None
        or fetched_at.utcoffset() is None
    ):
        raise ValueError("aware Transport observation time required")

    async def reverse(_coordinate: object) -> Address | None:
        return geo.address

    has_coordinate = (
        item.coordinate is not None
        if type(item) is TransportAirport
        else cast(TransportRestArea, item).lon is not None
    )
    if has_coordinate != (geo.mode == "resolved"):
        raise ValueError("unsupported Transport Geo coordinate evidence")
    if type(item) is TransportAirport:
        bundles = await airports_to_bundles(
            [cast(AirportMetadataItem, item)],
            fetched_at=fetched_at,
            reverse_geocoder=reverse if geo.mode == "resolved" else None,
        )
    else:
        bundles = await rest_areas_to_bundles(
            [cast(KrexRestAreaItem, item)],
            fetched_at=fetched_at,
            reverse_geocoder=reverse if geo.mode == "resolved" else None,
        )
    if len(bundles) != 1:
        raise ValueError("Transport projection did not produce one item")
    bundle = bundles[0]
    result = bundle.model_copy(
        update={"provider_field_presence": _presence(bundle.source_record.dataset_key)}
    )
    if not within_place_projection_budget((result,)):
        raise ValueError("invalid Transport bundle budget")
    return result


def _stored_coordinate(
    raw: dict[str, Any], lon_key: str, lat_key: str
) -> tuple[float | None, float | None]:
    values: list[float | None] = []
    if (raw[lon_key] is None) != (raw[lat_key] is None):
        raise ValueError("incomplete Transport projected coordinate")
    for key, bound in ((lon_key, 180), (lat_key, 90)):
        value = raw[key]
        if value is None:
            values.append(None)
            continue
        if type(value) is not str or len(value) > 128 or not value.isascii():
            raise ValueError("invalid Transport projected coordinate text")
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise ValueError("invalid Transport projected coordinate") from None
        if not number.is_finite() or number.copy_abs() > bound:
            raise ValueError("invalid Transport projected coordinate")
        values.append(float(number))
    return values[0], values[1]


async def rebuild_transport_projection(
    record: SourceRecord,
    *,
    geo: TransportGeoEvidence,
) -> FeatureBundle:
    """Map 저장 raw7만 원 dataclass로 복원한다. upstream 원문/생략된 flag 복원이 아니다."""
    if type(record) is not SourceRecord or not within_place_projection_budget((record,)):
        raise ValueError("invalid Transport record budget")
    if record.provider != KOR_TRAVEL_TRANSPORT_PROVIDER_NAME or record.expires_at is not None:
        raise ValueError("unsupported Transport source domain")
    raw = record.raw_data
    if record.dataset_key == DATASET_KEY_AIRPORTS and record.source_entity_type == "airport":
        keys = _AIRPORT_KEYS
    elif record.dataset_key == DATASET_KEY_REST_AREAS and record.source_entity_type == "rest_area":
        keys = _REST_KEYS
    else:
        raise ValueError("unsupported Transport source domain")
    if (
        type(raw) is not dict
        or len(raw) != 7
        or set(raw) != keys
        or any(value is not None and type(value) is not str for value in raw.values())
    ):
        raise ValueError("invalid Transport stored projection shape")
    if len(record.raw_payload_hash) != 32 or record.raw_payload_hash != make_payload_hash(raw):
        raise ValueError("Transport source hash mismatch")
    if record.source_record_key != make_source_record_key(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        source_entity_id=record.source_entity_id,
        raw_payload_hash=record.raw_payload_hash,
    ):
        raise ValueError("Transport source key mismatch")
    item: TransportAirport | TransportRestArea
    if record.dataset_key == DATASET_KEY_AIRPORTS:
        lon, lat = _stored_coordinate(raw, "longitude", "latitude")
        item = TransportAirport(
            code=raw["code"],
            name_korean=raw["name_korean"],
            name_english=raw["name_english"],
            icao_code=raw["icao_code"],
            municipality=raw["municipality"],
            coordinate=TransportCoordinate(lat=lat, lon=lon)
            if lat is not None and lon is not None
            else None,
            raw={},
        )
    else:
        lon, lat = _stored_coordinate(raw, "lon", "lat")
        item = TransportRestArea(
            natural_key=raw["natural_key"],
            name=raw["name"],
            route_name=raw["route_name"],
            direction=raw["direction"],
            lon=lon,
            lat=lat,
            phone_number=raw["phone_number"],
            has_gas_station=None,
            has_lpg_station=None,
            has_ev_charger=None,
            raw={},
        )
    bundle = await transport_item_to_native_bundle(item, fetched_at=record.fetched_at, geo=geo)
    rebuilt = bundle.source_record
    if (
        rebuilt.raw_data != raw
        or rebuilt.raw_payload_hash != record.raw_payload_hash
        or rebuilt.source_entity_id != record.source_entity_id
        or rebuilt.source_record_key != record.source_record_key
    ):
        raise ValueError("Transport projection roundtrip changed source evidence")
    return bundle.model_copy(update={"source_record": record})


def _meaning(bundle: FeatureBundle) -> dict[str, Any]:
    # 사전 공통 예산 검사를 통과한 정본 DTO만 호출한다. 전체 detail/alias/raw/lineage를 남긴다.
    result = bundle.model_dump(mode="json")
    result["feature"].pop("created_at")
    result["feature"].pop("updated_at")
    result["source_record"].pop("fetched_at")
    result["source_record"].pop("imported_at")
    result["source_link"].pop("created_at")
    return result


async def assess_transport_scalar_refresh(
    previous: SourceRecord,
    current: FeatureBundle,
    *,
    previous_normalizer_revision: str | None,
    previous_geo: TransportGeoEvidence | None,
    current_geo: TransportGeoEvidence | None,
) -> TransportScalarEligibility:
    """동일 raw 재관측만 진단한다. changed raw의 Geo 재사용 확대는 별도 계약 전 EX다."""
    if type(previous) is not SourceRecord or type(current) is not FeatureBundle:
        return TransportScalarEligibility(False, "noncanonical_bundle")
    if (
        type(previous_geo) is not TransportGeoEvidence
        or type(current_geo) is not TransportGeoEvidence
    ):
        return TransportScalarEligibility(False, "missing_geo_evidence")
    if not within_place_projection_budget(
        (
            previous,
            current,
            previous_geo.address,
            current_geo.address,
            previous_geo.version_token,
            previous_geo.data_token,
            previous_geo.stamp_digest,
            current_geo.version_token,
            current_geo.data_token,
            current_geo.stamp_digest,
        )
    ):
        return TransportScalarEligibility(False, "invalid_bundle_budget")
    if (
        type(current.feature) is not Feature
        or type(current.source_record) is not SourceRecord
        or type(current.source_link) is not SourceLink
    ):
        return TransportScalarEligibility(False, "noncanonical_bundle")
    if previous_geo != current_geo:
        return TransportScalarEligibility(False, "changed_geo_evidence")
    try:
        expected = _presence(previous.dataset_key)
    except ValueError:
        return TransportScalarEligibility(False, "unsupported_source_domain")
    if previous_normalizer_revision != expected.normalizer_revision:
        return TransportScalarEligibility(False, "unknown_normalizer_revision")
    if current.provider_field_presence != expected:
        return TransportScalarEligibility(False, "unproven_presence")
    if (
        current.feature.kind != FeatureKind.PLACE
        or type(current.feature.detail) is not PlaceDetail
        or current.source_link.source_role != SourceRole.PRIMARY
        or current.file_sources
        or current.geo_attempt is not None
        or current.admin_evidence is not None
    ):
        return TransportScalarEligibility(False, "unsupported_bundle_obligation")
    if (
        current.source_link.source_record_key != current.source_record.source_record_key
        or current.source_link.feature_id != current.feature.feature_id
        or current.feature.detail is None
        or current.feature.detail.feature_id != current.feature.feature_id
    ):
        return TransportScalarEligibility(False, "invalid_current_lineage")
    if any(
        type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None
        for value in (previous.fetched_at, current.source_record.fetched_at)
    ):
        return TransportScalarEligibility(False, "invalid_observation_time")
    if current.source_record.fetched_at < previous.fetched_at:
        return TransportScalarEligibility(False, "older_observation")
    try:
        before = await rebuild_transport_projection(previous, geo=previous_geo)
        rebuilt = await rebuild_transport_projection(current.source_record, geo=current_geo)
    except (ValueError, TypeError, KeyError):
        return TransportScalarEligibility(False, "invalid_typed_projection")
    if _meaning(rebuilt) != _meaning(current):
        return TransportScalarEligibility(False, "current_bundle_not_canonical")
    if before.source_record.raw_data != rebuilt.source_record.raw_data:
        return TransportScalarEligibility(False, "changed_raw_requires_ex")
    if _meaning(before) != _meaning(current):
        return TransportScalarEligibility(False, "unsupported_meaning_change")
    return TransportScalarEligibility(True, "unchanged_reobservation")
