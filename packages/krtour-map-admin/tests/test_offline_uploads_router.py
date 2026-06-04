"""``/admin/offline-uploads`` 라우터 단위 테스트."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.file_store import StoredObject
from krtour.map.infra.jobs_repo import ImportJob
from krtour.map.infra.offline_upload_repo import OfflineUpload, OfflineUploadPage
from krtour.map.offline_upload import validate_offline_tabular_upload

from krtour.map_admin.app import create_app
from krtour.map_admin.db import get_session
from krtour.map_admin.settings import AdminSettings


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
        self.calls: list[dict[str, Any]] = []
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
        return StoredObject(
            bucket="krtour-uploads",
            object_key=storage_key,
            byte_size=len(body),
            checksum_sha256="a" * 64,
        )


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(session: _FakeSession) -> TestClient:
    app = create_app(AdminSettings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _upload(
    *,
    upload_id: str = "00000000-0000-0000-0000-000000000001",
    state: str = "uploaded",
    storage_key: str | None = None,
    original_filename: str = "features.jsonl",
    detected_format: str = "jsonl",
    dataset_key: str = "offline_jsonl",
    byte_size: int = 123,
    checksum_sha256: str = "a" * 64,
    validation_job_id: str | None = None,
) -> OfflineUpload:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OfflineUpload(
        upload_id=upload_id,
        provider="offline-test-provider",
        dataset_key=dataset_key,
        sync_scope="default",
        original_filename=original_filename,
        storage_backend="rustfs",
        storage_key=storage_key or f"offline-uploads/{upload_id}/{original_filename}",
        byte_size=byte_size,
        checksum_sha256=checksum_sha256,
        detected_format=detected_format,
        detected_encoding="utf-8",
        state=state,
        validation_job_id=validation_job_id,
        load_job_id=None,
        created_by="pytest",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
def test_offline_upload_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/admin/offline-uploads" in spec["paths"]
    assert "/admin/offline-uploads/{upload_id}" in spec["paths"]
    assert "/admin/offline-uploads/{upload_id}/preview" in spec["paths"]
    assert "/admin/offline-uploads/{upload_id}/validate" in spec["paths"]
    assert "/admin/offline-uploads/{upload_id}/validation" in spec["paths"]
    assert "/admin/offline-uploads/{upload_id}/load" in spec["paths"]
    assert "OfflineUploadRecord" in spec["components"]["schemas"]


@pytest.mark.unit
def test_create_offline_upload_writes_object_and_metadata(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import offline_uploads as router_mod

    store = _FakeStore()

    async def _create(_session: Any, **kwargs: Any) -> OfflineUpload:
        assert kwargs["provider"] == "offline-test-provider"
        assert kwargs["dataset_key"] == "offline_jsonl"
        assert kwargs["storage_backend"] == "rustfs"
        assert kwargs["detected_format"] == "jsonl"
        assert kwargs["checksum_sha256"] == "a" * 64
        return _upload(
            upload_id=kwargs["upload_id"],
            storage_key=kwargs["storage_key"],
        )

    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "create_offline_upload", _create)

    response = client.post(
        "/admin/offline-uploads",
        data={
            "provider": "offline-test-provider",
            "dataset_key": "offline_jsonl",
            "sync_scope": "default",
            "created_by": "pytest",
        },
        files={
            "file": (
                "features.jsonl",
                b'{"feature":{"feature_id":"f1"}}\n',
                "application/x-ndjson",
            )
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["state"] == "uploaded"
    assert body["meta"]["bucket"] == "krtour-uploads"
    assert body["meta"]["object_key"].startswith("offline-uploads/")
    assert store.calls[0]["body"] == b'{"feature":{"feature_id":"f1"}}\n'
    assert store.calls[0]["metadata"]["provider"] == "offline-test-provider"
    assert session.begin_count == 1


@pytest.mark.unit
def test_create_offline_upload_accepts_csv(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import offline_uploads as router_mod

    store = _FakeStore()

    async def _create(_session: Any, **kwargs: Any) -> OfflineUpload:
        assert kwargs["detected_format"] == "csv"
        return _upload(
            upload_id=kwargs["upload_id"],
            storage_key=kwargs["storage_key"],
            original_filename="features.csv",
            detected_format="csv",
            dataset_key=kwargs["dataset_key"],
            byte_size=kwargs["byte_size"],
            checksum_sha256=kwargs["checksum_sha256"],
        )

    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "create_offline_upload", _create)

    response = client.post(
        "/admin/offline-uploads",
        data={"provider": "p", "dataset_key": "d"},
        files={"file": ("features.csv", b"name,lon,lat\nA,126.9,37.5\n", "text/csv")},
    )

    assert response.status_code == 201
    assert response.json()["data"]["detected_format"] == "csv"


@pytest.mark.unit
def test_create_rejects_file_over_configured_max_bytes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import offline_uploads as router_mod

    def _build_store(_settings: Any) -> _FakeStore:
        raise AssertionError("oversized upload must be rejected before object store")

    monkeypatch.setenv("KRTOUR_MAP_OFFLINE_UPLOAD_MAX_BYTES", "8")
    monkeypatch.setattr(router_mod, "build_offline_upload_store", _build_store)

    response = client.post(
        "/admin/offline-uploads",
        data={"provider": "p", "dataset_key": "d"},
        files={"file": ("features.jsonl", b"123456789", "application/x-ndjson")},
    )

    assert response.status_code == 413
    assert "최대 8 bytes" in response.json()["error"]["message"]


@pytest.mark.unit
def test_create_rejects_unsupported_format(client: TestClient) -> None:
    response = client.post(
        "/admin/offline-uploads",
        data={"provider": "p", "dataset_key": "d"},
        files={"file": ("features.xlsx", b"id,name\n1,a\n", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert "CSV/TSV" in response.json()["error"]["message"]


@pytest.mark.unit
def test_list_offline_uploads_passes_filters(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import offline_uploads as router_mod

    async def _list(_session: Any, **kwargs: Any) -> OfflineUploadPage:
        assert kwargs["state"] == "uploaded"
        assert kwargs["provider"] == "offline-test-provider"
        assert kwargs["dataset_key"] == "offline_jsonl"
        assert kwargs["limit"] == 25
        return OfflineUploadPage(items=(_upload(),), next_cursor="next")

    monkeypatch.setattr(router_mod, "list_offline_uploads", _list)

    response = client.get(
        "/admin/offline-uploads",
        params={
            "state": "uploaded",
            "provider": "offline-test-provider",
            "dataset_key": "offline_jsonl",
            "page_size": 25,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["upload_id"] == "00000000-0000-0000-0000-000000000001"
    assert body["next_cursor"] == "next"


@pytest.mark.unit
def test_load_offline_upload_launches_dagster(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(upload_id=upload_id)

    async def _launch(_request: Any, upload_id: str) -> Any:
        assert upload_id == "00000000-0000-0000-0000-000000000001"
        return router_mod._DagsterLaunch(run_id="dagster-run-1", status="QUEUED")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "launch_offline_upload_load", _launch)

    response = client.post(
        "/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["upload_id"] == "00000000-0000-0000-0000-000000000001"
    assert body["meta"]["dagster_run_id"] == "dagster-run-1"


@pytest.mark.unit
def test_preview_offline_upload_reads_csv_sample(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import offline_uploads as router_mod

    body = b"name,lon,lat\nA,126.9,37.5\nB,127.0,37.6\n"
    storage_key = "offline/features.csv"
    checksum = hashlib.sha256(body).hexdigest()
    upload = _upload(
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        dataset_key="offline_csv",
        byte_size=len(body),
        checksum_sha256=checksum,
    )
    store = _FakeStore({storage_key: body})

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        assert upload_id == upload.upload_id
        return upload

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)

    response = client.get(f"/admin/offline-uploads/{upload.upload_id}/preview")

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
    from krtour.map_admin.routers import offline_uploads as router_mod

    body = b"name,lon,lat,address\nA,126.9,37.5,\n"
    storage_key = "offline/features.csv"
    checksum = hashlib.sha256(body).hexdigest()
    upload = _upload(
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        dataset_key="offline_csv",
        byte_size=len(body),
        checksum_sha256=checksum,
    )
    validated_upload = _upload(
        state="validated",
        storage_key=storage_key,
        original_filename="features.csv",
        detected_format="csv",
        dataset_key="offline_csv",
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
        return validate_offline_tabular_upload(
            validated_upload,
            body,
            column_mapping=kwargs["column_mapping"],
            sample_size=kwargs["sample_size"],
            checksum_sha256=checksum,
        )

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "build_offline_upload_store", lambda _settings: store)
    monkeypatch.setattr(router_mod, "run_offline_upload_validation_job", _run)

    response = client.post(
        f"/admin/offline-uploads/{upload.upload_id}/validate",
        json={
            "sample_size": 100,
            "operator": "pytest",
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
    assert body_json["data"]["state"] == "validated"
    assert body_json["meta"]["valid_rows"] == 1
    assert body_json["meta"]["issues"] == []


@pytest.mark.unit
def test_get_validation_returns_saved_import_job_payload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import offline_uploads as router_mod

    upload = _upload(
        original_filename="features.csv",
        detected_format="csv",
        dataset_key="offline_csv",
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
                "job_state": "done",
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
            state="done",
            progress=100,
            current_stage=None,
            source_checksum=None,
            error_message=None,
        )

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)
    monkeypatch.setattr(router_mod, "get_import_job", _job)

    response = client.get(f"/admin/offline-uploads/{upload.upload_id}/validation")

    assert response.status_code == 200
    assert response.json()["meta"]["job_state"] == "done"


@pytest.mark.unit
def test_load_offline_upload_rejects_unloadable_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(upload_id=upload_id, state="loading")

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)

    response = client.post(
        "/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load"
    )

    assert response.status_code == 409
    assert "loading" in response.json()["error"]["message"]


@pytest.mark.unit
def test_load_offline_upload_rejects_csv_without_validation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import offline_uploads as router_mod

    async def _get(_session: Any, upload_id: str) -> OfflineUpload:
        return _upload(
            upload_id=upload_id,
            original_filename="features.csv",
            detected_format="csv",
            dataset_key="offline_csv",
        )

    monkeypatch.setattr(router_mod, "get_offline_upload", _get)

    response = client.post(
        "/admin/offline-uploads/00000000-0000-0000-0000-000000000001/load"
    )

    assert response.status_code == 409
    assert "validate" in response.json()["error"]["message"]
