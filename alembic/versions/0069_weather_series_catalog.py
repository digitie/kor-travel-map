"""weather physical-series registry와 weather-only 공간 인덱스.

Revision ID: 0069_weather_series_catalog
Revises: 0068_integrity_last_seen
Create Date: 2026-07-30

대용량 weather fact에서 매 요청마다 열린 ``forecast_style × metric_key`` 집합을
``DISTINCT``로 재발견하면 source 하나의 전체 history를 읽는다. 이 revision은
provider/domain까지 포함한 작은 physical-series registry를 만들고 writer trigger로
단조롭게 유지한다. series row가 stale이어도 predecessor 조회가 0행이므로 read
정확성에는 영향을 주지 않는다.

nearest 공유 anchor는 ``WeatherValue`` 계약의 canonical ``kind='weather'``만 허용한다.
공개 weather Feature 전용 partial GiST가 백만 개 이상의 일반 POI를 KNN 후보에서
제외한다. effective-time 인덱스는 series exact prefix 뒤에 시간축을 두어 series별
predecessor와 24시간 range를 index range scan으로 처리한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0069_weather_series_catalog"
down_revision: str | Sequence[str] | None = "0068_integrity_last_seen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EFFECTIVE_INDEX = "idx_weather_values_feature_effective"
_WEATHER_GIST = "idx_features_public_weather_coord_5179_gist"


def _index_is_valid(index_name: str) -> bool:
    return (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT index_.indisvalid
                FROM pg_catalog.pg_index AS index_
                JOIN pg_catalog.pg_class AS index_relation
                  ON index_relation.oid = index_.indexrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = index_relation.relnamespace
                WHERE namespace.nspname = 'feature'
                  AND index_relation.relname = :index_name
                """
            ),
            {"index_name": index_name},
        )
        .scalar_one_or_none()
        is True
    )


def _create_concurrent_index_unless_valid(
    index_name: str,
    create_statement: str,
) -> None:
    if _index_is_valid(index_name):
        return
    op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS feature.{index_name}")
    op.execute(create_statement)


def _create_series_table_and_trigger() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS feature.weather_metric_series (
            feature_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            weather_domain TEXT NOT NULL,
            forecast_style TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            CONSTRAINT weather_metric_series_pkey PRIMARY KEY (
                feature_id,
                provider,
                weather_domain,
                forecast_style,
                metric_key
            ),
            CONSTRAINT fk_weather_metric_series_feature
                FOREIGN KEY (feature_id)
                REFERENCES feature.features(feature_id)
                ON DELETE CASCADE
        )
        """
    )
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE OR REPLACE FUNCTION feature.register_weather_metric_series()
            RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = pg_catalog, feature
            AS $function$
            BEGIN
                INSERT INTO feature.weather_metric_series (
                    feature_id,
                    provider,
                    weather_domain,
                    forecast_style,
                    metric_key
                )
                VALUES (
                    NEW.feature_id,
                    NEW.provider,
                    NEW.weather_domain,
                    NEW.forecast_style,
                    NEW.metric_key
                )
                ON CONFLICT DO NOTHING;
                RETURN NEW;
            END
            $function$
            """
        )
        op.execute(
            """
            DROP TRIGGER IF EXISTS trg_register_weather_metric_series
            ON feature.feature_weather_values
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_register_weather_metric_series
            AFTER INSERT OR UPDATE OF
                feature_id,
                provider,
                weather_domain,
                forecast_style,
                metric_key
            ON feature.feature_weather_values
            FOR EACH ROW
            EXECUTE FUNCTION feature.register_weather_metric_series()
            """
        )


def upgrade() -> None:
    _create_series_table_and_trigger()
    op.execute(
        """
        INSERT INTO feature.weather_metric_series (
            feature_id,
            provider,
            weather_domain,
            forecast_style,
            metric_key
        )
        SELECT DISTINCT
            feature_id,
            provider,
            weather_domain,
            forecast_style,
            metric_key
        FROM feature.feature_weather_values
        ON CONFLICT DO NOTHING
        """
    )

    with op.get_context().autocommit_block():
        _create_concurrent_index_unless_valid(
            _EFFECTIVE_INDEX,
            f"""
            CREATE INDEX CONCURRENTLY {_EFFECTIVE_INDEX}
            ON feature.feature_weather_values (
                feature_id,
                provider,
                weather_domain,
                forecast_style,
                metric_key,
                (
                    COALESCE(
                        valid_at,
                        observed_at,
                        valid_from,
                        issued_at
                    )
                ) DESC,
                issued_at DESC NULLS LAST,
                collected_at DESC,
                weather_value_key
            )
            """,
        )
        _create_concurrent_index_unless_valid(
            _WEATHER_GIST,
            f"""
            CREATE INDEX CONCURRENTLY {_WEATHER_GIST}
            ON feature.features USING gist (coord_5179)
            WHERE status = 'active'
              AND deleted_at IS NULL
              AND kind = 'weather'
              AND coord_5179 IS NOT NULL
            """,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS feature.{_WEATHER_GIST}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS feature.{_EFFECTIVE_INDEX}")
        op.execute(
            """
            DROP TRIGGER IF EXISTS trg_register_weather_metric_series
            ON feature.feature_weather_values
            """
        )
        op.execute(
            "DROP FUNCTION IF EXISTS feature.register_weather_metric_series()"
        )
        op.execute("DROP TABLE IF EXISTS feature.weather_metric_series")
