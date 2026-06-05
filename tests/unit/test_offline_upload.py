"""offline upload parser 단위 테스트."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

import krtour.map.offline_upload as offline_upload_mod
from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.dto import (
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from krtour.map.infra.feature_repo import FeatureLoadResult
from krtour.map.infra.jobs_repo import ImportJob
from krtour.map.infra.offline_upload_repo import OfflineUpload
from krtour.map.offline_upload import (
    parse_offline_feature_bundles,
    preview_offline_tabular_upload,
    run_offline_upload_load_job,
    run_offline_upload_validation_job,
    validate_offline_tabular_upload,
)

pytestmark = pytest.mark.unit

_KST = timezone(timedelta(hours=9))
_FETCHED_AT = datetime(2026, 6, 3, 14, 0, tzinfo=_KST)


def test_parse_offline_feature_bundles_jsonl() -> None:
    bundle = _bundle("jsonl-001")
    payload = bundle.model_dump_json().encode("utf-8")

    parsed = parse_offline_feature_bundles(
        payload,
        detected_format="jsonl",
        detected_encoding="utf-8",
        original_filename="features.jsonl",
    )

    assert len(parsed) == 1
    assert parsed[0].feature.feature_id == bundle.feature.feature_id
    assert parsed[0].source_link.source_record_key == (bundle.source_record.source_record_key)


def test_parse_offline_feature_bundles_json_items() -> None:
    bundle = _bundle("json-001")
    payload = {"items": [bundle.model_dump(mode="json")]}

    parsed = parse_offline_feature_bundles(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        original_filename="features.json",
    )

    assert parsed[0].feature.name == "오프라인 테스트 장소"


def test_parse_offline_feature_bundles_csv_with_column_mapping() -> None:
    body = (
        "name,lon,lat,address,source_id\n"
        "오프라인 CSV 장소,126.9780,37.5665,서울특별시 중구 세종대로,csv-001\n"
    ).encode()

    parsed = parse_offline_feature_bundles(
        body,
        detected_format="csv",
        original_filename="features.csv",
        provider="offline-test-provider",
        dataset_key="offline_csv",
        column_mapping={
            "name": "name",
            "lon": "lon",
            "lat": "lat",
            "address": "address",
            "source_id": "source_id",
        },
    )

    assert len(parsed) == 1
    assert parsed[0].feature.name == "오프라인 CSV 장소"
    assert parsed[0].feature.coord == Coordinate(lon=Decimal("126.9780"), lat=Decimal("37.5665"))
    assert parsed[0].source_record.source_entity_id == "csv-001"
    assert parsed[0].source_record.raw_address == "서울특별시 중구 세종대로"


def test_preview_offline_tabular_upload_returns_headers_and_sample_rows() -> None:
    body = b"name\tlon\tlat\nA\t126.9\t37.5\nB\t127.0\t37.6\n"

    preview = preview_offline_tabular_upload(
        body,
        detected_format="tsv",
        original_filename="features.tsv",
        sample_size=1,
    )

    assert preview.parsed_format == "tsv"
    assert preview.delimiter == "\t"
    assert preview.headers == ("name", "lon", "lat")
    assert preview.rows_total == 2
    assert preview.rows_sampled == 1
    assert preview.sample_rows[0]["name"] == "A"


def test_validate_offline_tabular_upload_reports_mapping_errors() -> None:
    body = b"name,lon,lat\nA,126.9,37.5\n"

    result = validate_offline_tabular_upload(
        _csv_upload(body),
        body,
        column_mapping={"name": "name", "lon": "x", "lat": "lat"},
    )

    assert result.has_errors is True
    assert result.valid_rows == 0
    assert result.error_rows == 1
    assert {issue.code for issue in result.issues} == {
        "missing_required_column",
        "dto_validation_failed",
    }


@pytest.mark.asyncio
async def test_run_offline_upload_validation_job_persists_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        "name,lon,lat,address,source_id,bjd_code\n"
        "오프라인 CSV 장소,126.9780,37.5665,서울특별시 중구 세종대로,csv-001,1114010300\n"
    ).encode()
    upload = _csv_upload(body)
    calls = _FakeOfflineUploadCalls(upload)
    _patch_offline_job_repos(monkeypatch, calls)

    result = await run_offline_upload_validation_job(
        object(),
        upload.upload_id,
        store=_MemoryStore({upload.storage_key: body}),
        column_mapping={
            "name": "name",
            "lon": "lon",
            "lat": "lat",
            "address": "address",
            "source_id": "source_id",
            "bjd_code": "bjd_code",
        },
        operator="pytest",
    )

    assert result.has_errors is False
    assert result.upload.state == "validated"
    assert result.job is not None
    assert result.job.state == "done"
    assert result.valid_rows == 1
    assert result.error_rows == 0
    assert calls.validation_state == "validated"
    assert calls.updated_payloads[-1]["valid_rows"] == 1
    assert calls.heartbeats == ["read_object", "validate_tabular_rows"]


@pytest.mark.asyncio
async def test_run_offline_upload_validation_job_records_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"name,lon,lat\nA,126.9,37.5\n"
    upload = _csv_upload(body)
    calls = _FakeOfflineUploadCalls(upload)
    _patch_offline_job_repos(monkeypatch, calls)

    result = await run_offline_upload_validation_job(
        object(),
        upload.upload_id,
        store=_MemoryStore({upload.storage_key: body}),
        column_mapping={"name": "name", "lon": "missing", "lat": "lat"},
    )

    assert result.has_errors is True
    assert result.upload.state == "validation_failed"
    assert result.job is not None
    assert result.job.state == "failed"
    assert result.error_rows == 1
    assert calls.validation_state == "validation_failed"
    assert calls.finished_jobs[-1].error_message == "offline upload validation failed: 1 rows"


@pytest.mark.asyncio
async def test_run_offline_upload_load_job_uses_validation_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        "name,lon,lat,address,source_id,bjd_code\n"
        "오프라인 CSV 장소,126.9780,37.5665,서울특별시 중구 세종대로,csv-001,1114010300\n"
    ).encode()
    upload = _csv_upload(body, state="validated", validation_job_id="job-validation")
    calls = _FakeOfflineUploadCalls(upload)
    calls.validation_payload = {
        "column_mapping": {
            "name": "name",
            "lon": "lon",
            "lat": "lat",
            "address": "address",
            "source_id": "source_id",
            "bjd_code": "bjd_code",
        }
    }
    loaded_bundle_names: list[str] = []
    _patch_offline_job_repos(monkeypatch, calls)

    async def _load_bundles(_session: object, bundles: list[FeatureBundle]) -> FeatureLoadResult:
        loaded_bundle_names.extend(bundle.feature.name for bundle in bundles)
        return FeatureLoadResult(
            bundles_total=len(bundles),
            features_inserted=len(bundles),
            source_records_inserted=len(bundles),
            source_links_inserted=len(bundles),
        )

    monkeypatch.setattr(offline_upload_mod, "load_bundles", _load_bundles)

    result = await run_offline_upload_load_job(
        _NestedSession(),
        upload.upload_id,
        store=_MemoryStore({upload.storage_key: body}),
        dagster_run_id="run-1",
    )

    assert result.acquired is True
    assert result.upload.state == "loaded"
    assert result.job is not None
    assert result.job.state == "done"
    assert result.load == FeatureLoadResult(
        bundles_total=1,
        features_inserted=1,
        source_records_inserted=1,
        source_links_inserted=1,
    )
    assert loaded_bundle_names == ["오프라인 CSV 장소"]
    assert calls.load_state == "loaded"
    assert calls.heartbeats == [
        "read_object",
        "parse_feature_bundles",
        "load_feature_bundles",
    ]


@pytest.mark.asyncio
async def test_run_offline_upload_load_job_records_parser_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"name,lon,lat\nA,126.9,37.5\n"
    upload = _csv_upload(body, state="validated", validation_job_id="job-validation")
    calls = _FakeOfflineUploadCalls(upload)
    calls.validation_payload = {"column_mapping": {"name": "name", "lon": "x", "lat": "lat"}}
    _patch_offline_job_repos(monkeypatch, calls)

    result = await run_offline_upload_load_job(
        _NestedSession(),
        upload.upload_id,
        store=_MemoryStore({upload.storage_key: body}),
    )

    assert result.acquired is True
    assert result.upload.state == "load_failed"
    assert result.job is not None
    assert result.job.state == "failed"
    assert result.error_message == "lon column 'x'이 header에 없음."
    assert calls.load_state == "load_failed"


@pytest.mark.asyncio
async def test_run_offline_upload_load_job_uses_preclaimed_loading_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        "name,lon,lat,address,source_id,bjd_code\n"
        "오프라인 선전이 장소,126.9780,37.5665,서울특별시 중구 세종대로,csv-preclaim,1114010300\n"
    ).encode()
    upload = _csv_upload(
        body,
        state="loading",
        validation_job_id="job-validation",
        load_job_id="job-load-preclaimed",
    )
    calls = _FakeOfflineUploadCalls(upload)
    calls.jobs["job-load-preclaimed"] = ImportJob(
        job_id="job-load-preclaimed",
        kind="offline_upload_load",
        payload={"upload_id": upload.upload_id},
        state="running",
        progress=0,
        current_stage=None,
        source_checksum=upload.checksum_sha256,
        error_message=None,
    )
    calls.validation_payload = {
        "column_mapping": {
            "name": "name",
            "lon": "lon",
            "lat": "lat",
            "address": "address",
            "source_id": "source_id",
            "bjd_code": "bjd_code",
        }
    }
    _patch_offline_job_repos(monkeypatch, calls)

    async def _load_bundles(_session: object, bundles: list[FeatureBundle]) -> FeatureLoadResult:
        return FeatureLoadResult(
            bundles_total=len(bundles),
            features_inserted=len(bundles),
            source_records_inserted=len(bundles),
            source_links_inserted=len(bundles),
        )

    monkeypatch.setattr(offline_upload_mod, "load_bundles", _load_bundles)

    result = await run_offline_upload_load_job(
        _NestedSession(),
        upload.upload_id,
        store=_MemoryStore({upload.storage_key: body}),
        dagster_run_id="run-preclaimed",
    )

    assert result.acquired is True
    assert result.job is not None
    assert result.job.job_id == "job-load-preclaimed"
    assert calls.updated_payloads[-1]["dagster_run_id"] == "run-preclaimed"
    assert result.upload.state == "loaded"


@pytest.mark.asyncio
async def test_run_offline_upload_load_job_reports_lock_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"name,lon,lat\nA,126.9,37.5\n"
    upload = _csv_upload(body, state="validated", validation_job_id="job-validation")
    calls = _FakeOfflineUploadCalls(upload)
    _patch_offline_job_repos(monkeypatch, calls, lock_acquired=False)

    result = await run_offline_upload_load_job(
        _NestedSession(),
        upload.upload_id,
        store=_MemoryStore({upload.storage_key: body}),
    )

    assert result.acquired is False
    assert result.error_message == "offline upload load advisory lock busy"
    assert calls.jobs == {}


def _bundle(source_id: str) -> FeatureBundle:
    raw_payload = {
        "source_id": source_id,
        "name": "오프라인 테스트 장소",
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
        name="오프라인 테스트 장소",
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


def _csv_upload(
    body: bytes,
    *,
    state: str = "uploaded",
    validation_job_id: str | None = None,
    load_job_id: str | None = None,
) -> OfflineUpload:
    checksum = hashlib.sha256(body).hexdigest()
    return OfflineUpload(
        upload_id="00000000-0000-0000-0000-000000000011",
        provider="offline-test-provider",
        dataset_key="offline_csv",
        sync_scope="default",
        original_filename="features.csv",
        storage_backend="rustfs",
        storage_key="offline/features.csv",
        byte_size=len(body),
        checksum_sha256=checksum,
        detected_format="csv",
        detected_encoding="utf-8",
        state=state,
        validation_job_id=validation_job_id,
        load_job_id=load_job_id,
        created_by="pytest",
        created_at=_FETCHED_AT,
        updated_at=_FETCHED_AT,
    )


class _MemoryStore:
    def __init__(self, objects: Mapping[str, bytes]) -> None:
        self._objects = dict(objects)

    async def read_bytes(self, storage_key: str) -> bytes:
        return self._objects[storage_key]


class _NestedSession:
    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        yield


class _FakeOfflineUploadCalls:
    def __init__(self, upload: OfflineUpload) -> None:
        self.upload = upload
        self.jobs: dict[str, ImportJob] = {}
        self.validation_payload: dict[str, Any] | None = None
        self.updated_payloads: list[dict[str, Any]] = []
        self.finished_jobs: list[ImportJob] = []
        self.heartbeats: list[str] = []
        self.validation_state: str | None = None
        self.load_state: str | None = None

    def _replace_upload(self, **changes: object) -> OfflineUpload:
        data = self.upload.__dict__ | changes
        self.upload = OfflineUpload(**data)
        return self.upload

    def _replace_job(self, job: ImportJob, **changes: object) -> ImportJob:
        data = job.__dict__ | changes
        updated = ImportJob(**data)
        self.jobs[job.job_id] = updated
        return updated


def _patch_offline_job_repos(
    monkeypatch: pytest.MonkeyPatch,
    calls: _FakeOfflineUploadCalls,
    *,
    lock_acquired: bool = True,
) -> None:
    @asynccontextmanager
    async def _try_advisory_lock(_session: object, _key: str) -> AsyncIterator[bool]:
        yield lock_acquired

    async def _get_offline_upload(_session: object, upload_id: str) -> OfflineUpload | None:
        return calls.upload if upload_id == calls.upload.upload_id else None

    async def _start_import_job(
        _session: object,
        *,
        kind: str,
        payload: Mapping[str, Any] | None = None,
        source_checksum: str | None = None,
    ) -> ImportJob:
        job_id = f"job-{len(calls.jobs) + 1}"
        job = ImportJob(
            job_id=job_id,
            kind=kind,
            payload=dict(payload or {}),
            state="running",
            progress=0,
            current_stage=None,
            source_checksum=source_checksum,
            error_message=None,
        )
        calls.jobs[job_id] = job
        return job

    async def _heartbeat_import_job(
        _session: object,
        job_id: str,
        *,
        progress: int | None = None,
        current_stage: str | None = None,
    ) -> ImportJob:
        job = calls.jobs[job_id]
        calls.heartbeats.append(current_stage or "")
        return calls._replace_job(
            job,
            progress=progress if progress is not None else job.progress,
            current_stage=current_stage,
        )

    async def _finish_import_job(
        _session: object,
        job_id: str,
        *,
        state: str,
        error_message: str | None = None,
    ) -> ImportJob:
        job = calls._replace_job(
            calls.jobs[job_id],
            state=state,
            progress=100 if state == "done" else calls.jobs[job_id].progress,
            error_message=error_message,
        )
        calls.finished_jobs.append(job)
        return job

    async def _update_import_job_payload(
        _session: object,
        job_id: str,
        *,
        payload: Mapping[str, Any],
    ) -> ImportJob:
        calls.updated_payloads.append(dict(payload))
        return calls._replace_job(calls.jobs[job_id], payload=dict(payload))

    async def _get_import_job(_session: object, job_id: str) -> ImportJob | None:
        if job_id == calls.upload.validation_job_id and calls.validation_payload is not None:
            return ImportJob(
                job_id=job_id,
                kind="offline_upload_validate",
                payload=calls.validation_payload,
                state="done",
                progress=100,
                current_stage=None,
                source_checksum=calls.upload.checksum_sha256,
                error_message=None,
            )
        return calls.jobs.get(job_id)

    async def _mark_validating(
        _session: object,
        *,
        upload_id: str,
        validation_job_id: str,
    ) -> OfflineUpload:
        assert upload_id == calls.upload.upload_id
        return calls._replace_upload(state="validating", validation_job_id=validation_job_id)

    async def _finish_validation(
        _session: object,
        *,
        upload_id: str,
        state: str,
    ) -> OfflineUpload:
        assert upload_id == calls.upload.upload_id
        calls.validation_state = state
        return calls._replace_upload(state=state)

    async def _mark_loading(
        _session: object,
        *,
        upload_id: str,
        load_job_id: str,
    ) -> OfflineUpload:
        assert upload_id == calls.upload.upload_id
        return calls._replace_upload(state="loading", load_job_id=load_job_id)

    async def _finish_load(
        _session: object,
        *,
        upload_id: str,
        state: str,
    ) -> OfflineUpload:
        assert upload_id == calls.upload.upload_id
        calls.load_state = state
        return calls._replace_upload(state=state)

    monkeypatch.setattr(offline_upload_mod, "try_advisory_lock", _try_advisory_lock)
    monkeypatch.setattr(offline_upload_mod, "get_offline_upload", _get_offline_upload)
    monkeypatch.setattr(offline_upload_mod, "start_import_job", _start_import_job)
    monkeypatch.setattr(offline_upload_mod, "heartbeat_import_job", _heartbeat_import_job)
    monkeypatch.setattr(offline_upload_mod, "finish_import_job", _finish_import_job)
    monkeypatch.setattr(offline_upload_mod, "update_import_job_payload", _update_import_job_payload)
    monkeypatch.setattr(offline_upload_mod, "get_import_job", _get_import_job)
    monkeypatch.setattr(offline_upload_mod, "mark_offline_upload_validating", _mark_validating)
    monkeypatch.setattr(offline_upload_mod, "finish_offline_upload_validation", _finish_validation)
    monkeypatch.setattr(offline_upload_mod, "mark_offline_upload_loading", _mark_loading)
    monkeypatch.setattr(offline_upload_mod, "finish_offline_upload_load", _finish_load)
