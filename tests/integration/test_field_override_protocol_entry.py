"""field SQL·Python 선점 폐포를 실제 runtime/PG/ASGI로 검증한다.

ADR-117(435): 단건 writer는 P를 잡지 않는다(행 잠금과 ADR-111 gate만). 434의 정책 활성화(epoch>0)
세계와 regime 진입은 사라졌으므로, 이 모듈은 한 세계만 본다. HTTP 503은 P가 아니라 같은 Feature
행을 쥔 적재 뒤의 행 잠금 대기에서 난다.
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
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.feature_repo import lock_feature_curation_write
from tests.integration._owned_pg import _seed
from tests.integration._owned_pg import (
    scalar_container as scalar_container,
)
from tests.integration._owned_pg import scalar_engines as scalar_engines
from tests.integration.test_admin_override_protocol_entry import (
    _wait_row_blocker_without_protocol,
)
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
async def test_writer_waits_only_on_the_same_feature_row(scalar_engines, kind, same_feature):
    """단건 writer는 적재(P EX → Feature 행) 뒤에서 P가 아니라 같은 Feature 행에서만 기다린다.

    다른 Feature와 신규 생성은 적재가 열려 있는 동안 끝난다. 434까지는 applying scoped kernel
    (P SH + manifest 행)을 blocker로 썼다. ADR-117이 kernel을 지웠으므로 적재 모양으로 본다.
    """
    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime, kind)
    held = case if same_feature else await _case(admin, runtime)
    started = asyncio.get_running_loop().create_future()

    async def write():
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout='8s'"))
            started.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            return await _apply(session, kind, case)

    task = None
    try:
        async with AsyncSession(admin) as holder, holder.begin():
            await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
            await holder.execute(
                text(
                    "SELECT 1 FROM feature.features WHERE feature_id=CAST(:id AS uuid) FOR UPDATE"
                ),
                dict(id=held.feature),
            )
            blocker = int(await holder.scalar(text("SELECT pg_backend_pid()")))
            task = asyncio.create_task(write())
            pid = await asyncio.wait_for(asyncio.shield(started), 3)
            if same_feature and kind != "create":
                await _wait_row_blocker_without_protocol(admin, pid, blocker, task)
                assert not task.done()
            else:
                # 종전(414~418)에는 여기서 P EX를 기다렸다. 이제 행이 겹치지 않으면 끝난다.
                await asyncio.wait_for(asyncio.shield(task), 8)
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
async def test_writer_finishes_while_a_load_holds_protocol_ex(scalar_engines, kind):
    """적재가 P EX를 쥔 동안에도 다른 Feature의 관리 writer는 끝난다(종전 503, 434 DC-1·ADR-117)."""
    admin, runtime = scalar_engines
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
    # 416의 P EX 첫 줄이 434에서 regime 진입, 435(ADR-117)에서 주석 한 줄로 바뀌었다.
    gate = "  -- 435 ADR-117: 단건 writer는 P를 잡지 않는다(행 잠금과 ADR-111 gate).\n"
    assert "lock_scoped_feature_write_protocol" not in row.prosrc
    assert "lock_single_feature_writer_protocol" not in row.prosrc
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


@pytest.mark.parametrize("kind", ["author", "revoke", "patch"])
async def test_http_lock_timeout_rolls_back_and_retry_is_valid(scalar_engines, kind, monkeypatch):
    """같은 Feature 행을 쥔 적재 뒤에서 단건 writer는 행 대기 끝에 503이고 재시도가 유효하다.

    434까지는 regime(epoch>0) 진입이 P SH holder 뒤의 P EX 대기로 503을 냈다. ADR-117이 그
    진입을 지웠으므로 대기는 Feature 행에서 난다. 신규 생성(``create``)은 기존 행이 없어
    적재가 막을 자리가 없다 — 그것이 ADR-117의 결과이므로 이 503 경로에서 뺀다.
    """
    admin, runtime = scalar_engines
    case = await _prepare(admin, runtime, kind)
    # runtime 역할에는 lock_timeout 기본값이 없다(P 함수가 0이면 1s로 묶던 것과 다르다).
    # 행 대기가 영원히 걸리지 않도록 이 요청 engine에만 상한을 둔다.
    bounded = make_async_engine(
        runtime.url.render_as_string(hide_password=False),
        pool_size=2,
        server_settings={"lock_timeout": "1000"},
    )
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
        async with AsyncSession(bounded) as session:
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
    }[kind]
    url = "/v1/admin/features/" + case.feature + suffix
    body = {
        "author": dict(reason_code="field-416", values={"core.name": "http"}),
        "revoke": dict(reason_code="field-416", field_paths=["core.name"]),
        "patch": dict(reason="field-416", name="http"),
    }[kind]
    method = "PATCH" if kind == "patch" else "POST"
    before = await _state(admin, case)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            async with AsyncSession(admin) as holder, holder.begin():
                await holder.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
                await holder.execute(
                    text(
                        "SELECT 1 FROM feature.features "
                        "WHERE feature_id=CAST(:id AS uuid) FOR UPDATE"
                    ),
                    dict(id=case.feature),
                )
                response = await client.request(method, url, headers=headers, json=body)
                assert response.status_code == 503, response.text
                assert response.json()["code"] == "LOCK_TIMEOUT"
                assert response.headers["Retry-After"] == "5"
            assert await _state(admin, case) == before
            response = await client.request(method, url, headers=headers, json=body)
            assert response.status_code == 200, response.text
            replay = await client.request(method, url, headers=headers, json=body)
            assert replay.status_code == response.status_code
            assert replay.json()["data"] == response.json()["data"]
    finally:
        await bounded.dispose()


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
