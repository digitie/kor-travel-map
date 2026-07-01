# architecture.md

`kor-travel-map`의 내부 아키텍처는 **계층(layered) + async 함수 라이브러리**
모델이다. ADR-045 이후 운영 배포 모델은 이 내부 라이브러리를 감싼
**Docker 독립 프로그램 + OpenAPI** 모델이다. PinVi는 kor-travel-map DB에 직접
접근하거나 Python 패키지를 import하지 않고, OpenAPI client로 통신한다.

> **ADR-054/055**: public 배포명과 Python import root는 `kor-travel-map` /
> `kortravelmap`로 clean cut했다. REST/OpenAPI backend는 `kor-travel-map-api`
> (`kortravelmap.api`), admin UI는 `kor-travel-map-admin/frontend`로 분리한다.

## 1. 큰 그림

본 저장소는 **monorepo**다. 핵심 패키지와 운영 프로그램 패키지가 들어 있다:

- `kor-travel-map` (메인) — `src/kortravelmap/`. 함수 라이브러리. FastAPI/Uvicorn
  의존 없음. kor-travel-map API/Dagster 내부에서 사용한다.
- `kor-travel-map-api` (ADR-055) — `packages/kor-travel-map-api/`.
  FastAPI OpenAPI backend. Docker 독립 프로그램의 public/admin/ops/debug API 표면이다.
  인증 없음, 내부망/네트워크 계층 보호 전제.
- `kor-travel-map-admin` — `packages/kor-travel-map-admin/frontend/`.
  Next.js admin UI.

```
┌──────────────────────────────────────────────────────────────────────┐
│ PinVi / kor-travel-concierge                                        │
│   - PinVi: 사용자/여행계획/POI 도메인                               │
│   - kor-travel-concierge: YouTube 장소 후보 REST export provider        │
│   - 두 시스템 모두 kor-travel-map DB 직접 접근 금지                         │
│   - PinVi는 OpenAPI, concierge는 provider export HTTP                │
└──────────────────────────────────────────────────────────────────────┘
                              │ HTTP / OpenAPI
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ kor-travel-map 독립 프로그램 (Docker)                                      │
│                                                                      │
│  api        FastAPI + OpenAPI (`packages/kor-travel-map-api`)           │
│  frontend   Next.js admin UI (`packages/kor-travel-map-admin/frontend`) │
│  dagster    provider sync / feature update queue / consistency         │
│  worker     import_jobs / offline upload / dedup processing            │
└──────────────────────────────────────────────────────────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌────────────────┐    ┌───────────────────┐    ┌──────────────────┐
│ 독립 PostgreSQL │    │ S3 호환 객체 저장소  │    │ python-*-api     │
│ + PostGIS 3.5  │    │ (RustFS / MinIO)   │    │ provider clients │
│ + pg_trgm      │    │                    │    │                  │
│ + pgcrypto     │    │                    │    │ KMA, VisitKorea, │
│                │    │                    │    │ MOIS, OpiNet,    │
│ schema:        │    │                    │    │ KREX, KHOA,      │
│ - feature      │    │                    │    │ 국가유산, 산림청, │
│ - provider_sync│    │                    │    │ AirKorea, KASI,  │
│ - ops          │    │                    │    │ data.go.kr, ...  │
│ - x_extension  │    │                    │    │                  │
└────────────────┘    └───────────────────┘    └──────────────────┘

       내부 구현으로 import ↑
┌──────────────────────────────────────────────────────────────────────┐
│ kor-travel-map (메인 패키지, FastAPI 의존 없음)                       │
│                                                                      │
│  category → dto → core → infra → geocoding → providers → client → cli  │
│  AsyncKorTravelMapClient / raw SQL repo / provider 변환 함수               │
└──────────────────────────────────────────────────────────────────────┘
```

위 provider 입력에는 공공 `python-*-api` client 외에 형제 앱 `kor-travel-concierge`의
YouTube 장소 후보 REST export(현 코드/provider 이름 `kor-travel-concierge-youtube`)도 포함된다. 다만
`kor-travel-concierge`도 kor-travel-map DB에 직접 쓰지 않고, kor-travel-map Dagster가 HTTP로 pull한
JSON을 순수 변환 함수로 `FeatureBundle`화한다(ADR-053).

## 2. 의존 방향 (한 방향 강제)

