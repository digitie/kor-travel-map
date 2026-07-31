"""API boundary Protocols for ADR-081 cache-target streams."""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import HTTPException, Request, status

__all__ = [
    "CacheTargetStreamService",
    "get_cache_target_stream_service",
    "raise_for_cache_target_status",
]


def _getattr(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


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


def raise_for_cache_target_status(result: Any) -> None:
    """Translate typed cache-target service result statuses to stable HTTP errors."""

    result_status = _getattr(result, "status")
    if result_status in {"precondition_required", "missing_precondition"}:
        raise _http_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "PRECONDITION_REQUIRED",
            "조건부 요청 header가 필요합니다.",
        )
    if result_status in {"precondition_failed", "stale_etag"}:
        raise _http_error(
            status.HTTP_412_PRECONDITION_FAILED,
            "PRECONDITION_FAILED",
            "조건부 요청이 현재 resource 상태와 일치하지 않습니다.",
        )
    if result_status in {"conflict", "idempotency_conflict"}:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "CONFLICT",
            "요청이 기존 command 또는 stream 상태와 충돌합니다.",
        )
    if result_status in {"not_found", "missing"}:
        raise _http_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "요청한 cache target stream resource가 없습니다.",
        )
    if result_status in {"service_unavailable", "unavailable"}:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SERVICE_UNAVAILABLE",
            "cache target stream 저장소를 사용할 수 없습니다.",
        )


class CacheTargetStreamService(Protocol):
    """Repository/service calls owned by the main backend package."""

    async def get_cache_target_source(
        self,
        session: Any,
        *,
        external_system: str,
        target_key: str,
        include_deleted: bool = False,
    ) -> Any | None: ...

    async def apply_cache_target_source(self, session: Any, **kwargs: Any) -> Any: ...

    async def get_cache_target_stream(
        self,
        session: Any,
        *,
        external_system: str,
    ) -> Any | None: ...

    async def advance_cache_target_restore_fence(
        self,
        session: Any,
        **kwargs: Any,
    ) -> Any: ...

    async def create_refresh_request(self, session: Any, **kwargs: Any) -> Any: ...

    async def get_refresh_request(
        self,
        session: Any,
        *,
        request_id: str,
    ) -> Any | None: ...

    async def claim_cache_target_events(self, session: Any, **kwargs: Any) -> Any: ...

    async def ack_cache_target_events(self, session: Any, **kwargs: Any) -> Any: ...

    async def nack_cache_target_event(self, session: Any, **kwargs: Any) -> Any: ...

    async def get_cache_target_dead_letter(
        self,
        session: Any,
        *,
        event_id: str,
    ) -> Any | None: ...

    async def list_cache_target_dead_letters(self, session: Any, **kwargs: Any) -> Any: ...

    async def replay_cache_target_dead_letter(self, session: Any, **kwargs: Any) -> Any: ...

    async def get_cache_target_snapshot(self, session: Any, **kwargs: Any) -> Any: ...

    async def list_cache_target_stream_statuses(self, session: Any, **kwargs: Any) -> Any: ...

    async def request_cache_target_reconciliation(self, session: Any, **kwargs: Any) -> Any: ...

    async def get_cache_target_operation(
        self,
        session: Any,
        *,
        operation_id: str,
    ) -> Any | None: ...


class _RepoCacheTargetStreamService:
    """Thin API adapter over available main-library repository functions."""

    async def get_cache_target_source(
        self,
        session: Any,
        *,
        external_system: str,
        target_key: str,
        include_deleted: bool = False,
    ) -> Any | None:
        from kortravelmap.infra import get_cache_target_source

        return await get_cache_target_source(
            session,
            external_system=external_system,
            target_key=target_key,
            include_deleted=include_deleted,
        )

    async def apply_cache_target_source(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import apply_cache_target_source

        return await apply_cache_target_source(session, **kwargs)

    async def get_cache_target_stream(
        self,
        session: Any,
        *,
        external_system: str,
    ) -> Any | None:
        from kortravelmap.infra import get_cache_target_stream

        return await get_cache_target_stream(session, external_system=external_system)

    async def advance_cache_target_restore_fence(
        self,
        session: Any,
        **kwargs: Any,
    ) -> Any:
        from kortravelmap.infra import advance_cache_target_restore_fence

        return await advance_cache_target_restore_fence(session, **kwargs)

    async def create_refresh_request(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import create_cache_target_refresh_request

        return await create_cache_target_refresh_request(session, **kwargs)

    async def get_refresh_request(
        self,
        session: Any,
        *,
        request_id: str,
    ) -> Any | None:
        from kortravelmap.infra import get_cache_target_refresh_request

        return await get_cache_target_refresh_request(session, request_id=request_id)

    async def claim_cache_target_events(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import claim_cache_target_events

        return await claim_cache_target_events(session, **kwargs)

    async def ack_cache_target_events(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import CacheTargetAppliedReceipt, ack_cache_target_events

        applied = [
            CacheTargetAppliedReceipt(
                event_id=str(item["event_id"]),
                payload_fingerprint=str(item["payload_fingerprint"]),
            )
            for item in kwargs.pop("applied", [])
        ]
        return await ack_cache_target_events(session, applied=applied, **kwargs)

    async def nack_cache_target_event(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import nack_cache_target_event

        kwargs.pop("disposition", None)
        return await nack_cache_target_event(session, **kwargs)

    async def get_cache_target_dead_letter(
        self,
        session: Any,
        *,
        event_id: str,
    ) -> Any | None:
        from kortravelmap.infra import get_cache_target_dead_letter

        return await get_cache_target_dead_letter(session, event_id=event_id)

    async def list_cache_target_dead_letters(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import list_cache_target_dead_letters

        return await list_cache_target_dead_letters(session, **kwargs)

    async def replay_cache_target_dead_letter(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import replay_cache_target_dead_letter

        return await replay_cache_target_dead_letter(session, **kwargs)

    async def get_cache_target_snapshot(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import get_cache_target_snapshot

        return await get_cache_target_snapshot(session, **kwargs)

    async def list_cache_target_stream_statuses(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import list_cache_target_stream_statuses

        return await list_cache_target_stream_statuses(session, **kwargs)

    async def request_cache_target_reconciliation(self, session: Any, **kwargs: Any) -> Any:
        from kortravelmap.infra import request_cache_target_reconciliation

        return await request_cache_target_reconciliation(session, **kwargs)

    async def get_cache_target_operation(
        self,
        session: Any,
        *,
        operation_id: str,
    ) -> Any | None:
        from kortravelmap.infra import get_cache_target_operation

        return await get_cache_target_operation(session, operation_id=operation_id)


def get_cache_target_stream_service(request: Request) -> CacheTargetStreamService:
    """Return the configured cache-target stream service or fail explicitly."""

    service = getattr(request.app.state, "cache_target_stream_service", None)
    if service is None:
        service = _RepoCacheTargetStreamService()
        request.app.state.cache_target_stream_service = service
    return service
