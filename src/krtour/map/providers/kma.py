"""``krtour.map.providers.kma`` — KMA (기상청) → ``WeatherValue`` 변환.

본 모듈은 `python-kma-api` provider 라이브러리의 typed model을 본 라이브러리
``WeatherValue`` DTO로 정규화한다. provider client + typed model은 별도 lib
(ADR-006 wrapper 금지: 본 모듈은 변환만, 호출은 호출자가 직접).

지원 dataset (Sprint 2~3, 점진 추가):

| 함수 | dataset | forecast_style |
|------|---------|----------------|
| ``short_forecast_to_weather_values`` | `kma_short_forecast` | short |
| ``ultra_short_nowcast_to_weather_values`` (후속) | `kma_ultra_short_nowcast` | nowcast |
| ``ultra_short_forecast_to_weather_values`` (후속) | `kma_ultra_short_forecast` | ultra_short |
| ``mid_forecast_to_weather_values`` (후속) | `kma_mid_forecast` | mid |
| ``weather_alerts_to_notice_bundles`` (후속) | `kma_weather_alert` | advisory |

`docs/weather-feature-normalization.md` 사양 + ADR-010 두 축 분리.

설계 메모
--------
- `python-kma-api`의 typed model은 본 라이브러리가 import하지 않는다 (ADR-006).
  ``KmaShortForecastItem`` Protocol로 입력 shape만 정의.
- KMA 단기예보 한 row(원천) = 한 격자점·시각·카테고리(metric_key) → 한
  ``WeatherValue``. 호출자는 row stream을 그대로 본 함수에 넘긴다.
- ``feature_id``는 호출자가 weather kind ``Feature``를 미리 등록한 다음 그
  ID를 본 함수에 명시적으로 전달. KMA 격자점 → Feature 매핑은 본 모듈 책임이
  **아님** (weather feature 카탈로그가 별도 — Sprint 2~3 후속).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Final, Protocol, runtime_checkable

from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import (
    ForecastStyle,
    TimelineBucket,
    WeatherDomain,
    WeatherValue,
)

__all__ = [
    "KmaShortForecastItem",
    "KmaUltraShortNowcastItem",
    "short_forecast_to_weather_values",
    "ultra_short_nowcast_to_weather_values",
    # 메타
    "KMA_PROVIDER_NAME",
    "KMA_METRIC_UNITS",
    "KMA_METRIC_NAMES",
]


# -- 상수 -----------------------------------------------------------------

KMA_PROVIDER_NAME: Final[str] = "python-kma-api"
"""canonical provider name (ADR-024)."""


# 표준 metric_key → unit (`docs/weather-feature-normalization.md §2` 표 정합).
KMA_METRIC_UNITS: Final[dict[str, str]] = {
    "T1H": "deg_c",  # 초단기실황 기온
    "TMP": "deg_c",  # 예보 기온
    "TMN": "deg_c",  # 일 최저기온
    "TMX": "deg_c",  # 일 최고기온
    "T3H": "deg_c",  # 3시간 기온
    "REH": "%",  # 상대습도
    "WSD": "m/s",  # 풍속
    "WSDM": "m/s",  # 평균 풍속
    "VEC": "deg",  # 풍향
    "RN1": "mm",  # 1시간 강수량
    "PCP": "mm",  # 1시간 강수량 (예보)
    "SNO": "cm",  # 1시간 적설
    "PTY": "code",  # 강수형태 (0 없음, 1 비, 2 비/눈, 3 눈)
    "SKY": "code",  # 하늘상태 (1 맑음, 3 구름많음, 4 흐림)
    "POP": "%",  # 강수확률
    "WAV": "m",  # 파고
    "UUU": "m/s",  # 동서바람성분
    "VVV": "m/s",  # 남북바람성분
}

# 표준 metric_key → 한글 metric_name.
KMA_METRIC_NAMES: Final[dict[str, str]] = {
    "T1H": "초단기실황 기온",
    "TMP": "기온",
    "TMN": "일 최저기온",
    "TMX": "일 최고기온",
    "T3H": "3시간 기온",
    "REH": "상대습도",
    "WSD": "풍속",
    "WSDM": "평균 풍속",
    "VEC": "풍향",
    "RN1": "1시간 강수량",
    "PCP": "1시간 강수량 (예보)",
    "SNO": "1시간 적설",
    "PTY": "강수형태",
    "SKY": "하늘상태",
    "POP": "강수확률",
    "WAV": "파고",
    "UUU": "동서바람성분",
    "VVV": "남북바람성분",
}


# -- 입력 Protocol --------------------------------------------------------


@runtime_checkable
class KmaShortForecastItem(Protocol):
    """KMA 단기예보 row 1건의 입력 shape.

    `python-kma-api`의 typed model이 본 Protocol을 만족해야 한다. KMA
    원천 응답 필드명(`baseDate`/`baseTime`/`fcstDate`/`fcstTime`/`category`/
    `fcstValue`)을 영문 snake_case로 변환된 형태로 받는다고 가정.
    """

    base_date: str
    """발표 날짜 (YYYYMMDD)."""

    base_time: str
    """발표 시각 (HHMM, 24h)."""

    fcst_date: str
    """예보 대상 날짜 (YYYYMMDD)."""

    fcst_time: str
    """예보 대상 시각 (HHMM)."""

    nx: int
    """KMA 격자 X."""

    ny: int
    """KMA 격자 Y."""

    category: str
    """metric 카테고리 (KMA 표준 — TMP/REH/WSD/POP/PCP/SNO/SKY/PTY/...)."""

    fcst_value: str
    """예보 값. 카테고리에 따라 숫자 또는 코드(예: PTY '1', SKY '1') 문자열."""


@runtime_checkable
class KmaUltraShortNowcastItem(Protocol):
    """KMA 초단기실황 (`getUltraSrtNcst`) row 1건의 입력 shape.

    단기예보와 달리 ``fcst_date``/``fcst_time``이 없다 — 발표 시각이 곧 관측
    시각. ``base_date``/``base_time``을 그대로 ``observed_at``으로 매핑.

    KMA 초단기실황 카테고리 (단기예보와 일부 다름):
    - ``T1H`` (기온), ``RN1`` (1시간 강수량), ``REH`` (습도), ``UUU``/``VVV``/
      ``VEC``/``WSD`` (바람), ``PTY`` (강수형태).
    """

    base_date: str
    """관측 날짜 (YYYYMMDD)."""

    base_time: str
    """관측 시각 (HHMM)."""

    nx: int
    """KMA 격자 X."""

    ny: int
    """KMA 격자 Y."""

    category: str
    """metric 카테고리 (T1H/RN1/REH/UUU/VVV/VEC/WSD/PTY)."""

    obsr_value: str
    """관측값. 카테고리에 따라 숫자 또는 코드 문자열."""


# -- 헬퍼 ---------------------------------------------------------------


_KST_DATETIME_FMT_BASE: Final[str] = "%Y%m%d %H%M"
"""KMA `base_date`+`base_time` 또는 `fcst_date`+`fcst_time` 결합 후 strptime."""

_KST_TIMEZONE_OFFSET_HOURS: Final[int] = 9


_KST = timezone(timedelta(hours=_KST_TIMEZONE_OFFSET_HOURS))


def _parse_kma_datetime(date_str: str, time_str: str) -> datetime:
    """KMA 형식 (YYYYMMDD, HHMM) → KST aware datetime.

    Parameters
    ----------
    date_str
        ``"YYYYMMDD"`` 8자리. 길이 다르면 ValueError.
    time_str
        ``"HHMM"`` 4자리. 길이 다르면 ValueError.

    Returns
    -------
    datetime
        ``Asia/Seoul`` aware. ADR-019.
    """
    if len(date_str) != 8 or len(time_str) != 4:
        raise ValueError(
            f"KMA datetime 형식 오류 — date={date_str!r}, time={time_str!r}."
        )
    naive = datetime.strptime(f"{date_str} {time_str}", _KST_DATETIME_FMT_BASE)
    return naive.replace(tzinfo=_KST)


def _parse_value(category: str, raw: str) -> tuple[Decimal | None, str | None]:
    """KMA `fcst_value`를 (`value_number`, `value_text`)로 변환.

    KMA 강수량/적설은 '강수없음'/'적설없음'/'1mm 미만' 같은 텍스트 표기가 섞임.
    """
    text = raw.strip()
    if not text:
        return (None, None)
    # 강수/적설 텍스트 형식
    if category in {"RN1", "PCP", "SNO"}:
        if text in {"강수없음", "적설없음", "0", "0.0"}:
            return (Decimal("0"), text)
        if "미만" in text:
            # "1mm 미만" → 0 (보수적 — 실제 값은 텍스트 보존).
            return (Decimal("0"), text)
    # 숫자 변환 시도.
    try:
        return (Decimal(text), None)
    except (ValueError, ArithmeticError):
        # 변환 실패 — 텍스트로만 보존 (코드 자체가 텍스트인 경우).
        return (None, text)


# -- 단일 row → WeatherValue ---------------------------------------------


def _item_to_weather_value(
    item: KmaShortForecastItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> WeatherValue:
    """KMA 단기예보 row 한 건 → ``WeatherValue``."""
    issued_at = _parse_kma_datetime(item.base_date, item.base_time)
    valid_at = _parse_kma_datetime(item.fcst_date, item.fcst_time)
    value_number, value_text = _parse_value(item.category, item.fcst_value)

    return WeatherValue(
        feature_id=feature_id,
        provider=normalize_provider_name(KMA_PROVIDER_NAME),
        weather_domain=WeatherDomain.KMA_SHORT_FORECAST,
        forecast_style=ForecastStyle.SHORT,
        timeline_bucket=TimelineBucket.SHORT,
        metric_key=item.category,
        source_metric_key=item.category,
        metric_name=KMA_METRIC_NAMES.get(item.category),
        unit=KMA_METRIC_UNITS.get(item.category),
        issued_at=issued_at,
        valid_at=valid_at,
        value_number=value_number,
        value_text=value_text,
        normalization_version="kma-v1.0",
        payload={
            "base_date": item.base_date,
            "base_time": item.base_time,
            "fcst_date": item.fcst_date,
            "fcst_time": item.fcst_time,
            "nx": item.nx,
            "ny": item.ny,
            "category": item.category,
            "fcst_value": item.fcst_value,
        },
        source_record_key=source_record_key,
    )


# -- 공개 API -----------------------------------------------------------


def short_forecast_to_weather_values(
    items: Iterable[KmaShortForecastItem],
    *,
    feature_id: str,
    source_record_key: str | None = None,
) -> list[WeatherValue]:
    """KMA 단기예보 items → ``list[WeatherValue]``.

    Parameters
    ----------
    items
        `python-kma-api`의 단기예보 typed model iterable. 본 모듈의
        ``KmaShortForecastItem`` Protocol을 만족해야 한다.
    feature_id
        weather kind ``Feature``의 ID (`make_feature_id` 결과). 호출자가 격자
        점 → Feature 매핑을 사전 결정해서 명시 전달.
    source_record_key
        provider raw payload 추적용 (``make_source_record_key`` 결과). 권장 —
        누락 시 trace 불가.

    Returns
    -------
    list[WeatherValue]
        입력 순서 유지. KMA 1번 호출(보통 12 카테고리 × N 시각 = 수십~수백
        row)의 결과를 모두 정규화.

    Raises
    ------
    pydantic.ValidationError
        `value_number` + `value_text` 둘 다 누락 (모든 metric에서 둘 중 하나는
        필요 — ``_check_value_present`` validator).
    ValueError
        KMA datetime 형식 위반 또는 `KmaShortForecastItem` 필드 누락.

    Examples
    --------
    호출자(TripMate Dagster asset 등) 측 사용 예시:

    >>> # client = AsyncKmaClient(...)
    >>> # async for page in client.aiter_short_forecast(nx=60, ny=127, ...):
    >>> #     values = short_forecast_to_weather_values(
    >>> #         page.items,
    >>> #         feature_id=weather_feature_id,
    >>> #         source_record_key=source_record_key,
    >>> #     )
    >>> #     await krtour_client.load_weather_values(values)

    Notes
    -----
    - KMA 단기예보는 발표 시각 기준 3시간 단위 + 5일 예보. 한 격자점에서 수십
      개 (12 카테고리 × ~24 시각) row가 떨어진다.
    - 호출자는 격자점→`feature_id` 매핑을 캐시(`KmaGridFeatureCatalog` 등)로
      가지고 있어야 한다. 본 함수는 매핑 책임 X.
    - PR#39+: `ultra_short_nowcast_to_weather_values` 추가됨 (본 PR). 후속
      `ultra_short_forecast` / `mid_forecast` / `weather_alerts_to_notice_
      bundles` (notice kind FeatureBundle)는 별도 PR.
    """
    return [
        _item_to_weather_value(
            item,
            feature_id=feature_id,
            source_record_key=source_record_key,
        )
        for item in items
    ]


# -- 초단기실황 (ultra_short_nowcast) — PR#39 ---------------------------


def _nowcast_item_to_weather_value(
    item: KmaUltraShortNowcastItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> WeatherValue:
    """KMA 초단기실황 row 한 건 → ``WeatherValue``.

    단기예보와 달리 발표 시각이 곧 관측 시각이라 ``issued_at``이 아니라
    ``observed_at``에 채운다. ``valid_at``은 None — 관측은 시점값.
    """
    observed_at = _parse_kma_datetime(item.base_date, item.base_time)
    value_number, value_text = _parse_value(item.category, item.obsr_value)

    return WeatherValue(
        feature_id=feature_id,
        provider=normalize_provider_name(KMA_PROVIDER_NAME),
        weather_domain=WeatherDomain.KMA_ULTRA_SHORT_NOWCAST,
        forecast_style=ForecastStyle.NOWCAST,
        timeline_bucket=TimelineBucket.ULTRA_SHORT,
        metric_key=item.category,
        source_metric_key=item.category,
        metric_name=KMA_METRIC_NAMES.get(item.category),
        unit=KMA_METRIC_UNITS.get(item.category),
        observed_at=observed_at,
        value_number=value_number,
        value_text=value_text,
        normalization_version="kma-v1.0",
        payload={
            "base_date": item.base_date,
            "base_time": item.base_time,
            "nx": item.nx,
            "ny": item.ny,
            "category": item.category,
            "obsr_value": item.obsr_value,
        },
        source_record_key=source_record_key,
    )


def ultra_short_nowcast_to_weather_values(
    items: Iterable[KmaUltraShortNowcastItem],
    *,
    feature_id: str,
    source_record_key: str | None = None,
) -> list[WeatherValue]:
    """KMA 초단기실황 items → ``list[WeatherValue]``.

    Parameters
    ----------
    items
        `python-kma-api`의 ``getUltraSrtNcst`` typed model iterable.
        ``KmaUltraShortNowcastItem`` Protocol을 만족해야 한다.
    feature_id
        weather kind ``Feature``의 ID (``make_feature_id`` 결과).
    source_record_key
        provider raw payload 추적용 (`make_source_record_key` 결과).

    Returns
    -------
    list[WeatherValue]
        입력 순서 유지. ``forecast_style=nowcast``, ``timeline_bucket=
        ultra_short``, ``observed_at=base_date+base_time``, ``valid_at=None``.

    Notes
    -----
    - 초단기실황 카테고리는 단기예보와 일부 다름 (예: ``T1H`` 사용). 단위/한글
      이름은 ``KMA_METRIC_UNITS`` / ``KMA_METRIC_NAMES``에 모두 포함.
    - 같은 격자점에서 8 카테고리 × 1 시각 = 8 row가 떨어진다.
    """
    return [
        _nowcast_item_to_weather_value(
            item,
            feature_id=feature_id,
            source_record_key=source_record_key,
        )
        for item in items
    ]


