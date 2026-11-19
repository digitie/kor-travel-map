"""nearby 재작성(T-READ-09)이 종전 SQL과 **같은 행·같은 순서·같은 cursor**를 내는지 본다.

T-READ-09는 nearby SQL을 둘로 바꿨다 — (1) primary source LATERAL을 반경 안 전 행이 아니라
잘린 page 행에만 붙이고(provider 필터는 같은 선택 규칙의 상관 subquery), (2) 거리순 page를
GiST KNN(``<->``)으로 자른다. 응답 계약은 바뀌면 안 되므로 여기서는 **바꾸기 전 SQL을 그대로
옮긴 oracle**과 새 경로(``features_nearby`` / ``features_nearby_poi_cache_target``)를 같은
시드 위에서 page마다 비교한다.

시드는 일부러 동률을 많이 만든다 — 같은 좌표 4건(거리 동률 → ``feature_id`` tiebreak),
이름 53종(이름 동률), 갱신 시각 17종(시각 동률), primary link 2개(provider 선택 규칙),
primary 없는 행, 비공개 행. 비교는 cursor로 끝까지 걷는 page walk 전체다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo
from kortravelmap.infra.feature_repo import (  # noqa: PLC2701 - oracle·plan 검사 대상
    _NEARBY_COORD_SQL_BY_SORT,
    _NEARBY_SQL_BY_SORT,
    _PUBLIC_ACTIVE_NOTICE_FILTER_SQL,
    NearbyFeaturePage,
    _encode_nearby_cursor,
    _nearby_cursor_params,
    _nearby_row,
    _normalized_attributes,
    _normalized_filter,
    place_attribute_codes_sql,
    place_attribute_filter_sql,
)
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_BASE = datetime(2026, 6, 1, 9, 0, tzinfo=_KST)
# 대전 — 다른 nearby 시드(서울시청 근처)와 떨어진 곳.
_LON = 127.385
_LAT = 36.351
_ROWS = 1_200
_PROVIDER_A = "tread09-a"
_PROVIDER_B = "tread09-b"

# ── oracle: T-READ-09 이전 SQL(2026-11-19 main 68f04e81) 그대로 ─────────────────
_ORACLE_LATERAL = """
    LEFT JOIN LATERAL (
        SELECT pd.provider, pd.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_entities AS se
          ON se.source_entity_key = sl.source_entity_key
        JOIN provider_sync.provider_datasets AS pd
          ON pd.provider_dataset_id = se.provider_dataset_id
        JOIN provider_sync.source_entity_heads AS head
          ON head.source_entity_key = se.source_entity_key
        JOIN provider_sync.source_records AS sr
          ON sr.source_record_key = head.current_source_record_key
        WHERE sl.feature_id = f.feature_id
          AND sl.source_role = 'primary'
        ORDER BY head.observed_at DESC, sr.imported_at DESC, sr.source_record_key
        LIMIT 1
    ) AS ps ON TRUE
    WHERE (CAST(:kinds AS text[]) IS NULL OR f.kind = ANY(CAST(:kinds AS text[])))
      AND (
        CAST(:categories AS text[]) IS NULL
        OR f.category = ANY(CAST(:categories AS text[]))
      )
      AND (
        CAST(:providers AS text[]) IS NULL
        OR ps.provider = ANY(CAST(:providers AS text[]))
      )
      AND """

_ORACLE_SELECT = """
        f.feature_id,
        CAST(f.feature_uuid AS text) AS feature_uuid,
        f.kind,
        f.name,
        f.category,
        x_extension.ST_X(f.coord) AS lon,
        x_extension.ST_Y(f.coord) AS lat,
        x_extension.ST_Distance(f.coord_5179, {pt})::double precision
            AS distance_m,
        ps.provider AS primary_provider,
        ps.dataset_key AS primary_dataset_key,
        f.updated_at AS last_updated_at"""

_ORACLE_TARGET_CTE = (
    """
