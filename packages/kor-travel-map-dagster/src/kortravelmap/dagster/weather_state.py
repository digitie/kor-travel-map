"""weather 현재·예보·세 구간 요약을 Valkey에 세대 단위로 교체하는 job (ADR-114 2단계).

데이터셋마다 job 하나·schedule 하나다(일곱). op는 kor-travel-weather의 Map용 export(W1·W2·W3·W5)를
끝까지 받고, ``providers.kor_travel_weather_state``로 위치 단위 값을 만들고,
``infra.valkey_state.ValkeyStateStore.swap``으로 새 세대를 쓴 뒤 포인터를 원자적으로 바꾼다. 교체
순서·거부 기준·잠금은 1단계(``transport_state``)와 같은 store가 맡는다 — ADR-114 "구현 설계 — 1단계"
D3·D4와 "2단계" W3·W4가 정본이다.

- **PG를 읽지도 쓰지도 않는다.** Map의 weather feature 적재는 ADR-105가 지웠고 그대로다 — 이 job은
  ``kor_travel_map_client``를 요구하지 않고 weather 값을 PG에 쓰는 core 경로를 부르지 않는다.
- geo를 부르지 않는다. 법정동 코드는 weather W1 값을 그대로 쓴다(결정 6).
- schedule은 **기본 STOPPED**다. weather에 W1~W5가 배포되고
  (``KOR_TRAVEL_WEATHER_SERVICE_EXPORTS_ENABLED``) Map code-server에 weather 주소·토큰이
  들어간 뒤 켠다. 첫 교체 전에는 REST가 503이다.
- 503은 먼저 **그 페이지만** 같은 cursor로 유한 재시도한다(``Retry-After``를 따르고, 대기와 가장 긴
  요청이 run 상한 안에 들 때만, 한 순회 대기 합 60초·run 재시도 예산 안에서). weather의
  ``EXPORT_TEMPORARILY_UNAVAILABLE``(읽기 경합)과, 그 구분이 없던 이전 weather의
  ``EXPORT_NOT_READY``가 대상이다.
- 실패 분류: 503(``weather_not_ready``) 페이지 재시도 소진·410 재시도 소진·Valkey 연결 실패는 step
  재시도 대상이고, 401·404·계약 위반·JSON 아님·교체 거부·동시 교체·Valkey OOM·미설정은 step
  재시도를 끈다.
- 다른 적재가 같은 데이터셋을 잡고 있으면(잠금) 이번 run은 아무것도 하지 않고 성공으로 끝난다.
- **예보(W3)는 증분이다(ADR-122).** 지금 세대 meta의 cursor(직전 ``next_since``)로 ``since``를
  보내 바뀐 묶음만 받고, 지금 세대에 병합한 새 세대를 같은 CAS 교체로 올린다(그 세대가 아직
  current일 때만). cursor가 없거나·전량 주기가 됐거나·운영자가 요청했거나·증분을 믿을 수 없으면
  (422·cursor 역행·계약 위반·기준 세대 불일치) 같은 run에서 전량을 받는다. 거부 기준(D4)은 전량에만
  건다.
"""

# ``from __future__ import annotations``를 쓰지 않는다 — Dagster가 op의 ``context`` 주석을
# 실제 타입으로 검사한다(transport_state.py와 같다).
import asyncio
import contextlib
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Final, TypeVar

