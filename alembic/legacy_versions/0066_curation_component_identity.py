"""Curation source item과 membership component identity를 분리한다.

Revision ID: 0066_curation_component_identity
Revises: 0065_curation_source_presence
Create Date: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0066_curation_component_identity"
down_revision: str | Sequence[str] | None = "0065_curation_source_presence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_IDENTITY = "uq_curation_items_identity"
_COMPONENT_IDENTITY = "uq_curation_items_component_identity"
_ACTIVE_FEATURE_IDENTITY = "uq_curation_items_active_source_feature"
_COMPONENT_CANONICAL = "ck_curation_items_external_component_id_canonical"
_LEGACY_COMPONENT_TRIGGER = "trg_curation_items_legacy_component_identity"
_LEGACY_COMPONENT_FUNCTION = "feature.set_curation_item_legacy_component_identity"

_CREATE_LEGACY_COMPONENT_FUNCTION = """
CREATE OR REPLACE FUNCTION feature.set_curation_item_legacy_component_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.legacy_projection_id IS NOT NULL
       AND NEW.external_component_id = 'primary'
    THEN
        NEW.external_component_id :=
            'legacy:' || NEW.legacy_projection_id::text;
    END IF;
    RETURN NEW;
END;
$$
"""


def _fail_on_old_identity_duplicates() -> None:
    """0065 identity로 되돌릴 수 없는 component 행을 mutation 전에 거부한다."""
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                  collection_id::text,
                  external_item_id,
                  feature_id,
                  array_agg(
                    external_component_id
                    ORDER BY external_component_id, curation_item_id
                  ) AS component_ids
                FROM feature.curation_items
                GROUP BY collection_id, external_item_id, feature_id
                HAVING COUNT(*) > 1
                ORDER BY collection_id, external_item_id, feature_id
                LIMIT 20
                """
            )
        )
        .mappings()
        .all()
    )
    if rows:
        raise RuntimeError(
            "0066 downgrade cannot represent multiple source components with the "
            "0065 feature-target identity; remove or merge the rows first: "
            f"{[dict(row) for row in rows]!r}"
        )


def upgrade() -> None:
    op.add_column(
        "curation_items",
        sa.Column(
            "external_component_id",
            sa.Text(),
            nullable=True,
            server_default=sa.text("'primary'"),
        ),
        schema="feature",
    )
    op.execute(
        """
        WITH ranked AS (
          SELECT
            curation_item_id,
            legacy_projection_id,
            count(*) OVER (
              PARTITION BY collection_id, external_item_id
            ) AS component_count
          FROM feature.curation_items
        )
        UPDATE feature.curation_items AS item
        SET external_component_id = CASE
          WHEN ranked.legacy_projection_id IS NOT NULL
            THEN 'legacy:' || item.curation_item_id::text
          WHEN ranked.component_count = 1 THEN 'primary'
          ELSE 'legacy:' || item.curation_item_id::text
        END
        FROM ranked
        WHERE ranked.curation_item_id = item.curation_item_id
        """
    )
    # Alembic env는 0065→0066을 포함한 여러 revision을 한 transaction에서 실행한다.
    # 0065가 만든 INITIALLY DEFERRED FK와 sync trigger event를 먼저 검사·소진하지
    # 않으면 PostgreSQL은 같은 table의 후속 ALTER를 pending trigger event로 거부한다.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.alter_column(
        "curation_items",
        "external_component_id",
        existing_type=sa.Text(),
        nullable=False,
        server_default=sa.text("'primary'"),
        schema="feature",
    )
    op.create_check_constraint(
        op.f(_COMPONENT_CANONICAL),
        "curation_items",
        (
            "external_component_id <> '' "
            "AND external_component_id = btrim(external_component_id)"
        ),
        schema="feature",
    )

    op.drop_index(
        op.f(_OLD_IDENTITY),
        table_name="curation_items",
        schema="feature",
    )
    op.create_unique_constraint(
        op.f(_COMPONENT_IDENTITY),
        "curation_items",
        ["collection_id", "external_item_id", "external_component_id"],
        schema="feature",
    )
    op.create_index(
        op.f(_ACTIVE_FEATURE_IDENTITY),
        "curation_items",
        ["collection_id", "external_item_id", "feature_id"],
        unique=True,
        schema="feature",
        postgresql_where=sa.text(
            "source_present AND archived_at IS NULL AND feature_id IS NOT NULL"
        ),
    )
    op.execute(_CREATE_LEGACY_COMPONENT_FUNCTION)
    op.execute(
        f"""
        CREATE TRIGGER {_LEGACY_COMPONENT_TRIGGER}
        BEFORE INSERT
        ON feature.curation_items
        FOR EACH ROW
        EXECUTE FUNCTION {_LEGACY_COMPONENT_FUNCTION}()
        """
    )


def downgrade() -> None:
    _fail_on_old_identity_duplicates()
    op.execute(
        f"DROP TRIGGER {_LEGACY_COMPONENT_TRIGGER} "
        "ON feature.curation_items"
    )
    op.execute(f"DROP FUNCTION {_LEGACY_COMPONENT_FUNCTION}()")
    op.drop_index(
        op.f(_ACTIVE_FEATURE_IDENTITY),
        table_name="curation_items",
        schema="feature",
    )
    op.drop_constraint(
        op.f(_COMPONENT_IDENTITY),
        "curation_items",
        schema="feature",
        type_="unique",
    )
    op.create_index(
        op.f(_OLD_IDENTITY),
        "curation_items",
        ["collection_id", "external_item_id", "feature_id"],
        unique=True,
        schema="feature",
        postgresql_nulls_not_distinct=True,
    )
    op.drop_constraint(
        op.f(_COMPONENT_CANONICAL),
        "curation_items",
        schema="feature",
        type_="check",
    )
    op.drop_column(
        "curation_items",
        "external_component_id",
        schema="feature",
    )
