"""``list_admin_features`` 정렬·keyset 정합성 (키 단계 → 페이지 → 꾸밈 단계).

목록 SQL은 키 단계(``base``)에서 필터·정렬 키만 계산하고, 한 페이지를 자른 뒤에 대표
원천·이슈 같은 표시 값을 붙인다. ``provider`` 정렬의 키 단계는 대표 원천을 집합으로
(``DISTINCT ON``) 고르고 꾸밈 단계는 행마다 LATERAL로 고른다. 여기서는

* 모든 정렬·방향에서 한 행씩 넘긴 페이지의 합이 한 번에 읽은 목록과 같고(빠짐·겹침 없음),
* 정렬 키가 실제로 그 순서이며,
* 키 단계가 고른 대표 원천과 응답의 ``primary_provider``가 같은 행을 가리킨다는 것을

실 DB에서 고정한다. 대소문자만 다른 같은 이름(``GS25``/``gs25``)을 일부러 넣는다 — 종전
cursor는 원문 이름을 실어 ``lower(name)`` keyset과 비교해 이런 행을 빠뜨리거나(asc) 같은 행을
끝없이 되돌렸다(desc).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import md5
from typing import TYPE_CHECKING, Any

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import event, text

from kortravelmap.infra.admin_feature_repo import AdminFeatureRow, list_admin_features
from kortravelmap.infra.models import (
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)
from tests.integration._feature_ids import feature_uuid
from tests.integration._subtype_seed import seed_feature_subtype

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: 이 파일이 심는 행만 고르는 창 — 다른 seed와 섞이지 않게 updated_at을 미래 한 점에 둔다.
_WINDOW = datetime(2031, 1, 1, 0, 0, tzinfo=UTC)
_OBSERVED = datetime(2031, 1, 1, 0, 0, tzinfo=UTC)

_SORTS = ("name", "updated_at", "created_at", "kind", "provider", "issue_count")

#: (label, name, primary sources[(dataset 자리, observed 분)], open issue 수, 생성 분)
_SEED: tuple[tuple[str, str, tuple[tuple[int, int], ...], int, int], ...] = (
    ("gs25-a", "GS25 강남점", ((0, 0),), 0, 0),
    ("gs25-b", "GS25 강남점", ((1, 0),), 2, 1),
    ("gs25-c", "gs25 강남점", ((0, 0),), 1, 2),
    ("gs25-d", "Gs25 강남점", ((1, 0),), 0, 3),
    ("ga", "가람", ((0, 0),), 0, 4),
    ("na", "나루", ((1, 0),), 1, 5),
    # 대표 원천이 둘 — 나중에 관측된 쪽(dataset 1)이 대표다.
    ("two-primary", "다리", ((0, 0), (1, 30)), 0, 6),
    # 원천 연결이 없는 feature — provider 정렬 키는 ''.
    ("no-source", "마을", (), 0, 7),
)


async def _two_datasets(session: AsyncSession) -> tuple[int, int]:
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT ON (provider) provider_dataset_id
                FROM provider_sync.provider_datasets
                WHERE is_active
                ORDER BY provider, provider_dataset_id
                LIMIT 2
                """
            )
        )
    ).scalars().all()
    assert len(rows) == 2, "catalog에 활성 provider가 둘 이상 있어야 한다"
    return int(rows[0]), int(rows[1])


async def _seed(session: AsyncSession) -> dict[str, str]:
    datasets = await _two_datasets(session)
    ids: dict[str, str] = {}
    for label, name, sources, issues, created_minute in _SEED:
        feature_id = feature_uuid(f"admin-list-sort-{label}")
        ids[label] = feature_id
        session.add(
            FeatureRow(
                feature_id=feature_id,
                kind="place",
                name=name,
                category="01070300",
                coord=WKTElement("POINT(126.9769 37.5759)", srid=4326),
                address={"road": "서울특별시 종로구 세종대로 1"},
                urls={},
                raw_refs=[],
                lifecycle_state="active",
                publication_state="published",
                quality_state="valid",
                created_at=_WINDOW + timedelta(minutes=created_minute),
                updated_at=_WINDOW,
            )
        )
        await session.flush()
        await seed_feature_subtype(session, feature_id=feature_id, kind="place")
        for index, (slot, observed_minute) in enumerate(sources):
            key = f"admin-list-sort-{label}-{index}"
            session.add(
                SourceEntityRow(
                    source_entity_key=f"se-{key}",
                    provider_dataset_id=datasets[slot],
                    source_entity_type="license_place",
                    source_entity_id=key,
                    first_seen_at=_OBSERVED,
                    last_seen_at=_OBSERVED,
                )
            )
            await session.flush()
            session.add(
                SourceRecordRow(
                    source_record_key=key,
                    source_entity_key=f"se-{key}",
                    raw_payload_hash=md5(key.encode("utf-8")).hexdigest(),
                    raw_data={"id": key},
                    fetched_at=_OBSERVED,
                    imported_at=_OBSERVED,
                )
            )
            await session.flush()
            session.add(
                SourceEntityHeadRow(
                    source_entity_key=f"se-{key}",
                    current_source_record_key=key,
                    observed_at=_OBSERVED + timedelta(minutes=observed_minute),
                )
            )
            await session.flush()
            session.add(
                SourceLinkRow(
                    feature_id=feature_id,
                    source_entity_key=f"se-{key}",
                    source_role="primary",
                    match_method="natural_key",
                    confidence=100,
                    created_at=_OBSERVED,
                )
            )
            await session.flush()
        for issue_index in range(issues):
            await session.execute(
                text(
                    """
                    INSERT INTO ops.data_integrity_violations (
                        feature_id, violation_type, severity, message
                    ) VALUES (
                        CAST(:feature_id AS uuid), :violation_type, 'warning', '정렬 검증'
                    )
                    """
                ),
                {"feature_id": feature_id, "violation_type": f"sort_check_{issue_index}"},
            )
    await session.flush()
    return ids


