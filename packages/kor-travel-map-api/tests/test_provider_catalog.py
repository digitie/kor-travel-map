"""T-VN-33 DB provider dataset catalog/handler binding contract tests."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

import pytest
from kortravelmap.providers.feature_operation_registry import (
    FEATURE_OPERATION_HANDLERS,
    UnknownFeatureOperationHandlerError,
    feature_operation_handler_keys,
    resolve_feature_operation_handler,
)

from kortravelmap.api import provider_catalog
from kortravelmap.api.provider_catalog import (
    ActiveOperationHandlerDriftError,
    assert_active_operation_handler_exact_set,
    find_provider_dataset_catalog_entry,
    list_active_refresh_operation_bindings,
    list_provider_dataset_catalog,
)


class _FakeResult:
    def __init__(self, rows: list[Mapping[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[Mapping[str, Any]]:
        return self._rows


class _FakeSession:
    def __init__(
        self,
        *,
        catalog_rows: list[Mapping[str, Any]],
        active_operation_rows: list[Mapping[str, Any]],
    ) -> None:
        self.catalog_rows = catalog_rows
        self.active_operation_rows = active_operation_rows
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    async def execute(
        self,
        statement: Any,
        params: dict[str, object] | None = None,
    ) -> _FakeResult:
        sql = str(statement)
        self.calls.append((sql, params))
        rows = (
            self.active_operation_rows
            if "operation.operation_kind = 'refresh'" in sql
            else self.catalog_rows
        )
        return _FakeResult(rows)


_CATALOG_ROWS: list[Mapping[str, Any]] = [
    {
        "provider_dataset_id": 2,
        "provider": "python-example-api",
        "dataset_key": "weather",
        "display_name": "예시 날씨",
        "source_kind": "openapi",
        "is_active": True,
        "capabilities": '{"schema_version": 1, "produces": ["weather"]}',
        "operation_key": "feature_weather_example_job",
        "operation_kind": "refresh",
        "operation_is_enabled": True,
        "operation_config": '{"max_grids": 2}',
        "sync_scope": "dataset_wide",
    },
    {
        "provider_dataset_id": 2,
        "provider": "python-example-api",
        "dataset_key": "weather",
        "display_name": "예시 날씨",
        "source_kind": "openapi",
        "is_active": True,
        "capabilities": '{"schema_version": 1, "produces": ["weather"]}',
        "operation_key": "feature_weather_example_job",
        "operation_kind": "refresh",
        "operation_is_enabled": True,
        "operation_config": '{"max_grids": 2}',
        "sync_scope": "external_system:concierge",
    },
    {
        "provider_dataset_id": 2,
        "provider": "python-example-api",
        "dataset_key": "weather",
        "display_name": "예시 날씨",
        "source_kind": "openapi",
        "is_active": True,
        "capabilities": '{"schema_version": 1, "produces": ["weather"]}',
        "operation_key": "feature_weather_preview_job",
        "operation_kind": "preview",
        "operation_is_enabled": False,
        "operation_config": {},
        "sync_scope": None,
    },
    {
        "provider_dataset_id": 3,
        "provider": "python-example-api",
        "dataset_key": "retired",
        "display_name": "종료 dataset",
        "source_kind": "filedata",
        "is_active": False,
        "capabilities": {"schema_version": 1, "produces": ["place"]},
        "operation_key": None,
        "operation_kind": None,
        "operation_is_enabled": None,
        "operation_config": None,
        "sync_scope": None,
    },
]

_ACTIVE_OPERATION_ROWS: list[Mapping[str, Any]] = [
    {
        "provider_dataset_id": 2,
        "provider": "python-example-api",
        "dataset_key": "weather",
        "operation_key": "feature_weather_example_job",
    },
    {
        "provider_dataset_id": 4,
        "provider": "python-other-api",
        "dataset_key": "weather-copy",
        "operation_key": "feature_weather_example_job",
    },
    {
        "provider_dataset_id": 5,
        "provider": "python-other-api",
        "dataset_key": "place",
        "operation_key": "feature_place_example_job",
    },
]


def _session() -> _FakeSession:
    return _FakeSession(
        catalog_rows=_CATALOG_ROWS,
        active_operation_rows=_ACTIVE_OPERATION_ROWS,
    )


@pytest.mark.unit
async def test_catalog_is_db_projection_with_operations_and_normalized_scopes() -> None:
    session = _session()

    catalog = await list_provider_dataset_catalog(session)  # type: ignore[arg-type]

    assert [(entry.provider, entry.dataset_key) for entry in catalog] == [
        ("python-example-api", "retired"),
        ("python-example-api", "weather"),
    ]
    weather = catalog[1]
    assert weather.provider_dataset_id == 2
    assert weather.produces == ("weather",)
    with pytest.raises(TypeError):
        weather.capabilities["produces"] = ()  # type: ignore[index]
    operation_identities = [
        (operation.operation_key, operation.operation_kind) for operation in weather.operations
    ]
    assert operation_identities == [
        ("feature_weather_example_job", "refresh"),
        ("feature_weather_preview_job", "preview"),
    ]
    refresh = weather.operations[0]
    assert refresh.config == {"max_grids": 2}
    assert refresh.sync_scopes == ("dataset_wide", "external_system:concierge")
    assert "provider_sync.provider_datasets" in session.calls[0][0]
    assert "provider_sync.provider_dataset_operations" in session.calls[0][0]
    assert "provider_sync.provider_dataset_operation_scopes" in session.calls[0][0]
    assert session.calls[0][1] == {"active_only": False}


@pytest.mark.unit
async def test_catalog_lookup_delegates_to_db_projection() -> None:
    session = _session()

    entry = await find_provider_dataset_catalog_entry(  # type: ignore[arg-type]
        session,
        provider="python-example-api",
        dataset_key="weather",
        active_only=True,
    )

    assert entry is not None
    assert entry.provider_dataset_id == 2
    assert session.calls[0][1] == {"active_only": True}


@pytest.mark.unit
async def test_active_refresh_binding_keeps_dataset_identity_outside_handler_registry() -> None:
    session = _session()

    bindings = await list_active_refresh_operation_bindings(session)  # type: ignore[arg-type]

    assert [(item.provider_dataset_id, item.operation_key) for item in bindings] == [
        (2, "feature_weather_example_job"),
        (4, "feature_weather_example_job"),
        (5, "feature_place_example_job"),
    ]


@pytest.mark.unit
async def test_active_operation_and_handler_sets_must_match_exactly() -> None:
    session = _session()

    actual = await assert_active_operation_handler_exact_set(  # type: ignore[arg-type]
        session,
        handler_operation_keys={
            "feature_weather_example_job",
            "feature_place_example_job",
        },
    )

    assert actual == {"feature_weather_example_job", "feature_place_example_job"}

    with pytest.raises(ActiveOperationHandlerDriftError) as raised:
        await assert_active_operation_handler_exact_set(  # type: ignore[arg-type]
            session,
            handler_operation_keys={"feature_weather_example_job", "stale_job"},
        )
    assert raised.value.missing_handler_operation_keys == {"feature_place_example_job"}
    assert raised.value.stale_handler_operation_keys == {"stale_job"}


@pytest.mark.unit
def test_handler_registry_is_key_to_handler_only() -> None:
    assert len(FEATURE_OPERATION_HANDLERS) == 33
    assert feature_operation_handler_keys() == frozenset(FEATURE_OPERATION_HANDLERS)
    binding = resolve_feature_operation_handler("feature_place_knps_points_job")
    assert binding.job_name == "feature_place_knps_points_job"
    assert binding.asset_keys == ("feature_place_knps_points",)
    with pytest.raises(UnknownFeatureOperationHandlerError):
        resolve_feature_operation_handler("missing_operation")

    source = inspect.getsource(provider_catalog)
    assert "PROVIDER_DATASET_CATALOG" not in source
    registry_module = inspect.getmodule(resolve_feature_operation_handler)
    assert registry_module is not None
    registry_source = inspect.getsource(registry_module)
    assert "ProviderDatasetOperationKey" not in registry_source
    assert ".pairs" not in registry_source
