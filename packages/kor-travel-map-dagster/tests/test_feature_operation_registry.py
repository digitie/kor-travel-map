"""Feature operation registry와 durable run identity 회귀."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from dagster import build_schedule_context
from kortravelmap.providers.datagokr_file_data import DATAGOKR_FILEDATA_DATASETS
from kortravelmap.providers.feature_operation_registry import (
    ADMIN_MANUAL_TRIGGER_TAG,
    DAGSTER_BACKFILL_ID_TAG,
    DAGSTER_SCHEDULE_NAME_TAG,
    DAGSTER_SENSOR_NAME_TAG,
    FEATURE_OPERATION_DATASET_TAG,
    FEATURE_OPERATION_IDENTITY_TAG,
    FEATURE_OPERATION_JOB_BY_PAIR,
    FEATURE_OPERATION_PROVIDER_TAG,
    FEATURE_OPERATION_REGISTRY,
    FEATURE_OPERATION_REGISTRY_BY_JOB,
    FEATURE_OPERATION_REGISTRY_DIGEST,
    FEATURE_OPERATION_REGISTRY_SCHEMA_VERSION,
    FEATURE_OPERATION_REGISTRY_VERSION,
    FEATURE_OPERATION_REGISTRY_VERSION_TAG,
    FEATURE_OPERATION_TRIGGER_TAG,
    FEATURE_UPDATE_REQUEST_ID_TAG,
    INTERNAL_SYSTEM_TRIGGER_TAG,
    FeatureOperationIdentity,
    FeatureOperationRegistryError,
    FeatureOperationRuntimeSnapshot,
    all_feature_operation_registry_pairs,
    feature_operation_definition_tags,
    feature_operation_launch_tags,
    feature_operation_registry_manifest_json,
    feature_operation_run_config,
    parse_feature_operation_identity_tags,
    resolve_feature_operation_identity,
    resolve_feature_operation_runtime_snapshot,
    resolve_feature_operation_trigger,
    validate_feature_operation_identity,
)
from kortravelmap.providers.knps import KNPS_GEOMETRY_DATASETS, KNPS_PLACE_DATASETS
from kortravelmap.providers.mcst import MCST_FILE_DATASETS, MCST_PROVIDER_NAME

from kortravelmap.dagster.schedules import (
    FEATURE_LOAD_IDENTITIES,
    FEATURE_LOAD_JOBS,
    FEATURE_LOAD_SCHEDULE_SPECS,
    FEATURE_LOAD_SCHEDULES,
    compile_feature_load_identities,
)


def _knps_snapshot(
    *,
    point: str = "knps_visitor_centers",
    geometry: str = "knps_trails",
) -> FeatureOperationRuntimeSnapshot:
    return FeatureOperationRuntimeSnapshot(
        knps_point_dataset_key=point,
        knps_geometry_dataset_key=geometry,
    )


def _resolved(
    job_name: str,
    *,
    selected_asset_keys: Sequence[str] | None = None,
    run_config: Mapping[str, object] | None = None,
    runtime_snapshot: FeatureOperationRuntimeSnapshot | None = None,
) -> FeatureOperationIdentity:
    identity = resolve_feature_operation_identity(
        job_name=job_name,
        selected_asset_keys=selected_asset_keys,
        run_config=run_config,
        runtime_snapshot=runtime_snapshot,
    )
    assert identity is not None
    return identity


def _set_resource_dataset(
    run_config: dict[str, object],
    resource_name: str,
    dataset_key: str,
) -> None:
    resources = run_config["resources"]
    assert isinstance(resources, dict)
    resource = resources[resource_name]
    assert isinstance(resource, dict)
    config = resource["config"]
    assert isinstance(config, dict)
    config["dataset_key"] = dataset_key


def test_registry_is_immutable_and_versioned() -> None:
    assert isinstance(FEATURE_OPERATION_REGISTRY, tuple)
    assert len(FEATURE_OPERATION_REGISTRY) == 33
    manifest_json = feature_operation_registry_manifest_json()
    expected_digest = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
    assert expected_digest == FEATURE_OPERATION_REGISTRY_DIGEST
    assert (
        f"{FEATURE_OPERATION_REGISTRY_SCHEMA_VERSION}-{expected_digest[:12]}"
    ) == FEATURE_OPERATION_REGISTRY_VERSION
    assert hashlib.sha256((manifest_json + " ").encode()).hexdigest() != expected_digest

    entry = FEATURE_OPERATION_REGISTRY[0]
    with pytest.raises(FrozenInstanceError):
        entry.job_name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        FEATURE_OPERATION_REGISTRY_BY_JOB["new"] = entry  # type: ignore[index]


def test_registry_pairs_and_jobs_are_unique() -> None:
    registry_pairs = set(all_feature_operation_registry_pairs())

    assert len(registry_pairs) == 53
    assert len(FEATURE_OPERATION_JOB_BY_PAIR) == 53
    assert set(FEATURE_OPERATION_JOB_BY_PAIR) == registry_pairs
    assert len(FEATURE_OPERATION_REGISTRY_BY_JOB) == len(FEATURE_OPERATION_REGISTRY)
    for entry in FEATURE_OPERATION_REGISTRY:
        assert len(entry.pairs) == len(set(entry.pairs))
        assert len(entry.allowed_dataset_keys) == len(set(entry.allowed_dataset_keys))


def test_runtime_snapshot_reads_only_two_knps_environment_fields() -> None:
    snapshot = resolve_feature_operation_runtime_snapshot(
        {
            "KOR_TRAVEL_MAP_KNPS_POINT_DATASET_KEY": "knps_restrooms",
            "KOR_TRAVEL_MAP_KNPS_GEOMETRY_DATASET_KEY": "knps_hazard_zones",
            "KOR_TRAVEL_MAP_PG_DSN": "not-a-valid-postgres-dsn",
            "KOR_TRAVEL_MAP_DAGSTER_ADDRESS_VALIDATION": "not-a-valid-mode",
        }
    )

    assert snapshot == FeatureOperationRuntimeSnapshot(
        knps_point_dataset_key="knps_restrooms",
        knps_geometry_dataset_key="knps_hazard_zones",
    )


def test_runtime_snapshot_reads_dotenv_without_validating_unrelated_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KOR_TRAVEL_MAP_KNPS_POINT_DATASET_KEY", raising=False)
    monkeypatch.delenv("KOR_TRAVEL_MAP_KNPS_GEOMETRY_DATASET_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "KOR_TRAVEL_MAP_KNPS_POINT_DATASET_KEY=knps_restrooms",
                "KOR_TRAVEL_MAP_KNPS_GEOMETRY_DATASET_KEY=knps_hazard_zones",
                "KOR_TRAVEL_MAP_PG_DSN=not-a-valid-postgres-dsn",
                "KOR_TRAVEL_MAP_DAGSTER_ADDRESS_VALIDATION=not-a-valid-mode",
            )
        ),
        encoding="utf-8",
    )

    snapshot = resolve_feature_operation_runtime_snapshot()

    assert snapshot == FeatureOperationRuntimeSnapshot(
        knps_point_dataset_key="knps_restrooms",
        knps_geometry_dataset_key="knps_hazard_zones",
    )


def test_definition_compile_ignores_unrelated_malformed_environment() -> None:
    identities = compile_feature_load_identities(
        {
            "KOR_TRAVEL_MAP_KNPS_POINT_DATASET_KEY": "knps_restrooms",
            "KOR_TRAVEL_MAP_KNPS_GEOMETRY_DATASET_KEY": "knps_hazard_zones",
            "KOR_TRAVEL_MAP_PG_DSN": "not-a-valid-postgres-dsn",
            "KOR_TRAVEL_MAP_DAGSTER_ADDRESS_VALIDATION": "not-a-valid-mode",
        }
    )

    assert len(identities) == 33
    by_job = {identity.job_name: identity for identity in identities}
    assert by_job["feature_place_knps_points_job"].pairs[0].dataset_key == (
        "knps_restrooms"
    )
    assert by_job["feature_geometry_knps_records_job"].pairs[0].dataset_key == (
        "knps_hazard_zones"
    )


def test_every_feature_schedule_job_and_asset_has_one_registry_entry() -> None:
    assert len(FEATURE_LOAD_SCHEDULE_SPECS) == 33
    assert len(FEATURE_LOAD_JOBS) == 33
    assert len(FEATURE_LOAD_SCHEDULES) == 33
    assert len(FEATURE_LOAD_IDENTITIES) == 33
    assert {spec.job_name for spec in FEATURE_LOAD_SCHEDULE_SPECS} == set(
        FEATURE_OPERATION_REGISTRY_BY_JOB
    )

    for spec, identity in zip(
        FEATURE_LOAD_SCHEDULE_SPECS,
        FEATURE_LOAD_IDENTITIES,
        strict=True,
    ):
        assert identity.job_name == spec.job_name
        assert identity.asset_keys == tuple(
            sorted(key.to_user_string() for key in spec.asset.keys)
        )


def test_mcst_registry_resolves_all_13_pairs_without_pseudo_dataset() -> None:
    identity = _resolved(job_name="feature_place_mcst_culture_job")

    assert len(identity.pairs) == 13
    assert {pair.provider for pair in identity.pairs} == {MCST_PROVIDER_NAME}
    assert {pair.dataset_key for pair in identity.pairs} == {
        spec.dataset_key for spec in MCST_FILE_DATASETS.values()
    }
    tags = feature_operation_definition_tags(identity)
    assert tags[FEATURE_OPERATION_PROVIDER_TAG] == MCST_PROVIDER_NAME
    assert FEATURE_OPERATION_DATASET_TAG not in tags
    assert "mcst_file_datasets" not in identity.canonical_json()
    assert parse_feature_operation_identity_tags(tags) == identity


@pytest.mark.parametrize(
    ("job_name", "dataset_key"),
    [
        ("feature_place_knps_points_job", key)
        for key in sorted(KNPS_PLACE_DATASETS)
    ]
    + [
        ("feature_geometry_knps_records_job", key)
        for key in sorted(KNPS_GEOMETRY_DATASETS)
    ],
)
def test_knps_registry_freezes_each_allowed_runtime_dataset(
    job_name: str,
    dataset_key: str,
) -> None:
    snapshot = _knps_snapshot(
        point=dataset_key if "points" in job_name else "knps_visitor_centers",
        geometry=dataset_key if "geometry" in job_name else "knps_trails",
    )
    identity = _resolved(job_name=job_name, runtime_snapshot=snapshot)
    run_config = feature_operation_run_config(identity)

    assert identity.pairs[0].dataset_key == dataset_key
    assert (
        resolve_feature_operation_identity(
            job_name=job_name,
            run_config=run_config,
            runtime_snapshot=snapshot,
        )
        == identity
    )


def test_knps_registry_rejects_catalog_and_three_way_snapshot_drift() -> None:
    job_name = "feature_place_knps_points_job"
    with pytest.raises(FeatureOperationRegistryError, match="허용 catalog"):
        _resolved(job_name=job_name, runtime_snapshot=_knps_snapshot(point="unknown"))

    identity = _resolved(job_name=job_name, runtime_snapshot=_knps_snapshot())
    run_config = feature_operation_run_config(identity)
    _set_resource_dataset(run_config, "knps_point_records", "knps_restrooms")
    with pytest.raises(FeatureOperationRegistryError, match="fetcher/asset"):
        resolve_feature_operation_identity(job_name=job_name, run_config=run_config)

    alternate = _knps_snapshot(point="knps_restrooms")
    with pytest.raises(FeatureOperationRegistryError, match="settings/run config"):
        resolve_feature_operation_identity(
            job_name=job_name,
            run_config=feature_operation_run_config(identity),
            runtime_snapshot=alternate,
        )


@pytest.mark.parametrize(
    ("job_name", "resource_names"),
    [
        (
            "feature_place_knps_points_job",
            ("knps_point_dataset_key", "knps_point_records"),
        ),
        (
            "feature_geometry_knps_records_job",
            ("knps_geometry_dataset_key", "knps_geometry_records"),
        ),
    ],
)
def test_knps_schedule_launch_freezes_fetcher_and_asset_resources(
    job_name: str,
    resource_names: tuple[str, str],
) -> None:
    index = next(
        index
        for index, spec in enumerate(FEATURE_LOAD_SCHEDULE_SPECS)
        if spec.job_name == job_name
    )
    identity = FEATURE_LOAD_IDENTITIES[index]
    tick = FEATURE_LOAD_SCHEDULES[index].evaluate_tick(build_schedule_context())

    assert len(tick.run_requests) == 1
    run_config = tick.run_requests[0].run_config
    expected_key = identity.pairs[0].dataset_key
    assert {
        name: run_config["resources"][name]["config"]["dataset_key"]
        for name in resource_names
    } == {name: expected_key for name in resource_names}


@pytest.mark.parametrize("dataset_key", sorted(DATAGOKR_FILEDATA_DATASETS))
def test_filedata_job_requires_both_resource_configs_to_match(dataset_key: str) -> None:
    job_name = f"feature_place_{dataset_key}_job"
    identity = _resolved(
        job_name=job_name,
        run_config={
            "resources": {
                "datagokr_file_data_dataset_key": {
                    "config": {"dataset_key": dataset_key}
                },
                "datagokr_file_data_records": {"config": {"dataset_key": dataset_key}},
            }
        },
    )
    assert identity.pairs[0].dataset_key == dataset_key

    drifted = feature_operation_run_config(identity)
    _set_resource_dataset(
        drifted,
        "datagokr_file_data_records",
        next(key for key in DATAGOKR_FILEDATA_DATASETS if key != dataset_key),
    )
    with pytest.raises(FeatureOperationRegistryError, match="fileData"):
        resolve_feature_operation_identity(job_name=job_name, run_config=drifted)


def test_registered_selection_and_identity_tag_drift_fail_closed() -> None:
    job_name = "feature_place_opinet_stations_job"
    identity = _resolved(job_name=job_name)
    tags = feature_operation_launch_tags(identity, trigger_kind="schedule")

    assert (
        validate_feature_operation_identity(
            job_name=job_name,
            selected_asset_keys=identity.asset_keys,
            run_config={},
            tags=tags,
        )
        == identity
    )
    with pytest.raises(FeatureOperationRegistryError, match="selection drift"):
        resolve_feature_operation_identity(
            job_name=job_name,
            selected_asset_keys=("feature_place_opinet_stations", "unexpected"),
        )
    with pytest.raises(FeatureOperationRegistryError, match="selection drift"):
        resolve_feature_operation_identity(
            job_name=job_name,
            selected_asset_keys=(),
        )

    for missing_tag in (
        FEATURE_OPERATION_REGISTRY_VERSION_TAG,
        FEATURE_OPERATION_IDENTITY_TAG,
    ):
        bad_tags = dict(tags)
        bad_tags.pop(missing_tag)
        with pytest.raises(FeatureOperationRegistryError):
            validate_feature_operation_identity(
                job_name=job_name,
                selected_asset_keys=identity.asset_keys,
                run_config={},
                tags=bad_tags,
            )

    for tag_name, wrong_value in (
        (FEATURE_OPERATION_REGISTRY_VERSION_TAG, "stale-version"),
        (FEATURE_OPERATION_IDENTITY_TAG, identity.canonical_json() + " "),
        (FEATURE_OPERATION_PROVIDER_TAG, "opinet"),
        (FEATURE_OPERATION_DATASET_TAG, "different-dataset"),
    ):
        bad_tags = {**tags, tag_name: wrong_value}
        with pytest.raises(FeatureOperationRegistryError):
            validate_feature_operation_identity(
                job_name=job_name,
                selected_asset_keys=identity.asset_keys,
                run_config={},
                tags=bad_tags,
            )


def test_unregistered_job_is_panel_only_even_with_forged_tags() -> None:
    assert (
        validate_feature_operation_identity(
            job_name="arbitrary_user_code_job",
            selected_asset_keys=("arbitrary_asset",),
            run_config={},
            tags={
                FEATURE_OPERATION_REGISTRY_VERSION_TAG: FEATURE_OPERATION_REGISTRY_VERSION,
                FEATURE_OPERATION_IDENTITY_TAG: "forged",
            },
        )
        is None
    )
    assert (
        resolve_feature_operation_trigger(
            None,
            {FEATURE_OPERATION_TRIGGER_TAG: "manual"},
        )
        is None
    )


def test_definition_tags_have_no_trigger_and_launch_tags_do() -> None:
    identity = _resolved(job_name="feature_place_opinet_stations_job")

    definition_tags = feature_operation_definition_tags(identity)
    schedule_tags = feature_operation_launch_tags(identity, trigger_kind="schedule")

    assert FEATURE_OPERATION_TRIGGER_TAG not in definition_tags
    assert schedule_tags[FEATURE_OPERATION_TRIGGER_TAG] == "schedule"
    assert schedule_tags[FEATURE_OPERATION_PROVIDER_TAG] == "python-opinet-api"


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (
            {
                FEATURE_UPDATE_REQUEST_ID_TAG: "request",
                ADMIN_MANUAL_TRIGGER_TAG: "1",
            },
            "update_request",
        ),
        ({ADMIN_MANUAL_TRIGGER_TAG: "1", DAGSTER_SCHEDULE_NAME_TAG: "schedule"}, "manual"),
        ({DAGSTER_SCHEDULE_NAME_TAG: "schedule", DAGSTER_SENSOR_NAME_TAG: "sensor"}, "schedule"),
        ({DAGSTER_SENSOR_NAME_TAG: "sensor", DAGSTER_BACKFILL_ID_TAG: "backfill"}, "sensor"),
        ({DAGSTER_BACKFILL_ID_TAG: "backfill", INTERNAL_SYSTEM_TRIGGER_TAG: "1"}, "backfill"),
        ({INTERNAL_SYSTEM_TRIGGER_TAG: "1"}, "system"),
        ({}, "manual"),
    ],
)
def test_trigger_resolution_priority_and_manual_fallback(
    tags: dict[str, str],
    expected: str,
) -> None:
    identity = _resolved(job_name="feature_place_opinet_stations_job")
    assert resolve_feature_operation_trigger(identity, tags) == expected


def test_trigger_resolution_rejects_blank_and_unknown_signals() -> None:
    identity = _resolved(job_name="feature_place_opinet_stations_job")
    with pytest.raises(FeatureOperationRegistryError, match="비어"):
        resolve_feature_operation_trigger(identity, {DAGSTER_SCHEDULE_NAME_TAG: " "})
    with pytest.raises(FeatureOperationRegistryError, match="알 수 없음"):
        resolve_feature_operation_trigger(
            identity,
            {FEATURE_OPERATION_TRIGGER_TAG: "legacy_unknown"},
        )
