"""신규 생성4 SQL의 첫 protocol 잠금·유효값·rollback을 실제 owned PG로 검증한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_feature_id
from kortravelmap.infra.scoped_feature_writes import (
    begin_scoped_feature_write,
    finish_scoped_feature_write,
)
from tests.integration.test_admin_override_protocol_entry import _wait_protocol_blocker
from tests.integration.test_provider_field_scalar_projection import _plan, _seed
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_tvn_m05_manual_provider_dedup import _open_command

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]
_spec = spec_from_file_location(
    "_integration_418",
    Path(__file__).resolve().parents[2] / "alembic/versions/418_creation_protocol.py",
)
assert _spec is not None
assert _spec.loader is not None
_migration = module_from_spec(_spec)
_spec.loader.exec_module(_migration)
_KINDS = ["core", "provider", "manual", "approve"]
_CALLS = {
    "core": """CALL feature.create_feature_with_initial_state(CAST(:payload AS jsonb),
 'active','published','valid',CAST(:context AS jsonb),NULL,NULL,NULL)""",
    "provider": """CALL feature.create_provider_feature_with_initial_state(CAST(:payload AS
jsonb), CAST(:identity AS jsonb),'active','published','valid',CAST(:context AS
jsonb),NULL,NULL,NULL)""",
    "manual": """CALL feature.create_admin_manual_feature_with_initial_state(
 CAST(:payload AS jsonb),:command,NULL,NULL,NULL,NULL)""",
    "approve": """CALL feature.approve_feature_request_with_initial_state(
 CAST(:request AS uuid),CAST(:payload AS jsonb),:command,NULL,NULL,NULL,NULL)""",
}


@dataclass
class Case:
    feature: str
    held_feature: str
    dataset: int
    natural: str
    name: str
    alias: str
    request: UUID
    actor: str
    command: int = 0

    def params(self):
        return dict(
            payload=json.dumps(
                dict(
                    feature_id=self.feature,
                    kind="place",
                    name=self.name,
                    category="01070300",
                    lon=127.5,
                    lat=36.5,
                    coord_precision_digits=6,
                    marker_icon="marker",
                    marker_color="P-02",
                )
            ),
            identity=json.dumps(
                dict(
                    provider_dataset_id=self.dataset,
                    feature_kind="place",
                    natural_key=self.natural,
                    legacy_alias=self.alias,
                )
            ),
            context=json.dumps(
                dict(
                    transition_kind="initial",
                    reason_code="creation-418",
                    principal=self.actor,
                    causation_ref="test:" + self.natural,
                )
            ),
            request=self.request,
            command=self.command,
        )


async def _case(admin, runtime, kind):
    held, datasets, _ = await _seed(admin)
    suffix = uuid4().hex
    async with admin.connect() as c:
        feature = str(await c.scalar(text("SELECT feature.uuid_generate_v7()")))
    case = Case(
        feature,
        held,
        datasets[0],
        suffix,
        "생성418-" + suffix,
        make_feature_id(
            bjd_code=None,
            kind="place",
            category="01070300",
            source_type="creation418",
            source_natural_key=suffix,
        ),
        uuid4(),
        "admin:creation418-" + suffix,
    )
    if kind in {"manual", "approve"}:
        case.command = await _open_command(
            runtime,
            actor=case.actor,
            operation="admin.feature.create.manual-v1"
            if kind == "manual"
            else "admin.feature-request.approve.v1",
        )
    if kind == "approve":
        submission = await _open_command(
            runtime, actor="service:feature-request", operation="service.feature-request.submit.v1"
        )
        async with AsyncSession(runtime) as c, c.begin():
            result = (
                (
                    await c.execute(
                        text("""CALL feature.submit_feature_request(CAST(:id AS uuid),
              CAST(:payload AS jsonb),:command,NULL,NULL)"""),
                        dict(
                            id=case.request,
                            command=submission,
                            payload=json.dumps(
                                dict(
                                    kind="place",
                                    name=case.name,
                                    lon=127.5,
                                    lat=36.5,
                                    categories=["external-request"],
                                    note="creation418",
                                )
                            ),
                        ),
                    )
                )
                .mappings()
                .one()
            )
            assert result["o_status"] == "pending"
    return case


async def _apply(session, kind, case):
    return (await session.execute(text(_CALLS[kind]), case.params())).mappings().one()


async def _snapshot(admin, case):
    async with admin.connect() as c:
        rows = []
        for query, params in [
            (
                """SELECT to_jsonb(t) FROM feature.features t WHERE feature_id=CAST(:id AS uuid)
OR name=:name""",
                dict(id=case.feature, name=case.name),
            ),
            (
                """SELECT to_jsonb(t) FROM feature.manual_feature_identity_claims t WHERE
