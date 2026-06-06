"""``/admin/backups`` router tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from krtour.map_admin.app import create_app
from krtour.map_admin.settings import AdminSettings


def _write_artifact(root: Path, backup_id: str = "backup-1") -> None:
    backup_dir = root / backup_id
    (backup_dir / "postgres").mkdir(parents=True)
    (backup_dir / "rustfs").mkdir()
    (backup_dir / "meta").mkdir()
    (backup_dir / "postgres" / "krtour_map.dump").write_bytes(b"app")
    (backup_dir / "postgres" / "krtour_map_dagster.dump").write_bytes(b"dagster")
    (backup_dir / "rustfs" / "rustfs-data.tar.gz").write_bytes(b"rustfs")
    (backup_dir / "meta" / "manifest.json").write_text(
        json.dumps(
            {
                "backup_id": backup_id,
                "created_at_utc": "2026-06-06T02:00:00Z",
                "mode": "docker-compose-cold-backup",
                "components": {"postgres_app": "postgres/krtour_map.dump"},
                "databases": {"app": "krtour_map"},
                "object_storage": {"feature_bucket": "krtour-map"},
            }
        ),
        encoding="utf-8",
    )
    (backup_dir / "meta" / "SHA256SUMS").write_text(
        "a  postgres/krtour_map.dump\n",
        encoding="utf-8",
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    _write_artifact(tmp_path)
    return TestClient(
        create_app(
            AdminSettings(
                backup_root=tmp_path,
                backup_project_root=tmp_path,
                backup_command_enabled=False,
            )
        )
    )


@pytest.mark.unit
def test_admin_backup_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()

    assert "/admin/backups" in spec["paths"]
    assert "/admin/backups/{backup_id}" in spec["paths"]
    assert "/admin/restore/{backup_id}" in spec["paths"]
    assert "/admin/restore/{backup_id}/swap" in spec["paths"]
    assert "/admin/backups/restore/{backup_id}" not in spec["paths"]


@pytest.mark.unit
def test_list_backups_reads_artifacts(client: TestClient) -> None:
    response = client.get("/admin/backups")

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["count"] == 1
    assert body["data"]["items"][0]["backup_id"] == "backup-1"
    assert body["data"]["items"][0]["manifest_status"] == "ok"


@pytest.mark.unit
def test_create_backup_defaults_to_plan_only(client: TestClient) -> None:
    response = client.post("/admin/backups", json={"backup_id": "manual"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["operation"] == "backup"
    assert body["data"]["status"] == "planned"
    assert body["data"]["command"]["enabled"] is False
    assert body["data"]["command"]["env"]["KRTOUR_MAP_BACKUP_ID"] == "manual"


@pytest.mark.unit
def test_get_backup_rejects_invalid_id(client: TestClient) -> None:
    response = client.get("/admin/backups/bad!")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_BACKUP_ID"


@pytest.mark.unit
def test_execute_backup_requires_opt_in(client: TestClient) -> None:
    response = client.post(
        "/admin/backups",
        json={"backup_id": "manual", "execute": True},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "BACKUP_COMMAND_DISABLED"


@pytest.mark.unit
def test_execute_backup_uses_command_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from krtour.map_admin.routers import admin_backups as router_mod

    _write_artifact(tmp_path, "manual")
    app = create_app(
        AdminSettings(
            backup_root=tmp_path,
            backup_project_root=tmp_path,
            backup_command_enabled=True,
        )
    )
    seen: dict[str, Any] = {}

    async def _fake_run(plan: Any, *, timeout_seconds: float) -> Any:
        seen["plan"] = plan
        seen["timeout_seconds"] = timeout_seconds
        return router_mod._CommandResult(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(router_mod, "_run_command", _fake_run)
    response = TestClient(app).post(
        "/admin/backups",
        json={"backup_id": "manual", "execute": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "completed"
    assert body["data"]["artifact"]["backup_id"] == "manual"
    assert seen["plan"].env["KRTOUR_MAP_BACKUP_ID"] == "manual"


@pytest.mark.unit
def test_restore_plan_and_swap_boundary(client: TestClient) -> None:
    restore = client.post(
        "/admin/restore/backup-1",
        json={"recreate": True, "skip_rustfs": True},
    )
    assert restore.status_code == 200
    restore_body = restore.json()
    assert restore_body["data"]["operation"] == "restore"
    assert restore_body["data"]["status"] == "planned"
    assert restore_body["data"]["command"]["env"]["KRTOUR_MAP_RESTORE_RECREATE"] == "1"
    assert restore_body["data"]["command"]["env"]["KRTOUR_MAP_RESTORE_SKIP_RUSTFS"] == "1"

    swap = client.post("/admin/restore/backup-1/swap", json={})
    assert swap.status_code == 200
    swap_body = swap.json()
    assert swap_body["data"]["operation"] == "swap"
    assert swap_body["data"]["status"] == "manual_required"
