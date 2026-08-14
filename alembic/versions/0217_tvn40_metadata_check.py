"""T-VN-40 Alembic metadata reflection 경계를 닫는다.

Revision ID: 0217_tvn40_metadata_check
Revises: 0216_tvn40_import_item_cmd
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0217_tvn40_metadata_check"
down_revision: str | Sequence[str] | None = "0216_tvn40_import_item_cmd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """0105 expand에서 미검증으로 추가한 owner shape를 최종 검증한다.

    두 제약은 legacy NULL owner를 의도적으로 허용하므로 0105 직후에도 모든 기존
    행을 검증할 수 있다. ``NOT VALID`` 상태를 head까지 남기면 PostgreSQL inspector가
    ``dialect_options.not_valid``를 반환해 Alembic/SQLAlchemy metadata reflection이
    깨지고, 실제 배포 전 ``alembic check``도 신뢰할 수 없어진다.
    """

    op.execute(
        "ALTER TABLE feature.curated_themes "
        "VALIDATE CONSTRAINT ck_curated_themes_owner_shape"
    )
    op.execute(
        "ALTER TABLE feature.curated_source_rules "
        "VALIDATE CONSTRAINT ck_curated_source_rules_owner_shape"
    )


def downgrade() -> None:
    raise RuntimeError("0121 is forward-only; rebuild with the T-VN-40 release head")
