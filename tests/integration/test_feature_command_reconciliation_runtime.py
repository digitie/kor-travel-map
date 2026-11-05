"""#668: 정본 runtime 역할의 실제 Feature 변경과 미실행 봉인을 검증한다."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.http_revision import revision_etag
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration._owned_pg import scalar_container as scalar_container
from tests.integration._owned_pg import scalar_engines as scalar_engines
from tests.integration.test_field_override_protocol_entry import _case
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(60)]


@pytest.mark.parametrize("operation", ["admin.feature.patch", "admin.feature.delete"])
@pytest.mark.parametrize("execute_first", [False, True])
async def test_real_runtime_mutation_is_either_recovered_or_permanently_fenced(
    scalar_engines, operation, execute_first
):
    owner, runtime = scalar_engines
    case = await _case(owner, runtime)
    credential = "command-runtime-fixture-" + uuid4().hex
    app = create_app(
        ApiSettings(
            _env_file=None,
            admin_proxy_secret=credential,
            admin_routes_enabled=True,
            features_routes_enabled=False,
            debug_routes_enabled=False,
            ops_routes_enabled=False,
            api_call_log_enabled=False,
            prometheus_metrics_enabled=False,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def session_dependency():
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_session] = session_dependency
    headers = {
        "X-Kor-Travel-Map-Admin-Proxy-Secret": credential,
        "X-Kor-Travel-Map-Actor": case.actor,
    }
    body = {"reason": "runtime uncertain approval"}
    if operation.endswith("patch"):
        body["name"] = "runtime confirmed name"
    key = str(uuid4())
    command = dict(
        operation=operation,
        feature_id=case.feature,
        payload=body,
        expected_revision=revision_etag(case.revision),
        idempotency_key=key,
        expected_actor=case.actor,
        access_reason="실제 runtime 명령의 실행 결과 확인",
    )
    method = "PATCH" if operation.endswith("patch") else "DELETE"

    async def state():
        async with AsyncSession(owner) as db:
            return (
                await db.execute(
                    text(
                        "SELECT name,lifecycle_state,row_revision FROM feature.features "
                        "WHERE feature_id=CAST(:id AS uuid)"
                    ),
                    {"id": case.feature},
                )
            ).one()

    before = await state()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://runtime.test",
    ) as client:

        async def original():
            return await client.request(
                method,
                f"/v1/admin/features/{case.feature}",
                headers={
                    **headers,
                    "If-Match": command["expected_revision"],
                    "Idempotency-Key": key,
                },
                json=body,
            )

        first = await original() if execute_first else None
        if first is not None:
            assert first.status_code == 200, first.text
        resolution = await client.post(
            "/v1/admin/feature-commands/reconcile", headers=headers, json=command
        )
        assert resolution.status_code == 200, resolution.text
        result = resolution.json()["data"]
        assert result["state"] == ("completed" if execute_first else "abandoned")
        after = await state()
        if execute_first:
            assert result["receipt"]["data"] == first.json()["data"]
            assert after.row_revision > before.row_revision
            if method == "PATCH":
                assert after.name == body["name"]
                # v2에서 명시 NULL 추가는 다른 명령이며 기존 성공을 재생하지 않는다.
                changed = await client.patch(
                    f"/v1/admin/features/{case.feature}",
                    headers={
                        **headers,
                        "If-Match": command["expected_revision"],
                        "Idempotency-Key": key,
                    },
                    json={**body, "coord": None},
                )
                assert changed.status_code == 409, changed.text
                assert changed.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
            else:
                assert after.lifecycle_state == "retired"
        else:
            assert after == before
        late = await original()
        assert late.status_code == (200 if execute_first else 409), late.text
        if not execute_first:
            assert late.json()["code"] == "DOMAIN_COMMAND_ABANDONED"
        assert await state() == after
        again = await client.post(
            "/v1/admin/feature-commands/reconcile", headers=headers, json=command
        )
        assert again.status_code == 200, again.text
        assert again.json()["data"] == result
