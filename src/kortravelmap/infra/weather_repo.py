"""``kortravelmap.infra.weather_repo`` — weather value 적재/조회 + weather card (T-213e).

``WeatherValue`` DTO(ADR-010)를 ``feature.feature_weather_values``에 적재하고,
feature별 weather card(forecast_style/metric_key별 최신값 + freshness)를 만든다.
PK는 결정적 ``weather_value_key``(`make_weather_value_key`)라 재적재가 멱등 upsert다.
raw SQL은 본 모듈에 모음(ADR-004). commit은 호출자 책임.
"""

from __future__ import annotations

import json
from asyncio import timeout as asyncio_timeout
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal, cast

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
    "WeatherBatchCard",
    "WeatherBatchItem",
    "WeatherBatchItemState",
    "WeatherBatchMetricLimitExceededError",
    "WeatherBatchPayloadLimitExceededError",
    "WeatherBatchQueryTimeoutError",
    "WeatherBatchWorkLimitExceededError",
    "WeatherBatchSnapshot",
    "WeatherBatchTarget",
    "WeatherAnchor",
    "WeatherValueTimelineRow",
    "WeatherAlertHistoryRow",
    "DEFAULT_WEATHER_FRESHNESS_SECONDS",
    "DEFAULT_WEATHER_HISTORY_RETENTION_DAYS",
    "WEATHER_BATCH_MAX_FEATURE_ID_LENGTH",
    "WEATHER_BATCH_MAX_FEATURE_IDS_PER_TARGET",
    "WEATHER_BATCH_MAX_METRIC_ROWS",
    "WEATHER_BATCH_MAX_PAIRS",
    "WEATHER_BATCH_MAX_PLANNING_WORK",
    "WEATHER_BATCH_MAX_RESPONSE_BYTES",
    "WEATHER_BATCH_MAX_TARGETS",
    "WEATHER_BATCH_QUERY_TIMEOUT_SECONDS",
    "WEATHER_BATCH_MAX_SOURCE_SERIES_WORK",
    "WEATHER_BATCH_TIMELINE_DAYS",
    "WEATHER_BATCH_UNIQUE_FEATURE_WORK_WEIGHT",
    "load_weather_values",
    "build_admin_weather_card",
    "build_weather_card",
    "get_weather_batch_snapshots",
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

WEATHER_BATCH_TIMELINE_DAYS: Final[int] = 1
"""batch snapshot이 ``target_at`` 뒤에 제공하는 24시간 예보 timeline 지평선."""

WEATHER_BATCH_MAX_TARGETS: Final[int] = 366
"""한 요청의 날짜별 target group 상한."""

WEATHER_BATCH_MAX_FEATURE_IDS_PER_TARGET: Final[int] = 200
"""target group 하나의 Feature ID 상한."""

WEATHER_BATCH_MAX_FEATURE_ID_LENGTH: Final[int] = 256
"""request body와 PostgreSQL text[] 메모리를 제한하는 Feature ID 문자 상한."""

WEATHER_BATCH_MAX_PAIRS: Final[int] = 2_000
"""한 요청에서 실제 조회하는 ``target_at × feature_id`` pair 상한."""

WEATHER_BATCH_UNIQUE_FEATURE_WORK_WEIGHT: Final[int] = 5
"""고유 parent의 spatial candidate 계산 비용을 pair 대비 환산하는 가중치."""

WEATHER_BATCH_MAX_PLANNING_WORK: Final[int] = 2_500
"""DB 진입 전 ``pairs + weight × unique Feature`` 작업량 상한."""

WEATHER_BATCH_MAX_METRIC_ROWS: Final[int] = 20_000
"""부분 응답을 금지하기 위한 전체 current/timeline metric row 상한."""

WEATHER_BATCH_MAX_RESPONSE_BYTES: Final[int] = 8 * 1024 * 1024
"""item/card/metric 전체 응답의 보수적 JSON payload byte 상한(8 MiB)."""

WEATHER_BATCH_QUERY_TIMEOUT_SECONDS: Final[float] = 20.0
"""service request 하나가 PostgreSQL backend를 점유할 수 있는 절대 시간 상한."""

WEATHER_BATCH_MAX_SOURCE_SERIES_WORK: Final[int] = 150_000
"""fact 조회 전에 허용하는 공유 card×physical series 조합 상한."""


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
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    effective_at: datetime | None = None


@dataclass(frozen=True)
class WeatherCard:
    """feature 1건의 weather card — forecast_style별 최신 metric 묶음 + freshness."""

    feature_id: str
    asof: datetime | None
    source_styles: list[str]
    metrics: list[WeatherMetric]
    latest_at: datetime | None
    is_stale: bool


WeatherBatchItemState = Literal["found", "no_data", "retired"]


@dataclass(frozen=True)
class WeatherBatchItem:
    """한 snapshot에서 판정한 공개 parent와 공유 weather card 참조."""

    feature_id: str
    state: WeatherBatchItemState
    card_key: str | None


@dataclass(frozen=True)
class WeatherBatchCard:
    """같은 target/source bundle을 공유하는 정규화 weather card."""

    card_key: str
    source_styles: list[str]
    current: list[WeatherMetric]
    timeline: list[WeatherMetric]
    latest_at: datetime | None
    is_stale: bool


@dataclass(frozen=True)
class WeatherBatchTarget:
    """한 target 시각에 조회할 순서 보존 Feature ID 집합."""

    target_at: datetime
    feature_ids: tuple[str, ...]


@dataclass(frozen=True)
class WeatherBatchSnapshot:
    """target 시각 하나의 순서 보존 weather item 묶음."""

    target_at: datetime
    items: tuple[WeatherBatchItem, ...]
    cards: tuple[WeatherBatchCard, ...]


class WeatherBatchMetricLimitExceededError(RuntimeError):
    """weather batch 전체 metric 결과가 공개 응답 예산을 넘었다."""

    def __init__(self, *, actual: int, limit: int) -> None:
        self.actual = actual
        self.limit = limit
        super().__init__(f"weather batch metric rows {actual} exceed limit {limit}")


class WeatherBatchPayloadLimitExceededError(RuntimeError):
    """weather batch 전체 payload 추정치가 공개 응답 byte 예산을 넘었다."""

    def __init__(self, *, actual: int, limit: int) -> None:
        self.actual = actual
        self.limit = limit
        super().__init__(f"weather batch response bytes {actual} exceed limit {limit}")


