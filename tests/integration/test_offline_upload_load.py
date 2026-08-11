"""offline upload load job 통합 테스트."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap import offline_upload as offline_upload_module
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.core.managed_file_states import MANAGED_FILE_LOCATION_OFFLINE_UPLOADS
from kortravelmap.core.offline_upload_states import OFFLINE_UPLOAD_STATE_VALUES
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import file_registry
from kortravelmap.infra.feature_update_active_repo import _driver_constraint_identity
from kortravelmap.infra.jobs_repo import (
    ImportJobDatasetTarget,
    start_provider_dataset_import_job,
)
from kortravelmap.infra.offline_upload_repo import (
    OfflineUploadScopeOperationUnresolved,
    OfflineUploadStatusConflict,
    create_offline_upload,
    delete_offline_upload,
    finish_offline_upload_load,
    finish_offline_upload_validation,
    get_offline_upload,
    get_offline_upload_by_checksum,
    is_inactive_dataset_membership_violation,
    list_offline_uploads,
    mark_offline_upload_loading,
    reserve_offline_upload,
    reserve_offline_upload_delete,
    reserve_offline_upload_load,
    resolve_offline_upload_operation_key,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    create_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
)
from kortravelmap.infra.pipeline_cancellation_types import PipelineCancellationConflict
from tests.integration._db_cleanup import truncate_committed_test_rows

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED_AT = datetime(2026, 6, 3, 14, 0, tzinfo=_KST)
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_entities, "
    "provider_sync.source_records, provider_sync.source_links, "
    "ops.import_jobs, ops.offline_uploads "
    "RESTART IDENTITY CASCADE"
)


class _MemoryStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.read_count = 0

    async def read_bytes(self, storage_key: str) -> bytes:
        self.read_count += 1
        return self.objects[storage_key]


@pytest.fixture(autouse=True)
async def clean_offline_upload_tables(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[None]:
    await _truncate(migrated_engine)
    yield
    await _truncate(migrated_engine)


async def test_offline_upload_load_job_persists_feature_and_job(
    migrated_engine: AsyncEngine,
) -> None:
    bundle = _bundle("offline-success-001")
    body = bundle.model_dump_json().encode("utf-8")
    storage_key = "offline/offline-success-001/features.jsonl"
    upload_id = await _create_upload(migrated_engine, body=body, storage_key=storage_key)

    client = AsyncKorTravelMapClient(migrated_engine)
    result = await client.run_offline_upload_load_job(
        upload_id,
        store=_MemoryStore({storage_key: body}),
        dagster_run_id="dagster-run-offline-success",
    )

    assert result.acquired is True
    assert result.error_message is None
    assert result.job is not None
    assert result.job.status == "done"
    assert result.load is not None
    assert result.load.bundles_total == 1
    assert result.upload is not None
    assert result.upload.status == "loaded"

    async with AsyncSession(migrated_engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT f.feature_id, ou.status AS upload_status, ij.status AS job_status "
                    "FROM feature.features AS f "
                    "JOIN ops.offline_uploads AS ou ON ou.upload_id = :upload_id "
                    "JOIN ops.import_jobs AS ij ON ij.job_id = ou.load_job_id "
                    "WHERE f.feature_id = :feature_id"
                ),
                {"upload_id": upload_id, "feature_id": bundle.feature.feature_id},
            )
        ).one()

    assert row.feature_id == bundle.feature.feature_id
    assert row.upload_status == "loaded"
    assert row.job_status == "done"


async def test_offline_upload_load_job_uses_preclaimed_load_job(
    migrated_engine: AsyncEngine,
) -> None:
    bundle = _bundle("offline-preclaim-001")
    body = bundle.model_dump_json().encode("utf-8")
    storage_key = "offline/offline-preclaim-001/features.jsonl"
    upload_id = await _create_upload(migrated_engine, body=body, storage_key=storage_key)

    async with AsyncSession(migrated_engine) as session, session.begin():
        job = await start_provider_dataset_import_job(
            session,
            kind="offline_upload_load",
            dataset_membership=await _offline_membership(session),
            payload={"upload_id": upload_id, "dagster_run_id": None},
            source_checksum=hashlib.sha256(body).hexdigest(),
        )
        loading = await mark_offline_upload_loading(
            session,
            upload_id=upload_id,
            load_job_id=job.job_id,
        )
        assert loading is not None
        assert loading.status == "loading"
        assert loading.load_job_id == job.job_id

    client = AsyncKorTravelMapClient(migrated_engine)
    result = await client.run_offline_upload_load_job(
        upload_id,
        store=_MemoryStore({storage_key: body}),
        dagster_run_id="dagster-run-preclaimed",
    )

    assert result.acquired is True
    assert result.error_message is None
    assert result.job is not None
    assert result.job.job_id == job.job_id
    assert result.job.status == "done"
    assert result.job.dagster_run_id == "dagster-run-preclaimed"
    assert result.job.payload["dagster_run_id"] is None
    assert result.upload is not None
    assert result.upload.status == "loaded"


async def test_preclaimed_run_owner_mismatch_stops_before_object_io(
    migrated_engine: AsyncEngine,
) -> None:
    bundle = _bundle("offline-owner-mismatch")
    body = bundle.model_dump_json().encode("utf-8")
    storage_key = "offline/offline-owner-mismatch/features.jsonl"
    upload_id = await _create_upload(migrated_engine, body=body, storage_key=storage_key)

    async with AsyncSession(migrated_engine) as session, session.begin():
        job = await start_provider_dataset_import_job(
            session,
            kind="offline_upload_load",
            dataset_membership=await _offline_membership(session),
            payload={"upload_id": upload_id},
            source_checksum=hashlib.sha256(body).hexdigest(),
            dagster_run_id="owner-run",
        )
        assert await mark_offline_upload_loading(
            session,
            upload_id=upload_id,
            load_job_id=job.job_id,
        ) is not None

    store = _MemoryStore({storage_key: body})
    client = AsyncKorTravelMapClient(migrated_engine)
    with pytest.raises(PipelineCancellationConflict):
        await client.run_offline_upload_load_job(
            upload_id,
            store=store,
            dagster_run_id="other-run",
        )

    assert store.read_count == 0
    async with AsyncSession(migrated_engine) as session:
        state = (
            await session.execute(
                text(
                    "SELECT status, dagster_run_id FROM ops.import_jobs "
                    "WHERE job_id = CAST(:job_id AS uuid)"
                ),
                {"job_id": job.job_id},
            )
        ).one()
    assert (state.status, state.dagster_run_id) == ("running", "owner-run")


async def test_preclaimed_marker_race_stops_before_object_and_feature_io(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle("offline-marker-race")
    body = bundle.model_dump_json().encode("utf-8")
    storage_key = "offline/offline-marker-race/features.jsonl"
    upload_id = await _create_upload(migrated_engine, body=body, storage_key=storage_key)

    async with AsyncSession(migrated_engine) as session, session.begin():
        job = await start_provider_dataset_import_job(
            session,
            kind="offline_upload_load",
            dataset_membership=await _offline_membership(session),
            payload={"upload_id": upload_id},
            source_checksum=hashlib.sha256(body).hexdigest(),
        )
        assert await mark_offline_upload_loading(
            session,
            upload_id=upload_id,
            load_job_id=job.job_id,
        ) is not None

    selected = asyncio.Event()
    marker_committed = asyncio.Event()
    original_get_import_job = offline_upload_module.get_import_job
    paused = False

    async def get_import_job_with_barrier(
        session: AsyncSession, selected_job_id: str
    ) -> object:
        nonlocal paused
        loaded = await original_get_import_job(session, selected_job_id)
        if selected_job_id == job.job_id and not paused:
            paused = True
            selected.set()
            await marker_committed.wait()
        return loaded

    monkeypatch.setattr(
        offline_upload_module, "get_import_job", get_import_job_with_barrier
    )
    store = _MemoryStore({storage_key: body})
    client = AsyncKorTravelMapClient(migrated_engine)
    load_task = asyncio.create_task(
        client.run_offline_upload_load_job(upload_id, store=store)
    )
    await selected.wait()
    try:
        async with AsyncSession(migrated_engine) as marker_session, marker_session.begin():
            scope = await resolve_pipeline_cancellation_scope(
                marker_session,
                kind="import_job",
                execution_id=job.job_id,
            )
            assert scope is not None
            detail = await create_pipeline_cancellation_attempt(
                marker_session,
                scope=scope,
                requested_by="admin:marker-race",
                reason="preclaimed marker race",
            )
            cancellation_id = detail.attempt.cancellation_id
    finally:
        marker_committed.set()

    with pytest.raises(PipelineCancellationConflict):
        await load_task

    assert store.read_count == 0
    async with AsyncSession(migrated_engine) as session:
        state = (
            await session.execute(
                text(
                    "SELECT ij.status AS job_status, ij.cancellation_id, "
                    "ou.status AS upload_status, ou.load_job_id "
                    "FROM ops.import_jobs AS ij "
                    "JOIN ops.offline_uploads AS ou ON ou.load_job_id = ij.job_id "
                    "WHERE ij.job_id = CAST(:job_id AS uuid)"
                ),
                {"job_id": job.job_id},
            )
        ).one()
        feature_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM feature.features "
                    "WHERE feature_id = :feature_id"
                ),
                {"feature_id": bundle.feature.feature_id},
            )
        ).scalar_one()

    assert state.job_status == "running"
    assert str(state.cancellation_id) == cancellation_id
    assert state.upload_status == "loading"
    assert str(state.load_job_id) == job.job_id
    assert int(feature_count) == 0


async def test_offline_upload_validate_then_load_csv(
    migrated_engine: AsyncEngine,
) -> None:
    body = (
        "name,lon,lat,address,source_id\n"
        "오프라인 CSV 통합 장소,126.9780,37.5665,서울특별시 중구 세종대로,csv-live-001\n"
    ).encode()
    storage_key = "offline/offline-csv-001/features.csv"
    upload_id = await _create_upload(
        migrated_engine,
        body=body,
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        dataset_key="offline_csv",
    )
    store = _MemoryStore({storage_key: body})

    client = AsyncKorTravelMapClient(migrated_engine)
    validation = await client.run_offline_upload_validation_job(
        upload_id,
        store=store,
        column_mapping={
            "name": "name",
            "lon": "lon",
            "lat": "lat",
            "address": "address",
            "source_id": "source_id",
        },
        sample_size=100,
        operator="pytest",
        address_resolver=_fake_address_resolver,
    )
    assert validation.has_errors is False
    assert validation.valid_rows == 1
    assert validation.upload.status == "validated"
    assert validation.job is not None
    assert validation.job.status == "done"

    loaded = await client.run_offline_upload_load_job(
        upload_id,
        store=store,
        dagster_run_id="dagster-run-offline-csv",
        address_resolver=_fake_address_resolver,
    )

    assert loaded.error_message is None
    assert loaded.load is not None
    assert loaded.load.bundles_total == 1
    assert loaded.upload is not None
    assert loaded.upload.status == "loaded"

    async with AsyncSession(migrated_engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT f.name, se.source_entity_id, ou.status AS upload_status "
                    "FROM feature.features AS f "
                    "JOIN provider_sync.source_links AS sl "
                    "  ON sl.feature_id = f.feature_id "
                    "JOIN provider_sync.source_entities AS se "
                    "  ON se.source_entity_key = sl.source_entity_key "
                    "JOIN provider_sync.source_entity_heads AS head "
                    "  ON head.source_entity_key = se.source_entity_key "
                    "JOIN provider_sync.source_records AS sr "
                    "  ON sr.source_record_key = head.current_source_record_key "
                    "JOIN ops.offline_uploads AS ou ON ou.upload_id = :upload_id "
                    "WHERE se.source_entity_id = :source_entity_id"
                ),
                {"upload_id": upload_id, "source_entity_id": "csv-live-001"},
            )
        ).one()

    assert row.name == "오프라인 CSV 통합 장소"
    assert row.source_entity_id == "csv-live-001"
    assert row.upload_status == "loaded"


async def test_offline_upload_load_job_records_checksum_failure(
    migrated_engine: AsyncEngine,
) -> None:
    bundle = _bundle("offline-checksum-001")
    body = bundle.model_dump_json().encode("utf-8")
    storage_key = "offline/offline-checksum-001/features.jsonl"
    upload_id = await _create_upload(
        migrated_engine,
        body=body,
        storage_key=storage_key,
        checksum_sha256="0" * 64,
    )

    client = AsyncKorTravelMapClient(migrated_engine)
    result = await client.run_offline_upload_load_job(
        upload_id,
        store=_MemoryStore({storage_key: body}),
        dagster_run_id="dagster-run-offline-failed",
    )

    assert result.acquired is True
    assert result.error_message
    assert "checksum mismatch" in result.error_message
    assert result.job is not None
    assert result.job.status == "failed"
    assert result.upload is not None
    assert result.upload.status == "load_failed"

    async with AsyncSession(migrated_engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT ou.status AS upload_status, ij.status AS job_status, "
                    "ij.error_message "
                    "FROM ops.offline_uploads AS ou "
                    "JOIN ops.import_jobs AS ij ON ij.job_id = ou.load_job_id "
                    "WHERE ou.upload_id = :upload_id"
                ),
                {"upload_id": upload_id},
            )
        ).one()
        feature_count = (
            await session.execute(
                text("SELECT count(*) FROM feature.features WHERE feature_id = :feature_id"),
                {"feature_id": bundle.feature.feature_id},
            )
        ).scalar_one()

    assert row.upload_status == "load_failed"
    assert row.job_status == "failed"
    assert "checksum mismatch" in row.error_message
    assert int(feature_count) == 0


async def test_offline_upload_repo_rejects_invalid_state_transitions(
    migrated_engine: AsyncEngine,
) -> None:
    body = _bundle("offline-state-guard-001").model_dump_json().encode("utf-8")
    upload_id = await _create_upload(
        migrated_engine,
        body=body,
        storage_key="offline/offline-state-guard-001/features.jsonl",
    )

    async with AsyncSession(migrated_engine) as session, session.begin():
        with pytest.raises(OfflineUploadStatusConflict) as finish_conflict:
            await finish_offline_upload_load(
                session,
                upload_id=upload_id,
                status="loaded",
            )
        assert finish_conflict.value.current_status == "uploaded"
        assert finish_conflict.value.allowed_statuses == frozenset({"loading"})

        job = await start_provider_dataset_import_job(
            session,
            kind="offline_upload_load",
            dataset_membership=await _offline_membership(session),
        )
        loading = await mark_offline_upload_loading(
            session,
            upload_id=upload_id,
            load_job_id=job.job_id,
        )
        assert loading is not None
        assert loading.status == "loading"

        loaded = await finish_offline_upload_load(
            session,
            upload_id=upload_id,
            status="loaded",
        )
        assert loaded is not None
        assert loaded.status == "loaded"

        with pytest.raises(OfflineUploadStatusConflict) as reload_conflict:
            await mark_offline_upload_loading(
                session,
                upload_id=upload_id,
                load_job_id=job.job_id,
            )
        assert reload_conflict.value.current_status == "loaded"
        assert reload_conflict.value.target_status == "loading"


async def test_offline_upload_repo_reserves_load_job_transactionally(
    migrated_engine: AsyncEngine,
) -> None:
    body = _bundle("offline-reserve-001").model_dump_json().encode("utf-8")
    upload_id = await _create_upload(
        migrated_engine,
        body=body,
        storage_key="offline/offline-reserve-001/features.jsonl",
    )

    async with AsyncSession(migrated_engine) as session, session.begin():
        loading = await reserve_offline_upload_load(session, upload_id=upload_id)
        assert loading is not None
        assert loading.status == "loading"
        assert loading.load_job_id is not None

    async with AsyncSession(migrated_engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT ou.status AS upload_status, ou.load_job_id, "
                    "ij.status AS job_status, ij.kind, ij.source_checksum "
                    "FROM ops.offline_uploads AS ou "
                    "JOIN ops.import_jobs AS ij ON ij.job_id = ou.load_job_id "
                    "WHERE ou.upload_id = :upload_id"
                ),
                {"upload_id": upload_id},
            )
        ).one()

    assert row.upload_status == "loading"
    assert row.job_status == "running"
    assert row.kind == "offline_upload_load"
    assert row.source_checksum == hashlib.sha256(body).hexdigest()


async def test_offline_upload_repo_enforces_checksum_idempotency(
    migrated_engine: AsyncEngine,
) -> None:
    body = _bundle("offline-idempotent-001").model_dump_json().encode("utf-8")
    checksum = hashlib.sha256(body).hexdigest()
    first_id = await _create_upload(
        migrated_engine,
        body=body,
        storage_key="offline/idempotent/first.jsonl",
        checksum_sha256=checksum,
    )

    with pytest.raises(IntegrityError):
        async with AsyncSession(migrated_engine) as session, session.begin():
            await create_offline_upload(
                session,
                upload_id="00000000-0000-0000-0000-000000000099",
                provider_dataset_id=await _offline_provider_dataset_id(session),
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key="offline/idempotent/duplicate.jsonl",
                byte_size=len(body),
                checksum_sha256=checksum,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )

    async with AsyncSession(migrated_engine) as session:
        existing = await get_offline_upload_by_checksum(
            session,
            provider_dataset_id=await _offline_provider_dataset_id(session),
            sync_scope="dataset_wide",
            operation_key=_offline_operation_key("offline_jsonl"),
            checksum_sha256=checksum,
        )

    assert existing is not None
    assert existing.upload_id == first_id


async def test_offline_upload_repo_lists_with_keyset_and_provided_upload_id(
    migrated_engine: AsyncEngine,
) -> None:
    body = _bundle("offline-list-001").model_dump_json().encode("utf-8")
    second_body = _bundle("offline-list-002").model_dump_json().encode("utf-8")
    first_id = "00000000-0000-0000-0000-000000000001"
    second_id = "00000000-0000-0000-0000-000000000002"
    await _create_upload(
        migrated_engine,
        body=body,
        storage_key="offline/list/first.jsonl",
        upload_id=first_id,
    )
    await _create_upload(
        migrated_engine,
        body=second_body,
        storage_key="offline/list/second.jsonl",
        upload_id=second_id,
    )

    async with AsyncSession(migrated_engine) as session:
        page1 = await list_offline_uploads(
            session,
            provider_dataset_id=await _offline_provider_dataset_id(session),
            limit=1,
        )
        assert page1.next_cursor is not None
        assert page1.items[0].upload_id == second_id

        page2 = await list_offline_uploads(
            session,
            provider_dataset_id=await _offline_provider_dataset_id(session),
            limit=1,
            cursor=page1.next_cursor,
        )
        assert page2.items[0].upload_id == first_id
        assert page2.next_cursor is None


async def test_delete_offline_upload_unblocks_same_checksum_reupload(
    migrated_engine: AsyncEngine,
) -> None:
    """좀비 업로드(#397) 정리: row 삭제로 checksum 멱등 가드(409)가 풀려야 한다."""
    body = _bundle("offline-delete-001").model_dump_json().encode("utf-8")
    checksum = hashlib.sha256(body).hexdigest()
    upload_id = await _create_upload(
        migrated_engine,
        body=body,
        storage_key="offline/delete/zombie.jsonl",
        checksum_sha256=checksum,
    )

    async with AsyncSession(migrated_engine) as session, session.begin():
        command_id = await _reserve_delete(session, upload_id)
        deleted = await delete_offline_upload(
            session,
            upload_id=upload_id,
            command_id=command_id,
        )
    assert deleted is not None
    assert deleted.upload_id == upload_id
    assert deleted.checksum_sha256 == checksum

    async with AsyncSession(migrated_engine) as session:
        assert await get_offline_upload(session, upload_id) is None
        assert (
            await delete_offline_upload(
                session,
                upload_id=upload_id,
                command_id=command_id,
            )
            is None
        )

    # 같은 provider/dataset/scope/checksum 재업로드가 더는 unique 제약에 안 걸린다.
    second_id = await _create_upload(
        migrated_engine,
        body=body,
        storage_key="offline/delete/reupload.jsonl",
        checksum_sha256=checksum,
    )
    assert second_id != upload_id


async def test_delete_offline_upload_rejects_in_progress_and_keeps_jobs(
    migrated_engine: AsyncEngine,
) -> None:
    body = _bundle("offline-delete-002").model_dump_json().encode("utf-8")
    upload_id = await _create_upload(
        migrated_engine,
        body=body,
        storage_key="offline/delete/in-progress.jsonl",
    )

    async with AsyncSession(migrated_engine) as session, session.begin():
        job = await start_provider_dataset_import_job(
            session,
            kind="offline_upload_load",
            dataset_membership=await _offline_membership(session),
            payload={"upload_id": upload_id, "dagster_run_id": None},
            source_checksum=hashlib.sha256(body).hexdigest(),
        )
        loading = await mark_offline_upload_loading(
            session,
            upload_id=upload_id,
            load_job_id=job.job_id,
        )
        assert loading is not None

    # 진행 중(loading) row는 삭제 거부.
    with pytest.raises(OfflineUploadStatusConflict):
        async with AsyncSession(migrated_engine) as session, session.begin():
            await _reserve_delete(session, upload_id)

    async with AsyncSession(migrated_engine) as session, session.begin():
        finished = await finish_offline_upload_load(
            session,
            upload_id=upload_id,
            status="load_failed",
        )
        assert finished is not None

    async with AsyncSession(migrated_engine) as session, session.begin():
        command_id = await _reserve_delete(session, upload_id)
        deleted = await delete_offline_upload(
            session,
            upload_id=upload_id,
            command_id=command_id,
        )
    assert deleted is not None
    assert deleted.status == "deleting"

    # 연관 import job row는 audit 기록으로 남는다.
    async with AsyncSession(migrated_engine) as session:
        job_row = (
            await session.execute(
                text("SELECT job_id FROM ops.import_jobs WHERE job_id = :job_id"),
                {"job_id": job.job_id},
            )
        ).one_or_none()
    assert job_row is not None


# ---------------------------------------------------------------------------
# T-VN-33 (ADR-088) — scope→operation 유도 회귀.
#
# 업로드 요청 표면에는 operation이 없다. ``ops.offline_uploads``의 identity는
# triple이므로 repo가 (dataset, scope)에서 operation을 **유도**한다. 오늘 실측 시드는
# scope당 refresh operation이 최대 1개고 disabled operation이 0건이라 유도가 늘
# 성공하지만, 그건 계약이 아니라 우연한 데이터 상태다 — scope PK가 triple이라
# 형제 operation 등록은 스키마가 허용하는 정상 write다. 아래 세 테스트가 그 상태를
# 직접 만들어 유도 규칙을 밟는다.
# ---------------------------------------------------------------------------


async def test_resolve_scope_operation_rejects_when_only_operation_is_disabled(
    migrated_engine: AsyncEngine,
) -> None:
    """유일한 operation이 disabled면 **typed 409**지 DB 트리거 500이 아니다.

    후보를 ``is_enabled`` 없이 세면 repo가 disabled operation_key를 골라 INSERT까지
    가고, 그러면 ``reject_inactive_offline_upload_membership``이 23514로 터진다 —
    운영자에게는 500이다. 유도가 DB 가드와 같은 조건을 봐야 typed 오류로 끝난다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            await session.execute(
                text(
                    """
                    UPDATE provider_sync.provider_dataset_operations
                       SET is_enabled = false
                     WHERE provider_dataset_id = :dataset_id
                       AND operation_key = :operation_key
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "operation_key": _offline_operation_key("offline_jsonl"),
                },
            )

            with pytest.raises(OfflineUploadScopeOperationUnresolved) as excinfo:
                await create_offline_upload(
                    session,
                    provider_dataset_id=dataset_id,
                    sync_scope="dataset_wide",
                    original_filename="features.jsonl",
                    storage_backend="rustfs",
                    storage_key="offline/disabled-only/features.jsonl",
                    byte_size=3,
                    checksum_sha256="b" * 64,
                    detected_format="jsonl",
                    detected_encoding="utf-8",
                    created_by="pytest",
                )

            # disabled operation은 후보로 세지 않는다 — "0개"로 보여야 라우터가
            # 올바른 처방을 낸다.
            assert excinfo.value.resolved == 0
            # typed 오류는 INSERT **전에** 났다: 트랜잭션이 아직 살아 있고 행도 없다.
            assert await _upload_count(session, dataset_id) == 0
        finally:
            await session.rollback()


