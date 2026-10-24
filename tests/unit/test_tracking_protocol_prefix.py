"""tracking prefix의 기존 본문 보존·락 키·진입 순서 회귀."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra import feature_operation_repo as operations
from kortravelmap.infra import pipeline_cancellation_repo as cancellation
from kortravelmap.infra.advisory_lock import advisory_lock_key

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "tracking_prefix_migration", ROOT / "alembic/versions/424_tracking_protocol_prefix.py"
)
assert SPEC is not None
assert SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


@pytest.mark.parametrize("finalizing", [False, True])
def test_prefix_preserves_original_body_and_existing_isolation(finalizing: bool) -> None:
    body = (
        "\nDECLARE v integer;\nBEGIN\n"
        "  IF current_setting('transaction_isolation') <> 'serializable' THEN\n"
        "    RAISE EXCEPTION 'SER required';\n  END IF;\n"
        "  PERFORM old_capture();\nEND;\n"
    )
    changed = MIGRATION._with_prefix(body, finalizing=finalizing)
    entry = (
        "  PERFORM ops.lock_provider_feature_tracking_protocol(" + str(finalizing).lower() + ");\n"
    )
    assert changed.count(entry) == 1
    assert changed.replace(entry, "", 1) == body


@pytest.mark.parametrize(
    "body",
    [
        "BEGIN NULL; END",
        "\nBEGIN\nPERFORM ops.lock_provider_feature_tracking_protocol(true);\nEND;\n",
    ],
)
def test_migration_rejects_unreviewed_or_repeated_entry(body: str) -> None:
    with pytest.raises(RuntimeError):
        MIGRATION._with_prefix(body, finalizing=True)


def test_lineage_key_matches_the_existing_canonical_hash_contract() -> None:
    key = advisory_lock_key("kortravelmap:pipeline-lineage:mutation")
    assert key == 6832465333779826081
    assert (key >> 32, key & 0xFFFFFFFF) == (1590807301, 1746797985)
    sql = (ROOT / "alembic/versions/_424_tracking_prefix.sql").read_text()
    assert "pg_advisory_xact_lock(" + str(key) + "::bigint)" in sql


@pytest.mark.asyncio
async def test_python_prefix_modes_delegate_to_same_typed_database_entry() -> None:
    session = AsyncMock()
    await cancellation.lock_provider_feature_finalization(session)
    await cancellation.lock_provider_feature_tracking_leaf(session)
    assert [str(call.args[0]) for call in session.execute.await_args_list] == [
        "SELECT ops.lock_provider_feature_tracking_protocol(true)",
        "SELECT ops.lock_provider_feature_tracking_protocol(false)",
    ]


@pytest.mark.asyncio
async def test_append_prefix_failure_stops_before_reading_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PrefixFailure(Exception):
        pass

    prefix = AsyncMock(side_effect=PrefixFailure)
    load = AsyncMock()
    monkeypatch.setattr(operations, "lock_provider_feature_tracking_leaf", prefix)
    monkeypatch.setattr(operations, "_load_operation", load)
    with pytest.raises(PrefixFailure):
        await operations.append_dagster_feature_attempt_event(
            AsyncMock(),
            dagster_run_id="tracking-prefix",
            membership=ProviderDatasetOperationMembership(
                1, "dataset_wide", "feature.place.krheritage.items"
            ),
            attempt_number=1,
            outcome="failed",
            error={"kind": "fixture"},
        )
    prefix.assert_awaited_once()
    load.assert_not_awaited()


def test_existing_common_lineage_primitive_does_not_gain_protocol_lock() -> None:
    tree = ast.parse((ROOT / "src/kortravelmap/infra/pipeline_cancellation_repo.py").read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "lock_pipeline_lineage_mutation"
    )
    calls = [ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)]
    assert calls == ["session.execute", "text", "advisory_lock_key"]
    assert "lock_provider" not in ast.unparse(node)