class WeatherBatchQueryTimeoutError(RuntimeError):
    """weather batch statement가 service query 시간 예산을 넘었다."""


class WeatherBatchWorkLimitExceededError(RuntimeError):
    """weather batch source/card 조합이 DB 작업량 예산을 넘었다."""

    def __init__(self, *, actual: int, limit: int) -> None:
        self.actual = actual
        self.limit = limit
        super().__init__(f"weather batch series work {actual} exceeds limit {limit}")


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
# 0060 dedup과 같은 latest-known-at-wins 정책: 더 오래된 collected_at은 no-op,
# 동률에서 내용이 다르면 나중 write가 이기고 완전히 같은 재적재는 물리 UPDATE를
# 만들지 않는다. collected_at은 DTO와 DB 양쪽에서 non-null TIMESTAMPTZ다.
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
    source_metric_key = EXCLUDED.source_metric_key,
    source_metric_name = EXCLUDED.source_metric_name,
    timeline_bucket = EXCLUDED.timeline_bucket,
    valid_from = EXCLUDED.valid_from,
    valid_until = EXCLUDED.valid_until,
    normalization_version = EXCLUDED.normalization_version,
    payload = EXCLUDED.payload,
    source_record_key = EXCLUDED.source_record_key,
    collected_at = EXCLUDED.collected_at,
    updated_at = now()
WHERE EXCLUDED.collected_at >= feature_weather_values.collected_at
  AND ROW(
      EXCLUDED.value_number,
      EXCLUDED.value_text,
      EXCLUDED.unit,
      EXCLUDED.severity,
      EXCLUDED.metric_name,
      EXCLUDED.source_metric_key,
      EXCLUDED.source_metric_name,
      EXCLUDED.timeline_bucket,
      EXCLUDED.valid_from,
      EXCLUDED.valid_until,
      EXCLUDED.normalization_version,
      EXCLUDED.payload,
      EXCLUDED.source_record_key,
      EXCLUDED.collected_at
  ) IS DISTINCT FROM ROW(
      feature_weather_values.value_number,
      feature_weather_values.value_text,
      feature_weather_values.unit,
      feature_weather_values.severity,
      feature_weather_values.metric_name,
      feature_weather_values.source_metric_key,
      feature_weather_values.source_metric_name,
      feature_weather_values.timeline_bucket,
      feature_weather_values.valid_from,
      feature_weather_values.valid_until,
      feature_weather_values.normalization_version,
      feature_weather_values.payload,
      feature_weather_values.source_record_key,
      feature_weather_values.collected_at
  )
"""

_CARD_SQL: Final[str] = """
SELECT DISTINCT ON (forecast_style, metric_key)
    forecast_style, metric_key, metric_name, timeline_bucket,
    value_number, value_text, unit, severity,
    issued_at, valid_at, valid_from, valid_until, observed_at,
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


def _weather_effective_at_sql(alias: str) -> str:
    """weather의 예보/관측 대상 시각 SQL을 한 정의로 반환한다."""

    if not alias.isidentifier():
        raise ValueError("weather SQL alias must be an identifier")
    return f"COALESCE({alias}.valid_at, {alias}.observed_at, {alias}.valid_from, {alias}.issued_at)"


def _weather_known_at_sql(alias: str) -> str:
    """0060 current-row 단계의 ``known_at`` cutoff SQL."""

    if not alias.isidentifier():
        raise ValueError("weather SQL alias must be an identifier")
    return (
        f"{alias}.collected_at <= CAST(:known_at AS timestamptz) "
        f"AND ({alias}.issued_at IS NULL "
        f"OR {alias}.issued_at <= CAST(:known_at AS timestamptz)) "
        f"AND ({alias}.forecast_style NOT IN ('ultra_short', 'short', 'mid') "
        f"OR {alias}.issued_at IS NOT NULL)"
    )


_BATCH_EFFECTIVE_AT: Final[str] = _weather_effective_at_sql("w")
_BATCH_KNOWN_AT: Final[str] = _weather_known_at_sql("w")


def _weather_batch_current_predicate(target_expression: str) -> str:
    """고정된 내부 target 식에 대한 current weather 술어를 만든다."""

    if target_expression not in {"parent.target_at", "metric.target_at"}:
        raise ValueError("unsupported weather batch target expression")
    return f"""
{_BATCH_KNOWN_AT}
AND {_BATCH_EFFECTIVE_AT} IS NOT NULL
AND {_BATCH_EFFECTIVE_AT} <= {target_expression}
AND (
    w.valid_at IS NOT NULL
    OR w.observed_at IS NOT NULL
    OR w.valid_from IS NULL
    OR w.valid_until IS NULL
    OR w.valid_until >= {target_expression}
)
"""


_BATCH_CURRENT_FOR_PARENT: Final[str] = _weather_batch_current_predicate("parent.target_at")
_BATCH_CURRENT_FOR_METRIC: Final[str] = _weather_batch_current_predicate("metric.target_at")

# KMA weather source tier 술어. batch SQL이 module import 시 이 상수를 삽입하므로
# nearest-anchor SQL 정의보다 먼저 둔다.
_KMA_FORECAST_PREDICATE: Final[str] = (
    "w.provider = 'python-kma-api' "
    "AND w.forecast_style IN ('nowcast', 'ultra_short', 'short', 'mid')"
)
_OBSERVED_TEMP_PREDICATE: Final[str] = (
    "w.forecast_style = 'observed' AND w.metric_key IN ('T1H', 'TMP')"
)

