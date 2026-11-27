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
- 실패 분류(2026-11-24 개정·소유자 결정 "나이 기준 혼합", ``upstream_signal``이 정본): transport
  503(code 없음·모르는 code, ``EXPORT_SOURCE_NOT_CURRENT``·``EXPORT_NO_HISTORY``·
  ``EXPORT_INCIDENTS_NOT_CURRENT``·``EXPORT_EMPTY_SET``, 대기 상한을 넘는 경합
  ``EXPORT_BUSY``·``EXPORT_PREPARE_TIMEOUT``·``TRANSIENT_DB``, ``EXPORT_SOURCE_INCONSISTENT``)·
  ``collection`` stale/실패·무응답·HTTP 재시도를 다 쓴 5xx·429 같은 **상류 미준비**는 step 재시도
  없이 이번 tick을 건너뛰고 세대를 지킨다(``skipped=upstream_not_ready``, code·``Retry-After``를
  metadata에). 0건 export·교체 거부(``state_swap_refused``)도 세대를 지키고 건너뛴다. **run 결과는
  서비스 세대의 원천 나이가 정한다**: 데이터셋 경고 임계(settings
  ``transport_state_<데이터셋>_alert_after_seconds`` — 읽기 쪽 ``max_age``보다 낮게 묶는다) 안이면
  초록, 넘으면 step 재시도 없는 실패다(빨간 run이 Map의 유일한 상류 경보다).
  ``EXPORT_DISABLED``·``EXPORT_TOO_LARGE``·404·계약 위반은 기존 규약
  (``raise_terminal_if_transport_unrecoverable``)으로 재시도 없이 실패하고, 동시
  교체(``state_swap_conflict``)·Valkey OOM·미설정도 재시도하지 않는다. Valkey 연결 실패만 step을
  다시 돈다(op가 직접 요청 — ``RetryPolicy``를 쓰지 않는다: Dagster는 retry policy가 있으면 run 상한
  취소에도 재시도를 요청한다).
- 경합 503(``EXPORT_BUSY`` 등)은 fetcher가 ``Retry-After``대로 같은 요청을 다시 보낸다(HTTP 층).
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
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
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
    TransportExportEmpty,
    TransportSourceNotCurrent,
)
from kortravelmap.providers.kor_travel_transport_state import (
    DATASET_AIRPORTS,
    DATASET_FUEL_STATIONS,
    DATASET_HIGHWAY_INCIDENTS,
    DATASET_REST_AREA_FOOD,
    DATASET_REST_AREA_FUEL_PRICES,
    DATASET_REST_AREAS,
    TransportStateDataset,
    airport_state,
    fuel_station_state,
    highway_incident_state,
    rest_area_food_states,
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
    TransportExportUnchanged,
    fetch_transport_airports,
    fetch_transport_fuel_stations,
    fetch_transport_highway_incidents,
    fetch_transport_rest_area_food,
    fetch_transport_rest_area_fuel_prices,
    fetch_transport_rest_areas,
)
from .quota_exhaustion import raise_terminal_if_transport_unrecoverable
from .run_priority import run_priority_tags
from .schedule_overrides import cron_for_schedule
from .schedules import KST_TIMEZONE
from .transport_http_metrics import observing_transport_http, transport_http_metadata
from .upstream_requests import (
    UPSTREAM_REQUESTS_METADATA_KEY,
    counting_upstream_requests,
    observed_upstream_requests,
)
from .upstream_retry import RetryBudget, sharing_run_retry_budget
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

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "FULL_WALK_INTERVAL",
    "RETRY_TIME_SHARE",
    "alert_after_seconds",
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


async def _collect_rest_area_food(
    settings: KorTravelMapSettings,
    on_collected_at: Callable[[datetime], None],
    /,
    *,
    unchanged_since: datetime | None = None,
) -> list[Any]:
    """휴게소 기준정보 + 먹거리 export → 휴게소마다 KREX 코드 연결·메뉴 요약(ADR-127).

    세대의 원천 수집 시각은 먹거리 export의 것이다(휴게소 기준정보 세대는
    ``transport_state_rest_areas``가
    따로 잰다).
    """
    del unchanged_since  # 매일 한 번이라 건너뛰지 않는다
    areas = [area async for area in fetch_transport_rest_areas(settings)]
    collected: list[datetime] = []

    def _seen(value: datetime) -> None:
        collected.append(value)
        on_collected_at(value)

    foods = [food async for food in fetch_transport_rest_area_food(settings, on_collected_at=_seen)]
    if not collected:
        raise TransportExportEmpty("rest-area-food: collection.last_success_at이 없다.")
    return [
        to_state_item(state)
        for state in rest_area_food_states(areas, foods, collected_at=min(collected))
    ]


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
    alert_after_setting: str = ""
    """상류 경고 임계(초)를 담은 settings 필드 이름(:func:`alert_after_seconds`). 서비스 세대의 원천
    나이가 이를 넘으면 run을 실패시킨다(``upstream_signal.raise_if_stale``, 소유자 결정 2026-11-24
    "나이 기준 혼합"). 읽기 쪽 ``dataset.max_age``(REST ``stale``)보다 낮게 묶는다."""
    skip_unchanged: bool = False
    """첫 페이지 ``last_success_at``이 서비스 세대와 같으면 건너뛴다(:data:`FULL_WALK_INTERVAL`)."""


