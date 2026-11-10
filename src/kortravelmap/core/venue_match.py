"""행사 장소 이름 → 이미 좌표가 있는 장소 Feature 연결(#1468 D) — 순수 함수.

국가유산 행사 원천(``selectEventListOpenapi``)에는 좌표도 번지 주소도 없다. 있는 것은 시도·시군구
이름과 장소 이름(``subDesc`` — "진주성 일원", "밀양향교, 영남루")뿐이다. 그 장소 이름이 같은
시군구의 장소 Feature(국가유산·관광지·박물관 …) 이름과 **같으면** 그 좌표를 행사 좌표로 쓴다.

규칙은 일부러 좁다 — 틀린 핀은 핀이 없는 것보다 나쁘다.

- 장소 문자열은 ``,``·``/``·줄바꿈·" 및 "·" 또는 "로 나누고, 괄호 안과 끝의 "일원·일대·주변"(띄어 쓴
  "내·앞·등·외"도)을 뗀다. 글자(한글·영숫자)가 3자 미만이거나 일반 시설 낱말("기념관"·"행사장")뿐인
  조각은 버린다. **앞 조각부터** 본다 — 원천은 주 장소를 먼저 적는다.
- 이름은 글자만 남겨 **같아야** 한다. 앞 낱말이 그 행의 시도·시군구 이름이면 떼고도 비교한다
  ("고양 행주산성" = "행주산성"). 접두·포함 일치는 쓰지 않는다("정선향교" ≠ "정선향교 앞
  공영주차장").
- 시도·시군구 이름이 같아야 한다. 시도는 약칭 계열로 비교한다(``전라남도``·``광주광역시``·
  ``전남광주통합특별시``는 한 계열 — 2026 통합), 시군구는 첫 낱말에서 시·군·구·특례시를 뗀
  어근으로 비교한다("고양시" = "고양시 덕양구", "용인특례시" = "용인시 수지구").
- 같은 이름 후보들이 1 km보다 넓게 흩어져 있으면 고르지 않는다(동명 이소).
- 고를 때는 국가유산 본체(``prefer_dataset_key``)를 먼저, 그다음 ``feature_id`` 오름차순이다
  (결정적).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Final

from kortravelmap.dto import Coordinate

__all__ = [
    "VENUE_CLUSTER_MAX_KM",
    "VenueCandidate",
    "VenueMatch",
    "VenueResolver",
    "match_venue",
    "same_region",
    "sido_family",
    "sigungu_root",
    "split_venue_names",
    "venue_name_key",
]

VENUE_CLUSTER_MAX_KM: Final[float] = 1.0
"""같은 이름 후보가 이보다 넓게 흩어지면 동명 이소로 보고 고르지 않는다."""

_MIN_NAME_CHARS: Final[int] = 3

_SPLIT: Final[re.Pattern[str]] = re.compile(r"[,，/\n;]| 및 | 또는 ")
_PAREN: Final[re.Pattern[str]] = re.compile(r"[(（\[][^)）\]]*[)）\]]")
#: 끝의 범위 수식어. 한 글자짜리는 띄어 쓴 것만 뗀다("광한루 앞") — 이름 끝 글자("성내")는 둔다.
_TRAILING_QUALIFIER: Final[re.Pattern[str]] = re.compile(
    r"(?:\s*(?:일원|일대|주변)|\s+(?:내|앞|등|외))$"
)
#: 그 자체로는 장소 이름이 아닌 일반 시설 낱말. 이것만 남은 조각("기념관", "행사장")은 시군구에
#: 같은 이름이 하나뿐이어도 핀을 꽂지 않는다(적대 리뷰 — 조각 분해가 만드는 거짓 일치).
_GENERIC_VENUE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "기념관", "체육관", "행사장", "주차장", "박물관", "미술관", "전시관", "문화원", "공연장",
        "운동장", "교육관", "전수관", "전수교육관", "도서관", "복지관", "회관", "마을회관",
        "주민센터", "행정복지센터", "시청", "군청", "구청", "광장", "강당", "공원", "시장",
        "지역상권", "행사장전역", "전역", "추후공지예정", "추후공지",
    }
)
_NON_NAME: Final[re.Pattern[str]] = re.compile(r"[^0-9A-Za-z가-힣]")

#: 시도 이름 접두 → 비교 계열. 가장 긴 접두부터 본다. ``광주``는 2026 ``전남광주통합특별시``로
#: 전남과 한 계열이다(옛 ``광주광역시`` 표기와 새 표기가 섞여 온다 — prod 2026-11-10 실측).
_SIDO_FAMILY_PREFIXES: Final[tuple[tuple[str, str], ...]] = tuple(
    sorted(
        {
            "서울": "서울",
            "부산": "부산",
            "대구": "대구",
            "인천": "인천",
            "광주": "전남",
            "전남": "전남",
            "전라남": "전남",
            "대전": "대전",
            "울산": "울산",
            "세종": "세종",
            "경기": "경기",
            "강원": "강원",
            "충북": "충북",
            "충청북": "충북",
            "충남": "충남",
            "충청남": "충남",
            "전북": "전북",
            "전라북": "전북",
            "경북": "경북",
            "경상북": "경북",
            "경남": "경남",
            "경상남": "경남",
            "제주": "제주",
        }.items(),
        key=lambda item: -len(item[0]),
    )
)
_SIGUNGU_SUFFIX: Final[re.Pattern[str]] = re.compile(r"(?:특례시|시|군|구)$")


@dataclass(frozen=True, slots=True)
class VenueCandidate:
    """좌표가 있는 공개 장소 Feature 한 건(후보)."""

    feature_id: str
    name: str
    coord: Coordinate
    sido_name: str | None
    sigungu_name: str | None
    dataset_key: str | None = None


@dataclass(frozen=True, slots=True)
class VenueMatch:
    """장소 이름이 가리키는 Feature와 그 좌표."""

    feature_id: str
    coord: Coordinate
    matched_name: str


VenueResolver = Callable[[str, str | None, str | None], Awaitable[VenueMatch | None]]
"""``(장소 이름 조각, 시도 이름, 시군구 이름) → VenueMatch | None`` async 해석기."""


def _nfc(value: str | None) -> str:
    return unicodedata.normalize("NFC", value or "").strip()


def venue_name_key(value: str | None) -> str:
    """비교용 이름 — NFC 뒤 한글·영숫자만 남긴다."""
    return _NON_NAME.sub("", _nfc(value))


def split_venue_names(value: str | None) -> list[str]:
    """장소 문자열을 비교할 이름 조각으로 나눈다(원천 순서, 중복 제거)."""
    out: list[str] = []
    for part in _SPLIT.split(_nfc(value)):
        piece = _PAREN.sub("", part).strip()
        piece = _TRAILING_QUALIFIER.sub("", piece).strip()
        piece = " ".join(piece.split())
        key = venue_name_key(piece)
        if len(key) < _MIN_NAME_CHARS or key in _GENERIC_VENUE_KEYS or piece in out:
            continue
        out.append(piece)
    return out


def sido_family(value: str | None) -> str | None:
    """시도 이름 → 비교 계열(``전라남도``·``광주광역시``·``전남광주통합특별시`` → ``전남``)."""
    text_value = _nfc(value)
    if not text_value:
        return None
    for prefix, family in _SIDO_FAMILY_PREFIXES:
        if text_value.startswith(prefix):
            return family
    return text_value


def sigungu_root(value: str | None) -> str | None:
    """시군구 이름 → 첫 낱말의 어근("고양시 덕양구" → "고양", "용인특례시" → "용인").

    "중구"처럼 떼면 한 글자가 남는 이름은 그대로 둔다.
    """
    words = _nfc(value).split()
    if not words or words[0] == "-":
        return None
    root = _SIGUNGU_SUFFIX.sub("", words[0])
    return root if len(root) >= 2 else words[0]


def same_region(
    candidate: VenueCandidate, sido_name: str | None, sigungu_name: str | None
) -> bool:
    """후보가 행의 시도·시군구에 있는가(시군구가 없는 행 — 세종 ``-`` — 은 시도만 본다)."""
    want_sido = sido_family(sido_name)
    if want_sido is None or sido_family(candidate.sido_name) != want_sido:
        return False
    want_sigungu = sigungu_root(sigungu_name)
    if want_sigungu is None:
        return True
    return sigungu_root(candidate.sigungu_name) == want_sigungu


def _region_words(sido_name: str | None, sigungu_name: str | None) -> frozenset[str]:
    words = {sigungu_root(sigungu_name), sido_family(sido_name)}
    first = _nfc(sigungu_name).split()
    if first:
        words.add(first[0])
    first_sido = _nfc(sido_name).split()
    if first_sido:
        words.add(first_sido[0])
    return frozenset(word for word in words if word)


def _name_forms(name: str, region_words: frozenset[str]) -> set[str]:
    forms = {venue_name_key(name)}
    words = _nfc(name).split()
    if len(words) > 1 and words[0] in region_words:
        forms.add(venue_name_key(" ".join(words[1:])))
    forms.discard("")
    return forms


def _distance_km(a: Coordinate, b: Coordinate) -> float:
    lat = math.radians((float(a.lat) + float(b.lat)) / 2)
    dx = (float(a.lon) - float(b.lon)) * 111.32 * math.cos(lat)
    dy = (float(a.lat) - float(b.lat)) * 110.57
    return math.hypot(dx, dy)


def match_venue(
    venue: str,
    sido_name: str | None,
    sigungu_name: str | None,
    candidates: Iterable[VenueCandidate],
    *,
    prefer_dataset_key: str | None = None,
) -> VenueMatch | None:
    """장소 이름 조각 하나와 후보들 → 같은 지역·같은 이름의 Feature 하나(없거나 흩어지면 None)."""
    region_words = _region_words(sido_name, sigungu_name)
    wanted = _name_forms(venue, region_words)
    if not wanted:
        return None
    hits: list[VenueCandidate] = [
        candidate
        for candidate in candidates
        if same_region(candidate, sido_name, sigungu_name)
        and _name_forms(candidate.name, region_words) & wanted
    ]
    if not hits:
        return None
    for i, left in enumerate(hits):
        for right in hits[i + 1 :]:
            if _distance_km(left.coord, right.coord) > VENUE_CLUSTER_MAX_KM:
                return None
    chosen = min(
        hits,
        key=lambda c: (
            prefer_dataset_key is None or c.dataset_key != prefer_dataset_key,
            c.feature_id,
        ),
    )
    return VenueMatch(feature_id=chosen.feature_id, coord=chosen.coord, matched_name=chosen.name)
