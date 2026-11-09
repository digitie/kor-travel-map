"""검색어의 지역 토큰 해석 — "강릉 호텔"의 "강릉"을 시군구 코드 집합으로 바꾼다(#1459 §7).

왜 필요한가. ``/v1/features/search``는 검색어 전체로 trigram 유사도를 본다. 그래서 "강릉 호텔"은
"호텔"이 이름에 든 전국 행을 돌려주고(1위가 대구 '밀독 호텔'), "춘천 닭갈비"는 이름이
"춘천닭갈비"인 서울 식당을 춘천의 닭갈비집보다 앞에 둔다(2026-11-08 PinVi 여행 시나리오 검증).
검색어 앞(또는 뒤)의 지역 이름을 떼어 내 그 지역 Feature를 순위 맨 앞 자리로 올리는 것이 이
모듈의 일이다. SQL은 ``infra/feature_repo.py``가 갖는다 — 이 모듈은 순수 함수다.

지역 이름 → 코드는 **데이터에서** 만든다. 시군구 코드는 바뀐다(강원 42→51, 전북 45→52,
2026 ``전남광주통합특별시`` 12xxx가 옛 29·46과 함께 있다 — prod 2026-11-09 실측). 이름은
그보다 안정적이다. 그래서 호출자가 공개 Feature의 ``(sigungu_code, sido_name, sigungu_name)``
표본을 넘기고(``SearchRegionEntry``), 이 모듈은 이름 → 코드 색인을 만든다. 캐시는 두지 않는다
(ADR-030) — 표본 조회는 시군구 수(약 290)만큼의 색인 탐색이라 싸다.

토큰 규칙.

- 시도: 표본의 ``sido_name`` 그대로, 접미사(특별자치도·특별자치시·통합특별시·특별시·광역시·도)를
  뗀 이름, 그리고 ``SIDO_SHORT_NAMES``의 관용 약칭(충북·전남·경북 …).
- 시군구: ``sigungu_name``의 각 낱말("수원시 영통구" → "수원시", "영통구")과, 시·군·구로 끝나고
  뗀 뒤 두 글자 이상이면 접미사를 뗀 형태("강릉시" → "강릉", "중구"는 그대로).
- 잘 알려진 하위 지역(``SUBAREA_ALIASES``): 애월·우도·해운대 밖의 광안리 같은 이름을 시도 약칭 +
  시군구 이름으로 고정한다. 읍면동 경계까지 좁히지 않는다 — 시군구가 순위의 단위다.

검색어 해석(``split_region_query``). 공백으로 나눈 낱말 중 **앞쪽 연속 구간**(없으면 뒤쪽)에서
지역 토큰을 고른다. 첫 지역 토큰 뒤에 오는 지역 토큰은 교집합이 비지 않을 때만 함께 묶는다
("부산 해운대", "강원 고성", "제주 서귀포"). 그래서 "수원 화성"의 "화성"(화성시)은 지역이 아니라
나머지 검색어로 남는다. 나머지가 비면 지역 해석을 하지 않는다("강릉" 한 낱말은 이름 검색 그대로).
낱말 하나짜리 검색어("춘천닭갈비", "팔공산")는 지역 해석 대상이 아니다.

나머지 검색어가 분류 이름이면(``search_keyword_category_codes``) 그 분류 아래 코드도 넘긴다 —
"강릉 호텔"은 이름에 "호텔"이 없는 강릉의 호텔 분류 행도 찾는다. 분류 이름은 분류 체계에서
유도한다(``PLACE_CATEGORY_DEFINITIONS``).
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from kortravelmap.category import PLACE_CATEGORY_DEFINITIONS, PlaceCategory

__all__ = [
    "SIDO_SHORT_NAMES",
    "SUBAREA_ALIASES",
    "SEARCH_CATEGORY_KEYWORD_SYNONYMS",
    "RegionSearch",
    "SearchRegionEntry",
    "build_region_token_index",
    "search_keyword_category_codes",
    "search_query_tokens",
    "split_region_query",
]

#: 시도 이름 → 관용 약칭. 표본의 ``sido_name``이 키와 같을 때만 쓴다. 접미사를 뗀 이름
#: ("서울특별시" → "서울")은 규칙이 따로 만든다 — 여기에는 규칙으로 안 나오는 것만 둔다.
#: ``전남광주통합특별시``(2026)는 옛 광주광역시 구(동구·서구·남구·북구·광산구)와 전라남도
#: 시군을 함께 담는다 — "광주"·"전남" 둘 다 이 시도 전체를 가리킨다(구와 시군을 이름만으로
#: 가를 수 없어 넓게 잡는다. 순위 가중일 뿐 필터가 아니다).
SIDO_SHORT_NAMES: Final[Mapping[str, tuple[str, ...]]] = {
    "서울특별시": ("서울시",),
    "부산광역시": ("부산시",),
    "대구광역시": ("대구시",),
    "인천광역시": ("인천시",),
    "광주광역시": ("광주시",),
    "대전광역시": ("대전시",),
    "울산광역시": ("울산시",),
    "세종특별자치시": ("세종시",),
    "강원도": ("강원",),
    "충청북도": ("충북",),
    "충청남도": ("충남",),
    "전라북도": ("전북",),
    "전라남도": ("전남",),
    "경상북도": ("경북",),
    "경상남도": ("경남",),
    "제주특별자치도": ("제주도",),
    "전남광주통합특별시": ("전남", "광주"),
}

#: 시도 접미사 — 긴 것 먼저 뗀다("특별자치도"가 "도"보다 먼저).
_SIDO_SUFFIXES: Final[tuple[str, ...]] = (
    "특별자치도",
    "특별자치시",
    "통합특별시",
    "특별시",
    "광역시",
    "도",
)

#: 시군구 낱말 접미사.
_SIGUNGU_SUFFIXES: Final[tuple[str, ...]] = ("시", "군", "구")

#: 잘 알려진 하위 지역 → (시도 토큰, 시군구 토큰). 둘의 교집합 코드가 그 지역이다. 시도
#: 토큰을 함께 두는 이유: 시군구 이름은 시도마다 겹친다("중구"·"고성").
#: 2026-11-08 여행 시나리오 질의(애월 카페·우도 천진항·광안리 …)에서 나온 이름이 출발점이다.
#: 시군구 이름과 겹치는 하위 지역(서귀포 "남원읍" vs 남원시)은 넣지 않는다.
SUBAREA_ALIASES: Final[Mapping[str, tuple[str, str]]] = {
    "애월": ("제주", "제주시"),
    "한림": ("제주", "제주시"),
    "협재": ("제주", "제주시"),
    "구좌": ("제주", "제주시"),
    "월정리": ("제주", "제주시"),
    "함덕": ("제주", "제주시"),
    "조천": ("제주", "제주시"),
    "우도": ("제주", "제주시"),
    "성산": ("제주", "서귀포시"),
    "중문": ("제주", "서귀포시"),
    "표선": ("제주", "서귀포시"),
    "광안리": ("부산", "수영구"),
    "서면": ("부산", "부산진구"),
    "남포동": ("부산", "중구"),
    "송도": ("인천", "연수구"),
    "영종도": ("인천", "중구"),
    "을왕리": ("인천", "중구"),
    "강화도": ("인천", "강화군"),
    "정동진": ("강원", "강릉시"),
    "경포": ("강원", "강릉시"),
    "대관령": ("강원", "평창군"),
    "안면도": ("충남", "태안군"),
    "변산": ("전북", "부안군"),
    "울릉도": ("경북", "울릉군"),
    "거제도": ("경남", "거제시"),
    "홍대": ("서울", "마포구"),
    "이태원": ("서울", "용산구"),
    "인사동": ("서울", "종로구"),
    "북촌": ("서울", "종로구"),
    "명동": ("서울", "중구"),
    "잠실": ("서울", "송파구"),
}

#: 분류 이름이 아닌 흔한 검색 낱말 → 분류 이름. 분류 체계에 없는 말만 둔다.
SEARCH_CATEGORY_KEYWORD_SYNONYMS: Final[Mapping[str, str]] = {
    "해변": "해수욕장",
    "비치": "해수욕장",
    "맛집": "음식점",
    "식당": "음식점",
    "숙소": "숙박",
    "게하": "게스트하우스",
}


@dataclass(frozen=True, slots=True)
class SearchRegionEntry:
    """공개 Feature 한 행의 지역 표본 — 시군구 코드와 그 행 주소의 시도·시군구 이름."""

    sigungu_code: str
    sido_name: str | None
    sigungu_name: str | None


@dataclass(frozen=True, slots=True)
class RegionSearch:
    """지역 해석 결과.

    ``sigungu_codes``는 정렬된 코드, ``remainder``는 지역 토큰을 뗀 나머지 검색어(낱말 사이 공백
    하나), ``category_codes``는 나머지가 분류 이름일 때 그 분류와 하위 분류 코드다(없으면 빈 tuple).
    """

    region_label: str
    sigungu_codes: tuple[str, ...]
    remainder: str
    category_codes: tuple[str, ...]


def _key(value: str) -> str:
    """토큰 비교 키 — NFC, 소문자, 다시 NFC(``search_alias_key``와 같은 순서, 공백은 이미 없음)."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", value).lower())


