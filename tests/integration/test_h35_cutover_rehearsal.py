"""격리 PostGIS에서 수행하는 H35 0063→0079 전체 리허설."""

from __future__ import annotations

import asyncio
import csv
import json
import socket
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.cli._h35_cache_target import cache_target_gc_observation_run_id
from kortravelmap.cli._h35_contract import (
    CONTRACT_VERSION,
    H35Request,
    Operation,
    Receipt,
    compute_database_identity,
    parse_request,
    receipt_digest,
)
from kortravelmap.cli._h35_schema import TARGET_SCHEMA, partial_probe
from kortravelmap.cli.h35_cutover import _execute
from kortravelmap.core.cache_target_stream import SnapshotMerkleRowV1, snapshot_merkle_root
from kortravelmap.infra.curation_link_basis import trusted_basis_sql
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_PRE_REVISION = "0063_pipeline_root_id"
_TARGET_REVISION = TARGET_SCHEMA
_SOURCE_REVISION = "1" * 40
_TRANSACTION_ID = "00000000-0000-0000-0000-000000000001"
_SOURCE_RULE_PUBLIC = 3_043
_LEGACY_PUBLIC = 222
_PINVI_CONSUMER_ID = "pinvi-generation-7"
_CURRENT_SNAPSHOT_ID = "10000000-0000-0000-0000-000000000001"
_EXPIRED_UNREFERENCED_SNAPSHOT_ID = "10000000-0000-0000-0000-000000000002"
_EXPIRED_REFERENCED_SNAPSHOT_ID = "10000000-0000-0000-0000-000000000003"
_CURRENT_RECONCILIATION_ID = "20000000-0000-0000-0000-000000000001"
_EXPIRED_RECONCILIATION_ID = "20000000-0000-0000-0000-000000000002"
_OUTBOX_EVENT_ID = "30000000-0000-0000-0000-000000000001"
_CLAIM_ID = "40000000-0000-0000-0000-000000000001"
_TARGET_KEY = "pinvi-final-target"
_SOURCE_FINGERPRINT = "a" * 64
_LIVE_MERKLE_ROOT = snapshot_merkle_root(
    [
        SnapshotMerkleRowV1(
            external_system="pinvi",
            target_key=_TARGET_KEY,
            state="deleted",
            source_generation=1,
            source_payload_fingerprint=_SOURCE_FINGERPRINT,
        )
    ]
)
_MIXED_MERKLE_ROOT = snapshot_merkle_root(
    [
        SnapshotMerkleRowV1(
            external_system="pinvi",
            target_key="mixed-target",
            state="deleted",
            source_generation=1,
            source_payload_fingerprint=_SOURCE_FINGERPRINT,
        )
    ]
)


def _run_alembic(dsn: str, revision: str) -> None:
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(config, revision)


def _explicit_feature_ids() -> tuple[str, ...]:
    manifest = json.loads(
        (_ROOT / "resources" / "curations" / "manifest.json").read_text(encoding="utf-8")
    )
    identifiers: list[str] = []
    for entry in manifest["files"]:
        if entry.get("kind") != "official_seed":
            continue
        with (_ROOT / "resources" / "curations" / entry["path"]).open(
            encoding="utf-8-sig",
            newline="",
        ) as stream:
            identifiers.extend(
                row["feature_id"].strip()
                for row in csv.DictReader(stream)
                if row["feature_id"].strip()
            )
    assert len(identifiers) == _LEGACY_PUBLIC
    return tuple(identifiers)


async def _create_database(admin_dsn: str) -> tuple[str, str]:
    database = f"h35_rehearsal_{uuid4().hex}"
    dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    engine = make_async_engine(admin_dsn)
    try:
        async with engine.connect() as raw_connection:
            connection = await raw_connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        await engine.dispose()
    return database, dsn


async def _drop_database(admin_dsn: str, database: str) -> None:
    engine = make_async_engine(admin_dsn)
    try:
        async with engine.connect() as raw_connection:
            connection = await raw_connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
    finally:
        await engine.dispose()


async def _seed_exact_pre_cutover_surface(dsn: str) -> None:
    explicit_ids = _explicit_feature_ids()
    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category, marker_icon, marker_color
                    )
                    SELECT
                        'f_h35_source_' || value::text,
                        'place',
                        'H35 source fixture ' || value::text,
                        '01070100',
                        'place',
                        'P-01'
                    FROM generate_series(1, :count) AS value
                    """
                ),
                {"count": _SOURCE_RULE_PUBLIC},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category, marker_icon, marker_color
                    )
                    SELECT DISTINCT
                        feature_id,
                        'place',
                        'H35 CSV fixture ' || feature_id,
                        '01070100',
                        'place',
                        'P-01'
                    FROM unnest(CAST(:feature_ids AS text[])) AS feature_id
                    ON CONFLICT (feature_id) DO NOTHING
                    """
                ),
                {"feature_ids": list(explicit_ids)},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO provider_sync.source_entities (
                        source_entity_key, provider, dataset_key,
                        source_entity_type, source_entity_id,
                        first_seen_at, last_seen_at
                    ) VALUES (
                        'h35-fixture::entity', 'h35-fixture', 'source-rule',
                        'place', 'source-rule', now(), now()
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO provider_sync.source_records (
                        source_record_key, source_entity_key, provider, dataset_key,
                        source_entity_type, source_entity_id, raw_payload_hash, fetched_at
                    ) VALUES (
                        'h35-fixture::record', 'h35-fixture::entity',
                        'h35-fixture', 'source-rule', 'place', 'source-rule',
                        :payload_hash, now()
                    )
                    """
                ),
                {"payload_hash": "a" * 64},
            )
            await connection.execute(
                text(
                    """
                    UPDATE provider_sync.source_entities
                    SET current_source_record_key='h35-fixture::record'
                    WHERE source_entity_key='h35-fixture::entity'
                    """
                )
            )
            source_id = await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_sources (
                        provider, dataset_key, source_name, source_kind,
                        update_cycle, provider_status
                    ) VALUES (
                        'h35-fixture', 'source-rule', 'H35 fixture', 'internal',
                        'one_time', 'implemented'
                    ) RETURNING source_id
                    """
                )
            )
            theme_id = await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group, visibility
                    ) VALUES (
                        'h35-source-rule-fixture', 'H35 source rule fixture',
                        'test', 'public'
                    ) RETURNING theme_id
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.curated_features (
                        theme_id, feature_id, source_id, source_record_key,
                        curation_status, selection_origin, selected_by,
                        display_title, content_version
                    )
                    SELECT
                        CAST(:theme_id AS uuid),
                        'f_h35_source_' || value::text,
                        CAST(:source_id AS uuid),
                        'h35-fixture::record',
                        'curated', 'source_rule', 'system:h35-fixture',
                        'H35 source rule fixture', 1
                    FROM generate_series(1, :count) AS value
                    """
                ),
                {
                    "theme_id": str(theme_id),
                    "source_id": str(source_id),
                    "count": _SOURCE_RULE_PUBLIC,
                },
            )
            legacy_theme_id = await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                        theme_slug, theme_name, theme_group, visibility
                    ) VALUES (
                        'h35-legacy-fixture', 'H35 legacy fixture', 'test', 'public'
                    ) RETURNING theme_id
                    """
                )
            )
            legacy_collection_id = await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curation_collections (
                        collection_key, theme_id, title, status, visibility
                    ) VALUES (
                        'h35-legacy-fixture', CAST(:theme_id AS uuid),
                        'H35 legacy fixture', 'published', 'public'
                    ) RETURNING collection_id
                    """
                ),
                {"theme_id": str(legacy_theme_id)},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.curation_items (
                        collection_id, feature_id, external_item_id,
                        place_name, status, sort_order, created_by
                    )
                    SELECT
                        CAST(:collection_id AS uuid), feature_id,
                        'legacy-' || ordinal::text,
                        'H35 legacy fixture ' || ordinal::text,
                        'included', ordinal, 'system:h35-fixture'
                    FROM unnest(CAST(:feature_ids AS text[]))
                         WITH ORDINALITY AS item(feature_id, ordinal)
                    """
                ),
                {
                    "collection_id": str(legacy_collection_id),
                    "feature_ids": list(explicit_ids),
                },
            )
    finally:
        await engine.dispose()


