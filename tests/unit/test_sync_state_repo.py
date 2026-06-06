"""``sync_state_repo`` DB 무관 단위 테스트 (T-213 cursor 추적).

실제 UPSERT는 통합 테스트가 PostGIS에서 검증한다. 여기서는 파라미터 조립과
``_row_to_state``(cursor 문자열 역직렬화 포함) 분기를 mock session으로 본다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from krtour.map.infra import sync_state_repo as repo

_NOW = datetime(2026, 6, 6, tzinfo=UTC)


class _Row:
    def __init__(self, data: dict[str, Any]) -> None:
        self.__dict__.update(data)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def one_or_none(self) -> _Row | None:
        return _Row(self._rows[0]) if self._rows else None

    def one(self) -> _Row:
        return _Row(self._rows[0])

    def all(self) -> list[_Row]:
        return [_Row(r) for r in self._rows]


class _Session:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.calls: list[dict[str, Any]] = []

    async def execute(self, statement: object, params: dict[str, Any]) -> _Result:
        self.calls.append({"sql": str(statement), "params": params})
        return _Result(self._rows)


def _state_row(**over: Any) -> dict[str, Any]:
    base = {
        "provider": "python-mois-api",
        "dataset_key": "mois_license_features_bulk",
        "sync_scope": "default",
        "status": "active",
        "cursor": {"last_modified_date": "2026-06-01"},
        "last_success_at": _NOW,
        "last_failure_at": None,
        "consecutive_failures": 0,
        "next_run_after": None,
    }
    base.update(over)
    return base


async def test_get_sync_state_present_and_missing() -> None:
    state = await repo.get_sync_state(
        _Session([_state_row()]),  # type: ignore[arg-type]
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    )
    assert state is not None
    assert state.cursor == {"last_modified_date": "2026-06-01"}

    missing = await repo.get_sync_state(
        _Session([]),  # type: ignore[arg-type]
        provider="x",
        dataset_key="y",
    )
    assert missing is None


async def test_row_to_state_parses_json_string_cursor() -> None:
    # asyncpg가 JSONB를 str로 돌려주는 경로.
    session = _Session([_state_row(cursor=json.dumps({"k": "v"}))])
    state = await repo.get_sync_state(
        session,  # type: ignore[arg-type]
        provider="p",
        dataset_key="d",
    )
    assert state is not None
    assert state.cursor == {"k": "v"}


async def test_list_sync_states_passes_filters() -> None:
    session = _Session([_state_row(), _state_row(sync_scope="region")])
    states = await repo.list_sync_states(
        session,  # type: ignore[arg-type]
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        sync_scope=None,
    )
    assert len(states) == 2
    assert session.calls[0]["params"]["dataset_key"] == "mois_license_features_bulk"
    assert session.calls[0]["params"]["sync_scope"] is None


async def test_record_sync_success_serializes_cursor() -> None:
    session = _Session([_state_row(cursor={"last_modified_date": "2026-06-06"})])
    state = await repo.record_sync_success(
        session,  # type: ignore[arg-type]
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        cursor={"last_modified_date": "2026-06-06"},
    )
    assert state.consecutive_failures == 0
    assert json.loads(session.calls[0]["params"]["cursor"]) == {
        "last_modified_date": "2026-06-06"
    }


async def test_record_sync_failure_increments() -> None:
    session = _Session([_state_row(consecutive_failures=3, last_failure_at=_NOW)])
    state = await repo.record_sync_failure(
        session,  # type: ignore[arg-type]
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    )
    assert state.consecutive_failures == 3
    assert "cursor" not in session.calls[0]["params"]


@pytest.mark.parametrize("cursor", [None, {}])
async def test_row_to_state_empty_cursor(cursor: Any) -> None:
    state = await repo.get_sync_state(
        _Session([_state_row(cursor=cursor)]),  # type: ignore[arg-type]
        provider="p",
        dataset_key="d",
    )
    assert state is not None
    assert state.cursor == {}
