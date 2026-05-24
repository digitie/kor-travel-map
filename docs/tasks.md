# tasks.md — 백로그

이 문서는 작업 백로그다. 우선순위 순. 각 작업은 `T-NNN` 번호로 식별한다.

## 진행 중

- (없음 — PR#6 검토 대기)

## 다음 (우선순위 순)

- [ ] T-012 — ADR-020+ 후속 결정 작성 (일부 완료 → proposed)
  - **ADR-030 (proposed)** — 라이브러리 in-memory 캐시 금지 (`functools.cache`
    한정 예외) + `import-linter` 계약. 사용자 검토 → accepted 전환.
  - **ADR-031 (proposed)** — 디버그 패키지 OpenAPI export 정책 (첫 라우터부터
    활성화). 사용자 검토 → accepted 전환.
  - **ADR-032 (proposed, 시기 의존)** — Coverage 단계적 상향 일정 (Sprint 1
    → Sprint 5). T-014에 묶어 Sprint 일정 확정 후 accepted 전환.
  - **ADR-033 (proposed, 시기 의존)** — `feature_consistency_reports` 단계적
    도입 (Phase 1 = Sprint 3~4 F1~F3, Phase 2 = Sprint 5 F4~F8 + 게이트).
    T-014에 묶어 accepted 전환.
- [ ] T-013 — `CHANGELOG.md` 초기 엔트리 정리 (현 v2 design 완료 시점)
- [ ] T-014 — 코드 작성 단계 진입 검토
  - 모든 문서 검토 완료
  - 사용자 승인
  - Sprint 계획 (`SPRINT-1.md` 또는 `docs/sprints/`)
- [ ] T-017 — **공통 maki marker / category 매핑 npm 패키지 추출** (ADR-026
      후속, ADR-029 후보)
  - 본 라이브러리 디버그 UI frontend + TripMate `apps/web` 사용자 UI 공통화
  - `@krtour/map-marker-react` (가칭) — `krtour.map.category` Tier 1~4 →
    maki icon(55종) dispatch + `MakiMarker` 공통 컴포넌트
  - 의존: `maplibre-vworld`, `maplibre-gl`
  - 라이선스: GPL-3.0-or-later 또는 MIT (TripMate proprietary와 호환되도록
    별도 ADR로 결정)
- [ ] T-018 — **`python-knps-api` provider 등록** (ADR-027 카테고리 확장 +
      ADR-028 provider 등록 후보)
  - `digitie/python-knps-api` 저장소 신설 — `python-mois-api` 패턴 미러
  - `krtour.map.providers.knps` 모듈 신설
  - `docs/forest-feature-etl.md` §11 KNPS 통합 실행
- [ ] T-019 — **TripMate 측 후속 작업 추적** (ADR-026 후속, 본 저장소 외)
  - TripMate `apps/web` Kakao Maps → maplibre-vworld 교체 PR (TripMate 저장소)
  - SPEC V8 v8_3 Kakao Maps 섹션에 "superseded by python-krtour-map ADR-026"
    표기 (SPEC 저장소)
  - 본 저장소는 ADR-026 reference만 책임. 작업 자체는 미트래킹.

## 보류 (v2 1차 범위 외)

- [ ] T-101 — Materialized View 도입 검토 (feature + detail flatten)
- [ ] T-102 — pg_prewarm 부팅 후 warm-up
- [ ] T-103 — 별도 streaming ETL (Kafka/Redpanda) 대응

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
      maplibre-vworld 통일 (완료: 2026-05-25, PR#6 검토 대기)
  - `docs/decisions.md` ADR-025 + ADR-026
  - `docs/debug-ui-package.md` §14 frontend 사양
  - `packages/krtour-map-debug-ui/frontend/` skeleton
    (package.json / .env.example / .gitignore / README)
  - `docs/tripmate-integration.md` §14.5 사용자 UI 지도 stack
  - `docs/external-apis.md` Kakao Maps SDK 미사용 처리
  - `docs/forest-feature-etl.md` §11.6 ADR-026 → ADR-027 후보 재번호

## 폐기

- ~~T-100~~ — "디버그 UI 별도 Next.js 패키지 분리" — **폐기**:
  Python 패키지로 분리 (T-001b, ADR-020) + frontend는 React+Vite (ADR-025)로
  결정. Next.js 미채택.

## 우선순위 가이드

- **즉시** — PR#6 검토 + merge
- **다음** — T-012 (ADR-020+ 후속 결정) 또는 T-014 (코드 작성 단계 진입 검토,
  사용자 승인 필요)
- **장기** — Sprint 5 (T-200~T-204), provider 확장 (T-017, T-018)

## ADR 번호 가이드 (현재)

- **accepted**: ADR-001 ~ ADR-026
- **proposed (검토 대기)**: ADR-030 (캐시 금지) / ADR-031 (OpenAPI export) /
  ADR-032 (Coverage 일정, 시기 의존) / ADR-033 (`feature_consistency_reports`,
  시기 의존)
- **후보 (미작성)**: ADR-027 (forest 카테고리 확장) / ADR-028 (`python-knps-api`
  provider 등록) / ADR-029 (공통 maki npm 패키지) / ADR-034+ (신규 provider
  추가 절차 표준)
