from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from kortravelmap.api.pipeline_cancellation_service import cancel_pipeline_execution
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.core.cache_target_stream import (
    SnapshotMerkleRowV1,
    make_active_cache_target_source,
    make_deleted_cache_target_source,
    snapshot_merkle_root,
)
from kortravelmap.infra import cache_target_event_repo as result_event_repo
from kortravelmap.infra import cache_target_reconciliation_repo as snapshot_repo
from kortravelmap.infra import cache_target_service_repo as service_repo
from kortravelmap.infra.cache_target_event_repo import (
    CacheTargetRefreshMember,
    CacheTargetRefreshProtocolViolation,
    append_cache_target_links_reconciled_events,
    append_cache_target_refresh_status_events,
    capture_cache_target_refresh_members_by_keys,
    pinvi_cache_target_refresh_protocol_error,
)
from kortravelmap.infra.cache_target_outbox_repo import (
    CacheTargetAppliedReceipt,
    ack_cache_target_events,
    cache_target_event_cursor,
    claim_cache_target_events,
    get_cache_target_dead_letter,
    list_cache_target_dead_letters,
    nack_cache_target_event,
    replay_cache_target_dead_letter,
)
from kortravelmap.infra.cache_target_reconciliation_repo import (
    begin_cache_target_reconciliation,
    complete_cache_target_reconciliation,
    get_cache_target_operation,
    get_cache_target_reconciliation,
    get_cache_target_reconciliation_snapshot,
    get_cache_target_snapshot,
    get_cache_target_stream_discovery,
    list_cache_target_stream_statuses,
    observe_expired_cache_target_snapshot_backlog,
    prune_expired_cache_target_snapshots_batch,
    request_cache_target_reconciliation,
    seal_cache_target_reconciliation,
)
from kortravelmap.infra.cache_target_restore import (
    CacheTargetRestoreReference,
    fence_restored_cache_target_streams,
    list_cache_target_restore_references,
)
from kortravelmap.infra.cache_target_service_repo import (
    create_cache_target_refresh_request,
    get_cache_target_refresh_request,
    get_cache_target_source,
)
from kortravelmap.infra.cache_target_stream_repo import (
    CacheTargetStreamConflict,
    advance_cache_target_restore_fence,
    apply_cache_target_source,
    get_cache_target_stream,
    lock_cache_target_stream,
)
from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
    create_domain_command_claim,
)
from kortravelmap.infra.feature_update_repo import (
    enqueue_feature_update_request,
    get_update_request,
)
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from tests.integration._db_cleanup import truncate_committed_test_rows

_SYSTEM = "pinvi-test"
_CONSUMER = "pinvi-cache-consumer"
_TARGET_KEY = "trip-day-poi:1"


# 이 모듈의 여러 테스트가 session-scope `migrated_engine`에 **commit**한다(테스트 격리 밖).
# `test_feature_update_repo.py`는 같은 표에 전역 `count(*) == 0`을 단언하므로, 정리하지
# 않으면 두 모듈 사이에 수집 순서 의존이 생긴다. 지금까지는 알파벳 순서상 중간 모듈의
# autouse truncate가 우연히 지워 줘서 통과했을 뿐이라, 모듈을 골라 돌리면 깨진다
# (#975 적대 재리뷰 P2-d). 생산자가 자기 뒤처리를 한다.
# 이 모듈이 commit하는 표 — 새 commit 지점이 생기면 여기도 늘린다.
# 첫 판은 ops 계열만 담았다가 적대 리뷰에서 잡혔다: `_seed_scope_feature`가
# `feature.features`와 `provider_sync.source_*`에 commit해 `test_mois_loader`의 전역
# `count(feature.features) == 0`이 순서에 따라 깨진다.
# 주의 — `truncate_committed_test_rows`는 이 목록 앞에 curation 전체 reset을 무조건
# 붙이고 CASCADE 폐포로 managed_files·offline_uploads·cache-target 하위 표까지 함께
# 비운다. 이 모듈은 매 테스트가 자기 데이터를 새로 seed하므로 그 범위를 감수한다.
_STREAM_TRUNCATE_SQL = """
TRUNCATE
    feature.features,
    provider_sync.source_links,
    provider_sync.source_records,
    provider_sync.source_entity_heads,
    provider_sync.source_entities,
    provider_sync.provider_sync_state,
    ops.poi_cache_target_feature_links,
    ops.poi_cache_targets,
    ops.pipeline_cancellation_members,
    ops.pipeline_cancellation_runs,
    ops.pipeline_cancellations,
    ops.feature_update_requests,
    ops.import_job_events,
    ops.import_jobs
RESTART IDENTITY CASCADE
"""


@pytest.fixture(autouse=True)
async def _cleanup_committed_stream_rows(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[None]:
    """이 모듈이 commit한 행을 테스트마다 제거해 모듈 간 순서 의존을 없앤다."""
    yield
    async with AsyncSession(migrated_engine) as session, session.begin():
        await truncate_committed_test_rows(session, _STREAM_TRUNCATE_SQL)


async def _canonical_membership(session: AsyncSession) -> ImportJobDatasetTarget:
    """catalog에서 활성 triple 하나를 골라 update request membership으로 만든다.

    T-VN-33 이후 feature update request는 **정확한** membership을 요구한다
    (ADR-088 §결정 2) — provider/dataset_key 배열 경로는 없다. 0089가 catalog를
    seed하므로 실제 행을 읽어 쓴다. 활성 request가 이미 점유한 triple은 고르지
    않는다(member mutex는 여기 검증 대상이 아니다).
    """
    row = (
        await session.execute(
            text(
                """
                SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                WHERE dataset.is_active AND operation.is_enabled
                  AND NOT EXISTS (
                      SELECT 1
                      FROM ops.feature_update_request_datasets AS member
                      JOIN ops.feature_update_requests AS request
                        ON request.request_id = member.request_id
                      JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                      WHERE member.provider_dataset_id = scope.provider_dataset_id
                        AND member.sync_scope = scope.sync_scope
                        AND member.operation_key = scope.operation_key
                        AND job.status IN ('queued', 'running')
                  )
                ORDER BY scope.provider_dataset_id, scope.sync_scope, scope.operation_key
                LIMIT 1
                """
            )
        )
    ).one()
    return ImportJobDatasetTarget(
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=str(row.sync_scope),
        operation_key=str(row.operation_key),
    )


async def _seed_scope_feature(
    session: AsyncSession,
    *,
    membership: ImportJobDatasetTarget,
    feature_id: str,
    lon: float = 126.978,
    lat: float = 37.5665,
    category: str = "01070100",
) -> None:
    """cache target 반경 안에 primary source를 가진 feature 1건을 심는다.

    T-VN-33 이후 feature update request는 최소 1개의 canonical membership을
    요구한다(ADR-088 §결정 2). ``cache_target_keys`` scope의 membership은 target
    반경 안 feature의 **primary source가 소유한 dataset**에서 나오므로, service
    refresh 경로(직접 membership을 못 넘긴다)를 태우려면 scope 안에 실제 feature가
    있어야 한다.
    """
    entity_key = f"se_scope_{feature_id}"
    record_key = f"sr_scope_{feature_id}"
    params = {
        "feature_id": feature_id,
        "provider_dataset_id": membership.provider_dataset_id,
        "entity_key": entity_key,
        "record_key": record_key,
        # raw_payload_hash는 ^[0-9a-f]{1,64}$ 를 만족해야 한다.
        "record_hash": hashlib.sha256(record_key.encode("utf-8")).hexdigest(),
        "lon": lon,
        "lat": lat,
        "category": category,
    }
    await session.execute(
        text(
            """
            INSERT INTO feature.features (feature_id, kind, name, category, coord)
            VALUES (
              :feature_id, 'place', 'cache target scope anchor', :category,
              x_extension.ST_SetSRID(
                x_extension.ST_MakePoint(CAST(:lon AS double precision),
                                         CAST(:lat AS double precision)),
                4326
              )
            )
            """
        ),
        params,
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
              source_entity_key, provider_dataset_id, source_entity_type,
              source_entity_id, first_seen_at, last_seen_at
            )
            VALUES (:entity_key, :provider_dataset_id, 'scope_anchor',
                    :feature_id, now(), now())
            """
        ),
        params,
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
              source_record_key, source_entity_key, raw_data, raw_payload_hash,
              fetched_at, imported_at
            )
            VALUES (:record_key, :entity_key, '{}'::jsonb, :record_hash,
                    now(), now())
            """
        ),
        params,
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entity_heads (
              source_entity_key, current_source_record_key, observed_at
            )
            VALUES (:entity_key, :record_key, now())
            """
        ),
        params,
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
              feature_id, source_entity_key, source_role, match_method, confidence
            )
            VALUES (:feature_id, :entity_key, 'primary', 'natural_key', 100)
            """
        ),
        params,
    )


async def _apply_active(
    session: AsyncSession,
    *,
    generation: int,
    event_id: str,
    idempotency_key: str,
    create_only: bool,
    target_id: str | None = None,
    lock_version: int | None = None,
):
    return await apply_cache_target_source(
        session,
        consumer_id=_CONSUMER,
        source_event_id=event_id,
        idempotency_key=idempotency_key,
        external_system=_SYSTEM,
        target_key=_TARGET_KEY,
        restore_epoch=1,
        source_generation=generation,
        source=make_active_cache_target_source(
            lon="126.978",
            lat="37.5665",
            radius_km="5",
            update_enabled=True,
        ),
        occurred_at=datetime(2026, 7, 31, 12, generation, tzinfo=UTC),
        create_only=create_only,
        expected_target_id=target_id,
        expected_lock_version=lock_version,
    )


async def _ready_stream(session: AsyncSession) -> None:
    await session.execute(
        text(
            "UPDATE ops.poi_cache_target_streams "
            "SET status = 'ready', consumer_enabled = true, updated_at = now() "
            "WHERE external_system = :system"
        ),
        {"system": _SYSTEM},
    )


@pytest.mark.integration
async def test_source_generation_outbox_replay_tombstone_and_recreate(
    migrated_session: AsyncSession,
) -> None:
    created = await _apply_active(
        migrated_session,
        generation=1,
        event_id="10000000-0000-0000-0000-000000000001",
        idempotency_key="20000000-0000-0000-0000-000000000001",
        create_only=True,
    )
    assert created.target is not None
    assert created.target_sequence == 1
    assert created.relay_order > 0
    assert not created.idempotent_replay

    replay = await _apply_active(
        migrated_session,
        generation=1,
        event_id="10000000-0000-0000-0000-000000000001",
        idempotency_key="20000000-0000-0000-0000-000000000001",
        create_only=True,
    )
    assert replay.idempotent_replay
    assert replay.outbox_event_id == created.outbox_event_id
    assert replay.relay_order == created.relay_order

    with pytest.raises(CacheTargetStreamConflict) as reused:
        await _apply_active(
            migrated_session,
            generation=1,
            event_id="10000000-0000-0000-0000-000000000099",
            idempotency_key="20000000-0000-0000-0000-000000000001",
            create_only=True,
        )
    assert reused.value.code == "idempotency_key_reused"

    first_target = created.target
    updated = await _apply_active(
        migrated_session,
        generation=2,
        event_id="10000000-0000-0000-0000-000000000002",
        idempotency_key="20000000-0000-0000-0000-000000000002",
        create_only=False,
        target_id=first_target.target_id,
        lock_version=first_target.lock_version,
    )
    assert updated.target is not None
    assert updated.target.target_id == first_target.target_id
    assert updated.target.lock_version > first_target.lock_version
    created_after_update_replay = await _apply_active(
        migrated_session,
        generation=1,
        event_id="10000000-0000-0000-0000-000000000001",
        idempotency_key="20000000-0000-0000-0000-000000000001",
        create_only=True,
    )
    assert created_after_update_replay.entity_tag == created.entity_tag
    assert created_after_update_replay.target_id == created.target_id

    deleted = await apply_cache_target_source(
        migrated_session,
        consumer_id=_CONSUMER,
        source_event_id="10000000-0000-0000-0000-000000000003",
        idempotency_key="20000000-0000-0000-0000-000000000003",
        external_system=_SYSTEM,
        target_key=_TARGET_KEY,
        restore_epoch=1,
        source_generation=3,
        source=make_deleted_cache_target_source(),
        occurred_at=datetime(2026, 7, 31, 12, 3, tzinfo=UTC),
        create_only=False,
        expected_target_id=updated.target.target_id,
        expected_lock_version=updated.target.lock_version,
    )
    assert deleted.state == "deleted"
    assert deleted.payload["target"] is None
    assert deleted.target is not None
    receipt_lock_version = await migrated_session.scalar(
        text(
            "SELECT target_lock_version "
            "FROM ops.poi_cache_target_source_events "
            "WHERE event_id = '10000000-0000-0000-0000-000000000003'"
        )
    )
    drifted_lock_version = await migrated_session.scalar(
        text(
            "UPDATE ops.poi_cache_targets SET name = 'post-delete drift' "
            "WHERE target_id = CAST(:target_id AS uuid) RETURNING lock_version"
        ),
        {"target_id": deleted.target_id},
    )
    assert receipt_lock_version == deleted.target.lock_version
    assert drifted_lock_version == deleted.target.lock_version + 1

    delete_replay = await apply_cache_target_source(
        migrated_session,
        consumer_id=_CONSUMER,
        source_event_id="10000000-0000-0000-0000-000000000003",
        idempotency_key="20000000-0000-0000-0000-000000000003",
        external_system=_SYSTEM,
        target_key=_TARGET_KEY,
        restore_epoch=1,
        source_generation=3,
        source=make_deleted_cache_target_source(),
        occurred_at=datetime(2026, 7, 31, 12, 3, tzinfo=UTC),
        create_only=False,
        expected_target_id=updated.target.target_id,
        expected_lock_version=updated.target.lock_version,
    )
    assert delete_replay.idempotent_replay
    assert delete_replay.target is None
    assert delete_replay.target_id == deleted.target_id
    assert delete_replay.entity_tag == deleted.entity_tag

    recreated = await _apply_active(
        migrated_session,
        generation=4,
        event_id="10000000-0000-0000-0000-000000000004",
        idempotency_key="20000000-0000-0000-0000-000000000004",
        create_only=True,
    )
    assert recreated.target is not None
    assert recreated.target.target_id != first_target.target_id

    head = (
        await migrated_session.execute(
            text(
                "SELECT target_id, state, source_generation, target_sequence "
                "FROM ops.poi_cache_target_source_heads "
                "WHERE external_system = :system AND target_key = :key"
            ),
            {"system": _SYSTEM, "key": _TARGET_KEY},
        )
    ).one()
    assert str(head.target_id) == recreated.target.target_id
    assert (head.state, head.source_generation, head.target_sequence) == ("active", 4, 1)

    counts = (
        await migrated_session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM ops.poi_cache_target_source_events "
                " WHERE external_system = :system) AS source_count, "
                "(SELECT count(*) FROM ops.poi_cache_target_outbox_events "
                " WHERE external_system = :system) AS outbox_count, "
                "(SELECT count(*) FROM ops.poi_cache_target_outbox_deliveries AS d "
                " JOIN ops.poi_cache_target_outbox_events AS e USING (event_id) "
                " WHERE e.external_system = :system AND d.status = 'pending') "
                "AS delivery_count"
            ),
            {"system": _SYSTEM},
        )
    ).one()
    assert tuple(counts) == (4, 4, 4)


@pytest.mark.integration
async def test_generation_gap_and_restore_fence_cas(
    migrated_session: AsyncSession,
) -> None:
    await _apply_active(
        migrated_session,
        generation=1,
        event_id="30000000-0000-0000-0000-000000000001",
        idempotency_key="40000000-0000-0000-0000-000000000001",
        create_only=True,
    )
    with pytest.raises(CacheTargetStreamConflict) as caught:
        await _apply_active(
            migrated_session,
            generation=3,
            event_id="30000000-0000-0000-0000-000000000003",
            idempotency_key="40000000-0000-0000-0000-000000000003",
            create_only=False,
            target_id="00000000-0000-0000-0000-000000000001",
            lock_version=1,
        )
    assert caught.value.code == "source_generation_mismatch"
    assert caught.value.current["expected_next_generation"] == 2
    counts = (
        await migrated_session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM ops.poi_cache_target_source_events "
                " WHERE external_system = :system), "
                "(SELECT count(*) FROM ops.poi_cache_target_outbox_events "
                " WHERE external_system = :system)"
            ),
            {"system": _SYSTEM},
        )
    ).one()
    assert tuple(counts) == (1, 1)

    request = {
        "external_system": _SYSTEM,
        "expected_restore_epoch": 1,
        "reason": "restore test",
    }
    fingerprint = canonical_domain_command_fingerprint(request)
    claim = await create_domain_command_claim(
        migrated_session,
        actor=_CONSUMER,
        operation="cache_target.restore_fence",
        idempotency_key="50000000-0000-0000-0000-000000000001",
        request_fingerprint=fingerprint,
    )
    fenced = await advance_cache_target_restore_fence(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        command_id=claim.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason="restore test",
        request_fingerprint=fingerprint,
    )
    assert (fenced.previous_restore_epoch, fenced.restore_epoch) == (1, 2)
    assert (fenced.previous_control_version, fenced.control_version) == (1, 2)
    assert fenced.superseded_delivery_count == 1

    control = await get_cache_target_stream(
        migrated_session,
        external_system=_SYSTEM,
    )
    assert control is not None
    assert control.restore_epoch == 2
    assert control.status == "fenced"
    assert not control.consumer_enabled

    replay = await advance_cache_target_restore_fence(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        command_id=claim.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason="restore test",
        request_fingerprint=fingerprint,
    )
    assert replay.idempotent_replay
    assert replay.restore_epoch == 2
    assert replay.superseded_delivery_count == 1


