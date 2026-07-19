"""``/v1/admin/files`` router tests (개편 D).

레지스트리 DB 없이 라우터 계약을 검증한다 — get_session 의존성을 sentinel로
override하고 repo 함수를 monkeypatch해 wiring/필터 검증/purge 게이트만 확인한다.
DB 왕복 검증은 infra integration test 소관.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings


def _make_app(tmp_path: Path, **overrides: Any) -> Any:
    overrides.setdefault("admin_destructive_enabled", True)
    settings = ApiSettings(
        admin_proxy_secret=None,
        backup_root=tmp_path,
        backup_project_root=tmp_path,
        backup_command_enabled=False,
        **overrides,
    )
    app = create_app(settings)
    # get_session은 실제 DB 커넥션을 만든다 — sentinel로 대체(라우터가 세션을
    # 실제로 쓰기 전에 검증/게이트에서 분기하는 경로만 테스트).
    app.dependency_overrides[get_session] = lambda: SimpleNamespace()
    return app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(_make_app(tmp_path))


@pytest.mark.unit
def test_admin_files_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]

    assert "/v1/admin/files" in paths
    assert "/v1/admin/files/summary" in paths
    assert "/v1/admin/files/{file_id}" in paths
    assert "/v1/admin/files/{file_id}/events" in paths
    assert "post" in paths["/v1/admin/files/rescan"]
    assert "post" in paths["/v1/admin/files/{file_id}/purge"]


@pytest.mark.unit
def test_managed_file_links_use_canonical_admin_pages() -> None:
    from kortravelmap.api.routers.admin_files import _build_links

    links = _build_links(
        SimpleNamespace(
            origin_import_job_id="job/1",
            upload_id=None,
            location="object_store",
            kind="provider_source",
            path="source/file.csv",
            provider="provider/name",
            origin_dagster_run_id=None,
        )
    )

    assert [(link.rel, link.href) for link in links] == [
        ("import-job", "/ops/pipeline?execution=import_job:job%2F1"),
        ("provider", "/ops/datasets?provider=provider%2Fname"),
    ]


@pytest.mark.unit
def test_list_rejects_unknown_status(client: TestClient) -> None:
    # enum 검증은 세션 사용 전에 422로 끊는다.
    response = client.get("/v1/admin/files", params={"status": "bogus"})

    assert response.status_code == 422
    assert "bogus" in response.json()["detail"]


@pytest.mark.unit
def test_list_rejects_unknown_location(client: TestClient) -> None:
    response = client.get("/v1/admin/files", params={"location": "nope"})

    assert response.status_code == 422


@pytest.mark.unit
def test_purge_missing_file_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra import file_registry

    async def _none(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(file_registry, "get_managed_file", _none)
    response = client.post("/v1/admin/files/999/purge")

    assert response.status_code == 404


@pytest.mark.unit
def test_purge_rejects_non_orphan(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra import file_registry

    async def _active(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            file_id=1, storage_backend="s3", status="active", orphan_reason=None
        )

    monkeypatch.setattr(file_registry, "get_managed_file", _active)
    response = client.post("/v1/admin/files/1/purge")

    assert response.status_code == 409


@pytest.mark.unit
def test_purge_rejects_non_purgeable_orphan_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra import file_registry

    async def _orphan(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            file_id=1,
            storage_backend="s3",
            status="orphan",
            orphan_reason="temp_expired",  # purge 불가 사유
        )

    monkeypatch.setattr(file_registry, "get_managed_file", _orphan)
    response = client.post("/v1/admin/files/1/purge")

    assert response.status_code == 409


@pytest.mark.unit
def test_purge_requires_destructive_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.infra import file_registry

    async def _orphan(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            file_id=1,
            storage_backend="s3",
            status="orphan",
            orphan_reason="zombie_object",
        )

    monkeypatch.setattr(file_registry, "get_managed_file", _orphan)
    app = _make_app(tmp_path, admin_destructive_enabled=False)
    response = TestClient(app).post("/v1/admin/files/1/purge")

    # kill-switch가 꺼져 있으면 게이트에서 403 — 게이트가 raise 시 gate 통과 안 함.
    assert response.status_code == 403
