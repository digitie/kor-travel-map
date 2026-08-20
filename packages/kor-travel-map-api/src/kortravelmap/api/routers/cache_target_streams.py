"""ADR-081 cache-target service, ops read, and admin recovery routes."""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from kortravelmap.core.cache_target_stream import (
    cache_target_source_fingerprint,
    make_active_cache_target_source,
    make_deleted_cache_target_source,
    validate_cache_target_external_system,
    validate_cache_target_key,
)
from pydantic import AfterValidator, BaseModel

from kortravelmap.api.auth import (
    AdminProxyContext,
    CacheTargetServicePrincipalContext,
    require_admin_destructive_enabled,
    require_admin_frontend,
    require_cache_target_service_principal,
    require_cache_target_service_scope,
)
from kortravelmap.api.cache_target_stream_schema import (
    CacheTargetAckRecord,
    CacheTargetAckRequest,
    CacheTargetAckResponse,
    CacheTargetAppliedReceipt,
    CacheTargetClaimRecord,
    CacheTargetClaimRequest,
    CacheTargetClaimResponse,
    CacheTargetDeadLetterDetailResponse,
    CacheTargetDeadLetterListData,
    CacheTargetDeadLetterListResponse,
    CacheTargetDeadLetterRecord,
    CacheTargetDeadLetterReplayRequest,
    CacheTargetDeliveryRecord,
    CacheTargetDeliveryResponse,
    CacheTargetEventRecord,
    CacheTargetNackRequest,
    CacheTargetOperationResponse,
    CacheTargetReconciliationBeginRequest,
    CacheTargetReconciliationCompletionRequest,
    CacheTargetReconciliationPreparing,
    CacheTargetReconciliationRequest,
    CacheTargetReconciliationRunning,
    CacheTargetReconciliationSealRequest,
    CacheTargetRecoveryOperationRecord,
    CacheTargetRefreshRequest,
    CacheTargetRefreshRequestRecord,
    CacheTargetRefreshRequestResponse,
    CacheTargetRestoreFenceRecord,
    CacheTargetRestoreFenceRequest,
    CacheTargetRestoreFenceResponse,
    CacheTargetSnapshotAdmissionProblem,
    CacheTargetSnapshotData,
    CacheTargetSnapshotMaterialCompactedProblem,
    CacheTargetSnapshotResponse,
    CacheTargetSnapshotRow,
    CacheTargetSnapshotStatus,
    CacheTargetSourceDeleteRequest,
    CacheTargetSourceMutationRecord,
    CacheTargetSourceMutationResponse,
    CacheTargetSourceReadResponse,
    CacheTargetSourceRecord,
    CacheTargetSourceUpsertRequest,
    CacheTargetStreamControlRecord,
    CacheTargetStreamControlResponse,
    CacheTargetStreamStatusListData,
    CacheTargetStreamStatusListResponse,
    CacheTargetStreamStatusRecord,
)
from kortravelmap.api.cache_target_stream_service import (
    CacheTargetStreamService,
    get_cache_target_stream_service,
    raise_for_cache_target_status,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.domain_command_service import (
    begin_domain_command,
    complete_domain_command,
    idempotent_domain_command,
)
from kortravelmap.api.response import Meta, make_meta
from kortravelmap.api.settings import CacheTargetServiceScope

__all__ = [
    "admin_router",
    "ops_router",
    "service_router",
]


_ExternalSystemPath = Annotated[
    str,
    AfterValidator(validate_cache_target_external_system),
    Path(
        min_length=1,
        max_length=112,
        description="Trimmed Unicode NFC canonical external system identity.",
    ),
]
_TargetKeyPath = Annotated[
    str,
    AfterValidator(validate_cache_target_key),
    Path(
        min_length=1,
        max_length=512,
        description="Trimmed Unicode NFC canonical cache target identity.",
    ),
]

service_router = APIRouter(
    prefix="/service",
    tags=["service-cache-target-streams"],
)
ops_router = APIRouter(
    prefix="/ops",
    tags=["ops-cache-target-streams"],
)
admin_router = APIRouter(
    prefix="/admin",
    tags=["admin-cache-target-streams"],
)

_MAX_VERSION = 9_223_372_036_854_775_807
_IF_MATCH_PARAMETER = {
    "name": "If-Match",
    "in": "header",
    "required": True,
    "description": "직전 GET/성공 응답의 raw strong ETag.",
    "schema": {"type": "string"},
}
_OPTIONAL_IF_MATCH_PARAMETER = {
    **_IF_MATCH_PARAMETER,
    "required": False,
}
_IF_NONE_MATCH_PARAMETER = {
    "name": "If-None-Match",
    "in": "header",
    "required": False,
    "description": "create-only command에는 정확히 `*`를 보낸다.",
    "schema": {"type": "string"},
}
_ETAG_RESPONSE_HEADER = {
    "ETag": {
        "description": "현재 resource의 raw strong entity tag.",
        "schema": {"type": "string"},
    }
}
_ASYNC_OPERATION_HEADERS = {
    "Location": {
        "description": "accepted recovery operation status URL.",
        "schema": {"type": "string"},
    },
    "Retry-After": {
        "description": "status URL 재조회 전 최소 대기 시간(초).",
        "schema": {"type": "integer"},
    },
}
_SNAPSHOT_RETRY_AFTER_HEADER = {
    "Retry-After": {
        "description": "snapshot 작업 재시도 전 최소 대기 시간(초).",
        "schema": {"type": "integer", "minimum": 1},
    }
}


def _http_error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: object | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
        headers=headers,
    )


def _getattr(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _meta(started_at: float) -> Meta:
    return make_meta(started_at=started_at)


def _strong_uuid_version(value: str, *, header_name: str) -> tuple[str, int]:
    if not (value.startswith('"') and value.endswith('"')):
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            f"{header_name}는 server canonical UUID+version strong ETag여야 합니다.",
        )
    parts = value[1:-1].rsplit(":", 1)
    if len(parts) != 2:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            f"{header_name}는 server canonical UUID+version strong ETag여야 합니다.",
        )
    try:
        target_id = str(UUID(parts[0]))
        version = int(parts[1])
    except ValueError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            f"{header_name}는 server canonical UUID+version strong ETag여야 합니다.",
        ) from exc
    canonical = f'"{target_id}:{version}"'
    if value != canonical or not 0 < version <= _MAX_VERSION:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            f"{header_name}는 server canonical UUID+version strong ETag여야 합니다.",
        )
    return target_id, version


def _strong_stream_version(
    value: str,
    *,
    external_system: str,
    header_name: str,
) -> int:
    if not (value.startswith('"') and value.endswith('"')):
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            f"{header_name}는 server canonical stream strong ETag여야 합니다.",
        )
    parts = value[1:-1].rsplit(":", 1)
    if len(parts) != 2:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            f"{header_name}는 server canonical stream strong ETag여야 합니다.",
        )
    stream_external_system, raw_version = parts
    try:
        version = int(raw_version)
    except ValueError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            f"{header_name}는 server canonical stream strong ETag여야 합니다.",
        ) from exc
    if f'"{stream_external_system}:{version}"' != value or not 0 < version <= _MAX_VERSION:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            f"{header_name}는 server canonical stream strong ETag여야 합니다.",
        )
    if stream_external_system != external_system:
        raise _http_error(
            status.HTTP_412_PRECONDITION_FAILED,
            "PRECONDITION_FAILED",
            "If-Match stream ETag가 요청 external_system과 다릅니다.",
        )
    return version


