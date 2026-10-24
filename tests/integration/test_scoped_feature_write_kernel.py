"""고유·제한된 PostGIS에서 kernel 실제 다중 세션 계약을 검증한다.

이 fixture는 411 실행문과 최소 참조 표를 사용한다. 전체 application bootstrap/head/ACL
수용은 root 통합 게이트이며 이 파일의 통과를 그 결과로 보고하지 않는다.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import docker
from kortravelmap.infra.scoped_feature_writes import (
    ScopedWriteDependency,
    ScopedWriteRegion,
    append_scoped_feature_write_manifest,
    begin_scoped_feature_write,
    cancel_scoped_feature_write,
    claim_scoped_feature_write,
    finish_scoped_feature_write,
    lock_scoped_feature_write_protocol,
    seal_scoped_feature_write_manifest,
)
from tests.integration._postgis_image import resolve_postgis_image

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def kernel_database():
    assert not os.environ.get("DOCKER_HOST") or os.environ["DOCKER_HOST"].startswith("unix://")
    from testcontainers.postgres import PostgresContainer

    identity = uuid4().hex
    container = (
        PostgresContainer(
            resolve_postgis_image(),
            username="kernel_admin",
            password="kernel-" + identity,
            dbname="kernel_test",
        )
        .with_name("kt-map-scope-kernel-" + identity)
        .with_kwargs(
            labels={"codex.scoped-kernel": identity},
            mem_limit="1536m",
            memswap_limit="1536m",
            nano_cpus=2_000_000_000,
            pids_limit=256,
        )
    )
    captured_id = None
    try:
        container.start()
        actual = container.get_wrapped_container()
        actual.reload()
        captured_id = actual.id
        assert actual.attrs["Config"]["Labels"]["codex.scoped-kernel"] == identity
        assert "@sha256:" in resolve_postgis_image()
        admin = make_url(container.get_connection_url()).set(drivername="postgresql")
        password = "runtime-" + identity
        with psycopg.connect(admin.render_as_string(False), autocommit=True) as connection:
            for role in (
                "ktm_feature_schema_owner",
                "ktm_feature_state_procedure_owner",
                "ktm_feature_runtime",
            ):
                connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
            connection.execute(
                "GRANT ktm_feature_state_procedure_owner TO ktm_feature_schema_owner WITH "
                "INHERIT FALSE"
            )
            connection.execute(
                sql.SQL(
                    "CREATE ROLE kernel_runtime LOGIN PASSWORD {} IN ROLE ktm_feature_runtime"
                ).format(sql.Literal(password))
            )
            for schema in ("ops", "provider_sync", "feature"):
                connection.execute(
                    sql.SQL("CREATE SCHEMA {} AUTHORIZATION ktm_feature_schema_owner").format(
                        sql.Identifier(schema)
                    )
                )
                connection.execute(
                    sql.SQL(
                        "GRANT USAGE ON SCHEMA {} TO "
                        "ktm_feature_state_procedure_owner,ktm_feature_runtime"
                    ).format(sql.Identifier(schema))
                )
            connection.execute("SET ROLE ktm_feature_schema_owner")
            connection.execute(
                "CREATE TABLE provider_sync.provider_datasets(provider_dataset_id bigint "
                "PRIMARY KEY)"
            )
            connection.execute("INSERT INTO provider_sync.provider_datasets VALUES (1),(2)")
            connection.execute(
                "CREATE TABLE provider_sync.source_entities(source_entity_key text PRIMARY "
                "KEY,provider_dataset_id bigint NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE provider_sync.source_entity_heads(source_entity_key text "
                "PRIMARY KEY,current_source_record_key text NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE feature.features(feature_id uuid PRIMARY KEY,row_revision "
                "bigint NOT NULL,name text NOT NULL)"
            )
            connection.execute(
                "GRANT SELECT,UPDATE ON "
                "provider_sync.source_entities,provider_sync.source_entity_heads,"
                "feature.features TO ktm_feature_state_procedure_owner"
            )
            connection.execute("GRANT SELECT,UPDATE ON feature.features TO ktm_feature_runtime")
            connection.execute(
                "CREATE TABLE ops.application_schema_operation_receipts(destinati"
                "on_head text, CONSTRAINT ck_application_schema_operation_receipt"
                "s_head CHECK (destination_head IN ('300')))"
            )
            connection.execute(
                "CREATE TABLE provider_sync.source_links(feature_id uuid NOT NULL"
                " REFERENCES feature.features(feature_id), source_entity_key text"
                " NOT NULL REFERENCES provider_sync.source_entities(source_entity"
                "_key), source_role text NOT NULL, PRIMARY KEY(feature_id,source_"
                "entity_key,source_role))"
            )
            connection.execute(
                "GRANT SELECT,UPDATE ON provider_sync.source_links TO ktm_feature"
                "_state_procedure_owner"
            )
            connection.execute("RESET ROLE")
            path = _ROOT / "alembic/versions/411_scoped_feature_write_kernel.py"
            spec = importlib.util.spec_from_file_location("scoped_kernel_migration", path)
            assert spec
            assert spec.loader
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            # 실제 upgrade와 동일한 정적 실행 tuple. 전체 Alembic receipt 수용을 뜻하지 않는다.
            with connection.transaction():
                for statement in migration._UPGRADE_STATEMENTS:
                    connection.execute(statement)
                connection.execute("SET ROLE ktm_feature_schema_owner")
                connection.execute(
                    "REVOKE CREATE ON SCHEMA ops FROM ktm_feature_state_procedure_owner"
                )
                connection.execute("RESET ROLE")
        runtime = admin.set(
            username="kernel_runtime", password=password, drivername="postgresql+asyncpg"
        )
        yield {
            "admin": admin.set(drivername="postgresql+asyncpg"),
            "runtime": runtime,
            "container_id": actual.id,
            "owner": identity,
        }
    finally:
        client = docker.from_env(timeout=5)
        try:
            owned = client.containers.get("kt-map-scope-kernel-" + identity)
        except docker.errors.NotFound:
            pass
        else:
            # name/UUID label 외에도 이 fixture가 생성한 실제 object ID만 제거한다.
            expected_id = captured_id or container.get_wrapped_container().id
            assert owned.id == expected_id
            assert owned.attrs["Config"]["Labels"].get("codex.scoped-kernel") == identity
            assert owned.name == "kt-map-scope-kernel-" + identity
            owned.remove(force=True, v=True)
        finally:
            client.close()


@pytest.fixture
async def kernel_engines(kernel_database):
    admin = create_async_engine(
        kernel_database["admin"],
        pool_size=2,
        max_overflow=0,
        connect_args={"server_settings": {"statement_timeout": "4000", "lock_timeout": "1000"}},
    )
    runtime = create_async_engine(
        kernel_database["runtime"],
        pool_size=4,
        max_overflow=0,
        connect_args={"server_settings": {"statement_timeout": "4000", "lock_timeout": "1000"}},
    )
    try:
        yield admin, runtime
    finally:
        await runtime.dispose()
        await admin.dispose()


async def prepared(runtime, *, dataset=1, region=None, members=()):
    attempt, owner = uuid4(), uuid4()
    members = list(members)
    async with AsyncSession(runtime) as session, session.begin():
        for feature in [m for m in members if m.dependency_kind == "feature"]:
            if not any(
                m.dependency_kind == "feature_membership"
                and m.dependency_key == feature.dependency_key
                for m in members
            ):
                membership = await session.scalar(
                    text("SELECT ops.scoped_feature_write_membership_digest(CAST(:id AS uuid))"),
                    {"id": feature.dependency_key},
                )
                members.append(
                    ScopedWriteDependency(
                        len(members), "feature_membership", feature.dependency_key, membership
                    )
                )
        await claim_scoped_feature_write(
            session,
            attempt_id=attempt,
            owner=owner,
            dataset_id=dataset,
            idempotency_key=attempt.hex,
            regions=[ScopedWriteRegion(1, region)] if region else [],
            input_digest="a" * 64,
            expected_members=len(members),
        )
        if members:
            await append_scoped_feature_write_manifest(
                session, attempt_id=attempt, owner=owner, members=members
            )
        digest = await seal_scoped_feature_write_manifest(session, attempt_id=attempt, owner=owner)
    return {"attempt_id": attempt, "owner": owner}, digest


async def test_apply_completion_replay_and_direct_acl(kernel_engines):
    admin, runtime = kernel_engines
    token, digest = await prepared(runtime, region=uuid4().hex)
    async with AsyncSession(runtime) as session, session.begin():
        await begin_scoped_feature_write(session, **token, manifest_digest=digest)
        result = await finish_scoped_feature_write(session, **token, result_digest="b" * 64)
        assert result["status"] == "completed"
    async with AsyncSession(runtime) as session, session.begin():
        replay = await finish_scoped_feature_write(session, **token, result_digest="b" * 64)
        assert replay["result_digest"] == "b" * 64
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("UPDATE ops.feature_write_attempts SET status='completed'"))
    assert caught.value.orig.sqlstate == "42501"
    async with admin.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT status FROM ops.feature_write_attempts WHERE attempt_id=:id"),
                {"id": token["attempt_id"]},
            )
            == "completed"
        )


async def test_missing_finish_rolls_back_apply_and_write(kernel_engines):
    admin, runtime = kernel_engines
    feature = uuid4()
    async with admin.begin() as connection:
        await connection.execute(
            text("INSERT INTO feature.features VALUES(:id,1,'before')"), {"id": feature}
        )
    token, digest = await prepared(
        runtime,
        region=uuid4().hex,
        members=[ScopedWriteDependency(0, "feature", str(feature), "1")],
    )
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **token, manifest_digest=digest)
            await session.execute(
                text("UPDATE feature.features SET name='partial' WHERE feature_id=:id"),
                {"id": feature},
            )
    assert caught.value.orig.sqlstate == "23514"
    async with admin.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT name FROM feature.features WHERE feature_id=:id"), {"id": feature}
            )
            == "before"
        )
        assert (
            await connection.scalar(
                text("SELECT status FROM ops.feature_write_attempts WHERE attempt_id=:id"),
                {"id": token["attempt_id"]},
            )
            == "ready"
        )
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, **token)


async def test_changed_dependency_is_replanned(kernel_engines):
    admin, runtime = kernel_engines
    feature = uuid4()
    async with admin.begin() as connection:
        await connection.execute(
            text("INSERT INTO feature.features VALUES(:id,1,'before')"), {"id": feature}
        )
    token, digest = await prepared(
        runtime,
        region=uuid4().hex,
        members=[ScopedWriteDependency(0, "feature", str(feature), "1")],
    )
    async with admin.begin() as connection:
        await connection.execute(
            text("UPDATE feature.features SET row_revision=2 WHERE feature_id=:id"), {"id": feature}
        )
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **token, manifest_digest=digest)
    assert caught.value.orig.sqlstate == "40001"


async def test_disjoint_regions_overlap_and_whole_dataset_excludes(kernel_engines):
    _, runtime = kernel_engines
    first, d1 = await prepared(runtime, region=uuid4().hex)
    second, d2 = await prepared(runtime, region=uuid4().hex)
    both = asyncio.Barrier(2)

    async def worker(token, digest):
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **token, manifest_digest=digest)
            await asyncio.wait_for(both.wait(), 2)
            await session.execute(text("SELECT pg_sleep(0.05)"))
            await finish_scoped_feature_write(session, **token, result_digest="b" * 64)

    await asyncio.wait_for(asyncio.gather(worker(first, d1), worker(second, d2)), 4)
    active, _ = await prepared(runtime, region=uuid4().hex)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        await prepared(runtime)
    assert caught.value.orig.sqlstate == "55P03"
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, **active)


async def test_protocol_shared_exclusive_and_upgrade(kernel_engines):
    _, runtime = kernel_engines
    async with AsyncSession(runtime) as first, first.begin():
        await lock_scoped_feature_write_protocol(first, exclusive=False)
        with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
            async with AsyncSession(runtime) as second, second.begin():
                await second.execute(text("SET LOCAL lock_timeout='80ms'"))
                await lock_scoped_feature_write_protocol(second, exclusive=True)
        assert caught.value.orig.sqlstate == "55P03"
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await lock_scoped_feature_write_protocol(session, exclusive=False)
            await lock_scoped_feature_write_protocol(session, exclusive=True)
    assert caught.value.orig.sqlstate == "23514"
    async with AsyncSession(runtime) as session, session.begin():
        await lock_scoped_feature_write_protocol(session, exclusive=True)
        await lock_scoped_feature_write_protocol(session, exclusive=False)


async def test_expired_epoch_rejects_old_worker(kernel_engines):
    admin, runtime = kernel_engines
    region = uuid4().hex
    old, digest = await prepared(runtime, region=region)
    async with admin.begin() as connection:
        await connection.execute(
            text(
                "UPDATE ops.feature_write_attempts SET "
                "lease_until=clock_timestamp()-interval '1 second' WHERE attempt_id=:id"
            ),
            {"id": old["attempt_id"]},
        )
        await connection.execute(
            text(
                "UPDATE ops.feature_write_region_scopes SET "
                "lease_until=clock_timestamp()-interval '1 second' WHERE owner=:id"
            ),
            {"id": old["attempt_id"]},
        )
    newer, _ = await prepared(runtime, region=region)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **old, manifest_digest=digest)
    assert caught.value.orig.sqlstate == "40001"
    async with AsyncSession(runtime) as session, session.begin():
        assert await session.scalar(
            text("SELECT ops.expire_scoped_feature_write_attempt(:id)"), {"id": old["attempt_id"]}
        )
        assert await cancel_scoped_feature_write(session, **newer)


async def test_apply_lock_prevents_owner_takeover(kernel_engines):
    admin, runtime = kernel_engines
    region = uuid4().hex
    token, digest = await prepared(runtime, region=region)
    async with admin.begin() as connection:
        await connection.execute(
            text(
                "UPDATE ops.feature_write_attempts SET "
                "lease_until=clock_timestamp()+interval '300 milliseconds' WHERE "
                "attempt_id=:id"
            ),
            {"id": token["attempt_id"]},
        )
        await connection.execute(
            text(
                "UPDATE ops.feature_write_region_scopes SET "
                "lease_until=clock_timestamp()+interval '300 milliseconds' WHERE owner=:id"
            ),
            {"id": token["attempt_id"]},
        )
    async with AsyncSession(runtime) as first, first.begin():
        await begin_scoped_feature_write(first, **token, manifest_digest=digest)
        await asyncio.sleep(0.35)
        with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
            async with AsyncSession(runtime) as second, second.begin():
                await second.execute(text("SET LOCAL lock_timeout='80ms'"))
                await claim_scoped_feature_write(
                    second,
                    attempt_id=uuid4(),
                    owner=uuid4(),
                    dataset_id=1,
                    idempotency_key=uuid4().hex,
                    regions=[ScopedWriteRegion(1, region)],
                    input_digest="a" * 64,
                    expected_members=0,
                )
        assert caught.value.orig.sqlstate == "55P03"
        await finish_scoped_feature_write(first, **token, result_digest="b" * 64)
    newer, _ = await prepared(runtime, region=region)
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, **newer)


async def test_source_head_manifest_locks_and_revalidates(kernel_engines):
    admin, runtime = kernel_engines
    key = "entity-" + uuid4().hex
    async with admin.begin() as connection:
        await connection.execute(
            text("INSERT INTO provider_sync.source_entities VALUES(:key,1)"), {"key": key}
        )
        await connection.execute(
            text("INSERT INTO provider_sync.source_entity_heads VALUES(:key,'record1')"),
            {"key": key},
        )
    token, digest = await prepared(
        runtime,
        region=uuid4().hex,
        members=[ScopedWriteDependency(0, "source_head", key, "record1")],
    )
    async with AsyncSession(runtime) as first, first.begin():
        await begin_scoped_feature_write(first, **token, manifest_digest=digest)
        with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
            async with admin.begin() as connection:
                await connection.execute(text("SET LOCAL lock_timeout='80ms'"))
                await connection.execute(
                    text(
                        "UPDATE provider_sync.source_entity_heads SET "
                        "current_source_record_key='record2' WHERE source_entity_key=:key"
                    ),
                    {"key": key},
                )
        assert caught.value.orig.sqlstate == "55P03"
        await finish_scoped_feature_write(first, **token, result_digest="b" * 64)


async def test_cancel_during_apply_requires_rollback(kernel_engines):
    admin, runtime = kernel_engines
    token, digest = await prepared(runtime, region=uuid4().hex)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **token, manifest_digest=digest)
            await cancel_scoped_feature_write(session, **token)
    assert caught.value.orig.sqlstate == "23514"
    async with admin.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT status FROM ops.feature_write_attempts WHERE attempt_id=:id"),
                {"id": token["attempt_id"]},
            )
            == "ready"
        )
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, **token)


async def test_incomplete_immutable_manifest_and_idempotency(kernel_engines):
    _, runtime = kernel_engines
    attempt, owner = uuid4(), uuid4()
    params = dict(
        attempt_id=attempt,
        owner=owner,
        dataset_id=1,
        idempotency_key=attempt.hex,
        regions=[ScopedWriteRegion(1, attempt.hex)],
        input_digest="a" * 64,
        expected_members=2,
    )
    async with AsyncSession(runtime) as session, session.begin():
        first = await claim_scoped_feature_write(session, **params)
        replay = await claim_scoped_feature_write(session, **params)
        assert replay == first
        member = ScopedWriteDependency(0, "source_head", "entity", "record")
        assert (
            await append_scoped_feature_write_manifest(
                session, attempt_id=attempt, owner=owner, members=[member]
            )
            == 1
        )
        assert (
            await append_scoped_feature_write_manifest(
                session, attempt_id=attempt, owner=owner, members=[member]
            )
            == 1
        )
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await seal_scoped_feature_write_manifest(session, attempt_id=attempt, owner=owner)
    assert caught.value.orig.sqlstate == "23514"
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await append_scoped_feature_write_manifest(
                session,
                attempt_id=attempt,
                owner=owner,
                members=[ScopedWriteDependency(0, "source_head", "entity", "changed")],
            )
    assert caught.value.orig.sqlstate == "23514"
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await claim_scoped_feature_write(session, **(params | {"input_digest": "c" * 64}))
    assert caught.value.orig.sqlstate == "23514"
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, attempt_id=attempt, owner=owner)


async def test_actual_sql_rejects_bypass_oversize_and_unknown_owner(kernel_engines):
    _, runtime = kernel_engines
    token, digest = await prepared(runtime, region=uuid4().hex)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(
                session, attempt_id=token["attempt_id"], owner=uuid4(), manifest_digest=digest
            )
    assert caught.value.orig.sqlstate == "40001"
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(
                text(
                    "SELECT ops.claim_scoped_feature_write(:id,:owner,1,'invalid',CAST(:regions "
                    "AS jsonb),:digest,0,180,false)"
                ),
                {
                    "id": uuid4(),
                    "owner": uuid4(),
                    "regions": json.dumps(
                        [{"scope_version": 1, "region_key": str(i)} for i in range(257)]
                    ),
                    "digest": "a" * 64,
                },
            )
    assert caught.value.orig.sqlstate == "23514"
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SELECT ops._lock_scoped_feature_write_scope(1,'[]',false)"))
    assert caught.value.orig.sqlstate == "42501"
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, **token)


async def test_task_cancellation_releases_apply_locks(kernel_engines):
    _, runtime = kernel_engines
    region = uuid4().hex
    token, digest = await prepared(runtime, region=region)
    entered = asyncio.Event()

    async def blocked():
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **token, manifest_digest=digest)
            entered.set()
            await session.execute(text("SELECT pg_sleep(3)"))
            await finish_scoped_feature_write(session, **token, result_digest="b" * 64)

    worker = asyncio.create_task(blocked())
    await asyncio.wait_for(entered.wait(), 2)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, **token)
    successor, _ = await prepared(runtime, region=region)
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, **successor)


async def test_terminal_prune_is_bounded_and_not_runtime_callable(kernel_engines):
    admin, runtime = kernel_engines
    token, _ = await prepared(
        runtime,
        region=uuid4().hex,
        members=[ScopedWriteDependency(i, "source_head", f"entity{i}", "record") for i in range(4)],
    )
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, **token)
    async with admin.begin() as connection:
        await connection.execute(
            text(
                "UPDATE ops.feature_write_attempts SET updated_at=clock_timestamp()-interval "
                "'3 days' WHERE attempt_id=:id"
            ),
            {"id": token["attempt_id"]},
        )
        value = await connection.scalar(
            text(
                "SELECT ops.prune_scoped_feature_write_attempts(clock_timestamp()-interval "
                "'2 days',2)"
            )
        )
        assert value["manifest_rows"] == 2
        assert value["attempt_rows"] == 0
        value = await connection.scalar(
            text(
                "SELECT ops.prune_scoped_feature_write_attempts(clock_timestamp()-interval "
                "'2 days',2)"
            )
        )
        assert value["manifest_rows"] == 2
        assert value["attempt_rows"] == 1
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 진입/쓰기/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(
                text(
                    "SELECT ops.prune_scoped_feature_write_attempts(clock_timestamp()-interval "
                    "'2 days',2)"
                )
            )
    assert caught.value.orig.sqlstate == "42501"


async def test_cross_dataset_shared_feature_all_heads_lock_in_sorted_order(kernel_engines):
    admin, runtime = kernel_engines
    feature = uuid4()
    keys = ["a" + uuid4().hex, "b" + uuid4().hex]
    async with admin.begin() as connection:
        await connection.execute(
            text("INSERT INTO feature.features VALUES(:id,1,'before')"), {"id": feature}
        )
        for dataset, key in enumerate(keys, 1):
            await connection.execute(
                text("INSERT INTO provider_sync.source_entities VALUES(:key,:dataset)"),
                {"key": key, "dataset": dataset},
            )
            await connection.execute(
                text("INSERT INTO provider_sync.source_entity_heads VALUES(:key,'record')"),
                {"key": key},
            )
    async with admin.begin() as connection:
        for key in keys:
            await connection.execute(
                text("INSERT INTO provider_sync.source_links VALUES(:feature,:key,'primary')"),
                {"feature": feature, "key": key},
            )
    members = [
        ScopedWriteDependency(0, "source_head", keys[1], "record"),
        ScopedWriteDependency(1, "feature", str(feature), "1"),
        ScopedWriteDependency(2, "source_head", keys[0], "record"),
    ]
    left, d1 = await prepared(runtime, dataset=1, region=uuid4().hex, members=members)
    right, d2 = await prepared(
        runtime, dataset=2, region=uuid4().hex, members=list(reversed(members))
    )
    entered = asyncio.Event()

    async def first():
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **left, manifest_digest=d1)
            entered.set()
            await asyncio.sleep(0.15)
            await finish_scoped_feature_write(session, **left, result_digest="b" * 64)

    async def second():
        await entered.wait()
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **right, manifest_digest=d2)
            await finish_scoped_feature_write(session, **right, result_digest="b" * 64)

    await asyncio.wait_for(asyncio.gather(first(), second()), 3)
    async with admin.connect() as connection:
        assert (
            await connection.scalar(
                text(
                    "SELECT count(*) FROM ops.feature_write_attempts WHERE attempt_id IN "
                    "(:left,:right) AND status='completed'"
                ),
                {"left": left["attempt_id"], "right": right["attempt_id"]},
            )
            == 2
        )


async def test_repeatable_read_old_worker_is_serialization_failure(kernel_engines):
    admin, runtime = kernel_engines
    region = uuid4().hex
    token, digest = await prepared(runtime, region=region)
    rr = create_async_engine(
        runtime.url, isolation_level="REPEATABLE READ", pool_size=1, max_overflow=0
    )
    try:
        async with AsyncSession(rr) as old, old.begin():
            await old.execute(text("SELECT count(*) FROM feature.features"))
            async with admin.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE ops.feature_write_attempts SET "
                        "lease_until=clock_timestamp()-interval '1 second' WHERE attempt_id=:id"
                    ),
                    {"id": token["attempt_id"]},
                )
                await connection.execute(
                    text(
                        "UPDATE ops.feature_write_region_scopes SET "
                        "lease_until=clock_timestamp()-interval '1 second' WHERE owner=:id"
                    ),
                    {"id": token["attempt_id"]},
                )
            successor, _ = await prepared(runtime, region=region)
            with pytest.raises(DBAPIError) as caught:
                await begin_scoped_feature_write(old, **token, manifest_digest=digest)
            assert caught.value.orig.sqlstate == "40001"
        async with AsyncSession(runtime) as session, session.begin():
            assert await cancel_scoped_feature_write(session, **successor)
    finally:
        await rr.dispose()


async def test_participant_dataset_budget_is_enforced_before_apply(kernel_engines):
    admin, runtime = kernel_engines
    members = []
    async with admin.begin() as connection:
        for ordinal in range(33):
            dataset = 1000 + ordinal
            await connection.execute(
                text("INSERT INTO provider_sync.provider_datasets VALUES(:id)"), {"id": dataset}
            )
            key = "budget-" + uuid4().hex
            await connection.execute(
                text("INSERT INTO provider_sync.source_entities VALUES(:key,:dataset)"),
                {"key": key, "dataset": dataset},
            )
            await connection.execute(
                text("INSERT INTO provider_sync.source_entity_heads VALUES(:key,'record')"),
                {"key": key},
            )
            members.append(ScopedWriteDependency(ordinal, "source_head", key, "record"))
    token, digest = await prepared(runtime, region=uuid4().hex, members=members)
    with pytest.raises(DBAPIError) as caught:
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **token, manifest_digest=digest)
    assert caught.value.orig.sqlstate == "23514"
    async with admin.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT status FROM ops.feature_write_attempts WHERE attempt_id=:id"),
                {"id": token["attempt_id"]},
            )
            == "ready"
        )
    async with AsyncSession(runtime) as session, session.begin():
        assert await cancel_scoped_feature_write(session, **token)


async def test_cancel_cannot_overwrite_committed_apply(kernel_engines):
    _, runtime = kernel_engines
    token, digest = await prepared(runtime, region=uuid4().hex)
    async with AsyncSession(runtime) as first, first.begin():
        await begin_scoped_feature_write(first, **token, manifest_digest=digest)
        with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 실제 대기 중 취소 경쟁
            async with AsyncSession(runtime) as other, other.begin():
                await other.execute(text("SET LOCAL lock_timeout='80ms'"))
                await cancel_scoped_feature_write(other, **token)
        assert caught.value.orig.sqlstate == "55P03"
        await finish_scoped_feature_write(first, **token, result_digest="b" * 64)
    async with AsyncSession(runtime) as session, session.begin():
        assert not await cancel_scoped_feature_write(session, **token)


async def test_kernel_deadlines_preserve_shorter_caller_and_reject_unbounded_sql(kernel_engines):
    _, runtime = kernel_engines
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout='200ms'"))
        await session.execute(text("SET LOCAL lock_timeout='80ms'"))
        await claim_scoped_feature_write(
            session,
            attempt_id=uuid4(),
            owner=uuid4(),
            dataset_id=2,
            idempotency_key=uuid4().hex,
            regions=[ScopedWriteRegion(1, uuid4().hex)],
            input_digest="a" * 64,
            expected_members=0,
        )
        assert (
            await session.scalar(
                text("SELECT setting::int FROM pg_settings WHERE name='statement_timeout'")
            )
            == 200
        )
        assert (
            await session.scalar(
                text("SELECT setting::int FROM pg_settings WHERE name='lock_timeout'")
            )
            == 80
        )
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - SQL direct deadline 사전 거부
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL statement_timeout=0"))
            await session.execute(
                text(
                    "SELECT ops.claim_scoped_feature_write(:id,:owner,1,'unbounded','"
                    "[]',:digest,0,180,false)"
                ),
                {"id": uuid4(), "owner": uuid4(), "digest": "a" * 64},
            )
    assert caught.value.orig.sqlstate == "23514"
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout=0"))
        await session.execute(text("SET LOCAL lock_timeout=0"))
        token = await claim_scoped_feature_write(
            session,
            attempt_id=uuid4(),
            owner=uuid4(),
            dataset_id=2,
            idempotency_key=uuid4().hex,
            regions=[ScopedWriteRegion(1, uuid4().hex)],
            input_digest="a" * 64,
            expected_members=0,
        )
        assert token["status"] == "preparing"
        assert (
            await session.scalar(
                text("SELECT setting::int FROM pg_settings WHERE name='statement_timeout'")
            )
            == 30000
        )
        assert (
            await session.scalar(
                text("SELECT setting::int FROM pg_settings WHERE name='lock_timeout'")
            )
            == 1000
        )


async def test_public_protocol_preserves_finite_legacy_wait_and_resets_default(kernel_engines):
    _, runtime = kernel_engines
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL lock_timeout='15min'"))
        await lock_scoped_feature_write_protocol(session, exclusive=True)
        assert (
            await session.scalar(
                text("SELECT setting::int FROM pg_settings WHERE name='lock_timeout'")
            )
            == 900000
        )
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL lock_timeout=0"))
        await lock_scoped_feature_write_protocol(session, exclusive=True)
        assert (
            await session.scalar(
                text("SELECT setting::int FROM pg_settings WHERE name='lock_timeout'")
            )
            == 0
        )


async def _linked_feature(admin):
    feature = uuid4()
    key = "linked-" + uuid4().hex
    async with admin.begin() as connection:
        await connection.execute(
            text("INSERT INTO feature.features VALUES(:id,1,'before')"), {"id": feature}
        )
        await connection.execute(
            text("INSERT INTO provider_sync.source_entities VALUES(:key,1)"), {"key": key}
        )
        await connection.execute(
            text("INSERT INTO provider_sync.source_entity_heads VALUES(:key,'record')"),
            {"key": key},
        )
        await connection.execute(
            text("INSERT INTO provider_sync.source_links VALUES(:id,:key,'primary')"),
            {"id": feature, "key": key},
        )
    return feature, key


async def test_membership_delete_after_plan_is_replanned(kernel_engines):
    admin, runtime = kernel_engines
    feature, key = await _linked_feature(admin)
    token, digest = await prepared(
        runtime,
        region=uuid4().hex,
        members=[
            ScopedWriteDependency(0, "source_head", key, "record"),
            ScopedWriteDependency(1, "feature", str(feature), "1"),
        ],
    )
    async with admin.begin() as connection:
        await connection.execute(
            text("DELETE FROM provider_sync.source_links WHERE feature_id=:id"), {"id": feature}
        )
    with pytest.raises(DBAPIError) as caught:
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **token, manifest_digest=digest)
    assert caught.value.orig.sqlstate == "40001"


async def test_membership_all_source_heads_required_and_link_locked(kernel_engines):
    admin, runtime = kernel_engines
    feature, key = await _linked_feature(admin)
    incomplete, d1 = await prepared(
        runtime,
        region=uuid4().hex,
        members=[ScopedWriteDependency(0, "feature", str(feature), "1")],
    )
    with pytest.raises(DBAPIError) as caught:
        async with AsyncSession(runtime) as session, session.begin():
            await begin_scoped_feature_write(session, **incomplete, manifest_digest=d1)
    assert caught.value.orig.sqlstate == "40001"
    complete, d2 = await prepared(
        runtime,
        region=uuid4().hex,
        members=[
            ScopedWriteDependency(0, "source_head", key, "record"),
            ScopedWriteDependency(1, "feature", str(feature), "1"),
        ],
    )
    async with AsyncSession(runtime) as first, first.begin():
        await begin_scoped_feature_write(first, **complete, manifest_digest=d2)
        with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 별도 세션 실제 link 행 잠금
            async with admin.begin() as connection:
                await connection.execute(text("SET LOCAL lock_timeout='80ms'"))
                await connection.execute(
                    text("DELETE FROM provider_sync.source_links WHERE feature_id=:id"),
                    {"id": feature},
                )
        assert caught.value.orig.sqlstate == "55P03"
        await finish_scoped_feature_write(first, **complete, result_digest="b" * 64)


async def test_membership_digest_distinguishes_role_and_is_stable(kernel_engines):
    admin, runtime = kernel_engines
    feature, key = await _linked_feature(admin)
    async with AsyncSession(runtime) as session, session.begin():
        original = await session.scalar(
            text("SELECT ops.scoped_feature_write_membership_digest(:id)"), {"id": feature}
        )
        assert original == await session.scalar(
            text("SELECT ops.scoped_feature_write_membership_digest(:id)"), {"id": feature}
        )
    async with admin.begin() as connection:
        await connection.execute(
            text("INSERT INTO provider_sync.source_links VALUES(:id,:key,'enrichment')"),
            {"id": feature, "key": key},
        )
    async with AsyncSession(runtime) as session, session.begin():
        changed = await session.scalar(
            text("SELECT ops.scoped_feature_write_membership_digest(:id)"), {"id": feature}
        )
        assert changed != original


async def test_new_link_committing_during_feature_lock_wait_is_replanned(kernel_engines):
    admin, runtime = kernel_engines
    feature, key = await _linked_feature(admin)
    new_key = "phantom-" + uuid4().hex
    async with admin.begin() as connection:
        await connection.execute(
            text("INSERT INTO provider_sync.source_entities VALUES(:key,2)"), {"key": new_key}
        )
        await connection.execute(
            text("INSERT INTO provider_sync.source_entity_heads VALUES(:key,'record')"),
            {"key": new_key},
        )
    token, digest = await prepared(
        runtime,
        region=uuid4().hex,
        members=[
            ScopedWriteDependency(0, "source_head", key, "record"),
            ScopedWriteDependency(1, "feature", str(feature), "1"),
        ],
    )
    async with admin.connect() as inserting:
        transaction = await inserting.begin()
        try:
            await inserting.execute(
                text("INSERT INTO provider_sync.source_links VALUES(:id,:key,'primary')"),
                {"id": feature, "key": new_key},
            )
            async with AsyncSession(runtime) as applying, applying.begin():
                pid = await applying.scalar(text("SELECT pg_backend_pid()"))
                task = asyncio.create_task(
                    begin_scoped_feature_write(applying, **token, manifest_digest=digest)
                )
                try:
                    async with admin.connect() as probe:
                        async with asyncio.timeout(0.7):
                            for _ in range(70):
                                if await probe.scalar(
                                    text("SELECT cardinality(pg_blocking_pids(:pid))>0"),
                                    {"pid": pid},
                                ):
                                    break
                                await asyncio.sleep(0.01)
                            else:
                                raise RuntimeError("owned feature lock wait not observed")
                    # 새 link는 처음 membership 조회에는 보이지 않았다. FK가 Feature를 잠근
                    # 실제 대기를 확인한 뒤 commit하여 최종 membership 재조회가 필요함을 증명한다.
                    await transaction.commit()
                    with pytest.raises(DBAPIError) as caught:
                        await task
                    assert caught.value.orig.sqlstate == "40001"
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
        finally:
            if transaction.is_active:
                await transaction.rollback()
