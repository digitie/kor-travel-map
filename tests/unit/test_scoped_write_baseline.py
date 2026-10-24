"""실제 DB 없이 고정 artifact·경계·구간 계산을 검증한다."""

from __future__ import annotations

import json

import pytest

from scripts.scoped_write_baseline import FIXTURE_PATH, interval_overlap, load_fixture, plan


def test_fixed_plan_keeps_global_fence_and_reports_scope() -> None:
    fixture = load_fixture()
    assert fixture.sha256 == load_fixture().sha256
    assert len(fixture.points) == 4
    output = plan(fixture)
    assert output["scenarios"] == ["independent", "shared"]
    assert output["repetitions"] == 3
    assert output["global_fence_retained"] is True
    assert output["operational_access"] is False
    assert "OS page cache" in output["cold"]
    assert "root finalize" in output["excludes"]


@pytest.mark.parametrize(
    ("intervals", "overlap"),
    [([(1, 2), (2, 3)], 0), ([(1, 4), (2, 3)], 1), ([(2, 4), (1, 3)], 1)],
)
def test_overlap_uses_actual_dml_intervals(intervals, overlap) -> None:
    assert interval_overlap(intervals) == overlap


@pytest.mark.parametrize(
    "coordinates", [(True, 37), ("127", 37), (181, 37), (127, 91), (float("nan"), 37)]
)
def test_invalid_coordinates_are_rejected(tmp_path, coordinates) -> None:
    path = tmp_path / "fixture.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "observed_at": "2026-10-24T09:00:00+09:00",
                "points": [{"key": "a", "name": "x", "lon": coordinates[0], "lat": coordinates[1]}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="좌표"):
        load_fixture(path)


def test_duplicate_fixture_key_is_rejected(tmp_path) -> None:
    path = tmp_path / "fixture.json"
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture["points"].append(fixture["points"][0])
    path.write_text(json.dumps(fixture), encoding="utf-8")
    with pytest.raises(ValueError, match="중복"):
        load_fixture(path)
