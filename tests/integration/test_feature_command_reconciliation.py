"""Pinvi #668: 실제 HTTP/auth/PostgreSQL의 명령 부재 영구 확정."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from kortravelmap.api.app import create_app
from kortravelmap.api.auth import ADMIN_ACTOR_HEADER, ADMIN_PROXY_SECRET_HEADER
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def command_client(migrated_engine: AsyncEngine):
    credential = "reconcile-fixture-" + uuid4().hex
    actor = "admin:reconcile-" + uuid4().hex
    app = create_app(
        ApiSettings(
            _env_file=None,
            admin_routes_enabled=True,
            features_routes_enabled=False,
            debug_routes_enabled=False,
            ops_routes_enabled=False,
            api_call_log_enabled=False,
            prometheus_metrics_enabled=False,
            admin_proxy_secret=credential,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_session] = session
    headers = {ADMIN_PROXY_SECRET_HEADER: credential, ADMIN_ACTOR_HEADER: actor}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://map.test"
    ) as client:
        yield client, headers, actor


def _intent(actor: str, *, operation: str = "admin.feature.patch") -> dict:
    payload = {"reason": "original mutation", "operator": "legacy-ignored"}
    if operation.endswith("patch"):
        payload["name"] = "reconciled name"
    return {
        "operation": operation,
        "feature_id": str(uuid4()),
        "payload": payload,
        "expected_revision": '"1"',
        "idempotency_key": str(uuid4()),
        "expected_actor": actor,
        "access_reason": "confirm uncertain command safely",
    }


async def test_absent_command_is_sealed_and_late_original_request_cannot_execute(
    command_client, migrated_engine: AsyncEngine
):
    client, headers, actor = command_client
    body = _intent(actor)
    response = await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["state"] == "abandoned"
    assert data["actor"] == actor
    assert data["idempotency_key"] == body["idempotency_key"]
    async with AsyncSession(migrated_engine) as db:
        record = (
            await db.execute(
                text("""
            SELECT c.actor, r.response_status, r.response_body
            FROM ops.domain_commands c JOIN ops.domain_command_results r USING(command_id)
            WHERE c.idempotency_key=CAST(:key AS uuid) AND c.actor=:actor
        """),
                {"key": body["idempotency_key"], "actor": actor},
            )
        ).one()
        assert record.response_status == 409
        assert record.response_body["code"] == "DOMAIN_COMMAND_ABANDONED"
        assert record.response_body["details"]["resolution_reason"] == body["access_reason"]
    replay = await client.patch(
        f"/v1/admin/features/{body['feature_id']}",
        headers={
            **headers,
            "If-Match": body["expected_revision"],
            "Idempotency-Key": body["idempotency_key"],
        },
        json=body["payload"],
    )
    assert replay.status_code == 409, replay.text
    assert replay.json()["code"] == "DOMAIN_COMMAND_ABANDONED"
    again = await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    assert again.status_code == 200, again.text
    assert again.json()["data"]["command_id"] == data["command_id"]


async def _stored_command(
    engine, actor, body, *, completed=True, version=None, wrong_identity=None
):
    from kortravelmap.api.domain_command_service import (
        begin_domain_command,
        complete_domain_command,
    )
    from kortravelmap.api.routers.admin_feature_commands import (
        FeatureCommandReconcileRequest,
        _original_payload,
    )
    from pydantic import TypeAdapter

    command = TypeAdapter(FeatureCommandReconcileRequest).validate_python(body)
    payload = await _original_payload(command, actor=actor)
    if version == 1 and body["operation"] == "admin.feature.patch":
        from fastapi.encoders import jsonable_encoder

        payload["body"] = jsonable_encoder(command.payload)
    selected_version = (
        version if version is not None else (2 if body["operation"].endswith("patch") else 1)
    )
    async with AsyncSession(engine) as db, db.begin():
        handle = await begin_domain_command(
            db,
            actor=actor,
            operation=body["operation"],
            idempotency_key=command.idempotency_key,
            payload=payload,
            fingerprint_version=selected_version,
        )
        if body["operation"].endswith("patch"):
            data = {
                "feature_id": body["feature_id"],
                "row_revision": 2,
                "command_id": handle.command_id,
                "applied_field_count": 1,
            }
        else:
            data = {
                "feature_id": body["feature_id"],
                "row_revision": 2,
                "lifecycle_state": "retired",
                "publication_state": "published",
                "quality_state": "valid",
                "audit_transition_id": 17,
            }
        if wrong_identity == "command":
            data["command_id"] = handle.command_id + 1
        elif wrong_identity == "feature":
            data["feature_id"] = str(uuid4())
        receipt = {
            "data": data,
            "meta": {"duration_ms": 0, "request_id": str(uuid4()), "page": None, "cluster": None},
        }
        if completed:
            await complete_domain_command(db, command=handle, response=receipt)
        return handle, receipt


async def _original(client, headers, body, *, payload=None):
    return await client.request(
        "PATCH" if body["operation"].endswith("patch") else "DELETE",
        f"/v1/admin/features/{body['feature_id']}",
        headers={
            **headers,
            "If-Match": body["expected_revision"],
            "Idempotency-Key": body["idempotency_key"],
        },
        json=payload if payload is not None else body["payload"],
    )


@pytest.mark.parametrize("operation", ["admin.feature.patch", "admin.feature.delete"])
async def test_terminal_recovery_does_not_require_current_feature_or_revision(
    command_client, migrated_engine, operation
):
    client, headers, actor = command_client
    body = _intent(actor, operation=operation)
    handle, receipt = await _stored_command(migrated_engine, actor, body)
    result = await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["state"] == "completed"
    assert result.json()["data"]["command_id"] == handle.command_id
    assert result.json()["data"]["receipt"] == receipt
    replay = await _original(client, headers, body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == receipt


async def test_claim_only_is_not_safe_to_clear(command_client, migrated_engine):
    client, headers, actor = command_client
    body = _intent(actor)
    handle, _ = await _stored_command(migrated_engine, actor, body, completed=False)
    for _ in range(2):
        result = await client.post(
            "/v1/admin/feature-commands/reconcile", headers=headers, json=body
        )
        assert result.status_code == 200, result.text
        assert result.json()["data"]["state"] == "pending"
        assert result.json()["data"]["receipt"] is None
    replay = await _original(client, headers, body)
    assert replay.status_code == 409
    assert replay.json()["code"] == "IDEMPOTENCY_RESULT_PENDING"
    async with AsyncSession(migrated_engine) as db:
        assert (
            await db.scalar(
                text("SELECT count(*) FROM ops.domain_command_results WHERE command_id=:id"),
                {"id": handle.command_id},
            )
            == 0
        )


@pytest.mark.parametrize(
    "boundary", ["missing_secret", "wrong_secret", "actor_assertion", "other_actor"]
)
async def test_auth_or_actor_mismatch_never_proves_absence(
    command_client, migrated_engine, boundary
):
    client, headers, actor = command_client
    body = _intent(actor)
    actual = dict(headers)
    if boundary == "missing_secret":
        actual.pop(ADMIN_PROXY_SECRET_HEADER)
    elif boundary == "wrong_secret":
        actual[ADMIN_PROXY_SECRET_HEADER] = "wrong-fixture"
    elif boundary == "actor_assertion":
        body["expected_actor"] = "admin:another"
    else:
        actual[ADMIN_ACTOR_HEADER] = "admin:another"
    result = await client.post("/v1/admin/feature-commands/reconcile", headers=actual, json=body)
    assert result.status_code == 403, result.text
    async with AsyncSession(migrated_engine) as db:
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM ops.domain_commands "
                    "WHERE idempotency_key=CAST(:key AS uuid)"
                ),
                {"key": body["idempotency_key"]},
            )
            == 0
        )


async def test_new_patch_null_presence_reuse_cannot_consume_old_terminal(
    command_client, migrated_engine
):
    client, headers, actor = command_client
    body = _intent(actor)
    await _stored_command(migrated_engine, actor, body)
    different = {**body["payload"], "coord": None}
    replay = await _original(client, headers, body, payload=different)
    assert replay.status_code == 409, replay.text
    assert replay.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    result = await client.post(
        "/v1/admin/feature-commands/reconcile", headers=headers, json={**body, "payload": different}
    )
    assert result.status_code == 409
    assert result.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_v1_patch_claim_and_terminal_are_never_relabelled_or_consumed(
    command_client, migrated_engine
):
    client, headers, actor = command_client
    body = _intent(actor)
    handle, receipt = await _stored_command(migrated_engine, actor, body, version=1)
    for result in [
        await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body),
        await _original(client, headers, body),
    ]:
        assert result.status_code == 409, result.text
        assert result.json()["code"] == "LEGACY_FINGERPRINT_UNVERIFIABLE"
    async with AsyncSession(migrated_engine) as db:
        record = (
            await db.execute(
                text("""
            SELECT c.fingerprint_version, r.response_body FROM ops.domain_commands c
            JOIN ops.domain_command_results r USING(command_id) WHERE c.command_id=:id
        """),
                {"id": handle.command_id},
            )
        ).one()
        assert record.fingerprint_version == 1
        assert record.response_body == receipt


async def test_abandon_commit_response_loss_is_recovered_without_duplicate_command(
    command_client, migrated_engine, monkeypatch
):
    from kortravelmap.api.routers import admin_feature_commands as routes

    client, headers, actor = command_client
    body = _intent(actor)
    real = routes.reconcile_feature_command

    async def lose_response(*args, **kwargs):
        await real(*args, **kwargs)
        raise ConnectionResetError("fixture response lost after commit")

    monkeypatch.setattr(routes, "reconcile_feature_command", lose_response)
    with pytest.raises(ConnectionResetError):
        await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    monkeypatch.setattr(routes, "reconcile_feature_command", real)
    result = await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["state"] == "abandoned"
    async with AsyncSession(migrated_engine) as db:
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM ops.domain_commands WHERE actor=:actor "
                    "AND idempotency_key=CAST(:key AS uuid)"
                ),
                {"actor": actor, "key": body["idempotency_key"]},
            )
            == 1
        )


async def test_reconcile_commit_precedes_late_original_and_response(
    command_client, migrated_engine, monkeypatch
):
    import asyncio

    from kortravelmap.api.routers import admin_feature_commands as routes

    client, headers, actor = command_client
    body = _intent(actor)
    staged = asyncio.Event()
    release = asyncio.Event()
    real = routes.complete_domain_command

    async def stage(*args, **kwargs):
        await real(*args, **kwargs)
        staged.set()
        await release.wait()

    monkeypatch.setattr(routes, "complete_domain_command", stage)
    resolution = asyncio.create_task(
        client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    )
    late = None
    try:
        await asyncio.wait_for(staged.wait(), 5)
        assert not resolution.done()
        async with AsyncSession(migrated_engine) as observer:
            assert (
                await observer.scalar(
                    text(
                        "SELECT count(*) FROM ops.domain_commands WHERE actor=:actor "
                        "AND idempotency_key=CAST(:key AS uuid)"
                    ),
                    {"actor": actor, "key": body["idempotency_key"]},
                )
                == 0
            )
        late = asyncio.create_task(_original(client, headers, body))
        await asyncio.sleep(0.05)
        assert not late.done()
    finally:
        release.set()
    assert late is not None
    resolved, original = await asyncio.wait_for(asyncio.gather(resolution, late), 10)
    assert resolved.status_code == 200, resolved.text
    assert original.status_code == 409, original.text
    assert original.json()["code"] == "DOMAIN_COMMAND_ABANDONED"


async def test_running_original_commits_terminal_before_waiting_reconcile(
    command_client, migrated_engine
):
    import asyncio

    from kortravelmap.api.domain_command_service import (
        begin_domain_command,
        complete_domain_command,
    )
    from kortravelmap.api.routers.admin_feature_commands import (
        FeatureCommandReconcileRequest,
        _original_payload,
    )
    from pydantic import TypeAdapter

    client, headers, actor = command_client
    body = _intent(actor)
    command = TypeAdapter(FeatureCommandReconcileRequest).validate_python(body)
    payload = await _original_payload(command, actor=actor)
    staged = asyncio.Event()
    release = asyncio.Event()
    receipt = {}

    async def original():
        async with AsyncSession(migrated_engine) as db, db.begin():
            handle = await begin_domain_command(
                db,
                actor=actor,
                operation=body["operation"],
                idempotency_key=command.idempotency_key,
                payload=payload,
                fingerprint_version=2,
            )
            staged.set()
            await release.wait()
            receipt.update(
                data={
                    "feature_id": body["feature_id"],
                    "row_revision": 2,
                    "command_id": handle.command_id,
                    "applied_field_count": 1,
                },
                meta={"duration_ms": 0, "request_id": str(uuid4()), "page": None, "cluster": None},
            )
            await complete_domain_command(db, command=handle, response=receipt)

    first = asyncio.create_task(original())
    resolution = None
    try:
        await asyncio.wait_for(staged.wait(), 5)
        resolution = asyncio.create_task(
            client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
        )
        await asyncio.sleep(0.05)
        assert not resolution.done()
    finally:
        release.set()
    assert resolution is not None
    _, result = await asyncio.wait_for(asyncio.gather(first, resolution), 10)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["state"] == "completed"
    assert result.json()["data"]["receipt"] == receipt


@pytest.mark.parametrize("revision", ['W/"1"', '"01"', '"9223372036854775808"'])
async def test_bad_original_revision_does_not_create_a_cancellation(
    command_client, migrated_engine, revision
):
    client, headers, actor = command_client
    body = _intent(actor)
    body["expected_revision"] = revision
    result = await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    assert result.status_code == 422, result.text
    async with AsyncSession(migrated_engine) as db:
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM ops.domain_commands WHERE actor=:actor "
                    "AND idempotency_key=CAST(:key AS uuid)"
                ),
                {"actor": actor, "key": body["idempotency_key"]},
            )
            == 0
        )


@pytest.mark.parametrize(
    ("status", "receipt"),
    [
        (
            200,
            {
                "data": {"feature_id": "wrong-shape"},
                "meta": {"duration_ms": 0, "request_id": "fixture"},
            },
        ),
        (500, {"code": "PRIVATE_PROVIDER_MESSAGE", "detail": "fixture-private-never-return"}),
    ],
)
async def test_unverifiable_record_is_not_a_completed_or_abandoned_result(
    command_client, migrated_engine, status, receipt
):
    from kortravelmap.api.domain_command_service import (
        begin_domain_command,
        complete_domain_command,
    )
    from kortravelmap.api.routers.admin_feature_commands import (
        FeatureCommandReconcileRequest,
        _original_payload,
    )
    from pydantic import TypeAdapter

    client, headers, actor = command_client
    body = _intent(actor)
    command = TypeAdapter(FeatureCommandReconcileRequest).validate_python(body)
    payload = await _original_payload(command, actor=actor)
    async with AsyncSession(migrated_engine) as db, db.begin():
        handle = await begin_domain_command(
            db,
            actor=actor,
            operation=body["operation"],
            idempotency_key=command.idempotency_key,
            payload=payload,
            fingerprint_version=2,
        )
        await complete_domain_command(db, command=handle, response=receipt, status_code=status)
    result = await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    assert result.status_code == 503, result.text
    assert result.json()["code"] == "COMMAND_RECEIPT_UNVERIFIABLE"
    assert "fixture-private-never-return" not in result.text
    async with AsyncSession(migrated_engine) as db:
        stored = await db.scalar(
            text("SELECT response_body FROM ops.domain_command_results WHERE command_id=:id"),
            {"id": handle.command_id},
        )
        assert stored == receipt


async def test_absent_seal_is_scoped_to_original_actor_and_operation(command_client):
    client, headers, actor = command_client
    patch = _intent(actor)
    first = await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=patch)
    assert first.status_code == 200, first.text
    other_actor = actor + "-other"
    other_body = {**patch, "expected_actor": other_actor}
    other = await client.post(
        "/v1/admin/feature-commands/reconcile",
        headers={**headers, ADMIN_ACTOR_HEADER: other_actor},
        json=other_body,
    )
    assert other.status_code == 200, other.text
    deletion = {
        **patch,
        "operation": "admin.feature.delete",
        "payload": {"reason": "original mutation", "operator": "legacy-ignored"},
    }
    third = await client.post(
        "/v1/admin/feature-commands/reconcile", headers=headers, json=deletion
    )
    assert third.status_code == 200, third.text
    ids = {response.json()["data"]["command_id"] for response in [first, other, third]}
    assert len(ids) == 3


@pytest.mark.parametrize("identity", ["command", "feature"])
async def test_typed_receipt_must_match_record_and_original_uuid(
    command_client, migrated_engine, identity
):
    client, headers, actor = command_client
    body = _intent(actor)
    await _stored_command(migrated_engine, actor, body, wrong_identity=identity)
    result = await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    assert result.status_code == 503, result.text
    assert result.json()["code"] == "COMMAND_RECEIPT_UNVERIFIABLE"


async def test_cancellation_failure_before_commit_rolls_back_both_claim_and_result(
    command_client, migrated_engine, monkeypatch
):
    from kortravelmap.api.routers import admin_feature_commands as routes

    client, headers, actor = command_client
    body = _intent(actor)
    real = routes.complete_domain_command

    async def fail_before_commit(*args, **kwargs):
        await real(*args, **kwargs)
        raise ConnectionResetError("fixture before transaction commit")

    monkeypatch.setattr(routes, "complete_domain_command", fail_before_commit)
    with pytest.raises(ConnectionResetError):
        await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    async with AsyncSession(migrated_engine) as db:
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM ops.domain_commands WHERE actor=:actor "
                    "AND idempotency_key=CAST(:key AS uuid)"
                ),
                {"actor": actor, "key": body["idempotency_key"]},
            )
            == 0
        )
    monkeypatch.setattr(routes, "complete_domain_command", real)
    result = await client.post("/v1/admin/feature-commands/reconcile", headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["state"] == "abandoned"
