"""상속을 포함한 기존 CREATE 권한이 새 direct GRANT로 바뀌지 않게 한다."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = spec_from_file_location(
    "_test_423_acl", _ROOT / "alembic/versions/423_exclusive_context_select.py"
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
    def __init__(self, has_create):
        self.has_create = has_create
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
            old = (_ROOT / "alembic/versions/_420_exclusive_refresh_context.sql").read_text()
            return _Rows(
                [
                    dict(
                        body=old.split("$$")[1],
                        signature="p_feature uuid, p_dataset bigint",
                        owner="ktm_feature_state_procedure_owner",
                        kind="f",
                        prosecdef=True,
                        language="plpgsql",
                        volatility="v",
                        proconfig=["search_path=pg_catalog"],
                        result="boolean",
                    )
                ]
            )
        return _Rows([])


@pytest.mark.parametrize("has_create", [False, True])
def test_upgrade_preserves_effective_create_without_adding_inherited_direct_grant(
    monkeypatch, has_create
):
    bind = _Bind(has_create)
    monkeypatch.setattr(_migration.op, "get_bind", lambda: bind)
    _migration.upgrade()
    statements = [statement for statement, _ in bind.statements]
    grant = "GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner"
    revoke = "REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner"
    assert statements.count(grant) == int(not has_create)
    assert statements.count(revoke) == int(not has_create)
    assert (
        len([statement for statement in statements if statement.startswith("CREATE OR REPLACE")])
        == 1
    )
    restored = [params for statement, params in bind.statements if "set_config" in statement][-2:]
    assert restored == [
        {"name": "lock_timeout", "value": "25"},
        {"name": "statement_timeout", "value": "750"},
    ]
    assert statements[-1] == "SET ROLE ktm_feature_schema_owner"
