"""434 migration의 정본 고정·편집 계획·SQL/Python 분류 일치를 DB 없이 검증한다.

실제 PostgreSQL 위의 동작(대기·거부·drain)은 통합 검사가 본다 —
``tests/integration/test_tracking_protocol_prefix.py``(WI-1),
``tests/integration/test_single_writer_regime_entry.py``(DC-1).
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import re
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.infra.pipeline_cancellation_repo import cancellation_transition_finalizes

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "protocol_entry_narrowing", ROOT / "alembic/versions/434_protocol_entry_narrowing.py"
)
assert SPEC is not None
assert SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)
HEAD = (ROOT / "alembic/head-schema.sql").read_text(encoding="utf-8")

_BODY = (
    "\nDECLARE\n    v_source record;\nBEGIN\n"
    "  PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
    "  PERFORM 1;\nEND;\n"
)


def _row(body: str, routine: Any, *, name: str = "feature.synthetic") -> dict[str, Any]:
    return {
        "name": name,
        "owner": routine.owner,
        "kind": routine.kind,
        "prosecdef": routine.security_definer,
        "language": "plpgsql",
        "body": body,
        "definition": "CREATE OR REPLACE PROCEDURE feature.synthetic() AS $$" + body + "$$",
    }


@pytest.fixture
def synthetic(monkeypatch: pytest.MonkeyPatch) -> Any:
    routine = MIGRATION._Routine(
        "feature.synthetic()",
        "ktm_feature_state_procedure_owner",
        "p",
        True,
        hashlib.sha256(_BODY.encode()).hexdigest(),
        ((MIGRATION._PROTOCOL_EX, MIGRATION._SINGLE_WRITER),),
    )
    monkeypatch.setattr(MIGRATION, "_ROUTINES", {"feature.synthetic": routine})
    return routine


def test_plan_replaces_only_the_reviewed_entry(synthetic: Any) -> None:
    [(name, owner, definition)] = MIGRATION._planned_replacements([_row(_BODY, synthetic)])
    assert (name, owner) == ("feature.synthetic", synthetic.owner)
    assert "  PERFORM ops.lock_single_feature_writer_protocol();\n" in definition
    assert "lock_scoped_feature_write_protocol" not in definition
    assert definition.replace(MIGRATION._SINGLE_WRITER, MIGRATION._PROTOCOL_EX) == (
        _row(_BODY, synthetic)["definition"]
    )


@pytest.mark.parametrize(
    "drift", ["body", "owner", "kind", "security", "language", "inventory", "twice", "applied"]
)
def test_plan_refuses_any_drift_from_revision_432(
    synthetic: Any, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    """432 정본과 하나라도 다르면 아무것도 바꾸지 않는다(424·426과 같은 고정 방식)."""
    row = _row(_BODY, synthetic)
    rows = [row]
    if drift == "body":
        row.update(_row(_BODY.replace("PERFORM 1", "PERFORM 2"), synthetic))
    elif drift == "owner":
        row["owner"] = "ktm_feature_schema_owner"
    elif drift == "kind":
        row["kind"] = "f"
    elif drift == "security":
        row["prosecdef"] = False
    elif drift == "language":
        row["language"] = "sql"
    elif drift == "inventory":
        rows.append(dict(row, name="feature.unreviewed"))
    else:
        # 고정 hash를 바뀐 본문에 맞춰도 멈춰야 한다 — 바늘이 둘이거나 이미 적용된 경우.
        body = (
            _BODY + MIGRATION._PROTOCOL_EX
            if drift == "twice"
            else _BODY.replace("PERFORM 1", "PERFORM ops.lock_single_feature_writer_protocol()")
        )
        monkeypatch.setattr(synthetic, "body_sha256", hashlib.sha256(body.encode()).hexdigest())
        row.update(_row(body, synthetic))
    with pytest.raises(RuntimeError):
        MIGRATION._planned_replacements(rows)


def _head_body(name: str) -> str:
    bodies = re.findall(
        rf"CREATE (?:FUNCTION|PROCEDURE) {re.escape(name)}\(.*?AS (\$[A-Za-z0-9_]*\$)(.*?)\1;",
        HEAD,
        re.DOTALL,
    )
    assert len(bodies) == 1, name
    return str(bodies[0][1])


@pytest.mark.parametrize("name", sorted(MIGRATION._ROUTINES))
def test_head_is_exactly_revision_432_plus_the_reviewed_edits(name: str) -> None:
    """head-schema의 434 본문에서 편집을 거꾸로 되돌리면 고정한 432 hash가 나와야 한다."""
    routine = MIGRATION._ROUTINES[name]
    body = _head_body(name)
    for old, new in reversed(routine.edits):
        assert body.count(new) == 1, (name, new[:60])
        body = body.replace(new, old, 1)
    assert hashlib.sha256(body.encode()).hexdigest() == routine.body_sha256, name


def test_single_writer_entry_is_installed_with_its_drain_semantics() -> None:
    body = " ".join(_head_body("ops.lock_single_feature_writer_protocol").split())
    # epoch를 평범하게 읽는다(ACCESS SHARE) — 첫 활성화의 ACCESS EXCLUSIVE가 이 writer를 기다린다.
    assert "FROM feature.provider_field_policy_epoch WHERE singleton;" in body
    assert "FOR UPDATE" not in body
    assert "FOR SHARE" not in body
    # strict guard는 단독 SH를 거부하므로 regime의 단건 writer는 EX다.
    assert body.count("ops.lock_scoped_feature_write_protocol(true)") == 1
    assert "lock_scoped_feature_write_protocol(false)" not in body


_SQL_CONDITION = re.compile(r"(p_[a-z_]+) IS NOT DISTINCT FROM '([^']*)'")


def test_cancellation_finalization_matches_the_sql_entry_argument() -> None:
    """Python이 고른 prefix와 SQL 진입의 인자 식이 어긋나면 23514로 닫힌다.

    그래서 둘은 같은 진리표여야 한다.
    """
    conditions = dict(_SQL_CONDITION.findall(MIGRATION._CANCEL_TRANSITION_NEW))
    assert set(conditions) == {"p_result", "p_target_status", "p_dagster_terminal_status"}
    results = ["already_terminal", "cancelled", "cancel_failed", "pending"]
    targets = ["done", "failed", "cancelled"]
    terminals = ["SUCCESS", "FAILURE", "CANCELED", None]
    for result, target, terminal in itertools.product(results, targets, terminals):
        values = {
            "p_result": result,
            "p_target_status": target,
            "p_dagster_terminal_status": terminal,
        }
        sql = all(values[name] == literal for name, literal in conditions.items())
        assert (
            cancellation_transition_finalizes(
                result=result, target_status=target, dagster_terminal_status=terminal
            )
            is sql
        ), values


def test_finish_entry_mode_is_the_authoritative_argument_itself() -> None:
    entry = (
        "PERFORM ops.lock_provider_feature_tracking_protocol(p_authoritative_snapshot_complete);"
    )
    assert MIGRATION._FINISH_NEW.count(entry) == 1
    # NULL 검사는 잠금을 잡지 않는다 — 진입보다 앞서 22023으로 닫는다.
    assert MIGRATION._FINISH_NEW.index("IS NULL THEN") < MIGRATION._FINISH_NEW.index(entry)
