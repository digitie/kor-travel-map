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
    assert len(writes) == 55


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


def test_future_h22b_quarantine_command_cannot_bypass_domain_ledger() -> None:
    for key, operation in _openapi_writes().items():
        operation_id = str(operation.get("operationId", "")).lower()
        path = key[1].lower()
        if "reclassif" in operation_id or (
            "quarantine" in path and key[0] in _WRITE_METHODS
        ):
            assert COMMAND_REGISTRY[key].kind is CommandPolicyKind.DOMAIN_LEDGER


def test_policy_requires_operation_only_for_ledger_kinds() -> None:
    with pytest.raises(ValueError, match="requires operation"):
        CommandPolicy(
            kind=CommandPolicyKind.DOMAIN_LEDGER,
            reason="missing operation",
        )
    with pytest.raises(ValueError, match="must not declare operation"):
        CommandPolicy(
            kind=CommandPolicyKind.QUERY,
            reason="query",
            operation="not-allowed",
        )


def test_command_policy_fails_closed_for_unregistered_write() -> None:
    with pytest.raises(
        KeyError,
        match=r"unregistered write operation: POST /v1/admin/future-command",
    ):
        command_policy("post", "/v1/admin/future-command")
