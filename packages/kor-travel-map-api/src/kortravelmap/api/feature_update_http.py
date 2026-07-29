"""Feature update application exception의 FastAPI adapter."""

from __future__ import annotations

from typing import Any, Final

from fastapi import HTTPException, status

from kortravelmap.api import feature_update_service

__all__ = ["FEATURE_UPDATE_CONFLICT_RESPONSES", "to_http_exception"]

FEATURE_UPDATE_CONFLICT_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    409: {
        "description": (
            "Idempotency-Key body 불일치, 동일 effective scope의 다른 활성 요청, "
            "dispatch 불가 상태 또는 "
            "LOCK_BUSY(이 경우에만 Retry-After header 포함)"
        ),
    },
}


def to_http_exception(
    exc: feature_update_service.FeatureUpdateServiceError,
) -> HTTPException:
    """Typed application exception을 기존 HTTP status/detail 계약으로 변환한다."""

    if isinstance(exc, feature_update_service.FeatureUpdateLockConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": str(exc),
                "details": {"retry_after_seconds": exc.retry_after_seconds},
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    if isinstance(exc, feature_update_service.FeatureUpdateIdempotencyConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": str(exc),
                "details": {
                    "idempotency_key": exc.idempotency_key,
                    "request_id": exc.request_id,
                },
            },
        )
    if isinstance(exc, feature_update_service.FeatureUpdateActiveScopeConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": str(exc),
                "details": {
                    "request_id": exc.request_id,
                    "status": exc.status,
                    "detail_url": (f"/v1/ops/pipeline/executions/update_request/{exc.request_id}"),
                },
            },
        )
    if isinstance(exc, feature_update_service.FeatureUpdateDispatchStateConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": str(exc),
                "details": {
                    "request_id": exc.request_id,
                    "status": exc.current_status,
                    "detail_url": (f"/v1/ops/pipeline/executions/update_request/{exc.request_id}"),
                },
            },
        )
    if isinstance(exc, feature_update_service.FeatureUpdateRequestNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, feature_update_service.SigunguResolverUnavailable):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "GEO_AUTH_NOT_CONFIGURED",
                "message": str(exc),
                "details": {},
            },
        )
    if isinstance(exc, feature_update_service.FeatureUpdateValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, feature_update_service.FeatureUpdateResolverError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "PROVIDER_ERROR",
                "message": str(exc),
                "details": {},
            },
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="feature update request enqueue failed",
    )
