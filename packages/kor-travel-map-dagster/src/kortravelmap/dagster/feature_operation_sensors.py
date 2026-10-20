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
    DagsterFeatureOperationMutation,
    DagsterFeatureOperationPage,
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationMembership,
    TriggerKind,
)

from dagster import (
    DagsterRunStatus,
    DefaultSensorStatus,
    ResourceParam,
    RunRequest,
    RunStatusSensorContext,
    SensorDefinition,
    SensorEvaluationContext,
    SkipReason,
    run_status_sensor,
    sensor,
)

from .feature_operation_completion import (
    FEATURE_OPERATION_COMPLETION_JOB_NAME,
    feature_operation_completion_job,
)
from .feature_operation_tracking import (
    FeatureOperationGuardUnavailable,
    declared_execution_scopes,
    resolve_run_execution_manifest,
)
from .run_scope import MapRunScopeMismatch, map_runs_filter, require_map_code_location

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient


FEATURE_OPERATION_RECONCILE_INTERVAL_SECONDS: Final[int] = 30
"""missed event와 active DB root를 복구하는 최소 주기."""

FEATURE_OPERATION_RECONCILE_PAGE_SIZE: Final[int] = 200
"""한 tick에서 각 방향으로 처리하는 최대 run 수."""

FEATURE_OPERATION_SETTLE_LAG_SECONDS: Final[int] = 300
"""run storage transaction과 daemon/DB clock skew를 흡수하는 확정 지연."""

FEATURE_OPERATION_RECONCILE_CURSOR_VERSION: Final[int] = 1

FEATURE_OPERATION_COMPLETION_BACKSTOP_SECONDS: Final[int] = 900
"""reconcile sensor가 완결 대기 root를 보고 completion sweep을 다시 내기까지의 최소 간격.

1차 요청은 success 상태 sensor가 SUCCESS run마다 낸다. 이 간격은 그 요청을 놓쳤거나 sweep이
실패한 root의 뒷받침 재시도 주기다(고칠 수 없는 root도 이 주기로만 다시 시도한다)."""

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
_QUEUED_STATUSES: Final[frozenset[DagsterRunStatus]] = frozenset(
    {
        DagsterRunStatus.QUEUED,
        DagsterRunStatus.NOT_STARTED,
        DagsterRunStatus.MANAGED,
        DagsterRunStatus.STARTING,
    }
)
"""step을 아직 실행하지 않은 run — completion sweep이면 앞으로 active root 목록을 새로 읽는다."""
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
_COMPLETION_PENDING: Final[str] = "completion_pending"
"""sensor가 SUCCESS run의 root를 ensure만 하고 완결을 completion run에 넘겼다는 outcome."""


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

    def get_runs_count(self, filters: Any = None) -> int: ...


class _SensorLog(Protocol):
    def error(self, message: str, *args: object) -> None: ...

    def info(self, message: str, *args: object) -> None: ...


class _CodeLocationOrigin(Protocol):
    location_name: str


class _ReconcileContext(Protocol):
    cursor: str | None
    instance: _DagsterInstance
    log: _SensorLog

    @property
    def code_location_origin(self) -> _CodeLocationOrigin | None: ...

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

    # 공유 daemon에서는 모든 프로젝트의 run 이벤트가 한 event log에 쌓인다. 기본값
    # (``monitor_all_code_locations=False``, ``monitored_jobs`` 없음)이면 Dagster가 run의
    # remote origin(location·repository)을 이 sensor의 것과 대조해 Map run에서만 평가한다.
    # Map의 feature-load job은 전부 이 code location 하나에 있으므로 오늘 배포에서는
    # 평가 대상이 바뀌지 않는다.
    #
    # success sensor만 completion sweep job을 요청 대상으로 둔다(ADR-112 결정 0-1).
    @run_status_sensor(
        run_status=status,
        name=sensor_name,
        default_status=DefaultSensorStatus.RUNNING,
        request_job=(
            feature_operation_completion_job if status == DagsterRunStatus.SUCCESS else None
        ),
    )
    def _status_sensor(
        context: RunStatusSensorContext,
        kor_travel_map_client: ResourceParam[object],
    ) -> SkipReason | RunRequest | None:
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
    job_name=FEATURE_OPERATION_COMPLETION_JOB_NAME,
)
def feature_operation_reconciliation_sensor(
    context: SensorEvaluationContext,
    kor_travel_map_client: object | None = None,
) -> SkipReason | list[RunRequest]:
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
) -> SkipReason | RunRequest | None:
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
    if outcome == "panel_only":
        # operation key가 없는 run(completion sweep 자신 등)에는 할 일이 없다. None을 돌려주면
        # Dagster가 같은 tick에서 다음 이벤트로 넘어간다 — 그런 run이 tick을 하나씩 먹지 않는다.
        return None
    if outcome == _COMPLETION_PENDING and not _completion_sweep_queued(
        cast(_DagsterInstance, context.instance)
    ):
        # 1차 요청: SUCCESS run마다 sweep 하나. 아직 시작하지 않은 sweep이 있으면 그것이 이
        # root를 볼 것이므로 내지 않는다. 시작한 sweep은 이미 지나쳤을 수 있어 새로 낸다.
        return _completion_run_request(f"success:{record.dagster_run.run_id}")
    return SkipReason(
        "provider feature operation 상태 반영: "
        f"run_id={record.dagster_run.run_id} outcome={outcome}"
    )


