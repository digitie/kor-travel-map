"""Dagster provider feature operation 상태 추적과 양방향 복구 sensor."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Mapping, Sequence, Set
from dataclasses import dataclass, field
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
"""같은 run이 같은 **데이터·불변식** SQLSTATE로 연속 실패하면 terminal root를 닫는 횟수(ADR-111)."""

FEATURE_OPERATION_RECONCILE_BACKOFF_BASE_SECONDS: Final[int] = 30
FEATURE_OPERATION_RECONCILE_BACKOFF_MAX_SECONDS: Final[int] = 900
"""실패한 run을 다시 돌기 전 기다리는 시간. 30초에서 두 배씩, 15분에서 멈춘다.

무거운 트랜잭션(대형 dataset root 완결)이 실패할 때마다 30초 간격으로 다시 돌면 그 자체가
공유 자원을 계속 흔든다. 그래서 실패한 run은 **모두** 물러선다(미뤄 둔다) — 닫는 것은 아래
허용 목록뿐이다. 예외: root 완결의 gate try-lock이 바쁜 55P03은 잠깐의 경합이라 늘리지 않는다.
"""

FEATURE_OPERATION_RECONCILE_DEFERRED_MAX: Final[int] = FEATURE_OPERATION_RECONCILE_PAGE_SIZE
"""cursor에 들고 다니는 미뤄 둔 run의 최대 수. 넘치면 가장 늦게 다시 돌 것부터 버린다 — 버려진
run도 operation이 끝나지 않았으면 DB 쪽 page가 다시 집는다."""

_FLAT_BACKOFF_SIGNATURES: Final[frozenset[str]] = frozenset({"SQLSTATE 55P03"})

#: root를 닫아도 되는 SQLSTATE class — 데이터 예외(22)·무결성 위반(23)·plpgsql RAISE(P0).
#: 다시 돌려도 같은 답이 나오는 결정적 실패다. 그 밖(53 자원 고갈처럼 cluster의 다른 tenant가
#: 일으킬 수 있는 것, 배포 중 42xxx, 40001, 57014, 55P03, 58xxx, XX000, SQLSTATE 없음)은
#: 물러서서 다시 돌 뿐 닫지 않는다.
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
class DeferredRun:
    """반영이 실패해 미뤄 둔 run 하나 — 실패 서명, 연속 횟수, 다시 돌 시각, 닫기가 막혔는지."""

    signature: str
    count: int
    retry_after: datetime
    blocked: bool = False

    def __post_init__(self) -> None:
        _non_empty_string(self.signature, name="deferred signature")
        _positive_int(self.count, name="deferred count")
        _aware_datetime(self.retry_after, name="deferred retry_after")


@dataclass(frozen=True)
class FeatureOperationReconcileCursor:
    """Dagster→DB watermark와 DB→Dagster keyset cursor의 단일 commit 단위.

    ``deferred``는 반영이 실패한 run을 run_id별로 미뤄 둔 표다(ADR-111). 실패한 run은 tick을
    멈추지 않는다 — watermark는 그 run을 지나가고, 같은 tick의 나머지 run과 DB 쪽 page도 돈다.
    미뤄 둔 run은 ``retry_after``가 지나면 run_id로 다시 집는다. 표가 비면 JSON에 키를 쓰지
    않는다 — 그 앞 판의 cursor와 바이트가 같다. 앞 판 코드는 이 키가 있는 cursor를 거부한다
    (되돌릴 때 절차는 ADR-111).
    """

    dagster: DagsterRunWatermark | None = None
    database: DagsterFeatureOperationCursor | None = None
    deferred: Mapping[str, DeferredRun] = field(default_factory=dict)

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
        if self.deferred:
            value["deferred"] = {
                run_id: {
                    "blocked": entry.blocked,
                    "count": entry.count,
                    "retry_after": entry.retry_after.isoformat(),
                    "signature": entry.signature,
                }
                for run_id, entry in self.deferred.items()
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
        if not isinstance(raw, dict) or set(raw) - {"deferred"} != {
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
        deferred: dict[str, DeferredRun] = {}
        deferred_raw = raw.get("deferred")
        if deferred_raw is not None:
            if not isinstance(deferred_raw, dict) or not deferred_raw:
                raise ValueError("reconcile deferred table shape is invalid")
            for run_id, entry in deferred_raw.items():
                if not isinstance(entry, dict) or set(entry) != {
                    "blocked",
                    "count",
                    "retry_after",
                    "signature",
                } or not isinstance(entry["blocked"], bool):
                    raise ValueError("reconcile deferred entry shape is invalid")
                deferred[_non_empty_string(run_id, name="deferred run_id")] = DeferredRun(
                    signature=_non_empty_string(entry["signature"], name="deferred signature"),
                    count=_positive_int(entry["count"], name="deferred count"),
                    retry_after=_parse_datetime(entry["retry_after"]),
                    blocked=entry["blocked"],
                )
        return cls(dagster=dagster_cursor, database=database_cursor, deferred=deferred)


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
    ledger = _DeferredLedger(context, client, dict(cursor.deferred), _utcnow())
    dagster_records = _dagster_run_page(
        context.instance,
        watermark=cursor.dagster,
        page_size=FEATURE_OPERATION_RECONCILE_PAGE_SIZE,
    )
    dagster_applied = 0
    dagster_panel_only = 0
    for record in dagster_records:
        try:
            outcome = await ledger.apply(record)
        except FeatureOperationObservationError as exc:
            context.log.error("provider feature operation panel-only conflict: %s", exc)
            dagster_panel_only += 1
            continue
        if outcome not in {None, "panel_only"}:
            dagster_applied += 1

    # 실패한 run은 미뤄 뒀으므로 watermark는 page 끝까지 간다 — 한 run이 나머지를 막지 않는다.
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
        ledger,
        database_page,
    )
    await ledger.retry_due()

    next_cursor = FeatureOperationReconcileCursor(
        dagster=next_dagster_cursor,
        database=database_page.next_cursor,
        deferred=ledger.bounded(),
    )
    context.update_cursor(next_cursor.to_json())
    return SkipReason(
        "provider feature operation reconcile 완료: "
        f"dagster_applied={dagster_applied} "
        f"dagster_panel_only={dagster_panel_only} "
        f"database_applied={database_applied} "
        f"database_observation_errors={database_observation_errors} "
        f"failed={ledger.failed} parked={ledger.parked} deferred={len(next_cursor.deferred)}"
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
    ledger: _DeferredLedger,
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
            outcome = await ledger.apply(record)
        except FeatureOperationObservationError as exc:
            context.log.error(
                "active feature operation의 Dagster identity 관측 실패: run_id=%s error=%s",
                operation.dagster_run_id,
                exc,
            )
            observation_errors += 1
            continue
        if outcome not in {None, "panel_only"}:
            applied += 1
    return applied, observation_errors


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
    if signature in _FLAT_BACKOFF_SIGNATURES:
        return FEATURE_OPERATION_RECONCILE_BACKOFF_BASE_SECONDS
    return min(
        FEATURE_OPERATION_RECONCILE_BACKOFF_BASE_SECONDS << min(count - 1, 16),
        FEATURE_OPERATION_RECONCILE_BACKOFF_MAX_SECONDS,
    )


class _DeferredLedger:
    """한 tick 동안 run별 실패를 세고 미뤄 두는 표(ADR-111).

    실패한 run은 tick을 멈추지 않는다 — 기록하고 다음 run으로 간다. 같은 run이 같은 서명으로
    상한에 닿으면 한 번 ``reconcile_stalled``를 남기고, 서명이 데이터·불변식(22/23/P0)이며 run이
    terminal이면 root를 닫는다. 닫기가 ``applied``일 때만 표에서 지운다.
    """

    def __init__(
        self,
        context: _ReconcileContext,
        client: AsyncKorTravelMapClient,
        deferred: dict[str, DeferredRun],
        now: datetime,
    ) -> None:
        self._context = context
        self._client = client
        self._deferred = deferred
        self._now = now
        self._attempted: set[str] = set()
        self.failed = 0
        self.parked = 0

    async def apply(self, record: _RunRecord) -> str | None:
        """반영하고 outcome을 돌려준다. 미뤄 둔 시각 전이거나 실패하면 ``None``."""
        run_id = record.dagster_run.run_id
        if run_id in self._attempted:
            return None
        entry = self._deferred.get(run_id)
        if entry is not None and self._now < entry.retry_after:
            self.parked += 1
            return None
        self._attempted.add(run_id)
        try:
            outcome = await _apply_run_record(record, self._client)
        except FeatureOperationObservationError:
            raise
        except Exception as exc:
            self.failed += 1
            await self._defer(record, exc)
            return None
        self._deferred.pop(run_id, None)
        return outcome

    async def retry_due(self) -> None:
        """다시 돌 시각이 지난 run을 run_id로 집어 다시 한다(Dagster·DB page 어디에도 없을 때)."""
        for run_id, entry in sorted(self._deferred.items(), key=lambda item: item[1].retry_after):
            if run_id in self._attempted or self._now < entry.retry_after:
                continue
            try:
                record = self._context.instance.get_run_record_by_id(run_id)
            except Exception as exc:
                self._context.log.error(
                    "미뤄 둔 feature operation의 Dagster 관측 실패: run_id=%s error_type=%s",
                    run_id,
                    type(exc).__name__,
                )
                continue
            if record is None:
                self._context.log.error(
                    "미뤄 둔 feature operation의 Dagster run이 없어 표에서 지운다: run_id=%s",
                    run_id,
                )
                self._deferred.pop(run_id, None)
                continue
            try:
                await self.apply(record)
            except FeatureOperationObservationError as exc:
                self._context.log.error(
                    "미뤄 둔 feature operation의 identity 관측 실패: run_id=%s error=%s",
                    run_id,
                    exc,
                )

    def bounded(self) -> dict[str, DeferredRun]:
        kept = sorted(self._deferred.items(), key=lambda item: item[1].retry_after)
        if len(kept) > FEATURE_OPERATION_RECONCILE_DEFERRED_MAX:
            dropped = [run_id for run_id, _ in kept[FEATURE_OPERATION_RECONCILE_DEFERRED_MAX:]]
            self._context.log.error(
                "미뤄 둔 feature operation이 상한을 넘어 %d건을 표에서 버린다"
                "(DB page가 다시 집는다): %s",
                len(dropped),
                ",".join(dropped),
            )
        return dict(kept[:FEATURE_OPERATION_RECONCILE_DEFERRED_MAX])

    async def _defer(self, record: _RunRecord, error: Exception) -> None:
        run = record.dagster_run
        signature, closable = _failure_signature(error)
        previous = self._deferred.get(run.run_id)
        same = previous is not None and previous.signature == signature
        count = previous.count + 1 if previous is not None and same else 1
        blocked = previous.blocked if previous is not None and same else False
        retry_after = self._now + timedelta(seconds=_backoff_seconds(count, signature))
        self._context.log.error(
            "provider feature operation reconcile 실패 — 미뤄 둔다: "
            f"error_type={type(error).__name__} run_id={run.run_id} {signature} "
            f"consecutive={count}/{FEATURE_OPERATION_RECONCILE_FAILURE_LIMIT} "
            f"retry_after={retry_after.isoformat()}"
        )
        finished_at = _timestamp_datetime(record.end_time, name="Dagster finish timestamp")
        if (
            closable
            and not blocked
            and count >= FEATURE_OPERATION_RECONCILE_FAILURE_LIMIT
            and run.status in _TERMINAL_STATUSES
            and finished_at is not None
        ):
            try:
                mutation = await self._client.abandon_dagster_feature_run(
                    dagster_run_id=run.run_id,
                    terminal_status=run.status.value,
                    engine_finished_at=finished_at,
                    failure=signature,
                    attempts=count,
                )
            except Exception as exc:
                self._context.log.error(
                    "provider feature operation root 닫기 실패: run_id=%s error_type=%s",
                    run.run_id,
                    type(exc).__name__,
                )
            else:
                if mutation.outcome == "applied":
                    self._context.log.error(
                        "provider feature operation root를 failed로 닫았다: run_id=%s %s",
                        run.run_id,
                        signature,
                    )
                    self._deferred.pop(run.run_id, None)
                    return
                # 이미 terminal이거나 취소 중이다. 닫을 것이 없는데 반영은 여전히 실패한다 —
                # 닫기를 다시 시도하지 않고 멈춘 run으로 남긴다.
                blocked = True
                self._context.log.error(
                    "provider feature operation root를 닫지 못했다(outcome=%s, block_reason=%s): "
                    "run_id=%s — 멈춘 run으로 남긴다",
                    mutation.outcome,
                    getattr(mutation, "block_reason", None),
                    run.run_id,
                )
        self._deferred[run.run_id] = DeferredRun(
            signature=signature, count=count, retry_after=retry_after, blocked=blocked
        )
        if count == FEATURE_OPERATION_RECONCILE_FAILURE_LIMIT:
            await self._report_stalled(run, signature, count, closable=closable and not blocked)

    async def _report_stalled(
        self, run: _DagsterRun, signature: str, count: int, *, closable: bool
    ) -> None:
        """같은 서명이 상한에 처음 닿을 때 한 번 운영 로그로 올린다."""
        try:
            await self._client.record_feature_operation_reconcile_stalled(
                dagster_run_id=run.run_id,
                failure=signature,
                attempts=count,
                closable=closable,
            )
        except Exception as exc:
            self._context.log.error(
                "reconcile_stalled 기록 실패: run_id=%s error_type=%s",
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
    "FEATURE_OPERATION_RECONCILE_DEFERRED_MAX",
    "FEATURE_OPERATION_RECONCILE_FAILURE_LIMIT",
    "FEATURE_OPERATION_RECONCILE_INTERVAL_SECONDS",
    "FEATURE_OPERATION_RECONCILE_PAGE_SIZE",
    "FEATURE_OPERATION_SETTLE_LAG_SECONDS",
    "FEATURE_OPERATION_TRACKING_SENSORS",
    "DagsterRunWatermark",
    "FeatureOperationObservationError",
    "FeatureOperationReconcileCursor",
    "DeferredRun",
    "feature_operation_canceled_sensor",
    "feature_operation_canceling_sensor",
    "feature_operation_failure_sensor",
    "feature_operation_queued_sensor",
    "feature_operation_reconciliation_sensor",
    "feature_operation_started_sensor",
    "feature_operation_starting_sensor",
    "feature_operation_success_sensor",
]
