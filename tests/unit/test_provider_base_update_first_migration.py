"""기존 procedure 정의·CREATE 권한·짧은 caller cap을 보존한다."""

import hashlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = spec_from_file_location(
    "_test_425", _ROOT / "alembic/versions/425_provider_base_update_first.py"
)
assert _spec is not None
assert _spec.loader is not None
_migration = module_from_spec(_spec)
_spec.loader.exec_module(_migration)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def mappings(self):
        return self


class _Bind:
    def __init__(self, has_create, drift=None):
        self.has_create = has_create
        self.drift = drift
        self.statements = []

    def scalar(self, statement):
        assert "has_schema_privilege" in str(statement)
        return self.has_create

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if "SELECT name,setting FROM pg_settings" in sql:
            return _Rows([("lock_timeout", "25"), ("statement_timeout", "750")])
        if "SELECT p.prosrc AS body" in sql:
            body = "parent-catalog-body-fixture"
            row = dict(
                body=body,
                argument_names=_migration._EXPECTED_ARGUMENT_NAMES,
                argument_modes=["i"] * 7 + ["o"] * 3,
                argument_types=_migration._EXPECTED_ARGUMENT_TYPES,
                owner="ktm_feature_state_procedure_owner",
                kind="p",
                prosecdef=True,
                language="plpgsql",
                volatility="v",
                proconfig=["search_path=pg_catalog"],
            )
            if self.drift is not None:
                row[self.drift] = "definition-drift"
            return _Rows([row])
        return _Rows([])


@pytest.mark.parametrize("has_create", [False, True])
def test_upgrade_preserves_effective_create_and_shorter_caller_caps(monkeypatch, has_create):
    bind = _Bind(has_create)
    monkeypatch.setattr(_migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(
        _migration,
        "_EXPECTED_BODY_SHA256",
        hashlib.sha256(b"parent-catalog-body-fixture").hexdigest(),
    )
    _migration.upgrade()
    statements = [sql for sql, _ in bind.statements]
    for verb in ["GRANT", "REVOKE"]:
        assert statements.count(
            f"{verb} CREATE ON SCHEMA feature "
            f"{'TO' if verb == 'GRANT' else 'FROM'} ktm_feature_state_procedure_owner"
        ) == int(not has_create)
    assert len([sql for sql in statements if sql.startswith("CREATE OR REPLACE PROCEDURE")]) == 1
    restored = [params for sql, params in bind.statements if "set_config" in sql][-2:]
    assert restored == [
        {"name": "lock_timeout", "value": "25"},
        {"name": "statement_timeout", "value": "750"},
    ]
    assert statements[-1] == "SET ROLE ktm_feature_schema_owner"


@pytest.mark.parametrize("drift", ["body", "argument_types", "owner"])
def test_definition_drift_fails_before_create_grant_or_replacement(monkeypatch, drift):
    bind = _Bind(False, drift)
    monkeypatch.setattr(_migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(
        _migration,
        "_EXPECTED_BODY_SHA256",
        hashlib.sha256(b"parent-catalog-body-fixture").hexdigest(),
    )
    with pytest.raises(RuntimeError):
        _migration.upgrade()
    assert not any(sql.startswith(("GRANT", "CREATE OR REPLACE")) for sql, _ in bind.statements)
