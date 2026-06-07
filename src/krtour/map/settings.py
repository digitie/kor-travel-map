"""``KrtourMapSettings`` — 본 라이브러리 런타임 설정 (pydantic-settings v2).

본 모듈은 환경변수 ``KRTOUR_MAP_*``와 ``.env``에서 로딩되는 설정 클래스를
제공한다. 모든 secret은 ``SecretStr``로 보관되어 로그/repr 노출 방지.

ADR 참조
--------
- ADR-005 — 디버그 UI 인증 없음 + 내부망 전용
- ADR-007 — PostgreSQL 16 + PostGIS 3.5 + SQLAlchemy 2 async + asyncpg
- ADR-015 — S3 호환 객체 저장소 (RustFS 1차, MinIO/Ceph/R2 swap)
- ADR-019 — KST aware datetime
- ADR-030 — in-memory 캐시 금지 (``functools.cache`` 한정 narrow 예외)

호출자 (TripMate) 측 사용:
    >>> from krtour.map.settings import KrtourMapSettings
    >>> settings = KrtourMapSettings()  # 환경변수에서 로딩
    >>> settings.pg_dsn.get_secret_value()
    'postgresql+asyncpg://krtour_map:***@localhost:5432/krtour_map'

Sprint 1 (본 PR#17) — minimum settings만. Provider key 등은 후속 sprint에
필요한 시점에 점진 추가.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogFormat = Literal["json", "console"]


class KrtourMapSettings(BaseSettings):
    """본 라이브러리 런타임 설정.

    환경변수 prefix는 ``KRTOUR_MAP_``. ``.env`` 파일은 권한 600 (``AGENTS.md
    §"DO NOT" #8``). secret 필드는 모두 ``SecretStr``로 wrap.

    Sprint 1 시점에는 PostgreSQL DSN + 객체 저장소 + 로깅 최소 필드만.
    Provider API keys는 Sprint 2부터 provider별 추가
    (``docs/external-apis.md`` §2 환경변수 카탈로그).
    """

    model_config = SettingsConfigDict(
        env_prefix="KRTOUR_MAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 다른 prefix env (예: TRIPMATE_*) 침범 차단
    )

    # ── PostgreSQL (ADR-007) ─────────────────────────────────────────────
    pg_dsn: SecretStr = Field(
        default=SecretStr(
            "postgresql+asyncpg://krtour_map:changeme@localhost:5432/krtour_map"
        ),
        description=(
            "SQLAlchemy 2 async DSN. ``postgresql+asyncpg://...`` 권장. "
            "운영 환경에서는 systemd EnvironmentFile 또는 vault에서 주입."
        ),
    )

    # ── 객체 저장소 (S3 호환, ADR-015) ─────────────────────────────────
    object_store_endpoint_url: str | None = Field(
        default="http://127.0.0.1:9003",
        description=(
            "RustFS/MinIO/Ceph/R2 endpoint URL. 로컬 RustFS 표준 S3 API 예시는 "
            "``http://127.0.0.1:9003``이고 console은 ``http://127.0.0.1:9004``. "
            "``None``이면 AWS S3 기본 endpoint 사용."
        ),
    )
    object_store_bucket: str = Field(
        default="krtour-map",
        description="feature_files 저장 bucket 이름.",
    )
    object_store_region: str = Field(
        default="us-east-1",
        description="S3 호환 client region. RustFS/MinIO 로컬 기본은 ``us-east-1``.",
    )
    object_store_access_key_id: SecretStr | None = Field(
        default=None,
        description="S3 호환 access key ID. boto3 표준 chain도 사용 가능.",
    )
    object_store_secret_access_key: SecretStr | None = Field(
        default=None,
        description="S3 호환 secret access key.",
    )
    object_store_public_base_url: str | None = Field(
        default="http://127.0.0.1:9003/krtour-map",
        description="feature_files 공개 URL base. CDN/프록시 사용 시 해당 URL로 교체.",
    )
    object_store_prefix: str = Field(
        default="features",
        description="feature_files 객체 key prefix.",
    )
    offline_upload_bucket: str = Field(
        default="krtour-uploads",
        description="admin offline upload 원본 파일 보존 bucket (ADR-045 D-14).",
    )
    offline_upload_prefix: str = Field(
        default="offline-uploads",
        description="admin offline upload 원본 파일 객체 key prefix.",
    )
    offline_upload_max_bytes: int = Field(
        default=100 * 1024 * 1024,
        gt=0,
        description=(
            "admin offline upload 1개 파일 최대 크기(bytes). 라우터는 "
            "Content-Length 사전 차단과 실제 read 상한으로 이 값을 강제한다."
        ),
    )

    @property
    def object_store_access_key(self) -> SecretStr | None:
        """이전 문서 예시의 짧은 속성명 호환 alias."""
        return self.object_store_access_key_id

    @property
    def object_store_secret_key(self) -> SecretStr | None:
        """이전 문서 예시의 짧은 속성명 호환 alias."""
        return self.object_store_secret_access_key

    # ── kraddr-geo REST API v2 (geocoding, ADR-006/044) ─────────────────
    kraddr_geo_base_url: str | None = Field(
        default=None,
        description=(
            "kraddr-geo REST 서비스 base URL (로컬 기본 예: ``http://127.0.0.1:9001``). "
            "``None``이면 정/역지오코딩 보강 비활성 (좌표만으로 적재). 호출 측이 "
            "이 URL로 ``httpx.AsyncClient(base_url=...)``를 만들어 "
            "``KraddrGeoRestClient``에 주입한다 (python 패키지/DB 의존 없음)."
        ),
    )
    kraddr_geo_timeout_seconds: float = Field(
        default=10.0,
        ge=0.2,
        le=30.0,
        description="kraddr-geo REST 호출 timeout seconds.",
    )

    # ── Provider API credentials (Dagster resource wiring, ADR-044/045) ──
    data_go_kr_service_key: SecretStr | None = Field(
        default=None,
        description=(
            "data.go.kr gateway 공통 service key. source env는 "
            "``DATA_GO_KR_SERVICE_KEY``이며 datagokr/krheritage/MOIS 계열 provider "
            "resource가 참조한다."
        ),
    )
    opinet_api_key: SecretStr | None = Field(
        default=None,
        description="OpiNet certkey. source env는 ``OPINET_API_KEY``.",
    )
    krex_ex_api_key: SecretStr | None = Field(
        default=None,
        description="한국도로공사 EX OpenAPI key. source env는 ``KEX_GO_API_KEY``.",
    )
    krex_go_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "KREX data.go.kr standard/openapi key. source env는 "
            "``DATA_GO_KR_SERVICE_KEY``이며 ``data_go_kr_service_key``와 같은 값일 수 "
            "있다."
        ),
    )
    mois_source_db_path: str | None = Field(
        default=None,
        description=(
            "미리 sync된 MOIS 소스 SQLite DB 경로(Phase A 산출물). 미설정/파일 "
            "부재 시 fetcher가 명확히 실패. env ``KRTOUR_MAP_MOIS_SOURCE_DB_PATH``."
        ),
    )

    # ── 로깅 ─────────────────────────────────────────────────────────────
    log_level: str = Field(
        default="INFO",
        description=(
            "structlog 로깅 레벨. ``DEBUG``/``INFO``/``WARNING``/``ERROR``. "
            "운영 기본 ``INFO``."
        ),
    )
    log_format: LogFormat = Field(
        default="json",
        description="``json`` (운영) 또는 ``console`` (로컬 개발).",
    )

    # ── 옵션 동작 ─────────────────────────────────────────────────────────
    log_api_calls: bool = Field(
        default=False,
        description=(
            "True 시 provider 호출 횟수를 ``ops.api_call_log`` 테이블에 "
            "기록 (``docs/external-apis.md §4``)."
        ),
    )

    # Sprint 2~5에서 추가될 필드 (현 시점 미정의):
    #   - settings for Record Linkage 임계값 override (ADR-016).
    #   - settings for opening_hours 시간대 정책 (ADR-019).
