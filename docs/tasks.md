# tasks.md — 백로그

이 문서는 작업 백로그다. 우선순위 순. 각 작업은 `T-NNN` 번호로 식별한다.

## 진행 중

**open PR 없음** (main `225ac77`, PR#49까지 merged). 다음 작업은 새 feature
branch로.

### Sprint 2 종료 게이트 (잔여 4건 — 단일 출처: `sprints/SPRINT-2.md §7`)

1. **visitkorea enrichment** — `providers/visitkorea.py`
   `festival_to_enrichment_links` (datagokr feature_id ↔ visitkorea contentId,
   `source_role='enrichment'`). Sprint 2 §2.1 끝물.
2. **KMA `mid_forecast`** — `mid_forecast_to_weather_values` 중기예보 텍스트 +
   AM/PM split. Sprint 2 §2.2 마지막 dataset.
3. **ETL live 나머지 8 dataset** — `etl_live.LIVE_LOADER_REGISTRY` 확장
   (datagokr 1 + opinet 2 + krex 4 + kma_weather_alerts 1).
4. **Coverage bar 상향 + Sprint 2 종료 마무리** — `pyproject.toml` `fail_under`
   50→65 (실측 96%) + journal 회고 + resume → Sprint 3 + `SPRINT-3.md` 진입 PR 준비.

## 최근 완료 (Sprint 2)

- **PR#49** (merged 2026-05-28): `maplibre-vworld` v0.1.0 의존 핀 정합 — 기존
  `^1.0.0`은 이중 오류(버전 미존재 + npm 미게시) → `github:digitie/maplibre-
  vworld-js#v0.1.0` git URL+tag 핀 + `zod ^4.4.3`(peer) + ADR-036 amendment.
- **PR#48** (merged 2026-05-28): agent worktree 접두사 `geo-*` → `krtour-map-*`
  일괄 rename (7 normative docs) + 본 `tasks.md` 최신화 (PR#19~#47 반영).
- **PR#47** (merged 2026-05-28): 디버그 UI ETL preview `?source=live` 활성화 +
  8 provider API key(`SecretStr`) settings + `.env.example`. KMA 3 dataset
  (short/nowcast/ultra_short_forecast) 실 호출, 나머지 8은 framework(501).
  `etl_live.py` httpx async loader + LIVE_LOADER_REGISTRY. **CI red 3종 동반
  해소**: httpx dep 누락 / Alembic 1.18 `path_separator` deprecation /
  Alembic 1.18 async migration commit 안 됨(env.py) / coord_5179 assert
  대소문자. 450+21 green.
- **PR#46** (merged): KMA weather_alerts → notice FeatureBundle (alert×region
  fan-out) + krex TRAFFIC_NOTICE_CATEGORY 99000000 정정 + ETL preview registry
  11 dataset.
- **PR#45** (merged): Sprint 2 §2.4 krex 휴게소 multi-kind — 4 Protocol + 4
  변환(rest_areas place / prices food|fuel / weather observed / traffic notice)
  + 동일 feature_id 통합 검증.
- **PR#44** (merged): 디버그 UI ETL preview 라우터 3종 (`providers`/`{provider}/
  datasets`/`{provider}/{dataset}/preview`) + frontend `etl/page.tsx`. dry-run.
- **PR#43** (merged): Sprint 2 §2.3 마무리 — opinet `stations_to_bundles`
  (gas station place Feature, category 06020000).
- **PR#42** (merged): Sprint 2 §2.3 진입 — `PriceValue` DTO + `PriceDomain` +
  `make_price_value_key` + opinet `prices_to_values`.
- **PR#41** (merged): KMA `ultra_short_forecast_to_weather_values`
  (getUltraSrtFcst) + LGT(낙뢰) metric.
- **PR#40** (merged): `python-*-api` 라이브러리 status sweep — pyproject
  `[providers]` extra Sprint 그룹화 + provider-contract §12 git URL/sha 표.
- **PR#39** (merged): KMA `ultra_short_nowcast_to_weather_values` + `core/
  weather.py` pure 헬퍼 5종.
- **PR#38** (merged): Sprint 2 §2.2 진입 — `WeatherValue` DTO + 3 enum
  (WeatherDomain/ForecastStyle/TimelineBucket, ADR-010) + `make_weather_value_
  key` + KMA `short_forecast_to_weather_values`.
- **PR#37** (merged): ADR-041 본격 구현 — `python-kraddr-base` 의존 제거,
  `Address` DTO 보강 + `core/address.py` (bjd/phone/한글 정규화 utility).
- **PR#36** (merged): 디버그 UI frontend skeleton — Next.js 15 + React 19 +
  TanStack Query + Zustand (ADR-037) + map-marker-react `private:true` (ADR-043).
- **PR#35** (merged): 디버그 UI backend 첫 라우터 — `create_app` factory +
  `/debug/health` + `/debug/version` + `openapi.json` drift gate 활성 (ADR-031).
- **PR#34** (merged): Sprint 2 §2.1 datagokr 표준데이터 축제 1차 source
  (`cultural_festivals_to_bundles`, ADR-042).
- **PR#30~33** (merged): agent worktree + codegraph 룰 docs / codegraph MCP /
  거버넌스 보강 + ADR-035~043 proposed→accepted 일괄 전환.
- **PR#28~29** (merged): Sprint 2 prep — `infra/models.py` + Alembic 첫 2
  revision / `core/scoring.py`(ADR-016) + `core/providers.py`.
- **PR#19~27** (merged): Sprint 1 scaffolding (dto/core/infra) + review P0/P1
  해소. 상세는 `docs/journal.md`.
- **upstream knps-api PR#1** (https://github.com/digitie/python-knps-api/pull/1):
  maki icon 정정 (shelter / barrier).

## 다음 (우선순위 순)

- [ ] T-012 — ADR-020+ 후속 결정 작성 (proposed → accepted 사용자 검토 대기)
  - **ADR-030 (proposed, PR#8 merged)** — 라이브러리 in-memory 캐시 금지
    (`functools.cache` 한정 예외) + `import-linter` 계약. PR#10에서
    `pyproject.toml`에 forbidden 계약 박힘 → 사용자 review 후 accepted PR.
  - **ADR-031 (proposed, PR#8 merged)** — 디버그 패키지 OpenAPI export 정책
    (첫 라우터부터 활성화). PR#10에서 `scripts/export_openapi.py` skeleton
    박힘 → 사용자 review 후 accepted PR.
  - **ADR-032 (proposed, 시기 의존)** — Coverage 단계적 상향 일정. PR#10에서
    `pyproject.toml` `fail_under=0` + 주석으로 Sprint 1~5 schedule 박음.
    T-014 + Sprint 1 진입 PR에서 `fail_under=50`으로 상향 + accepted.
  - **ADR-033 (proposed, 시기 의존)** — `feature_consistency_reports` 단계적
    도입. T-014 + Sprint 3 진입 PR에서 Phase 1 (F1~F3) accepted.
- [x] **T-014 — 코드 작성 단계 진입** (사용자 승인 2026-05-25, 본 PR#16)
  - ADR 027/028/029/030/031/032/033/034 일괄 accepted 전환
  - `pyproject.toml` `fail_under=0→50` 상향 (ADR-032 Sprint 1 bar)
  - Sprint 1 = **active** (`docs/sprints/SPRINT-1.md` 상태 → active)
  - 후속 Sprint 1 scaffolding PR로 실제 코드 작성:
    - [x] PR#17 `src/krtour/map/` PEP 420 scaffolding + `settings.py` +
          6개 layer placeholder + smoke 테스트
    - [x] PR#18 `src/krtour/map/category/` 144건 (kraddr-base 이전 +
          ADR-027 3건 + tests/unit/test_category.py 16 cases)
    - [x] PR#19 `src/krtour/map/dto/` Feature + 5 detail (place/event/
          notice/route/area) + Coordinate + Address + URLs + OpeningHours +
          `core/types.py` KST/kst_now + ADR-027 적용 (`NOTICE_TYPES` 14건 +
          `AreaDetail.area_kind='hazard_zone'`) + ADR-018 detail discriminator
          + ADR-019 KST aware datetime + 27 dto cases. WeatherValue/
          PriceValue/SourceRecord은 Sprint 2 PR로 연기.
    - [x] PR#20 `src/krtour/map/core/` exceptions 7종 (ADR backend-package.md §5)
          + `make_feature_id` (ADR-009 결정적 SHA1) + tests 42건. scoring stub은
          dto Coordinate 의존 위해 후속 PR로.
    - [x] PR#21 `src/krtour/map/infra/crs.py` (pyproj.Transformer 4326↔5179
          singleton, ADR-030 narrow cache) + `infra/db.py` (async engine +
          session factory + DSN 정규화) + `tests/integration/conftest.py`
          (testcontainers PostGIS, ADR-007/008) + `test_pg_smoke.py` (extension
          격리 + schema + ST_Transform). pyproj>=3.6 dep. 25 unit + 6 integration.
    - [x] **PR#22 (본)** `.github/workflows/{ci,lint,openapi}.yml` + import-linter
          4 계약 활성화 (`tests/lint/test_import_linter.py`) + ADR-002 위반 1건
          실 해소 (KST/kst_now 정의 core/types.py → dto/_time.py 이전).
          ruff/mypy/import-linter all green. **Sprint 1 scaffolding 종료점.**
    - [x] PR#28 `infra/models.py` + Alembic 첫 2 revision (0001/0002) +
          통합 테스트 6 case (Sprint 2 prep, 2026-05-26 merged).
    - [x] **후속 (PR#29 merged)**: `core/scoring.py` (Record Linkage ADR-016) +
          `core/providers.py` (CANONICAL_PROVIDER_NAMES 18종). `core/weather.py`
          + `kst_now` 통합은 Sprint 2 KMA PR(#38~#39)에서 완료.
- [ ] T-017 — **공통 maki marker / category 매핑 npm 패키지 추출** (ADR-029
      proposed, PR#10 merged) — 실 코드는 Sprint 2
  - **ADR-029 (proposed, PR#10 merged)** — `@krtour/map-marker-react` (MIT
    license, monorepo `packages/map-marker-react/`).
  - PR#10에서 skeleton 박힘 (`package.json` / `README.md` / `vite.config.ts`
    / `.gitignore`).
  - 실제 코드 (`src/categoryMaki.ts`, `<MakiMarker>` 등)는 Sprint 2 PR.
  - drift gate: `tests/unit/test_category_maki_consistency.py` (Python ↔ TS
    1:1 검증, Sprint 2 코드 작성).
- [ ] T-018 — **`python-knps-api` provider 등록 / KNPS 적재 준비**
  - **외부 repo keyless file-only 전환 완료** (2026-05-25):
    `digitie/python-knps-api` `06da125f` (PR#3+#4). 공개 API:
    `KnpsClient`, `KnpsConfig`, `FileDataset`, `CatalogEntry`,
    `FileArtifact`, `FileMember`, `CsvPreview`, `CsvPreviewRow` + 예외 계층 +
    catalog helper. 삭제: `ApiEndpoint`, `Page`, `raw_endpoint`,
    `api_endpoint(s)`.
  - **ADR-028 accepted + amendment §H (PR#25)** — keyless, 14건 모두
    file dataset, `KNPS_SERVICE_KEY`/`DATA_GO_KR_SERVICE_KEY` 사용 안 함.
  - **ADR-027 accepted + 코드 적용 완료** — category 144건,
    `NOTICE_TYPES` 14건, `AreaDetail.area_kind='hazard_zone'`.
    PR#25에서 `protected_area`와 `facility_road` DTO 계약 추가.
  - `krtour.map.providers.knps` 모듈 신설은 Sprint 3 (ADR-034 7단계).
    SHP/CSV parsing은 본 라이브러리 `providers/knps` 책임.
  - 후속 ADR: `access_restriction`/`fire_alert` notice source 결정
    (산림청/소방청/scrape). KNPS는 notice source 아님.
- [ ] T-019 — **TripMate 측 후속 작업 추적** (ADR-026 + ADR-029 후속, 본
      저장소 외)
  - TripMate `apps/web` Kakao Maps → maplibre-vworld 교체 PR (TripMate
    저장소). Next.js stack 유지, 마커 import만 `@krtour/map-marker-react`
    교체.
  - SPEC V8 v8_3 Kakao Maps 섹션에 "superseded by python-krtour-map ADR-026"
    표기 (SPEC 저장소)
  - 본 저장소는 ADR-026/029 reference만 책임. 작업 자체는 미트래킹.

## 보류 (v2 1차 범위 외)

- [ ] T-101 — **Materialized View 도입 검토** (feature + 7 detail flatten)
  - 상세 분석: `docs/performance.md §9.3` (도입 조건, 부작용, ROI).
  - 도입 조건: read >> write 비율 실측 (Sprint 5 이후 24h 로그) + Phase 2
    정합성 게이트(ADR-033)가 이미 작동 + 디스크 ×2 수용.
  - 도입 절차: 하나의 hot path 시범 (예: `mv_features_place_with_detail`) →
    1주 운영 + EXPLAIN diff → 확장 판단 → ADR 신설.
- [ ] T-102 — **pg_prewarm 부팅 후 warm-up**
  - 상세 분석: `docs/performance.md §9.5` (장점, 조건, 부작용, ROI).
  - 도입 조건: 명시적 P99 SLO + 재배포 빈도 높음 + `shared_buffers`가 핫
    데이터 fit (Odroid 기본 512MB는 일부만 가능).
  - 도입 절차: `CREATE EXTENSION pg_prewarm SCHEMA x_extension;` (ADR-008)
    + `autoprewarm = on` background 모드 + `/health` `prewarm_completed:bool`
    노출.
- [ ] T-103 — **streaming ETL (Kafka/Redpanda) 대응** — 본 라이브러리는
      consumer 미보유 (ADR-003)
  - 상세 분석: `docs/performance.md §9.4` (시나리오, 비용, 라이브러리 위치).
  - consumer는 TripMate `apps/etl`이 담당. 본 라이브러리는 받은 message →
    DTO 변환 → `load_feature_bundles()` 호출의 *함수만* 제공.
  - 본 PR#10에서 `pyproject.toml` `import-linter` forbidden 계약에
    `kafka`/`aiokafka`/`confluent_kafka`/`faust` 추가 → 본 라이브러리 의존
    차단.
  - 도입 조건: 특정 provider가 진짜 초 단위 latency를 요구하는 증거.
    추측만으로 도입 금지.

## Sprint 5 운영 진입 직전 (kraddr-geo 패턴 미러)

- [ ] T-200 — **Batch DAG + 정합성 게이트** (kraddr-geo ADR-017 미러)
  - `ops.import_jobs`에 `load_batch_id UUID`, `parent_job_id UUID` 컬럼 추가
  - root job → child source loads → consistency_check gate → severity!=ERROR →
    mv_refresh (`strategy='swap'`)
  - phase별 중단/재개 (`PLAN_ONLY=1` preflight 포함)
- [ ] T-201 — **`ops.feature_consistency_reports` 도입**
  - 컬럼: `report_id UUID PK, batch_id UUID, started_at, finished_at,
    severity_max TEXT, cases JSONB, summary JSONB`
  - 케이스 F1~F8 (`python-krtour-map-spec.docx` B.18 참고)
  - Dagster 일 1회 검사 + admin `/admin/integrity` 페이지 연동
- [ ] T-202 — **pre-commit hook 정착**
  - `src/` 또는 `tests/` 수정 시 `docs/journal.md` 갱신 강제 (`BYPASS=1` 일회 우회)
  - `lint-imports` / `ruff format --check` / `mypy --strict`
- [ ] T-203 — **PR CI 워크플로**
  - `.github/workflows/ci.yml` — unit / integration / fixture_replay 분리 jobs
  - `.github/workflows/openapi.yml` — `--check` drift 검증 (디버그 UI 패키지)
  - `.github/workflows/lint.yml` — ruff/mypy/lint-imports
- [ ] T-204 — **GitHub branch protection 설정 가이드** (운영자용)
  - main: require PR + 1 approval + status checks + restrict force-push
  - ADR-021 §결정의 운영 정책을 별도 매뉴얼로

## 완료

- [x] T-000 — git v1 보존 + main orphan 재시작 (완료: 2026-05-24)
- [x] T-001 — v2 핵심 docs 작성 (완료: 2026-05-24)
  - AGENTS.md, README.md, SKILL.md, CLAUDE.md
  - .env.example, pyproject.toml, .gitignore, .gitattributes, LICENSE
  - docs/architecture.md
  - docs/decisions.md (ADR-001 ~ ADR-019)
  - docs/data-model.md, performance.md, test-strategy.md
  - docs/backend-package.md, agent-guide.md, dev-environment.md
  - docs/windows-reinstall-recovery.md
  - docs/feature-model.md, provider-contract.md, external-apis.md
- [x] T-001b — ADR-020 + 디버그 UI 별도 패키지로 분리 (완료: 2026-05-24)
  - decisions(ADR-020), architecture, backend-package, debug-ui-package(신규),
    AGENTS, SKILL, CLAUDE, README, pyproject(`[api]` 제거 + forbidden 계약 추가),
    .env.example, test-strategy 갱신
  - `packages/krtour-map-debug-ui/` pyproject + README skeleton
- [x] T-002 ~ T-011 — v1 docs를 v2 기준으로 일괄 이전 (완료: 2026-05-24, PR#2)
  - 14개 신규 docs (weather/files-rustfs/opening-hours/kraddr-base-types/
    address-geocoding/dagster-boundary/postgres-schema/debug-fixture-workflow/
    feature-db-initialization/tripmate-integration + provider ETL 10건)
- [x] T-001c — ADR-021/022/023 + PR-only workflow + `krtour.map` namespace +
      kraddr-base category 이전 (완료: 2026-05-24, PR#1)
  - AGENTS/SKILL/CLAUDE/architecture/agent-guide 일괄 갱신
  - `docs/category.md` 신설
  - import-linter 계약 placeholder
- [x] T-016 — `python-mois-api` 활용 feature 적재 4단계 lifecycle docs +
      ADR-024 canonical name 정정 (완료: 2026-05-24, PR#3)
  - `docs/mois-feature-etl.md` 신설 + 195 슬러그 카탈로그
  - 일괄 krmois→mois rename (`mois-license-feature-etl.md` 등)
- [x] T-015 — forest rename + category Tier 1~4 catalog + KNPS data.go.kr
      카탈로그 + 모든 ETL doc category 정보 audit (완료: 2026-05-25, PR#5)
  - `outdoor-feature-etl.md` → `forest-feature-etl.md` (git mv)
  - `docs/category.md` Tier 1~4 상세 테이블 (141건)
  - KNPS dataset 7건 카탈로그 + 옵션 A/B 비교 (옵션 B 권고)
- [x] T-017a — ADR-025 디버그 UI frontend = `maplibre-vworld-js` + ADR-025
      사용자 보강 (key 공유 + upstream 직접 PR) + ADR-026 TripMate 사용자 UI도
      maplibre-vworld 통일 (완료: 2026-05-25, PR#6 merged)
  - `docs/decisions.md` ADR-025 + ADR-026
  - `docs/debug-ui-package.md` §14 frontend 사양
  - `packages/krtour-map-debug-ui/frontend/` skeleton
  - `docs/tripmate-integration.md` §14.5 사용자 UI 지도 stack
  - `docs/external-apis.md` Kakao Maps SDK 미사용 처리
  - `docs/forest-feature-etl.md` §11.6 ADR-026 → ADR-027 후보 재번호
- [x] T-017b — ADR-025 2차 사용자 보강 (frontend 빌드 도구 Vite → **Next.js**
      정정) (완료: 2026-05-25, PR#11 merged)
  - `docs/decisions.md` ADR-025 §사용자 보강 2차 추가
  - `docs/debug-ui-package.md` §14 Next.js 전환 + 운영 옵션 3가지
  - `packages/krtour-map-debug-ui/frontend/` skeleton 일괄 Next.js 전환
    (package.json / .env.example / .gitignore / README / **next.config.js**
    신설), `VITE_*` → `NEXT_PUBLIC_*`
  - `docs/external-apis.md` / `docs/tripmate-integration.md` §14.5 / `docs/
    tasks.md` (T-100 재해석) 동기
- [x] T-013 — `CHANGELOG.md` 초기 엔트리 정리 (완료: 2026-05-25, PR#10 merged)
  - ADR-024~033 + T-101~103 + 명명 일치화 + 코드 변경 모두 inline
- [x] T-013b — 잔존 `krmois` → `mois` 명명 sweep (완료: 2026-05-25, PR#10
      merged) — 4건 정리 (forest §11.1 / mois-license §payload / journal 2건),
      ADR-024 narrative 등 역사 기록 컨텍스트는 유지
- [x] T-014a — Sprint 1 진입 계획 작성 (완료: 2026-05-25, PR#10 merged)
  - `docs/sprints/README.md` (Sprint 1~5 표 + 공통 진입 게이트)
  - `docs/sprints/SPRINT-1.md` (진입 조건 + 산출물 + DoD + Sprint 2 진입)
  - 실제 Sprint 1 진입 PR은 T-014 본체로 계속 pending (사용자 승인 필요)
- [x] T-017c — ADR-029 (proposed) + `@krtour/map-marker-react` skeleton
      (완료: 2026-05-25, PR#10 merged)
  - `docs/decisions.md` ADR-029 본문 (MIT, monorepo 위치, peer deps,
    drift gate, 배포 정책)
  - `packages/map-marker-react/` skeleton (`package.json` / `README.md` /
    `vite.config.ts` / `.gitignore`)
  - 실 코드는 T-017 본체 (Sprint 2)
- [x] T-018a — `python-knps-api` upstream scaffold 모니터링 + 본 라이브러리
      ADR-028 (proposed) 작성 (완료: 2026-05-25, PR#12 merged)
  - upstream `digitie/python-knps-api` `6e36990` scaffold 확인
  - `docs/decisions.md` ADR-028 본문
  - `docs/knps-feature-etl.md` 신설 (feature 적재 계약)
  - `docs/forest-feature-etl.md §11` 갱신 (외부 API 표면 + 채택 ✅ 표기)
  - `docs/provider-contract.md` / `docs/external-apis.md` / `pyproject.toml`
    동기
- [x] T-018b — upstream knps-api 측 PR — maki icon 정정 (완료: 2026-05-25,
      knps-api PR#1 open, https://github.com/digitie/python-knps-api/pull/1)
  - `docs/knps-feature-etl.md §4` shelter / barrier 정정 (본 라이브러리
    ADR-027 정합 + Maki 표준 호환)
  - 양방향 PR 워크플로 적용 사례 (ADR-028 §D)
- [x] T-012a — T-101~103 상세 분석을 `docs/performance.md`에 inline (완료:
      2026-05-25, PR#10 merged)
  - §9.3 T-101 (PostGIS MV), §9.4 T-103 (streaming ETL), §9.5 T-102
    (pg_prewarm) — 도입 조건, 부작용, ROI, 절차
- [x] T-012b — ADR-030/031/032/033 enforcement 코드 (완료: 2026-05-25, PR#10
      merged)
  - `pyproject.toml`: import-linter 차단 계약 (cachetools/async_lru/
    aiocache/diskcache + kafka/aiokafka/confluent_kafka/faust), coverage
    Sprint별 schedule 주석
  - `packages/krtour-map-debug-ui/scripts/export_openapi.py` skeleton
    (ADR-031, `--check` drift gate)

## 폐기 / 재해석

- ~~T-100~~ — "디버그 UI 별도 Next.js 패키지 분리" — **부분 재해석** (PR#11
  2026-05-25):
  - 원래 의도 = Next.js로 별도 패키지화. 실제 구현 = Python 패키지로 분리
    (T-001b, ADR-020) + frontend는 그 안의 `frontend/` 하위에 **Next.js**
    (ADR-025 2차 보강).
  - 즉 "Next.js 미채택"이라고 한 PR#7의 기록은 잘못됨 — ADR-025 2차 보강
    으로 Next.js 채택 확정.

## 우선순위 가이드

- **즉시 (검토 + merge)**: 본 PR#48 (worktree rename + tasks.md sweep) +
  upstream knps-api PR#1 (maki icon 정정)
- **다음 (Sprint 2 잔여 → Sprint 3 진입)**:
  - 디버그 UI ETL preview live 매트릭스 확장 — datagokr 1 + opinet 2 +
    krex 4 + kma_weather_alerts 1 = 8 dataset live loader 등록 (현재 KMA 3만)
  - `maplibre-vworld-js v0.1.0` 정합 — frontend `package.json` 의존 핀 정정
    (`^1.0.0`→git URL `#v0.1.0`, zod `^3`→`^4.4.3`) + docs 버전 갱신 (T-019 관련)
  - KMA `mid_forecast_to_weather_values` (중기예보 텍스트 + AM/PM split)
  - `/features/*` 라우터 + `infra/feature_repo.py` raw SQL + frontend 지도 화면
  - Sprint 2 §2.1 끝물 visitkorea TourAPI enrichment
    (`festival_to_enrichment_links`)
- **Sprint 진행 순서** (ADR-034):
  - Sprint 2 = ① 축제 ✅ → ② 날씨 ✅(mid 잔여) → ③ 유가 ✅ → ④ 휴게소 ✅
    + 디버그 UI 라우터 ✅ (`docs/sprints/SPRINT-2.md`)
  - Sprint 3 = ⑤ 국립공원/트래킹 → ⑥ 국가유산 + 정합성 Phase 1 (F1~F3)
    + ADR-036 maplibre-vworld-js v0.1.0 분리 (`SPRINT-3.md`)
  - Sprint 4 = ⑦ MOIS bulk 4단계 + dedup queue 운영 (`SPRINT-4.md`)
  - Sprint 5 = ⑧ 휴양림/수목원 → ⑨ 박물관/미술관 + Phase 2 F4~F8 + Dagster
    게이트 + 운영 진입 (`SPRINT-5.md`)
- **백그라운드**: T-019 (TripMate `apps/web` 측 Kakao → maplibre-vworld
  교체 모니터링) — upstream `digitie/maplibre-vworld-js` **v0.1.0 릴리스됨**
  (npm 미게시, git URL+tag 핀).
- **장기**: 운영 진입 후 v2.1 검토 (T-101 MV / T-102 pg_prewarm / T-103
  streaming / ADR-044+ 신규 provider)

## ADR 번호 가이드 (현재)

- **accepted (text on main)**: ADR-001 ~ ADR-043 (전부). PR#16에서 027~034,
  PR#33에서 035~043 일괄 accepted 전환. 029는 ADR-043으로 supersede.
- **다음 후보 번호 = ADR-044**:
  - **ADR-044+** — 신규 provider 추가 절차 표준 (체크리스트)
  - 후속 `@krtour/map-marker-react` npm 게시 자동화 ADR (현재 ADR-043 보류)
  - (필요 시) ADR — `core.feature_consistency_reports` Phase 2 알림 sink
  - (필요 시) ADR — Sprint 3 SHP/GeoJSON parsing 위치 결정 (`krtour.map.
    providers.knps` vs upstream `[geo]` extra)
  - (필요 시) ADR — MV 도입 (T-101 Sprint 5 시범 결과 후)
  - (필요 시) ADR — pg_prewarm 운영 정책 (T-102)

## 머지 history (참조)

| PR | branch | 머지 일자 | 핵심 |
|----|--------|----------|------|
| #1 | `chore/pr-workflow-namespace-rename-category-migration` | 2026-05-24 | ADR-021/022/023 |
| #2 | `docs/v1-to-v2-feature-ports` | 2026-05-24 | T-002~T-011 (14 docs) |
| #3 | `feat/mois-feature-etl` | 2026-05-24 | ADR-024 + mois-feature-etl.md |
| #4 | (merged via #3 lineage) | 2026-05-24 | 동일 |
| #5 | `feat/forest-knps-category` | 2026-05-25 | T-015 (forest rename + KNPS 카탈로그 + category Tier 1~4) |
| #6 | `feat/debug-ui-maplibre-vworld` | 2026-05-25 | ADR-025 + ADR-025 사용자 보강 + ADR-026 |
| #7 | `chore/tasks-md-update` | 2026-05-25 | tasks.md 백로그 |
| #8 | `docs/adr-030-031-032-033-proposed` | 2026-05-25 | ADR-030/031/032/033 proposed |
| #9 | `docs/adr-027-forest-category-expansion` | 2026-05-25 | ADR-027 proposed |
| #10 | `docs/pr10-t012-t018-codify` | 2026-05-25 | ADR-029 + T-013/14a/17c/12a/12b + 명명 sweep + 코딩 |
| #11 | `docs/pr11-debug-ui-nextjs` | 2026-05-25 | ADR-025 2차 보강 (Vite → Next.js) |
| #12 | `docs/pr12-knps-api-integration` | 2026-05-25 | ADR-028 + knps-feature-etl.md |
| #13 | `chore/tasks-md-pr12-merged-update` | 2026-05-25 | tasks.md 백로그 갱신 (PR#12 머지 후) |
| #14 | `docs/pr14-impl-order-sprint-plans` | 2026-05-25 | ADR-034 provider 9단계 + Sprint 2~5 plan |
| #15 | `docs/pr15-governance-sweep` | 2026-05-25 | governance docs sweep + DO NOT bug fix 3건 |
| #16 | `feat/sprint1-entry-adr-accepted` | 2026-05-25 | T-014 Sprint 1 진입 — ADR 027~034 일괄 accepted + fail_under=50 |
| #17 | `feat/sprint1-pr17-scaffolding` | 2026-05-25 | `src/krtour/map/` PEP 420 scaffolding + `settings.py` + smoke |
| #18 | `feat/sprint1-pr18-category-migration` | 2026-05-25 | `category/` 144건 (kraddr-base 이전 + ADR-027 3건) + 16 tests |
| #19 | `feat/sprint1-pr19-dto-foundation` | 2026-05-25 | `dto/` Feature + 5 detail + NOTICE_TYPES 14 (ADR-027) + AreaDetail hazard_zone + KST + 27 tests |
| #20 | `feat/sprint1-pr20-core-exceptions-id` | 2026-05-25 | `core/` exceptions 7종 + `make_feature_id` (ADR-009) + 42 tests |
| #21 | `feat/sprint1-pr21-infra-skeleton` | 2026-05-25 | `infra/crs.py` + `infra/db.py` + testcontainers PostGIS conftest |
| #22 | `feat/sprint1-pr22-ci-import-linter` | 2026-05-25 | CI workflows + import-linter 4 계약 + ADR-002 위반 해소 (dto/_time.py) |
| #23 | `docs/pr23-review-report` | 2026-05-25 | `docs/reports/pr-1-21-review.md` 종합 리뷰 |
| #24 | `fix/pr24-dto-strictness-p0` | 2026-05-25 | review P0-1/2/3 — detail dict 거부 + datetime aware + category 정규식 |
| #25 | `docs/pr25-knps-keyless-sync` | 2026-05-25 | python-knps-api keyless(`06da125f`) 반영 + ADR-028 amendment §H |
| #26 | `feat/pr26-source-record-bundle-dto` | 2026-05-25 | review P0-4 — ID helper 2종 + SourceRecord/Link/FeatureBundle DTO |
| #27 | `docs/pr27-p1-docs-drift-sweep` | 2026-05-25 | review P1 docs drift sweep |
| #28 | `feat/pr28-infra-models-alembic` | 2026-05-26 | `infra/models.py` + Alembic 첫 2 revision (0001/0002) + 통합 테스트 6 |
| #29 | `feat/pr29-core-scoring-providers` | 2026-05-26 | `core/scoring.py`(ADR-016) + `core/providers.py` (canonical 18종) |
| #30~31 | `docs/pr30-31-codegraph-worktree` | 2026-05-27 | agent worktree + codegraph 룰 docs + MCP 등록 |
| #32~33 | `docs/pr32-33-adr-035-043` | 2026-05-27 | 거버넌스 보강 + ADR-035~043 proposed→accepted |
| #34 | `feat/pr34-datagokr-festivals` | 2026-05-27 | Sprint 2 §2.1 datagokr 축제 1차 source (ADR-042) |
| #35 | `feat/pr35-debug-ui-routers` | 2026-05-27 | 디버그 UI `create_app` + health/version + openapi drift gate |
| #36 | `feat/pr36-frontend-skeleton` | 2026-05-27 | Next.js 15 frontend skeleton + TanStack/Zustand (ADR-037) |
| #37 | `feat/pr37-kraddr-base-absorb` | 2026-05-28 | ADR-041 — Address DTO 보강 + `core/address.py` |
| #38 | `feat/pr38-kma-short-forecast` | 2026-05-28 | `WeatherValue` DTO + 3 enum + KMA 단기예보 1차 |
| #39 | `feat/pr39-kma-nowcast` | 2026-05-28 | KMA 초단기실황 + `core/weather.py` pure 헬퍼 5종 |
| #40 | `docs/pr40-provider-status-sweep` | 2026-05-28 | `python-*-api` 라이브러리 status sweep |
| #41 | `feat/pr41-kma-ultra-short-forecast` | 2026-05-28 | KMA 초단기예보 (getUltraSrtFcst) + LGT |
| #42 | `feat/pr42-pricevalue-opinet` | 2026-05-28 | `PriceValue` DTO + opinet 가격 1차 |
| #43 | `feat/pr43-opinet-stations` | 2026-05-28 | opinet `stations_to_bundles` (gas station Feature) |
| #44 | `feat/pr44-etl-preview-router` | 2026-05-28 | 디버그 UI ETL preview 라우터 (fixture dry-run) |
| #45 | `feat/pr45-krex-multi-kind` | 2026-05-28 | Sprint 2 §2.4 krex 휴게소 4 dataset multi-kind |
| #46 | `feat/pr46-kma-weather-alerts` | 2026-05-28 | KMA weather_alerts → notice + krex category fix + ETL 11 dataset |
| #47 | `feat/pr47-etl-live-source` | 2026-05-28 | ETL preview `?source=live` (KMA 3) + 8 provider key + CI red 3종 해소 |
| #48 | `docs/pr48-worktree-rename-tasks-sweep` | 2026-05-28 | worktree `geo-*`→`krtour-map-*` rename + tasks.md 최신화 |
| #49 | `feat/pr49-maplibre-vworld-v010` | 2026-05-28 | maplibre-vworld v0.1.0 의존 핀 정합 (git URL+tag, zod ^4.4.3, ADR-036 amendment) |
| **#50** | `docs/pr50-sprint-task-resume-consolidation` | **open** | Sprint/task/resume 일관성 재정비 (현 상태 단일화) |
| knps-api #1 | `docs/knps-feature-maki-icons` | **open** | maki icon 정정 (shelter / barrier) |
