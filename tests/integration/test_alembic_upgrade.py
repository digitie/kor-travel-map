"""``test_alembic_upgrade`` — `alembic upgrade head` 적용 후 schema 검증.

PR#28 (Sprint 2 prep) — Alembic 첫 revision (0001 + 0002)이 testcontainers
PostGIS에서 깨끗하게 적용되는지 확인 + 4 schema / 3 extension / 4 신규 테이블
존재 확인.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from kortravelmap.infra.alembic_exclusions import (
    UNCOMPARED_INDEXES,
    UNMAPPED_APP_TABLES,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


pytestmark = pytest.mark.integration


_UNMAPPED_TABLE_COLUMNS: dict[
    tuple[str, str],
    set[tuple[str, str, bool]],
] = {
    ("feature", "feature_weather_values"): {
        ("weather_value_key", "text", True),
        ("feature_id", "text", True),
        ("provider", "text", True),
        ("weather_domain", "text", True),
        ("forecast_style", "text", True),
        ("timeline_bucket", "text", False),
        ("metric_key", "text", True),
        ("metric_name", "text", False),
        ("source_metric_key", "text", False),
        ("source_metric_name", "text", False),
        ("value_number", "numeric(14,4)", False),
        ("value_text", "text", False),
        ("unit", "text", False),
        ("severity", "text", False),
        ("issued_at", "timestamp with time zone", False),
        ("valid_at", "timestamp with time zone", False),
        ("valid_from", "timestamp with time zone", False),
        ("valid_until", "timestamp with time zone", False),
        ("observed_at", "timestamp with time zone", False),
        ("normalization_version", "text", False),
        ("payload", "jsonb", True),
        ("source_record_key", "text", False),
        ("collected_at", "timestamp with time zone", True),
        ("created_at", "timestamp with time zone", True),
        ("updated_at", "timestamp with time zone", True),
    },
    ("feature", "feature_price_values"): {
        ("price_value_key", "text", True),
        ("feature_id", "text", True),
        ("provider", "text", True),
        ("price_domain", "text", True),
        ("product_key", "text", True),
        ("product_name", "text", False),
        ("source_product_key", "text", False),
        ("source_product_name", "text", False),
        ("observed_at", "timestamp with time zone", True),
        ("value_number", "numeric(14,4)", True),
        ("unit", "text", True),
        ("normalization_version", "text", False),
        ("payload", "jsonb", True),
        ("source_record_key", "text", False),
        ("collected_at", "timestamp with time zone", True),
        ("created_at", "timestamp with time zone", True),
        ("updated_at", "timestamp with time zone", True),
    },
    ("ops", "system_log"): {
        ("system_log_id", "uuid", True),
        ("level", "text", True),
        ("source", "text", True),
        ("event", "text", True),
        ("message", "text", True),
        ("detail", "jsonb", True),
        ("request_id", "text", False),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "api_call_log"): {
        ("api_call_log_id", "uuid", True),
        ("method", "text", True),
        ("path", "text", True),
        ("status_code", "integer", True),
        ("duration_ms", "integer", True),
        ("request_id", "text", False),
        ("error_code", "text", False),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "public_api_keys"): {
        ("public_api_key_id", "uuid", True),
        ("key_hash", "text", True),
        ("key_hint", "text", True),
        ("label", "text", False),
        ("state", "text", True),
        ("created_at", "timestamp with time zone", True),
        ("created_by", "text", False),
        ("revoked_at", "timestamp with time zone", False),
        ("revoked_by", "text", False),
    },
    ("ops", "admin_auth_events"): {
        ("auth_event_id", "uuid", True),
        ("event_type", "text", True),
        ("outcome", "text", True),
        ("attempted_username", "text", False),
        ("actor", "text", False),
        ("reason", "text", False),
        ("next_path", "text", False),
        ("client_ip", "text", False),
        ("user_agent", "text", False),
        ("request_id", "text", False),
        ("created_at", "timestamp with time zone", True),
    },
    ("ops", "ops_live_ticket_claims"): {
        ("nonce_hash", "bytea", True),
        ("actor", "text", True),
        ("expires_at", "timestamp with time zone", True),
        ("claimed_at", "timestamp with time zone", True),
    },
    ("ops", "ops_live_topic_revisions"): {
        ("topic", "text", True),
        ("revision", "bigint", True),
        ("updated_at", "timestamp with time zone", True),
    },
}

_UNMAPPED_TABLE_CONSTRAINTS: dict[tuple[str, str], set[tuple[str, str]]] = {
    ("feature", "feature_weather_values"): {
        ("feature_weather_values_pkey", "p"),
        ("feature_weather_values_feature_id_fkey", "f"),
        ("ck_weather_value_present", "c"),
    },
    ("feature", "feature_price_values"): {
        ("feature_price_values_pkey", "p"),
        ("feature_price_values_feature_id_fkey", "f"),
        ("feature_price_values_source_record_key_fkey", "f"),
        ("ck_price_value_nonnegative", "c"),
        ("uq_price_value_identity", "u"),
    },
    ("ops", "system_log"): {
        ("system_log_pkey", "p"),
        ("ck_system_log_level", "c"),
    },
    ("ops", "api_call_log"): {("api_call_log_pkey", "p")},
    ("ops", "public_api_keys"): {
        ("public_api_keys_pkey", "p"),
        ("public_api_keys_key_hash_key", "u"),
        ("public_api_keys_key_hash_check", "c"),
        ("public_api_keys_key_hint_check", "c"),
        ("public_api_keys_label_check", "c"),
        ("public_api_keys_state_check", "c"),
        ("public_api_keys_check", "c"),
    },
    ("ops", "admin_auth_events"): {
        ("admin_auth_events_pkey", "p"),
        ("admin_auth_events_event_type_check", "c"),
        ("admin_auth_events_outcome_check", "c"),
        ("admin_auth_events_attempted_username_check", "c"),
        ("admin_auth_events_actor_check", "c"),
        ("admin_auth_events_reason_check", "c"),
        ("admin_auth_events_next_path_check", "c"),
        ("admin_auth_events_client_ip_check", "c"),
        ("admin_auth_events_user_agent_check", "c"),
        ("admin_auth_events_request_id_check", "c"),
    },
    ("ops", "ops_live_ticket_claims"): {
        ("pk_ops_live_ticket_claims", "p"),
        ("ck_ops_live_ticket_claims_nonce_hash_length", "c"),
        ("ck_ops_live_ticket_claims_actor_length", "c"),
    },
    ("ops", "ops_live_topic_revisions"): {
        ("pk_ops_live_topic_revisions", "p"),
        ("ck_ops_live_topic_revisions_topic", "c"),
        ("ck_ops_live_topic_revisions_revision", "c"),
    },
}

_UNMAPPED_TABLE_INDEXES: dict[tuple[str, str], set[str]] = {
    ("feature", "feature_weather_values"): {
        "feature_weather_values_pkey",
        "idx_weather_values_feature_card",
        "brin_weather_values_valid_at",
        "idx_weather_values_metric_feature",
        "idx_weather_values_feature_issued_valid",
        "idx_weather_values_feature_valid_issued",
        "brin_weather_values_collected_at",
    },
    ("feature", "feature_price_values"): {
        "feature_price_values_pkey",
        "uq_price_value_identity",
        "idx_price_values_feature_observed_identity",
        "idx_price_values_domain_product_observed",
        "idx_price_values_source_record",
        "idx_price_values_observed_at_brin",
    },
    ("ops", "system_log"): {
        "system_log_pkey",
        "idx_system_log_keyset",
        "idx_system_log_level",
        "idx_system_log_source",
    },
    ("ops", "api_call_log"): {
        "api_call_log_pkey",
        "idx_api_call_log_keyset",
        "idx_api_call_log_status",
    },
    ("ops", "public_api_keys"): {
        "public_api_keys_pkey",
        "public_api_keys_key_hash_key",
        "idx_public_api_keys_active_hash",
        "idx_public_api_keys_created_at",
    },
    ("ops", "admin_auth_events"): {
        "admin_auth_events_pkey",
        "idx_admin_auth_events_created_at",
        "idx_admin_auth_events_outcome_time",
    },
    ("ops", "ops_live_ticket_claims"): {
        "pk_ops_live_ticket_claims",
        "ix_ops_live_ticket_claims_expires_at",
    },
    ("ops", "ops_live_topic_revisions"): {"pk_ops_live_topic_revisions"},
}

_UNCOMPARED_INDEX_CONTRACTS: dict[
    tuple[str, str],
    tuple[bool, tuple[str, ...], str],
] = {
    ("feature", "idx_features_dedup_refresh_keyset"): (
        False,
        (
            "updated_at DESC NULLS FIRST",
            "feature_id DESC NULLS FIRST",
        ),
        "deleted_at IS NULL AND status = 'active' AND coord IS NOT NULL",
    ),
    ("feature", "idx_features_yt_channel_id"): (
        False,
        (
            "detail #>> '{payload,kor_travel_concierge,youtube,channel_id}' "
            "ASC NULLS LAST",
        ),
        "detail #>> '{payload,kor_travel_concierge,youtube,channel_id}' IS NOT NULL",
    ),
    ("feature", "idx_features_yt_playlist_id"): (
        False,
        (
            "detail #>> '{payload,kor_travel_concierge,youtube,playlist_id}' "
            "ASC NULLS LAST",
        ),
        "detail #>> '{payload,kor_travel_concierge,youtube,playlist_id}' IS NOT NULL",
    ),
    ("provider_sync", "idx_source_records_kma_alert_history"): (
        False,
        (
            "provider ASC NULLS LAST",
            "dataset_key ASC NULLS LAST",
            "source_entity_type ASC NULLS LAST",
            "fetched_at DESC NULLS FIRST",
            "source_record_key ASC NULLS LAST",
        ),
        "provider = 'python-kma-api' AND dataset_key = 'kma_weather_alerts' "
        "AND source_entity_type = 'weather_alert'",
    ),
}


def _canonical_pg_sql(value: str | None) -> str:
    if value is None:
        return ""
    without_casts = value.replace("::text[]", "").replace("::text", "")
    return re.sub(r'[\s()"]+', "", without_casts).lower()


async def _run_alembic_upgrade(dsn: str) -> None:
    """``alembic.command.upgrade(cfg, "head")``를 worker thread에서 실행.

    alembic은 sync API + 자체 asyncio.run(env.py)을 호출하므로 현재 pytest
    event loop과 충돌. ``asyncio.to_thread``로 별도 thread에서 alembic의
    asyncio 호출이 자기 event loop을 만들도록 분리.

    env.py는 ``Config.get_main_option("sqlalchemy.url")``을 우선 사용하므로
    여기서 박은 DSN이 적용됨 (KOR_TRAVEL_MAP_PG_DSN env var 불필요).
    """
    import asyncio
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    project_root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240  # sync IO is trivial path-arith here
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest.fixture(scope="session")
async def pg_engine_with_migrations(pg_container: object) -> object:
    """``pg_engine``과 동일하지만 alembic 적용 후 yield.

    ``pg_engine``의 schema/extension 직접 생성 fixture를 우회 — alembic가
    혼자 만들어내는지 확인하기 위함.
    """
    from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    async_dsn = normalize_async_dsn(raw_dsn)

    # alembic은 본인이 schema/extension 생성하므로 pg_engine의 setup은 건너뛴다.
    await _run_alembic_upgrade(async_dsn)

    engine = make_async_engine(async_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_alembic_creates_4_schemas(pg_engine_with_migrations: AsyncEngine) -> None:
    """0001 revision이 4 schema 생성."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname IN ('feature','provider_sync','ops','x_extension') "
                "ORDER BY nspname"
            )
        )
        schemas = [row[0] for row in result]
    assert schemas == ["feature", "ops", "provider_sync", "x_extension"]


