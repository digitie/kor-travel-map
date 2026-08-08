"""Dagster consistency/dedup refresh 운영 job."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING, Any, Final, cast

from kortravelmap.dto._time import kst_now
from kortravelmap.infra.consistency import DEDUP_PENDING_WARN_THRESHOLD
from kortravelmap.infra.dedup_refresh_repo import (
    DEDUP_REFRESH_DEFAULT_LIMIT,
    DedupRefreshScope,
)

from dagster import (
    Array,
    Backoff,
    Bool,
    DagsterRunStatus,
    DefaultScheduleStatus,
    Failure,
    Field,
    Int,
    OpExecutionContext,
    Permissive,
    RetryPolicy,
    RunRequest,
    RunsFilter,
    ScheduleDefinition,
    ScheduleEvaluationContext,
    SkipReason,
    job,
    op,
)

from .schedule_overrides import cron_for_schedule
from .schedules import KST_TIMEZONE

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient, DedupRefreshResult
    from kortravelmap.infra.consistency import ConsistencyReport

_PERMISSIVE_CONFIG = cast(Any, Permissive)

__all__ = [
    "CACHE_TARGET_SNAPSHOT_GC_JOB_TAGS",
    "CACHE_TARGET_SNAPSHOT_GC_SCHEDULES",
    "CURRENT_WEATHER_SUMMARY_REFRESH_JOB_TAGS",
    "CURRENT_WEATHER_SUMMARY_REFRESH_SCHEDULES",
    "CONSISTENCY_DEDUP_REFRESH_JOB_TAGS",
    "CONSISTENCY_DEDUP_REFRESH_SCHEDULES",
    "DEFAULT_DEDUP_SCOPE_PAIRS",
    "DEFAULT_DEDUP_SIBLING_SCOPES",
    "MAINTENANCE_RETRY_POLICY",
    "MAINTENANCE_JOBS",
    "MAINTENANCE_SCHEDULES",
    "FINDING_PURGE_DEFAULT_RETENTION",
    "NOTICE_PURGE_DEFAULT_RETENTION",
    "consistency_dedup_refresh_job",
    "cache_target_snapshot_gc_job",
    "current_weather_summary_refresh_job",
    "drain_expired_cache_target_snapshots_op",
    "materialize_current_weather_summary_op",
    "purge_expired_notices_op",
    "purge_resolved_integrity_findings_op",
    "refresh_dedup_candidates_op",
    "run_consistency_check_op",
]

CONSISTENCY_DEDUP_REFRESH_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": "maintenance",
    "kor_travel_map.job_kind": "consistency_dedup_refresh",
    "kor_travel_map.timezone": KST_TIMEZONE,
}
"""consistency/dedup refresh Dagster job 공통 tag."""

CACHE_TARGET_SNAPSHOT_GC_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": "maintenance",
    "kor_travel_map.job_kind": "cache_target_snapshot_gc",
    "kor_travel_map.timezone": KST_TIMEZONE,
}
"""cache-target snapshot background GC job 공통 tag."""

CURRENT_WEATHER_SUMMARY_REFRESH_JOB_TAGS: Final[dict[str, str]] = {
    "kor_travel_map.job_scope": "maintenance",
    "kor_travel_map.job_kind": "current_weather_summary_refresh",
    "kor_travel_map.timezone": KST_TIMEZONE,
}
"""weather deadline-driven current projection refresh Dagster job 공통 tag."""

_WEATHER_SUMMARY_ACTIVE_RUN_STATUSES: Final[tuple[DagsterRunStatus, ...]] = (
    DagsterRunStatus.QUEUED,
    DagsterRunStatus.NOT_STARTED,
    DagsterRunStatus.MANAGED,
    DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED,
    DagsterRunStatus.CANCELING,
)
"""minute tick이 전역 projection job을 backlog로 쌓지 않게 하는 active 상태."""

MAINTENANCE_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=Backoff.EXPONENTIAL,
)
"""consistency/dedup maintenance op 공통 retry policy."""

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

_CACHE_TARGET_SNAPSHOT_GC_CONFIG_SCHEMA: Final[dict[str, object]] = {
    "max_batches": Field(
        Int,
        default_value=2_000,
        description="실행당 최대 batch 수(기본 item 처리 용량 2,000,000건).",
    ),
    "max_seconds": Field(
        Int,
        default_value=3_300,
        description="hourly schedule 다음 실행 전 drain 종료 시간 예산(초).",
    ),
    "item_limit": Field(
        Int,
        default_value=1_000,
        description="system별 transaction에서 삭제할 snapshot item 상한.",
    ),
    "header_limit": Field(
        Int,
        default_value=100,
        description="system별 transaction에서 삭제할 빈 snapshot header 상한.",
    ),
    "batch_statement_timeout_ms": Field(
        Int,
        default_value=30_000,
        description="각 GC/observation transaction의 PostgreSQL statement timeout(ms).",
    ),
    "referenced_item_ceiling": Field(
        Int,
        default_value=16_800_000,
        description="영구 참조 snapshot item 보존량 alert ceiling.",
    ),
    "referenced_header_ceiling": Field(
        Int,
        default_value=168,
        description="영구 참조 snapshot header 보존량 alert ceiling.",
    ),
    "referenced_item_growth_ceiling_per_hour": Field(
        Int,
        default_value=100_000,
        description="직전 적격 baseline 대비 referenced item 시간당 증가 alert ceiling.",
    ),
    "referenced_header_growth_ceiling_per_hour": Field(
        Int,
        default_value=1,
        description="직전 적격 baseline 대비 referenced header 시간당 증가 alert ceiling.",
    ),
    "referenced_growth_min_interval_seconds": Field(
        Int,
        default_value=300,
        description="증가율 alert를 평가할 두 관측 사이 최소 간격(초).",
    ),
    "observation_retention_days": Field(
        Int,
        default_value=90,
        description="run별 referenced count 관측 이력 보존 일수.",
    ),
}


DEFAULT_DEDUP_SCOPE_PAIRS: Final[tuple[Mapping[str, object], ...]] = (
    # KNPS 문화시설/사찰(cultural_resources) ↔ 국가유산(krheritage) — 동일 사찰·문화재가
    # 양 provider에 중복 적재될 수 있다(ADR-034 6단계 메모). 실제 중복만 threshold(0.65)
    # 이상으로 큐에 적재되므로 비중복은 노이즈가 되지 않는다.
    {
        "left": {"provider": "python-knps-api"},
        "right": {"provider": "python-krheritage-api"},
    },
    # 자연휴양림(krforest, category 03030000) ↔ MOIS 관광숙박/리조트(ADR-034 8단계 —
    # 휴양림은 콘도/관광숙박과 중복 가능). MOIS side는 관련 LODGING 카테고리로 좁혀
    # 대규모 MOIS 전체 비교를 피한다. 수목원(arboretum)은 MOIS PROMOTED 슬러그에 식물원/
    # 수목원이 없어 dedup 후보가 없으므로 pair를 추가하지 않는다.
    {
        "left": {
            "provider": "python-krforest-api",
            "dataset_key": "krforest_recreation_forests",
        },
        "right": {
            "provider": "python-mois-api",
            "categories": ["03010100", "03020100", "03020200"],
        },
    },
    # 박물관/미술관(data.go.kr-standard) ↔ MOIS museums_and_art_galleries(ADR-034 9단계).
    # MOIS museums_and_art_galleries는 category 01040000(문화시설)으로 적재되므로 그 한
    # 카테고리로 좁힌다. standard 박물관/미술관은 01040000/01040100/01040200 모두 가능.
    {
        "left": {
            "provider": "data.go.kr-standard",
            "dataset_key": "datagokr_museums",
        },
        "right": {
            "provider": "python-mois-api",
            "categories": ["01040000"],
        },
    },
    # 관광지(data.go.kr-standard) ↔ MOIS 관광사업체(tourism_businesses, 01000000)
    # — 동일 관광지가 양쪽에 적재될 수 있다(ADR-034 보조).
    {
        "left": {
            "provider": "data.go.kr-standard",
            "dataset_key": "datagokr_tourist_attractions",
        },
        "right": {
            "provider": "python-mois-api",
            "categories": ["01000000"],
        },
    },
)
"""op_config가 비었을 때 적용하는 기본 cross-provider dedup scope pair.

