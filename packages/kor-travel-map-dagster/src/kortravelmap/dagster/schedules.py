"""Provider Feature 적재 Dagster schedule 정의."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from kortravelmap.providers.datagokr_file_data import (
    DATAGOKR_FILEDATA_DATASETS,
    DATAGOKR_FILEDATA_PROVIDER_NAME,
)

from dagster import AssetsDefinition, DefaultScheduleStatus, ScheduleDefinition, define_asset_job

from .assets import (
    feature_event_datagokr_cultural_festivals,
    feature_event_krheritage_events,
    feature_event_visitkorea_enrichment,
    feature_geometry_knps_records,
    feature_notice_krex_traffic_notices,
    feature_place_datagokr_file_data,
    feature_place_khoa_beaches,
    feature_place_knps_points,
    feature_place_kor_travel_concierge_youtube,
    feature_place_krairport_airports,
    feature_place_krex_rest_areas,
    feature_place_krforest_arboretums,
    feature_place_krforest_recreation_forests,
    feature_place_krheritage_items,
    feature_place_mois_licenses,
    feature_place_opinet_stations,
    feature_place_standard_museums,
    feature_place_standard_parking_lots,
    feature_place_standard_special_streets,
    feature_place_standard_tourist_attractions,
    feature_price_krex_rest_areas,
    feature_price_opinet_stations,
    feature_weather_airkorea_air_quality,
    feature_weather_krex_rest_areas,
)
from .kma_weather import (
    feature_notice_kma_weather_alerts,
    feature_weather_kma_mid_forecast,
    feature_weather_kma_short_forecast,
    feature_weather_kma_ultra_short_forecast,
    feature_weather_kma_ultra_short_nowcast,
)
from .mcst_features import (
    feature_place_mcst_culture,
)
from .schedule_overrides import cron_for_schedule

KST_TIMEZONE: Final[str] = "Asia/Seoul"
"""Dagster provider schedule execution timezone."""

SYSTEM_SCHEDULE_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.schedule_scope": "system",
    "kor_travel_map.timezone": KST_TIMEZONE,
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
    run_config: Mapping[str, Any] | None = None


_DATAGOKR_FILEDATA_MONTHLY_CRONS: Final[tuple[str, ...]] = (
    "52 4 4 * *",
    "53 4 4 * *",
    "54 4 4 * *",
    "56 4 4 * *",
)
"""curated fileData 4개 dataset을 매월 4일 새벽에 순차 적재한다."""


def _datagokr_file_data_run_config(dataset_key: str) -> dict[str, Any]:
    return {
        "resources": {
            "datagokr_file_data_dataset_key": {
                "config": {"dataset_key": dataset_key},
            },
            "datagokr_file_data_records": {
                "config": {"dataset_key": dataset_key},
            },
        }
    }


def _datagokr_file_data_schedule_specs() -> tuple[FeatureLoadScheduleSpec, ...]:
    return tuple(
        FeatureLoadScheduleSpec(
            asset=feature_place_datagokr_file_data,
            job_name=f"feature_place_{dataset_key}_job",
            schedule_name=f"feature_place_{dataset_key}_monthly_schedule",
            cron_schedule=cron_schedule,
            provider=DATAGOKR_FILEDATA_PROVIDER_NAME,
            dataset_key=dataset_key,
            description=(
                f"data.go.kr curated fileData {dataset.label} place Feature 월 1회 적재."
            ),
            run_config=_datagokr_file_data_run_config(dataset_key),
        )
        for cron_schedule, (dataset_key, dataset) in zip(
            _DATAGOKR_FILEDATA_MONTHLY_CRONS,
            DATAGOKR_FILEDATA_DATASETS.items(),
            strict=True,
        )
    )


FEATURE_LOAD_SCHEDULE_SPECS: Final[tuple[FeatureLoadScheduleSpec, ...]] = (
    FeatureLoadScheduleSpec(
        asset=feature_event_datagokr_cultural_festivals,
        job_name="feature_event_datagokr_cultural_festivals_job",
        schedule_name="feature_event_datagokr_cultural_festivals_monthly_schedule",
        cron_schedule="10 3 1 * *",
        provider="data.go.kr-standard",
        dataset_key="datagokr_cultural_festivals",
        description="전국문화축제표준데이터 event Feature 월 1회 야간 적재.",
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
        asset=feature_price_opinet_stations,
        job_name="feature_price_opinet_stations_job",
        schedule_name="feature_price_opinet_stations_daily_schedule",
        # #545: low_top_area scope의 lowTop10/aroundAll 호출이 OpiNet 무료키 일일
        # 한도(1,500/일)를 압박하므로 가격 적재를 1일 1회로 낮춘다. fetcher의
        # run당 hard budget(_OPINET_RUN_CALL_BUDGET=600)과 함께 두 layer 가드로
        # 월간 place job과 같은 날 겹쳐도 한도 아래를 유지한다.
        cron_schedule="18 18 * * *",
        provider="opinet",
        dataset_key="opinet_gas_station_prices",
        description="OpiNet 주유소 price Feature + PriceValue 일 1회 적재(scope 기반).",
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
        asset=feature_price_krex_rest_areas,
        job_name="feature_price_krex_rest_areas_job",
        schedule_name="feature_price_krex_rest_areas_twice_daily_schedule",
        cron_schedule="28 6,18 * * *",
        provider="krex",
        dataset_key="krex_rest_area_prices",
        description="KREX 휴게소 유가 price Feature + PriceValue 일 2회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_notice_krex_traffic_notices,
        job_name="feature_notice_krex_traffic_notices_job",
        schedule_name="feature_notice_krex_traffic_notices_monthly_schedule",
        cron_schedule="7 3 1 * *",
        provider="krex",
        dataset_key="krex_traffic_notices",
        description="고속도로 교통공지 notice Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_weather_krex_rest_areas,
        job_name="feature_weather_krex_rest_areas_job",
        schedule_name="feature_weather_krex_rest_areas_hourly_schedule",
        cron_schedule="35 * * * *",
        provider="krex",
        dataset_key="krex_rest_area_weather",
        description="고속도로 휴게소 관측 기상 weather Feature 매시 적재(기온→T1H, KMA 빈틈 보강).",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_krheritage_items,
        job_name="feature_place_krheritage_items_job",
        schedule_name="feature_place_krheritage_items_monthly_schedule",
        cron_schedule="15 2 2 * *",
        provider="krheritage",
        dataset_key="krheritage_heritage_features",
        description="국가유산 item place/area Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_event_krheritage_events,
        job_name="feature_event_krheritage_events_job",
        schedule_name="feature_event_krheritage_events_monthly_schedule",
        cron_schedule="25 3 2 * *",
        provider="krheritage",
        dataset_key="krheritage_event_list",
        description="국가유산 행사 event Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_mois_licenses,
        job_name="feature_place_mois_licenses_job",
        schedule_name="feature_place_mois_licenses_monthly_schedule",
        cron_schedule="35 4 2 * *",
        provider="mois",
        dataset_key="mois_license_features_bulk",
        description="MOIS 인허가 place Feature 월 1회 bulk 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_knps_points,
        job_name="feature_place_knps_points_job",
        schedule_name="feature_place_knps_points_monthly_schedule",
        cron_schedule="45 3 3 * *",
        provider="knps",
        dataset_key="knps_point_dataset_key",
        description="국립공원 point/place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_geometry_knps_records,
        job_name="feature_geometry_knps_records_job",
        schedule_name="feature_geometry_knps_records_monthly_schedule",
        cron_schedule="15 4 3 * *",
        provider="knps",
        dataset_key="knps_geometry_dataset_key",
        description="국립공원 route/area geometry Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_krforest_recreation_forests,
        job_name="feature_place_krforest_recreation_forests_job",
        schedule_name="feature_place_krforest_recreation_forests_monthly_schedule",
        cron_schedule="5 4 4 * *",
        provider="python-krforest-api",
        dataset_key="krforest_recreation_forests",
        description="전국 자연휴양림 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_krforest_arboretums,
        job_name="feature_place_krforest_arboretums_job",
        schedule_name="feature_place_krforest_arboretums_monthly_schedule",
        cron_schedule="15 4 4 * *",
        provider="python-krforest-api",
        dataset_key="krforest_arboretums",
        description="휴양림 수목원 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_standard_museums,
        job_name="feature_place_standard_museums_job",
        schedule_name="feature_place_standard_museums_monthly_schedule",
        cron_schedule="25 4 4 * *",
        provider="data.go.kr-standard",
        dataset_key="datagokr_museums",
        description="전국박물관미술관표준데이터 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_standard_tourist_attractions,
        job_name="feature_place_standard_tourist_attractions_job",
        schedule_name="feature_place_standard_tourist_attractions_monthly_schedule",
        cron_schedule="35 4 4 * *",
        provider="data.go.kr-standard",
        dataset_key="datagokr_tourist_attractions",
        description="전국관광지표준데이터 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_standard_parking_lots,
        job_name="feature_place_standard_parking_lots_job",
        schedule_name="feature_place_standard_parking_lots_monthly_schedule",
        cron_schedule="45 4 4 * *",
        provider="data.go.kr-standard",
        dataset_key="datagokr_parking_lots",
        description="전국주차장표준데이터 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_standard_special_streets,
        job_name="feature_place_standard_special_streets_job",
        schedule_name="feature_place_standard_special_streets_monthly_schedule",
        cron_schedule="50 4 4 * *",
        provider="data.go.kr-standard",
        dataset_key="standard_special_streets",
        description="전국지역특화거리표준데이터 place anchor Feature 월 1회 적재.",
    ),
    *_datagokr_file_data_schedule_specs(),
    FeatureLoadScheduleSpec(
        asset=feature_place_khoa_beaches,
        job_name="feature_place_khoa_beaches_job",
        schedule_name="feature_place_khoa_beaches_monthly_schedule",
        cron_schedule="55 4 4 * *",
        provider="python-khoa-api",
        dataset_key="khoa_beaches",
        description="해양수산부 해수욕장정보 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_krairport_airports,
        job_name="feature_place_krairport_airports_job",
        schedule_name="feature_place_krairport_airports_monthly_schedule",
        cron_schedule="5 5 4 * *",
        provider="python-krairport-api",
        dataset_key="krairport_airports",
        description="공항 메타데이터 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_place_kor_travel_concierge_youtube,
        job_name="feature_place_kor_travel_concierge_youtube_job",
        schedule_name="feature_place_kor_travel_concierge_youtube_monthly_schedule",
        cron_schedule="40 3 3 * *",
        provider="kor-travel-concierge-youtube",
        dataset_key="youtube_place_candidates",
        description="kor-travel-concierge YouTube 장소 후보 place Feature 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_event_visitkorea_enrichment,
        job_name="feature_event_visitkorea_enrichment_job",
        schedule_name="feature_event_visitkorea_enrichment_monthly_schedule",
        cron_schedule="50 4 1 * *",
        provider="python-visitkorea-api",
        dataset_key="visitkorea_festival_events",
        description="VisitKorea 축제 enrichment review 월 1회 적재.",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_weather_airkorea_air_quality,
        job_name="feature_weather_airkorea_air_quality_job",
        schedule_name="feature_weather_airkorea_air_quality_hourly_schedule",
        cron_schedule="10 * * * *",
        provider="python-airkorea-api",
        dataset_key="airkorea_air_quality",
        description="AirKorea 대기질 weather Feature + WeatherValue 매시 적재.",
    ),
    # KMA weather 3종 (T-219b) — 발표 스케줄 + 가용 지연(docs/etl/kma-weather-etl.md §6)
    # 에 맞춘 cron. 같은 base 재실행은 provider_sync_state cursor가 skip한다.
    FeatureLoadScheduleSpec(
        asset=feature_weather_kma_ultra_short_nowcast,
        job_name="feature_weather_kma_ultra_short_nowcast_job",
        schedule_name="feature_weather_kma_ultra_short_nowcast_hourly_schedule",
        cron_schedule="45 * * * *",
        provider="python-kma-api",
        dataset_key="kma_ultra_short_nowcast",
        description="KMA 초단기실황 WeatherValue 매시 적재(발표 HH:00 + 40분 지연 후).",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_weather_kma_ultra_short_forecast,
        job_name="feature_weather_kma_ultra_short_forecast_job",
        schedule_name="feature_weather_kma_ultra_short_forecast_hourly_schedule",
        cron_schedule="50 * * * *",
        provider="python-kma-api",
        dataset_key="kma_ultra_short_forecast",
        description="KMA 초단기예보 WeatherValue 매시 적재(발표 HH:30 + 15분 지연 후).",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_weather_kma_short_forecast,
        job_name="feature_weather_kma_short_forecast_job",
        schedule_name="feature_weather_kma_short_forecast_hourly_schedule",
        cron_schedule="20 * * * *",
        provider="python-kma-api",
        dataset_key="kma_short_forecast",
        description=(
            "KMA 단기예보 WeatherValue 매시 적재(발표 02~23시 3시간 간격 + 지연 후)."
        ),
    ),
    FeatureLoadScheduleSpec(
        asset=feature_weather_kma_mid_forecast,
        job_name="feature_weather_kma_mid_forecast_job",
        schedule_name="feature_weather_kma_mid_forecast_hourly_schedule",
        cron_schedule="25 * * * *",
        provider="python-kma-api",
        dataset_key="kma_mid_forecast",
        description="KMA 중기예보(육상+기온) WeatherValue 매시 적재(발표 06/18시 + 지연 후).",
    ),
    FeatureLoadScheduleSpec(
        asset=feature_notice_kma_weather_alerts,
        job_name="feature_notice_kma_weather_alerts_job",
        schedule_name="feature_notice_kma_weather_alerts_hourly_schedule",
        cron_schedule="15 * * * *",
        provider="python-kma-api",
        dataset_key="kma_weather_alerts",
        description="KMA 기상특보 notice Feature 매시 적재(rolling window 멱등 upsert).",
    ),
    # MCST 파일데이터 (T-220 재배선, #395) — 저빈도 시설 데이터, 월 1회.
    FeatureLoadScheduleSpec(
        asset=feature_place_mcst_culture,
        job_name="feature_place_mcst_culture_job",
        schedule_name="feature_place_mcst_culture_monthly_schedule",
        cron_schedule="30 4 3 * *",
        provider="python-mcst-api",
        dataset_key="mcst_file_datasets",
        description="MCST 파일데이터 CSV 등록 dataset place Feature 월 1회 적재(slug별 분리 적재).",
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
            "kor_travel_map.provider": spec.provider,
            "kor_travel_map.dataset_key": spec.dataset_key,
        },
    )
    for spec in FEATURE_LOAD_SCHEDULE_SPECS
]
"""정기 Feature 적재 schedule이 실행하는 asset job 목록."""


FEATURE_LOAD_SCHEDULES: Final = [
    ScheduleDefinition(
        name=spec.schedule_name,
        job=job,
        cron_schedule=cron_for_schedule(spec.schedule_name, spec.cron_schedule),
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        run_config=spec.run_config,
        tags={
            **SYSTEM_SCHEDULE_TAGS,
            "kor_travel_map.provider": spec.provider,
            "kor_travel_map.dataset_key": spec.dataset_key,
        },
        description=spec.description,
    )
    for spec, job in zip(FEATURE_LOAD_SCHEDULE_SPECS, FEATURE_LOAD_JOBS, strict=True)
]
"""Provider별 KST cron schedule 목록."""
