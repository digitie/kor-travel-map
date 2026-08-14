"""POI cache target metadata의 TripMate 키를 PinVi로 rename.

Revision ID: 0033_pinvi_poi_cache_metadata
Revises: 0032_curated_pinvi_rename
Create Date: 2026-06-25

``ops.poi_cache_targets.metadata``는 자유 JSONB지만 API 표면에서 이전
``tripmate_poi_id`` 키를 명시 필드처럼 사용했다. 정식 키를 ``pinvi_poi_id``로
전환하고 기존 row의 값을 보존한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033_pinvi_poi_cache_metadata"
down_revision: str | Sequence[str] | None = "0032_curated_pinvi_rename"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ops.poi_cache_targets
        SET metadata = (
            metadata
            || jsonb_build_object('pinvi_poi_id', metadata ->> 'tripmate_poi_id')
        ) - 'tripmate_poi_id'
        WHERE metadata ? 'tripmate_poi_id'
          AND NOT metadata ? 'pinvi_poi_id'
        """
    )
    op.execute(
        """
        UPDATE ops.poi_cache_targets
        SET metadata = metadata - 'tripmate_poi_id'
        WHERE metadata ? 'tripmate_poi_id'
          AND metadata ? 'pinvi_poi_id'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ops.poi_cache_targets
        SET metadata = (
            metadata
            || jsonb_build_object('tripmate_poi_id', metadata ->> 'pinvi_poi_id')
        ) - 'pinvi_poi_id'
        WHERE metadata ? 'pinvi_poi_id'
          AND NOT metadata ? 'tripmate_poi_id'
        """
    )
    op.execute(
        """
        UPDATE ops.poi_cache_targets
        SET metadata = metadata - 'pinvi_poi_id'
        WHERE metadata ? 'pinvi_poi_id'
          AND metadata ? 'tripmate_poi_id'
        """
    )
