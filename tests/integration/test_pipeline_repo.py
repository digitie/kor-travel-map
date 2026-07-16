"""파이프라인 root projection 통합 테스트 (ADR-064 T-ADM-C3b)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.infra import pipeline_repo
from kortravelmap.infra.pipeline_repo import (
    get_pipeline_execution,
    get_pipeline_status_counts,
    list_latest_dataset_pipeline_executions,
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
_REQUEST_JOB_NAMESPACE = UUID("8ff8c150-70cf-4dda-91bb-e6965fb5d0e3")

_INSERT_JOB_SQL = text(
    """
    INSERT INTO ops.import_jobs (
        job_id, kind, parent_job_id, payload, status, progress, current_stage,
        created_at, started_at, dagster_run_id, provider, dataset_key, sync_scope,
        trigger_kind
    ) VALUES (
        CAST(:job_id AS uuid), :kind, CAST(:parent_job_id AS uuid),
        CAST(:payload AS jsonb), :status, :progress, :current_stage,
        :created_at, :started_at, :dagster_run_id, :provider, :dataset_key,
        :sync_scope, :trigger_kind
    )
    """
)

_INSERT_REQUEST_SQL = text(
    """
    INSERT INTO ops.feature_update_requests (
        request_id, scope_type, scope, providers, dataset_keys, update_policy,
        run_mode, priority, matched_scope, job_id, operator, created_at
    ) VALUES (
        CAST(:request_id AS uuid), :scope_type, CAST(:scope AS jsonb),
        CAST(:providers AS text[]), CAST(:dataset_keys AS text[]), '{}'::jsonb,
        'queued', :priority, '{}'::jsonb,
        CAST(:job_id AS uuid), :operator, :created_at
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
    kind: str = "provider_load",
    parent_job_id: str | None = None,
    created_at: datetime = _T0,
    status: str = "queued",
    progress: int = 0,
    payload: dict[str, Any] | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    sync_scope: str | None = None,
) -> None:
    await session.execute(
        _INSERT_JOB_SQL,
        {
            "job_id": job_id,
            "kind": kind,
            "parent_job_id": parent_job_id,
            "payload": json.dumps(payload or {}),
            "status": status,
            "progress": progress,
            "current_stage": "loading" if status == "running" else None,
            "created_at": created_at,
            "started_at": created_at if status == "running" else None,
            "dagster_run_id": (
                None
                if kind == "feature_update_request" and status == "queued"
                else f"run-{job_id[:8]}"
            ),
            "provider": provider,
            "dataset_key": dataset_key,
            "sync_scope": sync_scope,
            "trigger_kind": "update_request" if kind == "feature_update_request" else None,
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
    if job_id is None:
        job_id = str(uuid5(_REQUEST_JOB_NAMESPACE, request_id))
        is_direct = request_scope["type"] == "provider_dataset"
        await _job(
            session,
            job_id,
            kind="feature_update_request",
            created_at=created_at,
            provider=(str(request_scope.get("provider")) if is_direct else None),
            dataset_key=(
                str(request_scope.get("dataset_key")) if is_direct else None
            ),
            sync_scope=(
                str(request_scope.get("sync_scope", "dataset_wide"))
                if is_direct
                else None
            ),
        )
    await session.execute(
        _INSERT_REQUEST_SQL,
        {
            "request_id": request_id,
            "scope_type": request_scope["type"],
            "scope": json.dumps(request_scope),
            "providers": providers,
            "dataset_keys": dataset_keys,
            "priority": 50,
            "job_id": job_id,
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


def _plan_nodes(plan: Any) -> list[dict[str, Any]]:
    document = plan[0] if isinstance(plan, list) else plan
    root = document["Plan"]
    pending = [root]
    nodes: list[dict[str, Any]] = []
    while pending:
        node = pending.pop()
        nodes.append(node)
        pending.extend(node.get("Plans", ()))
    return nodes


def _assert_bounded_selective_access(
    plan: Any,
    *,
    expected_index: str | None = None,
) -> None:
    base_relations = {
        "import_jobs",
        "import_job_events",
        "feature_update_requests",
    }
    nodes = _plan_nodes(plan)
    executed_sequential = [
        node
        for node in nodes
        if node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") in base_relations
        and float(node.get("Actual Loops", 0)) > 0
    ]
    assert executed_sequential == []

    base_access = [
        node for node in nodes if node.get("Relation Name") in base_relations
    ]
    assert base_access
    touches = sum(
        float(node.get("Actual Rows", 0)) * float(node.get("Actual Loops", 0))
        for node in base_access
    )
    assert touches <= 64, [
        (
            node.get("Node Type"),
            node.get("Relation Name"),
            node.get("Index Name"),
            node.get("Actual Rows"),
            node.get("Actual Loops"),
        )
        for node in base_access
    ]
    assert all(float(node.get("Actual Loops", 0)) <= 16 for node in base_access)

    if expected_index is not None:
        matching = [
            node
            for node in nodes
            if node.get("Index Name") == expected_index
            and float(node.get("Actual Rows", 0)) > 0
            and float(node.get("Actual Loops", 0)) > 0
        ]
        assert matching, [
            (
                node.get("Node Type"),
                node.get("Relation Name"),
                node.get("Index Name"),
                node.get("Actual Rows"),
                node.get("Actual Loops"),
            )
            for node in nodes
            if node.get("Index Name") is not None
        ]


async def _seed_owned_hierarchy(session: AsyncSession) -> None:
    await _job(
        session,
        _JOB_ROOT,
        kind="feature_update_request",
        created_at=_T0,
    )
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
        providers=("stored-b", "stored-a"),
        dataset_keys=("dataset-b", "dataset-a"),
    )


async def test_request_anchor_collapses_descendants_and_projects_deepest_job(
    migrated_session: AsyncSession,
) -> None:
    await _seed_owned_hierarchy(migrated_session)

    page = await list_pipeline_executions(migrated_session)

    assert [(item.kind, item.id) for item in page.items] == [("update_request", _REQUEST_OWNER)]
    root = page.items[0]
    assert root.requested_job_id == _JOB_ROOT
    assert root.linked_job_count == 3
    assert root.providers == ("stored-a", "stored-b")
    assert root.dataset_keys == ("dataset-a", "dataset-b")
    assert root.progress is None
    assert root.projected_job.id == _JOB_GRANDCHILD
    assert root.projected_job.depth == 2
    assert root.projected_job.status == "failed"


async def test_standalone_hierarchy_ignores_audit_event_and_payload_identity(
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
    assert root.providers == ()
    assert root.dataset_keys == ()
    assert root.provider_datasets == ()
    assert root.projected_job.id == _JOB_GRANDCHILD
    assert (
        await list_pipeline_executions(
            migrated_session, provider="provider-a", dataset_key="dataset-z"
        )
    ).items == ()
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


async def test_duplicate_requests_on_same_anchor_are_rejected(
    migrated_session: AsyncSession,
) -> None:
    await _seed_owned_hierarchy(migrated_session)
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _request(
                migrated_session,
                _REQUEST_LOSER,
                job_id=_JOB_ROOT,
                created_at=_T0 + timedelta(minutes=4),
            )

    page = await list_pipeline_executions(migrated_session)

    assert [item.id for item in page.items] == [_REQUEST_OWNER]
    owner = page.items[0]
    assert owner.linked_job_count == 3


async def test_request_cannot_anchor_to_noncanonical_child_job(
    migrated_session: AsyncSession,
) -> None:
    await _seed_owned_hierarchy(migrated_session)
    nested_request = "56666666-6666-4666-8666-666666666666"
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _request(
                migrated_session,
                nested_request,
                job_id=_JOB_CHILD,
                created_at=_T0 + timedelta(minutes=4),
            )

    page = await list_pipeline_executions(migrated_session)

    assert [item.id for item in page.items] == [_REQUEST_OWNER]
    assert page.items[0].linked_job_count == 3
    assert page.items[0].projected_job.id == _JOB_GRANDCHILD


async def test_feature_run_projects_root_and_exposes_pair_child_status(
    migrated_session: AsyncSession,
) -> None:
    root_id = "b1111111-1111-4111-8111-111111111111"
    child_id = "b2222222-2222-4222-8222-222222222222"
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
                job_id, kind, payload, status, progress, current_stage,
                dagster_run_id, trigger_kind, operation_registry_version,
                dagster_run_status, created_at, started_at
            ) VALUES (
                CAST(:root_id AS uuid), 'provider_feature_load_run', '{}'::jsonb,
                'running', 15, 'engine', 'feature-run-1', 'manual', 'v1',
                'STARTED', :created_at, :created_at
            )
            """
        ),
        {"root_id": root_id, "created_at": _T0},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
                job_id, kind, parent_job_id, payload, status, progress,
                current_stage, dagster_run_id, provider, dataset_key,
                created_at, started_at, finished_at
            ) VALUES (
                CAST(:child_id AS uuid), 'provider_feature_load',
                CAST(:root_id AS uuid), '{}'::jsonb, 'failed', 70, 'pair',
                'feature-run-1', 'provider-a', 'dataset-a', :created_at,
                :created_at, :created_at
            )
            """
        ),
        {"root_id": root_id, "child_id": child_id, "created_at": _T0},
    )

    page = await list_pipeline_executions(migrated_session)

    root = page.items[0]
    assert root.id == root_id
    assert root.status == "running"
    assert root.dagster_run_status == "STARTED"
    assert root.trigger_kind == "manual"
    assert root.operation_registry_version == "v1"
    assert root.projected_job.id == root_id
    assert root.projected_job.status == "running"
    assert root.provider_datasets == (
        pipeline_repo.PipelineProviderDatasetIdentity(
            provider="provider-a",
            dataset_key="dataset-a",
            sync_scope=None,
            operation_member_id=child_id,
            status="failed",
        ),
    )
    member_detail = await get_pipeline_execution(
        migrated_session,
        kind="import_job",
        execution_id=child_id,
    )
    assert member_detail is not None
    assert member_detail.id == root_id
    assert member_detail.projected_job == root.projected_job


async def test_typed_pair_is_canonical_when_audit_event_has_conflicting_pair(
    migrated_session: AsyncSession,
) -> None:
    await _job(
        migrated_session,
        _JOB_ROOT,
        provider="typed-provider",
        dataset_key="typed-dataset",
    )
    await _event(
        migrated_session,
        "b3333333-3333-4333-8333-333333333333",
        job_id=_JOB_ROOT,
        provider="event-provider",
        dataset_key="event-dataset",
    )

    root = (await list_pipeline_executions(migrated_session)).items[0]

    assert [(pair.provider, pair.dataset_key) for pair in root.provider_datasets] == [
        ("typed-provider", "typed-dataset")
    ]
    assert (
        await list_pipeline_executions(
            migrated_session,
            provider="event-provider",
            dataset_key="event-dataset",
        )
    ).items == ()
    detail = await get_pipeline_execution(
        migrated_session,
        kind="import_job",
        execution_id=_JOB_ROOT,
    )
    assert detail is not None
    assert [(pair.provider, pair.dataset_key) for pair in detail.provider_datasets] == [
        ("typed-provider", "typed-dataset")
    ]
    latest = await list_latest_dataset_pipeline_executions(migrated_session)
    assert [(item.provider, item.dataset_key) for item in latest] == [
        ("typed-provider", "typed-dataset")
    ]


async def test_event_only_sibling_does_not_create_canonical_pair(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _JOB_ROOT, status="queued")
    await _job(
        migrated_session,
        _JOB_CHILD,
        parent_job_id=_JOB_ROOT,
        status="running",
        provider="provider-typed",
        dataset_key="dataset-typed",
    )
    await _job(
        migrated_session,
        _JOB_GRANDCHILD,
        parent_job_id=_JOB_ROOT,
        status="failed",
    )
    await _event(
        migrated_session,
        "b4444444-4444-4444-8444-444444444444",
        job_id=_JOB_CHILD,
        provider="provider-conflict",
        dataset_key="dataset-conflict",
    )
    await _event(
        migrated_session,
        "b5555555-5555-4555-8555-555555555555",
        job_id=_JOB_GRANDCHILD,
        provider="provider-legacy",
        dataset_key="dataset-legacy",
    )

    root = (await list_pipeline_executions(migrated_session)).items[0]
    pairs = {
        (pair.provider, pair.dataset_key): pair for pair in root.provider_datasets
    }

    assert set(pairs) == {("provider-typed", "dataset-typed")}
    assert pairs[("provider-typed", "dataset-typed")].operation_member_id == _JOB_CHILD
    assert pairs[("provider-typed", "dataset-typed")].status == "running"
    for provider, dataset_key in pairs:
        filtered = await list_pipeline_executions(
            migrated_session,
            provider=provider,
            dataset_key=dataset_key,
        )
        assert [item.id for item in filtered.items] == [_JOB_ROOT]
    assert (
        await list_pipeline_executions(
            migrated_session,
            provider="provider-typed",
            dataset_key="dataset-legacy",
        )
    ).items == ()
    assert (
        await list_pipeline_executions(
            migrated_session,
            provider="provider-legacy",
            dataset_key="dataset-legacy",
        )
    ).items == ()
    assert (
        await list_pipeline_executions(
            migrated_session,
            provider="provider-conflict",
            dataset_key="dataset-conflict",
        )
    ).items == ()

    detail = await get_pipeline_execution(
        migrated_session,
        kind="import_job",
        execution_id=_JOB_GRANDCHILD,
    )
    assert detail is not None
    assert detail.id == _JOB_ROOT
    assert detail.provider_datasets == root.provider_datasets

    latest = await list_latest_dataset_pipeline_executions(migrated_session)
    latest_by_pair = {
        (item.provider, item.dataset_key): item for item in latest
    }
    assert set(latest_by_pair) == set(pairs)
    assert all(item.execution.id == _JOB_ROOT for item in latest_by_pair.values())
    assert latest_by_pair[("provider-typed", "dataset-typed")].pair_status == "running"


async def test_audit_events_never_create_provider_dataset_identity(
    migrated_session: AsyncSession,
) -> None:
    await _job(migrated_session, _JOB_ROOT)
    await _job(migrated_session, _JOB_CHILD, parent_job_id=_JOB_ROOT)
    await _job(migrated_session, _JOB_GRANDCHILD, parent_job_id=_JOB_ROOT)
    await _event(
        migrated_session,
        "b6000000-0000-4000-8000-000000000001",
        job_id=_JOB_CHILD,
        provider="provider-valid",
        dataset_key="dataset-valid",
    )
    malformed_pairs = (
        (" provider-leading", "dataset-leading-provider"),
        ("provider-trailing-dataset", "dataset-trailing "),
        ("   ", "dataset-blank-provider"),
        ("provider-blank-dataset", "   "),
    )
    for index, (provider, dataset_key) in enumerate(malformed_pairs, start=2):
        await _event(
            migrated_session,
            f"b6000000-0000-4000-8000-{index:012d}",
            job_id=_JOB_GRANDCHILD,
            provider=provider,
            dataset_key=dataset_key,
        )

    root = (await list_pipeline_executions(migrated_session)).items[0]

    assert root.providers == ()
    assert root.dataset_keys == ()
    assert root.provider_datasets == ()
    detail = await get_pipeline_execution(
        migrated_session,
        kind="import_job",
        execution_id=_JOB_GRANDCHILD,
    )
    assert detail is not None
    assert detail.provider_datasets == root.provider_datasets
    for provider, dataset_key in (
        ("provider-valid", "dataset-valid"),
        *malformed_pairs,
    ):
        assert (
            await list_pipeline_executions(
                migrated_session,
                provider=provider,
                dataset_key=dataset_key,
            )
        ).items == ()
    assert await list_latest_dataset_pipeline_executions(migrated_session) == ()


async def test_direct_request_pair_ignores_audit_event_pair(
    migrated_session: AsyncSession,
) -> None:
    await _job(
        migrated_session,
        _JOB_ROOT,
        kind="feature_update_request",
        provider="provider-direct",
        dataset_key="dataset-direct",
        sync_scope="target_grids",
    )
    await _request(
        migrated_session,
        _REQUEST_OWNER,
        job_id=_JOB_ROOT,
        created_at=_T0 + timedelta(minutes=1),
        scope={
            "type": "provider_dataset",
            "provider": "provider-direct",
            "dataset_key": "dataset-direct",
            "sync_scope": "target_grids",
        },
    )
    await _event(
        migrated_session,
        "b6666666-6666-4666-8666-666666666666",
        job_id=_JOB_ROOT,
        provider="provider-legacy",
        dataset_key="dataset-legacy",
    )

    root = (await list_pipeline_executions(migrated_session)).items[0]
    pairs = {
        (pair.provider, pair.dataset_key): pair for pair in root.provider_datasets
    }

    assert root.kind == "update_request"
    assert root.id == _REQUEST_OWNER
    assert set(pairs) == {("provider-direct", "dataset-direct")}
    assert pairs[("provider-direct", "dataset-direct")].sync_scope == "target_grids"
    assert pairs[("provider-direct", "dataset-direct")].operation_member_id == _JOB_ROOT
    assert (
        await list_pipeline_executions(
            migrated_session,
            provider="provider-legacy",
            dataset_key="dataset-legacy",
        )
    ).items == ()


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
    await _job(
        migrated_session,
        branch_a,
        kind="feature_update_request",
        created_at=_T0,
    )
    await _job(
        migrated_session,
        branch_a_child,
        parent_job_id=branch_a,
        created_at=_T0 + timedelta(minutes=1),
        provider="owned-provider",
        dataset_key="owned-dataset",
    )
    await _job(
        migrated_session,
        branch_b,
        kind="feature_update_request",
        created_at=_T0,
    )
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
        provider="standalone-provider",
        dataset_key="standalone-dataset",
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


async def test_request_arrays_are_single_filters_and_direct_scope_is_exact_pair(
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
            "sync_scope": "target_grids",
        },
    )

    assert (
        await list_pipeline_executions(
            migrated_session,
            provider="array-provider",
            dataset_key="array-dataset",
        )
    ).items == ()
    assert [
        item.id
        for item in (
            await list_pipeline_executions(
                migrated_session,
                provider="array-provider",
            )
        ).items
    ] == [array_request]
    assert [
        item.id
        for item in (
            await list_pipeline_executions(
                migrated_session,
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
    assert len(direct.items[0].provider_datasets) == 1
    pair = direct.items[0].provider_datasets[0]
    assert pair.provider == "direct-provider"
    assert pair.dataset_key == "direct-dataset"
    assert pair.sync_scope == "target_grids"
    assert pair.operation_member_id == str(uuid5(_REQUEST_JOB_NAMESPACE, direct_request))


async def test_direct_scope_cannot_disagree_with_typed_job_identity(
    migrated_session: AsyncSession,
) -> None:
    await _job(
        migrated_session,
        _JOB_ROOT,
        kind="feature_update_request",
        provider="typed-provider",
        dataset_key="typed-dataset",
        sync_scope="dataset_wide",
    )
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _request(
                migrated_session,
                _REQUEST_OWNER,
                job_id=_JOB_ROOT,
                created_at=_T0,
                scope={
                    "type": "provider_dataset",
                    "provider": "scope-provider",
                    "dataset_key": "scope-dataset",
                },
            )


async def test_latest_dataset_execution_keeps_direct_scopes_separate(
    migrated_session: AsyncSession,
) -> None:
    provider = "python-kma-api"
    dataset_key = "kma_short_forecast"
    requests = (
        (
            "a3333333-3333-4333-8333-333333333333",
            "target_grids",
            _T0,
        ),
        (
            "a4444444-4444-4444-8444-444444444444",
            "external_system:concierge",
            _T0 + timedelta(minutes=1),
        ),
    )
    for request_id, sync_scope, created_at in requests:
        await _request(
            migrated_session,
            request_id,
            job_id=None,
            created_at=created_at,
            scope={
                "type": "provider_dataset",
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
            },
        )

    latest = await list_latest_dataset_pipeline_executions(migrated_session)
    by_scope = {
        item.sync_scope: item
        for item in latest
        if item.provider == provider and item.dataset_key == dataset_key
    }

    assert set(by_scope) == {"target_grids", "external_system:concierge"}
    assert by_scope["target_grids"].execution.id == requests[0][0]
    assert by_scope["external_system:concierge"].execution.id == requests[1][0]


async def test_status_counts_for_overview(migrated_session: AsyncSession) -> None:
    await _job(
        migrated_session,
        _JOB_ROOT,
        kind="feature_update_request",
        status="failed",
    )
    await _request(
        migrated_session,
        _REQUEST_OWNER,
        job_id=_JOB_ROOT,
        created_at=_T0,
    )

    counts = await get_pipeline_status_counts(migrated_session)
    timeline = await list_pipeline_executions(migrated_session)

    assert counts.operations_by_status == {"failed": 1}
    assert sum(counts.operations_by_status.values()) == len(timeline.items)
    assert counts.active_operations == 0
    assert counts.failed_operations_24h == 0


async def test_more_than_one_thousand_roots_have_complete_pagination_and_latest(
    migrated_session: AsyncSession,
) -> None:
    root_count = 1_005
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
                kind, payload, status, provider, dataset_key, trigger_kind,
                created_at
            )
            SELECT
                'bulk_projection_fixture', '{}'::jsonb, 'queued',
                'bulk-provider',
                'bulk-dataset-' || lpad(seed.n::text, 4, '0'),
                'manual',
                CAST(:created_at AS timestamptz)
                    + seed.n * INTERVAL '1 millisecond'
            FROM generate_series(1, :root_count) AS seed(n)
            """
        ),
        {"created_at": _T0, "root_count": root_count},
    )

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = await list_pipeline_executions(
            migrated_session,
            provider="bulk-provider",
            limit=200,
            cursor=cursor,
        )
        seen.extend(item.id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    latest = await list_latest_dataset_pipeline_executions(migrated_session)
    counts = await get_pipeline_status_counts(migrated_session)

    assert len(seen) == root_count
    assert len(set(seen)) == root_count
    assert len(latest) == root_count
    assert {
        (item.provider, item.dataset_key) for item in latest
    } == {
        ("bulk-provider", f"bulk-dataset-{number:04d}")
        for number in range(1, root_count + 1)
    }
    assert counts.operations_by_status == {"queued": root_count}
    assert counts.active_operations == root_count


async def _seed_selective_projection_cardinality(
    session: AsyncSession,
) -> dict[str, str]:
    event_only_job_id = "71111111-1111-4111-8111-111111111111"
    direct_request_id = "72222222-2222-4222-8222-222222222222"
    provider_array_request_id = "73333333-3333-4333-8333-333333333333"
    dataset_array_request_id = "74444444-4444-4444-8444-444444444444"
    provider_only_job_id = "76666666-6666-4666-8666-666666666666"
    dataset_only_job_id = "77777777-7777-4777-8777-777777777777"

    await _job(session, _JOB_ROOT, kind="feature_update_request")
    await _job(
        session,
        _JOB_CHILD,
        parent_job_id=_JOB_ROOT,
        provider="typed-provider",
        dataset_key="typed-dataset",
    )
    await _job(
        session,
        provider_only_job_id,
        provider="provider-only",
        dataset_key="provider-only-dataset",
    )
    await _job(
        session,
        dataset_only_job_id,
        provider="dataset-only-provider",
        dataset_key="dataset-only",
    )
    await _request(
        session,
        _REQUEST_OWNER,
        job_id=_JOB_ROOT,
        created_at=_T0 + timedelta(minutes=1),
    )

    await _job(session, event_only_job_id)
    await _event(
        session,
        "75555555-5555-4555-8555-555555555555",
        job_id=event_only_job_id,
        provider="legacy-provider",
        dataset_key="legacy-dataset",
    )
    await _request(
        session,
        direct_request_id,
        job_id=None,
        created_at=_T0,
        scope={
            "type": "provider_dataset",
            "provider": "direct-provider",
            "dataset_key": "direct-dataset",
        },
    )
    await _request(
        session,
        provider_array_request_id,
        job_id=None,
        created_at=_T0,
        providers=("array-provider",),
    )
    await _request(
        session,
        dataset_array_request_id,
        job_id=None,
        created_at=_T0,
        dataset_keys=("array-dataset",),
    )

    await session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
                job_id, kind, payload, status, provider, dataset_key, trigger_kind,
                created_at
            )
            SELECT
                (
                  '30000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'projection_plan_noise', '{}'::jsonb, 'queued',
                'noise-provider-' || seed.n::text,
                'noise-dataset-' || seed.n::text,
                'update_request', CAST(:created_at AS timestamptz)
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
                (
                  '36000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'projection_exact_axis_noise', '{}'::jsonb, 'queued',
                'typed-provider',
                'typed-other-dataset-' || seed.n::text,
                'update_request', CAST(:created_at AS timestamptz)
            FROM generate_series(1, 2000) AS seed(n)

            UNION ALL

            SELECT
                (
                  '37000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'projection_exact_axis_noise', '{}'::jsonb, 'queued',
                'typed-other-provider-' || seed.n::text,
                'typed-dataset',
                'update_request', CAST(:created_at AS timestamptz)
            FROM generate_series(1, 2000) AS seed(n)
            """
        ),
        {"created_at": _T0},
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
                job_id, kind, payload, status, created_at
            )
            SELECT
                (
                  '31000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'projection_legacy_noise', '{}'::jsonb, 'queued',
                CAST(:created_at AS timestamptz)
            FROM generate_series(1, 4000) AS seed(n)
            """
        ),
        {"created_at": _T0},
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.import_job_events (
                event_id, job_id, provider, dataset_key,
                level, message, occurred_at
            )
            SELECT
                (
                  '32000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                (
                  '31000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                CASE
                  WHEN seed.n <= 2000 THEN 'legacy-provider'
                  ELSE 'legacy-other-provider-' || seed.n::text
                END,
                CASE
                  WHEN seed.n <= 2000
                    THEN 'legacy-other-dataset-' || seed.n::text
                  ELSE 'legacy-dataset'
                END,
                'info', 'noise', CAST(:created_at AS timestamptz)
            FROM generate_series(1, 4000) AS seed(n)
            """
        ),
        {"created_at": _T0},
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
                job_id, kind, payload, status, provider, dataset_key, sync_scope,
                trigger_kind, created_at
            )
            SELECT
                (
                  '3c000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'feature_update_request', '{}'::jsonb, 'queued',
                CASE
                  WHEN seed.n <= 2000 THEN 'direct-provider'
                  ELSE 'noise-direct-provider-' || seed.n::text
                END,
                CASE
                  WHEN seed.n <= 2000
                    THEN 'noise-direct-dataset-' || seed.n::text
                  ELSE 'direct-dataset'
                END,
                'dataset_wide', 'update_request', CAST(:created_at AS timestamptz)
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
                (
                  '3d000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'feature_update_request', '{}'::jsonb, 'queued',
                NULL, NULL, NULL, 'update_request', CAST(:created_at AS timestamptz)
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
                (
                  '3e000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'feature_update_request', '{}'::jsonb, 'queued',
                NULL, NULL, NULL, 'update_request', CAST(:created_at AS timestamptz)
            FROM generate_series(1, 4000) AS seed(n)
            """
        ),
        {"created_at": _T0},
    )
    await session.execute(
        text(
            """
            INSERT INTO ops.feature_update_requests (
                request_id, scope_type, scope, providers, dataset_keys,
                run_mode, job_id, created_at
            )
            SELECT
                (
                  '33000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'provider_dataset',
                jsonb_build_object(
                  'type', 'provider_dataset',
                  'provider', CASE
                    WHEN seed.n <= 2000 THEN 'direct-provider'
                    ELSE 'noise-direct-provider-' || seed.n::text
                  END,
                  'dataset_key', CASE
                    WHEN seed.n <= 2000
                      THEN 'noise-direct-dataset-' || seed.n::text
                    ELSE 'direct-dataset'
                  END
                ),
                '{}'::text[], '{}'::text[], 'queued',
                (
                  '3c000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                CAST(:created_at AS timestamptz)
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
                (
                  '34000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'feature_ids', '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                ARRAY['noise-array-provider-' || seed.n::text]::text[],
                '{}'::text[], 'queued',
                (
                  '3d000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                CAST(:created_at AS timestamptz)
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
                (
                  '35000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                'feature_ids', '{"type":"feature_ids","feature_ids":[]}'::jsonb,
                '{}'::text[],
                ARRAY['noise-array-dataset-' || seed.n::text]::text[],
                'queued',
                (
                  '3e000000-0000-4000-8000-'
                  || lpad(seed.n::text, 12, '0')
                )::uuid,
                CAST(:created_at AS timestamptz)
            FROM generate_series(1, 4000) AS seed(n)
            """
        ),
        {"created_at": _T0},
    )
    for relation in (
        "ops.import_jobs",
        "ops.import_job_events",
        "ops.feature_update_requests",
    ):
        await session.execute(text(f"ANALYZE {relation}"))

    return {
        "event_only_job": event_only_job_id,
        "direct_request": direct_request_id,
        "provider_array_request": provider_array_request_id,
        "dataset_array_request": dataset_array_request_id,
    }


async def test_selective_projection_plans_use_natural_bounded_access_paths(
    migrated_session: AsyncSession,
) -> None:
    await _seed_selective_projection_cardinality(migrated_session)
    await migrated_session.execute(
        text("SET LOCAL plan_cache_mode = force_generic_plan")
    )
    cases = (
        (
            "typed-exact",
            "typed-provider",
            "typed-dataset",
            "idx_import_jobs_provider_dataset_created",
        ),
        (
            "direct-exact",
            "direct-provider",
            "direct-dataset",
            "idx_import_jobs_provider_dataset_created",
        ),
        (
            "typed-provider",
            "provider-only",
            None,
            "idx_import_jobs_provider_created",
        ),
        (
            "request-provider-array",
            "array-provider",
            None,
            "idx_feature_update_providers_gin",
        ),
        (
            "typed-dataset",
            None,
            "dataset-only",
            "idx_import_jobs_dataset_created",
        ),
        (
            "request-dataset-array",
            None,
            "array-dataset",
            "idx_feature_update_dataset_keys_gin",
        ),
    )
    for label, provider, dataset_key, expected_index in cases:
        params = {
            "kind": None,
            "status": None,
            "provider": provider,
            "dataset_key": dataset_key,
            "created_from": None,
            "created_to": None,
            "cursor_created_at": None,
            "cursor_id": None,
            "cursor_item_kind": None,
            "page_limit": 51,
        }
        plan = (
            await migrated_session.execute(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                    f"/* {label} */ {pipeline_repo._LIST_EXECUTIONS_SQL}"
                ),
                params,
            )
        ).scalar_one()
        _assert_bounded_selective_access(plan, expected_index=expected_index)
        assert all(
            node.get("Relation Name") != "import_job_events"
            for node in _plan_nodes(plan)
        )


async def test_uuid_detail_plans_expand_only_selected_component(
    migrated_session: AsyncSession,
) -> None:
    targets = await _seed_selective_projection_cardinality(migrated_session)
    await migrated_session.execute(
        text("SET LOCAL plan_cache_mode = force_generic_plan")
    )
    cases = (
        ("import-member", "import_job", _JOB_CHILD, "pk_import_jobs"),
        (
            "jobless-request",
            "update_request",
            targets["direct_request"],
            "pk_feature_update_requests",
        ),
    )
    for label, root_kind, root_id, expected_index in cases:
        plan = (
            await migrated_session.execute(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                    f"/* {label} */ {pipeline_repo._GET_EXECUTION_SQL}"
                ),
                {"root_kind": root_kind, "root_id": root_id},
            )
        ).scalar_one()
        _assert_bounded_selective_access(plan, expected_index=expected_index)
