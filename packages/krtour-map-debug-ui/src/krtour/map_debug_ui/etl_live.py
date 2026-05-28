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
from decimal import Decimal
from typing import Any, Final

import httpx
from krtour.map.providers.kma import (
    short_forecast_to_weather_values,
    ultra_short_forecast_to_weather_values,
    ultra_short_nowcast_to_weather_values,
)
from krtour.map.providers.krex import (
    rest_area_prices_to_values,
    rest_area_weather_to_values,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from krtour.map.providers.opinet import prices_to_values, stations_to_bundles

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


# =========================================================================
# 한국도로공사 (krex) — EX OpenAPI (data.ex.co.kr). 휴게소 place + 가격 + 날씨
# + 교통 공지 4 dataset. provider 라이브러리 `python-krex-api` client의 raw
# REST 스펙(엔드포인트/param/응답 필드)을 PR#55에서 조사해 반영.
#
# EX 공통: GET, query에 `key`(서비스키) + `type=json`. 응답 list는
# `payload["list"]` (fallback List/data/items). adapter는 순수 함수라
# `tests/unit/test_etl_live_krex_adapters.py`로 단위 검증 (async fetch는 key
# 필요해 CI 미검증).
# =========================================================================

_KREX_EX_BASE_URL: Final[str] = "https://data.ex.co.kr"
"""한국도로공사 공공데이터포털(EX) OpenAPI base URL."""

# 휴게소 가격/날씨 변환은 rest area `feature_id`가 필요 — debug placeholder.
_DEFAULT_REST_AREA_FEATURE_ID: Final[str] = "f_global_p_live_demo"

_KREX_WEATHER_SENTINEL: Final[float] = -99.0
"""EX 휴게소 날씨 결측 sentinel — 해당 metric drop."""

# EX 휴게소 날씨 wide → long melt: raw 필드 → (metric_key, unit).
_KREX_WEATHER_METRICS: Final[tuple[tuple[str, str, str], ...]] = (
    ("tempValue", "T1H", "deg_c"),
    ("humidityValue", "REH", "%"),
    ("windValue", "WSD", "m/s"),
    ("rainfallValue", "RN1", "mm"),
)

# EX 돌발(incident) type 코드/한글 → 본 lib 표준 notice_type (NOTICE_TYPES).
# EX incidentType: 1=사고 / 2=공사 / 3=기상 / 4=기타.
_KREX_INCIDENT_TYPE_MAP: Final[dict[str, str]] = {
    "1": "traffic_accident",
    "사고": "traffic_accident",
    "교통사고": "traffic_accident",
    "2": "roadwork",
    "공사": "roadwork",
    "3": "weather_alert",
    "기상": "weather_alert",
    "4": "traffic",
    "기타": "traffic",
}


@dataclass(frozen=True)
class _KrexRestAreaAdapter:
    """`KrexRestAreaItem` Protocol 만족. serviceAreaRoute는 좌표 없음 → None."""

    uni_id: str
    name: str
    direction: str | None
    highway_name: str | None
    address: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    tel: str | None


@dataclass(frozen=True)
class _KrexPriceAdapter:
    """`KrexRestAreaPriceItem` Protocol 만족."""

    uni_id: str
    category: str
    product_key: str
    product_name: str | None
    price: Decimal
    observed_at: datetime


@dataclass(frozen=True)
class _KrexWeatherAdapter:
    """`KrexRestAreaWeatherItem` Protocol 만족."""

    uni_id: str
    metric_key: str
    value: Decimal
    observed_at: datetime
    unit: str | None


@dataclass(frozen=True)
class _KrexNoticeAdapter:
    """`KrexTrafficNoticeItem` Protocol 만족."""

    notice_id: str
    title: str
    notice_type: str
    description: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    valid_from: datetime | None
    valid_until: datetime | None
    severity: int | None
    source_agency: str | None


def _first_str(item: dict[str, Any], *keys: str) -> str | None:
    """raw dict에서 keys 순서대로 첫 non-empty 문자열 값. 없으면 None."""
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _krex_parse_dt(date_str: str | None, time_str: str | None) -> datetime | None:
    """EX 날짜(YYYYMMDD) + 시각(HHMM/HHMMSS) → KST aware datetime. 실패 시 None."""
    if not date_str or len(date_str) != 8 or not date_str.isdigit():
        return None
    hh, mm = 0, 0
    if time_str and time_str.isdigit() and len(time_str) >= 4:
        hh, mm = int(time_str[:2]), int(time_str[2:4])
    return datetime(
        int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]), hh, mm, tzinfo=KST
    )


