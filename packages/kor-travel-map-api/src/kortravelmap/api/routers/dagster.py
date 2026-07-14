"""``/ops/dagster`` legacy HTTP routes.

HTTP 요청 컨텍스트와 route metadata만 소유하며, Dagster 조회·파싱·조작은
``dagster_query_service``와 ``dagster_schedule_service``에 위임한다.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api import dagster_query_service, dagster_schedule_service
from kortravelmap.api.dagster_http import dagster_http_dependencies
from kortravelmap.api.dagster_schema import (
    DagsterNuxSeenResponse,
    DagsterRunDetailResponse,
    DagsterScheduleCommandRequest,
    DagsterScheduleCommandResponse,
    DagsterScheduleOverrideRequest,
    DagsterSummaryResponse,
)
from kortravelmap.api.db import get_session

__all__ = [
    "DagsterNuxSeenResponse",
    "DagsterRunDetailResponse",
    "DagsterScheduleCommandResponse",
    "DagsterSummaryResponse",
    "router",
]

router = APIRouter(prefix="/ops/dagster", tags=["ops", "dagster"])


@router.get(
    "/summary",
    response_model=DagsterSummaryResponse,
    summary="작업 자동화 요약",
    description=(
        "Dagster GraphQL에서 repository, asset, schedule/sensor, recent run 정보를 "
        "읽어 admin UI 요약 DTO로 반환한다. Dagster webserver가 내려가도 200 "
        "응답(status=unavailable)으로 UI가 장애 상태를 표시할 수 있게 한다. "
        "GET은 조회 전용이며 Dagster mutation은 호출하지 않는다."
    ),
)
async def get_dagster_summary(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    page_size: int = Query(default=10, ge=1, le=50),
) -> DagsterSummaryResponse:
    settings, client = dagster_http_dependencies(request)
    overrides = await dagster_schedule_service.schedule_overrides(session)
    return await dagster_query_service.get_summary(
        settings=settings,
        client=client,
        overrides=overrides,
        page_size=page_size,
    )


@router.get(
    "/runs/{run_id}",
    response_model=DagsterRunDetailResponse,
    summary="Dagster run 상세",
    description=(
        "Dagster GraphQL runOrError를 조회해 최근 event log와 실패 error payload를 "
        "admin UI용 DTO로 반환한다. 조회 전용이며 Dagster run을 재실행하거나 "
        "상태를 변경하지 않는다."
    ),
)
async def get_dagster_run_detail(
    request: Request,
    run_id: str,
    page_size: int = Query(default=50, ge=1, le=200),
    after: str | None = Query(
        default=None,
        description=(
            "event log cursor(이전 응답의 event_cursor). 긴 run의 뒤쪽(실패) 이벤트로 "
            "전진 페이지네이션하기 위함. 미지정이면 처음부터."
        ),
    ),
) -> DagsterRunDetailResponse:
    settings, client = dagster_http_dependencies(request)
    return await dagster_query_service.get_run_detail(
        settings=settings,
        client=client,
        run_id=run_id,
        page_size=page_size,
        after=after,
    )


@router.post(
    "/nux-seen",
    response_model=DagsterNuxSeenResponse,
    summary="Dagster NUX seen 처리",
    description=(
        "embedded Dagster 화면의 로컬 첫 실행 NUX를 접기 위해 Dagster GraphQL "
        "setNuxSeen mutation을 호출한다. GET summary의 부수효과를 제거하기 위해 "
        "명시 POST endpoint로 분리했다."
    ),
)
async def mark_dagster_nux_seen(request: Request) -> DagsterNuxSeenResponse:
    settings, client = dagster_http_dependencies(request)
    return await dagster_query_service.mark_nux_seen(settings=settings, client=client)


@router.patch(
    "/schedules/{schedule_name}",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 cron 수정",
    description=(
        "운영 스케줄의 cron override를 저장하고 code location reload를 요청한다. "
        "cron은 코드 정의를 직접 변경하지 않고 ops.dagster_schedule_overrides에 보관된다."
    ),
)
async def update_dagster_schedule(
    request: Request,
    schedule_name: str,
    body: DagsterScheduleOverrideRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DagsterScheduleCommandResponse:
    settings, client = dagster_http_dependencies(request)
    return await dagster_schedule_service.update_schedule(
        settings=settings,
        client=client,
        session=session,
        schedule_name=schedule_name,
        body=body,
    )


@router.post(
    "/schedules/{schedule_name}/default",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 기본값 복귀",
    description="운영 스케줄 cron override를 삭제하고 code location reload를 요청한다.",
)
async def reset_dagster_schedule_default(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    del body
    settings, client = dagster_http_dependencies(request)
    return await dagster_schedule_service.reset_schedule_default(
        settings=settings,
        client=client,
        session=session,
        schedule_name=schedule_name,
    )


async def mutate_schedule_state(
    *,
    request: Request,
    schedule_name: str,
    command: Literal["start", "stop", "reset"],
    session: AsyncSession,
) -> DagsterScheduleCommandResponse:
    """Legacy route wrapper for the shared schedule mutation service."""

    settings, client = dagster_http_dependencies(request)
    return await dagster_schedule_service.mutate_schedule_state(
        settings=settings,
        client=client,
        session=session,
        schedule_name=schedule_name,
        command=command,
    )


@router.post(
    "/schedules/{schedule_name}/start",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 시작",
)
async def start_dagster_schedule(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    del body
    return await mutate_schedule_state(
        request=request,
        schedule_name=schedule_name,
        command="start",
        session=session,
    )


@router.post(
    "/schedules/{schedule_name}/stop",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 중지",
)
async def stop_dagster_schedule(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    del body
    return await mutate_schedule_state(
        request=request,
        schedule_name=schedule_name,
        command="stop",
        session=session,
    )


@router.post(
    "/schedules/{schedule_name}/reset",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 상태 기본값 복귀",
)
async def reset_dagster_schedule_state(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    del body
    return await mutate_schedule_state(
        request=request,
        schedule_name=schedule_name,
        command="reset",
        session=session,
    )


@router.post(
    "/schedules/{schedule_name}/run",
    response_model=DagsterScheduleCommandResponse,
    summary="운영 스케줄 즉시 실행",
    description="스케줄이 가리키는 job을 현재 설정으로 1회 실행한다.",
)
async def run_dagster_schedule_now(
    request: Request,
    schedule_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: DagsterScheduleCommandRequest | None = None,
) -> DagsterScheduleCommandResponse:
    settings, client = dagster_http_dependencies(request)
    return await dagster_schedule_service.run_schedule_now(
        settings=settings,
        client=client,
        session=session,
        schedule_name=schedule_name,
        body=body,
    )
