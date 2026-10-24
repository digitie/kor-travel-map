"""관리·운영 reader의 SELECT 사이 writer commit을 실제 PostgreSQL로 반증한다."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from kortravelmap.api import db as api_db
from kortravelmap.api import ops_dataset_service
from kortravelmap.api.app import create_app
from kortravelmap.api.ops_dataset_schedule import DatasetScheduleIndex
from kortravelmap.api.routers import admin_issues
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra import cache_target_reconciliation_repo as cache_repo
from kortravelmap.infra import file_registry, status_repo
from kortravelmap.infra.integrity_violation_repo import create_data_integrity_violation
from tests.integration._db_cleanup import truncate_committed_test_rows
from tests.integration._feature_ids import feature_uuid
from tests.integration.test_cache_target_stream_repo import (
    _STREAM_TRUNCATE_SQL,
    _apply_snapshot_source,
    _reconciliation_command,
)
from tests.integration.test_ops_repo import _membership
from tests.integration.test_poi_cache_target_nearby import _insert_feature

pytestmark = pytest.mark.integration
_FIRST = feature_uuid("ops-reader-snapshot-first")
_SECOND = feature_uuid("ops-reader-snapshot-second")


@pytest.fixture
async def ops_reader_app(migrated_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(api_db, "_get_engine", lambda: migrated_engine)
    async with AsyncSession(migrated_engine) as session, session.begin():
        await _insert_feature(session, feature_id=_FIRST, name="old", lon=127.0, lat=37.5)
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    try:
        yield app
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await truncate_committed_test_rows(
                session,
                "TRUNCATE feature.features, provider_sync.source_entities, "
                "ops.managed_files, ops.data_integrity_violations RESTART IDENTITY CASCADE",
            )
            for table in [
                "provider_dataset_operation_scopes",
                "provider_dataset_operations",
                "provider_datasets",
            ]:
                await session.execute(
                    text(
                        f"DELETE FROM provider_sync.{table} WHERE provider_dataset_id IN "
                        "(SELECT provider_dataset_id FROM provider_sync.provider_datasets "
                        "WHERE provider='ops-reader-test')"
                    )
                )


def _control(app: Any, engine: AsyncEngine, snapshot: bool) -> None:
    if snapshot:
        return

    async def read_committed() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine) as session:
            yield session

    app.dependency_overrides[api_db.get_read_snapshot_session] = read_committed


@pytest.mark.parametrize("snapshot", [False, True], ids=["rc-counterexample", "repeatable-read"])
async def test_metrics_totals_and_kind_counts_share_snapshot(
    ops_reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: bool,
) -> None:
    _control(ops_reader_app, migrated_engine, snapshot)
    original = AsyncSession.execute
    injected = False

    async def after_total(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any):
        nonlocal injected
        result = await original(self, statement, *args, **kwargs)
        if not injected and str(statement) == status_repo._FEATURES_SQL:
            injected = True
            async with AsyncSession(migrated_engine) as writer, writer.begin():
                await _insert_feature(writer, feature_id=_SECOND, name="new", lon=127.0, lat=37.5)
        return result

    monkeypatch.setattr(AsyncSession, "execute", after_total)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(ops_reader_app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/ops/metrics")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert injected
    assert data["features_total"] == 1
    assert sum(data["features_by_kind"].values()) == (1 if snapshot else 2)


@pytest.mark.parametrize("snapshot", [False, True], ids=["rc-counterexample", "repeatable-read"])
async def test_file_metadata_and_events_share_snapshot(
    ops_reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: bool,
) -> None:
    async with AsyncSession(migrated_engine) as writer, writer.begin():
        row = await file_registry.register_file(
            writer,
            storage_backend="filesystem",
            location="backup_root",
            path="ops-reader-file",
            kind="backup",
            event_kind=None,
        )
    _control(ops_reader_app, migrated_engine, snapshot)
    original = file_registry.get_managed_file

    async def after_file(session: AsyncSession, file_id: int):
        result = await original(session, file_id)
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            await file_registry.mark_missing(writer, file_id=file_id)
        return result

    monkeypatch.setattr(file_registry, "get_managed_file", after_file)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(ops_reader_app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/admin/files/{row.file_id}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["file"]["status"] == "active"
    assert [event["event_kind"] for event in data["events"]] == (
        [] if snapshot else ["marked_missing"]
    )


@pytest.mark.parametrize("snapshot", [False, True], ids=["rc-counterexample", "repeatable-read"])
async def test_issue_and_linked_feature_share_snapshot(
    ops_reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: bool,
) -> None:
    async with AsyncSession(migrated_engine) as writer, writer.begin():
        issue = await create_data_integrity_violation(
            writer,
            violation_type="reader_test",
            severity="warning",
            message="old",
            feature_id=_FIRST,
        )
    _control(ops_reader_app, migrated_engine, snapshot)
    original = admin_issues.get_data_integrity_violation

    async def after_issue(session: AsyncSession, issue_id: str):
        result = await original(session, issue_id)
        async with migrated_engine.begin() as writer:
            await writer.execute(
                text(
                    "UPDATE feature.features SET coord=x_extension.ST_SetSRID("
                    "x_extension.ST_MakePoint(128.0,37.5),4326) WHERE feature_id=:id"
                ),
                {"id": _FIRST},
            )
        return result

    monkeypatch.setattr(admin_issues, "get_data_integrity_violation", after_issue)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(ops_reader_app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/admin/issues/{issue.issue_id}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["issue"]["message"] == "old"
    assert data["feature"]["lon"] == (127.0 if snapshot else 128.0)


@pytest.mark.parametrize("snapshot", [False, True], ids=["rc-counterexample", "repeatable-read"])
async def test_dataset_db_phase_begins_after_external_schedule_and_is_consistent(
    ops_reader_app: Any,
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: bool,
) -> None:
    _control(ops_reader_app, migrated_engine, snapshot)
    original = ops_dataset_service.sync_state_repo.list_all_sync_states
    external_done = False
    first_db = False

    async def schedule(**_kwargs: Any):
        nonlocal external_done
        assert not first_db
        external_done = True
        return DatasetScheduleIndex(source_status="unavailable", errors=(), by_operation_key={})

    async def after_states(session: AsyncSession):
        nonlocal first_db
        assert external_done
        first_db = True
        result = await original(session)
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            await _membership(writer, provider="ops-reader-test", dataset_key="new")
        return result

    monkeypatch.setattr(ops_dataset_service, "load_dataset_schedule_index", schedule)
    monkeypatch.setattr(ops_dataset_service.sync_state_repo, "list_all_sync_states", after_states)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(ops_reader_app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/ops/datasets")
    assert response.status_code == 200, response.text
    assert external_done
    assert first_db
    rows = response.json()["data"]["items"]
    assert any(row["provider"] == "ops-reader-test" for row in rows) is (not snapshot)


@pytest.mark.parametrize("readonly_control", [True, False], ids=["readonly-rejected", "locking-rr"])
async def test_reconciliation_actual_rowlock_guard_and_pool_lifetime(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    readonly_control: bool,
) -> None:
    monkeypatch.setattr(api_db, "_get_engine", lambda: migrated_engine)
    system = "ops-reader-snapshot-lock"
    token = "ops-reader-local-snapshot-token"
    profiles = [
        ["cache-target:command"],
        [
            "cache-target:read",
            "cache-target:claim",
            "cache-target:ack",
            "cache-target:nack",
            "cache-target:snapshot",
        ],
        ["cache-target:restore-fence"],
        ["cache-target:recovery", "cache-target:recovery-replay"],
    ]
    app = create_app(
        ApiSettings(
            public_api_key_required=False,
            vworld_api_key=None,
            cache_target_service_principals=[
                {
                    "principal_id": f"svc:ops-reader-{index}",
                    "consumer_id": "pinvi-cache-consumer",
                    "token_sha256": hashlib.sha256(
                        (token if index == 1 else f"{token}-{index}").encode()
                    ).hexdigest(),
                    "scopes": profile,
                    "external_systems": [system],
                }
                for index, profile in enumerate(profiles)
            ],
        )
    )
    async with AsyncSession(migrated_engine) as writer, writer.begin():
        await _apply_snapshot_source(
            writer,
            external_system=system,
            target_key="one",
            event_id="91110000-0000-4000-8000-000000000001",
            idempotency_key="91110000-0000-4000-8000-000000000002",
        )
        command = await _reconciliation_command(writer, key=str(uuid4()))
        request = await cache_repo.request_cache_target_reconciliation(
            writer,
            command_id=command,
            external_system=system,
            reason="reader snapshot test",
        )
    if readonly_control:
        app.dependency_overrides[api_db.get_locking_read_snapshot_session] = (
            api_db.get_read_snapshot_session
        )
    original = AsyncSession.execute
    writer_started = asyncio.Event()
    writer_task = None
    mode_checked = False
    writer_pid = None

    async def change_stream() -> None:
        nonlocal writer_pid
        async with migrated_engine.begin() as writer:
            writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
            await writer.execute(text("SET LOCAL lock_timeout='2s'"))
            await writer.execute(text("SET LOCAL statement_timeout='3s'"))
            writer_started.set()
            await writer.execute(
                text(
                    "UPDATE ops.poi_cache_target_streams SET consumer_enabled=true "
                    "WHERE external_system=:system"
                ),
                {"system": system},
            )

    async def before_items(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any):
        nonlocal writer_task, mode_checked
        if str(statement) == cache_repo._GET_SNAPSHOT_ITEMS_SQL:
            assert await self.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert await self.scalar(text("SHOW transaction_read_only")) == "off"
            mode_checked = True
            writer_task = asyncio.create_task(change_stream())
            await asyncio.wait_for(writer_started.wait(), timeout=2)
            reader_pid = await self.scalar(text("SELECT pg_backend_pid()"))
            async with migrated_engine.connect() as observer:
                async with asyncio.timeout(1):
                    while True:
                        blockers = await observer.scalar(
                            text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pid}
                        )
                        if reader_pid in blockers:
                            break
                        await asyncio.sleep(0.01)
            assert not writer_task.done()  # 관측한 blocker가 reader여야 한다.
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", before_items)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            url = f"/v1/service/cache-target-reconciliations/{request.request_id}/snapshot"
            headers = {"X-Kor-Travel-Map-Service-Token": token}
            if readonly_control:
                with pytest.raises(DBAPIError) as error:
                    await client.get(url, headers=headers)
                assert error.value.orig.sqlstate == "25006"
                assert not mode_checked
            else:
                response = await client.get(url, headers=headers)
                assert response.status_code == 200, response.text
                assert mode_checked
                assert writer_task is not None
                await asyncio.wait_for(writer_task, timeout=2)
                assert len(response.json()["data"]["items"]) == 1
        async with AsyncSession(migrated_engine) as probe:
            assert await probe.scalar(text("SHOW transaction_isolation")) == "read committed"
            assert await probe.scalar(text("SHOW transaction_read_only")) == "off"
    finally:
        if writer_task is not None:
            await asyncio.wait_for(writer_task, timeout=3)
        async with AsyncSession(migrated_engine) as cleanup, cleanup.begin():
            await truncate_committed_test_rows(cleanup, _STREAM_TRUNCATE_SQL)
