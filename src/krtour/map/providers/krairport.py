"""``krtour.map.providers.krairport`` — 공항 메타데이터 → FeatureBundle.

``python-krairport-api``(``import krairport``)의 번들 공항 메타데이터
(``AirportMetadata``)를 place ``FeatureBundle``로 정규화한다(ADR-034 보조). 공항
메타데이터 목록(``client.airports()``)은 **번들 정적 데이터**라 credential 없이 쓸 수
있다(knps와 동일 keyless).

- 공항 → category ``TRANSPORT_AIRPORT``(06050000), place_kind ``airport``. MOIS dedup
  후보 없음.

좌표는 provider ``Coordinate``(``.lat``/``.lon`` float) 중첩 객체로 온다. feature_id가
bjd_code에 의존하므로(ADR-009) 변환은 async이고 좌표 reverse로 행정코드를 보강한다.

ADR 참조: ADR-006 / ADR-009 / ADR-012 / ADR-019 / ADR-024 / ADR-034
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from krtour.map.category import (
    PlaceCategoryCode,
    mapbox_maki_icon_or_none,
)
from krtour.map.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
)
from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from krtour.map.geocoding import ReverseGeocoder, cached_reverse_geocoder

__all__ = [
    "AirportMetadataItem",
    "airports_to_bundles",
    "KRAIRPORT_PROVIDER_NAME",
    "DATASET_KEY_AIRPORTS",
    "AIRPORT_CATEGORY",
    "AIRPORT_MARKER_COLOR",
]

KRAIRPORT_PROVIDER_NAME: Final[str] = "python-krairport-api"
"""canonical provider name (ADR-024)."""

DATASET_KEY_AIRPORTS: Final[str] = "krairport_airports"
_AIRPORT_ENTITY_TYPE: Final[str] = "airport"
AIRPORT_CATEGORY: Final[str] = PlaceCategoryCode.TRANSPORT_AIRPORT.value
"""``Feature.category`` — 공항 06050000."""
AIRPORT_PLACE_KIND: Final[str] = "airport"
AIRPORT_MARKER_COLOR: Final[str] = "P-10"
_DEFAULT_AIRPORT_ICON: Final[str] = "airport"


@runtime_checkable
class AirportMetadataItem(Protocol):
    """공항 메타데이터 1건 입력 shape (``AirportMetadata``)."""

    code: str
    """공항 코드(IATA, 예: ``"ICN"``) — 안정 식별자(``source_entity_id``)."""

    name_korean: str | None
    """공항 한글명 (``Feature.name`` 우선)."""

    name_english: str
    """공항 영문명 (한글명 없을 때 ``Feature.name``)."""

    icao_code: str | None
    municipality: str | None
    """소재 도시명 (행정명/raw)."""

    coordinate: Any
    """provider ``Coordinate``(``.lat``/``.lon`` float) 또는 None."""


def _coord_of(coordinate: Any) -> Coordinate | None:
    """provider ``Coordinate``(중첩 객체) → krtour ``Coordinate``(Decimal). None 안전."""
    if coordinate is None:
        return None
    lat = getattr(coordinate, "lat", None)
    lon = getattr(coordinate, "lon", None)
    if lat is None or lon is None:
        return None
    return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))


async def _airport_to_bundle(
    item: AirportMetadataItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    name = normalize_korean_text(item.name_korean) or item.name_english or item.code
    coord = _coord_of(item.coordinate)
    municipality = normalize_korean_text(item.municipality)

    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    bjd_code = geo.bjd_code if geo is not None else None
    sigungu_code = (
        (geo.sigungu_code if geo is not None else None)
        or extract_sigungu_code(bjd_code)
    )
    sido_code = (
        (geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code)
    )
    address = Address(
        admin=(geo.admin if geo is not None else None) or municipality,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )

    natural_key = item.code
    raw_data: dict[str, Any] = {
        "code": item.code,
        "name_korean": item.name_korean,
        "name_english": item.name_english,
        "icao_code": item.icao_code,
        "municipality": item.municipality,
        "latitude": str(coord.lat) if coord is not None else None,
        "longitude": str(coord.lon) if coord is not None else None,
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KRAIRPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_AIRPORTS,
        source_entity_type=_AIRPORT_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=AIRPORT_CATEGORY,
        source_type=f"{KRAIRPORT_PROVIDER_NAME}:{DATASET_KEY_AIRPORTS}",
        source_natural_key=natural_key,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coord,
        address=address,
        category=AIRPORT_CATEGORY,
        marker_icon=mapbox_maki_icon_or_none(AIRPORT_CATEGORY) or _DEFAULT_AIRPORT_ICON,
        marker_color=AIRPORT_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=AIRPORT_PLACE_KIND,
            facility_info={
                k: v
                for k, v in {
                    "icao_code": item.icao_code,
                    "name_english": item.name_english,
                }.items()
                if v is not None
            },
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(KRAIRPORT_PROVIDER_NAME),
        dataset_key=DATASET_KEY_AIRPORTS,
        source_entity_type=_AIRPORT_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=item.name_korean or item.name_english,
        raw_address=municipality,
        raw_longitude=coord.lon if coord is not None else None,
        raw_latitude=coord.lat if coord is not None else None,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature, source_record=source_record, source_link=source_link
    )


async def airports_to_bundles(
    items: Iterable[AirportMetadataItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """공항 메타데이터 items → ``list[FeatureBundle]`` (place, category 06050000).

    안정키는 공항 코드(``code``, IATA). 좌표는 provider ``Coordinate`` 중첩 객체에서
    추출하고, 도로명 주소가 없어 좌표 reverse로 bjd를 보강한다.
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    return [
        await _airport_to_bundle(item, fetched_at=fetched_at, reverse_geocoder=geocoder)
        for item in items
    ]