@pytest.mark.integration
async def test_restore_fence_supersedes_prior_epoch_delivery_lifecycle(
    migrated_session: AsyncSession,
) -> None:
    results = []
    current = None
    for generation in range(1, 6):
        result = await _apply_active(
            migrated_session,
            generation=generation,
            event_id=f"31000000-0000-4000-8000-{generation:012d}",
            idempotency_key=f"41000000-0000-4000-8000-{generation:012d}",
            create_only=generation == 1,
            target_id=(current.target.target_id if current is not None else None),
            lock_version=(current.target.lock_version if current is not None else None),
        )
        assert result.target is not None
        current = result
        results.append(result)

    delivered, retry, dead, leased, pending = results
    active_claim_id = "51000000-0000-4000-8000-000000000001"
    lease_token = "61000000-0000-4000-8000-000000000001"
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_outbox_deliveries "
            "SET status = 'delivered', delivered_at = now(), updated_at = now() "
            "WHERE event_id = CAST(:event_id AS uuid)"
        ),
        {"event_id": delivered.outbox_event_id},
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_outbox_deliveries "
            "SET status = 'retry', available_at = now(), updated_at = now() "
            "WHERE event_id = CAST(:event_id AS uuid)"
        ),
        {"event_id": retry.outbox_event_id},
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_outbox_deliveries "
            "SET status = 'dead', error_class = 'permanent', "
            "error_code = 'old_epoch_poison', error_fingerprint = :fingerprint, "
            "updated_at = now() WHERE event_id = CAST(:event_id AS uuid)"
        ),
        {"event_id": dead.outbox_event_id, "fingerprint": "d" * 64},
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_outbox_claims ("
            "claim_id, external_system, consumer_id, idempotency_key, "
            "request_fingerprint, lease_token, status, first_relay_order, "
            "last_relay_order, lease_expires_at) VALUES ("
            "CAST(:claim_id AS uuid), :external_system, :consumer_id, "
            "CAST(:idempotency_key AS uuid), :request_fingerprint, "
            "CAST(:lease_token AS uuid), 'active', :relay_order, :relay_order, "
            "now() + interval '5 minutes')"
        ),
        {
            "claim_id": active_claim_id,
            "external_system": _SYSTEM,
            "consumer_id": _CONSUMER,
            "idempotency_key": "71000000-0000-4000-8000-000000000001",
            "request_fingerprint": "c" * 64,
            "lease_token": lease_token,
            "relay_order": leased.relay_order,
        },
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_outbox_deliveries "
            "SET status = 'leased', attempt_count = 1, "
            "claim_id = CAST(:claim_id AS uuid), "
            "lease_token = CAST(:lease_token AS uuid), "
            "lease_expires_at = now() + interval '5 minutes', updated_at = now() "
            "WHERE event_id = CAST(:event_id AS uuid)"
        ),
        {
            "claim_id": active_claim_id,
            "lease_token": lease_token,
            "event_id": leased.outbox_event_id,
        },
    )
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_streams "
            "SET status = 'blocked', blocked_event_id = CAST(:event_id AS uuid), "
            "consumer_enabled = false, updated_at = now() "
            "WHERE external_system = :external_system"
        ),
        {"external_system": _SYSTEM, "event_id": dead.outbox_event_id},
    )

    before = (
        await migrated_session.execute(
            text(
                "SELECT event.event_id, delivery.status, delivery.delivery_version "
                "FROM ops.poi_cache_target_outbox_events AS event "
                "JOIN ops.poi_cache_target_outbox_deliveries AS delivery "
                "ON delivery.event_id = event.event_id "
                "WHERE event.external_system = :external_system "
                "ORDER BY event.relay_order"
            ),
            {"external_system": _SYSTEM},
        )
    ).all()
    assert [row.status for row in before] == [
        "delivered",
        "retry",
        "dead",
        "leased",
        "pending",
    ]

    request = {
        "external_system": _SYSTEM,
        "expected_restore_epoch": 1,
        "reason": "supersede prior epoch",
    }
    fingerprint = canonical_domain_command_fingerprint(request)
    command = await create_domain_command_claim(
        migrated_session,
        actor=_CONSUMER,
        operation="cache_target.restore_fence",
        idempotency_key="81000000-0000-4000-8000-000000000001",
        request_fingerprint=fingerprint,
    )
    fence = await advance_cache_target_restore_fence(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        command_id=command.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason="supersede prior epoch",
        request_fingerprint=fingerprint,
    )
    assert fence.invalidated_claim_count == 1
    assert fence.superseded_delivery_count == 4

    after = (
        await migrated_session.execute(
            text(
                "SELECT event.event_id, delivery.status, delivery.delivery_version, "
                "delivery.claim_id, delivery.superseded_at "
                "FROM ops.poi_cache_target_outbox_events AS event "
                "JOIN ops.poi_cache_target_outbox_deliveries AS delivery "
                "ON delivery.event_id = event.event_id "
                "WHERE event.external_system = :external_system "
                "ORDER BY event.relay_order"
            ),
            {"external_system": _SYSTEM},
        )
    ).all()
    assert [row.status for row in after] == [
        "delivered",
        "superseded",
        "superseded",
        "superseded",
        "superseded",
    ]
    assert [row.delivery_version for row in after] == [1, 2, 2, 2, 2]
    assert after[0].superseded_at is None
    assert all(row.superseded_at is not None for row in after[1:])
    assert all(row.claim_id is None for row in after[1:])
    assert (
        await migrated_session.scalar(
            text(
                "SELECT status FROM ops.poi_cache_target_outbox_claims "
                "WHERE claim_id = CAST(:claim_id AS uuid)"
            ),
            {"claim_id": active_claim_id},
        )
        == "invalidated"
    )
    assert await get_cache_target_dead_letter(
        migrated_session,
        event_id=dead.outbox_event_id,
    ) is None
    dead_page = await list_cache_target_dead_letters(migrated_session)
    assert dead.outbox_event_id not in {
        item.event.event_id for item in dead_page.items
    }
    with pytest.raises(CacheTargetStreamConflict) as stale_replay:
        await replay_cache_target_dead_letter(
            migrated_session,
            event_id=dead.outbox_event_id,
            expected_delivery_version=2,
        )
    assert stale_replay.value.code == "dead_letter_not_found"

    replay = await advance_cache_target_restore_fence(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        command_id=command.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason="supersede prior epoch",
        request_fingerprint=fingerprint,
    )
    assert replay.idempotent_replay
    assert replay.superseded_delivery_count == 4
    replayed_versions = (
        await migrated_session.execute(
            text(
                "SELECT delivery.delivery_version "
                "FROM ops.poi_cache_target_outbox_events AS event "
                "JOIN ops.poi_cache_target_outbox_deliveries AS delivery "
                "ON delivery.event_id = event.event_id "
                "WHERE event.external_system = :external_system "
                "ORDER BY event.relay_order"
            ),
            {"external_system": _SYSTEM},
        )
    ).scalars().all()
    assert replayed_versions == [1, 2, 2, 2, 2]

    new_epoch = await apply_cache_target_source(
        migrated_session,
        consumer_id=_CONSUMER,
        source_event_id="91000000-0000-4000-8000-000000000001",
        idempotency_key="a1000000-0000-4000-8000-000000000001",
        external_system=_SYSTEM,
        target_key="trip-day-poi:new-epoch",
        restore_epoch=2,
        source_generation=1,
        source=make_active_cache_target_source(
            lon="126.979",
            lat="37.567",
            radius_km="3",
            update_enabled=True,
        ),
        occurred_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        create_only=True,
    )
    await _ready_stream(migrated_session)
    new_claim = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="b1000000-0000-4000-8000-000000000001",
        limit=10,
    )
    assert new_claim is not None
    assert [event.event_id for event in new_claim.events] == [new_epoch.outbox_event_id]
    assert new_claim.events[0].restore_epoch == 2

    status_page = await list_cache_target_stream_statuses(migrated_session)
    status = next(item for item in status_page.items if item.external_system == _SYSTEM)
    assert status.superseded_count == 4
    assert status.dead_count == 0
    assert status.delivered_count == 1
    assert status.pending_count == 0
    assert status.retry_count == 0
    assert status.leased_count == 1


@pytest.mark.integration
@pytest.mark.parametrize("seal_before_fence", [False, True], ids=["preparing", "running"])
async def test_restore_fence_supersedes_active_reconciliation_and_allows_new_begin(
    migrated_session: AsyncSession,
    *,
    seal_before_fence: bool,
) -> None:
    suffix = 2 if seal_before_fence else 1
    system = f"reconciliation-restore-fence-{suffix}"
    begin_command = await _reconciliation_command(
        migrated_session,
        key=f"8a000000-0000-4000-8000-{suffix:012d}",
        operation="service.cache-target-reconciliation.begin",
    )
    active = await begin_cache_target_reconciliation(
        migrated_session,
        command_id=begin_command,
        external_system=system,
        consumer_id=_CONSUMER,
        expected_restore_epoch=1,
        expected_control_version=None,
        create_only=True,
        reason="restore-fence lifecycle test",
    )
    empty_root = snapshot_merkle_root([])
    if seal_before_fence:
        active = await seal_cache_target_reconciliation(
            migrated_session,
            request_id=active.request_id,
            external_system=system,
            consumer_id=_CONSUMER,
            expected_phase_version=1,
            expected_restore_epoch=1,
            expected_item_count=0,
            expected_merkle_root=empty_root,
        )
        assert active.status == "running"

    fence_request = {
        "external_system": system,
        "expected_restore_epoch": 1,
        "reason": "replace active reconciliation",
    }
    fence_fingerprint = canonical_domain_command_fingerprint(fence_request)
    fence_command = await create_domain_command_claim(
        migrated_session,
        actor=_CONSUMER,
        operation="cache_target.restore_fence",
        idempotency_key=f"8b000000-0000-4000-8000-{suffix:012d}",
        request_fingerprint=fence_fingerprint,
    )
    fence = await advance_cache_target_restore_fence(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
        command_id=fence_command.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason="replace active reconciliation",
        request_fingerprint=fence_fingerprint,
    )

    assert fence.invalidated_claim_count == 0
    assert fence.superseded_delivery_count == 0
    assert fence.superseded_reconciliation_count == 1
    assert fence.superseded_reconciliation_request_id == active.request_id
    expected_phase_version = 3 if seal_before_fence else 2
    terminal = (
        await migrated_session.execute(
            text(
                "SELECT status, phase_version, snapshot_id, expected_merkle_root, "
                "actual_merkle_root, error_code, completed_at "
                "FROM ops.poi_cache_target_reconciliation_requests "
                "WHERE request_id = CAST(:request_id AS uuid)"
            ),
            {"request_id": active.request_id},
        )
    ).one()
    assert terminal.status == "superseded"
    assert terminal.phase_version == expected_phase_version
    assert terminal.completed_at is not None
    assert terminal.actual_merkle_root is None
    assert terminal.error_code == "restore_fenced"
    assert (terminal.snapshot_id is not None) is seal_before_fence
    assert (terminal.expected_merkle_root is not None) is seal_before_fence

    replay = await advance_cache_target_restore_fence(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
        command_id=fence_command.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason="replace active reconciliation",
        request_fingerprint=fence_fingerprint,
    )
    assert replay.idempotent_replay
    assert replay.invalidated_claim_count == fence.invalidated_claim_count
    assert replay.superseded_delivery_count == fence.superseded_delivery_count
    assert replay.superseded_reconciliation_count == 1
    assert replay.superseded_reconciliation_request_id == active.request_id
    assert (
        await migrated_session.scalar(
            text(
                "SELECT phase_version "
                "FROM ops.poi_cache_target_reconciliation_requests "
                "WHERE request_id = CAST(:request_id AS uuid)"
            ),
            {"request_id": active.request_id},
        )
        == expected_phase_version
    )

    discovery = await get_cache_target_stream_discovery(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
    )
    assert discovery is not None
    assert discovery.active_reconciliation is None

    with pytest.raises(CacheTargetStreamConflict) as stale_snapshot:
        await get_cache_target_reconciliation_snapshot(
            migrated_session,
            request_id=active.request_id,
            consumer_id=_CONSUMER,
        )
    assert stale_snapshot.value.code == "reconciliation_superseded"
    with pytest.raises(CacheTargetStreamConflict) as stale_seal:
        await seal_cache_target_reconciliation(
            migrated_session,
            request_id=active.request_id,
            external_system=system,
            consumer_id=_CONSUMER,
            expected_phase_version=expected_phase_version,
            expected_restore_epoch=1,
            expected_item_count=0,
            expected_merkle_root=empty_root,
        )
    assert stale_seal.value.code == "reconciliation_superseded"
    with pytest.raises(CacheTargetStreamConflict) as stale_completion:
        await complete_cache_target_reconciliation(
            migrated_session,
            request_id=active.request_id,
            external_system=system,
            consumer_id=_CONSUMER,
            snapshot_id=active.snapshot_id
            or f"8c000000-0000-4000-8000-{suffix:012d}",
            expected_restore_epoch=1,
            actual_merkle_root=empty_root,
        )
    assert stale_completion.value.code == "reconciliation_superseded"

    new_begin_command = await _reconciliation_command(
        migrated_session,
        key=f"8d000000-0000-4000-8000-{suffix:012d}",
        operation="service.cache-target-reconciliation.begin",
    )
    new_begin = await begin_cache_target_reconciliation(
        migrated_session,
        command_id=new_begin_command,
        external_system=system,
        consumer_id=_CONSUMER,
        expected_restore_epoch=2,
        expected_control_version=2,
        create_only=False,
        reason="new epoch reconciliation",
    )
    assert new_begin.status == "preparing"
    assert new_begin.request_id != active.request_id


@pytest.mark.integration
async def test_restore_fence_reconciliation_reference_is_stream_scoped(
    migrated_session: AsyncSession,
) -> None:
    source_system = "reconciliation-fence-source"
    other_system = "reconciliation-fence-other"
    source_command = await _reconciliation_command(
        migrated_session,
        key="8e000000-0000-4000-8000-000000000001",
        operation="service.cache-target-reconciliation.begin",
    )
    source_request = await begin_cache_target_reconciliation(
        migrated_session,
        command_id=source_command,
        external_system=source_system,
        consumer_id=_CONSUMER,
        expected_restore_epoch=1,
        expected_control_version=None,
        create_only=True,
        reason="stream-scoped fence source",
    )
    other_command = await _reconciliation_command(
        migrated_session,
        key="8e000000-0000-4000-8000-000000000002",
        operation="service.cache-target-reconciliation.begin",
    )
    other_request = await begin_cache_target_reconciliation(
        migrated_session,
        command_id=other_command,
        external_system=other_system,
        consumer_id=_CONSUMER,
        expected_restore_epoch=1,
        expected_control_version=None,
        create_only=True,
        reason="stream-scoped fence other",
    )

    fence_request = {
        "external_system": source_system,
        "expected_restore_epoch": 1,
        "reason": "stream-scoped fence",
    }
    fence_fingerprint = canonical_domain_command_fingerprint(fence_request)
    fence_command = await create_domain_command_claim(
        migrated_session,
        actor=_CONSUMER,
        operation="cache_target.restore_fence",
        idempotency_key="8e000000-0000-4000-8000-000000000003",
        request_fingerprint=fence_fingerprint,
    )
    fence = await advance_cache_target_restore_fence(
        migrated_session,
        external_system=source_system,
        consumer_id=_CONSUMER,
        command_id=fence_command.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason="stream-scoped fence",
        request_fingerprint=fence_fingerprint,
    )
    assert fence.superseded_reconciliation_count == 1
    assert fence.superseded_reconciliation_request_id == source_request.request_id

    replay = await advance_cache_target_restore_fence(
        migrated_session,
        external_system=source_system,
        consumer_id=_CONSUMER,
        command_id=fence_command.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason="stream-scoped fence",
        request_fingerprint=fence_fingerprint,
    )
    assert replay.idempotent_replay
    assert replay.superseded_reconciliation_request_id == source_request.request_id

    cross_fingerprint = canonical_domain_command_fingerprint(
        {"external_system": source_system, "request_id": other_request.request_id}
    )
    cross_command = await create_domain_command_claim(
        migrated_session,
        actor=_CONSUMER,
        operation="cache_target.restore_fence",
        idempotency_key="8e000000-0000-4000-8000-000000000004",
        request_fingerprint=cross_fingerprint,
    )
    with pytest.raises(IntegrityError) as cross_insert:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO ops.poi_cache_target_restore_fences ("
                    "external_system, consumer_id, command_id, "
                    "previous_restore_epoch, restore_epoch, "
                    "previous_control_version, control_version, "
                    "invalidated_claim_count, superseded_delivery_count, "
                    "superseded_reconciliation_count, "
                    "superseded_reconciliation_request_id, reason, "
                    "request_fingerprint) VALUES ("
                    ":external_system, :consumer_id, :command_id, 2, 3, 2, 3, "
                    "0, 0, 1, CAST(:request_id AS uuid), :reason, :fingerprint)"
                ),
                {
                    "external_system": source_system,
                    "consumer_id": _CONSUMER,
                    "command_id": cross_command.command_id,
                    "request_id": other_request.request_id,
                    "reason": "cross-stream insert must fail",
                    "fingerprint": cross_fingerprint,
                },
            )
    assert getattr(cross_insert.value.orig, "sqlstate", None) == "23503"
    assert (
        "fk_cache_target_restore_fences_superseded_reconciliation"
        in str(cross_insert.value.orig)
    )

    with pytest.raises(IntegrityError) as cross_update:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE ops.poi_cache_target_reconciliation_requests "
                    "SET external_system = :other_system "
                    "WHERE request_id = CAST(:request_id AS uuid)"
                ),
                {
                    "other_system": other_system,
                    "request_id": source_request.request_id,
                },
            )
    assert getattr(cross_update.value.orig, "sqlstate", None) == "23503"
    assert (
        "fk_cache_target_restore_fences_superseded_reconciliation"
        in str(cross_update.value.orig)
    )


@pytest.mark.integration
async def test_restore_swap_fence_replays_and_rejects_epoch_regression(
    migrated_session: AsyncSession,
) -> None:
    await lock_cache_target_stream(
        migrated_session,
        external_system="restore-swap-test",
        consumer_id=_CONSUMER,
    )
    live_references = await list_cache_target_restore_references(
        migrated_session
    )
    results = await fence_restored_cache_target_streams(
        migrated_session,
        live_references=live_references,
        host_command_id=901,
        host_input_digest="a" * 64,
    )
    assert len(results) == 1
    assert results[0].previous_restore_epoch == 1
    assert results[0].restore_epoch == 2
    assert not results[0].idempotent_replay

    replay = await fence_restored_cache_target_streams(
        migrated_session,
        live_references=live_references,
        host_command_id=901,
        host_input_digest="a" * 64,
    )
    assert len(replay) == 1
    assert replay[0].restore_epoch == 2
    assert replay[0].idempotent_replay

    with pytest.raises(CacheTargetStreamConflict) as caught:
        await fence_restored_cache_target_streams(
            migrated_session,
            live_references=(
                CacheTargetRestoreReference(
                    external_system="restore-swap-test",
                    consumer_id=_CONSUMER,
                    restore_epoch=3,
                    control_version=3,
                ),
            ),
            host_command_id=902,
            host_input_digest="b" * 64,
        )
    assert caught.value.code == "restore_epoch_regression"


