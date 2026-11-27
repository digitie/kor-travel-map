"""ADR-128 — 코스가 계보로 가진 구간만 은퇴 대상이다."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kortravelmap.dagster.assets import _course_segment_ids


def _bundle(payload: dict[str, list[str]]) -> SimpleNamespace:
    return SimpleNamespace(feature=SimpleNamespace(detail=SimpleNamespace(payload=payload)))


@pytest.mark.unit
def test_course_segment_ids_unions_payload_lineage() -> None:
    bundles = [
        _bundle({"segment_source_ids": ["a", "b"]}),
        _bundle({"segment_source_ids": ["b", "c"]}),
        SimpleNamespace(feature=SimpleNamespace(detail=None)),
    ]
    assert _course_segment_ids(bundles) == {"a", "b", "c"}
