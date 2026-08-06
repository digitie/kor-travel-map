"""DB operation key와 canonical dataset membership의 통합 회귀."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra.feature_operation_repo import (
    append_dagster_feature_attempt_event,
    ensure_dagster_feature_operation,
    finish_dagster_feature_membership,
    list_feature_operation_memberships,
    resolve_feature_operation_dataset_membership,
    resolve_feature_operation_memberships,
)

pytestmark = pytest.mark.integration


async def _mois_bulk_membership(
    session: AsyncSession,
) -> tuple[str, ProviderDatasetOperationMembership]:
    row = (
        await session.execute(
            text(
                """
                SELECT scope.operation_key, scope.provider_dataset_id, scope.sync_scope
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE dataset.provider = 'python-mois-api'
                  AND dataset.dataset_key = 'mois_license_features_bulk'
                  AND scope.operation_kind = 'refresh'
                ORDER BY scope.operation_key
                LIMIT 1
                """
            )
        )
    ).one()
    return (
        str(row.operation_key),
        ProviderDatasetOperationMembership(
            provider_dataset_id=int(row.provider_dataset_id),
            sync_scope=str(row.sync_scope),
            operation_key=str(row.operation_key),
        ),
    )


async def test_operation_memberships_are_read_from_db_binding(
    migrated_session: AsyncSession,
) -> None:
    operation_key, expected = await _mois_bulk_membership(migrated_session)

    memberships = await list_feature_operation_memberships(
        migrated_session,
        operation_key=operation_key,
    )
    scheduled_memberships = await resolve_feature_operation_memberships(
        migrated_session,
        operation_key=operation_key,
    )
    runtime_membership = await resolve_feature_operation_dataset_membership(
        migrated_session,
        operation_key=operation_key,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    )

    assert expected in memberships
    assert scheduled_memberships == memberships
    assert runtime_membership == expected


async def test_ensure_attempt_and_finish_use_only_canonical_membership(
    migrated_session: AsyncSession,
) -> None:
    operation_key, membership = await _mois_bulk_membership(migrated_session)
    run_id = f"tvn33-operation-{uuid4()}"
    started_at = datetime(2026, 8, 7, tzinfo=UTC)

    created = await ensure_dagster_feature_operation(
        migrated_session,
        dagster_run_id=run_id,
        trigger_kind="manual",
        selected_memberships=(membership,),
        operation_key=operation_key,
        engine_created_at=started_at,
        engine_started_at=started_at,
        observed_status="STARTED",
    )
    event = await append_dagster_feature_attempt_event(
        migrated_session,
        dagster_run_id=run_id,
        membership=membership,
        attempt_number=1,
        outcome="failed",
        error={"code": "TEST_FAILURE"},
    )
    finished = await finish_dagster_feature_membership(
        migrated_session,
        dagster_run_id=run_id,
        membership=membership,
    )

    assert created.operation.operation_key == operation_key
    assert created.operation.members[0].membership == membership
    assert event.import_job_dataset_id == created.operation.members[0].import_job_dataset_id
    assert finished.operation.status == "done"
    assert finished.operation.members[0].membership == membership