def _stream_entity_tag(external_system: str, control_version: int) -> str:
    return f'"{external_system}:{control_version}"'


def _single_header(request: Request, name: str) -> str | None:
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            f"{name}는 정확히 하나의 header line이어야 합니다.",
        )
    return values[0] if values else None


def _target_write_precondition(request: Request) -> tuple[bool, str | None, int | None]:
    if_none_match = _single_header(request, "if-none-match")
    if_match = _single_header(request, "if-match")
    if if_none_match is None and if_match is None:
        raise _http_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "PRECONDITION_REQUIRED",
            "create에는 If-None-Match: *, update에는 If-Match header가 필요합니다.",
        )
    if if_none_match is not None and if_match is not None:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "If-None-Match와 If-Match는 함께 보낼 수 없습니다.",
        )
    if if_none_match is not None:
        if if_none_match != "*":
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "VALIDATION_ERROR",
                "If-None-Match는 create-only `*`만 허용합니다.",
            )
        return True, None, None
    assert if_match is not None
    target_id, version = _strong_uuid_version(if_match, header_name="If-Match")
    return False, target_id, version


def _delete_precondition(request: Request) -> tuple[str, int]:
    if_match = _single_header(request, "if-match")
    if if_match is None:
        raise _http_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "PRECONDITION_REQUIRED",
            "If-Match header가 필요합니다.",
        )
    return _strong_uuid_version(if_match, header_name="If-Match")


def _stream_precondition(request: Request, *, external_system: str) -> int:
    if_match = _single_header(request, "if-match")
    if if_match is None:
        raise _http_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "PRECONDITION_REQUIRED",
            "If-Match header가 필요합니다.",
        )
    return _strong_stream_version(
        if_match,
        external_system=external_system,
        header_name="If-Match",
    )


def _stream_begin_precondition(
    request: Request,
    *,
    external_system: str,
) -> tuple[bool, int | None]:
    if_none_match = _single_header(request, "if-none-match")
    if_match = _single_header(request, "if-match")
    if if_none_match is None and if_match is None:
        raise _http_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "PRECONDITION_REQUIRED",
            "stream이 없으면 If-None-Match: *, 있으면 If-Match header가 필요합니다.",
        )
    if if_none_match is not None and if_match is not None:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "If-None-Match와 If-Match는 함께 보낼 수 없습니다.",
        )
    if if_none_match is not None:
        if if_none_match != "*":
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "VALIDATION_ERROR",
                "If-None-Match는 create-only `*`만 허용합니다.",
            )
        return True, None
    assert if_match is not None
    return False, _strong_stream_version(
        if_match,
        external_system=external_system,
        header_name="If-Match",
    )


def _reconciliation_precondition(request: Request, *, request_id: str) -> int:
    if_match = _single_header(request, "if-match")
    if if_match is None:
        raise _http_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "PRECONDITION_REQUIRED",
            "reconciliation If-Match header가 필요합니다.",
        )
    precondition_request_id, phase_version = _strong_uuid_version(
        if_match,
        header_name="If-Match",
    )
    if precondition_request_id != request_id:
        raise _http_error(
            status.HTTP_412_PRECONDITION_FAILED,
            "PRECONDITION_FAILED",
            "If-Match request_id가 seal 대상과 다릅니다.",
        )
    return phase_version


def _delivery_precondition(request: Request) -> tuple[str, int]:
    if_match = _single_header(request, "if-match")
    if if_match is None:
        raise _http_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "PRECONDITION_REQUIRED",
            "If-Match header가 필요합니다.",
        )
    return _strong_uuid_version(if_match, header_name="If-Match")


def _source_record(
    row: Any,
    *,
    external_system: str,
    target_key: str,
    fallback_fingerprint: str | None = None,
) -> CacheTargetSourceRecord:
    target = _getattr(row, "target")
    return CacheTargetSourceRecord(
        external_system=_getattr(row, "external_system", external_system),
        target_key=_getattr(row, "target_key", target_key),
        state=_getattr(row, "state", "active"),
        restore_epoch=_getattr(row, "restore_epoch"),
        source_generation=_getattr(row, "source_generation"),
        source_payload_fingerprint=_getattr(
            row,
            "source_payload_fingerprint",
            fallback_fingerprint,
        ),
        entity_tag=_getattr(row, "entity_tag") or _getattr(target, "entity_tag"),
        target_id=_getattr(row, "target_id") or _getattr(target, "target_id"),
        target_sequence=_getattr(row, "target_sequence"),
        occurred_at=_getattr(row, "occurred_at"),
        updated_at=_getattr(row, "updated_at"),
    )


def _source_mutation_record(
    row: Any,
    *,
    external_system: str,
    target_key: str,
    fallback_fingerprint: str,
) -> CacheTargetSourceMutationRecord:
    read_record = _source_record(
        row,
        external_system=external_system,
        target_key=target_key,
        fallback_fingerprint=fallback_fingerprint,
    )
    return CacheTargetSourceMutationRecord.model_validate(read_record.model_dump())


def _stream_control(row: Any) -> CacheTargetStreamControlRecord:
    external_system = _getattr(row, "external_system")
    control_version = _getattr(row, "control_version")
    default_state = "fenced" if _getattr(row, "fence_id") is not None else "active"
    active = _getattr(row, "active_reconciliation")
    active_record: (
        CacheTargetReconciliationPreparing | CacheTargetReconciliationRunning | None
    ) = None
    if active is not None:
        active_status = _getattr(active, "status")
        if active_status == "preparing":
            active_record = CacheTargetReconciliationPreparing(
                request_id=_getattr(active, "request_id"),
                status="preparing",
                restore_epoch=_getattr(active, "restore_epoch"),
                entity_tag=_getattr(active, "entity_tag"),
                stream_entity_tag=_getattr(active, "stream_entity_tag"),
                created_at=_getattr(active, "created_at"),
            )
        elif active_status == "running":
            active_record = CacheTargetReconciliationRunning(
                request_id=_getattr(active, "request_id"),
                status="running",
                snapshot_id=_getattr(active, "snapshot_id"),
                restore_epoch=_getattr(active, "restore_epoch"),
                count=_getattr(active, "count"),
                merkle_root=_getattr(active, "merkle_root"),
                high_watermark_cursor=_getattr(active, "high_watermark_cursor"),
                entity_tag=_getattr(active, "entity_tag"),
                stream_entity_tag=_getattr(active, "stream_entity_tag"),
                created_at=_getattr(active, "created_at"),
            )
        else:
            raise RuntimeError("active reconciliation status가 유효하지 않습니다.")
    return CacheTargetStreamControlRecord(
        external_system=external_system,
        restore_epoch=_getattr(row, "restore_epoch"),
        control_version=control_version,
        entity_tag=_getattr(row, "entity_tag")
        or _stream_entity_tag(external_system, control_version),
        state=_getattr(row, "state", _getattr(row, "status", default_state)),
        consumer_id=_getattr(row, "consumer_id"),
        blocked_event_id=_getattr(row, "blocked_event_id"),
        active_reconciliation=active_record,
        updated_at=_getattr(row, "updated_at"),
    )


