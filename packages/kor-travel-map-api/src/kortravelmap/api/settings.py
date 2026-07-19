"""``kortravelmap.api.settings`` — REST/admin API runtime 설정."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["ApiSettings"]


def _deployable_secret_shape(raw: str) -> bool:
    """production 배포 가능한 secret 형태 — 앞뒤 공백 없는 32자 이상.

    ``docker/api-entrypoint.sh``의 admin proxy secret 검사와 같은 기준이다.
    내부 공백 금지는 ops token 전용 규칙이라 여기서는 강제하지 않는다.
    """

    return raw == raw.strip() and len(raw) >= 32


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
        hide_input_in_errors=True,
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
    profile: str = Field(
        default="local-dev",
        pattern="^(production|local-dev)$",
        description=(
            "실행 profile (ADR-066 D-1, T-VN-01/T-VN-02). ``production``은 "
            "fail-closed로 기동을 검증한다 — admin proxy secret(앞뒤 공백 없는 "
            "32자 이상) 필수, ops surface 활성 시 read/cancel token 필수, features "
            "surface 활성 시 ``public_api_key_required=True``와 service token(앞뒤 "
            "공백 없는 32자 이상) 필수, metrics endpoint 활성 시 metrics token "
            "필수, 인증 없는 ``/debug`` 라우터 비활성 필수. secret 미설정 "
            "local-dev fallback은 ``local-dev``에서만 동작한다. Docker "
            "image/compose 기본값은 production이고 코드 기본값은 local-dev다"
            "(비-Docker 로컬 하위호환). env ``KOR_TRAVEL_MAP_API_PROFILE``."
        ),
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
    metrics_token: SecretStr | None = Field(
        default=None,
        description=(
            "Prometheus scrape identity token (ADR-066 결정 4, T-VN-02). 설정되면 "
            "metrics endpoint는 ``Authorization: Bearer <token>``이 이 값과 "
            "일치(상수시간 비교)해야 한다. 미설정(None)이면 강제하지 않음"
            "(로컬 scrape 하위호환) — 단 production profile은 metrics endpoint "
            "활성 시 앞뒤 공백 없는 32자 이상 값을 필수화한다. admin proxy "
            "secret·service token·ops token들과 서로 달라야 한다. scrape 측은 "
            "Prometheus scrape_config의 ``authorization``(type Bearer)로 주입한다. "
            "env ``KOR_TRAVEL_MAP_API_METRICS_TOKEN``."
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
            "단 production profile은 features surface 활성 시 이 token을 앞뒤 공백 "
            "없는 32자 이상으로 필수화한다(ADR-066 T-VN-01). "
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
    ops_read_token: SecretStr | None = Field(
        default=None,
        validation_alias="KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        description=(
            "PinVi server가 canonical ``/v1/ops/datasets*``·"
            "``/v1/ops/pipeline*``의 GET을 호출할 때만 사용하는 API-only "
            "token. ``X-Kor-Travel-Map-Ops-Token``으로 전달하며 admin frontend "
            "BFF secret이나 public service token과 공유하지 않는다."
        ),
    )
    ops_cancel_token: SecretStr | None = Field(
        default=None,
        validation_alias="KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        description=(
            "PinVi server가 canonical import-job cancel endpoint 한 곳을 호출할 "
            "때만 사용하는 API-only token. read token과 달라야 하며 schedule, "
            "policy, update-request 등 다른 mutation 권한을 부여하지 않는다."
        ),
    )
    ops_principal_required: bool = Field(
        default=False,
        description=(
            "True면 API startup에 read/cancel token 쌍을 필수로 요구한다. 로컬은 "
            "False로 principal을 끌 수 있고 n150 production은 True를 주입한다."
        ),
    )
    legacy_ops_actor: str | None = Field(
        default=None,
        validation_alias="KOR_TRAVEL_MAP_API_OPS_ACTOR",
        exclude=True,
        repr=False,
        description="제거된 configurable ops actor 감지용 startup guard.",
    )
    admin_trusted_proxy_cidrs: list[str] = Field(
        default=["127.0.0.1/32", "::1/128"],
        description=(
            "admin frontend proxy로 신뢰할 FastAPI peer CIDR 목록. 현재 PC 단일 운용은 "
            "localhost만 허용한다. Docker/리버스 프록시 배포 시 프록시 CIDR을 명시한다."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _validate_ops_principal_provenance(cls, data: object) -> object:
        """missing/empty provenance를 보존해 부분 설정을 disabled로 접지 않는다."""

        if not isinstance(data, Mapping):
            return data

        missing = object()

        def _input_value(field_name: str, env_name: str) -> object:
            if field_name in data:
                return data[field_name]
            if env_name in data:
                return data[env_name]
            return missing

        read = _input_value(
            "ops_read_token",
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        )
        cancel = _input_value(
            "ops_cancel_token",
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        )
        if (read is missing) != (cancel is missing):
            # docker/api-entrypoint.sh와 동일 문구 (issue #742 lockstep).
            raise ValueError(
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN and "
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN must be configured together"
            )
        if read is missing:
            return data

        def _input_kind(value: object) -> str:
            raw = value.get_secret_value() if isinstance(value, SecretStr) else value
            if raw is None:
                return "none"
            if raw == "":
                return "empty"
            return "value"

        read_kind = _input_kind(read)
        cancel_kind = _input_kind(cancel)
        if read_kind != cancel_kind:
            raise ValueError(
                "ops read and cancel tokens must both be empty or both be non-empty"
            )
        return data

    @field_validator("ops_read_token", "ops_cancel_token", mode="before")
    @classmethod
    def _validate_ops_token_shape(cls, value: object) -> object:
        """빈 optional 값은 끄고, 활성 secret은 공백 없는 32자 이상으로 제한한다."""

        if value is None:
            return value
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str):
            return value
        if raw == "":
            return None
        if any(character.isspace() for character in raw) or len(raw) < 32:
            raise ValueError(
                "ops token must be non-empty, at least 32 characters, "
                "and contain no whitespace"
            )
        return value

    @field_validator("metrics_token", mode="before")
    @classmethod
    def _normalize_metrics_token(cls, value: object) -> object:
        """빈 문자열은 미설정(None)과 같은 opt-out으로 정규화한다.

        배포 가능한 형태(앞뒤 공백 없는 32자 이상)는 service token과 같은
        기준으로 production matrix(``assert_production_ready``)가 검사한다 —
        root ``.env.example``의 CHANGE_ME placeholder가 local-dev full-stack
        검증을 막지 않게 한다(T-VN-01 service token 패턴).
        """

        if value is None:
            return value
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(raw, str) and raw == "":
            return None
        return value

    @model_validator(mode="after")
    def _validate_ops_principal_pair(self) -> ApiSettings:
        """C6c principal은 read/cancel secret을 한 쌍으로만 활성화한다."""

        read = self.ops_read_token
        cancel = self.ops_cancel_token
        if self.legacy_ops_actor is not None:
            raise ValueError(
                "KOR_TRAVEL_MAP_API_OPS_ACTOR was removed; the audit actor is fixed"
            )
        if (read is None) != (cancel is None):
            raise ValueError(
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN and "
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN must be configured together"
            )
        if self.ops_principal_required and (read is None or cancel is None):
            raise ValueError(
                "ops principal is required but read/cancel tokens are not configured"
            )
        if (
            read is not None
            and cancel is not None
            and read.get_secret_value() == cancel.get_secret_value()
        ):
            raise ValueError("ops read and cancel tokens must be distinct")
        protected_secrets = {
            "admin proxy secret": self.admin_proxy_secret,
            "service token": self.service_token,
        }
        for ops_name, ops_token in (
            ("ops read token", read),
            ("ops cancel token", cancel),
        ):
            if ops_token is None:
                continue
            raw_ops_token = ops_token.get_secret_value()
            for protected_name, protected_secret in protected_secrets.items():
                if (
                    protected_secret is not None
                    and raw_ops_token == protected_secret.get_secret_value()
                ):
                    raise ValueError(
                        f"{ops_name} must be distinct from {protected_name}"
                    )
        return self

    @model_validator(mode="after")
    def _validate_metrics_token_distinct(self) -> ApiSettings:
        """scrape token은 다른 신뢰 경계 secret과 재사용을 금지한다 (T-VN-02)."""

        if self.metrics_token is None:
            return self
        raw_metrics_token = self.metrics_token.get_secret_value()
        for protected_name, protected_secret in (
            ("admin proxy secret", self.admin_proxy_secret),
            ("service token", self.service_token),
            ("ops read token", self.ops_read_token),
            ("ops cancel token", self.ops_cancel_token),
        ):
            if (
                protected_secret is not None
                and raw_metrics_token == protected_secret.get_secret_value()
            ):
                raise ValueError(
                    f"metrics token must be distinct from {protected_name}"
                )
        return self

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

    @property
    def is_production(self) -> bool:
        """production profile 여부 (ADR-066 fail-closed 검증 대상)."""

        return self.profile == "production"

    @property
    def resolved_admin_routes_enabled(self) -> bool:
        """``None``이면 features flag를 따르는 admin 라우터 활성 최종값."""

        if self.admin_routes_enabled is None:
            return self.features_routes_enabled
        return self.admin_routes_enabled

    @property
    def resolved_ops_routes_enabled(self) -> bool:
        """``None``이면 features flag를 따르는 ops 라우터 활성 최종값."""

        if self.ops_routes_enabled is None:
            return self.features_routes_enabled
        return self.ops_routes_enabled

    def assert_production_ready(self) -> None:
        """ADR-066 D-1의 production 불변식을 검증한다.

        secret 미설정 fallback(admin actor ``local-dev`` 통과, keyless public read,
        인증 없는 ``/debug``)은 non-production profile에서만 허용한다. Docker 밖
        배포도 같은 검증을 받도록 entrypoint(shell)가 아닌 settings에서 검사하며,
        admin/service secret 기준은 ``docker/api-entrypoint.sh``의 admin secret과
        동일하다(앞뒤 공백 없는 32자 이상).
        """

        if not self.is_production:
            return

        problems: list[str] = []

        admin_secret = (
            None
            if self.admin_proxy_secret is None
            else self.admin_proxy_secret.get_secret_value()
        )
        if admin_secret is None or not _deployable_secret_shape(admin_secret):
            problems.append(
                "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET must be set to at least 32 "
                "characters without surrounding whitespace"
            )

        if self.resolved_ops_routes_enabled and (
            self.ops_read_token is None or self.ops_cancel_token is None
        ):
            problems.append(
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN and "
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN must be configured while "
                "the ops surface is enabled"
            )

        if self.features_routes_enabled and not self.public_api_key_required:
            problems.append(
                "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED must be true while "
                "the public features surface is enabled"
            )

        if self.debug_routes_enabled:
            problems.append(
                "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED must be false because "
                "/debug routes have no authentication"
            )

        # ADR-066 결정 4 (T-VN-02) — `/metrics`는 scrape identity 경계로만
        # 노출한다. service token과 같은 배포 가능 형태 기준을 적용한다.
        metrics_token_raw = (
            None if self.metrics_token is None else self.metrics_token.get_secret_value()
        )
        if self.prometheus_metrics_enabled:
            if metrics_token_raw is None or not _deployable_secret_shape(
                metrics_token_raw
            ):
                problems.append(
                    "KOR_TRAVEL_MAP_API_METRICS_TOKEN must be set to at least 32 "
                    "characters without surrounding whitespace while the "
                    "Prometheus metrics endpoint is enabled"
                )
        elif metrics_token_raw is not None and not _deployable_secret_shape(
            metrics_token_raw
        ):
            problems.append(
                "KOR_TRAVEL_MAP_API_METRICS_TOKEN must be at least 32 characters "
                "without surrounding whitespace when set"
            )

        service_token_raw = (
            None if self.service_token is None else self.service_token.get_secret_value()
        )
        if admin_secret is not None and admin_secret == service_token_raw:
            problems.append(
                "KOR_TRAVEL_MAP_API_SERVICE_TOKEN must be distinct from "
                "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET"
            )
        if self.features_routes_enabled:
            # D-1-2의 service secret: `/v1/features/batch` 같은 service surface가
            # public key로만 조용히 격하되지 않도록 features surface에서는 필수다.
            if service_token_raw is None or not _deployable_secret_shape(service_token_raw):
                problems.append(
                    "KOR_TRAVEL_MAP_API_SERVICE_TOKEN must be set to at least 32 "
                    "characters without surrounding whitespace while the public "
                    "features surface is enabled"
                )
        elif service_token_raw is not None and not _deployable_secret_shape(
            service_token_raw
        ):
            problems.append(
                "KOR_TRAVEL_MAP_API_SERVICE_TOKEN must be at least 32 characters "
                "without surrounding whitespace when set"
            )

        if problems:
            raise ValueError(
                "production profile is fail-closed (ADR-066): " + "; ".join(problems)
            )

    @model_validator(mode="after")
    def _validate_production_fail_closed(self) -> ApiSettings:
        """정상 settings 생성 시 production 불변식을 적용한다."""

        self.assert_production_ready()
        return self
