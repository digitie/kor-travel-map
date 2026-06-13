"""``/providers`` — provider 데이터 신선도 (T-213g 단건 + T-217g 목록).

``provider_sync.provider_sync_state``를 기준으로 provider의 마지막 적재 성공/실패
시각을 제공한다. 단건(``GET /providers/{provider}/last-sync``)은 TripMate 상세 카드
"n시간 전 갱신" 표시용, 목록(``GET /providers``)은 전 provider×dataset 신선도/최근
실패를 한눈에 보는 운영 대시보드용(D-07/T-217g). 내부 cursor(provider 증분 상태)는
**응답에 노출하지 않는다**(운영 내부 값). 단건은 ``dataset_key``/``sync_scope``
필터로 좁힐 수 있고, 매칭 행이 없으면 404. 목록은 빈 배열을 200으로 반환한다
(아직 한 번도 적재하지 않은 환경).
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from kortravelmap.infra import sync_state_repo
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    list_update_requests,
)
from kortravelmap.infra.provider_refresh_policy_repo import (
    ProviderRefreshPolicy,
    list_provider_refresh_policies,
)
from kortravelmap.infra.sync_state_repo import SyncState
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.provider_refresh_schema import (
    ProviderRefreshPolicyRecord,
    provider_refresh_policy_record,
)
from kortravelmap.api.response import Meta, make_meta

router = APIRouter(tags=["providers"])


class SyncStateSummary(BaseModel):
    """provider 1 (dataset_key, sync_scope) 신선도 — cursor 제외."""

    model_config = ConfigDict(extra="forbid")

    dataset_key: str
    sync_scope: str
    status: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int


class ProviderLastSyncData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    items: list[SyncStateSummary]


class ProviderLastSyncResponse(BaseModel):
    """``GET /providers/{provider}/last-sync`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: ProviderLastSyncData
    meta: Meta


class ProviderSyncStateSummary(BaseModel):
    """전체 목록의 1행 — ``SyncStateSummary`` + ``provider`` (cursor 제외)."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    sync_scope: str
    status: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int


class ProvidersFreshnessData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProviderSyncStateSummary]


class ProvidersFreshnessResponse(BaseModel):
    """``GET /providers`` 응답 — 전 provider×dataset 신선도 목록."""

    model_config = ConfigDict(extra="forbid")

    data: ProvidersFreshnessData
    meta: Meta


class OpsProviderLink(BaseModel):
    """provider ops 상세 화면이 쓰는 관련 API 링크."""

    model_config = ConfigDict(extra="forbid")

    rel: str
    href: str
    label: str | None = None


class OpsProviderDatasetSummary(BaseModel):
    """``GET /ops/providers`` 목록의 1행."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    sync_scope: str
    status: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    next_run_after: datetime | None
    refresh_policy: ProviderRefreshPolicyRecord | None = None
    links: list[OpsProviderLink]


class OpsProvidersData(BaseModel):
    """provider ops 목록 data."""

    model_config = ConfigDict(extra="forbid")

    items: list[OpsProviderDatasetSummary]


class OpsProvidersResponse(BaseModel):
    """``GET /ops/providers`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsProvidersData
    meta: Meta


class OpsProviderSyncStateDetail(BaseModel):
    """ops provider 상세에서만 노출하는 sync state 상세."""

    model_config = ConfigDict(extra="forbid")

    sync_scope: str
    status: str
    cursor: dict[str, Any]
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    next_run_after: datetime | None


class OpsProviderUpdateRequestSummary(BaseModel):
    """provider/dataset과 연결된 feature update request 요약."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: str
    run_mode: str
    dry_run: bool
    job_id: str | None = None
    dagster_run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    status_url: str


class OpsProviderDatasetDetail(BaseModel):
    """provider dataset 상세 추적 단위."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    dataset_key: str
    sync_states: list[OpsProviderSyncStateDetail]
    refresh_policy: ProviderRefreshPolicyRecord | None = None
    recent_update_requests: list[OpsProviderUpdateRequestSummary]
    links: list[OpsProviderLink]


