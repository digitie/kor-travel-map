"""Actor-scoped domain command ledger repository 단위 계약."""

from __future__ import annotations

from math import nan

import pytest

from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
    lock_domain_command,
)


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    async def execute(self, statement: object, params: object) -> None:
        self.calls.append((statement, params))


def test_fingerprint_is_canonical_for_json_object_order() -> None:
    left = canonical_domain_command_fingerprint(
        {
            "path": {"feature_id": "feature-1"},
            "body": {"name": "서울", "enabled": True, "tags": ["a", "b"]},
        }
    )
    right = canonical_domain_command_fingerprint(
        {
            "body": {"tags": ["a", "b"], "enabled": True, "name": "서울"},
            "path": {"feature_id": "feature-1"},
        }
    )

    assert left == right
    assert len(left) == 64


def test_fingerprint_changes_when_list_order_or_value_changes() -> None:
    original = canonical_domain_command_fingerprint({"items": [1, 2], "enabled": True})

    assert original != canonical_domain_command_fingerprint(
        {"items": [2, 1], "enabled": True}
    )
    assert original != canonical_domain_command_fingerprint(
        {"items": [1, 2], "enabled": False}
    )


def test_fingerprint_rejects_non_json_finite_number() -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_domain_command_fingerprint({"value": nan})


@pytest.mark.asyncio
async def test_lock_namespace_includes_actor_operation_and_key() -> None:
    session = _FakeSession()

    await lock_domain_command(  # type: ignore[arg-type]
        session,
        actor="admin:alice",
        operation="admin.feature.create",
        idempotency_key="91000000-0000-4000-8000-000000000001",
    )

    assert len(session.calls) == 1
    statement, params = session.calls[0]
    assert "pg_advisory_xact_lock" in str(statement)
    assert isinstance(params, dict)
    assert set(params) == {"lock_id"}
    assert isinstance(params["lock_id"], int)
