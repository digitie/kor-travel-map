"""public Feature asset operation guard/tracking 회귀."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from dagster import DagsterInstance, Definitions, asset, define_asset_job, resource
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.feature_operation import ProviderDatasetOperationKey
from kortravelmap.providers.datagokr_file_data import DATAGOKR_FILEDATA_DATASETS
from kortravelmap.providers.feature_operation_registry import (
    FEATURE_OPERATION_REGISTRY_VERSION_TAG,
    FeatureOperationRegistryError,
    feature_operation_definition_tags,
    resolve_feature_operation_identity,
    resolve_feature_operation_launch,
    resolve_feature_operation_runtime_snapshot,
)
from kortravelmap.providers.knps import KNPS_PLACE_DATASETS

from kortravelmap.dagster import feature_operation_tracking as tracking_module
from kortravelmap.dagster.definitions import _settings_value_resource
from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionBlocked,
    FeatureOperationExecutionGuard,
    FeatureOperationGuardUnavailable,
    _guard_from_context,
    ensure_tracked_multi_pair_asset,
    feature_operation_guard_resource,
    run_tracked_feature_asset,
)
from kortravelmap.dagster.resources import (
    _KNPS_POINT_RECORDS_SPEC,
    PROVIDER_RECORD_RESOURCE_DEFINITIONS,
    ProviderRecordResourceSpec,
    _build_knps_record_resource,
    build_provider_record_live_resource,
    datagokr_file_data_dataset_key_resource,
    kma_datagokr_client_resource,
    kma_weather_client_factory_resource,
)


class _AssetKey:
    def __init__(self, value: str) -> None:
        self.value = value

    def to_user_string(self) -> str:
        return self.value


class _Client:
    def __init__(self, *, blocked: bool = False) -> None:
        self.blocked = blocked
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def ensure_dagster_feature_operation(self, **kwargs: Any) -> Any:
        self.calls.append(("ensure", kwargs))
        return SimpleNamespace(
            outcome="blocked" if self.blocked else "applied",
            block_reason="cancellation" if self.blocked else None,
        )

    async def finish_dagster_feature_pair(self, **kwargs: Any) -> Any:
        self.calls.append(("finish", kwargs))
        return SimpleNamespace(outcome="applied", block_reason=None)

    async def append_dagster_feature_attempt_event(self, **kwargs: Any) -> Any:
        self.calls.append(("attempt", kwargs))
        return object()

    async def load_feature_bundles(self, bundles: object) -> None:
        self.calls.append(("load", {"bundles": bundles}))

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> int:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        return len(self.recorded_findings)


class _Log:
    def __init__(self) -> None:
        self.errors: list[tuple[object, ...]] = []

    def error(self, _message: str, *args: object) -> None:
        self.errors.append(args)

    def info(self, _message: str, *args: object) -> None:
        return None


class _RunRecordInstance:
    def __init__(
        self,
        run: Any,
        *,
        statuses: tuple[str, ...] = ("STARTED",),
        missing: bool = False,
    ) -> None:
        self.run = run
        self.statuses = statuses
        self.missing = missing
        self.calls = 0

    def get_run_record_by_id(self, _run_id: str) -> Any | None:
        if self.missing:
            return None
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        authoritative_run = SimpleNamespace(
            **{
                **vars(self.run),
                "status": SimpleNamespace(value=status),
            }
        )
        started_at = (
            datetime(2026, 7, 16, 1, 1, tzinfo=UTC).timestamp()
            if status != "STARTING"
            else None
        )
        return SimpleNamespace(
            dagster_run=authoritative_run,
            create_timestamp=datetime(2026, 7, 16, 1, 0, tzinfo=UTC),
            start_time=started_at,
        )


def _identity(job_name: str = "feature_place_mois_licenses_job") -> Any:
    identity = resolve_feature_operation_identity(job_name=job_name)
    assert identity is not None
    return identity


def _run_for_identity(
    identity: Any,
    *,
    run_id: str = "run-1",
    job_name: str | None = None,
    run_config: dict[str, object] | None = None,
    tags: dict[str, str] | None = None,
) -> Any:
    return SimpleNamespace(
        job_name=job_name or identity.job_name,
        run_id=run_id,
        run_config=run_config or {},
        tags=tags or feature_operation_definition_tags(identity),
        asset_selection=None,
        resolved_op_selection=None,
        status=SimpleNamespace(value="STARTED"),
    )


def _guard(client: _Client, *, blocked: bool = False) -> FeatureOperationExecutionGuard:
    identity = _identity()
    client.blocked = blocked
    run = _run_for_identity(identity)
    return FeatureOperationExecutionGuard(
        client=cast(AsyncKorTravelMapClient, client),
        instance=_RunRecordInstance(run),
        identity=identity,
        dagster_run_id="run-1",
        trigger_kind="manual",
    )


def _panel_guard(client: _Client | None = None) -> FeatureOperationExecutionGuard:
    return FeatureOperationExecutionGuard(
        client=cast(AsyncKorTravelMapClient, client or _Client()),
        instance=object(),
        identity=None,
        dagster_run_id="panel-run",
        trigger_kind=None,
    )


def _asset_context(
    guard: FeatureOperationExecutionGuard,
    *,
    retry_number: int = 0,
) -> Any:
    identity = cast(Any, guard.identity)
    return SimpleNamespace(
        resources=SimpleNamespace(
            feature_operation_guard=guard,
            kor_travel_map_client=guard.client,
        ),
        instance=guard.instance,
        run=getattr(guard.instance, "run", None),
        run_id=guard.dagster_run_id,
        selected_asset_keys={_AssetKey(identity.asset_keys[0])},
        asset_key=_AssetKey(identity.asset_keys[0]),
        job_name=identity.job_name,
        retry_number=retry_number,
    )


def _resource_context(
    *,
    tags: dict[str, str],
    identity: Any | None = None,
    run_config: dict[str, object] | None = None,
    record_statuses: tuple[str, ...] = ("STARTED",),
) -> Any:
    identity = identity or _identity()
    run = SimpleNamespace(
        job_name=identity.job_name,
        run_id="run-1",
        run_config=run_config or {},
        tags=tags,
        asset_selection=None,
        resolved_op_selection=None,
        status=SimpleNamespace(value="STARTING"),
    )
    return SimpleNamespace(
        run=run,
        resources=SimpleNamespace(kor_travel_map_client=_Client()),
        instance=_RunRecordInstance(run, statuses=record_statuses),
        log=_Log(),
    )


def test_context_run_id_prefers_run_without_deprecated_property_access() -> None:
    class _Context:
        run = SimpleNamespace(run_id="authoritative-run")

        @property
        def run_id(self) -> str:
            raise AssertionError("deprecated context.run_id must not be accessed")

    assert tracking_module._context_run_id(_Context()) == "authoritative-run"


@pytest.mark.parametrize("asset_selection", [None, frozenset()])
@pytest.mark.parametrize("resolved_op_selection", [None, frozenset()])
def test_empty_dagster_selection_matrix_recovers_registered_full_selection(
    asset_selection: object,
    resolved_op_selection: object,
) -> None:
    identity = _identity()
    context = _resource_context(tags=feature_operation_definition_tags(identity))
    context.run.asset_selection = asset_selection
    context.run.resolved_op_selection = resolved_op_selection
    context.instance.run = context.run

    guard = _guard_from_context(cast(Any, context))

    assert guard.identity == identity
    assert cast(_Client, context.resources.kor_travel_map_client).calls == []


@pytest.mark.parametrize("pair_shape", ["subset", "extra"])
def test_mcst_pair_shape_drift_fails_guard_before_ensure(pair_shape: str) -> None:
    identity = _identity("feature_place_mcst_culture_job")
    pairs = (
        identity.pairs[:-1]
        if pair_shape == "subset"
        else (
            *identity.pairs,
            ProviderDatasetOperationKey("forged-provider", "forged-dataset"),
        )
    )
    forged_identity = replace(identity, pairs=pairs)
    context = _resource_context(
        identity=identity,
        tags=feature_operation_definition_tags(forged_identity),
    )

    with pytest.raises(FeatureOperationRegistryError):
        _guard_from_context(cast(Any, context))

    assert cast(_Client, context.resources.kor_travel_map_client).calls == []


async def test_guard_refreshes_authoritative_run_record_for_every_ensure() -> None:
    identity = _identity()
    context = _resource_context(
        tags=feature_operation_definition_tags(identity),
        record_statuses=("STARTING", "STARTED", "STARTED"),
    )

    guard = _guard_from_context(cast(Any, context))
    await guard.ensure()
    await guard.ensure()

    assert guard.identity == identity
    assert guard.trigger_kind == "manual"
    assert context.instance.calls == 3
    client = cast(_Client, context.resources.kor_travel_map_client)
    ensure_calls = [kwargs for name, kwargs in client.calls if name == "ensure"]
    assert [kwargs["observed_status"] for kwargs in ensure_calls] == [
        "STARTED",
        "STARTED",
    ]
    assert all(
        kwargs["engine_created_at"]
        == datetime(2026, 7, 16, 1, 0, tzinfo=UTC)
        for kwargs in ensure_calls
    )
    assert all(
        kwargs["engine_started_at"]
        == datetime(2026, 7, 16, 1, 1, tzinfo=UTC)
        for kwargs in ensure_calls
    )


async def test_guard_rejects_naive_run_record_timestamp_before_db_ensure() -> None:
    identity = _identity()
    run = _run_for_identity(identity)
    client = _Client()

    class _NaiveTimestampInstance:
        def get_run_record_by_id(self, _run_id: str) -> object:
            return SimpleNamespace(
                dagster_run=run,
                create_timestamp=datetime(2026, 7, 16, 1, 0),
                start_time=None,
            )

    guard = FeatureOperationExecutionGuard(
        client=cast(AsyncKorTravelMapClient, client),
        instance=_NaiveTimestampInstance(),
        identity=identity,
        dagster_run_id=run.run_id,
        trigger_kind="manual",
    )

    with pytest.raises(FeatureOperationGuardUnavailable) as raised:
        await guard.ensure()

    assert raised.value.boundary == "run_record"
    assert raised.value.reason == "naive_timestamp"
    assert client.calls == []


def test_aware_run_record_timestamp_is_normalized_to_utc() -> None:
    value = tracking_module._aware_datetime(
        datetime.fromisoformat("2026-07-16T10:00:00+09:00")
    )

    assert value == datetime(2026, 7, 16, 1, 0, tzinfo=UTC)
    assert value.tzinfo is UTC


def test_guard_rejects_registry_version_skew_before_db_ensure() -> None:
    identity = _identity()
    tags = feature_operation_definition_tags(identity)
    tags[FEATURE_OPERATION_REGISTRY_VERSION_TAG] = "v1-stale-version"
    context = _resource_context(tags=tags)
    client = cast(_Client, context.resources.kor_travel_map_client)

    with pytest.raises(FeatureOperationRegistryError, match="registry version"):
        _guard_from_context(cast(Any, context))

    assert client.calls == []
    assert context.log.errors


@pytest.mark.parametrize(
    "job_name",
    [
        "feature_place_datagokr_seoul_bookstores_job",
        "feature_place_knps_points_job",
    ],
)
def test_dynamic_guard_materializes_canonical_defaults_for_direct_empty_config(
    job_name: str,
) -> None:
    launch = resolve_feature_operation_launch(
        job_name=job_name,
        runtime_snapshot=resolve_feature_operation_runtime_snapshot(),
    )
    assert launch is not None
    identity, _canonical_run_config = launch
    context = _resource_context(
        identity=identity,
        run_config={},
        tags=feature_operation_definition_tags(identity),
    )

    guard = _guard_from_context(cast(Any, context))

    assert guard.identity == identity


def test_dynamic_guard_preserves_unrelated_config_when_materializing_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_name = "feature_place_knps_points_job"
    launch = resolve_feature_operation_launch(
        job_name=job_name,
        runtime_snapshot=resolve_feature_operation_runtime_snapshot(),
    )
    assert launch is not None
    identity, _canonical_run_config = launch
    source_run_config: dict[str, object] = {
        "ops": {"feature_place_knps_points": {"config": {}}},
        "resources": {"unrelated": {"config": {"enabled": True}}},
    }
    context = _resource_context(
        identity=identity,
        run_config=source_run_config,
        tags=feature_operation_definition_tags(identity),
    )
    captured: dict[str, object] = {}
    validate = tracking_module.validate_feature_operation_identity

    def _capture_validate(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return validate(**kwargs)

    monkeypatch.setattr(
        tracking_module,
        "validate_feature_operation_identity",
        _capture_validate,
    )

    guard = _guard_from_context(cast(Any, context))

    assert guard.identity == identity
    effective = cast(dict[str, Any], captured["run_config"])
    assert effective["ops"] == source_run_config["ops"]
    assert effective["resources"]["unrelated"] == {
        "config": {"enabled": True}
    }
    for resource_name, resource_config in cast(
        dict[str, object], _canonical_run_config["resources"]
    ).items():
        assert effective["resources"][resource_name] == resource_config
    assert source_run_config == {
        "ops": {"feature_place_knps_points": {"config": {}}},
        "resources": {"unrelated": {"config": {"enabled": True}}},
    }


@pytest.mark.parametrize(
    ("job_name", "resource_name"),
    [
        (
            "feature_place_datagokr_seoul_bookstores_job",
            "datagokr_file_data_dataset_key",
        ),
        ("feature_place_knps_points_job", "knps_point_dataset_key"),
    ],
)
def test_dynamic_guard_rejects_one_side_override_before_db_ensure(
    job_name: str,
    resource_name: str,
) -> None:
    launch = resolve_feature_operation_launch(
        job_name=job_name,
        runtime_snapshot=resolve_feature_operation_runtime_snapshot(),
    )
    assert launch is not None
    identity, _canonical_run_config = launch
    context = _resource_context(
        identity=identity,
        run_config={
            "resources": {
                resource_name: {
                    "config": {"dataset_key": identity.pairs[0].dataset_key}
                }
            }
        },
        tags=feature_operation_definition_tags(identity),
    )

    with pytest.raises(FeatureOperationRegistryError, match="snapshot|fileData"):
        _guard_from_context(cast(Any, context))

    client = cast(_Client, context.resources.kor_travel_map_client)
    assert client.calls == []


@pytest.mark.parametrize(
    ("job_name", "resource_names", "wrong_dataset_key"),
    [
        (
            "feature_place_datagokr_seoul_bookstores_job",
            (
                "datagokr_file_data_dataset_key",
                "datagokr_file_data_records",
            ),
            next(
                key
                for key in DATAGOKR_FILEDATA_DATASETS
                if key != "datagokr_seoul_bookstores"
            ),
        ),
        (
            "feature_place_knps_points_job",
            ("knps_point_dataset_key", "knps_point_records"),
            next(key for key in KNPS_PLACE_DATASETS if key != "knps_visitor_centers"),
        ),
    ],
)
def test_dynamic_guard_rejects_wrong_two_side_override_before_db_ensure(
    job_name: str,
    resource_names: tuple[str, str],
    wrong_dataset_key: str,
) -> None:
    launch = resolve_feature_operation_launch(
        job_name=job_name,
        runtime_snapshot=resolve_feature_operation_runtime_snapshot(
            {
                "KOR_TRAVEL_MAP_KNPS_POINT_DATASET_KEY": "knps_visitor_centers",
                "KOR_TRAVEL_MAP_KNPS_GEOMETRY_DATASET_KEY": "knps_trails",
            }
        ),
    )
    assert launch is not None
    identity, _canonical_run_config = launch
    context = _resource_context(
        identity=identity,
        run_config={
            "resources": {
                name: {"config": {"dataset_key": wrong_dataset_key}}
                for name in resource_names
            }
        },
        tags=feature_operation_definition_tags(identity),
    )

    with pytest.raises(FeatureOperationRegistryError):
        _guard_from_context(cast(Any, context))

    client = cast(_Client, context.resources.kor_travel_map_client)
    assert client.calls == []


def test_resource_guard_ensures_full_selection_before_returning() -> None:
    identity = _identity()
    context = _resource_context(tags=feature_operation_definition_tags(identity))
    loop = asyncio.new_event_loop()
    context.event_loop = loop
    resource_fn = cast(Any, feature_operation_guard_resource.resource_fn)
    try:
        guard = resource_fn(context)
    finally:
        loop.close()

    client = cast(_Client, context.resources.kor_travel_map_client)
    assert guard.identity == identity
    assert [name for name, _kwargs in client.calls] == ["ensure"]
    assert client.calls[0][1]["selected_pairs"] == identity.pairs


def test_actual_definitions_marker_blocks_provider_factory_and_asset_child() -> None:
    identity = _identity()
    client = _Client(blocked=True)
    provider_fetch_calls = 0
    asset_child_calls = 0
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key=identity.pairs[0].dataset_key,
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal provider_fetch_calls
        provider_fetch_calls += 1
        return (object(),)

    @resource
    def _client_resource() -> object:
        return client

    @asset(
        name=identity.asset_keys[0],
        required_resource_keys={"provider_records"},
    )
    def _guarded_asset() -> None:
        nonlocal asset_child_calls
        asset_child_calls += 1

    job = define_asset_job(
        identity.job_name,
        selection=[_guarded_asset],
        tags=feature_operation_definition_tags(identity),
    )
    definitions = Definitions(
        assets=[_guarded_asset],
        jobs=[job],
        resources={
            "kor_travel_map_client": _client_resource,
            "feature_operation_guard": feature_operation_guard_resource,
            "provider_records": build_provider_record_live_resource(spec, _fetch),
        },
    )

    result = definitions.resolve_job_def(identity.job_name).execute_in_process(
        raise_on_error=False
    )

    assert result.success is False
    assert [name for name, _kwargs in client.calls] == ["ensure"]
    assert provider_fetch_calls == 0
    assert asset_child_calls == 0


def test_actual_definitions_default_guard_allows_production_shaped_success() -> None:
    identity = _identity()
    client = _Client()
    provider_fetch_calls = 0
    raw_calls = 0
    db_load_calls = 0
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key=identity.pairs[0].dataset_key,
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal provider_fetch_calls
        provider_fetch_calls += 1
        return (object(),)

    @resource
    def _client_resource() -> object:
        return client

    async def _raw(_context: object) -> None:
        nonlocal raw_calls, db_load_calls
        raw_calls += 1
        db_load_calls += 1

    @asset(
        name=identity.asset_keys[0],
        required_resource_keys={
            "feature_operation_guard",
            "kor_travel_map_client",
            "provider_records",
        },
    )
    async def _guarded_asset(context) -> None:  # type: ignore[no-untyped-def]
        await run_tracked_feature_asset(context, _raw)

    job = define_asset_job(
        identity.job_name,
        selection=[_guarded_asset],
        tags=feature_operation_definition_tags(identity),
    )
    definitions = Definitions(
        assets=[_guarded_asset],
        jobs=[job],
        resources={
            "kor_travel_map_client": _client_resource,
            "feature_operation_guard": feature_operation_guard_resource,
            "provider_records": build_provider_record_live_resource(spec, _fetch),
        },
    )

    result = definitions.resolve_job_def(identity.job_name).execute_in_process()

    assert result.success is True
    assert provider_fetch_calls == raw_calls == db_load_calls == 1
    assert [name for name, _kwargs in client.calls] == [
        "ensure",
        "ensure",
        "ensure",
        "finish",
    ]


def test_actual_knps_non_default_launch_uses_both_canonical_resource_configs() -> None:
    dataset_key = next(
        key for key in KNPS_PLACE_DATASETS if key != "knps_visitor_centers"
    )
    launch = resolve_feature_operation_launch(
        job_name="feature_place_knps_points_job",
        runtime_snapshot=resolve_feature_operation_runtime_snapshot(
            {
                "KOR_TRAVEL_MAP_KNPS_POINT_DATASET_KEY": dataset_key,
                "KOR_TRAVEL_MAP_KNPS_GEOMETRY_DATASET_KEY": "knps_trails",
            }
        ),
    )
    assert launch is not None
    identity, run_config = launch
    assert identity.pairs[0].dataset_key == dataset_key
    resource_config = cast(dict[str, Any], run_config["resources"])
    assert resource_config == {
        "knps_point_dataset_key": {"config": {"dataset_key": dataset_key}},
        "knps_point_records": {"config": {"dataset_key": dataset_key}},
    }

    class _IdempotentClient(_Client):
        def __init__(self) -> None:
            super().__init__()
            self.applied_ensure_calls = 0

        async def ensure_dagster_feature_operation(self, **kwargs: Any) -> Any:
            mutation = await super().ensure_dagster_feature_operation(**kwargs)
            if self.applied_ensure_calls == 0:
                self.applied_ensure_calls += 1
            else:
                mutation.outcome = "noop"
            return mutation

    client = _IdempotentClient()
    provider_fetch_calls = 0
    raw_calls = 0
    fetched_record = object()

    def _fetch(settings: object) -> tuple[object, ...]:
        nonlocal provider_fetch_calls
        provider_fetch_calls += 1
        assert cast(Any, settings).knps_point_dataset_key == dataset_key
        return (fetched_record,)

    @resource
    def _client_resource() -> object:
        return client

    async def _raw(context: Any) -> None:
        nonlocal raw_calls
        raw_calls += 1
        assert context.resources.knps_point_dataset_key == dataset_key
        records = tuple(context.resources.knps_point_records)
        assert records == (fetched_record,)
        await context.resources.kor_travel_map_client.load_feature_bundles(records)

    @asset(
        name=identity.asset_keys[0],
        required_resource_keys={
            "feature_operation_guard",
            "kor_travel_map_client",
            "knps_point_dataset_key",
            "knps_point_records",
        },
    )
    async def _guarded_asset(context) -> None:  # type: ignore[no-untyped-def]
        await run_tracked_feature_asset(context, _raw)

    job = define_asset_job(
        identity.job_name,
        selection=[_guarded_asset],
        tags=feature_operation_definition_tags(identity),
        config=run_config,
    )
    definitions = Definitions(
        assets=[_guarded_asset],
        jobs=[job],
        resources={
            "kor_travel_map_client": _client_resource,
            "feature_operation_guard": feature_operation_guard_resource,
            "knps_point_dataset_key": _settings_value_resource(
                "knps_point_dataset_key",
                "knps_point_dataset_key",
            ),
            "knps_point_records": _build_knps_record_resource(
                _KNPS_POINT_RECORDS_SPEC,
                _fetch,
                setting_name="knps_point_dataset_key",
                allowed_dataset_keys=frozenset(KNPS_PLACE_DATASETS),
            ),
        },
    )

    result = definitions.resolve_job_def(identity.job_name).execute_in_process(
        run_config=run_config
    )

    assert result.success is True
    assert provider_fetch_calls == raw_calls == 1
    assert client.applied_ensure_calls == 1
    assert [name for name, _kwargs in client.calls] == [
        "ensure",
        "ensure",
        "ensure",
        "load",
        "finish",
    ]


def test_actual_definitions_run_record_missing_has_zero_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    client = _Client()
    provider_fetch_calls = 0
    raw_calls = 0
    db_load_calls = 0
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key=identity.pairs[0].dataset_key,
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal provider_fetch_calls
        provider_fetch_calls += 1
        return (object(),)

    @resource
    def _client_resource() -> object:
        return client

    @resource(required_resource_keys={"kor_travel_map_client"})
    def _unensured_guard_resource(context) -> object:  # type: ignore[no-untyped-def]
        return FeatureOperationExecutionGuard(
            client=cast(
                AsyncKorTravelMapClient,
                context.resources.kor_travel_map_client,
            ),
            instance=context.instance,
            identity=identity,
            dagster_run_id=context.run.run_id,
            trigger_kind="manual",
        )

    def _missing_record(_instance: object, *, dagster_run_id: str) -> Any:
        raise RuntimeError(f"missing {dagster_run_id}")

    monkeypatch.setattr(tracking_module, "_run_record", _missing_record)

    @asset(
        name=identity.asset_keys[0],
        required_resource_keys={"provider_records"},
    )
    async def _guarded_asset() -> None:
        nonlocal raw_calls, db_load_calls
        raw_calls += 1
        db_load_calls += 1

    job = define_asset_job(
        identity.job_name,
        selection=[_guarded_asset],
        tags=feature_operation_definition_tags(identity),
    )
    definitions = Definitions(
        assets=[_guarded_asset],
        jobs=[job],
        resources={
            "kor_travel_map_client": _client_resource,
            "feature_operation_guard": _unensured_guard_resource,
            "provider_records": build_provider_record_live_resource(spec, _fetch),
        },
    )

    result = definitions.resolve_job_def(identity.job_name).execute_in_process(
        raise_on_error=False
    )

    assert result.success is False
    assert provider_fetch_calls == raw_calls == db_load_calls == 0
    assert client.calls == []


@pytest.mark.parametrize(
    ("guard_value", "reason"),
    [
        (None, "none"),
        (object(), "wrong_type"),
        (_panel_guard(), "registered_identity_missing"),
    ],
)
def test_actual_definitions_invalid_guard_blocks_provider_raw_and_db_load(
    guard_value: object,
    reason: str,
) -> None:
    identity = _identity()
    provider_fetch_calls = 0
    raw_calls = 0
    db_load_calls = 0
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key=identity.pairs[0].dataset_key,
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal provider_fetch_calls
        provider_fetch_calls += 1
        return (object(),)

    class _LoadClient:
        async def load_feature_bundles(self, _bundles: object) -> None:
            nonlocal db_load_calls
            db_load_calls += 1

    @resource
    def _load_client_resource() -> object:
        return _LoadClient()

    @resource
    def _invalid_guard_resource() -> object:
        return guard_value

    @asset(
        name=identity.asset_keys[0],
        required_resource_keys={"provider_records", "kor_travel_map_client"},
    )
    async def _guarded_asset(context) -> None:  # type: ignore[no-untyped-def]
        nonlocal raw_calls
        raw_calls += 1
        await context.resources.kor_travel_map_client.load_feature_bundles(())

    job = define_asset_job(
        identity.job_name,
        selection=[_guarded_asset],
        tags=feature_operation_definition_tags(identity),
    )
    definitions = Definitions(
        assets=[_guarded_asset],
        jobs=[job],
        resources={
            "kor_travel_map_client": _load_client_resource,
            "feature_operation_guard": _invalid_guard_resource,
            "provider_records": build_provider_record_live_resource(spec, _fetch),
        },
    )

    result = definitions.resolve_job_def(identity.job_name).execute_in_process(
        raise_on_error=False
    )

    assert result.success is False
    assert provider_fetch_calls == 0, reason
    assert raw_calls == 0, reason
    assert db_load_calls == 0, reason


@pytest.mark.parametrize(
    "case",
    [
        "wrong_pair",
        "wrong_config_snapshot",
        "wrong_version",
        "other_run_id",
        "trigger_none",
        "unensured_marker_blocked",
    ],
)
def test_actual_definitions_rejects_forged_or_unensured_dynamic_guard(
    case: str,
) -> None:
    launch = resolve_feature_operation_launch(
        job_name="feature_place_knps_points_job",
        runtime_snapshot=resolve_feature_operation_runtime_snapshot(),
    )
    assert launch is not None
    identity, _run_config = launch
    other_dataset = next(
        key
        for key in KNPS_PLACE_DATASETS
        if key != identity.pairs[0].dataset_key
    )
    if case == "wrong_pair":
        guard_identity = replace(
            identity,
            pairs=(
                ProviderDatasetOperationKey(
                    identity.pairs[0].provider,
                    other_dataset,
                ),
            ),
            config_snapshot=(("knps_point_dataset_key", other_dataset),),
        )
    elif case == "wrong_config_snapshot":
        guard_identity = replace(
            identity,
            config_snapshot=(("knps_point_dataset_key", other_dataset),),
        )
    elif case == "wrong_version":
        guard_identity = replace(identity, registry_version="v1-forged")
    else:
        guard_identity = identity

    client = _Client(blocked=case == "unensured_marker_blocked")
    provider_fetch_calls = 0
    raw_calls = 0
    db_load_calls = 0
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key=identity.pairs[0].dataset_key,
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal provider_fetch_calls
        provider_fetch_calls += 1
        return (object(),)

    class _LoadClient:
        async def load_feature_bundles(self, _bundles: object) -> None:
            nonlocal db_load_calls
            db_load_calls += 1

    @resource
    def _client_resource() -> object:
        return client

    @resource(required_resource_keys={"kor_travel_map_client"})
    def _unensured_guard_resource(context) -> object:  # type: ignore[no-untyped-def]
        run_id = context.run.run_id
        return FeatureOperationExecutionGuard(
            client=cast(
                AsyncKorTravelMapClient,
                context.resources.kor_travel_map_client,
            ),
            instance=context.instance,
            identity=guard_identity,
            dagster_run_id="other-run" if case == "other_run_id" else run_id,
            trigger_kind=None if case == "trigger_none" else "manual",
        )

    @asset(
        name=identity.asset_keys[0],
        required_resource_keys={"provider_records"},
    )
    async def _guarded_asset() -> None:
        nonlocal raw_calls
        raw_calls += 1
        await _LoadClient().load_feature_bundles(())

    job = define_asset_job(
        identity.job_name,
        selection=[_guarded_asset],
        tags=feature_operation_definition_tags(identity),
    )
    definitions = Definitions(
        assets=[_guarded_asset],
        jobs=[job],
        resources={
            "kor_travel_map_client": _client_resource,
            "feature_operation_guard": _unensured_guard_resource,
            "provider_records": build_provider_record_live_resource(spec, _fetch),
        },
    )

    with DagsterInstance.local_temp() as instance:
        result = definitions.resolve_job_def(identity.job_name).execute_in_process(
            instance=instance,
            raise_on_error=False,
        )

    assert result.success is False
    assert provider_fetch_calls == 0
    assert raw_calls == 0
    assert db_load_calls == 0
    if case == "unensured_marker_blocked":
        assert [name for name, _kwargs in client.calls] == ["ensure"]
    else:
        assert client.calls == []


def test_live_provider_missing_guard_is_typed_and_has_zero_io() -> None:
    fetch_calls = 0
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key="dataset",
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal fetch_calls
        fetch_calls += 1
        return (object(),)

    resource_def = build_provider_record_live_resource(spec, _fetch)
    context = SimpleNamespace(resources=SimpleNamespace())

    with pytest.raises(FeatureOperationGuardUnavailable) as raised:
        cast(Any, resource_def.resource_fn)(context)

    assert raised.value.reason == "missing"
    assert fetch_calls == 0


def test_live_provider_registered_guard_without_context_run_has_zero_io() -> None:
    fetch_calls = 0
    client = _Client()
    guard = _guard(client)
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key=cast(Any, guard.identity).pairs[0].dataset_key,
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal fetch_calls
        fetch_calls += 1
        return (object(),)

    resource_def = build_provider_record_live_resource(spec, _fetch)
    context = SimpleNamespace(
        resources=SimpleNamespace(
            feature_operation_guard=guard,
            kor_travel_map_client=client,
        ),
        instance=guard.instance,
    )

    with pytest.raises(FeatureOperationGuardUnavailable) as raised:
        cast(Any, resource_def.resource_fn)(context)

    assert raised.value.reason == "context_job_missing"
    assert fetch_calls == 0
    assert client.calls == []


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("client_mismatch", "client_mismatch"),
        ("instance_mismatch", "instance_mismatch"),
        ("run_record_missing", "run_record_missing"),
        ("authoritative_run_mismatch", "authoritative_run_mismatch"),
        ("wrong_trigger", "trigger_mismatch"),
    ],
)
def test_live_provider_authoritative_mismatch_is_typed_and_has_zero_io(
    case: str,
    reason: str,
) -> None:
    identity = _identity()
    client = _Client()
    other_client = _Client()
    context_run = _run_for_identity(identity)
    record_run = (
        _run_for_identity(identity, run_id="authoritative-other-run")
        if case == "authoritative_run_mismatch"
        else context_run
    )
    instance = _RunRecordInstance(
        record_run,
        missing=case == "run_record_missing",
    )
    guard = FeatureOperationExecutionGuard(
        client=cast(
            AsyncKorTravelMapClient,
            other_client if case == "client_mismatch" else client,
        ),
        instance=(object() if case == "instance_mismatch" else instance),
        identity=identity,
        dagster_run_id=context_run.run_id,
        trigger_kind="sensor" if case == "wrong_trigger" else "manual",
    )
    fetch_calls = 0
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key=identity.pairs[0].dataset_key,
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal fetch_calls
        fetch_calls += 1
        return (object(),)

    context = SimpleNamespace(
        run=context_run,
        instance=instance,
        resources=SimpleNamespace(
            feature_operation_guard=guard,
            kor_travel_map_client=client,
        ),
        resource_config={},
    )

    with pytest.raises(FeatureOperationGuardUnavailable) as raised:
        cast(Any, build_provider_record_live_resource(spec, _fetch).resource_fn)(
            context
        )

    assert raised.value.reason == reason
    assert fetch_calls == 0
    assert client.calls == other_client.calls == []


@pytest.mark.parametrize("pair_shape", ["subset", "extra"])
def test_mcst_pair_shape_drift_blocks_authoritative_provider_io(
    pair_shape: str,
) -> None:
    identity = _identity("feature_place_mcst_culture_job")
    pairs = (
        identity.pairs[:-1]
        if pair_shape == "subset"
        else (
            *identity.pairs,
            ProviderDatasetOperationKey("forged-provider", "forged-dataset"),
        )
    )
    forged_identity = replace(identity, pairs=pairs)
    client = _Client()
    run = _run_for_identity(
        identity,
        tags=feature_operation_definition_tags(forged_identity),
    )
    instance = _RunRecordInstance(run)
    guard = FeatureOperationExecutionGuard(
        client=cast(AsyncKorTravelMapClient, client),
        instance=instance,
        identity=identity,
        dagster_run_id=run.run_id,
        trigger_kind="manual",
    )
    fetch_calls = 0
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key=identity.pairs[0].dataset_key,
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal fetch_calls
        fetch_calls += 1
        return (object(),)

    context = SimpleNamespace(
        run=run,
        instance=instance,
        resources=SimpleNamespace(
            feature_operation_guard=guard,
            kor_travel_map_client=client,
        ),
        resource_config={},
    )

    with pytest.raises(FeatureOperationGuardUnavailable) as raised:
        cast(Any, build_provider_record_live_resource(spec, _fetch).resource_fn)(
            context
        )

    assert raised.value.reason == "registry_conflict"
    assert fetch_calls == 0
    assert client.calls == []


@pytest.mark.parametrize("pair_shape", ["subset", "extra"])
def test_actual_definitions_mcst_pair_shape_drift_has_zero_io(
    pair_shape: str,
) -> None:
    identity = _identity("feature_place_mcst_culture_job")
    pairs = (
        identity.pairs[:-1]
        if pair_shape == "subset"
        else (
            *identity.pairs,
            ProviderDatasetOperationKey("forged-provider", "forged-dataset"),
        )
    )
    forged_identity = replace(identity, pairs=pairs)
    client = _Client()
    fetch_calls = 0
    raw_calls = 0
    db_load_calls = 0
    spec = ProviderRecordResourceSpec(
        resource_key="provider_records",
        provider_package="python-test-api",
        dataset_key=identity.pairs[0].dataset_key,
    )

    def _fetch(_settings: object) -> tuple[object, ...]:
        nonlocal fetch_calls
        fetch_calls += 1
        return (object(),)

    @resource
    def _client_resource() -> object:
        return client

    @resource(required_resource_keys={"kor_travel_map_client"})
    def _guard_resource(context) -> object:  # type: ignore[no-untyped-def]
        return FeatureOperationExecutionGuard(
            client=cast(
                AsyncKorTravelMapClient,
                context.resources.kor_travel_map_client,
            ),
            instance=context.instance,
            identity=identity,
            dagster_run_id=context.run.run_id,
            trigger_kind="manual",
        )

    @asset(
        name=identity.asset_keys[0],
        required_resource_keys={"provider_records"},
    )
    async def _guarded_asset() -> None:
        nonlocal raw_calls, db_load_calls
        raw_calls += 1
        db_load_calls += 1

    job = define_asset_job(
        identity.job_name,
        selection=[_guarded_asset],
        tags=feature_operation_definition_tags(forged_identity),
    )
    definitions = Definitions(
        assets=[_guarded_asset],
        jobs=[job],
        resources={
            "kor_travel_map_client": _client_resource,
            "feature_operation_guard": _guard_resource,
            "provider_records": build_provider_record_live_resource(spec, _fetch),
        },
    )

    result = definitions.resolve_job_def(identity.job_name).execute_in_process(
        raise_on_error=False
    )

    assert result.success is False
    assert "reason='registry_conflict'" in str(result.all_events)
    assert fetch_calls == raw_calls == db_load_calls == 0
    assert client.calls == []


@pytest.mark.parametrize(
    "resource_def",
    [
        PROVIDER_RECORD_RESOURCE_DEFINITIONS["knps_point_records"],
        PROVIDER_RECORD_RESOURCE_DEFINITIONS["datagokr_file_data_records"],
        datagokr_file_data_dataset_key_resource,
        kma_weather_client_factory_resource,
        kma_datagokr_client_resource,
    ],
)
def test_special_live_provider_resources_reject_none_guard_before_io(
    resource_def: object,
) -> None:
    context = SimpleNamespace(
        resources=SimpleNamespace(feature_operation_guard=None),
        resource_config={},
    )

    def _initialize_resource() -> None:
        result = cast(Any, resource_def).resource_fn(context)
        if inspect.isgenerator(result):
            next(result)

    with pytest.raises(FeatureOperationGuardUnavailable) as raised:
        _initialize_resource()

    assert raised.value.reason == "none"


@pytest.mark.parametrize("boundary", ["single", "mcst"])
@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("wrong_pair", "identity_mismatch"),
        ("wrong_config_snapshot", "identity_mismatch"),
        ("wrong_version", "identity_mismatch"),
        ("other_run_id", "run_id_mismatch"),
        ("trigger_none", "trigger_mismatch"),
        ("wrong_trigger", "trigger_mismatch"),
        ("client_mismatch", "client_mismatch"),
        ("instance_mismatch", "instance_mismatch"),
        ("run_record_missing", "run_record_missing"),
        ("authoritative_run_mismatch", "authoritative_run_mismatch"),
    ],
)
async def test_direct_public_wrapper_rejects_forged_authoritative_guard(
    boundary: str,
    case: str,
    reason: str,
) -> None:
    identity = _identity(
        "feature_place_mcst_culture_job"
        if boundary == "mcst"
        else "feature_place_mois_licenses_job"
    )
    context_run = _run_for_identity(identity)
    record_run = (
        _run_for_identity(identity, run_id="authoritative-other-run")
        if case == "authoritative_run_mismatch"
        else context_run
    )
    instance = _RunRecordInstance(
        record_run,
        missing=case == "run_record_missing",
    )
    client = _Client()
    other_client = _Client()
    if case == "wrong_pair":
        guard_identity = replace(
            identity,
            pairs=(
                ProviderDatasetOperationKey("forged-provider", "forged-dataset"),
                *identity.pairs[1:],
            ),
        )
    elif case == "wrong_config_snapshot":
        guard_identity = replace(
            identity,
            config_snapshot=(("forged_snapshot", "forged-dataset"),),
        )
    elif case == "wrong_version":
        guard_identity = replace(identity, registry_version="forged-version")
    else:
        guard_identity = identity
    guard = FeatureOperationExecutionGuard(
        client=cast(
            AsyncKorTravelMapClient,
            other_client if case == "client_mismatch" else client,
        ),
        instance=(object() if case == "instance_mismatch" else instance),
        identity=guard_identity,
        dagster_run_id=("other-run" if case == "other_run_id" else "run-1"),
        trigger_kind=(
            None
            if case == "trigger_none"
            else "sensor"
            if case == "wrong_trigger"
            else "manual"
        ),
    )
    context = SimpleNamespace(
        resources=SimpleNamespace(
            feature_operation_guard=guard,
            kor_travel_map_client=client,
        ),
        instance=instance,
        run=context_run,
        run_id=context_run.run_id,
        job_name=identity.job_name,
        selected_asset_keys={_AssetKey(key) for key in identity.asset_keys},
        asset_key=_AssetKey(identity.asset_keys[0]),
        retry_number=0,
    )
    raw_calls = 0
    db_load_calls = 0

    async def _raw(_context: object) -> None:
        nonlocal raw_calls, db_load_calls
        raw_calls += 1
        db_load_calls += 1

    async def _run_public_boundary() -> None:
        if boundary == "single":
            await run_tracked_feature_asset(context, _raw)
        else:
            await ensure_tracked_multi_pair_asset(context)
            await _raw(context)

    with pytest.raises(FeatureOperationGuardUnavailable) as raised:
        await _run_public_boundary()

    assert raised.value.reason == reason
    assert raw_calls == db_load_calls == 0
    assert client.calls == other_client.calls == []


@pytest.mark.parametrize("boundary", ["single", "mcst"])
async def test_direct_public_wrapper_unensured_override_checks_marker(
    boundary: str,
) -> None:
    identity = _identity(
        "feature_place_mcst_culture_job"
        if boundary == "mcst"
        else "feature_place_mois_licenses_job"
    )
    client = _Client(blocked=True)
    run = _run_for_identity(identity)
    instance = _RunRecordInstance(run)
    guard = FeatureOperationExecutionGuard(
        client=cast(AsyncKorTravelMapClient, client),
        instance=instance,
        identity=identity,
        dagster_run_id=run.run_id,
        trigger_kind="manual",
    )
    context = SimpleNamespace(
        resources=SimpleNamespace(
            feature_operation_guard=guard,
            kor_travel_map_client=client,
        ),
        instance=instance,
        run=run,
        run_id=run.run_id,
        job_name=identity.job_name,
        selected_asset_keys={_AssetKey(key) for key in identity.asset_keys},
        asset_key=_AssetKey(identity.asset_keys[0]),
        retry_number=0,
    )
    raw_calls = 0
    db_load_calls = 0

    async def _raw(_context: object) -> None:
        nonlocal raw_calls, db_load_calls
        raw_calls += 1
        db_load_calls += 1

    async def _run_public_boundary() -> None:
        if boundary == "single":
            await run_tracked_feature_asset(context, _raw)
        else:
            await ensure_tracked_multi_pair_asset(context)
            await _raw(context)

    with pytest.raises(FeatureOperationExecutionBlocked, match="cancellation"):
        await _run_public_boundary()

    assert raw_calls == db_load_calls == 0
    assert [name for name, _kwargs in client.calls] == ["ensure"]


@pytest.mark.parametrize(
    ("resources", "reason"),
    [
        (SimpleNamespace(), "missing"),
        (SimpleNamespace(feature_operation_guard=None), "none"),
        (SimpleNamespace(feature_operation_guard=object()), "wrong_type"),
        (
            SimpleNamespace(feature_operation_guard=_panel_guard()),
            "registered_identity_missing",
        ),
    ],
)
async def test_registered_public_wrapper_invalid_guard_has_zero_raw_and_db_load(
    resources: object,
    reason: str,
) -> None:
    identity = _identity()
    raw_calls = 0
    db_load_calls = 0
    context = SimpleNamespace(
        resources=resources,
        selected_asset_keys={_AssetKey(identity.asset_keys[0])},
        asset_key=_AssetKey(identity.asset_keys[0]),
        job_name=identity.job_name,
        retry_number=0,
    )

    async def _raw(_context: object) -> None:
        nonlocal raw_calls, db_load_calls
        raw_calls += 1
        db_load_calls += 1

    with pytest.raises(FeatureOperationGuardUnavailable) as raised:
        await run_tracked_feature_asset(context, _raw)

    assert raised.value.reason == reason
    assert raw_calls == 0
    assert db_load_calls == 0


async def test_panel_only_requires_valid_guard_object_and_skips_tracking() -> None:
    client = _Client()
    run = SimpleNamespace(job_name="panel_only_job", run_id="panel-run")
    instance = object()
    guard = FeatureOperationExecutionGuard(
        client=cast(AsyncKorTravelMapClient, client),
        instance=instance,
        identity=None,
        dagster_run_id=run.run_id,
        trigger_kind=None,
    )
    raw_calls = 0
    context = SimpleNamespace(
        resources=SimpleNamespace(
            feature_operation_guard=guard,
            kor_travel_map_client=client,
        ),
        instance=instance,
        run=run,
        run_id=run.run_id,
        job_name="panel_only_job",
    )

    async def _raw(_context: object) -> str:
        nonlocal raw_calls
        raw_calls += 1
        return "panel"

    assert await run_tracked_feature_asset(context, _raw) == "panel"
    assert raw_calls == 1
    assert client.calls == []


async def test_panel_only_rejects_non_null_trigger_before_raw_io() -> None:
    client = _Client()
    run = SimpleNamespace(job_name="panel_only_job", run_id="panel-run")
    instance = object()
    guard = FeatureOperationExecutionGuard(
        client=cast(AsyncKorTravelMapClient, client),
        instance=instance,
        identity=None,
        dagster_run_id=run.run_id,
        trigger_kind="manual",
    )
    context = SimpleNamespace(
        resources=SimpleNamespace(
            feature_operation_guard=guard,
            kor_travel_map_client=client,
        ),
        instance=instance,
        run=run,
        run_id=run.run_id,
        job_name=run.job_name,
    )
    raw_calls = 0

    async def _raw(_context: object) -> None:
        nonlocal raw_calls
        raw_calls += 1

    with pytest.raises(FeatureOperationGuardUnavailable) as raised:
        await run_tracked_feature_asset(context, _raw)

    assert raised.value.reason == "panel_guard_invalid"
    assert raw_calls == 0
    assert client.calls == []


async def test_marker_block_prevents_public_wrapper_raw_body() -> None:
    client = _Client(blocked=True)
    context = _asset_context(_guard(client, blocked=True))
    raw_calls = 0

    async def _raw(_context: object) -> object:
        nonlocal raw_calls
        raw_calls += 1
        return object()

    with pytest.raises(FeatureOperationExecutionBlocked, match="cancellation"):
        await run_tracked_feature_asset(context, _raw)

    assert raw_calls == 0
    assert [name for name, _kwargs in client.calls] == ["ensure"]


async def test_step_retry_reuses_pair_and_finishes_only_after_success() -> None:
    client = _Client()
    guard = _guard(client)
    call_order: list[str] = []

    async def _first(_context: object) -> object:
        call_order.append("raw-first")
        raise RuntimeError("provider secret must not be persisted")

    async def _second(_context: object) -> str:
        call_order.append("raw-second")
        return "done"

    with pytest.raises(RuntimeError, match="provider secret"):
        await run_tracked_feature_asset(_asset_context(guard), _first)
    result = await run_tracked_feature_asset(
        _asset_context(guard, retry_number=1),
        _second,
    )

    assert result == "done"
    assert [name for name, _kwargs in client.calls] == [
        "ensure",
        "attempt",
        "ensure",
        "finish",
    ]
    attempt = client.calls[1][1]
    assert attempt["attempt_number"] == 1
    assert attempt["error"] == {
        "code": "FEATURE_OPERATION_ASSET_ATTEMPT_FAILED",
        "type": "RuntimeError",
    }
    assert "provider secret" not in str(attempt)
    assert call_order == ["raw-first", "raw-second"]
    assert client.calls[-1][1]["pair"] == cast(Any, guard.identity).pairs[0]


async def test_shared_run_repeated_wrapper_finish_is_idempotent() -> None:
    class _IdempotentClient(_Client):
        def __init__(self) -> None:
            super().__init__()
            self.finished = False
            self.finish_outcomes: list[str] = []

        async def finish_dagster_feature_pair(self, **kwargs: Any) -> Any:
            self.calls.append(("finish", kwargs))
            outcome = "noop" if self.finished else "applied"
            self.finished = True
            self.finish_outcomes.append(outcome)
            return SimpleNamespace(outcome=outcome, block_reason=None)

    client = _IdempotentClient()
    guard = _guard(client)
    raw_calls = 0

    async def _raw(_context: object) -> str:
        nonlocal raw_calls
        raw_calls += 1
        return "done"

    first = await run_tracked_feature_asset(_asset_context(guard), _raw)
    second = await run_tracked_feature_asset(_asset_context(guard), _raw)

    assert first == second == "done"
    assert raw_calls == 2
    assert [name for name, _kwargs in client.calls] == [
        "ensure",
        "finish",
        "ensure",
        "finish",
    ]
    assert client.calls[1][1]["dagster_run_id"] == "run-1"
    assert client.calls[3][1]["dagster_run_id"] == "run-1"
    assert client.calls[1][1]["pair"] == client.calls[3][1]["pair"]
    assert client.finish_outcomes == ["applied", "noop"]
