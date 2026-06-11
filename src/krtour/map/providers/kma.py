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

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from krtour.map.core.address import normalize_korean_text
from krtour.map.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import (
    Address,
    Feature,
    FeatureBundle,
    FeatureKind,
    ForecastStyle,
    NoticeDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
    TimelineBucket,
    WeatherDomain,
    WeatherValue,
)

__all__ = [
    "KmaShortForecastItem",
    "KmaUltraShortNowcastItem",
    "KmaUltraShortForecastItem",
    "KmaWeatherAlertRegion",
    "KmaWeatherAlertItem",
    "KmaMidLandForecastItem",
    "KmaMidTemperatureItem",
    "short_forecast_to_weather_values",
    "ultra_short_nowcast_to_weather_values",
    "ultra_short_forecast_to_weather_values",
    "weather_alerts_to_notice_bundles",
    "mid_land_forecast_to_weather_values",
    "mid_temperature_to_weather_values",
    # 메타
    "KMA_PROVIDER_NAME",
    "KMA_METRIC_UNITS",
    "KMA_METRIC_NAMES",
    "KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY",
    "KMA_ULTRA_SHORT_FORECAST_DATASET_KEY",
    "KMA_SHORT_FORECAST_DATASET_KEY",
    "KMA_MID_FORECAST_DATASET_KEY",
    "KMA_WEATHER_ALERT_DATASET_KEY",
    "KMA_WEATHER_ALERT_CATEGORY",
    "KMA_WEATHER_ALERT_MARKER_ICON",
    "KMA_WEATHER_ALERT_MARKER_COLOR",
    "KMA_ALERT_LEVEL_SEVERITY",
    "KmaMidRegionSpec",
    "parse_weather_extra_points",
    "parse_mid_region_features",
]


# -- 상수 -----------------------------------------------------------------

KMA_PROVIDER_NAME: Final[str] = "python-kma-api"
"""canonical provider name (ADR-024)."""


# -- weather dataset_key (T-219b) ----------------------------------------
# `docs/kma-weather-etl.md` §2 표 + `docs/provider-contract.md` §3 정합.

KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY: Final[str] = "kma_ultra_short_nowcast"
"""provider_sync dataset_key — 초단기실황 (``getUltraSrtNcst``)."""

KMA_ULTRA_SHORT_FORECAST_DATASET_KEY: Final[str] = "kma_ultra_short_forecast"
"""provider_sync dataset_key — 초단기예보 (``getUltraSrtFcst``)."""

KMA_SHORT_FORECAST_DATASET_KEY: Final[str] = "kma_short_forecast"
"""provider_sync dataset_key — 단기예보 (``getVilageFcst``)."""


# -- 특보 (weather_alerts) 상수 (PR#46) ---------------------------------

KMA_WEATHER_ALERT_DATASET_KEY: Final[str] = "kma_weather_alerts"
"""provider_sync.source_records.dataset_key — KMA 특보."""

_KMA_WEATHER_ALERT_ENTITY_TYPE: Final[str] = "weather_alert"

# notice kind는 NoticeDetail.notice_type이 진짜 분류. category는 부차적이라
# 카테고리 트리 확장될 때까지 placeholder ``"99000000"``.
KMA_WEATHER_ALERT_CATEGORY: Final[str] = "99000000"

KMA_WEATHER_ALERT_MARKER_ICON: Final[str] = "danger"
KMA_WEATHER_ALERT_MARKER_COLOR: Final[str] = "P-15"

# KMA 특보 등급 → NoticeDetail.severity (0~5).
KMA_ALERT_LEVEL_SEVERITY: Final[dict[str, int]] = {
    "예비특보": 0,
    "주의보": 1,
    "경보": 2,
    "긴급": 3,
    # 등급 외 영문 alias.
    "watch": 1,
    "warning": 2,
    "advisory": 1,
    "emergency": 3,
}


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
    "LGT": "code",  # 낙뢰 (초단기예보 전용)
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
    "LGT": "낙뢰",
}


