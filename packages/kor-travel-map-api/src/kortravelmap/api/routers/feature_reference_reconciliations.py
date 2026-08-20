"""M05 Feature 참조 reconciliation delivery service routes."""

from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from kortravelmap.infra import feature_reference_reconciliation_repo as reconciliation_repo
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from kortravelmap.api.auth import (
    AdminProxyContext,
    FeatureReferenceReconciliationServiceContext,
    require_admin_destructive_enabled,
    require_admin_frontend,
    require_feature_reference_reconciliation_ack_service_principal,
    require_feature_reference_reconciliation_read_service_principal,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    begin_domain_command,
    complete_domain_command,
    preflight_domain_command_claim,
)
from kortravelmap.api.response import Meta, make_meta, request_id

__all__ = ["activation_router", "admin_router", "service_router"]

service_router = APIRouter(
    prefix="/service/feature-reference-reconciliations",
    tags=["service-feature-reference-reconciliations"],
)
admin_router = APIRouter(
    prefix="/admin/manual-provider-dedup-cases",
    tags=["admin-manual-provider-dedup-cases"],
)
activation_router = APIRouter(
    prefix="/admin/feature-reference-reconciliation-subscriptions",
    tags=["admin-feature-reference-reconciliation-subscriptions"],
)


class FeatureReferenceReconciliationAckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: UUID
    lease_epoch: int = Field(ge=1)
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FeatureReferenceReconciliationFeatureReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    feature_uuid: UUID
    row_revision: int = Field(ge=1)


class FeatureReferenceReconciliationEventData(BaseModel):
    """DB가 보존한 canonical event payload를 재조립 없이 그대로 노출한다."""

    model_config = ConfigDict(extra="forbid")

    payload_schema_version: Literal[1]
    event_id: UUID
    event_sequence: int = Field(ge=1)
    occurred_at: str
    case_id: UUID
    resolution_id: UUID
    action: Literal["rebind", "detach"]
    old_feature: FeatureReferenceReconciliationFeatureReference
    replacement_feature: FeatureReferenceReconciliationFeatureReference | None
    manual_retire_transition_id: int = Field(ge=1)
    manual_retire_row_revision_after_transition: int = Field(ge=2)
    command_id: int = Field(ge=1)


class FeatureReferenceReconciliationLeaseData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["leased"]
    lease_epoch: int = Field(ge=1)
    lease_expires_at: str
    event: FeatureReferenceReconciliationEventData
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


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


class FeatureReferenceReconciliationSubscriptionProvisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_event_sequence: int = Field(ge=0, le=0)


class FeatureReferenceReconciliationSubscriptionProvisionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["provisioned"]
    principal_id: Literal["service:feature-reference-reconciliation"]
    initial_event_sequence: int = Field(ge=0)


class FeatureReferenceReconciliationSubscriptionProvisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: FeatureReferenceReconciliationSubscriptionProvisionData
    meta: Meta


class ManualProviderDedupFeatureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    feature_uuid: UUID
    row_revision: int = Field(ge=1)
    snapshot: dict[str, Any]


class ManualProviderDedupScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scorer_id: str
    scorer_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    name_score: float = Field(ge=0, le=1)
    spatial_score: float = Field(ge=0, le=1)
    category_score: float = Field(ge=0, le=1)
    total_score: float = Field(ge=0, le=1)
    distance_meters: float = Field(ge=0)


class ManualProviderDedupCaseData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    status: Literal["pending", "terminal"]
    created_at: datetime
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    manual_feature: ManualProviderDedupFeatureEvidence
    provider_feature: ManualProviderDedupFeatureEvidence
    scores: ManualProviderDedupScores


class ManualProviderDedupCasePageData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ManualProviderDedupCaseData]
    next_after_created_at: datetime | None
    next_after_case_id: UUID | None


class ManualProviderDedupCasePageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ManualProviderDedupCasePageData
    meta: Meta


class FeatureReferenceReconciliationAckAuditData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    command_id: int = Field(ge=1)
    acked_at: datetime


