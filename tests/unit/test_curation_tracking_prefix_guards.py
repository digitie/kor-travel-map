"""430 tracking source의 owner/분류/순서 경계. 실제 트리거·paired PG 수용은 별도다."""

from pathlib import Path

import pytest

from tests.unit.test_curation_activation_parent_order import _definition

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "alembic/versions/_430_tracking_prefix_guards.sql"
_NAMES = (
    "ops.reject_provider_feature_operation_raw_dml",
    "ops.reject_provider_feature_membership_raw_dml",
    "ops.reject_provider_feature_event_raw_dml",
)


@pytest.mark.parametrize("name", _NAMES)
def test_held_check_precedes_typed_owner_short_circuit(name: str) -> None:
    definition = _definition(SQL.read_text(), name)
    assert definition.index("IF v_provider THEN") < definition.index(
        "current_user = 'ktm_curation_command_owner'"
    )
    assert definition.index("ck_provider_tracking_write_prefix") < definition.index(
        "current_user = 'ktm_curation_command_owner'"
    )
    assert "SECURITY DEFINER" not in definition
    assert "pg_advisory_xact_lock" not in definition
    assert "FOR UPDATE" not in definition
    assert "set_config" not in definition
    assert "database=(SELECT oid" in definition
    assert "classid=1369104691 AND objid=115 AND objsubid=2" in definition
    assert "classid=1590807301 AND objid=1746797985 AND objsubid=1" in definition
    assert "v_protocol_held AND NOT v_protocol_exclusive" in definition


@pytest.mark.parametrize("name", _NAMES[:2])
def test_existing_owner_and_typed_authorization_tail_is_whole_exact(name: str) -> None:
    original = _definition((ROOT / "alembic/head-schema.sql").read_text(), name)
    actual = _definition(SQL.read_text(), name)
    anchor = "  IF current_user = 'ktm_curation_command_owner'"
    assert actual[actual.index(anchor) :] == original[original.index(anchor) :]


def test_event_old_provider_is_not_reclassified_as_generic() -> None:
    actual = _definition(SQL.read_text(), _NAMES[2])
    assert "WHERE job.job_id=OLD.job_id" in actual
    anchor = "  IF current_user = 'ktm_curation_command_owner'"
    tail = actual[actual.index(anchor) :]
    assert "IF v_provider THEN" in tail
    assert "ck_tvn40_provider_event_typed_command" in tail


def test_terminal_and_membership_event_mutation_modes_are_conservative() -> None:
    sql = SQL.read_text()
    operation = _definition(sql, _NAMES[0])
    assert "NEW.status IN ('done','failed','cancelled')" in operation
    assert "OLD.status IN ('done','failed','cancelled')" in operation
    for name in _NAMES[1:]:
        assert "v_need_final := TG_OP<>'INSERT'" in _definition(sql, name)


def test_dedicated_cancel_statement_targets_are_exact_and_never_acquire_locks() -> None:
    sql = SQL.read_text()
    target = _definition(sql, "ops.reject_pipeline_cancellation_prefix")
    assert "v_need_final boolean:=true" in target
    assert "pg_advisory_xact_lock" not in target
    assert "TG_LEVEL<>'STATEMENT'" in target
    assert sql.count("CREATE TRIGGER trg_00_provider_tracking_protocol") == 3
    for table in (
        "pipeline_cancellations",
        "pipeline_cancellation_members",
        "pipeline_cancellation_runs",
    ):
        assert f"BEFORE INSERT OR UPDATE OR DELETE ON ops.{table} FOR EACH STATEMENT" in sql
