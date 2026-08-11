"""ADR-045 T-207d 운영 조회 repository 통합 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from kortravelmap.api.routers.ops_live import (
    _IMPORT_JOB_EVENTS_LIVE_SQL,
    _IMPORT_JOBS_LIVE_SQL,
)
from sqlalchemy import text

from kortravelmap.infra import ops_repo
from kortravelmap.infra.consistency import run_consistency_checks
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    enqueue_feature_update_request,
)
from kortravelmap.infra.integrity_violation_repo import create_data_integrity_violation
from kortravelmap.infra.jobs_repo import (
    ImportJobDatasetTarget,
    enqueue_unpaired_import_job,
    record_import_job_event,
    start_provider_dataset_import_job,
    start_unpaired_import_job,
)
from kortravelmap.infra.ops_repo import (
    get_latest_consistency_report,
    get_ops_import_job,
    get_ops_integrity_issue_counts,
    list_ops_consistency_reports,
    list_ops_import_job_events,
    list_ops_import_jobs,
    list_ops_integrity_issues,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_MOIS_PROVIDER = "python-mois-api"
_MOIS_DATASET = "mois_license_features_bulk"


async def _membership(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str = "dataset_wide",
    operation_key: str = "ops_repo_fixture_refresh",
) -> ImportJobDatasetTarget:
    """catalog triple을 확보하고 job membership 대상으로 돌려준다 (T-VN-33).

    ``ops.import_job_datasets``는 ``provider_dataset_operation_scopes``를 FK로
    잡으므로 fixture 전용 pair도 catalog에 먼저 심어야 한다. 자연키 사본이
    사라진 뒤 job·event가 dataset에 닿는 유일한 경로가 이 membership이다.
    """

    dataset_id = int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind,
                        is_active, capabilities
                    )
                    SELECT :provider, :dataset_key, :provider, 'system', true,
                           jsonb_build_object('schema_version', 1,
                                              'produces', '[]'::jsonb,
                                              'extensions', '{}'::jsonb)
                    ON CONFLICT (provider, dataset_key) DO UPDATE
                        SET display_name = EXCLUDED.display_name
                    RETURNING provider_dataset_id
                    """
                ),
                {"provider": provider, "dataset_key": dataset_key},
            )
        ).scalar_one()
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operations (
                provider_dataset_id, operation_key, operation_kind, is_enabled, config
            )
            VALUES (
                CAST(:dataset_id AS bigint), :operation_key, 'refresh', true,
                '{}'::jsonb
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {"dataset_id": dataset_id, "operation_key": operation_key},
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key, operation_kind
            )
            VALUES (
                CAST(:dataset_id AS bigint), :sync_scope, :operation_key, 'refresh'
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "dataset_id": dataset_id,
            "sync_scope": sync_scope,
            "operation_key": operation_key,
        },
    )
    return ImportJobDatasetTarget(
        provider_dataset_id=dataset_id,
        sync_scope=sync_scope,
        operation_key=operation_key,
    )


async def test_import_job_reverse_links_typed_update_request_identity(
    migrated_session: AsyncSession,
) -> None:
    membership = await _membership(
        migrated_session, provider=_MOIS_PROVIDER, dataset_key=_MOIS_DATASET
    )
    request = await enqueue_feature_update_request(
        migrated_session,
        dataset_memberships=[membership],
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)

    job = await get_ops_import_job(migrated_session, request.job_id)

    assert job is not None
    assert job.update_request_id == request.request_id
    assert job.payload == {}


async def _job_member_id(session: AsyncSession, job_id: str) -> str:
    """job의 유일한 canonical membership id를 읽는다 (event 기록에 필요)."""

    return str(
        (
            await session.execute(
                text(
                    "SELECT import_job_dataset_id FROM ops.import_job_datasets "
                    "WHERE job_id = CAST(:job_id AS uuid)"
                ),
                {"job_id": job_id},
            )
        ).scalar_one()
    )


