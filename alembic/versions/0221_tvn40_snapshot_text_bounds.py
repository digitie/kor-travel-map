"""T-VN-40 service snapshot 문자열 상한을 producer DB에 고정한다.

Revision ID: 0221_tvn40_snapshot_text_bounds
Revises: 0220_tvn40_snapshot_cap_index
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0221_tvn40_snapshot_text_bounds"
down_revision: str | Sequence[str] | None = "0220_tvn40_snapshot_cap_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_schema_owner")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
              FROM feature.curated_themes
             WHERE char_length(theme_slug) NOT BETWEEN 1 AND 128
                OR char_length(theme_name) NOT BETWEEN 1 AND 200
          ) THEN
            RAISE EXCEPTION 'T-VN-40 theme snapshot text exceeds paired contract'
              USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1
              FROM feature.curation_collections
             WHERE char_length(title) NOT BETWEEN 1 AND 300
                OR char_length(edition_key) > 100
          ) THEN
            RAISE EXCEPTION 'T-VN-40 collection snapshot text exceeds paired contract'
              USING ERRCODE = '23514';
          END IF;
        END
        $$
        """
    )
    op.create_check_constraint(
        "ck_curated_themes_snapshot_text_bounds",
        "curated_themes",
        "char_length(theme_slug) BETWEEN 1 AND 128 "
        "AND char_length(theme_name) BETWEEN 1 AND 200",
        schema="feature",
    )
    op.create_check_constraint(
        "ck_curation_collections_snapshot_text_bounds",
        "curation_collections",
        "char_length(title) BETWEEN 1 AND 300 "
        "AND char_length(edition_key) <= 100",
        schema="feature",
    )


def downgrade() -> None:
    raise RuntimeError(
        "0221_tvn40_snapshot_text_bounds is forward-only; "
        "rebuild with the T-VN-40 release head"
    )
