"""실제 역할/owned PG에서 stamp SD 권한·원자성을 검증한다. collector 배선 시험은 아니다."""

from __future__ import annotations

import asyncio
import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import Address, Coordinate
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra import exclusive_provider_refresh as full
from kortravelmap.infra import feature_geocode_stamp_repo as stamp_repo
from kortravelmap.infra import feature_repo
from kortravelmap.infra import scoped_provider_batch as batch
from kortravelmap.infra import scoped_provider_refresh as native
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.feature_geocode_stamp_repo import upsert_stamps
from kortravelmap.infra.provider_field_candidates import lock_provider_field_policy_epoch
from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges_in_transaction
from kortravelmap.infra.scoped_feature_writes import (
    begin_scoped_feature_write,
    cancel_scoped_feature_write,
    finish_scoped_feature_write,
    lock_scoped_feature_write_protocol,
)
from tests.integration.test_exclusive_provider_full_refresh import _full_plan
from tests.integration.test_feature_geocode_stamps import _feature
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import (
    scalar_engines as scalar_engines,
)
from tests.integration.test_scoped_provider_batch import (
    _dataset_bundle,
    _entity,
    _plan,
    _seed_bundles,
)

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


@pytest.mark.parametrize("gate", [None, False, True], ids=["no-gate", "shared", "exclusive"])
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
        {
            "names": [
                "upsert_provider_geocode_stamps_ex",
                "lock_scoped_provider_geocode_stamps",
                "reobserve_scoped_provider_geocode_stamps",
            ]
        },
    )
    assert len(rows) == 3
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
                    {
                        "names": [row["proname"] for row in rows]
                        + ["_validate_scoped_provider_geocode_stamps"]
                    },
                )
            )
            .mappings()
            .all()
        )
        assert len(allowed) == 4
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


async def _active_name_setup(admin, runtime, count=2):
    dataset_key = "stamp-" + uuid4().hex
    keys = [uuid4().hex for _ in range(count)]

    def bundle(key, name, hours):
        value = _dataset_bundle(dataset_key, key, name, hours=hours)
        return value.model_copy(
            update={
                "feature": value.feature.model_copy(
                    update={
                        "coord": Coordinate(lon=127.0, lat=37.5),
                        "address": Address(legal="owned stamp fixture", bjd_code="1111010100"),
                    }
                ),
                "provider_field_presence": value.provider_field_presence.model_copy(
                    update={"supplied_fields": frozenset({"core.name"})}
                ),
            }
        )

    old = [bundle(key, f"before-{i}", -24) for i, key in enumerate(keys)]
    middle = [bundle(key, f"middle-{i}", 0) for i, key in enumerate(keys)]
    dataset, seeded = await _seed_bundles(admin, runtime, old, middle)
    geo = GeoLoadContext(
        geo_applied=GeoApplied(reverse=True, geocode=False),
        current_dataset=_A,
        observed_data_tokens=frozenset({_A.data_token}),
    )
    # active stamp seed에는 broad EX가 아니라 실제 applying EX full context를 사용한다.
    inputs, ex_plan = await _full_plan(runtime, dataset, seeded, geo=geo)
    async with AsyncSession(runtime) as session, session.begin():
        result = await full.refresh_exclusive_provider_snapshot(session, inputs, **ex_plan)
        assert result.load.geo_stamps_written == count
    items = [
        batch.ProviderScalarRefreshItem(item.feature_id, bundle(key, f"after-{i}", 1))
        for i, (key, item) in enumerate(zip(keys, seeded, strict=True))
    ]
    rows = await _stamps(admin, [str(item.feature_id) for item in items])
    assert len(rows) == count
    return dataset, items, rows


