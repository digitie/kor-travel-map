"""``/ops/geo-releases`` — geo 릴리스 재지오코딩 계획 운영 API (ADR-109 결정 8, T-GR-04).

kor-travel-geo가 새 데이터셋(``data_token``)을 서빙하면 Map은 geo 유도 값을 가진 dataset을 다시
적재한다. 그 **계획**은 ``ops.kor_travel_geo_releases``(+ items)에 있고, 감지·계획 생성은 Dagster
센서(T-GR-05)와 여기 ``POST /detect``가 **같은 함수**(``infra.geo_release_repo.plan_geo_release``)를
부른다. admin 프로필만(``require_ops_operator`` — app.py mount), 동사는 슬래시 경로다(콜론 동사는
저장소 선례가 없다).

- ``GET /ops/geo-releases`` — 최근 계획 + 지금 geo가 서빙하는 데이터셋(API가 geo를 대신 호출).
- ``GET /ops/geo-releases/{plan_id}`` — 계획·항목·커버리지.
- ``POST /ops/geo-releases/detect`` — 지금 감지(멱등; 첫 토큰은 기준선, 계획 없음).
- ``POST /ops/geo-releases/{plan_id}/items/{position}/skip`` — 대기·실패 항목 건너뛰기.
- ``POST /ops/geo-releases/{plan_id}/replan`` — 같은 토큰으로 ``plan_seq + 1`` 새 계획.
"""

from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from kortravelmap.dto.geo_dataset import DatasetRef
from kortravelmap.geocoding import (
    KorTravelGeoRestClient,
    fetch_current_dataset,
    geo_http_timeout,
)
from kortravelmap.infra import geo_release_repo
from kortravelmap.infra.feature_geocode_stamp_repo import GeoCoverage
from kortravelmap.settings import KorTravelMapSettings
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

__all__ = ["router"]

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/geo-releases", tags=["ops"])

CurrentStatus = Literal["ok", "no_token", "unavailable"]
PlanState = Literal["baseline", "planned", "running", "done", "superseded"]
ItemState = Literal["pending", "requested", "done", "failed", "skipped"]
ItemStateReason = Literal[
    "disabled",
    "no_geo_dependency",
    "queue_only",
    "operator",
    "sweep",
    "run_not_launched",
    "no_progress",
    "run_failed",
]


class GeoDatasetRecord(BaseModel):
    """geo가 지금 서빙하는 데이터셋(``POST /v2/dataset/version``의 ``current``)."""

    model_config = ConfigDict(extra="forbid")

    version_token: str
    data_token: str | None
    activated_at: datetime | None = None
    reference_months: dict[str, str] | None = None


class GeoReleaseDatasetRecord(BaseModel):
    """항목이 다시 적재하는 dataset."""

    model_config = ConfigDict(extra="forbid")

    provider_dataset_id: int
    provider: str
    dataset_key: str


class GeoReleaseItemRecord(BaseModel):
    """계획 항목 — Dagster run 1개(그 run이 다시 적재하는 dataset 목록)."""

    model_config = ConfigDict(extra="forbid")

    position: int
    operation_key: str
    datasets: list[GeoReleaseDatasetRecord]
    run_config: dict[str, Any] | None
    launch_blocked_reason: Literal["replay_not_launchable_before_t_gr_08"] | None
    attempt_seq: int
    state: ItemState
    state_reason: ItemStateReason | None
    run_key: str | None
    dagster_run_id: str | None
    requested_at: datetime | None


class GeoReleasePlanRecord(BaseModel):
    """계획 1건. 목록에서는 ``items``가 비어 있다."""

    model_config = ConfigDict(extra="forbid")

    plan_id: int
    geo_data_token: str
    plan_seq: int
    geo_version_token: str
    activated_at: datetime | None
    reference_months: dict[str, Any] | None
    state: PlanState
    residual_stale: int | None
    sweep_started_at: datetime | None
    observed_at: datetime
    completed_at: datetime | None
    items: list[GeoReleaseItemRecord]


class GeoCoverageRecord(BaseModel):
    """계획 토큰 기준 커버리지 — 분모는 그 계획의 비-skip 항목 dataset이다."""

    model_config = ConfigDict(extra="forbid")

    total_provider_with_coord: int
    stamped_current: int
    stamped_other: int
    unstamped: int
    not_called_by_kind: dict[str, int]
    excluded_by_skip: int
    unstamped_non_provider: int


class GeoReleaseListData(BaseModel):
    """``GET /ops/geo-releases`` data."""

    model_config = ConfigDict(extra="forbid")

    current: GeoDatasetRecord | None
    current_status: CurrentStatus
    plans: list[GeoReleasePlanRecord]


