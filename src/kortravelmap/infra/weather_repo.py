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
from datetime import datetime, timedelta
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
    "WeatherAnchor",
    "WeatherValueTimelineRow",
    "WeatherAlertHistoryRow",
    "DEFAULT_WEATHER_FRESHNESS_SECONDS",
    "DEFAULT_WEATHER_HISTORY_RETENTION_DAYS",
    "load_weather_values",
    "build_weather_card",
    "list_weather_values",
    "weather_history_floor",
    "nearest_weather_feature_for_coordinate",
    "nearest_weather_feature_for_feature",
    "list_kma_weather_alert_history",
]

# 최신 weather가 이 시간보다 오래되면 card.is_stale=True (nowcast/단기예보 갱신 주기 고려).
DEFAULT_WEATHER_FRESHNESS_SECONDS: Final[int] = 6 * 60 * 60
DEFAULT_WEATHER_HISTORY_RETENTION_DAYS: Final[int] = 365 * 3
"""REST weather history 기본 보존/조회 지평선(3년)."""


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


@dataclass(frozen=True)
class WeatherAnchor:
    """좌표/feature 기준으로 선택된 weather anchor feature."""

    feature_id: str
    name: str
    lon: float | None
    lat: float | None
    distance_m: float | None = None


@dataclass(frozen=True)
class WeatherValueTimelineRow:
    """외부 REST timeline API용 weather value row."""

    weather_value_key: str
    feature_id: str
    provider: str
    weather_domain: str
    forecast_style: str
    timeline_bucket: str | None
    metric_key: str
    metric_name: str | None
    value_number: Decimal | None
    value_text: str | None
    unit: str | None
    severity: str | None
    issued_at: datetime | None
    valid_at: datetime | None
    valid_from: datetime | None
    valid_until: datetime | None
    observed_at: datetime | None
    collected_at: datetime
    source_record_key: str | None


@dataclass(frozen=True)
class WeatherAlertHistoryRow:
    """KMA weather alert source history row."""

    source_record_key: str
    feature_id: str | None
    feature_name: str | None
    region_code: str | None
    region_name: str | None
    phenomenon: str | None
    alert_type: str | None
    level: str | None
    title: str | None
    description: str | None
    issued_at: datetime | None
    effective_from: datetime | None
    effective_until: datetime | None
    source_agency: str | None
    fetched_at: datetime | None
    imported_at: datetime | None
    last_seen_at: datetime | None
    payload: dict[str, Any]


# weather semantic identity tuple — alembic 0060 ``uq_weather_value_identity``
# (NULLS NOT DISTINCT) index 컬럼과 **정확히 동일**하고, ``WeatherValue.identity()``·
# ``make_weather_value_key`` 축과도 같다(timeline_bucket 제외). 단일 정본으로 두어
# writer conflict target이 DB unique index와 항상 일치하도록 강제한다(T-VN-17).
_WEATHER_IDENTITY_COLUMNS: Final[tuple[str, ...]] = (
    "feature_id",
    "provider",
    "weather_domain",
    "forecast_style",
    "metric_key",
    "issued_at",
    "valid_at",
    "observed_at",
)
_WEATHER_CONFLICT_TARGET: Final[str] = ", ".join(_WEATHER_IDENTITY_COLUMNS)

# T-VN-17: ON CONFLICT 대상을 PK(weather_value_key 해시)에서 semantic tuple index로
# 전환한다. 해시 PK는 tz 표기 차이로 같은 instant가 다른 key를 받는 구멍이 있었고,
# semantic UNIQUE(NULLS NOT DISTINCT)가 참 무결성 경계다. update-wins(ADR-072):
# 같은 semantic tuple 재적재는 최신 값/payload/source로 갱신한다(weather_value_key는
# 기존 행 값을 유지).
#
# 수용된 last-writer-wins(price writer와 동일 정책): known_at 가드가 없어 순서가
# 뒤바뀐/backfill 재적재가 더 최신 값을 덮어쓸 수 있다. in-order 수집에는 무해하고
# price도 같은 blind upsert다(parity). backfill 역행이 문제가 되면 향후
# ``... DO UPDATE SET ... WHERE EXCLUDED.collected_at >=
# feature_weather_values.collected_at`` 가드를 추가하는 옵션이 있으나 지금은
# 범위 밖(price 대칭 유지).
_INSERT_SQL: Final[str] = f"""
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
ON CONFLICT ({_WEATHER_CONFLICT_TARGET}) DO UPDATE SET
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

    공개 weather 표면(card/forecast)이 anchor feature_id를 응답에 노출하므로
    target·anchor 모두 ADR-067 ``feature.public_features`` projection에서만 찾는다
    — 비공개 feature는 anchor가 될 수 없고, 비공개 target은 빈 결과가 된다(F-1).
    """
    return f"""
WITH target AS (
    SELECT coord_5179
    FROM feature.public_features
    WHERE feature_id = :feature_id
      AND coord_5179 IS NOT NULL
)
SELECT f.feature_id
FROM feature.public_features AS f, target AS t
WHERE f.coord_5179 IS NOT NULL
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

_LIST_WEATHER_VALUES_SQL: Final[str] = """
SELECT
    weather_value_key, feature_id, provider, weather_domain, forecast_style,
    timeline_bucket, metric_key, metric_name, value_number, value_text, unit,
    severity, issued_at, valid_at, valid_from, valid_until, observed_at,
    collected_at, source_record_key