name_key=lower(:name)""",
                dict(name=case.name),
            ),
            (
                """SELECT to_jsonb(t) FROM provider_sync.provider_feature_identities t WHERE
provider_dataset_id=:dataset AND natural_key=:natural""",
                dict(dataset=case.dataset, natural=case.natural),
            ),
            (
                "SELECT to_jsonb(t) FROM ops.feature_requests t WHERE request_id=CAST(:id AS uuid)",
                dict(id=case.request),
            ),
            (
                "SELECT to_jsonb(t) FROM ops.domain_command_results t WHERE command_id=:id",
                dict(id=case.command),
            ),
            (
                """SELECT to_jsonb(t) FROM feature.feature_creation_origins t WHERE
creation_command_id=:id""",
                dict(id=case.command),
            ),
        ]:
            rows.append((await c.scalars(text(query), params)).all())
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


async def _probe_unclaimed(admin, case, kind):
    # 미커밋 행은 count만으로 판정하지 않는다. 동일 unique identity를 실제 삽입·rollback한다.
    async with AsyncSession(admin) as observer:
        tx = await observer.begin()
        try:
            await observer.execute(text("SET LOCAL lock_timeout='150ms'"))
            assert await observer.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended('feature-write-all',0))")
            )
            if case.command:
                assert (
                    await observer.scalar(
                        text(
                            "SELECT command_id FROM ops.domain_commands "
                            "WHERE command_id=:id FOR UPDATE NOWAIT"
                        ),
                        dict(id=case.command),
                    )
                    == case.command
                )
            if kind == "approve":
                assert (
                    await observer.scalar(
                        text(
                            """SELECT request_id FROM ops.feature_requests
WHERE request_id=CAST(:id AS uuid)
FOR UPDATE NOWAIT"""
                        ),
                        dict(id=case.request),
                    )
                    == case.request
                )
            if kind in {"manual", "approve"}:
                await observer.execute(
                    text("""INSERT INTO feature.manual_feature_identity_claims(
feature_id,feature_kind,name_key,lon_e6,lat_e6,claimed_by_command_id,claim_basis,claimed_at)
SELECT
:probe,k.feature_kind,k.name_key,k.lon_e6,k.lat_e6,:command,'manual_create',clock_timestamp()
FROM feature.manual_feature_identity_key('place',:name,127.5,36.5) k"""),
                    dict(probe=uuid4(), command=case.command, name=case.name),
                )
            elif kind == "provider":
                await observer.execute(
                    text("""INSERT INTO provider_sync.provider_feature_identities(
provider_dataset_id,feature_kind,natural_key,feature_id,bound_by_operation)
VALUES(:dataset,'place',:natural,CAST(:feature AS uuid),'provider_sync')"""),
                    dict(dataset=case.dataset, natural=case.natural, feature=case.held_feature),
                )
            else:
                await observer.execute(
                    text("""INSERT INTO feature.features(feature_id,kind,name,category)
                  VALUES(CAST(:id AS uuid),'place',:name,'01070300')"""),
                    dict(id=case.feature, name=case.name),
                )
        finally:
            await tx.rollback()


async def _assert_created(admin, case, kind, result):
    assert result["o_row_revision"] >= 1
    if kind in {"manual", "approve"}:
        assert result["o_outcome"] == "created"
    else:
        assert result["o_inserted"] is True
    target = result["o_feature_id"]
    if kind != "provider":
        assert str(target) == case.feature
    async with admin.connect() as c:
        row = (
            await c.execute(
                text(
                    """SELECT name,lifecycle_state,publication_state,quality_state FROM
feature.features WHERE feature_id=:id"""
                ),
                dict(id=target),
            )
        ).one()
        assert tuple(row) == (case.name, "active", "published", "valid")
        assert (
            await c.scalar(
                text("SELECT count(*) FROM feature.feature_state_transitions WHERE feature_id=:id"),
                dict(id=target),
            )
            == 1
        )
        if kind == "provider":
            assert (
                await c.scalar(
                    text(
                        """SELECT feature_id FROM provider_sync.provider_feature_identities WHERE
provider_dataset_id=:ds AND natural_key=:key"""
                    ),
                    dict(ds=case.dataset, key=case.natural),
                )
                == target
            )
            assert (
                await c.scalar(
                    text("SELECT feature_id FROM feature.feature_aliases WHERE alias=:alias"),
                    dict(alias=case.alias),
                )
                == target
            )
        if kind in {"manual", "approve"}:
            assert (
                await c.scalar(
                    text(
                        """SELECT claimed_by_command_id FROM feature.manual_feature_identity_claims
WHERE
feature_id=:id"""
                    ),
                    dict(id=target),
                )
                == case.command
            )
            assert (
                await c.scalar(
                    text(
                        """SELECT creation_command_id FROM feature.feature_creation_origins WHERE
