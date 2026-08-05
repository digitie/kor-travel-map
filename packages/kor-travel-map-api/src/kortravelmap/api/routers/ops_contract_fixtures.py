"""Docker Manager 전용 C6c contract fixture service API (ADR-084)."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from kortravelmap.infra.c6c_cancel_probe_fixture_repo import (
    C6C_CANCEL_PROBE_CAPABILITY_GENERATION,
    C6cCancelProbeFixture,
    C6cCancelProbeFixtureConflict,
    ensure_c6c_cancel_probe_fixture,
    finalize_c6c_cancel_probe_fixture,
    get_c6c_cancel_probe_fixture,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import (
    OPS_AUTH_ERROR_RESPONSES,
    require_ops_fixture_principal,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.response import Meta, make_meta

router = APIRouter(
    prefix="/ops/contract-fixtures/c6c-cancel-probe",
    tags=["ops-contract-fixtures"],
    dependencies=[Depends(require_ops_fixture_principal)],
    responses=OPS_AUTH_ERROR_RESPONSES,
)


class C6cCancelProbeFixtureRecord(BaseModel):
    """Manager가 crash 재개에 사용하는 secret-free durable fixture receipt."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID
    job_id: UUID
    state: Literal["armed", "consumed", "finalized"]
    cancellation_id: UUID | None
    created_at: datetime
    consumed_at: datetime | None
    finalized_at: datetime | None
    capability_generation: Literal[1] = C6C_CANCEL_PROBE_CAPABILITY_GENERATION


class C6cCancelProbeFixtureData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture: C6cCancelProbeFixtureRecord


class C6cCancelProbeFixtureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: C6cCancelProbeFixtureData
    meta: Meta


class C6cCancelProbeFixtureFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cancellation_id: UUID


def _record(value: C6cCancelProbeFixture) -> C6cCancelProbeFixtureRecord:
    return C6cCancelProbeFixtureRecord(
        transaction_id=UUID(value.transaction_id),
        job_id=UUID(value.job_id),
        state=value.state,
        cancellation_id=(
            UUID(value.cancellation_id) if value.cancellation_id is not None else None
        ),
        created_at=value.created_at,
        consumed_at=value.consumed_at,
        finalized_at=value.finalized_at,
    )


def _response(
    fixture: C6cCancelProbeFixture,
    *,
    started_at: float,
) -> C6cCancelProbeFixtureResponse:
    return C6cCancelProbeFixtureResponse(
        data=C6cCancelProbeFixtureData(fixture=_record(fixture)),
        meta=make_meta(started_at=started_at),
    )


@router.put(
    "/{transaction_id}",
    response_model=C6cCancelProbeFixtureResponse,
    summary="C6c cancel-probe fixture 멱등 ensure",
    responses={409: {"description": "fixture lifecycle conflict"}},
)
async def ensure_c6c_cancel_probe(
    transaction_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> C6cCancelProbeFixtureResponse:
    started_at = perf_counter()
    async with session.begin():
        fixture = await ensure_c6c_cancel_probe_fixture(
            session,
            transaction_id=str(transaction_id),
        )
    return _response(fixture, started_at=started_at)


@router.get(
    "/{transaction_id}",
    response_model=C6cCancelProbeFixtureResponse,
    summary="C6c cancel-probe fixture durable receipt 조회",
    responses={404: {"description": "fixture does not exist"}},
)
async def get_c6c_cancel_probe(
    transaction_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> C6cCancelProbeFixtureResponse:
    started_at = perf_counter()
    fixture = await get_c6c_cancel_probe_fixture(
        session,
        transaction_id=str(transaction_id),
    )
    if fixture is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "C6C_CANCEL_PROBE_FIXTURE_NOT_FOUND",
                "message": "C6c cancel-probe fixture를 찾을 수 없습니다.",
                "details": {},
            },
        )
    return _response(fixture, started_at=started_at)


@router.post(
    "/{transaction_id}/finalize",
    response_model=C6cCancelProbeFixtureResponse,
    summary="C6c cancel-probe fixture finalization",
    responses={409: {"description": "fixture state/cancellation conflict"}},
)
async def finalize_c6c_cancel_probe(
    transaction_id: UUID,
    body: C6cCancelProbeFixtureFinalizeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> C6cCancelProbeFixtureResponse:
    started_at = perf_counter()
    try:
        async with session.begin():
            fixture = await finalize_c6c_cancel_probe_fixture(
                session,
                transaction_id=str(transaction_id),
                cancellation_id=str(body.cancellation_id),
            )
    except C6cCancelProbeFixtureConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "C6C_CANCEL_PROBE_FIXTURE_CONFLICT",
                "message": str(exc),
                "details": {},
            },
        ) from exc
    return _response(fixture, started_at=started_at)
