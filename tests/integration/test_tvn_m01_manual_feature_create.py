"""T-VN-M01 — API 전용 수동 Feature writer의 실제 DB 경계."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.admin_feature_repo import (
    AdminManualFeatureCreated,
    AdminManualFeatureExactDuplicate,
    create_admin_feature_with_field_overrides,
)
from kortravelmap.infra.db import (
    assert_runtime_db_privilege_boundary,
    make_async_engine,
)
from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
    create_domain_command_claim,
)

pytestmark = pytest.mark.integration

_API_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"
_OPERATION = "admin.feature.create.manual-v1"


async def _api_runtime_engine(migrated_engine: AsyncEngine) -> AsyncEngine:
    """실 API LOGIN으로 wrapper를 호출한다; superuser shortcut은 허용하지 않는다."""

    dsn = migrated_engine.url.set(
        username="ktm_feature_api_runtime",
        password=_API_RUNTIME_PASSWORD,
    ).render_as_string(hide_password=False)
    engine = make_async_engine(dsn, pool_size=1)
    await assert_runtime_db_privilege_boundary(
        engine,
        expected_login="ktm_feature_api_runtime",
    )
    return engine


async def _claim_manual_command(session: AsyncSession, *, suffix: str) -> int:
    payload = {"test": "tvn-m01", "suffix": suffix}
    claim = await create_domain_command_claim(
        session,
        actor="admin:tvn-m01",
        operation=_OPERATION,
        idempotency_key=str(uuid4()),
        request_fingerprint=canonical_domain_command_fingerprint(payload),
    )
    return claim.command_id


def _payload() -> dict[str, object]:
    return {
        "kind": "place",
        "name": " M01 실제 경계 장소 ",
        "category": "01070300",
        "coord": {"lon": 127.5, "lat": 36.5},
        "marker_icon": "marker",
        "marker_color": "P-02",
        "detail": {"place_kind": "attraction"},
    }


async def test_api_manual_create_writes_immutable_claim_and_origin_once(
    migrated_engine: AsyncEngine,
) -> None:
    """winner만 evidence와 core/subtype을 만들고 loser는 exact winner만 받는다."""

    api_engine = await _api_runtime_engine(migrated_engine)
    try:
        async with (
            AsyncSession(api_engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            command_id = await _claim_manual_command(session, suffix="winner")
            winner = await create_admin_feature_with_field_overrides(
                session,
                payload=_payload(),
                reason_code="manual_create",
                operator="admin:tvn-m01",
                command_id=command_id,
            )
        assert isinstance(winner, AdminManualFeatureCreated)

        async with (
            AsyncSession(api_engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            duplicate_command_id = await _claim_manual_command(
                session,
                suffix="exact-conflict",
            )
            loser = await create_admin_feature_with_field_overrides(
                session,
                payload=_payload(),
                reason_code="manual_create",
                operator="admin:tvn-m01",
                command_id=duplicate_command_id,
            )
        assert isinstance(loser, AdminManualFeatureExactDuplicate)
        assert loser.existing_feature_uuid == winner.feature_uuid

        async with migrated_engine.connect() as connection:
            evidence = (
                await connection.execute(
                    text(
                        """
                        SELECT claim.feature_id::text, claim.feature_kind,
                               claim.name_key, claim.lon_e6, claim.lat_e6,
                               claim.claimed_by_command_id, claim.claim_basis,
                               origin.origin_kind, origin.creation_command_id,
                               origin.creator_principal_id, origin.created_by_actor,
                               origin.invoker_role, origin.procedure_definer
                        FROM feature.manual_feature_identity_claims AS claim
                        JOIN feature.feature_creation_origins AS origin
                          ON origin.feature_id = claim.feature_id
                         AND origin.creation_command_id = claim.claimed_by_command_id
                        WHERE claim.feature_id = CAST(:feature_uuid AS uuid)
                        """
                    ),
                    {"feature_uuid": winner.feature_uuid},
                )
            ).one()
            counts = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM feature.manual_feature_identity_claims),
                            (SELECT count(*) FROM feature.feature_creation_origins),
                            (SELECT count(*) FROM feature.features
                             WHERE feature_uuid = CAST(:feature_uuid AS uuid))
                        """
                    ),
                    {"feature_uuid": winner.feature_uuid},
                )
            ).one()

        assert evidence == (
            winner.feature_uuid,
            "place",
            "m01 실제 경계 장소",
            127500000,
            36500000,
            command_id,
            "manual_create",
            "manual_admin",
            command_id,
            "admin-ui-bff.manual-feature-create.v1",
            "admin:tvn-m01",
            "ktm_feature_api_runtime",
            "ktm_manual_feature_procedure_owner",
        )
        assert counts == (1, 1, 1)
    finally:
        await api_engine.dispose()
