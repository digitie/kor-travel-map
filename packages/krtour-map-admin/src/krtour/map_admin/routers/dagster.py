"""``krtour.map_admin.routers.dagster`` — Dagster 운영 요약 API.

Dagster webserver 자체 화면은 frontend에서 iframe으로 embed하고, 본 라우터는
같은 Dagster GraphQL 데이터를 admin UI가 읽기 쉬운 요약 DTO로 변환한다.
TripMate나 외부 서비스가 Dagster를 직접 제어하지 않는다는 ADR-045 경계를 유지한다.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from krtour.map_admin.settings import AdminSettings

__all__ = [
    "router",
    "DagsterNuxSeenResponse",
    "DagsterSummaryResponse",
]


router = APIRouter(prefix="/ops/dagster", tags=["ops", "dagster"])

JsonDict = dict[str, Any]
_ALLOWED_DAGSTER_SCHEMES = {"http", "https"}

_DAGSTER_SUMMARY_QUERY = """
query KrtourMapDagsterSummary($limit: Int!) {
  version
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        name
        location { name }
        pipelines { name isJob }
        schedules {
          name
          cronSchedule
          executionTimezone
          scheduleState { status }
        }
        sensors {
          name
          sensorState { status }
        }
        assetNodes {
          id
          groupName
          assetKey { path }
        }
      }
    }
    ... on PythonError {
      message
    }
  }
  runsOrError(limit: $limit) {
    __typename
    ... on Runs {
      results {
        runId
        jobName
        status
        startTime
        endTime
        updateTime
        tags { key value }
      }
    }
    ... on PythonError {
      message
    }
  }
}
"""

_DAGSTER_SET_NUX_SEEN_MUTATION = """
mutation KrtourMapSetNuxSeen {
  setNuxSeen
}
"""


class DagsterAssetGroup(BaseModel):
    """Dagster asset group 요약."""

    model_config = ConfigDict(extra="forbid")

    group_name: str
    asset_count: int
    assets: list[str]


class DagsterJob(BaseModel):
    """Dagster job/pipeline 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    is_job: bool


class DagsterSchedule(BaseModel):
    """Dagster schedule 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    cron_schedule: str | None = None
    execution_timezone: str | None = None
    status: str | None = None


class DagsterSensor(BaseModel):
    """Dagster sensor 요약."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str | None = None


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


class DagsterDetailMeta(BaseModel):
    """단건 요약 응답 meta."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int


class DagsterSummaryResponse(BaseModel):
    """`GET /ops/dagster/summary` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: DagsterSummaryData
    meta: DagsterDetailMeta


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
    meta: DagsterDetailMeta


@dataclass(frozen=True)
class _DagsterUrls:
    dagster_url: str
    graphql_url: str


class DagsterUrlConfigurationError(ValueError):
    """Dagster URL 설정이 backend allowlist를 통과하지 못했다."""


def _candidate_graphql_url(settings: AdminSettings) -> str:
    if settings.dagster_graphql_url:
        return settings.dagster_graphql_url
    return f"{settings.dagster_url.rstrip('/')}/graphql"


def _normalised_allowed_hosts(settings: AdminSettings) -> set[str]:
    return {
        host.strip().lower().rstrip(".")
        for host in settings.dagster_allowed_hosts
        if host.strip()
    }


def _validated_http_url(
    raw_url: str,
    *,
    setting_name: str,
    allowed_hosts: set[str],
    require_graphql_path: bool = False,
) -> str:
    value = raw_url.strip()
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_DAGSTER_SCHEMES:
        raise DagsterUrlConfigurationError(
            f"{setting_name} scheme must be http or https"
        )
    if parsed.username is not None or parsed.password is not None:
        raise DagsterUrlConfigurationError(
            f"{setting_name} must not include userinfo"
        )
    hostname = parsed.hostname
    if hostname is None:
        raise DagsterUrlConfigurationError(f"{setting_name} host is required")
    if hostname.lower().rstrip(".") not in allowed_hosts:
        raise DagsterUrlConfigurationError(
            f"{setting_name} host is not in dagster_allowed_hosts"
        )
    if parsed.query or parsed.fragment:
        raise DagsterUrlConfigurationError(
            f"{setting_name} must not include query or fragment"
        )
    if require_graphql_path and not parsed.path.rstrip("/").endswith("/graphql"):
        raise DagsterUrlConfigurationError(
            f"{setting_name} path must end with /graphql"
        )
    return urlunsplit((scheme, parsed.netloc, parsed.path, "", ""))


