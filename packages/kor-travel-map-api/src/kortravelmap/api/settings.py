"""``kortravelmap.api.settings`` — REST/admin API runtime 설정."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["ApiSettings"]


class ApiSettings(BaseSettings):
    """디버그/관리 API 백엔드 설정 (`KOR_TRAVEL_MAP_API_*` env prefix).

    public read는 API key/service token, admin mutation은 trusted frontend proxy
    actor/secret을 사용한다. 네트워크 계층 SSO/IP allowlist도 함께 적용한다.
    `host`는 ``127.0.0.1`` 기본이다.
    """

    model_config = SettingsConfigDict(
        env_prefix="KOR_TRAVEL_MAP_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
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
            "``/ops/...`` 운영 라우터 활성 여부. None이면 "
            "``features_routes_enabled`` 값을 따른다. DB 없는 부팅 검증에서는 "
            "관측·pipeline·dataset API를 함께 닫는다."
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
        validation_alias="KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
        description=(
            "Next.js admin frontend proxy가 FastAPI admin API 호출 시 넣는 server-only "
            "secret. 설정되면 ``/v1/admin/*`` 요청은 허용된 peer CIDR + "
            "``X-Kor-Travel-Map-Admin-Proxy-Secret`` + "
            "``X-Kor-Travel-Map-Actor``가 모두 맞아야 통과한다. 미설정이면 기존 "
            "로컬/테스트 하위호환으로 admin gate를 강제하지 않는다. API와 frontend가 "
            "공유하는 env 정본은 ``KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET``이다."
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
    dagster_termination_poll_interval_seconds: float = Field(
        default=0.25,
        ge=0.05,
        le=5.0,
        description="Dagster run 종료 재확인 poll 간격(초).",
    )
    dagster_termination_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="SAFE_TERMINATE 뒤 terminal 상태를 기다리는 전체 제한 시간(초).",
    )
    mois_source_sync_ttl_hours: int = Field(
        default=24,
        ge=0,
        validation_alias="KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS",
        description=(
            "MOIS 적재 요청 전 mois_localdata_source_sync 최근 SUCCESS run을 "
            "유효하게 보는 최대 경과 시간. Dagster/source 정본과 같은 "
            "KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS를 읽는다. 0이면 "
            "MOIS 적재 요청을 차단한다."
        ),
    )
    pipeline_cancellation_retry_after_seconds: int = Field(
        default=3,
        ge=1,
        le=300,
        description="pipeline cancellation 409/502/503 Retry-After 초.",
    )
    pipeline_cancellation_root_retry_limit: int = Field(
        default=3,
        ge=1,
        le=10,
        description="preliminary resolve와 lease 사이 canonical root 변경 재시도 횟수.",
    )
    pipeline_cancellation_lease_reload_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
        description="lease 경합 때 winner의 durable attempt를 bounded reload하는 횟수.",
    )
    pipeline_cancellation_lease_reload_interval_seconds: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="lease loser의 DB-only current attempt 재조회 간격(초).",
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
