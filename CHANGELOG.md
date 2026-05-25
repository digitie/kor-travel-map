# CHANGELOG

본 라이브러리의 사용자 가시 변경을 기록한다. [Keep a Changelog](https://keepachangelog.com)
형식을 따른다.

## [Unreleased]

### Sprint 1 scaffolding (2026-05-25, PR#17+)

- **PR#25 — KNPS keyless sync (python-knps-api PR#3+#4 반영)**:
  upstream knps-api commit `06da125f` 변경 본 라이브러리 docs/pyproject 일괄
  반영. **ADR-028 amendment §H** 신설 (keyless + file-only).
  - `KNPS_SERVICE_KEY` / `DATA_GO_KR_SERVICE_KEY` 사용 안 함 (인증 제거).
  - 14 dataset 모두 `kind="file_dataset"`. 신규 4건 (`knps_linear_facilities`,
    `knps_protected_areas`, `knps_basic_statistics`, `knps_lod_table_catalog`),
    제거 4건 (`knps_access_restrictions`, `knps_fire_alerts`,
    `knps_recommended_courses`, `knps_park_photos`).
  - 제거된 notice 2종 (`access_restriction`/`fire_alert`)은 산림청/소방청
    별도 source로 이전 (후속 ADR).
  - 공개 API 정정: `ApiEndpoint`/`Page`/`api_endpoint`/`raw_endpoint` 삭제,
    `FileArtifact`/`FileMember`/`CsvPreview`/`CsvPreviewRow` 신규.
  - 변경 docs: `decisions.md` (ADR-028 §H amendment) / `knps-feature-etl.md` /
    `forest-feature-etl.md §11` / `external-apis.md §3.8.1` /
    `provider-contract.md §3`. pyproject git URL 핀 (`@06da125f`) 주석.
  - **코드 변경 0** — docs/pyproject 주석만. 141 pytest passed 유지 (이전 PR).
- **PR#24 — DTO strictness P0 (Sprint 2 진입 전 차단)**:
  Review report (`docs/reports/pr-1-21-review.md`, PR#23 DRAFT) P0-1/2/3 해소.
  - `Feature.detail` `mode="before"` dict 거부 (Pydantic union dict coercion
    차단, ADR-018 진짜 강제)
  - 모든 DTO datetime aware validator 일관 적용:
    - `Feature.created_at/updated_at/deleted_at` (이전 PR#19)
    - `NoticeDetail.valid_start_time/valid_end_time` (신규)
    - `RawDataRef.fetched_at` (신규)
  - `dto/_time.py`에 `check_aware_datetime()` 공용 helper 추가 + 모든 DTO에
    적용. ADR-019 해석 명시: "aware면 OK, naive 거부" (KST 변환은 provider 책임)
  - `Feature.category` `^\d{8}$` 정규식 validator (ADR-023 PlaceCategoryCode
    8자리). strict known-code는 후속 PR (transitional)
  - 신규 tests: `test_dto_time.py` (11 case) + dict reject 3건 split +
    category 8자리 2건 + notice datetime 3건. 141 passed total.
- **PR#22 — CI workflows + import-linter 활성화 (Sprint 1 scaffolding 종료)**:
  - `.github/workflows/ci.yml` — pytest unit + integration (testcontainers
    PostGIS, ADR-007) + coverage XML, Python 3.11/3.12/3.13 matrix +
    `concurrency` group으로 이전 run 자동 cancel.
  - `.github/workflows/lint.yml` — ruff check + mypy --strict
    (`krtour.map` 전체) + import-linter (4 계약).
  - `.github/workflows/openapi.yml` — ADR-031 drift gate. Sprint 1은
    `continue-on-error: true` (앱 모듈 미존재) — Sprint 2 첫 라우터 PR
    에서 제거.
  - `tests/lint/test_import_linter.py` — pyproject.toml의 4 계약 wrap
    (subprocess로 `lint-imports` 실행). 미설치 시 skip.
  - `pyproject.toml`: `include_external_packages = true` (외부 forbidden
    검증 활성화) + `layers`에서 `krtour.map.cli` 제거 (모듈 미존재).
  - **ADR-002 위반 1건 실 해소** — `KST`/`kst_now` 정의를
    `core/types.py` → `dto/_time.py`로 이전 (dto/feature.py가 core를
    역참조하던 위반 해소). 공개 API `from krtour.map.core import kst_now`는
    그대로 (core/types.py shim).
  - `tests/unit/test_dto_*.py` + `test_category.py` —
    `pytest.raises(Exception)` → 구체 예외 type (B017/PT011 해소).
  - **125 passed, 10 skipped** (전체) + ruff/mypy/import-linter all green.
- **PR#21 — `src/krtour/map/infra/` skeleton (crs + db + testcontainers)**:
  - `src/krtour/map/infra/crs.py` — `pyproj.Transformer` singleton
    (`@functools.cache`, ADR-030 narrow 예외): `transformer_4326_to_5179` /
    `transformer_5179_to_4326` + `project_to_5179` / `project_to_4326`
    + `EPSG_WGS84` / `EPSG_UTM_K`. `always_xy=True` 강제.
  - `src/krtour/map/infra/db.py` — `make_async_engine` (SQLAlchemy 2
    AsyncEngine + asyncpg) + `make_async_session_factory` +
    `normalize_async_dsn` (psycopg2/psycopg/postgres → asyncpg 통일).
    `SecretStr` 자동 처리.
  - `tests/integration/__init__.py` + `tests/integration/conftest.py` —
    testcontainers PostGIS 베이스 (`pg_container` session-scope `postgis/
    postgis:16-3.5-alpine`, `pg_engine` 4 schema + 3 extension 자동
    생성, `pg_session` per-test rollback). Docker/testcontainers 미설치
    시 자동 `pytest.skip`.
  - `tests/integration/test_pg_smoke.py` — postgis/pg_trgm/pgcrypto
    `x_extension` 격리 확인 (ADR-008) + 4 schema 존재 + ST_Transform
    4326↔5179이 pyproj와 1m 이내 일치.
  - `tests/unit/test_crs.py` 13 case + `tests/unit/test_db.py` 12 case
    (asyncpg 미설치 환경 4건 자동 skip).
  - `pyproject.toml`: `pyproj>=3.6` 본 의존 추가.
  - **124 passed, 10 skipped** (전체 suite).
- **PR#20 — `src/krtour/map/core/` 예외 계층 + ADR-009 `make_feature_id`**:
  - `src/krtour/map/core/exceptions.py` — `KrtourMapError` 베이스 + 7 도메인
    예외 (`ValidationError`/`FeatureNotFoundError`/`SourceRecordNotFoundError`/
    `DuplicateFeatureError`/`ImportJobConflictError`/`ProviderError`/
    `FileStoreError`). HTTP 매핑은 `docs/debug-ui-package.md §6.4`.
  - `src/krtour/map/core/ids.py` — `make_feature_id(*, bjd_code, kind,
    category, source_type, source_natural_key, content_hash=None)`. 포맷
    `f_{bjd or 'global'}_{kind[0]}_{sha1[:16]}` (ADR-009 SPEC V8 D-2).
    `usedforsecurity=False` 명시. `|` 구분자 / 빈 문자열 검증.
  - dto 의존 회피 — `kind: str` 타입 (PR#19 `FeatureKind` StrEnum은 str
    서브클래스이므로 그대로 호환, 호출 측 코드 변경 0).
  - `core/__init__.py` — PR#19(`KST`/`kst_now`) + PR#20(exceptions 7 + ids
    2) 통합 export, 총 12 공개 식별자.
  - `tests/unit/test_exceptions.py` 7 case + `tests/unit/test_ids.py` 35
    case (parametrize 포함). **72 passed** (전체 suite).
- **PR#19 — `src/krtour/map/dto/` Feature + 5 detail + ADR-027 적용**:
  - `core/types.py` — `KST` / `kst_now()` (ADR-019)
  - `dto/_enums.py` — FeatureKind 7 / FeatureStatus 6 / SourceRole 8
  - `dto/coordinate.py` — Coordinate (Korea bounds, frozen)
  - `dto/address.py` — Address basic
  - `dto/urls.py` — FeatureUrls + RawDataRef
  - `dto/opening_hours.py` — OpeningTime/Period/SpecialDay/FeatureOpeningHours
  - `dto/place.py`/`event.py`/`route.py` — Detail 모델 + ROUTE_TYPES 9종 +
    normalize_route_type
  - **`dto/notice.py`** — NoticeDetail + **NOTICE_TYPES 14건** (ADR-027
    `access_restriction`/`fire_alert` 포함) + normalize_notice_type
  - **`dto/area.py`** — AreaDetail + AREA_KINDS 12종 (ADR-027 `hazard_zone`)
  - `dto/feature.py` — Feature (ADR-018 detail discriminator, ADR-019 KST
    aware enforcement, marker_color P-01~P-16 regex)
  - `dto/__init__.py` — 38 공개 식별자 re-export
  - `tests/unit/test_dto_{notice,area,feature}.py` (27 cases)
  - **62 pytest passed** (전체 test suite)
- **PR#18 — `src/krtour/map/category/` 144건 (ADR-023 이전 + ADR-027)**:
  - `_definitions.py` (~2110줄, kraddr-base 사본 + ADR-027 패치)
  - ADR-027 신규 3건: `LODGING_MOUNTAIN_SHELTER` (Tier 2) +
    `LODGING_MOUNTAIN_SHELTER_KNPS` / `_KFS` (Tier 3) + maki = `shelter`
  - `PLACE_CATEGORY_TIER2_NAMES_BY_TIER1["03"]["08"] = "대피소·산장"`
  - `@cache` on `get_category` (ADR-030 narrow 예외, immutable 카탈로그)
  - `category/__init__.py` re-export 14 식별자
  - `tests/unit/test_category.py` (16 cases) — 144 총건/depth/Tier1/
    ADR-027/maki/helper/cache 검증. **30 passed** (전체 test suite)
  - `docs/category.md` §4.3 depth 통계 정정 (원본 Tier 2/4 swap 오류)
- **PR#17 — `src/krtour/map/` PEP 420 scaffolding**:
  - `src/krtour/map/__init__.py` (`__version__ = "0.2.0-dev"`)
  - `src/krtour/map/py.typed` (PEP 561)
  - `src/krtour/map/settings.py` — `KrtourMapSettings(BaseSettings)`
    (pg_dsn / object_store_* / log_*)
  - `src/krtour/map/{category,dto,core,infra,providers,client}/__init__.py`
    (placeholder, 후속 PR에서 채움)
  - `pyproject.toml`: `pydantic-settings>=2.4` 의존 추가
  - `tests/lint/test_no_namespace_init.py` — ADR-022 PEP 420 enforcement
  - `tests/unit/test_smoke_import.py` — `krtour.map` + `KrtourMapSettings`
    smoke (5 cases)

### Sprint 1 진입 (2026-05-25, PR#16)

- **T-014 — 코드 작성 단계 진입**: 사용자 승인. Sprint 1 = **active**.
- **ADR 8건 일괄 proposed → accepted 전환** (ADR-027/028/029/030/031/032/
  033/034). 모두 main에 text on accepted 상태.
- `pyproject.toml` `[tool.coverage.report] fail_under` 0 → **50** (ADR-032
  Sprint 1 bar).
- `docs/sprints/SPRINT-1.md` 상태 → active. SPRINT-2~5.md 상태 → accepted
  (시기 대기).
- 후속 Sprint 1 scaffolding PR sequence (PR#17~#23): `src/krtour/map/`
  PEP 420 + `category/` 144건 + `dto/` (NOTICE_TYPES 14건 + AreaDetail.
  area_kind hazard_zone) + `core/` + `infra/` + CI workflows + 첫 통합
  테스트.

### 결정 (2026-05-25 — PR#6 ~ PR#10 시기)

- **NEW (accepted)**: ADR-024 — canonical provider name `python-krmois-api`
  → `python-mois-api` (PR#3). v1 내부 alias였던 `krmois`/`pykrmois`는 legacy
  alias로만 보존. `docs/krmois-license-feature-etl.md` → `docs/mois-license-feature-etl.md`
  (git mv).
- **NEW (accepted)**: ADR-025 — 디버그 UI frontend는 `maplibre-vworld-js` 채택
  (React + Vite + TS + `maplibre-vworld` + `maplibre-gl` + `zod`). Kakao
  Maps SDK 미사용. `packages/krtour-map-debug-ui/frontend/` skeleton.
  **사용자 보강 (2026-05-25)**: VWorld key는 `KRADDR_GEO_VWORLD_API_KEY`
  공유 / maplibre-vworld-js upstream 직접 PR로 적극 수정.
- **NEW (accepted)**: ADR-026 — TripMate 사용자 UI도 `maplibre-vworld` 채택
  (SPEC V8 v8_3 Kakao Maps 섹션 superseded). 두 UI 단일 stack.
- **NEW (proposed)**: ADR-027 — forest 카테고리/notice_type 확장 (PR#9):
  `LODGING_MOUNTAIN_SHELTER` Tier 2 신설 + `area_kind=hazard_zone` +
  generic `notice_type=access_restriction`/`fire_alert`. 사용자 결정으로
  `forest_` prefix 없는 generic 명명. WEATHER_MOUNTAIN_STATION /
  NATURE_ECOLOGY / Tier 1 `08 SAFETY`는 거부.
- **NEW (proposed)**: ADR-029 — `@krtour/map-marker-react` npm 패키지 추출
  (본 PR#10): 디버그 UI + TripMate 사용자 UI 공통 마커/카테고리 매핑.
  MIT 라이선스 (TripMate proprietary 호환). monorepo
  `packages/map-marker-react/`.
- **NEW (proposed)**: ADR-030 — 라이브러리 in-memory 캐시 금지 (PR#8).
  `functools.cache` 한정 narrow 예외 (PlaceCategoryCode 카탈로그,
  `pyproj.Transformer` singleton). `import-linter` 계약으로 `cachetools` /
  `async_lru` / `aiocache` / `diskcache` 차단.
- **NEW (proposed)**: ADR-031 — 디버그 패키지 OpenAPI export 첫 FastAPI
  라우터 등장 PR부터 즉시 활성화 (PR#8). `openapi.json` 저장소 커밋 +
  CI `--check` drift gate.
- **NEW (proposed, 시기 의존)**: ADR-032 — Coverage 단계적 상향 일정
  (Sprint 1 50% → Sprint 4 80%, PR#8). `dto/`는 Sprint 2부터 100% branch
  항상 강제. T-014 시점에 accepted 전환.
- **NEW (proposed, 시기 의존)**: ADR-033 — `feature_consistency_reports`
  두 단계 분할 도입 (PR#8). Phase 1 (Sprint 3~4) = 스키마 + F1~F3 critical
  (orphan source / detail 누락 / CRS drift, severity=ERROR, 게이트 미적용).
  Phase 2 (Sprint 5) = F4~F8 + Dagster 게이트 + swap 차단. T-014 시점에
  accepted 전환.

### 문서 확장 (2026-05-25)

- `docs/performance.md §9.3/§9.4/§9.5` — T-101 (PostGIS MV) / T-103
  (streaming ETL) / T-102 (pg_prewarm) 상세 분석 inline. 도입 조건, 부작용,
  ROI 평가.
- `docs/sprints/SPRINT-1.md` — 코드 작성 단계 진입 Sprint 1 계획 초안
  (T-014 후속).
- `docs/forest-feature-etl.md §11` — KNPS data.go.kr 통합 plan 7 dataset +
  옵션 A/B/C 비교. PR#5에서 outdoor→forest rename + KNPS dataset 카탈로그
  + 옵션 B (별도 `python-knps-api`) 권고. PR#9 (ADR-027)에서 카테고리/
  notice_type 결정 확정.
- `docs/category.md` §4 — Tier 1~4 전체 141건 카탈로그 (트리/표/maki icon
  분포). ADR-027 적용 후 144건 (`03.08 LODGING_MOUNTAIN_SHELTER` 3건 추가).
- `docs/notice-feature-etl.md` §3/§7 — NOTICE_TYPES 14건 (ADR-027의
  `access_restriction` / `fire_alert` 추가). 마커 스타일 매핑.
- `docs/tripmate-integration.md` §14.5 — TripMate 사용자 UI 지도 stack
  (ADR-026).
- `packages/krtour-map-debug-ui/frontend/` — React + Vite + maplibre-vworld
  skeleton (`package.json` / `.env.example` / `.gitignore` / `README.md`).

### 잔존 명명 일치화 (본 PR#10)

- `docs/forest-feature-etl.md:173` 컨벤션 예시: `python-krmois-api` →
  `python-mois-api`.
- `docs/mois-license-feature-etl.md:115` 예시 payload: `krmois_admin_address`
  → `mois_admin_address`.
- `docs/journal.md:151` 컨벤션 예시: `krmois/krheritage/krforest` →
  `mois/krheritage/krforest`.
- `docs/journal.md:475` 옛 provider 목록: `krmois` → `mois (구 krmois)`.
- ADR-024 migration 본문 / journal ADR-024 narrative / mois-feature-etl.md
  의 v1→v2 마이그레이션 표 등 *역사 기록 컨텍스트*의 `krmois` 표기는 그대로
  유지 (rename 사건 자체를 기록).

### 코드 (본 PR#10)

- `pyproject.toml` — ADR-030 `import-linter` forbidden 계약에
  `cachetools` / `async_lru` / `aiocache` / `diskcache` 추가. ADR-032
  `[tool.coverage.report] fail_under = 50` Sprint 1 bar 설정.
- `packages/krtour-map-debug-ui/scripts/export_openapi.py` — ADR-031
  CLI skeleton (실행은 코드 작성 단계에서).
- `packages/map-marker-react/` — ADR-029 skeleton (`package.json` /
  `README.md` / `.gitignore` / `vite.config.ts`).

### 변경 / 재설계 (v2 design — 초기)

- **NEW**: ADR-021 — main에 직접 push 금지. 모든 변경은 feature branch + PR
  (`gh pr create`). 운영 GitHub branch protection으로 강제.
  `docs/agent-guide.md` §7.5에 PR 워크플로/commit format/PR 본문 표준 박힘.

- **BREAKING**: ADR-022 — Python import 경로 변경.
  - `from krtour_map import ...` → `from krtour.map import ...`
  - `from krtour_map_debug_ui import ...` → `from krtour.map_debug_ui import ...`
  - `src/krtour_map/` → `src/krtour/map/`
  - `src/krtour_map_debug_ui/` → `src/krtour/map_debug_ui/` (디버그 UI 패키지)
  - `krtour` PEP 420 implicit namespace (no `src/krtour/__init__.py`).
  - PyPI distribution 이름(`python-krtour-map`), CLI(`krtour-map`),
    env prefix(`KRTOUR_MAP_*`), DB 이름(`krtour_map`)는 모두 유지.
  - `pyproject.toml` `packages.find` + `namespaces=true` + `import-linter`
    layers 갱신.

- **NEW**: ADR-023 — `python-kraddr-base`의 category 모듈
  (`kraddr.base.categories`, ~2,072줄, 141 enum)을 본 저장소
  `krtour.map.category`로 이전.
  - 공개 식별자 전부 유지 (`PlaceCategory`, `PlaceCategoryCode`, `get_category`,
    `iter_categories`, `mapbox_maki_icon_for_category` 등).
  - 의존 계층 최하단 (`category → dto → core → infra → providers → client → cli`).
  - 라이선스 GPL-3.0-or-later 호환. 실제 코드 이전은 코드 작성 단계에서 별도 PR.
  - 사양: `docs/category.md`.

- **BREAKING**: 디버그 REST API/UI를 별도 Python 패키지 `krtour-map-debug-ui`
  (`packages/krtour-map-debug-ui/`)로 분리 (ADR-020). 메인 라이브러리
  `python-krtour-map`에서 FastAPI/Uvicorn 의존성 제거. `[api]` extra 폐기.
  `krtour.map.api` 모듈 없음. ADR-005의 위치 부분은 ADR-020으로 superseded
  (인증 없음 + 내부망 전용 정책은 유지).
  - 디버그 UI 실행: `uvicorn krtour.map_debug_ui.app:app --host 127.0.0.1 --port 8600`
  - 환경변수 prefix: `KRTOUR_MAP_DEBUG_UI_*`
  - `import-linter`에 `메인 패키지는 fastapi/uvicorn/starlette import 금지`
    계약 추가.


- **BREAKING**: v1 코드는 `v1` 브랜치로 이동. main은 orphan으로 v2 사양 시작.
  v1 산출물은 `git checkout v1` 또는 `python-krtour-map-spec.docx` (저장소 루트
  약 80쪽) 참고.
- **BREAKING**: TripMate ↔ 라이브러리 연계는 **함수 직접 호출**로 일원화
  (ADR-003). REST 사용 안 함.
- **BREAKING**: 의존 스택 확정 — PostgreSQL 16 + PostGIS 3.5 + SQLAlchemy 2 async
  + GeoAlchemy2 + GeoPandas + Pydantic v2 + asyncpg + psycopg[binary,pool]>=3.2
  (ADR-007).
- **BREAKING**: schema 분리 — `feature`, `provider_sync`, `ops`, `x_extension`
  (ADR-008).
- **BREAKING**: `Feature.detail`은 자유 dict 금지, `DETAIL_MODELS` 분기 강제
  (ADR-018).
- **BREAKING**: 모든 datetime은 timezone aware (KST 기본). naive 입력은
  ValidationError (ADR-019).
- **NEW**: 디버그 REST API (옵션, 인증 없음, 내부망 전용, ADR-005).
- **NEW**: 의존 계층 강제 (`dto → core → infra → providers → client → api/cli`)
  + import-linter CI (ADR-002).
- **NEW**: 작업 큐 영속화 (`ops.import_jobs` + advisory lock + SKIP LOCKED,
  ADR-011).
- **NEW**: bulk insert 30k 안전 마진 룰 + `psycopg.copy_*` 우선 (ADR-013).
- **NEW**: 공간 쿼리 인덱스 최적화 — `coord_5179`(meter) 컬럼 + CTE 1회 변환
  강제 (ADR-012).
- **NEW**: 4단계 테스트 (unit/integration/e2e/fixture) + Coverage 목표 + EXPLAIN
  검증 의무화 (ADR-014).
- **NEW**: 객체 저장소는 S3 호환만 가정, RustFS 1차, MinIO/Ceph/R2 swap 가능
  (ADR-015).
- **NEW**: Record Linkage 가중치 0.45/0.35/0.20 + 임계값 0.85/0.65 박음
  (ADR-016).
- **NEW**: 보관 정책 박음 — place 무기한, event +20y, notice +1y, weather +30d
  (ADR-017).

### 문서

- 새 governance 문서 작성: `AGENTS.md`, `README.md`, `SKILL.md`, `CLAUDE.md`.
- 새 design 문서 작성:
  - `docs/architecture.md`
  - `docs/decisions.md` (ADR-001 ~ ADR-019)
  - `docs/data-model.md`
  - `docs/performance.md`
  - `docs/test-strategy.md`
  - `docs/backend-package.md`
  - `docs/agent-guide.md`
  - `docs/dev-environment.md`
  - `docs/windows-reinstall-recovery.md`
  - `docs/feature-model.md`
  - `docs/provider-contract.md`
  - `docs/external-apis.md`
  - `docs/tasks.md`, `docs/resume.md`, `docs/journal.md`
- `pyproject.toml`에 4단계 스택 의존성 + import-linter 계약 박음.

### 마이그레이션 가이드 (v1 → v2)

v1 사용자는 다음 흐름으로 마이그레이션한다 (코드 작성 단계 진입 후):

1. v1 데이터 dump (현재는 미정 — 코드 작성 단계에서 정의)
2. v2 schema (`feature/provider_sync/ops/x_extension`) 생성
3. detail JSONB 키 매핑 (v1 ↔ v2 차이 — 별도 변환 스크립트)
4. `feature_id` 재계산 (`make_feature_id`의 `bjd_code` 인자가 v2에서 명시적)
5. 보관 정책 적용 → 만료 row 삭제

상세 가이드는 코드 작성 단계 진입 시 별도 문서로 작성.

---

## v1 (역사 보존)

v1은 `v1` 브랜치에 보존. 자세한 v1 변경 이력은 그쪽 `git log`로 확인:

```bash
git checkout v1
git log --oneline
```

v1 마지막 commit: `08205ab Preserve v1 work: docs revamp, providers, debug UI,
spec docx` (2026-05-24).
