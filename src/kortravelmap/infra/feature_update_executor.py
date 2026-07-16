"""Feature update request 실행 본체 (ADR-045 T-206d).

본 모듈은 queued ``ops.feature_update_requests``를 상태 변경 없이 peek한 뒤
request/scope lease 안에서 CAS claim하고 provider/dataset 단위 runner를
호출한다. provider API client나 Dagster는 import하지 않고, 실제 refresh
구현은 호출자가 ``ProviderDatasetRefreshRunner``로 주입한다.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    feature_update_scope_advisory_key,
    finish_update_request,
    get_update_request,
    heartbeat_feature_update_request_job,
    lock_feature_update_execution_guard,
    peek_next_update_request,
    requeue_update_request_after_lock_contention,
    set_update_request_matched_scope,
    start_update_request,
    touch_queued_update_request_for_lock_retry,
)
from kortravelmap.infra.poi_cache_target_repo import (
    deactivate_poi_cache_target_feature_links,
    mark_poi_cache_targets_refresh_failed,
    mark_poi_cache_targets_refresh_requested,
    mark_poi_cache_targets_refreshed,
    upsert_poi_cache_target_feature_link,
)
from kortravelmap.infra.provider_refresh_policy_repo import (
    ProviderRefreshPolicy,
    get_provider_refresh_policy,
)
from kortravelmap.infra.scope_repo import (
    CacheTargetFeatureMatch,
    ProviderDatasetScope,
    ScopeResolution,
    SigunguByRadiusResolver,
    count_features_matching_scope,
)
from kortravelmap.infra.sync_state_repo import (
    record_sync_failure as record_provider_sync_failure,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncConnection

    from kortravelmap.infra.scope_repo import ScopeType

__all__ = [
    "FeatureUpdateExecutionPlan",
    "FeatureUpdateExecutionResult",
    "FeatureUpdateConnectionUnsafe",
    "FeatureUpdateLockReleaseError",
    "ProviderDatasetRefreshResult",
    "ProviderDatasetRefreshFailure",
    "ProviderDatasetRefreshRunner",
    "ProviderDatasetRefreshScope",
    "SkippedProviderDatasetRefresh",
    "build_feature_update_execution_plan",
    "execute_feature_update_request",
    "execute_next_feature_update_request",
]

_TRY_SCOPE_LOCK_SQL: Final[str] = "SELECT pg_try_advisory_lock(:lock_id)"
_UNLOCK_SCOPE_SQL: Final[str] = "SELECT pg_advisory_unlock(:lock_id)"
_REQUEST_EXECUTION_LOCK_PREFIX: Final[str] = "kortravelmap:feature-update:request"
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderDatasetRefreshScope:
    """runner가 실행할 provider/dataset refresh 단위."""

    request_id: str
    provider: str
    dataset_key: str
    scope_type: str
    request_scope: dict[str, Any]
    update_policy: dict[str, Any]
    feature_ids: tuple[str, ...]
    feature_count: int
    prevent_provider_reactivation: bool
    sync_scope: str | None = None
    provider_policy: ProviderRefreshPolicy | None = None
    rate_limit: dict[str, Any] | None = None
    target_ids: tuple[str, ...] = ()
    target_matches: tuple[CacheTargetFeatureMatch, ...] = ()

    def as_matched_scope(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "feature_count": self.feature_count,
            "prevent_provider_reactivation": self.prevent_provider_reactivation,
        }
        if self.target_ids:
            payload["target_ids"] = list(self.target_ids)
        if self.sync_scope is not None:
            payload["sync_scope"] = self.sync_scope
        if self.rate_limit:
            payload["rate_limit"] = dict(self.rate_limit)
        return payload


@dataclass(frozen=True)
class ProviderDatasetRefreshResult:
    """runner 1회 실행 결과."""

    provider: str
    dataset_key: str
    status: str = "done"
    loaded_feature_ids: tuple[str, ...] = ()
    loaded_count: int = 0
    metadata: dict[str, Any] | None = None

    def as_matched_scope(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "status": self.status,
            "loaded_feature_ids": list(self.loaded_feature_ids),
            "loaded_count": self.loaded_count,
            "metadata": dict(self.metadata or {}),
        }


class ProviderDatasetRefreshFailure(RuntimeError):
    """provider refresh 실패와 durable sync-state identity를 함께 전달한다."""

    def __init__(
        self,
        *,
        provider: str,
        dataset_key: str,
        sync_scope: str,
        message: str,
    ) -> None:
        for field_name, value in (
            ("provider", provider),
            ("dataset_key", dataset_key),
            ("sync_scope", sync_scope),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{field_name} must be a trimmed non-empty string")
        self.provider = provider
        self.dataset_key = dataset_key
        self.sync_scope = sync_scope
        super().__init__(message)


class ProviderDatasetRefreshRunner(Protocol):
    """provider/dataset refresh 실행 함수 계약.

    Dagster job/op 또는 테스트 runner가 이 프로토콜을 구현한다. session commit은
    executor 호출자가 소유한다.
    """

    async def __call__(
        self,
        session: AsyncSession,
        scope: ProviderDatasetRefreshScope,
    ) -> ProviderDatasetRefreshResult: ...


@dataclass(frozen=True)
class SkippedProviderDatasetRefresh:
    """정책/필터 때문에 실행하지 않은 provider/dataset."""

    provider: str
    dataset_key: str
    reason: str
    feature_count: int

    def as_matched_scope(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "reason": self.reason,
            "feature_count": self.feature_count,
        }


@dataclass(frozen=True)
class FeatureUpdateExecutionPlan:
    """실행 전 scope 해석 + 정책 적용 결과."""

    request: FeatureUpdateRequest
    resolution: ScopeResolution
    refresh_scopes: tuple[ProviderDatasetRefreshScope, ...]
    skipped_scopes: tuple[SkippedProviderDatasetRefresh, ...]
    matched_scope: dict[str, Any]


@dataclass(frozen=True)
class FeatureUpdateExecutionResult:
    """request 실행 결과."""

    request: FeatureUpdateRequest
    plan: FeatureUpdateExecutionPlan
    results: tuple[ProviderDatasetRefreshResult, ...]
    status: str
    error_message: str | None = None


class FeatureUpdateLockReleaseError(RuntimeError):
    """scope session lock의 exact unlock을 증명하지 못했다."""


class FeatureUpdateConnectionUnsafe(RuntimeError):
    """session lock backend의 pool 복귀 차단을 증명하지 못했다."""


class _FeatureUpdateExecutionStopped(RuntimeError):
    """marker/status guard가 provider 실행보다 먼저 승리했다."""


def _unresolved_execution_plan(
    request: FeatureUpdateRequest,
) -> FeatureUpdateExecutionPlan:
    """probe 실패도 lifecycle을 종결할 수 있게 하는 최소 오류 plan."""
    resolution = ScopeResolution(
        scope_type=cast("ScopeType", request.scope_type),
        features=(),
    )
    return FeatureUpdateExecutionPlan(
        request=request,
        resolution=resolution,
        refresh_scopes=(),
        skipped_scopes=(),
        matched_scope=dict(request.matched_scope),
    )


def _provider_dataset_scopes(
    request: FeatureUpdateRequest,
    resolution: ScopeResolution,
) -> tuple[ProviderDatasetScope, ...]:
    scopes = list(resolution.provider_datasets)
    if request.scope_type == "provider_dataset":
        provider = str(request.scope["provider"])
        dataset_key = str(request.scope["dataset_key"])
        if not any(
            item.provider == provider and item.dataset_key == dataset_key
            for item in scopes
        ):
            scopes.append(
                ProviderDatasetScope(
                    provider=provider,
                    dataset_key=dataset_key,
                    feature_count=resolution.feature_count,
                )
            )
    return tuple(scopes)


def _rate_limit(policy: ProviderRefreshPolicy | None) -> dict[str, Any]:
    if policy is None:
        return {}
    return {
        "source_kind": policy.source_kind,
        "targeted_policy": policy.targeted_policy,
        "min_interval_seconds": policy.min_interval_seconds,
        "max_requests_per_minute": policy.max_requests_per_minute,
        "max_requests_per_hour": policy.max_requests_per_hour,
        "max_requests_per_day": policy.max_requests_per_day,
        "max_concurrent": policy.max_concurrent,
        "burst_size": policy.burst_size,
        "rate_limit_source": policy.rate_limit_source,
    }


def _override_targeted_policy(
    *,
    provider: str,
    dataset_key: str,
    resolution: ScopeResolution,
) -> str | None:
    values: list[str] = []
    keys = (f"{provider}:{dataset_key}", provider)
    for target in resolution.cache_targets:
        for key in keys:
            raw = target.provider_overrides.get(key)
            if isinstance(raw, Mapping):
                value = raw.get("targeted_policy")
                if isinstance(value, str):
                    values.append(value)
    if "allow_targeted" in values:
        return "allow_targeted"
    if "disabled" in values:
        return "disabled"
    if "follow_system" in values:
        return "follow_system"
    return None


def _skip_reason(
    *,
    request: FeatureUpdateRequest,
    provider: str,
    dataset_key: str,
    policy: ProviderRefreshPolicy | None,
    resolution: ScopeResolution,
) -> str | None:
    providers = set(request.providers)
    dataset_keys = set(request.dataset_keys)
    if providers and provider not in providers:
        return "provider_filter"
    if dataset_keys and dataset_key not in dataset_keys:
        return "dataset_filter"
    override = _override_targeted_policy(
        provider=provider, dataset_key=dataset_key, resolution=resolution
    )
    if policy is not None and not policy.enabled:
        return "policy_disabled"
    effective_targeted_policy = override or (
        policy.targeted_policy if policy is not None else "allow_targeted"
    )
    if effective_targeted_policy == "disabled":
        return "targeted_policy_disabled"
    targeted_request = request.scope_type != "provider_dataset"
    if targeted_request and effective_targeted_policy == "follow_system":
        return "follow_system_skipped"
    if (
        targeted_request
        and policy is not None
        and policy.source_kind == "filedata"
        and effective_targeted_policy != "allow_targeted"
    ):
        return "filedata_targeted_skipped"
    return None


def _target_matches_for_provider(
    resolution: ScopeResolution,
    *,
    provider: str,
    dataset_key: str,
) -> tuple[CacheTargetFeatureMatch, ...]:
    return tuple(
        match
        for match in resolution.cache_target_matches
        if match.provider == provider and match.dataset_key == dataset_key
    )


def _target_ids_for_provider(
    matches: tuple[CacheTargetFeatureMatch, ...],
) -> tuple[str, ...]:
    seen: set[str] = set()
    values: list[str] = []
    for match in matches:
        if match.target_id in seen:
            continue
        seen.add(match.target_id)
        values.append(match.target_id)
    return tuple(values)


def _matched_scope(
    resolution: ScopeResolution,
    refresh_scopes: tuple[ProviderDatasetRefreshScope, ...],
    skipped_scopes: tuple[SkippedProviderDatasetRefresh, ...],
    results: tuple[ProviderDatasetRefreshResult, ...] = (),
) -> dict[str, Any]:
    payload = resolution.matched_scope()
    payload["eligible_provider_scopes"] = [
        scope.as_matched_scope() for scope in refresh_scopes
    ]
    payload["skipped_provider_scopes"] = [
        scope.as_matched_scope() for scope in skipped_scopes
    ]
    if results:
        payload["executed_provider_scopes"] = [
            result.as_matched_scope() for result in results
        ]
    return payload


async def build_feature_update_execution_plan(
    session: AsyncSession,
    request: FeatureUpdateRequest,
    *,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateExecutionPlan:
    """request를 실행 가능한 provider/dataset refresh 단위로 분해한다."""
    resolution = await count_features_matching_scope(
        session, request.scope, sigungu_resolver=sigungu_resolver
    )
    refresh_scopes: list[ProviderDatasetRefreshScope] = []
    skipped_scopes: list[SkippedProviderDatasetRefresh] = []
    prevent_provider_reactivation = bool(
        request.update_policy.get("prevent_provider_reactivation", True)
    )

    for item in _provider_dataset_scopes(request, resolution):
        policy = await get_provider_refresh_policy(
            session, provider=item.provider, dataset_key=item.dataset_key
        )
        reason = _skip_reason(
            request=request,
            provider=item.provider,
            dataset_key=item.dataset_key,
            policy=policy,
            resolution=resolution,
        )
        if reason is not None:
            skipped_scopes.append(
                SkippedProviderDatasetRefresh(
                    provider=item.provider,
                    dataset_key=item.dataset_key,
                    reason=reason,
                    feature_count=item.feature_count,
                )
            )
            continue
        target_matches = _target_matches_for_provider(
            resolution, provider=item.provider, dataset_key=item.dataset_key
        )
        refresh_scopes.append(
            ProviderDatasetRefreshScope(
                request_id=request.request_id,
                provider=item.provider,
                dataset_key=item.dataset_key,
                scope_type=request.scope_type,
                request_scope=request.scope,
                update_policy=request.update_policy,
                feature_ids=resolution.feature_ids,
                feature_count=item.feature_count,
                prevent_provider_reactivation=prevent_provider_reactivation,
                sync_scope=request.effective_sync_scope,
                provider_policy=policy,
                rate_limit=_rate_limit(policy),
                target_ids=_target_ids_for_provider(target_matches),
                target_matches=target_matches,
            )
        )

    return FeatureUpdateExecutionPlan(
        request=request,
        resolution=resolution,
        refresh_scopes=tuple(refresh_scopes),
        skipped_scopes=tuple(skipped_scopes),
        matched_scope=_matched_scope(
            resolution, tuple(refresh_scopes), tuple(skipped_scopes)
        ),
    )


async def _sync_cache_target_links(
    session: AsyncSession,
    resolution: ScopeResolution,
) -> None:
    for target in resolution.cache_targets:
        await deactivate_poi_cache_target_feature_links(session, target.target_id)
    for match in resolution.cache_target_matches:
        await upsert_poi_cache_target_feature_link(
            session,
            target_id=match.target_id,
            feature_id=match.feature_id,
            provider=match.provider,
            dataset_key=match.dataset_key,
            distance_m=match.distance_m,
            relation=match.relation,
        )


async def _final_resolution(
    session: AsyncSession,
    request: FeatureUpdateRequest,
    *,
    sigungu_resolver: SigunguByRadiusResolver | None,
) -> ScopeResolution:
    return await count_features_matching_scope(
        session, request.scope, sigungu_resolver=sigungu_resolver
    )


async def _heartbeat_request_job(
    session: AsyncSession,
    request: FeatureUpdateRequest,
    *,
    owner_dagster_run_id: str,
    progress: int | None = None,
    current_stage: str | None = None,
) -> None:
    updated = await heartbeat_feature_update_request_job(
        session,
        request.job_id,
        expected_generation=request.generation,
        owner_dagster_run_id=owner_dagster_run_id,
        progress=progress,
        current_stage=current_stage,
    )
    if not updated:
        raise _FeatureUpdateExecutionStopped


async def _hard_invalidate_connection(
    connection: AsyncConnection,
    *,
    cause: BaseException,
) -> None:
    """async invalidate 실패에도 pool proxy/driver를 hard terminate한다."""
    pool_proxy: Any = None
    try:
        sync_connection = connection.sync_connection
        if sync_connection is not None:
            candidate = sync_connection.connection
            if candidate is not None:
                pool_proxy = candidate
    except Exception:
        _LOG.warning("failed to capture feature update pool proxy", exc_info=True)

    try:
        await connection.invalidate(cause)
        if connection.invalidated:
            return
    except BaseException:
        _LOG.error("async feature update connection invalidation failed", exc_info=True)

    if pool_proxy is not None:
        try:
            pool_proxy.invalidate(cause, soft=False)
            return
        except BaseException:
            _LOG.critical("sync feature update hard invalidation failed", exc_info=True)

        try:
            dbapi_connection = pool_proxy.dbapi_connection
            driver_connection = getattr(dbapi_connection, "driver_connection", None)
            terminate = getattr(driver_connection, "terminate", None)
            if not callable(terminate):
                raise RuntimeError("physical driver terminate is unavailable")
            terminated = terminate()
            if inspect.isawaitable(terminated):
                await terminated
            return
        except Exception as exc:
            _LOG.critical(
                "physical feature update backend terminate failed",
                exc_info=True,
            )
            raise FeatureUpdateConnectionUnsafe(
                "failed to hard-invalidate the feature update execution backend"
            ) from exc

    raise FeatureUpdateConnectionUnsafe(
        "failed to hard-invalidate the feature update execution backend"
    ) from cause


async def _acquire_scope_lock(
    session: AsyncSession,
    connection: AsyncConnection,
    *,
    lock_id: int,
) -> bool:
    """session lock acquire의 implicit transaction을 즉시 종결한다."""
    try:
        acquired = bool(
            (
                await session.execute(
                    text(_TRY_SCOPE_LOCK_SQL),
                    {"lock_id": lock_id},
                )
            ).scalar_one()
        )
        await session.commit()
        return acquired
    except BaseException as exc:
        await _hard_invalidate_connection(connection, cause=exc)
        raise


async def _release_scope_lock(
    session: AsyncSession,
    connection: AsyncConnection,
    *,
    lock_id: int,
) -> None:
    """같은 backend에서 exact unlock=true를 확인하고 transaction을 닫는다."""
    try:
        unlocked = bool(
            (
                await session.execute(
                    text(_UNLOCK_SCOPE_SQL),
                    {"lock_id": lock_id},
                )
            ).scalar_one()
        )
        await session.commit()
    except BaseException as exc:
        await _hard_invalidate_connection(connection, cause=exc)
        raise
    if unlocked:
        return
    release_error = FeatureUpdateLockReleaseError(
        "feature update scope advisory lock exact unlock returned false"
    )
    await _hard_invalidate_connection(connection, cause=release_error)
    raise release_error


async def _guard_execution_phase(
    session: AsyncSession,
    request_id: str,
    *,
    expected_generation: int,
    owner_dagster_run_id: str,
) -> FeatureUpdateRequest:
    request = await lock_feature_update_execution_guard(
        session,
        request_id,
        expected_generation=expected_generation,
        owner_dagster_run_id=owner_dagster_run_id,
    )
    if request is None:
        raise _FeatureUpdateExecutionStopped
    return request


async def _reload_stopped_result(
    session: AsyncSession,
    request: FeatureUpdateRequest,
    *,
    plan: FeatureUpdateExecutionPlan | None,
    results: Sequence[ProviderDatasetRefreshResult],
) -> FeatureUpdateExecutionResult:
    """guard 패배 transaction과 분리해 cancellation/terminal 상태를 복원한다."""
    async with session.begin():
        current = await get_update_request(session, request.request_id) or request
        current_plan = (
            _unresolved_execution_plan(current)
            if plan is None
            else replace(plan, request=current)
        )
    return FeatureUpdateExecutionResult(
        request=current,
        plan=current_plan,
        results=tuple(results),
        status=current.status,
        error_message="request cancellation or terminal state took precedence",
    )


async def _finish_failed_execution(
    session: AsyncSession,
    request: FeatureUpdateRequest,
    *,
    plan: FeatureUpdateExecutionPlan,
    results: Sequence[ProviderDatasetRefreshResult],
    error_message: str,
    owner_dagster_run_id: str,
) -> FeatureUpdateExecutionResult:
    target_ids = [target.target_id for target in plan.resolution.cache_targets]
    try:
        async with session.begin():
            await _guard_execution_phase(
                session,
                request.request_id,
                expected_generation=request.generation,
                owner_dagster_run_id=owner_dagster_run_id,
            )
            await mark_poi_cache_targets_refresh_failed(session, target_ids)
            failed = await finish_update_request(
                session,
                request.request_id,
                status="failed",
                owner_dagster_run_id=owner_dagster_run_id,
                expected_generation=request.generation,
                error_message=error_message,
            )
            if failed is None:
                raise _FeatureUpdateExecutionStopped
    except _FeatureUpdateExecutionStopped:
        return await _reload_stopped_result(
            session,
            request,
            plan=plan,
            results=results,
        )
    return FeatureUpdateExecutionResult(
        request=failed,
        plan=replace(plan, request=failed),
        results=tuple(results),
        status="failed",
        error_message=error_message,
    )


async def _record_provider_refresh_failure(
    session: AsyncSession,
    failure: ProviderDatasetRefreshFailure,
) -> None:
    """실패한 bound refresh transaction과 분리해 sync failure를 먼저 commit한다."""
    async with session.begin():
        await record_provider_sync_failure(
            session,
            provider=failure.provider,
            dataset_key=failure.dataset_key,
            sync_scope=failure.sync_scope,
        )


async def execute_feature_update_request(
    connection: AsyncConnection,
    request: FeatureUpdateRequest,
    *,
    runner: ProviderDatasetRefreshRunner,
    dagster_run_id: str,
    expected_request_generation: int | None = None,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateExecutionResult:
    """전용 physical connection에서 request 1건을 phase별 commit으로 실행한다."""
    if connection.in_transaction():
        raise ValueError("feature update execution requires an idle connection")
    if not dagster_run_id or dagster_run_id != dagster_run_id.strip():
        raise ValueError("dagster_run_id must be a trimmed non-empty string")
    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=request.scope_type,
        scope=request.scope,
        providers=request.providers,
        dataset_keys=request.dataset_keys,
    )
    request_lock_key = f"{_REQUEST_EXECUTION_LOCK_PREFIX}:{request.request_id}"
    request_lock_id = advisory_lock_key(request_lock_key)
    lock_id = advisory_lock_key(scope_lock_key)
    async with AsyncSession(
        bind=connection,
        expire_on_commit=False,
    ) as session:
        request_acquired = await _acquire_scope_lock(
            session,
            connection,
            lock_id=request_lock_id,
        )
        if not request_acquired:
            async with session.begin():
                await touch_queued_update_request_for_lock_retry(
                    session,
                    request.request_id,
                    expected_generation=(
                        expected_request_generation
                        if expected_request_generation is not None
                        else request.generation
                    ),
                )
            raise FeatureUpdateLockBusy(lock_key=request_lock_key)
        scope_acquired = False
        interrupted: asyncio.CancelledError | None = None
        try:
            try:
                scope_acquired = await _acquire_scope_lock(
                    session,
                    connection,
                    lock_id=lock_id,
                )
            except BaseException:
                # acquire 오류는 connection을 invalidate해 request lock도 backend와
                # 함께 폐기한다. invalid connection에서 unlock을 재시도하지 않는다.
                request_acquired = False
                raise
            if not scope_acquired:
                async with session.begin():
                    await requeue_update_request_after_lock_contention(
                        session,
                        request.request_id,
                        expected_generation=(
                            expected_request_generation
                            if expected_request_generation is not None
                            else request.generation
                        ),
                        caller_dagster_run_id=dagster_run_id,
                    )
                raise FeatureUpdateLockBusy(lock_key=scope_lock_key)
            return await _execute_feature_update_request_locked(
                session,
                request,
                runner=runner,
                dagster_run_id=dagster_run_id,
                expected_request_generation=(
                    expected_request_generation
                    if expected_request_generation is not None
                    else request.generation
                ),
                sigungu_resolver=sigungu_resolver,
            )
        except asyncio.CancelledError as exc:
            interrupted = exc
            raise
        finally:
            cleanup_error: BaseException | None = None
            try:
                if session.in_transaction():
                    await session.rollback()
            except BaseException as exc:
                cleanup_error = exc
                try:
                    await _hard_invalidate_connection(connection, cause=exc)
                except BaseException as hard_error:
                    cleanup_error = hard_error
            if cleanup_error is None and scope_acquired:
                try:
                    await _release_scope_lock(
                        session,
                        connection,
                        lock_id=lock_id,
                    )
                except BaseException as exc:
                    cleanup_error = exc
            if cleanup_error is None and request_acquired:
                try:
                    await _release_scope_lock(
                        session,
                        connection,
                        lock_id=request_lock_id,
                    )
                except BaseException as exc:
                    cleanup_error = exc
            if cleanup_error is not None:
                if isinstance(cleanup_error, FeatureUpdateConnectionUnsafe):
                    if interrupted is not None:
                        raise cleanup_error from interrupted
                    raise cleanup_error
                if interrupted is not None:
                    _LOG.error(
                        "feature update cleanup failed after interruption: "
                        "request_id=%s error=%r",
                        request.request_id,
                        cleanup_error,
                    )
                else:
                    raise cleanup_error


async def _execute_feature_update_request_locked(
    session: AsyncSession,
    request: FeatureUpdateRequest,
    *,
    runner: ProviderDatasetRefreshRunner,
    dagster_run_id: str,
    expected_request_generation: int,
    sigungu_resolver: SigunguByRadiusResolver | None,
) -> FeatureUpdateExecutionResult:
    started = request
    plan: FeatureUpdateExecutionPlan | None = None
    target_ids: list[str] = []
    results: list[ProviderDatasetRefreshResult] = []
    try:
        async with session.begin():
            await _guard_execution_phase(
                session,
                request.request_id,
                expected_generation=expected_request_generation,
                owner_dagster_run_id=dagster_run_id,
            )
            claimed = await start_update_request(
                session,
                request.request_id,
                dagster_run_id=dagster_run_id,
                expected_generation=expected_request_generation,
            )
            if claimed is None:
                raise _FeatureUpdateExecutionStopped
            started = claimed

        async with session.begin():
            await _guard_execution_phase(
                session,
                started.request_id,
                expected_generation=started.generation,
                owner_dagster_run_id=dagster_run_id,
            )
            plan = await build_feature_update_execution_plan(
                session,
                started,
                sigungu_resolver=sigungu_resolver,
            )
            updated = await set_update_request_matched_scope(
                session,
                started.request_id,
                matched_scope=plan.matched_scope,
                expected_generation=started.generation,
                owner_dagster_run_id=dagster_run_id,
            )
            if updated is None:
                raise _FeatureUpdateExecutionStopped
            await _heartbeat_request_job(
                session,
                started,
                owner_dagster_run_id=dagster_run_id,
                progress=10,
                current_stage="resolved_scope",
            )
            target_ids = [
                target.target_id for target in plan.resolution.cache_targets
            ]
            await mark_poi_cache_targets_refresh_requested(session, target_ids)

        assert plan is not None
        total = max(len(plan.refresh_scopes), 1)
        for index, scope in enumerate(plan.refresh_scopes, start=1):
            async with session.begin():
                await _guard_execution_phase(
                    session,
                    started.request_id,
                    expected_generation=started.generation,
                    owner_dagster_run_id=dagster_run_id,
                )
                await _heartbeat_request_job(
                    session,
                    started,
                    owner_dagster_run_id=dagster_run_id,
                    progress=10 + int((index - 1) * 80 / total),
                    current_stage=(
                        f"refreshing:{scope.provider}:{scope.dataset_key}"
                    ),
                )
                result = await runner(session, scope)
                checkpoint_results = (*results, result)
                checkpoint = _matched_scope(
                    plan.resolution,
                    plan.refresh_scopes,
                    plan.skipped_scopes,
                    checkpoint_results,
                )
                updated = await set_update_request_matched_scope(
                    session,
                    started.request_id,
                    matched_scope=checkpoint,
                    expected_generation=started.generation,
                    owner_dagster_run_id=dagster_run_id,
                )
                if updated is None:
                    raise _FeatureUpdateExecutionStopped
            results.append(result)

        async with session.begin():
            await _guard_execution_phase(
                session,
                started.request_id,
                expected_generation=started.generation,
                owner_dagster_run_id=dagster_run_id,
            )
            final_resolution = plan.resolution
            if started.scope_type == "cache_target_keys":
                final_resolution = await _final_resolution(
                    session,
                    started,
                    sigungu_resolver=sigungu_resolver,
                )
                await _sync_cache_target_links(session, final_resolution)

            final_matched_scope = _matched_scope(
                final_resolution,
                plan.refresh_scopes,
                plan.skipped_scopes,
                tuple(results),
            )
            updated = await set_update_request_matched_scope(
                session,
                started.request_id,
                matched_scope=final_matched_scope,
                expected_generation=started.generation,
                owner_dagster_run_id=dagster_run_id,
            )
            if updated is None:
                raise _FeatureUpdateExecutionStopped
            # runner가 scope를 실제 호출하지 못해 ``skipped``로 돌려준 경우만 있으면
            # target freshness를 전진시키지 않는다.
            if any(result.status == "done" for result in results):
                await mark_poi_cache_targets_refreshed(session, target_ids)
            done = await finish_update_request(
                session,
                started.request_id,
                status="done",
                owner_dagster_run_id=dagster_run_id,
                expected_generation=started.generation,
            )
            if done is None:
                raise _FeatureUpdateExecutionStopped
        return FeatureUpdateExecutionResult(
            request=done,
            plan=FeatureUpdateExecutionPlan(
                request=done,
                resolution=final_resolution,
                refresh_scopes=plan.refresh_scopes,
                skipped_scopes=plan.skipped_scopes,
                matched_scope=final_matched_scope,
            ),
            results=tuple(results),
            status="done",
        )
    except _FeatureUpdateExecutionStopped:
        return await _reload_stopped_result(
            session,
            started,
            plan=plan,
            results=results,
        )
    except asyncio.CancelledError:
        if plan is None:
            plan = _unresolved_execution_plan(started)
        try:
            await _finish_failed_execution(
                session,
                started,
                plan=plan,
                results=results,
                error_message=(
                    "CancelledError: feature update execution was interrupted"
                ),
                owner_dagster_run_id=dagster_run_id,
            )
        except Exception:
            _LOG.exception(
                "failed to persist interrupted feature update: request_id=%s",
                started.request_id,
            )
        raise
    except Exception as exc:
        error_message = f"{exc.__class__.__name__}: {exc}"
        if plan is None:
            plan = _unresolved_execution_plan(started)
        if isinstance(exc, ProviderDatasetRefreshFailure):
            # runner의 bound transaction은 ``session.begin`` context가 이미
            # rollback했다. sync failure를 별도 transaction으로 먼저 commit해
            # 이후 request terminalize 실패에도 provider 실패 신호를 보존한다.
            await _record_provider_refresh_failure(session, exc)
        return await _finish_failed_execution(
            session,
            started,
            plan=plan,
            results=results,
            error_message=error_message,
            owner_dagster_run_id=dagster_run_id,
        )


async def execute_next_feature_update_request(
    connection: AsyncConnection,
    *,
    runner: ProviderDatasetRefreshRunner,
    dagster_run_id: str,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateExecutionResult | None:
    """queued request를 peek한 뒤 scope lock 아래 CAS claim해 실행한다."""
    if connection.in_transaction():
        raise ValueError("feature update execution requires an idle connection")
    if not dagster_run_id or dagster_run_id != dagster_run_id.strip():
        raise ValueError("dagster_run_id must be a trimmed non-empty string")
    async with AsyncSession(
        bind=connection,
        expire_on_commit=False,
    ) as session, session.begin():
        request = await peek_next_update_request(session)
    if request is None:
        return None
    return await execute_feature_update_request(
        connection,
        request,
        runner=runner,
        dagster_run_id=dagster_run_id,
        sigungu_resolver=sigungu_resolver,
    )
