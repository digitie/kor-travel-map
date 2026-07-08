"""curated_source_rules.detail_selector — 단일 source를 detail JSON 값으로 분할.

concierge youtube 후보를 channel/playlist 그룹핑별 테마로 자동 후보화하기 위해
``feature.curated_source_rules``에 ``detail_selector``(nullable jsonb)를 추가한다.
rule이 "detail의 특정 path 값이 value와 일치하는 feature만"을 지정할 수 있게 해,
하나의 source(kor-travel-concierge-youtube)를 grouping별로 여러 테마에 팬아웃한다.
apply(_APPLY_RULE_SQL)의 detail_selector 술어가 이 컬럼을 사용한다.

apply 술어(``f.detail #>> path = value``)를 지원하는 부분 표현식 인덱스도 추가한다.
concierge youtube channel/playlist 경로만 인덱싱(해당 feature만 대상 → 작고 빌드
빠름) — 1M feature 전체를 인덱싱하지 않는다.

Revision ID: 0042_curated_rule_detail_selector
Revises: 0041_managed_files
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0042_curated_rule_detail_selector"
down_revision: str | Sequence[str] | None = "0041_managed_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE feature.curated_source_rules
            ADD COLUMN IF NOT EXISTS detail_selector jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_source_rules
            DROP CONSTRAINT IF EXISTS ck_curated_source_rules_detail_selector
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_source_rules
            ADD CONSTRAINT ck_curated_source_rules_detail_selector
            CHECK (
                detail_selector IS NULL
                OR jsonb_typeof(detail_selector) = 'object'
            )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_features_yt_channel_id
        ON feature.features (
            (detail #>> '{payload,kor_travel_concierge,youtube,channel_id}')
        )
        WHERE detail #>> '{payload,kor_travel_concierge,youtube,channel_id}'
              IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_features_yt_playlist_id
        ON feature.features (
            (detail #>> '{payload,kor_travel_concierge,youtube,playlist_id}')
        )
        WHERE detail #>> '{payload,kor_travel_concierge,youtube,playlist_id}'
              IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS feature.idx_features_yt_playlist_id")
    op.execute("DROP INDEX IF EXISTS feature.idx_features_yt_channel_id")
    op.execute(
        """
        ALTER TABLE feature.curated_source_rules
            DROP CONSTRAINT IF EXISTS ck_curated_source_rules_detail_selector
        """
    )
    op.execute(
        """
        ALTER TABLE feature.curated_source_rules
            DROP COLUMN IF EXISTS detail_selector
        """
    )
