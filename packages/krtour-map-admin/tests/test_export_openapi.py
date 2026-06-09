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


def _schema_properties(spec: dict[str, Any], name: str) -> set[str]:
    schema = spec["components"]["schemas"][name]
    properties = schema.get("properties", {})
    assert isinstance(properties, dict)
    return set(properties)


@pytest.mark.unit
def test_user_openapi_spec_filters_internal_routes_and_prunes_schemas() -> None:
    module = _load_script_module()
    full = create_app(AdminSettings()).openapi()

    user = module.user_openapi_spec(full)

    assert user["info"]["title"] == "krtour-map-user"
    assert set(user["paths"]) == {
        "/categories",
        "/providers/{provider}/last-sync",
        "/health",
        "/version",
        "/features/in-bounds",
        "/features/nearby",
        "/features/nearby/by-target",
        "/features/search",
        "/features/{feature_id}",
        "/features/{feature_id}/weather",
        "/features/batch",
    }
    assert not any(path.startswith("/admin") for path in user["paths"])
    assert not any(path.startswith("/ops") for path in user["paths"])
    assert not any(path.startswith("/debug") for path in user["paths"])

    schemas = user["components"]["schemas"]
    assert "FeatureBatchResponse" in schemas
    assert "OpsMetricsResponse" not in schemas
    assert "AdminFeatureListResponse" not in schemas
    assert _refs(user["paths"]) <= set(schemas)
    assert {
        "coord_5179_srid",
        "parent_feature_id",
        "sibling_group_id",
    }.isdisjoint(_schema_properties(user, "FeatureDetailResponse"))
    assert {
        "target_id",
        "update_enabled",
        "refresh_policy",
        "next_eligible_refresh_at",
    }.isdisjoint(_schema_properties(user, "NearbyTargetSummary"))
    assert {
        "primary_provider",
        "primary_dataset_key",
    }.isdisjoint(_schema_properties(user, "NearbyFeatureSummary"))


@pytest.mark.unit
def test_user_operations_are_present_in_full_openapi() -> None:
    module = _load_script_module()
    full = create_app(AdminSettings()).openapi()

    for path, methods in module.USER_OPERATIONS.items():
        assert not path.startswith("/admin")
        assert path in full["paths"]
        path_item = full["paths"][path]
        assert methods <= {
            key for key in path_item if key in module.HTTP_METHODS
        }
