"""``kortravelmap.api.app`` — FastAPI application factory.

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
    ``uvicorn kortravelmap.api.app:app --host 127.0.0.1 --port 12701``

uvicorn 설정은 ``ApiSettings``(``KOR_TRAVEL_MAP_API_*`` env) 또는 호출자가
명시. ``host=0.0.0.0`` 직접 노출 금지 — Cloudflare Tunnel/SSO 게이트웨이 뒤에
둔다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from kortravelmap.infra.log_repo import record_api_call
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from kortravelmap.api import __version__
from kortravelmap.api.auth import (
    require_admin_destructive_enabled,
    require_admin_frontend,
    require_public_api_key,
)
from kortravelmap.api.db import configure_prometheus_metrics
from kortravelmap.api.prometheus import PrometheusMetrics
from kortravelmap.api.response import ProblemDetail, bind_request_id, reset_request_id
from kortravelmap.api.response import request_id as response_request_id
from kortravelmap.api.routers import (
    admin_auth_router,
    admin_backups_router,
    admin_curated_router,
    admin_features_router,
    admin_issues_router,
    admin_restore_router,
    categories_router,
    curated_router,
    dagster_router,
    dedup_review_router,
    enrichment_review_router,
    etl_router,
    feature_update_requests_router,
    features_router,
    mois_detail_router,
    offline_uploads_router,
    ops_live_router,
    ops_logs_router,
    ops_router,
    poi_cache_targets_router,
    provider_refresh_policies_router,
    providers_router,
    public_status_router,
    public_views_router,
)
from kortravelmap.api.settings import ApiSettings

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

# RFC7807 problem+json 응답을 OpenAPI에 주입할 때 쓰는 메서드 집합 (T-452).
_OPENAPI_HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

_PROBLEM_DEFAULT_DESCRIPTION = (
    "RFC7807 `application/problem+json` 에러 본문. 모든 4xx/5xx는 중앙 예외 "
    "핸들러가 동일 형식(`code`/`request_id` 확장 멤버 포함)으로 반환한다 "
    "(docs/architecture/rest-api.md §1.5)."
)


def _build_problem_components() -> dict[str, Any]:
    """``ProblemDetail``/``ProblemDetailError`` schema를 components용으로 평탄화한다.

    pydantic ``model_json_schema``는 nested model을 ``$defs``에 둔다. components
    참조(`#/components/schemas/...`)로 끌어올리기 위해 ``$defs``를 풀어 합친다.
    """
    schema: dict[str, Any] = ProblemDetail.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    defs = schema.pop("$defs", {})
    components: dict[str, Any] = dict(defs) if isinstance(defs, dict) else {}
    components["ProblemDetail"] = schema
    return components


_PROBLEM_COMPONENTS: dict[str, Any] = _build_problem_components()


def _problem_content() -> dict[str, Any]:
    return {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetail"},
        }
    }


def _augment_problem_responses(schema: dict[str, Any]) -> None:
    """생성된 OpenAPI에 RFC7807 problem+json 에러 응답을 주입한다 (T-452).

    중앙 핸들러가 모든 오류를 problem+json으로 통일하므로, 각 operation의 4xx/5xx와
    ``default`` 응답 본문을 ``ProblemDetail``로 선언한다. FastAPI 자동 422
    (``HTTPValidationError``)도 problem+json으로 대체하고, orphan이 되는 검증 schema는
    제거한다. 기존 응답의 ``description``은 보존한다.
    """
    components: dict[str, Any] = schema.setdefault("components", {}).setdefault(
        "schemas", {}
    )
    components.update(_PROBLEM_COMPONENTS)

    paths = schema.get("paths", {})
    if isinstance(paths, dict):
        for path_item in paths.values():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method not in _OPENAPI_HTTP_METHODS or not isinstance(operation, dict):
                    continue
                responses: dict[str, Any] = operation.setdefault("responses", {})
                for code, response in list(responses.items()):
                    if not isinstance(response, dict):
                        continue
                    if code == "default" or (code.isdigit() and int(code) >= 400):
                        response.setdefault("description", _PROBLEM_DEFAULT_DESCRIPTION)
                        response["content"] = _problem_content()
                responses.setdefault(
                    "default",
                    {
                        "description": _PROBLEM_DEFAULT_DESCRIPTION,
                        "content": _problem_content(),
                    },
                )

    # 모든 422가 problem+json으로 대체되어 FastAPI 검증 schema는 orphan이 된다.
    for orphan in ("HTTPValidationError", "ValidationError"):
        components.pop(orphan, None)


def _request_id(request: Request) -> str:
    return response_request_id(request)


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

        from kortravelmap.api.db import _get_engine

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
    problem_type = code.lower().replace("_", "-")
    problem: dict[str, object] = {
        "type": f"https://kor-travel-map/errors/{problem_type}",
        "title": message,
        "status": status_code,
        "detail": message,
        "code": code,
        "request_id": request_id,
        "errors": details.get("errors", [])
        if isinstance(details, Mapping)
        else [],
    }
    if details not in ({}, None) and not (
        isinstance(details, Mapping) and set(details) == {"errors"}
    ):
        problem["details"] = details
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        media_type="application/problem+json",
        content=jsonable_encoder(problem),
    )


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """FastAPI application factory.

    Parameters
    ----------
    settings
        ``ApiSettings`` instance. ``None``이면 env에서 자동 로드.

    Returns
    -------
    FastAPI
        liveness ``/health``·``/version``(public) + ``/v1/features/...``·``/admin/...``·
        ``/ops/...``·``/debug/...`` 라우터가 설정 flag에 따라 마운트된 app.

    Notes
    -----
    ``app.openapi()``가 ``scripts/export_openapi.py``의 입력. 본 함수 또는
    라우터/DTO 변경 시 ``packages/kor-travel-map-api/openapi.json`` drift
    gate(ADR-031)가 머지 차단.
    """
    if settings is None:
        settings = ApiSettings()
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
        title="kor-travel-map-api",
        version=__version__,
        description=(
            "Debug + admin REST API for TripMate `kor-travel-map`. "
            "Intranet-only (no auth in code, ADR-005). 운영 범위는 ADR-035 — "
            "/debug, /admin, /ops, /features prefix로 분리."
        ),
        # ADR-031 — `--check` mode drift gate 안정성을 위해 ``servers``는 OpenAPI
        # spec에 포함하지 않는다 (호스트별 차이로 drift 발생 우려).
        servers=[],
        lifespan=lifespan,
    )
    application.state.settings = settings

    prometheus_metrics: PrometheusMetrics | None = None
    if settings.prometheus_metrics_enabled:
        prometheus_metrics = PrometheusMetrics(
            service_name="kor-travel-map-api",
            version=__version__,
        )
        application.state.prometheus_metrics = prometheus_metrics
        configure_prometheus_metrics(prometheus_metrics)
        endpoint_metrics = prometheus_metrics

        @application.get(settings.prometheus_metrics_path, include_in_schema=False)
        async def prometheus_metrics_endpoint() -> Response:
            return endpoint_metrics.response()
    else:
        configure_prometheus_metrics(None)

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

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """처리되지 않은 예외를 RFC7807 problem+json 500으로 통일한다 (#510).

        starlette 기본 핸들러는 generic 예외를 ``text/plain`` 500
        ``Internal Server Error``로 흘려, OpenAPI가 선언한 ``application/problem+json``
        계약(모든 5xx)을 깬다. 본 핸들러가 이를 막는다. stack은 ``exc_info``로
        **로깅만** 하고(삼키지 않음), 응답 본문에는 예외 detail/stack을 노출하지
        않는다 — 내부 정보 누출 방지.
        """
        request_id = _request_id(request)
        _logger.error(
            "처리되지 않은 예외 (request_id=%s): %s",
            request_id,
            request.url.path,
            exc_info=exc,
        )
        return _error_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message="서버 내부 오류가 발생했습니다.",
            details={},
            request_id=request_id,
        )

    # frontend(Next.js dev/start 12705)가 브라우저에서 backend(12701)로 cross-origin
    # fetch → CORS 필요 (ADR-005: 내부 debug 도구, origin은 localhost frontend로
    # 한정). OpenAPI spec에는 영향 없음(미들웨어, ADR-031 drift gate 무관).
    if settings.cors_allow_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @application.middleware("http")
    async def attach_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = _request_id(request)
        token = bind_request_id(rid)
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)
        response.headers.setdefault("X-Request-ID", rid)
        return response

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

    if prometheus_metrics is not None:
        metrics = prometheus_metrics

        @application.middleware("http")
        async def record_prometheus_metrics(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            if request.url.path == settings.prometheus_metrics_path:
                return await call_next(request)
            return await metrics.instrument_request(request, call_next)

    # public liveness/version은 의존 없는 정적 응답 — 항상 mount (T-213h).
    # `/debug/health`·`/debug/version`은 이와 중복이라 제거(T-214h/ADR-048 clean cut) —
    # 상태확인은 `/health`·`/version`(public) + `/ops/health-deep`(readiness)로 수렴.
    application.include_router(public_status_router)

    if settings.debug_routes_enabled:
        application.include_router(etl_router, prefix="/v1")

    if settings.features_routes_enabled:
        # 사용자/서비스 표면 ``/features`` · ``/categories`` · ``/providers``는 ``/v1``
        # prefix로 노출한다(T-214b, ADR-048 — clean cut, unversioned alias 없음). 브라우저
        # admin UI도 쓰는 공용 read라 앱 토큰을 강제하지 않는다(operator는 proxy SSO).
        # ``POST /v1/features/batch``는 순수 service-to-service read라 route-level에서
        # service token으로 게이트한다(ADR-045 D-1; features.py). token 미설정이면
        # 통과(하위호환). 나머지 ``/v1/features`` read는 공용이라 앱 토큰을 강제하지 않는다.
        public_dependencies = [Depends(require_public_api_key)]
        application.include_router(
            features_router,
            prefix="/v1",
            dependencies=public_dependencies,
        )
        application.include_router(
            public_views_router,
            prefix="/v1",
            dependencies=public_dependencies,
        )
        application.include_router(curated_router, prefix="/v1")
        application.include_router(
            categories_router,
            prefix="/v1",
            dependencies=public_dependencies,
        )
        application.include_router(
            providers_router,
            prefix="/v1",
            dependencies=public_dependencies,
        )
        # Step D on-demand 상세는 DB(적재된 raw_data) 필요 → features와 동일 gate.
        if settings.debug_routes_enabled:
            application.include_router(mois_detail_router, prefix="/v1")

    if admin_routes_enabled:
        admin_dependencies = [Depends(require_admin_frontend)]
        application.include_router(
            admin_auth_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_backups_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        # restore/swap은 전부 파괴적 → kill-switch 게이트(admin_destructive_enabled).
        application.include_router(
            admin_restore_router,
            prefix="/v1",
            dependencies=[
                Depends(require_admin_frontend),
                Depends(require_admin_destructive_enabled),
            ],
        )
        application.include_router(
            admin_features_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_curated_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_issues_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            dedup_review_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            enrichment_review_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            feature_update_requests_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            poi_cache_targets_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            provider_refresh_policies_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            offline_uploads_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )

    if ops_routes_enabled:
        application.include_router(ops_router, prefix="/v1")
        application.include_router(ops_live_router, prefix="/v1")
        application.include_router(ops_logs_router, prefix="/v1")
        application.include_router(dagster_router, prefix="/v1")

    # ADR-031/T-452 — 생성 openapi에 RFC7807 problem+json 에러 응답을 주입한다.
    # 중앙 예외 핸들러가 모든 4xx/5xx를 problem+json으로 통일하는 구조를 기계 계약에
    # 반영한다(`export_openapi.py`가 이 `openapi()`를 호출).
    _default_openapi = application.openapi

    def _custom_openapi() -> dict[str, Any]:
        if application.openapi_schema is not None:
            return application.openapi_schema
        schema = _default_openapi()
        _augment_problem_responses(schema)
        application.openapi_schema = schema
        return schema

    application.openapi = _custom_openapi  # type: ignore[method-assign]

    return application


app: FastAPI = create_app()
"""모듈-레벨 FastAPI instance.

``uvicorn kortravelmap.api.app:app``로 직접 실행, ``scripts/export_openapi.
py``가 ``app.openapi()``를 호출.
"""