# T-VN-16C: 날짜별 sparse target을 flatten한 뒤 parent 판정, 고유 parent별 spatial
# candidate 계산, target별 bitemporal nearest-anchor 선택, current와 24시간 forecast
# timeline을 한 SQL statement/snapshot에서 읽는다. 같은 target/source bundle은 공유
# card 한 번만 계산한다.
#
# 0060은 full correction history/current-summary 이전 단계라 ``collected_at``이
# ``known_at`` proxy다(ADR-072). forecast는 미래 지식 누출을 막기 위해
# ``issued_at <= known_at``도 함께 강제한다.
_WEATHER_BATCH_SQL: Final[str] = f"""
WITH requested AS (
    SELECT item.feature_id, item.target_at, item.ordinality
    FROM unnest(
        CAST(:feature_ids AS text[]),
        CAST(:target_ats AS timestamptz[])
    ) WITH ORDINALITY AS item(feature_id, target_at, ordinality)
),
parents AS (
    SELECT
        requested.feature_id,
        requested.target_at,
        requested.ordinality,
        visible.feature_id AS visible_feature_id,
        visible.coord_5179
    FROM requested
    LEFT JOIN feature.public_features AS visible
      ON visible.feature_id = requested.feature_id
),
unique_parents AS (
    SELECT DISTINCT ON (feature_id)
        feature_id,
        visible_feature_id,
        coord_5179
    FROM parents
    ORDER BY feature_id, ordinality
),
source_capabilities AS MATERIALIZED (
    SELECT
        series.feature_id,
        bool_or(
            series.provider = 'python-kma-api'
            AND series.forecast_style IN ('nowcast', 'ultra_short', 'short', 'mid')
        ) AS has_kma_forecast,
        bool_or(
            series.forecast_style = 'observed'
            AND series.metric_key IN ('T1H', 'TMP')
        ) AS has_observed_temperature
    FROM feature.weather_metric_series AS series
    GROUP BY series.feature_id
),
anchor_candidates AS MATERIALIZED (
    SELECT
        parent.feature_id AS parent_feature_id,
        candidate.feature_id,
        candidate.coord_5179
          OPERATOR(x_extension.<->) parent.coord_5179 AS distance_order,
        capability.has_kma_forecast,
        capability.has_observed_temperature
    FROM unique_parents AS parent
    JOIN feature.public_features AS candidate
      ON parent.visible_feature_id IS NOT NULL
     AND candidate.kind = 'weather'
     AND parent.coord_5179 IS NOT NULL
     AND candidate.coord_5179 IS NOT NULL
     AND x_extension.ST_DWithin(
           candidate.coord_5179,
           parent.coord_5179,
           CAST(:radius_m AS double precision)
         )
    JOIN source_capabilities AS capability
      ON capability.feature_id = candidate.feature_id
),
own_has_temperature AS (
    SELECT
        parent.ordinality,
        EXISTS (
            SELECT 1 AS found
            FROM feature.weather_metric_series AS series
            JOIN LATERAL (
                SELECT 1
                FROM feature.feature_weather_values AS w
                WHERE w.feature_id = series.feature_id
                  AND w.provider = series.provider
                  AND w.weather_domain = series.weather_domain
                  AND w.forecast_style = series.forecast_style
                  AND w.metric_key = series.metric_key
                  AND {_BATCH_CURRENT_FOR_PARENT}
                LIMIT 1
            ) AS current_row ON true
            WHERE series.feature_id = parent.visible_feature_id
              AND series.metric_key IN ('T1H', 'TMP')
            LIMIT 1 OFFSET 0
        ) AS value
    FROM parents AS parent
),
kma_anchor AS (
    SELECT parent.ordinality, parent.target_at, anchor.feature_id
    FROM parents AS parent
    JOIN own_has_temperature AS own_temp USING (ordinality)
    LEFT JOIN LATERAL (
        SELECT candidate.feature_id
        FROM anchor_candidates AS candidate
        WHERE candidate.parent_feature_id = parent.feature_id
          AND candidate.has_kma_forecast
          AND NOT own_temp.value
          AND EXISTS (
              SELECT 1 AS found
              FROM feature.weather_metric_series AS series
              JOIN LATERAL (
                  SELECT 1
                  FROM feature.feature_weather_values AS w
                  WHERE w.feature_id = series.feature_id
                    AND w.provider = series.provider
                    AND w.weather_domain = series.weather_domain
                    AND w.forecast_style = series.forecast_style
                    AND w.metric_key = series.metric_key
                    AND {_BATCH_CURRENT_FOR_PARENT}
                  LIMIT 1
              ) AS current_row ON true
              WHERE series.feature_id = candidate.feature_id
                AND series.provider = 'python-kma-api'
                AND series.forecast_style IN ('nowcast', 'ultra_short', 'short', 'mid')
              LIMIT 1 OFFSET 0
          )
        ORDER BY candidate.distance_order, candidate.feature_id
        LIMIT 1
    ) AS anchor ON true
),
observed_anchor AS (
    SELECT parent.ordinality, parent.target_at, anchor.feature_id
    FROM parents AS parent
    JOIN own_has_temperature AS own_temp USING (ordinality)
    LEFT JOIN LATERAL (
        SELECT candidate.feature_id
        FROM anchor_candidates AS candidate
        WHERE candidate.parent_feature_id = parent.feature_id
          AND candidate.has_observed_temperature
          AND NOT own_temp.value
          AND EXISTS (
              SELECT 1 AS found
              FROM feature.weather_metric_series AS series
              JOIN LATERAL (
                  SELECT 1
                  FROM feature.feature_weather_values AS w
                  WHERE w.feature_id = series.feature_id
                    AND w.provider = series.provider
                    AND w.weather_domain = series.weather_domain
                    AND w.forecast_style = series.forecast_style
                    AND w.metric_key = series.metric_key
                    AND {_BATCH_CURRENT_FOR_PARENT}
                  LIMIT 1
              ) AS current_row ON true
              WHERE series.feature_id = candidate.feature_id
                AND series.forecast_style = 'observed'
                AND series.metric_key IN ('T1H', 'TMP')
              LIMIT 1 OFFSET 0
          )
        ORDER BY candidate.distance_order, candidate.feature_id
        LIMIT 1
    ) AS anchor ON true
),
preferred_sources AS (
    SELECT
        ordinality,
        target_at,
        visible_feature_id AS source_feature_id,
        0 AS tier
    FROM parents
    WHERE visible_feature_id IS NOT NULL
    UNION ALL
    SELECT ordinality, target_at, feature_id, 1
    FROM kma_anchor
    WHERE feature_id IS NOT NULL
    UNION ALL
    SELECT ordinality, target_at, feature_id, 2
    FROM observed_anchor
    WHERE feature_id IS NOT NULL
),
preferred_has_current AS (
    SELECT
        parent.ordinality,
        EXISTS (
            SELECT 1 AS found
            FROM preferred_sources AS source
            JOIN feature.weather_metric_series AS series
              ON series.feature_id = source.source_feature_id
            JOIN LATERAL (
                SELECT 1
                FROM feature.feature_weather_values AS w
                WHERE w.feature_id = series.feature_id
                  AND w.provider = series.provider
                  AND w.weather_domain = series.weather_domain
                  AND w.forecast_style = series.forecast_style
                  AND w.metric_key = series.metric_key
                  AND {_BATCH_CURRENT_FOR_PARENT}
                LIMIT 1
            ) AS current_row ON true
            WHERE source.ordinality = parent.ordinality
            LIMIT 1 OFFSET 0
        ) AS value
    FROM parents AS parent
),
fallback_anchor AS (
    SELECT parent.ordinality, parent.target_at, anchor.feature_id
    FROM parents AS parent
    JOIN preferred_has_current AS preferred USING (ordinality)
    LEFT JOIN LATERAL (
        SELECT candidate.feature_id
        FROM anchor_candidates AS candidate
        WHERE candidate.parent_feature_id = parent.feature_id
          AND NOT preferred.value
          AND EXISTS (
              SELECT 1 AS found
              FROM feature.weather_metric_series AS series
              JOIN LATERAL (
                  SELECT 1
                  FROM feature.feature_weather_values AS w
                  WHERE w.feature_id = series.feature_id
                    AND w.provider = series.provider
                    AND w.weather_domain = series.weather_domain
                    AND w.forecast_style = series.forecast_style
                    AND w.metric_key = series.metric_key
                    AND {_BATCH_CURRENT_FOR_PARENT}
                  LIMIT 1
              ) AS current_row ON true
              WHERE series.feature_id = candidate.feature_id
              LIMIT 1 OFFSET 0
          )
        ORDER BY candidate.distance_order, candidate.feature_id
        LIMIT 1
    ) AS anchor ON true
),
sources AS (
    SELECT ordinality, target_at, source_feature_id, tier
    FROM preferred_sources
    UNION ALL
    SELECT ordinality, target_at, feature_id, 3
    FROM fallback_anchor
    WHERE feature_id IS NOT NULL
),
metric_sources AS MATERIALIZED (
    SELECT DISTINCT
        source.ordinality,
        source.target_at,
        source.source_feature_id,
        source.tier
    FROM sources AS source
    JOIN feature.weather_metric_series AS series
      ON series.feature_id = source.source_feature_id
),
source_bundles AS (
    SELECT
        parent.ordinality,
        parent.target_at,
        COALESCE(
            array_agg(source.source_feature_id ORDER BY source.tier)
                FILTER (WHERE source.source_feature_id IS NOT NULL),
            CAST(ARRAY[] AS text[])
        ) AS source_feature_ids
    FROM parents AS parent
    LEFT JOIN metric_sources AS source USING (ordinality, target_at)
    GROUP BY parent.ordinality, parent.target_at
),
cards AS (
    SELECT
        target_at,
        source_feature_ids,
        min(ordinality) AS card_ordinal
    FROM source_bundles
    GROUP BY target_at, source_feature_ids
),
parent_cards AS (
    SELECT bundle.ordinality, card.card_ordinal
    FROM source_bundles AS bundle
    JOIN cards AS card
      ON card.target_at = bundle.target_at
     AND card.source_feature_ids = bundle.source_feature_ids
),
card_sources AS (
    SELECT
        card.card_ordinal AS ordinality,
        card.target_at,
        source.source_feature_id,
        source.tier
    FROM cards AS card
    JOIN metric_sources AS source
      ON source.ordinality = card.card_ordinal
),
source_metric_keys AS MATERIALIZED (
    SELECT
        source.ordinality,
        source.target_at,
        source.source_feature_id,
        source.tier,
        series.provider,
        series.weather_domain,
        series.forecast_style,
        series.metric_key
    FROM card_sources AS source
    JOIN feature.weather_metric_series AS series
      ON series.feature_id = source.source_feature_id
),
source_metric_key_count AS (
    SELECT count(*)::bigint AS value
    FROM source_metric_keys
),
current_source_rows AS (
    SELECT
        metric.ordinality,
        metric.target_at,
        metric.source_feature_id,
        metric.tier,
        row.forecast_style,
        row.metric_key,
        row.metric_name,
        row.timeline_bucket,
        row.value_number,
        row.value_text,
        row.unit,
        row.severity,
        row.issued_at,
        row.valid_at,
        row.valid_from,
        row.valid_until,
        row.observed_at,
        row.provider,
        row.weather_domain,
        row.effective_at,
        row.collected_at,
        row.weather_value_key
    FROM source_metric_keys AS metric
    CROSS JOIN source_metric_key_count
    JOIN LATERAL (
        SELECT
            w.forecast_style,
            w.metric_key,
            w.metric_name,
            w.timeline_bucket,
            w.value_number,
            w.value_text,
            w.unit,
            w.severity,
            w.issued_at,
            w.valid_at,
            w.valid_from,
            w.valid_until,
            w.observed_at,
            w.provider,
            w.weather_domain,
            {_BATCH_EFFECTIVE_AT} AS effective_at,
            w.collected_at,
            w.weather_value_key
        FROM feature.feature_weather_values AS w
        WHERE w.feature_id = metric.source_feature_id
          AND w.provider = metric.provider
          AND w.weather_domain = metric.weather_domain
          AND w.forecast_style = metric.forecast_style
          AND w.metric_key = metric.metric_key
          AND {_BATCH_CURRENT_FOR_METRIC}
        ORDER BY
            {_BATCH_EFFECTIVE_AT} DESC,
            w.issued_at DESC NULLS LAST,
            w.collected_at DESC,
            w.weather_value_key
        LIMIT 1
    ) AS row
      ON source_metric_key_count.value <= CAST(:series_work_limit AS bigint)
),
current_rows AS (
    SELECT DISTINCT ON (
        row.ordinality, row.forecast_style, row.metric_key
    )
        row.ordinality,
        'current'::text AS section,
        row.forecast_style,
        row.metric_key,
        row.metric_name,
        row.timeline_bucket,
        row.value_number,
        row.value_text,
        row.unit,
        row.severity,
        row.issued_at,
        row.valid_at,
        row.valid_from,
        row.valid_until,
        row.observed_at,
        row.provider,
        row.weather_domain,
        row.effective_at
    FROM current_source_rows AS row
    ORDER BY
        row.ordinality,
        row.forecast_style,
        row.metric_key,
        row.tier,
        row.effective_at DESC,
        row.issued_at DESC NULLS LAST,
        row.collected_at DESC,
        row.weather_value_key
),
timeline_source_rows AS (
    SELECT DISTINCT ON (
        metric.ordinality,
        metric.source_feature_id,
        w.forecast_style,
        w.metric_key,
        {_BATCH_EFFECTIVE_AT}
    )
        metric.ordinality,
        metric.tier,
        metric.source_feature_id,
        w.forecast_style,
        w.metric_key,
        w.metric_name,
        w.timeline_bucket,
        w.value_number,
        w.value_text,
        w.unit,
        w.severity,
        w.issued_at,
        w.valid_at,
        w.valid_from,
        w.valid_until,
        w.observed_at,
        w.provider,
        w.weather_domain,
        {_BATCH_EFFECTIVE_AT} AS effective_at
    FROM source_metric_keys AS metric
    CROSS JOIN source_metric_key_count
    JOIN feature.feature_weather_values AS w
      ON w.feature_id = metric.source_feature_id
     AND w.provider = metric.provider
     AND w.weather_domain = metric.weather_domain
     AND w.forecast_style = metric.forecast_style
     AND w.metric_key = metric.metric_key
     AND source_metric_key_count.value <= CAST(:series_work_limit AS bigint)
    WHERE {_BATCH_KNOWN_AT}
      AND {_BATCH_EFFECTIVE_AT} > metric.target_at
      AND {_BATCH_EFFECTIVE_AT}
          <= metric.target_at
             + make_interval(days => CAST(:timeline_days AS integer))
    ORDER BY
        metric.ordinality,
        metric.source_feature_id,
        w.forecast_style,
        w.metric_key,
        {_BATCH_EFFECTIVE_AT},
        w.issued_at DESC NULLS LAST,
        w.collected_at DESC,
        w.weather_value_key
),
timeline_rows AS (
    SELECT DISTINCT ON (
        row.ordinality,
        row.forecast_style,
        row.metric_key,
        row.effective_at
    )
        row.ordinality,
        'timeline'::text AS section,
        row.forecast_style,
        row.metric_key,
        row.metric_name,
        row.timeline_bucket,
        row.value_number,
        row.value_text,
        row.unit,
        row.severity,
        row.issued_at,
        row.valid_at,
        row.valid_from,
        row.valid_until,
        row.observed_at,
        row.provider,
        row.weather_domain,
        row.effective_at
    FROM timeline_source_rows AS row
    ORDER BY
        row.ordinality,
        row.forecast_style,
        row.metric_key,
        row.effective_at,
        row.tier,
        row.issued_at DESC NULLS LAST
),
weather_rows AS (
    SELECT * FROM current_rows
    UNION ALL
    SELECT * FROM timeline_rows
),
weather_row_count AS (
    SELECT count(*)::bigint AS value
    FROM weather_rows
),
weather_response_size AS (
    SELECT (
        4096
        + COALESCE(
            sum(
                64
                + octet_length(
                    CAST(
                        jsonb_build_object(
                            'forecast_style', forecast_style,
                            'metric_key', metric_key,
                            'metric_name', metric_name,
                            'timeline_bucket', timeline_bucket,
                            'value_number', value_number,
                            'value_text', value_text,
                            'unit', unit,
                            'severity', severity,
                            'issued_at', issued_at,
                            'valid_at', valid_at,
                            'valid_from', valid_from,
                            'valid_until', valid_until,
                            'observed_at', observed_at,
                            'provider', provider,
                            'weather_domain', weather_domain,
                            'effective_at', effective_at
                        ) AS text
                    )
                )
            ),
            0
        )
        + (
            SELECT COALESCE(
                sum(256 + octet_length(parent.feature_id)),
                0
            )
            FROM parents AS parent
        )
        + (SELECT count(*) * 256 FROM cards)
    )::bigint AS value
    FROM weather_rows
),
card_states AS (
    SELECT
        card.card_ordinal,
        EXISTS (
            SELECT 1
            FROM weather_rows AS weather
            WHERE weather.ordinality = card.card_ordinal
        ) AS has_weather
    FROM cards AS card
),
batch_rows AS (
    SELECT
        'item'::text AS row_kind,
        parent.ordinality AS item_ordinality,
        parent.feature_id,
        CASE
          WHEN parent.visible_feature_id IS NOT NULL AND card_state.has_weather
          THEN parent_card.card_ordinal
          ELSE NULL
        END AS card_ordinal,
        CASE
          WHEN parent.visible_feature_id IS NULL THEN 'retired'
          WHEN card_state.has_weather THEN 'found'
          ELSE 'no_data'
        END AS state,
        NULL::text AS section,
        NULL::text AS forecast_style,
        NULL::text AS metric_key,
        NULL::text AS metric_name,
        NULL::text AS timeline_bucket,
        NULL::numeric AS value_number,
        NULL::text AS value_text,
        NULL::text AS unit,
        NULL::text AS severity,
        NULL::timestamptz AS issued_at,
        NULL::timestamptz AS valid_at,
        NULL::timestamptz AS valid_from,
        NULL::timestamptz AS valid_until,
        NULL::timestamptz AS observed_at,
        NULL::text AS provider,
        NULL::text AS weather_domain,
        NULL::timestamptz AS effective_at
    FROM parents AS parent
    LEFT JOIN parent_cards AS parent_card USING (ordinality)
    LEFT JOIN card_states AS card_state
      ON card_state.card_ordinal = parent_card.card_ordinal

    UNION ALL

    SELECT
        'metric'::text AS row_kind,
        NULL::bigint AS item_ordinality,
        NULL::text AS feature_id,
        weather.ordinality AS card_ordinal,
        NULL::text AS state,
        weather.section,
        weather.forecast_style,
        weather.metric_key,
        weather.metric_name,
        weather.timeline_bucket,
        weather.value_number,
        weather.value_text,
        weather.unit,
        weather.severity,
        weather.issued_at,
        weather.valid_at,
        weather.valid_from,
        weather.valid_until,
        weather.observed_at,
        weather.provider,
        weather.weather_domain,
        weather.effective_at
    FROM weather_rows AS weather
    CROSS JOIN weather_row_count
    CROSS JOIN weather_response_size
    WHERE weather_row_count.value <= CAST(:metric_row_limit AS bigint)
      AND weather_response_size.value <= CAST(:response_byte_limit AS bigint)
)
SELECT
    batch.row_kind,
    batch.item_ordinality,
    batch.feature_id,
    batch.card_ordinal,
    batch.state,
    batch.section,
    batch.forecast_style,
    batch.metric_key,
    batch.metric_name,
    batch.timeline_bucket,
    batch.value_number,
    batch.value_text,
    batch.unit,
    batch.severity,
    batch.issued_at,
    batch.valid_at,
    batch.valid_from,
    batch.valid_until,
    batch.observed_at,
    batch.provider,
    batch.weather_domain,
    batch.effective_at,
    source_metric_key_count.value AS series_work_count,
    weather_row_count.value AS metric_row_count,
    weather_response_size.value AS response_payload_bytes
FROM batch_rows AS batch
CROSS JOIN source_metric_key_count
CROSS JOIN weather_row_count
CROSS JOIN weather_response_size
ORDER BY
    CASE batch.row_kind WHEN 'item' THEN 0 ELSE 1 END,
    COALESCE(batch.item_ordinality, batch.card_ordinal),
    CASE batch.section WHEN 'current' THEN 0 WHEN 'timeline' THEN 1 ELSE 2 END,
    batch.effective_at,
    batch.forecast_style,
    batch.metric_key
"""

