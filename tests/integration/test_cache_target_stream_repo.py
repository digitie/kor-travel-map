from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.core.cache_target_stream import (
    SnapshotMerkleRowV1,
    make_active_cache_target_source,
    make_deleted_cache_target_source,
    snapshot_merkle_root,
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
    assert (
        recovery_claim.events[0].relay_order,
        recovery_claim.events[0].payload_fingerprint,
    ) == (blocked_event.relay_order, blocked_event.payload_fingerprint)
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
    recovery = await claim_cache_target_events(
        migrated_session,
        external_system=_SYSTEM,
        consumer_id=_CONSUMER,
        idempotency_key="85000000-0000-0000-0000-000000000002",
        limit=2,
    )
    assert recovery is not None
    assert [event.event_id for event in recovery.events] == [poison.event_id]


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
                "SELECT count(*) FROM ops.poi_cache_target_snapshot_items "
                "WHERE external_system = :system"
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
    token = "route-transaction-token"
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
                    "principal_id": "svc:pinvi-route-it",
                    "consumer_id": _CONSUMER,
                    "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    "scopes": ["cache-target:recovery", "cache-target:snapshot"],
                    "external_systems": [system],
                }
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
                SERVICE_TOKEN_HEADER: token,
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
                SERVICE_TOKEN_HEADER: token,
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
                "target_sequence, source_payload_fingerprint "
                "FROM ops.poi_cache_target_outbox_events "
                "WHERE reconciliation_request_id = CAST(:request_id AS uuid)"
            ),
            {"request_id": second.request_id},
        )
    ).one()
    assert tuple(stream_event) == (
        "stream",
        None,
        None,
        None,
        None,
        second.expected_merkle_root,
    )
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
    source = await get_cache_target_source(
        migrated_session,
        external_system=system,
        target_key="refresh-target",
    )
    assert created.target is not None
    assert source is not None
    assert source.target_id == created.target.target_id
    assert source.entity_tag is not None

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