async def _stamp_plan(runtime, dataset, items, old_stamps):
    plan, _ = await _plan(runtime, dataset, items)
    # 정본 public 생성 경로의 se_/sr_ key를 보존한다. 가짜 bare 64hex로 대체하지 않는다.
    assert all(_entity(item.bundle).startswith("se_") for item in items)
    assert all(item.bundle.source_record.source_record_key.startswith("sr_") for item in items)
    stamps = {row["feature_id"]: row for row in old_stamps}
    targets = [
        {
            "feature_id": str(item.feature_id),
            "source_entity_key": _entity(item.bundle),
            "source_record_key": item.bundle.source_record.source_record_key,
            "policy_revision": 1,
            "geo_version_token": stamps[str(item.feature_id)]["geo_version_token"],
            "geo_data_token": stamps[str(item.feature_id)]["geo_data_token"],
            "reverse_outcome": stamps[str(item.feature_id)]["reverse_outcome"],
            "stamped_at": stamps[str(item.feature_id)]["stamped_at"].isoformat(),
        }
        for item in sorted(items, key=lambda item: item.feature_id)
    ]
    return plan, dict(
        attempt_id=str(plan["attempt_id"]),
        owner=str(plan["owner"]),
        manifest_digest=plan["manifest_digest"],
        input_digest=batch.scoped_provider_refresh_batch_input_digest(
            items, dataset_id=dataset, policy_revision=1
        ),
        targets_json=json.dumps(targets, separators=(",", ":")),
    )


async def _begin(session, plan):
    await lock_scoped_feature_write_protocol(session, exclusive=False)
    await lock_provider_field_policy_epoch(session)
    attempt = await begin_scoped_feature_write(
        session,
        attempt_id=plan["attempt_id"],
        owner=plan["owner"],
        manifest_digest=plan["manifest_digest"],
    )
    assert attempt["status"] == "applying"
    assert attempt["exclusive_protocol"] is False
    modes = (
        (
            await session.execute(
                text("""SELECT mode FROM pg_locks
        WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
        AND classid=1369104691::oid AND objid=115::oid AND objsubid=2""")
            )
        )
        .scalars()
        .all()
    )
    assert modes == ["ShareLock"]


async def _actual_sources(session, items, plan):
    for item in items:
        await native._assert_provider_scalar_target(
            session,
            item.bundle,
            feature_id=item.feature_id,
            dataset_id=plan["dataset_id"],
            policy_revision=1,
            attempt_id=plan["attempt_id"],
        )
    for item in items:
        head = await native._apply_provider_scalar(
            session,
            item.bundle,
            feature_id=item.feature_id,
            dataset_id=plan["dataset_id"],
            policy_revision=1,
            attempt_id=plan["attempt_id"],
            scalar_values=native._provider_scalar_values(item.bundle, feature_id=item.feature_id),
        )
        assert head == item.bundle.source_record.source_record_key


