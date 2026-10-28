"""field SQL·Python 선점 폐포를 실제 runtime/PG/ASGI로 검증한다.

434 DC-1 이후 이 모듈은 두 세계를 순서대로 본다. 앞쪽 테스트는 정책 활성화 전(epoch=0)이라
단건 writer가 P를 잡지 않는다. 활성화 테스트가 epoch를 올린 뒤의 HTTP 503 테스트는 regime
진입이 P EX를 기다리는 경로다(``_ensure_regime``이 단독 실행에서도 그 세계를 만든다).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
from kortravelmap.api import db as api_db
from kortravelmap.api.app import create_app
from kortravelmap.api.http_revision import revision_etag
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import admin_feature_repo as repo
from kortravelmap.infra.feature_repo import lock_feature_curation_write
from kortravelmap.infra.scoped_feature_writes import (
    begin_scoped_feature_write,
    finish_scoped_feature_write,
)
from tests.integration.test_admin_override_protocol_entry import (
    _wait_row_blocker_without_protocol,
)
from tests.integration.test_provider_field_scalar_projection import (
    _activate,
    _plan,
    _refresh,
    _seed,
)
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
            CAST(:values AS jsonb),'{}',NULL,NULL,NULL)"""),
            dict(
                feature=feature,
                dataset=datasets[0],
                entity=entities[0],
                record=entities[0] + "-r1",
                values=json.dumps({"core.name": "base", "place.phones": ["010-base"]}),
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


_OWN_PROTOCOL_MODES = """SELECT mode FROM pg_locks WHERE pid=pg_backend_pid()
AND locktype='advisory' AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
AND granted"""


async def _epoch(admin) -> int:
    async with AsyncSession(admin) as session:
        return int(
            await session.scalar(
                text("SELECT epoch FROM feature.provider_field_policy_epoch WHERE singleton")
            )
        )


async def _ensure_regime(admin, runtime) -> None:
    """epoch>0을 보장한다. 이 모듈의 활성화 테스트가 이미 올렸으면 그대로 둔다."""
    if await _epoch(admin) == 0:
        other = await _case(admin, runtime)
        await _activate(admin, other.feature)
    assert await _epoch(admin) > 0


@pytest.mark.parametrize(
    ("kind", "same_feature"),
    [
        ("author", True),
        ("author", False),
        ("revoke", True),
        ("revoke", False),
        ("patch", True),
        ("patch", False),
        ("create", True),
    ],
)
async def test_epoch0_writer_waits_only_on_the_same_feature_row(
    scalar_engines, kind, same_feature
):
    """434 DC-1: epoch=0의 단건 writer는 applying kernel의 P SH 뒤에 줄 서지 않는다.

    같은 Feature면 kernel이 잡은 Feature 행에서만 기다리고, 다른 Feature와 신규 생성은
    kernel이 열려 있는 동안 끝난다. 이 모듈의 활성화 테스트보다 앞에 있어야 epoch=0이다.
    """
    admin, runtime = scalar_engines
    assert await _epoch(admin) == 0
    case = await _prepare(admin, runtime, kind)
    held = case if same_feature else await _case(admin, runtime)
    attempt, owner, digest = await _plan(runtime, held.feature, held.dataset)
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
            if same_feature and kind != "create":
                await _wait_row_blocker_without_protocol(admin, pid, blocker, task)
                assert not task.done()
            else:
                # 종전(414~418)에는 여기서 P EX를 기다렸다. 이제 kernel과 겹치지 않으면 끝난다.
                await asyncio.wait_for(asyncio.shield(task), 8)
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
async def test_epoch0_writer_under_shared_protocol_does_not_upgrade(scalar_engines, kind):
    """434 DC-1: epoch=0이면 SH caller 안에서도 승격 없이 쓴다.

    epoch>0의 SH→EX 승격 거부(23514)는 ``test_single_writer_regime_entry.py``가 본다.
    """
    admin, runtime = scalar_engines
    assert await _epoch(admin) == 0
    case = await _prepare(admin, runtime, kind)
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
        assert await _apply(session, kind, case) is not None
        modes = (await session.scalars(text(_OWN_PROTOCOL_MODES))).all()
    assert modes == ["ShareLock"]


@pytest.mark.parametrize("kind", ["author", "revoke", "patch", "create"])
async def test_epoch0_writer_finishes_while_a_load_holds_protocol_ex(scalar_engines, kind):
    """434 DC-1: 적재가 P EX를 쥔 동안에도 다른 Feature의 관리 writer는 끝난다(종전 503)."""
    admin, runtime = scalar_engines
    assert await _epoch(admin) == 0
    case = await _prepare(admin, runtime, kind)
    async with AsyncSession(runtime) as holder, holder.begin():
        await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout='300ms'"))
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
    # 434 DC-1: 416의 P EX 첫 줄이 같은 자리의 regime 진입으로 바뀌었다.
    gate = "  PERFORM ops.lock_single_feature_writer_protocol();\n"
    assert "lock_scoped_feature_write_protocol" not in row.prosrc
    assert row.prosrc.count(gate) == 1
    assert row.prosrc.partition("\nBEGIN\n")[2].startswith(gate)
    assert (
        hashlib.sha256(row.prosrc.replace(gate, "", 1).encode()).hexdigest() == _ORIGINAL_BODY[name]
    )
    assert row.rolname == "ktm_feature_state_procedure_owner"
    assert row.prosecdef
    assert row.allowed
    assert row.closed
    assert row.proconfig == ["search_path=pg_catalog"]


async def _revision(admin, case):
    async with AsyncSession(admin) as observer:
        return int(
            await observer.scalar(
                text(
                    "SELECT row_revision FROM feature.features WHERE feature_id=CAST(:id AS uuid)"
                ),
                dict(id=case.feature),
            )
        )


async def test_active_override_survives_scoped_sql_reprojection_then_revoke(scalar_engines):
    admin, runtime = scalar_engines
    case = await _case(admin, runtime)
    await _activate(admin, case.feature)
    case.revision = await _revision(admin, case)
    await _command(runtime, case, "author")
    async with AsyncSession(runtime) as session, session.begin():
        result = await repo.author_admin_feature_field_overrides(
            session,
            case.feature,
            expected_row_revision=case.revision,
            reason_code="field-416",
            operator=case.actor,
            command_id=case.command,
            values={"core.name": "operator", "place.phones": ["010-operator"]},
            geometry_wkt={},
        )
        assert result.applied_field_count == 2
    record, source_hash = await _refresh(
        runtime,
        case.feature,
        case.dataset,
        case.entity,
        {"core.name": "fresh-base", "place.phones": ["010-fresh"]},
    )
    async with AsyncSession(admin) as observer:
        effective = (
            await observer.execute(
                text(
                    "SELECT name,phones FROM feature.features "
                    "JOIN feature.feature_places USING(feature_id) "
                    "WHERE feature_id=CAST(:id AS uuid)"
                ),
                dict(id=case.feature),
            )
        ).one()
        assert tuple(effective) == ("operator", ["010-operator"])
        bases = (
            await observer.execute(
                text(
                    "SELECT field_path,value_json,source_record_key,"
                    "source_raw_payload_hash FROM feature.feature_base_field_values "
                    "WHERE feature_id=CAST(:id AS uuid) ORDER BY field_path"
                ),
                dict(id=case.feature),
            )
        ).all()
        assert {row.field_path: row.value_json for row in bases} == {
            "core.name": "fresh-base",
            "place.phones": ["010-fresh"],
        }
        assert all(row.source_record_key == record for row in bases)
        assert all(row.source_raw_payload_hash == source_hash for row in bases)
    case.revision = await _revision(admin, case)
    await _command(runtime, case, "revoke")
    async with AsyncSession(runtime) as session, session.begin():
        result = await repo.revoke_admin_feature_field_overrides(
            session,
            case.feature,
            expected_row_revision=case.revision,
            reason_code="field-416",
            operator=case.actor,
            command_id=case.command,
            field_paths=["core.name", "place.phones"],
        )
        assert result.applied_field_count == 2
    async with AsyncSession(admin) as observer:
        effective = (
            await observer.execute(
                text(
                    "SELECT name,phones FROM feature.features "
                    "JOIN feature.feature_places USING(feature_id) "
                    "WHERE feature_id=CAST(:id AS uuid)"
                ),
                dict(id=case.feature),
            )
        ).one()
        assert tuple(effective) == ("fresh-base", ["010-fresh"])
        assert (
            await observer.scalar(
                text(
                    "SELECT count(*) FROM ops.feature_overrides WHERE "
                    "feature_id=CAST(:id AS uuid) AND status='active'"
                ),
                dict(id=case.feature),
            )
            == 0
        )


@pytest.mark.parametrize(
    ("path", "value"), [("core.category", "01010200"), ("core.address", {"road": "denied"})]
)
async def test_active_unsupported_fields_still_rollback(scalar_engines, path, value):
    admin, runtime = scalar_engines
    case = await _case(admin, runtime)
    await _activate(admin, case.feature)
    case.revision = await _revision(admin, case)
    await _command(runtime, case, "author")
    before = await _state(admin, case)
    params = case.params()
    params["values"] = json.dumps({path: value})
    with pytest.raises(DBAPIError) as caught:
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text(_CALLS["author"]), params)
    assert caught.value.orig.sqlstate == "23514"
    assert await _state(admin, case) == before


