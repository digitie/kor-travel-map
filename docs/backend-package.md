# backend-package.md — 메인 라이브러리 사양

본 문서는 `python-krtour-map` (메인 패키지)의 외부 표면(public API) reference다.
사용자 시나리오와 함수 시그니처 중심이다.

> **T-226 / ADR-054 예정 변경**: 메인 distribution은 `kor-travel-map`, Python import
> root는 `kortravel`, 권장 예시는 `import kortravel as kt`로 clean cut할 예정이다.
> 본 문서의 `krtour.map` 예시는 T-226c/d/e 적용 전 현재 코드 기준이다.

> **ADR-045 주의**: 메인 패키지의 Python API는 krtour-map 독립 프로그램 내부
> API/Dagster/테스트에서 사용하는 public Python 표면이다. TripMate 운영 연동은
> 이 Python API를 직접 import하지 않고 OpenAPI로 한다. Admin/OpenAPI 계약은
> `docs/openapi-admin-contract.md`를 기준으로 한다.

디버그 REST API/UI는 **별도 Python 패키지** `krtour-map-admin` (ADR-020)에
있고, 사양은 `docs/debug-ui-package.md`를 따른다. 메인 라이브러리는 FastAPI
의존이 없다.

## 1. 라이브러리 진입점

> **구현 현황 (2026-06-03)**: `AsyncKrtourMapClient`는 구현되어 있으며,
> krtour-map API/Dagster 내부 구현과 테스트에서 사용하는 public Python 표면이다.
> TripMate 운영 코드는 이 client를 직접 import하지 않고 OpenAPI를 호출한다.

### 1.1 `AsyncKrtourMapClient`

```python
from krtour.map import AsyncKrtourMapClient, KrtourMapSettings
from sqlalchemy.ext.asyncio import create_async_engine

settings = KrtourMapSettings()  # KRTOUR_MAP_* 환경변수 자동 로드
engine = create_async_engine(settings.pg_dsn.get_secret_value())

async with AsyncKrtourMapClient(engine=engine, settings=settings) as client:
    ...
```

**책임 분리**:
- 라이브러리는 engine을 스스로 생성하지 않는다. 호출자가 주입하고 lifecycle을
  관리한다.
- krtour-map API/Dagster가 필요 resource(provider client, kraddr-geo, RustFS)를
  구성하고, client에는 DB transaction 경계만 맡긴다.
- 라이브러리 settings는 자체 환경변수 `KRTOUR_MAP_*`만 읽는다. provider API 키는
  provider 라이브러리가 직접 읽는다.

### 1.2 메서드 카탈로그

```python
class AsyncKrtourMapClient:
    # 조회
    async def get_feature(self, feature_id: str) -> dict[str, Any] | None: ...
    async def features_in_bounds(
        self,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        kinds: list[str] | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]: ...
    async def pending_dedup_reviews(self, *, limit: int = 100) -> list[dict[str, Any]]: ...
    async def status_counts(self) -> StatusCounts: ...

    # 적재/운영
    async def load_feature_bundles(self, bundles: Iterable[FeatureBundle]) -> FeatureLoadResult: ...
    async def sync_dedup_candidates(
        self, left: Iterable[DedupInput], right: Iterable[DedupInput], *, include_auto_merge: bool = True
    ) -> DedupSyncResult: ...
    async def sync_sibling_candidates(
        self, features: Iterable[DedupInput], *, include_auto_merge: bool = True
    ) -> DedupSyncResult: ...
    async def merge_dedup_review(
        self, review_id: str, *, merged_by: str | None = None, reason: str | None = None
    ) -> MergeOutcome: ...

    # MOIS lifecycle
    async def load_mois_license_features_bulk(...): ...
    async def sync_mois_license_features_bulk(...): ...
    async def run_mois_license_bulk_job(...): ...
    async def run_mois_license_incremental_job(...): ...
    async def run_mois_license_closed_job(...): ...
    async def find_place_phone_candidates(...): ...
    async def enrich_place_phone(...): ...

    # Feature update request (ADR-045 T-206c/T-206d)
    async def enqueue_feature_update_request(...) -> FeatureUpdateRequest | FeatureUpdateRequestPreview: ...
    async def get_update_request(request_id: str) -> FeatureUpdateRequest | None: ...
    async def list_update_requests(
        *,
        state: str | None = None,
        scope_type: str | None = None,
        provider: str | None = None,
        dataset_key: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> FeatureUpdateRequestPage: ...
    async def cancel_update_request(request_id: str, *, error_message: str | None = None) -> FeatureUpdateRequest | None: ...
    async def execute_next_feature_update_request(...) -> FeatureUpdateExecutionResult | None: ...
    async def execute_feature_update_request(request_id: str, ...) -> FeatureUpdateExecutionResult | None: ...

    # POI/cache target 주변 feature 조회 (ADR-045 T-207f)
    async def features_nearby_poi_cache_target(
        *,
        target_id: str,
        radius_km: float | None = None,
        kinds: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        statuses: Sequence[str] | None = ("active",),
        providers: Sequence[str] | None = None,
        sort: str = "distance",
        limit: int = 100,
        cursor: str | None = None,
    ) -> NearbyFeaturePage: ...
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

이들은 `core/`에 정의되어 import-linter가 허용한다. ADR-045 이후 TripMate 운영
코드는 이 함수를 직접 import하지 않고 OpenAPI를 호출한다. 직접 import는
krtour-map API/Dagster 내부 구현과 테스트에서만 사용한다.

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

    # admin/API 프로그램 기본 바인드 (패키지 쪽 KRTOUR_MAP_ADMIN_*가 우선)
    admin_host: str = "127.0.0.1"  # 외부 노출 금지 default
    admin_port: int = 12301

    # 객체 저장소 (boto3 S3 호환)
    object_store_endpoint_url: str = "http://127.0.0.1:12101"
    object_store_bucket: str = "krtour-map"
    object_store_region: str = "us-east-1"
    object_store_access_key_id: SecretStr | None = None
    object_store_secret_access_key: SecretStr | None = None
    object_store_public_base_url: str | None = "http://127.0.0.1:12101/krtour-map"

    # 주소 보강 (kraddr-geo REST v2)
    kraddr_geo_base_url: str | None = "http://127.0.0.1:12201"

    # 로그
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Sentry (선택; krtour-map 운영 환경이 주입)
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

### 3.1 krtour-map Dagster asset (적재)

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

### 3.2 krtour-map FastAPI 라우터 (조회)

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
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        kinds=kinds,
    )
    return {"data": features, "meta": {"count": len(features), "cluster_unit": cluster_unit}}
```

### 3.3 디버그 UI (별도 패키지, 인증 없음, localhost)

`docs/debug-ui-package.md` 참조. 호출 예시는 거기 박혀 있다.

## 4. 의존성/주입 계약

| 주입 대상 | 타입 | 책임자 |
|---------|------|--------|
| `engine` | `sqlalchemy.ext.asyncio.AsyncEngine` | krtour-map API/Dagster |
| `file_store` | `FileStore` Protocol (boto3 S3 호환 client 래핑) | krtour-map API/Dagster |
| `kraddr_geo_client` | `KraddrGeoRestClient` 또는 `ReverseGeocoder` (선택) | krtour-map API/Dagster |
| `providers` | `dict[str, AsyncProviderClient]` (선택) | krtour-map Dagster |
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