async def test_alembic_creates_3_extensions_in_x_extension(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0001 revision이 3 extension을 ``x_extension``에 격리 생성 (ADR-008)."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT e.extname, n.nspname FROM pg_extension e "
                "JOIN pg_namespace n ON e.extnamespace = n.oid "
                "WHERE e.extname IN ('postgis','pg_trgm','pgcrypto') "
                "ORDER BY e.extname"
            )
        )
        rows = list(result)
    assert len(rows) == 3
    for ext_name, schema in rows:
        assert schema == "x_extension", (
            f"{ext_name} in {schema}, expected x_extension (ADR-008)"
        )


async def test_alembic_creates_features_table(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0002 revision이 ``feature.features`` 테이블 생성."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='feature' AND table_name='features' "
                "ORDER BY ordinal_position"
            )
        )
        columns = [row[0] for row in result]
    # 핵심 컬럼 존재 확인.
    for required in (
        "feature_id", "kind", "name", "category", "coord", "coord_5179",
        "coord_precision_digits", "geom", "address", "detail", "status",
        "created_at", "updated_at",
    ):
        assert required in columns, f"missing column: {required}"


async def test_alembic_coord_5179_is_generated_stored(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """ADR-012 — ``coord_5179``는 STORED generated column."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT is_generated, generation_expression "
                "FROM information_schema.columns "
                "WHERE table_schema='feature' AND table_name='features' "
                "AND column_name='coord_5179'"
            )
        )
        row = result.one()
    assert row.is_generated == "ALWAYS"
    # PostgreSQL은 generation_expression을 재파싱하며 함수명을 소문자 +
    # 스키마 한정으로 정규화한다 (예: ``x_extension.st_transform(coord, 5179)``).
    # 따라서 대소문자 무시하고 ``st_transform`` 참조만 확인 (ADR-008 + ADR-012).
    assert "st_transform" in (row.generation_expression or "").lower()


async def test_alembic_coord_precision_trigger_defaults_for_coord(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """T-RV-16 — coord가 있으면 DB trigger가 precision 기본값을 보강."""
    async with pg_engine_with_migrations.connect() as conn:
        tx = await conn.begin()
        try:
            await conn.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category, coord
                    ) VALUES (
                        'feature:precision-trigger',
                        'place',
                        'precision trigger',
                        '01070100',
                        x_extension.ST_SetSRID(
                            x_extension.ST_MakePoint(129.3320, 35.7900),
                            4326
                        )
                    )
                    """
                )
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT coord_precision_digits "
                        "FROM feature.features "
                        "WHERE feature_id = 'feature:precision-trigger'"
                    )
                )
            ).one()
        finally:
            await tx.rollback()
    assert row.coord_precision_digits == 6


