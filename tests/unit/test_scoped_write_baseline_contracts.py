"""fixture 효과 전체와 취소 중 전용 container 시작 정리를 검증한다."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from scripts._scoped_write_baseline_pg import (
    _effective_state,
    _start_owned_container,
    feature_id,
)
from scripts.scoped_write_baseline import load_fixture


def _rows() -> list[dict[str, Any]]:
    fixture = load_fixture()
    return [
        {
            "feature_id": feature_id("shared", "left", point),
            "kind": "place",
            "name": point.name,
            "category": "01010100",
            "lon": point.lon,
            "lat": point.lat,
            "marker_icon": "circle",
            "marker_color": "P-01",
            "place_kind": "tourism",
            "row_revision": 100,
        }
        for point in fixture.points
    ]


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("feature_id", "00000000-0000-0000-0000-000000000000"),
        ("kind", "event"),
        ("name", "변조"),
        ("category", "01010200"),
        ("lon", 128.0),
        ("lat", 38.0),
        ("marker_icon", "pin"),
        ("marker_color", "P-02"),
        ("place_kind", "leisure"),
    ],
)
def test_every_written_effective_field_is_checked(field: str, wrong: Any) -> None:
    rows = _rows()
    fixture = load_fixture()
    checked = _effective_state(rows, "shared", fixture)
    assert all("row_revision" not in row for row in checked)
    rows[0][field] = wrong
    with pytest.raises(RuntimeError, match="effective"):
        _effective_state(rows, "shared", fixture)


@pytest.mark.parametrize("cancel_twice", [False, True])
@pytest.mark.parametrize("startup_fails", [False, True])
async def test_cancel_drains_start_before_owner_stops(
    cancel_twice: bool, startup_fails: bool
) -> None:
    entered = threading.Event()
    release = threading.Event()
    events: list[str] = []

    class Container:
        def start(self) -> None:
            events.append("entered")
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test release")
            events.append("start_finished")
            if startup_fails:
                raise RuntimeError("test startup failure")

        def stop(self) -> None:
            events.append("stopped")

    container = Container()

    async def owned() -> None:
        try:
            await _start_owned_container(container)
        finally:
            container.stop()

    task = asyncio.create_task(owned())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        if cancel_twice:
            task.cancel()
            await asyncio.sleep(0)
        assert events == ["entered"]
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert events == ["entered", "start_finished", "stopped"]
