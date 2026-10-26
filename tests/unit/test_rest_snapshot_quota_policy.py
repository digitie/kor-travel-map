"""Rest의 명시 logical quota 정책과 실제 migration 소유자 경계를 고정한다."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_snapshot432_quota", _ROOT / "alembic/versions/432_rest_snapshot_atomic.py"
)
assert _spec is not None
assert _spec.loader is not None
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


class _Settings:
    def all(self):
        return [("lock_timeout", "25"), ("statement_timeout", "750")]


class _Bind:
    def __init__(self, had_create):
        self.had_create = had_create
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _Settings()

    def scalar(self, statement, params):
        assert "has_schema_privilege" in str(statement)
        assert params == {"owner": "ktm_curation_command_owner"}
        return self.had_create


@pytest.mark.parametrize("had_create", [False, True])
def test_actual_upgrade_seeds_only_rest_once_as_schema_owner_and_restores_caps(
    monkeypatch, had_create
):
    bind = _Bind(had_create)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    migration.upgrade()
    statements = [sql for sql, _ in bind.calls]
    quota_index = statements.index(migration._REST_QUOTA_SQL)
    assert statements.count(migration._REST_QUOTA_SQL) == 1
    assert statements[quota_index - 1] == "SET ROLE ktm_feature_schema_owner"
    assert statements[quota_index + 1] == migration._RECEIPT_HEAD_CHECK_SQL
    assert statements.index("SELECT ops.lock_scoped_feature_write_protocol(true)") < quota_index
    assert [params for sql, params in bind.calls if "set_config" in sql][-2:] == [
        {"name": "lock_timeout", "value": "25"},
        {"name": "statement_timeout", "value": "750"},
    ]
    assert statements.count("GRANT CREATE ON SCHEMA ops TO ktm_curation_command_owner") == int(
        not had_create
    )
    assert statements.count("REVOKE CREATE ON SCHEMA ops FROM ktm_curation_command_owner") == int(
        not had_create
    )
    assert statements[-1] == "SET ROLE ktm_feature_schema_owner"


def test_quota_seed_has_no_default_upsert_or_existing_usage_reset():
    sql = migration._REST_QUOTA_SQL
    assert migration._REST_QUOTA_BYTES == 8388608
    assert migration._REST_QUOTA_ROWS == 16
    assert "SELECT provider_dataset_id,8388608,16 FROM provider_sync.provider_datasets" in sql
    assert "provider='kor-travel-transport'" in sql
    assert "dataset_key='transport_rest_areas' AND is_active" in sql
    assert sql.count("INSERT INTO") == 1
    for forbidden in ("ON CONFLICT", "UPDATE ", "DELETE ", "used_bytes", "used_rows", "VALUES(0"):
        assert forbidden not in sql
    assert "transport_airports" not in sql
    assert migration._UPGRADE_STATEMENTS.count(sql) == 1
