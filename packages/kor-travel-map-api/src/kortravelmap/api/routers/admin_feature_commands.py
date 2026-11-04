"""미확정 Feature 명령의 동일 입력 조회와 부재 영구 중단."""

from __future__ import annotations

from inspect import signature, unwrap
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import AdminProxyContext, require_admin_frontend
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_registry import COMMAND_REGISTRY, CommandPolicy
from kortravelmap.api.domain_command_service import (
    DomainCommandPending,
    DomainCommandReplay,
    _route_payload,
    begin_domain_command,
    complete_domain_command,
)
from kortravelmap.api.http_revision import parse_revision_header
from kortravelmap.api.response import Meta, ProblemDetail, make_meta, request_id
from kortravelmap.api.routers.admin_features import (
    AdminFeatureDeleteRequest,
    AdminFeatureFieldOverrideResponse,
    AdminFeaturePatchRequest,
    AdminFeatureStateResponse,
    delete_feature_route,
    patch_feature_route,
)

router = APIRouter(prefix="/admin/feature-commands", tags=["admin-feature-commands"])
_ABANDONED = "DOMAIN_COMMAND_ABANDONED"


class _TargetCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_id: str = Field(min_length=1, max_length=255)
    expected_revision: str = Field(pattern=r'^"[1-9][0-9]*"$', max_length=21)
    idempotency_key: UUID
    expected_actor: str = Field(min_length=1, max_length=200)
    access_reason: str = Field(min_length=5, max_length=500)

    @field_validator("access_reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("조정 사유를 5자 이상 입력해 주세요.")
        return value


class FeaturePatchCommand(_TargetCommand):
    operation: Literal["admin.feature.patch"]
    payload: AdminFeaturePatchRequest


class FeatureDeleteCommand(_TargetCommand):
    operation: Literal["admin.feature.delete"]
    payload: AdminFeatureDeleteRequest


FeatureCommandReconcileRequest = Annotated[
    FeaturePatchCommand | FeatureDeleteCommand, Field(discriminator="operation")
]


class FeatureCommandResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["abandoned", "pending", "completed"]
    actor: str
    operation: Literal["admin.feature.patch", "admin.feature.delete"]
    idempotency_key: UUID
    feature_id: str
    request_fingerprint: str
    command_id: int = Field(ge=1)
    receipt: AdminFeatureFieldOverrideResponse | AdminFeatureStateResponse | None = None


class FeatureCommandResolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: FeatureCommandResolution
    meta: Meta


def _policy(command: FeaturePatchCommand | FeatureDeleteCommand) -> CommandPolicy:
    method = "PATCH" if isinstance(command, FeaturePatchCommand) else "DELETE"
    return COMMAND_REGISTRY[(method, "/v1/admin/features/{feature_id}")]


async def _original_payload(
    command: FeaturePatchCommand | FeatureDeleteCommand,
    *,
    actor: str,
) -> dict[str, object]:
    # 원래 경로의 signature·typed body를 그대로 쓰며 조정 사유와 actor assertion은 넣지 않는다.
    function = (
        patch_feature_route if isinstance(command, FeaturePatchCommand) else delete_feature_route
    )
    original = unwrap(function)
    request = Request(
        {
            "type": "http",
            "headers": [(b"if-match", command.expected_revision.encode("ascii"))],
        }
    )
    parse_revision_header(request, "If-Match", required=True)
    policy = _policy(command)
    return await _route_payload(
        signature(original),
        (),
        {
            "feature_id": command.feature_id,
            "body": command.payload,
            "request": request,
            "response": Response(),
            "context": AdminProxyContext(actor=actor),
            "session": None,
        },
        fingerprint_headers=policy.fingerprint_headers,
        fingerprint_version=policy.fingerprint_version,
    )


async def reconcile_feature_command(
    session: AsyncSession,
    command: FeaturePatchCommand | FeatureDeleteCommand,
    *,
    actor: str,
    correlation_id: str,
) -> FeatureCommandResolution:
    # 다른 인증 actor의 빈 namespace는 원래 명령 부재의 증거가 아니다.
    if command.expected_actor != actor:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "COMMAND_ACTOR_MISMATCH",
                "message": "원래 명령의 운영자와 현재 인증 운영자가 다릅니다.",
            },
        )
    payload = await _original_payload(command, actor=actor)
    version = _policy(command).fingerprint_version
    state: Literal["abandoned", "pending", "completed"]
    receipt: AdminFeatureFieldOverrideResponse | AdminFeatureStateResponse | None = None
    async with session.begin():
        try:
            handle = await begin_domain_command(
                session,
                actor=actor,
                operation=command.operation,
                idempotency_key=command.idempotency_key,
                payload=payload,
                fingerprint_version=version,
            )
        except DomainCommandPending as exc:
            command_id = exc.claim.command_id
            fingerprint = exc.claim.request_fingerprint
            state = "pending"
        except DomainCommandReplay as exc:
            record = exc.record
            command_id = record.command_id
            fingerprint = record.request_fingerprint
            if record.response_status == 409 and record.response_body.get("code") == _ABANDONED:
                state = "abandoned"
            elif record.response_status == 200:
                schema = (
                    AdminFeatureFieldOverrideResponse
                    if isinstance(command, FeaturePatchCommand)
                    else AdminFeatureStateResponse
                )
                try:
                    receipt = schema.model_validate(record.response_body)
                except ValidationError as error:
                    raise HTTPException(
                        status_code=503,
                        detail={
                            "code": "COMMAND_RECEIPT_UNVERIFIABLE",
                            "message": "저장된 명령 결과를 검증하지 못했습니다.",
                        },
                    ) from error
                state = "completed"
            else:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "COMMAND_RECEIPT_UNVERIFIABLE",
                        "message": "지원하지 않는 저장 명령 결과입니다.",
                    },
                ) from exc
        else:
            command_id = handle.command_id
            fingerprint = handle.request_fingerprint
            message = "이 명령은 실행 기록이 없음을 확인하고 영구 중단했습니다."
            problem = ProblemDetail(
                type="https://kor-travel-map/errors/domain-command-abandoned",
                title=message,
                status=409,
                detail=message,
                code=_ABANDONED,
                request_id=correlation_id,
                details={
                    "resolution_reason": command.access_reason,
                    "feature_id": command.feature_id,
                    "actor": actor,
                    "operation": command.operation,
                    "idempotency_key": str(command.idempotency_key),
                },
            )
            await complete_domain_command(
                session,
                command=handle,
                response=problem,
                status_code=409,
            )
            state = "abandoned"
    # 부재 claim과 terminal 중단을 커밋한 뒤에만 ABANDONED를 응답한다.
    return FeatureCommandResolution(
        state=state,
        actor=actor,
        operation=command.operation,
        idempotency_key=command.idempotency_key,
        feature_id=command.feature_id,
        request_fingerprint=fingerprint,
        command_id=command_id,
        receipt=receipt,
    )


@router.post("/reconcile", response_model=FeatureCommandResolutionResponse)
async def reconcile_feature_command_endpoint(
    body: FeatureCommandReconcileRequest,
    request: Request,
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeatureCommandResolutionResponse:
    started = perf_counter()
    result = await reconcile_feature_command(
        session,
        body,
        actor=context.actor,
        correlation_id=request_id(request),
    )
    return FeatureCommandResolutionResponse(data=result, meta=make_meta(started_at=started))
