"""T-VN-M04 범용 Feature request queue의 실제 role/causation 경계."""

from __future__ import annotations

import json
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("tvn_m01_m05_role_graph"),
]

_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"


def _runtime_engine(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    dsn = engine.url.set(username=login, password=_RUNTIME_PASSWORD).render_as_string(
        hide_password=False
    )
    return make_async_engine(dsn, pool_size=1)


async def _command(engine: AsyncEngine, *, actor: str, operation: str) -> int:
    async with engine.begin() as connection:
        return int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      :actor, :operation, x_extension.gen_random_uuid(),
                      encode(
                        x_extension.digest(
                          convert_to(x_extension.gen_random_uuid()::text, 'UTF8'),
                          'sha256'
                        ),
                        'hex'
                      )
                    ) RETURNING command_id
                    """
                ),
                {"actor": actor, "operation": operation},
            )
        )


async def test_feature_request_submit_then_admin_approval_creates_only_manual_request_feature(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    request_id = uuid4()
    service_command = await _command(
        migrated_engine,
        actor="service:feature-request",
        operation="service.feature-request.submit.v1",
    )
    admin_command = await _command(
        migrated_engine,
        actor=f"admin:tvn-m04-{suffix}",
        operation="admin.feature-request.approve.v1",
    )
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    request_payload = {
        "kind": "place",
        "name": "M04 Feature 요청 장소",
        "lon": 127.111111,
        "lat": 37.511111,
        "categories": ["external-request"],
        "note": "integration",
    }
    feature_uuid = "018f9f2b-7777-7def-8abc-1234567890ab"
    feature_id = f"f_global_p_m04{suffix[:12]}"
    feature_payload = {
        "feature_id": feature_id,
        "feature_uuid": feature_uuid,
        "kind": "place",
        "name": "M04 Feature 요청 장소",
        "category": "01070300",
        "lon": 127.111111,
        "lat": 37.511111,
        "coord_precision_digits": 6,
        "marker_color": "P-03",
        "marker_icon": "marker",
    }
    try:
        async with api.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            )
            submitted = (
                await connection.execute(
                    text(
                        """
                        CALL feature.submit_feature_request(
                          CAST(:request_id AS uuid), CAST(:payload AS jsonb), :command_id,
                          NULL::text, NULL::timestamptz
                        )
                        """
                    ),
                    {
                        "request_id": str(request_id),
                        "payload": json.dumps(request_payload),
                        "command_id": service_command,
                    },
                )
            ).mappings().one()
        assert submitted["o_status"] == "pending"

        async with dagster.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            )
            with pytest.raises(DBAPIError) as denied:
                await connection.execute(
                    text(
                        """
                        CALL feature.submit_feature_request(
                          CAST(:request_id AS uuid), CAST(:payload AS jsonb), :command_id,
                          NULL::text, NULL::timestamptz
                        )
                        """
                    ),
                    {
                        "request_id": str(uuid4()),
                        "payload": json.dumps(request_payload),
                        "command_id": service_command,
                    },
                )
        assert getattr(denied.value.orig, "sqlstate", None) == "42501"

        async with api.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            )
            approved = (
                await connection.execute(
                    text(
                        """
                        CALL feature.approve_feature_request_with_initial_state(
                          CAST(:request_id AS uuid), CAST(:feature_payload AS jsonb), :command_id,
                          -- OUT 넷: outcome · feature_id(uuid) · row_revision
                          -- · existing_feature_id(uuid). T-VN-39로 다섯에서 넷이 됐다.
                          NULL::text, NULL::uuid, NULL::bigint, NULL::uuid
                        )
                        """
                    ),
                    {
                        "request_id": str(request_id),
                        "feature_payload": json.dumps(feature_payload),
                        "command_id": admin_command,
                    },
                )
            ).mappings().one()
        assert approved["o_outcome"] == "created"
        assert str(approved["o_feature_uuid"]) == feature_uuid

        async with migrated_engine.connect() as connection:
            evidence = (
                await connection.execute(
                    text(
                        """
                        SELECT request.status, request.submission_command_id,
                               request.resolution_command_id,
                               request.resolved_feature_id, origin.origin_kind,
                               origin.creator_principal_id, origin.procedure_definer
                        FROM ops.feature_requests AS request
                        JOIN feature.feature_creation_origins AS origin
                          ON origin.feature_id = request.resolved_feature_id
                        WHERE request.request_id = CAST(:request_id AS uuid)
                        """
                    ),
                    {"request_id": str(request_id)},
                )
            ).mappings().one()
        assert evidence == {
            "status": "approved",
            "submission_command_id": service_command,
            "resolution_command_id": admin_command,
            "resolved_feature_id": UUID(feature_uuid),
            "origin_kind": "manual_request",
            "creator_principal_id": "feature-request.approval.v1",
            "procedure_definer": "ktm_feature_request_procedure_owner",
        }
    finally:
        await api.dispose()
        await dagster.dispose()


async def test_feature_request_admin_rejection_closes_the_request_without_a_feature(
    migrated_engine: AsyncEngine,
) -> None:
    """admin reject가 pending을 rejected로 닫고 **Feature를 만들지 않는다.**

    reject는 라우터·프로시저·ACL·OpenAPI에 전부 있었지만 **실제로 호출하는 테스트가
    없었다**(2026-09-07 §T-VN-M04 조문 실측). approve만 검증된 큐는 "승인은 되는데
    거절이 무엇을 남기는지 아무도 모르는" 상태이고, 그 상태로 해제 조건을 닫으면
    reject 경로의 회귀는 운영에서만 드러난다.

    여기서 결박하는 것은 셋이다 — 상태 전이(pending→rejected), 사유·resolution
    command의 보존, 그리고 **Feature가 생기지 않았다**는 부재 사실.
    """
    suffix = uuid4().hex
    request_id = uuid4()
    service_command = await _command(
        migrated_engine,
        actor="service:feature-request",
        operation="service.feature-request.submit.v1",
    )
    admin_command = await _command(
        migrated_engine,
        actor=f"admin:tvn-m04-reject-{suffix}",
        operation="admin.feature-request.reject.v1",
    )
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    request_payload = {
        "kind": "place",
        "name": "M04 거절 대상 요청",
        "lon": 127.222222,
        "lat": 37.522222,
        "categories": ["external-request"],
        "note": "integration-reject",
    }
    reason = f"integration reject {suffix[:8]}"
    try:
        async with api.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            )
            submitted = (
                (
                    await connection.execute(
                        text(
                            """
                            CALL feature.submit_feature_request(
                              CAST(:request_id AS uuid), CAST(:payload AS jsonb), :command_id,
                              NULL::text, NULL::timestamptz
                            )
                            """
                        ),
                        {
                            "request_id": str(request_id),
                            "payload": json.dumps(request_payload),
                            "command_id": service_command,
                        },
                    )
                )
                .mappings()
                .one()
            )
        assert submitted["o_status"] == "pending"

        async with api.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            )
            rejected = (
                (
                    await connection.execute(
                        text(
                            """
                            CALL feature.reject_feature_request(
                              CAST(:request_id AS uuid), CAST(:reason AS text), :command_id,
                              NULL::text
                            )
                            """
                        ),
                        {
                            "request_id": str(request_id),
                            "reason": reason,
                            "command_id": admin_command,
                        },
                    )
                )
                .mappings()
                .one()
            )
        assert rejected["o_status"] == "rejected"

        async with migrated_engine.connect() as connection:
            evidence = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT status, submission_command_id, resolution_command_id,
                                   resolved_feature_id, rejection_reason
                            FROM ops.feature_requests
                            WHERE request_id = CAST(:request_id AS uuid)
                            """
                        ),
                        {"request_id": str(request_id)},
                    )
                )
                .mappings()
                .one()
            )
        assert evidence["status"] == "rejected"
        assert evidence["submission_command_id"] == service_command
        assert evidence["resolution_command_id"] == admin_command
        # 거절은 Feature를 만들지 않는다. `resolved_feature_id`가 그 사실의 정본이고,
        # 스키마 CHECK가 rejected 행에 대해 그것이 NULL이며 사유가 비지 않았음을
        # 강제한다(`models.py`의 feature_requests 상태 CHECK).
        assert evidence["resolved_feature_id"] is None
        assert evidence["rejection_reason"] == reason
    finally:
        await api.dispose()


