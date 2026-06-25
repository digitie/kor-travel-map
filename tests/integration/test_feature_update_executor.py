"""ADR-045 T-206d feature update request 실행 본체 통합 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo
from kortravelmap.infra.advisory_lock import try_advisory_lock
from kortravelmap.infra.feature_update_executor import (
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
    execute_next_feature_update_request,
)
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    enqueue_feature_update_request,
    feature_update_scope_advisory_key,
    get_update_request,
)
from kortravelmap.infra.poi_cache_target_repo import (
    get_poi_cache_target_by_key,
    list_poi_cache_target_feature_links,
    upsert_poi_cache_target,
)
from kortravelmap.infra.provider_refresh_policy_repo import (
    upsert_provider_refresh_policy,
)
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 — provider 실모델 필드명 (#374)."""

    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


async def _bundle(
    seed: str,
    *,
    lon: str = "126.9780",
    lat: str = "37.5665",
):
    # 자연키는 name::address 파생(#374) — seed를 이름에 넣어 feature 구분.
    item = _Festival(
        fstvl_nm=f"executor 테스트 축제 {seed}",
        opar="테스트 광장",
        fstvl_start_date=date(2026, 6, 1),
        fstvl_end_date=date(2026, 6, 7),
        fstvl_co="feature update executor 테스트용 fixture.",
        mnnst_nm="중구청",
        phone_number="02-3396-4114",
        rdnmadr="서울특별시 중구 세종대로 110",
        lnmadr="서울특별시 중구 태평로1가 31",
        latitude=float(lat),
        longitude=float(lon),
        reference_date=date(2026, 6, 1),
        instt_nm="서울특별시 중구",
    )
    return (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=_FETCHED,
        )
    )[0]


async def _load_seed(session: AsyncSession, seed: str):
    bundle = await _bundle(seed)
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


async def _job_status(session: AsyncSession, job_id: str) -> dict[str, object]:
    row = (
        await session.execute(
            text(
                """
                SELECT status, progress, current_stage, error_message
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
        external_system="pinvi",
        target_key="poi-exec",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "cache_target_keys",
            "external_system": "pinvi",
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
    assert result.status == "done"
    assert result.request.status == "done"
    assert result.request.dagster_run_id == "dagster-run-1"
    assert result.results[0].loaded_count == 1
    assert competing_lock_results == [False]
    assert result.plan.matched_scope["executed_provider_scopes"][0][
        "loaded_count"
    ] == 1

    stored = await get_update_request(migrated_session, request.request_id)
    assert stored is not None
    assert stored.status == "done"
    assert stored.matched_scope["target_count"] == 1
    assert stored.matched_scope["eligible_provider_scopes"][0][
        "provider"
    ] == seed.source_record.provider
    assert (await _job_status(migrated_session, request.job_id))["progress"] == 100

    refreshed_target = await get_poi_cache_target_by_key(
        migrated_session,
        external_system="pinvi",
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
        external_system="pinvi",
        target_key="poi-skip",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "cache_target_keys",
            "external_system": "pinvi",
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
    assert result.status == "done"
    assert result.results == ()
    assert result.plan.skipped_scopes[0].reason == "follow_system_skipped"

    stored = await get_update_request(migrated_session, request.request_id)
    assert stored is not None
    assert stored.matched_scope["skipped_provider_scopes"][0][
        "reason"
    ] == "follow_system_skipped"
    refreshed_target = await get_poi_cache_target_by_key(
        migrated_session,
        external_system="pinvi",
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


async def test_failed_runner_rolls_back_refresh_writes(
    migrated_session: AsyncSession,
) -> None:
    seed = await _load_seed(migrated_session, "EXEC-ROLLBACK-SEED")
    await upsert_provider_refresh_policy(
        migrated_session,
        provider=seed.source_record.provider,
        dataset_key=seed.source_record.dataset_key,
        source_kind="openapi",
        targeted_policy="allow_targeted",
    )
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="pinvi",
        target_key="poi-rollback",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    request = await enqueue_feature_update_request(
        migrated_session,
        scope={
            "type": "cache_target_keys",
            "external_system": "pinvi",
            "target_keys": ["poi-rollback"],
        },
    )
    assert isinstance(request, FeatureUpdateRequest)
    loaded_feature_id: str | None = None

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        nonlocal loaded_feature_id
        assert scope.target_ids == (target.target_id,)
        loaded = await _bundle("EXEC-ROLLBACK-LOADED")
        loaded_feature_id = loaded.feature.feature_id
        await feature_repo.load_bundle(session, loaded)
        raise RuntimeError("provider refresh failed after partial write")

    result = await execute_next_feature_update_request(
        migrated_session, runner=runner
    )

    assert result is not None
    assert result.status == "failed"
    assert result.results == ()
    assert result.error_message is not None
    assert "RuntimeError" in result.error_message
    assert loaded_feature_id is not None
    persisted = (
        await migrated_session.execute(
            text("SELECT 1 FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": loaded_feature_id},
        )
    ).first()
    assert persisted is None

    stored = await get_update_request(migrated_session, request.request_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_message is not None
    assert "RuntimeError" in stored.error_message

    failed_target = await get_poi_cache_target_by_key(
        migrated_session,
        external_system="pinvi",
        target_key="poi-rollback",
    )
    assert failed_target is not None
    assert failed_target.last_failed_at is not None
    assert failed_target.last_refreshed_at is None