def _restore_fence(row: Any) -> CacheTargetRestoreFenceRecord:
    control = _stream_control(row)
    return CacheTargetRestoreFenceRecord(
        **control.model_dump(),
        fence_id=_getattr(row, "fence_id"),
        previous_restore_epoch=_getattr(row, "previous_restore_epoch"),
        previous_control_version=_getattr(row, "previous_control_version"),
        invalidated_claim_count=_getattr(row, "invalidated_claim_count"),
        superseded_delivery_count=_getattr(row, "superseded_delivery_count"),
        superseded_reconciliation_count=_getattr(
            row,
            "superseded_reconciliation_count",
        ),
        superseded_reconciliation_request_id=_getattr(
            row,
            "superseded_reconciliation_request_id",
        ),
    )


def _event_scope(row: Any) -> str:
    event_scope = _getattr(row, "event_scope")
    if event_scope in {"target", "stream"}:
        return str(event_scope)
    return "stream" if _getattr(row, "event_type") == "cache_target.reconciled" else "target"


def _event_record(row: Any) -> CacheTargetEventRecord:
    event_scope = _event_scope(row)
    data = {
        "event_id": _getattr(row, "event_id"),
        "event_scope": event_scope,
        "event_type": _getattr(row, "event_type"),
        "external_system": _getattr(row, "external_system"),
        "restore_epoch": _getattr(row, "restore_epoch"),
        "relay_order": _getattr(row, "relay_order"),
        "cursor": _getattr(row, "cursor"),
        "source_payload_fingerprint": _getattr(row, "source_payload_fingerprint"),
        "payload_fingerprint": _getattr(row, "payload_fingerprint"),
        "payload": _getattr(row, "payload", {}),
        "occurred_at": _getattr(row, "occurred_at"),
    }
    if event_scope == "stream":
        data.update(
            {
                "target_key": None,
                "target_id": None,
                "source_generation": None,
                "target_sequence": None,
            }
        )
    else:
        data.update(
            {
                "target_key": _getattr(row, "target_key"),
                "target_id": _getattr(row, "target_id"),
                "source_generation": _getattr(row, "source_generation"),
                "target_sequence": _getattr(row, "target_sequence"),
            }
        )
    return CacheTargetEventRecord.model_validate(data)


def _dead_letter_record(row: Any) -> CacheTargetDeadLetterRecord:
    event = _getattr(row, "event", row)
    event_scope = _event_scope(event)
    return CacheTargetDeadLetterRecord(
        event_id=_getattr(event, "event_id"),
        event_scope=event_scope,
        event_type=_getattr(event, "event_type"),
        external_system=_getattr(event, "external_system"),
        relay_order=_getattr(event, "relay_order"),
        target_key=None if event_scope == "stream" else _getattr(event, "target_key"),
        target_id=None if event_scope == "stream" else _getattr(event, "target_id"),
        restore_epoch=_getattr(event, "restore_epoch"),
        source_generation=(
            None if event_scope == "stream" else _getattr(event, "source_generation")
        ),
        target_sequence=(
            None if event_scope == "stream" else _getattr(event, "target_sequence")
        ),
        attempt_count=_getattr(row, "attempt_count"),
        error_class=_getattr(row, "error_class"),
        error_code=_getattr(row, "error_code"),
        payload_fingerprint=_getattr(event, "payload_fingerprint"),
        delivery_version=_getattr(row, "delivery_version"),
        entity_tag=_getattr(row, "entity_tag"),
        occurred_at=_getattr(event, "occurred_at"),
        updated_at=_getattr(row, "updated_at"),
    )


def _dead_letter_external_system(row: Any) -> str | None:
    event = _getattr(row, "event", row)
    external_system = _getattr(event, "external_system")
    return external_system if isinstance(external_system, str) else None


def _operation_record(row: Any) -> CacheTargetRecoveryOperationRecord:
    return CacheTargetRecoveryOperationRecord(
        operation_id=str(_getattr(row, "operation_id")),
        status=_getattr(row, "status", "accepted"),
        snapshot_id=_getattr(row, "snapshot_id"),
        status_url=_getattr(row, "status_url"),
        entity_tag=_getattr(row, "entity_tag"),
        stream_entity_tag=_getattr(row, "stream_entity_tag"),
    )


def _operation_record_from_result(
    row: Any,
    *,
    operation_id: str,
) -> CacheTargetRecoveryOperationRecord:
    status_url = _getattr(row, "status_url") or f"/v1/ops/cache-target-operations/{operation_id}"
    return CacheTargetRecoveryOperationRecord(
        operation_id=str(_getattr(row, "operation_id", operation_id)),
        status=_getattr(row, "operation_status", "accepted"),
        snapshot_id=_getattr(row, "snapshot_id"),
        status_url=status_url,
        entity_tag=_getattr(row, "entity_tag"),
        stream_entity_tag=_getattr(row, "stream_entity_tag"),
    )


def _set_etag(response: Response, record: BaseModel) -> None:
    value = getattr(record, "entity_tag", None)
    if isinstance(value, str) and value:
        response.headers["ETag"] = value


def _async_headers(row: Any, *, default_retry_after: int) -> dict[str, str]:
    headers: dict[str, str] = {}
    status_url = _getattr(row, "status_url")
    if isinstance(status_url, str) and status_url:
        headers["Location"] = status_url
    retry_after = _getattr(row, "retry_after_seconds", default_retry_after)
    headers["Retry-After"] = str(retry_after)
    return headers


def _set_async_headers(response: Response, row: Any, *, default_retry_after: int) -> None:
    response.headers.update(_async_headers(row, default_retry_after=default_retry_after))


def _require_bound_consumer(
    context: CacheTargetServicePrincipalContext,
    consumer_id: str,
) -> None:
    if consumer_id != context.consumer_id:
        raise _http_error(
            status.HTTP_403_FORBIDDEN,
            "CACHE_TARGET_CONSUMER_FORBIDDEN",
            "body consumer_id가 token principal과 일치하지 않습니다.",
        )


async def _require_reconciliation_metadata_access(
    session: Any,
    stream_service: CacheTargetStreamService,
    *,
    request_id: str,
    context: CacheTargetServicePrincipalContext,
    scope: CacheTargetServiceScope,
) -> Any:
    require_cache_target_service_scope(context, scope=scope)
    metadata = await stream_service.get_cache_target_reconciliation(
        session,
        request_id=request_id,
    )
    if _getattr(metadata, "consumer_id") != context.consumer_id:
        raise _http_error(
            status.HTTP_403_FORBIDDEN,
            "CACHE_TARGET_CONSUMER_FORBIDDEN",
            "reconciliation request consumer가 token principal과 일치하지 않습니다.",
        )
    require_cache_target_service_scope(
        context,
        scope=scope,
        external_system=_getattr(metadata, "external_system"),
    )
    return metadata