async def test_reserve_offline_upload_rejects_when_dataset_is_inactive(
    migrated_engine: AsyncEngine,
) -> None:
    """dataset이 inactive면 reserve 경로도 typed 409로 끝난다.

    ``reserve_offline_upload``는 라우터가 실제로 부르는 진입점이다. 유도가
    ``dataset.is_active``를 안 보면 여기서도 disabled membership INSERT가 DB 가드에
    걸려 500이 된다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            await session.execute(
                text(
                    """
                    UPDATE provider_sync.provider_datasets
                       SET is_active = false
                     WHERE provider_dataset_id = :dataset_id
                    """
                ),
                {"dataset_id": dataset_id},
            )

            with pytest.raises(OfflineUploadScopeOperationUnresolved) as excinfo:
                await reserve_offline_upload(
                    session,
                    upload_id="00000000-0000-0000-0000-0000000000a1",
                    provider_dataset_id=dataset_id,
                    sync_scope="dataset_wide",
                    original_filename="features.jsonl",
                    storage_backend="rustfs",
                    storage_key="offline/inactive-dataset/features.jsonl",
                    byte_size=3,
                    checksum_sha256="c" * 64,
                    detected_format="jsonl",
                    detected_encoding="utf-8",
                    created_by="pytest",
                )

            assert excinfo.value.resolved == 0
            assert await _upload_count(session, dataset_id) == 0
        finally:
            await session.rollback()


async def test_resolve_scope_operation_ignores_disabled_sibling_operation(
    migrated_engine: AsyncEngine,
) -> None:
    """disabled 형제는 후보 수를 부풀리면 안 된다.

    형제를 세면 멀쩡한 scope가 "operation이 둘 이상"으로 오판돼 정상 업로드가
    409로 막힌다 — 가용성 회귀다. 유도는 활성인 것만 센다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            enabled_key = _offline_operation_key("offline_jsonl")
            # 형제 key를 **활성 key보다 앞서게** 짓는다. 유도 SQL이
            # ``ORDER BY scope.operation_key``라, 뒤에 오는 이름이면 후보를 잘못 세는
            # 구현도 우연히 맞는 key를 집어 테스트가 통과해 버린다.
            assert f"a_disabled_sibling.{enabled_key}" < enabled_key
            await _register_sibling_operation(
                session,
                dataset_id=dataset_id,
                operation_key=f"a_disabled_sibling.{enabled_key}",
                is_enabled=False,
            )

            upload = await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key="offline/disabled-sibling/features.jsonl",
                byte_size=3,
                checksum_sha256="d" * 64,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )

            # 유일한 **활성** operation에 결박된다 — 형제 때문에 흔들리지 않는다.
            assert upload.operation_key == enabled_key
        finally:
            await session.rollback()


