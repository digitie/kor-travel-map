"""T-VN-33A — provider dataset 정본과 lineage 확장/seed/backfill.

Revision ID: 0089_tvn33_expand_seed
Revises: 0087_route_area_subtypes

이 revision은 런타임 registry를 import하지 않는다. provider×dataset과 실제
Dagster handler binding은 아래의 versioned literal seed가 유일한 생성 경계다.
기존 DB에서 발견하는 pair는 forensic history로만 보존하며 inactive row로 넣는다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final

from sqlalchemy import text
from sqlalchemy.util.concurrency import await_only

from alembic import op

revision: str = "0089_tvn33_expand_seed"
down_revision: str | Sequence[str] | None = "0088_source_record_lineage_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_sql_script(sql: str) -> None:
    """asyncpg prepared statement가 거부하는 복수 DDL을 현재 transaction에서 실행한다."""
    raw_connection = op.get_bind().connection.driver_connection
    await_only(raw_connection.execute(sql))


# (provider, dataset_key, Korean display name, produced kind, initial scope,
#  Dagster handler job).  ``None`` handler rows are historical-only catalog
# entries: the row is intentionally inactive and owns no operation/scope.
_DATASET_SEED: Final[tuple[tuple[str, str, str, str, str, str | None], ...]] = (
    (
        "data.go.kr-standard",
        "datagokr_cultural_festivals",
        "전국문화축제표준데이터 (1차 source, ADR-042)",
        "event",
        "dataset_wide",
        "feature_event_datagokr_cultural_festivals_job",
    ),
    (
        "data.go.kr-standard",
        "datagokr_museums",
        "전국박물관미술관표준데이터",
        "place",
        "dataset_wide",
        "feature_place_standard_museums_job",
    ),
    (
        "data.go.kr-standard",
        "datagokr_tourist_attractions",
        "전국관광지표준데이터",
        "place",
        "dataset_wide",
        "feature_place_standard_tourist_attractions_job",
    ),
    (
        "data.go.kr-standard",
        "datagokr_parking_lots",
        "전국주차장표준데이터",
        "place",
        "dataset_wide",
        "feature_place_standard_parking_lots_job",
    ),
    (
        "data.go.kr-standard",
        "standard_special_streets",
        "전국지역특화거리표준데이터 (테마 구역 anchor)",
        "place",
        "dataset_wide",
        "feature_place_standard_special_streets_job",
    ),
    (
        "python-kma-api",
        "kma_short_forecast",
        "KMA 단기예보 (getVilageFcst, 3시간×5일)",
        "weather",
        "target_grids",
        "feature_weather_kma_short_forecast_job",
    ),
    (
        "python-kma-api",
        "kma_ultra_short_nowcast",
        "KMA 초단기실황 (getUltraSrtNcst, 관측)",
        "weather",
        "target_grids",
        "feature_weather_kma_ultra_short_nowcast_job",
    ),
    (
        "python-kma-api",
        "kma_ultra_short_forecast",
        "KMA 초단기예보 (getUltraSrtFcst, 30분×6시간)",
        "weather",
        "target_grids",
        "feature_weather_kma_ultra_short_forecast_job",
    ),
    (
        "python-kma-api",
        "kma_mid_forecast",
        "KMA 중기예보 (getMidLandFcst + getMidTa, 3~10일)",
        "weather",
        "dataset_wide",
        "feature_weather_kma_mid_forecast_job",
    ),
    # place phone enrichment — provider를 호출자가 주고(`enrichment.py`) dataset_key는
    # 고정이다. catalog에 없으므로 문서가 고정한 3종을 직접 seed한다. 자기 operation은
    # 없고 record만 받으므로 `_WRITE_TARGET_DATASETS`가 active로 만든다.
    (
        "kakao-local-api",
        "place_phone_enrichment",
        "Kakao Local 전화번호 보강",
        "place",
        "dataset_wide",
        None,
    ),
    (
        "naver-search-api",
        "place_phone_enrichment",
        "Naver Search 전화번호 보강",
        "place",
        "dataset_wide",
        None,
    ),
    (
        "google-places-api-new",
        "place_phone_enrichment",
        "Google Places 전화번호 보강",
        "place",
        "dataset_wide",
        None,
    ),
    # KMA 예보 operation이 격자 단위로 남기는 source record의 dataset이다. 자기
    # operation은 없고(예보 operation이 대신 돈다) 쓰기만 받으므로
    # ``_WRITE_TARGET_DATASETS``가 active로 만든다.
    (
        "python-kma-api",
        "kma_ultra_short_grid",
        "KMA 초단기 격자 관측 source record",
        "weather",
        "dataset_wide",
        None,
    ),
    (
        "python-kma-api",
        "kma_short_grid",
        "KMA 단기 격자 예보 source record",
        "weather",
        "dataset_wide",
        None,
    ),
    (
        "python-kma-api",
        "kma_weather_alerts",
        "KMA 기상특보 (특보×구역 fan-out)",
        "notice",
        "dataset_wide",
        "feature_notice_kma_weather_alerts_job",
    ),
    (
        "python-khoa-api",
        "khoa_beaches",
        "해양수산부 해수욕장정보",
        "place",
        "dataset_wide",
        "feature_place_khoa_beaches_job",
    ),
    (
        "python-airkorea-api",
        "airkorea_stations",
        "대기질 측정소 (weather-kind Feature)",
        "weather",
        "dataset_wide",
        None,
    ),
    (
        "python-airkorea-api",
        "airkorea_air_quality",
        "대기질 측정소 + 측정값 (weather Feature + WeatherValue)",
        "weather",
        "dataset_wide",
        "feature_weather_airkorea_air_quality_job",
    ),
    (
        "python-opinet-api",
        "opinet_fuel_station_details",
        "OpiNet 주유소 상세 (place Feature)",
        "place",
        "dataset_wide",
        "feature_place_opinet_stations_job",
    ),
    (
        "python-opinet-api",
        "opinet_gas_station_prices",
        "OpiNet 유가 시계열 (PriceValue)",
        "price",
        "dataset_wide",
        "feature_price_opinet_stations_job",
    ),
    (
        "python-krex-api",
        "krex_rest_areas",
        "고속도로 휴게소 (place Feature)",
        "place",
        "dataset_wide",
        "feature_place_krex_rest_areas_job",
    ),
    (
        "python-krex-api",
        "krex_rest_area_prices",
        "휴게소 food/fuel 가격 시계열 (PriceValue)",
        "price",
        "dataset_wide",
        "feature_price_krex_rest_areas_job",
    ),
    (
        "python-krex-api",
        "krex_rest_area_weather",
        "휴게소 관측 기상 (observed WeatherValue + weather Feature)",
        "weather",
        "dataset_wide",
        "feature_weather_krex_rest_areas_job",
    ),
    (
        "python-krex-api",
        "krex_traffic_notices",
        "고속도로 교통 공지/돌발 (notice Feature)",
        "notice",
        "dataset_wide",
        "feature_notice_krex_traffic_notices_job",
    ),
    (
        "python-krforest-api",
        "krforest_recreation_forests",
        "전국자연휴양림",
        "place",
        "dataset_wide",
        "feature_place_krforest_recreation_forests_job",
    ),
    (
        "python-krforest-api",
        "krforest_arboretums",
        "수목원/식물원 (SHP)",
        "place",
        "dataset_wide",
        "feature_place_krforest_arboretums_job",
    ),
    (
        "python-krairport-api",
        "krairport_airports",
        "공항 메타데이터 (번들 정적)",
        "place",
        "dataset_wide",
        "feature_place_krairport_airports_job",
    ),
    (
        "python-krheritage-api",
        "krheritage_heritage_features",
        "국가유산 (국보/보물/사적/명승 등; place 또는 area)",
        "place",
        "dataset_wide",
        "feature_place_krheritage_items_job",
    ),
    (
        "python-krheritage-api",
        "krheritage_event_list",
        "국가유산 행사 목록",
        "event",
        "dataset_wide",
        "feature_event_krheritage_events_job",
    ),
    (
        "python-mois-api",
        "mois_license_features_bulk",
        "MOIS 지방행정 인허가 bulk (영업중, PROMOTED 42업종)",
        "place",
        "dataset_wide",
        "feature_place_mois_licenses_job",
    ),
    (
        "python-mois-api",
        "mois_license_features_history",
        "MOIS 인허가 history (증분/변경분)",
        "place",
        "dataset_wide",
        # `mois.py`의 증분 job이 이 dataset으로 돈다.
        "mois_license_incremental_update",
    ),
    (
        "python-mois-api",
        "mois_license_features_closed",
        "MOIS 인허가 closed (폐업 tombstone/inactive)",
        "place",
        "dataset_wide",
        # `mois.py`가 이 dataset으로 import job을 시작하고 sync state를 기록한다.
        # operation이 없으면 membership triple을 만들 수 없어 23503으로 죽는다.
        "mois_license_closed_update",
    ),
    (
        "python-mois-api",
        "mois_license_detail",
        "MOIS 인허가 상세(detail) 보강",
        "place",
        "dataset_wide",
        "mois_license_detail_update",
    ),
    (
        "python-visitkorea-api",
        "visitkorea_festival_events",
        "VisitKorea 축제 enrichment (datagokr 1차에 2차 보강)",
        "event",
        "dataset_wide",
        "feature_event_visitkorea_enrichment_job",
    ),
    (
        "python-visitkorea-api",
        "place_phone_enrichment",
        "전화번호 보강 (place detail.phones; candidate: kakao/naver/google)",
        "place",
        "dataset_wide",
        None,
    ),
    (
        "kor-travel-concierge-youtube",
        "youtube_place_candidates",
        "kor-travel-concierge YouTube 장소 후보",
        "place",
        "dataset_wide",
        "feature_place_kor_travel_concierge_youtube_job",
    ),
    (
        "python-datagokr-api",
        "datagokr_seoul_bookstores",
        "서울특별시 책방(서점)",
        "place",
        "dataset_wide",
        "feature_place_datagokr_seoul_bookstores_job",
    ),
    (
        "python-datagokr-api",
        "datagokr_gyeonggi_muslim_friendly_restaurants",
        "경기도 무슬림 친화 음식점",
        "place",
        "dataset_wide",
        "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job",
    ),
    (
        "python-datagokr-api",
        "datagokr_ansan_world_restaurants",
        "안산 세계맛집",
        "place",
        "dataset_wide",
        "feature_place_datagokr_ansan_world_restaurants_job",
    ),
    (
        "python-datagokr-api",
        "datagokr_jeju_local_restaurants",
        "제주 향토음식점",
        "place",
        "dataset_wide",
        "feature_place_datagokr_jeju_local_restaurants_job",
    ),
    (
        "python-mcst-api",
        "mcst_world_restaurants_csv",
        "세계음식 음식점",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_pet_friendly_culture_facilities_csv",
        "반려동물 동반 가능 문화시설",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_barrier_free_places_csv",
        "무장애 관광지",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_leisure_activity_facilities_csv",
        "레저활동 시설",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_family_infant_culture_facilities_csv",
        "가족/영유아 동반 문화시설",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_leisure_camping_facilities_csv",
        "레저 캠핑 시설",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_leisure_classes_csv",
        "레저 클래스/강습",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_media_famous_places_csv",
        "미디어콘텐츠 영상 촬영지",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_independent_bookstores_csv",
        "독립서점",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_cafe_bookstores_csv",
        "북카페",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_children_bookstores_csv",
        "아동서점",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_used_bookstores_csv",
        "중고서점",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-mcst-api",
        "mcst_golf_courses_status",
        "전국 골프장 현황",
        "place",
        "dataset_wide",
        "feature_place_mcst_culture_job",
    ),
    (
        "python-knps-api",
        "knps_visitor_centers",
        "국립공원 탐방안내소",
        "place",
        "dataset_wide",
        "feature_place_knps_points_job",
    ),
    (
        "python-knps-api",
        "knps_restrooms",
        "국립공원 화장실",
        "place",
        "dataset_wide",
        "feature_place_knps_points_job",
    ),
    (
        "python-knps-api",
        "knps_campgrounds",
        "국립공원 야영장",
        "place",
        "dataset_wide",
        "feature_place_knps_points_job",
    ),
    (
        "python-knps-api",
        "knps_shelters",
        "국립공원 대피소(산장)",
        "place",
        "dataset_wide",
        "feature_place_knps_points_job",
    ),
    (
        "python-knps-api",
        "knps_cultural_resources",
        "국립공원 문화자원(동적 category)",
        "place",
        "dataset_wide",
        "feature_place_knps_points_job",
    ),
    (
        "python-knps-api",
        "knps_trails",
        "국립공원 탐방로(LINESTRING)",
        "route",
        "dataset_wide",
        "feature_geometry_knps_records_job",
    ),
    (
        "python-knps-api",
        "knps_linear_facilities",
        "국립공원 선형 시설도로(LINESTRING)",
        "route",
        "dataset_wide",
        "feature_geometry_knps_records_job",
    ),
    (
        "python-knps-api",
        "knps_park_boundaries",
        "국립공원 경계(POLYGON)",
        "area",
        "dataset_wide",
        "feature_geometry_knps_records_job",
    ),
    (
        "python-knps-api",
        "knps_hazard_zones",
        "국립공원 위험지역(POLYGON)",
        "area",
        "dataset_wide",
        "feature_geometry_knps_records_job",
    ),
    (
        "python-knps-api",
        "knps_protected_areas",
        "국립공원 보호지역(POLYGON)",
        "area",
        "dataset_wide",
        "feature_geometry_knps_records_job",
    ),
)


# Fixture preview는 Dagster refresh handler와 별도 operation이다. migration은
# runtime registry를 읽지 않으므로, cutover 시점의 fixture 지원 쌍을 literal로 고정한다.
# 자기 operation은 없지만 **source record를 직접 받는** dataset.
#
# `is_active`는 "operation handler가 있다"가 아니라 **"쓰기를 받을 수 있다"**를
# 뜻한다. 두 축이 다르다는 것이 KMA에서 드러난다 — operation은
# `kma_ultra_short_nowcast`/`kma_short_forecast` 같은 예보 단위인데, source record는
# 격자 단위 `kma_*_grid`로 쓴다(`providers/kma.py`의 `KMA_*_GRID_DATASET_KEY`).
# 이 집합이 없으면 두 격자가 legacy pair sweep으로 `is_active=false` seed되고,
# cutover 직후 KMA 적재가 `ck_provider_dataset_active_write`로 전멸한다(prod에 실제
# record 118행 존재). operation과 record의 dataset_key를 조인해 유도하려 하면
# 이 4쌍에서 0행이 나오므로, 유도하지 않고 명시한다.
_WRITE_TARGET_DATASETS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("python-kma-api", "kma_ultra_short_grid"),
        ("python-kma-api", "kma_short_grid"),
        ("python-airkorea-api", "airkorea_stations"),
        ("python-mois-api", "mois_license_features_closed"),
        ("python-mois-api", "mois_license_detail"),
        # place phone enrichment은 provider를 **호출자가** 준다
        # (`enrichment.py`의 `normalize_provider_name`). catalog에 나타나지 않으므로
        # 문서(`docs/etl/place-phone-enrichment.md`)가 고정한 3종을 여기 박는다.
        # 빠지면 적재가 `LookupError: no active provider dataset is seeded`로 죽는다.
        ("kakao-local-api", "place_phone_enrichment"),
        ("naver-search-api", "place_phone_enrichment"),
        ("google-places-api-new", "place_phone_enrichment"),
    }
)


_FIXTURE_PREVIEW_DATASETS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("data.go.kr-standard", "datagokr_cultural_festivals"),
        ("python-kma-api", "kma_short_forecast"),
        ("python-kma-api", "kma_ultra_short_nowcast"),
        ("python-kma-api", "kma_ultra_short_forecast"),
        ("python-opinet-api", "opinet_fuel_station_details"),
        ("python-opinet-api", "opinet_gas_station_prices"),
        ("python-kma-api", "kma_weather_alerts"),
        ("python-krex-api", "krex_rest_areas"),
        ("python-krex-api", "krex_rest_area_prices"),
        ("python-krex-api", "krex_rest_area_weather"),
        ("python-krex-api", "krex_traffic_notices"),
        ("python-krforest-api", "krforest_recreation_forests"),
        ("python-krforest-api", "krforest_arboretums"),
        ("data.go.kr-standard", "datagokr_museums"),
        ("data.go.kr-standard", "datagokr_tourist_attractions"),
        ("data.go.kr-standard", "datagokr_parking_lots"),
        ("python-khoa-api", "khoa_beaches"),
        ("python-krairport-api", "krairport_airports"),
        ("python-airkorea-api", "airkorea_stations"),
        ("python-airkorea-api", "airkorea_air_quality"),
        ("python-mcst-api", "mcst_world_restaurants_csv"),
        ("python-mcst-api", "mcst_independent_bookstores_csv"),
        ("python-mcst-api", "mcst_children_bookstores_csv"),
    }
)


def _source_kind(provider: str) -> str:
    """고정 seed의 provider 유형을 DB enum 범위로 정규화한다."""
    if provider == "data.go.kr-standard":
        return "standard"
    if provider in {"python-datagokr-api", "python-mcst-api", "python-mois-api"}:
        return "filedata"
    if provider == "kor-travel-concierge-youtube":
        return "internal"
    return "openapi"


def _preflight_or_raise(label: str, probe_sql: str, remedy: str) -> None:
    quoted_label = label.replace("'", "''")
    quoted_remedy = remedy.replace("'", "''")
    op.execute(
        f"""
        DO $preflight$
        DECLARE
            total bigint;
        BEGIN
            SELECT count(*) INTO total FROM ({probe_sql}) AS probe;
            IF total <> 0 THEN
                RAISE EXCEPTION 'T-VN-33 preflight: % (% row(s))',
                    '{quoted_label}', total
                    USING HINT = '{quoted_remedy}';
            END IF;
        END
        $preflight$;
        """
    )


_LEGACY_PAIRS_SQL: Final[str] = """
    SELECT provider, dataset_key FROM provider_sync.source_entities
    UNION SELECT provider, dataset_key FROM provider_sync.source_records
    UNION SELECT provider, dataset_key FROM provider_sync.provider_sync_state
        WHERE provider IS NOT NULL OR dataset_key IS NOT NULL
    UNION SELECT provider, dataset_key FROM provider_sync.notice_lifecycle_scopes
    UNION SELECT provider, dataset_key FROM feature.curated_sources
    UNION SELECT provider, dataset_key FROM ops.import_jobs
        WHERE provider IS NOT NULL OR dataset_key IS NOT NULL
    UNION SELECT provider, dataset_key FROM ops.import_job_events
        WHERE provider IS NOT NULL OR dataset_key IS NOT NULL
    UNION SELECT provider, dataset_key FROM ops.offline_uploads
    UNION SELECT provider, dataset_key FROM ops.provider_refresh_policies
    UNION SELECT provider, dataset_key FROM ops.integrity_observation_scopes
    UNION SELECT provider, dataset_key FROM ops.integrity_observation_runs
    UNION SELECT provider, dataset_key FROM ops.data_integrity_violations
        WHERE provider IS NOT NULL OR dataset_key IS NOT NULL
    UNION SELECT provider, dataset_key FROM ops.poi_cache_target_feature_links
        WHERE provider IS NOT NULL OR dataset_key IS NOT NULL
    UNION SELECT provider, dataset_key FROM ops.managed_files
        WHERE provider IS NOT NULL AND dataset_key IS NOT NULL
    UNION SELECT source_provider, source_dataset_key FROM ops.enrichment_review_queue
