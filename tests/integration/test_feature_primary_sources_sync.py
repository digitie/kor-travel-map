"""ADR-125 — 대표 원천 사본(``feature_primary_sources``)은 모든 쓰기와 같은 transaction에서 맞는다.

규칙의 정의는 view ``feature.feature_primary_source_rule`` 하나다(primary 연결 중 가장 먼저 붙은 것,
동률이면 ``source_entity_key COLLATE "C"``). 여기서는

* 연결 추가·역할 변경·삭제·Feature 사이 이동·같은 값 upsert·head 관측 갱신·Feature 생성·삭제마다
  사본이 규칙과 같고(정합성 검사 F10의 SQL로 잰다),
* data-modifying CTE 한 문장, replica 역할, 런타임 login으로 쓴 경우에도 같고,
* 같은 Feature의 서로 다른 연결을 두 transaction이 함께 바꿔도 뒤에 commit하는 쪽이 앞의 commit을
  보고 다시 계산하며(READ COMMITTED write skew 없음),
* migration 459의 따라잡기 SQL이 어긋난 사본(빠진 행·고아 행·틀린 값)을 규칙대로 되돌린다는 것을

실 DB에서 고정한다.
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from hashlib import md5
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import text

from kortravelmap.infra.models import (
    FeatureRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)
from kortravelmap.infra.primary_source import PRIMARY_SOURCE_DRIFT_SQL
from tests.integration._feature_ids import feature_uuid
from tests.integration._subtype_seed import seed_feature_subtype
from tests.integration.conftest import as_dagster_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_T0 = datetime(2031, 3, 1, 0, 0, tzinfo=UTC)

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "459_feature_primary_sources.py"
)
_SPEC = importlib.util.spec_from_file_location("migration_459", _MIGRATION_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MIGRATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)

_FEATURE_COLUMNS = (
    "feature_id, kind, name, category, address, urls, raw_refs, "
    "lifecycle_state, publication_state, quality_state, created_at, updated_at"
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


async def _add_feature(session: AsyncSession, label: str) -> str:
    feature_id = feature_uuid(f"primary-source-sync-{label}")
    session.add(
        FeatureRow(
            feature_id=feature_id,
            kind="place",
            name=f"대표 원천 {label}",
            category="01070300",
            coord=WKTElement("POINT(126.9769 37.5759)", srid=4326),
            address={"road": "서울특별시 종로구 세종대로 1"},
            urls={},
            raw_refs=[],
            lifecycle_state="active",
            publication_state="published",
            quality_state="valid",
            created_at=_T0,
            updated_at=_T0,
        )
    )
    await session.flush()
    await seed_feature_subtype(session, feature_id=feature_id, kind="place")
    return feature_id


async def _add_entity(session: AsyncSession, key: str, provider_dataset_id: int) -> str:
    """entity·record·head 한 벌(연결은 따로)."""

    entity_key = f"se-primary-source-{key}"
    session.add(
        SourceEntityRow(
            source_entity_key=entity_key,
            provider_dataset_id=provider_dataset_id,
            source_entity_type="license_place",
            source_entity_id=f"primary-source-{key}",
            first_seen_at=_T0,
            last_seen_at=_T0,
        )
    )
    await session.flush()
    session.add(
        SourceRecordRow(
            source_record_key=f"primary-source-{key}",
            source_entity_key=entity_key,
            raw_payload_hash=md5(key.encode("utf-8")).hexdigest(),
            raw_data={"id": key},
            fetched_at=_T0,
            imported_at=_T0,
        )
    )
    await session.flush()
    session.add(
        SourceEntityHeadRow(
            source_entity_key=entity_key,
            current_source_record_key=f"primary-source-{key}",
            observed_at=_T0,
        )
    )
    await session.flush()
    return entity_key


async def _link(
    session: AsyncSession, feature_id: str, entity_key: str, *, role: str, minute: int
) -> None:
    session.add(
        SourceLinkRow(
            feature_id=feature_id,
            source_entity_key=entity_key,
            source_role=role,
            match_method="natural_key",
            confidence=100,
            created_at=_T0 + timedelta(minutes=minute),
        )
    )
    await session.flush()


async def _stored(session: AsyncSession, feature_id: str) -> tuple[Any, ...] | None:
    row = (
        await session.execute(
            text(
                "SELECT source_entity_key, provider_dataset_id, provider "
                "FROM feature.feature_primary_sources WHERE feature_id = CAST(:id AS uuid)"
            ),
            {"id": feature_id},
        )
    ).one_or_none()
    return None if row is None else tuple(row)


async def _drift(session: AsyncSession, feature_ids: list[str]) -> list[str]:
    rows = (
        await session.execute(
            text(
                f"SELECT CAST(d.id AS text) FROM ({PRIMARY_SOURCE_DRIFT_SQL}) AS d "
                "WHERE d.id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": feature_ids},
        )
    ).scalars().all()
    return [str(value) for value in rows]


async def _provider(session: AsyncSession, provider_dataset_id: int) -> str:
    return str(
        (
            await session.execute(
                text(
                    "SELECT provider FROM provider_sync.provider_datasets "
                    "WHERE provider_dataset_id = :id"
                ),
                {"id": provider_dataset_id},
            )
        ).scalar_one()
    )


async def test_primary_source_follows_every_link_write(migrated_session: AsyncSession) -> None:
    session = migrated_session
    d0, d1 = await _two_datasets(session)
    p0, p1 = await _provider(session, d0), await _provider(session, d1)
    f = await _add_feature(session, "f")
    g = await _add_feature(session, "g")
    ids = [f, g]

    async def check(label: str, expected: dict[str, tuple[Any, ...] | None]) -> None:
        await session.flush()
        for feature_id, value in expected.items():
            assert await _stored(session, feature_id) == value, label
        assert await _drift(session, ids) == [], label

    # 새 Feature — 행은 있고 원천은 비어 있다.
    await check("insert feature", {f: (None, None, None), g: (None, None, None)})

    late = await _add_entity(session, "late", d1)
    early = await _add_entity(session, "early", d0)
    enrich = await _add_entity(session, "enrich", d1)
    await _link(session, f, late, role="primary", minute=10)
    await check("first primary", {f: (late, d1, p1)})
    await _link(session, f, early, role="primary", minute=0)
    await check("earlier primary wins", {f: (early, d0, p0)})
    await _link(session, f, enrich, role="enrichment", minute=-10)
    await check("enrichment never wins", {f: (early, d0, p0)})

    # 관측 시각은 규칙 밖이다 — 늦게 붙은 쪽이 더 최근에 관측돼도 그대로.
    await session.execute(
        text(
            "UPDATE provider_sync.source_entity_heads SET observed_at = :at "
            "WHERE source_entity_key = :key"
        ),
        {"at": _T0 + timedelta(days=30), "key": late},
    )
    await check("head observation", {f: (early, d0, p0)})

    # 같은 값 upsert(적재가 매번 하는 모양) — 바뀌는 것이 없다.
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method, confidence, created_at
            ) VALUES (CAST(:f AS uuid), :key, 'primary', 'natural_key', 90, :at)
            ON CONFLICT (feature_id, source_entity_key) DO UPDATE
            SET confidence = EXCLUDED.confidence
            """
        ),
        {"f": f, "key": early, "at": _T0},
    )
    await check("same-value upsert", {f: (early, d0, p0)})

    # 역할 변경 — 대표가 primary에서 빠지면 다음 것, 돌아오면 다시 그것.
    role_sql = (
        "UPDATE provider_sync.source_links SET source_role = :role "
        "WHERE feature_id = CAST(:f AS uuid) AND source_entity_key = :key"
    )
    await session.execute(text(role_sql), {"role": "enrichment", "f": f, "key": early})
    await check("demote representative", {f: (late, d1, p1)})
    await session.execute(text(role_sql), {"role": "primary", "f": f, "key": early})
    await check("promote back", {f: (early, d0, p0)})

    # 연결 시각이 바뀌면 순서도 바뀐다.
    await session.execute(
        text(
            "UPDATE provider_sync.source_links SET created_at = :at "
            "WHERE feature_id = CAST(:f AS uuid) AND source_entity_key = :key"
        ),
        {"at": _T0 - timedelta(minutes=5), "f": f, "key": late},
    )
    await check("created_at change", {f: (late, d1, p1)})

    await session.execute(
        text(
            "DELETE FROM provider_sync.source_links "
            "WHERE feature_id = CAST(:f AS uuid) AND source_entity_key = :key"
        ),
        {"f": f, "key": late},
    )
    await check("delete representative", {f: (early, d0, p0)})

    # 병합처럼 연결을 다른 Feature로 옮긴다 — 양쪽이 다시 계산된다.
    await session.execute(
        text(
            "UPDATE provider_sync.source_links SET feature_id = CAST(:g AS uuid) "
            "WHERE feature_id = CAST(:f AS uuid)"
        ),
        {"f": f, "g": g},
    )
    await check("move links", {f: (None, None, None), g: (early, d0, p0)})

    # Feature 삭제 — 연결은 FK cascade로, 사본 행은 Feature trigger로 사라진다.
    await session.execute(
        text("DELETE FROM feature.features WHERE feature_id = CAST(:g AS uuid)"), {"g": g}
    )
    await check("delete feature", {g: None})