def search_query_tokens(q: str) -> tuple[str, ...]:
    """검색어를 공백(``str.isspace``)으로 나눈 낱말. 검색 비교 키의 공백 집합과 같다."""
    return tuple(q.split())


def _strip_suffix(value: str, suffixes: Sequence[str]) -> str | None:
    for suffix in suffixes:
        if value.endswith(suffix) and len(value) - len(suffix) >= 2:
            return value[: -len(suffix)]
    return None


def _mode(values: Iterable[str | None]) -> str | None:
    counter = Counter(value.strip() for value in values if value and value.strip())
    if not counter:
        return None
    # 최빈값, 동률이면 사전순 — 표본 순서와 무관하게 같은 색인을 만든다.
    return min(counter.items(), key=lambda item: (-item[1], item[0]))[0]


def build_region_token_index(
    entries: Iterable[SearchRegionEntry],
) -> dict[str, frozenset[str]]:
    """표본 → ``{토큰 키: 시군구 코드 집합}``.

    같은 코드의 표본이 여럿이면 시도·시군구 이름은 각각 최빈값을 쓴다(한 행의 주소 오류가
    색인을 흔들지 않게). 코드는 다섯 자리 숫자만 받는다.
    """
    by_code: dict[str, list[SearchRegionEntry]] = {}
    for entry in entries:
        code = entry.sigungu_code
        if not (isinstance(code, str) and len(code) == 5 and code.isdigit()):
            continue
        by_code.setdefault(code, []).append(entry)

    index: dict[str, set[str]] = {}

    def _add(token: str, code: str) -> None:
        if token:
            index.setdefault(_key(token), set()).add(code)

    for code, samples in by_code.items():
        sido_name = _mode(sample.sido_name for sample in samples)
        sigungu_name = _mode(sample.sigungu_name for sample in samples)
        if sido_name:
            for word in sido_name.split():
                _add(word, code)
                stripped = _strip_suffix(word, _SIDO_SUFFIXES)
                if stripped:
                    _add(stripped, code)
            for alias in SIDO_SHORT_NAMES.get(sido_name, ()):
                _add(alias, code)
        if sigungu_name:
            for word in sigungu_name.split():
                _add(word, code)
                stripped = _strip_suffix(word, _SIGUNGU_SUFFIXES)
                if stripped:
                    _add(stripped, code)

    for alias, (sido_token, sigungu_token) in SUBAREA_ALIASES.items():
        codes = index.get(_key(sido_token), set()) & index.get(_key(sigungu_token), set())
        if codes:
            index.setdefault(_key(alias), set()).update(codes)

    return {token: frozenset(codes) for token, codes in index.items()}


