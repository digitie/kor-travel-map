"""``feature_update_repo`` — feature update request lifecycle (ADR-045 T-206b).

검증 범위:
- dry-run은 scope만 해석하고 DB row/import job을 만들지 않는다.
- enqueue는 ``ops.feature_update_requests``와 ``ops.import_jobs``를 같은 transaction에
  생성한다.
- claim/start/finish/cancel은 request와 연결 import job 상태를 함께 갱신한다.
- 목록은 D-10 keyset cursor로 중복 없이 페이지를 넘긴다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from krtour.map.infra.advisory_lock import advisory_lock
from krtour.map.infra.feature_update_repo import (
    FEATURE_UPDATE_JOB_KIND,
    FEATURE_UPDATE_QUEUE_ADVISORY_KEY,
    FeatureUpdateLockBusy,
    FeatureUpdateQueueLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestPreview,
    cancel_update_request,
    claim_next_update_request,
    enqueue_feature_update_request,
    feature_update_scope_advisory_key,
    finish_update_request,
    get_update_request,
    list_update_requests,
    peek_next_update_request,
    peek_update_requests,
    start_update_request,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


async def _count_rows(session: AsyncSession, table: str) -> int:
    return int(
        (
            await session.execute(text(f"SELECT count(*) FROM {table}"))
        ).scalar_one()
    )


async def _job_row(session: AsyncSession, job_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                SELECT kind, payload, status, progress, current_stage, error_message
                FROM ops.import_jobs
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id},
        )
    ).mappings().one()
    return dict(row)


async def test_dry_run_returns_preview_without_writes(
    migrated_session: AsyncSession,
) -> None:
    preview = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-mois-api"],
        dry_run=True,
        operator="local-admin",
    )

    assert isinstance(preview, FeatureUpdateRequestPreview)
    assert preview.scope_type == "feature_ids"
    assert preview.providers == ("python-mois-api",)
    assert preview.matched_scope == {"feature_count": 0, "sigungu_codes": []}
    assert await _count_rows(migrated_session, "ops.feature_update_requests") == 0
    assert await _count_rows(migrated_session, "ops.import_jobs") == 0


async def test_enqueue_creates_request_and_import_job(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-mois-api"],
        dataset_keys=["mois_license_features_bulk"],
        update_policy={"mode": "refresh_existing"},
        priority=80,
        operator="local-admin",
        reason="test queue",
    )

    assert isinstance(request, FeatureUpdateRequest)
    assert request.status == "queued"
    assert request.priority == 80
    assert request.job_id is not None
    assert request.matched_scope == {"feature_count": 0, "sigungu_codes": []}

    job = await _job_row(migrated_session, request.job_id)
    payload = _json_obj(job["payload"])
    assert job["kind"] == FEATURE_UPDATE_JOB_KIND
    assert job["status"] == "queued"
    assert payload["request_id"] == request.request_id
    assert payload["scope_type"] == "feature_ids"
    assert payload["providers"] == ["python-mois-api"]


async def test_claim_uses_priority_and_starts_linked_job(
    migrated_session: AsyncSession,
) -> None:
    low = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        priority=10,
    )
    high = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        priority=90,
    )
    assert isinstance(low, FeatureUpdateRequest)
    assert isinstance(high, FeatureUpdateRequest)

    claimed = await claim_next_update_request(migrated_session)
    assert claimed is not None
    assert claimed.request_id == high.request_id
    assert claimed.status == "running"
    assert claimed.job_id is not None
    assert (await _job_row(migrated_session, claimed.job_id))["status"] == "running"
    assert (
        await _job_row(migrated_session, claimed.job_id)
    )["current_stage"] == "claimed"

    claimed_next = await claim_next_update_request(migrated_session)
    assert claimed_next is not None
    assert claimed_next.request_id == low.request_id
    assert await claim_next_update_request(migrated_session) is None


async def test_peek_next_update_request_does_not_claim(
    migrated_session: AsyncSession,
) -> None:
    low = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        priority=10,
    )
    high = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        priority=90,
    )
    assert isinstance(low, FeatureUpdateRequest)
    assert isinstance(high, FeatureUpdateRequest)

    peeked = await peek_next_update_request(migrated_session)
    assert peeked is not None
    assert peeked.request_id == high.request_id
    assert peeked.status == "queued"
    assert peeked.job_id is not None
    assert (await _job_row(migrated_session, peeked.job_id))["status"] == "queued"

    peeked_batch = await peek_update_requests(migrated_session, limit=2)
    assert [item.request_id for item in peeked_batch] == [
        high.request_id,
        low.request_id,
    ]
    assert all(item.status == "queued" for item in peeked_batch)

    claimed = await claim_next_update_request(migrated_session)
    assert claimed is not None
    assert claimed.request_id == high.request_id


async def test_claim_raises_when_queue_lock_is_held(
    migrated_engine: AsyncEngine,
    migrated_session: AsyncSession,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as holder,
        holder.begin(),
        advisory_lock(holder, FEATURE_UPDATE_QUEUE_ADVISORY_KEY),
    ):
        with pytest.raises(FeatureUpdateQueueLockBusy):
            await claim_next_update_request(migrated_session)

    still_queued = await get_update_request(migrated_session, request.request_id)
    assert still_queued is not None
    assert still_queued.status == "queued"


async def test_enqueue_now_raises_when_scope_lock_is_held(
    migrated_engine: AsyncEngine,
    migrated_session: AsyncSession,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    scope = {"type": "feature_ids", "feature_ids": ["feature-1", "feature-2"]}
    lock_key = feature_update_scope_advisory_key(
        scope_type="feature_ids",
        scope=scope,
        providers=["python-a-api"],
        dataset_keys=["dataset-a"],
    )

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as holder,
        holder.begin(),
        advisory_lock(holder, lock_key),
    ):
        with pytest.raises(FeatureUpdateLockBusy) as exc_info:
            await enqueue_feature_update_request(
                migrated_session,
                scope=scope,
                providers=["python-a-api"],
                dataset_keys=["dataset-a"],
                run_mode="now",
            )

    assert exc_info.value.retry_after_seconds == 15
    assert await _count_rows(migrated_session, "ops.feature_update_requests") == 0
    assert await _count_rows(migrated_session, "ops.import_jobs") == 0


async def test_start_finish_and_cancel_update_linked_import_job(
    migrated_session: AsyncSession,
) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        run_mode="now",
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None

    started = await start_update_request(
        migrated_session, request.request_id, dagster_run_id="run-1"
    )
    assert started is not None
    assert started.status == "running"
    assert started.dagster_run_id == "run-1"
    job = await _job_row(migrated_session, request.job_id)
    assert job["status"] == "running"
    assert job["current_stage"] == "started"

    done = await finish_update_request(
        migrated_session, request.request_id, status="done"
    )
    assert done is not None
    assert done.status == "done"
    job = await _job_row(migrated_session, request.job_id)
    assert job["status"] == "done"
    assert job["progress"] == 100
    assert await finish_update_request(
        migrated_session, request.request_id, status="failed"
    ) is None

    to_cancel = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(to_cancel, FeatureUpdateRequest)
    assert to_cancel.job_id is not None
    cancelled = await cancel_update_request(
        migrated_session,
        to_cancel.request_id,
        error_message="operator cancelled",
    )
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    job = await _job_row(migrated_session, to_cancel.job_id)
    assert job["status"] == "cancelled"
    assert job["error_message"] == "operator cancelled"


async def test_finish_invalid_status_raises(migrated_session: AsyncSession) -> None:
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
    )
    assert isinstance(request, FeatureUpdateRequest)
    with pytest.raises(ValueError, match="status must be one of"):
        await finish_update_request(
            migrated_session, request.request_id, status="running"
        )


async def test_list_update_requests_uses_keyset_cursor(
    migrated_session: AsyncSession,
) -> None:
    created = [
        await enqueue_feature_update_request(
            migrated_session,
            scope={"type": "feature_ids", "feature_ids": []},
            priority=priority,
        )
        for priority in (10, 20, 30)
    ]
    assert all(isinstance(item, FeatureUpdateRequest) for item in created)

    page1 = await list_update_requests(migrated_session, limit=2)
    assert len(page1.items) == 2
    assert page1.next_cursor is not None

    page2 = await list_update_requests(
        migrated_session, limit=2, cursor=page1.next_cursor
    )
    assert len(page2.items) == 1
    assert page2.next_cursor is None

    seen_ids = {item.request_id for item in page1.items + page2.items}
    assert seen_ids == {
        item.request_id for item in created if isinstance(item, FeatureUpdateRequest)
    }

    queued_page = await list_update_requests(
        migrated_session, status="queued", limit=10
    )
    assert len(queued_page.items) == 3


async def test_list_update_requests_filters_by_scope_provider_dataset_and_time(
    migrated_session: AsyncSession,
) -> None:
    target = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-a-api"],
        dataset_keys=["dataset-a"],
    )
    other_provider = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-b-api"],
        dataset_keys=["dataset-a"],
    )
    other_scope = await enqueue_feature_update_request(
        migrated_session,
        scope={"type": "bbox", "min_lon": 126, "min_lat": 37, "max_lon": 127, "max_lat": 38},
        providers=["python-a-api"],
        dataset_keys=["dataset-b"],
    )
    assert isinstance(target, FeatureUpdateRequest)
    assert isinstance(other_provider, FeatureUpdateRequest)
    assert isinstance(other_scope, FeatureUpdateRequest)

    page = await list_update_requests(
        migrated_session,
        scope_type="feature_ids",
        provider="python-a-api",
        dataset_key="dataset-a",
        created_from=target.created_at,
        created_to=target.created_at,
        limit=10,
    )

    assert [item.request_id for item in page.items] == [target.request_id]

    provider_dataset = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "provider_dataset",
            "provider": "python-c-api",
            "dataset_key": "dataset-c",
        },
    )
    assert isinstance(provider_dataset, FeatureUpdateRequest)

    provider_dataset_page = await list_update_requests(
        migrated_session,
        scope_type="provider_dataset",
        provider="python-c-api",
        dataset_key="dataset-c",
        limit=10,
    )

    assert [item.request_id for item in provider_dataset_page.items] == [
        provider_dataset.request_id
    ]


async def test_invalid_cursor_raises(migrated_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="invalid feature update request cursor"):
        await list_update_requests(migrated_session, cursor="not-base64")
