"""새 READY reset의 client 원 계획/commit 경계와 migration ACL. PG 수용은 별도다."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kortravelmap.client import _airport_snapshot, _rest_snapshot
from kortravelmap.infra import db
from kortravelmap.infra import runtime_privileges as acl
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotExecutorToken
from tests.unit.test_airport_snapshot_client import _client

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "snapshot_ready_reset_migration",
    _ROOT / "alembic/versions/433_snapshot_ready_plan_reset.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)


class _Settings:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values.items())


class _Bind:
    def __init__(self, create, values):
        self.create, self.values, self.calls = create, values, []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _Settings(self.values)

    def scalar(self, statement, params):
        assert "has_schema_privilege" in str(statement)
        assert params == {"owner": "ktm_curation_command_owner"}
        return self.create


@pytest.mark.parametrize("create", [False, True])
@pytest.mark.parametrize("prior", [0, 25, 50000])
def test_additive_upgrade_keeps_owner_acl_and_does_not_raise_shorter_deadlines(
    monkeypatch, create, prior
):
    settings = {"lock_timeout": str(prior), "statement_timeout": str(prior)}
    bind = _Bind(create, settings)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    migration.upgrade()
    sql = [statement for statement, _ in bind.calls]
    assert sql.index("SELECT ops.lock_scoped_feature_write_protocol(true)") < sql.index(
        migration._READY_RESET_SQL
    )
    role = None
    for statement in sql:
        if statement.startswith("SET ROLE "):
            role = statement.removeprefix("SET ROLE ")
        if statement == migration._READY_RESET_SQL:
            assert role == "ktm_curation_command_owner"
    for verb in ("GRANT", "REVOKE"):
        suffix = " TO " if verb == "GRANT" else " FROM "
        assert sql.count(verb + " CREATE ON SCHEMA ops" + suffix + migration._COMMAND_OWNER) == int(
            not create
        )
    settings_calls = [params for statement, params in bind.calls if "set_config" in statement]
    assert settings_calls[:2] == [
        {"name": "lock_timeout", "value": str(min(prior, 1000) if prior else 1000)},
        {"name": "statement_timeout", "value": str(min(prior, 30000) if prior else 30000)},
    ]
    assert settings_calls[-2:] == [
        {"name": "lock_timeout", "value": str(prior)},
        {"name": "statement_timeout", "value": str(prior)},
    ]
    assert sql[-1] == "SET ROLE ktm_feature_schema_owner"


def test_new_public_surface_is_versioned_without_changing_frozen_expired_reset_acl():
    name = "ops.reset_ready_provider_snapshot_plan"
    signature = name + "(uuid,bigint,uuid,uuid,uuid,text)"
    assert migration.revision == "433_snapshot_ready_plan_reset"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "432_rest_snapshot_atomic"
    assert acl._OPTIONAL_ROUTINES[name] == migration.revision
    assert (
        signature
        in db._EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS["ktm_feature_service"]
    )
    functions = {name: acl._ResolvedRoutine("FUNCTION", "uuid, bigint, uuid, uuid, uuid, text")}
    rendered = [
        acl._render_acl_statement(statement, functions)
        for statement in acl._SNAPSHOT_READY_RESET_COMMAND_OWNER_ACL
    ]
    assert all(statement is not None for statement in rendered)

    def normalized(value):
        return "".join(value.split())

    frozen = migration._UPGRADE_STATEMENTS[2:4]
    assert [normalized(statement) for statement in rendered] == [
        normalized(statement) for statement in frozen
    ]
    assert not any(name in statement for statement in acl._SNAPSHOT_COMMAND_OWNER_ACL)
    assert migration._SCOPE_OWNER_READ_SQL in " ".join(acl._SNAPSHOT_READY_RESET_SCOPE_OWNER_ACL)
    assert "to_regprocedure" in " ".join(acl._SNAPSHOT_READY_RESET_SCOPE_OWNER_ACL)
    assert migration._SCOPE_OWNER_READ_SQL in migration._UPGRADE_STATEMENTS

    assert "'433_snapshot_ready_plan_reset'" in migration._RECEIPT_HEAD_CHECK_SQL
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()


def _input():
    token = SnapshotExecutorToken(uuid4(), 3, uuid4())
    plan = SimpleNamespace(attempt_id=uuid4(), owner=uuid4(), manifest_digest="a" * 64)
    observed = SimpleNamespace(
        snapshot_id=token.snapshot_id, status="prepared", kernel_binding=plan
    )
    return token, plan, observed


@pytest.mark.parametrize("kind", ["airport", "rest"])
@pytest.mark.parametrize("unbound_after_reset", [False, True])
async def test_client_resets_original_apply_plan_once_and_commits_before_return(
    kind, unbound_after_reset
):
    module = _airport_snapshot if kind == "airport" else _rest_snapshot
    client, session, calls = _client()
    token, plan, observed = _input()
    if unbound_after_reset:
        observed.kernel_binding = None
    expected = "needs_read" if unbound_after_reset else "reset"
    session.scalar = AsyncMock(return_value=expected)
    result = await getattr(module, f"reset_rolled_back_{kind}_snapshot_plan")(
        client, observed, token, plan
    )
    assert result == expected
    assert calls == [True]
    assert session.events == ["session:enter", "tx:enter", "tx:ok", "session:ok"]
    session.scalar.assert_awaited_once()
    statement, params = session.scalar.await_args.args
    assert "ops.reset_ready_provider_snapshot_plan" in str(statement)
    assert params == {
        "snapshot": token.snapshot_id,
        "generation": token.generation,
        "fence": token.fence,
        "attempt": plan.attempt_id,
        "owner": plan.owner,
        "manifest": plan.manifest_digest,
    }


@pytest.mark.parametrize("kind", ["airport", "rest"])
@pytest.mark.parametrize("broken", ["snapshot", "status", "attempt_id", "owner", "manifest_digest"])
async def test_client_foreign_fresh_binding_never_opens_reset_transaction(kind, broken):
    module = _airport_snapshot if kind == "airport" else _rest_snapshot
    client, session, calls = _client()
    token, plan, observed = _input()
    if broken == "snapshot":
        observed.snapshot_id = uuid4()
    elif broken == "status":
        observed.status = "applied"
    else:
        values = dict(vars(plan))
        values[broken] = "b" * 64 if broken == "manifest_digest" else uuid4()
        observed.kernel_binding = SimpleNamespace(**values)
    with pytest.raises(ValueError, match="prepared snapshot|binding changed"):
        await getattr(module, f"reset_rolled_back_{kind}_snapshot_plan")(
            client, observed, token, plan
        )
    assert calls == []
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("kind", ["airport", "rest"])
async def test_client_reset_commit_response_loss_is_not_success_or_retry(kind):
    module = _airport_snapshot if kind == "airport" else _rest_snapshot
    client, session, calls = _client()
    token, plan, observed = _input()
    error = OSError("reset commit acknowledgement lost")
    session.commit_error = error
    session.scalar = AsyncMock(return_value="reset")
    with pytest.raises(OSError, match="reset commit acknowledgement lost") as caught:
        await getattr(module, f"reset_rolled_back_{kind}_snapshot_plan")(
            client, observed, token, plan
        )
    assert caught.value is error
    assert calls == [True]
    session.scalar.assert_awaited_once()
