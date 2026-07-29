"""OpenAPI export/profile 필터 테스트 (ADR-045 T-207g)."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.api.app import create_app
from kortravelmap.api.route_policy import RoutePolicy, build_route_policy_matrix
from kortravelmap.api.settings import ApiSettings


def _load_script_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "scripts" / "export_openapi.py"
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
    return {str(parameter["name"]) for parameter in parameters if parameter.get("in") == "query"}


@pytest.mark.unit
def test_user_openapi_spec_filters_internal_routes_and_prunes_schemas() -> None:
    module = _load_script_module()
    app = create_app(ApiSettings())
    full = app.openapi()

    user = module.user_openapi_spec(full, app=app)

    assert "visibility" not in _query_parameter_names(full, "/v1/curated-themes")
    assert "visibility" in _query_parameter_names(full, "/v1/admin/curated-themes")
    assert "curation_status" not in _query_parameter_names(full, "/v1/curated-features")
    assert "curation_status" in _query_parameter_names(full, "/v1/admin/features/curated")
    public_curated_queries = _query_parameter_names(full, "/v1/curated-features")
    admin_curated_queries = _query_parameter_names(full, "/v1/admin/features/curated")
    assert {"theme_slug", "q", "feature_name", "display_title"} <= (public_curated_queries)
    assert {"theme_id", "source_id", "provider", "dataset_key"}.isdisjoint(public_curated_queries)
    assert {"theme_id", "source_id", "provider", "dataset_key"} <= (admin_curated_queries)
    assert _refs(full["paths"]["/v1/curated-features"]["get"]["responses"]["200"]) == {
        "PublicCuratedFeaturesResponse"
    }
    assert _refs(full["paths"]["/v1/admin/features/curated"]["get"]["responses"]["200"]) == {
        "CuratedFeaturesResponse"
    }
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
        "/v1/features",
        "/v1/features/in-bounds",
        "/v1/features/nearby",
        "/v1/features/nearby/by-target",
        "/v1/features/search",
        "/v1/features/{feature_id}",
        "/v1/features/{feature_id}/contained-features",
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
        "/v1/curated-sources",
        "/v1/curated-themes",
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
    for row in build_route_policy_matrix(app):
        if not row.include_in_schema or row.policy is not RoutePolicy.PUBLIC_KEYED:
            continue
        for method in row.methods:
            assert user["paths"][row.schema_path][method.lower()]["security"] == [
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
    assert "PublicCurationItemView" in schemas
    assert "PublicCurationCollectionView" in schemas
    assert "AdminCurationItemView" not in schemas
    assert "AdminWeatherAlertHistoryItem" not in schemas
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
    assert {
        "source_record_key",
        "metadata",
    }.isdisjoint(_schema_properties(user, "PublicCurationItemView"))
    assert "metadata" not in _schema_properties(user, "PublicCurationCollectionView")
    assert "source_record_key" not in _schema_properties(user, "PublicWeatherValueItem")
    assert {
        "source_record_key",
        "payload",
        "fetched_at",
        "imported_at",
        "last_seen_at",
    }.isdisjoint(_schema_properties(user, "PublicWeatherAlertHistoryItem"))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "schemas", "expected"),
    [
        (
            "/v1/features/weather/alerts",
            {
                "Root": {
                    "type": "object",
                    "properties": {"source_record_key": {"type": "string"}},
                }
            },
            "source_record_key",
        ),
        (
            "/v1/features/weather/forecast",
            {
                "Root": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/Branch"},
                },
                "Branch": {
                    "oneOf": [
                        {
                            "allOf": [
                                {"$ref": "#/components/schemas/Cycle"},
                                {
                                    "type": "object",
                                    "properties": {"payload": {"type": "object"}},
                                },
                            ]
                        }
                    ]
                },
                "Cycle": {
                    "anyOf": [
                        {"$ref": "#/components/schemas/Branch"},
                        {"type": "null"},
                    ]
                },
            },
            "payload",
        ),
        (
            "/v1/curations",
            {
                "Root": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "metadata": {
                                        "type": "object",
                                        "additionalProperties": True,
                                    }
                                },
                            },
                        }
                    },
                }
            },
            "metadata",
        ),
    ],
)
def test_user_response_schema_gate_rejects_recursive_raw_fields(
    path: str,
    schemas: dict[str, Any],
    expected: str,
) -> None:
    module = _load_script_module()
    spec = {
        "components": {"schemas": schemas},
        "paths": {
            path: {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Root"}
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    with pytest.raises(ValueError, match=expected):
        module._validate_user_response_schemas(spec)


@pytest.mark.unit
def test_route_policy_full_and_user_operations_match_bidirectionally() -> None:
    module = _load_script_module()
    app = create_app(ApiSettings())
    full = app.openapi()
    user = module.user_openapi_spec(full, app=app)

    route_operations = {
        (row.schema_path, method.lower())
        for row in build_route_policy_matrix(app)
        if row.include_in_schema and not row.is_websocket
        for method in row.methods
        if method.lower() in module.HTTP_METHODS
    }
    full_operations = module._openapi_operations(full)
    expected_user_operations = {
        (row.schema_path, method.lower())
        for row in build_route_policy_matrix(app)
        if row.include_in_schema
        and not row.is_websocket
        and row.policy in module.USER_ROUTE_POLICIES
        for method in row.methods
        if method.lower() in module.HTTP_METHODS
    }

    assert full_operations == route_operations
    assert module._openapi_operations(user) == expected_user_operations


@pytest.mark.unit
def test_user_openapi_rejects_route_method_drift() -> None:
    module = _load_script_module()
    app = create_app(ApiSettings())
    full = copy.deepcopy(app.openapi())
    del full["paths"]["/v1/features"]["get"]

    with pytest.raises(ValueError, match="route/OpenAPI operation drift"):
        module.user_openapi_spec(full, app=app)


@pytest.mark.unit
def test_public_security_matches_route_policy_in_full_and_user_specs() -> None:
    module = _load_script_module()
    app = create_app(ApiSettings())
    full = app.openapi()
    user = module.user_openapi_spec(full, app=app)
    policies = {
        row.schema_path: row.policy
        for row in build_route_policy_matrix(app)
        if row.include_in_schema and not row.is_websocket
    }
    expected_security = {
        RoutePolicy.PUBLIC_UNAUTHENTICATED: [],
        RoutePolicy.PUBLIC_KEYED: [
            {"PublicApiKey": []},
            {"ServiceToken": []},
        ],
        RoutePolicy.SERVICE: [{"ServiceToken": []}],
    }

    for spec in (full, user):
        for path, method in module._openapi_operations(spec):
            policy = policies[path]
            operation = spec["paths"][path][method]
            if policy in expected_security:
                assert operation.get("security", []) == expected_security[policy], (
                    path,
                    method,
                    policy,
                )
            if {"PublicApiKey": []} in operation.get("security", []):
                assert policy is RoutePolicy.PUBLIC_KEYED


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
            default_schema = responses["default"]["content"]["application/problem+json"]["schema"]
            assert default_schema == problem_ref
            for code, response in responses.items():
                if code.isdigit() and int(code) >= 400:
                    schema = response["content"]["application/problem+json"]["schema"]
                    ref = schema.get("$ref") if isinstance(schema, dict) else None
                    assert ref is not None
                    assert ref.rsplit("/", 1)[-1] in schemas
                    error_responses_seen += 1
    assert error_responses_seen > 0

    policy_conflict = spec["paths"]["/v1/ops/datasets/refresh-policy"]["put"]["responses"]["409"][
        "content"
    ]["application/problem+json"]["schema"]
    assert policy_conflict == {"$ref": "#/components/schemas/ProviderRefreshPolicyConflictProblem"}


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
                                    "schema": {"$ref": "#/components/schemas/NotAProblem"}
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


# --- T-VN-H07: PinVi 소비 curated surface의 필드 단위(required/type/enum) 계약 ---
#
# 아래 helper·상수·테스트는 PinVi가 REST로 읽는 공개 curated 응답 schema를
# "경로/property 존재"가 아니라 required 집합·JSON type·enum(및 discriminator
# const)까지 생성 OpenAPI 기준으로 고정한다. Map 저장소 측 contract test를
# required/type/enum 필드까지 강화하는 T-VN-H07 Map half이다.


def _property_json_type(prop: dict[str, Any]) -> str:
    """생성 OpenAPI property의 primitive JSON type을 돌려준다.

    ``X | None`` 필드가 만드는 ``anyOf: [<schema>, {"type": "null"}]`` nullable
    shape를 벗겨내고, component 참조는 ``"$ref"``로 보고해 호출자가 필드별 JSON
    type을 정확히 고정할 수 있게 한다.
    """
    if "$ref" in prop:
        return "$ref"
    if "type" in prop:
        return str(prop["type"])
    branches = prop.get("anyOf")
    if isinstance(branches, list):
        non_null = [
            branch
            for branch in branches
            if isinstance(branch, dict) and branch.get("type") != "null"
        ]
        if len(non_null) == 1:
            only = non_null[0]
            if "$ref" in only:
                return "$ref"
            if "type" in only:
                return str(only["type"])
    raise AssertionError(f"cannot resolve JSON type for property: {prop!r}")


def _property_ref(prop: dict[str, Any]) -> str | None:
    """(nullable 포함) ``$ref`` property가 가리키는 schema 이름."""
    ref = prop.get("$ref")
    if not isinstance(ref, str):
        for branch in prop.get("anyOf", []):
            if isinstance(branch, dict) and isinstance(branch.get("$ref"), str):
                ref = branch["$ref"]
                break
    return ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None


def _property_format(prop: dict[str, Any]) -> str | None:
    """(nullable 포함) property의 선언된 ``format``."""
    if "format" in prop:
        return str(prop["format"])
    for branch in prop.get("anyOf", []):
        if isinstance(branch, dict) and branch.get("type") != "null" and "format" in branch:
            return str(branch["format"])
    return None


def _assert_object_schema_contract(
    spec: dict[str, Any],
    name: str,
    *,
    required: set[str],
    types: dict[str, str],
    formats: dict[str, str] | None = None,
    enums: dict[str, set[str]] | None = None,
    consts: dict[str, str] | None = None,
    refs: dict[str, str] | None = None,
) -> None:
    """생성 object schema 하나의 필드 단위 계약을 검증한다.

    exact property 집합, exact ``required`` 집합, 필드별 JSON type, ``format``,
    enum 값 집합, discriminator ``const``, ``$ref`` 대상을 모두 고정한다
    (T-VN-H07 Map contract 강화).
    """
    schema = spec["components"]["schemas"][name]
    assert schema.get("type") == "object", name
    assert schema.get("additionalProperties") is False, name
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == set(types), (name, set(properties) ^ set(types))
    observed_required = set(schema.get("required", []))
    assert observed_required == required, (name, observed_required ^ required)
    for field, expected in types.items():
        assert _property_json_type(properties[field]) == expected, (
            name,
            field,
            _property_json_type(properties[field]),
        )
    for field, fmt in (formats or {}).items():
        assert _property_format(properties[field]) == fmt, (name, field)
    for field, values in (enums or {}).items():
        enum = properties[field].get("enum")
        assert isinstance(enum, list), (name, field, enum)
        assert set(enum) == values, (name, field, enum)
    for field, value in (consts or {}).items():
        assert properties[field].get("const") == value, (name, field)
    for field, target in (refs or {}).items():
        assert _property_ref(properties[field]) == target, (name, field)


# PinVi curated_features union variant가 공유하는 base 필드 계약.
_CURATED_FEATURE_BASE_TYPES: dict[str, str] = {
    "curated_feature_id": "string",
    "theme_slug": "string",
    "theme_name": "string",
    "theme_group": "string",
    "feature_id": "string",
    "feature_name": "string",
    "feature_category": "string",
    "lon": "number",
    "lat": "number",
    "sido_code": "string",
    "sigungu_code": "string",
    "legal_dong_code": "string",
    "address": "$ref",
    "source_name": "string",
    "source_url": "string",
    "display_title": "string",
    "display_summary": "string",
    "curation_relation": "string",
    "reuse_policy": "string",
    "content_version": "integer",
    "updated_at": "string",
}
_CURATED_FEATURE_BASE_REQUIRED: set[str] = {
    "curated_feature_id",
    "theme_slug",
    "theme_name",
    "theme_group",
    "feature_id",
    "feature_name",
    "feature_category",
    "address",
    "source_name",
    "curation_relation",
    "reuse_policy",
    "content_version",
    "updated_at",
}
_CURATED_FEATURE_BASE_FORMATS: dict[str, str] = {
    "updated_at": "date-time",
    "source_url": "uri",
}
# feature_kind 판별값 → (variant schema, detail schema | None)
_CURATED_FEATURE_VARIANTS: dict[str, tuple[str, str | None]] = {
    "place": ("PublicCuratedPlaceFeatureView", "PublicCuratedPlaceDetail"),
    "event": ("PublicCuratedEventFeatureView", "PublicCuratedEventDetail"),
    "notice": ("PublicCuratedNoticeFeatureView", "PublicCuratedNoticeDetail"),
    "area": ("PublicCuratedAreaFeatureView", "PublicCuratedAreaDetail"),
    "route": ("PublicCuratedRouteFeatureView", "PublicCuratedRouteDetail"),
    "price": ("PublicCuratedPriceFeatureView", None),
    "weather": ("PublicCuratedWeatherFeatureView", None),
}
_CURATED_DETAIL_CONTRACTS: dict[str, dict[str, Any]] = {
    "PublicCuratedPlaceDetail": {
        "required": {"feature_id"},
        "types": {
            "feature_id": "string",
            "place_kind": "string",
            "phones": "array",
            "reviews_link": "$ref",
            "business_hours": "$ref",
            "facility_info": "$ref",
            "license_date": "string",
            "biz_number": "string",
        },
        "formats": {"license_date": "date"},
        "refs": {
            "reviews_link": "PublicCuratedReviewLinks",
            "business_hours": "PublicCuratedOpeningHours",
            "facility_info": "PublicCuratedPlaceFacilityInfo",
        },
    },
    "PublicCuratedEventDetail": {
        "required": {"feature_id"},
        "types": {
            "feature_id": "string",
            "event_kind": "string",
            "starts_on": "string",
            "ends_on": "string",
            "timezone": "string",
            "opening_hours": "$ref",
            "venue_name": "string",
            "tel": "string",
            "content_id": "string",
            "content_type_id": "string",
            "area_code": "string",
            "sigungu_code": "string",
        },
        "formats": {"starts_on": "date", "ends_on": "date"},
        "refs": {"opening_hours": "PublicCuratedOpeningHours"},
    },
    "PublicCuratedNoticeDetail": {
        "required": {"feature_id", "notice_type"},
        "types": {
            "feature_id": "string",
            "notice_type": "string",
            "severity": "integer",
            "valid_start_time": "string",
            "valid_end_time": "string",
            "source_agency": "string",
            "officer_name": "string",
        },
        "formats": {
            "valid_start_time": "date-time",
            "valid_end_time": "date-time",
        },
    },
    "PublicCuratedAreaDetail": {
        "required": {"feature_id"},
        "types": {
            "feature_id": "string",
            "area_kind": "string",
            "area_square_meters": "number",
            "boundary_source": "string",
            "regulation_scope": "string",
            "administrative_office": "string",
            "description": "string",
        },
    },
    "PublicCuratedRouteDetail": {
        "required": {"feature_id"},
        "types": {
            "feature_id": "string",
            "route_type": "string",
            "geometry_source": "string",
            "geometry_status": "string",
            "total_distance_meters": "number",
            "expected_duration_minutes": "integer",
            "difficulty": "string",
            "begin_name": "string",
            "begin_address": "string",
            "end_name": "string",
            "end_address": "string",
        },
    },
}


@pytest.mark.unit
def test_public_curated_feature_schemas_pin_required_types_and_enums() -> None:
    """PinVi가 소비하는 curated feature union을 required/type/const(kind) 단위로 고정."""
    module = _load_script_module()
    app = create_app(ApiSettings())
    user = module.user_openapi_spec(app.openapi(), app=app)

    for kind, (variant, detail) in _CURATED_FEATURE_VARIANTS.items():
        types = {**_CURATED_FEATURE_BASE_TYPES, "feature_kind": "string"}
        required = _CURATED_FEATURE_BASE_REQUIRED | {"feature_kind"}
        refs = {"address": "PublicCuratedAddress"}
        if detail is None:
            types["detail"] = "null"
        else:
            types["detail"] = "$ref"
            required = required | {"detail"}
            refs["detail"] = detail
        _assert_object_schema_contract(
            user,
            variant,
            required=required,
            types=types,
            formats=_CURATED_FEATURE_BASE_FORMATS,
            consts={"feature_kind": kind},
            refs=refs,
        )

    for detail_name, contract in _CURATED_DETAIL_CONTRACTS.items():
        _assert_object_schema_contract(
            user,
            detail_name,
            required=contract["required"],
            types=contract["types"],
            formats=contract.get("formats"),
            refs=contract.get("refs"),
        )

    # phones는 PinVi가 소비하는 array element이므로 item type까지 고정한다
    # (list[PublicPhone] = Annotated[str] → items.type == "string"). element가 object로
    # 바뀌면 items가 $ref가 되어 "type"이 사라지므로 element shape 변경을 검출한다.
    place_detail = user["components"]["schemas"]["PublicCuratedPlaceDetail"]
    assert place_detail["properties"]["phones"]["items"]["type"] == "string"

    # PublicCuratedAddress는 7개 curated feature variant 모두의 address ref
    # 대상이므로(PinVi 주 소비 표면) 그 필드 shape도 field-level로 고정한다.
    _assert_object_schema_contract(
        user,
        "PublicCuratedAddress",
        required=set(),
        types={
            "road": "string",
            "legal": "string",
            "admin": "string",
            "zipcode": "string",
            "sido_name": "string",
            "sigungu_name": "string",
        },
    )


@pytest.mark.unit
def test_public_curation_collection_item_group_pin_required_types_and_enums() -> None:
    """공개 curation collection/item/feature-group schema를 required/type/enum 고정."""
    module = _load_script_module()
    app = create_app(ApiSettings())
    user = module.user_openapi_spec(app.openapi(), app=app)

    _assert_object_schema_contract(
        user,
        "PublicCurationCollectionView",
        required={
            "collection_id",
            "collection_key",
            "theme_id",
            "theme_slug",
            "theme_name",
            "theme_group",
            "source_id",
            "provider",
            "dataset_key",
            "source_name",
            "source_url",
            "title",
            "edition_key",
            "description",
            "status",
            "visibility",
            "item_count",
            "created_at",
            "updated_at",
            "archived_at",
        },
        types={
            "collection_id": "string",
            "collection_key": "string",
            "theme_id": "string",
            "theme_slug": "string",
            "theme_name": "string",
            "theme_group": "string",
            "source_id": "string",
            "provider": "string",
            "dataset_key": "string",
            "source_name": "string",
            "source_url": "string",
            "title": "string",
            "edition_key": "string",
            "description": "string",
            "status": "string",
            "visibility": "string",
            "item_count": "integer",
            "created_at": "string",
            "updated_at": "string",
            "archived_at": "string",
        },
        formats={
            "collection_id": "uuid",
            "theme_id": "uuid",
            "source_id": "uuid",
            "created_at": "date-time",
            "updated_at": "date-time",
            "archived_at": "date-time",
        },
        enums={
            "status": {"draft", "published", "archived"},
            "visibility": {"admin_only", "public"},
        },
    )

    _assert_object_schema_contract(
        user,
        "PublicCurationItemView",
        required={
            "curation_item_id",
            "collection_id",
            "collection_key",
            "title",
            "edition_key",
            "theme_slug",
            "theme_name",
            "theme_group",
            "provider",
            "dataset_key",
            "source_name",
            "source_url",
            "feature_id",
            "feature_name",
            "feature_kind",
            "feature_category",
            "lon",
            "lat",
            "address",
            "external_item_id",
            "external_component_id",
            "place_name",
            "address_hint",
            "status",
            "sort_order",
            "item_title",
            "item_summary",
            "curation_relation",
            "reuse_policy",
            "created_at",
            "updated_at",
            "archived_at",
        },
        types={
            "curation_item_id": "string",
            "collection_id": "string",
            "collection_key": "string",
            "title": "string",
            "edition_key": "string",
            "theme_slug": "string",
            "theme_name": "string",
            "theme_group": "string",
            "provider": "string",
            "dataset_key": "string",
            "source_name": "string",
            "source_url": "string",
            "feature_id": "string",
            "feature_name": "string",
            "feature_kind": "string",
            "feature_category": "string",
            "lon": "number",
            "lat": "number",
            "address": "object",
            "external_item_id": "string",
            "external_component_id": "string",
            "place_name": "string",
            "address_hint": "string",
            "status": "string",
            "sort_order": "integer",
            "item_title": "string",
            "item_summary": "string",
            "curation_relation": "string",
            "reuse_policy": "string",
            "created_at": "string",
            "updated_at": "string",
            "archived_at": "string",
        },
        formats={
            "curation_item_id": "uuid",
            "collection_id": "uuid",
            "created_at": "date-time",
            "updated_at": "date-time",
            "archived_at": "date-time",
        },
        enums={
            "status": {"candidate", "included", "rejected", "archived"},
            "curation_relation": {
                "primary_stop",
                "food_stop",
                "cafe_stop",
                "bookstore_stop",
                "nearby_option",
                "accessibility_support",
                "pet_support",
                "family_support",
                "theme_area_anchor",
            },
            "reuse_policy": {"allowed", "blocked", "manual_review"},
        },
    )

    _assert_object_schema_contract(
        user,
        "CurationFeatureView",
        required={
            "feature_id",
            "name",
            "kind",
            "category",
            "lon",
            "lat",
            "address",
            "status",
        },
        types={
            "feature_id": "string",
            "name": "string",
            "kind": "string",
            "category": "string",
            "lon": "number",
            "lat": "number",
            "address": "object",
            "status": "string",
        },
    )

    _assert_object_schema_contract(
        user,
        "FeatureCurationGroupView",
        required={"feature", "curations", "curation_count"},
        types={
            "feature": "$ref",
            "curations": "array",
            "curation_count": "integer",
        },
        refs={"feature": "CurationFeatureView"},
    )
    group_curations = user["components"]["schemas"]["FeatureCurationGroupView"]["properties"][
        "curations"
    ]["items"]
    assert group_curations == {"$ref": "#/components/schemas/PublicCurationItemView"}
