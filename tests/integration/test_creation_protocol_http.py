"""승인 요청의 실제 DB 잠금 대기·rollback·동일 key 복구와 오류 비식별화."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import httpx
import pytest
from kortravelmap.api import db as api_db
from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import feature_request_repo as repo
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)
from tests.integration.test_tvn_m05_manual_provider_dedup import _open_command

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]


async def _request(runtime):
    identity = uuid4()
    actor = "service:feature-request"
    command = await _open_command(
        runtime, actor=actor, operation="service.feature-request.submit.v1"
    )
    async with AsyncSession(runtime) as session, session.begin():
        await repo.submit_feature_request(
            session,
            request_id=identity,
            request_payload=dict(
                kind="place",
                name="creation-http-" + uuid4().hex,
                lon=127.5,
                lat=36.5,
                categories=[],
            ),
            command_id=command,
        )
    return identity


def _client(runtime, monkeypatch):
    credential = uuid4().hex + uuid4().hex
    create_credential = uuid4().hex + uuid4().hex
    app = create_app(
        ApiSettings(
            admin_proxy_secret=credential,
            admin_manual_feature_create_enabled=True,
            admin_feature_create_token_sha256=hashlib.sha256(
                create_credential.encode()
            ).hexdigest(),
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )
    # 실제 auth/session/transaction/handler를 보존하고 접속 engine만 고유 runtime에 결박한다.
    monkeypatch.setattr(api_db, "_get_engine", lambda: runtime)
    headers = {
        "X-Kor-Travel-Map-Admin-Proxy-Secret": credential,
        "X-Kor-Travel-Map-Actor": "admin:creation-http-" + uuid4().hex,
        "X-Kor-Travel-Map-Admin-Feature-Create-Token": create_credential,
        "Idempotency-Key": str(uuid4()),
    }
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
    )
    return client, headers


_BODY = dict(category="01070300", marker_color="P-02", marker_icon="marker")


async def _command_count(admin, headers):
    async with admin.connect() as c:
        return await c.scalar(
            text(
                "SELECT count(*) FROM ops.domain_commands "
                "WHERE actor=:actor AND idempotency_key=CAST(:key AS uuid)"
            ),
            dict(actor=headers["X-Kor-Travel-Map-Actor"], key=headers["Idempotency-Key"]),
        )


async def test_approval_http_timeout_rollback_same_key_retry_replay_and_conflict(
    scalar_engines, monkeypatch
):
    admin, runtime = scalar_engines
    request = await _request(runtime)
    client, headers = _client(runtime, monkeypatch)
    url = "/v1/admin/feature-requests/" + str(request)
    async with client:
        assert (await client.post(url + "/approve", json=_BODY)).status_code == 403
        initial = await client.get(url, headers=headers)
        assert initial.status_code == 200
        assert initial.json()["data"]["status"] == "pending"
        # 434 epoch=0 단건 writer는 P를 잡지 않는다. 승인 대상 행 자체를 막아
        # 실제 잠금 timeout·전체 rollback·동일 key 재시도를 검증한다.
        async with AsyncSession(admin) as holder, holder.begin():
            assert (
                await holder.scalar(
                    text(
                        "SELECT request_id FROM ops.feature_requests "
                        "WHERE request_id=CAST(:request AS uuid) FOR UPDATE"
                    ),
                    {"request": str(request)},
                )
                == request
            )
            response = await client.post(url + "/approve", headers=headers, json=_BODY)
            assert response.status_code == 503, response.text
            assert response.json()["code"] == "LOCK_TIMEOUT"
            assert response.headers["Retry-After"] == "5"
        failed = await client.get(url, headers=headers)
        assert failed.status_code == 200
        assert failed.json()["data"] == initial.json()["data"]
        assert await _command_count(admin, headers) == 0
        async with admin.connect() as c:
            assert (
                await c.scalar(
                    text(
                        "SELECT count(*) FROM feature.feature_creation_origins "
                        "WHERE created_by_actor=:actor"
                    ),
                    dict(actor=headers["X-Kor-Travel-Map-Actor"]),
                )
                == 0
            )
        response = await client.post(url + "/approve", headers=headers, json=_BODY)
        assert response.status_code == 200, response.text
        created = response.json()["data"]
        assert created["status"] == "approved"
        feature_id = created["feature_id"]
        assert feature_id
        assert response.headers["Location"] == "/v1/admin/features/" + feature_id
        feature = await client.get("/v1/admin/features/" + feature_id, headers=headers)
        assert feature.status_code == 200
        detail = feature.json()["data"]
        assert detail["feature"]["name"] == initial.json()["data"]["name"]
        assert response.headers["ETag"] == '"' + str(detail["feature"]["row_revision"]) + '"'
        assert len(detail["state_transitions"]) == 1
        replay = await client.post(url + "/approve", headers=headers, json=_BODY)
        assert replay.status_code == 200
        assert replay.json()["data"] == created
        assert replay.headers["ETag"] == response.headers["ETag"]
        again = await client.post(
            url + "/approve", json=_BODY, headers={**headers, "Idempotency-Key": str(uuid4())}
        )
        assert again.status_code == 409
        assert again.json()["code"] == "FEATURE_REQUEST_STATE_CONFLICT"
        assert (await client.get(url, headers=headers)).json()["data"] == created
        async with admin.connect() as c:
            assert (
                await c.scalar(
                    text(
                        "SELECT count(*) FROM feature.feature_creation_origins "
                        "WHERE created_by_actor=:actor"
                    ),
                    dict(actor=headers["X-Kor-Travel-Map-Actor"]),
                )
                == 1
            )
            assert (
                await c.scalar(
                    text(
                        "SELECT count(*) FROM ops.domain_command_results r "
                        "JOIN ops.domain_commands c USING(command_id) WHERE c.actor=:actor "
                        "AND c.operation='admin.feature-request.approve.v1' "
                        "AND r.response_status=200"
                    ),
                    dict(actor=headers["X-Kor-Travel-Map-Actor"]),
                )
                == 1
            )


@pytest.mark.parametrize(
    ("sqlstate", "status_code"), [("23514", 422), ("40001", 500), ("XX000", 500)]
)
async def test_other_pg_errors_keep_existing_closed_mapping_and_same_key_recovery(
    scalar_engines, monkeypatch, sqlstate, status_code
):
    admin, runtime = scalar_engines
    request = await _request(runtime)
    client, headers = _client(runtime, monkeypatch)
    url = "/v1/admin/feature-requests/" + str(request)
    async with client:
        before = (await client.get(url, headers=headers)).json()["data"]
        # 오류 비식별화 전용 실제 PG fault 주입이다. 동시성 재현으로 세지 않는다.
        with monkeypatch.context() as injection:
            injection.setattr(
                repo,
                "_APPROVE_SQL",
                "DO $$ BEGIN RAISE EXCEPTION 'creation418 private diagnostic' "
                "USING ERRCODE='" + sqlstate + "'; END; $$",
            )
            response = await client.post(url + "/approve", json=_BODY, headers=headers)
            assert response.status_code == status_code, response.text
            assert "creation418 private diagnostic" not in response.text
        assert (await client.get(url, headers=headers)).json()["data"] == before
        assert await _command_count(admin, headers) == 0
        recovered = await client.post(url + "/approve", json=_BODY, headers=headers)
        assert recovered.status_code == 200, recovered.text
        replay = await client.post(url + "/approve", json=_BODY, headers=headers)
        assert replay.status_code == 200
        assert replay.json()["data"] == recovered.json()["data"]