@pytest.mark.integration
async def test_claim_applied_gap_and_contiguous_ack(
    migrated_session: AsyncSession,
) -> None:
    first = await _apply_active(
        migrated_session,
        generation=1,
        event_id="60000000-0000-0000-0000-000000000001",
        idempotency_key="61000000-0000-0000-0000-000000000001",
        create_only=True,
    )
    assert first.target is not None
    second = await _apply_active(
        migrated_session,
        generation=2,
        event_id="60000000-0000-0000-0000-000000000002",
        idempotency_key="61000000-0000-0000-0000-000000000002",
        create_only=False,
        target_id=first.target.target_id,
        lock_version=first.target.lock_version,
    )
    assert second.target is not None
    await _apply_active(
        migrated_session,
        generation=3,
        event_id="60000000-0000-0000-0000-000000000003",
        idempotency_key="61000000-0000-0000-0000-000000000003",
        create_only=False,
        target_id=second.target.target_id,
        lock_version=second.target.lock_version,
    )
    await _ready_stream(migrated_session)

    claim = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="62000000-0000-0000-0000-000000000001",
        limit=3,
    )
    assert claim is not None
    assert len(claim.events) == 3
    receipts = [
        CacheTargetAppliedReceipt(event.event_id, event.payload_fingerprint)
        for event in claim.events
    ]
    partial = await ack_cache_target_events(
        migrated_session,
        consumer_id=_CONSUMER,
        claim_id=claim.claim_id,
        lease_token=claim.lease_token,
        through_cursor=claim.events[0].cursor,
        applied=receipts,
    )
    assert partial.status == "active"
    assert partial.applied_count == 3
    assert partial.prefix_acked_count == 1

    gap_counts = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FILTER (WHERE consumer_applied_at IS NOT NULL), "
                "count(*) FILTER (WHERE prefix_acked_at IS NOT NULL) "
                "FROM ops.poi_cache_target_outbox_claim_events "
                "WHERE claim_id = CAST(:claim_id AS uuid)"
            ),
            {"claim_id": claim.claim_id},
        )
    ).one()
    assert tuple(gap_counts) == (3, 1)

    complete = await ack_cache_target_events(
        migrated_session,
        consumer_id=_CONSUMER,
        claim_id=claim.claim_id,
        lease_token=claim.lease_token,
        through_cursor=claim.events[-1].cursor,
        applied=[],
    )
    assert complete.status == "acked"
    assert complete.prefix_acked_count == 3
    delivery_statuses = (
        (
            await migrated_session.execute(
                text("SELECT status FROM ops.poi_cache_target_outbox_deliveries ORDER BY event_id")
            )
        )
        .scalars()
        .all()
    )
    assert delivery_statuses == ["delivered", "delivered", "delivered"]


@pytest.mark.integration
async def test_expired_claim_reclaims_same_event_with_new_lease(
    migrated_session: AsyncSession,
) -> None:
    await _apply_active(
        migrated_session,
        generation=1,
        event_id="70000000-0000-0000-0000-000000000001",
        idempotency_key="71000000-0000-0000-0000-000000000001",
        create_only=True,
    )
    await _ready_stream(migrated_session)
    first = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="72000000-0000-0000-0000-000000000001",
        limit=1,
    )
    assert first is not None
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_outbox_claims "
            "SET lease_expires_at = now() - interval '1 second' "
            "WHERE claim_id = CAST(:claim_id AS uuid)"
        ),
        {"claim_id": first.claim_id},
    )

    reclaimed = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="72000000-0000-0000-0000-000000000002",
        limit=1,
    )
    assert reclaimed is not None
    assert reclaimed.claim_id != first.claim_id
    assert reclaimed.lease_token != first.lease_token
    assert reclaimed.events[0].event_id == first.events[0].event_id


@pytest.mark.integration
async def test_permanent_nack_dead_letter_blocks_later_order_and_replays_same_event(
    migrated_session: AsyncSession,
) -> None:
    first = await _apply_active(
        migrated_session,
        generation=1,
        event_id="80000000-0000-0000-0000-000000000001",
        idempotency_key="81000000-0000-0000-0000-000000000001",
        create_only=True,
    )
    assert first.target is not None
    await _apply_active(
        migrated_session,
        generation=2,
        event_id="80000000-0000-0000-0000-000000000002",
        idempotency_key="81000000-0000-0000-0000-000000000002",
        create_only=False,
        target_id=first.target.target_id,
        lock_version=first.target.lock_version,
    )
    await _ready_stream(migrated_session)
    claim = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="82000000-0000-0000-0000-000000000001",
        limit=2,
    )
    assert claim is not None
    blocked_event = claim.events[0]
    dead = await nack_cache_target_event(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        claim_id=claim.claim_id,
        lease_token=claim.lease_token,
        event_id=blocked_event.event_id,
        error_class="permanent",
        error_code="unsupported_event",
        error_fingerprint="a" * 64,
    )
    assert dead.status == "dead"
    assert dead.stream_blocked
    control = await get_cache_target_stream(
        migrated_session,
        external_system=_SYSTEM,
    )
    assert control is not None
    assert control.status == "blocked"
    assert control.blocked_event_id == blocked_event.event_id
    assert not control.consumer_enabled

    detail = await get_cache_target_dead_letter(
        migrated_session,
        event_id=blocked_event.event_id,
    )
    assert detail is not None
    assert detail.event.relay_order == blocked_event.relay_order
    dead_page = await list_cache_target_dead_letters(migrated_session, limit=1)
    assert len(dead_page.items) == 1
    assert dead_page.items[0].event.event_id == blocked_event.event_id
    with pytest.raises(CacheTargetStreamConflict) as blocked:
        await claim_cache_target_events(
            migrated_session,
            external_system=_SYSTEM,
            consumer_id=_CONSUMER,
            idempotency_key="82000000-0000-0000-0000-000000000002",
            limit=2,
        )
    assert blocked.value.code == "consumer_disabled"

    replayed = await replay_cache_target_dead_letter(
        migrated_session,
        event_id=blocked_event.event_id,
        expected_delivery_version=detail.delivery_version,
    )
    assert replayed.status == "retry"
    replay_control = await get_cache_target_stream(
        migrated_session,
        external_system=_SYSTEM,
    )
    assert replay_control is not None
    assert replay_control.status == "blocked"
    assert replay_control.blocked_event_id == blocked_event.event_id
    assert not replay_control.consumer_enabled
    with pytest.raises(CacheTargetStreamConflict) as replay_blocked:
        await claim_cache_target_events(
            migrated_session,
            external_system=_SYSTEM,
            consumer_id=_CONSUMER,
            idempotency_key="82000000-0000-0000-0000-000000000007",
            limit=2,
        )
    assert replay_blocked.value.code == "consumer_disabled"
    completed = await _resume_stream_after_dead_letter_replay(
        migrated_session,
        key="82000000-0000-0000-0000-000000000005",
    )
    recovery_claim = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="82000000-0000-0000-0000-000000000003",
        limit=2,
    )
    assert recovery_claim is not None
    assert [event.event_type for event in recovery_claim.events] == [
        "cache_target.state_applied",
        "cache_target.state_applied",
    ]
    assert (
        recovery_claim.events[0].relay_order,
        recovery_claim.events[0].payload_fingerprint,
    ) == (blocked_event.relay_order, blocked_event.payload_fingerprint)
    await ack_cache_target_events(
        migrated_session,
        consumer_id=_CONSUMER,
        claim_id=recovery_claim.claim_id,
        lease_token=recovery_claim.lease_token,
        through_cursor=recovery_claim.events[-1].cursor,
        applied=[
            CacheTargetAppliedReceipt(
                event.event_id,
                event.payload_fingerprint,
            )
            for event in recovery_claim.events
        ],
    )
    reconciled_claim = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="82000000-0000-0000-0000-000000000004",
        limit=2,
    )
    assert reconciled_claim is not None
    assert len(reconciled_claim.events) == 1
    reconciled_event = reconciled_claim.events[0]
    assert reconciled_event.event_type == "cache_target.reconciled"
    assert reconciled_event.event_scope == "stream"
    assert reconciled_event.payload["request_id"] == completed.request_id
    await ack_cache_target_events(
        migrated_session,
        consumer_id=_CONSUMER,
        claim_id=reconciled_claim.claim_id,
        lease_token=reconciled_claim.lease_token,
        through_cursor=reconciled_event.cursor,
        applied=[
            CacheTargetAppliedReceipt(
                reconciled_event.event_id,
                reconciled_event.payload_fingerprint,
            )
        ],
    )
    assert (
        await claim_cache_target_events(
            migrated_session,
            external_system=_SYSTEM,
            consumer_id=_CONSUMER,
            idempotency_key="82000000-0000-0000-0000-000000000006",
            limit=2,
        )
        is None
    )


@pytest.mark.integration
async def test_mid_claim_dead_transition_requires_acked_prefix_then_replays(
    migrated_session: AsyncSession,
) -> None:
    first = await _apply_active(
        migrated_session,
        generation=1,
        event_id="83000000-0000-0000-0000-000000000001",
        idempotency_key="84000000-0000-0000-0000-000000000001",
        create_only=True,
    )
    assert first.target is not None
    await _apply_active(
        migrated_session,
        generation=2,
        event_id="83000000-0000-0000-0000-000000000002",
        idempotency_key="84000000-0000-0000-0000-000000000002",
        create_only=False,
        target_id=first.target.target_id,
        lock_version=first.target.lock_version,
    )
    await _ready_stream(migrated_session)
    claim = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="85000000-0000-0000-0000-000000000001",
        limit=2,
    )
    assert claim is not None
    leading, poison = claim.events

    with pytest.raises(CacheTargetStreamConflict) as unsafe:
        await nack_cache_target_event(
            migrated_session,
            external_system=_SYSTEM,
            consumer_id=_CONSUMER,
            claim_id=claim.claim_id,
            lease_token=claim.lease_token,
            event_id=poison.event_id,
            error_class="permanent",
            error_code="unsupported_event",
            error_fingerprint="b" * 64,
        )
    assert unsafe.value.code == "dead_letter_requires_prefix_ack"

    partial = await ack_cache_target_events(
        migrated_session,
        consumer_id=_CONSUMER,
        claim_id=claim.claim_id,
        lease_token=claim.lease_token,
        through_cursor=leading.cursor,
        applied=[
            CacheTargetAppliedReceipt(
                leading.event_id,
                leading.payload_fingerprint,
            )
        ],
    )
    assert partial.status == "active"
    claim_replay = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="85000000-0000-0000-0000-000000000001",
        limit=2,
    )
    assert claim_replay is not None
    assert claim_replay.idempotent_replay
    assert claim_replay.acked_through == leading.cursor
    dead = await nack_cache_target_event(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        claim_id=claim.claim_id,
        lease_token=claim.lease_token,
        event_id=poison.event_id,
        error_class="permanent",
        error_code="unsupported_event",
        error_fingerprint="b" * 64,
    )
    assert dead.status == "dead"
    replayed = await replay_cache_target_dead_letter(
        migrated_session,
        event_id=poison.event_id,
        expected_delivery_version=dead.delivery_version,
    )
    assert replayed.status == "retry"
    replay_control = await get_cache_target_stream(
        migrated_session,
        external_system=_SYSTEM,
    )
    assert replay_control is not None
    assert replay_control.status == "blocked"
    assert replay_control.blocked_event_id == poison.event_id
    assert not replay_control.consumer_enabled
    with pytest.raises(CacheTargetStreamConflict) as replay_blocked:
        await claim_cache_target_events(
            migrated_session,
            external_system=_SYSTEM,
            consumer_id=_CONSUMER,
            idempotency_key="85000000-0000-0000-0000-000000000004",
            limit=2,
        )
    assert replay_blocked.value.code == "consumer_disabled"
    completed = await _resume_stream_after_dead_letter_replay(
        migrated_session,
        key="85000000-0000-0000-0000-000000000003",
    )
    recovery = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="85000000-0000-0000-0000-000000000002",
        limit=2,
    )
    assert recovery is not None
    assert [event.event_id for event in recovery.events[:1]] == [poison.event_id]
    assert [event.event_type for event in recovery.events] == [
        "cache_target.state_applied",
        "cache_target.reconciled",
    ]
    assert recovery.events[1].payload["request_id"] == completed.request_id
    await ack_cache_target_events(
        migrated_session,
        consumer_id=_CONSUMER,
        claim_id=recovery.claim_id,
        lease_token=recovery.lease_token,
        through_cursor=recovery.events[-1].cursor,
        applied=[
            CacheTargetAppliedReceipt(
                event.event_id,
                event.payload_fingerprint,
            )
            for event in recovery.events
        ],
    )
    assert (
        await claim_cache_target_events(
            migrated_session,
            external_system=_SYSTEM,
            consumer_id=_CONSUMER,
            idempotency_key="85000000-0000-0000-0000-000000000005",
            limit=2,
        )
        is None
    )


async def _apply_snapshot_source(
    session: AsyncSession,
    *,
    external_system: str,
    target_key: str,
    event_id: str,
    idempotency_key: str,
):
    return await apply_cache_target_source(
        session,
        consumer_id=_CONSUMER,
        source_event_id=event_id,
        idempotency_key=idempotency_key,
        external_system=external_system,
        target_key=target_key,
        restore_epoch=1,
        source_generation=1,
        source=make_active_cache_target_source(
            lon="126.978",
            lat="37.5665",
            radius_km="5",
            update_enabled=True,
        ),
        occurred_at=datetime(2026, 7, 31, 18, 0, tzinfo=UTC),
        create_only=True,
    )


async def _bulk_seed_deleted_snapshot_heads(
    session: AsyncSession,
    *,
    external_system: str,
    count: int,
) -> None:
    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_source_heads ("
            "external_system, target_key, target_id, state, restore_epoch, "
            "source_generation, source_payload_fingerprint, target_sequence) "
            "SELECT :external_system, 'target-' || lpad(value::text, 4, '0'), "
            "NULL, 'deleted', 1, 1, repeat('b', 64), 0 "
            "FROM generate_series(1, :count) AS value"
        ),
        {"external_system": external_system, "count": count},
    )


@pytest.mark.integration
async def test_snapshot_materialization_streams_more_than_one_insert_batch(
    migrated_session: AsyncSession,
) -> None:
    system = "snapshot-streaming-batch-test"
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-0000",
        event_id="9f410000-0000-4000-8000-000000000001",
        idempotency_key="9f420000-0000-4000-8000-000000000001",
    )
    await _bulk_seed_deleted_snapshot_heads(
        migrated_session,
        external_system=system,
        count=1_004,
    )

    page = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=2,
    )

    assert page.count == 1_005
    assert [item.target_key for item in page.items] == ["target-0000", "target-0001"]
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) "
                "FROM ops.poi_cache_target_snapshot_material_items AS item "
                "JOIN ops.poi_cache_target_snapshots AS receipt "
                "ON receipt.material_id = item.material_id "
                "WHERE receipt.snapshot_id = CAST(:snapshot_id AS uuid)"
            ),
            {"snapshot_id": page.snapshot_id},
        )
        == 1_005
    )


