"""Dagster provider feature operation 상태 추적과 양방향 복구 sensor."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
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

FEATURE_OPERATION_RECONCILE_FAILURE_LIMIT: Final[int] = 5
"""Dagster page 머리 run이 같은 서명으로 연속 실패하면 멈춤을 알리고(닫을 수 있으면 닫는) 횟수."""

FEATURE_OPERATION_RECONCILE_BACKOFF_BASE_SECONDS: Final[int] = 30
FEATURE_OPERATION_RECONCILE_BACKOFF_MAX_SECONDS: Final[int] = 900
"""머리 run을 다시 돌기 전 기다리는 시간. 30초에서 두 배씩, 15분에서 멈춘다(ADR-111).

무거운 트랜잭션(대형 dataset root 완결)이 30초마다 다시 돌며 공유 자원을 흔들지 않게 한다.
root 완결의 gate try가 바쁜 55P03은 잠깐의 경합이라 늘리지 않고 세지도 않는다.
"""

FEATURE_OPERATION_RECONCILE_DATABASE_FAILURE_BUDGET: Final[int] = 3
FEATURE_OPERATION_RECONCILE_DATABASE_TIME_BUDGET_SECONDS: Final[float] = 20.0
"""DB page 한 tick의 예산 — 실패 세 번이나 20초가 넘으면 거기서 멈추고 다음 tick에 이어 간다.
sensor 평가 timeout(기본 60초) 안에 cursor 갱신까지 끝나게 한다."""

_GATE_BUSY_SIGNATURE: Final[str] = "SQLSTATE 55P03"

_CLOSABLE_SQLSTATE_CLASSES: Final[frozenset[str]] = frozenset({"22", "23", "P0"})

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

    def get_runs_count(self, filters: Any = None) -> int: ...


class _SensorLog(Protocol):
    def error(self, message: str, *args: object) -> None: ...


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
class HeadFailure:
    """Dagster page 머리 run의 반영이 연속 실패한 기록과 다시 돌 시각."""

    run_id: str
    signature: str
    count: int
    retry_after: datetime

    def __post_init__(self) -> None:
        _non_empty_string(self.run_id, name="head_failure run_id")
        _non_empty_string(self.signature, name="head_failure signature")
        _positive_int(self.count, name="head_failure count")
        _aware_datetime(self.retry_after, name="head_failure retry_after")


@dataclass(frozen=True)
class FeatureOperationReconcileCursor:
    """Dagster→DB watermark와 DB→Dagster keyset cursor의 단일 commit 단위.

    ``head_failure``는 Dagster page에서 반영이 실패한 **머리 run 하나**의 기록이다(ADR-111).
    그 run에서 Dagster watermark가 멈추고 — 아무것도 건너뛰지 않으므로 잃는 run이 없다 —
    ``retry_after``까지 Dagster page를 쉰다. DB page는 매 tick 돈다. 값이 없으면 JSON에 키를
    쓰지 않는다 — 그 앞 판의 cursor와 바이트가 같다. 앞 판 코드는 이 키가 있는 cursor를
    거부한다(되돌릴 때 절차는 ADR-111).
    """

    dagster: DagsterRunWatermark | None = None
    database: DagsterFeatureOperationCursor | None = None
    head_failure: HeadFailure | None = None

    def to_json(self) -> str:
        value: dict[str, object] = {
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
        if self.head_failure is not None:
            value["head_failure"] = {
                "count": self.head_failure.count,
                "retry_after": self.head_failure.retry_after.isoformat(),
                "run_id": self.head_failure.run_id,
                "signature": self.head_failure.signature,
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
        if not isinstance(raw, dict) or set(raw) - {"head_failure"} != {
            "database",
            "dagster",
            "version",
        }:
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
        head_failure = None
        head_raw = raw.get("head_failure")
        if head_raw is not None:
            if not isinstance(head_raw, dict) or set(head_raw) != {
                "count",
                "retry_after",
                "run_id",
                "signature",
            }:
                raise ValueError("reconcile head_failure shape is invalid")
            head_failure = HeadFailure(
                run_id=_non_empty_string(head_raw["run_id"], name="head_failure run_id"),
                signature=_non_empty_string(head_raw["signature"], name="head_failure signature"),
                count=_positive_int(head_raw["count"], name="head_failure count"),
                retry_after=_parse_datetime(head_raw["retry_after"]),
            )
        return cls(dagster=dagster_cursor, database=database_cursor, head_failure=head_failure)


class FeatureOperationObservationError(RuntimeError):
    """run record가 canonical DB mutation에 필요한 정보를 제공하지 못함."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _build_status_sensor(status: DagsterRunStatus) -> SensorDefinition:
    sensor_name = f"feature_operation_{status.value.lower()}_sensor"

    # 공유 daemon에서는 모든 프로젝트의 run 이벤트가 한 event log에 쌓인다. 기본값
    # (``monitor_all_code_locations=False``, ``monitored_jobs`` 없음)이면 Dagster가 run의
    # remote origin(location·repository)을 이 sensor의 것과 대조해 Map run에서만 평가한다.
    # Map의 feature-load job은 전부 이 code location 하나에 있으므로 오늘 배포에서는
    # 평가 대상이 바뀌지 않는다.
    @run_status_sensor(
        run_status=status,
        name=sensor_name,
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
    now = _utcnow()
    head = cursor.head_failure
    next_dagster_cursor = cursor.dagster
    dagster_applied = 0
    dagster_panel_only = 0
    dagster_state = "consumed"
    if head is not None and now < head.retry_after:
        # 머리 run이 물러서 있는 동안 Dagster page는 쉰다 — 그 run을 다시 돌지 않는다.
        dagster_state = f"backoff run_id={head.run_id} {head.signature} count={head.count}"
    else:
        dagster_records = _dagster_run_page(
            context.instance,
            watermark=cursor.dagster,
            page_size=FEATURE_OPERATION_RECONCILE_PAGE_SIZE,
        )
        for record in dagster_records:
            watermark = DagsterRunWatermark(
                storage_id=record.storage_id, run_id=record.dagster_run.run_id
            )
            try:
                outcome = await _apply_run_record(record, client)
            except FeatureOperationObservationError as exc:
                context.log.error("provider feature operation panel-only conflict: %s", exc)
                dagster_panel_only += 1
                next_dagster_cursor = watermark
                continue
            except Exception as exc:
                previous = head if head is not None and head.run_id == watermark.run_id else None
                head = await _head_failed(context, client, record, exc, previous, now)
                if head is not None:
                    # backpressure: 이 run에서 멈춘다. watermark는 마지막으로 반영한 run에 남는다.
                    dagster_state = (
                        f"held run_id={head.run_id} {head.signature} count={head.count}"
                    )
                    break
                next_dagster_cursor = watermark
                continue
            head = None
            next_dagster_cursor = watermark
            if outcome != "panel_only":
                dagster_applied += 1

    database_page = await client.list_reconcilable_dagster_feature_runs(
        cursor=cursor.database,
        page_size=FEATURE_OPERATION_RECONCILE_PAGE_SIZE,
    )
    (
        database_applied,
        database_observation_errors,
        database_failures,
        next_database_cursor,
    ) = await _reconcile_database_page(
        context,
        client,
        database_page,
        start=cursor.database,
        skip_run_id=head.run_id if head is not None else None,
    )

    next_cursor = FeatureOperationReconcileCursor(
        dagster=next_dagster_cursor,
        database=next_database_cursor,
        head_failure=head,
    )
    context.update_cursor(next_cursor.to_json())
    return SkipReason(
        "provider feature operation reconcile 완료: "
        f"dagster={dagster_state} "
        f"dagster_applied={dagster_applied} "
        f"dagster_panel_only={dagster_panel_only} "
        f"database_applied={database_applied} "
        f"database_observation_errors={database_observation_errors} "
        f"database_failures={database_failures}"
    )


async def _evaluate_reconciliation_sensor(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
) -> SkipReason:
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
    *,
    start: DagsterFeatureOperationCursor | None,
    skip_run_id: str | None,
) -> tuple[int, int, int, DagsterFeatureOperationCursor | None]:
    """DB 쪽 page를 예산 안에서 돈다. 다 돌면 page의 다음 cursor, 아니면 마지막으로 다룬 항목.

    실패한 항목은 세기만 하고 지나간다 — keyset이 한 바퀴 돌아 다시 집는다. 머리 run
    (``skip_run_id``)은 물러서 있는 동안 여기서도 돌지 않는다.
    """
    applied = 0
    observation_errors = 0
    failures = 0
    started = monotonic()
    last: Any = None
    for operation in page.items:
        if (
            failures >= FEATURE_OPERATION_RECONCILE_DATABASE_FAILURE_BUDGET
            or monotonic() - started > FEATURE_OPERATION_RECONCILE_DATABASE_TIME_BUDGET_SECONDS
        ):
            resume = (
                start
                if last is None
                else DagsterFeatureOperationCursor(
                    created_at=last.created_at, root_job_id=last.root_job_id
                )
            )
            return applied, observation_errors, failures, resume
        last = operation
        if operation.dagster_run_id == skip_run_id:
            continue
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
        except Exception as exc:
            failures += 1
            signature, _closable = _failure_signature(exc)
            context.log.error(
                "active feature operation 반영 실패(다음 바퀴에 다시): run_id=%s error_type=%s %s",
                operation.dagster_run_id,
                type(exc).__name__,
                signature,
            )
            continue
        if outcome != "panel_only":
            applied += 1
    return applied, observation_errors, failures, page.next_cursor


