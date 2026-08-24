"""``/admin/backups`` 운영 라우터 (T-209e-c).

The router exposes audit-preserving cold backup artifacts and opt-in backup
commands. `300` recovery has no supported restore or hot-swap format yet;
retired URI handlers therefore fail closed and are intentionally absent from
the public OpenAPI contract.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import signal
import stat
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, Literal, NoReturn
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

BackupOperation = Literal["backup"]
BackupOperationStatus = Literal["planned", "completed", "failed", "manual_required"]
_SUPERVISED_COMMAND_COMMUNICATIONS: set[asyncio.Task[tuple[bytes, bytes]]] = set()
_DOCKER_EFFECT_FENCE_NAME = "kor-travel-map-maintenance-effect-fence-v1"


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
    """Retired restore hot-swap request shape.

    T-VN-H46H 이후 endpoint 자체가 recovery format 부재로 410을 반환한다. 검증을
    생략하는 public escape hatch는 의도적으로 제공하지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    app_db: str | None = Field(default=None, min_length=1)
    dagster_db: str | None = Field(default=None, min_length=1)
    rustfs_volume: str | None = Field(default=None, min_length=1)
    apply: bool = False
    execute: bool = False
    note: str | None = None


class BackupCommandPlan(BaseModel):
    """Command plan returned by the backup endpoint."""

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
    """Backup operation response data."""

    model_config = ConfigDict(extra="forbid")

    operation: BackupOperation
    status: BackupOperationStatus
    backup_id: str
    message: str
    artifact: BackupRecord | None = None
    command: BackupCommandPlan | None = None
    stdout: str | None = None
    stderr: str | None = None


class BackupOperationResponse(BaseModel):
    """Backup operation response."""

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


def _restore_unsupported() -> HTTPException:
    """old lineage restore/swap command surface는 format 설계 전까지 완전히 닫는다."""

    return HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "RESTORE_UNSUPPORTED",
            "message": (
                "300 baseline recovery format이 아직 정의·검증되지 않아 restore와 "
                "hot swap은 지원하지 않습니다."
            ),
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
        _detach_supervised_command(process, communication)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "BACKUP_COMMAND_TIMEOUT",
                "message": "백업/복구 command 실행 시간이 초과했습니다.",
                "details": {"timeout_seconds": timeout_seconds},
            },
        ) from None
    except BaseException:
        _detach_supervised_command(process, communication)
        raise
    return _CommandResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


def _consume_supervised_command(
    communication: asyncio.Task[tuple[bytes, bytes]],
) -> None:
    _SUPERVISED_COMMAND_COMMUNICATIONS.discard(communication)
    if communication.cancelled():
        return
    with suppress(Exception):
        communication.exception()


def _detach_supervised_command(
    process: asyncio.subprocess.Process,
    communication: asyncio.Task[tuple[bytes, bytes]],
) -> None:
    if communication.done():
        return
    # Wrapper만 signal한다. wrapper는 이를 detach 요청으로 기록하고 daemon
    # effect와 연결된 child를 자연 terminal까지 감독하며 advisory lock을 유지한다.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    _SUPERVISED_COMMAND_COMMUNICATIONS.add(communication)
    communication.add_done_callback(_consume_supervised_command)


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
                "KOR_TRAVEL_MAP_COMMAND_EFFECT_TOKEN": execution.effect_token,
                "KOR_TRAVEL_MAP_COMMAND_FENCE_PREACQUIRED": "1",
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
    prepared: _PreparedBackupCommand,
    code: str,
    message: str,
) -> None:
    if result.returncode == 3:
        raise _maintenance_busy()
    if result.returncode == 4:
        raise _effect_reconciliation_required(
            prepared,
            reason="global Docker effect fence가 이미 존재하거나 상태가 모호함",
            diagnostic=result.stderr.strip(),
        )
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


