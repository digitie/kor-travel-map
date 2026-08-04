"""H35 cache-target snapshot GC와 final DB evidence."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.cli._h35_contract import (
    CacheTargetEvidence,
    H35IdentityError,
    H35Request,
    JsonValue,
    Receipt,
    all_pass,
    bind_database_identity,
    check,
    receipt,
    validate_cache_target_evidence,
)
from kortravelmap.cli._h35_schema_version import FORWARD_BOUNDARY, TARGET_SCHEMA
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.cache_target_stream import SnapshotMerkleRowV1, snapshot_merkle_root
from kortravelmap.infra.cache_target_outbox_repo import cache_target_event_cursor
from kortravelmap.infra.cache_target_reconciliation_repo import (
    observe_expired_cache_target_snapshot_backlog,
)
from kortravelmap.infra.cache_target_stream_repo import cache_target_stream_entity_tag
from kortravelmap.infra.db import make_async_engine

EVIDENCE_CONTRACT_VERSION: Final = "ktm-cache-target-final-evidence/v1"
EVIDENCE_EXTERNAL_SYSTEM: Final = "pinvi"
_OBSERVATION_RETENTION_DAYS: Final = 90
_OBSERVATION_GROWTH_MIN_INTERVAL_SECONDS: Final = 300
_SHA256_HEX: Final = frozenset("0123456789abcdef")


def cache_target_gc_observation_run_id(transaction_id: str) -> str:
    """outer cutover transaction에서 replay-stable observation identity를 만든다."""
    return f"h35:{transaction_id}:cache-target-snapshot-gc:v1"


def _dsn() -> str:
    value = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    if not value:
        raise RuntimeError("database_configuration_missing")
    return value


def _engine() -> AsyncEngine:
    return make_async_engine(
        _dsn(),
        # GC가 session advisory lock 연결을 고정한 채 batch transaction용
        # 두 번째 연결을 열므로 최소 두 연결이 필요하다.
        pool_size=2,
        max_overflow=0,
        server_settings={
            "application_name": "kor-travel-map-h35-helper",
            "lock_timeout": "5s",
        },
    )


def _image_revision_check(request: H35Request) -> dict[str, JsonValue]:
    return check(
        "candidate_image_source_revision",
        expected=request.source_revision,
        observed=os.environ.get("KOR_TRAVEL_MAP_IMAGE_REVISION", ""),
    )


async def _bind_live_database_identity(
    session: AsyncSession,
    request: H35Request,
) -> tuple[H35Request, dict[str, JsonValue]]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT current_database() AS database_name, "
                    "(pg_control_system()).system_identifier::text AS system_identifier, "
                    "(SELECT count(*) FROM alembic_version) AS alembic_rows"
                )
            )
        )
        .mappings()
        .one()
    )
    if int(row["alembic_rows"]) != 1:
        raise H35IdentityError("alembic_version_cardinality_invalid")
    return bind_database_identity(
        request,
        database=str(row["database_name"]),
        system_identifier=str(row["system_identifier"]),
    )


async def run_gc(request: H35Request) -> Receipt:
    """기존 bounded GC를 실행하고 state-convergent final backlog를 승인한다."""
    observation_run_id = cache_target_gc_observation_run_id(request.transaction_id)
    engine = _engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            live_request, identity_check = await _bind_live_database_identity(session, request)
            schema = str(await session.scalar(text("SELECT version_num FROM alembic_version")))
            before = await observe_expired_cache_target_snapshot_backlog(session)
        entry_checks = [
            identity_check,
            _image_revision_check(request),
            check("schema_before_gc", expected=TARGET_SCHEMA, observed=schema),
        ]
        if not all_pass(entry_checks):
            return receipt(
                live_request,
                status="rejected",
                schema_before=schema,
                schema_after=schema,
                forward_boundary=(FORWARD_BOUNDARY if schema == TARGET_SCHEMA else "not_crossed"),
                row_counts={
                    "remaining_headers": before.remaining_headers,
                    "remaining_items": before.remaining_items,
                },
                checks=entry_checks,
            )

        async with AsyncKorTravelMapClient(engine) as client:
            result = await client.drain_expired_cache_target_snapshots(
                observation_run_id=observation_run_id,
                observation_retention_days=_OBSERVATION_RETENTION_DAYS,
                observation_growth_min_interval_seconds=(_OBSERVATION_GROWTH_MIN_INTERVAL_SECONDS),
            )
    finally:
        await engine.dispose()

    checks = [
        *entry_checks,
        check("gc_lock_acquired", expected=True, observed=result.acquired),
        check("gc_not_skipped", expected=False, observed=result.skipped),
        check("gc_remaining_items", expected=0, observed=result.remaining_items),
        check("gc_remaining_headers", expected=0, observed=result.remaining_headers),
        check(
            "gc_referenced_items_preserved",
            expected=before.referenced_items,
            observed=result.referenced_items,
        ),
        check(
            "gc_referenced_headers_preserved",
            expected=before.referenced_headers,
            observed=result.referenced_headers,
        ),
        check(
            "gc_observation_run_id",
            expected=observation_run_id,
            observed=result.observation_run_id,
        ),
        check(
            "gc_observation_referenced_items_fresh",
            expected=result.referenced_items,
            observed=result.observation_referenced_items,
        ),
        check(
            "gc_observation_referenced_headers_fresh",
            expected=result.referenced_headers,
            observed=result.observation_referenced_headers,
        ),
        check(
            "gc_observation_timestamp_present",
            expected=True,
            observed=result.observed_at is not None,
        ),
    ]
    return receipt(
        live_request,
        status="accepted" if all_pass(checks) else "rejected",
        schema_before=schema,
        schema_after=schema,
        forward_boundary=FORWARD_BOUNDARY,
        row_counts={
            "batches": result.batches,
            "deleted_headers": result.deleted_headers,
            "deleted_items": result.deleted_items,
            "referenced_headers": int(result.referenced_headers or 0),
            "referenced_items": int(result.referenced_items or 0),
            "remaining_headers": int(result.remaining_headers or 0),
            "remaining_items": int(result.remaining_items or 0),
        },
        checks=checks,
    )


def _is_lowercase_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _SHA256_HEX for character in value)
    )


def _int(values: Mapping[str, object], key: str, *, default: int = -1) -> int:
    value = values.get(key)
    return int(value) if type(value) is int else default


def _snapshot_merkle(rows: list[RowMapping]) -> str:
    material: list[SnapshotMerkleRowV1] = []
    for row in rows:
        state = row["state"]
        if state not in {"active", "deleted"}:
            raise ValueError("snapshot_state_invalid")
        source_generation = row["source_generation"]
        if type(source_generation) is not int:
            raise TypeError("snapshot_source_generation_invalid")
        material.append(
            SnapshotMerkleRowV1(
                external_system=str(row["external_system"]),
                target_key=str(row["target_key"]),
                state=state,
                source_generation=source_generation,
                source_payload_fingerprint=str(row["source_payload_fingerprint"]),
            )
        )
    return snapshot_merkle_root(material)


async def collect_cache_target_final_evidence(
    request: H35Request,
) -> tuple[
    H35Request,
    dict[str, JsonValue],
    CacheTargetEvidence | None,
    list[dict[str, JsonValue]],
    dict[str, int],
]:
    """final all-writer stop 뒤 PinVi stream의 fresh DB-only evidence를 만든다."""
    observation_run_id = cache_target_gc_observation_run_id(request.transaction_id)
    engine = _engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            live_request, identity_check = await _bind_live_database_identity(session, request)
            schema = str(await session.scalar(text("SELECT version_num FROM alembic_version")))
            stream_row = (
                (
                    await session.execute(
                        text(
                            "SELECT external_system, consumer_id, restore_epoch, control_version, "
                            "status, blocked_event_id, consumer_enabled "
                            "FROM ops.poi_cache_target_streams "
                            "WHERE external_system=:external_system"
                        ),
                        {"external_system": EVIDENCE_EXTERNAL_SYSTEM},
                    )
                )
                .mappings()
                .one_or_none()
            )
            snapshot_row = (
                (
                    await session.execute(
                        text(
                            "SELECT snapshot_id, external_system, restore_epoch, "
                            "high_watermark_relay_order, material_high_watermark_relay_order, "
                            "item_count, merkle_root, expires_at > now() AS valid "
                            "FROM ops.poi_cache_target_snapshots "
                            "WHERE external_system=:external_system "
                            "ORDER BY created_at DESC, snapshot_id DESC LIMIT 1"
                        ),
                        {"external_system": EVIDENCE_EXTERNAL_SYSTEM},
                    )
                )
                .mappings()
                .one_or_none()
            )
            snapshot_item_rows = (
                []
                if snapshot_row is None
                else (
                    (
                        await session.execute(
                            text(
                                "SELECT external_system, target_key, state, "
                                "source_generation, source_payload_fingerprint "
                                "FROM ops.poi_cache_target_snapshot_items "
                                "WHERE snapshot_id=CAST(:snapshot_id AS uuid) "
                                "ORDER BY row_number"
                            ),
                            {"snapshot_id": snapshot_row["snapshot_id"]},
                        )
                    )
                    .mappings()
                    .all()
                )
            )
            source_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT external_system, target_key, state, source_generation, "
                            "source_payload_fingerprint "
                            "FROM ops.poi_cache_target_source_heads "
                            "WHERE external_system=:external_system "
                            "ORDER BY convert_to(normalize(external_system, NFC), 'UTF8'), "
                            "convert_to(normalize(target_key, NFC), 'UTF8')"
                        ),
                        {"external_system": EVIDENCE_EXTERNAL_SYSTEM},
                    )
                )
                .mappings()
                .all()
            )
            backlog_row = (
                (
                    await session.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM ops.poi_cache_target_reconciliation_requests "
                            " WHERE external_system=:external_system "
                            " AND status IN ('preparing','running')) AS reconciliation_backlog, "
                            "(SELECT count(*) FROM ops.poi_cache_target_outbox_events AS event "
                            " LEFT JOIN ops.poi_cache_target_outbox_deliveries AS delivery "
                            " ON delivery.event_id=event.event_id "
                            " WHERE event.external_system=:external_system "
                            " AND delivery.event_id IS NULL) AS outbox_backlog, "
                            "(SELECT count(*) FROM ops.poi_cache_target_outbox_claims "
                            " WHERE external_system=:external_system "
                            " AND status='active') AS claim_backlog, "
                            "(SELECT count(*) FROM ops.poi_cache_target_outbox_events AS event "
                            " JOIN ops.poi_cache_target_outbox_deliveries AS delivery "
                            " ON delivery.event_id=event.event_id "
                            " WHERE event.external_system=:external_system "
                            " AND delivery.status NOT IN ('delivered','superseded')) "
                            "AS delivery_backlog, "
                            "(SELECT COALESCE(max(relay_order),0) "
                            " FROM ops.poi_cache_target_outbox_events "
                            " WHERE external_system=:external_system "
                            " AND event_type='cache_target.state_applied') AS material_watermark"
                        ),
                        {"external_system": EVIDENCE_EXTERNAL_SYSTEM},
                    )
                )
                .mappings()
                .one()
            )
            gc_backlog = await observe_expired_cache_target_snapshot_backlog(session)
            observation_row = (
                (
                    await session.execute(
                        text(
                            "SELECT dagster_run_id, referenced_items, referenced_headers "
                            "FROM ops.poi_cache_target_snapshot_gc_observations "
                            "WHERE dagster_run_id=:observation_run_id"
                        ),
                        {"observation_run_id": observation_run_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
    finally:
        await engine.dispose()

    stream = dict(stream_row or {})
    snapshot = dict(snapshot_row or {})
    backlogs = dict(backlog_row)
    try:
        live_merkle_root = _snapshot_merkle(list(source_rows))
        snapshot_item_merkle_root = _snapshot_merkle(list(snapshot_item_rows))
    except (TypeError, ValueError):
        live_merkle_root = "invalid"
        snapshot_item_merkle_root = "invalid"

    consumer_id = stream.get("consumer_id")
    restore_epoch = _int(stream, "restore_epoch")
    control_version = _int(stream, "control_version")
    snapshot_count = _int(snapshot, "item_count")
    snapshot_merkle = snapshot.get("merkle_root")
    high_watermark = _int(snapshot, "high_watermark_relay_order")
    material_watermark = _int(backlogs, "material_watermark")
    reconciliation_backlog = _int(backlogs, "reconciliation_backlog")
    outbox_backlog = _int(backlogs, "outbox_backlog")
    claim_backlog = _int(backlogs, "claim_backlog")
    delivery_backlog = _int(backlogs, "delivery_backlog")
    observation = dict(observation_row or {})
    checks = [
        identity_check,
        _image_revision_check(request),
        check("schema_final_evidence", expected=TARGET_SCHEMA, observed=schema),
        check("pinvi_stream_exists", expected=True, observed=stream_row is not None),
        check(
            "pinvi_external_system",
            expected=EVIDENCE_EXTERNAL_SYSTEM,
            observed=stream.get("external_system"),
        ),
        check("pinvi_stream_ready", expected="ready", observed=stream.get("status")),
        check("pinvi_consumer_enabled", expected=True, observed=stream.get("consumer_enabled")),
        check("pinvi_stream_unblocked", expected=None, observed=stream.get("blocked_event_id")),
        check(
            "pinvi_consumer_id_canonical",
            expected=True,
            observed=(
                isinstance(consumer_id, str)
                and bool(consumer_id)
                and consumer_id == consumer_id.strip()
            ),
        ),
        check("pinvi_restore_epoch_positive", expected=True, observed=restore_epoch > 0),
        check("pinvi_control_version_positive", expected=True, observed=control_version > 0),
        check("pinvi_snapshot_exists", expected=True, observed=snapshot_row is not None),
        check("pinvi_snapshot_unexpired", expected=True, observed=snapshot.get("valid")),
        check(
            "pinvi_snapshot_external_system",
            expected=EVIDENCE_EXTERNAL_SYSTEM,
            observed=snapshot.get("external_system"),
        ),
        check(
            "pinvi_snapshot_restore_epoch",
            expected=restore_epoch,
            observed=_int(snapshot, "restore_epoch"),
        ),
        check("pinvi_snapshot_count_fresh", expected=len(source_rows), observed=snapshot_count),
        check(
            "pinvi_snapshot_item_count",
            expected=snapshot_count,
            observed=len(snapshot_item_rows),
        ),
        check(
            "pinvi_snapshot_merkle_format",
            expected=True,
            observed=_is_lowercase_sha256(snapshot_merkle),
        ),
        check("pinvi_snapshot_merkle_fresh", expected=live_merkle_root, observed=snapshot_merkle),
        check(
            "pinvi_snapshot_item_merkle",
            expected=snapshot_merkle,
            observed=snapshot_item_merkle_root,
        ),
        check(
            "pinvi_snapshot_items_match_live",
            expected=live_merkle_root,
            observed=snapshot_item_merkle_root,
        ),
        check(
            "pinvi_snapshot_material_watermark_fresh",
            expected=material_watermark,
            observed=_int(snapshot, "material_high_watermark_relay_order"),
        ),
        check(
            "pinvi_snapshot_watermark_order",
            expected=True,
            observed=high_watermark >= material_watermark >= 0,
        ),
        check("reconciliation_backlog_zero", expected=0, observed=reconciliation_backlog),
        check("outbox_backlog_zero", expected=0, observed=outbox_backlog),
        check("claim_backlog_zero", expected=0, observed=claim_backlog),
        check("delivery_backlog_zero", expected=0, observed=delivery_backlog),
        check("gc_remaining_items_final", expected=0, observed=gc_backlog.remaining_items),
        check("gc_remaining_headers_final", expected=0, observed=gc_backlog.remaining_headers),
        check("gc_observation_exists", expected=True, observed=observation_row is not None),
        check(
            "gc_observation_run_fresh",
            expected=observation_run_id,
            observed=observation.get("dagster_run_id"),
        ),
        check(
            "gc_observation_referenced_items_final",
            expected=gc_backlog.referenced_items,
            observed=observation.get("referenced_items"),
        ),
        check(
            "gc_observation_referenced_headers_final",
            expected=gc_backlog.referenced_headers,
            observed=observation.get("referenced_headers"),
        ),
    ]

    evidence: CacheTargetEvidence | None = None
    if all_pass(checks):
        evidence = validate_cache_target_evidence(
            {
                "contract_version": EVIDENCE_CONTRACT_VERSION,
                "external_system": EVIDENCE_EXTERNAL_SYSTEM,
                "stream_state": "ready",
                "consumer_id": consumer_id,
                "restore_epoch": restore_epoch,
                "control_version": control_version,
                "stream_control_etag": cache_target_stream_entity_tag(
                    EVIDENCE_EXTERNAL_SYSTEM, control_version
                ),
                "high_watermark_cursor": cache_target_event_cursor(high_watermark),
                "snapshot_count": snapshot_count,
                "snapshot_merkle_root": snapshot_merkle,
                "reconciliation_backlog_count": reconciliation_backlog,
                "outbox_backlog_count": outbox_backlog,
                "claim_backlog_count": claim_backlog,
                "delivery_backlog_count": delivery_backlog,
            }
        )
    return (
        live_request,
        identity_check,
        evidence,
        checks,
        {
            "claim_backlog": max(0, claim_backlog),
            "delivery_backlog": max(0, delivery_backlog),
            "outbox_backlog": max(0, outbox_backlog),
            "reconciliation_backlog": max(0, reconciliation_backlog),
            "snapshot_count": max(0, snapshot_count),
        },
    )


__all__ = [
    "EVIDENCE_CONTRACT_VERSION",
    "EVIDENCE_EXTERNAL_SYSTEM",
    "cache_target_gc_observation_run_id",
    "collect_cache_target_final_evidence",
    "run_gc",
]
