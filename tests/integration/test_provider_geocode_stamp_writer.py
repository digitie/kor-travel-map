"""legacy stamp SD writer(`feature.upsert_provider_geocode_stamps_ex`)의 권한·원자성·FK 경계.

ADR-117(alembic 435)이 이 함수를 **남기고** epoch·활성 정책 검사만 뺐다. 종전 시험
(`test_scoped_provider_geocode_stamps.py`)은 scoped(SH) stamp와 legacy 사례를 한 파일에 담았는데,
scoped 경로를 지우면서 legacy 사례를 이 파일로 옮겼다(내용은 그대로, SH gate 변형만 뺐다).
collector 배선 시험은 아니다.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto.geo_dataset import DatasetRef
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.feature_geocode_stamp_repo import upsert_stamps
from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges_in_transaction
from tests.integration._owned_pg import (
    scalar_container as scalar_container,
)
from tests.integration._owned_pg import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_feature_geocode_stamps import _feature

pytestmark = pytest.mark.integration
_A = DatasetRef(version_token="dv1-" + "a" * 32, data_token="dd1-" + "a" * 32)
_B = DatasetRef(version_token="dv1-" + "b" * 32, data_token="dd1-" + "b" * 32)


async def _read(admin, sql, params=None):
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout='3s'"))
        await session.execute(text("SET LOCAL lock_timeout='1s'"))
        return (await session.execute(text(sql), params or {})).mappings().all()


async def _stamps(admin, ids):
    return await _read(
        admin,
        """SELECT feature_id::text,geo_version_token,geo_data_token,reverse_outcome,stamped_at
        FROM feature.feature_geocode_stamps
        WHERE feature_id=ANY(CAST(:ids AS uuid[])) ORDER BY feature_id""",
        {"ids": ids},
    )


async def _nonactive_features(admin, count):
    # 실제 legacy public stamp는 canonical source를 요구하지 않는다.
    # 이 admin setup은 ACL/legacy 동등성용이며 SH/collector seed라고 주장하지 않는다.
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        return [await _feature(session) for _ in range(count)]


@pytest.fixture
async def boundary(scalar_engines, scalar_container, request):
    admin, source_runtime = scalar_engines
    wrapped = scalar_container.get_wrapped_container()
    wrapped.reload()
    attrs = wrapped.attrs
    label = attrs["Config"]["Labels"]["codex.scalar-projection"]
    assert attrs["Name"] == "/kt-map-scalar-" + label
    assert attrs["HostConfig"]["NanoCpus"] == 2_000_000_000
    assert attrs["HostConfig"]["Memory"] == attrs["HostConfig"]["MemorySwap"] == 1536 * 1024**2
    assert attrs["HostConfig"]["PidsLimit"] == 256
    request.node.user_properties.extend(
        [
            ("owned_pg_id", attrs["Id"]),
            ("owned_pg_name", attrs["Name"]),
            ("owned_pg_label", label),
            ("owned_pg_image_id", attrs["Image"]),
        ]
    )
    runtime = make_async_engine(
        source_runtime.url.render_as_string(hide_password=False), pool_size=1, max_overflow=0
    )
    try:
        async with AsyncSession(runtime) as session:
            assert tuple(
                (await session.execute(text("SELECT session_user,current_user"))).one()
            ) == ("ktm_feature_service", "ktm_feature_service")
        yield admin, runtime
    finally:
        await runtime.dispose()
        rows = await _read(
            admin,
            """SELECT count(*) AS count FROM pg_stat_activity
            WHERE datname=current_database() AND usename=:role""",
            {"role": runtime.url.username},
        )
        assert rows[0]["count"] == 0
        request.node.user_properties.append(("runtime_backend_count_after_dispose", 0))


@pytest.mark.parametrize("gate", [None, True], ids=["no-gate", "exclusive"])
@pytest.mark.parametrize("operation", ["insert", "update", "delete", "truncate", "for_update"])
async def test_direct_runtime_stamp_dml_is_denied_even_with_protocol(boundary, gate, operation):
    admin, runtime = boundary
    ids = await _nonactive_features(admin, 1)
    before = await _stamps(admin, ids)
    statements = {
        "insert": """INSERT INTO feature.feature_geocode_stamps(
            feature_id,geo_version_token,geo_data_token,reverse_outcome)
            VALUES(CAST(:id AS uuid),:version,:data,'called')""",
        "update": "UPDATE feature.feature_geocode_stamps SET stamped_at=now() WHERE false",
        "delete": "DELETE FROM feature.feature_geocode_stamps WHERE false",
        "truncate": "TRUNCATE feature.feature_geocode_stamps",
        "for_update": "SELECT * FROM feature.feature_geocode_stamps WHERE false FOR UPDATE",
    }

    async def denied_statement():
        async with AsyncSession(runtime) as session, session.begin():
            if gate is not None:
                await session.execute(
                    text("SELECT ops.lock_scoped_feature_write_protocol(:exclusive)"),
                    {"exclusive": gate},
                )
            # custom GUC는 권한 증명이 될 수 없다.
            await session.execute(text("SET LOCAL codex.stamp_writer_authorized='true'"))
            await session.execute(
                text(statements[operation]),
                {"id": ids[0], "version": _A.version_token, "data": _A.data_token},
            )

    with pytest.raises(DBAPIError) as caught:
        await denied_statement()
    assert caught.value.orig.sqlstate == "42501"
    assert await _stamps(admin, ids) == before
    assert runtime.pool.checkedout() == 0


async def test_stamp_acl_reconcile_and_explicit_migrator_role_are_distinct(boundary):
    admin, runtime = boundary
    create_sql = """SELECT has_schema_privilege('ktm_feature_state_procedure_owner',
        'feature','CREATE') AS can_create"""
    create_before = await _read(admin, create_sql)
    for _ in range(2):
        # 정본 reconcile은 끝에 schemaowner를 남긴다.
        # 이 setup engine을 runtime pool과 공유하지 않는다.
        setup = make_async_engine(runtime.url.render_as_string(hide_password=False), pool_size=1)
        try:
            async with setup.begin() as connection:
                await reconcile_runtime_privileges_in_transaction(connection)
        finally:
            await setup.dispose()
    async with AsyncSession(runtime) as session, session.begin():
        row = (
            (
                await session.execute(
                    text("""SELECT
            has_table_privilege(current_user,'feature.feature_geocode_stamps','SELECT') AS can_read,
            has_table_privilege(current_user,'feature.feature_geocode_stamps','INSERT')
                AS can_insert,
            has_table_privilege(current_user,'feature.feature_geocode_stamps','UPDATE')
                AS can_update,
            has_table_privilege(current_user,'feature.feature_geocode_stamps','DELETE')
                AS can_delete,
            pg_has_role(session_user,'ktm_feature_schema_owner','USAGE') AS inherits_owner,
            pg_has_role(session_user,'ktm_feature_schema_owner','SET') AS can_migrate
        """)
                )
            )
            .mappings()
            .one()
        )
        assert dict(row) == dict(
            can_read=True,
            can_insert=False,
            can_update=False,
            can_delete=False,
            inherits_owner=False,
            can_migrate=True,
        )
        await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
        assert await session.scalar(text("SELECT current_user")) == "ktm_feature_schema_owner"
        await session.execute(text("RESET ROLE"))
        assert await session.scalar(text("SELECT current_user")) == "ktm_feature_service"
    async with AsyncSession(runtime) as session:
        assert await session.scalar(text("SELECT current_user")) == "ktm_feature_service"
    rows = await _read(
        admin,
        """SELECT p.proname,r.rolname,p.prosecdef,p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_roles r ON r.oid=p.proowner
        WHERE n.nspname='feature' AND p.proname=ANY(CAST(:names AS text[])) ORDER BY p.proname""",
        {"names": ["upsert_provider_geocode_stamps_ex"]},
    )
    assert len(rows) == 1
    assert all(row["rolname"] == "ktm_feature_state_procedure_owner" for row in rows)
    assert all(row["prosecdef"] is True for row in rows)
    assert all("search_path=pg_catalog" in row["proconfig"] for row in rows)

    async with AsyncSession(runtime) as session:
        allowed = (
            (
                await session.execute(
                    text("""SELECT p.proname,
            has_function_privilege(current_user,p.oid,'EXECUTE') AS runtime_execute,
            EXISTS(SELECT 1 FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
                WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='feature' AND p.proname=ANY(CAST(:names AS text[]))"""),
                    {"names": [row["proname"] for row in rows]},
                )
            )
            .mappings()
            .all()
        )
        assert len(allowed) == 1
        assert all(row["public_execute"] is False for row in allowed)
        assert all(
            row["runtime_execute"] is (not row["proname"].startswith("_")) for row in allowed
        )
    # 임의 False를 가정하지 않고 정본으로 부여된 기존 ACL을 reconcile이 보존함을 확인한다.
    assert await _read(admin, create_sql) == create_before


async def test_legacy_none_empty_remains_zero_sql(boundary):
    _, runtime = boundary
    statements = []

    def count(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(runtime.sync_engine, "before_cursor_execute", count)
    try:
        async with AsyncSession(runtime) as session:
            assert (
                await upsert_stamps(session, current=None, outcomes={str(uuid4()): "called"}) == 0
            )
            assert (
                await upsert_stamps(
                    session,
                    current=DatasetRef(version_token=_A.version_token),
                    outcomes={str(uuid4()): "called"},
                )
                == 0
            )
            assert await upsert_stamps(session, current=_A, outcomes={}) == 0
        assert statements == []
    finally:
        event.remove(runtime.sync_engine, "before_cursor_execute", count)


@pytest.mark.parametrize("count", [1, 2731])
async def test_legacy_all_items_same_transaction_clock_and_rollback(boundary, count, request):
    admin, runtime = boundary
    ids = await _nonactive_features(admin, count)
    features_before = await _read(
        admin,
        "SELECT feature_id::text,row_revision FROM feature.features "
        "WHERE feature_id=ANY(CAST(:ids AS uuid[])) ORDER BY feature_id",
        {"ids": ids},
    )
    async with AsyncSession(runtime) as session, session.begin():
        clock = await session.scalar(text("SELECT transaction_timestamp()"))
        assert (
            await upsert_stamps(session, current=_A, outcomes=dict.fromkeys(ids, "called")) == count
        )
        assert (
            await upsert_stamps(session, current=_B, outcomes=dict.fromkeys(ids, "geocoded"))
            == count
        )
    rows = await _stamps(admin, ids)
    assert len(rows) == count
    assert all(
        (r["geo_version_token"], r["geo_data_token"], r["reverse_outcome"], r["stamped_at"])
        == (_B.version_token, _B.data_token, "geocoded", clock)
        for r in rows
    )
    assert (
        await _read(
            admin,
            "SELECT feature_id::text,row_revision FROM feature.features "
            "WHERE feature_id=ANY(CAST(:ids AS uuid[])) ORDER BY feature_id",
            {"ids": ids},
        )
        == features_before
    )

    async def rollback_after_actual_write():
        async with AsyncSession(runtime) as session, session.begin():
            assert (
                await upsert_stamps(session, current=_A, outcomes=dict.fromkeys(ids, "called"))
                == count
            )
            raise RuntimeError("owned legacy rollback")

    with pytest.raises(RuntimeError, match="owned legacy rollback"):
        await rollback_after_actual_write()
    assert await _stamps(admin, ids) == rows
    request.node.user_properties.append(("legacy_complete_count", count))


async def _wait_blocker(admin, waiter_pid, holder_pid):
    for _ in range(100):
        rows = await _read(
            admin, "SELECT pg_blocking_pids(:waiter) AS blockers", {"waiter": waiter_pid}
        )
        if holder_pid in rows[0]["blockers"]:
            return
        await asyncio.sleep(0.02)
    pytest.fail("owned waiter did not block on exact owned protocol holder")



async def test_stamp_foreign_key_cascade_for_nonactive_feature_is_preserved(boundary):
    admin, runtime = boundary
    ids = await _nonactive_features(admin, 1)
    async with AsyncSession(runtime) as session, session.begin():
        assert await upsert_stamps(session, current=_A, outcomes={ids[0]: "called"}) == 1
    assert len(await _stamps(admin, ids)) == 1
    # 명시 관리 경계: runtime DELETE 권한을 추가하지 않고 기존 FK cascade만 관측한다.
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await session.execute(
            text("DELETE FROM feature.features WHERE feature_id=CAST(:id AS uuid)"), {"id": ids[0]}
        )
    assert await _stamps(admin, ids) == []


@pytest.fixture(scope="module")
def fk_container():
    # 기존44가 설치한 module-local cutover와 분리된 새 OFF lab만 사용한다.
    generator = scalar_container.__wrapped__()
    try:
        yield next(generator)
    finally:
        generator.close()


@pytest.fixture(scope="module")
async def fk_engines(fk_container):
    generator = scalar_engines.__wrapped__(fk_container)
    try:
        yield await anext(generator)
    finally:
        await generator.aclose()


@pytest.fixture
async def fk_boundary(fk_engines, fk_container, request):
    # 자원/현재역할/backend0 경계는 기존44와 동일한 실제 fixture를 재사용한다.
    generator = boundary.__wrapped__(fk_engines, fk_container, request)
    try:
        pair = await anext(generator)
        admin, _ = pair
        # 435(ADR-117) 뒤에는 정책 활성화 표 자체가 없다.
        assert (
            await _read(
                admin,
                "SELECT to_regclass('feature.provider_field_active_policies') IS NULL AS absent",
            )
        )[0]["absent"] is True
        assert (
            await _read(
                admin,
                "SELECT count(*) AS count FROM pg_trigger "
                "WHERE tgname LIKE 'trg_scalar_%' AND NOT tgisinternal",
            )
        )[0]["count"] == 0
        request.node.user_properties.append(
            ("fk_scope", "fresh legacy-only lab")
        )
        yield pair
    finally:
        await generator.aclose()


async def test_legacy_missing_feature_fk_rejects_entire_batch(fk_boundary):
    admin, runtime = fk_boundary
    ids = await _nonactive_features(admin, 1)
    missing = str(uuid4())

    async def insert():
        async with AsyncSession(runtime) as session, session.begin():
            await upsert_stamps(
                session, current=_A, outcomes={ids[0]: "called", missing: "geocoded"}
            )

    with pytest.raises(DBAPIError) as caught:
        await insert()
    assert caught.value.orig.sqlstate == "23503"
    assert await _stamps(admin, ids + [missing]) == []
    assert runtime.pool.checkedout() == 0


@pytest.mark.parametrize("existing_stamp", [False, True], ids=["new-insert", "reobserve"])
@pytest.mark.parametrize("delete_commits", [False, True], ids=["parent-rollback", "parent-delete"])
async def test_legacy_fk_actual_parent_delete_race(fk_boundary, existing_stamp, delete_commits):
    admin, runtime = fk_boundary
    ids = await _nonactive_features(admin, 1)
    if existing_stamp:
        async with AsyncSession(runtime) as session, session.begin():
            assert await upsert_stamps(session, current=_A, outcomes={ids[0]: "called"}) == 1
    started = asyncio.get_running_loop().create_future()
    task = None
    try:
        async with AsyncSession(admin) as holder:
            transaction = await holder.begin()
            try:
                holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
                # 정본 highpriv fixture 관리자만 사용한다. runtime DELETE 권한 확대가 아니다.
                deleted = await holder.execute(
                    text("DELETE FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
                    {"id": ids[0]},
                )
                assert deleted.rowcount == 1

                async def writer():
                    async with AsyncSession(runtime) as session, session.begin():
                        await session.execute(text("SET LOCAL lock_timeout='5s'"))
                        await session.execute(text("SET LOCAL statement_timeout='8s'"))
                        started.set_result(await session.scalar(text("SELECT pg_backend_pid()")))
                        return await upsert_stamps(
                            session, current=_B, outcomes={ids[0]: "geocoded"}
                        )

                task = asyncio.create_task(writer())
                writer_pid = await asyncio.wait_for(asyncio.shield(started), 3)
                await _wait_blocker(admin, writer_pid, holder_pid)
                assert not task.done()
                # protocol 대기가 아닌 실제 FK/부모삭제 xact 경합임을 분리한다.
                locks = await _read(
                    admin,
                    """SELECT mode,granted FROM pg_locks
                    WHERE pid=:pid AND locktype='advisory' AND classid=1369104691::oid
                    AND objid=115::oid AND objsubid=2""",
                    {"pid": writer_pid},
                )
                assert [dict(row) for row in locks] == [{"mode": "ExclusiveLock", "granted": True}]
                if delete_commits:
                    await transaction.commit()
                else:
                    await transaction.rollback()
            finally:
                if transaction.is_active:
                    await transaction.rollback()
        if delete_commits:
            with pytest.raises(DBAPIError) as caught:
                await asyncio.wait_for(task, 8)
            assert caught.value.orig.sqlstate == "23503"
            assert await _stamps(admin, ids) == []
        else:
            assert await asyncio.wait_for(task, 8) == 1
            rows = await _stamps(admin, ids)
            assert len(rows) == 1
            assert rows[0]["geo_data_token"] == _B.data_token
            assert rows[0]["reverse_outcome"] == "geocoded"
        assert runtime.pool.checkedout() == 0
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
