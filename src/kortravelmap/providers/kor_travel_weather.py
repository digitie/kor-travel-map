"""``kortravelmap.providers.kor_travel_weather`` — kor-travel-weather Map export 계약 (ADR-114 2단계).

Map은 weather 값을 PG feature로 적재하지 않는다(ADR-105). 대신 kor-travel-weather가 Map용으로 연
``GET /v1/service/exports/{locations,current,forecasts,daily-summaries}``(weather W1·W2·W3·W5)를
Dagster ``weather_state_*`` job이 받아 Valkey에 세대 단위로 싣는다(ADR-114). 이 모듈은 그 계약의
Map 쪽 정본이다 — 이미 받은 JSON 페이지를 **엄격히** 읽어 Map이 쓰는 모양으로 바꾼다.

- **REST client wrapper가 아니다**(ADR-006은 공개 provider client 규칙이다). HTTP는 Dagster
  fetcher가 한다. transport export(``providers.kor_travel_transport``)와 같은 부류다.
- 인증은 weather의 기존 관리자 header :data:`ADMIN_TOKEN_HEADER`다(weather는 Map 전용 토큰을 따로
  만들지 않았다). 실패는 401이다 — transport의 404 은닉과 다르다.
- **계약을 pin·vendoring하지 않는다**(내부 소비자 규약). 필수 필드·타입이 어긋나면
  :class:`WeatherExportContractError`로 실패한다. weather가 필드를 **더하면** 무시한다(가산 변경).
- 응답 ``meta.source_status``는 ``ok``·``stale``만 성공 페이지에 온다. ``failed``는 weather가 503으로
  내므로 200 본문에 있으면 계약 위반이다.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any, Final, Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "ADMIN_TOKEN_HEADER",
    "EXPORT_PATH_CURRENT",
    "EXPORT_PATH_DAILY_SUMMARIES",
    "EXPORT_PATH_FORECASTS",
    "EXPORT_PATH_LOCATIONS",
    "KOR_TRAVEL_WEATHER_PROVIDER_NAME",
    "WeatherExportContractError",
    "WeatherExportFailure",
    "WeatherExportMalformed",
    "WeatherExportMissing",
    "WeatherExportNotReady",
    "WeatherExportSnapshotExpired",
    "WeatherExportUnauthorized",
    "WeatherExportCurrentValue",
    "WeatherExportDailySummary",
    "WeatherExportForecastGroup",
    "WeatherExportLocation",
    "WeatherExportMeta",
    "WeatherExportPage",
    "parse_current_page",
    "parse_daily_summary_page",
    "parse_forecast_page",
    "parse_location_page",
]

KOR_TRAVEL_WEATHER_PROVIDER_NAME: Final[str] = "kor-travel-weather"
"""Map이 weather 위치 id의 ``source_type`` 접두사로 쓰는 provider 정체성."""

ADMIN_TOKEN_HEADER: Final[str] = "X-Admin-Token"
"""weather 기존 관리자 header. 값은 weather ``KOR_TRAVEL_WEATHER_ADMIN_TOKEN``."""

EXPORT_PATH_LOCATIONS: Final[str] = "/v1/service/exports/locations"
EXPORT_PATH_CURRENT: Final[str] = "/v1/service/exports/current"
EXPORT_PATH_FORECASTS: Final[str] = "/v1/service/exports/forecasts"
EXPORT_PATH_DAILY_SUMMARIES: Final[str] = "/v1/service/exports/daily-summaries"


# -- 오류 ----------------------------------------------------------------------


class WeatherExportContractError(ValueError):
    """weather export 응답이 Map이 기대하는 모양과 어긋난다. 재시도로 풀리지 않는다."""

    failure_kind: str = "weather_contract"
    retryable: bool = False


class WeatherExportFailure(RuntimeError):
    """weather export를 상태 근거로 쓸 수 없다. 어느 경우든 Valkey에 아무것도 쓰지 않는다."""

    failure_kind: str = "weather_unavailable"
    retryable: bool = False


class WeatherExportNotReady(WeatherExportFailure):
    """503 — weather에 완결된 성공 export가 아직 없다. 다음 성공 승격에서 풀린다."""

    failure_kind = "weather_not_ready"
    retryable = True


class WeatherExportSnapshotExpired(WeatherExportFailure):
    """410 — 페이지 순회 도중 weather snapshot이 만료됐다(처음부터 다시 받아도 또 만료)."""

    failure_kind = "weather_snapshot_expired"
    retryable = True


class WeatherExportUnauthorized(WeatherExportFailure):
    """401 — 토큰이 weather ``KOR_TRAVEL_WEATHER_ADMIN_TOKEN``과 다르다."""

    failure_kind = "weather_unauthorized"


class WeatherExportMissing(WeatherExportFailure):
    """404 — weather가 W1~W5 export가 없는 버전이다(또는 주소가 틀렸다)."""

    failure_kind = "weather_export_missing"


class WeatherExportMalformed(WeatherExportFailure):
    """본문이 JSON이 아니다."""

    failure_kind = "weather_malformed_upstream"


# -- 모양 ----------------------------------------------------------------------


class _Lenient(BaseModel):
    # weather가 필드를 더해도 깨지지 않게 모르는 필드는 무시한다. 있는 필드는 엄격히 본다.
    model_config = ConfigDict(extra="ignore", frozen=True)


class WeatherExportMeta(_Lenient):
    generated_at: AwareDatetime
    source_collected_at: AwareDatetime | None
    source_status: Literal["ok", "stale"]
    item_count: int = Field(ge=0, le=5000)
    snapshot_id: str | None = None
    next_cursor: str | None = None
    has_more: bool = False


class WeatherExportLocation(_Lenient):
    location_id: str = Field(min_length=1)
    name: str
    latitude: float | None
    longitude: float | None
    legal_dong_code: str | None = Field(default=None, pattern=r"^[0-9]{10}$")
    sido_name: str | None = None
    sigungu_name: str | None = None


class WeatherExportCurrentValue(_Lenient):
    location_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    value: float | str | None
    unit: str | None
    target_at: AwareDatetime
    known_at: AwareDatetime
    forecast_style: Literal["observed", "nowcast"]


class WeatherExportForecastGroup(_Lenient):
    location_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    forecast_style: Literal["ultra_short", "short", "mid", "external"]
    known_at: AwareDatetime
    published_at: AwareDatetime
    target_at: list[AwareDatetime]
    metrics: dict[str, list[float | str | None]]


class WeatherExportDailySummary(_Lenient):
    location_id: str = Field(min_length=1)
    date: dt.date
    slot: Literal["morning", "noon", "evening"]
    temp_min: float | None
    temp_max: float | None
    temp_avg: float | None
    humidity_avg: float | None
    precip_sum_mm: float | None
    precip_occurred: bool | None
    sky_code: int | None
    wind_speed_avg: float | None
    sample_count: int = Field(ge=0, le=6)
    source_providers: list[str]
    partial: bool


ItemT = TypeVar("ItemT", bound=BaseModel)


class WeatherExportPage(_Lenient, Generic[ItemT]):
    """``{items, meta}`` 한 페이지."""

    items: list[ItemT]
    meta: WeatherExportMeta


def _parse_page(payload: Any, model: type[ItemT], *, where: str) -> WeatherExportPage[ItemT]:
    if not isinstance(payload, Mapping):
        raise WeatherExportContractError(f"{where}: 본문이 객체가 아니다.")
    try:
        page: WeatherExportPage[ItemT] = WeatherExportPage[model].model_validate(  # type: ignore[valid-type]
            payload
        )
    except ValidationError as exc:
        # 값 원문은 싣지 않는다 — 위치·필드만.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['type']}"
            for error in exc.errors()[:5]
        )
        raise WeatherExportContractError(f"{where}: 응답 모양이 다르다 ({problems}).") from None
    if page.meta.item_count != len(page.items):
        raise WeatherExportContractError(
            f"{where}: meta.item_count {page.meta.item_count} ≠ 항목 {len(page.items)}."
        )
    if page.meta.has_more and not page.meta.next_cursor:
        raise WeatherExportContractError(f"{where}: has_more인데 next_cursor가 없다.")
    return page


def parse_location_page(payload: Any) -> WeatherExportPage[WeatherExportLocation]:
    """W1 ``locations`` 한 페이지."""
    return _parse_page(payload, WeatherExportLocation, where=EXPORT_PATH_LOCATIONS)


def parse_current_page(payload: Any) -> WeatherExportPage[WeatherExportCurrentValue]:
    """W2 ``current`` 한 페이지."""
    return _parse_page(payload, WeatherExportCurrentValue, where=EXPORT_PATH_CURRENT)


def parse_forecast_page(
    payload: Any, *, style: str
) -> WeatherExportPage[WeatherExportForecastGroup]:
    """W3 ``forecasts?style=`` 한 페이지. 묶음의 style·배열 길이·시각 순서를 검사한다."""
    where = f"{EXPORT_PATH_FORECASTS}?style={style}"
    page = _parse_page(payload, WeatherExportForecastGroup, where=where)
    for group in page.items:
        label = f"{where} {group.location_id}/{group.provider}"
        if group.forecast_style != style:
            raise WeatherExportContractError(
                f"{label}: 요청 style {style!r}와 다른 묶음({group.forecast_style!r})."
            )
        if any(b <= a for a, b in zip(group.target_at, group.target_at[1:], strict=False)):
            raise WeatherExportContractError(f"{label}: target_at이 오름차순이 아니다.")
        wrong = sorted(
            name for name, values in group.metrics.items() if len(values) != len(group.target_at)
        )
        if wrong:
            raise WeatherExportContractError(
                f"{label}: metric 배열 길이가 target_at({len(group.target_at)})과 다르다: {wrong}."
            )
    return page


def parse_daily_summary_page(payload: Any) -> WeatherExportPage[WeatherExportDailySummary]:
    """W5 ``daily-summaries`` 한 페이지."""
    return _parse_page(payload, WeatherExportDailySummary, where=EXPORT_PATH_DAILY_SUMMARIES)
