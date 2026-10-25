"""비활성 strict guard 정의/installer 경계. 실제 PG 설치·행 경합 증거는 아니다."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic/versions"
_spec = spec_from_file_location(
    "_strict_guard_migration", _VERSIONS / "429_strict_sh_data_guards.py"
)
assert _spec is not None
assert _spec.loader is not None
_migration = module_from_spec(_spec)
_spec.loader.exec_module(_migration)


class _Rows:
    def all(self):
        return [("lock_timeout", "25"), ("statement_timeout", "750")]


class _Bind:
    def __init__(self, create):
        self.create = create
        self.calls = []

    def scalar(self, statement):
        assert "has_schema_privilege" in str(statement)
        return self.create

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _Rows()


@pytest.mark.parametrize("had_create", [False, True])
def test_definition_only_upgrade_restores_short_caps_and_create_acl(monkeypatch, had_create):
    bind = _Bind(had_create)
    monkeypatch.setattr(_migration.op, "get_bind", lambda: bind)
    _migration.upgrade()
    sql = [value for value, _ in bind.calls]
    protocol = sql.index("SELECT ops.lock_scoped_feature_write_protocol(true)")
    definitions = [
        i for i, value in enumerate(sql) if "CREATE FUNCTION feature._strict_sh_" in value
    ]
    assert len(definitions) == 4
    assert min(definitions) > protocol
    assert not any("SELECT feature._install_strict_sh_data_guards" in value for value in sql)
    assert not any(
        "CREATE TRIGGER" in value and not value.lstrip().startswith("-- 정본 activation")
        for value in sql
    )
    assert sql.count("GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner") == int(
        not had_create
    )
    assert sql.count(
        "REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner"
    ) == int(not had_create)
    assert [params for value, params in bind.calls if "set_config" in value][-2:] == [
        {"name": "lock_timeout", "value": "25"},
        {"name": "statement_timeout", "value": "750"},
    ]
    assert sql[-1] == "SET ROLE ktm_feature_schema_owner"
    assert not any("TO ktm_feature_runtime" in value or "GRANT SELECT" in value for value in sql)


def test_revision_receipt_and_forward_only_preserve_reserved_parent():
    assert _migration.revision == "429_strict_sh_data_guards"
    assert len(_migration.revision.encode("ascii")) <= 32
    assert _migration.down_revision == "428_bounded_curation_capture"
    assert "'428_bounded_curation_capture'" in _migration._RECEIPT_HEAD_CHECK_SQL
    assert "'429_strict_sh_data_guards'" in _migration._RECEIPT_HEAD_CHECK_SQL
    with pytest.raises(RuntimeError, match="forward-only"):
        _migration.downgrade()


def test_prefix_rejects_before_policy_epoch_or_row_lock():
    context = (_VERSIONS / "_429_strict_sh_data_context.sql").read_text()
    assert "FOR UPDATE" not in context
    assert "FOR SHARE" not in context
    assert "txid_current_if_assigned()" in context
    assert "a.status='applying' AND NOT a.exclusive_protocol" in context
    assert "IF p_allow_shared IS NULL" in context
    assert "database=(SELECT oid FROM pg_database WHERE datname=current_database())" in context
    assert "objsubid=2" in context
    assert "LIMIT 2" in context
    assert "lease_until" not in context
    statement = (_VERSIONS / "_429_strict_sh_data_statement_guard.sql").read_text()
    assert statement.index("_strict_sh_data_context") < statement.index(
        "lock_provider_field_policy_epoch"
    )


def test_exact_private_installer_targets_and_statement_order():
    import re

    installer = (_VERSIONS / "_429_install_strict_sh_data_guards.sql").read_text()
    relations = re.search(r"v_relations text\[\]:=ARRAY\[(.*?)\]", installer).group(1)
    values = re.findall(r"'([^']+)'", relations)
    assert len(values) == len(set(values)) == 25
    assert "provider_sync.source_records" in values
    assert not any(value.startswith("ops.feature_write_") for value in values)
    assert "provider_sync.sync_state" not in values
    assert "v_expected integer:=33" in installer
    assert "v_count NOT IN (0,v_expected)" in installer
    assert "v_trigger.tgenabled<>'O'" in installer
    assert "v_trigger.tgtype<>30" in installer
    assert "v_trigger.tgtype<>31" in installer
    assert "convert_to(v_profile,'UTF8')||decode('00','hex')" in installer
    assert installer.index("_strict_sh_data_context(false)") < installer.index("LOCK TABLE")
    snapshot = (_ROOT / "alembic/head-schema.sql").read_text()
    for match in re.finditer(
        r"CREATE TRIGGER ([a-z_0-9]+) BEFORE .*? ON ([a-z_]+\.[a-z_]+) .*?FOR EACH STATEMENT",
        snapshot,
    ):
        if match[2] in values:
            assert match[1] > "trg_00_strict_sh_data_protocol"


def test_source_upsert_identity_check_does_not_compare_first_seen_candidate():
    source = (_VERSIONS / "_429_strict_sh_source_row_guard.sql").read_text()
    assert "NEW.first_seen_at" not in source
    assert "NEW.provider_dataset_id IS DISTINCT FROM v_dataset" in source
    assert "dependency_kind='source_head'" in source
    assert "current_source_record_key" in source
    assert "TG_TABLE_NAME='source_records' AND TG_OP='DELETE'" in source
    assert "to_jsonb" not in source
    assert "row_to_json" not in source


def test_inactive_feature_does_not_bypass_exact_manifest_target():
    source = (_VERSIONS / "_429_strict_sh_feature_row_guard.sql").read_text()
    assert "assert_scoped_candidate_write(v_attempt,v_feature)" in source
    assert "assert_scoped_candidate_write(v_attempt,OLD.feature_id)" in source
    assert "feature.lifecycle_state='active'" in source
    assert "JOIN feature.provider_field_active_policies active USING(feature_id)" in source
    assert "NEW.lifecycle_state IS DISTINCT FROM 'active'" in source
    assert "ck_strict_data_feature_eligibility" in source
    assert "source_role='primary'" in source
    assert "OLD.source_entity_key IS DISTINCT FROM NEW.source_entity_key" in source
