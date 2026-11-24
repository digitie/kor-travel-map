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
- 실패 분류: transport 실패는 기존 규약(``raise_terminal_if_transport_unrecoverable``)을 따르고,
  교체 거부 (``state_swap_refused``)·동시 교체(``state_swap_conflict``)·Valkey OOM·미설정은 step
  재시도를 끈다 (다음 tick이 다시 본다). Valkey 연결 실패는 재시도한다.
- **transport 503 code**(2026-11-24 계약, 감사 MC-01): 근거 수집이 현재가 아니라고 code로 알린 503
  (``EXPORT_SOURCE_NOT_CURRENT``·``EXPORT_NO_HISTORY``·``EXPORT_INCIDENTS_NOT_CURRENT``·
  ``EXPORT_EMPTY_SET``)과 ``Retry-After``가 HTTP 층 상한보다 긴 경합 503은 step 재시도 없이 **run을
  실패로** 끝낸다(``outcome=skipped_upstream_not_current``, code·``Retry-After``·서비스 세대의 원천
  수집 시각을 metadata에). 세대는 그대로다. Map에는 상류 장애 경보가 따로 없어 빨간 run이 유일한
  신호이므로 초록으로 건너뛰지 않는다. 경합(``EXPORT_BUSY`` 등)은 fetcher가 같은 요청을 다시
  보낸다. ``EXPORT_DISABLED``·``EXPORT_TOO_LARGE``는 기존 규약
  (``raise_terminal_if_transport_unrecoverable``)으로 재시도 없이 실패하고,
  ``EXPORT_SOURCE_INCONSISTENT``와 code가 없거나 모르는 code의 503은 step 재시도다.
- **바뀌지 않은 집합은 다시 받지 않는다**(주유소·휴게소 유가, 감사 MC-04): 첫 페이지의
  ``collection.last_success_at``이 서비스 세대의 원천 수집 시각과 같고 그 세대를 적재한 지
  :data:`FULL_WALK_INTERVAL`이 안 됐으면 나머지 페이지와 교체를 건너뛴다(``skipped=unchanged``,
  run 성공). 주기마다 한 번은 전량을 받는다 — ``admin`` 주소처럼 ``last_success_at`` 없이 바뀌는
  필드가 있다.
- 요청마다 걸린 시간과 transport ``Server-Timing``(app·sql)을 ``transport_http_*``·
  ``transport_server_*`` metadata로 남긴다(:mod:`.transport_http_metrics`).
- 다른 적재가 같은 데이터셋을 잡고 있으면(잠금) 이번 run은 아무것도 하지 않고 성공으로 끝난다.
"""

# ``from __future__ import annotations``를 쓰지 않는다 — Dagster가 op의 ``context`` 주석을
# 실제 타입으로 검사하므로 문자열 주석이면 정의 시점에 거부한다(maintenance.py와 같다).
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

from kortravelmap.infra.valkey_state import (
    GenerationMeta,
    StateNotLoaded,
    StateStoreError,
    StateSwapRefused,
    ValkeyStateStore,
    make_valkey_client,
)
from kortravelmap.providers.kor_travel_transport import (
    TransportExportBusy,
    TransportExportFailure,
    TransportSourceNotCurrent,
)
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
    Backoff,
    DefaultScheduleStatus,
    Failure,
    Field,
    JobDefinition,
    OpExecutionContext,
    RetryPolicy,
    ScheduleDefinition,
    job,
    op,
)

from .provider_fetchers import (
    TransportExportUnchanged,
    fetch_transport_airports,
    fetch_transport_fuel_stations,
    fetch_transport_highway_incidents,
    fetch_transport_rest_area_fuel_prices,
    fetch_transport_rest_areas,
)
from .quota_exhaustion import raise_terminal_if_transport_unrecoverable
from .schedule_overrides import cron_for_schedule
from .schedules import KST_TIMEZONE
from .transport_http_metrics import observing_transport_http, transport_http_metadata
from .upstream_requests import (
    UPSTREAM_REQUESTS_METADATA_KEY,
    counting_upstream_requests,
    observed_upstream_requests,
)
from .upstream_retry import sharing_run_retry_budget

__all__ = [
    "FULL_WALK_INTERVAL",
    "TRANSPORT_STATE_JOBS",
    "TRANSPORT_STATE_JOB_TAGS",
    "TRANSPORT_STATE_RETRY_POLICY",
    "TRANSPORT_STATE_SCHEDULES",
    "TRANSPORT_STATE_SPECS",
    "TransportStateJobSpec",
    "collect_transport_state_items",
    "load_transport_state",
    "lock_ttl_seconds",
]

TRANSPORT_STATE_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy(
    max_retries=2,
    delay=30,
    backoff=Backoff.EXPONENTIAL,
)
"""Valkey 연결 실패·code 없는 transport 503 같은 기다리면 풀리는 실패만 다시 돈다.

