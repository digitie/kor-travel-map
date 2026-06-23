"""``kortravelmap.infra.weather_repo`` — weather value 적재/조회 + weather card (T-213e).

``WeatherValue`` DTO(ADR-010)를 ``feature.feature_weather_values``에 적재하고,
feature별 weather card(forecast_style/metric_key별 최신값 + freshness)를 만든다.
PK는 결정적 ``weather_value_key``(`make_weather_value_key`)라 재적재가 멱등 upsert다.
raw SQL은 본 모듈에 모음(ADR-004). commit은 호출자 책임.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

from kortravelmap.core.ids import make_weather_value_key
from kortravelmap.dto._time import kst_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto.weather import WeatherValue

__all__ = [
    "WeatherMetric",
    "WeatherCard",
    "DEFAULT_WEATHER_FRESHNESS_SECONDS",
    "load_weather_values",
    "build_weather_card",
]

# 최신 weather가 이 시간보다 오래되면 card.is_stale=True (nowcast/단기예보 갱신 주기 고려).
DEFAULT_WEATHER_FRESHNESS_SECONDS: Final[int] = 6 * 60 * 60


@dataclass(frozen=True)
class WeatherMetric:
    """weather card의 metric 1건 (forecast_style × metric_key 최신값)."""

    forecast_style: str
    metric_key: str
    metric_name: str | None
    timeline_bucket: str | None
    value_number: Decimal | None
    value_text: str | None
    unit: str | None
    severity: str | None
    issued_at: datetime | None
    valid_at: datetime | None
    observed_at: datetime | None


@dataclass(frozen=True)
class WeatherCard:
    """feature 1건의 weather card — forecast_style별 최신 metric 묶음 + freshness."""

    feature_id: str
    asof: datetime | None
    source_styles: list[str]
    metrics: list[WeatherMetric]
    latest_at: datetime | None
    is_stale: bool


_INSERT_SQL: Final[str] = """
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider, weather_domain, forecast_style,
    timeline_bucket, metric_key, metric_name, source_metric_key, source_metric_name,
    value_number, value_text, unit, severity, issued_at, valid_at, valid_from,
    valid_until, observed_at, normalization_version, payload, source_record_key,
    collected_at, updated_at
) VALUES (
    :weather_value_key, :feature_id, :provider, :weather_domain, :forecast_style,
    :timeline_bucket, :metric_key, :metric_name, :source_metric_key, :source_metric_name,
    :value_number, :value_text, :unit, :severity, :issued_at, :valid_at, :valid_from,
    :valid_until, :observed_at, :normalization_version, CAST(:payload AS jsonb),
    :source_record_key, :collected_at, now()
)
ON CONFLICT (weather_value_key) DO UPDATE SET
    value_number = EXCLUDED.value_number,
    value_text = EXCLUDED.value_text,
    unit = EXCLUDED.unit,
    severity = EXCLUDED.severity,
    metric_name = EXCLUDED.metric_name,
    timeline_bucket = EXCLUDED.timeline_bucket,
    valid_from = EXCLUDED.valid_from,
    valid_until = EXCLUDED.valid_until,
    normalization_version = EXCLUDED.normalization_version,
    payload = EXCLUDED.payload,
    source_record_key = EXCLUDED.source_record_key,
    collected_at = EXCLUDED.collected_at,
    updated_at = now()
"""

_CARD_SQL: Final[str] = """
SELECT DISTINCT ON (forecast_style, metric_key)
    forecast_style, metric_key, metric_name, timeline_bucket,
    value_number, value_text, unit, severity,
    issued_at, valid_at, observed_at
FROM feature.feature_weather_values
WHERE feature_id = :feature_id
  AND (
    CAST(:asof AS timestamptz) IS NULL
    OR COALESCE(valid_at, observed_at, issued_at) <= CAST(:asof AS timestamptz)
  )
ORDER BY
    forecast_style, metric_key,
    COALESCE(valid_at, observed_at, issued_at) DESC NULLS LAST
