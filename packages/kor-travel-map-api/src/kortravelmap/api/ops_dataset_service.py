"""``/ops/datasets`` application service (#678).

DB 조회 조립·freshness 계산·orphan mutation 가드를 router에서 분리한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import overload
from urllib.parse import quote, urlencode

import httpx
from kortravelmap.core import kst_now
from kortravelmap.core.sync_scope import (
    DATASET_WIDE_SYNC_SCOPE,
    parse_canonical_sync_scope,
)
from kortravelmap.infra import sync_state_repo
from kortravelmap.infra.dataset_status_repo import (
    DatasetExecutionSnapshot,
    DatasetIntegrityIssueCount,
    DatasetLatestExecution,
    count_open_integrity_issues_by_dataset,
    list_dataset_execution_snapshots,
    list_dataset_execution_snapshots_scoped,
)
from kortravelmap.infra.ops_repo import (
    OpsImportJobEvent,
    list_ops_import_job_events,
)
from kortravelmap.infra.pipeline_repo import PipelineExecution, list_pipeline_executions
from kortravelmap.infra.poi_cache_target_repo import (
    list_active_poi_cache_target_external_systems,
)
from kortravelmap.infra.provider_refresh_policy_repo import (
    ProviderRefreshPolicy,
    ProviderRefreshPolicyRevisionConflict,
    ProviderRefreshPolicyRevisionExhausted,
    ProviderRefreshPolicySourceKindImmutable,
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
    OpsDatasetEventHistory,
    OpsDatasetEventRecord,
    OpsDatasetExecution,
    OpsDatasetFreshness,
    OpsDatasetGridRow,
    OpsDatasetPreviewCapability,
    OpsDatasetProjectedJob,
    OpsDatasetProviderDataset,
    OpsDatasetRunHistory,
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
    resolve_dataset_history_sync_scopes,
)
from kortravelmap.api.provider_refresh_schema import (
    ProviderRefreshPolicyUpsertRequest,
    provider_refresh_policy_record,
)
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "DatasetNotFoundError",
    "OrphanMutationDisabledError",
    "ProviderRefreshPolicyRevisionConflict",
    "ProviderRefreshPolicyRevisionExhausted",
    "ProviderRefreshPolicySourceKindImmutable",
    "load_dataset_detail",
    "load_datasets_grid",
    "upsert_dataset_refresh_policy",
]

_NEVER_RUN_STATUS = "never_run"
_RECENT_RUNS_LIMIT = 10
_RECENT_EVENTS_LIMIT = 20


def _dataset_detail_url(provider: str, dataset_key: str, sync_scope: str) -> str:
    return (
        "/v1/ops/datasets/detail?"
        + urlencode(
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": sync_scope,
            },
            quote_via=quote,
        )
    )


def _event_history_url(
    provider: str,
    dataset_key: str,
    effective_sync_scope: str,
) -> str:
    return (
        "/v1/ops/pipeline/events?"
        + urlencode(
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": effective_sync_scope,
            },
            quote_via=quote,
        )
    )


def _run_history_url(
    provider: str,
    dataset_key: str,
    logical_sync_scope: str,
) -> str:
    return (
        "/v1/ops/pipeline/executions?"
        + urlencode(
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "sync_scope": logical_sync_scope,
            },
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
    scopes = [
        (
            DATASET_WIDE_SYNC_SCOPE
            if entry.scope_refresh_selector == "none"
            else entry.sync_scope
        )
    ]
    if entry.scope_refresh_selector == "poi_cache_targets":
        scopes.extend(
            f"external_system:{name}" for name in active_external_systems
        )
    return tuple(dict.fromkeys(scopes))


def _logical_state_scope(
    entry: ProviderDatasetCatalogEntry | None,
    state_scope: str,
) -> str:
    """내부 state namespace를 외부 canonical sync scope로 투영한다."""
    if state_scope == "default" and (
        entry is None or entry.scope_refresh_selector == "none"
    ):
        return DATASET_WIDE_SYNC_SCOPE
    return state_scope


def _api_state_scope(
    entry: ProviderDatasetCatalogEntry | None,
    state_scope: str,
) -> str | None:
    """내부 namespace를 변환하고 API에서 표현할 수 없는 legacy scope는 숨긴다."""
    logical_scope = _logical_state_scope(entry, state_scope)
    try:
        return parse_canonical_sync_scope(logical_scope).value
    except ValueError:
        return None


def _states_by_api_scope(
    entry: ProviderDatasetCatalogEntry | None,
    states: Sequence[SyncState],
) -> dict[str, SyncState]:
    """raw state alias를 logical API resource 하나로 deterministic하게 접는다."""
    selected: dict[str, SyncState] = {}
    for state in states:
        logical_scope = _api_state_scope(entry, state.sync_scope)
        if logical_scope is None:
            continue
        current = selected.get(logical_scope)
        if current is None or (
            current.sync_scope != logical_scope
            and state.sync_scope == logical_scope
        ):
            selected[logical_scope] = state
    return selected


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
def _execution_record(item: None) -> None:
    ...


@overload
def _execution_record(item: DatasetLatestExecution) -> OpsDatasetExecution:
    ...


def _execution_record(
    item: DatasetLatestExecution | None,
) -> OpsDatasetExecution | None:
    if item is None:
        return None
    root = item.execution
    projected = root.projected_job
    return OpsDatasetExecution(
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


def _dataset_execution_projection(
    snapshots: tuple[DatasetExecutionSnapshot, ...],
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str,
) -> tuple[DatasetLatestExecution | None, DatasetLatestExecution | None]:
    """logical scope의 terminal 최신값과 active 최신값을 같은 snapshot에서 고른다."""
    storage_scopes: tuple[str | None, ...] = (sync_scope,)
    if sync_scope == DATASET_WIDE_SYNC_SCOPE:
        storage_scopes = (DATASET_WIDE_SYNC_SCOPE, None)
    candidates = tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.provider == provider
        and snapshot.dataset_key == dataset_key
        and snapshot.sync_scope in storage_scopes
    )

    def latest(
        selections: tuple[DatasetLatestExecution | None, ...],
    ) -> DatasetLatestExecution | None:
        present = tuple(selection for selection in selections if selection is not None)
        if not present:
            return None
        return max(
            present,
            key=lambda item: (
                item.execution.created_at,
                item.execution.id,
                item.execution.kind,
            ),
        )

    return (
        latest(tuple(snapshot.latest_terminal for snapshot in candidates)),
        latest(tuple(snapshot.active for snapshot in candidates)),
    )


def _run_history_records(
    executions: tuple[PipelineExecution, ...],
    *,
    provider: str,
    dataset_key: str,
    sync_scopes: tuple[str | None, ...],
) -> list[OpsDatasetExecution]:
    """canonical root마다 논리 scope pair 하나만 골라 중복 없는 이력을 만든다."""
    records: list[OpsDatasetExecution] = []
    for execution in executions:
        pairs = tuple(
            pair
            for pair in execution.provider_datasets
            if pair.provider == provider
            and pair.dataset_key == dataset_key
            and pair.sync_scope in sync_scopes
        )
        if not pairs:
            continue
        pair = max(
            pairs,
            key=lambda item: (
                item.sync_scope == DATASET_WIDE_SYNC_SCOPE,
                item.sync_scope is not None,
                item.operation_member_id,
            ),
        )
        records.append(
            _execution_record(
                DatasetLatestExecution(
                    provider=provider,
                    dataset_key=dataset_key,
                    sync_scope=pair.sync_scope,
                    execution=execution,
                    operation_member_id=pair.operation_member_id,
                    pair_status=pair.status,
                )
            )
        )
    return records


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
    has_persisted_state: bool,
    entry: ProviderDatasetCatalogEntry | None,
    policy: ProviderRefreshPolicy | None,
    dataset_issues: DatasetIntegrityIssueCount | None,
    provider_issues: DatasetIntegrityIssueCount | None,
    latest_execution: DatasetLatestExecution | None,
    active_execution: DatasetLatestExecution | None,
    schedules: DatasetScheduleIndex,
    active_external_systems: tuple[str, ...],
    now: datetime,
) -> OpsDatasetGridRow:
    canonical = entry is not None
    return OpsDatasetGridRow(
        provider=provider,
        dataset_key=dataset_key,
        detail_url=_dataset_detail_url(provider, dataset_key, sync_scope),
        sync_scope=sync_scope,
        status=state.status if state is not None else _NEVER_RUN_STATUS,
        last_success_at=state.last_success_at if state is not None else None,
        last_failure_at=state.last_failure_at if state is not None else None,
        consecutive_failures=(state.consecutive_failures if state is not None else 0),
        eligible_after=state.next_run_after if state is not None else None,
        freshness=_freshness(state, policy, now=now),
        schedule=_schedule_summary(schedules.for_dataset(provider, dataset_key)),
        latest_execution=_execution_record(latest_execution),
        active_execution=_execution_record(active_execution),
        catalog_state="canonical" if canonical else "orphan",
        orphan_reason=(
            None
            if canonical
            else _orphan_reason(
                has_state=has_persisted_state,
                has_policy=policy is not None,
            )
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
    execution_snapshots = await list_dataset_execution_snapshots(session)
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
    rows: list[OpsDatasetGridRow] = []
    for entry in PROVIDER_DATASET_CATALOG:
        key = (entry.provider, entry.dataset_key)
        entry_states = states_by_key.pop(key, [])
        policy = policies_by_key.pop(key, None)
        states_by_scope = _states_by_api_scope(entry, entry_states)
        expected_scopes = _catalog_state_sync_scopes(
            entry,
            active_external_systems=active_external_systems,
        )
        stale_scopes = tuple(
            dict.fromkeys(
                logical_scope
                for state in entry_states
                if (logical_scope := _api_state_scope(entry, state.sync_scope))
                is not None
                and logical_scope not in expected_scopes
            )
        )
        row_scopes = tuple(dict.fromkeys((*expected_scopes, *stale_scopes)))
        for row_sync_scope in row_scopes:
            entry_state = states_by_scope.get(row_sync_scope)
            latest_execution, active_execution = _dataset_execution_projection(
                execution_snapshots,
                provider=entry.provider,
                dataset_key=entry.dataset_key,
                sync_scope=row_sync_scope,
            )
            rows.append(
                _grid_row(
                    provider=entry.provider,
                    dataset_key=entry.dataset_key,
                    sync_scope=row_sync_scope,
                    state=entry_state,
                    has_persisted_state=entry_state is not None,
                    entry=entry,
                    policy=policy,
                    dataset_issues=dataset_issues_by_key.get(key),
                    provider_issues=provider_issues_by_key.get(entry.provider),
                    latest_execution=latest_execution,
                    active_execution=active_execution,
                    schedules=schedules,
                    active_external_systems=active_external_systems,
                    now=reference,
                )
            )

    for (provider, dataset_key), orphan_states in states_by_key.items():
        key = (provider, dataset_key)
        policy = policies_by_key.pop(key, None)
        orphan_states_by_scope = _states_by_api_scope(None, orphan_states)
        for logical_scope, state in orphan_states_by_scope.items():
            latest_execution, active_execution = _dataset_execution_projection(
                execution_snapshots,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=logical_scope,
            )
            rows.append(
                _grid_row(
                    provider=provider,
                    dataset_key=dataset_key,
                    sync_scope=logical_scope,
                    state=state,
                    has_persisted_state=True,
                    entry=None,
                    policy=policy,
                    dataset_issues=dataset_issues_by_key.get(key),
                    provider_issues=provider_issues_by_key.get(provider),
                    latest_execution=latest_execution,
                    active_execution=active_execution,
                    schedules=schedules,
                    active_external_systems=active_external_systems,
                    now=reference,
                )
            )
        if orphan_states_by_scope:
            continue
        logical_scope = DATASET_WIDE_SYNC_SCOPE
        latest_execution, active_execution = _dataset_execution_projection(
            execution_snapshots,
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=logical_scope,
        )
        rows.append(
            _grid_row(
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=logical_scope,
                state=None,
                has_persisted_state=True,
                entry=None,
                policy=policy,
                dataset_issues=dataset_issues_by_key.get(key),
                provider_issues=provider_issues_by_key.get(provider),
                latest_execution=latest_execution,
                active_execution=active_execution,
                schedules=schedules,
                active_external_systems=active_external_systems,
                now=reference,
            )
        )

    for (provider, dataset_key), policy in policies_by_key.items():
        key = (provider, dataset_key)
        latest_execution, active_execution = _dataset_execution_projection(
            execution_snapshots,
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=DATASET_WIDE_SYNC_SCOPE,
        )
        rows.append(
            _grid_row(
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=DATASET_WIDE_SYNC_SCOPE,
                state=None,
                has_persisted_state=False,
                entry=None,
                policy=policy,
                dataset_issues=dataset_issues_by_key.get(key),
                provider_issues=provider_issues_by_key.get(provider),
                latest_execution=latest_execution,
                active_execution=active_execution,
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
        execution_coverage="db_recorded_canonical_operations",
    )


def _scope_state(
    state: SyncState,
    policy: ProviderRefreshPolicy | None,
    *,
    sync_scope: str,
    now: datetime,
) -> OpsDatasetScopeState:
    return OpsDatasetScopeState(
        sync_scope=sync_scope,
        status=state.status,
        cursor=state.cursor,
        last_success_at=state.last_success_at,
        last_failure_at=state.last_failure_at,
        consecutive_failures=state.consecutive_failures,
        eligible_after=state.next_run_after,
        freshness=_freshness(state, policy, now=now),
    )


def _event_record(event: OpsImportJobEvent) -> OpsDatasetEventRecord:
    if event.sync_scope is None:
        raise AssertionError("dataset canonical event must have an effective sync_scope")
    return OpsDatasetEventRecord(
        event_id=event.event_id,
        job_id=event.job_id,
        sync_scope=event.sync_scope,
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
    sync_scope: str,
    now: datetime | None = None,
) -> OpsDatasetDetailData:
    canonical_scope = parse_canonical_sync_scope(sync_scope).value
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
    states_by_scope = _states_by_api_scope(entry, states)
    if entry is not None:
        expected_scopes = _catalog_state_sync_scopes(
            entry,
            active_external_systems=active_external_systems,
        )
        stale_scopes = tuple(
            dict.fromkeys(
                logical_scope
                for state in states
                if (logical_scope := _api_state_scope(entry, state.sync_scope))
                is not None
                and logical_scope not in expected_scopes
            )
        )
        detail_scopes = tuple(dict.fromkeys((*expected_scopes, *stale_scopes)))
    else:
        detail_scopes = tuple(
            dict.fromkeys(
                logical_scope
                for state in states
                if (logical_scope := _api_state_scope(None, state.sync_scope))
                is not None
            )
        ) or (DATASET_WIDE_SYNC_SCOPE,)
    if canonical_scope not in detail_scopes:
        raise DatasetNotFoundError(
            "ops dataset scope 없음: "
            f"{provider!r}/{dataset_key!r}/{canonical_scope!r}"
        )
    scopes = [
        (
            _scope_state(
                state,
                policy,
                sync_scope=sync_scope,
                now=reference,
            )
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

    history_sync_scopes = resolve_dataset_history_sync_scopes(
        provider,
        dataset_key,
        canonical_scope,
    )
    event_sync_scope = (
        DATASET_WIDE_SYNC_SCOPE
        if DATASET_WIDE_SYNC_SCOPE in history_sync_scopes
        else canonical_scope
    )
    # detail은 단일 (provider, dataset_key)만 투영하므로 snapshot·run-history 모두
    # dataset-scoped 경로를 쓴다. unscoped 버전은 전체 파이프라인 히스토리에 대해
    # roots_with_identity의 per-root 상관 서브쿼리를 계산해 누적 이력에 비례하는
    # O(roots^2) 비용을 내고 detail 응답이 timeout을 넘긴다(504). scoped 경로는
    # roots_with_identity를 대상 dataset의 canonical pair root로만 좁혀 시간창이
    # 아니라 dataset 범위로 제한하므로 누적·유휴 여부와 무관하게 빠르다.
    # snapshot은 시간창을 두지 않아 유휴 scope의 latest_terminal/active도 보존한다.
    execution_snapshots = await list_dataset_execution_snapshots_scoped(
        session,
        provider=provider,
        dataset_key=dataset_key,
    )
    latest_execution, active_execution = _dataset_execution_projection(
        execution_snapshots,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=canonical_scope,
    )
    executions_page = await list_pipeline_executions(
        session,
        provider=provider,
        dataset_key=dataset_key,
        dataset_sync_scopes=history_sync_scopes,
        limit=_RECENT_RUNS_LIMIT,
    )
    events_page = await list_ops_import_job_events(
        session,
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=event_sync_scope,
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
        latest_execution=_execution_record(latest_execution),
        active_execution=_execution_record(active_execution),
        execution_coverage="db_recorded_canonical_operations",
        run_history=OpsDatasetRunHistory(
            items=_run_history_records(
                executions_page.items,
                provider=provider,
                dataset_key=dataset_key,
                sync_scopes=history_sync_scopes,
            ),
            next_cursor=executions_page.next_cursor,
            canonical_url=_run_history_url(
                provider,
                dataset_key,
                canonical_scope,
            ),
        ),
        event_history=OpsDatasetEventHistory(
            items=[_event_record(item) for item in events_page.items],
            next_cursor=events_page.next_cursor,
            canonical_url=_event_history_url(
                provider,
                dataset_key,
                event_sync_scope,
            ),
        ),
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
            expected_revision=(
                int(body.expected_revision)
                if body.expected_revision is not None
                else None
            ),
            targeted_policy=body.targeted_policy,
            system_interval_seconds=body.system_interval_seconds,
            optimal_interval_seconds=body.optimal_interval_seconds,
            min_interval_seconds=body.min_interval_seconds,
            max_requests_per_minute=body.max_requests_per_minute,
            max_requests_per_hour=body.max_requests_per_hour,
            max_requests_per_day=body.max_requests_per_day,
            max_concurrent=body.max_concurrent,
            burst_size=body.burst_size,
            config_source=body.config_source,
            enabled=body.enabled,
            stale_after_minutes=body.stale_after_minutes,
        )
