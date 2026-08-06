"""``scope_repo`` DB 미접근 helper/dispatcher 단위 테스트."""

from __future__ import annotations

import pytest

from kortravelmap.infra import scope_repo
from kortravelmap.infra.scope_repo import (
    CacheTargetFeatureMatch,
    CacheTargetScopeTarget,
    FeatureScopeRow,
    ProviderDatasetScope,
    ScopeResolution,
    canonicalize_feature_update_scope,
    count_features_matching_scope,
    resolve_cache_target_keys,
    resolve_feature_ids,
    resolve_sigungu_by_radius,
)

pytestmark = pytest.mark.unit


def _row(**values: object) -> dict[str, object]:
    return values


def test_scope_resolution_matched_scope_includes_cache_target_payload() -> None:
    resolution = ScopeResolution(
        scope_type="cache_target_keys",
        features=(
            FeatureScopeRow("feature-1", "11110"),
            FeatureScopeRow("feature-2", "11140"),
        ),
        provider_datasets=(
            ProviderDatasetScope(
                "python-a-api",
                "dataset-a",
                2,
                17,
                "dataset_wide",
                "refresh_dataset_a",
            ),
        ),
        sigungu_codes=("11110", "11140"),
        extra_matched_scope={
            "target_count": 2,
            "active_target_count": 1,
            "skipped_missing_keys": ["missing"],
        },
    )

    matched = resolution.matched_scope()

    assert resolution.feature_ids == ("feature-1", "feature-2")
    assert matched["feature_count"] == 2
    assert matched["deduped_provider_scopes"] == [
        {
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_dataset_a",
            "provider": "python-a-api",
            "dataset_key": "dataset-a",
            "feature_count": 2,
        }
    ]
    assert matched["skipped_missing_keys"] == ["missing"]


def test_scope_helper_conversions_cover_json_rows_and_dedup() -> None:
    assert scope_repo._unique_preserve_order(["a", "", "b", "a"]) == ("a", "b")
    assert scope_repo._sigungu_codes(
        [
            FeatureScopeRow("feature-2", "11140"),
            FeatureScopeRow("feature-1", "11110"),
            FeatureScopeRow("feature-3", None),
        ]
    ) == ("11110", "11140")
    assert scope_repo._json_dict('{"a": 1}') == {"a": 1}
    assert scope_repo._json_dict(None) == {}
    assert scope_repo._rows_to_features(
        [
            _row(feature_id="feature-1", sigungu_code="11110"),
            _row(feature_id="feature-2", sigungu_code=None),
        ]
    ) == (
        FeatureScopeRow("feature-1", "11110"),
        FeatureScopeRow("feature-2", None),
    )

    target = scope_repo._row_to_cache_target(
        _row(
            target_id="target-1",
            external_system="external-app",
            target_key="poi-1",
            lon="127.0",
            lat="37.0",
            radius_km="3.5",
            scope_mode="center_radius",
            refresh_policy="normal",
            provider_overrides='{"python-a-api": {"targeted_policy": "disabled"}}',
        )
    )
    match = scope_repo._row_to_cache_match(
        _row(
            target_id="target-1",
            feature_id="feature-1",
            provider_dataset_id=17,
            provider="python-a-api",
            dataset_key="dataset-a",
            distance_m="12.5",
            relation="within_radius",
        )
    )

    assert target.radius_km == 3.5
    assert target.provider_overrides["python-a-api"]["targeted_policy"] == "disabled"
    assert match.distance_m == 12.5
    assert (
        scope_repo._row_to_cache_match(
            _row(
                target_id="target-1",
                feature_id="feature-2",
                provider_dataset_id=None,
                provider=None,
                dataset_key=None,
                distance_m=None,
                relation="same_sigungu",
            )
        ).distance_m
        is None
    )


def test_cache_target_match_helpers_preserve_first_feature_order() -> None:
    matches = (
        CacheTargetFeatureMatch(
            target_id="target-1",
            feature_id="feature-1",
            provider_dataset_id=17,
            provider="python-a-api",
            dataset_key="dataset-a",
            distance_m=10.0,
            relation="within_radius",
        ),
        CacheTargetFeatureMatch(
            target_id="target-2",
            feature_id="feature-1",
            provider_dataset_id=17,
            provider="python-a-api",
            dataset_key="dataset-a",
            distance_m=11.0,
            relation="within_radius",
        ),
        CacheTargetFeatureMatch(
            target_id="target-1",
            feature_id="feature-2",
            provider_dataset_id=18,
            provider="python-b-api",
            dataset_key="dataset-b",
            distance_m=None,
            relation="same_sigungu",
        ),
    )

    assert scope_repo._features_from_matches(
        matches,
        {"feature-1": "11110", "feature-2": "11140"},
    ) == (
        FeatureScopeRow("feature-1", "11110"),
        FeatureScopeRow("feature-2", "11140"),
    )


