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

from collections.abc import Iterable, Mapping
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
from kortravelmap.geocoding import (
    AddressResolver,
    ReverseGeocoder,
    cached_address_resolver,
    cached_reverse_geocoder,
)

__all__ = [
    "MoisLicensePlaceRecord",
    "license_record_to_bundle",
    "license_records_to_bundles",
    "resolve_license_category",
    "resolve_license_place_kind",
    "license_source_entity_id",
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

# source_natural_key 구분자. make_feature_id/make_source_record_key는 구성요소
# 내부 ``|``를 금지하므로 ``::`` 사용 (kma.py alert×region 패턴과 동일).
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


def resolve_license_place_kind(slug: str) -> str:
    """PROMOTED 슬러그 → ``place_kind``. 미매핑이면 ``license_place`` fallback."""
    return PROMOTED_PLACE_KIND_BY_SLUG.get(slug, _LICENSE_ENTITY_TYPE)


def license_source_entity_id(record: MoisLicensePlaceRecord) -> str:
    """MOIS 인허가 record의 ``source_entity_id`` (자연키 ``{slug}::{mng_no}``).

    Step C 폐업/취소가 변환 없이 폐업 record → feature 매칭 키를 뽑을 때 사용
    (bulk 적재 시와 동일 공식, ADR-009 — ``|`` 금지 ``::``).
    """
    return f"{record.service_slug}{_NATURAL_KEY_SEP}{record.mng_no or ''}"


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
                record.designation_date.isoformat()
                if record.designation_date is not None
                else None
            ),
            "facility_total_scale": record.facility_total_scale,
        }
    return base


def _raw_data(record: MoisLicensePlaceRecord, *, category: str) -> dict[str, Any]:
    """payload_hash 입력용 canonical dict (안정적 key 순서, JSON 직렬화 가능)."""
    return {
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


# -- 변환 ---------------------------------------------------------------------


async def license_record_to_bundle(
    record: MoisLicensePlaceRecord,
    *,
    fetched_at: datetime,
    dataset_key: str = DATASET_KEY_BULK,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> FeatureBundle:
    """단일 PROMOTED 인허가 ``PlaceRecord`` → place ``FeatureBundle``.

    호출 측은 필터(EXCLUDED/non-PROMOTED/non-open)를 통과한 record만 넘기는 것을
    권장하나, 본 함수는 category 미상(PROMOTED 외) record에 ``ValueError``를 낸다.
    """
    slug = record.service_slug
    category = resolve_license_category(slug)
    if category is None:
        raise ValueError(
            f"service_slug={slug!r}는 PROMOTED 슬러그가 아님 — 변환 불가."
        )
    place_kind = resolve_license_place_kind(slug)
    natural_key = license_source_entity_id(record)

    coord = _coord_from(record.lon, record.lat)

    # bjd_code는 feature_id 전에 확정 (ADR-009). legal_dong_code 1차, 없으면 역지오코딩.
    bjd_code = normalize_bjd_code(record.legal_dong_code)
    geo: Address | None = None
    if bjd_code is None and coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
        bjd_code = geo.bjd_code if geo is not None else None
    if bjd_code is None and address_resolver is not None:
        resolved = await address_resolver(
            Address(
                road=normalize_korean_text(record.road_address),
                legal=normalize_korean_text(record.lot_address),
            )
        )
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
            bjd_code = resolved.bjd_code
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
        category=category,
        source_type=f"{PROVIDER_NAME}:{dataset_key}",
        source_natural_key=natural_key,
    )

    name = normalize_korean_text(record.place_name) or record.place_name or natural_key
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
        },
    )

    feature = Feature(
        feature_id=feature_id,
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
        raw_name=record.place_name,
        raw_address=record.road_address or record.lot_address,
        raw_longitude=Decimal(str(record.lon)) if record.lon is not None else None,
        raw_latitude=Decimal(str(record.lat)) if record.lat is not None else None,
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
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


async def license_records_to_bundles(
    records: Iterable[MoisLicensePlaceRecord],
    *,
    fetched_at: datetime,
    dataset_key: str = DATASET_KEY_BULK,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
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
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    resolver = (
        cached_address_resolver(address_resolver)
        if address_resolver is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for record in records:
        slug = record.service_slug
        if slug in EXCLUDED_SERVICE_SLUGS:
            continue
        if slug not in PROMOTED_SERVICE_SLUGS:
            continue
        if record.is_open is not True:
            continue
        bundles.append(
            await license_record_to_bundle(
                record,
                fetched_at=fetched_at,
                dataset_key=dataset_key,
                reverse_geocoder=geocoder,
                address_resolver=resolver,
            )
        )
    return bundles
