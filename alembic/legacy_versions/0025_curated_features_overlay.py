"""curated_features overlay table set 추가.

Revision ID: 0025_curated_features
Revises: 0024_import_job_events
Create Date: 2026-06-12

T-223c-1은 테마형 feature 후보를 ``feature.features`` 복제 없이 overlay로 관리하는
DB/API 기반을 추가한다. TripMate는 이후 이 overlay를 REST snapshot으로 읽어
``curated_trip_plans``에 복사한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025_curated_features"
down_revision: str | Sequence[str] | None = "0024_import_job_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feature.curated_themes (
            theme_id          UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
            theme_slug        TEXT NOT NULL UNIQUE,
            theme_name        TEXT NOT NULL,
            theme_description TEXT NOT NULL DEFAULT '',
            theme_group       TEXT NOT NULL,
            default_curated   BOOLEAN NOT NULL DEFAULT false,
            visibility        TEXT NOT NULL DEFAULT 'admin_only',
            metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_curated_themes_visibility
                CHECK (visibility IN ('admin_only','public','tripmate'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_themes_group_visibility
        ON feature.curated_themes (theme_group, visibility, theme_slug)
        """
    )

    op.execute(
        """
        CREATE TABLE feature.curated_sources (
            source_id               UUID PRIMARY KEY
                DEFAULT x_extension.gen_random_uuid(),
            provider                TEXT NOT NULL,
            dataset_key             TEXT NOT NULL,
            source_name             TEXT NOT NULL,
            source_url              TEXT,
            source_kind             TEXT NOT NULL,
            license                 TEXT,
            update_cycle            TEXT NOT NULL DEFAULT 'unknown',
            last_source_modified_at DATE,
            last_checked_at         TIMESTAMPTZ,
            next_expected_at        DATE,
            row_count               INTEGER,
            freshness_note          TEXT,
            provider_status         TEXT NOT NULL DEFAULT 'implemented',
            metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_curated_sources_provider_dataset
                UNIQUE (provider, dataset_key),
            CONSTRAINT ck_curated_sources_source_kind
                CHECK (source_kind IN ('openapi','filedata','standard','internal','manual')),
            CONSTRAINT ck_curated_sources_update_cycle
                CHECK (
                    update_cycle IN (
                        'realtime','daily','weekly','monthly','annual','one_time','unknown'
                    )
                ),
            CONSTRAINT ck_curated_sources_provider_status
                CHECK (
                    provider_status IN (
                        'implemented','provider_needed','manual_only','deprecated'
                    )
                ),
            CONSTRAINT ck_curated_sources_row_count
                CHECK (row_count IS NULL OR row_count >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_sources_provider
        ON feature.curated_sources (provider, dataset_key)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_sources_status
        ON feature.curated_sources (provider_status, updated_at DESC, source_id DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE feature.curated_source_rules (
            rule_id        UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
            theme_id       UUID NOT NULL
                REFERENCES feature.curated_themes(theme_id) ON DELETE CASCADE,
            source_id      UUID NOT NULL
                REFERENCES feature.curated_sources(source_id) ON DELETE CASCADE,
            dataset_key    TEXT NOT NULL,
            place_kind     TEXT,
            category       TEXT,
            region_scope   JSONB NOT NULL DEFAULT '{}'::jsonb,
            default_action TEXT NOT NULL DEFAULT 'candidate',
            priority       INTEGER NOT NULL DEFAULT 0,
            enabled        BOOLEAN NOT NULL DEFAULT true,
            metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_curated_source_rules_action
                CHECK (default_action IN ('candidate','curated','ignore')),
            CONSTRAINT ck_curated_source_rules_region_scope
                CHECK (jsonb_typeof(region_scope) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_source_rules_enabled
        ON feature.curated_source_rules (enabled, source_id, priority DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_source_rules_theme
        ON feature.curated_source_rules (theme_id, enabled, priority DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE feature.curated_features (
            curated_feature_id  UUID PRIMARY KEY
                DEFAULT x_extension.gen_random_uuid(),
            theme_id            UUID NOT NULL
                REFERENCES feature.curated_themes(theme_id) ON DELETE CASCADE,
            feature_id          TEXT NOT NULL
                REFERENCES feature.features(feature_id) ON DELETE CASCADE,
            source_id           UUID NOT NULL
                REFERENCES feature.curated_sources(source_id) ON DELETE RESTRICT,
            source_record_key   TEXT
                REFERENCES provider_sync.source_records(source_record_key)
                ON DELETE SET NULL,
            curation_status     TEXT NOT NULL DEFAULT 'candidate',
            selection_origin    TEXT NOT NULL DEFAULT 'source_rule',
            selected_by         TEXT,
            selected_at         TIMESTAMPTZ,
            rejected_by         TEXT,
            rejected_at         TIMESTAMPTZ,
            rejection_reason    TEXT,
            rank_score          NUMERIC(10, 4) NOT NULL DEFAULT 0,
            display_title       TEXT,
            display_summary     TEXT,
            tripmate_relation   TEXT NOT NULL DEFAULT 'nearby_option',
            tripmate_copy_policy TEXT NOT NULL DEFAULT 'manual_review',
            copy_version        INTEGER NOT NULL DEFAULT 1,
            metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            archived_at         TIMESTAMPTZ,
            CONSTRAINT ck_curated_features_status
                CHECK (curation_status IN ('candidate','curated','rejected','archived')),
            CONSTRAINT ck_curated_features_selection_origin
                CHECK (selection_origin IN ('source_rule','admin','external_api')),
            CONSTRAINT ck_curated_features_tripmate_relation
                CHECK (
                    tripmate_relation IN (
                        'primary_stop','food_stop','cafe_stop','bookstore_stop',
                        'nearby_option','accessibility_support','pet_support',
                        'family_support','theme_area_anchor'
                    )
                ),
            CONSTRAINT ck_curated_features_copy_policy
                CHECK (
                    tripmate_copy_policy IN (
                        'copy_allowed','copy_blocked','manual_review'
                    )
                ),
            CONSTRAINT ck_curated_features_copy_version
                CHECK (copy_version >= 1),
            CONSTRAINT ck_curated_features_metadata
                CHECK (jsonb_typeof(metadata) = 'object')
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_curated_features_theme_feature_active
        ON feature.curated_features (theme_id, feature_id)
        WHERE archived_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_features_status_keyset
        ON feature.curated_features (
            curation_status, updated_at DESC, curated_feature_id DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_features_theme_status_score
        ON feature.curated_features (
            theme_id, curation_status, rank_score DESC, curated_feature_id DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_features_source_status
        ON feature.curated_features (source_id, curation_status)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_curated_features_feature
        ON feature.curated_features (feature_id)
        """
    )

    _seed_curated_metadata()


