"""``krtour.map.core.dedup`` — cross-provider dedup 후보 생성 (ADR-016, SPRINT-3 §2.5).

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

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from krtour.map.core.scoring import (
    DedupDecision,
    category_similarity,
    classify_decision,
    name_similarity,
    score_pair,
    spatial_similarity,
)

if TYPE_CHECKING:
    from krtour.map.dto.coordinate import Coordinate

__all__ = ["DedupInput", "DedupCandidate", "find_dedup_candidates"]


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


def find_dedup_candidates(
    left: Iterable[DedupInput],
    right: Iterable[DedupInput],
    *,
    include_auto_merge: bool = True,
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

    Returns
    -------
    list[DedupCandidate]
        score 내림차순. 각 후보는 성분 점수(name/spatial/category) 동봉 →
        운영자 검토·디버깅 용이.

    Notes
    -----
    O(len(left) × len(right)) — SPRINT-3 §2.5의 사찰/temple은 수십~수백 건이라
    충분. 대규모 dataset은 후속에 blocking(시군구/grid)으로 후보 축소.
    """
    candidates: list[DedupCandidate] = []
    right_list = list(right)
    for a in left:
        for b in right_list:
            score = score_pair(
                name_a=a.name,
                name_b=b.name,
                coord_a=a.coord,
                coord_b=b.coord,
                cat_a={a.category},
                cat_b={b.category},
            )
            decision = classify_decision(score)
            if decision == DedupDecision.KEEP_SEPARATE:
                continue
            if decision == DedupDecision.AUTO_MERGE and not include_auto_merge:
                continue
            candidates.append(
                DedupCandidate(
                    feature_id_a=a.feature_id,
                    feature_id_b=b.feature_id,
                    name_a=a.name,
                    name_b=b.name,
                    score=round(score, 4),
                    decision=decision,
                    name_score=round(name_similarity(a.name, b.name), 4),
                    spatial_score=round(spatial_similarity(a.coord, b.coord), 4),
                    category_score=round(
                        category_similarity({a.category}, {b.category}), 4
                    ),
                )
            )
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