@pytest.mark.integration
async def test_snapshot_cumulative_timeout_rolls_back_and_releases_writer(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = "snapshot-cumulative-timeout-test"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="target-a",
            event_id="9f410000-0000-4000-8000-000000000011",
            idempotency_key="9f420000-0000-4000-8000-000000000011",
        )
        await _bulk_seed_deleted_snapshot_heads(
            setup,
            external_system=system,
            count=1_004,
        )

    original_stream = snapshot_repo._stream_snapshot_capture  # pyright: ignore[reportPrivateUsage]
    first_item_batch_inserted = asyncio.Event()
    never = asyncio.Event()
    stream_calls = 0

    async def _delayed_second_pass(
        session: AsyncSession,
        *,
        external_system: str,
    ) -> AsyncIterator[Any]:
        nonlocal stream_calls
        stream_calls += 1
        if stream_calls == 1:
            async for row in original_stream(
                session,
                external_system=external_system,
            ):
                yield row
            return
        async for row in original_stream(
            session,
            external_system=external_system,
        ):
            yield row
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) "
                    "FROM ops.poi_cache_target_snapshot_material_items AS item "
                    "JOIN ops.poi_cache_target_snapshot_materials AS material "
                    "ON material.material_id = item.material_id "
                    "WHERE material.external_system = :external_system"
                ),
                {"external_system": external_system},
            )
            == 1_000
        )
        first_item_batch_inserted.set()
        await never.wait()

    monkeypatch.setattr(snapshot_repo, "_SNAPSHOT_BUILD_TIMEOUT_SECONDS", 3.0)
    monkeypatch.setattr(snapshot_repo, "_stream_snapshot_capture", _delayed_second_pass)

    async def _build_snapshot() -> Any:
        async with AsyncSession(migrated_engine) as reader, reader.begin():
            return await get_cache_target_snapshot(
                reader,
                external_system=system,
                limit=1,
            )

    async def _write_source() -> Any:
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            return await _apply_snapshot_source(
                writer,
                external_system=system,
                target_key="writer-target",
                event_id="9f410000-0000-4000-8000-000000000012",
                idempotency_key="9f420000-0000-4000-8000-000000000012",
            )

    build_task = asyncio.create_task(_build_snapshot())
    writer_task: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(first_item_batch_inserted.wait(), timeout=5)
        writer_task = asyncio.create_task(_write_source())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(writer_task), timeout=0.1)

        with pytest.raises(CacheTargetStreamConflict) as timed_out:
            await asyncio.wait_for(build_task, timeout=5)
        assert timed_out.value.code == "snapshot_build_timeout"

        written = await asyncio.wait_for(writer_task, timeout=3)
        assert written.target_key == "writer-target"
    finally:
        pending = tuple(
            task
            for task in (build_task, writer_task)
            if task is not None and not task.done()
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async with AsyncSession(migrated_engine) as observer, observer.begin():
        assert (
            await observer.scalar(
                text(
                    "SELECT count(*) FROM ops.poi_cache_target_snapshots "
                    "WHERE external_system = :external_system"
                ),
                {"external_system": system},
            )
            == 0
        )
        assert (
            await observer.scalar(
                text(
                    "SELECT count(*) "
                    "FROM ops.poi_cache_target_snapshot_material_items AS item "
                    "JOIN ops.poi_cache_target_snapshot_materials AS material "
                    "ON material.material_id = item.material_id "
                    "WHERE material.external_system = :external_system"
                ),
                {"external_system": system},
            )
            == 0
        )


@pytest.mark.integration
async def test_non_nfc_identity_cannot_poison_snapshot(
    migrated_session: AsyncSession,
) -> None:
    system = "snapshot-nfc-test"
    canonical_key = "poi:\u00e9"
    noncanonical_key = "poi:e\u0301"

    def _scope(target_key: str) -> str:
        return json.dumps(
            {
                "type": "cache_target_keys",
                "external_system": system,
                "target_keys": [target_key],
                "scope_mode": "center_radius",
            }
        )

    assert await migrated_session.scalar(
        text(
            "SELECT ops.is_valid_feature_update_scope("
            "'cache_target_keys', CAST(:scope AS jsonb))"
        ),
        {"scope": _scope("x" * 512)},
    )
    assert not await migrated_session.scalar(
        text(
            "SELECT ops.is_valid_feature_update_scope("
            "'cache_target_keys', CAST(:scope AS jsonb))"
        ),
        {"scope": _scope("x" * 513)},
    )
    assert not await migrated_session.scalar(
        text(
            "SELECT ops.is_valid_feature_update_scope("
            "'cache_target_keys', CAST(:scope AS jsonb))"
        ),
        {"scope": _scope(noncanonical_key)},
    )

    with pytest.raises(ValueError, match="target_key.*NFC"):
        await _apply_snapshot_source(
            migrated_session,
            external_system=system,
            target_key=noncanonical_key,
            event_id="90a00000-0000-0000-0000-000000000001",
            idempotency_key="90b00000-0000-0000-0000-000000000001",
        )
    with pytest.raises(ValueError, match="target_key.*trim"):
        await _apply_snapshot_source(
            migrated_session,
            external_system=system,
            target_key="\u3000poi:space",
            event_id="90a00000-0000-0000-0000-000000000003",
            idempotency_key="90b00000-0000-0000-0000-000000000003",
        )
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO ops.poi_cache_target_streams ("
                    "external_system, consumer_id, restore_epoch, control_version, "
                    "status, consumer_enabled) VALUES ("
                    ":external_system, :consumer_id, 1, 1, 'fenced', false)"
                ),
                {
                    "external_system": "\u3000snapshot-space-test",
                    "consumer_id": _CONSUMER,
                },
            )
    constraint_rows = (
        await migrated_session.execute(
            text(
                "SELECT relation.relname AS table_name, "
                "pg_get_constraintdef(constraint_row.oid) AS definition "
                "FROM pg_constraint AS constraint_row "
                "JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid "
                "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'ops' "
                "AND constraint_row.contype = 'c' "
                "AND relation.relname = ANY(:table_names)"
            ),
            {
                "table_names": [
                    "poi_cache_targets",
                    "poi_cache_target_streams",
                    "poi_cache_target_source_heads",
                ]
            },
        )
    ).mappings()
    canonical_identity_tables = {
        str(row["table_name"])
        for row in constraint_rows
        if "btrim" in str(row["definition"]).lower()
        and "normalize" in str(row["definition"]).lower()
    }
    assert canonical_identity_tables == {
        "poi_cache_targets",
        "poi_cache_target_streams",
        "poi_cache_target_source_heads",
    }

    head = await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key=canonical_key,
        event_id="90a00000-0000-0000-0000-000000000002",
        idempotency_key="90b00000-0000-0000-0000-000000000002",
    )
    with pytest.raises(IntegrityError) as constraint_error:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE ops.poi_cache_targets SET target_key = :target_key "
                    "WHERE target_id = CAST(:target_id AS uuid)"
                ),
                {"target_key": noncanonical_key, "target_id": head.target_id},
            )
    assert "ck_poi_cache_targets_target_key_identity" in str(constraint_error.value)
    with pytest.raises(IntegrityError) as root_trim_constraint_error:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE ops.poi_cache_targets SET target_key = :target_key "
                    "WHERE target_id = CAST(:target_id AS uuid)"
                ),
                {"target_key": "\u3000poi:space", "target_id": head.target_id},
            )
    assert "ck_poi_cache_targets_target_key_identity" in str(
        root_trim_constraint_error.value
    )
    with pytest.raises(IntegrityError):
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE ops.poi_cache_target_source_heads "
                    "SET target_key = :target_key "
                    "WHERE external_system = :external_system AND target_key = :canonical_key"
                ),
                {
                    "target_key": "\u3000poi:space",
                    "external_system": system,
                    "canonical_key": canonical_key,
                },
            )

    snapshot = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=10,
    )
    assert snapshot.count == 1
    assert [item.target_key for item in snapshot.items] == [canonical_key]


@pytest.mark.integration
async def test_fixed_snapshot_pages_ignore_concurrent_committed_write(
    migrated_engine: AsyncEngine,
) -> None:
    system = "snapshot-concurrency-test"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="target-a",
            event_id="91000000-0000-0000-0000-000000000001",
            idempotency_key="92000000-0000-0000-0000-000000000001",
        )
        await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="target-b",
            event_id="91000000-0000-0000-0000-000000000002",
            idempotency_key="92000000-0000-0000-0000-000000000002",
        )

    async with AsyncSession(migrated_engine) as reader, reader.begin():
        first = await get_cache_target_snapshot(
            reader,
            external_system=system,
            limit=1,
        )
    assert first.count == 2
    assert first.next_cursor is not None

    async with AsyncSession(migrated_engine) as reader, reader.begin():
        reused = await get_cache_target_snapshot(
            reader,
            external_system=system,
            limit=1,
        )
    # 재사용은 material을 공유하고 **receipt는 새로 만든다**(0230). snapshot_id는 이제
    # "누가 언제 받아갔는가"이지 "무엇을 고정했는가"가 아니다 — 같은 material인지는
    # root/count로 본다. replay cursor는 material이 들고 있으므로 그대로 같다.
    assert reused.snapshot_id != first.snapshot_id
    assert (reused.merkle_root, reused.count) == (first.merkle_root, first.count)
    assert reused.high_watermark_cursor == first.high_watermark_cursor
    # 앞선 receipt의 만료를 물려받지 않는다 — 이것이 재사용 전 잔여 TTL 검사를
    # 없앨 수 있었던 이유다.
    assert reused.created_at > first.created_at
    assert reused.expires_at > first.expires_at

    async with AsyncSession(migrated_engine) as writer, writer.begin():
        await _apply_snapshot_source(
            writer,
            external_system=system,
            target_key="target-c",
            event_id="91000000-0000-0000-0000-000000000003",
            idempotency_key="92000000-0000-0000-0000-000000000003",
        )

    async with AsyncSession(migrated_engine) as reader, reader.begin():
        second = await get_cache_target_snapshot(
            reader,
            external_system=system,
            limit=1,
            cursor=first.next_cursor,
        )
        fresh = await get_cache_target_snapshot(
            reader,
            external_system=system,
            limit=10,
        )
    assert second.snapshot_id == first.snapshot_id
    assert second.count == first.count == 2
    assert second.merkle_root == first.merkle_root
    assert [first.items[0].target_key, second.items[0].target_key] == [
        "target-a",
        "target-b",
    ]
    assert fresh.snapshot_id != first.snapshot_id
    assert fresh.count == 3


@pytest.mark.integration
async def test_generic_snapshot_try_lock_fails_fast_and_then_reuses(
    migrated_engine: AsyncEngine,
) -> None:
    system = "snapshot-try-lock-test"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="target-a",
            event_id="9c000000-0000-4000-8000-000000000011",
            idempotency_key="9d000000-0000-4000-8000-000000000011",
        )

    async with AsyncSession(migrated_engine) as owner:
        owner_tx = await owner.begin()
        first = await get_cache_target_snapshot(
            owner,
            external_system=system,
            limit=1,
        )
        async with AsyncSession(migrated_engine) as contender, contender.begin():
            with pytest.raises(CacheTargetStreamConflict) as busy:
                await get_cache_target_snapshot(
                    contender,
                    external_system=system,
                    limit=1,
                )
            assert busy.value.code == "snapshot_busy"
        await owner_tx.commit()

    async with AsyncSession(migrated_engine) as retry, retry.begin():
        reused = await get_cache_target_snapshot(
            retry,
            external_system=system,
            limit=1,
        )
    # 재사용은 material을 공유하고 **receipt는 새로 만든다**(0230). snapshot_id는 이제
    # "누가 언제 받아갔는가"이지 "무엇을 고정했는가"가 아니다 — 같은 material인지는
    # root/count로 본다. replay cursor는 material이 들고 있으므로 그대로 같다.
    assert reused.snapshot_id != first.snapshot_id
    assert (reused.merkle_root, reused.count) == (first.merkle_root, first.count)
    assert reused.high_watermark_cursor == first.high_watermark_cursor


@pytest.mark.integration
async def test_snapshot_barrier_keeps_outbox_cursor_commit_safe_across_writers(
    migrated_engine: AsyncEngine,
) -> None:
    system = "snapshot-outbox-prefix-test"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        first = await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="target-a",
            event_id="9a100000-0000-4000-8000-000000000011",
            idempotency_key="9a200000-0000-4000-8000-000000000011",
        )
    member = CacheTargetRefreshMember(
        request_id="9a300000-0000-4000-8000-000000000011",
        target_id=first.target_id,
        external_system=system,
        target_key="target-a",
        restore_epoch=1,
        source_generation=1,
        source_payload_fingerprint=first.source_payload_fingerprint,
        created_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
    )

    low_writer = AsyncSession(migrated_engine)
    low_tx = await low_writer.begin()
    low_state = await _apply_snapshot_source(
        low_writer,
        external_system=system,
        target_key="target-b",
        event_id="9a100000-0000-4000-8000-000000000012",
        idempotency_key="9a200000-0000-4000-8000-000000000012",
    )

    async def _append_high_result():
        async with AsyncSession(migrated_engine) as writer, writer.begin():
            row = (
                await writer.execute(
                    text(
                        "INSERT INTO ops.poi_cache_target_outbox_events ("
                        "event_id, relay_order, event_type, event_scope, external_system, "
                        "target_key, target_id, restore_epoch, source_generation, "
                        "target_sequence, source_payload_fingerprint, "
                        "payload_fingerprint, payload) VALUES ("
                        "'9a500000-0000-4000-8000-000000000011', 1, "
                        "'cache_target.links_reconciled', 'target', "
                        ":external_system, 'target-a', CAST(:target_id AS uuid), "
                        "1, 1, 2, :source_fingerprint, :payload_fingerprint, "
                        "CAST(:payload AS jsonb)) "
                        "RETURNING event_id::text, relay_order"
                    ),
                    {
                        "external_system": system,
                        "target_id": member.target_id,
                        "source_fingerprint": member.source_payload_fingerprint,
                        "payload_fingerprint": "4" * 64,
                        "payload": '{"version":1,"ordinal":"high"}',
                    },
                )
            ).one()
            return str(row[0]), int(row[1])

    async def _read_snapshot():
        async with AsyncSession(migrated_engine) as reader, reader.begin():
            return await get_cache_target_snapshot(
                reader,
                external_system=system,
                limit=10,
            )

    high_task: asyncio.Task[tuple[str, int]] | None = None
    snapshot_task: asyncio.Task[Any] | None = None
    try:
        high_task = asyncio.create_task(_append_high_result())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(high_task), timeout=0.2)
        snapshot_task = asyncio.create_task(_read_snapshot())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(snapshot_task), timeout=0.2)

        await low_tx.commit()
        high_event_id, high_relay_order = await asyncio.wait_for(high_task, timeout=5)
        page = await asyncio.wait_for(snapshot_task, timeout=5)
    finally:
        pending_tasks = tuple(
            task
            for task in (high_task, snapshot_task)
            if task is not None and not task.done()
        )
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        if low_tx.is_active:
            await low_tx.rollback()
        await low_writer.close()

    assert low_state.relay_order < high_relay_order
    assert high_relay_order != 1
    assert page.high_watermark_cursor == cache_target_event_cursor(
        high_relay_order
    )
    assert {item.target_key for item in page.items} == {"target-a", "target-b"}
    async with AsyncSession(migrated_engine) as observer, observer.begin():
        persisted_orders = (
            await observer.execute(
                text(
                    "SELECT material.safe_high_watermark_relay_order, "
                    "material.material_high_watermark_relay_order "
                    "FROM ops.poi_cache_target_snapshots AS receipt "
                    "JOIN ops.poi_cache_target_snapshot_materials AS material "
                    "ON material.material_id = receipt.material_id "
                    "WHERE receipt.snapshot_id = CAST(:snapshot_id AS uuid)"
                ),
                {"snapshot_id": page.snapshot_id},
            )
        ).one()
        missing_state = await observer.scalar(
            text(
                "SELECT count(*) "
                "FROM ops.poi_cache_target_outbox_events AS event "
                "WHERE event.external_system = :external_system "
                "AND event.event_type = 'cache_target.state_applied' "
                "AND event.relay_order <= :high_watermark "
                "AND NOT EXISTS ("
                "SELECT 1 "
                "FROM ops.poi_cache_target_snapshot_material_items AS item "
                "JOIN ops.poi_cache_target_snapshots AS receipt "
                "ON receipt.material_id = item.material_id "
                "WHERE receipt.snapshot_id = CAST(:snapshot_id AS uuid) "
                "AND item.target_key = event.target_key)"
            ),
            {
                "external_system": system,
                "high_watermark": high_relay_order,
                "snapshot_id": page.snapshot_id,
            },
        )
    assert tuple(persisted_orders) == (
        high_relay_order,
        low_state.relay_order,
    )
    assert missing_state == 0

    async with AsyncSession(migrated_engine) as writer, writer.begin():
        later = await result_event_repo._append_result_event(  # pyright: ignore[reportPrivateUsage]
            writer,
            member=member,
            event_type="cache_target.links_reconciled",
            payload={"version": 1, "ordinal": "later"},
            refresh_request_id=None,
            job_id=None,
        )
    async with AsyncSession(migrated_engine) as reader, reader.begin():
        reused = await get_cache_target_snapshot(
            reader,
            external_system=system,
            limit=10,
        )
        replay_ids = set(
            (
                await reader.execute(
                    text(
                        "SELECT event_id::text "
                        "FROM ops.poi_cache_target_outbox_events "
                        "WHERE external_system = :external_system "
                        "AND relay_order > :high_watermark"
                    ),
                    {
                        "external_system": system,
                        "high_watermark": high_relay_order,
                    },
                )
            ).scalars()
        )
    # 재사용은 material을 공유하고 **receipt는 새로 만든다**(0230). snapshot_id는 이제
    # "누가 언제 받아갔는가"이지 "무엇을 고정했는가"가 아니다 — 같은 material인지는
    # root/count로 본다. replay cursor는 material이 들고 있으므로 그대로 같다.
    assert reused.snapshot_id != page.snapshot_id
    assert (reused.merkle_root, reused.count) == (page.merkle_root, page.count)
    assert reused.high_watermark_cursor == page.high_watermark_cursor
    assert high_event_id != later.event_id
    assert replay_ids == {later.event_id}


@pytest.mark.integration
async def test_refresh_capture_locks_stream_before_head_and_avoids_source_deadlock(
    migrated_engine: AsyncEngine,
) -> None:
    system = "refresh-lock-order-test"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        initial = await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="target-a",
            event_id="9b100000-0000-4000-8000-000000000011",
            idempotency_key="9b200000-0000-4000-8000-000000000011",
        )
        request = await enqueue_feature_update_request(
            setup,
            scope={
                "type": "cache_target_keys",
                "external_system": system,
                "target_keys": ["target-a"],
            },
            dataset_memberships=[await _canonical_membership(setup)],
        )
    assert initial.target is not None
    assert request is not None
    request_id = request.request_id
    captured = asyncio.Event()
    allow_append = asyncio.Event()

    async def _capture_and_append():
        async with AsyncSession(migrated_engine) as refresh, refresh.begin():
            members = await capture_cache_target_refresh_members_by_keys(
                refresh,
                request_id=request_id,
                external_system=system,
                target_keys=("target-a",),
            )
            captured.set()
            await allow_append.wait()
            events = await append_cache_target_refresh_status_events(
                refresh,
                request_id=request_id,
                job_id=request.job_id,
                status="running",
            )
            return members, events

    async def _update_source():
        await captured.wait()
        async with AsyncSession(migrated_engine) as source, source.begin():
            return await apply_cache_target_source(
                source,
                consumer_id=_CONSUMER,
                source_event_id="9b100000-0000-4000-8000-000000000012",
                idempotency_key="9b200000-0000-4000-8000-000000000012",
                external_system=system,
                target_key="target-a",
                restore_epoch=1,
                source_generation=2,
                source=make_active_cache_target_source(
                    lon="126.978",
                    lat="37.5665",
                    radius_km="6",
                    update_enabled=True,
                ),
                occurred_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC),
                create_only=False,
                expected_target_id=initial.target.target_id,
                expected_lock_version=initial.target.lock_version,
            )

    refresh_task: asyncio.Task[Any] | None = None
    source_task: asyncio.Task[Any] | None = None
    try:
        refresh_task = asyncio.create_task(_capture_and_append())
        await asyncio.wait_for(captured.wait(), timeout=5)
        source_task = asyncio.create_task(_update_source())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(source_task), timeout=0.2)
        allow_append.set()
        members, events = await asyncio.wait_for(refresh_task, timeout=5)
        updated = await asyncio.wait_for(source_task, timeout=5)
    finally:
        allow_append.set()
        pending_tasks = tuple(
            task
            for task in (refresh_task, source_task)
            if task is not None and not task.done()
        )
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

    assert len(members) == len(events) == 1
    assert events[0].relay_order < updated.relay_order


