"""ADR-045 T-206d feature update request 실행 본체 통합 테스트."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from kortravelmap.api import ops_dataset_service as dataset_service
from kortravelmap.api.app import create_app
from kortravelmap.api.auth import ADMIN_ACTOR_HEADER, ADMIN_PROXY_SECRET_HEADER
from kortravelmap.api.db import get_session
from kortravelmap.api.ops_dataset_schedule import DatasetScheduleIndex
from kortravelmap.api.settings import ApiSettings
from kortravelmap.dagster import feature_update_runner as dagster_runner_mod
from kortravelmap.dagster import kma_weather as kma_weather_mod
from kortravelmap.dagster.assets import run_feature_event_datagokr_cultural_festivals
from kortravelmap.dagster.feature_update_runner import (
    FeatureUpdateAssetRunner,
    FeatureUpdateRunnerSpec,
    RunnerResources,
    _bind_client_to_session,
)
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.infra import feature_repo
from kortravelmap.infra import feature_update_executor as executor_mod
from kortravelmap.infra.advisory_lock import advisory_lock_key, try_advisory_lock
from kortravelmap.infra.feature_update_executor import (
    FeatureUpdateConnectionUnsafe,
    FeatureUpdateExecutionPlan,
    FeatureUpdateLockReleaseError,
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
)
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    enqueue_feature_update_request,
    feature_update_scope_advisory_key,
    get_update_request,
)
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.pipeline_cancellation_repo import (
    cancel_queued_pipeline_cancellation_member,
    create_pipeline_cancellation_attempt,
    finish_pipeline_cancellation_attempt,
    resolve_pipeline_cancellation_scope,
)
from kortravelmap.infra.poi_cache_target_repo import (
    get_poi_cache_target_by_key,
    list_poi_cache_target_feature_links,
    upsert_poi_cache_target,
)
from kortravelmap.infra.provider_refresh_policy_repo import (
    upsert_provider_refresh_policy,
)
from kortravelmap.infra.scope_repo import ScopeResolution
from kortravelmap.providers.kma import (
    KMA_PROVIDER_NAME,
    KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
)
from kortravelmap.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    STANDARD_DATA_PROVIDER_NAME,
    cultural_festivals_to_bundles,
)
from kortravelmap.settings import KorTravelMapSettings
from tests.integration._db_cleanup import truncate_committed_test_rows

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)
# runner spec registry가 이 operation_key로 KMA grid handler를 dispatch한다.
KMA_ULTRA_SHORT_NOWCAST_OPERATION_KEY = "feature_weather_kma_ultra_short_nowcast_job"
_TRUNCATE_SQL = """
TRUNCATE
    feature.features,
    provider_sync.source_records,
    provider_sync.source_links,
    provider_sync.provider_sync_state,
    ops.poi_cache_target_feature_links,
    ops.poi_cache_targets,
    ops.provider_refresh_policies,
    ops.pipeline_cancellation_members,
    ops.pipeline_cancellation_runs,
    ops.feature_update_requests,
    ops.import_job_events,
    ops.import_jobs,
    ops.pipeline_cancellations
RESTART IDENTITY CASCADE
"""

_LOOKUP_MEMBERSHIP_SQL = """
SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
JOIN provider_sync.provider_dataset_operations AS operation
  ON operation.provider_dataset_id = scope.provider_dataset_id
 AND operation.operation_key = scope.operation_key
 AND operation.operation_kind = scope.operation_kind
WHERE dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND scope.sync_scope = :sync_scope
  AND scope.operation_kind = 'refresh'
  AND dataset.is_active
  AND operation.is_enabled
ORDER BY scope.operation_key
LIMIT 1
"""

_UPSERT_DATASET_SQL = """
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind, is_active, capabilities
)
SELECT :provider, :dataset_key, :provider, 'system', true,
       jsonb_build_object('schema_version', 1,
                          'produces', '[]'::jsonb,
                          'extensions', '{}'::jsonb)
ON CONFLICT (provider, dataset_key) DO UPDATE
    SET display_name = EXCLUDED.display_name