WITH target AS (
    SELECT target_id, coord_5179,
           COALESCE(CAST(:radius_km AS double precision), radius_km) * 1000.0
             AS radius_m
    FROM ops.poi_cache_targets
    WHERE target_id::text = :target_id
      AND deleted_at IS NULL
      AND coord_5179 IS NOT NULL
),
candidates AS (
    SELECT"""
    + _ORACLE_SELECT.format(pt="t.coord_5179")
    + """
    FROM target AS t
    JOIN feature.public_features AS f
      ON f.coord IS NOT NULL
     AND f.coord_5179 IS NOT NULL
     AND x_extension.ST_DWithin(f.coord_5179, t.coord_5179, t.radius_m)"""
    + _ORACLE_LATERAL
    + place_attribute_filter_sql("f")
    + "\n"
    + _PUBLIC_ACTIVE_NOTICE_FILTER_SQL
    + "\n)\n"
)

_ORACLE_COORD_CTE = (
    """
WITH origin AS (
    SELECT
        x_extension.ST_Transform(
            x_extension.ST_SetSRID(
                x_extension.ST_MakePoint(
                    CAST(:lon AS double precision), CAST(:lat AS double precision)
                ),
                4326
            ),
            5179
        ) AS pt_5179,
        CAST(:radius_m AS double precision) AS radius_m
),
candidates AS (
    SELECT"""
    + _ORACLE_SELECT.format(pt="o.pt_5179")
    + """
    FROM origin AS o
    JOIN feature.public_features AS f
      ON f.coord IS NOT NULL
     AND f.coord_5179 IS NOT NULL
     AND x_extension.ST_DWithin(f.coord_5179, o.pt_5179, o.radius_m)"""
    + _ORACLE_LATERAL
    + place_attribute_filter_sql("f")
    + "\n"
    + _PUBLIC_ACTIVE_NOTICE_FILTER_SQL
    + "\n)\n"
)

_ORACLE_TAIL_BY_SORT = {
    "distance": """
WHERE (
    CAST(:cursor_distance_m AS double precision) IS NULL
    OR (distance_m, feature_id) > (
        CAST(:cursor_distance_m AS double precision),
        CAST(:cursor_feature_id AS uuid)
    )
)
ORDER BY distance_m ASC, feature_id ASC
LIMIT :limit_plus_one
""",
    "name": """
WHERE (
    CAST(:cursor_name AS text) IS NULL
    OR (name, feature_id) > (
        CAST(:cursor_name AS text),
        CAST(:cursor_feature_id AS uuid)
    )
)
ORDER BY name ASC, feature_id ASC
LIMIT :limit_plus_one
""",
    "last_updated_at": """
WHERE (
    CAST(:cursor_last_updated_at AS timestamptz) IS NULL
    OR (last_updated_at, feature_id) < (
        CAST(:cursor_last_updated_at AS timestamptz),
        CAST(:cursor_feature_id AS uuid)
    )
)
ORDER BY last_updated_at DESC, feature_id DESC
LIMIT :limit_plus_one
""",
}


def _oracle_sql(cte: str, sort: str) -> str:
    return (
        cte
        + "SELECT candidates.*, "
        + place_attribute_codes_sql("candidates")
        + " AS attribute_codes\nFROM candidates"
        + _ORACLE_TAIL_BY_SORT[sort]
    )


async def _oracle_page(
    session: AsyncSession,
    sql: str,
    params: dict[str, Any],
    *,
    sort: str,
    limit: int,
    cursor: str | None,
) -> NearbyFeaturePage:
    """``features_nearby*``의 Python 쪽(limit+1·cursor 인코딩)을 그대로 따른 oracle page."""
    rows = (
        (
            await session.execute(
                text(sql),
                {
                    **params,
                    "limit_plus_one": limit + 1,
                    **_nearby_cursor_params(cursor, sort=sort),
                },
            )
        )
        .mappings()
        .all()
    )
    items = tuple(_nearby_row(row) for row in rows[:limit])
    next_cursor = (
        _encode_nearby_cursor(items[-1], sort=sort) if len(rows) > limit and items else None
    )
    return NearbyFeaturePage(items=items, next_cursor=next_cursor)


# ── 시드 ──────────────────────────────────────────────────────────────────────


async def _dataset_id(session: AsyncSession, provider: str) -> int:
    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    )
                    SELECT :provider, :provider || '_ds', :provider, 'system', true,
                           jsonb_build_object('schema_version', 1,
                                              'produces', '[]'::jsonb,
                                              'extensions', '{}'::jsonb)
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                        SET display_name = EXCLUDED.display_name
                    RETURNING provider_dataset_id
                    """
                ),
                {"provider": provider},
            )
        ).scalar_one()
    )