# KMA weather는 격자(≈5km) 단위라 적재된 격자에 속한 place feature에만 붙는다.
# 그 외 feature는 자기 weather_value가 없으므로, 반경 내 weather 보유한 가장 가까운
# feature(=가장 가까운 격자)의 값으로 폴백한다("위치에 맞춘" 지역 날씨). coord_5179
# (m, STORED generated)로 KNN(ADR-012: ST_Transform 술어 금지, PostGIS는 x_extension
# 스키마 qualify — #410/#411).
_NEAREST_WEATHER_RADIUS_M: Final[float] = 50_000.0


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
WHERE f.kind = 'weather'
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
_NEAREST_KMA_FORECAST_SQL: Final[str] = _nearest_anchor_sql(f"AND {_KMA_FORECAST_PREDICATE}")

# 반경 내 가장 가까운 관측 기온 anchor — observed T1H/TMP 보유(휴게소 등).
_NEAREST_OBSERVED_TEMP_SQL: Final[str] = _nearest_anchor_sql(f"AND {_OBSERVED_TEMP_PREDICATE}")


def _admin_nearest_anchor_sql(exists_predicate: str) -> str:
    """삭제 전 base Feature에서 admin weather anchor를 찾는 SQL."""

    return f"""
WITH target AS (
    SELECT coord_5179
    FROM feature.features
    WHERE feature_id = :feature_id
      AND deleted_at IS NULL
      AND user_deleted_at IS NULL
      AND status <> 'deleted'
      AND coord_5179 IS NOT NULL
)
SELECT f.feature_id
FROM feature.features AS f, target AS t
WHERE f.deleted_at IS NULL
  AND f.user_deleted_at IS NULL
  AND f.status <> 'deleted'
  AND f.kind = 'weather'
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


_ADMIN_NEAREST_WEATHER_SQL: Final[str] = _admin_nearest_anchor_sql("")
_ADMIN_NEAREST_KMA_FORECAST_SQL: Final[str] = _admin_nearest_anchor_sql(
    f"AND {_KMA_FORECAST_PREDICATE}"
)
_ADMIN_NEAREST_OBSERVED_TEMP_SQL: Final[str] = _admin_nearest_anchor_sql(
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
            _enum_value(value.timeline_bucket) if value.timeline_bucket is not None else None
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


async def load_weather_values(session: AsyncSession, values: Iterable[WeatherValue]) -> int:
    """``WeatherValue`` 들을 멱등 upsert 적재한다. 적재 건수 반환 (commit은 호출자).

    semantic tuple이 같으면 최신 ``collected_at``만 현재 row를 갱신한다. 더 오래된
    backfill과 완전히 같은 재적재는 DB no-op이다. 반환값은 실제 UPDATE 수가 아니라
    입력으로 수용한 건수다. weather kind ``feature``가 먼저 존재해야 한다(FK).
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