@pytest.mark.integration
async def test_generic_snapshot_reuse_ignores_nonmaterial_outbox_tail(
    migrated_session: AsyncSession,
) -> None:
    system = "snapshot-material-watermark-test"
    applied = await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-a",
        event_id="9e000000-0000-4000-8000-000000000011",
        idempotency_key="9f000000-0000-4000-8000-000000000011",
    )
    first = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=10,
    )
    nonmaterial_relay_order = await migrated_session.scalar(
        text(
            "INSERT INTO ops.poi_cache_target_outbox_events ("
            "event_id, event_type, event_scope, external_system, target_key, "
            "target_id, restore_epoch, source_generation, target_sequence, "
            "source_payload_fingerprint, payload_fingerprint, payload) VALUES ("
            "'a0000000-0000-4000-8000-000000000011', "
            "'cache_target.links_reconciled', 'target', :external_system, "
            "'target-a', CAST(:target_id AS uuid), 1, 1, 2, :source_fingerprint, "
            ":payload_fingerprint, CAST('{}' AS jsonb)) RETURNING relay_order"
        ),
        {
            "external_system": system,
            "target_id": applied.target_id,
            "source_fingerprint": applied.source_payload_fingerprint,
            "payload_fingerprint": "4" * 64,
        },
    )
    assert nonmaterial_relay_order is not None
    await migrated_session.execute(
        text(
            "UPDATE ops.poi_cache_target_source_heads SET target_sequence = 2 "
            "WHERE external_system = :external_system AND target_key = 'target-a'"
        ),
        {"external_system": system},
    )

    reused = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=10,
    )
    # 재사용은 material을 공유하고 **receipt는 새로 만든다**(0230). snapshot_id는 이제
    # "누가 언제 받아갔는가"이지 "무엇을 고정했는가"가 아니다 — 같은 material인지는
    # root/count로 본다. replay cursor는 material이 들고 있으므로 그대로 같다.
    assert reused.snapshot_id != first.snapshot_id
    assert (reused.merkle_root, reused.count) == (first.merkle_root, first.count)
    assert reused.high_watermark_cursor == first.high_watermark_cursor
    assert reused.high_watermark_cursor != cache_target_event_cursor(
        int(nonmaterial_relay_order)
    )

    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-b",
        event_id="9e000000-0000-4000-8000-000000000012",
        idempotency_key="9f000000-0000-4000-8000-000000000012",
    )
    fresh = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=10,
    )
    assert fresh.snapshot_id != first.snapshot_id
    assert fresh.count == 2
    await migrated_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        str(line)
        for line in (
            await migrated_session.execute(
                text(
                    "EXPLAIN (COSTS OFF) SELECT max(event.relay_order) "
                    "FROM ops.poi_cache_target_outbox_events AS event "
                    "WHERE event.external_system = :external_system "
                    "AND event.event_type = 'cache_target.state_applied'"
                ),
                {"external_system": system},
            )
        ).scalars()
    )
    assert "idx_cache_target_outbox_state_material_order" in plan


async def _seed_snapshot_material(
    session: AsyncSession,
    *,
    material_id: str,
    external_system: str,
    material_order: int,
    item_count: int,
    merkle_root: str,
) -> None:
    """GC/용량 경계용 material을 직접 심는다.

    같은 `(external_system, restore_epoch, material_order)`를 두 번 주면 살아 있는
    material은 identity마다 하나라는 partial unique에 걸린다(0230). 여러 개가 필요한
    테스트는 `material_order`를 갈라야 한다.
    """

    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_materials ("
            "material_id, external_system, restore_epoch, "
            "material_high_watermark_relay_order, safe_high_watermark_relay_order, "
            "item_count, merkle_root, materialized_at) VALUES ("
            "CAST(:material_id AS uuid), :external_system, 1, :material_order, "
            ":material_order, :item_count, :merkle_root, "
            "now() - interval '2 hours')"
        ),
        {
            "material_id": material_id,
            "external_system": external_system,
            "material_order": material_order,
            "item_count": item_count,
            "merkle_root": merkle_root,
        },
    )


async def _seed_snapshot_receipt(
    session: AsyncSession,
    *,
    snapshot_id: str,
    material_id: str,
    external_system: str,
    created_at: str,
    expires_at: str,
    receipt_kind: str = "generic",
) -> None:
    """material 하나에 receipt를 붙인다. 시각은 SQL 식으로 받는다."""

    await session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshots ("
            "snapshot_id, material_id, receipt_kind, external_system, "
            "created_at, expires_at) VALUES ("
            "CAST(:snapshot_id AS uuid), CAST(:material_id AS uuid), "
            ":receipt_kind, :external_system, "
            f"{created_at}, {expires_at})"
        ),
        {
            "snapshot_id": snapshot_id,
            "material_id": material_id,
            "receipt_kind": receipt_kind,
            "external_system": external_system,
        },
    )


@pytest.mark.integration
async def test_generic_snapshot_gc_is_bounded_and_preserves_referenced_snapshot(
    migrated_session: AsyncSession,
) -> None:
    system = "snapshot-gc-test"
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-a",
        event_id="95000000-0000-4000-8000-000000000001",
        idempotency_key="96000000-0000-4000-8000-000000000001",
    )
    current = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=1,
    )
    expired_id = "97000000-0000-4000-8000-000000000001"
    referenced_id = "97000000-0000-4000-8000-000000000002"
    # 두 receipt는 서로 다른 material을 갖는다. 같은 identity를 주면 살아 있는
    # material은 identity마다 하나라는 partial unique에 걸린다(0230).
    expired_material = "97100000-0000-4000-8000-000000000001"
    referenced_material = "97100000-0000-4000-8000-000000000002"
    await _seed_snapshot_material(
        migrated_session,
        material_id=expired_material,
        external_system=system,
        material_order=0,
        item_count=1001,
        merkle_root="c" * 64,
    )
    await _seed_snapshot_material(
        migrated_session,
        material_id=referenced_material,
        external_system=system,
        material_order=1,
        item_count=1,
        merkle_root="d" * 64,
    )
    await _seed_snapshot_receipt(
        migrated_session,
        snapshot_id=expired_id,
        material_id=expired_material,
        external_system=system,
        created_at="now() - interval '2 hours'",
        expires_at="now() - interval '1 hour'",
    )
    await _seed_snapshot_receipt(
        migrated_session,
        snapshot_id=referenced_id,
        material_id=referenced_material,
        external_system=system,
        created_at="now() - interval '2 hours'",
        expires_at="now() - interval '1 hour'",
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_material_items ("
            "material_id, row_number, target_key, state, "
            "source_generation, source_payload_fingerprint) "
            "SELECT CAST(:material_id AS uuid), value, "
            "'expired-' || value::text, 'active', 1, :fingerprint "
            "FROM generate_series(1, 1001) AS value"
        ),
        {"material_id": expired_material, "fingerprint": "e" * 64},
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_material_items ("
            "material_id, row_number, target_key, state, "
            "source_generation, source_payload_fingerprint) VALUES ("
            "CAST(:material_id AS uuid), 1, 'referenced', 'active', 1, :fingerprint)"
        ),
        {"material_id": referenced_material, "fingerprint": "f" * 64},
    )
    command_id = await _reconciliation_command(
        migrated_session,
        key="98000000-0000-4000-8000-000000000001",
        operation="snapshot.gc.reference",
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_reconciliation_requests ("
            "request_id, external_system, command_id, reason, status, "
            "phase_version, snapshot_id, expected_merkle_root, "
            "actual_merkle_root, started_at, completed_at) VALUES ("
            "CAST(:request_id AS uuid), :external_system, :command_id, "
            "'preserve terminal snapshot', 'succeeded', 3, "
            "CAST(:snapshot_id AS uuid), :merkle_root, :merkle_root, now(), now())"
        ),
        {
            "request_id": "99000000-0000-4000-8000-000000000001",
            "external_system": system,
            "command_id": command_id,
            "snapshot_id": referenced_id,
            "merkle_root": "d" * 64,
        },
    )
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-b",
        event_id="95000000-0000-4000-8000-000000000002",
        idempotency_key="96000000-0000-4000-8000-000000000002",
    )

    first_gc = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=1,
    )
    assert first_gc.snapshot_id != current.snapshot_id
    remaining = await migrated_session.scalar(
        text(
            "SELECT count(*) FROM ops.poi_cache_target_snapshot_material_items "
            "WHERE material_id = CAST(:material_id AS uuid)"
        ),
        {"material_id": expired_material},
    )
    assert remaining == 1
    assert await migrated_session.scalar(
        text(
            "SELECT count(*) FROM ops.poi_cache_target_snapshot_material_items "
            "WHERE material_id = CAST(:material_id AS uuid)"
        ),
        {"material_id": referenced_material},
    ) == 1

    background_gc = await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        item_limit=1_000,
        header_limit=100,
    )
    assert background_gc.external_system == system
    assert background_gc.deleted_items == 1
    # receipt는 앞선 snapshot 생성이 이미 지웠다. 0230 전에는 header 삭제에
    # "item이 비어 있을 것"이라는 조건이 붙어 있어 여기까지 밀렸다 — 이제 item은
    # material에 달려 있으므로 receipt는 만료 즉시 지운다.
    assert background_gc.deleted_headers == 0
    assert background_gc.compacted_materials == 0
    assert await migrated_session.scalar(
        text(
            "SELECT count(*) FROM ops.poi_cache_target_snapshot_materials "
            "WHERE material_id = CAST(:material_id AS uuid)"
        ),
        {"material_id": expired_material},
    ) == 0
    assert await migrated_session.scalar(
        text(
            "SELECT count(*) FROM ops.poi_cache_target_snapshots "
            "WHERE snapshot_id = CAST(:snapshot_id AS uuid)"
        ),
        {"snapshot_id": expired_id},
    ) == 0
    assert await migrated_session.scalar(
        text(
            "SELECT count(*) FROM ops.poi_cache_target_snapshots "
            "WHERE snapshot_id = CAST(:snapshot_id AS uuid)"
        ),
        {"snapshot_id": referenced_id},
    ) == 1


@pytest.mark.integration
async def test_generic_snapshot_capacity_excludes_expired_and_referenced_copies(
    migrated_session: AsyncSession,
) -> None:
    system = "snapshot-capacity-test"
    before = await observe_expired_cache_target_snapshot_backlog(migrated_session)
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-a",
        event_id="a1000000-0000-4000-8000-000000000011",
        idempotency_key="a2000000-0000-4000-8000-000000000011",
    )
    unreferenced_id = "a3000000-0000-4000-8000-000000000011"
    expired_id = "a3000000-0000-4000-8000-000000000012"
    referenced_id = "a3000000-0000-4000-8000-000000000013"
    # 상한이 세는 것은 **살아 있는 material** 수다. 셋에 같은 identity를 주면 material
    # 하나가 되어 상한을 시험하지 못한다 — material order를 갈라 셋으로 만든다.
    materials = {
        unreferenced_id: ("a3100000-0000-4000-8000-000000000011", 0),
        expired_id: ("a3100000-0000-4000-8000-000000000012", 1),
        referenced_id: ("a3100000-0000-4000-8000-000000000013", 2),
    }
    for snapshot_id, (material_id, material_order) in materials.items():
        await _seed_snapshot_material(
            migrated_session,
            material_id=material_id,
            external_system=system,
            material_order=material_order,
            item_count=0,
            merkle_root=snapshot_merkle_root([]),
        )
        expired = snapshot_id == expired_id
        await _seed_snapshot_receipt(
            migrated_session,
            snapshot_id=snapshot_id,
            material_id=material_id,
            external_system=system,
            created_at=(
                "now() - interval '3 hours'"
                if expired
                else "now() - interval '10 minutes'"
            ),
            expires_at=(
                "now() - interval '1 hour'"
                if expired
                else "now() + interval '90 minutes'"
            ),
        )
    command_id = await _reconciliation_command(
        migrated_session,
        key="a4000000-0000-4000-8000-000000000011",
        operation="snapshot.capacity.reference",
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_reconciliation_requests ("
            "request_id, external_system, command_id, reason, status, "
            "phase_version, snapshot_id, expected_merkle_root, "
            "actual_merkle_root, started_at, completed_at) VALUES ("
            "CAST(:request_id AS uuid), :external_system, :command_id, "
            "'capacity exclusion regression', 'succeeded', 3, "
            "CAST(:snapshot_id AS uuid), :empty_root, :empty_root, now(), now())"
        ),
        {
            "request_id": "a5000000-0000-4000-8000-000000000011",
            "external_system": system,
            "command_id": command_id,
            "snapshot_id": referenced_id,
            "empty_root": snapshot_merkle_root([]),
        },
    )

    created = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=10,
    )
    assert created.snapshot_id not in {unreferenced_id, expired_id, referenced_id}
    assert await migrated_session.scalar(
        text(
            "SELECT count(*) FROM ops.poi_cache_target_snapshots "
            "WHERE snapshot_id = CAST(:snapshot_id AS uuid)"
        ),
        {"snapshot_id": expired_id},
    ) == 0

    inventory = await observe_expired_cache_target_snapshot_backlog(migrated_session)
    assert inventory.remaining_headers == before.remaining_headers
    assert inventory.total_headers == before.total_headers + 3
    assert inventory.total_items == before.total_items + 1
    assert (
        inventory.unexpired_unreferenced_headers
        == before.unexpired_unreferenced_headers + 2
    )
    assert (
        inventory.unexpired_unreferenced_items
        == before.unexpired_unreferenced_items + 1
    )
    assert inventory.referenced_headers == before.referenced_headers + 1
    assert inventory.referenced_items == before.referenced_items

    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-b",
        event_id="a1000000-0000-4000-8000-000000000012",
        idempotency_key="a2000000-0000-4000-8000-000000000012",
    )
    with pytest.raises(CacheTargetStreamConflict) as capacity:
        await get_cache_target_snapshot(
            migrated_session,
            external_system=system,
            limit=10,
        )
    assert capacity.value.code == "snapshot_capacity_exceeded"
    assert capacity.value.current["snapshot_count"] == 2
    assert capacity.value.current["snapshot_limit"] == 2
    assert 1 <= capacity.value.current["retry_after_seconds"] <= 7_200


@pytest.mark.integration
async def test_background_snapshot_gc_round_robins_systems_and_observes_once(
    migrated_session: AsyncSession,
) -> None:
    first_system = "snapshot-background-gc-a"
    second_system = "snapshot-background-gc-z"
    await _apply_snapshot_source(
        migrated_session,
        external_system=first_system,
        target_key="target-a",
        event_id="a1000000-0000-4000-8000-000000000001",
        idempotency_key="a2000000-0000-4000-8000-000000000001",
    )
    await _apply_snapshot_source(
        migrated_session,
        external_system=second_system,
        target_key="target-z",
        event_id="a1000000-0000-4000-8000-000000000002",
        idempotency_key="a2000000-0000-4000-8000-000000000002",
    )
    first_material = "a3100000-0000-4000-8000-000000000001"
    second_material = "a3100000-0000-4000-8000-000000000002"
    await _seed_snapshot_material(
        migrated_session,
        material_id=first_material,
        external_system=first_system,
        material_order=0,
        item_count=2,
        merkle_root="1" * 64,
    )
    await _seed_snapshot_material(
        migrated_session,
        material_id=second_material,
        external_system=second_system,
        material_order=0,
        item_count=1,
        merkle_root="2" * 64,
    )
    await _seed_snapshot_receipt(
        migrated_session,
        snapshot_id="a3000000-0000-4000-8000-000000000001",
        material_id=first_material,
        external_system=first_system,
        created_at="now() - interval '2 hours'",
        expires_at="now() - interval '1 hour'",
    )
    await _seed_snapshot_receipt(
        migrated_session,
        snapshot_id="a3000000-0000-4000-8000-000000000002",
        material_id=second_material,
        external_system=second_system,
        created_at="now() - interval '2 hours'",
        expires_at="now() - interval '1 hour'",
    )
    await migrated_session.execute(
        text(
            "INSERT INTO ops.poi_cache_target_snapshot_material_items ("
            "material_id, row_number, target_key, state, "
            "source_generation, source_payload_fingerprint) VALUES "
            "(CAST(:first_material AS uuid), 1, 'a-1', 'active', 1, :fingerprint), "
            "(CAST(:first_material AS uuid), 2, 'a-2', 'active', 1, :fingerprint), "
            "(CAST(:second_material AS uuid), 1, 'z-1', 'active', 1, :fingerprint)"
        ),
        {
            "first_material": first_material,
            "second_material": second_material,
            "fingerprint": "3" * 64,
        },
    )

    first = await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        item_limit=1,
        header_limit=1,
    )
    second = await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        after_external_system=first.external_system,
        item_limit=1,
        header_limit=1,
    )
    wrapped = await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        after_external_system=second.external_system,
        item_limit=1,
        header_limit=1,
    )
    backlog = await observe_expired_cache_target_snapshot_backlog(migrated_session)

    assert (first.external_system, second.external_system, wrapped.external_system) == (
        first_system,
        second_system,
        first_system,
    )
    # 0230 전에는 header 삭제가 "item이 비어 있을 것"을 요구해 item보다 한 batch
    # 늦었다. 이제 receipt는 만료 즉시 지우고, item은 orphan이 된 material에서 지운다.
    assert (first.deleted_items, first.deleted_headers, first.has_more) == (1, 1, True)
    assert (second.deleted_items, second.deleted_headers, second.has_more) == (1, 1, True)
    # 세 batch로 전부 비워진다. 0230 전에는 header 삭제가 한 batch 늦어 여기서
    # backlog가 남았다.
    assert (wrapped.deleted_items, wrapped.deleted_headers, wrapped.has_more) == (
        1,
        0,
        False,
    )
    assert (first.compacted_materials, second.compacted_materials) == (0, 0)
    assert backlog.remaining_items == backlog.remaining_headers == 0
    assert backlog.snapshot_table_bytes > 0
    assert backlog.snapshot_index_bytes > 0
    assert backlog.snapshot_dead_tuples >= 0
    assert (
        backlog.snapshot_vacuum_lag_seconds is None
        or backlog.snapshot_vacuum_lag_seconds >= 0
    )


