"""``/admin/offline-uploads`` 라우터 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from krtour.map.infra.file_store import StoredObject
from krtour.map.infra.offline_upload_repo import OfflineUpload, OfflineUploadPage

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
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
) -> OfflineUpload:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return OfflineUpload(
        upload_id=upload_id,
        provider="offline-test-provider",
        dataset_key="offline_jsonl",
        sync_scope="default",
        original_filename="features.jsonl",
        storage_backend="rustfs",
        storage_key=storage_key or f"offline-uploads/{upload_id}/features.jsonl",
        byte_size=123,
        checksum_sha256="a" * 64,
        detected_format="jsonl",
        detected_encoding="utf-8",
        state=state,
        validation_job_id=None,
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
def test_create_rejects_unsupported_format(client: TestClient) -> None:
    response = client.post(
        "/admin/offline-uploads",
        data={"provider": "p", "dataset_key": "d"},
        files={"file": ("features.csv", b"id,name\n1,a\n", "text/csv")},
    )

    assert response.status_code == 422
    assert "JSON/JSONL" in response.json()["detail"]


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
    assert "loading" in response.json()["detail"]
