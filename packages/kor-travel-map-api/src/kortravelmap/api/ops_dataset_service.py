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
    "DatasetMutationDisabledError",
    "DatasetNotFoundError",
    "InactiveDatasetMutationDisabledError",
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
    operation_key: str | None = None,
) -> str:
    """이 응답이 실은 첫 페이지와 **같은 filter 집합**을 가리키는 canonical 링크.

    ``operation_key``를 빼면 안 된다 — cursor fingerprint에는 들어 있으므로,
    클라이언트가 이 URL과 응답의 ``next_cursor``를 합치면 filter mismatch로 422가
    난다. 그리고 embedded 첫 페이지와 "전체 목록"의 내용이 달라진다.
    """
    return (
        "/v1/ops/pipeline/events?"
        + urlencode(
            {
                "provider_dataset_id": provider_dataset_id,
                "sync_scope": effective_sync_scope,
                **({"operation_key": operation_key} if operation_key else {}),
            },
            quote_via=quote,
        )
    )


def _run_history_url(
    provider_dataset_id: int,
    logical_sync_scope: str,
    operation_key: str | None = None,
) -> str:
    """이 응답이 실은 첫 페이지와 **같은 filter 집합**을 가리키는 canonical 링크.

    ``operation_key``를 빼면 안 된다 — cursor fingerprint에는 들어 있으므로,
    클라이언트가 이 URL과 응답의 ``next_cursor``를 합치면 filter mismatch로 422가
    난다. 그리고 embedded 첫 페이지와 "전체 목록"의 내용이 달라진다.
    """
    return (
        "/v1/ops/pipeline/executions?"
        + urlencode(
            {
                "provider_dataset_id": provider_dataset_id,
                "sync_scope": logical_sync_scope,
                **({"operation_key": operation_key} if operation_key else {}),
            },
            quote_via=quote,
        )
    )


class DatasetNotFoundError(LookupError):
    """카탈로그·sync state·policy 어디에도 dataset이 없음."""


