# CHANGELOG

본 라이브러리의 사용자 가시 변경을 기록한다. [Keep a Changelog](https://keepachangelog.com)
형식을 따른다.

## [Unreleased]

### 변경 / 재설계 (v2 design)

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
