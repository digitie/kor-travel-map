"""T-212d hot read/keyset 성능 인덱스.

Revision ID: 0020_t212d_perf_keyset_indexes
Revises: 0019_enrichment_review_queue
Create Date: 2026-06-08

지도/API/admin/ops의 hot read는 대부분 keyset pagination 형태다. 기존 일부
인덱스는 정렬 tie-breaker UUID/feature_id가 없거나, 단일 컬럼만 있어 대량
데이터에서 Sort/Bitmap 재검사가 커질 수 있었다. T-212d 기준으로 실제 조회
정렬축과 필터축을 함께 커버하도록 보강한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020_t212d_perf_keyset_indexes"
down_revision: str | Sequence[str] | None = "0019_enrichment_review_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # feature.features: admin/features 정렬축 + status 필터 keyset.
    op.execute("DROP INDEX IF EXISTS feature.idx_features_status_updated")
    op.execute(
        """
        CREATE INDEX idx_features_updated_keyset
        ON feature.features (updated_at DESC, feature_id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_features_status_updated
        ON feature.features (status, updated_at DESC, feature_id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_features_lower_name_keyset
        ON feature.features (lower(name), feature_id)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_features_opening_hours_keyset
        ON feature.features (feature_id)
        WHERE deleted_at IS NULL
          AND detail IS NOT NULL
          AND detail <> '{}'::jsonb
          AND detail ?| ARRAY['business_hours','opening_hours']
        """
    )

    # ops.import_jobs: 목록 keyset과 queue FIFO tie-breaker를 분리한다.
    op.execute("CREATE SEQUENCE IF NOT EXISTS ops.import_jobs_queue_sequence_seq")
    op.execute(
        """
        ALTER TABLE ops.import_jobs
        ADD COLUMN IF NOT EXISTS queue_sequence bigint
        """
    )
    op.execute(
        """
        WITH ordered AS (
            SELECT
                job_id,
                row_number() OVER (ORDER BY created_at, job_id) AS seq
            FROM ops.import_jobs
            WHERE queue_sequence IS NULL
        )
        UPDATE ops.import_jobs AS j
        SET queue_sequence = ordered.seq
        FROM ordered
        WHERE j.job_id = ordered.job_id
        """
    )
    op.execute(
        """
        SELECT CASE
            WHEN max(queue_sequence) IS NULL
            THEN setval('ops.import_jobs_queue_sequence_seq'::regclass, 1, false)
            ELSE setval(
                'ops.import_jobs_queue_sequence_seq'::regclass,
                max(queue_sequence),
                true
            )
        END
        FROM ops.import_jobs
        """
    )
    op.execute(
        """
        ALTER TABLE ops.import_jobs
        ALTER COLUMN queue_sequence
        SET DEFAULT nextval('ops.import_jobs_queue_sequence_seq'::regclass)
        """
    )
    op.execute(
        """
        ALTER SEQUENCE ops.import_jobs_queue_sequence_seq
        OWNED BY ops.import_jobs.queue_sequence
        """
    )
    op.execute(
        """
        ALTER TABLE ops.import_jobs
        ALTER COLUMN queue_sequence SET NOT NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_state")
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_kind_state")
    op.execute(
        """
        CREATE INDEX idx_import_jobs_created_keyset
        ON ops.import_jobs (created_at DESC, job_id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_jobs_state
        ON ops.import_jobs (state, created_at, queue_sequence)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_jobs_kind_state
        ON ops.import_jobs (kind, state, created_at DESC, job_id DESC)
        """
    )

    # ops.feature_consistency_reports: latest/list + severity filter.
    op.execute("DROP INDEX IF EXISTS ops.idx_reports_started")
    op.execute(
        """
        CREATE INDEX idx_reports_started
        ON ops.feature_consistency_reports (started_at DESC, report_id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_reports_severity_started
        ON ops.feature_consistency_reports (
            severity_max, started_at DESC, report_id DESC
        )
        """
    )

    # ops.data_integrity_violations: 운영 이슈 목록의 status/provider/feature 필터.
    op.execute(
        """
        CREATE INDEX idx_violations_status_detected
        ON ops.data_integrity_violations (
            status, detected_at DESC, violation_key DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_violations_provider_status_detected
        ON ops.data_integrity_violations (
            provider, status, detected_at DESC, violation_key DESC
        )
        WHERE provider IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_violations_feature_detected
        ON ops.data_integrity_violations (
            feature_id, detected_at DESC, violation_key DESC
        )
        WHERE feature_id IS NOT NULL
        """
    )

    # review 큐: score desc + UUID tie-breaker까지 같은 인덱스에서 처리.
    op.execute("DROP INDEX IF EXISTS ops.idx_dedup_status_score")
    op.execute(
        """
        CREATE INDEX idx_dedup_status_score
        ON ops.dedup_review_queue (
            status, total_score DESC, review_key DESC
        )
        """
    )
    op.execute("DROP INDEX IF EXISTS ops.idx_enrichment_review_status_score")
    op.execute(
        """
        CREATE INDEX idx_enrichment_review_status_score
        ON ops.enrichment_review_queue (
            status, name_score DESC, review_key DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_enrichment_review_provider_status_score
        ON ops.enrichment_review_queue (
            source_provider, status, name_score DESC, review_key DESC
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ops.idx_enrichment_review_provider_status_score")
    op.execute("DROP INDEX IF EXISTS ops.idx_enrichment_review_status_score")
    op.execute(
        """
        CREATE INDEX idx_enrichment_review_status_score
        ON ops.enrichment_review_queue (status, name_score DESC)
        """
    )

    op.execute("DROP INDEX IF EXISTS ops.idx_dedup_status_score")
    op.execute(
        """
        CREATE INDEX idx_dedup_status_score
        ON ops.dedup_review_queue (status, total_score DESC)
        """
    )

    op.execute("DROP INDEX IF EXISTS ops.idx_violations_feature_detected")
    op.execute("DROP INDEX IF EXISTS ops.idx_violations_provider_status_detected")
    op.execute("DROP INDEX IF EXISTS ops.idx_violations_status_detected")

    op.execute("DROP INDEX IF EXISTS ops.idx_reports_severity_started")
    op.execute("DROP INDEX IF EXISTS ops.idx_reports_started")
    op.execute(
        """
        CREATE INDEX idx_reports_started
        ON ops.feature_consistency_reports (started_at DESC)
        """
    )

    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_kind_state")
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_state")
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_created_keyset")
    op.execute(
        """
        ALTER TABLE ops.import_jobs
        DROP COLUMN IF EXISTS queue_sequence
        """
    )
    op.execute("DROP SEQUENCE IF EXISTS ops.import_jobs_queue_sequence_seq")
    op.execute(
        """
        CREATE INDEX idx_import_jobs_kind_state
        ON ops.import_jobs (kind, state, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_jobs_state
        ON ops.import_jobs (state, created_at)
        """
    )

    op.execute("DROP INDEX IF EXISTS feature.idx_features_lower_name_keyset")
    op.execute("DROP INDEX IF EXISTS feature.idx_features_opening_hours_keyset")
    op.execute("DROP INDEX IF EXISTS feature.idx_features_status_updated")
    op.execute("DROP INDEX IF EXISTS feature.idx_features_updated_keyset")
    op.execute(
        """
        CREATE INDEX idx_features_status_updated
        ON feature.features (status, updated_at)
        """
    )
