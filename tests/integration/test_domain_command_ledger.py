"""T-VN-12 domain command ledger 스키마 불변식."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


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
