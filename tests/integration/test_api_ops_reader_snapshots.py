"""관리·운영 reader의 SELECT 사이 writer commit을 실제 PostgreSQL로 반증한다."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from kortravelmap.api import db as api_db
from kortravelmap.api import ops_dataset_service
from kortravelmap.api.app import create_app
from kortravelmap.api.ops_dataset_schedule import DatasetScheduleIndex
from kortravelmap.api.routers import admin_issues
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra import file_registry, status_repo
from kortravelmap.infra.integrity_violation_repo import create_data_integrity_violation
from tests.integration._db_cleanup import truncate_committed_test_rows
from tests.integration._feature_ids import feature_uuid
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
