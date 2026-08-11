"""``/v1/admin/offline-uploads`` 라우터 단위 테스트."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from kortravelmap.core.exceptions import (
    FileStoreObjectNotFoundError,
    GeoAuthNotConfiguredError,
    GeoRequestError,
)
from kortravelmap.infra.file_store import StoredObject
from kortravelmap.infra.jobs_repo import ImportJob
from kortravelmap.infra.offline_upload_repo import (
    OfflineUpload,
    OfflineUploadPage,
    OfflineUploadScopeOperationUnresolved,
    OfflineUploadStatusConflict,
)
from kortravelmap.offline_upload import validate_offline_tabular_upload
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.begin_count = 0

    def begin(self) -> _Tx:
        self.begin_count += 1
        return _Tx()


class _FakeStore:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.bucket = "kor-travel-map-uploads"
        self.calls: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.objects = objects or {}

    async def read_bytes(self, storage_key: str) -> bytes:
        return self.objects[storage_key]

    async def write_bytes(
        self,
        storage_key: str,
        body: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        self.calls.append(
            {
                "storage_key": storage_key,
                "body": body,
                "content_type": content_type,
                "metadata": metadata,
            }
        )
        self.objects[storage_key] = body
        return StoredObject(
            bucket="kor-travel-map-uploads",
            object_key=storage_key,
            byte_size=len(body),
            checksum_sha256=hashlib.sha256(body).hexdigest(),
            content_type=content_type or "application/octet-stream",
            metadata=dict(metadata or {}),
        )

    async def inspect_object(self, storage_key: str) -> StoredObject:
        call = next(
            (
                item
                for item in reversed(self.calls)
                if item["storage_key"] == storage_key
            ),
            None,
        )
        if call is None:
            raise FileStoreObjectNotFoundError(storage_key)
        body = self.objects[storage_key]
        return StoredObject(
            bucket="kor-travel-map-uploads",
            object_key=storage_key,
            byte_size=len(body),
            checksum_sha256=hashlib.sha256(body).hexdigest(),
            content_type=call["content_type"],
            metadata=dict(call["metadata"] or {}),
        )

    async def delete_object(self, storage_key: str) -> None:
        self.deleted.append(storage_key)
        self.objects.pop(storage_key, None)


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    from kortravelmap.infra.domain_command_execution_repo import (
        OfflineUploadCommandExecution,
    )

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import offline_uploads as router_mod

    app = create_app(ApiSettings(admin_destructive_enabled=True))

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    monkeypatch.setattr(
        domain_command_service,
        "begin_domain_command",
        AsyncMock(
            return_value=domain_command_service.DomainCommandHandle(
                command_id=1,
                actor="local-dev",
                operation="admin.offline-upload.create",
                idempotency_key="95000000-0000-4000-8000-000000000001",
                request_fingerprint="a" * 64,
            )
        ),
    )
    monkeypatch.setattr(
        domain_command_service,
        "complete_domain_command",
        AsyncMock(),
    )
    now = datetime(2026, 7, 31, tzinfo=UTC)
    executions: dict[int, OfflineUploadCommandExecution] = {}

    async def _create_execution(
        _session: object,
        **kwargs: Any,
    ) -> OfflineUploadCommandExecution:
        execution = OfflineUploadCommandExecution(
            command_id=int(kwargs["command_id"]),
            effect_kind=str(kwargs["effect_kind"]),
            phase="prepared",
            upload_id=str(kwargs["upload_id"]),
            storage_backend=kwargs["storage_backend"],
            bucket=kwargs["bucket"],
            storage_key=kwargs["storage_key"],
            content_type=kwargs["content_type"],
            byte_size=kwargs["byte_size"],
            content_sha256=kwargs["content_sha256"],
            metadata_digest=kwargs["metadata_digest"],
            load_job_id=kwargs["load_job_id"],
            dagster_run_id=None,
            input_digest=str(kwargs["input_digest"]),
            output_digest=None,
            prepared_at=now,
            effect_started_at=None,
            effect_completed_at=None,
        )
        executions[execution.command_id] = execution
        return execution

    async def _get_execution(
        _session: object,
        command_id: int,
    ) -> OfflineUploadCommandExecution | None:
        return executions.get(command_id)

    async def _start_execution(
        _session: object,
        command_id: int,
    ) -> OfflineUploadCommandExecution:
        execution = replace(
            executions[command_id],
            phase="effect_started",
            effect_started_at=now,
        )
        executions[command_id] = execution
        return execution

    monkeypatch.setattr(
        router_mod,
        "create_offline_upload_command_execution",
        _create_execution,
    )
    monkeypatch.setattr(
        router_mod,
        "get_offline_upload_command_execution",
        _get_execution,
    )
    monkeypatch.setattr(
        router_mod,
        "start_offline_upload_command_effect",
        _start_execution,
    )
    monkeypatch.setattr(
        router_mod,
        "complete_offline_upload_command_effect",
        AsyncMock(),
    )

    async def _reserve_delete(
        _session: object,
        *,
        upload_id: str,
        command_id: int,
    ) -> OfflineUpload | None:
        row = await router_mod.get_offline_upload(_session, upload_id)
        if row is None:
            return None
        if row.status in {"uploading", "validating", "loading", "deleting"}:
            raise OfflineUploadStatusConflict(
                upload_id=upload_id,
                current_status=row.status,
                target_status="deleting",
                allowed_statuses=frozenset(
                    {
                        "uploaded",
                        "validated",
                        "validation_failed",
                        "loaded",
                        "load_failed",
                        "cancelled",
                    }
                ),
            )
        return replace(
            row,
            status="deleting",
            delete_command_id=command_id,
        )

    monkeypatch.setattr(
        router_mod,
        "reserve_offline_upload_delete",
        _reserve_delete,
    )
    return TestClient(
        app,
        headers={"Idempotency-Key": "95000000-0000-4000-8000-000000000001"},
    )


# T-VN-33 (ADR-088): offline upload identity는
# provider_dataset_id + sync_scope + operation_key다. 자연키 사본(provider/
# dataset_key)은 스키마에서 삭제됐고, operation_key는 scope에서 유도돼 NOT NULL로 든다.
_PROVIDER_DATASET_ID: int = 7
_SYNC_SCOPE: str = "dataset_wide"
_OPERATION_KEY: str = "feature_weather_kma_ultra_short_nowcast_job"
_PROVIDER_DISPLAY: str = "kma"
_DATASET_KEY_DISPLAY: str = "ultra_short_nowcast"
_CREATE_FORM: dict[str, str] = {
    "provider_dataset_id": str(_PROVIDER_DATASET_ID),
    "sync_scope": _SYNC_SCOPE,
}


def _upload(
    *,
    upload_id: str = "00000000-0000-0000-0000-000000000001",
    state: str = "uploaded",
    storage_key: str | None = None,
    original_filename: str = "features.jsonl",
    detected_format: str = "jsonl",
    provider_dataset_id: int = _PROVIDER_DATASET_ID,
    sync_scope: str = _SYNC_SCOPE,
    operation_key: str = _OPERATION_KEY,
    byte_size: int = 123,
    checksum_sha256: str = "a" * 64,
    validation_job_id: str | None = None,
    load_job_id: str | None = None,
) -> OfflineUpload:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OfflineUpload(
        upload_id=upload_id,
        provider_dataset_id=provider_dataset_id,
        sync_scope=sync_scope,
        operation_key=operation_key,
        original_filename=original_filename,
        storage_backend="rustfs",
        storage_key=storage_key or f"offline-uploads/{upload_id}/{original_filename}",
        byte_size=byte_size,
        checksum_sha256=checksum_sha256,
        detected_format=detected_format,
        detected_encoding="utf-8",
        status=state,
        validation_job_id=validation_job_id,
        load_job_id=load_job_id,
        created_by="pytest",
        created_at=now,
        updated_at=now,
    )


def _import_job(
    *,
    job_id: str = "10000000-0000-0000-0000-000000000001",
    payload: dict[str, Any] | None = None,
    state: str = "running",
    source_checksum: str | None = "a" * 64,
    error_message: str | None = None,
) -> ImportJob:
    return ImportJob(
        job_id=job_id,
        kind="offline_upload_load",
        payload=payload or {},
        status=state,
        progress=0 if state == "running" else 100,
        current_stage=None,
        source_checksum=source_checksum,
        error_message=error_message,
    )


@pytest.mark.unit
def test_offline_upload_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/admin/offline-uploads" in spec["paths"]
    assert "/v1/admin/offline-uploads/{upload_id}" in spec["paths"]
    assert "delete" in spec["paths"]["/v1/admin/offline-uploads/{upload_id}"]
    assert "/v1/admin/offline-uploads/{upload_id}/preview" in spec["paths"]
    assert "/v1/admin/offline-uploads/{upload_id}/validate" in spec["paths"]
    assert "/v1/admin/offline-uploads/{upload_id}/validation" in spec["paths"]
    assert "/v1/admin/offline-uploads/{upload_id}/load" in spec["paths"]
    assert "OfflineUploadRecord" in spec["components"]["schemas"]


@pytest.mark.unit
def test_create_offline_upload_writes_object_and_metadata(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    store = _FakeStore()
    upload_body = b'{"feature":{"feature_id":"f1"}}\n'
    expected_checksum = hashlib.sha256(upload_body).hexdigest()
    reserved: OfflineUpload | None = None

    async def _create(_session: Any, **kwargs: Any) -> OfflineUpload:
        nonlocal reserved
        assert kwargs["provider_dataset_id"] == _PROVIDER_DATASET_ID
        assert kwargs["sync_scope"] == _SYNC_SCOPE
        assert kwargs["storage_backend"] == "rustfs"
        assert kwargs["detected_format"] == "jsonl"
        assert kwargs["detected_encoding"] is None
        assert kwargs["checksum_sha256"] == expected_checksum
        # T-VN-20 (ADR-066 D-2): created_by는 인증 principal(local-dev)에서만 파생한다.
        assert kwargs["created_by"] == "local-dev"
        reserved = _upload(
            upload_id=kwargs["upload_id"],
            state="uploading",
            storage_key=kwargs["storage_key"],
            checksum_sha256=kwargs["checksum_sha256"],
        )
        return reserved

    async def _finalize(_session: Any, **_kwargs: Any) -> OfflineUpload:
        assert reserved is not None
        return replace(reserved, status="uploaded")

    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "reserve_offline_upload", _create)
    monkeypatch.setattr(router_mod, "finalize_offline_upload_reservation", _finalize)

    response = client.post(
        "/v1/admin/offline-uploads",
        data=dict(_CREATE_FORM),
        files={
            "file": (
                "features.jsonl",
                upload_body,
                "application/x-ndjson",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["status"] == "uploaded"
    assert body["data"]["provider_dataset_id"] == _PROVIDER_DATASET_ID
    assert body["data"]["sync_scope"] == _SYNC_SCOPE
    assert body["meta"]["bucket"] == "kor-travel-map-uploads"
    assert body["meta"]["object_key"].startswith("offline-uploads/")
    assert store.calls[0]["body"] == b'{"feature":{"feature_id":"f1"}}\n'
    assert store.calls[0]["metadata"]["provider-dataset-id"] == str(_PROVIDER_DATASET_ID)
    assert store.calls[0]["metadata"]["sync-scope"] == _SYNC_SCOPE
    # claim+DB 예약, effect_started, 증명+terminal result, registry hook.
    assert session.begin_count == 4


@pytest.mark.unit
def test_create_offline_upload_duplicate_checksum_stops_before_object_store(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    store = _FakeStore()
    existing = _upload(upload_id="00000000-0000-0000-0000-000000000099")

    async def _reserve(_session: Any, **_kwargs: Any) -> None:
        return None

    async def _resolve(_session: Any, **kwargs: Any) -> str:
        assert kwargs["provider_dataset_id"] == _PROVIDER_DATASET_ID
        assert kwargs["sync_scope"] == _SYNC_SCOPE
        return existing.operation_key

    async def _duplicate(_session: Any, **kwargs: Any) -> OfflineUpload:
        assert kwargs["provider_dataset_id"] == _PROVIDER_DATASET_ID
        assert kwargs["sync_scope"] == _SYNC_SCOPE
        # 멱등 UNIQUE가 4열이므로 중복 조회도 triple을 지정해야 한다 —
        # writer가 결박한 operation을 빼면 형제 행을 집을 수 있다(alembic 0092).
        assert kwargs["operation_key"] == existing.operation_key
        assert kwargs["checksum_sha256"] == hashlib.sha256(
            b'{"feature":{"feature_id":"f1"}}\n'
        ).hexdigest()
        return existing

    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "reserve_offline_upload", _reserve)
    monkeypatch.setattr(router_mod, "resolve_offline_upload_operation_key", _resolve)
    monkeypatch.setattr(router_mod, "get_offline_upload_by_checksum", _duplicate)

    response = client.post(
        "/v1/admin/offline-uploads",
        data=dict(_CREATE_FORM),
        files={
            "file": (
                "features.jsonl",
                b'{"feature":{"feature_id":"f1"}}\n',
                "application/x-ndjson",
            )
        },
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "OFFLINE_UPLOAD_DUPLICATE"
    # T-VN-33 (ADR-088): 409는 가리키는 행의 exact identity(triple) + status를 싣는다.
    assert body["details"]["upload_id"] == existing.upload_id
    assert body["details"]["provider_dataset_id"] == existing.provider_dataset_id
    assert body["details"]["sync_scope"] == existing.sync_scope
    assert body["details"]["operation_key"] == existing.operation_key
    assert body["details"]["status"] == existing.status
    assert store.calls == []
    assert store.deleted == []


@pytest.mark.unit
def test_create_offline_upload_accepts_csv(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    store = _FakeStore()
    reserved: OfflineUpload | None = None

    async def _create(_session: Any, **kwargs: Any) -> OfflineUpload:
        nonlocal reserved
        assert kwargs["detected_format"] == "csv"
        reserved = _upload(
            upload_id=kwargs["upload_id"],
            state="uploading",
            storage_key=kwargs["storage_key"],
            original_filename="features.csv",
            detected_format="csv",
            provider_dataset_id=kwargs["provider_dataset_id"],
            sync_scope=kwargs["sync_scope"],
            byte_size=kwargs["byte_size"],
            checksum_sha256=kwargs["checksum_sha256"],
        )
        return reserved

    async def _finalize(_session: Any, **_kwargs: Any) -> OfflineUpload:
        assert reserved is not None
        return replace(reserved, status="uploaded")

    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "reserve_offline_upload", _create)
    monkeypatch.setattr(router_mod, "finalize_offline_upload_reservation", _finalize)

    response = client.post(
        "/v1/admin/offline-uploads",
        data=dict(_CREATE_FORM),
        files={"file": ("features.csv", b"name,lon,lat\nA,126.9,37.5\n", "text/csv")},
    )

    assert response.status_code == 201
    assert response.json()["data"]["detected_format"] == "csv"


@pytest.mark.unit
def test_create_offline_upload_restarts_exact_put_after_started_crash(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid5

    from kortravelmap.infra.domain_command_execution_repo import (
        OfflineUploadCommandExecution,
    )
    from kortravelmap.infra.domain_command_repo import (
        DomainCommandClaim,
        canonical_domain_command_fingerprint,
    )

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import offline_uploads as router_mod

    key = "95000000-0000-4000-8000-000000000001"
    operation = "admin.offline-upload.create"
    body = b'{"feature":{"feature_id":"f1"}}\n'
    checksum = hashlib.sha256(body).hexdigest()
    settings = KorTravelMapSettings(_env_file=None)
    client.app.state.kor_travel_map_settings = settings
    upload_id = str(
        uuid5(
            router_mod._OFFLINE_UPLOAD_COMMAND_NAMESPACE,
            f"local-dev:{operation}:{key}",
        )
    )
    storage_key = router_mod._storage_key(settings, upload_id, "features.jsonl")
    content_type = "application/x-ndjson"
    metadata = {
        "content-sha256": checksum,
        "provider-dataset-id": str(_PROVIDER_DATASET_ID),
        "sync-scope": _SYNC_SCOPE,
        "upload-id": upload_id,
    }
    metadata_digest = canonical_domain_command_fingerprint(metadata)
    fingerprint = canonical_domain_command_fingerprint(
        {
            "provider_dataset_id": _PROVIDER_DATASET_ID,
            "sync_scope": _SYNC_SCOPE,
            "filename": "features.jsonl",
            "storage_backend": "rustfs",
            "bucket": settings.offline_upload_bucket,
            "storage_key": storage_key,
            "content_type": content_type,
            "byte_size": len(body),
            "content_sha256": checksum,
            "metadata_digest": metadata_digest,
        }
    )
    now = datetime(2026, 7, 31, tzinfo=UTC)
    claim = DomainCommandClaim(
        command_id=99,
        actor="local-dev",
        operation=operation,
        idempotency_key=key,
        fingerprint_version=1,
        request_fingerprint=fingerprint,
        created_at=now,
    )
    execution = OfflineUploadCommandExecution(
        command_id=99,
        effect_kind="create",
        phase="effect_started",
        upload_id=upload_id,
        storage_backend="rustfs",
        bucket=settings.offline_upload_bucket,
        storage_key=storage_key,
        content_type=content_type,
        byte_size=len(body),
        content_sha256=checksum,
        metadata_digest=metadata_digest,
        load_job_id=None,
        dagster_run_id=None,
        input_digest=fingerprint,
        output_digest=None,
        prepared_at=now,
        effect_started_at=now,
        effect_completed_at=None,
    )
    reserved = _upload(
        upload_id=upload_id,
        state="uploading",
        storage_key=storage_key,
        byte_size=len(body),
        checksum_sha256=checksum,
    )
    store = _FakeStore()
    client.app.state.offline_upload_store = store

    async def _pending(*_args: Any, **_kwargs: Any) -> Any:
        raise domain_command_service.DomainCommandPending(claim)

    async def _get_execution(*_args: Any, **_kwargs: Any) -> Any:
        return execution

    async def _get_upload(*_args: Any, **_kwargs: Any) -> OfflineUpload:
        return reserved

    async def _finalize(*_args: Any, **_kwargs: Any) -> OfflineUpload:
        return replace(reserved, status="uploaded")

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _pending)
    monkeypatch.setattr(
        router_mod,
        "get_offline_upload_command_execution",
        _get_execution,
    )
    monkeypatch.setattr(router_mod, "get_offline_upload", _get_upload)
    monkeypatch.setattr(
        router_mod,
        "finalize_offline_upload_reservation",
        _finalize,
    )
    monkeypatch.setattr(
        router_mod,
        "start_offline_upload_command_effect",
        AsyncMock(side_effect=AssertionError("effect already started")),
    )

    response = client.post(
        "/v1/admin/offline-uploads",
        data=dict(_CREATE_FORM),
        files={"file": ("features.jsonl", body, content_type)},
    )

    assert response.status_code == 201
    assert len(store.calls) == 1
    assert store.calls[0]["storage_key"] == storage_key
    assert store.calls[0]["metadata"] == metadata


@pytest.mark.unit
def test_offline_upload_store_is_reused_from_app_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    store = _FakeStore()
    build_count = 0
    reserved: OfflineUpload | None = None

    def _build_store(_settings: Any) -> _FakeStore:
        nonlocal build_count
        build_count += 1
        return store

    async def _create(_session: Any, **kwargs: Any) -> OfflineUpload:
        nonlocal reserved
        reserved = _upload(
            upload_id=kwargs["upload_id"],
            state="uploading",
            storage_key=kwargs["storage_key"],
            provider_dataset_id=kwargs["provider_dataset_id"],
            sync_scope=kwargs["sync_scope"],
            byte_size=kwargs["byte_size"],
            checksum_sha256=kwargs["checksum_sha256"],
        )
        return reserved

    async def _finalize(_session: Any, **_kwargs: Any) -> OfflineUpload:
        assert reserved is not None
        return replace(reserved, status="uploaded")

    monkeypatch.setattr(router_mod, "build_offline_upload_store", _build_store)
    monkeypatch.setattr(router_mod, "reserve_offline_upload", _create)
    monkeypatch.setattr(router_mod, "finalize_offline_upload_reservation", _finalize)

    for filename in ("features-a.jsonl", "features-b.jsonl"):
        response = client.post(
            "/v1/admin/offline-uploads",
            data=dict(_CREATE_FORM),
            files={
                "file": (filename, b'{"feature":{"feature_id":"f1"}}\n', "application/x-ndjson")
            },
        )
        assert response.status_code == 201

    assert build_count == 1
    assert len(store.calls) == 2


@pytest.mark.unit
def test_preview_offline_upload_prefers_app_state_store(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    body = b"name,lon,lat\nA,126.9,37.5\n"
    storage_key = "offline/features.csv"
    upload = _upload(
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        byte_size=len(body),
        checksum_sha256=hashlib.sha256(body).hexdigest(),
    )
    store = _FakeStore({storage_key: body})
    client.app.state.offline_upload_store = store

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        assert upload_id == upload.upload_id
        return upload

    def _build_store(_settings: Any) -> _FakeStore:
        raise AssertionError("cached app.status store must be reused")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", _build_store)

    response = client.get(f"/v1/admin/offline-uploads/{upload.upload_id}/preview")

    assert response.status_code == 200
    assert response.json()["meta"]["headers"] == ["name", "lon", "lat"]


@pytest.mark.unit
def test_validate_offline_upload_prefers_app_state_store(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    body = b"name,lon,lat,address\nA,126.9,37.5,\n"
    storage_key = "offline/features.csv"
    checksum = hashlib.sha256(body).hexdigest()
    upload = _upload(
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        byte_size=len(body),
        checksum_sha256=checksum,
    )
    validated_upload = _upload(
        state="validated",
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        byte_size=len(body),
        checksum_sha256=checksum,
        validation_job_id="00000000-0000-0000-0000-000000000101",
    )
    store = _FakeStore({storage_key: body})
    client.app.state.offline_upload_store = store

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        assert upload_id == upload.upload_id
        return upload

    async def _run(_session: Any, upload_id: str, **kwargs: Any) -> Any:
        assert upload_id == upload.upload_id
        assert kwargs["store"] is store
        # T-VN-33: provider/dataset_key는 upload 행이 아니라 provider_dataset_id에서
        # 유도한 표시명이다(실제 run_offline_upload_validation_job이 하는 일).
        return validate_offline_tabular_upload(
            validated_upload,
            body,
            provider=_PROVIDER_DISPLAY,
            dataset_key=_DATASET_KEY_DISPLAY,
            column_mapping=kwargs["column_mapping"],
            sample_size=kwargs["sample_size"],
            checksum_sha256=checksum,
        )

    def _build_store(_settings: Any) -> _FakeStore:
        raise AssertionError("cached app.status store must be reused")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "run_offline_upload_validation_job", _run)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", _build_store)

    response = client.post(
        f"/v1/admin/offline-uploads/{upload.upload_id}/validate",
        json={
            "sample_size": 100,
            "column_mapping": {
                "name": "name",
                "lon": "lon",
                "lat": "lat",
                "address": "address",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "validated"


@pytest.mark.unit
def test_create_app_lifespan_closes_cached_offline_upload_s3_client() -> None:
    class _ClosableS3Client:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class _Store:
        def __init__(self, s3_client: _ClosableS3Client) -> None:
            self.s3_client = s3_client

    s3_client = _ClosableS3Client()
    app = create_app(ApiSettings())

    with TestClient(app) as live_client:
        live_client.app.state.offline_upload_store = _Store(s3_client)

    assert s3_client.closed is True


@pytest.mark.unit
def test_create_offline_upload_stops_before_object_when_reservation_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    store = _FakeStore()

    async def _create(_session: Any, **_kwargs: Any) -> OfflineUpload:
        raise RuntimeError("metadata reservation failed")

    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "reserve_offline_upload", _create)

    with pytest.raises(RuntimeError, match="metadata reservation failed"):
        client.post(
            "/v1/admin/offline-uploads",
            data=dict(_CREATE_FORM),
            files={
                "file": (
                    "features.jsonl",
                    b'{"feature":{"feature_id":"f1"}}\n',
                    "application/x-ndjson",
                )
            },
        )

    assert store.calls == []
    assert store.deleted == []
    assert store.objects == {}


def _post_upload(client: TestClient) -> Any:
    return client.post(
        "/v1/admin/offline-uploads",
        data=dict(_CREATE_FORM),
        files={
            "file": (
                "features.jsonl",
                b'{"feature":{"feature_id":"f1"}}\n',
                "application/x-ndjson",
            )
        },
    )


@pytest.mark.unit
def test_create_offline_upload_409_when_scope_has_no_enabled_operation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-VN-33 (ADR-088): scope→operation 유도 실패는 500이 아니라 typed 409다.

    resolved==0은 scope 행이 없을 때뿐 아니라 **operation이 disabled / dataset이
    inactive**일 때도 온다(유도가 DB 활성 가드와 같은 조건을 보므로). 그래서 처방은
    "등록하세요" 하나로 끝나면 안 된다 — 비활성 확인까지 말해야 한다.
    """

    from kortravelmap.api.routers import offline_uploads as router_mod

    store = _FakeStore()

    async def _unresolved(_session: Any, **_kwargs: Any) -> OfflineUpload:
        raise OfflineUploadScopeOperationUnresolved(
            "offline upload scope resolves to 0 operations", resolved=0
        )

    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "reserve_offline_upload", _unresolved)

    response = _post_upload(client)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "활성 refresh operation이 없어" in detail
    # 두 원인 모두에 처방이 닿아야 한다.
    assert "등록" in detail
    assert "is_active" in detail
    assert "is_enabled" in detail
    # 모호(>1) 쪽 문구가 새면 분기가 무너진 것이다.
    assert "여러 개" not in detail
    # 결박할 operation을 못 정했으므로 객체 저장은 시작조차 안 한다.
    assert store.calls == []
    assert store.deleted == []
    assert store.objects == {}


