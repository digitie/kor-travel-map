"""430 미호출 finalization 조각의 기존 본문 보존과 client RC 경계."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import kortravelmap.client as client_module
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from tests.unit.test_transaction_limits import _NOW, _client, _stub

_ROOT = Path(__file__).resolve().parents[2]
_SQL = (_ROOT / "alembic/versions/_430_snapshot_finalization.sql").read_text()
_OLD = (_ROOT / "alembic/head-schema.sql").read_text()
_NAMES = (
    "ops.lock_provider_feature_tracking_protocol",
    "feature.seal_provider_curation_snapshot_receipt",
    "feature.finalize_provider_curation_root",
    "feature.purge_manual_feature",
)


def _definition(sql, name):
    found = re.search(
        r"CREATE (?:OR REPLACE )?(FUNCTION|PROCEDURE) " + re.escape(name) + r"\(", sql
    )
    assert found is not None
    tag = re.search(r"\bAS (\$[^$]*\$)", sql[found.start() :])
    assert tag is not None
    start = found.start() + tag.end()
    end = sql.index(tag[1] + ";", start) + len(tag[1]) + 1
    return sql[found.start() : end].replace("CREATE OR REPLACE ", "CREATE ", 1)


@pytest.mark.parametrize("name", _NAMES)
def test_only_declared_rc_prefix_capture_changes(name):
    old = _definition(_OLD, name)
    current = _definition(_SQL, name)
    if name.startswith("ops."):
        addition = """    IF p_finalizing AND current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'provider finalization requires READ COMMITTED transaction'
            USING ERRCODE='25001';
    END IF;
"""  # noqa: E501
        assert current.count(addition) == 1
        current = current.replace(addition, "", 1)
    elif "purge_" in name:
        addition = "    PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
        assert current.count(addition) == 1
        assert current.index(addition) < current.index("SELECT * INTO v_command")
        current = current.replace(addition, "", 1)
    else:
        current = current.replace("<> 'read committed'", "<> 'serializable'")
        current = current.replace(
            "requires READ COMMITTED transaction", "requires SERIALIZABLE transaction"
        )
        if "seal_" in name:
            current = current.replace(
                "feature._member_provider_curation_input_set(\n"
                "    p_root_job_id,p_provider_dataset_id,p_sync_scope,p_operation_key,'child'\n  )",
                "feature.current_provider_curation_input_set(p_provider_dataset_id)",
            )
        else:
            current = current.replace(
                "feature._member_provider_curation_input_set(\n"
                "      p_root_job_id,v_child.provider_dataset_id,v_child.sync_scope,"
                "v_child.operation_key,'root'\n    )",
                "feature.current_provider_curation_input_set(\n"
                "      v_child.provider_dataset_id\n    )",
            )
    assert current == old


@pytest.mark.parametrize("authoritative", [False, True])
async def test_finish_membership_selects_rc_before_repository(monkeypatch, authoritative):
    monkeypatch.setattr(client_module, "repo_finish_dagster_feature_membership", _stub)
    client, factory = _client(monkeypatch)
    await client.finish_dagster_feature_membership(
        dagster_run_id="r",
        membership=ProviderDatasetOperationMembership(1, "dataset_wide", "load"),
        authoritative_snapshot_complete=authoritative,
    )
    (session,) = factory.sessions
    assert session.executed == (
        ["SET TRANSACTION ISOLATION LEVEL READ COMMITTED"] if authoritative else []
    )


@pytest.mark.parametrize("status", ["SUCCESS", "FAILURE"])
async def test_reconcile_selects_rc_only_for_success(monkeypatch, status):
    monkeypatch.setattr(client_module, "repo_reconcile_dagster_feature_run", _stub)
    client, factory = _client(monkeypatch)
    await client.reconcile_dagster_feature_run(
        dagster_run_id="r",
        trigger_kind="schedule",
        terminal_status=status,
        selected_memberships=(),
        operation_key="load",
        engine_created_at=_NOW,
        engine_started_at=None,
        engine_finished_at=_NOW,
        error=None,
    )
    (session,) = factory.sessions
    assert session.executed == (
        ["SET TRANSACTION ISOLATION LEVEL READ COMMITTED"] if status == "SUCCESS" else []
    )
