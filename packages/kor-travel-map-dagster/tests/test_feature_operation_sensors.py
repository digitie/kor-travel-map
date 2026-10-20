"""provider feature operation run-status/reconciliation sensor 회귀 테스트."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from dagster import (
    DagsterInstance,
    DagsterRun,
    DagsterRunStatus,
    DefaultSensorStatus,
    RunRequest,
)
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.core.feature_operation import (
    DagsterFeatureOperationCursor,
    DagsterFeatureOperationPage,
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationMembership,
)
from kortravelmap.infra import transaction_limits
from kortravelmap.infra.transaction_limits import remaining_seconds

from kortravelmap.dagster.feature_operation_completion import (
    FEATURE_OPERATION_COMPLETION_JOB_NAME,
    FEATURE_OPERATION_COMPLETION_POOL,
)
from kortravelmap.dagster.feature_operation_sensors import (
    FEATURE_OPERATION_COMPLETION_BACKSTOP_SECONDS,
    FEATURE_OPERATION_DAGSTER_PAGE_SECONDS,
    FEATURE_OPERATION_REALERT_SECONDS,
    FEATURE_OPERATION_RECONCILE_PAGE_SIZE,
    FEATURE_OPERATION_SETTLE_LAG_SECONDS,
    FEATURE_OPERATION_STALL_AFTER_SECONDS,
    FEATURE_OPERATION_TICK_BUDGET_SECONDS,
    FEATURE_OPERATION_TRACKING_SENSORS,
    DagsterRunWatermark,
    FeatureOperationObservationError,
    FeatureOperationReconcileCursor,
    _apply_run_record,
    _dagster_run_page,
    _evaluate_reconciliation_sensor,
    _evaluate_status_event,
    _failure_of,
    _map_run_count,
    _reconcile_tick,
    apply_completion_record,
    feature_operation_reconciliation_sensor,
)
from kortravelmap.dagster.run_scope import (
    CODE_LOCATION_RUN_TAG,
    MAP_CODE_LOCATION_NAME,
    MapRunScopeMismatch,
)

_NOW = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
_JOB_NAME = "feature_place_mois_licenses_job"
_OTHER_LOCATION = "kor_travel_weather.definitions"


@dataclass
class _Run:
    run_id: str
    job_name: str
    status: DagsterRunStatus
    run_config: dict[str, object]
    tags: dict[str, str]
    asset_selection: frozenset[object] | None


@dataclass
class _Record:
    storage_id: int
    dagster_run: _Run
    create_timestamp: datetime
    start_time: float | None = None
    end_time: float | None = None


@dataclass
class _Client:
    ensure_calls: list[dict[str, Any]] = field(default_factory=list)
    reconcile_calls: list[dict[str, Any]] = field(default_factory=list)
    list_calls: list[dict[str, Any]] = field(default_factory=list)
    membership_calls: list[dict[str, Any]] = field(default_factory=list)
    ensure_outcomes: list[str] = field(default_factory=list)
    ensure_block_reasons: list[str | None] = field(default_factory=list)
    ensure_errors: list[Exception | None] = field(default_factory=list)
    ensure_error: Exception | None = None
    reconcile_error: Exception | None = None
    list_error: Exception | None = None
    page: object = field(default_factory=lambda: DagsterFeatureOperationPage((), None))
    pages: list[object] = field(default_factory=list)
    alive: bool = True
    alive_calls: list[dict[str, Any]] = field(default_factory=list)
    abandon_calls: list[dict[str, Any]] = field(default_factory=list)
    abandon_outcome: str = "recorded_without_root"
    abandon_error: Exception | None = None
    stalled_calls: list[dict[str, Any]] = field(default_factory=list)
    stalled_error: Exception | None = None
    deadlines: list[float | None] = field(default_factory=list)

    async def is_reconcilable_dagster_feature_run(self, **kwargs: Any) -> bool:
        self.alive_calls.append(kwargs)
        return self.alive

    async def abandon_dagster_feature_run(self, **kwargs: Any) -> object:
        self.abandon_calls.append(kwargs)
        if self.abandon_error is not None:
            raise self.abandon_error
        return SimpleNamespace(outcome=self.abandon_outcome, root_job_id=None)

    async def record_feature_operation_reconcile_stalled(self, **kwargs: Any) -> None:
        self.stalled_calls.append(kwargs)
        if self.stalled_error is not None:
            raise self.stalled_error

    async def ensure_dagster_feature_operation(self, **kwargs: Any) -> object:
        self.ensure_calls.append(kwargs)
        self.deadlines.append(remaining_seconds())
        if self.ensure_errors:
            error = self.ensure_errors.pop(0)
            if error is not None:
                raise error
        if self.ensure_error is not None:
            raise self.ensure_error
        outcome = self.ensure_outcomes.pop(0) if self.ensure_outcomes else "applied"
        block_reason = self.ensure_block_reasons.pop(0) if self.ensure_block_reasons else (
            "terminal" if outcome == "blocked" else None
        )
        return SimpleNamespace(outcome=outcome, block_reason=block_reason)

    async def reconcile_dagster_feature_run(self, **kwargs: Any) -> object:
        self.reconcile_calls.append(kwargs)
        if self.reconcile_error is not None:
            raise self.reconcile_error
        return SimpleNamespace(outcome="applied")

    async def list_reconcilable_dagster_feature_runs(self, **kwargs: Any) -> object:
        self.list_calls.append(kwargs)
        self.deadlines.append(remaining_seconds())
        if self.list_error is not None:
            raise self.list_error
        if self.pages:
            return self.pages.pop(0)
        return self.page

    async def resolve_feature_operation_memberships(self, **kwargs: Any) -> object:
        self.membership_calls.append(kwargs)
        return (
            ProviderDatasetOperationMembership(
                provider_dataset_id=101,
                sync_scope="dataset_wide",
                operation_key=_JOB_NAME,
            ),
        )

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        count = len(self.recorded_findings)
        return IntegrityFindingSyncResult(count, count, count)


@dataclass
class _Log:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str, *args: object) -> None:
        self.errors.append(message % args if args else message)

    def warning(self, message: str, *args: object) -> None:
        self.warnings.append(message % args if args else message)

    def info(self, message: str, *args: object) -> None:
        pass


@dataclass
class _Instance:
    records: list[_Record]
    lookup_errors: dict[str, Exception] = field(default_factory=dict)
    records_error: Exception | None = None
    scan_records: list[_Record] | None = None
    cursor_storage_ids: dict[str, int] = field(default_factory=lambda: {"previous": 1})

    def get_run_record_by_id(self, run_id: str) -> _Record | None:
        error = self.lookup_errors.get(run_id)
        if error is not None:
            raise error
        record = next(
            (record for record in self.records if record.dagster_run.run_id == run_id),
            None,
        )
        if record is not None:
            return record
        storage_id = self.cursor_storage_ids.get(run_id)
        if storage_id is None:
            return None
        return _Record(
            storage_id=storage_id,
            dagster_run=_Run(
                run_id=run_id,
                job_name="cursor_anchor",
                status=DagsterRunStatus.NOT_STARTED,
                run_config={},
                tags={},
                asset_selection=None,
            ),
            create_timestamp=_NOW - timedelta(days=1),
        )

    def get_run_records(
        self,
        filters: object | None = None,
        limit: int | None = None,
        order_by: str | None = None,
        ascending: bool = False,
        cursor: str | None = None,
    ) -> list[_Record]:
        if self.records_error is not None:
            raise self.records_error
        selected = list(self.records if self.scan_records is None else self.scan_records)
        # 실제 run storage처럼 tag filter를 AND로 적용한다 — 무시하면 좁히지 않은 조회도
        # 이 fake에서는 초록이 된다.
        for key, value in (getattr(filters, "tags", None) or {}).items():
            selected = [
                record for record in selected if record.dagster_run.tags.get(key) == value
            ]
        job_name = getattr(filters, "job_name", None)
        if job_name is not None:
            selected = [record for record in selected if record.dagster_run.job_name == job_name]
        statuses = getattr(filters, "statuses", None)
        if statuses:
            selected = [record for record in selected if record.dagster_run.status in statuses]
        created_after = getattr(filters, "created_after", None)
        created_before = getattr(filters, "created_before", None)
        if created_after is not None:
            selected = [record for record in selected if record.create_timestamp > created_after]
        if created_before is not None:
            selected = [record for record in selected if record.create_timestamp < created_before]
        if cursor is not None:
            cursor_storage_id = self.cursor_storage_ids.get(cursor)
            if cursor_storage_id is None:
                cursor_record = next(
                    (record for record in self.records if record.dagster_run.run_id == cursor),
                    None,
                )
                cursor_storage_id = cursor_record.storage_id if cursor_record is not None else None
            if cursor_storage_id is None:
                return []
            selected = [
                record
                for record in selected
                if (
                    record.storage_id > cursor_storage_id
                    if ascending
                    else record.storage_id < cursor_storage_id
                )
            ]
        if order_by == "create_timestamp":
            selected.sort(
                key=lambda record: record.create_timestamp,
                reverse=not ascending,
            )
        else:
            selected.sort(key=lambda record: record.storage_id, reverse=not ascending)
        if limit is not None:
            selected = selected[:limit]
        return selected

    def get_runs_count(self, filters: object | None = None) -> int:
        return len(self.get_run_records(filters=filters))


@dataclass
class _Context:
    instance: _Instance
    cursor: str | None = None
    log: _Log = field(default_factory=_Log)
    updated_cursors: list[str] = field(default_factory=list)
    code_location_origin: Any = None

    def update_cursor(self, cursor: str) -> None:
        self.updated_cursors.append(cursor)


def _record(
    status: DagsterRunStatus,
    *,
    run_id: str = "run-1",
    created_at: datetime = _NOW,
    registered: bool = True,
    storage_id: int = 2,
    location: str = MAP_CODE_LOCATION_NAME,
) -> _Record:
    location_tags = {CODE_LOCATION_RUN_TAG: location}
    if not registered:
        return _Record(
            storage_id=storage_id,
            dagster_run=_Run(
                run_id=run_id,
                job_name="arbitrary_user_code_job",
                status=status,
                run_config={},
                tags=dict(location_tags),
                asset_selection=None,
            ),
            create_timestamp=created_at,
            start_time=created_at.timestamp()
            if status in {DagsterRunStatus.STARTED, DagsterRunStatus.CANCELING}
            else None,
            end_time=(created_at + timedelta(minutes=1)).timestamp()
            if status
            in {
                DagsterRunStatus.SUCCESS,
                DagsterRunStatus.FAILURE,
                DagsterRunStatus.CANCELED,
            }
            else None,
        )
    start_time = None
    if status in {
        DagsterRunStatus.STARTED,
        DagsterRunStatus.CANCELING,
        DagsterRunStatus.SUCCESS,
    }:
        start_time = (created_at + timedelta(seconds=10)).timestamp()
    end_time = None
    if status in {
        DagsterRunStatus.SUCCESS,
        DagsterRunStatus.FAILURE,
        DagsterRunStatus.CANCELED,
    }:
        end_time = (created_at + timedelta(minutes=1)).timestamp()
    return _Record(
        storage_id=storage_id,
        dagster_run=_Run(
            run_id=run_id,
            job_name=_JOB_NAME,
            status=status,
            run_config={},
            tags={
                **location_tags,
                "kor_travel_map.operation_key": _JOB_NAME,
                "kor_travel_map.trigger_kind": "schedule",
            },
            asset_selection=None,
        ),
        create_timestamp=created_at,
        start_time=start_time,
        end_time=end_time,
    )


def test_tracking_sensors_are_running_and_event_sensors_monitor_only_map_location() -> None:
    assert len(FEATURE_OPERATION_TRACKING_SENSORS) == 8
    assert {sensor.name for sensor in FEATURE_OPERATION_TRACKING_SENSORS} == {
        "feature_operation_queued_sensor",
        "feature_operation_starting_sensor",
        "feature_operation_started_sensor",
        "feature_operation_canceling_sensor",
        "feature_operation_success_sensor",
        "feature_operation_failure_sensor",
        "feature_operation_canceled_sensor",
        "feature_operation_reconciliation_sensor",
    }
    for tracking_sensor in FEATURE_OPERATION_TRACKING_SENSORS:
        assert tracking_sensor.default_status == DefaultSensorStatus.RUNNING
        assert tracking_sensor.required_resource_keys == {"kor_travel_map_client"}
    # 공유 daemon에서 다른 프로젝트의 run 이벤트를 평가하지 않는다 — Dagster가 run의
    # remote origin을 sensor의 code location과 대조한다.
    for event_sensor in FEATURE_OPERATION_TRACKING_SENSORS[:-1]:
        assert event_sensor._monitor_all_code_locations is False
        assert not event_sensor._monitored_jobs
    assert feature_operation_reconciliation_sensor.minimum_interval_seconds == 30
    assert FEATURE_OPERATION_SETTLE_LAG_SECONDS == 300


@pytest.mark.parametrize(
    ("status", "expected_observed_status", "expects_started_at"),
    [
        (DagsterRunStatus.QUEUED, "QUEUED", False),
        (DagsterRunStatus.NOT_STARTED, "NOT_STARTED", False),
        (DagsterRunStatus.MANAGED, "MANAGED", False),
        (DagsterRunStatus.STARTING, "STARTING", False),
        (DagsterRunStatus.STARTED, "STARTED", True),
        (DagsterRunStatus.CANCELING, "CANCELING", True),
    ],
)
async def test_active_statuses_ensure_exact_canonical_memberships(
    status: DagsterRunStatus,
    expected_observed_status: str,
    expects_started_at: bool,
) -> None:
    client = _Client()

    outcome = await _apply_run_record(_record(status), client)

    assert outcome == "applied"
    assert len(client.ensure_calls) == 1
    call = client.ensure_calls[0]
    assert call["observed_status"] == expected_observed_status
    assert (call["engine_started_at"] is not None) is expects_started_at
    assert call["selected_memberships"] == (
        ProviderDatasetOperationMembership(
            provider_dataset_id=101,
            sync_scope="dataset_wide",
            operation_key=_JOB_NAME,
        ),
    )
    assert call["operation_key"] == _JOB_NAME
    assert client.reconcile_calls == []


@pytest.mark.parametrize(
    "status",
    [DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED],
)
async def test_pre_resource_terminal_and_direct_cancel_ensure_then_reconcile(
    status: DagsterRunStatus,
) -> None:
    client = _Client()

    await _apply_run_record(_record(status), client)

    assert client.ensure_calls[0]["observed_status"] == "NOT_STARTED"
    assert client.ensure_calls[0]["engine_started_at"] is None
    assert client.reconcile_calls[0]["terminal_status"] == status.value
    assert client.reconcile_calls[0]["engine_finished_at"] == (_NOW + timedelta(minutes=1))


async def test_duplicate_terminal_delivery_replays_same_operation_idempotently() -> None:
    client = _Client(ensure_outcomes=["applied", "noop"])
    record = _record(DagsterRunStatus.CANCELED)

    first = await _apply_run_record(record, client)
    second = await _apply_run_record(record, client)

    assert first == second == "applied"
    assert len(client.ensure_calls) == 2
    assert len(client.reconcile_calls) == 2
    assert client.ensure_calls[0] == client.ensure_calls[1]
    assert client.reconcile_calls[0] == client.reconcile_calls[1]


async def test_terminal_selection_mismatch_bypasses_ensure_conflict_to_close_root() -> None:
    conflict = FeatureOperationInvariantConflict(
        "selection changed",
        dagster_run_id="run-1",
        root_job_id="11111111-1111-4111-8111-111111111111",
        details={"selected_memberships": {"expected": [], "actual": []}},
    )
    client = _Client(ensure_error=conflict)

    outcome = await apply_completion_record(_record(DagsterRunStatus.SUCCESS), client)

    assert outcome == "applied"
    assert len(client.reconcile_calls) == 1
    assert client.reconcile_calls[0]["terminal_status"] == "SUCCESS"
    assert client.reconcile_calls[0]["error"] is None


async def test_trigger_mismatch_is_delegated_to_atomic_terminal_reconcile() -> None:
    conflict = FeatureOperationInvariantConflict(
        "trigger changed",
        dagster_run_id="run-1",
        root_job_id="11111111-1111-4111-8111-111111111111",
        details={"trigger_kind": {"expected": "schedule", "actual": "manual"}},
    )
    client = _Client(ensure_error=conflict)

    outcome = await apply_completion_record(_record(DagsterRunStatus.SUCCESS), client)

    assert outcome == "applied"
    assert len(client.reconcile_calls) == 1
    assert client.reconcile_calls[0]["trigger_kind"] == "schedule"


async def test_success_delegates_partial_child_decision_to_atomic_reconcile() -> None:
    client = _Client()

    await apply_completion_record(_record(DagsterRunStatus.SUCCESS), client)

    assert len(client.reconcile_calls) == 1
    call = client.reconcile_calls[0]
    assert call["terminal_status"] == "SUCCESS"
    assert call["selected_memberships"] == client.ensure_calls[0]["selected_memberships"]
    assert "members" not in call


async def test_terminal_without_authoritative_finish_time_is_panel_only_conflict() -> None:
    client = _Client()
    record = _record(DagsterRunStatus.FAILURE)
    record.end_time = None

    with pytest.raises(FeatureOperationObservationError, match="finish timestamp"):
        await _apply_run_record(record, client)

    assert client.ensure_calls == []
    assert client.reconcile_calls == []


@pytest.mark.parametrize("invalid_start", [None, float("nan")])
async def test_started_requires_valid_authoritative_start_time(
    invalid_start: float | None,
) -> None:
    client = _Client()
    record = _record(DagsterRunStatus.STARTED)
    record.start_time = invalid_start

    with pytest.raises(FeatureOperationObservationError, match="start timestamp"):
        await _apply_run_record(record, client)

    assert client.ensure_calls == []


async def test_naive_engine_create_time_is_rejected_before_database_write() -> None:
    client = _Client()
    record = _record(DagsterRunStatus.NOT_STARTED)
    record.create_timestamp = _NOW.replace(tzinfo=None)

    with pytest.raises(FeatureOperationObservationError, match="timezone-aware"):
        await _apply_run_record(record, client)

    assert client.ensure_calls == []


def test_dagster_insertion_cursor_pages_equal_timestamps_once_after_restart() -> None:
    records = [
        _record(
            DagsterRunStatus.NOT_STARTED,
            run_id="run-c",
            registered=False,
            storage_id=3,
        ),
        _record(
            DagsterRunStatus.NOT_STARTED,
            run_id="run-a",
            registered=False,
            storage_id=1,
        ),
        _record(
            DagsterRunStatus.NOT_STARTED,
            run_id="run-b",
            registered=False,
            storage_id=2,
        ),
        _record(
            DagsterRunStatus.NOT_STARTED,
            run_id="run-d",
            created_at=_NOW + timedelta(seconds=1),
            registered=False,
            storage_id=4,
        ),
    ]
    instance = _Instance(records)

    first = _dagster_run_page(
        instance,
        watermark=None,
        page_size=2,
        settled_before=_NOW + timedelta(seconds=2),
    )
    first_watermark = DagsterRunWatermark(
        storage_id=first[-1].storage_id,
        run_id=first[-1].dagster_run.run_id,
    )
    second = _dagster_run_page(
        instance,
        watermark=first_watermark,
        page_size=2,
        settled_before=_NOW + timedelta(seconds=2),
    )
    second_watermark = DagsterRunWatermark(
        storage_id=second[-1].storage_id,
        run_id=second[-1].dagster_run.run_id,
    )
    idle = _dagster_run_page(
        instance,
        watermark=second_watermark,
        page_size=2,
        settled_before=_NOW + timedelta(seconds=2),
    )

    assert [record.dagster_run.run_id for record in first] == ["run-a", "run-b"]
    assert [record.dagster_run.run_id for record in second] == ["run-c", "run-d"]
    assert idle == ()


async def test_settled_frontier_stops_before_first_unsettled_insertion_id() -> None:
    frontier = datetime.now(tz=UTC) - timedelta(seconds=FEATURE_OPERATION_SETTLE_LAG_SECONDS)
    anchor = _record(
        DagsterRunStatus.NOT_STARTED,
        run_id="anchor",
        created_at=frontier - timedelta(seconds=1),
        registered=False,
        storage_id=1,
    )
    unsettled = _record(
        DagsterRunStatus.NOT_STARTED,
        run_id="clock-ahead-run",
        created_at=frontier + timedelta(minutes=1),
        registered=False,
        storage_id=2,
    )
    higher_settled = _record(
        DagsterRunStatus.NOT_STARTED,
        run_id="higher-settled-run",
        created_at=frontier - timedelta(seconds=1),
        registered=False,
        storage_id=3,
    )
    instance = _Instance([anchor, unsettled, higher_settled])
    watermark = DagsterRunWatermark(1, "anchor")
    context = _Context(
        instance=instance,
        cursor=FeatureOperationReconcileCursor(dagster=watermark).to_json(),
    )

    blocked = _dagster_run_page(
        instance,
        watermark=watermark,
        page_size=200,
        settled_before=frontier,
    )
    await _reconcile_tick(context, _Client())
    blocked_cursor = FeatureOperationReconcileCursor.from_json(context.updated_cursors[-1])
    unsettled.create_timestamp = frontier - timedelta(seconds=1)
    settled = _dagster_run_page(
        instance,
        watermark=watermark,
        page_size=200,
        settled_before=frontier,
    )
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, _Client())
    settled_cursor = FeatureOperationReconcileCursor.from_json(context.updated_cursors[-1])

    assert blocked == ()
    assert blocked_cursor.dagster == watermark
    assert [record.dagster_run.run_id for record in settled] == [
        "clock-ahead-run",
        "higher-settled-run",
    ]
    assert settled_cursor.dagster == DagsterRunWatermark(3, "higher-settled-run")


def test_dagster_insertion_page_never_exceeds_declared_limit() -> None:
    records = [
        _record(
            DagsterRunStatus.NOT_STARTED,
            run_id=f"run-{storage_id}",
            registered=False,
            storage_id=storage_id,
        )
        for storage_id in range(1, 1_001)
    ]

    page = _dagster_run_page(
        _Instance(records),
        watermark=None,
        page_size=200,
        settled_before=_NOW + timedelta(seconds=1),
    )

    assert len(page) == 200
    assert [record.storage_id for record in page] == list(range(1, 201))


def test_bidirectional_cursor_round_trip_preserves_independent_watermarks() -> None:
    cursor = FeatureOperationReconcileCursor(
        dagster=DagsterRunWatermark(2, "run-2"),
        database=DagsterFeatureOperationCursor(
            created_at=_NOW - timedelta(minutes=1),
            root_job_id="11111111-1111-4111-8111-111111111111",
        ),
    )

    restored = FeatureOperationReconcileCursor.from_json(cursor.to_json())

    assert restored == cursor


async def test_database_keyset_sweep_wraps_to_beginning_after_page_end() -> None:
    database_cursor = DagsterFeatureOperationCursor(
        created_at=_NOW,
        root_job_id="11111111-1111-4111-8111-111111111111",
    )
    context = _Context(
        instance=_Instance([]),
        cursor=FeatureOperationReconcileCursor(database=database_cursor).to_json(),
    )
    client = _Client(page=DagsterFeatureOperationPage((), None))

    await _reconcile_tick(context, client)

    assert len(context.updated_cursors) == 1
    committed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[0])
    assert committed.database is None
    assert client.list_calls == [{"cursor": database_cursor, "page_size": 200}]


async def test_database_dagster_unavailable_and_not_found_preserve_base_rows() -> None:
    unavailable_id = "unavailable-run"
    missing_id = "missing-run"
    page = SimpleNamespace(
        items=(
            SimpleNamespace(dagster_run_id=unavailable_id),
            SimpleNamespace(dagster_run_id=missing_id),
        ),
        next_cursor=None,
    )
    context = _Context(
        instance=_Instance([], lookup_errors={unavailable_id: RuntimeError("Dagster unavailable")}),
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(1, "previous")
        ).to_json(),
    )
    client = _Client(page=page)

    await _reconcile_tick(context, client)

    assert client.ensure_calls == []
    assert client.reconcile_calls == []
    assert len(context.log.errors) == 2
    assert "category=storage" in context.log.errors[0]
    assert "Dagster unavailable" not in context.log.errors[0]
    assert "category=run_missing" in context.log.errors[1]
    assert FeatureOperationReconcileCursor.from_json(context.updated_cursors[0]).database is None


async def test_event_record_lookup_error_is_redacted_without_database_write() -> None:
    run_id = "event-lookup-error"
    log = _Log()
    context = SimpleNamespace(
        instance=_Instance(
            [],
            lookup_errors={run_id: RuntimeError("postgresql://admin:secret@database/internal")},
        ),
        dagster_run=SimpleNamespace(run_id=run_id),
        log=log,
    )
    client = _Client()

    await _evaluate_status_event(context, client)

    assert len(log.errors) == 1
    assert "RuntimeError" in log.errors[0]
    assert "secret" not in log.errors[0]
    assert client.ensure_calls == []
    assert client.reconcile_calls == []


async def test_event_database_write_error_is_redacted() -> None:
    record = _record(DagsterRunStatus.STARTED, run_id="event-write-error")
    context = SimpleNamespace(
        instance=_Instance([record]),
        dagster_run=SimpleNamespace(run_id=record.dagster_run.run_id),
        log=_Log(),
    )
    client = _Client(ensure_error=RuntimeError("postgresql://admin:secret@database/internal"))

    await _evaluate_status_event(context, client)

    assert len(context.log.errors) == 1
    assert "RuntimeError" in context.log.errors[0]
    assert "secret" not in context.log.errors[0]


async def test_dagster_scan_error_is_redacted_holds_the_head_and_still_commits() -> None:
    """storage 읽기 실패는 머리 시계(key=watermark run)를 타고, cursor는 그래도 commit된다."""
    context = _Context(
        instance=_Instance(
            [],
            records_error=RuntimeError("postgresql://admin:secret@dagster-storage/internal"),
        ),
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(1, "previous")
        ).to_json(),
    )

    await _evaluate_reconciliation_sensor(context, _Client())

    assert len(context.updated_cursors) == 1
    committed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[0])
    assert committed.dagster == DagsterRunWatermark(1, "previous")
    assert committed.head is not None
    assert committed.head.key == "previous"
    assert _failure_of(committed.head)["category"] == "storage"
    assert _failure_of(committed.head)["closable"] is False
    assert len(context.log.errors) == 1
    assert "RuntimeError" in context.log.errors[0]
    assert "secret" not in context.log.errors[0]


async def test_deleted_dagster_cursor_anchor_fails_loud_without_advancing() -> None:
    instance = _Instance(
        [
            _record(
                DagsterRunStatus.STARTED,
                run_id="newer-run",
                storage_id=3,
            )
        ],
        cursor_storage_ids={},
    )
    context = _Context(
        instance=instance,
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(2, "deleted-anchor")
        ).to_json(),
    )
    client = _Client()

    await _evaluate_reconciliation_sensor(context, client)

    # watermark는 제자리, 머리 시계가 돈다. DB page는 그와 상관없이 돈다(결정 2).
    committed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[0])
    assert committed.dagster == DagsterRunWatermark(2, "deleted-anchor")
    assert committed.head is not None
    assert committed.head.key == "deleted-anchor"
    assert client.ensure_calls == []
    assert len(client.list_calls) == 1
    assert context.log.errors == [
        "Dagster run storage 읽기 실패(머리 시계): error_type=FeatureOperationObservationError"
    ]


async def test_dagster_write_failure_is_redacted_and_holds_the_watermark_at_that_run() -> None:
    context = _Context(
        instance=_Instance([_record(DagsterRunStatus.STARTED)]),
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(1, "previous")
        ).to_json(),
    )
    client = _Client(ensure_error=RuntimeError("postgresql://admin:secret@database/internal"))

    await _evaluate_reconciliation_sensor(context, client)

    committed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[0])
    assert committed.dagster == DagsterRunWatermark(1, "previous")
    assert committed.head is not None
    assert committed.head.key == "run-1"
    assert len(client.list_calls) == 1
    assert len(context.log.errors) == 1
    assert "RuntimeError" in context.log.errors[0]
    assert "secret" not in context.log.errors[0]


async def test_database_page_list_error_keeps_db_cursor_but_commits_dagster_progress() -> None:
    """M2: DB page 목록 조회 실패가 Dagster 쪽 진척 commit을 막지 않는다."""
    database_cursor = DagsterFeatureOperationCursor(
        created_at=_NOW, root_job_id="11111111-1111-4111-8111-111111111111"
    )
    context = _Context(
        instance=_Instance([_record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)]),
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(1, "previous"), database=database_cursor
        ).to_json(),
    )
    client = _Client(list_error=RuntimeError("postgresql://admin:secret@database/internal"))

    await _evaluate_reconciliation_sensor(context, client)

    committed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[0])
    assert committed.dagster == DagsterRunWatermark(2, "run-1")
    assert committed.database == database_cursor
    assert len(context.log.errors) == 1
    assert "RuntimeError" in context.log.errors[0]
    assert "secret" not in context.log.errors[0]


async def test_partial_dagster_page_failure_restarts_and_replays_committed_prefix() -> None:
    records = [
        _record(DagsterRunStatus.STARTED, run_id="run-1"),
        _record(
            DagsterRunStatus.STARTED,
            run_id="run-2",
            created_at=_NOW + timedelta(seconds=1),
            storage_id=3,
        ),
    ]
    initial_cursor = FeatureOperationReconcileCursor(
        dagster=DagsterRunWatermark(1, "previous")
    ).to_json()
    context = _Context(instance=_Instance(records), cursor=initial_cursor)
    first_client = _Client(ensure_errors=[None, RuntimeError("second write failed")])

    await _reconcile_tick(context, first_client)

    assert [call["dagster_run_id"] for call in first_client.ensure_calls] == [
        "run-1",
        "run-2",
    ]
    first = FeatureOperationReconcileCursor.from_json(context.updated_cursors[0])
    assert first.dagster == DagsterRunWatermark(2, "run-1")
    assert first.head is not None
    assert first.head.key == "run-2"

    replay_context = _Context(instance=_Instance(records), cursor=context.updated_cursors[0])
    replay_client = _Client()
    await _reconcile_tick(replay_context, replay_client)

    assert [call["dagster_run_id"] for call in replay_client.ensure_calls] == ["run-2"]
    replayed = FeatureOperationReconcileCursor.from_json(replay_context.updated_cursors[0])
    assert replayed.dagster == DagsterRunWatermark(3, "run-2")
    assert replayed.head is None


async def test_database_keyset_restart_continues_then_wraps_and_revisits_start() -> None:
    first_cursor = DagsterFeatureOperationCursor(
        created_at=_NOW,
        root_job_id="11111111-1111-4111-8111-111111111111",
    )
    missing = SimpleNamespace(dagster_run_id="missing-run")
    client = _Client(
        pages=[
            SimpleNamespace(items=(missing,), next_cursor=first_cursor),
            SimpleNamespace(items=(missing,), next_cursor=None),
            SimpleNamespace(items=(missing,), next_cursor=first_cursor),
        ]
    )
    context = _Context(
        instance=_Instance([], scan_records=[]),
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(1, "previous")
        ).to_json(),
    )

    await _reconcile_tick(context, client)
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    assert [call["cursor"] for call in client.list_calls] == [
        None,
        first_cursor,
        None,
    ]
    assert FeatureOperationReconcileCursor.from_json(context.updated_cursors[1]).database is None


async def test_database_page_write_failure_skips_the_item_and_watches_it() -> None:
    record = _record(DagsterRunStatus.CANCELED, run_id="db-active-run")
    database_cursor = DagsterFeatureOperationCursor(
        created_at=_NOW - timedelta(minutes=2),
        root_job_id="11111111-1111-4111-8111-111111111111",
    )
    initial = FeatureOperationReconcileCursor(
        dagster=DagsterRunWatermark(1, "previous"),
        database=database_cursor,
    ).to_json()
    context = _Context(
        instance=_Instance([record], scan_records=[]),
        cursor=initial,
    )
    client = _Client(
        ensure_error=RuntimeError("postgresql://admin:secret@database/internal"),
        page=SimpleNamespace(
            items=(SimpleNamespace(dagster_run_id="db-active-run"),),
            next_cursor=None,
        ),
    )

    await _evaluate_reconciliation_sensor(context, client)

    committed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[0])
    assert committed.database is None  # page 끝 - 처음으로 돌아간다
    assert committed.db_watch is not None
    assert committed.db_watch.key == "db-active-run"
    assert len(context.log.errors) == 1
    assert "RuntimeError" in context.log.errors[0]
    assert "secret" not in context.log.errors[0]


def _map_runs(count: int) -> list[_Record]:
    return [
        _record(DagsterRunStatus.SUCCESS, run_id=f"map-run-{index}", storage_id=index + 1)
        for index in range(count)
    ]


async def test_storage_above_one_page_without_cursor_is_unready_and_does_not_cut_over() -> None:
    """오래 쓴 전용 instance(n150은 1,825건): 전량 재생 대신 명시 cursor를 요구한다."""

    context = _Context(instance=_Instance(_map_runs(FEATURE_OPERATION_RECONCILE_PAGE_SIZE + 1)))
    client = _Client()

    await _reconcile_tick(context, client)

    assert context.updated_cursors == []
    assert context.log.errors == [
        "non-empty Dagster storage의 reconcile cursor가 준비되지 않음; "
        "maintenance drain에서 명시 insertion cursor를 설정해야 함 "
        f"(map_runs={FEATURE_OPERATION_RECONCILE_PAGE_SIZE + 1} "
        f"> page={FEATURE_OPERATION_RECONCILE_PAGE_SIZE})"
    ]
    assert client.ensure_calls == []
    assert client.reconcile_calls == []
    assert client.list_calls == []


@pytest.mark.parametrize("count", [0, 1, 2, FEATURE_OPERATION_RECONCILE_PAGE_SIZE])
async def test_at_most_one_page_without_cursor_seeds_null_and_replays_from_start(
    count: int,
) -> None:
    """공유 plane 첫 부팅 경주: 매분 schedule·queue sensor가 reconcile 첫 tick보다 먼저 Map
    run을 만들어도 영구히 멈추지 않는다. null cursor로 시작해 처음부터 훑는다(반영은 멱등)."""

    runs = _map_runs(count)
    for record in runs:
        record.create_timestamp = datetime.now(tz=UTC) - timedelta(hours=1)
    context = _Context(instance=_Instance(runs))
    client = _Client()

    await _reconcile_tick(context, client)

    assert context.log.errors == []
    assert [
        FeatureOperationReconcileCursor.from_json(cursor) for cursor in context.updated_cursors
    ] == [FeatureOperationReconcileCursor()]
    assert client.ensure_calls == []

    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    assert context.log.errors == []
    # SUCCESS run은 sensor에서 ensure만 한다 — 완결(reconcile)은 completion run 몫이다.
    ensured = [call["dagster_run_id"] for call in client.ensure_calls]
    assert ensured == [record.dagster_run.run_id for record in runs]
    assert client.reconcile_calls == []
    resumed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[-1])
    expected = DagsterRunWatermark(count, f"map-run-{count - 1}") if count else None
    assert resumed.dagster == expected


async def test_shared_storage_with_only_other_tenant_runs_seeds_null_cursor() -> None:
    """공유 plane 첫 tick: 남의 run만 있으면 Map 범위는 비어 있다 — null cursor로 시작한다.

    좁히지 않은 조회는 weather run을 보고 "non-empty storage" 오류로 영영 멈춘다.
    """

    instance = _Instance(
        [
            _record(
                DagsterRunStatus.SUCCESS,
                run_id="weather-run",
                storage_id=5,
                registered=False,
                location=_OTHER_LOCATION,
            )
        ]
    )
    context = _Context(instance=instance)
    client = _Client()

    await _reconcile_tick(context, client)

    assert context.log.errors == []
    assert [
        FeatureOperationReconcileCursor.from_json(cursor) for cursor in context.updated_cursors
    ] == [FeatureOperationReconcileCursor()]

    # 다음 tick: 남의 run은 Dagster→DB 방향 page에 들어오지 않고, Map run만 반영된다.
    instance.records.append(
        _record(
            DagsterRunStatus.STARTED,
            run_id="map-run",
            storage_id=6,
            created_at=datetime.now(tz=UTC) - timedelta(hours=1),
        )
    )
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    assert [call["dagster_run_id"] for call in client.ensure_calls] == ["map-run"]
    resumed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[-1])
    assert resumed.dagster == DagsterRunWatermark(6, "map-run")


async def test_reconcile_refuses_a_code_location_other_than_the_scoped_one() -> None:
    """배포된 location 이름이 조회 범위와 다르면 조용히 0건을 보지 않고 크게 실패한다."""

    context = _Context(
        instance=_Instance([]),
        code_location_origin=SimpleNamespace(location_name="renamed.location"),
    )
    client = _Client()

    # SKIP으로 숨기지 않는다 — sensor 평가(다른 예외는 SkipReason으로 삼킨다)에서도 올라와
    # tick이 FAILURE로 보인다.
    with pytest.raises(MapRunScopeMismatch, match="renamed.location"):
        await _evaluate_reconciliation_sensor(context, client)

    assert context.updated_cursors == []
    assert len(context.log.errors) == 1
    assert "renamed.location" in context.log.errors[0]
    assert client.list_calls == []

    context.code_location_origin = SimpleNamespace(location_name=MAP_CODE_LOCATION_NAME)
    await _reconcile_tick(context, client)
    assert len(context.updated_cursors) == 1


def _add_run(instance: DagsterInstance, run_id: str, location: str) -> None:
    instance.add_run(
        DagsterRun(
            job_name=_JOB_NAME,
            run_id=run_id,
            status=DagsterRunStatus.SUCCESS,
            tags={CODE_LOCATION_RUN_TAG: location},
        )
    )


def test_real_run_storage_scopes_watermark_and_page_to_map_location() -> None:
    """실제 run storage의 tag join과 insertion cursor로 좁힘을 확인한다(fake가 아니라)."""

    with DagsterInstance.ephemeral() as instance:
        _add_run(instance, "weather-1", _OTHER_LOCATION)
        assert _map_run_count(instance) == 0

        _add_run(instance, "map-1", MAP_CODE_LOCATION_NAME)
        _add_run(instance, "weather-2", _OTHER_LOCATION)
        _add_run(instance, "map-2", MAP_CODE_LOCATION_NAME)
        _add_run(instance, "weather-3", _OTHER_LOCATION)

        assert _map_run_count(instance) == 2

        settled_before = datetime.now(tz=UTC) + timedelta(hours=1)
        first = _dagster_run_page(
            instance, watermark=None, page_size=1, settled_before=settled_before
        )
        assert [record.dagster_run.run_id for record in first] == ["map-1"]
        watermark = DagsterRunWatermark(first[0].storage_id, "map-1")
        rest = _dagster_run_page(
            instance, watermark=watermark, page_size=200, settled_before=settled_before
        )
        assert [record.dagster_run.run_id for record in rest] == ["map-2"]


async def test_empty_storage_cutover_keeps_dagster_cursor_null() -> None:
    instance = _Instance([])
    context = _Context(instance=instance)
    client = _Client()

    await _reconcile_tick(context, client)

    committed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[0])
    assert committed.dagster is None

    instance.records.append(
        _record(DagsterRunStatus.STARTED, run_id="first-visible-run", storage_id=1)
    )
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    assert [call["dagster_run_id"] for call in client.ensure_calls] == ["first-visible-run"]
    resumed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[-1])
    assert resumed.dagster == DagsterRunWatermark(1, "first-visible-run")


# -- guard 예외 변환 / admin 수동 run 분류 ----------------------------------


@dataclass
class _NoEnabledMembershipClient(_Client):
    """카탈로그가 실행 가능 member를 0건으로 돌려주는 상태(operation disable 등)."""

    async def resolve_feature_operation_memberships(self, **kwargs: Any) -> object:
        self.membership_calls.append(kwargs)
        return ()


async def test_unresolvable_manifest_becomes_an_observation_error_not_a_dead_tick() -> None:
    """manifest 해석 실패는 **관측 실패로 번역**된다 — tick 밖으로 새지 않는다.

    ``_reconcile_tick``은 ``FeatureOperationObservationError``만 run 단위로 집계하고
    다음 run으로 넘어간다. guard 예외가 그대로 새면 그 tick 전체가 죽어, 문제 run
    하나 때문에 나머지 active operation의 reconcile이 모두 멈춘다.
    """
    client = _NoEnabledMembershipClient()

    with pytest.raises(
        FeatureOperationObservationError,
        match="operation_has_no_enabled_memberships",
    ):
        await _apply_run_record(_record(DagsterRunStatus.SUCCESS), client)

    assert client.ensure_calls == []
    assert client.reconcile_calls == []


async def test_admin_manual_run_is_recorded_as_manual_not_schedule() -> None:
    """admin UI "지금 실행" run은 ``trigger_kind="manual"``로 기록된다.

    그 run은 schedule을 거치지 않아 ``kor_travel_map.trigger_kind`` tag가 없고,
    admin 전용 tag만 붙는다. 그 분기가 사라지면 fallback이 ``"schedule"``을 돌려주어
    수동 실행이 DB에 예약 실행으로 남는다 — 운영자 화면의 실행 이력이 조용히 거짓이
    된다.
    """
    client = _Client()
    record = _record(DagsterRunStatus.STARTED)
    record.dagster_run.tags = {
        "kor_travel_map.operation_key": _JOB_NAME,
        "kor_travel_map.admin_manual_trigger": "admin-ui",
    }

    await _apply_run_record(record, client)

    assert client.ensure_calls[0]["trigger_kind"] == "manual"
    # 대조: admin tag가 없으면 같은 tag 모양이 ``schedule``로 떨어진다.
    schedule_client = _Client()
    schedule_record = _record(DagsterRunStatus.STARTED)
    schedule_record.dagster_run.tags = {"kor_travel_map.operation_key": _JOB_NAME}

    await _apply_run_record(schedule_record, schedule_client)

    assert schedule_client.ensure_calls[0]["trigger_kind"] == "schedule"


# -- ADR-112 결정 0-1: SUCCESS 완결은 sensor 밖 completion sweep이 한다 -------------------


def _completion_run(
    *,
    run_id: str,
    status: DagsterRunStatus,
    storage_id: int,
    ended_ago: timedelta | None = None,
) -> _Record:
    end_time = (
        (datetime.now(tz=UTC) - ended_ago).timestamp() if ended_ago is not None else None
    )
    return _Record(
        storage_id=storage_id,
        dagster_run=_Run(
            run_id=run_id,
            job_name=FEATURE_OPERATION_COMPLETION_JOB_NAME,
            status=status,
            run_config={},
            tags={CODE_LOCATION_RUN_TAG: MAP_CODE_LOCATION_NAME},
            asset_selection=None,
        ),
        create_timestamp=datetime.now(tz=UTC) - timedelta(hours=1),
        end_time=end_time,
    )


def _active_root(run_id: str) -> object:
    return SimpleNamespace(
        dagster_run_id=run_id,
        created_at=_NOW,
        root_job_id="11111111-1111-4111-8111-111111111111",
    )


def _db_page_context(*records: _Record) -> _Context:
    return _Context(
        instance=_Instance(list(records), cursor_storage_ids={"previous": 100}),
        # Dagster page는 비우고(watermark가 이미 끝) DB page만 본다.
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(100, "previous")
        ).to_json(),
    )


def _db_page_client(*run_ids: str) -> _Client:
    return _Client(
        page=DagsterFeatureOperationPage(
            tuple(_active_root(run_id) for run_id in run_ids),  # type: ignore[misc]
            None,
        )
    )


async def test_sensor_success_only_ensures_and_never_reconciles() -> None:
    """sensor 경로의 SUCCESS는 root를 ensure만 한다 — 완결 CALL을 품은 reconcile을 부르지 않는다."""

    client = _Client()

    outcome = await _apply_run_record(_record(DagsterRunStatus.SUCCESS), client)

    assert outcome == "completion_pending"
    assert len(client.ensure_calls) == 1
    assert client.ensure_calls[0]["observed_status"] == "STARTED"
    assert client.reconcile_calls == []


async def test_sensor_success_conflict_on_existing_root_is_left_to_the_sweep() -> None:
    conflict = FeatureOperationInvariantConflict(
        "trigger changed",
        dagster_run_id="run-1",
        root_job_id="11111111-1111-4111-8111-111111111111",
        details={"trigger_kind": {"expected": "schedule", "actual": "manual"}},
    )
    client = _Client(ensure_error=conflict)

    outcome = await _apply_run_record(_record(DagsterRunStatus.SUCCESS), client)

    assert outcome == "completion_pending"
    assert client.reconcile_calls == []


async def test_sensor_success_conflict_without_root_still_raises_like_before() -> None:
    """root를 가리키지 않는 conflict(quarantine)는 종전 reconcile처럼 올린다."""

    conflict = FeatureOperationInvariantConflict(
        "quarantined",
        dagster_run_id="run-1",
        details={"reason": "quarantined"},
    )
    client = _Client(ensure_error=conflict)

    with pytest.raises(FeatureOperationInvariantConflict):
        await _apply_run_record(_record(DagsterRunStatus.SUCCESS), client)

    assert client.reconcile_calls == []


async def test_sensor_success_on_blocked_root_needs_no_completion() -> None:
    client = _Client(ensure_outcomes=["blocked"])

    outcome = await _apply_run_record(_record(DagsterRunStatus.SUCCESS), client)

    assert outcome == "blocked"
    assert client.reconcile_calls == []


def _status_context(record: _Record, *extra: _Record) -> Any:
    return SimpleNamespace(
        instance=_Instance([record, *extra]),
        dagster_run=record.dagster_run,
        log=_Log(),
    )


async def test_success_event_requests_a_sweep_instead_of_reconciling() -> None:
    record = _record(DagsterRunStatus.SUCCESS)
    client = _Client()

    result = await _evaluate_status_event(_status_context(record), client)

    assert isinstance(result, RunRequest)
    assert result.run_key == "feature-operation-completion:success:run-1"
    assert client.reconcile_calls == []


async def test_success_event_skips_when_a_sweep_has_not_started_yet() -> None:
    record = _record(DagsterRunStatus.SUCCESS)
    queued = _completion_run(run_id="sweep-a", status=DagsterRunStatus.QUEUED, storage_id=3)
    client = _Client()

    result = await _evaluate_status_event(_status_context(record, queued), client)

    assert not isinstance(result, RunRequest)
    assert "completion_pending" in (result.skip_message or "")


async def test_success_event_requests_again_when_the_sweep_already_started() -> None:
    """시작한 sweep은 이 root를 이미 지나쳤을 수 있다 — 새 sweep을 낸다(pool이 줄 세운다)."""

    record = _record(DagsterRunStatus.SUCCESS)
    started = _completion_run(run_id="sweep-a", status=DagsterRunStatus.STARTED, storage_id=3)

    result = await _evaluate_status_event(_status_context(record, started), _Client())

    assert isinstance(result, RunRequest)


async def test_failure_event_still_reconciles_inline() -> None:
    record = _record(DagsterRunStatus.FAILURE)
    client = _Client()

    result = await _evaluate_status_event(_status_context(record), client)

    assert not isinstance(result, RunRequest)
    assert [call["terminal_status"] for call in client.reconcile_calls] == ["FAILURE"]


async def test_completion_record_requires_a_terminal_run() -> None:
    client = _Client()

    with pytest.raises(FeatureOperationObservationError, match="terminal"):
        await apply_completion_record(_record(DagsterRunStatus.STARTED), client)

    assert client.ensure_calls == []
    assert client.reconcile_calls == []


async def test_db_page_success_root_requests_a_backstop_sweep_without_db_writes() -> None:
    context = _db_page_context(_record(DagsterRunStatus.SUCCESS, run_id="run-1"))
    client = _db_page_client("run-1")

    result = await _reconcile_tick(context, client)

    assert isinstance(result, list)
    assert [request.run_key for request in result] == [
        "feature-operation-completion:backstop:first"
    ]
    # root는 이미 있다 — ensure도 reconcile도 하지 않는다.
    assert client.ensure_calls == []
    assert client.reconcile_calls == []
    assert len(context.updated_cursors) == 1
    assert context.log.errors == []


async def test_db_page_backstop_waits_for_an_active_or_recent_sweep() -> None:
    success = _record(DagsterRunStatus.SUCCESS, run_id="run-1")
    sweep = _completion_run(
        run_id="sweep-a",
        status=DagsterRunStatus.FAILURE,
        storage_id=3,
        ended_ago=timedelta(seconds=FEATURE_OPERATION_COMPLETION_BACKSTOP_SECONDS - 60),
    )
    context = _db_page_context(success, sweep)
    client = _db_page_client("run-1")

    first = await _reconcile_tick(context, client)
    assert not isinstance(first, list)
    assert "completion_pending=1" in (first.skip_message or "")

    sweep.end_time = (
        datetime.now(tz=UTC)
        - timedelta(seconds=FEATURE_OPERATION_COMPLETION_BACKSTOP_SECONDS + 1)
    ).timestamp()
    second = await _reconcile_tick(context, client)

    assert isinstance(second, list)
    assert [request.run_key for request in second] == [
        "feature-operation-completion:backstop:after:sweep-a"
    ]

    sweep.dagster_run.status = DagsterRunStatus.STARTED
    sweep.end_time = None
    assert not isinstance(await _reconcile_tick(context, client), list)


async def test_db_page_without_success_roots_requests_nothing() -> None:
    context = _db_page_context(_record(DagsterRunStatus.STARTED, run_id="run-1"))
    client = _db_page_client("run-1")

    result = await _reconcile_tick(context, client)

    assert not isinstance(result, list)
    assert len(client.ensure_calls) == 1


async def test_backstop_lookup_failure_requests_nothing_but_commits_cursor() -> None:
    context = _db_page_context(_record(DagsterRunStatus.SUCCESS, run_id="run-1"))
    context.instance = _CompletionLookupFailingInstance(
        context.instance.records, cursor_storage_ids={"previous": 100}
    )
    client = _db_page_client("run-1")

    result = await _reconcile_tick(context, client)

    assert not isinstance(result, list)
    assert len(context.updated_cursors) == 1
    assert len(context.log.errors) == 1
    assert "RuntimeError" in context.log.errors[0]
    assert "secret" not in context.log.errors[0]


async def test_sweep_completes_only_success_roots_and_survives_one_failure() -> None:
    from kortravelmap.dagster.feature_operation_completion import (
        sweep_succeeded_feature_operations,
    )

    records = [
        _record(DagsterRunStatus.SUCCESS, run_id="ok-1", storage_id=2),
        _record(DagsterRunStatus.STARTED, run_id="running", storage_id=3),
        _record(DagsterRunStatus.SUCCESS, run_id="broken", storage_id=4),
        _record(DagsterRunStatus.SUCCESS, run_id="ok-2", storage_id=5),
    ]
    records[2].end_time = None  # 관측 오류 — 이 root만 실패하고 다음 root는 계속한다.

    class _PagedClient(_Client):
        async def list_reconcilable_dagster_feature_runs(self, **kwargs: Any) -> object:
            self.list_calls.append(kwargs)
            if kwargs["cursor"] is None:
                return DagsterFeatureOperationPage(
                    (_active_root("ok-1"), _active_root("running")),  # type: ignore[arg-type]
                    DagsterFeatureOperationCursor(created_at=_NOW, root_job_id="r"),
                )
            return DagsterFeatureOperationPage(
                (_active_root("broken"), _active_root("ok-2"), _active_root("gone")),  # type: ignore[arg-type]
                None,
            )

    client = _PagedClient()
    log = _Log()

    completed, failed = await sweep_succeeded_feature_operations(
        _Instance(records), client, log
    )

    assert completed == 2
    assert failed == ["broken"]
    assert [call["dagster_run_id"] for call in client.reconcile_calls] == ["ok-1", "ok-2"]
    assert {call["terminal_status"] for call in client.reconcile_calls} == {"SUCCESS"}
    assert len(client.list_calls) == 2
    assert len(log.errors) == 1
    assert "FeatureOperationObservationError" in log.errors[0]


@pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__` is currently in beta"
)
def test_completion_job_is_registered_pooled_and_requested_by_both_sensors() -> None:
    from kortravelmap.dagster.definitions import defs
    from kortravelmap.dagster.feature_operation_sensors import feature_operation_success_sensor

    job = defs.get_job_def(FEATURE_OPERATION_COMPLETION_JOB_NAME)
    (op_def,) = list(job.graph.iterate_op_defs())
    # pool이 run을 하나씩 돌린다 — 완결은 lineage lock 하나로 직렬화된다.
    assert op_def.pool == FEATURE_OPERATION_COMPLETION_POOL
    # operation key가 없어야 두 sensor가 이 run을 panel-only로 본다.
    assert "kor_travel_map.operation_key" not in job.tags
    for sensor_def in (
        defs.resolve_sensor_def("feature_operation_reconciliation_sensor"),
        defs.resolve_sensor_def(feature_operation_success_sensor.name),
    ):
        assert [target.job_name for target in sensor_def.targets] == [
            FEATURE_OPERATION_COMPLETION_JOB_NAME
        ]
    # 나머지 상태 sensor는 run을 내지 않는다.
    assert not defs.resolve_sensor_def("feature_operation_failure_sensor").targets


@dataclass
class _CompletionLookupFailingInstance(_Instance):
    """completion sweep 이력 조회만 실패한다(Dagster page 조회는 성공)."""

    def get_run_records(self, filters: object | None = None, **kwargs: Any) -> list[_Record]:
        if getattr(filters, "job_name", None) == FEATURE_OPERATION_COMPLETION_JOB_NAME:
            raise RuntimeError("secret storage detail")
        return super().get_run_records(filters=filters, **kwargs)


async def test_sensor_success_on_child_cancellation_still_requests_completion() -> None:
    """ensure는 child marker로도 막히지만 reconcile은 root marker로만 막힌다 — sweep이 완결한다."""

    client = _Client(ensure_outcomes=["blocked"], ensure_block_reasons=["cancellation"])

    outcome = await _apply_run_record(_record(DagsterRunStatus.SUCCESS), client)

    assert outcome == "completion_pending"
    assert client.reconcile_calls == []


async def test_status_event_for_a_panel_only_run_yields_to_the_next_event() -> None:
    """operation key 없는 run(sweep 자신)은 None — Dagster가 같은 tick에서 다음 이벤트로 간다."""

    record = _completion_run(run_id="sweep-a", status=DagsterRunStatus.SUCCESS, storage_id=3)
    client = _Client()

    assert await _evaluate_status_event(_status_context(record), client) is None
    assert client.ensure_calls == []


async def test_backstop_fires_after_a_sweep_cancelled_before_it_started() -> None:
    cancelled = _completion_run(run_id="sweep-a", status=DagsterRunStatus.CANCELED, storage_id=3)
    context = _db_page_context(_record(DagsterRunStatus.SUCCESS, run_id="run-1"), cancelled)

    result = await _reconcile_tick(context, _db_page_client("run-1"))

    assert isinstance(result, list)
    assert [request.run_key for request in result] == [
        "feature-operation-completion:backstop:after:sweep-a"
    ]


async def test_sweep_list_failure_fails_the_run_without_raw_text() -> None:
    from kortravelmap.dagster.feature_operation_completion import (
        _SweepListUnavailable,
        sweep_succeeded_feature_operations,
    )

    client = _Client(list_error=RuntimeError("postgresql://secret@db"))

    with pytest.raises(_SweepListUnavailable) as caught:
        await sweep_succeeded_feature_operations(_Instance([]), client, _Log())

    assert "RuntimeError" in str(caught.value)
    assert "secret" not in str(caught.value)


def test_completion_job_has_no_automatic_retry() -> None:
    from kortravelmap.dagster.feature_operation_completion import (
        feature_operation_completion_job,
    )

    assert feature_operation_completion_job.tags["dagster/max_retries"] == "0"


# -- ADR-112 결정 1~7: 재시도·멈춤 알림·정한 실패만 닫기 ---------------------------------------
#
# 해제 조건(tasks-acceptance §T-RECONCILE-RETRY) 한 줄마다 아래 검사가 하나 이상 맞물린다.
# 서버 쪽 상한(statement_timeout/lock_timeout)과 gate 표지의 실제 procedure 효과는
# tests/integration/test_reconcile_retry.py가 본다.


class _Clock:
    """``_utcnow``와 ``_monotonic``을 함께 움직이는 시계."""

    def __init__(self) -> None:
        self.wall = _NOW + timedelta(days=1)
        # 실제 monotonic에서 시작한다 — 서버 쪽 상한(``remaining_seconds``)은 실제 시계로 잰다.
        self.mono = time.monotonic()

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    from kortravelmap.dagster import feature_operation_sensors as sensors

    fake = _Clock()
    monkeypatch.setattr(sensors, "_utcnow", lambda: fake.wall)
    monkeypatch.setattr(sensors, "_monotonic", lambda: fake.mono)
    return fake


def _held_context(
    *records: _Record, cursor: FeatureOperationReconcileCursor | None = None
) -> _Context:
    return _Context(
        instance=_Instance(list(records)),
        cursor=(
            cursor
            if cursor is not None
            else FeatureOperationReconcileCursor(dagster=DagsterRunWatermark(1, "previous"))
        ).to_json(),
    )


def _committed(context: _Context) -> FeatureOperationReconcileCursor:
    return FeatureOperationReconcileCursor.from_json(context.updated_cursors[-1])


class _PgError(Exception):
    """asyncpg ``PostgresError`` 모양(sqlstate·constraint_name·message)."""

    def __init__(self, sqlstate: str, message: str, constraint_name: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.message = message
        self.constraint_name = constraint_name


def _sqlalchemy_error(sqlstate: str, message: str, constraint: str | None = None) -> Exception:
    """SQLAlchemy가 asyncpg 오류를 감싼 모양 — ``exc.orig.__cause__``가 asyncpg 오류다."""
    from sqlalchemy.exc import DBAPIError

    cause = _PgError(sqlstate, message, constraint)
    orig = RuntimeError(f"<class 'asyncpg.exceptions'>: {message}")
    orig.__cause__ = cause
    return DBAPIError("CALL ...", {}, orig)


# --- 잃지 않는다 -------------------------------------------------------------------------


async def test_a_run_whose_root_was_never_created_holds_the_watermark(clock: _Clock) -> None:
    """(b)는 "root가 있다"이지 "ensure를 시도했다"가 아니다 — root 없는 run은 머리가 된다.

    변이: (b)를 ensure 시도로 느슨하게 하면 watermark가 run-1을 지나가 이 검사가 빨개진다.
    """
    records = [
        _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2),
        _record(DagsterRunStatus.STARTED, run_id="run-2", storage_id=3),
    ]
    context = _held_context(*records)
    client = _Client(ensure_errors=[RuntimeError("could not serialize")])

    await _reconcile_tick(context, client)

    committed = _committed(context)
    assert committed.dagster == DagsterRunWatermark(1, "previous")
    assert committed.head is not None
    assert committed.head.key == "run-1"
    # 머리 뒤의 run은 이번 tick에 손대지 않는다.
    assert [call["dagster_run_id"] for call in client.ensure_calls] == ["run-1"]


async def test_a_run_whose_root_exists_passes_even_if_the_next_call_fails(clock: _Clock) -> None:
    """ensure가 root를 돌려줬으면 뒤따른 reconcile이 실패해도 지나간다 — DB page가 맡는다."""
    record = _record(DagsterRunStatus.FAILURE, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client(reconcile_error=_sqlalchemy_error("40001", "could not serialize"))

    await _reconcile_tick(context, client)

    committed = _committed(context)
    assert committed.dagster == DagsterRunWatermark(2, "run-1")
    assert committed.head is None


async def test_an_observation_error_waits_out_the_clock_then_leaves_a_durable_record(
    clock: _Clock,
) -> None:
    """관측 오류는 바로 지나가지 않는다. 15분 뒤 (c) 기록을 남기고서야 지나간다(결정 1·4)."""
    broken = _record(DagsterRunStatus.FAILURE, run_id="run-1", storage_id=2)
    broken.end_time = None  # terminal인데 종료 시각이 없다 — 관측 오류
    context = _held_context(broken)
    client = _Client()

    await _reconcile_tick(context, client)
    first = _committed(context)
    assert first.dagster == DagsterRunWatermark(1, "previous")
    assert first.head is not None
    assert _failure_of(first.head)["category"] == "observation"
    assert client.abandon_calls == []

    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS - 1)
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)
    assert client.abandon_calls == []
    assert _committed(context).dagster == DagsterRunWatermark(1, "previous")

    clock.advance(1)
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    assert len(client.abandon_calls) == 1
    call = client.abandon_calls[0]
    assert call["dagster_run_id"] == "run-1"
    assert call["dagster_status"] == "FAILURE"
    assert call["engine_finished_at"] is None
    assert call["first_failed_at"] == datetime.fromtimestamp(first.head.first_failed_at, tz=UTC)
    passed = _committed(context)
    assert passed.dagster == DagsterRunWatermark(2, "run-1")
    assert passed.head is None


async def test_the_head_clock_survives_a_restart_and_a_changing_signature(clock: _Clock) -> None:
    """시계는 cursor에 있다. 실패 서명이 바뀌어도 같은 run이면 처음으로 돌아가지 않는다(H3)."""
    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client(
        ensure_errors=[
            _sqlalchemy_error("53200", "out of shared memory"),
            _sqlalchemy_error("55P03", "canceling statement due to lock timeout"),
        ]
    )

    await _reconcile_tick(context, client)
    first = _committed(context).head
    assert first is not None
    clock.advance(120)
    # 재시작: 새 context, 같은 cursor 바이트.
    restarted = _Context(instance=context.instance, cursor=context.updated_cursors[-1])
    await _reconcile_tick(restarted, client)
    second = _committed(restarted).head

    assert second is not None
    assert second.first_failed_at == first.first_failed_at
    assert _failure_of(first)["sqlstate"] == "53200"
    assert _failure_of(second)["sqlstate"] == "55P03"


async def test_the_clock_starts_when_the_failed_call_returns_not_at_tick_start(
    clock: _Clock,
) -> None:
    """M3: 시계 시작은 실패한 호출이 돌아온 시각이다(tick 시작이 아니다)."""
    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    tick_started = clock.wall

    class _SlowFailingClient(_Client):
        async def ensure_dagster_feature_operation(self, **kwargs: Any) -> object:
            clock.advance(7)
            raise RuntimeError("slow failure")

    await _reconcile_tick(context, _SlowFailingClient())

    head = _committed(context).head
    assert head is not None
    assert head.first_failed_at == (tick_started + timedelta(seconds=7)).timestamp()


# --- tick 시간이 유계다 --------------------------------------------------------------------


async def test_pages_stop_starting_calls_at_their_deadlines(clock: _Clock) -> None:
    """Dagster page는 시작+20초, DB page는 시작+40초. 5초 미만이면 새 호출을 시작하지 않는다."""
    records = [
        _record(DagsterRunStatus.STARTED, run_id=f"run-{index}", storage_id=index + 1)
        for index in range(1, 6)
    ]
    roots = [_active_root(f"db-{index}") for index in range(1, 6)]
    db_records = [
        _record(DagsterRunStatus.STARTED, run_id=f"db-{index}", storage_id=100 + index)
        for index in range(1, 6)
    ]

    class _SlowClient(_Client):
        async def ensure_dagster_feature_operation(self, **kwargs: Any) -> object:
            clock.advance(8)
            return await super().ensure_dagster_feature_operation(**kwargs)

    context = _held_context(*records, *db_records)
    context.instance.scan_records = records
    client = _SlowClient(page=DagsterFeatureOperationPage(tuple(roots), None))  # type: ignore[arg-type]
    started = clock.mono

    await _reconcile_tick(context, client)

    committed = _committed(context)
    # Dagster page 항목 마감은 20 − 6(닫기·알림 몫) = 14초: t=0 → 8 → 16, run-3은 시작하지 않는다.
    assert committed.dagster == DagsterRunWatermark(3, "run-2")
    # DB page 항목 마감은 40 − 6 = 34초: t=16 목록, 16 → 24 → 32, 남은 2초라 db-3은 시작하지 않는다.
    dagster_ids = {f"run-{index}" for index in range(1, 6)}
    db_calls = [
        call["dagster_run_id"]
        for call in client.ensure_calls
        if call["dagster_run_id"] not in dagster_ids
    ]
    assert db_calls == ["db-1", "db-2"]
    # 일찍 멈춘 DB page는 마지막으로 방문한 항목에 cursor를 둔다.
    assert committed.database == DagsterFeatureOperationCursor(
        created_at=_NOW, root_job_id="11111111-1111-4111-8111-111111111111"
    )
    assert clock.mono - started <= 40
    assert len(context.updated_cursors) == 1


async def test_every_client_call_carries_its_page_deadline(clock: _Clock) -> None:
    """client 호출 안의 트랜잭션은 page 마감에서 유도한 서버 쪽 상한을 받는다(결정 2)."""
    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client()

    await _reconcile_tick(context, client)

    # sensor의 시계를 멈춰 두었으므로 남은 시간은 page 마감에서 실제 경과만큼만 줄었다.
    dagster_page, database_page = client.deadlines
    assert dagster_page is not None
    assert database_page is not None
    reserve = 6
    assert FEATURE_OPERATION_DAGSTER_PAGE_SECONDS - reserve - 5 < dagster_page <= (
        FEATURE_OPERATION_DAGSTER_PAGE_SECONDS - reserve
    )
    assert FEATURE_OPERATION_TICK_BUDGET_SECONDS - reserve - 5 < database_page <= (
        FEATURE_OPERATION_TICK_BUDGET_SECONDS - reserve
    )


async def test_a_busy_storage_worker_counts_as_a_storage_failure_without_a_new_thread(
    clock: _Clock,
) -> None:
    """앞 tick의 storage 읽기가 worker를 잡고 있으면 이번 tick은 읽지 않는다(결정 2)."""
    from kortravelmap.dagster import feature_operation_sensors as sensors

    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client()
    assert sensors._STORAGE_SLOTS.acquire(blocking=False)
    try:
        await _reconcile_tick(context, client)
    finally:
        sensors._STORAGE_SLOTS.release()

    committed = _committed(context)
    assert client.ensure_calls == []
    assert committed.head is not None
    assert _failure_of(committed.head) == {
        "category": "storage",
        "closable": False,
        "constraint": None,
        "error_type": "DeadlineExceeded",
        "sqlstate": None,
    }


# --- 알림은 경과 시간으로 ----------------------------------------------------------------


async def test_a_lock_wait_at_the_head_alerts_after_15_minutes_hourly_and_never_closes(
    clock: _Clock,
) -> None:
    """55P03 같은 일시 실패도 15분 이어지면 알린다. 닫지 않고 머리를 잡는다(O5 (i))."""
    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client(
        ensure_error=_sqlalchemy_error("55P03", "canceling statement due to lock timeout")
    )

    async def tick() -> None:
        await _reconcile_tick(context, client)
        context.cursor = context.updated_cursors[-1]

    await tick()
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS - 30)
    await tick()
    assert client.stalled_calls == []

    clock.advance(30)
    await tick()
    assert len(client.stalled_calls) == 1
    alert = client.stalled_calls[0]
    assert alert["scope"] == "head"
    assert alert["dagster_run_id"] == "run-1"
    assert alert["last_failure"]["category"] == "lock_wait"
    assert "ktmctl reconcile-abandon run-1" in alert["action"]

    clock.advance(FEATURE_OPERATION_REALERT_SECONDS - 1)
    await tick()
    assert len(client.stalled_calls) == 1
    clock.advance(1)
    await tick()
    assert len(client.stalled_calls) == 2
    assert client.abandon_calls == []
    assert _committed(context).dagster == DagsterRunWatermark(1, "previous")


async def test_a_failed_alert_write_does_not_block_progress_and_retries(clock: _Clock) -> None:
    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client(ensure_error=RuntimeError("down"), stalled_error=RuntimeError("log down"))

    await _reconcile_tick(context, client)
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS)
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    head = _committed(context).head
    assert head is not None
    assert head.alerted_at is None
    client.stalled_error = None
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)
    head = _committed(context).head
    assert head is not None
    assert head.alerted_at == clock.wall.timestamp()
    assert len(client.stalled_calls) == 2


async def test_db_watch_hands_the_slot_on_after_alerting_a_non_closable_root(
    clock: _Clock,
) -> None:
    """고칠 수 없는 root 하나가 슬롯을 영영 잡지 않는다(2차 리뷰 H2)."""
    stuck = _record(DagsterRunStatus.FAILURE, run_id="stuck", storage_id=10)
    context = _db_page_context(stuck)
    client = _db_page_client("stuck")
    client.reconcile_error = _sqlalchemy_error("42883", "function does not exist")

    async def tick() -> None:
        await _reconcile_tick(context, client)
        context.cursor = context.updated_cursors[-1]

    await tick()
    watch = _committed(context).db_watch
    assert watch is not None
    assert watch.key == "stuck"
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS)
    await tick()

    assert len(client.stalled_calls) == 1
    assert client.stalled_calls[0]["scope"] == "db_watch"
    assert client.abandon_calls == []
    assert _committed(context).db_watch is None


async def test_db_watch_is_cleared_when_the_root_is_no_longer_reconcilable(
    clock: _Clock,
) -> None:
    """매 tick 시작의 짧은 읽기(active-root 술어)에서 더는 대상이 아니면 시계를 지운다."""
    stuck = _record(DagsterRunStatus.FAILURE, run_id="stuck", storage_id=10)
    context = _db_page_context(stuck)
    client = _db_page_client("stuck")
    client.reconcile_error = RuntimeError("boom")
    await _reconcile_tick(context, client)
    context.cursor = context.updated_cursors[-1]
    assert _committed(context).db_watch is not None

    client.alive = False
    client.page = DagsterFeatureOperationPage((), None)
    await _reconcile_tick(context, client)

    assert client.alive_calls == [{"dagster_run_id": "stuck"}]
    assert _committed(context).db_watch is None


# --- gate 경합과 lock_timeout을 가른다 ---------------------------------------------------


def test_gate_busy_is_recognized_only_by_its_marker_not_by_every_55p03() -> None:
    from kortravelmap.dagster.feature_operation_sensors import _classify_failure

    gate = _sqlalchemy_error(
        "55P03", "feature-write-all gate is busy; provider curation root retries later"
    )
    lock = _sqlalchemy_error("55P03", "canceling statement due to lock timeout")

    assert _classify_failure(gate, at_head=True)["category"] == "gate_busy"
    assert _classify_failure(lock, at_head=True)["category"] == "lock_wait"
    assert _classify_failure(gate, at_head=True)["closable"] is False
    # 표지는 message에서 읽는다. str(exc)에만 있는 문구는 표지가 아니다.
    disguised = _sqlalchemy_error("55P03", "lock timeout")
    disguised.args = ("feature-write-all gate is busy",)
    assert _classify_failure(disguised, at_head=True)["category"] == "lock_wait"


# --- 닫기는 명시 목록만 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sqlstate", "constraint", "closable"),
    [
        ("22023", None, True),
        ("22P02", None, True),
        ("23502", None, True),
        ("23514", "ck_tvn40_provider_curation_root", True),
        ("23514", "ck_tvn40_provider_curation_child_set", True),
        ("23514", "ck_tvn40_provider_curation_root_replay", True),
        ("23514", "ck_tvn40_provider_terminal_members", True),
        ("23514", "ck_tvn40_provider_terminal_receipts", True),
        ("23514", "ck_tvn40_provider_operation_membership", False),
        ("23505", None, False),
        ("P0001", None, False),
        ("42501", None, False),
        ("53200", None, False),
        ("55P03", None, False),
        ("40001", None, False),
        ("57014", None, False),
        ("08006", None, False),
    ],
)
def test_only_the_named_failures_are_closable(
    sqlstate: str, constraint: str | None, closable: bool
) -> None:
    from kortravelmap.dagster.feature_operation_sensors import _classify_failure

    failure = _classify_failure(_sqlalchemy_error(sqlstate, "x", constraint), at_head=True)

    assert failure["closable"] is closable
    assert failure["sqlstate"] == sqlstate


def test_non_database_failures_close_only_as_named() -> None:
    from kortravelmap.dagster.feature_operation_sensors import _classify_failure

    conflict = FeatureOperationInvariantConflict("x", dagster_run_id="run-1")
    observation = FeatureOperationObservationError("x")
    assert _classify_failure(conflict, at_head=False)["closable"] is True
    assert _classify_failure(observation, at_head=True)["closable"] is True
    # 관측 오류는 머리에서만 닫는다.
    assert _classify_failure(observation, at_head=False)["closable"] is False
    assert _classify_failure(TimeoutError(), at_head=True)["closable"] is False
    assert _classify_failure(RuntimeError("x"), at_head=True)["closable"] is False


async def test_a_closable_head_with_a_root_is_closed_and_passed(clock: _Clock) -> None:
    record = _record(DagsterRunStatus.SUCCESS, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client(
        ensure_error=_sqlalchemy_error("23502", "null value"), abandon_outcome="closed"
    )

    await _reconcile_tick(context, client)
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS)
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    assert [call["dagster_status"] for call in client.abandon_calls] == ["SUCCESS"]
    assert client.abandon_calls[0]["engine_finished_at"] == _NOW + timedelta(minutes=1)
    assert _committed(context).dagster == DagsterRunWatermark(2, "run-1")


async def test_a_head_whose_run_is_still_active_passes_without_closing(clock: _Clock) -> None:
    """결정 4 표 "root active, Dagster active": 닫지 않고 지나간다(1b) — root가 있다."""
    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client(
        ensure_error=FeatureOperationInvariantConflict("x", dagster_run_id="run-1"),
        abandon_outcome="run_active",
    )

    await _reconcile_tick(context, client)
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS)
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    assert len(client.abandon_calls) == 1
    committed = _committed(context)
    assert committed.dagster == DagsterRunWatermark(2, "run-1")
    assert committed.head is None


async def test_an_active_run_whose_ensure_conflict_points_at_its_root_passes(
    clock: _Clock,
) -> None:
    """root를 가리키는 identity conflict는 root가 있다는 증거다(1b) — 머리를 잡지 않는다."""
    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client(
        ensure_error=FeatureOperationInvariantConflict(
            "Dagster engine start time changed during ensure",
            dagster_run_id="run-1",
            root_job_id="11111111-1111-4111-8111-111111111111",
        )
    )

    await _reconcile_tick(context, client)

    committed = _committed(context)
    assert committed.dagster == DagsterRunWatermark(2, "run-1")
    assert committed.head is None


async def test_a_lock_wait_that_uses_up_the_call_budget_still_gets_its_alert(
    clock: _Clock,
) -> None:
    """실패한 호출이 lock_timeout(남은 시간 − 4초)까지 기다려도 알림 쓸 시간이 남는다(결정 2·3)."""

    class _LockWaitClient(_Client):
        async def ensure_dagster_feature_operation(self, **kwargs: Any) -> object:
            # 서버가 lock_timeout(마감 − 4초)에서 끊을 때까지 기다린 것처럼 sensor 시계를 옮긴다.
            deadline = transaction_limits._DEADLINE.get()
            assert deadline is not None
            clock.advance(deadline - clock.mono - 4)
            raise _sqlalchemy_error("55P03", "canceling statement due to lock timeout")

    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _LockWaitClient()

    await _reconcile_tick(context, client)
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS)
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    assert [call["scope"] for call in client.stalled_calls] == ["head"]
    head = _committed(context).head
    assert head is not None
    assert head.alerted_at is not None


async def test_db_watch_handoff_rotates_to_another_failing_root(clock: _Clock) -> None:
    """알림을 낸 root는 슬롯을 다음 실패 root에게 넘긴다 — 같은 root가 도로 잡지 않는다(H2)."""
    stuck = _record(DagsterRunStatus.FAILURE, run_id="stuck", storage_id=10)
    context = _db_page_context(stuck)
    client = _db_page_client("stuck", "gone")
    client.reconcile_error = _sqlalchemy_error("42883", "function does not exist")
    client.abandon_outcome = "closed"

    async def tick() -> None:
        await _reconcile_tick(context, client)
        context.cursor = context.updated_cursors[-1]

    await tick()
    first = _committed(context).db_watch
    assert first is not None
    assert first.key == "stuck"
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS)
    await tick()

    assert [call["dagster_run_id"] for call in client.stalled_calls] == ["stuck"]
    handed = _committed(context).db_watch
    assert handed is not None
    assert handed.key == "gone"
    await tick()
    assert _committed(context).db_watch == handed  # stuck가 첫 실패여도 슬롯을 도로 잡지 않는다
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS)
    await tick()

    assert [call["dagster_run_id"] for call in client.abandon_calls] == ["gone"]
    assert client.abandon_calls[0]["dagster_status"] is None


async def test_flapping_storage_does_not_restart_the_head_clock(clock: _Clock) -> None:
    """storage 실패와 머리 run 실패가 번갈아도 같은 자리의 시계는 처음으로 돌아가지 않는다."""
    record = _record(DagsterRunStatus.STARTED, run_id="run-1", storage_id=2)
    context = _held_context(record)
    client = _Client(ensure_error=RuntimeError("down"))

    async def tick() -> None:
        await _reconcile_tick(context, client)
        context.cursor = context.updated_cursors[-1]

    await tick()
    started = _committed(context).head
    assert started is not None
    for _ in range(3):
        clock.advance(300)
        context.instance.records_error = RuntimeError("storage slow")
        await tick()
        context.instance.records_error = None
        await tick()

    head = _committed(context).head
    assert head is not None
    assert head.key == "run-1"
    assert head.first_failed_at == started.first_failed_at
    assert len(client.stalled_calls) == 1


async def test_a_watched_root_whose_run_vanished_is_closed_with_no_dagster_status(
    clock: _Clock,
) -> None:
    context = _db_page_context()
    client = _db_page_client("gone")
    client.abandon_outcome = "closed"

    await _reconcile_tick(context, client)
    context.cursor = context.updated_cursors[-1]
    watch = _committed(context).db_watch
    assert watch is not None
    assert _failure_of(watch)["category"] == "run_missing"
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS)
    await _reconcile_tick(context, client)

    assert client.abandon_calls == [
        {
            "dagster_run_id": "gone",
            "dagster_status": None,
            "engine_finished_at": None,
            "failure": _failure_of(watch),
            "first_failed_at": datetime.fromtimestamp(watch.first_failed_at, tz=UTC),
        }
    ]
    assert _committed(context).db_watch is None


async def test_a_storage_failure_at_the_head_is_never_closed(clock: _Clock) -> None:
    context = _held_context()
    context.instance.records_error = RuntimeError("storage down")
    client = _Client()

    await _reconcile_tick(context, client)
    clock.advance(FEATURE_OPERATION_STALL_AFTER_SECONDS * 4)
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, client)

    assert client.abandon_calls == []
    assert len(client.stalled_calls) == 1
    assert "storage" in client.stalled_calls[0]["action"]


# --- cursor는 비면 같은 바이트, 커져도 유계 ----------------------------------------------


def test_an_empty_cursor_is_byte_identical_to_the_previous_format() -> None:
    cursor = FeatureOperationReconcileCursor(
        dagster=DagsterRunWatermark(7, "run-7"),
        database=DagsterFeatureOperationCursor(
            created_at=_NOW, root_job_id="11111111-1111-4111-8111-111111111111"
        ),
    )

    assert cursor.to_json() == (
        '{"dagster":{"run_id":"run-7","storage_id":7},'
        '"database":{"created_at":"2026-07-01T08:00:00+00:00",'
        '"root_job_id":"11111111-1111-4111-8111-111111111111"},"version":1}'
    )
    assert FeatureOperationReconcileCursor().to_json() == (
        '{"dagster":null,"database":null,"version":1}'
    )


def test_a_full_cursor_round_trips_and_stays_small() -> None:
    from kortravelcommon.stall import StallClock
    from kortravelmap.dagster.feature_operation_sensors import _encode_failure, _failure

    long_id = "r" * 64
    failure = _failure(
        category="closable_sqlstate",
        closable=True,
        error_type="IntegrityError" * 4,
        sqlstate="23514",
        constraint="c" * 63,
    )
    head = StallClock(
        key=long_id,
        first_failed_at=_NOW.timestamp(),
        last_failure=_encode_failure(failure),
        alerted_at=_NOW.timestamp(),
    )
    assert _failure_of(head) == failure
    cursor = FeatureOperationReconcileCursor(
        dagster=DagsterRunWatermark(2**40, long_id),
        database=DagsterFeatureOperationCursor(created_at=_NOW, root_job_id=long_id),
        head=head,
        db_watch=head,
    )

    encoded = cursor.to_json()
    assert FeatureOperationReconcileCursor.from_json(encoded) == cursor
    assert '"version":1' in encoded
    assert len(encoded.encode()) < 2_000


def test_cursor_parser_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="shape"):
        FeatureOperationReconcileCursor.from_json(
            '{"dagster":null,"database":null,"version":1,"head_failure":null}'
        )


async def test_status_events_also_carry_a_server_side_deadline() -> None:
    """run-status sensor도 공용 sensor thread를 쓴다 — 반영 트랜잭션에 상한이 걸린다(결정 2)."""
    record = _record(DagsterRunStatus.STARTED)
    client = _Client()

    await _evaluate_status_event(_status_context(record), client)

    (deadline,) = client.deadlines
    assert deadline is not None
    assert 0 < deadline <= 20