@pytest.mark.unit
def test_create_offline_upload_409_when_scope_is_ambiguous(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """활성 operation이 둘 이상이면 다른 처방이 나가야 한다.

    "등록하세요"는 여기서 정반대 지시다 — 이미 너무 많다.
    """

    from kortravelmap.api.routers import offline_uploads as router_mod

    store = _FakeStore()

    async def _unresolved(_session: Any, **_kwargs: Any) -> OfflineUpload:
        raise OfflineUploadScopeOperationUnresolved(
            "offline upload scope resolves to 2 operations", resolved=2
        )

    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "reserve_offline_upload", _unresolved)

    response = _post_upload(client)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "여러 개" in detail
    assert "등록" not in detail
    assert store.calls == []
    assert store.deleted == []
    assert store.objects == {}


@pytest.mark.unit
def test_create_rejects_file_over_configured_max_bytes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    def _build_store(_settings: Any) -> _FakeStore:
        raise AssertionError("oversized upload must be rejected before object store")

    monkeypatch.setenv("KOR_TRAVEL_MAP_OFFLINE_UPLOAD_MAX_BYTES", "8")
    monkeypatch.setattr(router_mod, "build_offline_upload_store", _build_store)

    response = client.post(
        "/v1/admin/offline-uploads",
        data=dict(_CREATE_FORM),
        files={"file": ("features.jsonl", b"123456789", "application/x-ndjson")},
    )

    assert response.status_code == 413
    assert "최대 8 bytes" in response.json()["detail"]


