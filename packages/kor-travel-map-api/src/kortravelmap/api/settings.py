"""``kortravelmap.api.settings`` — 디버그/관리 API runtime 설정.

``Pydantic Settings`` 기반. ``KOR_TRAVEL_MAP_API_*`` 환경변수 prefix.

PR#47 (2026-05-28) — provider raw API 키 8 종 추가. ETL preview의
`?source=live` 분기에서 사용. 각 provider repo의 ``.env``에서 같은 이름으로
박혀 있을 것을 가정 — `python-kma-api`의 `.env`는 ``KMA_SERVICE_KEY``를 쓰니
본 lib도 ``KOR_TRAVEL_MAP_API_KMA_SERVICE_KEY``로 박는다 (Pydantic Settings
의 prefix). 즉 사용자는 각 provider repo의 .env에서 키 값을 복사해 본 lib
.env에 prefix만 붙여 옮긴다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["ApiSettings"]


class ApiSettings(BaseSettings):
    """디버그/관리 API 백엔드 설정 (`KOR_TRAVEL_MAP_API_*` env prefix).

    ADR-005 + ADR-035: 인증 키 자체는 본 패키지에 없음 — 네트워크 계층 책임.
    `host`는 ``127.0.0.1`` 기본 + ``0.0.0.0`` 바인드 시 호출자(uvicorn) 측에서
    경고 로그 권고.
    """

    model_config = SettingsConfigDict(
        env_prefix="KOR_TRAVEL_MAP_API_",
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
        default=12701,
        description=(
            "FastAPI bind port. 기본 12701 "
            "(kor-travel-docker-manager map API 포트)."
        ),
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
            "조회용 (ADR-035). DB(``KOR_TRAVEL_MAP_PG_DSN``) 연결 필요 — DB 없는 "
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
    api_call_log_enabled: bool = Field(
        default=False,
        description=(
            "True면 모든 API 호출을 ops.api_call_log에 best-effort 기록"
            "(opt-in, 기본 off)."
        ),
    )
    prometheus_metrics_enabled: bool = Field(
        default=True,
        description=(
            "True면 Prometheus pull scrape용 metrics endpoint와 HTTP request "
            "duration/count/in-flight/response-size 및 DB query duration/count "
            "계측을 활성화한다. 기본 path는 /metrics."
        ),
    )
    prometheus_metrics_path: str = Field(
        default="/metrics",
        pattern=r"^/[A-Za-z0-9/_\-.]*$",
        description=(
            "Prometheus exposition endpoint path. kor-travel-docker-manager의 "
            "Prometheus는 API 포트(기본 12701)의 이 path를 scrape한다."
        ),
    )
    feature_change_review_mode: str = Field(
        default="require_review",
        pattern="^(require_review|immediate)$",
        description=(
            "place/event feature 추가·수정·삭제 요청 처리 모드. require_review면 "
            "ops.feature_change_requests에 pending으로 남기고 admin 승인 후 적용한다. "
            "immediate면 요청 transaction에서 바로 version 1로 적용한다."
        ),
    )
    cors_allow_origins: list[str] = Field(
        default=[
            "http://localhost:12705",
            "http://127.0.0.1:12705",
        ],
        description=(
            "CORS 허용 origin 목록. frontend(Next.js dev/start, 12705)가 브라우저에서 "
            "backend(12701)로 cross-origin fetch하므로 필요. 내부 debug 도구라 "
            "기본은 localhost frontend만 (ADR-005 — 네트워크 계층이 외부 차단). "
            "env override는 JSON 배열."
        ),
    )
    service_token: SecretStr | None = Field(
        default=None,
        description=(
            "외부 서비스 토큰(ADR-045 D-1 defense-in-depth, ADR-005 amendment). 설정되면 "
            "외부 surface(``/features`` · ``/curated-*`` · ``/categories`` · "
            "``/providers``)는 ``X-Kor-Travel-Map-Service-Token`` 헤더가 이 값과 일치(상수시간 "
            "비교)해야 한다. **미설정(None)이면 강제하지 않음**(intranet/dev 기본, 하위호환 — "
            "운영 인증의 1차 책임은 여전히 infra 계층의 reverse proxy/Cloudflare). "
            "``/health`` · ``/version`` · ``/debug`` · ``/admin`` · ``/ops``는 면제(liveness/"
            "operator는 proxy SSO). env ``KOR_TRAVEL_MAP_API_SERVICE_TOKEN``."
        ),
    )
    admin_proxy_secret: SecretStr | None = Field(
        default=None,
        description=(
            "Next.js admin frontend proxy가 FastAPI admin API 호출 시 넣는 server-only "
            "secret. 설정되면 ``/v1/admin/*`` 요청은 허용된 peer CIDR + "
            "``X-Kor-Travel-Map-Admin-Proxy-Secret`` + "
            "``X-Kor-Travel-Map-Actor``가 모두 맞아야 통과한다. 미설정이면 기존 "
            "로컬/테스트 하위호환으로 admin gate를 강제하지 않는다."
        ),
    )
    admin_trusted_proxy_cidrs: list[str] = Field(
        default=["127.0.0.1/32", "::1/128"],
        description=(
            "admin frontend proxy로 신뢰할 FastAPI peer CIDR 목록. 현재 PC 단일 운용은 "
            "localhost만 허용한다. Docker/리버스 프록시 배포 시 프록시 CIDR을 명시한다."
        ),
    )
    public_api_key_required: bool = Field(
        default=False,
        description=(
            "True면 public REST surface(`/v1/features`, `/v1/public`, `/v1/categories`, "
            "`/v1/providers`)에 VWorld 호환 `key` query 검증을 적용한다. trusted admin "
            "frontend proxy 또는 service-token 요청은 우회한다."
        ),
    )
    public_api_key_cache_ttl_s: int = Field(
        default=30,
        ge=0,
        le=3600,
        description=(
            "active public API key hash를 process-local 메모리에 보관하는 TTL초. "
            "생성/폐기 시 즉시 무효화하고, public hot path는 TTL 동안 DB 조회를 생략한다."
        ),
    )
    vworld_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "VWorld 지도 key. public_api_keys 테이블이 비어 있을 때 초기 전환 편의를 위해 "
            "같은 값을 public API key fallback으로 인정한다. 운영에서는 UI에서 생성한 "
            "key를 DB에 저장해 사용한다."
        ),
    )
    admin_destructive_enabled: bool = Field(
        default=True,
        description=(
            "파괴적 ``/admin`` 작업(restore/swap/feature deactivate/POI cache target "
            "delete) 허용 여부 kill-switch(defense-in-depth). False면 해당 엔드포인트는 "
            "403. 읽기/관측 전용 배포에서 내려 둔다. env "
            "``KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED``."
        ),
    )
    dagster_url: str = Field(
        default="http://127.0.0.1:12702",
        description=(
            "Dagster webserver base URL. admin UI embed와 backend GraphQL 조회에 "
            "사용한다. Docker API 컨테이너에서는 보통 ``http://dagster:12702``."
        ),
    )
    dagster_graphql_url: str | None = Field(
        default=None,
        description=(
            "Dagster GraphQL endpoint override. 미설정이면 "
            "``{dagster_url}/graphql``로 계산한다."
        ),
    )
    dagster_allowed_hosts: list[str] = Field(
        default=["127.0.0.1", "localhost", "::1", "dagster"],
        description=(
            "Backend가 Dagster GraphQL을 호출할 수 있는 host allowlist. "
            "SSRF 방지를 위해 ``dagster_url``과 ``dagster_graphql_url``의 scheme은 "
            "http/https, host는 이 목록 안의 값이어야 한다. Docker 기본 host는 "
            "``dagster``이고 로컬 기본은 ``127.0.0.1``."
        ),
    )
    dagster_request_timeout_seconds: float = Field(
        default=3.0,
        ge=0.2,
        le=30.0,
        description="Dagster GraphQL 조회 timeout seconds.",
    )
    dagster_repository_name: str = Field(
        default="__repository__",
        min_length=1,
        description="Dagster GraphQL launch selector repositoryName.",
    )
    dagster_repository_location_name: str = Field(
        default="kortravelmap.dagster.definitions",
        min_length=1,
        description="Dagster GraphQL launch selector repositoryLocationName.",
    )
    backup_root: Path = Field(
        default=Path("data/backups"),
        description="Standalone backup artifact root directory.",
    )
    backup_project_root: Path = Field(
        default=Path("."),
        description="Host project root used as cwd for backup/restore command execution.",
    )
    backup_script_path: Path = Field(
        default=Path("scripts/docker-backup.sh"),
        description="Backup script path. Relative paths are resolved from backup_project_root.",
    )
    restore_script_path: Path = Field(
        default=Path("scripts/docker-restore.sh"),
        description="Restore script path. Relative paths are resolved from backup_project_root.",
    )
    restore_swap_script_path: Path = Field(
        default=Path("scripts/docker-restore-swap.sh"),
        description=(
            "Restore hot-swap script path. Relative paths are resolved from backup_project_root."
        ),
    )
    backup_command_enabled: bool = Field(
        default=False,
        description=(
            "True면 /admin/backups command execution을 허용한다. 기본 False는 "
            "plan-only 모드."
        ),
    )
    backup_command_timeout_seconds: float = Field(
        default=1800.0,
        ge=1.0,
        le=21600.0,
        description="Backup/restore command execution timeout seconds.",
    )
    restore_app_db: str = Field(
        default="kor_travel_map_restore",
        min_length=1,
        description="Default staging app DB name for restore command plans.",
    )
    restore_dagster_db: str = Field(
        default="kor_travel_map_dagster_restore",
        min_length=1,
        description="Default staging Dagster DB name for restore command plans.",
    )
    restore_rustfs_volume: str = Field(
        default="kor-travel-map-rustfs-restore",
        min_length=1,
        description="Default staging RustFS Docker volume for restore command plans.",
    )

    # ── Provider API keys (PR#47, source=live 활성화용) ──────────────────
    #
    # 각 provider repo의 `.env`에 박힌 이름과 동일 (prefix `KOR_TRAVEL_MAP_API_`
    # 만 추가). 예: `python-kma-api`의 `.env`가 ``KMA_SERVICE_KEY=...``라면 본
    # lib는 ``KOR_TRAVEL_MAP_API_KMA_SERVICE_KEY=...``로 박는다. 미설정 시
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
