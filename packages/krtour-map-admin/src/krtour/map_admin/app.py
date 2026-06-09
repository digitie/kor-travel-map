"""``krtour.map_admin.app`` — FastAPI application factory.

ADR 참조
--------
- ADR-005 — 인증 없음 (네트워크 계층 책임)
- ADR-020 — 디버그 UI는 별도 패키지 (메인 라이브러리에 FastAPI 의존 X)
- ADR-031 — OpenAPI export drift gate (`scripts/export_openapi.py`)
- ADR-035 — 운영 범위 확장 (디버그 + admin + 유지보수 + 프로덕션 운영)
- ADR-038 — GitHub Actions CI/CD 재활성화

운영
----
uvicorn 직접 호출:
    ``uvicorn krtour.map_admin.app:app --host 127.0.0.1 --port 9011``

uvicorn 설정은 ``AdminSettings``(``KRTOUR_MAP_ADMIN_*`` env) 또는 호출자가
명시. ``host=0.0.0.0`` 직접 노출 금지 — Cloudflare Tunnel/SSO 게이트웨이 뒤에
둔다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from krtour.map.infra.log_repo import record_api_call
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from krtour.map_admin import __version__
from krtour.map_admin.auth import (
    require_admin_destructive_enabled,
)
from krtour.map_admin.routers import (
    admin_backups_router,
    admin_features_router,
    admin_issues_router,
    admin_restore_router,
    categories_router,
    dagster_router,
    dedup_review_router,
    enrichment_review_router,
    etl_router,
    feature_update_requests_router,
    features_router,
    health_router,
    mois_detail_router,
    offline_uploads_router,
    ops_logs_router,
    ops_router,
    poi_cache_targets_router,
    providers_router,
    public_status_router,
    version_router,
)
from krtour.map_admin.settings import AdminSettings

__all__ = ["app", "create_app"]

_logger = logging.getLogger(__name__)


_ERROR_CODE_BY_STATUS: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
    501: "NOT_IMPLEMENTED",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}


def _request_id(request: Request) -> str:
    value = request.headers.get("x-request-id")
    return value if value else str(uuid4())


async def _record_api_call_safe(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    request_id: str | None,
) -> None:
    """``ops.api_call_log``에 호출 1건을 best-effort로 기록한다 (T-212c).

    opt-in ``api_call_log_enabled`` 미들웨어에서만 호출된다. 짧게 사는 세션을 app
    DB engine으로 열어 INSERT + commit하고, **모든 예외를 삼킨다** — 로그 기록
    실패가 실제 요청을 절대 깨뜨리지 않게 한다(디버그 레벨로만 흘린다).
    """
    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        from krtour.map_admin.db import _get_engine

        async with AsyncSession(_get_engine(), expire_on_commit=False) as session:
            await record_api_call(
                session,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                error_code=None,
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — best-effort, 요청을 절대 깨뜨리지 않는다.
        _logger.debug("api_call_log 기록 실패 (무시)", exc_info=True)


def _status_error_code(status_code: int) -> str:
    if status_code in _ERROR_CODE_BY_STATUS:
        return _ERROR_CODE_BY_STATUS[status_code]
    if 400 <= status_code < 500:
        return "BAD_REQUEST"
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return "ERROR"


def _http_error_payload(
    detail: object,
    *,
    status_code: int,
) -> tuple[str, str, object]:
    if isinstance(detail, Mapping):
        code = detail.get("code")
        message = detail.get("message")
        if isinstance(code, str) and isinstance(message, str):
            return code, message, detail.get("details", {})
    if isinstance(detail, str):
        return _status_error_code(status_code), detail, {}
    if detail is None:
        return (
            _status_error_code(status_code),
            "요청 처리 중 오류가 발생했습니다.",
            {},
        )
    return _status_error_code(status_code), f"HTTP {status_code} error", detail


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: object,
    request_id: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    response_headers.setdefault("X-Request-ID", request_id)
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content=jsonable_encoder(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details if details is not None else {},
                    "request_id": request_id,
                }
            }
        ),
    )


def create_app(settings: AdminSettings | None = None) -> FastAPI:
    """FastAPI application factory.

    Parameters
    ----------
    settings
        ``AdminSettings`` instance. ``None``이면 env에서 자동 로드.

    Returns
    -------
    FastAPI
        ``/debug/health``, ``/debug/version`` 라우터가 마운트된 app. 후속 PR에서
        ``/features/...``, ``/admin/...``, ``/ops/...`` 추가.

    Notes
    -----
    ``app.openapi()``가 ``scripts/export_openapi.py``의 입력. 본 함수 또는
    라우터/DTO 변경 시 ``packages/krtour-map-admin/openapi.json`` drift
    gate(ADR-031)가 머지 차단.
    """
    if settings is None:
        settings = AdminSettings()
    admin_routes_enabled = (
        settings.features_routes_enabled
        if settings.admin_routes_enabled is None
        else settings.admin_routes_enabled
    )
    ops_routes_enabled = (
        settings.features_routes_enabled
        if settings.ops_routes_enabled is None
        else settings.ops_routes_enabled
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            offline_upload_store = getattr(application.state, "offline_upload_store", None)
            offline_upload_s3_client = getattr(offline_upload_store, "s3_client", None)
            offline_upload_close = getattr(offline_upload_s3_client, "close", None)
            if callable(offline_upload_close):
                offline_upload_close()
            client = getattr(application.state, "dagster_http_client", None)
            if isinstance(client, httpx.AsyncClient):
                await client.aclose()

    application = FastAPI(
        title="krtour-map-admin",
        version=__version__,
        description=(
            "Debug + admin REST API for TripMate `python-krtour-map`. "
            "Intranet-only (no auth in code, ADR-005). 운영 범위는 ADR-035 — "
            "/debug, /admin, /ops, /features prefix로 분리."
        ),
        # ADR-031 — `--check` mode drift gate 안정성을 위해 ``servers``는 OpenAPI
        # spec에 포함하지 않는다 (호스트별 차이로 drift 발생 우려).
        servers=[],
        lifespan=lifespan,
    )
    application.state.settings = settings

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        request_id = _request_id(request)
        code, message, details = _http_error_payload(
            exc.detail,
            status_code=exc.status_code,
        )
        return _error_response(
            status_code=exc.status_code,
            code=code,
            message=message,
            details=details,
            request_id=request_id,
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = _request_id(request)
        return _error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="요청 값이 올바르지 않습니다.",
            details={"errors": exc.errors()},
            request_id=request_id,
        )

    # frontend(Next.js dev/start 9012)가 브라우저에서 backend(9011)로 cross-origin
    # fetch → CORS 필요 (ADR-005: 내부 debug 도구, origin은 localhost frontend로
    # 한정). OpenAPI spec에는 영향 없음(미들웨어, ADR-031 drift gate 무관).
    if settings.cors_allow_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # opt-in API 호출 로그 (T-212c). 기본 off → 등록 안 하면 zero overhead.
    # OpenAPI spec에는 영향 없음(미들웨어, ADR-031 drift gate 무관).
    if settings.api_call_log_enabled:

        @application.middleware("http")
        async def record_api_call_log(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            started_at = perf_counter()
            response = await call_next(request)
            await _record_api_call_safe(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
                request_id=_request_id(request),
            )
            return response

    # public liveness/version은 의존 없는 정적 응답 — 항상 mount (T-213h).
    application.include_router(public_status_router)

    if settings.debug_routes_enabled:
        application.include_router(health_router)
        application.include_router(version_router)
        application.include_router(etl_router)

    if settings.features_routes_enabled:
        # 사용자/서비스 표면 ``/features`` · ``/categories`` · ``/providers``는 ``/v1``
        # prefix로 노출한다(T-214b, ADR-048 — clean cut, unversioned alias 없음). 브라우저
        # admin UI도 쓰는 공용 read라 앱 토큰을 강제하지 않는다(operator는 proxy SSO).
        # ``POST /v1/features/batch``는 순수 service-to-service read라 route-level에서
        # service token으로 게이트한다(ADR-045 D-1; features.py). token 미설정이면
        # 통과(하위호환). 나머지 ``/v1/features`` read는 공용이라 앱 토큰을 강제하지 않는다.
        # admin/ops/debug의 ``/v1`` 이동은 ADR-048/T-216a에서 처리한다.
        application.include_router(features_router, prefix="/v1")
        application.include_router(categories_router, prefix="/v1")
        application.include_router(providers_router, prefix="/v1")
        # Step D on-demand 상세는 DB(적재된 raw_data) 필요 → features와 동일 gate.
        if settings.debug_routes_enabled:
            application.include_router(mois_detail_router)

    if admin_routes_enabled:
        application.include_router(admin_backups_router)
        # restore/swap은 전부 파괴적 → kill-switch 게이트(admin_destructive_enabled).
        application.include_router(
            admin_restore_router,
            dependencies=[Depends(require_admin_destructive_enabled)],
        )
        application.include_router(admin_features_router)
        application.include_router(admin_issues_router)
        application.include_router(dedup_review_router)
        application.include_router(enrichment_review_router)
        application.include_router(feature_update_requests_router)
        application.include_router(poi_cache_targets_router)
        application.include_router(offline_uploads_router)

    if ops_routes_enabled:
        application.include_router(ops_router)
        application.include_router(ops_logs_router)
        application.include_router(dagster_router)

    return application


app: FastAPI = create_app()
"""모듈-레벨 FastAPI instance.

``uvicorn krtour.map_admin.app:app``로 직접 실행, ``scripts/export_openapi.
py``가 ``app.openapi()``를 호출.
"""