def test_effective_scope_mode_validates_mode() -> None:
    target = CacheTargetScopeTarget(
        target_id="target-1",
        external_system="external-app",
        target_key="poi-1",
        lon=127.0,
        lat=37.0,
        radius_km=3.0,
        scope_mode="sigungu_by_radius",
        refresh_policy="normal",
        provider_overrides={},
    )

    assert scope_repo._effective_scope_mode(target, None) == "sigungu_by_radius"
    assert scope_repo._effective_scope_mode(target, "center_radius") == "center_radius"
    with pytest.raises(ValueError, match="scope_mode must be"):
        scope_repo._effective_scope_mode(target, "unknown")


async def test_empty_or_invalid_public_resolvers_skip_db() -> None:
    assert (await resolve_feature_ids(object(), [])).matched_scope() == {
        "feature_count": 0,
        "sigungu_codes": [],
    }
    assert await scope_repo._provider_datasets_for_feature_ids(object(), []) == ()

    with pytest.raises(ValueError, match="requires external_system"):
        await resolve_cache_target_keys(object(), external_system="", target_keys=["poi-1"])
    with pytest.raises(ValueError, match="radius_km must be greater than 0"):
        await resolve_cache_target_keys(
            object(), external_system="external-app", target_keys=["poi-1"], radius_km=0
        )
    empty_cache = await resolve_cache_target_keys(
        object(), external_system="external-app", target_keys=[]
    )
    assert empty_cache.matched_scope()["target_count"] == 0

    async def empty_sigungu(**_kwargs: object) -> tuple[str, ...]:
        return ()

    empty_sigungu_result = await resolve_sigungu_by_radius(
        object(), lon=127.0, lat=37.0, radius_km=1.0, sigungu_resolver=empty_sigungu
    )
    assert empty_sigungu_result.feature_count == 0