신규 MOIS-sibling provider(standard_data 박물관/미술관 등)는 해당 feature-load PR에서
``{left: {provider: <new>}, right: {provider: python-mois-api, categories: [...]}}`` pair를
본 tuple에 추가한다(ADR-034 9단계).
"""

DEFAULT_DEDUP_SIBLING_SCOPES: Final[tuple[Mapping[str, object], ...]] = ()
"""op_config가 비었을 때 적용하는 기본 within-provider sibling dedup scope (현재 없음)."""


@op(
    name="refresh_dedup_candidates",
    required_resource_keys={"kor_travel_map_client"},
    config_schema=_DEDUP_REFRESH_CONFIG_SCHEMA,
    retry_policy=MAINTENANCE_RETRY_POLICY,
)
async def refresh_dedup_candidates_op(
    context: OpExecutionContext,
) -> dict[str, object]:
    """DB 기준 provider/dataset scope의 dedup 후보 큐를 갱신한다.

    ``pairs``/``sibling_scopes`` op_config가 둘 다 비어 있으면 ``DEFAULT_DEDUP_SCOPE_PAIRS``
    /``DEFAULT_DEDUP_SIBLING_SCOPES``를 적용한다 — 운영자가 Dagster run config를 매번 넘기지
    않아도 기본 cross-provider dedup이 돈다(신규 데이터소스는 기본 pair에 합류).
    """
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    config = cast(Mapping[str, object], context.op_config)
    include_auto_merge = bool(config.get("include_auto_merge", True))
    default_limit = _int_config(config.get("limit"), default=DEDUP_REFRESH_DEFAULT_LIMIT)

    pairs = _mapping_list(config.get("pairs"))
    sibling_scopes = _mapping_list(config.get("sibling_scopes"))
    if not pairs and not sibling_scopes:
        pairs = list(DEFAULT_DEDUP_SCOPE_PAIRS)
        sibling_scopes = list(DEFAULT_DEDUP_SIBLING_SCOPES)

    pair_results: list[DedupRefreshResult] = []
    for pair in pairs:
        left = _scope_from_config(pair.get("left"), default_limit=default_limit)
        right = _scope_from_config(pair.get("right"), default_limit=default_limit)
        pair_results.append(
            await client.refresh_dedup_candidates_for_scope_pair(
                left, right, include_auto_merge=include_auto_merge
            )
        )

    sibling_results: list[DedupRefreshResult] = []
    for scope_config in sibling_scopes:
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
    required_resource_keys={"kor_travel_map_client"},
    config_schema=_CONSISTENCY_CONFIG_SCHEMA,
    retry_policy=MAINTENANCE_RETRY_POLICY,
)
async def run_consistency_check_op(
    context: OpExecutionContext,
    dedup_refresh: dict[str, object],
) -> dict[str, object]:
    """dedup refresh 뒤 F1~F4 consistency report를 실행한다."""
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
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


NOTICE_PURGE_DEFAULT_RETENTION: Final[str] = "1 year"
"""만료 notice 보존 기간 — 종료일(없으면 발표일) + 본 기간 경과 시 soft-delete(§9)."""


FINDING_PURGE_DEFAULT_RETENTION: Final[str] = "90 days"
"""resolved finding 보존 기간 (T-VN-H32).

