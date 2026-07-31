"""T-VN-12 domain command ledger 스키마 불변식."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from kortravelmap.infra.offline_upload_repo import (
    OfflineUploadStatusConflict,
    reserve_offline_upload_delete,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration


async def test_offline_delete_resource_reservation_rolls_back_competing_claim(
    migrated_engine: AsyncEngine,
) -> None:
    upload_id = "97000000-0000-4000-8000-000000000001"
    first_reserved = asyncio.Event()
    release_first = asyncio.Event()
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)

    async with sessions.begin() as session:
        await session.execute(
            text(
                """
                INSERT INTO ops.offline_uploads (
                  upload_id, provider, dataset_key, sync_scope,
                  original_filename, storage_backend, storage_key, byte_size,
                  checksum_sha256, detected_format, status
                ) VALUES (
                  CAST(:upload_id AS uuid), 'integration', 'delete-race',
                  'default', 'race.jsonl', 'rustfs', 'offline/race.jsonl', 1,
                  repeat('f', 64), 'jsonl', 'uploaded'
                )
                """
            ),
            {"upload_id": upload_id},
        )

    async def _first() -> int:
        async with sessions() as session, session.begin():
            command_id = await session.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      'integration:first', 'admin.offline-upload.delete',
                      '97000000-0000-4000-8000-000000000011', repeat('a', 64)
                    )
                    RETURNING command_id
                    """
                )
            )
            assert command_id is not None
            reserved = await reserve_offline_upload_delete(
                session,
                upload_id=upload_id,
                command_id=command_id,
            )
            assert reserved is not None
            first_reserved.set()
            await release_first.wait()
            return command_id

    async def _attempt_competing_reservation() -> None:
        async with sessions() as session, session.begin():
            command_id = await session.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      'integration:second', 'admin.offline-upload.delete',
                      '97000000-0000-4000-8000-000000000012',
                      repeat('b', 64)
                    )
                    RETURNING command_id
                    """
                )
            )
            assert command_id is not None
            await reserve_offline_upload_delete(
                session,
                upload_id=upload_id,
                command_id=command_id,
            )

    async def _competing() -> None:
        await first_reserved.wait()
        with pytest.raises(OfflineUploadStatusConflict):
            await _attempt_competing_reservation()

    first_task = asyncio.create_task(_first())
    competing_task = asyncio.create_task(_competing())
    await first_reserved.wait()
    await asyncio.sleep(0)
    release_first.set()
    first_command_id, _ = await asyncio.gather(first_task, competing_task)

    async with sessions() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT status, delete_command_id
                    FROM ops.offline_uploads
                    WHERE upload_id = CAST(:upload_id AS uuid)
                    """
                ),
                {"upload_id": upload_id},
            )
        ).one()
        second_claims = await session.scalar(
            text(
                """
                SELECT count(*)
                FROM ops.domain_commands
                WHERE actor = 'integration:second'
                  AND operation = 'admin.offline-upload.delete'
                """
            )
        )
    assert row.status == "deleting"
    assert row.delete_command_id == first_command_id
    assert second_claims == 0


async def test_backup_maintenance_lock_fails_fast_when_exact_key_is_busy(
    migrated_engine: AsyncEngine,
) -> None:
    from fastapi import HTTPException
    from kortravelmap.api.routers.admin_backups import _maintenance_lock

    from kortravelmap.infra.advisory_lock import advisory_lock_key

    lock_id = advisory_lock_key("maintenance:backup-restore")
    async with migrated_engine.connect() as owner:
        await owner.execute(
            text("SELECT pg_advisory_lock(:lock_id)"),
            {"lock_id": lock_id},
        )
        try:
            with pytest.raises(HTTPException) as raised:
                async with _maintenance_lock(migrated_engine):
                    pass
            assert raised.value.status_code == 409
            assert raised.value.detail["code"] == "BACKUP_MAINTENANCE_BUSY"
        finally:
            unlocked = await owner.scalar(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": lock_id},
            )
            assert unlocked is True


