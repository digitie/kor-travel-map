# resume.md — 현재 진척도와 다음 한 작업

## 현재 상태

**v2 Sprint 1 scaffolding 종료, Sprint 2 진입 준비** (PR#17~#26 머지 완료
2026-05-25). main은 orphan으로 v2 사양 새로 시작. v1은 `v1` 브랜치에 보존.
ADR **001~034 모두 accepted** (T-014 + ADR-028 amendment §H, knps-api keyless
반영). `pyproject.toml` `fail_under=50` (Sprint 1 bar). Sprint 1 산출물:
- `src/krtour/map/` PEP 420 namespace + 6 layer (category 144건 + dto Feature
  + 5 detail + Coordinate + SourceRecord/Link + FeatureBundle + core 7 exceptions
  + ID helpers `make_feature_id`/`make_source_record_key`/`make_payload_hash` +
  infra `crs.py`/`db.py` skeleton)
- CI workflows (`.github/workflows/{ci,lint,openapi}.yml`) + import-linter
  4 계약 + testcontainers PostGIS 통합 테스트 베이스
- review report (`docs/reports/pr-1-21-review.md`) P0 4건 해소 (PR#24/#26 +
  Codex 후속 보강)

**중요 신규 룰 (ADR-021~023, 2026-05-24)**:
- main 직접 push 금지 — feature branch + PR만 (ADR-021).
- Python import는 `from krtour.map import ...` (`krtour_map` flat 금지, ADR-022).
- Category 모듈은 `krtour.map.category` (kraddr-base에서 이전, ADR-023).

스택 확정 (ADR-007):
- PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2
- GeoPandas + Shapely 2 + GDAL
- Pydantic v2 / FastAPI + Uvicorn / httpx + tenacity / Alembic

TripMate 연계 (ADR-003): 함수 직접 호출. REST 없음. 디버그 REST/UI는 별도
Python 패키지 `krtour-map-debug-ui` (ADR-020, `packages/krtour-map-debug-ui/`,
인증 없음 + 내부망 전용 ADR-005).

2026-05-25 codex 리뷰: PR#1~#21 신규 소스·문서 상세 리뷰 리포트는
`docs/reports/pr-1-21-review.md`. 핵심 보완 후보는 `Feature.detail` dict 입력
차단, DTO datetime KST 정책 일관화, Sprint 1 active 상태 문서 drift 정리,
PR#22 CI/import-linter merge 후 gate 확인. PR#22 merge 후 PR#23 리포트
브랜치 충돌은 2026-05-25 18:08 KST 기준 해결.

## 다음 한 작업

**Sprint 1 후속 PR 진행 상황**:
- [x] PR#17 `src/krtour/map/` PEP 420 scaffolding (`__init__.py`,
      `settings.py`, `py.typed`, 6 layer placeholder + smoke tests)
- [x] PR#18 `src/krtour/map/category/` 144건 코드 이전 (kraddr-base
      → krtour.map.category, ADR-023 + ADR-027) + 16 tests + docs/category
      통계 정정 — 30 pytest passed
- [x] PR#19 `src/krtour/map/dto/` Feature + 5 detail kinds (place/event/
      notice/route/area) + Coordinate + Address + URLs + OpeningHours +
      `core/types.py` KST/kst_now + NOTICE_TYPES 14건 (ADR-027) +
      AreaDetail.area_kind 'hazard_zone' (ADR-027) + ADR-018 detail
      discriminator + ADR-019 KST aware enforcement + 27 dto tests.
      WeatherValue/PriceValue/SourceRecord은 Sprint 2 PR로 연기.
- [x] PR#20 `src/krtour/map/core/` exceptions 7종 + `make_feature_id`
      (ADR-009 결정적 SHA1) + 42 tests. dto 의존 없이 자체 완결.
- [x] PR#21 `src/krtour/map/infra/` skeleton: `crs.py` (pyproj.Transformer
      singleton, ADR-030 narrow cache) + `db.py` (async engine + DSN
      정규화) + `tests/integration/conftest.py` (testcontainers PostGIS) +
      `test_pg_smoke.py` (extension 격리 + ST_Transform 정합). pyproj>=3.6
      dep. 25 unit + 6 integration tests.