def _sqlstate(error: BaseException) -> str | None:
    """SQLAlchemy/asyncpg wrapper chain에서 PostgreSQL SQLSTATE를 찾는다."""
    seen: set[int] = set()
    pending: list[BaseException | None] = [error]
    while pending:
        current = pending.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        value = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(value, str) and value:
            return value
        # 명시적 연결(``orig``·``raise ... from``)만 따른다. ``__context__``는 처리 중에
        # 우연히 겹친 다른 예외일 수 있다.
        pending.extend((getattr(current, "orig", None), current.__cause__))
    return None


def _failure_signature(error: BaseException) -> tuple[str, bool]:
    """실패의 서명(본문 없이)과, 그 실패가 root를 닫아도 되는 결정적 실패인지."""
    sqlstate = _sqlstate(error)
    if sqlstate is None:
        return type(error).__name__, False
    return f"SQLSTATE {sqlstate}", sqlstate[:2] in _CLOSABLE_SQLSTATE_CLASSES


def _backoff_seconds(count: int, signature: str) -> int:
    if signature == _GATE_BUSY_SIGNATURE:
        return FEATURE_OPERATION_RECONCILE_BACKOFF_BASE_SECONDS
    return min(
        FEATURE_OPERATION_RECONCILE_BACKOFF_BASE_SECONDS << min(count - 1, 16),
        FEATURE_OPERATION_RECONCILE_BACKOFF_MAX_SECONDS,
    )


