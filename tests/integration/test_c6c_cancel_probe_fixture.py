"""C6c cancel-probe fixture의 Map 소유 영속 수명주기 통합 회귀."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import pytest
from kortravelmap.api.routers.ops_live import (
    _IMPORT_JOB_EVENTS_LIVE_SQL,
    _IMPORT_JOBS_LIVE_SQL,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.c6c_cancel_probe_fixture_repo import (
    C6C_CANCEL_PROBE_JOB_KIND,
    ensure_c6c_cancel_probe_fixture,
    finalize_c6c_cancel_probe_fixture,
    mark_c6c_cancel_probe_consumed,
)
from kortravelmap.infra.jobs_repo import record_import_job_event
from kortravelmap.infra.ops_repo import (
    get_ops_import_job,
    list_ops_import_job_events,
    list_ops_import_jobs,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    create_pipeline_cancellation_attempt,
    finish_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
    set_pipeline_cancellation_member_result,
)
from kortravelmap.infra.pipeline_repo import list_pipeline_executions
from kortravelmap.infra.status_repo import gather_status_counts

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


pytestmark = pytest.mark.integration

_UNSAFE_ERROR = {
    "code": "PIPELINE_CANCELLATION_UNSAFE",
    "message": "probe has no Dagster run to terminate",
    "details": {"fixture": "c6c"},
}


async def test_fixture_is_idempotent_consumes_only_canonical_unsafe_and_finalizes(
    migrated_session: AsyncSession,
) -> None:
    transaction_id = str(uuid4())
    status_before = await gather_status_counts(migrated_session)
    live_before = (await migrated_session.execute(text(_IMPORT_JOBS_LIVE_SQL))).one()
    fixture = await ensure_c6c_cancel_probe_fixture(
        migrated_session,
        transaction_id=transaction_id,
    )
    same_fixture = await ensure_c6c_cancel_probe_fixture(
        migrated_session,
        transaction_id=transaction_id,
    )

    assert same_fixture == fixture
    state = (
        await migrated_session.execute(
            text(
                """
                SELECT kind, status, dagster_run_id, cancellation_id
                FROM ops.import_jobs
                WHERE job_id = CAST(:job_id AS uuid)
                """
            ),
            {"job_id": fixture.job_id},
        )
    ).one()
    assert (state.kind, state.status, state.dagster_run_id, state.cancellation_id) == (
        C6C_CANCEL_PROBE_JOB_KIND,
        "running",
        None,
        None,
    )

    # generic `/ops/pipeline/executions` projection에는 fixture가 보이지 않아야 한다.
    generic_page = await list_pipeline_executions(migrated_session)
    assert fixture.job_id not in {item.id for item in generic_page.items}
    assert await get_ops_import_job(migrated_session, fixture.job_id) is None
    assert fixture.job_id not in {
        item.job_id for item in (await list_ops_import_jobs(migrated_session)).items
    }
    assert (await gather_status_counts(migrated_session)).import_jobs_by_status == (
        status_before.import_jobs_by_status
    )
    live_after = (await migrated_session.execute(text(_IMPORT_JOBS_LIVE_SQL))).one()
    assert live_after.counts_by_status == live_before.counts_by_status
    assert fixture.job_id not in {item["job_id"] for item in live_after.active_jobs}

    event_stats_before = (await migrated_session.execute(text(_IMPORT_JOBS_LIVE_SQL))).one()
    assert (
        await record_import_job_event(
            migrated_session,
            fixture.job_id,
            message="generic writer must reject fixture",
        )
    ) is None
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_job_events (job_id, level, message, payload)
            VALUES (CAST(:job_id AS uuid), 'error', 'fixture must stay private', '{}'::jsonb)
            """
        ),
        {"job_id": fixture.job_id},
    )
    assert fixture.job_id not in {
        item.job_id for item in (await list_ops_import_job_events(migrated_session)).items
    }
    event_stats_after = (await migrated_session.execute(text(_IMPORT_JOBS_LIVE_SQL))).one()
    assert (event_stats_after.latest_event_id, event_stats_after.latest_event_at) == (
        event_stats_before.latest_event_id,
        event_stats_before.latest_event_at,
    )
    fixture_events_live = (
        await migrated_session.execute(
            text(_IMPORT_JOB_EVENTS_LIVE_SQL), {"job_id": fixture.job_id}
        )
    ).one()
    assert fixture_events_live.recent_events == []

    # cancel resolver만 전용 lineage CTE로 fixture root를 읽는다.
    scope = await resolve_pipeline_cancellation_scope(
        migrated_session,
        kind="import_job",
        execution_id=fixture.job_id,
    )
    assert scope is not None
    cancellation = await create_pipeline_cancellation_attempt(
        migrated_session,
        scope=scope,
        requested_by="service:pinvi",
        reason="C6c fixture verification",
    )
    cancellation_id = cancellation.attempt.cancellation_id
    changed = await set_pipeline_cancellation_member_result(
        migrated_session,
        cancellation_id=cancellation_id,
        job_id=fixture.job_id,
        result="cancel_failed",
        terminal_status=None,
        error=_UNSAFE_ERROR,
    )
    assert changed
    finished = await finish_pipeline_cancellation_attempt(
        migrated_session,
        cancellation_id=cancellation_id,
        status="failed",
        error=_UNSAFE_ERROR,
    )
    assert finished is not None

    consumed = await mark_c6c_cancel_probe_consumed(
        migrated_session,
        job_id=fixture.job_id,
        cancellation_id=cancellation_id,
    )
    assert consumed is not None
    assert consumed.state == "consumed"
    assert consumed.cancellation_id == cancellation_id

    finalized = await finalize_c6c_cancel_probe_fixture(
        migrated_session,
        transaction_id=transaction_id,
        cancellation_id=cancellation_id,
    )
    assert finalized.state == "finalized"
    assert finalized.finalized_at is not None
    assert (
        await migrated_session.execute(
            text("SELECT status FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"),
            {"job_id": fixture.job_id},
        )
    ).scalar_one() == "failed"