async def test_resolve_scope_operation_refuses_ambiguous_enabled_operations(
    migrated_engine: AsyncEngine,
) -> None:
    """활성 operation이 둘이면 조용히 하나를 고르지 않고 실패한다.

    어느 쪽을 골라도 임의 선택이고, 잘못 고르면 upload가 **엉뚱한 실행**에 영구히
    결박된다(소유권은 triple이라 UPDATE로 못 고친다).
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            enabled_key = _offline_operation_key("offline_jsonl")
            sibling_key = f"{enabled_key}.enabled_sibling"
            await _register_sibling_operation(
                session,
                dataset_id=dataset_id,
                operation_key=sibling_key,
                is_enabled=True,
            )

            with pytest.raises(OfflineUploadScopeOperationUnresolved) as excinfo:
                await create_offline_upload(
                    session,
                    provider_dataset_id=dataset_id,
                    sync_scope="dataset_wide",
                    original_filename="features.jsonl",
                    storage_backend="rustfs",
                    storage_key="offline/ambiguous/features.jsonl",
                    byte_size=3,
                    checksum_sha256="e" * 64,
                    detected_format="jsonl",
                    detected_encoding="utf-8",
                    created_by="pytest",
                )

            assert excinfo.value.resolved == 2
            # 임의 결박이 없었다는 증거 — 두 후보 어느 쪽으로도 행이 안 생겼다.
            assert await _upload_count(session, dataset_id) == 0
        finally:
            await session.rollback()


# ---------------------------------------------------------------------------
# T-VN-33 후속(alembic 0092) — 비활성 membership에서의 **정리 경로** 회귀.
#
# 0091의 ``reject_inactive_offline_upload_membership``은 DELETE에도 활성 검사를
# 걸었다. 그래서 dataset ``is_active=false`` 또는 operation ``is_enabled=false``가
# 되는 순간 기존 upload 행이 UPDATE도 DELETE도 안 되는 상태로 굳었고, FK
# ``ON DELETE RESTRICT``가 상위 행 삭제까지 막아 탈출 경로가 없었다. 아래 테스트는
# (a) 정리가 뚫려야 하고 (b) **새 실행을 여는 write는 여전히 막혀야** 한다는 두 축을
# 같이 못박는다 — 한쪽만 있으면 반대 방향으로 과잉 수정해도 초록이 뜬다.
# ---------------------------------------------------------------------------


async def _deactivate_membership(
    session: AsyncSession,
    *,
    dataset_id: int,
    target: str,
    operation_key: str,
) -> None:
    """dataset 또는 operation을 비활성으로 만든다."""

    if target == "dataset":
        await session.execute(
            text(
                """
                UPDATE provider_sync.provider_datasets
                   SET is_active = false
                 WHERE provider_dataset_id = :dataset_id
                """
            ),
            {"dataset_id": dataset_id},
        )
        return
    if target != "operation":
        raise AssertionError(f"unknown deactivation target: {target!r}")
    await session.execute(
        text(
            """
            UPDATE provider_sync.provider_dataset_operations
               SET is_enabled = false
             WHERE provider_dataset_id = :dataset_id
               AND operation_key = :operation_key
            """
        ),
        {"dataset_id": dataset_id, "operation_key": operation_key},
    )


@pytest.mark.parametrize("target", ["operation", "dataset"])
async def test_offline_upload_delete_survives_membership_deactivation(
    migrated_engine: AsyncEngine,
    target: str,
) -> None:
    """비활성화 뒤에도 운영자는 upload를 예약·삭제할 수 있어야 한다.

    삭제는 두 write다: ``status='deleting'`` UPDATE(예약)와 DELETE. 0091 가드는
    **둘 다** 23514로 거부했다. 하나만 풀면 여전히 잠긴다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            operation_key = _offline_operation_key("offline_jsonl")
            upload = await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key=f"offline/cleanup-{target}/features.jsonl",
                byte_size=3,
                checksum_sha256="1" * 64,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )

            await _deactivate_membership(
                session,
                dataset_id=dataset_id,
                target=target,
                operation_key=operation_key,
            )

            command_id = await _reserve_delete(session, upload.upload_id)
            deleted = await delete_offline_upload(
                session,
                upload_id=upload.upload_id,
                command_id=command_id,
            )

            assert deleted is not None
            assert deleted.upload_id == upload.upload_id
            assert await _upload_count(session, dataset_id) == 0
        finally:
            await session.rollback()


