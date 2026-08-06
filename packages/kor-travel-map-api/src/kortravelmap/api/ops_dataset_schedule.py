"""dataset grid용 Dagster schedule projection.

Schedule은 DB catalog가 소유한 ``operation_key`` tag로만 dataset에 연결한다.
provider/dataset pair를 Dagster tag·Python registry에 중복 보관하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from kortravelmap.api import dagster_graphql
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "DatasetScheduleIndex",
    "DatasetScheduleState",
    "load_dataset_schedule_index",
]

ScheduleSourceStatus = Literal["ok", "unavailable", "error"]
OPERATION_KEY_TAG = "kor_travel_map.operation_key"

_QUERY = """
query KorTravelMapDatasetSchedules {
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        schedules {
          name
          pipelineName
          tags { key value }
          scheduleState { status }
          futureTicks(limit: 1) { results { timestamp } }
        }
      }
    }
    ... on PythonError { message }
  }
}
"""


@dataclass(frozen=True)
class DatasetScheduleState:
    """동일 dataset에 매핑된 schedule들의 실제 상태."""

    basis: Literal["dagster_operation_key_tag", "not_scheduled", "unknown"]
    status: str | None
    schedule_names: tuple[str, ...]
    active_schedule_names: tuple[str, ...]
    next_scheduled_at: datetime | None


@dataclass(frozen=True)
class DatasetScheduleIndex:
    """한 번의 GraphQL 조회 결과."""

    source_status: ScheduleSourceStatus
    errors: tuple[str, ...]
    by_operation_key: dict[str, DatasetScheduleState]

    def for_operation_keys(
        self,
        operation_keys: tuple[str, ...],
    ) -> DatasetScheduleState:
        mapped = tuple(
            self.by_operation_key[key]
            for key in operation_keys
            if key in self.by_operation_key
        )
        if mapped:
            names = tuple(sorted({name for item in mapped for name in item.schedule_names}))
            active_names = tuple(
                sorted({name for item in mapped for name in item.active_schedule_names})
            )
            next_ticks = [item.next_scheduled_at for item in mapped if item.next_scheduled_at]
            statuses = {item.status for item in mapped if item.status is not None}
            status = (
                "RUNNING"
                if active_names
                else next(iter(statuses))
                if len(statuses) == 1
                else "MIXED"
                if statuses
                else None
            )
            return DatasetScheduleState(
                basis="dagster_operation_key_tag",
                status=status,
                schedule_names=names,
                active_schedule_names=active_names,
                next_scheduled_at=min(next_ticks) if next_ticks else None,
            )
        if self.source_status == "ok":
            return DatasetScheduleState(
                basis="not_scheduled",
                status=None,
                schedule_names=(),
                active_schedule_names=(),
                next_scheduled_at=None,
            )
        return DatasetScheduleState(
            basis="unknown",
            status=None,
            schedule_names=(),
            active_schedule_names=(),
            next_scheduled_at=None,
        )


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)


def _parse(payload: dict[str, Any]) -> DatasetScheduleIndex:
    graphql_errors = payload.get("errors")
    if isinstance(graphql_errors, list) and graphql_errors:
        return DatasetScheduleIndex(
            source_status="error",
            errors=tuple(
                dagster_graphql.graphql_error_message(error)
                for error in graphql_errors
            ),
            by_operation_key={},
        )
    connection = _dict(_dict(payload.get("data")).get("repositoriesOrError"))
    if connection.get("__typename") != "RepositoryConnection":
        message = _text(connection.get("message")) or "Dagster schedule 조회 실패"
        return DatasetScheduleIndex(
            source_status="error",
            errors=(message,),
            by_operation_key={},
        )

    grouped: dict[str, list[tuple[str, str | None, datetime | None]]] = {}
    for node in _list(connection.get("nodes")):
        for raw_schedule in _list(_dict(node).get("schedules")):
            schedule = _dict(raw_schedule)
            tags = {
                tag_key: tag_value
                for raw_tag in _list(schedule.get("tags"))
                if (tag_key := _text(_dict(raw_tag).get("key"))) is not None
                and (tag_value := _text(_dict(raw_tag).get("value"))) is not None
            }
            name = _text(schedule.get("name"))
            if name is None:
                continue
            operation_key = tags.get(OPERATION_KEY_TAG)
            if operation_key is None:
                continue
            pipeline_name = _text(schedule.get("pipelineName"))
            if pipeline_name != operation_key:
                continue
            status = _text(_dict(schedule.get("scheduleState")).get("status"))
            next_tick: datetime | None = None
            if status == "RUNNING":
                future_results = _list(
                    _dict(schedule.get("futureTicks")).get("results")
                )
                if future_results:
                    next_tick = _timestamp(_dict(future_results[0]).get("timestamp"))
            grouped.setdefault(operation_key, []).append((name, status, next_tick))

    by_operation_key: dict[str, DatasetScheduleState] = {}
    for group_key, schedules in grouped.items():
        names = tuple(sorted(name for name, _, _ in schedules))
        active_names = tuple(
            sorted(name for name, status, _ in schedules if status == "RUNNING")
        )
        next_ticks = [
            tick
            for _, status, tick in schedules
            if status == "RUNNING" and tick is not None
        ]
        statuses = {status for _, status, _ in schedules if status is not None}
        if active_names:
            aggregate_status = "RUNNING"
        elif len(statuses) == 1:
            aggregate_status = next(iter(statuses))
        elif statuses:
            aggregate_status = "MIXED"
        else:
            aggregate_status = None
        by_operation_key[group_key] = DatasetScheduleState(
            basis="dagster_operation_key_tag",
            status=aggregate_status,
            schedule_names=names,
            active_schedule_names=active_names,
            next_scheduled_at=min(next_ticks) if next_ticks else None,
        )
    return DatasetScheduleIndex(
        source_status="ok",
        errors=(),
        by_operation_key=by_operation_key,
    )


async def load_dataset_schedule_index(
    *,
    settings: ApiSettings,
    client: httpx.AsyncClient,
) -> DatasetScheduleIndex:
    """Dagster 전체 schedule을 한 번 읽는다. 실패해도 DB grid는 degrade한다."""
    try:
        urls = dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
        return DatasetScheduleIndex(
            source_status="error", errors=(str(exc),), by_operation_key={}
        )
    try:
        payload = await dagster_graphql.post_graphql(
            client=client,
            graphql_url=urls.graphql_url,
            variables={},
            query=_QUERY,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return DatasetScheduleIndex(
            source_status="unavailable", errors=(str(exc),), by_operation_key={}
        )
    return _parse(payload)
