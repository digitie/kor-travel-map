"""KNPS 보호지역의 바다 centroid 역지오 실패가 run 전체를 죽이지 않는다(#1450).

운영 1회 적재(2026-11-06)에서 해상 보호구역 134건이 ``reverse_geocode_failed``로 strict 검증에
걸려 1,516행 전부가 롤백됐다. dataset spec이 ``drop``을 고르면 그 행만 세어 버리고 나머지를
싣는다. 운영자가 ``off``를 골랐으면 그 값이 이긴다 — spec은 strict를 완화할 뿐 조이지 않는다.
"""

from __future__ import annotations

import pytest

from kortravelmap.dagster.assets import _effective_address_validation


@pytest.mark.parametrize(
    ("configured", "dataset_mode", "expected"),
    [
        ("strict", "drop", "drop"),
        (True, "drop", "drop"),
        ("drop", "drop", "drop"),
        ("off", "drop", "off"),
        (False, "drop", False),
        ("strict", "strict", "strict"),
        (True, "strict", True),
        ("off", "strict", "off"),
    ],
)
def test_dataset_mode_only_relaxes_strict(
    configured: bool | str, dataset_mode: str, expected: bool | str
) -> None:
    assert _effective_address_validation(configured, dataset_mode) == expected