def _effect_reconciliation_required(
    prepared: _PreparedBackupCommand,
    *,
    reason: str,
    diagnostic: str | None = None,
) -> HTTPException:
    execution = prepared.execution
    details: dict[str, object] = {
        "state": "manual_reconcile_required",
        "reason": reason,
        "command_id": prepared.command.command_id,
        "operation": prepared.command.operation,
        "effect_kind": execution.effect_kind,
        "effect_token": execution.effect_token,
        "input_digest": execution.input_digest,
        "fence_name": _DOCKER_EFFECT_FENCE_NAME,
        "safe_procedure": [
            "Docker fence의 exact name과 labels를 inspect하고 실제 target 상태를 확인합니다.",
            "command/output identity가 모두 일치할 때만 운영 runbook에 따라 "
            "terminal marker를 기록합니다.",
            "marker proof를 검증한 뒤 exact effect_token fence만 해제하고 "
            "같은 Idempotency-Key로 재시도합니다.",
            "missing/foreign/mismatched evidence이면 자동 재실행·자동 채택하지 않습니다.",
        ],
    }
    if diagnostic:
        details["diagnostic"] = diagnostic
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED",
            "message": (
                "이전 backup/restore effect의 terminal proof가 없어 "
                "중복 mutation을 방지하기 위해 자동 실행을 차단했습니다."
            ),
            "details": details,
        },
    )


def _docker_effect_fence_plan(
    settings: ApiSettings,
    prepared: _PreparedBackupCommand,
    *,
    action: Literal["acquire", "release"],
) -> BackupCommandPlan:
    execution = prepared.execution
    command = [
        sys.executable,
        str(
            _script_path(
                settings,
                Path("scripts/docker-domain-command-fence.py"),
            )
        ),
        action,
        "--effect-token",
        execution.effect_token,
        "--command-id",
        str(prepared.command.command_id),
        "--operation",
        prepared.command.operation,
        "--effect-kind",
        execution.effect_kind,
        "--input-digest",
        execution.input_digest,
        "--marker-key",
        execution.marker_key,
        "--backup-id",
        execution.backup_id,
    ]
    if action == "acquire":
        command.append("--adopt-existing-exact")
    return BackupCommandPlan(
        cwd=str(settings.backup_project_root.resolve()),
        command=command,
        env={},
        enabled=True,
    )


async def _acquire_docker_effect_fence(
    settings: ApiSettings,
    prepared: _PreparedBackupCommand,
) -> None:
    plan = _docker_effect_fence_plan(
        settings,
        prepared,
        action="acquire",
    )
    result = await _run_command(plan, timeout_seconds=30.0)
    if result.returncode != 0:
        _raise_external_command_failure(
            result,
            prepared=prepared,
            code="BACKUP_EFFECT_FENCE_ACQUIRE_FAILED",
            message="durable Docker effect fence 획득에 실패했습니다.",
        )


