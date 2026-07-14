"""``/ops/datasets`` — provider×dataset 상태·정책 그룹 (ADR-064 T-ADM-C2).

admin 페이지 ②(`/ops/datasets`)의 백엔드. "각 provider×dataset이 얼마나
신선하고, 정책이 뭐고, 문제가 뭔가"를 리소스 그룹 1개로 묶는다:

- ``GET /ops/datasets`` — ETL 카탈로그(`provider_catalog`) 기반
  provider×dataset×sync_scope **3원 그리드**. 한 번도 적재되지 않은 조합도
  ``status='never_run'``으로 포함하고, sync state·refresh policy·미해결
  integrity 이슈 카운트를 join한다.
- ``GET /ops/datasets/{provider}/{dataset}`` — 상세. sync state는 **scope
  배열**(cursor 포함)로 반환하고, 최근 실행(update request + 연결 import job
  요약)·최근 이벤트·정책·이슈 카운트를 함께 준다.
- ``PUT /ops/datasets/{provider}/{dataset}/refresh-policy`` — 2원 정책 upsert.
  3원 그리드 행은 ``{provider}/{dataset}`` 2원 정책 1건에 매핑된다(scope가
  달라도 같은 정책을 공유).
- ``POST /ops/datasets/{provider}/{dataset}/preview`` — ETL dry-run(변환 결과만
  응답, DB write 없음). fixture는 상시, live(실 provider 호출)는
  ``settings.etl_live_preview_enabled`` opt-in 뒤에 둔다(쿼터 소모 방지).

"지금 갱신" 숏컷은 본 그룹에 두지 않는다 — 페이지 ②가 pipeline 그룹의
``POST /ops/pipeline/requests``(provider_dataset scope)를 직접 호출한다(ADR-064).

마운트는 ``app.py``에서 ``ops_routes_enabled`` + ``require_admin_frontend``
의존성의 자체 include 블록으로 한다 — 조작(PUT/POST)이 포함되므로 기존 무인증
ops 패턴을 승계하지 않는다(ADR-064 결정 3).
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from kortravelmap.infra import sync_state_repo
from kortravelmap.infra.dataset_status_repo import (
    DatasetIntegrityIssueCount,
    count_open_integrity_issues_by_dataset,
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
    list_provider_refresh_policies,
    upsert_provider_refresh_policy,
)
from kortravelmap.infra.sync_state_repo import SyncState
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.etl_fixtures import FIXTURE_REGISTRY, run_fixture_preview
from kortravelmap.api.etl_live import LiveLoaderError, find_live_loader
from kortravelmap.api.provider_catalog import (
    PROVIDER_DATASET_CATALOG,
    ProviderDatasetCatalogEntry,
    find_catalog_entry,
)
from kortravelmap.api.provider_refresh_schema import (
    ProviderRefreshPolicyRecord,
    ProviderRefreshPolicyUpsertRequest,
    provider_refresh_policy_record,
)
from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "OpsDatasetDetailResponse",
    "OpsDatasetPreviewResponse",
    "OpsDatasetRefreshPolicyResponse",
    "OpsDatasetsGridResponse",
    "router",
]

router = APIRouter(prefix="/ops/datasets", tags=["ops-datasets"])

# 카탈로그에는 있으나 provider_sync_state row가 없는(=한 번도 적재되지 않은)
# 조합의 status. `/ops/providers`의 D-07 never-run 가시화 규칙 승계.
_NEVER_RUN_STATUS = "never_run"

# 상세 화면 요약 한도 — 전체 이력은 페이지 ①(pipeline 그룹) 딥링크가 담당한다.
_RECENT_RUNS_LIMIT = 10
_RECENT_EVENTS_LIMIT = 20


# ── 응답 schema ────────────────────────────────────────────────────────


class OpsDatasetCatalogInfo(BaseModel):
    """ETL 카탈로그(`provider_catalog`)가 아는 dataset 메타."""

    model_config = ConfigDict(extra="forbid")

    feature_kind: str = Field(
        description="산출 Feature 종류 (place/event/notice/price/weather/route/area).",
    )
    default_sync_scope: str = Field(
        description="카탈로그 기본 sync_scope — 대부분 `default`, KMA 격자/region 예외.",
    )
    label: str = Field(description="운영자용 한글 라벨.")
    is_feature_load: bool = Field(
        description="새 Feature(FeatureBundle) 적재 여부 (WeatherValue/PriceValue는 False).",
    )
    is_refreshable: bool = Field(
        description="Dagster feature update request로 실행 가능한 적재/갱신 단위 여부.",
    )
    preview: Literal["fixture", "live", "none"] = Field(
        description=(
            "ETL preview 가용성 — `fixture`(오프라인 replay) / `live`(provider "
            "실호출, opt-in flag 필요) / `none`(미배선)."
        ),
    )


class OpsDatasetGridRow(BaseModel):
    """``GET /ops/datasets`` 그리드의 1행 — provider×dataset×sync_scope 3원."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    sync_scope: str
    status: str = Field(
        description="sync state status. row 없는 카탈로그 조합은 `never_run`.",
    )
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    next_run_after: datetime | None
    catalog: OpsDatasetCatalogInfo | None = Field(
        default=None,
        description=(
            "ETL 카탈로그 메타. 카탈로그에서 빠진 잔존 sync/policy row는 null "
            "(defensive — dataset 제거 후에도 상태는 계속 보인다)."
        ),
    )
    refresh_policy: ProviderRefreshPolicyRecord | None = None
    open_issue_count: int = Field(
        description="미해결(open/acknowledged) data integrity 이슈 수.",
    )
    issue_severity_counts: dict[str, int] = Field(
        description="미해결 이슈의 severity별 분해 (없으면 빈 객체).",
    )


