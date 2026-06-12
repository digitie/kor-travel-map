"""``test_dedup_fp_stats`` — dedup 큐 운영자 결정 기반 FP 통계 (ADR-016 후속).

``dedup_fp_stats``가 ``dedup_review_queue`` status별 카운트에서 confirmed/rejected를
구분해 운영 precision/fp_rate를 계산하는지 검증한다(순수, DB 무관).
"""

from __future__ import annotations

import pytest

from kortravelmap.infra.status_repo import dedup_fp_stats


@pytest.mark.unit
def test_empty_no_resolved() -> None:
    s = dedup_fp_stats({})
    assert s.resolved == 0
    assert s.precision is None
    assert s.fp_rate is None


@pytest.mark.unit
def test_only_pending_no_resolved() -> None:
    s = dedup_fp_stats({"pending": 12})
    assert s.resolved == 0
    assert s.pending == 12
    assert s.precision is None


@pytest.mark.unit
def test_merged_and_rejected() -> None:
    # confirmed = merged 8, false positive = rejected 2.
    s = dedup_fp_stats({"merged": 8, "rejected": 2, "pending": 5})
    assert s.confirmed == 8
    assert s.rejected == 2
    assert s.resolved == 10
    assert s.precision == pytest.approx(0.8)
    assert s.fp_rate == pytest.approx(0.2)
    assert s.pending == 5


@pytest.mark.unit
def test_accepted_counts_as_confirmed() -> None:
    s = dedup_fp_stats({"accepted": 3, "merged": 1, "rejected": 0})
    # accepted + merged = confirmed, rejected 0 → precision 1.0.
    assert s.confirmed == 4
    assert s.resolved == 4
    assert s.precision == pytest.approx(1.0)
    assert s.fp_rate == pytest.approx(0.0)


@pytest.mark.unit
def test_ignored_excluded_from_precision() -> None:
    # ignored는 판단 불가 → resolved에서 제외.
    s = dedup_fp_stats({"ignored": 4, "merged": 1, "rejected": 1})
    assert s.ignored == 4
    assert s.resolved == 2  # merged 1 + rejected 1 (ignored 제외)
    assert s.precision == pytest.approx(0.5)


@pytest.mark.unit
def test_all_rejected_zero_precision() -> None:
    s = dedup_fp_stats({"rejected": 5})
    assert s.resolved == 5
    assert s.precision == pytest.approx(0.0)
    assert s.fp_rate == pytest.approx(1.0)