"""

# KMA weather는 격자(≈5km) 단위라 적재된 격자에 속한 place feature에만 붙는다.
# 그 외 feature는 자기 weather_value가 없으므로, 반경 내 weather 보유한 가장 가까운
# feature(=가장 가까운 격자)의 값으로 폴백한다("위치에 맞춘" 지역 날씨). coord_5179
# (m, STORED generated)로 KNN(ADR-012: ST_Transform 술어 금지, PostGIS는 x_extension
# 스키마 qualify — #410/#411).
_NEAREST_WEATHER_RADIUS_M: Final[float] = 50_000.0

_NEAREST_WEATHER_SQL: Final[str] = """
WITH target AS (
    SELECT coord_5179
    FROM feature.features
    WHERE feature_id = :feature_id
      AND deleted_at IS NULL
      AND coord_5179 IS NOT NULL
),
weather_features AS (
    SELECT DISTINCT feature_id FROM feature.feature_weather_values
)
SELECT f.feature_id
FROM target AS t
JOIN weather_features AS wf ON TRUE
JOIN feature.features AS f
  ON f.feature_id = wf.feature_id
 AND f.deleted_at IS NULL
 AND f.coord_5179 IS NOT NULL
 AND x_extension.ST_DWithin(
       f.coord_5179, t.coord_5179, CAST(:radius_m AS double precision)
     )
ORDER BY f.coord_5179 OPERATOR(x_extension.<->) t.coord_5179
LIMIT 1
"""

# 기온/단기예보(KMA)는 airkorea 대기질 측정소보다 성기게 적재돼, 단순 "가장 가까운
# weather"는 더 가까운 대기질 지점만 잡고 기온은 못 잡는 경우가 많다. 기온(T1H/TMP)을
# 가진 가장 가까운 지점을 따로 찾아 병합한다(반경 동일).
_NEAREST_TEMP_SQL: Final[str] = """
WITH target AS (
    SELECT coord_5179
    FROM feature.features
    WHERE feature_id = :feature_id
      AND deleted_at IS NULL
      AND coord_5179 IS NOT NULL
),
temp_features AS (
    SELECT DISTINCT feature_id
    FROM feature.feature_weather_values
    WHERE metric_key IN ('T1H', 'TMP')
)
SELECT f.feature_id
FROM target AS t
JOIN temp_features AS wf ON TRUE
JOIN feature.features AS f
  ON f.feature_id = wf.feature_id
 AND f.deleted_at IS NULL
 AND f.coord_5179 IS NOT NULL
 AND x_extension.ST_DWithin(
       f.coord_5179, t.coord_5179, CAST(:radius_m AS double precision)
     )
