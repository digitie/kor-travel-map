"""파이프라인 실행 타임라인 UNION 조회 통합 테스트 (ADR-064 T-ADM-C3).

``ops.import_jobs`` ∪ ``ops.feature_update_requests`` 공유 keyset cursor의
경계(동일 created_at tie-break)·중복/구멍 없음·필터를 실 PostGIS DB로 검증한다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra.pipeline_repo import (
    get_pipeline_status_counts,
    list_pipeline_executions,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_J1 = "11111111-1111-1111-1111-111111111111"  # queued kma job (t1)
_R1 = "22222222-2222-2222-2222-222222222222"  # queued kma request (t2)
_R2 = "44444444-4444-4444-4444-444444444444"  # failed opinet request (t3, tie)
_J3 = "55555555-5555-5555-5555-555555555555"  # failed old job (t0)
_J2 = "99999999-9999-4999-8999-999999999999"  # failed opinet job (t3, tie)

_T0 = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)
_T2 = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)
_T3 = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)

_INSERT_JOB_SQL = text(
    """
    INSERT INTO ops.import_jobs (
        job_id, kind, payload, status, created_at, finished_at, dagster_run_id
    ) VALUES (
        CAST(:job_id AS uuid), :kind, CAST(:payload AS jsonb), :status,
        :created_at,
        CASE WHEN CAST(:finished_hours_ago AS integer) IS NOT NULL
             THEN now() - make_interval(hours => CAST(:finished_hours_ago AS integer))
             ELSE NULL END,
        :dagster_run_id
    )
    """
)

_INSERT_REQUEST_SQL = text(
    """
    INSERT INTO ops.feature_update_requests (
        request_id, scope_type, scope, providers, dataset_keys, update_policy,
        run_mode, priority, status, dry_run, matched_scope, operator,
        created_at, finished_at
    ) VALUES (
        CAST(:request_id AS uuid), :scope_type, CAST(:scope AS jsonb),
        CAST(:providers AS jsonb), '[]'::jsonb, '{}'::jsonb,
        'queued', :priority, :status, false, '{}'::jsonb, :operator,
        :created_at,
        CASE WHEN CAST(:finished_hours_ago AS integer) IS NOT NULL
             THEN now() - make_interval(hours => CAST(:finished_hours_ago AS integer))
             ELSE NULL END
    )
    """
)


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        _INSERT_JOB_SQL,
        {
            "job_id": _J1,
            "kind": "provider_load",
            "payload": json.dumps(
                {
                    "provider": "python-kma-api",
                    "dataset_key": "kma_short_forecast",
                }
            ),
            "status": "queued",
            "created_at": _T1,
            "finished_hours_ago": None,
            "dagster_run_id": None,
        },
    )
    await session.execute(
        _INSERT_JOB_SQL,
        {
            "job_id": _J2,
            "kind": "provider_load",
            "payload": json.dumps({"provider": "python-opinet-api"}),
            "status": "failed",
            "created_at": _T3,
            "finished_hours_ago": 2,
            "dagster_run_id": "run-j2",
        },
    )
    await session.execute(
        _INSERT_JOB_SQL,
        {
            "job_id": _J3,
            "kind": "provider_load",
            "payload": json.dumps({"provider": "python-kma-api"}),
            "status": "failed",
            "created_at": _T0,
            "finished_hours_ago": 72,
            "dagster_run_id": None,
        },
    )
    await session.execute(
        _INSERT_REQUEST_SQL,
        {
            "request_id": _R1,
            "scope_type": "provider_dataset",
            "scope": json.dumps(
                {
                    "type": "provider_dataset",
                    "provider": "python-kma-api",
                    "dataset_key": "kma_short_forecast",
                }
            ),
            "providers": "[]",
            "priority": 50,
            "status": "queued",
            "operator": "tester",
            "created_at": _T2,
            "finished_hours_ago": None,
        },
    )
    await session.execute(
        _INSERT_REQUEST_SQL,
        {
            "request_id": _R2,
            "scope_type": "feature_ids",
            "scope": json.dumps({"type": "feature_ids", "feature_ids": ["f-1"]}),
            "providers": json.dumps(["python-opinet-api"]),
            "priority": 80,
            "status": "failed",
            "operator": "tester",
            "created_at": _T3,
            "finished_hours_ago": 1,
        },
    )


async def test_union_ordering_and_keyset_pagination(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)

    collected: list[tuple[str, str]] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = await list_pipeline_executions(
            migrated_session, limit=1, cursor=cursor
        )
        pages += 1
        collected.extend((item.kind, item.id) for item in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
        assert pages < 10, "cursor가 전진하지 않는다"

    # created_at DESC + 동일 created_at(t3)의 id DESC tie-break: J2 → R2.
    assert collected == [
        ("import_job", _J2),
        ("update_request", _R2),
        ("update_request", _R1),
        ("import_job", _J1),
        ("import_job", _J3),
    ]
    # 페이지 경계 중복/구멍 없음.
    assert len(collected) == len(set(collected))

    # 큰 페이지 1회 조회와 결과가 동일해야 한다 (경계 안정성).
    single = await list_pipeline_executions(migrated_session, limit=50)
    assert [(item.kind, item.id) for item in single.items] == collected
    assert single.next_cursor is None


async def test_union_row_field_mapping(migrated_session: AsyncSession) -> None:
    await _seed(migrated_session)

    page = await list_pipeline_executions(migrated_session, limit=2)

    job_row = page.items[0]
    assert job_row.kind == "import_job"
    assert job_row.job_kind == "provider_load"
    assert job_row.provider == "python-opinet-api"
    assert job_row.dagster_run_id == "run-j2"
    assert job_row.priority is None
    request_row = page.items[1]
    assert request_row.kind == "update_request"
    assert request_row.scope_type == "feature_ids"
    assert request_row.provider == "python-opinet-api"
    assert request_row.priority == 80
    assert request_row.operator == "tester"
    assert request_row.progress is None


async def test_kind_filter_limits_branches(migrated_session: AsyncSession) -> None:
    await _seed(migrated_session)

    jobs = await list_pipeline_executions(migrated_session, kind="import_job")
    requests = await list_pipeline_executions(
        migrated_session, kind="update_request"
    )

    assert [item.id for item in jobs.items] == [_J2, _J1, _J3]
    assert all(item.kind == "import_job" for item in jobs.items)
    assert [item.id for item in requests.items] == [_R2, _R1]
    assert all(item.kind == "update_request" for item in requests.items)


async def test_status_and_time_filters(migrated_session: AsyncSession) -> None:
    await _seed(migrated_session)

    failed = await list_pipeline_executions(migrated_session, status="failed")
    assert [item.id for item in failed.items] == [_J2, _R2, _J3]

    recent = await list_pipeline_executions(migrated_session, created_from=_T2)
    assert [item.id for item in recent.items] == [_J2, _R2, _R1]

    older = await list_pipeline_executions(migrated_session, created_to=_T2)
    assert [item.id for item in older.items] == [_R1, _J1, _J3]


async def test_provider_filter_covers_payload_scope_and_array(
    migrated_session: AsyncSession,
) -> None:
    await _seed(migrated_session)

    opinet = await list_pipeline_executions(
        migrated_session, provider="python-opinet-api"
    )
    # import job payload->>provider + update request providers 배열 매칭.
    assert [item.id for item in opinet.items] == [_J2, _R2]

    kma = await list_pipeline_executions(migrated_session, provider="python-kma-api")
    # provider_dataset scope의 provider 매칭 포함.
    assert [item.id for item in kma.items] == [_R1, _J1, _J3]


async def test_status_counts_for_overview(migrated_session: AsyncSession) -> None:
    await _seed(migrated_session)

    counts = await get_pipeline_status_counts(migrated_session)

    assert counts.import_jobs_by_status == {"queued": 1, "failed": 2}
    assert counts.update_requests_by_status == {"queued": 1, "failed": 1}
    # 24h 창: J2(2h 전)만 포함, J3(72h 전)는 제외.
    assert counts.failed_import_jobs_24h == 1
    assert counts.failed_update_requests_24h == 1