async def test_feature_request_direct_relation_access_and_invalid_payload_are_denied(
    migrated_engine: AsyncEngine,
) -> None:
    """runtime은 queue relation을 읽지 못하고 direct CALL도 HTTP 입력 경계를 지킨다."""

    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    request_id = uuid4()
    command_id = await _command(
        migrated_engine,
        actor="service:feature-request",
        operation="service.feature-request.submit.v1",
    )
    invalid_payload = {
        "kind": "place",
        "name": "M04 invalid direct call",
        "lon": 0,
        "lat": 0,
        "categories": [{}],
    }
    try:
        async with api.connect() as connection:
            with pytest.raises(DBAPIError) as direct_read:
                await connection.execute(text("SELECT * FROM ops.feature_requests"))
            assert getattr(direct_read.value.orig, "sqlstate", None) == "42501"
            await connection.rollback()

            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            )
            with pytest.raises(DBAPIError) as invalid_payload_error:
                await connection.execute(
                    text(
                        """
                        CALL feature.submit_feature_request(
                          CAST(:request_id AS uuid), CAST(:payload AS jsonb), :command_id,
                          NULL::text, NULL::timestamptz
                        )
                        """
                    ),
                    {
                        "request_id": str(request_id),
                        "payload": json.dumps(invalid_payload),
                        "command_id": command_id,
                    },
                )
            assert getattr(invalid_payload_error.value.orig, "sqlstate", None) == "23514"
            assert "Feature request payload is not canonical" in str(
                invalid_payload_error.value.orig
            )
            await connection.rollback()
        async with migrated_engine.connect() as connection:
            assert await connection.scalar(
                text(
                    "SELECT count(*) FROM ops.feature_requests "
                    "WHERE request_id = CAST(:request_id AS uuid)"
                ),
                {"request_id": str(request_id)},
            ) == 0
    finally:
        await api.dispose()


