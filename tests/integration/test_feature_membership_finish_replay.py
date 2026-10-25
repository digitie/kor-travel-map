"""정본 lifecycle로 완료한 root의 후속 finish가 DML 없이 원완료를 읽는다."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text

from kortravelmap.core.feature_operation import FeatureOperationInvariantConflict
from kortravelmap.infra.feature_operation_repo import (
    ensure_dagster_feature_operation,
    finish_dagster_feature_membership,
    reconcile_dagster_feature_run,
)
from kortravelmap.infra.pipeline_cancellation_repo import lock_provider_feature_finalization
from tests.integration._membership_seed import (
    SINGLE_MEMBER_OPERATION,
    memberships_for_operation,
)
from tests.integration.conftest import as_dagster_runtime

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _state(session: AsyncSession, root: str) -> object:
    return await session.scalar(
        text(
            """
            SELECT jsonb_build_array(
              (SELECT jsonb_agg(to_jsonb(job) ORDER BY job.job_id)
               FROM ops.import_jobs job
               WHERE job.job_id=CAST(:root AS uuid) OR job.parent_job_id=CAST(:root AS uuid)),
              (SELECT jsonb_agg(to_jsonb(member) ORDER BY member.import_job_dataset_id)
               FROM ops.import_job_datasets member JOIN ops.import_jobs job
                 ON job.job_id=member.job_id
               WHERE job.parent_job_id=CAST(:root AS uuid)),
              (SELECT jsonb_agg(to_jsonb(receipt) ORDER BY receipt.source_job_id)
               FROM ops.curation_provider_snapshot_receipts receipt
               WHERE receipt.root_job_id=CAST(:root AS uuid))
            )
            """
        ),
        {"root": root},
    )


@pytest.mark.parametrize("terminal", ["SUCCESS", "FAILURE", "CANCELED"])
async def test_terminal_root_finish_preserves_original_tracking_state(
    migrated_session: AsyncSession, terminal: str
) -> None:
    # row나 manifest를 읽기 전에 정본 P EX→L을 취득한다. guard 비활성화/raw status UPDATE0.
    async with as_dagster_runtime(migrated_session) as session:
        await lock_provider_feature_finalization(session)
    membership = (
        await memberships_for_operation(migrated_session, operation_key=SINGLE_MEMBER_OPERATION)
    )[0]
    run = "finish-success-race-" + str(uuid4())
    created = datetime(2026, 10, 25, tzinfo=UTC)
    async with as_dagster_runtime(migrated_session) as session:
        await ensure_dagster_feature_operation(
            session,
            dagster_run_id=run,
            trigger_kind="manual",
            selected_memberships=(membership,),
            operation_key=membership.operation_key,
            engine_created_at=created,
            engine_started_at=created,
            observed_status="STARTED",
        )
        completed = await finish_dagster_feature_membership(
            session, dagster_run_id=run, membership=membership
        )
        assert completed.outcome == "applied"
        terminal_result = await reconcile_dagster_feature_run(
            session,
            dagster_run_id=run,
            trigger_kind="manual",
            terminal_status=terminal,
            selected_memberships=(membership,),
            operation_key=membership.operation_key,
            engine_created_at=created,
            engine_started_at=created,
            engine_finished_at=created + timedelta(seconds=1),
            error=None,
        )
        assert terminal_result.operation.dagster_run_status == terminal
        root = terminal_result.operation.root_job_id
    before = await _state(migrated_session, root)
    async with as_dagster_runtime(migrated_session) as session:
        replay = await finish_dagster_feature_membership(
            session,
            dagster_run_id=run,
            membership=membership,
            authoritative_snapshot_complete=True,
        )
        assert replay.outcome == ("noop" if terminal == "SUCCESS" else "blocked")
        if terminal == "SUCCESS":
            for foreign in (
                replace(membership, provider_dataset_id=membership.provider_dataset_id + 9999),
                replace(membership, sync_scope="target_grids"),
                replace(membership, operation_key="feature_other_job"),
            ):
                with pytest.raises(FeatureOperationInvariantConflict, match="frozen run selection"):
                    await finish_dagster_feature_membership(
                        session, dagster_run_id=run, membership=foreign
                    )
    assert await _state(migrated_session, root) == before