class FeatureReferenceReconciliationSubscriptionDeliveryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    initial_event_sequence: int = Field(ge=0)
    acked_through_sequence: int = Field(ge=0)
    lease_epoch: int = Field(ge=0)
    lease_expires_at: datetime | None
    oldest_unacked_at: datetime | None
    ack: FeatureReferenceReconciliationAckAuditData | None


class ManualProviderDedupCaseDetailData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    status: Literal["pending", "terminal"]
    created_at: datetime
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    manual_feature: dict[str, Any]
    provider_feature: dict[str, Any]
    scores: dict[str, Any]
    resolution: dict[str, Any] | None
    event: FeatureReferenceReconciliationEventData | None
    subscriptions: list[FeatureReferenceReconciliationSubscriptionDeliveryData]


class ManualProviderDedupCaseDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ManualProviderDedupCaseDetailData
    meta: Meta


class ManualProviderDedupCaseDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["kept", "merged", "manual_retired"]
    expected_case_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_manual_row_revision: int = Field(ge=1)
    expected_provider_row_revision: int = Field(ge=1)
    survivor_feature_id: str | None = Field(default=None, min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _survivor_matches_decision(self) -> ManualProviderDedupCaseDecisionInput:
        if self.decision == "merged" and self.survivor_feature_id is None:
            raise ValueError("merged decision에는 survivor_feature_id가 필요합니다.")
        if self.decision != "merged" and self.survivor_feature_id is not None:
            raise ValueError("merged 이외 decision에는 survivor_feature_id를 둘 수 없습니다.")
        return self


class ManualProviderDedupCaseDecisionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["kept", "merged", "manual_retired"]
    resolution_id: UUID
    event_id: UUID | None
    manual_feature_id: str
    manual_feature_row_revision: int = Field(ge=1)


class ManualProviderDedupCaseDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: ManualProviderDedupCaseDecisionData
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
            or receipt.action not in {"rebind", "detach"}
            or receipt.event_payload is None
            or receipt.event_sha256 is None
            or receipt.occurred_at is None
            or receipt.lease_epoch is None
            or receipt.lease_expires_at is None
        ):
            raise reconciliation_repo.FeatureReferenceReconciliationError(
                "leased receipt가 불완전합니다."
            )
        event = FeatureReferenceReconciliationEventData.model_validate(receipt.event_payload)
    return FeatureReferenceReconciliationLeaseData(
        outcome="leased",
        lease_epoch=cast(int, receipt.lease_epoch),
        lease_expires_at=cast(datetime, receipt.lease_expires_at).isoformat(),
        event=event,
        event_sha256=receipt.event_sha256,
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


def _subscription_provision_conflict_body(request: Request) -> dict[str, Any]:
    return {
        "type": "https://kor-travel-map/errors/feature-reference-reconciliation-subscription-exists",
        "title": "Feature 참조 reconciliation subscription이 이미 있습니다.",
        "status": status.HTTP_409_CONFLICT,
        "detail": "기존 immutable initial cursor를 바꾸지 않습니다.",
        "code": "FEATURE_REFERENCE_RECONCILIATION_SUBSCRIPTION_EXISTS",
        "request_id": request_id(request),
        "errors": [],
    }


@service_router.get(
    "",
    response_model=FeatureReferenceReconciliationLeaseResponse,
    responses={
        204: {"description": "unacknowledged event 없음"},
        409: {"description": "다른 worker의 유효한 lease가 존재"},
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
) -> FeatureReferenceReconciliationLeaseResponse | Response:
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
    except reconciliation_repo.FeatureReferenceReconciliationUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "FEATURE_REFERENCE_RECONCILIATION_UNAVAILABLE",
                "message": str(error),
                "details": {},
            },
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
    if receipt.outcome == "not_ready":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "FEATURE_REFERENCE_RECONCILIATION_UNAVAILABLE",
                "message": (
                    "Feature 참조 reconciliation subscription이 아직 provision되지 않았습니다."
                ),
                "details": {},
            },
        )
    if receipt.outcome == "empty":
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if receipt.outcome == "lease_conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "FEATURE_REFERENCE_RECONCILIATION_LEASE_CONFLICT",
                "message": "다른 worker가 reconciliation lease를 보유하고 있습니다.",
                "details": {},
            },
        )
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
        200: {
            "headers": {
                "Idempotency-Replayed": {
                    "description": "기존 ACK receipt를 replay했을 때 true.",
                    "schema": {"type": "string", "enum": ["true"]},
                }
            }
        },
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
            command_payload = {"event_id": str(event_id), **body.model_dump(mode="json")}
            await preflight_domain_command_claim(
                session,
                actor=context.actor,
                operation="service.feature-reference-reconciliation.ack.v1",
                idempotency_key=idempotency_key,
                payload=command_payload,
            )
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
                payload=command_payload,
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
    except reconciliation_repo.FeatureReferenceReconciliationUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "FEATURE_REFERENCE_RECONCILIATION_UNAVAILABLE",
                "message": str(error),
                "details": {},
            },
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


