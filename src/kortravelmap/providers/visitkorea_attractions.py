"""``kortravelmap.providers.visitkorea_attractions`` — TourAPI 관광지·문화시설·레포츠 → place.

한국관광공사 국문 관광정보 서비스(KorService2) ``areaBasedList2``의 관광지 목록을
**1차 source** place Feature로 만든다(#1459 — 산막이옛길·고군산군도·부산타워 같은 대표
관광지가 운영 Map에 없었다). 축제(:mod:`kortravelmap.providers.visitkorea`, 같은 서비스의
``searchFestival2``)도 2026-11-10부터 1차 event source다 — 둘이 ``detailCommon2`` 일일 한도를
나눠 쓴다.

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
from typing import Any, Final, Literal, Protocol, runtime_checkable

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
from kortravelmap.core.visitor_text import DESCRIPTION_MAX, clean_text, http_url
from kortravelmap.dto import (
    VISITOR_INFO_KEY,
    AccessibilityGroup,
    AccessibilityNote,
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureFileSource,
    FeatureKind,
    PetPolicy,
    PlaceDetail,
    PlaceImage,
    PlaceVisitorInfo,
    SourceLink,
    SourceRecord,
    SourceRole,
    kogl_license,
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
    "TourApiDetailOp",
    "TourApiDetailOpsPlan",
    "TourApiDetailRequest",
    "merge_tourapi_detail_ops",
    "plan_tourapi_detail_ops",
    "tourapi_visitor_info",
    "TOURAPI_ACCESSIBILITY_FIELDS",
    "TOURAPI_DETAIL_OPS",
    "TOURAPI_DETAIL_RAW_KEY",
    "TOURAPI_INTRO_RAW_KEYS",
    "TOURAPI_MAX_IMAGES",
    "TOURAPI_PET_FIELDS",
    "attraction_category",
    "plan_attraction_details",
    "tourapi_attractions_to_bundles",
    "DATASET_KEY_VISITKOREA_ATTRACTIONS",
    "TOURAPI_ATTRACTION_CONTENT_TYPE_ID",
    "TOURAPI_PLACE_CONTENT_TYPE_IDS",
    "TOURAPI_LCLS1_CATEGORY",
    "TOURAPI_LCLS2_CATEGORY",
    "TOURAPI_LCLS3_CATEGORY",
    "ATTRACTION_MARKER_COLOR",
    "ATTRACTION_PLACE_KIND",
]

_PROVIDER_NAME: Final[str] = "python-visitkorea-api"
"""canonical provider name (ADR-024) — :mod:`visitkorea`의 ``VISITKOREA_PROVIDER_NAME``과 같다."""

DATASET_KEY_VISITKOREA_ATTRACTIONS: Final[str] = "visitkorea_tourist_attractions"
"""``provider_sync.source_records.dataset_key`` — TourAPI 관광지(12)·문화시설(14)·레포츠(28)."""

TOURAPI_ATTRACTION_CONTENT_TYPE_ID: Final[str] = "12"
"""TourAPI 관광타입 — 관광지."""

TOURAPI_PLACE_CONTENT_TYPE_IDS: Final[tuple[str, ...]] = ("12", "14", "28")
"""이 dataset이 적재하는 TourAPI 관광타입 — 관광지(12)·문화시설(14)·레포츠(28)(#1459).

숙박(32)·음식점(39)·쇼핑(38)은 MOIS 인허가가 정본이고, 축제(15)는 event·여행코스(25)는 route라
넣지 않는다."""

_PLACE_KIND_BY_CONTENT_TYPE: Final[dict[str, str]] = {
    "12": "tourapi_attraction",
    "14": "tourapi_culture_facility",
    "28": "tourapi_leisure",
}

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
    # 체험관광(EX)
    "EX040100": _P.TOURISM_HERITAGE_TEMPLE,  # 템플스테이
    "EX040200": _P.TOURISM_HERITAGE_TEMPLE,  # 사찰문화체험
    "EX050100": _P.HOT_SPRING_SPA_HOT_SPRING,  # 온천 / 사우나 / 스파
    "EX050200": _P.HOT_SPRING_SPA_SAUNA,  # 찜질방
    "EX070100": _P.TOURISM_ACTIVITY_CRUISE,  # 유람선/잠수함관광
    # 문화시설(14) — 2026-11-09 운영 키 2,753건의 3단계 분포 기준
    "VE120100": _P.TOURISM_CULTURAL_FACILITY,  # 서점(MCST 서점과 같은 자리)
    "VE120300": _P.TOURISM_CULTURAL_FACILITY,  # 기타문화시설(14에서 154건)
    # 레포츠(28) — 3,717건. 레저스포츠(LS)는 대부분 2단계 표의 레저스포츠로 간다.
    "LS010400": _P.TOURISM_ACTIVITY_GOLF,  # 골프
    # 숙박 분류(AC)가 레포츠에 섞여 온다 — 캠핑장 1,948건(52%)·펜션
    "AC050100": _P.LODGING_CAMPGROUND,  # 일반야영장
    "AC050200": _P.LODGING_CAMPGROUND_AUTO,  # 오토캠핑장
    "AC050300": _P.LODGING_CAMPGROUND_CARAVAN_RENTAL,  # 카라반
    "AC050400": _P.LODGING_CAMPGROUND_GLAMPING,  # 글램핑장
    "AC030100": _P.LODGING_PENSION,  # 펜션
    "AC030300": _P.LODGING_PENSION_RURAL,  # 농어촌민박
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
    "VE12": _P.TOURISM,  # 기타문화관광지
    "EX05": _P.HOT_SPRING_SPA_THERAPY,  # 웰니스관광(한방·명상·뷰티 등)
    "EX01": _P.TOURISM_ACTIVITY,  # 전통체험
    "EX02": _P.TOURISM_ACTIVITY,  # 공예체험
    "EX03": _P.TOURISM_ACTIVITY,  # 농·산·어촌 체험
    "EX04": _P.TOURISM_HERITAGE_TEMPLE,  # 산사체험
    "EX06": _P.TOURISM,  # 산업관광
    "EX07": _P.TOURISM_ACTIVITY,  # 기타체험
    "LS01": _P.TOURISM_ACTIVITY_LEISURE_SPORTS,  # 육상레저스포츠
    "LS02": _P.TOURISM_ACTIVITY_LEISURE_SPORTS,  # 수상레저스포츠
    "LS03": _P.TOURISM_ACTIVITY_LEISURE_SPORTS,  # 항공레저스포츠
    "LS04": _P.TOURISM_ACTIVITY_LEISURE_SPORTS,  # 복합레저스포츠
    "AC05": _P.LODGING_CAMPGROUND,  # 캠핑
    "AC03": _P.LODGING_PENSION,  # 펜션/민박
}
"""``lclsSystm2`` → Map category(3단계 표에 없을 때).

관광지(12) 목록에 오는 것은 NA·HS·EX 전부와 VE01~VE05·VE020500이고(공식 신분류체계 연계
정의서), VE06~VE10·VE12는 문화시설(14), LS·AC·VE10은 레포츠(28)에서 온다
(``docs/etl/visitkorea-tourist-attraction-etl.md`` §3.1)."""

#: 적재하지 않는 2단계 — 교통시설(VE11: 공항·기차역·여객선·휴게소·지하철)은 transport 원천
#: (``kor-travel-transport``)이 정본이라, TourAPI 행을 더하면 dedup 쌍 없이 중복 place가 된다.
_SKIPPED_LCLS2: Final[frozenset[str]] = frozenset({"VE11"})


def _skipped(lcls_systm2: str | None, lcls_systm3: str | None) -> bool:
    return ((lcls_systm2 or "").strip() or (lcls_systm3 or "").strip()[:4]) in _SKIPPED_LCLS2

_NA02_RIVER_LAKE: Final[frozenset[str]] = frozenset(
    {"NA020100", "NA020200", "NA020300", "NA020400"}  # 강·호수·저수지·연못/늪
)

TOURAPI_LCLS1_CATEGORY: Final[Mapping[str, PlaceCategoryCode]] = {
    "NA": _P.TOURISM_NATURAL_LANDSCAPE,
    "HS": _P.TOURISM_HERITAGE,
    "VE": _P.TOURISM,
    "EX": _P.TOURISM_ACTIVITY,
    "LS": _P.TOURISM_ACTIVITY_LEISURE_SPORTS,
    "AC": _P.LODGING,
}
"""``lclsSystm1`` → Map category(2단계 표에도 없을 때)."""


#: "기타육상레저스포츠"(LS011900)에는 길·둘레길이 섞여 온다(산막이옛길) — 이름이 길이면 트레킹.
#: 끝의 괄호·"N코스/N구간"·"입구"는 떼고 본다. 자전거길은 레저스포츠로 둔다.
_TRAIL_NAME_RE: Final = re.compile(r"(?:길|올레|트레킹|탐방로|산책로|코스)$")
_TRAIL_SUFFIX_RE: Final = re.compile(
    r"(?:\([^)]*\)|제?[\d①-⑳][\d①-⑳~-]*(?:코스|구간)|입구|[\d①-⑳]+)$"
)
_NOT_TRAIL_RE: Final = re.compile(r"자전거길$")


def _is_trail_name(title: str | None) -> bool:
    name = "".join((title or "").split())
    for _ in range(3):  # "OO둘레길(1구간) 입구" 꼴의 겹친 꼬리
        stripped = _TRAIL_SUFFIX_RE.sub("", name)
        if stripped == name or not stripped:
            break
        name = stripped
    return bool(_TRAIL_NAME_RE.search(name)) and not _NOT_TRAIL_RE.search(name)


def attraction_category(
    lcls_systm1: str | None,
    lcls_systm2: str | None,
    lcls_systm3: str | None,
    title: str | None = None,
) -> str:
    """TourAPI 신 분류 → Map category code(8자리). 모르는 코드는 상위 단계로 내려간다.

    ``title``은 기타육상레저스포츠(LS011900)를 트레킹·둘레길과 그 밖으로 가르는 데만 쓴다.
    """
    lcls3 = (lcls_systm3 or "").strip()
    if lcls3 == "LS011900" and _is_trail_name(title):
        return _P.TOURISM_ACTIVITY_TREKKING.value
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
        if not content_id or _skipped(item.lcls_systm2, item.lcls_systm3):
            continue  # 적재하지 않는 행의 상세는 저장되지 않아 매 run 다시 고르게 된다
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


# -- 소개·이미지·반려동물·무장애 상세(ADR-126) --------------------------------

TourApiDetailOp = Literal["intro", "images", "pet", "accessibility"]
"""상세 오퍼레이션 — ``detailIntro2``·``detailImage2``·``detailPetTour2``·
``KorWithService2/detailWithTour2``. data.go.kr 한도는 **오퍼레이션마다** 따로 걸린다."""

TOURAPI_DETAIL_OPS: Final[tuple[TourApiDetailOp, ...]] = ("intro", "images", "pet", "accessibility")

TOURAPI_DETAIL_RAW_KEY: Final[str] = "tourapi_detail_ops"
"""``raw_data`` 안 상세 묶음 키 — ``{op: {"modified_time": iso|None, "data": ...}}``.

``data``가 빈 dict/list면 "받았으나 원천에 없음"이다(다시 묻지 않는다). op 키가 없으면 아직 받지
않았다. ``modified_time``은 그 op을 받을 때 목록의 수정 시각이다 — 목록 값과 다르면 낡았다."""

#: 소개정보(``detailIntro2``)에서 남기는 원천 키 — 관광타입마다 접미사가 다르다.
_INTRO_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "usage_hours": ("usetime", "usetimeculture", "usetimeleports"),
    "rest_days": ("restdate", "restdateculture", "restdateleports"),
    "parking": ("parking", "parkingculture", "parkingleports"),
    "parking_fee": ("parkingfee", "parkingfeeleports"),
    "fee_text": ("usefee", "usefeeleports"),
    "discount": ("discountinfo",),
    "reservation": ("reservation",),
    "inquiry": ("infocenter", "infocenterculture", "infocenterleports"),
    "pet_note": ("chkpet", "chkpetculture", "chkpetleports"),
}
TOURAPI_INTRO_RAW_KEYS: Final[frozenset[str]] = frozenset(
    key for keys in _INTRO_FIELDS.values() for key in keys
)

#: 무장애(``detailWithTour2``) 원천 키 → (분류, 한글 이름). 순서가 화면 순서다.
TOURAPI_ACCESSIBILITY_FIELDS: Final[dict[str, tuple[AccessibilityGroup, str]]] = {
    "parking": ("physical", "주차"),
    "route": ("physical", "접근로"),
    "publictransport": ("physical", "대중교통"),
    "ticketoffice": ("physical", "매표소"),
    "promotion": ("physical", "홍보물"),
    "wheelchair": ("physical", "휠체어"),
    "exit": ("physical", "출입통로"),
    "elevator": ("physical", "엘리베이터"),
    "restroom": ("physical", "화장실"),
    "auditorium": ("physical", "관람석"),
    "room": ("physical", "객실"),
    "handicapetc": ("physical", "지체장애 기타"),
    "braileblock": ("visual", "점자블록"),
    "helpdog": ("visual", "보조견 동반"),
    "guidehuman": ("visual", "안내요원"),
    "audioguide": ("visual", "오디오가이드"),
    "bigprint": ("visual", "큰활자 홍보물"),
    "brailepromotion": ("visual", "점자 홍보물"),
    "guidesystem": ("visual", "유도·안내 설비"),
    "blindhandicapetc": ("visual", "시각장애 기타"),
    "signguide": ("hearing", "수어 안내"),
    "videoguide": ("hearing", "자막 비디오가이드"),
    "hearingroom": ("hearing", "객실(청각)"),
    "hearinghandicapetc": ("hearing", "청각장애 기타"),
    "stroller": ("infant_family", "유모차"),
    "lactationroom": ("infant_family", "수유실"),
    "babysparechair": ("infant_family", "유아용 보조의자"),
    "infantsfamilyetc": ("infant_family", "영유아 가족 기타"),
}

#: 반려동물(``detailPetTour2``) 원천 키 → :class:`PetPolicy` 필드.
TOURAPI_PET_FIELDS: Final[dict[str, str]] = {
    "acmpyTypeCd": "companion_type",
    "acmpyPsblCpam": "allowed_pets",
    "acmpyNeedMtr": "requirements",
    "etcAcmpyInfo": "notes",
}

TOURAPI_MAX_IMAGES: Final[int] = 20
"""한 관광지에 남기는 추가 이미지 상한(원천 순서 앞에서부터)."""

_KOGL_TYPE_BY_CODE: Final[dict[str, int]] = {"Type1": 1, "Type2": 2, "Type3": 3, "Type4": 4}

_CONTENT_TYPE_RANK: Final[dict[str, int]] = {"12": 0, "14": 1, "28": 2}
"""같은 우선 등급 안에서 관광지(12) → 문화시설(14) → 레포츠(28) 순으로 상세를 받는다."""


@dataclass(frozen=True, slots=True)
class TourApiDetailRequest:
    """상세 한 건 요청 — 소개정보는 관광타입이 있어야 묻는다."""

    content_id: str
    content_type_id: str


@dataclass(frozen=True, slots=True)
class TourApiDetailOpsPlan:
    """한 적재의 상세 오퍼레이션 계획.

    ``stored``: contentid → 이어 쓸 op 묶음(낡은 것도 포함 — 낡은 것은 ``fetch``에도 오른다).
    ``fetch``: op → 이번에 받을 요청(예산 안, 우선순위 순).
    ``deferred``: op → 예산 밖이라 다음 run으로 미룬 수.
    """

    stored: Mapping[str, Mapping[str, Any]]
    fetch: Mapping[TourApiDetailOp, tuple[TourApiDetailRequest, ...]]
    deferred: Mapping[TourApiDetailOp, int]


def _stored_ops(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    ops = raw.get(TOURAPI_DETAIL_RAW_KEY) if raw is not None else None
    if not isinstance(ops, Mapping):
        return {}
    return {
        op: entry
        for op, entry in ops.items()
        if op in TOURAPI_DETAIL_OPS and isinstance(entry, Mapping) and "data" in entry
    }


def plan_tourapi_detail_ops(
    items: Iterable[VisitKoreaAttractionItem],
    stored: Mapping[str, Mapping[str, Any]],
    *,
    budgets: Mapping[TourApiDetailOp, int],
    priority: Mapping[str, int] | None = None,
    members: Mapping[TourApiDetailOp, frozenset[str]] | None = None,
) -> TourApiDetailOpsPlan:
    """op마다 이번 run에 받을 contentid를 예산 안에서 고른다(일일 한도 보호, 점진 백필).

    - 저장 op의 ``modified_time``이 목록과 같으면 다시 받지 않는다.
    - 나머지는 받을 대상이다. 정렬: ``priority`` 점수(contentid → 점수 — 큐레이션 포함과 검색
      인지도, ``read_detail_priority_scores``)가 높은 것이 먼저, 같은 점수 안에서 낡은 것(저장값
      있음)이 없는 것보다 먼저, 관광지(12) → 문화시설(14) → 레포츠(28), 마지막으로 contentid
      순(결정적).
    - ``members``에 op이 있으면 그 집합(서비스 목록 — 무장애·반려동물)에 든 contentid만 묻는다.
      나머지는 묻지 않고 다음 run이 다시 본다(목록에 새로 들면 그때 받는다).
    - 낡은 op 값은 다시 받을 때까지 **그대로 보인다**(그 op의 ``modified_time``이 옛 값이라 다음
      run이 계속 다시 고른다). 목록 수정 시각은 아무 필드의 편집에도 바뀌므로, 받기 전에 지우면
      맞는 안내까지 사라진다.
    """
    keep: dict[str, dict[str, Any]] = {}
    scores = priority or {}
    member_sets = members or {}
    candidates: dict[TourApiDetailOp, list[tuple[tuple[int, int, int, str], TourApiDetailRequest]]]
    candidates = {op: [] for op in TOURAPI_DETAIL_OPS}
    seen: set[str] = set()
    for item in items:
        content_id = (item.content_id or "").strip()
        if not content_id or content_id in seen or _skipped(item.lcls_systm2, item.lcls_systm3):
            continue
        seen.add(content_id)
        content_type_id = (item.content_type_id or "").strip()
        ops = _stored_ops(stored.get(content_id))
        if ops:
            keep[content_id] = ops
        current = _iso(item.modified_time)
        request = TourApiDetailRequest(content_id=content_id, content_type_id=content_type_id)
        for op in TOURAPI_DETAIL_OPS:
            entry = ops.get(op)
            if entry is not None and entry.get("modified_time") == current:
                continue
            if op == "intro" and not content_type_id:
                continue  # detailIntro2는 관광타입이 필수다
            if op in member_sets and content_id not in member_sets[op]:
                continue  # 그 서비스에 실리지 않은 관광지 — 물어도 빈 답이다
            key = (
                -scores.get(content_id, 0),
                0 if entry is not None else 1,
                _CONTENT_TYPE_RANK.get(content_type_id, 9),
                content_id,
            )
            candidates[op].append((key, request))
    fetch: dict[TourApiDetailOp, tuple[TourApiDetailRequest, ...]] = {}
    deferred: dict[TourApiDetailOp, int] = {}
    for op in TOURAPI_DETAIL_OPS:
        ordered = [request for _key, request in sorted(candidates[op], key=lambda pair: pair[0])]
        limit = max(budgets.get(op, 0), 0)
        fetch[op] = tuple(ordered[:limit])
        deferred[op] = max(len(ordered) - limit, 0)
    return TourApiDetailOpsPlan(stored=keep, fetch=fetch, deferred=deferred)


def merge_tourapi_detail_ops(
    plan: TourApiDetailOpsPlan,
    fetched: Mapping[TourApiDetailOp, Mapping[str, Any]],
    modified_times: Mapping[str, str | None],
) -> dict[str, dict[str, Any]]:
    """저장 op 묶음 위에 이번에 받은 op 값을 얹는다 → contentid별 ``raw_data`` 상세 묶음."""
    merged: dict[str, dict[str, Any]] = {cid: dict(ops) for cid, ops in plan.stored.items()}
    for op, by_content in fetched.items():
        for content_id, data in by_content.items():
            merged.setdefault(content_id, {})[op] = {
                "modified_time": modified_times.get(content_id),
                "data": data,
            }
    return merged


def _first_text(data: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        text = clean_text(data.get(key))
        if text is not None:
            return text
    return None


def _tourapi_images(
    data: object, *, primary: str | None, primary_thumbnail: str | None, license_code: str | None
) -> list[PlaceImage]:
    """대표 이미지(목록 ``firstimage``, 목록 공공누리 유형) → 추가 이미지(``detailImage2``) 순.

    유형을 모르는 이미지는 담지 않는다(fail-closed). 같은 URL은 한 번만.
    """
    images: list[PlaceImage] = []
    seen: set[str] = set()
    primary_url = http_url(primary)
    primary_kogl = _KOGL_TYPE_BY_CODE.get((license_code or "").strip())
    if primary_url is not None and primary_kogl is not None:
        seen.add(primary_url)
        images.append(
            PlaceImage(
                url=primary_url,
                thumbnail_url=http_url(primary_thumbnail),
                license=kogl_license(primary_kogl, attribution=_ATTRIBUTION),
            )
        )
    if not isinstance(data, list):
        return images
    for row in data:
        if not isinstance(row, Mapping) or len(images) >= TOURAPI_MAX_IMAGES:
            continue
        url = http_url(row.get("originimgurl"))
        kogl = _KOGL_TYPE_BY_CODE.get(str(row.get("cpyrhtDivCd") or "").strip())
        if url is None or kogl is None or url in seen:
            continue  # 이용 조건을 모르는 이미지는 담지 않는다(fail-closed)
        seen.add(url)
        images.append(
            PlaceImage(
                url=url,
                thumbnail_url=http_url(row.get("smallimageurl")),
                caption=clean_text(row.get("imgname")),
                license=kogl_license(kogl, attribution=_ATTRIBUTION),
            )
        )
    return images


def _tourapi_accessibility(data: object) -> list[AccessibilityNote]:
    if not isinstance(data, Mapping):
        return []
    notes: list[AccessibilityNote] = []
    for key, (group, label) in TOURAPI_ACCESSIBILITY_FIELDS.items():
        text = clean_text(data.get(key))
        if text is not None:
            notes.append(AccessibilityNote(group=group, facility=key, label=label, text=text))
    return notes


def _tourapi_pet(data: object) -> PetPolicy | None:
    if not isinstance(data, Mapping):
        return None
    values = {field: clean_text(data.get(key)) for key, field in TOURAPI_PET_FIELDS.items()}
    if not any(values.values()):
        return None
    return PetPolicy.model_validate(values)


def _op_data(ops: Mapping[str, Any], op: str) -> object:
    entry = ops.get(op)
    return entry.get("data") if isinstance(entry, Mapping) else None


def tourapi_visitor_info(
    ops: Mapping[str, Any] | None,
    *,
    overview: str | None = None,
    primary_image: str | None = None,
    primary_thumbnail: str | None = None,
    license_code: str | None = None,
) -> PlaceVisitorInfo | None:
    """목록·``detailCommon2``·상세 op 묶음 → 방문 안내(없으면 ``None``). 태그·공백만 정리한다.

    소개문(``overview``)과 대표 이미지(``firstimage``)도 여기 싣는다 — 소비자가 원천마다 다른 자리
    (``facility_info.overview``·``image_url``)를 찾지 않게(ADR-126, 정본 하나). 평면 키는 기존
    소비자를 위해 당분간 함께 남는다.
    """
    ops = ops or {}
    raw_intro = _op_data(ops, "intro")
    intro: Mapping[str, Any] = raw_intro if isinstance(raw_intro, Mapping) else {}
    info = PlaceVisitorInfo(
        source="tourapi",
        attribution=_ATTRIBUTION,
        description=clean_text(overview, limit=DESCRIPTION_MAX),
        usage_hours=_first_text(intro, _INTRO_FIELDS["usage_hours"]),
        rest_days=_first_text(intro, _INTRO_FIELDS["rest_days"]),
        parking=_first_text(intro, _INTRO_FIELDS["parking"]),
        parking_fee=_first_text(intro, _INTRO_FIELDS["parking_fee"]),
        fee_text=_first_text(intro, _INTRO_FIELDS["fee_text"]),
        discount=_first_text(intro, _INTRO_FIELDS["discount"]),
        reservation=_first_text(intro, _INTRO_FIELDS["reservation"]),
        inquiry=_first_text(intro, _INTRO_FIELDS["inquiry"]),
        pet_note=_first_text(intro, _INTRO_FIELDS["pet_note"]),
        images=_tourapi_images(
            _op_data(ops, "images"),
            primary=primary_image,
            primary_thumbnail=primary_thumbnail,
            license_code=license_code,
        ),
        accessibility=_tourapi_accessibility(_op_data(ops, "accessibility")),
        pet_policy=_tourapi_pet(_op_data(ops, "pet")),
    )
    return None if info.is_empty() else info


# -- 변환 -----------------------------------------------------------------

_HREF_RE: Final = re.compile(r"""href\s*=\s*["']?(https?://[^"'\s>]+)""", re.IGNORECASE)
_URL_RE: Final = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_TAG_RE: Final = re.compile(r"<[^>]+>")
_BR_RE: Final = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ROAD_RE: Final = re.compile(r"\S+(?:로|길)\s+\d")
"""도로명 꼴 ``…로 12``/``…길 3-1``. 공백을 요구해 지번 ``종로1가 1``을 거른다."""


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
    license_code: str | None,
    dataset_key: str = DATASET_KEY_VISITKOREA_ATTRACTIONS,
) -> list[FeatureFileSource]:
    """대표·썸네일 이미지 URL → ``FeatureFileSource``(원본 참조, 가공 없음 — 공공누리 유형 준수).

    TourAPI 축제(:mod:`kortravelmap.providers.visitkorea`)도 같은 규칙으로 쓴다(``dataset_key``).
    """
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
                dataset_key=dataset_key,
                source_record_key=source_record_key,
                # 파일이 객체 저장소로 옮겨져도 이용 조건이 함께 간다(Type3은 변경 금지).
                payload={
                    "attribution": _ATTRIBUTION,
                    "kogl_type": license_code,
                    "license": _KOGL_LICENSE.get(license_code or "", license_code),
                },
            )
        )
    return sources


