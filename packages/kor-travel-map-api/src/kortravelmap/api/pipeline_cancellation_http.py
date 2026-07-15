"""Pipeline cancellation application exception의 FastAPI adapter."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from kortravelmap.api import pipeline_cancellation_service

__all__ = ["error_responses", "to_http_exception"]


def error_responses(
    *,
    not_found_description: str,
) -> dict[int | str, dict[str, Any]]:
    """공개 cancellation operation이 공유하는 OpenAPI 오류 계약."""
    retry_after = {
        "description": "재시도 가능한 오류일 때 적용할 대기 시간(초).",
        "schema": {"type": "integer"},
    }
    return {
        404: {"description": not_found_description},
        409: {
            "description": "동시 취소 또는 안전한 reconcile 불가",
            "headers": {"Retry-After": retry_after},
        },
        502: {
            "description": "Dagster terminate 실패",
            "headers": {"Retry-After": retry_after},
        },
        503: {
            "description": "Dagster 연결 또는 terminal 확인 실패",
            "headers": {"Retry-After": retry_after},
        },
    }


def _details(
    exc: pipeline_cancellation_service.PipelineCancellationServiceError,
) -> dict[str, Any] | None:
    if exc.detail is not None:
        return exc.detail.model_dump(mode="json")
    if exc.root is not None:
        return {
            "root": exc.root.model_dump(mode="json"),
            "cancellation": None,
        }
    return None


def _exception(
    exc: pipeline_cancellation_service.PipelineCancellationServiceError,
    *,
    status_code: int,
    retryable: bool = False,
) -> HTTPException:
    headers = None
    if retryable and exc.retry_after_seconds is not None:
        headers = {"Retry-After": str(exc.retry_after_seconds)}
    return HTTPException(
        status_code=status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "details": _details(exc),
        },
        headers=headers,
    )


def to_http_exception(
    exc: pipeline_cancellation_service.PipelineCancellationServiceError,
) -> HTTPException:
    """Typed cancellation error를 RFC7807 handler 입력으로 변환한다."""
    if isinstance(exc, pipeline_cancellation_service.PipelineExecutionNotFound):
        return _exception(exc, status_code=status.HTTP_404_NOT_FOUND)
    if isinstance(exc, pipeline_cancellation_service.PipelineCancellationInProgress):
        return _exception(
            exc,
            status_code=status.HTTP_409_CONFLICT,
            retryable=True,
        )
    if isinstance(exc, pipeline_cancellation_service.PipelineCancellationUnsafe):
        return _exception(exc, status_code=status.HTTP_409_CONFLICT)
    if isinstance(exc, pipeline_cancellation_service.DagsterTerminateFailed):
        return _exception(
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
            retryable=True,
        )
    if isinstance(exc, pipeline_cancellation_service.DagsterUnavailable):
        return _exception(
            exc,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            retryable=True,
        )
    if isinstance(exc, pipeline_cancellation_service.DagsterTerminationTimeout):
        return _exception(
            exc,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            retryable=True,
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="pipeline cancellation failed",
    )