@pytest.mark.unit
def test_create_rejects_unsupported_format(client: TestClient) -> None:
    response = client.post(
        "/v1/admin/offline-uploads",
        data=dict(_CREATE_FORM),
        files={"file": ("features.xlsx", b"id,name\n1,a\n", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "CSV/TSV" in response.json()["detail"]


@pytest.mark.unit
def test_list_offline_uploads_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    async def _list(_session: Any, **kwargs: Any) -> OfflineUploadPage:
        assert kwargs["status"] == "uploaded"
        assert kwargs["provider_dataset_id"] == _PROVIDER_DATASET_ID
        assert kwargs["limit"] == 25
        return OfflineUploadPage(items=(_upload(),), next_cursor="next")

    monkeypatch.setattr(router_mod, "list_offline_uploads", _list)

    response = client.get(
        "/v1/admin/offline-uploads",
        params={
            "status": "uploaded",
            "provider_dataset_id": _PROVIDER_DATASET_ID,
            "page_size": 25,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["page"] == {
        "page_size": 25,
        "next_cursor": "next",
        "total": None,
    }
    assert body["data"]["items"][0]["upload_id"] == (
        "00000000-0000-0000-0000-000000000001"
    )
    assert body["data"]["items"][0]["status"] == "uploaded"


@pytest.mark.unit
def test_load_offline_upload_launches_dagster(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    order: list[str] = []
    upload = _upload(upload_id="00000000-0000-0000-0000-000000000001")
    reserved = _upload(
        upload_id=upload.upload_id,
        state="loading",
        load_job_id="10000000-0000-0000-0000-000000000001",
    )

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        assert upload_id == upload.upload_id
        return upload

    async def _reserve(_session: Any, **kwargs: Any) -> OfflineUpload:
        order.append("reserve")
        assert kwargs["upload_id"] == upload.upload_id
        return reserved

    async def _launch(_request: Any, upload_id: str, *, run_id: str) -> Any:
        order.append("launch")
        assert upload_id == upload.upload_id
        assert run_id == reserved.load_job_id
        return router_mod._DagsterLaunch(run_id=run_id, status="QUEUED")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "reserve_offline_upload_load", _reserve)
    monkeypatch.setattr(router_mod, "launch_offline_upload_load", _launch)

    response = client.post("/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["upload_id"] == "00000000-0000-0000-0000-000000000001"
    assert body["data"]["status"] == "loading"
    assert body["data"]["load_job_id"] == "10000000-0000-0000-0000-000000000001"
    assert body["meta"]["dagster_run_id"] == reserved.load_job_id
    assert order == ["reserve", "launch"]


@pytest.mark.unit
def test_load_offline_upload_rejects_invalid_dagster_url_before_db_or_http(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    app = create_app(
        ApiSettings(
            dagster_url="http://dagster.example:12302",
            dagster_graphql_url=(
                "http://user:super-secret@dagster.example:12302/graphql?token=secret"
            ),
            dagster_allowed_hosts=["dagster.example"],
        )
    )
    calls: list[str] = []

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    async def _unexpected_get(_session: Any, upload_id: str) -> OfflineUpload:
        calls.append("get")
        raise AssertionError("invalid Dagster URL must fail before DB lookup")

    async def _unexpected_post(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append("post")
        raise AssertionError("invalid Dagster URL must fail before HTTP")

    app.dependency_overrides[get_session] = _fake_session
    monkeypatch.setattr(router_mod, "get_offline_upload", _unexpected_get)
    monkeypatch.setattr(router_mod, "_post_graphql", _unexpected_post)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load",
            headers={
                "Idempotency-Key": "95000000-0000-4000-8000-000000000001"
            },
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Dagster GraphQL URL 설정이 올바르지 않습니다."
    assert calls == []
    assert session.begin_count == 0
    assert "super-secret" not in response.text
    assert "token=secret" not in response.text


@pytest.mark.unit
def test_dagster_launch_variables_use_settings() -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    settings = ApiSettings(
        dagster_repository_name="admin-repo",
        dagster_repository_location_name="kortravelmap.dagster.custom",
    )

    variables = router_mod._launch_variables(
        settings,
        "00000000-0000-0000-0000-000000000001",
        run_id="10000000-0000-0000-0000-000000000001",
    )

    selector = variables["executionParams"]["selector"]
    run_config = variables["executionParams"]["runConfigData"]
    assert selector["repositoryName"] == "admin-repo"
    assert selector["repositoryLocationName"] == "kortravelmap.dagster.custom"
    assert run_config["ops"]["load_offline_upload"]["config"]["upload_id"] == (
        "00000000-0000-0000-0000-000000000001"
    )
    assert variables["executionParams"]["executionMetadata"]["runId"] == (
        "10000000-0000-0000-0000-000000000001"
    )


@pytest.mark.unit
def test_load_offline_upload_rejects_concurrent_reserve(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(upload_id=upload_id)

    async def _reserve(_session: Any, *, upload_id: str) -> OfflineUpload:
        raise OfflineUploadStatusConflict(
            upload_id=upload_id,
            current_status="loading",
            target_status="loading",
            allowed_statuses=frozenset({"uploaded", "validated", "load_failed"}),
        )

    async def _launch(_request: Any, _upload_id: str) -> Any:
        raise AssertionError("conflicting reserve must not launch Dagster")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "reserve_offline_upload_load", _reserve)
    monkeypatch.setattr(router_mod, "launch_offline_upload_load", _launch)

    response = client.post("/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load")

    assert response.status_code == 409
    assert "loading" in response.json()["detail"]


def _integrity_error(*, sqlstate: str, constraint_name: str) -> IntegrityError:
    """driver metadata를 실은 ``IntegrityError``를 만든다.

    라우터 판정이 문자열이 아니라 SQLSTATE + constraint 이름을 본다는 것을
    테스트에서도 그대로 밟기 위해, orig에 두 값을 그대로 얹는다
    (``_driver_constraint_identity``가 읽는 속성 이름 그대로다).
    """

    class _Orig(Exception):
        pass

    orig = _Orig(constraint_name)
    orig.sqlstate = sqlstate  # type: ignore[attr-defined]
    orig.constraint_name = constraint_name  # type: ignore[attr-defined]
    return IntegrityError("UPDATE ops.offline_uploads ...", {}, orig)


@pytest.mark.unit
@pytest.mark.parametrize(
    "constraint_name",
    ["ck_provider_dataset_active_write", "ck_provider_dataset_scope_active_write"],
)
def test_load_offline_upload_reports_inactive_membership_as_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    constraint_name: str,
) -> None:
    """비활성 dataset/operation은 상태 오류(409)지 500이 아니다.

    load 예약은 ``ops.import_job_datasets`` membership 행과 upload status 전이를
    같은 트랜잭션에서 쓴다 — 0091 가드가 둘 중 먼저 닿는 쪽을 23514로 거부하고
    constraint 이름이 갈린다. 두 이름을 모두 상태 오류로 옮겨야 운영자가 원인을 본다.
    """
    from kortravelmap.api.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(upload_id=upload_id)

    async def _reserve(_session: Any, *, upload_id: str) -> OfflineUpload:
        raise _integrity_error(sqlstate="23514", constraint_name=constraint_name)

    async def _launch(_request: Any, _upload_id: str, **_kwargs: Any) -> Any:
        raise AssertionError("inactive membership must not launch Dagster")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "reserve_offline_upload_load", _reserve)
    monkeypatch.setattr(router_mod, "launch_offline_upload_load", _launch)

    response = client.post("/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load")

    assert response.status_code == 409
    assert "비활성" in response.json()["detail"]


@pytest.mark.unit
def test_load_offline_upload_keeps_unrelated_check_violation_as_server_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """다른 CHECK 위반까지 409로 옮기면 진짜 버그가 상태 오류로 숨는다.

    판정을 "IntegrityError면 409"로 넓히면 이 테스트가 죽는다.
    """
    from kortravelmap.api.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(upload_id=upload_id)

    async def _reserve(_session: Any, *, upload_id: str) -> OfflineUpload:
        raise _integrity_error(
            sqlstate="23514", constraint_name="ck_offline_uploads_status"
        )

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "reserve_offline_upload_load", _reserve)

    with pytest.raises(IntegrityError):
        client.post("/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load")


@pytest.mark.unit
def test_validate_offline_upload_reports_inactive_membership_as_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """validation도 membership 행을 새로 만든다 — 같은 규칙으로 409."""
    from kortravelmap.api.routers import offline_uploads as router_mod

    upload = _upload(original_filename="features.csv", detected_format="csv")

    async def _get(_session: Any, _upload_id: str) -> OfflineUpload:
        return upload

    async def _run(_session: Any, _upload_id: str, **_kwargs: Any) -> Any:
        raise _integrity_error(
            sqlstate="23514", constraint_name="ck_provider_dataset_active_write"
        )

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: _FakeStore())
    monkeypatch.setattr(router_mod, "run_offline_upload_validation_job", _run)

    response = client.post(
        f"/v1/admin/offline-uploads/{upload.upload_id}/validate",
        json={
            "sample_size": 10,
            "column_mapping": {"name": "name", "lon": "lon", "lat": "lat"},
        },
    )

    assert response.status_code == 409
    assert "비활성" in response.json()["detail"]


@pytest.mark.unit
def test_load_offline_upload_keeps_reservation_pending_when_launch_is_ambiguous(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from kortravelmap.api.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(upload_id=upload_id)

    async def _reserve(_session: Any, *, upload_id: str) -> OfflineUpload:
        return _upload(
            upload_id=upload_id,
            state="loading",
            load_job_id="10000000-0000-0000-0000-000000000001",
        )

    async def _launch(_request: Any, _upload_id: str, *, run_id: str) -> Any:
        assert run_id == "10000000-0000-0000-0000-000000000001"
        raise HTTPException(status_code=502, detail="Dagster launch failed")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "reserve_offline_upload_load", _reserve)
    monkeypatch.setattr(router_mod, "launch_offline_upload_load", _launch)

    response = client.post("/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load")

    assert response.status_code == 502


@pytest.mark.unit
def test_load_offline_upload_terminal_replay_precedes_loading_state_lookup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.infra.domain_command_repo import DomainCommandRecord

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import offline_uploads as router_mod

    now = datetime(2026, 7, 31, tzinfo=UTC)
    replay_body = {
        "data": {"upload_id": "00000000-0000-0000-0000-000000000001"},
        "meta": {
            "duration_ms": 3,
            "dagster_run_id": "10000000-0000-0000-0000-000000000001",
            "dagster_status": "STARTED",
        },
    }
    record = DomainCommandRecord(
        command_id=1,
        actor="local-dev",
        operation="admin.offline-upload.load",
        idempotency_key="95000000-0000-4000-8000-000000000001",
        fingerprint_version=1,
        request_fingerprint="a" * 64,
        response_status=200,
        response_body=replay_body,
        response_headers={},
        claimed_at=now,
        completed_at=now,
    )

    async def _replay(*_args: Any, **_kwargs: Any) -> Any:
        raise domain_command_service.DomainCommandReplay(record)

    async def _get(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("terminal replay must precede loading row precondition")

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _replay)
    monkeypatch.setattr(router_mod, "get_offline_upload", _get)

    response = client.post(
        "/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load"
    )

    assert response.status_code == 200
    assert response.headers["Idempotency-Replayed"] == "true"
    assert response.json() == replay_body


@pytest.mark.unit
def test_preview_offline_upload_reads_csv_sample(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    body = b"name,lon,lat\nA,126.9,37.5\nB,127.0,37.6\n"
    storage_key = "offline/features.csv"
    checksum = hashlib.sha256(body).hexdigest()
    upload = _upload(
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        byte_size=len(body),
        checksum_sha256=checksum,
    )
    store = _FakeStore({storage_key: body})

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        assert upload_id == upload.upload_id
        return upload

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)

    response = client.get(f"/v1/admin/offline-uploads/{upload.upload_id}/preview")

    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["headers"] == ["name", "lon", "lat"]
    assert meta["rows_total"] == 2
    assert meta["sample_rows"][0]["name"] == "A"


@pytest.mark.unit
def test_validate_offline_upload_runs_validation_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    body = b"name,lon,lat,address\nA,126.9,37.5,\n"
    storage_key = "offline/features.csv"
    checksum = hashlib.sha256(body).hexdigest()
    upload = _upload(
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        byte_size=len(body),
        checksum_sha256=checksum,
    )
    validated_upload = _upload(
        state="validated",
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        byte_size=len(body),
        checksum_sha256=checksum,
        validation_job_id="00000000-0000-0000-0000-000000000101",
    )
    store = _FakeStore({storage_key: body})

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        assert upload_id == upload.upload_id
        return upload

    async def _run(_session: Any, upload_id: str, **kwargs: Any) -> Any:
        assert upload_id == upload.upload_id
        assert kwargs["store"] is store
        assert kwargs["column_mapping"]["name"] == "name"
        assert kwargs["sample_size"] == 100
        # T-VN-20 (ADR-066 D-2): operator는 인증 principal(local-dev)에서만 파생한다.
        assert kwargs["operator"] == "local-dev"
        # T-VN-33: provider/dataset_key는 upload 행이 아니라 provider_dataset_id에서
        # 유도한 표시명이다(실제 run_offline_upload_validation_job이 하는 일).
        return validate_offline_tabular_upload(
            validated_upload,
            body,
            provider=_PROVIDER_DISPLAY,
            dataset_key=_DATASET_KEY_DISPLAY,
            column_mapping=kwargs["column_mapping"],
            sample_size=kwargs["sample_size"],
            checksum_sha256=checksum,
        )

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "run_offline_upload_validation_job", _run)

    response = client.post(
        f"/v1/admin/offline-uploads/{upload.upload_id}/validate",
        json={
            "sample_size": 100,
            "column_mapping": {
                "name": "name",
                "lon": "lon",
                "lat": "lat",
                "address": "address",
            },
        },
    )

    assert response.status_code == 200
    body_json = response.json()
    assert body_json["data"]["status"] == "validated"
    assert body_json["meta"]["valid_rows"] == 1
    assert body_json["meta"]["issues"] == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (
            GeoAuthNotConfiguredError("geo trusted proxy 인증 미설정"),
            503,
            "GEO_AUTH_NOT_CONFIGURED",
        ),
        (
            GeoRequestError("kor-travel-geo 호출 실패"),
            502,
            "PROVIDER_ERROR",
        ),
    ],
)
def test_validate_offline_upload_keeps_typed_geo_problem_code(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    upload = _upload(
        original_filename="features.csv",
        detected_format="csv",
    )
    store = _FakeStore()

    async def _get(_session: Any, _upload_id: str) -> OfflineUpload:
        return upload

    async def _run(_session: Any, _upload_id: str, **_kwargs: Any) -> Any:
        raise error

    settings = KorTravelMapSettings(
        _env_file=None,
        kor_travel_geo_base_url="http://127.0.0.1:12501",
        kor_travel_geo_api_key=SecretStr("geo-public-key"),
    )
    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(
        router_mod,
        "_kor_travel_map_settings_from_request",
        lambda _request: settings,
    )
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "run_offline_upload_validation_job", _run)

    response = client.post(
        f"/v1/admin/offline-uploads/{upload.upload_id}/validate",
        json={
            "sample_size": 100,
            "column_mapping": {
                "name": "name",
                "lon": "lon",
                "lat": "lat",
                "address": "address",
            },
        },
    )

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == expected_code


@pytest.mark.unit
def test_validate_rejects_removed_operator_body_field(client: TestClient) -> None:
    # T-VN-20 (ADR-066 D-2): 제거된 body actor 필드를 보내면 extra="forbid"로 422.
    response = client.post(
        "/v1/admin/offline-uploads/upload-x/validate",
        json={
            "sample_size": 100,
            "operator": "attacker",
            "column_mapping": {"name": "name", "lon": "lon", "lat": "lat"},
        },
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_get_validation_returns_saved_import_job_payload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    upload = _upload(
        original_filename="features.csv",
        detected_format="csv",
        validation_job_id="00000000-0000-0000-0000-000000000101",
    )

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        assert upload_id == upload.upload_id
        return upload

    async def _job(_session: Any, job_id: str) -> ImportJob:
        assert job_id == upload.validation_job_id
        return ImportJob(
            job_id=job_id,
            kind="offline_upload_validate",
            payload={
                "job_id": job_id,
                "job_status": "done",
                "column_mapping": {"name": "name", "lon": "lon", "lat": "lat"},
                "parsed_format": "csv",
                "encoding": "utf-8",
                "delimiter": ",",
                "headers": ["name", "lon", "lat"],
                "sample_rows": [{"name": "A", "lon": "126.9", "lat": "37.5"}],
                "rows_total": 1,
                "rows_sampled": 1,
                "valid_rows": 1,
                "error_rows": 0,
                "issues": [],
                "bytes_read": 27,
                "checksum_sha256_actual": "b" * 64,
            },
            status="done",
            progress=100,
            current_stage=None,
            source_checksum=None,
            error_message=None,
        )

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "get_import_job", _job)

    response = client.get(f"/v1/admin/offline-uploads/{upload.upload_id}/validation")

    assert response.status_code == 200
    assert response.json()["meta"]["job_status"] == "done"


@pytest.mark.unit
def test_load_offline_upload_rejects_unloadable_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(upload_id=upload_id, state="loading")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)

    response = client.post("/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load")

    assert response.status_code == 409
    assert "loading" in response.json()["detail"]