def _dagster_urls(settings: AdminSettings) -> _DagsterUrls:
    allowed_hosts = _normalised_allowed_hosts(settings)
    dagster_url = _validated_http_url(
        settings.dagster_url,
        setting_name="dagster_url",
        allowed_hosts=allowed_hosts,
    )
    graphql_url = _validated_http_url(
        _candidate_graphql_url(settings),
        setting_name="dagster_graphql_url",
        allowed_hosts=allowed_hosts,
        require_graphql_path=True,
    )
    return _DagsterUrls(dagster_url=dagster_url.rstrip("/"), graphql_url=graphql_url)


def _dict(value: object) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _asset_name(asset_node: JsonDict) -> str:
    asset_key = _dict(asset_node.get("assetKey"))
    path = [part for part in _list(asset_key.get("path")) if isinstance(part, str)]
    if path:
        return "/".join(path)
    return _string(asset_node.get("id"), "unknown_asset")


def _parse_jobs(raw_jobs: list[object]) -> list[DagsterJob]:
    jobs: list[DagsterJob] = []
    for raw in raw_jobs:
        entry = _dict(raw)
        jobs.append(
            DagsterJob(
                name=_string(entry.get("name"), "unknown_job"),
                is_job=bool(entry.get("isJob")),
            )
        )
    return jobs


def _parse_schedules(raw_schedules: list[object]) -> list[DagsterSchedule]:
    schedules: list[DagsterSchedule] = []
    for raw in raw_schedules:
        entry = _dict(raw)
        state = _dict(entry.get("scheduleState"))
        schedules.append(
            DagsterSchedule(
                name=_string(entry.get("name"), "unknown_schedule"),
                cron_schedule=_optional_string(entry.get("cronSchedule")),
                execution_timezone=_optional_string(entry.get("executionTimezone")),
                status=_optional_string(state.get("status")),
            )
        )
    return schedules


def _parse_sensors(raw_sensors: list[object]) -> list[DagsterSensor]:
    sensors: list[DagsterSensor] = []
    for raw in raw_sensors:
        entry = _dict(raw)
        state = _dict(entry.get("sensorState"))
        sensors.append(
            DagsterSensor(
                name=_string(entry.get("name"), "unknown_sensor"),
                status=_optional_string(state.get("status")),
            )
        )
    return sensors


def _parse_asset_groups(raw_assets: list[object]) -> list[DagsterAssetGroup]:
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for raw in raw_assets:
        entry = _dict(raw)
        group_name = _string(entry.get("groupName"), "default")
        groups[group_name].append(_asset_name(entry))

    return [
        DagsterAssetGroup(
            group_name=group_name,
            asset_count=len(assets),
            assets=sorted(assets),
        )
        for group_name, assets in sorted(groups.items())
    ]


def _parse_repositories(raw_connection: JsonDict) -> tuple[list[DagsterRepository], list[str]]:
    errors: list[str] = []
    if raw_connection.get("__typename") != "RepositoryConnection":
        message = _optional_string(raw_connection.get("message")) or "Dagster repository 조회 실패"
        return [], [message]

    repositories: list[DagsterRepository] = []
    for raw in _list(raw_connection.get("nodes")):
        entry = _dict(raw)
        location = _dict(entry.get("location"))
        assets = _list(entry.get("assetNodes"))
        repositories.append(
            DagsterRepository(
                name=_string(entry.get("name"), "__repository__"),
                location_name=_string(location.get("name"), "unknown_location"),
                jobs=_parse_jobs(_list(entry.get("pipelines"))),
                schedules=_parse_schedules(_list(entry.get("schedules"))),
                sensors=_parse_sensors(_list(entry.get("sensors"))),
                asset_count=len(assets),
                asset_groups=_parse_asset_groups(assets),
            )
        )
    return repositories, errors