_SEED_FEATURES_SQL = """
INSERT INTO feature.features (
    feature_id, kind, name, category, coord,
    lifecycle_state, publication_state, quality_state, updated_at
)
SELECT
    CAST(md5('tread09:' || g) AS uuid),
    CASE WHEN g % 9 = 0 THEN 'notice' WHEN g % 5 = 0 THEN 'event' ELSE 'place' END,
    'tread09-' || lpad(CAST(g % 53 AS text), 2, '0'),
    CASE WHEN g % 3 = 0 THEN '06020000' ELSE '01010000' END,
    x_extension.ST_SetSRID(
        x_extension.ST_MakePoint(
            CAST(:lon AS double precision)
              + (((g % 300) * 7919) % 1000 - 500) / 1000.0 * 1.2,
            CAST(:lat AS double precision)
              + (((g % 300) * 104729) % 1000 - 500) / 1000.0 * 0.9
        ),
        4326
    ),
    'active',
    CASE WHEN g % 11 = 0 THEN 'suppressed' ELSE 'published' END,
    'valid',
    CAST(:base AS timestamptz) + make_interval(hours => g % 17)
FROM generate_series(1, :rows) AS g
"""

# notice(g % 9 = 0)의 절반은 이미 끝났다 — 공개 notice 감산 fragment가 실제로 행을 거른다.
_SEED_NOTICES_SQL = """
INSERT INTO feature.feature_notices (
    feature_id, kind, notice_type, valid_start_time, valid_end_time
)
SELECT
    CAST(md5('tread09:' || g) AS uuid), 'notice', 'tread09',
    CAST(:base AS timestamptz),
    CASE WHEN g % 2 = 0 THEN CAST(:base AS timestamptz) + interval '1 day'
         ELSE CAST(:base AS timestamptz) + interval '5 years' END
FROM generate_series(1, :rows) AS g
WHERE g % 9 = 0
"""

# primary link: g % 4 = 0이면 없음. 나머지는 g % 3 = 1이면 B, 아니면 A. g % 7 = 0이면 **다른**
# dataset의 primary link를 하나 더 붙이고 관측 시각을 늦춰 선택이 그쪽으로 넘어가게 한다.
# 계보 표들은 BEFORE 트리거가 앞 표를 조회하므로 한 문장의 CTE로 묶지 않고 차례로 넣는다.
_SEED_LINKS_SELECT = """
    SELECT g, 1 AS seq,
           CASE WHEN g % 3 = 1 THEN CAST(:ds_b AS bigint) ELSE CAST(:ds_a AS bigint) END
             AS dataset_id,
           CAST(:base AS timestamptz) AS observed_at
    FROM generate_series(1, :rows) AS g
    WHERE g % 4 <> 0
    UNION ALL
    SELECT g, 2 AS seq,
           CASE WHEN g % 3 = 1 THEN CAST(:ds_a AS bigint) ELSE CAST(:ds_b AS bigint) END
             AS dataset_id,
           CAST(:base AS timestamptz) + interval '1 day' AS observed_at
    FROM generate_series(1, :rows) AS g
    WHERE g % 4 <> 0 AND g % 7 = 0
"""