async def test_lock_wrapper_holds_lock_until_detached_docker_effect_exits(
    migrated_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    from kortravelmap.api.routers import admin_backups as router_mod

    from kortravelmap.infra.advisory_lock import advisory_lock_key
    from kortravelmap.infra.domain_command_marker import (
        backup_artifact_output_proof,
        verify_domain_command_marker,
    )

    project_root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240
    container_name = f"ktm-tvn12-supervised-{uuid4().hex}"
    backup_id = "detached-backup"
    command_id = 912
    marker_key = f"command-{command_id}"
    input_digest = "a" * 64
    artifact = tmp_path / backup_id
    (artifact / "meta").mkdir(parents=True)
    (artifact / "postgres").mkdir()
    dump = artifact / "postgres" / "app.dump"
    dump.write_bytes(b"detached-effect")
    (artifact / "meta" / "manifest.json").write_text(
        json.dumps({"backup_id": backup_id}),
        encoding="utf-8",
    )
    (artifact / "meta" / "SHA256SUMS").write_text(
        f"{hashlib.sha256(dump.read_bytes()).hexdigest()}  postgres/app.dump\n",
        encoding="utf-8",
    )
    marker_writer = project_root / "scripts" / "write-domain-command-marker.py"
    child_command = (
        f"docker run --rm --name {container_name} alpine:3.20 "
        "sh -c \"trap '' TERM INT; sleep 2\"; exec \"$@\""
    )
    plan = router_mod.BackupCommandPlan(
        cwd=str(project_root),
        command=[
            sys.executable,
            str(project_root / "scripts" / "with-pg-advisory-lock.py"),
            "--key",
            "maintenance:backup-restore",
            "--dsn",
            migrated_engine.url.render_as_string(hide_password=False),
            "--",
            "bash",
            "-c",
            child_command,
            "marker-writer",
            sys.executable,
            str(marker_writer),
            "--backup-root",
            str(tmp_path),
            "--command-id",
            str(command_id),
            "--operation",
            "admin.backup.create",
            "--marker-key",
            marker_key,
            "--effect-kind",
            "create",
            "--effect-state",
            "created",
            "--backup-id",
            backup_id,
            "--input-digest",
            input_digest,
        ],
        env={},
        enabled=True,
    )
    lock_id = advisory_lock_key("maintenance:backup-restore")

    async def _contender_can_acquire() -> bool:
        async with migrated_engine.connect() as contender:
            acquired = bool(
                await contender.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": lock_id},
                )
            )
            if acquired:
                unlocked = await contender.scalar(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": lock_id},
                )
                assert unlocked is True
            return acquired

    async def _docker(*args: str) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        return process.returncode, stdout.decode("utf-8", errors="replace").strip()

    async def _container_is_running() -> bool:
        returncode, output = await _docker(
            "inspect",
            "--format",
            "{{.State.Running}}",
            container_name,
        )
        return returncode == 0 and output == "true"

    task = asyncio.create_task(
        router_mod._run_command(plan, timeout_seconds=30.0)
    )
    try:
        for _ in range(600):
            if await _container_is_running():
                break
            await asyncio.sleep(0.05)
        assert await _container_is_running()
        assert await _contender_can_acquire() is False

        started = asyncio.get_running_loop().time()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert asyncio.get_running_loop().time() - started < 1.0

        assert await _container_is_running()
        assert await _contender_can_acquire() is False

        supervised = tuple(router_mod._SUPERVISED_COMMAND_COMMUNICATIONS)
        assert supervised
        await asyncio.wait_for(
            asyncio.gather(*supervised),
            timeout=10.0,
        )
        assert not router_mod._SUPERVISED_COMMAND_COMMUNICATIONS
        assert await _container_is_running() is False
        output_proof = backup_artifact_output_proof(tmp_path, backup_id)
        marker_sha256 = verify_domain_command_marker(
            tmp_path,
            command_id=command_id,
            operation="admin.backup.create",
            marker_key=marker_key,
            effect_kind="create",
            effect_state="created",
            backup_id=backup_id,
            input_digest=input_digest,
            output_proof=output_proof,
        )
        assert marker_sha256 is not None
        assert (
            verify_domain_command_marker(
                tmp_path,
                command_id=command_id,
                operation="admin.backup.create",
                marker_key=marker_key,
                effect_kind="create",
                effect_state="created",
                backup_id=backup_id,
                input_digest=input_digest,
                output_proof=output_proof,
            )
            == marker_sha256
        )
        assert await _contender_can_acquire() is True
    finally:
        await _docker("rm", "--force", container_name)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_domain_command_ledger_is_actor_and_operation_scoped(
    migrated_session: AsyncSession,
) -> None:
    key = "91000000-0000-4000-8000-000000000001"
    for actor, operation, marker in (
        ("admin:alice", "admin.feature.create", "alice-create"),
        ("admin:bob", "admin.feature.create", "bob-create"),
        ("admin:alice", "admin.feature.patch", "alice-patch"),
    ):
        await migrated_session.execute(
            text(
                """
                WITH command AS (
                  INSERT INTO ops.domain_commands (
                    actor, operation, idempotency_key, request_fingerprint
                  ) VALUES (
                    :actor, :operation, CAST(:key AS uuid), repeat('a', 64)
                  )
                  RETURNING command_id
                )
                INSERT INTO ops.domain_command_results (
                  command_id, response_status, response_body
                )
                SELECT command_id, 200,
                       jsonb_build_object('marker', CAST(:marker AS text))
                FROM command
                """
            ),
            {
                "actor": actor,
                "operation": operation,
                "key": key,
                "marker": marker,
            },
        )

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT command.actor, command.operation,
                       command.fingerprint_version,
                       result.response_body->>'marker' AS marker
                FROM ops.domain_commands AS command
                JOIN ops.domain_command_results AS result
                  ON result.command_id = command.command_id
                WHERE command.idempotency_key = CAST(:key AS uuid)
                ORDER BY command.actor, command.operation
                """
            ),
            {"key": key},
        )
    ).all()
    assert [tuple(row) for row in rows] == [
        ("admin:alice", "admin.feature.create", 1, "alice-create"),
        ("admin:alice", "admin.feature.patch", 1, "alice-patch"),
        ("admin:bob", "admin.feature.create", 1, "bob-create"),
    ]

    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      'admin:alice', 'admin.feature.create',
                      CAST(:key AS uuid), repeat('b', 64)
                    )
                    """
                ),
                {"key": key},
            )


