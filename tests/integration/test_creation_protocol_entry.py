"""신규 생성4 SQL의 진입(P 없음)·유효값·rollback을 실제 owned PG로 검증한다.

ADR-117(435): 단건 생성은 P를 잡지 않는다. 434의 regime 진입 줄은 주석 한 줄로 바뀌었다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_feature_id
from tests.integration._owned_pg import _seed
from tests.integration._owned_pg import (
    scalar_container as scalar_container,
)
from tests.integration._owned_pg import scalar_engines as scalar_engines
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
#: 435(ADR-117)가 434의 regime 진입(``PERFORM ops.lock_single_feature_writer_protocol();``)을
#: 바꾼 주석 한 줄. 생성은 P를 잡지 않는다.
_ENTRY = "-- 435 ADR-117: 단건 writer는 P를 잡지 않는다(행 잠금과 ADR-111 gate)."
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


_PROTOCOL_LOCKS_OF_PID = """SELECT count(*) FROM pg_locks WHERE pid=:pid
AND locktype='advisory' AND classid=1369104691::oid AND objid=115::oid AND objsubid=2"""


@pytest.mark.parametrize("kind", _KINDS)
async def test_creation_holds_no_protocol_until_caller_rollback(scalar_engines, kind):
    admin, runtime = scalar_engines
    case = await _case(admin, runtime, kind)
    before = await _snapshot(admin, case)
    async with AsyncSession(runtime) as creator:
        tx = await creator.begin()
        await _apply(creator, kind, case)
        own = _PROTOCOL_LOCKS_OF_PID.replace(":pid", "pg_backend_pid()")
        assert await creator.scalar(text(own)) == 0
        # 다른 backend가 P EX를 곧바로 얻는다(생성이 P를 쥐지 않는다). 434까지는 P SH로 봤다.
        async with AsyncSession(runtime) as s, s.begin():
            await s.execute(text("SET LOCAL lock_timeout='150ms'"))
            await s.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await tx.rollback()
    assert await _snapshot(admin, case) == before
    async with AsyncSession(runtime) as fresh, fresh.begin():
        result = await _apply(fresh, kind, case)
    await _assert_created(admin, case, kind, result)


@pytest.mark.parametrize("kind", _KINDS)
async def test_creation_completes_while_a_load_holds_protocol_ex_and_feature_rows(
    scalar_engines, kind
):
    """적재가 P EX와 기존 Feature 행을 쥔 동안에도 신규 생성은 P를 요청하지 않고 끝난다.

    434까지는 applying scoped kernel(P SH + manifest 행)과 load EX 두 blocker를 봤다. ADR-117이
    kernel을 지웠으므로 적재와 같은 모양(P EX → 기존 Feature 행 FOR UPDATE) 하나로 본다.
    """
    admin, runtime = scalar_engines
    case = await _case(admin, runtime, kind)
    async with AsyncSession(admin) as holder, holder.begin():
        await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        await holder.execute(
            text("SELECT 1 FROM feature.features WHERE feature_id=CAST(:id AS uuid) FOR UPDATE"),
            dict(id=case.held_feature),
        )
        async with AsyncSession(runtime) as s, s.begin():
            # 종전(418)에는 이 짧은 상한에서 55P03이었다. 434부터 생성은 P를 기다리지 않는다.
            await s.execute(text("SET LOCAL lock_timeout='150ms'"))
            result = await _apply(s, kind, case)
            own = _PROTOCOL_LOCKS_OF_PID.replace(":pid", "pg_backend_pid()")
            assert await s.scalar(text(own)) == 0
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
            # 418의 P EX 첫 줄이 434에서 regime 진입, 435(ADR-117)에서 주석 한 줄로 바뀌었다.
            assert "lock_scoped_feature_write_protocol" not in row["prosrc"]
            assert "lock_single_feature_writer_protocol" not in row["prosrc"]
            assert row["prosrc"].count("  " + _ENTRY + "\n") == 1
            assert row["prosrc"].partition("\nBEGIN\n")[2].lstrip().startswith(_ENTRY)
            original = row["prosrc"].replace("  " + _ENTRY + "\n", "", 1)
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
        # 435(ADR-117)가 434의 regime 진입 함수를 지웠다.
        assert (
            await c.scalar(
                text("SELECT to_regprocedure('ops.lock_single_feature_writer_protocol()')")
            )
            is None
        )


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
