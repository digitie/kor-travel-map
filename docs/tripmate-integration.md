# tripmate-integration.md — TripMate와 krtour-map OpenAPI 연동

> **ADR-045 supersede 안내 (2026-06-01)**:
> 본 문서의 예전 본문에는 TripMate가 `python-krtour-map`을 직접 import하고 같은
> process에서 `AsyncKrtourMapClient`를 호출하는 패턴이 남아 있다. 그 운영 모델은
> ADR-045로 supersede됐다. 현재 기준은 다음이다.
>
> - krtour-map은 Docker에서 실행되는 독립 프로그램이다.
> - krtour-map은 독립 PostgreSQL/PostGIS DB와 독립 Dagster를 가진다.
> - TripMate는 krtour-map DB에 직접 접근하지 않는다.
> - TripMate는 `python-krtour-map`을 운영 코드에서 직접 import하지 않는다.
> - TripMate는 krtour-map OpenAPI client로 feature 조회와 update request를 호출한다.
> - OpenAPI는 우선 admin UI 기준으로 작성하고, TripMate 연동 시 필요한 공개 API를
>   보완·확장한다.
>
> 아래 "직접 import" 예시는 ADR-045 이전 legacy 참고 자료다. 새 구현은
> `docs/openapi-admin-contract.md`를 우선한다.

## 0. 현재 표준: OpenAPI 연동

TripMate 연동의 현재 표준 흐름:

```
TripMate API/Web
  → generated krtour-map OpenAPI client
  → krtour-map API (`/features`, `/features/{id}`, `/admin/feature-update-requests`)
  → krtour-map 독립 DB/Dagster
```

초기 TripMate 후보 API:

| API | 목적 |
|-----|------|
| `GET /features` | bbox 기반 지도 feature 조회 |
| `GET /features/{feature_id}` | feature 상세 |
| `POST /tripmate/features/batch` | 여러 feature_id batch 상세 조회 (후속 확장) |
| `POST /admin/feature-update-requests` | 특정 feature/좌표 반경/시군구/provider 업데이트 큐잉 |
| `GET /admin/feature-update-requests/{request_id}` | 업데이트 요청 진행 상태 |
| `GET /admin/import-jobs/{job_id}` | 실제 Dagster/import job progress |

예: 특정 좌표 중심 반경 5km 안 feature 업데이트 요청.

```http
POST /admin/feature-update-requests
Content-Type: application/json

{
  "scope": {
    "type": "center_radius",
    "center": {"lon": 126.978, "lat": 37.5665},
    "radius_km": 5.0
  },
  "providers": [],
  "dataset_keys": [],
  "update_policy": {
    "mode": "refresh_existing",
    "force_provider_call": true,
    "dedup_after_load": true,
    "consistency_check_after_load": true
  },
  "run_mode": "queued",
  "dry_run": false,
  "operator": "tripmate-admin",
  "reason": "사용자 신고 지역 데이터 갱신"
}
```

예: TripMate POI를 cache target으로 등록. 좌표만으로 식별하지 않고
`target_key`를 함께 보낸다.

```http
PUT /admin/poi-cache-targets/tripmate/poi_123
Content-Type: application/json

{
  "coord": {"lon": 126.978, "lat": 37.5665},
  "coord_precision_digits": 6,
  "radius_km": 5.0,
  "scope_mode": "center_radius",
  "update_enabled": true,
  "refresh_policy": "provider_default",
  "on_conflict": "reject"
}
```

예: 여러 POI key를 기준으로 주변 캐시 갱신을 큐잉. 반경이 겹치는 feature/provider
scope는 krtour-map이 dedup해 한 번만 업데이트한다.

```http
POST /admin/feature-update-requests
Content-Type: application/json

{
  "scope": {
    "type": "cache_target_keys",
    "external_system": "tripmate",
    "target_keys": ["poi_123", "poi_456"],
    "radius_km": 5.0,
    "scope_mode": "center_radius"
  },
  "run_mode": "queued",
  "dry_run": false,
  "operator": "tripmate",
  "reason": "저장 POI 주변 캐시 갱신"
}
```

예: POI key 기준 주변 feature summary 조회. 목록 응답에는 detail JSON/raw payload가
포함되지 않고 `last_updated_at`은 항상 포함된다.

```http
GET /features/nearby/by-target?external_system=tripmate&target_key=poi_123&radius_km=5
```

예: 특정 좌표 중심 반경 10km와 교차하는 시군구의 feature 업데이트 dry-run.