@service_router.put(
    "/cache-targets/{external_system}/{target_key}",
    response_model=CacheTargetSourceMutationResponse,
    description="exact `cache-target:command` scope 전용 source upsert.",
    responses={
        200: {"description": "target source applied", "headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale If-Match"},
        428: {"description": "missing If-Match/If-None-Match"},
    },
    openapi_extra={
        "x-required-service-scope": "cache-target:command",
        "parameters": [_IF_NONE_MATCH_PARAMETER, _IF_MATCH_PARAMETER],
    },
)
async def put_service_cache_target(
    external_system: _ExternalSystemPath,
    target_key: _TargetKeyPath,
    body: CacheTargetSourceUpsertRequest,
    request: Request,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetSourceMutationResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(
        context,
        scope="cache-target:command",
        external_system=external_system,
    )
    create_only, expected_target_id, expected_lock_version = _target_write_precondition(
        request
    )
    try:
        source = make_active_cache_target_source(
            lon=body.coord.lon,
            lat=body.coord.lat,
            radius_km=body.radius_km,
            update_enabled=body.update_enabled,
        )
    except (TypeError, ValueError) as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            str(exc),
        ) from exc
    fingerprint = cache_target_source_fingerprint(source)
    async with session.begin():
        result = await stream_service.apply_cache_target_source(
            session,
            consumer_id=context.consumer_id,
            source_event_id=str(body.source_event_id),
            idempotency_key=str(idempotency_key),
            external_system=external_system,
            target_key=target_key,
            restore_epoch=body.restore_epoch,
            source_generation=body.source_generation,
            source=source,
            occurred_at=body.occurred_at,
            create_only=create_only,
            expected_target_id=expected_target_id,
            expected_lock_version=expected_lock_version,
        )
    raise_for_cache_target_status(result)
    record = _source_mutation_record(
        result,
        external_system=external_system,
        target_key=target_key,
        fallback_fingerprint=fingerprint,
    )
    _set_etag(response, record)
    return CacheTargetSourceMutationResponse(data=record, meta=_meta(started_at))


@service_router.get(
    "/cache-targets/{external_system}/{target_key}",
    response_model=CacheTargetSourceReadResponse,
    responses={
        200: {"description": "target source read", "headers": _ETAG_RESPONSE_HEADER},
        404: {"description": "target source not found"},
    },
    openapi_extra={"x-required-service-scope": "cache-target:read"},
)
async def get_service_cache_target(
    external_system: _ExternalSystemPath,
    target_key: _TargetKeyPath,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    include_deleted: Annotated[bool, Query()] = False,
) -> CacheTargetSourceReadResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(
        context,
        scope="cache-target:read",
        external_system=external_system,
    )
    row = await stream_service.get_cache_target_source(
        session,
        external_system=external_system,
        target_key=target_key,
        include_deleted=include_deleted,
    )
    if row is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "cache target source가 없습니다.",
        )
    record = _source_record(row, external_system=external_system, target_key=target_key)
    _set_etag(response, record)
    return CacheTargetSourceReadResponse(data=record, meta=_meta(started_at))


@service_router.delete(
    "/cache-targets/{external_system}/{target_key}",
    response_model=CacheTargetSourceMutationResponse,
    description="exact `cache-target:command` scope 전용 source tombstone 적용.",
    responses={
        200: {"description": "target tombstone applied", "headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale If-Match"},
        428: {"description": "missing If-Match"},
    },
    openapi_extra={
        "x-required-service-scope": "cache-target:command",
        "parameters": [_IF_MATCH_PARAMETER],
    },
)
async def delete_service_cache_target(
    external_system: _ExternalSystemPath,
    target_key: _TargetKeyPath,
    body: CacheTargetSourceDeleteRequest,
    request: Request,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetSourceMutationResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(
        context,
        scope="cache-target:command",
        external_system=external_system,
    )
    expected_target_id, expected_lock_version = _delete_precondition(request)
    source = make_deleted_cache_target_source()
    fingerprint = cache_target_source_fingerprint(source)
    async with session.begin():
        result = await stream_service.apply_cache_target_source(
            session,
            consumer_id=context.consumer_id,
            source_event_id=str(body.source_event_id),
            idempotency_key=str(idempotency_key),
            external_system=external_system,
            target_key=target_key,
            restore_epoch=body.restore_epoch,
            source_generation=body.source_generation,
            source=source,
            occurred_at=body.occurred_at,
            create_only=False,
            expected_target_id=expected_target_id,
            expected_lock_version=expected_lock_version,
        )
    raise_for_cache_target_status(result)
    record = _source_mutation_record(
        result,
        external_system=external_system,
        target_key=target_key,
        fallback_fingerprint=fingerprint,
    )
    _set_etag(response, record)
    return CacheTargetSourceMutationResponse(data=record, meta=_meta(started_at))


@service_router.get(
    "/cache-target-streams/{external_system}",
    response_model=CacheTargetStreamControlResponse,
    responses={200: {"headers": _ETAG_RESPONSE_HEADER}, 404: {"description": "stream 없음"}},
    openapi_extra={"x-required-service-scope": "cache-target:read"},
)
async def get_service_cache_target_stream(
    external_system: _ExternalSystemPath,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
) -> CacheTargetStreamControlResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(
        context,
        scope="cache-target:read",
        external_system=external_system,
    )
    row = await stream_service.get_cache_target_stream(
        session,
        external_system=external_system,
        consumer_id=context.consumer_id,
    )
    if row is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "stream이 없습니다.")
    record = _stream_control(row)
    _set_etag(response, record)
    return CacheTargetStreamControlResponse(data=record, meta=_meta(started_at))