@pytest.mark.unit
def test_load_offline_upload_rejects_loaded_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(upload_id=upload_id, state="loaded")

    async def _launch(_request: Any, _upload_id: str) -> object:
        raise AssertionError("loaded upload must not launch a Dagster run")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "launch_offline_upload_load", _launch)

    response = client.post("/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load")

    assert response.status_code == 409
    assert "loaded" in response.json()["detail"]


@pytest.mark.unit
def test_delete_offline_upload_removes_row_and_object(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    upload = _upload(state="loaded")
    store = _FakeStore({upload.storage_key: b'{"feature":{"feature_id":"f1"}}\n'})

    async def _delete(
        _session: Any,
        *,
        upload_id: str,
        command_id: int,
    ) -> OfflineUpload:
        assert upload_id == upload.upload_id
        assert command_id == 1
        return replace(upload, status="deleting", delete_command_id=command_id)

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        assert upload_id == upload.upload_id
        return upload

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "delete_offline_upload", _delete)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)

    response = client.delete(f"/v1/admin/offline-uploads/{upload.upload_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["upload_id"] == upload.upload_id
    assert body["data"]["status"] == "deleting"
    assert "duration_ms" in body["meta"]
    assert store.deleted == [upload.storage_key]
    assert store.objects == {}
    assert session.begin_count == 4


@pytest.mark.unit
@pytest.mark.parametrize("hook_fails", [False, True])
def test_delete_offline_upload_always_attempts_registry_audit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    hook_fails: bool,
) -> None:
    """DELETE는 registry에 삭제를 기록하고, 그 hook이 터져도 응답은 200이다.

    라우터는 hook을 ``file_registry.registry_guard``로 감싼다 —
    ``src/kortravelmap/infra/file_registry.py``의 ``except Exception``이 예외를 삼키고
    경고 로그만 남긴다. 그래서 hook이 DB에 거부당해도 **라우터 표면에서는 아무 신호가
    없다**(500이 아니라 200이다). 이 축이 없으면 hook 자체를 지워도 라우터 테스트가
    전부 초록이다.

    감사 기록이 실제로 DB에 남는지는 라우터 표면에서 볼 수 없으므로 실 DB 회귀가
    따로 있다 — ``tests/integration/test_offline_upload_load.py``의
    ``test_router_delete_records_managed_file_audit_for_inactive_dataset``.
    """
    from kortravelmap.infra import file_registry

    from kortravelmap.api.routers import offline_uploads as router_mod

    upload = _upload(state="loaded")
    store = _FakeStore({upload.storage_key: b'{"feature":{"feature_id":"f1"}}\n'})
    registered_paths: list[str] = []
    marked_deleted: list[int] = []

    async def _delete(
        _session: Any,
        *,
        upload_id: str,
        command_id: int,
    ) -> OfflineUpload:
        return replace(upload, status="deleting", delete_command_id=command_id)

    async def _get(_session: Any, _upload_id: str) -> OfflineUpload:
        return upload

    async def _register_file(_session: Any, **kwargs: Any) -> Any:
        registered_paths.append(str(kwargs["path"]))
        if hook_fails:
            raise _integrity_error(
                sqlstate="23514", constraint_name="ck_provider_dataset_active_write"
            )
        return SimpleNamespace(file_id=7)

    async def _mark_deleted(_session: Any, *, file_id: int, **_kwargs: Any) -> bool:
        marked_deleted.append(file_id)
        return True

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "delete_offline_upload", _delete)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(file_registry, "register_file", _register_file)
    monkeypatch.setattr(file_registry, "mark_deleted", _mark_deleted)

    response = client.delete(f"/v1/admin/offline-uploads/{upload.upload_id}")

    assert response.status_code == 200
    assert store.deleted == [upload.storage_key]
    # 성공/실패 어느 쪽이든 registry 등록은 **시도**돼야 한다.
    assert registered_paths == [upload.storage_key]
    # 등록이 터지면 삭제 표시까지 가지 못한다 — 그것이 감사 공백의 모양이다.
    assert marked_deleted == ([] if hook_fails else [7])


