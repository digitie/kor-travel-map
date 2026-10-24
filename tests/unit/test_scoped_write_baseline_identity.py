"""정본 UUID claim과 provider f_* 주소를 혼동하지 않는 fixture 계약."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

from scripts._scoped_write_baseline_pg import _bundle, feature_id, record
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


@pytest.mark.parametrize("case", ["independent", "shared"])
@pytest.mark.parametrize("writer", ["left", "right"])
def test_measured_source_is_strictly_newer_and_replay_keeps_clock(case: str, writer: str) -> None:
    fixture = load_fixture()
    key_tie_would_lose = False
    for point in fixture.points:
        seed = record(case, writer, point, fixture, measured=False)
        measured = _bundle(case, writer, point, fixture).source_record
        replay = _bundle(case, writer, point, fixture).source_record
        # 원천 key가 작은 자료도 명시적으로 최신이어야 한다. fetched_at만 바꾸면 안 된다.
        key_tie_would_lose |= measured.source_record_key < seed.source_record_key
        assert measured.imported_at == seed.imported_at + timedelta(seconds=1)
        assert measured.fetched_at == measured.imported_at
        assert (measured.imported_at, measured.source_record_key) > (
            seed.imported_at,
            seed.source_record_key,
        )
        assert replay == measured
    assert key_tie_would_lose
