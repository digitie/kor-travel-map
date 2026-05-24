# tasks.md — 백로그

이 문서는 작업 백로그다. 우선순위 순. 각 작업은 `T-NNN` 번호로 식별한다.

## 진행 중

- (없음 — PR#2 검토 대기)

## 다음 (우선순위 순)

- [ ] T-012 — ADR-020+ 후속 결정 (필요 시)
  - 캐시 전략 (라이브러리 레벨 cache 도입 여부)
  - OpenAPI export 정책 (디버그 패키지 라우터 노출 시점)
  - 단위 테스트 coverage 단계적 상향 계획
- [ ] T-013 — `CHANGELOG.md` 초기 엔트리 정리 (현 v2 design 완료 시점)
- [ ] T-014 — 코드 작성 단계 진입 검토
  - 모든 문서 검토 완료
  - 사용자 승인
  - Sprint 계획 (`SPRINT-1.md` 또는 `docs/sprints/`)

## 보류 (v2 1차 범위 외)

- [ ] T-100 — 디버그 UI 별도 Next.js 패키지 분리 (`krtour-map-debug-ui`)
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
- [x] T-001b — ADR-020 + 디버그 UI 별도 패키지로 분리 (완료: 2026-05-24)
  - decisions(ADR-020), architecture, backend-package, debug-ui-package(신규),
    AGENTS, SKILL, CLAUDE, README, pyproject(`[api]` 제거 + forbidden 계약 추가),
    .env.example, test-strategy 갱신
  - `packages/krtour-map-debug-ui/` pyproject + README skeleton
- [x] T-002 ~ T-011 — v1 docs를 v2 기준으로 일괄 이전 (완료: 2026-05-24, PR#2)
  - 14개 신규 docs (weather/files-rustfs/opening-hours/kraddr-base-types/
    address-geocoding/dagster-boundary/postgres-schema/debug-fixture-workflow/
    feature-db-initialization/tripmate-integration + provider ETL 10건)
- [x] T-001 — v2 핵심 docs 작성 (완료: 2026-05-24)
  - AGENTS.md, README.md, SKILL.md, CLAUDE.md
  - .env.example, pyproject.toml, .gitignore, .gitattributes, LICENSE
  - docs/architecture.md
  - docs/decisions.md (ADR-001 ~ ADR-019)
  - docs/data-model.md
  - docs/performance.md
  - docs/test-strategy.md
  - docs/backend-package.md
  - docs/agent-guide.md
  - docs/dev-environment.md
  - docs/windows-reinstall-recovery.md
  - docs/feature-model.md
  - docs/provider-contract.md
  - docs/external-apis.md

## 우선순위 가이드

- **즉시** — v2 코드 작성 단계 진입 전 필수: T-002 ~ T-011
- **이후** — 코드 작성 단계 진입 후 점진적 도입: T-012 ~ T-014
- **장기** — v2 1차 안정화 후: T-100 ~ T-103
