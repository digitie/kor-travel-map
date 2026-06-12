"""``krtour.map.providers.mcst`` — 문체부 파일데이터(CSV) → place FeatureBundle.

(T-220 재배선, #395 + T-223b) ``python-mcst-api``가 KCISA OpenAPI에서 **CSV 파일
다운로드 주경로**로 재편됨(provider #6/#7/#9/#11, ``@c011f6e``)에 따라 ``FileDataClient``
(**keyless**)의 ``iter_csv(slug)``가 주는 CSV dict row를 place ``FeatureBundle``로
정규화한다. provider client/카탈로그는 별도 라이브러리가 제공(ADR-006 — 본 모듈은
변환 순수 함수).

적재 13 dataset은 컬럼 방언 4종으로 묶인다(2026-06-12 live 전수 CSV 실측):

- ``kcisa_common`` — TITLE(또는 PLACENAME)/ADDRESS/TEL/URL/COORDINATES/
  CATEGORY1-3 대문자 컬럼 8종. ``leisure_classes_csv``는 좌표 컬럼이 없어 주소
  단서만, ``media_famous_places_csv``는 ``PLACENAME`` + ``MEDIATITLE`` 보조.
- ``cntc_resrce`` — CNTC_RESRCE_ID/TITLE/ADDRESS/CONTACT_POINT/COORDINATES 2종
  (독립서점/북카페).
- ``split_coord`` — FCLTY_NM/FCLTY_ROAD_NM_ADDR/FCLTY_LA/FCLTY_LO/TEL_NO 2종
  (아동서점/중고서점).
- ``korean_address`` — 지역/이름/사업자/소재지 한국어 컬럼·좌표 없음 1종
  (골프장 현황, ``지역``+``소재지`` 합성 주소 단서).

**제외 3 dataset** (``MCST_EXCLUDED_FILE_DATASETS``에 사유 보존):
``tourism_attractions_csv``(서지형 42컬럼 — POI 아닌 기사/자료 레코드 혼재) /
``recommended_travel_destinations_csv``(정책브리핑 기사형 — POI 아님) /
``public_libraries``(도서관 통계 — 시설 디렉토리 아님; 구 ODCloud 디렉토리
경로는 provider 재편으로 소멸 — 도서관 디렉토리 재적재는 후속 과제).

category는 전부 **기존 코드**(T-220a 결정 재사용 + 신규 3종도 기존 코드로 흡수
— 아동서점/중고서점은 서점류와 동일 계열, 골프장은 ``01080100``), marker는 문화
계열 1색 ``P-12``.

안정 식별자가 없어 자연키는 ``name::address``(정규화 후, ADR-009 ``::``).
``COORDINATES``는 실측 2형식("N37.5, E126.9" N/E 접두 lat-lon 순 / "35.8 , 128.6"
평문 lat-lon 순 — 공백 변형 포함)을 파싱하고 한국 bbox(lon 124~132, lat 33~43)로
검증한다(순서 뒤집힘 감지 포함). 파싱 실패/범위 밖은 좌표 없음으로 처리해 주소
단서 경로를 탄다. 좌표가 있으면 reverse로 bjd를 보강하고(ADR-046), 이름이
없거나 좌표·주소가 모두 없는 row는 식별 불가라 건너뛴다.

ADR 참조: ADR-006 / ADR-009 / ADR-012 / ADR-019 / ADR-024 / ADR-044 / ADR-046
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

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
    "MCST_FILE_DATASETS",
    "MCST_EXCLUDED_FILE_DATASETS",
    "McstDatasetSpec",
    "McstDialect",
    "file_rows_to_bundles",
    "parse_kcisa_coordinates",
]

MCST_PROVIDER_NAME: Final[str] = "python-mcst-api"
"""canonical provider name (ADR-024)."""

MCST_MARKER_COLOR: Final[str] = "P-12"
"""문화 계열 단일 marker color (T-220a 결정 유지)."""

_DEFAULT_MCST_ICON: Final[str] = "marker"

McstDialect = Literal["kcisa_common", "cntc_resrce", "split_coord", "korean_address"]
"""파일데이터 CSV 컬럼 방언 종류 (모듈 docstring 참조)."""


@dataclass(frozen=True, slots=True)
class McstDatasetSpec:
    """MCST 파일데이터 dataset 1종의 변환 메타 (slug 메타표 항목)."""

    slug: str
    """python-mcst-api 카탈로그 slug (``FileDataClient.iter_csv`` 인자)."""

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

    dialect: McstDialect
    """CSV 컬럼 방언 — 변환 함수의 컬럼 추출 분기."""


def _spec(
    slug: str,
    category: PlaceCategoryCode,
    place_kind: str,
    label: str,
    dialect: McstDialect,
    *,
    entity_type: str = "culture_place",
) -> McstDatasetSpec:
    return McstDatasetSpec(
        slug=slug,
        dataset_key=f"mcst_{slug}",
        category=category.value,
        place_kind=place_kind,
        entity_type=entity_type,
        label=label,
        dialect=dialect,
    )


MCST_FILE_DATASETS: Final[dict[str, McstDatasetSpec]] = {
    spec.slug: spec
    for spec in (
        # ── KCISA 공통 방언 A (8종) ───────────────────────────────────────
        _spec(
            "world_restaurants_csv",
            PlaceCategoryCode.FOOD_RESTAURANT,
            "world_restaurant",
            "세계음식 음식점",
            "kcisa_common",
        ),
        _spec(
            "pet_friendly_culture_facilities_csv",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "pet_friendly_culture_facility",
            "반려동물 동반 가능 문화시설",
            "kcisa_common",
        ),
        _spec(
            "barrier_free_places_csv",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "barrier_free_place",
            "무장애 관광지",
            "kcisa_common",
        ),
        _spec(
            "leisure_activity_facilities_csv",
            PlaceCategoryCode.TOURISM_ACTIVITY_LEISURE_SPORTS,
            "leisure_activity_facility",
            "레저활동 시설",
            "kcisa_common",
        ),
        _spec(
            "family_infant_culture_facilities_csv",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "family_culture_facility",
            "가족/영유아 동반 문화시설",
            "kcisa_common",
        ),
        _spec(
            "leisure_camping_facilities_csv",
            PlaceCategoryCode.LODGING_CAMPGROUND,
            "leisure_camping_facility",
            "레저 캠핑 시설",
            "kcisa_common",
        ),
        # 좌표 컬럼 없음(실측) — 주소 단서 경로.
        _spec(
            "leisure_classes_csv",
            PlaceCategoryCode.TOURISM_ACTIVITY,
            "leisure_class",
            "레저 클래스/강습",
            "kcisa_common",
        ),
        # TITLE 대신 PLACENAME, MEDIATITLE 보조(실측).
        _spec(
            "media_famous_places_csv",
            PlaceCategoryCode.TOURISM,
            "media_famous_place",
            "미디어콘텐츠 영상 촬영지",
            "kcisa_common",
        ),
        # ── CNTC_RESRCE 방언 (2종) ────────────────────────────────────────
        _spec(
            "independent_bookstores_csv",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "independent_bookstore",
            "독립서점",
            "cntc_resrce",
        ),
        _spec(
            "cafe_bookstores_csv",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "cafe_bookstore",
            "북카페",
            "cntc_resrce",
        ),
        # ── 분리좌표 방언 (2종) — 서점류와 동일 계열 ──────────────────────
        _spec(
            "children_bookstores_csv",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "children_bookstore",
            "아동서점",
            "split_coord",
        ),
        _spec(
            "used_bookstores_csv",
            PlaceCategoryCode.TOURISM_CULTURAL_FACILITY,
            "used_bookstore",
            "중고서점",
            "split_coord",
        ),
        # ── 한국어 주소-only (1종) — 좌표 없음, 지역+소재지 합성 주소 ─────
        _spec(
            "golf_courses_status",
            PlaceCategoryCode.TOURISM_ACTIVITY_GOLF,
            "golf_course",
            "전국 골프장 현황",
            "korean_address",
            entity_type="sports_facility",
        ),
    )
}
"""파일데이터 적재 13 dataset slug 메타표 (#395 + T-223b — 실측 헤더 기준)."""

MCST_EXCLUDED_FILE_DATASETS: Final[dict[str, str]] = {
    "tourism_attractions_csv": (
        "서지형 42컬럼(PUBLISHER/COLLECTIONDB/UCI 등) — POI가 아닌 기사/자료 "
        "레코드 혼재(실측 64,194행). place Feature로 부적합."
    ),
    "recommended_travel_destinations_csv": (
        "대한민국 정책브리핑 기사형(DESCRIPTION이 본문 HTML) — POI 아님."
    ),
    "public_libraries": (
        "도서관 통계(장서수/대출자수/자료구입비) — 시설 디렉토리 아님. "
        "구 ODCloud 디렉토리 경로(mcst_public_libraries/mcst_small_libraries)는 "
        "provider 재편으로 소멸 — 도서관 디렉토리 재적재는 후속 과제."
    ),
}
"""적재 제외 3 dataset과 사유 (#395 — 문서 `docs/mcst-feature-etl.md` §3)."""


# ── COORDINATES 파서 ─────────────────────────────────────────────────────

_COORD_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"^([NSEW])?\s*([+-]?\d+(?:\.\d+)?)$", re.IGNORECASE
)
_KOREA_LON_MIN: Final[float] = 124.0
_KOREA_LON_MAX: Final[float] = 132.0
_KOREA_LAT_MIN: Final[float] = 33.0
_KOREA_LAT_MAX: Final[float] = 43.0


