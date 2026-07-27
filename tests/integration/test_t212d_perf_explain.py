"""T-212d 성능 baseline EXPLAIN 통합 테스트.

로컬 live DB를 먼저 확인했지만 현재 Codex Postgres에는 offline smoke 1건만 있어
운영 분포를 측정하기엔 부족했다. 이 테스트는 CI 재현성을 위해 대량 seed를 만들되,
provider/dataset/지역/상태/이슈 분포와 실제 한국 지명 기반 검색어를 섞어 hot path가
대량 데이터에서도 인덱스 친화적인지 검증한다.
"""

from __future__ import annotations

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
                address, detail, urls, raw_refs,
                status, legal_dong_code, sido_code, sigungu_code,
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
                CASE
                  WHEN g % 17 = 0 THEN jsonb_build_object(
                    'place_kind', 'attraction',
                    'business_hours', jsonb_build_object(
                      'periods', jsonb_build_array(
                        jsonb_build_object(
                          'open', jsonb_build_object('day', '1', 'time', '0900'),
                          'close', jsonb_build_object('day', '1', 'time', '1800')
                        )
                      )
                    )
                  )
                  ELSE jsonb_build_object('place_kind', 'attraction')
                END AS detail,
                '{}'::jsonb AS urls,
                '[]'::jsonb AS raw_refs,
                CASE WHEN g % 29 = 0 THEN 'inactive' ELSE 'active' END AS status,
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
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider, dataset_key,
                source_entity_type, source_entity_id,
                first_seen_at, last_seen_at
            )
            SELECT
                'perf:se:' || lpad(g::text, 6, '0'),
                CASE
                  WHEN g % 5 = 0 THEN 'python-mois-api'
                  WHEN g % 5 = 1 THEN 'python-datagokr-api'
                  WHEN g % 5 = 2 THEN 'python-visitkorea-api'
                  WHEN g % 5 = 3 THEN 'python-opinet-api'
                  ELSE 'python-krheritage-api'
                END,
                CASE
                  WHEN g % 5 = 0 THEN 'mois_license_features_bulk'
                  WHEN g % 5 = 1 THEN 'standard_tourist_attractions'
                  WHEN g % 5 = 2 THEN 'visitkorea_festival_events'
                  WHEN g % 5 = 3 THEN 'opinet_stations'
                  ELSE 'krheritage_events'
                END,
                'perf_entity',
                lpad(g::text, 6, '0'),
                now() - (g::text || ' minutes')::interval,
                now() - (g::text || ' seconds')::interval
            FROM generate_series(1, :n) AS g
            """
        ),
        {"n": n},
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, provider, dataset_key,
                source_entity_type, source_entity_id,
                raw_name, raw_address, raw_data, raw_payload_hash,
                fetched_at, imported_at
            )
            SELECT
                'perf:sr:' || lpad(g::text, 6, '0'),
                'perf:se:' || lpad(g::text, 6, '0'),
                CASE
                  WHEN g % 5 = 0 THEN 'python-mois-api'
                  WHEN g % 5 = 1 THEN 'python-datagokr-api'
                  WHEN g % 5 = 2 THEN 'python-visitkorea-api'
                  WHEN g % 5 = 3 THEN 'python-opinet-api'
                  ELSE 'python-krheritage-api'
                END,
                CASE
                  WHEN g % 5 = 0 THEN 'mois_license_features_bulk'
                  WHEN g % 5 = 1 THEN 'standard_tourist_attractions'
                  WHEN g % 5 = 2 THEN 'visitkorea_festival_events'
                  WHEN g % 5 = 3 THEN 'opinet_stations'
                  ELSE 'krheritage_events'
                END,
                'perf_entity',
                lpad(g::text, 6, '0'),
                '원천명 ' || g::text,
                '원천주소 ' || g::text,
                jsonb_build_object('row', g),
                'perf-hash-' || g::text,
                now() - (g::text || ' minutes')::interval,
                now() - (g::text || ' seconds')::interval
            FROM generate_series(1, :n) AS g
            """
        ),
        {"n": n},
    )
    await session.execute(
        text(
            """
            UPDATE provider_sync.source_entities AS se
            SET current_source_record_key =
                'perf:sr:' || right(se.source_entity_key, 6)
            WHERE se.source_entity_key LIKE 'perf:se:%'
            """
        )
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role,
                match_method, confidence, is_primary_source, created_at
            )
            SELECT
                'perf:f:' || lpad(g::text, 6, '0'),
                'perf:se:' || lpad(g::text, 6, '0'),
                'primary',
                'natural_key',
                100,
                true,
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
                provider, dataset_key, source_record_key, feature_id,
                violation_type, severity, message, payload, status, detected_at
            )
            SELECT
                CASE WHEN g % 2 = 0 THEN 'python-mois-api' ELSE 'python-datagokr-api' END,
                CASE WHEN g % 2 = 0 THEN 'mois_license_features_bulk'
                     ELSE 'standard_tourist_attractions' END,
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
                target_feature_id, source_provider, source_dataset_key,
                source_entity_id, source_name, target_name, name_score,
                source_record, status, created_at
            )
            SELECT
                'perf:f:' || lpad(g::text, 6, '0'),
                CASE WHEN g % 3 = 0 THEN 'python-datagokr-api'
                     WHEN g % 3 = 1 THEN 'python-visitkorea-api'
                     ELSE 'python-krheritage-api' END,
                CASE WHEN g % 3 = 0 THEN 'standard_tourist_attractions'
                     WHEN g % 3 = 1 THEN 'visitkorea_festival_events'
                     ELSE 'krheritage_events' END,
                'enrich-' || g::text,
                '축제 원천 ' || g::text,
                '운영 유사 장소 ' || g::text,
                70 + (g % 250)::numeric / 10,
                jsonb_build_object(
                    'provider', CASE WHEN g % 3 = 0 THEN 'python-datagokr-api'
                                      WHEN g % 3 = 1 THEN 'python-visitkorea-api'
                                      ELSE 'python-krheritage-api' END,
                    'dataset_key', CASE WHEN g % 3 = 0 THEN 'standard_tourist_attractions'
                                        WHEN g % 3 = 1 THEN 'visitkorea_festival_events'
                                        ELSE 'krheritage_events' END,
                    'source_entity_id', 'enrich-' || g::text
                ),
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
    """coord 없이 geometry만 가진 route/area의 대표 planner 분포를 만든다."""
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, geom, status,
                sido_code, sigungu_code, legal_dong_code, created_at, updated_at
            )
            SELECT
                'perf:geom:' || lpad(g::text, 6, '0'),
                CASE WHEN g % 2 = 0 THEN 'route' ELSE 'area' END,
                'geometry-only feature ' || g::text,
                '02000000',
                NULL,
                CASE
                  WHEN g % 2 = 0 THEN x_extension.ST_SetSRID(
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
                  ELSE x_extension.ST_SetSRID(
                    x_extension.ST_MakeEnvelope(
                      126.0 + ((g % 1000)::float * 0.002),
                      36.0 + ((g % 800)::float * 0.002),
                      126.0004 + ((g % 1000)::float * 0.002),
                      36.0004 + ((g % 800)::float * 0.002)
                    ),
                    4326
                  )
                END,
                'active',
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
    await session.flush()
    await session.execute(text("ANALYZE feature.features"))


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
        text("EXPLAIN (FORMAT JSON, COSTS OFF) " + sql),
        params or {},
    )
    return result.scalar_one()[0]["Plan"]


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