class OpsDatasetsGridData(BaseModel):
    """datasets 그리드 data — 행 수가 유한(카탈로그 기반)해 페이지네이션 없음."""

    model_config = ConfigDict(extra="forbid")

    items: list[OpsDatasetGridRow]


class OpsDatasetsGridResponse(BaseModel):
    """``GET /ops/datasets`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsDatasetsGridData
    meta: Meta


class OpsDatasetScopeState(BaseModel):
    """상세의 sync_scope 1건 상태 — 운영 내부 cursor 포함."""

    model_config = ConfigDict(extra="forbid")

    sync_scope: str
    status: str
    cursor: dict[str, Any]
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    next_run_after: datetime | None


class OpsDatasetRunSummary(BaseModel):
    """dataset과 연결된 최근 실행 1건 — update request + 연결 import job 요약."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: str
    run_mode: str
    scope_type: str
    dry_run: bool
    priority: int
    job_id: str | None = None
    dagster_run_id: str | None = None
    job_status: str | None = Field(
        default=None,
        description="연결 import job status (job 미연결/미발견 시 null).",
    )
    job_progress: int | None = None
    job_current_stage: str | None = None
    operator: str | None = None
    reason: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class OpsDatasetEventRecord(BaseModel):
    """dataset과 연결된 최근 import job 이벤트 1건."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    job_id: str
    stage: str | None
    level: str
    code: str | None
    message: str
    occurred_at: datetime


class OpsDatasetDetailData(BaseModel):
    """``GET /ops/datasets/{provider}/{dataset}`` data."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    catalog: OpsDatasetCatalogInfo | None = None
    scopes: list[OpsDatasetScopeState] = Field(
        description=(
            "sync_scope별 상태 배열(3원 차원). sync row가 전혀 없으면 카탈로그 "
            "기본 scope 1건을 `never_run`으로 합성한다."
        ),
    )
    refresh_policy: ProviderRefreshPolicyRecord | None = None
    recent_runs: list[OpsDatasetRunSummary]
    recent_events: list[OpsDatasetEventRecord]
    open_issue_count: int
    issue_severity_counts: dict[str, int]


class OpsDatasetDetailResponse(BaseModel):
    """``GET /ops/datasets/{provider}/{dataset}`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsDatasetDetailData
    meta: Meta


class OpsDatasetRefreshPolicyResponse(BaseModel):
    """``PUT /ops/datasets/{provider}/{dataset}/refresh-policy`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: ProviderRefreshPolicyRecord
    meta: Meta


class OpsDatasetPreviewData(BaseModel):
    """``POST /ops/datasets/{provider}/{dataset}/preview`` data."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset: str
    source: Literal["fixture", "live"]
    variant: str = Field(description="`FeatureBundle` / `WeatherValue` / `PriceValue` 등.")
    description: str
    items: list[dict[str, Any]] = Field(
        description=(
            "변환 결과 list. variant에 따라 schema가 다르다 — FeatureBundle "
            "(feature/source_record/source_link 3-key dict) / WeatherValue / "
            "PriceValue 등."
        ),
    )


class OpsDatasetPreviewResponse(BaseModel):
    """``POST /ops/datasets/{provider}/{dataset}/preview`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsDatasetPreviewData
    meta: Meta


