"""T-VN-38A — immutable weather facts와 receipt-backed current summary.

Revision ID: 0092_weather_current_summary
Revises: 0091_tvn33_cutover_fence

서비스 전 단계이므로 기존 provider 문자열/0060 upsert history는 보존하지 않는다.
재적재는 exact operation membership을 가진 provider ETL이 새 source response record와 함께 한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.util.concurrency import await_only

from alembic import op

revision: str = "0092_weather_current_summary"
down_revision: str | Sequence[str] | None = "0091_tvn33_cutover_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_sql_script(sql: str) -> None:
    raw_connection = op.get_bind().connection.driver_connection
    await_only(raw_connection.execute(sql))


def upgrade() -> None:
    _execute_sql_script(
        """
        -- Fact provenance가 source entity의 canonical dataset과 response revision을 함께
        -- 참조할 수 있도록 T-VN-33 source lineage의 composite FK target을 만든다.
        ALTER TABLE provider_sync.source_entities
            ADD CONSTRAINT uq_source_entities_key_dataset
            UNIQUE (source_entity_key, provider_dataset_id);
        ALTER TABLE provider_sync.source_records
            ADD CONSTRAINT uq_source_records_record_entity_fetched
            UNIQUE (source_record_key, source_entity_key, fetched_at);

        CREATE TABLE ops.current_summary_runs (
            summary_run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            projection_kind text NOT NULL,
            run_kind text NOT NULL,
            status text NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            input_count bigint NOT NULL DEFAULT 0,
            inserted_count bigint NOT NULL DEFAULT 0,
            updated_count bigint NOT NULL DEFAULT 0,
            deleted_count bigint NOT NULL DEFAULT 0,
            scope jsonb NOT NULL DEFAULT '{}'::jsonb,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT uq_current_summary_runs_receipt_state
                UNIQUE (summary_run_id, projection_kind, status),
            CONSTRAINT ck_current_summary_runs_projection_kind
                CHECK (projection_kind IN ('weather', 'price')),
            CONSTRAINT ck_current_summary_runs_run_kind
                CHECK (run_kind IN ('ingest', 'reconcile', 'backfill', 'restore')),
            CONSTRAINT ck_current_summary_runs_status
                CHECK (status IN ('running', 'succeeded', 'failed')),
            CONSTRAINT ck_current_summary_runs_finished_at CHECK (
                (status = 'running' AND finished_at IS NULL)
                OR (status IN ('succeeded', 'failed') AND finished_at >= started_at)
            ),
            CONSTRAINT ck_current_summary_runs_counts_nonnegative CHECK (
                input_count >= 0 AND inserted_count >= 0
                AND updated_count >= 0 AND deleted_count >= 0
            ),
            CONSTRAINT ck_current_summary_runs_scope_object
                CHECK (jsonb_typeof(scope) = 'object'),
            CONSTRAINT ck_current_summary_runs_detail_object
                CHECK (jsonb_typeof(detail) = 'object')
        );
        CREATE INDEX idx_current_summary_runs_projection_finished
            ON ops.current_summary_runs (projection_kind, finished_at DESC)
            WHERE status = 'succeeded';

        CREATE FUNCTION ops.reject_terminal_current_summary_run_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF OLD.status IN ('succeeded', 'failed') THEN
                RAISE EXCEPTION 'terminal current summary receipt is immutable: %',
                    OLD.summary_run_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_current_summary_runs_terminal_immutable';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$;
        CREATE TRIGGER trg_current_summary_runs_terminal_immutable
            BEFORE UPDATE OR DELETE ON ops.current_summary_runs
            FOR EACH ROW EXECUTE FUNCTION ops.reject_terminal_current_summary_run_mutation();

        -- provider 문자열 identity/0060 latest-row upsert를 파기하고 raw response
        -- revision 단위 immutable weather fact를 새로 만든다.
        DROP TABLE feature.feature_weather_values;
        CREATE TABLE feature.feature_weather_values (
            weather_value_key text NOT NULL PRIMARY KEY,
            feature_id text NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
            provider_dataset_id bigint NOT NULL
                REFERENCES provider_sync.provider_datasets(provider_dataset_id),
            weather_domain text NOT NULL,
            forecast_style text NOT NULL,
            timeline_bucket text,
            metric_key text NOT NULL,
            metric_name text,
            source_metric_key text,
            source_metric_name text,
            value_number numeric(14, 4),
            value_text text,
            unit text,
            severity text,
            issued_at timestamptz,
            valid_at timestamptz,
            valid_during tstzrange,
            observed_at timestamptz,
            target_at timestamptz NOT NULL,
            known_at timestamptz NOT NULL,
            normalization_version text,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            source_entity_key text NOT NULL,
            source_record_key text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_weather_value_source_lineage FOREIGN KEY (
                source_record_key, source_entity_key, known_at
            ) REFERENCES provider_sync.source_records (
                source_record_key, source_entity_key, fetched_at
            ) ON DELETE RESTRICT,
            CONSTRAINT fk_weather_value_source_dataset FOREIGN KEY (
                source_entity_key, provider_dataset_id
            ) REFERENCES provider_sync.source_entities (
                source_entity_key, provider_dataset_id
            ) ON DELETE RESTRICT,
            CONSTRAINT ck_weather_value_present
                CHECK (value_number IS NOT NULL OR value_text IS NOT NULL),
            CONSTRAINT ck_weather_value_valid_during_not_empty
                CHECK (valid_during IS NULL OR NOT isempty(valid_during)),
            CONSTRAINT ck_weather_value_payload_object
                CHECK (jsonb_typeof(payload) = 'object'),
            CONSTRAINT ck_weather_value_bitemporal_order
                CHECK (issued_at IS NULL OR issued_at <= known_at),
            CONSTRAINT uq_weather_value_identity UNIQUE (
                feature_id, provider_dataset_id, weather_domain, forecast_style,
                metric_key, target_at, source_record_key
            )
        );
        CREATE UNIQUE INDEX uq_weather_value_summary_reference
            ON feature.feature_weather_values (
                weather_value_key, feature_id, provider_dataset_id, weather_domain,
                forecast_style, metric_key
            );
        CREATE INDEX idx_weather_values_feature_target_known
            ON feature.feature_weather_values (feature_id, target_at DESC, known_at DESC);

        CREATE FUNCTION feature.reject_weather_value_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM feature.features AS f WHERE f.feature_id = OLD.feature_id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'feature_weather_values facts are immutable (ADR-089)'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_weather_values_immutable';
        END;
        $$;
        CREATE TRIGGER trg_feature_weather_values_immutable
            BEFORE UPDATE OR DELETE ON feature.feature_weather_values
            FOR EACH ROW EXECUTE FUNCTION feature.reject_weather_value_mutation();
        CREATE TRIGGER trg_feature_weather_values_active_dataset_write
            BEFORE INSERT ON feature.feature_weather_values
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

        CREATE TABLE feature.current_weather_summary (
            feature_id text NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
            provider_dataset_id bigint NOT NULL
                REFERENCES provider_sync.provider_datasets(provider_dataset_id),
            weather_domain text NOT NULL,
            forecast_style text NOT NULL,
            metric_key text NOT NULL,
            weather_value_key text NOT NULL,
            summary_run_id bigint NOT NULL,
            selected_at timestamptz NOT NULL,
            refresh_after timestamptz NOT NULL,
            projection_kind text NOT NULL DEFAULT 'weather',
            receipt_status text NOT NULL DEFAULT 'succeeded',
            CONSTRAINT pk_current_weather_summary PRIMARY KEY (
                feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key
            ),
            CONSTRAINT fk_current_weather_summary_fact FOREIGN KEY (
                weather_value_key, feature_id, provider_dataset_id, weather_domain,
                forecast_style, metric_key
            ) REFERENCES feature.feature_weather_values (
                weather_value_key, feature_id, provider_dataset_id, weather_domain,
                forecast_style, metric_key
            ) ON DELETE CASCADE,
            CONSTRAINT fk_current_weather_summary_successful_run FOREIGN KEY (
                summary_run_id, projection_kind, receipt_status
            ) REFERENCES ops.current_summary_runs (summary_run_id, projection_kind, status),
            CONSTRAINT ck_current_weather_summary_projection_kind
                CHECK (projection_kind = 'weather'),
            CONSTRAINT ck_current_weather_summary_receipt_status
                CHECK (receipt_status = 'succeeded'),
            CONSTRAINT ck_current_weather_summary_refresh_after CHECK (refresh_after > selected_at)
        );
        CREATE INDEX idx_current_weather_summary_fact
            ON feature.current_weather_summary (weather_value_key);
        CREATE TRIGGER trg_current_weather_summary_active_dataset_write
            BEFORE INSERT OR UPDATE ON feature.current_weather_summary
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        """
    )


def downgrade() -> None:
    raise RuntimeError("0092 is destructive and forward-only; rebuild with provider ETL")
