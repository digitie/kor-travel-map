"""T-VN-36A registry·provider base lineage의 실제 PostgreSQL 계약."""

from __future__ import annotations

from contextlib import suppress

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.admin_feature_repo import (
    FeatureFieldOverrideNotFound,
    FeatureFieldOverridePreconditionFailed,
    FeatureFieldOverrideValidationError,
    author_admin_feature_field_overrides,
    revoke_admin_feature_field_overrides,
)

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
        """
        INSERT INTO feature.feature_places (feature_id, feature_uuid, kind, place_kind)
        SELECT feature_id, feature_uuid, kind, 'tourism'
        FROM feature.features
        WHERE feature_id = :feature_id
        """,
        """
        INSERT INTO provider_sync.source_links (
            feature_id, source_entity_key, source_role, match_method, confidence
        ) VALUES (
            :feature_id, 'tvn36-lineage-entity', 'primary', 'fixture', 100
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

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        async with migrated_session.begin_nested():
            applied = (
                await migrated_session.execute(
                    text(
                        """
                        CALL feature.apply_provider_feature_field_patch(
                            :feature_id, :dataset_id, 'tvn36-lineage-entity',
                            'tvn36-lineage-record', 1,
                            CAST(:values AS jsonb), CAST(:geometry_wkt AS jsonb),
                            NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "feature_id": feature_id,
                        "dataset_id": dataset_id,
                        "values": '{"core.name":"fresh provider name","place.biz_number":"123"}',
                        "geometry_wkt": "{}",
                    },
                )
            ).mappings().one()
    finally:
        await migrated_session.execute(text("RESET ROLE"))
    assert dict(applied) == {
        "o_feature_id": feature_id,
        "o_row_revision": 2,
        "o_applied_field_count": 2,
    }
    effective = (
        await migrated_session.execute(
            text(
                """
                SELECT core.name, place.biz_number
                FROM feature.features AS core
                JOIN feature.feature_places AS place USING (feature_id)
                WHERE core.feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert dict(effective) == {"name": "fresh provider name", "biz_number": "123"}

    # JSON ``null``은 field omission이 아니다. nullable core coordinate의 provider
    # observation은 base ledger와 typed effective column을 함께 명시적으로 비운다.
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        async with migrated_session.begin_nested():
            cleared_coordinate = (
                await migrated_session.execute(
                    text(
                        """
                        CALL feature.apply_provider_feature_field_patch(
                            :feature_id, :dataset_id, 'tvn36-lineage-entity',
                            'tvn36-lineage-record', 2,
                            '{"core.name":"fresh provider name"}'::jsonb,
                            CAST(:cleared_geometry AS jsonb),
                            NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "feature_id": feature_id,
                        "dataset_id": dataset_id,
                        "cleared_geometry": '{"core.coord":null}',
                    },
                )
            ).mappings().one()
    finally:
        await migrated_session.execute(text("RESET ROLE"))
    assert dict(cleared_coordinate) == {
        "o_feature_id": feature_id,
        "o_row_revision": 3,
        "o_applied_field_count": 2,
    }
    coordinate_state = (
        await migrated_session.execute(
            text(
                """
                SELECT core.coord IS NULL AS coord_is_null, base.value_json,
                       base.value_geometry IS NULL AS geometry_is_null
                FROM feature.features AS core
                JOIN feature.feature_base_field_values AS base
                  ON base.feature_id = core.feature_id
                 AND base.field_path = 'core.coord'
                WHERE core.feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert dict(coordinate_state) == {
        "coord_is_null": True,
        "value_json": None,
        "geometry_is_null": True,
    }

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        with pytest.raises(DBAPIError) as wrong_feature_kind:
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        """
                        CALL feature.apply_provider_feature_field_patch(
                            :feature_id, :dataset_id, 'tvn36-lineage-entity',
                            'tvn36-lineage-record', 3,
                            '{"route.route_type":"trail"}'::jsonb, '{}'::jsonb,
                            NULL, NULL, NULL
                        )
                        """
                    ),
                    {"feature_id": feature_id, "dataset_id": dataset_id},
                )
    finally:
        await migrated_session.execute(text("RESET ROLE"))
    assert _sqlstate(wrong_feature_kind.value) == "23514"
    assert _constraint_name(wrong_feature_kind.value) == "ck_feature_provider_field_path"

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

    author_command_id = int(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                        actor, operation, idempotency_key, fingerprint_version,
                        request_fingerprint
                    ) VALUES (
                        'admin:tvn36', 'admin.feature.override.author',
                        x_extension.gen_random_uuid(), 1, :fingerprint
                    )
                    RETURNING command_id
                    """
                ),
                {"fingerprint": "b" * 64},
            )
        ).scalar_one()
    )
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        async with migrated_session.begin_nested():
            authored = (
                await migrated_session.execute(
                    text(
                        """
                        CALL feature.author_feature_field_overrides(
                            :feature_id, 3, 'admin:tvn36', 'operator_correction',
                            :command_id,
                            '{"core.name":"operator name"}'::jsonb, '{}'::jsonb,
                            NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"feature_id": feature_id, "command_id": author_command_id},
                )
            ).mappings().one()
    finally:
        await migrated_session.execute(text("RESET ROLE"))
    assert dict(authored) == {
        "o_feature_id": feature_id,
        "o_row_revision": 4,
        "o_command_id": author_command_id,
        "o_applied_field_count": 1,
    }
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        async with migrated_session.begin_nested():
            masked = (
                await migrated_session.execute(
                    text(
                        """
                        CALL feature.apply_provider_feature_field_patch(
                            :feature_id, :dataset_id, 'tvn36-lineage-entity',
                            'tvn36-lineage-record', 4,
                            CAST(:values AS jsonb), CAST(:geometry_wkt AS jsonb),
                            NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "feature_id": feature_id,
                        "dataset_id": dataset_id,
                        "values": '{"core.name":"masked provider name","place.biz_number":"456"}',
                        "geometry_wkt": "{}",
                    },
                )
            ).mappings().one()
    finally:
        await migrated_session.execute(text("RESET ROLE"))
    assert dict(masked) == {
        "o_feature_id": feature_id,
        "o_row_revision": 5,
        "o_applied_field_count": 2,
    }
    masked_effective = (
        await migrated_session.execute(
            text(
                """
                SELECT core.name, place.biz_number, base.value_json
                FROM feature.features AS core
                JOIN feature.feature_places AS place USING (feature_id)
                JOIN feature.feature_base_field_values AS base
                  ON base.feature_id = core.feature_id
                 AND base.field_path = 'core.name'
                WHERE core.feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert dict(masked_effective) == {
        "name": "operator name",
        "biz_number": "456",
        "value_json": "masked provider name",
    }
    revoke_command_id = int(
        (
            await migrated_session.execute(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                        actor, operation, idempotency_key, fingerprint_version,
                        request_fingerprint
                    ) VALUES (
                        'admin:tvn36', 'admin.feature.override.revoke',
                        x_extension.gen_random_uuid(), 1, :fingerprint
                    )
                    RETURNING command_id
                    """
                ),
                {"fingerprint": "c" * 64},
            )
        ).scalar_one()
    )
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        async with migrated_session.begin_nested():
            revoked = (
                await migrated_session.execute(
                    text(
                        """
                        CALL feature.revoke_feature_field_overrides(
                            :feature_id, 5, 'admin:tvn36', 'operator_revoke',
                            :command_id, ARRAY['core.name'],
                            NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"feature_id": feature_id, "command_id": revoke_command_id},
                )
            ).mappings().one()
    finally:
        await migrated_session.execute(text("RESET ROLE"))
    assert dict(revoked) == {
        "o_feature_id": feature_id,
        "o_row_revision": 6,
        "o_command_id": revoke_command_id,
        "o_applied_field_count": 1,
    }
    restored = (
        await migrated_session.execute(
            text(
                """
                SELECT core.name, count(override.override_id) AS active_override_count
                FROM feature.features AS core
                LEFT JOIN ops.feature_overrides AS override
                  ON override.feature_id = core.feature_id
                 AND override.field_path = 'core.name'
                 AND override.status = 'active'
                WHERE core.feature_id = :feature_id
                GROUP BY core.name
                """
            ),
            {"feature_id": feature_id},
        )
    ).mappings().one()
    assert dict(restored) == {
        "name": "masked provider name",
        "active_override_count": 0,
    }
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


async def _open_domain_command(
    session: AsyncSession, *, actor: str, operation: str
) -> int:
    return int(
        (
            await session.execute(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                        actor, operation, idempotency_key, fingerprint_version,
                        request_fingerprint
                    ) VALUES (
                        :actor, :operation, x_extension.gen_random_uuid(), 1, :fingerprint
                    )
                    RETURNING command_id
                    """
                ),
                {"actor": actor, "operation": operation, "fingerprint": "d" * 64},
            )
        ).scalar_one()
    )


