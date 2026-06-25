"""feature_price_values 적재 테이블.

Revision ID: 0034_feature_price_values
Revises: 0033_pinvi_poi_cache_metadata
Create Date: 2026-06-25

``PriceValue`` DTO를 영속화하는 ``feature.feature_price_values``를 추가한다.
PK는 결정적 ``price_value_key``(`make_price_value_key`, identity tuple)이고,
latest/card 조회용 복합 인덱스와 시계열 ``observed_at`` BRIN 인덱스를 둔다.
FK는 price-kind anchor ``feature``로 CASCADE, source 추적은 nullable FK로 보존한다.
이 revision은 N150 운영 DB에 먼저 적용된 상태라 main Alembic graph에서도
동일 revision ID를 유지한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034_feature_price_values"
down_revision: str | Sequence[str] | None = "0033_pinvi_poi_cache_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feature.feature_price_values (
            price_value_key       TEXT PRIMARY KEY,
            feature_id            TEXT NOT NULL
                REFERENCES feature.features(feature_id) ON DELETE CASCADE,
            provider              TEXT NOT NULL,
            price_domain          TEXT NOT NULL,
            product_key           TEXT NOT NULL,
            product_name          TEXT,
            source_product_key    TEXT,
            source_product_name   TEXT,
            observed_at           TIMESTAMPTZ NOT NULL,
            value_number          NUMERIC(14, 4) NOT NULL,
            unit                  TEXT NOT NULL DEFAULT 'KRW',
            normalization_version TEXT,
            payload               JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_record_key     TEXT
                REFERENCES provider_sync.source_records(source_record_key)
                ON DELETE SET NULL,
            collected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_price_value_nonnegative
                CHECK (value_number >= 0),
            CONSTRAINT uq_price_value_identity
                UNIQUE (
                    feature_id,
                    provider,
                    price_domain,
                    product_key,
                    observed_at
                )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_price_values_feature_product_observed
        ON feature.feature_price_values
            (feature_id, price_domain, product_key, observed_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_price_values_domain_product_observed
        ON feature.feature_price_values
            (provider, price_domain, product_key, observed_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_price_values_source_record
        ON feature.feature_price_values (source_record_key)
        WHERE source_record_key IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_price_values_observed_at_brin
        ON feature.feature_price_values USING BRIN (observed_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feature.feature_price_values")
