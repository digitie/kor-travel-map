"""T-216f REST 명명 수렴을 물리 schema까지 반영.

Revision ID: 0023_t216f_rest_names
Revises: 0022_pg_prewarm_extension
Create Date: 2026-06-10

ADR-048의 REST 표면 정리(``*_key`` -> ``*_id``, 작업 상태 ``state`` -> ``status``)
를 ORM/repository와 같은 물리 DB 명명으로 수렴한다. provider/source 자연키와
``feature_id``/``target_key``는 기존 의미를 유지한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023_t216f_rest_names"
down_revision: str | Sequence[str] | None = "0022_pg_prewarm_extension"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename_constraint(table: str, old: str, new: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = '{table}'::regclass
                  AND conname = '{old}'
            ) THEN
                ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new};
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    # 재생성할 인덱스는 column rename 전에 제거한다.
    op.execute("DROP INDEX IF EXISTS ops.idx_dedup_status_score")
    op.execute("DROP INDEX IF EXISTS ops.idx_enrichment_review_status_score")
    op.execute("DROP INDEX IF EXISTS ops.idx_enrichment_review_provider_status_score")
    op.execute("DROP INDEX IF EXISTS ops.idx_violations_status_detected")
    op.execute("DROP INDEX IF EXISTS ops.idx_violations_provider_status_detected")
    op.execute("DROP INDEX IF EXISTS ops.idx_violations_feature_detected")
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_state")
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_kind_state")
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_heartbeat")
    op.execute("DROP INDEX IF EXISTS ops.idx_offline_uploads_state")
    op.execute("DROP INDEX IF EXISTS ops.idx_feature_update_state_priority")
    op.execute("DROP INDEX IF EXISTS ops.idx_system_log_keyset")
    op.execute("DROP INDEX IF EXISTS ops.idx_api_call_log_keyset")

    op.execute(
        "ALTER TABLE ops.dedup_review_queue RENAME COLUMN review_key TO review_id"
    )
    op.execute(
        "ALTER TABLE ops.enrichment_review_queue "
        "RENAME COLUMN review_key TO review_id"
    )
    op.execute(
        "ALTER TABLE ops.feature_merge_history RENAME COLUMN review_key TO review_id"
    )
    op.execute(
        "ALTER TABLE ops.data_integrity_violations "
        "RENAME COLUMN violation_key TO issue_id"
    )
    op.execute(
        "ALTER TABLE ops.feature_overrides RENAME COLUMN override_key TO override_id"
    )
    op.execute(
        "ALTER TABLE ops.system_log RENAME COLUMN system_log_key TO system_log_id"
    )
    op.execute(
        "ALTER TABLE ops.api_call_log RENAME COLUMN api_call_log_key TO api_call_log_id"
    )
    op.execute("ALTER TABLE ops.import_jobs RENAME COLUMN state TO status")
    op.execute("ALTER TABLE ops.offline_uploads RENAME COLUMN state TO status")
    op.execute(
        "ALTER TABLE ops.feature_update_requests RENAME COLUMN state TO status"
    )

    _rename_constraint(
        "ops.import_jobs", "ck_import_jobs_state", "ck_import_jobs_status"
    )
    _rename_constraint(
        "ops.offline_uploads",
        "ck_offline_uploads_state",
        "ck_offline_uploads_status",
    )
    _rename_constraint(
        "ops.feature_update_requests",
        "ck_feature_update_state",
        "ck_feature_update_status",
    )

    op.execute(
        """
        CREATE INDEX idx_dedup_status_score
        ON ops.dedup_review_queue (status, total_score DESC, review_id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_enrichment_review_status_score
        ON ops.enrichment_review_queue (status, name_score DESC, review_id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_enrichment_review_provider_status_score
        ON ops.enrichment_review_queue (
            source_provider, status, name_score DESC, review_id DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_violations_status_detected
        ON ops.data_integrity_violations (
            status, detected_at DESC, issue_id DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_violations_provider_status_detected
        ON ops.data_integrity_violations (
            provider, status, detected_at DESC, issue_id DESC
        )
        WHERE provider IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_violations_feature_detected
        ON ops.data_integrity_violations (
            feature_id, detected_at DESC, issue_id DESC
        )
        WHERE feature_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_jobs_status
        ON ops.import_jobs (status, created_at, queue_sequence)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_jobs_kind_status
        ON ops.import_jobs (kind, status, created_at DESC, job_id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_jobs_heartbeat
        ON ops.import_jobs (heartbeat_at)
        WHERE status='running'
        """
    )
    op.execute(
        """
        CREATE INDEX idx_offline_uploads_status
        ON ops.offline_uploads (status, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_feature_update_status_priority
        ON ops.feature_update_requests (status, priority DESC, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_system_log_keyset
        ON ops.system_log (created_at DESC, system_log_id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_api_call_log_keyset
        ON ops.api_call_log (created_at DESC, api_call_log_id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ops.idx_api_call_log_keyset")
    op.execute("DROP INDEX IF EXISTS ops.idx_system_log_keyset")
    op.execute("DROP INDEX IF EXISTS ops.idx_feature_update_status_priority")
    op.execute("DROP INDEX IF EXISTS ops.idx_offline_uploads_status")
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_heartbeat")
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_kind_status")
    op.execute("DROP INDEX IF EXISTS ops.idx_import_jobs_status")
    op.execute("DROP INDEX IF EXISTS ops.idx_violations_feature_detected")
    op.execute("DROP INDEX IF EXISTS ops.idx_violations_provider_status_detected")
    op.execute("DROP INDEX IF EXISTS ops.idx_violations_status_detected")
    op.execute("DROP INDEX IF EXISTS ops.idx_enrichment_review_provider_status_score")
    op.execute("DROP INDEX IF EXISTS ops.idx_enrichment_review_status_score")
    op.execute("DROP INDEX IF EXISTS ops.idx_dedup_status_score")

    _rename_constraint(
        "ops.import_jobs", "ck_import_jobs_status", "ck_import_jobs_state"
    )
    _rename_constraint(
        "ops.offline_uploads",
        "ck_offline_uploads_status",
        "ck_offline_uploads_state",
    )
    _rename_constraint(
        "ops.feature_update_requests",
        "ck_feature_update_status",
        "ck_feature_update_state",
    )

    op.execute("ALTER TABLE ops.feature_update_requests RENAME COLUMN status TO state")
    op.execute("ALTER TABLE ops.offline_uploads RENAME COLUMN status TO state")
    op.execute("ALTER TABLE ops.import_jobs RENAME COLUMN status TO state")
    op.execute(
        "ALTER TABLE ops.api_call_log RENAME COLUMN api_call_log_id TO api_call_log_key"
    )
    op.execute(
        "ALTER TABLE ops.system_log RENAME COLUMN system_log_id TO system_log_key"
    )
    op.execute(
        "ALTER TABLE ops.feature_overrides RENAME COLUMN override_id TO override_key"
    )
    op.execute(
        "ALTER TABLE ops.data_integrity_violations "
        "RENAME COLUMN issue_id TO violation_key"
    )
    op.execute(
        "ALTER TABLE ops.feature_merge_history RENAME COLUMN review_id TO review_key"
    )
    op.execute(
        "ALTER TABLE ops.enrichment_review_queue "
        "RENAME COLUMN review_id TO review_key"
    )
    op.execute(
        "ALTER TABLE ops.dedup_review_queue RENAME COLUMN review_id TO review_key"
    )

    op.execute(
        """
        CREATE INDEX idx_api_call_log_keyset
        ON ops.api_call_log (created_at DESC, api_call_log_key DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_system_log_keyset
        ON ops.system_log (created_at DESC, system_log_key DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_feature_update_state_priority
        ON ops.feature_update_requests (state, priority DESC, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_offline_uploads_state
        ON ops.offline_uploads (state, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_jobs_heartbeat
        ON ops.import_jobs (heartbeat_at)
        WHERE state='running'
        """
    )
    op.execute(
        """
        CREATE INDEX idx_import_jobs_kind_state
        ON ops.import_jobs (kind, state, created_at DESC, job_id DESC)
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
        CREATE INDEX idx_violations_feature_detected
        ON ops.data_integrity_violations (
            feature_id, detected_at DESC, violation_key DESC
        )
        WHERE feature_id IS NOT NULL
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
        CREATE INDEX idx_violations_status_detected
        ON ops.data_integrity_violations (
            status, detected_at DESC, violation_key DESC
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
    op.execute(
        """
        CREATE INDEX idx_enrichment_review_status_score
        ON ops.enrichment_review_queue (status, name_score DESC, review_key DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_dedup_status_score
        ON ops.dedup_review_queue (status, total_score DESC, review_key DESC)
        """
    )
