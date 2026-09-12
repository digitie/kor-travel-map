"""kor-travel-map Dagster definitions smoke test."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
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
from dagster._utils.schedules import cron_string_iterator
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
    DISABLED_FEATURE_LOAD_SCHEDULES,
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
    # 자동 적재를 끈 provider의 schedule은 **만들어지지 않는다**
    # (`DISABLED_FEATURE_LOAD_SCHEDULES`). 그 이름을 여기서 제외하는 것이 아니라
    # **명시적으로 확인**한다 — 목록이 조용히 늘면 이 단언이 먼저 빨개져야 한다.
    expected = {
        spec.schedule_name: spec
        for spec in FEATURE_LOAD_SCHEDULE_SPECS
        if spec.schedule_name not in DISABLED_FEATURE_LOAD_SCHEDULES
    }
    disabled = {
        spec.schedule_name
        for spec in FEATURE_LOAD_SCHEDULE_SPECS
        if spec.schedule_name in DISABLED_FEATURE_LOAD_SCHEDULES
    }
    assert disabled == set(DISABLED_FEATURE_LOAD_SCHEDULES), (
        "끈 목록에 spec이 없는 이름이 있다 — 이름이 바뀌었거나 spec이 사라졌다. "
        "그러면 '껐다'는 기록만 남고 실제로 끄는 대상이 없다."
    )
    assert len(FEATURE_LOAD_SCHEDULES) == len(expected)
    registered = {schedule.name for schedule in FEATURE_LOAD_SCHEDULES}
    assert registered.isdisjoint(disabled), (
        "끈 schedule이 정의에 남아 있다 — `default_status=STOPPED`만으로는 UI에서 "
        "한 번 켜면 인스턴스 상태가 배포를 넘어 살아남는다."
    )

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
        if spec.schedule_name in DISABLED_FEATURE_LOAD_SCHEDULES:
            # 시계를 껐어도 **능력은 남는다** — 수동 launch가 여전히 manifest를
            # 필요로 하므로 job 정의 tag는 그대로 검사한다. schedule 정의는 없다.
            assert EXECUTION_SCOPES_TAG in job_tags
            assert (
                declared_execution_scopes(job_tags, boundary="test")
                == spec.execution_scopes
            )
            continue
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
        if spec.schedule_name in DISABLED_FEATURE_LOAD_SCHEDULES:
            continue  # 시계를 껐다 — schedule 정의 자체가 없다.
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


def _global_run_timeout_seconds() -> int:
    """배에 실리는 `docker/dagster.yaml`의 run 전체 상한.

    리터럴로 적지 않는다 — 이 검사의 요구가 그 값에서 **유도**되어야, 전역 상한을
    내리면 그때 규칙에 새로 걸리는 job도 함께 드러난다.
    """
    repo_root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load(
        (repo_root / "docker" / "dagster.yaml").read_text(encoding="utf-8")
    )
    timeout = config["run_monitoring"]["max_runtime_seconds"]
    assert type(timeout) is int and timeout >= 1, timeout
    return timeout


def _minimum_firing_interval_seconds(cron_schedule: str) -> float:
    """이 cron이 두 발화 사이에 두는 **최소** 간격.

    `0 1,5,9 * * *`처럼 불균등한 cron이 있으므로 평균이나 첫 간격이 아니라 최소를
    본다. 계산은 Dagster 자신의 cron 엔진으로 한다 — scheduler가 실제로 쓰는 것과
    갈라질 수 없다.
    """
    start = datetime(2026, 1, 1, tzinfo=ZoneInfo(KST_TIMEZONE))
    iterator = cron_string_iterator(start.timestamp(), cron_schedule, KST_TIMEZONE)
    fires = [next(iterator) for _ in range(9)]
    return min(
        (later - earlier).total_seconds()
        for earlier, later in zip(fires[:-1], fires[1:], strict=True)
    )


def test_every_schedule_firing_faster_than_its_own_recovery_bound_is_protected() -> None:
    """자기 회수 상한보다 빨리 발화하는 schedule은 합치기와 자체 상한을 갖는다.

    이 검사는 리터럴 목록이었다 — job 이름 세 개를 손으로 적고 그 tag가 "7200"인지
    확인했다. 그것은 **적어 둔 셋만** 재고, 같은 조건의 네 번째 job은 보지 않는다.
    2026-09-12 감사가 정확히 그 네 번째를 찾았다:
    `feature_weather_krex_rest_areas_job`은 매시(3,600초)인데 전역 회수 상한은
    21,600초라, upstream이 trickle에 들어가면 같은 job의 멈춘 run이 최대 6개까지
    동시에 살아 10 슬롯 중 6개를 한 job이 먹는다. 리터럴 검사는 그때도 초록이었다.

    그래서 요구를 **유도**한다: 발화 간격이 전역 회수 상한보다 짧으면
    (= 다음 run이 뜰 때 이전 run이 아직 회수되지 않을 수 있으면)

      - `coalesce_active_runs` — 미종료 run이 있으면 tick을 생략한다
      - `max_runtime_seconds` — 전역보다 이른 자체 상한

    둘을 모두 요구한다. 세 출처(cron 문자열 · 전역 상한 · spec의 두 필드)를 엮으므로
    어느 쪽이 움직여도 빨개진다. 시간별 schedule을 새로 추가하고 보호를 잊으면
    추가되는 순간 빨갛다.
    """
    assert MAX_RUNTIME_SECONDS_TAG == "dagster/max_runtime"
    global_timeout = _global_run_timeout_seconds()

    unprotected: list[str] = []
    for spec in FEATURE_LOAD_SCHEDULE_SPECS:
        interval = _minimum_firing_interval_seconds(spec.cron_schedule)
        if interval >= global_timeout:
            # 다음 발화 전에 전역 상한이 이미 run을 회수한다.
            continue
        if not spec.coalesce_active_runs or spec.max_runtime_seconds is None:
            unprotected.append(
                f"{spec.job_name}(간격 {interval:.0f}s < 전역 {global_timeout}s, "
                f"coalesce={spec.coalesce_active_runs}, "
                f"max_runtime={spec.max_runtime_seconds})"
            )
            continue
        assert spec.max_runtime_seconds <= global_timeout, spec.job_name
        job = defs.resolve_job_def(spec.job_name)
        schedule = defs.resolve_schedule_def(spec.schedule_name)
        expected = str(spec.max_runtime_seconds)
        assert job.tags[MAX_RUNTIME_SECONDS_TAG] == expected, spec.job_name
        assert schedule.tags[MAX_RUNTIME_SECONDS_TAG] == expected, spec.schedule_name

    assert not unprotected, (
        "자기 회수 상한보다 빨리 발화하는데 합치기·자체 상한이 없는 schedule: "
        + " · ".join(unprotected)
        + ". 멈춘 run이 회수되기 전에 다음 run이 떠서 같은 job이 큐 슬롯을 여러 개 "
        "먹는다."
    )


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