@service_router.post(
    "/cache-target-streams/{external_system}/restore-fences",
    response_model=CacheTargetRestoreFenceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {
            "description": "exact Idempotency-Key replay",
            "model": CacheTargetRestoreFenceResponse,
            "headers": _ETAG_RESPONSE_HEADER,
        },
        201: {"description": "restore fence advanced", "headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale stream ETag"},
        428: {"description": "missing If-Match"},
    },
    openapi_extra={
        "x-required-service-scope": "cache-target:restore-fence",
        "parameters": [_IF_MATCH_PARAMETER],
    },
)
async def create_service_restore_fence(
    external_system: _ExternalSystemPath,
    body: CacheTargetRestoreFenceRequest,
    request: Request,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetRestoreFenceResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(
        context,
        scope="cache-target:restore-fence",
        external_system=external_system,
    )
    _require_bound_consumer(context, body.consumer_id)
    expected_control_version = _stream_precondition(
        request,
        external_system=external_system,
    )
    payload = {
        "external_system": external_system,
        "body": body.model_dump(mode="json"),
        "headers": {"If-Match": request.headers.get("if-match")},
    }
    async with session.begin():
        command = await begin_domain_command(
            session,
            actor=context.principal_id,
            operation="service.cache-target-restore-fence.create",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        result = await stream_service.advance_cache_target_restore_fence(
            session,
            external_system=external_system,
            consumer_id=context.consumer_id,
            command_id=command.command_id,
            expected_restore_epoch=body.expected_restore_epoch,
            expected_control_version=expected_control_version,
            reason=body.reason,
            request_fingerprint=command.request_fingerprint,
        )
        raise_for_cache_target_status(result)
        record = _restore_fence(result)
        response_body = CacheTargetRestoreFenceResponse(
            data=record,
            meta=_meta(started_at),
        )
        await complete_domain_command(
            session,
            command=command,
            response=response_body,
            # 최초 REST response는 decorator의 201을 그대로 반환한다. 단, ADR-081은
            # immutable receipt를 재생할 때 200을 요구한다. ledger에는 replay status만
            # 200으로 고정해야 global DomainCommandReplay handler가 이를 복원한다.
            status_code=status.HTTP_200_OK,
            response_headers={"ETag": record.entity_tag},
        )
    _set_etag(response, record)
    return response_body


@service_router.post(
    "/refresh-requests",
    response_model=CacheTargetRefreshRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    description="exact `cache-target:command` scope 전용 refresh request 생성.",
    responses={
        202: {
            "description": "refresh request accepted",
            "headers": _ASYNC_OPERATION_HEADERS,
        }
    },
    openapi_extra={"x-required-service-scope": "cache-target:command"},
)
async def create_service_refresh_request(
    body: CacheTargetRefreshRequest,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetRefreshRequestResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(
        context,
        scope="cache-target:command",
        external_system=body.external_system,
    )
    async with session.begin():
        result = await stream_service.create_refresh_request(
            session,
            principal_id=context.principal_id,
            consumer_id=context.consumer_id,
            idempotency_key=str(idempotency_key),
            external_system=body.external_system,
            target_keys=body.target_keys,
            reason=body.reason,
        )
    raise_for_cache_target_status(result)
    record = CacheTargetRefreshRequestRecord(
        request_id=_getattr(result, "request_id"),
        status=_getattr(result, "status", "queued"),
        status_url=_getattr(result, "status_url"),
        retry_after_seconds=_getattr(result, "retry_after_seconds"),
        created_at=_getattr(result, "created_at"),
        updated_at=_getattr(result, "updated_at"),
    )
    _set_async_headers(response, record, default_retry_after=5)
    return CacheTargetRefreshRequestResponse(data=record, meta=_meta(started_at))


@service_router.get(
    "/refresh-requests/{request_id}",
    response_model=CacheTargetRefreshRequestResponse,
    responses={404: {"description": "refresh request 없음"}},
    openapi_extra={"x-required-service-scope": "cache-target:read"},
)
async def get_service_refresh_request(
    request_id: Annotated[UUID, Path()],
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
) -> CacheTargetRefreshRequestResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(context, scope="cache-target:read")
    row = await stream_service.get_refresh_request(session, request_id=str(request_id))
    if row is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "refresh request가 없습니다.",
        )
    external_system = _getattr(row, "external_system")
    if isinstance(external_system, str):
        require_cache_target_service_scope(
            context,
            scope="cache-target:read",
            external_system=external_system,
        )
    record = CacheTargetRefreshRequestRecord(
        request_id=_getattr(row, "request_id", request_id),
        status=_getattr(row, "status"),
        status_url=_getattr(row, "status_url"),
        retry_after_seconds=_getattr(row, "retry_after_seconds"),
        created_at=_getattr(row, "created_at"),
        updated_at=_getattr(row, "updated_at"),
    )
    return CacheTargetRefreshRequestResponse(data=record, meta=_meta(started_at))


@service_router.post(
    "/cache-target-event-claims",
    response_model=CacheTargetClaimResponse,
    openapi_extra={"x-required-service-scope": "cache-target:claim"},
)
async def claim_service_cache_target_events(
    body: CacheTargetClaimRequest,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetClaimResponse:
    started_at = perf_counter()
    _require_bound_consumer(context, body.consumer_id)
    require_cache_target_service_scope(
        context,
        scope="cache-target:claim",
        external_system=body.external_system,
    )
    async with session.begin():
        claim = await stream_service.claim_cache_target_events(
            session,
            external_system=body.external_system,
            consumer_id=context.consumer_id,
            idempotency_key=str(idempotency_key),
            limit=body.limit,
            lease_seconds=body.lease_seconds,
        )
    if claim is None:
        return CacheTargetClaimResponse(data=None, meta=_meta(started_at))
    record = CacheTargetClaimRecord(
        claim_id=_getattr(claim, "claim_id"),
        external_system=_getattr(claim, "external_system"),
        consumer_id=_getattr(claim, "consumer_id"),
        lease_token=_getattr(claim, "lease_token"),
        status=_getattr(claim, "status"),
        first_relay_order=_getattr(claim, "first_relay_order"),
        last_relay_order=_getattr(claim, "last_relay_order"),
        acked_through=_getattr(claim, "acked_through"),
        lease_expires_at=_getattr(claim, "lease_expires_at"),
        events=[_event_record(event) for event in _getattr(claim, "events", [])],
        idempotent_replay=_getattr(claim, "idempotent_replay", False),
    )
    return CacheTargetClaimResponse(data=record, meta=_meta(started_at))


@service_router.post(
    "/cache-target-event-acks",
    response_model=CacheTargetAckResponse,
    openapi_extra={"x-required-service-scope": "cache-target:ack"},
)
async def ack_service_cache_target_events(
    body: CacheTargetAckRequest,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
) -> CacheTargetAckResponse:
    started_at = perf_counter()
    _require_bound_consumer(context, body.consumer_id)
    require_cache_target_service_scope(context, scope="cache-target:ack")
    applied = [
        receipt.model_dump(mode="json")
        if isinstance(receipt, CacheTargetAppliedReceipt)
        else receipt
        for receipt in body.applied
    ]
    try:
        async with session.begin():
            result = await stream_service.ack_cache_target_events(
                session,
                consumer_id=context.consumer_id,
                claim_id=str(body.claim_id),
                lease_token=str(body.lease_token),
                through_cursor=body.through_cursor,
                applied=applied,
            )
    except ValueError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            str(exc),
        ) from exc
    raise_for_cache_target_status(result)
    record = CacheTargetAckRecord(
        claim_id=_getattr(result, "claim_id", body.claim_id),
        consumer_id=_getattr(result, "consumer_id", context.consumer_id),
        acked_through=_getattr(result, "acked_through", body.through_cursor),
        accepted_count=_getattr(result, "applied_count", len(body.applied)),
        status=_getattr(result, "status", "acked"),
    )
    return CacheTargetAckResponse(data=record, meta=_meta(started_at))


@service_router.post(
    "/cache-target-event-nacks",
    response_model=CacheTargetDeliveryResponse,
    responses={409: {"headers": {"Retry-After": _ASYNC_OPERATION_HEADERS["Retry-After"]}}},
    openapi_extra={"x-required-service-scope": "cache-target:nack"},
)
async def nack_service_cache_target_event(
    body: CacheTargetNackRequest,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
) -> CacheTargetDeliveryResponse:
    started_at = perf_counter()
    _require_bound_consumer(context, body.consumer_id)
    require_cache_target_service_scope(
        context,
        scope="cache-target:nack",
        external_system=body.external_system,
    )
    try:
        async with session.begin():
            result = await stream_service.nack_cache_target_event(
                session,
                external_system=body.external_system,
                consumer_id=context.consumer_id,
                claim_id=str(body.claim_id),
                lease_token=str(body.lease_token),
                event_id=str(body.event_id),
                error_class=body.disposition,
                error_code=body.error_code or body.error_class,
                error_fingerprint=body.error_fingerprint,
                backoff_seconds=body.backoff_seconds,
                max_attempts=body.max_attempts,
            )
    except ValueError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            str(exc),
        ) from exc
    raise_for_cache_target_status(result)
    retry_after = _getattr(result, "retry_after_seconds")
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    record = CacheTargetDeliveryRecord(
        event_id=_getattr(result, "event_id", body.event_id),
        status=_getattr(result, "status"),
        relay_order=_getattr(result, "relay_order"),
        delivery_version=_getattr(result, "delivery_version"),
        entity_tag=_getattr(result, "entity_tag"),
        retry_after_seconds=retry_after,
    )
    return CacheTargetDeliveryResponse(data=record, meta=_meta(started_at))


@service_router.get(
    "/cache-target-event-dead-letters/{event_id}",
    response_model=CacheTargetDeadLetterDetailResponse,
    responses={200: {"headers": _ETAG_RESPONSE_HEADER}, 404: {"description": "dead letter 없음"}},
    openapi_extra={"x-required-service-scope": "cache-target:recovery-replay"},
)
async def get_service_cache_target_dead_letter(
    event_id: Annotated[UUID, Path()],
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
) -> CacheTargetDeadLetterDetailResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(context, scope="cache-target:recovery-replay")
    row = await stream_service.get_cache_target_dead_letter(
        session,
        event_id=str(event_id),
    )
    if row is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "dead letter가 없습니다.",
        )
    external_system = _dead_letter_external_system(row)
    if external_system is not None:
        require_cache_target_service_scope(
            context,
            scope="cache-target:recovery-replay",
            external_system=external_system,
        )
    record = _dead_letter_record(row)
    _set_etag(response, record)
    return CacheTargetDeadLetterDetailResponse(data=record, meta=_meta(started_at))