_SEED_SOURCES_SQL: tuple[str, ...] = (
    f"""
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id, source_entity_type,
    source_entity_id, first_seen_at, last_seen_at
)
SELECT 'tread09:e:' || g || ':' || seq, dataset_id, 'place',
       'tread09-' || g || '-' || seq, observed_at, observed_at
FROM ({_SEED_LINKS_SELECT}) AS links
""",
    f"""
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
)
SELECT 'tread09:r:' || g || ':' || seq, 'tread09:e:' || g || ':' || seq,
       '{{}}'::jsonb, md5('tread09:r:' || g || ':' || seq), observed_at
FROM ({_SEED_LINKS_SELECT}) AS links
""",
    f"""
INSERT INTO provider_sync.source_entity_heads (
    source_entity_key, current_source_record_key, observed_at
)
SELECT 'tread09:e:' || g || ':' || seq, 'tread09:r:' || g || ':' || seq, observed_at
FROM ({_SEED_LINKS_SELECT}) AS links
""",
    f"""
INSERT INTO provider_sync.source_links (
    feature_id, source_entity_key, source_role, match_method, confidence
)
SELECT CAST(md5('tread09:' || g) AS uuid), 'tread09:e:' || g || ':' || seq,
       'primary', 'natural_key', 100
FROM ({_SEED_LINKS_SELECT}) AS links
""",
)


async def _seed(session: AsyncSession) -> None:
    ds_a = await _dataset_id(session, _PROVIDER_A)
    ds_b = await _dataset_id(session, _PROVIDER_B)
    await session.execute(
        text(_SEED_FEATURES_SQL),
        {"lon": _LON, "lat": _LAT, "base": _BASE, "rows": _ROWS},
    )
    await session.execute(text(_SEED_NOTICES_SQL), {"base": _BASE, "rows": _ROWS})
    for statement in _SEED_SOURCES_SQL:
        await session.execute(
            text(statement),
            {"ds_a": ds_a, "ds_b": ds_b, "base": _BASE, "rows": _ROWS},
        )
    # 속성 필터·코드 — A dataset의 place만 pet_friendly.
    await session.execute(
        text(
            """
            INSERT INTO feature.dataset_place_attributes (
                provider_dataset_id, source_entity_type, attribute_code
            )
            VALUES (:ds_a, 'place', 'pet_friendly')
            ON CONFLICT DO NOTHING
            """
        ),
        {"ds_a": ds_a},
    )
    await session.flush()
    await session.execute(text("ANALYZE feature.features"))


_FILTERS: tuple[dict[str, Any], ...] = (
    {},
    {"kinds": ("event",)},
    {"providers": (_PROVIDER_B,)},
    {"kinds": ("place",), "categories": ("06020000",)},
    {"attributes": ("pet_friendly",)},
)
_SORTS = ("distance", "name", "last_updated_at")


def _filter_params(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "kinds": _normalized_filter(filters.get("kinds")),
        "categories": _normalized_filter(filters.get("categories")),
        "providers": _normalized_filter(filters.get("providers")),
        "attributes": _normalized_attributes(filters.get("attributes")),
    }


async def _walk_and_compare(
    session: AsyncSession,
    *,
    new_page: Any,
    oracle_sql: str,
    oracle_params: dict[str, Any],
    sort: str,
    limit: int,
    label: str,
) -> int:
    """cursor로 끝까지 걸으며 page마다 새 경로와 oracle이 같은지 본다. 걸은 행 수를 돌려준다."""
    cursor: str | None = None
    walked = 0
    for page_no in range(200):
        got: NearbyFeaturePage = await new_page(cursor)
        want = await _oracle_page(
            session, oracle_sql, oracle_params, sort=sort, limit=limit, cursor=cursor
        )
        assert got == want, f"{label} page {page_no} differs"
        walked += len(got.items)
        if got.next_cursor is None:
            return walked
        cursor = got.next_cursor
    raise AssertionError(f"{label}: page walk did not terminate")


