"""손상된 계측 구간을 정상적인 DML overlap=0으로 해석하지 않는다."""

from __future__ import annotations

from typing import Any

import pytest

from scripts.scoped_write_baseline import interval_overlap


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), True, "1"])
@pytest.mark.parametrize("position", [0, 1])
def test_non_finite_or_non_numeric_bound_fails(invalid: Any, position: int) -> None:
    interval = [1.0, 2.0]
    interval[position] = invalid
    with pytest.raises(ValueError, match="유효한 DML"):
        interval_overlap([(interval[0], interval[1]), (1.0, 2.0)])
