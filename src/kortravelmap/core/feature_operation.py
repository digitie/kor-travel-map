"""Dagster provider feature operation의 main-package 불변 계약."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypeAlias

from kortravelmap.core.sync_scope import parse_canonical_sync_scope

ExecutionState: TypeAlias = Literal["queued", "running", "done", "failed", "cancelled"]
TriggerKind: TypeAlias = Literal[
    "schedule", "manual", "sensor", "update_request", "backfill", "system"
]
DagsterFeatureRunStatus: TypeAlias = Literal[
    "QUEUED",
    "NOT_STARTED",
    "MANAGED",
    "STARTING",
    "STARTED",
    "CANCELING",
    "SUCCESS",
    "FAILURE",
    "CANCELED",
]
DagsterFeatureOperationOutcome: TypeAlias = Literal["applied", "noop", "blocked"]
DagsterFeatureOperationBlockReason: TypeAlias = Literal["cancellation", "terminal"]

FEATURE_OPERATION_ROOT_KIND = "provider_feature_load_run"
FEATURE_OPERATION_MEMBER_KIND = "provider_feature_load"
FEATURE_UPDATE_REQUEST_JOB_KIND = "feature_update_request"

DEDICATED_JOB_ONLY_OPERATION_KEYS: frozenset[str] = frozenset(
    {"feature_place_mois_licenses_job"}
)
"""feature update 큐로는 실행하지 않고 **전용 Dagster job으로만** 도는 operation (ADR-108).

큐 runner는 provider 쓰기를 executor transaction 하나에 묶는다. MOIS 재개형 적재는 chunk마다
commit해야 성립하므로 큐로는 돌 수 없다. 이 집합이 API enqueue 거부, 실행 계획의 skip 사유,
Dagster 큐 runner의 방어 skip이 함께 읽는 단일 정본이다.
"""

DEDICATED_JOB_ONLY_SKIP_REASON = "dedicated_job_only"
"""실행 계획이 위 operation을 건너뛸 때 ``skipped_provider_scopes[].reason`` 값."""

# -- geo 릴리스 재지오코딩 계획의 입력(ADR-109 결정 3·5, T-GR-04) -----------------------------
#
# 계획은 Dagster 센서(T-GR-05)와 Map API ``POST /v1/ops/geo-releases/detect``가 **같은 함수**
# (``infra/geo_release_repo.plan_geo_release``)로 만든다. API 프로세스는 ``kortravelmap.dagster``를
# import하지 않으므로 계획이 읽는 job 사실은 여기 core에 둔다 — 각 값이 Dagster 정의와 같다는 것은
# lint(``tests/lint/test_geo_heavy_assets_declare_the_pool.py``)와 dagster 패키지 테스트가 고정한다.

FEATURE_LOAD_JOB_OPERATION_KEYS: frozenset[str] = frozenset(
    {
        "feature_event_datagokr_cultural_festivals_job",
        "feature_event_krheritage_events_job",
        "feature_event_visitkorea_enrichment_job",
        "feature_geometry_knps_records_job",
        "feature_notice_krforest_landslide_forecast_issues_job",
        "feature_notice_transport_highway_incidents_job",
        "feature_place_datagokr_ansan_world_restaurants_job",
        "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job",
        "feature_place_datagokr_jeju_local_restaurants_job",
        "feature_place_datagokr_seoul_bookstores_job",
        "feature_place_khoa_beaches_job",
        "feature_place_knps_points_job",
        "feature_place_kor_travel_concierge_youtube_job",
        "feature_place_krforest_arboretums_job",
        "feature_place_krforest_recreation_forests_job",
        "feature_place_krheritage_items_job",
        "feature_place_mcst_culture_job",
        "feature_place_mois_licenses_job",
        "feature_place_standard_museums_job",
        "feature_place_standard_parking_lots_job",
        "feature_place_standard_special_streets_job",
        "feature_place_standard_tourist_attractions_job",
        "feature_place_transport_airports_job",
        "feature_place_transport_fuel_stations_job",
        "feature_place_transport_rest_areas_job",
        "feature_price_transport_fuel_stations_job",
        "feature_price_transport_rest_areas_job",
        "feature_route_krforest_dulle_trails_job",
        "feature_route_krforest_mountain_trails_job",
    }
)
"""Dagster 전용 적재 job이 있는 operation(= ``FEATURE_LOAD_SCHEDULE_SPECS``의 ``job_name`` 전부).

