"""transport 현재 상태를 Valkey에 세대 단위로 교체하는 job (ADR-114 1단계).

데이터셋마다 job 하나·schedule 하나다. op는 기존 transport export fetcher(``provider_fetchers``)로
원천을 끝까지 받고, ``providers.kor_travel_transport_state``로 값을 만들고,
``infra.valkey_state.ValkeyStateStore.swap``으로 새 세대를 쓴 뒤 포인터를 원자적으로 바꾼다.
교체 순서·거부 기준·잠금은 ADR-114 "구현 설계 — 1단계" D3·D4가 정본이다.

- **기존 PG transport 적재는 그대로다**(ADR-114 결정 7). 이 job은 PG를 읽지도 쓰지도 않는다 —
  ``kor_travel_map_client`` 같은 Map resource를 요구하지 않는다.
- geo를 부르지 않는다. 행정 코드는 transport export가 실어 줄 때까지 비어 있다(결정 6).
- schedule은 **기본 STOPPED**다. Valkey가 배포된 뒤 Dagster UI(Schedules)나 ``dagster schedule
  start <이름>``으로 켠다. 첫 교체 전에는 REST가 503 ``TRANSPORT_STATE_NOT_LOADED``다.
- 실패 분류(2026-11-24 개정, ``upstream_signal``이 정본): transport 503·``collection``
  stale/실패·무응답 같은 **상류 미준비**는 step 재시도 없이 이번 tick을 건너뛰고(run 성공, 세대
  유지) 서비스 세대의 원천 나이를 남긴다. 0건 export·교체 거부(``state_swap_refused``)도 세대를
  지키고 건너뛴다. 어느 결과든 서비스 세대가 데이터셋 stale 기준(``max_age``)을 넘으면 run은
  재시도 없이 실패한다. 그 밖의 transport
  실패는 기존 규약(``raise_terminal_if_transport_unrecoverable``)을 따르고, 동시
  교체(``state_swap_conflict``)·Valkey OOM·미설정은 step 재시도를 끈다. Valkey 연결 실패만 step을
  다시 돈다(op가 직접 요청 — ``RetryPolicy``를 쓰지 않는다).
- 다른 적재가 같은 데이터셋을 잡고 있으면(잠금) 이번 run은 아무것도 하지 않고 성공으로 끝난다.
"""

# ``from __future__ import annotations``를 쓰지 않는다 — Dagster가 op의 ``context`` 주석을
# 실제 타입으로 검사하므로 문자열 주석이면 정의 시점에 거부한다(maintenance.py와 같다).
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from kortravelmap.infra.valkey_state import (
    GenerationMeta,
    StateNotLoaded,
    StateStoreError,
    StateSwapRefused,
    ValkeyStateStore,
    make_valkey_client,
)
from kortravelmap.providers.kor_travel_transport import TransportExportEmpty
from kortravelmap.providers.kor_travel_transport_state import (
    DATASET_AIRPORTS,
    DATASET_FUEL_STATIONS,
    DATASET_HIGHWAY_INCIDENTS,
    DATASET_REST_AREA_FUEL_PRICES,
    DATASET_REST_AREAS,
    TransportStateDataset,
    airport_state,
    fuel_station_state,
    highway_incident_state,
    rest_area_fuel_price_state,
    rest_area_state,
    to_state_item,
)
from kortravelmap.settings import KorTravelMapSettings

from dagster import (
    MAX_RUNTIME_SECONDS_TAG,
    DefaultScheduleStatus,
    Failure,
    Field,
    JobDefinition,
    OpExecutionContext,
    ScheduleDefinition,
    job,
    op,
)

from .provider_fetchers import (
    fetch_transport_airports,
    fetch_transport_fuel_stations,
    fetch_transport_highway_incidents,
    fetch_transport_rest_area_fuel_prices,
    fetch_transport_rest_areas,
)
from .quota_exhaustion import raise_terminal_if_transport_unrecoverable
from .schedule_overrides import cron_for_schedule
from .schedules import KST_TIMEZONE
from .upstream_requests import (
    UPSTREAM_REQUESTS_METADATA_KEY,
    counting_upstream_requests,
    observed_upstream_requests,
)
from .upstream_retry import sharing_run_retry_budget
from .upstream_signal import (
    UPSTREAM_NOT_READY,
    UPSTREAM_OK,
    raise_if_stale,
    refused,
    report_upstream_signal,
    retry_state_store_outage,
    run_deadline,
    upstream_not_ready_kind,
    upstream_signal,
)

__all__ = [
    "TRANSPORT_STATE_JOBS",
    "TRANSPORT_STATE_JOB_TAGS",
    "TRANSPORT_STATE_SCHEDULES",
    "TRANSPORT_STATE_SPECS",
    "TransportStateJobSpec",
    "collect_transport_state_items",
    "load_transport_state",
    "lock_ttl_seconds",
]

