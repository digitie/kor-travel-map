"""``krtour.map_admin.etl_live`` — `?source=live` provider 실 호출.

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
    weather_alerts_to_notice_bundles,
)
from krtour.map.providers.krex import (
    rest_area_prices_to_values,
    rest_area_weather_to_values,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from krtour.map.providers.opinet import prices_to_values, stations_to_bundles
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

from krtour.map_admin.settings import AdminSettings

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
    [AdminSettings, dict[str, str]],
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
    settings: AdminSettings, params: dict[str, str]
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
    settings: AdminSettings, params: dict[str, str]
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
    settings: AdminSettings, params: dict[str, str]
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

@dataclass(frozen=True)
class _KrexRestAreaAdapter:
    """`KrexRestAreaItem` Protocol 만족 (provider ``RestArea`` 정합, ADR-044).

    자연키는 변환부에서 name+route_name+direction으로 파생(uni_id 컬럼 없음),
    Protocol에 주소 필드도 없다. serviceAreaRoute 응답엔 좌표가 없어 lat/lon=None.
    """

    name: str
    route_name: str | None
    direction: str | None
    lat: float | Decimal | None
    lon: float | Decimal | None
    phone_number: str | None


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
    """`KrexTrafficNoticeItem` Protocol 만족 (provider ``krex.models.Incident`` mirror).

    ADR-044: notice_id/title/notice_type/효력기간/severity/source_agency 등 파생은
    본 lib 변환부(`traffic_notices_to_bundles`)가 전담한다 — adapter는 provider
    ``_incident`` 파서와 동일하게 raw 필드만 mirror한다.
    """

    route_no: str | None
    route_name: str | None
    direction: str | None
    incident_type: str | None
    message: str | None
    started_at: str | None
    ended_at: str | None
    raw: dict[str, Any]


def _first_str(item: dict[str, Any], *keys: str) -> str | None:
    """raw dict에서 keys 순서대로 첫 non-empty 문자열 값. 없으면 None."""
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


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
    # uni_id/address는 신 Protocol에 없음 — 자연키는 변환부가
    # name+route_name+direction으로 파생(ADR-044). serviceAreaRoute는 좌표 없음.
    return _KrexRestAreaAdapter(
        name=_first_str(raw, "serviceAreaName", "unitName", "name") or "",
        route_name=_first_str(raw, "routeName", "highway_name"),
        direction=_first_str(raw, "direction", "gffDivCd"),
        lat=None,
        lon=None,
        phone_number=_first_str(raw, "telNo", "phoneNumber", "tel"),
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
        # 실측: curStateStation 일부 행이 비숫자 가격('-' 등) 반환 → Decimal
        # 변환 실패(InvalidOperation⊂ArithmeticError)는 skip (robustness, ADR-044).
        try:
            price = Decimal(str(value).strip())
        except (ValueError, ArithmeticError):
            continue
        out.append(
            _KrexPriceAdapter(
                uni_id=uni_id,
                category="fuel",
                product_key=product_key,
                product_name=None,
                price=price,
                observed_at=observed_at,
            )
        )
    return out


def _adapt_krex_food_row(
    raw: dict[str, Any], *, observed_at: datetime
) -> _KrexPriceAdapter | None:
    raw_price = raw.get("price") or raw.get("foodPrice")
    if raw_price is None or str(raw_price).strip() in {"", "0"}:
        return None
    try:
        price = Decimal(str(raw_price).strip())
    except (ValueError, ArithmeticError):
        return None
    return _KrexPriceAdapter(
        uni_id=_first_str(raw, "serviceAreaCode", "unitCode", "uni_id") or "",
        category="food",
        product_key=_first_str(raw, "foodCode", "menuCode") or "menu",
        product_name=_first_str(raw, "foodName", "menuName"),
        price=price,
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
    """raw EX incident dict → provider ``Incident`` shape mirror (ADR-044).

    provider ``krex.client._incident`` 파서와 동일한 raw 키를 읽어 그대로 옮긴다.
    notice_type 매핑·id/title 합성·효력기간 파싱·source_agency 부여 등 모든 파생은
    본 lib 변환부(`traffic_notices_to_bundles`)가 전담하므로 adapter는 mirror만 한다.
    """
    return _KrexNoticeAdapter(
        route_no=_first_str(raw, "routeNo"),
        route_name=_first_str(raw, "routeName"),
        direction=_first_str(raw, "dirType", "directionCode"),
        incident_type=_first_str(raw, "incidentType", "eventType"),
        message=_first_str(raw, "message", "contents", "incidentContent"),
        started_at=_first_str(raw, "startDate", "startTime"),
        ended_at=_first_str(raw, "endDate", "endTime"),
        raw=raw,
    )


def _krex_key(settings: AdminSettings) -> str:
    key = settings.krex_service_key
    if key is None:
        raise LiveLoaderError("KREX_SERVICE_KEY 미설정 (.env 확인).")
    return key.get_secret_value()


async def krex_rest_areas_live(
    settings: AdminSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """krex 휴게소 목록 raw API → list[FeatureBundle dict] (place)."""
    raw_items = await _krex_call(
        "openapi/business/serviceAreaRoute",
        service_key=_krex_key(settings),
        params={k: v for k, v in params.items() if k in {"routeName", "direction"}},
    )
    adapted = [_adapt_krex_rest_area(r) for r in raw_items]
    bundles = await rest_areas_to_bundles(
        adapted,  # type: ignore[arg-type]
        fetched_at=datetime.now(tz=KST),
    )
    return [b.model_dump(mode="json") for b in bundles]


async def krex_rest_area_prices_live(
    settings: AdminSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """krex 휴게소 가격(주유 + 식음료) raw API → list[PriceValue dict].

    주유(``curStateStation``)는 정상. 식음료(``restMenuList``)는 EX OpenAPI에서
    404(deprecated, 2026-05 실측) — best-effort로 호출하고 실패 시 주유 가격만
    반환(전체 실패 방지). EX 식음료 가격 endpoint 정정은 krex-api upstream 과제.
    """
    key = _krex_key(settings)
    observed_at = datetime.now(tz=KST)
    fuel_raw = await _krex_call(
        "openapi/business/curStateStation", service_key=key, params={}
    )
    try:
        food_raw = await _krex_call(
            "openapi/restinfo/restMenuList", service_key=key, params={}
        )
    except LiveLoaderError:
        food_raw = []  # 식음료 endpoint 404(deprecated) — 주유 가격만으로 진행.
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
    settings: AdminSettings, params: dict[str, str]
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
    settings: AdminSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """krex 교통 공지/돌발 raw API → list[FeatureBundle dict] (notice)."""
    raw_items = await _krex_call(
        "openapi/trafficapi/incident",
        service_key=_krex_key(settings),
        params={k: v for k, v in params.items() if k in {"routeNo", "incidentType"}},
    )
    adapted = [_adapt_krex_notice(r) for r in raw_items]
    bundles = await traffic_notices_to_bundles(
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


def _opinet_wgs84_to_katec(lon: float, lat: float) -> tuple[float, float] | None:
    """WGS84 (lon, lat) → OpiNet KATEC (x, y). aroundAll.do discovery용.

    `_opinet_katec_to_wgs84`의 역변환 — python-opinet-api `coords.py`와 동일
    proj (ADR-044). 실패 시 None.
    """
    from pyproj import Transformer

    try:
        transformer = Transformer.from_crs(
            "EPSG:4326", _OPINET_KATEC_PROJ, always_xy=True
        )
        x, y = transformer.transform(lon, lat)
    except Exception:  # noqa: BLE001 — 변환 실패는 discovery 미수행으로 강등.
        return None
    return (x, y)


def _opinet_first_uni_id(rows: list[dict[str, Any]]) -> str | None:
    for row in rows:
        uni = row.get("UNI_ID")
        if uni is not None and str(uni).strip():
            return str(uni).strip()
    return None


async def _opinet_discover_uni_id(service_key: str, params: dict[str, str]) -> str:
    """주유소 UNI_ID 결정 — ``id`` 명시 > ``(lon,lat)`` aroundAll > lowTop10.

    OpiNet ``detailById``는 단건 조회라 UNI_ID 필요. 미지정 시 discovery
    endpoint(``aroundAll.do``/``lowTop10.do``, certkey)로 자동 확보 —
    python-opinet-api ``search_stations_around``/``get_lowest_price_top20``과
    동일 endpoint (ADR-044). 좌표 변환·key param 모두 라이브러리 정합.
    """
    explicit = params.get("id") or params.get("uni_id")
    if explicit:
        return explicit
    prodcd = params.get("prodcd", "B027")  # B027 = 휘발유(기본).
    lon_s, lat_s = params.get("lon"), params.get("lat")
    if lon_s and lat_s:
        katec: tuple[float, float] | None = None
        try:
            katec = _opinet_wgs84_to_katec(float(lon_s), float(lat_s))
        except (ValueError, TypeError):
            katec = None
        if katec is not None:
            rows = await _opinet_call(
                "aroundAll.do",
                service_key=service_key,
                params={
                    "x": int(katec[0]),
                    "y": int(katec[1]),
                    "radius": int(params.get("radius", "5000")),
                    "prodcd": prodcd,
                    "sort": params.get("sort", "1"),
                },
            )
            uni = _opinet_first_uni_id(rows)
            if uni:
                return uni
    # 기본: 전국 최저가 top (좌표 불필요 — 가장 견고).
    rows = await _opinet_call(
        "lowTop10.do",
        service_key=service_key,
        params={"prodcd": prodcd, "cnt": int(params.get("cnt", "10"))},
    )
    uni = _opinet_first_uni_id(rows)
    if uni:
        return uni
    raise LiveLoaderError(
        "OpiNet 주유소 discovery 실패 — lowTop10/aroundAll 빈 결과. "
        "`?id=<UNI_ID>` 또는 `?lon=&lat=`로 직접 지정 가능."
    )


async def opinet_fuel_station_details_live(
    settings: AdminSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """OpiNet 주유소 상세 raw API → list[FeatureBundle dict] (place).

    UNI_ID 미지정 시 lowTop10/aroundAll로 자동 discovery (`?id=`/`?lon=&lat=`
    override 가능, PR#63).
    """
    key = settings.opinet_service_key
    if key is None:
        raise LiveLoaderError("OPINET_SERVICE_KEY 미설정 (.env 확인).")
    secret = key.get_secret_value()
    station_id = await _opinet_discover_uni_id(secret, params)
    rows = await _opinet_call(
        "detailById.do",
        service_key=secret,
        params={"id": station_id},
    )
    adapted = [_adapt_opinet_station(r) for r in rows]
    bundles = await stations_to_bundles(
        adapted,  # type: ignore[arg-type]
        fetched_at=datetime.now(tz=KST),
    )
    return [b.model_dump(mode="json") for b in bundles]


async def opinet_gas_station_prices_live(
    settings: AdminSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """OpiNet 주유소 가격 raw API → list[PriceValue dict] (detailById 중첩 OIL_PRICE).

    UNI_ID 미지정 시 자동 discovery (PR#63 — fuel loader와 동일).
    """
    key = settings.opinet_service_key
    if key is None:
        raise LiveLoaderError("OPINET_SERVICE_KEY 미설정 (.env 확인).")
    secret = key.get_secret_value()
    station_id = await _opinet_discover_uni_id(secret, params)
    rows = await _opinet_call(
        "detailById.do",
        service_key=secret,
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


# =========================================================================
# data.go.kr 표준데이터 (datagokr) — 전국문화축제표준데이터. 로컬
# `python-datagokr-api` `CulturalFestivalService` 기준 (ADR-044):
# endpoint `tn_pubr_public_cltur_fstvl_api`, params serviceKey/pageNo/
# numOfRows/type=json, 응답 `response.body.items[]`. PublicCulturalFestival
# alias = raw JSON key.
# =========================================================================

_DATAGOKR_BASE_URL: Final[str] = "https://api.data.go.kr/openapi"
"""data.go.kr 표준데이터 OpenAPI base URL (로컬 datagokr config 기준)."""

_DATAGOKR_CULTURAL_FESTIVAL_ENDPOINT: Final[str] = "tn_pubr_public_cltur_fstvl_api"


@dataclass(frozen=True)
class _DatagokrFestivalAdapter:
    """`CulturalFestivalItem` Protocol 만족 (standard_data.py)."""

    management_no: str
    festival_name: str
    venue_name: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    road_address: str | None
    jibun_address: str | None
    organizer_name: str | None
    organizer_tel: str | None
    data_reference_date: date | None
    provider_org_name: str | None


def _datagokr_parse_date(value: str | None) -> date | None:
    """표준데이터 날짜('YYYY-MM-DD' 또는 'YYYYMMDD') → date. 실패 시 None."""
    if not value:
        return None
    text = value.strip().replace(".", "-")
    digits = text.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    return None


def _datagokr_decimal(value: Any) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (ValueError, ArithmeticError):
        return None


def _adapt_datagokr_festival(raw: dict[str, Any]) -> _DatagokrFestivalAdapter:
    festival_name = _first_str(raw, "fstvlNm", "festival_name") or ""
    road = _first_str(raw, "rdnmadr")
    jibun = _first_str(raw, "lnmadr")
    # 표준데이터에 관리번호 컬럼이 없어 (축제명@주소)로 자연키 합성 (결정적).
    management_no = f"{festival_name}@{road or jibun or ''}".strip("@") or festival_name
    return _DatagokrFestivalAdapter(
        management_no=management_no or "unknown",
        festival_name=festival_name,
        venue_name=_first_str(raw, "opar"),
        start_date=_datagokr_parse_date(_first_str(raw, "fstvlStartDate")),
        end_date=_datagokr_parse_date(_first_str(raw, "fstvlEndDate")),
        description=_first_str(raw, "fstvlCo"),
        latitude=_datagokr_decimal(raw.get("latitude")),
        longitude=_datagokr_decimal(raw.get("longitude")),
        road_address=road,
        jibun_address=jibun,
        organizer_name=_first_str(raw, "mnnstNm", "auspcInsttNm"),
        organizer_tel=_first_str(raw, "phoneNumber"),
        data_reference_date=_datagokr_parse_date(_first_str(raw, "referenceDate")),
        provider_org_name=_first_str(raw, "instt_nm"),
    )


async def _datagokr_call(
    endpoint: str, *, service_key: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """data.go.kr 표준데이터 GET → `response.body.items[]` list 반환."""
    query: dict[str, Any] = {
        "serviceKey": service_key,
        "type": "json",
        "pageNo": 1,
        "numOfRows": 100,
        **params,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{_DATAGOKR_BASE_URL}/{endpoint}", params=query)
    if response.status_code != 200:
        raise LiveLoaderError(
            f"datagokr {endpoint} HTTP {response.status_code}: {response.text[:200]}"
        )
    payload = response.json()
    body = payload.get("response", {}).get("body", {}) if isinstance(payload, dict) else {}
    items = body.get("items", []) if isinstance(body, dict) else []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    return [row for row in items if isinstance(row, dict)]


async def datagokr_cultural_festivals_live(
    settings: AdminSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """data.go.kr 전국문화축제표준데이터 raw API → list[FeatureBundle dict]."""
    key = settings.datagokr_service_key
    if key is None:
        raise LiveLoaderError("DATAGOKR_SERVICE_KEY 미설정 (.env 확인).")
    raw_items = await _datagokr_call(
        _DATAGOKR_CULTURAL_FESTIVAL_ENDPOINT,
        service_key=key.get_secret_value(),
        params={},
    )
    adapted = [_adapt_datagokr_festival(r) for r in raw_items]
    bundles = await cultural_festivals_to_bundles(
        adapted,  # type: ignore[arg-type]
        fetched_at=datetime.now(tz=KST),
    )
    return [b.model_dump(mode="json") for b in bundles]


# =========================================================================
# 기상청 API 허브 (apihub.kma.go.kr) — 특보현황 `wrn_now_data`. data.go.kr
# 게이트웨이(serviceKey)와 달리 apihub는 `authKey`(별도 키, settings.
# kma_apihub_key)를 쓴다. wrn_now_data는 **특보구역(REG_ID) 단위 행**을 주므로
# 본 lib `weather_alerts_to_notice_bundles`(region fan-out)에 정합.
#
# 응답은 text/plain (JSON 아님): `#`-주석 헤더 + 공백/콤마 구분 데이터 행
# (로컬 python-kma-api `apihub.parse_apihub_text_table` 포맷 — ADR-044). 본
# 모듈은 동일 방식으로 헤더 줄을 찾아 행을 dict로 파싱한다.
#
# ⚠️ 컬럼명(REG_ID/TM_FC/TM_EF/WRN/LVL)은 KMA 공표 특보 스펙 기준으로 매핑하되,
# apihub help 블록의 정확한 헤더 표기는 실 응답(authKey 필요)으로 후속 검증
# 필요 — 헤더 줄을 못 찾으면 빈 list 반환(graceful). adapter는 순수 함수라
# `tests/test_etl_live_kma_alert_adapters.py`로 단위 검증.
# =========================================================================

_KMA_APIHUB_BASE_URL: Final[str] = "https://apihub.kma.go.kr"
"""기상청 API 허브 base URL (authKey 인증, data.go.kr와 별개)."""

_KMA_WRN_NOW_PATH: Final[str] = "api/typ01/url/wrn_now_data.php"
"""특보현황 조회 endpoint (로컬 apihub_endpoints.py `wrn_now_data` 기준)."""

# 특보종류 코드(WRN 1자) → (한글명, canonical notice_type). 미스펙 종류는
# generic `weather_alert`로 강등 (normalize_notice_type ValueError 회피 —
# dto/notice.py alias에 강풍/한파/건조/풍랑/태풍/황사/해일 미등록).
_KMA_WRN_CODE_MAP: Final[dict[str, tuple[str, str]]] = {
    "W": ("강풍", "weather_alert"),
    "R": ("호우", "heavy_rain_warning"),
    "C": ("한파", "weather_alert"),
    "D": ("건조", "weather_alert"),
    "O": ("폭풍해일", "weather_alert"),
    "N": ("지진해일", "weather_alert"),
    "V": ("풍랑", "weather_alert"),
    "T": ("태풍", "weather_alert"),
    "S": ("대설", "heavy_snow_warning"),
    "Y": ("황사", "weather_alert"),
    "H": ("폭염", "heat_wave_warning"),
}

# 특보수준 코드(LVL) → 한글 등급 (provider KMA_ALERT_LEVEL_SEVERITY 키와 정합).
_KMA_WRN_LEVEL_MAP: Final[dict[str, str]] = {
    "0": "예비특보",
    "1": "주의보",
    "2": "경보",
    "3": "경보",
}

# wrn_now_data 헤더 줄 식별용 known 컬럼 토큰 (help 블록의 설명 줄과 구분).
_KMA_WRN_HEADER_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "REG_ID",
        "REG_UP",
        "REG_KO",
        "REG_NM",
        "REG_NAME",
        "TM_FC",
        "TM_EF",
        "TM_ED",
        "ED_TM",
        "WRN",
        "LVL",
        "CMD",
    }
)


@dataclass(frozen=True)
class _KmaAlertRegionAdapter:
    """`KmaWeatherAlertRegion` Protocol 만족."""

    region_code: str
    region_name: str


@dataclass(frozen=True)
class _KmaWeatherAlertAdapter:
    """`KmaWeatherAlertItem` Protocol 만족 — wrn_now_data 1행 = 1 (특보×구역)."""

    alert_id: str
    alert_type: str
    level: str | None
    title: str
    description: str | None
    issued_at: datetime
    effective_from: datetime | None
    effective_until: datetime | None
    source_agency: str | None
    regions: list[_KmaAlertRegionAdapter]


def _kma_apihub_parse_dt(value: str | None) -> datetime | None:
    """apihub 시각(YYYYMMDDHHmm 12자리 / YYYYMMDD 8자리) → KST aware. 실패 None."""
    if not value:
        return None
    digits = value.strip()
    if not digits.isdigit():
        return None
    if len(digits) >= 12:
        return datetime(
            int(digits[:4]), int(digits[4:6]), int(digits[6:8]),
            int(digits[8:10]), int(digits[10:12]), tzinfo=KST,
        )
    if len(digits) == 8:
        return datetime(
            int(digits[:4]), int(digits[4:6]), int(digits[6:8]), tzinfo=KST
        )
    return None


def _kma_apihub_parse_table(text: str) -> list[dict[str, str]]:
    """apihub text 응답 → row dict list (헤더는 `#`-주석에서 추출, 대문자 키).

    로컬 `apihub.parse_apihub_text_table` 정책 정합: `#`-주석 줄 중 known 컬럼
    토큰 3개 이상인 줄을 헤더로 삼고, 데이터 행은 콤마(있으면)/공백으로 분리.
    헤더를 못 찾으면 빈 list (graceful).
    """
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    nonempty = [ln.strip() for ln in lines if ln.strip()]
    comments = [ln for ln in nonempty if ln.startswith("#")]
    data_lines = [ln for ln in nonempty if not ln.startswith("#")]
    headers: list[str] = []
    for comment in comments:
        tokens = [t.upper() for t in comment.lstrip("#").replace(",", " ").split()]
        known = [t for t in tokens if t in _KMA_WRN_HEADER_TOKENS]
        if len(known) >= 3:
            headers = tokens
            break
    if not headers:
        return []
    rows: list[dict[str, str]] = []
    for line in data_lines:
        values = line.split(",") if "," in line else line.split()
        values = [v.strip() for v in values]
        if len(values) < 2:
            continue
        rows.append(
            {
                headers[i]: (values[i] if i < len(values) else "")
                for i in range(len(headers))
            }
        )
    return rows


def _adapt_kma_wrn_row(row: dict[str, str]) -> _KmaWeatherAlertAdapter | None:
    """wrn_now_data 1행(dict, 대문자 키) → `_KmaWeatherAlertAdapter` 또는 None."""
    reg_code = _first_str(row, "REG_ID", "REG_UP")
    wrn = _first_str(row, "WRN")
    if reg_code is None or wrn is None:
        return None
    korean, notice_type = _KMA_WRN_CODE_MAP.get(wrn.upper(), (wrn, "weather_alert"))
    lvl_raw = _first_str(row, "LVL")
    level = _KMA_WRN_LEVEL_MAP.get(lvl_raw or "")
    tm_fc = _first_str(row, "TM_FC")
    issued = _kma_apihub_parse_dt(tm_fc) or datetime.now(tz=KST)
    effective_from = _kma_apihub_parse_dt(_first_str(row, "TM_EF")) or issued
    effective_until = _kma_apihub_parse_dt(_first_str(row, "ED_TM", "TM_ED"))
    region_name = _first_str(row, "REG_KO", "REG_NM", "REG_NAME") or reg_code
    title = f"{korean}{level}" if level else korean
    return _KmaWeatherAlertAdapter(
        alert_id=f"{reg_code}:{tm_fc or ''}:{wrn.upper()}:{lvl_raw or ''}",
        alert_type=notice_type,
        level=level,
        title=title,
        description=f"{title} 발효 — {region_name}",
        issued_at=issued,
        effective_from=effective_from,
        effective_until=effective_until,
        source_agency="기상청",
        regions=[
            _KmaAlertRegionAdapter(region_code=reg_code, region_name=region_name)
        ],
    )


async def _kma_apihub_text(
    path: str, *, auth_key: str, params: dict[str, Any]
) -> str:
    """apihub GET → response.text (text/plain). 비-200은 LiveLoaderError."""
    query: dict[str, Any] = {"authKey": auth_key, **params}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{_KMA_APIHUB_BASE_URL}/{path.lstrip('/')}", params=query
        )
    if response.status_code != 200:
        raise LiveLoaderError(
            f"KMA apihub {path} HTTP {response.status_code}: {response.text[:200]}"
        )
    return response.text


# ── data.go.kr getWthrWrnList fallback (apihub 활용신청 전/미보유 시) ──────
# apihub wrn_now_data가 활용신청 필요(HTTP 403)거나 KMA_APIHUB_KEY 미보유면
# data.go.kr `WthrWrnInfoService/getWthrWrnList`(공통 serviceKey =
# settings.kma_service_key)로 fallback. 단 getWthrWrnList는 구조화 특보구역이
# 없고 title(요약문)만 줌 → 관서(stnId) 단위 pseudo-region 1건으로 강등.
# 실 응답 필드(2026-05 확인): stnId / title / tmFc(int) / tmSeq.

_KMA_WTHR_WRN_LIST_URL: Final[str] = (
    "https://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnList"
)

# getWthrWrnList stnId 기본값 — 108(전국 본청).
_KMA_DEFAULT_WRN_STN: Final[str] = "108"

# 발표관서코드 → 한글명 (대표 몇 개; 미등록은 'KMA 관서 {stn}').
_KMA_WRN_STN_NAME: Final[dict[str, str]] = {
    "108": "기상청(전국 본청)",
    "109": "수도권(서울·인천·경기)",
    "159": "부산",
    "143": "대구",
    "146": "전주(전북)",
    "156": "광주(전남)",
    "133": "대전(충청)",
    "184": "제주",
    "105": "강원(영동)",
}

# 특보 title에서 특보종류 keyword → canonical notice_type (notice.py NOTICE_TYPES).
# 미스펙 종류는 generic weather_alert (normalize_notice_type ValueError 회피).
_KMA_WRN_TITLE_KEYWORDS: Final[tuple[tuple[str, str], ...]] = (
    ("호우", "heavy_rain_warning"),
    ("대설", "heavy_snow_warning"),
    ("폭염", "heat_wave_warning"),
    ("강풍", "weather_alert"),
    ("풍랑", "weather_alert"),
    ("한파", "weather_alert"),
    ("건조", "weather_alert"),
    ("태풍", "weather_alert"),
    ("황사", "weather_alert"),
    ("해일", "weather_alert"),
    ("폭풍", "weather_alert"),
)


def _datagokr_wrn_notice_type(title: str) -> str:
    """특보 title 요약문에서 특보종류 keyword → canonical notice_type."""
    for keyword, notice_type in _KMA_WRN_TITLE_KEYWORDS:
        if keyword in title:
            return notice_type
    return "weather_alert"


def _datagokr_wrn_level(title: str) -> str | None:
    """특보 title에서 등급 추출 (경보 > 주의보 > 예비특보 우선순위)."""
    if "경보" in title:
        return "경보"
    if "주의보" in title:
        return "주의보"
    if "예비특보" in title:
        return "예비특보"
    return None


def _adapt_datagokr_wrn(raw: dict[str, Any]) -> _KmaWeatherAlertAdapter:
    """getWthrWrnList 1행(stnId/title/tmFc/tmSeq) → `_KmaWeatherAlertAdapter`.

    구조화 특보구역이 없어 관서(stnId) 단위 pseudo-region 1건으로 강등. title
    요약문에서 특보종류/등급을 keyword 매칭으로 추출(coarse). apihub 활용신청
    시 primary(`_adapt_kma_wrn_row`)가 구조화 region 제공.
    """
    stn = _first_str(raw, "stnId") or _KMA_DEFAULT_WRN_STN
    title = _first_str(raw, "title") or ""
    tm_fc = _first_str(raw, "tmFc") or ""
    tm_seq = _first_str(raw, "tmSeq") or ""
    issued = _kma_apihub_parse_dt(tm_fc) or datetime.now(tz=KST)
    region_name = _KMA_WRN_STN_NAME.get(stn, f"KMA 관서 {stn}")
    return _KmaWeatherAlertAdapter(
        alert_id=f"{stn}:{tm_fc}:{tm_seq}",
        alert_type=_datagokr_wrn_notice_type(title),
        level=_datagokr_wrn_level(title),
        title=title or "기상특보",
        description=title or None,
        issued_at=issued,
        effective_from=issued,
        effective_until=None,
        source_agency="기상청",
        regions=[
            _KmaAlertRegionAdapter(region_code=f"stn:{stn}", region_name=region_name)
        ],
    )


async def _datagokr_wrn_list(
    *, service_key: str, params: dict[str, str]
) -> list[dict[str, Any]]:
    """data.go.kr getWthrWrnList GET → `response.body.items.item[]` list."""
    now = datetime.now(tz=KST)
    query: dict[str, Any] = {
        "serviceKey": service_key,
        "dataType": "JSON",
        "pageNo": 1,
        "numOfRows": 100,
        "stnId": params.get("stnId", _KMA_DEFAULT_WRN_STN),
        "fromTmFc": params.get(
            "fromTmFc", (now - timedelta(days=3)).strftime("%Y%m%d")
        ),
        "toTmFc": params.get("toTmFc", now.strftime("%Y%m%d")),
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(_KMA_WTHR_WRN_LIST_URL, params=query)
    if response.status_code != 200:
        raise LiveLoaderError(
            f"KMA getWthrWrnList HTTP {response.status_code}: {response.text[:200]}"
        )
    payload = response.json()
    body = payload.get("response", {}).get("body", {}) if isinstance(payload, dict) else {}
    items_wrap = body.get("items", {}) if isinstance(body, dict) else {}
    raw_items = (
        items_wrap.get("item", []) if isinstance(items_wrap, dict) else items_wrap
    )
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return []
    return [it for it in raw_items if isinstance(it, dict)]


async def kma_weather_alerts_live(
    settings: AdminSettings, params: dict[str, str]
) -> list[dict[str, Any]]:
    """KMA 특보현황 → list[FeatureBundle dict] (notice). **data.go.kr primary + apihub fallback**.

    KMA 소스 정책(사용자 지시 2026-05-28): **data.go.kr 소스가 있으면 data.go.kr이
    primary, apihub는 fallback** (동네예보 3종도 data.go.kr 단독으로 동일 정책).
    - **primary**: data.go.kr `getWthrWrnList`(settings.kma_service_key, 공통키) —
      관서(stnId) 단위 region(coarse), title 요약문 keyword 매칭. HTTP 200이면
      빈 결과(무특보)라도 valid로 반환.
    - **fallback**: apihub `wrn_now_data`(settings.kma_apihub_key) — 특보구역(REG_ID)
      구조화 region. data.go.kr **실패(에러/무키)** 시에만 사용 (apihub는 활용신청 필요).

    `?via=apihub`로 apihub 강제(구조화 region 테스트), `?via=datagokr`로 data.go.kr
    강제. 둘 다 미설정/불가면 503.
    """
    fetched_at = datetime.now(tz=KST)
    via = params.get("via", "")
    errors: list[str] = []

    # primary: data.go.kr getWthrWrnList (공통 serviceKey).
    datagokr_key = settings.kma_service_key
    if via != "apihub" and datagokr_key is not None:
        try:
            items = await _datagokr_wrn_list(
                service_key=datagokr_key.get_secret_value(), params=params
            )
        except LiveLoaderError as exc:
            errors.append(f"data.go.kr: {exc}")  # 에러 → apihub fallback.
        else:
            # HTTP 200 → 빈 결과(무특보)도 valid 반환 (primary 성공).
            adapted_dg = [_adapt_datagokr_wrn(it) for it in items]
            bundles = weather_alerts_to_notice_bundles(
                adapted_dg,  # type: ignore[arg-type]
                fetched_at=fetched_at,
            )
            return [b.model_dump(mode="json") for b in bundles]
    elif via != "apihub":
        errors.append("data.go.kr: KMA_SERVICE_KEY 미설정")

    # fallback: apihub wrn_now_data (구조화 region, 활용신청 필요).
    apihub_key = settings.kma_apihub_key
    if apihub_key is not None:
        try:
            text = await _kma_apihub_text(
                _KMA_WRN_NOW_PATH,
                auth_key=apihub_key.get_secret_value(),
                params={
                    "fe": params.get("fe", "f"),
                    "tm": params.get("tm", ""),
                    "disp": params.get("disp", "0"),
                    "help": "1",  # 컬럼 헤더(`#`-주석) 포함 — 파서 헤더 검출용.
                },
            )
            rows = _kma_apihub_parse_table(text)
            adapted = [a for a in (_adapt_kma_wrn_row(r) for r in rows) if a is not None]
            bundles = weather_alerts_to_notice_bundles(
                adapted,  # type: ignore[arg-type]
                fetched_at=fetched_at,
            )
            return [b.model_dump(mode="json") for b in bundles]
        except LiveLoaderError as exc:
            errors.append(f"apihub: {exc}")
    else:
        errors.append("apihub: KMA_APIHUB_KEY 미설정")

    raise LiveLoaderError(
        "weather_alerts live 미설정/불가 — data.go.kr KMA_SERVICE_KEY(primary) "
        "또는 apihub KMA_APIHUB_KEY(fallback, apihub.kma.go.kr 활용신청) 필요. "
        f"[{' / '.join(errors)}]"
    )


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
    ("data.go.kr-standard", "datagokr_cultural_festivals"): (
        datagokr_cultural_festivals_live
    ),
    ("python-kma-api", "kma_weather_alerts"): kma_weather_alerts_live,
    # ── 11/11 fixture dataset 전부 live wiring 완료 (ADR-044 로컬 repo 기준) ──
}


def find_live_loader(provider: str, dataset: str) -> LiveLoader | None:
    """``(provider, dataset)`` → ``LiveLoader`` 또는 ``None`` (등록 안 됨)."""
    return LIVE_LOADER_REGISTRY.get((provider, dataset))
