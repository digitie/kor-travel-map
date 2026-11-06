"""KNPS 보호지역의 바다 centroid 역지오 실패가 run 전체를 죽이지 않는다(#1450).

운영 1회 적재(2026-11-06)에서 해상 보호구역 134건이 ``reverse_geocode_failed``로 strict 검증에
걸려 1,516행 전부가 롤백됐다. dataset spec이 ``drop``을 고르면 그 행만 세어 버리고 나머지를
싣는다. 운영자가 ``off``를 골랐으면 그 값이 이긴다 — spec은 strict를 완화할 뿐 조이지 않는다.
"""

from __future__ import annotations

import pytest
from dagster import Failure
from kortravelmap.dto.geo_dataset import GeoApplied
from kortravelmap.geocoding import REVERSE_RESULT_EMPTY_KEY, GeoCallStats

from kortravelmap.dagster.assets import (
    _dataset_empty_reverse_ratio,
    _effective_address_validation,
)
from kortravelmap.dagster.etl import _raise_if_empty_answers_exceeded


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


def _stats(*, calls: int, empty: int) -> GeoCallStats:
    stats = GeoCallStats()
    stats.calls["reverse"] = calls
    stats.empty[REVERSE_RESULT_EMPTY_KEY] = empty
    return stats


def test_drop_dataset_uses_the_loss_bound_for_the_empty_answer_guard() -> None:
    """빈 답 가드(5%)가 drop dataset을 다시 죽이지 않는다 — 실측 450건 중 49건(10.9%).

    drop dataset에서 빈 답 행은 곧 버린 행이고, 그 수는 소실 하한(50%)이 이미 센다. 같은
    사건을 더 낮은 문턱으로 두 번 세면 drop이 의미를 잃는다. 문턱은 dataset 정책에서만
    완화된다 — 운영자가 전역으로 drop을 골라도 다른 dataset의 5%는 그대로다.
    """
    reverse = GeoApplied(reverse=True, geocode=False)
    ratio = _dataset_empty_reverse_ratio("drop")
    assert ratio == 0.5
    assert _dataset_empty_reverse_ratio("strict") is None
    _raise_if_empty_answers_exceeded(
        reverse, _stats(calls=450, empty=49), dataset_key="knps_protected_areas", ratio=ratio
    )
    with pytest.raises(Failure):
        _raise_if_empty_answers_exceeded(
            reverse, _stats(calls=450, empty=49), dataset_key="knps_protected_areas"
        )
    with pytest.raises(Failure):
        _raise_if_empty_answers_exceeded(
            reverse, _stats(calls=450, empty=300), dataset_key="knps_protected_areas", ratio=ratio
        )