- [x] PR#22 `.github/workflows/{ci,lint,openapi}.yml` + import-linter 4 계약
      활성화 + `tests/lint/test_import_linter.py`. **ADR-002 위반 1건 실 해소**
      — `dto/_time.py` 분리. ruff/mypy/import-linter all green. **Sprint 1
      scaffolding 마지막 PR, 2026-05-25 merge.**
- [x] PR#23 `docs/reports/pr-1-21-review.md` — PR#1~#21 신규 소스·문서 상세
      리뷰 리포트. P0 4건 + P1 docs drift + P2 안정화 식별. PR#22 merge 후
      충돌 해결 완료, merged.
- [x] PR#24 (merged) review report P0-1/2/3 해소: `Feature.detail` mode=before
      dict 거부 + 모든 DTO datetime aware validator + 8자리 category 정규식.
      `dto/_time.py`에 `check_aware_datetime()` 공용 helper.
- [x] PR#25 (merged) python-knps-api PR#3+#4 (keyless file-only, `06da125f`)
      반영. ADR-028 amendment §H. 14 dataset 정정. DTO에 `protected_area` /
      `facility_road` 표준값 추가 (사용자 별도 적용).
- [x] PR#26 (merged) review report P0-4 — `make_source_record_key` +
      `make_payload_hash` (`docs/data-model.md §11` 명세) + `SourceRecord` +
      `SourceLink` + `FeatureBundle` DTO. dto는 core 미import 원칙 준수
      (`SourceRecord.key()` 메서드 두지 않음 — 호출자가 helper로 계산).
      리뷰 후속으로 DB required 필드와 bundle 교차 검증, payload hash strict
      normalize, canonical docs 예시 정합 보강.
- [x] PR#27 (merged) review report P1: docs drift sweep — README/SKILL/agent-guide/
      tasks의 "Sprint 1 진입 직전" / "코드 작성 금지" 잔재 문단을 Sprint 1
      종료/Sprint 2 진입 준비 상태로 갱신.
- [ ] 후속 ADR (TBD, Sprint 3 KNPS 적재 이전): `access_restriction`/`fire_alert`
      notice source 결정 — 산림청 (`python-krforest-api`) / 소방청 / scrape
      중 선택.
- [x] **PR#28 (현재 open) / Sprint 2 prep**: `infra/models.py` SQLAlchemy 2
      declarative + GeoAlchemy2 (FeatureRow + SourceRecord/Link + ProviderSyncState)
      + Alembic 인프라 (`alembic.ini` + async-compatible `env.py` + 첫 2
      revision: 0001 4 schemas + 3 extensions on `x_extension` / 0002 features
      + source 테이블 + 핵심 인덱스 STORED coord_5179 + BRIN imported/fetched_at)
      + integration test 6 case. `alembic>=1.13` dep. 199 unit pytest passed,
      ruff/mypy(29 src files)/import-linter all green.
- [x] **PR#29 (merged)** Sprint 2 prep 2: `core/scoring.py` ADR-016
      Record Linkage (가중치 0.45/0.35/0.20 + 임계값 0.85/0.65 + Coordinate
      의존) + `core/providers.py` CANONICAL_PROVIDER_NAMES 18종 + alias 24종.
      `jellyfish>=1.0` dep. `core/weather.py`는 WeatherValue DTO 의존 →
      Sprint 2 KMA PR에서 함께. 238 pytest passed, all lint green.
- [x] **PR#30 (merged 2026-05-27 12:35)** agent worktree + codegraph 룰:
      `docs/codegraph-worktree.md` 신규 + AGENTS/CLAUDE/SKILL/agent-guide/
      dev-environment 절 추가 + `.gitignore`에 `.codegraph/`. 본 PC에 codegraph
      v0.9.5 설치 + `.codegraph/` 인덱스 초기화 (64 파일/719 노드/1,205 edge).
      향후 모든 AI 에이전트는 자기 전용 worktree(`geo-codex`/`geo-claude`/
      `geo-antigravity`) + 로컬 codegraph 인덱스로 작업.