@pytest.mark.parametrize("kind", ["author", "revoke", "patch", "create"])
async def test_http_lock_timeout_rolls_back_and_retry_is_valid(scalar_engines, kind, monkeypatch):
    """regime(epoch>0)의 단건 writer는 P EX를 기다리다 503으로 끝나고 재시도가 유효하다."""
    admin, runtime = scalar_engines
    await _ensure_regime(admin, runtime)
    case = await _prepare(admin, runtime, kind)
    app = create_app(
        ApiSettings(
            admin_proxy_secret="field-416-local-proxy-credential-000000000000",
            admin_manual_feature_create_enabled=True,
            admin_feature_create_token_sha256=hashlib.sha256(b"field-416-local-create").hexdigest(),
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def session_dependency():
        async with AsyncSession(runtime) as session:
            yield session

    app.dependency_overrides[api_db.get_session] = session_dependency
    headers = {
        "X-Kor-Travel-Map-Admin-Proxy-Secret": "field-416-local-proxy-credential-000000000000",
        "X-Kor-Travel-Map-Actor": case.actor,
        "Idempotency-Key": str(uuid4()),
        "If-Match": revision_etag(case.revision),
        "X-Kor-Travel-Map-Admin-Feature-Create-Token": "field-416-local-create",
    }
    suffix = {
        "author": "/field-overrides",
        "revoke": "/field-overrides/revoke",
        "patch": "",
        "create": "",
    }[kind]
    url = "/v1/admin/features" + ("" if kind == "create" else "/" + case.feature + suffix)
    body = {
        "author": dict(reason_code="field-416", values={"core.name": "http"}),
        "revoke": dict(reason_code="field-416", field_paths=["core.name"]),
        "patch": dict(reason="field-416", name="http"),
        "create": dict(_payload(case), reason="field-416"),
    }[kind]
    method = "PATCH" if kind == "patch" else "POST"
    before = await _state(admin, case)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        async with AsyncSession(admin) as holder, holder.begin():
            await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(false)"))
            response = await client.request(method, url, headers=headers, json=body)
            assert response.status_code == 503, response.text
            assert response.json()["code"] == "LOCK_TIMEOUT"
            assert response.headers["Retry-After"] == "5"
        assert await _state(admin, case) == before
        response = await client.request(method, url, headers=headers, json=body)
        assert response.status_code == (201 if kind == "create" else 200), response.text
        replay = await client.request(method, url, headers=headers, json=body)
        assert replay.status_code == response.status_code
        assert replay.json()["data"] == response.json()["data"]


@pytest.mark.parametrize("sqlstate", ["23514", "40001", "XX000"])
async def test_create_other_database_errors_remain_private_500(
    scalar_engines, sqlstate, monkeypatch
):
    from kortravelmap.api.routers import admin_features as router

    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime, "create")
    app = create_app(
        ApiSettings(
            admin_proxy_secret="field-416-local-proxy-credential-000000000000",
            admin_manual_feature_create_enabled=True,
            admin_feature_create_token_sha256=hashlib.sha256(b"field-416-local-create").hexdigest(),
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def session_dependency():
        async with AsyncSession(runtime) as session:
            yield session

    app.dependency_overrides[api_db.get_session] = session_dependency
    original = router.create_admin_feature_with_field_overrides

    async def fault(session, **_kwargs):
        # owned PG가 실제 SQLSTATE를 낸다. handler/권한 검사를 fake로 바꾸지 않는다.
        await session.execute(
            text(
                "DO $$ BEGIN RAISE EXCEPTION 'private-field-416-db-detail' "
                "USING ERRCODE='" + sqlstate + "'; END $$"
            )
        )

    monkeypatch.setattr(router, "create_admin_feature_with_field_overrides", fault)
    headers = {
        "X-Kor-Travel-Map-Admin-Proxy-Secret": "field-416-local-proxy-credential-000000000000",
        "X-Kor-Travel-Map-Actor": case.actor,
        "Idempotency-Key": str(uuid4()),
        "X-Kor-Travel-Map-Admin-Feature-Create-Token": "field-416-local-create",
    }
    before = await _state(admin, case)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/admin/features", headers=headers, json=dict(_payload(case), reason="field-416")
        )
        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
        assert "private-field-416-db-detail" not in response.text
        assert sqlstate not in response.text
        assert "Retry-After" not in response.headers
        assert await _state(admin, case) == before
        async with AsyncSession(admin) as observer:
            assert (
                await observer.scalar(
                    text(
                        "SELECT count(*) FROM ops.domain_command_results r "
                        "JOIN ops.domain_commands c USING(command_id) WHERE c.actor=:actor"
                    ),
                    dict(actor=case.actor),
                )
                == 0
            )
        # 같은 key를 다시 쓸 수 있어야 앞선 claim도 rollback됐음을 증명한다.
        monkeypatch.setattr(router, "create_admin_feature_with_field_overrides", original)
        response = await client.post(
            "/v1/admin/features", headers=headers, json=dict(_payload(case), reason="field-416")
        )
        assert response.status_code == 201, response.text


@pytest.mark.parametrize("kind", ["author", "revoke"])
async def test_ungranted_owner_cannot_execute_field_entry(scalar_engines, kind):
    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime, kind)
    before = await _state(admin, case)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 실제 비인가 role과 CALL 경계
        async with AsyncSession(admin) as session, session.begin():
            await session.execute(text("SET LOCAL ROLE ktm_manual_feature_procedure_owner"))
            await _apply(session, kind, case)
    assert caught.value.orig.sqlstate == "42501"
    assert await _state(admin, case) == before
