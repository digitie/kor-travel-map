"""``krtour.map.providers.mcst`` — 문체부(KCISA/ODCloud) → place FeatureBundle.

``python-mcst-api``(``import mcst``)의 두 표면을 place ``FeatureBundle``로
정규화한다(T-220a, 계획 정본 `docs/reports/kma-mcst-provider-plan-2026-06-11.md`
§3). provider client/model은 별도 라이브러리가 제공(ADR-006 — 본 모듈은 변환
순수 함수).

- **KCISA 14 dataset**: 단일 스키마를 공유하는 ``CultureRecord``(name/address/
  tel/url/lon/lat/category + raw) — slug 메타표 ``MCST_CULTURE_DATASETS`` 한
  곳에서 dataset_key/category/place_kind를 관리하고 변환 함수는 1개로 커버.
- **ODCloud 도서관 2 dataset**: ``RawRecord``(한국어 CSV 컬럼 dict) — 컬럼명
  방언을 관대하게 조회해 같은 bundle 모양으로 정규화.

category는 전부 **기존 코드**로 매핑(실측 결과 Tier3/4 신설 불요 — 계획 §3.2
표의 "신설 검토" 항목은 기존 Tier1/2 대표 코드로 흡수, place_kind가 세부 구분).
marker는 문화 계열 1색 ``P-12``(krforest P-05 단일색 패턴).

안정 식별자가 없어 자연키는 ``name::address``(정규화 후, ADR-009 ``::``).
좌표가 있으면 reverse로 bjd를 보강하고(ADR-046), 좌표가 없으면 provider 주소
문자열만 보존한다(주소 단서가 있어 Dagster 주소 검증 통과 — 좌표/주소 둘 다
없거나 이름이 없는 row는 식별 불가라 건너뛴다).

ADR 참조: ADR-006 / ADR-009 / ADR-012 / ADR-019 / ADR-024 / ADR-044 / ADR-046
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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
    "MCST_PROVIDER_NAME",
    "MCST_MARKER_COLOR",
    "MCST_CULTURE_DATASETS",
    "MCST_LIBRARY_DATASETS",
    "McstDatasetSpec",
    "McstCultureItem",
    "culture_records_to_bundles",
    "library_records_to_bundles",
]

MCST_PROVIDER_NAME: Final[str] = "python-mcst-api"
"""canonical provider name (ADR-024)."""

MCST_MARKER_COLOR: Final[str] = "P-12"
"""문화 계열 단일 marker color (계획 §3.1 — 미사용 색 중 확정)."""

_DEFAULT_MCST_ICON: Final[str] = "marker"


@dataclass(frozen=True, slots=True)
class McstDatasetSpec:
    """MCST dataset 1종의 변환 메타 (slug 메타표 항목)."""

    slug: str
    """python-mcst-api 카탈로그 slug (client 메서드명과 동일)."""

    dataset_key: str
    """provider_sync dataset_key — ``mcst_<slug>``."""

    category: str
    """``Feature.category`` (기존 ``PlaceCategoryCode`` 값)."""

    place_kind: str
    """``PlaceDetail.place_kind`` — dataset 세부 구분."""

    entity_type: str
    """``SourceRecord.source_entity_type``."""

    label: str
    """한글 라벨 (문서/로그용)."""


def _culture_spec(
    slug: str, category: PlaceCategoryCode, place_kind: str, label: str
) -> McstDatasetSpec:
    return McstDatasetSpec(
        slug=slug,
        dataset_key=f"mcst_{slug}",
        category=category.value,
        place_kind=place_kind,
        entity_type="culture_place",
        label=label,
    )


MCST_CULTURE_DATASETS: Final[dict[str, McstDatasetSpec]] = {
    spec.slug: spec
    for spec in (
        _culture_spec(
            "media_famous_places",
            PlaceCategoryCode.TOURISM,
            "media_famous_place",
            "미디어콘텐츠 영상 촬영지",
        ),
        _culture_spec(
            "barrier_free_places",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "barrier_free_place",
            "무장애 관광지",
        ),
        _culture_spec(
            "pet_friendly_culture_facilities",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "pet_friendly_culture_facility",
            "반려동물 동반 가능 문화시설",
        ),
        _culture_spec(
            "leisure_activity_facilities",
            PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS,
            "leisure_activity_facility",
            "레저활동 시설",
        ),
        _culture_spec(
            "leisure_camping_facilities",
            PlaceCategoryCode.LODGING_CAMPGROUND,
            "leisure_camping_facility",
            "레저 캠핑 시설",
        ),
        _culture_spec(
            "leisure_classes",
            PlaceCategoryCode.TOURISM_ACTIVITY,
            "leisure_class",
            "레저 클래스/강습",
        ),
        _culture_spec(
            "family_infant_culture_facilities",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "family_culture_facility",
            "가족/영유아 동반 문화시설",
        ),
        _culture_spec(
            "multilingual_guide_culture_facilities",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "multilingual_culture_facility",
            "다국어 안내 문화시설",
        ),
        _culture_spec(
            "world_restaurants",
            PlaceCategoryCode.FOOD_RESTAURANT,
            "world_restaurant",
            "세계음식 음식점",
        ),
        _culture_spec(
            "small_theaters",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL,
            "small_theater",
            "소공연장",
        ),
        _culture_spec(
            "meeting_seminar_facilities",
            PlaceCategoryCode.CONVENIENCE,
            "meeting_facility",
            "회의/세미나 시설",
        ),
        _culture_spec(
            "independent_bookstores",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "independent_bookstore",
            "독립서점",
        ),
        _culture_spec(
            "cafe_bookstores",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "cafe_bookstore",
            "북카페",
        ),
        _culture_spec(
            "recommended_travel_destinations",
            PlaceCategoryCode.TOURISM,
            "recommended_destination",
            "추천 여행지",
        ),
    )
}
"""KCISA 공통 ``CultureRecord`` 14 dataset slug 메타표 (계획 §3.2 — 빠짐없이)."""

MCST_LIBRARY_DATASETS: Final[dict[str, McstDatasetSpec]] = {
    spec.slug: spec
    for spec in (
        McstDatasetSpec(
            slug="public_libraries",
            dataset_key="mcst_public_libraries",
            category=PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_LIBRARY.value,
            place_kind="public_library",
            entity_type="library",
            label="전국 공공도서관",
        ),
        McstDatasetSpec(
            slug="small_libraries",
            dataset_key="mcst_small_libraries",
            category=PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_LIBRARY.value,
            place_kind="small_library",
            entity_type="library",
            label="작은도서관",
        ),
    )
}
"""ODCloud 도서관 2 dataset slug 메타표 (위치/운영 정보만 — 장서 제외)."""


@runtime_checkable
class McstCultureItem(Protocol):
    """``python-mcst-api`` ``CultureRecord``의 입력 shape."""

    name: str | None
    address: str | None
    tel: str | None
    url: str | None
    longitude: float | None
    latitude: float | None
    category: str | None
    """원천 분류 텍스트 (krtour category 아님 — ``facility_info``에 보존)."""

    raw: Mapping[str, Any]


def _coord_or_none(lon: float | None, lat: float | None) -> Coordinate | None:
    if lon is None or lat is None:
        return None
    return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))


async def _resolve_address(
    coord: Coordinate | None,
    *,
    fallback_admin: str | None,
    fallback_sido: str | None = None,
    fallback_sigungu: str | None = None,
    reverse_geocoder: ReverseGeocoder | None,
) -> Address:
    """좌표가 있으면 reverse로 bjd 보강, 없으면 provider 텍스트만 보존."""
    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    bjd_code = geo.bjd_code if geo is not None else None
    return Address(
        admin=(geo.admin if geo is not None else None) or fallback_admin,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=(
            (geo.sigungu_code if geo is not None else None)
            or extract_sigungu_code(bjd_code)
        ),
        sido_code=(
            (geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code)
        ),
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=(geo.sido_name if geo is not None else None) or fallback_sido,
        sigungu_name=(geo.sigungu_name if geo is not None else None)
        or fallback_sigungu,
    )


def _build_bundle(
    *,
    spec: McstDatasetSpec,
    name: str,
    coord: Coordinate | None,
    address: Address,
    raw_address: str | None,
    facility_info: dict[str, Any],
    raw_data: dict[str, Any],
    fetched_at: datetime,
) -> FeatureBundle:
    natural_key = "::".join(
        [normalize_korean_text(name) or name, raw_address or ""]
    )
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=MCST_PROVIDER_NAME,
        dataset_key=spec.dataset_key,
        source_entity_type=spec.entity_type,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=address.bjd_code,
        kind=FeatureKind.PLACE.value,
        category=spec.category,
        source_type=f"{MCST_PROVIDER_NAME}:{spec.dataset_key}",
        source_natural_key=natural_key,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=normalize_korean_text(name) or name,
        coord=coord,
        address=address,
        category=spec.category,
        marker_icon=mapbox_maki_icon_or_none(spec.category) or _DEFAULT_MCST_ICON,
        marker_color=MCST_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=spec.place_kind,
            facility_info={k: v for k, v in facility_info.items() if v is not None},
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(MCST_PROVIDER_NAME),
        dataset_key=spec.dataset_key,
        source_entity_type=spec.entity_type,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=name,
        raw_address=raw_address,
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


async def culture_records_to_bundles(
    items: Iterable[McstCultureItem],
    *,
    slug: str,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """KCISA ``CultureRecord`` items → place ``FeatureBundle`` (slug 메타표 기반).

    ``slug``는 ``MCST_CULTURE_DATASETS`` 키여야 한다(아니면 ``KeyError`` — 호출
    오타가 조용히 빈 dataset이 되지 않게). 이름이 없거나 좌표·주소가 모두 없는
    row는 식별/위치 단서가 없어 건너뛴다.
    """
    spec = MCST_CULTURE_DATASETS[slug]
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for item in items:
        name = normalize_korean_text(item.name)
        raw_address = normalize_korean_text(item.address)
        coord = _coord_or_none(item.longitude, item.latitude)
        if name is None or (coord is None and raw_address is None):
            continue
        address = await _resolve_address(
            coord,
            fallback_admin=raw_address,
            reverse_geocoder=geocoder,
        )
        raw_data: dict[str, Any] = {
            "name": item.name,
            "address": item.address,
            "tel": item.tel,
            "url": item.url,
            "longitude": str(item.longitude) if item.longitude is not None else None,
            "latitude": str(item.latitude) if item.latitude is not None else None,
            "category": item.category,
        }
        bundles.append(
            _build_bundle(
                spec=spec,
                name=name,
                coord=coord,
                address=address,
                raw_address=raw_address,
                facility_info={
                    "source_category": normalize_korean_text(item.category),
                    "tel": normalize_korean_text(item.tel),
                    "url": item.url,
                },
                raw_data=raw_data,
                fetched_at=fetched_at,
            )
        )
    return bundles


# ODCloud 도서관 RawRecord(한국어 CSV 컬럼)의 방언 후보 — mcst lib
# ``CultureRecord.from_row``의 관대한 조회 패턴을 미러한다(ADR-044).
_LIBRARY_NAME_KEYS: Final[tuple[str, ...]] = ("도서관명", "작은도서관명", "시설명")
_LIBRARY_ADDRESS_KEYS: Final[tuple[str, ...]] = (
    "소재지도로명주소",
    "도로명주소",
    "주소",
    "소재지지번주소",
    "소재지",
)
_LIBRARY_LON_KEYS: Final[tuple[str, ...]] = ("경도",)
_LIBRARY_LAT_KEYS: Final[tuple[str, ...]] = ("위도",)
_LIBRARY_TEL_KEYS: Final[tuple[str, ...]] = ("전화번호", "도서관전화번호", "연락처")
_LIBRARY_URL_KEYS: Final[tuple[str, ...]] = ("홈페이지주소", "홈페이지", "홈페이지 주소")
_LIBRARY_TYPE_KEYS: Final[tuple[str, ...]] = ("도서관유형", "도서관구분", "운영형태")
_LIBRARY_SIDO_KEYS: Final[tuple[str, ...]] = ("시도명", "시도")
_LIBRARY_SIGUNGU_KEYS: Final[tuple[str, ...]] = ("시군구명", "시군구")


def _row_text(row: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _row_float(row: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    text = _row_text(row, keys)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


async def library_records_to_bundles(
    rows: Iterable[Mapping[str, Any]],
    *,
    slug: str,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """ODCloud 도서관 ``RawRecord`` rows → place ``FeatureBundle``.

    ``slug``는 ``MCST_LIBRARY_DATASETS`` 키여야 한다. 컬럼명 방언은
    ``_LIBRARY_*_KEYS`` 후보로 관대하게 조회하고, 이름이 없거나 좌표·주소가
    모두 없는 row는 건너뛴다.
    """
    spec = MCST_LIBRARY_DATASETS[slug]
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for row in rows:
        name = normalize_korean_text(_row_text(row, _LIBRARY_NAME_KEYS))
        raw_address = normalize_korean_text(_row_text(row, _LIBRARY_ADDRESS_KEYS))
        coord = _coord_or_none(
            _row_float(row, _LIBRARY_LON_KEYS), _row_float(row, _LIBRARY_LAT_KEYS)
        )
        if name is None or (coord is None and raw_address is None):
            continue
        address = await _resolve_address(
            coord,
            fallback_admin=raw_address,
            fallback_sido=normalize_korean_text(_row_text(row, _LIBRARY_SIDO_KEYS)),
            fallback_sigungu=normalize_korean_text(
                _row_text(row, _LIBRARY_SIGUNGU_KEYS)
            ),
            reverse_geocoder=geocoder,
        )
        raw_data = {str(k): v for k, v in row.items()}
        bundles.append(
            _build_bundle(
                spec=spec,
                name=name,
                coord=coord,
                address=address,
                raw_address=raw_address,
                facility_info={
                    "library_type": normalize_korean_text(
                        _row_text(row, _LIBRARY_TYPE_KEYS)
                    ),
                    "tel": normalize_korean_text(_row_text(row, _LIBRARY_TEL_KEYS)),
                    "url": _row_text(row, _LIBRARY_URL_KEYS),
                },
                raw_data=raw_data,
                fetched_at=fetched_at,
            )
        )
    return bundles