async def _database_identity(dsn: str) -> str:
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT current_database() AS database, "
                            "(pg_control_system()).system_identifier::text AS system_identifier"
                        )
                    )
                )
                .mappings()
                .one()
            )
    finally:
        await engine.dispose()
    return compute_database_identity(
        transaction_id=_TRANSACTION_ID,
        database=str(row["database"]),
        system_identifier=str(row["system_identifier"]),
    )


def _request(
    operation: Operation,
    *,
    database_identity: str,
    prior: Receipt | None,
) -> H35Request:
    raw = {
        "contract_version": CONTRACT_VERSION,
        "operation": operation,
        "transaction_id": _TRANSACTION_ID,
        "source_revision": _SOURCE_REVISION,
        "database_identity": database_identity,
        "prior_receipt": prior,
        "prior_receipt_digest": receipt_digest(prior) if prior is not None else None,
    }
    return parse_request(json.dumps(raw), operation=operation)


async def _schema_and_public_count(dsn: str) -> tuple[str, int]:
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as connection:
            schema = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            public = await connection.scalar(
                text(
                    """
                    SELECT count(*)::bigint
                    FROM feature.curation_items AS item
                    JOIN feature.curation_collections AS collection
                      ON collection.collection_id=item.collection_id
                    JOIN feature.curated_themes AS theme ON theme.theme_id=collection.theme_id
                    WHERE item.archived_at IS NULL AND collection.archived_at IS NULL
                      AND item.status='included' AND collection.status='published'
                      AND collection.visibility='public' AND theme.visibility='public'
                      AND item.feature_id IS NOT NULL
                    """
                )
            )
    finally:
        await engine.dispose()
    return str(schema), int(public or 0)


async def _external_event_count(dsn: str) -> int:
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as connection:
            return int(
                (
                    await connection.scalar(
                        text(
                            """
                            SELECT
                                (SELECT count(*) FROM ops.poi_cache_target_source_events)
                              + (SELECT count(*) FROM ops.poi_cache_target_outbox_events)
                              + (SELECT count(*) FROM ops.poi_cache_target_outbox_claim_events)
                            """
                        )
                    )
                )
                or 0
            )
    finally:
        await engine.dispose()


async def _seed_generation7_final_state(dsn: str) -> None:
    """GC와 final evidence가 소비할 PinVi generation-7 terminal 상태를 만든다."""
    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_streams (
                      external_system, consumer_id, restore_epoch, control_version,
                      status, consumer_enabled
                    ) VALUES ('pinvi', :consumer_id, 1, 1, 'ready', true)
                    """
                ),
                {"consumer_id": _PINVI_CONSUMER_ID},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_source_heads (
                      external_system, target_key, target_id, state, restore_epoch,
                      source_generation, source_payload_fingerprint, target_sequence
                    ) VALUES (
                      'pinvi', :target_key, NULL, 'deleted', 1, 1, :fingerprint, 1
                    )
                    """
                ),
                {"target_key": _TARGET_KEY, "fingerprint": _SOURCE_FINGERPRINT},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_snapshots (
                      snapshot_id, external_system, restore_epoch,
                      high_watermark_relay_order, material_high_watermark_relay_order,
                      item_count, merkle_root, created_at, expires_at
                    ) VALUES
                      (CAST(:current AS uuid), 'pinvi', 1, 0, 0, 1, :root,
                       now(), now() + interval '2 hours'),
                      (CAST(:expired_unref AS uuid), 'pinvi', 1, 0, 0, 1, :root,
                       now() - interval '4 hours', now() - interval '3 hours'),
                      (CAST(:expired_ref AS uuid), 'pinvi', 1, 0, 0, 1, :root,
                       now() - interval '4 hours', now() - interval '3 hours')
                    """
                ),
                {
                    "current": _CURRENT_SNAPSHOT_ID,
                    "expired_unref": _EXPIRED_UNREFERENCED_SNAPSHOT_ID,
                    "expired_ref": _EXPIRED_REFERENCED_SNAPSHOT_ID,
                    "root": _LIVE_MERKLE_ROOT,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_snapshot_items (
                      snapshot_id, row_number, external_system, target_key, state,
                      source_generation, source_payload_fingerprint
                    )
                    SELECT snapshot_id, 1, 'pinvi', :target_key, 'deleted', 1, :fingerprint
                    FROM unnest(CAST(:snapshot_ids AS uuid[])) AS snapshot_id
                    """
                ),
                {
                    "snapshot_ids": [
                        _CURRENT_SNAPSHOT_ID,
                        _EXPIRED_UNREFERENCED_SNAPSHOT_ID,
                        _EXPIRED_REFERENCED_SNAPSHOT_ID,
                    ],
                    "target_key": _TARGET_KEY,
                    "fingerprint": _SOURCE_FINGERPRINT,
                },
            )
            command_ids = (
                (
                    await connection.execute(
                        text(
                            """
                            INSERT INTO ops.domain_commands (
                              actor, operation, idempotency_key, request_fingerprint
                            ) VALUES
                              ('system:h35', 'cache-target.reconcile',
                               '50000000-0000-0000-0000-000000000001', :fingerprint),
                              ('system:h35', 'cache-target.reconcile',
                               '50000000-0000-0000-0000-000000000002', :fingerprint)
                            RETURNING command_id
                            """
                        ),
                        {"fingerprint": "b" * 64},
                    )
                )
                .scalars()
                .all()
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_reconciliation_requests (
                      request_id, external_system, command_id, reason, status,
                      phase_version, snapshot_id, expected_merkle_root,
                      actual_merkle_root, started_at, completed_at
                    ) VALUES
                      (CAST(:current_request AS uuid), 'pinvi', :current_command,
                       'generation 7 current snapshot', 'succeeded', 2,
                       CAST(:current_snapshot AS uuid), :root, :root, now(), now()),
                      (CAST(:expired_request AS uuid), 'pinvi', :expired_command,
                       'generation 7 referenced snapshot', 'succeeded', 2,
                       CAST(:expired_snapshot AS uuid), :root, :root, now(), now())
                    """
                ),
                {
                    "current_request": _CURRENT_RECONCILIATION_ID,
                    "current_command": int(command_ids[0]),
                    "current_snapshot": _CURRENT_SNAPSHOT_ID,
                    "expired_request": _EXPIRED_RECONCILIATION_ID,
                    "expired_command": int(command_ids[1]),
                    "expired_snapshot": _EXPIRED_REFERENCED_SNAPSHOT_ID,
                    "root": _LIVE_MERKLE_ROOT,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_outbox_events (
                      event_id, event_type, event_scope, external_system, target_key,
                      target_id, restore_epoch, source_generation, target_sequence,
                      source_payload_fingerprint, payload_fingerprint, payload,
                      reconciliation_request_id
                    ) VALUES (
                      CAST(:event_id AS uuid), 'cache_target.reconciled', 'stream',
                      'pinvi', NULL, NULL, 1, NULL, NULL, :source_fingerprint,
                      :payload_fingerprint, CAST(:payload AS jsonb),
                      CAST(:request_id AS uuid)
                    )
                    """
                ),
                {
                    "event_id": _OUTBOX_EVENT_ID,
                    "source_fingerprint": _SOURCE_FINGERPRINT,
                    "payload_fingerprint": "c" * 64,
                    "payload": json.dumps({"status": "succeeded"}),
                    "request_id": _CURRENT_RECONCILIATION_ID,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_outbox_deliveries (
                      event_id, status, delivered_at
                    ) VALUES (CAST(:event_id AS uuid), 'delivered', now())
                    """
                ),
                {"event_id": _OUTBOX_EVENT_ID},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_outbox_claims (
                      claim_id, external_system, consumer_id, idempotency_key,
                      request_fingerprint, lease_token, status, first_relay_order,
                      last_relay_order, acked_through_relay_order, lease_expires_at,
                      completed_at
                    ) VALUES (
                      CAST(:claim_id AS uuid), 'pinvi', :consumer_id,
                      '60000000-0000-0000-0000-000000000001', :fingerprint,
                      '60000000-0000-0000-0000-000000000002', 'acked', 1, 1, 1,
                      now() - interval '1 minute', now()
                    )
                    """
                ),
                {
                    "claim_id": _CLAIM_ID,
                    "consumer_id": _PINVI_CONSUMER_ID,
                    "fingerprint": "d" * 64,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_outbox_claim_events (
                      claim_id, event_id, relay_order, position, consumer_applied_at,
                      prefix_acked_at, ack_payload_fingerprint
                    ) VALUES (
                      CAST(:claim_id AS uuid), CAST(:event_id AS uuid), 1, 1,
                      now(), now(), :fingerprint
                    )
                    """
                ),
                {
                    "claim_id": _CLAIM_ID,
                    "event_id": _OUTBOX_EVENT_ID,
                    "fingerprint": "e" * 64,
                },
            )
    finally:
        await engine.dispose()


async def _snapshot_gc_state(dsn: str) -> dict[str, int]:
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            SELECT
                              (SELECT count(*) FROM ops.poi_cache_target_snapshots)
                                AS headers,
                              (SELECT count(*) FROM ops.poi_cache_target_snapshot_items)
                                AS items,
                              (SELECT count(*) FROM ops.poi_cache_target_snapshots
                               WHERE snapshot_id=CAST(:unreferenced AS uuid))
                                AS expired_unreferenced,
                              (SELECT count(*) FROM ops.poi_cache_target_snapshots
                               WHERE snapshot_id=CAST(:referenced AS uuid))
                                AS expired_referenced,
                              (SELECT count(*)
                               FROM ops.poi_cache_target_snapshot_gc_observations
                               WHERE dagster_run_id=:run_id) AS observations
                            """
                        ),
                        {
                            "unreferenced": _EXPIRED_UNREFERENCED_SNAPSHOT_ID,
                            "referenced": _EXPIRED_REFERENCED_SNAPSHOT_ID,
                            "run_id": cache_target_gc_observation_run_id(_TRANSACTION_ID),
                        },
                    )
                )
                .mappings()
                .one()
            )
            return {key: int(value) for key, value in row.items()}
    finally:
        await engine.dispose()


