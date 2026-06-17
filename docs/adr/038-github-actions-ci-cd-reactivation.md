# ADR-038: GitHub Actions CI/CD 재활성화 — 머지 게이트 다시 켬

- **상태**: accepted (PR#33, 2026-05-27 — 종전 "쓰지마" 지시 reverse)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

2026-05-26 사용자가 "깃헙 ci/cd 쓰지마"로 지시 → 로컬 검증(pytest + ruff +
mypy + lint-imports) 기반 머지 직행 운영. `.github/workflows/{ci,lint,
openapi}.yml`은 워크플로우 파일은 남겨두고 실행 결과를 머지 게이트로 쓰지 않음.

운영 단계 진입 + 다중 에이전트 PR이 늘면서 다음 문제 인지:

- 로컬 검증만으로는 "내 PC에서 됨" 함정 (testcontainers PostGIS 환경 차이,
  Python 3.11/3.12/3.13 matrix 누락, OS 차이 등).
- 사용자가 직접 일일이 머지 직전 검증을 보강하기 어렵다.

### 결정

- **GitHub Actions CI/CD 재활성화**. 다음 워크플로우를 PR/main push 기준 머지
  게이트로 사용:
  - `.github/workflows/ci.yml` — pytest unit + integration matrix (3.11/12/13)
  - `.github/workflows/lint.yml` — ruff + mypy + import-linter
  - `.github/workflows/openapi.yml` — OpenAPI drift gate (ADR-031, Sprint 2
    첫 라우터 진입 후 실효)
- branch protection rules에서 위 워크플로우 통과 + 1 review approval 필수
  (사용자 직접 설정 — Settings → Branches → main).
- 로컬 검증은 **유지** — PR 푸시 전 1차 확인용. CI는 2차 검증 + matrix.

### 근거

- CI는 환경 격차/regression의 마지막 차단선. 끄면 후속 PR 빚을 진다.
- "쓰지마" 시기의 효율 이점(로컬 검증만 → 즉시 머지)은 PR 1~2건짜리 sprint
  scaffolding에서만 유효 — Sprint 2 본격 진입하면 코드 변경량/충돌이 늘어
  CI 없이 위험.

### 결과 (긍정)

- matrix CI로 3.11/3.12/3.13 + ubuntu-latest 환경 자동 검증.
- testcontainers PostGIS가 CI에서 매번 부트 → 적재 회귀 차단.

### 결과 (부정)

- 머지 latency가 늘어남 (PR push → CI 실행 ~5~8분 대기).
- CI 실패 시 fix 푸시 + 재실행 cycle.
- 완화: branch protection을 `Require status checks` + `Require branches up
  to date` 두 가지만, `Require linear history`/`Require signed commits`는
  당장은 보류(Sprint 4 진입 시 재검토).

### 후속

- `AGENTS.md` 작업 후 체크리스트 §"검증" 갱신 — "로컬 + CI 모두 green"
  표기.
- `SKILL.md` DO NOT 룰 #17 "main 직접 push 금지" 옆에 "CI green 통과 후
  머지" 추가.
- 사용자 측 GitHub Settings → Branches → main → Branch protection rules
  활성화 (사용자 직접 / 본 라이브러리 코드 변경 X).
- 종전 머지 직행 패턴 폐기 — `docs/journal.md` 2026-05-26 "쓰지마" 지시
  reference에 reverse note.