async def _krex_call(
    endpoint: str, *, service_key: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """EX OpenAPI GET → 응답 list 반환 (`list`/`List`/`data`/`items` 중 첫 list)."""
    query: dict[str, Any] = {
        "key": service_key,
        "type": "json",
        "numOfRows": 100,
        "pageNo": 1,
        **params,
    }
    url = f"{_KREX_EX_BASE_URL}/{endpoint.lstrip('/')}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, params=query)
    if response.status_code != 200:
        raise LiveLoaderError(
            f"krex {endpoint} HTTP {response.status_code}: {response.text[:200]}"
        )
    payload = response.json()
    code = payload.get("code")
    if code is not None and str(code).upper() not in {"SUCCESS", "0", "200"}:
        raise LiveLoaderError(
            f"krex {endpoint} code={code}: {payload.get('message', '')[:200]}"
        )
    for key in ("list", "List", "data", "items", "item"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return []


def _adapt_krex_rest_area(raw: dict[str, Any]) -> _KrexRestAreaAdapter:
    return _KrexRestAreaAdapter(
        uni_id=_first_str(raw, "serviceAreaCode", "unitCode", "uni_id") or "",
        name=_first_str(raw, "serviceAreaName", "unitName", "name") or "",
        direction=_first_str(raw, "direction", "gffDivCd"),
        highway_name=_first_str(raw, "routeName", "highway_name"),
        address=_first_str(raw, "svarAddr", "addr", "address"),
        longitude=None,  # serviceAreaRoute 응답에 좌표 없음 (조사 결과).
        latitude=None,
        tel=_first_str(raw, "telNo", "phoneNumber", "tel"),
    )


def _adapt_krex_fuel_row(
    raw: dict[str, Any], *, observed_at: datetime
) -> list[_KrexPriceAdapter]:
    """주유 가격 wide row → 연료별 _KrexPriceAdapter (explode)."""
    uni_id = _first_str(raw, "serviceAreaCode", "unitCode", "uni_id") or ""
    out: list[_KrexPriceAdapter] = []
    for raw_key, product_key in (
        ("gasoline_price", "gasoline"),
        ("gasolinePrice", "gasoline"),
        ("diesel_price", "diesel"),
        ("dieselPrice", "diesel"),
        ("lpg_price", "lpg"),
        ("lpgPrice", "lpg"),
    ):
        value = raw.get(raw_key)
        if value is None or str(value).strip() in {"", "0"}:
            continue
        out.append(
            _KrexPriceAdapter(
                uni_id=uni_id,
                category="fuel",
                product_key=product_key,
                product_name=None,
                price=Decimal(str(value)),
                observed_at=observed_at,
            )
        )
    return out


def _adapt_krex_food_row(
    raw: dict[str, Any], *, observed_at: datetime
) -> _KrexPriceAdapter | None:
    price = raw.get("price") or raw.get("foodPrice")
    if price is None or str(price).strip() in {"", "0"}:
        return None
    return _KrexPriceAdapter(
        uni_id=_first_str(raw, "serviceAreaCode", "unitCode", "uni_id") or "",
        category="food",
        product_key=_first_str(raw, "foodCode", "menuCode") or "menu",
        product_name=_first_str(raw, "foodName", "menuName"),
        price=Decimal(str(price)),
        observed_at=observed_at,
    )


def _adapt_krex_weather_row(
    raw: dict[str, Any], *, observed_at: datetime
) -> list[_KrexWeatherAdapter]:
    """휴게소 날씨 wide row → metric별 _KrexWeatherAdapter (melt, -99 drop)."""
    uni_id = _first_str(raw, "unitCode", "serviceAreaCode", "uni_id") or ""
    out: list[_KrexWeatherAdapter] = []
    for raw_key, metric_key, unit in _KREX_WEATHER_METRICS:
        value = raw.get(raw_key)
        if value is None or str(value).strip() == "":
            continue
        try:
            num = Decimal(str(value))
        except (ValueError, ArithmeticError):
            continue
        if num == Decimal(str(_KREX_WEATHER_SENTINEL)):
            continue
        out.append(
            _KrexWeatherAdapter(
                uni_id=uni_id,
                metric_key=metric_key,
                value=num,
                observed_at=observed_at,
                unit=unit,
            )
        )
    return out


def _adapt_krex_notice(raw: dict[str, Any]) -> _KrexNoticeAdapter:
    raw_type = _first_str(raw, "incidentType", "eventType", "notice_type") or "4"
    # EX 코드/한글 → 표준 notice_type. 매핑 없으면 generic 'traffic'.
    notice_type = _KREX_INCIDENT_TYPE_MAP.get(raw_type, "traffic")
    message = _first_str(raw, "message", "contents", "incidentContent", "title") or ""
    notice_id = _first_str(raw, "incidentId", "eventId", "notice_id")
    if notice_id is None:
        # EX incident는 안정 id가 없을 수 있음 → 결정적 합성.
        notice_id = f"{notice_type}:{_first_str(raw, 'startDate') or ''}:{message[:40]}"
    return _KrexNoticeAdapter(
        notice_id=notice_id,
        title=message or notice_type,
        notice_type=notice_type,
        description=message or None,
        longitude=None,
        latitude=None,
        valid_from=_krex_parse_dt(raw.get("startDate"), raw.get("startTime")),
        valid_until=_krex_parse_dt(raw.get("endDate"), raw.get("endTime")),
        severity=None,
        source_agency="한국도로공사",
    )


def _krex_key(settings: DebugUiSettings) -> str:
    key = settings.krex_service_key
    if key is None:
        raise LiveLoaderError("KREX_SERVICE_KEY 미설정 (.env 확인).")
    return key.get_secret_value()


async def krex_rest_areas_live(
    settings: DebugUiSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """krex 휴게소 목록 raw API → list[FeatureBundle dict] (place)."""
    raw_items = await _krex_call(
        "openapi/business/serviceAreaRoute",
        service_key=_krex_key(settings),
        params={k: v for k, v in params.items() if k in {"routeName", "direction"}},
    )
    adapted = [_adapt_krex_rest_area(r) for r in raw_items]
    bundles = rest_areas_to_bundles(
        adapted,  # type: ignore[arg-type]
        fetched_at=datetime.now(tz=KST),
    )
    return [b.model_dump(mode="json") for b in bundles]


async def krex_rest_area_prices_live(
    settings: DebugUiSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """krex 휴게소 가격(주유 + 식음료) raw API → list[PriceValue dict]."""
    key = _krex_key(settings)
    observed_at = datetime.now(tz=KST)
    fuel_raw = await _krex_call(
        "openapi/business/curStateStation", service_key=key, params={}
    )
    food_raw = await _krex_call(
        "openapi/restinfo/restMenuList", service_key=key, params={}
    )
    adapted: list[_KrexPriceAdapter] = []
    for row in fuel_raw:
        adapted.extend(_adapt_krex_fuel_row(row, observed_at=observed_at))
    for row in food_raw:
        food = _adapt_krex_food_row(row, observed_at=observed_at)
        if food is not None:
            adapted.append(food)
    values = rest_area_prices_to_values(
        adapted,  # type: ignore[arg-type]
        feature_id=params.get("feature_id", _DEFAULT_REST_AREA_FEATURE_ID),
    )
    return [v.model_dump(mode="json") for v in values]


async def krex_rest_area_weather_live(
    settings: DebugUiSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """krex 휴게소 날씨 raw API → list[WeatherValue dict]. sdate/stdHour 기본 현재."""
    now = datetime.now(tz=KST)
    observed_at = now
    raw_items = await _krex_call(
        "openapi/restinfo/restWeatherList",
        service_key=_krex_key(settings),
        params={
            "sdate": params.get("sdate", now.strftime("%Y%m%d")),
            "stdHour": params.get("stdHour", now.strftime("%H")),
        },
    )
    adapted: list[_KrexWeatherAdapter] = []
    for row in raw_items:
        adapted.extend(_adapt_krex_weather_row(row, observed_at=observed_at))
    values = rest_area_weather_to_values(
        adapted,  # type: ignore[arg-type]
        feature_id=params.get("feature_id", _DEFAULT_REST_AREA_FEATURE_ID),
    )
    return [v.model_dump(mode="json") for v in values]


async def krex_traffic_notices_live(
    settings: DebugUiSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """krex 교통 공지/돌발 raw API → list[FeatureBundle dict] (notice)."""
    raw_items = await _krex_call(
        "openapi/trafficapi/incident",
        service_key=_krex_key(settings),
        params={k: v for k, v in params.items() if k in {"routeNo", "incidentType"}},
    )
    adapted = [_adapt_krex_notice(r) for r in raw_items]
    bundles = traffic_notices_to_bundles(
        adapted,  # type: ignore[arg-type]
        fetched_at=datetime.now(tz=KST),
    )
    return [b.model_dump(mode="json") for b in bundles]


# =========================================================================
# 한국석유공사 (opinet) — detailById.do 주유소 상세 + 중첩 가격. 좌표는 KATEC
# (오피넷 전용 TM, bessel) → WGS84 reproject. raw 스펙은 로컬 `python-opinet-
# api` client `_build_station_detail`/`_build_oil_price` 기준 (ADR-044).
#
# detailById.do는 station id(UNI_ID) 1건만 조회 — "전체 목록" endpoint 없음.
# 따라서 본 loader는 `?id=<UNI_ID>` query 파라미터 필수.
# =========================================================================

_OPINET_BASE_URL: Final[str] = "https://www.opinet.co.kr/api"
"""한국석유공사 OpiNet OpenAPI base URL."""

# 오피넷 KATEC proj4 (로컬 python-opinet-api `coords.py`에서 그대로 가져옴).
_OPINET_KATEC_PROJ: Final[str] = (
    "+proj=tmerc +lat_0=38 +lon_0=128 +k=0.9999 +x_0=400000 +y_0=600000 "
    "+ellps=bessel +units=m "
    "+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43 +no_defs"
)

# 가격 변환은 주유소 feature_id 필요 — debug placeholder.
_DEFAULT_STATION_FEATURE_ID: Final[str] = "f_global_p_opinet_demo"


@dataclass(frozen=True)
class _OpinetStationAdapter:
    """`OpinetStationItem` Protocol 만족."""

    uni_id: str
    station_name: str
    brand_code: str | None
    address: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    tel: str | None
    lpg_yn: str | None


@dataclass(frozen=True)
class _OpinetPriceAdapter:
    """`OpinetPriceItem` Protocol 만족."""

    uni_id: str
    prodcd: str
    price: Decimal
    trade_dt: datetime


def _opinet_katec_to_wgs84(x: float, y: float) -> tuple[Decimal, Decimal] | None:
    """KATEC (x, y) → WGS84 (lon, lat) Decimal. 변환 실패/범위 밖이면 None."""
    from pyproj import Transformer  # krtour.map 의존으로 설치됨 (infra/crs.py).

    try:
        transformer = Transformer.from_crs(
            _OPINET_KATEC_PROJ, "EPSG:4326", always_xy=True
        )
        lon, lat = transformer.transform(x, y)
    except Exception:  # noqa: BLE001 — 좌표 변환 실패는 좌표 없음으로 강등.
        return None
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        return None
    return (Decimal(str(round(lon, 7))), Decimal(str(round(lat, 7))))


def _opinet_parse_trade_dt(date_str: str | None, time_str: str | None) -> datetime:
    """OpiNet TRADE_DT(YYYYMMDD) + TRADE_TM(HHMMSS) → KST aware. 결측 시 now."""
    if date_str and len(date_str) == 8 and date_str.isdigit():
        hh, mm, ss = 0, 0, 0
        if time_str and time_str.isdigit() and len(time_str) >= 4:
            hh, mm = int(time_str[:2]), int(time_str[2:4])
            ss = int(time_str[4:6]) if len(time_str) >= 6 else 0
        return datetime(
            int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]),
            hh, mm, ss, tzinfo=KST,
        )
    return datetime.now(tz=KST)


async def _opinet_call(
    endpoint: str, *, service_key: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """OpiNet API GET → `RESULT.OIL[]` list 반환."""
    query: dict[str, Any] = {"certkey": service_key, "out": "json", **params}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{_OPINET_BASE_URL}/{endpoint}", params=query)
    if response.status_code != 200:
        raise LiveLoaderError(
            f"opinet {endpoint} HTTP {response.status_code}: {response.text[:200]}"
        )
    payload = response.json()
    result = payload.get("RESULT", {})
    oil = result.get("OIL", []) if isinstance(result, dict) else []
    if isinstance(oil, dict):
        oil = [oil]
    if not isinstance(oil, list):
        return []
    return [row for row in oil if isinstance(row, dict)]


def _adapt_opinet_station(raw: dict[str, Any]) -> _OpinetStationAdapter:
    lon_lat: tuple[Decimal, Decimal] | None = None
    gis_x = raw.get("GIS_X_COOR")
    gis_y = raw.get("GIS_Y_COOR")
    if gis_x is not None and gis_y is not None and str(gis_x).strip() and str(gis_y).strip():
        try:
            lon_lat = _opinet_katec_to_wgs84(float(gis_x), float(gis_y))
        except (ValueError, TypeError):
            lon_lat = None
    lon = lon_lat[0] if lon_lat else None
    lat = lon_lat[1] if lon_lat else None
    return _OpinetStationAdapter(
        uni_id=str(raw.get("UNI_ID", "")),
        station_name=_first_str(raw, "OS_NM") or "",
        brand_code=_first_str(raw, "POLL_DIV_CO", "POLL_DIV_CD"),
        address=_first_str(raw, "NEW_ADR", "VAN_ADR"),
        longitude=lon,
        latitude=lat,
        tel=_first_str(raw, "TEL"),
        lpg_yn=_first_str(raw, "LPG_YN"),
    )


def _adapt_opinet_price(
    raw: dict[str, Any], *, uni_id: str
) -> _OpinetPriceAdapter | None:
    prodcd = _first_str(raw, "PRODCD")
    price = raw.get("PRICE")
    if prodcd is None or price is None or str(price).strip() in {"", "0"}:
        return None
    try:
        price_dec = Decimal(str(price))
    except (ValueError, ArithmeticError):
        return None
    return _OpinetPriceAdapter(
        uni_id=uni_id,
        prodcd=prodcd,
        price=price_dec,
        trade_dt=_opinet_parse_trade_dt(
            _first_str(raw, "TRADE_DT"), _first_str(raw, "TRADE_TM")
        ),
    )


def _opinet_station_id(params: dict[str, str]) -> str:
    station_id = params.get("id") or params.get("uni_id")
    if not station_id:
        raise LiveLoaderError(
            "OpiNet detailById는 주유소 id 필요 — `?source=live&id=<UNI_ID>` 지정. "
            "(전체 목록 endpoint 없음 — 가까운 주유소 UNI_ID를 직접 지정.)"
        )
    return station_id


async def opinet_fuel_station_details_live(
    settings: DebugUiSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """OpiNet 주유소 상세 raw API → list[FeatureBundle dict] (place)."""
    key = settings.opinet_service_key
    if key is None:
        raise LiveLoaderError("OPINET_SERVICE_KEY 미설정 (.env 확인).")
    rows = await _opinet_call(
        "detailById.do",
        service_key=key.get_secret_value(),
        params={"id": _opinet_station_id(params)},
    )
    adapted = [_adapt_opinet_station(r) for r in rows]
    bundles = stations_to_bundles(
        adapted,  # type: ignore[arg-type]
        fetched_at=datetime.now(tz=KST),
    )
    return [b.model_dump(mode="json") for b in bundles]


async def opinet_gas_station_prices_live(
    settings: DebugUiSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """OpiNet 주유소 가격 raw API → list[PriceValue dict] (detailById 중첩 OIL_PRICE)."""
    key = settings.opinet_service_key
    if key is None:
        raise LiveLoaderError("OPINET_SERVICE_KEY 미설정 (.env 확인).")
    station_id = _opinet_station_id(params)
    rows = await _opinet_call(
        "detailById.do",
        service_key=key.get_secret_value(),
        params={"id": station_id},
    )
    adapted: list[_OpinetPriceAdapter] = []
    for station in rows:
        uni_id = str(station.get("UNI_ID", station_id))
        oil_prices = station.get("OIL_PRICE", [])
        if isinstance(oil_prices, dict):
            oil_prices = [oil_prices]
        for op in oil_prices if isinstance(oil_prices, list) else []:
            if not isinstance(op, dict):
                continue
            price = _adapt_opinet_price(op, uni_id=uni_id)
            if price is not None:
                adapted.append(price)
    values = prices_to_values(
        adapted,  # type: ignore[arg-type]
        feature_id=params.get("feature_id", _DEFAULT_STATION_FEATURE_ID),
    )
    return [v.model_dump(mode="json") for v in values]


# ── Registry ──────────────────────────────────────────────────────────


LIVE_LOADER_REGISTRY: Final[dict[tuple[str, str], LiveLoader]] = {
    ("python-kma-api", "kma_short_forecast"): kma_short_forecast_live,
    ("python-kma-api", "kma_ultra_short_nowcast"): kma_ultra_short_nowcast_live,
    ("python-kma-api", "kma_ultra_short_forecast"): kma_ultra_short_forecast_live,
    ("python-krex-api", "krex_rest_areas"): krex_rest_areas_live,
    ("python-krex-api", "krex_rest_area_prices"): krex_rest_area_prices_live,
    ("python-krex-api", "krex_rest_area_weather"): krex_rest_area_weather_live,
    ("python-krex-api", "krex_traffic_notices"): krex_traffic_notices_live,
    ("python-opinet-api", "opinet_fuel_station_details"): (
        opinet_fuel_station_details_live
    ),
    ("python-opinet-api", "opinet_gas_station_prices"): opinet_gas_station_prices_live,
    # ── 후속 PR (ADR-044 로컬 repo 기준) ──
    # `data.go.kr-standard` datagokr_cultural_festivals — PR#57 (로컬
    #   python-datagokr-api client 기준).
    # `kma_weather_alerts` — PR#58 (로컬 python-kma-api apihub_endpoints.py
    #   wrn_now_data 구조화 region/level).
}


def find_live_loader(provider: str, dataset: str) -> LiveLoader | None:
    """``(provider, dataset)`` → ``LiveLoader`` 또는 ``None`` (등록 안 됨)."""
    return LIVE_LOADER_REGISTRY.get((provider, dataset))


# date / 사용 안 함 경고 silencer (향후 datagokr/opinet loader에서 date 활용).
_ = date