async def test_feature_and_link_in_one_statement(migrated_session: AsyncSession) -> None:
    """data-modifying CTE 한 문장 — 두 trigger 중 무엇이 먼저 돌든 끝 상태가 같다."""

    session = migrated_session
    d0, _ = await _two_datasets(session)
    entity = await _add_entity(session, "cte", d0)
    feature_id = str(uuid4())
    await session.execute(
        text(
            f"""
            WITH new_feature AS (
                INSERT INTO feature.features ({_FEATURE_COLUMNS})
                VALUES (
                    CAST(:f AS uuid), 'place', '한 문장', '01070300', '{{}}'::jsonb,
                    '{{}}'::jsonb, '[]'::jsonb, 'active', 'draft', 'valid', :at, :at
                )
                RETURNING feature_id
            )
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method, confidence, created_at
            )
            SELECT new_feature.feature_id, :key, 'primary', 'natural_key', 100, :at
            FROM new_feature
            """
        ),
        {"f": feature_id, "key": entity, "at": _T0},
    )
    assert await _stored(session, feature_id) == (entity, d0, await _provider(session, d0))
    assert await _drift(session, [feature_id]) == []


async def test_replica_role_and_runtime_login_still_maintain_the_copy(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    d0, d1 = await _two_datasets(session)
    f = await _add_feature(session, "replica")
    first = await _add_entity(session, "replica-first", d0)
    second = await _add_entity(session, "replica-second", d1)

    # replica 역할(복구·정리 도구) — trigger가 ENABLE ALWAYS라 그대로 돈다.
    await session.execute(text("SET LOCAL session_replication_role = replica"))
    await _link(session, f, second, role="primary", minute=5)
    await session.execute(text("SET LOCAL session_replication_role = origin"))
    assert await _stored(session, f) == (second, d1, await _provider(session, d1))

    # 런타임 login은 사본 표에 쓰기 권한이 없다 — SECURITY DEFINER trigger가 쓴다.
    async with as_dagster_runtime(session) as runtime:
        await runtime.execute(
            text(
                """
                INSERT INTO provider_sync.source_links (
                    feature_id, source_entity_key, source_role, match_method, confidence,
                    created_at
                ) VALUES (CAST(:f AS uuid), :key, 'primary', 'natural_key', 100, :at)
                """
            ),
            {"f": f, "key": first, "at": _T0},
        )
        denied = await runtime.execute(
            text(
                "SELECT has_table_privilege('feature.feature_primary_sources', 'UPDATE')"
            )
        )
        assert denied.scalar_one() is False
    assert await _stored(session, f) == (first, d0, await _provider(session, d0))
    assert await _drift(session, [f]) == []


async def test_rule_view_pushes_the_feature_filter_into_the_link_scan(
    migrated_session: AsyncSession,
) -> None:
    """trigger의 재계산은 그 Feature들의 연결만 읽는다 — 규칙 view 전체를 계산하지 않는다."""

    result = await migrated_session.execute(
        text(
            "EXPLAIN (FORMAT JSON) SELECT * FROM feature.feature_primary_source_rule "
            "WHERE feature_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": [str(uuid4()), str(uuid4())]},
    )
    plan = result.scalar_one()[0]["Plan"]

    def nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
        found = [node]
        for child in node.get("Plans", []):
            found.extend(nodes(child))
        return found

    (link_scan,) = [n for n in nodes(plan) if n.get("Relation Name") == "source_links"]
    pushed = f"{link_scan.get('Index Cond', '')} {link_scan.get('Filter', '')}"
    assert "feature_id = ANY" in pushed, plan


async def test_catch_up_sql_repairs_a_drifted_copy(migrated_session: AsyncSession) -> None:
    """migration 459의 따라잡기 문장(조각 경계가 있든 없든)이 사본을 규칙으로 되돌린다."""

    session = migrated_session
    d0, d1 = await _two_datasets(session)
    a = await _add_feature(session, "drift-a")
    b = await _add_feature(session, "drift-b")
    c = await _add_feature(session, "drift-c")
    entity = await _add_entity(session, "drift", d0)
    await _link(session, a, entity, role="primary", minute=0)
    orphan = str(uuid4())
    # trigger를 거치지 않고 사본을 망가뜨린다(소유자 권한) — 틀린 값·빠진 행·고아 행.
    await session.execute(
        text(
            "UPDATE feature.feature_primary_sources "
            "SET source_entity_key = 'wrong', provider_dataset_id = :d, provider = 'wrong' "
            "WHERE feature_id = CAST(:a AS uuid)"
        ),
        {"d": d1, "a": a},
    )
    await session.execute(
        text("DELETE FROM feature.feature_primary_sources WHERE feature_id = CAST(:b AS uuid)"),
        {"b": b},
    )
    await session.execute(
        text("INSERT INTO feature.feature_primary_sources (feature_id) VALUES (CAST(:o AS uuid))"),
        {"o": orphan},
    )
    ids = [a, b, c, orphan]
    assert sorted(await _drift(session, ids)) == sorted([a, b, orphan])

    low, high = sorted([a, b, c, orphan])[1], sorted([a, b, c, orphan])[3]
    for lower, upper, params in (
        (False, True, {"lo": None, "hi": low}),
        (True, True, {"lo": low, "hi": high}),
        (True, False, {"lo": high, "hi": None}),
    ):
        for statement in _MIGRATION._catch_up_sql(lower, upper):
            await session.execute(text(statement), params)

    assert await _drift(session, ids) == []
    assert await _stored(session, a) == (entity, d0, await _provider(session, d0))
    assert await _stored(session, b) == (None, None, None)
    assert await _stored(session, orphan) is None


async def _commit_seed(engine: AsyncEngine, run: str) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        d0, d1 = await _two_datasets(session)
        feature_id = await _add_feature(session, f"race-{run}")
        old_rep = await _add_entity(session, f"race-{run}-old", d0)
        other = await _add_entity(session, f"race-{run}-other", d1)
        newest = await _add_entity(session, f"race-{run}-new", d1)
        await _link(session, feature_id, old_rep, role="primary", minute=0)
        await _link(session, feature_id, other, role="primary", minute=10)
    return {
        "feature_id": feature_id,
        "entities": [old_rep, other, newest],
        "old_rep": old_rep,
        "newest": newest,
        "d1": d1,
    }


async def _cleanup(engine: AsyncEngine, seed: dict[str, Any]) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM feature.features WHERE feature_id = CAST(:f AS uuid)"),
            {"f": seed["feature_id"]},
        )
        for table in ("source_entity_heads", "source_records", "source_entities"):
            await connection.execute(
                text(
                    f"DELETE FROM provider_sync.{table} "
                    "WHERE source_entity_key = ANY(CAST(:keys AS text[]))"
                ),
                {"keys": seed["entities"]},
            )