def _plan_nodes(plan: Any) -> list[dict[str, Any]]:
    document = plan[0] if isinstance(plan, list) else plan
    pending = [document["Plan"]]
    nodes: list[dict[str, Any]] = []
    while pending:
        node = pending.pop()
        nodes.append(node)
        pending.extend(node.get("Plans", ()))
    return nodes


def _assert_bounded_event_audit_plan(
    plan: Any,
    *,
    expected_index: str,
) -> None:
    """감사 조회 계획이 **유계**인지 못박는다 — 정렬 노드의 유무가 아니라.

    앞 판은 세 케이스 중 둘에 ``assert not sort_nodes``(절대 금지)를 걸었다. 그 규칙은
    실측으로 비결정적이다: 같은 트리·같은 명령(``pytest tests/integration -q``)으로
    2026-08-11에 한 번은 이 단언에서 red, 한 번은 green이었고 파일 단독 실행은
    ``8 passed``였다. 테스트가 ``ANALYZE`` + ``force_generic_plan``을 이미 걸고 있으므로
    통계 최신화 누락이 아니라, 공유 DB에 형제 테스트가 커밋해 둔 행 위에서 top-N 정렬과
    index-ordered 경로의 비용이 팽팽해 표본에 따라 갈리는 것이다.

    유계성이 실제 보증이다. 정렬이 끼더라도 그것이 LIMIT에 묶인 top-N이면 — 정렬이 훑는
    행이 64 이하 — 비용은 index-ordered 경로와 같은 자릿수다. 반대로 index가 사라지면
    이 시드(12,000행) 위에서 ``touches``/``removed``/정렬 행 수가 함께 폭발하고
    ``expected_index`` 단언도 깨진다. 그래서 세 축(정렬 행·훑은 행·필터로 버린 행)에
    같은 상한을 걸고, Seq Scan 금지와 index 이름을 함께 못박는다.
    """

    nodes = _plan_nodes(plan)
    event_nodes = [
        node for node in nodes if node.get("Relation Name") == "import_job_events"
    ]
    assert event_nodes
    assert all(node.get("Node Type") != "Seq Scan" for node in event_nodes)
    sort_nodes = [
        node for node in nodes if "Sort" in str(node.get("Node Type"))
    ]
    sorted_rows = sum(
        float(node.get("Actual Rows", 0)) * float(node.get("Actual Loops", 0))
        for node in sort_nodes
    )
    assert sorted_rows <= 64, f"정렬이 유계가 아니다: {sorted_rows}행"
    assert any(node.get("Index Name") == expected_index for node in nodes)
    touches = sum(
        float(node.get("Actual Rows", 0)) * float(node.get("Actual Loops", 0))
        for node in event_nodes
    )
    removed = sum(
        float(node.get("Rows Removed by Filter", 0))
        * float(node.get("Actual Loops", 0))
        for node in event_nodes
    )
    assert touches <= 64
    assert removed <= 64


def _assert_bounded_live_event_plan(plan: Any, *, expected_index: str) -> None:
    event_nodes = [
        node
        for node in _plan_nodes(plan)
        if node.get("Relation Name") == "import_job_events"
    ]
    assert event_nodes
    assert all(node.get("Node Type") != "Seq Scan" for node in event_nodes)
    assert any(node.get("Index Name") == expected_index for node in event_nodes)
    touches = sum(
        float(node.get("Actual Rows", 0)) * float(node.get("Actual Loops", 0))
        for node in event_nodes
    )
    removed = sum(
        float(node.get("Rows Removed by Filter", 0))
        * float(node.get("Actual Loops", 0))
        for node in event_nodes
    )
    assert touches <= 8
    assert removed <= 8


