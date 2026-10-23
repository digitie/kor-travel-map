"""weather 현재·예보·세 구간 요약을 Valkey에 세대 단위로 교체하는 job (ADR-114 2단계).

데이터셋마다 job 하나·schedule 하나다(일곱). op는 kor-travel-weather의 Map용 export(W1·W2·W3·W5)를
끝까지 받고, ``providers.kor_travel_weather_state``로 위치 단위 값을 만들고,
``infra.valkey_state.ValkeyStateStore.swap``으로 새 세대를 쓴 뒤 포인터를 원자적으로 바꾼다. 교체
순서·거부 기준·잠금은 1단계(``transport_state``)와 같은 store가 맡는다 — ADR-114 "구현 설계 — 1단계"
D3·D4와 "2단계" W3·W4가 정본이다.

- **PG를 읽지도 쓰지도 않는다.** Map의 weather feature 적재는 ADR-105가 지웠고 그대로다 — 이 job은
  ``kor_travel_map_client``를 요구하지 않고 weather 값을 PG에 쓰는 core 경로를 부르지 않는다.
- geo를 부르지 않는다. 법정동 코드는 weather W1 값을 그대로 쓴다(결정 6).
- schedule은 **기본 STOPPED**다. weather에 W1~W5가 배포되고(``KOR_TRAVEL_WEATHER_SERVICE_EXPORTS_ENABLED``)
  Map code-server에 weather 주소·토큰이 들어간 뒤 켠다. 첫 교체 전에는 REST가 503이다.
- 실패 분류: 503(``weather_not_ready``)·410 재시도 소진·Valkey 연결 실패는 step 재시도 대상이고,
  401·404·계약 위반·JSON 아님·교체 거부·동시 교체·Valkey OOM·미설정은 step 재시도를 끈다.
- 다른 적재가 같은 데이터셋을 잡고 있으면(잠금) 이번 run은 아무것도 하지 않고 성공으로 끝난다.
"""

# ``from __future__ import annotations``를 쓰지 않는다 — Dagster가 op의 ``context`` 주석을
# 실제 타입으로 검사한다(transport_state.py와 같다).
import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, TypeVar

import httpx
from kortravelmap.infra.valkey_state import (
    StateItem,
    StateStoreError,
    StateSwapRefused,
    ValkeyStateStore,
    make_valkey_client,
)
from kortravelmap.providers.kor_travel_weather import (
    ADMIN_TOKEN_HEADER,
    EXPORT_PATH_CURRENT,
    EXPORT_PATH_DAILY_SUMMARIES,
    EXPORT_PATH_FORECASTS,
    EXPORT_PATH_LOCATIONS,
    WeatherExportContractError,
    WeatherExportCurrentValue,
    WeatherExportDailySummary,
    WeatherExportFailure,
    WeatherExportForecastGroup,
    WeatherExportLocation,
    WeatherExportMalformed,
    WeatherExportMissing,
    WeatherExportNotReady,
    WeatherExportPage,
    WeatherExportSnapshotExpired,
    WeatherExportUnauthorized,
    parse_current_page,
    parse_daily_summary_page,
    parse_forecast_page,
    parse_location_page,
)
from kortravelmap.providers.kor_travel_weather_state import (
    DATASET_CURRENT,
    DATASET_DAILY_SUMMARIES,
    DATASET_FORECAST_EXTERNAL,
    DATASET_FORECAST_MID,
    DATASET_FORECAST_SHORT,
    DATASET_FORECAST_ULTRA_SHORT,
    DATASET_LOCATIONS,
    CurrentGrouper,
    DailySummaryGrouper,
    ForecastGrouper,
    WeatherStateDataset,
    earliest_or_none,
    location_state_items,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import BaseModel

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

from . import upstream_retry
from .schedule_overrides import cron_for_schedule
from .schedules import KST_TIMEZONE
from .upstream_requests import (
    UPSTREAM_REQUESTS_METADATA_KEY,
    counting_upstream_requests,
    note_upstream_request,
    observed_upstream_requests,
)
from .upstream_retry import sharing_run_retry_budget

__all__ = [
    "WEATHER_STATE_JOBS",
    "WEATHER_STATE_JOB_TAGS",
    "WEATHER_STATE_RETRY_POLICY",
    "WEATHER_STATE_SCHEDULES",
    "WEATHER_STATE_SPECS",
    "WeatherCollected",
    "WeatherExportNotConfigured",
    "WeatherFetch",
    "WeatherStateJobSpec",
    "fetch_weather_current",
    "fetch_weather_daily_summaries",
    "fetch_weather_forecasts",
    "fetch_weather_locations",
    "load_weather_state",
    "weather_http_timeout",
    "weather_lock_ttl_seconds",
]

_LOGGER = logging.getLogger(__name__)

WEATHER_STATE_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy(
    max_retries=2,
    delay=30,
    backoff=Backoff.EXPONENTIAL,
)
"""Valkey 연결 실패·weather 503 같은 기다리면 풀리는 실패만 다시 돈다."""

WEATHER_STATE_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": "state",
    "kor_travel_map.job_kind": "weather_state",
    "kor_travel_map.timezone": KST_TIMEZONE,
}
"""상태 적재 job 공통 tag. feature operation이 아니므로 ``operation_key``를 달지 않는다."""