async def test_normal_cancel_relay_consumes_fixture_in_its_terminal_transaction(
    migrated_engine: AsyncEngine,
) -> None:
    """PinVi가 평소 cancel API를 호출해도 Map이 durable receipt를 consume한다."""

    from kortravelmap.api.pipeline_cancellation_service import (
        PipelineCancellationUnsafe,
        cancel_pipeline_execution,
    )
    from kortravelmap.api.settings import ApiSettings

    transaction_id = str(uuid4())
    fixture = None
    cancellation_id: str | None = None
    try:
        async with (
            AsyncSession(migrated_engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            fixture = await ensure_c6c_cancel_probe_fixture(
                session,
                transaction_id=transaction_id,
            )

        async def _unexpected_dagster_call(_request: httpx.Request) -> httpx.Response:
            raise AssertionError("runless fixture cancellation must not call Dagster")

        settings = ApiSettings(
            dagster_url="http://dagster.example",
            dagster_allowed_hosts=["dagster.example"],
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_unexpected_dagster_call)
        ) as client:
            with pytest.raises(PipelineCancellationUnsafe) as raised:
                await cancel_pipeline_execution(
                    engine=migrated_engine,
                    settings=settings,
                    http_client=client,
                    kind="import_job",
                    execution_id=fixture.job_id,
                    requested_by="service:pinvi",
                    reason="C6c fixture verification",
                )
        assert raised.value.detail is not None
        cancellation_id = str(raised.value.detail.cancellation_id)

        async with AsyncSession(migrated_engine) as verify:
            consumed = await mark_c6c_cancel_probe_consumed(
                verify,
                job_id=fixture.job_id,
                cancellation_id=cancellation_id,
            )
            assert consumed is None  # service close transaction이 이미 single-consume했다.
            row = (
                await verify.execute(
                    text(
                        "SELECT state, cancellation_id::text "
                        "FROM ops.c6c_cancel_probe_fixtures "
                        "WHERE transaction_id = CAST(:transaction_id AS uuid)"
                    ),
                    {"transaction_id": transaction_id},
                )
            ).one()
        assert (row.state, row.cancellation_id) == ("consumed", cancellation_id)
    finally:
        if fixture is not None:
            async with migrated_engine.begin() as cleanup:
                await cleanup.execute(
                    text(
                        "DELETE FROM ops.c6c_cancel_probe_fixtures "
                        "WHERE transaction_id = CAST(:transaction_id AS uuid)"
                    ),
                    {"transaction_id": transaction_id},
                )
                if cancellation_id is not None:
                    await cleanup.execute(
                        text(
                            "UPDATE ops.import_jobs SET cancellation_id = NULL, "
                            "cancellation_requested_at = NULL, "
                            "cancellation_requested_by = NULL, "
                            "cancellation_reason = NULL "
                            "WHERE job_id = CAST(:job_id AS uuid)"
                        ),
                        {"job_id": fixture.job_id},
                    )
                    await cleanup.execute(
                        text(
                            "DELETE FROM ops.pipeline_cancellation_members "
                            "WHERE cancellation_id = CAST(:cancellation_id AS uuid)"
                        ),
                        {"cancellation_id": cancellation_id},
                    )
                    await cleanup.execute(
                        text(
                            "DELETE FROM ops.pipeline_cancellations "
                            "WHERE cancellation_id = CAST(:cancellation_id AS uuid)"
                        ),
                        {"cancellation_id": cancellation_id},
                    )
                await cleanup.execute(
                    text("DELETE FROM ops.import_jobs WHERE job_id = CAST(:job_id AS uuid)"),
                    {"job_id": fixture.job_id},
                )