class GeoReleaseListResponse(BaseModel):
    """``GET /ops/geo-releases`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: GeoReleaseListData
    meta: Meta


class GeoReleaseDetailData(BaseModel):
    """계획·항목·커버리지."""

    model_config = ConfigDict(extra="forbid")

    plan: GeoReleasePlanRecord
    coverage: GeoCoverageRecord


class GeoReleaseDetailResponse(BaseModel):
    """계획 1건 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: GeoReleaseDetailData
    meta: Meta


class GeoReleaseDetectData(BaseModel):
    """``POST /ops/geo-releases/detect`` data — 감지 결과와 (있으면) 계획."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal[
        "no_token", "baseline_recorded", "baseline", "existing", "created", "already_complete"
    ]
    current: GeoDatasetRecord
    plan: GeoReleasePlanRecord | None
    superseded_plan_ids: list[int]


class GeoReleaseDetectResponse(BaseModel):
    """``POST /ops/geo-releases/detect`` 응답 (DA-D-03 envelope)."""

    model_config = ConfigDict(extra="forbid")

    data: GeoReleaseDetectData
    meta: Meta


def _dataset(current: DatasetRef) -> GeoDatasetRecord:
    return GeoDatasetRecord(
        version_token=current.version_token,
        data_token=current.data_token,
        activated_at=current.activated_at,
        reference_months=current.reference_months,
    )


def _item(item: geo_release_repo.GeoReleaseItem) -> GeoReleaseItemRecord:
    return GeoReleaseItemRecord(
        position=item.position,
        operation_key=item.operation_key,
        datasets=[
            GeoReleaseDatasetRecord(
                provider_dataset_id=dataset.provider_dataset_id,
                provider=dataset.provider,
                dataset_key=dataset.dataset_key,
            )
            for dataset in item.datasets
        ],
        run_config=item.run_config,
        launch_blocked_reason=item.launch_blocked_reason,
        attempt_seq=item.attempt_seq,
        state=cast("ItemState", item.state),
        state_reason=cast("ItemStateReason | None", item.state_reason),
        run_key=item.run_key,
        dagster_run_id=item.dagster_run_id,
        requested_at=item.requested_at,
    )


def _plan(plan: geo_release_repo.GeoReleasePlan) -> GeoReleasePlanRecord:
    return GeoReleasePlanRecord(
        plan_id=plan.plan_id,
        geo_data_token=plan.geo_data_token,
        plan_seq=plan.plan_seq,
        geo_version_token=plan.geo_version_token,
        activated_at=plan.activated_at,
        reference_months=plan.reference_months,
        state=cast("PlanState", plan.state),
        residual_stale=plan.residual_stale,
        sweep_started_at=plan.sweep_started_at,
        observed_at=plan.observed_at,
        completed_at=plan.completed_at,
        items=[_item(item) for item in plan.items],
    )


def _coverage(value: GeoCoverage) -> GeoCoverageRecord:
    return GeoCoverageRecord(
        total_provider_with_coord=value.total_provider_with_coord,
        stamped_current=value.stamped_current,
        stamped_other=value.stamped_other,
        unstamped=value.unstamped,
        not_called_by_kind=dict(value.not_called_by_kind),
        excluded_by_skip=value.excluded_by_skip,
        unstamped_non_provider=value.unstamped_non_provider,
    )


async def _current_dataset() -> DatasetRef | None:
    """geo의 현재 데이터셋 — 실패·미설정·활성 릴리스 없음은 None(경고는 팩토리가 낸다).

    run 경로와 같은 팩토리(``fetch_current_dataset``)를 쓴다(ADR-109 결정 2 — 팩토리 1개).
    """
    settings = KorTravelMapSettings()
    base_url = settings.kor_travel_geo_base_url
    if base_url is None:
        return await fetch_current_dataset(None, logger=_LOGGER)
    async with httpx.AsyncClient(
        base_url=base_url.get_secret_value(), timeout=geo_http_timeout(settings)
    ) as http:
        client = KorTravelGeoRestClient(http, api_key=settings.kor_travel_geo_api_key)
        return await fetch_current_dataset(client, logger=_LOGGER)


def _current_status(current: DatasetRef | None) -> CurrentStatus:
    if current is None:
        return "unavailable"
    return "no_token" if current.data_token is None else "ok"


async def _detail(session: AsyncSession, plan_id: int) -> GeoReleaseDetailData:
    plan = await geo_release_repo.get_geo_release_plan(session, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"geo 릴리스 계획 {plan_id}이 없다")
    return GeoReleaseDetailData(
        plan=_plan(plan), coverage=_coverage(await geo_release_repo.plan_coverage(session, plan))
    )


@router.get("", response_model=GeoReleaseListResponse, summary="geo 릴리스 계획 목록")
async def list_geo_releases(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> GeoReleaseListResponse:
    """최근 계획과 지금 geo가 서빙하는 데이터셋. ``current_status``가 ``no_token``이면 계획을 만들
    수 없다(geo 지문 backfill/복구 필요), ``unavailable``이면 geo가 답하지 않았다."""
    started_at = perf_counter()
    current = await _current_dataset()
    plans = await geo_release_repo.list_geo_release_plans(session, limit=limit)
    return GeoReleaseListResponse(
        data=GeoReleaseListData(
            current=_dataset(current) if current is not None else None,
            current_status=_current_status(current),
            plans=[_plan(plan) for plan in plans],
        ),
        meta=make_meta(started_at=started_at),
    )


@router.post(
    "/detect",
    response_model=GeoReleaseDetectResponse,
    summary="geo 릴리스 지금 감지",
    responses={503: {"description": "kor-travel-geo 현재 데이터셋을 읽지 못했다"}},
)
async def detect_geo_release(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GeoReleaseDetectResponse:
    """geo 현재 데이터셋으로 계획을 만들거나 기존 계획을 돌려준다 — 센서와 같은 함수, 멱등.

    처음 관측한 토큰은 기준선으로만 기록하고 계획을 만들지 않는다(소유자 결정 2026-10-15).
    """
    started_at = perf_counter()
    current = await _current_dataset()
    if current is None:
        raise HTTPException(
            status_code=503, detail="kor-travel-geo 현재 데이터셋을 읽지 못했다 — 감지할 수 없다"
        )
    async with session.begin():
        outcome = await geo_release_repo.plan_geo_release(session, current)
    return GeoReleaseDetectResponse(
        data=GeoReleaseDetectData(
            outcome=outcome.kind,
            current=_dataset(current),
            plan=_plan(outcome.plan) if outcome.plan is not None else None,
            superseded_plan_ids=list(outcome.superseded_plan_ids),
        ),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/{plan_id}",
    response_model=GeoReleaseDetailResponse,
    summary="geo 릴리스 계획",
    responses={404: {"description": "없는 계획"}},
)
async def get_geo_release(
    plan_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GeoReleaseDetailResponse:
    """계획·항목과 계획 토큰 기준 커버리지."""
    started_at = perf_counter()
    return GeoReleaseDetailResponse(
        data=await _detail(session, plan_id), meta=make_meta(started_at=started_at)
    )


@router.post(
    "/{plan_id}/items/{position}/skip",
    response_model=GeoReleaseDetailResponse,
    summary="geo 릴리스 계획 항목 건너뛰기",
    responses={
        404: {"description": "없는 계획"},
        409: {"description": "활성이 아닌 계획이거나 건너뛸 수 없는 항목"},
    },
)
async def skip_geo_release_item(
    plan_id: Annotated[int, Path(ge=1)],
    position: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GeoReleaseDetailResponse:
    """활성 계획의 대기·실패 항목을 ``skipped(operator)``로 둔다."""
    started_at = perf_counter()
    async with session.begin():
        try:
            await geo_release_repo.skip_item(session, plan_id, position)
        except geo_release_repo.GeoReleaseNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except geo_release_repo.GeoReleaseConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GeoReleaseDetailResponse(
        data=await _detail(session, plan_id), meta=make_meta(started_at=started_at)
    )


@router.post(
    "/{plan_id}/replan",
    response_model=GeoReleaseDetailResponse,
    summary="geo 릴리스 다시 계획",
    responses={
        404: {"description": "없는 계획"},
        409: {"description": "기준선이거나 최신 관측 토큰이 아닌 계획"},
    },
)
async def replan_geo_release(
    plan_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GeoReleaseDetailResponse:
    """그 계획의 토큰으로 ``plan_seq + 1`` 새 계획을 만든다(활성 계획은 ``superseded``).

    최신 관측 토큰의 계획만, 기준선이 아닌 것만 — 그 외는 409다."""
    started_at = perf_counter()
    async with session.begin():
        try:
            plan = await geo_release_repo.replan(session, plan_id)
        except geo_release_repo.GeoReleaseNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except geo_release_repo.GeoReleaseConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GeoReleaseDetailResponse(
        data=await _detail(session, plan.plan_id), meta=make_meta(started_at=started_at)
    )
