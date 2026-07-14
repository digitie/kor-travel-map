"""``/ops/datasets`` application service (#678).

DB 조회 조립·freshness 계산·orphan mutation 가드를 router에서 분리한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from kortravelmap.core import kst_now
from kortravelmap.infra import sync_state_repo
from kortravelmap.infra.dataset_status_repo import (
    DatasetIntegrityIssueCount,
    DatasetLatestExecution,
    count_open_integrity_issues_by_dataset,
    list_latest_dataset_executions,
    list_ops_import_jobs_by_ids,
)
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    list_update_requests,
)
from kortravelmap.infra.ops_repo import (
    OpsImportJob,
    OpsImportJobEvent,
    list_ops_import_job_events,
)
from kortravelmap.infra.provider_refresh_policy_repo import (
    ProviderRefreshPolicy,
    get_provider_refresh_policy,
    list_all_provider_refresh_policies,
    upsert_provider_refresh_policy,
)
from kortravelmap.infra.sync_state_repo import SyncState
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.ops_dataset_preview import (
    PREVIEW_DEFAULT_MAX_ITEMS,
    PREVIEW_MAX_ITEMS_LIMIT,
    PREVIEW_TIMEOUT_SECONDS,
)
from kortravelmap.api.ops_dataset_schedule import (
    DatasetScheduleIndex,
    DatasetScheduleState,
    load_dataset_schedule_index,
)
from kortravelmap.api.ops_dataset_schema import (
    OpsDatasetCatalogInfo,
    OpsDatasetDetailData,
    OpsDatasetEventRecord,
    OpsDatasetFreshness,
    OpsDatasetGridRow,
    OpsDatasetLatestExecution,
    OpsDatasetPreviewCapability,
    OpsDatasetRunSummary,
    OpsDatasetScheduleSummary,
    OpsDatasetScopeState,
    OpsDatasetsGridData,
    OpsIssueSummary,
)
from kortravelmap.api.provider_catalog import (
    PROVIDER_DATASET_CATALOG,
    ProviderDatasetCatalogEntry,
    find_catalog_entry,
)
from kortravelmap.api.provider_refresh_schema import (
    ProviderRefreshPolicyUpsertRequest,
    provider_refresh_policy_record,
)
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "DatasetNotFoundError",
    "OrphanMutationDisabledError",
    "load_dataset_detail",
    "load_datasets_grid",
    "upsert_dataset_refresh_policy",
]

_NEVER_RUN_STATUS = "never_run"
_RECENT_RUNS_LIMIT = 10
_RECENT_EVENTS_LIMIT = 20


class DatasetNotFoundError(LookupError):
    """카탈로그·sync state·policy 어디에도 dataset이 없음."""


class OrphanMutationDisabledError(RuntimeError):
    """카탈로그에서 제거된 잔존 row의 mutation 금지."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.mutation_disabled_reason = reason


def _preview_capability(
    entry: ProviderDatasetCatalogEntry,
) -> OpsDatasetPreviewCapability:
    supported = entry.preview == "fixture"
    return OpsDatasetPreviewCapability(
        supported=supported,
        sources=["fixture"] if supported else [],
        default_max_items=PREVIEW_DEFAULT_MAX_ITEMS,
        max_items_limit=PREVIEW_MAX_ITEMS_LIMIT,
        timeout_seconds=PREVIEW_TIMEOUT_SECONDS,
        external_call_budget=0,
    )


def _catalog_info(entry: ProviderDatasetCatalogEntry) -> OpsDatasetCatalogInfo:
    return OpsDatasetCatalogInfo(
        feature_kind=entry.feature_kind,
        default_sync_scope=entry.sync_scope,
        label=entry.label,
        is_feature_load=entry.is_feature_load,
        is_refreshable=entry.is_refreshable,
        preview=_preview_capability(entry),
    )


def _issue_summary(
    issues: DatasetIntegrityIssueCount | None,
) -> OpsIssueSummary:
    return OpsIssueSummary(
        open_count=issues.open_total if issues is not None else 0,
        severity_counts=dict(issues.by_severity) if issues is not None else {},
    )


