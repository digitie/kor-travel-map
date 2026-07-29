"""H25A current-snapshot evidence의 row identity fail-close 회귀."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "h25a_decisive.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("h25a_decisive", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _csv_row(
    item: str,
    feature_id: str | None,
) -> dict[str, object]:
    return {
        "collection_key": "collection",
        "source_item_key": item,
        "source_component_key": "primary",
        "place_name": f"장소 {item}",
        "feature_id": feature_id,
        "csv_file": "input.csv",
        "csv_line": 2,
        "csv_sha256": "a" * 64,
    }


def _db_row(
    item: str,
    feature_id: str | None,
) -> dict[str, object]:
    return {
        "collection_key": "collection",
        "source_item_key": item,
        "source_component_key": "primary",
        "place_name": f"장소 {item}",
        "feature_id": feature_id,
        "status": "included",
        "source_record_key": None,
    }


def test_compare_membership_rows_emits_exact_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    expected = {
        "csv_rows": 2,
        "csv_linked": 1,
        "csv_unresolved": 1,
        "csv_unique_feature_ids": 1,
        "db_rows": 2,
        "db_linked": 2,
        "db_unresolved": 0,
        "csv_unlinked_db_linked": 1,
        "csv_linked_db_unlinked": 0,
        "linked_target_mismatch": 0,
    }
    monkeypatch.setattr(module, "_EXPECTED_COUNTS", expected)

    summary, drift = module.compare_membership_rows(
        [_csv_row("a", "feature-a"), _csv_row("b", None)],
        [_db_row("a", "feature-a"), _db_row("b", "feature-b")],
    )

    assert summary == expected
    assert drift == [
        {
            "collection_key": "collection",
            "source_item_key": "b",
            "source_component_key": "primary",
            "place_name": "장소 b",
            "db_feature_id": "feature-b",
            "db_status": "included",
            "csv_file": "input.csv",
            "csv_line": 2,
            "csv_sha256": "a" * 64,
            "csv_legacy_identity_multiplicity": 1,
            "db_legacy_identity_multiplicity": 1,
        }
    ]


def test_compare_membership_rows_rejects_opposite_direction_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    expected = {
        "csv_rows": 2,
        "csv_linked": 1,
        "csv_unresolved": 1,
        "csv_unique_feature_ids": 1,
        "db_rows": 2,
        "db_linked": 1,
        "db_unresolved": 1,
        "csv_unlinked_db_linked": 0,
        "csv_linked_db_unlinked": 0,
        "linked_target_mismatch": 0,
    }
    monkeypatch.setattr(module, "_EXPECTED_COUNTS", expected)

    with pytest.raises(RuntimeError, match="count invariant"):
        module.compare_membership_rows(
            [_csv_row("a", "feature-a"), _csv_row("b", None)],
            [_db_row("a", None), _db_row("b", "feature-b")],
        )
