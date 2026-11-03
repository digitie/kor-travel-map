"""같은 원본의 분류 재투영은 base만 바꾸며 운영자 값과 source 증거를 보존한다."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.infra import admin_feature_repo, feature_identity, feature_repo
from kortravelmap.providers.mcst import file_rows_to_bundles
from tests.integration.conftest import as_api_runtime, as_dagster_runtime
from tests.integration.test_tvn36_override_lineage_spine import _open_domain_command

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration
_FETCHED = datetime(2026, 11, 4, tzinfo=UTC)


async def _mcst_bundle(info: str = "", fetched_at: datetime = _FETCHED):
    [bundle] = await file_rows_to_bundles(
        [{"TITLE": "원천 분류 재투영 호텔", "CATEGORY1": "숙박시설", "CATEGORY2": "호텔",
          "CATEGORY3": "관광호텔", "INFORMATION": info, "ADDRESS": "서울특별시 종로구 세종대로 1",
          "COORDINATES": "N37.5665, E126.9784"}],
        slug="pet_friendly_culture_facilities_csv", fetched_at=fetched_at,
    )
    return bundle


async def _revision(session: AsyncSession, feature_id: str) -> int:
    return int(await session.scalar(text(
        "SELECT row_revision FROM feature.features WHERE feature_id=CAST(:id AS uuid)"
    ), {"id": feature_id}))


async def _snapshot(session: AsyncSession, feature_id: str):
    return (await session.execute(text("""
        SELECT to_jsonb(f) AS core,
          (SELECT jsonb_agg(to_jsonb(b) ORDER BY field_path)
           FROM feature.feature_base_field_values b WHERE b.feature_id=f.feature_id) AS base,
          (SELECT jsonb_agg(to_jsonb(s) ORDER BY source_entity_key)
           FROM provider_sync.source_links s WHERE s.feature_id=f.feature_id) AS links,
          (SELECT count(*) FROM feature.feature_state_transitions t
           WHERE t.feature_id=f.feature_id) AS states
        FROM feature.features f WHERE feature_id=CAST(:id AS uuid)
    """), {"id": feature_id})).mappings().one()


@pytest.mark.parametrize("override", [False, True])
async def test_same_raw_head_reprojects_once_and_preserves_effective_override(
    migrated_session: AsyncSession, override: bool,
) -> None:
    bundle = await _mcst_bundle()
    old = bundle.model_copy(update={"feature": bundle.feature.model_copy(update={
        "category": "01040000", "marker_icon": "museum",
    })})
    async with as_dagster_runtime(migrated_session):
        await feature_repo.load_bundle(migrated_session, old)
    identity = await feature_identity.resolve_feature_identity(
        migrated_session, bundle.feature.feature_id,
    )
    assert identity is not None
    feature_id = identity.feature_id
    if override:
        async with as_api_runtime(migrated_session):
            command = await _open_domain_command(
                migrated_session, actor="admin:projection-test",
                operation="admin.feature.override.author",
            )
            await admin_feature_repo.author_admin_feature_field_overrides(
                migrated_session, feature_id,
                expected_row_revision=await _revision(migrated_session, feature_id),
                reason_code="operator_category", operator="admin:projection-test",
                command_id=command, values={"core.category": "01070400"}, geometry_wkt={},
            )
    before = await _snapshot(migrated_session, feature_id)
    before_heads = (await migrated_session.execute(text(
        "SELECT to_jsonb(h) FROM provider_sync.source_entity_heads h"
    ))).all()
    async with as_dagster_runtime(migrated_session):
        result = await feature_repo.load_bundle(migrated_session, bundle)
    assert result.features_updated == 1
    after = await _snapshot(migrated_session, feature_id)
    assert after["core"]["category"] == ("01070400" if override else "03010100")
    assert after["core"]["marker_color"] == before["core"]["marker_color"]
    assert after["core"]["address"] == before["core"]["address"]
    assert after["links"] == before["links"]
    assert after["states"] == before["states"]
    assert (await migrated_session.execute(text(
        "SELECT to_jsonb(h) FROM provider_sync.source_entity_heads h"
    ))).all() == before_heads
    base = {r["field_path"]: r for r in after["base"]}
    assert base["core.category"]["value_json"] == "03010100"
    async with as_dagster_runtime(migrated_session):
        again = await feature_repo.load_bundle(migrated_session, bundle)
    assert again.features_updated == 0
    assert await _snapshot(migrated_session, feature_id) == after
    if override:
        async with as_api_runtime(migrated_session):
            command = await _open_domain_command(
                migrated_session, actor="admin:projection-test",
                operation="admin.feature.override.revoke",
            )
            await admin_feature_repo.revoke_admin_feature_field_overrides(
                migrated_session, feature_id,
                expected_row_revision=await _revision(migrated_session, feature_id),
                reason_code="operator_revoke", operator="admin:projection-test",
                command_id=command, field_paths=["core.category"],
            )
        assert (await _snapshot(migrated_session, feature_id))["core"]["category"] == "03010100"


@pytest.mark.parametrize("operator_state", ["none", "quarantined", "venue_override", "retired"])
async def test_existing_event_quality_is_one_way_and_respects_operator_values(
    migrated_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, operator_state: str,
) -> None:
    from datetime import date

    from kortravelmap.dto import FeatureQualityState
    from kortravelmap.providers.krheritage import heritage_events_to_bundles
    from tests.unit.test_providers_krheritage import _Event

    event = _Event(sn="QUALITY-REPROJECTION", title="품질 회귀 행사",
                   starts_on=date(2026, 5, 1), ends_on=date(2026, 5, 3),
                   place="", raw={"sDate": "2026-05-01", "eDate": "2026-05-03", "subDesc": ""})
    [bundle] = await heritage_events_to_bundles([event], fetched_at=_FETCHED)
    old = bundle.model_copy(update={"feature": bundle.feature.model_copy(update={
        "quality_state": FeatureQualityState.VALID, "category": "01070000",
    })})

    async def old_normalizer(*args, **kwargs):
        return False

    # 실제 구버전의 이미 존재하는 valid 행을 구성한다. 이후 호출은 실제 writer다.
    with monkeypatch.context() as setup_patch:
        setup_patch.setattr(feature_repo, "_repair_current_provider_projection", old_normalizer)
        async with as_dagster_runtime(migrated_session):
            await feature_repo.load_bundle(migrated_session, old)
    identity = await feature_identity.resolve_feature_identity(
        migrated_session, bundle.feature.feature_id,
    )
    assert identity is not None
    feature_id = identity.feature_id
    if operator_state in {"quarantined", "retired"}:
        async with as_api_runtime(migrated_session):
            await admin_feature_repo.transition_admin_feature_state(
                migrated_session, feature_id,
                quality_state="quarantined" if operator_state == "quarantined" else None,
                expected_row_revision=await _revision(migrated_session, feature_id),
                reason_code="operator_quality", operator="admin:projection-test",
                action="patch" if operator_state == "quarantined" else "retire",
            )
    if operator_state == "venue_override":
        async with as_api_runtime(migrated_session):
            command = await _open_domain_command(
                migrated_session, actor="admin:projection-test",
                operation="admin.feature.override.author",
            )
            await admin_feature_repo.author_admin_feature_field_overrides(
                migrated_session, feature_id,
                expected_row_revision=await _revision(migrated_session, feature_id),
                reason_code="operator_venue", operator="admin:projection-test",
                command_id=command, values={"event.venue_name": "종묘"}, geometry_wkt={},
            )
    before = await _snapshot(migrated_session, feature_id)
    async with as_dagster_runtime(migrated_session):
        await feature_repo.load_bundle(migrated_session, bundle)
    after = await _snapshot(migrated_session, feature_id)
    expected = "valid" if operator_state in {"venue_override", "retired"} else "quarantined"
    assert after["core"]["quality_state"] == expected
    assert after["core"]["lifecycle_state"] == before["core"]["lifecycle_state"]
    assert after["core"]["publication_state"] == before["core"]["publication_state"]
    assert after["states"] == before["states"] + (operator_state == "none")
    async with as_dagster_runtime(migrated_session):
        again = await feature_repo.load_bundle(migrated_session, bundle)
    assert again.features_updated == 0
    assert await _snapshot(migrated_session, feature_id) == after


async def test_projection_reader_has_only_required_base_columns(
    migrated_session: AsyncSession,
) -> None:
    allowed = {"feature_id", "field_path", "provider_dataset_id", "source_entity_key", "value_json"}
    columns = (await migrated_session.execute(text("""
        SELECT column_name,
               has_column_privilege('ktm_feature_runtime',
                   'feature.feature_base_field_values', column_name, 'SELECT') AS can_read,
               has_column_privilege('ktm_feature_runtime',
                   'feature.feature_base_field_values', column_name, 'UPDATE') AS can_update,
               has_column_privilege('ktm_feature_runtime',
                   'feature.feature_base_field_values', column_name, 'INSERT') AS can_insert
        FROM information_schema.columns
        WHERE table_schema='feature' AND table_name='feature_base_field_values'
    """))).mappings().all()
    assert columns
    assert {row["column_name"] for row in columns if row["can_read"]} == allowed
    assert not any(row["can_update"] or row["can_insert"] for row in columns)
    assert not await migrated_session.scalar(text("""
        SELECT has_table_privilege('ktm_feature_runtime',
                                   'feature.feature_base_field_values', 'SELECT')
    """))


async def test_kha_legacy_fallback_period_conflict_preserves_existing_source_and_feature(
    migrated_session: AsyncSession,
) -> None:
    from dataclasses import replace
    from datetime import date

    from kortravelmap.infra.feature_identity import FeatureIdentityAnchorError
    from kortravelmap.providers.krheritage import heritage_events_to_bundles
    from tests.unit.test_providers_krheritage import _Event

    first = _Event(sn=None, title="fallback 동명 행사", starts_on=date(2026, 5, 1),
                   ends_on=date(2026, 5, 3), place="종묘",
                   raw={"sDate": "2026-05-01", "eDate": "2026-05-03", "subDesc": "종묘"})
    [a] = await heritage_events_to_bundles([first], fetched_at=_FETCHED)
    second = replace(first, ends_on=date(2026, 5, 4),
                     raw={**first.raw, "eDate": "2026-05-04"})
    [b] = await heritage_events_to_bundles(
        [second], fetched_at=_FETCHED + timedelta(days=1),
    )
    # 기존 fallback natural key와 legacy 별칭의 호환을 유지하므로 최종 writer에서 거부한다.
    assert a.feature.provider_natural_key == b.feature.provider_natural_key
    async with as_dagster_runtime(migrated_session):
        await feature_repo.load_bundle(migrated_session, a)
    identity = await feature_identity.resolve_feature_identity(
        migrated_session, a.feature.feature_id,
    )
    assert identity is not None
    before = await _snapshot(migrated_session, identity.feature_id)
    source_before = (await migrated_session.execute(text(
        "SELECT to_jsonb(h) FROM provider_sync.source_entity_heads h"
    ))).all()
    with pytest.raises(FeatureIdentityAnchorError, match="회차"):
        async with migrated_session.begin_nested(), as_dagster_runtime(migrated_session):
            await feature_repo.load_bundle(migrated_session, b)
    assert await _snapshot(migrated_session, identity.feature_id) == before
    assert (await migrated_session.execute(text(
        "SELECT to_jsonb(h) FROM provider_sync.source_entity_heads h"
    ))).all() == source_before
    async with as_dagster_runtime(migrated_session):
        again = await feature_repo.load_bundle(migrated_session, a)
    assert again.features_updated == 0


async def test_reprojection_does_not_take_another_primary_sources_base(
    migrated_session: AsyncSession,
) -> None:
    from kortravelmap.dto import SourceLink
    from kortravelmap.providers.mcst import file_rows_to_bundles

    bundle = await _mcst_bundle()
    async with as_dagster_runtime(migrated_session):
        await feature_repo.load_bundle(migrated_session, bundle)
    identity = await feature_identity.resolve_feature_identity(
        migrated_session, bundle.feature.feature_id,
    )
    assert identity is not None
    [other] = await file_rows_to_bundles(
        [{"TITLE": "다른 primary 시설", "CATEGORY1": "음식점/유흥시설", "CATEGORY2": "카페",
          "ADDRESS": "서울특별시 종로구 세종대로 1"}],
        slug="barrier_free_places_csv", fetched_at=_FETCHED,
    )
    async with as_dagster_runtime(migrated_session):
        state = await feature_repo._upsert_source_record_state(
            migrated_session, other.source_record,
        )
        await feature_repo.upsert_source_link(
            migrated_session, SourceLink.model_validate(other.source_link),
            feature_id=identity.feature_id,
        )
        await feature_repo._apply_provider_field_values(
            migrated_session, feature_id=identity.feature_id,
            provider_dataset_id=state.provider_dataset_id,
            source_membership=feature_repo._ProviderSourceMembership(
                source_entity_key=state.source_entity_key,
                source_record_key=state.source_record_key,
            ),
            expected_row_revision=await _revision(migrated_session, identity.feature_id),
            values='{"core.category":"02020000","core.marker_icon":"cafe"}', geometry_wkt="{}",
        )
    before = await _snapshot(migrated_session, identity.feature_id)
    async with as_dagster_runtime(migrated_session):
        result = await feature_repo.load_bundle(migrated_session, bundle)
    assert result.features_updated == 0
    assert await _snapshot(migrated_session, identity.feature_id) == before


async def test_old_artifact_cannot_reproject_current_head(
    migrated_session: AsyncSession,
) -> None:
    old = await _mcst_bundle("이전 원문")
    old = old.model_copy(update={"feature": old.feature.model_copy(update={
        "category": "01040000", "marker_icon": "museum",
    })})
    current = await _mcst_bundle("현재 원문", _FETCHED + timedelta(days=1))
    async with as_dagster_runtime(migrated_session):
        await feature_repo.load_bundle(migrated_session, old)
        await feature_repo.load_bundle(migrated_session, current)
    identity = await feature_identity.resolve_feature_identity(
        migrated_session, current.feature.feature_id,
    )
    assert identity is not None
    before = await _snapshot(migrated_session, identity.feature_id)
    async with as_dagster_runtime(migrated_session):
        result = await feature_repo.load_bundle(migrated_session, old)
    assert result.features_updated == 0
    assert await _snapshot(migrated_session, identity.feature_id) == before


@pytest.mark.parametrize("statement", [
    "SELECT * FROM feature.feature_base_field_values WHERE false",
    "SELECT value_geometry FROM feature.feature_base_field_values WHERE false",
    "UPDATE feature.feature_base_field_values SET value_json='null'::jsonb WHERE false",
    "DELETE FROM feature.feature_base_field_values WHERE false",
])
async def test_projection_reader_cannot_read_other_columns_or_write_directly(
    migrated_session: AsyncSession, statement: str,
) -> None:
    with pytest.raises(DBAPIError) as caught:
        async with migrated_session.begin_nested(), as_dagster_runtime(migrated_session):
            await migrated_session.execute(text(statement))
    assert caught.value.orig.sqlstate == "42501"


async def test_projection_column_acl_reconcile_removes_drift_and_converges(
    dagster_runtime_engine: AsyncEngine,
) -> None:
    from kortravelmap.infra.db import make_async_engine
    from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges_in_transaction

    setup = make_async_engine(
        dagster_runtime_engine.url.render_as_string(hide_password=False), pool_size=1,
    )
    try:
        async with setup.begin() as connection:
            await connection.execute(text("SET ROLE ktm_feature_schema_owner"))
            await connection.execute(text("""
                GRANT SELECT (source_raw_payload_hash), UPDATE (value_json)
                ON feature.feature_base_field_values TO ktm_feature_runtime
            """))
        for _ in range(2):
            async with setup.begin() as connection:
                await reconcile_runtime_privileges_in_transaction(connection)
                row = (await connection.execute(text("""
                    SELECT
                      has_column_privilege('ktm_feature_runtime',
                        'feature.feature_base_field_values', 'value_json', 'SELECT') AS needed,
                      has_column_privilege('ktm_feature_runtime',
                        'feature.feature_base_field_values', 'source_raw_payload_hash', 'SELECT')
                        AS unwanted,
                      has_column_privilege('ktm_feature_runtime',
                        'feature.feature_base_field_values', 'value_json', 'UPDATE') AS mutation
                """))).one()
                assert tuple(row) == (True, False, False)
    finally:
        await setup.dispose()