async def _head_failed(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
    record: _RunRecord,
    error: Exception,
    previous: HeadFailure | None,
    now: datetime,
) -> HeadFailure | None:
    """머리 run의 실패를 센다. 돌려준 값이 ``None``이면 그 run을 지나가도 된다(root가 닫혔다).

    - 55P03(root 완결의 gate가 바쁨)은 30초 고정으로 다시 하고, 멈춤·닫기로 세지 않는다.
    - 같은 서명이 5회째면 ``reconcile_stalled``를 한 번 남긴다(그 tick이 버려지면 다시 남을
      수 있다 — 적어도 한 번).
    - 서명이 데이터·불변식(22/23/P0)이고 run이 끝났으며 5회 이상이면 root를 닫는다. ``applied``와
      ``blocked``(이미 terminal)이면 지나가고, 취소 중이라 막혔으면 취소가 끝날 수 있으니 계속 한다.
    """
    run = record.dagster_run
    signature, closable = _failure_signature(error)
    same = previous is not None and previous.signature == signature
    count = previous.count + 1 if previous is not None and same else 1
    head = HeadFailure(
        run_id=run.run_id,
        signature=signature,
        count=count,
        retry_after=now + timedelta(seconds=_backoff_seconds(count, signature)),
    )
    context.log.error(
        "provider feature operation reconcile 실패 — Dagster page를 이 run에서 멈춘다: "
        f"error_type={type(error).__name__} run_id={run.run_id} {signature} "
        f"consecutive={count}/{FEATURE_OPERATION_RECONCILE_FAILURE_LIMIT} "
        f"retry_after={head.retry_after.isoformat()}"
    )
    if signature == _GATE_BUSY_SIGNATURE:
        return head
    terminal = run.status in _TERMINAL_STATUSES
    finished_at = _timestamp_datetime(record.end_time, name="Dagster finish timestamp")
    will_close = closable and terminal and finished_at is not None
    if count == FEATURE_OPERATION_RECONCILE_FAILURE_LIMIT:
        await _report_stalled(context, client, run, signature, count, will_close=will_close)
    if not will_close or count < FEATURE_OPERATION_RECONCILE_FAILURE_LIMIT:
        return head
    assert finished_at is not None
    try:
        mutation = await client.abandon_dagster_feature_run(
            dagster_run_id=run.run_id,
            terminal_status=run.status.value,
            engine_finished_at=finished_at,
            failure=signature,
            attempts=count,
        )
    except Exception as exc:
        context.log.error(
            "provider feature operation root 닫기 실패: run_id=%s error_type=%s",
            run.run_id,
            type(exc).__name__,
        )
        return head
    block_reason = getattr(mutation, "block_reason", None)
    if mutation.outcome == "applied" or block_reason == "terminal":
        context.log.error(
            "provider feature operation root를 지나간다(outcome=%s, block_reason=%s): run_id=%s %s",
            mutation.outcome,
            block_reason,
            run.run_id,
            signature,
        )
        return None
    context.log.error(
        "provider feature operation root를 아직 닫지 못했다(outcome=%s, block_reason=%s): "
        "run_id=%s — 다시 시도한다",
        mutation.outcome,
        block_reason,
        run.run_id,
    )
    return head