@pytest.mark.integration
async def test_terminal_material_compaction_drains_items_and_serves_typed_410(
    migrated_session: AsyncSession,
) -> None:
    """보존 기간을 넘긴 terminal reconciliation의 item만 되찾고 증거는 남긴다.

    보는 것 넷이다.

    1. 후보가 아닌 material(보존 기간 안, 또는 미만료 receipt 보유)은 건드리지 않는다.
    2. 후보는 표시되고 item이 빈다.
    3. **receipt와 material row는 남는다** — root/count가 감사 증거다.
    4. 그 receipt를 page하면 typed `410 snapshot_material_compacted`이고, 본문에
       보존된 snapshot_id/item_count/merkle_root/compacted_at이 실린다.
    """

    system = "snapshot-compaction-test"
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-a",
        event_id="9c000000-0000-4000-8000-000000000001",
        idempotency_key="9d000000-0000-4000-8000-000000000001",
    )

    old_material = "9e100000-0000-4000-8000-000000000001"
    fresh_material = "9e100000-0000-4000-8000-000000000002"
    live_material = "9e100000-0000-4000-8000-000000000003"
    old_receipt = "9e000000-0000-4000-8000-000000000001"
    fresh_receipt = "9e000000-0000-4000-8000-000000000002"
    live_receipt = "9e000000-0000-4000-8000-000000000003"
    root = "a" * 64

    for index, (material_id, receipt_id) in enumerate(
        (
            (old_material, old_receipt),
            (fresh_material, fresh_receipt),
            (live_material, live_receipt),
        )
    ):
        await _seed_snapshot_material(
            migrated_session,
            material_id=material_id,
            external_system=system,
            material_order=index,
            item_count=1,
            merkle_root=root,
        )
        await _seed_snapshot_receipt(
            migrated_session,
            snapshot_id=receipt_id,
            material_id=material_id,
            external_system=system,
            created_at="now() - interval '2 hours'",
            # `live`만 아직 만료되지 않았다 — 그것만으로 후보에서 빠져야 한다.
            expires_at=(
                "now() + interval '2 hours'"
                if material_id == live_material
                else "now() - interval '1 hour'"
            ),
            receipt_kind="reconciliation",
        )
        await migrated_session.execute(
            text(
                "INSERT INTO ops.poi_cache_target_snapshot_material_items ("
                "material_id, row_number, target_key, state, "
                "source_generation, source_payload_fingerprint) VALUES ("
                "CAST(:material_id AS uuid), 1, 'kept', 'active', 1, :fingerprint)"
            ),
            {"material_id": material_id, "fingerprint": "b" * 64},
        )

    # 셋 다 terminal reconciliation이 참조한다. 다른 것은 `completed_at`뿐이다.
    for index, (receipt_id, completed) in enumerate(
        (
            (old_receipt, "now() - interval '40 days'"),
            (fresh_receipt, "now() - interval '1 hour'"),
            (live_receipt, "now() - interval '40 days'"),
        )
    ):
        command_id = await _reconciliation_command(
            migrated_session,
            key=f"9f000000-0000-4000-8000-00000000000{index + 1}",
            operation="snapshot.compaction.retention",
        )
        await migrated_session.execute(
            text(
                "INSERT INTO ops.poi_cache_target_reconciliation_requests ("
                "request_id, external_system, command_id, reason, status, "
                "phase_version, snapshot_id, expected_merkle_root, "
                "actual_merkle_root, started_at, completed_at) VALUES ("
                "CAST(:request_id AS uuid), :external_system, :command_id, "
                "'compaction retention', 'succeeded', 3, "
                "CAST(:snapshot_id AS uuid), :root, :root, "
                f"now() - interval '41 days', {completed})"
            ),
            {
                "request_id": f"9f100000-0000-4000-8000-00000000000{index + 1}",
                "external_system": system,
                "command_id": command_id,
                "snapshot_id": receipt_id,
                "root": root,
            },
        )

    batch = await prune_expired_cache_target_snapshots_batch(
        migrated_session,
        item_limit=1_000,
        header_limit=100,
        compaction_retention_seconds=30 * 24 * 60 * 60,
    )

    assert batch.external_system == system
    # 후보는 하나뿐이다. `fresh`는 보존 기간 안이고 `live`는 미만료 receipt를 갖는다.
    assert batch.compacted_materials == 1
    assert batch.deleted_items == 1
    # reconciliation이 참조하는 receipt는 만료돼도 지우지 않는다 — 감사 증거다.
    assert batch.deleted_headers == 0

    compacted = (
        await migrated_session.execute(
            text(
                "SELECT material_id FROM ops.poi_cache_target_snapshot_materials "
                "WHERE external_system = :system AND compacted_at IS NOT NULL"
            ),
            {"system": system},
        )
    ).scalars().all()
    assert [str(value) for value in compacted] == [old_material]

    surviving_items = (
        await migrated_session.execute(
            text(
                "SELECT item.material_id, count(*) "
                "FROM ops.poi_cache_target_snapshot_material_items AS item "
                "JOIN ops.poi_cache_target_snapshot_materials AS material "
                "ON material.material_id = item.material_id "
                "WHERE material.external_system = :system "
                "GROUP BY item.material_id"
            ),
            {"system": system},
        )
    ).all()
    assert {str(row[0]) for row in surviving_items} == {fresh_material, live_material}

    # 증거는 남는다.
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_snapshots "
                "WHERE snapshot_id = CAST(:snapshot_id AS uuid)"
            ),
            {"snapshot_id": old_receipt},
        )
        == 1
    )
    preserved = (
        await migrated_session.execute(
            text(
                "SELECT item_count, merkle_root "
                "FROM ops.poi_cache_target_snapshot_materials "
                "WHERE material_id = CAST(:material_id AS uuid)"
            ),
            {"material_id": old_material},
        )
    ).one()
    assert (int(preserved.item_count), str(preserved.merkle_root)) == (1, root)

    with pytest.raises(CacheTargetStreamConflict) as compacted_page:
        await get_cache_target_snapshot(
            migrated_session,
            external_system=system,
            limit=10,
            cursor=snapshot_repo._snapshot_cursor(old_receipt, 0),  # pyright: ignore[reportPrivateUsage]
        )
    assert compacted_page.value.code == "snapshot_material_compacted"
    current = compacted_page.value.current
    assert current is not None
    assert current["snapshot_id"] == old_receipt
    assert current["item_count"] == 1
    assert current["merkle_root"] == root
    assert isinstance(current["compacted_at"], str)


@pytest.mark.integration
async def test_cursor_header_share_lock_makes_direct_item_gc_skip_snapshot(
    migrated_engine: AsyncEngine,
) -> None:
    system = "snapshot-reader-gc-lock-test"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="target-a",
            event_id="9a000000-0000-4000-8000-000000000011",
            idempotency_key="9b000000-0000-4000-8000-000000000011",
        )
        await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="target-b",
            event_id="9a000000-0000-4000-8000-000000000012",
            idempotency_key="9b000000-0000-4000-8000-000000000012",
        )
    async with AsyncSession(migrated_engine) as creator, creator.begin():
        snapshot = await get_cache_target_snapshot(
            creator,
            external_system=system,
            limit=1,
        )
    async with AsyncSession(migrated_engine) as expire, expire.begin():
        await expire.execute(text("SET LOCAL session_replication_role = replica"))
        await expire.execute(
            text(
                "UPDATE ops.poi_cache_target_snapshots "
                "SET expires_at = clock_timestamp() + interval '1 second' "
                "WHERE snapshot_id = CAST(:snapshot_id AS uuid)"
            ),
            {"snapshot_id": snapshot.snapshot_id},
        )

    async with AsyncSession(migrated_engine) as reader, reader.begin():
        header = (
            await reader.execute(
                text(snapshot_repo._GET_SNAPSHOT_SQL),  # pyright: ignore[reportPrivateUsage]
                {"snapshot_id": snapshot.snapshot_id},
            )
        ).one()
        assert bool(header.valid)
        await asyncio.sleep(1.2)

        async with AsyncSession(migrated_engine) as writer, writer.begin():
            await _apply_snapshot_source(
                writer,
                external_system=system,
                target_key="target-c",
                event_id="9a000000-0000-4000-8000-000000000013",
                idempotency_key="9b000000-0000-4000-8000-000000000013",
            )
        async with AsyncSession(migrated_engine) as pruner, pruner.begin():
            await get_cache_target_snapshot(
                pruner,
                external_system=system,
                limit=1,
            )
        item_rows = (
            await reader.execute(
                text(snapshot_repo._GET_SNAPSHOT_ITEMS_SQL),  # pyright: ignore[reportPrivateUsage]
                {
                    "external_system": system,
                    "material_id": header.material_id,
                    "after_row_number": 0,
                    "limit": 10,
                },
            )
        ).all()
        assert len(item_rows) == 2

    async with AsyncSession(migrated_engine) as writer, writer.begin():
        await _apply_snapshot_source(
            writer,
            external_system=system,
            target_key="target-d",
            event_id="9a000000-0000-4000-8000-000000000014",
            idempotency_key="9b000000-0000-4000-8000-000000000014",
        )
    async with AsyncSession(migrated_engine) as pruner, pruner.begin():
        await get_cache_target_snapshot(
            pruner,
            external_system=system,
            limit=1,
        )
    async with AsyncSession(migrated_engine) as probe:
        assert await probe.scalar(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_snapshots "
                "WHERE snapshot_id = CAST(:snapshot_id AS uuid)"
            ),
            {"snapshot_id": snapshot.snapshot_id},
        ) == 0


@pytest.mark.integration
async def test_reconciliation_discovery_pages_only_request_bound_snapshot(
    migrated_session: AsyncSession,
) -> None:
    system = "reconciliation-discovery-test"
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-a",
        event_id="9a000000-0000-0000-0000-000000000001",
        idempotency_key="9b000000-0000-0000-0000-000000000001",
    )
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-b",
        event_id="9a000000-0000-0000-0000-000000000002",
        idempotency_key="9b000000-0000-0000-0000-000000000002",
    )
    command_id = await _reconciliation_command(
        migrated_session,
        key="9c000000-0000-0000-0000-000000000001",
    )
    request = await request_cache_target_reconciliation(
        migrated_session,
        command_id=command_id,
        external_system=system,
        reason="discover fixed snapshot",
    )
    discovery = await get_cache_target_stream_discovery(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
    )
    assert discovery is not None
    active = discovery.active_reconciliation
    assert active is not None
    assert active.request_id == request.request_id
    assert active.snapshot_id == request.snapshot_id
    assert active.count == 2
    assert active.merkle_root == request.expected_merkle_root

    generic = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=1,
    )
    assert generic.snapshot_id != active.snapshot_id
    assert generic.next_cursor is not None
    first = await get_cache_target_reconciliation_snapshot(
        migrated_session,
        request_id=active.request_id,
        consumer_id=_CONSUMER,
        limit=1,
    )
    assert first.snapshot_id == active.snapshot_id
    assert first.next_cursor is not None
    second = await get_cache_target_reconciliation_snapshot(
        migrated_session,
        request_id=active.request_id,
        consumer_id=_CONSUMER,
        limit=1,
        cursor=first.next_cursor,
    )
    assert [first.items[0].target_key, second.items[0].target_key] == [
        "target-a",
        "target-b",
    ]
    with pytest.raises(CacheTargetStreamConflict) as wrong_snapshot_cursor:
        await get_cache_target_reconciliation_snapshot(
            migrated_session,
            request_id=active.request_id,
            consumer_id=_CONSUMER,
            limit=1,
            cursor=generic.next_cursor,
        )
    assert wrong_snapshot_cursor.value.code == "reconciliation_precondition_failed"
    with pytest.raises(CacheTargetStreamConflict) as wrong_epoch:
        await complete_cache_target_reconciliation(
            migrated_session,
            request_id=active.request_id,
            external_system=system,
            consumer_id=_CONSUMER,
            snapshot_id=active.snapshot_id,
            expected_restore_epoch=active.restore_epoch + 1,
            actual_merkle_root=active.merkle_root,
        )
    assert wrong_epoch.value.code == "reconciliation_precondition_failed"
    with pytest.raises(CacheTargetStreamConflict) as wrong_snapshot:
        await complete_cache_target_reconciliation(
            migrated_session,
            request_id=active.request_id,
            external_system=system,
            consumer_id=_CONSUMER,
            snapshot_id=generic.snapshot_id,
            expected_restore_epoch=active.restore_epoch,
            actual_merkle_root=active.merkle_root,
        )
    assert wrong_snapshot.value.code == "reconciliation_precondition_failed"
    with pytest.raises(CacheTargetStreamConflict) as wrong_request:
        await complete_cache_target_reconciliation(
            migrated_session,
            request_id="9d000000-0000-0000-0000-000000000001",
            external_system=system,
            consumer_id=_CONSUMER,
            snapshot_id=active.snapshot_id,
            expected_restore_epoch=active.restore_epoch,
            actual_merkle_root=active.merkle_root,
        )
    assert wrong_request.value.code == "reconciliation_precondition_failed"
    with pytest.raises(CacheTargetStreamConflict) as wrong_consumer:
        await get_cache_target_reconciliation_snapshot(
            migrated_session,
            request_id=active.request_id,
            consumer_id="other-consumer",
        )
    assert wrong_consumer.value.code == "consumer_mismatch"

    another_command = await _reconciliation_command(
        migrated_session,
        key="9c000000-0000-0000-0000-000000000002",
    )
    with pytest.raises(CacheTargetStreamConflict) as already_active:
        await request_cache_target_reconciliation(
            migrated_session,
            command_id=another_command,
            external_system=system,
            reason="must not replace active request",
        )
    assert already_active.value.code == "reconciliation_active"
    completed = await complete_cache_target_reconciliation(
        migrated_session,
        request_id=active.request_id,
        external_system=system,
        consumer_id=_CONSUMER,
        snapshot_id=active.snapshot_id,
        expected_restore_epoch=active.restore_epoch,
        actual_merkle_root=active.merkle_root,
    )
    assert completed.status == "succeeded"
    resumed = await get_cache_target_stream_discovery(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
    )
    assert resumed is not None
    assert resumed.active_reconciliation is None
    assert resumed.consumer_enabled
    assert resumed.status == "ready"


async def _reconciliation_command(
    session: AsyncSession,
    *,
    key: str,
    operation: str = "admin.cache-target-reconciliation.request",
) -> int:
    fingerprint = canonical_domain_command_fingerprint({"key": key})
    claim = await create_domain_command_claim(
        session,
        actor="admin:test",
        operation=operation,
        idempotency_key=key,
        request_fingerprint=fingerprint,
    )
    return claim.command_id


async def _resume_stream_after_dead_letter_replay(
    session: AsyncSession,
    *,
    key: str,
):
    """dead-letter replay 뒤의 consumer 재개는 checksum reconciliation만 허용한다."""

    command_id = await _reconciliation_command(session, key=key)
    request = await request_cache_target_reconciliation(
        session,
        command_id=command_id,
        external_system=_SYSTEM,
        reason="dead-letter replay resume",
    )
    assert request.snapshot_id is not None
    assert request.restore_epoch is not None
    assert request.expected_merkle_root is not None
    completed = await complete_cache_target_reconciliation(
        session,
        request_id=request.request_id,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        snapshot_id=request.snapshot_id,
        expected_restore_epoch=request.restore_epoch,
        actual_merkle_root=request.expected_merkle_root,
    )
    assert completed.status == "succeeded"
    return completed


@pytest.mark.integration
async def test_two_phase_reconciliation_reuses_current_generic_snapshot_material(
    migrated_session: AsyncSession,
) -> None:
    system = "reconciliation-generic-material-reuse-test"
    begin_command = await _reconciliation_command(
        migrated_session,
        key="9d100000-0000-4000-8000-000000000001",
        operation="service.cache-target-reconciliation.begin",
    )
    preparing = await begin_cache_target_reconciliation(
        migrated_session,
        command_id=begin_command,
        external_system=system,
        consumer_id=_CONSUMER,
        expected_restore_epoch=1,
        expected_control_version=None,
        create_only=True,
        reason="generic material 공유",
    )
    head = await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-a",
        event_id="9d200000-0000-4000-8000-000000000001",
        idempotency_key="9d300000-0000-4000-8000-000000000001",
    )
    generic = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=10,
    )
    expected_root = snapshot_merkle_root(
        [
            SnapshotMerkleRowV1(
                external_system=system,
                target_key="target-a",
                state=head.state,
                source_generation=head.source_generation,
                source_payload_fingerprint=head.source_payload_fingerprint,
            )
        ]
    )

    sealed = await seal_cache_target_reconciliation(
        migrated_session,
        request_id=preparing.request_id,
        external_system=system,
        consumer_id=_CONSUMER,
        expected_phase_version=1,
        expected_restore_epoch=1,
        expected_item_count=1,
        expected_merkle_root=expected_root,
    )

    # 0230 전에는 seal이 generic snapshot **행 자체**를 물려받아 두 역할이 같은
    # snapshot_id를 썼다. 이제 각자 receipt를 만들고 material만 공유한다 — 그래야
    # 한쪽이 다른 쪽의 만료 시각을 물려받지 않고, 공유가 양방향이 된다.
    assert sealed.snapshot_id != generic.snapshot_id
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_snapshots "
                "WHERE external_system = :system"
            ),
            {"system": system},
        )
        == 2
    )
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(DISTINCT material_id) "
                "FROM ops.poi_cache_target_snapshots "
                "WHERE external_system = :system"
            ),
            {"system": system},
        )
        == 1
    )
    assert (
        await migrated_session.scalar(
            text(
                "SELECT string_agg(receipt_kind, ',' ORDER BY receipt_kind) "
                "FROM ops.poi_cache_target_snapshots "
                "WHERE external_system = :system"
            ),
            {"system": system},
        )
        == "generic,reconciliation"
    )
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) "
                "FROM ops.poi_cache_target_snapshot_material_items AS item "
                "JOIN ops.poi_cache_target_snapshot_materials AS material "
                "ON material.material_id = item.material_id "
                "WHERE material.external_system = :system"
            ),
            {"system": system},
        )
        == 1
    )


