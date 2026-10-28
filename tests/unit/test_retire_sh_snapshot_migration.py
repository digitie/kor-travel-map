"""435(ADR-117) 퇴역 migration의 닫힌 판정 — 실제 DB 없이 결정 함수만 반증한다.

실제 적용(빈 DB → 435 → head 오라클 일치)은 통합 시험
``test_alembic_metadata_consistency.py::test_head_schema_artifact_matches_head``가 본다.
여기서는 운영에서만 만날 분기(쓰인 DB·바뀐 본문·다른 inventory)가 **아무것도 지우기 전에**
멈추는지를 본다.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "_retire435", _ROOT / "alembic/versions/435_retire_sh_snapshot_path.py"
)
assert _SPEC is not None
assert _SPEC.loader is not None
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)

_ZERO = {
    "active_policies": 0,
    "epoch": 0,
    "attempts": 0,
    "artifacts": 0,
    "controls": 0,
    "reservations": 0,
    "manifests": 0,
    "region_leases": 0,
    "activation_triggers": 0,
}


class _Result:
    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self._rows = list(rows)

    def mappings(self) -> _Result:
        return self

    def one(self) -> Mapping[str, Any]:
        assert len(self._rows) == 1
        return self._rows[0]

    def all(self) -> list[Mapping[str, Any]]:
        return self._rows


class _Bind:
    """``_PRECONDITION_SQL``·``_DROP_CATALOG_SQL``과 search_path 조회·설정만 흉내낸다."""

    def __init__(self, *, counts: Mapping[str, int], catalog: Sequence[Mapping[str, str]]) -> None:
        self.counts = dict(counts)
        self.catalog = list(catalog)
        self.statements: list[str] = []

    def execute(self, statement: Any, params: Mapping[str, Any] | None = None) -> _Result:
        sql = str(statement)
        self.statements.append(sql)
        if "active_policies" in sql and "activation_triggers" in sql:
            assert params is not None
            assert set(params["routines"]) == {drop.name for drop in migration._DROPS}
            assert list(params["tables"]) == list(migration._TABLES)
            return _Result([self.counts])
        if "pg_get_function_identity_arguments" in sql:
            return _Result(self.catalog)
        return _Result([])

    def scalar(self, statement: Any, params: Mapping[str, Any] | None = None) -> str:
        self.statements.append(str(statement))
        return '"$user", public'


def _planned_catalog() -> list[dict[str, str]]:
    return [
        {"name": d.name, "kind": d.kind, "owner": d.owner, "identity": d.identity}
        for d in migration._DROPS
    ]


def test_clean_state_passes_preconditions() -> None:
    migration._assert_preconditions(_Bind(counts=_ZERO, catalog=[]))


@pytest.mark.parametrize("key", sorted(_ZERO))
def test_any_used_state_stops_before_anything_is_dropped(key: str) -> None:
    bind = _Bind(counts={**_ZERO, key: 1}, catalog=[])
    with pytest.raises(RuntimeError, match=key):
        migration._assert_preconditions(bind)
    assert not any(sql.lstrip().upper().startswith("DROP") for sql in bind.statements)


def test_exact_drop_inventory_passes_and_reads_under_pg_catalog_path() -> None:
    bind = _Bind(counts=_ZERO, catalog=_planned_catalog())
    migration._assert_drop_inventory(bind)
    set_paths = [sql for sql in bind.statements if "set_config('search_path'" in sql]
    assert len(set_paths) == 2  # pg_catalog로 바꾸고 원래 값으로 되돌린다


@pytest.mark.parametrize("mutation", ["missing", "overload", "owner", "identity"])
def test_drop_inventory_mismatch_fails(mutation: str) -> None:
    catalog = _planned_catalog()
    if mutation == "missing":
        catalog.pop()
    elif mutation == "overload":
        catalog.append({**catalog[0], "identity": catalog[0]["identity"] + ", p_extra integer"})
    elif mutation == "owner":
        catalog[0] = {**catalog[0], "owner": "ktm_feature_runtime"}
    else:
        catalog[0] = {**catalog[0], "identity": "p_other text"}
    with pytest.raises(RuntimeError, match="drop inventory differs"):
        migration._assert_drop_inventory(_Bind(counts=_ZERO, catalog=catalog))


def test_changed_434_body_is_rejected() -> None:
    name = "ops.lock_scoped_feature_write_protocol"
    with pytest.raises(RuntimeError, match="434 body changed"):
        migration._edited_body(name, "\nBEGIN\nEND;\n")


def test_single_writer_edit_removes_only_the_regime_entry() -> None:
    name = "feature.transition_feature_state"
    body = (
        "\nDECLARE x int;\nBEGIN\n  PERFORM ops.lock_single_feature_writer_protocol();\n"
        "  RETURN;\nEND;\n"
    )
    routine = migration._ROUTINES[name]
    original = routine.body_sha256
    routine.body_sha256 = hashlib.sha256(body.encode()).hexdigest()
    try:
        edited = migration._edited_body(name, body)
    finally:
        routine.body_sha256 = original
    assert "lock_single_feature_writer_protocol" not in edited
    assert "lock_scoped_feature_write_protocol" not in edited
    assert edited.replace(migration._SINGLE_WRITER_NEW, migration._SINGLE_WRITER_OLD) == body


def test_retired_tables_drop_children_first_and_trigger_functions_last() -> None:
    statements = [s for s in migration._UPGRADE_STATEMENTS if s.startswith("DROP")]
    tables = [s.split()[-1] for s in statements if s.startswith("DROP TABLE")]
    assert tables == list(migration._TABLES)
    assert tables.index("ops.feature_write_attempts") > tables.index("ops.feature_write_manifests")
    last_table = max(i for i, s in enumerate(statements) if s.startswith("DROP TABLE"))
    trigger_drops = [
        i
        for i, s in enumerate(statements)
        if any(name + "(" in s for name in migration._TRIGGER_FUNCTIONS)
    ]
    assert trigger_drops
    assert min(trigger_drops) > last_table
    assert not any("CASCADE" in s.upper() for s in migration._UPGRADE_STATEMENTS)
    assert migration._UPGRADE_STATEMENTS[-1] == "SET ROLE ktm_feature_schema_owner"
    assert not any("RESET ROLE" in s.upper() for s in migration._UPGRADE_STATEMENTS)