async def test_offline_upload_winds_down_from_in_progress_after_deactivation(
    migrated_engine: AsyncEngine,
) -> None:
    """진행 중 행도 종료 상태로 내려와 삭제 가능해져야 한다.

    ``reserve_offline_upload_delete``는 ``OFFLINE_UPLOAD_DELETABLE_STATES``(진행 중이
    아닌 상태)에서만 예약한다. 그래서 DELETE만 면제하고 종료 상태 기록을 계속 막으면
    ``validating``/``loading``에 있던 행은 여전히 영구 잠금이다 — 그 구멍을 이 테스트가
    막는다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            operation_key = _offline_operation_key("offline_jsonl")
            upload = await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key="offline/cleanup-inflight/features.jsonl",
                byte_size=3,
                checksum_sha256="2" * 64,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )
            # membership이 아직 활성일 때 진행 중 상태로 들어간다(정상 경로).
            await session.execute(
                text(
                    "UPDATE ops.offline_uploads SET status = 'validating' "
                    "WHERE upload_id = :upload_id"
                ),
                {"upload_id": upload.upload_id},
            )

            await _deactivate_membership(
                session,
                dataset_id=dataset_id,
                target="operation",
                operation_key=operation_key,
            )

            finished = await finish_offline_upload_validation(
                session,
                upload_id=upload.upload_id,
                status="validation_failed",
            )
            assert finished is not None
            assert finished.status == "validation_failed"

            command_id = await _reserve_delete(session, upload.upload_id)
            assert (
                await delete_offline_upload(
                    session,
                    upload_id=upload.upload_id,
                    command_id=command_id,
                )
                is not None
            )
        finally:
            await session.rollback()


async def test_inactive_membership_blocks_exactly_the_new_work_statuses(
    migrated_engine: AsyncEngine,
) -> None:
    """면제 범위를 상태 전체에 대해 전수로 못박는다.

    ``validating``/``loading``만이 membership에 **새 실행**(validation/load import
    job)을 건다. 나머지 상태는 이미 있는 행을 내리는 정리 write다. 면제를 넓혀
    (모든 UPDATE 허용) 또는 좁혀(DELETE만 허용) 바꾸면 여기서 집합이 어긋난다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            operation_key = _offline_operation_key("offline_jsonl")
            upload = await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key="offline/status-sweep/features.jsonl",
                byte_size=3,
                checksum_sha256="3" * 64,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )
            delete_command_id = await session.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      'integration:offline-status-sweep',
                      'admin.offline-upload.delete',
                      x_extension.gen_random_uuid(),
                      repeat('b', 64)
                    )
                    RETURNING command_id
                    """
                )
            )
            await _deactivate_membership(
                session,
                dataset_id=dataset_id,
                target="operation",
                operation_key=operation_key,
            )

            blocked: set[str] = set()
            for status_value in OFFLINE_UPLOAD_STATE_VALUES:
                savepoint = await session.begin_nested()
                try:
                    await session.execute(
                        text(
                            """
                            UPDATE ops.offline_uploads
                               SET status = CAST(:status AS text),
                                   delete_command_id = CASE
                                       WHEN CAST(:status AS text) = 'deleting'
                                       THEN CAST(:command_id AS bigint)
                                       ELSE NULL
                                   END
                             WHERE upload_id = :upload_id
                            """
                        ),
                        {
                            "status": status_value,
                            "command_id": delete_command_id,
                            "upload_id": upload.upload_id,
                        },
                    )
                except IntegrityError:
                    blocked.add(status_value)
                await savepoint.rollback()

            assert blocked == {"validating", "loading"}

            # DELETE도 면제 대상이다 — 위 sweep은 UPDATE 축만 본다.
            savepoint = await session.begin_nested()
            await session.execute(
                text("DELETE FROM ops.offline_uploads WHERE upload_id = :upload_id"),
                {"upload_id": upload.upload_id},
            )
            await savepoint.rollback()
        finally:
            await session.rollback()


async def test_inactive_membership_still_rejects_offline_upload_insert(
    migrated_engine: AsyncEngine,
) -> None:
    """새 행을 비활성 membership에 **거는 것**은 그대로 막혀야 한다.

    repo는 유도 단계에서 typed 409로 먼저 끊으므로 이 축은 raw INSERT로만 밟힌다 —
    가드가 INSERT 면제까지 하면 repo 우회 writer(psql, 다른 서비스)가 비활성
    membership에 행을 심을 수 있게 된다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            operation_key = _offline_operation_key("offline_jsonl")
            await _deactivate_membership(
                session,
                dataset_id=dataset_id,
                target="operation",
                operation_key=operation_key,
            )

            with pytest.raises(IntegrityError) as excinfo:
                await session.execute(
                    text(
                        """
                        INSERT INTO ops.offline_uploads (
                            provider_dataset_id, sync_scope, operation_key,
                            original_filename, storage_backend, storage_key,
                            byte_size, checksum_sha256
                        ) VALUES (
                            :dataset_id, 'dataset_wide', :operation_key,
                            'features.jsonl', 'rustfs',
                            'offline/inactive-insert/features.jsonl', 3, :checksum
                        )
                        """
                    ),
                    {
                        "dataset_id": dataset_id,
                        "operation_key": operation_key,
                        "checksum": "4" * 64,
                    },
                )

            assert is_inactive_dataset_membership_violation(excinfo.value)
        finally:
            await session.rollback()


