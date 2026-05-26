"""``krtour.map.core.scoring`` — Record Linkage scoring (ADR-016).

같은 장소가 여러 provider에서 다른 이름/좌표로 올라온 경우, 자동 병합 / 수동
검토 / 별개 유지 셋 중 하나를 결정하는 점수 계산.

ADR-016 (SPEC V8 D-14):
- **Blocking** (DB 측): ``ST_DWithin(coord::geography, 100)`` + 같은 ``bjd_code``
  + 같은 ``kind`` 후보군 추출.
- **Scoring** (본 모듈): ``0.45 * name_sim + 0.35 * spatial_sim + 0.20 * category_sim``.
  - name_sim: ``jellyfish.jaro_winkler_similarity(normalize_kr_place_name(a),
    normalize_kr_place_name(b))``
  - spatial_sim: ``math.exp(-haversine_m / 50.0)`` (50m exponential decay)
  - category_sim: Jaccard on category tag set
- **임계값**:
  - `THRESHOLD_AUTO = 0.85` — 자동 병합 (master 선정 룰 적용).
  - `THRESHOLD_MANUAL = 0.65` — 수동 검토 큐 (`ops.dedup_review_queue`).
  - < 0.65 — 별개 feature 유지.

ADR 참조
--------
- ADR-016 — 본 모듈의 결정 (가중치 + 임계값 + master 선정)
- ADR-019 — datetime aware (master 선정 시 ``updated_at`` 비교)
- ADR-033 — Phase 2 consistency report에서 본 모듈 결과 활용
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Final

import jellyfish

from krtour.map.dto.coordinate import Coordinate

__all__ = [
    # 가중치 + 임계값 상수
    "WEIGHT_NAME",
    "WEIGHT_SPATIAL",
    "WEIGHT_CATEGORY",
    "THRESHOLD_AUTO",
    "THRESHOLD_MANUAL",
    "SPATIAL_DECAY_METERS",
    # scoring 함수
    "normalize_kr_place_name",
    "name_similarity",
    "spatial_similarity",
    "category_similarity",
    "score_pair",
    "haversine_meters",
    # 결과 분류
    "DedupDecision",
    "classify_decision",
]


# -- 가중치 (ADR-016 SPEC V8 D-14) ---------------------------------------


WEIGHT_NAME: Final[float] = 0.45
"""name similarity 가중치. 한국어 장소명은 띄어쓰기/접미사 변형이 많아 spatial
보다 약간 우선."""

WEIGHT_SPATIAL: Final[float] = 0.35
"""spatial (좌표 거리) similarity 가중치."""

WEIGHT_CATEGORY: Final[float] = 0.20
"""category tag set Jaccard 가중치. provider 간 category 매핑 불일치 잦음."""

# Sanity check — 합이 정확히 1.0.
assert abs((WEIGHT_NAME + WEIGHT_SPATIAL + WEIGHT_CATEGORY) - 1.0) < 1e-9


SPATIAL_DECAY_METERS: Final[float] = 50.0
"""spatial_sim = exp(-d / 50). 50m에서 0.37, 100m에서 0.14, 200m에서 0.018."""


THRESHOLD_AUTO: Final[float] = 0.85
"""auto-merge 임계값. 이상이면 ``master`` 선정 + 즉시 병합."""

THRESHOLD_MANUAL: Final[float] = 0.65
"""manual-review 임계값. 이 이상 ~ AUTO 미만이면 ``ops.dedup_review_queue``에
입주, 운영자 판단 대기."""


# -- 한국어 장소명 정규화 -------------------------------------------------


# 흔한 시설 접미사 / 접두사 (병합 비교 시 무시).
_NAME_TRIM_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\s+"),  # 다중 공백 → 하나
    re.compile(r"[\(\[].*?[\)\]]"),  # 괄호 안 내용 제거 (예: "장소 (분점)" → "장소")
)

# (선택) 제거할 흔한 접미사. 너무 공격적이면 false-positive 증가 — 보수적으로.
_NAME_SUFFIX_TO_STRIP: Final[tuple[str, ...]] = ()


def normalize_kr_place_name(name: str) -> str:
    """한국어 장소명 정규화 — Unicode NFKC + lower + 괄호 제거 + 공백 모두 제거.

    한국어 장소명은 provider 간 공백 사용이 비일관적 ("서울시청"/"서울 시청"/
    "서울특별시청"/"서울 특별시청"). name similarity 비교 시 공백 차이로
    동일 장소가 다르게 매칭되는 false-negative를 막기 위해 **모든 공백 제거**.

    Parameters
    ----------
    name
        provider raw 장소명.

    Returns
    -------
    str
        정규화된 비교용 문자열 (공백 0).

    Examples
    --------
    >>> normalize_kr_place_name("서울시청")
    '서울시청'
    >>> normalize_kr_place_name("  서울  시청  ")
    '서울시청'
    >>> normalize_kr_place_name("서울시청(본관)")
    '서울시청'
    """
    if not name:
        return ""
    # NFKC: 전각/반각, 호환 분해/조합 정규화.
    result = unicodedata.normalize("NFKC", name).strip().lower()
    # 괄호 내용 제거.
    for pattern in _NAME_TRIM_PATTERNS[1:]:
        result = pattern.sub("", result)
    # 모든 공백 제거 (한국어 장소명 공백 변형 흡수).
    return _NAME_TRIM_PATTERNS[0].sub("", result)


def name_similarity(a: str, b: str) -> float:
    """장소명 유사도 ∈ [0, 1] — Jaro-Winkler (정규화 후).

    ADR-016: ``jellyfish.jaro_winkler_similarity(normalize_kr_place_name(a), ...)``.
    """
    norm_a = normalize_kr_place_name(a)
    norm_b = normalize_kr_place_name(b)
    if not norm_a or not norm_b:
        return 0.0
    return float(jellyfish.jaro_winkler_similarity(norm_a, norm_b))


# -- 좌표 거리 ----------------------------------------------------------


_EARTH_RADIUS_M: Final[float] = 6_371_000.0
"""평균 지구 반지름 (m). haversine 공식용."""


def haversine_meters(a: Coordinate, b: Coordinate) -> float:
    """두 ``Coordinate`` 간 대원 거리 (m, haversine 공식).

    Python 측 거리 계산이 필요할 때 사용 — 실 DB 반경 검색은 PostGIS
    ``ST_DWithin(coord_5179, ...)``로 한다 (ADR-012).
    """
    lat1 = math.radians(float(a.lat))
    lat2 = math.radians(float(b.lat))
    dlat = math.radians(float(b.lat) - float(a.lat))
    dlon = math.radians(float(b.lon) - float(a.lon))
    inner = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(inner), math.sqrt(1 - inner))
    return _EARTH_RADIUS_M * c


def spatial_similarity(a: Coordinate | None, b: Coordinate | None) -> float:
    """좌표 거리 → 유사도 ∈ [0, 1].

    ADR-016: ``exp(-d / 50)``. 한 쪽이라도 좌표 없으면 0.

    Examples
    --------
    >>> from decimal import Decimal
    >>> c1 = Coordinate(lon=Decimal("126.97"), lat=Decimal("37.57"))
    >>> c2 = Coordinate(lon=Decimal("126.97"), lat=Decimal("37.57"))
    >>> spatial_similarity(c1, c2)
    1.0
    """
    if a is None or b is None:
        return 0.0
    d_m = haversine_meters(a, b)
    return math.exp(-d_m / SPATIAL_DECAY_METERS)


# -- 카테고리 유사도 ----------------------------------------------------


def category_similarity(
    a_tags: set[str] | frozenset[str] | None,
    b_tags: set[str] | frozenset[str] | None,
) -> float:
    """카테고리 태그 집합 Jaccard 유사도 ∈ [0, 1].

    Parameters
    ----------
    a_tags, b_tags
        카테고리 코드/이름 set. ``None`` 또는 빈 set이면 0.

    Examples
    --------
    >>> category_similarity({"01020101"}, {"01020101"})
    1.0
    >>> category_similarity({"01020101", "01020102"}, {"01020101"})
    0.5
    >>> category_similarity(set(), {"01020101"})
    0.0
    """
    if not a_tags or not b_tags:
        return 0.0
    a_set = set(a_tags)
    b_set = set(b_tags)
    intersection = len(a_set & b_set)
    union = len(a_set | b_set)
    return intersection / union if union > 0 else 0.0


# -- 종합 scoring -------------------------------------------------------


def score_pair(
    *,
    name_a: str,
    name_b: str,
    coord_a: Coordinate | None,
    coord_b: Coordinate | None,
    cat_a: set[str] | frozenset[str] | None,
    cat_b: set[str] | frozenset[str] | None,
) -> float:
    """ADR-016 종합 점수 ∈ [0, 1].

    ``WEIGHT_NAME * name_sim + WEIGHT_SPATIAL * spatial_sim +
    WEIGHT_CATEGORY * category_sim``.

    keyword-only 인자만 — 호출 측에서 positional 순서 혼동 차단.

    Examples
    --------
    >>> from decimal import Decimal
    >>> c1 = Coordinate(lon=Decimal("126.97"), lat=Decimal("37.57"))
    >>> c2 = Coordinate(lon=Decimal("126.97"), lat=Decimal("37.57"))
    >>> score_pair(
    ...     name_a="서울시청", name_b="서울시청",
    ...     coord_a=c1, coord_b=c2,
    ...     cat_a={"01020101"}, cat_b={"01020101"},
    ... )
    1.0
    """
    n = name_similarity(name_a, name_b)
    s = spatial_similarity(coord_a, coord_b)
    c = category_similarity(cat_a, cat_b)
    return WEIGHT_NAME * n + WEIGHT_SPATIAL * s + WEIGHT_CATEGORY * c


# -- 결과 분류 -----------------------------------------------------------


class DedupDecision:
    """ADR-016 임계값 기준 분류 결과 (string constant container).

    실제 dedup 처리 코드 (Sprint 3+)는 본 enum-like를 사용한다.
    """

    AUTO_MERGE: Final[str] = "auto_merge"
    """``>= THRESHOLD_AUTO``. master 선정 + 즉시 병합 (`feature_merge_history`)."""

    MANUAL_REVIEW: Final[str] = "manual_review"
    """``THRESHOLD_MANUAL <= score < THRESHOLD_AUTO``. ``ops.dedup_review_queue``
    입주 → 운영자 판단 대기."""

    KEEP_SEPARATE: Final[str] = "keep_separate"
    """``< THRESHOLD_MANUAL``. 별개 feature 유지."""


def classify_decision(score: float) -> str:
    """점수 → 결정. ``DedupDecision`` 상수 중 하나 반환.

    Examples
    --------
    >>> classify_decision(0.90)
    'auto_merge'
    >>> classify_decision(0.70)
    'manual_review'
    >>> classify_decision(0.50)
    'keep_separate'
    """
    if score >= THRESHOLD_AUTO:
        return DedupDecision.AUTO_MERGE
    if score >= THRESHOLD_MANUAL:
        return DedupDecision.MANUAL_REVIEW
    return DedupDecision.KEEP_SEPARATE