async def _reconcile_tick(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
) -> SkipReason | list[RunRequest]:
    # run 조회는 ``MAP_CODE_LOCATION_NAME``으로 좁힌다. 배포된 location 이름이 다르면 좁힌
    # 조회가 조용히 0건을 돌려 reconcile이 아무것도 하지 않는다 — tick을 실패로 올린다
    # (``_evaluate_reconciliation_sensor``가 이 예외만은 삼키지 않는다).
    origin = context.code_location_origin
    require_map_code_location(origin.location_name if origin is not None else None)
    if context.cursor is None:
        # 조회는 Map code location으로 좁혀져 있다. cursor가 없을 때 Map run이 한 page 이하면
        # null cursor로 시작해 처음부터 다시 훑는다 — 반영은 멱등이다. 공유 plane 첫 부팅에서
        # 매분 schedule이나 queue sensor가 reconcile 첫 tick보다 먼저 run을 만들어도 영구히
        # 멈추지 않는다. 그보다 많으면(오래 쓴 전용 instance) 전량 재생 대신 명시 cursor를 요구한다.
        existing = _map_run_count(context.instance)
        if existing > FEATURE_OPERATION_RECONCILE_PAGE_SIZE:
            message = (
                "non-empty Dagster storage의 reconcile cursor가 준비되지 않음; "
                "maintenance drain에서 명시 insertion cursor를 설정해야 함 "
                f"(map_runs={existing} > page={FEATURE_OPERATION_RECONCILE_PAGE_SIZE})"
            )
            context.log.error(message)
            return SkipReason(message)
        context.update_cursor(FeatureOperationReconcileCursor().to_json())
        return SkipReason(
            f"Map run {existing}건(page 이하)의 null insertion cursor 초기화 완료; "
            "cursor readback 뒤 다음 tick부터 처음부터 양방향 reconcile 수행"
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
    (
        database_applied,
        database_observation_errors,
        completion_pending,
    ) = await _reconcile_database_page(
        context,
        client,
        database_page,
    )
    backstop = _completion_backstop_request(context) if completion_pending else None

    next_cursor = FeatureOperationReconcileCursor(
        dagster=next_dagster_cursor,
        database=database_page.next_cursor,
    )
    context.update_cursor(next_cursor.to_json())
    summary = (
        "provider feature operation reconcile 완료: "
        f"dagster_applied={dagster_applied} "
        f"dagster_panel_only={dagster_panel_only} "
        f"database_applied={database_applied} "
        f"database_observation_errors={database_observation_errors} "
        f"completion_pending={len(completion_pending)}"
    )
    if backstop is not None:
        context.log.info(summary)
        return [backstop]
    return SkipReason(summary)


async def _evaluate_reconciliation_sensor(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
) -> SkipReason | list[RunRequest]:
    try:
        return await _reconcile_tick(context, client)
    except MapRunScopeMismatch as exc:
        # 설정 오류는 SKIP으로 숨기지 않는다 — tick이 FAILURE로 보여야 한다.
        context.log.error(str(exc))
        raise
    except Exception as exc:
        message = f"provider feature operation reconcile 실패: error_type={type(exc).__name__}"
        context.log.error(message)
        return SkipReason(message)


async def _reconcile_database_page(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
    page: DagsterFeatureOperationPage,
) -> tuple[int, int, tuple[str, ...]]:
    """active root를 반영하고, Dagster SUCCESS인데 아직 active인 root의 run id를 모은다.

    DB page는 취소 marker·quarantine이 없는 active root만 훑는다. 그런 root의 Dagster run이
    SUCCESS면 완결이 아직 없다는 뜻이다 — completion sweep이 맡는다(ADR-112 결정 0-1). root가
    이미 있으므로 ensure도 하지 않는다(identity conflict 행을 sweep마다 다시 쓰지 않는다).
    """
    applied = 0
    observation_errors = 0
    completion_pending: list[str] = []
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
        if record.dagster_run.status == DagsterRunStatus.SUCCESS:
            completion_pending.append(record.dagster_run.run_id)
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
    return applied, observation_errors, tuple(completion_pending)


def _completion_run_request(key: str) -> RunRequest:
    return RunRequest(run_key=f"feature-operation-completion:{key}")


def _completion_sweep_queued(instance: _DagsterInstance) -> bool:
    """아직 시작하지 않은 completion sweep이 있는가. 읽기 실패면 없다고 본다(여분 요청은 무해)."""
    try:
        return (
            instance.get_runs_count(
                filters=map_runs_filter(
                    job_name=FEATURE_OPERATION_COMPLETION_JOB_NAME,
                    statuses=list(_QUEUED_STATUSES),
                )
            )
            > 0
        )
    except Exception:
        return False


def _completion_backstop_request(context: _ReconcileContext) -> RunRequest | None:
    """완결 대기 root가 보일 때의 뒷받침 요청.

    가장 최근 completion sweep이 진행 중이거나 끝난 지
    ``FEATURE_OPERATION_COMPLETION_BACKSTOP_SECONDS``가 안 됐으면 내지 않는다. run_key에 그
    sweep의 run id를 넣어, 한 sweep 뒤에는 많아야 한 번만 낸다. run storage 읽기가 실패하면 이번
    tick은 내지 않는다 — root는 active로 남고 다음 tick이 다시 본다.
    """
    try:
        latest = next(
            iter(
                context.instance.get_run_records(
                    filters=map_runs_filter(job_name=FEATURE_OPERATION_COMPLETION_JOB_NAME),
                    limit=1,
                )
            ),
            None,
        )
    except Exception as exc:
        context.log.error(
            "completion sweep 이력 조회 실패(다음 tick에 다시 본다): error_type=%s",
            type(exc).__name__,
        )
        return None
    if latest is None:
        return _completion_run_request("backstop:first")
    if latest.dagster_run.status not in _TERMINAL_STATUSES:
        return None
    # 시작 전에 취소된 run은 end_time이 없을 수 있다 — 그때는 기다릴 기준이 없으니 바로 낸다.
    if latest.end_time is not None and datetime.now(tz=UTC) - datetime.fromtimestamp(
        latest.end_time, tz=UTC
    ) < timedelta(seconds=FEATURE_OPERATION_COMPLETION_BACKSTOP_SECONDS):
        return None
    return _completion_run_request(f"backstop:after:{latest.dagster_run.run_id}")


async def apply_completion_record(
    record: _RunRecord,
    client: AsyncKorTravelMapClient,
) -> str:
    """completion run이 쓰는 반영 — terminal run을 root에 반영하고 SUCCESS면 완결까지 한다.

    sensor가 FAILURE·CANCELED에 쓰는 것과 같은 함수다. 완결 CALL은 이 경로에서만 일어난다.
    """
    if record.dagster_run.status not in _TERMINAL_STATUSES:
        raise FeatureOperationObservationError(
            "completion 대상 Dagster run이 terminal이 아님: "
            f"run_id={record.dagster_run.run_id} status={record.dagster_run.status.value}"
        )
    return await _apply_run_record(record, client, completion=True)


async def _apply_run_record(
    record: _RunRecord,
    client: AsyncKorTravelMapClient,
    *,
    completion: bool = False,
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
    if status == DagsterRunStatus.SUCCESS and not completion:
        # sensor tick에서는 SUCCESS의 root 완결(무거운 CALL)을 하지 않는다. root가 있게만 하고
        # 완결은 completion sweep에 넘긴다(ADR-112 결정 0-1).
        # FAILURE·CANCELED는 완결이 없어 아래로 간다.
        return await _ensure_success_root(
            record,
            client,
            operation_key=operation_key,
            memberships=memberships,
            trigger_kind=trigger_kind,
            created_at=created_at,
            started_at=started_at,
        )
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


async def _ensure_terminal_root(
    record: _RunRecord,
    client: AsyncKorTravelMapClient,
    *,
    operation_key: str,
    memberships: Sequence[ProviderDatasetOperationMembership],
    trigger_kind: TriggerKind,
    created_at: datetime,
    started_at: datetime | None,
) -> DagsterFeatureOperationMutation:
    """terminal run의 root를 ensure한다. identity conflict는 올린다."""
    return await client.ensure_dagster_feature_operation(
        dagster_run_id=record.dagster_run.run_id,
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


async def _ensure_success_root(
    record: _RunRecord,
    client: AsyncKorTravelMapClient,
    *,
    operation_key: str,
    memberships: Sequence[ProviderDatasetOperationMembership],
    trigger_kind: TriggerKind,
    created_at: datetime,
    started_at: datetime | None,
) -> str:
    """sensor의 SUCCESS 반영 — ensure만 하고 완결은 completion run에 넘긴다.

    identity conflict는 client가 이미 ``feature_operation.invariant_conflict``로 남겼다. conflict가
    가리키는 root가 있으면 completion sweep이 종전과 같은 reconcile로 ``tracking_invariant``를
    닫으므로 여기서는 삼키고 completion 대기로 돌려준다. root를 가리키지 않는 conflict(quarantine
    등)는 종전처럼 올린다 — 종전 reconcile도 root가 없으면 같은 conflict로 끝났다.
    이미 terminal인 root만 completion이 필요 없다. 취소로 막힌 root도 sweep을 요청한다 — root
    marker면 sweep 목록에 오지 않아 무해하고, child marker만 있으면 종전 reconcile처럼 sweep이
    완결한다(ensure는 child marker로도 막히지만 reconcile은 root marker로만 막힌다).
    """
    try:
        mutation = await _ensure_terminal_root(
            record,
            client,
            operation_key=operation_key,
            memberships=memberships,
            trigger_kind=trigger_kind,
            created_at=created_at,
            started_at=started_at,
        )
    except FeatureOperationInvariantConflict as exc:
        if exc.root_job_id is None:
            raise
        return _COMPLETION_PENDING
    if mutation.outcome == "blocked" and mutation.block_reason == "terminal":
        return mutation.outcome
    return _COMPLETION_PENDING


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
        await _ensure_terminal_root(
            record,
            client,
            operation_key=operation_key,
            memberships=memberships,
            trigger_kind=trigger_kind,
            created_at=created_at,
            started_at=started_at,
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
            filters=map_runs_filter(),
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


def _map_run_count(instance: _DagsterInstance) -> int:
    return int(instance.get_runs_count(filters=map_runs_filter()))


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
    "FEATURE_OPERATION_COMPLETION_BACKSTOP_SECONDS",
    "FEATURE_OPERATION_RECONCILE_CURSOR_VERSION",
    "FEATURE_OPERATION_RECONCILE_INTERVAL_SECONDS",
    "FEATURE_OPERATION_RECONCILE_PAGE_SIZE",
    "FEATURE_OPERATION_SETTLE_LAG_SECONDS",
    "FEATURE_OPERATION_TRACKING_SENSORS",
    "DagsterRunWatermark",
    "FeatureOperationObservationError",
    "FeatureOperationReconcileCursor",
    "apply_completion_record",
    "feature_operation_canceled_sensor",
    "feature_operation_canceling_sensor",
    "feature_operation_failure_sensor",
    "feature_operation_queued_sensor",
    "feature_operation_reconciliation_sensor",
    "feature_operation_started_sensor",
    "feature_operation_starting_sensor",
    "feature_operation_success_sensor",
]
