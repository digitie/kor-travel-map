"""M05 Feature 참조 reconciliation delivery service routes."""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from kortravelmap.infra import feature_reference_reconciliation_repo as reconciliation_repo
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import (
    FeatureReferenceReconciliationServiceContext,
    require_feature_reference_reconciliation_ack_service_principal,
    require_feature_reference_reconciliation_read_service_principal,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    begin_domain_command,
    complete_domain_command,
)
from kortravelmap.api.response import Meta, make_meta

__all__ = ["service_router"]

service_router = APIRouter(
    prefix="/service/feature-reference-reconciliations",
    tags=["service-feature-reference-reconciliations"],
)


class FeatureReferenceReconciliationAckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: UUID
    lease_epoch: int = Field(ge=1)
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FeatureReferenceReconciliationEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_sequence: int
    case_id: UUID
    resolution_id: UUID
    action: Literal["rebind", "retire"]
    payload: dict[str, Any]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    occurred_at: str


class FeatureReferenceReconciliationLeaseData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["leased", "empty", "lease_conflict"]
    lease_epoch: int | None
    lease_expires_at: str | None
    event: FeatureReferenceReconciliationEventData | None


class FeatureReferenceReconciliationLeaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: FeatureReferenceReconciliationLeaseData
    meta: Meta


class FeatureReferenceReconciliationAckData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["acked", "replayed"]
    acked_through_sequence: int


class FeatureReferenceReconciliationAckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: FeatureReferenceReconciliationAckData
    meta: Meta


def _lease_response_data(
    receipt: reconciliation_repo.FeatureReferenceReconciliationLease,
) -> FeatureReferenceReconciliationLeaseData:
    event: FeatureReferenceReconciliationEventData | None = None
    if receipt.outcome == "leased":
        if (
            receipt.event_id is None
            or receipt.event_sequence is None
            or receipt.case_id is None
            or receipt.resolution_id is None
            or receipt.action not in {"rebind", "retire"}
            or receipt.event_payload is None
            or receipt.event_sha256 is None
            or receipt.occurred_at is None
        ):
            raise reconciliation_repo.FeatureReferenceReconciliationError(
                "leased receipt가 불완전합니다."
            )
        event = FeatureReferenceReconciliationEventData(
            event_id=receipt.event_id,
            event_sequence=receipt.event_sequence,
            case_id=receipt.case_id,
            resolution_id=receipt.resolution_id,
            action=receipt.action,
            payload=dict(receipt.event_payload),
            sha256=receipt.event_sha256,
            occurred_at=receipt.occurred_at.isoformat(),
        )
    return FeatureReferenceReconciliationLeaseData(
        outcome=receipt.outcome,
        lease_epoch=receipt.lease_epoch,
        lease_expires_at=(
            receipt.lease_expires_at.isoformat() if receipt.lease_expires_at is not None else None
        ),
        event=event,
    )


def _ack_response(
    request: Request,
    *,
    started_at: float,
    outcome: Literal["acked", "replayed"],
    acked_through_sequence: int,
) -> FeatureReferenceReconciliationAckResponse:
    return FeatureReferenceReconciliationAckResponse(
        data=FeatureReferenceReconciliationAckData(
            outcome=outcome,
            acked_through_sequence=acked_through_sequence,
        ),
        meta=make_meta(request, started_at=started_at),
    )


def _ack_conflict(outcome: str) -> HTTPException:
    code = {
        "conflict": "FEATURE_REFERENCE_RECONCILIATION_ACK_CONFLICT",
        "lease_conflict": "FEATURE_REFERENCE_RECONCILIATION_LEASE_CONFLICT",
        "not_next": "FEATURE_REFERENCE_RECONCILIATION_EVENT_NOT_NEXT",
    }.get(outcome, "FEATURE_REFERENCE_RECONCILIATION_ACK_CONFLICT")
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": code,
            "message": "Feature 참조 reconciliation ACK을 적용할 수 없습니다.",
            "details": {},
        },
    )