feature_id=:id"""
                    ),
                    dict(id=target),
                )
                == case.command
            )
        if kind == "approve":
            assert (
                await c.execute(
                    text(
                        """SELECT status,resolution_command_id,resolved_feature_id FROM
ops.feature_requests WHERE request_id=:id"""
                    ),
                    dict(id=case.request),
                )
            ).one() == ("approved", case.command, target)


@pytest.mark.parametrize("kind", _KINDS)
async def test_valid_creation_waits_before_identity_command_request_or_core(scalar_engines, kind):
    admin, runtime = scalar_engines
    case = await _case(admin, runtime, kind)
    attempt, owner, digest = await _plan(runtime, case.held_feature, case.dataset)
    started = asyncio.get_running_loop().create_future()

    async def write():
        async with AsyncSession(runtime) as s, s.begin():
            await s.execute(text("SET LOCAL lock_timeout='8s'"))
            started.set_result(int(await s.scalar(text("SELECT pg_backend_pid()"))))
            return await _apply(s, kind, case)

    task = None
    try:
        async with AsyncSession(runtime) as scoped, scoped.begin():
            assert (
                await begin_scoped_feature_write(
                    scoped, attempt_id=attempt, owner=owner, manifest_digest=digest
                )
            )["status"] == "applying"
            blocker = int(await scoped.scalar(text("SELECT pg_backend_pid()")))
            task = asyncio.create_task(write())
            pid = await asyncio.wait_for(asyncio.shield(started), 3)
            await _wait_protocol_blocker(admin, pid, blocker)
            assert not task.done()
            await _probe_unclaimed(admin, case, kind)
            assert (
                await finish_scoped_feature_write(
                    scoped, attempt_id=attempt, owner=owner, result_digest="e" * 64
                )
            )["status"] == "completed"
        result = await asyncio.wait_for(asyncio.shield(task), 6)
        await _assert_created(admin, case, kind, result)
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("kind", _KINDS)
async def test_creation_ex_blocks_other_backend_share_until_caller_rollback(scalar_engines, kind):
    admin, runtime = scalar_engines
    case = await _case(admin, runtime, kind)
    before = await _snapshot(admin, case)
    started = asyncio.get_running_loop().create_future()
    task = None

    async def share():
        async with AsyncSession(runtime) as s, s.begin():
            await s.execute(text("SET LOCAL lock_timeout='8s'"))
            started.set_result(int(await s.scalar(text("SELECT pg_backend_pid()"))))
            await s.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))

    try:
        async with AsyncSession(runtime) as creator:
            tx = await creator.begin()
            await _apply(creator, kind, case)
            blocker = int(await creator.scalar(text("SELECT pg_backend_pid()")))
            task = asyncio.create_task(share())
            pid = await asyncio.wait_for(asyncio.shield(started), 3)
            async with asyncio.timeout(3):
                while True:
                    async with admin.connect() as c:
                        blocked = await c.scalar(
                            text("""SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid
AND locktype='advisory'
AND classid=1369104691::oid AND objid=115::oid AND objsubid=2 AND
mode='ShareLock' AND NOT granted) AND :blocker=ANY(pg_blocking_pids(:pid))"""),
                            dict(pid=pid, blocker=blocker),
                        )
                    if blocked:
                        break
                    await asyncio.sleep(0.005)
            assert not task.done()
            await tx.rollback()
        await asyncio.wait_for(asyncio.shield(task), 3)
        assert await _snapshot(admin, case) == before
        async with AsyncSession(runtime) as fresh, fresh.begin():
            result = await _apply(fresh, kind, case)
        await _assert_created(admin, case, kind, result)
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("kind", _KINDS)
async def test_shared_upgrade_fails_before_dml_and_same_identity_retries(scalar_engines, kind):
    admin, runtime = scalar_engines
    case = await _case(admin, runtime, kind)
    before = await _snapshot(admin, case)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 gate와 실제 CALL
        async with AsyncSession(runtime) as s, s.begin():
            await s.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
            await _apply(s, kind, case)
    assert caught.value.orig.sqlstate == "23514"
    assert await _snapshot(admin, case) == before
    async with AsyncSession(runtime) as fresh, fresh.begin():
        result = await _apply(fresh, kind, case)
    await _assert_created(admin, case, kind, result)


@pytest.mark.parametrize("kind", _KINDS)
async def test_real_timeout_rolls_back_and_same_identity_retries(scalar_engines, kind):
    admin, runtime = scalar_engines
    case = await _case(admin, runtime, kind)
    before = await _snapshot(admin, case)
    async with AsyncSession(runtime) as holder, holder.begin():
        await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
        with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 gate와 실제 CALL
            async with AsyncSession(runtime) as s, s.begin():
                # approve 정본 proconfig5초는 그대로다. 다른3경로는 caller 유한값 보존.
                await s.execute(text("SET LOCAL lock_timeout='150ms'"))
                await _apply(s, kind, case)
        assert caught.value.orig.sqlstate == "55P03"
    assert await _snapshot(admin, case) == before
    async with AsyncSession(runtime) as fresh, fresh.begin():
        result = await _apply(fresh, kind, case)
    await _assert_created(admin, case, kind, result)


async def test_definition_inverse_hash_config_acl_and_create_privileges(scalar_engines):
    admin, _ = scalar_engines
    async with admin.connect() as c:
        rows = (
            (
                await c.execute(
                    text("""SELECT p.proname,p.prosrc,p.proconfig,p.prosecdef,
