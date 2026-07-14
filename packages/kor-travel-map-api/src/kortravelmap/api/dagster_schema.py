"""Dagster 운영 API의 공유 HTTP schema.

legacy ``/ops/dagster``와 신규 ``/ops/pipeline``이 같은 DTO를 사용하도록 router와
분리한다. 이 모듈은 FastAPI router/dependency나 외부 I/O를 소유하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    execution_timezone: str | None = None
    default_status: str | None = None
    can_reset: bool = False
    status: str | None = None
    state_id: str | None = None
    selector_id: str | None = None
    repository_name: str | None = None
    repository_location_name: str | None = None
    schedule_note: str | None = None
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
    """`GET /ops/dagster/summary` data."""

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
    """`GET /ops/dagster/summary` 응답 (DA-D-03 envelope)."""

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
    """`GET /ops/dagster/runs/{run_id}` data."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "not_found", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    run: DagsterRunSummary | None = None
    events: list[DagsterRunEvent] = Field(default_factory=list)
    failure_reason: str | None = None
    failure_events: list[DagsterRunFailure] = Field(default_factory=list)
    event_cursor: str | None = None
    event_has_more: bool = False
    errors: list[str] = Field(default_factory=list)


class DagsterRunDetailResponse(BaseModel):
    """`GET /ops/dagster/runs/{run_id}` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterRunDetailData
    meta: Meta


class DagsterNuxSeenData(BaseModel):
    """`POST /ops/dagster/nux-seen` data."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable", "error"]
    dagster_url: str
    graphql_url: str
    checked_at: datetime
    seen: bool
    errors: list[str] = Field(default_factory=list)


class DagsterNuxSeenResponse(BaseModel):
    """`POST /ops/dagster/nux-seen` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterNuxSeenData
    meta: Meta


class DagsterScheduleOverrideRequest(BaseModel):
    """운영 화면 schedule cron override 요청."""

    model_config = ConfigDict(extra="forbid")

    cron_schedule: str = Field(min_length=1, max_length=120)
    operator: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class DagsterScheduleCommandRequest(BaseModel):
    """Schedule start/stop/reset/run-now 명령 body."""

    model_config = ConfigDict(extra="forbid")

    operator: str | None = Field(default=None, max_length=120)
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
    schedule_status: str | None = None
    run_id: str | None = None
    run_status: str | None = None
    reloaded: bool = False
    errors: list[str] = Field(default_factory=list)


class DagsterScheduleCommandResponse(BaseModel):
    """Schedule write 명령 응답."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterScheduleCommandData
    meta: Meta