async def test_domain_command_ledger_is_append_only(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(
        text(
            """
            WITH command AS (
              INSERT INTO ops.domain_commands (
                actor, operation, idempotency_key, request_fingerprint
              ) VALUES (
                'admin:alice', 'admin.feature.delete',
                '92000000-0000-4000-8000-000000000001', repeat('c', 64)
              )
              RETURNING command_id
            )
            INSERT INTO ops.domain_command_results (
              command_id, response_status, response_body
            )
            SELECT command_id, 200, '{"deleted": true}'::jsonb
            FROM command
            """
        )
    )

    for statement in (
        "UPDATE ops.domain_commands SET request_fingerprint = repeat('d', 64) "
        "WHERE actor = 'admin:alice'",
        "DELETE FROM ops.domain_commands WHERE actor = 'admin:alice'",
        "UPDATE ops.domain_command_results SET response_status = 201",
        "DELETE FROM ops.domain_command_results",
        "TRUNCATE ops.domain_command_results",
    ):
        with pytest.raises(DBAPIError):
            async with migrated_session.begin_nested():
                await migrated_session.execute(text(statement))


async def test_domain_mutation_and_terminal_result_rollback_together(
    migrated_session: AsyncSession,
) -> None:
    async def _write_then_fail() -> None:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    WITH command AS (
                      INSERT INTO ops.domain_commands (
                        actor, operation, idempotency_key, request_fingerprint
                      ) VALUES (
                        'admin:alice', 'admin.feature.create',
                        '93000000-0000-4000-8000-000000000001',
                        repeat('d', 64)
                      )
                      RETURNING command_id
                    )
                    INSERT INTO ops.domain_command_results (
                      command_id, response_status, response_body
                    )
                    SELECT command_id, 201,
                           '{"feature_id": "feature-1"}'::jsonb
                    FROM command
                    """
                )
            )
            raise RuntimeError("simulated response failure")

    with pytest.raises(RuntimeError, match="simulated response failure"):
        await _write_then_fail()

    count = await migrated_session.scalar(
        text(
            """
            SELECT count(*)
            FROM ops.domain_command_results AS result
            JOIN ops.domain_commands AS command
              ON command.command_id = result.command_id
            WHERE command.idempotency_key =
                  '93000000-0000-4000-8000-000000000001'::uuid
            """
        )
    )
    assert count == 0
    claim_count = await migrated_session.scalar(
        text(
            """
            SELECT count(*)
            FROM ops.domain_commands
            WHERE idempotency_key =
              '93000000-0000-4000-8000-000000000001'::uuid
            """
        )
    )
    assert claim_count == 0


async def test_durable_claim_can_exist_without_terminal_result(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.domain_commands (
              actor, operation, idempotency_key, request_fingerprint
            ) VALUES (
              'admin:alice', 'admin.backup.restore',
              '94000000-0000-4000-8000-000000000001', repeat('e', 64)
            )
            """
        )
    )

    row = (
        await migrated_session.execute(
            text(
                """
                SELECT command.command_id, command.request_fingerprint,
                       result.completed_at
                FROM ops.domain_commands AS command
                LEFT JOIN ops.domain_command_results AS result
                  ON result.command_id = command.command_id
                WHERE command.actor = 'admin:alice'
                  AND command.operation = 'admin.backup.restore'
                """
            )
        )
    ).one()
    assert row.command_id > 0
    assert row.request_fingerprint == "e" * 64
    assert row.completed_at is None