@activation_router.post(
    "",
    response_model=FeatureReferenceReconciliationSubscriptionProvisionResponse,
    responses={
        200: {
            "headers": {
                "Idempotency-Replayed": {
                    "description": "동일 provision receipt를 replay했을 때 true.",
                    "schema": {"type": "string", "enum": ["true"]},
                }
            }
        },
        403: {"description": "AdminBFF 거부"},
        409: {
            "description": "subscription이 이미 있어 initial cursor를 변경할 수 없음",
            "headers": {
                "Idempotency-Replayed": {
                    "description": "동일 conflict receipt를 replay했을 때 true.",
                    "schema": {"type": "string", "enum": ["true"]},
                }
            },
        },
        422: {"description": "initial cursor 입력 오류"},
    },
)
async def provision_feature_reference_reconciliation_subscription_route(
    body: FeatureReferenceReconciliationSubscriptionProvisionInput,
    request: Request,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureReferenceReconciliationSubscriptionProvisionResponse | JSONResponse:
    """paired consumer의 immutable initial cursor를 admin receipt로 한 번만 등록한다."""

    started_at = perf_counter()
    principal_id = "service:feature-reference-reconciliation"
    payload = body.model_dump(mode="json") | {"principal_id": principal_id}
    try:
        async with session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            command = await begin_domain_command(
                session,
                actor=context.actor,
                operation="admin.feature-reference-reconciliation-subscription.provision.v1",
                idempotency_key=idempotency_key,
                payload=payload,
            )
            receipt = (
                await reconciliation_repo.provision_feature_reference_reconciliation_subscription(
                    session,
                    principal_id=principal_id,
                    initial_event_sequence=body.initial_event_sequence,
                    actor=context.actor,
                    command_id=command.command_id,
                )
            )
            if receipt.initial_event_sequence is None:
                raise reconciliation_repo.FeatureReferenceReconciliationError(
                    "subscription provision receipt가 불완전합니다."
                )
            if receipt.outcome == "already_provisioned":
                conflict_body = _subscription_provision_conflict_body(request)
                result: (
                    FeatureReferenceReconciliationSubscriptionProvisionResponse | JSONResponse
                ) = JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content=conflict_body,
                    media_type="application/problem+json",
                )
                await complete_domain_command(
                    session,
                    command=command,
                    response=conflict_body,
                    status_code=status.HTTP_409_CONFLICT,
                    response_headers={"Content-Type": "application/problem+json"},
                )
            else:
                result = FeatureReferenceReconciliationSubscriptionProvisionResponse(
                    data=FeatureReferenceReconciliationSubscriptionProvisionData(
                        outcome="provisioned",
                        principal_id=principal_id,
                        initial_event_sequence=receipt.initial_event_sequence,
                    ),
                    meta=make_meta(request, started_at=started_at),
                )
                await complete_domain_command(session, command=command, response=result)
    except reconciliation_repo.FeatureReferenceReconciliationValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VALIDATION_ERROR", "message": str(error), "details": {}},
        ) from error
    except reconciliation_repo.FeatureReferenceReconciliationUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "FEATURE_REFERENCE_RECONCILIATION_UNAVAILABLE",
                "message": str(error),
                "details": {},
            },
        ) from error
    except reconciliation_repo.FeatureReferenceReconciliationError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INTERNAL_ERROR",
                "message": (
                    "Feature 참조 reconciliation subscription을 등록하는 중 내부 오류가 "
                    "발생했습니다."
                ),
                "details": {},
            },
        ) from error
    return result


