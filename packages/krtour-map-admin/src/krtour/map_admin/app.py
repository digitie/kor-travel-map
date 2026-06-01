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
    ``uvicorn krtour.map_admin.app:app --host 127.0.0.1 --port 8087``

uvicorn 설정은 ``AdminSettings``(``KRTOUR_MAP_ADMIN_*`` env) 또는 호출자가
명시. ``host=0.0.0.0`` 직접 노출 금지 — Cloudflare Tunnel/SSO 게이트웨이 뒤에
둔다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from krtour.map_admin import __version__
from krtour.map_admin.routers import (
    etl_router,
    features_router,
    geocoding_router,
    health_router,
    mois_detail_router,
    version_router,
)
from krtour.map_admin.settings import AdminSettings

__all__ = ["app", "create_app"]


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
    )

    # frontend(Next.js dev 8610)가 브라우저에서 backend(8087)로 cross-origin
    # fetch → CORS 필요 (ADR-005: 내부 debug 도구, origin은 localhost frontend로
    # 한정). OpenAPI spec에는 영향 없음(미들웨어, ADR-031 drift gate 무관).
    if settings.cors_allow_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    if settings.debug_routes_enabled:
        application.include_router(health_router)
        application.include_router(version_router)
        application.include_router(etl_router)
        application.include_router(geocoding_router)

    if settings.features_routes_enabled:
        application.include_router(features_router)
        # Step D on-demand 상세는 DB(적재된 raw_data) 필요 → features와 동일 gate.
        if settings.debug_routes_enabled:
            application.include_router(mois_detail_router)

    return application


app: FastAPI = create_app()
"""모듈-레벨 FastAPI instance.

``uvicorn krtour.map_admin.app:app``로 직접 실행, ``scripts/export_openapi.
py``가 ``app.openapi()``를 호출.
"""