async def test_coord_nearby_matches_pre_t_read_09_sql(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)
    walked_total = 0
    for radius_m, limit in ((800.0, 1), (5_000.0, 7), (30_000.0, 37), (100_000.0, 50)):
        for sort in _SORTS:
            for filters in _FILTERS:

                async def new_page(
                    cursor: str | None,
                    radius_m: float = radius_m,
                    sort: str = sort,
                    filters: dict[str, Any] = filters,
                    limit: int = limit,
                ) -> NearbyFeaturePage:
                    return await feature_repo.features_nearby(
                        migrated_session,
                        lon=_LON,
                        lat=_LAT,
                        radius_m=radius_m,
                        sort=sort,
                        limit=limit,
                        cursor=cursor,
                        **filters,
                    )

                walked_total += await _walk_and_compare(
                    migrated_session,
                    new_page=new_page,
                    oracle_sql=_oracle_sql(_ORACLE_COORD_CTE, sort),
                    oracle_params={
                        "lon": _LON,
                        "lat": _LAT,
                        "radius_m": radius_m,
                        **_filter_params(filters),
                    },
                    sort=sort,
                    limit=limit,
                    label=f"coord r={radius_m} sort={sort} filters={json.dumps(filters)}",
                )
    # 비교가 빈 page끼리의 항진명제가 아니어야 한다 — 시드 공개 행 대부분을 걸었다.
    assert walked_total > 5_000


async def test_target_nearby_matches_pre_t_read_09_sql(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="tread09",
        target_key="daejeon",
        lon=_LON,
        lat=_LAT,
        radius_km=20.0,
    )
    walked_total = 0
    for radius_km, limit in ((None, 13), (100.0, 50)):
        for sort in _SORTS:
            for filters in _FILTERS:

                async def new_page(
                    cursor: str | None,
                    radius_km: float | None = radius_km,
                    sort: str = sort,
                    filters: dict[str, Any] = filters,
                    limit: int = limit,
                ) -> NearbyFeaturePage:
                    return await feature_repo.features_nearby_poi_cache_target(
                        migrated_session,
                        target_id=target.target_id,
                        radius_km=radius_km,
                        sort=sort,
                        limit=limit,
                        cursor=cursor,
                        **filters,
                    )

                walked_total += await _walk_and_compare(
                    migrated_session,
                    new_page=new_page,
                    oracle_sql=_oracle_sql(_ORACLE_TARGET_CTE, sort),
                    oracle_params={
                        "target_id": target.target_id,
                        "radius_km": radius_km,
                        **_filter_params(filters),
                    },
                    sort=sort,
                    limit=limit,
                    label=f"target r={radius_km} sort={sort} filters={json.dumps(filters)}",
                )
    assert walked_total > 1_000

    # 없는 target과 삭제된 target은 두 경로 모두 빈 page다.
    deleted = await upsert_poi_cache_target(
        migrated_session,
        external_system="tread09",
        target_key="daejeon-deleted",
        lon=_LON,
        lat=_LAT,
        radius_km=20.0,
    )
    await migrated_session.execute(
        text("UPDATE ops.poi_cache_targets SET deleted_at = now() WHERE target_id::text = :t"),
        {"t": deleted.target_id},
    )
    for target_id in ("00000000-0000-7000-8000-000000000000", deleted.target_id):
        got = await feature_repo.features_nearby_poi_cache_target(
            migrated_session, target_id=target_id, limit=10
        )
        want = await _oracle_page(
            migrated_session,
            _oracle_sql(_ORACLE_TARGET_CTE, "distance"),
            {"target_id": target_id, "radius_km": None, **_filter_params({})},
            sort="distance",
            limit=10,
            cursor=None,
        )
        assert got == want == NearbyFeaturePage(items=(), next_cursor=None)


