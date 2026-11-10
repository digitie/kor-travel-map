"""``kortravelmap.providers.mois`` — MOIS 지방행정 인허가(LOCALDATA) 변환.

행정안전부 LOCALDATA 인허가 데이터(``python-mois-api``, ``import mois``)를 본
라이브러리의 ``FeatureBundle``(place)로 정규화한다. ADR-034 9단계의 ⑦ provider.

범위 (Sprint 4a 변환 코어)
--------------------------
- ``PlaceRecord`` (mois가 source DB 적재용으로 정규화한 Pydantic 모델)의
  **structural Protocol**(``MoisLicensePlaceRecord``)만 입력으로 받아 place
  ``FeatureBundle``로 변환한다. 적재(DB write)·dedup·CLI mutex는 후속 PR.
- 195 업종 중 **PROMOTED 42종**만 feature로 승격, EXCLUDED 및 미매핑 슬러그는
  변환하지 않고 skip (영업중 row만). ``docs/etl/mois-feature-etl.md`` §4/§6/§8 사양.

설계 — ADR-006 (provider wrapper 금지) 정신 동일
------------------------------------------------
- ``mois``를 **런타임 import 하지 않는다**. ``PlaceRecord`` shape를 모사한
  ``@runtime_checkable`` Protocol만 정의 (ADR-006/044 — 정합성 1차 책임은 mois).
- 좌표는 **이미 WGS84** (``record.lon``/``record.lat``). EPSG:5174 → WGS84 변환은
  mois가 수행하므로 본 모듈은 좌표계 변환을 하지 않는다 (ADR-012/044). 원본
  EPSG:5174 ``source_x``/``source_y``는 payload에 보존만.
- 변환 함수는 ``async`` + geocoder 주입 — ``legal_dong_code``(mois 직접 제공)를
  1차 bjd_code로 쓰고, 없으면 좌표 역지오코딩, 그래도 없으면 주소 geocode로
  보강한다 (ADR-009 — feature_id 계산 전에 bjd_code 확정해 'global' bucket을
  벗어남).

ADR 참조
--------
- ADR-002 — 순수 함수 + async-only client
- ADR-006 — provider 직접 사용 (wrapper class 금지), 구조 Protocol 입력
- ADR-009 — ``make_feature_id`` / ``make_source_record_key`` / ``make_payload_hash``
- ADR-012 — ``Coordinate``는 WGS84 (lon/lat)
- ADR-024 — canonical provider name ``python-mois-api``
- ADR-044 — mois 데이터 정합성 1차 책임은 mois (응답 신뢰·미러)
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from kortravelmap.category import get_category, is_known_category_code
from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_bjd_code,
    normalize_korean_text,
    normalize_phone_number,
)
from kortravelmap.core.business_name import BusinessName, normalize_business_name
from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    Address,
    AdminEvidence,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.dto.geo_dataset import GeoAttemptEvidence
from kortravelmap.geocoding import (
    AddressGeocoder,
    AddressResolver,
    ReverseGeocoder,
    address_has_location_number,
    cached_address_geocoder,
    cached_address_resolver,
    cached_reverse_geocoder,
    geocode_missing_coordinate,
)

__all__ = [
    "COORD_SOURCE_GEOCODE",
    "LICENSE_DEDUP_FAMILY",
    "LicenseShadowIndex",
    "MOIS_COORD_RULE",
    "IN_BUILDING_FACILITY_SLUGS",
    "license_business_name",
    "license_needs_forward_geocode",
    "MOIS_SLUG_LOAD_GROUPS",
    "MOIS_SLUG_LOAD_ORDER",
    "MoisLicensePlaceRecord",
    "ShadowedLicenseRecord",
    "license_record_is_promotable",
    "order_service_slugs",
    "license_record_to_bundle",
    "license_records_to_bundles",
    "resolve_license_category",
    "resolve_license_place_kind",
    "license_source_entity_id",
    "license_record_payload_hash",
    "license_reverse_geocode_coordinate",
    "PROVIDER_NAME",
    "DATASET_KEY_BULK",
    "DATASET_KEY_HISTORY",
    "DATASET_KEY_CLOSED",
    "DATASET_KEY_DETAIL",
    "PROMOTED_SERVICE_SLUGS",
    "EXCLUDED_SERVICE_SLUGS",
    "PROMOTED_CATEGORY_BY_SLUG",
    "PROMOTED_PLACE_KIND_BY_SLUG",
    "MOIS_MARKER_COLOR",
    "MOIS_DEFAULT_MARKER_ICON",
    "MOIS_SOURCE_SYNC_COVERAGE_TAG",
    "MOIS_SOURCE_SYNC_FULL_COVERAGE",
]


PROVIDER_NAME: Final[str] = "python-mois-api"
"""canonical provider name (ADR-024)."""

DATASET_KEY_BULK: Final[str] = "mois_license_features_bulk"
DATASET_KEY_HISTORY: Final[str] = "mois_license_features_history"
DATASET_KEY_CLOSED: Final[str] = "mois_license_features_closed"
DATASET_KEY_DETAIL: Final[str] = "mois_license_detail"

_LICENSE_ENTITY_TYPE: Final[str] = "license_place"

MOIS_MARKER_COLOR: Final[str] = "P-01"
"""MOIS 인허가 place marker color. 인허가 place는 범용 장소 → 미사용 팔레트 P-01."""

MOIS_DEFAULT_MARKER_ICON: Final[str] = "marker"
"""category maki 미상 시 fallback marker icon."""

MOIS_SOURCE_SYNC_COVERAGE_TAG: Final[str] = "kor_travel_map.mois_source_sync.coverage"
"""Dagster MOIS Phase A run이 성공적으로 실행한 범위 tag."""

# source_natural_key 구분자. make_feature_id/make_source_record_key는 구성요소
# 내부 ``|``를 금지하므로 ``::`` 사용.
_NATURAL_KEY_SEP: Final[str] = "::"


# -- 슬러그 분류 (docs/etl/mois-feature-etl.md §4) -------------------------------

PROMOTED_SERVICE_SLUGS: Final[frozenset[str]] = frozenset(
    {
        # 식음 (6)
        "general_restaurants",
        "rest_cafes",
        "tourist_restaurants",
        "tourist_entertainment_restaurants",
        "foreigners_entertainment_restaurants",
        "bakeries",
        # 숙박 (8)
        "tourist_accommodations",
        "lodgings",
        "tourist_pensions",
        "rural_homestays",
        "foreigner_city_homestays",
        "general_campgrounds",
        "auto_campgrounds",
        "hanok_experience",
        # 관광/문화 (9)
        "tourism_businesses",
        "tourist_cruises",
        "city_tour_businesses",
        "tourist_railways",
        "museums_and_art_galleries",
        "performance_halls",
        "tourist_performance_halls",
        "tourist_theater_entertainment",
        "traditional_temples",
        # 테마파크/휴양 (5)
        "amusement_facilities_other",
        "general_amusement_facilities",
        "comprehensive_amusement_facilities",
        "special_resorts",
        "comprehensive_resorts",
        # MICE (2)
        "international_convention_facilities",
        "international_convention_planners",
        # 스포츠/레저 (9)
        "golf_courses",
        "ski_resorts",
        "yacht_marinas",
        "horse_riding",
        "sledding",
        "swimming_pools",
        "ice_rinks",
        "comprehensive_sports_facilities",
        "registered_sports_facilities",
        # 쇼핑/도시여가 (3)
        "large_scale_retail_stores",
        "movie_theaters",
        "public_baths",
    }
)
"""feature로 승격하는 42 업종 슬러그 (docs §4.1). 모두 mois.catalog 195건 일치."""

MOIS_SOURCE_SYNC_FULL_COVERAGE: Final[str] = (
    "promoted-national-sha256:"
    + hashlib.sha256("\n".join(sorted(PROMOTED_SERVICE_SLUGS)).encode("utf-8")).hexdigest()
)
"""현재 PROMOTED 전체 업종·전국 동기화를 증명하는 content-addressed coverage 값."""

EXCLUDED_SERVICE_SLUGS: Final[frozenset[str]] = frozenset(
    {
        # 미용/세탁 (4)
        "beauty_salons",
        "barber_shops",
        "laundries",
        "medical_laundry",
        # 주유/LPG (3) — OpiNet이 더 정확
        "oil_retailers",
        "petroleum_alt_fuel_retailers",
        "lpg_equipment_manufacturers",
        # 동물 (4)
        "animal_hospitals",
        "animal_pharmacies",
        "pet_grooming",
        "animal_boarding",
        # 오락/도시여가 (8)
        "billiard_halls",
        "video_viewing_rooms",
        "karaoke_rooms",
        "dance_halls",
        "dance_academies",
        "pc_bangs",
        "film_screenings",
        "golf_practice_ranges",
        # 의료/안경 (2)
        "optical_shops",
        "over_the_counter_medicine_stores",
    }
)
"""명시적으로 제외하는 슬러그 (docs §4.2). 그 외 미매핑 슬러그도 변환 skip."""


# -- category / place_kind 매핑 (docs §6.1, 31 코드 _definitions 검증) -------

PROMOTED_CATEGORY_BY_SLUG: Final[Mapping[str, str]] = {
    # 식음
    "general_restaurants": "02010100",
    "rest_cafes": "02020100",
    "tourist_restaurants": "02010000",
    "tourist_entertainment_restaurants": "02010800",
    "foreigners_entertainment_restaurants": "02010800",
    "bakeries": "02011000",
    # 숙박
    "tourist_accommodations": "03010100",
    "lodgings": "03040100",
    "tourist_pensions": "03050100",
    "rural_homestays": "03050200",
    "foreigner_city_homestays": "03070100",
    "general_campgrounds": "03060000",
    "auto_campgrounds": "03060100",
    "hanok_experience": "03070200",
    # 관광/문화
    "tourism_businesses": "01000000",
    "tourist_cruises": "01080300",
    "city_tour_businesses": "01080000",
    "tourist_railways": "01080200",
    "museums_and_art_galleries": "01040000",
    "performance_halls": "01040301",
    "tourist_performance_halls": "01040302",
    "tourist_theater_entertainment": "01040302",
    "traditional_temples": "01070100",
    # 테마파크/휴양
    "amusement_facilities_other": "01010400",
    "general_amusement_facilities": "01010102",
    "comprehensive_amusement_facilities": "01010101",
    "special_resorts": "03020100",
    "comprehensive_resorts": "03020200",
    # MICE
    "international_convention_facilities": "01000000",
    "international_convention_planners": "01000000",
    # 스포츠/레저
    "golf_courses": "01080100",
    "ski_resorts": "01080400",
    "yacht_marinas": "01080400",
    "horse_riding": "01080400",
    "sledding": "01080400",
    "swimming_pools": "01080400",
    "ice_rinks": "01080400",
    "comprehensive_sports_facilities": "01080400",
    "registered_sports_facilities": "01080400",
    # 쇼핑/도시여가
    "large_scale_retail_stores": "05050000",
    "movie_theaters": "01040400",
    "public_baths": "04020100",
}
"""PROMOTED 슬러그 → PlaceCategoryCode value (docs §6.1)."""

PROMOTED_PLACE_KIND_BY_SLUG: Final[Mapping[str, str]] = {
    "general_restaurants": "restaurant",
    "rest_cafes": "cafe",
    "tourist_restaurants": "restaurant_tourist",
    "tourist_entertainment_restaurants": "restaurant_entertainment_tourist",
    "foreigners_entertainment_restaurants": "restaurant_entertainment_foreigner",
    "bakeries": "bakery",
    "tourist_accommodations": "lodging_tourist_hotel",
    "lodgings": "lodging_general",
    "tourist_pensions": "lodging_pension",
    "rural_homestays": "lodging_rural_homestay",
    "foreigner_city_homestays": "lodging_city_homestay_foreigner",
    "general_campgrounds": "lodging_campground_general",
    "auto_campgrounds": "lodging_campground_auto",
    "hanok_experience": "lodging_hanok",
    "tourism_businesses": "tourism_business_office",
    "tourist_cruises": "tourism_cruise",
    "city_tour_businesses": "tourism_city_tour",
    "tourist_railways": "tourism_railway",
    "museums_and_art_galleries": "museum_art_gallery",
    "performance_halls": "performance_hall",
    "tourist_performance_halls": "performance_hall_tourist",
    "tourist_theater_entertainment": "theater_tourist_entertainment",
    "traditional_temples": "temple_traditional",
    "amusement_facilities_other": "theme_park_other",
    "general_amusement_facilities": "theme_park_general",
    "comprehensive_amusement_facilities": "theme_park_comprehensive",
    "special_resorts": "resort_special",
    "comprehensive_resorts": "resort_comprehensive",
    "international_convention_facilities": "mice_convention_facility",
    "international_convention_planners": "mice_convention_planner",
    "golf_courses": "golf_course",
    "ski_resorts": "ski_resort",
    "yacht_marinas": "yacht_marina",
    "horse_riding": "horse_riding",
    "sledding": "sledding",
    "swimming_pools": "swimming_pool",
    "ice_rinks": "ice_rink",
    "comprehensive_sports_facilities": "sports_facility_comprehensive",
    "registered_sports_facilities": "sports_facility_registered",
    "large_scale_retail_stores": "retail_large_scale",
    "movie_theaters": "movie_theater",
    "public_baths": "public_bath",
}
"""PROMOTED 슬러그 → ``PlaceDetail.place_kind`` (docs §6.1)."""


# -- 적재 순서 (docs §10.1) ---------------------------------------------------

MOIS_SLUG_LOAD_GROUPS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    # 여행 지도에서 먼저 보여야 할 것부터. 재개형 적재(ADR-108)는 run마다 이 순서로 업종을
    # 걷고 상한에 닿으면 다음 run이 잇는다 — sorted() 순서에서는 숙박이 일반음식점(67만 행)
    # 뒤라 4시간 run 몇 번으로는 닿지 못했다(2026-11-09 감사: 42종 중 12종만 적재).
    ("lodging", (
        "lodgings", "tourist_accommodations", "tourist_pensions", "rural_homestays",
        "foreigner_city_homestays", "hanok_experience", "general_campgrounds",
        "auto_campgrounds",
    )),
    ("resort_theme", (
        "special_resorts", "comprehensive_resorts", "comprehensive_amusement_facilities",
        "general_amusement_facilities", "amusement_facilities_other",
    )),
    ("tourism_culture", (
        "tourism_businesses", "tourist_cruises", "city_tour_businesses", "tourist_railways",
        "museums_and_art_galleries", "performance_halls", "tourist_performance_halls",
        "tourist_theater_entertainment", "traditional_temples",
    )),
    ("leisure_sports", (
        "golf_courses", "ski_resorts", "yacht_marinas", "horse_riding", "sledding",
        "swimming_pools", "ice_rinks", "comprehensive_sports_facilities",
        "registered_sports_facilities",
    )),
    ("mice", ("international_convention_facilities", "international_convention_planners")),
    ("shopping_urban", ("large_scale_retail_stores", "movie_theaters", "public_baths")),
    ("tourist_food", (
        "tourist_restaurants", "tourist_entertainment_restaurants",
        "foreigners_entertainment_restaurants",
    )),
    # 대량 식음은 마지막 — 일반음식점이 전체의 약 70%다.
    ("mass_food", ("bakeries", "rest_cafes", "general_restaurants")),
)  # fmt: skip
"""적재 우선순위 그룹(정본). 모든 PROMOTED 업종이 정확히 한 번 나와야 한다(import 시 검사)."""

MOIS_SLUG_LOAD_ORDER: Final[tuple[str, ...]] = tuple(
    slug for _group, slugs in MOIS_SLUG_LOAD_GROUPS for slug in slugs
)
"""업종 적재 순서 — :data:`MOIS_SLUG_LOAD_GROUPS`에서 유도한다."""

if len(MOIS_SLUG_LOAD_ORDER) != len(set(MOIS_SLUG_LOAD_ORDER)) or set(
    MOIS_SLUG_LOAD_ORDER
) != set(PROMOTED_SERVICE_SLUGS):  # pragma: no cover — 정의 오류는 import에서 바로 드러난다
    raise RuntimeError("MOIS_SLUG_LOAD_GROUPS가 PROMOTED 업종을 정확히 한 번씩 덮지 않는다")

_SLUG_LOAD_RANK: Final[Mapping[str, int]] = {
    slug: rank for rank, slug in enumerate(MOIS_SLUG_LOAD_ORDER)
}


def order_service_slugs(slugs: Iterable[str]) -> tuple[str, ...]:
    """업종 이름들을 적재 순서로 정렬한다(중복 제거). PROMOTED 밖의 이름은 ``ValueError``."""
    unique = set(slugs)
    unknown = sorted(unique - PROMOTED_SERVICE_SLUGS)
    if unknown:
        raise ValueError(f"PROMOTED 업종이 아니다: {unknown}")
    return tuple(sorted(unique, key=_SLUG_LOAD_RANK.__getitem__))


# -- 입력 Protocol ------------------------------------------------------------


@runtime_checkable
class MoisLicensePlaceRecord(Protocol):
    """MOIS 인허가 1건의 입력 shape (``mois.db.PlaceRecord`` 모사).

    ``mois``를 import하지 않고 structural typing으로만 의존한다 (ADR-006). 좌표
    ``lon``/``lat``는 이미 WGS84 (mois가 EPSG:5174 → WGS84 변환 수행).
    """

    @property
    def service_slug(self) -> str:
        """업종 슬러그 (예: ``general_restaurants``). PROMOTED/EXCLUDED 필터 키."""
        ...

    @property
    def mng_no(self) -> str | None:
        """인허가 관리번호. source_entity_id + 자연키."""
        ...

    @property
    def category(self) -> str | None:
        """한글 인허가 대분류 (예: ``식품``). payload 보존용."""
        ...

    @property
    def title(self) -> str | None:
        """한글 업종명 (예: ``식품_관광식당``). payload 보존용."""
        ...

    @property
    def opn_authority_code(self) -> str | None:
        """개방자치단체코드. **법정동코드 아님** — payload 보존만."""
        ...

    @property
    def place_name(self) -> str | None:
        """사업장명 (``BPLC_NM``). ``Feature.name``."""
        ...

    @property
    def status_code(self) -> str | None:
        """영업상태코드."""
        ...

    @property
    def status_name(self) -> str | None:
        """영업상태명."""
        ...

    @property
    def detail_status_code(self) -> str | None:
        """상세영업상태코드."""
        ...

    @property
    def detail_status_name(self) -> str | None:
        """상세영업상태명."""
        ...

    @property
    def is_open(self) -> bool | None:
        """영업중 여부. 변환은 영업중(True)만."""
        ...

    @property
    def license_date(self) -> date | None:
        """인허가일자."""
        ...

    @property
    def telno(self) -> str | None:
        """전화번호."""
        ...

    @property
    def road_address(self) -> str | None:
        """도로명 주소."""
        ...

    @property
    def lot_address(self) -> str | None:
        """지번 주소."""
        ...

    @property
    def road_zip(self) -> str | None:
        """도로명 우편번호."""
        ...

    @property
    def lot_zip(self) -> str | None:
        """지번 우편번호."""
        ...

    @property
    def legal_dong_code(self) -> str | None:
        """법정동 코드 (mois 직접 제공). bjd_code 1차 source."""
        ...

    @property
    def road_name_code(self) -> str | None:
        """도로명 코드."""
        ...

    @property
    def building_management_number(self) -> str | None:
        """건물관리번호 → ``Address.road_address_management_no``."""
        ...

    @property
    def lon(self) -> float | None:
        """경도 (WGS84, mois 변환 완료)."""
        ...

    @property
    def lat(self) -> float | None:
        """위도 (WGS84, mois 변환 완료)."""
        ...

    @property
    def source_x(self) -> float | None:
        """원본 EPSG:5174 X — payload 보존."""
        ...

    @property
    def source_y(self) -> float | None:
        """원본 EPSG:5174 Y — payload 보존."""
        ...

    # facility_info 구성 필드 (docs §6.2)
    @property
    def business_type_name(self) -> str | None: ...
    @property
    def subtype_name(self) -> str | None: ...
    @property
    def multi_use_business_place_yn(self) -> str | None: ...
    @property
    def sanitation_business_status_name(self) -> str | None: ...
    @property
    def facility_total_scale(self) -> str | None: ...
    @property
    def water_supply_facility_type_name(self) -> str | None: ...
    @property
    def culture_sports_business_type_name(self) -> str | None: ...
    @property
    def sales_method_name(self) -> str | None: ...
    @property
    def designation_date(self) -> date | None: ...
    @property
    def building_usage_name(self) -> str | None: ...
    @property
    def ground_floor_count(self) -> int | None: ...
    @property
    def underground_floor_count(self) -> int | None: ...
    @property
    def total_floor_count(self) -> int | None: ...
    @property
    def facility_area(self) -> float | None: ...
    @property
    def total_area(self) -> float | None: ...
    @property
    def sickbed_count(self) -> int | None: ...
    @property
    def bed_count(self) -> int | None: ...
    @property
    def healthcare_worker_count(self) -> int | None: ...
    @property
    def hospital_room_count(self) -> int | None: ...
    @property
    def medical_institution_type_name(self) -> str | None: ...
    @property
    def medical_subject_names(self) -> str | None: ...


# -- category / place_kind resolver ------------------------------------------


def resolve_license_category(slug: str) -> str | None:
    """PROMOTED 슬러그 → category code. PROMOTED 외면 ``None``."""
    return PROMOTED_CATEGORY_BY_SLUG.get(slug)


# 원천의 명시적인 업태만 기존 승격 업종 안에서 세분화한다.
_LICENSE_SUBTYPE_CATEGORIES: Final[Mapping[str, Mapping[str, str]]] = {
    "general_restaurants": {
        "한식": "02010100", "경양식": "02010200", "일식": "02010300",
        "중국식": "02010400", "외국음식전문점(인도,태국등)": "02010500",
        "패스트푸드": "02010600", "뷔페식": "02010700", "분식": "02010900",
    },
    "rest_cafes": {"다방": "02020000", "커피숍": "02020100"},
    "tourist_accommodations": {
        "관광호텔업": "03010100", "가족호텔업": "03010000",
        "비즈니스호텔": "03010200", "한옥호텔": "03010300",
    },
    "large_scale_retail_stores": {"대형마트": "05030000", "백화점": "05050000"},
    # 공중위생 숙박업(2026-11-09 원천 실측 업태 7종). 여관·여인숙·기타는 슬러그 기본값(일반 모텔).
    "lodgings": {
        "관광호텔": "03010100", "일반호텔": "03010000", "휴양콘도미니엄업": "03020100",
        "숙박업(생활)": "03000000", "여관업": "03040100", "여인숙업": "03040100",
    },
    # 관광사업체 중 관광숙박업은 숙박이다(관광 01000000이 아니다). 여행업은 승격하지 않는다.
    "tourism_businesses": {"관광숙박업": "03010100"},
}

_NON_PROMOTED_SUBTYPES: Final[Mapping[str, frozenset[str]]] = {
    # 여행업 사무소(예: ㈜호텔신라의 여행업 등록)는 지도 장소가 아니다 — 호텔 이름 검색을 가린다.
    "tourism_businesses": frozenset({"여행업"}),
}

_LICENSE_SUBTYPE_PLACE_KINDS: Final[Mapping[str, Mapping[str, str]]] = {
    "lodgings": {
        "관광호텔": "lodging_tourist_hotel", "일반호텔": "lodging_hotel",
        "휴양콘도미니엄업": "lodging_resort_condo", "숙박업(생활)": "lodging_residence",
    },
    "tourism_businesses": {"관광숙박업": "lodging_tourist_hotel"},
}


def _subtype_labels(record: MoisLicensePlaceRecord) -> set[str]:
    return {
        label.strip()
        for label in (
            record.subtype_name, record.business_type_name,
            record.culture_sports_business_type_name,
        )
        if label is not None and label.strip()
    }


def _record_category(record: MoisLicensePlaceRecord) -> str | None:
    fallback = resolve_license_category(record.service_slug)
    mapping = _LICENSE_SUBTYPE_CATEGORIES.get(record.service_slug, {})
    categories = {mapping[label] for label in _subtype_labels(record) if label in mapping}
    return next(iter(categories)) if len(categories) == 1 else fallback


def license_record_is_promotable(record: MoisLicensePlaceRecord) -> bool:
    """이 record가 place Feature가 되는가 — PROMOTED·영업중이고 승격 제외 업태가 아니다.

    승격 제외 업태(``tourism_businesses``의 ``여행업``)는 EXCLUDED 슬러그처럼 변환하지 않는다.
    업태 라벨이 여럿이면 하나라도 제외 업태일 때 제외한다(사무소 등록을 장소로 올리지 않는다).
    """
    if record.service_slug not in PROMOTED_SERVICE_SLUGS or record.is_open is not True:
        return False
    excluded = _NON_PROMOTED_SUBTYPES.get(record.service_slug)
    return not (excluded and _subtype_labels(record) & excluded)


def _record_place_kind(record: MoisLicensePlaceRecord) -> str:
    mapping = _LICENSE_SUBTYPE_PLACE_KINDS.get(record.service_slug, {})
    kinds = {mapping[label] for label in _subtype_labels(record) if label in mapping}
    return next(iter(kinds)) if len(kinds) == 1 else resolve_license_place_kind(record.service_slug)


def resolve_license_place_kind(slug: str) -> str:
    """PROMOTED 슬러그 → ``place_kind``. 미매핑이면 ``license_place`` fallback."""
    return PROMOTED_PLACE_KIND_BY_SLUG.get(slug, _LICENSE_ENTITY_TYPE)


def license_source_entity_id(record: MoisLicensePlaceRecord) -> str:
    """MOIS 인허가 record의 ``source_entity_id`` (자연키 ``{slug}::{mng_no}``).

    Step C 폐업/취소가 변환 없이 폐업 record → feature 매칭 키를 뽑을 때 사용
    (bulk 적재 시와 동일 공식, ADR-009 — ``|`` 금지 ``::``).
    """
    return f"{record.service_slug}{_NATURAL_KEY_SEP}{record.mng_no or ''}"


def license_record_payload_hash(record: MoisLicensePlaceRecord) -> str:
    """``license_record_to_bundle``이 ``SourceRecord.raw_payload_hash``로 쓸 값을 미리 계산한다.

    지오코딩 **전에** 알 수 있는 값이다 — ``_raw_data``는 원천 필드만 담고 역지오코딩
    결과를 담지 않는다. 그래서 재개형 적재(ADR-108)가 "이 record는 이미 같은 payload로
    적재돼 있는가"를 지오코딩 없이 물을 수 있다. PROMOTED 슬러그가 아니면 변환 함수와
    같은 이유로 ``ValueError``다.
    """
    category = _record_category(record)
    if category is None:
        raise ValueError(
            f"service_slug={record.service_slug!r}는 PROMOTED 슬러그가 아님 — 변환 불가."
        )
    return make_payload_hash(_raw_data(record, category=category))


def license_reverse_geocode_coordinate(record: MoisLicensePlaceRecord) -> Coordinate | None:
    """변환이 역지오코딩을 **부를** record면 그 좌표를, 아니면 ``None``을 돌려준다.

    ``license_record_to_bundle``의 분기와 같은 조건이다 — 원천이 법정동 코드를 이미
    주면(``legal_dong_code``) 역지오코딩하지 않고, 좌표가 없거나 한국 경계 밖이어도
    부르지 않는다. 적재기는 이것으로 chunk의 좌표를 미리 모아 bounded 동시성으로
    한 번에 조회한다(ADR-108).
    """
    if normalize_bjd_code(record.legal_dong_code) is not None:
        return None
    return _coord_from(record.lon, record.lat)


# -- 숙박 계열 업종 사이 중복 흡수 (docs §6.3) ------------------------------------

LICENSE_DEDUP_FAMILY: Final[tuple[str, ...]] = (
    "lodgings",
    "tourist_accommodations",
    "tourism_businesses",
)
"""같은 숙박시설이 여러 인허가로 등록되는 업종 — **앞이 이긴다**.

