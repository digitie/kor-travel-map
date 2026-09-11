"""T-VN-34B 공개 projection cache·ACL·partial index PostgreSQL 계약.

T-VN-39 재키(alembic 309) 뒤 ``feature.features.feature_id``와 subtype 5표의
``feature_id``가 uuid이고 사본 컬럼 ``feature_uuid``는 아홉 표에서 DROP됐다.
이 파일의 seed는 provider 적재 경로를 타지 않는 raw SQL이므로 정본 키를 스스로
발급한다 — 읽는 사람의 표찰은 ``name`` 열에 그대로 남기고, 그 표찰에서 유도한
canonical uuid를 키로 쓴다(:func:`tests.integration._feature_ids.feature_uuid`).
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration._feature_ids import feature_uuid

pytestmark = pytest.mark.integration

_PUBLIC_PREDICATE = (
    "lifecycle_state = 'active' AND publication_state = 'published' "
    "AND quality_state = 'valid'"
)

#: EXPLAIN 증명용 seed 규모. route/area는 그 뒤 두 자리를 이어 쓴다.
_PERF_ROW_COUNT = 25000
_PERF_ROUTE_ORDINAL = _PERF_ROW_COUNT + 1
_PERF_AREA_ORDINAL = _PERF_ROW_COUNT + 2

#: SQL이 같은 값을 만드는 식. Python과 두 벌이 되면 심은 행과 지우는 행이 갈라진다.
_PERF_FEATURE_ID_SQL = "CAST(CAST(:run AS text) || lpad(to_hex(g), 16, '0') AS uuid)"


def _perf_feature_id(run: str, ordinal: int) -> str:
    """run 표지(16 hex) + 일련번호(16 hex) = canonical uuid.

    재키(309) 뒤 ``feature_id``가 uuid라 ``LIKE 'prefix%'``로 seed를 쓸어 담을 수
    없다. 대신 SQL(:data:`_PERF_FEATURE_ID_SQL`)과 이 함수가 **같은 규칙**으로
    id를 유도해, 25 000행을 심을 때도 지울 때도 같은 집합을 가리키게 한다.
    """
    return str(UUID(f"{run}{ordinal:016x}"))


async def _insert_feature(
    session: AsyncSession,
    *,
    feature_id: str,
    name: str,
    kind: str,
    category: str,
    state: tuple[str, str, str] = ("active", "published", "valid"),
    coord: bool = False,
) -> None:
    """core 행 하나 — ``feature_id``는 정본 키(uuid), ``name``은 표찰이다.

    재키 전에는 두 슬롯이 **같은 바인드**였다(읽기 좋은 id를 이름으로도 썼다).
    uuid 컬럼과 varchar 컬럼에 같은 이름의 바인드를 쓰면 asyncpg 방언이 둘을 한
    ``$n``으로 접어 42P18(``uuid versus character varying``)로 선다 — 그래서
    바인드를 나눈다.
    """
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, lifecycle_state,
                publication_state, quality_state, coord
            ) VALUES (
                CAST(:feature_id AS uuid), :kind, :name, :category, :lifecycle_state,
                :publication_state, :quality_state,
                CASE WHEN :coord THEN x_extension.st_setsrid(
                    x_extension.st_makepoint(126.978, 37.5665), 4326
                ) END
            )
            """
        ),
        {
            "feature_id": feature_id,
            "name": name,
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
    """subtype 행 하나. 정본 키는 core에서 그대로 가져온다.

    309가 subtype 5표의 사본 컬럼 ``feature_uuid``와 그것을 보던 복합 FK를 함께
    없앴으므로 심을 identity는 ``feature_id`` 하나다.
    """
    if table == "feature_routes":
        await session.execute(
            text(
                """
                INSERT INTO feature.feature_routes (
                    feature_id, kind, geom, route_type, public_ready
                )
                SELECT feature_id, 'route',
                       x_extension.st_geomfromtext(
                           'MULTILINESTRING((126.97 37.56,126.98 37.57))', 4326
                       ),
                       'trail', false
                FROM feature.features
                WHERE feature_id = CAST(:feature_id AS uuid)
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
                    feature_id, kind, geom, area_kind, public_ready
                )
                SELECT feature_id, 'area',
                       x_extension.st_geomfromtext(
                           'MULTIPOLYGON(((126.97 37.56,126.98 37.56,126.98 37.57,126.97 37.56)))',
                           4326
                       ),
                       'boundary', false
                FROM feature.features
                WHERE feature_id = CAST(:feature_id AS uuid)
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
    label = f"tvn34b:{table}:{uuid4().hex}"
    feature_id = feature_uuid(label)
    await _insert_feature(
        migrated_session,
        feature_id=feature_id,
        name=label,
        kind=kind,
        category=category,
    )
    await _insert_subtype(migrated_session, table=table, feature_id=feature_id)

    assert await migrated_session.scalar(
        text(
            f"SELECT public_ready FROM feature.{table} "
            "WHERE feature_id = CAST(:feature_id AS uuid)"
        ),
        {"feature_id": feature_id},
    ) is True

    await migrated_session.execute(
        text(
            """
            UPDATE feature.features
            SET publication_state = 'suppressed'
            WHERE feature_id = CAST(:feature_id AS uuid)
            """
        ),
        {"feature_id": feature_id},
    )
    assert await migrated_session.scalar(
        text(
            f"SELECT public_ready FROM feature.{table} "
            "WHERE feature_id = CAST(:feature_id AS uuid)"
        ),
        {"feature_id": feature_id},
    ) is False

    # Even a privileged direct attempt cannot make the cache diverge: the
    # subtype BEFORE trigger recomputes it from the core state axes.
    await migrated_session.execute(
        text(
            f"UPDATE feature.{table} SET public_ready = true "
            "WHERE feature_id = CAST(:feature_id AS uuid)"
        ),
        {"feature_id": feature_id},
    )
    assert await migrated_session.scalar(
        text(
            f"SELECT public_ready FROM feature.{table} "
            "WHERE feature_id = CAST(:feature_id AS uuid)"
        ),
        {"feature_id": feature_id},
    ) is False

    # Subtype rows are 1:1 extensions of their core row, never attachments
    # that a generic UPDATE may retarget.  This is the lock-order boundary
    # that keeps ordinary subtype payload updates parent-lock-free.
    # 재부착 대상도 정본 키여야 관측이 성립한다 — 형식이 깨진 값이면 BEFORE
    # 트리거에 닿기 전 22P02로 죽어 "identity는 불변"이 아니라 "값이 uuid가
    # 아니다"를 증명하게 된다.
    with pytest.raises(DBAPIError) as caught:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    f"UPDATE feature.{table} "
                    "SET feature_id = CAST(:replacement AS uuid) "
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {
                    "feature_id": feature_id,
                    "replacement": feature_uuid(f"{label}:reattached"),
                },
            )
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"
    assert "route/area subtype identity is immutable" in str(caught.value.orig)


async def test_subtype_insert_waits_for_parent_state_lock_and_derives_fresh_flag(
    migrated_engine: AsyncEngine,
) -> None:
    """state update × subtype insert은 parent lock 순서로 stale flag 없이 직렬화된다."""
    label = f"tvn34b:interleave:{uuid4().hex}"
    feature_id = feature_uuid(label)
    async with AsyncSession(migrated_engine, expire_on_commit=False) as seed, seed.begin():
        await _insert_feature(
            seed,
            feature_id=feature_id,
            name=label,
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
                    "WHERE feature_id = CAST(:feature_id AS uuid) FOR UPDATE"
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
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
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
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": feature_id},
            ) is False
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM feature.features "
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
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

    label = f"tvn34b:deadlock:{table}:{uuid4().hex}"
    feature_id = feature_uuid(label)
    async with AsyncSession(migrated_engine, expire_on_commit=False) as seed, seed.begin():
        await _insert_feature(
            seed, feature_id=feature_id, name=label, kind=kind, category=category
        )
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
                        "WHERE feature_id = CAST(:feature_id AS uuid) FOR UPDATE"
                    ),
                    {"feature_id": feature_id},
                )

                subtype_update = asyncio.create_task(
                    subtype_session.execute(
                        text(
                            f"UPDATE feature.{table} "
                            "SET payload = jsonb_build_object('tvn34b_deadlock_probe', true) "
                            "WHERE feature_id = CAST(:feature_id AS uuid)"
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
                                CAST(:feature_id AS uuid),
                                'active', 'suppressed', 'valid', 1,
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
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": feature_id},
            )
            assert state.scalar_one() == "suppressed"
            assert await verify.scalar(
                text(
                    f"SELECT public_ready FROM feature.{table} "
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": feature_id},
            ) is False
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM feature.features "
                    "WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": feature_id},
            )


@pytest.mark.parametrize("table", ["feature_routes", "feature_areas"])
async def test_runtime_subtype_acl_excludes_public_ready(
    migrated_session: AsyncSession, table: str
) -> None:
    """Runtime에는 table UPDATE/flag UPDATE가 없고 business column만 허용한다.

    identity 축의 열거는 재키(309) 뒤 ``feature_id`` 하나다 — 사본 컬럼
    ``feature_uuid``가 subtype 5표에서 DROP됐으므로 그 열의 권한을 묻는 것은
    관측이 아니라 42703이다. 축이 줄어든 것이지 느슨해진 것이 아니다:
    ``table_update = False``가 열 단위 예외를 제외한 **모든** 열의 UPDATE를 이미
    막고, 남은 열 단위 단언은 그 예외 목록(geom만 허용)을 고정한다.
    """
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
        "kind_update": False,
    }
    # 사본 컬럼이 되살아나면 위 열거가 조용히 불완전해진다 — 그 자리를 이 단언이 지킨다.
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'feature' AND table_name = :table_name "
                "  AND column_name = 'feature_uuid'"
            ),
            {"table_name": table},
        )
    ) == 0

    label = f"tvn34b:acl:{table}:{uuid4().hex}"
    feature_id = feature_uuid(label)
    kind = "route" if table == "feature_routes" else "area"
    category = "06070000" if kind == "route" else "06050000"
    await _insert_feature(
        migrated_session,
        feature_id=feature_id,
        name=label,
        kind=kind,
        category=category,
    )
    await _insert_subtype(migrated_session, table=table, feature_id=feature_id)
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        with pytest.raises(DBAPIError) as caught:
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        f"UPDATE feature.{table} SET public_ready = false "
                        "WHERE feature_id = CAST(:feature_id AS uuid)"
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

    run = uuid4().hex[:16]
    try:
        await migrated_session.execute(
            text(
                f"""
                INSERT INTO feature.features (
                    feature_id, kind, name, category, coord, lifecycle_state,
                    publication_state, quality_state, updated_at
                )
                SELECT
                    {_PERF_FEATURE_ID_SQL}, 'place',
                    CASE WHEN g = 17 THEN 'tvn34 needle place' ELSE 'unrelated station' END,
                    CASE WHEN g = 17 THEN '06020001' ELSE '06020000' END,
                    x_extension.st_setsrid(
                        x_extension.st_makepoint(126.90 + g * 0.00001, 37.50 + g * 0.00001),
                        4326
                    ),
                    'active', 'published', 'valid', now() - (g || ' seconds')::interval
                FROM generate_series(1, CAST(:row_count AS integer)) AS g
                """
            ),
            {"run": run, "row_count": _PERF_ROW_COUNT},
        )
        route_id = _perf_feature_id(run, _PERF_ROUTE_ORDINAL)
        area_id = _perf_feature_id(run, _PERF_AREA_ORDINAL)
        await _insert_feature(
            migrated_session,
            feature_id=route_id,
            name=f"tvn34b:perf:{run}:route",
            kind="route",
            category="06070000",
        )
        await _insert_feature(
            migrated_session,
            feature_id=area_id,
            name=f"tvn34b:perf:{run}:area",
            kind="area",
            category="06050000",
        )
        await _insert_subtype(migrated_session, table="feature_routes", feature_id=route_id)
        await _insert_subtype(migrated_session, table="feature_areas", feature_id=area_id)
        await migrated_session.execute(text("ANALYZE feature.features"))
        await migrated_session.execute(text("ANALYZE feature.feature_routes"))
        await migrated_session.execute(text("ANALYZE feature.feature_areas"))
        # trgm 증명만 planner 기본값(seq scan 허용)으로 돌기 때문에, GIN의 쓰기
        # 버퍼가 그대로 비용에 섞이면 판정이 뒤집힌다. GIN은 fastupdate가 기본
        # ON이라 INSERT가 만든 항목이 본 트리가 아니라 pending list에 먼저 쌓이고,
        # `gincostestimate`는 그 pending list를 **모든** index scan 비용에 통째로
        # 더한다. 게다가 pending list는 rollback으로 되돌아가지 않는다 —
        # `migrated_engine` DB는 session scope라, 위 25 000행 seed가 남긴 109 page에
        # 다른 파일이 넣었다 되돌린 행의 항목까지 누적된다. 실측하면 그 잔여만으로
        # trgm 경로 비용이 250 → 1 360으로 부풀어 seq scan(1 363)을 넘고, planner가
        # Seq Scan을 고른다. 즉 partial index 술어가 틀려서가 아니라 아직 접히지
        # 않은 쓰기 버퍼를 인덱스 비용으로 청구당해서다.
        #
        # 운영에서는 autovacuum의 GIN cleanup이 이 버퍼를 접으므로 정상 상태는
        # flush된 쪽이고, 이 테스트가 증명하려는 것도 정상 상태의 접근 경로다.
        # 그래서 seed 직후 한 번 접어 그 상태를 재현한다 (통계를 맞추는 ANALYZE와
        # 같은 성격의 준비 단계다). 잔여를 본 트리로 옮겨도 실측 비용은 250 대로
        # 유지돼 판정 여유가 5배 이상으로 돌아온다.
        await migrated_session.execute(
            text(
                "SELECT pg_catalog.gin_clean_pending_list("
                "'feature.idx_features_name_trgm')"
            )
        )
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
        # uuid에는 LIKE가 없다 — seed와 같은 유도 규칙으로 같은 집합을 되짚는다
        # (route/area는 일련번호 뒤 두 자리라 이 한 문장이 셋을 다 데려간다).
        await migrated_session.execute(
            text(
                f"""
                DELETE FROM feature.features
                WHERE feature_id IN (
                    SELECT {_PERF_FEATURE_ID_SQL}
                    FROM generate_series(1, CAST(:last_ordinal AS integer)) AS g
                )
                """
            ),
            {"run": run, "last_ordinal": _PERF_AREA_ORDINAL},
        )
