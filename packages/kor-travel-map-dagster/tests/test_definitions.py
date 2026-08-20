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
from kortravelmap.providers.knps import PROVIDER_NAME as KNPS_PROVIDER_NAME
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster.assets import FEATURE_LOAD_ASSETS, FEATURE_LOAD_RETRY_POLICY
from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.feature_operation_tracking import (
    EXECUTION_SCOPES_TAG,
    DeclaredExecutionScope,
    declared_execution_scopes,
)
from kortravelmap.dagster.resources import PROVIDER_RECORD_RESOURCE_SPECS
from kortravelmap.dagster.schedules import (
    _KNPS_GEOMETRY_SCHEDULE,
    _KNPS_POINT_SCHEDULE,
    FEATURE_LOAD_SCHEDULE_SPECS,
    FEATURE_LOAD_SCHEDULES,
    KST_TIMEZONE,
    knps_schedule_binding,
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
        "feature_route_krforest_mountain_trails",
        "feature_route_krforest_dulle_trails",
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
        "feature_weather_krforest_mountain_weather",
        "feature_weather_krforest_wildfire_risk_forecast",
        "feature_notice_krforest_landslide_forecast_issues",
        "feature_place_mcst_culture",
        "feature_event_visitkorea_enrichment",
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
    "krforest_mountain_trails",
    "krforest_dulle_trails",
    "krforest_mountain_weather",
    "krforest_wildfire_risk_forecast",
    "krforest_landslide_forecast_issues",
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


def test_job_definition_tags_carry_the_execution_manifest_declaration() -> None:
    """실행 manifest 선언은 **job 정의 tag**에도 실려야 한다.

    schedule tag는 schedule이 띄운 run에만 붙는다. schedule을 거치지 않는 job 단위
    launch(admin UI "지금 실행" → GraphQL)의 run tag는 job 정의 tag에서 온다. 선언이
    정의 tag에 없으면 그 run만 manifest가 operation 전체로 넓어져, guard가 실행하지도
    않을 member까지 running으로 만든다.

    그래서 여기서는 helper가 아니라 **빌드된 job 정의 객체**(``defs.resolve_job_def``)
    의 tag를 본다 — helper만 보면 ``define_asset_job(tags=...)`` 연결이 끊겨도 통과한다.
    """
    declaring = [spec for spec in FEATURE_LOAD_SCHEDULE_SPECS if spec.execution_scopes]
    # 선언하는 spec이 하나도 없으면 아래 루프가 공회전한다 — 전제를 단언으로 박는다.
    assert {spec.job_name for spec in declaring} == {
        "feature_place_knps_points_job",
        "feature_geometry_knps_records_job",
        "feature_weather_kma_ultra_short_nowcast_job",
        "feature_weather_kma_ultra_short_forecast_job",
        "feature_weather_kma_short_forecast_job",
    }
    for spec in declaring:
        job_tags = defs.resolve_job_def(spec.job_name).tags
        schedule_tags = defs.resolve_schedule_def(spec.schedule_name).tags
        assert EXECUTION_SCOPES_TAG in job_tags, (
            f"{spec.job_name} 정의 tag에 실행 manifest 선언이 없다 — "
            "수동 launch가 operation 전체를 manifest로 잡는다"
        )
        assert job_tags[EXECUTION_SCOPES_TAG] == schedule_tags[EXECUTION_SCOPES_TAG]
        assert (
            declared_execution_scopes(job_tags, boundary="test") == spec.execution_scopes
        )


def test_specs_without_declaration_leave_the_manifest_tag_off() -> None:
    """선언이 없는 spec은 tag를 붙이지 않는다 — 빈 선언으로 죽이지 않는다.

    ``declared_execution_scopes``는 tag 부재를 "operation 전체가 manifest"로 읽고,
    빈 리스트는 ``execution_scopes_tag_malformed``로 거부한다. 1:1 operation이 빈
    tag를 달면 전부 그 자리에서 죽는다.
    """
    for spec in FEATURE_LOAD_SCHEDULE_SPECS:
        if spec.execution_scopes:
            continue
        assert EXECUTION_SCOPES_TAG not in defs.resolve_job_def(spec.job_name).tags
        assert EXECUTION_SCOPES_TAG not in defs.resolve_schedule_def(spec.schedule_name).tags


def test_knps_schedule_binding_follows_the_operator_dataset_key_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``KOR_TRAVEL_MAP_KNPS_*_DATASET_KEY`` 노브가 살아 있고, 한 값만 낳는다.

    schedule이 run_config로 dataset을 고정하면서 이 노브는 죽을 수 있었다 —
    ``knps_*_dataset_key``·``knps_*_records`` resource가 둘 다 run_config를 먼저
    보기 때문이다. 그래서 run_config와 실행 manifest 선언을 같은 읽기에서 만든다.
    이 테스트는 노브를 눌렀을 때 (1) run_config가 따라오고 (2) 선언이 **같은**
    dataset을 가리키는지를 함께 본다.
    """
    monkeypatch.setenv("KOR_TRAVEL_MAP_KNPS_POINT_DATASET_KEY", "knps_campgrounds")

    binding = knps_schedule_binding(
        setting_name="knps_point_dataset_key",
        dataset_key_resource="knps_point_dataset_key",
        records_resource="knps_point_records",
    )

    assert binding.dataset_key == "knps_campgrounds"
    assert binding.run_config == {
        "resources": {
            "knps_point_dataset_key": {"config": {"dataset_key": "knps_campgrounds"}},
            "knps_point_records": {"config": {"dataset_key": "knps_campgrounds"}},
        }
    }
    assert binding.execution_scopes == (
        DeclaredExecutionScope(
            provider=KNPS_PROVIDER_NAME,
            dataset_key="knps_campgrounds",
            sync_scope="dataset_wide",
        ),
    )


def test_knps_schedule_specs_use_the_settings_dataset_key() -> None:
    """schedule이 쓰는 KNPS dataset key는 settings 값과 **같은 객체에서** 나온다.

    예전에는 ``schedules``에 상수 사본이 있어 ``settings`` 기본값과 갈라질 수 있었다.
    지금은 사본이 없다는 것을 여기서 못 박는다.
    """
    settings = KorTravelMapSettings()
    assert _KNPS_POINT_SCHEDULE.dataset_key == settings.knps_point_dataset_key
    assert _KNPS_GEOMETRY_SCHEDULE.dataset_key == settings.knps_geometry_dataset_key

    specs = {spec.job_name: spec for spec in FEATURE_LOAD_SCHEDULE_SPECS}
    point = specs["feature_place_knps_points_job"]
    geometry = specs["feature_geometry_knps_records_job"]
    assert point.run_config == _KNPS_POINT_SCHEDULE.run_config
    assert point.execution_scopes == _KNPS_POINT_SCHEDULE.execution_scopes
    assert geometry.run_config == _KNPS_GEOMETRY_SCHEDULE.run_config
    assert geometry.execution_scopes == _KNPS_GEOMETRY_SCHEDULE.execution_scopes


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
        # run_config를 가진 spec이 datagokr뿐이라고 가정하지 않는다 — KNPS schedule도
        # 실행 dataset을 run_config로 고정한다.
        datagokr_config = run_config["resources"].get("datagokr_file_data_dataset_key")
        if datagokr_config is None:
            continue
        dataset_key = datagokr_config["config"]["dataset_key"]
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