def _in_korea_bbox(lon: float, lat: float) -> bool:
    return _KOREA_LON_MIN <= lon <= _KOREA_LON_MAX and _KOREA_LAT_MIN <= lat <= _KOREA_LAT_MAX


def _validated_lonlat(lon: float, lat: float) -> tuple[float, float] | None:
    """한국 bbox 검증 — 순서 뒤집힘이면 swap, 둘 다 아니면 None."""
    if _in_korea_bbox(lon, lat):
        return (lon, lat)
    if _in_korea_bbox(lat, lon):
        return (lat, lon)
    return None


def parse_kcisa_coordinates(text: str | None) -> tuple[float, float] | None:
    """KCISA ``COORDINATES`` 텍스트 → ``(lon, lat)`` (실측 2형식 + 공백 변형).

    - ``"N37.545904, E126.92094"`` — N/E 접두, lat-lon 순.
    - ``"35.86561079 , 128.6083915"`` / ``"37.54497283 126.9676467"`` — 평문
      lat-lon 순 (구분자 콤마/공백 변형).

    결과는 한국 bbox(lon 124~132, lat 33~43)로 검증하고 평문 순서 뒤집힘은
    bbox로 감지해 교정한다. 파싱 실패/범위 밖이면 ``None``(좌표 없음 처리 —
    주소 단서 경로).
    """
    if text is None:
        return None
    tokens = [token for token in re.split(r"[,\s]+", text.strip()) if token]
    if len(tokens) != 2:
        return None
    parsed: list[tuple[str | None, float]] = []
    for token in tokens:
        match = _COORD_TOKEN_RE.match(token)
        if match is None:
            return None
        axis = match.group(1).upper() if match.group(1) else None
        value = float(match.group(2))
        if axis == "S":
            axis, value = "N", -value
        elif axis == "W":
            axis, value = "E", -value
        parsed.append((axis, value))
    axes = [axis for axis, _value in parsed]
    if axes[0] is not None and axes[1] is not None:
        if set(axes) != {"N", "E"}:
            return None
        by_axis = dict(parsed)
        lat, lon = by_axis["N"], by_axis["E"]
        return (lon, lat) if _in_korea_bbox(lon, lat) else None
    # 평문(접두 없음/부분) — 실측 순서는 lat, lon.
    lat, lon = parsed[0][1], parsed[1][1]
    return _validated_lonlat(lon, lat)


