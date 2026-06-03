"""OpenAPI export/profile 필터 테스트 (ADR-045 T-207g)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from krtour.map_admin.app import create_app
from krtour.map_admin.settings import AdminSettings


def _load_script_module() -> Any:
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "export_openapi.py"
    )
    spec = importlib.util.spec_from_file_location("krtour_map_admin_export_openapi", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _refs(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for child in value.values():
            found.update(_refs(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_refs(child))
    return found


@pytest.mark.unit
def test_user_openapi_spec_filters_internal_routes_and_prunes_schemas() -> None:
    module = _load_script_module()
    full = create_app(AdminSettings()).openapi()

    user = module.user_openapi_spec(full)

    assert user["info"]["title"] == "krtour-map-user"
    assert set(user["paths"]) == {
        "/admin/feature-update-requests",
        "/admin/feature-update-requests/{request_id}",
        "/features/in-bounds",
        "/features/nearby/by-target",
        "/features/search",
        "/features/{feature_id}",
        "/tripmate/features/batch",
    }
    assert set(user["paths"]["/admin/feature-update-requests"]) >= {"post"}
    assert "get" not in user["paths"]["/admin/feature-update-requests"]
    assert not any(path.startswith("/ops") for path in user["paths"])
    assert not any(path.startswith("/debug") for path in user["paths"])
    assert "/admin/features" not in user["paths"]

    schemas = user["components"]["schemas"]
    assert "FeatureBatchResponse" in schemas
    assert "OpsMetricsResponse" not in schemas
    assert "AdminFeatureListResponse" not in schemas
    assert _refs(user["paths"]) <= set(schemas)