TRANSPORT_STATE_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": "state",
    "kor_travel_map.job_kind": "transport_state",
    "kor_travel_map.timezone": KST_TIMEZONE,
}
"""상태 적재 job 공통 tag. feature operation이 아니므로 ``operation_key``를 달지 않는다."""

Collector = Callable[[KorTravelMapSettings, Callable[[datetime], None]], Awaitable[list[Any]]]


async def _collect_fuel_stations(
    settings: KorTravelMapSettings, on_collected_at: Callable[[datetime], None]
) -> list[Any]:
    return [
        to_state_item(fuel_station_state(station))
        async for station in fetch_transport_fuel_stations(
            settings, on_collected_at=on_collected_at
        )
    ]


async def _collect_rest_areas(
    settings: KorTravelMapSettings, on_collected_at: Callable[[datetime], None]
) -> list[Any]:
    return [
        to_state_item(rest_area_state(area))
        async for area in fetch_transport_rest_areas(settings, on_collected_at=on_collected_at)
    ]


async def _collect_rest_area_fuel_prices(
    settings: KorTravelMapSettings, on_collected_at: Callable[[datetime], None]
) -> list[Any]:
    items = []
    async for record in fetch_transport_rest_area_fuel_prices(
        settings, on_collected_at=on_collected_at
    ):
        value = rest_area_fuel_price_state(record)
        items.append(
            to_state_item(value, lookup_keys=(value.match_key,) if value.match_key else ())
        )
    return items


async def _collect_highway_incidents(
    settings: KorTravelMapSettings, on_collected_at: Callable[[datetime], None]
) -> list[Any]:
    return [
        to_state_item(highway_incident_state(incident))
        async for incident in fetch_transport_highway_incidents(
            settings, on_collected_at=on_collected_at
        )
    ]


async def _collect_airports(
    settings: KorTravelMapSettings, on_collected_at: Callable[[datetime], None]
) -> list[Any]:
    # 공항 export에는 수집 상태(collection)가 없다 — 원천 수집 시각을 알릴 것이 없다.
    del on_collected_at
    return [
        to_state_item(airport_state(airport))
        async for airport in fetch_transport_airports(settings)
    ]


@dataclass(frozen=True, slots=True)
class TransportStateJobSpec:
    """데이터셋 하나의 job·schedule 정의."""

    dataset: TransportStateDataset
    job_name: str
    schedule_name: str
    cron_schedule: str
    max_runtime_seconds: int
    collect: Collector
    description: str


TRANSPORT_STATE_SPECS: Final[tuple[TransportStateJobSpec, ...]] = (
    TransportStateJobSpec(
        dataset=DATASET_FUEL_STATIONS,
        job_name="transport_state_fuel_stations",
        schedule_name="transport_state_fuel_stations_schedule",
        cron_schedule="17 * * * *",
        max_runtime_seconds=1_800,
        collect=_collect_fuel_stations,
        description="주유소 + 유종별 최신가 → Valkey 세대 교체(매시).",
    ),
    TransportStateJobSpec(
        dataset=DATASET_REST_AREAS,
        job_name="transport_state_rest_areas",
        schedule_name="transport_state_rest_areas_schedule",
        cron_schedule="47 4 * * *",
        max_runtime_seconds=900,
        collect=_collect_rest_areas,
        description="고속도로 휴게소 → Valkey 세대 교체(매일).",
    ),
    TransportStateJobSpec(
        dataset=DATASET_REST_AREA_FUEL_PRICES,
        job_name="transport_state_rest_area_fuel_prices",
        schedule_name="transport_state_rest_area_fuel_prices_schedule",
        cron_schedule="27 * * * *",
        max_runtime_seconds=900,
        collect=_collect_rest_area_fuel_prices,
        description="휴게소 주유소 최신 유가 → Valkey 세대 교체(매시).",
    ),
    TransportStateJobSpec(
        dataset=DATASET_HIGHWAY_INCIDENTS,
        job_name="transport_state_highway_incidents",
        schedule_name="transport_state_highway_incidents_schedule",
        cron_schedule="3-59/10 * * * *",
        max_runtime_seconds=480,
        collect=_collect_highway_incidents,
        description="고속도로 활성 돌발 → Valkey 세대 교체(10분마다).",
    ),
    TransportStateJobSpec(
        dataset=DATASET_AIRPORTS,
        job_name="transport_state_airports",
        schedule_name="transport_state_airports_schedule",
        cron_schedule="53 4 * * *",
        max_runtime_seconds=600,
        collect=_collect_airports,
        description="국내 운영 공항 → Valkey 세대 교체(매일).",
    ),
)