def _category_name_parts(category: PlaceCategory) -> tuple[str, ...]:
    """분류 노드 이름(가장 깊은 이름)과 그 "·" 조각 — 공백을 지운 비교 키."""
    names = [category.tier1_name, category.tier2_name, category.tier3_name, category.tier4_name]
    deepest = next((name for name in reversed(names) if name), None)
    if deepest is None:
        return ()
    whole = _key("".join(deepest.split()))
    parts = tuple(_key("".join(part.split())) for part in deepest.split("·"))
    return (whole, *[part for part in parts if part and part != whole])


def _category_prefix(category: PlaceCategory) -> str:
    return category.code[: 2 * category.depth] if category.depth > 0 else category.code


def search_keyword_category_codes(keyword: str) -> tuple[str, ...]:
    """나머지 검색어가 분류 이름이면 그 분류와 하위 분류 코드(정렬). 아니면 빈 tuple.

    비교 키는 공백을 지운 소문자 NFC다. 노드 이름(또는 "·" 조각)과 같거나, 두 글자 이상이고 조각의
    앞부분이면 일치한다("캠핑" → 캠핑장, "한옥" → 한옥호텔·한옥체험업·한옥·민속마을). 미분류
    (depth 0)는 대상이 아니다. 흔한 다른 말은 ``SEARCH_CATEGORY_KEYWORD_SYNONYMS``로 바꾼다.
    """
    key = _key("".join(keyword.split()))
    key = _key(SEARCH_CATEGORY_KEYWORD_SYNONYMS.get(key, key))
    if len(key) < 2:
        return ()
    prefixes: set[str] = set()
    for category in PLACE_CATEGORY_DEFINITIONS:
        if category.depth == 0:
            continue
        for part in _category_name_parts(category):
            if part == key or part.startswith(key):
                prefixes.add(_category_prefix(category))
                break
    if not prefixes:
        return ()
    return tuple(
        sorted(
            category.code
            for category in PLACE_CATEGORY_DEFINITIONS
            if category.depth > 0 and any(category.code.startswith(p) for p in prefixes)
        )
    )


