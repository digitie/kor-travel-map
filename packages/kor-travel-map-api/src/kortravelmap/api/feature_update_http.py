"""Feature update application exception의 FastAPI adapter."""

from __future__ import annotations

from typing import Any, Final

from fastapi import HTTPException, status

from kortravelmap.api import feature_update_service

__all__ = ["LOCK_CONFLICT_RESPONSE", "to_http_exception"]

LOCK_CONFLICT_RESPONSE: Final[dict[int | str, dict[str, Any]]] = {
    409: {
        "description": "동일 scope 즉시 실행 lock 경합",
        "headers": {
            "Retry-After": {
                "description": "동일 scope lock 경합 시 재시도 대기 초.",
                "schema": {"type": "integer"},
            }
        },
    }
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
    if isinstance(exc, feature_update_service.SigunguResolverUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, feature_update_service.FeatureUpdateValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, feature_update_service.FeatureUpdateResolverError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="feature update request enqueue failed",
    )