def _freshness(
    state: SyncState | None,
    policy: ProviderRefreshPolicy | None,
    *,
    now: datetime,
) -> OpsDatasetFreshness:
    if policy is not None and not policy.enabled:
        return OpsDatasetFreshness(
            state="disabled",
            basis="disabled",
            sla_seconds=None,
            due_at=None,
            is_overdue=False,
            overdue_by_seconds=0,
        )
    if state is None or state.last_success_at is None:
        return OpsDatasetFreshness(
            state="never_run",
            basis=(
                "policy_stale_after"
                if policy is not None and policy.stale_after_minutes is not None
                else "unknown"
            ),
            sla_seconds=(
                policy.stale_after_minutes * 60
                if policy is not None and policy.stale_after_minutes is not None
                else None
            ),
            due_at=None,
            is_overdue=False,
            overdue_by_seconds=0,
        )
    if policy is None or policy.stale_after_minutes is None:
        return OpsDatasetFreshness(
            state="unknown",
            basis="unknown",
            sla_seconds=None,
            due_at=None,
            is_overdue=False,
            overdue_by_seconds=0,
        )
    sla_seconds = policy.stale_after_minutes * 60
    due_at = state.last_success_at + timedelta(seconds=sla_seconds)
    is_overdue = now >= due_at
    overdue_seconds = max(0, int((now - due_at).total_seconds()))
    return OpsDatasetFreshness(
        state="overdue" if is_overdue else "fresh",
        basis="policy_stale_after",
        sla_seconds=sla_seconds,
        due_at=due_at,
        is_overdue=is_overdue,
        overdue_by_seconds=overdue_seconds,
    )


def _schedule_summary(state: DatasetScheduleState) -> OpsDatasetScheduleSummary:
    return OpsDatasetScheduleSummary(
        basis=state.basis,
        status=state.status,
        schedule_names=list(state.schedule_names),
        active_schedule_names=list(state.active_schedule_names),
        next_scheduled_at=state.next_scheduled_at,
    )


def _latest_execution(
    item: DatasetLatestExecution | None,
) -> OpsDatasetLatestExecution | None:
    if item is None:
        return None
    return OpsDatasetLatestExecution(
        kind=item.kind,
        execution_id=item.execution_id,
        status=item.status,
        status_source=item.status_source,
        job_status=item.job_status,
        created_at=item.created_at,
        started_at=item.started_at,
        finished_at=item.finished_at,
        dagster_run_id=item.dagster_run_id,
        job_id=item.job_id,
        request_id=item.request_id,
        progress=item.progress,
        current_stage=item.current_stage,
        error_message=item.error_message,
    )


def _orphan_reason(*, has_state: bool, has_policy: bool) -> str:
    if has_state and has_policy:
        return "catalog_missing_with_sync_state_and_policy"
    if has_state:
        return "catalog_missing_with_sync_state"
    return "catalog_missing_with_policy"


def _grid_row(
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str,
    state: SyncState | None,
    entry: ProviderDatasetCatalogEntry | None,
    policy: ProviderRefreshPolicy | None,
    dataset_issues: DatasetIntegrityIssueCount | None,
    provider_issues: DatasetIntegrityIssueCount | None,
    latest_execution: DatasetLatestExecution | None,
    schedules: DatasetScheduleIndex,
    now: datetime,
) -> OpsDatasetGridRow:
    canonical = entry is not None
    return OpsDatasetGridRow(
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=state.sync_scope if state is not None else sync_scope,
        status=state.status if state is not None else _NEVER_RUN_STATUS,
        last_success_at=state.last_success_at if state is not None else None,
        last_failure_at=state.last_failure_at if state is not None else None,
        consecutive_failures=(state.consecutive_failures if state is not None else 0),
        eligible_after=state.next_run_after if state is not None else None,
        freshness=_freshness(state, policy, now=now),
        schedule=_schedule_summary(schedules.for_dataset(provider, dataset_key)),
        latest_execution=_latest_execution(latest_execution),
        catalog_state="canonical" if canonical else "orphan",
        orphan_reason=(
            None
            if canonical
            else _orphan_reason(has_state=state is not None, has_policy=policy is not None)
        ),
        mutable=canonical,
        catalog=_catalog_info(entry) if entry is not None else None,
        refresh_policy=(
            provider_refresh_policy_record(policy) if policy is not None else None
        ),
        dataset_issues=_issue_summary(dataset_issues),
        provider_issues=_issue_summary(provider_issues),
    )