async def _report_stalled(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
    run: _DagsterRun,
    signature: str,
    count: int,
    *,
    will_close: bool,
) -> None:
    try:
        await client.record_feature_operation_reconcile_stalled(
            dagster_run_id=run.run_id,
            dagster_status=run.status.value,
            failure=signature,
            attempts=count,
            closable=will_close,
        )
    except Exception as exc:
        context.log.error(
            "feature_operation.reconcile_stalled 기록 실패: run_id=%s error_type=%s",
            run.run_id,
            type(exc).__name__,
        )


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
    "FEATURE_OPERATION_RECONCILE_BACKOFF_BASE_SECONDS",
    "FEATURE_OPERATION_RECONCILE_BACKOFF_MAX_SECONDS",
    "FEATURE_OPERATION_RECONCILE_CURSOR_VERSION",
    "FEATURE_OPERATION_RECONCILE_DATABASE_FAILURE_BUDGET",
    "FEATURE_OPERATION_RECONCILE_DATABASE_TIME_BUDGET_SECONDS",
    "FEATURE_OPERATION_RECONCILE_FAILURE_LIMIT",
    "FEATURE_OPERATION_RECONCILE_INTERVAL_SECONDS",
    "FEATURE_OPERATION_RECONCILE_PAGE_SIZE",
    "FEATURE_OPERATION_SETTLE_LAG_SECONDS",
    "FEATURE_OPERATION_TRACKING_SENSORS",
    "DagsterRunWatermark",
    "FeatureOperationObservationError",
    "FeatureOperationReconcileCursor",
    "HeadFailure",
    "feature_operation_canceled_sensor",
    "feature_operation_canceling_sensor",
    "feature_operation_failure_sensor",
    "feature_operation_queued_sensor",
    "feature_operation_reconciliation_sensor",
    "feature_operation_started_sensor",
    "feature_operation_starting_sensor",
    "feature_operation_success_sensor",
]
