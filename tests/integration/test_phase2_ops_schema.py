"""ADR-045 T-205c Phase 2 ops schema 계약 검증."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_phase2_ops_tables_and_indexes_exist(
    migrated_session: AsyncSession,
) -> None:
    tables = {
        row[0]
        for row in (
            await migrated_session.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'ops'
                      AND table_name = ANY(CAST(:tables AS text[]))
                    """
                ),
                {
                    "tables": [
                        "data_integrity_violations",
                        "poi_cache_targets",
                        "poi_cache_target_feature_links",
                        "provider_refresh_policies",
                    ]
                },
            )
        ).all()
    }
    assert tables == {
        "data_integrity_violations",
        "poi_cache_targets",
        "poi_cache_target_feature_links",
        "provider_refresh_policies",
    }

    indexes = {
        row[0]
        for row in (
            await migrated_session.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'ops'
                      AND indexname = ANY(CAST(:indexes AS text[]))
                    """
                ),
                {
                    "indexes": [
                        "idx_violations_type_status",
                        "idx_violations_feature",
                        "idx_violations_source_record",
                        "idx_violations_detected_brin",
                        "uq_poi_cache_targets_active_key",
                        "idx_poi_cache_targets_coord_5179",
                        "idx_poi_cache_targets_next_refresh",
                        "idx_poi_cache_links_feature",
                        "idx_poi_cache_links_provider_dataset",
                        "idx_provider_refresh_enabled",
                        "idx_provider_refresh_source_kind",
                    ]
                },
            )
        ).all()
    }
    assert indexes == {
        "idx_violations_type_status",
        "idx_violations_feature",
        "idx_violations_source_record",
        "idx_violations_detected_brin",
        "uq_poi_cache_targets_active_key",
        "idx_poi_cache_targets_coord_5179",
        "idx_poi_cache_targets_next_refresh",
        "idx_poi_cache_links_feature",
        "idx_poi_cache_links_provider_dataset",
        "idx_provider_refresh_enabled",
        "idx_provider_refresh_source_kind",
    }


async def test_poi_cache_target_generated_coord_and_active_key(
    migrated_session: AsyncSession,
) -> None:
    row = (
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.poi_cache_targets (
                    external_system, target_key, lon, lat, coord,
                    coord_key, radius_km
                )
                VALUES (
                    'tripmate', 'poi-1', 126.978, 37.5665,
                    x_extension.ST_SetSRID(
                        x_extension.ST_MakePoint(126.978, 37.5665),
                        4326
                    ),
                    '126.978000:37.566500:p6', 5.0
                )
                RETURNING
                    target_id, update_enabled, refresh_policy,
                    coord_5179 IS NOT NULL AS has_coord_5179
                """
            )
        )
    ).mappings().one()

    assert row["target_id"]
    assert row["update_enabled"] is True
    assert row["refresh_policy"] == "provider_default"
    assert row["has_coord_5179"] is True

    with pytest.raises(IntegrityError):
        await migrated_session.execute(
            text(
                """
                INSERT INTO ops.poi_cache_targets (
                    external_system, target_key, lon, lat, coord,
                    coord_key, radius_km
                )
                VALUES (
                    'tripmate', 'poi-1', 126.979, 37.5666,
                    x_extension.ST_SetSRID(
                        x_extension.ST_MakePoint(126.979, 37.5666),
                        4326
                    ),
                    '126.979000:37.566600:p6', 5.0
                )
                """
            )
        )


@pytest.mark.parametrize(
    ("table_sql", "params"),
    [
        (
            """
            INSERT INTO ops.data_integrity_violations (
                violation_type, severity, message
            )
            VALUES ('F6_opening_hours_conflict', 'bad', 'bad severity')
            """,
            {},
        ),
        (
            """
            INSERT INTO ops.provider_refresh_policies (
                provider, dataset_key, source_kind, max_concurrent
            )
            VALUES ('python-kma-api', 'kma_weather_alerts', 'openapi', 0)
            """,
            {},
        ),
        (
            """
            INSERT INTO ops.poi_cache_targets (
                external_system, target_key, lon, lat, coord,
                coord_key, radius_km
            )
            VALUES (
                'tripmate', 'bad-coord', 140.0, 37.5665,
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(140.0, 37.5665), 4326),
                '140.000000:37.566500:p6', 5.0
            )
            """,
            {},
        ),
    ],
)
async def test_phase2_check_constraints(
    migrated_session: AsyncSession,
    table_sql: str,
    params: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError):
        await migrated_session.execute(text(table_sql), params)
