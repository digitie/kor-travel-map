"""``kortravelmap.api.auth`` — 앱 레벨 service-token / 파괴적 작업 게이트.

ADR-045 D-1 defense-in-depth (ADR-005 amendment): 운영 인증의 **1차 책임은 infra
계층**(reverse proxy / Cloudflare Tunnel SSO + IP allowlist)이고, 본 모듈은 그 위에
얇은 앱 레벨 방어를 더한다(네트워크를 무조건 신뢰하지 않기 위함).

- ``require_service_token`` — ``settings.service_token`` 설정 시 외부 surface에서
  ``X-Kor-Travel-Map-Service-Token`` 헤더를 **상수시간** 비교로 검증. 미설정이면 통과
  (intranet/dev 하위호환).
- ``require_admin_destructive_enabled`` — 파괴적 ``/admin`` 작업 kill-switch.

``APIKeyHeader``를 ``Security``로 의존하므로 OpenAPI ``securitySchemes``에 자동
선언되고, 적용된 엔드포인트에 ``security`` 요구가 기록된다(계약 문서화).
"""

from __future__ import annotations

import hmac
import ipaddress
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

__all__ = [
    "ADMIN_ACTOR_HEADER",
    "ADMIN_PROXY_SECRET_HEADER",
    "SERVICE_TOKEN_HEADER",
    "AdminProxyContext",
    "require_admin_frontend",
    "require_service_token",
    "require_public_api_key",
    "require_admin_destructive_enabled",
    "resolve_admin_proxy_context",
    "service_token_matches",
]

ADMIN_ACTOR_HEADER = "X-Kor-Travel-Map-Actor"
ADMIN_PROXY_SECRET_HEADER = "X-Kor-Travel-Map-Admin-Proxy-Secret"
SERVICE_TOKEN_HEADER = "X-Kor-Travel-Map-Service-Token"

# auto_error=False — 토큰 미설정(opt-out) 환경에서 헤더가 없어도 통과시키기 위해
# 강제 401을 끄고, 실제 검증은 dependency 함수가 한다(설정 유무에 따라 분기).
_service_token_scheme = APIKeyHeader(
    name=SERVICE_TOKEN_HEADER,
    scheme_name="ServiceToken",
    auto_error=False,
    description="PinVi 등 외부 서비스 호출 토큰 (ADR-045 D-1).",
)


@dataclass(frozen=True, slots=True)
class AdminProxyContext:
    """Next.js admin frontend proxy가 주입한 운영자 컨텍스트."""

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
) -> AdminProxyContext | None:
    """신뢰할 수 있는 admin frontend proxy 요청이면 actor를 반환한다.

    ``admin_proxy_secret``이 설정되지 않은 개발/테스트 환경에서는 기존 localhost
    직접 호출을 유지한다. 운영/로컬 실사용은 gitignored ``.env``에 secret을 넣어
    Next.js 프론트 프록시만 FastAPI admin API를 호출하게 한다.
    """

    if settings.admin_proxy_secret is None:
        return AdminProxyContext(actor="local-dev")
    if not _peer_is_trusted(request, settings):
        return None
    if not _admin_proxy_secret_matches(request, settings):
        return None
    actor = (request.headers.get(ADMIN_ACTOR_HEADER) or "").strip()
    if not actor:
        return None
    return AdminProxyContext(actor=actor)


def require_admin_frontend(
    request: Request,
    proxy_secret: Annotated[
        str | None,
        Header(alias=ADMIN_PROXY_SECRET_HEADER, include_in_schema=False),
    ] = None,
) -> AdminProxyContext:
    """admin API가 Next.js frontend proxy를 통해 들어왔는지 검증한다."""

    settings = _settings(request)
    if settings.admin_proxy_secret is None:
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