def _case_data(
    item: reconciliation_repo.ManualProviderDedupCase,
) -> ManualProviderDedupCaseData:
    return ManualProviderDedupCaseData(
        case_id=item.case_id,
        status=item.status,
        created_at=item.created_at,
        evidence_fingerprint=item.evidence_fingerprint,
        manual_feature=dict(item.manual_feature),
        provider_feature=dict(item.provider_feature),
        scores=dict(item.scores),
    )


def _case_detail_data(
    item: reconciliation_repo.ManualProviderDedupCaseDetail,
) -> ManualProviderDedupCaseDetailData:
    """procedure JSON을 typed admin evidence response로 fail-closed 변환한다."""

    try:
        return ManualProviderDedupCaseDetailData.model_validate(item.data)
    except ValidationError as error:
        raise reconciliation_repo.FeatureReferenceReconciliationError(
            "manual/provider dedup case detail receipt가 내부 계약을 위반했습니다."
        ) from error


async def require_destructive_enabled_for_manual_provider_dedup_decision(
    request: Request,
) -> None:
    """merged/manual_retired의 kill-switch를 DB session보다 먼저 적용한다."""

    try:
        payload = await request.json()
    except ValueError:
        return
    if isinstance(payload, dict) and payload.get("decision") in {
        "merged",
        "manual_retired",
    }:
        require_admin_destructive_enabled(request)


@admin_router.get("", response_model=ManualProviderDedupCasePageResponse)
async def list_manual_provider_dedup_cases_route(
    request: Request,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[
        Literal["pending", "terminal"] | None,
        Query(alias="status"),
    ] = "pending",
    after_created_at: datetime | None = None,
    after_case_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ManualProviderDedupCasePageResponse:
    """admin BFF가 immutable M05 case의 stable keyset page를 읽는다."""

    del context
    if (after_created_at is None) != (after_case_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "after_created_at와 after_case_id는 함께 지정해야 합니다.",
                "details": {},
            },
        )
    started_at = perf_counter()
    try:
        items = await reconciliation_repo.list_manual_provider_dedup_cases(
            session,
            status=status_filter,
            after_created_at=after_created_at,
            after_case_id=after_case_id,
            limit=limit,
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
                "message": "manual/provider dedup case 목록을 읽는 중 내부 오류가 발생했습니다.",
                "details": {},
            },
        ) from error
    data = [_case_data(item) for item in items]
    final = data[-1] if data else None
    return ManualProviderDedupCasePageResponse(
        data=ManualProviderDedupCasePageData(
            items=data,
            next_after_created_at=final.created_at if final is not None else None,
            next_after_case_id=final.case_id if final is not None else None,
        ),
        meta=make_meta(request, started_at=started_at, page_size=limit),
    )


@admin_router.get(
    "/{case_id}",
    response_model=ManualProviderDedupCaseDetailResponse,
    responses={404: {"description": "manual/provider dedup case 없음"}},
)
async def get_manual_provider_dedup_case_route(
    case_id: UUID,
    request: Request,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ManualProviderDedupCaseDetailResponse:
    """case의 immutable evidence, resolution/event, subscription delivery 상태를 읽는다."""

    del context
    started_at = perf_counter()
    try:
        item = await reconciliation_repo.get_manual_provider_dedup_case(session, case_id=case_id)
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
                "message": "manual/provider dedup case를 읽는 중 내부 오류가 발생했습니다.",
                "details": {},
            },
        ) from error
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "MANUAL_PROVIDER_DEDUP_CASE_NOT_FOUND",
                "message": "manual/provider dedup case를 찾을 수 없습니다.",
                "details": {},
            },
        )
    return ManualProviderDedupCaseDetailResponse(
        data=_case_detail_data(item), meta=make_meta(request, started_at=started_at)
    )