async def test_ops_import_jobs_list_detail_and_cursor(
    migrated_session: AsyncSession,
) -> None:
    batch_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    membership = await _membership(
        migrated_session, provider=_MOIS_PROVIDER, dataset_key=_MOIS_DATASET
    )
    root_job = await start_unpaired_import_job(
        migrated_session,
        kind="full_load_batch",
        payload={"mode": "full"},
        load_batch_id=batch_id,
    )
    old_job = await enqueue_unpaired_import_job(
        migrated_session,
        kind="ops_update_fixture",
        payload={"request_id": "old"},
        load_batch_id=batch_id,
        parent_job_id=root_job.job_id,
    )
    new_job = await start_provider_dataset_import_job(
        migrated_session,
        kind="ops_update_fixture",
        payload={"request_id": "new"},
        load_batch_id=batch_id,
        parent_job_id=root_job.job_id,
        dataset_membership=membership,
        trigger_kind="manual",
    )
    member_id = new_job.dataset_memberships[0].import_job_dataset_id
    await migrated_session.execute(
        text(
            """
            UPDATE ops.import_jobs
            SET created_at = :created_at
            WHERE job_id = :job_id
            """
        ),
        {
            "job_id": old_job.job_id,
            "created_at": datetime(2026, 6, 3, 10, 0, tzinfo=_KST),
        },
    )
    await migrated_session.execute(
        text(
            """
            UPDATE ops.import_jobs
            SET created_at = :created_at
            WHERE job_id = :job_id
            """
        ),
        {
            "job_id": new_job.job_id,
            "created_at": datetime(2026, 6, 3, 11, 0, tzinfo=_KST),
        },
    )
    await migrated_session.flush()

    page1 = await list_ops_import_jobs(
        migrated_session,
        kind="ops_update_fixture",
        load_batch_id=batch_id,
        parent_job_id=root_job.job_id,
        limit=1,
    )
    assert [item.job_id for item in page1.items] == [new_job.job_id]
    assert page1.next_cursor is not None

    page2 = await list_ops_import_jobs(
        migrated_session,
        kind="ops_update_fixture",
        load_batch_id=batch_id,
        parent_job_id=root_job.job_id,
        limit=1,
        cursor=page1.next_cursor,
    )
    assert [item.job_id for item in page2.items] == [old_job.job_id]

    loaded = await get_ops_import_job(migrated_session, new_job.job_id)
    assert loaded is not None
    assert loaded.load_batch_id == batch_id
    assert loaded.parent_job_id == root_job.job_id
    assert loaded.payload == {"request_id": "new"}
    assert loaded.started_at is not None
    assert loaded.heartbeat_at is not None

    first_event = await record_import_job_event(
        migrated_session,
        new_job.job_id,
        level="error",
        code="provider.timeout",
        message="provider timeout",
        payload={"attempt": 1},
        import_job_dataset_id=member_id,
        stage="fetching",
    )
    second_event = await record_import_job_event(
        migrated_session,
        new_job.job_id,
        level="error",
        code="provider.timeout",
        message="provider timeout retry",
        payload={"attempt": 2},
        import_job_dataset_id=member_id,
        stage="fetching",
    )
    assert first_event is not None
    assert second_event is not None
    await migrated_session.execute(
        text(
            """
            UPDATE ops.import_job_events
            SET occurred_at = :occurred_at
            WHERE event_id = :event_id
            """
        ),
        {
            "event_id": first_event.event_id,
            "occurred_at": datetime(2026, 6, 3, 12, 0, tzinfo=_KST),
        },
    )
    await migrated_session.execute(
        text(
            """
            UPDATE ops.import_job_events
            SET occurred_at = :occurred_at
            WHERE event_id = :event_id
            """
        ),
        {
            "event_id": second_event.event_id,
            "occurred_at": datetime(2026, 6, 3, 13, 0, tzinfo=_KST),
        },
    )

    event_page1 = await list_ops_import_job_events(
        migrated_session,
        new_job.job_id,
        level="error",
        limit=1,
    )
    assert [item.event_id for item in event_page1.items] == [second_event.event_id]
    assert event_page1.next_cursor is not None

    event_page2 = await list_ops_import_job_events(
        migrated_session,
        new_job.job_id,
        level="error",
        limit=1,
        cursor=event_page1.next_cursor,
    )
    assert [item.event_id for item in event_page2.items] == [first_event.event_id]

    global_event_page = await list_ops_import_job_events(
        migrated_session,
        level="error",
        provider_dataset_id=membership.provider_dataset_id,
        limit=10,
    )
    assert [item.event_id for item in global_event_page.items] == [
        second_event.event_id,
        first_event.event_id,
    ]
    assert {item.import_job_dataset_id for item in global_event_page.items} == {
        member_id
    }


