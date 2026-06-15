"""``KorTravelMapSettings`` — 본 라이브러리 런타임 설정 (pydantic-settings v2).

본 모듈은 환경변수 ``KOR_TRAVEL_MAP_*``와 ``.env``에서 로딩되는 설정 클래스를
제공한다. 모든 secret은 ``SecretStr``로 보관되어 로그/repr 노출 방지.

ADR 참조
--------
- ADR-005 — 디버그 UI 인증 없음 + 내부망 전용
- ADR-007 — PostgreSQL 16 + PostGIS 3.5 + SQLAlchemy 2 async + asyncpg
- ADR-015 — S3 호환 객체 저장소 (RustFS 1차, MinIO/Ceph/R2 swap)
- ADR-019 — KST aware datetime
- ADR-030 — in-memory 캐시 금지 (``functools.cache`` 한정 narrow 예외)

호출자 (TripMate) 측 사용:
    >>> from kortravelmap.settings import KorTravelMapSettings
    >>> settings = KorTravelMapSettings()  # 환경변수에서 로딩
    >>> settings.pg_dsn.get_secret_value()
    'postgresql+asyncpg://kor_travel_map:***@localhost:5432/kor_travel_map'

Sprint 1 (본 PR#17) — minimum settings만. Provider key 등은 후속 sprint에
필요한 시점에 점진 추가.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogFormat = Literal["json", "console"]


class KorTravelMapSettings(BaseSettings):
    """본 라이브러리 런타임 설정.

    환경변수 prefix는 ``KOR_TRAVEL_MAP_``. ``.env`` 파일은 권한 600 (``AGENTS.md
    §"DO NOT" #8``). secret 필드는 모두 ``SecretStr``로 wrap.

    Sprint 1 시점에는 PostgreSQL DSN + 객체 저장소 + 로깅 최소 필드만.
    Provider API keys는 Sprint 2부터 provider별 추가
    (``docs/external-apis.md`` §2 환경변수 카탈로그).
    """

    model_config = SettingsConfigDict(
        env_prefix="KOR_TRAVEL_MAP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 다른 prefix env (예: TRIPMATE_*) 침범 차단
    )

    # ── PostgreSQL (ADR-007) ─────────────────────────────────────────────
    pg_dsn: SecretStr = Field(
        default=SecretStr(
            "postgresql+asyncpg://kor_travel_map:changeme@localhost:5432/kor_travel_map"
        ),
        description=(
            "SQLAlchemy 2 async DSN. ``postgresql+asyncpg://...`` 권장. "
            "운영 환경에서는 systemd EnvironmentFile 또는 vault에서 주입."
        ),
    )

    # ── 객체 저장소 (S3 호환, ADR-015) ─────────────────────────────────
    object_store_endpoint_url: str | None = Field(
        default="http://127.0.0.1:12101",
        description=(
            "RustFS/MinIO/Ceph/R2 endpoint URL. 로컬 RustFS 표준 S3 API 예시는 "
            "``http://127.0.0.1:12101``이고 console은 ``http://127.0.0.1:12105``. "
            "``None``이면 AWS S3 기본 endpoint 사용."
        ),
    )
    object_store_bucket: str = Field(
        default="kor-travel-map",
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
        default="http://127.0.0.1:12101/kor-travel-map",
        description="feature_files 공개 URL base. CDN/프록시 사용 시 해당 URL로 교체.",
    )
    object_store_prefix: str = Field(
        default="features",
        description="feature_files 객체 key prefix.",
    )
    offline_upload_bucket: str = Field(
        default="kor-travel-map-uploads",
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

    # ── kor-travel-geo REST API v2 (geocoding, ADR-006/044) ─────────────────
    kor_travel_geo_base_url: str | None = Field(
        default=None,
        description=(
            "kor-travel-geo REST 서비스 base URL (로컬 기본 예: ``http://127.0.0.1:12501``). "
            "``None``이면 정/역지오코딩 보강 비활성 (좌표만으로 적재). 호출 측이 "
            "이 URL로 ``httpx.AsyncClient(base_url=...)``를 만들어 "
            "``KorTravelGeoRestClient``에 주입한다 (python 패키지/DB 의존 없음)."
        ),
    )
    kor_travel_geo_timeout_seconds: float = Field(
        default=10.0,
        ge=0.2,
        le=30.0,
        description="kor-travel-geo REST 호출 timeout seconds.",
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
    opinet_scope_mode: Literal["disabled", "bbox", "poi_cache_target"] = Field(
        default="disabled",
        description=(
            "OpiNet 주유소 적재 scope (전국 dump endpoint 부재). ``disabled``(미적재) / "
            "``bbox``(operator bbox 1개) / ``poi_cache_target``(opinet POI cache target "
            "주변 enumerate). env ``OPINET_SCOPE_MODE``."
        ),
    )
    opinet_scope_bbox: str | None = Field(
        default=None,
        description=(
            "``bbox`` 모드 영역 ``min_lon,min_lat,max_lon,max_lat`` (WGS84, 콤마 구분). "
            "env ``OPINET_SCOPE_BBOX``."
        ),
    )
    opinet_scope_radius_m: int = Field(
        default=5000,
        ge=500,
        le=5000,
        description=(
            "``iter_stations_in_bbox`` aroundAll 격자 반경(m, ≤5km OpiNet 한계). "
            "env ``OPINET_SCOPE_RADIUS_M``."
        ),
    )
    kma_weather_extra_points: str | None = Field(
        default=None,
        description=(
            "KMA weather 적재 대상 추가 좌표 ``lon,lat;lon,lat`` (WGS84, 세미콜론 "
            "구분, T-219a). 기본 대상은 활성 POI cache target 좌표이며 본 설정으로 "
            "대표 지점을 명시 추가한다. 파서는 "
            "``kortravelmap.providers.kma.parse_weather_extra_points``. "
            "env ``KMA_WEATHER_EXTRA_POINTS``."
        ),
    )
    kma_weather_max_grids_per_run: int = Field(
        default=50,
        ge=1,
        le=500,
        description=(
            "KMA weather asset 1 run당 호출 격자 상한(T-219a) — data.go.kr 일일 "
            "한도 보호. 초과분은 다음 run으로(정렬 안정). "
            "env ``KMA_WEATHER_MAX_GRIDS_PER_RUN``."
        ),
    )
    kma_mid_region_features: str | None = Field(
        default=None,
        description=(
            "KMA 중기예보 region→feature 매핑 JSON (T-219c). 중기는 격자가 아니라 "
            "region 체계라 운영자가 광역시도 대표 feature를 명시 주입한다 — "
            '미설정이면 mid asset skip. 형식 ``[{"land_reg_id": "11B00000", '
            '"ta_reg_id": "11B10101", "feature_ids": ["..."]}]``. 파서는 '
            "``kortravelmap.providers.kma.parse_mid_region_features``. "
            "env ``KOR_TRAVEL_MAP_KMA_MID_REGION_FEATURES``."
        ),
    )
    kma_weather_alert_lookback_days: int = Field(
        default=3,
        ge=1,
        le=30,
        description=(
            "KMA 특보(getWthrWrnList) 조회 rolling window 일수(T-219c) — 오늘 "
            "포함 N일. env ``KOR_TRAVEL_MAP_KMA_WEATHER_ALERT_LOOKBACK_DAYS``."
        ),
    )
    dagster_address_validation: Literal["strict", "drop", "off"] = Field(
        default="strict",
        description=(
            "Dagster feature 적재 주소/좌표 검증 정책(#376). ``strict``(error "
            "이슈 1건이라도 있으면 run 실패 — 종전 동작) / ``drop``(error row만 "
            "제외하고 적재, 제외 건수·feature_id는 run 메타데이터에 기록) / "
            "``off``(전부 적재, 검증 요약만 기록). 실데이터에는 소수의 주소↔좌표 "
            "불일치가 항상 존재하므로 운영은 ``drop`` 권장 — 격리분은 "
            "``/admin/issues`` geocode retry/manual override로 처리. "
            "env ``KOR_TRAVEL_MAP_DAGSTER_ADDRESS_VALIDATION``."
        ),
    )
    mcst_max_items_per_dataset: int = Field(
        default=50000,
        ge=1,
        le=100000,
        description=(
            "MCST 파일데이터 CSV dataset당 1 run 최대 row 수(#395) — 이상 "
            "응답(비정상 거대 CSV) 방어. 기본 50000은 2026-06-12 live 실측 최대 "
            "(leisure_activity_facilities_csv 24,537행)의 약 2배 여유. "
            "env ``KOR_TRAVEL_MAP_MCST_MAX_ITEMS_PER_DATASET``."
        ),
    )
    krheritage_kind_codes: str = Field(
        default="11,12,13,15,16",
        description=(
            "국가유산 items live fetch 대상 종목코드(ccbaKdcd) comma 목록(#380). "
            "기본 11 국보/12 보물/13 사적/15 천연기념물/16 명승. "
            "env ``KOR_TRAVEL_MAP_KRHERITAGE_KIND_CODES``."
        ),
    )
    krheritage_max_items_per_run: int = Field(
        default=5000,
        ge=1,
        le=100000,
        description=(
            "국가유산 items 1 run 최대 record 수(#380) — detail이 1건당 1콜이라 "
            "과호출 방어(``mcst_max_items_per_dataset`` 패턴). "
            "env ``KOR_TRAVEL_MAP_KRHERITAGE_MAX_ITEMS_PER_RUN``."
        ),
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
            "부재 시 fetcher가 명확히 실패. env ``KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH``."
        ),
    )
    knps_point_dataset_key: str = Field(
        default="knps_visitor_centers",
        description=(
            "KNPS point feature-load asset이 적재할 file dataset key "
            "(``knps.file_datasets()`` 카탈로그 key). fetcher와 asset의 "
            "``knps_point_dataset_key`` resource가 같은 값을 쓰도록 한다."
        ),
    )
    knps_geometry_dataset_key: str = Field(
        default="knps_trails",
        description=(
            "KNPS geometry(route/area) feature-load asset이 적재할 file dataset key."
        ),
    )
    kor_travel_concierge_base_url: str | None = Field(
        default=None,
        description=(
            "kor-travel-concierge REST API base URL. **scheme+host[:port]만** 넣는다 "
            "(경로 segment 금지 — fetcher가 절대경로 ``/api/v1/...``로 호출하므로 base의 "
            "경로는 httpx join에서 버려진다, C-07). 예: ``http://127.0.0.1:12601``. 설정 시 "
            "Dagster ``kor_travel_concierge_youtube_features`` resource가 "
            "``/api/v1/features/{snapshot|changes}``를 pull한다(ADR-053/ADR-050)."
        ),
    )
    kor_travel_concierge_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "kor-travel-concierge 외부 호출용 ``X-API-Key`` 값. kor-travel-concierge 운영 "
            "환경의 ``API_KEYS`` 중 하나와 일치해야 한다."
        ),
    )
    kor_travel_concierge_feature_sync_endpoint: Literal["snapshot", "changes"] = Field(
        default="snapshot",
        description=(
            "kor-travel-concierge feature pull endpoint 선택. ``snapshot``은 full sync, "
            "``changes``는 incremental cursor sync."
        ),
    )
    kor_travel_concierge_feature_cursor: str | None = Field(
        default=None,
        description=(
            "kor-travel-concierge incremental 시작 cursor. 운영 cursor 영속화가 붙기 전 "
            "초기 wiring/수동 재개용 값."
        ),
    )
    kor_travel_concierge_feature_page_size: int = Field(
        default=200,
        ge=1,
        le=500,
        description=(
            "kor-travel-concierge feature export page size. 상한 500은 kor-travel-concierge "
            "``FEATURE_EXPORT_LIMIT_MAX``와 정렬(초과분은 서버가 silent 클램프하므로 "
            "계약상 상한을 일치시킨다, T-217a)."
        ),
    )
    kor_travel_concierge_timeout_seconds: float = Field(
        default=20.0,
        ge=0.2,
        le=60.0,
        description="kor-travel-concierge REST 호출 timeout seconds.",
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