async def _database_state_digest(dsn: str) -> str:
    """verify 호출 전후 generation-7 DB row의 exact mutation-zero digest."""
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as connection:
            value = await connection.scalar(
                text(
                    """
                    SELECT md5(concat_ws('|',
                      COALESCE((SELECT jsonb_agg(to_jsonb(row_value) ORDER BY external_system)
                        FROM (SELECT * FROM ops.poi_cache_target_streams) AS row_value)::text,
                        'null'),
                      COALESCE((SELECT jsonb_agg(to_jsonb(row_value)
                                                ORDER BY external_system, target_key)
                        FROM (SELECT * FROM ops.poi_cache_target_source_heads) AS row_value)::text,
                        'null'),
                      COALESCE((SELECT jsonb_agg(to_jsonb(row_value) ORDER BY snapshot_id)
                        FROM (SELECT * FROM ops.poi_cache_target_snapshots) AS row_value)::text,
                        'null'),
                      COALESCE((SELECT jsonb_agg(to_jsonb(row_value)
                                                ORDER BY snapshot_id, row_number)
                        FROM (SELECT * FROM ops.poi_cache_target_snapshot_items)
                          AS row_value)::text,
                        'null'),
                      COALESCE((SELECT jsonb_agg(to_jsonb(row_value) ORDER BY request_id)
                        FROM (SELECT * FROM ops.poi_cache_target_reconciliation_requests)
                          AS row_value)::text, 'null'),
                      COALESCE((SELECT jsonb_agg(to_jsonb(row_value) ORDER BY event_id)
                        FROM (SELECT * FROM ops.poi_cache_target_outbox_events) AS row_value)::text,
                        'null'),
                      COALESCE((SELECT jsonb_agg(to_jsonb(row_value) ORDER BY claim_id)
                        FROM (SELECT * FROM ops.poi_cache_target_outbox_claims) AS row_value)::text,
                        'null'),
                      COALESCE((SELECT jsonb_agg(to_jsonb(row_value) ORDER BY event_id)
                        FROM (SELECT * FROM ops.poi_cache_target_outbox_deliveries)
                          AS row_value)::text,
                        'null'),
                      COALESCE((SELECT jsonb_agg(to_jsonb(row_value) ORDER BY observation_id)
                        FROM (SELECT * FROM ops.poi_cache_target_snapshot_gc_observations)
                          AS row_value)::text, 'null')
                    ))
                    """
                )
            )
            assert isinstance(value, str)
            return value
    finally:
        await engine.dispose()


async def _execute_sql(dsn: str, *statements: str) -> None:
    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


async def _sql_scalar(dsn: str, query: str) -> str:
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as connection:
            value = await connection.scalar(text(query))
            assert isinstance(value, str)
            return value
    finally:
        await engine.dispose()


async def _assert_verify_rejected_without_mutation(
    dsn: str,
    *,
    identity: str,
    gc_receipt: Receipt,
    failed_check_prefix: str,
) -> Receipt:
    before = await _database_state_digest(dsn)
    rejected = await _execute(_request("verify", database_identity=identity, prior=gc_receipt))
    assert rejected["status"] == "rejected"
    assert rejected["cache_target_evidence"] is None
    assert rejected["runtime_mutation_count"] == 0
    assert rejected["external_event_count"] == 0
    assert any(
        str(value["name"]).startswith(failed_check_prefix) and value["passed"] is False
        for value in rejected["checks"]
    )
    assert await _database_state_digest(dsn) == before
    return rejected