async def test_external_execution_state_requires_operation_specific_terminal_proof(
    migrated_session: AsyncSession,
) -> None:
    backup_command_id = await migrated_session.scalar(
        text(
            """
            INSERT INTO ops.domain_commands (
              actor, operation, idempotency_key, request_fingerprint
            ) VALUES (
              'admin:alice', 'admin.backup.restore',
              '96000000-0000-4000-8000-000000000001', repeat('a', 64)
            )
            RETURNING command_id
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.backup_command_executions (
              command_id, effect_kind, phase, backup_id, app_db, dagster_db,
              rustfs_volume, marker_key, input_digest, effect_started_at
            ) VALUES (
              :command_id, 'restore', 'effect_started', 'backup-1',
              'app_stage', 'dagster_stage', 'rustfs_stage',
              'restore-1.json', repeat('b', 64), now()
            )
            """
        ),
        {"command_id": backup_command_id},
    )
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    UPDATE ops.backup_command_executions
                    SET phase = 'effect_succeeded',
                        effect_completed_at = now()
                    WHERE command_id = :command_id
                    """
                ),
                {"command_id": backup_command_id},
            )

    offline_command_id = await migrated_session.scalar(
        text(
            """
            INSERT INTO ops.domain_commands (
              actor, operation, idempotency_key, request_fingerprint
            ) VALUES (
              'admin:alice', 'admin.offline-upload.load',
              '96000000-0000-4000-8000-000000000002', repeat('c', 64)
            )
            RETURNING command_id
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.offline_upload_command_executions (
              command_id, effect_kind, phase, upload_id, load_job_id,
              input_digest, effect_started_at
            ) VALUES (
              :command_id, 'load', 'effect_started',
              '00000000-0000-0000-0000-000000000001',
              '10000000-0000-0000-0000-000000000001', repeat('d', 64), now()
            )
            """
        ),
        {"command_id": offline_command_id},
    )
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    UPDATE ops.offline_upload_command_executions
                    SET phase = 'effect_succeeded',
                        output_digest = repeat('e', 64),
                        effect_completed_at = now()
                    WHERE command_id = :command_id
                    """
                ),
                {"command_id": offline_command_id},
            )

    for statement in (
        "UPDATE ops.backup_command_executions SET backup_id = 'foreign' "
        "WHERE command_id = :command_id",
        "UPDATE ops.backup_command_executions SET phase = 'prepared' "
        "WHERE command_id = :command_id",
        "DELETE FROM ops.backup_command_executions "
        "WHERE command_id = :command_id",
    ):
        with pytest.raises(DBAPIError):
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(statement),
                    {"command_id": backup_command_id},
                )