RETURNING provider_dataset_id
"""

_UPSERT_OPERATION_SQL = """
INSERT INTO provider_sync.provider_dataset_operations (
    provider_dataset_id, operation_key, operation_kind, is_enabled, config
) VALUES (:provider_dataset_id, :operation_key, 'refresh', true, '{}'::jsonb)
ON CONFLICT (provider_dataset_id, operation_key, operation_kind) DO NOTHING
"""

_UPSERT_OPERATION_SCOPE_SQL = """
INSERT INTO provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id, sync_scope, operation_key, operation_kind
) VALUES (:provider_dataset_id, :sync_scope, :operation_key, 'refresh')
ON CONFLICT (provider_dataset_id, sync_scope, operation_key) DO NOTHING
"""


async def _membership(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str = "dataset_wide",
    operation_key: str = "feature_update",
) -> ImportJobDatasetTarget:
    """canonical refresh membership triple을 얻는다 (없으면 fixture로 심는다).

    T-VN-33 이후 request/job/sync-state identity는 자연키 pair가 아니라
    ``provider_dataset_id + sync_scope + operation_key``다. 0089가 seed한 실제
    dataset은 catalog 값을 그대로 읽고, 테스트 전용 pair만 새로 심는다.
    """
    row = (
        await session.execute(
            text(_LOOKUP_MEMBERSHIP_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
            },
        )
    ).one_or_none()
    if row is not None:
        return ImportJobDatasetTarget(
            provider_dataset_id=int(row.provider_dataset_id),
            sync_scope=str(row.sync_scope),
            operation_key=str(row.operation_key),
        )
    provider_dataset_id = int(
        (
            await session.execute(
                text(_UPSERT_DATASET_SQL),
                {"provider": provider, "dataset_key": dataset_key},
            )
        ).scalar_one()
    )
    params = {
        "provider_dataset_id": provider_dataset_id,
        "operation_key": operation_key,
        "sync_scope": sync_scope,
    }
    await session.execute(text(_UPSERT_OPERATION_SQL), params)
    await session.execute(text(_UPSERT_OPERATION_SCOPE_SQL), params)
    return ImportJobDatasetTarget(
        provider_dataset_id=provider_dataset_id,
        sync_scope=sync_scope,
        operation_key=operation_key,
    )


def _provider_dataset_scope(membership: ImportJobDatasetTarget) -> dict[str, Any]:
    """canonical membership을 그대로 든 ``provider_dataset`` request scope."""
    return {
        "type": "provider_dataset",
        "provider_dataset_id": membership.provider_dataset_id,
        "sync_scope": membership.sync_scope,
        "operation_key": membership.operation_key,
    }


@pytest.fixture(autouse=True)
async def _cleanup_committed_execution_rows(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[None]:
    """phase commit 테스트가 남긴 행을 테스트마다 제거한다."""
    yield
    async with AsyncSession(migrated_engine) as session, session.begin():
        await truncate_committed_test_rows(session, _TRUNCATE_SQL)


@pytest.fixture
async def execution_session(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    """Phase commit을 허용하고 module cleanup으로 격리하는 검증 session."""
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        try:
            yield session
        finally:
            await session.rollback()


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


def _festival(
    seed: str,
    *,
    lon: str = "126.9780",
    lat: str = "37.5665",
) -> _Festival:
    # 자연키는 name::address 파생(#374) — seed를 이름에 넣어 feature 구분.
    return _Festival(
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


async def _bundle(
    seed: str,
    *,
    lon: str = "126.9780",
    lat: str = "37.5665",
):
    item = _festival(seed, lon=lon, lat=lat)
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
                SELECT
                    status,
                    payload,
                    progress,
                    current_stage,
                    dagster_run_id,
                    error_message,
                    started_at,
                    finished_at,
                    heartbeat_at
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
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await _load_seed(execution_session, "EXEC-SEED")
    membership = await _membership(
        execution_session,
        provider=seed.source_record.provider,
        dataset_key=seed.source_record.dataset_key,
    )
    await upsert_provider_refresh_policy(
        execution_session,
        provider_dataset_id=membership.provider_dataset_id,
        source_kind="openapi",
        expected_revision=None,
        targeted_policy="allow_targeted",
        max_requests_per_minute=60,
    )
    target = await upsert_poi_cache_target(
        execution_session,
        external_system="external-app",
        target_key="poi-exec",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope={
            "type": "cache_target_keys",
            "external_system": "external-app",
            "target_keys": ["poi-exec"],
        },
        priority=90,
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=request.scope_type,
        scope=request.scope,
        dataset_memberships=request.dataset_memberships,
    )
    competing_lock_results: list[bool] = []
    phase_pids: list[int] = []
    original_acquire = executor_mod._acquire_scope_lock
    original_guard = executor_mod._guard_execution_phase
    original_release = executor_mod._release_scope_lock

    async def record_acquire(
        session: AsyncSession,
        connection: AsyncConnection,
        *,
        lock_id: int,
    ) -> bool:
        acquired = await original_acquire(
            session,
            connection,
            lock_id=lock_id,
        )
        assert session.in_transaction() is False
        phase_pids.append(
            int((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        )
        await session.commit()
        return acquired

    async def record_guard(
        session: AsyncSession,
        request_id: str,
        *,
        expected_generation: int,
        owner_dagster_run_id: str,
    ) -> FeatureUpdateRequest:
        assert session.in_transaction()
        assert expected_generation == request.generation
        assert owner_dagster_run_id == "dagster-run-1"
        phase_pids.append(
            int((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        )
        return await original_guard(
            session,
            request_id,
            expected_generation=expected_generation,
            owner_dagster_run_id=owner_dagster_run_id,
        )

    async def record_release(
        session: AsyncSession,
        connection: AsyncConnection,
        *,
        lock_id: int,
    ) -> None:
        assert session.in_transaction() is False
        phase_pids.append(
            int((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        )
        await session.commit()
        await original_release(session, connection, lock_id=lock_id)
        assert session.in_transaction() is False

    monkeypatch.setattr(executor_mod, "_acquire_scope_lock", record_acquire)
    monkeypatch.setattr(executor_mod, "_guard_execution_phase", record_guard)
    monkeypatch.setattr(executor_mod, "_release_scope_lock", record_release)

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        phase_pids.append(
            int((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        )
        assert scope.provider == seed.source_record.provider
        assert scope.dataset_key == seed.source_record.dataset_key
        assert scope.target_ids == (target.target_id,)

        async with (
            AsyncSession(migrated_engine, expire_on_commit=False) as competitor,
            competitor.begin(),
            try_advisory_lock(competitor, scope_lock_key) as acquired,
        ):
            competing_lock_results.append(acquired)
        loaded = await _bundle("EXEC-LOADED")
        await feature_repo.load_bundle(session, loaded)
        return ProviderDatasetRefreshResult(
            provider_dataset_id=scope.provider_dataset_id,
            sync_scope=scope.sync_scope,
            operation_key=scope.operation_key,
            provider=scope.provider,
            dataset_key=scope.dataset_key,
            loaded_feature_ids=(loaded.feature.feature_id,),
            loaded_count=1,
            metadata={"runner": "integration"},
        )

    await execution_session.commit()
    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_next_feature_update_request(
        runner=runner,
        dagster_run_id="dagster-run-1",
    )

    assert result is not None
    assert result.status == "done"
    assert result.request.status == "done"
    assert result.request.dagster_run_id == "dagster-run-1"
    assert result.results[0].loaded_count == 1
    assert competing_lock_results == [False]
    assert len(set(phase_pids)) == 1
    assert result.plan.matched_scope["executed_provider_scopes"][0][
        "loaded_count"
    ] == 1

    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "done"
    assert stored.matched_scope["target_count"] == 1
    assert stored.matched_scope["eligible_provider_scopes"][0][
        "provider"
    ] == seed.source_record.provider
    assert (await _job_status(execution_session, request.job_id))["progress"] == 100

    refreshed_target = await get_poi_cache_target_by_key(
        execution_session,
        external_system="external-app",
        target_key="poi-exec",
    )
    assert refreshed_target is not None
    assert refreshed_target.last_requested_at is not None
    assert refreshed_target.last_refreshed_at is not None
    links = await list_poi_cache_target_feature_links(
        execution_session, target.target_id
    )
    assert {
        seed.feature.feature_id,
        result.results[0].loaded_feature_ids[0],
    } <= {link.feature_id for link in links}


async def test_execute_next_request_applies_follow_system_policy_skip(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
) -> None:
    seed = await _load_seed(execution_session, "EXEC-SKIP")
    membership = await _membership(
        execution_session,
        provider=seed.source_record.provider,
        dataset_key=seed.source_record.dataset_key,
    )
    await upsert_provider_refresh_policy(
        execution_session,
        provider_dataset_id=membership.provider_dataset_id,
        source_kind="openapi",
        expected_revision=None,
        targeted_policy="follow_system",
    )
    target = await upsert_poi_cache_target(
        execution_session,
        external_system="external-app",
        target_key="poi-skip",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope={
            "type": "cache_target_keys",
            "external_system": "external-app",
            "target_keys": ["poi-skip"],
        },
    )
    assert isinstance(request, FeatureUpdateRequest)

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        raise AssertionError("follow_system policy must skip targeted runner")

    await execution_session.commit()
    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_next_feature_update_request(
        runner=runner,
        dagster_run_id="dagster-follow-system-skip",
    )

    assert result is not None
    assert result.status == "done"
    assert result.results == ()
    assert result.plan.skipped_scopes[0].reason == "follow_system_skipped"

    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.matched_scope["skipped_provider_scopes"][0][
        "reason"
    ] == "follow_system_skipped"
    refreshed_target = await get_poi_cache_target_by_key(
        execution_session,
        external_system="external-app",
        target_key="poi-skip",
    )
    assert refreshed_target is not None
    assert refreshed_target.last_requested_at is not None
    assert refreshed_target.last_refreshed_at is None
    assert (
        await list_poi_cache_target_feature_links(
            execution_session, target.target_id
        )
    )[0].feature_id == seed.feature.feature_id


async def test_runner_level_skip_does_not_mark_cache_target_refreshed(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
) -> None:
    seed = await _load_seed(execution_session, "EXEC-RUNNER-SKIP")
    membership = await _membership(
        execution_session,
        provider=seed.source_record.provider,
        dataset_key=seed.source_record.dataset_key,
    )
    await upsert_provider_refresh_policy(
        execution_session,
        provider_dataset_id=membership.provider_dataset_id,
        source_kind="openapi",
        expected_revision=None,
        targeted_policy="allow_targeted",
    )
    target = await upsert_poi_cache_target(
        execution_session,
        external_system="external-app",
        target_key="poi-runner-skip",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope={
            "type": "cache_target_keys",
            "external_system": "external-app",
            "target_keys": ["poi-runner-skip"],
        },
    )
    assert isinstance(request, FeatureUpdateRequest)

    async def runner(
        _session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        return ProviderDatasetRefreshResult(
            provider_dataset_id=scope.provider_dataset_id,
            sync_scope=scope.sync_scope,
            operation_key=scope.operation_key,
            provider=scope.provider,
            dataset_key=scope.dataset_key,
            status="skipped",
            metadata={"skip_reason": "global_provider_not_targetable"},
        )

    await execution_session.commit()
    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_next_feature_update_request(
        runner=runner,
        dagster_run_id="dagster-runner-skip",
    )

    assert result is not None
    assert result.status == "done"
    assert result.results[0].status == "skipped"
    refreshed_target = await get_poi_cache_target_by_key(
        execution_session,
        external_system="external-app",
        target_key="poi-runner-skip",
    )
    assert refreshed_target is not None
    assert refreshed_target.last_requested_at is not None
    assert refreshed_target.last_refreshed_at is None
    assert (
        await list_poi_cache_target_feature_links(
            execution_session,
            target.target_id,
        )
    )[0].feature_id == seed.feature.feature_id


async def test_failed_runner_rolls_back_refresh_writes(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
) -> None:
    seed = await _load_seed(execution_session, "EXEC-ROLLBACK-SEED")
    membership = await _membership(
        execution_session,
        provider=seed.source_record.provider,
        dataset_key=seed.source_record.dataset_key,
    )
    await upsert_provider_refresh_policy(
        execution_session,
        provider_dataset_id=membership.provider_dataset_id,
        source_kind="openapi",
        expected_revision=None,
        targeted_policy="allow_targeted",
    )
    target = await upsert_poi_cache_target(
        execution_session,
        external_system="external-app",
        target_key="poi-rollback",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope={
            "type": "cache_target_keys",
            "external_system": "external-app",
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

    await execution_session.commit()
    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_next_feature_update_request(
        runner=runner,
        dagster_run_id="dagster-provider-failure",
    )

    assert result is not None
    assert result.status == "failed"
    assert result.results == ()
    assert result.error_message is not None
    assert "RuntimeError" in result.error_message
    assert loaded_feature_id is not None
    persisted = (
        await execution_session.execute(
            text("SELECT 1 FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": loaded_feature_id},
        )
    ).first()
    assert persisted is None

    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_message is not None
    assert "RuntimeError" in stored.error_message

    failed_target = await get_poi_cache_target_by_key(
        execution_session,
        external_system="external-app",
        target_key="poi-rollback",
    )
    assert failed_target is not None
    assert failed_target.last_failed_at is not None
    assert failed_target.last_refreshed_at is None
    typed_kma_event_count = await execution_session.scalar(
        text(
            """
            SELECT count(*)
            FROM ops.import_job_events
            WHERE job_id = CAST(:job_id AS uuid)
              AND code = 'kma.target_scope_empty'
            """
        ),
        {"job_id": request.job_id},
    )
    assert typed_kma_event_count == 0


async def test_production_asset_runner_rolls_back_load_when_checkpoint_fails(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _festival("PRODUCTION-RUNNER-CHECKPOINT")
    expected_bundle = (
        await cultural_festivals_to_bundles(
            [record],  # type: ignore[list-item]
            fetched_at=_FETCHED,
        )
    )[0]
    membership = await _membership(
        execution_session,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    await execution_session.commit()

    def resources(
        _settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> RunnerResources:
        return RunnerResources({"datagokr_cultural_festivals": [record]})

    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": AsyncKorTravelMapClient(migrated_engine),
            "reverse_geocoder": None,
            "fetched_at": _FETCHED,
            "strict_address": "off",
        },
        log=logging.getLogger(__name__),
        settings_factory=KorTravelMapSettings.model_construct,
        specs=(
            FeatureUpdateRunnerSpec(
                operation_key=membership.operation_key,
                run=run_feature_event_datagokr_cultural_festivals,
                resources=resources,
                asset_key="feature_event_datagokr_cultural_festivals",
            ),
        ),
    )
    original_set_checkpoint = executor_mod.set_update_request_matched_scope
    checkpoint_writes = 0

    async def fail_provider_checkpoint(
        session: AsyncSession,
        request_id: str,
        *,
        matched_scope: Mapping[str, Any],
        expected_generation: int,
        owner_dagster_run_id: str,
    ) -> FeatureUpdateRequest | None:
        nonlocal checkpoint_writes
        checkpoint_writes += 1
        if checkpoint_writes == 2:
            raise RuntimeError("simulated provider checkpoint failure")
        return await original_set_checkpoint(
            session,
            request_id,
            matched_scope=matched_scope,
            expected_generation=expected_generation,
            owner_dagster_run_id=owner_dagster_run_id,
        )

    monkeypatch.setattr(
        executor_mod,
        "set_update_request_matched_scope",
        fail_provider_checkpoint,
    )
    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-checkpoint-failure",
    )

    assert result is not None
    assert result.status == "failed"
    assert result.error_message == "RuntimeError: simulated provider checkpoint failure"
    assert checkpoint_writes == 2
    persisted = (
        await execution_session.execute(
            text("SELECT 1 FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": expected_bundle.feature.feature_id},
        )
    ).first()
    assert persisted is None
    sync_state = (
        await execution_session.execute(
            text(
                "SELECT 1 FROM provider_sync.provider_sync_state "
                "WHERE provider_dataset_id = :provider_dataset_id "
                "AND sync_scope = :sync_scope AND operation_key = :operation_key"
            ),
            {
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
            },
        )
    ).first()
    assert sync_state is None
    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.matched_scope.get("executed_provider_scopes", []) == []


async def test_bound_kma_failure_records_sync_failure_once_after_rollback(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_scope = "external_system:external-app"
    await upsert_poi_cache_target(
        execution_session,
        external_system="external-app",
        target_key="bound-kma-failure",
        lon=126.978,
        lat=37.5665,
        radius_km=1.0,
    )
    membership = await _membership(
        execution_session,
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
        sync_scope=sync_scope,
        operation_key=KMA_ULTRA_SHORT_NOWCAST_OPERATION_KEY,
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    await execution_session.commit()

    class _FailingForecast:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        def now(self, *, nx: int, ny: int) -> object:
            self.calls.append((nx, ny))
            raise RuntimeError("bound KMA provider failure")

    forecast = _FailingForecast()
    monkeypatch.setattr(
        dagster_runner_mod,
        "_kma_weather_resources",
        lambda _settings, _scope: RunnerResources(
            {
                "kma_weather_client_factory": lambda: SimpleNamespace(
                    forecast=forecast
                )
            }
        ),
    )
    monkeypatch.setattr(
        kma_weather_mod,
        "_kma_grid",
        lambda lat, lon: (int(lon), int(lat)),
    )
    monkeypatch.setattr(
        kma_weather_mod,
        "_latest_nowcast_base",
        lambda: ("20260611", "0500"),
    )
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": AsyncKorTravelMapClient(migrated_engine),
            "reverse_geocoder": None,
            "fetched_at": _FETCHED,
            "strict_address": "off",
        },
        log=logging.getLogger(__name__),
        settings_factory=KorTravelMapSettings.model_construct,
    )

    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-bound-kma-failure",
    )

    assert result is not None
    assert result.status == "failed"
    assert result.error_message is not None
    assert "ProviderDatasetRefreshFailure" in result.error_message
    assert forecast.calls == [(126, 37)]
    sync_state = (
        await execution_session.execute(
            text(
                """
                SELECT cursor, consecutive_failures, last_failure_at, last_success_at
                FROM provider_sync.provider_sync_state
                WHERE provider_dataset_id = :provider_dataset_id
                  AND sync_scope = :sync_scope
                  AND operation_key = :operation_key
                """
            ),
            {
                "provider_dataset_id": membership.provider_dataset_id,
                "sync_scope": membership.sync_scope,
                "operation_key": membership.operation_key,
            },
        )
    ).mappings().one()
    assert sync_state["cursor"] == {}
    assert sync_state["consecutive_failures"] == 1
    assert sync_state["last_failure_at"] is not None
    assert sync_state["last_success_at"] is None
    empty_scope_event_count = await execution_session.scalar(
        text(
            """
            SELECT count(*)
            FROM ops.import_job_events
            WHERE job_id = CAST(:job_id AS uuid)
              AND code = 'kma.target_scope_empty'
            """
        ),
        {"job_id": request.job_id},
    )
    assert empty_scope_event_count == 0


async def test_bound_kma_empty_target_fails_operation_without_provider_or_state_write(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    membership = await _membership(
        execution_session,
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
        sync_scope="target_grids",
        operation_key=KMA_ULTRA_SHORT_NOWCAST_OPERATION_KEY,
    )
    state_params = {
        "provider_dataset_id": membership.provider_dataset_id,
        "sync_scope": membership.sync_scope,
        "operation_key": membership.operation_key,
    }
    await execution_session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_sync_state (
                provider_dataset_id,
                sync_scope,
                operation_key,
                status,
                cursor,
                last_success_at,
                last_failure_at,
                consecutive_failures,
                next_run_after,
                updated_at
            ) VALUES (
                :provider_dataset_id,
                :sync_scope,
                :operation_key,
                'paused',
                '{"sentinel":"must-remain-unchanged"}'::jsonb,
                TIMESTAMPTZ '2026-05-01 01:02:03+00',
                TIMESTAMPTZ '2026-05-02 04:05:06+00',
                7,
                TIMESTAMPTZ '2026-05-03 07:08:09+00',
                TIMESTAMPTZ '2026-05-04 10:11:12+00'
            )
            """
        ),
        state_params,
    )
    sync_state_sql = text(
        """
        SELECT
            provider_dataset_id,
            sync_scope,
            operation_key,
            status,
            cursor,
            last_success_at,
            last_failure_at,
            consecutive_failures,
            next_run_after,
            updated_at
        FROM provider_sync.provider_sync_state
        WHERE provider_dataset_id = :provider_dataset_id
          AND sync_scope = :sync_scope
          AND operation_key = :operation_key
        """
    )
    before_sync_state = dict(
        (await execution_session.execute(sync_state_sql, state_params)).mappings().one()
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    await execution_session.commit()

    lazy_client_calls: list[tuple[KorTravelMapSettings, ProviderDatasetRefreshScope]] = []

    def _forbidden_client_creation(
        settings: KorTravelMapSettings,
        scope: ProviderDatasetRefreshScope,
    ) -> object:
        lazy_client_calls.append((settings, scope))
        raise AssertionError("empty target preflight 뒤 KMA client를 만들면 안 된다")

    monkeypatch.setattr(
        dagster_runner_mod,
        "_new_kma_weather_client",
        _forbidden_client_creation,
    )
    asset_runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": AsyncKorTravelMapClient(migrated_engine),
            "reverse_geocoder": None,
            "fetched_at": _FETCHED,
            "strict_address": "off",
        },
        log=logging.getLogger(__name__),
        settings_factory=lambda: KorTravelMapSettings.model_construct(
            data_go_kr_service_key=None,
            kma_weather_extra_points=None,
            kma_weather_max_grids_per_run=50,
        ),
    )
    client = AsyncKorTravelMapClient(migrated_engine)
    runner_entered = asyncio.Event()
    release_runner = asyncio.Event()

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        runner_entered.set()
        await release_runner.wait()
        return await asset_runner(session, scope)

    first_execution = asyncio.create_task(
        client.execute_feature_update_request(
            request.request_id,
            runner=runner,
            dagster_run_id="dagster-kma-empty-target",
        )
    )
    await asyncio.wait_for(runner_entered.wait(), timeout=5)
    try:
        with pytest.raises(FeatureUpdateLockBusy):
            await client.execute_feature_update_request(
                request.request_id,
                runner=runner,
                dagster_run_id="dagster-kma-empty-target-concurrent-loser",
            )
    finally:
        release_runner.set()
    result = await first_execution

    assert result is not None
    assert result.status == "failed"
    assert result.results == ()
    assert result.error_message is not None
    assert lazy_client_calls == []

    after_first_sync_state = dict(
        (await execution_session.execute(sync_state_sql, state_params)).mappings().one()
    )
    assert after_first_sync_state == before_sync_state

    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_message == result.error_message
    job = await _job_status(execution_session, request.job_id)
    assert job["status"] == "failed"
    assert job["error_message"] == result.error_message
    await execution_session.commit()

    replay = await client.execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-kma-empty-target-terminal-replay",
    )

    assert replay is not None
    assert replay.status == "failed"
    assert replay.results == ()
    assert lazy_client_calls == []
    after_replay_sync_state = dict(
        (await execution_session.execute(sync_state_sql, state_params)).mappings().one()
    )
    assert after_replay_sync_state == before_sync_state

    # T-VN-33: request/job membership은 자연키 사본이 아니라 canonical triple
    # 링크 테이블(``feature_update_request_datasets``/``import_job_datasets``)이다.
    operation_counts = (
        await execution_session.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM ops.feature_update_requests AS request
                     JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                     JOIN ops.feature_update_request_datasets AS member
                       ON member.request_id = request.request_id
                     WHERE request.scope_type = 'provider_dataset'
                       AND CAST(request.scope ->> 'provider_dataset_id' AS bigint)
                           = CAST(:provider_dataset_id AS bigint)
                       AND request.scope ->> 'sync_scope' = CAST(:sync_scope AS text)
                       AND request.scope ->> 'operation_key'
                           = CAST(:operation_key AS text)
                       AND job.kind = 'feature_update_request'
                       AND member.provider_dataset_id
                           = CAST(:provider_dataset_id AS bigint)
                       AND member.sync_scope = CAST(:sync_scope AS text)
                       AND member.operation_key = CAST(:operation_key AS text)
                    ) AS requests,
                    (SELECT count(*) FROM ops.import_jobs AS job
                     JOIN ops.import_job_datasets AS member
                       ON member.job_id = job.job_id
                     WHERE job.kind = 'feature_update_request'
                       AND member.provider_dataset_id
                           = CAST(:provider_dataset_id AS bigint)
                       AND member.sync_scope = CAST(:sync_scope AS text)
                       AND member.operation_key = CAST(:operation_key AS text)
                    ) AS jobs
                """
            ),
            state_params,
        )
    ).mappings().one()
    assert operation_counts["requests"] == 1
    assert operation_counts["jobs"] == 1

    terminal_events = (
        await execution_session.execute(
            text(
                """
                SELECT event.job_id, event.level, event.code, event.message,
                       event.payload
                FROM ops.import_job_events AS event
                JOIN ops.import_jobs AS job ON job.job_id = event.job_id
                JOIN ops.import_job_datasets AS member ON member.job_id = job.job_id
                WHERE member.provider_dataset_id
                      = CAST(:provider_dataset_id AS bigint)
                  AND member.sync_scope = CAST(:sync_scope AS text)
                  AND member.operation_key = CAST(:operation_key AS text)
                  AND event.code = 'kma.target_scope_empty'
                ORDER BY event.occurred_at, event.event_id
                """
            ),
            state_params,
        )
    ).mappings().all()
    assert len(terminal_events) == 1
    terminal_event = terminal_events[0]
    assert str(terminal_event["job_id"]) == request.job_id
    assert terminal_event["level"] == "error"
    assert terminal_event["code"] == "kma.target_scope_empty"
    assert terminal_event["message"] == result.error_message
    assert terminal_event["payload"] == {
        "status": "failed",
        "failure_code": "kma.target_scope_empty",
    }
    await execution_session.commit()

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
            yield session

    async def _empty_schedule_index(**_kwargs: object) -> DatasetScheduleIndex:
        return DatasetScheduleIndex(source_status="ok", errors=(), by_dataset={})

    monkeypatch.setattr(
        dataset_service,
        "load_dataset_schedule_index",
        _empty_schedule_index,
    )
    proxy_secret = "kma-empty-target-integration-proxy-secret"
    app = create_app(
        ApiSettings(
            _env_file=None,
            debug_routes_enabled=False,
            features_routes_enabled=False,
            admin_routes_enabled=False,
            ops_routes_enabled=True,
            api_call_log_enabled=False,
            prometheus_metrics_enabled=False,
            admin_proxy_secret=SecretStr(proxy_secret),
            admin_trusted_proxy_cidrs=["127.0.0.1/32"],
            dagster_url="http://127.0.0.1:12702",
            dagster_graphql_url=None,
            dagster_allowed_hosts=["127.0.0.1"],
        )
    )
    app.dependency_overrides[get_session] = _request_session
    auth_headers = {
        ADMIN_ACTOR_HEADER: "admin:kma-empty-target-integration",
        ADMIN_PROXY_SECRET_HEADER: proxy_secret,
    }
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
        as dagster_http_client,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=app,
                client=("127.0.0.1", 43123),
            ),
            base_url="http://testserver",
            headers=auth_headers,
        ) as api_client,
    ):
        app.state.dagster_http_client = dagster_http_client
        pipeline_response = await api_client.get(
            f"/v1/ops/pipeline/executions/update_request/{request.request_id}"
        )
        dataset_response = await api_client.get(
            f"/v1/ops/datasets/{membership.provider_dataset_id}",
            params={"sync_scope": membership.sync_scope},
        )

    assert pipeline_response.status_code == 200, pipeline_response.text
    pipeline_event_codes = [
        event["code"] for event in pipeline_response.json()["data"]["events"]
    ]
    assert pipeline_event_codes.count("kma.target_scope_empty") == 1
    assert dataset_response.status_code == 200, dataset_response.text
    dataset_event_codes = [
        event["code"]
        for event in dataset_response.json()["data"]["event_history"]["items"]
    ]
    assert dataset_event_codes.count("kma.target_scope_empty") == 1


async def test_kma_empty_terminal_event_failure_rolls_back_job_and_preserves_state(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    membership = await _membership(
        execution_session,
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
        sync_scope="target_grids",
        operation_key=KMA_ULTRA_SHORT_NOWCAST_OPERATION_KEY,
    )
    state_params = {
        "provider_dataset_id": membership.provider_dataset_id,
        "sync_scope": membership.sync_scope,
        "operation_key": membership.operation_key,
    }
    await execution_session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_sync_state (
                provider_dataset_id, sync_scope, operation_key, status, cursor,
                last_success_at, last_failure_at, consecutive_failures,
                next_run_after, updated_at
            ) VALUES (
                :provider_dataset_id, :sync_scope, :operation_key, 'disabled',
                '{"atomic":"sentinel"}'::jsonb,
                TIMESTAMPTZ '2026-05-11 01:02:03+00',
                TIMESTAMPTZ '2026-05-12 04:05:06+00',
                9,
                TIMESTAMPTZ '2026-05-13 07:08:09+00',
                TIMESTAMPTZ '2026-05-14 10:11:12+00'
            )
            """
        ),
        state_params,
    )
    state_sql = text(
        """
        SELECT provider_dataset_id, sync_scope, operation_key, status, cursor,
               last_success_at, last_failure_at, consecutive_failures,
               next_run_after, updated_at
        FROM provider_sync.provider_sync_state
        WHERE provider_dataset_id = :provider_dataset_id
          AND sync_scope = :sync_scope
          AND operation_key = :operation_key
        """
    )
    before_state = dict(
        (await execution_session.execute(state_sql, state_params)).mappings().one()
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    await execution_session.commit()
    client_creations: list[bool] = []

    def _forbidden_client_creation(
        _settings: KorTravelMapSettings,
        _scope: ProviderDatasetRefreshScope,
    ) -> object:
        client_creations.append(True)
        raise AssertionError("empty preflight 뒤 client를 만들면 안 된다")

    async def _fail_terminal_event(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected terminal event failure")

    monkeypatch.setattr(
        dagster_runner_mod,
        "_new_kma_weather_client",
        _forbidden_client_creation,
    )
    monkeypatch.setattr(
        executor_mod,
        "record_import_job_event",
        _fail_terminal_event,
    )
    runner = FeatureUpdateAssetRunner(
        common_resources={
            "kor_travel_map_client": AsyncKorTravelMapClient(migrated_engine),
            "reverse_geocoder": None,
            "fetched_at": _FETCHED,
            "strict_address": "off",
        },
        log=logging.getLogger(__name__),
        settings_factory=lambda: KorTravelMapSettings.model_construct(
            data_go_kr_service_key=None,
            kma_weather_extra_points=None,
            kma_weather_max_grids_per_run=50,
        ),
    )

    with pytest.raises(RuntimeError, match="injected terminal event failure"):
        await AsyncKorTravelMapClient(
            migrated_engine
        ).execute_feature_update_request(
            request.request_id,
            runner=runner,
            dagster_run_id="dagster-kma-empty-event-fault",
        )

    assert client_creations == []
    after_state = dict(
        (await execution_session.execute(state_sql, state_params)).mappings().one()
    )
    assert after_state == before_state
    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "running"
    job = await _job_status(execution_session, request.job_id)
    assert job["status"] == "running"
    assert job["finished_at"] is None
    assert job["error_message"] is None
    terminal_event_count = await execution_session.scalar(
        text(
            """
            SELECT count(*)
            FROM ops.import_job_events
            WHERE job_id = CAST(:job_id AS uuid)
              AND code = 'kma.target_scope_empty'
            """
        ),
        {"job_id": request.job_id},
    )
    assert terminal_event_count == 0


async def test_transaction_bound_asset_client_rejects_engine_connection_escape(
    migrated_engine: AsyncEngine,
) -> None:
    async with AsyncSession(migrated_engine) as session, session.begin():
        bound_client = await _bind_client_to_session(
            AsyncKorTravelMapClient(migrated_engine),
            session,
        )

        async def unused_runner(
            _session: AsyncSession,
            _scope: ProviderDatasetRefreshScope,
        ) -> ProviderDatasetRefreshResult:
            raise AssertionError("missing request의 runner는 호출되면 안 된다.")

        with pytest.raises(
            RuntimeError,
            match="transaction-bound feature update asset client cannot open",
        ):
            await bound_client.execute_feature_update_request(
                "11111111-1111-4111-8111-111111111111",
                runner=unused_runner,
                dagster_run_id="dagster-bound-client",
            )


async def test_probe_failure_finishes_committed_prepare_as_failed(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    membership = await _membership(
        execution_session,
        provider="python-probe-api",
        dataset_key="probe-failure",
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    await execution_session.commit()

    async def fail_probe(*_args: Any, **_kwargs: Any) -> FeatureUpdateExecutionPlan:
        raise RuntimeError("scope probe failed")

    async def runner(
        _session: AsyncSession,
        _scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        raise AssertionError("probe 실패 뒤 runner를 호출하면 안 된다")

    monkeypatch.setattr(executor_mod, "build_feature_update_execution_plan", fail_probe)
    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-plan-failure",
    )

    assert result is not None
    assert result.status == "failed"
    assert result.request.status == "failed"
    assert result.results == ()
    assert result.error_message == "RuntimeError: scope probe failed"
    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "failed"


async def test_cancellation_marker_wins_before_runner_starts(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
) -> None:
    membership = await _membership(
        execution_session,
        provider="python-cancelled-api",
        dataset_key="cancelled-before-runner",
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    await execution_session.commit()

    async with AsyncSession(migrated_engine, expire_on_commit=False) as cancel_session:
        async with cancel_session.begin():
            scope = await resolve_pipeline_cancellation_scope(
                cancel_session,
                kind="update_request",
                execution_id=request.request_id,
            )
            assert scope is not None
            detail = await create_pipeline_cancellation_attempt(
                cancel_session,
                scope=scope,
                requested_by="feature-update-executor-test",
                reason="runner 선점 방지 검증",
            )
        cancellation_id = detail.attempt.cancellation_id
        async with cancel_session.begin():
            for member in sorted(detail.members, key=lambda item: item.job_id):
                assert await cancel_queued_pipeline_cancellation_member(
                    cancel_session,
                    cancellation_id=cancellation_id,
                    job_id=member.job_id,
                )
        async with cancel_session.begin():
            finished = await finish_pipeline_cancellation_attempt(
                cancel_session,
                cancellation_id=cancellation_id,
                status="completed",
                error=None,
            )
            assert finished is not None

    runner_calls = 0

    async def runner(
        _session: AsyncSession,
        _scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        nonlocal runner_calls
        runner_calls += 1
        raise AssertionError("취소 marker가 설정된 request의 runner를 호출하면 안 된다")

    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-cancelled-before-start",
    )

    assert result is not None
    assert result.status == "cancelled"
    assert result.request.status == "cancelled"
    assert str(
        await execution_session.scalar(
            text(
                "SELECT cancellation_id FROM ops.import_jobs "
                "WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": request.job_id},
        )
    ) == cancellation_id
    assert runner_calls == 0


async def test_execute_next_lock_busy_keeps_request_queued_and_rerunnable(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
) -> None:
    membership = await _membership(
        execution_session,
        provider="python-lock-busy-api",
        dataset_key="rerunnable",
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=request.scope_type,
        scope=request.scope,
        dataset_memberships=request.dataset_memberships,
    )
    await execution_session.commit()
    runner_calls = 0

    async def runner(
        _session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        nonlocal runner_calls
        runner_calls += 1
        return ProviderDatasetRefreshResult(
            provider_dataset_id=scope.provider_dataset_id,
            sync_scope=scope.sync_scope,
            operation_key=scope.operation_key,
            provider=scope.provider,
            dataset_key=scope.dataset_key,
        )

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as holder,
        holder.begin(),
        try_advisory_lock(holder, scope_lock_key) as acquired,
    ):
        assert acquired
        with pytest.raises(FeatureUpdateLockBusy):
            await AsyncKorTravelMapClient(
                migrated_engine
            ).execute_next_feature_update_request(
                runner=runner,
                dagster_run_id="dagster-scope-lock-loser",
            )

        queued = await get_update_request(execution_session, request.request_id)
        assert queued is not None
        assert queued.status == "queued"
        assert (await _job_status(execution_session, request.job_id))["status"] == (
            "queued"
        )
        assert runner_calls == 0
        await execution_session.commit()

    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_next_feature_update_request(
        runner=runner,
        dagster_run_id="dagster-scope-lock-retry",
    )

    assert result is not None
    assert result.status == "done"
    assert runner_calls == 1


async def test_preclaimed_running_request_requeues_when_scope_lock_is_busy(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
) -> None:
    membership = await _membership(
        execution_session,
        provider="python-preclaimed-api",
        dataset_key="lock-busy",
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    await execution_session.commit()
    client = AsyncKorTravelMapClient(migrated_engine)
    preclaimed = await client.mark_update_request_started(
        request.request_id,
        dagster_run_id="dagster-preclaim",
        expected_generation=request.generation,
    )
    assert preclaimed is not None
    assert preclaimed.status == "running"
    assert preclaimed.started_at is not None
    await execution_session.execute(
        text(
            """
            UPDATE ops.import_jobs
            SET progress = 47,
                current_stage = 'stale-provider-stage'
            WHERE job_id = :job_id
            """
        ),
        {"job_id": request.job_id},
    )
    await execution_session.commit()
    preclaimed_job = await _job_status(execution_session, request.job_id)
    assert preclaimed_job["dagster_run_id"] == "dagster-preclaim"
    assert preclaimed_job["started_at"] is not None
    assert preclaimed_job["heartbeat_at"] is not None
    assert preclaimed_job["progress"] == 47
    await execution_session.commit()
    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=request.scope_type,
        scope=request.scope,
        dataset_memberships=request.dataset_memberships,
    )

    async def runner(
        _session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        return ProviderDatasetRefreshResult(
            provider_dataset_id=scope.provider_dataset_id,
            sync_scope=scope.sync_scope,
            operation_key=scope.operation_key,
            provider=scope.provider,
            dataset_key=scope.dataset_key,
        )

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as holder,
        holder.begin(),
        try_advisory_lock(holder, scope_lock_key) as acquired,
    ):
        assert acquired
        with pytest.raises(FeatureUpdateLockBusy):
            await client.execute_feature_update_request(
                request.request_id,
                runner=runner,
                dagster_run_id="dagster-preclaim",
                expected_request_generation=preclaimed.generation,
            )

    requeued = await get_update_request(execution_session, request.request_id)
    assert requeued is not None
    assert requeued.status == "queued"
    assert requeued.dagster_run_id is None
    assert requeued.started_at is None
    assert requeued.generation == preclaimed.generation + 1
    requeued_job = await _job_status(execution_session, request.job_id)
    assert requeued_job["status"] == "queued"
    assert requeued_job["dagster_run_id"] is None
    assert requeued_job["started_at"] is None
    assert requeued_job["finished_at"] is None
    assert requeued_job["heartbeat_at"] is None
    assert requeued_job["progress"] == 0
    assert requeued_job["current_stage"] is None
    assert requeued_job["error_message"] is None
    requeued_payload = requeued_job["payload"]
    assert isinstance(requeued_payload, dict)
    assert requeued_payload == {}
    await execution_session.commit()

    result = await client.execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-retry",
        expected_request_generation=requeued.generation,
    )
    assert result is not None
    assert result.status == "done"
    assert result.request.dagster_run_id == "dagster-retry"
    retried_job = await _job_status(execution_session, request.job_id)
    assert retried_job["dagster_run_id"] == "dagster-retry"
    assert retried_job["started_at"] is not None
    assert retried_job["heartbeat_at"] is not None


async def test_request_lease_loser_touches_only_queued_run_key_and_can_retry(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
) -> None:
    membership = await _membership(
        execution_session,
        provider="python-request-lease-api",
        dataset_key="queued-retry",
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    await execution_session.commit()
    before = await get_update_request(execution_session, request.request_id)
    assert before is not None
    await execution_session.commit()
    request_lock_key = (
        f"kortravelmap:feature-update:request:{request.request_id}"
    )
    runner_calls = 0

    async def runner(
        _session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        nonlocal runner_calls
        runner_calls += 1
        return ProviderDatasetRefreshResult(
            provider_dataset_id=scope.provider_dataset_id,
            sync_scope=scope.sync_scope,
            operation_key=scope.operation_key,
            provider=scope.provider,
            dataset_key=scope.dataset_key,
        )

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as holder,
        holder.begin(),
        try_advisory_lock(holder, request_lock_key) as acquired,
    ):
        assert acquired
        with pytest.raises(FeatureUpdateLockBusy):
            await AsyncKorTravelMapClient(
                migrated_engine
            ).execute_feature_update_request(
                request.request_id,
                runner=runner,
                dagster_run_id="dagster-request-lock-loser",
                expected_request_generation=before.generation,
            )
        touched = await get_update_request(execution_session, request.request_id)
        assert touched is not None
        assert touched.status == "queued"
        assert touched.generation == before.generation + 1
        assert (await _job_status(execution_session, request.job_id))["status"] == (
            "queued"
        )
        assert runner_calls == 0
        await execution_session.commit()

    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-request-lock-retry",
        expected_request_generation=touched.generation,
    )
    assert result is not None
    assert result.status == "done"
    assert runner_calls == 1


async def test_request_lease_loser_does_not_touch_active_running_owner(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
) -> None:
    membership = await _membership(
        execution_session,
        provider="python-request-lease-api",
        dataset_key="active-owner",
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    await execution_session.commit()
    client = AsyncKorTravelMapClient(migrated_engine)
    running = await client.mark_update_request_started(
        request.request_id,
        dagster_run_id="active-owner-run",
        expected_generation=request.generation,
    )
    assert running is not None
    request_lock_key = (
        f"kortravelmap:feature-update:request:{request.request_id}"
    )

    async def runner(
        _session: AsyncSession,
        _scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        raise AssertionError("request lease loser must not call the runner")

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as holder,
        holder.begin(),
        try_advisory_lock(holder, request_lock_key) as acquired,
    ):
        assert acquired
        with pytest.raises(FeatureUpdateLockBusy):
            await client.execute_feature_update_request(
                request.request_id,
                runner=runner,
                dagster_run_id="active-owner-run",
                expected_request_generation=running.generation,
            )

    unchanged = await get_update_request(execution_session, request.request_id)
    assert unchanged is not None
    assert unchanged.status == "running"
    assert unchanged.generation == running.generation
    assert unchanged.dagster_run_id == "active-owner-run"
    active_job = await _job_status(execution_session, request.job_id)
    assert active_job["status"] == "running"
    assert active_job["dagster_run_id"] == "active-owner-run"


async def test_cancelled_error_releases_scope_lock_on_same_connection(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
) -> None:
    membership = await _membership(
        execution_session,
        provider="python-interrupted-api",
        dataset_key="cancelled-error",
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=request.scope_type,
        scope=request.scope,
        dataset_memberships=request.dataset_memberships,
    )
    await execution_session.commit()

    async def runner(
        session: AsyncSession,
        _scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        assert session.in_transaction()
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await AsyncKorTravelMapClient(
            migrated_engine
        ).execute_feature_update_request(
            request.request_id,
            runner=runner,
            dagster_run_id="dagster-cancelled-error",
        )

    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as competitor,
        competitor.begin(),
        try_advisory_lock(competitor, scope_lock_key) as acquired,
    ):
        assert acquired

    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_message == (
        "CancelledError: feature update execution was interrupted"
    )
    assert request.job_id is not None
    job = await _job_status(execution_session, request.job_id)
    assert job["status"] == "failed"
    assert job["error_message"] == stored.error_message


async def test_false_exact_unlock_invalidates_connection(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    membership = await _membership(
        execution_session,
        provider="python-unlock-api",
        dataset_key="false-unlock",
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    scope_lock_id = advisory_lock_key(
        feature_update_scope_advisory_key(
            scope_type=request.scope_type,
            scope=request.scope,
            dataset_memberships=request.dataset_memberships,
        )
    )
    request_lock_id = advisory_lock_key(
        f"kortravelmap:feature-update:request:{request.request_id}"
    )
    await execution_session.commit()
    invalidations: list[bool] = []
    async_invalidation_attempts: list[BaseException | None] = []
    original_backend_pids: list[int] = []

    async def fail_async_invalidation(
        _connection: AsyncConnection,
        exception: BaseException | None = None,
    ) -> None:
        async_invalidation_attempts.append(exception)
        raise RuntimeError("simulated async invalidate failure")

    def record_invalidation(
        _dbapi_connection: Any,
        _connection_record: Any,
        _exception: BaseException | None,
    ) -> None:
        invalidations.append(True)

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        original_backend_pids.append(
            int((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        )
        unlocked = bool(
            (
                await session.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": scope_lock_id},
                )
            ).scalar_one()
        )
        assert unlocked
        return ProviderDatasetRefreshResult(
            provider_dataset_id=scope.provider_dataset_id,
            sync_scope=scope.sync_scope,
            operation_key=scope.operation_key,
            provider=scope.provider,
            dataset_key=scope.dataset_key,
        )

    event.listen(migrated_engine.sync_engine, "invalidate", record_invalidation)
    monkeypatch.setattr(AsyncConnection, "invalidate", fail_async_invalidation)
    try:
        with pytest.raises(FeatureUpdateLockReleaseError):
            await AsyncKorTravelMapClient(
                migrated_engine
            ).execute_feature_update_request(
                request.request_id,
                runner=runner,
                dagster_run_id="dagster-unlock-failure",
            )
    finally:
        event.remove(migrated_engine.sync_engine, "invalidate", record_invalidation)

    assert async_invalidation_attempts
    assert invalidations
    assert len(original_backend_pids) == 1
    async with (
        AsyncSession(migrated_engine, expire_on_commit=False) as competitor,
        competitor.begin(),
    ):
        competitor_pid = int(
            (await competitor.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        )
        assert competitor_pid != original_backend_pids[0]
        original_backend_alive = bool(
            (
                await competitor.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_stat_activity WHERE pid = :pid"
                        ")"
                    ),
                    {"pid": original_backend_pids[0]},
                )
            ).scalar_one()
        )
        assert original_backend_alive is False
        request_lease_acquired = bool(
            (
                await competitor.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": request_lock_id},
                )
            ).scalar_one()
        )
        assert request_lease_acquired
        request_lease_released = bool(
            (
                await competitor.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": request_lock_id},
                )
            ).scalar_one()
        )
        assert request_lease_released
    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "done"


async def test_hard_invalidation_raises_unsafe_when_no_backend_can_be_closed() -> None:
    class _BrokenConnection:
        invalidated = False

        @property
        def sync_connection(self) -> object:
            raise RuntimeError("pool proxy unavailable")

        async def invalidate(self, _cause: BaseException) -> None:
            raise RuntimeError("async invalidate unavailable")

    broken_connection: Any = _BrokenConnection()
    cause = RuntimeError("lock ownership is uncertain")
    with pytest.raises(FeatureUpdateConnectionUnsafe):
        await executor_mod._hard_invalidate_connection(
            broken_connection,
            cause=cause,
        )


async def test_cancellation_marker_preserves_committed_scope_and_skips_next_runner(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memberships = {
        dataset_key: await _membership(
            execution_session,
            provider="python-phase-api",
            dataset_key=dataset_key,
            operation_key=f"feature_place_python_phase_{dataset_key}_job".replace("-", "_"),
        )
        for dataset_key in ("phase-a", "phase-b")
    }
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(memberships["phase-a"]),
        dataset_memberships=[memberships["phase-a"]],
    )
    assert isinstance(request, FeatureUpdateRequest)
    await execution_session.commit()

    resolution = ScopeResolution(scope_type="provider_dataset", features=())

    async def fake_plan(
        _session: AsyncSession,
        current: FeatureUpdateRequest,
        *,
        sigungu_resolver: Any = None,
    ) -> FeatureUpdateExecutionPlan:
        del sigungu_resolver
        scopes = tuple(
            ProviderDatasetRefreshScope(
                request_id=current.request_id,
                provider_dataset_id=memberships[dataset_key].provider_dataset_id,
                sync_scope=memberships[dataset_key].sync_scope,
                operation_key=memberships[dataset_key].operation_key,
                provider="python-phase-api",
                dataset_key=dataset_key,
                scope_type=current.scope_type,
                request_scope=current.scope,
                update_policy=current.update_policy,
                feature_ids=(),
                feature_count=0,
                prevent_provider_reactivation=True,
            )
            for dataset_key in ("phase-a", "phase-b")
        )
        return FeatureUpdateExecutionPlan(
            request=current,
            resolution=resolution,
            refresh_scopes=scopes,
            skipped_scopes=(),
            matched_scope={
                "feature_count": 0,
                "eligible_provider_scopes": [
                    scope.as_matched_scope() for scope in scopes
                ],
                "skipped_provider_scopes": [],
            },
        )

    original_guard = executor_mod._guard_execution_phase
    guard_calls = 0
    cancellation_finished = asyncio.Event()

    async def guarded_phase(
        session: AsyncSession,
        request_id: str,
        *,
        expected_generation: int,
        owner_dagster_run_id: str,
    ) -> FeatureUpdateRequest:
        nonlocal guard_calls
        assert expected_generation == request.generation
        assert owner_dagster_run_id == "dagster-mid-scope-cancellation"
        guard_calls += 1
        if guard_calls == 4:
            await asyncio.wait_for(cancellation_finished.wait(), timeout=5)
        return await original_guard(
            session,
            request_id,
            expected_generation=expected_generation,
            owner_dagster_run_id=owner_dagster_run_id,
        )

    monkeypatch.setattr(executor_mod, "build_feature_update_execution_plan", fake_plan)
    monkeypatch.setattr(executor_mod, "_guard_execution_phase", guarded_phase)

    runner_calls: list[str] = []
    loaded_feature_id: str | None = None
    cancellation_task: asyncio.Task[None] | None = None
    cancellation_detail: Any = None

    async def cancel_after_first_scope() -> None:
        nonlocal cancellation_detail
        try:
            async with (
                AsyncSession(migrated_engine) as cancel_session,
                cancel_session.begin(),
            ):
                scope = await resolve_pipeline_cancellation_scope(
                    cancel_session,
                    kind="update_request",
                    execution_id=request.request_id,
                )
                assert scope is not None
                cancellation_detail = await create_pipeline_cancellation_attempt(
                    cancel_session,
                    scope=scope,
                    requested_by="admin:test",
                    reason="scope checkpoint test",
                )
        finally:
            cancellation_finished.set()

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        nonlocal cancellation_task, loaded_feature_id
        runner_calls.append(scope.dataset_key)
        assert scope.dataset_key == "phase-a"
        loaded = await _bundle("EXEC-PHASE-COMMITTED")
        loaded_feature_id = loaded.feature.feature_id
        await feature_repo.load_bundle(session, loaded)
        cancellation_task = asyncio.create_task(cancel_after_first_scope())
        await asyncio.sleep(0)
        return ProviderDatasetRefreshResult(
            provider_dataset_id=scope.provider_dataset_id,
            sync_scope=scope.sync_scope,
            operation_key=scope.operation_key,
            provider=scope.provider,
            dataset_key=scope.dataset_key,
            loaded_feature_ids=(loaded.feature.feature_id,),
            loaded_count=1,
        )

    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-mid-scope-cancellation",
    )
    assert cancellation_task is not None
    await cancellation_task

    assert result is not None
    assert cancellation_detail is not None
    assert result.status == "running"
    assert result.request.status == "running"
    assert (
        result.request.cancellation_id
        == cancellation_detail.attempt.cancellation_id
    )
    assert [item.dataset_key for item in result.results] == ["phase-a"]
    assert runner_calls == ["phase-a"]
    assert loaded_feature_id is not None
    persisted = (
        await execution_session.execute(
            text("SELECT 1 FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": loaded_feature_id},
        )
    ).first()
    assert persisted is not None
    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "running"
    assert stored.cancellation_id == cancellation_detail.attempt.cancellation_id
    assert [
        item["dataset_key"]
        for item in stored.matched_scope["executed_provider_scopes"]
    ] == ["phase-a"]


async def test_failure_preserves_prior_scope_checkpoint_and_data(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memberships = {
        dataset_key: await _membership(
            execution_session,
            provider="python-checkpoint-api",
            dataset_key=dataset_key,
            operation_key=f"feature_place_python_checkpoint_{dataset_key}_job".replace("-", "_"),
        )
        for dataset_key in ("phase-a", "phase-b")
    }
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(memberships["phase-a"]),
        dataset_memberships=[memberships["phase-a"]],
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.job_id is not None
    await execution_session.commit()
    resolution = ScopeResolution(scope_type="provider_dataset", features=())

    async def fake_plan(
        _session: AsyncSession,
        current: FeatureUpdateRequest,
        *,
        sigungu_resolver: Any = None,
    ) -> FeatureUpdateExecutionPlan:
        del sigungu_resolver
        scopes = tuple(
            ProviderDatasetRefreshScope(
                request_id=current.request_id,
                provider_dataset_id=memberships[dataset_key].provider_dataset_id,
                sync_scope=memberships[dataset_key].sync_scope,
                operation_key=memberships[dataset_key].operation_key,
                provider="python-checkpoint-api",
                dataset_key=dataset_key,
                scope_type=current.scope_type,
                request_scope=current.scope,
                update_policy=current.update_policy,
                feature_ids=(),
                feature_count=0,
                prevent_provider_reactivation=True,
            )
            for dataset_key in ("phase-a", "phase-b")
        )
        return FeatureUpdateExecutionPlan(
            request=current,
            resolution=resolution,
            refresh_scopes=scopes,
            skipped_scopes=(),
            matched_scope={
                "feature_count": 0,
                "eligible_provider_scopes": [
                    scope.as_matched_scope() for scope in scopes
                ],
                "skipped_provider_scopes": [],
            },
        )

    monkeypatch.setattr(executor_mod, "build_feature_update_execution_plan", fake_plan)
    loaded_ids: dict[str, str] = {}

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        loaded = await _bundle(f"EXEC-CHECKPOINT-{scope.dataset_key}")
        loaded_ids[scope.dataset_key] = loaded.feature.feature_id
        await feature_repo.load_bundle(session, loaded)
        if scope.dataset_key == "phase-b":
            raise RuntimeError("second scope failed")
        return ProviderDatasetRefreshResult(
            provider_dataset_id=scope.provider_dataset_id,
            sync_scope=scope.sync_scope,
            operation_key=scope.operation_key,
            provider=scope.provider,
            dataset_key=scope.dataset_key,
            loaded_feature_ids=(loaded.feature.feature_id,),
            loaded_count=1,
        )

    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-provider-checkpoint-cancel",
    )

    assert result is not None
    assert result.status == "failed"
    assert [item.dataset_key for item in result.results] == ["phase-a"]
    assert set(loaded_ids) == {"phase-a", "phase-b"}
    persisted = {
        str(value)
        for value in await execution_session.scalars(
            text(
                "SELECT feature_id FROM feature.features "
                "WHERE feature_id IN (:first_id, :second_id)"
            ),
            {
                "first_id": loaded_ids["phase-a"],
                "second_id": loaded_ids["phase-b"],
            },
        )
    }
    assert persisted == {loaded_ids["phase-a"]}
    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert stored.status == "failed"
    assert [
        item["dataset_key"]
        for item in stored.matched_scope["executed_provider_scopes"]
    ] == ["phase-a"]
    assert (await _job_status(execution_session, request.job_id))["status"] == "failed"


async def test_scope_checkpoint_commits_before_real_cancellation_marker_wins(
    migrated_engine: AsyncEngine,
    execution_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    membership = await _membership(
        execution_session,
        provider="python-marker-race-api",
        dataset_key="phase-a",
        operation_key="feature_place_python_marker_race_phase_a_job",
    )
    request = await enqueue_feature_update_request(
        execution_session,
        scope=_provider_dataset_scope(membership),
        dataset_memberships=[membership],
    )
    assert isinstance(request, FeatureUpdateRequest)
    await execution_session.commit()
    resolution = ScopeResolution(scope_type="provider_dataset", features=())

    async def fake_plan(
        _session: AsyncSession,
        current: FeatureUpdateRequest,
        *,
        sigungu_resolver: Any = None,
    ) -> FeatureUpdateExecutionPlan:
        del sigungu_resolver
        scope = ProviderDatasetRefreshScope(
            request_id=current.request_id,
            provider_dataset_id=membership.provider_dataset_id,
            sync_scope=membership.sync_scope,
            operation_key=membership.operation_key,
            provider="python-marker-race-api",
            dataset_key="phase-a",
            scope_type=current.scope_type,
            request_scope=current.scope,
            update_policy=current.update_policy,
            feature_ids=(),
            feature_count=0,
            prevent_provider_reactivation=True,
        )
        return FeatureUpdateExecutionPlan(
            request=current,
            resolution=resolution,
            refresh_scopes=(scope,),
            skipped_scopes=(),
            matched_scope={
                "feature_count": 0,
                "eligible_provider_scopes": [scope.as_matched_scope()],
                "skipped_provider_scopes": [],
            },
        )

    marker_waiting = asyncio.Event()
    marker_finished = asyncio.Event()
    cancellation_detail: Any = None

    async def create_marker() -> None:
        nonlocal cancellation_detail
        try:
            async with AsyncSession(
                migrated_engine,
                expire_on_commit=False,
            ) as cancel_session, cancel_session.begin():
                scope = await resolve_pipeline_cancellation_scope(
                    cancel_session,
                    kind="update_request",
                    execution_id=request.request_id,
                )
                assert scope is not None
                marker_waiting.set()
                cancellation_detail = await create_pipeline_cancellation_attempt(
                    cancel_session,
                    scope=scope,
                    requested_by="feature-update-marker-race",
                    reason="scope checkpoint row-lock ordering",
                )
        finally:
            marker_finished.set()

    original_guard = executor_mod._guard_execution_phase
    guard_calls = 0

    async def wait_for_marker_before_finalize(
        session: AsyncSession,
        request_id: str,
        *,
        expected_generation: int,
        owner_dagster_run_id: str,
    ) -> FeatureUpdateRequest:
        nonlocal guard_calls
        assert expected_generation == request.generation
        assert owner_dagster_run_id == "dagster-finalize-cancel-race"
        guard_calls += 1
        if guard_calls == 4:
            await asyncio.wait_for(marker_finished.wait(), timeout=5)
        return await original_guard(
            session,
            request_id,
            expected_generation=expected_generation,
            owner_dagster_run_id=owner_dagster_run_id,
        )

    monkeypatch.setattr(executor_mod, "build_feature_update_execution_plan", fake_plan)
    monkeypatch.setattr(
        executor_mod,
        "_guard_execution_phase",
        wait_for_marker_before_finalize,
    )
    marker_task: asyncio.Task[None] | None = None
    loaded_feature_id: str | None = None

    async def runner(
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult:
        nonlocal marker_task, loaded_feature_id
        loaded = await _bundle("EXEC-MARKER-RACE")
        loaded_feature_id = loaded.feature.feature_id
        await feature_repo.load_bundle(session, loaded)
        marker_task = asyncio.create_task(create_marker())
        await asyncio.wait_for(marker_waiting.wait(), timeout=5)
        await asyncio.sleep(0.05)
        assert not marker_task.done()
        return ProviderDatasetRefreshResult(
            provider_dataset_id=scope.provider_dataset_id,
            sync_scope=scope.sync_scope,
            operation_key=scope.operation_key,
            provider=scope.provider,
            dataset_key=scope.dataset_key,
            loaded_feature_ids=(loaded.feature.feature_id,),
            loaded_count=1,
        )

    result = await AsyncKorTravelMapClient(
        migrated_engine
    ).execute_feature_update_request(
        request.request_id,
        runner=runner,
        dagster_run_id="dagster-finalize-cancel-race",
    )
    assert marker_task is not None
    await marker_task

    assert result is not None
    assert result.status == "running"
    assert cancellation_detail is not None
    assert str(
        await execution_session.scalar(
            text(
                "SELECT cancellation_id FROM ops.import_jobs "
                "WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": request.job_id},
        )
    ) == cancellation_detail.attempt.cancellation_id
    assert loaded_feature_id is not None
    assert (
        await execution_session.execute(
            text("SELECT 1 FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": loaded_feature_id},
        )
    ).first() is not None
    stored = await get_update_request(execution_session, request.request_id)
    assert stored is not None
    assert [
        item["dataset_key"]
        for item in stored.matched_scope["executed_provider_scopes"]
    ] == ["phase-a"]
