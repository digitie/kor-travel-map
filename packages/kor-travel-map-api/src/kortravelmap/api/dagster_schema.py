"""Canonical ``/ops/pipeline``과 Dagster application service의 공유 schema.

이 모듈은 FastAPI router/dependency나 외부 I/O를 소유하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from kortravelmap.api.response import Meta

__all__ = [
    "DagsterAssetGroup",
    "DagsterAssetSummary",
    "DagsterGraphqlError",
    "DagsterInstigationTick",
    "DagsterJob",
    "DagsterNuxSeenData",
    "DagsterNuxSeenResponse",
    "DagsterRepository",
    "DagsterRunSummary",
    "DagsterRunDetailData",
    "DagsterRunDetailResponse",
    "DagsterRunEvent",
    "DagsterRunFailure",
    "DagsterSchedule",
    "DagsterScheduleCommandData",
    "DagsterScheduleCommandRequest",
    "DagsterScheduleCommandResponse",
    "DagsterScheduleClaimResolution",
    "DagsterScheduleOverrideRequest",
    "DagsterSensor",
    "DagsterSummaryData",
    "DagsterSummaryResponse",
]


class DagsterAssetSummary(BaseModel):
    """Dagster asset 표시 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str


class DagsterAssetGroup(BaseModel):
    """Dagster asset group 요약."""

    model_config = ConfigDict(extra="forbid")

    group_name: str
    asset_count: int
    assets: list[str]
    asset_items: list[DagsterAssetSummary] = Field(default_factory=list)


class DagsterJob(BaseModel):
    """Dagster job/pipeline 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    is_job: bool


class DagsterGraphqlError(BaseModel):
    """Dagster GraphQL PythonError 요약."""

    model_config = ConfigDict(extra="forbid")

    message: str | None = None
    stack: list[str] = Field(default_factory=list)
    class_name: str | None = None


class DagsterInstigationTick(BaseModel):
    """Dagster schedule/sensor tick 요약."""

    model_config = ConfigDict(extra="forbid")

    tick_id: str
    status: str
    timestamp: float
    end_timestamp: float | None = None
    run_ids: list[str] = Field(default_factory=list)
    run_keys: list[str] = Field(default_factory=list)
    skip_reason: str | None = None
    cursor: str | None = None
    error: DagsterGraphqlError | None = None


class DagsterSchedule(BaseModel):
    """Dagster schedule 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    pipeline_name: str | None = None
    mode: str | None = None
    cron_schedule: str | None = None
    default_cron_schedule: str | None = None
    override_cron_schedule: str | None = None
    effective_cron_schedule: str | None
    override_saved: bool
    override_effective: bool | None
    execution_timezone: str | None = None
    default_status: str | None = None
    can_reset: bool = False
    status: str | None = None
    state_id: str | None = None
    selector_id: str | None = None
    repository_name: str | None = None
    repository_location_name: str | None = None
    schedule_note: str | None = None
    can_run_now: bool
    disabled_reason: str | None
    recent_ticks: list[DagsterInstigationTick] = Field(default_factory=list)


class DagsterSensor(BaseModel):
    """Dagster sensor 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str | None = None
    recent_ticks: list[DagsterInstigationTick] = Field(default_factory=list)


class DagsterRepository(BaseModel):
    """Dagster code location/repository 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    location_name: str
    jobs: list[DagsterJob]
    schedules: list[DagsterSchedule]
    sensors: list[DagsterSensor]
    asset_count: int
    asset_groups: list[DagsterAssetGroup]


class DagsterRunSummary(BaseModel):
    """최근 Dagster run 요약."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    job_name: str | None = None
    status: str
    start_time: float | None = None
    end_time: float | None = None
    update_time: float | None = None
    tags: dict[str, str]


class DagsterSummaryData(BaseModel):
    """Dagster repository/run summary application-service data."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    version: str | None = None
    checked_at: datetime
    repository_count: int
    job_count: int
    asset_count: int
    schedule_count: int
    sensor_count: int
    run_counts: dict[str, int]
    repositories: list[DagsterRepository]
    recent_runs: list[DagsterRunSummary]
    errors: list[str] = Field(default_factory=list)


