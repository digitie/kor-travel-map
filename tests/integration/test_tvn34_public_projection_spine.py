"""T-VN-34B 공개 projection cache·ACL·partial index PostgreSQL 계약."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_PUBLIC_PREDICATE = (
    "lifecycle_state = 'active' AND publication_state = 'published' "
    "AND quality_state = 'valid'"
)


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    kind: str,
    category: str,
    state: tuple[str, str, str] = ("active", "published", "valid"),
    coord: bool = False,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, lifecycle_state,
                publication_state, quality_state, coord
            ) VALUES (
                :feature_id, :kind, :feature_id, :category, :lifecycle_state,
                :publication_state, :quality_state,
                CASE WHEN :coord THEN x_extension.st_setsrid(
                    x_extension.st_makepoint(126.978, 37.5665), 4326
                ) END
            )
            """
        ),
        {
            "feature_id": feature_id,
            "kind": kind,
            "category": category,
            "lifecycle_state": state[0],
            "publication_state": state[1],
            "quality_state": state[2],
            "coord": coord,
        },
    )


async def _insert_subtype(
    session: AsyncSession, *, table: str, feature_id: str
) -> None:
    if table == "feature_routes":
        await session.execute(
            text(
                """
                INSERT INTO feature.feature_routes (
                    feature_id, feature_uuid, kind, geom, route_type, public_ready
                )
                SELECT CAST(:feature_id AS varchar), feature_uuid, 'route',
                       x_extension.st_geomfromtext(
                           'MULTILINESTRING((126.97 37.56,126.98 37.57))', 4326
                       ),
                       'trail', false
                FROM feature.features
                WHERE feature_id = CAST(:feature_id AS varchar)
                """
            ),
            {"feature_id": feature_id},
        )
        return
    if table == "feature_areas":
        await session.execute(
            text(
                """
                INSERT INTO feature.feature_areas (
                    feature_id, feature_uuid, kind, geom, area_kind, public_ready
                )
                SELECT CAST(:feature_id AS varchar), feature_uuid, 'area',
                       x_extension.st_geomfromtext(
                           'MULTIPOLYGON(((126.97 37.56,126.98 37.56,126.98 37.57,126.97 37.56)))',
                           4326
                       ),
                       'boundary', false
                FROM feature.features
                WHERE feature_id = CAST(:feature_id AS varchar)
                """
            ),
            {"feature_id": feature_id},
        )
        return
    raise AssertionError(f"unexpected subtype table: {table}")


@pytest.mark.parametrize(
    ("table", "kind", "category"),
    [("feature_routes", "route", "06070000"), ("feature_areas", "area", "06050000")],
)
async def test_route_area_public_ready_is_trigger_owned_and_tracks_core_state(
    migrated_session: AsyncSession,
    table: str,
    kind: str,
    category: str,
) -> None:
    """Caller-supplied flag은 덮어쓰고 core 3축 변경이 cache를 동기화한다."""
    feature_id = f"tvn34b:{table}:{uuid4().hex}"
    await _insert_feature(
        migrated_session, feature_id=feature_id, kind=kind, category=category
    )
    await _insert_subtype(migrated_session, table=table, feature_id=feature_id)

    assert await migrated_session.scalar(
        text(f"SELECT public_ready FROM feature.{table} WHERE feature_id = :feature_id"),
        {"feature_id": feature_id},
    ) is True

    await migrated_session.execute(
        text(
            """
            UPDATE feature.features
            SET publication_state = 'suppressed'
            WHERE feature_id = :feature_id
            """
        ),
        {"feature_id": feature_id},
    )
    assert await migrated_session.scalar(
        text(f"SELECT public_ready FROM feature.{table} WHERE feature_id = :feature_id"),
        {"feature_id": feature_id},
    ) is False

    # Even a privileged direct attempt cannot make the cache diverge: the
    # subtype BEFORE trigger recomputes it from the core state axes.
    await migrated_session.execute(
        text(f"UPDATE feature.{table} SET public_ready = true WHERE feature_id = :feature_id"),
        {"feature_id": feature_id},
    )
    assert await migrated_session.scalar(
        text(f"SELECT public_ready FROM feature.{table} WHERE feature_id = :feature_id"),
        {"feature_id": feature_id},
    ) is False

    # Subtype rows are 1:1 extensions of their core row, never attachments
    # that a generic UPDATE may retarget.  This is the lock-order boundary
    # that keeps ordinary subtype payload updates parent-lock-free.
    with pytest.raises(DBAPIError) as caught:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    f"UPDATE feature.{table} SET feature_id = :replacement "
                    "WHERE feature_id = :feature_id"
                ),
                {
                    "feature_id": feature_id,
                    "replacement": f"{feature_id}:reattached",
                },
            )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"
    assert "route/area subtype identity is immutable" in str(caught.value.orig)


