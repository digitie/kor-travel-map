"""주소 finding 관측을 불변 run generation으로 정규화한다.

단일 finding payload의 ``observed_run_id``는 겹친 run이 서로 덮어써, 먼저 관측한 run이
살아 있는 finding을 stale로 오판했다. provider/dataset별 단조 generation, run receipt,
run별 dedupe-key 관측 집합을 별도 테이블로 저장하고 authoritative close를 scope row lock으로
직렬화한다.

Revision ID: 0071_integrity_observations
Revises: 0070_domain_command_ledger
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0071_integrity_observations"
down_revision: str | Sequence[str] | None = "0070_domain_command_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integrity_observation_scopes",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("dataset_key", sa.Text(), nullable=False),
        sa.Column(
            "latest_generation",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "latest_authoritative_generation",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "provider = btrim(provider) AND provider <> ''",
            name="ck_integrity_observation_scopes_provider",
        ),
        sa.CheckConstraint(
            "dataset_key = btrim(dataset_key) AND dataset_key <> ''",
            name="ck_integrity_observation_scopes_dataset",
        ),
        sa.CheckConstraint(
            "latest_generation >= 0 "
            "AND latest_authoritative_generation >= 0 "
            "AND latest_authoritative_generation <= latest_generation",
            name="ck_integrity_observation_scopes_generations",
        ),
        sa.PrimaryKeyConstraint(
            "provider",
            "dataset_key",
            name="pk_integrity_observation_scopes",
        ),
        schema="ops",
    )

    op.create_table(
        "integrity_observation_runs",
        sa.Column(
            "observation_run_id",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("dataset_key", sa.Text(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("external_run_id", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'collecting'"),
        ),
        sa.Column(
            "source_observations",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "findings_observed",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "findings_unique",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "findings_upserted",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "generation > 0",
            name="ck_integrity_observation_runs_generation",
        ),
        sa.CheckConstraint(
            "external_run_id = btrim(external_run_id) AND external_run_id <> ''",
            name="ck_integrity_observation_runs_external_run",
        ),
        sa.CheckConstraint(
            "status IN ('collecting','authoritative','superseded')",
            name="ck_integrity_observation_runs_status",
        ),
        sa.CheckConstraint(
            "source_observations >= 0 "
            "AND findings_observed >= 0 "
            "AND findings_unique >= 0 "
            "AND findings_upserted >= 0 "
            "AND findings_unique <= findings_observed "
            "AND findings_upserted <= findings_unique",
            name="ck_integrity_observation_runs_counts",
        ),
        sa.CheckConstraint(
            "(status = 'collecting' AND completed_at IS NULL) "
            "OR (status IN ('authoritative','superseded') "
            "AND completed_at IS NOT NULL)",
            name="ck_integrity_observation_runs_completion",
        ),
        sa.ForeignKeyConstraint(
            ["provider", "dataset_key"],
            [
                "ops.integrity_observation_scopes.provider",
                "ops.integrity_observation_scopes.dataset_key",
            ],
            name="fk_integrity_observation_runs_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "observation_run_id",
            name="pk_integrity_observation_runs",
        ),
        sa.UniqueConstraint(
            "provider",
            "dataset_key",
            "generation",
            name="uq_integrity_observation_runs_generation",
        ),
        sa.UniqueConstraint(
            "provider",
            "dataset_key",
            "external_run_id",
            name="uq_integrity_observation_runs_external_run",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_integrity_observation_runs_scope_status",
        "integrity_observation_runs",
        ["provider", "dataset_key", "status", sa.text("generation DESC")],
        schema="ops",
    )

    op.create_table(
        "integrity_finding_observations",
        sa.Column("observation_run_id", sa.BigInteger(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "dedupe_key ~ '^av2_[0-9a-f]{64}$'",
            name="ck_integrity_finding_observations_key",
        ),
        sa.ForeignKeyConstraint(
            ["observation_run_id"],
            ["ops.integrity_observation_runs.observation_run_id"],
            name="fk_integrity_finding_observations_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "observation_run_id",
            "dedupe_key",
            name="pk_integrity_finding_observations",
        ),
        schema="ops",
    )
    op.create_index(
        "idx_integrity_finding_observations_key_run",
        "integrity_finding_observations",
        ["dedupe_key", "observation_run_id"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_integrity_finding_observations_key_run",
        table_name="integrity_finding_observations",
        schema="ops",
    )
    op.drop_table("integrity_finding_observations", schema="ops")
    op.drop_index(
        "idx_integrity_observation_runs_scope_status",
        table_name="integrity_observation_runs",
        schema="ops",
    )
    op.drop_table("integrity_observation_runs", schema="ops")
    op.drop_table("integrity_observation_scopes", schema="ops")
