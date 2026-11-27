"""``kortravelmap.providers.rest_area_food`` — 휴게소 먹거리(KREX 0502)·표준 코드(KREX 0615) 연결
규칙 (ADR-127).

transport ``rest-area-food``
export(:class:`~kortravelmap.providers.kor_travel_transport.TransportRestAreaFood`)를
Map 휴게소(transport ``rest-areas``, data.go.kr 표준데이터)와 맞추고, 메뉴를 결정적으로 요약하고,
오피넷
고속도로 주유소를 같은 방향 휴게소와 짝짓는 **순수 함수**만 둔다. 네트워크·DB·Valkey를 부르지
않는다.

- 휴게소 연결: 두 원천 모두 한국도로공사 표기 ``<이름>(<행선지>)``를 쓴다. 공백·"휴게소"·"방향"을
  걷어 낸
  ``(이름, 행선지)``가 KREX 휴게소 하나와만 같으면 연결한다(신뢰도 1.0). 둘 이상이거나 한 KREX
  코드에 Map
  휴게소가 둘 이상 붙으면 연결하지 않고 검토로 돌린다. 2026-11-27 운영 215곳 전부 이 규칙으로
  맞았다.
- 메뉴 요약: 대표(``bestfoodyn``)·프리미엄·추천 메뉴, 가격 최저·중앙·최고, 계절(여름·겨울) 메뉴.
  LLM을 쓰지
  않는다(소유자 결정 2026-11-27: 데이터만).
- 주유소 짝: 400 m 안 휴게소 후보마다 이름(휴게소 이름 포함·행선지·상하행)과 거리로 신뢰도를
  매긴다. :data:`STATION_PAIR_AUTO_CONFIDENCE` 이상만 자동으로 보이고, 나머지는 관리자 검토 목록에
  남는다.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Final, Literal

from kortravelmap.providers.kor_travel_transport import (
    TransportRestArea,
    TransportRestAreaFood,
    TransportRestAreaFoodMenu,
)

__all__ = [
    "FEATURED_MENU_LIMIT",
    "REST_AREA_LINK_AUTO_CONFIDENCE",
    "SEASONAL_MENU_LIMIT",
    "STATION_PAIR_AUTO_CONFIDENCE",
    "STATION_PAIR_RADIUS_M",
    "MenuSummary",
    "RestAreaLink",
    "StationPair",
    "StationPairCandidate",
    "link_rest_areas",
    "name_key",
    "pair_station",
    "summarize_menus",
    "with_rest_area_links",
]

REST_AREA_LINK_AUTO_CONFIDENCE: Final[float] = 0.9
"""휴게소 ↔ KREX 코드 연결을 자동으로 쓰는 하한."""
STATION_PAIR_AUTO_CONFIDENCE: Final[float] = 0.8
"""주유소 ↔ 휴게소 짝을 PinVi에 자동으로 보이는 하한. 아래는 관리자 검토 목록에만 남는다."""
STATION_PAIR_RADIUS_M: Final[float] = 400.0
"""주유소 짝 후보 반경. 2026-11-27 운영 실측: 휴게소 400 m 안 주유소 242곳(휴게소 214곳)."""
FEATURED_MENU_LIMIT: Final[int] = 12
SEASONAL_MENU_LIMIT: Final[int] = 10

_NOISE = re.compile(r"[\s·・.\-_/]")
_SUFFIX = re.compile(r"(휴게소|주유소|충전소|주차장|쉼터)+$")
_PAREN = re.compile(r"^(?P<base>[^()]+)\((?P<dest>[^()]+)\)(?P<tail>.*)$")
_CORP = re.compile(r"\(주\)|㈜|\(유\)|\(합\)|\(재\)|주식회사")


def _clean(value: str) -> str:
    return _NOISE.sub("", value)


def _strip_dest(value: str) -> str:
    return value[:-2] if value.endswith("방향") and len(value) > 2 else value


def name_key(name: str) -> tuple[str, str | None]:
    """휴게소·주유소 이름 → ``(이름, 행선지)``.

    ``칠서(양평)``·``칠서휴게소(양평방향)``·``칠서(양평)휴게소``는 모두 ``("칠서", "양평")``,
    괄호가 없으면
    ``("덕평", None)``이다. 공백·가운뎃점과 끝의 "휴게소"·"방향"을 걷어 낸다.
    """
    text = _clean(name.strip())
    match = _PAREN.match(text)
    if match is None:
        return _SUFFIX.sub("", text), None
    base = _SUFFIX.sub("", match.group("base"))
    dest = _strip_dest(_SUFFIX.sub("", match.group("dest")))
    return base, (dest or None)


# -- 휴게소 ↔ KREX 표준 코드 ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class RestAreaLink:
    """Map 휴게소 하나의 KREX 연결 결과. ``food``가 None이면 연결하지 못한 것이다."""

    natural_key: str
    name: str
    confidence: float
    method: Literal["name_exact", "name_merged", "ambiguous", "shared_code", "no_match"]
    food: TransportRestAreaFood | None
    candidates: tuple[str, ...] = ()
    """연결하지 못했을 때 검토용 후보 KREX 코드."""

    @property
    def linked(self) -> bool:
        return self.food is not None and self.confidence >= REST_AREA_LINK_AUTO_CONFIDENCE


def link_rest_areas(
    areas: Iterable[tuple[str, str]],
    foods: Iterable[TransportRestAreaFood],
) -> dict[str, RestAreaLink]:
    """``(natural_key, 원천 이름)`` 목록을 KREX 휴게소 코드에 잇는다.

    주유소(``facility_class=gas_station``) 행은 후보가 아니다. 분류를 모르는 행(0502에만 있는
    코드)은
    후보다 — 메뉴가 있으니 휴게소다.
    """
    index: dict[tuple[str, str | None], list[TransportRestAreaFood]] = defaultdict(list)
    for food in foods:
        if food.facility_class == "gas_station":
            continue
        index[name_key(food.name)].append(food)
    first: dict[str, RestAreaLink] = {}
    for natural_key, name in areas:
        candidates = index.get(name_key(name), [])
        classified = [food for food in candidates if food.facility_class is not None]
        menu_only = [food for food in candidates if food.facility_class is None]
        if len(candidates) == 1:
            first[natural_key] = RestAreaLink(natural_key, name, 1.0, "name_exact", candidates[0])
        elif len(classified) == 1 and menu_only:
            # 0615 코드 하나 + 0502에만 있는 옛 코드(2026-11-27 함양 000551 ↔ 000161). 코드·방향은
            # 0615,
            # 메뉴는 합친다.
            merged = replace(
                classified[0],
                menus=classified[0].menus
                + tuple(menu for food in menu_only for menu in food.menus),
            )
            first[natural_key] = RestAreaLink(
                natural_key, name, 0.95, "name_merged", merged,
                tuple(sorted(food.std_rest_code for food in candidates)),
            )
        elif candidates:
            first[natural_key] = RestAreaLink(
                natural_key, name, 0.0, "ambiguous", None,
                tuple(sorted(food.std_rest_code for food in candidates)),
            )
        else:
            first[natural_key] = RestAreaLink(natural_key, name, 0.0, "no_match", None)
    # 한 KREX 코드에 Map 휴게소 둘 이상이 붙으면 어느 쪽도 믿지 않는다.
    owners: dict[str, list[str]] = defaultdict(list)
    for link in first.values():
        if link.food is not None:
            owners[link.food.std_rest_code].append(link.natural_key)
    for code, keys in owners.items():
        if len(keys) > 1:
            for key in keys:
                link = first[key]
                first[key] = RestAreaLink(key, link.name, 0.0, "shared_code", None, (code,))
    return first


def with_rest_area_links(
    areas: Sequence[TransportRestArea], foods: Iterable[TransportRestAreaFood]
) -> list[TransportRestArea]:
    """휴게소마다 연결한 KREX 코드·노선·상하행을 ``ex_*`` 필드에 채운다.

    자연키·원천 필드는 그대로다.
    """
    links = link_rest_areas(((area.natural_key, area.name) for area in areas), foods)
    out: list[TransportRestArea] = []
    for area in areas:
        link = links[area.natural_key]
        if link.linked and link.food is not None:
            area = replace(
                area,
                ex_std_rest_code=link.food.std_rest_code,
                ex_route_code=link.food.route_code,
                ex_route_name=link.food.route_name,
                ex_direction_code=link.food.direction,
                ex_link_method=link.method,
                ex_link_confidence=link.confidence,
            )
        out.append(area)
    return out


def _base_related(left: str, right: str) -> bool:
    """같은 휴게소의 다른 표기인가("보성녹차" ↔ "보성", "금산인삼랜드" ↔ "인삼랜드")."""
    if not left or not right:
        return False
    short, long_ = sorted((left, right), key=len)
    return long_.startswith(short) if len(short) >= 2 else False


# -- 메뉴 요약 ----------------------------------------------------------------


MenuTag = Literal["best", "premium", "recommended"]


@dataclass(frozen=True, slots=True)
class MenuItem:
    name: str
    price: int | None
    tags: tuple[MenuTag, ...]
    season: Literal["all_year", "summer", "winter"] | None


@dataclass(frozen=True, slots=True)
class MenuSummary:
    menu_count: int
    price_min: int | None
    price_median: int | None
    price_max: int | None
    featured: tuple[MenuItem, ...]
    seasonal: tuple[MenuItem, ...]
    menu_updated_on: date | None


def _tags(menu: TransportRestAreaFoodMenu) -> tuple[MenuTag, ...]:
    tags: list[MenuTag] = []
    if menu.is_best:
        tags.append("best")
    if menu.is_premium:
        tags.append("premium")
    if menu.is_recommended:
        tags.append("recommended")
    return tuple(tags)


def _item(menu: TransportRestAreaFoodMenu) -> MenuItem:
    return MenuItem(name=menu.name, price=menu.price, tags=_tags(menu), season=menu.season)


def _price_order(menu: TransportRestAreaFoodMenu) -> tuple[int, str]:
    return (menu.price if menu.price is not None else 1 << 31, menu.name)


def summarize_menus(menus: Sequence[TransportRestAreaFoodMenu]) -> MenuSummary:
    """메뉴 목록 → 대표·추천 메뉴, 가격대(최저·중앙·최고), 계절 메뉴. 같은 입력이면 같은 출력이다.

    - 가격대는 0보다 큰 가격만 쓴다. 중앙값은 짝수 개면 낮은 쪽(실제 메뉴 가격 중 하나)이다.
    - 대표·추천: 대표 → 프리미엄 → 추천 순, 같은 무리 안에서는 가격·이름 순, 최대
      :data:`FEATURED_MENU_LIMIT`.
    - 계절: 여름·겨울 메뉴(사계절 제외), 여름 → 겨울, 가격·이름 순, 최대
      :data:`SEASONAL_MENU_LIMIT`.
    """
    prices = sorted(menu.price for menu in menus if menu.price is not None and menu.price > 0)
    featured = sorted(
        (menu for menu in menus if menu.is_best or menu.is_premium or menu.is_recommended),
        key=lambda menu: (
            0 if menu.is_best else 1 if menu.is_premium else 2,
            *_price_order(menu),
        ),
    )
    seasonal = sorted(
        (menu for menu in menus if menu.season in ("summer", "winter")),
        key=lambda menu: (0 if menu.season == "summer" else 1, *_price_order(menu)),
    )
    updated = [menu.menu_updated_on for menu in menus if menu.menu_updated_on is not None]
    return MenuSummary(
        menu_count=len(menus),
        price_min=prices[0] if prices else None,
        price_median=int(statistics.median_low(prices)) if prices else None,
        price_max=prices[-1] if prices else None,
        featured=tuple(_item(menu) for menu in featured[:FEATURED_MENU_LIMIT]),
        seasonal=tuple(_item(menu) for menu in seasonal[:SEASONAL_MENU_LIMIT]),
        menu_updated_on=max(updated) if updated else None,
    )


# -- 오피넷 주유소 ↔ 휴게소 ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class StationPairCandidate:
    """400 m 안 휴게소 후보 하나."""

    key: str
    """후보 식별자(호출자가 정한다 — 보통 휴게소 상태의 ``feature_id``)."""
    rest_area_name: str
    direction_code: Literal["up", "down"] | None
    distance_m: float


@dataclass(frozen=True, slots=True)
class StationPair:
    key: str
    confidence: float
    method: str
    distance_m: float

    @property
    def automatic(self) -> bool:
        return self.confidence >= STATION_PAIR_AUTO_CONFIDENCE


_UPDOWN: Final[Mapping[str, Literal["up", "down"]]] = {
    "상": "up", "상행": "up", "하": "down", "하행": "down",
}


def _station_tokens(station_name: str) -> tuple[str, set[str], set[tuple[str, str]]]:
    """주유소 이름 → (정리한 이름, 행선지 토큰, ``(이름, 행선지)`` 쌍)."""
    text = _clean(_CORP.sub("", station_name))
    pairs = {
        (_SUFFIX.sub("", match.group(1))[-8:], _strip_dest(match.group(2)))
        for match in re.finditer(r"([가-힣A-Za-z0-9]+?)\(([^()]+)\)", text)
    }
    tokens = {_strip_dest(dest) for _, dest in pairs}
    tokens.update(match.group(1) for match in re.finditer(r"([가-힣]+?)방향", text))
    return text, tokens, pairs


def _station_mentions(text: str, pairs: set[tuple[str, str]], base: str) -> bool:
    """주유소 이름이 휴게소 이름을 담는가.

    "밀양(함양)" ↔ "밀양영남루", "고삼하이파크고삼(세종)" ↔ "고삼호수".
    """
    if base in text:
        return True
    for station_base, _ in pairs:
        for start in range(len(station_base) - 1):
            if _base_related(station_base[start:], base):
                return True
    stem = _SUFFIX.sub("", re.split(r"주유소|충전소", text)[0])
    return any(_base_related(stem[start:], base) for start in range(max(len(stem) - 1, 0)))


def _score(station_name: str, candidate: StationPairCandidate, crowded: bool) -> tuple[float, str]:
    text, tokens, pairs = _station_tokens(station_name)
    base, dest = name_key(candidate.rest_area_name)
    if not _station_mentions(text, pairs, base):
        return (0.5 if not crowded and candidate.distance_m <= 150 else 0.3), "distance_only"
    if "양방향" in tokens or dest is None:
        return 0.9, "name_bidirectional"
    if dest in tokens or dest in text.replace(base, "", 1):
        return 0.95, "name_direction"
    updown = {_UPDOWN[token] for token in tokens if token in _UPDOWN}
    if candidate.direction_code is not None and updown == {candidate.direction_code}:
        return 0.9, "name_updown"
    return 0.6, "name_only"


def pair_station(
    station_name: str, candidates: Sequence[StationPairCandidate]
) -> StationPair | None:
    """주유소 하나를 400 m 안 휴게소 후보 중 하나와 짝짓는다. 후보가 없으면 None.

    이름 근거가 거리보다 앞선다(같은 휴게소 상하행 주유소의 좌표가 서로 바뀌어 있는 원천 사례가
    있다).
    이름이 휴게소만 가리키고 방향을 못 가리면(``name_only``) 그 휴게소 이름의 후보가 하나일 때만
    0.85다.
    """
    if not candidates:
        return None
    crowded = len(candidates) > 1
    scored = sorted(
        (
            (*_score(station_name, candidate, crowded), candidate)
            for candidate in candidates
        ),
        key=lambda row: (-row[0], row[2].distance_m, row[2].key),
    )
    confidence, method, best = scored[0]
    if method == "name_only" and sum(1 for row in scored if row[1] == "name_only") == 1:
        confidence, method = 0.85, "name_single"
    tied = [
        row
        for row in scored
        if row[0] == confidence and row[1] == method and row[2] is not best
    ]
    if tied and confidence >= STATION_PAIR_AUTO_CONFIDENCE and method != "name_bidirectional":
        # 같은 근거로 둘이 맞으면 고르지 않는다.
        confidence, method = 0.6, f"{method}_tie"
    return StationPair(best.key, confidence, method, best.distance_m)
