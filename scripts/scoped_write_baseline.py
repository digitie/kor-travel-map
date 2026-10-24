#!/usr/bin/env python3
"""ADR115의 격리 source/typed-patch/seal 기준선. 외부 DSN·운영 접속은 받지 않는다."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests/data/scoped-write-baseline-v1.json"
MAX_FIXTURE_BYTES = 128 * 1024


@dataclass(frozen=True)
class Point:
    key: str
    name: str
    lon: float
    lat: float


@dataclass(frozen=True)
class Fixture:
    sha256: str
    observed_at: datetime
    points: tuple[Point, ...]


def load_fixture(path: Path = FIXTURE_PATH) -> Fixture:
    with path.open("rb") as handle:
        raw = handle.read(MAX_FIXTURE_BYTES + 1)
    if len(raw) > MAX_FIXTURE_BYTES:
        raise ValueError("fixture는 128KiB 이하여야 합니다")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"version", "observed_at", "points"}:
        raise ValueError("fixture envelope이 잘못되었습니다")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("지원하지 않는 fixture version")
    observed = datetime.fromisoformat(value["observed_at"])
    if observed.utcoffset() is None:
        raise ValueError("fixture 시각에는 timezone이 필요합니다")
    rows = value["points"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError("fixture point 수는 1~128개여야 합니다")
    points = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"key", "name", "lon", "lat"}:
            raise ValueError("fixture point 필드가 잘못되었습니다")
        if not isinstance(row["key"], str) or not row["key"].isascii() or not row["key"]:
            raise ValueError("point key는 비어 있지 않은 ASCII여야 합니다")
        if not isinstance(row["name"], str) or not row["name"].strip():
            raise ValueError("point name이 필요합니다")
        coordinates = []
        for key, bound in (("lon", 180), ("lat", 90)):
            number = row[key]
            if type(number) not in (int, float):
                raise ValueError("좌표는 유한 숫자여야 합니다")
            number = float(number)
            if not math.isfinite(number) or abs(number) > bound:
                raise ValueError("좌표 범위가 잘못되었습니다")
            coordinates.append(number)
        points.append(Point(row["key"], row["name"], *coordinates))
    if len({point.key for point in points}) != len(points):
        raise ValueError("중복 point key")
    return Fixture(hashlib.sha256(raw).hexdigest(), observed, tuple(points))


def interval_overlap(intervals: list[tuple[float, float]]) -> float:
    if len(intervals) != 2 or any(end < start for start, end in intervals):
        raise ValueError("두 writer의 유효한 DML 구간이 필요합니다")
    return max(0.0, min(end for _, end in intervals) - max(start for start, _ in intervals))


def plan(fixture: Fixture) -> dict[str, Any]:
    return {
        "version": 1,
        "fixture_sha256": fixture.sha256,
        "points_per_dataset": len(fixture.points),
        "scenarios": ["independent", "shared"],
        "writers_per_scenario": 2,
        "repetitions": 3,
        "cold": "전용 PG 재시작 후 shared_buffers 첫 실행; OS page cache는 미통제",
        "warm": "같은 artifact의 즉시 replay",
        "measured_path": "global fence → source/typed field patch → causal input seal → commit",
        "excludes": [
            "provider HTTP/Geo",
            "전체 load_bundle identity 경로",
            "root finalize",
            "API/UI",
        ],
        "global_fence_retained": True,
        "operational_access": False,
        "fixture_points": [asdict(point) for point in fixture.points],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(plan(load_fixture()), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
