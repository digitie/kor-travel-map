"""dataset grid용 Dagster schedule projection (#678).

전체 schedule을 GraphQL 한 번으로 읽고 공용 registry version/digest로 검증한
canonical identity tag의 exact pair만 사용한다. 등록 feature job은 ``pipelineName``과
identity job까지 같아야 한다. scalar provider/dataset fallback과 schedule 이름 추론은 금지한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from kortravelmap.providers.feature_operation_registry import (
    FEATURE_OPERATION_IDENTITY_TAG,
    FEATURE_OPERATION_REGISTRY_BY_JOB,
    FEATURE_OPERATION_REGISTRY_VERSION_TAG,
    FeatureOperationRegistryError,
    parse_feature_operation_identity_tags,
)

from kortravelmap.api import dagster_graphql
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "DatasetScheduleIndex",
    "DatasetScheduleState",
    "load_dataset_schedule_index",
]

ScheduleSourceStatus = Literal["ok", "unavailable", "error"]

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

    basis: Literal["dagster_definition_tags", "not_scheduled", "unknown"]
    status: str | None
    schedule_names: tuple[str, ...]
    active_schedule_names: tuple[str, ...]
    next_scheduled_at: datetime | None


@dataclass(frozen=True)
class DatasetScheduleIndex:
    """한 번의 GraphQL 조회 결과."""

    source_status: ScheduleSourceStatus
    errors: tuple[str, ...]
    by_dataset: dict[tuple[str, str], DatasetScheduleState]

    def for_dataset(self, provider: str, dataset_key: str) -> DatasetScheduleState:
        mapped = self.by_dataset.get((provider, dataset_key))
        if mapped is not None:
            return mapped
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
            by_dataset={},
        )
    connection = _dict(_dict(payload.get("data")).get("repositoriesOrError"))
    if connection.get("__typename") != "RepositoryConnection":
        message = _text(connection.get("message")) or "Dagster schedule 조회 실패"
        return DatasetScheduleIndex(
            source_status="error",
            errors=(message,),
            by_dataset={},
        )

    grouped: dict[tuple[str, str], list[tuple[str, str | None, datetime | None]]] = {}
    identity_errors: list[str] = []
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
            pipeline_name = _text(schedule.get("pipelineName"))
            has_identity_tag = FEATURE_OPERATION_IDENTITY_TAG in tags
            has_version_tag = FEATURE_OPERATION_REGISTRY_VERSION_TAG in tags
            if pipeline_name is None:
                identity_errors.append(f"{name}: pipelineName 누락")
                continue
            if not has_identity_tag and not has_version_tag:
                if pipeline_name in FEATURE_OPERATION_REGISTRY_BY_JOB:
                    identity_errors.append(
                        f"{name}: 등록 feature job의 canonical identity/version tag 누락"
                    )
                continue
            try:
                identity = parse_feature_operation_identity_tags(tags)
            except FeatureOperationRegistryError as exc:
                identity_errors.append(f"{name}: {exc.reason}")
                continue
            if identity is None:
                identity_errors.append(f"{name}: canonical identity 누락")
                continue
            if identity.job_name != pipeline_name:
                identity_errors.append(
                    f"{name}: identity job/pipelineName 불일치"
                )
                continue
            status = _text(_dict(schedule.get("scheduleState")).get("status"))
            next_tick: datetime | None = None
            if status == "RUNNING":
                future_results = _list(
                    _dict(schedule.get("futureTicks")).get("results")
                )
                if future_results:
                    next_tick = _timestamp(_dict(future_results[0]).get("timestamp"))
            for pair in identity.pairs:
                grouped.setdefault((pair.provider, pair.dataset_key), []).append(
                    (name, status, next_tick)
                )

    by_dataset: dict[tuple[str, str], DatasetScheduleState] = {}
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
        by_dataset[group_key] = DatasetScheduleState(
            basis="dagster_definition_tags",
            status=aggregate_status,
            schedule_names=names,
            active_schedule_names=active_names,
            next_scheduled_at=min(next_ticks) if next_ticks else None,
        )
    return DatasetScheduleIndex(
        source_status="error" if identity_errors else "ok",
        errors=tuple(identity_errors),
        by_dataset=by_dataset,
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
            source_status="error", errors=(str(exc),), by_dataset={}
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
            source_status="unavailable", errors=(str(exc),), by_dataset={}
        )
    return _parse(payload)