```
메인 패키지 (kortravelmap):
  category → dto → core → infra → geocoding → providers → client → cli

별도 패키지 (kortravelmap.api):
  FastAPI app/routers → 메인 패키지(dto/core/infra/providers/client)
```

- 메인 패키지 내 화살표를 거스르는 import는 `import-linter`로 CI에서 차단
  (ADR-002 / 7). `kortravelmap.api`는 별도 API distribution이며 메인 계층 계약
  밖에 있다(ADR-055).
- `core/`는 순수 도메인 로직(`scoring`/`dedup`/`ids`/`weather`)이며 DB·FastAPI·
  네트워크 의존이 없다. repository 구현은 `infra/`(`feature_repo`/`source_repo`/
  `sync_repo`/`jobs_repo`/`file_store`)에 있고 `client.py`가 조립한다. (초기 설계의
  core-side Repository Protocol 주입은 현재 미구현 — 구체 infra repo를 직접 쓴다.)
- `core/`는 **순수**해야 한다 — DB, FastAPI, 파일시스템, 외부 네트워크 의존 없음.
  단위 테스트는 Fake repo로 100% 가능해야 한다.
- `providers/`는 `python-*-api`의 typed model을 받아 `dto/`의 모델로 정규화하는
  **순수 함수**의 집합이다. 새 wrapper class를 만들지 않는다 (ADR-002).
  `kor-travel-concierge-youtube`는 예외적으로 형제 앱 REST export JSON을 입력으로 받지만,
  동일하게 순수 변환 함수만 둔다.
- `geocoding.py`는 `infra/` 위, `providers/` 아래에 놓인 **단일 모듈**이다
  (패키지가 아님 — `src/kortravelmap/geocoding.py`). kor-travel-geo REST v2를 호출하는
  reverse/forward geocoding helper로, import-linter layer 계약에서 **providers 아래**
  (providers가 geocoding을 import) layer로 강제된다. (참고: `pyproject.toml`의 layer
  배열이 정본이며, 동일 파일의 주석도 같은 순서를 따른다.)
- `client.py`는 `providers/`와 `infra/` repository를 합쳐 외부에 노출하는
  단일 진입점 `AsyncKorTravelMapClient`다.
- `kortravelmap.api`는 별도 패키지로, HTTP projection에 필요한 메인 패키지
  DTO/core/infra/client를 import할 수 있다. FastAPI/Uvicorn 의존은 이 패키지에만 둔다.

## 3. PinVi와의 연계 (OpenAPI)

ADR-045 이후 PinVi와 kor-travel-map 사이의 운영 계약은 OpenAPI다.

- PinVi는 generated OpenAPI client로 feature read API(`GET /features/*` 또는
  목표 v1 계약의 `GET /v1/features/*`)와 batch 조회를 호출한다. Feature update
  request는 사용자/서비스 표면이 아니라 `/admin/features/update-requests*` 운영
  표면에서만 실행한다.
- PinVi는 kor-travel-map PostgreSQL에 직접 연결하지 않는다.
- PinVi는 `kor-travel-map`을 직접 import하지 않는다.
- PinVi DB에는 `feature_id`를 외부 참조 값으로 저장할 수 있으나 DB FK는 걸지
  않는다.
- OpenAPI는 처음에는 admin UI 기준으로 작성하고, PinVi 연동 시 공개/사용자
  응답을 보완·확장한다.
- `kor-travel-concierge`는 PinVi와 직접 연동하지 않고, `kor-travel-map` DB에도 쓰지
  않는다. `/api/v1/features/{snapshot|changes}`로 YouTube 장소 후보를 export하고,
  kor-travel-map Dagster가 이를 pull해 최종 `feature_id`를 생성한다(ADR-053).

자세한 계약은 `docs/architecture/openapi-admin-contract.md`.

## 4. REST API (별도 패키지, ADR-055)

REST/OpenAPI는 `kor-travel-map`이 아니라 **별도 Python 패키지**
`kor-travel-map-api`에 둔다. ADR-045 이후 이 패키지는 debug REST를 넘어
독립 프로그램의 public/admin/ops/API 표면이다. 메인 라이브러리는 FastAPI/Uvicorn 의존이 없다.

