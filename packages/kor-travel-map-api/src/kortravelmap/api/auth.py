"""``kortravelmap.api.auth`` — 앱 레벨 service-token / 파괴적 작업 게이트.

ADR-045 D-1 defense-in-depth (ADR-005 amendment): 운영 인증의 **1차 책임은 infra
계층**(reverse proxy / Cloudflare Tunnel SSO + IP allowlist)이고, 본 모듈은 그 위에
얇은 앱 레벨 방어를 더한다(네트워크를 무조건 신뢰하지 않기 위함).

- ``require_service_token`` — ``settings.service_token`` 설정 시 외부 surface에서
  ``X-Kor-Travel-Map-Service-Token`` 헤더를 **상수시간** 비교로 검증. 미설정이면 통과
  (intranet/dev 하위호환).
- ``require_ops_operator`` — canonical datasets/pipeline에 trusted frontend BFF,
  read-only principal 또는 exact import-job cancel principal만 허용.
- ``require_admin_destructive_enabled`` — 파괴적 ``/admin`` 작업 kill-switch.

``APIKeyHeader``를 ``Security``로 의존하므로 OpenAPI ``securitySchemes``에 자동
선언되고, 적용된 엔드포인트에 ``security`` 요구가 기록된다(계약 문서화).
"""

from __future__ import annotations

import hmac
import ipaddress
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from kortravelmap.api.settings import ApiSettings

from kortravelmap.infra.public_api_keys import (
    PUBLIC_API_KEY_QUERY_PARAM,
    cached_active_public_api_key_hashes,
    hash_public_api_key,
    public_api_key_matches,
)

from kortravelmap.api.db import get_session
from kortravelmap.api.response import ProblemDetail

__all__ = [
    "ADMIN_ACTOR_HEADER",
    "ADMIN_PROXY_SECRET_HEADER",
    "METRICS_AUTHORIZATION_SCHEME",
    "OPS_ACTOR",
    "OPS_SCOPE_HEADER",
    "OPS_TOKEN_HEADER",
    "OPS_AUTH_ERROR_RESPONSES",
    "SERVICE_TOKEN_HEADER",
    "AdminProxyContext",
    "OpsOperatorContext",
    "require_admin_frontend",
    "require_metrics_token",
    "require_ops_operator",
    "require_service_token",
    "require_public_api_key",
    "require_admin_destructive_enabled",
    "resolve_admin_proxy_context",
    "service_token_matches",
]

ADMIN_ACTOR_HEADER = "X-Kor-Travel-Map-Actor"
ADMIN_PROXY_SECRET_HEADER = "X-Kor-Travel-Map-Admin-Proxy-Secret"
METRICS_AUTHORIZATION_SCHEME = "Bearer"
OPS_ACTOR = "service:pinvi"
OPS_SCOPE_HEADER = "X-Kor-Travel-Map-Ops-Scope"
OPS_TOKEN_HEADER = "X-Kor-Travel-Map-Ops-Token"
SERVICE_TOKEN_HEADER = "X-Kor-Travel-Map-Service-Token"

OPS_AUTH_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {
        "model": ProblemDetail,
        "description": f"{OPS_TOKEN_HEADER} 누락",
    },
    403: {
        "model": ProblemDetail,
        "description": (
            "token 불일치 또는 token에 결박되지 않은 scope/method/exact path 요청"
        ),
    },
    422: {
        "model": ProblemDetail,
        "description": f"{OPS_SCOPE_HEADER} 누락 또는 알 수 없는 scope",
    },
}

_OPS_CANCEL_PATH_PATTERN = re.compile(
    r"\A/v1/ops/pipeline/executions/import_job/"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/cancel\Z"
)

# auto_error=False — 토큰 미설정(opt-out) 환경에서 헤더가 없어도 통과시키기 위해
# 강제 401을 끄고, 실제 검증은 dependency 함수가 한다(설정 유무에 따라 분기).
_service_token_scheme = APIKeyHeader(
    name=SERVICE_TOKEN_HEADER,
    scheme_name="ServiceToken",
    auto_error=False,
    description="외부 서비스 호출 토큰 (ADR-045 D-1).",
)

