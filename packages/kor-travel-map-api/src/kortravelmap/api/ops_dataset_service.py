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
    ProviderDatasetCatalogEntry,
    list_provider_dataset_catalog,
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


def _dataset_detail_url(
    provider_dataset_id: int,
    sync_scope: str,
    operation_key: str | None = None,
) -> str:
    """membership을 주소로 갖는 상세 링크.

    ``operation_key`` 없이 만들면 같은 scope의 형제 operation 행들이 **같은 링크**를
    갖게 돼, 그리드에서 어느 행을 눌러도 같은 화면이 열린다. 실행 가능한 operation이
    없는 catalog 행만 scope 단위 링크를 갖는다.
    """
    return (
        f"/v1/ops/datasets/{provider_dataset_id}?"
        + urlencode(
            {
                "sync_scope": sync_scope,
                **({"operation_key": operation_key} if operation_key else {}),
            },
            quote_via=quote,
        )
    )


def _event_history_url(
    provider_dataset_id: int,
    effective_sync_scope: str,
) -> str:
    return (
        "/v1/ops/pipeline/events?"
        + urlencode(
            {
                "provider_dataset_id": provider_dataset_id,
                "sync_scope": effective_sync_scope,
            },
            quote_via=quote,
        )
    )


def _run_history_url(
    provider_dataset_id: int,
    logical_sync_scope: str,
) -> str:
    return (
        "/v1/ops/pipeline/executions?"
        + urlencode(
            {
                "provider_dataset_id": provider_dataset_id,
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
    supported = entry.has_fixture_preview
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
    if not entry.supports_targeted_refresh:
        return OpsDatasetScopeRefreshCapability(
            supported=False,
            selector="none",
            effect="dataset_wide",
            default_sync_scope="dataset_wide",
            allowed_sync_scopes=[],
            reason="이 dataset은 전체 dataset 단위로만 갱신합니다.",
        )
    return OpsDatasetScopeRefreshCapability(
        supported=True,
        selector="poi_cache_targets",
        effect="sync_scope",
        default_sync_scope="target_grids",
        allowed_sync_scopes=["target_grids"],
        reason=None,
    )


def _catalog_state_memberships(
    entry: ProviderDatasetCatalogEntry,
) -> tuple[tuple[str, str | None], ...]:
    """catalog가 선언한 exact membership을 ``(sync_scope, operation_key)``로 편다.

    ``entry.refresh_scopes``는 operation을 가로질러 scope로 합집합한다 — 그 모양으로
    행을 만들면 같은 scope를 공유하는 형제 operation이 한 행으로 접힌다. 여기서는
    접지 않고 operation별로 편다.

    refresh operation이 하나도 없는 dataset(실측 74개 중 18개)은 결박할 실행
    identity가 없으므로 ``operation_key=None``인 catalog 전용 행 하나를 낸다.
    """
    if not entry.is_refreshable:
        return ((DATASET_WIDE_SYNC_SCOPE, None),)
    return tuple(
        dict.fromkeys(
            (sync_scope, operation.operation_key)
            for operation in entry.enabled_refresh_operations
            for sync_scope in operation.sync_scopes
        )
    )


def _logical_state_scope(
    entry: ProviderDatasetCatalogEntry | None,
    state_scope: str,
) -> str:
    """정규화된 DB state scope를 API scope로 투영한다.

    T-VN-33 cutover 뒤 state PK/FK는 canonical scope만 허용한다. 옛 ``default``
    alias를 보정하는 compatibility branch는 의도적으로 남기지 않는다.
    """
    del entry
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


def _states_by_api_membership(
    entry: ProviderDatasetCatalogEntry | None,
    states: Sequence[SyncState],
) -> dict[tuple[str, str], SyncState]:
    """sync state를 exact membership triple로 색인한다.

    ``pk_provider_sync_state``가 triple이므로 scope 하나에 operation별 state가 여러 개
    있을 수 있다. scope 문자열만으로 키를 잡으면 형제 operation이 조용히 덮여, 실패
    중인 operation이 형제에 가려 보이지 않는다 — cutover로 ``default`` alias가
    사라진 뒤로 옛 접기 규칙은 alias가 아니라 operation을 접고 있었다.

    표현 불가능한 legacy scope는 그대로 숨긴다.
    """
    selected: dict[tuple[str, str], SyncState] = {}
    for state in states:
        logical_scope = _api_state_scope(entry, state.sync_scope)
        if logical_scope is None:
            continue
        selected[(logical_scope, state.operation_key)] = state
    return selected


def _catalog_info(entry: ProviderDatasetCatalogEntry) -> OpsDatasetCatalogInfo:
    return OpsDatasetCatalogInfo(
        feature_kind=entry.feature_kind,
        provider_state_default_scope=(
            entry.default_refresh_scope if entry.is_refreshable else DATASET_WIDE_SYNC_SCOPE
        ),
        label=entry.display_name,
        is_refreshable=entry.is_refreshable,
        scope_refresh=_scope_refresh_capability(entry),
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
        provider_datasets=[
            OpsDatasetProviderDataset(
                provider_dataset_id=pair.provider_dataset_id,
                provider=pair.provider,
                dataset_key=pair.dataset_key,
                sync_scope=pair.sync_scope,
                operation_key=pair.operation_key,
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
        operation_key=root.operation_key,
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
            operation_key=projected.operation_key,
            depth=projected.depth,
            detail_url=f"/v1/ops/pipeline/executions/import_job/{projected.id}",
        ),
        cancellation=cancellation_summary_record(root.cancellation),
    )


def _dataset_execution_projection(
    snapshots: tuple[DatasetExecutionSnapshot, ...],
    *,
    provider_dataset_id: int,
    sync_scope: str,
    operation_key: str | None,
) -> tuple[DatasetLatestExecution | None, DatasetLatestExecution | None]:
    """exact membership의 terminal 최신값과 active 최신값을 같은 snapshot에서 고른다.

    repo가 triple별로 분리해 준 snapshot을 여기서 scope로만 모으면 도로 접힌다 —
    형제 operation의 실행이 서로의 자리를 다툰다. ``operation_key``가 None인
    catalog 전용 행에는 결박할 실행이 없으므로 후보가 비는 것이 정상이다.
    """
    candidates = tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.provider_dataset_id == provider_dataset_id
        and snapshot.sync_scope == sync_scope
        and snapshot.operation_key == operation_key
    )

    return _latest_terminal_and_active(candidates)


def _latest_terminal_and_active(
    candidates: tuple[DatasetExecutionSnapshot, ...],
) -> tuple[DatasetLatestExecution | None, DatasetLatestExecution | None]:
    """후보 snapshot에서 terminal 최신값과 active 최신값을 각각 고른다."""

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
    provider_dataset_id: int,
    sync_scopes: tuple[str, ...],
) -> list[OpsDatasetExecution]:
    """root가 건드린 **membership마다** 한 줄을 낸다.

    예전에는 root마다 membership 하나를 ``operation_member_id``(UUID) tie-break로
    골랐다. 그건 형제 operation 중 임의 선택이고, 이 작업이 없애려던 바로 그
    모양이다 — 게다가 고른 쪽의 ``operation_key``와 ``pair_status``가 응답에
    실리므로 운영자는 다른 operation이 어떤 상태였는지 알 방법이 없다.

    같은 root가 두 membership을 건드렸다면 그건 중복이 아니라 **서로 다른 두
    사실**이다. 행이 늘어나 보이는 것은 identity가 triple이기 때문이고,
    ``operation_key``가 함께 실리므로 화면에서 구분된다.
    """
    records: list[OpsDatasetExecution] = []
    for execution in executions:
        members = sorted(
            (
                member
                for member in execution.provider_datasets
                if member.provider_dataset_id == provider_dataset_id
                and member.sync_scope in sync_scopes
            ),
            key=lambda item: (item.sync_scope, item.operation_key),
        )
        for member in members:
            records.append(
                _execution_record(
                    DatasetLatestExecution(
                        provider_dataset_id=provider_dataset_id,
                        provider=member.provider,
                        dataset_key=member.dataset_key,
                        sync_scope=member.sync_scope,
                        operation_key=member.operation_key,
                        execution=execution,
                        operation_member_id=member.operation_member_id,
                        pair_status=member.status,
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


def _scope_execution_rollup(
    snapshots: tuple[DatasetExecutionSnapshot, ...],
    *,
    provider_dataset_id: int,
    sync_scope: str,
) -> tuple[DatasetLatestExecution | None, DatasetLatestExecution | None]:
    """scope 안의 **모든 operation을 가로지른** terminal/active 최신값.

    dataset 상세 URL이 scope 단위라 헤드라인 실행은 membership 하나로 좁힐 수 없다.
    이건 의도된 롤업이고, membership별 상태는 같은 응답의 ``scopes``가 따로 낸다 —
    ``_dataset_execution_projection``(triple 정확 일치)과 혼동하지 말 것.
    """
    candidates = tuple(
        snapshot
        for snapshot in snapshots
        if snapshot.provider_dataset_id == provider_dataset_id
        and snapshot.sync_scope == sync_scope
    )
    return _latest_terminal_and_active(candidates)


def _grid_row(
    *,
    provider: str,
    dataset_key: str,
    provider_dataset_id: int,
    sync_scope: str,
    operation_key: str | None,
    state: SyncState | None,
    has_persisted_state: bool,
    entry: ProviderDatasetCatalogEntry | None,
    policy: ProviderRefreshPolicy | None,
    dataset_issues: DatasetIntegrityIssueCount | None,
    latest_execution: DatasetLatestExecution | None,
    active_execution: DatasetLatestExecution | None,
    schedules: DatasetScheduleIndex,
    now: datetime,
) -> OpsDatasetGridRow:
    canonical = entry is not None
    return OpsDatasetGridRow(
        provider_dataset_id=provider_dataset_id,
        provider=provider,
        dataset_key=dataset_key,
        detail_url=_dataset_detail_url(provider_dataset_id, sync_scope, operation_key),
        sync_scope=sync_scope,
        operation_key=operation_key,
        status=state.status if state is not None else _NEVER_RUN_STATUS,
        last_success_at=state.last_success_at if state is not None else None,
        last_failure_at=state.last_failure_at if state is not None else None,
        consecutive_failures=(state.consecutive_failures if state is not None else 0),
        eligible_after=state.next_run_after if state is not None else None,
        freshness=_freshness(state, policy, now=now),
        schedule=_schedule_summary(
            schedules.for_operation_keys(
                tuple(
                    operation.operation_key
                    for operation in entry.enabled_refresh_operations
                )
                if entry is not None
                else ()
            )
        ),
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
            _catalog_info(entry)
            if entry is not None
            else None
        ),
        refresh_policy=(
            provider_refresh_policy_record(policy) if policy is not None else None
        ),
        dataset_issues=_issue_summary(dataset_issues),
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
    schedules = await load_dataset_schedule_index(
        settings=settings,
        client=dagster_client,
    )
    catalog_entries = await list_provider_dataset_catalog(session)
    reference = now or kst_now()

    states_by_dataset_id: dict[int, list[SyncState]] = {}
    for state in states:
        states_by_dataset_id.setdefault(state.provider_dataset_id, []).append(state)
    policies_by_dataset_id = {
        policy.provider_dataset_id: policy for policy in policies
    }
    dataset_issues_by_id = {item.provider_dataset_id: item for item in issue_counts}
    rows: list[OpsDatasetGridRow] = []
    for entry in catalog_entries:
        entry_states = states_by_dataset_id.pop(entry.provider_dataset_id, [])
        policy = policies_by_dataset_id.pop(entry.provider_dataset_id, None)
        states_by_membership = _states_by_api_membership(entry, entry_states)
        expected_memberships = _catalog_state_memberships(entry)
        # catalog가 선언하지 않았는데 state가 남아 있는 membership도 보여 준다 —
        # operation이 카탈로그에서 빠졌는데 state만 남은 상태가 여기서 드러난다.
        stale_memberships = tuple(
            dict.fromkeys(
                membership
                for membership in states_by_membership
                if membership not in expected_memberships
            )
        )
        row_memberships = tuple(
            dict.fromkeys((*expected_memberships, *stale_memberships))
        )
        for row_sync_scope, row_operation_key in row_memberships:
            entry_state = (
                states_by_membership.get((row_sync_scope, row_operation_key))
                if row_operation_key is not None
                else None
            )
            latest_execution, active_execution = (
                _dataset_execution_projection(
                    execution_snapshots,
                    provider_dataset_id=entry.provider_dataset_id,
                    sync_scope=row_sync_scope,
                    operation_key=row_operation_key,
                )
                if row_operation_key is not None
                # refresh operation이 없는 catalog 행은 결박할 membership이 없다.
                # 실행이 남아 있다면 그 scope의 롤업으로 보여 준다.
                else _scope_execution_rollup(
                    execution_snapshots,
                    provider_dataset_id=entry.provider_dataset_id,
                    sync_scope=row_sync_scope,
                )
            )
            rows.append(
                _grid_row(
                    provider=entry.provider,
                    dataset_key=entry.dataset_key,
                    provider_dataset_id=entry.provider_dataset_id,
                    sync_scope=row_sync_scope,
                    operation_key=row_operation_key,
                    state=entry_state,
                    has_persisted_state=entry_state is not None,
                    entry=entry,
                    policy=policy,
                    dataset_issues=dataset_issues_by_id.get(entry.provider_dataset_id),
                    latest_execution=latest_execution,
                    active_execution=active_execution,
                    schedules=schedules,
                    now=reference,
                )
            )

    for provider_dataset_id, orphan_states in states_by_dataset_id.items():
        provider = orphan_states[0].provider
        dataset_key = orphan_states[0].dataset_key
        policy = policies_by_dataset_id.pop(provider_dataset_id, None)
        orphan_states_by_membership = _states_by_api_membership(None, orphan_states)
        for (logical_scope, operation_key), state in orphan_states_by_membership.items():
            latest_execution, active_execution = _dataset_execution_projection(
                execution_snapshots,
                provider_dataset_id=state.provider_dataset_id,
                sync_scope=logical_scope,
                operation_key=operation_key,
            )
            rows.append(
                _grid_row(
                    provider=provider,
                    dataset_key=dataset_key,
                    provider_dataset_id=state.provider_dataset_id,
                    sync_scope=logical_scope,
                    operation_key=operation_key,
                    state=state,
                    has_persisted_state=True,
                    entry=None,
                    policy=policy,
                    dataset_issues=dataset_issues_by_id.get(state.provider_dataset_id),
                    latest_execution=latest_execution,
                    active_execution=active_execution,
                    schedules=schedules,
                    now=reference,
                )
            )
        if orphan_states_by_membership:
            continue
        logical_scope = DATASET_WIDE_SYNC_SCOPE
        # membership이 없는 자리표시자 행이므로 triple 정확 일치로는 아무것도 못 붙인다.
        # 운영자가 실행 자체를 잃지 않도록 scope 롤업을 쓴다(의도된 접기).
        latest_execution, active_execution = _scope_execution_rollup(
            execution_snapshots,
            provider_dataset_id=orphan_states[0].provider_dataset_id,
            sync_scope=logical_scope,
        )
        rows.append(
            _grid_row(
                provider=provider,
                dataset_key=dataset_key,
                provider_dataset_id=orphan_states[0].provider_dataset_id,
                sync_scope=logical_scope,
                operation_key=None,
                state=None,
                has_persisted_state=True,
                entry=None,
                policy=policy,
                dataset_issues=dataset_issues_by_id.get(orphan_states[0].provider_dataset_id),
                latest_execution=latest_execution,
                active_execution=active_execution,
                schedules=schedules,
                now=reference,
            )
        )

    for policy in policies_by_dataset_id.values():
        if policy.provider is None or policy.dataset_key is None:
            continue
        provider = policy.provider
        dataset_key = policy.dataset_key
        latest_execution, active_execution = _scope_execution_rollup(
            execution_snapshots,
            provider_dataset_id=policy.provider_dataset_id,
            sync_scope=DATASET_WIDE_SYNC_SCOPE,
        )
        rows.append(
            _grid_row(
                provider=provider,
                dataset_key=dataset_key,
                provider_dataset_id=policy.provider_dataset_id,
                sync_scope=DATASET_WIDE_SYNC_SCOPE,
                operation_key=None,
                state=None,
                has_persisted_state=False,
                entry=None,
                policy=policy,
                dataset_issues=dataset_issues_by_id.get(policy.provider_dataset_id),
                latest_execution=latest_execution,
                active_execution=active_execution,
                schedules=schedules,
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
    operation_key: str | None,
    now: datetime,
) -> OpsDatasetScopeState:
    return OpsDatasetScopeState(
        sync_scope=sync_scope,
        operation_key=operation_key,
        status=state.status,
        cursor=state.cursor,
        last_success_at=state.last_success_at,
        last_failure_at=state.last_failure_at,
        consecutive_failures=state.consecutive_failures,
        eligible_after=state.next_run_after,
        freshness=_freshness(state, policy, now=now),
    )


def _event_record(
    event: OpsImportJobEvent, *, sync_scope: str
) -> OpsDatasetEventRecord:
    return OpsDatasetEventRecord(
        event_id=event.event_id,
        job_id=event.job_id,
        import_job_dataset_id=event.import_job_dataset_id,
        provider_dataset_id=event.provider_dataset_id,
        sync_scope=sync_scope,
        operation_key=event.operation_key,
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
    provider_dataset_id: int,
    sync_scope: str,
    operation_key: str | None = None,
    now: datetime | None = None,
) -> OpsDatasetDetailData:
    canonical_scope = parse_canonical_sync_scope(sync_scope).value
    reference = now or kst_now()
    entry = next(
        (
            item
            for item in await list_provider_dataset_catalog(session)
            if item.provider_dataset_id == provider_dataset_id
        ),
        None,
    )
    states = await sync_state_repo.list_sync_states_by_dataset_id(
        session, provider_dataset_id=provider_dataset_id
    )
    policy = (
        await get_provider_refresh_policy(
            session,
            provider_dataset_id=entry.provider_dataset_id,
        )
        if entry is not None
        else None
    )
    if entry is None and not states and policy is None:
        raise DatasetNotFoundError(f"ops dataset 없음: provider_dataset_id={provider_dataset_id!r}")

    states_by_membership = _states_by_api_membership(entry, states)
    if entry is not None:
        expected_memberships = _catalog_state_memberships(entry)
        stale_memberships = tuple(
            dict.fromkeys(
                membership
                for membership in states_by_membership
                if membership not in expected_memberships
            )
        )
        detail_memberships = tuple(
            dict.fromkeys((*expected_memberships, *stale_memberships))
        )
    else:
        detail_memberships = tuple(dict.fromkeys(states_by_membership)) or (
            (DATASET_WIDE_SYNC_SCOPE, None),
        )
    if operation_key is not None:
        # membership을 지목했으면 그 하나로 좁힌다 — 형제 operation의 상태·실행이
        # 섞이지 않는다. 없는 조합이면 아래 scope 검사에서 404로 떨어진다.
        detail_memberships = tuple(
            membership
            for membership in detail_memberships
            if membership[1] == operation_key
        )
    detail_scopes = tuple(dict.fromkeys(scope for scope, _ in detail_memberships))
    if canonical_scope not in detail_scopes:
        raise DatasetNotFoundError(
            "ops dataset scope 없음: "
            f"provider_dataset_id={provider_dataset_id!r}/{canonical_scope!r}"
        )
    # membership마다 한 줄이다 — scope로 접으면 형제 operation의 상태가 사라진다.
    # ``operation_key``가 None인 catalog 전용 membership에는 결박할 state가 없으므로
    # never-run 자리표시자를 낸다.
    scopes = [
        (
            _scope_state(
                state,
                policy,
                sync_scope=sync_scope,
                operation_key=operation_key,
                now=reference,
            )
            if operation_key is not None
            and (state := states_by_membership.get((sync_scope, operation_key)))
            is not None
            else OpsDatasetScopeState(
                sync_scope=sync_scope,
                operation_key=operation_key,
                status=_NEVER_RUN_STATUS,
                cursor={},
                last_success_at=None,
                last_failure_at=None,
                consecutive_failures=0,
                eligible_after=None,
                freshness=_freshness(None, policy, now=reference),
            )
        )
        for sync_scope, operation_key in detail_memberships
    ]

    history_sync_scopes = (canonical_scope,)
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
    if entry is None:
        raise DatasetNotFoundError(
            "canonical pipeline dataset history에는 provider_dataset_id가 필요합니다."
        )
    assert entry is not None
    execution_snapshots = await list_dataset_execution_snapshots_scoped(
        session, provider_dataset_id=provider_dataset_id
    )
    # 상세 URL은 scope 단위이므로 헤드라인 실행은 그 scope의 **모든 membership을
    # 가로지르는 명시적 롤업**이다. grid 행처럼 membership 단위로 좁힐 수 없다 —
    # 접기를 없애는 대신 의도된 롤업임을 이름과 주석으로 드러낸다.
    latest_execution, active_execution = (
        _dataset_execution_projection(
            execution_snapshots,
            provider_dataset_id=provider_dataset_id,
            sync_scope=canonical_scope,
            operation_key=operation_key,
        )
        if operation_key is not None
        else _scope_execution_rollup(
            execution_snapshots,
            provider_dataset_id=provider_dataset_id,
            sync_scope=canonical_scope,
        )
    )
    executions_page = await list_pipeline_executions(
        session,
        provider_dataset_id=provider_dataset_id,
        dataset_sync_scopes=history_sync_scopes,
        limit=_RECENT_RUNS_LIMIT,
    )
    events_page = await list_ops_import_job_events(
        session,
        provider_dataset_id=provider_dataset_id,
        sync_scope=event_sync_scope,
        limit=_RECENT_EVENTS_LIMIT,
    )
    issue_counts = await count_open_integrity_issues_by_dataset(
        session, provider_dataset_id=provider_dataset_id
    )
    dataset_issues = next(
        (item for item in issue_counts if item.provider_dataset_id == provider_dataset_id), None
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
        provider_dataset_id=provider_dataset_id,
        provider=entry.provider,
        dataset_key=entry.dataset_key,
        catalog_state="canonical" if canonical else "orphan",
        orphan_reason=orphan_reason,
        mutable=canonical,
        catalog=(
            _catalog_info(entry)
            if entry is not None
            else None
        ),
        scopes=scopes,
        schedule=_schedule_summary(
            schedules.for_operation_keys(
                tuple(
                    operation.operation_key
                    for operation in entry.enabled_refresh_operations
                )
                if entry is not None
                else ()
            )
        ),
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
                provider_dataset_id=provider_dataset_id,
                sync_scopes=history_sync_scopes,
            ),
            next_cursor=executions_page.next_cursor,
            canonical_url=_run_history_url(
                provider_dataset_id,
                canonical_scope,
            ),
        ),
        event_history=OpsDatasetEventHistory(
            items=[_event_record(item, sync_scope=event_sync_scope) for item in events_page.items],
            next_cursor=events_page.next_cursor,
            canonical_url=_event_history_url(
                provider_dataset_id,
                event_sync_scope,
            ),
        ),
        dataset_issues=_issue_summary(dataset_issues),
    )


async def upsert_dataset_refresh_policy(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    body: ProviderRefreshPolicyUpsertRequest,
) -> ProviderRefreshPolicy:
    """canonical catalog dataset만 정책 mutation을 허용한다."""
    async with session.begin():
        entry = next(
            (
                item
                for item in await list_provider_dataset_catalog(session)
                if item.provider_dataset_id == provider_dataset_id
            ),
            None,
        )
        if entry is None:
            raise DatasetNotFoundError(
                f"ops dataset 없음: provider_dataset_id={provider_dataset_id!r}"
            )
        return await upsert_provider_refresh_policy(
            session,
            provider_dataset_id=entry.provider_dataset_id,
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