_RADIUS_PREDICATE_DISAGREEMENT_SQL = """
WITH origin AS (
    SELECT x_extension.ST_Transform(
        x_extension.ST_SetSRID(
            x_extension.ST_MakePoint(
                CAST(:lon AS double precision), CAST(:lat AS double precision)
            ),
            4326
        ),
        5179
    ) AS pt_5179
),
radii AS (
    SELECT CAST(r AS double precision) AS radius_m
    FROM unnest(CAST(:radii AS double precision[])) AS r
    UNION
    -- 경계: 시드 행까지의 정확한 거리 자체를 반경으로 — 등호 쪽 판정이 갈리면 여기서 걸린다.
    SELECT x_extension.ST_Distance(f.coord_5179, o.pt_5179)
    FROM feature.features AS f CROSS JOIN origin AS o
    WHERE CAST(f.feature_id AS text) IN (
        SELECT CAST(CAST(md5('tread09:' || g) AS uuid) AS text)
        FROM generate_series(1, 60) AS g
    )
)
SELECT
    count(*) FILTER (
        WHERE x_extension.ST_DWithin(f.coord_5179, o.pt_5179, radii.radius_m)
              IS DISTINCT FROM (
                f.coord_5179 OPERATOR(x_extension.&&)
                  x_extension.ST_Expand(o.pt_5179, radii.radius_m)
                AND f.coord_5179 OPERATOR(x_extension.<->) o.pt_5179 <= radii.radius_m
              )
    ) AS disagreements,
    count(*) FILTER (
        WHERE x_extension.ST_Distance(f.coord_5179, o.pt_5179) = radii.radius_m
    ) AS on_boundary,
    count(*) AS compared
FROM feature.features AS f
CROSS JOIN origin AS o
CROSS JOIN radii
WHERE f.coord_5179 IS NOT NULL
"""


async def test_radius_predicate_matches_st_dwithin(migrated_session: AsyncSession) -> None:
    """새 반경 술어(``&& ST_Expand`` + ``<-> <= r``)가 종전 ``ST_DWithin``과 모든 행에서 같다.

    planner 추정 때문에 ``ST_DWithin``을 두 조각으로 펼쳐 썼다. 반경 경계(행까지의 정확한 거리)를
    포함해 두 술어가 갈리는 (행, 반경) 쌍이 하나도 없어야 한다.
    """
    await _seed(migrated_session)
    row = (
        await migrated_session.execute(
            text(_RADIUS_PREDICATE_DISAGREEMENT_SQL),
            {"lon": _LON, "lat": _LAT, "radii": [0.5, 800.0, 5_000.0, 30_000.0, 100_000.0]},
        )
    ).one()
    assert row.disagreements == 0
    # 경계 반경이 실제로 행을 경계 위에 올렸다(동률 좌표 4건씩) — 검사가 공허하지 않다.
    assert row.on_boundary >= 60
    assert row.compared > 60 * 1_000


