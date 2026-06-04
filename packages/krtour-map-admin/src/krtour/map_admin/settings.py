"""``krtour.map_admin.settings`` — 디버그/관리 UI runtime 설정.

``Pydantic Settings`` 기반. ``KRTOUR_MAP_ADMIN_*`` 환경변수 prefix.

PR#47 (2026-05-28) — provider raw API 키 8 종 추가. ETL preview의
`?source=live` 분기에서 사용. 각 provider repo의 ``.env``에서 같은 이름으로
박혀 있을 것을 가정 — `python-kma-api`의 `.env`는 ``KMA_SERVICE_KEY``를 쓰니
본 lib도 ``KRTOUR_MAP_ADMIN_KMA_SERVICE_KEY``로 박는다 (Pydantic Settings
의 prefix). 즉 사용자는 각 provider repo의 .env에서 키 값을 복사해 본 lib
.env에 prefix만 붙여 옮긴다.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["AdminSettings"]


class AdminSettings(BaseSettings):
    """디버그/관리 UI 백엔드 설정 (`KRTOUR_MAP_ADMIN_*` env prefix).

    ADR-005 + ADR-035: 인증 키 자체는 본 패키지에 없음 — 네트워크 계층 책임.
    `host`는 ``127.0.0.1`` 기본 + ``0.0.0.0`` 바인드 시 호출자(uvicorn) 측에서
    경고 로그 권고.
    """

    model_config = SettingsConfigDict(
        env_prefix="KRTOUR_MAP_ADMIN_",
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
        default=9011,
        description="FastAPI bind port. 기본 9011 (krtour-map 고정 API 포트).",
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
    features_routes_enabled: bool = Field(
        default=True,
        description=(
            "``/features/...`` 조회 라우터 활성 여부. feature 적재 후 지도/목록 "
            "조회용 (ADR-035). DB(``KRTOUR_MAP_PG_DSN``) 연결 필요 — DB 없는 "
            "환경에서는 False로 내려 import/기동만 검증."
        ),
    )
    admin_routes_enabled: bool | None = Field(
        default=None,
        description=(
            "``/admin/...`` 운영 라우터 활성 여부. None이면 "
            "``features_routes_enabled`` 값을 따른다. DB 없는 부팅 검증에서는 "
            "features/admin을 함께 False로 내려 write surface를 닫는다."
        ),
    )
    ops_routes_enabled: bool | None = Field(
        default=None,
        description=(
            "``/ops/...``와 Dagster summary 라우터 활성 여부. None이면 "
            "``features_routes_enabled`` 값을 따른다. DB 없는 부팅 검증에서는 "
            "ops/dagster 조회도 함께 닫는다."
        ),
    )
    cors_allow_origins: list[str] = Field(
        default=[
            "http://localhost:9012",
            "http://127.0.0.1:9012",
        ],
        description=(
            "CORS 허용 origin 목록. frontend(Next.js dev/start, 9012)가 브라우저에서 "
            "backend(9011)로 cross-origin fetch하므로 필요. 내부 debug 도구라 "
            "기본은 localhost frontend만 (ADR-005 — 네트워크 계층이 외부 차단). "
            "env override는 JSON 배열."
        ),
    )
    dagster_url: str = Field(
        default="http://127.0.0.1:9013",
        description=(
            "Dagster webserver base URL. admin UI embed와 backend GraphQL 조회에 "
            "사용한다. Docker API 컨테이너에서는 보통 ``http://dagster:9013``."
        ),
    )
    dagster_graphql_url: str | None = Field(
        default=None,
        description=(
            "Dagster GraphQL endpoint override. 미설정이면 "
            "``{dagster_url}/graphql``로 계산한다."
        ),
    )
    dagster_request_timeout_seconds: float = Field(
        default=3.0,
        ge=0.2,
        le=30.0,
        description="Dagster GraphQL 조회 timeout seconds.",
    )

    # ── Provider API keys (PR#47, source=live 활성화용) ──────────────────
    #
    # 각 provider repo의 `.env`에 박힌 이름과 동일 (prefix `KRTOUR_MAP_ADMIN_`
    # 만 추가). 예: `python-kma-api`의 `.env`가 ``KMA_SERVICE_KEY=...``라면 본
    # lib는 ``KRTOUR_MAP_ADMIN_KMA_SERVICE_KEY=...``로 박는다. 미설정 시
    # ``None`` — `?source=live` 라우터는 503 응답.
    #
    # ADR-005 + ADR-035: 운영 시 Cloudflare Tunnel / SSO 뒤. 코드 외부 보호.
    # 키는 SecretStr — 로그/JSON 직렬화에 plaintext 노출 방지.

    kma_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "기상청 공공데이터포털(apis.data.go.kr) service key. **source: "
            "`python-kma-api/.env` 의 ``DATA_GO_KR_SERVICE_KEY``** (data.go.kr "
            "게이트웨이 공통키 — datagokr/krex/visitkorea와 동일 값일 수 있음). "
            "동네예보(단기/초단기) + weather_alerts fallback(getWthrWrnList)에서 사용."
        ),
    )
    kma_apihub_key: SecretStr | None = Field(
        default=None,
        description=(
            "기상청 API 허브(apihub.kma.go.kr) ``authKey``. data.go.kr "
            "``serviceKey``와 **다른 키** — `python-kma-api/.env` 의 "
            "``KMA_APIHUB_AUTH_KEY``(또는 ``KMA_APIHUB_KEY``). **KMA 소스 정책: "
            "data.go.kr이 primary, apihub는 fallback** (data.go.kr 소스 존재 시). "
            "특보현황(`kma_weather_alerts`)은 data.go.kr `getWthrWrnList`가 primary, "
            "이 apihub `wrn_now_data`(구조화 특보구역 REG_ID)는 data.go.kr 실패 시 "
            "fallback. **apihub는 API별 '활용신청' 필요**(미신청 시 HTTP 403)."
        ),
    )
    opinet_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "OpiNet API key. **source: `python-opinet-api/.env` 의 "
            "``OPINET_API_KEY``** (opinet.co.kr `certkey`)."
        ),
    )
    datagokr_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "data.go.kr 표준데이터 service key. **source: "
            "`python-datagokr-api/.env` 의 ``DATA_GO_KR_SERVICE_KEY``** "
            "(게이트웨이 공통키 — kma_service_key와 동일 값일 수 있음)."
        ),
    )
    visitkorea_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "VisitKorea TourAPI key. **source: `python-visitkorea-api/.env` 의 "
            "``KTO_DATA_GO_KR_SERVICE_KEY``** (또는 공통 ``DATA_GO_KR_SERVICE_KEY``)."
        ),
    )
    krex_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "한국도로공사 EX OpenAPI key. **source: `python-krex-api/.env` 의 "
            "``KEX_GO_API_KEY``** (data.ex.co.kr `key` — data.go.kr serviceKey와 다름)."
        ),
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
