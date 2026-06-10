"""Provider Feature 적재 Dagster schedule 정의."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from dagster import AssetsDefinition, DefaultScheduleStatus, ScheduleDefinition, define_asset_job

from .assets import (
    feature_event_datagokr_cultural_festivals,
    feature_event_krheritage_events,
    feature_geometry_knps_records,
    feature_notice_krex_traffic_notices,
    feature_place_knps_points,
    feature_place_krex_rest_areas,
    feature_place_krheritage_items,
    feature_place_mois_licenses,
    feature_place_opinet_stations,
    feature_place_tripmate_agent_youtube,
)

KST_TIMEZONE: Final[str] = "Asia/Seoul"
"""Dagster provider schedule execution timezone."""

SYSTEM_SCHEDULE_TAGS: Final[dict[str, str]] = {
    "krtour_map.schedule_scope": "system",
    "krtour_map.timezone": KST_TIMEZONE,
}


@dataclass(frozen=True)
class FeatureLoadScheduleSpec:
    """Feature load asset 1개에 대응하는 provider schedule spec."""

    asset: AssetsDefinition
    job_name: str
    schedule_name: str
    cron_schedule: str
    provider: str
    dataset_key: str
    description: str


FEATURE_LOAD_SCHEDULE_SPECS: Final[tuple[FeatureLoadScheduleSpec, ...]] = (
    FeatureLoadScheduleSpec(
        asset=feature_event_datagokr_cultural_festivals,
        job_name="feature_event_datagokr_cultural_festivals_job",
        schedule_name="feature_event_datagokr_cultural_festivals_daily_schedule",
        cron_schedule="10 3 * * *",
        provider="data.go.kr-standard",
        dataset_key="datagokr_cultural_festivals",
        description="전국문화축제표준데이터 event Feature 일 1회 야간 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_opinet_stations,
        job_name="feature_place_opinet_stations_job",
        schedule_name="feature_place_opinet_stations_monthly_schedule",
        cron_schedule="5 3 1 * *",
        provider="opinet",
        dataset_key="opinet_fuel_station_details",
        description="OpiNet 주유소 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_krex_rest_areas,
        job_name="feature_place_krex_rest_areas_job",
        schedule_name="feature_place_krex_rest_areas_monthly_schedule",
        cron_schedule="20 2 1 * *",
        provider="krex",
        dataset_key="krex_rest_areas",
        description="고속도로 휴게소 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_notice_krex_traffic_notices,
        job_name="feature_notice_krex_traffic_notices_job",
        schedule_name="feature_notice_krex_traffic_notices_quarter_hour_schedule",
        cron_schedule="7,22,37,52 * * * *",
        provider="krex",
        dataset_key="krex_traffic_notices",
        description="고속도로 교통공지 notice Feature 15분 간격 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_krheritage_items,
        job_name="feature_place_krheritage_items_job",
        schedule_name="feature_place_krheritage_items_weekly_schedule",
        cron_schedule="15 2 * * 1",
        provider="krheritage",
        dataset_key="krheritage_heritage_features",
        description="국가유산 item place/area Feature 주 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_event_krheritage_events,
        job_name="feature_event_krheritage_events_job",
        schedule_name="feature_event_krheritage_events_daily_schedule",
        cron_schedule="25 3 * * *",
        provider="krheritage",
        dataset_key="krheritage_event_list",
        description="국가유산 행사 event Feature 일 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_mois_licenses,
        job_name="feature_place_mois_licenses_job",
        schedule_name="feature_place_mois_licenses_weekly_schedule",
        cron_schedule="35 4 * * 1",
        provider="mois",
        dataset_key="mois_license_features_bulk",
        description="MOIS 인허가 place Feature 주 1회 bulk 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_knps_points,
        job_name="feature_place_knps_points_job",
        schedule_name="feature_place_knps_points_semiannual_schedule",
        cron_schedule="45 3 1 1,7 *",
        provider="knps",
        dataset_key="knps_point_dataset_key",
        description="국립공원 point/place Feature 반기 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_geometry_knps_records,
        job_name="feature_geometry_knps_records_job",
        schedule_name="feature_geometry_knps_records_semiannual_schedule",
        cron_schedule="15 4 1 1,7 *",
        provider="knps",
        dataset_key="knps_geometry_dataset_key",
        description="국립공원 route/area geometry Feature 반기 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_tripmate_agent_youtube,
        job_name="feature_place_tripmate_agent_youtube_job",
        schedule_name="feature_place_tripmate_agent_youtube_daily_schedule",
        cron_schedule="40 3 * * *",
        provider="tripmate-agent-youtube",
        dataset_key="youtube_place_candidates",
        description="TripMate-agent YouTube 장소 후보 place Feature 일 1회 적재.",
    ),
)
"""현재 구현된 Feature provider asset의 기본 schedule 사양."""


FEATURE_LOAD_JOBS: Final = [
    define_asset_job(
        spec.job_name,
        selection=[spec.asset],
        description=spec.description,
        tags={
            **SYSTEM_SCHEDULE_TAGS,
            "krtour_map.provider": spec.provider,
            "krtour_map.dataset_key": spec.dataset_key,
        },
    )
    for spec in FEATURE_LOAD_SCHEDULE_SPECS
]
"""정기 Feature 적재 schedule이 실행하는 asset job 목록."""


FEATURE_LOAD_SCHEDULES: Final = [
    ScheduleDefinition(
        name=spec.schedule_name,
        job=job,
        cron_schedule=spec.cron_schedule,
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags={
            **SYSTEM_SCHEDULE_TAGS,
            "krtour_map.provider": spec.provider,
            "krtour_map.dataset_key": spec.dataset_key,
        },
        description=spec.description,
    )
    for spec, job in zip(FEATURE_LOAD_SCHEDULE_SPECS, FEATURE_LOAD_JOBS, strict=True)
]
"""Provider별 KST cron schedule 목록."""
