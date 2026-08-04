"""H35 concurrent DDL 중단 상태의 revision-exact 판정 행렬."""

from __future__ import annotations

import pytest

from kortravelmap.cli._h35_schema import (
    partial_index_state_allowed,
    partial_invalid_indexes_allowed,
)
from kortravelmap.cli._h35_schema_version import TARGET_SCHEMA

pytestmark = pytest.mark.unit

_PRE = "0063_pipeline_root_id"
_PRICE_OLD = "idx_price_values_feature_product_observed"
_PRICE_NEW = "idx_price_values_feature_observed_identity"
_INTEGRITY_OLD = (
    "idx_violations_status_detected",
    "idx_violations_provider_status_detected",
    "idx_violations_feature_detected",
)
_INTEGRITY_NEW = (
    "idx_violations_status_seen",
    "idx_violations_provider_status_seen",
    "idx_violations_feature_seen",
)
_WEATHER = (
    "idx_weather_values_feature_effective",
    "idx_features_public_weather_coord_5179_gist",
)
_ALL = (_PRICE_OLD, _PRICE_NEW, *_INTEGRITY_OLD, *_INTEGRITY_NEW, *_WEATHER)


def _states(*canonical: str, residue: str | None = None) -> dict[str, tuple[bool, bool]]:
    result = {name: (False, False) for name in _ALL}
    for name in canonical:
        result[name] = (True, True)
    if residue is not None:
        result[residue] = (True, False)
    return result


@pytest.mark.parametrize(
    ("revision", "invalid", "expected"),
    [
        (_PRE, [], True),
        (_PRE, [_PRICE_NEW], True),
        (_PRE, [_INTEGRITY_NEW[0]], False),
        (_PRE, [_PRICE_NEW, _INTEGRITY_NEW[0]], False),
        ("0067_integrity_dedupe_key", [_INTEGRITY_NEW[1]], True),
        ("0067_integrity_dedupe_key", [_INTEGRITY_NEW[0], _INTEGRITY_NEW[1]], False),
        ("0068_integrity_last_seen", [_WEATHER[0]], True),
        ("0068_integrity_last_seen", [_PRICE_NEW], False),
        (TARGET_SCHEMA, [], True),
        (TARGET_SCHEMA, [_WEATHER[0]], False),
    ],
)
def test_invalid_index_allowlist_is_revision_exact(
    revision: str,
    invalid: list[str],
    expected: bool,
) -> None:
    assert partial_invalid_indexes_allowed(revision, invalid) is expected


def test_0063_requires_a_canonical_price_access_path() -> None:
    assert partial_index_state_allowed(_PRE, _states(_PRICE_OLD)) is True
    assert partial_index_state_allowed(_PRE, _states(_PRICE_NEW)) is True
    assert partial_index_state_allowed(_PRE, _states()) is False
    assert partial_index_state_allowed(_PRE, _states(residue=_PRICE_NEW)) is False


def test_0063_rejects_future_revision_material() -> None:
    for unexpected in (*_INTEGRITY_NEW, *_WEATHER):
        assert partial_index_state_allowed(
            _PRE,
            _states(_PRICE_OLD, unexpected),
        ) is False


def test_0067_accepts_only_canonical_integrity_statement_prefixes() -> None:
    base = (_PRICE_NEW, *_INTEGRITY_OLD)
    assert partial_index_state_allowed(
        "0067_integrity_dedupe_key",
        _states(*base),
    ) is True
    for prefix_length in range(1, len(_INTEGRITY_NEW) + 1):
        assert partial_index_state_allowed(
            "0067_integrity_dedupe_key",
            _states(*base, *_INTEGRITY_NEW[:prefix_length]),
        ) is True
    assert partial_index_state_allowed(
        "0067_integrity_dedupe_key",
        _states(*base, _INTEGRITY_NEW[1]),
    ) is False
    assert partial_index_state_allowed(
        "0067_integrity_dedupe_key",
        _states(*base, residue=_INTEGRITY_NEW[1]),
    ) is False
    assert partial_index_state_allowed(
        "0067_integrity_dedupe_key",
        _states(*base, *_INTEGRITY_NEW, _WEATHER[0]),
    ) is False


def test_0068_accepts_only_canonical_weather_statement_prefixes() -> None:
    base = (_PRICE_NEW, *_INTEGRITY_NEW)
    assert partial_index_state_allowed(
        "0068_integrity_last_seen",
        _states(*base),
    ) is True
    assert partial_index_state_allowed(
        "0068_integrity_last_seen",
        _states(*base, _WEATHER[0]),
    ) is True
    assert partial_index_state_allowed(
        "0068_integrity_last_seen",
        _states(*base, *_WEATHER),
    ) is True
    assert partial_index_state_allowed(
        "0068_integrity_last_seen",
        _states(*base, _WEATHER[1]),
    ) is False
    assert partial_index_state_allowed(
        "0068_integrity_last_seen",
        _states(*base, residue=_WEATHER[1]),
    ) is False


def test_post_0069_requires_final_index_shape_without_old_peers() -> None:
    final = (_PRICE_NEW, *_INTEGRITY_NEW, *_WEATHER)
    assert partial_index_state_allowed(
        TARGET_SCHEMA,
        _states(*final),
    ) is True
    for missing in final:
        remaining = tuple(name for name in final if name != missing)
        assert partial_index_state_allowed(
            TARGET_SCHEMA,
            _states(*remaining),
        ) is False
    assert partial_index_state_allowed(
        TARGET_SCHEMA,
        _states(*final, _PRICE_OLD),
    ) is False
    assert partial_index_state_allowed(
        TARGET_SCHEMA,
        _states(*final, _INTEGRITY_OLD[0]),
    ) is False


def test_unknown_revision_is_never_a_resume_state() -> None:
    assert partial_index_state_allowed("unknown", _states()) is False