async def test_cleanup_exemption_does_not_open_membership_rebinding(
    migrated_engine: AsyncEngine,
) -> None:
    """정리 면제가 소유권 재결박 구멍이 되면 안 된다.

    ``operation_key``만 갈아끼우는 UPDATE는 status를 안 건드리므로 "정리 write"처럼
    보인다. 면제를 소유권 검사보다 **앞에** 두면 비활성 membership에서 upload를 다른
    실행으로 조용히 옮길 수 있다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            operation_key = _offline_operation_key("offline_jsonl")
            sibling_key = f"{operation_key}.rebind_target"
            await _register_sibling_operation(
                session,
                dataset_id=dataset_id,
                operation_key=sibling_key,
                is_enabled=True,
            )
            upload = await session.execute(
                text(
                    """
                    INSERT INTO ops.offline_uploads (
                        provider_dataset_id, sync_scope, operation_key,
                        original_filename, storage_backend, storage_key,
                        byte_size, checksum_sha256
                    ) VALUES (
                        :dataset_id, 'dataset_wide', :operation_key,
                        'features.jsonl', 'rustfs',
                        'offline/rebind/features.jsonl', 3, :checksum
                    )
                    RETURNING upload_id
                    """
                ),
                {
                    "dataset_id": dataset_id,
                    "operation_key": operation_key,
                    "checksum": "5" * 64,
                },
            )
            upload_id = upload.scalar_one()

            await _deactivate_membership(
                session,
                dataset_id=dataset_id,
                target="operation",
                operation_key=operation_key,
            )

            with pytest.raises(IntegrityError) as excinfo:
                await session.execute(
                    text(
                        "UPDATE ops.offline_uploads SET operation_key = :sibling "
                        "WHERE upload_id = :upload_id"
                    ),
                    {"sibling": sibling_key, "upload_id": upload_id},
                )

            assert "ownership is immutable" in str(excinfo.value)
        finally:
            await session.rollback()


@pytest.mark.parametrize("target", ["operation", "dataset"])
async def test_offline_upload_keeps_catalog_row_deletion_restricted(
    migrated_engine: AsyncEngine,
    target: str,
) -> None:
    """정리 면제가 상위 카탈로그 행 삭제까지 열어주면 안 된다.

    upload 행이 살아 있는 동안 scope/operation 행을 지울 수 있게 되면 실행 기록이
    가리키는 대상이 사라져 조용한 고아가 생긴다 — FK ``ON DELETE RESTRICT``가 그대로
    남아 있어야 한다(운영자의 탈출 경로는 upload를 먼저 지우는 것이다).

    두 축을 모두 밟는다. 0092가 ``reject_inactive_provider_dataset``의 DELETE 면제를
    넣기 전에는 dataset 축에서 scope 행 DELETE가 FK보다 **먼저** 그 가드에 걸려
    ("inactive provider dataset cannot receive normal writes") FK가 막았는지를 볼 수
    없었다. 이제 두 축 모두 FK 이름까지 확인한다 — 면제를 과하게 넓혀 FK를 CASCADE로
    바꾸거나 가드를 되살려도 여기서 갈린다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            operation_key = _offline_operation_key("offline_jsonl")
            await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key=f"offline/restrict-{target}/features.jsonl",
                byte_size=3,
                checksum_sha256="6" * 64,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )
            await _deactivate_membership(
                session,
                dataset_id=dataset_id,
                target=target,
                operation_key=operation_key,
            )

            savepoint = await session.begin_nested()
            with pytest.raises(IntegrityError) as excinfo:
                await session.execute(
                    text(
                        """
                        DELETE FROM provider_sync.provider_dataset_operation_scopes
                         WHERE provider_dataset_id = :dataset_id
                           AND sync_scope = 'dataset_wide'
                           AND operation_key = :operation_key
                        """
                    ),
                    {"dataset_id": dataset_id, "operation_key": operation_key},
                )
            # 막은 주체가 **그 FK**임을 이름으로 못박는다. 다른 가드가 우연히 먼저
            # 걸려도 통과하는 단언이면 FK를 CASCADE로 바꿔도 초록이 뜬다.
            assert "fk_offline_uploads_exact_operation_scope" in str(excinfo.value)
            await savepoint.rollback()
        finally:
            await session.rollback()


