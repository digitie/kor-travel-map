"""``ops.feature_update_requests`` DDL 계약 검증 (ADR-045 T-205a).

T-205a는 repository 로직이 아니라 스키마 기반 PR이다. 따라서 통합 테스트도
마이그레이션 결과가 OpenAPI 계약의 기본값, FK, CHECK, 인덱스를 만족하는지에
집중한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_feature_update_idempotency_ledger_is_actor_scoped_and_append_only(
    migrated_session: AsyncSession,
) -> None:
    idempotency_key = "94000000-0000-4000-8000-000000000001"
    first_request_id = "94000000-0000-4000-8000-000000000002"
    second_request_id = "94000000-0000-4000-8000-000000000003"

    async def _seed_request(*, actor: str, request_id: str) -> None:
        job_id = (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (kind, payload, trigger_kind)
                    VALUES ('feature_update_request', '{}'::jsonb, 'update_request')
                    RETURNING job_id
                    """
                )
            )
        ).scalar_one()
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.feature_update_requests (
                  request_id, scope_type, scope, run_mode, job_id, operator
                ) VALUES (
                  CAST(:request_id AS uuid), 'feature_ids',
                  '{"type":"feature_ids","feature_ids":["feature-1"]}'::jsonb,
                  'queued', :job_id, :actor
                )
                """
            ),
            {"request_id": request_id, "job_id": job_id, "actor": actor},
        )

    await _seed_request(actor="actor-a", request_id=first_request_id)
    await _seed_request(actor="actor-b", request_id=second_request_id)
    for actor, request_id, reused in (
        ("actor-a", first_request_id, False),
        ("actor-b", second_request_id, True),
    ):
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.feature_update_request_idempotency (
                  actor, idempotency_key, request_fingerprint, request_id,
                  reused_active_request
                ) VALUES (
                  :actor, CAST(:idempotency_key AS uuid), repeat('a', 64),
                  CAST(:request_id AS uuid), :reused
                )
                """
            ),
            {
                "actor": actor,
                "idempotency_key": idempotency_key,
                "request_id": request_id,
                "reused": reused,
            },
        )

    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT actor, fingerprint_version, request_id::text,
                       reused_active_request, created_at
                FROM ops.feature_update_request_idempotency
                WHERE idempotency_key = CAST(:idempotency_key AS uuid)
                ORDER BY actor
                """
            ),
            {"idempotency_key": idempotency_key},
        )
    ).all()
    assert [
        (
            row.actor,
            row.fingerprint_version,
            row.request_id,
            row.reused_active_request,
            row.created_at is not None,
        )
        for row in rows
    ] == [
        ("actor-a", 1, first_request_id, False, True),
        ("actor-b", 1, second_request_id, True, True),
    ]
    constraints = dict(
        (
            await migrated_session.execute(
                text(
                    """
                    SELECT conname, pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conrelid = 'ops.feature_update_request_idempotency'::regclass
                      AND contype IN ('p','f')
                    """
                )
            )
        ).all()
    )
    assert constraints["pk_feature_update_request_idempotency"] == (
        "PRIMARY KEY (actor, idempotency_key)"
    )
    assert (
        "FOREIGN KEY (request_id)"
        in constraints["fk_feature_update_request_idempotency_request_id_feature_update_requests"]
    )
    assert (
        "ON DELETE RESTRICT"
        in constraints["fk_feature_update_request_idempotency_request_id_feature_update_requests"]
    )
    request_index = await migrated_session.scalar(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'ops'
              AND indexname = 'idx_feature_update_request_idempotency_request'
            """
        )
    )
    assert request_index is not None
    assert "(request_id)" in request_index

    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO ops.feature_update_request_idempotency (
                      actor, idempotency_key, request_fingerprint, request_id,
                      reused_active_request
                    ) VALUES (
                      'actor-b', '94000000-0000-4000-8000-000000000004',
                      repeat('b', 64), CAST(:request_id AS uuid), false
                    )
                    """
                ),
                {"request_id": first_request_id},
            )

    for statement in (
        "UPDATE ops.feature_update_request_idempotency "
        "SET reused_active_request = true WHERE actor = 'actor-a'",
        "DELETE FROM ops.feature_update_request_idempotency WHERE actor = 'actor-a'",
        "TRUNCATE ops.feature_update_request_idempotency",
    ):
        with pytest.raises(DBAPIError):
            async with migrated_session.begin_nested():
                await migrated_session.execute(text(statement))


async def test_feature_update_request_defaults_and_job_fk(
    migrated_session: AsyncSession,
) -> None:
    job_id = (
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.import_jobs (kind, payload, trigger_kind)
                VALUES (
                  'feature_update_request', '{}'::jsonb, 'update_request'
                )
                RETURNING job_id
                """
            ),
        )
    ).scalar_one()

    row = (
        (
            await migrated_session.execute(
                text(
                    """
                INSERT INTO ops.feature_update_requests (
                  scope_type, scope, run_mode, job_id, operator, reason
                )
                VALUES (
                  'center_radius',
                  CAST(:scope AS jsonb),
                  'queued',
                  :job_id,
                  'local-admin',
                  'schema smoke'
                )
                RETURNING
                  request_id, providers, dataset_keys, update_policy, priority,
                  matched_scope, job_id, created_at, generation
                """
                ),
                {
                    "job_id": job_id,
                    "scope": (
                        '{"type":"center_radius",'
                        '"center":{"lon":126.978,"lat":37.5665},'
                        '"radius_km":3.0}'
                    ),
                },
            )
        )
        .mappings()
        .one()
    )

    assert row["request_id"]
    assert row["providers"] == []
    assert row["dataset_keys"] == []
    assert row["update_policy"] == {}
    assert row["priority"] == 50
    assert row["matched_scope"] == {}
    assert row["job_id"] == job_id
    assert row["created_at"] is not None
    assert row["generation"] == 1