async def _finish(session, items, plan):
    record = items[0].bundle.source_record
    capture = await feature_repo.capture_provider_curation_input(
        session, provider=record.provider, dataset_key=record.dataset_key
    )
    digest = hashlib.sha256(
        json.dumps(
            [
                "owned-stamp-foundation-test-v1",
                capture.curation_input_member_count,
                capture.curation_input_set_hash,
                [item.bundle.source_record.source_record_key for item in items],
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    result = await finish_scoped_feature_write(
        session, attempt_id=plan["attempt_id"], owner=plan["owner"], result_digest=digest
    )
    assert result["status"] == "completed"


async def test_real_sh_preflight_source_candidate_and_timestamp_only_reobservation(boundary):
    admin, runtime = boundary
    dataset, items, old = await _active_name_setup(admin, runtime)
    plan, arguments = await _stamp_plan(runtime, dataset, items, old)
    ids = [str(item.feature_id) for item in items]
    async with AsyncSession(runtime) as session, session.begin():
        await _begin(session, plan)
        clock = await session.scalar(text("SELECT transaction_timestamp()"))
        assert await stamp_repo.lock_scoped_provider_geocode_stamps(session, **arguments) == 2
        assert await _stamps(admin, ids) == old
        await _actual_sources(session, items, plan)
        assert await stamp_repo.reobserve_scoped_provider_geocode_stamps(session, **arguments) == 2
        await _finish(session, items, plan)
    current = await _stamps(admin, ids)
    assert len(current) == 2
    for before, after in zip(old, current, strict=True):
        assert {k: v for k, v in after.items() if k != "stamped_at"} == {
            k: v for k, v in before.items() if k != "stamped_at"
        }
        assert after["stamped_at"] == clock
    rows = await _read(
        admin,
        """SELECT f.name,h.current_source_record_key
        FROM feature.features f JOIN provider_sync.source_links l USING(feature_id)
        JOIN provider_sync.source_entity_heads h USING(source_entity_key)
        WHERE f.feature_id=ANY(CAST(:ids AS uuid[])) ORDER BY f.name""",
        {"ids": ids},
    )
    assert [row["name"] for row in rows] == ["after-0", "after-1"]
    assert {row["current_source_record_key"] for row in rows} == {
        item.bundle.source_record.source_record_key for item in items
    }


@pytest.mark.parametrize(
    "fault",
    [
        "owner",
        "manifest",
        "input",
        "old_stamp",
        "missing",
        "duplicate",
        "extra_key",
        "bool_revision",
        "too_many",
        "oversize",
        "writer_before_source",
    ],
)
async def test_scoped_stamp_invalid_evidence_rolls_back_entire_apply(boundary, fault):
    admin, runtime = boundary
    dataset, items, old = await _active_name_setup(admin, runtime)
    plan, arguments = await _stamp_plan(runtime, dataset, items, old)
    ids = [str(item.feature_id) for item in items]
    before = await _read(
        admin,
        """SELECT f.feature_id::text,f.name,f.row_revision,
        h.current_source_record_key FROM feature.features f
        JOIN provider_sync.source_links l USING(feature_id)
        JOIN provider_sync.source_entity_heads h USING(source_entity_key)
        WHERE f.feature_id=ANY(CAST(:ids AS uuid[])) ORDER BY f.feature_id""",
        {"ids": ids},
    )
    invalid = dict(arguments)
    targets = json.loads(invalid["targets_json"])
    if fault == "owner":
        invalid["owner"] = str(uuid4())
    elif fault == "manifest":
        invalid["manifest_digest"] = "0" * 64
    elif fault == "input":
        invalid["input_digest"] = "0" * 64
    elif fault == "old_stamp":
        targets[0]["stamped_at"] = "2000-01-01T00:00:00+00:00"
    elif fault == "missing":
        targets.pop()
    elif fault == "duplicate":
        targets[1] = dict(targets[0])
    elif fault == "extra_key":
        targets[0]["authorize"] = True
    elif fault == "bool_revision":
        targets[0]["policy_revision"] = True
    elif fault == "too_many":
        targets = [dict(targets[0]) for _ in range(2731)]
    elif fault == "oversize":
        targets[0]["stamped_at"] = "x" * 1_048_577
    invalid["targets_json"] = json.dumps(targets, separators=(",", ":"))

    async def rejected_apply():
        async with AsyncSession(runtime) as session, session.begin():
            await _begin(session, plan)
            if fault == "writer_before_source":
                await stamp_repo.reobserve_scoped_provider_geocode_stamps(session, **arguments)
            elif fault in {"too_many", "oversize"}:
                # Python 크기 가드를 우회한 직접 SD 호출도 DB 자체에서 거부해야 한다.
                await session.execute(
                    text("""SELECT feature.lock_scoped_provider_geocode_stamps(
                    CAST(:attempt AS uuid),CAST(:owner AS uuid),:manifest,:input,
                    CAST(:targets AS jsonb))"""),
                    {
                        "attempt": plan["attempt_id"],
                        "owner": plan["owner"],
                        "manifest": invalid["manifest_digest"],
                        "input": invalid["input_digest"],
                        "targets": invalid["targets_json"],
                    },
                )
            else:
                await stamp_repo.lock_scoped_provider_geocode_stamps(session, **invalid)

    with pytest.raises(DBAPIError) as caught:
        await rejected_apply()
    assert caught.value.orig.sqlstate in {"23514", "40001"}
    assert await _stamps(admin, ids) == old
    assert (
        await _read(
            admin,
            """SELECT f.feature_id::text,f.name,f.row_revision,
        h.current_source_record_key FROM feature.features f
        JOIN provider_sync.source_links l USING(feature_id)
        JOIN provider_sync.source_entity_heads h USING(source_entity_key)
        WHERE f.feature_id=ANY(CAST(:ids AS uuid[])) ORDER BY f.feature_id""",
            {"ids": ids},
        )
        == before
    )
    assert (
        await _read(
            admin,
            "SELECT status FROM ops.feature_write_attempts WHERE attempt_id=:id",
            {"id": plan["attempt_id"]},
        )
    )[0]["status"] == "ready"
    assert runtime.pool.checkedout() == 0


async def _owned_state(admin, ids):
    output = {}
    for table in [
        "features",
        "feature_places",
        "feature_geocode_stamps",
        "provider_field_shadow_candidates",
        "feature_base_field_values",
    ]:
        # table names are test-owned fixed literals, not caller input.
        output[table] = await _read(
            admin,
            f"SELECT to_jsonb(row) AS value FROM feature.{table} row "
            "WHERE feature_id=ANY(CAST(:ids AS uuid[])) ORDER BY to_jsonb(row)::text",
            {"ids": ids},
        )
    for table in ["source_entities", "source_records", "source_entity_heads"]:
        output[table] = await _read(
            admin,
            f"SELECT to_jsonb(row) AS value FROM provider_sync.{table} row "
            "WHERE source_entity_key IN (SELECT source_entity_key FROM provider_sync.source_links "
            "WHERE feature_id=ANY(CAST(:ids AS uuid[]))) ORDER BY to_jsonb(row)::text",
            {"ids": ids},
        )
    return output


async def test_source_and_stamp_real_dml_rollback_then_same_plan_retry(boundary):
    admin, runtime = boundary
    dataset, items, old = await _active_name_setup(admin, runtime)
    plan, arguments = await _stamp_plan(runtime, dataset, items, old)
    ids = [str(item.feature_id) for item in items]
    before = await _owned_state(admin, ids)

    async def actual_apply_then_exception():
        async with AsyncSession(runtime) as session, session.begin():
            await _begin(session, plan)
            assert await stamp_repo.lock_scoped_provider_geocode_stamps(session, **arguments) == 2
            await _actual_sources(session, items, plan)
            assert (
                await stamp_repo.reobserve_scoped_provider_geocode_stamps(session, **arguments) == 2
            )
            await _finish(session, items, plan)
            raise RuntimeError("owned post-DML exception injection, not worker death")

    with pytest.raises(RuntimeError, match="owned post-DML"):
        await actual_apply_then_exception()
    assert await _owned_state(admin, ids) == before
    assert await _stamps(admin, ids) == old
    assert (
        await _read(
            admin,
            "SELECT status FROM ops.feature_write_attempts WHERE attempt_id=:id",
            {"id": plan["attempt_id"]},
        )
    )[0]["status"] == "ready"
    async with AsyncSession(runtime) as session, session.begin():
        await _begin(session, plan)
        assert await stamp_repo.lock_scoped_provider_geocode_stamps(session, **arguments) == 2
        await _actual_sources(session, items, plan)
        assert await stamp_repo.reobserve_scoped_provider_geocode_stamps(session, **arguments) == 2
        await _finish(session, items, plan)
    assert await _stamps(admin, ids) != old


@pytest.mark.parametrize("phase", ["ready", "cancelled", "exclusive", "no_protocol"])
async def test_scoped_stamp_requires_live_same_transaction_shared_attempt(boundary, phase):
    admin, runtime = boundary
    dataset, items, old = await _active_name_setup(admin, runtime)
    plan, arguments = await _stamp_plan(runtime, dataset, items, old)
    if phase == "cancelled":
        async with AsyncSession(runtime) as session, session.begin():
            assert await cancel_scoped_feature_write(
                session, attempt_id=plan["attempt_id"], owner=plan["owner"]
            )

    async def rejected_context():
        async with AsyncSession(runtime) as session, session.begin():
            if phase != "no_protocol":
                await lock_scoped_feature_write_protocol(session, exclusive=phase == "exclusive")
                await lock_provider_field_policy_epoch(session)
            await stamp_repo.lock_scoped_provider_geocode_stamps(session, **arguments)

    with pytest.raises(DBAPIError) as caught:
        await rejected_context()
    assert caught.value.orig.sqlstate in {"23514", "40001"}
    assert await _stamps(admin, [str(item.feature_id) for item in items]) == old


async def test_active_legacy_broad_ex_is_not_full_refresh_authority(boundary):
    admin, runtime = boundary
    _, items, old = await _active_name_setup(admin, runtime)
    ids = [str(item.feature_id) for item in items]

    async def broad_gate_only():
        async with AsyncSession(runtime) as session, session.begin():
            await lock_scoped_feature_write_protocol(session, exclusive=True)
            await upsert_stamps(session, current=_A, outcomes=dict.fromkeys(ids, "called"))

    with pytest.raises(DBAPIError) as caught:
        await broad_gate_only()
    assert caught.value.orig.sqlstate == "23514"
    assert await _stamps(admin, ids) == old


async def _wait_blocker(admin, waiter_pid, holder_pid):
    for _ in range(100):
        rows = await _read(
            admin, "SELECT pg_blocking_pids(:waiter) AS blockers", {"waiter": waiter_pid}
        )
        if holder_pid in rows[0]["blockers"]:
            return
        await asyncio.sleep(0.02)
    pytest.fail("owned waiter did not block on exact owned protocol holder")


@pytest.mark.parametrize(
    "shared_holder", [True, False], ids=["SH-blocks-EX-stamp", "EX-stamp-blocks-SH"]
)
async def test_actual_legacy_stamp_and_shared_protocol_exclude_both_directions(
    boundary, shared_holder
):
    admin, runtime = boundary
    ids = await _nonactive_features(admin, 1)
    other = make_async_engine(
        runtime.url.render_as_string(hide_password=False), pool_size=1, max_overflow=0
    )
    task = None
    released = asyncio.Event()
    started = asyncio.get_running_loop().create_future()
    try:
        async with AsyncSession(runtime) as holder, holder.begin():
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            if shared_holder:
                await lock_scoped_feature_write_protocol(holder, exclusive=False)
            else:
                assert await upsert_stamps(holder, current=_A, outcomes={ids[0]: "called"}) == 1
            modes = (
                (
                    await holder.execute(
                        text("""SELECT mode FROM pg_locks WHERE
                pid=pg_backend_pid() AND locktype='advisory' AND granted
                AND classid=1369104691::oid AND objid=115::oid AND objsubid=2""")
                    )
                )
                .scalars()
                .all()
            )
            assert modes == ["ShareLock" if shared_holder else "ExclusiveLock"]

            async def waiter():
                async with AsyncSession(other) as session, session.begin():
                    await session.execute(text("SET LOCAL lock_timeout='5s'"))
                    await session.execute(text("SET LOCAL statement_timeout='8s'"))
                    pid = await session.scalar(text("SELECT pg_backend_pid()"))
                    started.set_result(pid)
                    if shared_holder:
                        assert (
                            await upsert_stamps(session, current=_B, outcomes={ids[0]: "geocoded"})
                            == 1
                        )
                    else:
                        await lock_scoped_feature_write_protocol(session, exclusive=False)
                    assert released.is_set()

            task = asyncio.create_task(waiter())
            waiter_pid = await asyncio.wait_for(asyncio.shield(started), 3)
            await _wait_blocker(admin, waiter_pid, holder_pid)
            assert not task.done()
            if shared_holder:
                # EX waiter는 protocol부터 기다려야 하며 옛 global을 먼저 잡으면 안 된다.
                async with AsyncSession(admin) as observer, observer.begin():
                    assert await observer.scalar(
                        text(
                            "SELECT pg_try_advisory_xact_lock("
                            "hashtextextended('feature-curation-write',0))"
                        )
                    )
            released.set()
        await asyncio.wait_for(task, 8)
        assert runtime.pool.checkedout() == other.pool.checkedout() == 0
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await other.dispose()


async def test_legacy_stamp_shared_upgrade_rejects_then_fresh_transaction_succeeds(boundary):
    admin, runtime = boundary
    ids = await _nonactive_features(admin, 1)

    async def upgrade():
        async with AsyncSession(runtime) as session, session.begin():
            await lock_scoped_feature_write_protocol(session, exclusive=False)
            await upsert_stamps(session, current=_A, outcomes={ids[0]: "called"})

    with pytest.raises(DBAPIError) as caught:
        await upgrade()
    assert caught.value.orig.sqlstate == "23514"
    assert await _stamps(admin, ids) == []
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL lock_timeout='17s'"))
        await session.execute(text("SET LOCAL statement_timeout='23s'"))
        assert await upsert_stamps(session, current=_A, outcomes={ids[0]: "called"}) == 1
        assert await session.scalar(text("SHOW lock_timeout")) == "17s"
        assert await session.scalar(text("SHOW statement_timeout")) == "23s"


async def test_active_stamp_install_preserves_trigger_security_and_events(boundary):
    admin, runtime = boundary
    await _active_name_setup(admin, runtime)
    rows = await _read(
        admin,
        """SELECT t.tgname,p.proname,p.prosecdef,t.tgtype,
        pg_get_triggerdef(t.oid) AS definition
        FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid
        WHERE t.tgrelid='feature.feature_geocode_stamps'::regclass AND NOT t.tgisinternal
        ORDER BY t.tgname""",
    )
    entry = [row for row in rows if row["proname"] == "guard_stamp_writer_entry"]
    assert len(entry) == 1
    assert entry[0]["prosecdef"] is False
    assert "INSERT OR UPDATE" in entry[0]["definition"]
    unsupported = [row for row in rows if row["tgname"] == "trg_scalar_unsupported"]
    assert len(unsupported) == 1
    assert unsupported[0]["prosecdef"] is True
    assert "BEFORE DELETE" in unsupported[0]["definition"]
    assert "INSERT" not in unsupported[0]["definition"]
    assert "UPDATE" not in unsupported[0]["definition"]
    count = (
        await _read(
            admin,
            """SELECT count(*) AS count FROM pg_trigger
        WHERE tgname IN ('trg_scalar_epoch','trg_scalar_projection_insert',
            'trg_scalar_projection_update','trg_scalar_projection_delete',
            'trg_scalar_unsupported','trg_stamp_writer_entry') AND NOT tgisinternal""",
        )
    )[0]["count"]
    assert count == 51


async def test_preflight_really_locks_existing_stamp_rows_and_releases_on_rollback(boundary):
    admin, runtime = boundary
    dataset, items, old = await _active_name_setup(admin, runtime)
    plan, arguments = await _stamp_plan(runtime, dataset, items, old)
    ids = [str(item.feature_id) for item in items]

    async def nowait_stamp():
        async with AsyncSession(admin) as observer, observer.begin():
            return (
                (
                    await observer.execute(
                        text("""SELECT feature_id FROM feature.feature_geocode_stamps
                WHERE feature_id=ANY(CAST(:ids AS uuid[]))
                ORDER BY feature_id FOR UPDATE NOWAIT"""),
                        {"ids": ids},
                    )
                )
                .scalars()
                .all()
            )

    async def preflight_then_rollback():
        async with AsyncSession(runtime) as session, session.begin():
            await _begin(session, plan)
            assert await stamp_repo.lock_scoped_provider_geocode_stamps(session, **arguments) == 2
            assert await _stamps(admin, ids) == old
            with pytest.raises(DBAPIError) as caught:
                await nowait_stamp()
            assert caught.value.orig.sqlstate == "55P03"
            raise RuntimeError("owned preflight rollback")

    with pytest.raises(RuntimeError, match="owned preflight rollback"):
        await preflight_then_rollback()
    assert len(await nowait_stamp()) == 2
    assert await _stamps(admin, ids) == old


async def test_stamp_foreign_key_cascade_for_nonactive_feature_is_preserved(boundary):
    admin, runtime = boundary
    ids = await _nonactive_features(admin, 1)
    async with AsyncSession(runtime) as session, session.begin():
        assert await upsert_stamps(session, current=_A, outcomes={ids[0]: "called"}) == 1
    assert len(await _stamps(admin, ids)) == 1
    # 명시 관리 경계: runtime DELETE 권한을 추가하지 않고 기존 FK cascade만 관측한다.
    async with AsyncSession(admin) as session, session.begin():
        await lock_scoped_feature_write_protocol(session, exclusive=True)
        await session.execute(
            text("DELETE FROM feature.features WHERE feature_id=CAST(:id AS uuid)"), {"id": ids[0]}
        )
    assert await _stamps(admin, ids) == []


async def test_python_stamp_wrapper_rejects_oversize_without_sql(boundary):
    _, runtime = boundary
    statements = []

    def count(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(runtime.sync_engine, "before_cursor_execute", count)
    try:
        async with AsyncSession(runtime) as session:
            with pytest.raises(ValueError, match="1MiB"):
                await stamp_repo.lock_scoped_provider_geocode_stamps(
                    session,
                    attempt_id=str(uuid4()),
                    owner=str(uuid4()),
                    manifest_digest="a" * 64,
                    input_digest="b" * 64,
                    targets_json="[" + " " * 1_048_577 + "]",
                )
        assert statements == []
    finally:
        event.remove(runtime.sync_engine, "before_cursor_execute", count)


async def test_legacy_missing_feature_fk_rejects_entire_batch(boundary):
    admin, runtime = boundary
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
async def test_legacy_fk_actual_parent_delete_race(boundary, existing_stamp, delete_commits):
    admin, runtime = boundary
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
