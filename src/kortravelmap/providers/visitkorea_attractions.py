"""``kortravelmap.providers.visitkorea_attractions`` — TourAPI 관광지(contentTypeId 12) → place.

한국관광공사 국문 관광정보 서비스(KorService2) ``areaBasedList2``의 관광지 목록을
**1차 source** place Feature로 만든다(#1459 — 산막이옛길·고군산군도·부산타워 같은 대표
관광지가 운영 Map에 없었다). 축제(:mod:`kortravelmap.providers.visitkorea`)는 enrichment지만
본 dataset은 Feature를 직접 만든다.

| dataset_key | kind | 함수 |
|-------------|------|------|
| ``visitkorea_tourist_attractions`` | ``place`` | ``tourapi_attractions_to_bundles`` |

입력·자연키·분류
---------------

- 입력 shape는 :class:`VisitKoreaAttractionItem` ``Protocol``이다. ``python-visitkorea-api``의
  ``TourItem``이 그대로 만족한다(ADR-006 — wrapper 없음).
- 자연키는 TourAPI ``contentid``다(원천의 안정 관리번호).
- 분류는 2025년 KorService2의 **신 분류체계** ``lclsSystm1/2/3``으로 정한다. 옛
  ``cat1/cat2/cat3``는 KorService2 목록 응답에서 비어 온다(2026-11-09 운영 키 실측: 1,000행 모두
  None). 대응표는 :data:`TOURAPI_LCLS3_CATEGORY` → :data:`TOURAPI_LCLS2_CATEGORY` →
  :data:`TOURAPI_LCLS1_CATEGORY` 순으로 찾고, 셋 다 없으면 관광 ``01000000``이다
  (``docs/etl/visitkorea-tourist-attraction-etl.md`` §3).

상세(overview·homepage)
----------------------

``detailCommon2``는 항목마다 1회라 일일 한도(오퍼레이션당 1,000)를 넘는다. 상세는 적재가
예산 안에서 채우고(:func:`plan_attraction_details`), 채운 값은 ``raw_data``에 남아 다음 적재가
이어 쓴다. **상세를 받았는데 비어 있으면 빈 문자열**로 둔다 — ``None``은 "아직 받지 않았다"이다.

라이선스
--------

TourAPI 콘텐츠는 항목마다 공공누리 유형(``cpyrhtDivCd``: Type1 출처표시 / Type3 출처표시·변경금지)을
갖는다. 이미지·설명은 원본 그대로만 참조하고(가공 없음), 출처(한국관광공사)와 유형을
``facility_info``에 남긴다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import unescape
from typing import Any, Final, Protocol, runtime_checkable

from pydantic import ValidationError

from kortravelmap.category import PlaceCategoryCode, mapbox_maki_icon_or_none
from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
    normalize_phone_number,
)
from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureFileSource,
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
    "VisitKoreaAttractionItem",
    "AttractionDetailPlan",
    "attraction_category",
    "plan_attraction_details",
    "tourapi_attractions_to_bundles",
    "DATASET_KEY_VISITKOREA_ATTRACTIONS",
    "TOURAPI_ATTRACTION_CONTENT_TYPE_ID",
    "TOURAPI_LCLS1_CATEGORY",
    "TOURAPI_LCLS2_CATEGORY",
    "TOURAPI_LCLS3_CATEGORY",
    "ATTRACTION_MARKER_COLOR",
    "ATTRACTION_PLACE_KIND",
]

_PROVIDER_NAME: Final[str] = "python-visitkorea-api"
"""canonical provider name (ADR-024) — :mod:`visitkorea`의 ``VISITKOREA_PROVIDER_NAME``과 같다."""

DATASET_KEY_VISITKOREA_ATTRACTIONS: Final[str] = "visitkorea_tourist_attractions"
"""``provider_sync.source_records.dataset_key`` — TourAPI 관광지(contentTypeId 12)."""

TOURAPI_ATTRACTION_CONTENT_TYPE_ID: Final[str] = "12"
"""TourAPI 관광타입 — 관광지."""

_ENTITY_TYPE: Final[str] = "tourist_attraction"
ATTRACTION_PLACE_KIND: Final[str] = "tourapi_attraction"
ATTRACTION_MARKER_COLOR: Final[str] = "P-02"
"""관광지 표준데이터(``TOURIST_MARKER_COLOR``)와 같은 팔레트."""
_DEFAULT_ICON: Final[str] = "attraction"
_ATTRIBUTION: Final[str] = "한국관광공사"

_KOGL_LICENSE: Final[dict[str, str]] = {
    "Type1": "공공누리 제1유형(출처표시)",
    "Type3": "공공누리 제3유형(출처표시·변경금지)",
}

_P = PlaceCategoryCode

TOURAPI_LCLS3_CATEGORY: Final[Mapping[str, PlaceCategoryCode]] = {
    # 자연관광(NA)
    "NA010100": _P.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY,  # 산, 고개, 오름, 봉우리
    "NA010200": _P.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL,  # 숲
    "NA010300": _P.TOURISM_NATURAL_LANDSCAPE_WATERFALL_CAVE,  # 폭포
    "NA010400": _P.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY,  # 계곡
    "NA010500": _P.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY,  # 약수터
    "NA020900": _P.TOURISM_NATURE_BEACH,  # 해변·해수욕장
    "NA030100": _P.TOURISM_NATURAL_LANDSCAPE_WATERFALL_CAVE,  # 동굴
    "NA030400": _P.TOURISM_NATURAL_LANDSCAPE_RIVER_LAKE,  # 생태습지
    "NA040100": _P.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_NATIONAL_PARK,  # 국립공원
    "NA040200": _P.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_LOCAL_PARK,  # 도립공원
    "NA040300": _P.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_LOCAL_PARK,  # 군립공원
    "NA040600": _P.LODGING_RECREATION_FOREST,  # 자연휴양림 (krforest와 같은 자리)
    "NA040700": _P.TOURISM_BOTANICAL,  # 수목원·정원
    # 역사관광(HS)
    "HS010100": _P.TOURISM_HERITAGE_PALACE_ROYAL_TOMB,  # 고궁
    "HS010400": _P.TOURISM_HERITAGE_HANOK_FOLK_VILLAGE,  # 고택
    "HS010500": _P.TOURISM_HERITAGE_HANOK_FOLK_VILLAGE,  # 생가
    "HS010600": _P.TOURISM_HERITAGE_HANOK_FOLK_VILLAGE,  # 민속마을
    "HS010800": _P.TOURISM_HERITAGE_PALACE_ROYAL_TOMB,  # 고분, 능
    "HS011200": _P.TOURISM_HERITAGE,  # 기타역사유적지
    "HS030100": _P.TOURISM_HERITAGE_TEMPLE,  # 불교
    "HS030200": _P.TOURISM_HERITAGE,  # 기독교
    "HS030300": _P.TOURISM_HERITAGE,  # 이슬람
    "HS030400": _P.TOURISM_HERITAGE,  # 기타 종교성지
    # 문화관광(VE)
    "VE010200": _P.TOURISM_NATURE_OBSERVATORY,  # 타워 / 전망대
    "VE010400": _P.TOURISM_NATURE_PARK,  # 분수
    "VE010700": _P.TOURISM_NATURAL_LANDSCAPE_RIVER_LAKE,  # 댐
    "VE010800": _P.TOURISM_NATURE_LIGHTHOUSE,  # 등대
    "VE020100": _P.TOURISM_THEME_PARK_AMUSEMENT,  # 테마파크
    "VE020200": _P.TOURISM_THEME_PARK_WATER,  # 워터파크
    "VE020300": _P.TOURISM_THEME_PARK_ZOO,  # 동물원
    "VE020400": _P.TOURISM_THEME_PARK_AQUARIUM,  # 수족관 / 아쿠아리움
    "VE020500": _P.TOURISM_CULTURAL_FACILITY,  # 천문대
    "VE040300": _P.TOURISM_ACTIVITY_TREKKING,  # 둘레길
    "VE050200": _P.LODGING_RESORT,  # 리조트
    "VE060100": _P.TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL,  # 공연장
    "VE060200": _P.TOURISM_CULTURAL_FACILITY_CINEMA,  # 영화관
    "VE070100": _P.TOURISM_CULTURAL_FACILITY_MUSEUM,  # 박물관
    "VE070200": _P.TOURISM_CULTURAL_FACILITY_MUSEUM,  # 기념관
    "VE070500": _P.TOURISM_CULTURAL_FACILITY_MUSEUM,  # 과학관
    "VE070600": _P.TOURISM_CULTURAL_FACILITY_ART,  # 미술관/화랑
    "VE090100": _P.TOURISM_CULTURAL_FACILITY_CULTURE_CENTER,  # 한국문화원
    "VE090200": _P.TOURISM_CULTURAL_FACILITY_CULTURE_CENTER,  # 외국문화원
    "VE090300": _P.TOURISM_CULTURAL_FACILITY_LIBRARY,  # 도서관
    "VE110100": _P.TRANSPORT_AIRPORT,  # 공항
    "VE110200": _P.TRANSPORT_STOP_TRAIN,  # 기차역
    "VE110400": _P.TRANSPORT_FERRY_TERMINAL,  # 여객선터미널
    "VE110500": _P.TRANSPORT_REST_AREA_HIGHWAY,  # 고속도로휴게소
    "VE110600": _P.TRANSPORT_STOP_SUBWAY,  # 지하철
    # 체험관광(EX)
    "EX040100": _P.TOURISM_HERITAGE_TEMPLE,  # 템플스테이
    "EX040200": _P.TOURISM_HERITAGE_TEMPLE,  # 사찰문화체험
    "EX050100": _P.HOT_SPRING_SPA_HOT_SPRING,  # 온천 / 사우나 / 스파
    "EX050200": _P.HOT_SPRING_SPA_SAUNA,  # 찜질방
    "EX070100": _P.TOURISM_ACTIVITY_CRUISE,  # 유람선/잠수함관광
}
"""TourAPI 신 분류 3단계(``lclsSystm3``) → Map category. 여기 없는 코드는 2단계 표로 내려간다."""

TOURAPI_LCLS2_CATEGORY: Final[Mapping[str, PlaceCategoryCode]] = {
    "NA01": _P.TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY,  # 자연경관(산)
    "NA02": _P.TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND,  # 자연경관(하천·해양) — 강·호수는 아래
    "NA03": _P.TOURISM_NATURAL_LANDSCAPE,  # 자연생태
    "NA04": _P.TOURISM_NATURAL_LANDSCAPE,  # 자연공원(지질공원·생태관광지)
    "NA05": _P.TOURISM_NATURAL_LANDSCAPE,  # 기타자연관광
    "HS01": _P.TOURISM_HERITAGE_HISTORIC_SITE,  # 역사유적지
    "HS02": _P.TOURISM_HERITAGE_HISTORIC_SITE,  # 역사유물
    "HS03": _P.TOURISM_HERITAGE,  # 종교성지
    "HS04": _P.TOURISM_HERITAGE_HISTORIC_SITE,  # 안보관광지
    "VE01": _P.TOURISM,  # 랜드마크관광(건물·다리·동상·터널·기타)
    "VE02": _P.TOURISM_THEME_PARK,  # 테마공원
    "VE03": _P.TOURISM_NATURE_PARK,  # 도시공원
    "VE04": _P.TOURISM,  # 도시·지역문화관광(골목길·마을)
    "VE05": _P.TOURISM,  # 복합관광시설(관광단지)
    "VE06": _P.TOURISM_CULTURAL_FACILITY,  # 공연시설
    "VE07": _P.TOURISM_CULTURAL_FACILITY,  # 전시시설(전시관·컨벤션센터)
    "VE08": _P.TOURISM_CULTURAL_FACILITY,  # 행사시설
    "VE09": _P.TOURISM_CULTURAL_FACILITY,  # 교육시설
    "VE10": _P.TOURISM_ACTIVITY_LEISURE_SPORTS,  # 레저스포츠시설
    "VE11": _P.TRANSPORT,  # 교통시설(버스터미널 등)
    "VE12": _P.TOURISM,  # 기타문화관광지
    "EX05": _P.HOT_SPRING_SPA_THERAPY,  # 웰니스관광(한방·명상·뷰티 등)
    "EX01": _P.TOURISM_ACTIVITY,  # 전통체험
    "EX02": _P.TOURISM_ACTIVITY,  # 공예체험
    "EX03": _P.TOURISM_ACTIVITY,  # 농·산·어촌 체험
    "EX04": _P.TOURISM_HERITAGE_TEMPLE,  # 산사체험
    "EX06": _P.TOURISM,  # 산업관광
    "EX07": _P.TOURISM_ACTIVITY,  # 기타체험
}
"""``lclsSystm2`` → Map category(3단계 표에 없을 때)."""

_NA02_RIVER_LAKE: Final[frozenset[str]] = frozenset(
    {"NA020100", "NA020200", "NA020300", "NA020400"}  # 강·호수·저수지·연못/늪
)

TOURAPI_LCLS1_CATEGORY: Final[Mapping[str, PlaceCategoryCode]] = {
    "NA": _P.TOURISM_NATURAL_LANDSCAPE,
    "HS": _P.TOURISM_HERITAGE,
    "VE": _P.TOURISM,
    "EX": _P.TOURISM_ACTIVITY,
}
"""``lclsSystm1`` → Map category(2단계 표에도 없을 때)."""


def attraction_category(
    lcls_systm1: str | None, lcls_systm2: str | None, lcls_systm3: str | None
) -> str:
    """TourAPI 신 분류 → Map category code(8자리). 모르는 코드는 상위 단계로 내려간다."""
    lcls3 = (lcls_systm3 or "").strip()
    lcls2 = (lcls_systm2 or "").strip() or lcls3[:4]
    lcls1 = (lcls_systm1 or "").strip() or lcls2[:2]
    if lcls3 in TOURAPI_LCLS3_CATEGORY:
        return TOURAPI_LCLS3_CATEGORY[lcls3].value
    if lcls3 in _NA02_RIVER_LAKE:
        return _P.TOURISM_NATURAL_LANDSCAPE_RIVER_LAKE.value
    if lcls2 in TOURAPI_LCLS2_CATEGORY:
        return TOURAPI_LCLS2_CATEGORY[lcls2].value
    if lcls1 in TOURAPI_LCLS1_CATEGORY:
        return TOURAPI_LCLS1_CATEGORY[lcls1].value
    return _P.TOURISM.value


# -- 입력 Protocol --------------------------------------------------------


@runtime_checkable
class VisitKoreaAttractionItem(Protocol):
    """TourAPI ``areaBasedList2`` 관광지 한 item (``visitkorea.models.TourItem``이 만족)."""

    content_id: str | None
    content_type_id: str | None
    title: str | None
    addr1: str | None
    addr2: str | None
    zipcode: str | None
    tel: str | None
    first_image: str | None
    first_image2: str | None
    map_x: float | None
    map_y: float | None
    lcls_systm1: str | None
    lcls_systm2: str | None
    lcls_systm3: str | None
    l_dong_regn_cd: str | None
    l_dong_signgu_cd: str | None
    created_time: datetime | None
    modified_time: datetime | None
    copyright_division_code: str | None
    overview: str | None
    """``detailCommon2`` 상세 설명. ``None``=상세 미수신, ``""``=받았으나 비어 있음."""
    homepage: str | None
    """``detailCommon2`` 홈페이지(HTML anchor 포함 가능). ``None``/``""`` 의미는 overview와 같다."""


# -- 상세 예산 계획 -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttractionDetailPlan:
    """한 적재의 상세(``detailCommon2``) 계획.

    ``reuse``: contentid → 저장된 (overview, homepage) — 목록 ``modified_time``이 저장값과 같다.
    ``fetch``: 이번에 상세를 받을 contentid(예산 안, 우선순위 순).
    ``deferred``: 예산 밖이라 이번에는 상세 없이 적재하는 contentid 수.
    """

    reuse: Mapping[str, tuple[str, str]]
    fetch: tuple[str, ...]
    deferred: int


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def plan_attraction_details(
    items: Iterable[VisitKoreaAttractionItem],
    stored: Mapping[str, Mapping[str, Any]],
    *,
    budget: int,
) -> AttractionDetailPlan:
    """저장된 상세를 이어 쓸 항목과 이번에 받을 항목을 정한다(일일 한도 보호).

    - 저장 ``raw_data``의 ``modified_time``이 목록과 같고 ``overview``가 ``None``이 아니면
      (=상세를 받은 적이 있다) 저장값을 이어 쓴다.
    - 나머지는 상세가 필요하다. **수정된 항목(저장값은 있으나 낡음)을 먼저**, 한 번도 받지
      않은 항목을 그다음으로, 각각 contentid 순으로 ``budget``개까지 고른다. 낡은 상세를
      예산 밖에서 이어 쓰지 않는다 — 이어 쓰면 다음 적재가 그것을 최신으로 오인한다.
    """
    reuse: dict[str, tuple[str, str]] = {}
    stale: list[str] = []
    missing: list[str] = []
    for item in items:
        content_id = (item.content_id or "").strip()
        if not content_id:
            continue
        raw = stored.get(content_id)
        overview = raw.get("overview") if raw is not None else None
        if raw is not None and isinstance(overview, str):
            if raw.get("modified_time") == _iso(item.modified_time):
                homepage = raw.get("homepage")
                reuse[content_id] = (overview, homepage if isinstance(homepage, str) else "")
                continue
            stale.append(content_id)
        else:
            missing.append(content_id)
    ordered = sorted(set(stale)) + sorted(set(missing) - set(stale))
    limit = max(budget, 0)
    return AttractionDetailPlan(
        reuse=reuse, fetch=tuple(ordered[:limit]), deferred=max(len(ordered) - limit, 0)
    )


# -- 변환 -----------------------------------------------------------------

_HREF_RE: Final = re.compile(r"""href\s*=\s*["']?(https?://[^"'\s>]+)""", re.IGNORECASE)
_URL_RE: Final = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_TAG_RE: Final = re.compile(r"<[^>]+>")
_BR_RE: Final = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ROAD_RE: Final = re.compile(r"\S+(?:로|길)\s*\d")


def _homepage_url(value: str | None) -> str | None:
    """TourAPI homepage(``<a href="...">``가 흔하다) → 첫 http(s) URL."""
    text = unescape(value or "").strip()
    if not text:
        return None
    href = _HREF_RE.search(text)
    if href is not None:
        return href.group(1)
    bare = _URL_RE.search(text)
    return bare.group(0) if bare is not None else None


def _plain_text(value: str | None) -> str | None:
    """overview의 ``<br>``·태그·HTML entity를 걷어 낸 본문(없으면 None)."""
    if not value:
        return None
    text = _TAG_RE.sub("", _BR_RE.sub("\n", value))
    lines = [" ".join(unescape(line).split()) for line in text.splitlines()]
    joined = "\n".join(line for line in lines if line)
    return joined or None


def _coordinate(map_x: float | None, map_y: float | None) -> Coordinate | None:
    """TourAPI ``mapx``(경도)·``mapy``(위도) WGS84 → ``Coordinate``. 결측·0·범위 밖은 None."""
    if not map_x or not map_y:
        return None
    try:
        return Coordinate(lon=Decimal(str(map_x)), lat=Decimal(str(map_y)))
    except ValidationError:
        return None


def _split_address(addr1: str | None) -> tuple[str | None, str | None]:
    """addr1 → (도로명, 지번). TourAPI는 한 칸에 둘 중 하나를 준다."""
    text = normalize_korean_text(addr1)
    if text is None:
        return None, None
    return (text, None) if _ROAD_RE.search(text) else (None, text)


def _zipcode(value: str | None) -> str | None:
    """5자리 우편번호만 쓴다(옛 6자리 ``123-456`` 표기는 버린다)."""
    text = (value or "").strip()
    return text if len(text) == 5 and text.isdigit() else None


def _sigungu_from_ldong(regn: str | None, signgu: str | None) -> str | None:
    """TourAPI 법정동 시도(2)+시군구(3) 코드 → 5자리 시군구 코드(형식이 맞을 때만)."""
    code = f"{(regn or '').strip()}{(signgu or '').strip()}"
    return code if len(code) == 5 and code.isdigit() else None


def _file_sources(
    *,
    feature_id: str,
    source_record_key: str,
    primary: str | None,
    thumbnail: str | None,
    alt_text: str,
) -> list[FeatureFileSource]:
    """대표·썸네일 이미지 URL → ``FeatureFileSource``(원본 참조, 가공 없음 — 공공누리 유형 준수)."""
    sources: list[FeatureFileSource] = []
    for role, url, order in (("primary", primary, 0), ("thumbnail", thumbnail, 1)):
        if not url or (role == "thumbnail" and url == primary):
            continue
        sources.append(
            FeatureFileSource(
                feature_id=feature_id,
                source_url=url,
                role=role,
                display_order=order,
                file_type="image",
                alt_text=alt_text,
                provider=normalize_provider_name(_PROVIDER_NAME),
                dataset_key=DATASET_KEY_VISITKOREA_ATTRACTIONS,
                source_record_key=source_record_key,
            )
        )
    return sources


async def _attraction_to_bundle(
    item: VisitKoreaAttractionItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle | None:
    content_id = (item.content_id or "").strip()
    name = normalize_korean_text(item.title)
    if not content_id or name is None:
        return None
    # raw_data 키는 TourItem 필드 이름 그대로다 — replay가 ``TourItem.model_validate``로 되살린다.
    raw_data: dict[str, Any] = {
        "content_id": item.content_id,
        "content_type_id": item.content_type_id,
        "title": item.title,
        "addr1": item.addr1,
        "addr2": item.addr2,
        "zipcode": item.zipcode,
        "tel": item.tel,
        "first_image": item.first_image,
        "first_image2": item.first_image2,
        "map_x": str(item.map_x) if item.map_x is not None else None,
        "map_y": str(item.map_y) if item.map_y is not None else None,
        "lcls_systm1": item.lcls_systm1,
        "lcls_systm2": item.lcls_systm2,
        "lcls_systm3": item.lcls_systm3,
        "l_dong_regn_cd": item.l_dong_regn_cd,
        "l_dong_signgu_cd": item.l_dong_signgu_cd,
        "created_time": _iso(item.created_time),
        "modified_time": _iso(item.modified_time),
        "copyright_division_code": item.copyright_division_code,
        "overview": item.overview,
        "homepage": item.homepage,
    }
    coord = _coordinate(item.map_x, item.map_y)
    road_text, legal_text = _split_address(item.addr1)
    detail_text = normalize_korean_text(item.addr2)

    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    if (geo is None or geo.bjd_code is None) and address_resolver is not None:
        resolved = await address_resolver(Address(road=road_text, legal=legal_text))
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
    bjd_code = geo.bjd_code if geo is not None else None
    sigungu_code = (
        (geo.sigungu_code if geo is not None else None)
        or extract_sigungu_code(bjd_code)
        or _sigungu_from_ldong(item.l_dong_regn_cd, item.l_dong_signgu_cd)
    )
    sido_code = (
        (geo.sido_code if geo is not None else None)
        or extract_sido_code(bjd_code)
        or extract_sido_code(sigungu_code)
    )
    address = Address(
        road=road_text or (geo.road if geo is not None else None),
        legal=legal_text or (geo.legal if geo is not None else None),
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=geo.road_name_code if geo is not None else None,
        zipcode=(geo.zipcode if geo is not None else None) or _zipcode(item.zipcode),
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )

    category = attraction_category(item.lcls_systm1, item.lcls_systm2, item.lcls_systm3)
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=_PROVIDER_NAME,
        dataset_key=DATASET_KEY_VISITKOREA_ATTRACTIONS,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=content_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=category,
        source_type=f"{_PROVIDER_NAME}:{DATASET_KEY_VISITKOREA_ATTRACTIONS}",
        source_natural_key=content_id,
    )
    phone = normalize_phone_number(item.tel)
    license_code = (item.copyright_division_code or "").strip() or None
    facility_info: dict[str, Any] = {
        "tourapi_content_id": content_id,
        "tourapi_content_type_id": item.content_type_id,
        "lcls_systm3": item.lcls_systm3,
        "address_detail": detail_text,
        "overview": _plain_text(item.overview),
        "homepage_url": _homepage_url(item.homepage),
        "image_url": item.first_image or None,
        "thumbnail_url": item.first_image2 or None,
        "attribution": _ATTRIBUTION,
        "license": _KOGL_LICENSE.get(license_code or "", license_code),
        "modified_time": _iso(item.modified_time),
    }
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=content_id,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coord,
        address=address,
        category=category,
        marker_icon=mapbox_maki_icon_or_none(category) or _DEFAULT_ICON,
        marker_color=ATTRACTION_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=ATTRACTION_PLACE_KIND,
            phones=[phone] if phone else [],
            facility_info={k: v for k, v in facility_info.items() if v is not None},
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(_PROVIDER_NAME),
        dataset_key=DATASET_KEY_VISITKOREA_ATTRACTIONS,
        source_entity_type=_ENTITY_TYPE,
        source_entity_id=content_id,
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
        file_sources=_file_sources(
            feature_id=feature_id,
            source_record_key=source_record_key,
            primary=item.first_image,
            thumbnail=item.first_image2,
            alt_text=name,
        ),
    )