async def _assert_scope_validator_truth_table(dsn: str) -> None:
    """0052→0074→0075 delegate chain의 여섯 scope 의미를 end-to-end 고정한다."""
    cases: tuple[tuple[str, str, dict[str, object], tuple[bool, bool, bool]], ...] = (
        (
            "feature_ids_valid",
            "feature_ids",
            {"type": "feature_ids", "feature_ids": ["feature-a", "feature-b"]},
            (True, True, True),
        ),
        (
            "feature_ids_duplicate",
            "feature_ids",
            {"type": "feature_ids", "feature_ids": ["feature-a", "feature-a"]},
            (False, False, False),
        ),
        (
            "center_radius_valid",
            "center_radius",
            {
                "type": "center_radius",
                "center": {"lon": 127.0, "lat": 37.5},
                "radius_km": 5,
            },
            (True, True, True),
        ),
        (
            "center_radius_invalid_latitude",
            "center_radius",
            {
                "type": "center_radius",
                "center": {"lon": 127.0, "lat": 91},
                "radius_km": 5,
            },
            (False, False, False),
        ),
        (
            "sigungu_by_radius_valid",
            "sigungu_by_radius",
            {
                "type": "sigungu_by_radius",
                "center": {"lon": 126.978, "lat": 37.5665},
                "radius_km": 20,
                "match": "intersects",
            },
            (True, True, True),
        ),
        (
            "sigungu_by_radius_invalid_match",
            "sigungu_by_radius",
            {
                "type": "sigungu_by_radius",
                "center": {"lon": 126.978, "lat": 37.5665},
                "radius_km": 20,
                "match": "contains",
            },
            (False, False, False),
        ),
        (
            "bbox_valid",
            "bbox",
            {
                "type": "bbox",
                "min_lon": 126.0,
                "min_lat": 36.0,
                "max_lon": 128.0,
                "max_lat": 38.0,
            },
            (True, True, True),
        ),
        (
            "bbox_invalid_order",
            "bbox",
            {
                "type": "bbox",
                "min_lon": 128.0,
                "min_lat": 36.0,
                "max_lon": 126.0,
                "max_lat": 38.0,
            },
            (False, False, False),
        ),
        (
            "provider_dataset_valid",
            "provider_dataset",
            {
                "type": "provider_dataset",
                "provider": "python-kma-api",
                "dataset_key": "kma_short_forecast",
                "sync_scope": "target_grids",
            },
            (True, True, True),
        ),
        (
            "provider_dataset_invalid_blank",
            "provider_dataset",
            {
                "type": "provider_dataset",
                "provider": "",
                "dataset_key": "kma_short_forecast",
            },
            (False, False, False),
        ),
        (
            "cache_target_generation7_valid",
            "cache_target_keys",
            {
                "type": "cache_target_keys",
                "external_system": "pinvi",
                "target_keys": ["target-a"],
                "radius_km": 10,
                "scope_mode": "center_radius",
            },
            (True, True, True),
        ),
        (
            "cache_target_generation7_duplicate",
            "cache_target_keys",
            {
                "type": "cache_target_keys",
                "external_system": "pinvi",
                "target_keys": ["target-a", "target-a"],
                "scope_mode": "sigungu_by_radius",
            },
            (False, False, False),
        ),
        (
            "cache_target_generation7_512_boundary",
            "cache_target_keys",
            {
                "type": "cache_target_keys",
                "external_system": "pinvi",
                "target_keys": ["x" * 512],
                "scope_mode": "center_radius",
            },
            (True, False, False),
        ),
    )
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as connection:
            for label, scope_type, scope, expected in cases:
                row = (
                    await connection.execute(
                        text(
                            "SELECT "
                            "ops.is_valid_feature_update_scope(:scope_type, "
                            "CAST(:scope AS jsonb)), "
                            "ops.is_valid_feature_update_scope_0074(:scope_type, "
                            "CAST(:scope AS jsonb)), "
                            "ops.is_valid_feature_update_scope_0052(:scope_type, "
                            "CAST(:scope AS jsonb))"
                        ),
                        {"scope_type": scope_type, "scope": json.dumps(scope)},
                    )
                ).one()
                assert tuple(row) == expected, label
    finally:
        await engine.dispose()


async def _assert_scope_delegate_drift_matrix(
    dsn: str,
    *,
    identity: str,
    gc_receipt: Receipt,
) -> None:
    for function_name in (
        "is_valid_feature_update_scope_0074",
        "is_valid_feature_update_scope_0052",
    ):
        function_definition = await _sql_scalar(
            dsn,
            f"SELECT pg_get_functiondef('ops.{function_name}(text,jsonb)'::regprocedure)",
        )
        await _execute_sql(
            dsn,
            f"""
            CREATE OR REPLACE FUNCTION ops.{function_name}(
              p_scope_type text, p_scope jsonb
            ) RETURNS boolean
            LANGUAGE sql VOLATILE CALLED ON NULL INPUT SECURITY DEFINER LEAKPROOF
            PARALLEL UNSAFE SET search_path TO pg_catalog
            AS $function$ SELECT false $function$
            """,
        )
        await _assert_verify_rejected_without_mutation(
            dsn,
            identity=identity,
            gc_receipt=gc_receipt,
            failed_check_prefix="0075_0079_functions_semantic",
        )
        await _execute_sql(dsn, function_definition)

        saved_name = f"{function_name}_h35_saved"
        await _execute_sql(
            dsn,
            f"ALTER FUNCTION ops.{function_name}(text,jsonb) RENAME TO {saved_name}",
            f"""
            CREATE FUNCTION ops.{function_name}(p_scope_type text, p_scope text)
            RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE
            AS $function$ SELECT p_scope_type || p_scope $function$
            """,
        )
        await _assert_verify_rejected_without_mutation(
            dsn,
            identity=identity,
            gc_receipt=gc_receipt,
            failed_check_prefix="0075_0079_functions_semantic",
        )
        await _execute_sql(
            dsn,
            f"DROP FUNCTION ops.{function_name}(text,text)",
            f"ALTER FUNCTION ops.{saved_name}(text,jsonb) RENAME TO {function_name}",
        )


async def _assert_structural_negative_matrix(
    dsn: str,
    *,
    identity: str,
    gc_receipt: Receipt,
) -> None:
    constraint_name = "ck_poi_cache_target_streams_ck_cache_target_streams_versions"
    constraint_definition = await _sql_scalar(
        dsn,
        "SELECT pg_get_constraintdef(oid, true) FROM pg_constraint "
        "WHERE conrelid='ops.poi_cache_target_streams'::regclass "
        f"AND conname='{constraint_name}'",
    )
    await _execute_sql(
        dsn,
        f"ALTER TABLE ops.poi_cache_target_streams DROP CONSTRAINT {constraint_name}",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="0075_0079_constraints_semantic",
    )
    await _execute_sql(
        dsn,
        "ALTER TABLE ops.poi_cache_target_streams "
        f"ADD CONSTRAINT {constraint_name} CHECK (restore_epoch > 0)",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="0075_0079_constraints_semantic",
    )
    await _execute_sql(
        dsn,
        f"ALTER TABLE ops.poi_cache_target_streams DROP CONSTRAINT {constraint_name}",
        "ALTER TABLE ops.poi_cache_target_streams "
        f"ADD CONSTRAINT {constraint_name} {constraint_definition}",
    )

    index_definition = await _sql_scalar(
        dsn,
        "SELECT pg_get_indexdef('ops.idx_cache_target_source_heads_target'::regclass)",
    )
    await _execute_sql(
        dsn,
        "DROP INDEX ops.idx_cache_target_source_heads_target",
        "CREATE INDEX idx_cache_target_source_heads_target "
        "ON ops.poi_cache_target_source_heads (target_key)",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="0075_0079_indexes_semantic",
    )
    await _execute_sql(
        dsn,
        "DROP INDEX ops.idx_cache_target_source_heads_target",
        index_definition,
    )

    await _execute_sql(
        dsn,
        "UPDATE pg_catalog.pg_index SET indisvalid=false, indisready=false "
        "WHERE indexrelid='ops.idx_cache_target_snapshots_expiry'::regclass",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="0075_0079_indexes_semantic",
    )
    await _execute_sql(
        dsn,
        "UPDATE pg_catalog.pg_index SET indisvalid=true, indisready=true "
        "WHERE indexrelid='ops.idx_cache_target_snapshots_expiry'::regclass",
    )

    await _execute_sql(
        dsn,
        "ALTER TABLE ops.poi_cache_target_source_events "
        "DISABLE TRIGGER trg_poi_cache_target_source_events_append_only",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="0075_0079_triggers_semantic",
    )
    await _execute_sql(
        dsn,
        "ALTER TABLE ops.poi_cache_target_source_events "
        "ENABLE TRIGGER trg_poi_cache_target_source_events_append_only",
    )

    trigger_definition = await _sql_scalar(
        dsn,
        "SELECT pg_get_triggerdef(oid, true) FROM pg_trigger "
        "WHERE tgrelid='ops.poi_cache_target_source_events'::regclass "
        "AND tgname='trg_poi_cache_target_source_events_append_only'",
    )
    await _execute_sql(
        dsn,
        "DROP TRIGGER trg_poi_cache_target_source_events_append_only "
        "ON ops.poi_cache_target_source_events",
        "CREATE TRIGGER trg_poi_cache_target_source_events_append_only "
        "BEFORE DELETE ON ops.poi_cache_target_source_events FOR EACH ROW "
        "EXECUTE FUNCTION ops.reject_cache_target_history_mutation()",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="0075_0079_triggers_semantic",
    )
    await _execute_sql(
        dsn,
        "DROP TRIGGER trg_poi_cache_target_source_events_append_only "
        "ON ops.poi_cache_target_source_events",
        trigger_definition,
    )

    function_definition = await _sql_scalar(
        dsn,
        "SELECT pg_get_functiondef('ops.assign_cache_target_outbox_relay_order()'::regprocedure)",
    )
    await _execute_sql(
        dsn,
        """
        CREATE OR REPLACE FUNCTION ops.assign_cache_target_outbox_relay_order()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'ops'
        AS $function$
        BEGIN
          NEW.relay_order := 1;
          RETURN NEW;
        END;
        $function$
        """,
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="0075_0079_functions_semantic",
    )
    await _execute_sql(dsn, function_definition)
    await _assert_scope_delegate_drift_matrix(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
    )


