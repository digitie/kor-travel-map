"""OpenAPI export/profile 필터 테스트 (ADR-045 T-207g)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.admin.app import create_app
from kortravelmap.admin.settings import AdminSettings


def _load_script_module() -> Any:
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "export_openapi.py"
    )
    spec = importlib.util.spec_from_file_location("kor_travel_map_admin_export_openapi", path)
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

    assert user["info"]["title"] == "kor-travel-map-user"
    assert set(user["paths"]) == {
        "/v1/categories",
        "/v1/providers",
        "/v1/providers/{provider}/last-sync",
        "/health",
        "/version",
        "/v1/features/in-bounds",
        "/v1/features/nearby",
        "/v1/features/nearby/by-target",
        "/v1/features/search",
        "/v1/features/{feature_id}",
        "/v1/features/{feature_id}/weather",
        "/v1/features/batch",
        "/v1/public/beaches",
        "/v1/public/beaches/map-markers",
        "/v1/public/beaches/{feature_id}",
        "/v1/public/festivals/monthly",
        "/v1/public/festivals/map-markers",
        "/v1/public/festivals/{feature_id}",
        "/v1/curated-themes",
        "/v1/curated-sources",
        "/v1/curated-features",
        "/v1/curated-features/{curated_feature_id}",
        "/v1/curated-features/{curated_feature_id}/tripmate-copy",
    }
    assert not any(path.startswith("/admin") for path in user["paths"])
    assert not any(path.startswith("/ops") for path in user["paths"])
    assert not any(path.startswith("/debug") for path in user["paths"])

    schemas = user["components"]["schemas"]
    assert "FeatureBatchResponse" in schemas
    assert "BeachPublicView" in schemas
    assert "FestivalPublicView" in schemas
    assert "CuratedFeatureView" in schemas
    assert "TripmateCopySnapshotView" in schemas
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