``NOTICE_PURGE_DEFAULT_RETENTION``(1년)보다 짧다 — finding은 notice와 달리 **운영 신호**라
분기 회고에 필요한 만큼만 둔다. ``acknowledged``는 어떤 경우에도 지우지 않는다.
"""


@op(
    name="purge_resolved_integrity_findings",
    required_resource_keys={"kor_travel_map_client"},
    config_schema={
        "retention": Field(
            str,
            default_value=FINDING_PURGE_DEFAULT_RETENTION,
            description="PostgreSQL interval 문자열 (예: '90 days').",
        ),
    },
    retry_policy=MAINTENANCE_RETRY_POLICY,
)
async def purge_resolved_integrity_findings_op(
    context: OpExecutionContext,
) -> dict[str, object]:
    """보존 기간이 지난 ``resolved`` finding을 삭제한다 (T-VN-H32R).

    immutable authoritative generation sweep이 만든 ``resolved`` 이력을 90일 보존한다.
    ``open``·``acknowledged``는 대상이 아니다.
    """
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    retention = str(context.op_config.get("retention", FINDING_PURGE_DEFAULT_RETENTION))
    purged = await client.purge_resolved_integrity_findings(retention=retention)
    metadata: dict[str, object] = {"purged": purged, "retention": retention}
    context.add_output_metadata(metadata)
    return metadata


@op(
    name="purge_expired_notices",
    required_resource_keys={"kor_travel_map_client"},
    config_schema={
        "retention": Field(
            str,
            default_value=NOTICE_PURGE_DEFAULT_RETENTION,
            description="PostgreSQL interval 문자열 (예: '1 year').",
        ),
    },
    retry_policy=MAINTENANCE_RETRY_POLICY,
)
async def purge_expired_notices_op(context: OpExecutionContext) -> dict[str, object]:
    """보존 기간이 지난 notice feature를 soft-delete한다 (#632, §9 보관 정책)."""
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    retention = str(context.op_config.get("retention", NOTICE_PURGE_DEFAULT_RETENTION))
    purged = await client.purge_expired_notices(retention=retention)
    metadata: dict[str, object] = {"purged": purged, "retention": retention}
    context.add_output_metadata(metadata)
    return metadata


@op(
    name="drain_expired_cache_target_snapshots",
    required_resource_keys={"kor_travel_map_client"},
    config_schema=_CACHE_TARGET_SNAPSHOT_GC_CONFIG_SCHEMA,
    retry_policy=MAINTENANCE_RETRY_POLICY,
)
async def drain_expired_cache_target_snapshots_op(
    context: OpExecutionContext,
) -> dict[str, object]:
    """만료·미참조 cache-target snapshot을 독립 batch transaction으로 정리한다."""
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    config = cast(Mapping[str, object], context.op_config)
    max_batches = _bounded_int_config(
        config.get("max_batches"), name="max_batches", default=2_000, minimum=1
    )
    max_seconds = _bounded_int_config(
        config.get("max_seconds"), name="max_seconds", default=3_300, minimum=1
    )
    item_limit = _bounded_int_config(
        config.get("item_limit"),
        name="item_limit",
        default=1_000,
        minimum=1,
        maximum=10_000,
    )
    header_limit = _bounded_int_config(
        config.get("header_limit"),
        name="header_limit",
        default=100,
        minimum=1,
        maximum=1_000,
    )
    statement_timeout_ms = _bounded_int_config(
        config.get("batch_statement_timeout_ms"),
        name="batch_statement_timeout_ms",
        default=30_000,
        minimum=1,
        maximum=300_000,
    )
    item_ceiling = _bounded_int_config(
        config.get("referenced_item_ceiling"),
        name="referenced_item_ceiling",
        default=16_800_000,
        minimum=0,
    )
    header_ceiling = _bounded_int_config(
        config.get("referenced_header_ceiling"),
        name="referenced_header_ceiling",
        default=168,
        minimum=0,
    )
    item_growth_ceiling = _bounded_int_config(
        config.get("referenced_item_growth_ceiling_per_hour"),
        name="referenced_item_growth_ceiling_per_hour",
        default=100_000,
        minimum=0,
    )
    header_growth_ceiling = _bounded_int_config(
        config.get("referenced_header_growth_ceiling_per_hour"),
        name="referenced_header_growth_ceiling_per_hour",
        default=1,
        minimum=0,
    )
    growth_min_interval_seconds = _bounded_int_config(
        config.get("referenced_growth_min_interval_seconds"),
        name="referenced_growth_min_interval_seconds",
        default=300,
        minimum=1,
        maximum=86_400,
    )
    observation_retention_days = _bounded_int_config(
        config.get("observation_retention_days"),
        name="observation_retention_days",
        default=90,
        minimum=1,
        maximum=3_650,
    )
    started_at = monotonic()
    result = await client.drain_expired_cache_target_snapshots(
        max_batches=max_batches,
        max_seconds=max_seconds,
        item_limit=item_limit,
        header_limit=header_limit,
        batch_statement_timeout_ms=statement_timeout_ms,
        observation_run_id=context.run_id,
        observation_retention_days=observation_retention_days,
        observation_growth_min_interval_seconds=growth_min_interval_seconds,
    )
    elapsed_seconds = max(monotonic() - started_at, 0.001)
    backlog_observed = result.remaining_items is not None
    metadata: dict[str, object] = {
        "acquired": result.acquired,
        "skipped": result.skipped,
        "batches": result.batches,
        "deleted_items": result.deleted_items,
        "deleted_headers": result.deleted_headers,
        "remaining_items": (
            result.remaining_items
            if result.remaining_items is not None
            else "not_observed"
        ),
        "remaining_headers": (
            result.remaining_headers
            if result.remaining_headers is not None
            else "not_observed"
        ),
        "total_items": result.total_items if result.total_items is not None else "not_observed",
        "total_headers": (
            result.total_headers if result.total_headers is not None else "not_observed"
        ),
        "unexpired_unreferenced_items": (
            result.unexpired_unreferenced_items
            if result.unexpired_unreferenced_items is not None
            else "not_observed"
        ),
        "unexpired_unreferenced_headers": (
            result.unexpired_unreferenced_headers
            if result.unexpired_unreferenced_headers is not None
            else "not_observed"
        ),
        "referenced_items": (
            result.referenced_items
            if result.referenced_items is not None
            else "not_observed"
        ),
        "referenced_headers": (
            result.referenced_headers
            if result.referenced_headers is not None
            else "not_observed"
        ),
        "backlog_observed": backlog_observed,
        "backlog_alert": bool(
            backlog_observed
            and ((result.remaining_items or 0) > 0 or (result.remaining_headers or 0) > 0)
        ),
        "capacity_item_ceiling": max_batches * item_limit,
        "elapsed_seconds": elapsed_seconds,
        "deleted_items_per_hour": result.deleted_items / elapsed_seconds * 3_600,
    }
    metadata.update(
        _cache_target_referenced_alert_metadata(
            result,
            item_ceiling=item_ceiling,
            header_ceiling=header_ceiling,
            item_growth_ceiling_per_hour=item_growth_ceiling,
            header_growth_ceiling_per_hour=header_growth_ceiling,
            growth_min_interval_seconds=growth_min_interval_seconds,
            observation_retention_days=observation_retention_days,
        )
    )
    if metadata["referenced_alert"]:
        context.log.warning(
            "cache-target referenced snapshot 보존 alert: %s",
            metadata["referenced_alert_reasons"],
        )
    if metadata["referenced_observation_issue"]:
        context.log.warning(
            "cache-target referenced snapshot 관측 품질 경고: %s",
            metadata["referenced_observation_issue_reasons"],
        )
    context.add_output_metadata(metadata)
    return metadata


@op(
    name="materialize_current_weather_summary",
    required_resource_keys={"kor_travel_map_client"},
    retry_policy=MAINTENANCE_RETRY_POLICY,
)
async def materialize_current_weather_summary_op(
    context: OpExecutionContext,
) -> dict[str, object]:
    """새 provider write가 없어도 deadline을 지난 weather winner를 재선정한다."""
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    result = await client.materialize_current_weather_summary(
        selected_at=kst_now(),
        run_kind="reconcile",
    )
    metadata: dict[str, object] = {
        "summary_run_id": result.summary_run_id,
        "selected_at": result.selected_at.isoformat(),
        "input_count": result.input_count,
        "inserted_count": result.inserted_count,
        "updated_count": result.updated_count,
        "deleted_count": result.deleted_count,
    }
    context.add_output_metadata(metadata)
    return metadata


@job(
    name="consistency_dedup_refresh",
    tags=CONSISTENCY_DEDUP_REFRESH_JOB_TAGS,
    description=(
        "DB 기준 dedup 후보 큐를 갱신한 뒤 F1~F4 consistency report를 저장하고, "
        "보존 기간이 지난 notice와 resolved integrity finding을 정리한다."
    ),
)
def consistency_dedup_refresh_job() -> None:
    """운영자가 Dagster UI/API에서 실행하는 consistency/dedup refresh job."""
    run_consistency_check_op(refresh_dedup_candidates_op())
    purge_expired_notices_op()
    purge_resolved_integrity_findings_op()


@job(
    name="cache_target_snapshot_gc",
    tags=CACHE_TARGET_SNAPSHOT_GC_JOB_TAGS,
    description=(
        "만료·미참조 cache-target snapshot item/header를 system round-robin batch로 "
        "정리하고 정확한 잔여 backlog와 referenced 보존 추세 alert를 기록한다."
    ),
)
def cache_target_snapshot_gc_job() -> None:
    """hourly cache-target snapshot background GC 전용 job."""
    drain_expired_cache_target_snapshots_op()


@job(
    name="current_weather_summary_refresh",
    tags=CURRENT_WEATHER_SUMMARY_REFRESH_JOB_TAGS,
    description=(
        "새 provider write 없이 weather current summary deadline을 재평가해 "
        "eligible winner와 stale projection을 원자적으로 갱신한다."
    ),
)
def current_weather_summary_refresh_job() -> None:
    """deadline-driven weather current projection reconciliation 전용 job."""
    materialize_current_weather_summary_op()


def _weather_summary_refresh_execution_fn(
    context: ScheduleEvaluationContext,
) -> RunRequest | SkipReason:
    """실행 중인 global projection이 있으면 minute tick을 합친다."""
    active_runs = context.instance.get_runs(
        filters=RunsFilter(
            job_name="current_weather_summary_refresh",
            statuses=_WEATHER_SUMMARY_ACTIVE_RUN_STATUSES,
        ),
        limit=1,
    )
    if active_runs:
        active_run = active_runs[0]
        return SkipReason(
            "current_weather_summary_refresh의 "
            f"{active_run.status.value} run({active_run.run_id})이 있어 이번 tick을 생략함"
        )
    return RunRequest(
        tags={
            **CURRENT_WEATHER_SUMMARY_REFRESH_JOB_TAGS,
            "kor_travel_map.trigger_kind": "schedule",
        }
    )


CONSISTENCY_DEDUP_REFRESH_SCHEDULES: Final = [
    ScheduleDefinition(
        name="consistency_dedup_refresh_daily_schedule",
        job=consistency_dedup_refresh_job,
        cron_schedule=cron_for_schedule(
            "consistency_dedup_refresh_daily_schedule",
            "45 5 * * *",
        ),
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags=CONSISTENCY_DEDUP_REFRESH_JOB_TAGS,
        description=(
            "dedup 후보 큐·consistency report 갱신과 notice/finding 보존 정리를 "
            "일 1회 실행한다."
        ),
    )
]
"""consistency/dedup maintenance schedule 목록. 운영 enable 전까지 STOPPED."""

CACHE_TARGET_SNAPSHOT_GC_SCHEDULES: Final = [
    ScheduleDefinition(
        name="cache_target_snapshot_gc_hourly_schedule",
        job=cache_target_snapshot_gc_job,
        cron_schedule=cron_for_schedule(
            "cache_target_snapshot_gc_hourly_schedule",
            "15 * * * *",
        ),
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.STOPPED,
        tags=CACHE_TARGET_SNAPSHOT_GC_JOB_TAGS,
        description=(
            "만료 cache-target snapshot backlog를 매시 15분에 최대 200만 item 용량으로 "
            "정리하고 referenced 보존 추세를 경보한다. 운영 enable 전까지 STOPPED."
        ),
    )
]
"""cache-target snapshot GC hourly schedule. 운영 enable 전까지 STOPPED."""

CURRENT_WEATHER_SUMMARY_REFRESH_SCHEDULES: Final = [
    ScheduleDefinition(
        name="current_weather_summary_refresh_minutely_schedule",
        job=current_weather_summary_refresh_job,
        cron_schedule=cron_for_schedule(
            "current_weather_summary_refresh_minutely_schedule",
            "* * * * *",
        ),
        execution_timezone=KST_TIMEZONE,
        default_status=DefaultScheduleStatus.RUNNING,
        tags=CURRENT_WEATHER_SUMMARY_REFRESH_JOB_TAGS,
        execution_fn=_weather_summary_refresh_execution_fn,
        description=(
            "weather summary의 next eligibility·validity·SLA deadline을 1분마다 "
            "재계산한다. projection transaction lock이 동시 실행을 직렬화한다."
        ),
    )
]
"""weather current projection deadline schedule — 운영에서 기본 실행한다."""

MAINTENANCE_JOBS: Final = [
    consistency_dedup_refresh_job,
    cache_target_snapshot_gc_job,
    current_weather_summary_refresh_job,
]
MAINTENANCE_SCHEDULES: Final = [
    *CONSISTENCY_DEDUP_REFRESH_SCHEDULES,
    *CACHE_TARGET_SNAPSHOT_GC_SCHEDULES,
    *CURRENT_WEATHER_SUMMARY_REFRESH_SCHEDULES,
]


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


def _bounded_int_config(
    value: object,
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    try:
        result = _int_config(value, default=default)
    except (TypeError, ValueError) as exc:
        raise Failure(
            description=f"{name} config가 정수가 아닙니다.",
            allow_retries=False,
        ) from exc
    if result < minimum or (maximum is not None and result > maximum):
        suffix = f"{maximum} 이하" if maximum is not None else ""
        conjunction = " " if suffix else ""
        raise Failure(
            description=(
                f"{name} config는 {minimum} 이상{conjunction}{suffix}이어야 합니다."
            ),
            allow_retries=False,
        )
    return result


def _cache_target_referenced_alert_metadata(
    result: Any,
    *,
    item_ceiling: int,
    header_ceiling: int,
    item_growth_ceiling_per_hour: int,
    header_growth_ceiling_per_hour: int,
    growth_min_interval_seconds: int,
    observation_retention_days: int,
) -> dict[str, object]:
    not_observed = "not_observed"
    current_items = result.observation_referenced_items
    current_headers = result.observation_referenced_headers
    observed_at = result.observed_at
    baseline_observed_at = result.growth_baseline_observed_at
    baseline_items = result.growth_baseline_referenced_items
    baseline_headers = result.growth_baseline_referenced_headers
    previous_observed_at = result.previous_observed_at
    previous_items = result.previous_referenced_items
    previous_headers = result.previous_referenced_headers
    observation_available = (
        current_items is not None
        and current_headers is not None
        and observed_at is not None
        and result.observation_run_id is not None
    )
    growth_elapsed_seconds: float | None = None
    growth_item_delta: int | None = None
    growth_header_delta: int | None = None
    if (
        observation_available
        and baseline_observed_at is not None
        and baseline_items is not None
        and baseline_headers is not None
    ):
        growth_elapsed_seconds = (
            observed_at - baseline_observed_at
        ).total_seconds()
        growth_item_delta = current_items - baseline_items
        growth_header_delta = current_headers - baseline_headers
    previous_elapsed_seconds: float | None = None
    item_delta: int | None = None
    header_delta: int | None = None
    if (
        observation_available
        and previous_observed_at is not None
        and previous_items is not None
        and previous_headers is not None
    ):
        previous_elapsed_seconds = (
            observed_at - previous_observed_at
        ).total_seconds()
        item_delta = current_items - previous_items
        header_delta = current_headers - previous_headers
    persisted_min_interval = (
        result.observation_growth_min_interval_seconds
        if result.observation_growth_min_interval_seconds is not None
        else growth_min_interval_seconds
    )
    growth_observed = bool(
        growth_elapsed_seconds is not None
        and result.observation_growth_baseline_eligible is True
        and (
            previous_elapsed_seconds is None
            or previous_elapsed_seconds > 0
        )
        and growth_elapsed_seconds >= persisted_min_interval
        and growth_elapsed_seconds > 0
    )
    item_growth_per_hour = (
        growth_item_delta / growth_elapsed_seconds * 3_600
        if growth_observed
        and growth_item_delta is not None
        and growth_elapsed_seconds is not None
        else None
    )
    header_growth_per_hour = (
        growth_header_delta / growth_elapsed_seconds * 3_600
        if growth_observed
        and growth_header_delta is not None
        and growth_elapsed_seconds is not None
        else None
    )
    item_ceiling_alert = bool(
        observation_available and current_items > item_ceiling
    )
    header_ceiling_alert = bool(
        observation_available and current_headers > header_ceiling
    )
    item_growth_alert = bool(
        item_growth_per_hour is not None
        and item_growth_per_hour > item_growth_ceiling_per_hour
    )
    header_growth_alert = bool(
        header_growth_per_hour is not None
        and header_growth_per_hour > header_growth_ceiling_per_hour
    )
    item_inventory_loss_alert = bool(item_delta is not None and item_delta < 0)
    header_inventory_loss_alert = bool(
        header_delta is not None and header_delta < 0
    )
    non_forward_clock = bool(
        (
            previous_elapsed_seconds is not None
            and previous_elapsed_seconds <= 0
        )
        or (
            growth_elapsed_seconds is not None
            and growth_elapsed_seconds <= 0
        )
    )
    if result.skipped:
        observation_status = "overlap_skipped"
        observation_issue_reasons = ["gc_overlap_skipped"]
    elif not observation_available:
        observation_status = "unavailable"
        observation_issue_reasons = ["referenced_observation_unavailable"]
    elif non_forward_clock:
        observation_status = "non_forward_database_clock"
        observation_issue_reasons = ["non_forward_database_clock"]
    else:
        observation_status = "observed"
        observation_issue_reasons = []
    if not observation_available:
        growth_unobserved_reason = "referenced_observation_unavailable"
    elif baseline_observed_at is None:
        growth_unobserved_reason = "first_observation"
    elif non_forward_clock:
        growth_unobserved_reason = "non_forward_database_clock"
    elif not growth_observed:
        growth_unobserved_reason = "minimum_interval_not_reached"
    else:
        growth_unobserved_reason = "observed"
    reasons = [
        reason
        for reason, active in (
            ("referenced_item_ceiling", item_ceiling_alert),
            ("referenced_header_ceiling", header_ceiling_alert),
            ("referenced_item_growth", item_growth_alert),
            ("referenced_header_growth", header_growth_alert),
            ("referenced_item_inventory_loss", item_inventory_loss_alert),
            ("referenced_header_inventory_loss", header_inventory_loss_alert),
        )
        if active
    ]
    return {
        "referenced_observation_available": observation_available,
        "referenced_observation_status": observation_status,
        "referenced_observation_issue": bool(observation_issue_reasons),
        "referenced_observation_issue_reasons": observation_issue_reasons,
        "referenced_observation_run_id": (
            result.observation_run_id if observation_available else not_observed
        ),
        "referenced_observed_at": (
            observed_at.isoformat() if observation_available else not_observed
        ),
        "referenced_observation_items": (
            current_items if observation_available else not_observed
        ),
        "referenced_observation_headers": (
            current_headers if observation_available else not_observed
        ),
        "previous_referenced_observation_run_id": (
            result.previous_observation_run_id
            if result.previous_observation_run_id is not None
            else not_observed
        ),
        "previous_referenced_observed_at": (
            previous_observed_at.isoformat()
            if previous_observed_at is not None
            else not_observed
        ),
        "previous_referenced_items": (
            previous_items if previous_items is not None else not_observed
        ),
        "previous_referenced_headers": (
            previous_headers if previous_headers is not None else not_observed
        ),
        "growth_baseline_observation_run_id": (
            result.growth_baseline_observation_run_id
            if result.growth_baseline_observation_run_id is not None
            else not_observed
        ),
        "growth_baseline_observed_at": (
            baseline_observed_at.isoformat()
            if baseline_observed_at is not None
            else not_observed
        ),
        "growth_baseline_referenced_items": (
            baseline_items if baseline_items is not None else not_observed
        ),
        "growth_baseline_referenced_headers": (
            baseline_headers if baseline_headers is not None else not_observed
        ),
        "referenced_observation_growth_baseline_eligible": (
            result.observation_growth_baseline_eligible
            if observation_available
            else not_observed
        ),
        "referenced_observation_elapsed_seconds": (
            previous_elapsed_seconds
            if previous_elapsed_seconds is not None
            else not_observed
        ),
        "referenced_items_delta": item_delta if item_delta is not None else not_observed,
        "referenced_headers_delta": (
            header_delta if header_delta is not None else not_observed
        ),
        "referenced_growth_baseline_elapsed_seconds": (
            growth_elapsed_seconds
            if growth_elapsed_seconds is not None
            else not_observed
        ),
        "referenced_items_growth_baseline_delta": (
            growth_item_delta
            if growth_item_delta is not None
            else not_observed
        ),
        "referenced_headers_growth_baseline_delta": (
            growth_header_delta
            if growth_header_delta is not None
            else not_observed
        ),
        "referenced_growth_rate_observed": growth_observed,
        "referenced_growth_unobserved_reason": growth_unobserved_reason,
        "referenced_items_growth_per_hour": (
            item_growth_per_hour
            if item_growth_per_hour is not None
            else not_observed
        ),
        "referenced_headers_growth_per_hour": (
            header_growth_per_hour
            if header_growth_per_hour is not None
            else not_observed
        ),
        "referenced_item_ceiling": item_ceiling,
        "referenced_header_ceiling": header_ceiling,
        "referenced_item_growth_ceiling_per_hour": item_growth_ceiling_per_hour,
        "referenced_header_growth_ceiling_per_hour": (
            header_growth_ceiling_per_hour
        ),
        "referenced_growth_min_interval_seconds": persisted_min_interval,
        "referenced_observation_retention_days": observation_retention_days,
        "referenced_item_ceiling_alert": item_ceiling_alert,
        "referenced_header_ceiling_alert": header_ceiling_alert,
        "referenced_retention_ceiling_alert": (
            item_ceiling_alert or header_ceiling_alert
        ),
        "referenced_item_growth_alert": item_growth_alert,
        "referenced_header_growth_alert": header_growth_alert,
        "referenced_growth_alert": item_growth_alert or header_growth_alert,
        "referenced_item_inventory_loss_alert": item_inventory_loss_alert,
        "referenced_header_inventory_loss_alert": header_inventory_loss_alert,
        "referenced_inventory_loss_alert": (
            item_inventory_loss_alert or header_inventory_loss_alert
        ),
        "referenced_alert": bool(reasons),
        "referenced_alert_reasons": reasons,
        "referenced_requires_attention": bool(reasons or observation_issue_reasons),
    }


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
