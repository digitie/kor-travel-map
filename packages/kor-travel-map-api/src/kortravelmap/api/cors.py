"""``kortravelmap.api.cors`` — ADR-066 T-VN-H03 surface별 CORS 분리.

Starlette ``CORSMiddleware``는 app-global이라 route별로 켜고 끌 수 없다. 본
모듈은 route policy matrix(T-VN-02, ADR-066 D-1)의 표면 분류를 재사용해
browser-facing **public** 표면(``public-unauthenticated``·``public-keyed``)에만
CORS를 적용하고, ``service``·``operator``·``metrics``·``debug`` 표면에는 CORS
헤더를 전혀 내보내지 않는 표면 범위 미들웨어를 둔다.

근거
----
- public read(지도 UI·PinVi web)는 브라우저에서 cross-origin으로 fetch하므로
  CORS가 필요하다.
- operator 표면(admin BFF)은 admin frontend가 same-origin Next.js BFF
  (``/api/proxy``)로만 접근하므로 브라우저 cross-origin이 아니다 — CORS 불필요.
- service 표면(``X-Kor-Travel-Map-Service-Token``)과 metrics scrape은
  server-to-server라 브라우저 cross-origin이 아니다 — CORS 불필요.

경로 판정 규칙 (security-safe)
-----------------------------
어떤 경로가 CORS를 받으려면 **public 패턴에 매칭되고 동시에 비-public 패턴에는
전혀 매칭되지 않아야 한다.** 모든 비-public route는 자기 자신의 비-public 패턴에
매칭되므로, 비-public route는 어떤 경우에도 CORS를 받을 수 없다(구성상 보장).
이 규칙은 literal service route(``/v1/features/batch``)가 public param route
(``/v1/features/{feature_id}``) 패턴과 겹칠 때도 service를 CORS 대상에서 제외해
Starlette 라우팅(구체 route 우선 등록)과 일치한다. 오분류가 나더라도 실패
방향은 "public route가 CORS를 못 받는다"(가시적·테스트 가능)이지 "비-public
route가 CORS를 흘린다"가 아니다.

또 credential 모드를 켜지 않으므로 wildcard+credential 조합은 성립할 수 없다.
preflight는 route matrix의 실제 method와 CORS safelist + public API key header만
허용하고, 그 밖의 method/header는 ACAO 없이 거부한다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.routing import compile_path
from starlette.types import ASGIApp, Receive, Scope, Send

from kortravelmap.api.route_policy import RoutePolicy, RoutePolicyMatrixRow

__all__ = [
    "CORS_ELIGIBLE_POLICIES",
    "PUBLIC_CORS_REQUEST_HEADERS",
    "CorsPublicRoute",
    "CorsSurfacePatterns",
    "SurfaceScopedCORSMiddleware",
    "build_cors_surface_patterns",
]

#: CORS가 허용되는 browser-facing 표면. 나머지(service/operator/metrics/debug)는
#: server-to-server 또는 same-origin BFF라 CORS 헤더를 내보내지 않는다.
CORS_ELIGIBLE_POLICIES: frozenset[RoutePolicy] = frozenset(
    {RoutePolicy.PUBLIC_UNAUTHENTICATED, RoutePolicy.PUBLIC_KEYED}
)

#: public browser가 preflight에서 요청할 수 있는 header 정본. CORS safelist를
#: 명시해 middleware의 판정과 운영 문서가 같은 closed allowlist를 공유한다.
PUBLIC_CORS_REQUEST_HEADERS: tuple[str, ...] = (
    "Accept",
    "Accept-Language",
    "Content-Language",
    "Content-Type",
    "X-Kor-Travel-Map-Api-Key",
)


@dataclass(frozen=True, slots=True)
class CorsPublicRoute:
    """public route 하나의 경로 정규식과 실제 HTTP method 계약."""

    pattern: re.Pattern[str]
    methods: frozenset[str]


@dataclass(frozen=True, slots=True)
class CorsSurfacePatterns:
    """CORS 허용(public)·차단(비-public) route 경로 정규식 묶음.

    ``public``은 CORS 허용 표면 route, ``blocked``은 그 외 표면 route의 경로
    정규식이다. 판정은 security-safe 규칙(비-public 매칭 시 무조건 제외)을 쓴다.
    """

    public: tuple[CorsPublicRoute, ...]
    blocked: tuple[re.Pattern[str], ...]

    def public_methods(self, path: str) -> frozenset[str] | None:
        """경로가 public이면 실제 method 집합, 아니면 ``None``을 반환한다."""

        if any(pattern.match(path) for pattern in self.blocked):
            return None
        for route in self.public:
            if route.pattern.match(path):
                return route.methods
        return None

    @property
    def all_public_methods(self) -> tuple[str, ...]:
        """내부 Starlette middleware에 줄 public method 합집합."""

        return tuple(
            sorted({method for route in self.public for method in route.methods})
        )


def build_cors_surface_patterns(
    matrix: Iterable[RoutePolicyMatrixRow],
) -> CorsSurfacePatterns:
    """route policy matrix에서 public·비-public 경로 정규식을 컴파일한다.

    Starlette ``compile_path``로 route template(``{param}``·``{p:path}`` 포함)을
    Starlette 라우팅과 동일한 앵커드 정규식으로 변환한다.
    """

    public_methods_by_path: dict[str, set[str]] = {}
    blocked: list[re.Pattern[str]] = []
    seen_blocked: set[str] = set()
    for row in matrix:
        if row.policy in CORS_ELIGIBLE_POLICIES:
            public_methods_by_path.setdefault(row.path, set()).update(row.methods)
        elif row.path not in seen_blocked:
            path_regex, _path_format, _convertors = compile_path(row.path)
            seen_blocked.add(row.path)
            blocked.append(path_regex)

    public = tuple(
        CorsPublicRoute(
            pattern=compile_path(path)[0],
            methods=frozenset(methods),
        )
        for path, methods in public_methods_by_path.items()
    )
    return CorsSurfacePatterns(public=public, blocked=tuple(blocked))


class SurfaceScopedCORSMiddleware:
    """public 표면에만 CORS를 적용하는 표면 범위 ASGI 미들웨어 (T-VN-H03).

    요청 경로가 CORS 허용 표면(public)에 매칭되면 내부 ``CORSMiddleware``에
    위임해 preflight/``Access-Control-*`` 헤더를 정상 처리하고, 그렇지 않으면
    CORS 없이 app으로 통과시킨다(비-public 표면은 ACAO를 붙이지 않는다).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        surface_patterns: CorsSurfacePatterns,
        allow_origins: Sequence[str],
    ) -> None:
        self.app = app
        self._surface_patterns = surface_patterns
        self._allowed_header_names = frozenset(
            header.casefold() for header in PUBLIC_CORS_REQUEST_HEADERS
        )
        # 내부 CORSMiddleware는 credential 모드를 켜지 않는다 — wildcard+credential
        # 조합을 원천 차단한다(T-VN-H03).
        self._cors = CORSMiddleware(
            app,
            allow_origins=list(allow_origins),
            allow_methods=list(surface_patterns.all_public_methods),
            allow_headers=list(PUBLIC_CORS_REQUEST_HEADERS),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        allowed_methods = self._surface_patterns.public_methods(scope["path"])
        if allowed_methods is None:
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS":
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            requested_method = headers.get("access-control-request-method")
            requested_headers = headers.get("access-control-request-headers")
            disallowed_method = (
                requested_method is not None and requested_method not in allowed_methods
            )
            requested_header_names = {
                header.strip().casefold()
                for header in (requested_headers or "").split(",")
                if header.strip()
            }
            disallowed_headers = not requested_header_names <= self._allowed_header_names
            if origin is not None and requested_method is not None and (
                disallowed_method or disallowed_headers
            ):
                # Starlette CORSMiddleware는 실패 preflight에도 ACAO를 붙일 수 있다.
                # trust 계약 밖 요청은 직접 거부해 ACAO 자체를 광고하지 않는다.
                response = PlainTextResponse("Disallowed CORS request", status_code=400)
                await response(scope, receive, send)
                return
        await self._cors(scope, receive, send)