- [x] **PR#31 (merged 2026-05-27)** codegraph MCP 등록 snippet + `codegraph_
      explore` 영향도 평가 룰. `codegraph serve --mcp` 공식 snippet + `npx`
      대안 + WSL2 `--no-watch`.
- [x] **PR#32 (merged 2026-05-27)** 거버넌스 보강 + ADR-035~043 proposed.
      운영 단계 진입 사용자 지시 8건 + 정책 reverse 1건을 ADR 9건으로 박음.
- [x] **PR#33 (merged 2026-05-27)** ADR-035~043 9건 일괄 accepted 전환 (PR#16
      027~034 패턴 그대로). ADR 현황 = 001~043 모두 accepted, 029는 ADR-043
      supersede. 다음 후보 번호 = ADR-044.

## 다음 한 작업 (PR#34 머지 후)

- [x] **PR#34 (merged 2026-05-27)** — Sprint 2 §2.1 datagokr 표준데이터 1차
      축제 provider. `src/krtour/map/providers/standard_data.py` —
      `cultural_festivals_to_bundles` + `CulturalFestivalItem`/`ReverseGeocoder`
      Protocol + fixture 5 + 14 unit tests.
- [x] **PR#35 (merged 2026-05-27)** — Sprint 2 §2.5 debug/관리 UI backend 첫
      라우터 (ADR-031 + ADR-035 + ADR-038). `packages/krtour-map-debug-ui/src/
      krtour/map_debug_ui/` 신설 — `create_app(settings)` factory + `/debug/
      health` + `/debug/version` 2 라우터 + `openapi.json` drift gate
      baseline + `.github/workflows/{ci,openapi}.yml` 정상 활성. mypy_path
      통합. 6 debug-ui tests + 258 total green.
- [x] **PR#36 (merged 2026-05-27)** — Sprint 2 §2.5 frontend skeleton.
      Next.js 15 App Router + React 19 + TanStack Query + Zustand (ADR-025 +
      ADR-037). `src/api/{client,queries}.ts` (`/debug/health` + `/debug/
      version` useQuery hook) + `src/state/map.ts` (Zustand map viewport
      store) + `src/providers/query-client-provider.tsx` + `src/app/
      {layout,page}.tsx`. `packages/map-marker-react/package.json`
      `"private": true` (ADR-043 npm 게시 보류).
- [x] **PR#37 (merged 2026-05-28)** — ADR-041 본격 구현. `python-kraddr-base`
      의존 완전 제거. `Address` DTO 보강 (admin_dong_code/road_name_code/
      road_address_management_no/zipcode/sido_name/sigungu_name 추가 +
      자릿수 strict validator + bjd↔sigungu/sido consistency model_validator
      + is_complete()/display() helper). `core/address.py` 신설 — BjdParts /
      normalize_bjd_code / parse_bjd_code / extract_sigungu_code /
      extract_sido_code / normalize_phone_number / normalize_korean_text.
      `standard_data.py`에서 utility 적극 활용. 320 unit tests green.
      `PlaceCoordinate`는 명시적 제외 (좌표는 Coordinate 단일 source).
- [x] **PR#38 (merged 2026-05-28)** — Sprint 2 §2.2 KMA 단기예보 1차 진입.
      `dto/weather.py` `WeatherValue` DTO + 3 enum (`WeatherDomain` 16값 /
      `ForecastStyle` 7값 / `TimelineBucket` 3값, ADR-010 두 축 분리).
      `core/ids.py` `make_weather_value_key` 추가 (wv_{sha1[:20]}, timeline_
      bucket 제외). `providers/kma.py` `short_forecast_to_weather_values` +
      `KmaShortForecastItem` Protocol + KMA_METRIC_UNITS/NAMES 18종. 352
      tests green (신규 32).
- [x] **PR#39 (merged 2026-05-28)** — Sprint 2 §2.2 KMA 초단기실황 + `core/
      weather.py` pure 헬퍼 5종. `providers/kma.py` `ultra_short_nowcast_to_
      weather_values` + `KmaUltraShortNowcastItem` Protocol (observed_at 매핑,
      valid_at None). `core/weather.py` `pick_nowcast_value` / `pick_timeline_
      slice` / `group_by_metric_key` / `filter_by_provider` / `latest_by_
      metric_key` — DB 없이 동작하는 build_weather_card 빌드 블록. 373 tests
      green (신규 21).
- [x] **PR#40 (merged 2026-05-28)** — `python-*-api` 라이브러리 status sweep.
      `pyproject.toml [providers]` extra Sprint 그룹화 + kraddr-base 라인
      제거 (ADR-041) + Protocol 박힌 라이브러리(`kma`/`datagokr`) 본 lib 측
      참조 명시 + knps `@06da125f` (PR#25) 박음. `docs/provider-contract.md`
      §4 책임 매트릭스 + §12 git URL/sha status 표 (16 row) 갱신.
      `AGENTS.md` 식별자 표 cross-reference 추가.
- [x] **PR#41 (merged 2026-05-28)** — Sprint 2 §2.2 KMA 초단기예보 추가
      (`getUltraSrtFcst`). `providers/kma.py` `ultra_short_forecast_to_
      weather_values` + `KmaUltraShortForecastItem` Protocol. 단기예보와 동일
      shape이지만 forecast_style=ULTRA_SHORT, timeline=ULTRA_SHORT.
      `KMA_METRIC_UNITS/NAMES`에 LGT(낙뢰) 추가. 383 tests green (신규 10).
      KMA 진행: short ✅ / ultra_short_nowcast ✅ / ultra_short_forecast ✅ /
      mid ⏳ / weather_alerts ⏳.

다음 PR 후보 (Sprint 2 entry 계속):

1. **PR#37 — Sprint 2 §2.2 kma 날씨**:
   - `src/krtour/map/providers/kma.py` —
     `short_forecast_to_weather_values` / `ultra_short_nowcast_to_weather_
     values` / `mid_forecast_to_weather_values` / `weather_alerts_to_notice_
     bundles`.
   - 보조 provider: airkorea / krforest_mountain_weather / khoa_coastal.
   - `dto/weather.py` `WeatherValue` 신설 (timeline_bucket / forecast_style)
   - `core/weather.py` `build_weather_card` (Sprint 2 prep PR#29 연기분).

2. **PR#38 — Sprint 2 §2.3 opinet 유가** + `PriceValue` DTO + BRIN bulk
   (`psycopg.copy_*` 안전 마진 30k 검증, ADR-013).

3. **PR#39 — Sprint 2 §2.4 krex 휴게소** — multi-kind (place + price +
   weather + notice) 통합 테스트 + EXPLAIN bbox/BRIN 검증.

4. **PR#40 — Sprint 2 §2.1 끝물 visitkorea TourAPI enrichment** —
   `festival_to_enrichment_links` (datagokr feature_id ↔ visitkorea
   contentId, `source_role='enrichment'`).

5. **PR#41 — Sprint 2 §2.5 backend `/features/*` 라우터 + frontend wiring**:
   - `src/krtour/map/infra/feature_repo.py` raw SQL (`features_in_bounds`,
     `features_nearby`, `get_feature_by_id`)
   - `routers/features.py` — `/features/in-bounds`, `/features/nearby`,
     `/features/{id}`
   - frontend `src/api/{client,queries}.ts`에 `useFeaturesInBounds` 등 추가
   - maplibre-vworld 실 컴포넌트 통합 — landing page를 지도 화면으로 교체

6. **PR#42+ — Sprint 3 진입** — knps / krforest_trails / krheritage +
   ADR-036 maplibre-vworld-js v0.1.0 분리 prep + ADR-033 Phase 1 (F1~F3).

2. **PR#36 — Sprint 2 §2.5 frontend 시작** (ADR-025 + ADR-037 + ADR-043):
   - `packages/krtour-map-debug-ui/frontend/package.json`에 `@tanstack/
     react-query` + `zustand` 추가
   - `packages/map-marker-react/package.json` `"private": true` 박음 (ADR-043)
   - 기본 페이지 + map viewport Zustand store + `/features/in-bounds`
     useQuery hook

3. **PR#37 — Sprint 2 §2.2 kma 날씨**:
   - `src/krtour/map/providers/kma.py` —
     `short_forecast_to_weather_values` / `ultra_short_nowcast_to_weather_
     values` / `mid_forecast_to_weather_values` / `weather_alerts_to_notice_
     bundles`.
   - 보조 provider: airkorea / krforest_mountain_weather / khoa_coastal.
   - `dto/weather.py` `WeatherValue` 신설 (timeline_bucket / forecast_style)
   - `core/weather.py` `build_weather_card` (Sprint 2 prep PR#29 연기분).

4. **PR#38 — Sprint 2 §2.3 opinet 유가** + `PriceValue` DTO + BRIN bulk.

5. **PR#39 — Sprint 2 §2.4 krex 휴게소** — multi-kind (place + price +
   weather + notice) 통합 테스트.

6. **PR#40 — Sprint 2 §2.1 끝물 visitkorea TourAPI enrichment** —
   `festival_to_enrichment_links` (datagokr feature_id ↔ visitkorea
   contentId, `source_role='enrichment'`).

7. **PR#41+ — Sprint 3 진입** — knps / krforest_trails / krheritage +
   ADR-036 maplibre-vworld-js v0.1.0 분리 prep + ADR-033 Phase 1 (F1~F3).
- [ ] **Sprint 2 첫 provider PR** (ADR-034 1단계, PR#30 후보):
      `providers/visitkorea/` 축제 + `infra/feature_repo.py` raw SQL +
      `feature_event_details` 테이블 마이그레이션.

## 진척도

### 핵심 governance / 결정

- [x] `AGENTS.md` (지시 우선순위, DO NOT 룰, TripMate 경계)
- [x] `README.md` (정체성, 빠른 시작, 문서 지도)
- [x] `SKILL.md` (DO NOT, 자주 묻는 작업, 도메인 어휘)
- [x] `CLAUDE.md` (1쪽 진입 요약)
- [x] `LICENSE` (GPL-3.0-or-later)
- [x] `.gitignore`, `.gitattributes`, `.env.example`
- [x] `pyproject.toml` (스택 + import-linter 계약 placeholder)
- [x] `docs/architecture.md` (의존 방향 + 데이터 흐름 + 모듈 표)
- [x] `docs/decisions.md` (ADR-001 ~ ADR-019)
- [x] `docs/data-model.md` (전체 table + 인덱스 + CHECK)
- [x] `docs/performance.md` (인덱스 + 공간 쿼리 + bulk + 안티패턴)
- [x] `docs/test-strategy.md` (4단계 테스트 + Coverage + EXPLAIN 검증)
- [x] `docs/backend-package.md` (라이브러리 API + 디버그 REST)
- [x] `docs/agent-guide.md` (첫 5분 + 체크리스트)
- [x] `docs/dev-environment.md` (WSL ext4/NTFS)
- [x] `docs/windows-reinstall-recovery.md` (세션 복구)
- [x] `docs/feature-model.md` (Feature DTO + detail 7 kind)
- [x] `docs/provider-contract.md` (wrapper 금지 + 카탈로그)
- [x] `docs/external-apis.md` (API 키 발급/호출)
- [x] `docs/tasks.md` (백로그)
- [x] `docs/resume.md` (본 문서)
- [x] `docs/journal.md` (작업 일지)
- [x] `docs/debug-ui-package.md` (ADR-020에 따른 별도 패키지 사양)
- [x] `packages/krtour-map-debug-ui/` (별도 패키지 skeleton — pyproject + README)
- [x] ADR-021 (PR-only) + `docs/agent-guide.md` §7.5 (PR 워크플로 + commit format)
- [x] ADR-022 (`krtour` implicit namespace) + 전 docs/pyproject 일괄 rename
- [x] ADR-023 (kraddr-base category 이전) + `docs/category.md` 신설

### v1 → v2 도큐먼트 이관 (2026-05-24 완료)

- [x] T-002 `docs/weather-feature-normalization.md`
- [x] T-003 `docs/feature-files-rustfs.md`
- [x] T-004 `docs/feature-opening-hours.md`
- [x] T-005 `docs/kraddr-base-types.md` + `docs/address-geocoding.md`
- [x] T-006 provider별 ETL 문서 10건 (event/mois-license/opinet/khoa/krheritage/forest/
      krex-rest-area/standard-data/notice/kma-weather/place-phone-enrichment)
- [x] **ADR-024** + `docs/mois-feature-etl.md` 신설 — `python-mois-api` full lifecycle
      (Step A/B/C/D), 195 슬러그 카탈로그, PROMOTED 42종 + EXCLUDED 분류
- [x] 일괄 rename `krmois` → `mois` (canonical name 정정, ADR-024)
- [x] **ADR-025** — 디버그 UI frontend `maplibre-vworld-js` 채택
- [x] `docs/debug-ui-package.md` §14 frontend 사양 + `packages/krtour-map-debug-ui/frontend/`
      skeleton (package.json / .env.example / .gitignore / README)
- [x] **ADR-025 사용자 보강 (2026-05-25)** — VWorld key는
      `KRADDR_GEO_VWORLD_API_KEY` 공유 / 별도 발급 금지 / maplibre-vworld-js
      upstream에 직접 PR로 적극 수정
- [x] **ADR-026** — TripMate 사용자 UI도 `maplibre-vworld` 채택 (SPEC V8 v8_3
      supersede), Kakao Maps JS SDK 제거
- [x] T-007 `docs/dagster-boundary.md`
- [x] T-008 `docs/postgres-schema.md`
- [x] T-009 `docs/debug-fixture-workflow.md`
- [x] T-010 `docs/feature-db-initialization.md`
- [x] T-011 `docs/tripmate-integration.md`

### 코드 작성 단계 진입 전

- [ ] T-012 ADR-020+ 후속 결정 (proposed 4건 — PR#10에서 코드 박힘 + 사용자
      review 후 accepted 전환)
- [x] T-013 `CHANGELOG.md` 초기 엔트리 정리 — PR#10 merged
- [ ] T-014 코드 작성 단계 진입 검토 (사용자 승인 후, Sprint 1 PR로 진입)
  - **Sprint 1 plan** (`docs/sprints/SPRINT-1.md`) — PR#10 merged (provider
    없음 명확화는 본 PR#14)
  - **Sprint 2~5 plan** (`docs/sprints/SPRINT-2.md` ~ `SPRINT-5.md`) —
    **본 PR#14**에서 ADR-034 9단계 순서로 박음
- [x] T-017c ADR-029 npm 패키지 추출 — PR#10 merged (skeleton). 실 코드는
      Sprint 2.
- [x] T-018a `python-knps-api` provider — PR#12 merged (ADR-028 +
      `docs/knps-feature-etl.md`). 외부 repo scaffold `6e36990` 반영.
- [ ] T-018 본체 — `krtour.map.providers.knps` 모듈 신설 + 적재 (Sprint 3)

## 다음 ADR

**accepted (text on main)**: ADR-001 ~ ADR-034 — 본 PR#16에서 027~034 일괄
proposed → accepted 전환 (T-014 Sprint 1 진입과 동시).

**후보 (미작성)**:
- **ADR-035+** — 신규 provider 추가 절차 표준 (체크리스트)
- 후속 maki npm 게시 자동화 ADR
- (필요 시) Sprint 2 SHP/GeoJSON parser 위치 결정 ADR
- (필요 시) Sprint 5 MV / pg_prewarm 도입 ADR (T-101/102 후속)

## 차단 사유 / 결정 대기

- (없음) 사용자가 코드 작성 시작 신호를 주기 전까지는 모두 문서 작업.

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
정합 + kraddr-geo 디시플린을 종합한 reference. 새 에이전트가 v1 전체를 파지
않고도 핵심을 빠르게 잡을 수 있다.

## 핵심 메시지

이 단계의 미션은 "**문서가 코드보다 먼저 정확하게 박혀 있어야 한다**"다. 코드
작성이 시작되면 본 문서들의 룰이 자동 강제되어야 하고, 그 강제 수단(import-linter,
EXPLAIN 통합 테스트, fixture 회귀, 커버리지)이 모두 ADR/문서에 박혀 있어야 한다.