DB의 ``refresh`` operation 중 여기 없는 것(MOIS 증분·상세·폐업 갱신 등)은 큐 runner로만 돈다 —
릴리스 계획은 그 항목을 ``skipped(queue_only)``로 남긴다(센서는 job으로만 run을 낸다).
"""

GEO_DEPENDENT_OPERATION_KEYS: frozenset[str] = frozenset(
    {
        "feature_event_datagokr_cultural_festivals_job",
        "feature_event_krheritage_events_job",
        "feature_geometry_knps_records_job",
        "feature_place_datagokr_ansan_world_restaurants_job",
        "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job",
        "feature_place_datagokr_jeju_local_restaurants_job",
        "feature_place_datagokr_seoul_bookstores_job",
        "feature_place_khoa_beaches_job",
        "feature_place_knps_points_job",
        "feature_place_kor_travel_concierge_youtube_job",
        "feature_place_krforest_arboretums_job",
        "feature_place_krforest_recreation_forests_job",
        "feature_place_krheritage_items_job",
        "feature_place_mcst_culture_job",
        "feature_place_mois_licenses_job",
        "feature_place_standard_museums_job",
        "feature_place_standard_parking_lots_job",
        "feature_place_standard_special_streets_job",
        "feature_place_standard_tourist_attractions_job",
        "feature_place_transport_airports_job",
        "feature_place_transport_fuel_stations_job",
        "feature_place_transport_rest_areas_job",
        "feature_route_krforest_dulle_trails_job",
        "feature_route_krforest_mountain_trails_job",
    }
)
"""geo 유도 값을 만드는 operation — asset이 ``reverse_geocoder=``/``address_resolver=``에
None이 아닌 값을 넘긴다(ADR-109 결정 3). 런타임 정본이고, lint가 AST 유도 집합과의 **집합
동등**으로 고정한다."""

FEATURE_LOAD_DISABLED_OPERATION_KEYS: frozenset[str] = frozenset(
    {
        "feature_place_datagokr_ansan_world_restaurants_job",
        "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job",
        "feature_place_datagokr_jeju_local_restaurants_job",
        "feature_place_standard_special_streets_job",
    }
)
"""자동 적재를 끈 operation — Dagster ``schedules.DISABLED_FEATURE_LOAD_OPERATION_KEYS``와 같은
값이다(dagster 패키지 테스트가 동등을 고정한다). 릴리스 계획은 ``skipped(disabled)``로 남긴다."""

DATASET_CONFIGURED_OPERATION_RESOURCES: dict[str, tuple[str, ...]] = {
    "feature_place_knps_points_job": ("knps_point_dataset_key", "knps_point_records"),
    "feature_geometry_knps_records_job": ("knps_geometry_dataset_key", "knps_geometry_records"),
    "feature_place_datagokr_seoul_bookstores_job": (
        "datagokr_file_data_dataset_key",
        "datagokr_file_data_records",
    ),
    "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job": (
        "datagokr_file_data_dataset_key",
        "datagokr_file_data_records",
    ),
    "feature_place_datagokr_ansan_world_restaurants_job": (
        "datagokr_file_data_dataset_key",
        "datagokr_file_data_records",
    ),
    "feature_place_datagokr_jeju_local_restaurants_job": (
        "datagokr_file_data_dataset_key",
        "datagokr_file_data_records",
    ),
}
"""dataset을 run_config로 고르는 operation → ``{"config": {"dataset_key": …}}``를 받는 resource들.

