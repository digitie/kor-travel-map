"""잔존 curated catalog repo 계약 — rule 명령의 full-desired CAS 입력.

T-VN-40C가 `tests/unit/test_curated_repo.py`를 지우면서 legacy projection 검사와
함께 사라질 뻔한 잔존 계약만 옮겼다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.infra import curated_repo

_KST = timezone(timedelta(hours=9))

_THEME_ID = "11111111-1111-1111-1111-111111111111"

_SOURCE_ID = "22222222-2222-2222-2222-222222222222"

_RULE_ID = "33333333-3333-3333-3333-333333333333"

_NOW = datetime(2026, 6, 12, 18, 0, tzinfo=_KST)

class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def one(self) -> dict[str, Any]:
        assert len(self._rows) == 1
        return self._rows[0]

class _FakeSession:
    def __init__(self, *results: list[dict[str, Any]]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append((str(statement), params or {}))
        assert self._results, f"unexpected execute: {statement}"
        return _FakeResult(self._results.pop(0))

def _rule_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "rule_id": _RULE_ID,
        "theme_id": _THEME_ID,
        "theme_slug": "bookstores",
        "source_id": _SOURCE_ID,
        "provider_dataset_id": 101,
        "provider": "python-datagokr-api",
        "dataset_key": "datagokr_seoul_bookstores",
        "place_kind": "seoul_bookstore",
        "category": None,
        "region_scope": {},
        "detail_selector": None,
        "default_action": "candidate",
        "priority": 70,
        "enabled": True,
        "metadata": {"curation_relation": "bookstore_stop"},
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(overrides)
    return row

@pytest.mark.asyncio
async def test_retained_rule_commands_use_full_desired_cas_inputs() -> None:
    session = _FakeSession(
        [{"o_rule_id": _RULE_ID, "o_rule_revision": 1, "o_generation_id": "gen-1"}],
        [_rule_row(row_revision=1)],
        [_rule_row(row_revision=1)],
        [{"o_rule_id": _RULE_ID, "o_rule_revision": 2, "o_generation_id": "gen-2"}],
        [_rule_row(row_revision=2, priority=90, default_action="ignore")],
        [_rule_row(row_revision=2, priority=90, default_action="ignore")],
        [{"o_rule_id": _RULE_ID, "o_rule_revision": 3, "o_generation_id": "gen-3"}],
        [
            _rule_row(
                row_revision=3,
                priority=90,
                default_action="ignore",
                archived_at=_NOW,
            )
        ],
    )

    created = await curated_repo.create_curated_source_rule_command(
        session,
        theme_id=_THEME_ID,
        source_id=_SOURCE_ID,
        region_scope={"sido_code": "11"},
        command_id=101,
        principal="admin:rule-test",
    )
    patched = await curated_repo.patch_curated_source_rule_command(
        session,
        rule_id=_RULE_ID,
        expected_revision=1,
        updates={"priority": 90, "default_action": "ignore"},
        command_id=102,
        principal="admin:rule-test",
    )
    archived = await curated_repo.archive_curated_source_rule_command(
        session,
        rule_id=_RULE_ID,
        expected_revision=2,
        command_id=103,
        reason_code="operator_retired",
        principal="admin:rule-test",
    )

    assert created.row_revision == 1
    assert patched is not None
    assert (patched.row_revision, patched.priority, patched.default_action) == (
        2,
        90,
        "ignore",
    )
    assert archived is not None
    assert (archived.row_revision, archived.archived_at) == (3, _NOW)
    command_calls = [call for call in session.calls if "CALL feature." in call[0]]
    assert [
        "create_curated_source_rule_command" in call[0]
        or "patch_curated_source_rule_command" in call[0]
        or "archive_curated_source_rule_command" in call[0]
        for call in command_calls
    ] == [True, True, True]
    assert command_calls[1][1]["expected_revision"] == 1
    assert command_calls[1][1]["priority"] == 90
    assert command_calls[1][1]["region_scope_json"] == "{}"
    assert command_calls[2][1]["expected_revision"] == 2
