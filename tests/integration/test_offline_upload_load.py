"""offline upload load job 통합 테스트."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

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
from kortravelmap.infra.jobs_repo import start_import_job
from kortravelmap.infra.offline_upload_repo import (
    OfflineUploadStatusConflict,
    create_offline_upload,
    delete_offline_upload,
    finish_offline_upload_load,
    get_offline_upload,
    get_offline_upload_by_checksum,
    list_offline_uploads,
    mark_offline_upload_loading,
    reserve_offline_upload_load,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    create_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
)
from kortravelmap.infra.pipeline_cancellation_types import PipelineCancellationConflict

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
        job = await start_import_job(
            session,
            kind="offline_upload_load",
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
        job = await start_import_job(
            session,
            kind="offline_upload_load",
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
        job = await start_import_job(
            session,
            kind="offline_upload_load",
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
                    "SELECT f.name, sr.source_entity_id, ou.status AS upload_status "
                    "FROM feature.features AS f "
                    "JOIN provider_sync.source_links AS sl "
                    "  ON sl.feature_id = f.feature_id "
                    "JOIN provider_sync.source_entities AS se "
                    "  ON se.source_entity_key = sl.source_entity_key "
                    "JOIN provider_sync.source_records AS sr "
                    "  ON sr.source_record_key = se.current_source_record_key "
                    "JOIN ops.offline_uploads AS ou ON ou.upload_id = :upload_id "
                    "WHERE sr.source_entity_id = :source_entity_id"
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

        job = await start_import_job(session, kind="offline_upload_load")
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
                provider="offline-test-provider",
                dataset_key="offline_jsonl",
                sync_scope="default",
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
            provider="offline-test-provider",
            dataset_key="offline_jsonl",
            sync_scope="default",
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
            provider="offline-test-provider",
            dataset_key="offline_jsonl",
            limit=1,
        )
        assert page1.next_cursor is not None
        assert page1.items[0].upload_id == second_id

        page2 = await list_offline_uploads(
            session,
            provider="offline-test-provider",
            dataset_key="offline_jsonl",
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
        deleted = await delete_offline_upload(session, upload_id=upload_id)
    assert deleted is not None
    assert deleted.upload_id == upload_id
    assert deleted.checksum_sha256 == checksum

    async with AsyncSession(migrated_engine) as session:
        assert await get_offline_upload(session, upload_id) is None
        assert await delete_offline_upload(session, upload_id=upload_id) is None

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
        job = await start_import_job(
            session,
            kind="offline_upload_load",
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
            await delete_offline_upload(session, upload_id=upload_id)

    async with AsyncSession(migrated_engine) as session, session.begin():
        finished = await finish_offline_upload_load(
            session,
            upload_id=upload_id,
            status="load_failed",
        )
        assert finished is not None

    async with AsyncSession(migrated_engine) as session, session.begin():
        deleted = await delete_offline_upload(session, upload_id=upload_id)
    assert deleted is not None
    assert deleted.status == "load_failed"

    # 연관 import job row는 audit 기록으로 남는다.
    async with AsyncSession(migrated_engine) as session:
        job_row = (
            await session.execute(
                text("SELECT job_id FROM ops.import_jobs WHERE job_id = :job_id"),
                {"job_id": job.job_id},
            )
        ).one_or_none()
    assert job_row is not None


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
            provider="offline-test-provider",
            dataset_key=dataset_key,
            sync_scope="default",
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
        await session.execute(text(_TRUNCATE_SQL))


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
        raw_name=feature.name,
        raw_longitude=Decimal("126.9780"),
        raw_latitude=Decimal("37.5665"),
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
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )
