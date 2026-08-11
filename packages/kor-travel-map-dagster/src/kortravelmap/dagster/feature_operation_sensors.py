"""Dagster provider feature operation 상태 추적과 양방향 복구 sensor."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Protocol, TypeVar, cast

from kortravelmap.core.feature_operation import (
    TRIGGER_KIND_VALUES,
    DagsterFeatureOperationCursor,
    DagsterFeatureOperationPage,
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationMembership,
    TriggerKind,
)

from dagster import (
    DagsterRunStatus,
    DefaultSensorStatus,
    ResourceParam,
    RunStatusSensorContext,
    SensorDefinition,
    SensorEvaluationContext,
    SkipReason,
    run_status_sensor,
    sensor,
)

from .feature_operation_tracking import (
    FeatureOperationGuardUnavailable,
    declared_execution_scopes,
    resolve_run_execution_manifest,
)

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient


FEATURE_OPERATION_RECONCILE_INTERVAL_SECONDS: Final[int] = 30
"""missed event와 active DB root를 복구하는 최소 주기."""

FEATURE_OPERATION_RECONCILE_PAGE_SIZE: Final[int] = 200
"""한 tick에서 각 방향으로 처리하는 최대 run 수."""

FEATURE_OPERATION_SETTLE_LAG_SECONDS: Final[int] = 300
"""run storage transaction과 daemon/DB clock skew를 흡수하는 확정 지연."""

FEATURE_OPERATION_RECONCILE_CURSOR_VERSION: Final[int] = 1

_ACTIVE_STATUSES: Final[frozenset[DagsterRunStatus]] = frozenset(
    {
        DagsterRunStatus.QUEUED,
        DagsterRunStatus.NOT_STARTED,
        DagsterRunStatus.MANAGED,
        DagsterRunStatus.STARTING,
        DagsterRunStatus.STARTED,
        DagsterRunStatus.CANCELING,
    }
)
_TERMINAL_STATUSES: Final[frozenset[DagsterRunStatus]] = frozenset(
    {
        DagsterRunStatus.SUCCESS,
        DagsterRunStatus.FAILURE,
        DagsterRunStatus.CANCELED,
    }
)
_EVENT_STATUSES: Final[tuple[DagsterRunStatus, ...]] = (
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
    DagsterRunStatus.CANCELING,
    DagsterRunStatus.SUCCESS,
    DagsterRunStatus.FAILURE,
    DagsterRunStatus.CANCELED,
)
_T = TypeVar("_T")
_OPERATION_KEY_TAG: Final[str] = "kor_travel_map.operation_key"
_TRIGGER_KIND_TAG: Final[str] = "kor_travel_map.trigger_kind"
_ADMIN_MANUAL_TRIGGER_TAG: Final[str] = "kor_travel_map.admin_manual_trigger"


class _DagsterRun(Protocol):
    run_id: str
    job_name: str
    run_config: Mapping[str, object]
    asset_selection: Set[Any] | None
    status: DagsterRunStatus
    tags: Mapping[str, str]


class _RunRecord(Protocol):
    storage_id: int
    dagster_run: _DagsterRun
    create_timestamp: datetime
    start_time: float | None
    end_time: float | None


class _DagsterInstance(Protocol):
    def get_run_record_by_id(self, run_id: str) -> _RunRecord | None: ...

    def get_run_records(
        self,
        filters: object | None = None,
        limit: int | None = None,
        order_by: str | None = None,
        ascending: bool = False,
        cursor: str | None = None,
    ) -> Sequence[_RunRecord]: ...


class _SensorLog(Protocol):
    def error(self, message: str, *args: object) -> None: ...


class _ReconcileContext(Protocol):
    cursor: str | None
    instance: _DagsterInstance
    log: _SensorLog

    def update_cursor(self, cursor: str) -> None: ...


@dataclass(frozen=True, order=True)
class DagsterRunWatermark:
    """Dagster run storage insertion ID와 run ID의 안정적인 cursor."""

    storage_id: int
    run_id: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.storage_id, bool)
            or not isinstance(self.storage_id, int)
            or self.storage_id < 1
        ):
            raise ValueError("dagster watermark storage_id must be positive")
        if not self.run_id or self.run_id != self.run_id.strip():
            raise ValueError("dagster watermark run_id must be trimmed and non-empty")


@dataclass(frozen=True)
class FeatureOperationReconcileCursor:
    """Dagster→DB watermark와 DB→Dagster keyset cursor의 단일 commit 단위."""

    dagster: DagsterRunWatermark | None = None
    database: DagsterFeatureOperationCursor | None = None

    def to_json(self) -> str:
        value = {
            "database": (
                {
                    "created_at": self.database.created_at.isoformat(),
                    "root_job_id": self.database.root_job_id,
                }
                if self.database is not None
                else None
            ),
            "dagster": (
                {
                    "run_id": self.dagster.run_id,
                    "storage_id": self.dagster.storage_id,
                }
                if self.dagster is not None
                else None
            ),
            "version": FEATURE_OPERATION_RECONCILE_CURSOR_VERSION,
        }
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str | None) -> FeatureOperationReconcileCursor:
        if value is None:
            return cls()
        try:
            raw = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("feature operation reconcile cursor is not valid JSON") from exc
        if not isinstance(raw, dict) or set(raw) != {"database", "dagster", "version"}:
            raise ValueError("feature operation reconcile cursor shape is invalid")
        if raw["version"] != FEATURE_OPERATION_RECONCILE_CURSOR_VERSION:
            raise ValueError("feature operation reconcile cursor version is unsupported")
        dagster_raw = raw["dagster"]
        database_raw = raw["database"]
        dagster_cursor = None
        database_cursor = None
        if dagster_raw is not None:
            if not isinstance(dagster_raw, dict) or set(dagster_raw) != {
                "run_id",
                "storage_id",
            }:
                raise ValueError("dagster reconcile watermark shape is invalid")
            dagster_cursor = DagsterRunWatermark(
                storage_id=_positive_int(dagster_raw["storage_id"], name="dagster storage_id"),
                run_id=_non_empty_string(dagster_raw["run_id"], name="dagster run_id"),
            )
        if database_raw is not None:
            if not isinstance(database_raw, dict) or set(database_raw) != {
                "created_at",
                "root_job_id",
            }:
                raise ValueError("database reconcile cursor shape is invalid")
            database_cursor = DagsterFeatureOperationCursor(
                created_at=_parse_datetime(database_raw["created_at"]),
                root_job_id=_non_empty_string(
                    database_raw["root_job_id"], name="database root_job_id"
                ),
            )
        return cls(dagster=dagster_cursor, database=database_cursor)


class FeatureOperationObservationError(RuntimeError):
    """run record가 canonical DB mutation에 필요한 정보를 제공하지 못함."""


def _build_status_sensor(status: DagsterRunStatus) -> SensorDefinition:
    sensor_name = f"feature_operation_{status.value.lower()}_sensor"

    @run_status_sensor(
        run_status=status,
        name=sensor_name,
        monitor_all_code_locations=True,
        default_status=DefaultSensorStatus.RUNNING,
    )
    def _status_sensor(
        context: RunStatusSensorContext,
        kor_travel_map_client: ResourceParam[object],
    ) -> SkipReason:
        return _run_async(
            _evaluate_status_event(
                context,
                cast("AsyncKorTravelMapClient", kor_travel_map_client),
            )
        )

    return _status_sensor


feature_operation_queued_sensor: Final = _build_status_sensor(_EVENT_STATUSES[0])
feature_operation_starting_sensor: Final = _build_status_sensor(_EVENT_STATUSES[1])
feature_operation_started_sensor: Final = _build_status_sensor(_EVENT_STATUSES[2])
feature_operation_canceling_sensor: Final = _build_status_sensor(_EVENT_STATUSES[3])
feature_operation_success_sensor: Final = _build_status_sensor(_EVENT_STATUSES[4])
feature_operation_failure_sensor: Final = _build_status_sensor(_EVENT_STATUSES[5])
feature_operation_canceled_sensor: Final = _build_status_sensor(_EVENT_STATUSES[6])


@sensor(
    name="feature_operation_reconciliation_sensor",
    minimum_interval_seconds=FEATURE_OPERATION_RECONCILE_INTERVAL_SECONDS,
    default_status=DefaultSensorStatus.RUNNING,
    required_resource_keys={"kor_travel_map_client"},
)
def feature_operation_reconciliation_sensor(
    context: SensorEvaluationContext,
    kor_travel_map_client: object | None = None,
) -> SkipReason:
    client = cast(
        "AsyncKorTravelMapClient",
        kor_travel_map_client
        if kor_travel_map_client is not None
        else context.resources.kor_travel_map_client,
    )
    return _run_async(_evaluate_reconciliation_sensor(cast(_ReconcileContext, context), client))


FEATURE_OPERATION_TRACKING_SENSORS: Final = [
    feature_operation_queued_sensor,
    feature_operation_starting_sensor,
    feature_operation_started_sensor,
    feature_operation_canceling_sensor,
    feature_operation_success_sensor,
    feature_operation_failure_sensor,
    feature_operation_canceled_sensor,
    feature_operation_reconciliation_sensor,
]
"""provider feature operation 상태 추적 sensor 전체."""


async def _evaluate_status_event(
    context: RunStatusSensorContext,
    client: AsyncKorTravelMapClient,
) -> SkipReason:
    try:
        record = cast(
            "_RunRecord | None",
            context.instance.get_run_record_by_id(context.dagster_run.run_id),
        )
    except Exception as exc:
        message = (
            "provider feature operation event의 Dagster run 관측 실패: "
            f"run_id={context.dagster_run.run_id} error_type={type(exc).__name__}"
        )
        context.log.error(message)
        return SkipReason(message)
    if record is None:
        message = (
            "provider feature operation event의 Dagster run record를 찾지 못함: "
            f"run_id={context.dagster_run.run_id}"
        )
        context.log.error(message)
        return SkipReason(message)
    try:
        outcome = await _apply_run_record(record, client)
    except FeatureOperationObservationError as exc:
        context.log.error("provider feature operation panel-only conflict: %s", exc)
        return SkipReason(str(exc))
    except Exception as exc:
        message = (
            "provider feature operation event DB 반영 실패: "
            f"run_id={record.dagster_run.run_id} error_type={type(exc).__name__}"
        )
        context.log.error(message)
        return SkipReason(message)
    return SkipReason(
        "provider feature operation 상태 반영: "
        f"run_id={record.dagster_run.run_id} outcome={outcome}"
    )


async def _reconcile_tick(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
) -> SkipReason:
    if context.cursor is None:
        latest = _latest_dagster_watermark(context.instance)
        if latest is not None:
            message = (
                "non-empty Dagster storage의 reconcile cursor가 준비되지 않음; "
                "maintenance drain에서 명시 insertion cursor를 설정해야 함"
            )
            context.log.error(message)
            return SkipReason(message)
        context.update_cursor(FeatureOperationReconcileCursor().to_json())
        return SkipReason(
            "empty Dagster storage의 null insertion cursor 초기화 완료; "
            "cursor readback 뒤 다음 tick부터 양방향 reconcile 수행"
        )
    cursor = FeatureOperationReconcileCursor.from_json(context.cursor)
    dagster_records = _dagster_run_page(
        context.instance,
        watermark=cursor.dagster,
        page_size=FEATURE_OPERATION_RECONCILE_PAGE_SIZE,
    )
    dagster_applied = 0
    dagster_panel_only = 0
    for record in dagster_records:
        try:
            outcome = await _apply_run_record(record, client)
        except FeatureOperationObservationError as exc:
            context.log.error("provider feature operation panel-only conflict: %s", exc)
            dagster_panel_only += 1
            continue
        if outcome != "panel_only":
            dagster_applied += 1

    next_dagster_cursor = cursor.dagster
    if dagster_records:
        last_record = dagster_records[-1]
        next_dagster_cursor = DagsterRunWatermark(
            storage_id=last_record.storage_id,
            run_id=last_record.dagster_run.run_id,
        )

    database_page = await client.list_reconcilable_dagster_feature_runs(
        cursor=cursor.database,
        page_size=FEATURE_OPERATION_RECONCILE_PAGE_SIZE,
    )
    database_applied, database_observation_errors = await _reconcile_database_page(
        context,
        client,
        database_page,
    )

    next_cursor = FeatureOperationReconcileCursor(
        dagster=next_dagster_cursor,
        database=database_page.next_cursor,
    )
    context.update_cursor(next_cursor.to_json())
    return SkipReason(
        "provider feature operation reconcile 완료: "
        f"dagster_applied={dagster_applied} "
        f"dagster_panel_only={dagster_panel_only} "
        f"database_applied={database_applied} "
        f"database_observation_errors={database_observation_errors}"
    )


async def _evaluate_reconciliation_sensor(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
) -> SkipReason:
    try:
        return await _reconcile_tick(context, client)
    except Exception as exc:
        message = f"provider feature operation reconcile 실패: error_type={type(exc).__name__}"
        context.log.error(message)
        return SkipReason(message)


async def _reconcile_database_page(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
    page: DagsterFeatureOperationPage,
) -> tuple[int, int]:
    applied = 0
    observation_errors = 0
    for operation in page.items:
        try:
            record = context.instance.get_run_record_by_id(operation.dagster_run_id)
        except Exception as exc:
            context.log.error(
                "active feature operation의 Dagster 관측 실패: run_id=%s error_type=%s",
                operation.dagster_run_id,
                type(exc).__name__,
            )
            observation_errors += 1
            continue
        if record is None:
            context.log.error(
                "active feature operation의 Dagster run을 찾지 못함: run_id=%s",
                operation.dagster_run_id,
            )
            observation_errors += 1
            continue
        try:
            outcome = await _apply_run_record(record, client)
        except FeatureOperationObservationError as exc:
            context.log.error(
                "active feature operation의 Dagster identity 관측 실패: run_id=%s error=%s",
                operation.dagster_run_id,
                exc,
            )
            observation_errors += 1
            continue
        if outcome != "panel_only":
            applied += 1
    return applied, observation_errors


async def _apply_run_record(
    record: _RunRecord,
    client: AsyncKorTravelMapClient,
) -> str:
    run = record.dagster_run
    operation_key = _operation_key(run.tags)
    if operation_key is None:
        return "panel_only"
    trigger_kind = _trigger_kind(run.tags)
    if trigger_kind is None:
        raise FeatureOperationObservationError(
            f"operation run trigger를 해석할 수 없음: run_id={run.run_id}"
        )
    # selection은 run이 선언한 실행 manifest다 — operation의 실행 가능 scope 전체가
    # 아니다. guard(실행 중)와 이 sensor(실행 밖)가 같은 tag에서 같은 함수로
    # 유도해야 두 쪽이 서로 다른 selection을 ensure/reconcile에 넘겨 identity
    # conflict를 내지 않는다.
    try:
        memberships = await resolve_run_execution_manifest(
            client,
            operation_key=operation_key,
            declared=declared_execution_scopes(run.tags, boundary="reconcile_sensor"),
            boundary="reconcile_sensor",
        )
    except FeatureOperationGuardUnavailable as exc:
        raise FeatureOperationObservationError(
            f"run 실행 manifest를 해석할 수 없음: run_id={run.run_id} reason={exc.reason}"
        ) from exc
    created_at = _aware_datetime(record.create_timestamp, name="Dagster create timestamp")
    started_at = _timestamp_datetime(record.start_time, name="Dagster start timestamp")
    finished_at = _timestamp_datetime(record.end_time, name="Dagster finish timestamp")
    status = run.status
    if status in {DagsterRunStatus.STARTED, DagsterRunStatus.CANCELING} and started_at is None:
        raise FeatureOperationObservationError(
            f"running Dagster run에 start timestamp가 없음: run_id={run.run_id}"
        )
    if status in _TERMINAL_STATUSES and finished_at is None:
        raise FeatureOperationObservationError(
            f"terminal Dagster run에 finish timestamp가 없음: run_id={run.run_id}"
        )
    if status in _ACTIVE_STATUSES:
        mutation = await client.ensure_dagster_feature_operation(
            dagster_run_id=run.run_id,
            trigger_kind=trigger_kind,
            selected_memberships=memberships,
            operation_key=operation_key,
            engine_created_at=created_at,
            engine_started_at=started_at,
            observed_status=status.value,
        )
        return mutation.outcome
    if status not in _TERMINAL_STATUSES:
        raise FeatureOperationObservationError(
            f"지원하지 않는 Dagster run status: run_id={run.run_id} status={status.value}"
        )
    assert finished_at is not None
    return await _apply_terminal_record(
        record,
        client,
        operation_key=operation_key,
        memberships=memberships,
        trigger_kind=trigger_kind,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
    )


async def _apply_terminal_record(
    record: _RunRecord,
    client: AsyncKorTravelMapClient,
    *,
    operation_key: str,
    memberships: Sequence[ProviderDatasetOperationMembership],
    trigger_kind: TriggerKind,
    created_at: datetime,
    started_at: datetime | None,
    finished_at: datetime,
) -> str:
    run = record.dagster_run
    ensure_conflict: FeatureOperationInvariantConflict | None = None
    try:
        await client.ensure_dagster_feature_operation(
            dagster_run_id=run.run_id,
            trigger_kind=trigger_kind,
            selected_memberships=memberships,
            operation_key=operation_key,
            engine_created_at=created_at,
            engine_started_at=started_at,
            observed_status=(
                DagsterRunStatus.STARTED.value
                if started_at is not None
                else DagsterRunStatus.NOT_STARTED.value
            ),
        )
    except FeatureOperationInvariantConflict as exc:
        ensure_conflict = exc

    try:
        mutation = await client.reconcile_dagster_feature_run(
            dagster_run_id=run.run_id,
            trigger_kind=trigger_kind,
            terminal_status=run.status.value,
            selected_memberships=memberships,
            operation_key=operation_key,
            engine_created_at=created_at,
            engine_started_at=started_at,
            engine_finished_at=finished_at,
            error=_terminal_error(run),
        )
    except FeatureOperationInvariantConflict as exc:
        if ensure_conflict is not None:
            raise ensure_conflict from exc
        raise
    return mutation.outcome


def _operation_key(tags: Mapping[str, str]) -> str | None:
    value = tags.get(_OPERATION_KEY_TAG)
    if not value or value != value.strip():
        return None
    return value


def _trigger_kind(tags: Mapping[str, str]) -> TriggerKind | None:
    raw = tags.get(_TRIGGER_KIND_TAG)
    if raw in TRIGGER_KIND_VALUES:
        return raw
    if tags.get(_ADMIN_MANUAL_TRIGGER_TAG) == "admin-ui":
        return "manual"
    return "schedule" if _operation_key(tags) is not None else None


def _dagster_run_page(
    instance: _DagsterInstance,
    *,
    watermark: DagsterRunWatermark | None,
    page_size: int,
    settled_before: datetime | None = None,
) -> tuple[_RunRecord, ...]:
    limit = max(1, min(int(page_size), FEATURE_OPERATION_RECONCILE_PAGE_SIZE))
    if watermark is not None:
        anchor = instance.get_run_record_by_id(watermark.run_id)
        if anchor is None:
            raise FeatureOperationObservationError("Dagster insertion cursor anchor가 삭제됨")
        if anchor.storage_id != watermark.storage_id:
            raise FeatureOperationObservationError(
                "Dagster insertion cursor anchor storage ID가 변경됨"
            )
    cutoff = (
        _aware_datetime(settled_before, name="Dagster settled cutoff")
        if settled_before is not None
        else datetime.now(tz=UTC) - timedelta(seconds=FEATURE_OPERATION_SETTLE_LAG_SECONDS)
    )
    insertion_page = tuple(
        instance.get_run_records(
            limit=limit,
            ascending=True,
            cursor=watermark.run_id if watermark is not None else None,
        )
    )
    page_storage_ids = tuple(record.storage_id for record in insertion_page)
    if page_storage_ids != tuple(sorted(set(page_storage_ids))):
        raise FeatureOperationObservationError(
            "Dagster insertion cursor page가 strict ascending이 아님"
        )
    if watermark is not None and any(
        storage_id <= watermark.storage_id for storage_id in page_storage_ids
    ):
        raise FeatureOperationObservationError("Dagster insertion cursor가 이전 watermark를 역행함")
    records: list[_RunRecord] = []
    for record in insertion_page:
        created_at = _aware_datetime(record.create_timestamp, name="Dagster create timestamp")
        if created_at >= cutoff:
            break
        records.append(record)
    return tuple(records)


def _latest_dagster_watermark(
    instance: _DagsterInstance,
) -> DagsterRunWatermark | None:
    latest = tuple(
        instance.get_run_records(
            limit=1,
            ascending=False,
        )
    )
    if not latest:
        return None
    return DagsterRunWatermark(
        storage_id=latest[0].storage_id,
        run_id=latest[0].dagster_run.run_id,
    )


def _terminal_error(run: _DagsterRun) -> dict[str, str] | None:
    if run.status == DagsterRunStatus.SUCCESS:
        return None
    return {
        "kind": "dagster_run_terminal",
        "run_id": run.run_id,
        "status": run.status.value,
    }


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("cursor datetime must be an ISO string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("cursor datetime is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("cursor datetime must be timezone-aware")
    return parsed.astimezone(UTC)


def _aware_datetime(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FeatureOperationObservationError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp_datetime(value: float | None, *, name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FeatureOperationObservationError(f"{name} must be an epoch number")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OSError, OverflowError, ValueError) as exc:
        raise FeatureOperationObservationError(f"{name} is invalid") from exc


def _non_empty_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be trimmed and non-empty")
    return value


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _run_async(awaitable: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("Dagster sensor 평가는 running event loop 밖에서 호출해야 함.")


__all__ = [
    "FEATURE_OPERATION_RECONCILE_CURSOR_VERSION",
    "FEATURE_OPERATION_RECONCILE_INTERVAL_SECONDS",
    "FEATURE_OPERATION_RECONCILE_PAGE_SIZE",
    "FEATURE_OPERATION_SETTLE_LAG_SECONDS",
    "FEATURE_OPERATION_TRACKING_SENSORS",
    "DagsterRunWatermark",
    "FeatureOperationObservationError",
    "FeatureOperationReconcileCursor",
    "feature_operation_canceled_sensor",
    "feature_operation_canceling_sensor",
    "feature_operation_failure_sensor",
    "feature_operation_queued_sensor",
    "feature_operation_reconciliation_sensor",
    "feature_operation_started_sensor",
    "feature_operation_starting_sensor",
    "feature_operation_success_sensor",
]
