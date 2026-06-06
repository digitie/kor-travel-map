"""feature_weather_values 적재 테이블 (T-213e, ADR-010/013).

Revision ID: 0017_feature_weather_values
Revises: 0016_offline_upload_idempotency
Create Date: 2026-06-06

``WeatherValue`` DTO(ADR-010 — forecast_style + timeline_bucket 두 축)를 영속화하는
``feature.feature_weather_values``를 추가한다. PK는 결정적 ``weather_value_key``
(`make_weather_value_key`, identity tuple). card 조회용 복합 인덱스 + 시계열 BRIN
(`valid_at`, ADR-013 성능 가이드). FK는 weather kind ``feature``로 CASCADE.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_feature_weather_values"
down_revision: str | Sequence[str] | None = "0016_offline_upload_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feature.feature_weather_values (
            weather_value_key      TEXT PRIMARY KEY,
            feature_id             TEXT NOT NULL
                REFERENCES feature.features(feature_id) ON DELETE CASCADE,
            provider               TEXT NOT NULL,
            weather_domain         TEXT NOT NULL,
            forecast_style         TEXT NOT NULL,
            timeline_bucket        TEXT,
            metric_key             TEXT NOT NULL,
            metric_name            TEXT,
            source_metric_key      TEXT,
            source_metric_name     TEXT,
            value_number           NUMERIC(14, 4),
            value_text             TEXT,
            unit                   TEXT,
            severity               TEXT,
            issued_at              TIMESTAMPTZ,
            valid_at               TIMESTAMPTZ,
            valid_from             TIMESTAMPTZ,
            valid_until            TIMESTAMPTZ,
            observed_at            TIMESTAMPTZ,
            normalization_version  TEXT,
            payload                JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_record_key      TEXT,
            collected_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_weather_value_present
                CHECK (value_number IS NOT NULL OR value_text IS NOT NULL)
        )
        """
    )
    # card 조회: feature별 (forecast_style, metric_key)의 최신값 — DISTINCT ON 정렬축.
    op.execute(
        """
        CREATE INDEX idx_weather_values_feature_card
        ON feature.feature_weather_values
            (feature_id, forecast_style, metric_key, valid_at DESC)
        """
    )
    # 시계열 BRIN (ADR-013 성능 가이드).
    op.execute(
        """
        CREATE INDEX brin_weather_values_valid_at
        ON feature.feature_weather_values USING BRIN (valid_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feature.feature_weather_values")
