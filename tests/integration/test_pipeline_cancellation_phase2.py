"""pipeline cancellation의 canonical root 예약 통합 회귀."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.jobs_repo import enqueue_unpaired_import_job
from kortravelmap.infra.pipeline_cancellation_repo import (
    create_pipeline_cancellation_attempt,
    get_pipeline_cancellation_detail,
    resolve_pipeline_cancellation_scope,
)

pytestmark = pytest.mark.integration


async def test_cancellation_reserves_one_generic_import_root(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_unpaired_import_job(
        migrated_session,
        kind="cancellation-integration-fixture",
        payload={"fixture": str(uuid4())},
        source_checksum=None,
    )
    scope = await resolve_pipeline_cancellation_scope(
        migrated_session,
        kind="import_job",
        execution_id=job.job_id,
    )

    assert scope is not None
    attempt = await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=scope,
        requested_by="admin:integration-test",
        reason="canonical cancellation reservation",
    )
    detail = await get_pipeline_cancellation_detail(
        migrated_session,
        attempt.attempt.cancellation_id,
    )

    assert detail is not None
    assert detail.root_id == job.job_id
    assert detail.root_kind == "import_job"
    assert len(detail.members) == 1
    assert detail.members[0].job_id == job.job_id


async def test_cancellation_scope_does_not_synthesize_provider_dataset_identity(
    migrated_session: AsyncSession,
) -> None:
    job = await enqueue_unpaired_import_job(
        migrated_session,
        kind="cancellation-integration-fixture",
        payload={"fixture": str(uuid4())},
        source_checksum=None,
    )

    scope = await resolve_pipeline_cancellation_scope(
        migrated_session,
        kind="import_job",
        execution_id=job.job_id,
    )

    assert scope is not None
    assert scope.provider_datasets == ()
