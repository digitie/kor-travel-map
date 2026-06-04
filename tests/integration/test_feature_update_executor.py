"""ADR-045 T-206d feature update request 실행 본체 통합 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.infra import feature_repo
from krtour.map.infra.advisory_lock import try_advisory_lock
from krtour.map.infra.feature_update_executor import (
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
    execute_next_feature_update_request,
)
from krtour.map.infra.feature_update_repo import (
    FeatureUpdateRequest,
    enqueue_feature_update_request,
    feature_update_scope_advisory_key,
    get_update_request,
)
from krtour.map.infra.poi_cache_target_repo import (
    get_poi_cache_target_by_key,
    list_poi_cache_target_feature_links,
    upsert_poi_cache_target,
)
from krtour.map.infra.provider_refresh_policy_repo import (
    upsert_provider_refresh_policy,
)
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Festival:
    management_no: str
    festival_name: str
    venue_name: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    road_address: str | None
    jibun_address: str | None
    organizer_name: str | None
    organizer_tel: str | None
    data_reference_date: date | None
    provider_org_name: str | None
    bjd_code: str | None = None
    sigungu_code: str | None = None
    sido_code: str | None = None
    admin_address: str | None = None


async def _bundle(
    management_no: str,
    *,
    lon: str = "126.9780",
    lat: str = "37.5665",
    bjd_code: str = "1114010100",
    sigungu_code: str = "11140",
):
    item = _Festival(
        management_no=management_no,
        festival_name=f"executor 테스트 축제 {management_no}",
        venue_name="테스트 광장",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 7),
        description="feature update executor 테스트용 fixture.",
        latitude=Decimal(lat),
        longitude=Decimal(lon),
        road_address="서울특별시 중구 세종대로 110",
        jibun_address="서울특별시 중구 태평로1가 31",
        organizer_name="중구청",
        organizer_tel="02-3396-4114",
        data_reference_date=date(2026, 6, 1),
        provider_org_name="서울특별시 중구",
        bjd_code=bjd_code,
        sigungu_code=sigungu_code,
        sido_code=bjd_code[:2],
    )
    return (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=_FETCHED,
        )
    )[0]


async def _load_seed(session: AsyncSession, management_no: str):
    bundle = await _bundle(management_no)
    await feature_repo.load_bundle(session, bundle)
    await session.execute(
        text(
            """
            UPDATE feature.features
            SET sigungu_code = :sigungu_code,
                sido_code = :sido_code,
                legal_dong_code = :bjd_code
            WHERE feature_id = :feature_id
            """
        ),
        {
            "feature_id": bundle.feature.feature_id,
            "sigungu_code": "11140",
            "sido_code": "11",
            "bjd_code": "1114010100",
        },
    )
    await session.flush()
    return bundle


async def _job_state(session: AsyncSession, job_id: str) -> dict[str, object]:
    row = (
        await session.execute(
            text(
                """
                SELECT state, progress, current_stage, error_message
                FROM ops.import_jobs
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id},
        )
    ).mappings().one()
    return dict(row)


async def test_execute_next_request_runs_provider_and_syncs_target_links(
    migrated_engine: AsyncEngine,
    migrated_session: AsyncSession,
) -> None:
    seed = await _load_seed(migrated_session, "EXEC-SEED")
    await upsert_provider_refresh_policy(
        migrated_session,
        provider=seed.source_record.provider,
        dataset_key=seed.source_record.dataset_key,
        source_kind="openapi",
        targeted_policy="allow_targeted",
        max_requests_per_minute=60,
    )
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="tripmate",
        target_key="poi-exec",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "cache_target_keys",
            "external_system": "tripmate",
            "target_keys": ["poi-exec"],
        },
        priority=90,
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=request.scope_type,
        scope=request.scope,
        providers=request.providers,
        dataset_keys=request.dataset_keys,
    )
    competing_lock_results: list[bool] = []

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        assert scope.provider == seed.source_record.provider
        assert scope.dataset_key == seed.source_record.dataset_key
        assert scope.target_ids == (target.target_id,)
        from sqlalchemy.ext.asyncio import AsyncSession

        async with (
            AsyncSession(migrated_engine, expire_on_commit=False) as competitor,
            competitor.begin(),
            try_advisory_lock(competitor, scope_lock_key) as acquired,
        ):
            competing_lock_results.append(acquired)
        loaded = await _bundle("EXEC-LOADED")
        await feature_repo.load_bundle(session, loaded)
        return ProviderDatasetRefreshResult(
            provider=scope.provider,
            dataset_key=scope.dataset_key,
            loaded_feature_ids=(loaded.feature.feature_id,),
            loaded_count=1,
            metadata={"runner": "integration"},
        )

    result = await execute_next_feature_update_request(
        migrated_session, runner=runner, dagster_run_id="dagster-run-1"
    )

    assert result is not None
    assert result.state == "done"
    assert result.request.state == "done"
    assert result.request.dagster_run_id == "dagster-run-1"
    assert result.results[0].loaded_count == 1
    assert competing_lock_results == [False]
    assert result.plan.matched_scope["executed_provider_scopes"][0][
        "loaded_count"
    ] == 1

    stored = await get_update_request(migrated_session, request.request_id)
    assert stored is not None
    assert stored.state == "done"
    assert stored.matched_scope["target_count"] == 1
    assert stored.matched_scope["eligible_provider_scopes"][0][
        "provider"
    ] == seed.source_record.provider
    assert (await _job_state(migrated_session, request.job_id))["progress"] == 100

    refreshed_target = await get_poi_cache_target_by_key(
        migrated_session,
        external_system="tripmate",
        target_key="poi-exec",
    )
    assert refreshed_target is not None
    assert refreshed_target.last_requested_at is not None
    assert refreshed_target.last_refreshed_at is not None
    links = await list_poi_cache_target_feature_links(
        migrated_session, target.target_id
    )
    assert {
        seed.feature.feature_id,
        result.results[0].loaded_feature_ids[0],
    } <= {link.feature_id for link in links}


async def test_execute_next_request_applies_follow_system_policy_skip(
    migrated_session: AsyncSession,
) -> None:
    seed = await _load_seed(migrated_session, "EXEC-SKIP")
    await upsert_provider_refresh_policy(
        migrated_session,
        provider=seed.source_record.provider,
        dataset_key=seed.source_record.dataset_key,
        source_kind="openapi",
        targeted_policy="follow_system",
    )
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="tripmate",
        target_key="poi-skip",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "cache_target_keys",
            "external_system": "tripmate",
            "target_keys": ["poi-skip"],
        },
    )
    assert isinstance(request, FeatureUpdateRequest)

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        raise AssertionError("follow_system policy must skip targeted runner")

    result = await execute_next_feature_update_request(
        migrated_session, runner=runner
    )

    assert result is not None
    assert result.state == "done"
    assert result.results == ()
    assert result.plan.skipped_scopes[0].reason == "follow_system_skipped"

    stored = await get_update_request(migrated_session, request.request_id)
    assert stored is not None
    assert stored.matched_scope["skipped_provider_scopes"][0][
        "reason"
    ] == "follow_system_skipped"
    refreshed_target = await get_poi_cache_target_by_key(
        migrated_session,
        external_system="tripmate",
        target_key="poi-skip",
    )
    assert refreshed_target is not None
    assert refreshed_target.last_requested_at is not None
    assert refreshed_target.last_refreshed_at is None
    assert (
        await list_poi_cache_target_feature_links(
            migrated_session, target.target_id
        )
    )[0].feature_id == seed.feature.feature_id
