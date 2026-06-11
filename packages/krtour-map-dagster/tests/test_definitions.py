"""krtour-map Dagster definitions smoke test."""

from __future__ import annotations

import pytest
from dagster import DefaultScheduleStatus

from krtour.map_dagster.assets import FEATURE_LOAD_ASSETS, FEATURE_LOAD_RETRY_POLICY
from krtour.map_dagster.definitions import defs
from krtour.map_dagster.resources import PROVIDER_RECORD_RESOURCE_SPECS
from krtour.map_dagster.schedules import (
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
        "feature_place_krex_rest_areas",
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
        "feature_place_khoa_beaches",
        "feature_place_krairport_airports",
        "feature_place_tripmate_agent_youtube",
        "feature_weather_airkorea_air_quality",
        "feature_weather_kma_ultra_short_nowcast",
        "feature_weather_kma_ultra_short_forecast",
        "feature_weather_kma_short_forecast",
        "feature_weather_kma_mid_forecast",
        "feature_notice_kma_weather_alerts",
        "feature_place_mcst_culture",
        "feature_place_mcst_libraries",
        "feature_event_visitkorea_enrichment",
    } <= asset_keys


def test_feature_load_assets_have_retry_policy() -> None:
    for asset_def in FEATURE_LOAD_ASSETS:
        assert asset_def.op.retry_policy == FEATURE_LOAD_RETRY_POLICY


def test_feature_update_job_and_sensors_registered() -> None:
    assert defs.get_job_def("feature_update_request_worker").name == (
        "feature_update_request_worker"
    )
    assert defs.get_job_def("consistency_dedup_refresh").name == (
        "consistency_dedup_refresh"
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


def test_repository_loads_all_definitions() -> None:
    """repository 전체 로드 회귀 (#384).

    웹서버/데몬은 ``load_all_definitions``로 노드명 유일성까지 검증한다 —
    CLI materialize/execute는 이 경로를 타지 않아 op/job 동명 충돌(#384,
    mois Phase A)이 잠복했었다. 여기서 한 번 전체 로드해 CI에서 잡는다.
    """
    defs.get_repository_def().load_all_definitions()


def test_offline_upload_load_default_resources_registered() -> None:
    job = defs.get_job_def("offline_upload_load")
    assert {"krtour_map_client", "offline_upload_store"} <= set(
        job.required_resource_keys
    )
    assert defs.get_repository_def().get_top_level_resources()["krtour_map_client"]
    assert defs.get_repository_def().get_top_level_resources()["offline_upload_store"]


# T-RV-04b: provider별 live fetcher가 연결된 resource key. 나머지는 guard.
_LIVE_PROVIDER_RESOURCE_KEYS = {
    "datagokr_cultural_festivals",
    "opinet_stations",
    "krex_rest_areas",
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
    "khoa_beaches",
    "krairport_airports",
    "airkorea_stations",
    "airkorea_air_quality",
    "visitkorea_festival_events",
    "tripmate_agent_youtube_features",
    "kma_weather_alert_records",
    "mcst_culture_records",
    "mcst_library_records",
}


def test_feature_load_provider_guard_resources_registered() -> None:
    top_level_resources = defs.get_repository_def().get_top_level_resources()

    for spec in PROVIDER_RECORD_RESOURCE_SPECS:
        resource_def = top_level_resources[spec.resource_key]
        assert resource_def.description
        if spec.resource_key in _LIVE_PROVIDER_RESOURCE_KEYS:
            assert "live fetcher" in resource_def.description
        else:
            assert "provider record guard" in resource_def.description

    assert top_level_resources["reverse_geocoder"]


def test_feature_load_schedules_registered_with_kst_cron() -> None:
    expected = {
        spec.schedule_name: spec for spec in FEATURE_LOAD_SCHEDULE_SPECS
    }
    assert len(FEATURE_LOAD_SCHEDULES) == len(expected)

    for schedule_name, spec in expected.items():
        schedule = defs.resolve_schedule_def(schedule_name)
        assert schedule.name == schedule_name
        assert schedule.cron_schedule == spec.cron_schedule
        assert schedule.execution_timezone == KST_TIMEZONE
        assert schedule.default_status == DefaultScheduleStatus.STOPPED
        assert schedule.job_name == spec.job_name
        assert schedule.tags["krtour_map.schedule_scope"] == "system"
        assert schedule.tags["krtour_map.provider"] == spec.provider
        assert schedule.tags["krtour_map.dataset_key"] == spec.dataset_key


def test_mois_localdata_source_sync_schedule_registered() -> None:
    schedule = defs.resolve_schedule_def("mois_localdata_source_sync_weekly_schedule")
    assert schedule.name == "mois_localdata_source_sync_weekly_schedule"
    assert schedule.cron_schedule == "0 4 * * 1"
    assert schedule.execution_timezone == KST_TIMEZONE
    assert schedule.default_status == DefaultScheduleStatus.STOPPED
    assert schedule.job_name == "mois_localdata_source_sync"
    assert schedule.tags["krtour_map.job_kind"] == "mois_localdata_source_sync"
    assert schedule.tags["krtour_map.provider"] == "python-mois-api"


def test_consistency_dedup_refresh_schedule_registered() -> None:
    schedule = defs.resolve_schedule_def("consistency_dedup_refresh_daily_schedule")
    assert schedule.name == "consistency_dedup_refresh_daily_schedule"
    assert schedule.cron_schedule == "45 5 * * *"
    assert schedule.execution_timezone == KST_TIMEZONE
    assert schedule.default_status == DefaultScheduleStatus.STOPPED
    assert schedule.job_name == "consistency_dedup_refresh"
    assert schedule.tags["krtour_map.job_scope"] == "maintenance"
    assert schedule.tags["krtour_map.job_kind"] == "consistency_dedup_refresh"
