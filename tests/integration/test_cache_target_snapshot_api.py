"""Service cache-target snapshot의 요청 간 durable pagination 회귀 테스트."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from kortravelmap.api.app import create_app
from kortravelmap.api.auth import CACHE_TARGET_CONSUMER_HEADER, SERVICE_TOKEN_HEADER
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from kortravelmap.core.cache_target_stream import make_active_cache_target_source
from kortravelmap.infra.cache_target_stream_repo import apply_cache_target_source

_SYSTEM = "snapshot-api-durability-test"
_CONSUMER = "snapshot-api-consumer"
_TOKEN = "snapshot-api-token-000000000000000000000000"


def _service_principals() -> list[dict[str, object]]:
    role_scopes = {
        "command": ["cache-target:command"],
        "consumer": [
            "cache-target:read",
            "cache-target:claim",
            "cache-target:ack",
            "cache-target:nack",
            "cache-target:snapshot",
        ],
        "restore": ["cache-target:restore-fence"],
        "recovery": ["cache-target:recovery", "cache-target:recovery-replay"],
    }
    return [
        {
            "principal_id": f"svc:snapshot-api-{role}",
            "consumer_id": _CONSUMER,
            "token_sha256": hashlib.sha256(
                (_TOKEN if role == "consumer" else f"{_TOKEN}-{role}").encode()
            ).hexdigest(),
            "scopes": scopes,
            "external_systems": [_SYSTEM],
        }
        for role, scopes in role_scopes.items()
    ]


async def _apply_source(
    session: AsyncSession,
    *,
    target_key: str,
    event_id: str,
    idempotency_key: str,
) -> None:
    await apply_cache_target_source(
        session,
        consumer_id=_CONSUMER,
        source_event_id=event_id,
        idempotency_key=idempotency_key,
        external_system=_SYSTEM,
        target_key=target_key,
        restore_epoch=1,
        source_generation=1,
        source=make_active_cache_target_source(
            lon="126.978",
            lat="37.5665",
            radius_km="5",
            update_enabled=True,
        ),
        occurred_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        create_only=True,
    )


@pytest.fixture
async def snapshot_connection(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncConnection]:
    async with migrated_engine.connect() as connection:
        outer = await connection.begin()
        async with AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
        ) as setup, setup.begin():
            await _apply_source(
                setup,
                target_key="target-a",
                event_id="93000000-0000-4000-8000-000000000001",
                idempotency_key="94000000-0000-4000-8000-000000000001",
            )
            await _apply_source(
                setup,
                target_key="target-b",
                event_id="93000000-0000-4000-8000-000000000002",
                idempotency_key="94000000-0000-4000-8000-000000000002",
            )
        try:
            yield connection
        finally:
            await outer.rollback()


@pytest.mark.integration
async def test_snapshot_first_page_commits_for_next_request_session(
    snapshot_connection: AsyncConnection,
) -> None:
    settings = ApiSettings(
        _env_file=None,
        admin_proxy_secret=None,
        ops_cancel_token=None,
        ops_fixture_token=None,
        ops_read_token=None,
        public_api_key_required=False,
        service_token=None,
        vworld_api_key=None,
        cache_target_service_principals=_service_principals(),
    )
    app = create_app(settings)

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            bind=snapshot_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    app.dependency_overrides[get_session] = _request_session
    headers = {
        SERVICE_TOKEN_HEADER: _TOKEN,
        CACHE_TARGET_CONSUMER_HEADER: _CONSUMER,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get(
            f"/v1/service/cache-target-snapshots/{_SYSTEM}",
            headers=headers,
            params={"page_size": 1},
        )
        assert first.status_code == 200, first.text
        first_body = first.json()
        snapshot_id = first_body["data"]["snapshot_id"]
        cursor = first_body["meta"]["page"]["next_cursor"]
        assert cursor is not None
        assert first_body["data"]["created_at"] < first_body["data"]["expires_at"]
        expires_at = datetime.fromisoformat(
            first_body["data"]["expires_at"].replace("Z", "+00:00")
        )
        assert expires_at - datetime.now(UTC) >= timedelta(hours=1)
        assert [item["target_key"] for item in first_body["data"]["items"]] == [
            "target-a"
        ]

        async with AsyncSession(
            bind=snapshot_connection,
            join_transaction_mode="create_savepoint",
        ) as probe:
            persisted = (
                await probe.execute(
                    text(
                        "SELECT material.item_count, "
                        "count(item.row_number) AS item_rows "
                        "FROM ops.poi_cache_target_snapshots AS snapshot "
                        "JOIN ops.poi_cache_target_snapshot_materials AS material "
                        "ON material.material_id = snapshot.material_id "
                        "LEFT JOIN "
                        "ops.poi_cache_target_snapshot_material_items AS item "
                        "ON item.material_id = snapshot.material_id "
                        "WHERE snapshot.snapshot_id = CAST(:snapshot_id AS uuid) "
                        "GROUP BY material.item_count"
                    ),
                    {"snapshot_id": snapshot_id},
                )
            ).one()
        assert (int(persisted.item_count), int(persisted.item_rows)) == (2, 2)

        second = await client.get(
            f"/v1/service/cache-target-snapshots/{_SYSTEM}",
            headers=headers,
            params={"page_size": 1, "cursor": cursor},
        )
        reused = await client.get(
            f"/v1/service/cache-target-snapshots/{_SYSTEM}",
            headers=headers,
            params={"page_size": 1},
        )

    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["data"]["snapshot_id"] == snapshot_id
    assert second_body["data"]["merkle_root"] == first_body["data"]["merkle_root"]
    assert [item["target_key"] for item in second_body["data"]["items"]] == [
        "target-b"
    ]
    assert second_body["meta"]["page"]["next_cursor"] is None
    assert reused.status_code == 200, reused.text
    reused_body = reused.json()
    assert reused_body["data"]["snapshot_id"] == snapshot_id
    assert reused_body["data"]["created_at"] == first_body["data"]["created_at"]
    assert reused_body["data"]["expires_at"] == first_body["data"]["expires_at"]