async def test_subtype_insert_waits_for_parent_state_lock_and_derives_fresh_flag(
    migrated_engine: AsyncEngine,
) -> None:
    """state update × subtype insert은 parent lock 순서로 stale flag 없이 직렬화된다."""
    feature_id = f"tvn34b:interleave:{uuid4().hex}"
    async with AsyncSession(migrated_engine, expire_on_commit=False) as seed, seed.begin():
        await _insert_feature(
            seed,
            feature_id=feature_id,
            kind="route",
            category="06070000",
        )

    try:
        async with (
            AsyncSession(migrated_engine, expire_on_commit=False) as state_session,
            AsyncSession(migrated_engine, expire_on_commit=False) as subtype_session,
        ):
            await state_session.begin()
            await subtype_session.begin()
            await state_session.execute(
                text(
                    "SELECT feature_id FROM feature.features "
                    "WHERE feature_id = :feature_id FOR UPDATE"
                ),
                {"feature_id": feature_id},
            )
            insert_task = asyncio.create_task(
                _insert_subtype(
                    subtype_session, table="feature_routes", feature_id=feature_id
                )
            )
            await asyncio.sleep(0.05)
            assert not insert_task.done(), "subtype trigger did not wait for parent row lock"
            await state_session.execute(
                text(
                    "UPDATE feature.features SET publication_state = 'suppressed' "
                    "WHERE feature_id = :feature_id"
                ),
                {"feature_id": feature_id},
            )
            await state_session.commit()
            await insert_task
            await subtype_session.commit()

        async with AsyncSession(migrated_engine, expire_on_commit=False) as verify:
            assert await verify.scalar(
                text(
                    "SELECT public_ready FROM feature.feature_routes "
                    "WHERE feature_id = :feature_id"
                ),
                {"feature_id": feature_id},
            ) is False
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM feature.features WHERE feature_id = :feature_id"),
                {"feature_id": feature_id},
            )


@pytest.mark.parametrize(
    ("table", "kind", "category"),
    [
        ("feature_routes", "route", "06070000"),
        ("feature_areas", "area", "06050000"),
    ],
)
async def test_subtype_update_and_state_transition_serialize_before_tuple_locks(
    migrated_engine: AsyncEngine,
    table: str,
    kind: str,
    category: str,
) -> None:
    """route/area UPDATE × state procedure은 40P01 없이 core→subtype으로 끝난다.

    state session이 parent tuple을 먼저 잡은 상태에서 subtype payload UPDATE를
    완료시킨 뒤, state transition이 subtype cache tuple을 기다리게 한다. 구 구현은
    subtype UPDATE가 parent를 다시 기다려 이 순서를 만들지 못했으며, transition을
    동시에 시작하면 parent ↔ subtype 역순 `40P01`으로 끝났다. 0096은 stable
    subtype UPDATE의 parent lock을 제거하고 identity reattachment를 금지한다.
    """

    feature_id = f"tvn34b:deadlock:{table}:{uuid4().hex}"
    async with AsyncSession(migrated_engine, expire_on_commit=False) as seed, seed.begin():
        await _insert_feature(seed, feature_id=feature_id, kind=kind, category=category)
        await _insert_subtype(seed, table=table, feature_id=feature_id)

    try:
        async with (
            AsyncSession(migrated_engine, expire_on_commit=False) as state_session,
            AsyncSession(migrated_engine, expire_on_commit=False) as subtype_session,
        ):
            await state_session.begin()
            await subtype_session.begin()
            try:
                await state_session.execute(text("SET LOCAL deadlock_timeout = '100ms'"))
                await subtype_session.execute(text("SET LOCAL deadlock_timeout = '100ms'"))
                await state_session.execute(
                    text(
                        "SELECT feature_id FROM feature.features "
                        "WHERE feature_id = :feature_id FOR UPDATE"
                    ),
                    {"feature_id": feature_id},
                )

                subtype_update = asyncio.create_task(
                    subtype_session.execute(
                        text(
                            f"UPDATE feature.{table} "
                            "SET payload = jsonb_build_object('tvn34b_deadlock_probe', true) "
                            "WHERE feature_id = :feature_id"
                        ),
                        {"feature_id": feature_id},
                    )
                )
                await asyncio.wait_for(subtype_update, timeout=3)

                state_transition = asyncio.create_task(
                    state_session.execute(
                        text(
                            """
                            CALL feature.transition_feature_state(
                                :feature_id, 'active', 'suppressed', 'valid', 1,
                                jsonb_build_object(
                                    'transition_kind', 'admin',
                                    'reason_code', 'tvn34b_deadlock_regression',
                                    'principal', 'admin:tvn34b-deadlock'
                                ),
                                NULL, NULL
                            )
                            """
                        ),
                        {"feature_id": feature_id},
                    )
                )
                await asyncio.sleep(0.05)
                assert not state_transition.done(), (
                    "state transition did not wait for the subtype cache row"
                )
                await subtype_session.commit()
                await asyncio.wait_for(state_transition, timeout=3)
                await state_session.commit()
            finally:
                if state_session.in_transaction():
                    await state_session.rollback()
                if subtype_session.in_transaction():
                    await subtype_session.rollback()

        async with AsyncSession(migrated_engine, expire_on_commit=False) as verify:
            state = await verify.execute(
                text(
                    "SELECT publication_state FROM feature.features "
                    "WHERE feature_id = :feature_id"
                ),
                {"feature_id": feature_id},
            )
            assert state.scalar_one() == "suppressed"
            assert await verify.scalar(
                text(f"SELECT public_ready FROM feature.{table} WHERE feature_id = :feature_id"),
                {"feature_id": feature_id},
            ) is False
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM feature.features WHERE feature_id = :feature_id"),
                {"feature_id": feature_id},
            )