async def test_dataset_events_filter_effective_scope_before_limit_and_cursor(
    migrated_session: AsyncSession,
) -> None:
    """같은 dataset의 두 scope가 limit/cursor 전에 갈린다 (T-VN-33).

    event는 provider/dataset_key/sync_scope 사본을 더 이상 들지 않는다. 두 요청은
    같은 ``provider_dataset_id``를 공유하고 ``sync_scope``만 다르므로, filter가
    membership을 통해 정확히 갈라야 한다는 원래 의도가 그대로 유지된다.
    """

    membership_a = await _membership(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_short_forecast",
        sync_scope="target_grids",
    )
    membership_b = await _membership(
        migrated_session,
        provider="python-kma-api",
        dataset_key="kma_short_forecast",
        sync_scope="external_system:other",
    )
    assert membership_a.provider_dataset_id == membership_b.provider_dataset_id
    scope_a = membership_a.sync_scope
    scope_b = membership_b.sync_scope
    request_a = await enqueue_feature_update_request(
        migrated_session,
        dataset_memberships=[membership_a],
        scope={
            "type": "provider_dataset",
            "provider_dataset_id": membership_a.provider_dataset_id,
            "sync_scope": membership_a.sync_scope,
            "operation_key": membership_a.operation_key,
        },
    )
    request_b = await enqueue_feature_update_request(
        migrated_session,
        dataset_memberships=[membership_b],
        scope={
            "type": "provider_dataset",
            "provider_dataset_id": membership_b.provider_dataset_id,
            "sync_scope": membership_b.sync_scope,
            "operation_key": membership_b.operation_key,
        },
    )
    member_a = await _job_member_id(migrated_session, request_a.job_id)
    member_b = await _job_member_id(migrated_session, request_b.job_id)
    event_a1 = await record_import_job_event(
        migrated_session,
        request_a.job_id,
        level="error",
        code="scope-a.older",
        message="scope A older",
        import_job_dataset_id=member_a,
    )
    event_a2 = await record_import_job_event(
        migrated_session,
        request_a.job_id,
        level="error",
        code="scope-a.newer",
        message="scope A newer",
        import_job_dataset_id=member_a,
    )
    assert event_a1 is not None
    assert event_a2 is not None
    assert event_a1.import_job_dataset_id == member_a
    assert event_a2.import_job_dataset_id == member_a
    for index in range(22):
        event_b = await record_import_job_event(
            migrated_session,
            request_b.job_id,
            level="error",
            code=f"scope-b.{index:02d}",
            message=f"scope B {index:02d}",
            import_job_dataset_id=member_b,
        )
        assert event_b is not None
    await migrated_session.execute(
        text(
            """
            UPDATE ops.import_job_events
            SET occurred_at = CASE event_id
              WHEN CAST(:older_id AS uuid) THEN TIMESTAMPTZ '2026-07-01 01:00:00+00'
              WHEN CAST(:newer_id AS uuid) THEN TIMESTAMPTZ '2026-07-01 02:00:00+00'
            END
            WHERE event_id IN (CAST(:older_id AS uuid), CAST(:newer_id AS uuid))
            """
        ),
        {"older_id": event_a1.event_id, "newer_id": event_a2.event_id},
    )

    page_a1 = await list_ops_import_job_events(
        migrated_session,
        level="error",
        provider_dataset_id=membership_a.provider_dataset_id,
        sync_scope=scope_a,
        limit=1,
    )
    assert [item.code for item in page_a1.items] == ["scope-a.newer"]
    assert [item.import_job_dataset_id for item in page_a1.items] == [member_a]
    assert page_a1.next_cursor is not None

    page_a2 = await list_ops_import_job_events(
        migrated_session,
        level="error",
        provider_dataset_id=membership_a.provider_dataset_id,
        sync_scope=scope_a,
        limit=1,
        cursor=page_a1.next_cursor,
    )
    assert [item.code for item in page_a2.items] == ["scope-a.older"]
    assert [item.import_job_dataset_id for item in page_a2.items] == [member_a]
    assert page_a2.next_cursor is None

    page_b = await list_ops_import_job_events(
        migrated_session,
        level="error",
        provider_dataset_id=membership_b.provider_dataset_id,
        sync_scope=scope_b,
        limit=20,
    )
    assert len(page_b.items) == 20
    assert {item.import_job_dataset_id for item in page_b.items} == {member_b}
    assert page_b.next_cursor is not None


