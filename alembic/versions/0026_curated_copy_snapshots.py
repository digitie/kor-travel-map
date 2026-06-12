"""curated TripMate copy snapshot cache 추가.

Revision ID: 0026_curated_copy_snapshots
Revises: 0025_curated_features
Create Date: 2026-06-12

T-223c-2는 Dagster ``curated_features`` group이 TripMate 복사용 snapshot을
물리화할 수 있도록 cache table을 추가한다. TripMate는 여전히 REST snapshot을
읽어 자기 DB에 복사하며, 본 table은 krtour-map 내부 materialize/cache 경계다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026_curated_copy_snapshots"
down_revision: str | Sequence[str] | None = "0025_curated_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feature.curated_tripmate_copy_snapshots (
            curated_feature_id UUID PRIMARY KEY
                REFERENCES feature.curated_features(curated_feature_id)
                ON DELETE CASCADE,
            copy_version       INTEGER NOT NULL,
            etag               TEXT NOT NULL,
            snapshot           JSONB NOT NULL,
            materialized_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_curated_copy_snapshots_version
                CHECK (copy_version >= 1),
            CONSTRAINT ck_curated_copy_snapshots_snapshot
                CHECK (jsonb_typeof(snapshot) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_copy_snapshots_updated
        ON feature.curated_tripmate_copy_snapshots (
            updated_at DESC, curated_feature_id DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_copy_snapshots_etag
        ON feature.curated_tripmate_copy_snapshots (etag)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feature.curated_tripmate_copy_snapshots")