async def collect_transport_state_items(
    spec: TransportStateJobSpec, settings: KorTravelMapSettings
) -> tuple[list[Any], datetime | None]:
    """원천을 끝까지 받아 상태 항목과 원천 수집 시각(페이지 중 가장 이른 값)을 돌려준다."""
    collected: list[datetime] = []
    items = await spec.collect(settings, collected.append)
    return items, (min(collected) if collected else None)


_CANCEL_GRACE_SECONDS: Final[int] = 600
"""``docker/dagster.yaml``의 run 취소 유예(``cancel_timeout_seconds``)."""


def lock_ttl_seconds(spec: TransportStateJobSpec) -> int:
    """적재 잠금 TTL — run 상한 + 취소 유예 + 60초."""
    return spec.max_runtime_seconds + _CANCEL_GRACE_SECONDS + 60


def _terminal(exc: StateStoreError) -> Failure:
    return Failure(
        description=f"Valkey 상태 적재 실패({exc.failure_kind}) — step 재시도를 끈다: {exc}",
        metadata={
            "failure_kind": exc.failure_kind,
            "state_error": type(exc).__name__,
            "step_retries_suppressed": "true",
        },
        allow_retries=False,
    )


async def _served_meta(store: ValkeyStateStore, dataset: str) -> GenerationMeta | None:
    """지금 서비스하는 세대 meta. 없거나(첫 적재 전) 읽지 못하면 ``None``."""
    try:
        return await store.current_meta(dataset)
    except (StateNotLoaded, StateStoreError):
        return None


async def load_transport_state(
    spec: TransportStateJobSpec,
    *,
    settings: KorTravelMapSettings,
    run_id: str | None,
    allow_shrink: bool,
    store: ValkeyStateStore | None = None,
) -> dict[str, Any]:
    """한 데이터셋을 받아 Valkey 세대를 교체한다. 반환값은 op metadata다.

    ``store``를 넘기지 않으면 settings로 client를 만들고 끝나면 닫는다. 상류 미준비면 교체 없이
    ``skipped=upstream_not_ready``로, 0건·비정상 집합이면 ``skipped=refused``로 끝난다. run을
    실패시킬지는 op가 서비스 세대 나이로 정한다(``upstream_signal.raise_if_stale``).
    """
    owned = store is None
    try:
        active = store if store is not None else ValkeyStateStore(make_valkey_client(settings))
    except StateStoreError as exc:
        raise _terminal(exc) from exc
    try:
        # 잠금 TTL = run 상한 + 취소 유예 + 여유 — 죽은 run의 잠금이 다음 tick들을 오래 막지
        # 않으면서, 취소 중인 run보다 먼저 풀리지도 않게.
        async with active.load_lock(
            spec.dataset.name, ttl_seconds=lock_ttl_seconds(spec)
        ) as acquired:
            if not acquired:
                return {"dataset": spec.dataset.name, "skipped": "locked"}
            with counting_upstream_requests(), sharing_run_retry_budget():
                try:
                    items, source_collected_at = await collect_transport_state_items(
                        spec, settings
                    )
                except TransportExportEmpty as exc:
                    # 0건 export는 교체 거부와 같은 데이터 보호다 — 같은 규칙으로 끝낸다.
                    return refused(
                        dataset=spec.dataset.name,
                        failure_kind=exc.failure_kind,
                        description=str(exc),
                        served=await _served_meta(active, spec.dataset.name),
                        alert_after=spec.dataset.max_age,
                        now=datetime.now(UTC),
                        details={"baseline": -1, "new_count": 0},
                    )
                except Exception as exc:
                    kind = upstream_not_ready_kind(exc)
                    if kind is None:
                        raise_terminal_if_transport_unrecoverable(exc)
                        raise
                    not_ready: dict[str, Any] = {
                        "dataset": spec.dataset.name,
                        "skipped": "upstream_not_ready",
                        "failure_kind": kind,
                        "reason": str(exc)[:500],
                        **upstream_signal(
                            UPSTREAM_NOT_READY,
                            served=await _served_meta(active, spec.dataset.name),
                            alert_after=spec.dataset.max_age,
                            now=datetime.now(UTC),
                            reason=kind,
                        ),
                    }
                    observed = observed_upstream_requests()
                    if observed is not None:
                        not_ready[UPSTREAM_REQUESTS_METADATA_KEY] = observed
                    return not_ready
                upstream = observed_upstream_requests()
            result = await active.swap(
                spec.dataset.name,
                items,
                guard=spec.dataset.guard,
                source_collected_at=source_collected_at,
                loaded_at=datetime.now(UTC),
                run_id=run_id,
                allow_shrink=allow_shrink,
            )
            try:
                retired = await active.retire_other_versions(spec.dataset.name)
            except StateStoreError:
                retired = -1
        metadata: dict[str, Any] = {
            "dataset": spec.dataset.name,
            "generation": result.meta.generation,
            "previous_generation": result.previous_generation or "",
            "count": result.meta.count,
            "geo_count": result.meta.geo_count,
            "duplicates": result.meta.duplicates,
            "baseline": result.baseline if result.baseline is not None else -1,
            "source_collected_at": (
                result.meta.source_collected_at.isoformat()
                if result.meta.source_collected_at is not None
                else ""
            ),
            "guard_override": result.meta.guard_override,
            "retired_other_version_keys": retired,
            **upstream_signal(
                UPSTREAM_OK,
                served=result.meta,
                alert_after=spec.dataset.max_age,
                now=datetime.now(UTC),
            ),
        }
        if upstream is not None:
            metadata[UPSTREAM_REQUESTS_METADATA_KEY] = upstream
        return metadata
    except StateSwapRefused as exc:
        return refused(
            dataset=spec.dataset.name,
            failure_kind=exc.failure_kind,
            description=str(exc),
            served=await _served_meta(active, spec.dataset.name),
            alert_after=spec.dataset.max_age,
            now=datetime.now(UTC),
            details={
                "baseline": exc.baseline if exc.baseline is not None else -1,
                "new_count": exc.new_count,
            },
        )
    except StateStoreError as exc:
        if exc.retryable:
            raise
        raise _terminal(exc) from exc
    finally:
        if owned:
            await active.client.aclose()


