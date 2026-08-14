"""cache target snapshot GC의 referenced 보존 추세를 영속화한다.

Revision ID: 0078_cache_target_gc_observe
Revises: 0077_cache_target_snapshot_gc
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0078_cache_target_gc_observe"
down_revision: str | Sequence[str] | None = "0077_cache_target_snapshot_gc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "poi_cache_target_snapshot_gc_observations",
        sa.Column(
            "observation_id",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column("dagster_run_id", sa.Text(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("referenced_items", sa.BigInteger(), nullable=False),
        sa.Column("referenced_headers", sa.BigInteger(), nullable=False),
        sa.Column("previous_observation_run_id", sa.Text(), nullable=True),
        sa.Column(
            "previous_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("previous_referenced_items", sa.BigInteger(), nullable=True),
        sa.Column("previous_referenced_headers", sa.BigInteger(), nullable=True),
        sa.Column("growth_baseline_run_id", sa.Text(), nullable=True),
        sa.Column(
            "growth_baseline_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "growth_baseline_referenced_items",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "growth_baseline_referenced_headers",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column("growth_baseline_eligible", sa.Boolean(), nullable=False),
        sa.Column("growth_min_interval_seconds", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "(previous_observation_run_id IS NULL "
            "AND previous_observed_at IS NULL "
            "AND previous_referenced_items IS NULL "
            "AND previous_referenced_headers IS NULL) OR "
            "(previous_observation_run_id IS NOT NULL "
            "AND previous_observation_run_id = btrim(previous_observation_run_id) "
            "AND previous_observation_run_id <> '' "
            "AND length(previous_observation_run_id) <= 255 "
            "AND previous_observation_run_id <> dagster_run_id "
            "AND previous_observed_at IS NOT NULL "
            "AND previous_referenced_items IS NOT NULL "
            "AND previous_referenced_items >= 0 "
            "AND previous_referenced_headers IS NOT NULL "
            "AND previous_referenced_headers >= 0)",
            name=op.f("ck_cache_target_snapshot_gc_observations_previous"),
        ),
        sa.CheckConstraint(
            "dagster_run_id = btrim(dagster_run_id) "
            "AND dagster_run_id <> '' "
            "AND length(dagster_run_id) <= 255",
            name=op.f("ck_cache_target_snapshot_gc_observations_run_id"),
        ),
        sa.CheckConstraint(
            "referenced_items >= 0 AND referenced_headers >= 0",
            name=op.f("ck_cache_target_snapshot_gc_observations_counts"),
        ),
        sa.CheckConstraint(
            "growth_min_interval_seconds BETWEEN 1 AND 86400",
            name=op.f("ck_cache_target_snapshot_gc_observations_growth_interval"),
        ),
        sa.CheckConstraint(
            "(growth_baseline_run_id IS NULL "
            "AND growth_baseline_observed_at IS NULL "
            "AND growth_baseline_referenced_items IS NULL "
            "AND growth_baseline_referenced_headers IS NULL) OR "
            "(growth_baseline_run_id IS NOT NULL "
            "AND growth_baseline_run_id = btrim(growth_baseline_run_id) "
            "AND growth_baseline_run_id <> '' "
            "AND length(growth_baseline_run_id) <= 255 "
            "AND growth_baseline_run_id <> dagster_run_id "
            "AND growth_baseline_observed_at IS NOT NULL "
            "AND growth_baseline_referenced_items IS NOT NULL "
            "AND growth_baseline_referenced_items >= 0 "
            "AND growth_baseline_referenced_headers IS NOT NULL "
            "AND growth_baseline_referenced_headers >= 0)",
            name=op.f("ck_cache_target_snapshot_gc_observations_growth_baseline"),
        ),
        sa.CheckConstraint(
            "(growth_baseline_run_id IS NULL "
            "AND growth_baseline_eligible = ("
            "previous_observation_run_id IS NULL "
            "OR observed_at > previous_observed_at)) OR "
            "(growth_baseline_run_id IS NOT NULL "
            "AND growth_baseline_eligible = ("
            "observed_at > growth_baseline_observed_at "
            "AND (previous_observation_run_id IS NULL "
            "OR observed_at > previous_observed_at) "
            "AND extract(epoch FROM observed_at - growth_baseline_observed_at) "
            ">= growth_min_interval_seconds))",
            name=op.f("ck_cache_target_snapshot_gc_observations_eligibility"),
        ),
        sa.PrimaryKeyConstraint(
            "observation_id",
            name=op.f("pk_cache_target_snapshot_gc_observations"),
        ),
        sa.UniqueConstraint(
            "dagster_run_id",
            name=op.f("uq_cache_target_snapshot_gc_observations_run_id"),
        ),
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_snapshot_gc_observations_time",
        "poi_cache_target_snapshot_gc_observations",
        ["observed_at"],
        schema="ops",
    )
    op.create_index(
        "idx_cache_target_snapshot_gc_observations_growth_baseline",
        "poi_cache_target_snapshot_gc_observations",
        ["observation_id"],
        unique=False,
        schema="ops",
        postgresql_where=sa.text("growth_baseline_eligible"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_cache_target_snapshot_gc_observations_growth_baseline",
        table_name="poi_cache_target_snapshot_gc_observations",
        schema="ops",
    )
    op.drop_index(
        "idx_cache_target_snapshot_gc_observations_time",
        table_name="poi_cache_target_snapshot_gc_observations",
        schema="ops",
    )
    op.drop_table(
        "poi_cache_target_snapshot_gc_observations",
        schema="ops",
    )
