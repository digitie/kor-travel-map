"""공용 run 큐 우선순위(``dagster/priority``) — Map job 전체의 단일 표.

n150 Dagster instance는 Map·PinVi·concierge가 함께 쓴다. ``QueuedRunCoordinator``는
instance 전체 큐를 ``dagster/priority``(정수 문자열, 클수록 먼저 dequeue, 없으면 0,
같은 값은 FIFO)로 줄 세운다. 값의 뜻은 테넌트 공통 규칙이다(소유자 결정 2026-11-24,
정본: kor-travel-docker-manager ``docs/dagster-tenant-fairness.md``).

분류는 **자료의 성격 + 주기**다.

- **10 = 실시간 수집** — 현황(관측·상태)을 1시간 미만 주기로 갱신하는 정기
  수집·상태 적재. 이것만 10이다.
- **5 = 매시 수집** — 시간 단위로 바뀌는 값(가격·예보 등)을 하루 미만 주기로
  갱신하는 정기 수집. 1시간 미만 주기여도 현황이 아니면 5다.
- **0 = 배치** — 그 밖 전부. 기준정보·시간표·목록·POI 같은 기준 자료는 주기와
  무관하게 0. 하루 이상 주기, backfill, 전체 재적재, 정리·유지보수·검증·export,
  수동·관리자 일괄 실행도 0.
- 음수·10 초과 금지 — 다른 테넌트를 굶기지 않는다.

값은 **job 정의 tag에만** 단다. Dagster는 job의 run tag(``run_tags``를 따로 주지 않으면
정의 ``tags``) 위에 schedule·sensor ``RunRequest`` tag, launchpad·GraphQL ``launchRun``
실행 tag를 덮어 run tag를 만든다. 재실행은 job tag에 부모 run tag를 덮는다. 그래서 job
정의에만 두면 모든 실행 경로의 run에 실린다. schedule·sensor ``RunRequest``는 이 key를
싣지 않는다(공용 규칙 — 같은 key를 덮어쓰지 않는다). 그래서 정기 job을 사람이 launchpad·
관리자 "지금 실행"으로 띄워도 job 값을 물려받는다. 규칙의 "수동 일괄 실행 = 0"은 수동으로만
도는 일괄 job(offline upload·batch gate 등)을 가리킨다.

주기는 schedule의 **코드 기본 cron**으로 판정한다. 운영자가 cron을 override해도 값은
따라 바뀌지 않는다 — 주기를 바꾸면 이 표도 바꾼다. ``tests/test_run_priority.py``가
표 ↔ 정의된 job 집합 ↔ 코드 cron 주기를 대조한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = [
    "BATCH_PRIORITY",
    "HOURLY_PRIORITY",
    "JOB_RUN_PRIORITIES",
    "REALTIME_PRIORITY",
    "RUN_PRIORITY_TAG",
    "RUN_PRIORITY_VALUES",
    "run_priority_tags",
]

RUN_PRIORITY_TAG: Final[str] = "dagster/priority"
"""Dagster ``QueuedRunCoordinatorDaemon``이 읽는 run tag."""

REALTIME_PRIORITY: Final[int] = 10
"""1시간 미만 주기의 정기 수집·상태 적재."""

HOURLY_PRIORITY: Final[int] = 5
"""1시간 이상·하루 미만 주기의 정기 수집."""

BATCH_PRIORITY: Final[int] = 0
"""하루 이상 주기·backfill·전체 재적재·정리·유지보수·검증·수동 일괄 실행."""

RUN_PRIORITY_VALUES: Final[frozenset[int]] = frozenset(
    {BATCH_PRIORITY, HOURLY_PRIORITY, REALTIME_PRIORITY}
)
"""규칙이 허용하는 값. 이 밖의 값(음수·10 초과·중간값)은 두지 않는다."""

JOB_RUN_PRIORITIES: Final[Mapping[str, int]] = MappingProxyType({
    # ── 상태 적재(Valkey, ADR-114) ─────────────────────────────────────────
    "transport_state_highway_incidents": REALTIME_PRIORITY,  # 10분마다
    "transport_state_fuel_stations": HOURLY_PRIORITY,  # 매시
    "transport_state_rest_area_fuel_prices": HOURLY_PRIORITY,  # 매시
    "transport_state_rest_areas": BATCH_PRIORITY,  # 매일
    "transport_state_airports": BATCH_PRIORITY,  # 매일
    "transport_state_rest_area_food": BATCH_PRIORITY,  # 매일
    "weather_state_current": REALTIME_PRIORITY,  # 매시 :25·:40
    "weather_state_forecast_ultra_short": HOURLY_PRIORITY,  # 매시
    "weather_state_daily_summaries": HOURLY_PRIORITY,  # 매시
    "weather_state_forecast_short": HOURLY_PRIORITY,  # 3시간
    "weather_state_forecast_external": HOURLY_PRIORITY,  # 3시간
    "weather_state_forecast_mid": HOURLY_PRIORITY,  # 하루 4회
    "weather_state_locations": BATCH_PRIORITY,  # 매일
    # ── feature 적재(PG) ─────────────────────────────────────────────────
    "feature_notice_krforest_landslide_forecast_issues_job": HOURLY_PRIORITY,  # 하루 6회
    "feature_event_visitkorea_festivals_job": BATCH_PRIORITY,  # 매일
    "feature_place_visitkorea_tourist_attractions_job": BATCH_PRIORITY,  # 매일
    "feature_place_transport_fuel_stations_job": BATCH_PRIORITY,  # 매주
    "feature_place_transport_rest_areas_job": BATCH_PRIORITY,  # 매주
    "feature_place_transport_rail_stations_job": BATCH_PRIORITY,  # 매주
    "feature_place_transport_ferry_ports_job": BATCH_PRIORITY,  # 매주
    "feature_place_transport_airports_job": BATCH_PRIORITY,  # 매월
    "feature_place_krheritage_items_job": BATCH_PRIORITY,  # 매월
    "feature_event_krheritage_events_job": BATCH_PRIORITY,  # 매월
    "feature_place_mois_licenses_job": BATCH_PRIORITY,  # 매월 + 이어 달리기
    "feature_place_knps_points_job": BATCH_PRIORITY,  # 매월(dataset별)
    "feature_geometry_knps_records_job": BATCH_PRIORITY,  # 매월(dataset별)
    "feature_place_krforest_recreation_forests_job": BATCH_PRIORITY,  # 매월
    "feature_place_krforest_arboretums_job": BATCH_PRIORITY,  # 매월
    "feature_route_krforest_mountain_trails_job": BATCH_PRIORITY,  # 매월
    "feature_route_krforest_dulle_trails_job": BATCH_PRIORITY,  # 매월
    "feature_place_standard_museums_job": BATCH_PRIORITY,  # 매월
    "feature_place_standard_tourist_attractions_job": BATCH_PRIORITY,  # 매월
    "feature_place_standard_parking_lots_job": BATCH_PRIORITY,  # 매월
    "feature_place_standard_special_streets_job": BATCH_PRIORITY,  # 매월
    "feature_place_standard_traditional_markets_job": BATCH_PRIORITY,  # 매월
    "feature_place_datagokr_seoul_bookstores_job": BATCH_PRIORITY,  # 매월
    "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job": BATCH_PRIORITY,
    "feature_place_datagokr_ansan_world_restaurants_job": BATCH_PRIORITY,  # 매월
    "feature_place_datagokr_jeju_local_restaurants_job": BATCH_PRIORITY,  # 매월
    "feature_place_khoa_beaches_job": BATCH_PRIORITY,  # 매월
    "feature_place_kor_travel_concierge_youtube_job": BATCH_PRIORITY,  # 매월
    "feature_place_mcst_culture_job": BATCH_PRIORITY,  # 매월
    "mois_localdata_source_sync": BATCH_PRIORITY,  # 매주(원천 파일 DB)
    # ── 큐·수동 실행 ──────────────────────────────────────────────────────
    # 큐 요청(PinVi cache target·관리자 갱신)은 사람이 기다릴 수 있지만 규칙
    # 표에 없는 "대화형 요청"이다 — 정해질 때까지 0(소유자 결정 대기).
    "feature_update_request_worker": BATCH_PRIORITY,
    "offline_upload_load": BATCH_PRIORITY,
    "full_load_batch_consistency_gate": BATCH_PRIORITY,
    # ── 정리·유지보수·검증 ────────────────────────────────────────────────
    "consistency_dedup_refresh": BATCH_PRIORITY,  # 매일
    "cache_target_snapshot_gc": BATCH_PRIORITY,  # 매시지만 정리
    "managed_file_scan": BATCH_PRIORITY,  # 6시간이지만 정리
    "manual_provider_dedup_detection": BATCH_PRIORITY,  # 매일
    # 성공 run 뒤 sensor가 띄우는 root 완결 sweep. 산사태 notice(5)의 root도 완결하지만
    # 하는 일은 장부 정리라 0으로 둔다.
    "feature_operation_completion": BATCH_PRIORITY,
    # 완주 게이트 탐침(검증). 큐가 5·10 run으로 차 있으면 게이트 상한 안에 못 뜰 수 있다.
    "map_run_heartbeat": BATCH_PRIORITY,
})
"""job 이름 → 큐 우선순위. Map code location의 모든 job이 여기 있어야 한다."""


def run_priority_tags(job_name: str) -> dict[str, str]:
    """job 정의 tag에 펼쳐 넣을 ``{"dagster/priority": "<값>"}``.

    표에 없는 job은 code location 로드에서 바로 실패한다 — 새 job이 분류 없이
    기본 0으로 조용히 들어가지 않게.
    """
    try:
        priority = JOB_RUN_PRIORITIES[job_name]
    except KeyError:
        raise KeyError(
            f"{job_name!r}의 run 큐 우선순위가 run_priority.JOB_RUN_PRIORITIES에 없다 — "
            "주기를 보고 0·5·10 중 하나로 분류해 넣는다."
        ) from None
    return {RUN_PRIORITY_TAG: str(priority)}
