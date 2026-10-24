"""field SQL·Python 선점 폐포를 실제 runtime/PG/ASGI로 검증한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import admin_feature_repo as repo
from kortravelmap.infra.feature_repo import lock_feature_curation_write
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
_CALLS = {
    "author": """CALL feature.author_feature_field_overrides(
        :feature,:revision,:actor,'field-416',:command,CAST(:values AS jsonb),'{}',
        NULL,NULL,NULL,NULL)""",
    "revoke": """CALL feature.revoke_feature_field_overrides(
        :feature,:revision,:actor,'field-416',:command,ARRAY['core.name'],
        NULL,NULL,NULL,NULL)""",
}
_ORIGINAL_BODY = {
    "author_feature_field_overrides": (
        "5f8361fab39f188f0a36afd1c74c23cea9e0dc81479cdd80f4aec8742a7fd8f3"
    ),
    "revoke_feature_field_overrides": (
        "c1f346b4baa68c1a069006a09e694dd97473016de1519afd069ea99b6e770bb8"
    ),
}


@dataclass
class Case:
    feature: str
    dataset: int
    entity: str
    actor: str
    revision: int
    command: int = 0

    def params(self):
        return dict(
            feature=UUID(self.feature),
            revision=self.revision,
            actor=self.actor,
            command=self.command,
            values=json.dumps({"core.name": "override"}),
        )


async def _case(admin, runtime):
    feature, datasets, entities = await _seed(admin)
    async with AsyncSession(runtime) as session, session.begin():
        await lock_feature_curation_write(session)
        await session.execute(
            text("""CALL feature.apply_provider_feature_field_patch(
            CAST(:feature AS uuid),:dataset,:entity,:record,1,
            '{"core.name":"base","place.phones":["010-base"]}','{}',NULL,NULL,NULL)"""),
            dict(
                feature=feature, dataset=datasets[0], entity=entities[0], record=entities[0] + "-r1"
            ),
        )
    async with AsyncSession(admin) as session:
        revision = await session.scalar(
            text(
                "SELECT row_revision FROM feature.features WHERE feature_id=CAST(:feature AS uuid)"
            ),
            dict(feature=feature),
        )
    return Case(feature, datasets[0], entities[0], "admin:field-416-" + uuid4().hex, revision)


async def _command(runtime, case, kind):
    operation = {
        "author": "admin.feature.override.author",
        "revoke": "admin.feature.override.revoke",
        "patch": "admin.feature.patch",
        "create": "admin.feature.create.manual-v1",
    }[kind]
    case.command = await _open_command(runtime, actor=case.actor, operation=operation)


async def _prepare(admin, runtime, kind):
    case = await _case(admin, runtime)
    if kind == "revoke":
        await _command(runtime, case, "author")
        async with AsyncSession(runtime) as session, session.begin():
            row = await _apply(session, "author", case)
            case.revision = row["o_row_revision"]
    await _command(runtime, case, kind)
    return case


def _payload(case):
    return dict(
        kind="place",
        name=case.actor,
        marker_icon="marker",
        marker_color="P-02",
        category="01070300",
        coord=dict(lon=127.5, lat=36.5),
        detail=dict(place_kind="attraction"),
    )


async def _apply(session, kind, case):
    if kind == "patch":
        return await repo.patch_admin_feature_with_field_overrides(
            session,
            case.feature,
            payload={"name": "override"},
            expected_row_revision=case.revision,
            reason_code="field-416",
            operator=case.actor,
            command_id=case.command,
        )
    if kind == "create":
        return await repo.create_admin_feature_with_field_overrides(
            session,
            payload=_payload(case),
            reason_code="field-416",
            operator=case.actor,
            command_id=case.command,
        )
    return (await session.execute(text(_CALLS[kind]), case.params())).mappings().one()


async def _state(admin, case):
    async with AsyncSession(admin) as session:
        rows = {}
        for relation in [
            "feature.features",
            "feature.feature_places",
            "feature.feature_base_field_values",
            "ops.feature_overrides",
            "feature.feature_state_transitions",
        ]:
            rows[relation] = list(
                (
                    await session.scalars(
                        text(
                            f"SELECT to_jsonb(row) FROM {relation} row "
                            "WHERE feature_id=CAST(:feature AS uuid) "
                            'ORDER BY to_jsonb(row)::text COLLATE "C"'
                        ),
                        dict(feature=case.feature),
                    )
                ).all()
            )
        rows["manual"] = list(
            (
                await session.scalars(
                    text(
                        "SELECT to_jsonb(row) FROM "
                        "feature.manual_feature_identity_claims row WHERE feature_id IN "
                        "(SELECT feature_id FROM feature.features WHERE name=:name)"
                    ),
                    dict(name=case.actor),
                )
            ).all()
        )
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("kind", ["author", "revoke", "patch", "create"])
async def test_valid_writer_waits_before_first_feature_or_manual_claim(scalar_engines, kind):
    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime, kind)
    attempt, owner, digest = await _plan(runtime, case.feature, case.dataset)
    started = asyncio.get_running_loop().create_future()

    async def write():
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout='8s'"))
            started.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            return await _apply(session, kind, case)

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
            async with AsyncSession(admin) as observer:
                # create가 protocol 대기 전에 claim/core를 쓰지 않았는지 직접 확인한다.
                assert (
                    await observer.scalar(
                        text("SELECT count(*) FROM feature.features WHERE name=:name"),
                        dict(name=case.actor),
                    )
                    == 0
                )
            assert (
                await finish_scoped_feature_write(
                    scoped, attempt_id=attempt, owner=owner, result_digest="f" * 64
                )
            )["status"] == "completed"
        result = await asyncio.wait_for(asyncio.shield(task), 5)
        assert result is not None
        async with AsyncSession(admin) as observer:
            if kind == "create":
                assert isinstance(result, repo.AdminManualFeatureCreated)
                assert (
                    await observer.scalar(
                        text(
                            "SELECT count(*) FROM "
                            "feature.manual_feature_identity_claims "
                            "WHERE feature_id=CAST(:id AS uuid)"
                        ),
                        dict(id=result.feature_id),
                    )
                    == 1
                )
            else:
                assert await observer.scalar(
                    text("SELECT name FROM feature.features WHERE feature_id=CAST(:id AS uuid)"),
                    dict(id=case.feature),
                ) == ("base" if kind == "revoke" else "override")
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("kind", ["author", "revoke", "patch", "create"])
async def test_shared_upgrade_rollback_and_new_transaction_retry(scalar_engines, kind):
    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime, kind)
    before = await _state(admin, case)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 gate와 실제 CALL
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
            await _apply(session, kind, case)
    assert caught.value.orig.sqlstate == "23514"
    assert await _state(admin, case) == before
    async with AsyncSession(runtime) as session, session.begin():
        assert await _apply(session, kind, case) is not None


@pytest.mark.parametrize("kind", ["author", "revoke", "patch", "create"])
async def test_caller_rollback_keeps_values_and_releases_gate(scalar_engines, kind):
    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime, kind)
    before = await _state(admin, case)
    async with AsyncSession(runtime) as session:
        tx = await session.begin()
        assert await _apply(session, kind, case) is not None
        await tx.rollback()
    assert await _state(admin, case) == before
    async with AsyncSession(admin) as observer, observer.begin():
        assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(1369104691,115)"))
        assert (
            await observer.scalar(
                text(
                    "SELECT 1 FROM feature.features WHERE "
                    "feature_id=CAST(:id AS uuid) FOR UPDATE NOWAIT"
                ),
                dict(id=case.feature),
            )
            == 1
        )
    async with AsyncSession(runtime) as session, session.begin():
        assert await _apply(session, kind, case) is not None


@pytest.mark.parametrize("name", _ORIGINAL_BODY)
async def test_original_body_acl_config_and_owner_are_preserved(scalar_engines, name):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        row = (
            await session.execute(
                text("""SELECT proc.prosrc,owner.rolname,proc.prosecdef,
            proc.proconfig,has_function_privilege('ktm_feature_runtime',proc.oid,'EXECUTE') allowed,
            NOT EXISTS(SELECT 1 FROM aclexplode(proc.proacl) acl WHERE acl.grantee=0) closed
            FROM pg_proc proc JOIN pg_namespace ns ON ns.oid=proc.pronamespace
            JOIN pg_roles owner ON owner.oid=proc.proowner
            WHERE ns.nspname='feature' AND proc.proname=:name"""),
                dict(name=name),
            )
        ).one()
    gate = "  PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
    assert row.prosrc.count(gate) == 1
    assert (
        hashlib.sha256(row.prosrc.replace(gate, "", 1).encode()).hexdigest() == _ORIGINAL_BODY[name]
    )
    assert row.rolname == "ktm_feature_state_procedure_owner"
    assert row.prosecdef
    assert row.allowed
    assert row.closed
    assert row.proconfig == ["search_path=pg_catalog"]
