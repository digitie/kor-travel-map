"""OpenAPI export/profile 필터 테스트 (ADR-045 T-207g)."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.api import app as app_module
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

    # T-VN-40C — legacy curated overlay 표면(공개 `/v1/curated-*`, admin
    # `/v1/admin/features/curated*`)은 물리 삭제됐다. admin themes/sources만 남는다.
    assert "visibility" in _query_parameter_names(full, "/v1/admin/curated-themes")

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
        "/v1/features/{feature_id}/price/snapshot",
        "/v1/features/{feature_id}/weather",
        "/v1/features/{feature_id}/weather/snapshot",
        "/v1/features/{feature_id}/weather/forecast",
        "/v1/features/weather/forecast",
        "/v1/features/weather/alerts",
        "/v1/public/beaches",
        "/v1/public/beaches/map-markers",
        "/v1/public/beaches/{feature_id}",
        "/v1/public/festivals/monthly",
        "/v1/public/festivals/map-markers",
        "/v1/public/festivals/{feature_id}",
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
    assert "FeatureBatchResponse" not in schemas
    assert "WeatherBatchResponse" not in schemas
    assert "CacheTargetClaimResponse" not in schemas
    assert "CacheTargetEventRecord" not in schemas
    assert "BeachPublicView" in schemas
    assert "FestivalPublicView" in schemas
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
    # T-VN-40C — 공개 `PublicCuratedFeature*` union과 nested DTO는 legacy overlay와
    # 함께 물리 삭제됐다. 그 계약을 지키던 단언도 같이 사라진다(위 `not in schemas`가
    # 재등장을 막는다).
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
    # T-VN-34C: public visibility는 fence로만 표현한다. Feature 상태 원문과
    # 내부 3축은 admin projection에만 있으며 어떤 public feature schema에도 없다.
    for schema_name in (
        "FeatureSummary",
        "FeatureDetailResponse",
        "NearbyFeatureSummary",
        "CurationFeatureView",
    ):
        assert {"status", "lifecycle_state", "publication_state", "quality_state"}.isdisjoint(
            _schema_properties(user, schema_name)
        )
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
    service = module.service_openapi_spec(full, app=app)

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
    expected_service_operations = {
        (row.schema_path, method.lower())
        for row in build_route_policy_matrix(app)
        if row.include_in_schema
        and not row.is_websocket
        and row.policy in module.SERVICE_ROUTE_POLICIES
        for method in row.methods
        if method.lower() in module.HTTP_METHODS
    }

    assert full_operations == route_operations
    assert module._openapi_operations(user) == expected_user_operations
    assert module._openapi_operations(service) == expected_service_operations


@pytest.mark.unit
def test_service_openapi_spec_contains_service_routes_and_prunes_user_routes() -> None:
    module = _load_script_module()
    app = create_app(ApiSettings())
    full = app.openapi()
    service = module.service_openapi_spec(full, app=app)

    assert service["info"]["title"] == "kor-travel-map-service"
    assert set(service["paths"]) == {
        "/v1/features/batch",
        "/v1/features/weather/batch",
        "/v1/ops/contract-fixtures/c6c-cancel-probe/{transaction_id}",
        "/v1/ops/contract-fixtures/c6c-cancel-probe/{transaction_id}/finalize",
        "/v1/service/cache-target-event-acks",
        "/v1/service/cache-target-event-claims",
        "/v1/service/cache-target-event-dead-letters/{event_id}",
        "/v1/service/cache-target-event-dead-letters/{event_id}/replays",
        "/v1/service/cache-target-event-nacks",
        "/v1/service/cache-target-reconciliations",
        "/v1/service/cache-target-reconciliations/{request_id}/completions",
        "/v1/service/cache-target-reconciliations/{request_id}/seals",
        "/v1/service/cache-target-reconciliations/{request_id}/snapshot",
        "/v1/service/cache-target-snapshots/{external_system}",
        "/v1/service/cache-target-streams/{external_system}",
        "/v1/service/cache-target-streams/{external_system}/restore-fences",
        "/v1/service/cache-targets/{external_system}/{target_key}",
        "/v1/service/curation-collections/{collection_id}/detail-snapshot",
        "/v1/service/curation-cutover/identity-mappings",
        "/v1/service/curation-items/{curation_item_id}/detail-snapshot",
        # T-VN-32C alias-map DB-to-DB 이관 표면 (ADR-068 전환·복구 경계 read).
        "/v1/service/feature-alias-maps",
        "/v1/service/feature-alias-maps/checksum",
        "/v1/service/refresh-requests",
        "/v1/service/refresh-requests/{request_id}",
    }
    assert set(service["components"]["securitySchemes"]) == {
        "OpsScope",
        "OpsToken",
        "ServiceToken",
    }
    service_only_paths = {
        "/v1/ops/contract-fixtures/c6c-cancel-probe/{transaction_id}",
        "/v1/ops/contract-fixtures/c6c-cancel-probe/{transaction_id}/finalize",
        "/v1/service/cache-target-reconciliations",
        "/v1/service/cache-target-reconciliations/{request_id}/completions",
        "/v1/service/cache-target-reconciliations/{request_id}/seals",
        "/v1/service/cache-target-reconciliations/{request_id}/snapshot",
    }
    for path in service_only_paths:
        assert path in app.openapi()["paths"]
        assert path not in module.user_openapi_spec(app.openapi(), app=app)["paths"]
        assert path in service["paths"]
    for path, method in module._openapi_operations(service):
        expected_security = [{"ServiceToken": []}]
        if path.startswith("/v1/ops/contract-fixtures/"):
            expected_security = [{"OpsToken": [], "OpsScope": []}]
        assert service["paths"][path][method]["security"] == expected_security

    schemas = service["components"]["schemas"]
    assert "FeatureBatchResponse" in schemas
    assert "WeatherBatchResponse" in schemas
    assert "CacheTargetClaimResponse" in schemas
    snapshot_data = schemas["CacheTargetSnapshotData"]
    assert {"created_at", "expires_at"} <= set(snapshot_data["required"])
    assert snapshot_data["properties"]["created_at"]["format"] == "date-time"
    assert snapshot_data["properties"]["expires_at"]["format"] == "date-time"
    expires_description = snapshot_data["properties"]["expires_at"]["description"]
    assert "서버 handoff 직전 최소 75분" in expires_description
    assert "client 수신 후 최소 60분" in expires_description
    assert "running" in expires_description
    high_watermark_description = snapshot_data["properties"]["high_watermark_cursor"]["description"]
    assert "replay lower-bound" in high_watermark_description
    assert "중복 허용" in high_watermark_description
    snapshot_responses = service["paths"]["/v1/service/cache-target-snapshots/{external_system}"][
        "get"
    ]["responses"]
    capacity_response = snapshot_responses["429"]
    retry_after_schema = capacity_response["headers"]["Retry-After"]["schema"]
    assert retry_after_schema == {"type": "integer", "minimum": 1, "maximum": 7_200}
    assert "application/problem+json" in capacity_response["content"]
    assert "413" in snapshot_responses
    assert "503" in snapshot_responses
    assert "Retry-After" in snapshot_responses["503"]["headers"]
    assert "headers" not in snapshot_responses["413"]
    seal_responses = service["paths"][
        "/v1/service/cache-target-reconciliations/{request_id}/seals"
    ]["post"]["responses"]
    assert "413" in seal_responses
    assert "503" in seal_responses
    assert "Retry-After" in seal_responses["503"]["headers"]
    assert "headers" not in seal_responses["413"]
    assert "application/problem+json" in seal_responses["413"]["content"]
    compacted_ref = {
        "$ref": "#/components/schemas/CacheTargetSnapshotMaterialCompactedProblem"
    }
    for spec, path, method in (
        (
            service,
            "/v1/service/cache-target-snapshots/{external_system}",
            "get",
        ),
        (
            service,
            "/v1/service/cache-target-reconciliations/{request_id}/seals",
            "post",
        ),
        (
            full,
            "/v1/admin/cache-target-reconciliations",
            "post",
        ),
    ):
        admission_schema = spec["paths"][path][method]["responses"]["413"]["content"][
            "application/problem+json"
        ]["schema"]
        assert _refs(admission_schema) == {
            "CacheTargetSnapshotItemLimitProblem",
            "CacheTargetSnapshotByteLimitProblem",
        }
        assert admission_schema["discriminator"]["propertyName"] == "code"
        assert set(admission_schema["discriminator"]["mapping"]) == {
            "SNAPSHOT_ITEM_LIMIT_EXCEEDED",
            "SNAPSHOT_BYTE_LIMIT_EXCEEDED",
        }
    assert service["paths"][
        "/v1/service/cache-target-reconciliations/{request_id}/snapshot"
    ]["get"]["responses"]["410"]["content"]["application/problem+json"][
        "schema"
    ] == compacted_ref

    item_problem = schemas["CacheTargetSnapshotItemLimitProblem"]
    assert item_problem["properties"]["status"]["const"] == 413
    assert item_problem["properties"]["code"]["const"] == (
        "SNAPSHOT_ITEM_LIMIT_EXCEEDED"
    )
    assert _refs(item_problem["properties"]["details"]) == {
        "CacheTargetSnapshotItemLimitDetails"
    }
    byte_problem = schemas["CacheTargetSnapshotByteLimitProblem"]
    assert byte_problem["properties"]["status"]["const"] == 413
    assert byte_problem["properties"]["code"]["const"] == (
        "SNAPSHOT_BYTE_LIMIT_EXCEEDED"
    )
    assert _refs(byte_problem["properties"]["details"]) == {
        "CacheTargetSnapshotByteLimitDetails"
    }
    assert set(schemas["CacheTargetSnapshotItemLimitDetails"]["required"]) == {
        "item_count_lower_bound",
        "item_limit",
    }
    assert set(schemas["CacheTargetSnapshotByteLimitDetails"]["required"]) == {
        "material_bytes_lower_bound",
        "material_byte_limit",
    }
    compacted_problem = schemas["CacheTargetSnapshotMaterialCompactedProblem"]
    assert compacted_problem["properties"]["status"]["const"] == 410
    assert (
        compacted_problem["properties"]["code"]["const"]
        == "SNAPSHOT_MATERIAL_COMPACTED"
    )
    compacted_details = schemas["CacheTargetSnapshotMaterialCompactedDetails"]
    assert set(compacted_details["required"]) == {
        "snapshot_id",
        "item_count",
        "merkle_root",
        "compacted_at",
    }
    assert compacted_details["properties"]["snapshot_id"]["format"] == "uuid"
    assert compacted_details["properties"]["compacted_at"]["format"] == "date-time"
    assert compacted_details["properties"]["merkle_root"]["pattern"] == r"^[0-9a-f]{64}$"
    mutation_record = schemas["CacheTargetSourceMutationRecord"]
    assert {"target_id", "entity_tag", "target_sequence"} <= set(mutation_record["required"])
    assert mutation_record["properties"]["target_id"]["format"] == "uuid"
    assert "anyOf" not in mutation_record["properties"]["target_id"]
    assert "anyOf" not in mutation_record["properties"]["entity_tag"]
    assert mutation_record["properties"]["target_sequence"]["minimum"] == 1
    read_record = schemas["CacheTargetSourceRecord"]
    assert {"type": "null"} in read_record["properties"]["target_id"]["anyOf"]
    assert {"type": "null"} in read_record["properties"]["entity_tag"]["anyOf"]
    assert {"type": "null"} in read_record["properties"]["target_sequence"]["anyOf"]
    target_path = service["paths"]["/v1/service/cache-targets/{external_system}/{target_key}"]
    assert _refs(target_path["put"]["responses"]["200"]) == {"CacheTargetSourceMutationResponse"}
    assert _refs(target_path["delete"]["responses"]["200"]) == {"CacheTargetSourceMutationResponse"}
    assert _refs(target_path["get"]["responses"]["200"]) == {"CacheTargetSourceReadResponse"}
    assert _refs(schemas["CacheTargetSourceMutationResponse"]["properties"]["data"]) == {
        "CacheTargetSourceMutationRecord"
    }
    assert _refs(schemas["CacheTargetSourceReadResponse"]["properties"]["data"]) == {
        "CacheTargetSourceRecord"
    }
    begin_headers = {
        parameter["name"]: parameter
        for parameter in service["paths"]["/v1/service/cache-target-reconciliations"]["post"][
            "parameters"
        ]
        if parameter.get("in") == "header"
    }
    assert begin_headers["If-Match"]["required"] is False
    assert begin_headers["If-None-Match"]["required"] is False
    seal_headers = {
        parameter["name"]: parameter
        for parameter in service["paths"][
            "/v1/service/cache-target-reconciliations/{request_id}/seals"
        ]["post"]["parameters"]
        if parameter.get("in") == "header"
    }
    assert seal_headers["If-Match"]["required"] is True
    running_schema = schemas["CacheTargetReconciliationRunning"]
    assert running_schema["properties"]["merkle_root"]["pattern"] == r"^[0-9a-f]{64}$"
    event_schema = schemas["CacheTargetEventRecord"]
    event_properties = event_schema["properties"]
    assert {
        "event_scope",
        "payload",
        "source_payload_fingerprint",
        "target_key",
        "target_id",
        "source_generation",
        "target_sequence",
    } <= set(event_properties)
    assert set(event_properties["event_scope"]["enum"]) == {"target", "stream"}
    assert {"type": "null"} in event_properties["target_key"]["anyOf"]
    assert {"type": "null"} in event_properties["target_id"]["anyOf"]
    assert {"type": "null"} in event_properties["source_generation"]["anyOf"]
    assert {"type": "null"} in event_properties["target_sequence"]["anyOf"]
    assert "CacheTargetReconciledPayload" in _refs(event_properties["payload"])
    reconciled_payload = schemas["CacheTargetReconciledPayload"]
    assert set(reconciled_payload["required"]) == {
        "request_id",
        "snapshot_id",
        "actual_merkle_root",
        "expected_merkle_root",
        "status",
        "version",
    }
    assert reconciled_payload["additionalProperties"] is False
    assert reconciled_payload["properties"]["request_id"]["format"] == "uuid"
    assert reconciled_payload["properties"]["snapshot_id"]["format"] == "uuid"
    refresh_target_keys = schemas["CacheTargetRefreshRequest"]["properties"]["target_keys"]
    assert refresh_target_keys["maxItems"] == 500
    assert refresh_target_keys["uniqueItems"] is True
    assert "PublicCuratedFeatureView" not in schemas
    assert "AdminFeatureListResponse" not in schemas


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
    service = module.service_openapi_spec(full, app=app)
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

    for spec in (full, user, service):
        for path, method in module._openapi_operations(spec):
            policy = policies[path]
            operation = spec["paths"][path][method]
            security = expected_security.get(policy)
            if path.startswith("/v1/ops/contract-fixtures/"):
                security = [{"OpsToken": [], "OpsScope": []}]
            if security is not None:
                assert operation.get("security", []) == security, (
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
                    assert isinstance(schema, dict)
                    assert app_module._declares_problem_schema(  # pyright: ignore[reportPrivateUsage]
                        schema,
                        schemas,
                    )
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
            # ADR-088 — dataset canonical ID가 정본 축이고 provider/dataset_key는
            # 표시용 projection으로 남는다.
            "provider_dataset_id",
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
            "provider_dataset_id": "integer",
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
            "provider_dataset_id",
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
            "provider_dataset_id": "integer",
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
        },
        types={
            "feature_id": "string",
            "name": "string",
            "kind": "string",
            "category": "string",
            "lon": "number",
            "lat": "number",
            "address": "object",
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
