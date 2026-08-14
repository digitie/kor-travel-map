"""0065 curation source presence schema migration 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_PRE_REVISION = "0064_price_series_identity"
_TARGET_REVISION = "0065_curation_source_presence"


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    # 아카이브 체인 전용 그래프 — alembic/legacy_versions/README.md 참조.
    config.set_main_option("version_locations", str(root / "alembic" / "legacy_versions"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _schema_state(engine: Any) -> tuple[tuple[Any, ...] | None, dict[str, str]]:
    async with engine.connect() as connection:
        column = (
            await connection.execute(
                text(
                    "SELECT is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'feature' "
                    "AND table_name = 'curation_items' "
                    "AND column_name = 'source_present'"
                )
            )
        ).one_or_none()
        indexes = await connection.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'feature' "
                "AND tablename = 'curation_items'"
            )
        )
    return column, {str(name): str(definition) for name, definition in indexes}


async def _seed_pre_0065_identity_conflicts(engine: Any) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, detail, status
                ) VALUES (
                    'feature:migration-presence', 'place', 'migration fixture',
                    '01070100', '{}'::jsonb, 'active'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, detail, status
                ) VALUES
                    (
                        'feature:migration-split', 'place',
                        'migration split fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-theft-a', 'place',
                        'migration theft A fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-theft-a-collision', 'place',
                        'migration theft A identity collision fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-theft-b', 'place',
                        'migration theft B fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-theft-c', 'place',
                        'migration theft C fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-theft-c-safe', 'place',
                        'migration theft C safe fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-deleted-theft-a', 'place',
                        'migration deleted theft A fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-deleted-theft-c', 'place',
                        'migration deleted theft C fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-quarantine-prefix', 'place',
                        'migration quarantine prefix fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-theft-master', 'place',
                        'migration theft canonical master fixture',
                        '01070100', '{}'::jsonb, 'active'
                    ),
                    (
                        'feature:migration-stable-group-new', 'place',
                        'migration stable group new fixture',
                        '01070100', '{}'::jsonb, 'active'
                    )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, detail, status
                ) VALUES (
                    'feature:migration-external-api', 'place',
                    'migration external api fixture',
                    '01070100', '{}'::jsonb, 'active'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                WITH theme AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group
                    ) VALUES (
                        'migration-presence', 'migration presence', 'test'
                    )
                    RETURNING theme_id
                ), collection AS (
                    INSERT INTO feature.curation_collections (
                        collection_key, theme_id, title
                    )
                    SELECT
                        'migration-presence:2026', theme_id,
                        'migration presence'
                    FROM theme
                    RETURNING collection_id
                )
                INSERT INTO feature.curation_items (
                    collection_id, feature_id, external_item_id, place_name,
                    status, archived_at, updated_at
                )
                SELECT
                    collection_id, 'feature:migration-presence',
                    'resolved-conflict', 'resolved tombstone old',
                    'archived', now() - interval '2 hours',
                    now() - interval '2 hours'
                FROM collection
                UNION ALL
                SELECT
                    collection_id, 'feature:migration-presence',
                    'resolved-conflict', 'resolved tombstone newest',
                    'archived', now() - interval '1 hour',
                    now() - interval '1 hour'
                FROM collection
                UNION ALL
                SELECT
                    collection_id, 'feature:migration-presence',
                    'resolved-conflict', 'resolved resurrected',
                    'included', NULL, now()
                FROM collection
                UNION ALL
                SELECT
                    collection_id, NULL,
                    'unresolved-conflict', 'unresolved tombstone',
                    'archived', now() - interval '1 hour',
                    now() - interval '1 hour'
                FROM collection
                UNION ALL
                SELECT
                    collection_id, NULL,
                    'unresolved-conflict', 'unresolved resurrected',
                    'included', NULL, now()
                FROM collection
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items
                SET curation_relation = 'primary_stop',
                    reuse_policy = 'blocked',
                    updated_by = 'migration-tombstone-operator'
                WHERE place_name IN (
                    'resolved tombstone newest',
                    'unresolved tombstone'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items
                SET metadata = '{"provider_revision": "latest"}'::jsonb
                WHERE place_name IN (
                    'resolved resurrected',
                    'unresolved resurrected'
                )
                """
            )
        )
        await connection.execute(
            text(
                """
                WITH source AS (
                    INSERT INTO feature.curated_sources (
                        provider, dataset_key, source_name, source_kind,
                        update_cycle, provider_status, metadata
                    ) VALUES (
                        'migration-provider', 'migration-dataset',
                        'migration source', 'manual', 'unknown',
                        'manual_only', '{}'::jsonb
                    )
                    RETURNING source_id
                ), theme AS (
                    SELECT theme_id
                    FROM feature.curated_themes
                    WHERE theme_slug = 'migration-presence'
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id, curation_status,
                    selection_origin, selected_by, display_title,
                    curation_relation, reuse_policy
                )
                SELECT
                    theme.theme_id, 'feature:migration-presence',
                    source.source_id, 'curated', 'external_api',
                    'external-principal', 'migration legacy override',
                    'nearby_option', 'manual_review'
                FROM theme CROSS JOIN source
                UNION ALL
                SELECT
                    theme.theme_id, 'feature:migration-external-api',
                    source.source_id, 'curated', 'external_api',
                    'external-principal', 'migration external provenance',
                    'nearby_option', 'manual_review'
                FROM theme CROSS JOIN source
                """
            )
        )
        # collection_key는 admin이 임의 지정할 수 있다. 0065의 최종 stable base,
        # split key와 과거 staging namespace를 모두 선점해도 migration이 수동
        # collection을 덮거나 unique violation으로 중단하면 안 된다.
        await connection.execute(
            text(
                """
                WITH legacy_collection AS (
                    SELECT
                        collection.collection_id,
                        collection.theme_id,
                        'legacy:' || collection.theme_id::text || ':' ||
                            collection.source_id::text || ':' ||
                            md5(collection.title) AS base_key
                    FROM feature.curated_features AS legacy
                    JOIN feature.curation_items AS item
                      ON item.curation_item_id =
                         legacy.curated_feature_id
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id = item.collection_id
                    WHERE legacy.display_title =
                          'migration legacy override'
                )
                INSERT INTO feature.curation_collections (
                    collection_key, theme_id, title
                )
                SELECT
                    base_key,
                    theme_id,
                    'manual stable base collision'
                FROM legacy_collection
                UNION ALL
                SELECT
                    base_key || ':split:' || collection_id::text,
                    theme_id,
                    'manual stable split collision'
                FROM legacy_collection
                UNION ALL
                SELECT
                    'legacy:0065-stage:' || collection_id::text,
                    theme_id,
                    'manual upgrade staging collision'
                FROM legacy_collection
                """
            )
        )
        await connection.execute(
            text(
                """
                WITH source AS (
                    SELECT source_id
                    FROM feature.curated_sources
                    WHERE provider = 'migration-provider'
                      AND dataset_key = 'migration-dataset'
                ), themes AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group, visibility
                    ) VALUES
                        (
                            'migration-legacy-duplicate',
                            'migration legacy duplicate',
                            'test',
                            'public'
                        ),
                        (
                            'migration-status-only-archive',
                            'migration status-only archive',
                            'test',
                            'public'
                        )
                    RETURNING theme_id, theme_slug
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id, curation_status,
                    selection_origin, display_title, archived_at, updated_at
                )
                SELECT
                    themes.theme_id, 'feature:migration-presence',
                    source.source_id, 'archived', 'source_rule',
                    'migration legacy duplicate',
                    now() - interval '2 hours',
                    now() - interval '2 hours'
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'migration-legacy-duplicate'
                UNION ALL
                SELECT
                    themes.theme_id, 'feature:migration-presence',
                    source.source_id, 'curated', 'source_rule',
                    'migration legacy duplicate', NULL, now()
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'migration-legacy-duplicate'
                UNION ALL
                SELECT
                    themes.theme_id, 'feature:migration-presence',
                    source.source_id, 'archived', 'source_rule',
                    'migration status-only archive', NULL, now()
                FROM themes CROSS JOIN source
                WHERE themes.theme_slug = 'migration-status-only-archive'
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items AS item
                SET external_item_id = 'migration-legacy-duplicate'
                FROM feature.curated_features AS legacy
                WHERE legacy.display_title = 'migration legacy duplicate'
                  AND item.curation_item_id = legacy.curated_feature_id
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items AS item
                SET status = 'archived',
                    archived_at = now(),
                    updated_by = 'canonical-tombstone-drift',
                    updated_at = clock_timestamp()
                FROM feature.curated_features AS legacy
                WHERE legacy.display_title = 'migration legacy duplicate'
                  AND legacy.curation_status = 'curated'
                  AND item.curation_item_id = legacy.curated_feature_id
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items AS item
                SET status = 'rejected',
                    curation_relation = 'primary_stop',
                    reuse_policy = 'blocked',
                    updated_by = 'canonical-operator',
                    updated_at = clock_timestamp()
                FROM feature.curated_features AS legacy
                WHERE legacy.feature_id = 'feature:migration-presence'
                  AND legacy.display_title = 'migration legacy override'
                  AND item.curation_item_id = legacy.curated_feature_id
                """
            )
        )
        await connection.execute(
            text(
                """
                WITH source AS (
                    SELECT source_id
                    FROM feature.curated_sources
                    WHERE provider = 'migration-provider'
                      AND dataset_key = 'migration-dataset'
                ), theme AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group, visibility
                    ) VALUES (
                        'migration-owner-a',
                        'migration owner A',
                        'test',
                        'public'
                    )
                    RETURNING theme_id
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id,
                    curation_status, selection_origin, display_title
                )
                SELECT
                    theme.theme_id,
                    'feature:migration-split',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'migration split title'
                FROM theme CROSS JOIN source
                UNION ALL
                SELECT
                    theme.theme_id,
                    'feature:migration-theft-a',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'migration theft title'
                FROM theme CROSS JOIN source
                UNION ALL
                SELECT
                    theme.theme_id,
                    'feature:migration-theft-a-collision',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'migration theft title'
                FROM theme CROSS JOIN source
                UNION ALL
                SELECT
                    theme.theme_id,
                    'feature:migration-deleted-theft-a',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'migration deleted theft title'
                FROM theme CROSS JOIN source
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.curation_items (
                    collection_id,
                    feature_id,
                    source_record_key,
                    external_item_id,
                    place_name,
                    status,
                    created_at
                )
                SELECT
                    item.collection_id,
                    'feature:migration-theft-master',
                    item.source_record_key,
                    item.external_item_id,
                    'migration theft canonical master',
                    'included',
                    item.created_at
                FROM feature.curation_items AS item
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id =
                     item.curation_item_id
                WHERE legacy.display_title =
                      'migration theft title'
                  AND legacy.feature_id =
                      'feature:migration-theft-a'
                UNION ALL
                SELECT
                    item.collection_id,
                    'feature:migration-theft-master',
                    NULL,
                    'migration-deleted-theft-orphan',
                    'migration deleted theft orphan',
                    'included',
                    now() - interval '1 day'
                FROM feature.curation_items AS item
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id =
                     item.curation_item_id
                WHERE legacy.display_title =
                      'migration deleted theft title'
                  AND legacy.feature_id =
                      'feature:migration-deleted-theft-a'
                UNION ALL
                SELECT
                    item.collection_id,
                    'feature:migration-theft-master',
                    NULL,
                    'migration-theft-pre-owner-other',
                    'migration theft pre-owner other',
                    'included',
                    now() - interval '1 day'
                FROM feature.curation_items AS item
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id =
                     item.curation_item_id
                WHERE legacy.display_title =
                      'migration theft title'
                  AND legacy.feature_id =
                      'feature:migration-theft-a'
                """
            )
        )
        # owner 탈취 당시 projection이 이미 operator tombstone이어도 0065 복구가
        # canonical-only companion과 함께 원 theme collection으로 이동해야 한다.
        await connection.execute(
            text(
                """
                UPDATE feature.curated_features
                SET curation_status = 'archived',
                    selection_origin = 'admin',
                    archived_at = now(),
                    updated_at = clock_timestamp()
                WHERE display_title = 'migration theft title'
                  AND feature_id = 'feature:migration-theft-a'
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curated_themes
                SET theme_slug = 'migration-owner-a-renamed',
                    updated_at = clock_timestamp()
                WHERE theme_slug = 'migration-owner-a'
                """
            )
        )
        # 0064는 slug rename 뒤 같은 projection 갱신 시 같은 semantic group의
        # split collection을 새 key로 만든다.
        await connection.execute(
            text(
                """
                UPDATE feature.curated_features
                SET display_summary = 'rename 뒤 provider 갱신',
                    updated_at = clock_timestamp()
                WHERE display_title = 'migration split title'
                """
            )
        )
        # 비워진 old slug를 다른 theme가 재사용하면 0064 ON CONFLICT가 기존
        # collection owner를 덮고 서로 다른 theme의 item을 섞는다.
        await connection.execute(
            text(
                """
                WITH source AS (
                    SELECT source_id
                    FROM feature.curated_sources
                    WHERE provider = 'migration-provider'
                      AND dataset_key = 'migration-dataset'
                ), theme AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group, visibility
                    ) VALUES (
                        'migration-owner-a',
                        'migration owner B',
                        'test',
                        'public'
                    )
                    RETURNING theme_id
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id,
                    curation_status, selection_origin, display_title
                )
                SELECT
                    theme.theme_id,
                    'feature:migration-theft-b',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'migration theft title'
                FROM theme CROSS JOIN source
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.curation_items (
                    collection_id,
                    feature_id,
                    external_item_id,
                    place_name,
                    status,
                    created_at
                )
                SELECT
                    item.collection_id,
                    'feature:migration-theft-master',
                    item.external_item_id,
                    'migration theft B canonical pair',
                    'included',
                    item.created_at
                FROM feature.curation_items AS item
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id =
                     item.curation_item_id
                WHERE legacy.display_title =
                      'migration theft title'
                  AND legacy.feature_id =
                      'feature:migration-theft-b'
                UNION ALL
                SELECT
                    item.collection_id,
                    'feature:migration-theft-master',
                    'migration-theft-ambiguous-owner',
                    'migration theft ambiguous owner',
                    'included',
                    now()
                FROM feature.curation_items AS item
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id =
                     item.curation_item_id
                WHERE legacy.display_title =
                      'migration theft title'
                  AND legacy.feature_id =
                      'feature:migration-theft-b'
                """
            )
        )
        # C projection은 owner 탈취보다 오래전에 다른 slug로 만들어 둔다.
        # projection.created_at을 탈취 경계로 쓰면 이후 B에 추가된 ambiguous item이
        # C의 public collection에 남으므로 이 순서가 회귀를 재현한다.
        await connection.execute(
            text(
                """
                UPDATE feature.curated_themes
                SET theme_slug = 'migration-owner-b-renamed',
                    updated_at = clock_timestamp()
                WHERE theme_slug = 'migration-owner-a'
                  AND theme_name = 'migration owner B'
                """
            )
        )
        await connection.execute(
            text(
                """
                WITH source AS (
                    SELECT source_id
                    FROM feature.curated_sources
                    WHERE provider = 'migration-provider'
                      AND dataset_key = 'migration-dataset'
                ), theme AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group, visibility
                    ) VALUES (
                        'migration-owner-c-initial',
                        'migration owner C',
                        'test',
                        'public'
                    )
                    RETURNING theme_id
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id,
                    curation_status, selection_origin, display_title,
                    created_at, updated_at
                )
                SELECT
                    theme.theme_id,
                    'feature:migration-theft-c',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'migration theft title',
                    now() - interval '2 days',
                    now() - interval '2 days'
                FROM theme CROSS JOIN source
                UNION ALL
                SELECT
                    theme.theme_id,
                    'feature:migration-theft-c-safe',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'migration theft title',
                    now() - interval '2 days',
                    now() - interval '2 days'
                FROM theme CROSS JOIN source
                UNION ALL
                SELECT
                    theme.theme_id,
                    'feature:migration-deleted-theft-c',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'migration deleted theft title',
                    now() - interval '2 days',
                    now() - interval '2 days'
                FROM theme CROSS JOIN source
                """
            )
        )
        # 같은 legacy key를 세 번째 theme가 다시 사용하면 0064 trigger가 old
        # collection owner를 C로 덮고 A/B/C projection과 companion을 한데 섞는다.
        await connection.execute(
            text(
                """
                UPDATE feature.curated_themes
                SET theme_slug = 'migration-owner-a',
                    updated_at = clock_timestamp()
                WHERE theme_slug = 'migration-owner-c-initial'
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curated_features
                SET display_summary = '기존 C projection의 owner 탈취',
                    updated_at = now() + interval '12 hours'
                WHERE feature_id IN (
                      'feature:migration-theft-c',
                      'feature:migration-theft-c-safe',
                      'feature:migration-deleted-theft-c'
                  )
                """
            )
        )
        # old projection이 upgrade 전에 삭제돼 repair map 증거가 사라져도
        # legacy-marker collection의 canonical-only orphan은 공개하지 않는다.
        await connection.execute(
            text(
                """
                DELETE FROM feature.curated_features
                WHERE feature_id = 'feature:migration-deleted-theft-a'
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items AS orphan
                SET external_item_id = current_projection.external_item_id
                FROM feature.curation_items AS current_projection
                JOIN feature.curated_features AS current_legacy
                  ON current_legacy.curated_feature_id =
                     current_projection.curation_item_id
                WHERE orphan.place_name =
                      'migration deleted theft orphan'
                  AND current_legacy.feature_id =
                      'feature:migration-deleted-theft-c'
                """
            )
        )
        # 0064 marker는 admin collection metadata whole-object PATCH로 지울 수
        # 있었다. immutable legacy key namespace도 함께 봐야 격리를 우회하지
        # 못한다.
        await connection.execute(
            text(
                """
                UPDATE feature.curation_collections
                SET metadata = '{}'::jsonb,
                    updated_by = 'migration-admin-metadata-patch',
                    updated_at = clock_timestamp()
                WHERE title = 'migration deleted theft title'
                """
            )
        )
        # `quarantine:`는 0064 theme_slug에서 예약되지 않았다. prefix만으로
        # migration-generated quarantine을 제외하면 정상 legacy collection이
        # 격리를 우회한다.
        await connection.execute(
            text(
                """
                WITH source AS (
                    SELECT source_id
                    FROM feature.curated_sources
                    WHERE provider = 'migration-provider'
                      AND dataset_key = 'migration-dataset'
                ), theme AS (
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group, visibility
                    ) VALUES (
                        'quarantine:operator-theme',
                        'migration quarantine prefix theme',
                        'test',
                        'public'
                    )
                    RETURNING theme_id
                )
                INSERT INTO feature.curated_features (
                    theme_id, feature_id, source_id,
                    curation_status, selection_origin, display_title
                )
                SELECT
                    theme.theme_id,
                    'feature:migration-quarantine-prefix',
                    source.source_id,
                    'curated',
                    'source_rule',
                    'migration quarantine prefix title'
                FROM theme CROSS JOIN source
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.curation_items (
                    collection_id,
                    feature_id,
                    external_item_id,
                    place_name,
                    status
                )
                SELECT
                    projection.collection_id,
                    'feature:migration-theft-master',
                    'migration-quarantine-prefix-canonical',
                    'migration quarantine prefix canonical',
                    'included'
                FROM feature.curation_items AS projection
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id =
                     projection.curation_item_id
                WHERE legacy.feature_id =
                      'feature:migration-quarantine-prefix'
                """
            )
        )
        await connection.execute(
            text(
                """
                UPDATE feature.curation_collections
                SET metadata = '{}'::jsonb,
                    updated_by = 'migration-admin-metadata-patch',
                    updated_at = clock_timestamp()
                WHERE title = 'migration quarantine prefix title'
                """
            )
        )
        # 서로 다른 old/current theme가 같은 provider external identity를 가질 수
        # 있다. 이때 current pair를 old repair target으로 이동하지 않고
        # ambiguity quarantine으로 보내야 한다.
        await connection.execute(
            text(
                """
                UPDATE feature.curation_items AS item
                SET external_item_id = 'migration-shared-owner-external'
                FROM feature.curated_features AS legacy
                WHERE item.curation_item_id =
                      legacy.curated_feature_id
                  AND legacy.feature_id IN (
                      'feature:migration-theft-a-collision',
                      'feature:migration-theft-c'
                  )
                """
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.curation_items (
                    collection_id,
                    feature_id,
                    external_item_id,
                    place_name,
                    status,
                    created_at
                )
                SELECT
                    item.collection_id,
                    'feature:migration-theft-master',
                    'migration-theft-post-owner',
                    'migration theft post-owner',
                    'included',
                    now() + interval '1 day'
                FROM feature.curation_items AS item
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id =
                     item.curation_item_id
                WHERE legacy.display_title =
                      'migration theft title'
                  AND legacy.feature_id =
                      'feature:migration-theft-c'
                UNION ALL
                SELECT
                    item.collection_id,
                    'feature:migration-theft-master',
                    item.external_item_id,
                    'migration theft C ambiguous canonical pair',
                    'included',
                    now() + interval '1 day'
                FROM feature.curation_items AS item
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id =
                     item.curation_item_id
                WHERE legacy.display_title =
                      'migration theft title'
                  AND legacy.feature_id =
                      'feature:migration-theft-c'
                UNION ALL
                SELECT
                    item.collection_id,
                    'feature:migration-theft-master',
                    item.external_item_id,
                    'migration theft C safe canonical pair',
                    'included',
                    now() + interval '1 day'
                FROM feature.curation_items AS item
                JOIN feature.curated_features AS legacy
                  ON legacy.curated_feature_id =
                     item.curation_item_id
                WHERE legacy.display_title =
                      'migration theft title'
                  AND legacy.feature_id =
                      'feature:migration-theft-c-safe'
                """
            )
        )


async def test_source_presence_upgrade_downgrade_forward_recovery(
    pg_container: Any,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"curation_source_presence_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(
        hide_password=False
    )
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = make_async_engine(target_dsn)
    try:
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        before_column, before_indexes = await _schema_state(target_engine)
        assert before_column is None
        assert "source_present" not in (
            before_indexes["idx_curation_items_collection_status_order"]
        )
        await _seed_pre_0065_identity_conflicts(target_engine)

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        upgraded_column, upgraded_indexes = await _schema_state(target_engine)
        assert upgraded_column == ("NO", "true")
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_collections AS collection
                    SET status = 'archived',
                        visibility = 'admin_only',
                        updated_by = 'migration-collection-operator',
                        archived_at = now(),
                        updated_at = clock_timestamp()
                    FROM feature.curated_features AS legacy
                    JOIN feature.curation_items AS item
                      ON item.legacy_projection_id =
                         legacy.curated_feature_id
                    WHERE legacy.display_title =
                          'migration legacy override'
                      AND collection.collection_id =
                          item.collection_id
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id,
                        feature_id,
                        source_id,
                        curation_status,
                        selection_origin,
                        display_title
                    )
                    SELECT
                        legacy.theme_id,
                        'feature:migration-stable-group-new',
                        legacy.source_id,
                        'curated',
                        'source_rule',
                        legacy.display_title
                    FROM feature.curated_features AS legacy
                    WHERE legacy.display_title =
                          'migration legacy override'
                    """
                )
            )
        async with target_engine.connect() as connection:
            provenance_columns = {
                (str(table_name), str(column_name))
                for table_name, column_name in (
                    await connection.execute(
                        text(
                            "SELECT table_name, column_name "
                            "FROM information_schema.columns "
                            "WHERE table_schema = 'feature' "
                            "AND table_name IN ('curated_features','curation_items') "
                            "AND column_name IN ("
                            "'source_updated_at',"
                            "'legacy_projection_id',"
                            "'operator_updated_by','operator_updated_at'"
                            ")"
                        )
                    )
                ).all()
            }
            legacy_provenance = (
                await connection.execute(
                    text(
                        "SELECT display_title, operator_updated_by, "
                        "operator_updated_at IS NOT NULL "
                        "FROM feature.curated_features "
                        "WHERE display_title IN ("
                            "'migration external provenance',"
                            "'migration legacy override'"
                            ") AND operator_updated_by IS NOT NULL "
                        "ORDER BY display_title"
                    )
                )
            ).all()
            canonical_provenance = (
                await connection.execute(
                    text(
                        "SELECT feature_id, status, curation_relation, "
                        "reuse_policy, operator_updated_by, "
                        "operator_updated_at IS NOT NULL "
                        "FROM feature.curation_items "
                        "WHERE feature_id IN ("
                        "'feature:migration-presence',"
                        "'feature:migration-external-api'"
                        ") AND metadata ->> 'legacy_selection_origin' = 'external_api' "
                        "ORDER BY feature_id"
                    )
                )
            ).all()
            projection_fk = (
                await connection.execute(
                    text(
                        """
                        SELECT condeferrable, condeferred
                        FROM pg_constraint
                        WHERE conname =
                            'fk_curation_items_legacy_projection_id_curated_features'
                        """
                    )
                )
            ).one()
            mapped_projection_count = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curation_items AS item
                        JOIN feature.curated_features AS legacy
                          ON legacy.curated_feature_id =
                             item.legacy_projection_id
                        """
                    )
                )
            ).scalar_one()
            unstable_legacy_collection_count = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curation_collections
                        WHERE source_id IS NOT NULL
                          AND metadata @>
                              '{"migrated_from": "feature.curated_features"}'::jsonb
                          AND collection_key IS DISTINCT FROM (
                              'legacy:' || theme_id::text || ':' ||
                              source_id::text || ':' || md5(title)
                          )
                          AND collection_key NOT LIKE (
                              'legacy:' || theme_id::text || ':' ||
                              source_id::text || ':' || md5(title) ||
                              ':split:legacy%'
                          )
                          AND collection_key NOT LIKE (
                              'legacy:' || theme_id::text || ':' ||
                              source_id::text || ':' || md5(title) ||
                              ':split:' || collection_id::text || '%'
                          )
                        """
                    )
                )
            ).scalar_one()
            split_collection_state = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            count(*),
                            count(*) FILTER (
                                WHERE collection_key LIKE '%:split:%'
                            ),
                            count(*) FILTER (
                                WHERE EXISTS (
                                    SELECT 1
                                    FROM feature.curation_items AS item
                                    WHERE item.collection_id =
                                          collection.collection_id
                                )
                            )
                        FROM feature.curation_collections AS collection
                        WHERE collection.title = 'migration split title'
                        """
                    )
                )
            ).one()
            stolen_owner_mismatch_count = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curated_features AS legacy
                        JOIN feature.curation_items AS item
                          ON item.legacy_projection_id =
                             legacy.curated_feature_id
                        JOIN feature.curation_collections AS collection
                          ON collection.collection_id = item.collection_id
                        WHERE legacy.display_title =
                              'migration theft title'
                          AND (
                              collection.theme_id <> legacy.theme_id
                              OR collection.source_id IS DISTINCT FROM
                                 legacy.source_id
                          )
                        """
                    )
                )
            ).scalar_one()
            quarantined_canonical_only_count = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curation_items AS companion
                        JOIN feature.curation_collections AS collection
                          ON collection.collection_id =
                             companion.collection_id
                        WHERE companion.place_name IN (
                              'migration theft canonical master',
                              'migration theft pre-owner other',
                              'migration theft B canonical pair',
                              'migration theft ambiguous owner',
                              'migration theft post-owner',
                              'migration theft C ambiguous canonical pair',
                              'migration theft C safe canonical pair',
                              'migration deleted theft orphan',
                              'migration quarantine prefix canonical'
                          )
                          AND collection.status = 'draft'
                          AND collection.visibility = 'admin_only'
                          AND collection.metadata @>
                              '{"migration_quarantine": "0065"}'::jsonb
                        """
                    )
                )
            ).scalar_one()
            quarantine_roundtrip_state = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            collection.collection_id::text,
                            collection.collection_key,
                            collection.metadata ->>
                                'original_collection_id',
                            array_agg(
                                item.curation_item_id::text
                                ORDER BY item.curation_item_id
                            ) FILTER (
                                WHERE item.curation_item_id IS NOT NULL
                            )
                        FROM feature.curation_collections AS collection
                        LEFT JOIN feature.curation_items AS item
                          ON item.collection_id =
                             collection.collection_id
                        WHERE collection.collection_key LIKE
                              'legacy:quarantine:%'
                          AND collection.metadata @>
                              '{"migration_quarantine": "0065"}'::jsonb
                        GROUP BY collection.collection_id
                        ORDER BY collection.collection_id
                        """
                    )
                )
            ).all()
            manual_collision_keys_preserved = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curation_collections
                        WHERE title IN (
                            'manual stable base collision',
                            'manual stable split collision',
                            'manual upgrade staging collision'
                        )
                        """
                    )
                )
            ).scalar_one()
            stable_group_collection_state = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            count(DISTINCT item.collection_id),
                            bool_and(
                                collection.status = 'archived'
                                AND collection.visibility = 'admin_only'
                                AND collection.updated_by =
                                    'migration-collection-operator'
                            )
                        FROM feature.curated_features AS legacy
                        JOIN feature.curation_items AS item
                          ON item.legacy_projection_id =
                             legacy.curated_feature_id
                        JOIN feature.curation_collections AS collection
                          ON collection.collection_id =
                             item.collection_id
                        WHERE legacy.display_title =
                              'migration legacy override'
                        """
                    )
                )
            ).one()
        assert provenance_columns == {
            ("curated_features", "operator_updated_by"),
            ("curated_features", "operator_updated_at"),
            ("curation_items", "legacy_projection_id"),
            ("curation_items", "source_updated_at"),
            ("curation_items", "operator_updated_by"),
            ("curation_items", "operator_updated_at"),
        }
        assert projection_fk == (True, True)
        assert mapped_projection_count > 0
        assert unstable_legacy_collection_count == 0
        assert split_collection_state == (2, 1, 1)
        assert stolen_owner_mismatch_count == 0
        assert quarantined_canonical_only_count == 9
        assert quarantine_roundtrip_state
        assert manual_collision_keys_preserved == 3
        assert stable_group_collection_state == (1, True)
        assert legacy_provenance == [
            ("migration external provenance", "external-principal", True),
            ("migration legacy override", "external-principal", True),
        ]
        assert canonical_provenance == [
            (
                "feature:migration-external-api",
                "included",
                "nearby_option",
                "manual_review",
                "external-principal",
                True,
            ),
            (
                "feature:migration-presence",
                "rejected",
                "primary_stop",
                "blocked",
                "canonical-operator",
                True,
            ),
        ]
        assert "collection_id, source_present, status, sort_order" in (
            upgraded_indexes["idx_curation_items_collection_status_order"]
        )
        assert "feature_id, source_present, status, collection_id" in (
            upgraded_indexes["idx_curation_items_feature_status_collection"]
        )
        assert "uq_curation_items_active_identity" not in upgraded_indexes
        assert "UNIQUE" in upgraded_indexes["uq_curation_items_identity"]
        assert "NULLS NOT DISTINCT" in upgraded_indexes["uq_curation_items_identity"]
        assert " WHERE " not in upgraded_indexes["uq_curation_items_identity"]
        assert "UNIQUE" in upgraded_indexes["uq_curation_items_legacy_projection_id"]
        assert "legacy_projection_id IS NOT NULL" in (
            upgraded_indexes["uq_curation_items_legacy_projection_id"]
        )
        async with target_engine.begin() as connection:
            normalized = (
                await connection.execute(
                    text(
                        "SELECT external_item_id, count(*) AS total, "
                        "count(*) FILTER (WHERE archived_at IS NULL) AS active, "
                        "max(place_name) FILTER (WHERE archived_at IS NOT NULL) AS kept "
                        "FROM feature.curation_items "
                        "WHERE external_item_id IN "
                        "('resolved-conflict','unresolved-conflict') "
                        "GROUP BY external_item_id ORDER BY external_item_id"
                    )
                )
            ).all()
            reconciled_axes = (
                await connection.execute(
                    text(
                        "SELECT external_item_id, curation_relation, "
                        "reuse_policy, operator_updated_by, metadata "
                        "FROM feature.curation_items "
                        "WHERE external_item_id IN "
                        "('resolved-conflict','unresolved-conflict') "
                        "ORDER BY external_item_id"
                    )
                )
            ).all()
            assert normalized == [
                ("resolved-conflict", 1, 0, "resolved resurrected"),
                ("unresolved-conflict", 1, 0, "unresolved resurrected"),
            ]
            assert reconciled_axes == [
                (
                    "resolved-conflict",
                    "primary_stop",
                    "blocked",
                    "migration-tombstone-operator",
                    {"provider_revision": "latest"},
                ),
                (
                    "unresolved-conflict",
                    "primary_stop",
                    "blocked",
                    "migration-tombstone-operator",
                    {"provider_revision": "latest"},
                ),
            ]
            migrated_legacy = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            count(*) FILTER (
                                WHERE legacy.display_title =
                                    'migration legacy duplicate'
                            ),
                            count(*) FILTER (
                                WHERE legacy.display_title =
                                    'migration legacy duplicate'
                                  AND legacy.archived_at IS NULL
                            ),
                            count(*) FILTER (
                                WHERE legacy.display_title =
                                    'migration legacy duplicate'
                                  AND legacy.metadata @>
                                      '{"merge_projection_detached": true}'::jsonb
                            ),
                            bool_and(legacy.archived_at IS NOT NULL)
                                FILTER (
                                    WHERE legacy.display_title =
                                        'migration status-only archive'
                                ),
                            bool_and(legacy.selection_origin = 'admin')
                                FILTER (
                                    WHERE legacy.display_title =
                                        'migration status-only archive'
                                )
                        FROM feature.curated_features AS legacy
                        WHERE legacy.display_title IN (
                            'migration legacy duplicate',
                            'migration status-only archive'
                        )
                        """
                    )
                )
            ).one()
            assert migrated_legacy == (2, 0, 1, True, True)
            migrated_canonical = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            count(*) FILTER (
                                WHERE item.external_item_id =
                                    'migration-legacy-duplicate'
                            ),
                            bool_and(
                                item.status = 'archived'
                                AND item.archived_at IS NOT NULL
                            )
                        FROM feature.curation_items AS item
                        LEFT JOIN feature.curated_features AS legacy
                          ON legacy.curated_feature_id =
                             item.curation_item_id
                        WHERE item.external_item_id =
                                'migration-legacy-duplicate'
                           OR legacy.display_title =
                                'migration status-only archive'
                        """
                    )
                )
            ).one()
            assert migrated_canonical[0] == 1
            assert migrated_canonical[1] is True
            await connection.execute(
                text(
                    "INSERT INTO feature.curation_items ("
                    "collection_id, feature_id, external_item_id, place_name, "
                    "source_present, status"
                    ") SELECT collection_id, NULL, 'source-absent', "
                    "'source absent', false, 'included' "
                    "FROM feature.curation_collections "
                    "WHERE collection_key = 'migration-presence:2026'"
                )
            )

        await target_engine.dispose()
        with pytest.raises(Exception, match="durable curation state exists"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            assert (
                await connection.execute(
                    text(
                        "SELECT version_num FROM alembic_version "
                        "WHERE version_num = :version"
                    ),
                    {"version": _TARGET_REVISION},
                )
            ).scalar_one() == _TARGET_REVISION
            await connection.execute(
                text(
                    "DELETE FROM feature.curation_items "
                    "WHERE external_item_id = 'source-absent'"
                )
            )
        await target_engine.dispose()
        with pytest.raises(Exception, match="durable curation state exists"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE feature.curation_items "
                    "SET operator_updated_by = NULL, operator_updated_at = NULL"
                )
            )
            await connection.execute(
                text(
                    "UPDATE feature.curated_features "
                    "SET operator_updated_by = NULL, operator_updated_at = NULL"
                )
            )
            await connection.execute(
                text(
                    "DELETE FROM feature.curation_items AS item "
                    "USING feature.curated_features AS legacy "
                    "WHERE legacy.display_title = 'migration legacy override' "
                    "AND item.curation_item_id = legacy.curated_feature_id"
                )
            )
            await connection.execute(
                text(
                    "UPDATE feature.curated_features "
                    "SET feature_id = 'feature:migration-external-api', "
                    "curation_status = 'archived', "
                    "metadata = metadata || "
                    "'{\"merge_projection_detached\": true}'::jsonb, "
                    "archived_at = now(), "
                    "updated_at = clock_timestamp() "
                    "WHERE display_title = 'migration legacy override'"
                )
            )
        await target_engine.dispose()
        with pytest.raises(Exception, match="durable curation state exists"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM feature.curated_features "
                    "WHERE metadata @> "
                    "'{\"merge_projection_detached\": true}'::jsonb"
                )
            )
            non_direct_relations = (
                await connection.execute(
                    text(
                        """
                        UPDATE feature.curation_items AS item
                        SET curation_item_id = x_extension.gen_random_uuid()
                        FROM feature.curated_features AS legacy
                        WHERE legacy.display_title =
                              'migration external provenance'
                          AND item.legacy_projection_id =
                              legacy.curated_feature_id
                        RETURNING item.curation_item_id
                        """
                    )
                )
            ).all()
            assert len(non_direct_relations) == 1
        await target_engine.dispose()
        with pytest.raises(Exception, match="durable curation state exists"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_items
                    SET curation_item_id = legacy_projection_id
                    WHERE legacy_projection_id IS NOT NULL
                      AND legacy_projection_id <> curation_item_id
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.curation_collections (
                        collection_key, theme_id, title
                    )
                    SELECT
                        'legacy:0065-downgrade-stage:' ||
                            collection.collection_id::text,
                        collection.theme_id,
                        'manual downgrade staging collision'
                    FROM feature.curation_collections AS collection
                    WHERE collection.source_id IS NOT NULL
                      AND collection.metadata @>
                          '{"migrated_from": "feature.curated_features"}'::jsonb
                    ORDER BY collection.collection_id
                    LIMIT 1
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    UPDATE feature.curation_collections
                    SET metadata = metadata ||
                        '{"migrated_from": "feature.curated_features"}'::jsonb,
                        updated_by = 'migration-admin-metadata-patch',
                        updated_at = clock_timestamp()
                    WHERE collection_key LIKE 'legacy:quarantine:%'
                      AND created_by = 'migration:0065'
                    """
                )
            )
        await target_engine.dispose()
        await asyncio.to_thread(
            _run_alembic,
            target_dsn,
            _PRE_REVISION,
            downgrade=True,
        )
        target_engine = make_async_engine(target_dsn)
        downgraded_column, downgraded_indexes = await _schema_state(target_engine)
        assert downgraded_column is None
        async with target_engine.connect() as connection:
            remaining_provenance_columns = (
                await connection.execute(
                    text(
                        "SELECT count(*) "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'feature' "
                        "AND table_name IN ('curated_features','curation_items') "
                        "AND column_name IN ("
                        "'source_updated_at',"
                        "'legacy_projection_id',"
                        "'operator_updated_by','operator_updated_at'"
                        ")"
                    )
                )
            ).scalar_one()
            old_key_mismatch_count = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curation_collections AS collection
                        JOIN feature.curated_themes AS theme
                          ON theme.theme_id = collection.theme_id
                        WHERE collection.source_id IS NOT NULL
                          AND collection.metadata @>
                              '{"migrated_from": "feature.curated_features"}'::jsonb
                          AND NOT (
                              collection.collection_key ~
                                  '^legacy:quarantine:[0-9a-f]{8}-[0-9a-f]{4}-'
                                  '[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-'
                                  '[0-9a-f]{12}$'
                              AND collection.created_by =
                                  'migration:0065'
                          )
                          AND collection.collection_key IS DISTINCT FROM (
                              'legacy:' || theme.theme_slug || ':' ||
                              substr(md5(
                                  collection.source_id::text || ':' ||
                                  collection.title
                              ), 1, 20)
                          )
                          AND collection.collection_key NOT LIKE (
                              'legacy:' || theme.theme_slug || ':' ||
                              substr(md5(
                                  collection.source_id::text || ':' ||
                                  collection.title
                              ), 1, 20) || ':split:legacy%'
                          )
                          AND collection.collection_key NOT LIKE (
                              'legacy:' || theme.theme_slug || ':' ||
                              substr(md5(
                                  collection.source_id::text || ':' ||
                                  collection.title
                              ), 1, 20) || ':split:' ||
                              collection.collection_id::text || '%'
                          )
                        """
                    )
                )
            ).scalar_one()
            manual_downgrade_key_preserved = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curation_collections
                        WHERE title = 'manual downgrade staging collision'
                          AND collection_key LIKE
                              'legacy:0065-downgrade-stage:%'
                        """
                    )
                )
            ).scalar_one()
        assert remaining_provenance_columns == 0
        assert old_key_mismatch_count == 0
        assert manual_downgrade_key_preserved == 1
        assert "source_present" not in (
            downgraded_indexes["idx_curation_items_collection_status_order"]
        )
        assert "source_present" not in (
            downgraded_indexes["idx_curation_items_feature_status_collection"]
        )
        assert "uq_curation_items_identity" not in downgraded_indexes
        assert "uq_curation_items_legacy_projection_id" not in downgraded_indexes
        assert " WHERE (archived_at IS NULL)" in (
            downgraded_indexes["uq_curation_items_active_identity"]
        )

        await target_engine.dispose()
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        recovered_column, recovered_indexes = await _schema_state(target_engine)
        assert recovered_column == ("NO", "true")
        assert "source_present" in (
            recovered_indexes["idx_curation_items_collection_status_order"]
        )
        assert "uq_curation_items_identity" in recovered_indexes
        assert "uq_curation_items_legacy_projection_id" in recovered_indexes
        async with target_engine.connect() as connection:
            recovered_key_mismatch_count = (
                await connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM feature.curation_collections
                        WHERE source_id IS NOT NULL
                          AND metadata @>
                              '{"migrated_from": "feature.curated_features"}'::jsonb
                          AND NOT (
                              collection_key ~
                                  '^legacy:quarantine:[0-9a-f]{8}-[0-9a-f]{4}-'
                                  '[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-'
                                  '[0-9a-f]{12}$'
                              AND created_by = 'migration:0065'
                          )
                          AND collection_key IS DISTINCT FROM (
                              'legacy:' || theme_id::text || ':' ||
                              source_id::text || ':' || md5(title)
                          )
                          AND collection_key NOT LIKE (
                              'legacy:' || theme_id::text || ':' ||
                              source_id::text || ':' || md5(title) ||
                              ':split:legacy%'
                          )
                          AND collection_key NOT LIKE (
                              'legacy:' || theme_id::text || ':' ||
                              source_id::text || ':' || md5(title) ||
                              ':split:' || collection_id::text || '%'
                          )
                        """
                    )
                )
            ).scalar_one()
            recovered_quarantine_roundtrip_state = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            collection.collection_id::text,
                            collection.collection_key,
                            collection.metadata ->>
                                'original_collection_id',
                            array_agg(
                                item.curation_item_id::text
                                ORDER BY item.curation_item_id
                            ) FILTER (
                                WHERE item.curation_item_id IS NOT NULL
                            )
                        FROM feature.curation_collections AS collection
                        LEFT JOIN feature.curation_items AS item
                          ON item.collection_id =
                             collection.collection_id
                        WHERE collection.collection_key LIKE
                              'legacy:quarantine:%'
                          AND collection.metadata @>
                              '{"migration_quarantine": "0065"}'::jsonb
                        GROUP BY collection.collection_id
                        ORDER BY collection.collection_id
                        """
                    )
                )
            ).all()
        assert recovered_key_mismatch_count == 0
        assert recovered_quarantine_roundtrip_state == quarantine_roundtrip_state
    finally:
        await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            )
        await admin_engine.dispose()
