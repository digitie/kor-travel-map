# CHANGELOG

본 라이브러리의 사용자 가시 변경을 기록한다. [Keep a Changelog](https://keepachangelog.com)
형식을 따른다.

## [Unreleased]

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