async def test_count_features_matching_scope_dispatches_to_resolvers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeExecuteResult:
        def mappings(self) -> FakeExecuteResult:
            return self

        def all(self) -> list[dict[str, object]]:
            return [{"feature_id": "feature-sigungu", "sigungu_code": "11110"}]

        def one_or_none(self) -> dict[str, object]:
            return {
                "provider_dataset_id": 17,
                "sync_scope": "dataset_wide",
                "operation_key": "refresh_dataset_a",
                "provider": "python-a-api",
                "dataset_key": "dataset-a",
            }

    class FakeSession:
        async def execute(self, *_args: object, **_kwargs: object) -> FakeExecuteResult:
            calls.append(("execute_preview", {}))
            return FakeExecuteResult()

    def result(scope_type: str) -> ScopeResolution:
        return ScopeResolution(scope_type=scope_type, features=())

    async def fake_count(session: object, sql: str, params: dict[str, object]) -> int:
        calls.append(("count", {"session": session, "sql": sql, "params": params}))
        return 3

    async def fake_provider_datasets(
        session: object, sql: str, params: dict[str, object]
    ) -> tuple[ProviderDatasetScope, ...]:
        calls.append(("provider_datasets", {"session": session, "sql": sql, "params": params}))
        return (
            ProviderDatasetScope(
                "python-a-api",
                "dataset-a",
                3,
                17,
                "dataset_wide",
                "refresh_dataset_a",
            ),
        )

    async def fake_provider_datasets_for_ids(
        session: object, feature_ids: list[str] | tuple[str, ...]
    ) -> tuple[ProviderDatasetScope, ...]:
        calls.append(
            (
                "provider_datasets_for_ids",
                {"session": session, "feature_ids": tuple(feature_ids)},
            )
        )
        return (
            ProviderDatasetScope(
                "python-a-api",
                "dataset-a",
                2,
                17,
                "dataset_wide",
                "refresh_dataset_a",
            ),
        )

    async def fake_sigungu_codes(
        session: object, sql: str, params: dict[str, object]
    ) -> tuple[str, ...]:
        calls.append(("sigungu_codes", {"session": session, "sql": sql, "params": params}))
        return ("11110",)

    async def fake_feature_ids(
        session: object,
        feature_ids: list[str] | tuple[str, ...],
        *,
        limit: int,
    ) -> ScopeResolution:
        calls.append(
            (
                "feature_ids",
                {"session": session, "feature_ids": tuple(feature_ids), "limit": limit},
            )
        )
        return result("feature_ids")

    async def fake_center_radius(
        session: object, *, lon: float, lat: float, radius_km: float, limit: int
    ) -> ScopeResolution:
        calls.append(
            (
                "center_radius",
                {
                    "session": session,
                    "lon": lon,
                    "lat": lat,
                    "radius_km": radius_km,
                    "limit": limit,
                },
            )
        )
        return result("center_radius")

    async def fake_bbox(
        session: object,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        limit: int,
    ) -> ScopeResolution:
        calls.append(
            (
                "bbox",
                {
                    "session": session,
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                    "limit": limit,
                },
            )
        )
        return result("bbox")

    async def fake_provider_dataset(
        session: object,
        *,
        provider_dataset_id: int,
        sync_scope: str,
        operation_key: str,
        limit: int,
    ) -> ScopeResolution:
        calls.append(
            (
                "provider_dataset",
                {
                    "session": session,
                    "provider_dataset_id": provider_dataset_id,
                    "sync_scope": sync_scope,
                    "operation_key": operation_key,
                    "limit": limit,
                },
            )
        )
        return result("provider_dataset")

    async def fake_cache_target_keys(
        session: object,
        *,
        external_system: str,
        target_keys: list[str],
        radius_km: float | None,
        scope_mode: str | None,
        sigungu_resolver: object,
    ) -> ScopeResolution:
        calls.append(
            (
                "cache_target_keys",
                {
                    "session": session,
                    "external_system": external_system,
                    "target_keys": target_keys,
                    "radius_km": radius_km,
                    "scope_mode": scope_mode,
                    "sigungu_resolver": sigungu_resolver,
                },
            )
        )
        return result("cache_target_keys")

    monkeypatch.setattr(scope_repo, "_count_scalar", fake_count)
    monkeypatch.setattr(scope_repo, "_provider_datasets_from_sql", fake_provider_datasets)
    monkeypatch.setattr(
        scope_repo,
        "_provider_datasets_for_feature_ids",
        fake_provider_datasets_for_ids,
    )
    monkeypatch.setattr(scope_repo, "_sigungu_codes_from_sql", fake_sigungu_codes)
    monkeypatch.setattr(scope_repo, "resolve_feature_ids", fake_feature_ids)
    monkeypatch.setattr(scope_repo, "resolve_center_radius", fake_center_radius)
    monkeypatch.setattr(scope_repo, "resolve_bbox", fake_bbox)
    monkeypatch.setattr(scope_repo, "resolve_provider_dataset", fake_provider_dataset)
    monkeypatch.setattr(scope_repo, "resolve_cache_target_keys", fake_cache_target_keys)

    session = FakeSession()

    async def resolver(**_kwargs: object) -> tuple[str, ...]:
        return ("11110", "11110")

    scopes = [
        {"type": "feature_ids", "feature_ids": ["one", "two"]},
        {"type": "center_radius", "center": {"lon": 127.0, "lat": 37.0}, "radius_km": 3},
        {
            "type": "bbox",
            "min_lon": 126.0,
            "min_lat": 36.0,
            "max_lon": 128.0,
            "max_lat": 38.0,
        },
        {
            "type": "provider_dataset",
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_dataset_a",
        },
        {
            "type": "cache_target_keys",
            "external_system": "external-app",
            "target_keys": ["poi-1", "poi-2"],
            "radius_km": 4,
            "scope_mode": "sigungu_by_radius",
        },
        {
            "type": "sigungu_by_radius",
            "center": {"lon": 127.0, "lat": 37.0},
            "radius_km": 5,
        },
    ]

    for scope in scopes:
        await count_features_matching_scope(session, scope, sigungu_resolver=resolver)

    call_names = [name for name, _payload in calls]
    assert call_names.count("count") == 5
    assert call_names.count("sigungu_codes") == 5
    assert "provider_datasets_for_ids" in call_names
    assert "execute_preview" in call_names
    feature_id_payload = next(payload for name, payload in calls if name == "feature_ids")
    assert feature_id_payload["feature_ids"] == ("one", "two")
    assert feature_id_payload["limit"] == scope_repo.DEFAULT_SCOPE_PREVIEW_LIMIT
    preview_calls = {
        name: payload
        for name, payload in calls
        if name in {"center_radius", "bbox", "provider_dataset"}
    }
    assert preview_calls["center_radius"]["limit"] == scope_repo.DEFAULT_SCOPE_PREVIEW_LIMIT
    assert preview_calls["bbox"]["limit"] == scope_repo.DEFAULT_SCOPE_PREVIEW_LIMIT
    assert preview_calls["provider_dataset"]["limit"] == scope_repo.DEFAULT_SCOPE_PREVIEW_LIMIT
    assert any(
        name == "cache_target_keys" and payload["target_keys"] == ["poi-1", "poi-2"]
        for name, payload in calls
    )