async def _walk(
    session: AsyncSession, *, sort: str, order: str, page_size: int, **filters: Any
) -> list[AdminFeatureRow]:
    items: list[AdminFeatureRow] = []
    cursor: str | None = None
    for _ in range(len(_SEED) + 2):
        page = await list_admin_features(
            session,
            sort=sort,  # type: ignore[arg-type]
            order=order,  # type: ignore[arg-type]
            page_size=page_size,
            cursor=cursor,
            updated_from=_WINDOW,
            updated_to=_WINDOW,
            **filters,
        )
        items.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return items
    raise AssertionError(f"{sort} {order}: cursor가 끝나지 않는다 — 같은 페이지가 되돌아온다")


async def _db_rank(session: AsyncSession, values: list[str]) -> dict[str, int]:
    """DB 정렬(collation) 기준의 문자열 순위 — Python 정렬은 collation을 모른다."""

    ordered = (
        await session.execute(
            text("SELECT v FROM unnest(CAST(:values AS text[])) AS v ORDER BY v"),
            {"values": sorted(set(values))},
        )
    ).scalars().all()
    return {value: rank for rank, value in enumerate(ordered)}


async def _sort_key(session: AsyncSession, sort: str, items: list[AdminFeatureRow]) -> list[Any]:
    if sort == "name":
        lowered = [item.name.lower() for item in items]
        rank = await _db_rank(session, lowered)
        return [rank[value] for value in lowered]
    if sort == "provider":
        providers = [item.primary_provider or "" for item in items]
        rank = await _db_rank(session, providers)
        return [rank[value] for value in providers]
    if sort == "kind":
        return [item.kind for item in items]
    if sort == "issue_count":
        return [item.issue_count for item in items]
    return [getattr(item, sort) for item in items]


@pytest.mark.parametrize("order", ["asc", "desc"])
@pytest.mark.parametrize("sort", _SORTS)
async def test_admin_feature_pages_cover_the_list_in_sort_order(
    migrated_session: AsyncSession, sort: str, order: str
) -> None:
    await _seed(migrated_session)

    whole = await _walk(migrated_session, sort=sort, order=order, page_size=500)
    assert len(whole) == len(_SEED)
    for page_size in (1, 2, 3):
        paged = await _walk(migrated_session, sort=sort, order=order, page_size=page_size)
        assert [item.feature_id for item in paged] == [item.feature_id for item in whole], (
            f"{sort} {order} page_size={page_size}: 페이지를 넘기며 행이 빠지거나 겹쳤다"
        )

    keys = await _sort_key(migrated_session, sort, whole)
    pairs = [(key, item.feature_id) for key, item in zip(keys, whole, strict=True)]
    assert pairs == sorted(pairs, reverse=order == "desc"), f"{sort} {order}: 정렬 순서가 아니다"


async def test_admin_feature_provider_sort_key_matches_the_displayed_primary_source(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)
    first, second = await _two_datasets(migrated_session)
    providers = dict(
        (
            await migrated_session.execute(
                text(
                    "SELECT provider_dataset_id, provider FROM provider_sync.provider_datasets"
                    " WHERE provider_dataset_id = ANY(CAST(:ids AS bigint[]))"
                ),
                {"ids": [first, second]},
            )
        ).tuples().all()
    )

    by_id = {
        item.feature_id: item
        for item in await _walk(migrated_session, sort="provider", order="asc", page_size=2)
    }

    # 대표 원천이 둘이면 나중에 관측된 쪽이다 — 키 단계(집합 선택)와 응답(LATERAL)이 같다.
    assert by_id[ids["two-primary"]].primary_provider == providers[second]
    assert by_id[ids["no-source"]].primary_provider is None
    assert by_id[ids["ga"]].primary_provider == providers[first]

    # 같은 대표 원천 필터는 키 단계의 LATERAL로 거른다 — 집합 선택과 같은 행을 고른다.
    filtered = await _walk(
        migrated_session, sort="provider", order="asc", page_size=2, provider_dataset_id=second
    )
    assert {item.feature_id for item in filtered} == {
        ids["gs25-b"],
        ids["gs25-d"],
        ids["na"],
        ids["two-primary"],
    }
    by_name = await _walk(
        migrated_session, sort="name", order="asc", page_size=2, provider_dataset_id=second
    )
    assert {item.feature_id for item in by_name} == {item.feature_id for item in filtered}