ORDER BY f.coord_5179 OPERATOR(x_extension.<->) t.coord_5179
LIMIT 1
"""


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _weather_value_params(value: WeatherValue) -> dict[str, Any]:
    key = make_weather_value_key(
        feature_id=value.feature_id,
        provider=value.provider,
        weather_domain=_enum_value(value.weather_domain),
        forecast_style=_enum_value(value.forecast_style),
        metric_key=value.metric_key,
        issued_at=value.issued_at,
        valid_at=value.valid_at,
        observed_at=value.observed_at,
    )
    return {
        "weather_value_key": key,
        "feature_id": value.feature_id,
        "provider": value.provider,
        "weather_domain": _enum_value(value.weather_domain),
        "forecast_style": _enum_value(value.forecast_style),
        "timeline_bucket": (
            _enum_value(value.timeline_bucket)
            if value.timeline_bucket is not None
            else None
        ),
        "metric_key": value.metric_key,
        "metric_name": value.metric_name,
        "source_metric_key": value.source_metric_key,
        "source_metric_name": value.source_metric_name,
        "value_number": value.value_number,
        "value_text": value.value_text,
        "unit": value.unit,
        "severity": value.severity,
        "issued_at": value.issued_at,
        "valid_at": value.valid_at,
        "valid_from": value.valid_from,
        "valid_until": value.valid_until,
        "observed_at": value.observed_at,
        "normalization_version": value.normalization_version,
        "payload": json.dumps(value.payload, ensure_ascii=False, default=str),
        "source_record_key": value.source_record_key,
        "collected_at": value.collected_at,
    }


async def load_weather_values(
    session: AsyncSession, values: Iterable[WeatherValue]
) -> int:
    """``WeatherValue`` 들을 멱등 upsert 적재한다. 적재 건수 반환 (commit은 호출자).

    PK ``weather_value_key``가 identity tuple(ADR-010)이라 같은 값 재적재는 갱신.
    weather kind ``feature``가 먼저 존재해야 한다(FK).
    """
    params = [_weather_value_params(v) for v in values]
    if not params:
        return 0
    await session.execute(text(_INSERT_SQL), params)
    return len(params)


async def build_weather_card(
    session: AsyncSession,
    *,
    feature_id: str,
    asof: datetime | None = None,
    freshness_seconds: int = DEFAULT_WEATHER_FRESHNESS_SECONDS,
) -> WeatherCard:
    """feature의 weather card — forecast_style × metric_key별 최신값 + freshness.

    ``asof``가 주어지면 그 시점 이하 값만(미래 예보 제외). 각 (forecast_style,
    metric_key)에서 ``COALESCE(valid_at, observed_at, issued_at)`` 최신 1건을 고른다
    (``DISTINCT ON``). ``is_stale``은 최신 시각이 ``asof``(또는 now) 기준
    ``freshness_seconds``를 넘으면 True. source trace는 ``source_styles``로 노출.
    """
    rows = list(
        (
            await session.execute(
                text(_CARD_SQL), {"feature_id": feature_id, "asof": asof}
            )
        )
        .mappings()
        .all()
    )
    params = {"feature_id": feature_id, "radius_m": _NEAREST_WEATHER_RADIUS_M}
    # 기온(T1H/TMP)이 없으면 반경 내 가장 가까운 기온(KMA) 지점의 forecast 값을 병합
    # 한다(자체 대기질 등 기존 metric은 유지). card.feature_id는 요청 feature_id 유지.
    if not any(r["metric_key"] in ("T1H", "TMP") for r in rows):
        temp_id = (
            await session.execute(text(_NEAREST_TEMP_SQL), params)
        ).scalar_one_or_none()
        if temp_id is not None and str(temp_id) != feature_id:
            extra = (
                await session.execute(
                    text(_CARD_SQL), {"feature_id": str(temp_id), "asof": asof}
                )
            ).mappings().all()
            seen = {(r["forecast_style"], r["metric_key"]) for r in rows}
            for row in extra:
                key = (row["forecast_style"], row["metric_key"])
                if key not in seen:
                    rows.append(row)
                    seen.add(key)
    # 근처에 기온도 없으면(완전 미적재 지역) 가장 가까운 임의 weather로 폴백(빈 카드 회피).
    if not rows:
        any_id = (
            await session.execute(text(_NEAREST_WEATHER_SQL), params)
        ).scalar_one_or_none()
        if any_id is not None and str(any_id) != feature_id:
            rows = list(
                (
                    await session.execute(
                        text(_CARD_SQL), {"feature_id": str(any_id), "asof": asof}
                    )
                )
                .mappings()
                .all()
            )
    metrics = [
        WeatherMetric(
            forecast_style=str(row["forecast_style"]),
            metric_key=str(row["metric_key"]),
            metric_name=row["metric_name"],
            timeline_bucket=row["timeline_bucket"],
            value_number=row["value_number"],
            value_text=row["value_text"],
            unit=row["unit"],
            severity=row["severity"],
            issued_at=row["issued_at"],
            valid_at=row["valid_at"],
            observed_at=row["observed_at"],
        )
        for row in rows
    ]
    source_styles = sorted({m.forecast_style for m in metrics})
    candidates = [
        ts
        for m in metrics
        if (ts := (m.valid_at or m.observed_at or m.issued_at)) is not None
    ]
    latest_at = max(candidates) if candidates else None
    reference = asof if asof is not None else kst_now()
    is_stale = (
        latest_at is None
        or (reference - latest_at).total_seconds() > freshness_seconds
    )
    return WeatherCard(
        feature_id=feature_id,
        asof=asof,
        source_styles=source_styles,
        metrics=metrics,
        latest_at=latest_at,
        is_stale=is_stale,
    )
