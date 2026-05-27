"""``krtour.map_debug_ui.settings`` — 디버그/관리 UI runtime 설정.

``Pydantic Settings`` 기반. ``KRTOUR_MAP_DEBUG_UI_*`` 환경변수 prefix.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["DebugUiSettings"]


class DebugUiSettings(BaseSettings):
    """디버그/관리 UI 백엔드 설정 (`KRTOUR_MAP_DEBUG_UI_*` env prefix).

    ADR-005 + ADR-035: 인증 키 자체는 본 패키지에 없음 — 네트워크 계층 책임.
    `host`는 ``127.0.0.1`` 기본 + ``0.0.0.0`` 바인드 시 호출자(uvicorn) 측에서
    경고 로그 권고.
    """

    model_config = SettingsConfigDict(
        env_prefix="KRTOUR_MAP_DEBUG_UI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(
        default="127.0.0.1",
        description=(
            "FastAPI bind host. 기본 localhost — 운영 시 Cloudflare Tunnel/"
            "SSO 게이트웨이 뒤 (ADR-035)."
        ),
    )
    port: int = Field(
        default=8087,
        description="FastAPI bind port. 기본 8087 (메인 lib 다른 서비스와 충돌 회피).",
    )
    log_level: str = Field(
        default="info",
        description="uvicorn log level — debug/info/warning/error.",
    )
    debug_routes_enabled: bool = Field(
        default=True,
        description=(
            "``/debug/...`` 라우터 활성 여부. 프로덕션 admin-only 운영 시 False로 "
            "내려 두면 발견 reduce. ``/admin/...`` 운영 라우터는 별도 flag (Sprint 4+)."
        ),
    )