# -- weather export HTTP ----------------------------------------------------------


class WeatherExportNotConfigured(WeatherExportFailure):
    """weather 주소·토큰이 없다. 설정을 넣어야 풀린다."""

    failure_kind = "weather_not_configured"


def _weather_connection(settings: KorTravelMapSettings) -> tuple[str, dict[str, str]]:
    """base URL과 인증 header. 빈 문자열도 미설정으로 본다(compose ``${X:-}``)."""
    base_url = (settings.kor_travel_weather_base_url or "").strip()
    token = settings.kor_travel_weather_service_token
    secret = token.get_secret_value().strip() if token is not None else ""
    if not base_url:
        raise WeatherExportNotConfigured(
            "weather 상태 적재에는 KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_BASE_URL이 필요하다."
        )
    if not secret:
        raise WeatherExportNotConfigured(
            "weather 상태 적재에는 KOR_TRAVEL_MAP_KOR_TRAVEL_WEATHER_SERVICE_TOKEN"
            "(weather KOR_TRAVEL_WEATHER_ADMIN_TOKEN과 같은 값)이 필요하다."
        )
    return base_url.rstrip("/"), {ADMIN_TOKEN_HEADER: secret}


def weather_http_timeout(settings: KorTravelMapSettings) -> httpx.Timeout:
    """weather client의 ``httpx.Timeout`` — read는 넉넉히(페이지 최대 4 MiB), 연결 수립은 짧게.

    weather는 다른 호스트(odroid)에 있어 꺼지면 무응답이다(ADR-110 결정 3과 같은 이유).
    ``tests/lint/test_geo_transport_clients_use_timeout_factory.py``가 생성 지점마다 강제한다.
    """
    return httpx.Timeout(
        settings.kor_travel_weather_timeout_seconds,
        connect=settings.kor_travel_weather_connect_timeout_seconds,
    )


_WEATHER_MAX_PAGES: Final[int] = 2_000
"""페이지 루프 상한. 넘으면 cursor 계약이 깨진 것이다(같은 cursor 반복은 즉시 잡는다)."""

_WEATHER_TRANSIENT_STATUSES: Final[frozenset[int]] = frozenset({502, 504})
_WEATHER_RETRY_BASE_DELAY_SECONDS: float = upstream_retry.PROVIDER_BOUNDARY_BASE_DELAY_SECONDS
"""HTTP 층 재시도 간격 기준(테스트가 0으로 바꾼다)."""


class _WeatherTransientStatus(WeatherExportFailure):
    """502/504. HTTP 층에서 유한 재시도하고, 소진하면 step 재시도 대상이다."""

    failure_kind = "weather_transient_status"
    retryable = True


def _raise_weather_status(response: httpx.Response, path: str) -> None:
    status = response.status_code
    if status == 401:
        raise WeatherExportUnauthorized(
            f"kor-travel-weather {path}가 401이다 — 토큰이 weather KOR_TRAVEL_WEATHER_ADMIN_TOKEN과 "
            "다르다."
        )
    if status == 404:
        raise WeatherExportMissing(
            f"kor-travel-weather {path}가 404다 — W1~W5 export가 없는 weather 버전이거나 주소가 "
            "틀렸다."
        )
    if status == 410:
        raise WeatherExportSnapshotExpired(f"kor-travel-weather {path} snapshot이 만료됐다(410).")
    if status == 503:
        raise WeatherExportNotReady(
            f"kor-travel-weather {path}가 503이다 — 완결된 성공 export가 아직 없다(빈 정상 "
            "집합이 아니다). 이번 run은 아무것도 쓰지 않는다."
        )
    if status == 422:
        raise WeatherExportContractError(f"kor-travel-weather {path}가 422다(cursor·질의 계약).")
    if status in _WEATHER_TRANSIENT_STATUSES:
        raise _WeatherTransientStatus(f"kor-travel-weather {path}가 {status}다.")
    if status != 200:
        raise WeatherExportFailure(f"kor-travel-weather {path}가 {status}다.")


