# architecture.md

`python-krtour-map`의 내부 아키텍처는 **계층(layered) + async 함수 라이브러리**
모델이다. ADR-045 이후 운영 배포 모델은 이 내부 라이브러리를 감싼
**Docker 독립 프로그램 + OpenAPI** 모델이다. TripMate는 krtour-map DB에 직접
접근하거나 Python 패키지를 import하지 않고, OpenAPI client로 통신한다.

## 1. 큰 그림

본 저장소는 **monorepo**다. 핵심 패키지와 운영 프로그램 패키지가 들어 있다:

- `python-krtour-map` (메인) — `src/krtour/map/`. 함수 라이브러리. FastAPI/Uvicorn
  의존 없음. krtour-map API/Dagster 내부에서 사용한다.
- `krtour-map-admin` (ADR-020/035/045) — `packages/krtour-map-admin/`.
  FastAPI OpenAPI backend + Next.js admin UI. Docker 독립 프로그램의 API/admin
  표면이다. 인증 없음, 내부망/네트워크 계층 보호 전제.

```
┌──────────────────────────────────────────────────────────────────────┐
│ TripMate / krtour-ai-agent                                            │
│   - TripMate: 사용자/여행계획/POI 도메인                               │
│   - krtour-ai-agent: YouTube 장소 후보 REST export provider            │
│   - 두 시스템 모두 krtour-map DB 직접 접근 금지                         │
│   - TripMate는 OpenAPI, krtour-ai-agent는 provider export HTTP          │
└──────────────────────────────────────────────────────────────────────┘
                              │ HTTP / OpenAPI
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│ krtour-map 독립 프로그램 (Docker)                                      │
│                                                                      │
│  api        FastAPI + OpenAPI (`packages/krtour-map-admin`)         │
│  frontend   Next.js admin UI                                          │
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
│ python-krtour-map (메인 패키지, FastAPI 의존 없음)                       │
│                                                                      │
│  category → dto → core → infra → providers → client → cli              │
│  AsyncKrtourMapClient / raw SQL repo / provider 변환 함수               │
└──────────────────────────────────────────────────────────────────────┘
```

위 provider 입력에는 공공 `python-*-api` client 외에 형제 앱 `krtour-ai-agent`의
YouTube 장소 후보 REST export(`krtour-ai-agent-youtube`)도 포함된다. 다만
`krtour-ai-agent`도 krtour-map DB에 직접 쓰지 않고, krtour-map Dagster가 HTTP로 pull한
JSON을 순수 변환 함수로 `FeatureBundle`화한다(ADR-053).

## 2. 의존 방향 (한 방향 강제)

```
메인 패키지 (krtour.map):
  category → dto → core → infra → providers → client → cli

별도 패키지 (krtour.map_admin):
  FastAPI routers → deps/client service → krtour.map.client → ... (메인 패키지 import)
```

- 메인 패키지 내 화살표를 거스르는 import는 `import-linter`로 CI에서 차단
  (ADR-002 / 7). `krtour.map.api`는 존재하지 않는다 (ADR-020).
- `core/`는 Protocol(`FeatureRepo`, `DedupRepo`, `ProviderSyncRepo`,
  `WeatherValuesRepo`, `FileStore`, ...)에만 의존한다. `infra/`/`providers/`는
  이 Protocol의 구체 구현이다.
- `core/`는 **순수**해야 한다 — DB, FastAPI, 파일시스템, 외부 네트워크 의존 없음.
  단위 테스트는 Fake repo로 100% 가능해야 한다.
- `providers/`는 `python-*-api`의 typed model을 받아 `dto/`의 모델로 정규화하는
  **순수 함수**의 집합이다. 새 wrapper class를 만들지 않는다 (ADR-002).
  `krtour-ai-agent-youtube`는 예외적으로 형제 앱 REST export JSON을 입력으로 받지만,
  동일하게 순수 변환 함수만 둔다.
- `client.py`는 `providers/`와 `infra/` repository를 합쳐 외부에 노출하는
  단일 진입점 `AsyncKrtourMapClient`다.
- `krtour.map_admin`는 별도 패키지로, 기본적으로 `krtour.map.client`를 통해
  메인 패키지를 호출한다. 라우터가 메인 패키지의 `infra/`/`providers/`를 직접
  우회하지 않는다.

## 3. TripMate와의 연계 (OpenAPI)

ADR-045 이후 TripMate와 krtour-map 사이의 운영 계약은 OpenAPI다.

- TripMate는 generated OpenAPI client로 feature read API(`GET /features/*` 또는
  목표 v1 계약의 `GET /v1/features/*`)와 batch 조회를 호출한다. Feature update
  request는 사용자/서비스 표면이 아니라 `/admin/feature-update-requests*` 운영
  표면에서만 실행한다.
