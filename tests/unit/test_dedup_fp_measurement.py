"""``test_dedup_fp_measurement`` — ADR-016 scoring false-positive 측정/회귀 가드.

대표 라벨 평가셋(true duplicate / distinct, **blocking 범위 내** — ADR-016 DB
blocking이 100m·같은 bjd·같은 kind로 사전 필터하므로 멀리 떨어진 쌍은 애초에
후보가 아님)을 실제 ``score_pair``/``classify_decision``으로 채점해 다음을 가드한다:

1. **오토머지 오류 0** — distinct 쌍이 ``THRESHOLD_AUTO``(0.85) 이상으로 올라가
   자동 병합되지 않는다(가장 위험한 FP). 핵심 안전 속성.
2. **true-dup recall 100%** — 모든 true duplicate가 ``THRESHOLD_MANUAL``(0.65)
   이상으로 최소한 검토 큐에 들어온다(놓치지 않음).
3. manual 임계 precision은 측정만(접근 가까운 같은 카테고리 distinct는 manual로
   가는 게 설계 의도 — 운영자 판단). 회귀 floor만 가드.

상세 분석/권고는 ``docs/reports/dedup-fp-measurement-2026-06-01.md``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from krtour.map.core.scoring import (
    THRESHOLD_AUTO,
    THRESHOLD_MANUAL,
    classify_decision,
    score_pair,
)
from krtour.map.dto.coordinate import Coordinate


def _c(lon: str, lat: str) -> Coordinate:
    return Coordinate(lon=Decimal(lon), lat=Decimal(lat))


_BASE = _c("126.9780", "37.5665")
_N30 = _c("126.97834", "37.56668")  # ~30m
_N20 = _c("126.97822", "37.56662")  # ~20m
_N10 = _c("126.97811", "37.56655")  # ~10m

# (label, is_duplicate, name_a, name_b, coord_a, coord_b, cat_a, cat_b)
_CASES = (
    # ── true duplicates (cross-provider 표기 변이) ──
    ("exact-same", True, "서울특별시청", "서울특별시청", _BASE, _BASE, {"01"}, {"01"}),
    ("spacing", True, "롯데월드 어드벤처", "롯데월드어드벤처", _BASE, _BASE, {"02"}, {"02"}),
    ("paren-branch", True, "스타벅스 (종로점)", "스타벅스", _BASE, _BASE, {"06"}, {"06"}),
    ("coord-30m", True, "경복궁", "경복궁", _BASE, _N30, {"01"}, {"01"}),
    ("space-mid", True, "국립중앙박물관", "국립 중앙박물관", _BASE, _BASE, {"01"}, {"01"}),
    ("cat-mismatch", True, "불국사", "불국사", _BASE, _BASE, {"0107"}, {"0202"}),
    ("brand-suffix", True, "이디야 강남점", "이디야커피 강남점", _BASE, _BASE, {"06"}, {"06"}),
    # ── distinct (blocking 범위 내 별개 장소) ──
    ("diff-food", False, "김밥천국", "맘스터치", _BASE, _BASE, {"0201"}, {"0201"}),
    ("diff-retail", False, "올리브영", "다이소", _BASE, _N20, {"06"}, {"06"}),
    ("diff-cafe", False, "스타벅스", "투썸플레이스", _BASE, _BASE, {"06"}, {"06"}),
    ("pharmacy-suffix", False, "현대약국", "종로약국", _BASE, _N10, {"0303"}, {"0303"}),
    ("church-suffix", False, "중앙교회", "제일교회", _BASE, _N20, {"05"}, {"05"}),
    ("mart-suffix", False, "행복마트", "건강마트", _BASE, _N10, {"06"}, {"06"}),
    ("diff-name-samecat", False, "종로떡집", "광화문문구", _BASE, _N30, {"06"}, {"06"}),
)


def _scored() -> list[tuple[str, bool, float, str]]:
    out = []
    for label, is_dup, na, nb, ca, cb, cata, catb in _CASES:
        sc = score_pair(
            name_a=na, name_b=nb, coord_a=ca, coord_b=cb, cat_a=cata, cat_b=catb
        )
        out.append((label, is_dup, sc, classify_decision(sc)))
    return out


@pytest.mark.unit
def test_no_false_auto_merge() -> None:
    """distinct 쌍은 어느 것도 AUTO 임계 이상이 아니다(자동 병합 FP = 0)."""
    offenders = [
        (label, sc)
        for label, is_dup, sc, _ in _scored()
        if (not is_dup) and sc >= THRESHOLD_AUTO
    ]
    assert offenders == [], f"false auto-merges: {offenders}"


@pytest.mark.unit
def test_true_duplicate_recall_into_queue() -> None:
    """모든 true duplicate는 MANUAL 임계 이상(최소 검토 큐 진입) — recall 100%."""
    missed = [
        (label, sc)
        for label, is_dup, sc, _ in _scored()
        if is_dup and sc < THRESHOLD_MANUAL
    ]
    assert missed == [], f"missed true duplicates: {missed}"


@pytest.mark.unit
def test_candidate_precision_floor() -> None:
    """MANUAL 임계 이상 후보의 precision 회귀 floor (현 측정 ≈ 0.64).

    manual로 가는 가까운 동일-카테고리 distinct는 설계 의도(운영자 판단)이므로
    precision은 1.0이 목표가 아니다 — 회귀(급락)만 가드.
    """
    scored = _scored()
    candidates = [(label, is_dup) for label, is_dup, sc, _ in scored if sc >= THRESHOLD_MANUAL]
    true_pos = sum(1 for _, is_dup in candidates if is_dup)
    precision = true_pos / len(candidates)
    # 현 측정: true 7 / 후보 11 = 0.636. 0.55 아래로 떨어지면 회귀.
    assert precision >= 0.55, f"manual-precision regressed: {precision:.3f}"
    # recall은 항상 100% (위 테스트가 보장) — 후보에 true 7건 모두 포함.
    assert true_pos == sum(1 for _, is_dup, _, _ in scored if is_dup)


@pytest.mark.unit
def test_auto_merge_precision_is_perfect() -> None:
    """AUTO 임계 이상(자동 병합)은 전부 true duplicate — precision 100%."""
    auto = [is_dup for _, is_dup, sc, _ in _scored() if sc >= THRESHOLD_AUTO]
    assert auto, "auto-merge 후보가 하나도 없으면 평가셋이 부적절"
    assert all(auto), "auto-merge에 distinct가 섞임(위험)"
