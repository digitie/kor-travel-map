"""``/v1/admin/files`` router tests (개편 D).

레지스트리 DB 없이 라우터 계약을 검증한다 — get_session 의존성을 sentinel로
override하고 repo 함수를 monkeypatch해 wiring/필터 검증/purge 게이트만 확인한다.
DB 왕복 검증은 infra integration test 소관.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_read_snapshot_session, get_session
from kortravelmap.api.settings import ApiSettings


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def begin(self) -> _Tx:
        return _Tx()


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
    app.dependency_overrides[get_session] = _FakeSession
    app.dependency_overrides[get_read_snapshot_session] = _FakeSession
    return app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from kortravelmap.api import domain_command_service

    app = _make_app(tmp_path)
    monkeypatch.setattr(
        domain_command_service,
        "begin_domain_command",
        AsyncMock(
            return_value=domain_command_service.DomainCommandHandle(
                command_id=1,
                actor="local-dev",
                operation="admin.managed-file.rescan",
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
    return TestClient(
        app,
        headers={"Idempotency-Key": "95000000-0000-4000-8000-000000000001"},
    )


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
            # dataset deep-link identity는 provider_dataset_id다(ADR-088) —
            # provider/dataset_key 자연키 사본은 삭제됐다.
            provider_dataset_id=7,
            origin_dagster_run_id=None,
        )
    )

    assert [(link.rel, link.href) for link in links] == [
        ("import-job", "/ops/pipeline?execution=import_job:job%2F1"),
        ("provider", "/ops/datasets?provider_dataset_id=7"),
    ]


@pytest.mark.unit
def test_backup_file_link_targets_existing_backup_page() -> None:
    from kortravelmap.api.routers.admin_files import _build_links

    links = _build_links(
        SimpleNamespace(
            origin_import_job_id=None,
            upload_id=None,
            location="backup_root",
            kind="backup",
            path="nested/기록 1.dump",
            provider_dataset_id=None,
            origin_dagster_run_id=None,
        )
    )

    # 백업 UI는 목록 페이지에서 선택한다. 파일 경로를 상세 route로 만들지 않는다.
    assert [(link.rel, link.href) for link in links] == [("backup", "/admin/backups")]


@pytest.mark.unit
def test_offline_upload_link_targets_existing_list_page() -> None:
    from kortravelmap.api.routers.admin_files import _build_links

    links = _build_links(
        SimpleNamespace(
            origin_import_job_id=None,
            upload_id="0193f2a4-7c1e-7d3a-9b2c-5e6f7a8b9c0d",
            location="object_store",
            kind="offline_upload",
            path="offline-uploads/0193f2a4/features.jsonl",
            provider_dataset_id=None,
            origin_dagster_run_id=None,
        )
    )

    # 업로드별 상세 route는 없다. 목록 페이지에서 선택하므로 upload_id를 경로에 넣지 않는다.
    assert [(link.rel, link.href) for link in links] == [
        ("offline-upload", "/admin/offline-uploads")
    ]


_FRONTEND_APP = (
    Path(__file__).resolve().parents[2] / "kor-travel-map-admin" / "frontend" / "src" / "app"
)


def _frontend_page_routes() -> list[tuple[str, ...]]:
    """App Router ``page.tsx``의 URL 경로. route group ``(x)``는 URL에 없다."""

    return [
        tuple(
            part
            for part in page.parent.relative_to(_FRONTEND_APP).parts
            if not (part.startswith("(") and part.endswith(")"))
        )
        for page in _FRONTEND_APP.rglob("page.tsx")
    ]


def _route_matches(route: tuple[str, ...], segments: tuple[str, ...]) -> bool:
    for index, part in enumerate(route):
        if part.startswith(("[[...", "[...")):
            return len(segments) > index or part.startswith("[[...")
        if index >= len(segments):
            return False
        if not (part.startswith("[") and part.endswith("]")) and part != segments[index]:
            return False
    return len(route) == len(segments)


@pytest.mark.unit
def test_every_managed_file_link_href_has_a_frontend_page() -> None:
    """서버가 조립한 deep-link는 프론트에 실제 페이지가 있어야 한다(없으면 prefetch·클릭이 404).

    모든 링크 근원을 한 행에 채워 ``_build_links``가 내는 href를 전부 본다. 함수가 새 속성을
    읽기 시작하면 ``SimpleNamespace``가 AttributeError로 이 테스트를 다시 쓰게 만든다.
    """
    from urllib.parse import urlsplit

    from kortravelmap.api.routers.admin_files import _build_links

    routes = _frontend_page_routes()
    assert ("admin", "offline-uploads") in routes, (
        f"frontend app 경로를 못 찾았다: {_FRONTEND_APP}"
    )
    links = _build_links(
        SimpleNamespace(
            origin_import_job_id="job/1",
            upload_id="0193f2a4-7c1e-7d3a-9b2c-5e6f7a8b9c0d",
            location="backup_root",
            kind="backup",
            path="nested/기록 1.dump",
            provider_dataset_id=7,
            origin_dagster_run_id="0f1e2d3c4b5a69788796a5b4c3d2e1f0",
        )
    )
    hrefs = {link.rel: link.href for link in links if link.href is not None}
    # 본 것에 하한을 건다: 링크 근원 넷이 모두 href를 냈는지 먼저 본다.
    assert set(hrefs) == {"import-job", "offline-upload", "backup", "provider"}
    missing = {
        rel: href
        for rel, href in hrefs.items()
        if not any(
            _route_matches(route, tuple(filter(None, urlsplit(href).path.split("/"))))
            for route in routes
        )
    }
    assert not missing, f"page.tsx가 없는 deep-link: {missing}"


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