pg_get_function_identity_arguments(p.oid) AS
signature,r.rolname,p.proacl::text AS acl,
EXISTS(SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0) AS public
FROM pg_proc p JOIN pg_namespace n
ON n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner WHERE
n.nspname='feature' AND p.proname=ANY(CAST(:names AS text[]))"""),
                    dict(names=list(_migration._LEGACY_OWNERS)),
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 4
        for row in rows:
            assert row["prosrc"].count("  " + _migration._PROTOCOL + "\n") == 1
            assert row["prosrc"].partition("\nBEGIN\n")[2].lstrip().startswith(_migration._PROTOCOL)
            original = row["prosrc"].replace("  " + _migration._PROTOCOL + "\n", "", 1)
            assert (
                hashlib.sha256(original.encode()).hexdigest()
                == _migration._EXPECTED_DEFINITIONS[row["proname"]][1]
            )
            assert (
                hashlib.sha256(row["signature"].encode()).hexdigest()
                == _migration._EXPECTED_DEFINITIONS[row["proname"]][0]
            )
            assert row["rolname"] == _migration._LEGACY_OWNERS[row["proname"]]
            assert row["prosecdef"]
            expected = ["search_path=pg_catalog"]
            if row["proname"] == "approve_feature_request_with_initial_state":
                expected = ["search_path=pg_catalog, feature, ops, x_extension", "lock_timeout=5s"]
            assert row["proconfig"] == expected
            # 정본417은 세 owner 모두 feature CREATE를 이미 보유한다. 새로 제거하지 않는다.
            assert await c.scalar(
                text("SELECT has_schema_privilege(:role,'feature','CREATE')"),
                dict(role=row["rolname"]),
            )
            executors = {
                "approve_feature_request_with_initial_state": {
                    "ktm_feature_request_admin_executor"
                },
                "create_admin_manual_feature_with_initial_state": {
                    "ktm_manual_feature_admin_executor"
                },
                "create_feature_with_initial_state": {
                    "ktm_manual_feature_procedure_owner",
                    "ktm_curation_command_owner",
                    "ktm_feature_request_procedure_owner",
                    "ktm_feature_create_provider_executor",
                },
                "create_provider_feature_with_initial_state": {
                    "ktm_feature_create_provider_executor"
                },
            }
            owner = row["rolname"]
            expected_acl = {role + "=X/" + owner for role in executors[row["proname"]] | {owner}}
            assert set(row["acl"].strip("{}").split(",")) == expected_acl
            assert not row["public"]

        grantees = set(
            (
                await c.scalars(
                    text("""SELECT r.rolname FROM pg_proc p
CROSS JOIN LATERAL aclexplode(p.proacl) a JOIN
pg_roles r ON r.oid=a.grantee WHERE
p.oid='ops.lock_scoped_feature_write_protocol(boolean)'::regprocedure AND
a.privilege_type='EXECUTE'""")
                )
            ).all()
        )
        assert grantees == {
            "ktm_feature_state_procedure_owner",
            "ktm_curation_command_owner",
            "ktm_feature_schema_owner",
            "ktm_manual_provider_dedup_procedure_owner",
            "ktm_feature_runtime",
            "ktm_manual_feature_procedure_owner",
            "ktm_feature_request_procedure_owner",
        }


@pytest.mark.parametrize("regression", ["manual", "approve", "reject"])
async def test_existing_m01_m04_business_regressions_on_owned_bootstrap(scalar_engines, regression):
    # 기존 business assertion을 그대로 호출한다. 정본 role/ACL은 같은 bounded fresh bootstrap이다.
    from tests.integration import test_tvn_m01_manual_feature_create as m01
    from tests.integration import test_tvn_m04_feature_request_queue as m04

    admin, _ = scalar_engines
    approve = (
        m04.test_feature_request_submit_then_admin_approval_creates_only_manual_request_feature
    )
    checks = {
        "manual": m01.test_api_manual_create_writes_immutable_claim_and_origin_once,
        "approve": approve,
        "reject": m04.test_feature_request_admin_rejection_closes_the_request_without_a_feature,
    }
    await checks[regression](admin)
