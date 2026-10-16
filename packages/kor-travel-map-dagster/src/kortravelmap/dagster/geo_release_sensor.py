"""kor-travel-geo 릴리스 재지오코딩 센서 — 감지 → 계획 → 전용 job RunRequest → 완료.

ADR-109 결정 5. geo가 새 데이터셋(새 ``data_token``)을 서빙하면 geo 유도 값을 가진 dataset을
다시 적재해 스탬프가 낡은 행을 고친다(재해석은 적재 경로의 stale 분기 — 결정 4). 이 센서는 그
재적재를 **기존 전용 job**으로 낸다. 큐(``feature_update_requests``)를 쓰지 않는 이유는 결정 5
머리말이다.

판정은 전부 공용 함수다 — 센서 전용 규칙을 두지 않는다:

- 감지·계획: ``client.create_geo_release_plan`` →
  ``infra.geo_release_repo.plan_geo_release``(운영 API ``POST /v1/ops/geo-releases/detect``와 같은
  함수). 첫 관측 토큰은 기준선(계획 0), 같은 토큰 멱등, 끝난 토큰 재계획 없음.
- 항목 = run 1개(``provider_dataset_ids`` — MCST는 run 1개에 dataset 13개). 상태도 항목 하나로
  본다.
- launch 게이트: ``GeoReleaseItem.launch_blocked_reason``이 있는 항목은 내지 않는다. 1단계 replay는
  전부 launchable이고(T-GR-08), MOIS(``SENSOR_MANUAL_OPERATION_KEYS``)는 막힌다 — 운영자가 수동
  실행하고 항목을 skip한다(#1333 리뷰 R2).
- 완료: ``client.complete_geo_release_plan(…, sigungu_resolver=)`` — resolver는 이 tick의 geo
  client로 만든다(``sigungu_by_radius`` cache target 링크 재동기화).

**상한(단순하게).** tick 300초, **한 번에 run 1개만 진행**(``requested`` 항목이 있으면 새로 내지
않는다). 근거: geo 의존 job은 전부 ``GEO_HEAVY_POOL``(limit 1, run 단위)에 들어 있어 어차피 직렬로
돈다 — 여러 개를 내면 pool에서 줄을 서며 run 슬롯·run_key만 쓴다. 300초는 MOIS 이어 달리기 센서와
같은 주기이고, geo ``dataset/version``의 권장 폴링(60초 이상)보다 넉넉하다. 새 pool·limit 태그는
없다(Manager ``dagster.yaml`` 변경 0). 기본 **STOPPED**(소유자 지시 — odroid geo 스케줄은
mv_refresh 실측 뒤에 켠다).

**PinVi 알림은 범위 밖이다.** 완료 단계가 ``poi_cache_target_feature_links``를 다시 계산하지만
PinVi에 보내는 stream 이벤트는 만들지 않는다(prod 활성 target 0개 — acceptance §T-GR-04
메모 (8)).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Protocol, TypeVar, cast

from kortravelmap.geocoding import (
    KorTravelGeoRestClient,
    fetch_current_dataset,
    open_geo_client,
    resolve_sigungu_by_radius,
)
from kortravelmap.settings import KorTravelMapSettings

from dagster import (
    DagsterRunStatus,
    DefaultSensorStatus,
    RunRequest,
    SensorEvaluationContext,
    SkipReason,
    sensor,
)

from .mois_chunked_load import (
    MOIS_LOAD_JOB_NAME,
    MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED,
    MOIS_LOAD_OUTCOME_TAG,
    mois_load_continuation_decision,
)
from .run_scope import GEO_RELEASE_PLAN_ID_TAG, map_owned_runs_filter, map_runs_filter
from .schedules import FEATURE_LOAD_JOBS

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient
    from kortravelmap.dto.geo_dataset import DatasetRef
    from kortravelmap.infra.geo_release_repo import GeoReleaseItem, GeoReleasePlan
    from kortravelmap.infra.scope_repo import SigunguByRadiusResolver

__all__ = [
    "GEO_RELEASE_MAX_IN_FLIGHT",
    "GEO_RELEASE_PLAN_ID_TAG",
    "GEO_RELEASE_RUN_KEY_TAG",
    "GEO_RELEASE_RUN_LAUNCH_TIMEOUT_SECONDS",
    "GEO_RELEASE_SENSOR_INTERVAL_SECONDS",
    "MOIS_RELEASE_ATTEMPT_CAP",
    "GeoTickSource",
    "RunLookup",
    "evaluate_geo_release_tick",
    "kor_travel_geo_release_sensor",
]

GEO_RELEASE_SENSOR_INTERVAL_SECONDS: Final[int] = 300
"""tick 주기(초) — MOIS 이어 달리기 센서와 같다."""

GEO_RELEASE_MAX_IN_FLIGHT: Final[int] = 1
"""동시에 진행하는 릴리스 run 수. geo 의존 job은 ``GEO_HEAVY_POOL``(limit 1)이라 어차피 직렬이다."""

GEO_RELEASE_RUN_LAUNCH_TIMEOUT_SECONDS: Final[int] = 3 * GEO_RELEASE_SENSOR_INTERVAL_SECONDS
"""``requested``인데 이만큼 지나도 run이 없으면 ``failed(run_not_launched)``(3 tick)."""

MOIS_RELEASE_ATTEMPT_CAP: Final[int] = 12
"""MOIS 이어 달리기 상한(``attempt_seq``) — 넘으면 ``failed(no_progress)``."""

NON_MOIS_RETRY_ATTEMPTS: Final[int] = 2
"""비-MOIS 항목은 실패 시 자동 재요청 1회(``attempt_seq`` 2까지), 그 다음은 운영자."""


GEO_RELEASE_RUN_KEY_TAG: Final[str] = "kor_travel_map.geo_release_run_key"
"""항목 → run 조회 키(``map_owned_runs_filter``는 ``kor_travel_map.*`` tag로만 거른다)."""

_TRIGGER_KIND_TAG: Final[str] = "kor_travel_map.trigger_kind"
_WORKER_JOB_NAME: Final[str] = "feature_update_request_worker"
_ACTIVE_STATUSES: Final[tuple[DagsterRunStatus, ...]] = (
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.MANAGED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
    DagsterRunStatus.CANCELING,
)
_TERMINAL_ITEM_STATES: Final[frozenset[str]] = frozenset({"done", "failed", "skipped"})
_T = TypeVar("_T")


class RunLookup(Protocol):
    """센서가 Dagster run storage에 묻는 것 — 테스트가 가짜로 바꾼다."""

    def active_queue_worker(self) -> str | None: ...

    def active_run_for(self, operation_key: str) -> str | None: ...

    def run_for_key(self, run_key: str) -> Any | None: ...


class GeoTickSource(Protocol):
    """이 tick의 geo — 현재 데이터셋(HTTP 1회)과 sigungu resolver."""

    async def current(self) -> DatasetRef | None: ...

    @property
    def sigungu_resolver(self) -> SigunguByRadiusResolver | None: ...


@dataclass(frozen=True)
class _InstanceRuns:
    instance: Any

    def active_queue_worker(self) -> str | None:
        runs = self.instance.get_runs(
            filters=map_runs_filter(job_name=_WORKER_JOB_NAME, statuses=_ACTIVE_STATUSES),
            limit=1,
        )
        return str(runs[0].run_id) if runs else None

    def active_run_for(self, operation_key: str) -> str | None:
        runs = self.instance.get_runs(
            filters=map_owned_runs_filter(
                job_name=operation_key,
                statuses=_ACTIVE_STATUSES,
                tags={"kor_travel_map.operation_key": operation_key},
            ),
            limit=1,
        )
        return str(runs[0].run_id) if runs else None

    def run_for_key(self, run_key: str) -> Any | None:
        runs = self.instance.get_runs(
            filters=map_owned_runs_filter(tags={GEO_RELEASE_RUN_KEY_TAG: run_key}), limit=1
        )
        return runs[0] if runs else None


class _SettingsGeoSource:
    """settings의 geo client 하나로 현재 데이터셋과 sigungu resolver를 준다(tick 동안만 산다)."""

    def __init__(self, client: KorTravelGeoRestClient | None) -> None:
        self._client = client

    async def current(self) -> DatasetRef | None:
        return await fetch_current_dataset(self._client)

    @property
    def sigungu_resolver(self) -> SigunguByRadiusResolver | None:
        client = self._client
        if client is None:
            return None

        async def resolver(*, lon: float, lat: float, radius_km: float) -> tuple[str, ...]:
            return await resolve_sigungu_by_radius(client, lon=lon, lat=lat, radius_km=radius_km)

        return resolver


@asynccontextmanager
async def _settings_geo_source() -> AsyncIterator[GeoTickSource]:
    async with open_geo_client(KorTravelMapSettings()) as client:
        yield _SettingsGeoSource(client)


def _run_key(plan: GeoReleasePlan, item: GeoReleaseItem) -> str:
    return (
        f"geo_release/{plan.geo_data_token}/{plan.plan_seq}/{item.operation_key}/"
        f"{item.position}/{item.attempt_seq}"
    )


def _blocked_summary(plan: GeoReleasePlan) -> str:
    blocked = [
        f"{item.position}:{item.operation_key}={item.launch_blocked_reason}"
        for item in plan.items
        if item.state == "pending" and item.launch_blocked_reason is not None
    ]
    return ", ".join(blocked) if blocked else "-"


async def _settle_requested(
    client: AsyncKorTravelMapClient,
    plan: GeoReleasePlan,
    runs: RunLookup,
    *,
    now: float,
) -> list[str]:
    """``requested`` 항목을 run 결과로 전이한다(ADR-109 결정 5.5). 돌려주는 것은 사건 기록."""
    events: list[str] = []
    for item in plan.items:
        if item.state != "requested" or item.run_key is None:
            continue
        run = runs.run_for_key(item.run_key)
        if run is None:
            requested_at = item.requested_at
            if (
                requested_at is not None
                and now - _epoch(requested_at) > GEO_RELEASE_RUN_LAUNCH_TIMEOUT_SECONDS
            ):
                await client.settle_geo_release_item(
                    plan.plan_id, item.position, state="failed", reason="run_not_launched"
                )
                events.append(f"{item.position}:run_not_launched")
            continue
        if not run.is_finished:
            continue
        run_id = str(run.run_id)
        if run.status == DagsterRunStatus.SUCCESS:
            if (
                item.operation_key == MOIS_LOAD_JOB_NAME
                and run.tags.get(MOIS_LOAD_OUTCOME_TAG)
                == MOIS_LOAD_OUTCOME_BUDGET_EXHAUSTED
            ):
                decision = mois_load_continuation_decision(run)
                if isinstance(decision, RunRequest) and item.attempt_seq < MOIS_RELEASE_ATTEMPT_CAP:
                    await client.requeue_geo_release_item(plan.plan_id, item.position)
                    events.append(f"{item.position}:mois_continue")
                else:
                    await client.settle_geo_release_item(
                        plan.plan_id,
                        item.position,
                        state="failed",
                        reason="no_progress",
                        dagster_run_id=run_id,
                    )
                    events.append(f"{item.position}:no_progress")
                continue
            await client.settle_geo_release_item(
                plan.plan_id, item.position, state="done", dagster_run_id=run_id
            )
            events.append(f"{item.position}:done")
            continue
        if run.status == DagsterRunStatus.CANCELED:
            # 운영자가 취소했다 — 다시 내지 않는다(취소를 존중한다).
            await client.settle_geo_release_item(
                plan.plan_id,
                item.position,
                state="failed",
                reason="canceled",
                dagster_run_id=run_id,
            )
            events.append(f"{item.position}:canceled")
            continue
        if item.operation_key != MOIS_LOAD_JOB_NAME and item.attempt_seq < NON_MOIS_RETRY_ATTEMPTS:
            await client.requeue_geo_release_item(plan.plan_id, item.position)
            events.append(f"{item.position}:retry")
        else:
            await client.settle_geo_release_item(
                plan.plan_id,
                item.position,
                state="failed",
                reason="run_failed",
                dagster_run_id=run_id,
            )
            events.append(f"{item.position}:run_failed")
    return events


def _epoch(value: datetime) -> float:
    return value.timestamp()


async def evaluate_geo_release_tick(
    *,
    client: AsyncKorTravelMapClient,
    runs: RunLookup,
    geo: GeoTickSource,
    now: float,
) -> RunRequest | SkipReason:
    """센서 tick 1회 — 순서가 규칙이다(ADR-109 결정 5.1~5.6).

    1. 활성 큐 worker run이 있으면 Skip(큐 run이 전역 잠금을 쥔 동안 전용 job이 pool을 쥔 채
       멎는다).
    2. geo 현재 데이터셋 — 못 읽거나 ``data_token``이 없으면 Skip(계획 없음).
    3. 공용 계획 함수 — 기준선·끝난 토큰·롤백 정리는 그 함수가 정한다. 계획이 없으면 Skip.
    4. ``requested`` 항목을 run 결과로 전이(SUCCESS → done, MOIS ``budget_exhausted`` → 이어 달리기,
       실패 → 비-MOIS 1회 재요청, 취소 → ``failed(canceled)``(재요청 없음), 3 tick 무run →
       ``run_not_launched``).
    5. 항목이 전부 끝났으면 완료 판정(sweep 또는 링크 재동기화 → done).
    6. 진행 중 run이 없으면 다음 대기 항목 하나(게이트 통과·같은 operation run 없음)를 낸다.
    """
    worker = runs.active_queue_worker()
    if worker is not None:
        return SkipReason(f"feature update 큐 worker run {worker}이 진행 중이다 — 다음 tick")
    current = await geo.current()
    if current is None:
        return SkipReason("kor-travel-geo 현재 데이터셋을 읽지 못했다(미설정·장애·릴리스 없음)")
    if current.data_token is None:
        return SkipReason("geo data_token 없음 — 지문 backfill/복구 필요(계획하지 않는다)")
    outcome = await client.create_geo_release_plan(current)
    plan = outcome.plan
    if plan is None or outcome.kind not in ("existing", "created"):
        return SkipReason(f"계획 없음({outcome.kind}) — 토큰 {current.data_token}")
    events = await _settle_requested(client, plan, runs, now=now)
    refreshed = await client.get_geo_release_plan(plan.plan_id)
    if refreshed is None:
        return SkipReason(f"계획 {plan.plan_id}을 다시 읽지 못했다")
    plan = refreshed
    if plan.items and all(item.state in _TERMINAL_ITEM_STATES for item in plan.items):
        completion = await client.complete_geo_release_plan(
            plan.plan_id, sigungu_resolver=geo.sigungu_resolver
        )
        return SkipReason(
            f"계획 {plan.plan_id} 완료 판정: {completion.kind}"
            f"(sweep={list(completion.sweep_positions)}, target={completion.linked_target_count})"
        )
    in_flight = [item for item in plan.items if item.state == "requested"]
    if len(in_flight) >= GEO_RELEASE_MAX_IN_FLIGHT:
        return SkipReason(
            f"계획 {plan.plan_id}: 진행 중 run {[i.position for i in in_flight]} 대기"
            f" (이번 tick {events or '-'})"
        )
    launchable = [
        item
        for item in plan.items
        if item.state == "pending" and item.launch_blocked_reason is None
    ]
    if not launchable:
        return SkipReason(
            f"계획 {plan.plan_id}: 낼 수 있는 항목 없음 — 막힌 항목 {_blocked_summary(plan)}"
        )
    item = launchable[0]
    busy = runs.active_run_for(item.operation_key)
    if busy is not None:
        return SkipReason(f"{item.operation_key} run {busy}이 진행 중이다 — 겹쳐 내지 않는다")
    run_key = _run_key(plan, item)
    if not await client.mark_geo_release_item_requested(
        plan.plan_id, item.position, attempt_seq=item.attempt_seq, run_key=run_key
    ):
        return SkipReason(f"항목 {item.position}이 이미 다른 tick에서 요청됐다")
    return RunRequest(
        job_name=item.operation_key,
        run_key=run_key,
        run_config=dict(item.run_config or {}),
        tags={
            _TRIGGER_KIND_TAG: "sensor",
            GEO_RELEASE_PLAN_ID_TAG: str(plan.plan_id),
            GEO_RELEASE_RUN_KEY_TAG: run_key,
        },
    )


def _run_async(awaitable: Awaitable[_T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await(awaitable))
    raise RuntimeError("Dagster sensor 평가는 running event loop 밖에서 호출해야 함.")


async def _await(awaitable: Awaitable[_T]) -> _T:
    return await awaitable


async def _tick(
    client: AsyncKorTravelMapClient,
    runs: RunLookup,
    source: Callable[[], Any] = _settings_geo_source,
) -> RunRequest | SkipReason:
    async with source() as geo:
        return await evaluate_geo_release_tick(
            client=client, runs=runs, geo=geo, now=time.time()
        )


@sensor(
    name="kor_travel_geo_release_sensor",
    jobs=FEATURE_LOAD_JOBS,
    minimum_interval_seconds=GEO_RELEASE_SENSOR_INTERVAL_SECONDS,
    default_status=DefaultSensorStatus.STOPPED,
    required_resource_keys={"kor_travel_map_client"},
    description=(
        "kor-travel-geo 새 데이터셋 감지 → 재지오코딩 계획 → 전용 job run을 하나씩"
        "(ADR-109 결정 5). "
        "첫 토큰은 기준선, replay 항목은 T-GR-08 전에는 내지 않는다. 기본 STOPPED."
    ),
)
def kor_travel_geo_release_sensor(
    context: SensorEvaluationContext,
) -> RunRequest | SkipReason:
    """tick 1회. 외부 효과는 geo ``dataset/version`` HTTP 1회(완료 tick은 sigungu 조회) + DB."""
    client = cast("AsyncKorTravelMapClient", context.resources.kor_travel_map_client)
    result = _run_async(_tick(client, _InstanceRuns(context.instance)))
    if isinstance(result, SkipReason):
        context.log.info(result.skip_message or "")
    return result
