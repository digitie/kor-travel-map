"""``kortravelmap.infra.pipeline_repo`` cursor/입력 검증 단위 테스트 (ADR-064)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kortravelmap.infra import pipeline_repo
from kortravelmap.infra.pipeline_repo import (
    PIPELINE_EXECUTION_KINDS,
    PipelineExecution,
    get_pipeline_status_counts,
    list_pipeline_executions,
)

pytestmark = pytest.mark.unit


class _NoQuerySession:
    """SQL 실행에 도달하면 안 되는 검증 경로 테스트용 세션."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("검증 실패 경로는 SQL을 실행하면 안 된다")


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def one(self) -> Any:
        return self._rows[0]


class _Session:
    def __init__(self, *results: _Result) -> None:
        self._results = list(results)
        self.params: list[dict[str, Any]] = []

    async def execute(
        self, _statement: Any, params: dict[str, Any] | None = None
    ) -> _Result:
        self.params.append(dict(params or {}))
        return self._results.pop(0)


def _job_row(job_id: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        kind="import_job",
        id=job_id,
        status="running",
        created_at=at,
        job_kind="provider_load",
        provider="python-kma-api",
        dataset_key="kma_short_forecast",
        progress=40,
        current_stage="loading",
        scope_type=None,
        priority=None,
        run_mode=None,
        operator=None,
        error_message=None,
        started_at=at,
        finished_at=None,
        dagster_run_id="run-1",
        linked_job_id=None,
        linked_request_id="22222222-2222-2222-2222-222222222222",
        load_batch_id="33333333-3333-3333-3333-333333333333",
        parent_job_id=None,
    )


def test_execution_kinds_match_contract() -> None:
    assert sorted(PIPELINE_EXECUTION_KINDS) == ["import_job", "update_request"]


def test_cursor_round_trip_preserves_keyset() -> None:
    at = datetime(2026, 7, 14, 12, 34, 56, 789000, tzinfo=UTC)
    cursor = pipeline_repo._encode_cursor(
        at=at, key="11111111-1111-1111-1111-111111111111"
    )

    decoded_at, decoded_key = pipeline_repo._decode_cursor(cursor)

    assert decoded_at == at
    assert decoded_key == "11111111-1111-1111-1111-111111111111"


def test_decode_cursor_none_returns_empty_keyset() -> None:
    assert pipeline_repo._decode_cursor(None) == (None, None)


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!!!",
        "aGVsbG8",  # base64지만 JSON 아님
    ],
)
def test_decode_cursor_rejects_malformed_values(cursor: str) -> None:
    with pytest.raises(ValueError, match="pipeline_executions cursor"):
        pipeline_repo._decode_cursor(cursor)


def test_decode_cursor_rejects_foreign_kind() -> None:
    # 다른 목록(import_jobs 등)의 cursor를 흘려 넣으면 거부한다.
    import base64
    import json

    raw = json.dumps(
        {"v": 1, "kind": "import_jobs", "at": "2026-07-14T00:00:00+00:00", "key": "k"},
        separators=(",", ":"),
    ).encode("utf-8")
    foreign = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    with pytest.raises(ValueError, match="pipeline_executions cursor"):
        pipeline_repo._decode_cursor(foreign)


async def test_list_maps_rows_filters_and_next_cursor() -> None:
    at = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
    session = _Session(
        _Result(
            [
                _job_row("11111111-1111-1111-1111-111111111111", at=at),
                _job_row("99999999-9999-4999-8999-999999999999", at=at),
            ]
        )
    )

    page = await list_pipeline_executions(
        cast(Any, session),
        kind="import_job",
        status="running",
        provider="python-kma-api",
        limit=1,
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert isinstance(item, PipelineExecution)
    assert item.kind == "import_job"
    assert item.job_kind == "provider_load"
    assert item.request_id == "22222222-2222-2222-2222-222222222222"
    assert item.dagster_run_id == "run-1"
    assert item.load_batch_id == "33333333-3333-3333-3333-333333333333"
    assert page.next_cursor is not None
    decoded = pipeline_repo._decode_cursor(page.next_cursor)
    assert decoded == (at, "11111111-1111-1111-1111-111111111111")

    params = session.params[0]
    assert params["include_import_jobs"] is True
    assert params["include_update_requests"] is False
    assert params["status"] == "running"
    assert params["provider"] == "python-kma-api"
    assert params["provider_filter"] == '["python-kma-api"]'
    assert params["branch_limit"] == 2


async def test_status_counts_parses_aggregates() -> None:
    session = _Session(
        _Result(
            [
                SimpleNamespace(
                    import_jobs_by_status='{"queued": 2, "failed": 1}',
                    update_requests_by_status='{"done": 4}',
                    failed_import_jobs_24h=1,
                    failed_update_requests_24h=0,
                )
            ]
        )
    )

    counts = await get_pipeline_status_counts(cast(Any, session))

    assert counts.import_jobs_by_status == {"queued": 2, "failed": 1}
    assert counts.update_requests_by_status == {"done": 4}
    assert counts.failed_import_jobs_24h == 1
    assert counts.failed_update_requests_24h == 0


async def test_list_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="kind must be one of"):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            kind="dagster_run",
        )


async def test_list_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit must be greater than 0"):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            limit=0,
        )


async def test_list_rejects_invalid_cursor_before_query() -> None:
    with pytest.raises(ValueError, match="pipeline_executions cursor"):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            cursor="broken",
        )
