"""T-212d 성능 baseline EXPLAIN 통합 테스트.

로컬 live DB를 먼저 확인했지만 현재 Codex Postgres에는 offline smoke 1건만 있어
운영 분포를 측정하기엔 부족했다. 이 테스트는 CI 재현성을 위해 대량 seed를 만들되,
provider/dataset/지역/상태/이슈 분포와 실제 한국 지명 기반 검색어를 섞어 hot path가
대량 데이터에서도 인덱스 친화적인지 검증한다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.infra import (
    admin_feature_repo,
    consistency,
    dedup_refresh_repo,
    ops_repo,
)
from kortravelmap.infra.admin_feature_repo import (  # noqa: PLC2701 - EXPLAIN 대상
    _DEDUP_REVIEW_SQL,
    _ENRICHMENT_REVIEW_SCALAR_STATUS_PROVIDER_SQL,
    _ENRICHMENT_REVIEW_STATUS_PROVIDER_SQL,
    _ENRICHMENT_REVIEW_STATUS_SQL,
)
from kortravelmap.infra.feature_repo import (  # noqa: PLC2701 - EXPLAIN 대상
    _CLUSTER_BBOX_SQL_BY_UNIT,
    _FEATURE_SEARCH_BY_SCORE_SQL,
    _FEATURES_IN_BBOX_SQL,
    _NEARBY_COORD_DISTANCE_SQL,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _seed_live_like_perf_data(session: AsyncSession, *, n: int = 3200) -> None:
    """서울/부산/제주 주변의 provider-like feature/source/ops row를 대량 seed."""
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                address, urls, raw_refs,
                lifecycle_state, publication_state, quality_state,
                legal_dong_code, sido_code, sigungu_code,
                created_at, updated_at
            )
            SELECT
                'perf:f:' || lpad(g::text, 6, '0') AS feature_id,
                CASE
                  WHEN g % 19 = 0 THEN 'event'
                  WHEN g % 23 = 0 THEN 'weather'
                  ELSE 'place'
                END AS kind,
                CASE
                  WHEN g % 37 = 0 THEN '광화문 실측 카페 ' || g::text
                  WHEN g % 41 = 0 THEN '해운대 축제 라이브 ' || g::text
                  WHEN g % 43 = 0 THEN '제주 오름 휴양림 ' || g::text
                  ELSE '운영 유사 장소 ' || g::text
                END AS name,
                CASE
                  WHEN g % 19 = 0 THEN '02010000'
                  WHEN g % 23 = 0 THEN '99000000'
                  WHEN g % 7 = 0 THEN '06020000'
                  ELSE '01070300'
                END AS category,
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(
                        CASE
                          WHEN g % 11 = 0 THEN 129.10 + ((g % 50)::float * 0.001)
                          WHEN g % 13 = 0 THEN 126.50 + ((g % 40)::float * 0.002)
                          ELSE 126.92 + ((g % 120)::float * 0.0015)
                        END,
                        CASE
                          WHEN g % 11 = 0 THEN 35.15 + ((g % 50)::float * 0.001)
                          WHEN g % 13 = 0 THEN 33.38 + ((g % 40)::float * 0.002)
                          ELSE 37.48 + ((g % 120)::float * 0.0010)
                        END
                    ),
                    4326
                ) AS coord,
                jsonb_build_object(
                    'road', '서울특별시 종로구 세종대로 ' || (g % 200)::text,
                    'legal', '서울특별시 종로구 세종로'
                ) AS address,
                '{}'::jsonb AS urls,
                '[]'::jsonb AS raw_refs,
                -- T-VN-34(0097): 단일 ``status``가 사라지고 3축이 정본이다. 이
                -- seed가 지키려던 것은 "29행마다 1행은 공개 표면 밖"이라는 **분포**
                -- 이지 문자열 'inactive'가 아니다. 0095 backfill이
                -- status='inactive' → lifecycle='retired' + publication='suppressed'
                -- 로 옮겼고 ``ck_features_state_tuple``이 retired인 행에
                -- publication='suppressed'를 강제하므로 두 축을 함께 뒤집어야
                -- 같은 분포가 재현된다. legacy seed에 status='broken'이 없었으니
                -- quality는 전 행 'valid'이고, 공개 partial index
                -- (lifecycle='active' AND publication='published' AND
                --  quality='valid')가 걸러내는 비율도 종전과 같다.
                CASE WHEN g % 29 = 0 THEN 'retired' ELSE 'active' END
                    AS lifecycle_state,
                CASE WHEN g % 29 = 0 THEN 'suppressed' ELSE 'published' END
                    AS publication_state,
                'valid' AS quality_state,
                CASE WHEN g % 11 = 0 THEN '2611010100'
                     WHEN g % 13 = 0 THEN '5011010100'
                     ELSE '1111010100' END AS legal_dong_code,
                CASE WHEN g % 11 = 0 THEN '26'
                     WHEN g % 13 = 0 THEN '50'
                     ELSE '11' END AS sido_code,
                CASE WHEN g % 11 = 0 THEN '26110'
                     WHEN g % 13 = 0 THEN '50110'
                     ELSE '11110' END AS sigungu_code,
                now() - (g::text || ' minutes')::interval AS created_at,
                now() - ((:n - g)::text || ' seconds')::interval AS updated_at
            FROM generate_series(1, :n) AS g
            """
        ),
        {"n": n},
    )
    # T-VN-35(ADR-086): kind별 값의 정본은 subtype이다. 종전 seed가 core
    # ``detail``에 넣던 place_kind/business_hours가 typed 컬럼으로 간다 —
    # ``idx_feature_places_opening_hours``가 종전 ``idx_features_opening_hours_keyset``
    # 자리를 대신하므로 같은 17행 주기로 business_hours를 채운다.
    await session.execute(
        text(
            """
            INSERT INTO feature.feature_places (
                feature_id, feature_uuid, kind, place_kind, business_hours
            )
            SELECT
                f.feature_id,
                f.feature_uuid,
                f.kind,
                'attraction',
                CASE
                  WHEN right(f.feature_id, 6)::int % 17 = 0 THEN jsonb_build_object(
                    'periods', jsonb_build_array(
                      jsonb_build_object(
                        'open', jsonb_build_object('day', '1', 'time', '0900'),
                        'close', jsonb_build_object('day', '1', 'time', '1800')
                      )
                    )
                  )
                END
            FROM feature.features AS f
            WHERE f.feature_id LIKE 'perf:f:%' AND f.kind = 'place'
            """
        )
    )
    await session.execute(
        text(
            """
            INSERT INTO feature.feature_events (
                feature_id, feature_uuid, kind, event_kind, starts_on, ends_on
            )
            SELECT
                f.feature_id, f.feature_uuid, f.kind, 'festival',
                CURRENT_DATE - 3, CURRENT_DATE + 3
            FROM feature.features AS f
            WHERE f.feature_id LIKE 'perf:f:%' AND f.kind = 'event'
            """
        )
    )
    # T-VN-33: entity/record는 자연키 사본을 갖지 않는다 — dataset 소유는
    # ``provider_dataset_id`` 하나뿐이라 provider 분포는 catalog 행으로 만든다.
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind, is_active,
                capabilities
            )
            SELECT
                pair.provider, pair.dataset_key, pair.provider, 'system', true,
                jsonb_build_object('schema_version', 1, 'produces', '[]'::jsonb,
                                   'extensions', '{}'::jsonb)
            FROM (VALUES
                (0, 'python-mois-api', 'mois_license_features_bulk'),
                (1, 'python-datagokr-api', 'standard_tourist_attractions'),
                (2, 'python-visitkorea-api', 'visitkorea_festival_events'),
                (3, 'python-opinet-api', 'opinet_stations'),
                (4, 'python-krheritage-api', 'krheritage_events')
            ) AS pair(bucket, provider, dataset_key)
            ON CONFLICT (provider, dataset_key)
            DO UPDATE SET display_name = EXCLUDED.display_name
            """
        )
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id,
                source_entity_type, source_entity_id,
                first_seen_at, last_seen_at
            )
            SELECT
                'perf:se:' || lpad(g::text, 6, '0'),
                pd.provider_dataset_id,
                'perf_entity',
                lpad(g::text, 6, '0'),
                now() - (g::text || ' minutes')::interval,
                now() - (g::text || ' seconds')::interval
            FROM generate_series(1, :n) AS g
            JOIN (VALUES
                (0, 'python-mois-api', 'mois_license_features_bulk'),
                (1, 'python-datagokr-api', 'standard_tourist_attractions'),
                (2, 'python-visitkorea-api', 'visitkorea_festival_events'),
                (3, 'python-opinet-api', 'opinet_stations'),
                (4, 'python-krheritage-api', 'krheritage_events')
            ) AS pair(bucket, provider, dataset_key) ON pair.bucket = g % 5
            JOIN provider_sync.provider_datasets AS pd
              ON pd.provider = pair.provider AND pd.dataset_key = pair.dataset_key
            """
        ),
        {"n": n},
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, raw_data, raw_payload_hash,
                fetched_at, imported_at
            )
            SELECT
                'perf:sr:' || lpad(g::text, 6, '0'),
                'perf:se:' || lpad(g::text, 6, '0'),
                jsonb_build_object('row', g),
                -- raw_payload_hash는 소문자 hex여야 한다(자유 문자열 아님).
                md5(g::text),
                now() - (g::text || ' minutes')::interval,
                now() - (g::text || ' seconds')::interval
            FROM generate_series(1, :n) AS g
            """
        ),
        {"n": n},
    )
    # 현재 record 포인터는 entity가 아니라 head가 든다(entity당 head 정확히 1개).
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entity_heads (
                source_entity_key, current_source_record_key, observed_at
            )
            SELECT
                'perf:se:' || lpad(g::text, 6, '0'),
                'perf:sr:' || lpad(g::text, 6, '0'),
                now() - (g::text || ' seconds')::interval
            FROM generate_series(1, :n) AS g
            """
        ),
        {"n": n},
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role,
                match_method, confidence, created_at
            )
            SELECT
                'perf:f:' || lpad(g::text, 6, '0'),
                'perf:se:' || lpad(g::text, 6, '0'),
                'primary',
                'natural_key',
                100,
                now()
            FROM generate_series(1, :n) AS g
            """
        ),
        {"n": n},
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
                kind, payload, status, progress,
                load_batch_id, parent_job_id, created_at, started_at, heartbeat_at
            )
            SELECT
                CASE WHEN g % 3 = 0 THEN 'update_request_perf_fixture'
                     WHEN g % 3 = 1 THEN 'provider_load'
                     ELSE 'consistency_check' END,
                jsonb_build_object('row', g),
                CASE WHEN g % 7 = 0 THEN 'running'
                     WHEN g % 11 = 0 THEN 'failed'
                     ELSE 'queued' END,
                (g % 100),
                CASE WHEN g % 4 = 0
                     THEN 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'::uuid
                     ELSE NULL END,
                NULL,
                now() - (g::text || ' seconds')::interval,
                CASE WHEN g % 7 = 0 THEN now() - interval '1 minute' ELSE NULL END,
                CASE WHEN g % 7 = 0 THEN now() - interval '30 seconds' ELSE NULL END
            FROM generate_series(1, 900) AS g
            """
        )
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.feature_consistency_reports (
                batch_id, started_at, finished_at, severity_max, cases, summary
            )
            SELECT
                x_extension.gen_random_uuid(),
                now() - (g::text || ' seconds')::interval,
                now() - ((g - 1)::text || ' seconds')::interval,
                CASE WHEN g % 4 = 0 THEN 'WARN' ELSE 'OK' END,
                '[]'::jsonb,
                jsonb_build_object('total_violations', g % 3)
            FROM generate_series(1, 600) AS g
            """
        )
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.data_integrity_violations (
                provider_dataset_id, source_record_key, feature_id,
                violation_type, severity, message, payload, status, detected_at
            )
            SELECT
                -- issue의 dataset은 source record의 dataset과 일치해야 한다
                -- (``ck_data_integrity_violations_dataset_source_record``).
                se.provider_dataset_id,
                'perf:sr:' || lpad(g::text, 6, '0'),
                'perf:f:' || lpad(g::text, 6, '0'),
                CASE WHEN g % 3 = 0 THEN 'missing_address'
                     ELSE 'provider_address_mismatch' END,
                CASE WHEN g % 3 = 0 THEN 'warning' ELSE 'error' END,
                CASE WHEN g % 17 = 0 THEN '광화문 주소 불일치' ELSE '주소 검토 필요' END,
                jsonb_build_object('row', g),
                CASE WHEN g % 13 = 0 THEN 'resolved' ELSE 'open' END,
                now() - (g::text || ' seconds')::interval
            FROM generate_series(1, 900) AS g
            JOIN provider_sync.source_entities AS se
              ON se.source_entity_key = 'perf:se:' || lpad(g::text, 6, '0')
            """
        )
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.dedup_review_queue (
                feature_id_a, feature_id_b,
                total_score, name_score, spatial_score, category_score,
                status, created_at
            )
            SELECT
                'perf:f:' || lpad(g::text, 6, '0'),
                'perf:f:' || lpad((g + 1600)::text, 6, '0'),
                70 + (g % 250)::numeric / 10,
                80,
                75,
                90,
                CASE WHEN g % 9 = 0 THEN 'rejected' ELSE 'pending' END,
                now() - (g::text || ' seconds')::interval
            FROM generate_series(1, 500) AS g
            """
        )
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.enrichment_review_queue (
                target_feature_id, source_entity_key, source_record_key,
                source_name, target_name, name_score, status, created_at
            )
            SELECT
                'perf:f:' || lpad(g::text, 6, '0'),
                'perf:se:' || lpad(g::text, 6, '0'),
                'perf:sr:' || lpad(g::text, 6, '0'),
                '축제 원천 ' || g::text,
                '운영 유사 장소 ' || g::text,
                70 + (g % 250)::numeric / 10,
                CASE WHEN g % 8 = 0 THEN 'ignored' ELSE 'pending' END,
                now() - (g::text || ' seconds')::interval
            FROM generate_series(1, 500) AS g
            """
        )
    )
    await session.flush()
    await session.execute(text("ANALYZE"))


