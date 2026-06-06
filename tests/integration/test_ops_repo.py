"""ADR-045 T-207d 운영 조회 repository 통합 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.infra.consistency import run_consistency_checks
from krtour.map.infra.integrity_violation_repo import create_data_integrity_violation
from krtour.map.infra.jobs_repo import enqueue_import_job, start_import_job
from krtour.map.infra.ops_repo import (
    get_latest_consistency_report,
    get_ops_import_job,
    get_ops_integrity_issue_counts,
    list_ops_consistency_reports,
    list_ops_import_jobs,
    list_ops_integrity_issues,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))


async def test_ops_import_jobs_list_detail_and_cursor(
    migrated_session: AsyncSession,
) -> None:
    batch_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    root_job = await start_import_job(
        migrated_session,
        kind="full_load_batch",
        payload={"mode": "full"},
        load_batch_id=batch_id,
    )
    old_job = await enqueue_import_job(
        migrated_session,
        kind="feature_update_request",
        payload={"request_id": "old"},
        load_batch_id=batch_id,
        parent_job_id=root_job.job_id,
    )
    new_job = await start_import_job(
        migrated_session,
        kind="feature_update_request",
        payload={"request_id": "new"},
        load_batch_id=batch_id,
        parent_job_id=root_job.job_id,
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
        kind="feature_update_request",
        load_batch_id=batch_id,
        parent_job_id=root_job.job_id,
        limit=1,
    )
    assert [item.job_id for item in page1.items] == [new_job.job_id]
    assert page1.next_cursor is not None

    page2 = await list_ops_import_jobs(
        migrated_session,
        kind="feature_update_request",
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
            WHERE violation_key = :violation_key
            """
        ),
        {
            "violation_key": first.violation_key,
            "detected_at": datetime(2026, 6, 3, 10, 0, tzinfo=_KST),
        },
    )
    await migrated_session.execute(
        text(
            """
            UPDATE ops.data_integrity_violations
            SET detected_at = :detected_at
            WHERE violation_key = :violation_key
            """
        ),
        {
            "violation_key": second.violation_key,
            "detected_at": datetime(2026, 6, 3, 11, 0, tzinfo=_KST),
        },
    )
    await migrated_session.flush()

    page1 = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        limit=1,
    )
    assert [item.violation_key for item in page1.items] == [second.violation_key]
    assert page1.next_cursor is not None

    page2 = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        limit=1,
        cursor=page1.next_cursor,
    )
    assert [item.violation_key for item in page2.items] == [first.violation_key]

    counts = await get_ops_integrity_issue_counts(migrated_session)
    assert counts.open_total == 2
    assert counts.by_status == {"open": 2}
    assert counts.by_severity == {"error": 1, "warning": 1}
    assert counts.by_type == {"missing_address": 1, "missing_coordinate": 1}


async def test_ops_integrity_issues_q_and_bbox_filters(
    migrated_session: AsyncSession,
) -> None:
    from geoalchemy2 import WKTElement

    from krtour.map.infra.models import FeatureRow

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
    keys = {item.violation_key for item in seoul.items}
    assert in_bbox.violation_key in keys
    assert no_feature.violation_key not in keys

    # bbox: 다른 지역(부산) → 매칭 없음.
    busan = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        bbox=(129.0, 35.0, 129.2, 35.2),
    )
    assert in_bbox.violation_key not in {item.violation_key for item in busan.items}

    # q: message 부분일치.
    matched = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        q="불일치",
    )
    assert {item.violation_key for item in matched.items} == {in_bbox.violation_key}

    # q: feature_id 부분일치.
    by_fid = await list_ops_integrity_issues(
        migrated_session,
        provider="python-mois-api",
        q="issue_bbox",
    )
    assert by_fid.items
    assert all(item.feature_id == fid for item in by_fid.items)