@pytest.mark.unit
def test_delete_offline_upload_retries_same_effect_after_ambiguous_store_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.core.exceptions import FileStoreError
    from kortravelmap.infra.domain_command_repo import DomainCommandClaim

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import offline_uploads as router_mod

    upload = _upload()
    deleted_rows: list[str] = []
    begin_calls = 0
    now = datetime(2026, 7, 31, tzinfo=UTC)

    class _FlakyStore(_FakeStore):
        async def delete_object(self, storage_key: str) -> None:
            attempt = len(self.deleted) + 1
            await super().delete_object(storage_key)
            if attempt == 1:
                raise FileStoreError(f"객체 저장소 삭제 실패: key={storage_key!r}")

    store = _FlakyStore({upload.storage_key: b"payload"})

    async def _delete(
        _session: Any,
        *,
        upload_id: str,
        command_id: int,
    ) -> OfflineUpload:
        deleted_rows.append(upload_id)
        return replace(upload, status="deleting", delete_command_id=command_id)

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        if begin_calls > 1:
            return replace(upload, status="deleting", delete_command_id=1)
        return upload

    async def _begin(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal begin_calls
        begin_calls += 1
        if begin_calls == 1:
            return domain_command_service.DomainCommandHandle(
                command_id=1,
                actor="local-dev",
                operation="admin.offline-upload.delete",
                idempotency_key="95000000-0000-4000-8000-000000000001",
                request_fingerprint="a" * 64,
            )
        raise domain_command_service.DomainCommandPending(
            DomainCommandClaim(
                command_id=1,
                actor="local-dev",
                operation="admin.offline-upload.delete",
                idempotency_key="95000000-0000-4000-8000-000000000001",
                fingerprint_version=1,
                request_fingerprint="a" * 64,
                created_at=now,
            )
        )

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _begin)
    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "delete_offline_upload", _delete)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)

    first = client.delete(f"/v1/admin/offline-uploads/{upload.upload_id}")

    assert first.status_code == 409
    assert first.json()["code"] == "IDEMPOTENCY_RESULT_PENDING"
    assert deleted_rows == []

    second = client.delete(f"/v1/admin/offline-uploads/{upload.upload_id}")

    assert second.status_code == 200
    assert second.json()["data"]["upload_id"] == upload.upload_id
    assert store.deleted == [upload.storage_key, upload.storage_key]
    assert deleted_rows == [upload.upload_id]


