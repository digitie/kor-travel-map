"""ADR115 reader: 두 PG 세션의 실제 commit을 repo SELECT 사이에 주입한다."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from kortravelmap.api import db as api_db
from kortravelmap.api.app import create_app
from kortravelmap.api.routers import features
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra import price_repo
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from tests.integration._db_cleanup import truncate_committed_test_rows
from tests.integration._feature_ids import feature_uuid
from tests.integration.test_poi_cache_target_nearby import _insert_feature
from tests.integration.test_price_freshness_horizon import _append_price_response, _price_value

pytestmark = pytest.mark.integration
_FIRST = feature_uuid("reader-snapshot-first")
_SECOND = feature_uuid("reader-snapshot-second")
_AT = datetime(2026, 10, 24, tzinfo=UTC)
_CLEAN = "TRUNCATE feature.features, provider_sync.source_entities RESTART IDENTITY CASCADE"


@pytest.fixture
async def reader_app(migrated_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(api_db, "_get_engine", lambda: migrated_engine)
    async with AsyncSession(migrated_engine) as session, session.begin():
        await _insert_feature(session, feature_id=_FIRST, name="old", lon=127.0, lat=37.5)
        await _insert_feature(session, feature_id=_SECOND, name="far", lon=129.0, lat=35.0)
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    try:
        yield app
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await truncate_committed_test_rows(session, _CLEAN)


def _use_control_session(app: Any, engine: AsyncEngine, snapshot: bool) -> None:
    if snapshot:
        return

    async def read_committed() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine) as session:
            yield session

    app.dependency_overrides[api_db.get_read_snapshot_session] = read_committed


async def _rename(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE feature.features SET name='new' WHERE feature_id=:id"),
            {"id": _FIRST},
        )


@pytest.mark.parametrize("snapshot", [False, True], ids=["rc-counterexample", "repeatable-read"])
async def test_detail_identity_then_body_uses_one_image(
    reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: bool,
) -> None:
    _use_control_session(reader_app, migrated_engine, snapshot)
    original = features.resolve_feature_ref_or_error

    async def after_identity(session: AsyncSession, ref: str):
        result = await original(session, ref)
        await _rename(migrated_engine)
        return result

    monkeypatch.setattr(features, "resolve_feature_ref_or_error", after_identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(reader_app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/features/{_FIRST}")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["name"] == ("old" if snapshot else "new")


@pytest.mark.parametrize("snapshot", [False, True], ids=["rc-counterexample", "repeatable-read"])
async def test_batch_identity_then_trip_card_uses_one_image(
    reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: bool,
) -> None:
    _use_control_session(reader_app, migrated_engine, snapshot)
    original = features.feature_identity.resolve_feature_identities_bulk

    async def after_identity(session: AsyncSession, refs: Any):
        result = await original(session, refs)
        await _rename(migrated_engine)
        return result

    monkeypatch.setattr(
        features.feature_identity, "resolve_feature_identities_bulk", after_identity
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(reader_app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/features/batch", json={"items": [{"feature_id": _FIRST}]})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["items"][0]["trip_card"]["name"] == (
        "old" if snapshot else "new"
    )


@pytest.mark.parametrize("snapshot", [False, True], ids=["rc-counterexample", "repeatable-read"])
async def test_target_metadata_then_nearby_uses_one_image(
    reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: bool,
) -> None:
    async with AsyncSession(migrated_engine) as writer, writer.begin():
        await upsert_poi_cache_target(
            writer,
            external_system="snapshot-test",
            target_key="one",
            lon=127.0,
            lat=37.5,
            radius_km=1,
        )
    _use_control_session(reader_app, migrated_engine, snapshot)
    original = features.get_poi_cache_target_by_key

    async def after_target(session: AsyncSession, **kwargs: Any):
        result = await original(session, **kwargs)
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            await upsert_poi_cache_target(
                writer,
                external_system="snapshot-test",
                target_key="one",
                lon=129.0,
                lat=35.0,
                radius_km=1,
                on_conflict="move",
            )
        return result

    monkeypatch.setattr(features, "get_poi_cache_target_by_key", after_target)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(reader_app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/v1/features/nearby/by-target",
                params={"external_system": "snapshot-test", "target_key": "one"},
            )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["target"]["lon"] == 127.0
        assert [row["name"] for row in data["items"]] == (["old"] if snapshot else ["far"])
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM ops.poi_cache_targets WHERE external_system='snapshot-test'")
            )


@pytest.mark.parametrize("snapshot", [False, True], ids=["rc-counterexample", "repeatable-read"])
async def test_price_snapshot_current_then_history_uses_one_image(
    reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: bool,
) -> None:
    async with AsyncSession(migrated_engine) as writer, writer.begin():
        await _append_price_response(
            writer, [_price_value(_FIRST, product_key="gasoline", observed_at=_AT, price=1800)]
        )
    _use_control_session(reader_app, migrated_engine, snapshot)
    original = AsyncSession.execute
    injected = False

    async def after_current(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any):
        nonlocal injected
        result = await original(self, statement, *args, **kwargs)
        if not injected and str(statement) == price_repo._HISTORICAL_CURRENT_SQL:
            injected = True
            async with AsyncSession(migrated_engine) as writer, writer.begin():
                await _append_price_response(
                    writer,
                    [
                        _price_value(
                            _FIRST,
                            product_key="gasoline",
                            observed_at=_AT + timedelta(minutes=1),
                            price=1900,
                        )
                    ],
                )
        return result

    monkeypatch.setattr(AsyncSession, "execute", after_current)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(reader_app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/v1/features/{_FIRST}/price/snapshot",
            params={
                "observed_at": (_AT + timedelta(hours=1)).isoformat(),
                "known_at": (_AT + timedelta(days=1)).isoformat(),
            },
        )
    assert response.status_code == 200, response.text
    assert injected
    data = response.json()["data"]
    assert float(data["current"][0]["value_number"]) == 1800
    assert [float(row["value_number"]) for row in data["history"]] == (
        [1800] if snapshot else [1900, 1800]
    )


async def test_snapshot_is_readonly_before_first_query_and_returns_pool_on_error(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_db, "_get_engine", lambda: migrated_engine)
    generator = api_db.get_read_snapshot_session()
    session = await anext(generator)
    try:
        assert await session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert await session.scalar(text("SHOW transaction_read_only")) == "on"
        with pytest.raises(DBAPIError):
            await session.execute(text("CREATE TABLE forbidden_readonly_write (id int)"))
    finally:
        await generator.aclose()
    assert not session.in_transaction()
    # 같은 pool 다음 세션에 read-only/RR을 흘리지 않고 기존 writer를 보존한다.
    async with AsyncSession(migrated_engine) as writer, writer.begin():
        assert await writer.scalar(text("SHOW transaction_read_only")) == "off"
        assert await writer.scalar(text("SHOW transaction_isolation")) == "read committed"
        await writer.execute(text("CREATE TEMP TABLE snapshot_writer_ok (id int) ON COMMIT DROP"))


@pytest.mark.parametrize("concurrent_requests", [1, 3])
async def test_cold_public_key_auth_and_snapshot_share_one_connection_pool(
    reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    concurrent_requests: int,
) -> None:
    from kortravelmap.api.auth import PUBLIC_API_KEY_HEADER
    from sqlalchemy.ext.asyncio import create_async_engine

    from kortravelmap.infra.public_api_keys import (
        create_public_api_key,
        invalidate_public_api_key_cache,
    )

    async with AsyncSession(migrated_engine) as writer, writer.begin():
        key = await create_public_api_key(writer, label="reader-pool", created_by="local-test")
    invalidate_public_api_key_cache()
    # 연결 하나로 auth와 snapshot을 차례로 쓰는지 본다. 요청이 연결 둘을 쥐면 둘째 checkout이
    # 끝내 기다리다 실패한다. 직렬로 도는 요청 셋이 느린 runner에서 0.25초 대기를 넘겨
    # 오탐이 났으므로 대기를 5초로 둔다(교착은 여전히 5초 뒤 실패로 드러난다).
    bounded = create_async_engine(
        migrated_engine.url, pool_size=1, max_overflow=0, pool_timeout=5
    )
    monkeypatch.setattr(api_db, "_get_engine", lambda: bounded)
    app = create_app(ApiSettings(public_api_key_required=True, vworld_api_key=None))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            responses = await asyncio.gather(
                *(
                    client.get(f"/v1/features/{_FIRST}", headers={PUBLIC_API_KEY_HEADER: key.key})
                    for _ in range(concurrent_requests)
                )
            )
            assert all(response.status_code == 200 for response in responses)
            assert all(response.json()["data"]["name"] == "old" for response in responses)
            assert bounded.pool.checkedout() == 0
            invalidate_public_api_key_cache()
            rejected = await client.get(
                f"/v1/features/{_FIRST}", headers={PUBLIC_API_KEY_HEADER: "invalid-local-key"}
            )
            assert rejected.status_code == 401
        assert bounded.pool.checkedout() == 0
    finally:
        await bounded.dispose()
        invalidate_public_api_key_cache()
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM ops.public_api_keys WHERE public_api_key_id=CAST(:id AS uuid)"),
                {"id": key.item.public_api_key_id},
            )


@pytest.mark.parametrize("snapshot", [False, True], ids=["rc-counterexample", "repeatable-read"])
async def test_admin_count_then_items_uses_one_image(
    reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: bool,
) -> None:
    from kortravelmap.infra import admin_feature_repo
    from kortravelmap.infra.models import DedupReviewQueueRow

    third = feature_uuid("reader-snapshot-third")

    def review(a: str, b: str) -> DedupReviewQueueRow:
        first, second = sorted((a, b))
        return DedupReviewQueueRow(
            feature_id_a=first,
            feature_id_b=second,
            total_score=90,
            name_score=90,
            spatial_score=90,
            category_score=90,
        )

    async with AsyncSession(migrated_engine) as writer, writer.begin():
        await _insert_feature(writer, feature_id=third, name="third", lon=128.0, lat=36.0)
        writer.add(review(_FIRST, _SECOND))
    _use_control_session(reader_app, migrated_engine, snapshot)
    original = AsyncSession.execute
    injected = False

    async def after_count(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any):
        nonlocal injected
        result = await original(self, statement, *args, **kwargs)
        if not injected and str(statement) == admin_feature_repo._DEDUP_REVIEW_FAST_COUNT_SQL:
            injected = True
            async with AsyncSession(migrated_engine) as writer, writer.begin():
                writer.add(review(_FIRST, third))
        return result

    monkeypatch.setattr(AsyncSession, "execute", after_count)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(reader_app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/admin/features/dedup-reviews")
    assert response.status_code == 200, response.text
    assert injected
    data = response.json()
    assert data["meta"]["page"]["total"] == 1
    assert len(data["data"]["items"]) == (1 if snapshot else 2)