@service_router.get(
    "",
    response_model=FeatureReferenceReconciliationLeaseResponse,
    responses={
        401: {"description": "reconciliation read token 없음/불일치"},
        403: {"description": "다른 service scope token"},
        503: {"description": "M05 reconciliation read boundary 비활성"},
    },
)
async def lease_feature_reference_reconciliation_event_route(
    request: Request,
    worker_id: Annotated[UUID, Header(alias="X-Reconciliation-Worker-Id")],
    context: Annotated[
        FeatureReferenceReconciliationServiceContext,
        Depends(require_feature_reference_reconciliation_read_service_principal),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureReferenceReconciliationLeaseResponse:
    """consumer별 earliest unacknowledged event에 fenced lease를 부여한다."""

    started_at = perf_counter()
    try:
        async with session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            receipt = await reconciliation_repo.lease_feature_reference_reconciliation_event(
                session,
                principal_id=context.principal_id,
                worker_id=worker_id,
            )
    except reconciliation_repo.FeatureReferenceReconciliationValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VALIDATION_ERROR", "message": str(error), "details": {}},
        ) from error
    except reconciliation_repo.FeatureReferenceReconciliationError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Feature 참조 reconciliation lease 처리 중 내부 오류가 발생했습니다.",
                "details": {},
            },
        ) from error
    return FeatureReferenceReconciliationLeaseResponse(
        data=_lease_response_data(receipt),
        meta=make_meta(request, started_at=started_at),
    )


@service_router.post(
    "/{event_id}/acks",
    response_model=FeatureReferenceReconciliationAckResponse,
    responses={
        401: {"description": "reconciliation ACK token 없음/불일치"},
        403: {"description": "다른 service scope token"},
        409: {"description": "ACK hash, lease 또는 event order 충돌"},
        422: {"description": "ACK 입력 오류"},
        503: {"description": "M05 reconciliation ACK boundary 비활성"},
    },
)
async def ack_feature_reference_reconciliation_event_route(
    event_id: UUID,
    body: FeatureReferenceReconciliationAckInput,
    request: Request,
    response: Response,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    context: Annotated[
        FeatureReferenceReconciliationServiceContext,
        Depends(require_feature_reference_reconciliation_ack_service_principal),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureReferenceReconciliationAckResponse:
    """ACK evidence를 한 번 기록하고, semantic replay는 claim 전에 종료한다."""

    started_at = perf_counter()
    try:
        async with session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            preflight = await reconciliation_repo.preflight_feature_reference_reconciliation_ack(
                session,
                principal_id=context.principal_id,
                event_id=event_id,
                event_sha256=body.event_sha256,
                local_receipt_sha256=body.local_receipt_sha256,
            )
            if preflight.outcome == "replayed":
                if preflight.acked_through_sequence is None:
                    raise reconciliation_repo.FeatureReferenceReconciliationError(
                        "replayed ACK cursor가 없습니다."
                    )
                response.headers["Idempotency-Replayed"] = "true"
                return _ack_response(
                    request,
                    started_at=started_at,
                    outcome="replayed",
                    acked_through_sequence=preflight.acked_through_sequence,
                )
            if preflight.outcome == "conflict":
                raise _ack_conflict(preflight.outcome)

            command = await begin_domain_command(
                session,
                actor=context.actor,
                operation="service.feature-reference-reconciliation.ack.v1",
                idempotency_key=idempotency_key,
                payload={"event_id": str(event_id), **body.model_dump(mode="json")},
            )
            receipt = await reconciliation_repo.ack_feature_reference_reconciliation_event(
                session,
                principal_id=context.principal_id,
                event_id=event_id,
                worker_id=body.worker_id,
                lease_epoch=body.lease_epoch,
                event_sha256=body.event_sha256,
                local_receipt_sha256=body.local_receipt_sha256,
                command_id=command.command_id,
            )
            if receipt.outcome in {"conflict", "lease_conflict", "not_next"}:
                raise _ack_conflict(receipt.outcome)
            if receipt.outcome not in {"acked", "replayed"} or (
                receipt.acked_through_sequence is None
            ):
                raise reconciliation_repo.FeatureReferenceReconciliationError(
                    "ACK receipt가 불완전합니다."
                )
            outcome: Literal["acked", "replayed"] = (
                "acked" if receipt.outcome == "acked" else "replayed"
            )
            result = _ack_response(
                request,
                started_at=started_at,
                outcome=outcome,
                acked_through_sequence=receipt.acked_through_sequence,
            )
            await complete_domain_command(session, command=command, response=result)
    except reconciliation_repo.FeatureReferenceReconciliationValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VALIDATION_ERROR", "message": str(error), "details": {}},
        ) from error
    except reconciliation_repo.FeatureReferenceReconciliationError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Feature 참조 reconciliation ACK 처리 중 내부 오류가 발생했습니다.",
                "details": {},
            },
        ) from error
    return result
