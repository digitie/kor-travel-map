"""433 READY reset의 실제 ACL·runtime 시작 경계를 독립적으로 검증한다."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import db as runtime_db
from kortravelmap.infra import runtime_privileges as acl
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_expired_plan_reset import (
    _bounded,
    _registered,
    _state,
)
from tests.integration.test_provider_snapshot_expired_plan_reset import (
    _release_this_case_ready_plans as _release_this_case_ready_plans,
)
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(50)]
_SIGNATURE = "ops.reset_ready_provider_snapshot_plan(uuid,bigint,uuid,uuid,uuid,text)"
_RESET_READY = """SELECT ops.reset_ready_provider_snapshot_plan(
    CAST(:snapshot AS uuid),:generation,CAST(:fence AS uuid),
    CAST(:attempt AS uuid),CAST(:owner AS uuid),:manifest)"""


async def test_ready_reset433_catalog_owner_search_path_and_execute_acl(scalar_engines):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        await _bounded(session)
        assert (await session.scalars(text("SELECT version_num FROM alembic_version"))).all() == [
            "433_snapshot_ready_plan_reset"
        ]
        routine = (
            (
                await session.execute(
                    text("""SELECT owner.rolname AS owner,p.prosecdef,p.proconfig,
                p.prokind::text AS prokind
                FROM pg_proc p JOIN pg_roles owner ON owner.oid=p.proowner
                WHERE p.oid=to_regprocedure(:signature)"""),
                    {"signature": _SIGNATURE},
                )
            )
            .mappings()
            .one()
        )
        assert dict(routine) == {
            "owner": "ktm_curation_command_owner",
            "prosecdef": True,
            "proconfig": ["search_path=pg_catalog"],
            "prokind": "f",
        }
        acl = (
            await session.execute(
                text("""SELECT COALESCE(grantee.rolname,'PUBLIC') AS grantee,
                grantor.rolname AS grantor,a.privilege_type,a.is_grantable
                FROM pg_proc p CROSS JOIN LATERAL
                aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
                LEFT JOIN pg_roles grantee ON grantee.oid=a.grantee
                JOIN pg_roles grantor ON grantor.oid=a.grantor
                WHERE p.oid=to_regprocedure(:signature)"""),
                {"signature": _SIGNATURE},
            )
        ).all()
        # PUBLIC은 pg_roles에 없는 pseudo-role이다. 유효 ACL의 grantee=0도 함께
        # 대조하므로 PUBLIC/base runtime/service 직접 EXECUTE 재부여를 검출한다.
        assert set(map(tuple, acl)) == {
            (role, "ktm_curation_command_owner", "EXECUTE", False)
            for role in ("ktm_curation_command_owner", "ktm_curation_provider_executor")
        }
        for role, expected in (
            ("ktm_feature_runtime", False),
            ("ktm_curation_provider_executor", True),
            ("ktm_feature_service", True),
        ):
            assert (
                await session.scalar(
                    text("SELECT has_function_privilege(:role,:signature,'EXECUTE')"),
                    {"role": role, "signature": _SIGNATURE},
                )
                is expected
            )


async def test_ready_reset_base_runtime_denied_service_inherited_access_rolls_back(scalar_engines):
    admin, runtime = scalar_engines
    _, args = await _registered(scalar_engines)
    before = await _state(admin, args)
    async with AsyncSession(admin) as session:
        await _bounded(session)
        await session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
        assert await session.scalar(text("SELECT current_user")) == "ktm_feature_runtime"
        # 정상 args를 사용해 인자 불일치가 아닌 진입 권한으로 거부되는지 확인한다.
        with pytest.raises(DBAPIError) as caught:
            await session.scalar(text(_RESET_READY), args)
        assert caught.value.orig.sqlstate == "42501"
        await session.rollback()
    assert await _state(admin, args) == before

    async with AsyncSession(runtime) as session:
        await _bounded(session)
        assert await session.scalar(text("SELECT current_user")) == "ktm_feature_service"
        assert await session.scalar(text(_RESET_READY), args) == "reset"
        # 이 testcase는 ACL 진입만 검증한다. 상태 변경 성공·경합 검증은 별도 caller
        # 시험이 소유하며, 여기서는 성공한 변경도 rollback해 canonical READY를 보존한다.
        await session.rollback()
    assert await _state(admin, args) == before


async def test_ready_reset433_public_startup_accepts_current_rejects_old_sd_expectation(
    scalar_engines, monkeypatch
):
    _, runtime = scalar_engines
    await runtime_db.assert_runtime_db_privilege_boundary(
        runtime, expected_login="ktm_feature_service"
    )
    expected = runtime_db._EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS
    assert _SIGNATURE in expected["ktm_feature_service"]
    old_expected = dict(expected)
    old_expected["ktm_feature_service"] = expected["ktm_feature_service"] - {_SIGNATURE}
    # 구432 전체 binary가 아니라 새 SD 함수 하나가 없던 기대 집합만 test-local로
    # 재현한다. 실제 catalog 조회·head 검사·역할 검사·public startup은 그대로다.
    with monkeypatch.context() as context:
        context.setattr(
            runtime_db, "_EXPECTED_RUNTIME_APPLICATION_SECURITY_DEFINER_FUNCTIONS", old_expected
        )
        with pytest.raises(runtime_db.RuntimeDbPrivilegeBoundaryError) as caught:
            await runtime_db.assert_runtime_db_privilege_boundary(
                runtime, expected_login="ktm_feature_service"
            )
        assert str(caught.value) == (
            "runtime DB privilege preflight failed: runtime login must not EXECUTE unexpected "
            "application SECURITY DEFINER functions: " + _SIGNATURE
        )
    await runtime_db.assert_runtime_db_privilege_boundary(
        runtime, expected_login="ktm_feature_service"
    )


async def test_ready_reset_command_owner_scope_read_is_exactly_three_columns(scalar_engines):
    admin, _ = scalar_engines
    dataset, args = await _registered(scalar_engines)
    async with AsyncSession(admin) as session:
        await _bounded(session)
        rows = (
            await session.execute(
                text("""SELECT a.attname,
            has_column_privilege('ktm_curation_command_owner',a.attrelid,a.attnum,'SELECT')
            FROM pg_attribute a WHERE a.attrelid='ops.feature_write_dataset_scopes'::regclass
              AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum""")
            )
        ).all()
    assert {name for name, allowed in rows if allowed} == {"provider_dataset_id", "epoch", "owner"}
    async with AsyncSession(admin) as session, session.begin():
        await _bounded(session)
        await session.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
        row = (
            await session.execute(
                text("""SELECT epoch,owner FROM ops.feature_write_dataset_scopes
            WHERE provider_dataset_id=:dataset"""),
                {"dataset": dataset},
            )
        ).one()
        assert row.epoch > 0
        assert str(row.owner) == args["attempt"]
    for role, statement in [
        ("ktm_curation_command_owner", "SELECT lease_until FROM ops.feature_write_dataset_scopes"),
        ("ktm_feature_service", "SELECT epoch FROM ops.feature_write_dataset_scopes"),
    ]:
        async with AsyncSession(admin) as session:
            await session.begin()
            await _bounded(session)
            await session.execute(text("SET LOCAL ROLE " + role))
            with pytest.raises(DBAPIError) as denied:
                await session.scalar(
                    text(statement + " WHERE provider_dataset_id=:dataset"), {"dataset": dataset}
                )
            assert denied.value.orig.sqlstate == "42501"
            await session.rollback()

    # 전체432 DB/구binary 시험이 아니다. 새 함수가 아직 없는 catalog 경계에서
    # 새3열 grant가 생기지 않음을 같은433 fixture의 rollback-only TX로 검증한다.
    async with AsyncSession(admin) as session:
        await session.begin()
        try:
            await _bounded(session)
            await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            await session.execute(
                text(
                    "REVOKE SELECT(provider_dataset_id,epoch,owner) "
                    "ON TABLE ops.feature_write_dataset_scopes FROM ktm_curation_command_owner"
                )
            )
            await session.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
            await session.execute(text("DROP FUNCTION " + _SIGNATURE))
            await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
            for statement in acl._SNAPSHOT_READY_RESET_SCOPE_OWNER_ACL:
                await session.execute(text(statement))
            assert not await session.scalar(
                text(
                    "SELECT has_column_privilege('ktm_curation_command_owner',"
                    "'ops.feature_write_dataset_scopes','provider_dataset_id','SELECT') "
                    "OR has_column_privilege('ktm_curation_command_owner',"
                    "'ops.feature_write_dataset_scopes','epoch','SELECT') "
                    "OR has_column_privilege('ktm_curation_command_owner',"
                    "'ops.feature_write_dataset_scopes','owner','SELECT')"
                )
            )
        finally:
            await session.rollback()
    async with AsyncSession(admin) as session:
        await _bounded(session)
        assert await session.scalar(
            text("SELECT to_regprocedure(:signature) IS NOT NULL"), {"signature": _SIGNATURE}
        )
        for column in ("provider_dataset_id", "epoch", "owner"):
            assert await session.scalar(
                text(
                    "SELECT has_column_privilege('ktm_curation_command_owner',"
                    "'ops.feature_write_dataset_scopes',:column,'SELECT')"
                ),
                {"column": column},
            )