@pytest.mark.unit
def test_delete_offline_upload_terminal_replay_precedes_missing_row_lookup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.infra.domain_command_repo import DomainCommandRecord

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import offline_uploads as router_mod

    now = datetime(2026, 7, 31, tzinfo=UTC)
    replay_body = {
        "data": {"upload_id": "00000000-0000-0000-0000-000000000001"},
        "meta": {"duration_ms": 3},
    }
    record = DomainCommandRecord(
        command_id=1,
        actor="local-dev",
        operation="admin.offline-upload.delete",
        idempotency_key="95000000-0000-4000-8000-000000000001",
        fingerprint_version=1,
        request_fingerprint="a" * 64,
        response_status=200,
        response_body=replay_body,
        response_headers={},
        claimed_at=now,
        completed_at=now,
    )

    async def _replay(*_args: Any, **_kwargs: Any) -> Any:
        raise domain_command_service.DomainCommandReplay(record)

    async def _get(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("terminal replay must precede current row lookup")

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _replay)
    monkeypatch.setattr(router_mod, "get_offline_upload", _get)

    response = client.delete(
        "/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 200
    assert response.headers["Idempotency-Replayed"] == "true"
    assert response.json() == replay_body


@pytest.mark.unit
def test_delete_offline_upload_returns_404_for_missing_row(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import offline_uploads as router_mod

    store = _FakeStore()
    order: list[str] = []

    async def _get(_session: Any, upload_id: str) -> None:
        order.append("row")

    async def _begin(*_args: Any, **_kwargs: Any) -> Any:
        order.append("claim")
        return domain_command_service.DomainCommandHandle(
            command_id=1,
            actor="local-dev",
            operation="admin.offline-upload.delete",
            idempotency_key="95000000-0000-4000-8000-000000000001",
            request_fingerprint="a" * 64,
        )

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _begin)
    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)

    response = client.delete(
        "/v1/admin/offline-uploads/00000000-0000-0000-0000-00000000dead"
    )

    assert response.status_code == 404
    assert store.deleted == []
    assert order == ["claim", "row"]


@pytest.mark.unit
def test_delete_offline_upload_rejects_in_progress_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    store = _FakeStore()

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(upload_id=upload_id, state="loading")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)

    response = client.delete(
        "/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 409
    assert "loading" in response.json()["detail"]
    assert store.deleted == []


@pytest.mark.unit
def test_delete_offline_upload_blocked_when_destructive_disabled(
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    async def _delete(
        _session: Any,
        *,
        upload_id: str,
        command_id: int,
    ) -> OfflineUpload:
        raise AssertionError("destructive kill-switch must reject before repo delete")

    monkeypatch.setattr(router_mod, "delete_offline_upload", _delete)

    app = create_app(ApiSettings(admin_destructive_enabled=False))

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    guarded_client = TestClient(app)

    response = guarded_client.delete(
        "/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 403


@pytest.mark.unit
def test_load_offline_upload_rejects_csv_without_validation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(
            upload_id=upload_id,
            original_filename="features.csv",
            detected_format="csv",
            )

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)

    response = client.post("/v1/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load")

    assert response.status_code == 409
    assert "validate" in response.json()["detail"]
