# resume.md — 현재 진척도와 다음 한 작업

## 2026-06-03 Codex 작업 메모 — feature update client 표면

ADR-045 T-206c로 `AsyncKrtourMapClient`에 feature update request 메서드 4종을
추가한다. `enqueue_feature_update_request`는 `infra.feature_update_repo`를 감싸되,
`dry_run=True`일 때는 DB write 없이 preview만 반환하고 실제 enqueue는
`ops.feature_update_requests`와 연결 `ops.import_jobs` 생성을 한 transaction으로
묶는다. `get_update_request`, `list_update_requests`, `cancel_update_request`도 같은
client 표면으로 노출해 T-207a admin router와 T-208e Dagster sensor가 공유할
오케스트레이션 경계를 마련한다.

동시에 `from krtour.map import AsyncKrtourMapClient` top-level import를 실제 public
export로 맞추고, client/module 문서의 TripMate 직접 import 설명을 ADR-045 OpenAPI
운영 모델 기준으로 정정한다. 통합 테스트는 dry-run preview, enqueue, get/list,
cancel lifecycle을 PostGIS migrated DB에서 확인한다.

다음 한 작업은 **T-206a-geo**다. 형제 repo `python-kraddr-geo`에서
`POST /v2/regions/within-radius`와 optional PostGIS 실데이터 테스트를 현재 endpoint
기준으로 재검증하고, 빠진 부분이 있으면 별도 PR로 보완한다. 그 다음 T-206d request
실행 본체에 들어가기 전에 **T-205c**로 `ops.provider_refresh_policies`(provider별
update 주기/rate limit), `ops.poi_cache_targets` + `_feature_links`
(`cache_target_keys` scope 선행), `ops.data_integrity_violations`(F5~F8 저장 기반)을
먼저 만든다. 이후 T-206d → T-207a → T-208e 순서로 진행한다.

## 2026-06-03 Codex 작업 메모 — feature update request 큐 repository

ADR-045 T-206b로 `infra/feature_update_repo.py`를 추가한다. 이 repo는
`ops.feature_update_requests`와 `ops.import_jobs`를 같은 transaction에서 연결해
admin API와 Dagster sensor가 공유할 request lifecycle을 제공한다.

구현 범위는 dry-run preview(쓰기 없음), enqueue(request + import job 생성),
priority 기반 claim(`FOR UPDATE SKIP LOCKED` + advisory lock), start/finish/cancel,
get/list다. 목록은 D-10 결정대로 `created_at DESC, request_id DESC` keyset cursor를
base64 opaque cursor로 제공한다. `cache_target_keys` scope는 아직
`ops.poi_cache_targets`가 없으므로 Phase 2에 남긴다.

다음 한 작업은 T-206c다. `AsyncKrtourMapClient`에
`enqueue_feature_update_request` / `get_update_request` / `list_update_requests` /
`cancel_update_request`를 transaction 경계와 함께 노출하고, T-207a admin router가
그 client 메서드를 사용하게 준비한다.

## 2026-06-03 Codex 작업 메모 — feature update scope resolver

ADR-045 T-206a로 `infra/scope_repo.py`를 추가한다. resolver는
`feature_ids`, `center_radius`, `bbox`, `sigungu_by_radius`, `provider_dataset` scope를
read-only raw SQL로 해석하고, dry-run/queue 저장에 쓸 `matched_scope` payload를
만든다. `center_radius`는 입력 좌표를 CTE에서 한 번만 EPSG:5179로 변환하고
`feature.features.coord_5179`에 `ST_DWithin`을 직접 적용한다(ADR-012).

`sigungu_by_radius`는 kraddr-geo REST v2 `/v2/regions/within-radius`를 직접 import하지
않고, 호출자가 주입한 async resolver가 반환한 5자리 `sigungu_code`를 그대로 DB 조회에
사용한다. 이로써 `infra` → `geocoding` 레이어 역방향 import를 만들지 않는다.
`cache_target_keys`는 `ops.poi_cache_targets` 테이블이 필요한 Phase 2로 남긴다.

## 2026-06-03 Codex 작업 메모 — feature update request 스키마

ADR-045 T-205a로 `ops.feature_update_requests`를 Alembic `0008`과
`FeatureUpdateRequestRow` ORM 매핑에 추가한다. 이 테이블은 OpenAPI/admin UI가 만든
feature update request를 `ops.import_jobs`/Dagster run과 연결하기 위한 기반이다.

이번 범위는 **스키마/매핑/DDL 검증**이다. `scope_type` 6종(`feature_ids`,
`center_radius`, `sigungu_by_radius`, `bbox`, `provider_dataset`,
`cache_target_keys`), `run_mode`(`queued`/`now`), 상태 전이
(`queued`/`running`/`done`/`failed`/`cancelled`) CHECK, JSONB 기본값,
`job_id ON DELETE SET NULL`, claim/list용 인덱스를 검증한다. scope resolver,
enqueue/claim repository, admin API, Dagster sensor는 T-206/T-207/T-208 후속 PR로
분리한다.

## 2026-06-02 Codex 작업 메모 — admin UI Dagster 운영 화면

admin UI에 `/admin/dagster`를 추가했다. backend `GET /ops/dagster/summary`는
Dagster GraphQL을 호출해 version, code location, asset group, schedule/sensor, 최근
run 상태를 admin UI용 DTO로 정규화한다. frontend는 같은 화면에서 자체 요약 UI와
Dagster webserver iframe embed를 제공한다. 홈 화면에도 Dagster 상태 요약과 진입
링크를 추가했다. embedded Dagster webserver의 로컬 첫 실행 커뮤니티 모달은
`/ops/dagster/summary`가 `setNuxSeen`을 best-effort 호출해 접는다.

이번 범위는 Dagster **관측/관리 화면 1차 수직 슬라이스**다. feature update request
queue, import job progress, Dagster sensor/worker 연결은 기존 문서의 후속 구현 순서에
따라 별도 PR에서 진행한다.