def _weather_metric(row: RowMapping) -> WeatherMetric:
    valid_at = row["valid_at"]
    observed_at = row["observed_at"]
    valid_from = row["valid_from"]
    issued_at = row["issued_at"]
    effective_at = row.get("effective_at")
    if effective_at is None:
        effective_at = valid_at or observed_at or valid_from or issued_at
    return WeatherMetric(
        forecast_style=str(row["forecast_style"]),
        metric_key=str(row["metric_key"]),
        metric_name=row["metric_name"],
        timeline_bucket=row["timeline_bucket"],
        value_number=row["value_number"],
        value_text=row["value_text"],
        unit=row["unit"],
        severity=row["severity"],
        issued_at=issued_at,
        valid_at=valid_at,
        observed_at=observed_at,
        provider=row["provider"],
        weather_domain=row["weather_domain"],
        valid_from=valid_from,
        valid_until=row["valid_until"],
        effective_at=effective_at,
    )


async def get_weather_batch_snapshots(
    session: AsyncSession,
    *,
    targets: Sequence[WeatherBatchTarget],
    known_at: datetime,
    freshness_seconds: int = DEFAULT_WEATHER_FRESHNESS_SECONDS,
    metric_row_limit: int = WEATHER_BATCH_MAX_METRIC_ROWS,
    response_byte_limit: int = WEATHER_BATCH_MAX_RESPONSE_BYTES,
    series_work_limit: int = WEATHER_BATCH_MAX_SOURCE_SERIES_WORK,
    query_timeout_seconds: float = WEATHER_BATCH_QUERY_TIMEOUT_SECONDS,
) -> tuple[WeatherBatchSnapshot, ...]:
    """날짜별 공개 parent와 weather를 한 SQL snapshot에서 반환한다.

    각 target은 그 날짜에 실제로 필요한 Feature ID만 가진 sparse group이다.
    target 순서와 group 안의 Feature ID 순서는 응답에서도 그대로 유지한다. 같은
    target/source bundle의 item은 target-local ``card_key``로 한 card를 공유한다.
    ``known_at``은 모든 target이 공유하는 지식 cutoff다. 현 0060 schema에서는
    ``collected_at``을 known-at proxy로 사용하고 forecast ``issued_at``도 cutoff
    이하로 제한한다.

    ``retired``는 base-table 세부 상태를 공개하지 않는 service weather 경계에서
    "현재 공개 parent가 아님"을 뜻한다. ``no_data``는 공개 parent가 존재하지만
    cutoff와 source-tier 규칙을 만족하는 weather가 없다는 별도 상태다.
    """
    if not targets:
        return ()
    if len(targets) > WEATHER_BATCH_MAX_TARGETS:
        raise ValueError("weather batch target count exceeds limit")
    if not 1 <= metric_row_limit <= WEATHER_BATCH_MAX_METRIC_ROWS:
        raise ValueError("weather batch metric row limit is out of range")
    if not 1 <= response_byte_limit <= WEATHER_BATCH_MAX_RESPONSE_BYTES:
        raise ValueError("weather batch response byte limit is out of range")
    if not 1 <= series_work_limit <= WEATHER_BATCH_MAX_SOURCE_SERIES_WORK:
        raise ValueError("weather batch series work limit is out of range")
    if not 0 < query_timeout_seconds <= WEATHER_BATCH_QUERY_TIMEOUT_SECONDS:
        raise ValueError("weather batch query timeout is out of range")

    feature_ids: list[str] = []
    target_ats: list[datetime] = []
    previous_target_at: datetime | None = None
    for target in targets:
        if previous_target_at is not None and target.target_at <= previous_target_at:
            raise ValueError("weather batch targets must be strictly increasing")
        previous_target_at = target.target_at
        if not target.feature_ids:
            raise ValueError("weather batch target feature_ids must not be empty")
        if len(target.feature_ids) > WEATHER_BATCH_MAX_FEATURE_IDS_PER_TARGET:
            raise ValueError("weather batch target feature count exceeds limit")
        if len(target.feature_ids) != len(set(target.feature_ids)):
            raise ValueError("weather batch target feature_ids must be unique")
        if any(
            len(feature_id) > WEATHER_BATCH_MAX_FEATURE_ID_LENGTH
            for feature_id in target.feature_ids
        ):
            raise ValueError("weather batch feature_id length exceeds limit")
        feature_ids.extend(target.feature_ids)
        target_ats.extend([target.target_at] * len(target.feature_ids))

    if len(feature_ids) > WEATHER_BATCH_MAX_PAIRS:
        raise ValueError("weather batch pair count exceeds limit")
    planning_work = len(feature_ids) + WEATHER_BATCH_UNIQUE_FEATURE_WORK_WEIGHT * len(
        set(feature_ids)
    )
    if planning_work > WEATHER_BATCH_MAX_PLANNING_WORK:
        raise ValueError("weather batch planning work exceeds limit")

    try:
        async with asyncio_timeout(query_timeout_seconds):
            rows = (
                (
                    await session.execute(
                        text(_WEATHER_BATCH_SQL),
                        {
                            "feature_ids": feature_ids,
                            "target_ats": target_ats,
                            "known_at": known_at,
                            "radius_m": _NEAREST_WEATHER_RADIUS_M,
                            "timeline_days": WEATHER_BATCH_TIMELINE_DAYS,
                            "metric_row_limit": metric_row_limit,
                            "response_byte_limit": response_byte_limit,
                            "series_work_limit": series_work_limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
    except TimeoutError as exc:
        raise WeatherBatchQueryTimeoutError(
            f"weather batch query exceeded {query_timeout_seconds:g} seconds"
        ) from exc
    if not rows:
        raise RuntimeError("weather batch query returned no parent rows")
    series_work_count = int(rows[0]["series_work_count"])
    if series_work_count > series_work_limit:
        raise WeatherBatchWorkLimitExceededError(
            actual=series_work_count,
            limit=series_work_limit,
        )
    metric_row_count = int(rows[0]["metric_row_count"])
    if metric_row_count > metric_row_limit:
        raise WeatherBatchMetricLimitExceededError(
            actual=metric_row_count,
            limit=metric_row_limit,
        )
    response_payload_bytes = int(rows[0]["response_payload_bytes"])
    if response_payload_bytes > response_byte_limit:
        raise WeatherBatchPayloadLimitExceededError(
            actual=response_payload_bytes,
            limit=response_byte_limit,
        )

    pair_count = len(feature_ids)
    current_by_card: dict[int, list[WeatherMetric]] = {}
    timeline_by_card: dict[int, list[WeatherMetric]] = {}
    state_by_ordinal: dict[int, WeatherBatchItemState] = {}
    card_by_ordinal: dict[int, int | None] = {}
    feature_by_ordinal: dict[int, str] = {}
    valid_states: frozenset[str] = frozenset({"found", "no_data", "retired"})
    for row in rows:
        row_kind = str(row["row_kind"])
        if row_kind == "item":
            ordinal = int(row["item_ordinality"])
            if not 1 <= ordinal <= pair_count:
                raise RuntimeError(f"unexpected weather batch item ordinal: {ordinal}")
            raw_state = str(row["state"])
            if raw_state not in valid_states:
                raise RuntimeError(f"unexpected weather batch state: {raw_state}")
            raw_card_ordinal = row["card_ordinal"]
            card_ordinal = int(raw_card_ordinal) if raw_card_ordinal is not None else None
            if raw_state == "found" and card_ordinal is None:
                raise RuntimeError("found weather batch item has no card")
            if raw_state != "found" and card_ordinal is not None:
                raise RuntimeError("non-found weather batch item references a card")
            state_by_ordinal[ordinal] = cast(WeatherBatchItemState, raw_state)
            card_by_ordinal[ordinal] = card_ordinal
            feature_by_ordinal[ordinal] = str(row["feature_id"])
            continue
        if row_kind != "metric":
            raise RuntimeError(f"unexpected weather batch row kind: {row_kind}")
        raw_card_ordinal = row["card_ordinal"]
        if raw_card_ordinal is None:
            raise RuntimeError("weather batch metric has no card ordinal")
        card_ordinal = int(raw_card_ordinal)
        if not 1 <= card_ordinal <= pair_count:
            raise RuntimeError(f"unexpected weather batch card ordinal: {card_ordinal}")
        section = row["section"]
        if section is None:
            raise RuntimeError("weather batch metric has no section")
        metric = _weather_metric(row)
        if section == "current":
            current_by_card.setdefault(card_ordinal, []).append(metric)
        elif section == "timeline":
            timeline_by_card.setdefault(card_ordinal, []).append(metric)
        else:
            raise RuntimeError(f"unexpected weather batch section: {section}")

    expected_ordinals = set(range(1, pair_count + 1))
    if set(state_by_ordinal) != expected_ordinals:
        raise RuntimeError("weather batch query returned incomplete item rows")

    flat_items: list[WeatherBatchItem] = []
    cards: dict[int, WeatherBatchCard] = {}
    for ordinal, feature_id in enumerate(feature_ids, start=1):
        if feature_by_ordinal[ordinal] != feature_id:
            raise RuntimeError("weather batch query changed item identity or order")
        state = state_by_ordinal[ordinal]
        card_ordinal = card_by_ordinal[ordinal]
        card_key = f"c{card_ordinal}" if card_ordinal is not None else None
        flat_items.append(
            WeatherBatchItem(
                feature_id=feature_id,
                state=state,
                card_key=card_key,
            )
        )
        if card_ordinal is None or card_ordinal in cards:
            continue
        current = current_by_card.get(card_ordinal, [])
        timeline = timeline_by_card.get(card_ordinal, [])
        if not current and not timeline:
            raise RuntimeError("found weather batch card has no metrics")
        latest_candidates = [
            metric.effective_at for metric in current if metric.effective_at is not None
        ]
        latest_at = max(latest_candidates) if latest_candidates else None
        card_target_at = target_ats[card_ordinal - 1]
        cards[card_ordinal] = WeatherBatchCard(
            card_key=f"c{card_ordinal}",
            source_styles=sorted(
                {metric.forecast_style for metric in (*current, *timeline)}
            ),
            current=current,
            timeline=timeline,
            latest_at=latest_at,
            is_stale=(
                latest_at is None
                or (card_target_at - latest_at).total_seconds() > freshness_seconds
            ),
        )

    if (set(current_by_card) | set(timeline_by_card)) != set(cards):
        raise RuntimeError("weather batch query returned an unreferenced card")

    cards_by_key = {card.card_key: card for card in cards.values()}
    snapshots: list[WeatherBatchSnapshot] = []
    offset = 0
    for target in targets:
        next_offset = offset + len(target.feature_ids)
        target_items = flat_items[offset:next_offset]
        target_cards: list[WeatherBatchCard] = []
        seen_card_keys: set[str] = set()
        for item in target_items:
            if item.card_key is None or item.card_key in seen_card_keys:
                continue
            target_cards.append(cards_by_key[item.card_key])
            seen_card_keys.add(item.card_key)
        snapshots.append(
            WeatherBatchSnapshot(
                target_at=target.target_at,
                items=tuple(target_items),
                cards=tuple(target_cards),
            )
        )
        offset = next_offset
    return tuple(snapshots)


async def _build_weather_card(
    session: AsyncSession,
    *,
    feature_id: str,
    asof: datetime | None,
    freshness_seconds: int,
    nearest_weather_sql: str,
    nearest_kma_forecast_sql: str,
    nearest_observed_temp_sql: str,
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
        (await session.execute(text(_CARD_SQL), {"feature_id": feature_id, "asof": asof}))
        .mappings()
        .all()
    )
    params = {"feature_id": feature_id, "radius_m": _NEAREST_WEATHER_RADIUS_M}

    async def _anchor_rows(sql: str) -> list[RowMapping]:
        anchor_id = (await session.execute(text(sql), params)).scalar_one_or_none()
        if anchor_id is None or str(anchor_id) == feature_id:
            return []
        return list(
            (await session.execute(text(_CARD_SQL), {"feature_id": str(anchor_id), "asof": asof}))
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
        _merge(await _anchor_rows(nearest_kma_forecast_sql))
        _merge(await _anchor_rows(nearest_observed_temp_sql))
    # 어느 tier도 반경에 없으면(완전 미적재 지역) 가장 가까운 임의 weather로 폴백(빈 카드 회피).
    if not rows:
        _merge(await _anchor_rows(nearest_weather_sql))
    metrics = [_weather_metric(row) for row in rows]
    source_styles = sorted({m.forecast_style for m in metrics})
    candidates = [
        ts for m in metrics if (ts := (m.valid_at or m.observed_at or m.issued_at)) is not None
    ]
    latest_at = max(candidates) if candidates else None
    reference = asof if asof is not None else kst_now()
    is_stale = latest_at is None or (reference - latest_at).total_seconds() > freshness_seconds
    return WeatherCard(
        feature_id=feature_id,
        asof=asof,
        source_styles=source_styles,
        metrics=metrics,
        latest_at=latest_at,
        is_stale=is_stale,
    )


async def build_weather_card(
    session: AsyncSession,
    *,
    feature_id: str,
    asof: datetime | None = None,
    freshness_seconds: int = DEFAULT_WEATHER_FRESHNESS_SECONDS,
) -> WeatherCard:
    """공개 Feature와 공개 anchor만 사용하는 weather card."""

    return await _build_weather_card(
        session,
        feature_id=feature_id,
        asof=asof,
        freshness_seconds=freshness_seconds,
        nearest_weather_sql=_NEAREST_WEATHER_SQL,
        nearest_kma_forecast_sql=_NEAREST_KMA_FORECAST_SQL,
        nearest_observed_temp_sql=_NEAREST_OBSERVED_TEMP_SQL,
    )


async def build_admin_weather_card(
    session: AsyncSession,
    *,
    feature_id: str,
    asof: datetime | None = None,
    freshness_seconds: int = DEFAULT_WEATHER_FRESHNESS_SECONDS,
) -> WeatherCard:
    """삭제 전 base Feature와 base anchor를 사용하는 admin weather card."""

    return await _build_weather_card(
        session,
        feature_id=feature_id,
        asof=asof,
        freshness_seconds=freshness_seconds,
        nearest_weather_sql=_ADMIN_NEAREST_WEATHER_SQL,
        nearest_kma_forecast_sql=_ADMIN_NEAREST_KMA_FORECAST_SQL,
        nearest_observed_temp_sql=_ADMIN_NEAREST_OBSERVED_TEMP_SQL,
    )