- TripMate는 krtour-map PostgreSQL에 직접 연결하지 않는다.
- TripMate는 `python-krtour-map`을 직접 import하지 않는다.
- TripMate DB에는 `feature_id`를 외부 참조 값으로 저장할 수 있으나 DB FK는 걸지
  않는다.
- OpenAPI는 처음에는 admin UI 기준으로 작성하고, TripMate 연동 시 공개/사용자
  응답을 보완·확장한다.
- `krtour-ai-agent`는 TripMate와 직접 연동하지 않고, `python-krtour-map` DB에도 쓰지
  않는다. `/api/v1/features/{snapshot|changes}`로 YouTube 장소 후보를 export하고,
  krtour-map Dagster가 이를 pull해 최종 `feature_id`를 생성한다(ADR-053).

자세한 계약은 `docs/openapi-admin-contract.md`.

## 4. 디버그 REST API (별도 패키지, ADR-020)

REST/OpenAPI는 `python-krtour-map`이 아니라 **별도 Python 패키지**
`krtour-map-admin`에 둔다. ADR-045 이후 이 패키지는 debug REST를 넘어
독립 프로그램의 admin/API 표면이다. 메인 라이브러리는 FastAPI/Uvicorn 의존이 없다.

```
┌──────────────────────────────────────────────────────────────────┐
│ krtour-map API/admin (별도 패키지)                                  │
│ packages/krtour-map-admin/src/krtour/map_admin/            │
│                                                                  │
│  uvicorn krtour.map_admin.app:app --host 127.0.0.1 --port 12301│
│                                                                  │
│   ├── /debug/health, /debug/version          (구현됨, PR#35)    │
│   ├── /debug/etl/...   (provider preview)     (구현됨, PR#44~47) │
│   ├── /features        (bbox 목록)            (구현됨, PR#73)    │
│   ├── /features/{feature_id}  (단건 상세)     (구현됨, PR#73)    │
│   ├── /features/nearby, /{id}/weather, /sources  (Sprint 3~4)   │
│   ├── /providers/{name}/sync-state               (Sprint 4)     │
│   ├── /debug/explain, /debug/fixtures            (Sprint 4)     │
│   ├── /admin/dedup-review, /admin/integrity      (Sprint 4~5)   │
│   └── /admin/feature-update-requests             (ADR-045)      │
└──────────────────────────────────────────────────────────────────┘
        │  authentication: 없음 (내부망 / localhost 전제)
        │  내부 호출
        ▼
   from krtour.map import AsyncKrtourMapClient
        ▼
   AsyncKrtourMapClient (메인 패키지 client.py)
```

- **별도 Python 패키지** (`krtour-map-admin`). 메인 라이브러리는 FastAPI
  의존이 없다 (ADR-020).
- **인증 키 없음**. 내부망 / localhost / 사내망 전제 (ADR-005).
- 외부 노출이 필요해지면 네트워크 계층(SSO 게이트웨이, IP allowlist,
  Cloudflare Tunnel)에서 보호한다. 패키지 코드/응답에 인증 로직이 들어가지
  않는다.
- TripMate는 이 패키지에 Python 의존하지 않는다. HTTP/OpenAPI로만 호출한다.
- Admin UI, TripMate 연동, provider update queue는 이 패키지의 OpenAPI를 기준으로
  확장한다.
- 자세한 사양은 `docs/debug-ui-package.md`와 `docs/openapi-admin-contract.md`.

## 5. 데이터 흐름 (적재 → 조회)

### 5.1 적재 (provider → DB)

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

### 5.2 조회 (TripMate → 사용자)

```
[TripMate 사용자] → TripMate API/Web
                  → krtour-map OpenAPI (`/features`, `/features/{id}`, ...)
                  → AsyncKrtourMapClient.<query>(...)  # krtour-map API 내부
                  → infra.repos (raw SQL EXPLAIN-검증된 쿼리)
                  → API 응답(data/meta/error) → TripMate가 자기 응답으로 재가공
```

## 6. 4 schema

- `feature` — `features`, `feature_*_details`, `feature_files`,
  `feature_opening_periods`, `feature_special_days`,
  `feature_weather_values`, `price_points`, `price_values`,
  `feature_merge_history`, `feature_overrides`.
- `provider_sync` — `source_records`, `source_links`, `provider_sync_state`.
- `ops` — `import_jobs`, `dedup_review_queue`, `feature_merge_history`,
  `data_integrity_violations`, `feature_update_requests`, `poi_cache_targets`,
  `poi_cache_target_feature_links`, `provider_refresh_policies`, `api_call_log`
  (구독 옵션).
- `x_extension` — `postgis`, `postgis_topology`, `pg_trgm`, `pgcrypto`
  (ADR-008, search_path에 추가).

ADR-045 이후 krtour-map DB는 TripMate DB와 물리적으로 분리된다. schema 분리는
krtour-map 내부 도메인(`feature`), provider 추적(`provider_sync`), 운영(`ops`)을
분리하기 위한 경계다. 테이블별 ddl은 `data-model.md`.

