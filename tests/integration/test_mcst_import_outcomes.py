"""실제 MCST wrapper의 부분 성공·재시도·종결 통합 회귀.

봉인 영수증은 append-only이므로 전용 disposable DB의 수명으로 격리한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from dagster import DagsterRunStatus
from kortravelmap.dagster.feature_operation_sensors import apply_completion_record
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from tests.integration._owned_pg import scalar_container as scalar_container
from tests.integration._owned_pg import scalar_engines as scalar_engines
from tests.integration.test_canonical_provider_operations import (
    _TREE_WITH_MEMBERS_SQL,
    _tracking_context,
    _tracking_guard,
    _tracking_record,
)

pytestmark = pytest.mark.integration


async def test_mcst_actual_public_wrapper_seals_twelve_members_before_terminal_failure(
    scalar_engines: Any,
) -> None:
    """실제 wrapper → load/sync → 완료 command → terminal 경로의 12/13 회귀."""
    import logging
    from typing import cast

    from dagster import Failure
    from kortravelmap.dagster.mcst_features import feature_place_mcst_culture

    from kortravelmap.infra.ops_repo import list_ops_import_job_events
    from kortravelmap.providers.mcst import MCST_FILE_DATASETS, McstSlugAttempt, McstSlugFailure

    migrated_engine, runtime = scalar_engines
    client = AsyncKorTravelMapClient(runtime)
    operation_key = "feature_place_mcst_culture_job"
    memberships = await client.resolve_feature_operation_memberships(operation_key=operation_key)
    assert len(memberships) == 13
    guard = _tracking_guard(
        client,  # type: ignore[arg-type]
        operation_key=operation_key,
        memberships=memberships,
        run_id=f"run-mcst-actual-wrapper-{uuid4()}",
    )
    ctx = _tracking_context(guard, retry_number=0)
    ctx.log = logging.getLogger("test-mcst-outcomes")
    ctx.add_output_metadata = lambda _metadata: None
    failing_slug = tuple(MCST_FILE_DATASETS)[-1]
    ctx.resources.mcst_culture_records = [
        *(McstSlugAttempt(slug) for slug in MCST_FILE_DATASETS),
        McstSlugFailure(failing_slug, "DOWNLOAD_CHECK_FAILED", retryable=True),
    ]
    wrapper = cast(Any, feature_place_mcst_culture.op.compute_fn).decorated_fn
    root_id: str | None = None
    with pytest.raises(Failure):
        await wrapper(ctx)
    snapshot = await guard.ensure()
    assert snapshot is not None
    root_id = snapshot.operation.root_job_id
    before = snapshot.operation
    done_before = {m.job_id: m for m in before.members if m.status == "done"}
    assert len(done_before) == 12
    assert all(m.progress == 100 and m.finished_at is not None for m in done_before.values())
    async with AsyncSession(migrated_engine) as db:
        first_events = await list_ops_import_job_events(
            db,
            root_id,
            include_direct_children=True,
            level="error",
            limit=1,
        )
        assert len(first_events.items) == 1
        assert first_events.items[0].payload["error"] == {
            "code": "MCST_DATASET_FETCH_FAILED",
            "phase": "fetch",
            "reason": "DOWNLOAD_CHECK_FAILED",
            "retryable": True,
        }
        assert first_events.items[0].job_id not in done_before
        assert first_events.next_cursor is None
        receipt_before = (
            await db.execute(
                text(
                    "SELECT provider_dataset_id, sync_scope, input_member_count, "
                    "source_input_set_hash, observed_at "
                    "FROM ops.curation_provider_snapshot_receipts "
                    "WHERE root_job_id=CAST(:root AS uuid) ORDER BY provider_dataset_id"
                ),
                {"root": root_id},
            )
        ).all()
    assert len(receipt_before) == 12

    ctx.retry_number = 1
    with pytest.raises(Failure):
        await wrapper(ctx)
    after_retry = await guard.ensure()
    assert after_retry is not None
    assert {m.job_id: m for m in after_retry.operation.members if m.status == "done"} == done_before

    finished_at = datetime.now(UTC) + timedelta(seconds=1)
    outcome = await apply_completion_record(
        _tracking_record(
            operation_key=operation_key,
            run_id=guard.dagster_run_id,
            status=DagsterRunStatus.FAILURE,
            created_at=datetime(2026, 7, 16, 1, tzinfo=UTC),
            started_at=datetime(2026, 7, 16, 1, 0, 1, tzinfo=UTC),
            finished_at=finished_at,
            trigger_kind="manual",
        ),
        client,
    )
    assert outcome == "applied"
    async with AsyncSession(migrated_engine) as db:
        rows = (await db.execute(text(_TREE_WITH_MEMBERS_SQL), {"root_id": root_id})).all()
        receipts_after = (
            await db.execute(
                text(
                    "SELECT provider_dataset_id, sync_scope, input_member_count, "
                    "source_input_set_hash, observed_at "
                    "FROM ops.curation_provider_snapshot_receipts "
                    "WHERE root_job_id=CAST(:root AS uuid) ORDER BY provider_dataset_id"
                ),
                {"root": root_id},
            )
        ).all()
        events = await list_ops_import_job_events(
            db,
            root_id,
            include_direct_children=True,
            level="error",
            limit=1,
        )
        assert events.next_cursor is not None
        older = await list_ops_import_job_events(
            db,
            root_id,
            include_direct_children=True,
            cursor=events.next_cursor,
            level="error",
            limit=1,
        )
        assert events.items[0].event_id != older.items[0].event_id
        with pytest.raises(ValueError, match="filter"):
            await list_ops_import_job_events(db, root_id, cursor=events.next_cursor)
    root, *children = rows
    assert root.status == "failed"
    assert root.progress == 92
    assert sum(m.status == "done" for m in children) == 12
    assert sum(m.status == "failed" for m in children) == 1
    assert all(
        m.finished_at == done_before[str(m.job_id)].finished_at
        for m in children
        if m.status == "done"
    )
    assert receipts_after == receipt_before


async def test_narrowed_mcst_manifest_ignores_disabled_foreign_dataset_before_load(
    scalar_engines: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import logging
    from dataclasses import replace
    from typing import cast

    from kortravelmap.dagster import mcst_features
    from kortravelmap.dagster.feature_operation_tracking import (
        EXECUTION_SCOPES_TAG,
        DeclaredExecutionScope,
        encode_execution_scopes,
    )

    from kortravelmap.providers.mcst import MCST_FILE_DATASETS, McstSlugAttempt

    admin, runtime = scalar_engines
    client = AsyncKorTravelMapClient(runtime)
    specs = tuple(MCST_FILE_DATASETS.values())
    selected = specs[0]
    excluded = specs[-1]
    key = "feature_place_mcst_culture_job"
    member = await client.resolve_feature_operation_dataset_membership(
        operation_key=key, provider="python-mcst-api", dataset_key=selected.dataset_key,
    )
    scope = DeclaredExecutionScope("python-mcst-api", selected.dataset_key, "dataset_wide")
    guard = replace(_tracking_guard(
        client,  # type: ignore[arg-type]
        operation_key=key, memberships=(member,), run_id=f"mcst-narrow-{uuid4()}",
        extra_tags={EXECUTION_SCOPES_TAG: encode_execution_scopes((scope,))},
    ), declared_scopes=(scope,))
    ctx = _tracking_context(guard, retry_number=0)
    ctx.log = logging.getLogger("test-mcst-narrow")
    ctx.add_output_metadata = lambda _metadata: None
    ctx.resources.mcst_culture_records = [McstSlugAttempt(slug) for slug in MCST_FILE_DATASETS]
    calls: list[str] = []
    original = mcst_features._load

    async def load(context: Any, **kwargs: Any) -> Any:
        calls.append(kwargs["dataset_key"])
        return await original(context, **kwargs)

    monkeypatch.setattr(mcst_features, "_load", load)
    async with AsyncSession(admin) as db:
        await db.execute(text(
            "UPDATE provider_sync.provider_dataset_operations SET is_enabled=false "
            "WHERE operation_key=:key AND provider_dataset_id=("
            "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
            "WHERE provider='python-mcst-api' AND dataset_key=:dataset)"
        ), {"key": key, "dataset": excluded.dataset_key})
        await db.commit()
    try:
        wrapper = cast(Any, mcst_features.feature_place_mcst_culture.op.compute_fn).decorated_fn
        first = await wrapper(ctx)
        ctx.retry_number = 1
        second = await wrapper(ctx)
        assert calls == [selected.dataset_key]
        assert len(first.results) == 1
        assert len(second.results) == 0
        snapshot = await guard.ensure()
        assert snapshot is not None
        assert len(snapshot.operation.members) == 1
        assert snapshot.operation.members[0].status == "done"
    finally:
        async with AsyncSession(admin) as db:
            await db.execute(text(
                "UPDATE provider_sync.provider_dataset_operations SET is_enabled=true "
                "WHERE operation_key=:key AND provider_dataset_id=("
                "SELECT provider_dataset_id FROM provider_sync.provider_datasets "
                "WHERE provider='python-mcst-api' AND dataset_key=:dataset)"
            ), {"key": key, "dataset": excluded.dataset_key})
            await db.commit()