관광호텔 하나가 공중위생 숙박업(``lodgings``, 업태로 호텔·콘도를 가른다)·관광숙박업 등록
(``tourist_accommodations``, 업태가 ``관광숙박업`` 하나뿐)·관광사업체(``tourism_businesses``의
``관광숙박업``)에 함께 있다. 업태가 가장 구체적인 ``lodgings``가 Feature가 되고, 뒤 업종의 같은
시설 행은 Feature가 되지 않는다(이미 있었다면 적재기가 은퇴시킨다 — 이긴 쪽 Feature가 실제로
있을 때만, ``mois_chunked_load``).
"""

IN_BUILDING_FACILITY_SLUGS: Final[tuple[str, ...]] = ("public_baths", "performance_halls")
"""호텔 안 시설이 호텔 법인 상호 그대로 등록되는 업종 — 가려지기만 하고 이기지 않는다.

2026-11-09 원천: "(주)라한호텔목포"·"주식회사라한호텔전주"의 사우나(목욕장업), "호텔신라"의 공연장이
호텔과 같은 상호·같은 건물로 있다. 표시 이름이 호텔과 똑같아 검색에 같은 이름이 둘 셋 뜬다. 이름
키가 **정확히** 같고 도로명 주소의 건물번호까지가 같을 때만 가린다("조선팰리스강남 사우나"처럼
이름이 다른 시설은 남는다).
"""

SHADOW_MAX_DISTANCE_M: Final[float] = 100.0
"""도로명 주소가 다르거나 없을 때 같은 시설로 보는 좌표 거리 상한(m). 이름 키는 같아야 한다."""

SHADOW_MIN_CONTAINED_KEY: Final[int] = 4
"""같은 건물에서 한 이름 키가 다른 키의 **앞부분**이면 같은 시설로 보는 최소 키 길이.

