"""offline upload metadata for Dagster load job (ADR-045 D-14).

Revision ID: 0011_offline_uploads
Revises: 0010_feature_overrides
Create Date: 2026-06-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_offline_uploads"
down_revision: str | Sequence[str] | None = "0010_feature_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "offline_uploads",
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("dataset_key", sa.Text(), nullable=False),
        sa.Column(
            "sync_scope",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_backend", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("detected_format", sa.Text(), nullable=True),
        sa.Column("detected_encoding", sa.Text(), nullable=True),
        sa.Column(
            "state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'uploaded'"),
        ),
        sa.Column(
            "validation_job_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "load_job_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("ops.import_jobs.job_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "state IN ("
            "'uploaded','validating','validated','validation_failed',"
            "'loading','loaded','load_failed','cancelled'"
            ")",
            name="ck_offline_uploads_state",
        ),
        sa.CheckConstraint("byte_size >= 0", name="ck_offline_uploads_byte_size"),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_offline_uploads_checksum_sha256",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_offline_uploads_provider_dataset",
        "offline_uploads",
        ["provider", "dataset_key", sa.text("created_at DESC")],
        schema="ops",
    )
    op.create_index(
        "idx_offline_uploads_state",
        "offline_uploads",
        ["state", sa.text("created_at DESC")],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_offline_uploads_state",
        table_name="offline_uploads",
        schema="ops",
    )
    op.drop_index(
        "idx_offline_uploads_provider_dataset",
        table_name="offline_uploads",
        schema="ops",
    )
    op.drop_table("offline_uploads", schema="ops")
