"""파이프라인 root projection 통합 테스트 (ADR-064 T-ADM-C3b).

T-VN-33 이후 실행 identity는 자연키 사본이 아니라 canonical triple
``(provider_dataset_id, sync_scope, operation_key)``이다. job/request 행은
provider·dataset_key·sync_scope 열을 더 이상 갖지 않고, membership은
``ops.import_job_datasets`` / ``ops.feature_update_request_datasets``가 든다.
따라서 fixture는 catalog(datasets → operations → operation_scopes)를 먼저 심고
그 triple로 membership을 쓴다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.infra import pipeline_repo
from kortravelmap.infra.feature_update_repo import (
    enqueue_feature_update_request,
    finish_update_request,
    start_update_request,
)
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.pipeline_repo import (
    get_pipeline_execution,
    get_pipeline_status_counts,
    list_dataset_pipeline_execution_snapshots,
    list_dataset_pipeline_execution_snapshots_scoped,
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
_OPERATION_KEY = "test_pipeline_refresh"


@dataclass(frozen=True)
class _Member:
    """catalog에 실재하는 exact membership triple (ADR-088 §결정 2)."""

    provider_dataset_id: int
    provider: str
    dataset_key: str
    sync_scope: str
    operation_key: str


_UPSERT_DATASET_SQL = text(
    """
    INSERT INTO provider_sync.provider_datasets (
        provider, dataset_key, display_name, source_kind, is_active, capabilities
    )
    SELECT :provider, :dataset_key, :provider, 'system', true,
           jsonb_build_object('schema_version', 1, 'produces', '[]'::jsonb,
                              'extensions', '{}'::jsonb)
    ON CONFLICT (provider, dataset_key) DO UPDATE SET display_name = EXCLUDED.display_name
    RETURNING provider_dataset_id
    """
)

_UPSERT_OPERATION_SQL = text(
    """
    INSERT INTO provider_sync.provider_dataset_operations (
        provider_dataset_id, operation_key, operation_kind, is_enabled
    )
    VALUES (CAST(:provider_dataset_id AS bigint), :operation_key, 'refresh', true)
    ON CONFLICT (provider_dataset_id, operation_key) DO NOTHING
    """
)

_UPSERT_SCOPE_SQL = text(
    """
    INSERT INTO provider_sync.provider_dataset_operation_scopes (
        provider_dataset_id, sync_scope, operation_key, operation_kind
    )
    VALUES (CAST(:provider_dataset_id AS bigint), :sync_scope, :operation_key, 'refresh')
    ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO NOTHING
    """
)

_INSERT_JOB_SQL = text(
    """
    INSERT INTO ops.import_jobs (
        job_id, kind, load_batch_id, parent_job_id, payload, status, progress, current_stage,
        created_at, started_at, dagster_run_id, trigger_kind, operation_key,
        dagster_run_status, dataset_membership_mode
    ) VALUES (
        CAST(:job_id AS uuid), :kind, CAST(:load_batch_id AS uuid), CAST(:parent_job_id AS uuid),
        CAST(:payload AS jsonb), :status, :progress, :current_stage,
        :created_at, :started_at, :dagster_run_id,
        :trigger_kind, :operation_key, :dagster_run_status, :dataset_membership_mode
    )
    """
)

_INSERT_JOB_MEMBER_SQL = text(
    """
    INSERT INTO ops.import_job_datasets (
        job_id, provider_dataset_id, sync_scope, operation_key
    ) VALUES (
        CAST(:job_id AS uuid), CAST(:provider_dataset_id AS bigint), :sync_scope, :operation_key
    )
    RETURNING import_job_dataset_id::text AS member_id
    """
)

_INSERT_REQUEST_SQL = text(
    """
    INSERT INTO ops.feature_update_requests (
        request_id, scope_type, scope, update_policy,
        run_mode, priority, matched_scope, job_id, operator, created_at,
        dataset_membership_mode
    ) VALUES (
        CAST(:request_id AS uuid), :scope_type, CAST(:scope AS jsonb), '{}'::jsonb,
        'queued', :priority, '{}'::jsonb,
        CAST(:job_id AS uuid), :operator, :created_at, 'single'
    )
    """
)

_INSERT_REQUEST_MEMBER_SQL = text(
    """
    INSERT INTO ops.feature_update_request_datasets (
        request_id, provider_dataset_id, sync_scope, operation_key
    ) VALUES (
        CAST(:request_id AS uuid), CAST(:provider_dataset_id AS bigint),
        :sync_scope, :operation_key
    )
    RETURNING feature_update_request_dataset_id::text AS member_id
    """
)

# dataset membership을 가진 job의 event는 그 member를 반드시 지목해야 한다
# (``ck_import_job_event_member_required``). root job event는 member가 NULL이어야 한다.
_INSERT_EVENT_SQL = text(
    """
    INSERT INTO ops.import_job_events (
        event_id, job_id, import_job_dataset_id, level, message, occurred_at
    ) VALUES (
        CAST(:event_id AS uuid), CAST(:job_id AS uuid),
        CAST(:import_job_dataset_id AS uuid), 'info', 'seed', :occurred_at
    )
    """
)


async def _member(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str = "dataset_wide",
    operation_key: str = _OPERATION_KEY,
) -> _Member:
    """catalog에 dataset+operation+scope를 심고 exact triple을 돌려준다."""
    provider_dataset_id = int(
        (
            await session.execute(
                _UPSERT_DATASET_SQL, {"provider": provider, "dataset_key": dataset_key}
            )
        ).scalar_one()
    )
    params = {"provider_dataset_id": provider_dataset_id, "operation_key": operation_key}
    await session.execute(_UPSERT_OPERATION_SQL, params)
    await session.execute(_UPSERT_SCOPE_SQL, {**params, "sync_scope": sync_scope})
    return _Member(
        provider_dataset_id=provider_dataset_id,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=sync_scope,
        operation_key=operation_key,
    )


async def _job(
    session: AsyncSession,
    job_id: str,
    *,
    kind: str = "provider_load",
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
    created_at: datetime = _T0,
    status: str = "queued",
    progress: int = 0,
    payload: dict[str, Any] | None = None,
    member: _Member | None = None,
) -> str | None:
    """job 1건 + (선택) canonical dataset membership 1건. membership id를 돌려준다."""
    await session.execute(
        _INSERT_JOB_SQL,
        {
            "job_id": job_id,
            "kind": kind,
            "load_batch_id": load_batch_id,
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
            "trigger_kind": (
                "manual"
                if kind == "provider_feature_load_run"
                else ("update_request" if kind == "feature_update_request" else None)
            ),
            "operation_key": (
                "test-v1" if kind == "provider_feature_load_run" else None
            ),
            "dagster_run_status": ("STARTED" if kind == "provider_feature_load_run" else None),
            "dataset_membership_mode": "root" if member is None else "single",
        },
    )
    if member is None:
        return None
    return str(
        (
            await session.execute(
                _INSERT_JOB_MEMBER_SQL,
                {
                    "job_id": job_id,
                    "provider_dataset_id": member.provider_dataset_id,
                    "sync_scope": member.sync_scope,
                    "operation_key": member.operation_key,
                },
            )
        ).scalar_one()
    )


async def _request(
    session: AsyncSession,
    request_id: str,
    *,
    job_id: str | None,
    created_at: datetime,
    member: _Member,
    direct: bool = False,
) -> str:
    """request 1건 + canonical membership 1건. membership id를 돌려준다.

    ``job_id=None``이면 canonical ``feature_update_request`` job을 함께 만든다.
    request root의 provider/dataset identity는 job이 아니라 request membership이
    소유한다(``canonical_provider_datasets``).
    """
    request_scope: dict[str, Any] = (
        {
            "type": "provider_dataset",
            "provider_dataset_id": member.provider_dataset_id,
            "sync_scope": member.sync_scope,
            "operation_key": member.operation_key,
        }
        if direct
        else {"type": "feature_ids", "feature_ids": ["f-1"]}
    )
    if job_id is None:
        job_id = str(uuid5(_REQUEST_JOB_NAMESPACE, request_id))
        await _job(
            session,
            job_id,
            kind="feature_update_request",
            created_at=created_at,
        )
    await session.execute(
        _INSERT_REQUEST_SQL,
        {
            "request_id": request_id,
            "scope_type": request_scope["type"],
            "scope": json.dumps(request_scope),
            "priority": 50,
            "job_id": job_id,
            "operator": "tester",
            "created_at": created_at,
        },
    )
    return str(
        (
            await session.execute(
                _INSERT_REQUEST_MEMBER_SQL,
                {
                    "request_id": request_id,
                    "provider_dataset_id": member.provider_dataset_id,
                    "sync_scope": member.sync_scope,
                    "operation_key": member.operation_key,
                },
            )
        ).scalar_one()
    )


async def _event(
    session: AsyncSession,
    event_id: str,
    *,
    job_id: str,
    member_id: str | None = None,
) -> None:
    await session.execute(
        _INSERT_EVENT_SQL,
        {
            "event_id": event_id,
            "job_id": job_id,
            "import_job_dataset_id": member_id,
            "occurred_at": _T0,
        },
    )


def _pairs(execution: Any) -> dict[tuple[str, str], Any]:
    return {
        (pair.provider, pair.dataset_key): pair for pair in execution.provider_datasets
    }


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

    base_access = [node for node in nodes if node.get("Relation Name") in base_relations]
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


async def _seed_owned_hierarchy(session: AsyncSession) -> _Member:
    # ADR-077: lineage는 ≤2단계(root + 자식). 과거 3단계(grandchild)는 stamp
    # 트리거가 거부하므로 root + 자식 하나로 소유 계층을 구성한다. request root의
    # projected winner는 (run root가 아니므로) 가장 깊은 member = 자식이다.
    member = await _member(
        session, provider="stored-provider", dataset_key="stored-dataset"
    )
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
    await _request(
        session,
        _REQUEST_OWNER,
        job_id=_JOB_ROOT,
        created_at=_T0 + timedelta(minutes=3),
        member=member,
    )
    return member


async def test_request_anchor_collapses_descendants_and_projects_deepest_job(
    migrated_session: AsyncSession,
) -> None:
    member = await _seed_owned_hierarchy(migrated_session)

    page = await list_pipeline_executions(migrated_session)

    assert [(item.kind, item.id) for item in page.items] == [("update_request", _REQUEST_OWNER)]
    root = page.items[0]
    assert root.requested_job_id == _JOB_ROOT
    assert root.linked_job_count == 2
    assert [
        (pair.provider, pair.dataset_key, pair.sync_scope, pair.operation_key)
        for pair in root.provider_datasets
    ] == [
        (member.provider, member.dataset_key, member.sync_scope, member.operation_key)
    ]
    assert root.progress is None
    assert root.projected_job.id == _JOB_CHILD
    assert root.projected_job.depth == 1
    assert root.projected_job.status == "running"


async def test_standalone_hierarchy_ignores_audit_event_and_payload_identity(
    migrated_session: AsyncSession,
) -> None:
    unrelated = await _member(
        migrated_session, provider="provider-a", dataset_key="dataset-z"
    )
    await _job(
        migrated_session,
        _JOB_ROOT,
        payload={"provider": "misleading", "dataset_key": "wrong"},
    )
    await _job(migrated_session, _JOB_CHILD, parent_job_id=_JOB_ROOT)
    await _event(
        migrated_session,
        "61111111-1111-4111-8111-111111111111",
        job_id=_JOB_ROOT,
    )
    await _event(
        migrated_session,
        "62222222-2222-4222-8222-222222222222",
        job_id=_JOB_CHILD,
    )
    await _event(
        migrated_session,
        "63333333-3333-4333-8333-333333333333",
        job_id=_JOB_CHILD,
    )

    page = await list_pipeline_executions(migrated_session)

    assert len(page.items) == 1
    root = page.items[0]
    assert root.id == _JOB_ROOT
    assert root.linked_job_count == 2
    # payload의 provider/dataset_key 문자열은 identity가 아니다 — membership이 없다.
    assert root.provider_datasets == ()
    assert (
        await list_pipeline_executions(
            migrated_session, provider_dataset_id=unrelated.provider_dataset_id
        )
    ).items == ()


async def test_root_id_stamped_and_two_level_lineage_enforced(
    migrated_session: AsyncSession,
) -> None:
    """ADR-077: stamp 트리거가 root_id를 부모에서 파생하고, 2단계 초과·존재하지
    않는 parent를 거부한다(과거의 임의 depth·cycle 재귀 대신 저장·불변식)."""
    root = "71111111-1111-4111-8111-111111111111"
    child = "72222222-2222-4222-8222-222222222222"
    grandchild = "73333333-3333-4333-8333-333333333333"
    absent = "7fffffff-ffff-4fff-8fff-ffffffffffff"

    await _job(migrated_session, root, created_at=_T0)
    await _job(
        migrated_session, child, parent_job_id=root, created_at=_T0 + timedelta(minutes=1)
    )

    root_row = (
        await migrated_session.execute(
            text(
                "SELECT root_id::text AS root_id, root_kind FROM ops.import_jobs "
                "WHERE job_id = CAST(:j AS uuid)"
            ),
            {"j": root},
        )
    ).one()
    assert root_row.root_id == root  # parent NULL → self root
    assert root_row.root_kind == "import_job"
    child_row = (
        await migrated_session.execute(
            text(
                "SELECT root_id::text AS root_id, root_kind FROM ops.import_jobs "
                "WHERE job_id = CAST(:j AS uuid)"
            ),
            {"j": child},
        )
    ).one()
    assert child_row.root_id == root  # 자식은 부모의 root 승계
    assert child_row.root_kind == "import_job"

    # 3단계(자식의 자식)는 stamp 트리거가 거부한다.
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _job(
                migrated_session,
                grandchild,
                parent_job_id=child,
                created_at=_T0 + timedelta(minutes=2),
            )

    # 존재하지 않는 parent는 FK가 거부한다.
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _job(
                migrated_session,
                "74444444-4444-4444-8444-444444444444",
                parent_job_id=absent,
            )

    # 양방향 lock: 자식을 이미 가진 job(root)을 다른 root로 reparent하면 3단계가
    # 되므로 leaf guard가 거부한다(리뷰어 지적 — parent-is-root만으로는 부족).
    other_root = "75555555-5555-4555-8555-555555555555"
    await _job(migrated_session, other_root, created_at=_T0 + timedelta(minutes=3))
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE ops.import_jobs SET parent_job_id = CAST(:p AS uuid) "
                    "WHERE job_id = CAST(:j AS uuid)"
                ),
                {"p": other_root, "j": root},
            )


async def test_duplicate_requests_on_same_anchor_are_rejected(
    migrated_session: AsyncSession,
) -> None:
    await _seed_owned_hierarchy(migrated_session)
    loser_member = await _member(
        migrated_session, provider="loser-provider", dataset_key="loser-dataset"
    )
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _request(
                migrated_session,
                _REQUEST_LOSER,
                job_id=_JOB_ROOT,
                created_at=_T0 + timedelta(minutes=4),
                member=loser_member,
            )

    page = await list_pipeline_executions(migrated_session)

    assert [item.id for item in page.items] == [_REQUEST_OWNER]
    owner = page.items[0]
    assert owner.linked_job_count == 2


async def test_request_cannot_anchor_to_noncanonical_child_job(
    migrated_session: AsyncSession,
) -> None:
    await _seed_owned_hierarchy(migrated_session)
    nested_member = await _member(
        migrated_session, provider="nested-provider", dataset_key="nested-dataset"
    )
    nested_request = "56666666-6666-4666-8666-666666666666"
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await _request(
                migrated_session,
                nested_request,
                job_id=_JOB_CHILD,
                created_at=_T0 + timedelta(minutes=4),
                member=nested_member,
            )

    page = await list_pipeline_executions(migrated_session)

    assert [item.id for item in page.items] == [_REQUEST_OWNER]
    assert page.items[0].linked_job_count == 2
    assert page.items[0].projected_job.id == _JOB_CHILD


async def test_feature_run_projects_root_and_exposes_pair_child_status(
    migrated_session: AsyncSession,
) -> None:
    root_id = "b1111111-1111-4111-8111-111111111111"
    child_id = "b2222222-2222-4222-8222-222222222222"
    member = await _member(
        migrated_session, provider="provider-a", dataset_key="dataset-a"
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
                job_id, kind, payload, status, progress, current_stage,
                dagster_run_id, trigger_kind, operation_key,
                dagster_run_status, created_at, started_at, dataset_membership_mode
            ) VALUES (
                CAST(:root_id AS uuid), 'provider_feature_load_run', '{}'::jsonb,
                'running', 15, 'engine', 'feature-run-1', 'manual', 'v1',
                'STARTED', :created_at, :created_at, 'root'
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
                current_stage, dagster_run_id,
                created_at, started_at, finished_at, dataset_membership_mode
            ) VALUES (
                CAST(:child_id AS uuid), 'provider_feature_load',
                CAST(:root_id AS uuid), '{}'::jsonb, 'failed', 70, 'pair',
                'feature-run-1', :created_at,
                :created_at, :created_at, 'single'
            )
            """
        ),
        {"root_id": root_id, "child_id": child_id, "created_at": _T0},
    )
    member_id = str(
        (
            await migrated_session.execute(
                _INSERT_JOB_MEMBER_SQL,
                {
                    "job_id": child_id,
                    "provider_dataset_id": member.provider_dataset_id,
                    "sync_scope": member.sync_scope,
                    "operation_key": member.operation_key,
                },
            )
        ).scalar_one()
    )

    page = await list_pipeline_executions(migrated_session)

    root = page.items[0]
    assert root.id == root_id
    assert root.status == "running"
    assert root.dagster_run_status == "STARTED"
    assert root.trigger_kind == "manual"
    assert root.operation_key == "v1"
    assert root.projected_job.id == root_id
    assert root.projected_job.status == "running"
    assert root.provider_datasets == (
        pipeline_repo.PipelineProviderDatasetIdentity(
            provider_dataset_id=member.provider_dataset_id,
            provider="provider-a",
            dataset_key="dataset-a",
            sync_scope="dataset_wide",
            operation_key=_OPERATION_KEY,
            operation_member_id=member_id,
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


async def test_typed_pair_is_canonical_when_audit_event_inherits_owner_pair(
    migrated_session: AsyncSession,
) -> None:
    typed = await _member(
        migrated_session, provider="typed-provider", dataset_key="typed-dataset"
    )
    other = await _member(
        migrated_session, provider="event-provider", dataset_key="event-dataset"
    )
    typed_member_id = await _job(migrated_session, _JOB_ROOT, member=typed)
    await _event(
        migrated_session,
        "b3333333-3333-4333-8333-333333333333",
        job_id=_JOB_ROOT,
        member_id=typed_member_id,
    )

    root = (await list_pipeline_executions(migrated_session)).items[0]

    assert [(pair.provider, pair.dataset_key) for pair in root.provider_datasets] == [
        ("typed-provider", "typed-dataset")
    ]
    assert (
        await list_pipeline_executions(
            migrated_session, provider_dataset_id=other.provider_dataset_id
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
    assert latest[0].provider_dataset_id == typed.provider_dataset_id


async def test_event_only_sibling_does_not_create_canonical_pair(
    migrated_session: AsyncSession,
) -> None:
    typed = await _member(
        migrated_session, provider="provider-typed", dataset_key="dataset-typed"
    )
    legacy = await _member(
        migrated_session, provider="provider-legacy", dataset_key="dataset-legacy"
    )
    await _job(migrated_session, _JOB_ROOT, status="queued")
    typed_member_id = await _job(
        migrated_session,
        _JOB_CHILD,
        parent_job_id=_JOB_ROOT,
        status="running",
        member=typed,
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
        member_id=typed_member_id,
    )
    await _event(
        migrated_session,
        "b5555555-5555-4555-8555-555555555555",
        job_id=_JOB_GRANDCHILD,
    )

    root = (await list_pipeline_executions(migrated_session)).items[0]
    pairs = _pairs(root)

    assert set(pairs) == {("provider-typed", "dataset-typed")}
    assert pairs[("provider-typed", "dataset-typed")].status == "running"
    filtered = await list_pipeline_executions(
        migrated_session, provider_dataset_id=typed.provider_dataset_id
    )
    assert [item.id for item in filtered.items] == [_JOB_ROOT]
    # membership이 없는 dataset은 event가 있어도 root를 만들지 않는다.
    assert (
        await list_pipeline_executions(
            migrated_session, provider_dataset_id=legacy.provider_dataset_id
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
    latest_by_pair = {(item.provider, item.dataset_key): item for item in latest}
    assert set(latest_by_pair) == set(pairs)
    assert all(item.execution.id == _JOB_ROOT for item in latest_by_pair.values())
    assert latest_by_pair[("provider-typed", "dataset-typed")].pair_status == "running"


async def test_audit_events_never_create_provider_dataset_identity(
    migrated_session: AsyncSession,
) -> None:
    """T-VN-33: identity는 membership FK뿐이다 — audit event는 결코 pair를 만들지
    않는다(구 버전이 방어하던 자유 문자열 provider/dataset_key 열 자체가 사라졌다)."""
    unrelated = await _member(
        migrated_session, provider="provider-valid", dataset_key="dataset-valid"
    )
    await _job(migrated_session, _JOB_ROOT)
    await _job(migrated_session, _JOB_CHILD, parent_job_id=_JOB_ROOT)
    await _job(migrated_session, _JOB_GRANDCHILD, parent_job_id=_JOB_ROOT)
    for index in range(1, 6):
        await _event(
            migrated_session,
            f"b6000000-0000-4000-8000-{index:012d}",
            job_id=_JOB_GRANDCHILD if index > 1 else _JOB_CHILD,
        )

    root = (await list_pipeline_executions(migrated_session)).items[0]

    assert root.provider_datasets == ()
    detail = await get_pipeline_execution(
        migrated_session,
        kind="import_job",
        execution_id=_JOB_GRANDCHILD,
    )
    assert detail is not None
    assert detail.provider_datasets == root.provider_datasets
    assert (
        await list_pipeline_executions(
            migrated_session, provider_dataset_id=unrelated.provider_dataset_id
        )
    ).items == ()
    assert await list_latest_dataset_pipeline_executions(migrated_session) == ()


async def test_direct_request_pair_is_unchanged_by_inherited_audit_identity(
    migrated_session: AsyncSession,
) -> None:
    direct = await _member(
        migrated_session,
        provider="provider-direct",
        dataset_key="dataset-direct",
        sync_scope="target_grids",
    )
    legacy = await _member(
        migrated_session, provider="provider-legacy", dataset_key="dataset-legacy"
    )
    await _job(
        migrated_session,
        _JOB_ROOT,
        kind="feature_update_request",
    )
    member_id = await _request(
        migrated_session,
        _REQUEST_OWNER,
        job_id=_JOB_ROOT,
        created_at=_T0 + timedelta(minutes=1),
        member=direct,
        direct=True,
    )
    await _event(
        migrated_session,
        "b6666666-6666-4666-8666-666666666666",
        job_id=_JOB_ROOT,
    )

    root = (await list_pipeline_executions(migrated_session)).items[0]
    pairs = _pairs(root)

    assert root.kind == "update_request"
    assert root.id == _REQUEST_OWNER
    assert set(pairs) == {("provider-direct", "dataset-direct")}
    assert pairs[("provider-direct", "dataset-direct")].sync_scope == "target_grids"
    assert pairs[("provider-direct", "dataset-direct")].operation_member_id == member_id
    assert (
        await list_pipeline_executions(
            migrated_session, provider_dataset_id=legacy.provider_dataset_id
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
    owned = await _member(
        migrated_session, provider="owned-provider", dataset_key="owned-dataset"
    )
    standalone_member = await _member(
        migrated_session, provider="standalone-provider", dataset_key="standalone-dataset"
    )
    request_a_member = await _member(
        migrated_session, provider="request-provider", dataset_key="request-dataset-a"
    )
    request_b_member = await _member(
        migrated_session, provider="request-provider", dataset_key="request-dataset-b"
    )
    await _job(migrated_session, batch_root, created_at=_T0)
    await _job(
        migrated_session,
        branch_a,
        kind="feature_update_request",
        created_at=_T0,
    )
    owned_member_id = await _job(
        migrated_session,
        branch_a_child,
        parent_job_id=branch_a,
        created_at=_T0 + timedelta(minutes=1),
        member=owned,
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
    standalone_member_id = await _job(
        migrated_session,
        unowned_descendant,
        parent_job_id=batch_root,
        created_at=_T0 + timedelta(minutes=2),
        member=standalone_member,
    )
    await _request(
        migrated_session,
        request_a,
        job_id=branch_a,
        created_at=_T0 + timedelta(minutes=3),
        member=request_a_member,
    )
    await _request(
        migrated_session,
        request_b,
        job_id=branch_b,
        created_at=_T0 + timedelta(minutes=4),
        member=request_b_member,
    )
    await _event(
        migrated_session,
        "e1111111-1111-4111-8111-111111111111",
        job_id=branch_a_child,
        member_id=owned_member_id,
    )
    await _event(
        migrated_session,
        "e2222222-2222-4222-8222-222222222222",
        job_id=unowned_descendant,
        member_id=standalone_member_id,
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
    assert [
        (pair.provider, pair.dataset_key) for pair in standalone.provider_datasets
    ] == [("standalone-provider", "standalone-dataset")]
    assert by_key[("update_request", request_a)].linked_job_count == 2
    assert by_key[("update_request", request_b)].linked_job_count == 2
    assert sum(item.linked_job_count for item in page.items) == 7
    # request branch가 소유한 job membership은 import_job root로 노출되지 않는다.
    assert (
        await list_pipeline_executions(
            migrated_session,
            kind="import_job",
            provider_dataset_id=owned.provider_dataset_id,
        )
    ).items == ()


async def test_cursor_kind_breaks_same_timestamp_and_uuid_tie(
    migrated_session: AsyncSession,
) -> None:
    shared = "91111111-1111-4111-8111-111111111111"
    at = _T0 + timedelta(days=1)
    member = await _member(
        migrated_session, provider="tie-provider", dataset_key="tie-dataset"
    )
    await _job(migrated_session, shared, created_at=at)
    await _request(migrated_session, shared, job_id=None, created_at=at, member=member)

    first = await list_pipeline_executions(migrated_session, limit=1)
    second = await list_pipeline_executions(migrated_session, limit=1, cursor=first.next_cursor)

    assert [(item.kind, item.id) for item in first.items] == [("update_request", shared)]
    assert first.next_cursor is not None
    assert [(item.kind, item.id) for item in second.items] == [("import_job", shared)]
    assert second.next_cursor is None


async def test_component_membership_filters_are_applied_before_page_limit(
    migrated_session: AsyncSession,
) -> None:
    target_root = "a9111111-1111-4111-8111-111111111111"
    target_child = "a9222222-2222-4222-8222-222222222222"
    load_batch_id = "a9333333-3333-4333-8333-333333333333"
    await _job(
        migrated_session,
        target_root,
        kind="provider_feature_load_run",
        created_at=_T0,
        status="running",
    )
    await _job(
        migrated_session,
        target_child,
        load_batch_id=load_batch_id,
        parent_job_id=target_root,
        created_at=_T0 + timedelta(minutes=1),
    )
    for index in range(3):
        await _job(
            migrated_session,
            str(uuid5(_REQUEST_JOB_NAMESPACE, f"newer-unrelated-root-{index}")),
            created_at=_T0 + timedelta(hours=index + 1),
        )

    by_batch = await list_pipeline_executions(
        migrated_session,
        load_batch_id=load_batch_id,
        limit=1,
    )
    by_parent = await list_pipeline_executions(
        migrated_session,
        parent_job_id=target_root,
        limit=1,
    )

    assert [(item.kind, item.id) for item in by_batch.items] == [("import_job", target_root)]
    assert by_batch.items[0].projected_job.id == target_root
    assert by_batch.next_cursor is None
    assert [(item.kind, item.id) for item in by_parent.items] == [("import_job", target_root)]
    assert by_parent.next_cursor is None

    request_root = "a9444444-4444-4444-8444-444444444444"
    request_child = "a9555555-5555-4555-8555-555555555555"
    request_id = "a9666666-6666-4666-8666-666666666666"
    request_load_batch_id = "a9777777-7777-4777-8777-777777777777"
    request_projection = "a9888888-8888-4888-8888-888888888888"
    request_member = await _member(
        migrated_session, provider="membership-provider", dataset_key="membership-dataset"
    )
    await _job(
        migrated_session,
        request_root,
        kind="feature_update_request",
        created_at=_T0 - timedelta(hours=2),
    )
    await _job(
        migrated_session,
        request_child,
        load_batch_id=request_load_batch_id,
        parent_job_id=request_root,
        created_at=_T0 - timedelta(hours=1),
    )
    await _job(
        migrated_session,
        request_projection,
        parent_job_id=request_root,
        created_at=_T0 - timedelta(minutes=30),
    )
    await _request(
        migrated_session,
        request_id,
        job_id=request_root,
        created_at=_T0 - timedelta(hours=2),
        member=request_member,
    )

    request_by_batch = await list_pipeline_executions(
        migrated_session,
        load_batch_id=request_load_batch_id,
        limit=1,
    )
    request_by_parent = await list_pipeline_executions(
        migrated_session,
        parent_job_id=request_root,
        limit=1,
    )

    assert [(item.kind, item.id) for item in request_by_batch.items] == [
        ("update_request", request_id)
    ]
    assert request_by_batch.items[0].projected_job.id == request_projection
    assert request_by_batch.next_cursor is None
    assert [(item.kind, item.id) for item in request_by_parent.items] == [
        ("update_request", request_id)
    ]
    assert request_by_parent.next_cursor is None


async def test_direct_scope_cannot_disagree_with_canonical_membership(
    migrated_session: AsyncSession,
) -> None:
    """direct scope는 자신의 canonical membership과 정확히 일치해야 한다.

    T-VN-33 이전에는 request.scope의 provider/dataset_key 문자열과 job 열의 사본이
    어긋나는지를 DB 트리거가 봤다. 사본이 사라진 지금 이 불변식은 제출 경로가
    exact triple 대조로 든다(``_resolve_feature_update_plan``).
    """
    scope_member = await _member(
        migrated_session, provider="scope-provider", dataset_key="scope-dataset"
    )
    other_member = await _member(
        migrated_session, provider="typed-provider", dataset_key="typed-dataset"
    )

    with pytest.raises(ValueError, match="canonical membership"):
        await enqueue_feature_update_request(
            migrated_session,
            scope={
                "type": "provider_dataset",
                "provider_dataset_id": scope_member.provider_dataset_id,
                "sync_scope": scope_member.sync_scope,
                "operation_key": scope_member.operation_key,
            },
            dataset_memberships=[
                ImportJobDatasetTarget(
                    provider_dataset_id=other_member.provider_dataset_id,
                    sync_scope=other_member.sync_scope,
                    operation_key=other_member.operation_key,
                )
            ],
        )

    assert (await list_pipeline_executions(migrated_session)).items == ()


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
        member = await _member(
            migrated_session,
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=sync_scope,
        )
        await _request(
            migrated_session,
            request_id,
            job_id=None,
            created_at=created_at,
            member=member,
            direct=True,
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


async def test_dataset_execution_snapshot_keeps_terminal_and_active_independent(
    migrated_session: AsyncSession,
) -> None:
    provider = "python-kma-api"
    dataset_key = "kma_short_forecast"
    sync_scope = "target_grids"
    terminal_request_id = "a5555555-5555-4555-8555-555555555555"
    active_request_id = "a6666666-6666-4666-8666-666666666666"
    member = await _member(
        migrated_session,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=sync_scope,
    )
    await _request(
        migrated_session,
        terminal_request_id,
        job_id=None,
        created_at=_T0,
        member=member,
        direct=True,
    )
    started = await start_update_request(
        migrated_session,
        terminal_request_id,
        dagster_run_id="terminal-snapshot-run",
        expected_generation=1,
    )
    assert started is not None
    finished = await finish_update_request(
        migrated_session,
        terminal_request_id,
        status="done",
        owner_dagster_run_id="terminal-snapshot-run",
        expected_generation=1,
    )
    assert finished is not None
    await _request(
        migrated_session,
        active_request_id,
        job_id=None,
        created_at=_T0 + timedelta(minutes=1),
        member=member,
        direct=True,
    )

    snapshots = await list_dataset_pipeline_execution_snapshots(migrated_session)
    snapshot = next(
        item
        for item in snapshots
        if (item.provider, item.dataset_key, item.sync_scope)
        == (provider, dataset_key, sync_scope)
    )

    assert snapshot.latest_terminal is not None
    assert snapshot.latest_terminal.execution.id == terminal_request_id
    assert snapshot.latest_terminal.pair_status == "done"
    assert snapshot.active is not None
    assert snapshot.active.execution.id == active_request_id
    assert snapshot.active.pair_status == "queued"


async def test_scoped_dataset_execution_snapshot_matches_unscoped_filtered(
    migrated_session: AsyncSession,
) -> None:
    """scoped snapshot 쿼리는 대상 canonical dataset에 대해 unscoped 결과를
    필터한 것과 동일해야 한다(다른 dataset의 root가 존재해도 제외한다)."""
    provider = "python-kma-api"
    dataset_key = "kma_short_forecast"
    other_dataset_key = "kma_ultra_short_nowcast"
    sync_scope = "target_grids"

    target_terminal_id = str(uuid5(_REQUEST_JOB_NAMESPACE, "scoped-target-terminal"))
    target_active_id = str(uuid5(_REQUEST_JOB_NAMESPACE, "scoped-target-active"))
    other_request_id = str(uuid5(_REQUEST_JOB_NAMESPACE, "scoped-other-dataset"))

    target = await _member(
        migrated_session,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=sync_scope,
    )
    other = await _member(
        migrated_session,
        provider=provider,
        dataset_key=other_dataset_key,
        sync_scope=sync_scope,
    )

    # 대상 dataset: 종료 실행 + 활성 실행
    await _request(
        migrated_session,
        target_terminal_id,
        job_id=None,
        created_at=_T0,
        member=target,
        direct=True,
    )
    started = await start_update_request(
        migrated_session,
        target_terminal_id,
        dagster_run_id="scoped-target-run",
        expected_generation=1,
    )
    assert started is not None
    finished = await finish_update_request(
        migrated_session,
        target_terminal_id,
        status="done",
        owner_dagster_run_id="scoped-target-run",
        expected_generation=1,
    )
    assert finished is not None
    await _request(
        migrated_session,
        target_active_id,
        job_id=None,
        created_at=_T0 + timedelta(minutes=1),
        member=target,
        direct=True,
    )
    # 다른 dataset의 root — scoped 결과에서 반드시 제외돼야 한다
    await _request(
        migrated_session,
        other_request_id,
        job_id=None,
        created_at=_T0 + timedelta(minutes=2),
        member=other,
        direct=True,
    )

    unscoped = await list_dataset_pipeline_execution_snapshots(migrated_session)
    scoped = await list_dataset_pipeline_execution_snapshots_scoped(
        migrated_session, provider_dataset_id=target.provider_dataset_id
    )

    def _identity(items: tuple[Any, ...]) -> set[tuple[Any, ...]]:
        return {
            (
                s.provider_dataset_id,
                s.sync_scope,
                s.latest_terminal.execution.id if s.latest_terminal else None,
                s.active.execution.id if s.active else None,
            )
            for s in items
        }

    unscoped_target = tuple(
        s for s in unscoped if s.provider_dataset_id == target.provider_dataset_id
    )
    # 핵심 등가 주장: scoped == unscoped를 대상 dataset으로 필터한 것
    assert _identity(scoped) == _identity(unscoped_target)
    # 다른 dataset은 unscoped엔 있고 scoped엔 없다
    assert any(s.provider_dataset_id == other.provider_dataset_id for s in unscoped)
    assert all(s.provider_dataset_id == target.provider_dataset_id for s in scoped)
    # 대상 dataset의 terminal/active identity가 보존된다
    result = next(s for s in scoped if s.sync_scope == sync_scope)
    assert result.latest_terminal is not None
    assert result.latest_terminal.execution.id == target_terminal_id
    assert result.active is not None
    assert result.active.execution.id == target_active_id


async def test_dataset_scope_filter_is_applied_before_page_limit(
    migrated_session: AsyncSession,
) -> None:
    provider = "python-kma-api"
    dataset_key = "kma_short_forecast"
    selected_scope = "external_system:retired"
    selected = await _member(
        migrated_session,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=selected_scope,
    )
    child_member = await _member(
        migrated_session, provider="python-other-api", dataset_key="other-dataset"
    )
    selected_request_ids: list[str] = []
    for index in range(11):
        selected_request_id = str(uuid5(_REQUEST_JOB_NAMESPACE, f"selected-retired-scope-{index}"))
        selected_request_ids.append(selected_request_id)
        selected_created_at = _T0 + timedelta(minutes=index * 2)
        await _request(
            migrated_session,
            selected_request_id,
            job_id=None,
            created_at=selected_created_at,
            member=selected,
            direct=True,
        )
        selected_job_id = str(uuid5(_REQUEST_JOB_NAMESPACE, selected_request_id))
        if index == 0:
            await _job(
                migrated_session,
                str(uuid5(_REQUEST_JOB_NAMESPACE, "selected-multi-pair-child")),
                parent_job_id=selected_job_id,
                created_at=selected_created_at,
                status="done",
                progress=100,
                member=child_member,
            )
        owner = f"selected-scope-run-{index}"
        started = await start_update_request(
            migrated_session,
            selected_request_id,
            dagster_run_id=owner,
            expected_generation=1,
        )
        assert started is not None
        finished = await finish_update_request(
            migrated_session,
            selected_request_id,
            status="done",
            owner_dagster_run_id=owner,
            expected_generation=1,
        )
        assert finished is not None
        interleaved = await _member(
            migrated_session,
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=f"external_system:other-{index}",
        )
        await _request(
            migrated_session,
            str(uuid5(_REQUEST_JOB_NAMESPACE, f"interleaved-other-scope-{index}")),
            job_id=None,
            created_at=selected_created_at + timedelta(minutes=1),
            member=interleaved,
            direct=True,
        )

    unscoped_page = await list_pipeline_executions(
        migrated_session,
        provider_dataset_id=selected.provider_dataset_id,
        limit=10,
    )
    exact_first_page = await list_pipeline_executions(
        migrated_session,
        provider_dataset_id=selected.provider_dataset_id,
        dataset_sync_scopes=(selected_scope,),
        limit=10,
    )
    assert exact_first_page.next_cursor is not None
    exact_second_page = await list_pipeline_executions(
        migrated_session,
        provider_dataset_id=selected.provider_dataset_id,
        dataset_sync_scopes=(selected_scope,),
        limit=10,
        cursor=exact_first_page.next_cursor,
    )

    exact_ids = [item.id for item in (*exact_first_page.items, *exact_second_page.items)]
    assert len(unscoped_page.items) == 10
    assert exact_ids == list(reversed(selected_request_ids))
    assert len(exact_ids) == len(set(exact_ids)) == 11
    assert exact_second_page.next_cursor is None
    multi_pair_root = exact_second_page.items[0]
    assert multi_pair_root.id == selected_request_ids[0]
    # request root의 canonical pair는 request membership이 든다 — 하위 job의
    # membership은 import_job root에서만 노출된다.
    assert {
        (pair.provider, pair.dataset_key, pair.sync_scope)
        for pair in multi_pair_root.provider_datasets
    } == {(provider, dataset_key, selected_scope)}
    assert child_member.provider_dataset_id > 0


async def test_status_counts_for_overview(migrated_session: AsyncSession) -> None:
    member = await _member(
        migrated_session, provider="counts-provider", dataset_key="counts-dataset"
    )
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
        member=member,
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
    bulk = await _member(
        migrated_session, provider="bulk-provider", dataset_key="bulk-dataset"
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key, operation_kind
            )
            SELECT CAST(:provider_dataset_id AS bigint),
                   'external_system:bulk-' || lpad(seed.n::text, 4, '0'),
                   :operation_key, 'refresh'
            FROM generate_series(1, :root_count) AS seed(n)
            """
        ),
        {
            "provider_dataset_id": bulk.provider_dataset_id,
            "operation_key": bulk.operation_key,
            "root_count": root_count,
        },
    )
    await migrated_session.execute(
        text(
            """
            WITH inserted AS (
                INSERT INTO ops.import_jobs (
                    kind, payload, status, trigger_kind, created_at,
                    dataset_membership_mode
                )
                SELECT
                    'bulk_projection_fixture', '{}'::jsonb, 'queued', 'manual',
                    CAST(:created_at AS timestamptz)
                        + seed.n * INTERVAL '1 millisecond',
                    'single'
                FROM generate_series(1, :root_count) AS seed(n)
                RETURNING job_id, created_at
            )
            INSERT INTO ops.import_job_datasets (
                job_id, provider_dataset_id, sync_scope, operation_key
            )
            SELECT
                inserted.job_id,
                CAST(:provider_dataset_id AS bigint),
                'external_system:bulk-' || lpad(
                    (ROW_NUMBER() OVER (ORDER BY inserted.created_at))::text, 4, '0'
                ),
                :operation_key
            FROM inserted
            """
        ),
        {
            "created_at": _T0,
            "root_count": root_count,
            "provider_dataset_id": bulk.provider_dataset_id,
            "operation_key": bulk.operation_key,
        },
    )

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = await list_pipeline_executions(
            migrated_session,
            provider_dataset_id=bulk.provider_dataset_id,
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
        (item.provider, item.dataset_key, item.sync_scope) for item in latest
    } == {
        ("bulk-provider", "bulk-dataset", f"external_system:bulk-{number:04d}")
        for number in range(1, root_count + 1)
    }
    assert counts.operations_by_status == {"queued": root_count}
    assert counts.active_operations == root_count


_PLAN_NOISE_COUNT = 1_200


async def _seed_selective_projection_cardinality(
    session: AsyncSession,
) -> dict[str, Any]:
    event_only_job_id = "71111111-1111-4111-8111-111111111111"
    direct_request_id = "72222222-2222-4222-8222-222222222222"
    membership_load_batch_id = "78888888-8888-4888-8888-888888888888"

    typed = await _member(
        session, provider="typed-provider", dataset_key="typed-dataset"
    )
    direct = await _member(
        session, provider="direct-provider", dataset_key="direct-dataset"
    )
    owner = await _member(
        session, provider="owner-provider", dataset_key="owner-dataset"
    )

    await _job(session, _JOB_ROOT, kind="feature_update_request")
    await _job(
        session,
        _JOB_CHILD,
        load_batch_id=membership_load_batch_id,
        parent_job_id=_JOB_ROOT,
        member=typed,
    )
    await _request(
        session,
        _REQUEST_OWNER,
        job_id=_JOB_ROOT,
        created_at=_T0 + timedelta(minutes=1),
        member=owner,
    )

    await _job(session, event_only_job_id)
    await _event(
        session,
        "75555555-5555-4555-8555-555555555555",
        job_id=event_only_job_id,
    )
    await _request(
        session,
        direct_request_id,
        job_id=None,
        created_at=_T0,
        member=direct,
        direct=True,
    )

    # --- noise: 서로 다른 canonical dataset을 가진 job/request root 다수 --------
    noise_params = {"noise_count": _PLAN_NOISE_COUNT, "operation_key": _OPERATION_KEY}
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind, is_active, capabilities
            )
            SELECT 'noise-provider', 'noise-dataset-' || seed.n::text, 'noise', 'system',
                   true,
                   jsonb_build_object('schema_version', 1, 'produces', '[]'::jsonb,
                                      'extensions', '{}'::jsonb)
            FROM generate_series(1, :noise_count) AS seed(n)
            """
        ),
        noise_params,
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operations (
                provider_dataset_id, operation_key, operation_kind, is_enabled
            )
            SELECT dataset.provider_dataset_id, :operation_key, 'refresh', true
            FROM provider_sync.provider_datasets AS dataset
            WHERE dataset.provider = 'noise-provider'
            """
        ),
        noise_params,
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key, operation_kind
            )
            SELECT dataset.provider_dataset_id, 'dataset_wide', :operation_key, 'refresh'
            FROM provider_sync.provider_datasets AS dataset
            WHERE dataset.provider = 'noise-provider'
            """
        ),
        noise_params,
    )
    await session.execute(
        text(
            """
            WITH noise AS (
                SELECT dataset.provider_dataset_id,
                       ROW_NUMBER() OVER (ORDER BY dataset.provider_dataset_id) AS rn
                FROM provider_sync.provider_datasets AS dataset
                WHERE dataset.provider = 'noise-provider'
            ), inserted AS (
                INSERT INTO ops.import_jobs (
                    kind, payload, status, trigger_kind, created_at,
                    dataset_membership_mode
                )
                SELECT 'projection_plan_noise', '{}'::jsonb, 'queued', 'update_request',
                       CAST(:created_at AS timestamptz), 'single'
                FROM noise
                RETURNING job_id
            ), numbered AS (
                SELECT job_id, ROW_NUMBER() OVER (ORDER BY job_id) AS rn FROM inserted
            )
            INSERT INTO ops.import_job_datasets (
                job_id, provider_dataset_id, sync_scope, operation_key
            )
            SELECT numbered.job_id, noise.provider_dataset_id, 'dataset_wide', :operation_key
            FROM numbered
            JOIN noise ON noise.rn = numbered.rn
            """
        ),
        {**noise_params, "created_at": _T0},
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind, is_active, capabilities
            )
            SELECT 'noise-request-provider', 'noise-request-dataset-' || seed.n::text,
                   'noise', 'system', true,
                   jsonb_build_object('schema_version', 1, 'produces', '[]'::jsonb,
                                      'extensions', '{}'::jsonb)
            FROM generate_series(1, :noise_count) AS seed(n)
            """
        ),
        noise_params,
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operations (
                provider_dataset_id, operation_key, operation_kind, is_enabled
            )
            SELECT dataset.provider_dataset_id, :operation_key, 'refresh', true
            FROM provider_sync.provider_datasets AS dataset
            WHERE dataset.provider = 'noise-request-provider'
            """
        ),
        noise_params,
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key, operation_kind
            )
            SELECT dataset.provider_dataset_id, 'dataset_wide', :operation_key, 'refresh'
            FROM provider_sync.provider_datasets AS dataset
            WHERE dataset.provider = 'noise-request-provider'
            """
        ),
        noise_params,
    )
    await session.execute(
        text(
            """
            WITH noise AS (
                SELECT dataset.provider_dataset_id,
                       ROW_NUMBER() OVER (ORDER BY dataset.provider_dataset_id) AS rn
                FROM provider_sync.provider_datasets AS dataset
                WHERE dataset.provider = 'noise-request-provider'
            ), inserted AS (
                INSERT INTO ops.import_jobs (
                    kind, payload, status, trigger_kind, created_at,
                    dataset_membership_mode
                )
                SELECT 'feature_update_request', '{}'::jsonb, 'queued', 'update_request',
                       CAST(:created_at AS timestamptz), 'root'
                FROM noise
                RETURNING job_id
            ), numbered AS (
                SELECT job_id, ROW_NUMBER() OVER (ORDER BY job_id) AS rn FROM inserted
            ), requests AS (
                INSERT INTO ops.feature_update_requests (
                    scope_type, scope, run_mode, job_id, created_at,
                    dataset_membership_mode
                )
                SELECT
                    'feature_ids',
                    jsonb_build_object('type', 'feature_ids', 'feature_ids', '[]'::jsonb),
                    'queued', numbered.job_id, CAST(:created_at AS timestamptz), 'single'
                FROM numbered
                RETURNING request_id, job_id
            )
            INSERT INTO ops.feature_update_request_datasets (
                request_id, provider_dataset_id, sync_scope, operation_key
            )
            SELECT requests.request_id, noise.provider_dataset_id, 'dataset_wide',
                   :operation_key
            FROM requests
            JOIN numbered ON numbered.job_id = requests.job_id
            JOIN noise ON noise.rn = numbered.rn
            """
        ),
        {**noise_params, "created_at": _T0},
    )
    for relation in (
        "ops.import_jobs",
        "ops.import_job_events",
        "ops.feature_update_requests",
        "ops.import_job_datasets",
        "ops.feature_update_request_datasets",
        "provider_sync.provider_datasets",
    ):
        await session.execute(text(f"ANALYZE {relation}"))

    return {
        "event_only_job": event_only_job_id,
        "direct_request": direct_request_id,
        "membership_load_batch": membership_load_batch_id,
        "typed": typed,
        "direct": direct,
    }


async def test_selective_projection_plans_use_natural_bounded_access_paths(
    migrated_session: AsyncSession,
) -> None:
    targets = await _seed_selective_projection_cardinality(migrated_session)
    await migrated_session.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))
    cases = (
        (
            "typed-job-membership",
            targets["typed"].provider_dataset_id,
            "idx_import_job_datasets_exact_operation_job",
        ),
        (
            "direct-request-membership",
            targets["direct"].provider_dataset_id,
            "idx_feature_update_request_datasets_dataset_request",
        ),
    )
    for label, provider_dataset_id, expected_index in cases:
        params = {
            "kind": None,
            "status": None,
            "provider_dataset_id": provider_dataset_id,
            "filter_sync_scopes": False,
            "sync_scopes": [],
            "include_unscoped_scope": False,
            "load_batch_id": None,
            "parent_job_id": None,
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
        assert all(node.get("Relation Name") != "import_job_events" for node in _plan_nodes(plan))


async def test_membership_projection_plans_use_natural_bounded_access_paths(
    migrated_session: AsyncSession,
) -> None:
    targets = await _seed_selective_projection_cardinality(migrated_session)
    await migrated_session.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))
    cases = (
        (
            "load-batch-membership",
            targets["membership_load_batch"],
            None,
            "idx_import_jobs_load_batch_created",
        ),
        (
            "parent-membership",
            None,
            _JOB_ROOT,
            "idx_import_jobs_parent_created",
        ),
    )
    for label, load_batch_id, parent_job_id, expected_index in cases:
        plan = (
            await migrated_session.execute(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                    f"/* {label} */ {pipeline_repo._LIST_MEMBERSHIP_EXECUTIONS_SQL}"
                ),
                {
                    "kind": None,
                    "status": None,
                    "provider_dataset_id": None,
                    "filter_sync_scopes": False,
                    "sync_scopes": [],
                    "include_unscoped_scope": False,
                    "load_batch_id": load_batch_id,
                    "parent_job_id": parent_job_id,
                    "created_from": None,
                    "created_to": None,
                    "cursor_created_at": None,
                    "cursor_id": None,
                    "cursor_item_kind": None,
                    "page_limit": 51,
                },
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
    await migrated_session.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))
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


async def test_external_system_scope_run_history_cursor_pages_past_boundary(
    migrated_session: AsyncSession,
) -> None:
    """C7 cursor-overflow(구 live 51-req 루프)의 실질 계약을 seed로 검증한다.

    단일 KMA ``external_system`` scope에 page_size+1개 root를 넣으면 첫 페이지가
    non-null ``next_cursor``를 내고 둘째 페이지가 disjoint·정렬 연속으로 이어진다.
    같은 dataset의 다른 scope를 interleave해 scope 필터가 page-limit **이전**에
    적용됨(crowding-out 방지, #832 §C)도 함께 확인한다. 51회 실 KMA refresh를
    prod-live에서 돌릴 필요가 없다 — 이 계약이 그 게이트가 실제로 지키던 것.
    """
    provider = "python-kma-api"
    dataset_key = "kma_ultra_short_nowcast"
    sync_scope = "external_system:c7-overflow-contract"
    page_size = 50
    total = page_size + 1

    selected = await _member(
        migrated_session,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=sync_scope,
    )

    ids: list[str] = []
    for index in range(total):
        request_id = str(uuid5(_REQUEST_JOB_NAMESPACE, f"c7-overflow-{index}"))
        ids.append(request_id)
        await _request(
            migrated_session,
            request_id,
            job_id=None,
            created_at=_T0 + timedelta(minutes=index),
            member=selected,
            direct=True,
        )
        # 다음 동일-scope 요청을 만들기 전에 terminal로 보낸다 — active exact
        # triple 하나만 허용하는 membership mutex를 피한다(실제 overflow도 각
        # 요청을 done까지 몰고 다음을 만든다).
        owner = f"c7-overflow-run-{index}"
        started = await start_update_request(
            migrated_session, request_id, dagster_run_id=owner, expected_generation=1
        )
        assert started is not None
        finished = await finish_update_request(
            migrated_session,
            request_id,
            status="done",
            owner_dagster_run_id=owner,
            expected_generation=1,
        )
        assert finished is not None
        # 같은 dataset의 다른 scope를 사이사이 넣어, scope 필터가 page-limit 뒤에
        # 적용되면 첫 페이지가 밀려나도록(= 그러면 안 됨) 압박한다.
        other = await _member(
            migrated_session,
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=f"external_system:c7-other-{index}",
        )
        await _request(
            migrated_session,
            str(uuid5(_REQUEST_JOB_NAMESPACE, f"c7-other-{index}")),
            job_id=None,
            created_at=_T0 + timedelta(minutes=index, seconds=30),
            member=other,
            direct=True,
        )

    first = await list_pipeline_executions(
        migrated_session,
        provider_dataset_id=selected.provider_dataset_id,
        dataset_sync_scopes=(sync_scope,),
        limit=page_size,
    )
    assert len(first.items) == page_size
    assert first.next_cursor is not None

    second = await list_pipeline_executions(
        migrated_session,
        provider_dataset_id=selected.provider_dataset_id,
        dataset_sync_scopes=(sync_scope,),
        limit=page_size,
        cursor=first.next_cursor,
    )
    assert len(second.items) == 1
    assert second.next_cursor is None

    paged = [item.id for item in (*first.items, *second.items)]
    # created_at DESC 연속: 가장 최근(마지막 seed)부터 역순
    assert paged == list(reversed(ids))
    assert len(paged) == len(set(paged)) == total
    assert {item.id for item in first.items}.isdisjoint(
        {item.id for item in second.items}
    )


async def test_dataset_execution_snapshot_separates_operations_on_one_scope(
    migrated_session: AsyncSession,
) -> None:
    """같은 dataset+scope의 두 operation은 **각각의 snapshot**으로 나와야 한다.

    스키마는 한 dataset에 refresh operation을 여러 개 두는 것을 허용하고
    (``provider_dataset_operations`` PK는 ``(provider_dataset_id, operation_key)``),
    scope PK가 triple이라 그 둘이 같은 ``dataset_wide``를 함께 가질 수 있다 —
    실측으로 확인했다. 그러면 ``import_job_datasets``에 operation만 다른 두
    membership이 생긴다.

    SQL은 triple로 partition해 두 행을 정확히 내보내지만, 집계가 pair로 키를
    잡으면 두 번째 행이 첫 행과 충돌한다. 지금 그 조합이 없는 것은 seed된
    카탈로그가 dataset마다 refresh operation을 하나씩만 주기 때문일 뿐, 제약이
    막아 주는 것이 아니다.
    """
    provider = "data.go.kr-standard"
    dataset_key = "datagokr_museums"
    sync_scope = "dataset_wide"
    first = await _member(
        migrated_session,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=sync_scope,
        operation_key="feature_place_standard_museums_job",
    )
    second = await _member(
        migrated_session,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=sync_scope,
        operation_key="feature_place_standard_museums_job.backfill",
    )
    for index, (request_id, member) in enumerate(
        (
            ("a7777777-7777-4777-8777-777777777777", first),
            ("a8888888-8888-4888-8888-888888888888", second),
        )
    ):
        await _request(
            migrated_session,
            request_id,
            job_id=None,
            created_at=_T0 + timedelta(minutes=index),
            member=member,
            direct=True,
        )

    snapshots = await list_dataset_pipeline_execution_snapshots(migrated_session)
    matched = [
        item
        for item in snapshots
        if (item.provider, item.dataset_key, item.sync_scope)
        == (provider, dataset_key, sync_scope)
    ]

    assert len(matched) == 2, "operation별로 snapshot이 분리돼야 한다"
    assert {item.operation_key for item in matched} == {
        first.operation_key,
        second.operation_key,
    }