async def load_datasets_grid(
    session: AsyncSession,
    *,
    settings: ApiSettings,
    dagster_client: httpx.AsyncClient,
    now: datetime | None = None,
) -> OpsDatasetsGridData:
    """3원 grid를 batch query들로 조립한다. 행별 detail 조회는 하지 않는다."""
    states = await sync_state_repo.list_all_sync_states(session)
    policies = await list_all_provider_refresh_policies(session)
    issue_counts = await count_open_integrity_issues_by_dataset(session)
    latest_executions = await list_latest_dataset_executions(session)
    schedules = await load_dataset_schedule_index(
        settings=settings,
        client=dagster_client,
    )
    reference = now or kst_now()

    states_by_key: dict[tuple[str, str], list[SyncState]] = {}
    for state in states:
        states_by_key.setdefault((state.provider, state.dataset_key), []).append(state)
    policies_by_key = {
        (policy.provider, policy.dataset_key): policy for policy in policies
    }
    dataset_issues_by_key = {
        (item.provider, item.dataset_key): item
        for item in issue_counts
        if item.dataset_key is not None
    }
    provider_issues_by_key = {
        item.provider: item for item in issue_counts if item.dataset_key is None
    }
    latest_by_key = {
        (item.provider, item.dataset_key): item for item in latest_executions
    }

    rows: list[OpsDatasetGridRow] = []
    for entry in PROVIDER_DATASET_CATALOG:
        key = (entry.provider, entry.dataset_key)
        entry_states = states_by_key.pop(key, [])
        policy = policies_by_key.pop(key, None)
        if not entry_states:
            entry_states_or_none: list[SyncState | None] = [None]
        else:
            entry_states_or_none = list(entry_states)
        for entry_state in entry_states_or_none:
            rows.append(
                _grid_row(
                    provider=entry.provider,
                    dataset_key=entry.dataset_key,
                    sync_scope=entry.sync_scope,
                    state=entry_state,
                    entry=entry,
                    policy=policy,
                    dataset_issues=dataset_issues_by_key.get(key),
                    provider_issues=provider_issues_by_key.get(entry.provider),
                    latest_execution=latest_by_key.get(key),
                    schedules=schedules,
                    now=reference,
                )
            )

    for (provider, dataset_key), orphan_states in states_by_key.items():
        key = (provider, dataset_key)
        policy = policies_by_key.pop(key, None)
        for state in orphan_states:
            rows.append(
                _grid_row(
                    provider=provider,
                    dataset_key=dataset_key,
                    sync_scope=state.sync_scope,
                    state=state,
                    entry=None,
                    policy=policy,
                    dataset_issues=dataset_issues_by_key.get(key),
                    provider_issues=provider_issues_by_key.get(provider),
                    latest_execution=latest_by_key.get(key),
                    schedules=schedules,
                    now=reference,
                )
            )

    for (provider, dataset_key), policy in policies_by_key.items():
        key = (provider, dataset_key)
        rows.append(
            _grid_row(
                provider=provider,
                dataset_key=dataset_key,
                sync_scope="default",
                state=None,
                entry=None,
                policy=policy,
                dataset_issues=dataset_issues_by_key.get(key),
                provider_issues=provider_issues_by_key.get(provider),
                latest_execution=latest_by_key.get(key),
                schedules=schedules,
                now=reference,
            )
        )

    rows.sort(key=lambda row: (row.provider, row.dataset_key, row.sync_scope))
    return OpsDatasetsGridData(
        items=rows,
        schedule_source_status=schedules.source_status,
        schedule_source_errors=list(schedules.errors),
    )


def _scope_state(
    state: SyncState,
    policy: ProviderRefreshPolicy | None,
    *,
    now: datetime,
) -> OpsDatasetScopeState:
    return OpsDatasetScopeState(
        sync_scope=state.sync_scope,
        status=state.status,
        cursor=state.cursor,
        last_success_at=state.last_success_at,
        last_failure_at=state.last_failure_at,
        consecutive_failures=state.consecutive_failures,
        eligible_after=state.next_run_after,
        freshness=_freshness(state, policy, now=now),
    )


def _run_summary(
    update_request: FeatureUpdateRequest,
    job: OpsImportJob | None,
) -> OpsDatasetRunSummary:
    return OpsDatasetRunSummary(
        request_id=update_request.request_id,
        status=update_request.status,
        run_mode=update_request.run_mode,
        scope_type=update_request.scope_type,
        dry_run=update_request.dry_run,
        priority=update_request.priority,
        job_id=update_request.job_id,
        dagster_run_id=(
            update_request.dagster_run_id
            or (job.dagster_run_id if job is not None else None)
        ),
        job_status=job.status if job is not None else None,
        job_progress=job.progress if job is not None else None,
        job_current_stage=job.current_stage if job is not None else None,
        operator=update_request.operator,
        reason=update_request.reason,
        error_message=(
            update_request.error_message
            or (job.error_message if job is not None else None)
        ),
        created_at=update_request.created_at,
        started_at=update_request.started_at,
        finished_at=update_request.finished_at,
        updated_at=update_request.updated_at,
    )


def _event_record(event: OpsImportJobEvent) -> OpsDatasetEventRecord:
    return OpsDatasetEventRecord(
        event_id=event.event_id,
        job_id=event.job_id,
        stage=event.stage,
        level=event.level,
        code=event.code,
        message=event.message,
        occurred_at=event.occurred_at,
    )