# ── 컬럼 추출 helper ─────────────────────────────────────────────────────

_PLACEHOLDER_TEXTS: Final[frozenset[str]] = frozenset({"정보없음", "-"})
"""실측 CSV의 placeholder 값 — tel/url 등 보조 필드에서 None 처리."""


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


def _aux_text(row: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    """보조 필드(tel/url 등) — placeholder 값은 None."""
    text = _row_text(row, keys)
    if text is None or text in _PLACEHOLDER_TEXTS:
        return None
    return text


def _joined_categories(row: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    parts = [part for part in (_row_text(row, (key,)) for key in keys) if part]
    return " > ".join(parts) if parts else None


@dataclass(frozen=True, slots=True)
class _ExtractedRow:
    """방언별 추출 결과 — bundle 빌드 공통 입력."""

    name: str | None
    raw_address: str | None
    lonlat: tuple[float, float] | None
    facility_info: dict[str, Any]


def _extract_kcisa_common(row: Mapping[str, Any]) -> _ExtractedRow:
    """공통 방언 A — media는 PLACENAME/MEDIATITLE, leisure_classes는 좌표 없음."""
    return _ExtractedRow(
        name=_row_text(row, ("TITLE", "PLACENAME")),
        raw_address=_row_text(row, ("ADDRESS",)),
        lonlat=parse_kcisa_coordinates(_row_text(row, ("COORDINATES",))),
        facility_info={
            "source_category": _joined_categories(row, ("CATEGORY1", "CATEGORY2", "CATEGORY3")),
            "tel": _aux_text(row, ("TEL",)),
            "url": _aux_text(row, ("URL",)),
            "media_title": _row_text(row, ("MEDIATITLE",)),
            "operating_time": _row_text(row, ("OPERATINGTIME",)),
        },
    )


def _extract_cntc_resrce(row: Mapping[str, Any]) -> _ExtractedRow:
    return _ExtractedRow(
        name=_row_text(row, ("TITLE",)),
        raw_address=_row_text(row, ("ADDRESS",)),
        lonlat=parse_kcisa_coordinates(_row_text(row, ("COORDINATES",))),
        facility_info={
            "source_category": _row_text(row, ("SUBJECT_KEYWORD",)),
            "tel": _aux_text(row, ("CONTACT_POINT",)),
            # 안정 id처럼 보이나 명세 보증이 없어 자연키로는 쓰지 않고 보존만.
            "cntc_resrce_id": _row_text(row, ("CNTC_RESRCE_ID",)),
        },
    )


def _extract_split_coord(row: Mapping[str, Any]) -> _ExtractedRow:
    lat = _row_float(row, ("FCLTY_LA",))
    lon = _row_float(row, ("FCLTY_LO",))
    lonlat = _validated_lonlat(lon, lat) if lon is not None and lat is not None else None
    return _ExtractedRow(
        name=_row_text(row, ("FCLTY_NM",)),
        raw_address=_row_text(row, ("FCLTY_ROAD_NM_ADDR",)),
        lonlat=lonlat,
        facility_info={
            "source_category": _joined_categories(row, ("LCLAS_NM", "MLSFC_NM")),
            "tel": _aux_text(row, ("TEL_NO",)),
        },
    )


def _extract_korean_address(row: Mapping[str, Any]) -> _ExtractedRow:
    """골프장 현황 — 좌표 없음, ``지역``+``소재지`` 합성 주소 단서."""
    region = _row_text(row, ("지역",))
    location = _row_text(row, ("소재지",))
    if location is None:
        raw_address = region
    elif region is None or location.startswith(region):
        raw_address = location
    else:
        raw_address = f"{region} {location}"
    return _ExtractedRow(
        name=_row_text(row, ("이름",)),
        raw_address=raw_address,
        lonlat=None,
        facility_info={
            "source_category": _row_text(row, ("구분",)),
            "operator": _row_text(row, ("사업자",)),
            "hole_count": _row_text(row, ("홀",)),
        },
    )


_DIALECT_EXTRACTORS: Final[dict[McstDialect, Callable[[Mapping[str, Any]], _ExtractedRow]]] = {
    "kcisa_common": _extract_kcisa_common,
    "cntc_resrce": _extract_cntc_resrce,
    "split_coord": _extract_split_coord,
    "korean_address": _extract_korean_address,
}


# ── bundle 빌드 ──────────────────────────────────────────────────────────


def _coord_or_none(lonlat: tuple[float, float] | None) -> Coordinate | None:
    if lonlat is None:
        return None
    lon, lat = lonlat
    return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))