FROM feature.feature_weather_values
WHERE feature_id = :feature_id
  AND (
    CAST(:forecast_styles AS text[]) IS NULL
    OR forecast_style = ANY(CAST(:forecast_styles AS text[]))
  )
  AND (
    CAST(:weather_domains AS text[]) IS NULL
    OR weather_domain = ANY(CAST(:weather_domains AS text[]))
  )
  AND (
    CAST(:metric_keys AS text[]) IS NULL
    OR metric_key = ANY(CAST(:metric_keys AS text[]))
  )
  AND (
    CAST(:history_from AS timestamptz) IS NULL
    OR COALESCE(issued_at, observed_at, valid_at, collected_at)
       >= CAST(:history_from AS timestamptz)
  )
  AND (
    CAST(:issued_from AS timestamptz) IS NULL
    OR issued_at >= CAST(:issued_from AS timestamptz)
  )
  AND (
    CAST(:issued_to AS timestamptz) IS NULL
    OR issued_at <= CAST(:issued_to AS timestamptz)
  )
  AND (
    CAST(:valid_from_filter AS timestamptz) IS NULL
    OR COALESCE(valid_until, valid_at, observed_at, issued_at)
       >= CAST(:valid_from_filter AS timestamptz)
  )
  AND (
    CAST(:valid_to_filter AS timestamptz) IS NULL
    OR COALESCE(valid_at, valid_from, observed_at, issued_at)
       <= CAST(:valid_to_filter AS timestamptz)
  )
ORDER BY
    issued_at DESC NULLS LAST,
    observed_at DESC NULLS LAST,
    valid_at ASC NULLS LAST,
    valid_from ASC NULLS LAST,
    forecast_style,
    metric_key,
    weather_value_key
LIMIT :limit
"""

_NEAREST_WEATHER_BY_COORDINATE_SQL: Final[str] = f"""
WITH input AS (
    SELECT x_extension.ST_Transform(
        x_extension.ST_SetSRID(
            x_extension.ST_MakePoint(
                CAST(:lon AS double precision),
                CAST(:lat AS double precision)
            ),
            4326
        ),
        5179
    ) AS geom_5179
)
SELECT
    f.feature_id,
    f.name,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    x_extension.ST_Distance(f.coord_5179, input.geom_5179) AS distance_m
FROM feature.public_features AS f, input
WHERE f.coord IS NOT NULL
  AND f.coord_5179 IS NOT NULL
  AND x_extension.ST_DWithin(
        f.coord_5179, input.geom_5179, CAST(:radius_m AS double precision)
      )
  AND EXISTS (
        SELECT 1
        FROM feature.feature_weather_values AS w
        WHERE w.feature_id = f.feature_id
          AND {_KMA_FORECAST_PREDICATE}
      )
ORDER BY f.coord_5179 OPERATOR(x_extension.<->) input.geom_5179, f.feature_id
LIMIT 1
"""

_NEAREST_WEATHER_BY_FEATURE_SQL: Final[str] = f"""
WITH target AS (
    SELECT coord_5179
    FROM feature.public_features
    WHERE feature_id = :feature_id
      AND coord_5179 IS NOT NULL
)
SELECT
    f.feature_id,
    f.name,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    x_extension.ST_Distance(f.coord_5179, target.coord_5179) AS distance_m
FROM feature.public_features AS f, target
WHERE f.coord IS NOT NULL
  AND f.coord_5179 IS NOT NULL
  AND x_extension.ST_DWithin(
        f.coord_5179, target.coord_5179, CAST(:radius_m AS double precision)
      )
  AND EXISTS (
        SELECT 1
        FROM feature.feature_weather_values AS w
        WHERE w.feature_id = f.feature_id
          AND {_KMA_FORECAST_PREDICATE}
      )
