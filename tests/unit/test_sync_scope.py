"""Canonical provider refresh ``sync_scope`` parser 단위 테스트."""

from __future__ import annotations

import pytest

from kortravelmap.core.sync_scope import (
    DATASET_WIDE_SYNC_SCOPE,
    TARGET_GRIDS_SYNC_SCOPE,
    parse_canonical_sync_scope,
)

pytestmark = pytest.mark.unit


def test_parse_canonical_sync_scope_accepts_fixed_scopes() -> None:
    dataset_wide = parse_canonical_sync_scope(DATASET_WIDE_SYNC_SCOPE)
    target_grids = parse_canonical_sync_scope(TARGET_GRIDS_SYNC_SCOPE)

    assert (dataset_wide.value, dataset_wide.kind, dataset_wide.external_system) == (
        "dataset_wide",
        "dataset_wide",
        None,
    )
    assert (target_grids.value, target_grids.kind, target_grids.external_system) == (
        "target_grids",
        "target_grids",
        None,
    )


def test_parse_canonical_sync_scope_preserves_exact_external_system() -> None:
    parsed = parse_canonical_sync_scope("external_system:tripmate-prod")

    assert parsed.value == "external_system:tripmate-prod"
    assert parsed.kind == "external_system"
    assert parsed.external_system == "tripmate-prod"

    max_name = "x" * 112
    assert parse_canonical_sync_scope(
        f"external_system:{max_name}"
    ).external_system == max_name


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "default",
        "all",
        "target-grids",
        " target_grids",
        "target_grids ",
        "external_system:",
        "external_system: ",
        "external_system:tripmate ",
        f"external_system:{'x' * 113}",
    ],
)
def test_parse_canonical_sync_scope_rejects_blank_alias_and_non_exact_values(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="sync_scope|external_system"):
        parse_canonical_sync_scope(value)
