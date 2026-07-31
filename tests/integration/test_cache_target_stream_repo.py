from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.cache_target_stream import (
    make_active_cache_target_source,
    make_deleted_cache_target_source,
)
from kortravelmap.infra.cache_target_event_repo import (
    append_cache_target_links_reconciled_events,
    append_cache_target_refresh_status_events,
    capture_cache_target_refresh_members_by_keys,
)
from kortravelmap.infra.cache_target_outbox_repo import (
    CacheTargetAppliedReceipt,
    ack_cache_target_events,
    claim_cache_target_events,
    get_cache_target_dead_letter,
    nack_cache_target_event,
    replay_cache_target_dead_letter,
)
from kortravelmap.infra.cache_target_stream_repo import (
    CacheTargetStreamConflict,
    advance_cache_target_restore_fence,
    apply_cache_target_source,
    get_cache_target_stream,
)
from kortravelmap.infra.domain_command_repo import (
    canonical_domain_command_fingerprint,
    create_domain_command_claim,
)
from kortravelmap.infra.feature_update_repo import enqueue_feature_update_request

_SYSTEM = "pinvi-test"
_CONSUMER = "pinvi-cache-consumer"
_TARGET_KEY = "trip-day-poi:1"


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

    detail = await get_cache_target_dead_letter(
        migrated_session,
        event_id=blocked_event.event_id,
    )
    assert detail is not None
    assert detail.event.relay_order == blocked_event.relay_order
    with pytest.raises(CacheTargetStreamConflict) as blocked:
        await claim_cache_target_events(
            migrated_session,
            external_system=_SYSTEM,
            consumer_id=_CONSUMER,
            idempotency_key="82000000-0000-0000-0000-000000000002",
            limit=2,
        )
    assert blocked.value.code == "stream_blocked"

    replayed = await replay_cache_target_dead_letter(
        migrated_session,
        event_id=blocked_event.event_id,
        expected_delivery_version=detail.delivery_version,
    )
    assert replayed.status == "retry"
    recovery_claim = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="82000000-0000-0000-0000-000000000003",
        limit=2,
    )
    assert recovery_claim is not None
    assert [event.event_id for event in recovery_claim.events] == [blocked_event.event_id]
    await ack_cache_target_events(
        migrated_session,
        consumer_id=_CONSUMER,
        claim_id=recovery_claim.claim_id,
        lease_token=recovery_claim.lease_token,
        through_cursor=recovery_claim.events[0].cursor,
        applied=[
            CacheTargetAppliedReceipt(
                recovery_claim.events[0].event_id,
                recovery_claim.events[0].payload_fingerprint,
            )
        ],
    )
    with pytest.raises(CacheTargetStreamConflict) as still_blocked:
        await claim_cache_target_events(
            migrated_session,
            external_system=_SYSTEM,
            consumer_id=_CONSUMER,
            idempotency_key="82000000-0000-0000-0000-000000000004",
            limit=2,
        )
    assert still_blocked.value.code == "blocked_event_not_head"


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