```
┌──────────────────────────────────────────────────────────────────┐
│ kor-travel-map API (별도 Python 패키지)                                │
│ packages/kor-travel-map-api/src/kortravelmap/api/                      │
│                                                                  │
│  uvicorn kortravelmap.api.app:app --host 127.0.0.1 --port 12701│
│                                                                  │
│   ├── /debug/health, /debug/version          (구현됨, PR#35)    │
│   ├── /debug/etl/...   (provider preview)     (구현됨, PR#44~47) │
│   ├── /features        (bbox 목록)            (구현됨, PR#73)    │
│   ├── /features/{feature_id}  (단건 상세)     (구현됨, PR#73)    │
│   ├── /features/nearby, /{id}/weather, /sources  (Sprint 3~4)   │
│   ├── /providers/{name}/sync-state               (Sprint 4)     │
│   ├── /ops/logs                                  (T-221e)       │
│   ├── /admin/dedup-review, /admin/integrity      (Sprint 4~5)   │
│   └── /admin/features/update-requests             (ADR-045)      │
└──────────────────────────────────────────────────────────────────┘
        │  authentication: 없음 (내부망 / localhost 전제)
        │  내부 호출
        ▼
   from kortravelmap import AsyncKorTravelMapClient
        ▼
   AsyncKorTravelMapClient (메인 패키지 client.py)
```

- **별도 Python 패키지** (`kor-travel-map-api`). 메인 라이브러리는 FastAPI
  의존이 없다 (ADR-020).
- **인증 키 없음**. 내부망 / localhost / 사내망 전제 (ADR-005).
- 외부 노출이 필요해지면 네트워크 계층(SSO 게이트웨이, IP allowlist,
  Cloudflare Tunnel)에서 보호한다. 패키지 코드/응답에 인증 로직이 들어가지
  않는다.
- PinVi는 이 패키지에 Python 의존하지 않는다. HTTP/OpenAPI로만 호출한다.
- Admin UI, PinVi 연동, provider update queue는 이 패키지의 OpenAPI를 기준으로
  확장한다.
- 자세한 사양은 `docs/architecture/debug-ui-package.md`와 `docs/architecture/openapi-admin-contract.md`.

## 5. Admin UI frontend (별도 패키지, ADR-055)

Admin UI는 `packages/kor-travel-map-admin/frontend/`의 별도 Next.js 패키지다.
현재 표준 stack은 다음과 같다.

- Next.js 16 App Router + React 19 + TypeScript.
- 서버 상태와 mutation은 TanStack Query가 source of truth다. 원격 응답을
  Zustand에 복제하지 않는다.
- 클라이언트 UI 상태는 Zustand, form 상태와 검증은 React Hook Form + Zod resolver로
  처리한다.
- 운영 목록/검토 화면의 데이터 테이블은 공용 `DataTable`을 쓴다.
  `DataTable`은 `@tanstack/react-table` v8 + `@tanstack/react-virtual` v3
  기반이며, shadcn `Table` primitive는 의미론적/시각적 table 렌더링에만 쓴다.
- 지도는 MapLibre GL + VWorld style builder다. `maplibre-vworld-js`/
  `maplibre-vworld` npm dependency는 사용하지 않는다. T-MAP-VWORLD-04 이후
  `digitie/maplibre-vworld-react`의 `vworld-map-core`/`vworld-map-web` 경계를
  기준으로 필요한 `VWorldMapView`와 style builder만 admin 내부에 포팅했다.
- 공통 마커와 category→maki 매핑은 `@kor-travel-map/map-marker-react`를 쓴다
  (모노레포 내부 private package).

세부 UI 계약은 `docs/architecture/debug-ui-package.md` §14,
OpenAPI 연동 규칙은 `docs/architecture/openapi-admin-contract.md` §9,
화면별 워크플로는 `docs/debug-ui-admin-workflows.md`가 정본이다.

## 6. 데이터 흐름 (적재 → 조회)

### 6.1 적재 (provider → DB)

```
[provider API] → python-*-api client (raw + typed model)
              → providers/<name>.py (순수 변환)
              → dto.FeatureBundle (Feature + Detail + SourceRecord + SourceLink
                + FeatureFileSource + (optional) WeatherValue / PriceValue)
              → core.load_pipeline (validation, dedup blocking, FeatureFileSource
                업로드)
              → infra.repos (raw SQL upsert; bulk는 COPY)
              → Postgres + 객체 저장소
              → infra.provider_sync_repo (cursor 업데이트)
              → infra.import_jobs_repo (status='done' + progress)
```

