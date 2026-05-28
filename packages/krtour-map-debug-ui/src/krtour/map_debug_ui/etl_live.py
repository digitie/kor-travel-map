"""``krtour.map_debug_ui.etl_live`` — `?source=live` provider 실 호출.

`etl_fixtures.py`가 hard-coded sample을 변환하는 dry-run이라면, 본 모듈은
실제 provider 공공 API를 httpx로 호출 → response를 본 lib `providers/*`
Protocol 만족 dataclass로 adapter → 본 lib 변환 함수 → JSON 결과 응답.

ADR-006 정합 메모
--------
- 본 모듈은 **디버그 UI 측에 한정** — 메인 lib(`krtour.map`)는 여전히 provider
  wrapper 없음 (Protocol 통과만).
- `python-*-api` provider 라이브러리들이 install되어 있지 않아도 본 모듈은
  동작 — httpx 직접 호출. 단점: provider 라이브러리의 typed model을 못 쓰니
  raw dict → dataclass adapter 필요.

라우터 사용
-----------
``routers/etl.py``의 `?source=live` 분기에서 ``LIVE_LOADER_REGISTRY``의
``(provider, dataset)`` 매핑을 lookup → ``LiveLoader`` async 호출.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final

import httpx
from krtour.map.providers.kma import (
    short_forecast_to_weather_values,
    ultra_short_forecast_to_weather_values,
    ultra_short_nowcast_to_weather_values,
)

from krtour.map_debug_ui.settings import DebugUiSettings

__all__ = [
    "LiveLoader",
    "LiveLoaderError",
    "LIVE_LOADER_REGISTRY",
    "find_live_loader",
]


KST = timezone(timedelta(hours=9))

# 디폴트 좌표: 서울 격자 (60, 127) — 호출자가 query 파라미터로 다른 격자 지정 가능.
_DEFAULT_NX: Final[int] = 60
_DEFAULT_NY: Final[int] = 127

# 디폴트 feature_id (가짜) — 실 적재 X. 본 lib 변환 함수가 요구하므로 placeholder.
_DEFAULT_WEATHER_FEATURE_ID: Final[str] = "f_global_w_live_demo"

_KMA_BASE_URL: Final[str] = (
    "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
)
"""기상청 공공데이터포털 동네예보 API base URL."""


class LiveLoaderError(Exception):
    """live loader 실행 중 외부 호출 실패. router가 502/503으로 매핑."""


# ── LiveLoader type ──────────────────────────────────────────────────


LiveLoader = Callable[
    [DebugUiSettings, dict[str, str]],
    Awaitable[list[Any]],
]
"""``async def(settings, params) -> list[dict]`` — 응답 dict의 list."""


# ── KMA: 단기예보 (getVilageFcst) ─────────────────────────────────────


@dataclass(frozen=True)
class _KmaShortAdapter:
    """`KmaShortForecastItem` Protocol 만족 — raw JSON item → snake_case."""

    base_date: str
    base_time: str
    fcst_date: str
    fcst_time: str
    nx: int
    ny: int
    category: str
    fcst_value: str


def _kma_now_base() -> tuple[str, str]:
    """단기예보 발표 시각 — 02/05/08/11/14/17/20/23시 중 가장 가까운 과거."""
    now = datetime.now(tz=KST)
    # 단기예보 발표는 매일 8회 (HH=02,05,08,11,14,17,20,23). 발표 + 10분 후 호출 가능.
    base_hours = [23, 20, 17, 14, 11, 8, 5, 2]
    for hour in base_hours:
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= now - timedelta(minutes=10):
            return candidate.strftime("%Y%m%d"), candidate.strftime("%H00")
    # 자정 직후 fallback: 어제 23시.
    yesterday = now - timedelta(days=1)
    candidate = yesterday.replace(hour=23, minute=0, second=0, microsecond=0)
    return candidate.strftime("%Y%m%d"), candidate.strftime("%H00")


async def _kma_call(
    endpoint: str,
    *,
    service_key: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """KMA API GET → response.body.items.item list 반환."""
    query: dict[str, Any] = {
        "serviceKey": service_key,
        "dataType": "JSON",
        "numOfRows": 1000,
        "pageNo": 1,
        **params,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{_KMA_BASE_URL}/{endpoint}", params=query)
    if response.status_code != 200:
        raise LiveLoaderError(
            f"KMA {endpoint} HTTP {response.status_code}: {response.text[:200]}"
        )
    payload = response.json()
    body = payload.get("response", {}).get("body", {})
    items_wrap = body.get("items", {})
    if isinstance(items_wrap, dict):
        raw_items = items_wrap.get("item", [])
    elif isinstance(items_wrap, list):
        raw_items = items_wrap
    else:
        raw_items = []
    if not isinstance(raw_items, list):
        raise LiveLoaderError(
            f"KMA {endpoint} unexpected items shape: {type(raw_items).__name__}"
        )
    return [item for item in raw_items if isinstance(item, dict)]


def _adapt_kma_short(item: dict[str, Any]) -> _KmaShortAdapter:
    return _KmaShortAdapter(
        base_date=str(item.get("baseDate", "")),
        base_time=str(item.get("baseTime", "")),
        fcst_date=str(item.get("fcstDate", "")),
        fcst_time=str(item.get("fcstTime", "")),
        nx=int(item.get("nx", 0)),
        ny=int(item.get("ny", 0)),
        category=str(item.get("category", "")),
        fcst_value=str(item.get("fcstValue", "")),
    )


async def kma_short_forecast_live(
    settings: DebugUiSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """KMA 단기예보 raw API → list[WeatherValue dict]."""
    key = settings.kma_service_key
    if key is None:
        raise LiveLoaderError("KMA_SERVICE_KEY 미설정 (.env 확인).")
    base_date, base_time = _kma_now_base()
    raw_items = await _kma_call(
        "getVilageFcst",
        service_key=key.get_secret_value(),
        params={
            "base_date": params.get("base_date", base_date),
            "base_time": params.get("base_time", base_time),
            "nx": int(params.get("nx", _DEFAULT_NX)),
            "ny": int(params.get("ny", _DEFAULT_NY)),
        },
    )
    adapted_short = [_adapt_kma_short(item) for item in raw_items]
    # `_KmaShortAdapter` dataclass는 Protocol 만족하나 mypy strict는 명목적 매칭만.
    values_short = short_forecast_to_weather_values(
        adapted_short,  # type: ignore[arg-type]
        feature_id=params.get("feature_id", _DEFAULT_WEATHER_FEATURE_ID),
    )
    return [v.model_dump(mode="json") for v in values_short]


# ── KMA: 초단기실황 (getUltraSrtNcst) ─────────────────────────────────


@dataclass(frozen=True)
class _KmaNowcastAdapter:
    """`KmaUltraShortNowcastItem` Protocol 만족."""

    base_date: str
    base_time: str
    nx: int
    ny: int
    category: str
    obsr_value: str


def _kma_ncst_base() -> tuple[str, str]:
    """초단기실황은 매시 40분 이후 그 시각의 base 사용 가능."""
    now = datetime.now(tz=KST)
    if now.minute < 40:
        # 이전 시각 사용.
        base = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    else:
        base = now.replace(minute=0, second=0, microsecond=0)
    return base.strftime("%Y%m%d"), base.strftime("%H00")


def _adapt_kma_nowcast(item: dict[str, Any]) -> _KmaNowcastAdapter:
    return _KmaNowcastAdapter(
        base_date=str(item.get("baseDate", "")),
        base_time=str(item.get("baseTime", "")),
        nx=int(item.get("nx", 0)),
        ny=int(item.get("ny", 0)),
        category=str(item.get("category", "")),
        obsr_value=str(item.get("obsrValue", "")),
    )


async def kma_ultra_short_nowcast_live(
    settings: DebugUiSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """KMA 초단기실황 raw API → list[WeatherValue dict]."""
    key = settings.kma_service_key
    if key is None:
        raise LiveLoaderError("KMA_SERVICE_KEY 미설정 (.env 확인).")
    base_date, base_time = _kma_ncst_base()
    raw_items = await _kma_call(
        "getUltraSrtNcst",
        service_key=key.get_secret_value(),
        params={
            "base_date": params.get("base_date", base_date),
            "base_time": params.get("base_time", base_time),
            "nx": int(params.get("nx", _DEFAULT_NX)),
            "ny": int(params.get("ny", _DEFAULT_NY)),
        },
    )
    adapted_now = [_adapt_kma_nowcast(item) for item in raw_items]
    # Protocol structural check는 OK이지만 mypy strict는 명목적 type 매칭만
    # 인정 — 같은 attribute set이라도 다른 Protocol이라 별 어노테이션 필요.
    values_n = ultra_short_nowcast_to_weather_values(
        adapted_now,  # type: ignore[arg-type]
        feature_id=params.get("feature_id", _DEFAULT_WEATHER_FEATURE_ID),
    )
    return [v.model_dump(mode="json") for v in values_n]


# ── KMA: 초단기예보 (getUltraSrtFcst) ─────────────────────────────────


def _kma_usf_base() -> tuple[str, str]:
    """초단기예보는 매시 45분 이후 그 시각의 base 사용 가능 (30분 단위)."""
    now = datetime.now(tz=KST)
    if now.minute < 45:
        base = now.replace(minute=30, second=0, microsecond=0) - timedelta(hours=1)
    else:
        base = now.replace(minute=30, second=0, microsecond=0)
    return base.strftime("%Y%m%d"), base.strftime("%H%M")


async def kma_ultra_short_forecast_live(
    settings: DebugUiSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """KMA 초단기예보 raw API → list[WeatherValue dict]. 응답 shape은 단기예보와
    동일하므로 `_KmaShortAdapter`/`_adapt_kma_short` 재사용."""
    key = settings.kma_service_key
    if key is None:
        raise LiveLoaderError("KMA_SERVICE_KEY 미설정 (.env 확인).")
    base_date, base_time = _kma_usf_base()
    raw_items = await _kma_call(
        "getUltraSrtFcst",
        service_key=key.get_secret_value(),
        params={
            "base_date": params.get("base_date", base_date),
            "base_time": params.get("base_time", base_time),
            "nx": int(params.get("nx", _DEFAULT_NX)),
            "ny": int(params.get("ny", _DEFAULT_NY)),
        },
    )
    adapted_uf = [_adapt_kma_short(item) for item in raw_items]
    # 단기예보와 초단기예보는 응답 shape 동일하나 mypy Protocol은 명목적 매칭만.
    values_uf = ultra_short_forecast_to_weather_values(
        adapted_uf,  # type: ignore[arg-type]
        feature_id=params.get("feature_id", _DEFAULT_WEATHER_FEATURE_ID),
    )
    return [v.model_dump(mode="json") for v in values_uf]


# ── Registry ──────────────────────────────────────────────────────────


LIVE_LOADER_REGISTRY: Final[dict[tuple[str, str], LiveLoader]] = {
    ("python-kma-api", "kma_short_forecast"): kma_short_forecast_live,
    ("python-kma-api", "kma_ultra_short_nowcast"): kma_ultra_short_nowcast_live,
    ("python-kma-api", "kma_ultra_short_forecast"): kma_ultra_short_forecast_live,
    # `kma_weather_alerts` — 다른 endpoint (특보 API). 후속 PR.
    # `data.go.kr-standard` datagokr_cultural_festivals — 후속 PR.
    # `python-opinet-api` station/prices — 후속 PR.
    # `python-krex-api` 4 dataset — 후속 PR.
}


def find_live_loader(provider: str, dataset: str) -> LiveLoader | None:
    """``(provider, dataset)`` → ``LiveLoader`` 또는 ``None`` (등록 안 됨)."""
    return LIVE_LOADER_REGISTRY.get((provider, dataset))


# date / 사용 안 함 경고 silencer (향후 datagokr/opinet loader에서 date 활용).
_ = date
