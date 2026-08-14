"""import_jobs batch DAG columns (ADR-045 T-205d).

Revision ID: 0012_import_jobs_batch_columns
Revises: 0011_offline_uploads
Create Date: 2026-06-04

T-200 full-load orchestration이 root import job과 provider child job을 같은
load batch로 묶을 수 있도록 ``ops.import_jobs``에 배치 식별자와 self-parent
관계를 추가한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_import_jobs_batch_columns"
down_revision: str | Sequence[str] | None = "0011_offline_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "import_jobs",
        sa.Column("load_batch_id", postgresql.UUID(as_uuid=False), nullable=True),
        schema="ops",
    )
    op.add_column(
        "import_jobs",
        sa.Column("parent_job_id", postgresql.UUID(as_uuid=False), nullable=True),
        schema="ops",
    )
    op.create_foreign_key(
        "fk_import_jobs_parent_job_id",
        "import_jobs",
        "import_jobs",
        ["parent_job_id"],
        ["job_id"],
        source_schema="ops",
        referent_schema="ops",
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_import_jobs_load_batch_created",
        "import_jobs",
        ["load_batch_id", sa.text("created_at DESC"), sa.text("job_id DESC")],
        schema="ops",
        postgresql_where=sa.text("load_batch_id IS NOT NULL"),
    )
    op.create_index(
        "idx_import_jobs_parent_created",
        "import_jobs",
        ["parent_job_id", sa.text("created_at DESC"), sa.text("job_id DESC")],
        schema="ops",
        postgresql_where=sa.text("parent_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_import_jobs_parent_created", table_name="import_jobs", schema="ops")
    op.drop_index(
        "idx_import_jobs_load_batch_created",
        table_name="import_jobs",
        schema="ops",
    )
    op.drop_constraint(
        "fk_import_jobs_parent_job_id",
        "import_jobs",
        schema="ops",
        type_="foreignkey",
    )
    op.drop_column("import_jobs", "parent_job_id", schema="ops")
    op.drop_column("import_jobs", "load_batch_id", schema="ops")
