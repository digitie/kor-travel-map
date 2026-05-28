"""``krtour.map_debug_ui.settings`` — 디버그/관리 UI runtime 설정.

``Pydantic Settings`` 기반. ``KRTOUR_MAP_DEBUG_UI_*`` 환경변수 prefix.

PR#47 (2026-05-28) — provider raw API 키 8 종 추가. ETL preview의
`?source=live` 분기에서 사용. 각 provider repo의 ``.env``에서 같은 이름으로
박혀 있을 것을 가정 — `python-kma-api`의 `.env`는 ``KMA_SERVICE_KEY``를 쓰니
본 lib도 ``KRTOUR_MAP_DEBUG_UI_KMA_SERVICE_KEY``로 박는다 (Pydantic Settings
의 prefix). 즉 사용자는 각 provider repo의 .env에서 키 값을 복사해 본 lib
.env에 prefix만 붙여 옮긴다.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
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

    # ── Provider API keys (PR#47, source=live 활성화용) ──────────────────
    #
    # 각 provider repo의 `.env`에 박힌 이름과 동일 (prefix `KRTOUR_MAP_DEBUG_UI_`
    # 만 추가). 예: `python-kma-api`의 `.env`가 ``KMA_SERVICE_KEY=...``라면 본
    # lib는 ``KRTOUR_MAP_DEBUG_UI_KMA_SERVICE_KEY=...``로 박는다. 미설정 시
    # ``None`` — `?source=live` 라우터는 503 응답.
    #
    # ADR-005 + ADR-035: 운영 시 Cloudflare Tunnel / SSO 뒤. 코드 외부 보호.
    # 키는 SecretStr — 로그/JSON 직렬화에 plaintext 노출 방지.

    kma_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "기상청 공공데이터포털 service key. `python-kma-api/.env` 의 "
            "``KMA_SERVICE_KEY`` 값과 동일."
        ),
    )
    opinet_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "OpiNet API key. `python-opinet-api/.env` 의 "
            "``OPINET_SERVICE_KEY``."
        ),
    )
    datagokr_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "data.go.kr 표준데이터 service key. `python-datagokr-api/.env` 의 "
            "``DATAGOKR_SERVICE_KEY``."
        ),
    )
    visitkorea_service_key: SecretStr | None = Field(
        default=None,
        description="`python-visitkorea-api/.env` 의 ``VISITKOREA_SERVICE_KEY``.",
    )
    krex_service_key: SecretStr | None = Field(
        default=None,
        description="`python-krex-api/.env` 의 ``KREX_SERVICE_KEY``.",
    )
    knps_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "`python-knps-api`는 키 없는 file dataset 기반(ADR-028 amendment) "
            "이라 보통 불필요. 일부 보조 endpoint에는 사용 가능."
        ),
    )
    airkorea_service_key: SecretStr | None = Field(
        default=None,
        description="`python-airkorea-api/.env` 의 ``AIRKOREA_SERVICE_KEY``.",
    )
    krforest_service_key: SecretStr | None = Field(
        default=None,
        description="`python-krforest-api/.env` 의 ``KRFOREST_SERVICE_KEY``.",
    )