class DatasetMutationDisabledError(RuntimeError):
    """서버가 조작 불가로 판정한 dataset row의 mutation 금지."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.mutation_disabled_reason = reason


class OrphanMutationDisabledError(DatasetMutationDisabledError):
    """카탈로그에서 제거된 잔존 row의 mutation 금지."""


class InactiveDatasetMutationDisabledError(DatasetMutationDisabledError):
    """``is_active=false`` dataset의 mutation 금지.

    DB가 이미 같은 규칙을 강제한다 — ``provider_sync.reject_inactive_provider_dataset``
    트리거가 ``ops.provider_refresh_policies``를 포함한 여러 테이블의 write를
    ``ERRCODE 23514 / ck_provider_dataset_active_write``로 거부한다. 그런데 API에는
    대응 분기가 없어 catch-all이 **500 INTERNAL_ERROR**로 만들었다. 상태 오류는
    상태 오류로 답한다 — offline upload 500을 typed 4xx로 바꿀 때 세운 것과 같은 규칙.

    도달 경로: 카탈로그 조회가 ``active_only=False``라 비활성 dataset도 canonical
    entry로 통과한다(실측 seed에 1건). refresh 요청은 ``is_refreshable``이 이미
    ``is_active``를 보므로 막히지만, 정책 PUT에는 그 가드가 없었다.
    """


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


def _unrefreshable_reason(entry: ProviderDatasetCatalogEntry) -> str:
    """``is_refreshable=false``의 **실제 원인**을 그대로 문장으로 만든다.

    세 원인이 각각 다른 조치를 요구한다(dataset 활성화 / operation 등록 / scope 행
    등록). 한 문장으로 뭉치면 화면은 틀린 조치를 안내한다.
    """
    if not entry.is_active:
        return "비활성 dataset이라 갱신할 수 없습니다."
    if not entry.enabled_refresh_operations:
        return "이 dataset에는 실행 가능한 refresh runner가 없습니다."
    return "이 dataset의 refresh operation에 sync scope 선언이 없어 걸 대상이 없습니다."


def _scope_refresh_capability(
    entry: ProviderDatasetCatalogEntry,
) -> OpsDatasetScopeRefreshCapability:
    """이 dataset에 **제출 가능한 sync scope 집합**을 계약 한 벌로 낸다.

    읽는 법은 ``effect``가 정한다(``OpsDatasetScopeRefreshCapability.effect``의
    description과 프론트 fail-closed 게이트 `resolveDatasetRefreshScope`가 같은 규칙을
    쓴다).

    * ``"none"`` — 제출 가능한 scope가 없다.
    * ``"dataset_wide"`` — ``default_sync_scope`` 하나뿐이다. 이 분기에서만
      ``allowed_sync_scopes``를 비운다("고를 것이 없다"). 프론트 게이트가 그 모양을
      그대로 검사하므로(``allowed_sync_scopes.length > 0``이면 계약 모순으로 fail-closed)
      여기에 선언 목록을 실으면 정상 dataset의 갱신이 통째로 막힌다.
    * ``"sync_scope"`` — ``allowed_sync_scopes`` 중에서 고른다.

    세 분기를 합친 **제출 가능 집합**은 서버가 실제로 받는 집합과 같아야 한다.
    서버는 ``infra/feature_update_repo._ACTIVE_DATASET_MEMBERSHIPS_SQL``로 요청
    membership을 해석한다 — dataset이 ``is_active``이고 enabled refresh operation이
    그 ``sync_scope`` 행을 선언했으면 받는다. scope kind는 보지 않는다.
    그 집합이 곧 ``entry.refresh_scopes``이므로 ``allowed_sync_scopes``는
    **카탈로그가 선언한 scope 그대로**여야 한다(선언 목록 밖의 값을 지어내지도,
    선언한 값을 감추지도 않는다).

    이 성질은 ``tests/integration/test_provider_catalog.py``가 실 DB에 probe 카탈로그를
    심어 ``GET /v1/ops/datasets`` 응답 전체에 대고 단언한다 — grid가 낸 모든 행의
    ``sync_scope``가 그 행 capability의 제출 가능 집합에 있는 것과, DB가 그 triple을
    실제로 받아들이는 것이 동치여야 한다.
    """
    # ``effect="none"``은 "이 capability로는 어떤 sync scope도 제출할 수 없다"는 뜻이다.
    # 앞 판은 이 상태에도 ``effect="dataset_wide"``를 냈고, 그러면 payload가 **정상
    # dataset-wide capability와 ``reason`` 문자열 하나만** 달라진다. 프론트 게이트
    # (`frontend/src/api/datasets.ts` `resolveDatasetRefreshScope`)는 허용 경로에서
    # ``reason``을 읽지 않으므로 두 상태를 구분할 수단이 아예 없었다 — 갱신 불가
    # dataset에도 ``{allowed: true}``를 돌려줬다.
    if not entry.is_refreshable:
        return OpsDatasetScopeRefreshCapability(
            supported=False,
            selector="none",
            effect="none",
            default_sync_scope=DATASET_WIDE_SYNC_SCOPE,
            # 선언된 것이 있다면(예: 비활성 dataset의 잔존 scope) 그대로 보여 준다.
            # 운영자가 "왜 갱신이 막혔는지"를 이 목록으로 판단한다. ``effect="none"``이
            # 제출 가능 집합을 비우므로 이 목록이 실행 대상을 넓히지는 않는다.
            allowed_sync_scopes=list(entry.refresh_scopes),
            reason=_unrefreshable_reason(entry),
        )
    if entry.refresh_scopes == (DATASET_WIDE_SYNC_SCOPE,):
        # 선언이 ``dataset_wide`` 하나뿐이라 고를 것이 없다. 이 분기의 사유는 그 조건이
        # 참일 때만 참이다 — ``dataset_wide`` **말고 다른 scope도 선언된** dataset에까지
        # 이 분기를 쓰면(앞 판은 ``not supports_targeted_refresh``로 접었다) 같은 응답이
        # ``external_system:*`` membership 행을 내면서 capability로는 "전체 dataset
        # 단위로만 갱신합니다"라고 말한다. 그 문장은 그 행에 대해 거짓이고, 서버는 그
        # triple을 실제로 받는다.
        return OpsDatasetScopeRefreshCapability(
            supported=False,
            selector="none",
            effect="dataset_wide",
            default_sync_scope=DATASET_WIDE_SYNC_SCOPE,
            allowed_sync_scopes=[],
            reason="이 dataset은 전체 dataset 단위로만 갱신합니다.",
        )
    # 허용 scope는 **카탈로그가 선언한 것**이다(`provider_dataset_operation_scopes`).
    # 앞 판은 `["target_grids"]`를 박아 두어, 같은 API가 낸 membership 행을 같은
    # API가 "현재 활성 target에 포함되지 않은 sync scope입니다"라는 **거짓 사유로**
    # 거부했다. 시드에 실제로 있다 — `0089_tvn33_expand_seed`는 target_grids
    # dataset에 `dataset_wide` scope 행도 함께 심고(KMA 3종), 그 triple은
    # `POST /ops/pipeline/requests`가 그대로 받는다. 한 응답 안에서 정본과 투영이
    # 서로 모순하던 것이고, T-VN-33이 없애려던 pair 시대 투영 그 자체다.
    #
    # main에 있던 "활성 POI external system을 allowed에 덧붙인다"도 여기로 수렴한다 —
    # `external_system:*`는 이제 scope 행으로 선언돼야 허용된다. 카탈로그가 유일한
    # 정본이라는 규칙이 그 축에도 똑같이 적용된다.
    return OpsDatasetScopeRefreshCapability(
        supported=True,
        # ``selector``는 "**scope 안의 대상**을 무엇이 고르는가"다 — scope 자체를 고를 수
        # 있는지가 아니다. 이 분기를 ``target_grids`` 선언 밖으로 넓히면서 그 둘이 갈렸다:
        # ``external_system:*``만 선언한 dataset에는 POI target이 하나도 없는데
        # ``poi_cache_targets``를 그대로 내면 화면이 "범위 계약: 활성 POI target"이라고
        # 적고, 막힐 때 사유도 "현재 활성 target에 포함되지 않은 sync scope입니다"가 된다.
        # 둘 다 그 dataset에 대해 거짓이다 — 이 브랜치가 없애려던 거짓 표시 그 자체다.
        selector=(
            "poi_cache_targets" if entry.supports_targeted_refresh else "none"
        ),
        effect="sync_scope",
        # canonical scope를 하나도 선언하지 않은 dataset(``external_system:*`` 뿐)에는
        # ``entry.default_refresh_scope``의 표시용 degrade 값(``dataset_wide``)을 쓰지
        # 않는다 — 그 값은 ``allowed_sync_scopes``에 없어서 프론트 게이트가 계약 모순으로
        # 읽고, 선언되지도 않은 전체 갱신을 기본값으로 제안하는 셈이 된다. 선언된 것 중
        # 정렬 첫 값을 쓴다(``refresh_scopes``는 정렬돼 있다). ``default_sync_scope``는
        # 언제나 제출 가능 집합 안에 있어야 한다는 것이 이 분기의 불변식이다.
        default_sync_scope=(
            entry.default_refresh_scope
            if entry.declares_default_refresh_scope
            else entry.refresh_scopes[0]
        ),
        allowed_sync_scopes=list(entry.refresh_scopes),
        reason=None,
    )


def _catalog_state_memberships(
    entry: ProviderDatasetCatalogEntry,
) -> tuple[tuple[str, str | None], ...]:
    """catalog가 선언한 exact membership을 ``(sync_scope, operation_key)``로 편다.

    ``entry.refresh_scopes``는 operation을 가로질러 scope로 합집합한다 — 그 모양으로
    행을 만들면 같은 scope를 공유하는 형제 operation이 한 행으로 접힌다. 여기서는
    접지 않고 operation별로 편다.

    refresh operation이 하나도 없는 dataset은 결박할 실행 identity가 없으므로
    ``operation_key=None``인 catalog 전용 행 하나를 낸다. 그런 dataset은 seed에 실재하며
    (``tests/integration/test_provider_catalog.py``가 alembic head DB에서 단언한다),
    개수는 DB마다 다르다 — 0089가 legacy pair를 harvest하므로 개발/프로덕션 DB가
    seed-only DB보다 많다. 그래서 여기에는 개수를 박지 않는다.
    """
    if not entry.is_refreshable:
        return ((DATASET_WIDE_SYNC_SCOPE, None),)
    memberships = tuple(
        dict.fromkeys(
            (sync_scope, operation.operation_key)
            for operation in entry.enabled_refresh_operations
            for sync_scope in operation.sync_scopes
        )
    )
    # ``is_refreshable``이 이미 "enabled refresh operation이 scope를 하나 이상 선언"을
    # 요구하므로 여기서 ``memberships``가 비는 경로는 지금 없다. 그래도 자리표시자를
    # 남긴다 — 두 판정이 갈라지면 그리드에서 **행 자체가 사라져** catalog 존재도
    # integrity issue도 정책도 보이지 않게 되고, 그 실패는 화면에 아무 흔적을 남기지
    # 않는다.
    return memberships or ((DATASET_WIDE_SYNC_SCOPE, None),)


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
        is_active=entry.is_active,
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
        # membership 축이다(``sync_scope``와 짝). root 자신의 operation은
        # ``projected_job.operation_key``가 들고 있어 잃지 않는다.
        operation_key=item.operation_key,
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
    operation_keys: tuple[str, ...] | None,
) -> list[OpsDatasetExecution]:
    """root가 건드린 **membership마다** 한 줄을 낸다.

    예전에는 root마다 membership 하나를 ``operation_member_id``(UUID) tie-break로
    골랐다. 그건 형제 operation 중 임의 선택이고, 이 작업이 없애려던 바로 그
    모양이다 — 게다가 고른 쪽의 ``operation_key``와 ``pair_status``가 응답에
    실리므로 운영자는 다른 operation이 어떤 상태였는지 알 방법이 없다.

    같은 root가 두 membership을 건드렸다면 그건 중복이 아니라 **서로 다른 두
    사실**이다. 행이 늘어나 보이는 것은 identity가 triple이기 때문이고,
    ``operation_key``가 함께 실리므로 화면에서 구분된다.

    ``operation_keys``는 그 확장이 **요청한 축을 넘지 않게** 막는다. query는
    ``dataset_operation_key``로 root를 고르지만, 고른 root의 membership 목록에는
    형제 operation이 그대로 들어 있다 — 걸러내지 않으면 exact triple을 지목한
    상세 화면이 옆 operation의 실행까지 섞어 보여준다(화면 안내문과도 어긋난다).
    scope 롤업(``operation_keys=None``)일 때만 전부 싣는다.
    """
    records: list[OpsDatasetExecution] = []
    for execution in executions:
        members = sorted(
            (
                member
                for member in execution.provider_datasets
                if member.provider_dataset_id == provider_dataset_id
                and member.sync_scope in sync_scopes
                and (operation_keys is None or member.operation_key in operation_keys)
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
            # 이 행이 지목한 operation의 schedule만 본다. dataset의 모든 operation을
            # 넘기면 멈춘 operation 행이 형제의 RUNNING/next tick을 자기 것으로
            # 보고한다 — ``OpsDatasetGridRow`` docstring이 금지한 바로 그 모양이다.
            # None인 catalog 전용 행은 refresh operation이 없어야 나오므로 빈 튜플이
            # 정확하다.
            schedules.for_operation_keys(
                (operation_key,) if operation_key is not None else ()
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
        # `is_active=false`면 DB 트리거가 write를 거부한다 — 그 사실을 표면에
        # 반영하지 않으면 UI가 "조작 가능"이라 말한 뒤 서버가 거절한다.
        mutable=canonical and entry is not None and entry.is_active,
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
        # 행 자신의 값을 쓴다. 요청 필터 값을 각인하면 "사본이 아니라 projection"이라는
        # 규칙을 표면에서 어기는 셈이고, 필터가 넓어지는 순간 거짓말이 된다.
        # member 없는 job-level event는 null이다 — 같은 리소스의 두 표현
        # (`PipelineJobEventRecord`)과 nullability도 맞춘다.
        sync_scope=event.sync_scope,
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
    # ``operation_key``를 주면 membership 정확 일치, 없으면 그 scope의 모든
    # membership을 가로지르는 **명시적 롤업**이다 — 접기를 없애는 대신 의도된
    # 롤업임을 이름과 분기로 드러낸다. ``scopes``/``run_history``/``event_history``도
    # 같은 규칙을 따른다.
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
    # `canonical_url`이 `operation_key`를 실으므로 **이 page도 같은 filter로** 만들어야
    # 한다. 축이 어긋나면 클라이언트가 embedded 첫 page의 `next_cursor`를
    # `canonical_url`에 붙였을 때 cursor fingerprint 불일치로 422가 난다 —
    # `_run_history_url` docstring이 금지한 바로 그것이다. 그리고 첫 page와 "전체
    # 목록"의 내용이 달라진다.
    executions_page = await list_pipeline_executions(
        session,
        provider_dataset_id=provider_dataset_id,
        dataset_sync_scopes=history_sync_scopes,
        dataset_operation_key=operation_key,
        limit=_RECENT_RUNS_LIMIT,
    )
    events_page = await list_ops_import_job_events(
        session,
        provider_dataset_id=provider_dataset_id,
        sync_scope=event_sync_scope,
        operation_key=operation_key,
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
        # `is_active=false`면 DB 트리거가 write를 거부한다 — 그 사실을 표면에
        # 반영하지 않으면 UI가 "조작 가능"이라 말한 뒤 서버가 거절한다.
        mutable=canonical and entry is not None and entry.is_active,
        catalog=(
            _catalog_info(entry)
            if entry is not None
            else None
        ),
        scopes=scopes,
        schedule=_schedule_summary(
            # membership을 지목했으면 그 operation의 schedule만, 아니면 scope 전체의
            # 롤업이다 — ``latest_execution``/``run_history``와 같은 규칙이다.
            schedules.for_operation_keys(
                (operation_key,)
                if operation_key is not None
                else tuple(
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
                operation_keys=(operation_key,) if operation_key is not None else None,
            ),
            next_cursor=executions_page.next_cursor,
            canonical_url=_run_history_url(
                provider_dataset_id,
                canonical_scope,
                operation_key,
            ),
        ),
        event_history=OpsDatasetEventHistory(
            items=[_event_record(item, sync_scope=event_sync_scope) for item in events_page.items],
            next_cursor=events_page.next_cursor,
            canonical_url=_event_history_url(
                provider_dataset_id,
                event_sync_scope,
                operation_key,
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
        if not entry.is_active:
            raise InactiveDatasetMutationDisabledError("provider_dataset_inactive")
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