async def _weather_request_once(
    client: httpx.AsyncClient, path: str, params: Mapping[str, Any]
) -> httpx.Response:
    """HTTP 요청 정확히 1건 — 시도마다 여기서 센다(재시도도 요청이다)."""
    note_upstream_request()
    response = await client.get(path, params=dict(params))
    _raise_weather_status(response, path)
    return response


def _weather_retryable(exc: BaseException) -> bool:
    return isinstance(exc, httpx.TransportError | _WeatherTransientStatus)


async def _weather_get(
    client: httpx.AsyncClient,
    path: str,
    params: Mapping[str, Any],
    *,
    budget: upstream_retry.RetryBudget,
) -> httpx.Response:
    """요청 1건(전송 오류·502/504는 유한 재시도). 규약은 transport fetcher와 같다."""
    attempts = upstream_retry.DEFAULT_UPSTREAM_ATTEMPTS
    for attempt in range(1, attempts + 1):
        try:
            return await _weather_request_once(client, path, params)
        except Exception as exc:
            if attempt >= attempts or not _weather_retryable(exc) or not budget.try_consume():
                raise
            delay = min(
                _WEATHER_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
                upstream_retry.DEFAULT_UPSTREAM_MAX_DELAY_SECONDS,
            )
            _LOGGER.warning(
                "kor-travel-weather %s 재시도 %d/%d (%s)", path, attempt, attempts,
                type(exc).__name__,
            )
            await asyncio.sleep(delay)
    raise AssertionError(f"unreachable: kor-travel-weather {path}")  # pragma: no cover


