"""T-VN-M02 provenance reader와 hard-purge fence의 static contract."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _ROOT / "alembic" / "versions" / "0227_tvn_m02_manual_feature_provenance.py"


def test_m02_migration_is_forward_only_and_closed_to_manual_admin_reader() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0227_m02_feature_provenance"' in source
    assert 'down_revision: str | Sequence[str] | None = "0226_m01_manual_feature_create"' in source
    assert "SECURITY DEFINER" in source
    assert "feature.read_admin_manual_feature_provenance(uuid)" in source
    assert "TO ktm_manual_feature_admin_executor" in source
    assert "ktm_feature_dagster_runtime" in source
    assert "raise RuntimeError(\"0227_m02_feature_provenance is forward-only\")" in source


def test_m02_reader_is_current_feature_driven_and_purge_fence_is_named() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")

    assert "FROM feature.features AS core" in source
    assert "LEFT JOIN feature.manual_feature_identity_claims AS claim" in source
    assert "WHERE core.feature_uuid = p_feature_uuid" in source
    assert "CREATE TRIGGER trg_features_manual_feature_hard_purge_fence" in source
    assert "BEFORE DELETE ON feature.features" in source
    assert "ck_manual_feature_purge_not_ready" in source