Dagster 지수 backoff는 ``((2**n) - 1) × delay``라 실패 뒤 30초, 그다음 90초에 다시 돈다.
transport가 code로 "이 run 안에서는 풀리지 않는다"고 알린 503은 이 정책을 타지 않는다
(``allow_retries=False``)."""

TRANSPORT_STATE_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": "state",
    "kor_travel_map.job_kind": "transport_state",
    "kor_travel_map.timezone": KST_TIMEZONE,
}
"""상태 적재 job 공통 tag. feature operation이 아니므로 ``operation_key``를 달지 않는다."""

class Collector(Protocol):
    """원천을 끝까지 받아 상태 항목을 만든다. ``unchanged_since``는 바뀌지 않은 집합 건너뛰기 기준
    (지원하는 데이터셋만 쓰고, 첫 페이지가 같으면 :class:`TransportExportUnchanged`)."""

    def __call__(
        self,
        settings: KorTravelMapSettings,
        on_collected_at: Callable[[datetime], None],
        /,
        *,
        unchanged_since: datetime | None = None,
    ) -> Awaitable[list[Any]]: ...


FULL_WALK_INTERVAL: Final[timedelta] = timedelta(hours=6)
"""바뀌지 않은 집합 건너뛰기를 해도 이 간격마다 한 번은 전량을 받는다(서비스 세대 적재 시각
기준). T1 ``admin`` 주소는 주소 job으로 바뀌어 ``last_success_at``만으로는 보이지 않는다(감사
MC-04 정정)."""


async def _collect_fuel_stations(
    settings: KorTravelMapSettings,
    on_collected_at: Callable[[datetime], None],
    /,
    *,
    unchanged_since: datetime | None = None,
) -> list[Any]:
    return [
        to_state_item(fuel_station_state(station))
        async for station in fetch_transport_fuel_stations(
            settings, on_collected_at=on_collected_at, unchanged_since=unchanged_since
        )
    ]


async def _collect_rest_areas(
    settings: KorTravelMapSettings,
    on_collected_at: Callable[[datetime], None],
    /,
    *,
    unchanged_since: datetime | None = None,
) -> list[Any]:
    del unchanged_since  # 매일 한 번이라 건너뛰지 않는다
    return [
        to_state_item(rest_area_state(area))
        async for area in fetch_transport_rest_areas(settings, on_collected_at=on_collected_at)
    ]


async def _collect_rest_area_fuel_prices(
    settings: KorTravelMapSettings,
    on_collected_at: Callable[[datetime], None],
    /,
    *,
    unchanged_since: datetime | None = None,
) -> list[Any]:
    items = []
    async for record in fetch_transport_rest_area_fuel_prices(
        settings, on_collected_at=on_collected_at, unchanged_since=unchanged_since
    ):
        value = rest_area_fuel_price_state(record)
        items.append(
            to_state_item(value, lookup_keys=(value.match_key,) if value.match_key else ())
        )
    return items


async def _collect_highway_incidents(
    settings: KorTravelMapSettings,
    on_collected_at: Callable[[datetime], None],
    /,
    *,
    unchanged_since: datetime | None = None,
) -> list[Any]:
    del unchanged_since  # 페이지 없는 단건이라 건너뛸 것이 없다
    return [
        to_state_item(highway_incident_state(incident))
        async for incident in fetch_transport_highway_incidents(
            settings, on_collected_at=on_collected_at
        )
    ]


async def _collect_airports(
    settings: KorTravelMapSettings,
    on_collected_at: Callable[[datetime], None],
    /,
    *,
    unchanged_since: datetime | None = None,
) -> list[Any]:
    # 공항 export에는 수집 상태(collection)가 없다 — 원천 수집 시각을 알릴 것이 없다.
    del on_collected_at, unchanged_since
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
    skip_unchanged: bool = False
    """첫 페이지 ``last_success_at``이 서비스 세대와 같으면 건너뛴다(:data:`FULL_WALK_INTERVAL`)."""


TRANSPORT_STATE_SPECS: Final[tuple[TransportStateJobSpec, ...]] = (
    TransportStateJobSpec(
        dataset=DATASET_FUEL_STATIONS,
        job_name="transport_state_fuel_stations",
        schedule_name="transport_state_fuel_stations_schedule",
        cron_schedule="17 * * * *",
        max_runtime_seconds=1_800,
        collect=_collect_fuel_stations,
        description="주유소 + 유종별 최신가 → Valkey 세대 교체(매시, 바뀌지 않았으면 건너뜀).",
        skip_unchanged=True,
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
        description="휴게소 주유소 최신 유가 → Valkey 세대 교체(매시, 바뀌지 않았으면 건너뜀).",
        skip_unchanged=True,
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
    spec: TransportStateJobSpec,
    settings: KorTravelMapSettings,
    *,
    unchanged_since: datetime | None = None,
) -> tuple[list[Any], datetime | None]:
    """원천을 끝까지 받아 상태 항목과 원천 수집 시각(페이지 중 가장 이른 값)을 돌려준다.

    ``unchanged_since``가 첫 페이지와 같으면 :class:`TransportExportUnchanged`가 그대로 올라간다.
    """
    collected: list[datetime] = []
    if unchanged_since is None:
        items = await spec.collect(settings, collected.append)
    else:
        items = await spec.collect(settings, collected.append, unchanged_since=unchanged_since)
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
    """지금 서비스하는 세대 meta. 없거나(첫 적재 전) 읽지 못하면 ``None``(판단을 막지 않는다)."""
    try:
        return await store.current_meta(dataset)
    except (StateNotLoaded, StateStoreError):
        return None


def _unchanged_since(meta: GenerationMeta | None, *, now: datetime) -> datetime | None:
    """건너뛰기 기준 — 서비스 세대의 원천 수집 시각. 세대가 없거나 전량 주기가 됐으면 ``None``."""
    if meta is None or meta.source_collected_at is None:
        return None
    if now - meta.loaded_at >= FULL_WALK_INTERVAL:
        return None
    return meta.source_collected_at


def _iso_or_blank(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _upstream_stop(exc: BaseException) -> TransportExportFailure | None:
    """transport가 503 code로 "이 run 안에서는 풀리지 않는다"고 알린 실패. 아니면 ``None``.

    :class:`TransportSourceNotCurrent`(code 4종)와 ``Retry-After``가 HTTP 층 상한보다 긴 경합
    (:class:`TransportExportBusy` ``retryable=False``)이다. ``__cause__``만 따른다.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TransportSourceNotCurrent | TransportExportBusy):
            return None if current.retryable else current
        current = current.__cause__
    return None


