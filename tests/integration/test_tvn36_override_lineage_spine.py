"""T-VN-36A registry·provider base lineage의 실제 PostgreSQL 계약."""

from __future__ import annotations

from contextlib import suppress

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_SOURCE_HASH = "a" * 64


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def _constraint_name(error: DBAPIError) -> str | None:
    candidate: BaseException | None = error.orig
    while candidate is not None:
        value = getattr(candidate, "constraint_name", None)
        if isinstance(value, str):
            return value
        candidate = candidate.__cause__
    return None


async def _seed_feature_source(session: AsyncSession) -> tuple[str, int]:
    feature_id = "tvn36-lineage-place"
    dataset_id = int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                        provider, dataset_key, display_name, source_kind
                    ) VALUES ('tvn36', 'lineage', 'T-VN-36 lineage', 'manual')
                    RETURNING provider_dataset_id
                    """
                )
            )
        ).scalar_one()
    )
    for statement in (
        """
        INSERT INTO provider_sync.source_entities (
            source_entity_key, provider_dataset_id, source_entity_type,
            source_entity_id, first_seen_at, last_seen_at
        ) VALUES ('tvn36-lineage-entity', :dataset_id, 'place', 'lineage', now(), now())
        """,
        """
        INSERT INTO provider_sync.source_records (
            source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
        ) VALUES ('tvn36-lineage-record', 'tvn36-lineage-entity',
                  '{}'::jsonb, :source_hash, now())
        """,
        """
        INSERT INTO provider_sync.source_entity_heads (
            source_entity_key, current_source_record_key, observed_at
        ) VALUES ('tvn36-lineage-entity', 'tvn36-lineage-record', now())
        """,
        """
        INSERT INTO feature.features (
            feature_id, feature_uuid, kind, name, category,
            lifecycle_state, publication_state, quality_state
        ) VALUES (
            :feature_id, x_extension.gen_random_uuid(), 'place', 'provider place',
            '01010100', 'active', 'published', 'valid'
        )
        """,
    ):
        await session.execute(
            text(statement),
            {
                "dataset_id": dataset_id,
                "feature_id": feature_id,
                "source_hash": _SOURCE_HASH,
            },
        )
    return feature_id, dataset_id


async def test_tvn36_registry_base_lineage_and_override_type_fence(
    migrated_session: AsyncSession,
) -> None:
    """64 path registry와 typed provider base/override rejection을 DB에서 검증한다."""

    feature_id, dataset_id = await _seed_feature_source(migrated_session)
    registry_count = int(
        (
            await migrated_session.execute(
                text("SELECT count(*) FROM ops.feature_override_field_paths")
            )
        ).scalar_one()
    )
    assert registry_count == 64

    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.feature_base_field_values (
                feature_id, field_path, feature_uuid, provider_dataset_id,
                source_entity_key, source_record_key, source_raw_payload_hash,
                value_json, base_revision, observed_at
            )
            SELECT :feature_id, 'core.name', feature_uuid, :dataset_id,
                   'tvn36-lineage-entity', 'tvn36-lineage-record', :source_hash,
                   '"canonical provider name"'::jsonb, row_revision, now()
            FROM feature.features WHERE feature_id = :feature_id
            """
        ),
        {
            "feature_id": feature_id,
            "dataset_id": dataset_id,
            "source_hash": _SOURCE_HASH,
        },
    )
    base_value = (
        await migrated_session.execute(
            text(
                """
                SELECT field_path, value_json, source_raw_payload_hash
                FROM feature.feature_base_field_values
                WHERE feature_id = :feature_id AND field_path = 'core.name'
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert dict(base_value) == {
        "field_path": "core.name",
        "value_json": "canonical provider name",
        "source_raw_payload_hash": _SOURCE_HASH,
    }

    with pytest.raises(DBAPIError) as wrong_base_type:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO feature.feature_base_field_values (
                        feature_id, field_path, feature_uuid, provider_dataset_id,
                        source_entity_key, source_record_key, source_raw_payload_hash,
                        value_json, base_revision, observed_at
                    )
                    SELECT :feature_id, 'core.marker_color', feature_uuid, :dataset_id,
                           'tvn36-lineage-entity', 'tvn36-lineage-record', :source_hash,
                           '7'::jsonb, row_revision, now()
                    FROM feature.features WHERE feature_id = :feature_id
                    """
                ),
                {
                    "feature_id": feature_id,
                    "dataset_id": dataset_id,
                    "source_hash": _SOURCE_HASH,
                },
            )
    assert _sqlstate(wrong_base_type.value) == "23514"
    assert _constraint_name(wrong_base_type.value) == "ck_feature_base_field_value"

    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_overrides (
                feature_id, field_path, override_value, status, reason, created_by,
                base_revision
            ) VALUES (
                :feature_id, 'core.name', '"operator name"'::jsonb, 'active',
                'T-VN-36 typed override fixture', 'admin:tvn36', 1
            )
            """
        ),
        {"feature_id": feature_id},
    )
    with pytest.raises(DBAPIError) as mismatched_target:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO ops.feature_overrides (
                        feature_id, field_path, value_geometry, status, reason, created_by
                    ) VALUES (
                        :feature_id, 'route.geom',
                        x_extension.ST_GeomFromText('MULTILINESTRING((126 37,126.1 37.1))', 4326),
                        'active', 'wrong subtype', 'admin:tvn36'
                    )
                    """
                ),
                {"feature_id": feature_id},
            )
    assert _sqlstate(mismatched_target.value) == "23514"
    assert _constraint_name(mismatched_target.value) == "ck_feature_override_field_target"


async def test_tvn36_runtime_cannot_mutate_lineage_relations(
    migrated_session: AsyncSession,
) -> None:
    """runtime은 registry 읽기만 가능하고 base/override 직접 DML은 42501이다."""

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        assert int(
            (
                await migrated_session.execute(
                    text("SELECT count(*) FROM ops.feature_override_field_paths")
                )
            ).scalar_one()
        ) == 64
        for forbidden_sql in (
            "INSERT INTO ops.feature_override_field_paths ("
            "field_path, feature_kind, target_relation, target_column, value_kind, "
            "allows_null, requires_source, provider_writable, operator_writable, sort_order) "
            "VALUES ('bad.path','*','features','name','text',false,true,true,true,1)",
            "UPDATE ops.feature_override_field_paths SET sort_order = sort_order WHERE FALSE",
            "INSERT INTO feature.feature_base_field_values (feature_id, field_path) "
            "VALUES ('missing','core.name')",
            "UPDATE ops.feature_overrides SET status = status WHERE FALSE",
        ):
            with pytest.raises(DBAPIError) as rejected:
                async with migrated_session.begin_nested():
                    await migrated_session.execute(text(forbidden_sql))
            assert _sqlstate(rejected.value) == "42501"
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))
