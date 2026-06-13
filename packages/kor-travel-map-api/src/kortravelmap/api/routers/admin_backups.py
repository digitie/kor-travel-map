"""``/admin/backups`` 운영 라우터 (T-209e-c).

The router exposes backup artifacts and safe command plans. Running the host
Docker backup/restore scripts is opt-in because the API container should not
silently gain host Docker control in production.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from kortravelmap.infra.backup import (
    BackupArtifact,
    BackupArtifactError,
    backup_artifact,
    list_backup_artifacts,
    validate_backup_id,
)
from pydantic import BaseModel, ConfigDict, Field

from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "router",
    "restore_router",
    "BackupListResponse",
    "BackupDetailResponse",
    "BackupOperationResponse",
]

router = APIRouter(prefix="/admin/backups", tags=["admin-backups"])
restore_router = APIRouter(prefix="/admin/restore", tags=["admin-backups"])

BackupOperation = Literal["backup", "restore", "swap"]
BackupOperationStatus = Literal["planned", "completed", "failed", "manual_required"]


@dataclass(frozen=True, slots=True)
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str


class BackupRecord(BaseModel):
    """Backup artifact HTTP representation."""

    model_config = ConfigDict(extra="forbid")

    backup_id: str
    path: str
    manifest_status: str
    created_at_utc: datetime | None = None
    mode: str | None = None
    components: dict[str, str]
    databases: dict[str, str]
    object_storage: dict[str, Any]
    byte_size: int
    checksum_count: int
    detail_url: str
    restore_url: str


class BackupListData(BaseModel):
    """Backup list data."""

    model_config = ConfigDict(extra="forbid")

    items: list[BackupRecord]
    backup_root: str
    command_enabled: bool


class BackupDetailResponse(BaseModel):
    """``GET /admin/backups/{backup_id}`` response."""

    model_config = ConfigDict(extra="forbid")

    data: BackupRecord
    meta: Meta


class BackupListResponse(BaseModel):
    """``GET /admin/backups`` response."""

    model_config = ConfigDict(extra="forbid")

    data: BackupListData
    meta: Meta


class BackupRunRequest(BaseModel):
    """Backup command request.

    ``execute`` defaults to false. The API first returns an auditable command
    plan; actual host command execution needs explicit request + enabled
    server setting.
    """

    model_config = ConfigDict(extra="forbid")

    backup_id: str | None = Field(default=None, min_length=1)
    allow_running: bool = False
    execute: bool = False


class RestoreRunRequest(BaseModel):
    """Staging restore command request."""

    model_config = ConfigDict(extra="forbid")

    app_db: str | None = Field(default=None, min_length=1)
    dagster_db: str | None = Field(default=None, min_length=1)
    rustfs_volume: str | None = Field(default=None, min_length=1)
    recreate: bool = False
    skip_checksum: bool = False
    skip_rustfs: bool = False
    execute: bool = False


class RestoreSwapRequest(BaseModel):
    """Restore hot-swap command request."""

    model_config = ConfigDict(extra="forbid")

    app_db: str | None = Field(default=None, min_length=1)
    dagster_db: str | None = Field(default=None, min_length=1)
    rustfs_volume: str | None = Field(default=None, min_length=1)
    env_file: str | None = Field(default=None, min_length=1)
    apply: bool = False
    skip_verify: bool = False
    execute: bool = False
    operator: str | None = Field(default=None, min_length=1)
    note: str | None = None


class BackupCommandPlan(BaseModel):
    """Command plan returned by backup/restore endpoints."""

    model_config = ConfigDict(extra="forbid")

    cwd: str
    command: list[str]
    env: dict[str, str]
    enabled: bool


class RestoreTargets(BaseModel):
    """Staging restore targets."""

    model_config = ConfigDict(extra="forbid")

    app_db: str
    dagster_db: str
    rustfs_volume: str


class BackupOperationData(BaseModel):
    """Backup/restore/swap operation response data."""

    model_config = ConfigDict(extra="forbid")

    operation: BackupOperation
    status: BackupOperationStatus
    backup_id: str
    message: str
    artifact: BackupRecord | None = None
    restore_targets: RestoreTargets | None = None
    command: BackupCommandPlan | None = None
    stdout: str | None = None
    stderr: str | None = None


class BackupOperationResponse(BaseModel):
    """Backup/restore/swap operation response."""

    model_config = ConfigDict(extra="forbid")

    data: BackupOperationData
    meta: Meta


def _settings(request: Request) -> ApiSettings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, ApiSettings) else ApiSettings()


def _backup_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _record(artifact: BackupArtifact) -> BackupRecord:
    return BackupRecord(
        backup_id=artifact.backup_id,
        path=str(artifact.path),
        manifest_status=artifact.manifest_status,
        created_at_utc=artifact.created_at_utc,
        mode=artifact.mode,
        components=artifact.components,
        databases=artifact.databases,
        object_storage=artifact.object_storage,
        byte_size=artifact.byte_size,
        checksum_count=artifact.checksum_count,
        detail_url=f"/v1/admin/backups/{artifact.backup_id}",
        restore_url=f"/v1/admin/restore/{artifact.backup_id}",
    )


def _backup_error(exc: BackupArtifactError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "BACKUP_NOT_FOUND",
            "message": str(exc),
            "details": {},
        },
    )


def _invalid_backup_id(exc: BackupArtifactError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "INVALID_BACKUP_ID",
            "message": str(exc),
            "details": {},
        },
    )


def _command_disabled() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "BACKUP_COMMAND_DISABLED",
            "message": (
                "백업/복구 host command 실행은 비활성 상태입니다. "
                "KOR_TRAVEL_MAP_API_BACKUP_COMMAND_ENABLED=true 설정 후 실행하세요."
            ),
            "details": {},
        },
    )


def _script_path(settings: ApiSettings, script: Path) -> Path:
    if script.is_absolute():
        return script
    return (settings.backup_project_root / script).resolve()


def _command_plan(
    *,
    settings: ApiSettings,
    script: Path,
    env: dict[str, str],
    args: list[str] | None = None,
) -> BackupCommandPlan:
    return BackupCommandPlan(
        cwd=str(settings.backup_project_root.resolve()),
        command=["bash", str(_script_path(settings, script)), *(args or [])],
        env=env,
        enabled=settings.backup_command_enabled,
    )


async def _run_command(
    plan: BackupCommandPlan,
    *,
    timeout_seconds: float,
) -> _CommandResult:
    env = {**os.environ, **plan.env}
    process = await asyncio.create_subprocess_exec(
        *plan.command,
        cwd=plan.cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "BACKUP_COMMAND_TIMEOUT",
                "message": "백업/복구 command 실행 시간이 초과했습니다.",
                "details": {"timeout_seconds": timeout_seconds},
            },
        ) from None
    return _CommandResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


@router.get("", response_model=BackupListResponse)
async def list_backups(request: Request) -> BackupListResponse:
    """List local backup artifacts."""
    started_at = perf_counter()
    settings = _settings(request)
    items = [_record(item) for item in list_backup_artifacts(settings.backup_root)]
    return BackupListResponse(
        data=BackupListData(
            items=items,
            backup_root=str(settings.backup_root),
            command_enabled=settings.backup_command_enabled,
        ),
        meta=make_meta(started_at=started_at),
    )


@router.get("/{backup_id}", response_model=BackupDetailResponse)
async def get_backup(request: Request, backup_id: str) -> BackupDetailResponse:
    """Return one backup artifact."""
    started_at = perf_counter()
    settings = _settings(request)
    try:
        safe_id = validate_backup_id(backup_id)
    except BackupArtifactError as exc:
        raise _invalid_backup_id(exc) from exc
    try:
        artifact = backup_artifact(settings.backup_root, safe_id)
    except BackupArtifactError as exc:
        raise _backup_error(exc) from exc
    return BackupDetailResponse(
        data=_record(artifact),
        meta=make_meta(started_at=started_at),
    )


@router.post("", response_model=BackupOperationResponse)
async def create_backup(
    request: Request,
    body: BackupRunRequest | None = None,
) -> BackupOperationResponse:
    """Plan or run a cold backup command."""
    started_at = perf_counter()
    settings = _settings(request)
    payload = body or BackupRunRequest()
    try:
        backup_id = validate_backup_id(payload.backup_id or _backup_id())
    except BackupArtifactError as exc:
        raise _invalid_backup_id(exc) from exc
    env = {
        "KOR_TRAVEL_MAP_BACKUP_ROOT": str(settings.backup_root),
        "KOR_TRAVEL_MAP_BACKUP_ID": backup_id,
        "KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING": "1" if payload.allow_running else "0",
    }
    plan = _command_plan(
        settings=settings,
        script=settings.backup_script_path,
        env=env,
    )
    if not payload.execute:
        return BackupOperationResponse(
            data=BackupOperationData(
                operation="backup",
                status="planned",
                backup_id=backup_id,
                message="백업 command plan을 생성했습니다.",
                command=plan,
            ),
            meta=make_meta(started_at=started_at),
        )
    if not settings.backup_command_enabled:
        raise _command_disabled()
    result = await _run_command(
        plan,
        timeout_seconds=settings.backup_command_timeout_seconds,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "BACKUP_COMMAND_FAILED",
                "message": "백업 command 실행이 실패했습니다.",
                "details": {"stderr": result.stderr, "stdout": result.stdout},
            },
        )
    try:
        artifact = _record(backup_artifact(settings.backup_root, backup_id))
    except BackupArtifactError:
        artifact = None
    return BackupOperationResponse(
        data=BackupOperationData(
            operation="backup",
            status="completed",
            backup_id=backup_id,
            message="백업 command 실행이 완료됐습니다.",
            artifact=artifact,
            command=plan,
            stdout=result.stdout,
            stderr=result.stderr,
        ),
        meta=make_meta(started_at=started_at),
    )


def _restore_targets_from_values(
    settings: ApiSettings,
    *,
    app_db: str | None,
    dagster_db: str | None,
    rustfs_volume: str | None,
) -> RestoreTargets:
    return RestoreTargets(
        app_db=validate_backup_id(app_db or settings.restore_app_db),
        dagster_db=validate_backup_id(dagster_db or settings.restore_dagster_db),
        rustfs_volume=validate_backup_id(rustfs_volume or settings.restore_rustfs_volume),
    )


@restore_router.post("/{backup_id}", response_model=BackupOperationResponse)
async def restore_backup(
    request: Request,
    backup_id: str,
    body: RestoreRunRequest | None = None,
) -> BackupOperationResponse:
    """Plan or run a staging restore command."""
    started_at = perf_counter()
    settings = _settings(request)
    try:
        safe_id = validate_backup_id(backup_id)
    except BackupArtifactError as exc:
        raise _invalid_backup_id(exc) from exc
    payload = body or RestoreRunRequest()
    try:
        artifact = _record(backup_artifact(settings.backup_root, safe_id))
    except BackupArtifactError as exc:
        raise _backup_error(exc) from exc
    try:
        targets = _restore_targets_from_values(
            settings,
            app_db=payload.app_db,
            dagster_db=payload.dagster_db,
            rustfs_volume=payload.rustfs_volume,
        )
    except BackupArtifactError as exc:
        raise _invalid_backup_id(exc) from exc
    env = {
        "KOR_TRAVEL_MAP_BACKUP_ROOT": str(settings.backup_root),
        "KOR_TRAVEL_MAP_RESTORE_BACKUP_ID": safe_id,
        "KOR_TRAVEL_MAP_RESTORE_APP_DB": targets.app_db,
        "KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB": targets.dagster_db,
        "KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME": targets.rustfs_volume,
        "KOR_TRAVEL_MAP_RESTORE_RECREATE": "1" if payload.recreate else "0",
        "KOR_TRAVEL_MAP_RESTORE_SKIP_CHECKSUM": "1" if payload.skip_checksum else "0",
        "KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS": "1" if payload.skip_rustfs else "0",
    }
    plan = _command_plan(
        settings=settings,
        script=settings.restore_script_path,
        env=env,
        args=[safe_id],
    )
    if not payload.execute:
        return BackupOperationResponse(
            data=BackupOperationData(
                operation="restore",
                status="planned",
                backup_id=safe_id,
                message="staging restore command plan을 생성했습니다.",
                artifact=artifact,
                restore_targets=targets,
                command=plan,
            ),
            meta=make_meta(started_at=started_at),
        )
    if not settings.backup_command_enabled:
        raise _command_disabled()
    result = await _run_command(
        plan,
        timeout_seconds=settings.backup_command_timeout_seconds,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "RESTORE_COMMAND_FAILED",
                "message": "restore command 실행이 실패했습니다.",
                "details": {"stderr": result.stderr, "stdout": result.stdout},
            },
        )
    return BackupOperationResponse(
        data=BackupOperationData(
            operation="restore",
            status="completed",
            backup_id=safe_id,
            message="staging restore command 실행이 완료됐습니다.",
            artifact=artifact,
            restore_targets=targets,
            command=plan,
            stdout=result.stdout,
            stderr=result.stderr,
        ),
        meta=make_meta(started_at=started_at),
    )


@restore_router.post("/{backup_id}/swap", response_model=BackupOperationResponse)
async def plan_restore_swap(
    request: Request,
    backup_id: str,
    body: RestoreSwapRequest | None = None,
) -> BackupOperationResponse:
    """Plan or run the restore hot-swap env switch."""
    started_at = perf_counter()
    settings = _settings(request)
    try:
        safe_id = validate_backup_id(backup_id)
    except BackupArtifactError as exc:
        raise _invalid_backup_id(exc) from exc
    payload = body or RestoreSwapRequest()
    try:
        artifact = _record(backup_artifact(settings.backup_root, safe_id))
    except BackupArtifactError as exc:
        raise _backup_error(exc) from exc
    try:
        targets = _restore_targets_from_values(
            settings,
            app_db=payload.app_db,
            dagster_db=payload.dagster_db,
            rustfs_volume=payload.rustfs_volume,
        )
    except BackupArtifactError as exc:
        raise _invalid_backup_id(exc) from exc
    env = {
        "KOR_TRAVEL_MAP_BACKUP_ROOT": str(settings.backup_root),
        "KOR_TRAVEL_MAP_RESTORE_BACKUP_ID": safe_id,
        "KOR_TRAVEL_MAP_RESTORE_APP_DB": targets.app_db,
        "KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB": targets.dagster_db,
        "KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME": targets.rustfs_volume,
        "KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY": "1" if payload.apply else "0",
        "KOR_TRAVEL_MAP_RESTORE_SWAP_SKIP_VERIFY": "1" if payload.skip_verify else "0",
    }
    if payload.env_file:
        env["KOR_TRAVEL_MAP_RESTORE_SWAP_ENV_FILE"] = payload.env_file
    plan = _command_plan(
        settings=settings,
        script=settings.restore_swap_script_path,
        env=env,
    )
    if not payload.execute:
        return BackupOperationResponse(
            data=BackupOperationData(
                operation="swap",
                status="planned",
                backup_id=safe_id,
                message="restore hot-swap command plan을 생성했습니다.",
                artifact=artifact,
                restore_targets=targets,
                command=plan,
            ),
            meta=make_meta(started_at=started_at),
        )
    if not settings.backup_command_enabled:
        raise _command_disabled()
    result = await _run_command(
        plan,
        timeout_seconds=settings.backup_command_timeout_seconds,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "RESTORE_SWAP_COMMAND_FAILED",
                "message": "restore hot-swap command 실행이 실패했습니다.",
                "details": {"stderr": result.stderr, "stdout": result.stdout},
            },
        )
    return BackupOperationResponse(
        data=BackupOperationData(
            operation="swap",
            status="completed",
            backup_id=safe_id,
            message="restore hot-swap command 실행이 완료됐습니다.",
            artifact=artifact,
            restore_targets=targets,
            command=plan,
            stdout=result.stdout,
            stderr=result.stderr,
        ),
        meta=make_meta(started_at=started_at),
    )