import httpx
from kortravelmap.dto.weather_state import WeatherForecastState
from kortravelmap.infra.valkey_state import (
    GenerationMeta,
    StateItem,
    StateNotLoaded,
    StateStoreError,
    StateStoreUnavailable,
    StateSwapRefused,
    ValkeyStateStore,
    make_valkey_client,
)
from kortravelmap.providers.kor_travel_weather import (
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
    ForecastDeltaRefused,
    ForecastGrouper,
    ForecastMerge,
    WeatherStateDataset,
    earliest_or_none,
    forecast_membership_digest,
    location_state_items,
    merge_forecast_delta,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import BaseModel, ValidationError

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
    "ForecastSyncPlan",
    "WeatherCollected",
    "WeatherExportNotConfigured",
    "WeatherFetch",
    "WeatherStateJobSpec",
    "fetch_weather_current",
    "fetch_weather_daily_summaries",
    "fetch_weather_forecasts",
    "fetch_weather_locations",
    "forecast_sync_plan",
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
    return base_url.rstrip("/"), {settings.kor_travel_weather_auth_header: secret}


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

_WEATHER_RETRY_BASE_DELAY_SECONDS: float = upstream_retry.PROVIDER_BOUNDARY_BASE_DELAY_SECONDS
"""HTTP 층 재시도 간격 기준(테스트가 0으로 바꾼다)."""

_WEATHER_PAGE_ATTEMPTS: Final[int] = 4
"""503 한 페이지의 시도 상한(첫 요청 포함). 실패한 페이지만 같은 cursor로 다시 묻는다."""

_WEATHER_PAGE_RETRY_BASE_DELAY_SECONDS: Final[float] = 5.0
"""503 페이지 재시도 간격 기준(5·10·20초). ``Retry-After``가 더 길면 그것을 따른다."""

_WEATHER_PAGE_RETRY_MAX_DELAY_SECONDS: Final[float] = 60.0
"""한 번 기다리는 상한. ``Retry-After``가 이보다 길면 이 페이지를 다시 묻지 않고 실패한다(그 뒤는
step 재시도 몫이다 — ``RetryPolicy`` 30초가 ``Retry-After``보다 이를 수 있다)."""

_WEATHER_WALK_RETRY_SLEEP_SECONDS: Final[float] = 60.0
"""한 순회(``_read_all_pages``)의 503 페이지 재시도 대기 합 상한. 페이지마다 따로 맞는 재시도가
쌓여 run 상한을 넘기지 않게 한다 — 남은 페이지 수는 미리 알 수 없다."""

_WEATHER_RUN_TAIL_SECONDS: Final[int] = 60
"""페이지를 다 받은 뒤 Valkey 교체·정리에 남겨 두는 시간. run 상한에서 뺀다."""

_PAGE_RETRY_CODES: Final[frozenset[str | None]] = frozenset(
    {"EXPORT_TEMPORARILY_UNAVAILABLE", "EXPORT_NOT_READY", None}
)
"""페이지 재시도 대상 503 code. ``EXPORT_NOT_READY``는 읽기 경합을 그 이름으로 내던 이전 weather
때문이다(경합 code를 내는 weather가 배포되면 뺀다). ``None``은 code가 없는 503(앞단 프록시)이다.
그 밖의 명시 code(모양이 틀린 것 포함)는 곧바로 실패한다."""

_PROBLEM_CODE: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_INVALID_PROBLEM_CODE: Final[str] = "<invalid>"
"""``code``가 있으나 모양이 틀린 503 — 명시 code로 보고 재시도하지 않는다."""

_WEATHER_DEADLINE: Final[ContextVar[float | None]] = ContextVar(
    "kortravelmap_weather_deadline", default=None
)
"""이 적재가 페이지 재시도를 시작해도 되는 마지막 monotonic 시각. 없으면 시도 상한만 건다."""

_page_retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
"""503 페이지 재시도 대기(테스트가 기록용으로 바꾼다)."""


@contextlib.contextmanager
def _paging_deadline(deadline: float | None) -> Iterator[None]:
    token = _WEATHER_DEADLINE.set(deadline)
    try:
        yield
    finally:
        _WEATHER_DEADLINE.reset(token)


class _WeatherCursorRejected(WeatherExportContractError):
    """422. 첫 페이지면 질의 계약 위반(terminal)이고, 둘째 페이지 이후면 순회 도중 weather가
    재배포돼 provider 선택·서명이 바뀐 것일 수 있어 처음부터 **한 번** 다시 받는다(ADR-114 W3)."""

    failure_kind = "weather_cursor_rejected"


class _WeatherTransientStatus(WeatherExportFailure):
    """429와 503을 뺀 5xx(500 포함). HTTP 층에서 유한 재시도하고, 소진하면 step 재시도 대상이다."""

    failure_kind = "weather_transient_status"
    retryable = True


class _WeatherUnavailable(WeatherExportNotReady):
    """503. 페이지 재시도가 쓰는 problem ``code``와 ``Retry-After``(초)를 함께 든다."""

    def __init__(self, message: str, *, code: str | None, retry_after: float | None) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


def _problem_code(response: httpx.Response) -> str | None:
    """503 problem의 ``code``. JSON 객체가 아니거나 ``code``가 없으면(앞단 프록시) ``None``."""
    try:
        body = response.json()
    except (ValueError, RecursionError):
        return None
    if not isinstance(body, dict) or "code" not in body:
        return None
    code = body["code"]
    if isinstance(code, str) and _PROBLEM_CODE.fullmatch(code):
        return code
    return _INVALID_PROBLEM_CODE


def _retry_after_seconds(value: str | None) -> float | None:
    """``Retry-After``(초 또는 HTTP-date)를 초로. 읽을 수 없으면 ``None``."""
    text = (value or "").strip()
    if text.isascii() and text.isdigit():
        return float(int(text)) if len(text) <= 12 else 1e12  # 아주 길면 그냥 "아주 오래"
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:
        return None
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _raise_weather_status(response: httpx.Response, path: str) -> None:
    status = response.status_code
    if status == 401:
        raise WeatherExportUnauthorized(
            f"kor-travel-weather {path}가 401이다 — 토큰이 weather "
            "KOR_TRAVEL_WEATHER_ADMIN_TOKEN과 다르다."
        )
    if status == 404:
        raise WeatherExportMissing(
            f"kor-travel-weather {path}가 404다 — W1~W5 export가 없는 weather 버전이거나 주소가 "
            "틀렸다."
        )
    if status == 410:
        raise WeatherExportSnapshotExpired(f"kor-travel-weather {path} snapshot이 만료됐다(410).")
    if status == 503:
        code = _problem_code(response)
        reason = (
            "읽기 경합이다(같은 요청을 다시 보내면 된다)"
            if code == "EXPORT_TEMPORARILY_UNAVAILABLE"
            else "완결된 성공 export가 아직 없다(빈 정상 집합이 아니다)"
        )
        raise _WeatherUnavailable(
            f"kor-travel-weather {path}가 503(code={code})이다 — {reason}. 이번 run은 아무것도 "
            "쓰지 않는다.",
            code=code,
            retry_after=_retry_after_seconds(response.headers.get("retry-after")),
        )
    if status == 422:
        raise _WeatherCursorRejected(f"kor-travel-weather {path}가 422다(cursor·질의 계약).")
    if status == 429 or status >= 500:
        raise _WeatherTransientStatus(f"kor-travel-weather {path}가 {status}다.")
    if status == 304:
        return
    if status != 200:
        raise WeatherExportFailure(f"kor-travel-weather {path}가 {status}다.")


async def _weather_request_once(
    client: httpx.AsyncClient,
    path: str,
    params: Mapping[str, Any],
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    """HTTP 요청 정확히 1건 — 시도마다 여기서 센다(재시도도 요청이다)."""
    note_upstream_request()
    response = await client.get(path, params=dict(params), headers=dict(headers or {}))
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
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    """요청 1건(전송 오류·429·5xx는 유한 재시도, 503 제외). 규약은 transport fetcher와 같다."""
    attempts = upstream_retry.DEFAULT_UPSTREAM_ATTEMPTS
    for attempt in range(1, attempts + 1):
        try:
            return await _weather_request_once(client, path, params, headers)
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


@dataclass(slots=True)
class _PageClock:
    """한 순회의 503 페이지 재시도 시계.

    ``slowest``는 이 순회에서 가장 오래 걸린 요청이다. 재시도는 대기 + 그만큼의 요청이
    ``deadline``(run 상한 - 꼬리) 안에 들어갈 때만 시작한다 — 시작한 요청의 길이는 이미
    ``kor_travel_weather_timeout_seconds``가 묶는다.
    """

    deadline: float | None
    slowest: float = 0.0
    slept: float = 0.0

    def fits(self, delay: float) -> bool:
        if self.slept + delay > _WEATHER_WALK_RETRY_SLEEP_SECONDS:
            return False
        return self.deadline is None or time.monotonic() + delay + self.slowest <= self.deadline


async def _weather_get_page(
    client: httpx.AsyncClient,
    path: str,
    params: Mapping[str, Any],
    *,
    budget: upstream_retry.RetryBudget,
    clock: _PageClock,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    """페이지 요청 1건. 503이면 **그 페이지만** 같은 cursor로 유한 재시도한다(순회는 이어 간다)."""
    for attempt in range(1, _WEATHER_PAGE_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            response = await _weather_get(client, path, params, budget=budget, headers=headers)
        except _WeatherUnavailable as exc:
            clock.slowest = max(clock.slowest, time.monotonic() - started)
            delay = max(
                _WEATHER_PAGE_RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1), exc.retry_after or 0.0
            )
            if (
                attempt >= _WEATHER_PAGE_ATTEMPTS
                or exc.code not in _PAGE_RETRY_CODES
                or delay > _WEATHER_PAGE_RETRY_MAX_DELAY_SECONDS
                or not clock.fits(delay)
                or not budget.try_consume()  # 상관 장애면 run 재시도 예산이 먼저 끊는다
            ):
                raise
            clock.slept += delay
            _LOGGER.warning(
                "kor-travel-weather %s 503(code=%s) — %.0f초 뒤 같은 페이지 재시도 %d/%d",
                path, exc.code, delay, attempt, _WEATHER_PAGE_ATTEMPTS - 1,
            )
            await _page_retry_sleep(delay)
            continue
        clock.slowest = max(clock.slowest, time.monotonic() - started)
        return response
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
    etag: str | None = None
    """첫 페이지 ETag(다음 적재의 ``If-None-Match``)."""
    not_modified: bool = False
    """첫 페이지가 304였다 — ``rows``는 비었고 지금 세대가 그대로 맞다."""
    next_since: datetime | None = None
    """W3 publication watermark(모든 페이지가 같아야 한다). 다음 증분의 ``since``(ADR-122)."""
    membership_digest: str | None = None
    """W3 manifest 멤버십 digest(모든 페이지가 같아야 한다). 없으면 ``None``(ADR-122)."""
    clock_epoch: str | None = None
    """W3 publication clock epoch(모든 페이지가 같아야 한다). 없으면 ``None``(ADR-122)."""
    omitted_expired: list[Any] | None = None
    """W3 페이지들의 ``omitted_expired``를 이은 것(미래 시각이 없어 항목에서 뺀 멤버). weather가 그
    필드를 내지 않으면 ``None``(ADR-122)."""


async def _read_all_pages(
    settings: KorTravelMapSettings,
    path: str,
    params: Mapping[str, Any],
    parse: Callable[[Any], WeatherExportPage[_ItemT]],
    if_none_match: str | None = None,
) -> WeatherFetch:
    """cursor를 끝까지 따라간다.

    410(snapshot 만료)이나 둘째 페이지 이후의 422(순회 도중 weather 재배포)이면 첫 페이지부터
    **한 번** 다시 받는다. 첫 페이지 422는 질의 계약 위반이라 그대로 실패한다. 503은 그 페이지만
    다시 묻는다(:func:`_weather_get_page`).
    ``if_none_match``가 있으면 첫 페이지에 보내고, 304면 바로 ``not_modified``로 끝낸다.
    """
    base_url, headers = _weather_connection(settings)
    shared = upstream_retry.active_run_retry_budget()
    budget = shared if shared is not None else upstream_retry.RetryBudget()
    clock = _PageClock(_WEATHER_DEADLINE.get())
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=weather_http_timeout(settings),
        headers=headers,
    ) as client:
        for restart in range(2):
            try:
                return await _walk_pages(
                    client, path, params, parse, budget=budget, clock=clock,
                    if_none_match=if_none_match,
                )
            except (WeatherExportSnapshotExpired, _MidWalkCursorRejected) as exc:
                if restart:
                    if isinstance(exc, _MidWalkCursorRejected):
                        raise WeatherExportContractError(
                            f"{path}: 처음부터 다시 받아도 순회 도중 422다."
                        ) from exc
                    raise
                _LOGGER.warning(
                    "kor-travel-weather %s %s — 처음부터 다시 받는다.", path, exc.failure_kind
                )
    raise AssertionError("unreachable")  # pragma: no cover


class _MidWalkCursorRejected(WeatherExportFailure):
    """둘째 페이지 이후의 422 — :func:`_read_all_pages`가 한 번 재시작한다."""

    failure_kind = "weather_cursor_rejected_mid_walk"
    retryable = True


async def _walk_pages(
    client: httpx.AsyncClient,
    path: str,
    params: Mapping[str, Any],
    parse: Callable[[Any], WeatherExportPage[_ItemT]],
    *,
    budget: upstream_retry.RetryBudget,
    clock: _PageClock,
    if_none_match: str | None = None,
) -> WeatherFetch:
    rows: list[Any] = []
    collected: list[datetime | None] = []
    statuses: set[str] = set()
    snapshot_id: str | None = None
    next_since: datetime | None = None
    membership: str | None = None
    epoch: str | None = None
    omitted: list[Any] | None = None
    etag: str | None = None
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for page_number in range(1, _WEATHER_MAX_PAGES + 1):
        query = dict(params)
        if cursor is not None:
            query["cursor"] = cursor
        first = page_number == 1
        headers = {"If-None-Match": if_none_match} if first and if_none_match else None
        try:
            response = await _weather_get_page(
                client, path, query, budget=budget, clock=clock, headers=headers
            )
        except _WeatherCursorRejected as exc:
            if first:
                raise
            raise _MidWalkCursorRejected(f"{path}: 페이지 {page_number}에서 422다.") from exc
        if response.status_code == 304:
            if not (first and if_none_match):
                raise WeatherExportContractError(f"{path}: 조건 없는 요청에 304다.")
            return WeatherFetch(
                rows=[], source_collected_at=None, source_status="ok", pages=1,
                snapshot_id=None, etag=if_none_match, not_modified=True,
            )
        if first:
            etag = response.headers.get("etag")
        page = parse(_weather_json(response, path))
        if page_number == 1:
            snapshot_id = page.meta.snapshot_id
            next_since = page.meta.next_since
            membership = page.meta.membership_digest
            epoch = page.meta.clock_epoch
            omitted = None if page.meta.omitted_expired is None else []
        elif page.meta.snapshot_id != snapshot_id:
            raise WeatherExportContractError(
                f"{path}: 페이지 {page_number}의 snapshot_id가 첫 페이지와 다르다."
            )
        elif page.meta.next_since != next_since:
            # watermark는 snapshot manifest 하나의 값이다 — 페이지마다 다르면 cursor를 믿을 수 없다.
            raise WeatherExportContractError(
                f"{path}: 페이지 {page_number}의 next_since가 첫 페이지와 다르다."
            )
        elif (page.meta.membership_digest, page.meta.clock_epoch) != (membership, epoch):
            raise WeatherExportContractError(
                f"{path}: 페이지 {page_number}의 membership_digest·clock_epoch가 "
                "첫 페이지와 다르다."
            )
        if (page.meta.omitted_expired is None) != (omitted is None):
            raise WeatherExportContractError(
                f"{path}: 페이지 {page_number}의 omitted_expired 유무가 첫 페이지와 다르다."
            )
        if omitted is not None and page.meta.omitted_expired is not None:
            omitted.extend(page.meta.omitted_expired)
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
                etag=etag,
                next_since=next_since,
                membership_digest=membership,
                clock_epoch=epoch,
                omitted_expired=omitted,
            )
        next_cursor = page.meta.next_cursor
        assert next_cursor is not None  # 파서가 보장한다.
        if next_cursor in seen_cursors or next_cursor == cursor:
            raise WeatherExportContractError(f"{path}: next_cursor가 이미 지난 cursor다(순환).")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise WeatherExportContractError(f"{path}: {_WEATHER_MAX_PAGES}페이지를 넘었다.")


async def fetch_weather_locations(
    settings: KorTravelMapSettings, *, if_none_match: str | None = None
) -> WeatherFetch:
    """W1 위치 roster 전체."""
    return await _read_all_pages(
        settings,
        EXPORT_PATH_LOCATIONS,
        {"limit": settings.kor_travel_weather_page_size},
        parse_location_page,
        if_none_match,
    )


async def fetch_weather_current(
    settings: KorTravelMapSettings, *, if_none_match: str | None = None
) -> WeatherFetch:
    """W2 활성 관측 제공처 전체의 최신 관측."""
    return await _read_all_pages(
        settings,
        EXPORT_PATH_CURRENT,
        {"limit": settings.kor_travel_weather_page_size},
        parse_current_page,
        if_none_match,
    )


async def fetch_weather_forecasts(
    settings: KorTravelMapSettings,
    style: str,
    *,
    if_none_match: str | None = None,
    since: datetime | None = None,
) -> WeatherFetch:
    """W3 한 style의 예보 묶음. ``since``가 없으면 전량, 있으면 그 watermark 뒤에 공개된 승인
    scope의 묶음만이다(ADR-122). 페이지마다 같은 ``since``를 보낸다(cursor가 그 질의에 묶인다)."""
    params: dict[str, Any] = {"style": style, "limit": settings.kor_travel_weather_page_size}
    if since is not None:
        params["since"] = since.isoformat()
    return await _read_all_pages(
        settings,
        EXPORT_PATH_FORECASTS,
        params,
        lambda payload: parse_forecast_page(payload, style=style),
        if_none_match,
    )


async def fetch_weather_daily_summaries(
    settings: KorTravelMapSettings, *, if_none_match: str | None = None
) -> WeatherFetch:
    """W5 최근 ``weather_daily_summary_days``일 세 구간 요약 전체."""
    return await _read_all_pages(
        settings,
        EXPORT_PATH_DAILY_SUMMARIES,
        {
            "days": settings.weather_daily_summary_days,
            "limit": settings.kor_travel_weather_page_size,
        },
        parse_daily_summary_page,
        if_none_match,
    )


# -- 상태 항목 ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WeatherCollected:
    items: list[StateItem]
    row_duplicates: int
    """위치 안에서 같은 관측·묶음·(날짜, 구간)이 두 번 와서 버린 행 수(ADR-114 W1)."""
    fetch: WeatherFetch
    members: dict[tuple[str, str], datetime] | None = None
    """예보 전량의 멤버십 장부(ADR-122). 예보가 아니면 ``None``."""


Collector = Callable[[KorTravelMapSettings, str | None], Awaitable[WeatherCollected]]
"""``(settings, if_none_match)`` → 상태 항목. ``if_none_match``는 지금 세대의 원천 ETag다."""


async def _collect_locations(
    settings: KorTravelMapSettings, if_none_match: str | None
) -> WeatherCollected:
    fetch = await fetch_weather_locations(settings, if_none_match=if_none_match)
    rows: list[WeatherExportLocation] = fetch.rows
    return WeatherCollected(items=location_state_items(rows), row_duplicates=0, fetch=fetch)


async def _collect_current(
    settings: KorTravelMapSettings, if_none_match: str | None
) -> WeatherCollected:
    fetch = await fetch_weather_current(settings, if_none_match=if_none_match)
    grouper = CurrentGrouper()
    row: WeatherExportCurrentValue
    for row in fetch.rows:
        grouper.add(row)
    return WeatherCollected(grouper.items(), grouper.duplicates, fetch)


def _forecast_collector(dataset: WeatherStateDataset) -> Collector:
    style = dataset.style
    assert style is not None

    async def _collect(
        settings: KorTravelMapSettings, if_none_match: str | None
    ) -> WeatherCollected:
        fetch = await fetch_weather_forecasts(settings, style, if_none_match=if_none_match)
        grouper = ForecastGrouper(style=style)
        group: WeatherExportForecastGroup
        for group in fetch.rows:
            grouper.add(group)
        members = grouper.members()
        for member in fetch.omitted_expired or ():
            key = (member.location_id, member.provider)
            if key in members:
                raise WeatherExportContractError(
                    f"{EXPORT_PATH_FORECASTS}?style={style}: {key}가 항목과 "
                    "omitted_expired에 함께 왔다."
                )
            members[key] = member.published_at  # 값 없는 멤버(digest에는 있다)
        return WeatherCollected(grouper.items(), grouper.duplicates, fetch, members=members)

    return _collect


DeltaFetcher = Callable[[KorTravelMapSettings, datetime], Awaitable[WeatherFetch]]
"""``(settings, since)`` → 그 watermark 뒤의 예보 묶음(ADR-122)."""


def _forecast_delta_fetcher(dataset: WeatherStateDataset) -> DeltaFetcher:
    style = dataset.style
    assert style is not None

    async def _fetch(settings: KorTravelMapSettings, since: datetime) -> WeatherFetch:
        return await fetch_weather_forecasts(settings, style, since=since)

    return _fetch


async def _collect_daily_summaries(
    settings: KorTravelMapSettings, if_none_match: str | None
) -> WeatherCollected:
    fetch = await fetch_weather_daily_summaries(settings, if_none_match=if_none_match)
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
    delta: DeltaFetcher | None = None
    """있으면 ``since`` 증분을 지금 세대에 병합할 수 있다(W3 예보, ADR-122). ``collect``는 전량."""


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
        delta=_forecast_delta_fetcher(dataset) if dataset.style is not None else None,
    )


