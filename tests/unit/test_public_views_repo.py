"""``public_views_repo`` 단위 테스트 — DB 없이 row mapping/cursor 검증."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from krtour.map.infra import public_views_repo

pytestmark = pytest.mark.unit

_KST = timezone(timedelta(hours=9))
_UPDATED = datetime(2026, 6, 12, 9, 0, tzinfo=_KST)


class _FakeMappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeSession:
    def __init__(self, *row_sets: list[dict[str, Any]]) -> None:
        self._row_sets = list(row_sets)
        self.calls: list[dict[str, Any]] = []

    async def execute(self, _sql: Any, params: dict[str, Any]) -> _FakeResult:
        self.calls.append(params)
        return _FakeResult(self._row_sets.pop(0))


def _beach_mapping(
    feature_id: str = "f_beach_1",
    *,
    updated_at: datetime = _UPDATED,
) -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "display_name": "광안리 해수욕장",
        "lon": 129.118,
        "lat": 35.155,
        "sido_code": "26",
        "sigungu_code": "26110",
        "legal_dong_code": "2611010100",
        "address": {"road": "부산 광안해변로", "legal": "부산 수영구 광안동"},
        "detail": {"place_kind": "beach", "facility_info": {"beach_kind": "일반"}},
        "urls": {"homepage": "https://example.test/beach"},
        "source_raw_data": {"image_url": "https://example.test/beach.jpg"},
        "marker_icon": "beach",
        "marker_color": "P-07",
        "source_providers": ["python-khoa-api"],
        "updated_at": updated_at,
    }


def _festival_mapping(
    feature_id: str = "f_festival_1",
    *,
    updated_at: datetime = _UPDATED,
) -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "festival_name": "봄꽃 축제",
        "lon": 126.9239,
        "lat": 37.5263,
        "sido_code": "11",
        "sigungu_code": "11560",
        "legal_dong_code": "1156010100",
        "address": {"road": "서울 여의공원로", "legal": "서울 영등포구"},
        "detail": {
            "event_kind": "festival",
            "starts_on": "2026-04-25",
            "ends_on": "2026-05-03",
        },
        "urls": {"homepage": "https://example.test/festival"},
        "source_raw_data": {"fstvl_co": "축제 상세"},
        "marker_icon": "star",
        "marker_color": "P-11",
        "source_providers": ["data.go.kr-standard"],
        "updated_at": updated_at,
    }


def _marker_mapping(feature_id: str = "f_marker_1") -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "name": "마커",
        "lon": 127.0,
        "lat": 37.5,
        "sigungu_code": "11110",
    }


async def test_list_public_beaches_builds_and_reads_cursor() -> None:
    first_session = _FakeSession(
        [
            _beach_mapping("f_beach_2", updated_at=_UPDATED + timedelta(seconds=1)),
            _beach_mapping("f_beach_1", updated_at=_UPDATED),
        ]
    )

    page = await public_views_repo.list_public_beaches(
        first_session,
        sido_code="26",
        q="광안리",
        page_size=1,
    )

    assert [item.feature_id for item in page.items] == ["f_beach_2"]
    assert page.next_cursor is not None
    assert first_session.calls[0]["q_pattern"] == "%광안리%"
    assert first_session.calls[0]["limit"] == 2

    second_session = _FakeSession([])
    await public_views_repo.list_public_beaches(
        second_session,
        page_size=1,
        cursor=page.next_cursor,
    )
    assert second_session.calls[0]["cursor_feature_id"] == "f_beach_2"
    assert second_session.calls[0]["cursor_updated_at"] == _UPDATED + timedelta(seconds=1)


async def test_public_beach_detail_and_markers() -> None:
    session = _FakeSession([_beach_mapping()], [_marker_mapping()])

    beach = await public_views_repo.get_public_beach(session, feature_id="f_beach_1")
    markers = await public_views_repo.list_public_beach_markers(
        session,
        min_lon=126.0,
        min_lat=37.0,
        max_lon=128.0,
        max_lat=38.0,
        max_items=5,
    )

    assert beach is not None
    assert beach.source_raw_data["image_url"] == "https://example.test/beach.jpg"
    assert markers[0].feature_id == "f_marker_1"
    assert session.calls[1]["bbox_enabled"] is True
    assert session.calls[1]["limit"] == 5


async def test_public_festivals_monthly_maps_months_and_cursor() -> None:
    session = _FakeSession(
        [_festival_mapping("f_festival_1"), _festival_mapping("f_festival_2")],
        [{"year": 2026, "month": 4, "count": 1}, {"year": 2026, "month": 5, "count": 2}],
    )

    page = await public_views_repo.list_public_festivals_monthly(
        session,
        month_start=date(2026, 5, 1),
        month_end=date(2026, 5, 31),
        page_size=1,
        include_months=True,
    )

    assert [item.feature_id for item in page.items] == ["f_festival_1"]
    assert page.next_cursor is not None
    assert [(month.year, month.month, month.count) for month in page.months] == [
        (2026, 4, 1),
        (2026, 5, 2),
    ]
    assert session.calls[0]["limit"] == 2


async def test_public_festival_detail_markers_and_invalid_inputs() -> None:
    session = _FakeSession([_festival_mapping()], [_marker_mapping("f_festival_marker")])

    festival = await public_views_repo.get_public_festival(
        session,
        feature_id="f_festival_1",
    )
    markers = await public_views_repo.list_public_festival_markers(
        session,
        month_start=date(2026, 5, 1),
        month_end=date(2026, 5, 31),
        max_items=3,
    )

    assert festival is not None
    assert festival.source_providers == ("data.go.kr-standard",)
    assert markers[0].feature_id == "f_festival_marker"
    assert session.calls[1]["bbox_enabled"] is False

    with pytest.raises(ValueError, match="invalid public view cursor"):
        await public_views_repo.list_public_beaches(session, cursor="not-base64")

    with pytest.raises(ValueError, match="bbox min"):
        await public_views_repo.list_public_beach_markers(
            session,
            min_lon=128.0,
            min_lat=37.0,
            max_lon=127.0,
            max_lat=38.0,
        )