async def test_inactive_dataset_catalog_rows_are_deletable_after_cleanup(
    migrated_engine: AsyncEngine,
) -> None:
    """자식을 지운 뒤에는 비활성 dataset의 카탈로그 행 자체가 지워져야 한다.

    0091의 ``reject_inactive_provider_dataset``은 DELETE에서도 OLD쪽 활성 검사를 돌아
    scope/operation 행 DELETE를 ``ck_provider_dataset_active_write``로 거부했다. 그래서
    운영자가 upload 행을 지워도 상위 카탈로그 행은 영원히 남았다 — 정리 경로가 offline
    upload 축에만 뚫려 있었다. 0092가 DELETE만 면제해 그 경로를 연다.

    같은 transaction 안에서 **거부 → 정리 → 성공** 순서를 밟아, 성공이 "원래부터
    자식이 없어서"가 아니라 "자식을 지웠기 때문"임을 못박는다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            operation_key = _offline_operation_key("offline_jsonl")
            upload = await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key="offline/catalog-cleanup/features.jsonl",
                byte_size=3,
                checksum_sha256="8" * 64,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )
            await _deactivate_membership(
                session,
                dataset_id=dataset_id,
                target="dataset",
                operation_key=operation_key,
            )

            delete_scope = text(
                """
                DELETE FROM provider_sync.provider_dataset_operation_scopes
                 WHERE provider_dataset_id = :dataset_id
                   AND sync_scope = 'dataset_wide'
                   AND operation_key = :operation_key
                """
            )
            parameters = {"dataset_id": dataset_id, "operation_key": operation_key}

            savepoint = await session.begin_nested()
            with pytest.raises(IntegrityError) as excinfo:
                await session.execute(delete_scope, parameters)
            assert "fk_offline_uploads_exact_operation_scope" in str(excinfo.value)
            await savepoint.rollback()

            command_id = await _reserve_delete(session, upload.upload_id)
            assert (
                await delete_offline_upload(
                    session,
                    upload_id=upload.upload_id,
                    command_id=command_id,
                )
                is not None
            )

            assert (await session.execute(delete_scope, parameters)).rowcount == 1
            assert (
                await session.execute(
                    text(
                        """
                        DELETE FROM provider_sync.provider_dataset_operations
                         WHERE provider_dataset_id = :dataset_id
                           AND operation_key = :operation_key
                        """
                    ),
                    parameters,
                )
            ).rowcount == 1
        finally:
            await session.rollback()


class _DeleteOnlyStore:
    """라우터 DELETE 경로가 부르는 객체 저장소 최소 stub."""

    bucket = "kor-travel-map-uploads"

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_object(self, storage_key: str) -> None:
        self.deleted.append(storage_key)


async def test_router_delete_records_managed_file_audit_for_inactive_dataset(
    migrated_engine: AsyncEngine,
) -> None:
    """비활성 dataset의 라우터 DELETE는 200이고 registry 감사 기록이 실제로 남는다.

    라우터는 registry hook을 ``file_registry.registry_guard``(``except Exception``)로
    감싼다. 그래서 hook이 DB에 거부당해도 응답은 200이고 로그 한 줄만 남는다 — 실측:
    0091 head에서 비활성 dataset의 ``ops.managed_files`` write는 INSERT/UPDATE/DELETE
    전부 ``ck_provider_dataset_active_write``로 거부됐다. 응답 코드만 보는 회귀로는
    그 조용한 감사 공백을 볼 수 없으므로, 여기서는 **registry 행의 최종 상태**를
    DB에서 직접 읽는다.

    ``clean_offline_upload_tables``가 ``ops.managed_files``는 건드리지 않으므로 시드와
    registry 행을 finally에서 직접 지운다(공유 ``migrated_engine`` 오염 방지).
    """

    from kortravelmap.api.app import create_app
    from kortravelmap.api.db import get_session
    from kortravelmap.api.settings import ApiSettings

    storage_key = "offline/router-delete/features.jsonl"
    checksum = "9" * 64
    store = _DeleteOnlyStore()

    async with AsyncSession(migrated_engine) as session, session.begin():
        dataset_id = await _offline_provider_dataset_id(session)
        upload = await create_offline_upload(
            session,
            provider_dataset_id=dataset_id,
            sync_scope="dataset_wide",
            original_filename="features.jsonl",
            storage_backend="s3",
            storage_key=storage_key,
            byte_size=3,
            checksum_sha256=checksum,
            detected_format="jsonl",
            detected_encoding="utf-8",
            created_by="pytest",
        )
        # 업로드 시점(=dataset 활성)에 registry가 남기는 행. 라우터 DELETE는 이 행을
        # 다시 upsert한 뒤 deleted로 내린다.
        await file_registry.register_file(
            session,
            storage_backend="s3",
            location=MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
            path=storage_key,
            kind="upload",
            provider_dataset_id=dataset_id,
            byte_size=3,
            checksum_sha256=checksum,
            upload_id=upload.upload_id,
            actor="pytest",
        )
        await _deactivate_membership(
            session,
            dataset_id=dataset_id,
            target="dataset",
            operation_key=_offline_operation_key("offline_jsonl"),
        )

    try:
        app = create_app(
            ApiSettings(
                _env_file=None,
                debug_routes_enabled=False,
                features_routes_enabled=False,
                admin_routes_enabled=True,
                ops_routes_enabled=False,
                api_call_log_enabled=False,
                prometheus_metrics_enabled=False,
                admin_proxy_secret=None,
                admin_destructive_enabled=True,
            )
        )

        async def _session() -> AsyncIterator[AsyncSession]:
            async with AsyncSession(migrated_engine, expire_on_commit=False) as api_session:
                yield api_session

        app.dependency_overrides[get_session] = _session
        app.state.offline_upload_store = store

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://offline-upload-test"
        ) as client:
            response = await client.request(
                "DELETE",
                f"/v1/admin/offline-uploads/{upload.upload_id}",
                headers={"Idempotency-Key": str(uuid4())},
            )

        assert response.status_code == 200, response.text
        assert store.deleted == [storage_key]

        async with AsyncSession(migrated_engine) as session:
            registry_row = (
                await session.execute(
                    text(
                        """
                        SELECT file_id, status, deleted_at
                          FROM ops.managed_files
                         WHERE storage_backend = 's3'
                           AND location = :location
                           AND path = :path
                        """
                    ),
                    {
                        "location": MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
                        "path": storage_key,
                    },
                )
            ).one_or_none()
            assert registry_row is not None, "registry 행이 통째로 사라졌다"
            assert registry_row.status == "deleted"
            assert registry_row.deleted_at is not None
            event_kinds = [
                row.event_kind
                for row in (
                    await session.execute(
                        text(
                            "SELECT event_kind FROM ops.managed_file_events "
                            "WHERE file_id = :file_id"
                        ),
                        {"file_id": registry_row.file_id},
                    )
                ).all()
            ]
            assert "deleted" in event_kinds, event_kinds
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(
                text(
                    """
                    DELETE FROM ops.managed_file_events
                     WHERE file_id IN (
                        SELECT file_id FROM ops.managed_files
                         WHERE storage_backend = 's3'
                           AND location = :location
                           AND path = :path
                     )
                    """
                ),
                {
                    "location": MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
                    "path": storage_key,
                },
            )
            await session.execute(
                text(
                    "DELETE FROM ops.managed_files "
                    "WHERE storage_backend = 's3' AND location = :location AND path = :path"
                ),
                {
                    "location": MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
                    "path": storage_key,
                },
            )
            await session.execute(
                text(
                    "UPDATE provider_sync.provider_datasets SET is_active = true "
                    "WHERE provider_dataset_id = :dataset_id"
                ),
                {"dataset_id": dataset_id},
            )


async def test_managed_file_owner_attaches_once_and_then_never_moves(
    migrated_engine: AsyncEngine,
) -> None:
    """``ops.managed_files``의 소유권 가드는 NULL→값만 허용하고 나머지는 거부한다.

    alembic 0092 ``reject_managed_file_dataset_rebinding``의 첫 판은
    ``OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id``만 보아
    **NULL → 값**까지 "ownership is immutable"로 거부했다. 그런데 같은 브랜치의
    ``file_registry._UPSERT_SQL``은 재등록 시 소유자를 붙이는 ``CASE``를 명시적으로
    갖고 있고, ``file_registry_scan.scan_s3_location``은 소유 ``ops.offline_uploads``
    행이 아직 없는 객체를 ``provider_dataset_id=NULL``로 먼저 등록한 뒤
    ``mark_orphan('zombie_object')``까지 보낸다. 그래서 DB 가드가 writer의 정상
    경로를 막았다 — 게다가 ``scan_s3_location``은 이 호출을 ``registry_guard``로
    감싸지 않으므로 예외가 asset 밖으로 나가 그 pass의 등록분이 통째로 롤백된다.

    세 전이를 한 테스트에서 함께 못박는다. 하나만 두면 "NULL→값을 열었다"가
    "아무 전이나 열었다"로 번져도 red가 나지 않는다:

    a. NULL → 값 (최초 귀속) = 성공. 행이 그 dataset에 실제로 귀속돼야 한다.
    b. 값 → 다른 값 (재귀속)  = 거부.
    c. 값 → NULL (귀속 해제)  = 거부. ``violation-fixtures-v1.sql``의
       ``inactive_dataset_managed_file_owner_clear``가 계약 쪽에서 못박는 것이 c다.

    ``clean_offline_upload_tables``가 ``ops.managed_files``는 건드리지 않으므로
    registry 행을 finally에서 직접 지운다(공유 ``migrated_engine`` 오염 방지).
    """

    path = "offline/owner-attach/features.jsonl"

    async with AsyncSession(migrated_engine) as session, session.begin():
        dataset_id = await _offline_provider_dataset_id(session)
        sibling_dataset_id = await _offline_provider_dataset_id(
            session, dataset_key="offline_owner_attach_sibling"
        )
        assert sibling_dataset_id != dataset_id

    try:
        # (a) scan이 소유자를 못 찾은 pass — NULL로 등록되고 zombie로 내려간다.
        async with AsyncSession(migrated_engine) as session, session.begin():
            unowned = await file_registry.register_file(
                session,
                storage_backend="s3",
                location=MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
                path=path,
                kind="upload",
                registered_by="scan",
                provider_dataset_id=None,
                actor="scan:test",
            )
            assert unowned.provider_dataset_id is None
            assert (
                await file_registry.mark_orphan(
                    session,
                    file_id=unowned.file_id,
                    reason="zombie_object",
                    actor="scan:test",
                )
                is True
            )

        # 소유 upload 행이 생긴 뒤의 다음 pass — 같은 (backend, location, path)를
        # 소유자와 함께 재등록한다. 이것이 첫 판에서 죽던 write다.
        async with AsyncSession(migrated_engine) as session, session.begin():
            attached = await file_registry.register_file(
                session,
                storage_backend="s3",
                location=MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
                path=path,
                kind="upload",
                registered_by="scan",
                provider_dataset_id=dataset_id,
                actor="scan:test",
            )
        assert attached.file_id == unowned.file_id, "재등록이 새 행을 만들었다"
        assert attached.provider_dataset_id == dataset_id
        assert attached.status == "active"

        # 커밋된 상태를 다시 읽는다 — 위 단언은 RETURNING 값이라 트리거가 뒤에서
        # 되돌렸다면 그것만으로는 드러나지 않는다.
        async with AsyncSession(migrated_engine) as session:
            stored = (
                await session.execute(
                    text(
                        "SELECT provider_dataset_id, status FROM ops.managed_files "
                        "WHERE file_id = :file_id"
                    ),
                    {"file_id": attached.file_id},
                )
            ).one()
        assert stored.provider_dataset_id == dataset_id
        assert stored.status == "active"

        # (b) 값 → 다른 값 = 재귀속, (c) 값 → NULL = 귀속 해제. 둘 다 계속 거부돼야 한다.
        # ``provider_name``을 함께 맞춰 주는 이유: ``ck_managed_files_owner``(head 이름
        # ``ck_managed_files_owner_v2``)가 dataset id와 provider name의 배타를 요구해서,
        # 안 맞추면 소유권 트리거가 아니라 그 CHECK가 먼저 터진다. 그러면 트리거를
        # 통째로 꺼도 테스트가 계속 green이 되는 공허한 단언이 된다(변이 M3로 실증).
        for label, new_owner, new_provider_name in (
            ("rebind", sibling_dataset_id, None),
            ("clear", None, "x"),
        ):
            async with AsyncSession(migrated_engine) as session:
                with pytest.raises(IntegrityError) as rejected:
                    async with session.begin():
                        await session.execute(
                            text(
                                "UPDATE ops.managed_files "
                                "SET provider_dataset_id = :owner, "
                                "    provider_name = :provider_name "
                                "WHERE file_id = :file_id"
                            ),
                            {
                                "owner": new_owner,
                                "provider_name": new_provider_name,
                                "file_id": attached.file_id,
                            },
                        )
            # 문자열이 아니라 driver metadata로 좁힌다 — 같은 예외 타입에 실려 오는
            # 다른 CHECK 위반을 "거부됐으니 통과"로 세면 공허한 단언이 된다.
            sqlstate, constraint_name = _driver_constraint_identity(rejected.value)
            assert (sqlstate, constraint_name) == (
                "23514",
                "ck_provider_dataset_ownership_immutable",
            ), f"{label}: {sqlstate} / {constraint_name} — {rejected.value}"

        async with AsyncSession(migrated_engine) as session:
            still = (
                await session.execute(
                    text(
                        "SELECT provider_dataset_id FROM ops.managed_files "
                        "WHERE file_id = :file_id"
                    ),
                    {"file_id": attached.file_id},
                )
            ).one()
        assert still.provider_dataset_id == dataset_id
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(
                text(
                    """
                    DELETE FROM ops.managed_file_events
                     WHERE file_id IN (
                        SELECT file_id FROM ops.managed_files
                         WHERE storage_backend = 's3'
                           AND location = :location
                           AND path = :path
                     )
                    """
                ),
                {"location": MANAGED_FILE_LOCATION_OFFLINE_UPLOADS, "path": path},
            )
            await session.execute(
                text(
                    "DELETE FROM ops.managed_files "
                    "WHERE storage_backend = 's3' AND location = :location AND path = :path"
                ),
                {"location": MANAGED_FILE_LOCATION_OFFLINE_UPLOADS, "path": path},
            )


# ---------------------------------------------------------------------------
# T-VN-33 후속(alembic 0092) — 멱등 UNIQUE가 identity triple을 따른다.
#
# 0090이 만든 ``uq_offline_uploads_dataset_scope_checksum``은 3열이었고, 0091이 scope
# PK를 pair→triple로 올리면서 같은 (dataset, scope)에 형제 refresh operation을
# 등록하는 것이 정상 write가 됐다. 그 사이에서 재현되는 상태가 아래 두 테스트다.
# ---------------------------------------------------------------------------


async def test_same_checksum_can_rebind_after_operation_rotation(
    migrated_engine: AsyncEngine,
) -> None:
    """operation을 교체하면 같은 파일을 새 operation으로 다시 올릴 수 있어야 한다.

    운영자 시나리오: operation A로 파일을 올린 뒤 A를 disable하고 후속 operation B를
    enable한다(유도는 활성 하나만 세므로 B로 풀린다). 멱등 키가 3열이면 **이미 없어진
    A에 결박된 옛 행** 때문에 UNIQUE 위반이 나고, 운영자는 그 파일을 영영 다시 올릴 수
    없다. 4열이면 두 행이 각자의 operation을 들고 공존한다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            first_key = _offline_operation_key("offline_jsonl")
            second_key = f"{first_key}.rotated"
            checksum = "7" * 64

            first = await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key="offline/rotation/first.jsonl",
                byte_size=3,
                checksum_sha256=checksum,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )
            assert first.operation_key == first_key

            await _register_sibling_operation(
                session,
                dataset_id=dataset_id,
                operation_key=second_key,
                is_enabled=True,
            )
            await _deactivate_membership(
                session,
                dataset_id=dataset_id,
                target="operation",
                operation_key=first_key,
            )

            second = await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key="offline/rotation/second.jsonl",
                byte_size=3,
                checksum_sha256=checksum,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )

            assert second.operation_key == second_key
            assert second.upload_id != first.upload_id
            assert await _upload_count(session, dataset_id) == 2
        finally:
            await session.rollback()


