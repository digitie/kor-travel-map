"""``kortravelmap.providers.khoa`` — 해양수산부 해수욕장정보 → FeatureBundle.

``python-khoa-api``(``import khoa``)의 해수욕장정보(``OceanBeachInfo``)를 place
``FeatureBundle``로 정규화한다(ADR-034 보조 dataset). provider client/model은 별도
라이브러리가 제공(ADR-006 — 본 모듈은 변환 순수 함수).

- 해수욕장 → category ``TOURISM_NATURE_BEACH``(01050100, 전용 해수욕장 코드 — DA-D-07),
  place_kind ``beach``. MOIS PROMOTED 슬러그에 해수욕장이 없어 dedup 후보 없음.

provider 모델은 road/jibun 주소 없이 ``sido_name``/``gugun_name`` 행정명 + WGS84
``latitude``/``longitude``만 준다. feature_id가 bjd_code에 의존하므로(ADR-009) 변환은
**async**이고 좌표 reverse로 행정코드를 보강한다(주소 geocode 경로는 도로명이 없어 미사용).

ADR 참조: ADR-006 / ADR-009 / ADR-012 / ADR-019 / ADR-024 / ADR-034
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

__all__ = [
    "OceanBeachInfoItem",
    "beaches_to_bundles",
    "KHOA_PROVIDER_NAME",
    "DATASET_KEY_BEACHES",
    "BEACH_CATEGORY",
    "BEACH_MARKER_COLOR",
]

KHOA_PROVIDER_NAME: Final[str] = "python-khoa-api"
"""canonical provider name (ADR-024)."""

DATASET_KEY_BEACHES: Final[str] = "khoa_beaches"
_BEACH_ENTITY_TYPE: Final[str] = "beach"
BEACH_CATEGORY: Final[str] = PlaceCategoryCode.TOURISM_NATURE_BEACH.value
"""``Feature.category`` — 해수욕장(자연명소 > 해수욕장) 01050100.

DA-D-07(2026-06-16): 전용 해수욕장 코드 ``TOURISM_NATURE_BEACH``(01050100)로 정렬.
이전 ``TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND``(01020300, 해안/섬 일반)은 오분류였다.
둘 다 maki ``beach``라 마커는 무변, category 값만 정밀화(feature_id에 category가 박혀
재import 시 1회 re-key)."""
BEACH_PLACE_KIND: Final[str] = "beach"
BEACH_MARKER_COLOR: Final[str] = "P-07"
_DEFAULT_BEACH_ICON: Final[str] = "beach"


@runtime_checkable
class OceanBeachInfoItem(Protocol):
    """해양수산부 해수욕장정보 1 row 입력 shape (``OceanBeachInfo``)."""

    name: str
    """해수욕장명 (``Feature.name``)."""

    sido_name: str
    """시도명 (행정명/자연키 파생)."""

    gugun_name: str | None
    """시군구명 (행정명/자연키 파생)."""

    latitude: float | None
    longitude: float | None

    beach_kind: str | None
    """해수욕장 종류 (``facility_info``)."""

    image_url: str | None
    """대표 이미지 URL (``facility_info``)."""

    raw: Any


async def _beach_to_bundle(
    item: OceanBeachInfoItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    name = item.name or ""
    coord: Coordinate | None
    if item.latitude is not None and item.longitude is not None:
        coord = Coordinate(lon=Decimal(str(item.longitude)), lat=Decimal(str(item.latitude)))
    else:
        coord = None

    admin_text = (
        " ".join(
            part
            for part in [
                normalize_korean_text(item.sido_name),
                normalize_korean_text(item.gugun_name),
            ]
            if part
        )
        or None
    )

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
        admin=(geo.admin if geo is not None else None) or admin_text,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=(geo.sido_name if geo is not None else None)
        or normalize_korean_text(item.sido_name),
        sigungu_name=(geo.sigungu_name if geo is not None else None)
        or normalize_korean_text(item.gugun_name),
    )

    natural_key = "::".join(
        [
            normalize_korean_text(name) or name,
            normalize_korean_text(item.sido_name) or (item.sido_name or ""),
            normalize_korean_text(item.gugun_name) or (item.gugun_name or ""),
        ]
    )
    raw_data: dict[str, Any] = {
        "name": item.name,
        "sido_name": item.sido_name,
        "gugun_name": item.gugun_name,
        "beach_kind": item.beach_kind,
        "image_url": item.image_url,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "longitude": str(item.longitude) if item.longitude is not None else None,
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KHOA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_BEACHES,
        source_entity_type=_BEACH_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=BEACH_CATEGORY,
        source_type=f"{KHOA_PROVIDER_NAME}:{DATASET_KEY_BEACHES}",
        source_natural_key=natural_key,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=normalize_korean_text(name) or name,
        coord=coord,
        address=address,
        category=BEACH_CATEGORY,
        marker_icon=mapbox_maki_icon_or_none(BEACH_CATEGORY) or _DEFAULT_BEACH_ICON,
        marker_color=BEACH_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=BEACH_PLACE_KIND,
            facility_info={
                k: v
                for k, v in {
                    "beach_kind": normalize_korean_text(item.beach_kind),
                    "image_url": item.image_url,
                }.items()
                if v is not None
            },
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(KHOA_PROVIDER_NAME),
        dataset_key=DATASET_KEY_BEACHES,
        source_entity_type=_BEACH_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=item.name,
        raw_address=admin_text,
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


async def beaches_to_bundles(
    items: Iterable[OceanBeachInfoItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """해양수산부 해수욕장정보 items → ``list[FeatureBundle]`` (place, category 01050100).

    provider 모델에 도로명 주소가 없어 좌표 reverse만으로 bjd를 보강한다. 안정 식별자가
    없어 ``name::sido::gugun`` 파생키(ADR-009 ``::``)를 쓴다.
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    return [
        await _beach_to_bundle(item, fetched_at=fetched_at, reverse_geocoder=geocoder)
        for item in items
    ]
