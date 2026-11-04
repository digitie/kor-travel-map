"""행사 회차 비교 — 날짜가 증명하는 경우만 ``different``다(#1444 리뷰)."""

from __future__ import annotations

from datetime import date

import pytest

from kortravelmap.core.events import compare_event_occurrences
from kortravelmap.dto import EventDetail


def _event(start: str | None, end: str | None, venue: str | None) -> EventDetail:
    return EventDetail(
        feature_id="f_event",
        starts_on=date.fromisoformat(start) if start else None,
        ends_on=date.fromisoformat(end) if end else None,
        venue_name=venue,
    )


@pytest.mark.parametrize(
    ("right", "expected"),
    [
        # 같은 기간·장소(공백·대소문자 무시)는 같은 회차다.
        (("2026-05-01", "2026-05-03", " 종 묘 "), "same"),
        # 기간이 겹치지 않으면 다른 회차다(매주 열리는 같은 이름 행사).
        (("2026-05-08", "2026-05-08", "종묘"), "different"),
        (("2025-05-01", "2025-05-03", "종묘"), "different"),
        # 시작일이 다른데 한쪽 종료일이 없으면 겹침을 증명할 수 없다.
        (("2026-05-02", None, "종묘"), "different"),
        # 기간이 겹치지만 날짜가 다르다 — 연장·정정일 수 있어 판단을 사람에게 넘긴다.
        (("2026-05-01", "2026-05-04", "종묘"), "unknown"),
        (("2026-05-02", "2026-05-04", "종묘"), "unknown"),
        # 장소 표기만 다르다 — 원천마다 표기가 달라 자동 병합하지 않되 막지도 않는다.
        (("2026-05-01", "2026-05-03", "종묘 일원"), "unknown"),
        # 필수 정보가 비면 같은 회차로 단정하지 않는다.
        ((None, None, "종묘"), "unknown"),
        (("2026-05-01", "2026-05-03", None), "unknown"),
    ],
)
def test_only_dates_prove_a_different_occurrence(
    right: tuple[str | None, str | None, str | None], expected: str,
) -> None:
    left = _event("2026-05-01", "2026-05-03", "종묘")
    other = _event(*right)
    assert compare_event_occurrences(left, other) == expected
    assert compare_event_occurrences(other, left) == expected


def test_non_event_detail_is_unknown() -> None:
    assert compare_event_occurrences(None, _event("2026-05-01", "2026-05-03", "종묘")) == (
        "unknown"
    )
