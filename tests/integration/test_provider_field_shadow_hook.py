"""실제 public client가 명시 scope에서만 shadow를 같은 TX에 기록한다."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.providers.mcst import MCST_FILE_DATASETS, MCST_PROVIDER_NAME, file_rows_to_bundles
from kortravelmap.settings import KorTravelMapSettings
from tests.unit.test_providers_mcst import _NOW, _world_restaurant_row

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(("enabled", "as_runtime"), [(False, False), (True, False), (True, True)])
async def test_native_replay_records_shadow_without_changing_effective_or_identity(
    migrated_engine: AsyncEngine, migrated_session: AsyncSession, enabled: bool, as_runtime: bool
) -> None:
    session = migrated_session
    bundle = (
        await file_rows_to_bundles(
            [_world_restaurant_row()], slug="world_restaurants_csv", fetched_at=_NOW
        )
    )[0]
    scope = (MCST_PROVIDER_NAME, MCST_FILE_DATASETS["world_restaurants_csv"].dataset_key)
    connection = await session.connection()
    # 외부 fixture TX를 각 public client 호출이 실제 savepoint로 사용한다. 운영의
    # 원본 session factory/commit 규약은 변경하지 않는다. 마지막 outer rollback으로 회수한다.
    client = AsyncKorTravelMapClient(migrated_engine)
    client._session_factory = async_sessionmaker(
        connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    first = await client.load_feature_bundles([bundle])
    assert first.features_inserted == 1
    before = (
        (
            await session.execute(
                text("""
        SELECT feature_id,name,row_revision FROM feature.features WHERE name=:name
    """),
                {"name": bundle.feature.name},
            )
        )
        .mappings()
        .one()
    )
    dataset_id = await session.scalar(
        text("""
        SELECT provider_dataset_id FROM provider_sync.provider_datasets
        WHERE provider=:provider AND dataset_key=:dataset
    """),
        {"provider": scope[0], "dataset": scope[1]},
    )
    await session.execute(
        text("""
        CALL feature.register_provider_field_shadow_policy(
            1,:id,'mcst-name-v1',CAST(:fields AS jsonb))
    """),
        {
            "id": dataset_id,
            "fields": json.dumps(
                [
                    {
                        "field_path": "core.name",
                        "provider_rank": 10,
                        "omitted_policy": "carry_forward",
                        "null_policy": "value",
                    }
                ]
            ),
        },
    )
    settings = KorTravelMapSettings(
        provider_field_shadow_policy_revision=1,
        provider_field_shadow_scopes=frozenset({scope})
        if enabled
        else frozenset({("other", "other")}),
        _env_file=None,
    )
    observed = AsyncKorTravelMapClient(migrated_engine, settings=settings)
    observed._session_factory = client._session_factory
    # 원문/Feature는 이미 있다. native skip/replay에서도 신규 shadow를 채워야 한다.
    if as_runtime:
        await session.execute(text("SET LOCAL ROLE ktm_feature_runtime"))
    second = await observed.load_feature_bundles([bundle])
    if as_runtime:
        await session.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
    assert (
        second.features_inserted == second.features_updated == second.source_records_inserted == 0
    )
    rows = (
        (
            await session.execute(
                text("""
        SELECT field_path,value_json,value_source_record_key,validated_source_record_key,
               availability,normalizer_revision FROM feature.provider_field_shadow_candidates
        WHERE provider_dataset_id=:dataset
    """),
                {"dataset": dataset_id},
            )
        )
        .mappings()
        .all()
    )
    if enabled:
        assert len(rows) == 1
        assert rows[0]["field_path"] == "core.name"
        assert rows[0]["value_json"] == bundle.feature.name
        assert rows[0]["availability"] == "value"
        assert rows[0]["normalizer_revision"] == "mcst-name-v1"
        assert rows[0]["value_source_record_key"] == rows[0]["validated_source_record_key"]
    else:
        assert rows == []
    after = (
        (
            await session.execute(
                text("""
        SELECT feature_id,name,row_revision FROM feature.features WHERE feature_id=:id
    """),
                {"id": before["feature_id"]},
            )
        )
        .mappings()
        .one()
    )
    assert after == before


async def test_missing_shadow_policy_rolls_back_native_insert_in_same_transaction(
    migrated_engine: AsyncEngine, migrated_session: AsyncSession
) -> None:
    session = migrated_session
    bundle = (
        await file_rows_to_bundles(
            [_world_restaurant_row()], slug="world_restaurants_csv", fetched_at=_NOW
        )
    )[0]
    scope = (MCST_PROVIDER_NAME, MCST_FILE_DATASETS["world_restaurants_csv"].dataset_key)
    observed = AsyncKorTravelMapClient(
        migrated_engine,
        settings=KorTravelMapSettings(
            provider_field_shadow_policy_revision=1,
            provider_field_shadow_scopes={scope},
            _env_file=None,
        ),
    )
    observed._session_factory = async_sessionmaker(
        await session.connection(),
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    with pytest.raises(DBAPIError, match="shadow policy is not explicitly configured"):
        await observed.load_feature_bundles([bundle])
    # shadow 실패를 삼켜 native 성공만 남기지 않는다. 한 TX의 원문/Feature도 전부 되감긴다.
    assert (
        await session.scalar(
            text("""
        SELECT count(*) FROM feature.features WHERE name=:name
    """),
            {"name": bundle.feature.name},
        )
        == 0
    )
    assert (
        await session.scalar(
            text("""
        SELECT count(*) FROM provider_sync.source_records WHERE source_record_key=:key
    """),
            {"key": bundle.source_record.source_record_key},
        )
        == 0
    )