# ── helpers ────────────────────────────────────────────────────────────


def _settings(request: Request) -> ApiSettings:
    settings = request.app.state.settings
    assert isinstance(settings, ApiSettings)  # noqa: S101 — app factory 불변식
    return settings


def _catalog_info(entry: ProviderDatasetCatalogEntry) -> OpsDatasetCatalogInfo:
    return OpsDatasetCatalogInfo(
        feature_kind=entry.feature_kind,
        default_sync_scope=entry.sync_scope,
        label=entry.label,
        is_feature_load=entry.is_feature_load,
        is_refreshable=entry.is_refreshable,
        preview=entry.preview,
    )


def _policy_record(
    policy: ProviderRefreshPolicy | None,
) -> ProviderRefreshPolicyRecord | None:
    return provider_refresh_policy_record(policy) if policy is not None else None


def _grid_row(
    *,
    provider: str,
    dataset_key: str,
    sync_scope: str,
    state: SyncState | None,
    entry: ProviderDatasetCatalogEntry | None,
    policy: ProviderRefreshPolicy | None,
    issues: DatasetIntegrityIssueCount | None,
) -> OpsDatasetGridRow:
    return OpsDatasetGridRow(
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=state.sync_scope if state is not None else sync_scope,
        status=state.status if state is not None else _NEVER_RUN_STATUS,
        last_success_at=state.last_success_at if state is not None else None,
        last_failure_at=state.last_failure_at if state is not None else None,
        consecutive_failures=(state.consecutive_failures if state is not None else 0),
        next_run_after=state.next_run_after if state is not None else None,
        catalog=_catalog_info(entry) if entry is not None else None,
        refresh_policy=_policy_record(policy),
        open_issue_count=issues.open_total if issues is not None else 0,
        issue_severity_counts=dict(issues.by_severity) if issues is not None else {},
    )


def _scope_state(state: SyncState) -> OpsDatasetScopeState:
    return OpsDatasetScopeState(
        sync_scope=state.sync_scope,
        status=state.status,
        cursor=state.cursor,
        last_success_at=state.last_success_at,
        last_failure_at=state.last_failure_at,
        consecutive_failures=state.consecutive_failures,
        next_run_after=state.next_run_after,
    )


