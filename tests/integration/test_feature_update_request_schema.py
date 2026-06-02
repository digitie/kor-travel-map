"""``ops.feature_update_requests`` DDL 계약 검증 (ADR-045 T-205a).

T-205a는 repository 로직이 아니라 스키마 기반 PR이다. 따라서 통합 테스트도
마이그레이션 결과가 OpenAPI 계약의 기본값, FK, CHECK, 인덱스를 만족하는지에
집중한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_feature_update_request_defaults_and_job_fk(
    migrated_session: AsyncSession,
) -> None:
    job_id = (
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.import_jobs (kind, payload)
                VALUES ('feature_update_request', CAST(:payload AS jsonb))
                RETURNING job_id
                """
            ),
            {"payload": '{"request_id":"pending"}'},
        )
    ).scalar_one()

    row = (
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
                  state, dry_run, matched_scope, job_id, created_at, updated_at
                """
            ),
            {
                "job_id": job_id,
                "scope": '{"center":{"lon":126.978,"lat":37.5665},"radius_km":3.0}',
            },
        )
    ).mappings().one()

    assert row["request_id"]
    assert row["providers"] == []
    assert row["dataset_keys"] == []
    assert row["update_policy"] == {}
    assert row["priority"] == 50
    assert row["state"] == "queued"
    assert row["dry_run"] is False
    assert row["matched_scope"] == {}
    assert row["job_id"] == job_id
    assert row["created_at"] is not None
    assert row["updated_at"] is not None

    await migrated_session.execute(
        text("DELETE FROM ops.import_jobs WHERE job_id = :job_id"),
        {"job_id": job_id},
    )
    fk_after_delete = (
        await migrated_session.execute(
            text("SELECT job_id FROM ops.feature_update_requests")
        )
    ).scalar_one()
    assert fk_after_delete is None


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("scope_type", "bad_scope"),
        ("run_mode", "later"),
        ("state", "blocked"),
    ],
)
async def test_feature_update_request_check_constraints(
    migrated_session: AsyncSession,
    column: str,
    value: str,
) -> None:
    values = {
        "scope_type": "feature_ids",
        "scope": '{"feature_ids":[]}',
        "run_mode": "queued",
        "state": "queued",
    }
    values[column] = value

    with pytest.raises(IntegrityError):
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.feature_update_requests (
                  scope_type, scope, run_mode, state
                )
                VALUES (:scope_type, CAST(:scope AS jsonb), :run_mode, :state)
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
        "idx_feature_update_state_priority",
        "idx_feature_update_created",
        "idx_feature_update_job",
    }.issubset(indexes)
