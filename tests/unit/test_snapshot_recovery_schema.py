"""430 배선 source/owner/ACL 정본. 실제 SQL 설치·head oracle 수용은 별도다."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from kortravelmap.infra import db, models
from kortravelmap.infra import runtime_privileges as acl

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_snapshot430", _ROOT / "alembic/versions/430_provider_snapshot_recovery.py"
)
assert _spec is not None
assert _spec.loader is not None
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


class _Settings:
    def all(self):
        return [("lock_timeout", "25"), ("statement_timeout", "750")]


class _Bind:
    def __init__(self, create):
        self.create = create
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _Settings()

    def scalar(self, statement, params):
        assert "has_schema_privilege" in str(statement)
        return self.create[params["owner"], params["schema"]]


@pytest.mark.parametrize("mode", ["none", "all", "mixed"])
def test_actual_upgrade_keeps_owner_windows_short_caps_and_create_state(monkeypatch, mode):
    states = {
        pair: mode == "all" or (mode == "mixed" and pair[1] == "ops")
        for pair in migration._CREATE_WINDOWS
    }
    bind = _Bind(states)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    migration.upgrade()
    sql = [statement for statement, _ in bind.calls]
    protocol = sql.index("SELECT ops.lock_scoped_feature_write_protocol(true)")
    first_table = next(i for i, statement in enumerate(sql) if "CREATE TABLE" in statement)
    assert protocol < first_table
    for (owner, schema), had_create in states.items():
        assert sql.count("GRANT CREATE ON SCHEMA " + schema + " TO " + owner) == int(not had_create)
        assert sql.count("REVOKE CREATE ON SCHEMA " + schema + " FROM " + owner) == int(
            not had_create
        )
    assert [params for statement, params in bind.calls if "set_config" in statement][-2:] == [
        {"name": "lock_timeout", "value": "25"},
        {"name": "statement_timeout", "value": "750"},
    ]
    assert sql[-1] == "SET ROLE ktm_feature_schema_owner"
    owners = {name: owner for _, rows in migration._SIDECARS for name, _, _, owner, _, _ in rows}
    role = None
    observed = []
    for statement in sql:
        if statement.startswith("SET ROLE "):
            role = statement.removeprefix("SET ROLE ")
        for match in migration._CREATE.finditer(statement):
            assert role == owners[match[2]]
            observed.append(match[2])
    assert set(observed) == set(owners)
    assert len(observed) == len(owners)


def test_sidecar_sections_rejoin_exact_bytes_and_existing_routine_owners_match_oracle():
    oracle = (_ROOT / "alembic/head-schema.sql").read_text()
    for filename, rows in migration._SIDECARS:
        chunks = migration._sections(filename, rows)
        assert (
            "".join(body for _, body in chunks)
            == (_ROOT / "alembic/versions" / filename).read_text()
        )
        for name, kind, _, owner, newly_created, _ in rows:
            if not newly_created:
                pattern = (
                    r"-- Name: "
                    + re.escape(name.split(".")[1])
                    + r"\([^\n]*?; Type: "
                    + kind
                    + r"; Schema: "
                    + name.split(".")[0]
                    + r"; Owner: ([^\n]+)"
                )
                found = re.search(pattern, oracle)
                assert found is not None
                assert found[1] == owner


def _normalized(sql):
    return re.sub(r"\s+", "", sql)


def test_frozen_migration_acl_matches_current_catalog_rendered_inventory():
    signatures = {
        name: acl._ResolvedRoutine(kind, signature[1:-1].replace(",", ", "))
        for _, rows in migration._SIDECARS
        for name, kind, signature, _, _, _ in rows
    }
    signatures.update(
        {
            "feature._install_strict_sh_data_guards": acl._ResolvedRoutine("FUNCTION", ""),
            "ops._arm_scoped_feature_write_deadline": acl._ResolvedRoutine("FUNCTION", ""),
            "ops.cancel_scoped_feature_write": acl._ResolvedRoutine("FUNCTION", "uuid, uuid"),
            "feature._bounded_provider_curation_input_set": acl._ResolvedRoutine(
                "FUNCTION", "bigint"
            ),
        }
    )
    current = (
        (migration._SCHEMA_OWNER, acl._SNAPSHOT_SCHEMA_OWNER_ACL),
        (migration._STATE_OWNER, acl._SNAPSHOT_STATE_OWNER_DEPENDENCY_ACL),
        (migration._COMMAND_OWNER, acl._SNAPSHOT_COMMAND_OWNER_ACL),
    )
    for (owner, statements), (frozen_owner, frozen) in zip(
        current, migration._SNAPSHOT_PRIVILEGE_WINDOWS, strict=True
    ):
        assert owner == frozen_owner
        rendered = [acl._render_acl_statement(statement, signatures) for statement in statements]
        assert all(statement is not None for statement in rendered)
        assert [_normalized(statement) for statement in rendered] == [
            _normalized(statement) for statement in frozen
        ]


def test_new_public_sd_and_seal_are_exact_startup_surface_private_helpers_absent():
    public = {
        name + signature
        for _, rows in migration._SIDECARS
        for name, kind, signature, _, new, typed in rows
        if new and typed and kind == "FUNCTION"
    }
    private = {
        name
        for _, rows in migration._SIDECARS
        for name, kind, _, _, new, typed in rows
        if new
        and not typed
        and kind == "FUNCTION"
        and name != "feature._assert_strict_sh_data_guard_inventory"
    }
    expected = db._EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS["ktm_feature_service"]
    assert public <= expected
    assert "feature._assert_strict_sh_data_guard_inventory(boolean)" in expected
    assert not any(signature.split("(")[0] in private for signature in expected)
    assert (
        "ops.seal_provider_snapshot_member(uuid,text,text,bigint,uuid,text,text)"
        in (db._EXPECTED_RUNTIME_APPLICATION_PROCEDURES["ktm_feature_service"])
    )
    for name in public | {
        "ops.seal_provider_snapshot_member(uuid,text,text,bigint,uuid,text,text)"
    }:
        assert acl._OPTIONAL_ROUTINES[name.split("(")[0]] == migration.revision


@pytest.mark.parametrize(
    "relation",
    [
        "provider_snapshot_artifacts",
        "provider_snapshot_controls",
        "provider_snapshot_quota_limits",
        "provider_snapshot_quota_reservations",
    ],
)
def test_private_tables_have_mapped_constraints_and_runtime_no_raw_grants(relation):
    table = models.Base.metadata.tables["ops." + relation]
    assert table.primary_key.columns
    assert acl._OPS_TABLE_PRIVILEGES[relation] == ()
    rendered = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "CREATE TABLE ops." + relation in rendered
    assert "PRIMARY KEY" in rendered
    assert any(isinstance(constraint, CheckConstraint) for constraint in table.constraints)


def test_explicit_first_profile_quota_and_generated_hashes_preserved():
    artifacts = models.ProviderSnapshotArtifactRow.__table__
    controls = models.ProviderSnapshotControlRow.__table__
    quotas = models.ProviderSnapshotQuotaLimitRow.__table__
    for table, names in (
        (artifacts, ("artifact_sha256", "context_sha256")),
        (controls, ("result_sha256",)),
    ):
        for name in names:
            assert table.c[name].computed is not None
            assert table.c[name].computed.persisted is True
    assert all(quotas.c[name].server_default is None for name in ("max_bytes", "max_rows"))
    assert quotas.c.quota_key.autoincrement is False
    checks = " ".join(
        str(c.sqltext) for c in controls.constraints if isinstance(c, CheckConstraint)
    )
    assert "applied_generation<=executor_generation" in checks
    assert "seal_txid IS NULL" in checks


def test_forward_revision_receipt_and_no_automatic_policy_activation():
    assert migration.revision == "430_provider_snapshot_recovery"
    assert len(migration.revision) <= 32
    assert migration.down_revision == "429_strict_sh_data_guards"
    assert "'430_provider_snapshot_recovery'" in migration._RECEIPT_HEAD_CHECK_SQL
    assert migration._RECEIPT_HEAD_CHECK_SQL in migration._UPGRADE_STATEMENTS
    statements = migration._UPGRADE_STATEMENTS
    assert not any(
        re.match(r"\s*(?:SELECT|CALL|DO).*_install_strict_sh_data_guards", sql)
        for sql in statements
        if "GRANT EXECUTE" not in sql
    )
    assert migration._GLOBAL_QUOTA_BYTES == 16 * 1024 * 1024
    assert migration._GLOBAL_QUOTA_ROWS == 256
    assert migration._AIRPORT_QUOTA_BYTES == 4 * 1024 * 1024
    assert migration._AIRPORT_QUOTA_ROWS == 64
    seeds = [
        sql
        for sql in statements
        if sql.startswith("INSERT INTO ops.provider_snapshot_quota_limits")
    ]
    assert seeds == list(migration._QUOTA_STATEMENTS)
    assert len(seeds) == 2
    assert "VALUES(0,16777216,256)" in seeds[0]
    assert "SELECT provider_dataset_id,4194304,64" in seeds[1]
    assert "provider='kor-travel-transport'" in seeds[1]
    assert "dataset_key='transport_airports' AND is_active" in seeds[1]
    assert "ON CONFLICT" not in " ".join(seeds)
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()


def test_inventory_validator_reuses_exact_installer_tail_without_installing():
    original = (_ROOT / "alembic/versions/_429_install_strict_sh_data_guards.sql").read_text()
    validator = (_ROOT / "alembic/versions/_430_snapshot_guard_inventory.sql").read_text()
    tail = original[original.index("    -- 기존 이름과 부딪히면") : original.index("END;\n$$;")]
    assert tail in validator
    assert "CREATE TRIGGER" not in validator
    assert "LOCK TABLE" not in validator
    assert "RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER" in validator
    assert "feature._assert_strict_sh_data_guard_inventory(false)" in str(
        db._RUNTIME_STRICT_GUARD_INVENTORY_SQL
    )
    assert "NOT EXISTS(SELECT 1 FROM feature.provider_field_active_policies)" in validator
    assert "p_require_all boolean DEFAULT true" in validator
    assert "IF p_require_all IS NULL" in validator
    assert "NOT EXISTS(SELECT 1 FROM pg_trigger" in validator


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("can_access_provider_snapshot_private_relations", True, "private provider snapshot"),
        ("can_access_provider_snapshot_private_relations", None, "private provider snapshot"),
        ("strict_data_guard_inventory_valid", False, "strict data guard inventory"),
        ("strict_data_guard_inventory_valid", None, "strict data guard inventory"),
    ],
)
def test_startup_refuses_snapshot_raw_access_and_incomplete_guard_inventory(field, value, message):
    from tests.unit.test_db import _runtime_privilege_row

    row = _runtime_privilege_row()
    assert db._runtime_db_privilege_problems(row, expected_login="ktm_feature_service") == []
    row[field] = value
    assert any(
        message in problem
        for problem in db._runtime_db_privilege_problems(row, expected_login="ktm_feature_service")
    )


def test_fixed_sql_sidecars_do_not_create_sqlalchemy_literal_bind_parameters():
    from sqlalchemy import text

    for filename, rows in migration._SIDECARS:
        for _, body in migration._sections(filename, rows):
            assert not text(body)._bindparams, filename


@pytest.mark.parametrize(
    ("head_matches", "guard", "error"),
    [(True, True, False), (True, False, True), (False, True, True)],
)
async def test_actual_startup_uses_readonly_inventory_only_after_exact_head(
    head_matches, guard, error
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from tests.unit.test_db import _runtime_privilege_row

    row = _runtime_privilege_row()
    if not head_matches:
        row["applied_alembic_heads"] = ["429_strict_sh_data_guards"]
    result = SimpleNamespace(mappings=lambda: SimpleNamespace(one_or_none=lambda: row))
    connection = SimpleNamespace(
        execute=AsyncMock(return_value=result), scalar=AsyncMock(return_value=guard)
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=connection)
    context.__aexit__ = AsyncMock(return_value=False)
    engine = SimpleNamespace(connect=lambda: context)
    if error:
        with pytest.raises(db.RuntimeDbPrivilegeBoundaryError):
            await db.assert_runtime_db_privilege_boundary(
                engine, expected_login="ktm_feature_service"
            )
    else:
        await db.assert_runtime_db_privilege_boundary(engine, expected_login="ktm_feature_service")
    assert connection.scalar.await_count == int(head_matches)
    if head_matches:
        assert connection.scalar.await_args.args == (db._RUNTIME_STRICT_GUARD_INVENTORY_SQL,)
    assert context.__aexit__.await_count == 1


def test_asyncpg_receives_single_top_level_ddl_without_splitting_function_bodies():
    sql = (
        "CREATE TABLE a(id int); CREATE FUNCTION f() RETURNS void AS $body$ "
        "BEGIN PERFORM 1; END; $body$ LANGUAGE plpgsql; -- trailing comment"
    )
    commands = migration._top_level_statements(sql)
    assert len(commands) == 2
    assert "BEGIN PERFORM 1; END;" in commands[1]
    assert migration._top_level_statements("SELECT 'a;b'; SELECT 'it''s;ok';") == (
        "SELECT 'a;b';",
        "SELECT 'it''s;ok';",
    )
    for filename, rows in migration._SIDECARS:
        for _, body in migration._sections(filename, rows):
            for command in migration._top_level_statements(body):
                assert migration._top_level_statements(command) == (command,)
    storage = next(
        body
        for owner, body in migration._sections(*migration._SIDECARS[0])
        if "CREATE TABLE" in body
    )
    assert len(migration._top_level_statements(storage)) == 2
