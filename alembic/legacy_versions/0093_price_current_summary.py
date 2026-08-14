"""T-VN-38B — immutable price facts와 receipt-backed current summary.

Revision ID: 0093_price_current_summary
Revises: 0092_weather_current_summary

서비스 전 cutover이므로 0060 계열의 provider-string/latest-row price history를
보존하지 않는다. provider ETL은 exact operation membership의 canonical dataset과
그 response ``SourceRecord``로 최종 fact를 재적재한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.util.concurrency import await_only

from alembic import op

revision: str = "0093_price_current_summary"
down_revision: str | Sequence[str] | None = "0092_weather_current_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_sql_script(sql: str) -> None:
    raw_connection = op.get_bind().connection.driver_connection
    await_only(raw_connection.execute(sql))


def upgrade() -> None:
    _execute_sql_script(
        """
        -- price도 provider 문자열 current-row를 남기지 않는다. 사실의 producer는
        -- canonical dataset과 immutable raw-response revision으로만 식별한다.
        DROP TABLE feature.feature_price_values;
        CREATE TABLE feature.feature_price_values (
            price_value_key text NOT NULL PRIMARY KEY,
            feature_id text NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
            provider_dataset_id bigint NOT NULL
                REFERENCES provider_sync.provider_datasets(provider_dataset_id),
            price_domain text NOT NULL,
            product_key text NOT NULL,
            product_name text,
            source_product_key text,
            source_product_name text,
            observed_at timestamptz NOT NULL,
            known_at timestamptz NOT NULL,
            value_number numeric(14, 4) NOT NULL,
            unit text NOT NULL DEFAULT 'KRW',
            normalization_version text,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            source_entity_key text NOT NULL,
            source_record_key text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_price_value_source_lineage FOREIGN KEY (
                source_record_key, source_entity_key, known_at
            ) REFERENCES provider_sync.source_records (
                source_record_key, source_entity_key, fetched_at
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_price_value_source_dataset FOREIGN KEY (
                source_entity_key, provider_dataset_id
            ) REFERENCES provider_sync.source_entities (
                source_entity_key, provider_dataset_id
            ) ON DELETE RESTRICT,
            CONSTRAINT ck_price_value_nonnegative CHECK (value_number >= 0),
            CONSTRAINT ck_price_value_payload_object
                CHECK (jsonb_typeof(payload) = 'object'),
            CONSTRAINT uq_price_value_identity UNIQUE (
                feature_id, provider_dataset_id, price_domain, product_key,
                observed_at, source_record_key
            )
        );
        CREATE UNIQUE INDEX uq_price_value_summary_reference
            ON feature.feature_price_values (
                price_value_key, feature_id, provider_dataset_id, price_domain, product_key
            );
        CREATE INDEX idx_price_values_feature_observed_identity
            ON feature.feature_price_values (
                feature_id, observed_at DESC, known_at DESC, provider_dataset_id,
                price_domain, product_key
            );

        CREATE FUNCTION feature.reject_price_value_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            -- parent feature cascade는 derived fact/summary 제거의 유일한 예외다.
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM feature.features AS f WHERE f.feature_id = OLD.feature_id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'feature_price_values facts are immutable (ADR-089)'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_price_values_immutable';
        END;
        $$;
        CREATE TRIGGER trg_feature_price_values_immutable
            BEFORE UPDATE OR DELETE ON feature.feature_price_values
            FOR EACH ROW EXECUTE FUNCTION feature.reject_price_value_mutation();
        CREATE TRIGGER trg_feature_price_values_active_dataset_write
            BEFORE INSERT ON feature.feature_price_values
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

        -- summary는 가격을 복제하지 않는다. natural identity와 selected immutable
        -- fact의 identity가 같은지는 composite FK가 보장한다.
        CREATE TABLE feature.current_price_summary (
            feature_id text NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
            provider_dataset_id bigint NOT NULL
                REFERENCES provider_sync.provider_datasets(provider_dataset_id),
            price_domain text NOT NULL,
            product_key text NOT NULL,
            price_value_key text NOT NULL,
            summary_run_id bigint NOT NULL,
            projection_kind text NOT NULL DEFAULT 'price',
            receipt_status text NOT NULL DEFAULT 'succeeded',
            CONSTRAINT pk_current_price_summary PRIMARY KEY (
                feature_id, provider_dataset_id, price_domain, product_key
            ),
            CONSTRAINT fk_current_price_summary_fact FOREIGN KEY (
                price_value_key, feature_id, provider_dataset_id, price_domain, product_key
            ) REFERENCES feature.feature_price_values (
                price_value_key, feature_id, provider_dataset_id, price_domain, product_key
            ) ON DELETE CASCADE,
            CONSTRAINT fk_current_price_summary_successful_run FOREIGN KEY (
                summary_run_id, projection_kind, receipt_status
            ) REFERENCES ops.current_summary_runs (summary_run_id, projection_kind, status),
            CONSTRAINT ck_current_price_summary_projection_kind
                CHECK (projection_kind = 'price'),
            CONSTRAINT ck_current_price_summary_receipt_status
                CHECK (receipt_status = 'succeeded')
        );
        CREATE INDEX idx_current_price_summary_fact
            ON feature.current_price_summary (price_value_key);
        CREATE TRIGGER trg_current_price_summary_active_dataset_write
            BEFORE INSERT OR UPDATE ON feature.current_price_summary
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        """
    )


def downgrade() -> None:
    raise RuntimeError("0093 is destructive and forward-only; rebuild with provider ETL")