async def _attraction_to_bundle(
    item: VisitKoreaAttractionItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
    detail_ops: Mapping[str, Any] | None = None,
) -> FeatureBundle | None:
    content_id = (item.content_id or "").strip()
    name = normalize_korean_text(item.title)
    if not content_id or name is None:
        return None
    if _skipped(item.lcls_systm2, item.lcls_systm3):
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
    if detail_ops:
        # 상세 묶음이 없는 행은 키를 두지 않는다 — 그 행의 payload hash가 이 기능 전과 같다.
        raw_data[TOURAPI_DETAIL_RAW_KEY] = {op: detail_ops[op] for op in sorted(detail_ops)}
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
        or (sigungu_code[:2] if sigungu_code else None)
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

    category = attraction_category(
        item.lcls_systm1, item.lcls_systm2, item.lcls_systm3, item.title
    )
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
        VISITOR_INFO_KEY: tourapi_visitor_info(
            detail_ops,
            overview=item.overview,
            primary_image=item.first_image,
            primary_thumbnail=item.first_image2,
            license_code=license_code,
        ),
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
            place_kind=_PLACE_KIND_BY_CONTENT_TYPE.get(
                (item.content_type_id or "").strip(), ATTRACTION_PLACE_KIND
            ),
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
            license_code=license_code,
        ),
    )


async def tourapi_attractions_to_bundles(
    items: Iterable[VisitKoreaAttractionItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
    details: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[FeatureBundle]:
    """TourAPI 관광지 items → place ``FeatureBundle`` (자연키 contentid).

    ``details``는 contentid → 상세 op 묶음(:data:`TOURAPI_DETAIL_RAW_KEY` 모양)이다. 묶음은
    ``raw_data``에 그대로 남고(다음 run·replay가 이어 쓴다) 방문 안내로 바뀌어
    ``facility_info.visitor_info``에 들어간다(ADR-126).

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
        content_id = (item.content_id or "").strip()
        bundle = await _attraction_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
            detail_ops=(details or {}).get(content_id),
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
