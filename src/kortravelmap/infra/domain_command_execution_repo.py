"""Operation-specific external command execution state machines.

The command claim is durable before an external effect starts.  A transition to
``effect_started`` is deliberately fail-close: without operation-specific proof
the same command must not be executed again after a process crash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "BackupCommandExecution",
    "OfflineUploadCommandExecution",
    "complete_backup_command_effect",
    "complete_offline_upload_command_effect",
    "create_backup_command_execution",
    "create_offline_upload_command_execution",
    "get_backup_command_execution",
    "get_offline_upload_command_execution",
    "start_backup_command_effect",
    "start_offline_upload_command_effect",
]

ExecutionPhase = Literal["prepared", "effect_started", "effect_succeeded"]


@dataclass(frozen=True, slots=True)
class BackupCommandExecution:
    command_id: int
    effect_kind: str
    effect_token: str
    phase: ExecutionPhase
    backup_id: str
    app_db: str | None
    dagster_db: str | None
    rustfs_volume: str | None
    marker_key: str
    input_digest: str
    prepared_result: dict[str, Any] | None
    output_digest: str | None
    marker_sha256: str | None
    prepared_at: datetime
    effect_started_at: datetime | None
    effect_completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class OfflineUploadCommandExecution:
    command_id: int
    effect_kind: str
    phase: ExecutionPhase
    upload_id: str
    storage_backend: str | None
    bucket: str | None
    storage_key: str | None
    content_type: str | None
    byte_size: int | None
    content_sha256: str | None
    metadata_digest: str | None
    load_job_id: str | None
    dagster_run_id: str | None
    input_digest: str
    output_digest: str | None
    prepared_at: datetime
    effect_started_at: datetime | None
    effect_completed_at: datetime | None


_BACKUP_COLUMNS = """
command_id, effect_kind, effect_token, phase, backup_id, app_db, dagster_db, rustfs_volume,
marker_key, input_digest, prepared_result, output_digest, marker_sha256, prepared_at,
effect_started_at, effect_completed_at
"""
_OFFLINE_COLUMNS = """
command_id, effect_kind, phase, upload_id, storage_backend, bucket, storage_key,
content_type, byte_size, content_sha256, metadata_digest, load_job_id,
dagster_run_id, input_digest, output_digest, prepared_at, effect_started_at,
effect_completed_at
"""


def _backup(row: Any) -> BackupCommandExecution:
    return BackupCommandExecution(
        command_id=int(row.command_id),
        effect_kind=str(row.effect_kind),
        effect_token=str(row.effect_token),
        phase=row.phase,
        backup_id=str(row.backup_id),
        app_db=row.app_db,
        dagster_db=row.dagster_db,
        rustfs_volume=row.rustfs_volume,
        marker_key=str(row.marker_key),
        input_digest=str(row.input_digest),
        prepared_result=row.prepared_result,
        output_digest=row.output_digest,
        marker_sha256=row.marker_sha256,
        prepared_at=row.prepared_at,
        effect_started_at=row.effect_started_at,
        effect_completed_at=row.effect_completed_at,
    )


def _offline(row: Any) -> OfflineUploadCommandExecution:
    return OfflineUploadCommandExecution(
        command_id=int(row.command_id),
        effect_kind=str(row.effect_kind),
        phase=row.phase,
        upload_id=str(row.upload_id),
        storage_backend=row.storage_backend,
        bucket=row.bucket,
        storage_key=row.storage_key,
        content_type=row.content_type,
        byte_size=int(row.byte_size) if row.byte_size is not None else None,
        content_sha256=row.content_sha256,
        metadata_digest=row.metadata_digest,
        load_job_id=str(row.load_job_id) if row.load_job_id is not None else None,
        dagster_run_id=row.dagster_run_id,
        input_digest=str(row.input_digest),
        output_digest=row.output_digest,
        prepared_at=row.prepared_at,
        effect_started_at=row.effect_started_at,
        effect_completed_at=row.effect_completed_at,
    )


async def get_backup_command_execution(
    session: AsyncSession,
    command_id: int,
) -> BackupCommandExecution | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_BACKUP_COLUMNS} "
                "FROM ops.backup_command_executions WHERE command_id = :command_id"
            ),
            {"command_id": command_id},
        )
    ).one_or_none()
    return _backup(row) if row is not None else None


async def create_backup_command_execution(
    session: AsyncSession,
    *,
    command_id: int,
    effect_kind: str,
    effect_token: str,
    backup_id: str,
    app_db: str | None,
    dagster_db: str | None,
    rustfs_volume: str | None,
    marker_key: str,
    input_digest: str,
    prepared_result: dict[str, Any] | None = None,
) -> BackupCommandExecution:
    row = (
        await session.execute(
            text(
                f"""
                INSERT INTO ops.backup_command_executions (
                    command_id, effect_kind, effect_token, phase, backup_id, app_db,
                    dagster_db, rustfs_volume, marker_key, input_digest,
                    prepared_result
                ) VALUES (
                    :command_id, :effect_kind, :effect_token, 'prepared', :backup_id, :app_db,
                    :dagster_db, :rustfs_volume, :marker_key, :input_digest,
                    CAST(:prepared_result AS jsonb)
                )
                RETURNING {_BACKUP_COLUMNS}
                """
            ),
            {
                "command_id": command_id,
                "effect_kind": effect_kind,
                "effect_token": effect_token,
                "backup_id": backup_id,
                "app_db": app_db,
                "dagster_db": dagster_db,
                "rustfs_volume": rustfs_volume,
                "marker_key": marker_key,
                "input_digest": input_digest,
                "prepared_result": (
                    json.dumps(
                        prepared_result,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if prepared_result is not None
                    else None
                ),
            },
        )
    ).one()
    return _backup(row)


async def start_backup_command_effect(
    session: AsyncSession,
    command_id: int,
) -> BackupCommandExecution:
    row = (
        await session.execute(
            text(
                f"""
                UPDATE ops.backup_command_executions
                SET phase = 'effect_started', effect_started_at = now()
                WHERE command_id = :command_id AND phase = 'prepared'
                RETURNING {_BACKUP_COLUMNS}
                """
            ),
            {"command_id": command_id},
        )
    ).one_or_none()
    if row is None:
        raise RuntimeError("backup command effect cannot be started twice")
    return _backup(row)


async def complete_backup_command_effect(
    session: AsyncSession,
    command_id: int,
    *,
    output_digest: str,
    marker_sha256: str,
) -> BackupCommandExecution:
    row = (
        await session.execute(
            text(
                f"""
                UPDATE ops.backup_command_executions
                SET phase = 'effect_succeeded',
                    output_digest = :output_digest,
                    marker_sha256 = :marker_sha256,
                    effect_completed_at = now()
                WHERE command_id = :command_id AND phase = 'effect_started'
                RETURNING {_BACKUP_COLUMNS}
                """
            ),
            {
                "command_id": command_id,
                "output_digest": output_digest,
                "marker_sha256": marker_sha256,
            },
        )
    ).one_or_none()
    if row is None:
        raise RuntimeError("backup command proof transition was rejected")
    return _backup(row)


async def get_offline_upload_command_execution(
    session: AsyncSession,
    command_id: int,
) -> OfflineUploadCommandExecution | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_OFFLINE_COLUMNS} "
                "FROM ops.offline_upload_command_executions "
                "WHERE command_id = :command_id"
            ),
            {"command_id": command_id},
        )
    ).one_or_none()
    return _offline(row) if row is not None else None


async def create_offline_upload_command_execution(
    session: AsyncSession,
    *,
    command_id: int,
    effect_kind: str,
    upload_id: str,
    storage_backend: str | None,
    bucket: str | None,
    storage_key: str | None,
    content_type: str | None,
    byte_size: int | None,
    content_sha256: str | None,
    metadata_digest: str | None,
    load_job_id: str | None,
    input_digest: str,
) -> OfflineUploadCommandExecution:
    row = (
        await session.execute(
            text(
                f"""
                INSERT INTO ops.offline_upload_command_executions (
                    command_id, effect_kind, phase, upload_id, storage_backend,
                    bucket, storage_key, content_type, byte_size, content_sha256,
                    metadata_digest, load_job_id, input_digest
                ) VALUES (
                    :command_id, :effect_kind, 'prepared',
                    CAST(:upload_id AS uuid), :storage_backend, :bucket,
                    :storage_key, :content_type, :byte_size, :content_sha256,
                    :metadata_digest, CAST(:load_job_id AS uuid), :input_digest
                )
                RETURNING {_OFFLINE_COLUMNS}
                """
            ),
            {
                "command_id": command_id,
                "effect_kind": effect_kind,
                "upload_id": upload_id,
                "storage_backend": storage_backend,
                "bucket": bucket,
                "storage_key": storage_key,
                "content_type": content_type,
                "byte_size": byte_size,
                "content_sha256": content_sha256,
                "metadata_digest": metadata_digest,
                "load_job_id": load_job_id,
                "input_digest": input_digest,
            },
        )
    ).one()
    return _offline(row)


async def start_offline_upload_command_effect(
    session: AsyncSession,
    command_id: int,
) -> OfflineUploadCommandExecution:
    row = (
        await session.execute(
            text(
                f"""
                UPDATE ops.offline_upload_command_executions
                SET phase = 'effect_started', effect_started_at = now()
                WHERE command_id = :command_id AND phase = 'prepared'
                RETURNING {_OFFLINE_COLUMNS}
                """
            ),
            {"command_id": command_id},
        )
    ).one_or_none()
    if row is None:
        raise RuntimeError("offline upload command effect cannot be started twice")
    return _offline(row)


async def complete_offline_upload_command_effect(
    session: AsyncSession,
    command_id: int,
    *,
    output_digest: str,
    dagster_run_id: str | None = None,
) -> OfflineUploadCommandExecution:
    row = (
        await session.execute(
            text(
                f"""
                UPDATE ops.offline_upload_command_executions
                SET phase = 'effect_succeeded',
                    output_digest = :output_digest,
                    dagster_run_id = :dagster_run_id,
                    effect_completed_at = now()
                WHERE command_id = :command_id AND phase = 'effect_started'
                RETURNING {_OFFLINE_COLUMNS}
                """
            ),
            {
                "command_id": command_id,
                "output_digest": output_digest,
                "dagster_run_id": dagster_run_id,
            },
        )
    ).one_or_none()
    if row is None:
        raise RuntimeError("offline upload command proof transition was rejected")
    return _offline(row)