@pytest.mark.parametrize("table", ["feature_routes", "feature_areas"])
async def test_runtime_subtype_acl_excludes_public_ready(
    migrated_session: AsyncSession, table: str
) -> None:
    """Runtime에는 table UPDATE/flag UPDATE가 없고 business column만 허용한다."""
    privileges = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    has_table_privilege('ktm_feature_runtime', :relation, 'UPDATE') AS table_update,
                    has_table_privilege('ktm_feature_runtime', :relation, 'DELETE') AS table_delete,
                    has_column_privilege(
                        'ktm_feature_runtime', :relation, 'public_ready', 'UPDATE'
                    ) AS flag_update,
                    has_column_privilege(
                        'ktm_feature_runtime', :relation, 'geom', 'UPDATE'
                    ) AS geom_update,
                    has_column_privilege(
                        'ktm_feature_runtime', :relation, 'feature_id', 'UPDATE'
                    ) AS feature_id_update,
                    has_column_privilege(
                        'ktm_feature_runtime', :relation, 'feature_uuid', 'UPDATE'
                    ) AS feature_uuid_update,
                    has_column_privilege(
                        'ktm_feature_runtime', :relation, 'kind', 'UPDATE'
                    ) AS kind_update
                """
            ),
            {"relation": f"feature.{table}"},
        )
    ).mappings().one()
    assert dict(privileges) == {
        "table_update": False,
        "table_delete": False,
        "flag_update": False,
        "geom_update": True,
        "feature_id_update": False,
        "feature_uuid_update": False,
        "kind_update": False,
    }

    feature_id = f"tvn34b:acl:{table}:{uuid4().hex}"
    kind = "route" if table == "feature_routes" else "area"
    category = "06070000" if kind == "route" else "06050000"
    await _insert_feature(
        migrated_session, feature_id=feature_id, kind=kind, category=category
    )
    await _insert_subtype(migrated_session, table=table, feature_id=feature_id)
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        with pytest.raises(DBAPIError) as caught:
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        f"UPDATE feature.{table} SET public_ready = false "
                        "WHERE feature_id = :feature_id"
                    ),
                    {"feature_id": feature_id},
                )
        assert getattr(caught.value.orig, "sqlstate", None) == "42501"
    finally:
        await migrated_session.execute(text("RESET ROLE"))


async def test_public_partial_indexes_have_exact_state_predicate_and_explain_proof(
    migrated_session: AsyncSession,
) -> None:
    """point/category/key/text 및 route/area GiST가 3축/ready partial index를 쓴다."""
    definitions = {
        row.indexname: row.indexdef
        for row in (
            await migrated_session.execute(
                text(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'feature'
                      AND indexname = ANY(:index_names)
                    """
                ),
                {
                    "index_names": [
                        "idx_features_coord_gist",
                        "idx_features_kind_category",
                        "idx_features_updated_keyset",
                        "idx_features_lower_name_keyset",
                        "idx_features_name_trgm",
                        "idx_feature_routes_geom_gist",
                        "idx_feature_areas_geom_gist",
                    ]
                },
            )
        ).mappings()
    }
    core_indexes = (
        "idx_features_coord_gist",
        "idx_features_kind_category",
        "idx_features_updated_keyset",
        "idx_features_lower_name_keyset",
        "idx_features_name_trgm",
    )
    for name in core_indexes:
        definition = definitions[name]
        for fragment in ("lifecycle_state", "publication_state", "quality_state"):
            assert fragment in definition, (name, definition)
        assert "deleted_at" not in definition, definition
        assert "status" not in definition, definition
    for name in ("idx_feature_routes_geom_gist", "idx_feature_areas_geom_gist"):
        assert "WHERE public_ready" in definitions[name], definitions[name]

    prefix = f"tvn34b:perf:{uuid4().hex}:"
    try:
        await migrated_session.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, coord, lifecycle_state,
                    publication_state, quality_state, updated_at
                )
                SELECT
                    :prefix || g::text, 'place',
                    CASE WHEN g = 17 THEN 'tvn34 needle place' ELSE 'unrelated station' END,
                    CASE WHEN g = 17 THEN '06020001' ELSE '06020000' END,
                    x_extension.st_setsrid(
                        x_extension.st_makepoint(126.90 + g * 0.00001, 37.50 + g * 0.00001),
                        4326
                    ),
                    'active', 'published', 'valid', now() - (g || ' seconds')::interval
                FROM generate_series(1, 25000) AS g
                """
            ),
            {"prefix": prefix},
        )
        route_id = f"{prefix}route"
        area_id = f"{prefix}area"
        await _insert_feature(
            migrated_session, feature_id=route_id, kind="route", category="06070000"
        )
        await _insert_feature(
            migrated_session, feature_id=area_id, kind="area", category="06050000"
        )
        await _insert_subtype(migrated_session, table="feature_routes", feature_id=route_id)
        await _insert_subtype(migrated_session, table="feature_areas", feature_id=area_id)
        await migrated_session.execute(text("ANALYZE feature.features"))
        await migrated_session.execute(text("ANALYZE feature.feature_routes"))
        await migrated_session.execute(text("ANALYZE feature.feature_areas"))
        queries: tuple[tuple[str, str], ...] = (
            (
                "idx_features_coord_gist",
                """
                SELECT feature_id FROM feature.features
                WHERE lifecycle_state = 'active' AND publication_state = 'published'
                  AND quality_state = 'valid'
                  AND coord OPERATOR(x_extension.&&) x_extension.st_makeenvelope(
                      126.975, 37.565, 126.979, 37.569, 4326
                  )
                """,
            ),
            (
                "idx_features_kind_category",
                """
                SELECT feature_id FROM feature.features
                WHERE lifecycle_state = 'active' AND publication_state = 'published'
                  AND quality_state = 'valid' AND kind = 'place' AND category = '06020001'
                """,
            ),
            (
                "idx_features_updated_keyset",
                """
                SELECT feature_id FROM feature.features
                WHERE lifecycle_state = 'active' AND publication_state = 'published'
                  AND quality_state = 'valid'
                ORDER BY updated_at DESC, feature_id DESC LIMIT 25
                """,
            ),
            (
                "idx_features_lower_name_keyset",
                """
                SELECT feature_id FROM feature.features
                WHERE lifecycle_state = 'active' AND publication_state = 'published'
                  AND quality_state = 'valid' AND lower(name) = 'tvn34 needle place'
                ORDER BY feature_id LIMIT 25
                """,
            ),
            (
                "idx_features_name_trgm",
                """
                SELECT feature_id FROM feature.features
                WHERE lifecycle_state = 'active' AND publication_state = 'published'
                  AND quality_state = 'valid'
                  AND name OPERATOR(x_extension.%) 'tvn34 needle place'
                """,
            ),
            (
                "idx_feature_routes_geom_gist",
                """
                SELECT feature_id FROM feature.feature_routes
                WHERE public_ready
                  AND geom OPERATOR(x_extension.&&) x_extension.st_makeenvelope(
                      126.96, 37.55, 126.99, 37.58, 4326
                  )
                """,
            ),
            (
                "idx_feature_areas_geom_gist",
                """
                SELECT feature_id FROM feature.feature_areas
                WHERE public_ready
                  AND geom OPERATOR(x_extension.&&) x_extension.st_makeenvelope(
                      126.96, 37.55, 126.99, 37.58, 4326
                  )
                """,
            ),
        )
        for index_name, query in queries:
            # The normal planner must select the selective trgm GIN path.  A
            # forced no-seq-scan setting can prefer an unrelated full btree
            # partial-index walk solely because every state axis is public.
            planner_default = index_name == "idx_features_name_trgm"
            await migrated_session.execute(
                text(
                    "SET LOCAL enable_seqscan = "
                    + ("on" if planner_default else "off")
                )
            )
            plan = "\n".join(
                row[0]
                for row in await migrated_session.execute(
                    text(f"EXPLAIN (ANALYZE, BUFFERS) {query}")
                )
            )
            assert index_name in plan, (index_name, plan)
    finally:
        await migrated_session.execute(
            text("DELETE FROM feature.features WHERE feature_id LIKE :prefix"),
            {"prefix": f"{prefix}%"},
        )
