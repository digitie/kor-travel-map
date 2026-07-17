"""Dagster API용 FastAPI request adapter."""

from __future__ import annotations

import httpx
from fastapi import HTTPException, Request, status

from kortravelmap.api import dagster_schedule_service
from kortravelmap.api.dagster_schema import DagsterScheduleCommandResponse
from kortravelmap.api.response import ProblemDetail
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "dagster_http_dependencies",
    "http_client_from_request",
    "schedule_command_response_or_raise",
    "schedule_idempotency_http_exception",
    "schedule_uncertain_outcome_http_exception",
    "schedule_storage_http_exception",
    "schedule_validation_http_exception",
    "SCHEDULE_WRITE_ERROR_RESPONSES",
    "settings_from_request",
]

SCHEDULE_WRITE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    500: {"model": ProblemDetail, "description": "외부 반영 여부 불명 — 운영자 확인 필요"},
    409: {"model": ProblemDetail, "description": "Idempotency-Key 충돌/결과 확인 필요"},
    422: {"model": ProblemDetail, "description": "요청 body/header 또는 cron 검증 실패"},
    502: {"model": ProblemDetail, "description": "Dagster 명령 의미 오류"},
    503: {"model": ProblemDetail, "description": "저장소 또는 Dagster transport 장애"},
}


def schedule_idempotency_http_exception(
    exc: dagster_schedule_service.DagsterScheduleIdempotencyConflict,
) -> HTTPException:
    """중복/불명 schedule command를 새 원격 mutation 없이 409로 반환한다."""

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "DAGSTER_SCHEDULE_IDEMPOTENCY_CONFLICT",
            "message": str(exc),
            "details": {
                "command_id": str(exc.command_id),
                "active_command_id": (
                    str(exc.active_command_id) if exc.active_command_id is not None else None
                ),
            },
        },
    )


def schedule_uncertain_outcome_http_exception(
    exc: dagster_schedule_service.DagsterScheduleUncertainOutcome,
) -> HTTPException:
    """불명 외부 결과를 원격 재실행 없이 operator recovery 정보와 반환한다."""

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "DAGSTER_SCHEDULE_OUTCOME_UNCERTAIN",
            "message": str(exc),
            "details": {
                "command_id": str(exc.command_id),
                "active_command_id": str(exc.command_id),
                "outcome_certainty": "uncertain",
            },
        },
    )


def schedule_storage_http_exception(
    exc: dagster_schedule_service.DagsterScheduleStorageUnavailable,
) -> HTTPException:
    """schedule 영속 저장소 장애를 원격 mutation 전 503으로 중단한다."""

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "DAGSTER_SCHEDULE_STORAGE_UNAVAILABLE",
            "message": str(exc),
            "details": None,
        },
    )


def schedule_validation_http_exception(
    exc: dagster_schedule_service.DagsterScheduleValidationError,
) -> HTTPException:
    """schedule 입력 오류를 RFC7807 중앙 handler 입력으로 바꾼다."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "INVALID_SCHEDULE_COMMAND",
            "message": str(exc),
            "details": None,
        },
    )


def schedule_command_response_or_raise(
    response: DagsterScheduleCommandResponse,
) -> DagsterScheduleCommandResponse:
    """Dagster command 실패 envelope를 성공 HTTP 200으로 노출하지 않는다."""

    data = response.data
    if data.status == "ok":
        return response
    status_code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if data.status == "unavailable"
        else status.HTTP_502_BAD_GATEWAY
    )
    code = (
        "DAGSTER_SCHEDULE_UNAVAILABLE"
        if data.status == "unavailable"
        else "DAGSTER_SCHEDULE_COMMAND_FAILED"
    )
    message = data.errors[0] if data.errors else "Dagster schedule 명령에 실패했습니다."
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": data.model_dump(mode="json"),
        },
    )


def settings_from_request(request: Request) -> ApiSettings:
    """앱에 주입된 설정을 읽고, 없으면 기본 설정을 사용한다."""

    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, ApiSettings):
        return settings
    return ApiSettings()


def http_client_from_request(
    request: Request,
    settings: ApiSettings,
) -> httpx.AsyncClient:
    """앱 수명 동안 재사용하는 Dagster HTTP client를 반환한다."""

    client = getattr(request.app.state, "dagster_http_client", None)
    if isinstance(client, httpx.AsyncClient) and not client.is_closed:
        return client
    client = httpx.AsyncClient(timeout=settings.dagster_request_timeout_seconds)
    request.app.state.dagster_http_client = client
    return client


def dagster_http_dependencies(
    request: Request,
) -> tuple[ApiSettings, httpx.AsyncClient]:
    """Dagster application service가 요구하는 HTTP 의존성을 조립한다."""

    settings = settings_from_request(request)
    return settings, http_client_from_request(request, settings)
