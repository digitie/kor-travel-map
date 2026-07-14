"""Dagster GraphQL transport, URL validation, and response parsing."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from kortravelmap.core.dagster_asset_labels import DAGSTER_ASSET_KOREAN_LABELS

from kortravelmap.api.dagster_schema import (
    DagsterAssetGroup,
    DagsterAssetSummary,
    DagsterGraphqlError,
    DagsterInstigationTick,
    DagsterJob,
    DagsterRepository,
    DagsterRunDetailData,
    DagsterRunEvent,
    DagsterRunFailure,
    DagsterRunSummary,
    DagsterSchedule,
    DagsterSensor,
)
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "DagsterUrlConfigurationError",
    "DagsterUrls",
    "JsonDict",
    "as_dict",
    "candidate_graphql_url",
    "dagster_urls",
    "default_cron_for_schedule",
    "graphql_error_message",
    "optional_string",
    "parse_repositories",
    "parse_run_detail",
    "parse_runs",
    "post_graphql",
]

JsonDict = dict[str, Any]
_ALLOWED_DAGSTER_SCHEMES = {"http", "https"}
_MAX_EVENT_CURSOR_LENGTH = 2048

_DEFAULT_SCHEDULE_CRONS: dict[str, str] = {
    "consistency_dedup_refresh_daily_schedule": "45 5 * * *",
    "curated_features_refresh_daily_schedule": "55 4 * * *",
    "mois_localdata_source_sync_weekly_schedule": "0 4 * * 1",
    "feature_event_datagokr_cultural_festivals_monthly_schedule": "10 3 1 * *",
    "feature_place_opinet_stations_monthly_schedule": "5 3 1 * *",
    "feature_price_opinet_stations_daily_schedule": "18 18 * * *",
    "feature_place_krex_rest_areas_monthly_schedule": "20 2 1 * *",
    "feature_price_krex_rest_areas_twice_daily_schedule": "28 6,18 * * *",
    "feature_notice_krex_traffic_notices_ten_minute_schedule": "*/10 * * * *",
    "feature_weather_krex_rest_areas_hourly_schedule": "35 * * * *",
    "feature_place_krheritage_items_monthly_schedule": "15 2 2 * *",
    "feature_event_krheritage_events_monthly_schedule": "25 3 2 * *",
    "feature_place_mois_licenses_monthly_schedule": "35 4 2 * *",
    "feature_place_knps_points_monthly_schedule": "45 3 3 * *",
    "feature_geometry_knps_records_monthly_schedule": "15 4 3 * *",
    "feature_place_krforest_recreation_forests_monthly_schedule": "5 4 4 * *",
    "feature_place_krforest_arboretums_monthly_schedule": "15 4 4 * *",
    "feature_place_standard_museums_monthly_schedule": "25 4 4 * *",
    "feature_place_standard_tourist_attractions_monthly_schedule": "35 4 4 * *",
    "feature_place_standard_parking_lots_monthly_schedule": "45 4 4 * *",
    "feature_place_standard_special_streets_monthly_schedule": "50 4 4 * *",
    "feature_place_datagokr_seoul_bookstores_monthly_schedule": "52 4 4 * *",
    "feature_place_datagokr_gyeonggi_muslim_friendly_restaurants_monthly_schedule": "53 4 4 * *",
    "feature_place_datagokr_ansan_world_restaurants_monthly_schedule": "54 4 4 * *",
    "feature_place_datagokr_jeju_local_restaurants_monthly_schedule": "56 4 4 * *",
    "feature_place_khoa_beaches_monthly_schedule": "55 4 4 * *",
    "feature_place_krairport_airports_monthly_schedule": "5 5 4 * *",
    "feature_place_kor_travel_concierge_youtube_monthly_schedule": "40 3 3 * *",
    "feature_event_visitkorea_enrichment_monthly_schedule": "50 4 1 * *",
    "feature_weather_airkorea_air_quality_hourly_schedule": "10 * * * *",
    "feature_weather_kma_ultra_short_nowcast_hourly_schedule": "45 * * * *",
    "feature_weather_kma_ultra_short_forecast_hourly_schedule": "50 * * * *",
    "feature_weather_kma_short_forecast_hourly_schedule": "20 * * * *",
    "feature_weather_kma_mid_forecast_hourly_schedule": "25 * * * *",
    "feature_notice_kma_weather_alerts_hourly_schedule": "15 * * * *",
    "feature_place_mcst_culture_monthly_schedule": "30 4 3 * *",
}

_FILE_DOWNLOAD_SCHEDULE_HINTS = {
    "datagokr_filedata",
    "file_data",
    "localdata",
    "mcst_file",
}


@dataclass(frozen=True)
class DagsterUrls:
    dagster_url: str
    graphql_url: str


class DagsterUrlConfigurationError(ValueError):
    """Dagster URL 설정이 backend allowlist를 통과하지 못했다."""


def candidate_graphql_url(settings: ApiSettings) -> str:
    if settings.dagster_graphql_url:
        return settings.dagster_graphql_url
    return f"{settings.dagster_url.rstrip('/')}/graphql"


def _normalised_allowed_hosts(settings: ApiSettings) -> set[str]:
    return {
        host.strip().lower().rstrip(".") for host in settings.dagster_allowed_hosts if host.strip()
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
        raise DagsterUrlConfigurationError(f"{setting_name} scheme must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise DagsterUrlConfigurationError(f"{setting_name} must not include userinfo")
    hostname = parsed.hostname
    if hostname is None:
        raise DagsterUrlConfigurationError(f"{setting_name} host is required")
    if hostname.lower().rstrip(".") not in allowed_hosts:
        raise DagsterUrlConfigurationError(f"{setting_name} host is not in dagster_allowed_hosts")
    if parsed.query or parsed.fragment:
        raise DagsterUrlConfigurationError(f"{setting_name} must not include query or fragment")
    if require_graphql_path and not parsed.path.rstrip("/").endswith("/graphql"):
        raise DagsterUrlConfigurationError(f"{setting_name} path must end with /graphql")
    return urlunsplit((scheme, parsed.netloc, parsed.path, "", ""))


def dagster_urls(settings: ApiSettings) -> DagsterUrls:
    allowed_hosts = _normalised_allowed_hosts(settings)
    dagster_url = _validated_http_url(
        settings.dagster_url,
        setting_name="dagster_url",
        allowed_hosts=allowed_hosts,
    )
    graphql_url = _validated_http_url(
        candidate_graphql_url(settings),
        setting_name="dagster_graphql_url",
        allowed_hosts=allowed_hosts,
        require_graphql_path=True,
    )
    return DagsterUrls(dagster_url=dagster_url.rstrip("/"), graphql_url=graphql_url)


def as_dict(value: object) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _string_list(value: object) -> list[str]:
    return [item for item in _list(value) if isinstance(item, str)]


def _asset_name(asset_node: JsonDict) -> str:
    asset_key = as_dict(asset_node.get("assetKey"))
    path = [part for part in _list(asset_key.get("path")) if isinstance(part, str)]
    if path:
        return "/".join(path)
    return _string(asset_node.get("id"), "unknown_asset")


def _asset_display_name(asset_name: str) -> str:
    return DAGSTER_ASSET_KOREAN_LABELS.get(asset_name, asset_name)


def _parse_jobs(raw_jobs: list[object]) -> list[DagsterJob]:
    jobs: list[DagsterJob] = []
    for raw in raw_jobs:
        entry = as_dict(raw)
        jobs.append(
            DagsterJob(
                name=_string(entry.get("name"), "unknown_job"),
                is_job=bool(entry.get("isJob")),
            )
        )
    return jobs


def _parse_graphql_error(raw_error: object) -> DagsterGraphqlError | None:
    error = as_dict(raw_error)
    if not error:
        return None
    return DagsterGraphqlError(
        message=optional_string(error.get("message")),
        stack=_string_list(error.get("stack")),
        class_name=optional_string(error.get("className")),
    )


def graphql_error_message(raw_error: object) -> str:
    """GraphQL ``errors[]`` 항목 → 사람이 읽을 메시지(dict repr 노출 방지).

    GraphQL 스펙 오류는 ``{"message": ..., "locations": ..., "path": ...}`` dict라
    ``str(dict)``이면 UI에 파이썬 repr이 새어나간다. ``message``를 우선 추출한다.
    """
    error = as_dict(raw_error)
    message = optional_string(error.get("message"))
    if message:
        return message
    return str(raw_error)


def _parse_ticks(raw_ticks: object) -> list[DagsterInstigationTick]:
    ticks: list[DagsterInstigationTick] = []
    for raw in _list(raw_ticks):
        entry = as_dict(raw)
        tick_id = _string(entry.get("tickId"))
        if not tick_id:
            continue
        ticks.append(
            DagsterInstigationTick(
                tick_id=tick_id,
                status=_string(entry.get("status"), "UNKNOWN"),
                timestamp=_optional_float(entry.get("timestamp")) or 0.0,
                end_timestamp=_optional_float(entry.get("endTimestamp")),
                run_ids=_string_list(entry.get("runIds")),
                run_keys=_string_list(entry.get("runKeys")),
                skip_reason=optional_string(entry.get("skipReason")),
                cursor=optional_string(entry.get("cursor")),
                error=_parse_graphql_error(entry.get("error")),
            )
        )
    return ticks


# 운영자 cron override 분 필드 ``*/N`` 최소 step(분). 정당한 10분 주기(KREX 교통공지)는
# 허용하되 그보다 잦은 고빈도는 막는다(#613 가드 + #617 KREX 10분 스케줄 reconcile).


def _schedule_note(schedule_name: str, default_cron: str | None) -> str | None:
    lowered = schedule_name.lower()
    if any(token in lowered for token in _FILE_DOWNLOAD_SCHEDULE_HINTS):
        return "파일 다운로드 계열 기본 주기는 월 1회입니다."
    if default_cron and default_cron.endswith(" * * * *"):
        return "provider rate limit의 약 90% 이하를 목표로 한 시간 단위 기본값입니다."
    return "provider rate limit의 약 90% 이하를 목표로 한 기본값입니다."


def default_cron_for_schedule(schedule_name: str, current_cron: str | None) -> str | None:
    return _DEFAULT_SCHEDULE_CRONS.get(schedule_name, current_cron)


def _parse_schedules(
    raw_schedules: list[object],
    *,
    overrides: dict[str, str] | None = None,
) -> list[DagsterSchedule]:
    schedules: list[DagsterSchedule] = []
    overrides = overrides or {}
    for raw in raw_schedules:
        entry = as_dict(raw)
        state = as_dict(entry.get("scheduleState"))
        name = _string(entry.get("name"), "unknown_schedule")
        cron_schedule = optional_string(entry.get("cronSchedule"))
        default_cron = default_cron_for_schedule(name, cron_schedule)
        schedules.append(
            DagsterSchedule(
                name=name,
                description=optional_string(entry.get("description")),
                pipeline_name=optional_string(entry.get("pipelineName")),
                mode=optional_string(entry.get("mode")),
                cron_schedule=cron_schedule,
                default_cron_schedule=default_cron,
                override_cron_schedule=overrides.get(name),
                execution_timezone=optional_string(entry.get("executionTimezone")),
                default_status=optional_string(entry.get("defaultStatus")),
                can_reset=bool(entry.get("canReset")),
                status=optional_string(state.get("status")),
                state_id=optional_string(state.get("id")),
                selector_id=optional_string(state.get("selectorId")),
                repository_name=optional_string(state.get("repositoryName")),
                repository_location_name=optional_string(state.get("repositoryLocationName")),
                schedule_note=_schedule_note(name, default_cron),
                recent_ticks=_parse_ticks(state.get("ticks")),
            )
        )
    return schedules


def _parse_sensors(raw_sensors: list[object]) -> list[DagsterSensor]:
    sensors: list[DagsterSensor] = []
    for raw in raw_sensors:
        entry = as_dict(raw)
        state = as_dict(entry.get("sensorState"))
        sensors.append(
            DagsterSensor(
                name=_string(entry.get("name"), "unknown_sensor"),
                status=optional_string(state.get("status")),
                recent_ticks=_parse_ticks(state.get("ticks")),
            )
        )
    return sensors


def _parse_asset_groups(raw_assets: list[object]) -> list[DagsterAssetGroup]:
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for raw in raw_assets:
        entry = as_dict(raw)
        group_name = _string(entry.get("groupName"), "default")
        groups[group_name].append(_asset_name(entry))

    return [
        DagsterAssetGroup(
            group_name=group_name,
            asset_count=len(assets),
            assets=sorted(assets),
            asset_items=[
                DagsterAssetSummary(
                    name=asset,
                    display_name=_asset_display_name(asset),
                )
                for asset in sorted(assets)
            ],
        )
        for group_name, assets in sorted(groups.items())
    ]


def parse_repositories(
    raw_connection: JsonDict,
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[list[DagsterRepository], list[str]]:
    errors: list[str] = []
    if raw_connection.get("__typename") != "RepositoryConnection":
        message = optional_string(raw_connection.get("message")) or "Dagster repository 조회 실패"
        return [], [message]

    repositories: list[DagsterRepository] = []
    for raw in _list(raw_connection.get("nodes")):
        entry = as_dict(raw)
        location = as_dict(entry.get("location"))
        assets = _list(entry.get("assetNodes"))
        repositories.append(
            DagsterRepository(
                name=_string(entry.get("name"), "__repository__"),
                location_name=_string(location.get("name"), "unknown_location"),
                jobs=_parse_jobs(_list(entry.get("pipelines"))),
                schedules=_parse_schedules(
                    _list(entry.get("schedules")),
                    overrides=overrides,
                ),
                sensors=_parse_sensors(_list(entry.get("sensors"))),
                asset_count=len(assets),
                asset_groups=_parse_asset_groups(assets),
            )
        )
    return repositories, errors


def parse_runs(raw_runs: JsonDict) -> tuple[list[DagsterRunSummary], dict[str, int], list[str]]:
    if raw_runs.get("__typename") != "Runs":
        message = optional_string(raw_runs.get("message")) or "Dagster run 조회 실패"
        return [], {}, [message]

    runs: list[DagsterRunSummary] = []
    counts: Counter[str] = Counter()
    for raw in _list(raw_runs.get("results")):
        entry = as_dict(raw)
        status = _string(entry.get("status"), "UNKNOWN")
        counts[status] += 1
        tags = {
            _string(as_dict(tag).get("key")): _string(as_dict(tag).get("value"))
            for tag in _list(entry.get("tags"))
            if _string(as_dict(tag).get("key"))
        }
        runs.append(
            DagsterRunSummary(
                run_id=_string(entry.get("runId"), "unknown_run"),
                job_name=optional_string(entry.get("jobName")),
                status=status,
                start_time=_optional_float(entry.get("startTime")),
                end_time=_optional_float(entry.get("endTime")),
                update_time=_optional_float(entry.get("updateTime")),
                tags=tags,
            )
        )
    return runs, dict(counts), []


def _parse_run_summary(entry: JsonDict) -> DagsterRunSummary:
    tags = {
        _string(as_dict(tag).get("key")): _string(as_dict(tag).get("value"))
        for tag in _list(entry.get("tags"))
        if _string(as_dict(tag).get("key"))
    }
    return DagsterRunSummary(
        run_id=_string(entry.get("runId"), "unknown_run"),
        job_name=optional_string(entry.get("jobName")),
        status=_string(entry.get("status"), "UNKNOWN"),
        start_time=_optional_float(entry.get("startTime")),
        end_time=_optional_float(entry.get("endTime")),
        update_time=_optional_float(entry.get("updateTime")),
        tags=tags,
    )


def _parse_run_event(raw_event: object) -> DagsterRunEvent:
    event = as_dict(raw_event)
    return DagsterRunEvent(
        event_type=_string(event.get("__typename"), "DagsterEvent"),
        message=optional_string(event.get("message")),
        timestamp=optional_string(event.get("timestamp")),
        level=optional_string(event.get("level")),
        step_id=optional_string(event.get("stepKey")),
        dagster_event_type=optional_string(event.get("eventType")),
        error=_parse_graphql_error(event.get("error")),
    )


def _is_failure_event(event: DagsterRunEvent) -> bool:
    if event.error is not None:
        return True
    event_type = (event.dagster_event_type or event.event_type).upper()
    return event.level == "ERROR" or "FAIL" in event_type


def _failure_message(event: DagsterRunEvent) -> str | None:
    if event.error is not None:
        if event.error.class_name and event.error.message:
            return f"{event.error.class_name}: {event.error.message}"
        if event.error.message:
            return event.error.message
        if event.error.class_name:
            return event.error.class_name
        return event.error.stack[0] if event.error.stack else None
    return event.message


def _run_failures(events: list[DagsterRunEvent]) -> list[DagsterRunFailure]:
    return [
        DagsterRunFailure(
            event_type=event.event_type,
            message=_failure_message(event),
            timestamp=event.timestamp,
            level=event.level,
            step_id=event.step_id,
            dagster_event_type=event.dagster_event_type,
            error=event.error,
        )
        for event in events
        if _is_failure_event(event)
    ]


def parse_run_detail(
    raw_run: JsonDict,
    *,
    dagster_urls: DagsterUrls,
    checked_at: datetime,
    expected_run_id: str,
) -> DagsterRunDetailData:
    typename = _string(raw_run.get("__typename"))
    if typename == "Run":
        raw_run_id = raw_run.get("runId")
        if not isinstance(raw_run_id, str) or not raw_run_id:
            return _run_detail_error(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                message="Dagster Run 응답에 유효한 runId가 없습니다.",
            )
        if raw_run_id != expected_run_id:
            return _run_detail_error(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                message=(
                    "Dagster Run 응답의 runId가 요청과 일치하지 않습니다: "
                    f"{raw_run_id}"
                ),
            )

        raw_event_connection = raw_run.get("eventConnection")
        if not isinstance(raw_event_connection, dict):
            return _run_detail_error(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                message="Dagster Run 응답의 eventConnection이 객체가 아닙니다.",
            )
        required_page_fields = {"cursor", "hasMore", "events"}
        missing_page_fields = required_page_fields - raw_event_connection.keys()
        if missing_page_fields:
            return _run_detail_error(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                message=(
                    "Dagster Run eventConnection 필드가 누락됐습니다: "
                    + ", ".join(sorted(missing_page_fields))
                ),
            )
        raw_cursor = raw_event_connection["cursor"]
        raw_has_more = raw_event_connection["hasMore"]
        raw_events = raw_event_connection["events"]
        if raw_cursor is not None and not isinstance(raw_cursor, str):
            return _run_detail_error(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                message="Dagster Run event cursor가 문자열 또는 null이 아닙니다.",
            )
        if not isinstance(raw_has_more, bool):
            return _run_detail_error(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                message="Dagster Run event hasMore가 boolean이 아닙니다.",
            )
        if not isinstance(raw_events, list):
            return _run_detail_error(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                message="Dagster Run events가 배열이 아닙니다.",
            )
        if raw_has_more and (
            not raw_cursor or len(raw_cursor) > _MAX_EVENT_CURSOR_LENGTH
        ):
            return _run_detail_error(
                dagster_urls=dagster_urls,
                checked_at=checked_at,
                message=(
                    "뒤 event page가 있지만 재사용 가능한 event cursor가 없습니다."
                ),
            )

        events = [
            _parse_run_event(raw_event) for raw_event in raw_events
        ]
        failure_events = _run_failures(events)
        return DagsterRunDetailData(
            status="ok",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            run=_parse_run_summary(raw_run),
            events=events,
            failure_reason=(failure_events[-1].message if failure_events else None),
            failure_events=failure_events,
            event_cursor=raw_cursor,
            event_has_more=raw_has_more,
        )
    if typename == "RunNotFoundError":
        return DagsterRunDetailData(
            status="not_found",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            errors=[_string(raw_run.get("message"), "Dagster run을 찾을 수 없습니다.")],
        )
    if typename == "PythonError":
        message = optional_string(raw_run.get("message")) or "Dagster run 상세 조회 실패"
        return DagsterRunDetailData(
            status="error",
            dagster_url=dagster_urls.dagster_url,
            graphql_url=dagster_urls.graphql_url,
            checked_at=checked_at,
            errors=[message],
        )
    return DagsterRunDetailData(
        status="error",
        dagster_url=dagster_urls.dagster_url,
        graphql_url=dagster_urls.graphql_url,
        checked_at=checked_at,
        errors=[f"알 수 없는 Dagster run 응답 타입: {typename or 'unknown'}"],
    )


def _run_detail_error(
    *, dagster_urls: DagsterUrls, checked_at: datetime, message: str
) -> DagsterRunDetailData:
    return DagsterRunDetailData(
        status="error",
        dagster_url=dagster_urls.dagster_url,
        graphql_url=dagster_urls.graphql_url,
        checked_at=checked_at,
        errors=[message],
    )


async def post_graphql(
    client: httpx.AsyncClient,
    graphql_url: str,
    variables: dict[str, object],
    query: str,
) -> JsonDict:
    response = await client.post(
        graphql_url,
        json={"query": query, "variables": variables},
    )
    response.raise_for_status()
    payload = response.json()
    return as_dict(payload)