async def tourapi_attractions_to_bundles(
    items: Iterable[VisitKoreaAttractionItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """TourAPI 관광지 items → place ``FeatureBundle`` (자연키 contentid).

    - 좌표는 원천 ``mapx``/``mapy``(WGS84)이고, 역지오코딩으로 법정동 코드를 채운다. 역지오코딩이
      실패하면 주소 해석, 그래도 없으면 TourAPI 법정동 시도·시군구 코드로 시군구까지만 채운다.
    - contentid나 이름이 없는 행은 건너뛴다. 같은 contentid가 두 번 오면(페이지 경계에서 목록이
      밀린 경우) 처음 것 하나만 남긴다 — 내용이 다르면 payload hash가 작은 쪽(결정적).
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    resolver = cached_address_resolver(address_resolver) if address_resolver is not None else None
    chosen: dict[str, FeatureBundle] = {}
    order: list[str] = []
    for item in items:
        bundle = await _attraction_to_bundle(
            item, fetched_at=fetched_at, reverse_geocoder=geocoder, address_resolver=resolver
        )
        if bundle is None:
            continue
        key = bundle.source_record.source_entity_id
        kept = chosen.get(key)
        if kept is None:
            order.append(key)
            chosen[key] = bundle
        elif bundle.source_record.raw_payload_hash < kept.source_record.raw_payload_hash:
            chosen[key] = bundle
    return [chosen[key] for key in order]
