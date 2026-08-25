"""T-VN-12A OpenAPI command inventory 완전성 gate."""

from __future__ import annotations

from typing import Any

import pytest

from kortravelmap.api.app import app
from kortravelmap.api.domain_command_registry import (
    COMMAND_REGISTRY,
    CommandPolicy,
    CommandPolicyKind,
    command_policy,
)

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _openapi_writes() -> dict[tuple[str, str], dict[str, Any]]:
    spec = app.openapi()
    return {
        (method.upper(), path): operation
        for path, path_item in spec["paths"].items()
        for method, operation in path_item.items()
        if method.upper() in _WRITE_METHODS
    }


def _header(operation: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next(
        (
            parameter
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header" and parameter.get("name") == name
        ),
        None,
    )


def test_every_openapi_write_operation_has_exact_static_policy() -> None:
    writes = _openapi_writes()

    assert set(COMMAND_REGISTRY) == set(writes)
    assert len(writes) == 77


def test_registered_domain_and_specialized_ledgers_have_stable_operation_names() -> None:
    operations = [
        policy.operation
        for policy in COMMAND_REGISTRY.values()
        if policy.kind
        in {
            CommandPolicyKind.DOMAIN_LEDGER,
            CommandPolicyKind.SPECIALIZED_LEDGER,
        }
    ]

    assert all(operation is not None for operation in operations)
    assert len(operations) == len(set(operations))


def test_existing_specialized_routes_require_uuid_idempotency_header() -> None:
    writes = _openapi_writes()
    specialized_header_routes = {
        key
        for key, policy in COMMAND_REGISTRY.items()
        if policy.kind is CommandPolicyKind.SPECIALIZED_LEDGER
        and policy.operation
        in {
            "feature-update.request",
            "dagster-schedule.patch",
            "dagster-schedule.command",
        }
    }

    for key in specialized_header_routes:
        header = _header(writes[key], "Idempotency-Key")
        assert header is not None, key
        assert header["required"] is True
        assert header["schema"]["format"] == "uuid"


def test_feature_curation_review_domain_routes_require_uuid_header() -> None:
    writes = _openapi_writes()
    deferred_external_operations = {
        "admin.backup.create",
        "admin.backup.delete",
        "admin.offline-upload.create",
        "admin.offline-upload.delete",
        "admin.offline-upload.load",
    }
    routes = {
        key
        for key, policy in COMMAND_REGISTRY.items()
        if policy.kind is CommandPolicyKind.DOMAIN_LEDGER
        and policy.operation not in deferred_external_operations
    }

    for key in routes:
        header = _header(writes[key], "Idempotency-Key")
        assert header is not None, key
        assert header["required"] is True
        assert header["schema"]["format"] == "uuid"


def test_generic_domain_ledger_is_admin_bff_only() -> None:
    writes = _openapi_writes()
    routes = {
        key
        for key, policy in COMMAND_REGISTRY.items()
        if policy.kind is CommandPolicyKind.DOMAIN_LEDGER
    }

    for key in routes:
        method, path = key
        assert method in _WRITE_METHODS
        if path.startswith("/v1/admin/"):
            expected_security = (
                [{"AdminBFF": [], "AdminFeatureCreateBFF": []}]
                if key
                in {
                    ("POST", "/v1/admin/features"),
                    (
                        "POST",
                        "/v1/admin/curations/{collection_id}/items/manual-feature",
                    ),
                    ("POST", "/v1/admin/feature-requests/{request_id}/approve"),
                    ("POST", "/v1/admin/feature-requests/{request_id}/reject"),
                }
                else [{"AdminBFF": []}]
            )
            assert writes[key]["security"] == expected_security, key
        else:
            assert path.startswith("/v1/service/")
            assert writes[key]["security"] == [{"ServiceToken": []}], key


def test_domain_terminal_contract_matches_declared_openapi_success_response() -> None:
    writes = _openapi_writes()
    transport_headers = {"X-Request-ID", "Idempotency-Replayed"}

    for key, policy in COMMAND_REGISTRY.items():
        if policy.kind is not CommandPolicyKind.DOMAIN_LEDGER:
            continue
        responses = writes[key]["responses"]
        success_codes = {int(code) for code in responses if str(code).startswith("2")}
        replay_codes = {
            int(code)
            for code, response in responses.items()
            if response.get("description") == "exact Idempotency-Key replay"
        }
        assert replay_codes <= {200}, key
        assert success_codes == {policy.success_status, *replay_codes}, key
        expected_headers = set(policy.replay_headers)
        if key == ("POST", "/v1/admin/features"):
            expected_headers.update(transport_headers)
        response = responses[str(policy.success_status)]
        assert set(response.get("headers", {})) == expected_headers, key
        for replay_code in replay_codes:
            response = responses[str(replay_code)]
            assert set(response.get("headers", {})) == expected_headers, key


def test_domain_fingerprint_header_contract_is_explicit_and_minimal() -> None:
    assert {
        policy.operation: policy.fingerprint_headers
        for policy in COMMAND_REGISTRY.values()
        if policy.kind is CommandPolicyKind.DOMAIN_LEDGER and policy.fingerprint_headers
    } == {
        "admin.cache-target-dead-letter.replay": ("If-Match",),
        "admin.curation-collection.archive": ("If-Match",),
        "admin.curation-collection.patch": ("If-Match",),
        "admin.curation-item.archive": ("If-Match",),
        "admin.curation-item.patch": ("If-Match",),
        "admin.curation-quarantine.reclassify": ("If-Match",),
        "admin.curation.import": ("If-Match",),
        "admin.curated-theme.archive": ("If-Match",),
        "admin.curated-theme.patch": ("If-Match",),
        "admin.curated-source.archive": ("If-Match",),
        "admin.curated-source.patch": ("If-Match",),
        "admin.curated-source-rule.archive": ("If-Match",),
        "admin.curated-source-rule.patch": ("If-Match",),
        "admin.feature.patch": ("If-Match",),
        # T-VN-36: typed field override의 author/revoke도 row_revision If-Match로
        # 잠긴다 (patch와 같은 낙관적 동시성 경계).
        "admin.feature.override.author": ("If-Match",),
        "admin.feature.override.revoke": ("If-Match",),
        "admin.feature.delete": ("If-Match",),
        "admin.feature.state": ("If-Match",),
        "admin.feature.state.reactivate": ("If-Match",),
        "admin.theme-feature-candidate.promote": ("If-Match",),
        "admin.theme-feature-candidate.reject": ("If-Match",),
        "service.cache-target-dead-letter.replay": ("If-Match",),
        "service.cache-target-reconciliation.begin": (
            "If-Match",
            "If-None-Match",
        ),
        "service.cache-target-reconciliation.seal": ("If-Match",),
        "service.cache-target-restore-fence.create": ("If-Match",),
    }


def test_curation_revision_commands_publish_required_if_match_header() -> None:
    """runtime에서 필수인 curation CAS가 OpenAPI에서도 optional로 약화되지 않는다."""

    writes = _openapi_writes()
    operations = {
        "admin.curation-collection.archive",
        "admin.curation-collection.patch",
        "admin.curation-item.archive",
        "admin.curation-item.patch",
        "admin.theme-feature-candidate.promote",
        "admin.theme-feature-candidate.reject",
    }
    routes = {key for key, policy in COMMAND_REGISTRY.items() if policy.operation in operations}
    assert len(routes) == len(operations)
    for key in routes:
        header = _header(writes[key], "If-Match")
        assert header is not None, key
        assert header["required"] is True, key
        assert header["schema"]["type"] == "string", key


def test_tvn40_canonical_collection_and_item_commands_are_serializable() -> None:
    operations = {
        "admin.curation-collection.archive",
        "admin.curation-collection.create",
        "admin.curation-collection.patch",
        "admin.curation-item.archive",
        "admin.curation-item.create",
        "admin.curation-item.patch",
    }
    policies = {
        policy.operation: policy
        for policy in COMMAND_REGISTRY.values()
        if policy.kind is CommandPolicyKind.DOMAIN_LEDGER and policy.operation in operations
    }
    assert set(policies) == operations
    assert all(policy.transaction_isolation == "serializable" for policy in policies.values())


def test_manual_feature_create_has_versioned_read_committed_terminal_contract() -> None:
    policy = COMMAND_REGISTRY[("POST", "/v1/admin/features")]
    response_headers = set(
        _openapi_writes()[("POST", "/v1/admin/features")]["responses"]["201"]["headers"]
    )

    assert policy.kind is CommandPolicyKind.DOMAIN_LEDGER
    assert policy.operation == "admin.feature.create.manual-v1"
    assert policy.success_status == 201
    assert policy.replay_headers == ("ETag", "Location")
    assert policy.transaction_isolation == "read-committed"
    assert response_headers == {
        "ETag",
        "Location",
        "X-Request-ID",
        "Idempotency-Replayed",
    }


def test_future_h22b_quarantine_command_cannot_bypass_domain_ledger() -> None:
    for key, operation in _openapi_writes().items():
        operation_id = str(operation.get("operationId", "")).lower()
        path = key[1].lower()
        if "reclassif" in operation_id or ("quarantine" in path and key[0] in _WRITE_METHODS):
            assert COMMAND_REGISTRY[key].kind is CommandPolicyKind.DOMAIN_LEDGER


def test_policy_requires_operation_only_for_ledger_kinds() -> None:
    with pytest.raises(ValueError, match="requires operation"):
        CommandPolicy(
            kind=CommandPolicyKind.DOMAIN_LEDGER,
            reason="missing operation",
            success_status=200,
        )
    with pytest.raises(ValueError, match="must not declare operation"):
        CommandPolicy(
            kind=CommandPolicyKind.QUERY,
            reason="query",
            operation="not-allowed",
        )
    with pytest.raises(ValueError, match="requires success_status"):
        CommandPolicy(
            kind=CommandPolicyKind.DOMAIN_LEDGER,
            reason="missing success response contract",
            operation="admin.test",
        )
    with pytest.raises(ValueError, match="unsupported terminal response headers"):
        CommandPolicy(
            kind=CommandPolicyKind.DOMAIN_LEDGER,
            reason="unsafe replay header",
            operation="admin.test",
            success_status=200,
            replay_headers=("Set-Cookie",),
        )
    with pytest.raises(ValueError, match="unsupported fingerprint headers"):
        CommandPolicy(
            kind=CommandPolicyKind.DOMAIN_LEDGER,
            reason="unsafe request identity",
            operation="admin.test",
            success_status=200,
            fingerprint_headers=("Cookie",),
        )
    with pytest.raises(ValueError, match="unsupported domain transaction isolation"):
        CommandPolicy(
            kind=CommandPolicyKind.DOMAIN_LEDGER,
            reason="unsafe isolation",
            operation="admin.test",
            success_status=200,
            transaction_isolation="repeatable-read",
        )


def test_command_policy_fails_closed_for_unregistered_write() -> None:
    with pytest.raises(
        KeyError,
        match=r"unregistered write operation: POST /v1/admin/future-command",
    ):
        command_policy("post", "/v1/admin/future-command")