class DagsterSummaryResponse(BaseModel):
    """Dagster repository/run summary application-service envelope."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterSummaryData
    meta: Meta


class DagsterRunEvent(BaseModel):
    """Dagster run event/failure 요약."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    message: str | None = None
    timestamp: str | None = None
    level: str | None = None
    step_id: str | None = None
    dagster_event_type: str | None = None
    error: DagsterGraphqlError | None = None


class DagsterRunFailure(BaseModel):
    """Run failure 원인 요약."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    message: str | None = None
    timestamp: str | None = None
    level: str | None = None
    step_id: str | None = None
    dagster_event_type: str | None = None
    error: DagsterGraphqlError | None = None


class DagsterRunDetailData(BaseModel):
    """``/ops/pipeline/dagster-runs/{run_id}`` 상세 data."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "not_found", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    run: DagsterRunSummary | None = None
    events: list[DagsterRunEvent] = Field(
        default_factory=list,
        description="현재 Dagster event cursor page의 event 목록.",
    )
    failure_reason: str | None = Field(
        default=None,
        description=(
            "현재 event page에서 마지막으로 발견한 실패 원인. 전체 run의 전역 실패 "
            "요약이 아니며 event_has_more=true이면 null이어도 뒤 page에 실패가 있을 수 있다."
        ),
    )
    failure_events: list[DagsterRunFailure] = Field(
        default_factory=list,
        description=(
            "현재 event page에서만 추출한 구조화 실패 event. event_has_more=true일 때 "
            "빈 배열을 전체 run의 실패 event 부재로 해석하지 않는다."
        ),
    )
    event_cursor: str | None = Field(
        default=None,
        description="다음 page의 after query에 그대로 전달할 Dagster opaque cursor.",
    )
    event_has_more: bool = Field(
        default=False,
        description="뒤 event page 존재 여부. true이면 event_cursor로 전진 조회한다.",
    )
    errors: list[str] = Field(default_factory=list)


class DagsterRunDetailResponse(BaseModel):
    """Dagster run 상세 응답(DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterRunDetailData
    meta: Meta


class DagsterNuxSeenData(BaseModel):
    """라우터와 분리된 Dagster NUX mutation application-service data."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    seen: bool
    errors: list[str] = Field(default_factory=list)


class DagsterNuxSeenResponse(BaseModel):
    """Dagster NUX mutation application-service envelope."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterNuxSeenData
    meta: Meta


class DagsterScheduleOverrideRequest(BaseModel):
    """운영 화면 schedule cron override 요청."""

    model_config = ConfigDict(extra="forbid")

    cron_schedule: str = Field(min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class DagsterScheduleCommandRequest(BaseModel):
    """Schedule start/stop/reset/run-now 명령 body."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class DagsterScheduleCommandData(BaseModel):
    """Schedule write 명령 결과."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    schedule_name: str
    command: Literal["update", "default", "start", "stop", "reset", "run"]
    cron_schedule: str | None = None
    default_cron_schedule: str | None = None
    override_cron_schedule: str | None = None
    effective_cron_schedule: str | None
    schedule_status: str | None = None
    run_id: str | None = None
    run_status: str | None = None
    save_status: Literal["not_applicable", "saved", "cleared"]
    reload_status: Literal["not_requested", "succeeded", "failed"]
    effective_status: Literal["confirmed", "pending_verification", "mismatch", "unknown"]
    outcome_certainty: Literal["confirmed", "uncertain"] = "confirmed"
    audit_command_id: UUID | None = None
    audit_status: Literal["recorded", "terminal_record_failed"] = "recorded"
    errors: list[str] = Field(default_factory=list)


class DagsterScheduleCommandResponse(BaseModel):
    """Schedule write 명령 응답."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterScheduleCommandData
    meta: Meta


class DagsterScheduleClaimResolution(BaseModel):
    """불명 schedule claim에 대한 운영자 확인 감사 레코드."""

    model_config = ConfigDict(extra="forbid")

    resolution_id: int
    command_id: UUID
    schedule_name: str
    resolution: Literal["confirmed_applied", "confirmed_not_applied"]
    actor: str
    reason: str
    resolved_at: datetime
    replayed: bool