"""


def _create_provider_dataset_schema() -> None:
    _execute_sql_script(
        """
        CREATE FUNCTION provider_sync.is_valid_provider_dataset_capabilities(value jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        SET search_path = pg_catalog
        AS $$
        DECLARE
            produced text;
        BEGIN
            IF jsonb_typeof(value) <> 'object'
               OR NOT (value ?& ARRAY['schema_version', 'produces', 'extensions'])
               OR (value - ARRAY['schema_version', 'produces', 'extensions']) <> '{}'::jsonb
               OR jsonb_typeof(value -> 'schema_version') IS DISTINCT FROM 'number'
               OR value -> 'schema_version' <> '1'::jsonb
               OR jsonb_typeof(value -> 'produces') IS DISTINCT FROM 'array'
               OR jsonb_typeof(value -> 'extensions') IS DISTINCT FROM 'object'
            THEN
                RETURN false;
            END IF;
            FOR produced IN SELECT jsonb_array_elements_text(value -> 'produces') LOOP
                IF produced NOT IN (
                    'place', 'event', 'notice', 'price', 'weather', 'route', 'area', 'enrichment'
                ) THEN
                    RETURN false;
                END IF;
            END LOOP;
            IF EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(value -> 'produces') AS item(value)
                GROUP BY item.value HAVING count(*) > 1
            ) THEN
                RETURN false;
            END IF;
            RETURN true;
        END;
        $$;

        CREATE FUNCTION provider_sync.is_valid_provider_dataset_sync_scope(value text)
        RETURNS boolean
        LANGUAGE sql
        IMMUTABLE
        SET search_path = pg_catalog
        AS $$
            SELECT value IN ('dataset_wide', 'target_grids')
                OR value ~ '^external_system:[^[:space:]][^[:space:]]{0,111}$'
        $$;

        CREATE TABLE provider_sync.provider_datasets (
            provider_dataset_id bigint GENERATED ALWAYS AS IDENTITY,
            provider text NOT NULL,
            dataset_key text NOT NULL,
            display_name text NOT NULL,
            source_kind text NOT NULL,
            is_active boolean NOT NULL DEFAULT true,
            capabilities jsonb NOT NULL DEFAULT
                '{"schema_version" : 1,"produces":[],"extensions":{}}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_provider_datasets PRIMARY KEY (provider_dataset_id),
            CONSTRAINT uq_provider_datasets_identity UNIQUE (provider, dataset_key),
            CONSTRAINT ck_provider_datasets_provider_canonical CHECK (
                provider <> '' AND provider = btrim(provider)
                AND provider = normalize(provider, NFC) AND length(provider) <= 112
            ),
            CONSTRAINT ck_provider_datasets_dataset_key_canonical CHECK (
                dataset_key <> '' AND dataset_key = btrim(dataset_key)
                AND dataset_key = normalize(dataset_key, NFC) AND length(dataset_key) <= 112
            ),
            CONSTRAINT ck_provider_datasets_display_name_canonical CHECK (
                display_name <> '' AND display_name = btrim(display_name)
                AND display_name = normalize(display_name, NFC) AND length(display_name) <= 256
            ),
            CONSTRAINT ck_provider_datasets_source_kind CHECK (
                source_kind IN ('openapi', 'filedata', 'manual', 'system', 'standard', 'internal')
            ),
            CONSTRAINT ck_provider_datasets_capabilities CHECK (
                provider_sync.is_valid_provider_dataset_capabilities(capabilities)
            )
        );

        CREATE TABLE provider_sync.provider_dataset_operations (
            provider_dataset_id bigint NOT NULL,
            operation_key text NOT NULL,
            operation_kind text NOT NULL,
            is_enabled boolean NOT NULL DEFAULT true,
            config jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_provider_dataset_operations
                PRIMARY KEY (provider_dataset_id, operation_key),
            CONSTRAINT fk_provider_dataset_operations_dataset FOREIGN KEY (provider_dataset_id)
                REFERENCES provider_sync.provider_datasets (provider_dataset_id),
            CONSTRAINT ck_provider_dataset_operations_key_canonical CHECK (
                operation_key <> '' AND operation_key = btrim(operation_key)
                AND operation_key = normalize(operation_key, NFC) AND length(operation_key) <= 128
            ),
            CONSTRAINT ck_provider_dataset_operations_kind CHECK (
                operation_kind IN ('feature_load', 'refresh', 'preview')
            ),
            CONSTRAINT uq_provider_dataset_operations_kind UNIQUE (
                provider_dataset_id, operation_key, operation_kind
            ),
            CONSTRAINT ck_provider_dataset_operations_config CHECK (jsonb_typeof(config) = 'object')
        );

        CREATE TABLE provider_sync.provider_dataset_operation_scopes (
            provider_dataset_id bigint NOT NULL,
            sync_scope text NOT NULL,
            operation_key text NOT NULL,
            operation_kind text NOT NULL DEFAULT 'refresh',
            -- 중간 단계에서는 pair PK를 쓴다. 0090의 membership FK가 아직
            -- operation_key 열을 갖지 않기 때문이다. 0091이 triple로 승격한다.
            CONSTRAINT pk_provider_dataset_operation_scopes PRIMARY KEY (
                provider_dataset_id, sync_scope
            ),
            CONSTRAINT fk_provider_dataset_operation_scopes_operation FOREIGN KEY (
                provider_dataset_id, operation_key, operation_kind
            ) REFERENCES provider_sync.provider_dataset_operations (
                provider_dataset_id, operation_key, operation_kind
            ) ON DELETE RESTRICT,
            CONSTRAINT ck_provider_dataset_operation_scopes_refresh_only CHECK (
                operation_kind = 'refresh'
            ),
            CONSTRAINT ck_provider_dataset_operation_scopes_syntax CHECK (
                provider_sync.is_valid_provider_dataset_sync_scope(sync_scope)
            )
        );
        """
    )


def _seed_provider_datasets() -> None:
    connection = op.get_bind()
    insert_dataset = text(
        """
        INSERT INTO provider_sync.provider_datasets (
            provider, dataset_key, display_name, source_kind, is_active, capabilities
        ) VALUES (
            :provider, :dataset_key, :display_name, :source_kind, :is_active,
            CAST(:capabilities AS jsonb)
        ) ON CONFLICT (provider, dataset_key) DO NOTHING
        """
    )
    insert_operation = text(
        """
        INSERT INTO provider_sync.provider_dataset_operations (
            provider_dataset_id, operation_key, operation_kind, is_enabled, config
        )
        SELECT provider_dataset_id, :operation_key, :operation_kind, true,
            CAST(:config AS jsonb)
        FROM provider_sync.provider_datasets
        WHERE provider = :provider AND dataset_key = :dataset_key
        """
    )
    insert_scope = text(
        """
        INSERT INTO provider_sync.provider_dataset_operation_scopes (
            provider_dataset_id, sync_scope, operation_key, operation_kind
        )
        SELECT provider_dataset_id, :sync_scope, :operation_key, 'refresh'
        FROM provider_sync.provider_datasets
        WHERE provider = :provider AND dataset_key = :dataset_key
        """
    )
    for provider, dataset_key, display_name, produced, scope, job_name in _DATASET_SEED:
        connection.execute(
            insert_dataset,
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "display_name": display_name,
                "source_kind": _source_kind(provider),
                "is_active": job_name is not None
                or (provider, dataset_key) in _FIXTURE_PREVIEW_DATASETS
                or (provider, dataset_key) in _WRITE_TARGET_DATASETS,
                "capabilities": json.dumps(
                    {"schema_version": 1, "produces": [produced], "extensions": {}}
                ),
            },
        )
        if job_name is not None:
            connection.execute(
                insert_operation,
                {
                    "provider": provider,
                    "dataset_key": dataset_key,
                    "operation_key": job_name,
                    "operation_kind": "refresh",
                    "config": "{}",
                },
            )
            # dataset-wide is universally available to a refreshable dataset.
            # KMA grid feeds have an additional explicit targeted scope; no
            # scope is inferred at runtime from a request payload.
            connection.execute(
                insert_scope,
                {
                    "provider": provider,
                    "dataset_key": dataset_key,
                    "sync_scope": "dataset_wide",
                    "operation_key": job_name,
                },
            )
            if scope == "target_grids":
                connection.execute(
                    insert_scope,
                    {
                        "provider": provider,
                        "dataset_key": dataset_key,
                        "sync_scope": "target_grids",
                        "operation_key": job_name,
                    },
                )
        if (provider, dataset_key) in _FIXTURE_PREVIEW_DATASETS:
            connection.execute(
                insert_operation,
                {
                    "provider": provider,
                    "dataset_key": dataset_key,
                    "operation_key": f"{job_name or 'fixture'}.preview",
                    "operation_kind": "preview",
                    "config": '{"handler":"fixture"}',
                },
            )

    # 코드 catalog 밖의 pair를 데이터에서 주워 담는다. handler 등록은 아니지만
    # **소유 행이 있으면 active**여야 한다 — inactive는 그 행에 대한 모든 normal
    # write를 영구히 거부하고(`assert_active_provider_dataset`), dataset identity는
    # immutable이라 되돌리려면 새 migration이 필요하다.
    #
    # 실측으로 잡힌 것: 현재 시즌 curation source 11건(등대 스탬프투어 6, 한국관광
    # 100선 2, 수목원, 국가유산 방문 캠페인, 특화거리)이 이 경로로 들어오는데
    # handler가 없어 종전에는 전부 inactive였다. `_preflight_write_targets_are_active`
    # 가 이제 그 상태를 fail-close로 잡는다.
    op.execute(
        f"""
        INSERT INTO provider_sync.provider_datasets (
            provider, dataset_key, display_name, source_kind, is_active, capabilities
        )
        SELECT
            provider,
            dataset_key,
            provider || ' / ' || dataset_key,
            'system',
            true,
            '{{"schema_version" : 1,"produces":[],"extensions":{{}}}}'::jsonb
        FROM ({_LEGACY_PAIRS_SQL}) AS legacy_pair
        WHERE provider IS NOT NULL AND dataset_key IS NOT NULL
        ON CONFLICT (provider, dataset_key) DO NOTHING
        """
    )


def _preflight_legacy_rows() -> None:
    _preflight_or_raise(
        "provider/dataset pair is partial or non-canonical",
        f"""
        SELECT provider, dataset_key
        FROM ({_LEGACY_PAIRS_SQL}) AS pair
        WHERE provider IS NULL OR dataset_key IS NULL
           OR provider = '' OR dataset_key = ''
           OR provider <> btrim(provider) OR dataset_key <> btrim(dataset_key)
           OR provider <> normalize(provider, NFC)
           OR dataset_key <> normalize(dataset_key, NFC)
           OR length(provider) > 112 OR length(dataset_key) > 112
        """,
        "Repair the legacy pair, or rebuild the development database from the final ETL.",
    )


def _expand_lineage_and_ownership_columns() -> None:
    _execute_sql_script(
        """
        ALTER TABLE provider_sync.source_entities
            ADD COLUMN provider_dataset_id bigint;
        UPDATE provider_sync.source_entities AS entity
        SET provider_dataset_id = dataset.provider_dataset_id
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = entity.provider
          AND dataset.dataset_key = entity.dataset_key;
        ALTER TABLE provider_sync.source_entities
            ALTER COLUMN provider_dataset_id SET NOT NULL;

        CREATE TABLE provider_sync.source_entity_heads (
            source_entity_key text NOT NULL,
            current_source_record_key text NOT NULL,
            observed_at timestamptz NOT NULL,
            expires_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_source_entity_heads PRIMARY KEY (source_entity_key),
            CONSTRAINT fk_source_entity_heads_entity FOREIGN KEY (source_entity_key)
                REFERENCES provider_sync.source_entities (source_entity_key) ON DELETE CASCADE,
            CONSTRAINT fk_source_entity_heads_record FOREIGN KEY (
                source_entity_key, current_source_record_key
            ) REFERENCES provider_sync.source_records (source_entity_key, source_record_key)
                ON DELETE RESTRICT
        );
        INSERT INTO provider_sync.source_entity_heads (
            source_entity_key, current_source_record_key, observed_at, expires_at
        )
        WITH ranked AS (
            SELECT DISTINCT ON (record.source_entity_key)
                record.source_entity_key,
                record.source_record_key,
                record.last_seen_at,
                record.expires_at
            FROM provider_sync.source_records AS record
            ORDER BY
                record.source_entity_key,
                record.last_seen_at DESC,
                record.fetched_at DESC,
                record.imported_at DESC,
                record.source_record_key DESC
        )
        SELECT
            entity.source_entity_key,
            COALESCE(current_record.source_record_key, ranked.source_record_key),
            COALESCE(current_record.last_seen_at, ranked.last_seen_at),
            COALESCE(current_record.expires_at, ranked.expires_at)
        FROM provider_sync.source_entities AS entity
        JOIN ranked ON ranked.source_entity_key = entity.source_entity_key
        LEFT JOIN provider_sync.source_records AS current_record
          ON current_record.source_entity_key = entity.source_entity_key
         AND current_record.source_record_key = entity.current_source_record_key;

        ALTER TABLE provider_sync.provider_sync_state
            ADD COLUMN provider_dataset_id bigint;
        UPDATE provider_sync.provider_sync_state AS state
        SET provider_dataset_id = dataset.provider_dataset_id,
            sync_scope = CASE
                WHEN state.sync_scope = 'default' THEN 'dataset_wide'
                ELSE state.sync_scope
            END
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = state.provider
          AND dataset.dataset_key = state.dataset_key;

        ALTER TABLE provider_sync.notice_lifecycle_scopes
            ADD COLUMN notice_lifecycle_scope_id bigint GENERATED ALWAYS AS IDENTITY,
            ADD COLUMN provider_dataset_id bigint;
        UPDATE provider_sync.notice_lifecycle_scopes AS scope
        SET provider_dataset_id = dataset.provider_dataset_id
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = scope.provider
          AND dataset.dataset_key = scope.dataset_key;

        ALTER TABLE feature.curated_sources
            ADD COLUMN provider_dataset_id bigint;
        UPDATE feature.curated_sources AS source
        SET provider_dataset_id = dataset.provider_dataset_id
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = source.provider
          AND dataset.dataset_key = source.dataset_key;

        -- offline upload도 실행 membership이므로 triple을 갖는다(ADR-088 §결정 2).
        -- 기존 행에는 operation이 없으므로 그 dataset+scope의 refresh operation에서
        -- 유도한다. scope PK가 triple이라 후보가 여럿일 수 있는데, 과거 upload는
        -- pair로만 식별됐으므로 결정적으로 고르려면 하나여야 한다 —
        -- 아래 preflight가 그 조건을 검사한다.
        ALTER TABLE ops.offline_uploads
            ADD COLUMN provider_dataset_id bigint,
            ADD COLUMN operation_key text;
        UPDATE ops.offline_uploads AS upload
        SET provider_dataset_id = dataset.provider_dataset_id,
            sync_scope = CASE
                WHEN upload.sync_scope = 'default' THEN 'dataset_wide'
                ELSE upload.sync_scope
            END
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = upload.provider
          AND dataset.dataset_key = upload.dataset_key;
        UPDATE ops.offline_uploads AS upload
        SET operation_key = scope.operation_key
        FROM provider_sync.provider_dataset_operation_scopes AS scope
        WHERE scope.provider_dataset_id = upload.provider_dataset_id
          AND scope.sync_scope = upload.sync_scope;

        ALTER TABLE ops.provider_refresh_policies
            ADD COLUMN provider_dataset_id bigint;
        UPDATE ops.provider_refresh_policies AS policy
        SET provider_dataset_id = dataset.provider_dataset_id
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = policy.provider
          AND dataset.dataset_key = policy.dataset_key;

        ALTER TABLE ops.integrity_observation_scopes
            ADD COLUMN integrity_observation_scope_id bigint GENERATED ALWAYS AS IDENTITY,
            ADD COLUMN provider_dataset_id bigint;
        UPDATE ops.integrity_observation_scopes AS scope
        SET provider_dataset_id = dataset.provider_dataset_id
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = scope.provider
          AND dataset.dataset_key = scope.dataset_key;

        ALTER TABLE ops.integrity_observation_runs
            ADD COLUMN integrity_observation_scope_id bigint;
        UPDATE ops.integrity_observation_runs AS run
        SET integrity_observation_scope_id = scope.integrity_observation_scope_id
        FROM ops.integrity_observation_scopes AS scope
        WHERE scope.provider = run.provider
          AND scope.dataset_key = run.dataset_key;

        ALTER TABLE ops.data_integrity_violations
            ADD COLUMN provider_dataset_id bigint;
        UPDATE ops.data_integrity_violations AS violation
        SET provider_dataset_id = dataset.provider_dataset_id
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = violation.provider
          AND dataset.dataset_key = violation.dataset_key;

        ALTER TABLE ops.poi_cache_target_feature_links
            ADD COLUMN provider_dataset_id bigint;
        UPDATE ops.poi_cache_target_feature_links AS link
        SET provider_dataset_id = dataset.provider_dataset_id
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = link.provider
          AND dataset.dataset_key = link.dataset_key;

        ALTER TABLE ops.enrichment_review_queue
            ADD COLUMN source_entity_key text,
            ADD COLUMN source_record_key text;
        UPDATE ops.enrichment_review_queue AS review
        SET source_entity_key = entity.source_entity_key
        FROM provider_sync.source_entities AS entity
        WHERE entity.provider = review.source_provider
          AND entity.dataset_key = review.source_dataset_key
          AND entity.source_entity_id = review.source_entity_id;
        UPDATE ops.enrichment_review_queue AS review
        SET source_record_key = head.current_source_record_key
        FROM provider_sync.source_entity_heads AS head
        WHERE head.source_entity_key = review.source_entity_key;

        ALTER TABLE ops.managed_files
            ADD COLUMN provider_dataset_id bigint,
            ADD COLUMN provider_name text;
        UPDATE ops.managed_files AS file
        SET provider_dataset_id = dataset.provider_dataset_id
        FROM provider_sync.provider_datasets AS dataset
        WHERE dataset.provider = file.provider
          AND dataset.dataset_key = file.dataset_key;
        UPDATE ops.managed_files
        SET provider_name = provider
        WHERE provider_dataset_id IS NULL AND provider IS NOT NULL;
        """
    )


def _preflight_offline_upload_operation_is_unambiguous() -> None:
    """기존 offline upload가 정확히 하나의 refresh operation으로 해석되는지 본다.

    upload는 종전에 (provider, dataset_key, sync_scope) pair로만 식별됐다. triple로
    올리면서 operation을 유도해야 하는데, 같은 scope에 refresh operation이 둘 이상
    등록돼 있으면 어느 것을 골라도 임의 선택이다 — 조용히 고르지 않고 중단한다.
    """
    _preflight_or_raise(
        "offline upload scope resolves to more than one refresh operation",
        """
        SELECT upload.upload_id
        FROM ops.offline_uploads AS upload
        JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = upload.provider_dataset_id
         AND scope.sync_scope = upload.sync_scope
        GROUP BY upload.upload_id
        HAVING count(*) <> 1
        """,
        "Record the operation explicitly on the upload before migrating.",
    )


def _preflight_scope_memberships() -> None:
    """정규 scope가 없는 legacy operational row를 조용히 고아로 만들지 않는다."""
    _preflight_or_raise(
        "legacy sync state has no enabled canonical refresh scope",
        """
        SELECT state.provider, state.dataset_key, state.sync_scope
        FROM provider_sync.provider_sync_state AS state
        LEFT JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider = state.provider
         AND dataset.dataset_key = state.dataset_key
        LEFT JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = dataset.provider_dataset_id
         AND scope.sync_scope = CASE
             WHEN state.sync_scope = 'default' THEN 'dataset_wide' ELSE state.sync_scope
         END
        WHERE scope.provider_dataset_id IS NULL
        """,
        "Do not infer an operation for historical state; reload it through a seeded handler.",
    )
    _preflight_or_raise(
        "legacy job pair has no enabled canonical refresh scope",
        """
        SELECT job.job_id
        FROM ops.import_jobs AS job
        LEFT JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider = job.provider AND dataset.dataset_key = job.dataset_key
        LEFT JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = dataset.provider_dataset_id
         AND scope.sync_scope = CASE
             WHEN job.sync_scope = 'default' OR job.sync_scope IS NULL THEN 'dataset_wide'
             ELSE job.sync_scope
         END
        WHERE job.provider IS NOT NULL AND job.dataset_key IS NOT NULL
          AND scope.provider_dataset_id IS NULL
        """,
        "Historical jobs cannot manufacture an operation; rebuild them from a seeded handler.",
    )
    _preflight_or_raise(
        "legacy feature update request has no linked exact-pair job",
        """
        SELECT request.request_id
        FROM ops.feature_update_requests AS request
        JOIN ops.import_jobs AS job ON job.job_id = request.job_id
        WHERE job.provider IS NULL OR job.dataset_key IS NULL
        """,
        "Recreate the request after the dataset resolver can capture canonical members.",
    )


def _expand_job_and_request_membership() -> None:
    _execute_sql_script(
        """
        ALTER TABLE ops.import_jobs
            ADD COLUMN dataset_membership_mode text NOT NULL DEFAULT 'root';
        CREATE TABLE ops.import_job_datasets (
            import_job_dataset_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
            job_id uuid NOT NULL,
            provider_dataset_id bigint NOT NULL,
            sync_scope text NOT NULL,
            operation_key text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_import_job_datasets PRIMARY KEY (import_job_dataset_id),
            CONSTRAINT uq_import_job_datasets_exact_identity UNIQUE (
                job_id, provider_dataset_id, sync_scope, operation_key
            ),
            CONSTRAINT uq_import_job_datasets_job_member UNIQUE (
                job_id, import_job_dataset_id
            )
        );
        UPDATE ops.import_jobs
        SET dataset_membership_mode = CASE
            WHEN provider IS NULL AND dataset_key IS NULL THEN 'root'
            ELSE 'single'
        END;
        INSERT INTO ops.import_job_datasets (
            job_id, provider_dataset_id, sync_scope
        )
        SELECT
            job.job_id,
            dataset.provider_dataset_id,
            CASE
                WHEN job.sync_scope = 'default' OR job.sync_scope IS NULL THEN 'dataset_wide'
                ELSE job.sync_scope
            END
        FROM ops.import_jobs AS job
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider = job.provider AND dataset.dataset_key = job.dataset_key
        WHERE job.provider IS NOT NULL AND job.dataset_key IS NOT NULL;

        ALTER TABLE ops.import_job_events
            ADD COLUMN import_job_dataset_id uuid;
        UPDATE ops.import_job_events AS event
        SET import_job_dataset_id = member.import_job_dataset_id,
            sync_scope = CASE
                WHEN event.sync_scope = 'default' THEN 'dataset_wide'
                ELSE event.sync_scope
            END
        FROM provider_sync.provider_datasets AS dataset
        JOIN ops.import_job_datasets AS member
          ON member.provider_dataset_id = dataset.provider_dataset_id
        WHERE member.job_id = event.job_id
          AND member.sync_scope = CASE
              WHEN event.sync_scope = 'default' OR event.sync_scope IS NULL THEN 'dataset_wide'
              ELSE event.sync_scope
          END
          AND dataset.provider = event.provider
          AND dataset.dataset_key = event.dataset_key;

        ALTER TABLE ops.feature_update_requests
            ADD COLUMN dataset_membership_mode text NOT NULL DEFAULT 'single';
        CREATE TABLE ops.feature_update_request_datasets (
            feature_update_request_dataset_id uuid NOT NULL DEFAULT x_extension.gen_random_uuid(),
            request_id uuid NOT NULL,
            provider_dataset_id bigint NOT NULL,
            sync_scope text NOT NULL,
            CONSTRAINT pk_feature_update_request_datasets
                PRIMARY KEY (feature_update_request_dataset_id),
            CONSTRAINT uq_feature_update_request_datasets_identity UNIQUE (
                request_id, provider_dataset_id, sync_scope
            )
        );
        INSERT INTO ops.feature_update_request_datasets (
            request_id, provider_dataset_id, sync_scope
        )
        SELECT request.request_id, member.provider_dataset_id, member.sync_scope
        FROM ops.feature_update_requests AS request
        JOIN ops.import_job_datasets AS member ON member.job_id = request.job_id;
        UPDATE ops.feature_update_requests AS request
        SET dataset_membership_mode = CASE
            WHEN count_value.member_count = 1 THEN 'single'
            ELSE 'multiple'
        END
        FROM (
            SELECT request_id, count(*)::bigint AS member_count
            FROM ops.feature_update_request_datasets
            GROUP BY request_id
        ) AS count_value
        WHERE count_value.request_id = request.request_id;
        """
    )


def _preflight_write_targets_are_active() -> None:
    """실제로 lineage row를 가진 pair가 inactive로 seed되면 **중단**한다.

    `is_active`는 "쓰기를 받을 수 있다"를 뜻하고, cutover 뒤 inactive dataset에
    대한 INSERT/UPDATE는 `ck_provider_dataset_active_write`로 거부된다. 그런데
    seed의 활성 판정은 operation handler 유무에서 출발하고, **operation의
    dataset_key와 source record의 dataset_key는 같지 않다**(KMA 예보 operation이
    격자 dataset에 record를 남긴다). 그래서 handler가 없는 write target이 조용히
    inactive로 들어가 다음 적재부터 전멸시킬 수 있다 — 실제로 그 상태로 있었다.

    `_WRITE_TARGET_DATASETS`가 알려진 것을 덮지만, 새 provider가 생기면 같은 일이
    반복된다. 그래서 알고 있는 목록이 아니라 **DB에 실재하는 데이터**를 기준으로
    검사한다. 여기서 걸리면 그 pair를 seed에 넣고 write target으로 표시할 것.
    """
    _preflight_or_raise(
        "dataset owns live rows but would be seeded inactive",
        f"""
        SELECT dataset.provider, dataset.dataset_key
        FROM provider_sync.provider_datasets AS dataset
        WHERE NOT dataset.is_active
          AND (dataset.provider, dataset.dataset_key) IN (
              SELECT provider, dataset_key FROM ({_LEGACY_PAIRS_SQL}) AS owned
              WHERE provider IS NOT NULL AND dataset_key IS NOT NULL
          )
        """,
        "Add the pair to _DATASET_SEED (and _WRITE_TARGET_DATASETS if it has no "
        "operation of its own) in this revision.",
    )


def _normalize_payload_hashes() -> None:
    """외부 시스템이 붙인 알고리즘 접두를 벗겨 canonical hex로 만든다.

    `raw_payload_hash`는 provider가 준 값을 그대로 저장한다
    (`providers/kor_travel_concierge.py`의 `source_record.raw_payload_hash`).
    concierge는 `sha256:<hex>` 형태로 보내므로 prod에 그 형태가 실재한다
    (실측 1,481행, 전부 `kor-travel-concierge-youtube/youtube_place_candidates`).
    0090이 `ck_source_records_payload_hash_canonical`(`^[0-9a-f]{1,64}$`)을
    validate하면 그 행들에서 **중단된다** — 실제로 그렇게 막혔다.

    `source_record_key`는 저장 후 opaque key이므로(단일 PR 설계 §2) 해시만 고쳐도
    키는 그대로다. 접두 제거 후 비정본 0건·`uq_source_records` 충돌 0건을 prod
    복원본에서 확인했고, 아래 preflight가 그 두 조건을 매 실행마다 다시 본다.
    """
    _preflight_or_raise(
        "payload hash is not canonical even after stripping the algorithm prefix",
        """
        SELECT source_record_key
        FROM provider_sync.source_records
        WHERE NOT (
            lower(regexp_replace(raw_payload_hash, '^(sha256|sha1|md5|sha512):', ''))
            ~ '^[0-9a-f]{1,64}$'
        )
        """,
        "Repair the payload hash at the provider, or rebuild from the final ETL.",
    )
    _preflight_or_raise(
        "stripping the payload hash prefix would collide within uq_source_records",
        """
        SELECT provider, dataset_key, source_entity_type, source_entity_id
        FROM provider_sync.source_records
        GROUP BY provider, dataset_key, source_entity_type, source_entity_id,
                 lower(regexp_replace(raw_payload_hash, '^(sha256|sha1|md5|sha512):', ''))
        HAVING count(*) > 1
        """,
        "Deduplicate the conflicting source records before rerunning the migration.",
    )
    op.execute(
        """
        UPDATE provider_sync.source_records
        SET raw_payload_hash =
            lower(regexp_replace(raw_payload_hash, '^(sha256|sha1|md5|sha512):', ''))
        WHERE raw_payload_hash <>
            lower(regexp_replace(raw_payload_hash, '^(sha256|sha1|md5|sha512):', ''))
        """
    )


def upgrade() -> None:
    _preflight_legacy_rows()
    _create_provider_dataset_schema()
    _seed_provider_datasets()
    _preflight_write_targets_are_active()
    _normalize_payload_hashes()
    _expand_lineage_and_ownership_columns()
    _preflight_offline_upload_operation_is_unambiguous()
    _preflight_scope_memberships()
    _expand_job_and_request_membership()


def downgrade() -> None:
    raise RuntimeError("T-VN-33 is forward-only: rebuild the development database from final ETL.")
