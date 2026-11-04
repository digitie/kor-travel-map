"""행사 기간·장소의 필수 정보와 회차 비교 규칙."""

from __future__ import annotations

from typing import Literal

from kortravelmap.dto import EventDetail


def has_required_event_details(detail: object) -> bool:
    """수집 시각이나 행정구역으로 행사 기간·장소를 추정하지 않는다."""
    return (
        isinstance(detail, EventDetail)
        and detail.starts_on is not None
        and detail.ends_on is not None
        and bool(detail.venue_name and detail.venue_name.strip())
    )


def compare_event_occurrences(
    left: object, right: object,
) -> Literal["same", "different", "unknown"]:
    """행사 기간·장소의 일치 근거가 부족하면 자동으로 같은 회차로 판단하지 않는다.

    ``different``는 **날짜가 증명할 때만**이다 — 기간이 겹치지 않거나, 시작일이 다른데
    겹침을 증명할 종료일이 없을 때. 겹치는 기간의 날짜 차이(연장·정정)와 장소 표기
    차이는 원천마다 흔하므로 ``unknown``(사람 검토)으로 둔다. ``different``는 dedup
    후보·관리자 병합·KHA fallback 적재를 모두 막기 때문이다(#1444 리뷰).
    """
    if not isinstance(left, EventDetail) or not isinstance(right, EventDetail):
        return "unknown"
    if (
        left.ends_on is not None and right.starts_on is not None
        and left.ends_on < right.starts_on
    ) or (
        right.ends_on is not None and left.starts_on is not None
        and right.ends_on < left.starts_on
    ):
        return "different"
    if (
        left.starts_on is not None and right.starts_on is not None
        and left.starts_on != right.starts_on
        and (left.ends_on is None or right.ends_on is None)
    ):
        return "different"
    venues = ["".join((d.venue_name or "").split()).casefold() for d in (left, right)]
    if (
        left.starts_on != right.starts_on
        or left.ends_on != right.ends_on
        or (all(venues) and venues[0] != venues[1])
    ):
        return "unknown"
    if has_required_event_details(left) and has_required_event_details(right):
        return "same"
    return "unknown"
