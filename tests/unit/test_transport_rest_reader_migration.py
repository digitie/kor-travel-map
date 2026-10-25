"""새 reader 설치가 기존 권한과 짧은 caller timeout을 보존하는지 확인한다."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = spec_from_file_location(
    "_rest_reader_migration", _ROOT / "alembic/versions/431_transport_rest_reader.py"
)
assert _spec is not None
assert _spec.loader is not None
_migration = module_from_spec(_spec)
_spec.loader.exec_module(_migration)


class _Rows:
    def all(self):
        return [("lock_timeout", "25"), ("statement_timeout", "750")]


class _Bind:
    def __init__(self, has_create):
        self.has_create = has_create
        self.statements = []

    def scalar(self, statement):
        assert "has_schema_privilege" in str(statement)
        return self.has_create

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return _Rows()


@pytest.mark.parametrize("has_create", [False, True])
def test_install_preserves_create_acl_and_shorter_timeout(monkeypatch, has_create):
    bind = _Bind(has_create)
    monkeypatch.setattr(_migration.op, "get_bind", lambda: bind)
    _migration.upgrade()
    statements = [sql for sql, _ in bind.statements]
    lock = statements.index("SELECT ops.lock_scoped_feature_write_protocol(true)")
    creates = [
        i
        for i, sql in enumerate(statements)
        if next(
            (
                line.strip()
                for line in sql.splitlines()
                if line.strip() and not line.lstrip().startswith("--")
            ),
            "",
        ).startswith("CREATE FUNCTION")
    ]
    assert len(creates) == 3
    assert lock < min(creates)
    for verb, direction in [("GRANT", "TO"), ("REVOKE", "FROM")]:
        assert statements.count(
            f"{verb} CREATE ON SCHEMA feature {direction} ktm_feature_state_procedure_owner"
        ) == int(not has_create)
    assert [params for sql, params in bind.statements if "set_config" in sql][-2:] == [
        {"name": "lock_timeout", "value": "25"},
        {"name": "statement_timeout", "value": "750"},
    ]
    assert statements[-1] == "SET ROLE ktm_feature_schema_owner"
    public_grants = [sql for sql in statements if sql.startswith("GRANT EXECUTE")]
    assert public_grants == [
        "GRANT EXECUTE ON FUNCTION feature.read_transport_rest_snapshot_evidence(bigint) "
        "TO ktm_feature_runtime"
    ]
    assert not any("GRANT SELECT" in sql for sql in statements)


def test_linear_revision_and_receipt_do_not_replace_history():
    assert _migration.revision == "431_transport_rest_reader"
    assert len(_migration.revision.encode("ascii")) <= 32
    assert _migration.down_revision == "430_provider_snapshot_recovery"
    assert "'430_provider_snapshot_recovery'" in _migration._RECEIPT_HEAD_CHECK_SQL
    assert "'431_transport_rest_reader'" in _migration._RECEIPT_HEAD_CHECK_SQL
    with pytest.raises(RuntimeError, match="forward-only"):
        _migration.downgrade()


def test_every_variable_column_matches_the_reviewable_inventory():
    import json
    import re

    inventory = json.loads(
        (_ROOT / "docs/reports/2026-10-25-rest-reader-column-inventory.json").read_text()
    )["가변열"]
    sql = (_ROOT / "alembic/versions/_431_transport_rest_evidence_inventory.sql").read_text()
    pattern = re.compile(
        r"feature\._heritage_evidence_metadata_bytes\(ARRAY\[(.*?)\]::bigint\[\],"
        r"ARRAY\[(.*?)\]::boolean\[\],ARRAY\[(.*?)\]::integer\[\],"
        r"ARRAY\[(.*?)\]::boolean\[\]\) AS bytes\s+FROM ([a-z_]+\.[a-z_]+) t",
        re.S,
    )
    actual = {}
    for sizes, compressions, caps, nulls, relation in pattern.findall(sql):
        columns = re.findall(r"pg_column_size\(t\.([a-z_]+)\)", sizes)
        compressed_columns = re.findall(r"pg_column_compression\(t\.([a-z_]+)\)", compressions)
        cap_values = [int(value) for value in caps.split(",")]
        null_values = [value.strip() == "true" for value in nulls.split(",")]
        assert columns == compressed_columns
        assert len(columns) == len(cap_values) == len(null_values)
        values = {
            column: {
                "physical_cap": cap,
                "sql_null_allowed": nullable,
                "compression_allowed": False,
            }
            for column, cap, nullable in zip(columns, cap_values, null_values, strict=True)
        }
        if relation in actual:
            assert actual[relation] == values
        actual[relation] = values
    assert actual == inventory
    assert sum(len(columns) for columns in actual.values()) == 51


def test_existing_case_indexes_are_reused_without_new_index_or_raw_privilege(monkeypatch):
    bind = _Bind(False)
    monkeypatch.setattr(_migration.op, "get_bind", lambda: bind)
    _migration.upgrade()
    statements = [sql for sql, _ in bind.statements]
    assert not any(sql.startswith("CREATE INDEX") for sql in statements)
    assert not any("GRANT SELECT" in sql for sql in statements)
    sql = (_ROOT / "alembic/versions/_431_transport_rest_evidence_inventory.sql").read_text()
    assert sql.count("(CASE WHEN pg_catalog.octet_length(t.") == 4
    assert "v_total>4194304" in sql
    assert "FROM feature.feature_areas t WHERE t.feature_id=ANY(v_features)" in sql


def test_typed_runtime_signature_acl_and_private_helpers_are_exact():
    from kortravelmap.infra import runtime_privileges as privileges
    from kortravelmap.infra.db import _EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS

    public = "feature.read_transport_rest_snapshot_evidence"
    private = {
        "feature._transport_rest_evidence_shape",
        "feature._transport_rest_evidence_inventory",
    }
    signatures = _EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS["ktm_feature_service"]
    assert public + "(bigint)" in signatures
    assert not any(name + "(" in signature for name in private for signature in signatures)
    for name in private | {public}:
        assert privileges._OPTIONAL_ROUTINES[name] == "431_transport_rest_reader"
    grants = []
    for role, statements in privileges._ACL_ROLE_WINDOWS:
        for sql in statements:
            if any(name + "(" in sql for name in private | {public}):
                assert role == "ktm_feature_state_procedure_owner"
                grants.append(sql)
    assert grants == [
        "REVOKE ALL ON FUNCTION feature._transport_rest_evidence_shape(...) "
        "FROM PUBLIC,ktm_feature_runtime",
        "REVOKE ALL ON FUNCTION feature._transport_rest_evidence_inventory(...) "
        "FROM PUBLIC,ktm_feature_runtime",
        "REVOKE ALL ON FUNCTION feature.read_transport_rest_snapshot_evidence(...) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION feature.read_transport_rest_snapshot_evidence(...) "
        "TO ktm_feature_runtime",
    ]


def test_scalar_lineages_and_non_scalar_fields_are_distinct_before_encoding():
    sql = (_ROOT / "alembic/versions/_431_read_transport_rest_evidence.sql").read_text()
    assert "mixed_scalar_lineage" in sql
    assert (
        "v_phones->'value_source_record_key' IS DISTINCT FROM "
        "v_candidate->'value_source_record_key'"
        in sql
    )
    assert sql.index("mixed_scalar_lineage") < sql.index("v_item:=jsonb_build_object")
    assert "jsonb_array_length(v_base_rows)<>23" in sql
    assert "v_count<>25" in sql
    assert "'phones_base',v_phones_base" in sql
    assert "'phones_value_record',v_phones_record" in sql
    assert "v_scope_count>256" in sql
    assert "LIMIT 257" in sql
    assert "v_bytes>4190000" in sql
    assert "))>4194304" in sql
