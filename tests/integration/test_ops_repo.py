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

from kortravelmap.core.feature_operation import ProviderDatasetOperationKey
from kortravelmap.infra import ops_repo
from kortravelmap.infra.consistency import run_consistency_checks
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    enqueue_feature_update_request,
)
from kortravelmap.infra.integrity_violation_repo import create_data_integrity_violation
from kortravelmap.infra.jobs_repo import (
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


async def test_import_job_reverse_links_typed_update_request_identity(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)

    job = await get_ops_import_job(migrated_session, request.job_id)

    assert job is not None
    assert job.update_request_id == request.request_id
    assert job.payload == {}


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
    allow_bounded_sort: bool = False,
) -> None:
    nodes = _plan_nodes(plan)
    event_nodes = [
        node for node in nodes if node.get("Relation Name") == "import_job_events"
    ]
    assert event_nodes
    assert all(node.get("Node Type") != "Seq Scan" for node in event_nodes)
    sort_nodes = [
        node for node in nodes if "Sort" in str(node.get("Node Type"))
    ]
    if allow_bounded_sort:
        assert sum(
            float(node.get("Actual Rows", 0)) * float(node.get("Actual Loops", 0))
            for node in sort_nodes
        ) <= 64
    else:
        assert not sort_nodes
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
        provider_dataset=ProviderDatasetOperationKey(
            "python-mois-api", "mois_license_features_bulk"
        ),
        trigger_kind="manual",
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
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        stage="fetching",
    )
    second_event = await record_import_job_event(
        migrated_session,
        new_job.job_id,
        level="error",
        code="provider.timeout",
        message="provider timeout retry",
        payload={"attempt": 2},
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
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
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        limit=10,
    )
    assert [item.event_id for item in global_event_page.items] == [
        second_event.event_id,
        first_event.event_id,
    ]


async def test_dataset_events_filter_effective_scope_before_limit_and_cursor(
    migrated_session: AsyncSession,
) -> None:
    provider = "python-kma-api"
    dataset_key = "kma_short_forecast"
    scope_a = "target_grids"
    scope_b = "external_system:other"
    request_a = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "provider_dataset",
            "provider": provider,
            "dataset_key": dataset_key,
            "sync_scope": scope_a,
        },
        effective_sync_scope=scope_a,
    )
    request_b = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "provider_dataset",
            "provider": provider,
            "dataset_key": dataset_key,
            "sync_scope": scope_b,
        },
        effective_sync_scope=scope_b,
    )
    event_a1 = await record_import_job_event(
        migrated_session,
        request_a.job_id,
        level="error",
        code="scope-a.older",
        message="scope A older",
    )
    event_a2 = await record_import_job_event(
        migrated_session,
        request_a.job_id,
        level="error",
        code="scope-a.newer",
        message="scope A newer",
    )
    assert event_a1 is not None
    assert event_a2 is not None
    assert event_a1.sync_scope == scope_a
    assert event_a2.sync_scope == scope_a
    for index in range(22):
        event_b = await record_import_job_event(
            migrated_session,
            request_b.job_id,
            level="error",
            code=f"scope-b.{index:02d}",
            message=f"scope B {index:02d}",
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
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=scope_a,
        limit=1,
    )
    assert [item.code for item in page_a1.items] == ["scope-a.newer"]
    assert [item.sync_scope for item in page_a1.items] == [scope_a]
    assert page_a1.next_cursor is not None

    page_a2 = await list_ops_import_job_events(
        migrated_session,
        level="error",
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=scope_a,
        limit=1,
        cursor=page_a1.next_cursor,
    )
    assert [item.code for item in page_a2.items] == ["scope-a.older"]
    assert [item.sync_scope for item in page_a2.items] == [scope_a]
    assert page_a2.next_cursor is None

    page_b = await list_ops_import_job_events(
        migrated_session,
        level="error",
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=scope_b,
        limit=20,
    )
    assert len(page_b.items) == 20
    assert {item.sync_scope for item in page_b.items} == {scope_b}
    assert page_b.next_cursor is not None


