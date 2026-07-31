"""큐레이션 import row와 Feature link decision provenance를 정규화한다.

Revision ID: 0072_curation_provenance
Revises: 0071_integrity_observations
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0072_curation_provenance"
down_revision: str | Sequence[str] | None = "0071_integrity_observations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "curation_import_batches",
        sa.Column(
            "import_batch_id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("batch_kind", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_curation_import_batches_sha256",
        ),
        sa.CheckConstraint(
            "batch_kind IN ('csv_upload','normalized_rows','forward_recovery')",
            name="ck_curation_import_batches_kind",
        ),
        sa.CheckConstraint(
            "row_count >= 0",
            name="ck_curation_import_batches_row_count",
        ),
        sa.CheckConstraint(
            "actor = btrim(actor) AND actor <> ''",
            name="ck_curation_import_batches_actor",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_curation_import_batches_metadata",
        ),
        sa.PrimaryKeyConstraint(
            "import_batch_id",
            name="pk_curation_import_batches",
        ),
        schema="feature",
    )
    op.create_index(
        "idx_curation_import_batches_sha_time",
        "curation_import_batches",
        ["content_sha256", sa.text("imported_at DESC"), "import_batch_id"],
        schema="feature",
    )

    op.create_table(
        "curation_import_rows",
        sa.Column(
            "import_row_id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("import_batch_id", sa.UUID(), nullable=False),
        sa.Column("curation_item_id", sa.UUID(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("source_row_sha256", sa.Text(), nullable=False),
        sa.Column(
            "row_payload",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "row_number > 0",
            name="ck_curation_import_rows_row_number",
        ),
        sa.CheckConstraint(
            "source_row_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_curation_import_rows_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(row_payload) = 'object'",
            name="ck_curation_import_rows_payload",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(provenance) = 'object'",
            name="ck_curation_import_rows_provenance",
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["feature.curation_import_batches.import_batch_id"],
            name="fk_curation_import_rows_batch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["curation_item_id"],
            ["feature.curation_items.curation_item_id"],
            name="fk_curation_import_rows_item",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "import_row_id",
            name="pk_curation_import_rows",
        ),
        sa.UniqueConstraint(
            "import_batch_id",
            "row_number",
            name="uq_curation_import_rows_batch_row",
        ),
        sa.UniqueConstraint(
            "import_row_id",
            "curation_item_id",
            name="uq_curation_import_rows_item_pointer",
        ),
        schema="feature",
    )
    op.create_index(
        "idx_curation_import_rows_item_time",
        "curation_import_rows",
        ["curation_item_id", sa.text("imported_at DESC"), "import_row_id"],
        schema="feature",
    )

    op.create_table(
        "curation_link_decisions",
        sa.Column(
            "decision_id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("x_extension.gen_random_uuid()"),
        ),
        sa.Column("curation_item_id", sa.UUID(), nullable=False),
        sa.Column("feature_id", sa.Text(), nullable=False),
        sa.Column("import_row_id", sa.UUID()),
        sa.Column("decision_kind", sa.Text(), nullable=False),
        sa.Column("match_basis", sa.Text(), nullable=False),
        sa.Column("resolver_version", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("supersedes_decision_id", sa.UUID()),
        sa.CheckConstraint(
            "decision_kind IN ('accepted','revoked')",
            name="ck_curation_link_decisions_kind",
        ),
        sa.CheckConstraint(
            "match_basis IN ("
            "'csv_explicit_feature_id','admin_review','legacy_unattributed',"
            "'forward_recovery'"
            ")",
            name="ck_curation_link_decisions_basis",
        ),
        sa.CheckConstraint(
            "resolver_version = btrim(resolver_version) "
            "AND resolver_version <> ''",
            name="ck_curation_link_decisions_resolver",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'object'",
            name="ck_curation_link_decisions_evidence",
        ),
        sa.CheckConstraint(
            "actor = btrim(actor) AND actor <> ''",
            name="ck_curation_link_decisions_actor",
        ),
        sa.CheckConstraint(
            "supersedes_decision_id IS DISTINCT FROM decision_id",
            name="ck_curation_link_decisions_not_self_superseding",
        ),
        sa.ForeignKeyConstraint(
            ["curation_item_id"],
            ["feature.curation_items.curation_item_id"],
            name="fk_curation_link_decisions_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["import_row_id", "curation_item_id"],
            [
                "feature.curation_import_rows.import_row_id",
                "feature.curation_import_rows.curation_item_id",
            ],
            name="fk_curation_link_decisions_import_row",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_decision_id", "curation_item_id"],
            [
                "feature.curation_link_decisions.decision_id",
                "feature.curation_link_decisions.curation_item_id",
            ],
            name="fk_curation_link_decisions_supersedes",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "decision_id",
            name="pk_curation_link_decisions",
        ),
        sa.UniqueConstraint(
            "decision_id",
            "curation_item_id",
            name="uq_curation_link_decisions_item_pointer",
        ),
        sa.UniqueConstraint(
            "decision_id",
            "curation_item_id",
            "feature_id",
            name="uq_curation_link_decisions_item_target",
        ),
        schema="feature",
    )
    op.create_index(
        "idx_curation_link_decisions_item_time",
        "curation_link_decisions",
        ["curation_item_id", sa.text("decided_at DESC"), "decision_id"],
        schema="feature",
    )
    op.create_index(
        "idx_curation_link_decisions_basis_time",
        "curation_link_decisions",
        ["match_basis", sa.text("decided_at DESC"), "decision_id"],
        schema="feature",
    )

    op.add_column(
        "curation_items",
        sa.Column("current_import_row_id", sa.UUID()),
        schema="feature",
    )
    op.add_column(
        "curation_items",
        sa.Column("accepted_link_decision_id", sa.UUID()),
        schema="feature",
    )
    op.create_foreign_key(
        "fk_curation_items_current_import_row",
        "curation_items",
        "curation_import_rows",
        ["current_import_row_id", "curation_item_id"],
        ["import_row_id", "curation_item_id"],
        source_schema="feature",
        referent_schema="feature",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_curation_items_accepted_link_decision",
        "curation_items",
        "curation_link_decisions",
        ["accepted_link_decision_id", "curation_item_id", "feature_id"],
        ["decision_id", "curation_item_id", "feature_id"],
        source_schema="feature",
        referent_schema="feature",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    # 기존 link의 승인 근거는 추정하지 않는다. exact item/target을 보존하되 공개 승인에는
    # 쓸 수 없는 legacy_unattributed decision으로 명시한다.
    op.execute(
        """
        WITH inserted AS (
            INSERT INTO feature.curation_link_decisions (
                curation_item_id,
                feature_id,
                decision_kind,
                match_basis,
                resolver_version,
                evidence,
                actor,
                decided_at
            )
            SELECT
                item.curation_item_id,
                item.feature_id,
                'accepted',
                'legacy_unattributed',
                'pre-0072-unknown',
                jsonb_build_object(
                    'migration', '0072_curation_provenance',
                    'reason', '기존 link의 선택 근거를 안전하게 복구할 수 없음'
                ),
                COALESCE(
                    NULLIF(btrim(item.operator_updated_by), ''),
                    NULLIF(btrim(item.updated_by), ''),
                    NULLIF(btrim(item.created_by), ''),
                    'migration:0072'
                ),
                COALESCE(item.operator_updated_at, item.updated_at, item.created_at)
            FROM feature.curation_items AS item
            WHERE item.feature_id IS NOT NULL
            RETURNING decision_id, curation_item_id
        )
        UPDATE feature.curation_items AS item
           SET accepted_link_decision_id = inserted.decision_id
          FROM inserted
         WHERE inserted.curation_item_id = item.curation_item_id
        """
    )
    op.execute(
        """
        CREATE FUNCTION feature.reject_curation_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RAISE EXCEPTION 'curation import/link history is append-only'
            USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table_name in (
        "curation_import_batches",
        "curation_import_rows",
        "curation_link_decisions",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON feature.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION feature.reject_curation_history_mutation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_no_truncate
            BEFORE TRUNCATE ON feature.{table_name}
            FOR EACH STATEMENT
            EXECUTE FUNCTION feature.reject_curation_history_mutation()
            """
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_curation_items_accepted_link_decision",
        "curation_items",
        schema="feature",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_curation_items_current_import_row",
        "curation_items",
        schema="feature",
        type_="foreignkey",
    )
    op.drop_column("curation_items", "accepted_link_decision_id", schema="feature")
    op.drop_column("curation_items", "current_import_row_id", schema="feature")
    op.drop_index(
        "idx_curation_link_decisions_basis_time",
        table_name="curation_link_decisions",
        schema="feature",
    )
    op.execute(
        "DROP TRIGGER trg_curation_link_decisions_no_truncate "
        "ON feature.curation_link_decisions"
    )
    op.execute(
        "DROP TRIGGER trg_curation_link_decisions_append_only "
        "ON feature.curation_link_decisions"
    )
    op.drop_index(
        "idx_curation_link_decisions_item_time",
        table_name="curation_link_decisions",
        schema="feature",
    )
    op.drop_table("curation_link_decisions", schema="feature")
    op.execute(
        "DROP TRIGGER trg_curation_import_rows_no_truncate "
        "ON feature.curation_import_rows"
    )
    op.execute(
        "DROP TRIGGER trg_curation_import_rows_append_only "
        "ON feature.curation_import_rows"
    )
    op.drop_index(
        "idx_curation_import_rows_item_time",
        table_name="curation_import_rows",
        schema="feature",
    )
    op.drop_table("curation_import_rows", schema="feature")
    op.execute(
        "DROP TRIGGER trg_curation_import_batches_no_truncate "
        "ON feature.curation_import_batches"
    )
    op.execute(
        "DROP TRIGGER trg_curation_import_batches_append_only "
        "ON feature.curation_import_batches"
    )
    op.drop_index(
        "idx_curation_import_batches_sha_time",
        table_name="curation_import_batches",
        schema="feature",
    )
    op.drop_table("curation_import_batches", schema="feature")
    op.execute("DROP FUNCTION feature.reject_curation_history_mutation()")