ORDER BY f.coord_5179 OPERATOR(x_extension.<->) target.coord_5179, f.feature_id
LIMIT 1
"""

_KMA_WEATHER_ALERT_HISTORY_SQL: Final[str] = """
WITH alert_records AS (
    SELECT
        sr.source_record_key,
        f.feature_id,
        f.name AS feature_name,
        sr.raw_data,
        sr.raw_data->>'region_code' AS region_code,
        sr.raw_data->>'region_name' AS region_name,
        sr.raw_data->>'phenomenon' AS phenomenon,
        sr.raw_data->>'alert_type' AS alert_type,
        sr.raw_data->>'level' AS level,
        sr.raw_data->>'title' AS title,
        sr.raw_data->>'description' AS description,
        CASE
          WHEN NULLIF(sr.raw_data->>'issued_at', '') IS NULL THEN sr.fetched_at
          ELSE CAST(sr.raw_data->>'issued_at' AS timestamptz)
        END AS issued_at,
        CASE
          WHEN NULLIF(sr.raw_data->>'effective_from', '') IS NULL THEN NULL
          ELSE CAST(sr.raw_data->>'effective_from' AS timestamptz)
        END AS effective_from,
        CASE
          WHEN NULLIF(sr.raw_data->>'effective_until', '') IS NULL THEN NULL
          ELSE CAST(sr.raw_data->>'effective_until' AS timestamptz)
        END AS effective_until,
        sr.raw_data->>'source_agency' AS source_agency,
        sr.fetched_at,
        sr.imported_at,
        sr.last_seen_at
    FROM provider_sync.source_records AS sr
    LEFT JOIN provider_sync.source_links AS sl
      ON sl.source_entity_key = sr.source_entity_key
     AND sl.is_primary_source
    -- 공개 projection에만 조인: 비공개 anchor의 alert row는 살아남되
    -- feature_id/feature_name은 NULL로 떨어진다 (ADR-067 / T-VN-04).
    LEFT JOIN feature.public_features AS f
      ON f.feature_id = sl.feature_id
    WHERE sr.provider = 'python-kma-api'
      AND sr.dataset_key = 'kma_weather_alerts'
      AND sr.source_entity_type = 'weather_alert'
)
SELECT *
FROM alert_records
WHERE (
    CAST(:region_code AS text) IS NULL
    OR region_code = CAST(:region_code AS text)
  )
  AND (
    CAST(:phenomenon AS text) IS NULL
    OR phenomenon = CAST(:phenomenon AS text)
  )
  AND (
    CAST(:level AS text) IS NULL
    OR level = CAST(:level AS text)
  )
  AND (
    CAST(:history_from AS timestamptz) IS NULL
    OR COALESCE(issued_at, fetched_at, imported_at)
       >= CAST(:history_from AS timestamptz)
  )
  AND (
    CAST(:issued_from AS timestamptz) IS NULL
    OR issued_at >= CAST(:issued_from AS timestamptz)
  )
  AND (
    CAST(:issued_to AS timestamptz) IS NULL
    OR issued_at <= CAST(:issued_to AS timestamptz)
  )
ORDER BY issued_at DESC NULLS LAST, source_record_key DESC
LIMIT :limit
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


def weather_history_floor(
    *,
    now: datetime | None = None,
    retention_days: int = DEFAULT_WEATHER_HISTORY_RETENTION_DAYS,
) -> datetime:
    """REST weather history 기본 lower bound를 계산한다."""
    return (now or kst_now()) - timedelta(days=max(retention_days, 1))