def _weather_json(response: httpx.Response, path: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise WeatherExportMalformed(
            f"kor-travel-weather {path} 응답이 JSON이 아니다(status={response.status_code}, "
            f"content-type={response.headers.get('content-type', '')!r}, "
            f"bytes={len(response.content)})."
        ) from exc


_ItemT = TypeVar("_ItemT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class WeatherFetch:
    """export 하나를 끝까지 받은 결과."""

    rows: list[Any]
    source_collected_at: datetime | None
    """페이지들 중 가장 이른 원천 수집 시각. 한 페이지라도 null이면 null(ADR-114 W4)."""
    source_status: str
    """페이지들 중 가장 나쁜 상태(``stale`` > ``ok``)."""
    pages: int
    snapshot_id: str | None


async def _read_all_pages(
    settings: KorTravelMapSettings,
    path: str,
    params: Mapping[str, Any],
    parse: Callable[[Any], WeatherExportPage[_ItemT]],
) -> WeatherFetch:
    """cursor를 끝까지 따라간다. 410(snapshot 만료)이면 첫 페이지부터 **한 번** 다시 받는다."""
    base_url, headers = _weather_connection(settings)
    shared = upstream_retry.active_run_retry_budget()
    budget = shared if shared is not None else upstream_retry.RetryBudget()
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=weather_http_timeout(settings),
        headers=headers,
    ) as client:
        for restart in range(2):
            try:
                return await _walk_pages(client, path, params, parse, budget=budget)
            except WeatherExportSnapshotExpired:
                if restart:
                    raise
                _LOGGER.warning("kor-travel-weather %s snapshot 만료 — 처음부터 다시 받는다.", path)
    raise AssertionError("unreachable")  # pragma: no cover


async def _walk_pages(
    client: httpx.AsyncClient,
    path: str,
    params: Mapping[str, Any],
    parse: Callable[[Any], WeatherExportPage[_ItemT]],
    *,
    budget: upstream_retry.RetryBudget,
) -> WeatherFetch:
    rows: list[Any] = []
    collected: list[datetime | None] = []
    statuses: set[str] = set()
    snapshot_id: str | None = None
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for page_number in range(1, _WEATHER_MAX_PAGES + 1):
        query = dict(params)
        if cursor is not None:
            query["cursor"] = cursor
        response = await _weather_get(client, path, query, budget=budget)
        page = parse(_weather_json(response, path))
        if page_number == 1:
            snapshot_id = page.meta.snapshot_id
        elif page.meta.snapshot_id != snapshot_id:
            raise WeatherExportContractError(
                f"{path}: 페이지 {page_number}의 snapshot_id가 첫 페이지와 다르다."
            )
        rows.extend(page.items)
        collected.append(page.meta.source_collected_at)
        statuses.add(page.meta.source_status)
        if not page.meta.has_more:
            return WeatherFetch(
                rows=rows,
                source_collected_at=earliest_or_none(collected),
                source_status="stale" if "stale" in statuses else "ok",
                pages=page_number,
                snapshot_id=snapshot_id,
            )
        next_cursor = page.meta.next_cursor
        assert next_cursor is not None  # 파서가 보장한다.
        if next_cursor in seen_cursors or next_cursor == cursor:
            raise WeatherExportContractError(f"{path}: next_cursor가 이미 지난 cursor다(순환).")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise WeatherExportContractError(f"{path}: {_WEATHER_MAX_PAGES}페이지를 넘었다.")


async def fetch_weather_locations(settings: KorTravelMapSettings) -> WeatherFetch:
    """W1 위치 roster 전체."""
    return await _read_all_pages(
        settings,
        EXPORT_PATH_LOCATIONS,
        {"limit": settings.kor_travel_weather_page_size},
        parse_location_page,
    )


async def fetch_weather_current(settings: KorTravelMapSettings) -> WeatherFetch:
    """W2 활성 관측 제공처 전체의 최신 관측."""
    return await _read_all_pages(
        settings,
        EXPORT_PATH_CURRENT,
        {"limit": settings.kor_travel_weather_page_size},
        parse_current_page,
    )


async def fetch_weather_forecasts(settings: KorTravelMapSettings, style: str) -> WeatherFetch:
    """W3 한 style의 예보 묶음 전체(증분 ``since`` 없이 전량 — ADR-114 W3)."""
    return await _read_all_pages(
        settings,
        EXPORT_PATH_FORECASTS,
        {"style": style, "limit": settings.kor_travel_weather_page_size},
        lambda payload: parse_forecast_page(payload, style=style),
    )


async def fetch_weather_daily_summaries(settings: KorTravelMapSettings) -> WeatherFetch:
    """W5 최근 ``weather_daily_summary_days``일 세 구간 요약 전체."""
    return await _read_all_pages(
        settings,
        EXPORT_PATH_DAILY_SUMMARIES,
        {
            "days": settings.weather_daily_summary_days,
            "limit": settings.kor_travel_weather_page_size,
        },
        parse_daily_summary_page,
    )


# -- 상태 항목 ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WeatherCollected:
    items: list[StateItem]
    row_duplicates: int
    """위치 안에서 같은 관측·묶음·(날짜, 구간)이 두 번 와서 버린 행 수(ADR-114 W1)."""
    fetch: WeatherFetch


Collector = Callable[[KorTravelMapSettings], Awaitable[WeatherCollected]]


async def _collect_locations(settings: KorTravelMapSettings) -> WeatherCollected:
    fetch = await fetch_weather_locations(settings)
    rows: list[WeatherExportLocation] = fetch.rows
    return WeatherCollected(items=location_state_items(rows), row_duplicates=0, fetch=fetch)


async def _collect_current(settings: KorTravelMapSettings) -> WeatherCollected:
    fetch = await fetch_weather_current(settings)
    grouper = CurrentGrouper()
    row: WeatherExportCurrentValue
    for row in fetch.rows:
        grouper.add(row)
    return WeatherCollected(grouper.items(), grouper.duplicates, fetch)


def _forecast_collector(dataset: WeatherStateDataset) -> Collector:
    style = dataset.style
    assert style is not None

    async def _collect(settings: KorTravelMapSettings) -> WeatherCollected:
        fetch = await fetch_weather_forecasts(settings, style)
        grouper = ForecastGrouper(style=style)
        group: WeatherExportForecastGroup
        for group in fetch.rows:
            grouper.add(group)
        return WeatherCollected(grouper.items(), grouper.duplicates, fetch)

    return _collect


async def _collect_daily_summaries(settings: KorTravelMapSettings) -> WeatherCollected:
    fetch = await fetch_weather_daily_summaries(settings)
    grouper = DailySummaryGrouper()
    row: WeatherExportDailySummary
    for row in fetch.rows:
        grouper.add(row)
    return WeatherCollected(grouper.items(), grouper.duplicates, fetch)


@dataclass(frozen=True, slots=True)
class WeatherStateJobSpec:
    """데이터셋 하나의 job·schedule 정의."""

    dataset: WeatherStateDataset
    job_name: str
    schedule_name: str
    cron_schedule: str
    max_runtime_seconds: int
    collect: Collector
    description: str


def _spec(
    dataset: WeatherStateDataset,
    suffix: str,
    cron: str,
    max_runtime_seconds: int,
    collect: Collector,
    description: str,
) -> WeatherStateJobSpec:
    return WeatherStateJobSpec(
        dataset=dataset,
        job_name=f"weather_state_{suffix}",
        schedule_name=f"weather_state_{suffix}_schedule",
        cron_schedule=cron,
        max_runtime_seconds=max_runtime_seconds,
        collect=collect,
        description=description,
    )


WEATHER_STATE_SPECS: Final[tuple[WeatherStateJobSpec, ...]] = (
    _spec(
        DATASET_LOCATIONS, "locations", "37 4 * * *", 900, _collect_locations,
        "weather 위치 roster(W1) → Valkey 세대 교체(매일).",
    ),
    _spec(
        DATASET_CURRENT, "current", "6-59/10 * * * *", 480, _collect_current,
        "weather 최신 관측·실황(W2) → Valkey 세대 교체(10분마다).",
    ),
    _spec(
        DATASET_FORECAST_ULTRA_SHORT, "forecast_ultra_short", "14,44 * * * *", 600,
        _forecast_collector(DATASET_FORECAST_ULTRA_SHORT),
        "weather 초단기예보(W3 ultra_short) → Valkey 세대 교체(30분마다).",
    ),
    _spec(
        DATASET_FORECAST_SHORT, "forecast_short", "24 * * * *", 1_500,
        _forecast_collector(DATASET_FORECAST_SHORT),
        "weather 단기예보(W3 short) → Valkey 세대 교체(매시).",
    ),
    _spec(
        DATASET_FORECAST_MID, "forecast_mid", "34 */3 * * *", 900,
        _forecast_collector(DATASET_FORECAST_MID),
        "weather 중기예보(W3 mid) → Valkey 세대 교체(3시간마다).",
    ),
    _spec(
        DATASET_FORECAST_EXTERNAL, "forecast_external", "54 * * * *", 1_200,
        _forecast_collector(DATASET_FORECAST_EXTERNAL),
        "weather 외부 provider 예보(W3 external) → Valkey 세대 교체(매시).",
    ),
    _spec(
        DATASET_DAILY_SUMMARIES, "daily_summaries", "41 * * * *", 900, _collect_daily_summaries,
        "weather 하루 세 구간 요약(W5) → Valkey 세대 교체(매시).",
    ),
)


_CANCEL_GRACE_SECONDS: Final[int] = 600
"""``docker/dagster.yaml``의 run 취소 유예(``cancel_timeout_seconds``) — transport_state와 같다."""


def weather_lock_ttl_seconds(spec: WeatherStateJobSpec) -> int:
    """적재 잠금 TTL — run 상한 + 취소 유예 + 60초(1단계 D3과 같은 규칙)."""
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


def _raise_terminal_if_weather_unrecoverable(exc: BaseException) -> None:
    """weather 실패 중 기다려도 풀리지 않는 것(401·404·계약·JSON 아님·미설정)이면 재시도를 끈다."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, WeatherExportFailure | WeatherExportContractError):
            if current.retryable:
                return
            raise Failure(
                description=(
                    f"kor-travel-weather 실패({current.failure_kind}) — 기다려도 풀리지 않으므로 "
                    f"step 재시도를 끈다. 원 예외: {type(current).__name__}: {current}"
                ),
                metadata={
                    "failure_kind": current.failure_kind,
                    "provider_error": type(current).__name__,
                    "step_retries_suppressed": "true",
                },
                allow_retries=False,
            ) from current
        current = current.__cause__


async def load_weather_state(
    spec: WeatherStateJobSpec,
    *,
    settings: KorTravelMapSettings,
    run_id: str | None,
    allow_shrink: bool,
    store: ValkeyStateStore | None = None,
) -> dict[str, Any]:
    """한 데이터셋을 받아 Valkey 세대를 교체한다. 반환값은 op metadata다.

    ``store``를 넘기지 않으면 settings로 client를 만들고 끝나면 닫는다.
    """
    owned = store is None
    try:
        active = store if store is not None else ValkeyStateStore(make_valkey_client(settings))
    except StateStoreError as exc:
        raise _terminal(exc) from exc
    try:
        async with active.load_lock(
            spec.dataset.name, ttl_seconds=weather_lock_ttl_seconds(spec)
        ) as acquired:
            if not acquired:
                return {"dataset": spec.dataset.name, "skipped": "locked"}
            with counting_upstream_requests(), sharing_run_retry_budget():
                try:
                    collected = await spec.collect(settings)
                except Exception as exc:
                    _raise_terminal_if_weather_unrecoverable(exc)
                    raise
                upstream = observed_upstream_requests()
            result = await active.swap(
                spec.dataset.name,
                collected.items,
                guard=spec.dataset.guard,
                source_collected_at=collected.fetch.source_collected_at,
                loaded_at=datetime.now(UTC),
                run_id=run_id,
                allow_shrink=allow_shrink,
                source_status=collected.fetch.source_status,
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
            "row_duplicates": collected.row_duplicates,
            "source_rows": len(collected.fetch.rows),
            "pages": collected.fetch.pages,
            "baseline": result.baseline if result.baseline is not None else -1,
            "source_collected_at": (
                result.meta.source_collected_at.isoformat()
                if result.meta.source_collected_at is not None
                else ""
            ),
            "source_status": collected.fetch.source_status,
            "guard_override": result.meta.guard_override,
            "retired_other_version_keys": retired,
        }
        if upstream is not None:
            metadata[UPSTREAM_REQUESTS_METADATA_KEY] = upstream
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


_OP_CONFIG: Final[dict[str, Field]] = {
    "allow_shrink": Field(
        bool,
        default_value=False,
        is_required=False,
        description=(
            "true면 비정상 집합 거부(ADR-114 D4)를 이번 한 번 넘긴다. 원천이 진짜로 줄었을 때만 "
            "쓴다 — 세대 meta에 guard_override=1로 남는다."
        ),
    ),
}


def _build_job(spec: WeatherStateJobSpec) -> JobDefinition:
    @op(
        name=f"{spec.job_name}_op",
        config_schema=_OP_CONFIG,
        retry_policy=WEATHER_STATE_RETRY_POLICY,
        description=spec.description,
    )
    async def _load_op(context: OpExecutionContext) -> dict[str, Any]:
        metadata = await load_weather_state(
            spec,
            settings=KorTravelMapSettings(),
            run_id=context.run_id,
            allow_shrink=bool(context.op_config.get("allow_shrink", False)),
        )
        if metadata.get("skipped"):
            context.log.info("%s: 다른 적재가 잠금을 쥐고 있어 건너뛴다.", spec.dataset.name)
        context.add_output_metadata(metadata)
        return metadata

    tags = {
        **WEATHER_STATE_JOB_TAGS,
        MAX_RUNTIME_SECONDS_TAG: str(spec.max_runtime_seconds),
    }

    @job(name=spec.job_name, tags=tags, description=spec.description)
    def _state_job() -> None:
        _load_op()

    return _state_job


WEATHER_STATE_JOBS: Final[tuple[JobDefinition, ...]] = tuple(
    _build_job(spec) for spec in WEATHER_STATE_SPECS
)

WEATHER_STATE_SCHEDULES: Final[tuple[ScheduleDefinition, ...]] = tuple(
    ScheduleDefinition(
        name=spec.schedule_name,
        job=job_definition,
        cron_schedule=cron_for_schedule(spec.schedule_name, spec.cron_schedule),
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags={**WEATHER_STATE_JOB_TAGS, MAX_RUNTIME_SECONDS_TAG: str(spec.max_runtime_seconds)},
        description=f"{spec.description} weather W1~W5 배포·Map env 전까지 STOPPED.",
    )
    for spec, job_definition in zip(WEATHER_STATE_SPECS, WEATHER_STATE_JOBS, strict=True)
)
"""weather 상태 적재 schedule. 운영 enable 전까지 STOPPED(ADR-114 W8)."""