TRANSPORT_STATE_SPECS: Final[tuple[TransportStateJobSpec, ...]] = (
    TransportStateJobSpec(
        dataset=DATASET_FUEL_STATIONS,
        job_name="transport_state_fuel_stations",
        alert_after_setting="transport_state_fuel_stations_alert_after_seconds",
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
        alert_after_setting="transport_state_rest_areas_alert_after_seconds",
        schedule_name="transport_state_rest_areas_schedule",
        cron_schedule="47 4 * * *",
        max_runtime_seconds=900,
        collect=_collect_rest_areas,
        description="고속도로 휴게소 → Valkey 세대 교체(매일).",
    ),
    TransportStateJobSpec(
        dataset=DATASET_REST_AREA_FUEL_PRICES,
        job_name="transport_state_rest_area_fuel_prices",
        alert_after_setting="transport_state_rest_area_fuel_prices_alert_after_seconds",
        schedule_name="transport_state_rest_area_fuel_prices_schedule",
        cron_schedule="27 * * * *",
        max_runtime_seconds=900,
        collect=_collect_rest_area_fuel_prices,
        description="휴게소 주유소 최신 유가 → Valkey 세대 교체(매시, 바뀌지 않았으면 건너뜀).",
        skip_unchanged=True,
    ),
    TransportStateJobSpec(
        dataset=DATASET_REST_AREA_FOOD,
        job_name="transport_state_rest_area_food",
        alert_after_setting="transport_state_rest_area_food_alert_after_seconds",
        schedule_name="transport_state_rest_area_food_schedule",
        # transport 휴게소 먹거리 수집(03:50 KST)과 휴게소 상태(04:47) 뒤.
        cron_schedule="7 5 * * *",
        max_runtime_seconds=900,
        collect=_collect_rest_area_food,
        description=(
            "휴게소 먹거리(한국도로공사 메뉴 요약·표준 코드 연결) → Valkey 세대 교체"
            "(매일, ADR-127)."
        ),
    ),
    TransportStateJobSpec(
        dataset=DATASET_HIGHWAY_INCIDENTS,
        job_name="transport_state_highway_incidents",
        alert_after_setting="transport_state_highway_incidents_alert_after_seconds",
        schedule_name="transport_state_highway_incidents_schedule",
        cron_schedule="3-59/10 * * * *",
        max_runtime_seconds=480,
        collect=_collect_highway_incidents,
        description="고속도로 활성 돌발 → Valkey 세대 교체(10분마다).",
    ),
    TransportStateJobSpec(
        dataset=DATASET_AIRPORTS,
        job_name="transport_state_airports",
        alert_after_setting="transport_state_airports_alert_after_seconds",
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
    except StateNotLoaded:
        return None


def _unchanged_since(meta: GenerationMeta | None, *, now: datetime) -> datetime | None:
    """건너뛰기 기준 — 서비스 세대의 원천 수집 시각. 세대가 없거나 전량 주기가 됐으면 ``None``.

    주기의 기준은 그 세대가 이어 온 마지막 전량 순회의 **시작** 시각(``full_synced_at``, 없으면
    옛 세대라 ``loaded_at``)이다 — 끝(교체) 시각을 쓰면 순회 시간만큼 늦어져 매시 tick에서 전량이
    7시간마다가 된다(#1549 적대 리뷰). 기준이 지금보다 미래면(시계 역행) 믿지 않고 전량을 받는다.
    """
    if meta is None or meta.source_collected_at is None:
        return None
    basis = meta.full_synced_at or meta.loaded_at
    if basis > now or now - basis >= FULL_WALK_INTERVAL:
        return None
    return meta.source_collected_at


RETRY_TIME_SHARE: Final[float] = 0.25
"""상태 job 하나가 HTTP 층 재시도(실패한 시도 + 대기)에 쓸 수 있는 시간 = run 상한 × 이 비율.
대기가 run 상한을 밀어내지 않게 한다(돌발 480초 → 120초, 휴게소 유가 900초 → 225초)."""


def alert_after_seconds(spec: TransportStateJobSpec, settings: KorTravelMapSettings) -> int:
    """데이터셋의 상류 경고 임계(초). 읽기 stale 기준(``max_age``)보다 작게 묶는다."""
    configured = int(getattr(settings, spec.alert_after_setting))
    return min(configured, int(spec.dataset.max_age.total_seconds()) - 1)


def _hold_metadata(exc: BaseException) -> dict[str, Any]:
    """transport 503 code가 알린 미준비의 ``outcome``과 대기 상한(있으면). ``__cause__``만 따른다.

    ``upstream_source_not_current``(근거 수집 미현재 code 4종)·``upstream_busy_exhausted``(HTTP 층
    재시도를 다 쓴 경합)·``upstream_busy_over_cap``(``Retry-After``가 대기 상한을 넘어 기다리지
    않은 경합). 그 밖의 미준비(code 없는 503·무응답 등)는 ``outcome=upstream_not_ready``다.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TransportSourceNotCurrent):
            return {
                "outcome": "upstream_source_not_current",
                "transport_retry_after_cap_seconds": -1.0,
            }
        if isinstance(current, TransportExportBusy):
            metadata: dict[str, Any] = {
                "outcome": (
                    "upstream_busy_over_cap"
                    if current.retry_after_exceeds_cap
                    else "upstream_busy_exhausted"
                )
            }
            metadata["transport_retry_after_cap_seconds"] = (
                float(current.retry_after_cap) if current.retry_after_cap is not None else -1.0
            )
            return metadata
        current = current.__cause__
    return {"outcome": "upstream_not_ready", "transport_retry_after_cap_seconds": -1.0}


def _iso_or_blank(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _problem_metadata(exc: BaseException) -> dict[str, Any]:
    """transport 503 problem ``code``·``Retry-After``. 원인 사슬(``__cause__``)을 따른다.

    모르는 값 규칙(상태 job metadata 공통, README): 원천 응답에서 읽는 값은 key를 언제나 싣고 모르면
    문자열 ``""``·수 ``-1``이다(code 없는 503·무응답). 재지 않은 계측(``transport_http_*``·
    ``upstream_requests_min``)만 key를 싣지 않는다 — "세지 않았다"를 0으로 읽지 않게.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "code", None)
        if isinstance(code, str) and code:
            retry_after = getattr(current, "retry_after", None)
            return {
                "transport_problem_code": code,
                "transport_retry_after_seconds": (
                    float(retry_after) if isinstance(retry_after, int | float) else -1.0
                ),
            }
        current = current.__cause__
    return {"transport_problem_code": "", "transport_retry_after_seconds": -1.0}


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
    force_full_walk: bool = False,
) -> dict[str, Any]:
    """한 데이터셋을 받아 Valkey 세대를 교체한다. 반환값은 op metadata다.

    ``store``를 넘기지 않으면 settings로 client를 만들고 끝나면 닫는다. 바뀌지 않은 집합이면 교체
    없이 ``skipped=unchanged``로, 상류 미준비면 ``skipped=upstream_not_ready``로, 0건·비정상
    집합이면 ``skipped=refused``로 끝난다. run을 실패시킬지는 op가 서비스 세대 나이로 정한다
    (``upstream_signal.raise_if_stale``).
    """
    owned = store is None
    served: GenerationMeta | None = None
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
            served = await _served_meta(active, spec.dataset.name)
            alert_after = timedelta(seconds=alert_after_seconds(spec, settings))
            walk_started = datetime.now(UTC)
            unchanged_since = (
                _unchanged_since(served, now=walk_started)
                if spec.skip_unchanged and not force_full_walk
                else None
            )
            budget = RetryBudget(max_seconds=spec.max_runtime_seconds * RETRY_TIME_SHARE)
            with (
                counting_upstream_requests(),
                sharing_run_retry_budget(budget),
                observing_transport_http(),
            ):
                try:
                    items, source_collected_at = await collect_transport_state_items(
                        spec, settings, unchanged_since=unchanged_since
                    )
                except TransportExportUnchanged:
                    assert served is not None  # unchanged_since가 있었다
                    # 원천이 그대로임을 확인한 시각을 세대 meta에 남긴다(weather 304와 같은
                    # checked_at). 판정 나이는 원천 수집 시각 기준이라 그대로다 — 기록일 뿐이다.
                    # 기록이라 실패가 run 색을 정하지 않게 한다(retire_other_versions와 같다).
                    checked_at = datetime.now(UTC)
                    try:
                        checked = await active.touch_checked(
                            spec.dataset.name, served.generation, checked_at
                        )
                    except StateStoreError as exc:
                        _LOGGER.warning(
                            "%s 확인 시각을 적지 못했다(%s) — 판정은 원천 나이로 그대로 한다.",
                            spec.dataset.name,
                            type(exc).__name__,
                        )
                        checked = False
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
                        "checked": checked,
                        **_request_metadata(),
                        **upstream_signal(
                            UPSTREAM_OK,
                            served=replace(served, checked_at=checked_at) if checked else served,
                            alert_after=alert_after,
                            now=datetime.now(UTC),
                            reason="unchanged",
                        ),
                    }
                except TransportExportEmpty as exc:
                    # 0건 export는 교체 거부와 같은 데이터 보호다 — 같은 규칙으로 끝낸다.
                    return refused(
                        dataset=spec.dataset.name,
                        failure_kind=exc.failure_kind,
                        description=str(exc),
                        served=served,
                        alert_after=alert_after,
                        now=datetime.now(UTC),
                        details={"baseline": -1, "new_count": 0, **_request_metadata()},
                    )
                except Exception as exc:
                    kind = upstream_not_ready_kind(exc)
                    if kind is None:
                        _LOGGER.warning(
                            "%s 실패 — transport 요청 계측: %s",
                            spec.dataset.name,
                            " ".join(f"{k}={v}" for k, v in transport_http_metadata().items())
                            or "-",
                        )
                        raise_terminal_if_transport_unrecoverable(exc)
                        raise
                    return {
                        "dataset": spec.dataset.name,
                        "skipped": "upstream_not_ready",
                        "failure_kind": kind,
                        "reason": str(exc)[:500],
                        **_hold_metadata(exc),
                        **_problem_metadata(exc),
                        **_request_metadata(),
                        **upstream_signal(
                            UPSTREAM_NOT_READY,
                            served=served,
                            alert_after=alert_after,
                            now=datetime.now(UTC),
                            reason=kind,
                        ),
                    }
                requests = _request_metadata()
            result = await active.swap(
                spec.dataset.name,
                items,
                guard=spec.dataset.guard,
                source_collected_at=source_collected_at,
                loaded_at=datetime.now(UTC),
                run_id=run_id,
                allow_shrink=allow_shrink,
                full_synced_at=walk_started,
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
            **upstream_signal(
                UPSTREAM_OK,
                served=result.meta,
                alert_after=alert_after,
                now=datetime.now(UTC),
            ),
        }
        return metadata
    except StateSwapRefused as exc:
        return refused(
            dataset=spec.dataset.name,
            failure_kind=exc.failure_kind,
            description=str(exc),
            served=served,  # 잠금 안에서 읽은 값 — 예외 처리 안에서 Valkey를 다시 읽지 않는다
            alert_after=timedelta(seconds=alert_after_seconds(spec, settings)),
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
    "force_full_walk": Field(
        bool,
        default_value=False,
        is_required=False,
        description=(
            "true면 바뀌지 않은 집합 건너뛰기를 이번 한 번 끄고 전량을 받는다 — Map 변환을 고친 "
            "뒤 다시 돌릴 때 쓴다(그렇지 않으면 다음 전량 주기까지 skipped=unchanged)."
        ),
    ),
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
                force_full_walk=bool(context.op_config.get("force_full_walk", False)),
            )
        except StateStoreError as exc:
            if exc.retryable:
                retry_state_store_outage(context, exc, deadline=deadline)
            raise
        if metadata.get("skipped") == "locked":
            context.log.info("%s: 다른 적재가 잠금을 쥐고 있어 건너뛴다.", spec.dataset.name)
        elif metadata.get("skipped") == "unchanged":
            context.log.info(
                "%s: 근거 수집(%s)이 서비스 세대와 같아 교체하지 않는다(전량은 %s초마다).",
                spec.dataset.name,
                metadata.get("source_collected_at"),
                metadata.get("full_walk_interval_seconds"),
            )
        report_upstream_signal(context, metadata)
        raise_if_stale(metadata)
        context.add_output_metadata(metadata)
        return metadata

    tags = {
        **TRANSPORT_STATE_JOB_TAGS,
        MAX_RUNTIME_SECONDS_TAG: str(spec.max_runtime_seconds),
        **run_priority_tags(spec.job_name),
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