@service_router.post(
    "/cache-target-event-dead-letters/{event_id}/replays",
    response_model=CacheTargetDeliveryResponse,
    responses={
        200: {"description": "dead letter replayed", "headers": _ETAG_RESPONSE_HEADER},
        412: {"description": "stale delivery ETag"},
        428: {"description": "missing If-Match"},
    },
    openapi_extra={
        "x-required-service-scope": "cache-target:recovery-replay",
        "parameters": [_IF_MATCH_PARAMETER],
    },
)
async def replay_service_cache_target_dead_letter(
    event_id: Annotated[UUID, Path()],
    body: CacheTargetDeadLetterReplayRequest,
    request: Request,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetDeliveryResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(context, scope="cache-target:recovery-replay")
    expected_event_id, expected_delivery_version = _delivery_precondition(request)
    if expected_event_id != str(event_id):
        raise _http_error(
            status.HTTP_412_PRECONDITION_FAILED,
            "PRECONDITION_FAILED",
            "If-Match event_id가 replay 대상과 다릅니다.",
        )
    payload = {
        "event_id": str(event_id),
        "body": body.model_dump(mode="json"),
        "headers": {"If-Match": request.headers.get("if-match")},
    }
    async with session.begin():
        command = await begin_domain_command(
            session,
            actor=context.principal_id,
            operation="service.cache-target-dead-letter.replay",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        dead_letter = await stream_service.get_cache_target_dead_letter(
            session,
            event_id=str(event_id),
        )
        if dead_letter is None:
            raise _http_error(
                status.HTTP_404_NOT_FOUND,
                "NOT_FOUND",
                "dead letter가 없습니다.",
            )
        external_system = _dead_letter_external_system(dead_letter)
        if external_system is not None:
            require_cache_target_service_scope(
                context,
                scope="cache-target:recovery-replay",
                external_system=external_system,
            )
        result = await stream_service.replay_cache_target_dead_letter(
            session,
            event_id=str(event_id),
            expected_delivery_version=expected_delivery_version,
        )
        raise_for_cache_target_status(result)
        record = CacheTargetDeliveryRecord(
            event_id=_getattr(result, "event_id", event_id),
            status=_getattr(result, "status"),
            relay_order=_getattr(result, "relay_order"),
            delivery_version=_getattr(result, "delivery_version"),
            entity_tag=_getattr(result, "entity_tag"),
            retry_after_seconds=_getattr(result, "retry_after_seconds"),
        )
        response_body = CacheTargetDeliveryResponse(
            data=record,
            meta=_meta(started_at),
        )
        await complete_domain_command(
            session,
            command=command,
            response=response_body,
            status_code=status.HTTP_200_OK,
            response_headers={"ETag": record.entity_tag},
        )
    _set_etag(response, record)
    return response_body


@service_router.post(
    "/cache-target-reconciliations",
    response_model=CacheTargetOperationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {
            "description": "two-phase reconciliation begin",
            "headers": {
                **_ASYNC_OPERATION_HEADERS,
                **_ETAG_RESPONSE_HEADER,
            },
        },
        412: {"description": "stale stream ETag or unexpected stream state"},
        428: {"description": "missing If-Match/If-None-Match"},
    },
    openapi_extra={
        "x-required-service-scope": "cache-target:recovery",
        "parameters": [_IF_NONE_MATCH_PARAMETER, _OPTIONAL_IF_MATCH_PARAMETER],
    },
)
async def begin_service_cache_target_reconciliation(
    body: CacheTargetReconciliationBeginRequest,
    request: Request,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetOperationResponse:
    started_at = perf_counter()
    _require_bound_consumer(context, body.consumer_id)
    require_cache_target_service_scope(
        context,
        scope="cache-target:recovery",
        external_system=body.external_system,
    )
    create_only, expected_control_version = _stream_begin_precondition(
        request,
        external_system=body.external_system,
    )
    payload = {
        "body": body.model_dump(mode="json"),
        "headers": {
            "If-Match": request.headers.get("if-match"),
            "If-None-Match": request.headers.get("if-none-match"),
        },
    }
    async with session.begin():
        command = await begin_domain_command(
            session,
            actor=context.principal_id,
            operation="service.cache-target-reconciliation.begin",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        result = await stream_service.begin_cache_target_reconciliation(
            session,
            command_id=command.command_id,
            external_system=body.external_system,
            consumer_id=context.consumer_id,
            expected_restore_epoch=body.expected_restore_epoch,
            expected_control_version=expected_control_version,
            create_only=create_only,
            reason=body.reason,
        )
        raise_for_cache_target_status(result)
        record = _operation_record(result)
        response_body = CacheTargetOperationResponse(
            data=record,
            meta=_meta(started_at),
        )
        response_headers = _async_headers(record, default_retry_after=5)
        if record.entity_tag is not None:
            response_headers["ETag"] = record.entity_tag
        await complete_domain_command(
            session,
            command=command,
            response=response_body,
            status_code=status.HTTP_201_CREATED,
            response_headers=response_headers,
        )
    _set_async_headers(response, record, default_retry_after=5)
    if record.entity_tag is not None:
        response.headers["ETag"] = record.entity_tag
    return response_body


@service_router.post(
    "/cache-target-reconciliations/{request_id}/seals",
    response_model=CacheTargetOperationResponse,
    responses={
        200: {"description": "two-phase reconciliation sealed", "headers": _ETAG_RESPONSE_HEADER},
        413: {
            "model": CacheTargetSnapshotAdmissionProblem,
            "description": (
                "snapshot item 1,000,000개 또는 canonical material 512 MiB "
                "admission 상한을 초과함."
            )
        },
        503: {
            "description": "snapshot writer barrier 또는 materialization 제한 시간 초과.",
            "headers": _SNAPSHOT_RETRY_AFTER_HEADER,
        },
        412: {"description": "request ETag or checksum precondition failed"},
        428: {"description": "missing If-Match"},
    },
    openapi_extra={
        "x-required-service-scope": "cache-target:recovery",
        "parameters": [_IF_MATCH_PARAMETER],
    },
)
async def seal_service_cache_target_reconciliation(
    request_id: Annotated[UUID, Path()],
    body: CacheTargetReconciliationSealRequest,
    request: Request,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetOperationResponse:
    started_at = perf_counter()
    request_id_text = str(request_id)
    payload = {
        "request_id": request_id_text,
        "body": body.model_dump(mode="json"),
        "headers": {"If-Match": request.headers.get("if-match")},
    }
    async with session.begin():
        await _require_reconciliation_metadata_access(
            session,
            stream_service,
            request_id=request_id_text,
            context=context,
            scope="cache-target:recovery",
        )
        _require_bound_consumer(context, body.consumer_id)
        expected_phase_version = _reconciliation_precondition(
            request,
            request_id=request_id_text,
        )
        command = await begin_domain_command(
            session,
            actor=context.principal_id,
            operation="service.cache-target-reconciliation.seal",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        result = await stream_service.seal_cache_target_reconciliation(
            session,
            request_id=request_id_text,
            external_system=body.external_system,
            consumer_id=context.consumer_id,
            expected_phase_version=expected_phase_version,
            expected_restore_epoch=body.expected_restore_epoch,
            expected_item_count=body.expected_item_count,
            expected_merkle_root=body.expected_merkle_root,
        )
        raise_for_cache_target_status(result)
        record = _operation_record(result)
        response_body = CacheTargetOperationResponse(
            data=record,
            meta=_meta(started_at),
        )
        response_headers = {}
        if record.entity_tag is not None:
            response_headers["ETag"] = record.entity_tag
        await complete_domain_command(
            session,
            command=command,
            response=response_body,
            status_code=status.HTTP_200_OK,
            response_headers=response_headers,
        )
    if record.entity_tag is not None:
        response.headers["ETag"] = record.entity_tag
    return response_body


@service_router.post(
    "/cache-target-reconciliations/{request_id}/completions",
    response_model=CacheTargetOperationResponse,
    openapi_extra={"x-required-service-scope": "cache-target:snapshot"},
)
async def complete_service_cache_target_reconciliation(
    request_id: Annotated[UUID, Path()],
    body: CacheTargetReconciliationCompletionRequest,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetOperationResponse:
    started_at = perf_counter()
    request_id_text = str(request_id)
    payload = {
        "request_id": request_id_text,
        "body": body.model_dump(mode="json"),
    }
    async with session.begin():
        await _require_reconciliation_metadata_access(
            session,
            stream_service,
            request_id=request_id_text,
            context=context,
            scope="cache-target:snapshot",
        )
        _require_bound_consumer(context, body.consumer_id)
        command = await begin_domain_command(
            session,
            actor=context.principal_id,
            operation="service.cache-target-reconciliation.complete",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        result = await stream_service.complete_cache_target_reconciliation(
            session,
            request_id=request_id_text,
            external_system=body.external_system,
            consumer_id=context.consumer_id,
            snapshot_id=str(body.snapshot_id),
            expected_restore_epoch=body.expected_restore_epoch,
            actual_merkle_root=body.actual_merkle_root,
        )
        raise_for_cache_target_status(result)
        response_body = CacheTargetOperationResponse(
            data=_operation_record(result),
            meta=_meta(started_at),
        )
        await complete_domain_command(
            session,
            command=command,
            response=response_body,
            status_code=status.HTTP_200_OK,
        )
    return response_body


@service_router.get(
    "/cache-target-snapshots/{external_system}",
    response_model=CacheTargetSnapshotResponse,
    responses={
        413: {
            "model": CacheTargetSnapshotAdmissionProblem,
            "description": (
                "snapshot item 1,000,000개 또는 canonical material 512 MiB "
                "admission 상한을 초과함."
            )
        },
        # NOTE(T-VN-41S): 이 경로는 `410 SNAPSHOT_MATERIAL_COMPACTED`를 **실제로**
        # 낸다(generic/reconciliation receipt가 material을 공유하므로). 그런데 여기
        # 선언하면 service spec bytes가 바뀌어 PinVi vendor 재고정이 같은 호흡으로
        # 필요해진다 — paired receipt가 그것을 요구한다. 이 브랜치의 범위는 material/
        # receipt 정규화이므로 선언은 다음 PinVi re-vendor와 함께 묶는다
        # (`docs/tasks.md` T-VN-41S 잔여 항목). 누락 자체는 이 브랜치 이전부터 있었다.
        429: {
            "description": (
                "미만료·미참조 generic snapshot copy 상한 도달. 가장 오래된 "
                "snapshot 만료 뒤 재시도한다."
            ),
            "headers": {
                "Retry-After": {
                    "description": "가장 오래된 snapshot 만료까지의 DB 기준 대기 시간(초).",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 7_200},
                }
            },
        },
        503: {
            "description": (
                "snapshot 생성 경합, handoff TTL 부족, writer barrier 또는 "
                "materialization 제한 시간 초과."
            ),
            "headers": _SNAPSHOT_RETRY_AFTER_HEADER,
        },
    },
    openapi_extra={"x-required-service-scope": "cache-target:snapshot"},
)
async def get_service_cache_target_snapshot(
    external_system: _ExternalSystemPath,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    page_size: Annotated[int, Query(ge=1, le=1000)] = 500,
    cursor: Annotated[str | None, Query()] = None,
) -> CacheTargetSnapshotResponse:
    started_at = perf_counter()
    require_cache_target_service_scope(
        context,
        scope="cache-target:snapshot",
        external_system=external_system,
    )
    async with session.begin():
        page = await stream_service.get_cache_target_snapshot(
            session,
            external_system=external_system,
            limit=page_size,
            cursor=cursor,
        )
        raise_for_cache_target_status(page)
        return _snapshot_response(
            page,
            started_at=started_at,
            page_size=page_size,
        )


def _snapshot_response(
    page: Any,
    *,
    started_at: float,
    page_size: int,
) -> CacheTargetSnapshotResponse:
    data = CacheTargetSnapshotData(
        snapshot_id=_getattr(page, "snapshot_id"),
        restore_epoch=_getattr(page, "restore_epoch"),
        high_watermark_cursor=_getattr(page, "high_watermark_cursor"),
        count=_getattr(page, "count"),
        merkle_root=_getattr(page, "merkle_root"),
        created_at=_getattr(page, "created_at"),
        expires_at=_getattr(page, "expires_at"),
        items=[
            CacheTargetSnapshotRow(
                external_system=_getattr(row, "external_system"),
                target_key=_getattr(row, "target_key"),
                state=_getattr(row, "state"),
                source_generation=_getattr(row, "source_generation"),
                source_payload_fingerprint=_getattr(
                    row,
                    "source_payload_fingerprint",
                ),
            )
            for row in _getattr(page, "items", [])
        ],
    )
    return CacheTargetSnapshotResponse(
        data=data,
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=_getattr(page, "next_cursor"),
        ),
    )


@service_router.get(
    "/cache-target-reconciliations/{request_id}/snapshot",
    response_model=CacheTargetSnapshotResponse,
    responses={
        410: {
            "model": CacheTargetSnapshotMaterialCompactedProblem,
            "description": (
                "terminal audit 보존 기간 뒤 snapshot item material이 compact되어 "
                "header/root receipt만 남음."
            )
        }
    },
    openapi_extra={"x-required-service-scope": "cache-target:snapshot"},
)
async def get_service_cache_target_reconciliation_snapshot(
    request_id: Annotated[UUID, Path()],
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[
        CacheTargetServicePrincipalContext,
        Depends(require_cache_target_service_principal),
    ],
    page_size: Annotated[int, Query(ge=1, le=1000)] = 500,
    cursor: Annotated[str | None, Query()] = None,
) -> CacheTargetSnapshotResponse:
    started_at = perf_counter()
    await _require_reconciliation_metadata_access(
        session,
        stream_service,
        request_id=str(request_id),
        scope="cache-target:snapshot",
        context=context,
    )
    page = await stream_service.get_cache_target_reconciliation_snapshot(
        session,
        request_id=str(request_id),
        consumer_id=context.consumer_id,
        limit=page_size,
        cursor=cursor,
    )
    raise_for_cache_target_status(page)
    return _snapshot_response(
        page,
        started_at=started_at,
        page_size=page_size,
    )


@ops_router.get(
    "/cache-target-streams",
    response_model=CacheTargetStreamStatusListResponse,
)
async def list_ops_cache_target_streams(
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> CacheTargetStreamStatusListResponse:
    started_at = perf_counter()
    page = await stream_service.list_cache_target_stream_statuses(
        session,
        limit=page_size,
        cursor=cursor,
    )
    items: list[CacheTargetStreamStatusRecord] = []
    for row in _getattr(page, "items", []):
        snapshot = _getattr(row, "last_snapshot")
        items.append(
            CacheTargetStreamStatusRecord(
                external_system=_getattr(row, "external_system"),
                restore_epoch=_getattr(row, "restore_epoch"),
                control_version=_getattr(row, "control_version"),
                consumer_enabled=_getattr(row, "consumer_enabled"),
                state=_getattr(row, "state"),
                pending_count=_getattr(row, "pending_count"),
                leased_count=_getattr(row, "leased_count"),
                retry_count=_getattr(row, "retry_count"),
                dead_count=_getattr(row, "dead_count"),
                delivered_count=_getattr(row, "delivered_count"),
                superseded_count=_getattr(row, "superseded_count"),
                blocked_event_id=_getattr(row, "blocked_event_id"),
                last_snapshot=(
                    CacheTargetSnapshotStatus(
                        snapshot_id=_getattr(snapshot, "snapshot_id"),
                        count=_getattr(snapshot, "count"),
                        merkle_root=_getattr(snapshot, "merkle_root"),
                        high_watermark_cursor=_getattr(
                            snapshot,
                            "high_watermark_cursor",
                        ),
                        created_at=_getattr(snapshot, "created_at"),
                    )
                    if snapshot is not None
                    else None
                ),
                updated_at=_getattr(row, "updated_at"),
            )
        )
    return CacheTargetStreamStatusListResponse(
        data=CacheTargetStreamStatusListData(items=items),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=_getattr(page, "next_cursor"),
        ),
    )


@ops_router.get(
    "/cache-target-event-dead-letters",
    response_model=CacheTargetDeadLetterListResponse,
)
async def list_ops_cache_target_dead_letters(
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> CacheTargetDeadLetterListResponse:
    started_at = perf_counter()
    page = await stream_service.list_cache_target_dead_letters(
        session,
        limit=page_size,
        cursor=cursor,
    )
    return CacheTargetDeadLetterListResponse(
        data=CacheTargetDeadLetterListData(
            items=[_dead_letter_record(row) for row in _getattr(page, "items", [])],
        ),
        meta=make_meta(
            started_at=started_at,
            page_size=page_size,
            next_cursor=_getattr(page, "next_cursor"),
        ),
    )


@ops_router.get(
    "/cache-target-event-dead-letters/{event_id}",
    response_model=CacheTargetDeadLetterDetailResponse,
    responses={200: {"headers": _ETAG_RESPONSE_HEADER}, 404: {"description": "dead letter 없음"}},
)
async def get_ops_cache_target_dead_letter(
    event_id: Annotated[UUID, Path()],
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
) -> CacheTargetDeadLetterDetailResponse:
    started_at = perf_counter()
    row = await stream_service.get_cache_target_dead_letter(
        session,
        event_id=str(event_id),
    )
    if row is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "dead letter가 없습니다.",
        )
    record = _dead_letter_record(row)
    _set_etag(response, record)
    return CacheTargetDeadLetterDetailResponse(data=record, meta=_meta(started_at))


@ops_router.get(
    "/cache-target-operations/{operation_id}",
    response_model=CacheTargetOperationResponse,
    responses={404: {"description": "operation 없음"}},
)
async def get_ops_cache_target_operation(
    operation_id: Annotated[str, Path(min_length=1, max_length=128)],
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
) -> CacheTargetOperationResponse:
    started_at = perf_counter()
    row = await stream_service.get_cache_target_operation(
        session,
        operation_id=operation_id,
    )
    if row is None:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "cache target operation이 없습니다.",
        )
    return CacheTargetOperationResponse(data=_operation_record(row), meta=_meta(started_at))


@admin_router.post(
    "/cache-target-event-dead-letters/{event_id}/replays",
    response_model=CacheTargetOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin_destructive_enabled)],
    responses={
        202: {"description": "replay accepted", "headers": _ASYNC_OPERATION_HEADERS},
        412: {"description": "stale delivery ETag"},
        428: {"description": "missing If-Match"},
    },
    openapi_extra={"parameters": [_IF_MATCH_PARAMETER]},
)
@idempotent_domain_command("admin.cache-target-dead-letter.replay")
async def replay_admin_cache_target_dead_letter(
    event_id: Annotated[UUID, Path()],
    body: CacheTargetDeadLetterReplayRequest,
    request: Request,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
) -> CacheTargetOperationResponse:
    del body, context
    started_at = perf_counter()
    expected_event_id, expected_delivery_version = _delivery_precondition(request)
    if expected_event_id != str(event_id):
        raise _http_error(
            status.HTTP_412_PRECONDITION_FAILED,
            "CACHE_TARGET_DEAD_LETTER_STALE",
            "If-Match event_id가 replay 대상과 다릅니다.",
        )
    result = await stream_service.replay_cache_target_dead_letter(
        session,
        event_id=str(event_id),
        expected_delivery_version=expected_delivery_version,
    )
    raise_for_cache_target_status(result)
    record = _operation_record_from_result(result, operation_id=str(event_id))
    _set_async_headers(response, record, default_retry_after=3)
    return CacheTargetOperationResponse(data=record, meta=_meta(started_at))


@admin_router.post(
    "/cache-target-reconciliations",
    response_model=CacheTargetOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin_destructive_enabled)],
    responses={
        202: {"description": "reconciliation accepted", "headers": _ASYNC_OPERATION_HEADERS},
        413: {
            "model": CacheTargetSnapshotAdmissionProblem,
            "description": (
                "snapshot item 1,000,000개 또는 canonical material 512 MiB "
                "admission 상한을 초과함."
            )
        },
        503: {
            "description": "snapshot writer barrier 또는 materialization 제한 시간 초과.",
            "headers": _SNAPSHOT_RETRY_AFTER_HEADER,
        },
    },
)
async def request_admin_cache_target_reconciliation(
    body: CacheTargetReconciliationRequest,
    response: Response,
    session: Annotated[Any, Depends(get_session)],
    stream_service: Annotated[
        CacheTargetStreamService,
        Depends(get_cache_target_stream_service),
    ],
    context: Annotated[AdminProxyContext, Depends(require_admin_frontend)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CacheTargetOperationResponse:
    started_at = perf_counter()
    operation = "admin.cache-target-reconciliation.request"
    payload = {
        "external_system": body.external_system,
        "reason": body.reason,
    }
    async with session.begin():
        command = await begin_domain_command(
            session,
            actor=context.actor,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        result = await stream_service.request_cache_target_reconciliation(
            session,
            command_id=command.command_id,
            external_system=body.external_system,
            reason=body.reason,
        )
        raise_for_cache_target_status(result)
        record = _operation_record(result)
        response_body = CacheTargetOperationResponse(
            data=record,
            meta=_meta(started_at),
        )
        response_headers = _async_headers(result, default_retry_after=5)
        await complete_domain_command(
            session,
            command=command,
            response=response_body,
            status_code=status.HTTP_202_ACCEPTED,
            response_headers=response_headers,
        )
    response.headers.update(response_headers)
    return response_body
