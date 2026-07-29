"""provider feature operation run-status/reconciliation sensor 회귀 테스트."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from dagster import AssetKey, DagsterRunStatus, DefaultSensorStatus
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.core.feature_operation import (
    DagsterFeatureOperationCursor,
    DagsterFeatureOperationPage,
    FeatureOperationInvariantConflict,
)
from kortravelmap.providers.feature_operation_registry import (
    feature_operation_launch_tags,
    resolve_feature_operation_launch,
)

from kortravelmap.dagster.feature_operation_sensors import (
    FEATURE_OPERATION_SETTLE_LAG_SECONDS,
    FEATURE_OPERATION_TRACKING_SENSORS,
    DagsterRunWatermark,
    FeatureOperationObservationError,
    FeatureOperationReconcileCursor,
    _apply_run_record,
    _dagster_run_page,
    _evaluate_reconciliation_sensor,
    _evaluate_status_event,
    _reconcile_tick,
    feature_operation_reconciliation_sensor,
)

_NOW = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
_JOB_NAME = "feature_place_mois_licenses_job"


@dataclass
class _Run:
    run_id: str
    job_name: str
    status: DagsterRunStatus
    run_config: dict[str, object]
    tags: dict[str, str]
    asset_selection: frozenset[AssetKey] | None


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
    ensure_outcomes: list[str] = field(default_factory=list)
    ensure_errors: list[Exception | None] = field(default_factory=list)
    ensure_error: Exception | None = None
    reconcile_error: Exception | None = None
    list_error: Exception | None = None
    page: object = field(default_factory=lambda: DagsterFeatureOperationPage((), None))
    pages: list[object] = field(default_factory=list)

    async def ensure_dagster_feature_operation(self, **kwargs: Any) -> object:
        self.ensure_calls.append(kwargs)
        if self.ensure_errors:
            error = self.ensure_errors.pop(0)
            if error is not None:
                raise error
        if self.ensure_error is not None:
            raise self.ensure_error
        outcome = self.ensure_outcomes.pop(0) if self.ensure_outcomes else "applied"
        return SimpleNamespace(outcome=outcome)

    async def reconcile_dagster_feature_run(self, **kwargs: Any) -> object:
        self.reconcile_calls.append(kwargs)
        if self.reconcile_error is not None:
            raise self.reconcile_error
        return SimpleNamespace(outcome="applied")

    async def list_reconcilable_dagster_feature_runs(self, **kwargs: Any) -> object:
        self.list_calls.append(kwargs)
        if self.list_error is not None:
            raise self.list_error
        if self.pages:
            return self.pages.pop(0)
        return self.page

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


@dataclass
class _Instance:
    records: list[_Record]
    lookup_errors: dict[str, Exception] = field(default_factory=dict)
    records_error: Exception | None = None
    scan_records: list[_Record] | None = None
    cursor_storage_ids: dict[str, int] = field(
        default_factory=lambda: {"previous": 1}
    )

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
        selected = list(
            self.records if self.scan_records is None else self.scan_records
        )
        created_after = getattr(filters, "created_after", None)
        created_before = getattr(filters, "created_before", None)
        if created_after is not None:
            selected = [
                record
                for record in selected
                if record.create_timestamp > created_after
            ]
        if created_before is not None:
            selected = [
                record
                for record in selected
                if record.create_timestamp < created_before
            ]
        if cursor is not None:
            cursor_storage_id = self.cursor_storage_ids.get(cursor)
            if cursor_storage_id is None:
                cursor_record = next(
                    (
                        record
                        for record in self.records
                        if record.dagster_run.run_id == cursor
                    ),
                    None,
                )
                cursor_storage_id = (
                    cursor_record.storage_id if cursor_record is not None else None
                )
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


@dataclass
class _Context:
    instance: _Instance
    cursor: str | None = None
    log: _Log = field(default_factory=_Log)
    updated_cursors: list[str] = field(default_factory=list)

    def update_cursor(self, cursor: str) -> None:
        self.updated_cursors.append(cursor)


def _record(
    status: DagsterRunStatus,
    *,
    run_id: str = "run-1",
    created_at: datetime = _NOW,
    registered: bool = True,
    storage_id: int = 2,
) -> _Record:
    if not registered:
        return _Record(
            storage_id=storage_id,
            dagster_run=_Run(
                run_id=run_id,
                job_name="arbitrary_user_code_job",
                status=status,
                run_config={},
                tags={},
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
    launch = resolve_feature_operation_launch(job_name=_JOB_NAME)
    assert launch is not None
    identity, run_config = launch
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
            run_config=run_config,
            tags=feature_operation_launch_tags(identity, trigger_kind="schedule"),
            asset_selection=frozenset(
                AssetKey.from_user_string(key) for key in identity.asset_keys
            ),
        ),
        create_timestamp=created_at,
        start_time=start_time,
        end_time=end_time,
    )


def test_tracking_sensors_are_running_and_event_sensors_monitor_all_locations() -> None:
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
    for event_sensor in FEATURE_OPERATION_TRACKING_SENSORS[:-1]:
        assert event_sensor._monitor_all_code_locations is True
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
async def test_active_and_periodic_only_statuses_ensure_exact_registry_selection(
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
    assert [(pair.provider, pair.dataset_key) for pair in call["selected_pairs"]] == [
        ("python-mois-api", "mois_license_features_bulk")
    ]
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
    assert client.reconcile_calls[0]["engine_finished_at"] == (
        _NOW + timedelta(minutes=1)
    )


async def test_duplicate_terminal_delivery_replays_same_identity_idempotently() -> None:
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
        details={"selected_pairs": {"expected": [], "actual": []}},
    )
    client = _Client(ensure_error=conflict)

    outcome = await _apply_run_record(_record(DagsterRunStatus.SUCCESS), client)

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

    outcome = await _apply_run_record(_record(DagsterRunStatus.SUCCESS), client)

    assert outcome == "applied"
    assert len(client.reconcile_calls) == 1
    assert client.reconcile_calls[0]["trigger_kind"] == "schedule"


async def test_success_delegates_partial_child_decision_to_atomic_reconcile() -> None:
    client = _Client()

    await _apply_run_record(_record(DagsterRunStatus.SUCCESS), client)

    assert len(client.reconcile_calls) == 1
    call = client.reconcile_calls[0]
    assert call["terminal_status"] == "SUCCESS"
    assert call["selected_pairs"] == client.ensure_calls[0]["selected_pairs"]
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
    frontier = datetime.now(tz=UTC) - timedelta(
        seconds=FEATURE_OPERATION_SETTLE_LAG_SECONDS
    )
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
    blocked_cursor = FeatureOperationReconcileCursor.from_json(
        context.updated_cursors[-1]
    )
    unsettled.create_timestamp = frontier - timedelta(seconds=1)
    settled = _dagster_run_page(
        instance,
        watermark=watermark,
        page_size=200,
        settled_before=frontier,
    )
    context.cursor = context.updated_cursors[-1]
    await _reconcile_tick(context, _Client())
    settled_cursor = FeatureOperationReconcileCursor.from_json(
        context.updated_cursors[-1]
    )

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
        instance=_Instance(
            [], lookup_errors={unavailable_id: RuntimeError("Dagster unavailable")}
        ),
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(1, "previous")
        ).to_json(),
    )
    client = _Client(page=page)

    await _reconcile_tick(context, client)

    assert client.ensure_calls == []
    assert client.reconcile_calls == []
    assert len(context.log.errors) == 2
    assert "관측 실패" in context.log.errors[0]
    assert "Dagster unavailable" not in context.log.errors[0]
    assert "찾지 못함" in context.log.errors[1]
    assert FeatureOperationReconcileCursor.from_json(
        context.updated_cursors[0]
    ).database is None


async def test_event_record_lookup_error_is_redacted_without_database_write() -> None:
    run_id = "event-lookup-error"
    log = _Log()
    context = SimpleNamespace(
        instance=_Instance(
            [],
            lookup_errors={
                run_id: RuntimeError("postgresql://admin:secret@database/internal")
            },
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
    client = _Client(
        ensure_error=RuntimeError("postgresql://admin:secret@database/internal")
    )

    await _evaluate_status_event(context, client)

    assert len(context.log.errors) == 1
    assert "RuntimeError" in context.log.errors[0]
    assert "secret" not in context.log.errors[0]


async def test_dagster_scan_error_is_redacted_without_cursor_advance() -> None:
    context = _Context(
        instance=_Instance(
            [],
            records_error=RuntimeError(
                "postgresql://admin:secret@dagster-storage/internal"
            ),
        ),
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(1, "previous")
        ).to_json(),
    )

    await _evaluate_reconciliation_sensor(context, _Client())

    assert context.updated_cursors == []
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

    assert context.updated_cursors == []
    assert client.ensure_calls == []
    assert client.list_calls == []
    assert context.log.errors == [
        "provider feature operation reconcile 실패: "
        "error_type=FeatureOperationObservationError"
    ]


async def test_dagster_write_failure_is_redacted_and_does_not_advance_cursor() -> None:
    context = _Context(
        instance=_Instance([_record(DagsterRunStatus.STARTED)]),
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(1, "previous")
        ).to_json(),
    )
    client = _Client(
        ensure_error=RuntimeError("postgresql://admin:secret@database/internal")
    )

    await _evaluate_reconciliation_sensor(context, client)

    assert context.updated_cursors == []
    assert client.list_calls == []
    assert len(context.log.errors) == 1
    assert "RuntimeError" in context.log.errors[0]
    assert "secret" not in context.log.errors[0]


async def test_database_page_list_error_is_redacted_without_cursor_advance() -> None:
    context = _Context(
        instance=_Instance([]),
        cursor=FeatureOperationReconcileCursor(
            dagster=DagsterRunWatermark(1, "previous")
        ).to_json(),
    )
    client = _Client(
        list_error=RuntimeError("postgresql://admin:secret@database/internal")
    )

    await _evaluate_reconciliation_sensor(context, client)

    assert context.updated_cursors == []
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
    first_client = _Client(
        ensure_errors=[None, RuntimeError("second write failed")]
    )

    with pytest.raises(RuntimeError, match="second write failed"):
        await _reconcile_tick(context, first_client)

    assert [call["dagster_run_id"] for call in first_client.ensure_calls] == [
        "run-1",
        "run-2",
    ]
    assert context.updated_cursors == []

    replay_context = _Context(instance=_Instance(records), cursor=initial_cursor)
    replay_client = _Client()
    await _reconcile_tick(replay_context, replay_client)

    assert [call["dagster_run_id"] for call in replay_client.ensure_calls] == [
        "run-1",
        "run-2",
    ]
    assert len(replay_context.updated_cursors) == 1


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
    assert FeatureOperationReconcileCursor.from_json(
        context.updated_cursors[1]
    ).database is None


async def test_database_page_write_failure_keeps_both_watermarks_uncommitted() -> None:
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

    assert context.updated_cursors == []
    assert len(context.log.errors) == 1
    assert "RuntimeError" in context.log.errors[0]
    assert "secret" not in context.log.errors[0]


async def test_non_empty_storage_without_cursor_is_unready_and_does_not_cut_over() -> None:
    record = _record(
        DagsterRunStatus.SUCCESS,
        run_id="historical-registered-run",
    )
    context = _Context(instance=_Instance([record]))
    client = _Client()

    await _reconcile_tick(context, client)

    assert context.updated_cursors == []
    assert context.log.errors == [
        "non-empty Dagster storage의 reconcile cursor가 준비되지 않음; "
        "maintenance drain에서 명시 insertion cursor를 설정해야 함"
    ]
    assert client.ensure_calls == []
    assert client.reconcile_calls == []
    assert client.list_calls == []


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

    assert [call["dagster_run_id"] for call in client.ensure_calls] == [
        "first-visible-run"
    ]
    resumed = FeatureOperationReconcileCursor.from_json(context.updated_cursors[-1])
    assert resumed.dagster == DagsterRunWatermark(1, "first-visible-run")
