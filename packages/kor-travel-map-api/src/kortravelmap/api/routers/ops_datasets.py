"""``/ops/datasets`` — provider×dataset 상태·정책 REST API (ADR-064, #678).

HTTP validation/response만 담당한다. schema, DB 조립, Dagster schedule projection,
fixture preview 실행은 각각 전용 모듈에 둔다.
"""

from __future__ import annotations

from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request, status
from kortravelmap.core.sync_scope import parse_canonical_sync_scope
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import OPS_AUTH_ERROR_RESPONSES
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
    ProviderRefreshPolicyRevisionConflict,
    ProviderRefreshPolicyRevisionExhausted,
    ProviderRefreshPolicySourceKindImmutable,
    load_dataset_detail,
    load_datasets_grid,
    upsert_dataset_refresh_policy,
)
from kortravelmap.api.provider_catalog import list_provider_dataset_catalog
from kortravelmap.api.provider_refresh_schema import (
    ProviderRefreshPolicyConflictProblem,
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

router = APIRouter(
    prefix="/ops/datasets",
    tags=["ops-datasets"],
    responses=OPS_AUTH_ERROR_RESPONSES,
)


@router.get(
    "",
    response_model=OpsDatasetsGridResponse,
    summary="provider×dataset×sync_scope 상태 그리드",
    description=(
        "freshness SLA, Dagster 실제 다음 schedule tick, 최신 DB-recorded execution, "
        "각 `provider_dataset_id`에 귀속된 integrity issue 집계를 batch 조회한다. "
        "provider-only issue group은 만들지 않는다. `eligible_after`는 "
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
    "/{provider_dataset_id:int}",
    response_model=OpsDatasetDetailResponse,
    summary="dataset 상세 — scope 상태·실행·이벤트·정책",
    responses={
        404: {"description": "카탈로그·sync state·policy 또는 exact scope 없음"},
        422: {"description": "canonical sync_scope 검증 실패"},
    },
)
async def get_dataset_detail(
    request: Request,
    provider_dataset_id: Annotated[int, Path(ge=1)],
    sync_scope: Annotated[str, Query(min_length=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
    operation_key: Annotated[
        str | None,
        Query(
            min_length=1,
            description=(
                "exact membership의 operation. 주면 그 membership 하나로 좁힌다. "
                "생략하면 scope 안의 모든 operation을 롤업해 보여 준다."
            ),
        ),
    ] = None,
) -> OpsDatasetDetailResponse:
    started_at = perf_counter()
    settings, dagster_client = dagster_http_dependencies(request)
    try:
        data = await load_dataset_detail(
            session,
            operation_key=operation_key,
            settings=settings,
            dagster_client=dagster_client,
            provider_dataset_id=provider_dataset_id,
            sync_scope=sync_scope,
        )
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return OpsDatasetDetailResponse(
        data=data,
        meta=make_meta(started_at=started_at),
    )


@router.put(
    "/refresh-policy",
    response_model=OpsDatasetRefreshPolicyResponse,
    summary="canonical dataset refresh policy upsert",
    responses={
        404: {"description": "canonical provider_dataset_id 없음"},
        409: {
            "model": ProviderRefreshPolicyConflictProblem,
            "description": (
                "revision CAS 불일치·소진, source_kind 변경 또는 카탈로그에서 "
                "제거된 orphan row. 현재 record/revision 또는 "
                "mutation_disabled_reason 포함."
            )
        },
    },
)
async def put_dataset_refresh_policy(
    provider_dataset_id: Annotated[int, Query(ge=1)],
    body: ProviderRefreshPolicyUpsertRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpsDatasetRefreshPolicyResponse:
    started_at = perf_counter()
    try:
        policy = await upsert_dataset_refresh_policy(
            session,
            provider_dataset_id=provider_dataset_id,
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
                    "expected_revision": body.expected_revision,
                    "current_revision": None,
                    "current_record": None,
                    "mutation_disabled_reason": exc.mutation_disabled_reason,
                },
            },
        ) from exc
    except ProviderRefreshPolicyRevisionConflict as exc:
        current_record = (
            provider_refresh_policy_record(exc.current)
            if exc.current is not None
            else None
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PROVIDER_REFRESH_POLICY_REVISION_CONFLICT",
                "message": "provider refresh policy revision conflict",
                "details": {
                    "expected_revision": (
                        str(exc.expected_revision)
                        if exc.expected_revision is not None
                        else None
                    ),
                    "current_revision": (
                        current_record.revision if current_record is not None else None
                    ),
                    "current_record": (
                        current_record.model_dump(mode="json")
                        if current_record is not None
                        else None
                    ),
                    "mutation_disabled_reason": None,
                },
            },
        ) from exc
    except ProviderRefreshPolicyRevisionExhausted as exc:
        current_record = provider_refresh_policy_record(exc.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PROVIDER_REFRESH_POLICY_REVISION_EXHAUSTED",
                "message": "provider refresh policy revision exhausted",
                "details": {
                    "expected_revision": body.expected_revision,
                    "current_revision": current_record.revision,
                    "current_record": current_record.model_dump(mode="json"),
                    "mutation_disabled_reason": None,
                },
            },
        ) from exc
    except ProviderRefreshPolicySourceKindImmutable as exc:
        current_record = provider_refresh_policy_record(exc.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PROVIDER_REFRESH_POLICY_SOURCE_KIND_IMMUTABLE",
                "message": "provider refresh policy source_kind is immutable",
                "details": {
                    "expected_revision": body.expected_revision,
                    "current_revision": current_record.revision,
                    "current_record": current_record.model_dump(mode="json"),
                    "mutation_disabled_reason": None,
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
    "/{provider_dataset_id:int}/preview",
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
    provider_dataset_id: Annotated[int, Path(ge=1)],
    sync_scope: Annotated[str, Query(min_length=1)],
    body: Annotated[OpsDatasetPreviewRequest, Body()],
    session: Annotated[AsyncSession, Depends(get_session)],
    operation_key: Annotated[
        str | None,
        Query(
            min_length=1,
            description=(
                "exact membership의 operation. 주면 그 dataset/scope에 실재하는 "
                "operation인지 검증한다 — 콘솔이 보내는 축을 서버가 조용히 "
                "버리면 형제 operation을 고른 것이 아무 효과도 내지 않는다."
            ),
        ),
    ] = None,
) -> OpsDatasetPreviewResponse:
    started_at = perf_counter()
    try:
        canonical_scope = parse_canonical_sync_scope(sync_scope).value
        if canonical_scope != sync_scope:
            raise ValueError("sync_scope must be canonical")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    entry = next(
        (
            item
            for item in await list_provider_dataset_catalog(session)
            if item.provider_dataset_id == provider_dataset_id
        ),
        None,
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"등록되지 않은 dataset: provider_dataset_id={provider_dataset_id!r}",
        )
    if canonical_scope not in entry.refresh_scopes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "등록되지 않은 dataset scope: "
                f"provider_dataset_id={provider_dataset_id!r}/{canonical_scope!r}"
            ),
        )
    if operation_key is not None and not any(
        operation.operation_key == operation_key and canonical_scope in operation.sync_scopes
        for operation in entry.enabled_refresh_operations
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "등록되지 않은 dataset membership: "
                f"provider_dataset_id={provider_dataset_id!r}/"
                f"{canonical_scope!r}/{operation_key!r}"
            ),
        )
    if not entry.has_fixture_preview:
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
            entry.provider,
            entry.dataset_key,
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
            provider_dataset_id=provider_dataset_id,
            sync_scope=canonical_scope,
            provider=result.provider,
            dataset_key=result.dataset,
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