async def test_get_offline_upload_by_checksum_reads_the_exact_triple(
    migrated_engine: AsyncEngine,
) -> None:
    """중복 조회는 형제 operation 행이 있어도 **결박된 그 행**을 집어야 한다.

    ``operation_key`` 술어를 빼면 4열 UNIQUE가 허용하는 형제 행까지 걸려
    ``one_or_none()``이 터지거나 409가 엉뚱한 upload를 가리킨다.
    """

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        try:
            dataset_id = await _offline_provider_dataset_id(session)
            first_key = _offline_operation_key("offline_jsonl")
            second_key = f"{first_key}.rotated"
            checksum = "8" * 64

            first = await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key="offline/exact/first.jsonl",
                byte_size=3,
                checksum_sha256=checksum,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )
            await _register_sibling_operation(
                session,
                dataset_id=dataset_id,
                operation_key=second_key,
                is_enabled=True,
            )
            await _deactivate_membership(
                session,
                dataset_id=dataset_id,
                target="operation",
                operation_key=first_key,
            )
            second = await create_offline_upload(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                original_filename="features.jsonl",
                storage_backend="rustfs",
                storage_key="offline/exact/second.jsonl",
                byte_size=3,
                checksum_sha256=checksum,
                detected_format="jsonl",
                detected_encoding="utf-8",
                created_by="pytest",
            )

            # 라우터가 중복 409를 만들 때 쓰는 유도값 = 지금 활성인 operation.
            resolved = await resolve_offline_upload_operation_key(
                session,
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
            )
            assert resolved == second_key

            for expected, operation_key in ((first, first_key), (second, second_key)):
                found = await get_offline_upload_by_checksum(
                    session,
                    provider_dataset_id=dataset_id,
                    sync_scope="dataset_wide",
                    operation_key=operation_key,
                    checksum_sha256=checksum,
                )
                assert found is not None
                assert found.upload_id == expected.upload_id
                assert found.operation_key == operation_key
        finally:
            await session.rollback()