async def _insert_negative_snapshot(
    dsn: str,
    *,
    snapshot_id: str,
    restore_epoch: int,
    target_key: str,
    merkle_root: str,
    expired: bool = False,
) -> None:
    created_at_sql = "now() - interval '2 hours'" if expired else "now() + interval '1 minute'"
    expires_at_sql = "now() - interval '1 hour'" if expired else "now() + interval '2 hours'"
    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    f"""
                    INSERT INTO ops.poi_cache_target_snapshots (
                      snapshot_id, external_system, restore_epoch,
                      high_watermark_relay_order, material_high_watermark_relay_order,
                      item_count, merkle_root, created_at, expires_at
                    ) VALUES (
                      CAST(:snapshot_id AS uuid), 'pinvi', :restore_epoch, 1, 0, 1,
                      :merkle_root, {created_at_sql}, {expires_at_sql}
                    )
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "restore_epoch": restore_epoch,
                    "merkle_root": merkle_root,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.poi_cache_target_snapshot_items (
                      snapshot_id, row_number, external_system, target_key, state,
                      source_generation, source_payload_fingerprint
                    ) VALUES (
                      CAST(:snapshot_id AS uuid), 1, 'pinvi', :target_key, 'deleted',
                      1, :fingerprint
                    )
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "target_key": target_key,
                    "fingerprint": _SOURCE_FINGERPRINT,
                },
            )
    finally:
        await engine.dispose()


async def _delete_snapshot(dsn: str, snapshot_id: str) -> None:
    await _execute_sql(
        dsn,
        f"DELETE FROM ops.poi_cache_target_snapshots WHERE snapshot_id='{snapshot_id}'::uuid",
    )


async def _assert_evidence_negative_matrix(
    dsn: str,
    *,
    identity: str,
    gc_receipt: Receipt,
) -> None:
    for suffix, restore_epoch, target_key, root, expired, failed_check_prefix in (
        ("1", 2, _TARGET_KEY, _LIVE_MERKLE_ROOT, False, "pinvi_snapshot_"),
        ("2", 1, "mixed-target", _MIXED_MERKLE_ROOT, False, "pinvi_snapshot_"),
        ("3", 1, _TARGET_KEY, "f" * 64, False, "pinvi_snapshot_"),
        ("4", 1, _TARGET_KEY, _LIVE_MERKLE_ROOT, True, "gc_remaining_"),
    ):
        snapshot_id = f"70000000-0000-0000-0000-00000000000{suffix}"
        await _insert_negative_snapshot(
            dsn,
            snapshot_id=snapshot_id,
            restore_epoch=restore_epoch,
            target_key=target_key,
            merkle_root=root,
            expired=expired,
        )
        await _assert_verify_rejected_without_mutation(
            dsn,
            identity=identity,
            gc_receipt=gc_receipt,
            failed_check_prefix=failed_check_prefix,
        )
        await _delete_snapshot(dsn, snapshot_id)

    await _execute_sql(
        dsn,
        "UPDATE ops.poi_cache_target_streams "
        "SET status='fenced', consumer_enabled=false WHERE external_system='pinvi'",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="pinvi_stream_ready",
    )
    await _execute_sql(
        dsn,
        "UPDATE ops.poi_cache_target_streams "
        "SET status='ready', consumer_enabled=true WHERE external_system='pinvi'",
    )

    await _execute_sql(
        dsn,
        "DELETE FROM ops.poi_cache_target_outbox_deliveries "
        f"WHERE event_id='{_OUTBOX_EVENT_ID}'::uuid",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="outbox_backlog_zero",
    )
    await _execute_sql(
        dsn,
        "INSERT INTO ops.poi_cache_target_outbox_deliveries "
        f"(event_id, status, delivered_at) VALUES "
        f"('{_OUTBOX_EVENT_ID}'::uuid, 'delivered', now())",
    )

    await _execute_sql(
        dsn,
        "UPDATE ops.poi_cache_target_outbox_deliveries "
        "SET status='retry', delivered_at=NULL "
        f"WHERE event_id='{_OUTBOX_EVENT_ID}'::uuid",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="delivery_backlog_zero",
    )
    await _execute_sql(
        dsn,
        "UPDATE ops.poi_cache_target_outbox_deliveries "
        "SET status='delivered', delivered_at=now() "
        f"WHERE event_id='{_OUTBOX_EVENT_ID}'::uuid",
    )

    await _execute_sql(
        dsn,
        "UPDATE ops.poi_cache_target_outbox_claims "
        "SET status='active', completed_at=NULL, lease_expires_at=now() + interval '1 hour' "
        f"WHERE claim_id='{_CLAIM_ID}'::uuid",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="claim_backlog_zero",
    )
    await _execute_sql(
        dsn,
        "UPDATE ops.poi_cache_target_outbox_claims "
        "SET status='acked', completed_at=now(), lease_expires_at=now() - interval '1 minute' "
        f"WHERE claim_id='{_CLAIM_ID}'::uuid",
    )

    await _execute_sql(
        dsn,
        """
        WITH command AS (
          INSERT INTO ops.domain_commands (
            actor, operation, idempotency_key, request_fingerprint
          ) VALUES (
            'system:h35', 'cache-target.reconcile',
            '80000000-0000-0000-0000-000000000001',
            'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
          ) RETURNING command_id
        )
        INSERT INTO ops.poi_cache_target_reconciliation_requests (
          request_id, external_system, command_id, reason, status, phase_version,
          started_at
        ) SELECT
          '80000000-0000-0000-0000-000000000002'::uuid, 'pinvi', command_id,
          'H35 active backlog', 'preparing', 1, now()
        FROM command
        """,
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="reconciliation_backlog_zero",
    )
    await _execute_sql(
        dsn,
        "UPDATE ops.poi_cache_target_reconciliation_requests "
        "SET status='superseded', completed_at=now(), error_code='restore_fenced' "
        "WHERE request_id='80000000-0000-0000-0000-000000000002'::uuid",
    )

    observation_run_id = cache_target_gc_observation_run_id(_TRANSACTION_ID)
    await _execute_sql(
        dsn,
        "UPDATE ops.poi_cache_target_snapshot_gc_observations "
        f"SET dagster_run_id='foreign-observation' WHERE dagster_run_id='{observation_run_id}'",
    )
    await _assert_verify_rejected_without_mutation(
        dsn,
        identity=identity,
        gc_receipt=gc_receipt,
        failed_check_prefix="gc_observation_exists",
    )
    await _execute_sql(
        dsn,
        "UPDATE ops.poi_cache_target_snapshot_gc_observations "
        f"SET dagster_run_id='{observation_run_id}' "
        "WHERE dagster_run_id='foreign-observation'",
    )


async def _assert_mixed_partial_state_rejected(dsn: str) -> None:
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(
                text(
                    "CREATE INDEX idx_violations_status_seen "
                    "ON ops.data_integrity_violations (status)"
                )
            )
        async with engine.connect() as connection:
            checks = await partial_probe(connection, _PRE_REVISION)
            by_name = {str(value["name"]): value for value in checks}
            assert by_name["partial_statement_prefix_canonical"]["passed"] is False
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text("DROP INDEX ops.idx_violations_status_seen"))
    finally:
        await engine.dispose()


def _loopback_only(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    external_hosts: list[str] = []
    original = socket.socket.connect

    def guarded_connect(instance: socket.socket, address: Any) -> Any:
        if isinstance(address, tuple):
            host = str(address[0])
            if host not in {"127.0.0.1", "::1", "localhost"}:
                external_hosts.append(host)
                raise AssertionError("H35 rehearsal attempted an external network connection")
        return original(instance, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return external_hosts


async def test_h35_exact_surface_network_free_rehearsal(
    pg_container: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database, dsn = await _create_database(admin_dsn)
    external_hosts = _loopback_only(monkeypatch)
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        await _seed_exact_pre_cutover_surface(dsn)
        assert await _schema_and_public_count(dsn) == (_PRE_REVISION, 3_265)

        identity = await _database_identity(dsn)
        monkeypatch.setenv("KOR_TRAVEL_MAP_PG_DSN", dsn)
        monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", _SOURCE_REVISION)

        before_rejections = await _schema_and_public_count(dsn)
        wrong_identity = await _execute(
            _request("preflight", database_identity="f" * 64, prior=None)
        )
        assert wrong_identity["status"] == "rejected"
        assert wrong_identity["database_identity"] == identity
        monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "2" * 40)
        wrong_revision = await _execute(
            _request("preflight", database_identity=identity, prior=None)
        )
        assert wrong_revision["status"] == "rejected"
        assert await _schema_and_public_count(dsn) == before_rejections
        monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", _SOURCE_REVISION)

        await _assert_mixed_partial_state_rejected(dsn)
        assert await _schema_and_public_count(dsn) == before_rejections

        preflight = await _execute(_request("preflight", database_identity=identity, prior=None))
        assert preflight["status"] == "accepted"
        assert preflight["row_counts"]["public_items"] == 3_265

        migrate = await _execute(_request("migrate", database_identity=identity, prior=preflight))
        failed_migrate_checks = [
            value for value in migrate["checks"] if value["passed"] is not True
        ]
        assert migrate["status"] == "accepted", (
            migrate["row_counts"],
            failed_migrate_checks,
        )
        assert migrate["schema_before"] == _PRE_REVISION
        assert migrate["schema_after"] == _TARGET_REVISION
        assert migrate["row_counts"]["public_items"] == 3_043

        csv5 = await _execute(_request("csv5", database_identity=identity, prior=migrate))
        assert csv5["status"] == "accepted"
        assert csv5["row_counts"] == {
            "accepted": 222,
            "batches": 5,
            "csv_files": 5,
            "imported_rows": 486,
            "public_items": 3_265,
            "rejected": 0,
        }

        csv5_replay = await _execute(_request("csv5", database_identity=identity, prior=migrate))
        assert csv5_replay["status"] == "accepted"
        assert csv5_replay["row_counts"] == csv5["row_counts"]
        await _assert_scope_validator_truth_table(dsn)

        await _seed_generation7_final_state(dsn)
        event_count = await _external_event_count(dsn)
        assert await _snapshot_gc_state(dsn) == {
            "expired_referenced": 1,
            "expired_unreferenced": 1,
            "headers": 3,
            "items": 3,
            "observations": 0,
        }

        gc = await _execute(_request("gc", database_identity=identity, prior=csv5))
        assert gc["status"] == "accepted"
        assert gc["row_counts"]["deleted_headers"] == 1
        assert gc["row_counts"]["deleted_items"] == 1
        assert gc["row_counts"]["remaining_headers"] == 0
        assert gc["row_counts"]["remaining_items"] == 0
        assert gc["row_counts"]["referenced_headers"] == 2
        assert gc["row_counts"]["referenced_items"] == 2
        assert gc["cache_target_evidence"] is None

        gc_replay = await _execute(_request("gc", database_identity=identity, prior=csv5))
        assert gc_replay["status"] == "accepted"
        assert gc_replay["row_counts"]["deleted_headers"] == 0
        assert gc_replay["row_counts"]["deleted_items"] == 0
        assert gc_replay["row_counts"]["remaining_headers"] == 0
        assert gc_replay["row_counts"]["remaining_items"] == 0
        assert await _snapshot_gc_state(dsn) == {
            "expired_referenced": 1,
            "expired_unreferenced": 0,
            "headers": 2,
            "items": 2,
            "observations": 1,
        }

        verify = await _execute(_request("verify", database_identity=identity, prior=gc_replay))
        assert verify["status"] == "accepted"
        assert verify["schema_after"] == _TARGET_REVISION
        assert verify["row_counts"]["public_items"] == 3_265
        assert verify["runtime_mutation_count"] == 0
        assert verify["external_event_count"] == 0
        assert set(verify) == {
            "cache_target_evidence",
            "checks",
            "contract_version",
            "database_identity",
            "external_event_count",
            "forward_boundary",
            "operation",
            "prior_receipt_digest",
            "request_digest",
            "row_counts",
            "runtime_mutation_count",
            "schema_after",
            "schema_before",
            "source_revision",
            "status",
            "transaction_id",
        }
        evidence = verify["cache_target_evidence"]
        assert isinstance(evidence, dict)
        assert set(evidence) == {
            "claim_backlog_count",
            "consumer_id",
            "contract_version",
            "control_version",
            "delivery_backlog_count",
            "external_system",
            "high_watermark_cursor",
            "outbox_backlog_count",
            "reconciliation_backlog_count",
            "restore_epoch",
            "snapshot_count",
            "snapshot_merkle_root",
            "stream_control_etag",
            "stream_state",
        }
        assert evidence == {
            "claim_backlog_count": 0,
            "consumer_id": _PINVI_CONSUMER_ID,
            "contract_version": "ktm-cache-target-final-evidence/v1",
            "control_version": 1,
            "delivery_backlog_count": 0,
            "external_system": "pinvi",
            "high_watermark_cursor": (
                "eyJraW5kIjoiY2FjaGVfdGFyZ2V0X2V2ZW50IiwicmVsYXlfb3JkZXIiOjAsInYiOjF9"
            ),
            "outbox_backlog_count": 0,
            "reconciliation_backlog_count": 0,
            "restore_epoch": 1,
            "snapshot_count": 1,
            "snapshot_merkle_root": _LIVE_MERKLE_ROOT,
            "stream_control_etag": '"pinvi:1"',
            "stream_state": "ready",
        }
        await _assert_structural_negative_matrix(
            dsn,
            identity=identity,
            gc_receipt=gc_replay,
        )
        await _assert_evidence_negative_matrix(
            dsn,
            identity=identity,
            gc_receipt=gc_replay,
        )
        final_verify = await _execute(
            _request("verify", database_identity=identity, prior=gc_replay)
        )
        assert final_verify["status"] == "accepted"
        assert final_verify["cache_target_evidence"] == evidence
        assert await _external_event_count(dsn) == event_count
        assert external_hosts == []
    finally:
        await _drop_database(admin_dsn, database)


async def test_partial_probe_passes_at_target_schema(pg_container: Any) -> None:
    """head까지 올린 실제 DB에서 partial probe가 통과해야 한다 — migrate 재시도 경로.

    `run_migrate`의 `if schema_before != TARGET_SCHEMA: upgrade`는 동일 request 재발행 시
    이미 head인 DB에 accepted receipt를 돌려주기 위한 것이다(runbook §2/§4의 forward 재개).
    그런데 그 앞의 `partial_statement_prefix_canonical` 게이트가 head에서 통과하지 못하면
    재시도가 **무조건 거부**되어 그 경로 자체가 죽는다. 그 상태의 유일한 출구는 PITR 없는
    prod의 단일 dump 복원이므로 반드시 고정한다.

    실제로 그런 결함이 있었다: `idx_features_public_weather_coord_5179_gist` signature가
    `kind = 'weather'::text`를 요구했는데 `feature.features.kind`가 `character varying`이라
    PostgreSQL은 항상 `((kind)::text = 'weather'::text)`로 deparse한다 — 어떤 DB에서도
    일치하지 않아 이 index가 영구히 non-canonical이었다.

    기존 테스트가 놓친 이유: 단위 테스트는 합성 `_states()` 맵을 쓰고 리허설은
    `_PRE_REVISION`에서만 probe해서, **실제 `pg_get_indexdef` 출력을 head에서 검사하는
    경로가 없었다.**
    """
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database, dsn = await _create_database(admin_dsn)
    try:
        await asyncio.to_thread(_run_alembic, dsn, "head")
        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                checks = await partial_probe(connection, _TARGET_REVISION)
                failed = [str(value["name"]) for value in checks if value.get("passed") is not True]
            assert not failed, (
                f"head({_TARGET_REVISION})에서 partial probe가 실패했다 — "
                f"migrate 재시도가 영구 불가해진다: {failed}"
            )
        finally:
            await engine.dispose()
    finally:
        await _drop_database(admin_dsn, database)


async def test_index_signatures_match_real_indexdef(pg_container: Any) -> None:
    """모든 index signature fragment가 실제 `pg_get_indexdef` 출력과 일치해야 한다.

    signature를 손으로 적으면 PostgreSQL의 deparse 형태(특히 `character varying` 컬럼의
    `(col)::text` 캐스트)와 어긋나기 쉽고, 어긋나면 그 index는 조용히 영구
    non-canonical이 된다. head에 존재하는 index 전부를 전수 확인한다.
    """
    from kortravelmap.cli._h35_schema import _INDEX_SIGNATURES

    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database, dsn = await _create_database(admin_dsn)
    try:
        await asyncio.to_thread(_run_alembic, dsn, "head")
        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                rows = (
                    await connection.execute(
                        text(
                            "select indexname, lower(indexdef) as indexdef "
                            "from pg_indexes "
                            "where schemaname in ('feature','ops','provider_sync')"
                        )
                    )
                ).all()
            actual = {str(name): str(definition) for name, definition in rows}

            checked = 0
            mismatched: list[str] = []
            for index_name, fragments in _INDEX_SIGNATURES.items():
                definition = actual.get(index_name)
                if definition is None:
                    # head에 없는 index(구 revision 전용)는 이 테스트 대상이 아니다.
                    continue
                checked += 1
                for fragment in fragments:
                    if fragment.lower() not in definition:
                        mismatched.append(f"{index_name}: {fragment!r} not in {definition!r}")
            assert checked > 0, "head에서 확인된 signature가 하나도 없다 — 테스트가 공회전한다"
            assert not mismatched, "signature가 실제 indexdef와 불일치한다:\n" + "\n".join(
                mismatched
            )
        finally:
            await engine.dispose()
    finally:
        await _drop_database(admin_dsn, database)


async def test_public_count_detects_source_absent_item(pg_container: Any) -> None:
    """공개 item 카운트가 `source_present`를 반영해야 한다 — de-publish 감지.

    실제 공개 목록 술어(`curation_repo._LIST_FEATURE_ITEMS_SQL`)는 `AND i.source_present`를
    포함한다. helper의 카운트가 이를 빼면, csv5의 authoritative replace가 기존 item을
    source-absent로 만들었을 때 **API에서는 사라졌는데 게이트는 같은 수를 계속 보고**한다.
    그 상태로 verify가 통과하면 공개 표면 축소를 아무도 못 잡는다.

    현재 데이터에는 `source_present=false`인 active item이 0건이라 정상 경로에서 두 계산이
    같은 값을 낸다 — 그래서 실제로 하나를 source-absent로 만들어 차이를 강제한다.
    """
    from kortravelmap.cli._h35_schema import _public_count

    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database, dsn = await _create_database(admin_dsn)
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        await _seed_exact_pre_cutover_surface(dsn)
        await asyncio.to_thread(_run_alembic, dsn, "head")

        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                before = await _public_count(connection, migrated=True)
            assert before > 0, "픽스처가 공개 item을 만들지 못했다 — 테스트가 공회전한다"

            # 반드시 **공개로 집계되는** item을 골라야 한다. 아무 included item이나
            # 고르면 그 item이 애초에 공개 집합 밖(비공개 collection·미신뢰 link)일 수
            # 있어 카운트가 안 움직이고, 테스트가 통과하는 것처럼 보인다.
            async with engine.begin() as connection:
                target = (
                    await connection.execute(
                        text(
                            f"""
                            SELECT item.curation_item_id
                            FROM feature.curation_items AS item
                            JOIN feature.curation_collections AS collection
                              ON collection.collection_id = item.collection_id
                            JOIN feature.curated_themes AS theme
                              ON theme.theme_id = collection.theme_id
                            WHERE item.archived_at IS NULL
                              AND collection.archived_at IS NULL
                              AND item.source_present
                              AND item.status = 'included'
                              AND collection.status = 'published'
                              AND collection.visibility = 'public'
                              AND theme.visibility = 'public'
                              AND EXISTS (
                                  SELECT 1 FROM feature.curation_link_decisions AS decision
                                  WHERE decision.decision_id = item.accepted_link_decision_id
                                    AND decision.curation_item_id = item.curation_item_id
                                    AND decision.feature_id = item.feature_id
                                    AND decision.decision_kind = 'accepted'
                                    AND {trusted_basis_sql("decision.match_basis")}
                              )
                            LIMIT 1
                            """
                        )
                    )
                ).scalar_one()
                await connection.execute(
                    text(
                        "UPDATE feature.curation_items SET source_present = false "
                        "WHERE curation_item_id = :target"
                    ),
                    {"target": target},
                )

            async with engine.connect() as connection:
                after = await _public_count(connection, migrated=True)

            assert after == before - 1, (
                "source_present=false로 바뀐 item이 공개 카운트에서 빠지지 않았다 — "
                f"{before} -> {after}. de-publish를 게이트가 놓친다."
            )
        finally:
            await engine.dispose()
    finally:
        await _drop_database(admin_dsn, database)


async def _plant_quarantine_candidate(engine: Any) -> str:
    """`0065`가 격리할 item을 하나 심는다 — legacy-marker collection 안의 네이티브 item.

    시드는 legacy-marker collection을 만들지 않으므로 전용 marker collection을 하나 만든 뒤
    그 안에 `curated_features` 투영본이 **아닌** item을 넣어야 격리 조건이 성립한다.
    """
    async with engine.begin() as connection:
        source_collection_id = (
            await connection.execute(
                text(
                    "SELECT item.collection_id FROM feature.curation_items AS item "
                    "JOIN feature.curation_collections AS collection "
                    "ON collection.collection_id=item.collection_id "
                    "WHERE collection.source_id IS NOT NULL "
                    "ORDER BY item.curation_item_id LIMIT 1"
                )
            )
        ).scalar_one()
        collection_id = (
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.curation_collections (
                        collection_key, theme_id, source_id, title, edition_key,
                        description, status, visibility, metadata, created_by,
                        updated_by, created_at, updated_at, archived_at
                    )
                    SELECT
                        'legacy:probe:' || replace(x_extension.gen_random_uuid()::text, '-', ''),
                        theme_id, source_id, 'H35 quarantine probe', edition_key,
                        description, status, visibility,
                        '{"migrated_from":"feature.curated_features"}'::jsonb,
                        'test:h35', 'test:h35', created_at, updated_at, NULL
                    FROM feature.curation_collections
                    WHERE collection_id=:source_collection_id
                    RETURNING collection_id
                    """
                ),
                {"source_collection_id": source_collection_id},
            )
        ).scalar_one()

        # 형제 행을 복사해 NOT NULL 컬럼을 빠짐없이 채운다. 바꾸는 것은 세 가지뿐:
        # collection 및 새 `curation_item_id`(어떤 `curated_feature_id`와도 안 겹쳐
        # 투영본이 아니게 됨),
        # 고유 `external_item_id`(tombstone 병합 회피), `feature_id=NULL`
        # (`0066`의 active-source-feature 유일성 회피).
        await connection.execute(
            text(
                """
                INSERT INTO feature.curation_items
                SELECT (jsonb_populate_record(
                    NULL::feature.curation_items,
                    to_jsonb(source) || jsonb_build_object(
                        'collection_id', CAST(:collection_id AS uuid),
                        'curation_item_id', x_extension.gen_random_uuid(),
                        'external_item_id', 'h22a-native-probe',
                        'feature_id', NULL
                    )
                )).*
                FROM feature.curation_items AS source
                WHERE source.collection_id = :source_collection_id
                ORDER BY source.curation_item_id
                LIMIT 1
                """
            ),
            {
                "collection_id": collection_id,
                "source_collection_id": source_collection_id,
            },
        )
    return str(collection_id)


async def test_quarantine_gate_fires_before_the_forward_boundary(pg_container: Any) -> None:
    """격리 후보는 `0063`에서, 즉 **되돌릴 수 있는 동안** 걸려야 한다.

    이 검사를 migrate/verify에 hard check로 두면 안 된다. 격리 발생은 공개 카운트로
    드러나지 않으므로(격리 조건은 `status`·`source_present`·accepted link 어느 것도
    요구하지 않아 공개 집합과 독립) **기존 게이트가 통과시키던 상태를 경계 뒤에서 새로
    거부**하게 되는데, 그 지점에는 출구가 없다 — csv5는 accepted prior receipt를 요구하고,
    migrate 재실행은 `schema_before=0063`을 요구하는데 DB는 이미 0078이며, `0065`
    downgrade는 durable state에 fail-close한다. PITR 없는 prod에서 dump 복원만 남는다.

    그래서 이 테스트는 세 가지를 함께 고정한다.
      1. `0063`에서 후보가 잡힌다 (경계 앞 탐지).
      2. 같은 상태를 head까지 밀면 `0065`가 실제로 격리한다 — 즉 `0063` 술어가 공회전이
         아니라 진짜 격리 조건과 같은 것을 고른다.
      3. 그런데도 verify의 **check**는 늘어나지 않는다 (경계 뒤 거부 없음).
    """
    from kortravelmap.cli._h35_schema import (
        _quarantine_candidate_count,
        _quarantine_counts,
        verify_0075_0079,
    )

    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database, dsn = await _create_database(admin_dsn)
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        await _seed_exact_pre_cutover_surface(dsn)

        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                clean = await _quarantine_candidate_count(connection)
            assert clean == 0, (
                f"시드 표면에 이미 격리 후보가 {clean}건 있다 — 실제 prod 실측(0건)과 "
                "다르므로 이 테스트가 무엇을 검증하는지 알 수 없다."
            )

            await _plant_quarantine_candidate(engine)

            # ① 경계 앞에서 잡힌다.
            async with engine.connect() as connection:
                planted = await _quarantine_candidate_count(connection)
            assert planted == 1, (
                f"`0063` 술어가 심어 둔 격리 후보를 못 잡았다 (={planted}). 이 술어가 "
                "0을 내면 preflight 게이트는 아무것도 막지 못한다."
            )

            await asyncio.to_thread(_run_alembic, dsn, "head")

            # ② `0063` 술어가 고른 것이 진짜 `0065`의 격리 대상과 같다.
            async with engine.connect() as connection:
                quarantine_collections, quarantine_items = await _quarantine_counts(connection)
                checks, counts = await verify_0075_0079(connection)
            assert quarantine_items == 1, (
                "`0063`에서 후보로 잡았는데 `0065`가 격리하지 않았다 — 두 술어가 다른 "
                f"것을 고르고 있다. items={quarantine_items}"
            )
            assert quarantine_collections == 1, (
                "격리 item은 생겼는데 quarantine collection 수가 다르다 "
                f"(={quarantine_collections})."
            )

            # ③ 그래도 경계 뒤에서는 거부하지 않는다. 관측치로만 남는다.
            assert counts["quarantine_items"] == 1, "verify가 격리 관측치를 안 남겼다."
            assert counts["quarantine_collections"] == 1, "verify가 격리 관측치를 안 남겼다."
            failed = [str(entry["name"]) for entry in checks if entry.get("passed") is not True]
            assert not failed, (
                "격리가 발생했다고 경계 **뒤** 게이트가 거부했다 — 그 지점에는 출구가 없다. "
                f"실패한 check={failed}. 이 판정은 preflight의 "
                "`quarantine_candidates_before`가 해야 한다."
            )
        finally:
            await engine.dispose()
    finally:
        await _drop_database(admin_dsn, database)


