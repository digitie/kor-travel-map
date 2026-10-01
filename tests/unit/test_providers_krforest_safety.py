"""산림청 산사태 예보 notice 변환 테스트.

산악기상·산불위험(weather kind) 변환은 ADR-105로 제거했다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.providers.krforest_safety import (
    LANDSLIDE_FORECAST_DATASET_KEY,
    landslide_active_lineage_keys,
    landslide_forecast_issues_to_bundles,
)

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class _LandslideIssue:
    issue_kind_code: str | None
    issue_kind_name: str | None
    issuing_institution: str | None
    status: str | None
    issued_at: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)


def _now(hour: int = 12) -> datetime:
    return datetime(2026, 8, 20, hour, 0, tzinfo=KST)


@pytest.mark.unit
def test_landslide_release_is_same_lineage_but_not_active() -> None:
    active = _LandslideIssue(
        issue_kind_code="1",
        issue_kind_name="산사태주의보",
        issuing_institution="강원특별자치도",
        status="발령",
        issued_at=_now(8),
    )
    released = _LandslideIssue(
        issue_kind_code="1",
        issue_kind_name="산사태주의보",
        issuing_institution="강원특별자치도",
        status="해제",
        issued_at=_now(8),
    )
    bundles = landslide_forecast_issues_to_bundles(
        [active, released], fetched_at=_now()
    )
    assert len(bundles) == 1
    assert bundles[0].source_record.dataset_key == LANDSLIDE_FORECAST_DATASET_KEY
    assert bundles[0].feature.detail is not None
    assert bundles[0].feature.detail.valid_end_time == _now()  # type: ignore[union-attr]
    assert not landslide_active_lineage_keys([released])


@pytest.mark.unit
def test_landslide_unknown_status_is_not_active_and_distinct_issue_times_split() -> None:
    items = [
        _LandslideIssue(
            issue_kind_code="1",
            issue_kind_name="산사태주의보",
            issuing_institution="강원특별자치도",
            status=None,
            issued_at=_now(8),
        ),
        _LandslideIssue(
            issue_kind_code="1",
            issue_kind_name="산사태주의보",
            issuing_institution="강원특별자치도",
            status="발령",
            issued_at=_now(10),
        ),
    ]
    bundles = landslide_forecast_issues_to_bundles(items, fetched_at=_now())
    assert len(bundles) == 2
    assert not landslide_active_lineage_keys(items[:1])