@pytest.mark.parametrize("first", ["delete", "insert"])
async def test_concurrent_link_writes_on_one_feature_serialize(
    migrated_engine: AsyncEngine, first: str
) -> None:
    """두 transaction이 같은 Feature의 다른 연결을 함께 바꾼다 — 끝 상태가 규칙과 같다.

    A는 대표 연결을 지우고(혼자 보면 대표 = ``other``), B는 더 먼저 붙은 새 연결을 넣는다(혼자
    보면 대표 = ``newest``). 각자 자기 snapshot으로만 계산하면 나중 commit이 상대의 변경을 모른 채
    덮는다. trigger는 사본 행을 먼저 잠그고 새 문장에서 계산하므로 뒤에 온 쪽이 기다렸다가 앞의
    commit을 보고 계산한다.
    """

    seed = await _commit_seed(migrated_engine, f"{first}-{uuid4().hex[:8]}")
    feature_id = seed["feature_id"]
    delete_sql = text(
        "DELETE FROM provider_sync.source_links "
        "WHERE feature_id = CAST(:f AS uuid) AND source_entity_key = :key"
    )
    insert_sql = text(
        """
        INSERT INTO provider_sync.source_links (
            feature_id, source_entity_key, source_role, match_method, confidence, created_at
        ) VALUES (CAST(:f AS uuid), :key, 'primary', 'natural_key', 100, :at)
        """
    )
    writes = {
        "delete": (delete_sql, {"f": feature_id, "key": seed["old_rep"]}),
        "insert": (
            insert_sql,
            {"f": feature_id, "key": seed["newest"], "at": _T0 - timedelta(minutes=10)},
        ),
    }
    second = "insert" if first == "delete" else "delete"
    try:
        async with migrated_engine.connect() as conn_a, migrated_engine.connect() as conn_b:
            await conn_a.begin()
            await conn_b.begin()
            await conn_a.execute(text("SET LOCAL lock_timeout = '20s'"))
            await conn_b.execute(text("SET LOCAL lock_timeout = '20s'"))
            await conn_a.execute(*writes[first])
            blocked = asyncio.create_task(conn_b.execute(*writes[second]))
            done, _ = await asyncio.wait({blocked}, timeout=1.0)
            assert not done, "뒤 transaction이 사본 행 잠금을 기다리지 않았다"
            await conn_a.commit()
            await blocked
            await conn_b.commit()

        async with migrated_engine.connect() as check:
            stored = (
                await check.execute(
                    text(
                        "SELECT source_entity_key FROM feature.feature_primary_sources "
                        "WHERE feature_id = CAST(:f AS uuid)"
                    ),
                    {"f": feature_id},
                )
            ).scalar_one()
            drift = (
                await check.execute(
                    text(
                        f"SELECT count(*) FROM ({PRIMARY_SOURCE_DRIFT_SQL}) AS d "
                        "WHERE d.id = CAST(:f AS uuid)"
                    ),
                    {"f": feature_id},
                )
            ).scalar_one()
        assert stored == seed["newest"]
        assert drift == 0
    finally:
        await _cleanup(migrated_engine, seed)