def _run_summary(
    request: FeatureUpdateRequest,
    job: OpsImportJob | None,
) -> OpsDatasetRunSummary:
    return OpsDatasetRunSummary(
        request_id=request.request_id,
        status=request.status,
        run_mode=request.run_mode,
        scope_type=request.scope_type,
        dry_run=request.dry_run,
        priority=request.priority,
        job_id=request.job_id,
        dagster_run_id=request.dagster_run_id,
        job_status=job.status if job is not None else None,
        job_progress=job.progress if job is not None else None,
        job_current_stage=job.current_stage if job is not None else None,
        operator=request.operator,
        reason=request.reason,
        error_message=request.error_message,
        created_at=request.created_at,
        started_at=request.started_at,
        finished_at=request.finished_at,
        updated_at=request.updated_at,
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


# fixture variant는 FeatureBundle/WeatherValue/PriceValue 3종. fixture 미등록
# dataset은 카탈로그의 is_feature_load/feature_kind로 variant를 추정한다.
def _variant_for(entry: ProviderDatasetCatalogEntry) -> str:
    if entry.is_feature_load:
        return "FeatureBundle"
    if entry.feature_kind == "price":
        return "PriceValue"
    if entry.feature_kind == "weather":
        return "WeatherValue"
    return "Enrichment"


# ── 라우터 ───────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=OpsDatasetsGridResponse,
    summary="provider×dataset×sync_scope 상태 그리드",
    description=(
        "ETL 카탈로그의 전 provider×dataset을 base set으로 sync state(신선도)·"
        "refresh policy·미해결 integrity 이슈 카운트를 LEFT JOIN 한다. sync row가 "
        "있는 dataset은 scope별로 여러 행(3원)이 되고, 한 번도 적재되지 않은 "
        "조합도 `status='never_run'`으로 노출한다(never_run vs stale 구분 승계). "
        "행 수가 유한해 페이지네이션 없이 전량 반환한다."
    ),
)
async def list_datasets_grid(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsDatasetsGridResponse:
    started_at = perf_counter()
    states = await sync_state_repo.list_all_sync_states(session)
    policies = await list_provider_refresh_policies(session, limit=500)
    issue_counts = await count_open_integrity_issues_by_dataset(session)

    states_by_key: dict[tuple[str, str], list[SyncState]] = {}
    for state in states:
        states_by_key.setdefault((state.provider, state.dataset_key), []).append(state)
    policy_by_key: dict[tuple[str, str], ProviderRefreshPolicy] = {
        (policy.provider, policy.dataset_key): policy for policy in policies
    }
    issues_by_key: dict[tuple[str, str], DatasetIntegrityIssueCount] = {
        (row.provider, row.dataset_key): row
        for row in issue_counts
        if row.dataset_key is not None
    }

    rows: list[OpsDatasetGridRow] = []

    # 1) 카탈로그 전 행 — sync row가 있으면 scope별 1행, 없으면 never_run 1행.
    for entry in PROVIDER_DATASET_CATALOG:
        key = (entry.provider, entry.dataset_key)
        entry_states = states_by_key.pop(key, [])
        policy = policy_by_key.pop(key, None)
        issues = issues_by_key.get(key)
        if not entry_states:
            rows.append(
                _grid_row(
                    provider=entry.provider,
                    dataset_key=entry.dataset_key,
                    sync_scope=entry.sync_scope,
                    state=None,
                    entry=entry,
                    policy=policy,
                    issues=issues,
                )
            )
            continue
        for state in entry_states:
            rows.append(
                _grid_row(
                    provider=entry.provider,
                    dataset_key=entry.dataset_key,
                    sync_scope=state.sync_scope,
                    state=state,
                    entry=entry,
                    policy=policy,
                    issues=issues,
                )
            )

    # 2) 카탈로그에서 빠진 잔존 sync row — 상태 가시성 보존(defensive).
    for (provider, dataset_key), leftover_states in states_by_key.items():
        policy = policy_by_key.pop((provider, dataset_key), None)
        issues = issues_by_key.get((provider, dataset_key))
        for state in leftover_states:
            rows.append(
                _grid_row(
                    provider=provider,
                    dataset_key=dataset_key,
                    sync_scope=state.sync_scope,
                    state=state,
                    entry=None,
                    policy=policy,
                    issues=issues,
                )
            )

    # 3) 카탈로그·sync 둘 다 없는 policy-only row — 정책 가시성 보존(defensive).
    for (provider, dataset_key), policy in policy_by_key.items():
        rows.append(
            _grid_row(
                provider=provider,
                dataset_key=dataset_key,
                sync_scope="default",
                state=None,
                entry=None,
                policy=policy,
                issues=issues_by_key.get((provider, dataset_key)),
            )
        )

    rows.sort(key=lambda row: (row.provider, row.dataset_key, row.sync_scope))
    return OpsDatasetsGridResponse(
        data=OpsDatasetsGridData(items=rows),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/{provider}/{dataset}",
    response_model=OpsDatasetDetailResponse,
    summary="dataset 상세 — scope 배열 + 최근 실행/이벤트 + 정책",
    responses={404: {"description": "카탈로그·sync state·policy 어디에도 없는 조합"}},
)
async def get_dataset_detail(
    provider: str,
    dataset: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsDatasetDetailResponse:
    """provider×dataset 1조합의 운영 상세.

    카탈로그 조합은 sync row가 없어도 200(never_run scope 합성). 카탈로그에
    없더라도 sync state 또는 policy row가 남아 있으면 200(잔존 상태 가시성).
    셋 다 없으면 404.
    """
    started_at = perf_counter()
    entry = find_catalog_entry(provider, dataset)
    states = await sync_state_repo.list_sync_states(
        session, provider=provider, dataset_key=dataset
    )
    policy = await get_provider_refresh_policy(
        session, provider=provider, dataset_key=dataset
    )
    if entry is None and not states and policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ops dataset 없음: {provider!r}/{dataset!r}",
        )

    scopes = [_scope_state(state) for state in states]
    if not scopes and entry is not None:
        scopes = [
            OpsDatasetScopeState(
                sync_scope=entry.sync_scope,
                status=_NEVER_RUN_STATUS,
                cursor={},
                last_success_at=None,
                last_failure_at=None,
                consecutive_failures=0,
                next_run_after=None,
            )
        ]

    requests_page = await list_update_requests(
        session,
        provider=provider,
        dataset_key=dataset,
        limit=_RECENT_RUNS_LIMIT,
    )
    jobs = await list_ops_import_jobs_by_ids(
        session,
        [item.job_id for item in requests_page.items if item.job_id],
    )
    job_by_id = {job.job_id: job for job in jobs}
    recent_runs = [
        _run_summary(item, job_by_id.get(item.job_id) if item.job_id else None)
        for item in requests_page.items
    ]

    events_page = await list_ops_import_job_events(
        session,
        provider=provider,
        dataset_key=dataset,
        limit=_RECENT_EVENTS_LIMIT,
    )
    issue_counts = await count_open_integrity_issues_by_dataset(
        session, provider=provider, dataset_key=dataset
    )
    issues = issue_counts[0] if issue_counts else None

    return OpsDatasetDetailResponse(
        data=OpsDatasetDetailData(
            provider=provider,
            dataset_key=dataset,
            catalog=_catalog_info(entry) if entry is not None else None,
            scopes=scopes,
            refresh_policy=_policy_record(policy),
            recent_runs=recent_runs,
            recent_events=[_event_record(event) for event in events_page.items],
            open_issue_count=issues.open_total if issues is not None else 0,
            issue_severity_counts=(
                dict(issues.by_severity) if issues is not None else {}
            ),
        ),
        meta=make_meta(started_at=started_at),
    )


async def _refresh_policy_target_exists(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
) -> bool:
    """refresh-policy PUT 허용 집합 — 카탈로그 ∪ 잔존 sync state ∪ 기존 policy row.

    read 표면(그리드의 잔존 sync 행·policy-only 행·상세)이 노출하는 모든 조합을
    편집 가능하게 유지하면서, 어디에도 없는 오타 조합의 유령 정책 row 생성만
    막는다. 호출자는 이미 시작된 transaction 안에서 부른다 — SELECT가 세션을
    autobegin한 뒤 ``session.begin()``을 부르면 ``InvalidRequestError``가 나는
    순서 결함(리뷰 S2) 방지.
    """
    if find_catalog_entry(provider, dataset_key) is not None:
        return True
    states = await sync_state_repo.list_sync_states(
        session, provider=provider, dataset_key=dataset_key
    )
    if states:
        return True
    existing = await get_provider_refresh_policy(
        session, provider=provider, dataset_key=dataset_key
    )
    return existing is not None


@router.put(
    "/{provider}/{dataset}/refresh-policy",
    response_model=OpsDatasetRefreshPolicyResponse,
    summary="dataset refresh policy upsert (2원)",
    responses={404: {"description": "카탈로그·sync state·기존 policy 어디에도 없는 조합"}},
)
async def upsert_dataset_refresh_policy(
    provider: str,
    dataset: str,
    body: ProviderRefreshPolicyUpsertRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsDatasetRefreshPolicyResponse:
    """``{provider}/{dataset}`` 2원 refresh policy를 full upsert한다.

    그리드/상세의 3원(scope 포함) 행이라도 정책은 2원 1건에 매핑된다. 오타로
    유령 정책 row가 생기지 않게 카탈로그·잔존 sync state·기존 policy 중 하나에
    있는 조합만 허용하고, 그 외는 404. 존재 검증 SELECT와 upsert는 **하나의
    ``session.begin()`` transaction 안**에서 실행한다 — begin 밖 SELECT는 세션을
    autobegin시켜 이후 ``begin()``이 500으로 터진다(리뷰 S2). 실세션 회귀는
    ``tests/integration/test_ops_datasets_refresh_policy.py``가 고정한다.
    """
    started_at = perf_counter()
    try:
        async with session.begin():
            if not await _refresh_policy_target_exists(
                session, provider=provider, dataset_key=dataset
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"ops dataset 없음: {provider!r}/{dataset!r}",
                )
            policy = await upsert_provider_refresh_policy(
                session,
                provider=provider,
                dataset_key=dataset,
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
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpsDatasetRefreshPolicyResponse(
        data=provider_refresh_policy_record(policy),
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/{provider}/{dataset}/preview",
    response_model=OpsDatasetPreviewResponse,
    summary="ETL 변환 dry-run preview",
    description=(
        "fixture 또는 live source로 provider raw → DTO 변환을 실행하고 결과를 "
        "JSON으로 응답한다. DB write 없음. fixture 모드는 외부 의존 없이 상시 "
        "동작. live 모드(실 provider 호출·쿼터 소모)는 "
        "`KOR_TRAVEL_MAP_API_ETL_LIVE_PREVIEW_ENABLED=1` opt-in 뒤에서만 열리고, "
        "`etl_live.LIVE_LOADER_REGISTRY` 등록 dataset만 지원한다."
    ),
    responses={
        403: {"description": "source=live인데 etl_live_preview_enabled=False"},
        404: {"description": "등록되지 않은 (provider, dataset) 또는 fixture 미등록"},
        501: {"description": "source=live 미구현 (LIVE_LOADER_REGISTRY 미등록)"},
        502: {"description": "provider 외부 API 호출 실패"},
        503: {"description": "API key 미설정 (.env 확인)"},
    },
)
async def post_dataset_preview(
    request: Request,
    provider: str,
    dataset: str,
    source: Annotated[Literal["fixture", "live"], Query()] = "fixture",
) -> OpsDatasetPreviewResponse:
    started_at = perf_counter()
    if source == "live":
        settings = _settings(request)
        if not settings.etl_live_preview_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "live ETL preview가 비활성화되어 있습니다 — 실 provider "
                    "호출(쿼터 소모)은 opt-in입니다. "
                    "KOR_TRAVEL_MAP_API_ETL_LIVE_PREVIEW_ENABLED=1로 열 수 "
                    "있습니다. fixture preview는 flag 없이 동작합니다."
                ),
            )
        return await _run_live_preview(
            provider, dataset, request, settings=settings, started_at=started_at
        )

    try:
        result = await run_fixture_preview(provider, dataset)
    except KeyError as exc:
        # fixture 미등록 — 카탈로그에 있으면 live 안내, 없으면 unknown.
        catalog_entry = find_catalog_entry(provider, dataset)
        if catalog_entry is not None:
            live_hint = (
                "`?source=live`(opt-in flag 필요)로 실호출 preview 가능."
                if catalog_entry.preview == "live"
                else "live loader도 미배선 — preview 불가."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"no preview fixture (use live): ({provider!r}, "
                    f"{dataset!r})는 카탈로그에 있으나 fixture 미등록. "
                    f"{live_hint}"
                ),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    result.pop("count", None)
    return OpsDatasetPreviewResponse(
        data=OpsDatasetPreviewData(**result),
        meta=make_meta(started_at=started_at),
    )


async def _run_live_preview(
    provider: str,
    dataset: str,
    request: Request,
    *,
    settings: ApiSettings,
    started_at: float,
) -> OpsDatasetPreviewResponse:
    """``?source=live`` 분기 — provider 실 호출 + 변환 결과 응답.

    카탈로그에 있는 (provider, dataset)이면 fixture 미등록이어도 live preview를
    허용한다 — variant/description은 fixture가 있으면 그 메타를, 없으면 카탈로그
    기반 추정/라벨을 쓴다.
    """
    catalog_entry = find_catalog_entry(provider, dataset)
    if catalog_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"등록되지 않은 (provider, dataset): ({provider!r}, "
                f"{dataset!r}). `GET /v1/ops/datasets`에서 확인."
            ),
        )
    fixture = next(
        (e for e in FIXTURE_REGISTRY if e.provider == provider and e.dataset == dataset),
        None,
    )
    variant = fixture.variant if fixture else _variant_for(catalog_entry)
    description = fixture.description if fixture else catalog_entry.label
    loader = find_live_loader(provider, dataset)
    if loader is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"source=live 미구현: ({provider!r}, {dataset!r}). "
                "fixture 모드는 동작하나 live 호출 wiring은 후속 PR. "
                "`etl_live.LIVE_LOADER_REGISTRY`에 매핑 추가 필요."
            ),
        )

    # query 파라미터를 그대로 loader에 전달 (provider별 의미는 loader 자체에서).
    params: dict[str, str] = {
        k: v for k, v in request.query_params.items() if k != "source"
    }

    try:
        items = await loader(settings, params)
    except LiveLoaderError as exc:
        # API key 미설정 / provider 응답 실패 등.
        msg = str(exc)
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "미설정" in msg or "not configured" in msg.lower()
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=status_code, detail=msg) from exc

    return OpsDatasetPreviewResponse(
        data=OpsDatasetPreviewData(
            provider=provider,
            dataset=dataset,
            source="live",
            variant=variant,
            description=description,
            items=items,
        ),
        meta=make_meta(started_at=started_at),
    )