async def test_feature_update_request_job_pair_is_bidirectional_and_immutable(
    migrated_session: AsyncSession,
) -> None:
    request_id = "91000000-0000-4000-8000-000000000001"
    job_id = "92000000-0000-4000-8000-000000000002"
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
              job_id, kind, payload, status, trigger_kind
            ) VALUES (
              :job_id, 'feature_update_request', '{}'::jsonb, 'queued',
              'update_request'
            )
            """
        ),
        {"job_id": job_id},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_update_requests (
              request_id, scope_type, scope, run_mode, job_id
            ) VALUES (
              :request_id, 'feature_ids',
              '{"type":"feature_ids","feature_ids":[]}'::jsonb,
              'queued', :job_id
            )
            """
        ),
        {"request_id": request_id, "job_id": job_id},
    )
    await migrated_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await migrated_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))

    async def insert_unpaired_feature_update_job() -> None:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      kind, payload, status, trigger_kind
                    ) VALUES (
                      'feature_update_request', '{}'::jsonb, 'queued',
                      'update_request'
                    )
                    """
                )
            )
            await migrated_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    with pytest.raises(IntegrityError):
        await insert_unpaired_feature_update_job()

    async def delete_linked_request() -> None:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text("DELETE FROM ops.feature_update_requests WHERE request_id = :request_id"),
                {"request_id": request_id},
            )
            await migrated_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    with pytest.raises(IntegrityError):
        await delete_linked_request()

    other_job_id = "93000000-0000-4000-8000-000000000003"
    await migrated_session.execute(
        text(
            "INSERT INTO ops.import_jobs (job_id, kind, payload) "
            "VALUES (:job_id, 'generic', '{}'::jsonb)"
        ),
        {"job_id": other_job_id},
    )
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE ops.feature_update_requests SET job_id = :other_job_id "
                    "WHERE request_id = :request_id"
                ),
                {"request_id": request_id, "other_job_id": other_job_id},
            )

    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text("DELETE FROM ops.import_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
    fk_after_rejected_delete = (
        await migrated_session.execute(
            text("SELECT job_id FROM ops.feature_update_requests WHERE request_id = :request_id"),
            {"request_id": request_id},
        )
    ).scalar_one()
    assert str(fk_after_rejected_delete) == job_id

    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE ops.import_jobs "
                    "SET payload = jsonb_build_object('duplicate', true) "
                    "WHERE job_id = :job_id"
                ),
                {"job_id": job_id},
            )


async def test_feature_update_request_mutation_guard_and_generation_cas(
    migrated_session: AsyncSession,
) -> None:
    job_id = (
        await migrated_session.execute(
            text(
                "INSERT INTO ops.import_jobs (kind, payload, trigger_kind) "
                "VALUES ('feature_update_request', '{}'::jsonb, 'update_request') "
                "RETURNING job_id"
            )
        )
    ).scalar_one()
    request_id = (
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.feature_update_requests (
                  scope_type, scope, run_mode, job_id
                ) VALUES (
                  'feature_ids', '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                  'queued', :job_id
                )
                RETURNING request_id
                """
            ),
            {"job_id": job_id},
        )
    ).scalar_one()

    await migrated_session.execute(
        text(
            "UPDATE ops.feature_update_requests "
            "SET matched_scope = jsonb_build_object('feature_count', 0), "
            "generation = generation + 1 "
            "WHERE request_id = :request_id"
        ),
        {"request_id": request_id},
    )
    generation = (
        await migrated_session.execute(
            text(
                "SELECT generation FROM ops.feature_update_requests WHERE request_id = :request_id"
            ),
            {"request_id": request_id},
        )
    ).scalar_one()
    assert generation == 2

    for statement in (
        "UPDATE ops.feature_update_requests SET priority = 99 WHERE request_id = :request_id",
        "UPDATE ops.feature_update_requests SET generation = generation + 2 "
        "WHERE request_id = :request_id",
    ):
        with pytest.raises(IntegrityError):
            async with migrated_session.begin_nested():
                await migrated_session.execute(text(statement), {"request_id": request_id})

    await migrated_session.execute(
        text("UPDATE ops.import_jobs SET status = 'done' WHERE job_id = :job_id"),
        {"job_id": job_id},
    )
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE ops.feature_update_requests SET generation = generation + 1 "
                    "WHERE request_id = :request_id"
                ),
                {"request_id": request_id},
            )