async def test_feature_request_reconciler_restores_cross_owner_dependencies(
    migrated_engine: AsyncEngine,
) -> None:
    """no-owner/no-privileges restore를 흉내 내도 submit·approve writer가 복구된다."""

    async with migrated_engine.begin() as connection:
        for statement in (
            "REVOKE ALL ON FUNCTION feature.manual_feature_identity_key("
            "text, text, numeric, numeric) FROM ktm_feature_request_procedure_owner",
            "REVOKE ALL ON PROCEDURE feature.create_feature_with_initial_state("
            "jsonb, text, text, text, jsonb) FROM ktm_feature_request_procedure_owner",
            "REVOKE ALL ON TABLE feature.manual_feature_identity_claims, "
            "feature.feature_creation_origins FROM ktm_feature_request_procedure_owner",
            "REVOKE ALL ON TABLE ops.feature_requests, ops.domain_commands, "
            "ops.domain_command_results FROM ktm_feature_request_procedure_owner",
        ):
            await connection.execute(text(statement))

    previous_dsn = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    os.environ["KOR_TRAVEL_MAP_PG_DSN"] = migrated_engine.url.set(
        username="ktm_feature_migrator",
        password="tvn34-test-only-migrator-password",
    ).render_as_string(hide_password=False)
    try:
        await reconcile_runtime_privileges()
    finally:
        if previous_dsn is None:
            os.environ.pop("KOR_TRAVEL_MAP_PG_DSN", None)
        else:
            os.environ["KOR_TRAVEL_MAP_PG_DSN"] = previous_dsn

    suffix = uuid4().hex
    request_id = uuid4()
    service_command = await _command(
        migrated_engine,
        actor="service:feature-request",
        operation="service.feature-request.submit.v1",
    )
    admin_command = await _command(
        migrated_engine,
        actor=f"admin:tvn-m04-restore-{suffix}",
        operation="admin.feature-request.approve.v1",
    )
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    feature_uuid = "018f9f2b-8888-7def-8abc-1234567890ab"
    feature_id = f"f_global_p_m04restore{suffix[:8]}"
    request_payload = {
        "kind": "place",
        "name": "M04 restore writer",
        "lon": 127.211111,
        "lat": 37.611111,
        "categories": ["external-request"],
    }
    feature_payload = {
        "feature_id": feature_id,
        "feature_uuid": feature_uuid,
        "kind": "place",
        "name": "M04 restore writer",
        "category": "01070300",
        "lon": 127.211111,
        "lat": 37.611111,
        "coord_precision_digits": 6,
        "marker_color": "P-03",
        "marker_icon": "marker",
    }
    try:
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            await connection.execute(
                text(
                    "CALL feature.submit_feature_request("
                    "CAST(:request_id AS uuid), CAST(:payload AS jsonb), :command_id, "
                    "NULL::text, NULL::timestamptz)"
                ),
                {
                    "request_id": str(request_id),
                    "payload": json.dumps(request_payload),
                    "command_id": service_command,
                },
            )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            approved = (
                await connection.execute(
                    text(
                        "CALL feature.approve_feature_request_with_initial_state("
                        "CAST(:request_id AS uuid), CAST(:payload AS jsonb), :command_id, "
                        # OUT 넷 — T-VN-39로 다섯에서 넷이 됐다.
                        "NULL::text, NULL::uuid, NULL::bigint, NULL::uuid)"
                    ),
                    {
                        "request_id": str(request_id),
                        "payload": json.dumps(feature_payload),
                        "command_id": admin_command,
                    },
                )
            ).mappings().one()
        assert approved["o_outcome"] == "created"
    finally:
        await api.dispose()
