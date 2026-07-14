"""``infra.dataset_status_repo`` (ADR-064 T-ADM-C2) 통합 테스트."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kortravelmap.infra.dataset_status_repo import (
    count_open_integrity_issues_by_dataset,
    list_ops_import_jobs_by_ids,
)
from kortravelmap.infra.integrity_violation_repo import (
    create_data_integrity_violation,
    set_data_integrity_violation_status,
)
from kortravelmap.infra.jobs_repo import enqueue_import_job, start_import_job

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_count_open_issues_groups_by_dataset_and_severity(
    migrated_session: AsyncSession,
) -> None:
    await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
    )
    await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        violation_type="missing_address",
        severity="warning",
        message="주소 없음",
    )
    acknowledged = await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        violation_type="missing_address",
        severity="warning",
        message="주소 없음 (확인됨)",
    )
    await set_data_integrity_violation_status(
        migrated_session, acknowledged.issue_id, status="acknowledged"
    )
    # 해결된 이슈는 집계에서 빠진다.
    resolved = await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        violation_type="missing_address",
        severity="warning",
        message="주소 없음 (해결됨)",
    )
    await set_data_integrity_violation_status(
        migrated_session, resolved.issue_id, status="resolved"
    )
    # 다른 dataset은 별도 행으로 집계된다.
    await create_data_integrity_violation(
        migrated_session,
        provider="python-krex-api",
        dataset_key="krex_rest_areas",
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
    )
    # provider 없는 전역 이슈는 dataset 집계에서 제외한다.
    await create_data_integrity_violation(
        migrated_session,
        violation_type="orphan_source_link",
        severity="error",
        message="고아 source link",
    )
    await migrated_session.flush()

    counts = await count_open_integrity_issues_by_dataset(migrated_session)
    by_key = {(row.provider, row.dataset_key): row for row in counts}
    assert set(by_key) == {
        ("python-mois-api", "mois_license_features_bulk"),
        ("python-krex-api", "krex_rest_areas"),
    }
    mois = by_key[("python-mois-api", "mois_license_features_bulk")]
    assert mois.open_total == 3  # open 2 + acknowledged 1
    assert mois.by_severity == {"error": 1, "warning": 2}
    krex = by_key[("python-krex-api", "krex_rest_areas")]
    assert krex.open_total == 1
    assert krex.by_severity == {"error": 1}

    # provider/dataset 필터 — 상세 화면 단건 조회 경로.
    filtered = await count_open_integrity_issues_by_dataset(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    )
    assert len(filtered) == 1
    assert filtered[0].open_total == 3

    missing = await count_open_integrity_issues_by_dataset(
        migrated_session,
        provider="python-mois-api",
        dataset_key="no_such_dataset",
    )
    assert missing == ()


async def test_list_ops_import_jobs_by_ids_roundtrip(
    migrated_session: AsyncSession,
) -> None:
    queued = await enqueue_import_job(
        migrated_session,
        kind="feature_update_request",
        payload={"request_id": "req-queued"},
    )
    running = await start_import_job(
        migrated_session,
        kind="feature_update_request",
        payload={"request_id": "req-running"},
    )
    await migrated_session.flush()

    jobs = await list_ops_import_jobs_by_ids(
        migrated_session,
        [
            queued.job_id,
            running.job_id,
            # 존재하지 않는 id는 조용히 빠진다.
            "99999999-9999-9999-9999-999999999999",
        ],
    )
    by_id = {job.job_id: job for job in jobs}
    assert set(by_id) == {queued.job_id, running.job_id}
    assert by_id[queued.job_id].status == "queued"
    assert by_id[queued.job_id].payload == {"request_id": "req-queued"}
    assert by_id[queued.job_id].created_at is not None
    assert by_id[running.job_id].status == "running"
    assert by_id[running.job_id].started_at is not None

    assert await list_ops_import_jobs_by_ids(migrated_session, []) == ()