def _filter_values(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized = [value for value in values if value]
    return normalized or None


def _timeline_row(row: RowMapping) -> WeatherValueTimelineRow:
    return WeatherValueTimelineRow(
        weather_value_key=str(row["weather_value_key"]),
        feature_id=str(row["feature_id"]),
        provider=str(row["provider"]),
        weather_domain=str(row["weather_domain"]),
        forecast_style=str(row["forecast_style"]),
        timeline_bucket=row["timeline_bucket"],
        metric_key=str(row["metric_key"]),
        metric_name=row["metric_name"],
        value_number=row["value_number"],
        value_text=row["value_text"],
        unit=row["unit"],
        severity=row["severity"],
        issued_at=row["issued_at"],
        valid_at=row["valid_at"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        observed_at=row["observed_at"],
        collected_at=row["collected_at"],
        source_record_key=row["source_record_key"],
    )


async def list_weather_values(
    session: AsyncSession,
    *,
    feature_id: str,
    forecast_styles: Iterable[str] | None = None,
    weather_domains: Iterable[str] | None = None,
    metric_keys: Iterable[str] | None = None,
    history_from: datetime | None = None,
    issued_from: datetime | None = None,
    issued_to: datetime | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    limit: int = 500,
) -> list[WeatherValueTimelineRow]:
    """feature weather values timeline을 반환한다.

    같은 ``valid_at``이라도 ``issued_at``이 다르면 별도 row로 반환하므로, 호출자는
    현재 발표와 3시간/1일 전 발표를 같은 유효시각 기준으로 비교할 수 있다.
    """
    rows = (
        (
            await session.execute(
                text(_LIST_WEATHER_VALUES_SQL),
                {
                    "feature_id": feature_id,
                    "forecast_styles": _filter_values(forecast_styles),
                    "weather_domains": _filter_values(weather_domains),
                    "metric_keys": _filter_values(metric_keys),
                    "history_from": history_from,
                    "issued_from": issued_from,
                    "issued_to": issued_to,
                    "valid_from_filter": valid_from,
                    "valid_to_filter": valid_to,
                    "limit": max(1, limit),
                },
            )
        )
        .mappings()
        .all()
    )
    return [_timeline_row(row) for row in rows]


def _anchor_from_row(row: RowMapping | None) -> WeatherAnchor | None:
    if row is None:
        return None
    lon = row["lon"]
    lat = row["lat"]
    distance_m = row["distance_m"]
    return WeatherAnchor(
        feature_id=str(row["feature_id"]),
        name=str(row["name"]),
        lon=float(lon) if lon is not None else None,
        lat=float(lat) if lat is not None else None,
        distance_m=float(distance_m) if distance_m is not None else None,
    )


async def nearest_weather_feature_for_coordinate(
    session: AsyncSession,
    *,
    lon: float,
    lat: float,
    radius_m: float = _NEAREST_WEATHER_RADIUS_M,
) -> WeatherAnchor | None:
    """좌표 주변 가장 가까운 KMA forecast weather anchor를 찾는다."""
    row = (
        (
            await session.execute(
                text(_NEAREST_WEATHER_BY_COORDINATE_SQL),
                {"lon": lon, "lat": lat, "radius_m": radius_m},
            )
        )
        .mappings()
        .first()
    )
    return _anchor_from_row(row)


async def nearest_weather_feature_for_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    radius_m: float = _NEAREST_WEATHER_RADIUS_M,
) -> WeatherAnchor | None:
    """feature 좌표 주변 가장 가까운 KMA forecast weather anchor를 찾는다."""
    row = (
        (
            await session.execute(
                text(_NEAREST_WEATHER_BY_FEATURE_SQL),
                {"feature_id": feature_id, "radius_m": radius_m},
            )
        )
        .mappings()
        .first()
    )
    return _anchor_from_row(row)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _alert_history_row(row: RowMapping) -> WeatherAlertHistoryRow:
    return WeatherAlertHistoryRow(
        source_record_key=str(row["source_record_key"]),
        feature_id=row["feature_id"],
        feature_name=row["feature_name"],
        region_code=row["region_code"],
        region_name=row["region_name"],
        phenomenon=row["phenomenon"],
        alert_type=row["alert_type"],
        level=row["level"],
        title=row["title"],
        description=row["description"],
        issued_at=row["issued_at"],
        effective_from=row["effective_from"],
        effective_until=row["effective_until"],
        source_agency=row["source_agency"],
        fetched_at=row["fetched_at"],
        imported_at=row["imported_at"],
        last_seen_at=row["last_seen_at"],
        payload=_json_object(row["raw_data"]),
    )


async def list_kma_weather_alert_history(
    session: AsyncSession,
    *,
    region_code: str | None = None,
    phenomenon: str | None = None,
    level: str | None = None,
    history_from: datetime | None = None,
    issued_from: datetime | None = None,
    issued_to: datetime | None = None,
    limit: int = 200,
) -> list[WeatherAlertHistoryRow]:
    """KMA 기상특보 source_record 이력을 반환한다."""
    rows = (
        (
            await session.execute(
                text(_KMA_WEATHER_ALERT_HISTORY_SQL),
                {
                    "region_code": region_code,
                    "phenomenon": phenomenon,
                    "level": level,
                    "history_from": history_from,
                    "issued_from": issued_from,
                    "issued_to": issued_to,
                    "limit": max(1, limit),
                },
            )
        )
        .mappings()
        .all()
    )
    return [_alert_history_row(row) for row in rows]


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
