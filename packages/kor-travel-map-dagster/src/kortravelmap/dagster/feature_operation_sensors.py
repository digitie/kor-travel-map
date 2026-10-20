"""Dagster provider feature operation 상태 추적과 양방향 복구 sensor."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence, Set
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, Final, Protocol, TypeVar, cast

from kortravelcommon.deadline import DeadlineExceeded, call_with_deadline
from kortravelcommon.pg_errors import pg_error_info
from kortravelcommon.stall import StallClock, due_alert, mark_alerted, observe_failure
from kortravelmap.core.feature_operation import (
    TRIGGER_KIND_VALUES,
    DagsterFeatureOperation,
    DagsterFeatureOperationCursor,
    DagsterFeatureOperationMutation,
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationMembership,
    TriggerKind,
)
from kortravelmap.infra.transaction_limits import transaction_deadline

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

FEATURE_OPERATION_TICK_BUDGET_SECONDS: Final[int] = 40
"""reconcile sensor 본문의 고정 예산(ADR-112 결정 2). Dagster 평가 timeout(60초)에서 code server
thread 대기와 resource 초기화 몫 20초를 뺐다. daemon 쪽 환경 변수에서 끌어내지 않는다."""

FEATURE_OPERATION_DAGSTER_PAGE_SECONDS: Final[int] = 20
"""Dagster page 마감(본문 시작 + 20초). DB page 마감은 본문 시작 + 40초다."""

FEATURE_OPERATION_MIN_CALL_SECONDS: Final[int] = 5
"""page 마감까지 이보다 적게 남으면 새 호출을 시작하지 않는다."""

FEATURE_OPERATION_STALL_AFTER_SECONDS: Final[int] = 900
"""처음 본 실패에서 이만큼 지나면 멈춤이다 — 알리고, 정한 실패면 닫는다(결정 3·4)."""

FEATURE_OPERATION_REALERT_SECONDS: Final[int] = 3_600
"""같은 시계의 알림 사이 최소 간격(시계마다 한 시간에 한 행)."""

_CLIENT_TIMEOUT_GRACE_SECONDS: Final[float] = 3.0
"""client 쪽 ``asyncio.timeout`` = 남은 시간 + 3초. 서버 쪽 상한 뒤를 받치는 보조 장치다."""

_STATUS_EVENT_BUDGET_SECONDS: Final[float] = 20.0
"""run-status sensor 평가 하나의 DB 반영 예산(서버 쪽 상한의 기준)."""

_MAX_FAILURE_LOG_LINES: Final[int] = 3
"""한 tick의 실패 로그 줄 수 상한. 나머지는 요약의 개수로만 남긴다."""

_STORAGE_SLOTS: Final = threading.BoundedSemaphore(1)
"""Dagster run storage 동기 읽기의 worker 하나. 앞 tick의 읽기가 아직 돌아오지 않았으면 이번
tick은 storage를 읽지 않고 storage 실패로 센다 — thread가 쌓이지 않는다(결정 2)."""

_ACTION_RESERVE_SECONDS: Final[float] = 6.0
"""page 마감 앞에 남겨 두는 몫. 항목 반영은 그만큼 일찍 끊고, 남은 몫으로 닫기·알림을 한다 —
실패한 호출이 lock_timeout까지 기다려도 멈춤 알림이 시간 부족으로 굶지 않는다."""

_STORAGE_START_KEY: Final[str] = "dagster-storage-start"
"""watermark가 아직 없을 때 storage 실패 시계의 key."""

_GATE_BUSY_MARKER: Final[str] = "feature-write-all gate is busy"
"""root 완결이 gate를 잡지 못했다는 표지. 55P03이면서 message가 이것으로 시작해야 한다(결정 5)."""

_CLOSABLE_CHECK_CONSTRAINTS: Final[frozenset[str]] = frozenset(
    {
        "ck_tvn40_provider_curation_root",
        "ck_tvn40_provider_curation_child_set",
        "ck_tvn40_provider_curation_root_replay",
        "ck_tvn40_provider_terminal_members",
        "ck_tvn40_provider_terminal_receipts",
    }
)
"""닫을 수 있는 23514 constraint(결정 4). 모두 취소 root lock을 든 뒤의 receipt·terminal 불일치다.
``ck_tvn40_provider_operation_membership``은 운영자가 dataset을 끄기만 해도 나므로 넣지 않는다."""

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


_CURSOR_REQUIRED_KEYS: Final[frozenset[str]] = frozenset({"database", "dagster", "version"})
_CURSOR_OPTIONAL_KEYS: Final[frozenset[str]] = frozenset({"head", "db_watch"})


def _clock_to_cursor(clock: StallClock) -> dict[str, Any]:
    """cursor의 시계 모양 — ADR-112 결정 3의 ``{run_id, first_failed_at, last_failure, alerted_at}``.

    kor-travel-common ``StallClock``(시각은 epoch 초, 실패 서명은 200자 이하 문자열)을 그대로 싣되
    대상 key를 ``run_id``라 부른다. cursor 키는 Map이 정한다.
    """
    value = clock.to_dict()
    value["run_id"] = value.pop("key")
    return value


def _clock_from_cursor(raw: object, *, name: str) -> StallClock:
    if not isinstance(raw, dict) or set(raw) != {
        "alerted_at",
        "first_failed_at",
        "last_failure",
        "run_id",
    }:
        raise ValueError(f"reconcile cursor {name} shape is invalid")
    value = dict(raw)
    value["key"] = value.pop("run_id")
    try:
        clock = StallClock.from_dict(value)
        _decode_failure(clock.last_failure)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"reconcile cursor {name} is invalid") from exc
    return clock


@dataclass(frozen=True)
class FeatureOperationReconcileCursor:
    """Dagster→DB watermark와 DB→Dagster keyset cursor, 두 멈춤 시계의 단일 commit 단위.

    ``head``(Dagster page의 머리)와 ``db_watch``(DB page에서 지켜보는 root 하나)는 선택 키다.
    비어 있으면 쓰지 않으므로 아무 일도 없을 때 cursor 바이트가 앞 판과 같다. ``version``은 1
    그대로이고 parser는 선택 키가 있어도 없어도 받는다(ADR-112 결정 7).
    """

    dagster: DagsterRunWatermark | None = None
    database: DagsterFeatureOperationCursor | None = None
    head: StallClock | None = None
    db_watch: StallClock | None = None

    def to_json(self) -> str:
        value: dict[str, Any] = {
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
        if self.head is not None:
            value["head"] = _clock_to_cursor(self.head)
        if self.db_watch is not None:
            value["db_watch"] = _clock_to_cursor(self.db_watch)
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str | None) -> FeatureOperationReconcileCursor:
        if value is None:
            return cls()
        try:
            raw = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("feature operation reconcile cursor is not valid JSON") from exc
        if (
            not isinstance(raw, dict)
            or not set(raw) >= _CURSOR_REQUIRED_KEYS
            or not set(raw) <= _CURSOR_REQUIRED_KEYS | _CURSOR_OPTIONAL_KEYS
        ):
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
        return cls(
            dagster=dagster_cursor,
            database=database_cursor,
            head=_clock_from_cursor(raw["head"], name="head") if "head" in raw else None,
            db_watch=(
                _clock_from_cursor(raw["db_watch"], name="db_watch") if "db_watch" in raw else None
            ),
        )


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
        # 상태 sensor도 공용 code server의 sensor thread를 나눠 쓴다 — reconcile tick과 같은 서버 쪽
        # 상한을 건다(ADR-112 결정 2). 반영은 다음 이벤트·reconcile이 다시 하므로 짧게 끊어도 된다.
        deadline = _monotonic() + _STATUS_EVENT_BUDGET_SECONDS
        with transaction_deadline(deadline):
            async with asyncio.timeout(
                _STATUS_EVENT_BUDGET_SECONDS + _CLIENT_TIMEOUT_GRACE_SECONDS
            ):
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


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _monotonic() -> float:
    return time.monotonic()


class _OutOfTime(RuntimeError):
    """page 마감까지 새 호출을 시작할 시간이 남지 않았다."""


@dataclass
class _Tick:
    """한 tick의 시간 예산과 실패 로그 상한(ADR-112 결정 2)."""

    context: _ReconcileContext
    started: float
    failures: int = 0

    @property
    def dagster_deadline(self) -> float:
        return self.started + FEATURE_OPERATION_DAGSTER_PAGE_SECONDS

    @property
    def database_deadline(self) -> float:
        return self.started + FEATURE_OPERATION_TICK_BUDGET_SECONDS

    def remaining(self, deadline: float) -> float:
        return deadline - _monotonic()

    def has_time(self, deadline: float) -> bool:
        return self.remaining(deadline) >= FEATURE_OPERATION_MIN_CALL_SECONDS

    def log_failure(self, message: str, *args: object) -> None:
        self.failures += 1
        if self.failures <= _MAX_FAILURE_LOG_LINES:
            self.context.log.error(message, *args)

    def read_storage(self, call: Callable[[], _T], deadline: float) -> _T:
        """run storage 동기 읽기를 worker 하나짜리 slot에서 page 마감까지만 기다린다."""
        remaining = self.remaining(deadline)
        if remaining <= 0:
            raise DeadlineExceeded("page deadline already passed")
        return call_with_deadline(call, timeout_seconds=remaining, slots=_STORAGE_SLOTS)

    async def call(self, deadline: float, factory: Callable[[], Awaitable[_T]]) -> _T:
        """client 호출 하나. 그 안에서 여는 트랜잭션마다 서버 쪽 상한이 page 마감에서 유도된다."""
        remaining = self.remaining(deadline)
        if remaining < FEATURE_OPERATION_MIN_CALL_SECONDS:
            raise _OutOfTime("page deadline leaves no time for a new call")
        with transaction_deadline(deadline):
            async with asyncio.timeout(remaining + _CLIENT_TIMEOUT_GRACE_SECONDS):
                return await factory()


@dataclass
class _RootSeen:
    """이번 반영에서 그 run의 root가 있음을 확인했는가(결정 1 (b))."""

    root: bool = False


def _failure(
    *,
    category: str,
    closable: bool,
    error_type: str,
    sqlstate: str | None = None,
    constraint: str | None = None,
) -> dict[str, Any]:
    """cursor ``last_failure``의 고정 모양. 값은 모두 짧은 식별자라 크기에 상한이 있다."""
    return {
        "category": category,
        "closable": closable,
        "constraint": constraint,
        "error_type": error_type,
        "sqlstate": sqlstate,
    }


_FAILURE_FIELDS: Final[tuple[str, ...]] = (
    "category",
    "closable",
    "sqlstate",
    "constraint",
    "error_type",
)


def _encode_failure(failure: Mapping[str, Any]) -> str:
    """시계의 실패 서명 — ``category|closable|sqlstate|constraint|error_type``(200자 이하).

    값은 모두 식별자다(SQLSTATE·constraint 이름·예외 class 이름). 오류 원문은 싣지 않는다.
    """
    parts = [
        str(failure["category"]),
        "1" if failure["closable"] else "0",
        failure["sqlstate"] or "-",
        (failure["constraint"] or "-")[:63],
        str(failure["error_type"])[:60],
    ]
    return "|".join(part.replace("|", "/") for part in parts)


def _decode_failure(signature: str) -> dict[str, Any]:
    parts = signature.split("|")
    if len(parts) != len(_FAILURE_FIELDS) or parts[1] not in {"0", "1"}:
        raise ValueError("stall clock failure signature is invalid")
    category, closable, sqlstate, constraint, error_type = parts
    return _failure(
        category=category,
        closable=closable == "1",
        error_type=error_type,
        sqlstate=None if sqlstate == "-" else sqlstate,
        constraint=None if constraint == "-" else constraint,
    )


def _failure_of(clock: StallClock) -> dict[str, Any]:
    return _decode_failure(clock.last_failure)


def _observe(
    clock: StallClock | None, *, key: str, failure: Mapping[str, Any], now: datetime
) -> StallClock:
    return observe_failure(clock, key=key, failure=_encode_failure(failure), now=now.timestamp())


def _clock_time(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


def _classify_failure(error: BaseException, *, at_head: bool) -> dict[str, Any]:
    """실패를 닫을 수 있는 것(CLOSABLE)과 재시도·알림만 할 것으로 가른다(ADR-112 결정 4·5).

    sqlstate·constraint·message는 asyncpg 오류(``exc.orig.__cause__``)에서 읽는다.
    """
    error_type = type(error).__name__
    if isinstance(error, FeatureOperationObservationError):
        # operation key가 있는데 root를 만들 수 없는 관측 오류는 머리에서만 닫는다.
        return _failure(category="observation", closable=at_head, error_type=error_type)
    if isinstance(error, FeatureOperationInvariantConflict):
        return _failure(category="invariant_conflict", closable=True, error_type=error_type)
    if isinstance(error, (_OutOfTime, DeadlineExceeded, TimeoutError)):
        return _failure(category="timeout", closable=False, error_type=error_type)
    info = pg_error_info(error)
    if info is None:
        return _failure(category="exception", closable=False, error_type=error_type)
    sqlstate = info.sqlstate
    if sqlstate == "55P03":
        gate_busy = (info.message or "").startswith(_GATE_BUSY_MARKER)
        return _failure(
            category="gate_busy" if gate_busy else "lock_wait",
            closable=False,
            error_type=error_type,
            sqlstate=sqlstate,
        )
    closable = (
        sqlstate.startswith("22")
        or sqlstate == "23502"
        or (sqlstate == "23514" and info.constraint in _CLOSABLE_CHECK_CONSTRAINTS)
    )
    return _failure(
        category="closable_sqlstate" if closable else "sqlstate",
        closable=closable,
        error_type=error_type,
        sqlstate=sqlstate,
        constraint=info.constraint,
    )


def _storage_failure(error: BaseException) -> dict[str, Any]:
    return _failure(category="storage", closable=False, error_type=type(error).__name__)


def _stalled(clock: StallClock, now: datetime) -> bool:
    return now.timestamp() - clock.first_failed_at >= FEATURE_OPERATION_STALL_AFTER_SECONDS


async def _reconcile_tick(
    context: _ReconcileContext,
    client: AsyncKorTravelMapClient,
) -> SkipReason | list[RunRequest]:
    tick = _Tick(context=context, started=_monotonic())
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
        existing = tick.read_storage(
            lambda: _map_run_count(context.instance), tick.dagster_deadline
        )
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
    dagster = await _reconcile_dagster_page(tick, client, cursor.dagster, cursor.head)
    database = await _reconcile_database_page(tick, client, cursor.database, cursor.db_watch)
    backstop = (
        _completion_backstop_request(tick) if database.completion_pending else None
    )

    # 모든 분기에서 return 전에 commit한다(결정 2). DB page 목록 조회가 실패해도 Dagster 쪽 진척은
    # commit하고 DB cursor는 그대로 둔다.
    next_cursor = FeatureOperationReconcileCursor(
        dagster=dagster.watermark,
        database=database.cursor,
        head=dagster.head,
        db_watch=database.watch,
    )
    context.update_cursor(next_cursor.to_json())
    summary = (
        "provider feature operation reconcile 완료: "
        f"dagster_applied={dagster.applied} "
        f"dagster_panel_only={dagster.panel_only} "
        f"dagster_held={dagster.head.key if dagster.head is not None else '-'} "
        f"database_applied={database.applied} "
        f"database_failed={database.failed} "
        f"completion_pending={len(database.completion_pending)} "
        f"failures={tick.failures}"
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


@dataclass
class _DagsterPageResult:
    watermark: DagsterRunWatermark | None
    head: StallClock | None
    applied: int = 0
    panel_only: int = 0


async def _reconcile_dagster_page(
    tick: _Tick,
    client: AsyncKorTravelMapClient,
    watermark: DagsterRunWatermark | None,
    head: StallClock | None,
) -> _DagsterPageResult:
    """Dagster page — run R은 (a)(b)(c) 중 하나일 때만 지나간다(ADR-112 결정 1).

    (a) operation key가 없다, (b) 이번 tick에 R의 root가 있음을 확인했다, (c) 결정 4의 닫기가
    R에 대한 내구성 있는 기록을 commit했다. 셋 다 아니면 R에서 멈추고 R이 머리가 된다.

    읽기와 반영은 page 마감보다 ``_ACTION_RESERVE_SECONDS`` 일찍 끝나는 항목 마감 안에서 한다.
    남긴 몫으로 머리의 닫기·알림을 한다 — 실패한 호출이 lock_timeout까지 기다려도 알림이 굶지 않는다.
    """
    deadline = tick.dagster_deadline
    item_deadline = deadline - _ACTION_RESERVE_SECONDS
    result = _DagsterPageResult(watermark=watermark, head=head)
    if not tick.has_time(item_deadline):
        return result
    instance = tick.context.instance
    storage_key = watermark.run_id if watermark is not None else _STORAGE_START_KEY
    try:
        records = tick.read_storage(
            lambda: _dagster_run_page(
                instance, watermark=watermark, page_size=FEATURE_OPERATION_RECONCILE_PAGE_SIZE
            ),
            item_deadline,
        )
    except Exception as exc:
        # anchor 삭제·순서 어긋남·시간 초과·worker 점유 — 머리는 watermark 다음 자리다. 닫지 않는다.
        # 그 자리에 이미 run의 머리 시계가 있으면 그 시계를 잇는다(storage가 오락가락해도 시계가
        # 처음으로 돌아가지 않는다). 없으면 watermark run을 key로 새 시계를 연다.
        tick.log_failure(
            "Dagster run storage 읽기 실패(머리 시계): error_type=%s", type(exc).__name__
        )
        storage_head = _observe(
            head,
            key=head.key if head is not None else storage_key,
            failure=_storage_failure(exc),
            now=_utcnow(),
        )
        result.head = await _alert_if_due(
            tick, client, storage_head, scope="head", dagster_status=None, deadline=deadline
        )
        return result
    current = result.head
    if current is not None and (
        current.key in {storage_key, _STORAGE_START_KEY}
        or not records
        or records[0].dagster_run.run_id != current.key
    ):
        # storage만 실패하던 시계이거나, 머리였던 run이 page 맨 앞에 없으면(지워졌다) 그 시계는 끝났다.
        current = None
    for record in records:
        if not tick.has_time(item_deadline):
            break
        run = record.dagster_run
        seen = _RootSeen()
        error: Exception | None = None
        outcome = "panel_only"
        try:
            outcome = await tick.call(
                item_deadline,
                partial(_apply_run_record, record, client, seen=seen),
            )
        except _OutOfTime:
            break
        except Exception as exc:
            error = exc
        if error is not None and seen.root:
            # (b) root가 있다. 뒤따른 호출의 실패는 DB page(active)나 취소 coordinator가 맡는다.
            tick.log_failure(
                "operation run 반영 일부 실패(root 있음, 지나감): run_id=%s error_type=%s",
                run.run_id,
                type(error).__name__,
            )
            error = None
            outcome = "root_present"
        if error is None:
            if current is not None and current.key == run.run_id:
                current = None
            result.watermark = DagsterRunWatermark(record.storage_id, run.run_id)
            if outcome == "panel_only":
                result.panel_only += 1
            else:
                result.applied += 1
            continue
        failure = _classify_failure(error, at_head=True)
        now = _utcnow()
        current = _observe(current, key=run.run_id, failure=failure, now=now)
        tick.log_failure(
            "operation run 반영 실패(머리): run_id=%s category=%s error_type=%s",
            run.run_id,
            failure["category"],
            failure["error_type"],
        )
        if failure["closable"] and _stalled(current, now):
            # 닫기는 root가 없으면 기록 한 행(c)을, 있으면 그 root(b)를 남긴다. Dagster run이 아직
            # 돌고 있어 닫지 않은 경우도 root는 있다(b) — 어느 쪽이든 지나간다(결정 4 표).
            if await _abandon(tick, client, current, record=record, deadline=deadline):
                current = None
                result.watermark = DagsterRunWatermark(record.storage_id, run.run_id)
                result.applied += 1
                continue
        current = await _alert_if_due(
            tick, client, current, scope="head", dagster_status=run.status.value, deadline=deadline
        )
        break
    result.head = current
    return result


@dataclass
class _DatabasePageResult:
    cursor: DagsterFeatureOperationCursor | None
    watch: StallClock | None
    applied: int = 0
    failed: int = 0
    completion_pending: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ItemFailure:
    run_id: str
    failure: dict[str, Any]
    record: _RunRecord | None
    failed_at: datetime


async def _reconcile_database_page(
    tick: _Tick,
    client: AsyncKorTravelMapClient,
    database_cursor: DagsterFeatureOperationCursor | None,
    watch: StallClock | None,
) -> _DatabasePageResult:
    """DB page — active root를 반영하고, 실패하는 root 하나를 ``db_watch``로 지켜본다.

    DB page는 취소 marker·quarantine이 없는 active root만 훑는다. 그런 root의 Dagster run이
    SUCCESS면 완결이 아직 없다는 뜻이다 — completion sweep이 맡는다(ADR-112 결정 0-1). root가
    이미 있으므로 ensure도 하지 않는다(identity conflict 행을 sweep마다 다시 쓰지 않는다).
    항목 하나가 실패하면 그 항목만 건너뛴다 — 다음 sweep이 다시 집는다. 항목은 page 마감보다
    ``_ACTION_RESERVE_SECONDS`` 일찍 끊고, 남긴 몫으로 ``db_watch``의 닫기·알림을 한다.
    """
    deadline = tick.database_deadline
    item_deadline = deadline - _ACTION_RESERVE_SECONDS
    result = _DatabasePageResult(cursor=database_cursor, watch=watch)
    if watch is not None and tick.has_time(item_deadline):
        try:
            alive = await tick.call(
                item_deadline,
                lambda: client.is_reconcilable_dagster_feature_run(dagster_run_id=watch.key),
            )
        except Exception as exc:
            tick.log_failure("db_watch root 확인 실패: error_type=%s", type(exc).__name__)
        else:
            if not alive:
                result.watch = None
    if not tick.has_time(item_deadline):
        return result
    try:
        page = await tick.call(
            item_deadline,
            lambda: client.list_reconcilable_dagster_feature_runs(
                cursor=database_cursor, page_size=FEATURE_OPERATION_RECONCILE_PAGE_SIZE
            ),
        )
    except Exception as exc:
        tick.log_failure(
            "active feature operation 목록 조회 실패(DB cursor 유지): error_type=%s",
            type(exc).__name__,
        )
        return result
    next_cursor = page.next_cursor
    visited: DagsterFeatureOperation | None = None
    failures: list[_ItemFailure] = []
    for operation in page.items:
        if not tick.has_time(item_deadline):
            # 일찍 멈추면 마지막으로 방문한 항목에 둔다 — 다음 tick이 그 뒤부터 잇는다.
            next_cursor = _database_cursor_of(visited) if visited is not None else database_cursor
            break
        run_id = operation.dagster_run_id
        error: BaseException | None = None
        failure: dict[str, Any] | None = None
        record: _RunRecord | None = None
        try:
            record = tick.read_storage(
                partial(tick.context.instance.get_run_record_by_id, run_id),
                item_deadline,
            )
        except DeadlineExceeded:
            # worker가 아직 앞 읽기를 들고 있거나 마감에 닿았다 — 이 항목부터 다음 tick에.
            next_cursor = _database_cursor_of(visited) if visited is not None else database_cursor
            tick.log_failure("active feature operation의 Dagster 관측 시간 초과: run_id=%s", run_id)
            break
        except Exception as exc:
            error = exc
            failure = _storage_failure(exc)
        if failure is None and record is None:
            failure = _failure(category="run_missing", closable=True, error_type="RunMissing")
        if failure is None and record is not None:
            if record.dagster_run.status == DagsterRunStatus.SUCCESS:
                visited = operation
                result.completion_pending.append(record.dagster_run.run_id)
                if result.watch is not None and result.watch.key == run_id:
                    result.watch = None
                continue
            try:
                await tick.call(item_deadline, partial(_apply_run_record, record, client))
            except _OutOfTime:
                # 이 항목은 반영하지 않았다 — cursor는 그 앞 항목에 둔다.
                next_cursor = (
                    _database_cursor_of(visited) if visited is not None else database_cursor
                )
                break
            except Exception as exc:
                error = exc
                failure = _classify_failure(exc, at_head=False)
        visited = operation
        if failure is None:
            result.applied += 1
            if result.watch is not None and result.watch.key == run_id:
                result.watch = None
            continue
        result.failed += 1
        failed_at = _utcnow()
        tick.log_failure(
            "active feature operation 반영 실패: run_id=%s category=%s error_type=%s",
            run_id,
            failure["category"],
            type(error).__name__ if error is not None else failure["error_type"],
        )
        failures.append(
            _ItemFailure(run_id=run_id, failure=failure, record=record, failed_at=failed_at)
        )
        if result.watch is None or result.watch.key == run_id:
            result.watch = _observe(result.watch, key=run_id, failure=failure, now=failed_at)
    result.cursor = next_cursor
    watched = next(
        (item for item in failures if result.watch is not None and item.run_id == result.watch.key),
        None,
    )
    if result.watch is not None and watched is not None:
        result.watch = await _settle_watch(tick, client, result.watch, watched, failures, deadline)
    return result


async def _settle_watch(
    tick: _Tick,
    client: AsyncKorTravelMapClient,
    watch: StallClock,
    watched: _ItemFailure,
    failures: Sequence[_ItemFailure],
    deadline: float,
) -> StallClock | None:
    """``db_watch`` 시계가 멈춤이면 닫거나(정한 실패) 알린 뒤 슬롯을 넘긴다(결정 3·4).

    넘길 때는 이번 tick에 실패한 root 가운데 지켜보던 root **다음** 것(없으면 처음으로 돌아가
    지켜보던 root가 아닌 첫 것)에게 준다. 그래야 고칠 수 없는 root 하나가 다음 tick에 첫 실패로
    슬롯을 도로 잡지 않는다(2차 리뷰 H2). 다른 실패가 없으면 비운다.
    """
    now = _utcnow()
    if not _stalled(watch, now):
        return watch
    if _failure_of(watch)["closable"] and await _abandon(
        tick, client, watch, record=watched.record, deadline=deadline, pass_on_active=False
    ):
        return None
    alerted = await _alert_if_due(
        tick,
        client,
        watch,
        scope="db_watch",
        dagster_status=(
            watched.record.dagster_run.status.value if watched.record is not None else None
        ),
        deadline=deadline,
    )
    if alerted.alerted_at is None:
        return alerted
    position = next(
        index for index, item in enumerate(failures) if item.run_id == watched.run_id
    )
    successor = next(
        (
            item
            for item in (*failures[position + 1 :], *failures[:position])
            if item.run_id != watched.run_id
        ),
        None,
    )
    if successor is None:
        return None
    return _observe(None, key=successor.run_id, failure=successor.failure, now=successor.failed_at)


async def _abandon(
    tick: _Tick,
    client: AsyncKorTravelMapClient,
    clock: StallClock,
    *,
    record: _RunRecord | None,
    deadline: float,
    pass_on_active: bool = True,
) -> bool:
    """정한 실패가 15분 넘게 이어진 run을 닫는다. 그 run을 놓아 줘도 되면 ``True``.

    ``run_active``(Dagster run이 아직 돈다)는 root가 있다는 뜻이다 — 머리는 (b)로 지나가지만
    (``pass_on_active``), ``db_watch``는 그 root를 계속 지켜보다 알리고 넘긴다.
    """
    status = record.dagster_run.status.value if record is not None else None
    try:
        finished_at = (
            _timestamp_datetime(record.end_time, name="Dagster finish timestamp")
            if record is not None
            else None
        )
    except FeatureOperationObservationError:
        finished_at = None
    try:
        outcome = await tick.call(
            deadline,
            lambda: client.abandon_dagster_feature_run(
                dagster_run_id=clock.key,
                dagster_status=status,
                engine_finished_at=finished_at,
                failure=_failure_of(clock),
                first_failed_at=_clock_time(clock.first_failed_at),
            ),
        )
    except Exception as exc:
        tick.log_failure(
            "operation run 닫기 실패: run_id=%s error_type=%s", clock.key, type(exc).__name__
        )
        return False
    tick.context.log.error(
        "operation run을 reconcile에서 놓아 줌: run_id=%s outcome=%s", clock.key, outcome.outcome
    )
    return pass_on_active or outcome.outcome != "run_active"


async def _alert_if_due(
    tick: _Tick,
    client: AsyncKorTravelMapClient,
    clock: StallClock,
    *,
    scope: str,
    dagster_status: str | None,
    deadline: float,
) -> StallClock:
    """멈춘 시계를 tick마다 요약 로그로, 한 시간에 한 번은 ``ops.system_log`` 한 행으로 알린다.

    system log 쓰기가 실패해도 결정 1의 진행은 막지 않는다 — ``alerted_at``을 비워 둔 채 다음
    tick이 다시 시도한다.
    """
    now = _utcnow()
    if not _stalled(clock, now):
        return clock
    tick.context.log.error(
        "provider feature operation reconcile 멈춤: scope=%s run_id=%s since=%s category=%s",
        scope,
        clock.key,
        _clock_time(clock.first_failed_at).isoformat(),
        _failure_of(clock)["category"],
    )
    if not due_alert(
        clock,
        now=now.timestamp(),
        stall_after=FEATURE_OPERATION_STALL_AFTER_SECONDS,
        realert_after=FEATURE_OPERATION_REALERT_SECONDS,
    ):
        return clock
    try:
        await tick.call(
            deadline,
            lambda: client.record_feature_operation_reconcile_stalled(
                scope=scope,
                dagster_run_id=clock.key,
                dagster_status=dagster_status,
                first_failed_at=_clock_time(clock.first_failed_at),
                last_failure=_failure_of(clock),
                alerted_at=_clock_time(clock.alerted_at) if clock.alerted_at is not None else None,
                action=_stall_action(scope, clock),
            ),
        )
    except Exception as exc:
        tick.context.log.error(
            "reconcile 멈춤 알림 기록 실패(다음 tick에 다시): error_type=%s", type(exc).__name__
        )
        return clock
    return mark_alerted(clock, now.timestamp())


def _stall_action(scope: str, clock: StallClock) -> str:
    category = _failure_of(clock)["category"]
    if category == "storage":
        return (
            "Dagster run storage cannot be read; the Dagster page is paused - check the code "
            "server and run storage"
        )
    manual = f"ktmctl reconcile-abandon {clock.key} --dagster-status <STATUS|missing>"
    if scope == "head":
        return (
            "the Dagster page is held at this run (missed-event recovery is paused); fix the "
            f"cause or close it manually with `{manual}`"
        )
    return f"this root keeps failing reconcile; fix the cause or close it manually with `{manual}`"


def _database_cursor_of(operation: DagsterFeatureOperation) -> DagsterFeatureOperationCursor:
    return DagsterFeatureOperationCursor(
        created_at=operation.created_at, root_job_id=operation.root_job_id
    )


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


def _completion_backstop_request(tick: _Tick) -> RunRequest | None:
    """완결 대기 root가 보일 때의 뒷받침 요청.

    가장 최근 completion sweep이 진행 중이거나 끝난 지
    ``FEATURE_OPERATION_COMPLETION_BACKSTOP_SECONDS``가 안 됐으면 내지 않는다. run_key에 그
    sweep의 run id를 넣어, 한 sweep 뒤에는 많아야 한 번만 낸다. run storage 읽기가 실패하면 이번
    tick은 내지 않는다 — root는 active로 남고 다음 tick이 다시 본다. 읽기는 DB page 마감 안에서만
    한다(결정 2).
    """
    context = tick.context
    if not tick.has_time(tick.database_deadline):
        return None
    try:
        latest = tick.read_storage(
            lambda: next(
                iter(
                    context.instance.get_run_records(
                        filters=map_runs_filter(job_name=FEATURE_OPERATION_COMPLETION_JOB_NAME),
                        limit=1,
                    )
                ),
                None,
            ),
            tick.database_deadline,
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
    seen: _RootSeen | None = None,
) -> str:
    """run record 하나를 DB에 반영하고 outcome을 돌려준다.

    ``seen``을 넘기면 반영 도중 그 run의 root가 있음을 확인한 순간 ``seen.root``를 켠다 — 뒤따른
    호출이 실패해도 Dagster page가 그 run을 지나가도 되는지(ADR-112 결정 1 (b))를 가른다.
    """
    seen = seen if seen is not None else _RootSeen()
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
        try:
            mutation = await client.ensure_dagster_feature_operation(
                dagster_run_id=run.run_id,
                trigger_kind=trigger_kind,
                selected_memberships=memberships,
                operation_key=operation_key,
                engine_created_at=created_at,
                engine_started_at=started_at,
                observed_status=status.value,
            )
        except FeatureOperationInvariantConflict as exc:
            # root를 가리키는 conflict는 그 root를 잠근 채 읽은 결과다 — root는 있다.
            if exc.root_job_id is not None:
                seen.root = True
            raise
        seen.root = True
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
            seen=seen,
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
        seen=seen,
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
    seen: _RootSeen,
) -> DagsterFeatureOperationMutation:
    """terminal run의 root를 ensure한다. identity conflict는 올린다.

    conflict가 root를 가리키면(``root_job_id``) 그 root는 있다 — ``seen``에 남기고 올린다.
    """
    try:
        mutation = await client.ensure_dagster_feature_operation(
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
    except FeatureOperationInvariantConflict as exc:
        if exc.root_job_id is not None:
            seen.root = True
        raise
    seen.root = True
    return mutation


async def _ensure_success_root(
    record: _RunRecord,
    client: AsyncKorTravelMapClient,
    *,
    operation_key: str,
    memberships: Sequence[ProviderDatasetOperationMembership],
    trigger_kind: TriggerKind,
    created_at: datetime,
    started_at: datetime | None,
    seen: _RootSeen,
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
            seen=seen,
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
    seen: _RootSeen,
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
            seen=seen,
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
    seen.root = True
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
    "FEATURE_OPERATION_DAGSTER_PAGE_SECONDS",
    "FEATURE_OPERATION_MIN_CALL_SECONDS",
    "FEATURE_OPERATION_REALERT_SECONDS",
    "FEATURE_OPERATION_RECONCILE_CURSOR_VERSION",
    "FEATURE_OPERATION_RECONCILE_INTERVAL_SECONDS",
    "FEATURE_OPERATION_RECONCILE_PAGE_SIZE",
    "FEATURE_OPERATION_SETTLE_LAG_SECONDS",
    "FEATURE_OPERATION_STALL_AFTER_SECONDS",
    "FEATURE_OPERATION_TICK_BUDGET_SECONDS",
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
