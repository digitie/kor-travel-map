"""``kortravelmap.providers.datagokr_file_data`` — data.go.kr fileData → FeatureBundle.

T-223b curated source 보강으로 ``python-datagokr-api``의 fileData 자동변환 API
4종(서울 책방, 경기도 무슬림 친화 음식점, 안산 세계맛집, 제주 향토음식점)을
place ``FeatureBundle``로 정규화한다.

provider client와 카탈로그는 ``python-datagokr-api``가 제공하고, 본 모듈은
``PublicFileDataRecord.raw`` 또는 raw ``Mapping``을 받아 DTO로 변환하는 순수 함수만
둔다(ADR-006/044). fileData는 dataset마다 원천 컬럼명이 달라 typed field를 새로
발명하지 않고 raw 컬럼 방언을 이 모듈 안에서만 해석한다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Literal, Protocol

from kortravelmap.category import PlaceCategoryCode, mapbox_maki_icon_or_none
from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
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
    "DATAGOKR_FILEDATA_PROVIDER_NAME",
    "DATAGOKR_FILEDATA_DATASETS",
    "DATAGOKR_FILEDATA_BOOK_MARKER_COLOR",
    "DATAGOKR_FILEDATA_FOOD_MARKER_COLOR",
    "DataGoKrFileDataDatasetSpec",
    "DataGoKrFileDataRecord",
    "file_data_rows_to_bundles",
]

DATAGOKR_FILEDATA_PROVIDER_NAME: Final[str] = "python-datagokr-api"
"""canonical provider name (ADR-024)."""

DATAGOKR_FILEDATA_BOOK_MARKER_COLOR: Final[str] = "P-12"
"""책/문화 계열 curated fileData marker color."""

DATAGOKR_FILEDATA_FOOD_MARKER_COLOR: Final[str] = "P-03"
"""음식 계열 curated fileData marker color."""

DataGoKrFileDataDialect = Literal[
    "seoul_bookstore",
    "gyeonggi_muslim_friendly_restaurant",
    "ansan_world_restaurant",
    "jeju_local_restaurant",
]


class DataGoKrFileDataRecord(Protocol):
    """``python-datagokr-api`` ``PublicFileDataRecord`` 호환 입력 shape."""

    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DataGoKrFileDataDatasetSpec:
    """data.go.kr fileData dataset 1종의 변환 메타."""

    dataset_key: str
    label: str
    category: str
    place_kind: str
    entity_type: str
    marker_color: str
    dialect: DataGoKrFileDataDialect


DATAGOKR_FILEDATA_DATASETS: Final[dict[str, DataGoKrFileDataDatasetSpec]] = {
    "datagokr_seoul_bookstores": DataGoKrFileDataDatasetSpec(
        dataset_key="datagokr_seoul_bookstores",
        label="서울특별시 책방(서점)",
        category=PlaceCategoryCode.TOURISM_CULTURAL_FACILITY.value,
        place_kind="seoul_bookstore",
        entity_type="bookstore",
        marker_color=DATAGOKR_FILEDATA_BOOK_MARKER_COLOR,
        dialect="seoul_bookstore",
    ),
    "datagokr_gyeonggi_muslim_friendly_restaurants": DataGoKrFileDataDatasetSpec(
        dataset_key="datagokr_gyeonggi_muslim_friendly_restaurants",
        label="경기도 무슬림 친화 음식점",
        category=PlaceCategoryCode.FOOD_RESTAURANT.value,
        place_kind="muslim_friendly_restaurant",
        entity_type="restaurant",
        marker_color=DATAGOKR_FILEDATA_FOOD_MARKER_COLOR,
        dialect="gyeonggi_muslim_friendly_restaurant",
    ),
    "datagokr_ansan_world_restaurants": DataGoKrFileDataDatasetSpec(
        dataset_key="datagokr_ansan_world_restaurants",
        label="안산 세계맛집",
        category=PlaceCategoryCode.FOOD_RESTAURANT.value,
        place_kind="ansan_world_restaurant",
        entity_type="restaurant",
        marker_color=DATAGOKR_FILEDATA_FOOD_MARKER_COLOR,
        dialect="ansan_world_restaurant",
    ),
    "datagokr_jeju_local_restaurants": DataGoKrFileDataDatasetSpec(
        dataset_key="datagokr_jeju_local_restaurants",
        label="제주 향토음식점",
        category=PlaceCategoryCode.FOOD_RESTAURANT.value,
        place_kind="jeju_local_restaurant",
        entity_type="restaurant",
        marker_color=DATAGOKR_FILEDATA_FOOD_MARKER_COLOR,
        dialect="jeju_local_restaurant",
    ),
}
"""T-223b curated source fileData 4종 메타표."""


@dataclass(frozen=True, slots=True)
class _ExtractedRow:
    name: str | None
    raw_address: str | None
    lonlat: tuple[float, float] | None
    phone: str | None
    natural_id: str | None
    facility_info: dict[str, Any]


_KOREA_LON_MIN: Final[float] = 124.0
_KOREA_LON_MAX: Final[float] = 132.0
_KOREA_LAT_MIN: Final[float] = 33.0
_KOREA_LAT_MAX: Final[float] = 43.0


def _in_korea_bbox(lon: float, lat: float) -> bool:
    return _KOREA_LON_MIN <= lon <= _KOREA_LON_MAX and _KOREA_LAT_MIN <= lat <= _KOREA_LAT_MAX


def _validated_lonlat(lon: float, lat: float) -> tuple[float, float] | None:
    if _in_korea_bbox(lon, lat):
        return (lon, lat)
    if _in_korea_bbox(lat, lon):
        return (lat, lon)
    return None


def _row_mapping(row: DataGoKrFileDataRecord | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    return row.raw


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
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _joined(row: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    parts = [part for part in (_row_text(row, (key,)) for key in keys) if part]
    return " > ".join(parts) if parts else None


def _lonlat_from_generic_keys(row: Mapping[str, Any]) -> tuple[float, float] | None:
    lat = _row_float(row, ("위도", "latitude", "LAT", "lat", "Y", "y"))
    lon = _row_float(row, ("경도", "longitude", "LON", "lon", "X", "x"))
    if lon is None or lat is None:
        return None
    return _validated_lonlat(lon, lat)


def _extract_seoul_bookstore(row: Mapping[str, Any]) -> _ExtractedRow:
    return _ExtractedRow(
        name=_row_text(row, ("책방명", "서점명", "상호명", "상호", "명칭", "name")),
        raw_address=_row_text(
            row,
            (
                "주소",
                "도로명주소",
                "소재지도로명주소",
                "소재지",
                "상세주소",
                "addr",
            ),
        ),
        lonlat=_lonlat_from_generic_keys(row),
        phone=_row_text(row, ("전화번호", "연락처", "대표전화", "tel")),
        natural_id=_row_text(row, ("관리번호", "책방ID", "서점ID", "id")),
        facility_info={
            "source_category": _joined(row, ("책방구분명", "운영형태", "종류", "구분")),
            "homepage_url": _row_text(row, ("홈페이지", "홈페이지주소", "URL", "url")),
            "description": _row_text(row, ("책방소개", "공간소개", "소개", "설명")),
        },
    )


def _extract_gyeonggi_muslim(row: Mapping[str, Any]) -> _ExtractedRow:
    return _ExtractedRow(
        name=_row_text(row, ("상호", "업소명", "가게명")),
        raw_address=_row_text(row, ("주소", "도로명주소", "소재지")),
        lonlat=_lonlat_from_generic_keys(row),
        phone=_row_text(row, ("연락처", "전화번호")),
        natural_id=None,
        facility_info={
            "region": _row_text(row, ("지역",)),
            "source_category": _row_text(row, ("종류", "구분")),
        },
    )


def _extract_ansan_world(row: Mapping[str, Any]) -> _ExtractedRow:
    return _ExtractedRow(
        name=_row_text(row, ("가게명", "상호", "업소명")),
        raw_address=_row_text(row, ("주소", "도로명주소", "소재지")),
        lonlat=_lonlat_from_generic_keys(row),
        phone=_row_text(row, ("연락처", "전화번호")),
        natural_id=None,
        facility_info={
            "source_category": _row_text(row, ("음식종류", "종류")),
            "description": _row_text(row, ("게시글 내용", "내용", "설명")),
            "view_count": _row_text(row, ("조회수",)),
            "created_at": _row_text(row, ("작성일",)),
            "updated_at": _row_text(row, ("수정일",)),
        },
    )


def _extract_jeju_local(row: Mapping[str, Any]) -> _ExtractedRow:
    return _ExtractedRow(
        name=_row_text(row, ("업소명", "상호", "가게명")),
        raw_address=_row_text(row, ("소재지", "주소", "도로명주소")),
        lonlat=_lonlat_from_generic_keys(row),
        phone=_row_text(row, ("연락처", "전화번호")),
        natural_id=_row_text(row, ("지정번호",)),
        facility_info={
            "management_agency": _row_text(row, ("관리기관",)),
            "source_category": _row_text(row, ("향토음식 주메뉴", "주메뉴", "메뉴")),
            "reference_date": _row_text(row, ("데이터기준일자", "기준일자")),
        },
    )


_EXTRACTORS: Final[dict[DataGoKrFileDataDialect, Callable[[Mapping[str, Any]], _ExtractedRow]]] = {
    "seoul_bookstore": _extract_seoul_bookstore,
    "gyeonggi_muslim_friendly_restaurant": _extract_gyeonggi_muslim,
    "ansan_world_restaurant": _extract_ansan_world,
    "jeju_local_restaurant": _extract_jeju_local,
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _coord_or_none(lonlat: tuple[float, float] | None) -> Coordinate | None:
    if lonlat is None:
        return None
    lon, lat = lonlat
    return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))


async def _resolve_address(
    coord: Coordinate | None,
    *,
    raw_address: str | None,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> Address:
    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    if (geo is None or geo.bjd_code is None) and address_resolver is not None:
        resolved = await address_resolver(Address(road=raw_address))
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
    bjd_code = geo.bjd_code if geo is not None else None
    return Address(
        road=raw_address,
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=(
            (geo.sigungu_code if geo is not None else None) or extract_sigungu_code(bjd_code)
        ),
        sido_code=((geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code)),
        road_name_code=geo.road_name_code if geo is not None else None,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )


def _build_bundle(
    *,
    spec: DataGoKrFileDataDatasetSpec,
    name: str,
    coord: Coordinate | None,
    address: Address,
    raw_address: str | None,
    phone: str | None,
    natural_key: str,
    facility_info: dict[str, Any],
    raw_data: dict[str, Any],
    fetched_at: datetime,
) -> FeatureBundle:
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=DATAGOKR_FILEDATA_PROVIDER_NAME,
        dataset_key=spec.dataset_key,
        source_entity_type=spec.entity_type,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=address.bjd_code,
        kind=FeatureKind.PLACE.value,
        category=spec.category,
        source_type=f"{DATAGOKR_FILEDATA_PROVIDER_NAME}:{spec.dataset_key}",
        source_natural_key=natural_key,
    )
    normalized_phone = normalize_phone_number(phone)
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coord,
        address=address,
        category=spec.category,
        marker_icon=mapbox_maki_icon_or_none(spec.category) or "marker",
        marker_color=spec.marker_color,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=spec.place_kind,
            phones=[normalized_phone] if normalized_phone else [],
            facility_info={k: v for k, v in facility_info.items() if v is not None},
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(DATAGOKR_FILEDATA_PROVIDER_NAME),
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
    return FeatureBundle(feature=feature, source_record=source_record, source_link=source_link)


async def file_data_rows_to_bundles(
    rows: Iterable[DataGoKrFileDataRecord | Mapping[str, Any]],
    *,
    dataset_key: str,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """data.go.kr fileData raw rows → place ``FeatureBundle``.

    ``dataset_key``는 ``DATAGOKR_FILEDATA_DATASETS`` 키여야 한다. 이름이 없거나
    좌표·주소가 모두 없는 row는 feature 식별/위치 단서가 없어 건너뛴다.
    """

    spec = DATAGOKR_FILEDATA_DATASETS[dataset_key]
    extractor = _EXTRACTORS[spec.dialect]
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    resolver = cached_address_resolver(address_resolver) if address_resolver is not None else None
    bundles: list[FeatureBundle] = []
    for row in rows:
        raw_row = _row_mapping(row)
        extracted = extractor(raw_row)
        name = normalize_korean_text(extracted.name)
        raw_address = normalize_korean_text(extracted.raw_address)
        coord = _coord_or_none(extracted.lonlat)
        if name is None or (coord is None and raw_address is None):
            continue
        natural_key = extracted.natural_id or "::".join([name, raw_address or ""])
        address = await _resolve_address(
            coord,
            raw_address=raw_address,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        raw_data = {str(key): _json_safe(value) for key, value in raw_row.items()}
        bundles.append(
            _build_bundle(
                spec=spec,
                name=name,
                coord=coord,
                address=address,
                raw_address=raw_address,
                phone=extracted.phone,
                natural_key=natural_key,
                facility_info=extracted.facility_info,
                raw_data=raw_data,
                fetched_at=fetched_at,
            )
        )
    return bundles