@pytest.mark.integration
async def test_two_phase_reconciliation_seal_is_exact_and_transactional(
    migrated_session: AsyncSession,
) -> None:
    system = "reconciliation-two-phase-test"
    begin_command = await _reconciliation_command(
        migrated_session,
        key="9e000000-0000-0000-0000-000000000001",
        operation="service.cache-target-reconciliation.begin",
    )

    preparing = await begin_cache_target_reconciliation(
        migrated_session,
        command_id=begin_command,
        external_system=system,
        consumer_id=_CONSUMER,
        expected_restore_epoch=1,
        expected_control_version=None,
        create_only=True,
        reason="PinVi cutover",
    )

    assert preparing.status == "preparing"
    assert preparing.phase_version == 1
    assert preparing.snapshot_id is None
    assert preparing.stream_entity_tag == f'"{system}:1"'
    assert preparing.retry_after_seconds == 5

    replay = await begin_cache_target_reconciliation(
        migrated_session,
        command_id=begin_command,
        external_system=system,
        consumer_id=_CONSUMER,
        expected_restore_epoch=1,
        expected_control_version=None,
        create_only=True,
        reason="PinVi cutover",
    )
    assert replay.idempotent_replay
    assert replay.request_id == preparing.request_id
    assert replay.status == "preparing"

    with pytest.raises(CacheTargetStreamConflict) as preparing_snapshot:
        await get_cache_target_reconciliation_snapshot(
            migrated_session,
            request_id=preparing.request_id,
            consumer_id=_CONSUMER,
            limit=1,
        )
    assert preparing_snapshot.value.code == "reconciliation_not_sealed"

    head = await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="target-a",
        event_id="9e000000-0000-0000-0000-000000000101",
        idempotency_key="9e000000-0000-0000-0000-000000000201",
    )
    expected_root = snapshot_merkle_root(
        [
            SnapshotMerkleRowV1(
                external_system=system,
                target_key="target-a",
                state=head.state,
                source_generation=head.source_generation,
                source_payload_fingerprint=head.source_payload_fingerprint,
            )
        ]
    )

    with pytest.raises(CacheTargetStreamConflict) as wrong_phase:
        await seal_cache_target_reconciliation(
            migrated_session,
            request_id=preparing.request_id,
            external_system=system,
            consumer_id=_CONSUMER,
            expected_phase_version=2,
            expected_restore_epoch=1,
            expected_item_count=1,
            expected_merkle_root=expected_root,
        )
    assert wrong_phase.value.code == "reconciliation_precondition_failed"

    with pytest.raises(CacheTargetStreamConflict) as mismatch:
        await seal_cache_target_reconciliation(
            migrated_session,
            request_id=preparing.request_id,
            external_system=system,
            consumer_id=_CONSUMER,
            expected_phase_version=1,
            expected_restore_epoch=1,
            expected_item_count=2,
            expected_merkle_root=expected_root,
        )
    assert mismatch.value.code == "reconciliation_precondition_failed"
    metadata = await get_cache_target_reconciliation(
        migrated_session,
        request_id=preparing.request_id,
    )
    assert metadata.status == "preparing"
    assert metadata.phase_version == 1
    assert metadata.snapshot_id is None
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_snapshots "
                "WHERE external_system = :system"
            ),
            {"system": system},
        )
        == 0
    )
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) "
                "FROM ops.poi_cache_target_snapshot_material_items AS item "
                "JOIN ops.poi_cache_target_snapshot_materials AS material "
                "ON material.material_id = item.material_id "
                "WHERE material.external_system = :system"
            ),
            {"system": system},
        )
        == 0
    )

    sealed = await seal_cache_target_reconciliation(
        migrated_session,
        request_id=preparing.request_id,
        external_system=system,
        consumer_id=_CONSUMER,
        expected_phase_version=1,
        expected_restore_epoch=1,
        expected_item_count=1,
        expected_merkle_root=expected_root,
    )
    assert sealed.status == "running"
    assert sealed.phase_version == 2
    assert sealed.snapshot_id is not None
    assert sealed.expected_merkle_root == expected_root
    running = await get_cache_target_stream_discovery(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
    )
    assert running is not None
    assert running.active_reconciliation is not None
    assert running.active_reconciliation.status == "running"
    assert running.active_reconciliation.snapshot_id == sealed.snapshot_id
    assert running.active_reconciliation.entity_tag == sealed.entity_tag

    page = await get_cache_target_reconciliation_snapshot(
        migrated_session,
        request_id=sealed.request_id,
        consumer_id=_CONSUMER,
        limit=10,
    )
    assert page.snapshot_id == sealed.snapshot_id
    assert page.count == 1
    assert page.merkle_root == expected_root

    completed = await complete_cache_target_reconciliation(
        migrated_session,
        request_id=sealed.request_id,
        external_system=system,
        consumer_id=_CONSUMER,
        snapshot_id=sealed.snapshot_id,
        expected_restore_epoch=1,
        actual_merkle_root=expected_root,
    )
    assert completed.status == "succeeded"
    assert completed.phase_version == 3
    resumed = await get_cache_target_stream_discovery(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
    )
    assert resumed is not None
    assert resumed.active_reconciliation is None
    assert resumed.status == "ready"
    assert resumed.consumer_enabled


@pytest.mark.integration
async def test_two_phase_reconciliation_begin_preconditions(
    migrated_session: AsyncSession,
) -> None:
    system = "reconciliation-two-phase-precondition-test"
    await lock_cache_target_stream(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
    )

    create_command = await _reconciliation_command(
        migrated_session,
        key="9f000000-0000-0000-0000-000000000001",
        operation="service.cache-target-reconciliation.begin",
    )
    with pytest.raises(CacheTargetStreamConflict) as create_existing:
        await begin_cache_target_reconciliation(
            migrated_session,
            command_id=create_command,
            external_system=system,
            consumer_id=_CONSUMER,
            expected_restore_epoch=1,
            expected_control_version=None,
            create_only=True,
            reason="create existing",
        )
    assert create_existing.value.code == "reconciliation_precondition_failed"

    stale_command = await _reconciliation_command(
        migrated_session,
        key="9f000000-0000-0000-0000-000000000002",
        operation="service.cache-target-reconciliation.begin",
    )
    with pytest.raises(CacheTargetStreamConflict) as stale:
        await begin_cache_target_reconciliation(
            migrated_session,
            command_id=stale_command,
            external_system=system,
            consumer_id=_CONSUMER,
            expected_restore_epoch=1,
            expected_control_version=2,
            create_only=False,
            reason="stale stream etag",
        )
    assert stale.value.code == "reconciliation_precondition_failed"

    command = await _reconciliation_command(
        migrated_session,
        key="9f000000-0000-0000-0000-000000000003",
        operation="service.cache-target-reconciliation.begin",
    )
    started = await begin_cache_target_reconciliation(
        migrated_session,
        command_id=command,
        external_system=system,
        consumer_id=_CONSUMER,
        expected_restore_epoch=1,
        expected_control_version=1,
        create_only=False,
        reason="valid existing stream",
    )
    assert started.status == "preparing"

    active_command = await _reconciliation_command(
        migrated_session,
        key="9f000000-0000-0000-0000-000000000004",
        operation="service.cache-target-reconciliation.begin",
    )
    with pytest.raises(CacheTargetStreamConflict) as active:
        await begin_cache_target_reconciliation(
            migrated_session,
            command_id=active_command,
            external_system=system,
            consumer_id=_CONSUMER,
            expected_restore_epoch=1,
            expected_control_version=2,
            create_only=False,
            reason="active request exists",
        )
    assert active.value.code == "reconciliation_active"


@pytest.mark.integration
async def test_two_phase_reconciliation_service_routes_use_one_fresh_session_transaction(
    migrated_engine: AsyncEngine,
) -> None:
    from kortravelmap.api.app import create_app
    from kortravelmap.api.auth import SERVICE_TOKEN_HEADER
    from kortravelmap.api.db import get_session
    from kortravelmap.api.settings import ApiSettings

    system = "reconciliation-route-transaction-test"
    recovery_token = "route-transaction-recovery-token"
    consumer_token = "route-transaction-consumer-token"
    begin_key = "9f100000-0000-0000-0000-000000000001"
    seal_key = "9f100000-0000-0000-0000-000000000002"
    completion_key = "9f100000-0000-0000-0000-000000000003"

    async def _session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
            yield session

    app = create_app(
        ApiSettings(
            _env_file=None,
            admin_proxy_secret=None,
            api_call_log_enabled=False,
            cache_target_service_principals=[
                {
                    "principal_id": f"svc:pinvi-route-it-{role}",
                    "consumer_id": _CONSUMER,
                    "token_sha256": hashlib.sha256(
                        {
                            "command": "route-transaction-command-token",
                            "consumer": consumer_token,
                            "restore": "route-transaction-restore-token",
                            "recovery": recovery_token,
                        }[role].encode("utf-8")
                    ).hexdigest(),
                    "scopes": scopes,
                    "external_systems": [system],
                }
                for role, scopes in {
                    "command": ["cache-target:command"],
                    "consumer": [
                        "cache-target:read",
                        "cache-target:claim",
                        "cache-target:ack",
                        "cache-target:nack",
                        "cache-target:snapshot",
                    ],
                    "restore": ["cache-target:restore-fence"],
                    "recovery": [
                        "cache-target:recovery",
                        "cache-target:recovery-replay",
                    ],
                }.items()
            ],
        )
    )
    app.dependency_overrides[get_session] = _session

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as setup,
        setup.begin(),
    ):
        begin_command = await _reconciliation_command(
            setup,
            key=begin_key,
            operation="service.cache-target-reconciliation.begin",
        )
        preparing = await begin_cache_target_reconciliation(
            setup,
            command_id=begin_command,
            external_system=system,
            consumer_id=_CONSUMER,
            expected_restore_epoch=1,
            expected_control_version=None,
            create_only=True,
            reason="route transaction regression",
        )
        head = await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="target-a",
            event_id="9f100000-0000-0000-0000-000000000101",
            idempotency_key="9f100000-0000-0000-0000-000000000201",
        )
    expected_root = snapshot_merkle_root(
        [
            SnapshotMerkleRowV1(
                external_system=system,
                target_key="target-a",
                state=head.state,
                source_generation=head.source_generation,
                source_payload_fingerprint=head.source_payload_fingerprint,
            )
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        seal = await client.post(
            f"/v1/service/cache-target-reconciliations/{preparing.request_id}/seals",
            headers={
                SERVICE_TOKEN_HEADER: recovery_token,
                "If-Match": f'"{preparing.request_id}:1"',
                "Idempotency-Key": seal_key,
            },
            json={
                "external_system": system,
                "consumer_id": _CONSUMER,
                "expected_restore_epoch": 1,
                "expected_item_count": 1,
                "expected_merkle_root": expected_root,
            },
        )

    assert seal.status_code == 200, seal.text
    assert seal.headers["etag"] == f'"{preparing.request_id}:2"'

    async with AsyncSession(migrated_engine, expire_on_commit=False) as verify:
        metadata = await get_cache_target_reconciliation(
            verify,
            request_id=preparing.request_id,
        )
    assert metadata.status == "running"
    assert metadata.snapshot_id is not None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        completion = await client.post(
            f"/v1/service/cache-target-reconciliations/{preparing.request_id}/completions",
            headers={
                SERVICE_TOKEN_HEADER: consumer_token,
                "Idempotency-Key": completion_key,
            },
            json={
                "external_system": system,
                "consumer_id": _CONSUMER,
                "snapshot_id": metadata.snapshot_id,
                "expected_restore_epoch": 1,
                "actual_merkle_root": expected_root,
            },
        )

    assert completion.status_code == 200, completion.text
    async with AsyncSession(migrated_engine, expire_on_commit=False) as verify:
        completed = await get_cache_target_reconciliation(
            verify,
            request_id=preparing.request_id,
        )
    assert completed.status == "succeeded"


@pytest.mark.integration
async def test_reconciliation_mismatch_halts_and_exact_match_resumes_empty_stream(
    migrated_session: AsyncSession,
) -> None:
    system = "reconciliation-empty-test"
    await lock_cache_target_stream(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
    )
    first_command = await _reconciliation_command(
        migrated_session,
        key="93000000-0000-0000-0000-000000000001",
    )
    first = await request_cache_target_reconciliation(
        migrated_session,
        command_id=first_command,
        external_system=system,
        reason="empty mismatch",
    )
    with pytest.raises(CacheTargetStreamConflict) as stale_snapshot:
        await complete_cache_target_reconciliation(
            migrated_session,
            request_id=first.request_id,
            external_system=system,
            consumer_id=_CONSUMER,
            snapshot_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            expected_restore_epoch=1,
            actual_merkle_root=first.expected_merkle_root,
        )
    assert stale_snapshot.value.code == "reconciliation_precondition_failed"
    mismatch = await complete_cache_target_reconciliation(
        migrated_session,
        request_id=first.request_id,
        external_system=system,
        consumer_id=_CONSUMER,
        snapshot_id=first.snapshot_id,
        expected_restore_epoch=1,
        actual_merkle_root="f" * 64,
    )
    assert mismatch.status == "failed"
    control = await get_cache_target_stream(
        migrated_session,
        external_system=system,
    )
    assert control is not None
    assert control.status == "fenced"
    assert not control.consumer_enabled
    with pytest.raises(CacheTargetStreamConflict) as reused:
        await complete_cache_target_reconciliation(
            migrated_session,
            request_id=first.request_id,
            external_system=system,
            consumer_id=_CONSUMER,
            snapshot_id=first.snapshot_id,
            expected_restore_epoch=1,
            actual_merkle_root=first.expected_merkle_root,
        )
    assert reused.value.code == "reconciliation_receipt_mismatch"

    second_command = await _reconciliation_command(
        migrated_session,
        key="93000000-0000-0000-0000-000000000002",
    )
    second = await request_cache_target_reconciliation(
        migrated_session,
        command_id=second_command,
        external_system=system,
        reason="empty exact",
    )
    running_operation = await get_cache_target_operation(
        migrated_session,
        operation_id=second.operation_id,
    )
    assert running_operation is not None
    assert running_operation.status == "running"
    assert running_operation.snapshot_id == second.snapshot_id
    succeeded = await complete_cache_target_reconciliation(
        migrated_session,
        request_id=second.request_id,
        external_system=system,
        consumer_id=_CONSUMER,
        snapshot_id=second.snapshot_id,
        expected_restore_epoch=1,
        actual_merkle_root=second.expected_merkle_root,
    )
    assert succeeded.status == "succeeded"
    succeeded_operation = await get_cache_target_operation(
        migrated_session,
        operation_id=second.operation_id,
    )
    assert succeeded_operation is not None
    assert succeeded_operation.status == "succeeded"
    assert succeeded_operation.snapshot_id == second.snapshot_id
    control = await get_cache_target_stream(
        migrated_session,
        external_system=system,
    )
    assert control is not None
    assert control.status == "ready"
    assert control.consumer_enabled
    stream_event = (
        await migrated_session.execute(
            text(
                "SELECT event_scope, target_key, target_id, source_generation, "
                "target_sequence, source_payload_fingerprint, payload "
                "FROM ops.poi_cache_target_outbox_events "
                "WHERE reconciliation_request_id = CAST(:request_id AS uuid)"
            ),
            {"request_id": second.request_id},
        )
    ).one()
    assert tuple(stream_event[:6]) == (
        "stream",
        None,
        None,
        None,
        None,
        second.expected_merkle_root,
    )
    assert stream_event.payload == {
        "request_id": second.request_id,
        "snapshot_id": second.snapshot_id,
        "actual_merkle_root": second.expected_merkle_root,
        "expected_merkle_root": second.expected_merkle_root,
        "status": "succeeded",
        "version": "cache-target-reconciliation-v1",
    }
    statuses = await list_cache_target_stream_statuses(migrated_session, limit=100)
    status = next(item for item in statuses.items if item.external_system == system)
    assert status.consumer_enabled
    assert status.last_snapshot is not None
    assert status.last_snapshot.count == 0


@pytest.mark.integration
async def test_all_tombstone_reconciliation_emits_stream_scoped_event(
    migrated_session: AsyncSession,
) -> None:
    system = "reconciliation-tombstone-test"
    created = await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="deleted-target",
        event_id="94000000-0000-0000-0000-000000000001",
        idempotency_key="95000000-0000-0000-0000-000000000001",
    )
    assert created.target is not None
    deleted = await apply_cache_target_source(
        migrated_session,
        consumer_id=_CONSUMER,
        source_event_id="94000000-0000-0000-0000-000000000002",
        idempotency_key="95000000-0000-0000-0000-000000000002",
        external_system=system,
        target_key="deleted-target",
        restore_epoch=1,
        source_generation=2,
        source=make_deleted_cache_target_source(),
        occurred_at=datetime(2026, 7, 31, 18, 1, tzinfo=UTC),
        create_only=False,
        expected_target_id=created.target.target_id,
        expected_lock_version=created.target.lock_version,
    )
    assert deleted.target is not None
    command_id = await _reconciliation_command(
        migrated_session,
        key="96000000-0000-0000-0000-000000000001",
    )
    request = await request_cache_target_reconciliation(
        migrated_session,
        command_id=command_id,
        external_system=system,
        reason="tombstone exact",
    )
    page = await get_cache_target_snapshot(
        migrated_session,
        external_system=system,
        limit=10,
        cursor=None,
    )
    assert page.count == 1
    assert page.items[0].state == "deleted"
    succeeded = await complete_cache_target_reconciliation(
        migrated_session,
        request_id=request.request_id,
        external_system=system,
        consumer_id=_CONSUMER,
        snapshot_id=request.snapshot_id,
        expected_restore_epoch=1,
        actual_merkle_root=request.expected_merkle_root,
    )
    assert succeeded.status == "succeeded"
    scopes = (
        await migrated_session.execute(
            text(
                "SELECT event_scope, target_id FROM ops.poi_cache_target_outbox_events "
                "WHERE external_system = :external_system ORDER BY relay_order"
            ),
            {"external_system": system},
        )
    ).all()
    assert scopes[-1] == ("stream", None)
    assert all(scope == "target" and target_id is not None for scope, target_id in scopes[:-1])


@pytest.mark.integration
async def test_service_source_read_and_refresh_request_idempotency(
    migrated_session: AsyncSession,
) -> None:
    system = "service-refresh-test"
    created = await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="refresh-target",
        event_id="97000000-0000-0000-0000-000000000001",
        idempotency_key="98000000-0000-0000-0000-000000000001",
    )
    await _seed_scope_feature(
        migrated_session,
        membership=await _canonical_membership(migrated_session),
        feature_id="f_cache_target_scope_anchor",
    )
    source = await get_cache_target_source(
        migrated_session,
        external_system=system,
        target_key="refresh-target",
    )
    assert created.target is not None
    assert source is not None
    assert source.target_id == created.target.target_id
    assert source.entity_tag is not None

    request_count = await migrated_session.scalar(
        text("SELECT count(*) FROM ops.feature_update_requests")
    )
    with pytest.raises(ValueError, match="target_key.*NFC"):
        await create_cache_target_refresh_request(
            migrated_session,
            principal_id="pinvi-service",
            consumer_id=_CONSUMER,
            idempotency_key="99000000-0000-0000-0000-000000000009",
            external_system=system,
            target_keys=["refresh:e\u0301"],
            reason="invalid identity",
        )
    assert (
        await migrated_session.scalar(text("SELECT count(*) FROM ops.feature_update_requests"))
        == request_count
    )
    member_count = await migrated_session.scalar(
        text("SELECT count(*) FROM ops.poi_cache_target_refresh_members")
    )
    with pytest.raises(ValueError, match="target_key.*NFC"):
        await capture_cache_target_refresh_members_by_keys(
            migrated_session,
            request_id="99000000-0000-0000-0000-000000000008",
            external_system=system,
            target_keys=["refresh:e\u0301"],
        )
    assert (
        await migrated_session.scalar(
            text("SELECT count(*) FROM ops.poi_cache_target_refresh_members")
        )
        == member_count
    )

    request = await create_cache_target_refresh_request(
        migrated_session,
        principal_id="pinvi-service",
        consumer_id=_CONSUMER,
        idempotency_key="99000000-0000-0000-0000-000000000001",
        external_system=system,
        target_keys=["refresh-target"],
        reason="service refresh",
    )
    assert request.status == "queued"
    assert not request.idempotent_replay
    queued_events = (
        await migrated_session.execute(
            text(
                "SELECT event_type, payload, restore_epoch, source_generation "
                "FROM ops.poi_cache_target_outbox_events "
                "WHERE refresh_request_id = CAST(:request_id AS uuid)"
            ),
            {"request_id": request.request_id},
        )
    ).all()
    assert len(queued_events) == 1
    queued_event = queued_events[0]
    assert queued_event.event_type == "refresh_request.status_changed"
    assert queued_event.payload["status"] == "queued"
    assert queued_event.payload["request_id"] == request.request_id
    assert queued_event.restore_epoch == 1
    assert queued_event.source_generation == 1
    replay = await create_cache_target_refresh_request(
        migrated_session,
        principal_id="pinvi-service",
        consumer_id=_CONSUMER,
        idempotency_key="99000000-0000-0000-0000-000000000001",
        external_system=system,
        target_keys=["refresh-target"],
        reason="service refresh",
    )
    assert replay.request_id == request.request_id
    assert replay.idempotent_replay
    detail = await get_cache_target_refresh_request(
        migrated_session,
        request_id=request.request_id,
    )
    assert detail is not None
    assert detail.external_system == system
    with pytest.raises(CacheTargetStreamConflict) as conflict:
        await create_cache_target_refresh_request(
            migrated_session,
            principal_id="pinvi-service",
            consumer_id=_CONSUMER,
            idempotency_key="99000000-0000-0000-0000-000000000001",
            external_system=system,
            target_keys=["refresh-target"],
            reason="different reason",
        )
    assert conflict.value.code == "refresh_idempotency_key_reused"

    # source protocol 도입 전 admin 경로가 만든 target은 source head가 없다. 이를
    # request만 queued되고 status outbox가 0건인 거짓 성공으로 남기지 않는다.
    legacy_target = await upsert_poi_cache_target(
        migrated_session,
        external_system=system,
        target_key="legacy-refresh-target",
        lon=126.978,
        lat=37.5665,
        radius_km=5,
    )
    requests_before = await migrated_session.scalar(
        text("SELECT count(*) FROM ops.feature_update_requests")
    )
    with pytest.raises(CacheTargetStreamConflict) as missing_source:
        await create_cache_target_refresh_request(
            migrated_session,
            principal_id="pinvi-service",
            consumer_id=_CONSUMER,
            idempotency_key="99000000-0000-0000-0000-000000000010",
            external_system=system,
            target_keys=[legacy_target.target_key],
            reason="legacy target must fail closed",
        )
    assert missing_source.value.code == "refresh_source_head_missing"
    assert missing_source.value.current == {
        "external_system": system,
        "target_keys": [legacy_target.target_key],
    }
    assert (
        await migrated_session.scalar(
            text("SELECT count(*) FROM ops.feature_update_requests")
        )
        == requests_before
    )


