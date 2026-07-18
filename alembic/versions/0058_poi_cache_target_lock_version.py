"""POI cache target에 server-owned entity version을 추가한다.

Revision ID: 0058_poi_target_lock_version
Revises: 0057_import_job_event_scope
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0058_poi_target_lock_version"
down_revision: str | Sequence[str] | None = "0057_import_job_event_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "poi_cache_targets",
        sa.Column(
            "lock_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema="ops",
    )
    op.create_check_constraint(
        "ck_poi_cache_targets_lock_version",
        "poi_cache_targets",
        "lock_version >= 1",
        schema="ops",
    )
    op.execute(
        """
        CREATE FUNCTION ops.force_poi_cache_target_lock_version()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            NEW.lock_version := OLD.lock_version + 1;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_poi_cache_targets_lock_version "
        "BEFORE UPDATE ON ops.poi_cache_targets "
        "FOR EACH ROW EXECUTE FUNCTION ops.force_poi_cache_target_lock_version()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_poi_cache_targets_lock_version "
        "ON ops.poi_cache_targets"
    )
    op.execute("DROP FUNCTION ops.force_poi_cache_target_lock_version()")
    op.drop_constraint(
        "ck_poi_cache_targets_lock_version",
        "poi_cache_targets",
        schema="ops",
        type_="check",
    )
    op.drop_column("poi_cache_targets", "lock_version", schema="ops")