def _leading_region(
    tokens: Sequence[str],
    index: Mapping[str, frozenset[str]],
) -> tuple[int, frozenset[str]] | None:
    """앞에서부터 지역 토큰을 묶는다 → (묶은 낱말 수, 코드). 첫 낱말이 지역이 아니면 None."""
    first = index.get(_key(tokens[0]))
    if not first:
        return None
    codes = first
    used = 1
    for token in tokens[1:]:
        more = index.get(_key(token))
        if not more or not (codes & more):
            break
        codes = codes & more
        used += 1
    return used, codes


def split_region_query(
    q: str,
    index: Mapping[str, frozenset[str]],
) -> RegionSearch | None:
    """검색어 → 지역 해석. 지역 토큰이 없거나 나머지가 비면 None(종전 검색 그대로).

    앞쪽 연속 구간을 먼저 본다. 앞이 지역이 아니면 뒤쪽 연속 구간을 본다("신라호텔 서울").
    """
    tokens = search_query_tokens(q)
    if len(tokens) < 2 or not index:
        return None
    region_tokens: Sequence[str]
    rest: Sequence[str]
    leading = _leading_region(tokens, index)
    if leading is not None:
        used, codes = leading
        region_tokens, rest = tokens[:used], tokens[used:]
    else:
        trailing = _leading_region(tuple(reversed(tokens)), index)
        if trailing is None:
            return None
        used, codes = trailing
        region_tokens, rest = tokens[len(tokens) - used :], tokens[: len(tokens) - used]
    if not rest or not codes:
        return None
    remainder = " ".join(rest)
    return RegionSearch(
        region_label=" ".join(region_tokens),
        sigungu_codes=tuple(sorted(codes)),
        remainder=remainder,
        category_codes=search_keyword_category_codes(remainder),
    )