async def test_alembic_creates_source_tables(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """provider sync의 entity / observation / link / cursor 테이블을 생성한다."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='provider_sync' "
                "ORDER BY table_name"
            )
        )
        tables = [row[0] for row in result]
    assert tables == [
        "notice_lifecycle_scopes",
        "notice_lineage_states",
        "provider_sync_state",
        "source_entities",
        "source_links",
        "source_records",
    ]


async def test_alembic_features_indexes_exist(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """핵심 GIST/GIN/partial 인덱스 존재."""
    async with pg_engine_with_migrations.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname='feature' AND tablename='features'"
            )
        )
        idx = {row[0] for row in result}
    required = {
        "idx_features_coord_gist",
        "idx_features_coord_5179_gist",
        "idx_features_geom_gist",
        "idx_features_kind_category",
        "idx_features_name_trgm",
    }
    missing = required - idx
    assert not missing, f"missing indexes: {missing}"


async def test_alembic_creates_feature_price_values_table(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0034 revision이 ``feature.feature_price_values``와 핵심 인덱스를 생성."""
    async with pg_engine_with_migrations.connect() as conn:
        columns = [
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='feature' "
                        "AND table_name='feature_price_values' "
                        "ORDER BY ordinal_position"
                    )
                )
            )
        ]
        indexes = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname='feature' "
                        "AND tablename='feature_price_values'"
                    )
                )
            )
        }

    for required in (
        "price_value_key",
        "feature_id",
        "provider",
        "price_domain",
        "product_key",
        "observed_at",
        "value_number",
        "source_record_key",
    ):
        assert required in columns
    assert {
        "idx_price_values_feature_observed_identity",
        "idx_price_values_observed_at_brin",
    } <= indexes