KNPS는 job 하나에 dataset 다섯이 결박돼 있어 dataset마다 run이 하나씩이다(``knps_schedule_binding``
꼴). datagokr fileData job은 job마다 dataset 하나지만 run_config가 없으면 resource가 기본값을 쓴다.
dagster 패키지 테스트가 schedule spec의 run_config resource 이름과 같음을 고정한다."""

REPLAY_RECORDS_RESOURCES: dict[str, str] = {
    "feature_place_mois_licenses_job": "mois_license_records",
    "feature_event_datagokr_cultural_festivals_job": "datagokr_cultural_festivals",
    "feature_place_standard_museums_job": "standard_museums",
    "feature_place_standard_tourist_attractions_job": "standard_tourist_attractions",
    "feature_place_standard_parking_lots_job": "standard_parking_lots",
    "feature_place_standard_special_streets_job": "standard_special_streets",
    "feature_place_datagokr_seoul_bookstores_job": "datagokr_file_data_records",
    "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_job": (
        "datagokr_file_data_records"
    ),
    "feature_place_datagokr_ansan_world_restaurants_job": "datagokr_file_data_records",
    "feature_place_datagokr_jeju_local_restaurants_job": "datagokr_file_data_records",
}
"""쿼터 민감 operation → ``source_mode=replay``를 받을 records resource(ADR-109 결정 7·열린 결정 4
1단계 범위: MOIS·datagokr fileData·standard_data). **resource 쪽 ``source_mode``는 T-GR-08이
더한다** — 그 전에 이 run_config로 run을 내면 Dagster config 검증이 거부한다(T-GR-05 센서는
replay 항목을 T-GR-08 뒤에만 낸다)."""
C6C_CANCEL_PROBE_JOB_KIND = "c6c_cancel_probe"
FEATURE_OPERATION_RESERVED_KINDS = frozenset(
    {
        FEATURE_OPERATION_ROOT_KIND,
        FEATURE_OPERATION_MEMBER_KIND,
    }
)
TRIGGER_KIND_VALUES: tuple[TriggerKind, ...] = (
    "schedule",
    "manual",
    "sensor",
    "update_request",
    "backfill",
    "system",
)
DAGSTER_FEATURE_RUN_STATUS_VALUES: tuple[DagsterFeatureRunStatus, ...] = (
    "QUEUED",
    "NOT_STARTED",
    "MANAGED",
    "STARTING",
    "STARTED",
    "CANCELING",
    "SUCCESS",
    "FAILURE",
    "CANCELED",
)
DAGSTER_FEATURE_ACTIVE_STATUS_VALUES = frozenset(
    {"QUEUED", "NOT_STARTED", "MANAGED", "STARTING", "STARTED", "CANCELING"}
)
DAGSTER_FEATURE_TERMINAL_STATUS_VALUES = frozenset({"SUCCESS", "FAILURE", "CANCELED"})


@dataclass(frozen=True, order=True)
class ProviderDatasetOperationKey:
    """trim된 exact provider/dataset identity."""

    provider: str
    dataset_key: str

    def __post_init__(self) -> None:
        if not self.provider or self.provider != self.provider.strip():
            raise ValueError("provider must be trimmed and non-empty")
        if not self.dataset_key or self.dataset_key != self.dataset_key.strip():
            raise ValueError("dataset_key must be trimmed and non-empty")


@dataclass(frozen=True, order=True)
class ProviderDatasetOperationMembership:
    """Dagster operation이 실행하는 immutable canonical dataset scope."""

    provider_dataset_id: int
    sync_scope: str
    operation_key: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_dataset_id, int)
            or isinstance(self.provider_dataset_id, bool)
            or self.provider_dataset_id <= 0
        ):
            raise ValueError("provider_dataset_id must be a positive integer")
        parse_canonical_sync_scope(self.sync_scope)
        if (
            not isinstance(self.operation_key, str)
            or not self.operation_key
            or self.operation_key != self.operation_key.strip()
        ):
            raise ValueError("operation_key must be trimmed and non-empty")


@dataclass(frozen=True)
class DagsterFeatureOperationMember:
    job_id: str
    import_job_dataset_id: str
    membership: ProviderDatasetOperationMembership
    status: ExecutionState
    progress: int
    current_stage: str | None
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class DagsterFeatureOperation:
    root_job_id: str
    dagster_run_id: str
    status: ExecutionState
    dagster_run_status: DagsterFeatureRunStatus
    progress: int
    current_stage: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    trigger_kind: TriggerKind
    operation_key: str
    members: tuple[DagsterFeatureOperationMember, ...]


@dataclass(frozen=True)
class DagsterFeatureOperationMutation:
    outcome: DagsterFeatureOperationOutcome
    operation: DagsterFeatureOperation
    block_reason: DagsterFeatureOperationBlockReason | None = None


@dataclass(frozen=True, order=True)
class DagsterFeatureOperationCursor:
    created_at: datetime
    root_job_id: str


@dataclass(frozen=True)
class DagsterFeatureOperationPage:
    items: tuple[DagsterFeatureOperation, ...]
    next_cursor: DagsterFeatureOperationCursor | None


class FeatureOperationInvariantConflict(RuntimeError):
    """run identity/selection 불변식 위반. 부분 mutation은 남기지 않는다."""

    code = "FEATURE_OPERATION_INVARIANT_CONFLICT"

    def __init__(
        self,
        message: str,
        *,
        dagster_run_id: str,
        root_job_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.dagster_run_id = dagster_run_id
        self.root_job_id = root_job_id
        self.details = details or {}


__all__ = [
    "DEDICATED_JOB_ONLY_OPERATION_KEYS",
    "DEDICATED_JOB_ONLY_SKIP_REASON",
    "DAGSTER_FEATURE_ACTIVE_STATUS_VALUES",
    "DAGSTER_FEATURE_RUN_STATUS_VALUES",
    "DAGSTER_FEATURE_TERMINAL_STATUS_VALUES",
    "C6C_CANCEL_PROBE_JOB_KIND",
    "FEATURE_OPERATION_MEMBER_KIND",
    "FEATURE_OPERATION_RESERVED_KINDS",
    "FEATURE_OPERATION_ROOT_KIND",
    "FEATURE_UPDATE_REQUEST_JOB_KIND",
    "TRIGGER_KIND_VALUES",
    "DagsterFeatureOperation",
    "DagsterFeatureOperationBlockReason",
    "DagsterFeatureOperationCursor",
    "DagsterFeatureOperationMember",
    "DagsterFeatureOperationMutation",
    "DagsterFeatureOperationOutcome",
    "DagsterFeatureOperationPage",
    "DagsterFeatureRunStatus",
    "ExecutionState",
    "FeatureOperationInvariantConflict",
    "ProviderDatasetOperationKey",
    "ProviderDatasetOperationMembership",
    "TriggerKind",
]