def _parse_runs(raw_runs: JsonDict) -> tuple[list[DagsterRunSummary], dict[str, int], list[str]]:
    if raw_runs.get("__typename") != "Runs":
        message = _optional_string(raw_runs.get("message")) or "Dagster run 조회 실패"
        return [], {}, [message]

    runs: list[DagsterRunSummary] = []
    counts: Counter[str] = Counter()
    for raw in _list(raw_runs.get("results")):
        entry = _dict(raw)
        status = _string(entry.get("status"), "UNKNOWN")
        counts[status] += 1
        tags = {
            _string(_dict(tag).get("key")): _string(_dict(tag).get("value"))
            for tag in _list(entry.get("tags"))
            if _string(_dict(tag).get("key"))
        }
        runs.append(
            DagsterRunSummary(
                run_id=_string(entry.get("runId"), "unknown_run"),
                job_name=_optional_string(entry.get("jobName")),
                status=status,
                start_time=_optional_float(entry.get("startTime")),
                end_time=_optional_float(entry.get("endTime")),
                update_time=_optional_float(entry.get("updateTime")),
                tags=tags,
            )
        )
    return runs, dict(counts), []


async def _post_graphql(
    client: httpx.AsyncClient,
    graphql_url: str,
    variables: dict[str, object],
    query: str = _DAGSTER_SUMMARY_QUERY,
) -> JsonDict:
    response = await client.post(
        graphql_url,
        json={"query": query, "variables": variables},
    )
    response.raise_for_status()
    payload = response.json()
    return _dict(payload)


def _settings_from_request(request: Request) -> AdminSettings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, AdminSettings):
        return settings
    return AdminSettings()


def _http_client_from_request(
    request: Request,
    settings: AdminSettings,
) -> httpx.AsyncClient:
    client = getattr(request.app.state, "dagster_http_client", None)
    if isinstance(client, httpx.AsyncClient) and not client.is_closed:
        return client
    client = httpx.AsyncClient(timeout=settings.dagster_request_timeout_seconds)
    request.app.state.dagster_http_client = client
    return client


def _summary_response(
    data: DagsterSummaryData, *, started_at: float
) -> DagsterSummaryResponse:
    return DagsterSummaryResponse(
        data=data,
        meta=DagsterDetailMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
        ),
    )


def _nux_seen_response(
    data: DagsterNuxSeenData, *, started_at: float
) -> DagsterNuxSeenResponse:
    return DagsterNuxSeenResponse(
        data=data,
        meta=DagsterDetailMeta(
            duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
        ),
    )