async def test_count_features_matching_scope_validation_errors() -> None:
    with pytest.raises(ValueError, match="feature_ids must be an array"):
        await count_features_matching_scope(object(), {"type": "feature_ids", "feature_ids": "x"})
    with pytest.raises(ValueError, match="missing required keys"):
        await count_features_matching_scope(object(), {"type": "center_radius"})
    with pytest.raises(ValueError, match="missing required keys"):
        await count_features_matching_scope(
            object(), {"type": "cache_target_keys", "target_keys": "poi"}
        )
    with pytest.raises(ValueError, match="sigungu_by_radius scope requires sigungu_resolver"):
        await count_features_matching_scope(
            object(),
            {"type": "sigungu_by_radius", "center": {"lon": 127, "lat": 37}, "radius_km": 1},
        )
    with pytest.raises(ValueError, match="missing required keys"):
        await count_features_matching_scope(
            object(),
            {"type": "sigungu_by_radius", "radius_km": 1},
            sigungu_resolver=lambda **_kwargs: (),
        )
    with pytest.raises(ValueError, match="unsupported scope type"):
        await count_features_matching_scope(object(), {"type": "unknown"})


def test_canonicalize_feature_update_scope_materializes_defaults_and_strips_generic_text() -> None:
    assert canonicalize_feature_update_scope(
        {
            "type": "sigungu_by_radius",
            "center": {"lon": 127, "lat": 37},
            "radius_km": 5,
        }
    ) == {
        "type": "sigungu_by_radius",
        "center": {"lon": 127.0, "lat": 37.0},
        "radius_km": 5.0,
        "match": "intersects",
    }
    assert canonicalize_feature_update_scope(
        {
            "type": "provider_dataset",
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_dataset_a",
        }
    ) == {
        "type": "provider_dataset",
        "provider_dataset_id": 17,
        "sync_scope": "dataset_wide",
        "operation_key": "refresh_dataset_a",
    }
    assert canonicalize_feature_update_scope(
        {
            "type": "cache_target_keys",
            "external_system": "pinvi",
            "target_keys": ["poi-1"],
            "radius_km": None,
        }
    ) == {
        "type": "cache_target_keys",
        "external_system": "pinvi",
        "target_keys": ["poi-1"],
        "scope_mode": "center_radius",
    }


@pytest.mark.parametrize(
    "scope",
    [
        {"type": "feature_ids", "feature_ids": [1]},
        {"type": "feature_ids", "feature_ids": ["\t"]},
        {"type": "feature_ids", "feature_ids": ["a", "a"]},
        {
            "type": "center_radius",
            "center": {"lon": 181, "lat": 37},
            "radius_km": 1,
        },
        {
            "type": "sigungu_by_radius",
            "center": {"lon": 127, "lat": 37},
            "radius_km": 1,
            "match": "contains_center",
        },
        {
            "type": "bbox",
            "min_lon": 128,
            "min_lat": 37,
            "max_lon": 127,
            "max_lat": 38,
        },
        {
            "type": "provider_dataset",
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_dataset_a",
            "extra": True,
        },
        {
            "type": "cache_target_keys",
            "external_system": "pinvi",
            "target_keys": [],
            "radius_km": 501,
        },
        {
            "type": "cache_target_keys",
            "external_system": "pinvi",
            "target_keys": ["poi-1", "poi-1"],
        },
        {
            "type": "cache_target_keys",
            "external_system": " pinvi ",
            "target_keys": ["poi-1"],
        },
        {
            "type": "cache_target_keys",
            "external_system": "pinvi",
            "target_keys": ["poi:e\u0301"],
        },
        {
            "type": "cache_target_keys",
            "external_system": "pinvi",
            "target_keys": ["x" * 513],
        },
        {
            "type": "center_radius",
            "center": {"lon": 10**1000, "lat": 37},
            "radius_km": 1,
        },
    ],
)
def test_canonicalize_feature_update_scope_rejects_noncanonical_contract(
    scope: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="must|unsupported|bbox|이어야|NFC|문자열"):
        canonicalize_feature_update_scope(scope)


def test_cache_target_scope_accepts_full_root_identity_length() -> None:
    target_key = "x" * 512

    assert canonicalize_feature_update_scope(
        {
            "type": "cache_target_keys",
            "external_system": "pinvi",
            "target_keys": [target_key],
        }
    )["target_keys"] == [target_key]
