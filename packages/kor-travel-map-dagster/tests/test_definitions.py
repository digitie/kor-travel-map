"""kor-travel-map Dagster definitions smoke test."""

from __future__ import annotations

import pytest
from dagster import (
    MAX_RUNTIME_SECONDS_TAG,
    DagsterInstance,
    DagsterRunStatus,
    DefaultScheduleStatus,
    build_schedule_context,
)
from dagster._core.remote_origin import (
    RegisteredCodeLocationOrigin,
    RemoteJobOrigin,
    RemoteRepositoryOrigin,
)
from kortravelmap.providers.datagokr_file_data import DATAGOKR_FILEDATA_DATASETS

from kortravelmap.dagster.assets import FEATURE_LOAD_ASSETS, FEATURE_LOAD_RETRY_POLICY
from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.resources import PROVIDER_RECORD_RESOURCE_SPECS
from kortravelmap.dagster.schedules import (
    FEATURE_LOAD_SCHEDULE_SPECS,
    FEATURE_LOAD_SCHEDULES,
    KST_TIMEZONE,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


def test_feature_load_asset_keys_registered() -> None:
    asset_keys = {
        key.to_user_string() for key in defs.resolve_asset_graph().get_all_asset_keys()
    }
    assert {
        "feature_event_datagokr_cultural_festivals",
        "feature_place_opinet_stations",
        "feature_price_opinet_stations",
        "feature_place_krex_rest_areas",
        "feature_price_krex_rest_areas",
        "feature_notice_krex_traffic_notices",
        "feature_place_krheritage_items",
        "feature_event_krheritage_events",
        "feature_place_mois_licenses",
        "feature_place_knps_points",
        "feature_geometry_knps_records",
        "feature_place_krforest_recreation_forests",
        "feature_place_krforest_arboretums",
        "feature_place_standard_museums",
        "feature_place_standard_tourist_attractions",
        "feature_place_standard_parking_lots",
        "feature_place_standard_special_streets",
        "feature_place_datagokr_file_data",
        "feature_place_khoa_beaches",
        "feature_place_krairport_airports",
        "feature_place_kor_travel_concierge_youtube",
        "feature_weather_airkorea_air_quality",
        "feature_weather_krex_rest_areas",
        "feature_weather_kma_ultra_short_nowcast",
        "feature_weather_kma_ultra_short_forecast",
        "feature_weather_kma_short_forecast",
        "feature_weather_kma_mid_forecast",
        "feature_notice_kma_weather_alerts",
        "feature_place_mcst_culture",
        "feature_event_visitkorea_enrichment",
        "curated_source_metadata",
        "curated_feature_candidates",
        "curated_feature_status_sweep",
        "curated_feature_detail_snapshots",
    } <= asset_keys


def test_feature_load_assets_have_retry_policy() -> None:
    for asset_def in FEATURE_LOAD_ASSETS:
        assert asset_def.op.retry_policy == FEATURE_LOAD_RETRY_POLICY


def test_feature_load_assets_have_provider_schedules() -> None:
    asset_keys = {
        key.to_user_string()
        for asset_def in FEATURE_LOAD_ASSETS
        for key in asset_def.keys
    }
    scheduled_asset_keys = {
        key.to_user_string()
        for spec in FEATURE_LOAD_SCHEDULE_SPECS
        for key in spec.asset.keys
    }

    assert asset_keys <= scheduled_asset_keys


def test_feature_update_job_and_sensors_registered() -> None:
    assert defs.get_job_def("feature_update_request_worker").name == (
        "feature_update_request_worker"
    )
    assert defs.get_job_def("consistency_dedup_refresh").name == (
        "consistency_dedup_refresh"
    )
    assert defs.get_job_def("cache_target_snapshot_gc").name == (
        "cache_target_snapshot_gc"
    )
    assert defs.get_job_def("current_weather_summary_refresh").name == (
        "current_weather_summary_refresh"
    )
    assert defs.get_job_def("full_load_batch_consistency_gate").name == (
        "full_load_batch_consistency_gate"
    )
    assert defs.get_job_def("offline_upload_load").name == "offline_upload_load"
    assert defs.get_job_def("mois_localdata_source_sync").name == (
        "mois_localdata_source_sync"
    )
    assert defs.resolve_job_def("curated_features_refresh").name == (
        "curated_features_refresh"
    )
    assert defs.resolve_sensor_def("feature_update_request_queue_sensor").name == (
        "feature_update_request_queue_sensor"
    )
    assert defs.resolve_sensor_def("feature_update_request_failure_sensor").name == (
        "feature_update_request_failure_sensor"
    )
    for sensor_name in (
        "feature_operation_queued_sensor",
        "feature_operation_starting_sensor",
        "feature_operation_started_sensor",
        "feature_operation_canceling_sensor",
        "feature_operation_success_sensor",
        "feature_operation_failure_sensor",
        "feature_operation_canceled_sensor",
        "feature_operation_reconciliation_sensor",
    ):
        assert defs.resolve_sensor_def(sensor_name).name == sensor_name


def test_feature_update_runner_default_resource_registered() -> None:
    top_level_resources = defs.get_repository_def().get_top_level_resources()

    resource_def = top_level_resources["feature_update_runner"]

    assert resource_def.description
    assert "asset dispatcher" in resource_def.description


def test_repository_loads_all_definitions() -> None:
    """repository 전체 로드 회귀 (#384).

    웹서버/데몬은 ``load_all_definitions``로 노드명 유일성까지 검증한다 —
    CLI materialize/execute는 이 경로를 타지 않아 op/job 동명 충돌(#384,
    mois Phase A)이 잠복했었다. 여기서 한 번 전체 로드해 CI에서 잡는다.
    """
    defs.get_repository_def().load_all_definitions()


def test_offline_upload_load_default_resources_registered() -> None:
    job = defs.get_job_def("offline_upload_load")
    assert {"kor_travel_map_client", "offline_upload_store"} <= set(
        job.required_resource_keys
    )
    assert defs.get_repository_def().get_top_level_resources()["kor_travel_map_client"]
    assert defs.get_repository_def().get_top_level_resources()["offline_upload_store"]


# T-RV-04b: provider별 live fetcher가 연결된 resource key. 나머지는 guard.
_LIVE_PROVIDER_RESOURCE_KEYS = {
    "datagokr_cultural_festivals",
    "opinet_stations",
    "opinet_station_price_details",
    "krex_rest_areas",
    "krex_rest_area_weather",
    "krex_rest_area_fuel_prices",
    "krex_traffic_notices",
    "krheritage_items",
    "krheritage_events",
    "mois_license_records",
    "knps_point_records",
    "knps_geometry_records",
    "krforest_recreation_forests",
    "krforest_arboretums",
    "standard_museums",
    "standard_tourist_attractions",
    "standard_parking_lots",
    "standard_special_streets",
    "datagokr_file_data_records",
    "khoa_beaches",
    "krairport_airports",
    "airkorea_stations",
    "airkorea_air_quality",
    "visitkorea_festival_events",
    "kor_travel_concierge_youtube_features",
    "kma_weather_alert_records",
    "mcst_culture_records",
}


def test_feature_load_provider_guard_resources_registered() -> None:
    top_level_resources = defs.get_repository_def().get_top_level_resources()

    operation_guard = top_level_resources["feature_operation_guard"]
    assert operation_guard.required_resource_keys == {"kor_travel_map_client"}
    for spec in FEATURE_LOAD_SCHEDULE_SPECS:
        assert "feature_operation_guard" in spec.asset.required_resource_keys

    for spec in PROVIDER_RECORD_RESOURCE_SPECS:
        resource_def = top_level_resources[spec.resource_key]
        assert resource_def.description
        if spec.resource_key in _LIVE_PROVIDER_RESOURCE_KEYS:
            assert "live fetcher" in resource_def.description
            assert {
                "feature_operation_guard",
                "kor_travel_map_client",
            } <= resource_def.required_resource_keys
        else:
            assert "provider record guard" in resource_def.description

    for resource_key in ("kma_weather_client_factory", "kma_datagokr_client"):
        assert {
            "feature_operation_guard",
            "kor_travel_map_client",
        } <= top_level_resources[resource_key].required_resource_keys
    assert top_level_resources["reverse_geocoder"]


def test_feature_load_schedules_registered_with_kst_cron() -> None:
    expected = {spec.schedule_name: spec for spec in FEATURE_LOAD_SCHEDULE_SPECS}
    assert len(FEATURE_LOAD_SCHEDULES) == len(expected)

    for schedule_name, spec in expected.items():
        schedule = defs.resolve_schedule_def(schedule_name)
        job = defs.resolve_job_def(spec.job_name)
        assert schedule.name == schedule_name
        assert schedule.cron_schedule == spec.cron_schedule
        assert schedule.execution_timezone == KST_TIMEZONE
        assert schedule.default_status == DefaultScheduleStatus.STOPPED
        assert schedule.job_name == spec.job_name
        assert schedule.tags["kor_travel_map.trigger_kind"] == "schedule"
        assert schedule.tags["kor_travel_map.operation_key"] == spec.job_name
        assert job.tags["kor_travel_map.operation_key"] == spec.job_name
        assert "kor_travel_map.schedule_scope" not in job.tags
        assert "kor_travel_map.schedule_scope" not in schedule.tags
        assert not any("provider" in key or "dataset" in key for key in schedule.tags)


def test_krex_traffic_notices_schedule_runs_every_ten_minutes() -> None:
    schedule = defs.resolve_schedule_def(
        "feature_notice_krex_traffic_notices_ten_minute_schedule"
    )

    assert schedule.cron_schedule == "*/10 * * * *"
    assert schedule.execution_timezone == KST_TIMEZONE
    assert schedule.default_status == DefaultScheduleStatus.STOPPED
    assert schedule.job_name == "feature_notice_krex_traffic_notices_job"
    assert schedule.tags["kor_travel_map.operation_key"] == schedule.job_name
    assert schedule.tags["kor_travel_map.trigger_kind"] == "schedule"


def test_krex_traffic_notices_schedule_coalesces_non_terminal_run() -> None:
    schedule = defs.resolve_schedule_def(
        "feature_notice_krex_traffic_notices_ten_minute_schedule"
    )
    job = defs.resolve_job_def("feature_notice_krex_traffic_notices_job")
    remote_origin = RemoteJobOrigin(
        RemoteRepositoryOrigin(
            RegisteredCodeLocationOrigin("test"),
            "__repository__",
        ),
        job.name,
    )

    with DagsterInstance.local_temp() as instance:
        for run_status in (
            DagsterRunStatus.QUEUED,
            DagsterRunStatus.NOT_STARTED,
            DagsterRunStatus.MANAGED,
            DagsterRunStatus.STARTING,
            DagsterRunStatus.STARTED,
            DagsterRunStatus.CANCELING,
        ):
            run = instance.create_run_for_job(
                job,
                status=run_status,
                tags={"kor_travel_map.operation_key": job.name},
                remote_job_origin=(
                    remote_origin if run_status == DagsterRunStatus.QUEUED else None
                ),
            )

            with build_schedule_context(instance=instance) as context:
                tick = schedule.evaluate_tick(context)

            assert tick.run_requests == []
            assert tick.skip_message is not None
            assert run_status.value in tick.skip_message
            instance.delete_run(run.run_id)


def test_krex_coalescing_ignores_untagged_run() -> None:
    schedule = defs.resolve_schedule_def(
        "feature_notice_krex_traffic_notices_ten_minute_schedule"
    )
    job = defs.resolve_job_def("feature_notice_krex_traffic_notices_job")

    with DagsterInstance.local_temp() as instance:
        instance.create_run_for_job(
            job,
            status=DagsterRunStatus.STARTED,
            tags={},
        )
        with build_schedule_context(instance=instance) as context:
            tick = schedule.evaluate_tick(context)

    assert tick.skip_message is None
    assert len(tick.run_requests) == 1


def test_krex_traffic_notices_schedule_requests_run_without_non_terminal_run() -> None:
    schedule = defs.resolve_schedule_def(
        "feature_notice_krex_traffic_notices_ten_minute_schedule"
    )
    job = defs.resolve_job_def("feature_notice_krex_traffic_notices_job")

    with DagsterInstance.local_temp() as instance:
        with build_schedule_context(instance=instance) as context:
            tick_without_runs = schedule.evaluate_tick(context)

        for terminal_status in (
            DagsterRunStatus.SUCCESS,
            DagsterRunStatus.FAILURE,
            DagsterRunStatus.CANCELED,
        ):
            instance.create_run_for_job(
                job,
                status=terminal_status,
                tags={"kor_travel_map.operation_key": job.name},
            )

        with build_schedule_context(instance=instance) as context:
            tick_with_terminal_runs = schedule.evaluate_tick(context)

    for tick in (tick_without_runs, tick_with_terminal_runs):
        assert tick.skip_message is None
        assert len(tick.run_requests) == 1
        assert tick.run_requests[0].tags["kor_travel_map.operation_key"] == job.name
        assert tick.run_requests[0].tags["kor_travel_map.trigger_kind"] == "schedule"


def test_freshness_sensitive_jobs_have_two_hour_runtime_tag() -> None:
    assert MAX_RUNTIME_SECONDS_TAG == "dagster/max_runtime"

    expected = {
        "feature_place_opinet_stations_job": (
            "feature_place_opinet_stations_monthly_schedule"
        ),
        "feature_price_opinet_stations_job": (
            "feature_price_opinet_stations_daily_schedule"
        ),
        "feature_notice_krex_traffic_notices_job": (
            "feature_notice_krex_traffic_notices_ten_minute_schedule"
        ),
    }
    for job_name, schedule_name in expected.items():
        job = defs.resolve_job_def(job_name)
        schedule = defs.resolve_schedule_def(schedule_name)
        assert job.tags[MAX_RUNTIME_SECONDS_TAG] == "7200"
        assert schedule.tags[MAX_RUNTIME_SECONDS_TAG] == "7200"


def test_datagokr_file_data_schedules_cover_all_curated_datasets() -> None:
    specs = {}
    for spec in FEATURE_LOAD_SCHEDULE_SPECS:
        run_config = spec.run_config
        if run_config is None:
            continue
        dataset_key = run_config["resources"]["datagokr_file_data_dataset_key"][
            "config"
        ]["dataset_key"]
        if dataset_key in DATAGOKR_FILEDATA_DATASETS:
            specs[dataset_key] = spec

    assert set(specs) == set(DATAGOKR_FILEDATA_DATASETS)

    for dataset_key, spec in specs.items():
        schedule = defs.resolve_schedule_def(spec.schedule_name)
        assert schedule.tags["kor_travel_map.operation_key"] == spec.job_name
        tick = schedule.evaluate_tick(build_schedule_context())
        assert len(tick.run_requests) == 1
        assert tick.run_requests[0].run_config == {
            "resources": {
                "datagokr_file_data_dataset_key": {
                    "config": {"dataset_key": dataset_key},
                },
                "datagokr_file_data_records": {
                    "config": {"dataset_key": dataset_key},
                },
            }
        }


def test_mois_localdata_source_sync_schedule_registered() -> None:
    schedule = defs.resolve_schedule_def("mois_localdata_source_sync_weekly_schedule")
    assert schedule.name == "mois_localdata_source_sync_weekly_schedule"
    assert schedule.cron_schedule == "0 4 * * 1"
    assert schedule.execution_timezone == KST_TIMEZONE
    assert schedule.default_status == DefaultScheduleStatus.STOPPED
    assert schedule.job_name == "mois_localdata_source_sync"
    assert schedule.tags["kor_travel_map.job_kind"] == "mois_localdata_source_sync"
    assert schedule.tags["kor_travel_map.provider"] == "python-mois-api"


def test_consistency_dedup_refresh_schedule_registered() -> None:
    schedule = defs.resolve_schedule_def("consistency_dedup_refresh_daily_schedule")
    assert schedule.name == "consistency_dedup_refresh_daily_schedule"
    assert schedule.cron_schedule == "45 5 * * *"
    assert schedule.execution_timezone == KST_TIMEZONE
    assert schedule.default_status == DefaultScheduleStatus.STOPPED
    assert schedule.job_name == "consistency_dedup_refresh"
    assert schedule.tags["kor_travel_map.job_scope"] == "maintenance"
    assert schedule.tags["kor_travel_map.job_kind"] == "consistency_dedup_refresh"


def test_cache_target_snapshot_gc_hourly_schedule_registered() -> None:
    schedule = defs.resolve_schedule_def("cache_target_snapshot_gc_hourly_schedule")
    assert schedule.name == "cache_target_snapshot_gc_hourly_schedule"
    assert schedule.cron_schedule == "15 * * * *"
    assert schedule.execution_timezone == KST_TIMEZONE
    assert schedule.default_status == DefaultScheduleStatus.STOPPED
    assert schedule.job_name == "cache_target_snapshot_gc"
    assert schedule.tags["kor_travel_map.job_scope"] == "maintenance"
    assert schedule.tags["kor_travel_map.job_kind"] == "cache_target_snapshot_gc"


def test_current_weather_summary_refresh_schedule_is_running_and_minutely() -> None:
    schedule = defs.resolve_schedule_def(
        "current_weather_summary_refresh_minutely_schedule"
    )
    assert schedule.name == "current_weather_summary_refresh_minutely_schedule"
    assert schedule.cron_schedule == "* * * * *"
    assert schedule.execution_timezone == KST_TIMEZONE
    assert schedule.default_status == DefaultScheduleStatus.RUNNING
    assert schedule.job_name == "current_weather_summary_refresh"
    assert schedule.tags["kor_travel_map.job_scope"] == "maintenance"
    assert schedule.tags["kor_travel_map.job_kind"] == "current_weather_summary_refresh"


def test_current_weather_summary_refresh_schedule_coalesces_active_global_run() -> None:
    schedule = defs.resolve_schedule_def(
        "current_weather_summary_refresh_minutely_schedule"
    )
    job = defs.resolve_job_def("current_weather_summary_refresh")
    with DagsterInstance.local_temp() as instance:
        instance.create_run_for_job(job, status=DagsterRunStatus.STARTED)
        with build_schedule_context(instance=instance) as context:
            tick = schedule.evaluate_tick(context)

    assert tick.run_requests == []
    assert tick.skip_message is not None
    assert "STARTED" in tick.skip_message


def test_curated_features_refresh_schedule_registered() -> None:
    schedule = defs.resolve_schedule_def("curated_features_refresh_daily_schedule")
    assert schedule.name == "curated_features_refresh_daily_schedule"
    assert schedule.cron_schedule == "55 4 * * *"
    assert schedule.execution_timezone == KST_TIMEZONE
    assert schedule.default_status == DefaultScheduleStatus.STOPPED
    assert schedule.job_name == "curated_features_refresh"
    assert schedule.tags["kor_travel_map.job_scope"] == "curated_features"
    assert schedule.tags["kor_travel_map.job_kind"] == "curated_features_refresh"
    assert schedule.tags["kor_travel_map.schedule_scope"] == "system"