_admin_proxy_secret_scheme = APIKeyHeader(
    name=ADMIN_PROXY_SECRET_HEADER,
    scheme_name="AdminBFF",
    auto_error=False,
    description=(
        "trusted admin frontend BFF가 주입하는 server-only secret. 허용된 peer CIDR과 "
        f"{ADMIN_ACTOR_HEADER} actor header도 함께 검증한다."
    ),
)

_ops_token_scheme = APIKeyHeader(
    name=OPS_TOKEN_HEADER,
    scheme_name="OpsToken",
    auto_error=False,
    description=(
        "canonical ops server-to-server read/cancel token. scope 문자열만으로는 "
        "권한을 얻지 못하며, token 종류와 method/exact path도 일치해야 한다."
    ),
)


@dataclass(frozen=True, slots=True)
class AdminProxyContext:
    """Next.js admin frontend proxy가 주입한 운영자 컨텍스트."""

    actor: str


@dataclass(frozen=True, slots=True)
class OpsOperatorContext:
    """canonical ops route가 신뢰한 audit actor 컨텍스트."""

    actor: str


def _settings(request: Request) -> ApiSettings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _peer_is_trusted(request: Request, settings: ApiSettings) -> bool:
    peer_host = request.client.host if request.client is not None else ""
    try:
        peer = ipaddress.ip_address(peer_host)
    except ValueError:
        return False
    for raw_network in settings.admin_trusted_proxy_cidrs:
        try:
            if peer in ipaddress.ip_network(raw_network, strict=False):
                return True
        except ValueError:
            continue
    return False


def _admin_proxy_secret_matches(
    request: Request,
    settings: ApiSettings,
    provided: str | None = None,
) -> bool:
    expected = settings.admin_proxy_secret
    if expected is None:
        return True
    actual = (provided or request.headers.get(ADMIN_PROXY_SECRET_HEADER) or "").strip()
    return bool(actual) and hmac.compare_digest(actual, expected.get_secret_value())


def resolve_admin_proxy_context(
    request: Request,
    settings: ApiSettings,
    proxy_secret: str | None = None,
) -> AdminProxyContext | None:
    """신뢰할 수 있는 admin frontend proxy 요청이면 actor를 반환한다.

    ``admin_proxy_secret``이 설정되지 않은 개발/테스트 환경에서는 기존 localhost
    직접 호출을 유지한다. 운영/로컬 실사용은 gitignored ``.env``에 secret을 넣어
    Next.js 프론트 프록시만 FastAPI admin API를 호출하게 한다. ADR-066(T-VN-01):
    이 local-dev fallback은 non-production profile 전용이다 — production은 settings
    검증이 secret을 필수화하므로 secret 없는 production 상태는 방어적으로 거부한다.
    """

    if settings.admin_proxy_secret is None:
        if settings.is_production:
            return None
        return AdminProxyContext(actor="local-dev")
    if not _peer_is_trusted(request, settings):
        return None
    if not _admin_proxy_secret_matches(request, settings, proxy_secret):
        return None
    actor = (request.headers.get(ADMIN_ACTOR_HEADER) or "").strip()
    if not actor:
        return None
    return AdminProxyContext(actor=actor)


def require_admin_frontend(
    request: Request,
    proxy_secret: Annotated[
        str | None,
        Security(_admin_proxy_secret_scheme),
    ] = None,
) -> AdminProxyContext:
    """admin API가 Next.js frontend proxy를 통해 들어왔는지 검증한다."""

    settings = _settings(request)
    if settings.admin_proxy_secret is None:
        # ADR-066(T-VN-01): secret 없는 local-dev pass-through는 non-production
        # 전용. production settings는 기동 시점에 secret을 필수화하므로 이 분기는
        # 검증 우회로 만든 비정상 상태에서만 도달한다 — fail-closed로 닫는다.
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "production profile에서는 admin proxy secret 없이 admin API를 "
                    "사용할 수 없습니다."
                ),
            )
        return AdminProxyContext(actor="local-dev")
    if not _peer_is_trusted(request, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="허용된 admin frontend proxy에서 온 요청만 사용할 수 있습니다.",
        )
    if not _admin_proxy_secret_matches(request, settings, proxy_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin frontend proxy 인증 헤더가 유효하지 않습니다.",
        )
    actor = (request.headers.get(ADMIN_ACTOR_HEADER) or "").strip()
    if not actor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{ADMIN_ACTOR_HEADER} 헤더가 필요합니다.",
        )
    return AdminProxyContext(actor=actor)