async def _release_docker_effect_fence(
    settings: ApiSettings,
    prepared: _PreparedBackupCommand,
) -> None:
    plan = _docker_effect_fence_plan(
        settings,
        prepared,
        action="release",
    )
    result = await _run_command(plan, timeout_seconds=30.0)
    if result.returncode != 0:
        _raise_external_command_failure(
            result,
            prepared=prepared,
            code="BACKUP_EFFECT_FENCE_RELEASE_FAILED",
            message="terminal marker 뒤 exact Docker effect fence 해제에 실패했습니다.",
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
                effect_token=secrets.token_hex(32),
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
    engine: AsyncEngine,
    settings: ApiSettings,
    prepared: _PreparedBackupCommand,
    *,
    reserve_destination: bool = False,
) -> _PreparedBackupCommand:
    if prepared.execution.phase != "prepared":
        return prepared
    async with _maintenance_lock(engine):
        async with session.begin():
            current = await get_backup_command_execution(
                session,
                prepared.command.command_id,
            )
        if current is None:
            raise _effect_reconciliation_required(
                prepared,
                reason="maintenance lock 획득 뒤 command execution을 다시 읽을 수 없음",
            )
        current_prepared = _PreparedBackupCommand(
            command=prepared.command,
            execution=current,
            started_now=False,
        )
        if current.phase != "prepared":
            return current_prepared
        await _acquire_docker_effect_fence(settings, current_prepared)
        if reserve_destination:
            try:
                await asyncio.to_thread(
                    reserve_backup_destination,
                    settings.backup_root,
                    command_id=current_prepared.command.command_id,
                    backup_id=current.backup_id,
                    input_digest=current.input_digest,
                )
            except (OSError, ValueError) as exc:
                try:
                    await _release_docker_effect_fence(
                        settings,
                        current_prepared,
                    )
                except HTTPException as release_exc:
                    raise _effect_reconciliation_required(
                        current_prepared,
                        reason=(
                            "effect 시작 전 destination reservation 실패 뒤 "
                            "exact prepared fence 해제를 증명하지 못함"
                        ),
                    ) from release_exc
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "BACKUP_DESTINATION_NOT_OWNED",
                        "message": (
                            "backup destination이 다른 artifact 또는 command 소유입니다."
                        ),
                        "details": {
                            "backup_id": current.backup_id,
                            "error": str(exc),
                        },
                    },
                ) from exc
        try:
            async with session.begin():
                execution = await start_backup_command_effect(
                    session,
                    prepared.command.command_id,
                )
        except RuntimeError as exc:
            async with session.begin():
                recovered = await get_backup_command_execution(
                    session,
                    prepared.command.command_id,
                )
            if recovered is not None and recovered.phase != "prepared":
                return _PreparedBackupCommand(
                    command=prepared.command,
                    execution=recovered,
                    started_now=False,
                )
            raise _effect_reconciliation_required(
                current_prepared,
                reason=(
                    "exact fence 획득 뒤 prepared effect transition의 "
                    "현재 phase를 증명하지 못함"
                ),
            ) from exc
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
    engine: Annotated[AsyncEngine, Depends(get_engine)],
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
    prepared = await _start_prepared_backup_command(
        session,
        engine,
        settings,
        prepared,
        reserve_destination=True,
    )
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
        if not prepared.started_now:
            raise _effect_reconciliation_required(
                prepared,
                reason="effect_started command에 exact terminal marker가 없음",
            )
        result = await _run_command(
            plan,
            timeout_seconds=settings.backup_command_timeout_seconds,
        )
        if result.returncode != 0:
            _raise_external_command_failure(
                result,
                prepared=prepared,
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
    await _release_docker_effect_fence(settings, prepared)
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


@restore_router.post(
    "/{backup_id}",
    status_code=status.HTTP_410_GONE,
    deprecated=True,
    include_in_schema=False,
    response_model=None,
    summary="사용 중단된 restore endpoint",
    responses={
        status.HTTP_410_GONE: {
            "description": "300 baseline recovery format이 정의되기 전까지 restore는 지원하지 않음"
        }
    },
)
async def restore_backup(
    request: Request,
    backup_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    body: RestoreRunRequest | None = None,
) -> NoReturn:
    """Retired restore endpoint — no plan or host command is issued."""
    del request, backup_id, session, engine, context, idempotency_key, body
    raise _restore_unsupported()

    # 아래 legacy implementation은 `300` recovery format을 설계할 때까지 실행 불가다.
    # Guard보다 뒤에 남긴 것은 old artifact audit context만 보존하기 위해서다.
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
        start_effect=False,
    )
    prepared = await _start_prepared_backup_command(
        session,
        engine,
        settings,
        prepared,
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
        if not prepared.started_now:
            raise _effect_reconciliation_required(
                prepared,
                reason="effect_started command에 exact terminal marker가 없음",
            )
        result = await _run_command(
            plan,
            timeout_seconds=settings.backup_command_timeout_seconds,
        )
        if result.returncode != 0:
            _raise_external_command_failure(
                result,
                prepared=prepared,
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
    await _release_docker_effect_fence(settings, prepared)
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


@restore_router.post(
    "/{backup_id}/swap",
    status_code=status.HTTP_410_GONE,
    deprecated=True,
    include_in_schema=False,
    response_model=None,
    summary="사용 중단된 restore hot-swap endpoint",
    responses={
        status.HTTP_410_GONE: {
            "description": "300 baseline recovery format이 정의되기 전까지 hot swap은 지원하지 않음"
        }
    },
)
async def plan_restore_swap(
    request: Request,
    backup_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    body: RestoreSwapRequest | None = None,
) -> NoReturn:
    """Retired restore hot-swap endpoint — no plan or host command is issued."""
    del request, backup_id, session, engine, context, idempotency_key, body
    raise _restore_unsupported()

    # 아래 legacy implementation은 `300` recovery format을 설계할 때까지 실행 불가다.
    # Guard보다 뒤에 남긴 것은 old artifact audit context만 보존하기 위해서다.
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
        "KOR_TRAVEL_MAP_RESTORE_SWAP_SKIP_VERIFY": "0",
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
        start_effect=False,
    )
    prepared = await _start_prepared_backup_command(
        session,
        engine,
        settings,
        prepared,
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
                "performed",
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
        if not prepared.started_now:
            raise _effect_reconciliation_required(
                prepared,
                reason="effect_started command에 exact terminal marker가 없음",
            )
        result = await _run_command(
            plan,
            timeout_seconds=settings.backup_command_timeout_seconds,
        )
        if result.returncode != 0:
            _raise_external_command_failure(
                result,
                prepared=prepared,
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
                    "performed",
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
    await _release_docker_effect_fence(settings, prepared)
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
