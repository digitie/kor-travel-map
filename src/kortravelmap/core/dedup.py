"""``kortravelmap.core.dedup`` — cross-provider dedup 후보 생성 (ADR-016, SPRINT-3 §2.5).

서로 다른 provider의 같은 실세계 장소(예: knps ``cultural_resources``(사찰) ↔
krheritage ``temple``)를 ``score_pair``(ADR-016 Record Linkage)로 cross-score해
``manual_review``/``auto_merge`` 후보를 만든다. 본 모듈은 **순수 함수** (ADR-002
core 계층) — DB 의존 없음. 실제 ``ops.dedup_review_queue`` 적재는 적재
오케스트레이션(후속)이 본 결과를 받아 수행한다.

ADR 참조
--------
- ADR-002 — core 순수 함수 (stdlib/Protocol/scoring만)
- ADR-016 — Record Linkage 가중 점수 + 임계값 (``score_pair``/``classify_decision``)
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol, runtime_checkable

from kortravelmap.core.events import compare_event_occurrences
from kortravelmap.core.scoring import (
    THRESHOLD_MANUAL,
    WEIGHT_CATEGORY,
    WEIGHT_NAME,
    WEIGHT_SPATIAL,
    DedupDecision,
    category_similarity,
    classify_decision,
    haversine_meters,
    name_similarity,
    normalize_kr_place_name,
    score_pair,
    spatial_similarity,
)

if TYPE_CHECKING:
    from kortravelmap.dto.coordinate import Coordinate

__all__ = [
    "DEDUP_MATCH_MODES",
    "DedupInput",
    "DedupCandidate",
    "DedupMatch",
    "DedupPoint",
    "find_dedup_candidates",
    "find_sibling_candidates",
    "route_overlap_candidate",
]

DedupMatch = Literal["score", "same_name", "score_or_same_name"]
"""점 후보의 판정 방식(#1468).

- ``score`` — ADR-016 점수가 ``THRESHOLD_MANUAL`` 이상인 쌍(기존 동작).
- ``same_name`` — 정규화 이름(``normalize_kr_place_name``)이 같은 쌍만. 점수와 무관하게
  최소 ``manual_review``로 올린다(예: 같은 이름의 휴양림·수목원 — 범주가 달라 점수 상한이
  0.80이고 28 m 밖이면 0.65에 못 미친다).
- ``score_or_same_name`` — 둘 중 하나라도 맞으면.
"""

DEDUP_MATCH_MODES: Final[frozenset[str]] = frozenset(
    {"score", "same_name", "score_or_same_name"}
)

_METERS_PER_DEGREE_LAT: Final[float] = 111_320.0
#: 경도 1도 길이의 하한을 잡는 위도 — 한반도(33~39°N)보다 북쪽으로 잡아 격자 칸이 반경보다
#: 좁아지지 않게 한다(칸이 반경 이상이면 이웃 3×3 칸이 반경 원을 다 덮는다).
_GRID_LAT_BOUND_DEG: Final[float] = 45.0


@runtime_checkable
class DedupInput(Protocol):
    """dedup 후보 생성 입력 shape — ``Feature``가 그대로 만족.

    ``Feature``는 ``feature_id``/``name``/``coord``/``category``를 모두 가지므로
    추가 adapter 없이 직접 넘길 수 있다.
    """

    @property
    def feature_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def coord(self) -> Coordinate | None: ...

    @property
    def category(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def detail(self) -> object: ...


@dataclass(frozen=True)
class DedupCandidate:
    """cross-provider 중복 후보 1쌍 (score + 결정 + 성분 점수).

    ``decision``은 ``DedupDecision`` 상수 (``auto_merge``/``manual_review``).
    ``ops.dedup_review_queue`` 적재 시 ``manual_review``만 운영자 검토 대상.
    """

    feature_id_a: str
    feature_id_b: str
    name_a: str
    name_b: str
    score: float
    decision: str
    name_score: float
    spatial_score: float
    category_score: float
    reason: str | None = None
    """큐 ``decision_reason``에 남길 설명. ``None``이면 ``decision``을 그대로 쓴다.

    점수 밖 규칙으로 올린 후보는 그 규칙을 적는다(``manual_review:same_name``,
    ``manual_review:route_overlap=0.87``) — 검토자가 왜 올랐는지 본다(#1468)."""


@dataclass(frozen=True)
class DedupPoint:
    """``DedupInput``을 만족하는 최소 값 객체 — 선형 겹침 후보처럼 repo가 쌍을 직접 찾을 때."""

    feature_id: str
    name: str
    coord: Coordinate | None
    category: str
    kind: str
    detail: object = None


def route_overlap_candidate(
    a: DedupInput, b: DedupInput, *, overlap_ratio: float
) -> DedupCandidate:
    """선형 겹침으로 찾은 쌍 → ``manual_review`` 후보(#1468).

    점수 성분은 점 후보와 같은 식(``score_pair``)으로 둔다 — 큐의 ``total_score``를 F7
    (점수 회귀 감시)이 같은 식으로 다시 계산하기 때문이다. 겹침 비율은 ``reason``에 적는다.
    자동 병합하지 않는다: 같은 산의 다른 갈래도 버퍼 안에서 겹칠 수 있다.
    """
    if not 0.0 <= overlap_ratio <= 1.0:
        raise ValueError(f"overlap_ratio는 0~1이어야 한다: {overlap_ratio!r}")
    score = score_pair(
        name_a=a.name,
        name_b=b.name,
        coord_a=a.coord,
        coord_b=b.coord,
        cat_a={a.category},
        cat_b={b.category},
    )
    return DedupCandidate(
        feature_id_a=a.feature_id,
        feature_id_b=b.feature_id,
        name_a=a.name,
        name_b=b.name,
        score=round(score, 4),
        decision=DedupDecision.MANUAL_REVIEW,
        name_score=round(name_similarity(a.name, b.name), 4),
        spatial_score=round(spatial_similarity(a.coord, b.coord), 4),
        category_score=round(category_similarity({a.category}, {b.category}), 4),
        reason=f"{DedupDecision.MANUAL_REVIEW}:route_overlap={overlap_ratio:.2f}",
    )


def find_dedup_candidates(
    left: Iterable[DedupInput],
    right: Iterable[DedupInput],
    *,
    include_auto_merge: bool = True,
    max_distance_m: float | None = None,
    match: DedupMatch = "score",
) -> list[DedupCandidate]:
    """``left`` × ``right`` cross-score → 중복 후보 리스트 (점수 내림차순).

    같은 실세계 entity일 가능성이 있는 서로 다른 provider feature 쌍을 찾는다.
    ``KEEP_SEPARATE``(< THRESHOLD_MANUAL)는 제외. ``include_auto_merge=False``면
    ``manual_review`` 밴드만(``ops.dedup_review_queue`` 입주분) 반환.

    Parameters
    ----------
    left, right
        ``DedupInput`` (보통 두 provider의 feature 집합; 예: knps 사찰 / krheritage
        temple). 호출 측에서 종류(사찰/temple)로 미리 필터링해 넘긴다.
    include_auto_merge
        ``auto_merge``(>= THRESHOLD_AUTO) 후보 포함 여부. 기본 True.
    max_distance_m
        주어지면 두 좌표가 이 거리(m) 안인 쌍만 본다 — 좌표 격자로 blocking해 비교 수를
        줄이고, 같은 범주·같은 이름이면 거리와 무관하게 0.65가 되는 전국 동명 쌍(체인점 등)을
        끊는다. 좌표가 없는 feature는 이때 비교하지 않는다(#1468).
    match
        ``DedupMatch`` — ``score``(기본)·``same_name``·``score_or_same_name``.

    Returns
    -------
    list[DedupCandidate]
        score 내림차순. 각 후보는 성분 점수(name/spatial/category) 동봉 →
        운영자 검토·디버깅 용이.

    Notes
    -----
    ``max_distance_m``가 없으면 O(len(left) × len(right)). 있으면 격자 3×3 이웃 칸만 본다.
    """
    if match not in DEDUP_MATCH_MODES:
        raise ValueError(f"dedup match 방식 아님: {match!r}")
    if max_distance_m is not None and not max_distance_m > 0:
        raise ValueError("max_distance_m은 0보다 커야 한다")
    if match != "score" and max_distance_m is None:
        # 이름만 같으면 올리는 방식에 거리 상한이 없으면 전국 동명 시설이 전부 쌍이 된다.
        raise ValueError(f"match={match!r}에는 max_distance_m이 필요하다")
    candidates: list[DedupCandidate] = []
    if max_distance_m is None:
        right_list = list(right)
        for a in left:
            for b in right_list:
                cand = _score_candidate(
                    a, b, include_auto_merge=include_auto_merge, match=match
                )
                if cand is not None:
                    candidates.append(cand)
    else:
        grid = _CoordGrid(right, max_distance_m)
        for a in left:
            if a.coord is None:
                continue
            for b in grid.near(a.coord):
                cand = _score_candidate(
                    a, b, include_auto_merge=include_auto_merge, match=match
                )
                if cand is not None:
                    candidates.append(cand)
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


class _CoordGrid:
    """반경 ``radius_m`` 이웃 조회용 위경도 격자. 칸 한 변이 반경 이상이라 3×3 칸이 원을 덮는다."""

    def __init__(self, items: Iterable[DedupInput], radius_m: float) -> None:
        self._radius_m = radius_m
        self._lat_step = radius_m / _METERS_PER_DEGREE_LAT
        self._lon_step = radius_m / (
            _METERS_PER_DEGREE_LAT * math.cos(math.radians(_GRID_LAT_BOUND_DEG))
        )
        self._cells: dict[tuple[int, int], list[DedupInput]] = defaultdict(list)
        for item in items:
            if item.coord is not None:
                self._cells[self._key(item.coord)].append(item)

    def _key(self, coord: Coordinate) -> tuple[int, int]:
        return (
            math.floor(float(coord.lat) / self._lat_step),
            math.floor(float(coord.lon) / self._lon_step),
        )

    def near(self, coord: Coordinate) -> Iterable[DedupInput]:
        lat_key, lon_key = self._key(coord)
        for d_lat in (-1, 0, 1):
            for d_lon in (-1, 0, 1):
                for item in self._cells.get((lat_key + d_lat, lon_key + d_lon), ()):
                    if item.coord is not None and (
                        haversine_meters(coord, item.coord) <= self._radius_m
                    ):
                        yield item


def _same_name(a: DedupInput, b: DedupInput) -> bool:
    norm_a = normalize_kr_place_name(a.name)
    return bool(norm_a) and norm_a == normalize_kr_place_name(b.name)


def _score_candidate(
    a: DedupInput,
    b: DedupInput,
    *,
    include_auto_merge: bool,
    match: DedupMatch = "score",
) -> DedupCandidate | None:
    """한 쌍(a, b)을 score → ``DedupCandidate`` 또는 제외 시 ``None``.

    ``match="score"``면 ``KEEP_SEPARATE``(< THRESHOLD_MANUAL)는 ``None``.
    ``same_name``류는 정규화 이름이 같은 쌍을 점수와 무관하게 최소 ``manual_review``로
    올린다. ``include_auto_merge=False``면 ``auto_merge`` 밴드도 ``None``.
    """
    if a.kind != b.kind:
        return None
    occurrence = compare_event_occurrences(a.detail, b.detail) if a.kind == "event" else "same"
    if occurrence == "different":
        return None
    same_name = match != "score" and _same_name(a, b)
    if match == "same_name" and not same_name:
        return None
    if not same_name:
        # 이름 유사도(가장 비싼 성분)를 부르기 전에 상한으로 거른다 — 이름이 완전히 같다고
        # 쳐도 수동 검토 임계값에 못 미치면 결과는 KEEP_SEPARATE다(가지치기일 뿐 판정은 같다,
        # #1459). 식은 ``score_pair``와 같은 순서·같은 가중치라 부동소수 결과도 같다.
        spatial = spatial_similarity(a.coord, b.coord)
        category = category_similarity({a.category}, {b.category})
        bound = WEIGHT_NAME * 1.0 + WEIGHT_SPATIAL * spatial + WEIGHT_CATEGORY * category
        if bound < THRESHOLD_MANUAL:
            return None
    score = score_pair(
        name_a=a.name,
        name_b=b.name,
        coord_a=a.coord,
        coord_b=b.coord,
        cat_a={a.category},
        cat_b={b.category},
    )
    decision = classify_decision(score)
    reason: str | None = None
    if decision == DedupDecision.KEEP_SEPARATE:
        if not same_name:
            return None
        decision = DedupDecision.MANUAL_REVIEW
        reason = f"{DedupDecision.MANUAL_REVIEW}:same_name"
    if decision == DedupDecision.AUTO_MERGE and occurrence == "unknown":
        decision = DedupDecision.MANUAL_REVIEW
    if decision == DedupDecision.AUTO_MERGE and not include_auto_merge:
        return None
    return DedupCandidate(
        feature_id_a=a.feature_id,
        feature_id_b=b.feature_id,
        name_a=a.name,
        name_b=b.name,
        score=round(score, 4),
        decision=decision,
        name_score=round(name_similarity(a.name, b.name), 4),
        spatial_score=round(spatial_similarity(a.coord, b.coord), 4),
        category_score=round(category_similarity({a.category}, {b.category}), 4),
        reason=reason,
    )


def find_sibling_candidates(
    features: Iterable[DedupInput],
    *,
    include_auto_merge: bool = True,
) -> list[DedupCandidate]:
    """**같은 집합 내** 중복 후보 (within-set pairwise) — MOIS 자기 sibling.

    하나의 provider/dataset 안에서 같은 실세계 사업장이 2개 슬러그로 중복 등록된
    경우(예: MOIS ``general_restaurants`` ↔ ``tourist_restaurants``)를 찾는다.
    ``find_dedup_candidates``가 두 집합 cross-product인 것과 달리, 본 함수는 한
    집합의 **고유 쌍**(i < j)만 score한다 — self-pair(같은 feature_id)와 대칭
    중복(b,a)을 제외.

    Parameters
    ----------
    features
        같은 dataset의 ``DedupInput`` 집합 (``Feature``가 그대로 만족). 동일
        ``feature_id``가 중복으로 들어와도 self-pair는 건너뛴다.
    include_auto_merge
        ``auto_merge`` 후보 포함 여부 (기본 True).

    Returns
    -------
    list[DedupCandidate]
        score 내림차순. ``feature_id_a``/``_b``는 입력 순서를 따른다.

    Notes
    -----
    O(n²/2). 대규모 dataset은 후속에 blocking(시군구/grid)으로 후보 축소
    (``find_dedup_candidates`` Notes와 동일).
    """
    items = list(features)
    candidates: list[DedupCandidate] = []
    for i in range(len(items)):
        a = items[i]
        for j in range(i + 1, len(items)):
            b = items[j]
            if a.feature_id == b.feature_id:
                continue  # self-pair (중복 입력) 제외
            cand = _score_candidate(a, b, include_auto_merge=include_auto_merge)
            if cand is not None:
                candidates.append(cand)
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
