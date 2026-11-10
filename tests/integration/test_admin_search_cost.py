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
from kortravelmap.infra.models import SourceEntityHeadRow, SourceEntityRow
from tests.integration._feature_ids import feature_uuid
from tests.integration._subtype_seed import seed_feature_subtype
from tests.integration.test_admin_feature_repo import (
    _NOW,
    _feature_row,
    _provider_dataset_id,
    _seed_feature,
    _source_link,
    _source_record,
)

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


async def test_unmatched_search_takes_candidate_path_without_source_records(
    migrated_session: AsyncSession,
) -> None:
    for index in range(48):
        await _seed_feature(migrated_session, feature_uuid(f"admin-search-cost-{index}"))
    for scope in ("all", "feature"):
        statements = await _captured_statements(migrated_session, scope)
        # 후보 SQL + 본 질의. 일치가 없으니 후보 경로다(본 질의가 id 배열로 시작한다).
        assert len(statements) == 2, statements
        main_sql, main_params = statements[1]
        # driver 문장이라 bind 이름은 없다 — 후보 절의 모양으로 가린다.
        assert "AS uuid[]" in main_sql, main_sql
        assert "WITH base AS MATERIALIZED (" in main_sql, main_sql
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


async def _seed_with_source_identifiers(
    session: AsyncSession,
    feature_id: str,
    *,
    name: str,
    entity_id: str,
    record_key: str,
    road_address: str | None = None,
    raw_data: dict[str, Any] | None = None,
) -> None:
    """원천 entity id와 현재 record key가 이름·주소·id와 겹치지 않는 Feature 1건.

    ``_seed_feature``는 셋을 모두 ``sr-{feature_id}``로 둬서 원천 식별자 갈래만으로
    찾히는지를 가를 수 없다. entity identity는 갱신이 막혀 있으므로(트리거) 처음부터
    따로 심는다.
    """
    row = _feature_row(feature_id, name=name)
    if road_address is not None:
        row.address = {"road": road_address}
    session.add(row)
    await session.flush()
    await seed_feature_subtype(session, feature_id=feature_id, kind="place")
    entity_key = f"se-{record_key}"
    session.add(
        SourceEntityRow(
            source_entity_key=entity_key,
            provider_dataset_id=await _provider_dataset_id(session),
            source_entity_type="license_place",
            source_entity_id=entity_id,
            first_seen_at=_NOW,
            last_seen_at=_NOW,
        )
    )
    await session.flush()
    record = _source_record(record_key)
    if raw_data is not None:
        record.raw_data = raw_data
    session.add(record)
    await session.flush()
    session.add(
        SourceEntityHeadRow(
            source_entity_key=entity_key,
            current_source_record_key=record_key,
            observed_at=_NOW,
        )
    )
    await session.flush()
    session.add(_source_link(feature_id, record_key))
    await session.flush()


async def test_scopes_search_identifiers_but_not_raw_source_json(
    migrated_session: AsyncSession,
) -> None:
    feature_id = feature_uuid("admin-source-scope")
    await _seed_with_source_identifiers(
        migrated_session,
        feature_id,
        name="관리자범위검색전용장소",
        road_address="관리자범위검색전용도로 43",
        entity_id="ext-entity-관리자원천식별자",
        record_key="rec-관리자현재레코드키",
        raw_data={"operator_note": "원천전용명칭"},
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
    """후보 경로와 훑기 경로는 비용만 다르고 고르는 행은 같다 — 갈래마다 하나씩."""
    token = "pathparity7"

    def fid(label: str) -> str:
        return feature_uuid(f"admin-path-parity-{scope}-{label}")

    async def seed(label: str, **kwargs: Any) -> str:
        feature_id = fid(label)
        defaults: dict[str, Any] = {
            "name": f"무관한이름 {label}",
            "entity_id": f"ext-{scope}-{label}",
            "record_key": f"rec-{scope}-{label}",
        }
        await _seed_with_source_identifiers(
            migrated_session, feature_id, **{**defaults, **kwargs}
        )
        return feature_id

    by_name = await seed("name", name=f"{token} 이름")
    by_address = await seed("address", road_address=f"{token} 도로 1")
    by_entity = await seed("entity", entity_id=f"ext-{scope}-{token}-entity")
    by_record = await seed("record", record_key=f"rec-{scope}-{token}-key")
    by_many = await seed("many", name=f"{token} 여러갈래", road_address=f"{token} 도로 2")
    by_alias = await seed("alias")
    await migrated_session.execute(
        text(
            "INSERT INTO feature.feature_aliases (alias, feature_id, alias_kind) "
            "VALUES (:alias, CAST(:feature_id AS uuid), 'legacy_feature_id')"
        ),
        {"alias": f"f_{token}{scope}_p_0123456789abcdef", "feature_id": by_alias},
    )
    # head 없는 원천 entity는 종전 계획(head join)에서도 찾히지 않았다 — 두 경로 모두 뺀다.
    headless = fid("headless")
    migrated_session.add(_feature_row(headless, name="무관한이름 headless"))
    await migrated_session.flush()
    await seed_feature_subtype(migrated_session, feature_id=headless, kind="place")
    migrated_session.add(
        SourceEntityRow(
            source_entity_key=f"se-headless-{scope}",
            provider_dataset_id=await _provider_dataset_id(migrated_session),
            source_entity_type="license_place",
            source_entity_id=f"ext-{scope}-{token}-headless",
            first_seen_at=_NOW,
            last_seen_at=_NOW,
        )
    )
    await migrated_session.flush()
    migrated_session.add(_source_link(headless, f"headless-{scope}"))
    await migrated_session.flush()

    async def pages(cap: int) -> list[str]:
        monkeypatch.setattr(admin_feature_repo, "_ADMIN_FEATURES_Q_CANDIDATE_CAP", cap)
        seen: list[str] = []
        cursor: str | None = None
        while True:
            page = await list_admin_features(
                migrated_session,
                q=token,
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
    expected = {by_name, by_address, by_many, by_alias}
    if scope == "all":
        expected |= {by_entity, by_record}
    assert len(via_candidates) == len(set(via_candidates))
    # 같은 세션 DB에 앞선 테스트의 행이 남으므로 "내 것" 범위로 본다.
    mine = {by_name, by_address, by_entity, by_record, by_many, by_alias, headless}
    assert set(via_candidates) & mine == expected


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