@pytest.mark.integration
async def test_service_refresh_rejects_source_head_from_prior_restore_epoch(
    migrated_session: AsyncSession,
) -> None:
    """restore fence 뒤 남은 head로 epoch-1 delivery를 새로 만들지 않는다."""

    system = "service-refresh-stale-head-test"
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="refresh-target",
        event_id="9d100000-0000-4000-8000-000000000001",
        idempotency_key="9d200000-0000-4000-8000-000000000001",
    )
    fence_request = {
        "external_system": system,
        "expected_restore_epoch": 1,
        "reason": "stale source head must not refresh",
    }
    fingerprint = canonical_domain_command_fingerprint(fence_request)
    claim = await create_domain_command_claim(
        migrated_session,
        actor=_CONSUMER,
        operation="cache_target.restore_fence",
        idempotency_key="9d300000-0000-4000-8000-000000000001",
        request_fingerprint=fingerprint,
    )
    fenced = await advance_cache_target_restore_fence(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
        command_id=claim.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason=fence_request["reason"],
        request_fingerprint=fingerprint,
    )
    assert fenced.restore_epoch == 2

    requests_before = await migrated_session.scalar(
        text("SELECT count(*) FROM ops.feature_update_requests")
    )
    with pytest.raises(CacheTargetStreamConflict) as stale_source:
        await create_cache_target_refresh_request(
            migrated_session,
            principal_id="pinvi-service",
            consumer_id=_CONSUMER,
            idempotency_key="9d400000-0000-4000-8000-000000000001",
            external_system=system,
            target_keys=["refresh-target"],
            reason="stale epoch must fail closed",
        )
    assert stale_source.value.code == "refresh_source_head_missing"
    assert stale_source.value.current == {
        "external_system": system,
        "target_keys": ["refresh-target"],
    }
    assert (
        await migrated_session.scalar(text("SELECT count(*) FROM ops.feature_update_requests"))
        == requests_before
    )


@pytest.mark.integration
async def test_queued_service_refresh_cancellation_emits_exact_tuple_status(
    migrated_engine: AsyncEngine,
) -> None:
    """실행 전 취소도 queued snapshot과 같은 tuple로 relay에 남긴다."""

    system = "queued-refresh-cancellation-test"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="refresh-target",
            event_id="9d500000-0000-4000-8000-000000000001",
            idempotency_key="9d600000-0000-4000-8000-000000000001",
        )
        await _seed_scope_feature(
            setup,
            membership=await _canonical_membership(setup),
            feature_id="f_queued_refresh_cancellation_scope_anchor",
            # migrated_engine는 다음 테스트에도 commit을 남긴다. 카테고리 집계
            # 회귀 fixture와 충돌하지 않는 전용 코드로 격리한다.
            category="99999101",
        )
        request = await create_cache_target_refresh_request(
            setup,
            principal_id="pinvi-service",
            consumer_id=_CONSUMER,
            idempotency_key="9d700000-0000-4000-8000-000000000001",
            external_system=system,
            target_keys=["refresh-target"],
            reason="queued cancellation relay evidence",
        )

    settings = ApiSettings(
        dagster_url="http://dagster.example",
        dagster_allowed_hosts=["dagster.example"],
    )
    async with httpx.AsyncClient() as client:
        result = await cancel_pipeline_execution(
            engine=migrated_engine,
            settings=settings,
            http_client=client,
            kind="update_request",
            execution_id=request.request_id,
            requested_by="admin:test",
            reason="queued refresh cancellation",
        )

    assert result.status == "completed"
    assert result.members[0].result == "cancelled"
    async with AsyncSession(migrated_engine) as probe:
        rows = (
            await probe.execute(
                text(
                    """
                    SELECT payload ->> 'status' AS status, restore_epoch,
                           source_generation, source_payload_fingerprint
                    FROM ops.poi_cache_target_outbox_events
                    WHERE refresh_request_id = CAST(:request_id AS uuid)
                    ORDER BY relay_order
                    """
                ),
                {"request_id": request.request_id},
            )
        ).all()
    assert [(row.status, row.restore_epoch, row.source_generation) for row in rows] == [
        ("queued", 1, 1),
        ("cancelled", 1, 1),
    ]
    assert len({str(row.source_payload_fingerprint) for row in rows}) == 1


@pytest.mark.integration
async def test_restore_fence_rejects_previously_queued_service_refresh_status_event(
    migrated_session: AsyncSession,
) -> None:
    """fence 전 정상 queue도 fence 뒤 epoch-1 status event를 다시 만들지 않는다."""

    system = "pinvi"
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="fenced-refresh-target",
        event_id="9e100000-0000-4000-8000-000000000001",
        idempotency_key="9e200000-0000-4000-8000-000000000001",
    )
    await _seed_scope_feature(
        migrated_session,
        membership=await _canonical_membership(migrated_session),
        feature_id="f_fenced_service_refresh_scope_anchor",
    )
    request = await create_cache_target_refresh_request(
        migrated_session,
        principal_id="pinvi-service",
        consumer_id=_CONSUMER,
        idempotency_key="9e300000-0000-4000-8000-000000000001",
        external_system=system,
        target_keys=["fenced-refresh-target"],
        reason="queue before restore fence",
    )
    fence_request = {
        "external_system": system,
        "expected_restore_epoch": 1,
        "reason": "fence queued refresh",
    }
    fingerprint = canonical_domain_command_fingerprint(fence_request)
    claim = await create_domain_command_claim(
        migrated_session,
        actor=_CONSUMER,
        operation="cache_target.restore_fence",
        idempotency_key="9e400000-0000-4000-8000-000000000001",
        request_fingerprint=fingerprint,
    )
    await advance_cache_target_restore_fence(
        migrated_session,
        external_system=system,
        consumer_id=_CONSUMER,
        command_id=claim.command_id,
        expected_restore_epoch=1,
        expected_control_version=1,
        reason=fence_request["reason"],
        request_fingerprint=fingerprint,
    )

    protocol_error = await pinvi_cache_target_refresh_protocol_error(
        migrated_session,
        request_id=request.request_id,
        external_system=system,
        target_keys=["fenced-refresh-target"],
    )
    assert protocol_error is not None
    assert "restore epoch" in protocol_error
    stored_request = await get_update_request(migrated_session, request.request_id)
    assert stored_request is not None
    with pytest.raises(
        CacheTargetRefreshProtocolViolation, match="restore epoch"
    ) as fence_violation:
        await append_cache_target_refresh_status_events(
            migrated_session,
            request_id=request.request_id,
            job_id=stored_request.job_id,
            status="running",
        )
    # #975 적대 재리뷰 P2: 호출자는 예외 클래스가 아니라 reason으로 분기한다. fence 이동만
    # 억제 근거를 가지므로 이 경로가 정확히 그 reason을 달고 나와야 한다.
    assert (
        fence_violation.value.reason
        == CacheTargetRefreshProtocolViolation.EPOCH_MOVED
    )
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_outbox_events "
                "WHERE refresh_request_id = CAST(:request_id AS uuid) "
                "AND payload ->> 'status' = 'running'"
            ),
            {"request_id": request.request_id},
        )
        == 0
    )


@pytest.mark.integration
async def test_service_refresh_creation_serializes_stream_before_capture(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """서로 다른 idempotency key도 stream lock upgrade 없이 순서대로 queue한다."""

    system = "service-refresh-serialization-test"
    async with AsyncSession(migrated_engine) as setup, setup.begin():
        created = await _apply_snapshot_source(
            setup,
            external_system=system,
            target_key="refresh-target",
            event_id="9c100000-0000-4000-8000-000000000001",
            idempotency_key="9c200000-0000-4000-8000-000000000001",
        )
        await _seed_scope_feature(
            setup,
            membership=await _canonical_membership(setup),
            feature_id="f_service_refresh_serialization_anchor",
            category="99999102",
        )
    assert created.target is not None

    first_scope_entered = asyncio.Event()
    second_scope_entered = asyncio.Event()
    release_first_scope = asyncio.Event()
    release_second_scope = asyncio.Event()
    scope_calls = 0
    original_scope_memberships = service_repo._refresh_scope_memberships

    async def _gated_scope_memberships(*args: Any, **kwargs: Any):
        nonlocal scope_calls
        scope_calls += 1
        if scope_calls == 1:
            first_scope_entered.set()
            await release_first_scope.wait()
        else:
            second_scope_entered.set()
            await release_second_scope.wait()
        return await original_scope_memberships(*args, **kwargs)

    monkeypatch.setattr(
        service_repo,
        "_refresh_scope_memberships",
        _gated_scope_memberships,
    )

    async def _submit(idempotency_key: str):
        async with AsyncSession(migrated_engine) as session, session.begin():
            return await create_cache_target_refresh_request(
                session,
                principal_id="pinvi-service",
                consumer_id=_CONSUMER,
                idempotency_key=idempotency_key,
                external_system=system,
                target_keys=["refresh-target"],
                reason="concurrent service refresh",
            )

    first = asyncio.create_task(_submit("9c300000-0000-4000-8000-000000000001"))
    await asyncio.wait_for(first_scope_entered.wait(), timeout=5)
    second = asyncio.create_task(_submit("9c300000-0000-4000-8000-000000000002"))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(second_scope_entered.wait(), timeout=0.3)

    release_first_scope.set()
    first_request = await asyncio.wait_for(first, timeout=5)
    await asyncio.wait_for(second_scope_entered.wait(), timeout=5)
    async with AsyncSession(migrated_engine) as complete, complete.begin():
        await complete.execute(
            text(
                "UPDATE ops.import_jobs AS job SET status = 'done', progress = 100, "
                "finished_at = now() FROM ops.feature_update_requests AS request "
                "WHERE request.request_id = CAST(:request_id AS uuid) "
                "AND job.job_id = request.job_id"
            ),
            {"request_id": first_request.request_id},
        )
    release_second_scope.set()
    second_request = await asyncio.wait_for(
        second,
        timeout=5,
    )
    assert first_request.request_id != second_request.request_id
    async with AsyncSession(migrated_engine) as verify:
        queued_event_count = await verify.scalar(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_outbox_events "
                "WHERE refresh_request_id::text = ANY(CAST(:request_ids AS text[]))"
            ),
            {
                "request_ids": [first_request.request_id, second_request.request_id],
            },
        )
    assert queued_event_count == 2


@pytest.mark.integration
async def test_refresh_member_result_events_are_idempotent_and_transactional(
    migrated_session: AsyncSession,
) -> None:
    created = await _apply_active(
        migrated_session,
        generation=1,
        event_id="10000000-0000-0000-0000-000000000041",
        idempotency_key="20000000-0000-0000-0000-000000000041",
        create_only=True,
    )
    assert created.target is not None
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "cache_target_keys",
            "external_system": _SYSTEM,
            "target_keys": [_TARGET_KEY],
        },
        dataset_memberships=[await _canonical_membership(migrated_session)],
    )
    assert request is not None

    savepoint = await migrated_session.begin_nested()
    members = await capture_cache_target_refresh_members_by_keys(
        migrated_session,
        request_id=request.request_id,
        external_system=_SYSTEM,
        target_keys=[_TARGET_KEY],
    )
    assert len(members) == 1
    rolled_back = await append_cache_target_refresh_status_events(
        migrated_session,
        request_id=request.request_id,
        job_id=request.job_id,
        status="running",
    )
    assert rolled_back[0].target_sequence == 2
    await savepoint.rollback()

    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_outbox_events "
                "WHERE refresh_request_id = CAST(:request_id AS uuid)"
            ),
            {"request_id": request.request_id},
        )
        == 0
    )

    members = await capture_cache_target_refresh_members_by_keys(
        migrated_session,
        request_id=request.request_id,
        external_system=_SYSTEM,
        target_keys=[_TARGET_KEY],
    )
    assert members[0].restore_epoch == 1
    assert members[0].source_generation == 1
    running = await append_cache_target_refresh_status_events(
        migrated_session,
        request_id=request.request_id,
        job_id=request.job_id,
        status="running",
    )
    links = await append_cache_target_links_reconciled_events(
        migrated_session,
        request_id=request.request_id,
        job_id=request.job_id,
        active_link_counts={created.target.target_id: 3},
    )
    done = await append_cache_target_refresh_status_events(
        migrated_session,
        request_id=request.request_id,
        job_id=request.job_id,
        status="done",
    )
    assert [
        running[0].target_sequence,
        links[0].target_sequence,
        done[0].target_sequence,
    ] == [2, 3, 4]
    assert links[0].payload["active_link_count"] == 3

    replay = await append_cache_target_refresh_status_events(
        migrated_session,
        request_id=request.request_id,
        job_id=request.job_id,
        status="done",
    )
    assert replay[0].idempotent_replay
    assert replay[0].event_id == done[0].event_id
    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) FROM ops.poi_cache_target_outbox_deliveries "
                "WHERE event_id IN ("
                "SELECT event_id FROM ops.poi_cache_target_outbox_events "
                "WHERE external_system = :system)"
            ),
            {"system": _SYSTEM},
        )
        == 4
    )


@pytest.mark.integration
async def test_service_refresh_rejects_inactive_or_unknown_keys_at_intake(
    migrated_session: AsyncSession,
) -> None:
    """PinVi service refresh는 exact key set — 활성 target이 아닌 key가 하나라도 있으면 409.

    #975 적대 재리뷰 P1: 예전엔 active key만 member로 capture하고 202/queued를 돌려준 뒤 실행자의
    exact-set 검사에서 relay event 없이 fail-close했다(consumer는 영원히 기다린다). intake에서
    `refresh_target_inactive`로 막고 request 행·outbox event를 만들지 않는다.
    """
    system = "service-refresh-inactive-key-test"
    await _apply_snapshot_source(
        migrated_session,
        external_system=system,
        target_key="active-key",
        event_id="9e100000-0000-4000-8000-000000000001",
        idempotency_key="9e200000-0000-4000-8000-000000000001",
    )
    await apply_cache_target_source(
        migrated_session,
        consumer_id=_CONSUMER,
        source_event_id="9e100000-0000-4000-8000-000000000002",
        idempotency_key="9e200000-0000-4000-8000-000000000002",
        external_system=system,
        target_key="disabled-key",
        restore_epoch=1,
        source_generation=1,
        source=make_active_cache_target_source(
            lon="126.978", lat="37.5665", radius_km="5", update_enabled=False
        ),
        occurred_at=datetime(2026, 7, 31, 18, 0, tzinfo=UTC),
        create_only=True,
    )
    requests_before = await migrated_session.scalar(
        text("SELECT count(*) FROM ops.feature_update_requests")
    )
    events_before = await migrated_session.scalar(
        text("SELECT count(*) FROM ops.poi_cache_target_outbox_events")
    )
    with pytest.raises(CacheTargetStreamConflict) as conflict:
        await create_cache_target_refresh_request(
            migrated_session,
            principal_id="pinvi-service",
            consumer_id=_CONSUMER,
            idempotency_key="9e300000-0000-4000-8000-000000000001",
            external_system=system,
            target_keys=["active-key", "disabled-key", "never-registered-key"],
            reason="mixed keys",
        )
    assert conflict.value.code == "refresh_target_inactive"
    assert conflict.value.current == {
        "external_system": system,
        "target_keys": ["disabled-key", "never-registered-key"],
    }
    assert (
        await migrated_session.scalar(text("SELECT count(*) FROM ops.feature_update_requests"))
        == requests_before
    )
    assert (
        await migrated_session.scalar(
            text("SELECT count(*) FROM ops.poi_cache_target_outbox_events")
        )
        == events_before
    )