_OP_CONFIG: Final[dict[str, Field]] = {
    "allow_shrink": Field(
        bool,
        default_value=False,
        is_required=False,
        description=(
            "true면 비정상 집합 거부(ADR-114 D4)를 이번 한 번 넘긴다. 원천이 진짜로 줄었을 때만 "
            "쓴다 — "
            "세대 meta에 guard_override=1로 남는다."
        ),
    ),
}


_RUN_TAIL_SECONDS: Final[int] = 60
"""Valkey 재시도 대기가 run 상한에 닿지 않게 남겨 두는 꼬리."""


def _build_job(spec: TransportStateJobSpec) -> JobDefinition:
    # retry_policy를 달지 않는다 — Dagster는 retry policy가 있는 step이 run 상한 초과 취소로
    # 끝나도 재시도를 요청한다. Valkey 연결 실패만 op가 직접 재시도를 요청한다(upstream_signal).
    @op(
        name=f"{spec.job_name}_op",
        config_schema=_OP_CONFIG,
        description=spec.description,
    )
    async def _load_op(context: OpExecutionContext) -> dict[str, Any]:
        deadline = run_deadline(context, spec.max_runtime_seconds, _RUN_TAIL_SECONDS)
        try:
            metadata = await load_transport_state(
                spec,
                settings=KorTravelMapSettings(),
                run_id=context.run_id,
                allow_shrink=bool(context.op_config.get("allow_shrink", False)),
            )
        except StateStoreError as exc:
            if exc.retryable:
                retry_state_store_outage(context, exc, deadline=deadline)
            raise
        if metadata.get("skipped") == "locked":
            context.log.info("%s: 다른 적재가 잠금을 쥐고 있어 건너뛴다.", spec.dataset.name)
        report_upstream_signal(context, metadata)
        raise_if_stale(metadata)
        context.add_output_metadata(metadata)
        return metadata

    tags = {
        **TRANSPORT_STATE_JOB_TAGS,
        MAX_RUNTIME_SECONDS_TAG: str(spec.max_runtime_seconds),
    }

    @job(name=spec.job_name, tags=tags, description=spec.description)
    def _state_job() -> None:
        _load_op()

    return _state_job


TRANSPORT_STATE_JOBS: Final[tuple[JobDefinition, ...]] = tuple(
    _build_job(spec) for spec in TRANSPORT_STATE_SPECS
)

TRANSPORT_STATE_SCHEDULES: Final[tuple[ScheduleDefinition, ...]] = tuple(
    ScheduleDefinition(
        name=spec.schedule_name,
        job=job_definition,
        cron_schedule=cron_for_schedule(spec.schedule_name, spec.cron_schedule),
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags={**TRANSPORT_STATE_JOB_TAGS, MAX_RUNTIME_SECONDS_TAG: str(spec.max_runtime_seconds)},
        description=f"{spec.description} Valkey 배포 전까지 STOPPED.",
    )
    for spec, job_definition in zip(TRANSPORT_STATE_SPECS, TRANSPORT_STATE_JOBS, strict=True)
)
"""상태 적재 schedule. 운영 enable 전까지 STOPPED(ADR-114 D7)."""
