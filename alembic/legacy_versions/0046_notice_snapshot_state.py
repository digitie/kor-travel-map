"""notice snapshot/event scope와 계보 lifecycle 상태를 저장한다.

Revision ID: 0046_notice_snapshot_state
Revises: 0045_curation_collections
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0046_notice_snapshot_state"
down_revision: str | Sequence[str] | None = "0045_curation_collections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE provider_sync.notice_lifecycle_scopes (
            provider text NOT NULL,
            dataset_key text NOT NULL,
            source_entity_type text NOT NULL,
            mode text NOT NULL,
            applied_at timestamptz NOT NULL,
            state_fingerprint text NOT NULL,
            CONSTRAINT pk_notice_lifecycle_scopes PRIMARY KEY (
                provider, dataset_key, source_entity_type
            ),
            CONSTRAINT ck_notice_lifecycle_scopes_mode
                CHECK (mode IN ('snapshot', 'event'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE provider_sync.notice_lineage_states (
            provider text NOT NULL,
            dataset_key text NOT NULL,
            source_entity_type text NOT NULL,
            lineage_key text NOT NULL,
            present boolean NOT NULL,
            changed_at timestamptz NOT NULL,
            valid_until timestamptz NULL,
            CONSTRAINT pk_notice_lineage_states PRIMARY KEY (
                provider, dataset_key, source_entity_type, lineage_key
            ),
            CONSTRAINT fk_notice_lineage_states_scope FOREIGN KEY (
                provider, dataset_key, source_entity_type
            ) REFERENCES provider_sync.notice_lifecycle_scopes (
                provider, dataset_key, source_entity_type
            ) ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM provider_sync.notice_lifecycle_scopes
            ) OR EXISTS (
                SELECT 1 FROM provider_sync.notice_lineage_states
            ) THEN
                RAISE EXCEPTION
                    '0046 downgrade refused: notice lifecycle state is not empty';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP TABLE provider_sync.notice_lineage_states")
    op.execute("DROP TABLE provider_sync.notice_lifecycle_scopes")
