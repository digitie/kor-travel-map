"""curated theme set 확장.

Revision ID: 0039_expand_curated_theme_sets
Revises: 0038_source_record_last_seen
Create Date: 2026-07-02 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0039_expand_curated_theme_sets"
down_revision: str | Sequence[str] | None = "0038_source_record_last_seen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO feature.curated_themes (
            theme_slug, theme_name, theme_description, theme_group,
            default_curated, visibility, metadata
        ) VALUES
            ('seasonal-spring-blossom', '봄꽃 여행지',
             '벚꽃·유채꽃·철쭉처럼 봄철 방문성이 높은 여행지 후보',
             'seasonal', false, 'public',
             '{"icon":"flower-2","color":"P-15","seed":"0039_expand_curated_theme_sets"}'::jsonb),
            ('seasonal-summer-coast', '여름 바다 여행지',
             '해수욕장·해안 산책·여름 피서 동선에 어울리는 여행지 후보',
             'seasonal', false, 'public',
             '{"icon":"waves","color":"P-16","seed":"0039_expand_curated_theme_sets"}'::jsonb),
            ('seasonal-autumn-foliage', '가을 단풍 여행지',
             '단풍·억새·가을 산책과 연결하기 좋은 여행지 후보',
             'seasonal', false, 'public',
             '{"icon":"leaf","color":"P-17","seed":"0039_expand_curated_theme_sets"}'::jsonb),
            ('seasonal-winter-snow', '겨울 눈꽃 여행지',
             '눈꽃·온천·겨울 풍경과 연결하기 좋은 여행지 후보',
             'seasonal', false, 'public',
             '{"icon":"snowflake","color":"P-18","seed":"0039_expand_curated_theme_sets"}'::jsonb),
            ('region-seoul-capital', '서울·수도권 여행지',
             '서울·인천·경기권의 짧은 이동 동선용 여행지 후보',
             'regional', false, 'public',
             '{"icon":"building-2","color":"P-19","seed":"0039_expand_curated_theme_sets"}'::jsonb),
            ('region-busan-coast', '부산·동남권 여행지',
             '부산·울산·경남 해안/도심 동선에 맞는 여행지 후보',
             'regional', false, 'public',
             '{"icon":"ship","color":"P-20","seed":"0039_expand_curated_theme_sets"}'::jsonb),
            ('region-jeju-island', '제주 여행지',
             '제주 섬 여행 동선과 어울리는 자연·문화 여행지 후보',
             'regional', false, 'public',
             '{"icon":"mountain-snow","color":"P-21","seed":"0039_expand_curated_theme_sets"}'::jsonb),
            ('region-gangwon-nature', '강원 자연 여행지',
             '강원 산·바다·숲 중심 여행지 후보',
             'regional', false, 'public',
             '{"icon":"trees","color":"P-22","seed":"0039_expand_curated_theme_sets"}'::jsonb),
            ('region-jeolla-food', '전라 맛·문화 여행지',
             '전라권 음식·문화·해안 동선에 어울리는 여행지 후보',
             'regional', false, 'public',
             '{"icon":"utensils","color":"P-23","seed":"0039_expand_curated_theme_sets"}'::jsonb),
            ('region-gyeongju-history', '경주·신라 역사 여행지',
             '경주와 신라권 역사 문화 동선에 맞는 여행지 후보',
             'regional', false, 'public',
             '{"icon":"landmark","color":"P-24","seed":"0039_expand_curated_theme_sets"}'::jsonb)
        ON CONFLICT (theme_slug) DO UPDATE
        SET
            theme_name = EXCLUDED.theme_name,
            theme_description = EXCLUDED.theme_description,
            theme_group = EXCLUDED.theme_group,
            default_curated = EXCLUDED.default_curated,
            visibility = EXCLUDED.visibility,
            metadata = feature.curated_themes.metadata || EXCLUDED.metadata,
            updated_at = now()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM feature.curated_themes
        WHERE metadata ->> 'seed' = '0039_expand_curated_theme_sets'
          AND NOT EXISTS (
              SELECT 1
              FROM feature.curated_features AS cf
              WHERE cf.theme_id = feature.curated_themes.theme_id
          )
          AND NOT EXISTS (
              SELECT 1
              FROM feature.curated_source_rules AS csr
              WHERE csr.theme_id = feature.curated_themes.theme_id
          )
        """
    )