## 7. 모듈 책임 1줄 요약

| 모듈 | 역할 |
|------|------|
| `dto/feature.py` | `FeatureBase`, `FeatureKind`, `FeatureStatus`, `FeatureUrls` |
| `dto/details.py` | `PlaceDetail`, `EventDetail`, `NoticeDetail`, `RouteDetail`, `AreaDetail` |
| `dto/weather.py` | `WeatherValue`, `ForecastStyle`, `TimelineBucket`, `WeatherDomain` |
| `dto/price.py` | `PricePoint`, `PriceValue` |
| `dto/source.py` | `SourceRecord`, `SourceLink`, `SourceRole`, `RawDataRef` |
| `dto/files.py` | `FeatureFile`, `FeatureFileSource` |
| `dto/opening_hours.py` | `OpeningTime`, `OpeningPeriod`, `SpecialOpeningDay`, `FeatureOpeningHours` |
| `dto/sync.py` | `ProviderSyncState` |
| `dto/jobs.py` | `ImportJob`, `ImportJobState` |
| `core/ids.py` | `make_feature_id`, `make_source_record_key`, `make_payload_hash` |
| `core/providers.py` | `CANONICAL_PROVIDER_NAMES`, `normalize_provider_name` |
| `core/scoring.py` | Record Linkage scoring + `normalize_kr_place_name` |
| `core/weather.py` | `build_weather_card`, `latest_weather_values` |
| `core/protocols.py` | Repository Protocol 정의 |
| `core/exceptions.py` | 도메인 예외 |
| `core/settings.py` | Pydantic settings (`KRTOUR_MAP_*`, `SecretStr`) |
| `infra/models.py` | SQLAlchemy ORM 매핑 (read-only mapping) |
| `infra/feature_repo.py` | raw SQL repository (`_SQL` 상수 + `text()`) — FeatureBundle upsert + get_feature_row |
| `infra/source_repo.py`, `infra/sync_repo.py`, `infra/jobs_repo.py`, ... | 각 도메인 repository |
| `infra/file_store.py` | S3 호환 객체 저장소 (RustFS) |
| `providers/<name>.py` | provider raw → DTO 변환 + dataset_key 상수 |
| `client.py` | `AsyncKrtourMapClient` |
| `cli/main.py` | `krtour-map` CLI |

**별도 패키지** `packages/krtour-map-admin/src/krtour/map_admin/` (ADR-020):

| 모듈 | 역할 |
|------|------|
| `app.py` | FastAPI app factory + uvicorn entrypoint |
| `routers/*.py` | 디버그 엔드포인트 라우터 |
| `deps.py` | `AsyncKrtourMapClient` 주입 |
| `settings.py` | `KRTOUR_MAP_ADMIN_*` 환경변수 |
| `views/` (옵션) | 정적 HTML 또는 Next.js bridge |

## 8. 핵심 결정 요약 (전체는 `decisions.md`)

| ADR | 결정 |
|-----|------|
| ADR-001 | v1은 `v1` 브랜치 보존, main은 orphan v2로 재시작 |
| ADR-002 | 의존 계층 + import-linter 강제 / async-only API |
| ADR-003 | TripMate ↔ 라이브러리 함수 호출 운영 모델은 ADR-045로 superseded |
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
| ADR-020 | 디버그 UI는 별도 패키지 `krtour-map-admin` (ADR-005 위치 부분 supersede) |
| ADR-045 | Docker 독립 프로그램 + 독립 DB/Dagster + TripMate OpenAPI 연동 |

## 9. v1 대비 변경 요약

| 항목 | v1 | v2 |
|------|----|-----|
| 의존 계층 | 명시되지 않음 | dto/core/infra/providers/client/api 5층 + import-linter |
| TripMate 연계 | 일부 함수 + 일부 라우터 | OpenAPI HTTP 연동 (ADR-045) |
| 디버그 UI | stdlib HTTP server (별도 package) | FastAPI 별도 package `krtour-map-admin` (ADR-020, 인증 없음) |
| ORM | 일부 SQLAlchemy ORM 사용 | ORM은 매핑만, 쿼리는 raw SQL `text()` |
| 시간 | 일부 naive datetime 혼재 | KST aware 일원화 |
| 공간 쿼리 | 좌표 자유 변환 | `coord_5179`(meter) 기준, CTE 1회 변환 강제 |
| bulk insert | SQLAlchemy `values()` | `psycopg.copy_*` 우선 |
| 작업 큐 | 없음 / 메모리 | `import_jobs` 영속화 |
| 객체 저장소 | RustFS hard-coded | S3 호환만 가정, swap 가능 |
| 테스트 | replay fixture 중심 | unit/integration/e2e/fixture 4단계 |
| 디버그 API 인증 | 없음 (v1과 동일) | 없음 (명시적 결정 ADR-005) |
| v1 동기 인터페이스 | 일부 동기 path | 동기 신규 추가 금지 (async-only) |
