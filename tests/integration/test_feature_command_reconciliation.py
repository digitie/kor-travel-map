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