@router.get(
    "/summary",
    response_model=DagsterSummaryResponse,
    summary="Dagster 운영 요약",
    description=(
        "Dagster GraphQL에서 repository, asset, schedule/sensor, recent run 정보를 "
        "읽어 admin UI 요약 DTO로 반환한다. Dagster webserver가 내려가도 200 "
        "응답(status=unavailable)으로 UI가 장애 상태를 표시할 수 있게 한다. "
        "GET은 조회 전용이며 Dagster mutation은 호출하지 않는다."
    ),
)
async def get_dagster_summary(
    request: Request,
    run_limit: int = Query(default=10, ge=1, le=50),
) -> DagsterSummaryResponse:
    started_at = perf_counter()
    settings = _settings_from_request(request)
    checked_at = datetime.now(UTC)
    raw_graphql_url = _candidate_graphql_url(settings)

    try:
        dagster_urls = _dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        return _summary_response(
            DagsterSummaryData(
                status="error",
                dagster_url=settings.dagster_url,
                graphql_url=raw_graphql_url,
                checked_at=checked_at,
                repository_count=0,
                job_count=0,
                asset_count=0,
                schedule_count=0,
                sensor_count=0,
                run_counts={},
                repositories=[],
                recent_runs=[],
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    client = _http_client_from_request(request, settings)

    try:
        payload = await _post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={"limit": run_limit},
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _summary_response(
            DagsterSummaryData(
                status="unavailable",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                repository_count=0,
                job_count=0,
                asset_count=0,
                schedule_count=0,
                sensor_count=0,
                run_counts={},
                repositories=[],
                recent_runs=[],
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return _summary_response(
            DagsterSummaryData(
                status="error",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                repository_count=0,
                job_count=0,
                asset_count=0,
                schedule_count=0,
                sensor_count=0,
                run_counts={},
                repositories=[],
                recent_runs=[],
                errors=[str(error) for error in graphql_errors],
            ),
            started_at=started_at,
        )

    data = _dict(payload.get("data"))
    repositories, repository_errors = _parse_repositories(
        _dict(data.get("repositoriesOrError"))
    )
    recent_runs, run_counts, run_errors = _parse_runs(_dict(data.get("runsOrError")))
    errors = [*repository_errors, *run_errors]

    return _summary_response(
        DagsterSummaryData(
            status="error" if errors else "ok",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            version=_optional_string(data.get("version")),
            checked_at=checked_at,
            repository_count=len(repositories),
            job_count=sum(len(repository.jobs) for repository in repositories),
            asset_count=sum(repository.asset_count for repository in repositories),
            schedule_count=sum(len(repository.schedules) for repository in repositories),
            sensor_count=sum(len(repository.sensors) for repository in repositories),
            run_counts=run_counts,
            repositories=repositories,
            recent_runs=recent_runs,
            errors=errors,
        ),
        started_at=started_at,
    )


@router.post(
    "/nux-seen",
    response_model=DagsterNuxSeenResponse,
    summary="Dagster NUX seen 처리",
    description=(
        "embedded Dagster 화면의 로컬 첫 실행 NUX를 접기 위해 Dagster GraphQL "
        "setNuxSeen mutation을 호출한다. GET summary의 부수효과를 제거하기 위해 "
        "명시 POST endpoint로 분리했다."
    ),
)
async def mark_dagster_nux_seen(request: Request) -> DagsterNuxSeenResponse:
    started_at = perf_counter()
    settings = _settings_from_request(request)
    checked_at = datetime.now(UTC)
    raw_graphql_url = _candidate_graphql_url(settings)

    try:
        dagster_urls = _dagster_urls(settings)
    except DagsterUrlConfigurationError as exc:
        return _nux_seen_response(
            DagsterNuxSeenData(
                status="error",
                dagster_url=settings.dagster_url,
                graphql_url=raw_graphql_url,
                checked_at=checked_at,
                seen=False,
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    client = _http_client_from_request(request, settings)
    try:
        payload = await _post_graphql(
            client=client,
            graphql_url=dagster_urls.graphql_url,
            variables={},
            query=_DAGSTER_SET_NUX_SEEN_MUTATION,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _nux_seen_response(
            DagsterNuxSeenData(
                status="unavailable",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                seen=False,
                errors=[str(exc)],
            ),
            started_at=started_at,
        )

    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return _nux_seen_response(
            DagsterNuxSeenData(
                status="error",
                dagster_url=dagster_urls.dagster_url,
                graphql_url=dagster_urls.graphql_url,
                checked_at=checked_at,
                seen=False,
                errors=[str(error) for error in graphql_errors],
            ),
            started_at=started_at,
        )

    seen = _dict(payload.get("data")).get("setNuxSeen") is True
    return _nux_seen_response(
        DagsterNuxSeenData(
            status="ok" if seen else "error",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            seen=seen,
            errors=[] if seen else ["Dagster setNuxSeen mutation did not return true"],
        ),
        started_at=started_at,
    )
