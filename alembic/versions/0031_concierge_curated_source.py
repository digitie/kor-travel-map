"""concierge YouTube 후보를 curated source rule에 추가.

Revision ID: 0031_concierge_curated_source
Revises: 0030_khoa_rekey_hardening
Create Date: 2026-06-25

kor-travel-concierge가 공급하는 YouTube 장소 후보는 이미
``feature.features``의 ``place``로 적재된다. 본 migration은 같은 provider/dataset을
``media-places`` curated theme의 기본 source rule로 등록해, Dagster
``curated_features_refresh``가 PinVi 복사용 curated overlay까지 만들 수 있게 한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031_concierge_curated_source"
down_revision: str | Sequence[str] | None = "0030_khoa_rekey_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO feature.curated_sources (
            provider, dataset_key, source_name, source_url, source_kind,
            license, update_cycle, last_source_modified_at, next_expected_at,
            row_count, freshness_note, provider_status, metadata
        ) VALUES (
            'kor-travel-concierge-youtube',
            'youtube_place_candidates',
            'kor-travel-concierge YouTube 장소 후보',
            NULL,
            'internal',
            NULL,
            'daily',
            NULL,
            NULL,
            NULL,
            'YouTube 채널·재생목록·검색어 기반 AI 추출/검수 후보',
            'implemented',
            '{"slug":"youtube_place_candidates","surface":"feature_export",
              "seed":"0031_concierge_curated_source"}'::jsonb
        )
        ON CONFLICT (provider, dataset_key)
        DO UPDATE SET
            source_name = EXCLUDED.source_name,
            source_kind = EXCLUDED.source_kind,
            update_cycle = EXCLUDED.update_cycle,
            freshness_note = EXCLUDED.freshness_note,
            provider_status = EXCLUDED.provider_status,
            metadata = feature.curated_sources.metadata || EXCLUDED.metadata,
            updated_at = now()
        """
    )
    op.execute(
        """
        WITH source_row AS (
            SELECT source_id
            FROM feature.curated_sources
            WHERE provider = 'kor-travel-concierge-youtube'
              AND dataset_key = 'youtube_place_candidates'
        ),
        theme_row AS (
            SELECT theme_id
            FROM feature.curated_themes
            WHERE theme_slug = 'media-places'
        )
        INSERT INTO feature.curated_source_rules (
            theme_id, source_id, dataset_key, place_kind, default_action,
            priority, metadata
        )
        SELECT
            t.theme_id,
            s.source_id,
            'youtube_place_candidates',
            'youtube_place_candidate',
            'curated',
            90,
            jsonb_build_object(
                'pinvi_relation', 'primary_stop',
                'pinvi_copy_policy', 'copy_allowed',
                'seed', '0031_concierge_curated_source'
            )
        FROM theme_row AS t
        CROSS JOIN source_row AS s
        WHERE NOT EXISTS (
            SELECT 1
            FROM feature.curated_source_rules AS r
            WHERE r.theme_id = t.theme_id
              AND r.source_id = s.source_id
              AND r.dataset_key = 'youtube_place_candidates'
              AND r.place_kind = 'youtube_place_candidate'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM feature.curated_source_rules AS r
        USING feature.curated_sources AS s
        WHERE r.source_id = s.source_id
          AND s.provider = 'kor-travel-concierge-youtube'
          AND s.dataset_key = 'youtube_place_candidates'
          AND r.metadata ->> 'seed' = '0031_concierge_curated_source'
        """
    )
    op.execute(
        """
        DELETE FROM feature.curated_sources
        WHERE provider = 'kor-travel-concierge-youtube'
          AND dataset_key = 'youtube_place_candidates'
          AND metadata ->> 'seed' = '0031_concierge_curated_source'
          AND NOT EXISTS (
              SELECT 1
              FROM feature.curated_features AS cf
              WHERE cf.source_id = feature.curated_sources.source_id
          )
        """
    )