async def _register_sibling_operation(
    session: AsyncSession,
    *,
    dataset_id: int,
    operation_key: str,
    is_enabled: bool,
) -> None:
    """같은 (dataset, dataset_wide) scope에 형제 refresh operation을 등록한다.

    scope PK가 triple이라 스키마가 허용하는 정상 write다(T-VN-33 migration contract
    테스트가 같은 방식을 쓴다). 호출자는 트랜잭션을 rollback해 카탈로그를 되돌린다 —
    실행 행(``ops.offline_uploads``)이 먼저 사라지고 그 다음 scope·operation 행이
    사라지는 순서를 rollback이 그대로 보장한다.
    """

    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operations (
                provider_dataset_id, operation_key, operation_kind, is_enabled, config
            ) VALUES (
                :dataset_id, :operation_key, 'refresh', :is_enabled, '{}'::jsonb
            )
            """
        ),
        {
            "dataset_id": dataset_id,
            "operation_key": operation_key,
            "is_enabled": is_enabled,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key, operation_kind
            ) VALUES (:dataset_id, 'dataset_wide', :operation_key, 'refresh')
            """
        ),
        {"dataset_id": dataset_id, "operation_key": operation_key},
    )


async def _upload_count(session: AsyncSession, dataset_id: int) -> int:
    return int(
        await session.scalar(
            text(
                "SELECT count(*) FROM ops.offline_uploads "
                "WHERE provider_dataset_id = :dataset_id"
            ),
            {"dataset_id": dataset_id},
        )
        or 0
    )


async def _reserve_delete(session: AsyncSession, upload_id: str) -> int:
    command_id = await session.scalar(
        text(
            """
            INSERT INTO ops.domain_commands (
              actor, operation, idempotency_key, request_fingerprint
            ) VALUES (
              'integration:offline-delete',
              'admin.offline-upload.delete',
              x_extension.gen_random_uuid(),
              repeat('a', 64)
            )
            RETURNING command_id
            """
        )
    )
    assert command_id is not None
    reserved = await reserve_offline_upload_delete(
        session,
        upload_id=upload_id,
        command_id=command_id,
    )
    assert reserved is not None
    assert reserved.status == "deleting"
    assert reserved.delete_command_id == command_id
    return command_id


async def _create_upload(
    engine: AsyncEngine,
    *,
    body: bytes,
    storage_key: str,
    upload_id: str | None = None,
    checksum_sha256: str | None = None,
    original_filename: str = "features.jsonl",
    detected_format: str = "jsonl",
    dataset_key: str = "offline_jsonl",
) -> str:
    async with AsyncSession(engine) as session, session.begin():
        upload = await create_offline_upload(
            session,
            upload_id=upload_id,
            provider_dataset_id=await _offline_provider_dataset_id(
                session, dataset_key=dataset_key
            ),
            sync_scope="dataset_wide",
            original_filename=original_filename,
            storage_backend="rustfs",
            storage_key=storage_key,
            byte_size=len(body),
            checksum_sha256=checksum_sha256 or hashlib.sha256(body).hexdigest(),
            detected_format=detected_format,
            detected_encoding="utf-8",
            created_by="pytest",
        )
        return upload.upload_id


async def _truncate(engine: AsyncEngine) -> None:
    async with AsyncSession(engine) as session, session.begin():
        await truncate_committed_test_rows(session, _TRUNCATE_SQL)


def _offline_operation_key(dataset_key: str) -> str:
    """fixture dataset이 소유하는 유일한 canonical operation key."""

    return f"offline_fixture_{dataset_key}_refresh"


async def _offline_membership(
    session: AsyncSession,
    *,
    dataset_key: str = "offline_jsonl",
) -> ImportJobDatasetTarget:
    """T-VN-33 canonical membership — dataset+scope+operation triple.

    ``ops.import_job_datasets``가 ``provider_dataset_operation_scopes``를 FK로
    잡으므로 fixture pair도 catalog에 먼저 있어야 한다.
    """

    return ImportJobDatasetTarget(
        provider_dataset_id=await _offline_provider_dataset_id(
            session, dataset_key=dataset_key
        ),
        sync_scope="dataset_wide",
        operation_key=_offline_operation_key(dataset_key),
    )


async def _offline_provider_dataset_id(
    session: AsyncSession,
    *,
    dataset_key: str = "offline_jsonl",
) -> int:
    dataset_id = int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    ) VALUES (
                        'offline-test-provider', :dataset_key,
                        'offline integration fixture', 'manual', true,
                        CAST(:capabilities AS jsonb)
                    )
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                    SET is_active = true
                    RETURNING provider_dataset_id
                    """
                ),
                {
                    "dataset_key": dataset_key,
                    "capabilities": json.dumps(
                        {
                            "schema_version": 1,
                            "produces": ["place"],
                            "extensions": {},
                        }
                    ),
                },
            )
        ).scalar_one()
    )
    operation_key = _offline_operation_key(dataset_key)
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operations (
                provider_dataset_id, operation_key, operation_kind, is_enabled, config
            ) VALUES (
                :provider_dataset_id, :operation_key, 'refresh', true, '{}'::jsonb
            )
            ON CONFLICT (provider_dataset_id, operation_key, operation_kind) DO UPDATE
            SET is_enabled = true
            """
        ),
        {"provider_dataset_id": dataset_id, "operation_key": operation_key},
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key, operation_kind
            ) VALUES (
                :provider_dataset_id, 'dataset_wide', :operation_key, 'refresh'
            )
            ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO UPDATE
            SET operation_kind = EXCLUDED.operation_kind
            """
        ),
        {"provider_dataset_id": dataset_id, "operation_key": operation_key},
    )
    return dataset_id


async def _fake_address_resolver(address: Address) -> Address | None:
    return Address(
        road=address.road,
        legal=address.legal,
        bjd_code="1114010100",
        sigungu_code="11140",
        sido_code="11",
    )


def _bundle(source_id: str) -> FeatureBundle:
    raw_payload = {
        "source_id": source_id,
        "name": "오프라인 통합 테스트 장소",
        "lon": "126.9780",
        "lat": "37.5665",
    }
    payload_hash = make_payload_hash(raw_payload)
    source_record_key = make_source_record_key(
        provider="offline-test-provider",
        dataset_key="offline_jsonl",
        source_entity_type="offline_feature_bundle",
        source_entity_id=source_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code="1111010100",
        kind="place",
        category="02020101",
        source_type="offline_test",
        source_natural_key=source_id,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name="오프라인 통합 테스트 장소",
        coord=Coordinate(lon=Decimal("126.9780"), lat=Decimal("37.5665")),
        category="02020101",
        marker_icon="marker",
        marker_color="P-01",
        detail=PlaceDetail(feature_id=feature_id, place_kind="offline_test"),
    )
    source_record = SourceRecord(
        provider="offline-test-provider",
        dataset_key="offline_jsonl",
        source_entity_type="offline_feature_bundle",
        source_entity_id=source_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_payload,
        fetched_at=_FETCHED_AT,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="offline_upload",
        confidence=100,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )
