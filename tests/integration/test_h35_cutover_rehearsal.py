"""격리 PostGIS에서 수행하는 H35 0063→0078 전체 리허설."""

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
from kortravelmap.cli._h35_contract import (
    CONTRACT_VERSION,
    H35Request,
    Operation,
    Receipt,
    compute_database_identity,
    parse_request,
    receipt_digest,
)
from kortravelmap.cli._h35_schema import partial_probe
from kortravelmap.cli.h35_cutover import _execute
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_PRE_REVISION = "0063_pipeline_root_id"
_TARGET_REVISION = "0078_cache_target_gc_observe"
_SOURCE_REVISION = "1" * 40
_TRANSACTION_ID = "00000000-0000-0000-0000-000000000001"
_SOURCE_RULE_PUBLIC = 3_043
_LEGACY_PUBLIC = 222


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

        preflight = await _execute(
            _request("preflight", database_identity=identity, prior=None)
        )
        assert preflight["status"] == "accepted"
        assert preflight["row_counts"]["public_items"] == 3_265

        migrate = await _execute(
            _request("migrate", database_identity=identity, prior=preflight)
        )
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

        csv5_replay = await _execute(
            _request("csv5", database_identity=identity, prior=migrate)
        )
        assert csv5_replay["status"] == "accepted"
        assert csv5_replay["row_counts"] == csv5["row_counts"]

        verify = await _execute(
            _request("verify", database_identity=identity, prior=csv5)
        )
        assert verify["status"] == "accepted"
        assert verify["schema_after"] == _TARGET_REVISION
        assert verify["row_counts"]["public_items"] == 3_265
        assert verify["runtime_mutation_count"] == 0
        assert verify["external_event_count"] == 0
        assert await _external_event_count(dsn) == 0
        assert external_hosts == []
    finally:
        await _drop_database(admin_dsn, database)