async def test_field_override_procedure_errors_survive_as_domain_errors(
    migrated_session: AsyncSession,
) -> None:
    """override procedure의 DB contract가 **실 DB에서** 도메인 오류로 보존되는지 본다.

    이 축이 없으면 매핑은 조용히 죽는다 — T-VN-34에서 실제로 그랬다. asyncpg는 진단
    속성을 ``error.orig``(SQLAlchemy DBAPI 래퍼)가 아니라 그 ``__cause__``에 두므로
    ``orig``만 보는 추출기는 SQLSTATE를 **항상 None**으로 읽고, 그러면 P0002/40001/23514가
    전부 라우터의 except 사슬을 통과해 catch-all 500이 된다. 단언 대상을 상태코드가 아니라
    **도메인 예외 타입**으로 두는 이유는 라우터가 그 타입으로 404/412/422를 만들기 때문이다
    (타입이 맞으면 상태코드는 라우터 테스트가 고정한다).
    """

    feature_id, _ = await _seed_feature_source(migrated_session)
    actor = "admin:tvn36-mapping"
    revision = int(
        (
            await migrated_session.execute(
                text("SELECT row_revision FROM feature.features WHERE feature_id = :fid"),
                {"fid": feature_id},
            )
        ).scalar_one()
    )

    # P0002 — 없는 feature.
    command_id = await _open_domain_command(
        migrated_session, actor=actor, operation="admin.feature.override.author"
    )
    with pytest.raises(FeatureFieldOverrideNotFound):
        async with migrated_session.begin_nested():
            await author_admin_feature_field_overrides(
                migrated_session,
                "tvn36-no-such-feature",
                expected_row_revision=1,
                reason_code="operator_correction",
                operator=actor,
                command_id=command_id,
                values={"core.name": "이름"},
                geometry_wkt={},
            )

    # 40001 — stale If-Match revision.
    command_id = await _open_domain_command(
        migrated_session, actor=actor, operation="admin.feature.override.author"
    )
    with pytest.raises(FeatureFieldOverridePreconditionFailed) as stale:
        async with migrated_session.begin_nested():
            await author_admin_feature_field_overrides(
                migrated_session,
                feature_id,
                expected_row_revision=revision + 41,
                reason_code="operator_correction",
                operator=actor,
                command_id=command_id,
                values={"core.name": "이름"},
                geometry_wkt={},
            )
    assert stale.value.expected == revision + 41

    # 23514 — registry에 없는 field path.
    command_id = await _open_domain_command(
        migrated_session, actor=actor, operation="admin.feature.override.author"
    )
    with pytest.raises(FeatureFieldOverrideValidationError):
        async with migrated_session.begin_nested():
            await author_admin_feature_field_overrides(
                migrated_session,
                feature_id,
                expected_row_revision=revision,
                reason_code="operator_correction",
                operator=actor,
                command_id=command_id,
                values={"core.not_a_registered_path": "이름"},
                geometry_wkt={},
            )

    # 23514 — author 전용 command로 revoke를 시도하면 operation allow-list가 막는다.
    command_id = await _open_domain_command(
        migrated_session, actor=actor, operation="admin.feature.override.author"
    )
    with pytest.raises(FeatureFieldOverrideValidationError):
        async with migrated_session.begin_nested():
            await revoke_admin_feature_field_overrides(
                migrated_session,
                feature_id,
                expected_row_revision=revision,
                reason_code="operator_correction",
                operator=actor,
                command_id=command_id,
                field_paths=("core.name",),
            )
