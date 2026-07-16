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


def _assert_bounded_event_audit_plan(plan: Any, *, expected_index: str) -> None:
    nodes = _plan_nodes(plan)
    event_nodes = [
        node for node in nodes if node.get("Relation Name") == "import_job_events"
    ]
    assert event_nodes
    assert all(node.get("Node Type") != "Seq Scan" for node in event_nodes)
    assert not any("Sort" in str(node.get("Node Type")) for node in nodes)
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


async def test_event_audit_filters_use_bounded_natural_plans(
    migrated_session: AsyncSession,
) -> None:
    target_job = await start_unpaired_import_job(
        migrated_session,
        kind="event_audit_target_plan_fixture",
    )
    noise_job = await start_unpaired_import_job(
        migrated_session,
        kind="event_audit_noise_plan_fixture",
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
              CAST(:noise_job_id AS uuid), 'other-provider-' || seed.n::text,
              'target-dataset', 'warning', 'dataset-noise',
              CAST(:occurred_at AS timestamptz) + INTERVAL '1 day'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)

            UNION ALL

            SELECT
              ('83000000-0000-4000-8000-' || lpad(seed.n::text, 12, '0'))::uuid,
              CAST(:noise_job_id AS uuid), 'target-provider',
              'other-dataset-' || seed.n::text, 'warning', 'provider-noise',
              CAST(:occurred_at AS timestamptz) + INTERVAL '2 days'
                + seed.n * INTERVAL '1 second'
            FROM generate_series(1, 4000) AS seed(n)
            """
        ),
        {
            "target_job_id": target_job.job_id,
            "noise_job_id": noise_job.job_id,
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
            None,
            "target-dataset",
            "idx_import_job_events_dataset_time",
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
                        "cursor_occurred_at": cursor_at,
                        "cursor_event_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                        "limit": 51,
                    },
                )
            ).scalar_one()
            _assert_bounded_event_audit_plan(plan, expected_index=expected_index)

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
            SET detected_at = :detected_at
            WHERE issue_id = :issue_id
            """
        ),
        {
            "issue_id": first.issue_id,
            "detected_at": datetime(2026, 6, 3, 10, 0, tzinfo=_KST),
        },
    )
    await migrated_session.execute(
        text(
            """
            UPDATE ops.data_integrity_violations
            SET detected_at = :detected_at
            WHERE issue_id = :issue_id
            """
        ),
        {
            "issue_id": second.issue_id,
            "detected_at": datetime(2026, 6, 3, 11, 0, tzinfo=_KST),
        },
    )
    await migrated_session.flush()

    page1 = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        limit=1,
    )
    assert [item.issue_id for item in page1.items] == [second.issue_id]
    assert page1.next_cursor is not None

    page2 = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        limit=1,
        cursor=page1.next_cursor,
    )
    assert [item.issue_id for item in page2.items] == [first.issue_id]

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
