"""T-VN-21 — 3단 성능 gate 재사용 helper (performance.md §8.3, ADR-075 D-12-4).

정본 정의는 ``docs/architecture/performance.md`` §8.3의 vNext 3단 gate다. 이 모듈은
그 tier-1(매 PR) 검사와 tier-3(index PR) 측정을 위한 재사용 primitive를 모은다.

- tier-1: ``HOT_QUERIES`` registry + ``explain_plan``/``assert_no_seq_scan_on``/
  ``assert_uses_index``(planner-default EXPLAIN smoke), ``count_sql_statements``
  (batch item 수 ≠ query 수 가드), ``query_result_columns``(response-shape 회귀).
- tier-3: ``measure_index_write_cost``(index 변경 전후 write 비용·크기 실측).

hot query를 tier-1에 추가하려면 ``HOT_QUERIES``에 ``HotQuery`` 한 줄을 더한다.
SQL 상수는 ``feature_repo``의 정본을 **읽기만** 하고 재구현하지 않는다.
"""

from __future__ import annotations

import uuid as uuid_module
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import event, text

from kortravelmap.infra.feature_repo import (
    _CATEGORY_FEATURE_COUNTS_SQL,
    _CLUSTER_BBOX_SQL_BY_UNIT,
    _FEATURE_SEARCH_BY_SCORE_SQL,
    _FEATURES_IN_BBOX_SQL,
    _GET_PUBLIC_FEATURE_SQL,
    _GET_PUBLIC_FEATURES_BY_IDS_SQL,
    _NEARBY_COORD_DISTANCE_SQL,
    _SERVICE_FEATURE_BATCH_SQL,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

__all__ = [
    "HOT_QUERIES",
    "HotQuery",
    "assert_no_seq_scan_on",
    "assert_uses_index",
    "count_sql_statements",
    "explain_plan",
    "index_names",
    "measure_index_write_cost",
    "query_result_columns",
    "seed_hot_query_features",
    "seed_uuid_namespace",
    "seeded_feature_id",
    "seq_scan_relations",
    "walk_plan",
]


# ---------------------------------------------------------------------------
# seed 라벨 → 정본 키(uuid) 대역
# ---------------------------------------------------------------------------

# T-VN-39 재키(alembic 309) 뒤 ``feature.features.feature_id``는 uuid이고, 값을
# 채워 주던 ``trg_features_feature_uuid_fill``도 영구 제거됐다 — seed가 정본 키를
# **직접** 넣어야 한다. 그런데 ``gen_random_uuid()``로 흩뿌리면 tier-1 hot query가
# 겨누는 "그 50건"을 seed 밖에서 다시 알아낼 방법이 없다(EXPLAIN 파라미터는 seed
# 이전에 정해진다).
#
# 그래서 종전의 라벨(``perf:f:``/``tier2:f:``)을 버리지 않고 uuid **대역**으로
# 접는다: 라벨이 상위 20자리를, 순번이 하위 12자리를 정한다. 이 형태가 종전 문자열
# id의 세 성질을 그대로 옮긴다.
#
# - **결정적**: 파이썬과 SQL이 seed 없이도 같은 값을 만든다.
# - **라벨별 분리**: 라벨이 다르면 대역이 겹치지 않는다 — tier-2가 "고정 fixture
#   id에 기대지 않는다"를 검사할 때 두 seed를 가르는 축이 남는다.
# - **순번 정렬 = uuid 정렬**: uuid 비교는 16바이트 사전식이고 대역이 상수이므로,
#   공개 batch selector의 ``ORDER BY feature_id``가 종전 문자열 정렬과 같은 순서를
#   낸다.
_SEED_UUID_LABEL_NAMESPACE: Final[uuid_module.UUID] = uuid_module.UUID(
    "f39d0000-0000-7000-8000-000000000000"
)


def seed_uuid_namespace(feature_id_prefix: str) -> str:
    """seed 라벨 → 그 라벨이 쓰는 ``feature_id`` uuid의 상위 20자리(순번 앞까지).

    버전/변이 nibble을 7/8로 못 박아 canonical UUIDv7 표기를 유지한다 — 응답
    경계가 돌려주는 값과 같은 모양이라야 fixture가 운영과 다른 형태를 planner에
    보여주지 않는다.
    """

    label = uuid_module.uuid5(_SEED_UUID_LABEL_NAMESPACE, feature_id_prefix).hex
    return f"{label[:8]}-{label[8:12]}-7{label[13:16]}-8{label[17:20]}-"


def seeded_feature_id(feature_id_prefix: str, index: int) -> str:
    """``feature_id_prefix`` 대역의 ``index``번째 seed feature 정본 키(uuid text)."""

    return f"{seed_uuid_namespace(feature_id_prefix)}{index:012x}"


#: tier-1 기본 seed 라벨. ``seed_hot_query_features``의 기본값과 같아야 한다.
_SEED_FEATURE_ID_PREFIX: Final[str] = "perf:f:"
_SEED_FEATURE_ID = seeded_feature_id(_SEED_FEATURE_ID_PREFIX, 100)


# ---------------------------------------------------------------------------
# hot-query registry (tier-1 대상) — 한 줄 추가로 gate에 편입된다.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HotQuery:
    """tier-1 planner-default EXPLAIN smoke 대상 hot query 1건."""

    name: str
    sql: str
    params: Mapping[str, Any]
    # 최소 1개가 plan에 나타나야 하는 기대 index. 빈 tuple이면 index 사용은
    # 검사하지 않고(집계 등) seq-scan 부재만 검사한다.
    expected_indexes: tuple[str, ...]
    # 이 relation들에 base-table Seq Scan이 없어야 한다. 기본은 features.
    no_seq_scan_on: tuple[str, ...] = ("features",)
    # EXPLAIN 전에 같은 트랜잭션에서 실행할 SET LOCAL 등.
    pre_statements: tuple[str, ...] = field(default_factory=tuple)
    # 요청 cardinality가 커도 운영 규모와 비슷한 selectivity에서 planner를 검증한다.
    seed_n: int = 3200


_BBOX_PARAMS: dict[str, Any] = {
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
}
_NEARBY_PARAMS: dict[str, Any] = {
    "lon": 126.978,
    "lat": 37.5665,
    "radius_m": 7000.0,
    "kinds": ["place"],
    "categories": None,
    # T-VN-34: nearby CTE는 ``feature.public_features``를 조인하므로 가시성 술어가
    # 뷰 안(3축 active/published/valid)에 있다. 호출자가 넘기던 ``statuses`` 필터는
    # 3축 어느 축으로도 옮길 자리가 없어졌다 — 옮기면 뷰가 이미 건 술어를 밖에서
    # 한 번 더 재구현하는 것이라 F-1(공개 술어 복제)이다. 그래서 키를 뺀다.
    "providers": None,
    "limit_plus_one": 51,
    "cursor_distance_m": None,
    "cursor_name": None,
    "cursor_last_updated_at": None,
    "cursor_feature_id": None,
}
_SEARCH_PARAMS: dict[str, Any] = {
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
}
_CLUSTER_PARAMS: dict[str, Any] = {
    "min_lon": 126.975,
    "min_lat": 37.515,
    "max_lon": 126.985,
    "max_lat": 37.525,
    "kinds": ["place", "event"],
    "categories": None,
    "providers": None,
    "limit": 200,
}

_COORD_SPATIAL = ("idx_features_coord_gist", "idx_features_coord")
_COORD_5179_SPATIAL = ("idx_features_coord_5179_gist", "idx_features_coord_5179")

# features의 ``feature_id`` 동등 조건이 탈 수 있는 **동치** 접근 경로.
#
# T-VN-35(alembic 0084)의 배타 arc 참조 대상 ``UNIQUE (feature_id, kind)``는 PK와
# 선두 컬럼이 같은 btree라, ``kind``까지 투영하는 hot query에서 planner가 이 covering
# index를 골라 index-only scan을 한다. 309 재키가 그 제약을
# ``uq_features_identity_kind`` → ``uq_features_id_kind``로 개명했다(``_UNIQUE_RENAME``)
# — 이름이 "identity"를 자칭할 이유가 없어졌기 때문이다.
#
# 같은 성격이던 ``uq_features_identity_pair UNIQUE (feature_id, feature_uuid)``는
# **사라졌다.** 309 ``_SHADOW_DROP``의 ``features DROP COLUMN feature_uuid``가 그
# 제약을 함께 지웠고 ``_COLLATERAL_RECREATE``도 되살리지 않는다 — 두 컬럼이 한
# 값의 두 표기가 된 마당에 (feature_id, feature_uuid) 복합 unique는 PK의 사본이다.
# 그래서 이 목록에서도 뺀다: 남겨 두면 "돌아올 수 없는 index"를 기대 이름으로
# 계속 세어 gate가 무엇을 보장하는지 흐려진다.
#
# 성능 축은 **약화되지 않는다** — 남은 이름들은 선두 컬럼이 PK와 같아 selectivity가
# 동일하고, heap 접근이 줄어드는 쪽이다. gate가 지키려는 것은 "Seq Scan 금지 +
# index 접근"이므로 이 이름들을 동치로 받는다. (PK 자체가 사라지는 회귀는
# ``assert_no_seq_scan_on``이 계속 잡는다.)
_FEATURES_PK_ACCESS = (
    "pk_features",
    "features_pkey",
    "uq_features_id_kind",
)

HOT_QUERIES: tuple[HotQuery, ...] = (
    HotQuery(
        "public detail (PK)",
        _GET_PUBLIC_FEATURE_SQL,
        {"feature_id": _SEED_FEATURE_ID},
        expected_indexes=_FEATURES_PK_ACCESS,
    ),
    HotQuery(
        "public batch (ANY ids)",
        _GET_PUBLIC_FEATURES_BY_IDS_SQL,
        {
            "feature_ids": [
                seeded_feature_id(_SEED_FEATURE_ID_PREFIX, i) for i in range(1, 51)
            ]
        },
        expected_indexes=_FEATURES_PK_ACCESS,
    ),
    HotQuery(
        "service feature batch 5-state (200)",
        _SERVICE_FEATURE_BATCH_SQL,
        {
            "feature_ids": [
                seeded_feature_id(_SEED_FEATURE_ID_PREFIX, i) for i in range(1, 201)
            ],
            "known_row_revisions": [None] * 200,
        },
        expected_indexes=_FEATURES_PK_ACCESS,
        # 기존 public batch 50/3,200과 같은 1.56% selectivity를 유지한다.
        seed_n=12_800,
    ),
    HotQuery(
        "in-bounds / bbox",
        _FEATURES_IN_BBOX_SQL,
        _BBOX_PARAMS,
        expected_indexes=_COORD_SPATIAL,
    ),
    HotQuery(
        "nearby (5179 GiST)",
        _NEARBY_COORD_DISTANCE_SQL,
        _NEARBY_PARAMS,
        expected_indexes=_COORD_5179_SPATIAL,
    ),
    HotQuery(
        "search (trgm GIN)",
        _FEATURE_SEARCH_BY_SCORE_SQL,
        _SEARCH_PARAMS,
        expected_indexes=("idx_features_name_trgm",),
        pre_statements=("SET LOCAL pg_trgm.similarity_threshold = 0.2",),
    ),
    HotQuery(
        "category counts (GROUP BY)",
        _CATEGORY_FEATURE_COUNTS_SQL,
        {},
        # 공개 술어 partial index로 집계를 돌린다(seq scan 아님). 특정 index 이름을
        # 강제하지 않고 features base-table Seq Scan 부재만 검사한다.
        expected_indexes=(),
    ),
    HotQuery(
        "cluster rollup — sido",
        _CLUSTER_BBOX_SQL_BY_UNIT["sido"],
        _CLUSTER_PARAMS,
        expected_indexes=_COORD_SPATIAL,
    ),
    HotQuery(
        "cluster rollup — sigungu",
        _CLUSTER_BBOX_SQL_BY_UNIT["sigungu"],
        _CLUSTER_PARAMS,
        expected_indexes=_COORD_SPATIAL,
    ),
    HotQuery(
        "cluster rollup — eupmyeondong",
        _CLUSTER_BBOX_SQL_BY_UNIT["eupmyeondong"],
        _CLUSTER_PARAMS,
        expected_indexes=_COORD_SPATIAL,
    ),
)


# ---------------------------------------------------------------------------
# EXPLAIN plan primitives
# ---------------------------------------------------------------------------


def walk_plan(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """plan 트리를 평탄화한다."""

    nodes: list[Mapping[str, Any]] = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(walk_plan(child))
    return nodes


def index_names(plan: Mapping[str, Any]) -> set[str]:
    return {
        str(node["Index Name"])
        for node in walk_plan(plan)
        if node.get("Index Name") is not None
    }


def seq_scan_relations(plan: Mapping[str, Any]) -> set[str]:
    return {
        str(node["Relation Name"])
        for node in walk_plan(plan)
        if node.get("Node Type") == "Seq Scan" and node.get("Relation Name") is not None
    }


async def explain_plan(
    session: AsyncSession,
    sql: str,
    params: Mapping[str, Any] | None = None,
    *,
    planner_default: bool = True,
    pre_statements: Sequence[str] = (),
) -> dict[str, Any]:
    """``EXPLAIN (FORMAT JSON, COSTS OFF)``의 최상위 Plan을 반환한다.

    ``planner_default=True``(tier-1 기본)면 ``enable_seqscan``을 건드리지 않아 실제
    planner 선택을 본다. ``False``는 회귀 감시용 index 적격성 확인(``enable_seqscan
    =off``) 전용이며 채택 근거로 쓰지 않는다(§8.3, D-12-4).
    """

    if not planner_default:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
    for statement in pre_statements:
        await session.execute(text(statement))
    result = await session.execute(
        text("EXPLAIN (FORMAT JSON, COSTS OFF) " + sql), dict(params or {})
    )
    plan: dict[str, Any] = result.scalar_one()[0]["Plan"]
    return plan


def assert_uses_index(plan: Mapping[str, Any], *expected: str) -> None:
    if not expected:
        return
    used = index_names(plan)
    assert set(expected) & used, f"expected one of {expected}, used={sorted(used)}"


def assert_no_seq_scan_on(plan: Mapping[str, Any], *relations: str) -> None:
    seq = seq_scan_relations(plan)
    offending = seq & set(relations)
    assert not offending, (
        f"unexpected base-table Seq Scan on {sorted(offending)} "
        f"(all seq scans: {sorted(seq)})"
    )


# ---------------------------------------------------------------------------
# query-count guard (batch item 수 ≠ query 수) + response-shape 회귀
# ---------------------------------------------------------------------------


@contextmanager
def count_sql_statements(bind: AsyncEngine | Engine) -> Iterator[list[str]]:
    """context 안에서 실행된 non-EXPLAIN SQL statement를 수집한다.

    ``bind``는 async engine 또는 그 ``sync_engine``. batch/list repo 호출을 이
    context로 감싸 ``len(statements)``가 item 수에 비례하지 않는지 검사한다(N+1 가드).
    """

    sync_engine = getattr(bind, "sync_engine", bind)
    collected: list[str] = []

    def _before(_conn: Any, _cursor: Any, statement: str, *_a: Any) -> None:
        normalized = statement.lstrip().lower()
        if normalized.startswith(("explain", "set ", "begin", "commit", "rollback")):
            return
        collected.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield collected
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


async def query_result_columns(
    session: AsyncSession,
    sql: str,
    params: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """쿼리 결과 컬럼 이름을 정렬해 반환한다(response-shape 회귀 snapshot용)."""

    result = await session.execute(text(sql), dict(params or {}))
    return tuple(sorted(result.keys()))


# ---------------------------------------------------------------------------
# tier-3 — index 변경 PR before/after write 비용 helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WriteCostSample:
    """index 유무 한 조건의 write 비용 실측."""

    label: str
    rows: int
    elapsed_ms: float
    index_bytes: int


async def measure_index_write_cost(
    session: AsyncSession,
    *,
    label: str,
    insert_sql: str,
    row_batches: Sequence[Mapping[str, Any]],
    index_relation: str | None = None,
) -> WriteCostSample:
    """``insert_sql``을 ``row_batches``로 실행한 write 소요 시간·index 크기를 잰다.

    index 변경 PR(tier-3)이 변경 전/후로 각각 호출해 write 비용과 index 크기를
    첨부한다(§8.3, GiST 6→partial 정리의 ~1.6× 실측 선례). 순수 측정 helper로
    스키마를 바꾸지 않는다 — index 생성/삭제는 호출자(migration/DDL)가 한다.
    """

    import time

    start = time.perf_counter()
    for batch in row_batches:
        await session.execute(text(insert_sql), dict(batch))
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    index_bytes = 0
    if index_relation is not None:
        index_bytes = int(
            (
                await session.execute(
                    text("SELECT pg_relation_size(:rel)"),
                    {"rel": index_relation},
                )
            ).scalar_one()
        )
    return WriteCostSample(
        label=label,
        rows=len(row_batches),
        elapsed_ms=elapsed_ms,
        index_bytes=index_bytes,
    )


# ---------------------------------------------------------------------------
# focused seed — public hot query만 겨냥한 features 분포 (self-contained)
# ---------------------------------------------------------------------------

# T-VN-35(ADR-086): core에 ``detail``이 없다. kind별 값은 subtype 5종이 정본이고
# 응답 ``detail``은 공개 projection ``feature.public_features``가 subtype join으로
# 조립한다(0097이 중간 뷰 ``features_detailed``를 없애고 그 조립을 공개 뷰로
# 흡수했다) — seed도 같은 구조를 만들어야 planner가 운영과 같은 relation 분포를
# 본다(place/event subtype이 비어 있으면 뷰 조인이 비현실적으로 싸진다).
#
# T-VN-34(0095~0097): 이 seed가 planner에게 보여야 하는 것은 "공개 표면에 들어오는
# 행과 빠지는 행의 비율"이다. 옛 ``status``의 두 값이 그 비율을 만들었고, 0095
# backfill 규칙상 ``'active'`` → (lifecycle active, publication published),
# ``'inactive'`` → (lifecycle retired, publication suppressed)로 대응한다. 아래는
# 그 대응을 그대로 쓴 것이라 ``g % 29`` 비공개 비율(≈3.4%)이 이식 전후로 동일하고,
# 따라서 tier-1이 보는 selectivity와 index 선택도 바뀌지 않는다.
# ``quality_state``는 명시하지 않는다 — 옛 seed가 ``status='broken'``을 만든 적이
# 없어 3축으로는 전부 컬럼 DEFAULT인 ``'valid'``이고, 굳이 적으면 "quarantined
# 행이 있을 수 있다"는 없는 분포를 암시하게 된다.
_SEED_FEATURES_SQL = """
INSERT INTO feature.features (
    feature_id, kind, name, category, coord,
    address, urls, raw_refs,
    lifecycle_state, publication_state,
    legal_dong_code, sido_code, sigungu_code,
    created_at, updated_at
)
SELECT
    -- 재키 뒤 정본 키는 uuid다. 라벨 대역(상위 20자리) + 순번(하위 12자리) —
    -- ``seed_uuid_namespace``/``seeded_feature_id``가 같은 값을 파이썬에서 만든다.
    CAST(:uuid_namespace || lpad(to_hex(g), 12, '0') AS uuid) AS feature_id,
    CASE WHEN g % 19 = 0 THEN 'event' WHEN g % 23 = 0 THEN 'weather'
         ELSE 'place' END AS kind,
    CASE
      WHEN g % 37 = 0 THEN '광화문 실측 카페 ' || g::text
      WHEN g % 41 = 0 THEN '해운대 축제 라이브 ' || g::text
      WHEN g % 43 = 0 THEN '제주 오름 휴양림 ' || g::text
      ELSE '운영 유사 장소 ' || g::text
    END AS name,
    CASE WHEN g % 19 = 0 THEN '02010000' WHEN g % 23 = 0 THEN '99000000'
         WHEN g % 7 = 0 THEN '06020000' ELSE '01070300' END AS category,
    x_extension.ST_SetSRID(
        x_extension.ST_MakePoint(
            CASE WHEN g % 11 = 0 THEN 129.10 + ((g % 50)::float * 0.001)
                 WHEN g % 13 = 0 THEN 126.50 + ((g % 40)::float * 0.002)
                 ELSE 126.92 + ((g % 120)::float * 0.0015) END,
            CASE WHEN g % 11 = 0 THEN 35.15 + ((g % 50)::float * 0.001)
                 WHEN g % 13 = 0 THEN 33.38 + ((g % 40)::float * 0.002)
                 ELSE 37.48 + ((g % 120)::float * 0.0010) END
        ), 4326) AS coord,
    jsonb_build_object('road', '서울특별시 종로구 세종대로 ' || (g % 200)::text,
                       'legal', '서울특별시 종로구 세종로') AS address,
    '{}'::jsonb AS urls,
    '[]'::jsonb AS raw_refs,
    CASE WHEN g % 29 = 0 THEN 'retired' ELSE 'active' END AS lifecycle_state,
    CASE WHEN g % 29 = 0 THEN 'suppressed' ELSE 'published' END AS publication_state,
    CASE WHEN g % 11 = 0 THEN '2611010100' WHEN g % 13 = 0 THEN '5011010100'
         ELSE '1111010100' END AS legal_dong_code,
    CASE WHEN g % 11 = 0 THEN '26' WHEN g % 13 = 0 THEN '50'
         ELSE '11' END AS sido_code,
    CASE WHEN g % 11 = 0 THEN '26110' WHEN g % 13 = 0 THEN '50110'
         ELSE '11110' END AS sigungu_code,
    now() - (g::text || ' minutes')::interval AS created_at,
    now() - ((:n - g)::text || ' seconds')::interval AS updated_at
FROM generate_series(1, :n) AS g
"""

#: place/event subtype seed — core seed와 같은 kind 분기를 따른다. weather는
#: subtype이 없다(값 정본은 ``feature_weather_values``).
_SEED_PLACE_SUBTYPE_SQL = """
INSERT INTO feature.feature_places (feature_id, kind, place_kind)
SELECT f.feature_id, f.kind, 'attraction'
FROM feature.features AS f
WHERE CAST(f.feature_id AS text) LIKE :uuid_namespace || '%' AND f.kind = 'place'
"""

_SEED_EVENT_SUBTYPE_SQL = """
INSERT INTO feature.feature_events (
    feature_id, kind, event_kind, starts_on, ends_on
)
SELECT
    f.feature_id, f.kind, 'festival',
    CURRENT_DATE - 3, CURRENT_DATE + 3
FROM feature.features AS f
WHERE CAST(f.feature_id AS text) LIKE :uuid_namespace || '%' AND f.kind = 'event'
"""

# source_entities/records/links — 공개 read가 공유하는 notice 감산
# 필터(``public_active_notice_filter_sql``의 source_links NOT EXISTS anti-join)와
# nearby primary-source LATERAL이 실측 planner 선택을 내려면 populated 되어야 한다.
_PERF_DATASET_PAIRS_SQL = """
SELECT * FROM (VALUES
    (0, 'python-mois-api', 'mois_license_features_bulk'),
    (1, 'python-datagokr-api', 'standard_tourist_attractions'),
    (2, 'python-visitkorea-api', 'visitkorea_festival_events'),
    (3, 'python-opinet-api', 'opinet_stations'),
    (4, 'python-krheritage-api', 'krheritage_events')
) AS pair(bucket, provider, dataset_key)
"""

# fixture는 catalog seed에 의존하지 않고 자기 pair를 만든다. 0089가 심는 목록은
# provider_catalog.py + 그 DB의 실데이터 legacy sweep에 따라 달라지므로(실측: 이 5쌍
# 중 2쌍만 존재) catalog를 전제하면 fixture가 DB마다 다르게 깨진다.
_SEED_PERF_PROVIDER_DATASETS_SQL = f"""
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind, is_active, capabilities
)
SELECT
    pair.provider, pair.dataset_key, pair.provider || ' / ' || pair.dataset_key,
    'system', true,
    jsonb_build_object(
        'schema_version', 1, 'produces', '[]'::jsonb, 'extensions', '{{}}'::jsonb
    )
FROM ({_PERF_DATASET_PAIRS_SQL}) AS pair
ON CONFLICT (provider, dataset_key) DO NOTHING
"""

_SEED_SOURCE_ENTITIES_SQL = f"""
INSERT INTO provider_sync.source_entities (
    source_entity_key, provider_dataset_id,
    source_entity_type, source_entity_id, first_seen_at, last_seen_at
)
SELECT
    'perf:se:' || lpad(g::text, 6, '0'),
    dataset.provider_dataset_id,
    'perf_entity', lpad(g::text, 6, '0'),
    now() - (g::text || ' minutes')::interval,
    now() - (g::text || ' seconds')::interval
FROM generate_series(1, :n) AS g
JOIN ({_PERF_DATASET_PAIRS_SQL}) AS pair ON pair.bucket = g % 5
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider = pair.provider
 AND dataset.dataset_key = pair.dataset_key
"""

# source_record는 provider/dataset을 더 들지 않는다 — entity를 통해 도달한다.
_SEED_SOURCE_RECORDS_SQL = """
INSERT INTO provider_sync.source_records (
    source_record_key, source_entity_key,
    raw_data, raw_payload_hash, fetched_at, imported_at
)
SELECT
    'perf:sr:' || lpad(g::text, 6, '0'),
    'perf:se:' || lpad(g::text, 6, '0'),
    jsonb_build_object('row', g, 'raw_name', '원천명 ' || g::text),
    md5('perf-hash-' || g::text),
    now() - (g::text || ' minutes')::interval,
    now() - (g::text || ' seconds')::interval
FROM generate_series(1, :n) AS g
"""

# 현재 record 포인터와 계보 정렬축은 head가 갖는다. ``lineage_key``는
# BEFORE INSERT 트리거가 채우므로 여기서 쓰지 않는다 — 쓰면 파생이 아니게 된다.
_SEED_SOURCE_ENTITY_HEADS_SQL = """
INSERT INTO provider_sync.source_entity_heads (
    source_entity_key, current_source_record_key, observed_at
)
SELECT
    'perf:se:' || lpad(g::text, 6, '0'),
    'perf:sr:' || lpad(g::text, 6, '0'),
    now() - (g::text || ' seconds')::interval
FROM generate_series(1, :n) AS g
"""

_SEED_SOURCE_LINKS_SQL = """
INSERT INTO provider_sync.source_links (
    feature_id, source_entity_key, source_role,
    match_method, confidence, created_at
)
SELECT
    CAST(:uuid_namespace || lpad(to_hex(g), 12, '0') AS uuid),
    'perf:se:' || lpad(g::text, 6, '0'),
    'primary', 'natural_key', 100, now()
FROM generate_series(1, :n) AS g
"""


async def seed_hot_query_features(
    session: AsyncSession,
    *,
    n: int = 3200,
    feature_id_prefix: str = _SEED_FEATURE_ID_PREFIX,
) -> None:
    """서울/부산/제주 분포의 features + primary source lineage를 seed하고 ANALYZE한다.

    tier-1 EXPLAIN이 실제 planner 선택을 보려면 통계가 필요하므로 ANALYZE한다. 공개
    notice 감산 필터의 ``source_links`` NOT EXISTS anti-join과 nearby primary-source
    LATERAL이 실측 plan을 내도록 source_entities/records/links도 함께 채운다(빈
    상태면 planner가 features를 seq-scan한다). ops/review 계열은 public hot query에
    불필요해 생략한다. n은 selective 쿼리에서 planner가 index를 선호하기에 충분하다.
    ``feature_id_prefix``는 tier-2가 고정 fixture ID에 의존하지 않는 경로를 검증할 때만
    바꾸며 tier-1 기본 계약은 ``perf:f:``를 유지한다. T-VN-39 재키 뒤 그 라벨은
    ``feature_id`` 값에 문자열로 남지 않고 uuid **대역**으로 접힌다
    (:func:`seed_uuid_namespace`) — 라벨별 분리와 순번 정렬은 그대로다.
    """

    uuid_namespace = seed_uuid_namespace(feature_id_prefix)
    await session.execute(
        text(_SEED_FEATURES_SQL),
        {"n": n, "uuid_namespace": uuid_namespace},
    )
    for subtype_sql in (_SEED_PLACE_SUBTYPE_SQL, _SEED_EVENT_SUBTYPE_SQL):
        await session.execute(text(subtype_sql), {"uuid_namespace": uuid_namespace})
    await session.execute(text(_SEED_PERF_PROVIDER_DATASETS_SQL))
    await session.execute(text(_SEED_SOURCE_ENTITIES_SQL), {"n": n})
    await session.execute(text(_SEED_SOURCE_RECORDS_SQL), {"n": n})
    await session.execute(text(_SEED_SOURCE_ENTITY_HEADS_SQL), {"n": n})
    await session.execute(
        text(_SEED_SOURCE_LINKS_SQL),
        {"n": n, "uuid_namespace": uuid_namespace},
    )
    await session.execute(text("ANALYZE"))