WEATHER_STATE_SPECS: Final[tuple[WeatherStateJobSpec, ...]] = (
    _spec(
        DATASET_LOCATIONS, "locations", "37 4 * * *", 900, _collect_locations,
        "weather 위치 roster(W1) → Valkey 세대 교체(매일).",
    ),
    _spec(
        DATASET_CURRENT, "current", "25,40 * * * *", 480, _collect_current,
        "weather 최신 관측·실황(W2) → Valkey 세대 교체(매시 :25·:40 — weather 공개 :20·:35 뒤).",
    ),
    _spec(
        DATASET_FORECAST_ULTRA_SHORT, "forecast_ultra_short", "48 * * * *", 600,
        _forecast_collector(DATASET_FORECAST_ULTRA_SHORT),
        "weather 초단기예보(W3 ultra_short) → Valkey 세대 교체(매시 :48).",
    ),
    # 단기·외부 상한은 증분이 아니라 **전량 재동기화**(첫 적재·하루 한 번·증분 거절 뒤)에 맞춘다.
    # odroid eMMC cold 전량은 단기 약 1,174초·외부 약 674초인데, 1,500·1,200초 상한에서 run이
    # 1,514·1,201초에 ReadTimeout으로 죽었다(2026-11-10). 증분 거절 뒤 같은 run의 전량까지 들게
    # 늘리되, lock TTL(상한 + 660초)은 3시간 발화 간격 안이다(ADR-122).
    _spec(
        DATASET_FORECAST_SHORT, "forecast_short", "30 2-23/3 * * *", 3_600,
        _forecast_collector(DATASET_FORECAST_SHORT),
        "weather 단기예보(W3 short) → Valkey 세대 교체(하루 8회, 발표 02·05…23시 뒤 :30).",
    ),
    _spec(
        DATASET_FORECAST_MID, "forecast_mid", "40 6,7,18,19 * * *", 900,
        _forecast_collector(DATASET_FORECAST_MID),
        "weather 중기예보(W3 mid) → Valkey 세대 교체(발표 06·18시 뒤, 한 시간 뒤 한 번 더).",
    ),
    _spec(
        DATASET_FORECAST_EXTERNAL, "forecast_external", "55 */3 * * *", 2_400,
        _forecast_collector(DATASET_FORECAST_EXTERNAL),
        "weather 외부 provider 예보(W3 external) → Valkey 세대 교체(3시간마다).",
    ),
    # W5는 14일 × 세 구간 × 위치(운영 약 6만 1천 건, 2,000건 페이지 약 31개)다. 포화된 odroid에서
    # 페이지당 약 27초라(2026-11-02 실측) 한 번 전량에 14분, 재시도까지 900초 상한을 넘겼다.
    # 매시 발화 간격(3,600초) 안에 lock TTL(상한 + 660초)이 들어가는 2,700초로 둔다.
    _spec(
        DATASET_DAILY_SUMMARIES, "daily_summaries", "41 * * * *", 2_700, _collect_daily_summaries,
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


async def _current_meta_or_none(store: ValkeyStateStore, dataset: str) -> GenerationMeta | None:
    """지금 세대 meta(원천 ETag용). 없으면 ``None`` — 깨진 저장소는 교체 단계가 실패시킨다."""
    try:
        return await store.current_meta(dataset)
    except StateNotLoaded:
        return None
    except StateStoreUnavailable:
        return None


_FULL_RESYNC_SLACK: Final[timedelta] = timedelta(minutes=15)
"""전량 주기 판정의 여유. 전량 시각은 run 시작 시각이라, 하루 뒤 같은 cron tick이 몇 초 일찍
시작해도 그 tick이 전량이 되게 한다(늦어지는 쪽으로 3시간씩 밀리지 않게)."""


@dataclass(frozen=True, slots=True)
class ForecastSyncPlan:
    """이번 예보 적재의 방식. ``since``가 있으면 증분, 없으면 전량이고 ``reason``이 그 이유다."""

    since: datetime | None
    reason: str


def forecast_sync_plan(
    current: GenerationMeta | None,
    *,
    now: datetime,
    full_resync_hours: float,
    allow_shrink: bool,
    full_resync: bool,
) -> ForecastSyncPlan:
    """증분을 쓸 수 있는가(ADR-122). 증분은 **전량에서 시작한 사슬**의 다음 고리일 때만이다."""
    if full_resync_hours <= 0:
        return ForecastSyncPlan(None, "delta_disabled")
    if allow_shrink:
        return ForecastSyncPlan(None, "allow_shrink")
    if full_resync:
        return ForecastSyncPlan(None, "requested")
    if current is None:
        return ForecastSyncPlan(None, "not_loaded")
    if (
        current.sync_cursor is None
        or current.full_synced_at is None
        or current.row_duplicates is None
        or current.member_count is None
    ):
        # 증분·멤버십 장부 이전 코드가 쓴 세대거나 meta가 덜 찼다.
        return ForecastSyncPlan(None, "no_cursor")
    if current.row_duplicates > 0:
        # 전량의 "같은 (위치, provider) 첫 행" 선택을 증분이 재현할 수 없다.
        return ForecastSyncPlan(None, "base_row_duplicates")
    due = current.full_synced_at + timedelta(hours=full_resync_hours) - _FULL_RESYNC_SLACK
    if now >= due or current.full_synced_at > now + _FULL_RESYNC_SLACK:
        # 미래의 전량 시각은 시계 이상이다 — 믿지 않고 전량으로 다시 시작한다.
        return ForecastSyncPlan(None, "periodic")
    return ForecastSyncPlan(current.sync_cursor, "delta")


class _FullResyncNeeded(Exception):
    """증분을 이번 run에서 믿을 수 없다 — 같은 run에서 전량으로 다시 받는다."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class _DeltaUnavailable(Exception):
    """증분 요청이 503(재시도 소진)이다 — 지금 세대가 weather 전량 fallback 이상이라 그대로 둔다."""


@dataclass(frozen=True, slots=True)
class _DeltaReady:
    fetch: WeatherFetch
    merge: ForecastMerge
    since: datetime
    next_since: datetime
    membership_verified: bool | None
    clock_epoch: str | None


async def _prepare_forecast_delta(
    spec: WeatherStateJobSpec,
    store: ValkeyStateStore,
    current: GenerationMeta,
    since: datetime,
    settings: KorTravelMapSettings,
) -> _DeltaReady:
    """증분을 받아 지금 세대에 병합한다(아직 쓰지 않는다).

    믿을 수 없으면 :class:`_FullResyncNeeded`, 503이면 :class:`_DeltaUnavailable`.
    """
    assert spec.delta is not None
    assert spec.dataset.style is not None
    try:
        fetch = await spec.delta(settings, since)
    except WeatherExportNotReady as exc:
        # weather는 얼리지 못하면 같은 선택(since 포함)의 직전 snapshot을 낸다.
        # 새 since에는 그것이 없어 503이다. 전량이었다면 직전 전량 snapshot
        # (이미 병합한 것 이하)을 받았을 것이라 바꿀 것이 없다. 세대·cursor를
        # 그대로 두고 run은 성공한다(다음 tick이 같은 since로 다시 묻는다).
        raise _DeltaUnavailable(str(exc)) from exc
    except _WeatherCursorRejected as exc:
        # 첫 페이지 422 — weather가 이 watermark를 발급한 적이 없거나
        # (DB 복원·재설치) 질의가 틀렸다.
        raise _FullResyncNeeded("cursor_rejected", str(exc)) from exc
    if fetch.next_since is None:
        raise _FullResyncNeeded("no_next_since", "증분 응답에 next_since가 없다.")
    if fetch.next_since < since:
        raise _FullResyncNeeded(
            "cursor_regressed",
            f"next_since {fetch.next_since.isoformat()}가 since {since.isoformat()}보다 이르다.",
        )
    if fetch.clock_epoch is not None and fetch.clock_epoch != current.clock_epoch:
        # weather DB가 복원·재설치·재시작됐다(또는 이 사슬이 epoch를 모른다) — 벽시계 clock이라
        # 복원 뒤 공개가 cursor를 곧바로 넘어서 422로는 드러나지 않는다(ADR-122 원천 계약 7).
        raise _FullResyncNeeded(
            "clock_epoch_changed",
            f"clock_epoch {current.clock_epoch!r} → {fetch.clock_epoch!r}.",
        )
    raw = await store.generation_items(spec.dataset.name, current.generation)
    if len(raw) != current.count:
        # 기준 세대가 meta와 다르다(부분 유실·grace 만료 중 읽기) — 병합하면 빠진 위치가 사라진다.
        raise _FullResyncNeeded(
            "base_count_mismatch",
            f"기준 세대 {current.generation} 값 {len(raw)}건 ≠ meta {current.count}건.",
        )
    try:
        base = [WeatherForecastState.model_validate_json(value) for value in raw.values()]
    except ValidationError as exc:
        raise _FullResyncNeeded("base_unreadable", "기준 세대 값이 모델과 맞지 않는다.") from exc
    base_members = await store.generation_members(spec.dataset.name, current.generation)
    if len(base_members) != current.member_count:
        raise _FullResyncNeeded(
            "base_count_mismatch",
            f"기준 세대 {current.generation} 멤버십 {len(base_members)}건 ≠ meta "
            f"{current.member_count}건.",
        )
    try:
        merge = merge_forecast_delta(
            base,
            fetch.rows,
            style=spec.dataset.style,
            since=since,
            now=datetime.now(UTC),
            base_members=base_members,
            omitted=fetch.omitted_expired or (),
        )
    except ForecastDeltaRefused as exc:
        raise _FullResyncNeeded(exc.reason, str(exc)) from exc
    verified: bool | None = None
    if fetch.membership_digest is not None:
        verified = forecast_membership_digest(merge.members) == fetch.membership_digest
        if not verified and current.membership_verified is not False:
            # 검증된(또는 검증해 본 적 없는) 사슬에서 다르다 — weather manifest에서 빠지거나 바뀐
            # 것을 증분이 놓쳤다(만료·비활성화·provider 퇴역·미래 시각 없는 재공개).
            raise _FullResyncNeeded(
                "membership_mismatch",
                "병합 멤버십 digest가 weather membership_digest와 다르다.",
            )
    return _DeltaReady(
        fetch=fetch,
        merge=merge,
        since=since,
        next_since=fetch.next_since,
        membership_verified=verified,
        clock_epoch=fetch.clock_epoch or current.clock_epoch,
    )


async def _swap_forecast_delta(
    spec: WeatherStateJobSpec,
    store: ValkeyStateStore,
    current: GenerationMeta,
    ready: _DeltaReady,
    *,
    run_id: str | None,
    upstream: Any,
) -> dict[str, Any]:
    """병합한 세대를 **읽은 기준 세대가 아직 current일 때만** 올린다(ADR-122)."""
    result = await store.swap(
        spec.dataset.name,
        ready.merge.items,
        guard=spec.dataset.guard,
        source_collected_at=ready.fetch.source_collected_at,
        loaded_at=datetime.now(UTC),
        run_id=run_id,
        allow_shrink=False,
        source_status=ready.fetch.source_status,
        source_etag=None,
        apply_guard=False,
        require_base=current.generation,
        sync_mode="delta",
        sync_cursor=ready.next_since,
        full_synced_at=current.full_synced_at,
        row_duplicates=0,
        members=ready.merge.members,
        membership_verified=ready.membership_verified,
        clock_epoch=ready.clock_epoch,
    )
    try:
        retired = await store.retire_other_versions(spec.dataset.name)
    except StateStoreError:
        retired = -1
    merge = ready.merge
    _LOGGER.info(
        "weather %s 증분: since=%s next_since=%s 묶음 %d(교체 %d·추가 %d) 이어 옴 %d(잘림 %d) "
        "만료 %d → %d곳",
        spec.dataset.name, ready.since.isoformat(), ready.next_since.isoformat(),
        merge.delta_rows, merge.replaced, merge.added, merge.carried, merge.trimmed,
        merge.expired, result.meta.count,
    )
    metadata: dict[str, Any] = {
        "dataset": spec.dataset.name,
        "sync_mode": "delta",
        "resync_reason": "",
        "generation": result.meta.generation,
        "previous_generation": result.previous_generation or "",
        "count": result.meta.count,
        "since": ready.since.isoformat(),
        "next_since": ready.next_since.isoformat(),
        "full_synced_at": (
            current.full_synced_at.isoformat() if current.full_synced_at is not None else ""
        ),
        "delta_rows": merge.delta_rows,
        "delta_replaced": merge.replaced,
        "delta_added": merge.added,
        "carried": merge.carried,
        "trimmed_groups": merge.trimmed,
        "expired_groups": merge.expired,
        "pages": ready.fetch.pages,
        "source_collected_at": (
            result.meta.source_collected_at.isoformat()
            if result.meta.source_collected_at is not None
            else ""
        ),
        "source_status": ready.fetch.source_status,
        "retired_other_version_keys": retired,
        "membership_verified": _verified_text(ready.membership_verified),
        "member_count": len(merge.members),
        "clock_epoch": ready.clock_epoch or "",
    }
    if upstream is not None:
        metadata[UPSTREAM_REQUESTS_METADATA_KEY] = upstream
    return metadata


def _verified_text(value: bool | None) -> str:
    return "" if value is None else "1" if value else "0"


async def load_weather_state(
    spec: WeatherStateJobSpec,
    *,
    settings: KorTravelMapSettings,
    run_id: str | None,
    allow_shrink: bool,
    store: ValkeyStateStore | None = None,
    deadline: float | None = None,
    full_resync: bool = False,
) -> dict[str, Any]:
    """한 데이터셋을 받아 Valkey 세대를 교체한다. 반환값은 op metadata다.

    ``store``를 넘기지 않으면 settings로 client를 만들고 끝나면 닫는다. ``deadline``
    (monotonic)을 넘기면 그 뒤로는 503 페이지 재시도를 시작하지 않는다(:func:`_run_deadline`).
    예보(``spec.delta``)는 :func:`forecast_sync_plan`이 증분을 고르면 증분을 병합하고, 그 증분을
    믿을 수 없으면 같은 run에서 전량으로 다시 받는다(ADR-122). ``full_resync``는 운영자 요청이다.
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
            current = await _current_meta_or_none(active, spec.dataset.name)
            started = datetime.now(UTC)
            plan: ForecastSyncPlan | None = None
            if spec.delta is not None:
                plan = forecast_sync_plan(
                    current,
                    now=started,
                    full_resync_hours=settings.weather_forecast_full_resync_hours,
                    allow_shrink=allow_shrink,
                    full_resync=full_resync,
                )
            resync_reason = plan.reason if plan is not None else ""
            # 예보 전량은 If-None-Match를 보내지 않는다 — 304는 cursor·전량 시각을
            # 다시 잡지 못해, 증분을 거절한 뒤의 전량이 304로 끝나면 run마다
            # 거절 → 304가 되풀이된다(ADR-122 리뷰).
            etag = (
                current.source_etag
                if current is not None and not allow_shrink and spec.delta is None
                else None
            )
            with (
                counting_upstream_requests(),
                sharing_run_retry_budget(),
                _paging_deadline(deadline),
            ):
                ready: _DeltaReady | None = None
                if plan is not None and plan.since is not None and current is not None:
                    try:
                        ready = await _prepare_forecast_delta(
                            spec, active, current, plan.since, settings
                        )
                    except _DeltaUnavailable as exc:
                        _LOGGER.warning(
                            "weather %s 증분이 503이다 — 세대·cursor를 그대로 둔다: %s",
                            spec.dataset.name, exc,
                        )
                        unavailable: dict[str, Any] = {
                            "dataset": spec.dataset.name,
                            "unchanged": "delta_unavailable",
                            "sync_mode": "delta",
                            "generation": current.generation,
                            "since": plan.since.isoformat(),
                        }
                        observed = observed_upstream_requests()
                        if observed is not None:
                            unavailable[UPSTREAM_REQUESTS_METADATA_KEY] = observed
                        return unavailable
                    except _FullResyncNeeded as exc:
                        resync_reason = exc.reason
                        _LOGGER.warning(
                            "weather %s 증분을 버리고 전량으로 다시 받는다(%s): %s",
                            spec.dataset.name, exc.reason, exc,
                        )
                    except Exception as exc:
                        _raise_terminal_if_weather_unrecoverable(exc)
                        raise
                if ready is not None:
                    upstream = observed_upstream_requests()
                    assert current is not None
                    return await _swap_forecast_delta(
                        spec, active, current, ready, run_id=run_id, upstream=upstream
                    )
                try:
                    collected = await spec.collect(settings, etag)
                except Exception as exc:
                    _raise_terminal_if_weather_unrecoverable(exc)
                    raise
                upstream = observed_upstream_requests()
            if collected.fetch.not_modified:
                assert current is not None
                touched = await active.touch_checked(
                    spec.dataset.name, current.generation, datetime.now(UTC)
                )
                unchanged: dict[str, Any] = {
                    "dataset": spec.dataset.name,
                    "unchanged": "not_modified",
                    "generation": current.generation,
                    "checked": touched,
                }
                if upstream is not None:
                    unchanged[UPSTREAM_REQUESTS_METADATA_KEY] = upstream
                return unchanged
            forecast = spec.delta is not None
            # 전량 장부가 weather digest와 다르면 manifest에 Map이 받지 못한 행(미래 시각이 없는
            # 묶음)이 있다 — 이 사슬은 digest로 검증할 수 없다(ADR-122).
            full_verified: bool | None = None
            if forecast and collected.fetch.membership_digest is not None:
                full_verified = (
                    forecast_membership_digest(collected.members or {})
                    == collected.fetch.membership_digest
                )
                # "검증할 수 없다"(False)는 weather가 시간 필터로 뺀 행을 알리지 않고
                # (omitted_expired 없음) 실제로 뺐을 때(stale 페이지)만이다. 그 밖의 불일치는
                # 정의·계약 어긋남이라 False로 두면 검사가 조용히 꺼진다 — 모름(None)으로
                # 두어 다음 증분이 다시 전량을 받게 하고 오류로 남긴다(ADR-122 리뷰 M1).
                if not full_verified and (
                    collected.fetch.omitted_expired is not None
                    or collected.fetch.source_status != "stale"
                ):
                    _LOGGER.error(
                        "weather %s 전량 멤버십 digest가 weather와 다르다(omitted_expired=%s, "
                        "source_status=%s) — 정의·계약 어긋남 의심.",
                        spec.dataset.name,
                        collected.fetch.omitted_expired is not None,
                        collected.fetch.source_status,
                    )
                    full_verified = None
            result = await active.swap(
                spec.dataset.name,
                collected.items,
                guard=spec.dataset.guard,
                source_collected_at=collected.fetch.source_collected_at,
                loaded_at=datetime.now(UTC),
                run_id=run_id,
                allow_shrink=allow_shrink,
                source_status=collected.fetch.source_status,
                source_etag=collected.fetch.etag,
                apply_guard=True,  # 전량은 언제나 거부 기준(D4)을 받는다
                require_base=None,
                # 예보 전량은 증분 사슬의 시작이다 — cursor와 전량 시각(run 시작)을
                # 세대와 함께 둔다.
                sync_mode="full" if forecast else None,
                sync_cursor=collected.fetch.next_since if forecast else None,
                full_synced_at=started if forecast else None,
                row_duplicates=collected.row_duplicates if forecast else None,
                members=collected.members,
                membership_verified=full_verified,
                clock_epoch=collected.fetch.clock_epoch,
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
        if forecast:
            metadata["sync_mode"] = "full"
            metadata["resync_reason"] = resync_reason
            metadata["next_since"] = (
                collected.fetch.next_since.isoformat()
                if collected.fetch.next_since is not None
                else ""
            )
            metadata["full_synced_at"] = started.isoformat()
            metadata["membership_verified"] = _verified_text(full_verified)
            metadata["member_count"] = len(collected.members or {})
            metadata["clock_epoch"] = collected.fetch.clock_epoch or ""
            _LOGGER.info(
                "weather %s 전량(%s): %d곳, next_since=%s",
                spec.dataset.name, resync_reason, result.meta.count, metadata["next_since"],
            )
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
    "full_resync": Field(
        bool,
        default_value=False,
        is_required=False,
        description=(
            "true면 예보(W3) 증분 대신 이번 한 번 전량을 받는다(ADR-122). 거부 기준은 그대로 건다. "
            "예보가 아닌 데이터셋은 언제나 전량이라 영향이 없다."
        ),
    ),
}


def _run_deadline(context: OpExecutionContext, spec: WeatherStateJobSpec) -> float:
    """run 상한(``dagster/max_runtime``)에서 꼬리를 뺀 monotonic 시각.

    run monitor는 step이 아니라 **run** 시작부터 센다 — step 재시도가 이미 쓴 시간도 뺀다
    (``mois_chunked_load._run_clock_start``와 같은 규칙). 상한은 run의 실제 tag(없으면 spec)다.
    run 시작을 모르면(조회 실패 포함) 지금부터 센다.
    """
    now = time.time()
    cap = spec.max_runtime_seconds
    with contextlib.suppress(AttributeError, TypeError, ValueError):
        cap = int(context.run.tags.get(MAX_RUNTIME_SECONDS_TAG, cap))
    try:
        record = context.instance.get_run_record_by_id(context.run_id)
    except Exception:  # noqa: BLE001 — 시작 시각을 모르면 지금부터 센다(적재를 막지 않는다)
        record = None
    start_time = getattr(record, "start_time", None)
    elapsed = 0.0
    if (
        isinstance(start_time, int | float)
        and not isinstance(start_time, bool)
        and math.isfinite(start_time)
        and 0 < start_time <= now
    ):
        elapsed = now - float(start_time)
    return time.monotonic() + cap - _WEATHER_RUN_TAIL_SECONDS - elapsed


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
            deadline=_run_deadline(context, spec),
            full_resync=bool(context.op_config.get("full_resync", False)),
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
