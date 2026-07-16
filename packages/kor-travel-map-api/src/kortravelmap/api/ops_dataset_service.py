"""``/ops/datasets`` application service (#678).

DB 조회 조립·freshness 계산·orphan mutation 가드를 router에서 분리한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import overload
from urllib.parse import quote, urlencode

import httpx
from kortravelmap.core import kst_now
from kortravelmap.infra import sync_state_repo
from kortravelmap.infra.dataset_status_repo import (
    DatasetIntegrityIssueCount,
    DatasetLatestExecution,
    count_open_integrity_issues_by_dataset,
    list_latest_dataset_executions,
)
from kortravelmap.infra.ops_repo import (
    OpsImportJobEvent,
    list_ops_import_job_events,
)
from kortravelmap.infra.pipeline_repo import list_pipeline_executions
from kortravelmap.infra.poi_cache_target_repo import (
    list_active_poi_cache_target_external_systems,
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
    OpsDatasetProjectedJob,
    OpsDatasetProviderDataset,
    OpsDatasetScheduleSummary,
    OpsDatasetScopeRefreshCapability,
    OpsDatasetScopeState,
    OpsDatasetsGridData,
    OpsIssueSummary,
)
from kortravelmap.api.pipeline_cancellation_schema import cancellation_summary_record
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


def _dataset_detail_url(provider: str, dataset_key: str) -> str:
    return (
        "/v1/ops/datasets/detail?"
        + urlencode(
            {"provider": provider, "dataset_key": dataset_key},
            quote_via=quote,
        )
    )


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


def _scope_refresh_capability(
    entry: ProviderDatasetCatalogEntry,
    *,
    active_external_systems: tuple[str, ...],
) -> OpsDatasetScopeRefreshCapability:
    if not entry.is_refreshable:
        return OpsDatasetScopeRefreshCapability(
            supported=False,
            selector="none",
            effect="dataset_wide",
            default_sync_scope="dataset_wide",
            allowed_sync_scopes=[],
            reason="이 dataset에는 실행 가능한 refresh runner가 없습니다.",
        )
    if entry.scope_refresh_selector == "none":
        return OpsDatasetScopeRefreshCapability(
            supported=False,
            selector="none",
            effect="dataset_wide",
            default_sync_scope="dataset_wide",
            allowed_sync_scopes=[],
            reason="이 dataset은 전체 dataset 단위로만 갱신합니다.",
        )
    allowed = ["target_grids"]
    allowed.extend(f"external_system:{name}" for name in active_external_systems)
    return OpsDatasetScopeRefreshCapability(
        supported=True,
        selector="poi_cache_targets",
        effect="sync_scope",
        default_sync_scope="target_grids",
        allowed_sync_scopes=allowed,
        reason=None,
    )


def _catalog_state_sync_scopes(
    entry: ProviderDatasetCatalogEntry,
    *,
    active_external_systems: tuple[str, ...],
) -> tuple[str, ...]:
    scopes = [entry.sync_scope]
    if entry.scope_refresh_selector == "poi_cache_targets":
        scopes.extend(
            f"external_system:{name}" for name in active_external_systems
        )
    return tuple(dict.fromkeys(scopes))


def _catalog_info(
    entry: ProviderDatasetCatalogEntry,
    *,
    active_external_systems: tuple[str, ...],
) -> OpsDatasetCatalogInfo:
    return OpsDatasetCatalogInfo(
        feature_kind=entry.feature_kind,
        provider_state_default_scope=entry.sync_scope,
        label=entry.label,
        is_feature_load=entry.is_feature_load,
        is_refreshable=entry.is_refreshable,
        scope_refresh=_scope_refresh_capability(
            entry,
            active_external_systems=active_external_systems,
        ),
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


@overload
def _latest_execution(item: None) -> None:
    ...


@overload
def _latest_execution(item: DatasetLatestExecution) -> OpsDatasetLatestExecution:
    ...


def _latest_execution(
    item: DatasetLatestExecution | None,
) -> OpsDatasetLatestExecution | None:
    if item is None:
        return None
    root = item.execution
    projected = root.projected_job
    return OpsDatasetLatestExecution(
        kind=root.kind,
        id=root.id,
        detail_url=f"/v1/ops/pipeline/executions/{root.kind}/{root.id}",
        status=root.status,
        pair_status=item.pair_status,
        operation_member_id=item.operation_member_id,
        sync_scope=item.sync_scope,
        providers=list(root.providers),
        dataset_keys=list(root.dataset_keys),
        provider_datasets=[
            OpsDatasetProviderDataset(
                provider=pair.provider,
                dataset_key=pair.dataset_key,
                sync_scope=pair.sync_scope,
                operation_member_id=pair.operation_member_id,
                status=pair.status,
            )
            for pair in root.provider_datasets
        ],
        created_at=root.created_at,
        started_at=root.started_at,
        finished_at=root.finished_at,
        dagster_run_id=root.dagster_run_id,
        dagster_run_status=root.dagster_run_status,
        trigger_kind=root.trigger_kind,
        operation_registry_version=root.operation_registry_version,
        error_message=root.error_message,
        projected_job=OpsDatasetProjectedJob(
            id=projected.id,
            job_kind=projected.job_kind,
            status=projected.status,
            progress=projected.progress,
            current_stage=projected.current_stage,
            error_message=projected.error_message,
            created_at=projected.created_at,
            started_at=projected.started_at,
            finished_at=projected.finished_at,
            dagster_run_id=projected.dagster_run_id,
            dagster_run_status=projected.dagster_run_status,
            trigger_kind=projected.trigger_kind,
            operation_registry_version=projected.operation_registry_version,
            depth=projected.depth,
            detail_url=f"/v1/ops/pipeline/executions/import_job/{projected.id}",
        ),
        cancellation=cancellation_summary_record(root.cancellation),
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
    active_external_systems: tuple[str, ...],
    now: datetime,
) -> OpsDatasetGridRow:
    canonical = entry is not None
    return OpsDatasetGridRow(
        provider=provider,
        dataset_key=dataset_key,
        detail_url=_dataset_detail_url(provider, dataset_key),
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
        catalog=(
            _catalog_info(
                entry,
                active_external_systems=active_external_systems,
            )
            if entry is not None
            else None
        ),
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
    active_external_systems = tuple(
        await list_active_poi_cache_target_external_systems(session)
    )
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
        (item.provider, item.dataset_key, item.sync_scope): item
        for item in latest_executions
    }

    def latest_for(
        *,
        provider: str,
        dataset_key: str,
        sync_scope: str,
        allow_unscoped: bool,
    ) -> DatasetLatestExecution | None:
        exact = latest_by_key.get((provider, dataset_key, sync_scope))
        if not allow_unscoped:
            return exact
        candidates = tuple(
            item
            for item in (exact, latest_by_key.get((provider, dataset_key, None)))
            if item is not None
        )
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item.execution.created_at,
                item.execution.id,
                item.execution.kind,
            ),
        )

    rows: list[OpsDatasetGridRow] = []
    for entry in PROVIDER_DATASET_CATALOG:
        key = (entry.provider, entry.dataset_key)
        entry_states = states_by_key.pop(key, [])
        policy = policies_by_key.pop(key, None)
        states_by_scope = {state.sync_scope: state for state in entry_states}
        expected_scopes = _catalog_state_sync_scopes(
            entry,
            active_external_systems=active_external_systems,
        )
        stale_scopes = tuple(
            state.sync_scope
            for state in entry_states
            if state.sync_scope not in expected_scopes
        )
        row_scopes = (*expected_scopes, *stale_scopes)
        for row_sync_scope in row_scopes:
            entry_state = states_by_scope.get(row_sync_scope)
            rows.append(
                _grid_row(
                    provider=entry.provider,
                    dataset_key=entry.dataset_key,
                    sync_scope=row_sync_scope,
                    state=entry_state,
                    entry=entry,
                    policy=policy,
                    dataset_issues=dataset_issues_by_key.get(key),
                    provider_issues=provider_issues_by_key.get(entry.provider),
                    latest_execution=latest_for(
                        provider=entry.provider,
                        dataset_key=entry.dataset_key,
                        sync_scope=(
                            row_sync_scope
                            if entry.scope_refresh_selector == "poi_cache_targets"
                            else "dataset_wide"
                        ),
                        allow_unscoped=entry.scope_refresh_selector == "none",
                    ),
                    schedules=schedules,
                    active_external_systems=active_external_systems,
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
                    latest_execution=latest_for(
                        provider=provider,
                        dataset_key=dataset_key,
                        sync_scope=state.sync_scope,
                        allow_unscoped=False,
                    ),
                    schedules=schedules,
                    active_external_systems=active_external_systems,
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
                latest_execution=latest_for(
                    provider=provider,
                    dataset_key=dataset_key,
                    sync_scope="default",
                    allow_unscoped=False,
                ),
                schedules=schedules,
                active_external_systems=active_external_systems,
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

    active_external_systems = tuple(
        await list_active_poi_cache_target_external_systems(session)
    )
    states_by_scope = {state.sync_scope: state for state in states}
    if entry is not None:
        expected_scopes = _catalog_state_sync_scopes(
            entry,
            active_external_systems=active_external_systems,
        )
        stale_scopes = tuple(
            state.sync_scope
            for state in states
            if state.sync_scope not in expected_scopes
        )
        detail_scopes = (*expected_scopes, *stale_scopes)
    else:
        detail_scopes = tuple(state.sync_scope for state in states) or ("default",)
    scopes = [
        (
            _scope_state(state, policy, now=reference)
            if (state := states_by_scope.get(sync_scope)) is not None
            else OpsDatasetScopeState(
                sync_scope=sync_scope,
                status=_NEVER_RUN_STATUS,
                cursor={},
                last_success_at=None,
                last_failure_at=None,
                consecutive_failures=0,
                eligible_after=None,
                freshness=_freshness(None, policy, now=reference),
            )
        )
        for sync_scope in detail_scopes
    ]

    executions_page = await list_pipeline_executions(
        session,
        provider=provider,
        dataset_key=dataset_key,
        limit=_RECENT_RUNS_LIMIT,
    )
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
        catalog=(
            _catalog_info(
                entry,
                active_external_systems=active_external_systems,
            )
            if entry is not None
            else None
        ),
        scopes=scopes,
        schedule=_schedule_summary(schedules.for_dataset(provider, dataset_key)),
        schedule_source_status=schedules.source_status,
        schedule_source_errors=list(schedules.errors),
        refresh_policy=(
            provider_refresh_policy_record(policy) if policy is not None else None
        ),
        recent_runs=[
            _latest_execution(
                DatasetLatestExecution(
                    provider=provider,
                    dataset_key=dataset_key,
                    sync_scope=pair.sync_scope,
                    execution=item,
                    operation_member_id=pair.operation_member_id,
                    pair_status=pair.status,
                )
            )
            for item in executions_page.items
            for pair in item.provider_datasets
            if pair.provider == provider and pair.dataset_key == dataset_key
        ],
        recent_runs_next_cursor=executions_page.next_cursor,
        pipeline_history_url=(
            "/v1/ops/pipeline/executions?"
            + urlencode(
                {
                    "provider": provider,
                    "dataset_key": dataset_key,
                },
                quote_via=quote,
            )
        ),
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