```http
POST /admin/feature-update-requests
Content-Type: application/json

{
  "scope": {
    "type": "sigungu_by_radius",
    "center": {"lon": 126.978, "lat": 37.5665},
    "radius_km": 10.0,
    "match": "intersects"
  },
  "run_mode": "queued",
  "dry_run": true,
  "operator": "tripmate-admin",
  "reason": "대상 시군구 산정"
}
```

## ⚠️ DEPRECATED (ADR-045 supersede, 2026-06-01) — 직접 import 모델 (사용 금지)

> **이 섹션 아래 전체(§1~끝)는 ADR-003 기준 legacy 설계다. TripMate ↔ krtour-map
> 새 연동/구현에는 절대 사용하지 말 것.** 현행 모델은 본 문서 상단 "OpenAPI 연동"
> 섹션 + `docs/architecture.md` + ADR-045. TripMate는 라이브러리를 import하지 않고
> krtour-map OpenAPI를 HTTP로 호출하며 krtour-map DB에 직접 연결하지 않는다.
> 아래는 (a) 내부 Python API(`api`/`dagster`가 내부에서 쓰는 `AsyncKrtourMapClient`)
> 의 의도, (b) 이전 결정 맥락 이해 — 두 용도로만 보존한다.

## 1. 개관

```
┌──────────────────────────────────────────────────────────────────┐
│ TripMate (apps/)                                                 │
│   apps/api/        — FastAPI 라우터 + Admin                       │
│   apps/web/        — Next.js 사용자 UI                            │
│   apps/etl/        — Dagster definitions/jobs/schedules           │
│                                                                  │
│   pip install python-krtour-map                                  │
│   from krtour.map import AsyncKrtourMapClient, Feature, ...      │
└──────────────────────────────────────────────────────────────────┘
                              │ 함수 직접 호출 (HTTP 없음)
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ python-krtour-map (이 저장소, 같은 venv)                          │
└──────────────────────────────────────────────────────────────────┘
```

TripMate ↔ 라이브러리는 같은 Python 프로세스에서 함수 호출만. REST/JSON
직렬화/네트워크 hop 없음 (ADR-003).

## 2. 설치

TripMate의 `pyproject.toml`:

```toml
dependencies = [
  "python-krtour-map @ git+https://github.com/digitie/python-krtour-map.git@<sha>",
  # 또는 PyPI 배포 후: "python-krtour-map>=0.2,<0.3"
  # provider 라이브러리는 TripMate가 직접 의존:
  "python-kraddr-base @ git+...",
  "python-kraddr-geo @ git+...",
  "python-visitkorea-api @ git+...",
  "python-kma-api @ git+...",
  # ...
]
```

본 라이브러리의 디버그 UI는 별도 패키지(`krtour-map-admin`)이며 TripMate는
의존하지 않는다 (ADR-020). 디버그 UI는 운영자가 별도로 띄울 수 있다.

## 3. Resource 주입 (TripMate가 책임)

본 라이브러리는 어떤 resource(engine, S3 client, provider client, geocoder)도
자체 생성하지 않는다. 모두 TripMate에서 주입:

```python
# apps/api/app/dependencies/krtour_map.py
from functools import lru_cache
from sqlalchemy.ext.asyncio import create_async_engine

from krtour.map import AsyncKrtourMapClient
from kraddr.geo import AsyncAddressClient

from apps.api.app.settings import TripMateSettings
from apps.api.app.dependencies.object_store import get_file_store
from apps.api.app.dependencies.providers import get_provider_clients

@lru_cache
def get_feature_engine():
    settings = TripMateSettings()
    return create_async_engine(
        settings.krtour_map_pg_dsn.get_secret_value(),
        pool_size=settings.pg_pool_size,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": "public,x_extension"}},
    )

async def get_krtour_map_client() -> AsyncKrtourMapClient:
    engine = get_feature_engine()
    file_store = get_file_store()
    kraddr_geo = AsyncAddressClient(...)        # TripMate가 관리
    providers = await get_provider_clients()    # dict[str, AsyncProviderClient]
    return AsyncKrtourMapClient(
        engine=engine,
        file_store=file_store,
        kraddr_geo_client=kraddr_geo,
        providers=providers,
        settings=KrtourMapSettings(),           # 본 라이브러리 settings
    )
```

`KRTOUR_MAP_*` 환경변수는 TripMate의 `.env`에 함께 들어간다.

## 4. 사용 시나리오 1: 조회 (read path)

### 4.1 지도 viewport (FastAPI 라우터)