async def test_knn_operator_is_st_distance(migrated_session: AsyncSession) -> None:
    """``<->``가 ``ST_Distance``와 같은 C 함수여야 거리 값·순서·cursor가 종전과 같다.

    새 nearby SQL은 ``distance_m``을 ``<->``로 계산한다(KNN을 타려면 정렬 식이 연산자여야
    한다). PostGIS가 바뀌어 ``<->``가 다른 함수(예: centroid 거리)가 되면 여기서 빨개진다.
    """
    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT knn.prosrc AS knn_src, dist.prosrc AS dist_src
                FROM pg_operator AS op
                JOIN pg_proc AS knn ON knn.oid = op.oprcode
                CROSS JOIN pg_proc AS dist
                WHERE op.oprname = '<->'
                  AND op.oprleft = CAST('x_extension.geometry' AS regtype)
                  AND op.oprright = CAST('x_extension.geometry' AS regtype)
                  AND dist.oid = CAST(
                    'x_extension.st_distance(x_extension.geometry, x_extension.geometry)'
                    AS regprocedure
                  )
                """
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].knn_src == rows[0].dist_src == "ST_Distance"


def _plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


async def _explain_analyze(
    session: AsyncSession, sql: str, params: dict[str, Any], *, pre: Sequence[str] = ()
) -> dict[str, Any]:
    for statement in pre:
        await session.execute(text(statement))
    raw = (
        await session.execute(text("EXPLAIN (ANALYZE, FORMAT JSON) " + sql), params)
    ).scalar_one()
    doc = raw if isinstance(raw, list) else json.loads(raw)
    return dict(doc[0]["Plan"])


def _coord_params(radius_m: float, limit_plus_one: int) -> dict[str, Any]:
    return {
        "lon": _LON,
        "lat": _LAT,
        "radius_m": radius_m,
        **_filter_params({}),
        "limit_plus_one": limit_plus_one,
        **_nearby_cursor_params(None, sort="distance"),
    }


async def test_nearby_primary_source_runs_only_for_page_rows(
    migrated_session: AsyncSession,
) -> None:
    """회귀 방지: primary source 조회가 반경 안 전 행이 아니라 page 행에만 돈다.

    T-READ-09 전에는 100km 반경 20만 행 전부에 LATERAL을 돌아 5초가 걸렸다. 계획이 무엇이든
    ``source_links``를 읽는 노드의 실행 횟수(loops)는 page 크기 이하여야 한다.
    """
    await _seed(migrated_session)
    limit_plus_one = 6
    for sort, sql in _NEARBY_COORD_SQL_BY_SORT.items():
        # ``place``만 — notice 행은 공개 notice 감산 fragment가 행마다 계보(source_links)를
        # 따로 읽는다. 그건 종전과 같은 비용이고 여기서 재는 primary source와 무관하다.
        plan = await _explain_analyze(
            migrated_session,
            sql,
            {**_coord_params(100_000.0, limit_plus_one), "kinds": ["place"]},
        )
        assert int(plan["Actual Rows"]) == limit_plus_one, sort
        # ``sl`` = primary source LATERAL, ``attr_link`` = 속성 코드. notice 감산 fragment의
        # 계보 조회(``cur_sl``·``other_sl``)는 종전과 같은 비용이라 여기서 세지 않는다.
        link_nodes = [
            node
            for node in _plan_nodes(plan)
            if node.get("Relation Name") == "source_links"
            and node.get("Alias") in {"sl", "attr_link"}
        ]
        assert link_nodes, f"{sort}: primary source·속성 코드 노드가 없다"
        # LATERAL(page 행마다 1회) + 속성 코드(page 행마다 1회). 반경 안 행 수(~1,000)에
        # 비례하면 회귀다.
        too_many = [
            (
                node.get("Alias"),
                node.get("Node Type"),
                node.get("Actual Loops"),
                node.get("Actual Rows"),
                node.get("Index Name"),
            )
            for node in link_nodes
            if int(node.get("Actual Loops", 0)) > limit_plus_one
        ]
        assert not too_many, (sort, too_many, json.dumps(plan)[:4000])


async def test_nearby_distance_page_can_use_knn_index_order(
    migrated_session: AsyncSession,
) -> None:
    """회귀 방지: 거리순 page의 정렬이 GiST KNN(``<->``)으로 풀 수 있는 형태다.

    작은 시드에서 planner가 무엇을 고를지는 비용 문제라 강제하지 않는다. 대신 bitmap·seq
    scan을 끄면 **정렬 노드 없이** ``idx_features_coord_5179_gist`` 순서 scan으로 풀리는지 —
    누가 page 정렬을 ``ST_Distance(...)`` 식으로 되돌리면 KNN이 불가능해져 여기서 빨개진다.
    """
    await _seed(migrated_session)
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="tread09",
        target_key="daejeon-knn",
        lon=_LON,
        lat=_LAT,
        radius_km=100.0,
    )
    target_params = {
        "target_id": target.target_id,
        "radius_km": None,
        **_filter_params({}),
        "limit_plus_one": 11,
        **_nearby_cursor_params(None, sort="distance"),
    }
    for label, sql, params in (
        ("coord", _NEARBY_COORD_SQL_BY_SORT["distance"], _coord_params(100_000.0, 11)),
        ("target", _NEARBY_SQL_BY_SORT["distance"], target_params),
    ):
        plan = await _explain_analyze(
            migrated_session,
            sql,
            params,
            pre=("SET LOCAL enable_bitmapscan = off", "SET LOCAL enable_seqscan = off"),
        )
        knn = [
            node
            for node in _plan_nodes(plan)
            if node.get("Index Name") == "idx_features_coord_5179_gist" and node.get("Order By")
        ]
        assert knn, f"{label}: 거리순 page가 GiST KNN 순서 scan으로 풀리지 않는다"
        # KNN scan은 LIMIT에서 멈춘다 — 반경 안 전 행(~1,000)을 읽지 않는다.
        assert int(knn[0]["Actual Rows"]) < 200, (label, knn[0]["Actual Rows"])
        assert int(plan["Actual Rows"]) == 11, label
