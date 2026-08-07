"""``infra.dataset_status_repo`` (ADR-064 T-ADM-C2) 통합 테스트."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from sqlalchemy import text

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
    ImportJobDatasetTarget,
    enqueue_provider_dataset_import_job,
    record_import_job_event,
    start_unpaired_import_job,
)
from kortravelmap.infra.pipeline_repo import list_pipeline_executions

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _provider_dataset_id(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
) -> int:
    value = await session.scalar(
        text(
            "SELECT provider_dataset_id "
            "FROM provider_sync.provider_datasets "
            "WHERE provider = :provider AND dataset_key = :dataset_key"
        ),
        {"provider": provider, "dataset_key": dataset_key},
    )
    assert value is not None
    return int(value)


async def test_count_open_issues_groups_by_dataset_and_severity(
    migrated_session: AsyncSession,
) -> None:
    mois_dataset_id = await _provider_dataset_id(
        migrated_session,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
    )
    krex_dataset_id = await _provider_dataset_id(
        migrated_session,
        provider="python-krex-api",
        dataset_key="krex_rest_areas",
    )
    await create_data_integrity_violation(
        migrated_session,
        provider_dataset_id=mois_dataset_id,
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
    )
    await create_data_integrity_violation(
        migrated_session,
        provider_dataset_id=mois_dataset_id,
        violation_type="missing_address",
        severity="warning",
        message="주소 없음",
    )
    acknowledged = await create_data_integrity_violation(
        migrated_session,
        provider_dataset_id=mois_dataset_id,
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
        provider_dataset_id=mois_dataset_id,
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
        provider_dataset_id=krex_dataset_id,
        violation_type="missing_coordinate",
        severity="error",
        message="좌표 없음",
    )
    # provider_dataset_id 없는 전역 이슈는 dataset 집계에 임의 귀속하지 않는다.
    await create_data_integrity_violation(
        migrated_session,
        violation_type="orphan_source_link",
        severity="error",
        message="고아 source link",
    )
    await migrated_session.flush()

    counts = await count_open_integrity_issues_by_dataset(migrated_session)
    by_dataset_id = {row.provider_dataset_id: row for row in counts}
    assert set(by_dataset_id) == {mois_dataset_id, krex_dataset_id}
    mois = by_dataset_id[mois_dataset_id]
    assert (mois.provider, mois.dataset_key) == (
        "python-mois-api",
        "mois_license_features_bulk",
    )
    assert mois.open_total == 3  # open 2 + acknowledged 1
    assert mois.by_severity == {"error": 1, "warning": 2}
    krex = by_dataset_id[krex_dataset_id]
    assert krex.open_total == 1
    assert krex.by_severity == {"error": 1}

    # canonical dataset ID 필터 — 상세 화면 단건 조회 경로.
    filtered = await count_open_integrity_issues_by_dataset(
        migrated_session,
        provider_dataset_id=mois_dataset_id,
    )
    assert [row.provider_dataset_id for row in filtered] == [mois_dataset_id]
    assert filtered[0].open_total == 3

    missing = await count_open_integrity_issues_by_dataset(
        migrated_session,
        provider_dataset_id=999_999,
    )
    assert missing == ()


_KMA_PROVIDER = "python-kma-api"
_KMA_DATASET = "kma_ultra_short_nowcast"
_KMA_OPERATION = "feature_weather_kma_ultra_short_nowcast_job"


async def test_latest_dataset_execution_collapses_linked_request_job_root(
    migrated_session: AsyncSession,
) -> None:
    """T-VN-33: dataset latest는 exact triple 단위다.

    scope 사본(job.sync_scope)이 사라졌으므로 두 root를 분리하려면 같은 dataset의
    **다른 catalog sync_scope**를 쓴다(unscoped ``None`` scope는 더 이상 없다).
    """
    dataset_id = await _provider_dataset_id(
        migrated_session, provider=_KMA_PROVIDER, dataset_key=_KMA_DATASET
    )
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "provider_dataset",
            "provider_dataset_id": dataset_id,
            "sync_scope": "dataset_wide",
            "operation_key": _KMA_OPERATION,
        },
        dataset_memberships=[
            ImportJobDatasetTarget(
                provider_dataset_id=dataset_id,
                sync_scope="dataset_wide",
                operation_key=_KMA_OPERATION,
            )
        ],
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    # 자유 payload의 request_id는 lineage를 만들지 않는다(root_id/root_kind가 정본).
    await start_unpaired_import_job(
        migrated_session,
        kind="payload_linked_job",
        payload={"request_id": request.request_id},
    )
    await migrated_session.flush()

    linked_only = await list_latest_dataset_executions(migrated_session)
    linked_root = next(
        item
        for item in linked_only
        if (item.provider_dataset_id, item.sync_scope) == (dataset_id, "dataset_wide")
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
        dataset_membership=ImportJobDatasetTarget(
            provider_dataset_id=dataset_id,
            sync_scope="target_grids",
            operation_key=_KMA_OPERATION,
        ),
        trigger_kind="manual",
    )
    await record_import_job_event(
        migrated_session,
        independent.job_id,
        import_job_dataset_id=independent.dataset_memberships[0].import_job_dataset_id,
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
    by_scope = {
        (item.provider, item.dataset_key, item.sync_scope): item for item in latest
    }
    assert len(latest) == len(by_scope)

    request_scope = by_scope[(_KMA_PROVIDER, _KMA_DATASET, "dataset_wide")]
    assert request_scope.execution.kind == "update_request"
    assert request_scope.execution.id == request.request_id

    job = by_scope[(_KMA_PROVIDER, _KMA_DATASET, "target_grids")]
    assert job.execution.kind == "import_job"
    assert job.execution.id == independent.job_id
    assert job.execution.trigger_kind == "manual"
    timeline = await list_pipeline_executions(
        migrated_session, provider_dataset_id=dataset_id
    )
    assert job.execution.id == timeline.items[0].id
    assert job.execution.status == timeline.items[0].status
    assert job.execution.projected_job == timeline.items[0].projected_job

    # scope가 다르면 created_at 동률이어도 dataset latest는 각각의 root를 보존한다.
    # 전체 pipeline 목록은 이 fixture에서 created_at/id 순서를 적용한다. 동일 UUID의
    # kind 최종 tie-break는 test_cursor_kind_breaks_same_timestamp_and_uuid_tie가 맡는다.
    await migrated_session.execute(
        text(
            "UPDATE ops.import_jobs SET created_at = :created_at "
            "WHERE job_id = CAST(:job_id AS uuid)"
        ),
        {"job_id": independent.job_id, "created_at": request.created_at},
    )
    tied = await list_latest_dataset_executions(migrated_session)
    tied_by_scope = {
        (item.provider, item.dataset_key, item.sync_scope): item for item in tied
    }
    assert len(tied) == len(tied_by_scope)
    assert (
        tied_by_scope[(_KMA_PROVIDER, _KMA_DATASET, "dataset_wide")].execution.id
        == request.request_id
    )
    assert (
        tied_by_scope[(_KMA_PROVIDER, _KMA_DATASET, "target_grids")].execution.id
        == independent.job_id
    )

    tied_timeline = await list_pipeline_executions(
        migrated_session, provider_dataset_id=dataset_id
    )
    expected_id = max(UUID(request.request_id), UUID(independent.job_id))
    assert UUID(tied_timeline.items[0].id) == expected_id
