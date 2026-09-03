"""``kortravelmap.api.app`` — FastAPI application factory.

ADR 참조
--------
- ADR-005 — 네트워크 인증 + 앱 레벨 defense-in-depth
- ADR-020 — 디버그 UI는 별도 패키지 (메인 라이브러리에 FastAPI 의존 X)
- ADR-031 — OpenAPI export drift gate (`scripts/export_openapi.py`)
- ADR-035 — 운영 범위 확장 (디버그 + admin + 유지보수 + 프로덕션 운영)
- ADR-038 — GitHub Actions CI/CD 재활성화

운영
----
표준 기동:
    package-scoped API env와 root 공유 env를 준비하고 ``npm run admin:stack`` 사용

launcher는 ``ApiSettings``(``KOR_TRAVEL_MAP_API_*`` env)와 process별 credential
allowlist를 검증한다. ``host=0.0.0.0`` 직접 노출 금지 — Cloudflare Tunnel/SSO
게이트웨이 뒤에 둔다.
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
from kortravelmap.core.exceptions import GeoAuthNotConfiguredError, GeoRequestError
from kortravelmap.infra import (
    CacheTargetStreamConflict,
    snapshot_build_budget_seconds,
)
from kortravelmap.infra.db import assert_runtime_db_privilege_boundary
from kortravelmap.infra.feature_subtype import SubtypeDetailError
from kortravelmap.infra.log_repo import record_api_call
from kortravelmap.settings import KorTravelMapSettings
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from kortravelmap.api import __version__
from kortravelmap.api.auth import (
    ADMIN_FEATURE_CREATE_TOKEN_HEADER,
    OPS_SCOPE_HEADER,
    PUBLIC_API_KEY_HEADER,
    require_admin_frontend,
    require_metrics_token,
    require_ops_operator,
    require_public_api_key,
)
from kortravelmap.api.cors import (
    SurfaceScopedCORSMiddleware,
    build_cors_surface_patterns,
)
from kortravelmap.api.db import configure_prometheus_metrics
from kortravelmap.api.domain_command_service import (
    DomainCommandFingerprintConflict,
    DomainCommandPending,
    DomainCommandReplay,
)
from kortravelmap.api.prometheus import PrometheusMetrics
from kortravelmap.api.response import ProblemDetail, bind_request_id, reset_request_id
from kortravelmap.api.response import request_id as response_request_id
from kortravelmap.api.route_policy import (
    RoutePolicy,
    RoutePolicyError,
    RoutePolicyMatrixRow,
    assert_route_policy_wiring,
    build_route_policy_matrix,
)
from kortravelmap.api.routers import (
    admin_auth_router,
    admin_backups_router,
    admin_cache_target_streams_router,
    admin_curated_router,
    admin_curation_candidates_router,
    admin_curations_router,
    admin_feature_reference_reconciliation_subscriptions_router,
    admin_feature_requests_router,
    admin_features_router,
    admin_files_router,
    admin_issues_router,
    admin_manual_provider_dedup_cases_router,
    admin_restore_router,
    admin_weather_router,
    categories_router,
    curations_router,
    dedup_review_router,
    enrichment_review_router,
    feature_dedup_review_router,
    feature_enrichment_review_router,
    features_router,
    offline_uploads_router,
    ops_cache_target_streams_router,
    ops_contract_fixtures_router,
    ops_datasets_router,
    ops_live_router,
    ops_logs_router,
    ops_pipeline_router,
    ops_router,
    poi_cache_targets_router,
    public_providers_router,
    public_status_router,
    public_views_router,
    service_cache_target_streams_router,
    service_curation_cutover_router,
    service_curation_snapshots_router,
    service_feature_alias_maps_router,
    service_feature_reference_reconciliations_router,
    service_feature_requests_router,
    weather_router,
)
from kortravelmap.api.routers.admin_features import (
    AdminManualFeatureCanonicalJSONResponse,
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
    429: "TOO_MANY_REQUESTS",
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

_CACHE_TARGET_NOT_FOUND_CODES = frozenset(
    {
        "claim_not_found",
        "dead_letter_not_found",
        "reconciliation_not_found",
        "target_not_found",
    }
)
_CACHE_TARGET_PRECONDITION_CODES = frozenset(
    {
        "create_precondition_failed",
        "dead_letter_precondition_failed",
        "reconciliation_precondition_failed",
        "restore_fence_precondition_failed",
        "target_precondition_failed",
    }
)
_CACHE_TARGET_FORBIDDEN_CODES = frozenset(
    {
        "claim_binding_mismatch",
        "consumer_mismatch",
    }
)
_CACHE_TARGET_UNAVAILABLE_CODES = frozenset(
    {
        "snapshot_barrier_timeout",
        "snapshot_build_timeout",
        "snapshot_busy",
        "snapshot_ttl_too_short",
        # writer가 stream row lock을 제 시간에 못 잡았다. 클라이언트 잘못이 아니라
        # 지금 서버가 그 stream을 다른 작업에 쓰고 있다는 뜻이므로 재시도 가능한 503이다.
        "stream_busy",
        "stream_version_exhausted",
    }
)
_CACHE_TARGET_TOO_MANY_REQUEST_CODES = frozenset({"snapshot_capacity_exceeded"})
_CACHE_TARGET_PAYLOAD_TOO_LARGE_CODES = frozenset(
    {
        "snapshot_byte_limit_exceeded",
        "snapshot_item_limit_exceeded",
    }
)
_CACHE_TARGET_GONE_CODES = frozenset({"snapshot_material_compacted"})

_OPS_CANONICAL_PREFIXES = (
    "/v1/ops/datasets",
    "/v1/ops/pipeline",
)
_OPS_OBSERVABILITY_PATHS = frozenset(
    {
        "/v1/ops/api-call-logs",
        "/v1/ops/consistency/issues",
        "/v1/ops/consistency/reports",
        "/v1/ops/health-deep",
        "/v1/ops/metrics",
        "/v1/ops/system-logs",
    }
)
_OPS_CANCEL_PATH = "/v1/ops/pipeline/executions/import_job/{execution_id}/cancel"
_OPS_FIXTURE_PATH_PREFIX = "/v1/ops/contract-fixtures/c6c-cancel-probe/"
_ADMIN_MANUAL_FEATURE_CREATE_PATH = "/v1/admin/features"
_ADMIN_MANUAL_CURATION_FEATURE_CREATE_PATH = (
    "/v1/admin/curations/{collection_id}/items/manual-feature"
)
_ADMIN_FEATURE_REQUEST_APPROVE_PATH = "/v1/admin/feature-requests/{request_id}/approve"
_ADMIN_FEATURE_REQUEST_REJECT_PATH = "/v1/admin/feature-requests/{request_id}/reject"
_ADMIN_BFF_SECURITY: list[dict[str, list[str]]] = [{"AdminBFF": []}]
_ADMIN_MANUAL_FEATURE_CREATE_SECURITY: list[dict[str, list[str]]] = [
    {"AdminBFF": [], "AdminFeatureCreateBFF": []}
]
# service principal 대안은 OpsToken과 OpsScope를 AND로 함께 요구한다 — 런타임
# 판정(require_ops_operator)이 token만으로는 통과시키지 않고 scope 헤더 누락을
# 422로 거부하는 계약과 일치시킨다.
_ADMIN_OR_OPS_SECURITY: list[dict[str, list[str]]] = [
    {"AdminBFF": []},
    {"OpsToken": [], "OpsScope": []},
]
_OPS_FIXTURE_SECURITY: list[dict[str, list[str]]] = [
    {"OpsToken": [], "OpsScope": []},
]
_PUBLIC_READ_SECURITY: list[dict[str, list[str]]] = [
    {"PublicApiKey": []},
    {"ServiceToken": []},
]

# OpsScope는 runtime dependency상 `Header` 파라미터라 FastAPI가 security scheme을
# 자동 생성하지 않는다. OpenAPI 계약에는 OpsToken과 AND로 선언해야 하므로 여기서
# scheme을 주입한다.
_OPS_SCOPE_SECURITY_SCHEME: dict[str, str] = {
    "type": "apiKey",
    "in": "header",
    "name": OPS_SCOPE_HEADER,
    "description": (
        "service principal 사용 시 OpsToken과 함께 필수인 scope 헤더. GET은 "
        "`ops:read`, exact import-job cancel POST는 `ops:cancel`이다. scope "
        "문자열만으로는 권한을 얻지 못하며 token 종류와 method/exact path도 "
        "일치해야 한다."
    ),
}
_PUBLIC_API_KEY_SECURITY_SCHEME: dict[str, str] = {
    "type": "apiKey",
    "in": "header",
    "name": PUBLIC_API_KEY_HEADER,
    "description": (
        "외부/비신뢰 public read용 VWorld 호환 API key를 X-Kor-Travel-Map-Api-Key "
        "헤더로 전달한다. ServiceToken 요청은 같은 runtime dependency에서 별도 "
        "principal로 허용한다. T-VN-H01 — 접근 로그·Referer 유출을 막기 위해 이전 "
        "?key= 쿼리 파라미터는 제거됐다."
    ),
}
_ADMIN_FEATURE_CREATE_SECURITY_SCHEME: dict[str, str] = {
    "type": "apiKey",
    "in": "header",
    "name": ADMIN_FEATURE_CREATE_TOKEN_HEADER,
    "description": (
        "trusted admin frontend BFF가 수동 Feature 생성 요청에만 주입하는 "
        "server-only 전용 token. AdminBFF와 함께 검증한다."
    ),
}


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
_PROBLEM_REQUIRED_FIELDS = frozenset({"type", "title", "status", "detail", "code", "request_id"})


def _declares_problem_schema(
    candidate: Mapping[str, Any],
    components: Mapping[str, Any],
    *,
    _seen_refs: frozenset[str] = frozenset(),
) -> bool:
    """명시 schema 또는 union의 모든 branch가 RFC7807 계약일 때만 보존한다."""

    ref = candidate.get("$ref")
    prefix = "#/components/schemas/"
    if isinstance(ref, str) and ref.startswith(prefix):
        if ref in _seen_refs:
            return False
        component = components.get(ref.removeprefix(prefix))
        if not isinstance(component, Mapping):
            return False
        return _declares_problem_schema(
            component,
            components,
            _seen_refs=_seen_refs | {ref},
        )
    required = candidate.get("required")
    if isinstance(required, list) and _PROBLEM_REQUIRED_FIELDS.issubset(required):
        return True
    alternatives = candidate.get("oneOf", candidate.get("anyOf"))
    return (
        bool(alternatives)
        and isinstance(alternatives, list)
        and all(
            isinstance(alternative, Mapping)
            and _declares_problem_schema(
                alternative,
                components,
                _seen_refs=_seen_refs,
            )
            for alternative in alternatives
        )
    )


def _problem_content(
    response: Mapping[str, Any] | None = None,
    *,
    components: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    schema: object = {"$ref": "#/components/schemas/ProblemDetail"}
    content = response.get("content") if response is not None else None
    if isinstance(content, Mapping) and components is not None:
        for media_type in ("application/problem+json", "application/json"):
            media = content.get(media_type)
            if not isinstance(media, Mapping):
                continue
            candidate = media.get("schema")
            if not isinstance(candidate, Mapping):
                continue
            if _declares_problem_schema(candidate, components):
                schema = dict(candidate)
                break
    return {
        "application/problem+json": {
            "schema": schema,
        }
    }


def _augment_problem_responses(schema: dict[str, Any]) -> None:
    """생성된 OpenAPI에 RFC7807 problem+json 에러 응답을 주입한다 (T-452).

    중앙 핸들러가 모든 오류를 problem+json으로 통일하므로, 각 operation의 4xx/5xx와
    ``default``와 model을 지정하지 않은 오류 응답 본문을 ``ProblemDetail``로 선언한다.
    라우터가 typed problem model을 명시한 경우 그 schema는 보존하고 media type만
    ``application/problem+json``으로 통일한다. FastAPI 자동 422
    (``HTTPValidationError``)는 problem+json으로 대체하고, orphan이 되는 검증 schema는
    제거한다. 기존 응답의 ``description``은 보존한다.
    """
    components: dict[str, Any] = schema.setdefault("components", {}).setdefault("schemas", {})
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
                        response["content"] = _problem_content(
                            response,
                            components=components,
                        )
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


def _apply_route_security_contract(
    schema: dict[str, Any],
    route_matrix: tuple[RoutePolicyMatrixRow, ...],
) -> None:
    """public/operator route별 실제 principal 대안을 OpenAPI에 선언한다.

    FastAPI는 router dependency의 여러 ``Security`` scheme을 operation 단위 권한으로
    정확히 분리하지 못한다. canonical ops와 잔여 관측 GET은 BFF 또는 read
    principal, exact import-job cancel만 cancel principal, 나머지 ops mutation은
    BFF만 허용한다. 조립된 route policy matrix의 모든
    ``public-keyed`` operation은 public key와 trusted service principal을 OR로,
    ``service`` operation은 service principal만으로 선언한다.
    ``public-unauthenticated`` operation은 security 요구를 제거한다. trusted admin BFF
    우회는 public consumer 계약에 노출하지 않는다.
    """

    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    if isinstance(security_schemes, dict):
        if "OpsToken" in security_schemes:
            security_schemes.setdefault("OpsScope", dict(_OPS_SCOPE_SECURITY_SCHEME))
        security_schemes.setdefault(
            "PublicApiKey",
            dict(_PUBLIC_API_KEY_SECURITY_SCHEME),
        )
        security_schemes.setdefault(
            "AdminFeatureCreateBFF",
            dict(_ADMIN_FEATURE_CREATE_SECURITY_SCHEME),
        )

    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return

    public_security_by_policy: dict[RoutePolicy, list[dict[str, list[str]]]] = {
        RoutePolicy.PUBLIC_UNAUTHENTICATED: [],
        RoutePolicy.PUBLIC_KEYED: _PUBLIC_READ_SECURITY,
        RoutePolicy.SERVICE: [{"ServiceToken": []}],
    }
    for row in route_matrix:
        security = (
            _OPS_FIXTURE_SECURITY
            if row.schema_path.startswith(_OPS_FIXTURE_PATH_PREFIX)
            else public_security_by_policy.get(row.policy)
        )
        if security is None or row.is_websocket or not row.include_in_schema:
            continue
        path_item = paths.get(row.schema_path)
        if not isinstance(path_item, dict):
            continue
        for method in row.methods:
            operation = path_item.get(method.lower())
            if not isinstance(operation, dict):
                continue
            if security:
                operation["security"] = [dict(requirement) for requirement in security]
            else:
                operation.pop("security", None)

    for manual_feature_path in (
        _ADMIN_MANUAL_FEATURE_CREATE_PATH,
        _ADMIN_MANUAL_CURATION_FEATURE_CREATE_PATH,
        _ADMIN_FEATURE_REQUEST_APPROVE_PATH,
        _ADMIN_FEATURE_REQUEST_REJECT_PATH,
    ):
        manual_feature_path_item = paths.get(manual_feature_path)
        if not isinstance(manual_feature_path_item, dict):
            continue
        operation = manual_feature_path_item.get("post")
        if isinstance(operation, dict):
            operation["security"] = [
                dict(requirement) for requirement in _ADMIN_MANUAL_FEATURE_CREATE_SECURITY
            ]

    for path, path_item in paths.items():
        if not isinstance(path, str):
            continue
        if not isinstance(path_item, dict):
            continue
        canonical_ops = path.startswith(_OPS_CANONICAL_PREFIXES)
        observability_ops = path in _OPS_OBSERVABILITY_PATHS
        if not canonical_ops and not observability_ops:
            continue
        for method, operation in path_item.items():
            if method not in _OPENAPI_HTTP_METHODS or not isinstance(operation, dict):
                continue
            service_capable = method == "get" or (method == "post" and path == _OPS_CANCEL_PATH)
            operation["security"] = (
                _ADMIN_OR_OPS_SECURITY if service_capable else _ADMIN_BFF_SECURITY
            )
            if service_capable:
                continue
            parameters = operation.get("parameters")
            if not isinstance(parameters, list):
                continue
            operation["parameters"] = [
                parameter
                for parameter in parameters
                if not (
                    isinstance(parameter, Mapping)
                    and parameter.get("in") == "header"
                    and parameter.get("name") == OPS_SCOPE_HEADER
                )
            ]


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


def _cache_target_stream_conflict_status(code: str) -> int:
    if code in _CACHE_TARGET_NOT_FOUND_CODES:
        return 404
    if code in _CACHE_TARGET_PRECONDITION_CODES:
        return 412
    if code in _CACHE_TARGET_FORBIDDEN_CODES:
        return 403
    if code in _CACHE_TARGET_UNAVAILABLE_CODES:
        return 503
    if code in _CACHE_TARGET_TOO_MANY_REQUEST_CODES:
        return 429
    if code in _CACHE_TARGET_PAYLOAD_TOO_LARGE_CODES:
        return 413
    if code in _CACHE_TARGET_GONE_CODES:
        return 410
    return 409


#: build 예산을 통째로 태우고 실패한 요청에 1초 뒤 재시도를 지시하면, 그 stream은
#: barrier를 놓지 않는 100% duty cycle로 물린다 — 재시도가 즉시 advisory lock을 다시
#: 잡고 같은 예산을 또 태우기 때문이다. 그동안 writer는 계속 밀린다. 실패에 든 시간
#: 만큼은 비워 줘야 부하가 실제로 빠진다.
#: `stream_busy`의 재시도 간격은 lock 대기보다 **길어야** 한다. 대기 1초 뒤 곧바로 다시
#: 오면 서버는 그 client 몫으로 connection을 계속 붙들고 있는 셈이라(대기/주기 = duty cycle)
#: 무한 대기를 고친 효과가 대부분 사라진다. 이 관계는
#: `test_stream_busy_retry_after_is_longer_than_the_lock_wait`이 지킨다.
_STREAM_BUSY_RETRY_AFTER_SECONDS = 10


def _cache_target_retry_after(exc: CacheTargetStreamConflict) -> str | None:
    if exc.code == "snapshot_build_timeout":
        # 상수를 여기 다시 적지 않고 **요청 시점에** 읽는다. import 시각에 얼려 두면
        # 예산을 바꾼 프로세스에서 wire 값과 실제 예산이 갈린다.
        return str(int(snapshot_build_budget_seconds()))
    if exc.code == "stream_busy":
        return str(_STREAM_BUSY_RETRY_AFTER_SECONDS)
    if exc.code in {
        "snapshot_barrier_timeout",
        "snapshot_busy",
        "snapshot_ttl_too_short",
    }:
        return "1"
    if exc.code != "snapshot_capacity_exceeded":
        return None
    value = exc.current.get("retry_after_seconds")
    if type(value) is not int:
        return "1"
    return str(min(max(value, 1), 7_200))


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


def _manual_feature_create_validation_errors(
    exc: RequestValidationError,
) -> list[dict[str, str]]:
    """M01 create 입력 오류를 Pydantic 버전·원문 값과 분리해 공개한다."""

    sanitized: list[dict[str, str]] = []
    for error in exc.errors():
        location = error.get("loc")
        parts = list(location) if isinstance(location, tuple | list) else []
        if parts and parts[0] == "body":
            parts.pop(0)
        field = ".".join(str(part) for part in parts) or "body"
        sanitized.append(
            {
                "field": field,
                "message": "요청 값이 수동 Feature 생성 계약과 맞지 않습니다.",
            }
        )
    return sanitized


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
        "errors": details.get("errors", []) if isinstance(details, Mapping) else [],
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


async def _verify_kor_travel_geo_credentials(core_settings: KorTravelMapSettings) -> None:
    """기동 시 geo가 이 API key를 실제로 받아들이는지 확인한다 (T-VN-H46C).

    ``preflight()``는 존재·공백·길이만 본다. 다른 서비스의 키를 넣어도 통과하므로
    "설정돼 있다"와 "동작한다" 사이에 간극이 있고, 2026-08-13 prod 사고가 정확히 그
    간극이었다.

    판정은 비대칭이다.

    - **키 거부 → 기동 거부.** 그 키로는 어떤 지오코딩도 성공하지 못한다. 그대로 뜨면
      정/역지오코딩이 전부 실패하는 서비스가 healthy로 보인다.
    - **도달 불가·5xx → 경고 후 진행.** geo는 별도 stack이라 그쪽 지연이 map 전체의
      부팅 교착이 되면 안 된다.

    ⚠️ **이 검사가 못 보는 축이 있다.** 여기서 확인하는 것은 python 프로세스가 주입된
    httpx client로 나가는 경로뿐이다. Next.js admin UI의 geo 프록시
    (``packages/kor-travel-map-admin/frontend``)는 별개 통로이고, 2026-08-14 사고는
    **그쪽**이었다. 이 검사가 통과했다고 geo 결선 전체가 검증된 것은 아니다.
    """
    if not core_settings.kor_travel_geo_preflight_required:
        return
    base_url = core_settings.kor_travel_geo_base_url
    if base_url is None:
        # 지오코딩 보강 자체가 비활성이다 — 검사할 대상이 없다.
        return

    from kortravelmap.core.exceptions import GeoRequestError
    from kortravelmap.geocoding import KorTravelGeoRestClient

    async with httpx.AsyncClient(
        base_url=base_url.get_secret_value(),
        timeout=core_settings.kor_travel_geo_timeout_seconds,
    ) as http_client:
        client = KorTravelGeoRestClient(
            http_client,
            api_key=core_settings.kor_travel_geo_api_key,
        )
        try:
            await client.verify_credentials()
        except GeoRequestError as exc:
            # 판정 불가. 기동을 막지 않는다.
            _logger.warning("kor-travel-geo 자격증명 확인 불가 — 기동은 계속한다: %s", exc)


def _assert_no_production_debug_surface(
    application: FastAPI, settings: ApiSettings
) -> None:
    """production에서 ``/v1/debug`` 표면이 마운트되면 기동을 거부한다.

    ``debug_routes_enabled``는 **flag**를 거부할 뿐 표면을 거부하지 않는다. 그
    차이가 실제 결함을 냈다 — flag 뒤에 있던 라우트가 계약에는 들어가고 운영
    이미지에는 없어서, 실행 중 표면과 계약을 바이트 비교하는 M05 live
    attestation이 구조적으로 통과 불가였다(2026-09-03).

    그 라우트를 지운 뒤 flag를 보는 코드가 하나도 남지 않았다. 그러면 flag는
    "아무것도 막지 않는 게이트"가 되고, 문서만 막는다고 말한다. 그래서 불변식을
    **표면 위로** 옮긴다 — 조건부로 마운트하든 무조건 마운트하든, production은
    ``/v1/debug`` 아래의 어떤 경로도 제공하지 않는다.

    거부이지 삭제가 아니다. local-dev debug 표면이 다시 필요해지면 만들 수 있고,
    다만 그것이 운영 계약에 들어가려는 순간 여기서 멈춘다.
    """

    if not settings.is_production:
        return
    mounted = sorted(
        path
        for route in application.routes
        if isinstance(path := getattr(route, "path", None), str)
        and (path == "/v1/debug" or path.startswith("/v1/debug/"))
    )
    if mounted:
        raise RoutePolicyError(
            "production must not serve a /v1/debug surface (ADR-005/ADR-066): "
            + ", ".join(mounted)
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
        ``/ops/...`` 라우터가 설정 flag에 따라 마운트된 app.

    Notes
    -----
    ``app.openapi()``가 ``scripts/export_openapi.py``의 입력. 본 함수 또는
    라우터/DTO 변경 시 ``packages/kor-travel-map-api/openapi.json`` drift
    gate(ADR-031)가 머지 차단.
    """
    if settings is None:
        settings = ApiSettings()
    # ``model_construct``/``model_copy(update=...)``처럼 Pydantic 검증을 우회한
    # settings가 주입되더라도 production app 조립 전에 같은 불변식을 다시 확인한다.
    settings.assert_production_ready()
    # flag 해석은 settings의 resolved 속성이 정본이다 — production fail-closed
    # 검증(ADR-066 T-VN-01)이 mount 규칙과 같은 해석을 공유해야 하기 때문.
    admin_routes_enabled = settings.resolved_admin_routes_enabled
    ops_routes_enabled = settings.resolved_ops_routes_enabled

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        core_settings = KorTravelMapSettings()
        if core_settings.runtime_db_preflight_required:
            from kortravelmap.api.db import get_engine

            await assert_runtime_db_privilege_boundary(
                await get_engine(),
                expected_login="ktm_feature_api_runtime",
            )
        await _verify_kor_travel_geo_credentials(core_settings)
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

    # ADR-066 D-1 (T-VN-02) — 인증 없는 interactive docs UI(``/docs``·``/redoc``·
    # swagger oauth2 redirect)는 production에서 내린다. D-1의
    # public-unauthenticated=(liveness/version)을 넓히지 않기 위함이며, debug
    # 라우터를 production에서 내리는 것과 같은 패턴이다. 기계 판독 공개 계약
    # ``/openapi.json``(ADR-031 served artifact)은 유지한다 — 세 route 모두
    # ``include_in_schema=False``라 committed openapi.json ``paths``에는 애초에
    # 없어 drift가 없다.
    docs_url = None if settings.is_production else "/docs"
    redoc_url = None if settings.is_production else "/redoc"

    application = FastAPI(
        title="kor-travel-map-api",
        version=__version__,
        description=(
            "Admin + public REST API for `kor-travel-map`. "
            "Intranet-only (no auth in code, ADR-005). 운영 범위는 ADR-035 — "
            "/admin, /ops, /features prefix로 분리."
        ),
        # ADR-031 — `--check` mode drift gate 안정성을 위해 ``servers``는 OpenAPI
        # spec에 포함하지 않는다 (호스트별 차이로 drift 발생 우려).
        servers=[],
        docs_url=docs_url,
        redoc_url=redoc_url,
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

        # ADR-066 결정 4 (T-VN-02) — `/metrics`는 scrape identity(management
        # 경계)로 제한한다. metrics token 미설정 local-dev는 기존 open scrape를
        # 유지하고, production은 settings 검증이 token을 필수화한다.
        @application.get(
            settings.prometheus_metrics_path,
            include_in_schema=False,
            dependencies=[Depends(require_metrics_token)],
        )
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
        if (
            request.method == "POST"
            and request.scope.get("path") == _ADMIN_MANUAL_FEATURE_CREATE_PATH
        ):
            return _error_response(
                status_code=422,
                code="VALIDATION_ERROR",
                message="수동 Feature 생성 요청 값이 올바르지 않습니다.",
                details={
                    "errors": _manual_feature_create_validation_errors(exc),
                },
                request_id=request_id,
            )
        return _error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="요청 값이 올바르지 않습니다.",
            details={"errors": exc.errors()},
            request_id=request_id,
        )

    @application.exception_handler(DomainCommandReplay)
    async def domain_command_replay_handler(
        request: Request,
        exc: DomainCommandReplay,
    ) -> JSONResponse:
        body = exc.record.response_body
        meta = body.get("meta")
        original_request_id = (
            meta.get("request_id")
            if isinstance(meta, Mapping) and isinstance(meta.get("request_id"), str)
            else body.get("request_id")
            if isinstance(body.get("request_id"), str)
            else None
        )
        headers = {
            **exc.record.response_headers,
            "Idempotency-Replayed": "true",
        }
        if original_request_id:
            headers["X-Request-ID"] = original_request_id
        response_class = (
            AdminManualFeatureCanonicalJSONResponse
            if exc.record.operation == "admin.feature.create.manual-v1"
            else JSONResponse
        )
        return response_class(
            status_code=exc.record.response_status,
            content=jsonable_encoder(body),
            headers=headers,
        )

    @application.exception_handler(DomainCommandFingerprintConflict)
    async def domain_command_fingerprint_conflict_handler(
        request: Request,
        exc: DomainCommandFingerprintConflict,
    ) -> JSONResponse:
        return _error_response(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message=str(exc),
            details={
                "operation": exc.claim.operation,
                "idempotency_key": exc.claim.idempotency_key,
            },
            request_id=_request_id(request),
        )

    @application.exception_handler(DomainCommandPending)
    async def domain_command_pending_handler(
        request: Request,
        exc: DomainCommandPending,
    ) -> JSONResponse:
        return _error_response(
            status_code=409,
            code="IDEMPOTENCY_RESULT_PENDING",
            message=str(exc),
            details={
                "operation": exc.claim.operation,
                "idempotency_key": exc.claim.idempotency_key,
                "claimed_at": exc.claim.created_at.isoformat(),
            },
            request_id=_request_id(request),
            headers={"Retry-After": "5"},
        )

    @application.exception_handler(GeoAuthNotConfiguredError)
    async def geo_auth_not_configured_handler(
        request: Request,
        exc: GeoAuthNotConfiguredError,
    ) -> JSONResponse:
        return _error_response(
            status_code=503,
            code="GEO_AUTH_NOT_CONFIGURED",
            message=str(exc),
            details={},
            request_id=_request_id(request),
        )

    @application.exception_handler(GeoRequestError)
    async def geo_request_error_handler(
        request: Request,
        exc: GeoRequestError,
    ) -> JSONResponse:
        return _error_response(
            status_code=502,
            code="PROVIDER_ERROR",
            message=str(exc),
            details={},
            request_id=_request_id(request),
        )

    @application.exception_handler(CacheTargetStreamConflict)
    async def cache_target_stream_conflict_handler(
        request: Request,
        exc: CacheTargetStreamConflict,
    ) -> JSONResponse:
        status_code = _cache_target_stream_conflict_status(exc.code)
        retry_after = _cache_target_retry_after(exc)
        return _error_response(
            status_code=status_code,
            code=exc.code.upper(),
            message=str(exc),
            details=exc.current,
            request_id=_request_id(request),
            headers={"Retry-After": retry_after} if retry_after is not None else None,
        )

    @application.exception_handler(SubtypeDetailError)
    async def subtype_detail_error_handler(
        request: Request,
        exc: SubtypeDetailError,
    ) -> JSONResponse:
        """kind 계약과 맞지 않는 ``detail``은 서버 결함이 아니라 요청 결함이다.

        typed subtype(T-VN-35, ADR-086) 도입 뒤 필수 필드 결측은 write 경계에서
        거부된다. 그 거부가 500으로 새면 **이미 접수된 change request**가 승인
        시점마다 500을 내며 영구히 적용 불가가 된다 — 무엇을 고쳐야 하는지도
        알려주지 않는다.
        """
        return _error_response(
            status_code=422,
            code="DETAIL_KIND_MISMATCH",
            message=str(exc),
            details={"kind": exc.kind, "feature_id": exc.feature_id},
            request_id=_request_id(request),
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
        is_manual_feature_create = (
            request.method == "POST"
            and request.scope.get("path") == _ADMIN_MANUAL_FEATURE_CREATE_PATH
        )
        return _error_response(
            status_code=500,
            code=("INTERNAL_SERVER_ERROR" if is_manual_feature_create else "INTERNAL_ERROR"),
            message=(
                "수동 Feature 생성 중 내부 오류가 발생했습니다."
                if is_manual_feature_create
                else "서버 내부 오류가 발생했습니다."
            ),
            details={},
            request_id=request_id,
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

    if settings.features_routes_enabled:
        # 사용자/서비스 표면 ``/features`` · ``/categories`` · ``/providers``는 ``/v1``
        # prefix로 노출한다(T-214b, ADR-048 — clean cut, unversioned alias 없음). 브라우저
        # admin UI도 쓰는 공용 read라 앱 토큰을 강제하지 않는다(operator는 proxy SSO).
        # ``POST /v1/features/batch``와 ``POST /v1/features/weather/batch``는 순수
        # service-to-service read라 route-level에서 service token으로 게이트한다
        # (ADR-045 D-1; features.py). 나머지 ``/v1/features`` read는 공용이라
        # 앱 토큰을 강제하지 않는다.
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
        application.include_router(
            weather_router,
            prefix="/v1",
            dependencies=public_dependencies,
        )
        application.include_router(
            curations_router,
            prefix="/v1",
            dependencies=public_dependencies,
        )
        application.include_router(
            categories_router,
            prefix="/v1",
            dependencies=public_dependencies,
        )
        application.include_router(
            public_providers_router,
            prefix="/v1",
            dependencies=public_dependencies,
        )
        application.include_router(
            service_cache_target_streams_router,
            prefix="/v1",
        )
        application.include_router(
            service_curation_snapshots_router,
            prefix="/v1",
        )
        application.include_router(
            service_curation_cutover_router,
            prefix="/v1",
        )
        # T-VN-32C alias-map DB-to-DB 이관 표면 — route-level service token gate
        # (라우터 자체 dependency), 이관·복구 경계 전용 read (ADR-068 결정 3).
        application.include_router(
            service_feature_alias_maps_router,
            prefix="/v1",
        )
        application.include_router(
            service_feature_requests_router,
            prefix="/v1",
        )
        application.include_router(
            service_feature_reference_reconciliations_router,
            prefix="/v1",
        )

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
        application.include_router(
            admin_files_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        # Retired compatibility URI는 인증된 요청에만 410을 반환한다. recovery format과
        # 실행 경로가 없는 상태이므로 destructive gate나 DB dependency를 거치지 않는다.
        application.include_router(
            admin_restore_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        # `/admin/features/{feature_id}`보다 구체적인 feature 하위 운영 route를
        # 먼저 mount해야 `dedup-reviews` 같은 segment가 feature_id로 잡히지 않는다.
        application.include_router(
            admin_curated_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_curations_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_curation_candidates_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_weather_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            feature_dedup_review_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            feature_enrichment_review_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_features_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_feature_requests_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_feature_reference_reconciliation_subscriptions_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_manual_provider_dedup_cases_router,
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
            poi_cache_targets_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            offline_uploads_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )
        application.include_router(
            admin_cache_target_streams_router,
            prefix="/v1",
            dependencies=admin_dependencies,
        )

    if ops_routes_enabled:
        observability_dependencies = [Depends(require_ops_operator)]
        application.include_router(
            ops_router,
            prefix="/v1",
            dependencies=observability_dependencies,
        )
        application.include_router(ops_live_router, prefix="/v1")
        application.include_router(
            ops_logs_router,
            prefix="/v1",
            dependencies=observability_dependencies,
        )
        application.include_router(
            ops_cache_target_streams_router,
            prefix="/v1",
            dependencies=observability_dependencies,
        )
        application.include_router(
            ops_contract_fixtures_router,
            prefix="/v1",
        )

    # ADR-064 (T-ADM-C2/C6c) — canonical `/ops/datasets`는 기존 admin frontend와
    # read-only server-to-server principal만 허용한다. service mutation은 거부한다.
    # T-ADM-C3(pipeline 그룹)와의 rebase 충돌을 줄이기 위해 자체 블록으로 둔다.
    if ops_routes_enabled:
        application.include_router(
            ops_datasets_router,
            prefix="/v1",
            dependencies=[Depends(require_ops_operator)],
        )

    # ADR-064 (T-ADM-C3/C6c) — canonical `/ops/pipeline`도 같은 ops principal로
    # 마운트한다. legacy ops와 admin/BFF route의 인증 범위는 넓히지 않는다. datasets 그룹
    # (T-ADM-C2)과의 병렬 작업 충돌을 줄이기 위해 include 블록을 분리해 둔다.
    if ops_routes_enabled:
        application.include_router(
            ops_pipeline_router,
            prefix="/v1",
            dependencies=[Depends(require_ops_operator)],
        )

    # ADR-031/T-452 — 생성 openapi에 RFC7807 problem+json 에러 응답을 주입한다.
    # 중앙 예외 핸들러가 모든 4xx/5xx를 problem+json으로 통일하는 구조를 기계 계약에
    # 반영한다(`export_openapi.py`가 이 `openapi()`를 호출).
    _default_openapi = application.openapi

    def _custom_openapi() -> dict[str, Any]:
        if application.openapi_schema is not None:
            return application.openapi_schema
        schema = _default_openapi()
        _augment_problem_responses(schema)
        _apply_route_security_contract(schema, build_route_policy_matrix(application))
        application.openapi_schema = schema
        return schema

    application.openapi = _custom_openapi  # type: ignore[method-assign]

    # ADR-066 결정 1 (T-VN-02/H03R) — 모든 HTTP/WS route의 분류와 실제 enforcing
    # dependency 배선을 startup에서 함께 검증한다. 미분류·miswire·stale exception은
    # 앱을 실행하기 전에 실패한다.
    route_policy_matrix = assert_route_policy_wiring(application)
    _assert_no_production_debug_surface(application, settings)

    # ADR-066 T-VN-H03 — surface별 CORS 분리. route policy matrix(T-VN-02)의
    # 분류를 재사용해 browser-facing public 표면(public-unauthenticated·
    # public-keyed)에만 CORS를 적용한다. operator(admin BFF same-origin proxy)·
    # service(server-to-server token)·metrics·debug 표면은 CORS 헤더를 내보내지
    # 않는다. app-global CORSMiddleware를 route policy로 게이트하는 표면 범위
    # 미들웨어라 가장 바깥에 둔다. OpenAPI spec 무관(미들웨어, ADR-031 drift 무관).
    if settings.cors_allow_origins:
        application.add_middleware(
            SurfaceScopedCORSMiddleware,
            surface_patterns=build_cors_surface_patterns(route_policy_matrix),
            allow_origins=settings.cors_allow_origins,
        )

    return application


app: FastAPI = create_app()
"""모듈-레벨 FastAPI instance.

검증된 launcher가 이 instance를 실행하고, ``scripts/export_openapi.py``가
``app.openapi()``를 호출한다.
"""