def _request_metadata() -> dict[str, Any]:
    """이 적재가 transport에 보낸 요청 수(하한)와 요청 계측. 재지 않았으면 key를 싣지 않는다."""
    metadata: dict[str, Any] = {}
    upstream = observed_upstream_requests()
    if upstream is not None:
        metadata[UPSTREAM_REQUESTS_METADATA_KEY] = upstream
    metadata.update(transport_http_metadata())
    return metadata


async def load_transport_state(
    spec: TransportStateJobSpec,
    *,
    settings: KorTravelMapSettings,
    run_id: str | None,
    allow_shrink: bool,
    store: ValkeyStateStore | None = None,
) -> dict[str, Any]:
    """한 데이터셋을 받아 Valkey 세대를 교체한다. 반환값은 op metadata다.

    ``store``를 넘기지 않으면 settings로 client를 만들고 끝나면 닫는다. 바뀌지 않은 집합이면 교체
    없이 ``skipped=unchanged``로 끝난다. transport가 503 code로 근거 수집이 현재가 아니라고 알리면
    재시도 없는 :class:`dagster.Failure`(``outcome=skipped_upstream_not_current``)다.
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
            served = await _served_meta(active, spec.dataset.name) if spec.skip_unchanged else None
            unchanged_since = _unchanged_since(served, now=datetime.now(UTC))
            with (
                counting_upstream_requests(),
                sharing_run_retry_budget(),
                observing_transport_http(),
            ):
                try:
                    items, source_collected_at = await collect_transport_state_items(
                        spec, settings, unchanged_since=unchanged_since
                    )
                except TransportExportUnchanged:
                    assert served is not None  # unchanged_since가 있었다
                    return {
                        "dataset": spec.dataset.name,
                        "skipped": "unchanged",
                        "generation": served.generation,
                        "source_collected_at": _iso_or_blank(served.source_collected_at),
                        "generation_loaded_at": served.loaded_at.isoformat(),
                        "generation_age_seconds": int(
                            (datetime.now(UTC) - served.loaded_at).total_seconds()
                        ),
                        "full_walk_interval_seconds": int(FULL_WALK_INTERVAL.total_seconds()),
                        **_request_metadata(),
                    }
                except Exception as exc:
                    stop = _upstream_stop(exc)
                    if stop is not None:
                        raise await _upstream_not_current_failure(
                            spec, active, stop, served=served
                        ) from exc
                    raise_terminal_if_transport_unrecoverable(exc)
                    raise
                requests = _request_metadata()
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
            "source_collected_at": _iso_or_blank(result.meta.source_collected_at),
            "guard_override": result.meta.guard_override,
            "retired_other_version_keys": retired,
            **requests,
        }
        return metadata
    except StateSwapRefused as exc:
        raise Failure(
            description=str(exc),
            metadata={
                "failure_kind": exc.failure_kind,
                "dataset": spec.dataset.name,
                "baseline": exc.baseline if exc.baseline is not None else -1,
                "new_count": exc.new_count,
                "step_retries_suppressed": "true",
                "override": "run config ops.<op>.config.allow_shrink: true",
            },
            allow_retries=False,
        ) from exc
    except StateStoreError as exc:
        if exc.retryable:
            raise
        raise _terminal(exc) from exc
    finally:
        if owned:
            await active.client.aclose()


async def _upstream_not_current_failure(
    spec: TransportStateJobSpec,
    store: ValkeyStateStore,
    stop: TransportExportFailure,
    *,
    served: GenerationMeta | None,
) -> Failure:
    """transport가 code로 근거 수집이 현재가 아니라고 알렸다 — 재시도 없이 run을 실패시킨다.

    세대는 건드리지 않았다(REST는 직전 세대를 ``age_seconds``·``stale``과 함께 계속 낸다). 초록으로
    건너뛰지 않는 이유: Map에는 상류 장애 경보가 따로 없어 빨간 run이 유일한 신호다.
    """
    if served is None:
        served = await _served_meta(store, spec.dataset.name)
    now = datetime.now(UTC)
    retry_after = stop.retry_after
    metadata: dict[str, Any] = {
        "dataset": spec.dataset.name,
        "outcome": "skipped_upstream_not_current",
        "failure_kind": stop.failure_kind,
        "transport_problem_code": stop.code or "",
        "transport_retry_after_seconds": float(retry_after) if retry_after is not None else -1.0,
        "served_generation": served.generation if served is not None else "",
        "last_success_at": _iso_or_blank(served.source_collected_at if served else None),
        "served_age_seconds": (
            int((now - served.source_collected_at).total_seconds())
            if served is not None and served.source_collected_at is not None
            else -1
        ),
        "step_retries_suppressed": "true",
        **_request_metadata(),
    }
    collected = metadata["last_success_at"] or "모름"
    served_text = (
        f"서비스 세대 {served.generation}(원천 수집 {collected})를 그대로 둔다"
        if served is not None
        else "서비스할 세대가 아직 없다(첫 적재 전 — REST는 503)"
    )
    wait = f"{retry_after:.0f}초" if retry_after is not None else "알리지 않음"
    return Failure(
        description=(
            f"{spec.dataset.name}: transport가 503 code={stop.code}(Retry-After {wait})로 근거 "
            f"수집이 이 run 안에서는 현재가 되지 않는다고 알렸다 — step 재시도 없이 실패한다. "
            f"{served_text}. transport 수집 상태를 본다."
        ),
        metadata=metadata,
        allow_retries=False,
    )


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


def _build_job(spec: TransportStateJobSpec) -> JobDefinition:
    @op(
        name=f"{spec.job_name}_op",
        config_schema=_OP_CONFIG,
        retry_policy=TRANSPORT_STATE_RETRY_POLICY,
        description=spec.description,
    )
    async def _load_op(context: OpExecutionContext) -> dict[str, Any]:
        metadata = await load_transport_state(
            spec,
            settings=KorTravelMapSettings(),
            run_id=context.run_id,
            allow_shrink=bool(context.op_config.get("allow_shrink", False)),
        )
        if metadata.get("skipped") == "locked":
            context.log.info("%s: 다른 적재가 잠금을 쥐고 있어 건너뛴다.", spec.dataset.name)
        elif metadata.get("skipped") == "unchanged":
            context.log.info(
                "%s: 근거 수집(%s)이 서비스 세대와 같아 교체하지 않는다(전량은 %s초마다).",
                spec.dataset.name,
                metadata.get("source_collected_at"),
                metadata.get("full_walk_interval_seconds"),
            )
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