async def _seed_geom_only_perf_data(
    session: AsyncSession,
    *,
    n: int = 3200,
) -> None:
    """coord 없이 geometry만 가진 route/area의 대표 planner 분포를 만든다.

    T-VN-35(ADR-086): geometry 정본이 ``feature_routes``/``feature_areas``로
    옮겨졌고 두 subtype의 ``geom``은 NOT NULL이다 — core는 좌표 없는 껍데기만
    갖는다. 인덱스도 core 단일 partial GiST가 아니라 subtype별 GiST 2종이므로
    seed 구조를 그대로 옮기고, 통계는 세 relation 모두에 만든다.
    """
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord,
                lifecycle_state, publication_state, quality_state,
                sido_code, sigungu_code, legal_dong_code, created_at, updated_at
            )
            SELECT
                'perf:geom:' || lpad(g::text, 6, '0'),
                CASE WHEN g % 2 = 0 THEN 'route' ELSE 'area' END,
                'geometry-only feature ' || g::text,
                '02000000',
                NULL,
                -- 종전 status='active'의 3축 등가. 여기서는 값 자체보다 **공개
                -- 표면 소속**이 중요하다: 0096의 subtype GiST가
                -- ``WHERE public_ready``인데 그 플래그를 채우는 trigger가 부모의
                -- 3축을 그대로 읽는다. 세 축이 모두 공개값이라야 route/area 행이
                -- public_ready=true로 들어가고 이 테스트가 겨누는
                -- ``idx_feature_routes_geom_gist``/``idx_feature_areas_geom_gist``
                -- 가 후보를 실제로 담는다.
                'active',
                'published',
                'valid',
                '11',
                '11110',
                '1111010100',
                now(),
                now()
            FROM generate_series(1, :n) AS g
            """
        ),
        {"n": n},
    )
    await session.execute(
        text(
            """
            INSERT INTO feature.feature_routes (
                feature_id, feature_uuid, kind, geom, route_type
            )
            SELECT
                f.feature_id,
                f.feature_uuid,
                f.kind,
                x_extension.ST_Multi(
                    x_extension.ST_SetSRID(
                        x_extension.ST_MakeLine(
                            x_extension.ST_MakePoint(
                                126.0 + ((g % 1000)::float * 0.002),
                                36.0 + ((g % 800)::float * 0.002)
                            ),
                            x_extension.ST_MakePoint(
                                126.0004 + ((g % 1000)::float * 0.002),
                                36.0004 + ((g % 800)::float * 0.002)
                            )
                        ),
                        4326
                    )
                )::x_extension.geometry(MultiLineString, 4326),
                'route'
            FROM feature.features AS f
            JOIN LATERAL (SELECT right(f.feature_id, 6)::int AS g) AS s ON TRUE
            WHERE f.feature_id LIKE 'perf:geom:%' AND f.kind = 'route'
            """
        )
    )
    await session.execute(
        text(
            """
            INSERT INTO feature.feature_areas (
                feature_id, feature_uuid, kind, geom, area_kind
            )
            SELECT
                f.feature_id,
                f.feature_uuid,
                f.kind,
                x_extension.ST_Multi(
                    x_extension.ST_SetSRID(
                        x_extension.ST_MakeEnvelope(
                            126.0 + ((g % 1000)::float * 0.002),
                            36.0 + ((g % 800)::float * 0.002),
                            126.0004 + ((g % 1000)::float * 0.002),
                            36.0004 + ((g % 800)::float * 0.002)
                        ),
                        4326
                    )
                )::x_extension.geometry(MultiPolygon, 4326),
                'area'
            FROM feature.features AS f
            JOIN LATERAL (SELECT right(f.feature_id, 6)::int AS g) AS s ON TRUE
            WHERE f.feature_id LIKE 'perf:geom:%' AND f.kind = 'area'
            """
        )
    )
    await session.flush()
    await session.execute(text("ANALYZE feature.features"))
    await session.execute(text("ANALYZE feature.feature_routes"))
    await session.execute(text("ANALYZE feature.feature_areas"))


async def _explain_json(
    session: AsyncSession,
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    force_index: bool = True,
) -> dict[str, Any]:
    await session.execute(
        text(f"SET LOCAL enable_seqscan = {'off' if force_index else 'on'}")
    )
    result = await session.execute(
        text("EXPLAIN (FORMAT JSON, SETTINGS) " + sql),
        params or {},
    )
    explain = result.scalar_one()[0]
    plan = dict(explain["Plan"])
    plan["_explain_settings"] = explain.get("Settings", [])
    plan["_planner_mode"] = "forced-index" if force_index else "default"
    return plan


def _walk_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_walk_plan(child))
    return nodes


def _index_names(plan: dict[str, Any]) -> set[str]:
    return {
        str(node["Index Name"])
        for node in _walk_plan(plan)
        if node.get("Index Name") is not None
    }


def _relation_names(plan: dict[str, Any]) -> set[str]:
    return {
        str(node["Relation Name"])
        for node in _walk_plan(plan)
        if node.get("Relation Name") is not None
    }


def _format_plan(plan: dict[str, Any]) -> str:
    return json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True)


def _assert_uses_index(plan: dict[str, Any], *expected: str) -> None:
    used = _index_names(plan)
    assert set(expected) & used, (
        f"expected one of {expected}, used={sorted(used)}\n"
        "EXPLAIN (FORMAT JSON, SETTINGS):\n"
        f"{_format_plan(plan)}"
    )


_COORD_SPATIAL_INDEXES = ("idx_features_coord_gist", "idx_features_coord")

# features의 ``feature_id`` 동등 조건이 탈 수 있는 **동치** 접근 경로.
#
# alembic 0083(T-VN-32C)이 복합 FK의 참조 대상으로
# ``uq_features_identity_pair UNIQUE (feature_id, feature_uuid)``를 만들면서 PK와
# 선두 컬럼이 같은 btree가 하나 더 생겼고, ``feature_uuid``를 함께 투영하는
# 질의에서는 planner가 이 covering index를 골라 index-only scan을 한다.
# 선두 컬럼이 같아 selectivity·성능 축은 동일하므로 gate는 둘을 동치로 받는다
# (``tests/integration/perf_gate._FEATURES_PK_ACCESS``와 같은 근거).
# T-VN-35(alembic 0084): 배타 arc 참조 대상 ``uq_features_identity_kind
# UNIQUE (feature_id, kind)``가 생기면서 PK와 선두 컬럼이 같은 btree가 하나 더
# 늘었다. planner는 ``kind``까지 투영하는 hot query에서 이 covering index를 골라
# index-only scan을 한다 — selectivity가 동일하므로 성능 축은 약화되지 않는다.
_FEATURES_PK_ACCESS = (
    "pk_features",
    "features_pkey",
    "uq_features_identity_pair",
    "uq_features_identity_kind",
)

# enrichment review 목록이 탈 수 있는 **동치** 접근 경로.
#
# T-VN-33: queue가 ``source_provider``/``source_dataset_key`` 사본을 잃고
# ``source_entity_key``/``source_record_key``만 든다. provider 표시값은 이제
# entity → provider_datasets join에서 나오므로 provider 전용 복합 인덱스
# (``idx_enrichment_review_provider_status_score``)는 사라졌고, planner는 상황에
# 따라 status/score keyset 또는 entity/record join 인덱스로 queue에 진입한다.
# 두 경로 모두 queue full scan이 아니므로 gate는 둘을 동치로 받고, seq scan 부재는
# 별도로 못박는다.
_ENRICHMENT_REVIEW_ACCESS = (
    "idx_enrichment_review_status_score",
    "idx_enrichment_review_queue_source_entity_record",
)

# T-VN-H50: dedup refresh의 planner 진입점은 이름 하나가 아니라 SQL join 역할별로
# 검증한다. ``idx_source_links_entity`` 하나만 있어도 다른 relation을 우연히 index로
# 읽은 plan이 통과하던 false-pass를 막는다. 각 집합은 현재 ORM/baseline의 정본 index다.
#
# - features: 현재 ``idx_features_updated_keyset``(구 ``idx_features_dedup_refresh_keyset``
#   는 0096에서 제거됨) 또는 feature_id 동등 조회용 PK/covering index
# - source_links: source_entity_key 진입, primary partial 진입, feature/entity PK 진입
# - source_entities: dataset-driven, source_entity_key-driven, key+dataset FK bridge
#   ``source_entities_pkey`` is the canonical PK path for the source_entity_key join.
# ``provider_datasets``는 이 seed에서 dataset당 한 행인 catalog dimension이다. 기본
# planner가 이 작은 relation을 Seq Scan하는 것은 회귀가 아니므로 no-Seq-Scan 대상에서
# 제외한다. ``source_entities``도 이 전용 fixture에서는 provider/dataset 하나가 정확히
# 20%를 선택하므로, 기본 planner가 3,200행 relation을 순차 읽는 것이 정상적인 비용
# 선택일 수 있다. 이 경우에도 강제-index plan으로 provider/dataset index의 호환성은
# 별도로 고정한다. 나머지 대량 relation은 기본 planner에서도 index path를 강제한다.
_DEDUP_REFRESH_ACCESS_BY_RELATION = {
    "features": (
        "idx_features_updated_keyset",
        "pk_features",
        "features_pkey",
        "uq_features_identity_pair",
        "uq_features_identity_kind",
    ),
    "source_links": (
        "idx_source_links_entity",
        "idx_source_links_primary",
        "pk_source_links",
    ),
    "source_entities": (
        "idx_source_entities_provider_dataset",
        "uq_source_entities_key_dataset",
        "source_entities_pkey",
    ),
    "source_entity_heads": (
        "pk_source_entity_heads",
        "source_entity_heads_pkey",
    ),
    "source_records": (
        "pk_source_records",
        "source_records_pkey",
    ),
}
_DEDUP_REFRESH_NO_SEQ_SCAN_RELATIONS = (
    "features",
    "source_links",
    "source_entities",
    "source_entity_heads",
    "source_records",
)


def _assert_no_seq_scan_on(plan: dict[str, Any], relation_name: str) -> None:
    seq_scans = [
        node
        for node in _walk_plan(plan)
        if node.get("Node Type") in {"Seq Scan", "Parallel Seq Scan"}
        and node.get("Relation Name") == relation_name
    ]
    assert not seq_scans, (
        f"unexpected sequential scan on {relation_name}: {seq_scans}\n"
        "EXPLAIN (FORMAT JSON, SETTINGS):\n"
        f"{_format_plan(plan)}"
    )


def _index_names_for_relation(plan: dict[str, Any], relation_name: str) -> set[str]:
    index_names: set[str] = set()

    def visit(node: dict[str, Any], active_relation: str | None = None) -> None:
        node_relation = node.get("Relation Name") or active_relation
        if node_relation == relation_name and node.get("Index Name") is not None:
            index_names.add(str(node["Index Name"]))
        for child in node.get("Plans", []):
            visit(child, node_relation)

    visit(plan)
    return index_names


def _assert_relation_uses_index(
    plan: dict[str, Any], relation_name: str, *expected: str
) -> None:
    used = _index_names_for_relation(plan, relation_name)
    allowed = set(expected)
    assert used, (
        f"{relation_name} expected an index from {expected}, used={sorted(used)}\n"
        "EXPLAIN (FORMAT JSON, SETTINGS):\n"
        f"{_format_plan(plan)}"
    )
    assert used <= allowed, (
        f"{relation_name} expected only indexes from {expected}, used={sorted(used)}\n"
        "EXPLAIN (FORMAT JSON, SETTINGS):\n"
        f"{_format_plan(plan)}"
    )


def _assert_dedup_refresh_is_index_compatible(plan: dict[str, Any]) -> None:
    for relation_name in _DEDUP_REFRESH_NO_SEQ_SCAN_RELATIONS:
        _assert_no_seq_scan_on(plan, relation_name)
    for relation_name, expected in _DEDUP_REFRESH_ACCESS_BY_RELATION.items():
        _assert_relation_uses_index(plan, relation_name, *expected)


def _assert_dedup_refresh_default_plan(plan: dict[str, Any]) -> None:
    """기본 planner가 고선택성 relation을 순차 scan으로 퇴화시키지 않는다.

    ``source_entities``의 provider/dataset 조건은 perf fixture에서 정확히 20%를
    반환한다. PostgreSQL 버전·통계의 비용 경계에 따라 이 작은 relation은 정상적으로
    Seq Scan을 고를 수 있으므로, index 유효성은 위의 forced-index gate가 담당한다.
    """

    for relation_name in _DEDUP_REFRESH_NO_SEQ_SCAN_RELATIONS:
        if relation_name != "source_entities":
            _assert_no_seq_scan_on(plan, relation_name)
    for relation_name, expected in _DEDUP_REFRESH_ACCESS_BY_RELATION.items():
        if relation_name != "source_entities":
            _assert_relation_uses_index(plan, relation_name, *expected)


async def _walk_dedup_review_ids(
    session: AsyncSession, *, page_size: int = 37
) -> list[str]:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(101):
        page = await admin_feature_repo.list_dedup_reviews(
            session, page_size=page_size, cursor=cursor
        )
        seen.extend(item.review_id for item in page.items)
        if page.next_cursor is None:
            return seen
        cursor = page.next_cursor
    raise AssertionError("dedup review page walk did not terminate")


async def _walk_enrichment_review_ids(
    session: AsyncSession, *, page_size: int = 37
) -> list[str]:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(101):
        page = await admin_feature_repo.list_enrichment_reviews(
            session, page_size=page_size, cursor=cursor
        )
        seen.extend(item.review_id for item in page.items)
        if page.next_cursor is None:
            return seen
        cursor = page.next_cursor
    raise AssertionError("enrichment review page walk did not terminate")


async def test_t212d_feature_hot_reads_use_spatial_and_search_indexes(
    migrated_session: AsyncSession,
) -> None:
    await _seed_live_like_perf_data(migrated_session)

    nearby = await _explain_json(
        migrated_session,
        _NEARBY_COORD_DISTANCE_SQL,
        {
            "lon": 126.978,
            "lat": 37.5665,
            "radius_m": 7000.0,
            "kinds": ["place"],
            "categories": None,
            # T-VN-34: nearby는 더 이상 ``:statuses``를 받지 않는다. 종전
            # ``statuses=['active']``이 뜻하던 "공개 표면만"은 이제 질의가 읽는
            # ``feature.public_features``의 3축 술어에 흡수됐고, 같은 술어가
            # ``idx_features_coord_5179_gist``의 partial 조건이기도 하다 — 즉
            # 필터가 사라진 게 아니라 인덱스 쪽으로 내려갔다.
            "providers": None,
            "limit_plus_one": 51,
            "cursor_distance_m": None,
            "cursor_name": None,
            "cursor_last_updated_at": None,
            "cursor_feature_id": None,
        },
    )
    _assert_uses_index(
        nearby,
        "idx_features_coord_5179_gist",
        "idx_features_coord_5179",
    )

    in_bbox = await _explain_json(
        migrated_session,
        _FEATURES_IN_BBOX_SQL,
        {
            "min_lon": 126.975,
            "min_lat": 37.515,
            "max_lon": 126.985,
            "max_lat": 37.525,
            "kinds": ["place", "event"],
            "categories": None,
            "providers": None,
            "cursor_feature_id": None,
            "limit": 200,
            "price_stale_hide_days": 4,
        },
    )
    _assert_uses_index(in_bbox, *_COORD_SPATIAL_INDEXES)

    await migrated_session.execute(
        text("SET LOCAL pg_trgm.similarity_threshold = 0.2")
    )
    search = await _explain_json(
        migrated_session,
        _FEATURE_SEARCH_BY_SCORE_SQL,
        {
            "q": "광화문 실측 카페 37",
            "bbox_enabled": False,
            "min_lon": None,
            "min_lat": None,
            "max_lon": None,
            "max_lat": None,
            "kinds": None,
            "categories": None,
            "cursor_score": None,
            "cursor_feature_id": None,
            "limit_plus_one": 51,
        },
    )
    _assert_uses_index(search, "idx_features_name_trgm")


async def test_t212d_cluster_hot_reads_use_spatial_index_without_mv(
    migrated_session: AsyncSession,
) -> None:
    await _seed_live_like_perf_data(migrated_session)

    params = {
        "min_lon": 126.975,
        "min_lat": 37.515,
        "max_lon": 126.985,
        "max_lat": 37.525,
        "kinds": ["place", "event"],
        "categories": None,
        "providers": None,
        "limit": 200,
    }
    for cluster_unit in ("sido", "sigungu", "eupmyeondong"):
        cluster = await _explain_json(
            migrated_session,
            _CLUSTER_BBOX_SQL_BY_UNIT[cluster_unit],
            params,
        )
        _assert_uses_index(cluster, *_COORD_SPATIAL_INDEXES)

    representative = await _explain_json(
        migrated_session,
        _CLUSTER_BBOX_SQL_BY_UNIT["sigungu"],
        params,
        force_index=False,
    )
    _assert_uses_index(representative, *_COORD_SPATIAL_INDEXES)
    _assert_no_seq_scan_on(representative, "features")


async def test_t212d_geom_only_cluster_uses_subtype_gist_representatively(
    migrated_session: AsyncSession,
) -> None:
    """coord 없는 route/area cluster가 실제 planner에서 **subtype** GiST를 쓴다.

    T-VN-35(ADR-086): geometry 정본이 subtype으로 옮겨지면서 core partial GiST
    (``idx_features_geom_gist``)가 사라지고 ``idx_feature_routes_geom_gist`` /
    ``idx_feature_areas_geom_gist``가 그 자리를 대신한다. bbox 후보 술어가 조립
    뷰의 ``COALESCE(geom)``(인덱스 없음)로 퇴화하면 여기서 잡힌다 — 그때는
    subtype GiST가 plan에서 사라지고 features seq scan이 나타난다.
    """
    await _seed_geom_only_perf_data(migrated_session)

    plan = await _explain_json(
        migrated_session,
        _CLUSTER_BBOX_SQL_BY_UNIT["sigungu"],
        {
            "min_lon": 126.975,
            "min_lat": 36.975,
            "max_lon": 126.985,
            "max_lat": 36.985,
            "kinds": ["route", "area"],
            "categories": None,
            "providers": None,
            "limit": 200,
        },
        force_index=False,
    )

    _assert_uses_index(
        plan, "idx_feature_routes_geom_gist", "idx_feature_areas_geom_gist"
    )
    _assert_no_seq_scan_on(plan, "features")


async def test_t212d_cluster_provider_filter_uses_spatial_index(
    migrated_session: AsyncSession,
) -> None:
    """클러스터 rollup에 provider(소스) 필터를 켜도 bbox GIST 인덱스로 풀리고
    feature.features seqscan이 없어야 한다 — in-bounds provider 필터 '2번 완화책'
    (``:providers`` 단락 + EXISTS, 클러스터 집계에 join 미도입)의 perf 검증.
    """
    await _seed_live_like_perf_data(migrated_session)

    filtered_params = {
        "min_lon": 126.9,
        "min_lat": 37.4,
        "max_lon": 127.1,
        "max_lat": 37.7,
        "kinds": None,
        "categories": None,
        "providers": ["python-visitkorea-api"],
        "limit": 200,
    }
    for cluster_unit in ("sido", "sigungu", "eupmyeondong"):
        plan = await _explain_json(
            migrated_session,
            _CLUSTER_BBOX_SQL_BY_UNIT[cluster_unit],
            filtered_params,
        )
        _assert_uses_index(plan, *_COORD_SPATIAL_INDEXES)

    representative = await _explain_json(
        migrated_session,
        _CLUSTER_BBOX_SQL_BY_UNIT["sigungu"],
        filtered_params,
        force_index=False,
    )
    _assert_uses_index(representative, *_COORD_SPATIAL_INDEXES)
    _assert_no_seq_scan_on(representative, "features")


async def test_t212d_planner_selects_representative_indexes_without_seqscan_hint(
    migrated_session: AsyncSession,
) -> None:
    await _seed_live_like_perf_data(migrated_session)

    in_bbox = await _explain_json(
        migrated_session,
        _FEATURES_IN_BBOX_SQL,
        {
            "min_lon": 126.975,
            "min_lat": 37.515,
            "max_lon": 126.985,
            "max_lat": 37.525,
            "kinds": ["place", "event"],
            "categories": None,
            "providers": None,
            "cursor_feature_id": None,
            "limit": 200,
            "price_stale_hide_days": 4,
        },
        force_index=False,
    )
    _assert_uses_index(in_bbox, *_COORD_SPATIAL_INDEXES)
    _assert_no_seq_scan_on(in_bbox, "features")

    # admin 목록은 **상태 무필터**가 기본이다(T-VN-34C가 legacy status 기본 필터를
    # 제거했다). 그래서 0096이 공개 3축 partial로 좁힌 `idx_features_lower_name_keyset`
    # 로는 이 표면을 덮을 수 없다 — 축을 비우면 후보가 partial 밖으로 나가 features
    # Seq Scan + Sort로 떨어진다. 한동안 이 gate는 파라미터에 공개 3축을 박아
    # "통과하도록" 좁혀져 있었고, 그러면 정작 잃은 표면을 아무도 보지 않게 된다.
    #
    # 0098이 admin scope 전체 인덱스를 신설했으므로 여기서는 **축을 비운 그대로**
    # 못박는다. 두 표면이 각자 인덱스를 갖는다는 것이 그 결정의 내용이다.
    admin_features_by_name = await _explain_json(
        migrated_session,
        admin_feature_repo._admin_features_sql(sort="name", order="asc"),
        {
            "kinds": None,
            "categories": None,
            "lifecycle_states": None,
            "publication_states": None,
            "quality_states": None,
            "provider_dataset_id": None,
            "issue_types": None,
            "has_coord": None,
            "updated_from": None,
            "updated_to": None,
            "q_like": None,
            "has_issue": None,
            "include_ended": False,
            "cursor_feature_id": None,
            "cursor_text": None,
            "cursor_dt": None,
            "cursor_int": None,
            "limit_plus_one": 51,
        },
        force_index=False,
    )
    _assert_uses_index(
        admin_features_by_name, "idx_features_admin_lower_name_keyset"
    )
    _assert_no_seq_scan_on(admin_features_by_name, "features")
    # 인덱스 이름만으로는 "정렬을 인덱스가 대신한다"가 증명되지 않는다(bitmap으로
    # 모아 놓고 다시 Sort해도 이름은 나온다). partial predicate 함의가 실제로
    # 증명됐는지는 최상위 ``Limit`` 바로 아래에 ``Sort``가 없는 것으로 갈린다 —
    # 3축을 비웠을 때 나타나던 노드가 정확히 그 ``Sort``다. issue 집계 LATERAL
    # 안쪽 ``Sort``는 정렬축과 무관하므로 최상위 두 노드만 본다.
    assert admin_features_by_name["Node Type"] == "Limit", admin_features_by_name
    assert (
        admin_features_by_name["Plans"][0]["Node Type"] != "Sort"
    ), admin_features_by_name["Plans"][0]

    # admin **지도**(bbox)와 이름 검색은 상태 무필터일 때 여전히 Seq Scan이다.
    # 0098은 정렬축만 닫았다 — bbox/trgm 축은 실측 두 번이 다 실패했다(전체 인덱스는
    # 공개 partial 보증을 깨고, 여집합 partial은 무필터 질의가 술어를 함의하지 못해
    # 사용 불가). 근거 없는 인덱스를 남기는 대신 공백을 사실로 둔다. 닫으려면 공개
    # partial을 전체로 되돌려 공유하거나 admin 목록에 상태 필터를 필수화해야 하고,
    # 둘 다 표면 결정이라 별도 태스크다(alembic 0098 설계 주석 참조).


async def test_t212d_ops_and_review_lists_use_expected_indexes(
    migrated_session: AsyncSession,
) -> None:
    await _seed_live_like_perf_data(migrated_session)

    admin_features = await _explain_json(
        migrated_session,
        admin_feature_repo._admin_features_sql(sort="updated_at", order="desc"),
        {
            "kinds": ["place"],
            "categories": None,
            # 종전 ``statuses=['active']``의 3축 등가. 0095 backfill 기준으로
            # status='active'인 행은 정확히 lifecycle='active' ∧
            # publication='published' ∧ quality='valid'이고, 그것이 0096 공개
            # partial index의 조건식과 글자 그대로 같다 — 그래서 이 조합만
            # ``idx_features_updated_keyset``에 진입할 수 있다.
            "lifecycle_states": ["active"],
            "publication_states": ["published"],
            "quality_states": ["valid"],
            "provider_dataset_id": None,
            "issue_types": None,
            "has_coord": True,
            "updated_from": None,
            "updated_to": None,
            "q_like": None,
            "has_issue": None,
            "include_ended": False,
            "cursor_feature_id": None,
            "cursor_text": None,
            "cursor_dt": None,
            "cursor_int": None,
            "limit_plus_one": 51,
        },
    )
    # T-VN-34(0097): status 전용 인덱스 ``idx_features_status_updated``는 컬럼과
    # 함께 삭제됐다. 그 자리는 0096이 만든 공개 3축 partial
    # ``idx_features_updated_keyset``(updated_at DESC, feature_id DESC)이
    # 대신한다 — 위 파라미터가 세 축을 공개값으로 못박았으므로 동일한 keyset
    # 진입 경로가 그대로 남는다.
    _assert_uses_index(admin_features, "idx_features_updated_keyset")

    # 완전한 feature_id 검색은 PK 등가 fast-path로 features PK 인덱스를 탄다.
    # (ILIKE 전체 스캔 + source_records 상관 서브쿼리를 건너뜀.) 런타임처럼
    # q_like/q_exact를 모두 넘겨 여분 파라미터가 실행을 깨지 않음도 함께 검증.
    admin_features_by_id = await _explain_json(
        migrated_session,
        admin_feature_repo._admin_features_sql(
            sort="updated_at", order="desc", exact_id=True
        ),
        {
            "kinds": None,
            "categories": None,
            # exact-id fast-path는 상태와 무관하게 PK 등가로 진입해야 한다 —
            # 운영자가 retired/quarantined 행도 id로 찾아야 하므로 세 축 모두
            # 미지정(종전 ``statuses=None``과 같은 뜻)이다.
            "lifecycle_states": None,
            "publication_states": None,
            "quality_states": None,
            "provider_dataset_id": None,
            "issue_types": None,
            "has_coord": None,
            "updated_from": None,
            "updated_to": None,
            "q_like": None,
            "q_exact": "f_1168010100_p_a1b2c3d4e5f6a7b8",
            "has_issue": None,
            "include_ended": True,
            "cursor_feature_id": None,
            "cursor_text": None,
            "cursor_dt": None,
            "cursor_int": None,
            "limit_plus_one": 51,
        },
    )
    _assert_uses_index(admin_features_by_id, *_FEATURES_PK_ACCESS)

    # T-VN-32C (R5) — canonical UUID 검색어는 ``uq_features_feature_uuid`` 인덱스
    # 등가 fast-path를 탄다. 값 전환 후 운영자가 응답 feature_id(UUID)를 그대로
    # 검색하므로, 이 분기가 빠지면 #639가 고친 ILIKE 풀스캔(14~60s)이 회귀한다.
    admin_features_by_uuid = await _explain_json(
        migrated_session,
        admin_feature_repo._admin_features_sql(
            sort="updated_at", order="desc", exact_uuid=True
        ),
        {
            "kinds": None,
            "categories": None,
            # exact-uuid fast-path도 같은 이유로 상태 축을 비운다.
            "lifecycle_states": None,
            "publication_states": None,
            "quality_states": None,
            "provider_dataset_id": None,
            "issue_types": None,
            "has_coord": None,
            "updated_from": None,
            "updated_to": None,
            "q_like": None,
            "q_exact_uuid": "00000000-0000-7000-8000-000000000001",
            "has_issue": None,
            "include_ended": True,
            "cursor_feature_id": None,
            "cursor_text": None,
            "cursor_dt": None,
            "cursor_int": None,
            "limit_plus_one": 51,
        },
    )
    _assert_uses_index(admin_features_by_uuid, "uq_features_feature_uuid")

    jobs = await _explain_json(
        migrated_session,
        ops_repo._LIST_IMPORT_JOBS_SQL,
        {
            "status": "queued",
            "kind": None,
            "load_batch_id": None,
            "parent_job_id": None,
            "cursor_created_at": None,
            "cursor_job_id": None,
            "limit": 51,
        },
    )
    _assert_uses_index(
        jobs,
        "idx_import_jobs_status",
        "idx_import_jobs_created_keyset",
    )

    reports = await _explain_json(
        migrated_session,
        ops_repo._LIST_CONSISTENCY_SQL,
        {
            "severity_max": "WARN",
            "cursor_started_at": None,
            "cursor_report_id": None,
            "limit": 51,
        },
    )
    _assert_uses_index(reports, "idx_reports_severity_started")

    mois_dataset_id = (
        await migrated_session.execute(
            text(
                "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
                "WHERE provider = 'python-mois-api' "
                "  AND dataset_key = 'mois_license_features_bulk'"
            )
        )
    ).scalar_one()
    issues = await _explain_json(
        migrated_session,
        ops_repo._LIST_ISSUES_SQL,
        {
            "status": "open",
            "severity": None,
            "violation_type": None,
            "provider_dataset_id": mois_dataset_id,
            "feature_id": None,
            "q_like": None,
            "bbox_min_lon": None,
            "bbox_min_lat": None,
            "bbox_max_lon": None,
            "bbox_max_lat": None,
            "cursor_last_seen_at": None,
            "cursor_issue_id": None,
            "limit": 51,
        },
    )
    # T-VN-33: provider/dataset_key 사본이 사라지면서 dataset 필터 인덱스가
    # ``idx_violations_provider_status_seen`` → ``idx_data_integrity_violations_dataset_status``
    # (provider_dataset_id, status, last_seen_at)로 바뀌었다.
    _assert_uses_index(
        issues,
        "idx_data_integrity_violations_dataset_status",
        "idx_violations_status_seen",
    )

    dedup = await _explain_json(
        migrated_session,
        _DEDUP_REVIEW_SQL,
        {
            "statuses": ["pending"],
            "providers": None,
            "dataset_keys": None,
            "kinds": None,
            "categories": None,
            "min_score": None,
            "max_score": None,
            "q_like": None,
            "limit_plus_one": 51,
            "cursor_review_id": None,
            "cursor_score": None,
        },
    )
    _assert_uses_index(dedup, "idx_dedup_status_score")

    # 적대 리뷰 P3-2: null cursor는 keyset 술어가 constant-TRUE로 short-circuit돼
    # no-cursor plan과 동일하다. active(비-null) cursor로도 (status,score,id) 복합
    # 인덱스 range를 실제로 타는지(seq scan 없이) 증명한다.
    dedup_cursor = await _explain_json(
        migrated_session,
        _DEDUP_REVIEW_SQL,
        {
            "statuses": ["pending"],
            "providers": None,
            "dataset_keys": None,
            "kinds": None,
            "categories": None,
            "min_score": None,
            "max_score": None,
            "q_like": None,
            "limit_plus_one": 51,
            "cursor_review_id": "00000000-0000-0000-0000-000000000001",
            "cursor_score": "0.5",
        },
    )
    _assert_uses_index(dedup_cursor, "idx_dedup_status_score")
    _assert_no_seq_scan_on(dedup_cursor, "dedup_review_queue")

    dedup_count = await _explain_json(
        migrated_session,
        admin_feature_repo._DEDUP_REVIEW_FAST_COUNT_SQL,  # noqa: PLC2701
        {
            "statuses": ["pending"],
            "min_score": None,
            "max_score": None,
        },
    )
    _assert_uses_index(dedup_count, "idx_dedup_status_score")
    assert _relation_names(dedup_count) == {"dedup_review_queue"}

    enrichment = await _explain_json(
        migrated_session,
        _ENRICHMENT_REVIEW_STATUS_SQL,
        {
            "statuses": ["pending"],
            "providers": None,
            "min_score": None,
            "max_score": None,
            "q_like": None,
            "limit_plus_one": 51,
            "cursor_review_id": None,
            "cursor_score": None,
        },
    )
    _assert_uses_index(enrichment, *_ENRICHMENT_REVIEW_ACCESS)
    _assert_no_seq_scan_on(enrichment, "enrichment_review_queue")

    # 적대 리뷰 P3-2: active(비-null) cursor로도 index range 사용을 증명(enrichment).
    enrichment_cursor = await _explain_json(
        migrated_session,
        _ENRICHMENT_REVIEW_STATUS_SQL,
        {
            "statuses": ["pending"],
            "providers": None,
            "min_score": None,
            "max_score": None,
            "q_like": None,
            "limit_plus_one": 51,
            "cursor_review_id": "00000000-0000-0000-0000-000000000001",
            "cursor_score": "0.5",
        },
    )
    _assert_uses_index(enrichment_cursor, *_ENRICHMENT_REVIEW_ACCESS)
    _assert_no_seq_scan_on(enrichment_cursor, "enrichment_review_queue")

    enrichment_provider = await _explain_json(
        migrated_session,
        _ENRICHMENT_REVIEW_SCALAR_STATUS_PROVIDER_SQL,
        {
            "statuses": ["pending"],
            "status": "pending",
            "providers": ["python-visitkorea-api"],
            "provider": "python-visitkorea-api",
            "min_score": None,
            "max_score": None,
            "q_like": None,
            "limit_plus_one": 51,
            "cursor_review_id": None,
            "cursor_score": None,
        },
    )
    _assert_uses_index(enrichment_provider, *_ENRICHMENT_REVIEW_ACCESS)
    _assert_no_seq_scan_on(enrichment_provider, "enrichment_review_queue")

    enrichment_multi_provider = await _explain_json(
        migrated_session,
        _ENRICHMENT_REVIEW_STATUS_PROVIDER_SQL,
        {
            "statuses": ["pending"],
            "providers": ["python-visitkorea-api", "python-datagokr-api"],
            "min_score": None,
            "max_score": None,
            "q_like": None,
            "limit_plus_one": 51,
            "cursor_review_id": None,
            "cursor_score": None,
        },
    )
    _assert_no_seq_scan_on(enrichment_multi_provider, "enrichment_review_queue")


async def test_t212d_dedup_refresh_and_consistency_checks_are_index_compatible(
    migrated_session: AsyncSession,
) -> None:
    await _seed_live_like_perf_data(migrated_session)

    dedup_params = {
        "provider": "python-mois-api",
        "dataset_key": "mois_license_features_bulk",
        "kinds": ["place"],
        "categories": None,
        "cursor_updated_at": None,
        "cursor_feature_id": None,
        "limit": 500,
    }
    provider_dataset_count = int(
        await migrated_session.scalar(
            text("SELECT count(*) FROM provider_sync.provider_datasets")
        )
        or 0
    )
    assert provider_dataset_count <= 100, (
        "provider_datasets dimension grew beyond the H50 small-table Seq Scan exception: "
        f"count={provider_dataset_count}"
    )
    scoped_source_entities, perf_source_entities = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    count(*) FILTER (
                        WHERE pd.provider = :provider
                          AND pd.dataset_key = :dataset_key
                    ),
                    count(*)
                FROM provider_sync.source_entities AS se
                JOIN provider_sync.provider_datasets AS pd
                  ON pd.provider_dataset_id = se.provider_dataset_id
                WHERE se.source_entity_key LIKE 'perf:se:%'
                """
            ),
            dedup_params,
        )
    ).one()
    assert perf_source_entities > 0, (
        "perf fixture source_entities가 비어 있어 선택성을 검증할 수 없다"
    )
    assert scoped_source_entities * 5 == perf_source_entities, (
        "source_entities Seq Scan 예외는 perf fixture의 정확히 20% provider/dataset "
        f"선택성에만 적용된다: scoped={scoped_source_entities}, "
        f"total={perf_source_entities}"
    )
    dedup_refresh = await _explain_json(
        migrated_session,
        dedup_refresh_repo._LIST_DEDUP_FEATURES_SQL,
        dedup_params,
    )
    # T-VN-33/H50: record가 dataset 자연키 사본을 잃으면서
    # ``idx_source_records_provider_dataset_entity``가 사라졌다. planner는 dataset에서
    # entity로 들어가면 ``idx_source_entities_provider_dataset``를, source link에서
    # entity로 들어가면 entity PK/``uq_source_entities_key_dataset``를 쓸 수 있다. CI의
    # 비용 경계에서 ``idx_source_links_entity``를 고르는 경우도 source_links·source_entities·
    # provider_datasets 각 relation의 역할별 index 조건을 함께 만족해야 한다.
    _assert_dedup_refresh_is_index_compatible(dedup_refresh)

    # H50: forced-index compatibility만 보면 ``enable_seqscan=off``가 숨긴 기본
    # planner 회귀를 놓친다. 단, 이 fixture의 provider/dataset은 source_entities의
    # 정확히 20%를 고르므로 그 relation의 기본 Seq Scan은 비용상 정상이다. 다른 대량
    # relation은 기본 planner에서도 index 조건을 만족해야 한다.
    dedup_refresh_default = await _explain_json(
        migrated_session,
        dedup_refresh_repo._LIST_DEDUP_FEATURES_SQL,
        dedup_params,
        force_index=False,
    )
    _assert_dedup_refresh_default_plan(dedup_refresh_default)

    f4_sample = await _explain_json(
        migrated_session,
        consistency._F4_PENDING_SAMPLE_SQL,  # noqa: PLC2701 - EXPLAIN 대상
        {"lim": 20},
    )
    _assert_uses_index(f4_sample, "idx_dedup_status_score")

    f6_sql = next(case.sql for case in consistency.CONSISTENCY_CASES if case.code == "F6")
    f6 = await _explain_json(migrated_session, f6_sql)
    # T-VN-35(alembic 0084): 영업시간 후보 인덱스는 place subtype으로 이관됐다
    # (``idx_features_opening_hours_keyset`` → ``idx_feature_places_opening_hours``).
    # F6 SQL이 조립 뷰를 읽는 한 후보 술어가 subtype 컬럼에 직접 걸리지 않아 그
    # partial index를 탈 수 없다 — 이 gate는 우선 features/subtype base-table
    # Seq Scan 부재만 고정하고, index 구동 복원은 F6 SQL을 ``feature_places``
    # 직접 참조로 재작성하는 후속 작업이 가져간다(T-VN-35 후속).
    _assert_no_seq_scan_on(f6, "features")
    _assert_no_seq_scan_on(f6, "feature_places")

    f7 = await _explain_json(
        migrated_session,
        consistency._F7_DEDUP_SCORE_ROWS_SQL,  # noqa: PLC2701 - EXPLAIN 대상
    )
    _assert_uses_index(f7, "idx_dedup_status_score", "idx_source_links_primary")

    # feature_files는 아직 실제 Alembic 테이블이 없고, 첫 파일 업로드 PR에서
    # 도입될 예정이다. F8 SQL의 실행 계획 형태만 고정하기 위한 임시 DDL이다.
    await migrated_session.execute(
        text(
            """
            CREATE TABLE feature.feature_files (
                file_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
                feature_id TEXT,
                storage_backend TEXT NOT NULL,
                bucket TEXT NOT NULL,
                object_key TEXT NOT NULL
            )
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.feature_files (
                feature_id, storage_backend, bucket, object_key
            )
            SELECT
                'perf:f:' || lpad(g::text, 6, '0'),
                'rustfs',
                'kor-travel-map',
                'provider/live-like/' || g::text || '.jpg'
            FROM generate_series(1, 200) AS g
            """
        )
    )
    await migrated_session.flush()
    await migrated_session.execute(text("ANALYZE feature.feature_files"))
    f8 = await _explain_json(
        migrated_session,
        consistency._F8_FEATURE_FILE_METADATA_ROWS_SQL,  # noqa: PLC2701
    )
    _assert_uses_index(f8, *_FEATURES_PK_ACCESS)