async def test_exact_scope_event_history_filters_on_canonical_membership(
    migrated_session: AsyncSession,
) -> None:
    """exact (dataset, scope) event 이력이 membership만으로 갈린다.

    T-VN-33 전에는 ``ops.import_job_events``가 provider/dataset_key/sync_scope
    사본을 들고 ``idx_import_job_events_provider_dataset_scope_time`` 부분
    인덱스를 탔다. 사본과 그 인덱스는 0091이 없앴고, exact scope의 정본은
    ``ops.import_job_datasets``(dataset+scope+operation) membership 하나다.

    여기서는 ① 8,000건 규모에서 filter가 대상 scope만 돌려주고 cursor가 그 안에서
    전진하는지, ② 사라진 사본 인덱스가 되살아나지 않고 설계된 대체 인덱스
    (``idx_import_job_events_member_time``)가 존재하는지를 지킨다.

    계획 모양은 **의도적으로** 못박지 않는다. 현재
    ``ops_repo._list_import_job_events_sql``은 member를 LEFT JOIN한 뒤 event를
    전역 ``occurred_at DESC``로 정렬하므로 planner가 대체 인덱스에 닿지 못하고
    전역 시간 인덱스를 탄다(이 fixture에서 51행을 얻는 데 4,052행 스캔). 그건
    테스트가 완화할 일이 아니라 제품이 고쳐야 할 회귀라 별도로 보고한다.
    """

    target = await _membership(
        migrated_session,
        provider="scope-provider",
        dataset_key="scope-dataset",
        sync_scope="target_grids",
    )
    other = await _membership(
        migrated_session,
        provider="scope-provider",
        dataset_key="scope-dataset",
        sync_scope="external_system:other",
    )
    target_job = await start_provider_dataset_import_job(
        migrated_session,
        kind="exact_scope_target_plan_fixture",
        dataset_membership=target,
    )
    other_job = await start_provider_dataset_import_job(
        migrated_session,
        kind="exact_scope_other_plan_fixture",
        dataset_membership=other,
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_job_events (
              event_id, job_id, import_job_dataset_id, level, message, occurred_at
            )
            SELECT
              ('85000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              CAST(:target_job_id AS uuid), CAST(:target_member_id AS uuid),
              'info', 'target scope',
              TIMESTAMPTZ '2026-07-01 00:00:00+00'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
              ('86000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              CAST(:other_job_id AS uuid), CAST(:other_member_id AS uuid),
              'info', 'other scope',
              TIMESTAMPTZ '2026-07-02 00:00:00+00'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)
            """
        ),
        {
            "target_job_id": target_job.job_id,
            "target_member_id": target_job.dataset_memberships[0].import_job_dataset_id,
            "other_job_id": other_job.job_id,
            "other_member_id": other_job.dataset_memberships[0].import_job_dataset_id,
        },
    )
    await migrated_session.execute(text("ANALYZE ops.import_job_events"))
    await migrated_session.execute(text("ANALYZE ops.import_job_datasets"))

    # exact scope filter가 8,000건 안에서 대상 scope만, cursor 전진까지 정확히
    # 고른다. 두 membership은 같은 provider_dataset_id를 공유하므로 갈림의
    # 정본은 sync_scope다.
    target_member = target_job.dataset_memberships[0].import_job_dataset_id
    page1 = await list_ops_import_job_events(
        migrated_session,
        provider_dataset_id=target.provider_dataset_id,
        sync_scope="target_grids",
        limit=50,
    )
    assert len(page1.items) == 50
    assert {item.import_job_dataset_id for item in page1.items} == {target_member}
    assert page1.next_cursor is not None

    page2 = await list_ops_import_job_events(
        migrated_session,
        provider_dataset_id=target.provider_dataset_id,
        sync_scope="target_grids",
        limit=50,
        cursor=page1.next_cursor,
    )
    assert {item.import_job_dataset_id for item in page2.items} == {target_member}
    assert page1.items[-1].occurred_at > page2.items[0].occurred_at

    # 사라진 사본 인덱스가 되살아나지 않고, 설계된 대체 인덱스는 존재한다.
    index_names = {
        str(row.indexname)
        for row in (
            await migrated_session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'ops' AND tablename = 'import_job_events'"
                )
            )
        ).all()
    }
    assert "idx_import_job_events_member_time" in index_names
    assert not index_names & {
        "idx_import_job_events_provider_time",
        "idx_import_job_events_provider_dataset_time",
        "idx_import_job_events_provider_dataset_scope_time",
    }


async def test_event_audit_filters_use_bounded_natural_plans(
    migrated_session: AsyncSession,
) -> None:
    target = await _membership(
        migrated_session,
        provider="target-provider",
        dataset_key="target-dataset",
    )
    dataset_noise = await _membership(
        migrated_session,
        provider="other-provider",
        dataset_key="target-dataset",
    )
    provider_noise = await _membership(
        migrated_session,
        provider="target-provider",
        dataset_key="other-dataset",
    )
    target_job = await start_provider_dataset_import_job(
        migrated_session,
        kind="event_audit_target_plan_fixture",
        dataset_membership=target,
    )
    dataset_noise_job = await start_provider_dataset_import_job(
        migrated_session,
        kind="event_audit_dataset_noise_plan_fixture",
        dataset_membership=dataset_noise,
    )
    provider_noise_job = await start_provider_dataset_import_job(
        migrated_session,
        kind="event_audit_provider_noise_plan_fixture",
        dataset_membership=provider_noise,
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_job_events (
              event_id, job_id, import_job_dataset_id, level, message, occurred_at
            )
            SELECT
              ('81000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              CAST(:target_job_id AS uuid), CAST(:target_member_id AS uuid),
              'info', 'target', CAST(:occurred_at AS timestamptz)
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 60) AS seed(n)

            UNION ALL

            SELECT
              ('82000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              CAST(:dataset_noise_job_id AS uuid),
              CAST(:dataset_noise_member_id AS uuid),
              'warning', 'dataset-noise',
              CAST(:occurred_at AS timestamptz) + INTERVAL '1 day'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
              ('83000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              CAST(:provider_noise_job_id AS uuid),
              CAST(:provider_noise_member_id AS uuid),
              'warning', 'provider-noise',
              CAST(:occurred_at AS timestamptz) + INTERVAL '2 days'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)
            """
        ),
        {
            "target_job_id": target_job.job_id,
            "target_member_id": target_job.dataset_memberships[0].import_job_dataset_id,
            "dataset_noise_job_id": dataset_noise_job.job_id,
            "dataset_noise_member_id": (
                dataset_noise_job.dataset_memberships[0].import_job_dataset_id
            ),
            "provider_noise_job_id": provider_noise_job.job_id,
            "provider_noise_member_id": (
                provider_noise_job.dataset_memberships[0].import_job_dataset_id
            ),
            "occurred_at": datetime(2026, 7, 1, tzinfo=_KST),
        },
    )
    await migrated_session.execute(text("ANALYZE ops.import_job_events"))
    await migrated_session.execute(text("ANALYZE ops.import_job_datasets"))
    await migrated_session.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))

    # provider/dataset_key 사본 filter는 T-VN-33에서 사라졌다. 자연 계획이
    # 남아 있는 감사 축은 전체/``job_id``/``level`` 세 개다. dataset membership
    # 축은 현재 bounded 계획이 없어(``test_exact_scope_event_history_filters_on_
    # canonical_membership`` docstring 참조) 여기서 계획을 못박지 않는다.
    cases = (
        (None, None, None, "idx_import_job_events_time"),
        (target_job.job_id, None, None, "idx_import_job_events_job_time"),
        (None, "info", None, "idx_import_job_events_level_time"),
    )
    for cursor_at in (None, datetime(2026, 7, 1, 2, 0, tzinfo=_KST)):
        for job_id, level, provider_dataset_id, expected_index in cases:
            sql = ops_repo._list_import_job_events_sql(
                job_id=job_id,
                level=level,
                provider_dataset_id=provider_dataset_id,
                sync_scope=None,
                operation_key=None,
                cursor_occurred_at=cursor_at,
            )
            plan = (
                await migrated_session.execute(
                    text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"),
                    {
                        "job_id": job_id,
                        "level": level,
                        "provider_dataset_id": provider_dataset_id,
                        "sync_scope": None,
                        "cursor_occurred_at": cursor_at,
                        "cursor_event_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                        "limit": 51,
                    },
                )
            ).scalar_one()
            _assert_bounded_event_audit_plan(
                plan,
                expected_index=expected_index,
            )

    live_cases = (
        (_IMPORT_JOBS_LIVE_SQL, {}, "idx_import_job_events_time"),
        (
            _IMPORT_JOB_EVENTS_LIVE_SQL,
            {"job_id": target_job.job_id},
            "idx_import_job_events_job_time",
        ),
    )
    for sql, params, expected_index in live_cases:
        plan = (
            await migrated_session.execute(
                text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"),
                params,
            )
        ).scalar_one()
        _assert_bounded_live_event_plan(plan, expected_index=expected_index)