def _ops_auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": {}},
    )


def _ops_principal_is_enabled(settings: ApiSettings) -> bool:
    return (
        settings.ops_read_token is not None
        or settings.ops_cancel_token is not None
    )


def _is_exact_import_job_cancel(request: Request) -> bool:
    return (
        request.method == "POST"
        and _OPS_CANCEL_PATH_PATTERN.fullmatch(request.scope.get("path", ""))
        is not None
    )


def require_ops_operator(
    request: Request,
    admin_proxy_secret: Annotated[
        str | None,
        Security(_admin_proxy_secret_scheme),
    ] = None,
    token: Annotated[str | None, Security(_ops_token_scheme)] = None,
    scope: Annotated[
        str | None,
        Header(
            alias=OPS_SCOPE_HEADER,
            description=(
                "service principal을 사용할 때 GET은 `ops:read`, exact import-job "
                "cancel POST는 `ops:cancel`이 필수다. 권한은 scope 문자열이 아니라 "
                "각각의 secret과 method/exact path 결박으로 판정한다. trusted admin "
                "frontend BFF 인증에는 이 헤더가 필요하지 않다."
            ),
        ),
    ] = None,
) -> OpsOperatorContext:
    """canonical ops의 BFF 또는 read/exact-cancel principal을 검증한다."""

    settings = _settings(request)
    # admin secret이 없는 개발 환경은 ops principal도 완전히 꺼졌을 때만
    # local-dev 호환을 유지한다. principal을 켠 순간 headerless BFF 우회는 닫힌다.
    if (
        settings.admin_proxy_secret is not None
        or not _ops_principal_is_enabled(settings)
    ):
        frontend = resolve_admin_proxy_context(
            request,
            settings,
            admin_proxy_secret,
        )
        if frontend is not None:
            return OpsOperatorContext(actor=frontend.actor)

    if token is None or token == "":
        raise _ops_auth_error(
            status.HTTP_401_UNAUTHORIZED,
            "OPS_TOKEN_REQUIRED",
            f"{OPS_TOKEN_HEADER} 헤더가 필요합니다.",
        )

    read_expected = settings.ops_read_token
    cancel_expected = settings.ops_cancel_token
    read_matches = read_expected is not None and hmac.compare_digest(
        token, read_expected.get_secret_value()
    )
    cancel_matches = cancel_expected is not None and hmac.compare_digest(
        token, cancel_expected.get_secret_value()
    )
    if not read_matches and not cancel_matches:
        raise _ops_auth_error(
            status.HTTP_403_FORBIDDEN,
            "OPS_TOKEN_INVALID",
            f"{OPS_TOKEN_HEADER} 헤더가 유효하지 않습니다.",
        )

    if scope is None or scope.strip() == "":
        raise _ops_auth_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "OPS_SCOPE_REQUIRED",
            f"{OPS_SCOPE_HEADER} 헤더가 필요합니다.",
        )
    if scope not in {"ops:read", "ops:cancel"}:
        raise _ops_auth_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "OPS_SCOPE_INVALID",
            f"{OPS_SCOPE_HEADER} 헤더가 유효하지 않습니다.",
        )

    read_allowed = (
        scope == "ops:read"
        and read_matches
        and request.method == "GET"
    )
    cancel_allowed = (
        scope == "ops:cancel"
        and cancel_matches
        and _is_exact_import_job_cancel(request)
    )
    if not read_allowed and not cancel_allowed:
        raise _ops_auth_error(
            status.HTTP_403_FORBIDDEN,
            "OPS_SCOPE_FORBIDDEN",
            "token에 결박된 scope, method와 exact path가 일치하지 않습니다.",
        )
    return OpsOperatorContext(actor=OPS_ACTOR)


def service_token_matches(request: Request, token: str | None = None) -> bool:
    """설정된 service token과 요청 헤더/명시 token이 상수시간으로 일치하는지 반환."""

    settings = _settings(request)
    expected = settings.service_token
    if expected is None:
        return False
    headers = getattr(request, "headers", {})
    header_value = headers.get(SERVICE_TOKEN_HEADER) if hasattr(headers, "get") else None
    provided = token or header_value or ""
    return hmac.compare_digest(provided, expected.get_secret_value())


