"""``kortravelmap.infra.pipeline_repo`` cursor/입력 검증 단위 테스트 (ADR-064)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kortravelmap.infra import pipeline_repo
from kortravelmap.infra.pipeline_repo import (
    PIPELINE_EXECUTION_KINDS,
    PipelineCursorFilterMismatch,
    PipelineExecution,
    get_pipeline_status_counts,
    list_dataset_pipeline_execution_snapshots,
    list_latest_dataset_pipeline_executions,
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

    def one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, *results: _Result) -> None:
        self._results = list(results)
        self.params: list[dict[str, Any]] = []

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> _Result:
        self.params.append(dict(params or {}))
        return self._results.pop(0)


def _job_row(job_id: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        kind="import_job",
        id=job_id,
        status="running",
        created_at=at,
        providers=["python-kma-api"],
        dataset_keys=["kma_short_forecast"],
        provider_datasets=json.dumps(
            [
                {
                    "provider": "python-kma-api",
                    "dataset_key": "kma_short_forecast",
                    "sync_scope": None,
                    "operation_member_id": job_id,
                    "status": "running",
                }
            ]
        ),
        scope_provider=None,
        scope_dataset=None,
        scope_sync_scope=None,
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
        dagster_run_status="STARTED",
        trigger_kind="manual",
        operation_registry_version=None,
        requested_job_id=None,
        linked_job_count=2,
        projected_job_id="77777777-7777-4777-8777-777777777777",
        projected_job_kind="provider_load",
        projected_status="running",
        projected_progress=40,
        projected_current_stage="loading",
        projected_error_message=None,
        projected_created_at=at,
        projected_started_at=at,
        projected_finished_at=None,
        projected_dagster_run_id="run-child",
        projected_dagster_run_status=None,
        projected_trigger_kind="manual",
        projected_operation_registry_version=None,
        projected_load_batch_id="33333333-3333-3333-3333-333333333333",
        projected_parent_job_id=job_id,
        projected_depth=1,
        cancellation_id=None,
        cancellation_status=None,
        cancellation_requested_at=None,
        cancellation_requested_by=None,
        cancellation_reason=None,
        cancellation_retryable=None,
        cancellation_unresolved_member_count=None,
        selected_provider="python-kma-api",
        selected_dataset_key="kma_short_forecast",
        selected_sync_scope="target_grids",
        selected_operation_member_id=job_id,
        selected_pair_status="running",
    )


def test_execution_kinds_match_contract() -> None:
    assert sorted(PIPELINE_EXECUTION_KINDS) == ["import_job", "update_request"]


def test_cursor_round_trip_preserves_keyset() -> None:
    at = datetime(2026, 7, 14, 12, 34, 56, 789000, tzinfo=UTC)
    cursor = pipeline_repo._encode_cursor(
        at=at,
        key="11111111-1111-1111-1111-111111111111",
        item_kind="update_request",
    )

    decoded_at, decoded_key, decoded_kind = pipeline_repo._decode_cursor(cursor)

    assert decoded_at == at
    assert decoded_key == "11111111-1111-1111-1111-111111111111"
    assert decoded_kind == "update_request"


def test_decode_cursor_none_returns_empty_keyset() -> None:
    assert pipeline_repo._decode_cursor(None) == (None, None, None)


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


def test_encode_cursor_rejects_non_uuid_key() -> None:
    with pytest.raises(ValueError, match="pipeline_executions cursor"):
        pipeline_repo._encode_cursor(
            at=datetime(2026, 7, 14, tzinfo=UTC),
            key="not-a-uuid",
            item_kind="import_job",
        )


def test_decode_cursor_rejects_foreign_kind() -> None:
    # 다른 목록(import_jobs 등)의 cursor를 흘려 넣으면 거부한다.
    import base64
    import json

    raw = json.dumps(
        {
            "v": 2,
            "cursor": "import_jobs",
            "at": "2026-07-14T00:00:00+00:00",
            "id": "11111111-1111-1111-1111-111111111111",
            "item_kind": "import_job",
        },
        separators=(",", ":"),
    ).encode("utf-8")
    foreign = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    with pytest.raises(ValueError, match="pipeline_executions cursor"):
        pipeline_repo._decode_cursor(foreign)


def test_decode_cursor_rejects_unknown_item_kind() -> None:
    import base64
    import json

    raw = json.dumps(
        {
            "v": 2,
            "cursor": "pipeline_executions",
            "at": "2026-07-14T00:00:00+00:00",
            "id": "11111111-1111-1111-1111-111111111111",
            "item_kind": "dagster_run",
        },
        separators=(",", ":"),
    ).encode("utf-8")
    cursor = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    with pytest.raises(ValueError, match="pipeline_executions cursor"):
        pipeline_repo._decode_cursor(cursor)


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
        load_batch_id="33333333-3333-3333-3333-333333333333",
        parent_job_id="11111111-1111-1111-1111-111111111111",
        limit=1,
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert isinstance(item, PipelineExecution)
    assert item.kind == "import_job"
    assert item.providers == ("python-kma-api",)
    assert item.dagster_run_id == "run-1"
    assert item.provider_datasets[0].operation_member_id == item.id
    assert item.linked_job_count == 2
    assert item.projected_job.job_kind == "provider_load"
    assert item.projected_job.load_batch_id == ("33333333-3333-3333-3333-333333333333")
    assert page.next_cursor is not None
    decoded = pipeline_repo._decode_cursor(
        page.next_cursor,
        filter_fingerprint=pipeline_repo._filter_fingerprint(
            kind="import_job",
            status="running",
            provider="python-kma-api",
            load_batch_id="33333333-3333-3333-3333-333333333333",
            parent_job_id="11111111-1111-1111-1111-111111111111",
        ),
    )
    assert decoded == (
        at,
        "11111111-1111-1111-1111-111111111111",
        "import_job",
    )

    params = session.params[0]
    assert params["kind"] == "import_job"
    assert params["status"] == "running"
    assert params["provider"] == "python-kma-api"
    assert params["dataset_key"] is None
    assert params["filter_sync_scopes"] is False
    assert params["sync_scopes"] == []
    assert params["include_unscoped_scope"] is False
    assert params["load_batch_id"] == "33333333-3333-3333-3333-333333333333"
    assert params["parent_job_id"] == "11111111-1111-1111-1111-111111111111"
    assert params["page_limit"] == 2


def test_component_membership_filters_precede_cursor_and_limit() -> None:
    normalized = " ".join(pipeline_repo._LIST_EXECUTIONS_BODY_SQL.split())

    load_filter = normalized.index("member.load_batch_id = CAST(:load_batch_id AS uuid)")
    parent_filter = normalized.index("member.parent_job_id = CAST(:parent_job_id AS uuid)")
    cursor_filter = normalized.index("CAST(:cursor_created_at AS timestamptz) IS NULL")
    page_limit = normalized.index("LIMIT :page_limit")

    assert load_filter < cursor_filter < page_limit
    assert parent_filter < cursor_filter < page_limit


async def test_status_counts_parses_aggregates() -> None:
    session = _Session(
        _Result(
            [
                SimpleNamespace(
                    operations_by_status='{"queued": 2, "failed": 1}',
                    active_operations=2,
                    failed_operations_24h=1,
                )
            ]
        )
    )

    counts = await get_pipeline_status_counts(cast(Any, session))

    assert counts.operations_by_status == {"queued": 2, "failed": 1}
    assert counts.active_operations == 2
    assert counts.failed_operations_24h == 1


async def test_latest_dataset_batch_maps_common_root_and_selected_pair() -> None:
    at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    row = _job_row("11111111-1111-1111-1111-111111111111", at=at)
    session = _Session(_Result([row]))

    items = await list_latest_dataset_pipeline_executions(cast(Any, session))

    assert len(items) == 1
    assert items[0].provider == "python-kma-api"
    assert items[0].dataset_key == "kma_short_forecast"
    assert items[0].sync_scope == "target_grids"
    assert items[0].execution.id == "11111111-1111-1111-1111-111111111111"
    assert items[0].operation_member_id == items[0].execution.id
    assert items[0].pair_status == "running"


async def test_dataset_execution_snapshot_maps_terminal_and_active_in_one_query() -> None:
    terminal_at = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
    active_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    terminal = _job_row("11111111-1111-1111-1111-111111111111", at=terminal_at)
    terminal.status = "done"
    terminal.projected_status = "done"
    terminal.selected_pair_status = "done"
    terminal.selected_is_active = False
    active = _job_row("22222222-2222-2222-2222-222222222222", at=active_at)
    active.selected_is_active = True
    session = _Session(_Result([terminal, active]))

    snapshots = await list_dataset_pipeline_execution_snapshots(cast(Any, session))

    assert len(session.params) == 1
    assert len(snapshots) == 1
    assert snapshots[0].latest_terminal is not None
    assert snapshots[0].latest_terminal.execution.id == terminal.id
    assert snapshots[0].active is not None
    assert snapshots[0].active.execution.id == active.id


async def test_list_rejects_cursor_from_different_filter_set_before_query() -> None:
    cursor = pipeline_repo._encode_cursor(
        at=datetime(2026, 7, 15, tzinfo=UTC),
        key="11111111-1111-1111-1111-111111111111",
        item_kind="import_job",
        filter_fingerprint=pipeline_repo._filter_fingerprint(
            provider="provider-a",
        ),
    )

    with pytest.raises(PipelineCursorFilterMismatch, match="current filters"):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            provider="provider-b",
            cursor=cursor,
        )


async def test_list_rejects_noncanonical_dataset_scope_before_query() -> None:
    with pytest.raises(ValueError, match="unsupported sync_scope"):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            provider="python-kma-api",
            dataset_key="kma_short_forecast",
            dataset_sync_scopes=("default",),
        )


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


async def test_list_requires_exact_dataset_identity_for_scope_filter() -> None:
    with pytest.raises(
        ValueError,
        match="dataset_sync_scopes requires both provider and dataset_key",
    ):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            provider="python-kma-api",
            dataset_sync_scopes=("target_grids",),
        )


@pytest.mark.parametrize("field_name", ["load_batch_id", "parent_job_id"])
async def test_list_rejects_invalid_component_uuid_filter(field_name: str) -> None:
    with pytest.raises(ValueError, match=rf"{field_name} must be a UUID"):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            **{field_name: "not-a-uuid"},
        )