@admin_router.post(
    "/{case_id}/decisions",
    response_model=ManualProviderDedupCaseDecisionResponse,
    responses={
        403: {"description": "AdminBFF 또는 destructive decision kill-switch 거부"},
        409: {
            "description": "stale evidence 또는 Idempotency-Key 충돌",
            "headers": {
                "Idempotency-Replayed": {
                    "description": "동일 stale receipt를 replay했을 때 true.",
                    "schema": {"type": "string", "enum": ["true"]},
                }
            },
        },
        422: {"description": "decision 입력 오류"},
        503: {"description": "paired reconciliation subscription이 아직 활성화되지 않음"},
    },
    dependencies=[Depends(require_destructive_enabled_for_manual_provider_dedup_decision)],
)
async def resolve_manual_provider_dedup_case_route(
    case_id: UUID,
    body: ManualProviderDedupCaseDecisionInput,
    request: Request,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ManualProviderDedupCaseDecisionResponse | JSONResponse:
    """admin decision과 immutable resolution/event를 같은 command transaction으로 확정한다."""

    started_at = perf_counter()
    command_payload = body.model_dump(mode="json") | {"case_id": str(case_id)}
    try:
        async with session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            command = await begin_domain_command(
                session,
                actor=context.actor,
                operation="admin.manual-provider-dedup-case.resolve.v1",
                idempotency_key=idempotency_key,
                payload=command_payload,
            )
            receipt = await reconciliation_repo.resolve_manual_provider_dedup_case(
                session,
                case_id=case_id,
                decision=body.decision,
                expected_case_fingerprint=body.expected_case_fingerprint,
                expected_manual_row_revision=body.expected_manual_row_revision,
                expected_provider_row_revision=body.expected_provider_row_revision,
                survivor_feature_id=body.survivor_feature_id,
                reason=body.reason,
                actor=context.actor,
                command_id=command.command_id,
            )
            if receipt.outcome == "stale":
                stale_body = {
                    "type": "https://kor-travel-map/errors/stale-manual-provider-dedup-case",
                    "title": "manual/provider dedup case evidence가 stale입니다.",
                    "status": status.HTTP_409_CONFLICT,
                    "detail": "판정 전 증적이 현재 Feature/provider 상태와 일치하지 않습니다.",
                    "code": "STALE_MANUAL_PROVIDER_DEDUP_CASE",
                    "request_id": request_id(request),
                    "errors": [],
                }
                await complete_domain_command(
                    session,
                    command=command,
                    response=stale_body,
                    status_code=status.HTTP_409_CONFLICT,
                    response_headers={"Content-Type": "application/problem+json"},
                )
                result: ManualProviderDedupCaseDecisionResponse | JSONResponse = JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content=stale_body,
                    media_type="application/problem+json",
                )
            else:
                if (
                    receipt.resolution_id is None
                    or receipt.manual_feature_id is None
                    or receipt.manual_feature_row_revision is None
                    or (
                        receipt.outcome in {"merged", "manual_retired"} and receipt.event_id is None
                    )
                ):
                    raise reconciliation_repo.FeatureReferenceReconciliationError(
                        "manual/provider dedup decision receipt가 불완전합니다."
                    )
                result = ManualProviderDedupCaseDecisionResponse(
                    data=ManualProviderDedupCaseDecisionData(
                        outcome=receipt.outcome,
                        resolution_id=receipt.resolution_id,
                        event_id=receipt.event_id,
                        manual_feature_id=receipt.manual_feature_id,
                        manual_feature_row_revision=receipt.manual_feature_row_revision,
                    ),
                    meta=make_meta(request, started_at=started_at),
                )
                await complete_domain_command(session, command=command, response=result)
    except reconciliation_repo.FeatureReferenceReconciliationValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VALIDATION_ERROR", "message": str(error), "details": {}},
        ) from error
    except reconciliation_repo.FeatureReferenceReconciliationUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "FEATURE_REFERENCE_RECONCILIATION_UNAVAILABLE",
                "message": str(error),
                "details": {},
            },
        ) from error
    except reconciliation_repo.FeatureReferenceReconciliationError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "manual/provider dedup decision 처리 중 내부 오류가 발생했습니다.",
                "details": {},
            },
        ) from error
    return result
