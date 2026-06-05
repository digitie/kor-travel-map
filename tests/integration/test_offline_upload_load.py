"""offline upload load job 통합 테스트."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map.client import AsyncKrtourMapClient
from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.dto import (
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
from krtour.map.infra.jobs_repo import start_import_job
from krtour.map.infra.offline_upload_repo import (
    OfflineUploadStateConflict,
    create_offline_upload,
    finish_offline_upload_load,
    get_offline_upload_by_checksum,
    list_offline_uploads,
    mark_offline_upload_loading,
    reserve_offline_upload_load,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED_AT = datetime(2026, 6, 3, 14, 0, tzinfo=_KST)
_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_records, "
    "provider_sync.source_links, ops.import_jobs, ops.offline_uploads "
    "RESTART IDENTITY CASCADE"
)


class _MemoryStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    async def read_bytes(self, storage_key: str) -> bytes:
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

    client = AsyncKrtourMapClient(migrated_engine)
    result = await client.run_offline_upload_load_job(
        upload_id,
        store=_MemoryStore({storage_key: body}),
        dagster_run_id="dagster-run-offline-success",
    )

    assert result.acquired is True
    assert result.error_message is None
    assert result.job is not None
    assert result.job.state == "done"
    assert result.load is not None
    assert result.load.bundles_total == 1
    assert result.upload is not None
    assert result.upload.state == "loaded"

    async with AsyncSession(migrated_engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT f.feature_id, ou.state AS upload_state, ij.state AS job_state "
                    "FROM feature.features AS f "
                    "JOIN ops.offline_uploads AS ou ON ou.upload_id = :upload_id "
                    "JOIN ops.import_jobs AS ij ON ij.job_id = ou.load_job_id "
                    "WHERE f.feature_id = :feature_id"
                ),
                {"upload_id": upload_id, "feature_id": bundle.feature.feature_id},
            )
        ).one()

    assert row.feature_id == bundle.feature.feature_id
    assert row.upload_state == "loaded"
    assert row.job_state == "done"


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
        assert loading.state == "loading"
        assert loading.load_job_id == job.job_id

    client = AsyncKrtourMapClient(migrated_engine)
    result = await client.run_offline_upload_load_job(
        upload_id,
        store=_MemoryStore({storage_key: body}),
        dagster_run_id="dagster-run-preclaimed",
    )

    assert result.acquired is True
    assert result.error_message is None
    assert result.job is not None
    assert result.job.job_id == job.job_id
    assert result.job.state == "done"
    assert result.job.payload["dagster_run_id"] == "dagster-run-preclaimed"
    assert result.upload is not None
    assert result.upload.state == "loaded"


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

    client = AsyncKrtourMapClient(migrated_engine)
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
    assert validation.upload.state == "validated"
    assert validation.job is not None
    assert validation.job.state == "done"

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
    assert loaded.upload.state == "loaded"

    async with AsyncSession(migrated_engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT f.name, sr.source_entity_id, ou.state AS upload_state "
                    "FROM feature.features AS f "
                    "JOIN provider_sync.source_links AS sl "
                    "  ON sl.feature_id = f.feature_id "
                    "JOIN provider_sync.source_records AS sr "
                    "  ON sr.source_record_key = sl.source_record_key "
                    "JOIN ops.offline_uploads AS ou ON ou.upload_id = :upload_id "
                    "WHERE sr.source_entity_id = :source_entity_id"
                ),
                {"upload_id": upload_id, "source_entity_id": "csv-live-001"},
            )
        ).one()

    assert row.name == "오프라인 CSV 통합 장소"
    assert row.source_entity_id == "csv-live-001"
    assert row.upload_state == "loaded"


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

    client = AsyncKrtourMapClient(migrated_engine)
    result = await client.run_offline_upload_load_job(
        upload_id,
        store=_MemoryStore({storage_key: body}),
        dagster_run_id="dagster-run-offline-failed",
    )

    assert result.acquired is True
    assert result.error_message
    assert "checksum mismatch" in result.error_message
    assert result.job is not None
    assert result.job.state == "failed"
    assert result.upload is not None
    assert result.upload.state == "load_failed"

    async with AsyncSession(migrated_engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT ou.state AS upload_state, ij.state AS job_state, "
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

    assert row.upload_state == "load_failed"
    assert row.job_state == "failed"
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
        with pytest.raises(OfflineUploadStateConflict) as finish_conflict:
            await finish_offline_upload_load(
                session,
                upload_id=upload_id,
                state="loaded",
            )
        assert finish_conflict.value.current_state == "uploaded"
        assert finish_conflict.value.allowed_states == frozenset({"loading"})

        job = await start_import_job(session, kind="offline_upload_load")
        loading = await mark_offline_upload_loading(
            session,
            upload_id=upload_id,
            load_job_id=job.job_id,
        )
        assert loading is not None
        assert loading.state == "loading"

        loaded = await finish_offline_upload_load(
            session,
            upload_id=upload_id,
            state="loaded",
        )
        assert loaded is not None
        assert loaded.state == "loaded"

        with pytest.raises(OfflineUploadStateConflict) as reload_conflict:
            await mark_offline_upload_loading(
                session,
                upload_id=upload_id,
                load_job_id=job.job_id,
            )
        assert reload_conflict.value.current_state == "loaded"
        assert reload_conflict.value.target_state == "loading"


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
        assert loading.state == "loading"
        assert loading.load_job_id is not None

    async with AsyncSession(migrated_engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT ou.state AS upload_state, ou.load_job_id, "
                    "ij.state AS job_state, ij.kind, ij.source_checksum "
                    "FROM ops.offline_uploads AS ou "
                    "JOIN ops.import_jobs AS ij ON ij.job_id = ou.load_job_id "
                    "WHERE ou.upload_id = :upload_id"
                ),
                {"upload_id": upload_id},
            )
        ).one()

    assert row.upload_state == "loading"
    assert row.job_state == "running"
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
