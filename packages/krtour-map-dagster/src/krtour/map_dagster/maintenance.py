"""Dagster consistency/dedup refresh 운영 job."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, cast

from dagster import (
    Array,
    Bool,
    DefaultScheduleStatus,
    Field,
    Int,
    OpExecutionContext,
    Permissive,
    ScheduleDefinition,
    job,
    op,
)
from krtour.map.infra.consistency import DEDUP_PENDING_WARN_THRESHOLD
from krtour.map.infra.dedup_refresh_repo import (
    DEDUP_REFRESH_DEFAULT_LIMIT,
    DedupRefreshScope,
)

from .schedules import KST_TIMEZONE

if TYPE_CHECKING:
    from krtour.map.client import AsyncKrtourMapClient, DedupRefreshResult
    from krtour.map.infra.consistency import ConsistencyReport

_PERMISSIVE_CONFIG = cast(Any, Permissive)

__all__ = [
    "CONSISTENCY_DEDUP_REFRESH_JOB_TAGS",
    "CONSISTENCY_DEDUP_REFRESH_SCHEDULES",
    "MAINTENANCE_JOBS",
    "MAINTENANCE_SCHEDULES",
    "consistency_dedup_refresh_job",
    "refresh_dedup_candidates_op",
    "run_consistency_check_op",
]

CONSISTENCY_DEDUP_REFRESH_JOB_TAGS: Final[dict[str, str]] = {
    "krtour_map.job_scope": "maintenance",
    "krtour_map.job_kind": "consistency_dedup_refresh",
    "krtour_map.timezone": KST_TIMEZONE,
}
"""consistency/dedup refresh Dagster job 공통 tag."""

_DEDUP_REFRESH_CONFIG_SCHEMA: Final[dict[str, object]] = {
    "pairs": Field(
        Array(_PERMISSIVE_CONFIG()),
        default_value=[],
        description=(
            "cross-provider dedup scope pair 목록. 각 항목은 "
            "{left:{provider,dataset_key?}, right:{provider,dataset_key?}}."
        ),
    ),
    "sibling_scopes": Field(
        Array(_PERMISSIVE_CONFIG()),
        default_value=[],
        description="within-dataset sibling dedup scope 목록.",
    ),
    "include_auto_merge": Field(
        Bool,
        default_value=True,
        description="auto_merge 후보까지 큐에 포함할지 여부.",
    ),
    "limit": Field(
        Int,
        default_value=DEDUP_REFRESH_DEFAULT_LIMIT,
        description="scope별 feature 조회 기본 상한.",
    ),
}

_CONSISTENCY_CONFIG_SCHEMA: Final[dict[str, object]] = {
    "persist": Field(
        Bool,
        default_value=True,
        description="ops.feature_consistency_reports에 리포트를 저장할지 여부.",
    ),
    "sample_limit": Field(
        Int,
        default_value=20,
        description="case별 sample id 상한.",
    ),
    "dedup_pending_threshold": Field(
        Int,
        default_value=DEDUP_PENDING_WARN_THRESHOLD,
        description="F4 pending dedup backlog WARN 임계값.",
    ),
}


@op(
    name="refresh_dedup_candidates",
    required_resource_keys={"krtour_map_client"},
    config_schema=_DEDUP_REFRESH_CONFIG_SCHEMA,
)
async def refresh_dedup_candidates_op(
    context: OpExecutionContext,
) -> dict[str, object]:
    """DB 기준 provider/dataset scope의 dedup 후보 큐를 갱신한다."""
    client = cast("AsyncKrtourMapClient", _resource_object(context, "krtour_map_client"))
    config = cast(Mapping[str, object], context.op_config)
    include_auto_merge = bool(config.get("include_auto_merge", True))
    default_limit = _int_config(
        config.get("limit"), default=DEDUP_REFRESH_DEFAULT_LIMIT
    )

    pair_results: list[DedupRefreshResult] = []
    for pair in _mapping_list(config.get("pairs")):
        left = _scope_from_config(pair.get("left"), default_limit=default_limit)
        right = _scope_from_config(pair.get("right"), default_limit=default_limit)
        pair_results.append(
            await client.refresh_dedup_candidates_for_scope_pair(
                left, right, include_auto_merge=include_auto_merge
            )
        )

    sibling_results: list[DedupRefreshResult] = []
    for scope_config in _mapping_list(config.get("sibling_scopes")):
        scope = _scope_from_config(scope_config, default_limit=default_limit)
        sibling_results.append(
            await client.refresh_sibling_dedup_candidates(
                scope, include_auto_merge=include_auto_merge
            )
        )

    metadata = _dedup_metadata(
        pair_results=pair_results,
        sibling_results=sibling_results,
    )
    context.add_output_metadata(metadata)
    return metadata


@op(
    name="run_consistency_check",
    required_resource_keys={"krtour_map_client"},
    config_schema=_CONSISTENCY_CONFIG_SCHEMA,
)
async def run_consistency_check_op(
    context: OpExecutionContext,
    dedup_refresh: dict[str, object],
) -> dict[str, object]:
    """dedup refresh 뒤 F1~F4 consistency report를 실행한다."""
    client = cast("AsyncKrtourMapClient", _resource_object(context, "krtour_map_client"))
    config = cast(Mapping[str, object], context.op_config)
    report = await client.run_consistency_report(
        persist=bool(config.get("persist", True)),
        sample_limit=_int_config(config.get("sample_limit"), default=20),
        dedup_pending_threshold=_int_config(
            config.get("dedup_pending_threshold"),
            default=DEDUP_PENDING_WARN_THRESHOLD,
        ),
    )
    metadata = _consistency_metadata(report, dedup_refresh=dedup_refresh)
    context.add_output_metadata(metadata)
    return metadata


@job(
    name="consistency_dedup_refresh",
    tags=CONSISTENCY_DEDUP_REFRESH_JOB_TAGS,
    description="DB 기준 dedup 후보 큐를 갱신한 뒤 F1~F4 consistency report를 저장한다.",
)
def consistency_dedup_refresh_job() -> None:
    """운영자가 Dagster UI/API에서 실행하는 consistency/dedup refresh job."""
    run_consistency_check_op(refresh_dedup_candidates_op())


CONSISTENCY_DEDUP_REFRESH_SCHEDULES: Final = [
    ScheduleDefinition(
        name="consistency_dedup_refresh_daily_schedule",
        job=consistency_dedup_refresh_job,
        cron_schedule="45 5 * * *",
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags=CONSISTENCY_DEDUP_REFRESH_JOB_TAGS,
        description="dedup 후보 큐 재계산과 consistency report를 일 1회 실행한다.",
    )
]
"""consistency/dedup maintenance schedule 목록. 운영 enable 전까지 STOPPED."""

MAINTENANCE_JOBS: Final = [consistency_dedup_refresh_job]
MAINTENANCE_SCHEDULES: Final = CONSISTENCY_DEDUP_REFRESH_SCHEDULES


def _resource_object(context: OpExecutionContext, name: str) -> object:
    resources = cast(Any, context.resources)
    if not hasattr(resources, name):
        raise AttributeError(f"Dagster resource 없음: {name}")
    return getattr(resources, name)


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("dedup refresh config list가 아님")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("dedup refresh config item은 mapping이어야 함")
        result.append(cast(Mapping[str, object], item))
    return result


def _scope_from_config(
    value: object,
    *,
    default_limit: int,
) -> DedupRefreshScope:
    if not isinstance(value, Mapping):
        raise TypeError("dedup refresh scope는 mapping이어야 함")
    provider = value.get("provider")
    if not isinstance(provider, str) or not provider:
        raise ValueError("dedup refresh scope.provider는 필수")
    dataset_key_value = value.get("dataset_key")
    if dataset_key_value is not None and not isinstance(dataset_key_value, str):
        raise TypeError("dedup refresh scope.dataset_key는 문자열이어야 함")
    limit_value = value.get("limit", default_limit)
    return DedupRefreshScope(
        provider=provider,
        dataset_key=dataset_key_value,
        kinds=_string_tuple(value.get("kinds")),
        categories=_string_tuple(value.get("categories")),
        limit=_int_config(limit_value, default=default_limit),
        cursor_updated_at=_datetime_config(value.get("cursor_updated_at")),
        cursor_feature_id=_optional_string(value.get("cursor_feature_id")),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence):
        raise TypeError("dedup refresh scope filter는 문자열 목록이어야 함")
    return tuple(str(item) for item in value if str(item))


def _int_config(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise TypeError("정수 config에 boolean은 사용할 수 없음")
    if isinstance(value, int | str):
        return int(value)
    raise TypeError("정수 config 값이어야 함")


def _datetime_config(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError("datetime config 값은 ISO 문자열이어야 함")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("문자열 config 값이어야 함")
    return value


def _dedup_metadata(
    *,
    pair_results: list["DedupRefreshResult"],
    sibling_results: list["DedupRefreshResult"],
) -> dict[str, object]:
    results = [*pair_results, *sibling_results]
    return {
        "pair_scope_count": len(pair_results),
        "sibling_scope_count": len(sibling_results),
        "feature_left_total": sum(result.left_count for result in results),
        "feature_right_total": sum(result.right_count for result in results),
        "candidates_total": sum(len(result.candidates) for result in results),
        "queue_inserted": sum(result.queue.inserted for result in results),
        "queue_updated": sum(result.queue.updated for result in results),
        "queue_skipped": sum(result.queue.skipped for result in results),
        "results": [result.as_metadata() for result in results],
    }


def _consistency_metadata(
    report: "ConsistencyReport",
    *,
    dedup_refresh: dict[str, object],
) -> dict[str, object]:
    return {
        "batch_id": report.batch_id,
        "severity_max": report.severity_max,
        "total_violations": int(report.summary.get("total_violations", 0)),
        "cases_evaluated": int(report.summary.get("cases_evaluated", 0)),
        "case_counts": dict(report.summary.get("by_code", {})),
        "dedup_candidates_total": dedup_refresh.get("candidates_total", 0),
        "dedup_queue_inserted": dedup_refresh.get("queue_inserted", 0),
        "dedup_queue_updated": dedup_refresh.get("queue_updated", 0),
        "dedup_queue_skipped": dedup_refresh.get("queue_skipped", 0),
    }