async def _resolve_address(
    coord: Coordinate | None,
    *,
    fallback_admin: str | None,
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
            (geo.sigungu_code if geo is not None else None) or extract_sigungu_code(bjd_code)
        ),
        sido_code=((geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code)),
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
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
    natural_key = "::".join([name, raw_address or ""])
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
        name=name,
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
    return FeatureBundle(feature=feature, source_record=source_record, source_link=source_link)


async def file_rows_to_bundles(
    rows: Iterable[Mapping[str, Any]],
    *,
    slug: str,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """MCST 파일데이터 CSV rows → place ``FeatureBundle`` (slug 메타표 기반).

    ``slug``는 ``MCST_FILE_DATASETS`` 키여야 한다(아니면 ``KeyError`` — 호출
    오타가 조용히 빈 dataset이 되지 않게). 컬럼 추출은 spec의 방언으로 분기하고,
    이름이 없거나 좌표·주소가 모두 없는 row는 식별/위치 단서가 없어 건너뛴다.
    """
    spec = MCST_FILE_DATASETS[slug]
    extractor = _DIALECT_EXTRACTORS[spec.dialect]
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    bundles: list[FeatureBundle] = []
    for row in rows:
        extracted = extractor(row)
        name = normalize_korean_text(extracted.name)
        raw_address = normalize_korean_text(extracted.raw_address)
        coord = _coord_or_none(extracted.lonlat)
        if name is None or (coord is None and raw_address is None):
            continue
        address = await _resolve_address(
            coord,
            fallback_admin=raw_address,
            reverse_geocoder=geocoder,
        )
        raw_data = {str(key): value for key, value in row.items()}
        bundles.append(
            _build_bundle(
                spec=spec,
                name=name,
                coord=coord,
                address=address,
                raw_address=raw_address,
                facility_info=extracted.facility_info,
                raw_data=raw_data,
                fetched_at=fetched_at,
            )
        )
    return bundles