class OpsProviderDetailData(BaseModel):
    """provider 상세 data."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    datasets: list[OpsProviderDatasetDetail]


class OpsProviderDetailResponse(BaseModel):
    """``GET /ops/providers/{provider}`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: OpsProviderDetailData
    meta: Meta


def _quote_path(value: str) -> str:
    return quote(value, safe="")


def _quote_query(value: str) -> str:
    return quote(value, safe="")


def _policy_key(policy: ProviderRefreshPolicy) -> tuple[str, str]:
    return policy.provider, policy.dataset_key


def _state_key(state: SyncState) -> tuple[str, str]:
    return state.provider, state.dataset_key


def _dataset_links(provider: str, dataset_key: str) -> list[OpsProviderLink]:
    provider_path = _quote_path(provider)
    dataset_path = _quote_path(dataset_key)
    provider_query = _quote_query(provider)
    dataset_query = _quote_query(dataset_key)
    return [
        OpsProviderLink(
            rel="feature_update_requests",
            href=(
                "/v1/admin/feature-update-requests"
                f"?scope_type=provider_dataset&provider={provider_query}"
                f"&dataset_key={dataset_query}"
            ),
            label="provider_dataset update requests",
        ),
        OpsProviderLink(
            rel="create_feature_update_request",
            href="/v1/admin/feature-update-requests",
            label="create provider_dataset update request",
        ),
        OpsProviderLink(
            rel="refresh_policy",
            href=(
                "/v1/admin/provider-refresh-policies/"
                f"{provider_path}/{dataset_path}"
            ),
            label="provider refresh policy",
        ),
    ]


def _policy_record(
    policy: ProviderRefreshPolicy | None,
) -> ProviderRefreshPolicyRecord | None:
    return provider_refresh_policy_record(policy) if policy is not None else None


def _ops_summary(
    *,
    provider: str,
    dataset_key: str,
    state: SyncState | None,
    policy: ProviderRefreshPolicy | None,
) -> OpsProviderDatasetSummary:
    return OpsProviderDatasetSummary(
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=state.sync_scope if state is not None else "default",
        status=state.status if state is not None else "not_synced",
        last_success_at=state.last_success_at if state is not None else None,
        last_failure_at=state.last_failure_at if state is not None else None,
        consecutive_failures=(
            state.consecutive_failures if state is not None else 0
        ),
        next_run_after=state.next_run_after if state is not None else None,
        refresh_policy=_policy_record(policy),
        links=_dataset_links(provider, dataset_key),
    )


def _sync_state_detail(state: SyncState) -> OpsProviderSyncStateDetail:
    return OpsProviderSyncStateDetail(
        sync_scope=state.sync_scope,
        status=state.status,
        cursor=state.cursor,
        last_success_at=state.last_success_at,
        last_failure_at=state.last_failure_at,
        consecutive_failures=state.consecutive_failures,
        next_run_after=state.next_run_after,
    )


def _update_request_summary(
    request: FeatureUpdateRequest,
) -> OpsProviderUpdateRequestSummary:
    return OpsProviderUpdateRequestSummary(
        request_id=request.request_id,
        status=request.status,
        run_mode=request.run_mode,
        dry_run=request.dry_run,
        job_id=request.job_id,
        dagster_run_id=request.dagster_run_id,
        created_at=request.created_at,
        updated_at=request.updated_at,
        status_url=f"/v1/admin/feature-update-requests/{request.request_id}",
    )


@router.get(
    "/providers",
    response_model=ProvidersFreshnessResponse,
    summary="전 provider 데이터 신선도 목록(대시보드)",
)
async def list_providers_freshness(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProvidersFreshnessResponse:
    """전 provider×dataset×scope의 last-sync/최근 실패 요약 (T-217g, D-07).

    행 수가 유한(provider×dataset 수십 개)하므로 페이지네이션 없이 전량 반환한다
    (``/v1/categories`` bounded reference 패턴). 빈 환경은 200 + 빈 ``items``.
    """
    started_at = perf_counter()
    states = await sync_state_repo.list_all_sync_states(session)
    items = [
        ProviderSyncStateSummary(
            provider=s.provider,
            dataset_key=s.dataset_key,
            sync_scope=s.sync_scope,
            status=s.status,
            last_success_at=s.last_success_at,
            last_failure_at=s.last_failure_at,
            consecutive_failures=s.consecutive_failures,
        )
        for s in states
    ]
    return ProvidersFreshnessResponse(
        data=ProvidersFreshnessData(items=items),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/ops/providers",
    response_model=OpsProvidersResponse,
    summary="provider 운영 상세 목록",
)
async def list_ops_providers(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsProvidersResponse:
    """전 provider×dataset의 sync state와 refresh policy를 함께 조회한다.

    ``/v1/providers``는 사용자/서비스 표면이라 cursor를 계속 숨긴다. 이 endpoint는
    admin UI 내부 운영 화면이 쓰는 확장 표면이다.
    """
    started_at = perf_counter()
    states = await sync_state_repo.list_all_sync_states(session)
    policies = await list_provider_refresh_policies(session, limit=500)
    policy_by_key = {_policy_key(policy): policy for policy in policies}
    items = [
        _ops_summary(
            provider=state.provider,
            dataset_key=state.dataset_key,
            state=state,
            policy=policy_by_key.get(_state_key(state)),
        )
        for state in states
    ]
    state_keys = {_state_key(state) for state in states}
    for provider, dataset_key in sorted(set(policy_by_key) - state_keys):
        items.append(
            _ops_summary(
                provider=provider,
                dataset_key=dataset_key,
                state=None,
                policy=policy_by_key[(provider, dataset_key)],
            )
        )
    return OpsProvidersResponse(
        data=OpsProvidersData(items=items),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/ops/providers/{provider}",
    response_model=OpsProviderDetailResponse,
    summary="provider 운영 상세",
    responses={404: {"description": "provider sync/policy row 없음"}},
)
async def get_ops_provider(
    provider: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsProviderDetailResponse:
    """provider의 dataset별 sync state, refresh policy, 최근 update request."""
    started_at = perf_counter()
    states = await sync_state_repo.list_sync_states(session, provider=provider)
    policies = await list_provider_refresh_policies(
        session, provider=provider, limit=500
    )
    states_by_dataset: dict[str, list[SyncState]] = {}
    for state in states:
        states_by_dataset.setdefault(state.dataset_key, []).append(state)
    policy_by_dataset = {policy.dataset_key: policy for policy in policies}
    dataset_keys = sorted(set(states_by_dataset) | set(policy_by_dataset))
    if not dataset_keys:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"provider ops row 없음: {provider!r}",
        )

    datasets: list[OpsProviderDatasetDetail] = []
    for dataset_key in dataset_keys:
        requests = await list_update_requests(
            session,
            provider=provider,
            dataset_key=dataset_key,
            scope_type="provider_dataset",
            limit=10,
        )
        datasets.append(
            OpsProviderDatasetDetail(
                provider=provider,
                dataset_key=dataset_key,
                sync_states=[
                    _sync_state_detail(state)
                    for state in sorted(
                        states_by_dataset.get(dataset_key, ()),
                        key=lambda item: item.sync_scope,
                    )
                ],
                refresh_policy=_policy_record(policy_by_dataset.get(dataset_key)),
                recent_update_requests=[
                    _update_request_summary(request) for request in requests.items
                ],
                links=_dataset_links(provider, dataset_key),
            )
        )
    return OpsProviderDetailResponse(
        data=OpsProviderDetailData(provider=provider, datasets=datasets),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/providers/{provider}/last-sync",
    response_model=ProviderLastSyncResponse,
    summary="provider 데이터 신선도(last-sync)",
    responses={404: {"description": "provider sync state 없음"}},
)
async def get_provider_last_sync(
    session: Annotated[AsyncSession, Depends(get_session)],
    provider: str,
    dataset_key: Annotated[str | None, Query(description="dataset_key 필터")] = None,
    sync_scope: Annotated[str | None, Query(description="sync_scope 필터")] = None,
) -> ProviderLastSyncResponse:
    started_at = perf_counter()
    states = await sync_state_repo.list_sync_states(
        session, provider=provider, dataset_key=dataset_key, sync_scope=sync_scope
    )
    if not states:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"provider sync state 없음: {provider!r}",
        )
    items = [
        SyncStateSummary(
            dataset_key=s.dataset_key,
            sync_scope=s.sync_scope,
            status=s.status,
            last_success_at=s.last_success_at,
            last_failure_at=s.last_failure_at,
            consecutive_failures=s.consecutive_failures,
        )
        for s in states
    ]
    return ProviderLastSyncResponse(
        data=ProviderLastSyncData(provider=provider, items=items),
        meta=make_meta(started_at=started_at),
    )
