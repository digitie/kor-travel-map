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
    from sqlalchemy import RowMapping
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
    provider: str | None = None
    weather_domain: str | None = None


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
    issued_at, valid_at, observed_at,
    provider, weather_domain
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

# KMA-forecast tier 술어 — 단기/초단기/중기 예보를 만드는 격자 anchor.
# `python-kma-api`의 nowcast/ultra_short/short/mid가 SKY/POP/TMN/TMX(+TMP/T1H)를
# 모두 싣는다. (#498) 휴게소 관측(observed)·airkorea 대기질을 제외해야 단순 "가장
# 가까운 weather"가 더 가까운 관측만 잡고 예보를 못 잡는 문제를 막는다.
_KMA_FORECAST_PREDICATE: Final[str] = (
    "w.provider = 'python-kma-api' "
    "AND w.forecast_style IN ('nowcast', 'ultra_short', 'short', 'mid')"
)

# observed-temp tier 술어 — 관측 기온 anchor (KREX 휴게소 등 forecast_style=observed).
# (#497) 휴게소는 관측 기온을 T1H로 적재한다. 관측 기온은 예보 anchor를 그림자로
# 가리지 않고 별도 row로 **증강**된다(병합 키에 forecast_style 포함).
_OBSERVED_TEMP_PREDICATE: Final[str] = (
    "w.forecast_style = 'observed' AND w.metric_key IN ('T1H', 'TMP')"
)


def _nearest_anchor_sql(exists_predicate: str) -> str:
    """반경 내 가장 가까운(KNN) anchor feature 1건을 찾는 SQL.

    #499: 과거 구현은 ``SELECT DISTINCT feature_id FROM feature_weather_values``
    CTE(≈30M row full scan)를 **공간 좁히기 전에** 먼저 만들었다. 이를 GiST 후보
    우선(target coord_5179 → ``ST_DWithin`` 반경 술어 → ``<->`` KNN 정렬)으로
    재작성하고, weather 보유 여부는 ``EXISTS`` 상관 서브쿼리로 확인한다. 결정적
    tie-break으로 ``f.feature_id``를 정렬 말미에 둔다(같은 좌표 다수 시 안정).
    ADR-012: STORED ``coord_5179`` 대상, ``x_extension`` qualify, ST_Transform 금지.
    """
    return f"""
WITH target AS (
    SELECT coord_5179
    FROM feature.features
    WHERE feature_id = :feature_id
      AND deleted_at IS NULL
      AND coord_5179 IS NOT NULL
)
SELECT f.feature_id
FROM feature.features AS f, target AS t
WHERE f.deleted_at IS NULL
  AND f.coord_5179 IS NOT NULL
  AND x_extension.ST_DWithin(
        f.coord_5179, t.coord_5179, CAST(:radius_m AS double precision)
      )
  AND EXISTS (
        SELECT 1
        FROM feature.feature_weather_values AS w
        WHERE w.feature_id = f.feature_id
          {exists_predicate}
      )
ORDER BY f.coord_5179 OPERATOR(x_extension.<->) t.coord_5179, f.feature_id
LIMIT 1
"""


# 반경 내 가장 가까운 weather 보유 feature (종류 무관) — 완전 미적재 지역 폴백.
_NEAREST_WEATHER_SQL: Final[str] = _nearest_anchor_sql("")

# 반경 내 가장 가까운 KMA-forecast anchor — SKY/POP/TMN/TMX(+TMP/T1H) 보유.
_NEAREST_KMA_FORECAST_SQL: Final[str] = _nearest_anchor_sql(
    f"AND {_KMA_FORECAST_PREDICATE}"
)

# 반경 내 가장 가까운 관측 기온 anchor — observed T1H/TMP 보유(휴게소 등).
_NEAREST_OBSERVED_TEMP_SQL: Final[str] = _nearest_anchor_sql(
    f"AND {_OBSERVED_TEMP_PREDICATE}"
)


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

    폴백 병합 (#498) — 자기 weather row가 기온을 못 채우는 농촌/비격자 feature는
    SOURCE TIER별로 반경 내 가장 가까운 anchor를 합친다:

    1. feature 자체 row.
    2. KMA-forecast tier — 반경 내 가장 가까운 KMA 예보 anchor의 SKY/POP/TMN/TMX
       (+TMP/T1H). (forecast_style, metric_key) 키로 자기 row를 가리지 않는 것만 추가
       → KMA anchor가 반경 안이면 SKY/POP/TMN/TMX가 **항상** 붙는다.
    3. observed tier — 반경 내 가장 가까운 관측 기온 anchor(휴게소 등, #497). 관측
       T1H는 (forecast_style, metric_key)가 KMA 예보 기온과 달라 **증강**으로 추가되며
       KMA 단기/중기 기온을 그림자로 가리지 않는다. KMA anchor가 반경에 없을 때만
       관측이 유일한 기온 source가 된다.

    card.feature_id는 요청 feature_id를 유지한다.
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

    async def _anchor_rows(sql: str) -> list[RowMapping]:
        anchor_id = (
            await session.execute(text(sql), params)
        ).scalar_one_or_none()
        if anchor_id is None or str(anchor_id) == feature_id:
            return []
        return list(
            (
                await session.execute(
                    text(_CARD_SQL), {"feature_id": str(anchor_id), "asof": asof}
                )
            )
            .mappings()
            .all()
        )

    def _merge(extra: list[RowMapping]) -> None:
        """(forecast_style, metric_key) 키로 아직 없는 row만 추가 — 기존 row 보존."""
        seen = {(r["forecast_style"], r["metric_key"]) for r in rows}
        for row in extra:
            key = (row["forecast_style"], row["metric_key"])
            if key not in seen:
                rows.append(row)
                seen.add(key)

    # 자기 row에 기온(T1H/TMP)이 없으면 tier 폴백. KMA 예보 tier를 먼저 병합해
    # SKY/POP/TMN/TMX를 우선 확보하고, 그 다음 관측 기온 tier로 증강한다.
    if not any(r["metric_key"] in ("T1H", "TMP") for r in rows):
        _merge(await _anchor_rows(_NEAREST_KMA_FORECAST_SQL))
        _merge(await _anchor_rows(_NEAREST_OBSERVED_TEMP_SQL))
    # 어느 tier도 반경에 없으면(완전 미적재 지역) 가장 가까운 임의 weather로 폴백(빈 카드 회피).
    if not rows:
        _merge(await _anchor_rows(_NEAREST_WEATHER_SQL))
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
            provider=row["provider"],
            weather_domain=row["weather_domain"],
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