def _assert_uses_index(plan: dict[str, Any], *expected: str) -> None:
    used = _index_names(plan)
    assert set(expected) & used, f"expected one of {expected}, used={sorted(used)}"


_COORD_SPATIAL_INDEXES = ("idx_features_coord_gist", "idx_features_coord")


def _assert_no_seq_scan_on(plan: dict[str, Any], relation_name: str) -> None:
    seq_scans = [
        node
        for node in _walk_plan(plan)
        if node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") == relation_name
    ]
    assert not seq_scans, f"unexpected Seq Scan on {relation_name}: {seq_scans}"


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
            "statuses": ["active"],
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


async def test_t212d_geom_only_cluster_uses_partial_gist_representatively(
    migrated_session: AsyncSession,
) -> None:
    """coord 없는 route/area cluster도 실제 planner에서 geom partial GiST를 쓴다."""
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

    _assert_uses_index(plan, "idx_features_geom_gist")
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

    admin_features_by_name = await _explain_json(
        migrated_session,
        admin_feature_repo._admin_features_sql(sort="name", order="asc"),
        {
            "kinds": None,
            "categories": None,
            "statuses": None,
            "providers": None,
            "dataset_keys": None,
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
    _assert_uses_index(admin_features_by_name, "idx_features_lower_name_keyset")
    _assert_no_seq_scan_on(admin_features_by_name, "features")


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
            "statuses": ["active"],
            "providers": None,
            "dataset_keys": None,
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
    _assert_uses_index(
        admin_features,
        "idx_features_status_updated",
        "idx_features_updated_keyset",
    )

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
            "statuses": None,
            "providers": None,
            "dataset_keys": None,
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
    _assert_uses_index(admin_features_by_id, "features_pkey", "pk_features")

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

    issues = await _explain_json(
        migrated_session,
        ops_repo._LIST_ISSUES_SQL,
        {
            "status": "open",
            "severity": None,
            "violation_type": None,
            "provider": "python-mois-api",
            "dataset_key": None,
            "feature_id": None,
            "q_like": None,
            "bbox_min_lon": None,
            "bbox_min_lat": None,
            "bbox_max_lon": None,
            "bbox_max_lat": None,
            "cursor_detected_at": None,
            "cursor_issue_id": None,
            "limit": 51,
        },
    )
    _assert_uses_index(
        issues,
        "idx_violations_provider_status_detected",
        "idx_violations_status_detected",
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
    _assert_uses_index(enrichment, "idx_enrichment_review_status_score")

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
    _assert_uses_index(enrichment_cursor, "idx_enrichment_review_status_score")
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
    _assert_uses_index(
        enrichment_provider,
        "idx_enrichment_review_provider_status_score",
        "idx_enrichment_review_status_score",
    )

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

    dedup_refresh = await _explain_json(
        migrated_session,
        dedup_refresh_repo._LIST_DEDUP_FEATURES_SQL,
        {
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
            "kinds": ["place"],
            "categories": None,
            "cursor_updated_at": None,
            "cursor_feature_id": None,
            "limit": 500,
        },
    )
    _assert_uses_index(
        dedup_refresh,
        "idx_source_records_provider_dataset_entity",
        "idx_features_dedup_refresh_keyset",
    )

    f4_sample = await _explain_json(
        migrated_session,
        consistency._F4_PENDING_SAMPLE_SQL,  # noqa: PLC2701 - EXPLAIN 대상
        {"lim": 20},
    )
    _assert_uses_index(f4_sample, "idx_dedup_status_score")

    f6_sql = next(case.sql for case in consistency.CONSISTENCY_CASES if case.code == "F6")
    f6 = await _explain_json(migrated_session, f6_sql)
    _assert_uses_index(f6, "idx_features_opening_hours_keyset")

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
    _assert_uses_index(f8, "pk_features")


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
