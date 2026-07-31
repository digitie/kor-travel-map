"""``/admin/backups`` 운영 라우터 (T-209e-c).

The router exposes backup artifacts and safe command plans. Running the host
Docker backup/restore scripts is opt-in because the API container should not
silently gain host Docker control in production.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from kortravelmap.core.managed_file_states import MANAGED_FILE_LOCATION_BACKUP_ROOT
from kortravelmap.infra import file_registry
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.backup import (
    BackupArtifact,
    BackupArtifactError,
    backup_artifact,
    list_backup_artifacts,
    validate_backup_id,
)
from kortravelmap.infra.domain_command_execution_repo import (
    BackupCommandExecution,
    complete_backup_command_effect,
    create_backup_command_execution,
    get_backup_command_execution,
    start_backup_command_effect,
)
from kortravelmap.infra.domain_command_marker import (
    backup_artifact_output_proof,
    delete_output_proof,
    reserve_backup_destination,
    restore_output_proof,
    swap_output_proof,
    verify_domain_command_marker,
    write_domain_command_marker,
)
from kortravelmap.infra.domain_command_repo import (
    DomainCommandClaim,
    canonical_domain_command_fingerprint,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.api import domain_command_service
from kortravelmap.api.auth import (
    AdminProxyContext,
    require_admin_destructive_enabled,
    require_admin_frontend,
)
from kortravelmap.api.db import get_engine, get_session
from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "router",
    "restore_router",
    "BackupListResponse",
    "BackupDetailResponse",
    "BackupDeleteResponse",
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


@dataclass(frozen=True, slots=True)
class _PreparedBackupCommand:
    command: domain_command_service.DomainCommandHandle
    execution: BackupCommandExecution
    started_now: bool


def _artifact_meta(artifact: BackupArtifact) -> dict[str, Any]:
    """registry ``meta``용 manifest 요약."""

    return {
        "manifest_status": artifact.manifest_status,
        "mode": artifact.mode,
        "components": artifact.components,
        "databases": artifact.databases,
        "checksum_count": artifact.checksum_count,
        "physical": {"path": str(artifact.path)},
    }


async def _registry_upsert_backup(
    session: AsyncSession,
    artifact: BackupArtifact,
    *,
    actor: str,
    event_kind: str | None,
) -> file_registry.ManagedFile:
    """백업 artifact를 registry에 upsert(백업 hook 공통부)."""

    return await file_registry.register_file(
        session,
        storage_backend="filesystem",
        location=MANAGED_FILE_LOCATION_BACKUP_ROOT,
        path=artifact.backup_id,
        kind="backup",
        is_directory=True,
        byte_size=artifact.byte_size,
        downloaded_at=artifact.created_at_utc,
        actor=actor,
        event_kind=event_kind,
        meta=_artifact_meta(artifact),
    )


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


class BackupDeleteData(BaseModel):
    """Deleted backup artifact snapshot."""

    model_config = ConfigDict(extra="forbid")

    deleted: bool
    item: BackupRecord


class BackupDeleteResponse(BaseModel):
    """``DELETE /admin/backups/{backup_id}`` response."""

    model_config = ConfigDict(extra="forbid")

    data: BackupDeleteData
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
    apply: bool = False
    skip_verify: bool = False
    execute: bool = False
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


def _command_unavailable(exc: OSError, plan: BackupCommandPlan) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "BACKUP_COMMAND_UNAVAILABLE",
            "message": "백업/복구 command 시작에 실패했습니다.",
            "details": {
                "command": plan.command,
                "cwd": plan.cwd,
                "error": str(exc),
            },
        },
    )


def _delete_failed(exc: OSError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "BACKUP_DELETE_FAILED",
            "message": "backup artifact 삭제에 실패했습니다.",
            "details": {"error": str(exc)},
        },
    )


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(path)


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
    try:
        process = await asyncio.create_subprocess_exec(
            *plan.command,
            cwd=plan.cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise _command_unavailable(exc, plan) from exc
    communication = asyncio.create_task(process.communicate())
    try:
        stdout, stderr = await asyncio.wait_for(
            asyncio.shield(communication),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        await _reap_process_group(process, communication)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "BACKUP_COMMAND_TIMEOUT",
                "message": "백업/복구 command 실행 시간이 초과했습니다.",
                "details": {"timeout_seconds": timeout_seconds},
            },
        ) from None
    except BaseException:
        await _reap_process_group(process, communication)
        raise
    return _CommandResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


async def _terminate_process_group(
    process: asyncio.subprocess.Process,
    communication: asyncio.Task[tuple[bytes, bytes]],
) -> None:
    if process.returncode is None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    done, _ = await asyncio.wait({communication}, timeout=5.0)
    if not done and process.returncode is None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    await communication


async def _reap_process_group(
    process: asyncio.subprocess.Process,
    communication: asyncio.Task[tuple[bytes, bytes]],
) -> None:
    """반복 cancellation에도 child group 회수를 끝낸 뒤 반환한다."""

    cleanup = asyncio.create_task(_terminate_process_group(process, communication))
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
    await cleanup


async def _write_marker(
    settings: ApiSettings,
    prepared: _PreparedBackupCommand,
    *,
    effect_state: str,
    output_proof: dict[str, object],
) -> str:
    execution = prepared.execution
    return await asyncio.to_thread(
        write_domain_command_marker,
        settings.backup_root,
        command_id=prepared.command.command_id,
        operation=prepared.command.operation,
        marker_key=execution.marker_key,
        effect_kind=execution.effect_kind,
        effect_state=effect_state,
        backup_id=execution.backup_id,
        input_digest=execution.input_digest,
        output_proof=output_proof,
    )


async def _marker_proof(
    settings: ApiSettings,
    prepared: _PreparedBackupCommand,
    *,
    effect_state: str,
    output_proof: dict[str, object],
) -> str | None:
    execution = prepared.execution
    try:
        return await asyncio.to_thread(
            verify_domain_command_marker,
            settings.backup_root,
            command_id=prepared.command.command_id,
            operation=prepared.command.operation,
            marker_key=execution.marker_key,
            effect_kind=execution.effect_kind,
            effect_state=effect_state,
            backup_id=execution.backup_id,
            input_digest=execution.input_digest,
            output_proof=output_proof,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"backup command marker proof mismatch: {exc}",
        ) from exc


async def _marker_proof_variants(
    settings: ApiSettings,
    prepared: _PreparedBackupCommand,
    *,
    effect_state: str,
    output_proofs: tuple[dict[str, object], ...],
) -> str | None:
    """허용된 proof 중 marker와 exact 일치하는 한 가지를 찾는다."""

    mismatch: HTTPException | None = None
    for output_proof in output_proofs:
        try:
            digest = await _marker_proof(
                settings,
                prepared,
                effect_state=effect_state,
                output_proof=output_proof,
            )
        except HTTPException as exc:
            mismatch = exc
            continue
        if digest is not None:
            return digest
        return None
    if mismatch is not None:
        raise mismatch
    return None


def _plan_with_marker(
    plan: BackupCommandPlan,
    prepared: _PreparedBackupCommand,
    *,
    recovery: bool = False,
) -> BackupCommandPlan:
    execution = prepared.execution
    return plan.model_copy(
        update={
            "env": {
                **plan.env,
                "KOR_TRAVEL_MAP_COMMAND_ID": str(prepared.command.command_id),
                "KOR_TRAVEL_MAP_COMMAND_OPERATION": prepared.command.operation,
                "KOR_TRAVEL_MAP_COMMAND_MARKER_KEY": execution.marker_key,
                "KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND": execution.effect_kind,
                "KOR_TRAVEL_MAP_COMMAND_BACKUP_ID": execution.backup_id,
                "KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST": execution.input_digest,
                "KOR_TRAVEL_MAP_COMMAND_RECOVERY": "1" if recovery else "0",
            }
        }
    )


@asynccontextmanager
async def _maintenance_lock(engine: AsyncEngine) -> AsyncIterator[None]:
    """host script와 같은 session advisory lock을 별도 connection에 고정한다."""

    lock_id = advisory_lock_key("maintenance:backup-restore")
    async with engine.connect() as connection:
        acquired = bool(
            (
                await connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": lock_id},
                )
            ).scalar_one()
        )
        if not acquired:
            raise _maintenance_busy()
        try:
            yield
        finally:
            unlocked = (
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": lock_id},
                )
            ).scalar_one()
            if not unlocked:
                raise RuntimeError("maintenance advisory lock exact unlock failed")


def _maintenance_busy() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "BACKUP_MAINTENANCE_BUSY",
            "message": "다른 backup/restore command가 실행 중입니다.",
            "details": {
                "lock_key": "maintenance:backup-restore",
            },
        },
        headers={"Retry-After": "3"},
    )


def _raise_external_command_failure(
    result: _CommandResult,
    *,
    code: str,
    message: str,
) -> None:
    if result.returncode == 3:
        raise _maintenance_busy()
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": code,
            "message": message,
            "details": {
                "stderr": result.stderr,
                "stdout": result.stdout,
            },
        },
    )


def _pending_execution(
    prepared: _PreparedBackupCommand,
) -> domain_command_service.DomainCommandPending:
    execution = prepared.execution
    command = prepared.command
    return domain_command_service.DomainCommandPending(
        DomainCommandClaim(
            command_id=command.command_id,
            actor=command.actor,
            operation=command.operation,
            idempotency_key=command.idempotency_key,
            fingerprint_version=1,
            request_fingerprint=command.request_fingerprint,
            created_at=execution.prepared_at,
        )
    )


async def _prepare_backup_command(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    idempotency_key: UUID,
    payload: dict[str, object],
    effect_kind: str,
    backup_id: str,
    app_db: str | None = None,
    dagster_db: str | None = None,
    rustfs_volume: str | None = None,
    prepared_result: dict[str, Any] | None = None,
    start_effect: bool = True,
) -> _PreparedBackupCommand:
    started_now = False
    async with session.begin():
        try:
            command = await domain_command_service.begin_domain_command(
                session,
                actor=actor,
                operation=operation,
                idempotency_key=idempotency_key,
                payload=payload,
            )
            execution = await create_backup_command_execution(
                session,
                command_id=command.command_id,
                effect_kind=effect_kind,
                backup_id=backup_id,
                app_db=app_db,
                dagster_db=dagster_db,
                rustfs_volume=rustfs_volume,
                marker_key=f"command-{command.command_id}",
                input_digest=command.request_fingerprint,
                prepared_result=prepared_result,
            )
        except domain_command_service.DomainCommandPending as pending:
            command = domain_command_service.DomainCommandHandle(
                command_id=pending.claim.command_id,
                actor=pending.claim.actor,
                operation=pending.claim.operation,
                idempotency_key=pending.claim.idempotency_key,
                request_fingerprint=pending.claim.request_fingerprint,
            )
            recovered_execution = await get_backup_command_execution(
                session, command.command_id
            )
            if recovered_execution is None:
                raise
            execution = recovered_execution
    if (
        execution.effect_kind != effect_kind
        or execution.backup_id != backup_id
        or execution.app_db != app_db
        or execution.dagster_db != dagster_db
        or execution.rustfs_volume != rustfs_volume
        or execution.input_digest != command.request_fingerprint
        or (
            prepared_result is not None
            and execution.prepared_result != prepared_result
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="backup command execution identity mismatch",
        )
    if start_effect and execution.phase == "prepared":
        async with session.begin():
            execution = await start_backup_command_effect(
                session, command.command_id
            )
        started_now = True
    return _PreparedBackupCommand(
        command=command,
        execution=execution,
        started_now=started_now,
    )


async def _start_prepared_backup_command(
    session: AsyncSession,
    prepared: _PreparedBackupCommand,
) -> _PreparedBackupCommand:
    if prepared.execution.phase != "prepared":
        return prepared
    async with session.begin():
        execution = await start_backup_command_effect(
            session,
            prepared.command.command_id,
        )
    return _PreparedBackupCommand(
        command=prepared.command,
        execution=execution,
        started_now=True,
    )


async def _complete_backup_command(
    session: AsyncSession,
    *,
    prepared: _PreparedBackupCommand,
    response: BaseModel,
    marker_sha256: str,
) -> None:
    async with session.begin():
        if prepared.execution.phase == "effect_started":
            await complete_backup_command_effect(
                session,
                prepared.command.command_id,
                output_digest=canonical_domain_command_fingerprint(
                    response.model_dump(mode="json")
                ),
                marker_sha256=marker_sha256,
            )
        await domain_command_service.complete_domain_command(
            session,
            command=prepared.command,
            response=response,
        )


async def _complete_planned_command(
    session: AsyncSession,
    *,
    actor: str,
    operation: str,
    idempotency_key: UUID,
    payload: dict[str, object],
    response: BackupOperationResponse,
) -> BackupOperationResponse:
    async with session.begin():
        command = await domain_command_service.begin_domain_command(
            session,
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        await domain_command_service.complete_domain_command(
            session,
            command=command,
            response=response,
        )
    return response


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


@router.delete(
    "/{backup_id}",
    response_model=BackupDeleteResponse,
    dependencies=[Depends(require_admin_destructive_enabled)],
)
async def delete_backup(
    request: Request,
    backup_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> BackupDeleteResponse:
    """Delete one backup artifact directory."""
    started_at = perf_counter()
    settings = _settings(request)
    try:
        safe_id = validate_backup_id(backup_id)
    except BackupArtifactError as exc:
        raise _invalid_backup_id(exc) from exc
    artifact: BackupArtifact | None
    try:
        artifact = backup_artifact(settings.backup_root, safe_id)
        prepared_result = _record(artifact).model_dump(mode="json")
    except BackupArtifactError:
        artifact = None
        prepared_result = None
    if prepared_result is None:
        async with session.begin():
            try:
                await domain_command_service.begin_domain_command(
                    session,
                    actor=context.actor,
                    operation="admin.backup.delete",
                    idempotency_key=idempotency_key,
                    payload={"backup_id": safe_id},
                )
            except domain_command_service.DomainCommandPending:
                pass
            else:
                raise _backup_error(
                    BackupArtifactError(
                        f"backup artifact가 없습니다: {safe_id}"
                    )
                )
    prepared = await _prepare_backup_command(
        session,
        actor=context.actor,
        operation="admin.backup.delete",
        idempotency_key=idempotency_key,
        payload={"backup_id": safe_id},
        effect_kind="delete",
        backup_id=safe_id,
        prepared_result=prepared_result,
    )
    if prepared.execution.prepared_result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="backup delete prepared result is missing",
        )
    deleted_item = BackupRecord.model_validate(
        prepared.execution.prepared_result
    )
    output_proof = delete_output_proof(
        backup_id=safe_id,
        prepared_result=prepared.execution.prepared_result,
    )
    async with _maintenance_lock(engine):
        marker_sha256 = await _marker_proof(
            settings,
            prepared,
            effect_state="deleted",
            output_proof=output_proof,
        )
        artifact_path = settings.backup_root / safe_id
        if marker_sha256 is None and await asyncio.to_thread(
            _path_lexists, artifact_path
        ):
            metadata = artifact_path.lstat()
            if not stat.S_ISDIR(metadata.st_mode):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="backup delete target is not a real directory",
                )
            try:
                current_result = _record(
                    backup_artifact(settings.backup_root, safe_id)
                ).model_dump(mode="json")
                if current_result != prepared.execution.prepared_result:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="backup artifact changed after delete preparation",
                    )
                shutil.rmtree(artifact_path)
            except BackupArtifactError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="backup artifact cannot be revalidated",
                ) from exc
            except OSError as exc:
                raise _delete_failed(exc) from exc
        if marker_sha256 is None:
            if await asyncio.to_thread(_path_lexists, artifact_path):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="backup artifact is still present after delete",
                )
            marker_sha256 = await _write_marker(
                settings,
                prepared,
                effect_state="deleted",
                output_proof=output_proof,
            )
        response = BackupDeleteResponse(
            data=BackupDeleteData(deleted=True, item=deleted_item),
            meta=make_meta(started_at=started_at),
        )
        await _complete_backup_command(
            session,
            prepared=prepared,
            response=response,
            marker_sha256=marker_sha256,
        )
    # 파일 registry hook (H2) — rmtree 확정 후 deleted 기록, 실패 무해.
    if artifact is not None:
        async with file_registry.registry_guard("backup:delete"), session.begin():
            registered = await _registry_upsert_backup(
                session,
                artifact,
                actor=context.actor,
                event_kind=None,
            )
            await file_registry.mark_deleted(
                session,
                file_id=registered.file_id,
                actor=context.actor,
            )
    return response


@router.post("", response_model=BackupOperationResponse)
async def create_backup(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    body: BackupRunRequest | None = None,
) -> BackupOperationResponse:
    """Plan or run a cold backup command."""
    started_at = perf_counter()
    settings = _settings(request)
    payload = body or BackupRunRequest()
    try:
        backup_id = validate_backup_id(
            payload.backup_id or f"backup-{idempotency_key}"
        )
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
    command_payload = {
        **payload.model_dump(mode="json"),
        "backup_id": backup_id,
    }
    if not payload.execute:
        response = BackupOperationResponse(
            data=BackupOperationData(
                operation="backup",
                status="planned",
                backup_id=backup_id,
                message="백업 command plan을 생성했습니다.",
                command=plan,
            ),
            meta=make_meta(started_at=started_at),
        )
        return await _complete_planned_command(
            session,
            actor=context.actor,
            operation="admin.backup.create",
            idempotency_key=idempotency_key,
            payload=command_payload,
            response=response,
        )
    if not settings.backup_command_enabled:
        raise _command_disabled()
    prepared = await _prepare_backup_command(
        session,
        actor=context.actor,
        operation="admin.backup.create",
        idempotency_key=idempotency_key,
        payload=command_payload,
        effect_kind="create",
        backup_id=backup_id,
        start_effect=False,
    )
    try:
        await asyncio.to_thread(
            reserve_backup_destination,
            settings.backup_root,
            command_id=prepared.command.command_id,
            backup_id=backup_id,
            input_digest=prepared.execution.input_digest,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BACKUP_DESTINATION_NOT_OWNED",
                "message": "backup destination이 다른 artifact 또는 command 소유입니다.",
                "details": {"backup_id": backup_id, "error": str(exc)},
            },
        ) from exc
    prepared = await _start_prepared_backup_command(session, prepared)
    plan = _plan_with_marker(
        plan,
        prepared,
        recovery=not prepared.started_now,
    )
    output_proof: dict[str, object] | None
    try:
        output_proof = await asyncio.to_thread(
            backup_artifact_output_proof,
            settings.backup_root,
            backup_id,
        )
    except (OSError, ValueError):
        output_proof = None
    marker_sha256 = (
        await _marker_proof(
            settings,
            prepared,
            effect_state="created",
            output_proof=output_proof,
        )
        if output_proof is not None
        else None
    )
    result: _CommandResult | None = None
    if marker_sha256 is None:
        result = await _run_command(
            plan,
            timeout_seconds=settings.backup_command_timeout_seconds,
        )
        if result.returncode != 0:
            _raise_external_command_failure(
                result,
                code="BACKUP_COMMAND_FAILED",
                message="백업 command 실행이 실패했습니다.",
            )
        try:
            output_proof = await asyncio.to_thread(
                backup_artifact_output_proof,
                settings.backup_root,
                backup_id,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "BACKUP_ARTIFACT_INVALID",
                    "message": "백업 command output 검증에 실패했습니다.",
                    "details": {"error": str(exc)},
                },
            ) from exc
        marker_sha256 = await _marker_proof(
            settings,
            prepared,
            effect_state="created",
            output_proof=output_proof,
        )
        if marker_sha256 is None:
            raise _pending_execution(prepared)
    artifact_raw: BackupArtifact | None = None
    try:
        artifact_raw = backup_artifact(settings.backup_root, backup_id)
        artifact = _record(artifact_raw)
    except BackupArtifactError:
        artifact = None
    response = BackupOperationResponse(
        data=BackupOperationData(
            operation="backup",
            status="completed",
            backup_id=backup_id,
            message="백업 command 실행이 완료됐습니다.",
            artifact=artifact,
            command=plan,
            stdout=result.stdout if result is not None else None,
            stderr=result.stderr if result is not None else None,
        ),
        meta=make_meta(started_at=started_at),
    )
    await _complete_backup_command(
        session,
        prepared=prepared,
        response=response,
        marker_sha256=marker_sha256,
    )
    # 파일 registry hook (H1) — 백업 성공 + artifact 파싱 성공 시 등록, 실패 무해.
    if artifact_raw is not None:
        async with file_registry.registry_guard("backup:create"), session.begin():
            await _registry_upsert_backup(
                session,
                artifact_raw,
                actor=context.actor,
                event_kind="downloaded",
            )
    return response


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
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
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
    command_payload = {
        **payload.model_dump(mode="json"),
        "backup_id": safe_id,
        "targets": targets.model_dump(mode="json"),
    }
    if not payload.execute:
        response = BackupOperationResponse(
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
        return await _complete_planned_command(
            session,
            actor=context.actor,
            operation="admin.backup.restore",
            idempotency_key=idempotency_key,
            payload=command_payload,
            response=response,
        )
    if not settings.backup_command_enabled:
        raise _command_disabled()
    prepared = await _prepare_backup_command(
        session,
        actor=context.actor,
        operation="admin.backup.restore",
        idempotency_key=idempotency_key,
        payload=command_payload,
        effect_kind="restore",
        backup_id=safe_id,
        app_db=targets.app_db,
        dagster_db=targets.dagster_db,
        rustfs_volume=targets.rustfs_volume,
    )
    plan = _plan_with_marker(
        plan,
        prepared,
        recovery=not prepared.started_now,
    )
    restore_proof = restore_output_proof(
        settings.backup_root,
        safe_id,
        app_db=targets.app_db,
        dagster_db=targets.dagster_db,
        rustfs_volume=targets.rustfs_volume,
        verification="performed",
    )
    marker_sha256 = await _marker_proof(
        settings,
        prepared,
        effect_state="restored",
        output_proof=restore_proof,
    )
    result: _CommandResult | None = None
    if marker_sha256 is None:
        result = await _run_command(
            plan,
            timeout_seconds=settings.backup_command_timeout_seconds,
        )
        if result.returncode != 0:
            _raise_external_command_failure(
                result,
                code="RESTORE_COMMAND_FAILED",
                message="restore command 실행이 실패했습니다.",
            )
        marker_sha256 = await _marker_proof(
            settings,
            prepared,
            effect_state="restored",
            output_proof=restore_proof,
        )
        if marker_sha256 is None:
            raise _pending_execution(prepared)
    response = BackupOperationResponse(
        data=BackupOperationData(
            operation="restore",
            status="completed",
            backup_id=safe_id,
            message="staging restore command 실행이 완료됐습니다.",
            artifact=artifact,
            restore_targets=targets,
            command=plan,
            stdout=result.stdout if result is not None else None,
            stderr=result.stderr if result is not None else None,
        ),
        meta=make_meta(started_at=started_at),
    )
    await _complete_backup_command(
        session,
        prepared=prepared,
        response=response,
        marker_sha256=marker_sha256,
    )
    # 파일 registry hook (H3) — 복원 = 소비이므로 last_loaded_at 갱신, 실패 무해.
    async with file_registry.registry_guard("backup:restore"), session.begin():
        touched = await file_registry.touch_loaded(
            session,
            storage_backend="filesystem",
            location=MANAGED_FILE_LOCATION_BACKUP_ROOT,
            path=safe_id,
            event_kind="restored",
            actor=context.actor,
            detail={"targets": targets.model_dump()},
        )
        if not touched:
            # 미등록 artifact(수동 생성분) — 등록 후 restored 기록.
            try:
                raw = backup_artifact(settings.backup_root, safe_id)
            except BackupArtifactError:
                raw = None
            if raw is not None:
                await _registry_upsert_backup(
                    session,
                    raw,
                    actor=context.actor,
                    event_kind="restored",
                )
    return response


@restore_router.post("/{backup_id}/swap", response_model=BackupOperationResponse)
async def plan_restore_swap(
    request: Request,
    backup_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
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
    plan = _command_plan(
        settings=settings,
        script=settings.restore_swap_script_path,
        env=env,
    )
    command_payload = {
        **payload.model_dump(mode="json"),
        "backup_id": safe_id,
        "targets": targets.model_dump(mode="json"),
    }
    if not payload.execute:
        response = BackupOperationResponse(
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
        return await _complete_planned_command(
            session,
            actor=context.actor,
            operation="admin.backup.swap",
            idempotency_key=idempotency_key,
            payload=command_payload,
            response=response,
        )
    if not settings.backup_command_enabled:
        raise _command_disabled()
    prepared = await _prepare_backup_command(
        session,
        actor=context.actor,
        operation="admin.backup.swap",
        idempotency_key=idempotency_key,
        payload=command_payload,
        effect_kind="swap",
        backup_id=safe_id,
        app_db=targets.app_db,
        dagster_db=targets.dagster_db,
        rustfs_volume=targets.rustfs_volume,
    )
    plan = _plan_with_marker(
        plan,
        prepared,
        recovery=not prepared.started_now,
    )
    effect_state = "swap_applied" if payload.apply else "swap_planned"
    swap_env_file = settings.backup_project_root / ".env.restore-swap"
    try:
        swap_proofs = tuple(
            swap_output_proof(
                settings.backup_root,
                safe_id,
                app_db=targets.app_db,
                dagster_db=targets.dagster_db,
                rustfs_volume=targets.rustfs_volume,
                env_file=swap_env_file,
                effect_state=effect_state,
                verification=verification,
            )
            for verification in (
                ("skipped" if payload.skip_verify else "performed"),
                "recovery_performed",
            )
        )
    except (OSError, ValueError):
        swap_proofs = ()
    marker_sha256 = (
        await _marker_proof_variants(
            settings,
            prepared,
            effect_state=effect_state,
            output_proofs=swap_proofs,
        )
        if swap_proofs
        else None
    )
    result: _CommandResult | None = None
    if marker_sha256 is None:
        result = await _run_command(
            plan,
            timeout_seconds=settings.backup_command_timeout_seconds,
        )
        if result.returncode != 0:
            _raise_external_command_failure(
                result,
                code="RESTORE_SWAP_COMMAND_FAILED",
                message="restore hot-swap command 실행이 실패했습니다.",
            )
        try:
            swap_proofs = tuple(
                swap_output_proof(
                    settings.backup_root,
                    safe_id,
                    app_db=targets.app_db,
                    dagster_db=targets.dagster_db,
                    rustfs_volume=targets.rustfs_volume,
                    env_file=swap_env_file,
                    effect_state=effect_state,
                    verification=verification,
                )
                for verification in (
                    ("skipped" if payload.skip_verify else "performed"),
                    "recovery_performed",
                )
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "RESTORE_SWAP_OUTPUT_INVALID",
                    "message": "restore hot-swap output 검증에 실패했습니다.",
                    "details": {"error": str(exc)},
                },
            ) from exc
        marker_sha256 = await _marker_proof_variants(
            settings,
            prepared,
            effect_state=effect_state,
            output_proofs=swap_proofs,
        )
        if marker_sha256 is None:
            raise _pending_execution(prepared)
    response = BackupOperationResponse(
        data=BackupOperationData(
            operation="swap",
            status="completed",
            backup_id=safe_id,
            message="restore hot-swap command 실행이 완료됐습니다.",
            artifact=artifact,
            restore_targets=targets,
            command=plan,
            stdout=result.stdout if result is not None else None,
            stderr=result.stderr if result is not None else None,
        ),
        meta=make_meta(started_at=started_at),
    )
    await _complete_backup_command(
        session,
        prepared=prepared,
        response=response,
        marker_sha256=marker_sha256,
    )
    # 파일 registry hook (H10) — swap 스위치 파일(.env.restore-swap)을 temp로 등록.
    async with file_registry.registry_guard("backup:swap-env-file"), session.begin():
        env_file = str(settings.backup_project_root / ".env.restore-swap")
        await file_registry.register_file(
            session,
            storage_backend="filesystem",
            location=MANAGED_FILE_LOCATION_BACKUP_ROOT,
            path=Path(env_file).name,
            kind="temp",
            actor=context.actor,
            downloaded_at=datetime.now(UTC),
            meta={
                "physical": {"path": env_file},
                "backup_id": safe_id,
                "purpose": "restore hot-swap env switch",
            },
        )
    return response