### 6.2 조회 (PinVi → 사용자)

```
[PinVi 사용자] → PinVi API/Web
                  → kor-travel-map OpenAPI (`/features`, `/features/{id}`, ...)
                  → AsyncKorTravelMapClient.<query>(...)  # kor-travel-map API 내부
                  → infra.repos (raw SQL EXPLAIN-검증된 쿼리)
                  → API 응답(data/meta/error) → PinVi가 자기 응답으로 재가공
```

## 7. 4 schema

- `feature` — `features`, `feature_*_details`, `feature_files`,
  `feature_opening_periods`, `feature_special_days`,
  `feature_weather_values`, `feature_price_values`,
  `feature_merge_history`, `feature_overrides`.
- `provider_sync` — `source_records`, `source_links`, `provider_sync_state`.
- `ops` — `import_jobs`, `dedup_review_queue`, `feature_merge_history`,
  `data_integrity_violations`, `feature_update_requests`, `poi_cache_targets`,
  `poi_cache_target_feature_links`, `provider_refresh_policies`, `api_call_log`
  (구독 옵션).
- `x_extension` — `postgis`, `postgis_topology`, `pg_trgm`, `pgcrypto`
  (ADR-008, search_path에 추가).

ADR-045 이후 kor-travel-map DB는 PinVi DB와 물리적으로 분리된다. schema 분리는
kor-travel-map 내부 도메인(`feature`), provider 추적(`provider_sync`), 운영(`ops`)을
분리하기 위한 경계다. 테이블별 ddl은 `data-model.md`.

## 8. 모듈 책임 1줄 요약

| 모듈 | 역할 |
|------|------|
| `dto/feature.py` | `Feature`, `FeatureKind`, `FeatureStatus`, `FeatureUrls` |
| `dto/place.py`, `dto/event.py`, `dto/notice.py`, `dto/route.py`, `dto/area.py` | `PlaceDetail`, `EventDetail`, `NoticeDetail`, `RouteDetail`, `AreaDetail` (kind별 파일) |
| `dto/weather.py` | `WeatherValue`, `ForecastStyle`, `TimelineBucket`, `WeatherDomain` |
| `dto/price.py` | `PriceValue` (`kind=price` anchor feature에 연결되는 시계열 값) |
| `dto/source.py` | `SourceRecord`, `SourceLink`, `SourceRole`, `RawDataRef` |
| `dto/file.py` | `FeatureFile`, `FeatureFileSource` |
| `dto/opening_hours.py` | `OpeningTime`, `OpeningPeriod`, `SpecialOpeningDay`, `FeatureOpeningHours` |
| (dto 모듈 아님) | `ProviderSyncState`/`ImportJob`은 `dto/`에 별도 모듈로 있지 않다 — provider sync state·import job 타입은 infra(`infra/jobs_repo.py` 등) 쪽에 있다 |
| `core/ids.py` | `make_feature_id`, `make_source_record_key`, `make_payload_hash` |
| `core/providers.py` | `CANONICAL_PROVIDER_NAMES`, `normalize_provider_name` |
| `core/scoring.py` | Record Linkage scoring + `normalize_kr_place_name` |
| `core/weather.py` | `build_weather_card`, `latest_weather_values` |
| `core/types.py` | KST tzinfo·`kst_now` 등 시간 헬퍼 re-export shim (Repository Protocol 정의는 현재 없음) |
| `core/exceptions.py` | 도메인 예외 |
| `settings.py` (top-level) | Pydantic settings (`KOR_TRAVEL_MAP_*`, `SecretStr`) |
| `infra/models.py` | SQLAlchemy ORM 매핑 (read-only mapping) |
| `infra/feature_repo.py` | raw SQL repository (`_SQL` 상수 + `text()`) — FeatureBundle upsert + get_feature_row |
| `infra/source_repo.py`, `infra/sync_repo.py`, `infra/jobs_repo.py`, ... | 각 도메인 repository |
| `infra/file_store.py` | S3 호환 객체 저장소 (RustFS) |
| `providers/<name>.py` | provider raw → DTO 변환 + dataset_key 상수 |
| `geocoding.py` (단일 모듈) | kor-travel-geo REST v2 reverse/forward geocoding helper (infra 위, providers 아래 — providers가 import) |
| `client.py` | `AsyncKorTravelMapClient` |
| `cli/main.py` | `kor-travel-map` CLI |

