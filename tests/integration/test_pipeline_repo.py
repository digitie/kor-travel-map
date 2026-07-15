"""파이프라인 root projection 통합 테스트 (ADR-064 T-ADM-C3b)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.infra import pipeline_repo
from kortravelmap.infra.pipeline_repo import (
    get_pipeline_status_counts,
    list_pipeline_executions,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_T0 = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
_JOB_ROOT = "11111111-1111-4111-8111-111111111111"
_JOB_CHILD = "22222222-2222-4222-8222-222222222222"
_JOB_GRANDCHILD = "33333333-3333-4333-8333-333333333333"
_REQUEST_OWNER = "44444444-4444-4444-8444-444444444444"
_REQUEST_LOSER = "55555555-5555-4555-8555-555555555555"

_INSERT_JOB_SQL = text(
    """
    INSERT INTO ops.import_jobs (
        job_id, kind, parent_job_id, payload, status, progress, current_stage,
        created_at, started_at, dagster_run_id
    ) VALUES (
        CAST(:job_id AS uuid), :kind, CAST(:parent_job_id AS uuid),
        CAST(:payload AS jsonb), :status, :progress, :current_stage,
        :created_at, :started_at, :dagster_run_id
    )
    """
)

_INSERT_REQUEST_SQL = text(
    """
    INSERT INTO ops.feature_update_requests (
        request_id, scope_type, scope, providers, dataset_keys, update_policy,
        run_mode, priority, status, dry_run, matched_scope, job_id,
        dagster_run_id, operator, created_at
    ) VALUES (
        CAST(:request_id AS uuid), :scope_type, CAST(:scope AS jsonb),
        CAST(:providers AS jsonb), CAST(:dataset_keys AS jsonb), '{}'::jsonb,
        'queued', :priority, :status, false, '{}'::jsonb,
        CAST(:job_id AS uuid), :dagster_run_id, :operator, :created_at
    )
    """
)

_INSERT_EVENT_SQL = text(
    """
    INSERT INTO ops.import_job_events (
        event_id, job_id, provider, dataset_key, level, message, occurred_at
    ) VALUES (
        CAST(:event_id AS uuid), CAST(:job_id AS uuid), :provider, :dataset_key,
        'info', 'seed', :occurred_at
    )
    """
)


async def _job(
    session: AsyncSession,
    job_id: str,
    *,
    parent_job_id: str | None = None,
    created_at: datetime = _T0,
    status: str = "queued",
    progress: int = 0,
    payload: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        _INSERT_JOB_SQL,
        {
            "job_id": job_id,
            "kind": "provider_load",
            "parent_job_id": parent_job_id,
            "payload": json.dumps(payload or {}),
            "status": status,
            "progress": progress,
            "current_stage": "loading" if status == "running" else None,
            "created_at": created_at,
            "started_at": created_at if status == "running" else None,
            "dagster_run_id": f"run-{job_id[:8]}",
        },
    )


async def _request(
    session: AsyncSession,
    request_id: str,
    *,
    job_id: str | None,
    created_at: datetime,
    providers: tuple[str, ...] = (),
    dataset_keys: tuple[str, ...] = (),
    scope: dict[str, Any] | None = None,
) -> None:
    request_scope = scope or {"type": "feature_ids", "feature_ids": ["f-1"]}
    await session.execute(
        _INSERT_REQUEST_SQL,
        {
            "request_id": request_id,
            "scope_type": request_scope["type"],
            "scope": json.dumps(request_scope),
            "providers": json.dumps(providers),
            "dataset_keys": json.dumps(dataset_keys),
            "priority": 50,
            "status": "queued",
            "job_id": job_id,
            "dagster_run_id": f"request-run-{request_id[:8]}",
            "operator": "tester",
            "created_at": created_at,
        },
    )


async def _event(
    session: AsyncSession,
    event_id: str,
    *,
    job_id: str,
    provider: str | None,
    dataset_key: str | None,
) -> None:
    await session.execute(
        _INSERT_EVENT_SQL,
        {
            "event_id": event_id,
            "job_id": job_id,
            "provider": provider,
            "dataset_key": dataset_key,
            "occurred_at": _T0,
        },
    )


async def _seed_owned_hierarchy(session: AsyncSession) -> None:
    await _job(session, _JOB_ROOT, created_at=_T0)
    await _job(
        session,
        _JOB_CHILD,
        parent_job_id=_JOB_ROOT,
        created_at=_T0 + timedelta(minutes=1),
        status="running",
        progress=40,
    )
    await _job(
        session,
        _JOB_GRANDCHILD,
        parent_job_id=_JOB_CHILD,
        created_at=_T0 + timedelta(minutes=2),
        status="failed",
        progress=70,
    )
    await _request(
        session,
        _REQUEST_OWNER,
        job_id=_JOB_ROOT,
        created_at=_T0 + timedelta(minutes=3),
        providers=("stored-b", "stored-a", "stored-b"),
        dataset_keys=("dataset-b", "dataset-a"),
    )


async def test_request_anchor_collapses_descendants_and_projects_deepest_job(
    migrated_session: AsyncSession,
) -> None:
    await _seed_owned_hierarchy(migrated_session)

    page = await list_pipeline_executions(migrated_session)

    assert [(item.kind, item.id) for item in page.items] == [("update_request", _REQUEST_OWNER)]
    root = page.items[0]
    assert root.lineage_owner is True
    assert root.requested_job_id == _JOB_ROOT
    assert root.linked_job_count == 3
    assert root.providers == ("stored-b", "stored-a", "stored-b")
    assert root.dataset_keys == ("dataset-b", "dataset-a")
    assert root.progress is None
    assert root.projected_job is not None
    assert root.projected_job.id == _JOB_GRANDCHILD
    assert root.projected_job.depth == 2
    assert root.projected_job.status == "failed"


async def test_standalone_hierarchy_uses_sorted_event_identity_and_ignores_payload(
    migrated_session: AsyncSession,
) -> None:
    await _job(
        migrated_session,
        _JOB_ROOT,
        payload={"provider": "misleading", "dataset_key": "wrong"},
    )
    await _job(migrated_session, _JOB_CHILD, parent_job_id=_JOB_ROOT)
    await _job(migrated_session, _JOB_GRANDCHILD, parent_job_id=_JOB_CHILD)
    await _event(
        migrated_session,
        "61111111-1111-4111-8111-111111111111",
        job_id=_JOB_ROOT,
        provider="provider-z",
        dataset_key="dataset-z",
    )
    await _event(
        migrated_session,
        "62222222-2222-4222-8222-222222222222",
        job_id=_JOB_CHILD,
        provider="provider-a",
        dataset_key="dataset-a",
    )
    await _event(
        migrated_session,
        "63333333-3333-4333-8333-333333333333",
        job_id=_JOB_GRANDCHILD,
        provider="provider-a",
        dataset_key="",
    )
    await _event(
        migrated_session,
        "64444444-4444-4444-8444-444444444444",
        job_id=_JOB_GRANDCHILD,
        provider=None,
        dataset_key=None,
    )

    page = await list_pipeline_executions(migrated_session)

    assert len(page.items) == 1
    root = page.items[0]
    assert root.id == _JOB_ROOT
    assert root.linked_job_count == 3
    assert root.providers == ("provider-a", "provider-z")
    assert root.dataset_keys == ("dataset-a", "dataset-z")
    assert root.projected_job is not None
    assert root.projected_job.id == _JOB_GRANDCHILD
    assert [
        item.id
        for item in (
            await list_pipeline_executions(
                migrated_session, provider="provider-a", dataset_key="dataset-z"
            )
        ).items
    ] == [_JOB_ROOT]
    assert (await list_pipeline_executions(migrated_session, provider="misleading")).items == ()


async def test_missing_parent_is_self_root_and_cycle_has_one_canonical_root(
    migrated_session: AsyncSession,
) -> None:
    missing = "71111111-1111-4111-8111-111111111111"
    absent = "7fffffff-ffff-4fff-8fff-ffffffffffff"
    cycle_a = "81111111-1111-4111-8111-111111111111"
    cycle_b = "82222222-2222-4222-8222-222222222222"
    await migrated_session.execute(text("SET LOCAL session_replication_role = replica"))
    await _job(migrated_session, missing, parent_job_id=absent)
    await _job(migrated_session, cycle_a, parent_job_id=cycle_b)
    await _job(migrated_session, cycle_b, parent_job_id=cycle_a)
    await migrated_session.execute(text("SET LOCAL session_replication_role = origin"))

    page = await list_pipeline_executions(migrated_session)

    roots = {item.id: item for item in page.items}
    assert set(roots) == {missing, cycle_a}
    assert roots[missing].linked_job_count == 1
    assert roots[cycle_a].linked_job_count == 2
    assert sum(item.linked_job_count for item in roots.values()) == 3


async def test_duplicate_requests_on_same_anchor_choose_one_owner_and_keep_loser(
    migrated_session: AsyncSession,
) -> None:
    await _seed_owned_hierarchy(migrated_session)
    await _request(
        migrated_session,
        _REQUEST_LOSER,
        job_id=_JOB_ROOT,
        created_at=_T0 + timedelta(minutes=4),
    )

    page = await list_pipeline_executions(migrated_session)

    by_id = {item.id: item for item in page.items}
    assert set(by_id) == {_REQUEST_OWNER, _REQUEST_LOSER}
    owner = by_id[_REQUEST_OWNER]
    loser = by_id[_REQUEST_LOSER]
    # 같은 anchor에서는 created_at/id가 빠른 request 하나만 owner다.
    assert owner.lineage_owner is True
    assert owner.linked_job_count == 3
    assert loser.lineage_owner is False
    assert loser.requested_job_id == _JOB_ROOT
    assert loser.linked_job_count == 0
    assert loser.projected_job is None
    assert sum(item.linked_job_count for item in page.items) == 3


async def test_nested_request_anchor_splits_parent_branch(
    migrated_session: AsyncSession,
) -> None:
    await _seed_owned_hierarchy(migrated_session)
    nested_request = "56666666-6666-4666-8666-666666666666"
    await _request(
        migrated_session,
        nested_request,
        job_id=_JOB_CHILD,
        created_at=_T0 + timedelta(minutes=4),
    )

    page = await list_pipeline_executions(migrated_session)

    by_id = {item.id: item for item in page.items}
    parent = by_id[_REQUEST_OWNER]
    nested = by_id[nested_request]
    assert parent.linked_job_count == 1
    assert parent.projected_job is not None
    assert parent.projected_job.id == _JOB_ROOT
    assert parent.projected_job.depth == 0
    assert nested.linked_job_count == 2
    assert nested.projected_job is not None
    assert nested.projected_job.id == _JOB_GRANDCHILD
    assert nested.projected_job.depth == 1
    assert sum(item.linked_job_count for item in page.items) == 3


async def test_batch_root_keeps_two_request_branches_and_unowned_siblings_separate(
    migrated_session: AsyncSession,
) -> None:
    batch_root = "c1111111-1111-4111-8111-111111111111"
    branch_a = "c2222222-2222-4222-8222-222222222222"
    branch_a_child = "c3333333-3333-4333-8333-333333333333"
    branch_b = "c4444444-4444-4444-8444-444444444444"
    branch_b_child = "c5555555-5555-4555-8555-555555555555"
    unowned_sibling = "c6666666-6666-4666-8666-666666666666"
    unowned_descendant = "c7777777-7777-4777-8777-777777777777"
    request_a = "d1111111-1111-4111-8111-111111111111"
    request_b = "d2222222-2222-4222-8222-222222222222"
    await _job(migrated_session, batch_root, created_at=_T0)
    await _job(migrated_session, branch_a, parent_job_id=batch_root, created_at=_T0)
    await _job(
        migrated_session,
        branch_a_child,
        parent_job_id=branch_a,
        created_at=_T0 + timedelta(minutes=1),
    )
    await _job(migrated_session, branch_b, parent_job_id=batch_root, created_at=_T0)
    await _job(
        migrated_session,
        branch_b_child,
        parent_job_id=branch_b,
        created_at=_T0 + timedelta(minutes=1),
    )
    await _job(
        migrated_session,
        unowned_sibling,
        parent_job_id=batch_root,
        created_at=_T0 + timedelta(minutes=1),
    )
    await _job(
        migrated_session,
        unowned_descendant,
        parent_job_id=unowned_sibling,
        created_at=_T0 + timedelta(minutes=2),
    )
    await _request(
        migrated_session,
        request_a,
        job_id=branch_a,
        created_at=_T0 + timedelta(minutes=3),
    )
    await _request(
        migrated_session,
        request_b,
        job_id=branch_b,
        created_at=_T0 + timedelta(minutes=4),
    )
    await _event(
        migrated_session,
        "e1111111-1111-4111-8111-111111111111",
        job_id=branch_a_child,
        provider="owned-provider",
        dataset_key="owned-dataset",
    )
    await _event(
        migrated_session,
        "e2222222-2222-4222-8222-222222222222",
        job_id=unowned_descendant,
        provider="standalone-provider",
        dataset_key="standalone-dataset",
    )

    page = await list_pipeline_executions(migrated_session)

    by_key = {(item.kind, item.id): item for item in page.items}
    assert set(by_key) == {
        ("import_job", batch_root),
        ("update_request", request_a),
        ("update_request", request_b),
    }
    standalone = by_key[("import_job", batch_root)]
    assert standalone.linked_job_count == 3
    assert standalone.projected_job is not None
    assert standalone.projected_job.id == unowned_descendant
    assert standalone.providers == ("standalone-provider",)
    assert standalone.dataset_keys == ("standalone-dataset",)
    assert by_key[("update_request", request_a)].linked_job_count == 2
    assert by_key[("update_request", request_b)].linked_job_count == 2
    assert sum(item.linked_job_count for item in page.items) == 7
    assert (
        await list_pipeline_executions(
            migrated_session, kind="import_job", provider="owned-provider"
        )
    ).items == ()


async def test_cursor_kind_breaks_same_timestamp_and_uuid_tie(
    migrated_session: AsyncSession,
) -> None:
    shared = "91111111-1111-4111-8111-111111111111"
    at = _T0 + timedelta(days=1)
    await _job(migrated_session, shared, created_at=at)
    await _request(migrated_session, shared, job_id=None, created_at=at)

    first = await list_pipeline_executions(migrated_session, limit=1)
    second = await list_pipeline_executions(migrated_session, limit=1, cursor=first.next_cursor)

    assert [(item.kind, item.id) for item in first.items] == [("update_request", shared)]
    assert first.next_cursor is not None
    assert [(item.kind, item.id) for item in second.items] == [("import_job", shared)]
    assert second.next_cursor is None


async def test_request_filters_use_arrays_and_direct_provider_dataset_scope(
    migrated_session: AsyncSession,
) -> None:
    array_request = "a1111111-1111-4111-8111-111111111111"
    direct_request = "a2222222-2222-4222-8222-222222222222"
    await _request(
        migrated_session,
        array_request,
        job_id=None,
        created_at=_T0,
        providers=("array-provider",),
        dataset_keys=("array-dataset",),
    )
    await _request(
        migrated_session,
        direct_request,
        job_id=None,
        created_at=_T0,
        scope={
            "type": "provider_dataset",
            "provider": "direct-provider",
            "dataset_key": "direct-dataset",
            "sync_scope": "region:11",
        },
    )

    assert [
        item.id
        for item in (
            await list_pipeline_executions(
                migrated_session,
                provider="array-provider",
                dataset_key="array-dataset",
            )
        ).items
    ] == [array_request]
    direct = await list_pipeline_executions(
        migrated_session,
        provider="direct-provider",
        dataset_key="direct-dataset",
    )
    assert [item.id for item in direct.items] == [direct_request]
    assert direct.items[0].providers == ("direct-provider",)
    assert direct.items[0].dataset_keys == ("direct-dataset",)
    assert direct.items[0].provider_dataset is not None
    assert direct.items[0].provider_dataset.provider == "direct-provider"
    assert direct.items[0].provider_dataset.dataset_key == "direct-dataset"
    assert direct.items[0].provider_dataset.sync_scope == "region:11"


async def test_status_counts_for_overview(migrated_session: AsyncSession) -> None:
    await _job(migrated_session, _JOB_ROOT, status="failed")
    await _request(
        migrated_session,
        _REQUEST_OWNER,
        job_id=_JOB_ROOT,
        created_at=_T0,
    )

    counts = await get_pipeline_status_counts(migrated_session)

    assert counts.import_jobs_by_status == {"failed": 1}
    assert counts.update_requests_by_status == {"queued": 1}


async def test_projection_explain_records_recursive_and_event_access_plan(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _JOB_ROOT)
    await _event(
        migrated_session,
        "b1111111-1111-4111-8111-111111111111",
        job_id=_JOB_ROOT,
        provider="provider-a",
        dataset_key="dataset-a",
    )
    params = {
        "kind": None,
        "status": None,
        "provider": "provider-a",
        "dataset_key": "dataset-a",
        "created_from": None,
        "created_to": None,
        "cursor_created_at": None,
        "cursor_id": None,
        "cursor_item_kind": None,
        "page_limit": 51,
    }

    # 1행 fixture에서 planner 비용 우연으로 seq scan을 택하지 않게 하고,
    # 이 테스트의 목적인 event access index의 사용 가능성을 직접 검증한다.
    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (
        await migrated_session.execute(
            text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {pipeline_repo._LIST_EXECUTIONS_SQL}"),
            params,
        )
    ).scalar_one()
    plan_text = json.dumps(plan, sort_keys=True)
    assert "Recursive Union" in plan_text
    assert "import_job_events" in plan_text
    assert '"Index Name": "idx_import_job_events_job_time"' in plan_text
    assert len(plan_text) < 1_000_000
