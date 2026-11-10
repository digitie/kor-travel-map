"""관리자 Feature 부분 검색의 계획·범위를 검증한다(#1444, #1475).

#1475: 부분 검색은 비부분 trigram 인덱스(rev 445)로 일치 후보를 먼저 모으고(드문 q),
후보가 상한을 넘으면 종전처럼 keyset 인덱스를 훑는다(흔한 q). 두 경로는 같은 행을 골라야
하고, 원천 JSON 본문(``raw_data::text``)은 어느 범위에서도 검색하지 않는다.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import admin_feature_repo
from kortravelmap.infra.admin_feature_repo import AdminFeatureSearchScope, list_admin_features
from tests.integration._feature_ids import feature_uuid
from tests.integration.test_admin_feature_repo import _seed_feature

pytestmark = pytest.mark.integration

#: rev 445가 만든 갈래별 trigram 인덱스. 후보 SQL의 술어 식이 인덱스 식과 어긋나면
#: (예: ``name`` 대 ``lower(name)``) 인덱스가 후보에서 빠지고 이 단언이 깨진다.
_ARM_INDEXES = {
    "features": {
        "idx_features_admin_lower_name_trgm",
        "idx_features_admin_feature_id_trgm",
        "idx_features_admin_address_trgm",
    },
    "feature_aliases": {"idx_feature_aliases_alias_trgm"},
    "source_entities": {"idx_source_entities_source_entity_id_trgm"},
    "source_entity_heads": {"idx_source_entity_heads_record_key_trgm"},
}


def _nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result = [plan]
    for child in plan.get("Plans", []):
        result.extend(_nodes(child))
    return result


async def _explain(
    session: AsyncSession, sql: str, params: dict[str, Any], *, analyze: bool = False
) -> dict[str, Any]:
    options = "ANALYZE, BUFFERS, FORMAT JSON" if analyze else "FORMAT JSON"
    result = await session.execute(text(f"EXPLAIN ({options}) {sql}"), params)
    plan: dict[str, Any] = result.scalar_one()[0]["Plan"]
    return plan


async def test_candidate_arms_use_admin_trigram_indexes(
    migrated_session: AsyncSession,
) -> None:
    """후보 SQL의 모든 갈래가 자기 표의 trigram 인덱스로 들어간다.

    seed가 작아 기본 planner는 Seq Scan을 고를 수 있으므로 seqscan을 끄고 **인덱스가
    후보인지**를 본다 — 술어 식과 인덱스 식이 어긋나면 seqscan을 꺼도 Seq Scan이 남는다.
    """
    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = await _explain(
        migrated_session,
        admin_feature_repo._admin_feature_candidates_sql("all"),
        {"q_like": "%관리자후보인덱스%", "q_candidate_limit": 8001},
    )
    nodes = _nodes(plan)
    for relation, expected in _ARM_INDEXES.items():
        used = {
            str(node["Index Name"])
            for node in nodes
            if node.get("Index Name") in expected
        }
        assert used == expected, (relation, sorted(used), plan)
    seq = [
        node["Relation Name"]
        for node in nodes
        if node.get("Node Type") in {"Seq Scan", "Parallel Seq Scan"}
        and node.get("Relation Name") in _ARM_INDEXES
    ]
    assert seq == [], plan
    # 원천 JSON 본문은 후보 단계에서 읽지 않는다.
    assert all(node.get("Relation Name") != "source_records" for node in nodes), plan


async def test_sparse_search_reads_no_raw_source_json(
    migrated_session: AsyncSession,
) -> None:
    for index in range(48):
        await _seed_feature(migrated_session, feature_uuid(f"admin-search-cost-{index}"))
    for scope in ("all", "feature"):
        statements = await _captured_statements(migrated_session, scope)
        # 후보 SQL + 본 질의. 일치가 없으니 후보 경로다(본 질의가 id 배열로 시작한다).
        assert len(statements) == 2, statements
        main_sql, main_params = statements[1]
        assert "ANY(" in main_sql, main_sql
        connection = await migrated_session.connection()
        result = await connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + main_sql, main_params
        )
        plan = result.scalar_one()[0]["Plan"]
        reads = [
            int(node.get("Actual Loops", 0))
            for node in _nodes(plan)
            if node.get("Relation Name") == "source_records"
            and node.get("Actual Loops", 0) > 0
        ]
        assert reads == [], (scope, plan)


async def _captured_statements(
    session: AsyncSession, search_scope: AdminFeatureSearchScope,
) -> list[tuple[str, Any]]:
    statements: list[tuple[str, Any]] = []

    def record(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append((statement, parameters))

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        page = await list_admin_features(
            session,
            q="관리자희소검색용비일치명칭",
            search_scope=search_scope,
            page_size=50,
        )
    finally:
        event.remove(bind, "before_cursor_execute", record)
    assert page.items == ()
    return statements


async def _seed_source_identifiers(
    session: AsyncSession, feature_id: str, *, entity_id: str, record_key: str
) -> None:
    """seed 원천의 entity id와 **현재** record key를 이름·주소·id와 겹치지 않게 바꾼다."""
    entity_key = f"se-sr-{feature_id}"
    await session.execute(
        text(
            "UPDATE provider_sync.source_entities SET source_entity_id = :entity_id "
            "WHERE source_entity_key = :entity_key"
        ),
        {"entity_id": entity_id, "entity_key": entity_key},
    )
    await session.execute(
        text(
            "INSERT INTO provider_sync.source_records "
            "(source_record_key, source_entity_key, raw_payload_hash, raw_data, "
            " fetched_at, imported_at) "
            "SELECT :record_key, source_entity_key, md5(:record_key), raw_data, "
            "       fetched_at, imported_at "
            "FROM provider_sync.source_records WHERE source_entity_key = :entity_key"
        ),
        {"record_key": record_key, "entity_key": entity_key},
    )
    await session.execute(
        text(
            "UPDATE provider_sync.source_entity_heads "
            "SET current_source_record_key = :record_key "
            "WHERE source_entity_key = :entity_key"
        ),
        {"record_key": record_key, "entity_key": entity_key},
    )


async def test_scopes_search_identifiers_but_not_raw_source_json(
    migrated_session: AsyncSession,
) -> None:
    feature_id = feature_uuid("admin-source-scope")
    await _seed_feature(
        migrated_session,
        feature_id,
        source_payload={"operator_note": "원천전용명칭"},
        name="관리자범위검색전용장소",
        road_address="관리자범위검색전용도로 43",
    )
    await _seed_source_identifiers(
        migrated_session,
        feature_id,
        entity_id="ext-entity-관리자원천식별자",
        record_key="rec-관리자현재레코드키",
    )
    # 원천 JSON 본문만 가진 말은 어느 범위·기본값에서도 찾히지 않는다(#1475).
    for scope in ("all", "feature", None):
        kwargs: dict[str, Any] = {} if scope is None else {"search_scope": scope}
        page = await list_admin_features(migrated_session, q="원천전용명칭", **kwargs)
        assert page.items == (), scope
    # 원천 식별자는 all(=기본값)에서만 찾힌다.
    for query in ("관리자원천식별자", "관리자현재레코드키"):
        for scope in ("all", None):
            kwargs = {} if scope is None else {"search_scope": scope}
            page = await list_admin_features(migrated_session, q=query, **kwargs)
            assert [item.feature_id for item in page.items] == [feature_id], (query, scope)
        bounded = await list_admin_features(
            migrated_session, q=query, search_scope="feature"
        )
        assert bounded.items == (), query
    for query in ("관리자범위검색전용장소", "관리자범위검색전용도로", feature_id[:13]):
        for scope in ("all", "feature"):
            page = await list_admin_features(
                migrated_session,
                q=query,
                search_scope=scope,  # type: ignore[arg-type]
            )
            assert [item.feature_id for item in page.items] == [feature_id], (query, scope)


@pytest.mark.parametrize("scope", ["all", "feature"])
async def test_candidate_and_scan_paths_return_the_same_rows(
    migrated_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scope: AdminFeatureSearchScope,
) -> None:
    """후보 경로와 훑기 경로는 비용만 다르고 고르는 행은 같다."""
    ids = {feature_uuid(f"admin-path-parity-{index}") for index in range(5)}
    for index, feature_id in enumerate(sorted(ids)):
        await _seed_feature(
            migrated_session,
            feature_id,
            name=f"관리자경로동등장소 {index % 2}",
            road_address=f"관리자경로동등도로 {index}",
        )
    other = feature_uuid("admin-path-parity-source")
    await _seed_feature(migrated_session, other, name="무관한이름")
    await _seed_source_identifiers(
        migrated_session, other, entity_id="ext-관리자경로동등", record_key="rec-x-1"
    )

    async def pages(cap: int) -> list[str]:
        monkeypatch.setattr(admin_feature_repo, "_ADMIN_FEATURES_Q_CANDIDATE_CAP", cap)
        seen: list[str] = []
        cursor: str | None = None
        while True:
            page = await list_admin_features(
                migrated_session,
                q="관리자경로동등",
                search_scope=scope,
                page_size=2,
                cursor=cursor,
            )
            seen.extend(item.feature_id for item in page.items)
            if page.next_cursor is None:
                return seen
            cursor = page.next_cursor

    via_candidates = await pages(2000)
    via_scan = await pages(0)
    assert via_candidates == via_scan
    expected = ids | ({other} if scope == "all" else set())
    assert len(via_candidates) == len(set(via_candidates)) == len(expected)
    assert set(via_candidates) == expected


async def test_short_query_skips_candidate_probe(
    migrated_session: AsyncSession,
) -> None:
    """세 글자 미만은 trigram을 뽑을 수 없어 후보를 모으지 않고 바로 훑는다."""
    feature_id = feature_uuid("admin-short-query")
    await _seed_feature(migrated_session, feature_id, name="짧은검색어장소")
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(args[2])

    bind = migrated_session.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        page = await list_admin_features(migrated_session, q="짧은", search_scope="feature")
    finally:
        event.remove(bind, "before_cursor_execute", record)
    assert feature_id in {item.feature_id for item in page.items}
    assert len(statements) == 1, statements


async def test_feature_scope_paginates_without_duplicates(
    migrated_session: AsyncSession,
) -> None:
    ids = {feature_uuid(f"admin-feature-scope-page-{index}") for index in range(3)}
    # 세 이름을 같게 유지해 cursor의 UUID tie-breaker도 검증한다.
    for feature_id in ids:
        await _seed_feature(
            migrated_session, feature_id, name="관리자페이지범위전용장소"
        )
    first = await list_admin_features(
        migrated_session,
        q="관리자페이지범위전용장소",
        search_scope="feature",
        page_size=2,
    )
    assert first.next_cursor is not None
    second = await list_admin_features(
        migrated_session,
        q="관리자페이지범위전용장소",
        search_scope="feature",
        page_size=2,
        cursor=first.next_cursor,
    )
    returned = [item.feature_id for item in (*first.items, *second.items)]
    assert len(returned) == len(set(returned)) == 3
    assert set(returned) == ids