**별도 패키지** `packages/kor-travel-map-api/src/kortravelmap/api/` (ADR-055):

| 모듈 | 역할 |
|------|------|
| `app.py` | FastAPI app factory + uvicorn entrypoint |
| `routers/*.py` | public/admin/ops/debug 엔드포인트 라우터 |
| `settings.py` | `KOR_TRAVEL_MAP_API_*` 환경변수 |
| `prometheus.py` | Prometheus HTTP/DB 성능 메트릭 |

## 9. 핵심 결정 요약 (전체는 `decisions.md`)

| ADR | 결정 |
|-----|------|
| ADR-001 | v1은 `v1` 브랜치 보존, main은 orphan v2로 재시작 |
| ADR-002 | 의존 계층 + import-linter 강제 / async-only API |
| ADR-003 | PinVi ↔ 라이브러리 함수 호출 운영 모델은 ADR-045로 superseded |
| ADR-004 | ORM은 매핑만, 쿼리는 raw SQL `text()` |
| ADR-005 | 디버그 REST API는 인증 없음, 내부망 전용 |
| ADR-006 | provider adapter/wrapper 신규 생성 금지 |
| ADR-007 | Postgres + PostGIS + SQLAlchemy 2 async + GeoAlchemy2 + GeoPandas 채택 |
| ADR-008 | PostGIS extension은 `x_extension` schema 격리 |
| ADR-009 | `feature_id` 결정적 생성 (`make_feature_id`) |
| ADR-010 | weather: `forecast_style` + `timeline_bucket` 분리 |
| ADR-011 | 작업 큐는 `import_jobs` 영속화, advisory lock + SKIP LOCKED |
| ADR-012 | 공간 쿼리는 입력 좌표 1회 변환, 반경은 `coord_5179`(meter) |
| ADR-013 | bulk insert는 `psycopg.copy_*` 우선, 안전 마진 30k |
| ADR-014 | 테스트 4단계 (unit/integration/e2e/fixture) + Coverage 목표 |
| ADR-015 | 객체 저장소는 S3 호환만 가정, RustFS 1차, MinIO/Ceph/R2 swap |
| ADR-016 | Record Linkage: blocking(`ST_DWithin 100m + bjd_code + kind`) → scoring(0.45/0.35/0.20) → 임계값 0.85/0.65 |
| ADR-017 | 보관 정책: place 무기한, event +20y, notice +1y, weather +30d, price 카테고리별 |
| ADR-018 | `Feature.detail`은 자유 dict 금지 (`DETAIL_MODELS` 분기 강제) |
| ADR-019 | KST aware datetime만 허용 (`kst_now()`) |
| ADR-020 | 메인 라이브러리에서 FastAPI/Uvicorn 의존 분리 (ADR-005 위치 부분 supersede) |
| ADR-055 | REST API Python backend(`kor-travel-map-api`)와 admin frontend(`kor-travel-map-admin`) 분리 |
| ADR-045 | Docker 독립 프로그램 + 독립 DB/Dagster + PinVi OpenAPI 연동 |

## 10. v1 대비 변경 요약

| 항목 | v1 | v2 |
|------|----|-----|
| 의존 계층 | 명시되지 않음 | dto/core/infra/providers/client/api 5층 + import-linter |
| PinVi 연계 | 일부 함수 + 일부 라우터 | OpenAPI HTTP 연동 (ADR-045) |
| 디버그/UI | stdlib HTTP server (별도 package) | FastAPI `kor-travel-map-api` + Next.js `kor-travel-map-admin` (ADR-055, 인증 없음) |
| ORM | 일부 SQLAlchemy ORM 사용 | ORM은 매핑만, 쿼리는 raw SQL `text()` |
| 시간 | 일부 naive datetime 혼재 | KST aware 일원화 |
| 공간 쿼리 | 좌표 자유 변환 | `coord_5179`(meter) 기준, CTE 1회 변환 강제 |
| bulk insert | SQLAlchemy `values()` | `psycopg.copy_*` 우선 |
| 작업 큐 | 없음 / 메모리 | `import_jobs` 영속화 |
| 객체 저장소 | RustFS hard-coded | S3 호환만 가정, swap 가능 |
| 테스트 | replay fixture 중심 | unit/integration/e2e/fixture 4단계 |
| 디버그 API 인증 | 없음 (v1과 동일) | 없음 (명시적 결정 ADR-005) |
| v1 동기 인터페이스 | 일부 동기 path | 동기 신규 추가 금지 (async-only) |