def parse_weather_extra_points(value: str | None) -> list[tuple[float, float]]:
    """``kma_weather_extra_points`` 설정(``lon,lat;lon,lat``) 파서 (T-219a).

    KMA weather 적재 대상에 명시 추가할 좌표 목록. 세미콜론으로 지점을, 콤마로
    lon/lat을 구분한다(공백 허용). 빈 항목은 무시하고, 숫자가 아니거나 한국
    bbox(경도 124~132, 위도 33~43) 밖이면 ``ValueError`` — 설정 오타가 조용히
    빈 대상이 되지 않게 한다. ``None``/빈 문자열은 빈 목록.
    """
    if value is None or not value.strip():
        return []
    points: list[tuple[float, float]] = []
    for chunk in value.split(";"):
        part = chunk.strip()
        if not part:
            continue
        pieces = [p.strip() for p in part.split(",")]
        if len(pieces) != 2:
            raise ValueError(f"좌표는 'lon,lat' 형식이어야 합니다: {part!r}")
        try:
            lon, lat = float(pieces[0]), float(pieces[1])
        except ValueError as exc:
            raise ValueError(f"좌표 숫자 변환 실패: {part!r}") from exc
        if not (124.0 <= lon <= 132.0 and 33.0 <= lat <= 43.0):
            raise ValueError(
                f"좌표가 한국 bbox(lon 124~132, lat 33~43) 밖입니다: {part!r}"
            )
        points.append((lon, lat))
    return points


@dataclass(frozen=True, slots=True)
class KmaMidRegionSpec:
    """중기예보 적재 대상 region 1건 (T-219c — `parse_mid_region_features` 결과).

    중기 **육상**(`getMidLandFcst`)과 **기온**(`getMidTa`)은 예보구역 코드 체계가
    다르다(예: 서울 육상 ``11B00000`` vs 기온 ``11B10101``) — 한 spec이 두 코드와
    값을 적재할 feature 목록을 함께 갖는다.
    """

    land_reg_id: str
    """중기육상예보 구역 코드 (``getMidLandFcst`` regId)."""

    ta_reg_id: str
    """중기기온예보 구역 코드 (``getMidTa`` regId)."""

    feature_ids: tuple[str, ...]
    """이 region의 ``WeatherValue``를 붙일 feature ID 목록 (비어 있으면 안 됨)."""


def parse_mid_region_features(value: str | None) -> tuple[KmaMidRegionSpec, ...]:
    """``kma_mid_region_features`` 설정(JSON) 파서 (T-219c).

    중기예보는 격자가 아니라 region 107 지점 체계라 좌표→격자 매핑(옵션 B)을
    쓸 수 없다 — 1차는 운영자가 광역시도 대표 feature 매핑을 설정으로 주입하고,
    미설정이면 asset이 skip한다(계획 정본 §2.4). 형식:

    ``[{"land_reg_id": "11B00000", "ta_reg_id": "11B10101",
    "feature_ids": ["..."]}]``

    ``None``/빈 문자열은 빈 tuple. JSON 오류·필수 키 누락·빈 feature_ids·
    중복 (land, ta) 페어는 ``ValueError`` — 설정 오타가 조용히 빈 대상이 되지
    않게 한다.
    """
    if value is None or not value.strip():
        return ()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"kma_mid_region_features JSON 파싱 실패: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError("kma_mid_region_features는 JSON 배열이어야 합니다.")
    specs: list[KmaMidRegionSpec] = []
    seen: set[tuple[str, str]] = set()
    for entry in parsed:
        if not isinstance(entry, dict):
            raise ValueError(f"region 항목은 객체여야 합니다: {entry!r}")
        land = entry.get("land_reg_id")
        ta = entry.get("ta_reg_id")
        feature_ids = entry.get("feature_ids")
        if not isinstance(land, str) or not land.strip():
            raise ValueError(f"land_reg_id 누락/형식 오류: {entry!r}")
        if not isinstance(ta, str) or not ta.strip():
            raise ValueError(f"ta_reg_id 누락/형식 오류: {entry!r}")
        if (
            not isinstance(feature_ids, list)
            or not feature_ids
            or not all(isinstance(f, str) and f.strip() for f in feature_ids)
        ):
            raise ValueError(f"feature_ids는 비어 있지 않은 문자열 배열이어야 합니다: {entry!r}")
        pair = (land.strip(), ta.strip())
        if pair in seen:
            raise ValueError(f"중복 region 페어: {pair!r}")
        seen.add(pair)
        specs.append(
            KmaMidRegionSpec(
                land_reg_id=pair[0],
                ta_reg_id=pair[1],
                feature_ids=tuple(f.strip() for f in feature_ids),
            )
        )
    return tuple(specs)


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