def _seed_curated_metadata() -> None:
    op.execute(
        """
        INSERT INTO feature.curated_themes (
            theme_slug, theme_name, theme_description, theme_group,
            default_curated, visibility, metadata
        ) VALUES
            ('bookstores', '책방 여행', '독립서점·북카페·아동서점·중고서점 후보', 'books',
             false, 'tripmate', '{"icon":"book-open","color":"P-12"}'::jsonb),
            ('world-food', '세계음식 여행', '세계음식점·무슬림 친화·지역 향토음식 후보', 'food',
             false, 'tripmate', '{"icon":"utensils","color":"P-03"}'::jsonb),
            ('barrier-free', '무장애 여행', '무장애 관광지 후보', 'accessibility',
             false, 'tripmate', '{"icon":"accessibility","color":"P-08"}'::jsonb),
            ('pet-friendly', '반려동물 동반', '반려동물 동반 가능 문화시설 후보', 'pet',
             false, 'tripmate', '{"icon":"paw-print","color":"P-06"}'::jsonb),
            ('family-culture', '가족 문화', '가족·영유아 동반 문화시설 후보', 'family',
             false, 'tripmate', '{"icon":"baby","color":"P-09"}'::jsonb),
            ('media-places', '미디어 촬영지', '방송·영화·콘텐츠 촬영지 후보', 'culture',
             false, 'tripmate', '{"icon":"clapperboard","color":"P-10"}'::jsonb),
            ('leisure', '레저 여행', '레저활동·캠핑·강습·골프 후보', 'leisure',
             false, 'tripmate', '{"icon":"tent","color":"P-13"}'::jsonb),
            ('theme-streets', '특화거리', '음식·문화 특화거리 anchor 후보', 'culture',
             false, 'tripmate', '{"icon":"map-pinned","color":"P-14"}'::jsonb)
        """
    )

    op.execute(
        """
        INSERT INTO feature.curated_sources (
            provider, dataset_key, source_name, source_url, source_kind,
            license, update_cycle, last_source_modified_at, next_expected_at,
            row_count, freshness_note, provider_status, metadata
        ) VALUES
            ('python-mcst-api', 'mcst_world_restaurants_csv', '한국문화정보원 세계음식점',
             NULL, 'filedata', NULL, 'unknown', NULL, NULL, NULL, NULL,
             'implemented', '{"slug":"world_restaurants_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_independent_bookstores_csv', '한국문화정보원 독립서점',
             'https://www.data.go.kr/data/15138901/openapi.do?recommendDataYn=Y',
             'filedata', NULL, 'realtime', '2025-08-13', NULL, NULL, NULL,
             'implemented', '{"slug":"independent_bookstores_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_cafe_bookstores_csv', '한국문화정보원 카페가 있는 서점',
             'https://www.data.go.kr/data/15138904/openapi.do?recommendDataYn=Y',
             'filedata', NULL, 'realtime', '2025-08-13', NULL, NULL, NULL,
             'implemented', '{"slug":"cafe_bookstores_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_children_bookstores_csv', '한국문화정보원 아동서점',
             'https://www.data.go.kr/data/15089405/fileData.do?recommendDataYn=Y',
             'filedata', NULL, 'annual', '2025-08-14', NULL, 795, NULL,
             'implemented', '{"slug":"children_bookstores_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_used_bookstores_csv', '한국문화정보원 중고서점',
             'https://www.data.go.kr/data/15100298/openapi.do?recommendDataYn=Y',
             'filedata', NULL, 'realtime', '2025-08-13', NULL, NULL, NULL,
             'implemented', '{"slug":"used_bookstores_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_media_famous_places_csv', '한국문화정보원 미디어 촬영지',
             NULL, 'filedata', NULL, 'unknown', NULL, NULL, NULL, NULL,
             'implemented', '{"slug":"media_famous_places_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_barrier_free_places_csv', '한국문화정보원 무장애 관광지',
             NULL, 'filedata', NULL, 'unknown', NULL, NULL, NULL, NULL,
             'implemented', '{"slug":"barrier_free_places_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_pet_friendly_culture_facilities_csv',
             '한국문화정보원 반려동물 동반 가능 문화시설', NULL, 'filedata',
             NULL, 'unknown', NULL, NULL, NULL, NULL, 'implemented',
             '{"slug":"pet_friendly_culture_facilities_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_leisure_activity_facilities_csv',
             '한국문화정보원 레저활동 시설', NULL, 'filedata', NULL, 'unknown',
             NULL, NULL, NULL, NULL, 'implemented',
             '{"slug":"leisure_activity_facilities_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_leisure_camping_facilities_csv',
             '한국문화정보원 레저 캠핑 시설', NULL, 'filedata', NULL, 'unknown',
             NULL, NULL, NULL, NULL, 'implemented',
             '{"slug":"leisure_camping_facilities_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_leisure_classes_csv', '한국문화정보원 레저 클래스',
             NULL, 'filedata', NULL, 'unknown', NULL, NULL, NULL,
             '좌표 컬럼 없음, 주소 기반 후보화', 'implemented',
             '{"slug":"leisure_classes_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_family_infant_culture_facilities_csv',
             '한국문화정보원 가족·영유아 동반 문화시설', NULL, 'filedata',
             NULL, 'unknown', NULL, NULL, NULL, NULL, 'implemented',
             '{"slug":"family_infant_culture_facilities_csv","surface":"csv"}'::jsonb),
            ('python-mcst-api', 'mcst_golf_courses_status', '한국문화정보원 골프장 현황',
             NULL, 'filedata', NULL, 'unknown', NULL, NULL, NULL,
             '좌표 없음, 주소 기반 후보화', 'implemented',
             '{"slug":"golf_courses_status","surface":"csv"}'::jsonb),
            ('python-datagokr-api', 'datagokr_seoul_bookstores', '서울특별시 책방',
             'https://www.data.go.kr/data/15084328/fileData.do',
             'filedata', NULL, 'one_time', '2025-12-02', NULL, 555,
             '서울 열린데이터광장 원천 서비스 종료 안내 노출', 'implemented',
             '{"surface":"fileData"}'::jsonb),
            ('python-datagokr-api', 'datagokr_gyeonggi_muslim_friendly_restaurants',
             '경기관광공사 무슬림 친화 음식점',
             'https://www.data.go.kr/data/15099378/fileData.do',
             'filedata', NULL, 'one_time', '2025-09-23', NULL, 51,
             '2024-05 기준 조사', 'implemented', '{"surface":"fileData"}'::jsonb),
            ('python-datagokr-api', 'datagokr_ansan_world_restaurants',
             '경기도 안산시 다문화 세계맛집',
             'https://www.data.go.kr/data/15152605/fileData.do',
             'filedata', NULL, 'one_time', '2025-11-20', NULL, 44,
             '다국어 설명 포함', 'implemented', '{"surface":"fileData"}'::jsonb),
            ('python-datagokr-api', 'datagokr_jeju_local_restaurants',
             '제주특별자치도 향토음식점',
             'https://www.data.go.kr/data/15043695/fileData.do?recommendDataYn=Y',
             'filedata', NULL, 'annual', '2025-11-20', '2026-11-20', 62,
             NULL, 'implemented', '{"surface":"fileData"}'::jsonb),
            ('python-datagokr-api', 'standard_special_streets', '전국지역특화거리 표준데이터',
             'https://www.data.go.kr/data/15017322/standard.do',
             'standard', NULL, 'annual', '2025-12-03', NULL, NULL,
             'geometry 없는 현 단계에서는 theme_area_anchor place로 보존',
             'implemented', '{"surface":"standard"}'::jsonb)
        """
    )

    op.execute(
        """
        WITH rule_seed(theme_slug, provider, dataset_key, place_kind, default_action,
                       priority, relation, copy_policy) AS (
            VALUES
                ('world-food','python-mcst-api','mcst_world_restaurants_csv',
                 'world_restaurant','candidate',80,'food_stop','copy_allowed'),
                ('bookstores','python-mcst-api','mcst_independent_bookstores_csv',
                 'independent_bookstore','candidate',80,'bookstore_stop','copy_allowed'),
                ('bookstores','python-mcst-api','mcst_cafe_bookstores_csv',
                 'cafe_bookstore','candidate',85,'cafe_stop','copy_allowed'),
                ('bookstores','python-mcst-api','mcst_children_bookstores_csv',
                 'children_bookstore','candidate',70,'bookstore_stop','copy_allowed'),
                ('bookstores','python-mcst-api','mcst_used_bookstores_csv',
                 'used_bookstore','candidate',75,'bookstore_stop','copy_allowed'),
                ('media-places','python-mcst-api','mcst_media_famous_places_csv',
                 'media_famous_place','candidate',50,'primary_stop','manual_review'),
                ('barrier-free','python-mcst-api','mcst_barrier_free_places_csv',
                 'barrier_free_place','candidate',60,'accessibility_support','copy_allowed'),
                ('pet-friendly','python-mcst-api',
                 'mcst_pet_friendly_culture_facilities_csv',
                 'pet_friendly_culture_facility','candidate',60,'pet_support','copy_allowed'),
                ('leisure','python-mcst-api','mcst_leisure_activity_facilities_csv',
                 'leisure_activity_facility','candidate',50,'nearby_option','manual_review'),
                ('leisure','python-mcst-api','mcst_leisure_camping_facilities_csv',
                 'leisure_camping_facility','candidate',55,'nearby_option','manual_review'),
                ('leisure','python-mcst-api','mcst_leisure_classes_csv',
                 'leisure_class','candidate',40,'nearby_option','manual_review'),
                ('family-culture','python-mcst-api',
                 'mcst_family_infant_culture_facilities_csv',
                 'family_culture_facility','candidate',60,'family_support','copy_allowed'),
                ('leisure','python-mcst-api','mcst_golf_courses_status',
                 'golf_course','candidate',45,'nearby_option','manual_review'),
                ('bookstores','python-datagokr-api','datagokr_seoul_bookstores',
                 'seoul_bookstore','candidate',70,'bookstore_stop','copy_allowed'),
                ('world-food','python-datagokr-api',
                 'datagokr_gyeonggi_muslim_friendly_restaurants',
                 'muslim_friendly_restaurant','candidate',75,'food_stop','copy_allowed'),
                ('world-food','python-datagokr-api','datagokr_ansan_world_restaurants',
                 'ansan_world_restaurant','candidate',75,'food_stop','copy_allowed'),
                ('world-food','python-datagokr-api','datagokr_jeju_local_restaurants',
                 'jeju_local_restaurant','candidate',70,'food_stop','copy_allowed'),
                ('theme-streets','python-datagokr-api','standard_special_streets',
                 'theme_area_anchor','candidate',60,'theme_area_anchor','manual_review')
        )
        INSERT INTO feature.curated_source_rules (
            theme_id, source_id, dataset_key, place_kind, default_action,
            priority, metadata
        )
        SELECT
            t.theme_id,
            s.source_id,
            r.dataset_key,
            r.place_kind,
            r.default_action,
            r.priority,
            jsonb_build_object(
                'tripmate_relation', r.relation,
                'tripmate_copy_policy', r.copy_policy,
                'seed', 'T-223c-1'
            )
        FROM rule_seed AS r
        JOIN feature.curated_themes AS t ON t.theme_slug = r.theme_slug
        JOIN feature.curated_sources AS s
          ON s.provider = r.provider AND s.dataset_key = r.dataset_key
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feature.curated_features")
    op.execute("DROP TABLE IF EXISTS feature.curated_source_rules")
    op.execute("DROP TABLE IF EXISTS feature.curated_sources")
    op.execute("DROP TABLE IF EXISTS feature.curated_themes")