## 11. 이관된 결정 (구 ADR)

핵심 구조 결정은 아니나 패키지/의존 정리·provider 순서에 영향을 주는 결정들을
ADR에서 본 문서로 이관한다.

### 11.1 패키지 정리 — kraddr-base 흡수

- **category 모듈을 `kortravelmap.category`로 자체 보유** (구 ADR-023): v1까지
  외부 의존이던 `python-kraddr-base.categories`(141 enum + maki icon 매핑,
  `PlaceCategory`/`get_category`/`mapbox_maki_icon_for_category` 등)를 본 저장소로
  이전했다. category 데이터는 지도 도메인에 직접 종속이고 `kor-travel-map`이
  유일 소비자라 응집도가 높으며, 의존 그래프에서 외부 dep 1개를 끊는다.
  의존 계층상 `dto`보다 낮은 `category` 계층으로 두고(§2 그래프의 최하단),
  `Feature.category` 검증·정규화가 이를 import한다. 라이선스(GPL-3.0-or-later)는
  양쪽 호환이라 파일 상단 derivation 주석으로 출처를 남긴다.
- **`python-kraddr-base` 전체 흡수 후 폐기** (구 ADR-041, PR#33): category 외
  `address`(→`dto/address.py` 머지)·`domain`(→category/enum 흡수)·utility 함수
  (→`core/normalize.py`·`core/strings.py`)도 본 라이브러리 외 사용처가 없어
  흡수하고 원 저장소는 archive한다. 외부 의존 1개를 줄여 install/version pinning을
  단순화한다. **단, `PlaceCoordinate`는 가져오지 않는다** — 본 lib의
  `dto.Coordinate`와 책임이 중복되고 EPSG/Decimal 처리 정책이 충돌하므로, 좌표
  DTO는 `kortravelmap.dto.Coordinate`가 단일 source of truth다(CLAUDE.md §5의
  PlaceCoordinate import 금지 룰과 정합).

### 11.2 provider 명명·구현 순서

- **MOIS provider canonical name = `python-mois-api`** (구 ADR-024): 행정안전부
  지방행정 인허가 OpenAPI 라이브러리의 실제 PyPI 배포명은 `python-mois-api`,
  import 이름은 `mois`다(v1 내부 alias `krmois`는 실재하지 않음). 따라서
  `CANONICAL_PROVIDER_NAMES`에 `python-mois-api`를 등록하고 import는
  `from mois import MoisClient`, 본 lib provider 경로는
  `kortravelmap.providers.mois`, dataset_key prefix는 `mois_*`를 쓴다. v1 호환을
  위해 `krmois`/`mois`/`pykrmois`/`python-krmois-api`는 `LEGACY_PROVIDER_ALIASES`로
  매핑한다. (provider 명명 정본은 `core/providers.py` + `provider-contract.md`.)
- **provider 9단계 구현 순서 — MOIS를 마지막 군에** (구 ADR-034): 축제 → 날씨 →
  유가 → 휴게소 → 국립공원/트래킹 → 국가유산 → **MOIS 인허가** → 휴양림/수목원 →
  박물관/미술관 순으로 적재한다. 핵심 근거는 dedup 룰 검증 순서다 — Record
  Linkage scoring(ADR-016)을 작은 dataset(축제·유가·휴게소 등)에서 먼저 안정화한
  뒤, MOIS의 대량 bulk(195 슬러그 × 다수 시군구)를 진입시켜야
  `dedup_review_queue` 폭증을 피하고 정합성 게이트(ADR-033)의 baseline을 확보한다.
  MOIS-sibling provider(휴양림/수목원·박물관/미술관 — MOIS 슬러그와 중복 가능)는
  MOIS가 primary로 먼저 들어간 뒤 enrichment로 join하도록 MOIS 이후에 둔다.
  Sprint 매핑·보조 dataset 배치는 `docs/sprints/`가 정본이다.