## 2026-06-02 Codex 작업 메모 — Docker/포트 표준화

ADR-047로 krtour-map standalone 로컬 포트를 API `9011`, admin UI `9012`, Dagster
`9013`으로 고정했다. `AdminSettings`, frontend scripts, Playwright 기본 baseURL,
`.env.example`, runbook 문서를 같은 기준으로 맞추고, `scripts/stop-fixed-ports.sh`,
`scripts/load-env.sh`, `scripts/run-admin-stack.sh`, `scripts/docker-build.sh`,
`scripts/docker-up.sh`를 추가했다.

Docker 1차는 `postgres`, `api`, `frontend`, `dagster` 서비스로 구성한다. API는
Postgres health 이후 `alembic upgrade head`를 실행하고, `.env`의 provider service key는
`KRTOUR_MAP_ADMIN_*`/`NEXT_PUBLIC_*` 환경변수로 매핑한다.

## 2026-06-02 Codex 작업 메모 — krtour-map Dagster Feature ETL 1차 구현

TripMate 구현을 참고하지 않고 krtour-map 자체 Dagster code location
`packages/krtour-map-dagster/`를 추가했다. 메인 라이브러리 `krtour.map`은 계속
Dagster를 import하지 않으며, Dagster 패키지가 provider record resource를 받아 기존
provider 변환 함수 9종을 호출하고 `FeatureBundle` 주소/좌표 검증 후
`AsyncKrtourMapClient.load_feature_bundles`로 PostGIS에 적재한다.

1차 asset: datagokr 문화축제, OpiNet 주유소, KREX 휴게소/교통공지, krheritage
유산/행사, MOIS 인허가, KNPS point/geometry. 통합 테스트는 Dagster context를 통해
9개 asset runner를 실행하고 `feature.features`/`provider_sync.source_records`
커밋과 `coord_5179`/행정코드 적재를 검증한다.

## 2026-06-02 Codex 작업 메모 — kraddr-geo 반경 endpoint 재정합

kraddr-geo `origin/main` 기준 `POST /v2/regions/within-radius`가 구현되어 있음을
다시 확인하고, krtour-map `KraddrGeoRestClient`/helper/parser를 최신 REST v2 계약에
맞췄다. 공개 relation 값은 `contains`/`overlaps`이고, `sigungu.code`는 5자리,
`emd.code`는 8자리 행정구역 코드다. 추가로 `RegionV2.sig_cd`/`eup_myeon_dong`을
파싱해 bjd 없는 reverse 응답에서도 `sigungu_code`/`sido_code`/admin 이름을 보존한다.

실데이터 확인은 로컬 kraddr-geo REST `http://127.0.0.1:9001` + T-027 최종 적재
PostGIS DB(`tl_scco_ctprvn=17`, `tl_scco_sig=255`, `tl_scco_emd=5067`)로 수행했다.
샘플 `(lon=126.978, lat=37.5665, radius_km=3.0, levels=sigungu+emd)`에서 HTTP 200,
`sigungu` 6건, `emd` 190건을 확인했고, `resolve_sigungu_by_radius`는
`("11140", "11110", "11170", "11290", "11410", "11440")`를 반환했다.

## 2026-06-02 Codex 작업 메모

Codex는 admin frontend를 문서화된 stack(Next.js 16 + React 19 + TanStack Query +
Zustand + Zod + React Hook Form + shadcn/ui + maplibre-vworld) 기준으로 전환했다.
geocoding 전용 디버그 화면/라우터는 kraddr-geo 프로젝트에서만 본다는 사용자 결정에
따라 krtour-map-admin에서 제거했다. krtour-map에는 provider 주소 보강에 필요한
`krtour.map.geocoding` client만 남긴다. 검증은 frontend lint/type/build,
React Doctor, admin OpenAPI drift check, admin pytest, Windows Playwright e2e를
통과했다.

## 현재 상태

**Sprint 4 (4a+4b) ✅ 완료 → Sprint 5 + ADR-045 독립 프로그램화 🟡 진행 중**
(2026-06-03 기준). main 최신: `PR#159`. Sprint 4a
(MOIS Step A bulk + Step B incremental cursor + `krtour-map dedup-merge` +
`feature_merge_history` alembic 0007 + dedup FP 측정/운영 통계) + Sprint 4b
(MOIS Step C/D + ADR-033 F4 + Place phone enrichment + coverage 75→80 + 에이전트
runbook)를 PR#133~#142로 완료했다. PR#143~#149에서 ADR-045 admin/OpenAPI/cache
명세, 실행 계획, 모든 D-1~D-16 의사결정, `krtour-map-admin` rename을 완료했다.
그 전 PR#96~#114에서 Sprint 4 prep,
`/features` UX, geocoding v2 전환, Windows Git + NTFS 정책을 반영했다.
2026-06-01 추가 결정: **ADR-045**로 운영 모델을 Docker 독립 프로그램 + 독립
PostgreSQL/PostGIS DB + 독립 Dagster + TripMate OpenAPI 연동으로 전환했다. Admin
OpenAPI 기준 문서(`docs/openapi-admin-contract.md`), admin UI 상세 사양
(`docs/debug-ui-admin-workflows.md`), 외부 POI key 기반 캐시 갱신 타깃
(`docs/poi-cache-update-targets.md`)을 추가했다. TripMate 직접 import/공유 DB 모델은
legacy 참고로만 본다. **ADR-046**으로 ADR-045 이행 시 구 패키지명/env/import,
TripMate 직접 import, 공유 DB, TripMate-owned Dagster 호환 shim을 만들지 않는
정책을 확정했다.
테스트 최신 기준: full pytest **~835 passed** (coverage 실측 94.12%, gate
`fail_under=80`) + debug-ui non-live 117 + Windows Playwright e2e / GitHub Actions
(lint + pytest 3.11/3.12/3.13 + openapi-drift) 전체 green.

에이전트 공용 runbook은 `docs/runbooks/`(인덱스 README + `agent-workflow.md` 표준
1-PR 흐름 + `agent-failure-patterns.md` 반복 실패 회피) — 작업 전 후자 둘을 훑는다.