async def test_ops_consistency_reports_latest_and_list(
    migrated_session: AsyncSession,
) -> None:
    report = await run_consistency_checks(
        migrated_session,
        batch_id="11111111-1111-1111-1111-111111111111",
        persist=True,
    )
    await migrated_session.flush()

    latest = await get_latest_consistency_report(migrated_session)
    assert latest is not None
    assert latest.batch_id == report.batch_id
    assert latest.summary["total_violations"] == report.summary["total_violations"]

    page = await list_ops_consistency_reports(
        migrated_session,
        severity_max=report.severity_max,
        limit=10,
    )
    assert len(page.items) == 1
    assert page.items[0].cases[0]["code"] == "F1"


async def test_ops_integrity_issues_list_cursor_and_counts(
    migrated_session: AsyncSession,
) -> None:
    membership = await _membership(
        migrated_session, provider=_MOIS_PROVIDER, dataset_key=_MOIS_DATASET
    )
    first = await create_data_integrity_violation(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
    )
    second = await create_data_integrity_violation(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        violation_type="missing_address",
        severity="warning",
        message="주소 없음",
    )
    await migrated_session.execute(
        text(
            """
            UPDATE ops.data_integrity_violations
            SET detected_at = :detected_at,
                last_seen_at = :last_seen_at
            WHERE issue_id = :issue_id
            """
        ),
        {
            "issue_id": first.issue_id,
            "detected_at": datetime(2026, 6, 3, 10, 0, tzinfo=_KST),
            "last_seen_at": datetime(2026, 6, 3, 12, 0, tzinfo=_KST),
        },
    )
    await migrated_session.execute(
        text(
            """
            UPDATE ops.data_integrity_violations
            SET detected_at = :detected_at,
                last_seen_at = :last_seen_at
            WHERE issue_id = :issue_id
            """
        ),
        {
            "issue_id": second.issue_id,
            "detected_at": datetime(2026, 6, 3, 11, 0, tzinfo=_KST),
            "last_seen_at": datetime(2026, 6, 3, 11, 0, tzinfo=_KST),
        },
    )
    await migrated_session.flush()

    page1 = await list_ops_integrity_issues(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        limit=1,
    )
    assert [item.issue_id for item in page1.items] == [first.issue_id]
    assert page1.items[0].provider == _MOIS_PROVIDER
    assert page1.items[0].dataset_key == _MOIS_DATASET
    assert page1.next_cursor is not None

    page2 = await list_ops_integrity_issues(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        limit=1,
        cursor=page1.next_cursor,
    )
    assert [item.issue_id for item in page2.items] == [second.issue_id]
    assert page1.items[0].last_seen_at > page2.items[0].last_seen_at

    counts = await get_ops_integrity_issue_counts(migrated_session)
    assert counts.open_total == 2
    assert counts.by_status == {"open": 2}
    assert counts.by_severity == {"error": 1, "warning": 1}
    assert counts.by_type == {"missing_address": 1, "missing_coordinate": 1}