async def test_t212d_page_queries_keep_uuid_tie_breakers(
    migrated_session: AsyncSession,
) -> None:
    await _seed_live_like_perf_data(migrated_session)

    dedup_page = await admin_feature_repo.list_dedup_reviews(
        migrated_session, page_size=5
    )
    assert len(dedup_page.items) == 5
    assert dedup_page.next_cursor is not None
    dedup_next = await admin_feature_repo.list_dedup_reviews(
        migrated_session, page_size=5, cursor=dedup_page.next_cursor
    )
    assert {item.review_id for item in dedup_page.items}.isdisjoint(
        {item.review_id for item in dedup_next.items}
    )

    enrichment_page = await admin_feature_repo.list_enrichment_reviews(
        migrated_session, page_size=5
    )
    assert len(enrichment_page.items) == 5
    assert enrichment_page.next_cursor is not None
    enrichment_next = await admin_feature_repo.list_enrichment_reviews(
        migrated_session, page_size=5, cursor=enrichment_page.next_cursor
    )
    assert {item.review_id for item in enrichment_page.items}.isdisjoint(
        {item.review_id for item in enrichment_next.items}
    )

    dedup_seen = await _walk_dedup_review_ids(migrated_session)
    dedup_expected = list(
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT review_id::text
                    FROM ops.dedup_review_queue
                    WHERE status = 'pending'
                    ORDER BY total_score DESC, review_id DESC
                    """
                )
            )
        ).scalars()
    )
    assert dedup_seen == dedup_expected
    assert len(dedup_seen) == len(set(dedup_seen))

    enrichment_seen = await _walk_enrichment_review_ids(migrated_session)
    enrichment_expected = list(
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT review_id::text
                    FROM ops.enrichment_review_queue
                    WHERE status = 'pending'
                    ORDER BY name_score DESC, review_id DESC
                    """
                )
            )
        ).scalars()
    )
    assert enrichment_seen == enrichment_expected
    assert len(enrichment_seen) == len(set(enrichment_seen))