async def test_alembic_creates_feature_merge_history(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """0007 revision이 ``ops.feature_merge_history`` 생성 (ADR-016)."""
    async with pg_engine_with_migrations.connect() as conn:
        exists = (
            await conn.execute(
                text("SELECT to_regclass('ops.feature_merge_history')")
            )
        ).scalar_one()
    assert exists is not None


async def test_alembic_unmapped_tables_keep_structural_contract(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """metadata 제외 table의 전체 column과 핵심 constraint/index를 고정한다."""

    assert set(_UNMAPPED_TABLE_COLUMNS) == UNMAPPED_APP_TABLES
    assert set(_UNMAPPED_TABLE_CONSTRAINTS) == UNMAPPED_APP_TABLES
    assert set(_UNMAPPED_TABLE_INDEXES) == UNMAPPED_APP_TABLES

    async with pg_engine_with_migrations.connect() as conn:
        column_rows = await conn.execute(
            text(
                """
                SELECT
                    namespace.nspname AS schema_name,
                    relation.relname AS table_name,
                    attribute.attname AS column_name,
                    pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
                        AS formatted_type,
                    attribute.attnotnull AS not_null
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname IN ('feature', 'ops')
                  AND relation.relname = ANY(CAST(:table_names AS text[]))
                  AND relation.relkind IN ('r', 'p')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                """
            ),
            {"table_names": sorted({table for _, table in _UNMAPPED_TABLE_COLUMNS})},
        )
        constraint_rows = await conn.execute(
            text(
                """
                SELECT
                    namespace.nspname AS schema_name,
                    relation.relname AS table_name,
                    constraint_.conname AS constraint_name,
                    constraint_.contype AS constraint_type
                FROM pg_catalog.pg_constraint AS constraint_
                JOIN pg_catalog.pg_class AS relation
                  ON relation.oid = constraint_.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname IN ('feature', 'ops')
                  AND relation.relname = ANY(CAST(:table_names AS text[]))
                """
            ),
            {"table_names": sorted({table for _, table in _UNMAPPED_TABLE_COLUMNS})},
        )
        index_rows = await conn.execute(
            text(
                """
                SELECT schemaname AS schema_name, tablename AS table_name, indexname
                FROM pg_catalog.pg_indexes
                WHERE schemaname IN ('feature', 'ops')
                  AND tablename = ANY(CAST(:table_names AS text[]))
                """
            ),
            {"table_names": sorted({table for _, table in _UNMAPPED_TABLE_COLUMNS})},
        )

    actual_columns: dict[tuple[str, str], set[tuple[str, str, bool]]] = {
        key: set() for key in _UNMAPPED_TABLE_COLUMNS
    }
    for row in column_rows:
        key = (row.schema_name, row.table_name)
        if key in actual_columns:
            actual_columns[key].add(
                (row.column_name, row.formatted_type, row.not_null)
            )

    actual_constraints: dict[tuple[str, str], set[tuple[str, str]]] = {
        key: set() for key in _UNMAPPED_TABLE_CONSTRAINTS
    }
    for row in constraint_rows:
        key = (row.schema_name, row.table_name)
        if key in actual_constraints:
            constraint_type = row.constraint_type
            if isinstance(constraint_type, bytes):
                constraint_type = constraint_type.decode("ascii")
            actual_constraints[key].add((row.constraint_name, constraint_type))

    actual_indexes: dict[tuple[str, str], set[str]] = {
        key: set() for key in _UNMAPPED_TABLE_INDEXES
    }
    for row in index_rows:
        key = (row.schema_name, row.table_name)
        if key in actual_indexes:
            actual_indexes[key].add(row.indexname)

    assert actual_columns == _UNMAPPED_TABLE_COLUMNS
    for key, required in _UNMAPPED_TABLE_CONSTRAINTS.items():
        assert required <= actual_constraints[key], f"{key} constraint drift"
    for key, required in _UNMAPPED_TABLE_INDEXES.items():
        assert required <= actual_indexes[key], f"{key} index drift"


async def test_alembic_uncompared_indexes_keep_exact_semantics(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """비교 제외 index의 UNIQUE·키 순서·predicate를 catalog로 고정한다."""

    assert set(_UNCOMPARED_INDEX_CONTRACTS) == UNCOMPARED_INDEXES

    async with pg_engine_with_migrations.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT
                    namespace.nspname AS schema_name,
                    index_relation.relname AS index_name,
                    index_.indisunique AS is_unique,
                    ARRAY(
                        SELECT
                            pg_get_indexdef(
                                index_.indexrelid,
                                key_position,
                                true
                            )
                            || CASE
                                WHEN (
                                    index_.indoption[key_position - 1] & 1
                                ) = 1 THEN ' DESC'
                                ELSE ' ASC'
                            END
                            || CASE
                                WHEN (
                                    index_.indoption[key_position - 1] & 2
                                ) = 2 THEN ' NULLS FIRST'
                                ELSE ' NULLS LAST'
                            END
                        FROM generate_series(1, index_.indnkeyatts) AS key_position
                        ORDER BY key_position
                    ) AS key_expressions,
                    pg_get_expr(index_.indpred, index_.indrelid, true) AS predicate
                FROM pg_catalog.pg_index AS index_
                JOIN pg_catalog.pg_class AS index_relation
                  ON index_relation.oid = index_.indexrelid
                JOIN pg_catalog.pg_class AS table_relation
                  ON table_relation.oid = index_.indrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = table_relation.relnamespace
                WHERE index_relation.relname = ANY(CAST(:index_names AS text[]))
                """
            ),
            {
                "index_names": sorted(
                    index_name for _, index_name in _UNCOMPARED_INDEX_CONTRACTS
                )
            },
        )

    actual = {
        (row.schema_name, row.index_name): (
            row.is_unique,
            tuple(_canonical_pg_sql(value) for value in row.key_expressions),
            _canonical_pg_sql(row.predicate),
        )
        for row in rows
    }
    expected = {
        key: (
            is_unique,
            tuple(_canonical_pg_sql(value) for value in key_expressions),
            _canonical_pg_sql(predicate),
        )
        for key, (is_unique, key_expressions, predicate) in (
            _UNCOMPARED_INDEX_CONTRACTS.items()
        )
    }

    assert actual == expected


async def test_alembic_security_table_checks_reject_invalid_rows(
    pg_engine_with_migrations: AsyncEngine,
) -> None:
    """인증/운영 제외 table의 핵심 CHECK가 이름만 남은 퇴행을 막는다."""

    invalid_inserts = (
        "INSERT INTO ops.system_log "
        "(level, source, event, message) VALUES ('invalid', 'test', 'test', 'test')",
        "INSERT INTO ops.public_api_keys (key_hash, key_hint) "
        "VALUES ('not-a-sha256', '123456')",
        "INSERT INTO ops.admin_auth_events (event_type, outcome) "
        "VALUES ('invalid', 'succeeded')",
        "INSERT INTO ops.ops_live_ticket_claims (nonce_hash, actor, expires_at) "
        "VALUES (decode('00', 'hex'), 'test', now())",
        "INSERT INTO ops.ops_live_topic_revisions (topic, revision) "
        "VALUES ('review-contract', -1)",
    )
    async with pg_engine_with_migrations.connect() as conn:
        for statement in invalid_inserts:
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(text(statement))