@runtime_checkable
class KmaUltraShortForecastItem(Protocol):
    """KMA 초단기예보 (``getUltraSrtFcst``) row 1건의 입력 shape.

    필드 shape은 단기예보와 동일 (base/fcst 분리). 차이는 도메인 + style +
    timeline_bucket과 카테고리 일부 (예: ``LGT`` 낙뢰가 ultra_short에만).

    호출자가 단기예보 → ``KmaShortForecastItem``, 초단기예보 → 본 Protocol로
    명시 분류해서 전달.
    """

    base_date: str
    """발표 날짜 (YYYYMMDD)."""

    base_time: str
    """발표 시각 (HHMM)."""

    fcst_date: str
    """예보 대상 날짜 (YYYYMMDD)."""

    fcst_time: str
    """예보 대상 시각 (HHMM)."""

    nx: int
    """KMA 격자 X."""

    ny: int
    """KMA 격자 Y."""

    category: str
    """metric 카테고리 (T1H/RN1/REH/UUU/VVV/VEC/WSD/PTY/SKY/LGT)."""

    fcst_value: str
    """예보 값. 카테고리에 따라 숫자 또는 코드 문자열."""


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


# -- 초단기예보 (ultra_short_forecast) — PR#41 --------------------------


def _ultra_short_forecast_item_to_weather_value(
    item: KmaUltraShortForecastItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> WeatherValue:
    """KMA 초단기예보 row 한 건 → ``WeatherValue``.

    단기예보와 필드 shape은 동일. domain/style/timeline만 ultra_short로.
    """
    issued_at = _parse_kma_datetime(item.base_date, item.base_time)
    valid_at = _parse_kma_datetime(item.fcst_date, item.fcst_time)
    value_number, value_text = _parse_value(item.category, item.fcst_value)

    return WeatherValue(
        feature_id=feature_id,
        provider=normalize_provider_name(KMA_PROVIDER_NAME),
        weather_domain=WeatherDomain.KMA_ULTRA_SHORT_FORECAST,
        forecast_style=ForecastStyle.ULTRA_SHORT,
        timeline_bucket=TimelineBucket.ULTRA_SHORT,
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


def ultra_short_forecast_to_weather_values(
    items: Iterable[KmaUltraShortForecastItem],
    *,
    feature_id: str,
    source_record_key: str | None = None,
) -> list[WeatherValue]:
    """KMA 초단기예보 items → ``list[WeatherValue]``.

    Parameters
    ----------
    items
        ``python-kma-api``의 ``getUltraSrtFcst`` typed model iterable.
        ``KmaUltraShortForecastItem`` Protocol을 만족해야 한다.
    feature_id
        weather kind ``Feature``의 ID.
    source_record_key
        provider raw payload 추적용.

    Returns
    -------
    list[WeatherValue]
        ``forecast_style=ultra_short``, ``timeline_bucket=ultra_short``,
        `issued_at`/`valid_at` 채움, `observed_at=None`.

    Notes
    -----
    - 초단기예보는 30분 단위로 발표, 6시간 예보. 한 격자점에서 10 카테고리 ×
      ~12 시각 = ~120 row가 떨어진다.
    - 카테고리 일부는 단기예보와 다름 (예: ``LGT`` 낙뢰는 초단기예보 전용).
      ``KMA_METRIC_UNITS``/``KMA_METRIC_NAMES``에 수록돼 있다(unit=code).
    """
    return [
        _ultra_short_forecast_item_to_weather_value(
            item,
            feature_id=feature_id,
            source_record_key=source_record_key,
        )
        for item in items
    ]


# -- 특보 (weather_alerts) → notice FeatureBundle — PR#46 ---------------


@runtime_checkable
class KmaWeatherAlertRegion(Protocol):
    """KMA 특보 적용 지역 1건."""

    region_code: str
    """KMA 특보 구역 코드 (예: ``"11B10101"``). source_natural_key의 일부로 사용."""

    region_name: str
    """지역 한글 명 (예: ``"서울특별시"``)."""


@runtime_checkable
class KmaWeatherAlertItem(Protocol):
    """KMA 특보 1건의 입력 shape.

    한 alert은 여러 region에 적용된다 — 본 모듈은 ``alert × region`` 조합마다
    별도 ``FeatureBundle``(notice kind)을 생성한다.
    """

    alert_id: str
    """KMA 특보 자연키 (provider 내 unique)."""

    alert_type: str
    """특보 종류 (한/영 alias 가능 — ``normalize_notice_type``이 정규화)."""

    level: str | None
    """등급 (``"주의보"``/``"경보"``/``"긴급"`` 등)."""

    title: str
    """제목 (``Feature.name``)."""

    description: str | None
    """본문."""

    issued_at: datetime
    """발표 시각 (KST aware)."""

    effective_from: datetime | None
    """효력 시작."""

    effective_until: datetime | None
    """효력 종료 (open-ended 가능)."""

    source_agency: str | None
    """발령 기관 (보통 ``"기상청"``)."""

    regions: list[KmaWeatherAlertRegion]
    """적용 지역 list. 빈 list면 본 함수가 결과를 빈 list로 반환."""


def _alert_region_to_bundle(
    alert: KmaWeatherAlertItem,
    region: KmaWeatherAlertRegion,
    *,
    fetched_at: datetime,
) -> FeatureBundle:
    """`(alert, region)` → 한 notice ``FeatureBundle``."""
    raw_data: dict[str, Any] = {
        "alert_id": alert.alert_id,
        "alert_type": alert.alert_type,
        "level": alert.level,
        "title": alert.title,
        "description": alert.description,
        "issued_at": alert.issued_at.isoformat(),
        "effective_from": (
            alert.effective_from.isoformat() if alert.effective_from else None
        ),
        "effective_until": (
            alert.effective_until.isoformat()
            if alert.effective_until
            else None
        ),
        "source_agency": alert.source_agency,
        "region_code": region.region_code,
        "region_name": region.region_name,
    }
    payload_hash = make_payload_hash(raw_data)

    # source_natural_key는 alert_id × region_code 조합.
    natural_key = f"{alert.alert_id}::{region.region_code}"
    source_record_key = make_source_record_key(
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_WEATHER_ALERT_DATASET_KEY,
        source_entity_type=_KMA_WEATHER_ALERT_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=None,  # KMA region_code는 bjd_code와 다름. global fallback.
        kind=FeatureKind.NOTICE.value,
        category=KMA_WEATHER_ALERT_CATEGORY,
        source_type=f"{KMA_PROVIDER_NAME}:{KMA_WEATHER_ALERT_DATASET_KEY}",
        source_natural_key=natural_key,
    )

    title_normalized = normalize_korean_text(alert.title) or alert.title

    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.NOTICE,
        name=title_normalized,
        coord=None,  # 특보는 region 단위 — 점 좌표 X. 호출자가 후속 enrichment 가능.
        address=Address(),  # 빈 주소 (region_name은 payload에).
        category=KMA_WEATHER_ALERT_CATEGORY,
        marker_icon=KMA_WEATHER_ALERT_MARKER_ICON,
        marker_color=KMA_WEATHER_ALERT_MARKER_COLOR,
        detail=NoticeDetail(
            feature_id=feature_id,
            notice_type=alert.alert_type,  # NoticeDetail validator가 normalize
            severity=KMA_ALERT_LEVEL_SEVERITY.get(alert.level or ""),
            valid_start_time=alert.effective_from or alert.issued_at,
            valid_end_time=alert.effective_until,
            source_agency=normalize_korean_text(alert.source_agency),
            payload={
                "domain": "weather",
                "region_code": region.region_code,
                "region_name": region.region_name,
                "level": alert.level,
                "kma_alert_id": alert.alert_id,
                "description": normalize_korean_text(alert.description),
            },
        ),
    )

    source_record = SourceRecord(
        provider=normalize_provider_name(KMA_PROVIDER_NAME),
        dataset_key=KMA_WEATHER_ALERT_DATASET_KEY,
        source_entity_type=_KMA_WEATHER_ALERT_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        raw_name=alert.title,
        # 특보는 region 단위 무좌표 notice — region명이 유일한 위치 단서다.
        # Dagster 주소 검증(ADR-046 missing_address)이 이 단서를 인정한다(T-219c).
        raw_address=region.region_name,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature, source_record=source_record, source_link=source_link
    )


def weather_alerts_to_notice_bundles(
    items: Iterable[KmaWeatherAlertItem],
    *,
    fetched_at: datetime,
) -> list[FeatureBundle]:
    """KMA 특보 → notice ``FeatureBundle`` (region 단위로 fan-out).

    Parameters
    ----------
    items
        ``python-kma-api``의 특보 typed model iterable.
    fetched_at
        provider 호출 시각 (KST aware).

    Returns
    -------
    list[FeatureBundle]
        한 alert × N region → N bundle. ``Feature(kind=notice, coord=None)`` +
        ``NoticeDetail`` (notice_type은 alias normalize, severity는 KMA level
        매핑, valid_start_time = effective_from 또는 issued_at).

    Notes
    -----
    - 좌표는 region 단위라 본 함수는 ``coord=None``. 호출자가 KMA region_code →
      대표 좌표 매핑이 필요하면 후속 enrichment로 추가.
    - notice_type alias 예: ``"호우주의보"`` → ``"heavy_rain_warning"`` /
      ``"폭염"`` → ``"heat_wave_warning"`` (`normalize_notice_type`).
    - alert_id의 `feature_id`는 region마다 다름 — `f"{alert_id}::{region_code}"`
      가 자연키.
    """
    bundles: list[FeatureBundle] = []
    for item in items:
        for region in item.regions:
            bundles.append(
                _alert_region_to_bundle(item, region, fetched_at=fetched_at)
            )
    return bundles


# =========================================================================
# 중기예보 (mid forecast) — getMidLandFcst (육상, 텍스트 + AM/PM) +
# getMidTa (기온, 일 최저/최고). ADR-010 forecast_style=mid / timeline=mid.
# =========================================================================

KMA_MID_FORECAST_DATASET_KEY: Final[str] = "kma_mid_forecast"
"""``WeatherValue.weather_domain`` = ``kma_mid_forecast`` dataset 식별자."""

_MID_ANNOUNCE_FMT: Final[str] = "%Y%m%d%H%M"
"""중기예보 ``tm_fc`` (발표시각) 형식 — ``"YYYYMMDDHHMM"`` 12자리."""

# (day_offset, period, hour_start, hour_end). 3~7일은 AM/PM 분리, 8~10일 단일.
# day_offset은 발표일(tm_fc) 기준 N일 후. period=None이면 종일.
_MID_LAND_PERIODS: Final[tuple[tuple[int, str | None, int, int], ...]] = (
    (3, "am", 0, 12),
    (3, "pm", 12, 24),
    (4, "am", 0, 12),
    (4, "pm", 12, 24),
    (5, "am", 0, 12),
    (5, "pm", 12, 24),
    (6, "am", 0, 12),
    (6, "pm", 12, 24),
    (7, "am", 0, 12),
    (7, "pm", 12, 24),
    (8, None, 0, 24),
    (9, None, 0, 24),
    (10, None, 0, 24),
)

_MID_TEMP_DAYS: Final[tuple[int, ...]] = (3, 4, 5, 6, 7, 8, 9, 10)
"""중기기온 일 최저/최고 제공 일자 (발표일 기준 N일 후)."""


@runtime_checkable
class KmaMidLandForecastItem(Protocol):
    """중기육상예보 (``getMidLandFcst``) 한 region row의 입력 shape.

    한 row(=한 ``reg_id``)가 3~10일 예보를 flat 필드로 담는다. 3~7일은 오전
    (``_am``)/오후(``_pm``) 분리, 8~10일은 단일. 본 모듈이 day-period별
    ``WeatherValue``로 fan-out한다.

    필드명은 ``python-kma-api`` 원천 camelCase(``wf3Am``)를 snake_case로 맞춘
    것 — 다르면 호출자가 dataclass adapter로 변환.
    """

    reg_id: str
    """예보구역 코드 (예: ``"11B00000"`` 서울/인천/경기)."""
    tm_fc: str
    """발표시각 ``"YYYYMMDDHHMM"`` 12자리 (``issued_at`` 산출)."""

    # 날씨 텍스트 (예: ``"맑음"`` / ``"구름많음"`` / ``"흐리고 비"``).
    wf_3_am: str | None
    wf_3_pm: str | None
    wf_4_am: str | None
    wf_4_pm: str | None
    wf_5_am: str | None
    wf_5_pm: str | None
    wf_6_am: str | None
    wf_6_pm: str | None
    wf_7_am: str | None
    wf_7_pm: str | None
    wf_8: str | None
    wf_9: str | None
    wf_10: str | None

    # 강수확률 % (정수).
    rn_st_3_am: int | None
    rn_st_3_pm: int | None
    rn_st_4_am: int | None
    rn_st_4_pm: int | None
    rn_st_5_am: int | None
    rn_st_5_pm: int | None
    rn_st_6_am: int | None
    rn_st_6_pm: int | None
    rn_st_7_am: int | None
    rn_st_7_pm: int | None
    rn_st_8: int | None
    rn_st_9: int | None
    rn_st_10: int | None


@runtime_checkable
class KmaMidTemperatureItem(Protocol):
    """중기기온예보 (``getMidTa``) 한 region row의 입력 shape.

    3~10일 일 최저(``ta_min_N``)/최고(``ta_max_N``) 기온. 본 모듈이 일자별
    ``TMN``/``TMX`` ``WeatherValue``로 fan-out.
    """

    reg_id: str
    """기온 예보구역 코드 (예: ``"11B10101"`` 서울)."""
    tm_fc: str
    """발표시각 ``"YYYYMMDDHHMM"``."""

    ta_min_3: int | None
    ta_max_3: int | None
    ta_min_4: int | None
    ta_max_4: int | None
    ta_min_5: int | None
    ta_max_5: int | None
    ta_min_6: int | None
    ta_max_6: int | None
    ta_min_7: int | None
    ta_max_7: int | None
    ta_min_8: int | None
    ta_max_8: int | None
    ta_min_9: int | None
    ta_max_9: int | None
    ta_min_10: int | None
    ta_max_10: int | None


def _parse_mid_announce(tm_fc: str) -> datetime:
    """중기예보 ``tm_fc`` (``"YYYYMMDDHHMM"``) → KST aware datetime."""
    if len(tm_fc) != 12:
        raise ValueError(f"중기예보 tm_fc 형식 오류 — {tm_fc!r} (12자리 필요).")
    naive = datetime.strptime(tm_fc, _MID_ANNOUNCE_FMT)
    return naive.replace(tzinfo=_KST)


def _mid_window(
    issued_at: datetime, day_offset: int, hour_start: int, hour_end: int
) -> tuple[datetime, datetime]:
    """발표일 자정 기준 N일 후 ``[hour_start, hour_end)`` 구간 (KST aware)."""
    base_midnight = issued_at.replace(hour=0, minute=0, second=0, microsecond=0)
    valid_from = base_midnight + timedelta(days=day_offset, hours=hour_start)
    valid_until = base_midnight + timedelta(days=day_offset, hours=hour_end)
    return (valid_from, valid_until)


def _mid_land_item_to_values(
    item: KmaMidLandForecastItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> list[WeatherValue]:
    """중기육상예보 한 region → day-period별 ``WeatherValue`` (SKY 텍스트 + POP)."""
    issued_at = _parse_mid_announce(item.tm_fc)
    values: list[WeatherValue] = []

    for day, period, h_start, h_end in _MID_LAND_PERIODS:
        suffix = f"_{period}" if period else ""
        wf_raw: str | None = getattr(item, f"wf_{day}{suffix}")
        pop_raw: int | None = getattr(item, f"rn_st_{day}{suffix}")
        valid_from, valid_until = _mid_window(issued_at, day, h_start, h_end)

        payload = {
            "reg_id": item.reg_id,
            "tm_fc": item.tm_fc,
            "day_offset": day,
            "period": period,
        }
        # valid_at = 구간 시작 — identity() 유일성 보장 (ADR-010 valid_from은
        # identity 제외라 day-period 구분용으로 valid_at을 박는다).
        if wf_raw is not None and wf_raw.strip():
            values.append(
                WeatherValue(
                    feature_id=feature_id,
                    provider=normalize_provider_name(KMA_PROVIDER_NAME),
                    weather_domain=WeatherDomain.KMA_MID_FORECAST,
                    forecast_style=ForecastStyle.MID,
                    timeline_bucket=TimelineBucket.MID,
                    metric_key="SKY",
                    source_metric_key=f"wf{day}{suffix}",
                    metric_name=KMA_METRIC_NAMES.get("SKY", "하늘상태"),
                    issued_at=issued_at,
                    valid_at=valid_from,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    value_text=wf_raw.strip(),
                    normalization_version="kma-v1.0",
                    payload=payload,
                    source_record_key=source_record_key,
                )
            )
        if pop_raw is not None:
            values.append(
                WeatherValue(
                    feature_id=feature_id,
                    provider=normalize_provider_name(KMA_PROVIDER_NAME),
                    weather_domain=WeatherDomain.KMA_MID_FORECAST,
                    forecast_style=ForecastStyle.MID,
                    timeline_bucket=TimelineBucket.MID,
                    metric_key="POP",
                    source_metric_key=f"rnSt{day}{suffix}",
                    metric_name=KMA_METRIC_NAMES.get("POP", "강수확률"),
                    unit=KMA_METRIC_UNITS.get("POP", "%"),
                    issued_at=issued_at,
                    valid_at=valid_from,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    value_number=Decimal(pop_raw),
                    normalization_version="kma-v1.0",
                    payload=payload,
                    source_record_key=source_record_key,
                )
            )
    return values


def _mid_temp_item_to_values(
    item: KmaMidTemperatureItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> list[WeatherValue]:
    """중기기온예보 한 region → 일자별 ``TMN``/``TMX`` ``WeatherValue``."""
    issued_at = _parse_mid_announce(item.tm_fc)
    values: list[WeatherValue] = []

    for day in _MID_TEMP_DAYS:
        valid_from, valid_until = _mid_window(issued_at, day, 0, 24)
        payload = {"reg_id": item.reg_id, "tm_fc": item.tm_fc, "day_offset": day}
        for metric_key, attr in (("TMN", f"ta_min_{day}"), ("TMX", f"ta_max_{day}")):
            raw: int | None = getattr(item, attr)
            if raw is None:
                continue
            values.append(
                WeatherValue(
                    feature_id=feature_id,
                    provider=normalize_provider_name(KMA_PROVIDER_NAME),
                    weather_domain=WeatherDomain.KMA_MID_FORECAST,
                    forecast_style=ForecastStyle.MID,
                    timeline_bucket=TimelineBucket.MID,
                    metric_key=metric_key,
                    source_metric_key=attr,
                    metric_name=KMA_METRIC_NAMES.get(metric_key),
                    unit=KMA_METRIC_UNITS.get(metric_key, "deg_c"),
                    issued_at=issued_at,
                    valid_at=valid_from,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    value_number=Decimal(raw),
                    normalization_version="kma-v1.0",
                    payload=payload,
                    source_record_key=source_record_key,
                )
            )
    return values


def mid_land_forecast_to_weather_values(
    items: Iterable[KmaMidLandForecastItem],
    *,
    feature_id: str,
    source_record_key: str | None = None,
) -> list[WeatherValue]:
    """KMA 중기육상예보 items → ``list[WeatherValue]`` (SKY 텍스트 + POP).

    한 region row가 3~10일 예보를 담고, 본 함수가 day-period별로 fan-out한다.
    3~7일은 AM/PM 2건씩, 8~10일은 1건. 각 day-period마다 날씨 텍스트(``SKY``,
    ``value_text``) + 강수확률(``POP``, ``value_number``)을 만든다. AM/PM 구간은
    ``valid_from``/``valid_until``로, identity 유일성은 ``valid_at``(구간 시작)로.

    Parameters
    ----------
    items
        ``python-kma-api`` 중기육상예보 typed model iterable
        (``KmaMidLandForecastItem`` Protocol).
    feature_id
        weather kind ``Feature`` ID. 호출자가 예보구역→Feature 매핑 사전 결정.
    source_record_key
        provider raw 추적용 (``make_source_record_key`` 결과, 권장).

    Returns
    -------
    list[WeatherValue]
        빈 텍스트/None metric은 생략 — ``len`` 가변. ``forecast_style=mid`` /
        ``timeline_bucket=mid`` / ``weather_domain=kma_mid_forecast``.

    Raises
    ------
    ValueError
        ``tm_fc`` 형식 위반 (12자리 아님).

    Notes
    -----
    - 좌표는 예보구역 단위 — 본 함수는 좌표를 다루지 않는다 (값만).
    - 중기 날씨 텍스트는 표준 ``SKY``에 ``value_text``로 담는다 (단기처럼 code가
      아님) — 원천 필드는 ``source_metric_key='wf3Am'`` 등으로 보존.
    - 기온(``TMN``/``TMX``)은 별도 endpoint(``getMidTa``) →
      ``mid_temperature_to_weather_values``.
    """
    values: list[WeatherValue] = []
    for item in items:
        values.extend(
            _mid_land_item_to_values(
                item, feature_id=feature_id, source_record_key=source_record_key
            )
        )
    return values


def mid_temperature_to_weather_values(
    items: Iterable[KmaMidTemperatureItem],
    *,
    feature_id: str,
    source_record_key: str | None = None,
) -> list[WeatherValue]:
    """KMA 중기기온예보 items → ``list[WeatherValue]`` (일 ``TMN``/``TMX``).

    한 region row가 3~10일 최저/최고 기온을 담고, 본 함수가 일자별로 fan-out.
    각 일자에 ``TMN``(최저) + ``TMX``(최고) ``WeatherValue`` (종일 구간).

    Parameters
    ----------
    items
        ``python-kma-api`` 중기기온 typed model iterable
        (``KmaMidTemperatureItem`` Protocol).
    feature_id
        weather kind ``Feature`` ID.
    source_record_key
        provider raw 추적용 (권장).

    Returns
    -------
    list[WeatherValue]
        ``forecast_style=mid`` / ``timeline_bucket=mid``. None 기온은 생략.

    Raises
    ------
    ValueError
        ``tm_fc`` 형식 위반.
    """
    values: list[WeatherValue] = []
    for item in items:
        values.extend(
            _mid_temp_item_to_values(
                item, feature_id=feature_id, source_record_key=source_record_key
            )
        )
    return values