async def test_preflight_rejects_quarantine_candidate(pg_container: Any, monkeypatch: Any) -> None:
    """preflight receipt가 격리 후보를 이름 붙은 check로 거부해야 한다.

    앞 테스트는 술어가 후보를 **센다**는 것까지만 고정한다. `run_preflight`가 그 수를
    실제로 check로 만들지 않으면 게이트는 없는 것과 같으므로, receipt를 직접 본다.
    """
    from kortravelmap.cli._h35_contract import H35Request
    from kortravelmap.cli._h35_schema import run_preflight

    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database, dsn = await _create_database(admin_dsn)
    try:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        await _seed_exact_pre_cutover_surface(dsn)
        monkeypatch.setenv("KOR_TRAVEL_MAP_PG_DSN", dsn)
        monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "h22a-test-revision")
        request = H35Request(
            operation="preflight",
            transaction_id="0f9d3c6e-5a41-4b2e-9c77-2b8a1d4e6f30",
            source_revision="h22a-test-revision",
            database_identity="",
            prior_receipt=None,
            prior_receipt_digest=None,
            request_digest="h22a-test-digest",
        )

        clean_receipt = await run_preflight(request)
        clean = {str(entry["name"]): entry for entry in clean_receipt["checks"]}
        assert "quarantine_candidates_before" in clean, (
            "preflight receipt에 quarantine_candidates_before check가 없다 — "
            "게이트가 배선되지 않았다."
        )
        assert clean["quarantine_candidates_before"]["passed"] is True, (
            "격리 후보가 없는 표면인데 preflight가 거부했다 — 정상 cutover를 막는다."
        )

        engine = make_async_engine(dsn)
        try:
            await _plant_quarantine_candidate(engine)
        finally:
            await engine.dispose()

        planted_receipt = await run_preflight(request)
        planted = {str(entry["name"]): entry for entry in planted_receipt["checks"]}
        assert planted["quarantine_candidates_before"]["passed"] is False, (
            "격리 후보를 심었는데 preflight가 통과시켰다."
        )
        assert planted_receipt["status"] == "rejected", (
            "격리 후보가 있는데 preflight receipt가 accepted다 — cutover가 그대로 진행된다."
        )
        assert planted_receipt["forward_boundary"] == "not_crossed", (
            "preflight 거부는 경계 앞이어야 재실행할 수 있다."
        )
    finally:
        await _drop_database(admin_dsn, database)
