"""``/v1/admin/backups`` router tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import AdminProxyContext, require_admin_frontend
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings

_IDEMPOTENCY_HEADERS = {
    "Idempotency-Key": "96000000-0000-4000-8000-000000000001"
}


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def begin(self) -> _Tx:
        return _Tx()


@pytest.fixture(autouse=True)
def _domain_command_fakes(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    from kortravelmap.infra.domain_command_execution_repo import (
        BackupCommandExecution,
    )

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_backups as router_mod

    next_command_id = {"value": 0}

    async def _begin(_session: Any, **kwargs: Any) -> Any:
        next_command_id["value"] += 1
        return domain_command_service.DomainCommandHandle(
            command_id=next_command_id["value"],
            actor=str(kwargs["actor"]),
            operation=str(kwargs["operation"]),
            idempotency_key=str(kwargs["idempotency_key"]),
            request_fingerprint="a" * 64,
        )

    async def _create(_session: Any, **kwargs: Any) -> BackupCommandExecution:
        return BackupCommandExecution(
            command_id=int(kwargs["command_id"]),
            effect_kind=str(kwargs["effect_kind"]),
            effect_token=str(kwargs["effect_token"]),
            phase="prepared",
            backup_id=str(kwargs["backup_id"]),
            app_db=kwargs["app_db"],
            dagster_db=kwargs["dagster_db"],
            rustfs_volume=kwargs["rustfs_volume"],
            marker_key=str(kwargs["marker_key"]),
            input_digest=str(kwargs["input_digest"]),
            prepared_result=kwargs["prepared_result"],
            output_digest=None,
            marker_sha256=None,
            prepared_at=datetime(2026, 7, 31, tzinfo=UTC),
            effect_started_at=None,
            effect_completed_at=None,
        )

    async def _start(
        _session: Any,
        command_id: int,
    ) -> BackupCommandExecution:
        execution = await _create(
            _session,
            command_id=command_id,
            effect_kind="create",
            backup_id="unused",
            app_db=None,
            dagster_db=None,
            rustfs_volume=None,
            marker_key=f"command-{command_id}",
            input_digest="a" * 64,
            prepared_result=None,
        )
        return replace(
            execution,
            phase="effect_started",
            effect_started_at=datetime(2026, 7, 31, tzinfo=UTC),
        )

    executions: dict[int, BackupCommandExecution] = {}

    async def _create_and_remember(
        _session: Any, **kwargs: Any
    ) -> BackupCommandExecution:
        execution = await _create(_session, **kwargs)
        executions[execution.command_id] = execution
        return execution

    async def _start_remembered(
        _session: Any, command_id: int
    ) -> BackupCommandExecution:
        execution = replace(
            executions[command_id],
            phase="effect_started",
            effect_started_at=datetime(2026, 7, 31, tzinfo=UTC),
        )
        executions[command_id] = execution
        return execution

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _begin)
    monkeypatch.setattr(
        domain_command_service,
        "complete_domain_command",
        AsyncMock(),
    )
    monkeypatch.setattr(
        router_mod,
        "create_backup_command_execution",
        _create_and_remember,
    )
    monkeypatch.setattr(
        router_mod,
        "get_backup_command_execution",
        AsyncMock(side_effect=lambda _session, command_id: executions.get(command_id)),
    )
    monkeypatch.setattr(
        router_mod,
        "start_backup_command_effect",
        _start_remembered,
    )
    monkeypatch.setattr(
        router_mod,
        "complete_backup_command_effect",
        AsyncMock(),
    )
    monkeypatch.setattr(
        router_mod,
        "_acquire_docker_effect_fence",
        AsyncMock(),
    )
    monkeypatch.setattr(
        router_mod,
        "_release_docker_effect_fence",
        AsyncMock(),
    )

    @asynccontextmanager
    async def _lock(_engine: Any) -> AsyncIterator[None]:
        yield

    proof_calls: dict[int, int] = {}

    async def _marker_proof(
        _settings: Any,
        prepared: Any,
        **_kwargs: Any,
    ) -> str | None:
        command_id = int(prepared.command.command_id)
        proof_calls[command_id] = proof_calls.get(command_id, 0) + 1
        return "b" * 64 if proof_calls[command_id] > 1 else None

    async def _write_marker(*_args: Any, **_kwargs: Any) -> str:
        return "b" * 64

    async def _marker_proof_variants(
        _settings: Any,
        prepared: Any,
        **_kwargs: Any,
    ) -> str | None:
        command_id = int(prepared.command.command_id)
        proof_calls[command_id] = proof_calls.get(command_id, 0) + 1
        return "c" * 64 if proof_calls[command_id] > 1 else None

    if request.node.name != "test_maintenance_lock_is_exact_fail_fast_and_exactly_unlocked":
        monkeypatch.setattr(router_mod, "_maintenance_lock", _lock)
    monkeypatch.setattr(router_mod, "_marker_proof", _marker_proof)
    monkeypatch.setattr(router_mod, "_write_marker", _write_marker)
    monkeypatch.setattr(
        router_mod,
        "_marker_proof_variants",
        _marker_proof_variants,
    )
    monkeypatch.setattr(
        router_mod,
        "reserve_backup_destination",
        lambda *_args, **_kwargs: "d" * 64,
    )
    monkeypatch.setattr(
        router_mod,
        "swap_output_proof",
        lambda *_args, **_kwargs: {"swap": "proof"},
    )


def _write_artifact(root: Path, backup_id: str = "backup-1") -> None:
    backup_dir = root / backup_id
    (backup_dir / "postgres").mkdir(parents=True)
    (backup_dir / "rustfs").mkdir()
    (backup_dir / "meta").mkdir()
    (backup_dir / "postgres" / "kor_travel_map.dump").write_bytes(b"app")
    (backup_dir / "postgres" / "kor_travel_map_dagster.dump").write_bytes(b"dagster")
    (backup_dir / "rustfs" / "rustfs-data.tar.gz").write_bytes(b"rustfs")
    (backup_dir / "meta" / "manifest.json").write_text(
        json.dumps(
            {
                "backup_id": backup_id,
                "created_at_utc": "2026-06-06T02:00:00Z",
                "mode": "docker-compose-cold-backup",
                "components": {"postgres_app": "postgres/kor_travel_map.dump"},
                "databases": {"app": "kor_travel_map"},
                "object_storage": {"feature_bucket": "kor-travel-map"},
            }
        ),
        encoding="utf-8",
    )
    checksum_lines = []
    for relative_path in (
        "postgres/kor_travel_map.dump",
        "postgres/kor_travel_map_dagster.dump",
        "rustfs/rustfs-data.tar.gz",
    ):
        digest = hashlib.sha256(
            (backup_dir / relative_path).read_bytes()
        ).hexdigest()
        checksum_lines.append(f"{digest}  {relative_path}")
    (backup_dir / "meta" / "SHA256SUMS").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_lock_is_exact_fail_fast_and_exactly_unlocked() -> None:
    from fastapi import HTTPException
    from kortravelmap.infra.advisory_lock import advisory_lock_key

    from kortravelmap.api.routers import admin_backups as router_mod

    class _Connection:
        def __init__(self, acquired: bool) -> None:
            self.acquired = acquired
            self.calls: list[tuple[str, dict[str, int]]] = []

        async def execute(
            self,
            statement: Any,
            parameters: dict[str, int],
        ) -> Any:
            sql = str(statement)
            self.calls.append((sql, parameters))
            value = self.acquired if "pg_try" in sql else True
            return SimpleNamespace(scalar_one=lambda: value)

    class _Connect:
        def __init__(self, connection: _Connection) -> None:
            self.connection = connection

        async def __aenter__(self) -> _Connection:
            return self.connection

        async def __aexit__(self, *_exc: object) -> None:
            return None

    class _Engine:
        def __init__(self, connection: _Connection) -> None:
            self.connection = connection

        def connect(self) -> _Connect:
            return _Connect(self.connection)

    connection = _Connection(acquired=True)
    async with router_mod._maintenance_lock(_Engine(connection)):  # type: ignore[arg-type]
        pass
    expected_id = advisory_lock_key("maintenance:backup-restore")
    assert [call[0] for call in connection.calls] == [
        "SELECT pg_try_advisory_lock(:lock_id)",
        "SELECT pg_advisory_unlock(:lock_id)",
    ]
    assert [call[1]["lock_id"] for call in connection.calls] == [
        expected_id,
        expected_id,
    ]

    busy = _Connection(acquired=False)
    with pytest.raises(HTTPException) as raised:
        async with router_mod._maintenance_lock(_Engine(busy)):  # type: ignore[arg-type]
            pass
    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "BACKUP_MAINTENANCE_BUSY"
    assert len(busy.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["cancellation", "timeout"])
async def test_command_abort_detaches_supervised_effect(
    tmp_path: Path,
    trigger: str,
) -> None:
    from kortravelmap.api.routers import admin_backups as router_mod

    pid_file = tmp_path / "supervised.pid"
    completed_file = tmp_path / "supervised-completed"
    command = (
        f"trap '' TERM INT; echo $$ > {pid_file}; "
        f"sleep 0.5; touch {completed_file}"
    )
    plan = router_mod.BackupCommandPlan(
        cwd=str(tmp_path),
        command=["bash", "-c", command],
        env={},
        enabled=True,
    )
    task = asyncio.create_task(
        router_mod._run_command(
            plan,
            timeout_seconds=30.0 if trigger == "cancellation" else 0.2,
        )
    )
    for _ in range(200):
        if pid_file.exists():
            break
        await asyncio.sleep(0.01)
    assert pid_file.exists()
    supervised_pid = int(pid_file.read_text(encoding="utf-8"))

    if trigger == "cancellation":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(HTTPException) as raised:
            await task
        assert raised.value.status_code == 504
        assert raised.value.detail["code"] == "BACKUP_COMMAND_TIMEOUT"

    assert router_mod._SUPERVISED_COMMAND_COMMUNICATIONS
    os.kill(supervised_pid, 0)
    await asyncio.wait_for(
        asyncio.gather(*tuple(router_mod._SUPERVISED_COMMAND_COMMUNICATIONS)),
        timeout=3.0,
    )
    assert completed_file.exists()
    assert not router_mod._SUPERVISED_COMMAND_COMMUNICATIONS
    with pytest.raises(ProcessLookupError):
        os.kill(supervised_pid, 0)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    _write_artifact(tmp_path)
    return TestClient(
        create_app(
            ApiSettings(
                admin_destructive_enabled=True,
                admin_proxy_secret=None,
                backup_root=tmp_path,
                backup_project_root=tmp_path,
                backup_command_enabled=False,
            )
        ),
        headers=_IDEMPOTENCY_HEADERS,
    )


@pytest.mark.unit
def test_admin_backup_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()

    assert "/v1/admin/backups" in spec["paths"]
    assert "/v1/admin/backups/{backup_id}" in spec["paths"]
    assert "delete" in spec["paths"]["/v1/admin/backups/{backup_id}"]
    assert "/v1/admin/restore/{backup_id}" in spec["paths"]
    assert "/v1/admin/restore/{backup_id}/swap" in spec["paths"]
    assert "/v1/admin/backups/restore/{backup_id}" not in spec["paths"]
    assert "operator" not in spec["components"]["schemas"]["RestoreSwapRequest"][
        "properties"
    ]


@pytest.mark.unit
def test_list_backups_reads_artifacts(client: TestClient) -> None:
    response = client.get("/v1/admin/backups")

    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]["items"]) == 1
    assert body["data"]["backup_root"]
    assert body["data"]["command_enabled"] is False
    assert body["data"]["items"][0]["backup_id"] == "backup-1"
    assert body["data"]["items"][0]["manifest_status"] == "ok"


@pytest.mark.unit
def test_create_backup_defaults_to_plan_only(client: TestClient) -> None:
    response = client.post("/v1/admin/backups", json={"backup_id": "manual"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["operation"] == "backup"
    assert body["data"]["status"] == "planned"
    assert body["data"]["command"]["enabled"] is False
    assert body["data"]["command"]["env"]["KOR_TRAVEL_MAP_BACKUP_ID"] == "manual"


@pytest.mark.unit
def test_get_backup_rejects_invalid_id(client: TestClient) -> None:
    response = client.get("/v1/admin/backups/bad!")

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_BACKUP_ID"


@pytest.mark.unit
def test_delete_backup_removes_artifact(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "delete-me")
    client = TestClient(
        create_app(
            ApiSettings(
                admin_destructive_enabled=True,
                admin_proxy_secret=None,
                backup_root=tmp_path,
                backup_project_root=tmp_path,
                backup_command_enabled=False,
            )
        ),
        headers=_IDEMPOTENCY_HEADERS,
    )

    response = client.delete("/v1/admin/backups/delete-me")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["deleted"] is True
    assert body["data"]["item"]["backup_id"] == "delete-me"
    assert not (tmp_path / "delete-me").exists()
    assert client.get("/v1/admin/backups/delete-me").status_code == 404


@pytest.mark.unit
def test_delete_missing_backup_does_not_leave_new_command_claim(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            ApiSettings(
                admin_destructive_enabled=True,
                admin_proxy_secret=None,
                backup_root=tmp_path,
                backup_project_root=tmp_path,
            )
        ),
        headers=_IDEMPOTENCY_HEADERS,
    )

    response = client.delete("/v1/admin/backups/missing")

    assert response.status_code == 404
    assert response.json()["code"] == "BACKUP_NOT_FOUND"


@pytest.mark.unit
def test_delete_backup_requires_destructive_gate(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "keep-me")
    client = TestClient(
        create_app(
            ApiSettings(
                admin_destructive_enabled=False,
                admin_proxy_secret=None,
                backup_root=tmp_path,
                backup_project_root=tmp_path,
                backup_command_enabled=False,
            )
        ),
        headers=_IDEMPOTENCY_HEADERS,
    )

    response = client.delete("/v1/admin/backups/keep-me")

    assert response.status_code == 403
    assert (tmp_path / "keep-me").is_dir()


@pytest.mark.unit
def test_execute_backup_requires_opt_in(client: TestClient) -> None:
    response = client.post(
        "/v1/admin/backups",
        json={"backup_id": "manual", "execute": True},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "BACKUP_COMMAND_DISABLED"


@pytest.mark.unit
def test_execute_backup_reports_missing_command_cwd(tmp_path: Path) -> None:
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
            backup_root=tmp_path,
            backup_project_root=tmp_path / "missing-runner",
            backup_command_enabled=True,
        )
    )
    response = TestClient(app, headers=_IDEMPOTENCY_HEADERS).post(
        "/v1/admin/backups",
        json={"backup_id": "manual", "execute": True},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "BACKUP_COMMAND_UNAVAILABLE"
    assert body["details"]["cwd"].endswith("missing-runner")


@pytest.mark.unit
def test_execute_backup_uses_command_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_backups as router_mod

    _write_artifact(tmp_path, "manual")
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
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
    response = TestClient(app, headers=_IDEMPOTENCY_HEADERS).post(
        "/v1/admin/backups",
        json={"backup_id": "manual", "execute": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "completed"
    assert body["data"]["artifact"]["backup_id"] == "manual"
    assert seen["plan"].env["KOR_TRAVEL_MAP_BACKUP_ID"] == "manual"
    assert len(seen["plan"].env["KOR_TRAVEL_MAP_COMMAND_EFFECT_TOKEN"]) == 64
    assert seen["plan"].env["KOR_TRAVEL_MAP_COMMAND_FENCE_PREACQUIRED"] == "1"
    assert "KOR_TRAVEL_MAP_MAINTENANCE_LOCK_HELD" not in seen["plan"].env


@pytest.mark.unit
def test_foreign_fence_keeps_new_command_prepared_and_runs_no_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_backups as router_mod

    start_effect = AsyncMock()

    async def _foreign_fence(_settings: Any, prepared: Any) -> None:
        raise router_mod._effect_reconciliation_required(
            prepared,
            reason="foreign Docker fence",
        )

    monkeypatch.setattr(
        router_mod,
        "_acquire_docker_effect_fence",
        _foreign_fence,
    )
    monkeypatch.setattr(
        router_mod,
        "start_backup_command_effect",
        start_effect,
    )
    run = AsyncMock()
    monkeypatch.setattr(router_mod, "_run_command", run)
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
            backup_root=tmp_path,
            backup_project_root=tmp_path,
            backup_command_enabled=True,
        )
    )
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    before_paths = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    response = TestClient(app, headers=_IDEMPOTENCY_HEADERS).post(
        "/v1/admin/backups",
        json={"backup_id": "fenced", "execute": True},
    )
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    after_paths = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    assert response.status_code == 409
    assert response.json()["code"] == (
        "BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED"
    )
    assert after == before
    assert after_paths == before_paths
    assert not (tmp_path / "fenced").exists()
    start_effect.assert_not_awaited()
    run.assert_not_awaited()


@pytest.mark.unit
def test_execute_backup_maps_wrapper_lock_contention_to_retryable_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_backups as router_mod

    async def _busy(*_args: Any, **_kwargs: Any) -> Any:
        return router_mod._CommandResult(
            returncode=3,
            stdout="",
            stderr="advisory lock is already held",
        )

    monkeypatch.setattr(router_mod, "_run_command", _busy)
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
            backup_root=tmp_path,
            backup_project_root=tmp_path,
            backup_command_enabled=True,
        )
    )

    response = TestClient(app, headers=_IDEMPOTENCY_HEADERS).post(
        "/v1/admin/backups",
        json={"backup_id": "manual", "execute": True},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "BACKUP_MAINTENANCE_BUSY"
    assert response.headers["Retry-After"] == "3"


@pytest.mark.unit
def test_create_backup_never_adopts_unmarked_artifact_after_process_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.infra.domain_command_execution_repo import (
        BackupCommandExecution,
    )
    from kortravelmap.infra.domain_command_repo import DomainCommandClaim

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_backups as router_mod

    _write_artifact(tmp_path, "manual")
    now = datetime(2026, 7, 31, tzinfo=UTC)
    claim = DomainCommandClaim(
        command_id=71,
        actor="admin",
        operation="admin.backup.create",
        idempotency_key=_IDEMPOTENCY_HEADERS["Idempotency-Key"],
        fingerprint_version=1,
        request_fingerprint="a" * 64,
        created_at=now,
    )
    execution = BackupCommandExecution(
        command_id=71,
        effect_kind="create",
        effect_token="1" * 64,
        phase="effect_started",
        backup_id="manual",
        app_db=None,
        dagster_db=None,
        rustfs_volume=None,
        marker_key="command-71",
        input_digest="a" * 64,
        prepared_result=None,
        output_digest=None,
        marker_sha256=None,
        prepared_at=now,
        effect_started_at=now,
        effect_completed_at=None,
    )

    async def _pending(*_args: Any, **_kwargs: Any) -> Any:
        raise domain_command_service.DomainCommandPending(claim)

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _pending)
    monkeypatch.setattr(
        router_mod,
        "get_backup_command_execution",
        AsyncMock(return_value=execution),
    )
    run = AsyncMock(
        return_value=router_mod._CommandResult(
            returncode=0,
            stdout="rerun",
            stderr="",
        )
    )
    marker_proof = AsyncMock(side_effect=[None, "b" * 64])
    monkeypatch.setattr(router_mod, "_run_command", run)
    monkeypatch.setattr(router_mod, "_marker_proof", marker_proof)
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
            backup_root=tmp_path,
            backup_project_root=tmp_path,
            backup_command_enabled=True,
        )
    )

    response = TestClient(app, headers=_IDEMPOTENCY_HEADERS).post(
        "/v1/admin/backups",
        json={"backup_id": "manual", "execute": True},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED"
    assert body["details"]["state"] == "manual_reconcile_required"
    assert body["details"]["command_id"] == 71
    assert body["details"]["effect_token"] == "1" * 64
    assert (
        body["details"]["fence_name"]
        == "kor-travel-map-maintenance-effect-fence-v1"
    )
    run.assert_not_awaited()


@pytest.mark.unit
def test_create_backup_retry_terminalizes_detached_effect_marker_without_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.infra import domain_command_marker as marker_mod
    from kortravelmap.infra.domain_command_execution_repo import (
        BackupCommandExecution,
    )
    from kortravelmap.infra.domain_command_repo import DomainCommandClaim

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_backups as router_mod

    now = datetime(2026, 7, 31, tzinfo=UTC)
    command_id = 73
    backup_id = "detached"
    input_digest = "a" * 64
    marker_mod.reserve_backup_destination(
        tmp_path,
        command_id=command_id,
        backup_id=backup_id,
        input_digest=input_digest,
    )
    _write_artifact(tmp_path, backup_id)
    output_proof = marker_mod.backup_artifact_output_proof(
        tmp_path, backup_id
    )
    marker_sha256 = marker_mod.write_domain_command_marker(
        tmp_path,
        command_id=command_id,
        operation="admin.backup.create",
        marker_key=f"command-{command_id}",
        effect_kind="create",
        effect_state="created",
        backup_id=backup_id,
        input_digest=input_digest,
        output_proof=output_proof,
    )
    claim = DomainCommandClaim(
        command_id=command_id,
        actor="admin",
        operation="admin.backup.create",
        idempotency_key=_IDEMPOTENCY_HEADERS["Idempotency-Key"],
        fingerprint_version=1,
        request_fingerprint=input_digest,
        created_at=now,
    )
    execution = BackupCommandExecution(
        command_id=command_id,
        effect_kind="create",
        effect_token="2" * 64,
        phase="effect_started",
        backup_id=backup_id,
        app_db=None,
        dagster_db=None,
        rustfs_volume=None,
        marker_key=f"command-{command_id}",
        input_digest=input_digest,
        prepared_result=None,
        output_digest=None,
        marker_sha256=None,
        prepared_at=now,
        effect_started_at=now,
        effect_completed_at=None,
    )

    async def _pending(*_args: Any, **_kwargs: Any) -> Any:
        raise domain_command_service.DomainCommandPending(claim)

    async def _actual_marker_proof(
        _settings: ApiSettings,
        prepared: Any,
        *,
        effect_state: str,
        output_proof: dict[str, object],
    ) -> str | None:
        current = prepared.execution
        return marker_mod.verify_domain_command_marker(
            tmp_path,
            command_id=prepared.command.command_id,
            operation=prepared.command.operation,
            marker_key=current.marker_key,
            effect_kind=current.effect_kind,
            effect_state=effect_state,
            backup_id=current.backup_id,
            input_digest=current.input_digest,
            output_proof=output_proof,
        )

    run = AsyncMock()
    release = AsyncMock()
    monkeypatch.setattr(domain_command_service, "begin_domain_command", _pending)
    monkeypatch.setattr(
        router_mod,
        "get_backup_command_execution",
        AsyncMock(return_value=execution),
    )
    monkeypatch.setattr(router_mod, "_marker_proof", _actual_marker_proof)
    monkeypatch.setattr(router_mod, "_run_command", run)
    monkeypatch.setattr(router_mod, "_release_docker_effect_fence", release)
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
            backup_root=tmp_path,
            backup_project_root=tmp_path,
            backup_command_enabled=True,
        )
    )

    response = TestClient(app, headers=_IDEMPOTENCY_HEADERS).post(
        "/v1/admin/backups",
        json={"backup_id": backup_id, "execute": True},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "completed"
    assert response.json()["data"]["stdout"] is None
    run.assert_not_awaited()
    release.assert_awaited_once()
    assert marker_mod.verify_domain_command_marker(
        tmp_path,
        command_id=command_id,
        operation="admin.backup.create",
        marker_key=f"command-{command_id}",
        effect_kind="create",
        effect_state="created",
        backup_id=backup_id,
        input_digest=input_digest,
        output_proof=output_proof,
    ) == marker_sha256


@pytest.mark.unit
def test_create_backup_rejects_existing_unreserved_custom_destination_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.infra import domain_command_marker as marker_mod

    from kortravelmap.api.routers import admin_backups as router_mod

    _write_artifact(tmp_path, "custom")
    start_effect = AsyncMock()
    release_fence = AsyncMock()
    monkeypatch.setattr(
        router_mod,
        "reserve_backup_destination",
        marker_mod.reserve_backup_destination,
    )
    monkeypatch.setattr(
        router_mod,
        "start_backup_command_effect",
        start_effect,
    )
    monkeypatch.setattr(
        router_mod,
        "_release_docker_effect_fence",
        release_fence,
    )
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
            backup_root=tmp_path,
            backup_project_root=tmp_path,
            backup_command_enabled=True,
        )
    )

    response = TestClient(app, headers=_IDEMPOTENCY_HEADERS).post(
        "/v1/admin/backups",
        json={"backup_id": "custom", "execute": True},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "BACKUP_DESTINATION_NOT_OWNED"
    start_effect.assert_not_awaited()
    release_fence.assert_awaited_once()


@pytest.mark.unit
def test_restore_plan_and_swap_boundary(client: TestClient) -> None:
    restore = client.post(
        "/v1/admin/restore/backup-1",
        json={"recreate": True, "skip_rustfs": True},
    )
    assert restore.status_code == 200
    restore_body = restore.json()
    assert restore_body["data"]["operation"] == "restore"
    assert restore_body["data"]["status"] == "planned"
    assert restore_body["data"]["command"]["env"]["KOR_TRAVEL_MAP_RESTORE_RECREATE"] == "1"
    assert restore_body["data"]["command"]["env"]["KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS"] == "1"

    swap = client.post("/v1/admin/restore/backup-1/swap", json={})
    assert swap.status_code == 200
    swap_body = swap.json()
    assert swap_body["data"]["operation"] == "swap"
    assert swap_body["data"]["status"] == "planned"
    assert swap_body["data"]["command"]["env"]["KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY"] == "0"
    assert swap_body["data"]["command"]["env"]["KOR_TRAVEL_MAP_RESTORE_SWAP_SKIP_VERIFY"] == "0"


@pytest.mark.unit
def test_execute_restore_swap_requires_opt_in(client: TestClient) -> None:
    response = client.post(
        "/v1/admin/restore/backup-1/swap",
        json={"execute": True, "apply": True},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "BACKUP_COMMAND_DISABLED"


@pytest.mark.unit
def test_execute_restore_swap_uses_command_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_backups as router_mod

    _write_artifact(tmp_path, "backup-1")
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
            backup_root=tmp_path,
            backup_project_root=tmp_path,
            backup_command_enabled=True,
        )
    )
    seen: dict[str, Any] = {}

    async def _fake_run(plan: Any, *, timeout_seconds: float) -> Any:
        seen["plan"] = plan
        seen["timeout_seconds"] = timeout_seconds
        return router_mod._CommandResult(returncode=0, stdout="swapped", stderr="")

    monkeypatch.setattr(router_mod, "_run_command", _fake_run)
    response = TestClient(app, headers=_IDEMPOTENCY_HEADERS).post(
        "/v1/admin/restore/backup-1/swap",
        json={"execute": True, "apply": True, "skip_verify": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "completed"
    assert body["data"]["stdout"] == "swapped"
    assert seen["plan"].env["KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY"] == "1"
    assert seen["plan"].env["KOR_TRAVEL_MAP_RESTORE_SWAP_SKIP_VERIFY"] == "1"
    assert "KOR_TRAVEL_MAP_MAINTENANCE_LOCK_HELD" not in seen["plan"].env


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "operation", "effect_kind", "payload"),
    [
        (
            "/v1/admin/restore/backup-1",
            "admin.backup.restore",
            "restore",
            {"execute": True},
        ),
        (
            "/v1/admin/restore/backup-1/swap",
            "admin.backup.swap",
            "swap",
            {"execute": True, "apply": True},
        ),
    ],
)
def test_restore_commands_fail_close_started_effect_without_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    operation: str,
    effect_kind: str,
    payload: dict[str, object],
) -> None:
    from kortravelmap.infra.domain_command_execution_repo import (
        BackupCommandExecution,
    )
    from kortravelmap.infra.domain_command_repo import DomainCommandClaim

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import admin_backups as router_mod

    _write_artifact(tmp_path, "backup-1")
    now = datetime(2026, 7, 31, tzinfo=UTC)
    claim = DomainCommandClaim(
        command_id=72,
        actor="admin",
        operation=operation,
        idempotency_key=_IDEMPOTENCY_HEADERS["Idempotency-Key"],
        fingerprint_version=1,
        request_fingerprint="a" * 64,
        created_at=now,
    )
    execution = BackupCommandExecution(
        command_id=72,
        effect_kind=effect_kind,
        effect_token="3" * 64,
        phase="effect_started",
        backup_id="backup-1",
        app_db="kor_travel_map_restore",
        dagster_db="kor_travel_map_dagster_restore",
        rustfs_volume="kor-travel-map-rustfs-restore",
        marker_key="command-72",
        input_digest="a" * 64,
        prepared_result=None,
        output_digest=None,
        marker_sha256=None,
        prepared_at=now,
        effect_started_at=now,
        effect_completed_at=None,
    )

    async def _pending(*_args: Any, **_kwargs: Any) -> Any:
        raise domain_command_service.DomainCommandPending(claim)

    run = AsyncMock()

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _pending)
    monkeypatch.setattr(
        router_mod,
        "get_backup_command_execution",
        AsyncMock(return_value=execution),
    )
    monkeypatch.setattr(router_mod, "_run_command", run)
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
            backup_root=tmp_path,
            backup_project_root=tmp_path,
            backup_command_enabled=True,
        )
    )

    response = TestClient(app, headers=_IDEMPOTENCY_HEADERS).post(
        path,
        json=payload,
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED"
    assert body["details"]["command_id"] == 72
    assert body["details"]["effect_token"] == "3" * 64
    run.assert_not_awaited()


@pytest.mark.unit
def test_restore_swap_rejects_removed_operator_field(client: TestClient) -> None:
    response = client.post(
        "/v1/admin/restore/backup-1/swap",
        json={"operator": "spoofed-principal"},
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_restore_swap_rejects_removed_env_file_override(client: TestClient) -> None:
    response = client.post(
        "/v1/admin/restore/backup-1/swap",
        json={"env_file": "/tmp/foreign"},
    )

    assert response.status_code == 422


@pytest.mark.unit
def test_backup_registry_events_use_each_authenticated_principal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import admin_backups as router_mod

    for backup_id in ("manual", "delete-me", "restore-me", "swap-me"):
        _write_artifact(tmp_path, backup_id)

    session = _FakeSession()
    current_actor = {"value": "create-principal"}
    app = create_app(
        ApiSettings(
            admin_destructive_enabled=True,
            admin_proxy_secret=None,
            backup_root=tmp_path,
            backup_project_root=tmp_path,
            backup_command_enabled=True,
        )
    )

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[require_admin_frontend] = lambda: AdminProxyContext(
        actor=current_actor["value"]
    )

    calls: list[tuple[str, str, str | None]] = []

    async def _fake_run(plan: Any, *, timeout_seconds: float) -> Any:
        del plan, timeout_seconds
        return router_mod._CommandResult(returncode=0, stdout="ok", stderr="")

    async def _fake_upsert(
        session: Any,
        artifact: Any,
        *,
        actor: str,
        event_kind: str | None,
    ) -> Any:
        del session
        calls.append(("upsert", actor, event_kind))
        return SimpleNamespace(file_id=f"file:{artifact.backup_id}")

    async def _fake_mark_deleted(
        session: Any,
        *,
        file_id: str,
        actor: str,
    ) -> None:
        del session, file_id
        calls.append(("deleted", actor, None))

    async def _fake_touch_loaded(session: Any, **kwargs: Any) -> bool:
        del session
        calls.append(("restored", kwargs["actor"], kwargs["event_kind"]))
        return True

    async def _fake_register_file(session: Any, **kwargs: Any) -> Any:
        del session
        calls.append(("swap", kwargs["actor"], kwargs.get("event_kind")))
        return SimpleNamespace(file_id="file:swap")

    monkeypatch.setattr(router_mod, "_run_command", _fake_run)
    monkeypatch.setattr(router_mod, "_registry_upsert_backup", _fake_upsert)
    monkeypatch.setattr(router_mod.file_registry, "mark_deleted", _fake_mark_deleted)
    monkeypatch.setattr(router_mod.file_registry, "touch_loaded", _fake_touch_loaded)
    monkeypatch.setattr(router_mod.file_registry, "register_file", _fake_register_file)

    with TestClient(app, headers=_IDEMPOTENCY_HEADERS) as principal_client:
        create = principal_client.post(
            "/v1/admin/backups",
            json={"backup_id": "manual", "execute": True},
        )
        assert create.status_code == 200

        current_actor["value"] = "delete-principal"
        delete = principal_client.delete("/v1/admin/backups/delete-me")
        assert delete.status_code == 200

        current_actor["value"] = "restore-principal"
        restore = principal_client.post(
            "/v1/admin/restore/restore-me",
            json={"execute": True},
        )
        assert restore.status_code == 200

        current_actor["value"] = "swap-principal"
        swap = principal_client.post(
            "/v1/admin/restore/swap-me/swap",
            json={"execute": True},
        )
        assert swap.status_code == 200

    assert calls == [
        ("upsert", "create-principal", "downloaded"),
        ("upsert", "delete-principal", None),
        ("deleted", "delete-principal", None),
        ("restored", "restore-principal", "restored"),
        ("swap", "swap-principal", None),
    ]
