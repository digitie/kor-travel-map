"""capture 이전 의존 정의 확인·쓰기 진입 순서·caller cap 복원을 검증한다."""

import hashlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = spec_from_file_location(
    "_test_428", _ROOT / "alembic/versions/428_bounded_curation_capture.py"
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


class _Bind:
    def __init__(self, prior, drift=None):
        self.prior = prior
        self.drift = drift
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if "SELECT name,setting FROM pg_settings" in sql:
            return _Rows(list(zip(("lock_timeout", "statement_timeout"), self.prior, strict=True)))
        if "SELECT p.proname,p.prosrc" in sql:
            rows = [
                [
                    "current_provider_curation_input_set",
                    "canonical",
                    True,
                    "s",
                    ["search_path=pg_catalog, feature, provider_sync, ops, x_extension"],
                    "ktm_feature_schema_owner",
                    "f",
                ],
                [
                    "_heritage_evidence_metadata_bytes",
                    "metadata",
                    False,
                    "i",
                    ["search_path=pg_catalog"],
                    "ktm_feature_state_procedure_owner",
                    "f",
                ],
            ]
            if self.drift:
                row, column = self.drift
                rows[row][column] = "changed-definition"
            return _Rows(rows)
        return _Rows([])


def _install_fake(monkeypatch, bind):
    monkeypatch.setattr(_migration.op, "get_bind", lambda: bind)
    for key, body in [("CANONICAL", b"canonical"), ("METADATA", b"metadata")]:
        monkeypatch.setattr(
            _migration, f"_EXPECTED_{key}_BODY_SHA256", hashlib.sha256(body).hexdigest()
        )


@pytest.mark.parametrize(
    ("prior", "capped"),
    [
        (("0", "0"), ("1000", "30000")),
        (("25", "750"), ("25", "750")),
        (("5000", "100000"), ("1000", "30000")),
        (("25", "0"), ("25", "30000")),
    ],
)
def test_upgrade_caps_before_protocol_and_restores_exact_caller_settings(
    monkeypatch, prior, capped
):
    bind = _Bind(prior)
    _install_fake(monkeypatch, bind)
    _migration.upgrade()
    statements = [sql for sql, _ in bind.statements]
    gate = statements.index("SELECT ops.lock_scoped_feature_write_protocol(true)")
    dependency = next(i for i, sql in enumerate(statements) if "SELECT p.proname,p.prosrc" in sql)
    first_ddl = next(i for i, sql in enumerate(statements) if sql.startswith(("GRANT", "CREATE")))
    assert gate < dependency < first_ddl
    settings = [params["value"] for sql, params in bind.statements if "set_config" in sql]
    assert settings == list(capped + prior)
    assert statements[-1] == "SET ROLE ktm_feature_schema_owner"
    assert not any("CREATE ON SCHEMA" in sql for sql in statements)


@pytest.mark.parametrize("routine", [0, 1])
@pytest.mark.parametrize("column", [1, 2, 3, 4, 5, 6])
def test_dependency_drift_is_rejected_before_any_grant_or_definition(monkeypatch, routine, column):
    bind = _Bind(("0", "0"), (routine, column))
    _install_fake(monkeypatch, bind)
    with pytest.raises(RuntimeError, match="dependency definition changed"):
        _migration.upgrade()
    assert not any(sql.startswith(("GRANT", "CREATE")) for sql, _ in bind.statements)


def test_canonical_acl_uses_schema_owner_for_schema_owned_capture_functions():
    from kortravelmap.infra.runtime_privileges import _ACL_ROLE_WINDOWS

    seen = []
    for role, statements in _ACL_ROLE_WINDOWS:
        for statement in statements:
            if statement.startswith(
                (
                    "REVOKE ALL ON FUNCTION feature._bounded_",
                    "GRANT EXECUTE ON FUNCTION feature._bounded_",
                )
            ):
                assert role == "ktm_feature_schema_owner"
                seen.append(statement)
    assert len(seen) == 3
