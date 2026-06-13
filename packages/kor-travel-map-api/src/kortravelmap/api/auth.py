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
from typing import TYPE_CHECKING, Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

if TYPE_CHECKING:
    from kortravelmap.api.settings import ApiSettings

__all__ = [
    "SERVICE_TOKEN_HEADER",
    "require_service_token",
    "require_admin_destructive_enabled",
]

SERVICE_TOKEN_HEADER = "X-Kor-Travel-Map-Service-Token"

# auto_error=False — 토큰 미설정(opt-out) 환경에서 헤더가 없어도 통과시키기 위해
# 강제 401을 끄고, 실제 검증은 dependency 함수가 한다(설정 유무에 따라 분기).
_service_token_scheme = APIKeyHeader(
    name=SERVICE_TOKEN_HEADER,
    scheme_name="ServiceToken",
    auto_error=False,
    description="TripMate 등 외부 서비스 호출 토큰 (ADR-045 D-1).",
)


def _settings(request: Request) -> ApiSettings:
    return request.app.state.settings  # type: ignore[no-any-return]


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
    provided = token or ""
    if not hmac.compare_digest(provided, expected.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"유효한 {SERVICE_TOKEN_HEADER} 헤더가 필요합니다.",
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
