"""krtour-map Dagster definitions smoke test."""

from __future__ import annotations

import pytest
from dagster import DefaultScheduleStatus

from krtour.map_dagster.definitions import defs
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
    } <= asset_keys


def test_feature_update_job_and_sensors_registered() -> None:
    assert defs.get_job_def("feature_update_request_worker").name == (
        "feature_update_request_worker"
    )
    assert defs.get_job_def("consistency_dedup_refresh").name == (
        "consistency_dedup_refresh"
    )
    assert defs.resolve_sensor_def("feature_update_request_queue_sensor").name == (
        "feature_update_request_queue_sensor"
    )
    assert defs.resolve_sensor_def("feature_update_request_failure_sensor").name == (
        "feature_update_request_failure_sensor"
    )


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


def test_consistency_dedup_refresh_schedule_registered() -> None:
    schedule = defs.resolve_schedule_def("consistency_dedup_refresh_daily_schedule")
    assert schedule.name == "consistency_dedup_refresh_daily_schedule"
    assert schedule.cron_schedule == "45 5 * * *"
    assert schedule.execution_timezone == KST_TIMEZONE
    assert schedule.default_status == DefaultScheduleStatus.STOPPED
    assert schedule.job_name == "consistency_dedup_refresh"
    assert schedule.tags["krtour_map.job_scope"] == "maintenance"
    assert schedule.tags["krtour_map.job_kind"] == "consistency_dedup_refresh"
