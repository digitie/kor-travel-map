"""``kortravelmap.core.business_name`` — 인허가 상호(법인 표기)에서 사람이 부르는 이름을 뗀다.

인허가 원천(MOIS LOCALDATA)의 ``사업장명``은 법인 등기 표기를 그대로 담는다 —
``(주)호텔롯데 롯데시티호텔대전``, ``주식회사라한호텔전주``,
``(주)이랜드파크켄싱턴호텔설악(스타)``. 지도 검색은 ``features.name`` trigram 유사도로 후보를
고르므로(``infra/feature_repo.py``) 법인 접두가 붙은 긴 이름은 "롯데시티호텔 대전" 같은 검색어와의
유사도가 문턱(0.2) 밑으로 떨어진다. 이 모듈은 표시 이름을 만들고 법인 표기는 따로 돌려준다
(호출자가 detail에 보존한다).

규칙(순서대로, 전부 결정적):

1. ``normalize_korean_text``(NFKC — ``㈜``가 ``(주)``가 된다·공백 축약).
2. 앞·뒤의 법인 표기를 걷는다: ``(주)``·``(유)``·``(재)``·``(사)``·``(합)``와 ``주식회사``·
   ``유한회사``·``유한책임회사``·``재단법인``·``사단법인``·``합자회사``·``합명회사``. **가운데**는
   건드리지 않는다(상호의 일부일 수 있다).
3. 큐레이션한 모회사 접두(:data:`PARENT_COMPANY_PREFIXES`)를 걷는다 — 법인 표기가 있었거나
   접두 뒤가 공백일 때만, 그리고 남는 이름이 :data:`MIN_PARENT_REST_CHARS` 이상일 때만.
   일반 낱말 접두(예: ``동승``)는 법인 표기와 공백을 **둘 다** 요구한다.
4. (``expand_trailing_bracket=True``일 때만) 맨 끝의 짧은 한글 괄호(``(경주)``)를 공백 뒤 낱말로
   편다 — 검색 키가 공백만 지우므로 괄호가 남으면 "라한호텔 경주"가 이름을 품지 못한다. 호출자가
   업종을 골라 켠다(숙박만 — 모든 업종에 켜면 괄호 상호 6만 행이 한꺼번에 다시 변환된다).
   **라틴 괄호는 이름에 남긴다** — 검색은 ``features.name``만 trigram으로 보므로, 떼면 영문 검색
   ("Fairfield by Marriott")이 그 Feature를 아예 후보로 올리지 못한다(적대 리뷰 MED).
5. 어느 단계든 남는 이름이 너무 짧아지면 그 단계를 되돌린다(과잉 제거 가드).

no-space 별칭은 따로 만들지 않는다 — 검색 순위가 이름과 검색어를 **공백을 지운 형태**로
비교한다(``search_alias_key``/``_search_compact_sql``). 큐레이션 브랜드 사전
(:data:`CURATED_BRAND_SEARCH_ALIASES`)은 ``feature.feature_search_aliases`` 행의 정본이다 —
migration 442이 같은 값을 심고, unit test가 둘을 대조한다.

ADR-002(core 순수 함수) — DB·provider 의존 없음.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from kortravelmap.core.address import normalize_korean_text

__all__ = [
    "CURATED_BRAND_SEARCH_ALIASES",
    "MIN_DISPLAY_CHARS",
    "MIN_PARENT_REST_CHARS",
    "PARENT_COMPANY_PREFIXES",
    "BrandSearchAlias",
    "BusinessName",
    "business_name_key",
    "normalize_business_name",
]

MIN_DISPLAY_CHARS: Final[int] = 2
"""표시 이름이 가져야 할 최소 의미 글자 수(한글·라틴·숫자). 못 미치면 그 단계를 되돌린다."""

MIN_PARENT_REST_CHARS: Final[int] = 4
"""모회사 접두를 뗀 나머지의 최소 의미 글자 수 — "호텔롯데 부산"이 "부산"이 되지 않게 한다."""

_ABBREVIATED_MARKER: Final[str] = r"\(\s*(?:주|유|재|사|합)\s*\)"
_SPELLED_MARKER: Final[str] = (
    r"(?:주식회사|유한책임회사|유한회사|재단법인|사단법인|합자회사|합명회사)"
)
_LEADING_MARKER: Final[re.Pattern[str]] = re.compile(
    rf"^(?:{_ABBREVIATED_MARKER}|{_SPELLED_MARKER})\s*"
)
_TRAILING_MARKER: Final[re.Pattern[str]] = re.compile(
    rf"\s*(?:{_ABBREVIATED_MARKER}|{_SPELLED_MARKER})$"
)
_TRAILING_BRACKET: Final[re.Pattern[str]] = re.compile(r"\s*\(([^()]*)\)$")
_HANGUL_SUFFIX: Final[re.Pattern[str]] = re.compile(r"^[가-힣0-9]{1,12}$")
_MEANINGFUL: Final[re.Pattern[str]] = re.compile(r"[가-힣A-Za-z0-9]")


@dataclass(frozen=True)
class _ParentPrefix:
    name: str
    requires_marker_and_space: bool = False


PARENT_COMPANY_PREFIXES: Final[tuple[_ParentPrefix, ...]] = (
    # 접두 뒤에 운영 브랜드가 붙는 숙박 운영 법인(2026-11-09 MOIS 원천 실측).
    _ParentPrefix("조선호텔앤리조트"),  # (주)조선호텔앤리조트 조선팰리스강남
    _ParentPrefix("이랜드파크"),  # (주)이랜드파크켄싱턴호텔설악(스타)
    _ParentPrefix("호텔롯데"),  # (주)호텔롯데 롯데시티호텔대전
    # 일반 낱말이라 "(주) 동승 JW메리어트…"처럼 법인 표기와 공백이 둘 다 있을 때만 뗀다.
    _ParentPrefix("동승", requires_marker_and_space=True),
)
"""큐레이션한 모회사 접두. 긴 것이 먼저 맞도록 매칭 때 길이순으로 본다."""


@dataclass(frozen=True)
class BusinessName:
    """표시 이름과 법인 표기(정규화한 원문)."""

    display: str
    legal: str

    @property
    def changed(self) -> bool:
        """표시 이름이 정규화한 원문과 다른가."""
        return self.display != self.legal


def _meaningful_chars(value: str) -> int:
    return len(_MEANINGFUL.findall(value))


def _strip_markers(name: str) -> tuple[str, bool]:
    stripped = False
    while True:
        candidate = _LEADING_MARKER.sub("", name, count=1)
        candidate = _TRAILING_MARKER.sub("", candidate, count=1).strip()
        if candidate == name:
            return name, stripped
        if _meaningful_chars(candidate) < MIN_DISPLAY_CHARS:
            return name, stripped
        name, stripped = candidate, True


def _strip_parent(name: str, *, had_marker: bool) -> str:
    for prefix in sorted(PARENT_COMPANY_PREFIXES, key=lambda p: -len(p.name)):
        if not name.startswith(prefix.name):
            continue
        rest = name[len(prefix.name) :]
        spaced = rest[:1].isspace()
        if prefix.requires_marker_and_space:
            if not (had_marker and spaced):
                continue
        elif not (had_marker or spaced):
            continue
        rest = rest.strip()
        if _meaningful_chars(rest) < MIN_PARENT_REST_CHARS or rest.startswith("("):
            continue
        return rest
    return name


def _expand_trailing_bracket(name: str) -> str:
    match = _TRAILING_BRACKET.search(name)
    if match is None:
        return name
    inner = match.group(1).strip()
    head = name[: match.start()].strip()
    if _meaningful_chars(head) < MIN_DISPLAY_CHARS or not _HANGUL_SUFFIX.match(inner):
        return name
    return f"{head} {inner}"


def normalize_business_name(
    raw: str | None, *, expand_trailing_bracket: bool = False
) -> BusinessName | None:
    """인허가 상호 → :class:`BusinessName`. 빈 입력은 ``None``.

    >>> normalize_business_name("(주)호텔롯데 롯데시티호텔대전").display
    '롯데시티호텔대전'
    >>> normalize_business_name("주식회사라한호텔전주").display
    '라한호텔전주'
    >>> normalize_business_name("주식회사 라한호텔(경주)", expand_trailing_bracket=True).display
    '라한호텔 경주'
    >>> normalize_business_name("(주)").display
    '(주)'
    """
    legal = normalize_korean_text(raw)
    if legal is None:
        return None
    name, had_marker = _strip_markers(legal)
    name = _strip_parent(name, had_marker=had_marker)
    if expand_trailing_bracket:
        name = _expand_trailing_bracket(name)
    name = normalize_korean_text(name) or legal
    return BusinessName(display=name, legal=legal)


def business_name_key(raw: str | None) -> str | None:
    """중복 판정용 이름 키 — 표시 이름의 공백을 지우고 소문자로. 빈 입력은 ``None``."""
    normalized = normalize_business_name(raw)
    if normalized is None:
        return None
    return re.sub(r"\s+", "", normalized.display).lower() or None


@dataclass(frozen=True)
class BrandSearchAlias:
    """``feature.feature_search_aliases`` 한 행의 정본(큐레이션)."""

    query: str
    """사람이 치는 검색어(공백·대소문자 무관 — 행의 ``alias``는 ``search_alias_key``)."""
    canonical_name: str
    """그 검색어가 뜻하는 ``features.name`` — 숙박 업종 이름 규칙의 결과와 같아야 한다."""
    source_name: str
    """확인한 원천 상호(검증 입력) — 괄호 펴기를 켠 표시 이름이 ``canonical_name``이다."""
    note: str


CURATED_BRAND_SEARCH_ALIASES: Final[tuple[BrandSearchAlias, ...]] = (
    BrandSearchAlias(
        "신라호텔", "호텔신라", "호텔신라",
        "서울 중구 동호로 249 관광호텔(MOIS lodgings). 법인 상호가 곧 사업장명이다",
    ),
    BrandSearchAlias(
        "서울신라호텔", "호텔신라", "호텔신라", "통칭 — 서울 중구 동호로 249",
    ),
    BrandSearchAlias(
        "현대호텔목포", "라한호텔목포", "(주)라한호텔목포",
        "영암 삼호읍 대불로 91 — 통칭 현대호텔 목포(2026-11-09 소유자 감사 확인)",
    ),
    BrandSearchAlias(
        "호텔현대목포", "라한호텔목포", "(주)라한호텔목포", "옛 통칭 — 영암 삼호읍 대불로 91",
    ),
    BrandSearchAlias(
        "조선팰리스", "조선팰리스강남", "(주)조선호텔앤리조트 조선팰리스강남",
        "서울 강남 테헤란로 231 관광호텔 — 브랜드 조선 팰리스 서울 강남",
    ),
    BrandSearchAlias(
        "조선팰리스서울강남", "조선팰리스강남", "(주)조선호텔앤리조트 조선팰리스강남",
        "브랜드 정식 표기",
    ),
    BrandSearchAlias(
        "켄싱턴호텔설악", "켄싱턴호텔설악 스타", "(주)이랜드파크켄싱턴호텔설악(스타)",
        "속초 설악산로 998 관광호텔 — 원천 상호의 (스타)는 그대로 둔다",
    ),
    BrandSearchAlias(
        "jw메리어트서울", "JW메리어트호텔서울", "JW메리어트호텔서울",
        "서울 서초 신반포로 176 관광호텔",
    ),
)
"""검색 별칭 정본(migration 442이 심는다). 확인되지 않은 통칭은 넣지 않는다."""