async def require_service_token(
    request: Request,
    token: Annotated[str | None, Security(_service_token_scheme)] = None,
) -> None:
    """``service_token`` 설정 시 ``X-Kor-Travel-Map-Service-Token``을 상수시간 검증한다.

    미설정(None)이면 강제하지 않는다(intranet/dev 기본, ADR-005 하위호환). 운영에서
    토큰을 주입하면 외부 surface는 일치 헤더 없이는 401.
    """
    settings = _settings(request)
    expected = settings.service_token
    if expected is None:
        return
    if not service_token_matches(request, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"유효한 {SERVICE_TOKEN_HEADER} 헤더가 필요합니다.",
        )


async def require_public_api_key(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    key: Annotated[
        str | None,
        Query(
            alias=PUBLIC_API_KEY_QUERY_PARAM,
            description=(
                "외부/비신뢰 클라이언트용 VWorld 호환 공개 API 키. "
                "trusted admin proxy 또는 service token 요청은 검증을 우회한다."
            ),
            min_length=1,
            max_length=128,
        ),
    ] = None,
) -> None:
    """public REST surface용 VWorld 호환 API key를 검증한다."""

    settings = _settings(request)
    if not settings.public_api_key_required:
        return
    if (
        settings.admin_proxy_secret is not None
        and resolve_admin_proxy_context(request, settings) is not None
    ):
        return
    if service_token_matches(request):
        return
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"유효한 {PUBLIC_API_KEY_QUERY_PARAM} 쿼리 파라미터가 필요합니다.",
        )
    active_hashes = await cached_active_public_api_key_hashes(
        session,
        ttl_seconds=settings.public_api_key_cache_ttl_s,
    )
    effective_hashes = active_hashes or _vworld_default_key_hashes(settings)
    if not effective_hashes or not public_api_key_matches(key, effective_hashes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="VWorld 호환 API 키가 유효하지 않습니다.",
        )


def _vworld_default_key_hashes(settings: ApiSettings) -> frozenset[str]:
    if settings.vworld_api_key is None:
        return frozenset()
    key = settings.vworld_api_key.get_secret_value().strip()
    if not key:
        return frozenset()
    return frozenset({hash_public_api_key(key)})


def require_metrics_token(request: Request) -> None:
    """``metrics_token`` 설정 시 Prometheus scrape identity를 검증한다.

    ADR-066 결정 4(T-VN-02) — ``/metrics``는 scrape identity/management 경계로
    제한한다. Prometheus scrape config가 네이티브로 지원하는
    ``Authorization: Bearer <token>``을 상수시간 비교로 검증한다. 미설정(None)
    이면 non-production 하위호환으로 열어 두며(로컬 scrape 유지), production
    profile은 settings 검증이 metrics endpoint 활성 시 token을 필수화하므로
    token 없는 production 상태는 방어적으로 403으로 닫는다.
    """

    settings = _settings(request)
    expected = settings.metrics_token
    if expected is None:
        if settings.is_production:
            # T-VN-01 admin gate와 같은 방어 분기 — production settings는 기동
            # 시점에 token을 필수화하므로 검증 우회 상태에서만 도달한다.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "production profile에서는 metrics token 없이 /metrics를 "
                    "사용할 수 없습니다."
                ),
            )
        return
    provided = request.headers.get("Authorization") or ""
    scheme, _, credential = provided.partition(" ")
    # RFC7235 — auth-scheme은 대소문자 무관. credential 비교만 상수시간이면 된다.
    if scheme.lower() != METRICS_AUTHORIZATION_SCHEME.lower() or not hmac.compare_digest(
        credential.strip(), expected.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"유효한 Authorization: {METRICS_AUTHORIZATION_SCHEME} metrics "
                "token이 필요합니다."
            ),
        )


def require_admin_destructive_enabled(request: Request) -> None:
    """``admin_destructive_enabled=False``면 파괴적 admin 작업을 403으로 차단한다."""
    settings = _settings(request)
    if not settings.admin_destructive_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "파괴적 admin 작업이 비활성화되어 있습니다 "
                "(admin_destructive_enabled=False)."
            ),
        )
