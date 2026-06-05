"""offline upload checksum idempotency (T-RV-23).

Revision ID: 0016_offline_upload_idempotency
Revises: 0015_feature_coord_precision
Create Date: 2026-06-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016_offline_upload_idempotency"
down_revision: str | Sequence[str] | None = "0015_feature_coord_precision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "uq_offline_uploads_provider_dataset_scope_checksum"


def upgrade() -> None:
    op.create_unique_constraint(
        _CONSTRAINT,
        "offline_uploads",
        ["provider", "dataset_key", "sync_scope", "checksum_sha256"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT,
        "offline_uploads",
        schema="ops",
        type_="unique",
    )
