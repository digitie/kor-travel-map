"""weather 공개 이력 API 조회 인덱스.

외부 시스템이 REST API로 예보 snapshot을 비교할 수 있도록
``feature_weather_values``의 feature+발표시각/유효시각 조회축을 보강한다.
보존 정책은 3년이며, 본 migration은 삭제 작업을 만들지 않는다.

Revision ID: 0043_weather_history_idx
Revises: 0042_rule_detail_selector
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0043_weather_history_idx"
down_revision: str | Sequence[str] | None = "0042_rule_detail_selector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_weather_values_feature_issued_valid
        ON feature.feature_weather_values (
            feature_id,
            issued_at DESC,
            valid_at ASC,
            metric_key,
            forecast_style
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_weather_values_feature_valid_issued
        ON feature.feature_weather_values (
            feature_id,
            valid_at ASC,
            issued_at DESC,
            metric_key,
            forecast_style
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS brin_weather_values_collected_at
        ON feature.feature_weather_values USING BRIN (collected_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_records_kma_alert_history
        ON provider_sync.source_records (
            provider,
            dataset_key,
            source_entity_type,
            fetched_at DESC,
            source_record_key
        )
        WHERE provider = 'python-kma-api'
          AND dataset_key = 'kma_weather_alerts'
          AND source_entity_type = 'weather_alert'
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS provider_sync.idx_source_records_kma_alert_history"
    )
    op.execute("DROP INDEX IF EXISTS feature.brin_weather_values_collected_at")
    op.execute("DROP INDEX IF EXISTS feature.idx_weather_values_feature_valid_issued")
    op.execute("DROP INDEX IF EXISTS feature.idx_weather_values_feature_issued_valid")