async def test_feature_update_request_running_job_requires_owner(
    migrated_session: AsyncSession,
) -> None:
    job_id = (
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.import_jobs (
                  kind, payload, status, trigger_kind
                ) VALUES (
                  'feature_update_request', '{}'::jsonb, 'queued',
                  'update_request'
                )
                RETURNING job_id
                """
            )
        )
    ).scalar_one()
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_update_requests (
              scope_type, scope, run_mode, job_id
            ) VALUES (
              'feature_ids', '{"type":"feature_ids","feature_ids":[]}'::jsonb,
              'queued', :job_id
            )
            """
        ),
        {"job_id": job_id},
    )
    await migrated_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await migrated_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))

    definition = (
        await migrated_session.execute(
            text(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE connamespace = 'ops'::regnamespace
                  AND conname = 'ck_import_jobs_update_request_shape'
                """
            )
        )
    ).scalar_one()
    assert "dagster_run_id = btrim(dagster_run_id)" in definition
    assert "dagster_run_id <> ''" in definition
    assert "status <> 'queued'" in definition
    assert "dagster_run_id IS NULL" in definition
    assert "status <> 'running'" in definition
    assert "dagster_run_id IS NOT NULL" in definition

    invalid_updates = (
        (
            "UPDATE ops.import_jobs SET dagster_run_id = :owner WHERE job_id = :job_id",
            "queued-owner-is-invalid",
        ),
        (
            "UPDATE ops.import_jobs SET status = 'running', dagster_run_id = :owner "
            "WHERE job_id = :job_id",
            None,
        ),
        (
            "UPDATE ops.import_jobs SET status = 'running', dagster_run_id = :owner "
            "WHERE job_id = :job_id",
            "",
        ),
        (
            "UPDATE ops.import_jobs SET status = 'done', dagster_run_id = :owner "
            "WHERE job_id = :job_id",
            " padded-owner ",
        ),
    )
    for statement, owner in invalid_updates:
        with pytest.raises(IntegrityError):
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(statement),
                    {"job_id": job_id, "owner": owner},
                )

    await migrated_session.execute(
        text(
            """
            UPDATE ops.import_jobs
               SET status = 'running', dagster_run_id = 'schema-running-owner'
             WHERE job_id = :job_id
            """
        ),
        {"job_id": job_id},
    )
    status, owner = (
        await migrated_session.execute(
            text("SELECT status, dagster_run_id FROM ops.import_jobs WHERE job_id = :job_id"),
            {"job_id": job_id},
        )
    ).one()
    assert status == "running"
    assert owner == "schema-running-owner"


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("scope_type", "bad_scope"),
        ("run_mode", "later"),
    ],
)
async def test_feature_update_request_check_constraints(
    migrated_session: AsyncSession,
    column: str,
    value: str,
) -> None:
    values = {
        "scope_type": "feature_ids",
        "scope": '{"type":"feature_ids","feature_ids":[]}',
        "run_mode": "queued",
    }
    values[column] = value
    values["job_id"] = (
        await migrated_session.execute(
            text(
                "INSERT INTO ops.import_jobs (kind, payload, trigger_kind) "
                "VALUES ('feature_update_request', '{}'::jsonb, 'update_request') "
                "RETURNING job_id"
            )
        )
    ).scalar_one()

    with pytest.raises(IntegrityError):
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.feature_update_requests (
                  scope_type, scope, run_mode, job_id
                )
                VALUES (
                  :scope_type, CAST(:scope AS jsonb), :run_mode, :job_id
                )
                """
            ),
            values,
        )


async def test_feature_update_request_indexes_exist(
    migrated_session: AsyncSession,
) -> None:
    indexes = {
        row[0]
        for row in (
            await migrated_session.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'ops'
                      AND tablename = 'feature_update_requests'
                    """
                )
            )
        ).all()
    }
    assert {
        "idx_feature_update_priority",
        "idx_feature_update_created",
        "uq_feature_update_requests_job_id",
    }.issubset(indexes)
