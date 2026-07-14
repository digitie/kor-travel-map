"""``/ops/datasets`` — provider×dataset 상태·정책 REST API (ADR-064, #678).

HTTP validation/response만 담당한다. schema, DB 조립, Dagster schedule projection,
fixture preview 실행은 각각 전용 모듈에 둔다.
"""

from __future__ import annotations

from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.dagster_http import dagster_http_dependencies
from kortravelmap.api.db import get_session
from kortravelmap.api.ops_dataset_preview import (
    PREVIEW_TIMEOUT_SECONDS,
    run_dataset_fixture_preview,
)
from kortravelmap.api.ops_dataset_schema import (
    OpsDatasetDetailResponse,
    OpsDatasetPreviewBudget,
    OpsDatasetPreviewData,
    OpsDatasetPreviewRequest,
    OpsDatasetPreviewResponse,
    OpsDatasetRefreshPolicyResponse,
    OpsDatasetsGridResponse,
)
from kortravelmap.api.ops_dataset_service import (
    DatasetNotFoundError,
    OrphanMutationDisabledError,
    load_dataset_detail,
    load_datasets_grid,
    upsert_dataset_refresh_policy,
)
from kortravelmap.api.provider_catalog import find_catalog_entry
from kortravelmap.api.provider_refresh_schema import (
    ProviderRefreshPolicyUpsertRequest,
    provider_refresh_policy_record,
)
from kortravelmap.api.response import make_meta

__all__ = [
    "OpsDatasetDetailResponse",
    "OpsDatasetPreviewResponse",
    "OpsDatasetRefreshPolicyResponse",
    "OpsDatasetsGridResponse",
    "router",
]

router = APIRouter(prefix="/ops/datasets", tags=["ops-datasets"])


@router.get(
    "",
    response_model=OpsDatasetsGridResponse,
    summary="provider×dataset×sync_scope 상태 그리드",
    description=(
        "freshness SLA, Dagster 실제 다음 schedule tick, 최신 DB-recorded execution, "
        "dataset/provider integrity issue를 batch 조회한다. `eligible_after`는 "
        "backoff/rate-limit 시각이며 `schedule.next_scheduled_at`과 의미가 다르다."
    ),
)
async def list_datasets_grid(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsDatasetsGridResponse:
    started_at = perf_counter()
    settings, dagster_client = dagster_http_dependencies(request)
    data = await load_datasets_grid(
        session,
        settings=settings,
        dagster_client=dagster_client,
    )
    return OpsDatasetsGridResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/{provider}/{dataset}",
    response_model=OpsDatasetDetailResponse,
    summary="dataset 상세 — scope 상태·실행·이벤트·정책",
    responses={404: {"description": "카탈로그·sync state·policy 모두 없음"}},
)
async def get_dataset_detail(
    request: Request,
    provider: str,
    dataset: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsDatasetDetailResponse:
    started_at = perf_counter()
    settings, dagster_client = dagster_http_dependencies(request)
    try:
        data = await load_dataset_detail(
            session,
            settings=settings,
            dagster_client=dagster_client,
            provider=provider,
            dataset_key=dataset,
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return OpsDatasetDetailResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


@router.put(
    "/{provider}/{dataset}/refresh-policy",
    response_model=OpsDatasetRefreshPolicyResponse,
    summary="canonical dataset refresh policy upsert",
    responses={
        404: {"description": "dataset 없음"},
        409: {
            "description": (
                "카탈로그에서 제거된 orphan row. mutation_disabled_reason 포함."
            )
        },
    },
)
async def put_dataset_refresh_policy(
    provider: str,
    dataset: str,
    body: ProviderRefreshPolicyUpsertRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsDatasetRefreshPolicyResponse:
    started_at = perf_counter()
    try:
        policy = await upsert_dataset_refresh_policy(
            session,
            provider=provider,
            dataset_key=dataset,
            body=body,
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrphanMutationDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ORPHAN_MUTATION_DISABLED",
                "message": "orphan dataset refresh policy mutation is disabled",
                "details": {
                    "mutation_disabled_reason": exc.mutation_disabled_reason,
                },
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpsDatasetRefreshPolicyResponse(
        data=provider_refresh_policy_record(policy),
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/{provider}/{dataset}/preview",
    response_model=OpsDatasetPreviewResponse,
    summary="fixture ETL 변환 preview",
    description=(
        "typed body(`source=fixture`, `max_items`)만 받는다. 외부 provider 호출 "
        "budget은 0이다. max_items는 응답 크기 cap이며 변환 CPU budget은 아니다."
    ),
    responses={
        404: {"description": "등록되지 않은 dataset"},
        409: {"description": "fixture preview capability 없음"},
        504: {"description": "fixture preview cooperative timeout"},
    },
)
async def post_dataset_preview(
    provider: str,
    dataset: str,
    body: Annotated[OpsDatasetPreviewRequest, Body()],
) -> OpsDatasetPreviewResponse:
    started_at = perf_counter()
    entry = find_catalog_entry(provider, dataset)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"등록되지 않은 dataset: {provider!r}/{dataset!r}",
        )
    if entry.preview != "fixture":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PREVIEW_NOT_SUPPORTED",
                "message": "fixture preview capability가 없습니다",
                "details": {"capability": "none"},
            },
        )
    try:
        result = await run_dataset_fixture_preview(
            provider,
            dataset,
            max_items=body.max_items,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PREVIEW_REGISTRY_MISMATCH",
                "message": "fixture registry와 catalog capability가 불일치합니다",
                "details": {"capability": "fixture"},
            },
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="fixture preview timeout",
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OpsDatasetPreviewResponse(
        data=OpsDatasetPreviewData(
            provider=result.provider,
            dataset=result.dataset,
            source="fixture",
            variant=result.variant,
            description=result.description,
            items=list(result.items),
            total_items=result.total_items,
            returned_items=len(result.items),
            truncated=result.truncated,
            budget=OpsDatasetPreviewBudget(
                max_items=result.max_items,
                timeout_seconds=PREVIEW_TIMEOUT_SECONDS,
                external_call_budget=0,
            ),
        ),
        meta=make_meta(started_at=started_at),
    )