예: "호텔신라제주"가 "호텔신라제주신라"의 앞부분. 숙박 계열끼리만, 같은 건물이고 분류의 앞 네
자리(호텔 0301·리조트 0302 …)가 같을 때만 쓴다 — 생활숙박 "OO호텔레지던스"가 관광호텔 "OO호텔"을
가리지 않게(적대 리뷰 LOW).
"""

COORD_SOURCE_GEOCODE: Final[str] = "kor_travel_geo_geocode"
"""원천 좌표 없이 주소 정지오코딩으로 얻은 점의 출처 표식(``detail.payload["coord_source"]``)."""

MOIS_COORD_RULE: Final[str] = "mois-address-geocode-v1"
"""원천 좌표가 없는 행만 ``raw_data["coord_rule"]``에 싣는 판.

이미 점 없이 적재된 행이 "그대로"로 건너뛰지 않고 한 번 다시 변환되어 정지오코딩을 받는다.
"""

_EXPAND_BRACKET_SLUGS: Final[frozenset[str]] = frozenset(LICENSE_DEDUP_FAMILY)
"""맨 끝 한글 괄호(``(경주)``)를 공백 낱말로 펴는 업종 — 숙박 계열 세 업종만(아직 미적재).

모든 업종에 켜면 괄호 상호 6만 행이, 적재된 캠핑장·민박에 켜도 그만큼이 다시 변환된다.
"""


def license_needs_forward_geocode(record: MoisLicensePlaceRecord) -> bool:
    """원천 좌표가 없고(또는 한국 경계 밖) 점으로 찍을 만한 주소가 있는 record.

    주소에 건물번호·지번이 있어야 한다(``geocoding.address_has_location_number`` — 행정구역까지인
    주소는 대표점이라 쓰지 않는다, #1463). 변환이 공용 정지오코딩을 부르는 조건과 같다.
    """
    return _coord_from(record.lon, record.lat) is None and address_has_location_number(
        Address(
            road=normalize_korean_text(record.road_address),
            legal=normalize_korean_text(record.lot_address),
        )
    )


def license_business_name(record: MoisLicensePlaceRecord) -> BusinessName | None:
    """record의 표시 이름(업종별 괄호 규칙 포함). 변환·해시·중복 키가 모두 이것을 쓴다."""
    return normalize_business_name(
        record.place_name,
        expand_trailing_bracket=record.service_slug in _EXPAND_BRACKET_SLUGS,
    )


def _name_key(record: MoisLicensePlaceRecord) -> str | None:
    business = license_business_name(record)
    if business is None:
        return None
    return re.sub(r"[\s()]+", "", business.display).lower() or None


def _road_base(road: str | None) -> str | None:
    """도로명 주소의 건물번호까지(쉼표·괄호 뒤 상세 제외), 공백 없이."""
    text = normalize_korean_text(road)
    if text is None:
        return None
    head = re.split(r"[,(]", text, maxsplit=1)[0]
    return re.sub(r"\s+", "", head) or None


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6_371_000.0 * math.asin(math.sqrt(min(1.0, h)))


@dataclass(frozen=True)
class _ShadowEntry:
    rank: int
    key: str
    source_entity_id: str
    road_base: str | None
    point: tuple[float, float] | None
    facility: bool
    category: str


@dataclass(frozen=True)
class ShadowedLicenseRecord:
    """앞 업종의 같은 시설에 가려 Feature가 되지 않는 record(적재기가 은퇴 대상으로 본다)."""

    record: MoisLicensePlaceRecord
    winner_source_entity_id: str

    @property
    def service_slug(self) -> str:
        return self.record.service_slug


class LicenseShadowIndex:
    """:data:`LICENSE_DEDUP_FAMILY` 업종의 승격 record로 만든 "같은 시설" 색인.

    숙박 계열끼리 같은 시설 = 이름 키(표시 이름의 공백·괄호 제거, 소문자)가 같고 도로명 주소의
    건물번호까지가 같거나 좌표가 :data:`SHADOW_MAX_DISTANCE_M` 안이다. 또는 같은 건물에서 한 키가
    다른 키를 품는다(:data:`SHADOW_MIN_CONTAINED_KEY`). :data:`IN_BUILDING_FACILITY_SLUGS`는 같은
    건물·정확히 같은 키일 때만 가려진다. 업종 선택과 무관하게 원천 snapshot 전체로 만든다.
    """

    def __init__(self, entries: Sequence[_ShadowEntry]) -> None:
        self._by_name: dict[str, list[_ShadowEntry]] = {}
        self._by_road: dict[str, list[_ShadowEntry]] = {}
        for entry in sorted(entries, key=lambda e: (e.rank, e.source_entity_id)):
            self._by_name.setdefault(entry.key, []).append(entry)
            if entry.road_base is not None:
                self._by_road.setdefault(entry.road_base, []).append(entry)

    @classmethod
    def build(cls, records: Iterable[MoisLicensePlaceRecord]) -> LicenseShadowIndex:
        """승격되는 숙박 계열 record로 색인을 만든다(시설 업종·그 밖의 record는 이기지 않는다)."""
        return cls(
            [
                entry
                for record in records
                if (entry := _shadow_entry(record)) is not None and not entry.facility
            ]
        )

    def __len__(self) -> int:
        return sum(len(rows) for rows in self._by_name.values())

    def winner_for(self, record: MoisLicensePlaceRecord) -> str | None:
        """``record``를 가리는 **맨 앞** 업종 record의 ``source_entity_id``. 없으면 ``None``.

        사슬을 끝까지 따라간다 — 관광사업체 B가 관광숙박업 T에, T가 lodgings L에 가려지면 B의 답은
        L이다. T를 답으로 주면 T가 철회돼 지도에 없으므로 적재기가 B를 다시 싣는다(적대 리뷰 MED).
        """
        mine = _shadow_entry(record)
        if mine is None:
            return None
        winner = self._winner_entry(mine)
        if winner is None:
            return None
        seen = {winner.source_entity_id}
        while (higher := self._winner_entry(winner)) is not None:
            if higher.source_entity_id in seen:  # pragma: no cover — rank가 줄어들므로 없다
                break
            seen.add(higher.source_entity_id)
            winner = higher
        return winner.source_entity_id

    def _winner_entry(self, mine: _ShadowEntry) -> _ShadowEntry | None:
        """``mine``을 직접 가리는 entry 중 rank가 가장 작은 것."""
        found: list[_ShadowEntry] = []
        for other in self._by_name.get(mine.key, ()):
            if other.rank >= mine.rank:
                break
            same_road = mine.road_base is not None and mine.road_base == other.road_base
            near = (
                not mine.facility
                and mine.point is not None
                and other.point is not None
                and _distance_m(mine.point, other.point) <= SHADOW_MAX_DISTANCE_M
            )
            if same_road or near:
                found.append(other)
        if not mine.facility and mine.road_base is not None:
            for other in self._by_road.get(mine.road_base, ()):
                if other.rank >= mine.rank:
                    break
                shorter, longer = sorted((mine.key, other.key), key=len)
                if (
                    len(shorter) >= SHADOW_MIN_CONTAINED_KEY
                    and longer.startswith(shorter)
                    and other.category[:4] == mine.category[:4]
                ):
                    found.append(other)
        return min(found, key=lambda e: (e.rank, e.source_entity_id), default=None)


def _shadow_entry(record: MoisLicensePlaceRecord) -> _ShadowEntry | None:
    slug = record.service_slug
    facility = slug in IN_BUILDING_FACILITY_SLUGS
    if slug not in LICENSE_DEDUP_FAMILY and not facility:
        return None
    if not license_record_is_promotable(record):
        return None
    category = _record_category(record) or ""
    if not facility and not category.startswith("03"):
        # 관광사업체 중 숙박이 아닌 업태(관광객이용시설업 등)는 숙박시설과 같은 시설일 수 없다.
        return None
    key = _name_key(record)
    if key is None:
        return None
    coord = _coord_from(record.lon, record.lat)
    rank = (
        len(LICENSE_DEDUP_FAMILY) + IN_BUILDING_FACILITY_SLUGS.index(slug)
        if facility
        else LICENSE_DEDUP_FAMILY.index(slug)
    )
    return _ShadowEntry(
        rank=rank,
        key=key,
        source_entity_id=license_source_entity_id(record),
        road_base=_road_base(record.road_address),
        point=(float(coord.lon), float(coord.lat)) if coord is not None else None,
        facility=facility,
        category=category,
    )


def _maki_for(category: str) -> str:
    """category → maki icon (카탈로그 우선, 없으면 fallback)."""
    if is_known_category_code(category):
        return get_category(category).mapbox_maki_icon or MOIS_DEFAULT_MARKER_ICON
    return MOIS_DEFAULT_MARKER_ICON


def _coord_from(lon: float | None, lat: float | None) -> Coordinate | None:
    """WGS84 lon/lat → ``Coordinate`` (없거나 한국 경계 밖이면 ``None``)."""
    if lon is None or lat is None:
        return None
    try:
        return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))
    except (ValueError, ArithmeticError):
        return None


def _zipcode(road_zip: str | None, lot_zip: str | None) -> str | None:
    """신우편번호 5자리만 채택 (그 외 형식은 payload에만)."""
    for candidate in (road_zip, lot_zip):
        if candidate is not None and candidate.isdigit() and len(candidate) == 5:
            return candidate
    return None


def _build_address(
    record: MoisLicensePlaceRecord,
    *,
    geo: Address | None,
    bjd_code: str | None,
) -> Address:
    """mois 원천 주소 + (선택) 역지오코딩 결과를 ``Address``로 병합.

    ``legal_dong_code``(mois 직접 제공)가 1차 bjd_code. ``opn_authority_code``는
    법정동코드가 아니므로 절대 bjd로 쓰지 않는다 (docs §7).
    """
    sigungu = extract_sigungu_code(bjd_code) if bjd_code else None
    sido = extract_sido_code(bjd_code) if bjd_code else None
    if geo is not None:
        sigungu = sigungu or geo.sigungu_code
        sido = sido or geo.sido_code
    return Address(
        road=normalize_korean_text(record.road_address),
        legal=normalize_korean_text(record.lot_address),
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu,
        sido_code=sido,
        road_name_code=record.road_name_code,
        road_address_management_no=record.building_management_number,
        zipcode=_zipcode(record.road_zip, record.lot_zip),
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )


def _facility_info(record: MoisLicensePlaceRecord) -> dict[str, Any]:
    """업종별 mois 필드를 ``PlaceDetail.facility_info``로 promote (docs §6.2)."""
    base: dict[str, Any] = {
        "service_slug": record.service_slug,
        "category": record.category,
        "subtype_name": record.subtype_name,
        "sales_method_name": record.sales_method_name,
    }
    if record.facility_area or record.total_area or record.total_floor_count:
        base["building"] = {
            "facility_area_m2": record.facility_area,
            "total_area_m2": record.total_area,
            "floors_ground": record.ground_floor_count,
            "floors_underground": record.underground_floor_count,
            "floors_total": record.total_floor_count,
            "use": record.building_usage_name,
        }
    if record.bed_count or record.healthcare_worker_count:
        base["medical"] = {
            "bed_count": record.bed_count,
            "sickbed_count": record.sickbed_count,
            "healthcare_worker_count": record.healthcare_worker_count,
            "hospital_room_count": record.hospital_room_count,
            "specialties": record.medical_subject_names,
            "institution_type": record.medical_institution_type_name,
        }
    if record.sanitation_business_status_name or record.water_supply_facility_type_name:
        base["food"] = {
            "sanitation_status": record.sanitation_business_status_name,
            "water_facility_type": record.water_supply_facility_type_name,
            "business_type": record.business_type_name,
            "multi_use": record.multi_use_business_place_yn == "Y",
        }
    if record.culture_sports_business_type_name:
        base["culture_sports"] = {
            "type": record.culture_sports_business_type_name,
            "designation_date": (
                record.designation_date.isoformat() if record.designation_date is not None else None
            ),
            "facility_total_scale": record.facility_total_scale,
        }
    return base


def _raw_data(record: MoisLicensePlaceRecord, *, category: str) -> dict[str, Any]:
    """payload_hash 입력용 canonical dict (안정적 key 순서, JSON 직렬화 가능)."""
    raw: dict[str, Any] = {
        "service_slug": record.service_slug,
        "mng_no": record.mng_no,
        "category": record.category,
        "title": record.title,
        "place_name": record.place_name,
        "opn_authority_code": record.opn_authority_code,
        "status_code": record.status_code,
        "status_name": record.status_name,
        "detail_status_code": record.detail_status_code,
        "detail_status_name": record.detail_status_name,
        "is_open": record.is_open,
        "license_date": (
            record.license_date.isoformat() if record.license_date is not None else None
        ),
        "telno": record.telno,
        "road_address": record.road_address,
        "lot_address": record.lot_address,
        "legal_dong_code": record.legal_dong_code,
        "road_name_code": record.road_name_code,
        "lon": record.lon,
        "lat": record.lat,
        "source_x": record.source_x,
        "source_y": record.source_y,
        "krtour_category": category,
    }
    business = license_business_name(record)
    if business is not None and business.changed:
        # 규칙 판이 아니라 **결과**를 해시한다 — 결과가 바뀐 행만 다시 변환된다(리뷰 MED).
        raw["display_name"] = business.display
    if license_needs_forward_geocode(record):
        # 원천 좌표가 없고 주소가 있는 행만 — 이미 점 없이 적재된 행도 한 번 다시 변환된다.
        raw["coord_rule"] = MOIS_COORD_RULE
    if record.service_slug in _LICENSE_SUBTYPE_CATEGORIES:
        # 분류를 세분화하는 슬러그만 업태를 담는다 — 복원 되먹임이 같은 분류를 다시 내고,
        # 다른 슬러그의 해시(재개형 적재 키)는 바뀌지 않는다(#1444 리뷰).
        raw.update(
            subtype_name=record.subtype_name,
            business_type_name=record.business_type_name,
            culture_sports_business_type_name=record.culture_sports_business_type_name,
        )
    return raw


# -- 변환 ---------------------------------------------------------------------


async def license_record_to_bundle(
    record: MoisLicensePlaceRecord,
    *,
    fetched_at: datetime,
    dataset_key: str = DATASET_KEY_BULK,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
    address_geocoder: AddressGeocoder | None = None,
) -> FeatureBundle:
    """단일 PROMOTED 인허가 ``PlaceRecord`` → place ``FeatureBundle``.

    호출 측은 필터(EXCLUDED/non-PROMOTED/non-open)를 통과한 record만 넘기는 것을
    권장하나, 본 함수는 category 미상(PROMOTED 외) record에 ``ValueError``를 낸다.

    ``address_geocoder``(공용 원천 좌표 결측 fallback, #1463)가 있고 원천 좌표(EPSG:5174
    변환값)가 없으면 건물번호·지번이 있는 주소로 점을 얻는다 — ``detail.payload["coord_source"]``가
    ``kor_travel_geo_geocode``가 된다. 그 점으로 평소처럼 역지오코딩한다(원천 법정동이 없을 때).
    """
    slug = record.service_slug
    category = _record_category(record)
    if category is None:
        raise ValueError(f"service_slug={slug!r}는 PROMOTED 슬러그가 아님 — 변환 불가.")
    place_kind = _record_place_kind(record)
    natural_key = license_source_entity_id(record)

    coord = _coord_from(record.lon, record.lat)
    coord_source: str | None = None

    # bjd_code는 feature_id 전에 확정 (ADR-009). legal_dong_code 1차, 없으면 역지오코딩.
    bjd_code = normalize_bjd_code(record.legal_dong_code)
    geo: Address | None = None
    # T-VN-H30C: obs 축은 좌표 reverse 결과만 실어야 하므로 출처를 분리해 둔다.
    reverse_geo: Address | None = None
    # 실제로 reverse를 **불렀는지**를 기록한다. 입력이 갖춰졌는지가 아니다 — MOIS는
    # payload에 bjd가 있으면 아래 분기를 타지 않으므로, 입력 기준으로 판정하면
    # 그 흔한 경우 전부가 "reverse 시도했는데 실패"로 잘못 보고된다.
    reverse_called = False
    # ADR-109 결정 3 ②: geocode로 법정동코드를 **받았는가**(시도만 하고 못 받은 행은 geo 유도 값
    # 0개).
    geocode_obtained_code = False
    source_address = Address(
        road=normalize_korean_text(record.road_address),
        legal=normalize_korean_text(record.lot_address),
    )
    if coord is None and address_geocoder is not None:
        located = await geocode_missing_coordinate(None, source_address, address_geocoder)
        if located is not None:
            # 공용 fallback(#1463)과 같다 — 아래 역지오코딩이 법정동을 채우고 스탬프는 called다.
            coord = located
            coord_source = COORD_SOURCE_GEOCODE
    if bjd_code is None and coord is not None and reverse_geocoder is not None:
        reverse_called = True
        geo = await reverse_geocoder(coord)
        reverse_geo = geo
        bjd_code = geo.bjd_code if geo is not None else None
    if bjd_code is None and address_resolver is not None:
        resolved = await address_resolver(source_address)
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
            bjd_code = resolved.bjd_code
            geocode_obtained_code = True
    address = _build_address(record, geo=geo, bjd_code=bjd_code)

    raw_data = _raw_data(record, category=category)
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=_LICENSE_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        # 재분류로 기존 legacy ID 별칭이 달라지지 않도록 이전 slug seed를 유지한다.
        category=PROMOTED_CATEGORY_BY_SLUG[slug],
        source_type=f"{PROVIDER_NAME}:{dataset_key}",
        source_natural_key=natural_key,
    )

    business = license_business_name(record)
    name = business.display if business is not None else (record.place_name or natural_key)
    phones = [p for p in (normalize_phone_number(record.telno),) if p]
    detail = PlaceDetail(
        feature_id=feature_id,
        place_kind=place_kind,
        phones=phones,
        facility_info=_facility_info(record),
        license_date=record.license_date,
        payload={
            "mng_no": record.mng_no,
            "status_code": record.status_code,
            "status_name": record.status_name,
            "detail_status_code": record.detail_status_code,
            "detail_status_name": record.detail_status_name,
            "opn_authority_code": record.opn_authority_code,
            "title": record.title,
            "epsg5174": (
                {"x": record.source_x, "y": record.source_y}
                if record.source_x is not None and record.source_y is not None
                else None
            ),
            # 법인 표기는 상세에 남긴다 — 표시 이름은 그것을 걷은 것이다(docs §6.4).
            **(
                {"legal_name": business.legal}
                if business is not None and business.changed
                else {}
            ),
            **({"coord_source": coord_source} if coord_source is not None else {}),
        },
    )

    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=natural_key,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coord,
        address=address,
        category=category,
        marker_icon=_maki_for(category),
        marker_color=MOIS_MARKER_COLOR,
        detail=detail,
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(PROVIDER_NAME),
        dataset_key=dataset_key,
        source_entity_type=_LICENSE_ENTITY_TYPE,
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
        feature=feature,
        source_record=source_record,
        source_link=source_link,
        # T-VN-H30C: MOIS는 payload에 legal_dong_code가 있으면 reverse를 **호출하지 않는다**
        # (위 분기). 따라서 obs 축이 없어 staleness 대조는 성립하지 않는다 — 그 사실을
        # ``claim_only``로 집계에 드러내는 것이 목적이다. ``unarmed``(미계측)와 구분된다.
        # reverse를 강제로 부르지는 않는다: 977k 레코드에 대한 호출은 비용이 다른 문제다.
        admin_evidence=AdminEvidence(
            # obs 축은 **좌표 reverse** 결과만이다. 위 분기의 ``geo``는 address_resolver
            # (provider 주소 문자열의 정지오코딩)로도 채워지므로 그대로 쓰면 obs가
            # claim_text와 같은 출처가 되어 자기 자신과 비교하게 된다. reverse 경로에서
            # 온 값만 싣는다.
            obs_code=reverse_geo.bjd_code if reverse_geo is not None else None,
            reverse_attempted=reverse_called,
            claim_code=normalize_bjd_code(record.legal_dong_code),
            claim_kind=(
                "bjd" if normalize_bjd_code(record.legal_dong_code) else None
            ),
            claim_text=record.road_address or record.lot_address or None,
        ),
        geo_attempt=GeoAttemptEvidence(
            reverse_attempted=reverse_called,
            geocode_obtained_code=geocode_obtained_code,
        ),
    )


async def license_records_to_bundles(
    records: Iterable[MoisLicensePlaceRecord],
    *,
    fetched_at: datetime,
    dataset_key: str = DATASET_KEY_BULK,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
    address_geocoder: AddressGeocoder | None = None,
) -> list[FeatureBundle]:
    """인허가 ``PlaceRecord`` iterable → place ``FeatureBundle`` 리스트.

    EXCLUDED 슬러그 / PROMOTED 외 슬러그 / 비영업(``is_open != True``) record는
    변환하지 않고 skip한다. 입력 순서를 유지한다.

    Parameters
    ----------
    records
        ``MoisLicensePlaceRecord`` Protocol 만족 iterable (mois source DB
        ``iter_open_place_records`` 결과 등).
    fetched_at
        provider 호출 시각 (KST aware, ADR-019).
    dataset_key
        ``mois_license_features_bulk`` (기본) / ``_history`` / ``_closed``.
    reverse_geocoder
        좌표 → ``Address`` async 역지오코더. ``legal_dong_code`` 부재 시에만
        호출되어 bjd_code를 보강한다 (ADR-009). 중복 좌표는
        ``cached_reverse_geocoder``로 1회만 호출.
    address_resolver
        주소 → ``Address`` async 보강 geocoder. ``legal_dong_code``와 좌표 reverse
        결과가 모두 없을 때 road/lot 주소로 ``/v2/geocode``를 호출한다. 중복 주소는
        ``cached_address_resolver``로 1회만 호출.
    address_geocoder
        원천 좌표가 없는 행의 주소 → 점(공용 fallback, #1463). 중복 주소는
        ``cached_address_geocoder``로 1회만 호출(호출은 행 순서대로 하나씩 — 동시성 1).
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    resolver = cached_address_resolver(address_resolver) if address_resolver is not None else None
    geocoder_fwd = (
        cached_address_geocoder(address_geocoder) if address_geocoder is not None else None
    )
    bundles: list[FeatureBundle] = []
    for record in records:
        if record.service_slug in EXCLUDED_SERVICE_SLUGS:
            continue
        if not license_record_is_promotable(record):
            continue
        bundles.append(
            await license_record_to_bundle(
                record,
                fetched_at=fetched_at,
                dataset_key=dataset_key,
                reverse_geocoder=geocoder,
                address_resolver=resolver,
                address_geocoder=geocoder_fwd,
            )
        )
    return bundles
