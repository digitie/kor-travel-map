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
    """행사 기간·장소의 일치 근거가 부족하면 자동으로 같은 회차로 판단하지 않는다."""
    if not isinstance(left, EventDetail) or not isinstance(right, EventDetail):
        return "unknown"
    for a, b in ((left.starts_on, right.starts_on), (left.ends_on, right.ends_on)):
        if a is not None and b is not None and a != b:
            return "different"
    if (
        left.ends_on is not None and right.starts_on is not None
        and left.ends_on < right.starts_on
    ) or (
        right.ends_on is not None and left.starts_on is not None
        and right.ends_on < left.starts_on
    ):
        return "different"
    venues = ["".join((d.venue_name or "").split()).casefold() for d in (left, right)]
    if all(venues) and venues[0] != venues[1]:
        return "different"
    if has_required_event_details(left) and has_required_event_details(right):
        return "same"
    return "unknown"