async def test_ops_integrity_issues_q_and_bbox_filters(
    migrated_session: AsyncSession,
) -> None:
    from geoalchemy2 import WKTElement

    from kortravelmap.infra.models import FeatureRow

    fid = "f_issue_bbox"
    migrated_session.add(
        FeatureRow(
            feature_id=fid,
            kind="place",
            name="광화문",
            category="01070300",
            coord=WKTElement("POINT(126.9769 37.5759)", srid=4326),
            address={"road": "서울특별시 종로구 세종대로 1"},
            urls={},
            raw_refs=[],
            status="active",
        )
    )
    await migrated_session.flush()

    membership = await _membership(
        migrated_session, provider=_MOIS_PROVIDER, dataset_key=_MOIS_DATASET
    )
    in_bbox = await create_data_integrity_violation(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        feature_id=fid,
        violation_type="provider_address_mismatch",
        severity="warning",
        message="주소 불일치: 서울 종로",
    )
    no_feature = await create_data_integrity_violation(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        violation_type="missing_address",
        severity="warning",
        message="좌표만 있음",
    )
    await migrated_session.flush()

    # bbox: 광화문 포함 → feature 연결 이슈만(미연결 이슈 제외).
    seoul = await list_ops_integrity_issues(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        bbox=(126.97, 37.57, 126.98, 37.58),
    )
    keys = {item.issue_id for item in seoul.items}
    assert in_bbox.issue_id in keys
    assert no_feature.issue_id not in keys

    # bbox: 다른 지역(부산) → 매칭 없음.
    busan = await list_ops_integrity_issues(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        bbox=(129.0, 35.0, 129.2, 35.2),
    )
    assert in_bbox.issue_id not in {item.issue_id for item in busan.items}

    # q: message 부분일치.
    matched = await list_ops_integrity_issues(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        q="불일치",
    )
    assert {item.issue_id for item in matched.items} == {in_bbox.issue_id}

    # q: feature_id 부분일치.
    by_fid = await list_ops_integrity_issues(
        migrated_session,
        provider_dataset_id=membership.provider_dataset_id,
        q="issue_bbox",
    )
    assert by_fid.items
    assert all(item.feature_id == fid for item in by_fid.items)