개발 환경 문서는 Windows Git(`git.exe`) + NTFS worktree
(`F:\dev\python-krtour-map*`)를 Git 원본으로 명시한다. WSL ext4는
테스트/실행 전용 샌드박스이며, 필요 시 NTFS 소스를 `rsync`해서 사용한다.
`python-kraddr-geo` 최신 로컬 포트 정책도 재확인하여 geocoding REST live
기본값은 FastAPI backend `http://127.0.0.1:9001`로 맞췄다.

Sprint 1 scaffolding (PR#17~#27) 종료 후 Sprint 2 (PR#28~#59)에서
ADR-034 9단계 중 ①~④ provider + 디버그 UI + ETL live 11/11 dataset을 구현했다.
Sprint 3(PR#60~#95)에서는 DB 적재/조회, consistency report, dedup queue,
client orchestration, KNPS/krheritage provider, `/features` debug UI까지 완료했다.

ADR **001~047 모두 accepted**. 029→043, 003·035 일부→045로 supersede.
ADR-044 = 관련 라이브러리 `F:\dev\` 로컬 우선 조회 + 데이터 정합성 책임은 각
provider 라이브러리. ADR-045 = krtour-map Docker 독립 프로그램 + 독립 DB/Dagster +
TripMate OpenAPI 연동(ADR-003 함수 직접 호출 모델 supersede). ADR-046 = 호환 shim
없이 정본 방향으로 이행. 다음 후보 번호 = ADR-048.

**Sprint 2 주요 산출물**:
- Provider ① 축제: `providers/standard_data.py` (datagokr 표준데이터,
  ADR-042) — `cultural_festivals_to_bundles`
- Provider ② 날씨: `providers/kma.py` (단기/초단기실황/초단기예보/특보 4종)
  + `dto/weather.py` (`WeatherValue` + 3 enum) + `core/weather.py` (5 pure helper)
- Provider ③ 유가: `providers/opinet.py` (`prices_to_values` +
  `stations_to_bundles`) + `dto/price.py` (`PriceValue` + `PriceDomain`)
- Provider ④ 휴게소: `providers/krex.py` (4 dataset multi-kind 통합)
- 디버그 UI backend: `create_app` factory + health/version + ETL preview
  (`?source=fixture` + `?source=live` KMA 3종) + OpenAPI drift gate
- 디버그 UI frontend: Next.js 16 + TanStack Query + Zustand skeleton +
  ETL preview 페이지
- Infra: `models.py` (SQLAlchemy 2 + GeoAlchemy2) + Alembic 2 revision
- Core: `scoring.py` (ADR-016 Record Linkage) + `providers.py` (canonical 18종)
  + `address.py` (bjd/phone/한글 정규화, ADR-041 kraddr-base 흡수)

**스택** (ADR-007):
- PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2
- GeoPandas + Shapely 2 + GDAL
- Pydantic v2 / FastAPI + Uvicorn / httpx + tenacity / Alembic

TripMate 연계 (**ADR-045**, ADR-003 supersede): krtour-map은 Docker 독립 프로그램
이고 TripMate는 **OpenAPI(HTTP)** 로 feature 조회/상세/업데이트를 호출한다(직접
import·공유 DB 없음). admin/API는 `krtour-map-admin` 패키지(ADR-020, 내부망·
인증 없음 ADR-005)가 제공하며, 메인 라이브러리(`krtour.map`)는 그 api/dagster가
내부에서 쓰는 핵심 엔진이다.

## 다음 한 작업

### Sprint 2 잔여 — **전부 완료** (`sprints/SPRINT-2.md §7`)

- [x] visitkorea enrichment — PR#51 (`festival_to_enrichment_links`, 8 test).
- [x] KMA mid_forecast — PR#52 (`mid_land_forecast_to_weather_values` +
  `mid_temperature_to_weather_values`, 11 test).
- [x] ETL live 11/11 dataset — krex 4 (PR#55) / opinet 2 (PR#56) / datagokr 1
  (PR#57) / kma_weather_alerts apihub (PR#58).
- [x] Coverage bar 50→65 + Sprint 2 종료 회고 + Sprint 3 진입 (PR#59).

### 통합 검증 (사용자 지시 2026-05-28 — Sprint 2 종료 직후)

ETL 로직을 실데이터로 끝까지 검증하고 상세 리포트를 남긴다. (`tasks #114~#118`)

1. **weather_alerts data.go.kr fallback** (PR) — apihub authKey가 로컬에 없어
   `getWthrWrnList`(기존 `DATA_GO_KR_SERVICE_KEY`) fallback loader 추가 → 11/11
   전부 지금 live 검증 가능.
2. **ETL live 실데이터 + 정합성** — provider .env 키를 debug-ui `.env`(gitignore,
   커밋 금지)로 매핑 복사 후 11 dataset live 호출 → 유입/정합성 검증 + 리포트.
3. **DB 적재 통합 테스트** — FeatureBundle→`infra/models` ORM→testcontainer
   PostGIS 적재·재조회 검증 (docker는 WSL).
4. **Debug UI e2e** — WSL에 node 설치 → backend+frontend 기동, Windows Playwright로
   검증 + 스크린샷/리포트.
5. **종합 리포트** — `docs/reports/`에 테스트 케이스·결과·발견 이슈 정리.

> ⚠️ **키 이름 drift 발견**: provider repo .env의 실제 키 이름이 debug-ui
> settings 가정과 다름 — data.go.kr 게이트웨이는 공통 `DATA_GO_KR_SERVICE_KEY`
> (kma 동네예보/datagokr/krex/visitkorea), opinet=`OPINET_API_KEY`,
> krex(data.ex.co.kr)=`KEX_GO_API_KEY`. apihub authKey는 부재. → 통합 검증 시
> 매핑 + settings 문서 정정.

### Sprint 3 본작업 (통합 검증 후)

- **Provider ⑤ KNPS** 14 dataset (`providers/knps.py`) — Point/place 5건 +
  geometry(route/area) 5건 ✅ 구현. `knps_point_records_to_bundles` +
  `knps_geometry_records_to_bundles`(WKT 입력) + `core/geometry.py`(shapely) +
  `Feature.geom` 필드 + `feature_repo` geom 적재 (ADR-028/034/012). +
  **knps-api `CsvPreview` 브리지**(`knps_csv_preview_to_{point,geometry}_bundles`,
  best-guess 컬럼맵 override 가능). **본 lib KNPS 변환 완료** — SHP→WKT 디코딩은
  **knps-api 책임**(ADR-028 Amendment I / ADR-044). ⚠️ CSV 컬럼명 best-guess —
  live `CsvPreview.headers`로 확정 필요(현재 환경 data.go.kr 차단). `06da125f`.
  (통계 3건은 feature 본문 X.)
- **geocoding (kraddr-geo REST v2 연동)** (`krtour.map.geocoding`) ✅ — 좌표↔주소
  보강. **PR#90/#123**: in-process python client 후보(`reverse_v2`/`geocode_v2`)를
  쓰지 않고 **REST v2 `POST /v2/reverse`, `POST /v2/geocode`**로 전환.
  실제 `ReverseResponse`/`GeocodeResponse`/`AddressStructure`
  structural Protocol + 순수 변환 `reverse_response_to_address`/
  `geocode_response_to_coordinate` + `KraddrGeoRestClient`(httpx **주입**,
  TYPE_CHECKING-only — 메인 패키지 런타임 httpx 의존 X) + 팩토리
  `kraddr_geo_{reverse,address}_geocoder` + `cached_reverse_geocoder`(좌표 메모이즈).
  설정: `KRTOUR_MAP_KRADDR_GEO_BASE_URL` (로컬 기본 예:
  `http://127.0.0.1:9001`).
- **provider 변환기 전면 async + geocoder 자동 보강** ✅ — festival/opinet/krex/
  knps 변환 함수가 모두 `async` + `reverse_geocoder` 인자. feature_id 계산 전에
  await해 bjd_code 보강(ADR-009 — 'global' bucket 탈출). standard_data sync
  Protocol 제거 → geocoding async `ReverseGeocoder`로 통일. debug-ui etl 경로도
  async. **남은 것**: kraddr-geo client 수명·실 DB 적재 오케스트레이션은 호출자.
- **Provider ⑥ krheritage** (`providers/krheritage.py`) ✅ — 국가유산 place +
  area + event. `heritage_items_to_bundles`(place/area, ccba_kdcd로 kind 분기 +
  키워드 category) / `heritage_events_to_bundles`(EventDetail heritage_event).
  모두 async + reverse_geocoder. area는 GIS WKT(있으면) → geom + centroid.
  structural Protocol 입력(KrHeritageItem/KrHeritageEvent), krheritage import 안 함.
  **후속 ✅ 완료**: PR#85(#119) `FeatureFileSource` DTO + krheritage 미디어
  primary file_source / PR#86(#120) `geometry_area_square_meters` 측지 면적 +
  krheritage AREA 보강 / PR#87(#121) `find_dedup_candidates`(knps 사찰↔krheritage
  temple cross-score) / PR#88(#122) `ops.dedup_review_queue` 적재.
- ~~ADR-033 Phase 1 — `feature_consistency_reports` (F1~F3)~~ ✅ 완료
  (alembic 0003 + `infra/consistency.py` + 단위/통합 테스트)
- ~~`AsyncKrtourMapClient` 적재/dedup 오케스트레이션~~ ✅ 완료 (PR#89/#122 —
  `load_feature_bundles`/`sync_dedup_candidates`/읽기 메서드 + integration 3건).
- ~~Debug UI WSL 기동 + Windows Playwright e2e~~ ✅ 완료 (PR#91/#92/#93/#102/#114, #117 —
  workspace 루트 + 초기 e2e 7/7 + `/features` 9/9 + geocoding 포함 최신 14/14 +
  검출한 잠복 빌드 버그 fix + frontend CI 게이트).
- ~~`/features/*` 라우터 + frontend 지도 wiring (maplibre-vworld)~~ ✅ 완료
  (PR#95 — `/features` 지도 페이지: maplibre-gl + react-query + zustand viewport
  + bbox refetch + 단순 marker, e2e 2건 추가하여 9/9 통과).
- ~~Sprint 3 종료 회고 + Sprint 4 진입 준비~~ ✅ 완료 (본 prep PR —
  coverage bar 75 / SPRINT-3 §6 일괄 체크 / SPRINT-4 §1 진입 조건 + §3 **4a/4b
  분할 채택** / sprints/README.md + journal 회고 entry).

## 다음 한 작업 — **ADR-045 독립 프로그램화 / Sprint 5 진입**

Sprint 4(4a+4b)는 아래 체크리스트대로 **전부 완료**(PR#133~#142). ADR-045
의사결정은 PR#146~#149에서 **전부 확정**됐다. 다음 한 작업은
**ADR-045 독립 프로그램화** — 세분 실행 계획이 문서화됨:

- **실행 계획(정본, AI agent 실행용)**: `docs/adr045-standalone-plan.md` —
  Phase 1~6 + T-205~T-210 fine-grained task + 권장 순서 §8.
- **의사결정 결과**: `docs/adr045-open-decisions.md` — D-1~D-16 전부 결정 완료.
  구현은 이 결정을 그대로 따른다.
- **TripMate 연계 REST 계약**: `docs/tripmate-rest-api.md` (params/returns 1차).
- 기존 명세 정본: `docs/openapi-admin-contract.md`(admin API/큐 DDL/Docker 서비스),
  `docs/debug-ui-admin-workflows.md`, `docs/poi-cache-update-targets.md`,
  `docs/dagster-boundary.md`.

**1차 진입 task**(권장): T-205a(`feature_update_requests`
alembic 0008, 완료) → T-206a(scope resolver, 완료) → T-206b(feature update repo,
완료) → T-206c(client, 본 PR) → **T-206a-geo(형제 repo endpoint 검증/보완)** →
**T-205c(Phase 2 스키마)** → T-206d(request 실행 본체) → T-207a/e(admin
update-requests + 사용자 features 라우터) → T-208d/e(Dagster schedule/sensor). 그
다음 Sprint 5 provider(MOIS-sibling) + Phase 2 정합성.
세부는 `docs/sprints/SPRINT-5.md`.

### Sprint 4 (4a+4b) 완료 체크리스트 (PR#133~#142, 2026-06-01)

`docs/sprints/SPRINT-4.md §2.1` Step A(bulk):
- [x] `providers/mois.py` 변환 코어 — structural Protocol `MoisLicensePlaceRecord`
  + `license_record_to_bundle` / `license_records_to_bundles`(async +
  reverse_geocoder) + PROMOTED 42 category/place_kind 매핑 + EXCLUDED skip +
  facility_info. (자연키 `::` / marker P-01 / mypy·22 unit·ruff·import-linter green.)
- [x] `krtour.map.mois.load_mois_license_features_bulk` loader — `license_records_to_bundles`
  → `infra.load_bundles` 얇은 오케스트레이션 + `AsyncKrtourMapClient` 메서드 +
  PostGIS 통합 테스트 3건(적재/skip/idempotent/empty). (mypy 51 / 702 passed.)
- [x] Step A snapshot soft-delete — `infra.soft_delete_features_not_in_snapshot` +
  `krtour.map.mois.{delete_mois_license_features_not_in,sync_mois_license_features_bulk}`
  + `AsyncKrtourMapClient.sync_mois_license_features_bulk` + PostGIS 통합 3건.
  status='inactive'+deleted_at(ADR-017). (mypy 51 / 705 passed.)
- [x] advisory lock helper(ADR-011 기초) — `infra/advisory_lock.py`
  (`advisory_lock`/`try_advisory_lock` async ctx + `advisory_lock_key`) + unit 3 +
  PostGIS 통합 3건. conftest `pg_engine` search_path role 방어 보강. (mypy 52 / 711 passed.)
- [x] `ops.import_jobs` 작업 큐(ADR-011) — alembic 0006 + `ImportJobRow` +
  `infra/jobs_repo.py`(enqueue/claim advisory+SKIP LOCKED/heartbeat/finish/
  recover_stale) + `ImportJob` + integration 9. (mypy 53 / 720 passed.)
- [x] MOIS Step A 작업 통합 — `jobs_repo.start_import_job` + `krtour.map.mois.run_mois_license_bulk_job`
  (advisory lock 단일 워커 직렬화 + import_jobs 추적 + sync) + `AsyncKrtourMapClient`
  메서드 + `MoisBulkJobResult` + integration 2. (mypy 53 / 722 passed.)
- [x] MOIS Step A streaming 배치 적재 — `_batched` + `DEFAULT_BATCH_SIZE` +
  `batch_size` 인자(sync/run/client) + `FeatureLoadResult.merge`. `records`로
  `iter_open_place_records(...)` 주입 시 Step A 완성(ADR-006 호출자 주입). unit 7 +
  integration 1. (mypy 53 / 730 passed.)
- [x] CLI mutex(SPRINT-4 §2.8) — `src/krtour/map/cli/` layer 신설 + `cli/mutex.py`
  (`mutex_lock`/`try_mutex_lock` + lock key 헬퍼) + import-linter layers cli 최상위
  추가. unit 4 + integration 3. (mypy 55 / 737 passed.)
- [x] krtour-map CLI 골격 + status — `cli/main.py`(argparse + status) +
  `infra/status_repo.gather_status_counts` + `AsyncKrtourMapClient.status_counts` +
  `[project.scripts] krtour-map`. unit 5 + integration 2. (mypy 57 / 744 passed,
  `krtour-map --help` 실동작.)
- [x] dedup MOIS self-sibling — `core/dedup.find_sibling_candidates`(within-set
  pairwise) + `AsyncKrtourMapClient.sync_sibling_candidates`. unit 6 + integration 1.
  (mypy 57 / 751 passed.)
- [x] geocoder 보강 라이브 재검증 — kraddr-geo REST(`127.0.0.1:9001`) 실연동으로
  MOIS 좌표 → bjd_code 보강 200/200(100%) 확인. `docs/reports/mois-live-test-2026-06-01.md`
  §5. 코드 변경 없음.
- [x] CLI mutate 명령 ①  `krtour-map import mois <records-file>` — NDJSON snapshot
  record source(`cli/records.py`, ADR-006 provider 미import) → `run_mois_license_bulk_job`
  (advisory lock self-serialize + import_jobs 추적, lock 미획득 시 exit 3).
  `--geocoder-url` 선택 보강. unit 17 + integration 2. (ruff/mypy 58/import-linter 4 /
  776 passed.)
- [x] CLI mutate 명령 ② `krtour-map dedup-merge <review_key>` — 수동 병합(ADR-016).
  merge primitive 신규: `core.scoring.select_master`(좌표→updated_at→원천우선순위) +
  `infra.merge_repo`(source_link 재지정+충돌drop / loser soft-delete / 큐 merged 전이)
  + alembic 0007 `ops.feature_merge_history` + `client.merge_dedup_review`. lock은 CLI
  소유(`dedup-merge:{review_key}`), skip exit 3 / 미존재·이미검토 exit 2. unit 9 +
  integration 9. (ruff/mypy 59/import-linter 4 / 794 passed.)
- [x] Step B incremental + cursor. `infra/sync_state_repo`(get/record_success/failure,
  UPSERT) + `mois.run_mois_license_incremental_job`(prune 없음 + cursor 전진) +
  `client.run_mois_license_incremental_job` + `import mois --mode incremental --cursor
  <값> [--sync-scope]`. `provider_sync_state` 기존 테이블 활용(마이그레이션 없음).
  unit 3 + integration 9. (ruff/mypy 60/import-linter 4 / 806 passed.)
- [x] dedup false-positive 측정 + ADR-016 검토. 대표 평가셋 14쌍 채점 — 오토머지 FP
  **0** / true-dup recall **100%** / manual precision 63.6%. **가중치·임계값 변경 없음**
  (안전성 검증; 접미사 stripping은 접두사 충돌 FP 위험으로 보류). `docs/reports/
  dedup-fp-measurement-2026-06-01.md` + 회귀 가드 `tests/unit/test_dedup_fp_measurement.py`.
  (810 passed.)
- [x] (Sprint 4b) Step C 폐업/취소 — `infra.inactivate_features_by_source_entity_ids`
  + `mois.close_mois_license_features`/`run_mois_license_closed_job` + `import mois
  --mode closed --cursor`. feature `status='inactive'`(ADR-017). unit 3 + integration 7.
  (818 passed.)
- [x] (Sprint 4b) Step D on-demand 상세 — `infra.get_primary_source_detail` +
  debug-ui `GET /debug/mois-license/{license_id}`(TTL 캐시, **적재 없음**). 적재된
  raw_data 재사용(ADR-006). debug-ui unit 4 + integration 1. (819 + 117 passed.)
- [x] (Sprint 4b) dedup 운영 FP 측정 도구 — `infra.status_repo.dedup_fp_stats`
  (confirmed=merged+accepted / FP=rejected / precision / fp_rate) + `krtour-map status`
  `dedup FP(운영)` 라인. 운영자 결정 누적분으로 실 FP율 자동 집계(검토 완료 0이면
  "후보 없음"). dedup-fp 리포트 §6 운영 측정 경로 연결. unit 7. (826 passed.)
- [x] (Sprint 4b) ADR-033 F4 — dedup_review_queue 미해소 백로그 baseline 초과 → WARN
  (observe-only). `infra.consistency._check_f4_dedup_backlog` +
  `DEDUP_PENDING_WARN_THRESHOLD`(provisional 1000) + `dedup_pending_threshold` 인자.
  integration 3. (829 passed.)
- [x] (Sprint 4b) Place 전화번호 보강 백그라운드 시작 — `krtour.map.enrichment`
  (`find_place_phone_candidates` + `apply_place_phone_enrichment`: 정규화·dedup·max3 +
  enrichment source_link) + `infra.feature_repo.{find_place_features_without_phone,
  set_feature_phones}` + client 2 메서드. 외부 API는 호출자 주입(ADR-006). integration 6.
  (835 passed.)
- [x] (Sprint 4b) Coverage 80% 완전 달성 — `fail_under` 75→80(ADR-032 Sprint 4 목표).
  실측 **94.12%**(모든 tier 상회). **Sprint 4(4a+4b) 종료.**

## Open PR

(없음 — main 기준 모든 PR merged. 다음 작업은 새 feature branch로.)

## 완료 PR 요약

### 개발 정책 NTFS 전환 및 에이전트 워크트리 재설정 (PR#110, 2026-05-31)

- PR#110 `AGENTS.md` + `docs/dev-environment.md` + `docs/codegraph-worktree.md` 정책 문서 수정 (NTFS를 메인레포로 잡고 테스트 시 WSL 내 ext4로 카피하는 정책 정립, 에이전트별 worktree 프리픽스를 `python-krtour-map-`으로 개정하고 NTFS F:\dev\ 상에 신설 및 .env 로컬 키 복사, MCP 설정의 `codegraph.cwd` 를 각 에이전트 워크트리 경로로 동기화)

### maplibre-vworld-js 스타일 및 MCP 설정 동기화 (PR#107, 2026-05-31)

- PR#107 `react-doctor.config.json` + `.gemini/mcp.json` + `antigravity.json` + `claude.json` + `.codex/config.toml` (maplibre-vworld-js 프로젝트 스타일 및 에이전트별 MCP 설정을 가져와서 각 에이전트 worktree 경로에 맞게 보정하여 동기화)

### 에이전트 설정 형상관리 (PR#105, 2026-05-31)

- PR#105 `claude.json` + `antigravity.json` + `.codex/config.toml` (각 에이전트별 Playwright, Sequential Thinking MCP 설정 파일 생성 및 형상관리 등록)

### Sprint 1 (PR#17~#27, 2026-05-25 종료)

- PR#17 `src/krtour/map/` PEP 420 scaffolding + settings + smoke tests
- PR#18 `category/` 144건 (kraddr-base → krtour.map.category, ADR-023/027)
- PR#19 `dto/` Feature + 5 detail + Coordinate + Address + KST + 27 tests
- PR#20 `core/` exceptions 7종 + `make_feature_id` (ADR-009) + 42 tests
- PR#21 `infra/` crs.py + db.py + testcontainers PostGIS + 31 tests
- PR#22 CI workflows + import-linter 4 계약 (Sprint 1 scaffolding 종료)
- PR#23 PR#1~#21 리뷰 리포트 (`docs/reports/pr-1-21-review.md`)
- PR#24 DTO strictness P0 해소 (detail dict 거부 + datetime aware)
- PR#25 python-knps-api keyless sync + ADR-028 amendment §H
- PR#26 `make_source_record_key` + `make_payload_hash` + SourceRecord/Link/Bundle
- PR#27 review P1 docs drift sweep

### Sprint 2 Prep (PR#28~#29, 2026-05-26)

- PR#28 `infra/models.py` SQLAlchemy 2 + GeoAlchemy2 + Alembic 2 revision
- PR#29 `core/scoring.py` (ADR-016) + `core/providers.py` (canonical 18종)

### Sprint 2 본격 (PR#30~#48, 2026-05-27~28)

- PR#30~31 agent worktree + codegraph 룰 + MCP snippet
- PR#32~33 거버넌스 보강 + ADR-035~043 proposed→accepted
- PR#34 Sprint 2 §2.1 datagokr 축제 1차 (`cultural_festivals_to_bundles`)
- PR#35 디버그 UI backend 첫 라우터 (health/version + openapi drift gate)
- PR#36 frontend skeleton (Next.js 15 + TanStack Query + Zustand)
- PR#37 ADR-041 kraddr-base 흡수 — Address DTO 보강 + `core/address.py`
- PR#38 `WeatherValue` DTO + 3 enum + KMA 단기예보 1차
- PR#39 KMA 초단기실황 + `core/weather.py` pure 헬퍼 5종
- PR#40 `python-*-api` 라이브러리 status sweep
- PR#41 KMA 초단기예보 (`getUltraSrtFcst`) + LGT(낙뢰)
- PR#42 `PriceValue` DTO + `PriceDomain` + opinet `prices_to_values`
- PR#43 opinet `stations_to_bundles` (gas station Feature)
- PR#44 디버그 UI ETL preview 라우터 (fixture dry-run)
- PR#45 Sprint 2 §2.4 krex 휴게소 4 dataset multi-kind
- PR#46 KMA weather_alerts → notice + krex category fix + ETL 11 dataset
- PR#47 ETL preview `?source=live` (KMA 3) + 8 provider key + CI red 3종 해소
  (httpx dep / Alembic 1.18 path_separator + async commit / coord_5179 assert)
- PR#48 agent worktree `geo-*` → `krtour-map-*` rename + tasks.md 최신화
- PR#49 maplibre-vworld v0.1.0 의존 핀 정합 (git URL+tag, zod ^4.4.3, ADR-036 amendment)
- PR#114 maplibre-vworld v0.1.2 + Next.js 16 최신화 (git URL+tag, ESLint CLI flat config)
- PR#50 Sprint/task/resume 문서 일관성 재정비
- PR#51 Sprint 2 §2.1 끝물 — VisitKorea TourAPI enrichment (`festival_to_enrichment_links`)
- PR#52 Sprint 2 §2.2 마무리 — KMA 중기예보 (`mid_land_forecast`/`mid_temperature`)
- PR#53 fix: OpiNet product code map C004/K015 정정 (kerosene/lpg)
- PR#54 ADR-044 — 관련 라이브러리 로컬(`F:\dev\`) 우선 조회 + 데이터 정합성 책임 분계
- PR#55 ETL live — krex 4 dataset loader (EX OpenAPI, 14 단위 test)
- PR#56 ETL live — opinet 2 dataset loader (detailById.do, KATEC→WGS84, 10 단위 test)
- PR#57 ETL live — datagokr 전국문화축제표준데이터 loader (7 단위 test)
- PR#58 ETL live — kma_weather_alerts (apihub `wrn_now_data`, 8 단위 test) → 11/11 live
- PR#59 Sprint 2 종료 — coverage 50→65 + 회고 + Sprint 3 진입 (본 PR)

### 문서/거버넌스 (PR#1~#16, 2026-05-24~25)

- PR#1 ADR-021/022/023 (PR-only + namespace + category 이전)
- PR#2 T-002~T-011 (v1→v2 docs 14건 이전)
- PR#3~4 ADR-024 + mois-feature-etl.md
- PR#5 forest rename + category Tier 1~4 + KNPS 카탈로그
- PR#6 ADR-025/026 (maplibre-vworld + TripMate UI 통일)
- PR#7 tasks.md 백로그
- PR#8 ADR-030/031/032/033 proposed
- PR#9 ADR-027 (forest category 확장)
- PR#10 ADR-029 + T-012~018 codify + 명명 일치화
- PR#11 ADR-025 2차 (Vite → Next.js)
- PR#12 ADR-028 + knps-feature-etl.md
- PR#13 tasks.md 갱신
- PR#14 ADR-034 provider 9단계 + Sprint 2~5 plan
- PR#15 governance sweep
- PR#16 T-014 Sprint 1 진입 (ADR 027~034 accepted + fail_under=50)

## 진척도

### 핵심 governance / 결정

- [x] `AGENTS.md` / `README.md` / `SKILL.md` / `CLAUDE.md`
- [x] `LICENSE` (GPL-3.0-or-later)
- [x] `.gitignore`, `.gitattributes`, `.env.example`
- [x] `pyproject.toml` (스택 + import-linter 계약)
- [x] `docs/architecture.md` (의존 방향 + 데이터 흐름)
- [x] `docs/decisions.md` (ADR-001 ~ ADR-043, 전부 accepted)
- [x] `docs/data-model.md` / `docs/performance.md` / `docs/test-strategy.md`
- [x] `docs/backend-package.md` / `docs/agent-guide.md`
- [x] `docs/dev-environment.md` / `docs/windows-reinstall-recovery.md`
- [x] `docs/feature-model.md` / `docs/provider-contract.md` / `docs/external-apis.md`
- [x] `docs/debug-ui-package.md` / `docs/codegraph-worktree.md`
- [x] `docs/tasks.md` / `docs/resume.md` / `docs/journal.md`
- [x] ADR-021 (PR-only) + ADR-022 (krtour namespace) + ADR-023 (category 이전)
- [x] Sprint 1~5 계획 (`docs/sprints/SPRINT-1.md` ~ `SPRINT-5.md`)

### 코드 산출물

- [x] `src/krtour/map/category/` — 144건 PlaceCategory
- [x] `src/krtour/map/dto/` — Feature + 5 detail + Coordinate + Address +
      WeatherValue + PriceValue + SourceRecord/Link/FeatureBundle
- [x] `src/krtour/map/core/` — exceptions 7종 + `make_feature_id` +
      `make_source_record_key` + `make_payload_hash` + `make_weather_value_key` +
      `make_price_value_key` + scoring (Record Linkage) + providers (canonical 18종)
      + weather (5 helper) + address (bjd/phone/한글 정규화) + types (KST)
- [x] `src/krtour/map/infra/` — models.py (ORM, +FeatureConsistencyReportRow) +
      crs.py (pyproj) + db.py (async engine) + consistency.py (ADR-033 Phase 1
      F1~F3) + Alembic 3 revision (0003 = ops.feature_consistency_reports)
- [x] `src/krtour/map/providers/` — standard_data / kma / opinet / krex /
      visitkorea (enrichment, PR#51) / knps (Point/place 5 + geometry route/area
      5) — 6 provider. `core/geometry.py`(shapely WKT) + `Feature.geom` 추가.
- [ ] `src/krtour/map/providers/` — knps SHP bytes→WKT 디코딩(park_boundaries) /
      krheritage (Sprint 3) / mois (Sprint 4)
- [x] `src/krtour/map/infra/feature_repo.py` — raw SQL load 경로 (Sprint 3 —
      FeatureBundle upsert features/source_records/source_links + get_feature_row,
      ADR-004; bulk COPY + /features 라우터는 후속)
- [ ] `src/krtour/map/client/` — `AsyncKrtourMapClient` (Sprint 3~4)
- [x] `packages/krtour-map-admin/` — create_app + routers (health/version/etl)
      + settings (8 provider key) + etl_fixtures + etl_live + openapi.json
- [x] `packages/krtour-map-admin/frontend/` — Next.js 16 + TanStack + Zustand
      + ETL preview page
- [x] `packages/map-marker-react/` — skeleton (`private: true`, ADR-043)
- [x] `.github/workflows/{ci,lint,openapi}.yml` + import-linter 4 계약
- [x] `tests/` — 469+ pytest (unit + integration + lint)
- [x] 에이전트별 MCP 설정 파일 (`claude.json`, `antigravity.json`, `.codex/config.toml`)

### 미완료 (Sprint 순서)

- [x] visitkorea enrichment (Sprint 2 잔여 1/4 — PR#51)
- [x] KMA 중기예보 (`mid_forecast`, Sprint 2 잔여 2/4 — PR#52)
- [x] ETL live 11/11 dataset (Sprint 2 잔여 3/4 — PR#55~#58)
- [x] Coverage 65% (Sprint 2 DoD — PR#59)
- [ ] 통합 검증 (ETL live 실데이터/정합성/DB 적재/Playwright e2e + 리포트, tasks #114~#118)
- [ ] KNPS 14 dataset + krforest trails (Sprint 3)
- [ ] krheritage 국가유산 (Sprint 3)
- [x] ADR-033 Phase 1 F1~F3 (Sprint 3 — alembic 0003 + `infra/consistency.py`)
- [x] `infra/feature_repo.py` raw SQL load 경로 (Sprint 3 — upsert/load_bundles/
      get_feature_row, ADR-004)
- [x] `/features/*` 조회 라우터 (debug-ui — bbox + 단건, `features_in_bbox`,
      Sprint 3). frontend 지도 wiring(#117)은 후속.
- [x] MOIS Step A~D 4단계 (Sprint 4 — bulk/incremental/closed/detail)
- [x] dedup_review_queue 운영 + dedup-merge + feature_merge_history (Sprint 4)
- [x] ADR-033 F4 (dedup 백로그 WARN, Sprint 4b)
- [x] Place phone enrichment (Sprint 4b — `krtour.map.enrichment`)
- [ ] 휴양림/수목원 + 박물관/미술관 (Sprint 5)
- [ ] Phase 2 F5~F8 + Dagster 게이트 (Sprint 5)
- [ ] ADR-045 Docker 독립 프로그램화 (compose + admin OpenAPI + 독립 Dagster)
- [ ] T-101 MV / T-102 pg_prewarm / T-103 streaming (운영 후)

## 다음 ADR

**accepted (text on main)**: ADR-001 ~ ADR-047 전부.
029→043 supersede, 044 (로컬 우선 조회 + 정합성 책임), 045 (krtour-map Docker 독립
+ OpenAPI, ADR-003 supersede), 046 (호환 shim 금지), 047 (고정 포트
API 9011/admin UI 9012/Dagster 9013). 다음 후보 번호 = ADR-048.

**후보 (미작성)**:
- ADR-048+ — 신규 provider 추가 절차 표준 (체크리스트)
- (필요 시) Sprint 5 MV / pg_prewarm 도입 ADR (T-101/102)

## 차단 사유 / 결정 대기

- **Sprint 2 → 3 전환**: (visitkorea enrichment ✅ PR#51) mid_forecast + ETL
  live 8종 + coverage 상향 후 Sprint 2 종료 회고 → Sprint 3 진입 PR.
- ~~**SHP/GeoJSON parser 위치**~~: ✅ 결정됨 (2026-05-29) — **knps-api 책임**
  (ADR-028 Amendment I / ADR-044). 본 lib는 record(좌표·WKT) Protocol 소비만.
- **ADR-033 Phase 1 시점**: Sprint 3 진입 후 `feature_consistency_reports` F1~F3
  도입 — Sprint 2 provider 적재가 선행 조건.

## v1 산출물 reference

코드 작성 단계에서 v1을 참고할 때:

```bash
git checkout v1                          # v1 브랜치로
ls src/krtour/map/                       # 기존 모듈 구조
cat docs/event-feature-etl.md            # provider 문서 예시
git checkout main                        # 복귀
```

또는 GitHub UI:
- https://github.com/digitie/python-krtour-map/tree/v1

저장소 루트의 `python-krtour-map-spec.docx` (약 80쪽)는 v1 산출물 + SPEC V8
정합 + kraddr-geo 디시플린을 종합한 reference.

## 핵심 메시지

Sprint 2 완료 — provider ①~④(축제·날씨·유가·휴게소) + visitkorea enrichment +
KMA mid_forecast + 디버그 UI backend + **ETL live 11/11 dataset** + coverage 65.
다음은 사용자 지시(2026-05-28)에 따른 **통합 검증**: ETL live 실데이터로 유입·
정합성·DB 적재·debug UI(Playwright)를 끝까지 검증하고 상세 리포트를 남긴다.
그 후 Sprint 3 (KNPS/krheritage + 정합성 Phase 1 + `feature_repo.py` 실 적재)
진입. 현재 적재(DB write)는 아직 없고 provider → DTO 변환 + 디버그 preview까지
완성된 상태다.
