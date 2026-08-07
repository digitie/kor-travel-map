"""``sync_state_repo`` DB 무관 단위 테스트 (T-213 cursor 추적).

실제 UPSERT는 통합 테스트가 PostGIS에서 검증한다. 여기서는 파라미터 조립과
``_row_to_state``(cursor 문자열 역직렬화 포함) 분기를 mock session으로 본다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra import sync_state_repo as repo

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
        "provider_dataset_id": 42,
        "provider": "python-mois-api",
        "dataset_key": "mois_license_features_bulk",
        "sync_scope": "dataset_wide",
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
    assert state.provider_dataset_id == 42
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
        operation_key="op_test",
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
        operation_key="op_test",
        cursor={"last_modified_date": "2026-06-06"},
    )
    assert state.consecutive_failures == 0
    assert json.loads(session.calls[0]["params"]["cursor"]) == {
        "last_modified_date": "2026-06-06"
    }
    assert "provider_dataset_id" in session.calls[0]["sql"]
    assert "provider_sync.provider_datasets" in session.calls[0]["sql"]


async def test_record_sync_failure_increments() -> None:
    session = _Session([_state_row(consecutive_failures=3, last_failure_at=_NOW)])
    state = await repo.record_sync_failure(
        session,  # type: ignore[arg-type]
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        operation_key="op_test",
    )
    assert state.consecutive_failures == 3
    assert "cursor" not in session.calls[0]["params"]
    assert "ON CONFLICT (provider_dataset_id, sync_scope)" in session.calls[0]["sql"]


async def test_exact_operation_membership_sync_state_uses_full_refresh_identity() -> None:
    membership = ProviderDatasetOperationMembership(
        provider_dataset_id=42,
        sync_scope="dataset_wide",
        operation_key="feature_place_mois_bulk_job",
    )

    get_session = _Session([_state_row()])
    state = await repo.get_sync_state_for_operation_membership(
        get_session,  # type: ignore[arg-type]
        membership=membership,
    )
    assert state is not None
    assert get_session.calls[0]["params"] == {
        "provider_dataset_id": 42,
        "sync_scope": "dataset_wide",
        "operation_key": "feature_place_mois_bulk_job",
    }
    assert "dataset.provider_dataset_id" in get_session.calls[0]["sql"]
    assert "scope.operation_key" in get_session.calls[0]["sql"]

    success_session = _Session([_state_row()])
    await repo.record_sync_success_for_operation_membership(
        success_session,  # type: ignore[arg-type]
        membership=membership,
        cursor={"watermark": "2026-08-07"},
    )
    assert json.loads(success_session.calls[0]["params"]["cursor"]) == {
        "watermark": "2026-08-07"
    }
    assert "exact_membership" in success_session.calls[0]["sql"]

    failure_session = _Session([_state_row()])
    await repo.record_sync_failure_for_operation_membership(
        failure_session,  # type: ignore[arg-type]
        membership=membership,
    )
    assert "cursor" not in failure_session.calls[0]["params"]
    assert "scope.operation_key" in failure_session.calls[0]["sql"]


@pytest.mark.parametrize("cursor", [None, {}])
async def test_row_to_state_empty_cursor(cursor: Any) -> None:
    state = await repo.get_sync_state(
        _Session([_state_row(cursor=cursor)]),  # type: ignore[arg-type]
        provider="p",
        dataset_key="d",
    )
    assert state is not None
    assert state.cursor == {}
