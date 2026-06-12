"""Feature update request 실행 본체 (ADR-045 T-206d).

본 모듈은 queued ``ops.feature_update_requests``를 claim하고, scope를 다시 해석한 뒤
provider/dataset 단위 runner를 호출한다. provider API client나 Dagster는 import하지
않고, 실제 refresh 구현은 호출자가 ``ProviderDatasetRefreshRunner``로 주입한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from kortravelmap.infra.advisory_lock import try_advisory_lock
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateLockBusy,
    FeatureUpdateRequest,
    claim_next_update_request,
    feature_update_scope_advisory_key,
    finish_update_request,
    set_update_request_matched_scope,
    start_update_request,
)
from kortravelmap.infra.jobs_repo import heartbeat_import_job
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

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FeatureUpdateExecutionPlan",
    "FeatureUpdateExecutionResult",
    "ProviderDatasetRefreshResult",
    "ProviderDatasetRefreshRunner",
    "ProviderDatasetRefreshScope",
    "SkippedProviderDatasetRefresh",
    "build_feature_update_execution_plan",
    "execute_feature_update_request",
    "execute_next_feature_update_request",
]


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
    progress: int | None = None,
    current_stage: str | None = None,
) -> None:
    if request.job_id is None:
        return
    await heartbeat_import_job(
        session,
        request.job_id,
        progress=progress,
        current_stage=current_stage,
    )


async def _run_refresh_scope(
    session: AsyncSession,
    *,
    runner: ProviderDatasetRefreshRunner,
    scope: ProviderDatasetRefreshScope,
) -> ProviderDatasetRefreshResult:
    """runner 1회의 DB write를 savepoint 안에 격리한다."""
    async with session.begin_nested():
        return await runner(session, scope)


async def execute_feature_update_request(
    session: AsyncSession,
    request: FeatureUpdateRequest,
    *,
    runner: ProviderDatasetRefreshRunner,
    dagster_run_id: str | None = None,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateExecutionResult:
    """이미 claim됐거나 queued인 request 1건을 실행한다."""
    scope_lock_key = feature_update_scope_advisory_key(
        scope_type=request.scope_type,
        scope=request.scope,
        providers=request.providers,
        dataset_keys=request.dataset_keys,
    )
    async with try_advisory_lock(session, scope_lock_key) as acquired:
        if not acquired:
            raise FeatureUpdateLockBusy(lock_key=scope_lock_key)
        return await _execute_feature_update_request_locked(
            session,
            request,
            runner=runner,
            dagster_run_id=dagster_run_id,
            sigungu_resolver=sigungu_resolver,
        )


async def _execute_feature_update_request_locked(
    session: AsyncSession,
    request: FeatureUpdateRequest,
    *,
    runner: ProviderDatasetRefreshRunner,
    dagster_run_id: str | None,
    sigungu_resolver: SigunguByRadiusResolver | None,
) -> FeatureUpdateExecutionResult:
    started = await start_update_request(
        session, request.request_id, dagster_run_id=dagster_run_id
    )
    if started is None:
        plan = await build_feature_update_execution_plan(
            session, request, sigungu_resolver=sigungu_resolver
        )
        return FeatureUpdateExecutionResult(
            request=request,
            plan=plan,
            results=(),
            status=request.status,
            error_message="request is not executable",
        )

    plan = await build_feature_update_execution_plan(
        session, started, sigungu_resolver=sigungu_resolver
    )
    await set_update_request_matched_scope(
        session, started.request_id, matched_scope=plan.matched_scope
    )
    await _heartbeat_request_job(
        session,
        started,
        progress=10,
        current_stage="resolved_scope",
    )
    target_ids = [target.target_id for target in plan.resolution.cache_targets]
    await mark_poi_cache_targets_refresh_requested(session, target_ids)

    results: list[ProviderDatasetRefreshResult] = []
    try:
        total = max(len(plan.refresh_scopes), 1)
        for index, scope in enumerate(plan.refresh_scopes, start=1):
            await _heartbeat_request_job(
                session,
                started,
                progress=10 + int((index - 1) * 80 / total),
                current_stage=f"refreshing:{scope.provider}:{scope.dataset_key}",
            )
            results.append(
                await _run_refresh_scope(session, runner=runner, scope=scope)
            )

        final_resolution = plan.resolution
        if started.scope_type == "cache_target_keys":
            final_resolution = await _final_resolution(
                session, started, sigungu_resolver=sigungu_resolver
            )
            await _sync_cache_target_links(session, final_resolution)

        final_matched_scope = _matched_scope(
            final_resolution,
            plan.refresh_scopes,
            plan.skipped_scopes,
            tuple(results),
        )
        await set_update_request_matched_scope(
            session, started.request_id, matched_scope=final_matched_scope
        )
        if results:
            await mark_poi_cache_targets_refreshed(session, target_ids)
        done = await finish_update_request(
            session, started.request_id, status="done", dagster_run_id=dagster_run_id
        )
        if done is None:
            done = started
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
    except Exception as exc:
        error_message = f"{exc.__class__.__name__}: {exc}"
        await mark_poi_cache_targets_refresh_failed(session, target_ids)
        failed = await finish_update_request(
            session,
            started.request_id,
            status="failed",
            dagster_run_id=dagster_run_id,
            error_message=error_message,
        )
        return FeatureUpdateExecutionResult(
            request=failed or started,
            plan=plan,
            results=tuple(results),
            status="failed",
            error_message=error_message,
        )


async def execute_next_feature_update_request(
    session: AsyncSession,
    *,
    runner: ProviderDatasetRefreshRunner,
    dagster_run_id: str | None = None,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> FeatureUpdateExecutionResult | None:
    """queued request 1건을 claim한 뒤 실행한다. 큐가 비어 있으면 ``None``."""
    request = await claim_next_update_request(session)
    if request is None:
        return None
    return await execute_feature_update_request(
        session,
        request,
        runner=runner,
        dagster_run_id=dagster_run_id,
        sigungu_resolver=sigungu_resolver,
    )
