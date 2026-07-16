"""``infra.dataset_status_repo`` (ADR-064 T-ADM-C2) 통합 테스트."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from sqlalchemy import text

from kortravelmap.core.feature_operation import ProviderDatasetOperationKey
from kortravelmap.infra.dataset_status_repo import (
    count_open_integrity_issues_by_dataset,
    list_latest_dataset_executions,
)
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    enqueue_feature_update_request,
)
from kortravelmap.infra.integrity_violation_repo import (
    create_data_integrity_violation,
    set_data_integrity_violation_status,
)
from kortravelmap.infra.jobs_repo import (
    enqueue_provider_dataset_import_job,
    record_import_job_event,
    start_unpaired_import_job,
)
from kortravelmap.infra.pipeline_repo import list_pipeline_executions

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
    # provider 단위 이슈는 dataset 이슈와 분리된 행으로 유지한다.
    await create_data_integrity_violation(
        migrated_session,
        provider="python-mois-api",
        violation_type="provider_contract_drift",
        severity="warning",
        message="provider 계약 drift",
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
        ("python-mois-api", None),
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
    filtered_by_key = {row.dataset_key: row for row in filtered}
    assert set(filtered_by_key) == {"mois_license_features_bulk", None}
    assert filtered_by_key["mois_license_features_bulk"].open_total == 3
    assert filtered_by_key[None].open_total == 1

    missing = await count_open_integrity_issues_by_dataset(
        migrated_session,
        provider="python-mois-api",
        dataset_key="no_such_dataset",
    )
    assert len(missing) == 1
    assert missing[0].dataset_key is None
    assert missing[0].open_total == 1


async def test_latest_dataset_execution_collapses_linked_request_job_root(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "provider_dataset",
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
        },
        effective_sync_scope="dataset_wide",
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    await start_unpaired_import_job(
        migrated_session,
        kind="payload_linked_job",
        payload={
            "request_id": request.request_id,
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
        },
    )
    await migrated_session.flush()

    linked_only = await list_latest_dataset_executions(migrated_session)
    linked_root = next(
        item
        for item in linked_only
        if (item.provider, item.dataset_key)
        == ("python-mois-api", "mois_license_features_bulk")
    )
    assert linked_root.execution.kind == "update_request"
    assert linked_root.execution.id == request.request_id
    assert linked_root.execution.projected_job.id == request.job_id
    assert linked_root.pair_status == "queued"

    # 자유 payload의 request_id가 UUID가 아니어도 projection이 cast 때문에 깨지지 않는다.
    independent = await enqueue_provider_dataset_import_job(
        migrated_session,
        kind="manual_provider_sync",
        payload={"request_id": "not-a-uuid"},
        provider_dataset=ProviderDatasetOperationKey(
            "python-mois-api", "mois_license_features_bulk"
        ),
        trigger_kind="manual",
    )
    await record_import_job_event(
        migrated_session,
        independent.job_id,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        message="independent import event",
    )
    # transaction_timestamp() 동률을 피하고 실제 created_at 최신 root 선택을 검증한다.
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET created_at = :created_at "
            "WHERE job_id = CAST(:job_id AS uuid)"
        ),
        {
            "job_id": independent.job_id,
            "created_at": request.created_at + timedelta(minutes=1),
        },
    )
    await migrated_session.flush()

    latest = await list_latest_dataset_executions(migrated_session)
    by_key = {(item.provider, item.dataset_key): item for item in latest}

    job = by_key[("python-mois-api", "mois_license_features_bulk")]
    assert job.execution.kind == "import_job"
    assert job.execution.id == independent.job_id
    assert job.execution.trigger_kind == "manual"
    timeline = await list_pipeline_executions(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    )
    assert job.execution.id == timeline.items[0].id
    assert job.execution.status == timeline.items[0].status
    assert job.execution.projected_job == timeline.items[0].projected_job

    # created_at 동률에서는 canonical root id/kind total order를 그대로 쓴다.
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET created_at = :created_at "
            "WHERE job_id = CAST(:job_id AS uuid)"
        ),
        {"job_id": independent.job_id, "created_at": request.created_at},
    )
    tied = await list_latest_dataset_executions(migrated_session)
    tied_root = next(
        item
        for item in tied
        if (item.provider, item.dataset_key)
        == ("python-mois-api", "mois_license_features_bulk")
    )
    expected_id = max(UUID(request.request_id), UUID(independent.job_id))
    assert UUID(tied_root.execution.id) == expected_id