```python
# apps/api/app/routers/features.py
from fastapi import APIRouter, Depends, Query
from krtour.map import AsyncKrtourMapClient, FeatureKind, BBox, ClusterUnit

router = APIRouter(prefix="/features")

@router.get("/in-bounds")
async def features_in_bounds(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
    kinds: list[str] = Query(default=["place", "event"]),
    zoom: int = Query(default=12, ge=0, le=22),
    client: AsyncKrtourMapClient = Depends(get_krtour_map_client),
):
    cluster_unit = _cluster_unit_from_zoom(zoom)
    features = await client.features_in_bounds(
        bbox=BBox(min_lon, min_lat, max_lon, max_lat),
        kinds=[FeatureKind(k) for k in kinds],
        cluster_unit=cluster_unit,
    )
    return {"data": features, "meta": {"count": len(features)}}

def _cluster_unit_from_zoom(zoom: int) -> ClusterUnit | None:
    if zoom < 7:  return "sido"
    if zoom < 11: return "sigungu"
    if zoom < 14: return "eupmyeondong"
    return None
```

TripMate가 SPEC V8 응답 셰입 `{"data": ..., "meta": ...}`로 래핑한다. 라이브러리
DTO는 자체 래핑 키가 없음 (ADR-003 + DO NOT #7).

### 4.2 feature 상세 + weather card

```python
@router.get("/{feature_id}")
async def get_feature(feature_id: str, client = Depends(get_krtour_map_client)):
    feature = await client.get_feature(feature_id)
    if feature is None:
        raise HTTPException(404, detail={"code": "FEATURE_NOT_FOUND"})
    return {"data": feature}

@router.get("/{feature_id}/weather")
async def feature_weather(feature_id: str, client = Depends(get_krtour_map_client)):
    card = await client.build_weather_card(feature_id, asof=datetime.utcnow())
    return {"data": card}
```

`WeatherCard`는 `{"nowcast": ..., "ultra_short": [...], "short": [...], "mid":
[...], "sources": [{provider, valid_at, payload}]}` 셰입 (`docs/weather-feature-
normalization.md` 참고).

### 4.3 반경 검색

```python
@router.get("/nearby")
async def features_nearby(
    lon: float, lat: float, radius_m: int = Query(default=1000, le=10000),
    kinds: list[str] = Query(default=["place"]),
    limit: int = Query(default=100, le=500),
    client = Depends(get_krtour_map_client),
):
    results = await client.features_nearby(
        lon=lon, lat=lat, radius_m=radius_m,
        kinds=[FeatureKind(k) for k in kinds],
        limit=limit,
    )
    return {"data": results, "meta": {"count": len(results)}}
```

`coord_5179`(meter) 컬럼 사용 (ADR-012). 라이브러리가 내부적으로 EPSG:4326 →
5179 변환을 CTE에서 한 번만 수행.

## 5. 사용 시나리오 2: 적재 (Dagster asset)

### 5.1 raw → feature 흐름

```python
# apps/etl/assets/visitkorea_festivals.py
from dagster import asset, FreshnessPolicy
from krtour.map import AsyncKrtourMapClient
from krtour.map.dto import FeatureBundle  # 또는 client.providers.* 반환 타입

@asset(
    group_name="features",
    freshness_policy=FreshnessPolicy(maximum_lag_minutes=60 * 24),  # 일 1회
)
async def feature_event_visitkorea_festivals(
    ctx,
    visitkorea,                  # Dagster resource: AsyncVisitKoreaClient
    krtour_map_client,           # Dagster resource: AsyncKrtourMapClient
):
    # 1. provider 호출 (provider 라이브러리 직접)
    items = list(await visitkorea.search_festival(eventStartDate="20260501"))
    ctx.log.info("fetched_festivals", extra={"count": len(items)})

    # 2. 변환 (라이브러리 facade — 순수 함수)
    bundles = list(krtour_map_client.providers.visitkorea.festival_to_bundles(
        items, fetched_at=ctx.run.created_timestamp,
    ))

    # 3. DB 적재
    result = await krtour_map_client.load_feature_bundles(bundles)
    ctx.log.info("loaded_festivals", extra=result.as_metadata())

    # 5. sync state
    await krtour_map_client.upsert_sync_state(ProviderSyncState(
        provider="python-visitkorea-api",
        dataset_key="visitkorea_festival_events",
        last_success_at=kst_now(),
        cursor={"last_pageNo": items[-1].pageNo if items else None},
    ))
    return result
```

### 5.2 schedule

```python
# apps/etl/schedules.py
from dagster import ScheduleDefinition

visitkorea_festival_schedule = ScheduleDefinition(
    name="visitkorea_festival_daily",
    cron_schedule="0 3 * * *",      # 매일 03:00
    job=visitkorea_festival_job,
    execution_timezone="Asia/Seoul",
)
```

Dagster scheduler가 cron을 본다. 라이브러리 측은 `ProviderSyncState.next_run_after`
helper만 제공 (스케줄러 X).

### 5.3 concurrency 제어 (provider 쿼터 보호)

```python
# apps/etl/resources.py
from dagster import ConcurrencyConfig

defs = Definitions(
    assets=[...],
    resources={...},
    asset_concurrency_configs={
        "opinet_api": ConcurrencyConfig(max_concurrent=1),   # 분당 호출 한도
        "kma_api":    ConcurrencyConfig(max_concurrent=1),
        "datagokr_api": ConcurrencyConfig(max_concurrent=2),
    },
)
```

## 6. 사용 시나리오 3: Admin / 검수

### 6.1 dedup 검토

```python
# apps/api/app/routers/admin_dedup.py
@router.get("/admin/dedup-review")
async def list_dedup_pending(client = Depends(get_krtour_map_client)):
    # 라이브러리 helper가 ops.dedup_review_queue 조회
    rows = await client.list_dedup_pending(limit=50)
    return {"data": rows}

@router.post("/admin/dedup-review/{review_key}/merge")
async def merge_pair(
    review_key: UUID,
    master_id: str = Body(...),
    loser_id: str = Body(...),
    reason: str = Body(...),
    client = Depends(get_krtour_map_client),
):
    await client.merge_features(master_id=master_id, loser_id=loser_id,
                                 decision_reason=reason)
    await client.update_dedup_review(review_key, status="merged")
    return {"data": {"ok": True}}
```

### 6.2 정합성 위반 조회

```python
@router.get("/admin/integrity-violations")
async def list_violations(
    status: str = Query(default="open"),
    severity: str | None = None,
    client = Depends(get_krtour_map_client),
):
    rows = await client.list_data_integrity_violations(status=status, severity=severity)
    return {"data": rows}
```

## 7. 사용 시나리오 4: TripMate POI 도메인 연계

POI 도메인은 TripMate. POI는 `feature_id`로 본 라이브러리 feature를 참조.

```python
# TripMate trip_pois.feature_id (FK) → feature.features.feature_id
# 단, feature가 삭제될 수 있으므로 PoiSnapshot이 동시 저장 (SPEC V8 D-13)

@router.post("/trips/{trip_id}/pois")
async def add_poi(trip_id: UUID, body: AddPoiRequest, client = Depends(get_krtour_map_client)):
    feature = await client.get_feature(body.feature_id)
    if feature is None:
        raise HTTPException(404)
    
    # Snapshot 생성 — feature 삭제 대비 폴백
    snapshot = PoiSnapshot(
        name=feature.name,
        coord_lat=feature.coord.lat if feature.coord else None,
        coord_lon=feature.coord.lon if feature.coord else None,
        kind=feature.kind,
        category=feature.category,
        # ...
    )
    
    poi = await trip_pois_repo.create(
        trip_id=trip_id, feature_id=feature.feature_id,
        snapshot=snapshot, ...,
    )
    return {"data": poi}
```

feature가 soft-delete되면 (`client.soft_delete_feature(feature_id)`) POI는
`feature_link_broken_at` 표시되고 `snapshot` 폴백으로 렌더링 (SPEC V8 D-13).

## 8. PoiSnapshot cascade

```python
async def archive_feature(feature_id: str, client = Depends(get_krtour_map_client)):
    """관리자가 feature를 비활성/삭제할 때 POI snapshot을 새로 굳히는 helper."""
    await client.soft_delete_feature(feature_id)
    # TripMate 측에서:
    await trip_pois_repo.mark_feature_links_broken(feature_id, broken_at=now())
```

`feature_link_broken_at` cascade는 라이브러리가 트리거로 하지 않고 명시적 함수
호출로 (SPEC V8 ADR-018 미러 — 명시적 cascade가 디버깅에 좋다).

## 9. 권한 / 인증

본 라이브러리는 권한 모델을 정의하지 않는다. TripMate가 JWT/OAuth/role
(`user/admin/operator/cpo`)을 책임진다.

라이브러리 함수에 `actor_user_id`, `actor_role` 같은 파라미터를 전달하면
`location_access_log` (SPEC V8 M-15)를 라이브러리가 기록할 수 있다 (옵션):

```python
await client.get_feature(feature_id, audit_actor=(user.id, user.role))
```

TripMate `cpo` role만 `location_access_log` 조회 가능 — 이건 TripMate의 권한
미들웨어 책임.

## 10. structlog 키 표준

본 라이브러리가 emit하는 로그는 다음 키를 일관되게 사용 (TripMate Loki/Grafana
대시보드 호환):

```
{
  "level": "info",
  "msg": "feature_upserted",
  "provider": "python-visitkorea-api",
  "dataset_key": "visitkorea_festival_events",
  "source_record_id": "sr_abc...",
  "feature_id": "f_1111010100_e_def...",
  "request_id": "<X-Request-Id from FastAPI>"  // 있을 때만
}
```

`request_id`는 FastAPI 미들웨어가 ContextVar로 주입. TripMate가 일관 설정.

## 11. 에러 변환

```python
# apps/api/app/exception_handlers.py
from krtour.map.core.exceptions import (
    KrtourMapError, ValidationError, FeatureNotFoundError,
    ProviderError, ImportJobConflictError,
)

@app.exception_handler(FeatureNotFoundError)
async def feature_not_found(request, exc):
    return JSONResponse(404, content={
        "error": {"code": "FEATURE_NOT_FOUND", "message": str(exc)}
    })

@app.exception_handler(ValidationError)
async def validation_error(request, exc):
    return JSONResponse(422, content={
        "error": {"code": "VALIDATION_ERROR", "message": str(exc), "details": exc.details}
    })

# ... 나머지 매핑
```

라이브러리는 HTTP 응답 셰입을 모름. TripMate가 표준 응답으로 래핑.

## 12. 마이그레이션 (TripMate ↔ 라이브러리 release 동기)

라이브러리 release 흐름:
1. 본 저장소 PR merge → tag (예: `v0.3.0`)
2. TripMate `pyproject.toml`에서 commit sha 또는 version 핀 갱신
3. TripMate CI: integration test 통과 확인
4. TripMate release

스키마 변경이 있는 release는 항상 Alembic migration 첨부. TripMate는
`alembic upgrade head`를 배포 단계에 포함.

## 13. 테스트 (TripMate 측)

```python
# apps/api/tests/conftest.py
@pytest.fixture
async def krtour_map_client_for_test(pg_engine_for_test):
    # testcontainers PostGIS를 본 라이브러리 conftest와 공유 가능
    from krtour.map import AsyncKrtourMapClient
    return AsyncKrtourMapClient(
        engine=pg_engine_for_test,
        file_store=InMemoryFileStore(),  # 본 라이브러리 tests/fakes/
        kraddr_geo_client=None,
        providers={},
        settings=KrtourMapSettings(),
    )
```

TripMate 테스트는 라이브러리의 Fake repo / InMemoryFileStore를 재사용 가능.

## 14. 디버그 UI (옵션, 운영자만)

```bash
# TripMate와 같은 venv에 추가 설치
uv pip install -e ../python-krtour-map/packages/krtour-map-admin

# 내부망에서 운영자가 띄움 (인증 없음, 127.0.0.1 default)
uvicorn krtour.map_admin.app:app --host 127.0.0.1 --port 8087
```

TripMate UI에서 사용자에게 노출되지 않음. 운영자 SSH 터널/내부망 전용.

## 14.5 TripMate 사용자 UI 지도 stack (ADR-026)

**TripMate `apps/web` 사용자 가시 지도 UI는 본 라이브러리 디버그 UI와 동일한
지도 stack을 사용한다** — ADR-026 (2026-05-25). 빌드 도구는 양쪽 모두
**Next.js** (ADR-025 2차 보강 2026-05-25).

| 항목 | 값 |
|------|-----|
| Framework | Next.js 16 (App Router) — 본 라이브러리 디버그 UI + TripMate `apps/web` 동일 stack |
| 지도 엔진 | `maplibre-gl` (BSD-3) |
| VWorld 컴포넌트 | `maplibre-vworld` **v0.1.2** (`github:digitie/maplibre-vworld-js#v0.1.2`, ISC — npm 미게시, git URL+tag 핀) |
| 좌표 검증 | `zod` ^4.4.3 (maplibre-vworld v0.1.2 peer) |
| VWorld API key | `KRADDR_GEO_VWORLD_API_KEY` **공유** (`NEXT_PUBLIC_VWORLD_API_KEY`로 노출, ADR-025 보강 1차+2차) |
| 마커 / category maki | `@krtour/map-marker-react` npm 패키지 (ADR-029) — 본 라이브러리 디버그 UI + TripMate UI 공통. drift gate. |

**Kakao Maps JS SDK는 제거 대상** — SPEC V8 v8_3의 Kakao Maps 섹션은
ADR-026으로 superseded. 관련 환경변수(`NEXT_PUBLIC_KAKAO_JS_KEY` 등) 일괄
제거 (TripMate 측 후속 PR).

**작업 분담**:
- 본 라이브러리: ADR-026 + ADR-029 박음 + 공통 maki npm 패키지 (`@krtour/
  map-marker-react`) 제공 + 디버그 UI도 Next.js (ADR-025 2차 보강).
- TripMate 저장소: `apps/web` 지도 코드 Kakao → maplibre-vworld 교체 PR
  (Next.js 그대로 유지, 마커 import만 `@krtour/map-marker-react`로 교체).
- SPEC V8 저장소: v8_3 Kakao Maps 섹션에 "superseded by python-krtour-map
  ADR-026" 표기.

**provider 안정성**: `maplibre-vworld-js`는 본 사용자가 직접 운영하는 저장소.
문제 발생 시 wrapper 도입(ADR-006 위배) 대신 upstream에 직접 PR로 적극 수정
(ADR-025 보강 2026-05-25).

## 15. v1 → v2 마이그레이션 가이드

v1을 import한 TripMate 코드 → v2로 옮길 때:

| v1 | v2 |
|----|----|
| `from krtour_map import ...` | `from krtour.map import ...` |
| `from krtour_map_admin import ...` | `from krtour.map_admin import ...` |
| `from kraddr.base import PlaceCategory` | `from krtour.map.category import PlaceCategory` (ADR-023) |
| `krtour_map.api.app` | `krtour.map_admin.app` (별도 패키지로 분리, ADR-020) |
| 동기 client 사용 | `asyncio.run(...)` 로 감싸기 (ADR-002 async-only) |
| `Feature.detail: dict` 자유 입력 | `PlaceDetail/EventDetail/...` Pydantic 인스턴스만 (ADR-018) |
| naive datetime | KST aware (`kst_now()`) (ADR-019) |
| 반경 검색 `ST_Transform` 사용 | `coord_5179` 컬럼 + CTE 1회 변환 (ADR-012) |

상세 매핑은 v2 코드 작성 단계에서 마이그레이션 스크립트와 함께 별도 PR.

## 16. 비책임 (다시 확인)

본 라이브러리는 TripMate의 다음을 책임지지 **않는다**:

- 사용자 / 인증 / 세션 / 권한
- 여행계획 / POI / trip_pois 도메인
- WebSocket 실시간 동기
- Admin UI 페이지 (라이브러리는 함수만 제공)
- Dagster orchestration (asset 정의 / scheduler / daemon — TripMate `apps/etl`)
- 이메일 발송 / Resend / 알림
- 결제 / 외부 거래
- 백업 / DR

본 라이브러리는 **함수 라이브러리**다. 위 모든 도메인은 TripMate에서 본
라이브러리의 함수를 `import해서 사용`한다.

## 17. 의존 흐름 요약

```
사용자 → TripMate FastAPI → AsyncKrtourMapClient (메모리 호출)
                           → SQLAlchemy AsyncEngine → Postgres
                           → boto3 client → 객체 저장소
                           → provider client → 외부 공공 API

운영자 → krtour.map_admin (별도 uvicorn) → AsyncKrtourMapClient (메모리 호출)
                                              → ... (위와 동일)
```

내부망 외부 노출 없음 (디버그 UI는 127.0.0.1 default).

## 18. 운영 체크리스트 (TripMate 측)

- [ ] `python-krtour-map` git sha 또는 version 핀
- [ ] `KRTOUR_MAP_*` 환경변수 (`KRTOUR_MAP_PG_DSN` 등)
- [ ] PostgreSQL 16 + PostGIS 3.5 schema + extension 부트스트랩 (운영자 1회)
- [ ] Alembic upgrade head (배포 단계)
- [ ] provider API 키 (TripMate `.env`)
- [ ] 객체 저장소 bucket healthy
- [ ] `client.healthz()` 모든 항목 true
- [ ] Dagster asset 정의 + scheduler 활성
- [ ] (옵션) `krtour-map-admin` 별도 설치, 운영자 내부망만