def _plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


async def _analyzed_main_plan(
    session: AsyncSession, *, sort: str, page_size: int
) -> dict[str, Any]:
    statements: list[tuple[str, Any]] = []

    def record(
        connection: Any, cursor: Any, statement: str, parameters: Any, context: Any,
        executemany: bool,
    ) -> None:
        if "page AS (" in statement:
            statements.append((statement, parameters))

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        await list_admin_features(
            session,
            sort=sort,  # type: ignore[arg-type]
            order="desc",
            page_size=page_size,
            updated_from=_WINDOW,
            updated_to=_WINDOW,
        )
    finally:
        event.remove(bind, "before_cursor_execute", record)
    (main_sql, main_params), = statements
    connection = await session.connection()
    result = await connection.exec_driver_sql(
        "EXPLAIN (ANALYZE, FORMAT JSON) " + main_sql, main_params
    )
    plan: dict[str, Any] = result.scalar_one()[0]["Plan"]
    return plan


@pytest.mark.parametrize("sort", ["kind", "issue_count"])
async def test_admin_feature_display_values_are_read_for_page_rows_only(
    migrated_session: AsyncSession, sort: str
) -> None:
    """표시용 원천·이슈 조회는 한 페이지 행에만 돈다(키 단계는 정렬에 필요한 것만).

    종전 계획은 정렬 키가 인덱스를 못 타면 필터를 통과한 feature마다 대표 원천 LATERAL
    (원천 계보 다섯 표)과 이슈 jsonb 집계를 돌린 뒤에 top-N을 골랐다 — prod 43만 행에서
    유휴 12.7~18.6 s, I/O 부하 중 39 s.
    """
    await _seed(migrated_session)
    page_size = 2
    plan = await _analyzed_main_plan(migrated_session, sort=sort, page_size=page_size)

    nodes = _plan_nodes(plan)
    # 원천 계보 조회는 꾸밈 단계의 LATERAL뿐이고, 그 LATERAL은 페이지 행 수(limit + 1)만큼만
    # 시작한다 — 행마다 source_links를 한 번 찌른다(그 안쪽 표는 link 수만큼 돈다).
    # (``provider`` 정렬은 키 단계가 원천을 집합으로 고르므로 여기서 재지 않는다 — 작은 seed에서는
    # planner가 그 집합 선택을 index 조회로 풀어 loops가 행 수가 된다. 정합성은 위 시험이 본다.)
    link_loops = [
        int(node["Actual Loops"])
        for node in nodes
        if node.get("Relation Name") == "source_links"
    ]
    assert link_loops == [page_size + 1], (sort, link_loops, plan)
    # 이슈 본문 집계(jsonb_agg)도 페이지 행에만 — 키 단계의 건수 LATERAL은 issue_count 정렬일
    # 때만 feature마다 돈다.
    issue_loops = [
        int(node["Actual Loops"])
        for node in nodes
        if node.get("Relation Name") == "data_integrity_violations"
    ]
    if sort == "issue_count":
        assert max(issue_loops) == len(_SEED), (issue_loops, plan)
        assert min(issue_loops) <= page_size + 1, (issue_loops, plan)
    else:
        assert max(issue_loops) <= page_size + 1, (sort, issue_loops, plan)


async def test_admin_feature_issue_filters_use_the_same_open_issue_count(
    migrated_session: AsyncSession,
) -> None:
    ids = await _seed(migrated_session)

    with_issue = await _walk(
        migrated_session, sort="issue_count", order="desc", page_size=1, has_issue=True
    )
    assert [item.feature_id for item in with_issue][0] == ids["gs25-b"]
    assert {item.feature_id for item in with_issue} == {ids["gs25-b"], ids["gs25-c"], ids["na"]}
    assert all(item.issue_count == len(item.issues) for item in with_issue)

    without_issue = await _walk(
        migrated_session, sort="name", order="asc", page_size=2, has_issue=False
    )
    assert {item.feature_id for item in without_issue}.isdisjoint(
        {item.feature_id for item in with_issue}
    )
    assert len(without_issue) + len(with_issue) == len(_SEED)

    one_type = await _walk(
        migrated_session,
        sort="issue_count",
        order="desc",
        page_size=1,
        issue_types=["sort_check_1"],
    )
    assert one_type[0].feature_id == ids["gs25-b"]
    assert one_type[0].issue_count == 1
