"""``feature_update_executor``의 canonical membership 실행 계획 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kortravelmap.infra import feature_update_executor as executor
from kortravelmap.infra.feature_update_executor import (
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
    SkippedProviderDatasetRefresh,
    build_feature_update_execution_plan,
)
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    FeatureUpdateRequestDataset,
)
from kortravelmap.infra.provider_refresh_policy_repo import ProviderRefreshPolicy
from kortravelmap.infra.scope_repo import (
    CacheTargetFeatureMatch,
    CacheTargetScopeTarget,
    FeatureScopeRow,
    ProviderDatasetScope,
    ScopeResolution,
)

pytestmark = pytest.mark.unit


class _IdleConnection:
    def in_transaction(self) -> bool:
        return False


def _member(
    provider_dataset_id: int,
    provider: str,
    dataset_key: str,
    *,
    sync_scope: str = "dataset_wide",
    operation_key: str = "refresh_test_dataset",
) -> FeatureUpdateRequestDataset:
    return FeatureUpdateRequestDataset(
        feature_update_request_dataset_id=None,
        provider_dataset_id=provider_dataset_id,
        sync_scope=sync_scope,
        provider=provider,
        dataset_key=dataset_key,
        operation_key=operation_key,
    )


def _request(
    *,
    scope_type: str = "cache_target_keys",
    scope: dict[str, object] | None = None,
    dataset_memberships: tuple[FeatureUpdateRequestDataset, ...] | None = None,
    update_policy: dict[str, object] | None = None,
) -> FeatureUpdateRequest:
    now = datetime(2026, 8, 7, tzinfo=UTC)
    members = dataset_memberships or (
        _member(11, "python-a-api", "dataset-a"),
    )
    return FeatureUpdateRequest(
        request_id="req-1",
        scope_type=scope_type,
        scope=scope
        or {
            "type": "cache_target_keys",
            "external_system": "external-app",
            "target_keys": [],
            "scope_mode": "center_radius",
        },
        dataset_membership_mode="single" if len(members) == 1 else "multiple",
        dataset_memberships=members,
        update_policy=update_policy or {},
        run_mode="queued",
        priority=100,
        status="queued",
        matched_scope={},
        job_id="job-1",
        dagster_run_id=None,
        operator="tester",
        reason="unit",
        error_message=None,
        created_at=now,
        started_at=None,
        finished_at=None,
        generation=1,
    )


@pytest.mark.parametrize("entrypoint", ["specific", "next"])
@pytest.mark.parametrize("owner", [None, "", " ", " owner", "owner "])
async def test_execution_entrypoints_reject_missing_or_untrimmed_owner(
    entrypoint: str,
    owner: str | None,
) -> None:
    connection = _IdleConnection()

    async def execute() -> None:
        if entrypoint == "specific":
            await executor.execute_feature_update_request(
                connection,  # type: ignore[arg-type]
                _request(),
                runner=object(),  # type: ignore[arg-type]
                dagster_run_id=owner,  # type: ignore[arg-type]
            )
            return
        await executor.execute_next_feature_update_request(
            connection,  # type: ignore[arg-type]
            runner=object(),  # type: ignore[arg-type]
            dagster_run_id=owner,  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="trimmed non-empty"):
        await execute()


def _policy(
    *,
    provider_dataset_id: int = 11,
    provider: str = "python-a-api",
    dataset_key: str = "dataset-a",
    source_kind: str = "openapi",
    targeted_policy: str = "allow_targeted",
    enabled: bool = True,
) -> ProviderRefreshPolicy:
    now = datetime(2026, 8, 7, tzinfo=UTC)
    return ProviderRefreshPolicy(
        provider_dataset_id=provider_dataset_id,
        provider=provider,
        dataset_key=dataset_key,
        source_kind=source_kind,
        targeted_policy=targeted_policy,
        system_interval_seconds=3600,
        optimal_interval_seconds=1800,
        min_interval_seconds=300,
        max_requests_per_minute=10,
        max_requests_per_hour=100,
        max_requests_per_day=None,
        max_concurrent=2,
        burst_size=3,
        rate_limit_source={"doc": "unit"},
        config_source="unit",
        enabled=enabled,
        revision=1,
        created_at=now,
        updated_at=now,
    )


def _target() -> CacheTargetScopeTarget:
    return CacheTargetScopeTarget(
        target_id="target-1",
        external_system="external-app",
        target_key="poi-1",
        lon=127.0,
        lat=37.0,
        radius_km=3.0,
        scope_mode="center_radius",
        refresh_policy="normal",
        provider_overrides={
            "python-b-api": {"targeted_policy": "allow_targeted"},
            "python-z-api:dataset-z": {"targeted_policy": "disabled"},
        },
    )


def test_matched_scope_helpers_include_canonical_membership() -> None:
    match = CacheTargetFeatureMatch(
        target_id="target-1",
        feature_id="feature-1",
        provider_dataset_id=11,
        provider="python-a-api",
        dataset_key="dataset-a",
        distance_m=12.5,
        relation="within_radius",
    )
    refresh = ProviderDatasetRefreshScope(
        request_id="req-1",
        provider_dataset_id=11,
        sync_scope="dataset_wide",
        provider="python-a-api",
        dataset_key="dataset-a",
        scope_type="cache_target_keys",
        request_scope={
            "type": "cache_target_keys",
            "external_system": "external-app",
            "target_keys": [],
            "scope_mode": "center_radius",
        },
        update_policy={},
        feature_ids=("feature-1",),
        feature_count=1,
        prevent_provider_reactivation=True,
        operation_key="refresh_dataset_a",
        rate_limit={"max_requests_per_minute": 10},
        target_ids=("target-1",),
        target_matches=(match,),
    )
    result = ProviderDatasetRefreshResult(
        provider_dataset_id=11,
        sync_scope="dataset_wide",
        operation_key="refresh_dataset_a",
        provider="python-a-api",
        dataset_key="dataset-a",
        loaded_feature_ids=("feature-2",),
        loaded_count=1,
        metadata={"cursor": "abc"},
    )
    skipped = SkippedProviderDatasetRefresh(
        provider_dataset_id=12,
        sync_scope="dataset_wide",
        provider="python-b-api",
        dataset_key="dataset-b",
        reason="follow_system_skipped",
        feature_count=2,
        operation_key="refresh_dataset_b",
    )

    assert refresh.as_matched_scope()["provider_dataset_id"] == 11
    assert refresh.as_matched_scope()["target_ids"] == ["target-1"]
    assert refresh.as_matched_scope()["rate_limit"]["max_requests_per_minute"] == 10
    assert result.as_matched_scope()["loaded_feature_ids"] == ["feature-2"]
    assert result.as_matched_scope()["metadata"] == {"cursor": "abc"}
    assert skipped.as_matched_scope()["sync_scope"] == "dataset_wide"
    assert skipped.as_matched_scope()["reason"] == "follow_system_skipped"


def test_skip_reason_covers_policy_and_override_branches() -> None:
    resolution = ScopeResolution(
        scope_type="cache_target_keys",
        features=(FeatureScopeRow("feature-1", "11110"),),
        cache_targets=(_target(),),
    )

    assert (
        executor._skip_reason(
            request=_request(),
            provider="python-a-api",
            dataset_key="dataset-a",
            policy=_policy(enabled=False),
            resolution=resolution,
        )
        == "policy_disabled"
    )
    assert (
        executor._skip_reason(
            request=_request(),
            provider="python-z-api",
            dataset_key="dataset-z",
            policy=_policy(
                provider="python-z-api",
                dataset_key="dataset-z",
                targeted_policy="allow_targeted",
            ),
            resolution=resolution,
        )
        == "targeted_policy_disabled"
    )
    assert (
        executor._skip_reason(
            request=_request(),
            provider="python-a-api",
            dataset_key="dataset-a",
            policy=_policy(targeted_policy="follow_system"),
            resolution=resolution,
        )
        == "follow_system_skipped"
    )
    assert (
        executor._skip_reason(
            request=_request(),
            provider="python-b-api",
            dataset_key="dataset-b",
            policy=_policy(
                provider="python-b-api",
                dataset_key="dataset-b",
                targeted_policy="follow_system",
            ),
            resolution=resolution,
        )
        is None
    )


async def test_build_plan_uses_request_snapshot_after_catalog_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        scope={
            "type": "cache_target_keys",
            "external_system": "external-app",
            "target_keys": ["poi-1"],
            "scope_mode": "center_radius",
        },
        dataset_memberships=(
            _member(11, "python-a-api", "dataset-a"),
            _member(12, "python-b-api", "dataset-b"),
            _member(13, "python-c-api", "dataset-c"),
        ),
        update_policy={"prevent_provider_reactivation": False},
    )
    target_match = CacheTargetFeatureMatch(
        target_id="target-1",
        feature_id="feature-1",
        provider_dataset_id=11,
        provider="python-a-api",
        dataset_key="dataset-a",
        distance_m=10.0,
        relation="within_radius",
    )
    # 실행 시점 catalog에는 새 dataset만 남아도 request가 저장한 membership은 바뀌지 않는다.
    resolution = ScopeResolution(
        scope_type="cache_target_keys",
        features=(FeatureScopeRow("feature-1", "11110"),),
        provider_datasets=(
            ProviderDatasetScope(
                "python-new-api",
                "new-dataset",
                1,
                99,
                "dataset_wide",
                "refresh_new_dataset",
            ),
        ),
        sigungu_codes=("11110",),
        cache_targets=(_target(),),
        cache_target_matches=(target_match,),
        extra_matched_scope={"target_count": 1, "active_target_count": 1},
    )
    policies = {
        11: _policy(provider_dataset_id=11),
        12: _policy(
            provider_dataset_id=12,
            provider="python-b-api",
            dataset_key="dataset-b",
            targeted_policy="follow_system",
        ),
        13: _policy(
            provider_dataset_id=13,
            provider="python-c-api",
            dataset_key="dataset-c",
            enabled=False,
        ),
    }
    policy_lookups: list[int] = []

    async def fake_count(*_args: object, **_kwargs: object) -> ScopeResolution:
        return resolution

    async def fake_policy(
        _session: object, *, provider_dataset_id: int
    ) -> ProviderRefreshPolicy | None:
        policy_lookups.append(provider_dataset_id)
        return policies.get(provider_dataset_id)

    monkeypatch.setattr(executor, "count_features_matching_scope", fake_count)
    monkeypatch.setattr(executor, "get_provider_refresh_policy", fake_policy)

    plan = await build_feature_update_execution_plan(object(), request)

    assert [
        (scope.provider_dataset_id, scope.sync_scope)
        for scope in plan.refresh_scopes
    ] == [(11, "dataset_wide"), (12, "dataset_wide")]
    assert policy_lookups == [11, 12, 13]
    assert plan.refresh_scopes[0].target_ids == ("target-1",)
    assert plan.refresh_scopes[0].prevent_provider_reactivation is False
    assert plan.refresh_scopes[0].rate_limit["max_requests_per_hour"] == 100
    assert {
        (scope.provider_dataset_id, scope.sync_scope): scope.reason
        for scope in plan.skipped_scopes
    } == {(13, "dataset_wide"): "policy_disabled"}
    assert plan.matched_scope["target_count"] == 1
    assert len(plan.matched_scope["eligible_provider_scopes"]) == 2
    assert len(plan.matched_scope["skipped_provider_scopes"]) == 1


async def test_direct_plan_rebuilds_transient_read_scope_from_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        scope_type="provider_dataset",
        scope={
            "type": "provider_dataset",
            "provider_dataset_id": 11,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_test_dataset",
        },
        dataset_memberships=(_member(11, "python-a-api", "dataset-a"),),
    )
    resolution = ScopeResolution(
        scope_type="provider_dataset",
        features=(FeatureScopeRow("feature-1", "11110"),),
    )
    resolved_scopes: list[dict[str, object]] = []

    async def fake_count(
        _session: object,
        scope: dict[str, object],
        **_kwargs: object,
    ) -> ScopeResolution:
        resolved_scopes.append(scope)
        return resolution

    async def fake_policy(
        _session: object, *, provider_dataset_id: int
    ) -> ProviderRefreshPolicy | None:
        assert provider_dataset_id == 11
        return None

    monkeypatch.setattr(executor, "count_features_matching_scope", fake_count)
    monkeypatch.setattr(executor, "get_provider_refresh_policy", fake_policy)

    plan = await build_feature_update_execution_plan(object(), request)

    assert resolved_scopes == [
        {
            "type": "provider_dataset",
            "provider_dataset_id": 11,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_test_dataset",
        }
    ]
    assert len(plan.refresh_scopes) == 1
    assert plan.refresh_scopes[0].provider_dataset_id == 11
    assert plan.refresh_scopes[0].feature_count == 1
