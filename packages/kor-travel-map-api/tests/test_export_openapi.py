"""OpenAPI export/profile 필터 테스트 (ADR-045 T-207g)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings


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


def _query_parameter_names(spec: dict[str, Any], path: str) -> set[str]:
    parameters = spec["paths"][path]["get"].get("parameters", [])
    return {
        str(parameter["name"])
        for parameter in parameters
        if parameter.get("in") == "query"
    }


@pytest.mark.unit
def test_user_openapi_spec_filters_internal_routes_and_prunes_schemas() -> None:
    module = _load_script_module()
    full = create_app(ApiSettings()).openapi()

    user = module.user_openapi_spec(full)

    assert "visibility" not in _query_parameter_names(full, "/v1/curated-themes")
    assert "visibility" in _query_parameter_names(full, "/v1/admin/curated-themes")
    assert "curation_status" not in _query_parameter_names(full, "/v1/curated-features")
    assert "curation_status" in _query_parameter_names(
        full, "/v1/admin/features/curated"
    )
    public_curated_queries = _query_parameter_names(full, "/v1/curated-features")
    admin_curated_queries = _query_parameter_names(
        full, "/v1/admin/features/curated"
    )
    assert {"theme_slug", "q", "feature_name", "display_title"} <= (
        public_curated_queries
    )
    assert {"theme_id", "source_id", "provider", "dataset_key"}.isdisjoint(
        public_curated_queries
    )
    assert {"theme_id", "source_id", "provider", "dataset_key"} <= (
        admin_curated_queries
    )
    assert _refs(
        full["paths"]["/v1/curated-features"]["get"]["responses"]["200"]
    ) == {"PublicCuratedFeaturesResponse"}
    assert _refs(
        full["paths"]["/v1/admin/features/curated"]["get"]["responses"]["200"]
    ) == {"CuratedFeaturesResponse"}
    full_schemas = full["components"]["schemas"]
    assert "source_record_key" in _schema_properties(full, "CuratedFeatureView")
    assert "PublicCuratedFeatureView" in full_schemas
    assert "CuratedFeatureView" in full_schemas

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
        "/v1/features/{feature_id}/price",
        "/v1/features/{feature_id}/weather",
        "/v1/features/{feature_id}/weather/forecast",
        "/v1/features/weather/forecast",
        "/v1/features/weather/alerts",
        "/v1/features/batch",
        "/v1/public/beaches",
        "/v1/public/beaches/map-markers",
        "/v1/public/beaches/{feature_id}",
        "/v1/public/festivals/monthly",
        "/v1/public/festivals/map-markers",
        "/v1/public/festivals/{feature_id}",
        "/v1/curated-features",
        "/v1/curated-features/{curated_feature_id}",
        "/v1/curations",
        "/v1/curations/collections",
        "/v1/curations/collections/{collection_id}",
        "/v1/curations/features/{feature_id}",
    }
    assert not any(path.startswith("/admin") for path in user["paths"])
    assert not any(path.startswith("/ops") for path in user["paths"])
    assert not any(path.startswith("/debug") for path in user["paths"])
    assert set(user["components"]["securitySchemes"]) == {
        "PublicApiKey",
        "ServiceToken",
    }
    for path in {
        "/v1/curated-features",
        "/v1/curated-features/{curated_feature_id}",
    }:
        assert user["paths"][path]["get"]["security"] == [
            {"PublicApiKey": []},
            {"ServiceToken": []},
        ]

    schemas = user["components"]["schemas"]
    assert "FeatureBatchResponse" in schemas
    assert "BeachPublicView" in schemas
    assert "FestivalPublicView" in schemas
    assert "PublicCuratedFeatureView" in schemas
    assert "CuratedFeatureView" not in schemas
    assert "FeatureCurationGroupsResponse" in schemas
    assert "CurationCollectionResponse" in schemas
    assert "FeatureCurationGroupResponse" in schemas
    assert "CuratedFeatureDetailSnapshotView" not in schemas
    assert "OpsMetricsResponse" not in schemas
    assert "AdminFeatureListResponse" not in schemas
    # T-VN-05: raw observation lineage schema/route는 user-facing subset에서 제외.
    assert "FeatureObservationHistoryResponse" not in schemas
    assert "FeatureObservationView" not in schemas
    assert "FeatureSourcesResponse" not in schemas
    assert "FeatureSourcesData" not in schemas
    # T-VN-05R: 공개 schema는 feature_kind 판별 union이고 각 variant/nested DTO가
    # extra를 닫는다. admin/source identity와 raw lineage는 어느 variant에도 없다.
    public_union = schemas["PublicCuratedFeatureView"]
    discriminator = public_union["discriminator"]
    variant_names = {
        "place": "PublicCuratedPlaceFeatureView",
        "event": "PublicCuratedEventFeatureView",
        "notice": "PublicCuratedNoticeFeatureView",
        "area": "PublicCuratedAreaFeatureView",
        "route": "PublicCuratedRouteFeatureView",
        "price": "PublicCuratedPriceFeatureView",
        "weather": "PublicCuratedWeatherFeatureView",
    }
    assert discriminator["propertyName"] == "feature_kind"
    assert discriminator["mapping"] == {
        kind: f"#/components/schemas/{name}" for kind, name in variant_names.items()
    }
    assert _refs(public_union["oneOf"]) == set(variant_names.values())

    internal_fields = {
        "theme_id",
        "source_id",
        "provider",
        "dataset_key",
        "source_record_key",
        "selection_origin",
        "selected_by",
        "selected_at",
        "rejected_by",
        "rejected_at",
        "rejection_reason",
        "metadata",
        "created_at",
        "archived_at",
    }
    common_public_fields = {
        "curated_feature_id",
        "theme_slug",
        "feature_id",
        "detail",
        "source_name",
        "content_version",
        "updated_at",
    }
    for variant_name in variant_names.values():
        assert schemas[variant_name]["additionalProperties"] is False
        properties = _schema_properties(user, variant_name)
        assert internal_fields.isdisjoint(properties)
        assert common_public_fields <= properties

    strict_nested_schemas = {
        "PublicCuratedAddress",
        "PublicCuratedOpeningTime",
        "PublicCuratedOpeningPeriod",
        "PublicCuratedSpecialOpeningDay",
        "PublicCuratedOpeningHours",
        "PublicCuratedReviewLinks",
        "PublicCuratedPlaceFacilityInfo",
        "PublicCuratedPlaceDetail",
        "PublicCuratedEventDetail",
        "PublicCuratedNoticeDetail",
        "PublicCuratedAreaDetail",
        "PublicCuratedRouteDetail",
    }
    for schema_name in strict_nested_schemas:
        assert schemas[schema_name]["additionalProperties"] is False
    assert {
        "youtube_video_id",
        "youtube_video_url",
        "youtube_video_title",
        "youtube_channel_id",
        "youtube_channel_title",
        "youtube_playlist_id",
        "youtube_playlist_title",
        "youtube_source_type",
        "youtube_source_value",
        "youtube_source_title",
        "youtube_source_search_query",
        "youtube_corrected_search_query",
        "timestamp_start",
        "timestamp_end",
        "transcript_excerpt",
        "gemini_url_evidence",
        "confidence_score",
        "source_record_key",
    }.isdisjoint(_schema_properties(user, "PublicCuratedPlaceFacilityInfo"))
    assert {
        "bjd_code",
        "admin_dong_code",
        "road_name_code",
        "road_address_management_no",
    }.isdisjoint(_schema_properties(user, "PublicCuratedAddress"))
    assert _refs(user["paths"]) <= set(schemas)
    assert {
        "coord_5179_srid",
        "parent_feature_id",
        "sibling_group_id",
        # T-VN-05: raw observation lineage는 공개 detail에 없다.
        "observations",
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
    full = create_app(ApiSettings()).openapi()

    for path, methods in module.USER_OPERATIONS.items():
        assert not path.startswith("/admin")
        assert path in full["paths"]
        path_item = full["paths"][path]
        assert methods <= {
            key for key in path_item if key in module.HTTP_METHODS
        }


@pytest.mark.unit
def test_openapi_declares_rfc7807_problem_json_error_responses() -> None:
    """T-452 — 오류 media type 통일과 명시적 typed problem schema 보존."""
    module = _load_script_module()
    spec = create_app(ApiSettings()).openapi()
    schemas = spec["components"]["schemas"]

    assert "ProblemDetail" in schemas
    assert "ProblemDetailError" in schemas
    # FastAPI 자동 검증 schema는 problem+json으로 대체되어 orphan 제거된다.
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas

    problem_ref = {"$ref": "#/components/schemas/ProblemDetail"}
    error_responses_seen = 0
    for path_item in spec["paths"].values():
        for method, operation in path_item.items():
            if method not in module.HTTP_METHODS:
                continue
            responses = operation["responses"]
            default_schema = responses["default"]["content"][
                "application/problem+json"
            ]["schema"]
            assert default_schema == problem_ref
            for code, response in responses.items():
                if code.isdigit() and int(code) >= 400:
                    schema = response["content"]["application/problem+json"]["schema"]
                    ref = schema.get("$ref") if isinstance(schema, dict) else None
                    assert ref is not None
                    assert ref.rsplit("/", 1)[-1] in schemas
                    error_responses_seen += 1
    assert error_responses_seen > 0

    policy_conflict = spec["paths"]["/v1/ops/datasets/refresh-policy"]["put"][
        "responses"
    ]["409"]["content"]["application/problem+json"]["schema"]
    assert policy_conflict == {
        "$ref": "#/components/schemas/ProviderRefreshPolicyConflictProblem"
    }


@pytest.mark.unit
def test_problem_augmenter_does_not_preserve_non_problem_error_ref() -> None:
    """오류 response의 임의 DTO ref를 typed problem으로 오인하지 않는다."""
    from kortravelmap.api.app import _augment_problem_responses

    spec = {
        "components": {
            "schemas": {
                "NotAProblem": {
                    "type": "object",
                    "required": ["data", "meta"],
                    "properties": {},
                }
            }
        },
        "paths": {
            "/regression": {
                "get": {
                    "responses": {
                        "409": {
                            "description": "잘못 지정된 성공 DTO",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/NotAProblem"
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }

    _augment_problem_responses(spec)

    schema = spec["paths"]["/regression"]["get"]["responses"]["409"]["content"][
        "application/problem+json"
    ]["schema"]
    assert schema == {"$ref": "#/components/schemas/ProblemDetail"}