async def test_exact_scope_event_history_uses_bounded_partial_index(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_jobs (
              job_id, kind, payload, status, provider, dataset_key,
              sync_scope, trigger_kind
            ) VALUES
            ('84000000-0000-4000-8000-000000000001',
             'feature_update_request', '{}'::jsonb, 'done',
             'scope-provider', 'scope-dataset', 'target_grids',
             'update_request'),
            ('84000000-0000-4000-8000-000000000002',
             'feature_update_request', '{}'::jsonb, 'done',
             'scope-provider', 'scope-dataset', 'external_system:other',
             'update_request')
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_update_requests (
              request_id, scope_type, scope, run_mode, job_id
            ) VALUES
            ('84000000-0000-4000-8000-000000000011',
             'provider_dataset',
             '{"type":"provider_dataset","provider":"scope-provider",'
             '"dataset_key":"scope-dataset",'
             '"sync_scope":"target_grids"}'::jsonb,
             'queued', '84000000-0000-4000-8000-000000000001'),
            ('84000000-0000-4000-8000-000000000012',
             'provider_dataset',
             '{"type":"provider_dataset","provider":"scope-provider",'
             '"dataset_key":"scope-dataset",'
             '"sync_scope":"external_system:other"}'::jsonb,
             'queued', '84000000-0000-4000-8000-000000000002')
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_job_events (
              event_id, job_id, level, message, occurred_at
            )
            SELECT
              ('85000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              '84000000-0000-4000-8000-000000000001'::uuid,
              'info', 'target scope',
              TIMESTAMPTZ '2026-07-01 00:00:00+00'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
              ('86000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              '84000000-0000-4000-8000-000000000002'::uuid,
              'info', 'other scope',
              TIMESTAMPTZ '2026-07-02 00:00:00+00'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)
            """
        )
    )
    await migrated_session.execute(text("ANALYZE ops.import_job_events"))
    await migrated_session.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))

    for cursor_at in (None, datetime(2026, 7, 1, 9, 30, tzinfo=_KST)):
        sql = ops_repo._list_import_job_events_sql(
            job_id=None,
            level=None,
            provider="scope-provider",
            dataset_key="scope-dataset",
            sync_scope="target_grids",
            cursor_occurred_at=cursor_at,
        )
        plan = (
            await migrated_session.execute(
                text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"),
                {
                    "job_id": None,
                    "level": None,
                    "provider": "scope-provider",
                    "dataset_key": "scope-dataset",
                    "sync_scope": "target_grids",
                    "cursor_occurred_at": cursor_at,
                    "cursor_event_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                    "limit": 51,
                },
            )
        ).scalar_one()
        _assert_bounded_event_audit_plan(
            plan,
            expected_index="idx_import_job_events_provider_dataset_scope_time",
        )


async def test_event_audit_filters_use_bounded_natural_plans(
    migrated_session: AsyncSession,
) -> None:
    target_job = await start_provider_dataset_import_job(
        migrated_session,
        kind="event_audit_target_plan_fixture",
        provider_dataset=ProviderDatasetOperationKey(
            "target-provider",
            "target-dataset",
        ),
    )
    dataset_noise_job = await start_provider_dataset_import_job(
        migrated_session,
        kind="event_audit_dataset_noise_plan_fixture",
        provider_dataset=ProviderDatasetOperationKey(
            "other-provider",
            "target-dataset",
        ),
    )
    provider_noise_job = await start_provider_dataset_import_job(
        migrated_session,
        kind="event_audit_provider_noise_plan_fixture",
        provider_dataset=ProviderDatasetOperationKey(
            "target-provider",
            "other-dataset",
        ),
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.import_job_events (
              event_id, job_id, provider, dataset_key, level, message, occurred_at
            )
            SELECT
              ('81000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              CAST(:target_job_id AS uuid), 'target-provider', 'target-dataset',
              'info', 'target', CAST(:occurred_at AS timestamptz)
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 60) AS seed(n)

            UNION ALL

            SELECT
              ('82000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              CAST(:dataset_noise_job_id AS uuid), 'other-provider',
              'target-dataset', 'warning', 'dataset-noise',
              CAST(:occurred_at AS timestamptz) + INTERVAL '1 day'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
              ('83000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              CAST(:provider_noise_job_id AS uuid), 'target-provider',
              'other-dataset', 'warning', 'provider-noise',
              CAST(:occurred_at AS timestamptz) + INTERVAL '2 days'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)
            """
        ),
        {
            "target_job_id": target_job.job_id,
            "dataset_noise_job_id": dataset_noise_job.job_id,
            "provider_noise_job_id": provider_noise_job.job_id,
            "occurred_at": datetime(2026, 7, 1, tzinfo=_KST),
        },
    )
    await migrated_session.execute(text("ANALYZE ops.import_job_events"))
    await migrated_session.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))

    cases = (
        (None, None, None, None, "idx_import_job_events_time"),
        (
            target_job.job_id,
            None,
            None,
            None,
            "idx_import_job_events_job_time",
        ),
        (None, "info", None, None, "idx_import_job_events_level_time"),
        (
            None,
            None,
            "target-provider",
            None,
            "idx_import_job_events_provider_time",
        ),
        (
            None,
            None,
            "target-provider",
            "target-dataset",
            "idx_import_job_events_provider_dataset_time",
        ),
    )
    for cursor_at in (None, datetime(2026, 7, 1, 2, 0, tzinfo=_KST)):
        for job_id, level, provider, dataset_key, expected_index in cases:
            sql = ops_repo._list_import_job_events_sql(
                job_id=job_id,
                level=level,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=None,
                cursor_occurred_at=cursor_at,
            )
            plan = (
                await migrated_session.execute(
                    text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"),
                    {
                        "job_id": job_id,
                        "level": level,
                        "provider": provider,
                        "dataset_key": dataset_key,
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
                allow_bounded_sort=(
                    expected_index == "idx_import_job_events_job_time"
                ),
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
    first = await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
    )
    second = await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
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
        provider="python-mois-api",
        limit=1,
    )
    assert [item.issue_id for item in page1.items] == [first.issue_id]
    assert page1.next_cursor is not None

    page2 = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
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
            detail={},
            urls={},
            raw_refs=[],
            status="active",
        )
    )
    await migrated_session.flush()

    in_bbox = await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        feature_id=fid,
        violation_type="provider_address_mismatch",
        severity="warning",
        message="주소 불일치: 서울 종로",
    )
    no_feature = await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        violation_type="missing_address",
        severity="warning",
        message="좌표만 있음",
    )
    await migrated_session.flush()

    # bbox: 광화문 포함 → feature 연결 이슈만(미연결 이슈 제외).
    seoul = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        bbox=(126.97, 37.57, 126.98, 37.58),
    )
    keys = {item.issue_id for item in seoul.items}
    assert in_bbox.issue_id in keys
    assert no_feature.issue_id not in keys

    # bbox: 다른 지역(부산) → 매칭 없음.
    busan = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        bbox=(129.0, 35.0, 129.2, 35.2),
    )
    assert in_bbox.issue_id not in {item.issue_id for item in busan.items}

    # q: message 부분일치.
    matched = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        q="불일치",
    )
    assert {item.issue_id for item in matched.items} == {in_bbox.issue_id}

    # q: feature_id 부분일치.
    by_fid = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        q="issue_bbox",
    )
    assert by_fid.items
    assert all(item.feature_id == fid for item in by_fid.items)
