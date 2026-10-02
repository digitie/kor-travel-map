"""``kortravelmap.providers.krairport`` — 공항 메타데이터 → FeatureBundle.

원천: kor-travel-transport ``/v1/service/exports/airports``(ADR-106). transport가
``python-krairport-api`` 번들의 국내 운영 공항 전체(포항경주 KPO 포함)를 ICAO·소재지·좌표와 함께
내고, ``providers.kor_travel_transport.parse_airports``가 이 모듈의 입력 shape로 바꾼다.
Map은 krairport 라이브러리를 직접 import하지 않는다. provider 정체성은 ``kor-travel-transport``,
자연키는 IATA 코드다.

- 공항 → category ``TRANSPORT_AIRPORT``(06050000), place_kind ``airport``. MOIS dedup
  후보 없음.

좌표는 ``Coordinate``(``.lat``/``.lon`` float) 중첩 객체로 온다. 좌표 reverse로 행정코드를 보강한다.

ADR 참조: ADR-009 / ADR-012 / ADR-019 / ADR-098 / ADR-106
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from kortravelmap.category import (
    PlaceCategoryCode,
    mapbox_maki_icon_or_none,
)
from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
)
from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
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
from kortravelmap.geocoding import ReverseGeocoder, cached_reverse_geocoder
from kortravelmap.providers.kor_travel_transport import (
    DATASET_KEY_AIRPORTS,
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
)

__all__ = [
    "AirportMetadataItem",
    "airports_to_bundles",
    "AIRPORT_CATEGORY",
    "AIRPORT_MARKER_COLOR",
]

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
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_AIRPORTS,
        source_entity_type=_AIRPORT_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=AIRPORT_CATEGORY,
        source_type=f"{KOR_TRAVEL_TRANSPORT_PROVIDER_NAME}:{DATASET_KEY_AIRPORTS}",
        source_natural_key=natural_key,
    )
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=natural_key,
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
        provider=normalize_provider_name(KOR_TRAVEL_TRANSPORT_PROVIDER_NAME),
        dataset_key=DATASET_KEY_AIRPORTS,
        source_entity_type=_AIRPORT_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
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
