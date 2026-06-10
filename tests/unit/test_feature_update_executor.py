"""``feature_update_executor`` 순수 planning/helper 경로 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from krtour.map.infra import feature_update_executor as executor
from krtour.map.infra.feature_update_executor import (
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
    SkippedProviderDatasetRefresh,
    build_feature_update_execution_plan,
)
from krtour.map.infra.feature_update_repo import FeatureUpdateRequest
from krtour.map.infra.provider_refresh_policy_repo import ProviderRefreshPolicy
from krtour.map.infra.scope_repo import (
    CacheTargetFeatureMatch,
    CacheTargetScopeTarget,
    FeatureScopeRow,
    ProviderDatasetScope,
    ScopeResolution,
)

pytestmark = pytest.mark.unit


def _request(
    *,
    scope_type: str = "cache_target_keys",
    scope: dict[str, object] | None = None,
    providers: tuple[str, ...] = (),
    dataset_keys: tuple[str, ...] = (),
    update_policy: dict[str, object] | None = None,
) -> FeatureUpdateRequest:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return FeatureUpdateRequest(
        request_id="req-1",
        scope_type=scope_type,
        scope=scope or {"type": scope_type},
        providers=providers,
        dataset_keys=dataset_keys,
        update_policy=update_policy or {},
        run_mode="queued",
        priority=100,
        status="queued",
        dry_run=False,
        matched_scope={},
        job_id="job-1",
        dagster_run_id=None,
        operator="tester",
        reason="unit",
        error_message=None,
        created_at=now,
        started_at=None,
        finished_at=None,
        updated_at=now,
    )


def _policy(
    *,
    provider: str = "python-a-api",
    dataset_key: str = "dataset-a",
    source_kind: str = "openapi",
    targeted_policy: str = "allow_targeted",
    enabled: bool = True,
) -> ProviderRefreshPolicy:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    return ProviderRefreshPolicy(
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
        created_at=now,
        updated_at=now,
    )


def _target() -> CacheTargetScopeTarget:
    return CacheTargetScopeTarget(
        target_id="target-1",
        external_system="tripmate",
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


def test_matched_scope_helpers_include_optional_payloads() -> None:
    match = CacheTargetFeatureMatch(
        target_id="target-1",
        feature_id="feature-1",
        provider="python-a-api",
        dataset_key="dataset-a",
        distance_m=12.5,
        relation="within_radius",
    )
    refresh = ProviderDatasetRefreshScope(
        request_id="req-1",
        provider="python-a-api",
        dataset_key="dataset-a",
        scope_type="cache_target_keys",
        request_scope={"type": "cache_target_keys"},
        update_policy={},
        feature_ids=("feature-1",),
        feature_count=1,
        prevent_provider_reactivation=True,
        rate_limit={"max_requests_per_minute": 10},
        target_ids=("target-1",),
        target_matches=(match,),
    )
    result = ProviderDatasetRefreshResult(
        provider="python-a-api",
        dataset_key="dataset-a",
        loaded_feature_ids=("feature-2",),
        loaded_count=1,
        metadata={"cursor": "abc"},
    )
    skipped = SkippedProviderDatasetRefresh(
        provider="python-b-api",
        dataset_key="dataset-b",
        reason="follow_system_skipped",
        feature_count=2,
    )

    assert refresh.as_matched_scope()["target_ids"] == ["target-1"]
    assert refresh.as_matched_scope()["rate_limit"]["max_requests_per_minute"] == 10
    assert result.as_matched_scope()["loaded_feature_ids"] == ["feature-2"]
    assert result.as_matched_scope()["metadata"] == {"cursor": "abc"}
    assert skipped.as_matched_scope()["reason"] == "follow_system_skipped"


def test_skip_reason_covers_policy_and_filter_branches() -> None:
    resolution = ScopeResolution(
        scope_type="cache_target_keys",
        features=(FeatureScopeRow("feature-1", "11110"),),
        cache_targets=(_target(),),
    )

    assert (
        executor._skip_reason(
            request=_request(providers=("python-a-api",)),
            provider="python-x-api",
            dataset_key="dataset-a",
            policy=None,
            resolution=resolution,
        )
        == "provider_filter"
    )
    assert (
        executor._skip_reason(
            request=_request(dataset_keys=("dataset-a",)),
            provider="python-a-api",
            dataset_key="dataset-x",
            policy=None,
            resolution=resolution,
        )
        == "dataset_filter"
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
            provider="python-a-api",
            dataset_key="dataset-a",
            policy=_policy(source_kind="filedata", targeted_policy="disabled"),
            resolution=ScopeResolution(
                scope_type="cache_target_keys",
                features=(FeatureScopeRow("feature-1", "11110"),),
            ),
        )
        == "targeted_policy_disabled"
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


async def test_build_plan_applies_filters_overrides_and_rate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        scope={"type": "cache_target_keys", "external_system": "tripmate"},
        providers=(
            "python-a-api",
            "python-b-api",
            "python-c-api",
            "python-d-api",
        ),
        dataset_keys=("dataset-a", "dataset-b", "dataset-c"),
        update_policy={"prevent_provider_reactivation": False},
    )
    target_match = CacheTargetFeatureMatch(
        target_id="target-1",
        feature_id="feature-1",
        provider="python-a-api",
        dataset_key="dataset-a",
        distance_m=10.0,
        relation="within_radius",
    )
    resolution = ScopeResolution(
        scope_type="cache_target_keys",
        features=(
            FeatureScopeRow("feature-1", "11110"),
            FeatureScopeRow("feature-2", "11110"),
        ),
        provider_datasets=(
            ProviderDatasetScope("python-a-api", "dataset-a", 1),
            ProviderDatasetScope("python-b-api", "dataset-b", 1),
            ProviderDatasetScope("python-c-api", "dataset-c", 1),
            ProviderDatasetScope("python-d-api", "dataset-d", 1),
            ProviderDatasetScope("python-e-api", "dataset-e", 1),
        ),
        sigungu_codes=("11110",),
        cache_targets=(_target(),),
        cache_target_matches=(target_match, target_match),
        extra_matched_scope={"target_count": 1, "active_target_count": 1},
    )
    policies = {
        ("python-a-api", "dataset-a"): _policy(),
        ("python-b-api", "dataset-b"): _policy(
            provider="python-b-api",
            dataset_key="dataset-b",
            targeted_policy="follow_system",
        ),
        ("python-c-api", "dataset-c"): _policy(
            provider="python-c-api",
            dataset_key="dataset-c",
            enabled=False,
        ),
    }

    async def fake_count(*_args: object, **_kwargs: object) -> ScopeResolution:
        return resolution

    async def fake_policy(
        _session: object, *, provider: str, dataset_key: str
    ) -> ProviderRefreshPolicy | None:
        return policies.get((provider, dataset_key))

    monkeypatch.setattr(executor, "count_features_matching_scope", fake_count)
    monkeypatch.setattr(executor, "get_provider_refresh_policy", fake_policy)

    plan = await build_feature_update_execution_plan(object(), request)

    assert [(s.provider, s.dataset_key) for s in plan.refresh_scopes] == [
        ("python-a-api", "dataset-a"),
        ("python-b-api", "dataset-b"),
    ]
    assert plan.refresh_scopes[0].target_ids == ("target-1",)
    assert plan.refresh_scopes[0].prevent_provider_reactivation is False
    assert plan.refresh_scopes[0].rate_limit["max_requests_per_hour"] == 100
    assert {
        (s.provider, s.dataset_key): s.reason for s in plan.skipped_scopes
    } == {
        ("python-c-api", "dataset-c"): "policy_disabled",
        ("python-d-api", "dataset-d"): "dataset_filter",
        ("python-e-api", "dataset-e"): "provider_filter",
    }
    assert plan.matched_scope["target_count"] == 1
    assert len(plan.matched_scope["eligible_provider_scopes"]) == 2
    assert len(plan.matched_scope["skipped_provider_scopes"]) == 3


async def test_build_plan_adds_provider_dataset_scope_when_resolution_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        scope_type="provider_dataset",
        scope={
            "type": "provider_dataset",
            "provider": "python-a-api",
            "dataset_key": "dataset-a",
        },
    )
    resolution = ScopeResolution(
        scope_type="provider_dataset",
        features=(FeatureScopeRow("feature-1", "11110"),),
    )

    async def fake_count(*_args: object, **_kwargs: object) -> ScopeResolution:
        return resolution

    async def fake_policy(
        _session: object, *, provider: str, dataset_key: str
    ) -> ProviderRefreshPolicy | None:
        return None

    monkeypatch.setattr(executor, "count_features_matching_scope", fake_count)
    monkeypatch.setattr(executor, "get_provider_refresh_policy", fake_policy)

    plan = await build_feature_update_execution_plan(object(), request)

    assert len(plan.refresh_scopes) == 1
    assert plan.refresh_scopes[0].provider == "python-a-api"
    assert plan.refresh_scopes[0].dataset_key == "dataset-a"
    assert plan.refresh_scopes[0].feature_count == 1