async def load_dataset_detail(
    session: AsyncSession,
    *,
    settings: ApiSettings,
    dagster_client: httpx.AsyncClient,
    provider: str,
    dataset_key: str,
    now: datetime | None = None,
) -> OpsDatasetDetailData:
    reference = now or kst_now()
    entry = find_catalog_entry(provider, dataset_key)
    states = await sync_state_repo.list_sync_states(
        session, provider=provider, dataset_key=dataset_key
    )
    policy = await get_provider_refresh_policy(
        session, provider=provider, dataset_key=dataset_key
    )
    if entry is None and not states and policy is None:
        raise DatasetNotFoundError(f"ops dataset 없음: {provider!r}/{dataset_key!r}")

    scopes = [_scope_state(state, policy, now=reference) for state in states]
    if not scopes:
        sync_scope = entry.sync_scope if entry is not None else "default"
        scopes = [
            OpsDatasetScopeState(
                sync_scope=sync_scope,
                status=_NEVER_RUN_STATUS,
                cursor={},
                last_success_at=None,
                last_failure_at=None,
                consecutive_failures=0,
                eligible_after=None,
                freshness=_freshness(None, policy, now=reference),
            )
        ]

    requests_page = await list_update_requests(
        session,
        provider=provider,
        dataset_key=dataset_key,
        limit=_RECENT_RUNS_LIMIT,
    )
    jobs = await list_ops_import_jobs_by_ids(
        session,
        [item.job_id for item in requests_page.items if item.job_id],
    )
    jobs_by_id = {job.job_id: job for job in jobs}
    events_page = await list_ops_import_job_events(
        session,
        provider=provider,
        dataset_key=dataset_key,
        limit=_RECENT_EVENTS_LIMIT,
    )
    issue_counts = await count_open_integrity_issues_by_dataset(
        session, provider=provider, dataset_key=dataset_key
    )
    dataset_issues = next(
        (item for item in issue_counts if item.dataset_key == dataset_key), None
    )
    provider_issues = next(
        (item for item in issue_counts if item.dataset_key is None), None
    )
    schedules = await load_dataset_schedule_index(
        settings=settings,
        client=dagster_client,
    )
    canonical = entry is not None
    orphan_reason = (
        None
        if canonical
        else _orphan_reason(has_state=bool(states), has_policy=policy is not None)
    )
    return OpsDatasetDetailData(
        provider=provider,
        dataset_key=dataset_key,
        catalog_state="canonical" if canonical else "orphan",
        orphan_reason=orphan_reason,
        mutable=canonical,
        catalog=_catalog_info(entry) if entry is not None else None,
        scopes=scopes,
        schedule=_schedule_summary(schedules.for_dataset(provider, dataset_key)),
        schedule_source_status=schedules.source_status,
        schedule_source_errors=list(schedules.errors),
        refresh_policy=(
            provider_refresh_policy_record(policy) if policy is not None else None
        ),
        recent_runs=[
            _run_summary(
                item,
                jobs_by_id.get(item.job_id) if item.job_id is not None else None,
            )
            for item in requests_page.items
        ],
        recent_events=[_event_record(item) for item in events_page.items],
        dataset_issues=_issue_summary(dataset_issues),
        provider_issues=_issue_summary(provider_issues),
    )


async def upsert_dataset_refresh_policy(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    body: ProviderRefreshPolicyUpsertRequest,
) -> ProviderRefreshPolicy:
    """canonical catalog dataset만 정책 mutation을 허용한다."""
    async with session.begin():
        if find_catalog_entry(provider, dataset_key) is None:
            states = await sync_state_repo.list_sync_states(
                session, provider=provider, dataset_key=dataset_key
            )
            existing = await get_provider_refresh_policy(
                session, provider=provider, dataset_key=dataset_key
            )
            if states or existing is not None:
                reason = _orphan_reason(
                    has_state=bool(states), has_policy=existing is not None
                )
                raise OrphanMutationDisabledError(reason)
            raise DatasetNotFoundError(
                f"ops dataset 없음: {provider!r}/{dataset_key!r}"
            )
        return await upsert_provider_refresh_policy(
            session,
            provider=provider,
            dataset_key=dataset_key,
            source_kind=body.source_kind,
            targeted_policy=body.targeted_policy,
            system_interval_seconds=body.system_interval_seconds,
            optimal_interval_seconds=body.optimal_interval_seconds,
            min_interval_seconds=body.min_interval_seconds,
            max_requests_per_minute=body.max_requests_per_minute,
            max_requests_per_hour=body.max_requests_per_hour,
            max_requests_per_day=body.max_requests_per_day,
            max_concurrent=body.max_concurrent,
            burst_size=body.burst_size,
            rate_limit_source=body.rate_limit_source,
            config_source=body.config_source,
            enabled=body.enabled,
            stale_after_minutes=body.stale_after_minutes,
        )
