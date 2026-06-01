# backend-package.md — 메인 라이브러리 사양

본 문서는 `python-krtour-map` (메인 패키지)의 외부 표면(public API) reference다.
사용자 시나리오와 함수 시그니처 중심이다.

> **ADR-045 주의**: 메인 패키지의 Python API는 krtour-map 독립 프로그램 내부
> API/Dagster/테스트에서 사용하는 public Python 표면이다. TripMate 운영 연동은
> 이 Python API를 직접 import하지 않고 OpenAPI로 한다. Admin/OpenAPI 계약은
> `docs/openapi-admin-contract.md`를 기준으로 한다.

디버그 REST API/UI는 **별도 Python 패키지** `krtour-map-admin` (ADR-020)에
있고, 사양은 `docs/debug-ui-package.md`를 따른다. 메인 라이브러리는 FastAPI
의존이 없다.

## 1. 라이브러리 진입점

> **구현 현황 (2026-05-29)**: 본 절의 `AsyncKrtourMapClient`는 **설계 단계 API**다
> (`src/krtour/map/client/`는 아직 미구현, Sprint 3~4 예정). 현재 적재/조회는
> `krtour.map.infra.feature_repo`의 함수(`load_bundles` / `get_feature_row` /
> `features_in_bbox`)를 직접 호출하는 단계이며, debug-ui `/features` 라우터가 이를
> 사용한다 (PR#71~#73). client는 이 repo 함수들을 묶는 단일 진입점이 될 예정.

### 1.1 `AsyncKrtourMapClient` (설계)

```python
from krtour.map import AsyncKrtourMapClient, KrtourMapSettings
from sqlalchemy.ext.asyncio import create_async_engine

settings = KrtourMapSettings()  # KRTOUR_MAP_* 환경변수 자동 로드
engine = create_async_engine(settings.pg_dsn.get_secret_value())

async with AsyncKrtourMapClient(
    engine=engine,
    file_store=tripmate_rustfs_store,           # boto3 S3 client 호환
    kraddr_geo_client=tripmate_kraddr_client,   # 선택, 주소 보강용
    providers={                                  # provider별 client 주입
        "visitkorea": visitkorea_async_client,
        "mois": mois_async_client,
        "kma": kma_async_client,
        # ...
    },
    settings=settings,
) as client:
    ...
```

**책임 분리**:
- 라이브러리는 어떤 resource(engine, S3 client, provider client)도 스스로
  생성하지 않는다. 모두 주입받는다.
- TripMate(또는 디버그 환경)가 lifecycle 관리.
- 라이브러리 settings는 자체 환경변수 `KRTOUR_MAP_*`만 읽는다. provider API 키는
  provider 라이브러리가 직접 읽는다.

### 1.2 메서드 카탈로그

```python
class AsyncKrtourMapClient:
    # ─── 조회 ───────────────────────────────────────
    async def features_in_bounds(self, *, bbox: BBox, kinds: list[FeatureKind] = ...,
                                  cluster_unit: ClusterUnit | None = None,
                                  limit: int = 1000) -> list[FeatureSummary]: ...

    async def features_nearby(self, *, lon: float, lat: float, radius_m: float,
                               kinds: list[FeatureKind] = ..., limit: int = 100
                               ) -> list[FeatureNearby]: ...

    async def get_feature(self, feature_id: str) -> FeatureFull | None: ...

    async def search_by_name(self, *, q: str, kinds: list[FeatureKind] = ...,
                              limit: int = 50, similarity_threshold: float = 0.3
                              ) -> list[FeatureSearchHit]: ...

    async def build_weather_card(self, feature_id: str, asof: datetime | None = None
                                  ) -> WeatherCard: ...

    async def list_sources(self, feature_id: str) -> list[SourceLinkInfo]: ...

    # ─── 적재 (collect → load) ───────────────────────
    async def load_feature_bundles(self, bundles: Iterable[FeatureBundle],
                                    *, prune_existing: bool = False
                                    ) -> FeatureLoadResult: ...

    async def upload_feature_files(self, sources: list[FeatureFileSource]
                                    ) -> list[FeatureFile]: ...

    # ─── 운영 ───────────────────────────────────────
    async def soft_delete_feature(self, feature_id: str) -> None: ...

    async def merge_features(self, *, master_id: str, loser_id: str,
                              decision_reason: str | None = None) -> None: ...

    async def get_sync_state(self, *, provider: str, dataset_key: str,
                              sync_scope: str = "global") -> ProviderSyncState | None: ...

    async def upsert_sync_state(self, state: ProviderSyncState) -> ProviderSyncState: ...

    # ─── 작업 큐 (ADR-011) ────────────────────────────
    async def enqueue_import_job(self, kind: str, payload: dict[str, Any]
                                  ) -> ImportJob: ...

    async def claim_next_import_job(self) -> ImportJob | None: ...  # SKIP LOCKED

    async def update_import_job(self, job_id: UUID, *, state: ImportJobState,
                                 progress: int | None = None,
                                 current_stage: str | None = None,
                                 error_message: str | None = None) -> None: ...

    # ─── provider 변환 (속성) ─────────────────────────
    @property
    def providers(self) -> ProvidersFacade:
        """provider별 변환 함수 모음 (얇은 facade, wrapper 아님).

        Examples:
            client.providers.visitkorea.festival_to_bundles(items)
            client.providers.mois.license_record_to_bundle(record, mapping)
            client.providers.kma.short_forecast_to_weather_values(records, feature_id, coord)
        """
        ...
```

### 1.3 DTO 표

| DTO | 정의 | 위치 |
|-----|------|------|
| `FeatureSummary` | 지도/목록용 경량 표현 (id, kind, name, category, lat, lon, marker_*) | dto.feature |
| `FeatureNearby` | `FeatureSummary` + `dist_m` | dto.feature |
| `FeatureFull` | `Feature` + Detail + opening_hours + files | dto.feature |
| `FeatureSearchHit` | `FeatureSummary` + similarity score | dto.feature |
| `WeatherCard` | `nowcast/ultra_short/short/mid/sources` 셰입 | dto.weather |
| `SourceLinkInfo` | source_link + source_record 요약 | dto.source |
| `FeatureBundle` | provider 변환 결과 (Feature + Detail + SourceRecord + SourceLink + FeatureFileSource list + (옵션) WeatherValue/PriceValue/PricePoint) | dto.bundle |
| `FeatureLoadResult` | 적재 결과 카운트 dataclass | dto.bundle |
| `BBox` | `(min_lon, min_lat, max_lon, max_lat)` | dto.geo |
| `ClusterUnit` | `'sido' \| 'sigungu' \| 'eupmyeondong' \| None` | dto.geo |

상세 필드는 `docs/feature-model.md`.

### 1.4 ID/normalization 함수

```python
from krtour.map import (
    make_feature_id, make_source_record_key, make_payload_hash,
    normalize_provider_name, CANONICAL_PROVIDER_NAMES,
    normalize_kr_place_name, score_feature_pair,
    kst_now,
)
```

이들은 `core/`에 정의되어 import-linter가 허용한다. TripMate에서도 동일 함수
import 가능.

### 1.5 settings

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class KrtourMapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KRTOUR_MAP_", env_file=".env")

    # DB
    pg_dsn: SecretStr
    pg_dsn_sync: SecretStr | None = None
    pg_pool_size: int = 10
    pg_max_overflow: int = 10
    pg_pool_pre_ping: bool = True

    # 디버그 API (옵션)
    debug_api_host: str = "127.0.0.1"  # 외부 노출 금지 default
    debug_api_port: int = 8087

    # 객체 저장소 (boto3 S3 호환)
    object_store_endpoint_url: str = "http://127.0.0.1:9000"
    object_store_bucket: str = "krtour-map"
    object_store_region: str = "us-east-1"
    object_store_access_key_id: SecretStr | None = None
    object_store_secret_access_key: SecretStr | None = None
    object_store_public_base_url: str | None = None

    # 주소 보강
    kraddr_geo_pg_dsn: SecretStr | None = None

    # 로그
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Sentry (선택; TripMate가 주입)
    sentry_dsn: SecretStr | None = None
```

settings는 라이브러리 내부 정적 정책만 다룬다. provider API 키는 provider
라이브러리가 직접 자기 env에서 읽는다 (예: `KMA_API_KEY`는 python-kma-api).

## 2. 디버그 REST API (별도 패키지)

`docs/debug-ui-package.md` 참조. 본 문서에서는 다루지 않는다.

요약:
- 별도 Python 패키지 `krtour-map-admin` (`packages/krtour-map-admin/`).
- 메인 라이브러리를 import해서 `AsyncKrtourMapClient` 함수 호출.
- 인증 없음, 내부망 전용 (ADR-005 + ADR-020).
- 엔드포인트, 응답 셰입, OpenAPI 생성은 `docs/debug-ui-package.md`.

## 3. 사용 시나리오

### 3.1 TripMate Dagster asset (적재)

```python
from krtour.map import AsyncKrtourMapClient

@asset(group_name="features", retry_policy=...)
async def feature_event_visitkorea_festivals(ctx, visitkorea, krtour_map_client):
    items = list(visitkorea.search_festival(eventStartDate="20260501"))
    bundles = krtour_map_client.providers.visitkorea.festival_to_bundles(items)
    result = await krtour_map_client.load_feature_bundles(bundles)
    ctx.log.info("loaded", extra=result.as_metadata())
    return result
```

### 3.2 TripMate FastAPI 라우터 (조회)

```python
from krtour.map import AsyncKrtourMapClient

@router.get("/features/in-bounds")
async def list_features_in_bounds(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
    kinds: list[str] = Query(default=["place", "event"]),
    zoom: int = 12,
    krtour_map_client: AsyncKrtourMapClient = Depends(...)
):
    cluster_unit = _cluster_unit_from_zoom(zoom)
    features = await krtour_map_client.features_in_bounds(
        bbox=BBox(min_lon, min_lat, max_lon, max_lat),
        kinds=[FeatureKind(k) for k in kinds],
        cluster_unit=cluster_unit,
    )
    return {"data": features, "meta": {"count": len(features)}}
```

### 3.3 디버그 UI (별도 패키지, 인증 없음, localhost)

`docs/debug-ui-package.md` 참조. 호출 예시는 거기 박혀 있다.

## 4. 의존성/주입 계약

| 주입 대상 | 타입 | 책임자 |
|---------|------|--------|
| `engine` | `sqlalchemy.ext.asyncio.AsyncEngine` | TripMate / 디버그 환경 |
| `file_store` | `FileStore` Protocol (boto3 S3 호환 client 래핑) | TripMate |
| `kraddr_geo_client` | `kraddr.geo.AsyncAddressClient` (선택) | TripMate |
| `providers` | `dict[str, AsyncProviderClient]` (선택) | TripMate |
| `settings` | `KrtourMapSettings` | 라이브러리 자체 / 호출자 override |

라이브러리는 위 의존성이 없으면 NotImplementedError 또는 graceful disable.
예: `file_store=None`이면 file upload 비활성, `upload_feature_files`는
NotImplementedError.

## 5. 에러 모델

```python
# core/exceptions.py
class KrtourMapError(Exception): ...
class ValidationError(KrtourMapError): ...           # DTO Pydantic validation
class FeatureNotFoundError(KrtourMapError): ...
class SourceRecordNotFoundError(KrtourMapError): ...
class DuplicateFeatureError(KrtourMapError): ...
class ProviderError(KrtourMapError): ...             # provider 호출 실패
class FileStoreError(KrtourMapError): ...
class ImportJobConflictError(KrtourMapError): ...    # advisory lock 미획득
```

디버그 API는 이를 위 §2.3의 응답 셰입으로 변환한다.

## 6. 로깅

- structlog JSON to stdout (Promtail 자동 수집).
- 필수 키: `provider`, `dataset_key`, `source_record_id` (해당 시), `request_id`
  (FastAPI request에서), `feature_id` (해당 시).
- 라이브러리 내부 자체 로거 핸들러 박지 않는다.
- PII 마스킹은 호출자(TripMate Sentry `before_send` hook) 책임.

## 7. 성능 보장

`docs/performance.md`에 정의된 SLA:

| 호출 | 목표 응답 (p95) | 측정 환경 |
|------|----------------|----------|
| `features_in_bounds(limit=1000)` | < 100ms | 100k features seeded |
| `features_nearby(radius_m=1000, limit=100)` | < 50ms | 동일 |
| `get_feature` | < 20ms | warm cache |
| `build_weather_card` | < 100ms | feature당 weather 1000건 누적 |
| `search_by_name` | < 200ms | name pg_trgm 100k row |
| `load_feature_bundles(50개)` | < 500ms | warm cache |
| bulk COPY (10k price_values) | < 5s | psycopg.copy_* |

부하 테스트는 nightly (`tests/integration` `-m slow`).

## 8. 호환성 정책

- Public API (위 §1.2의 `AsyncKrtourMapClient` 메서드) 변경은 minor version
  bump.
- DTO 필드 추가는 patch.
- DTO 필드 삭제는 major 또는 deprecation cycle (1 minor).
- DB schema 변경은 ADR + Alembic migration + CHANGELOG.

## 9. provider facade

`client.providers.<name>`은 provider별 변환 함수의 namespace. wrapper class
아님 (ADR-006). 예:

```python
class VisitKoreaProviderFacade:
    @staticmethod
    def festival_to_bundles(items: Iterable[VisitKoreaFestivalItem]) -> Iterable[FeatureBundle]: ...
    @staticmethod
    def attraction_to_bundle(item: VisitKoreaAttractionItem) -> FeatureBundle: ...
```

facade는 단지 모듈 함수 namespace화. 상태/lifecycle 없음. provider client는
주입받은 `providers["visitkorea"]`를 그대로 사용한다.

## 10. CLI (옵션)

```bash
krtour-map healthz                       # DB ping + 객체저장소 ping
krtour-map alembic upgrade head          # Alembic 위임
krtour-map import enqueue --kind ...     # import_job 등록
krtour-map import claim                  # 워커 모드
```

CLI는 `typer`. 인증 없음 (로컬 전용). 운영 schedule은 krtour-map 독립 Dagster에서.

## 11. 비책임 (다시 확인)

- 사용자/여행계획/POI 도메인 — TripMate
- JWT/OAuth/세션/권한 — 네트워크 계층 또는 호출자
- 이메일 발송 — TripMate (Resend)
- WebSocket 실시간 동기 — TripMate
- TripMate 사용자 UI 페이지 — TripMate
- Dagster orchestration (job 정의, scheduler, daemon) — krtour-map 독립 Dagster 패키지

본 메인 라이브러리는 함수만 제공한다. OpenAPI/admin UI/Dagster 실행 코드는 별도
패키지 책임이다.
