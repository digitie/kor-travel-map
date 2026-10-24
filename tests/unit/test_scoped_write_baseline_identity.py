"""정본 UUID claim과 provider f_* 주소를 혼동하지 않는 fixture 계약."""

from __future__ import annotations

import re

import pytest

from scripts._scoped_write_baseline_pg import _bundle, feature_id
from scripts.scoped_write_baseline import load_fixture


@pytest.mark.parametrize("case", ["independent", "shared"])
def test_source_aliases_preserve_canonical_claim_axis(case: str) -> None:
    fixture = load_fixture()
    point = fixture.points[0]
    aliases = []
    canonical = []
    for writer in ("left", "right"):
        bundle = _bundle(case, writer, point, fixture)
        alias = bundle.feature.feature_id
        claimed_id = feature_id(case, writer, point)
        assert re.fullmatch(r"f_global_p_[0-9a-f]{16}", alias)
        assert alias != claimed_id
        assert bundle.feature.provider_natural_key == point.key
        assert bundle.feature.detail is not None
        assert bundle.feature.detail.feature_id == alias
        assert bundle.source_link.feature_id == alias
        aliases.append(alias)
        canonical.append(claimed_id)
    assert aliases[0] != aliases[1]
    assert (canonical[0] == canonical[1]) is (case == "shared")
