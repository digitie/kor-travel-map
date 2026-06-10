# 에이전트 운영 Runbook

`python-krtour-map`을 편집하는 **AI 에이전트 공용** runbook. Claude Code / OpenAI
Codex / Google Antigravity 가 **같은 파일을 공유**한다 — 내용은 에이전트 중립이며,
에이전트별로 다른 부분(worktree 경로, `sandbox/<agent>` 브랜치)은 표로 분기한다.

> TripMate 본체(`F:\dev\tripmate`)의 `docs/runbooks/` 컨벤션(인덱스 + 공통 정책 +
> 에이전트별 worktree)을 본 라이브러리에 맞춰 옮긴 것이다. ADR-045 이후
> TripMate ↔ krtour-map은 **OpenAPI 기반 HTTP** 관계다. 운영 절차는 공유하되
> 식별자·포트는 본 lib 기준으로 적는다.

## 1. 인덱스

| 파일 | 범위 |
|------|------|
| [agent-workflow.md](./agent-workflow.md) | 표준 1-PR 작업 흐름 (worktree → 브랜치 → NTFS 편집 → WSL 게이트 → PR → CI green → 머지 → 동기화) + 갱신 필수 문서 |
| [agent-failure-patterns.md](./agent-failure-patterns.md) | 본 repo에서 반복된 **실패 패턴**과 회피·복구법 (CI/로컬 괴리, 자연키, upstream drift, 테스트 격리 등) |
| [branch-protection.md](./branch-protection.md) | GitHub `main` branch protection 운영자 설정. PR 필수, required checks, force-push 차단 |
| [docker-app.md](./docker-app.md) | 독립 Docker app 기동/중지/스모크. 고정 포트: API 9011, admin UI 9012, Dagster 9013 |
| [admin-ui-screen-checklist.md](./admin-ui-screen-checklist.md) | admin UI 16 route 화면별 점검(필터/cursor/빈·에러/kill-switch/a11y/e2e 매트릭스) + 신규 폼 추가 절차 (T-218f) |
| [cross-repo-audit-checklist.md](./cross-repo-audit-checklist.md) | 분기 1회 4-repo 계약/문서 drift 점검(origin/main 실측·계약 대조·전제 신선도·결정 전파) (T-217d) — 연동 지도는 [`../integration-map.md`](../integration-map.md) |
| [../backup-restore.md](../backup-restore.md) | 독립 app cold backup/restore 경계. 대상: `krtour_map` + `krtour_map_dagster` + RustFS |

> 환경·도구 1차 문서는 별도다 — 본 runbook은 그걸 **운영 절차로 엮는다**.
> - 개발 환경(NTFS/WSL, e2e): `docs/dev-environment.md`
> - worktree + codegraph: `docs/codegraph-worktree.md` + `AGENTS.md` §"에이전트 worktree"
> - 진입·문서화 규약: `docs/agent-guide.md`
> - DO NOT 룰: `SKILL.md` §4

## 2. 에이전트별 분기 (공유 표)

| AI 에이전트 | 고정 worktree | 작업 브랜치 push 대상 |
|-------------|---------------|----------------------|
| OpenAI Codex | `F:\dev\python-krtour-map-codex` | `sandbox/codex` |
| Claude Code | `F:\dev\python-krtour-map-claude` | `sandbox/claude` |
| Google Antigravity 2.0 | `F:\dev\python-krtour-map-antigravity` | `sandbox/antigravity` |

- **worktree는 영속**, 작업마다 그 안에서 **브랜치만 새로** 딴다
  (`git switch -c feat/<topic> main`). 메인 trunk(`F:\dev\python-krtour-map`)는
  사람 전용 — 에이전트는 자기 worktree만 만진다.
- 모든 에이전트는 PR을 **`main`** 으로 올린다. `sandbox/<agent>`는 자기 worktree의
  머지 후 동기화용 브랜치(머지된 main을 ff로 따라가며 push)다.
- 자세한 setup: `docs/codegraph-worktree.md`.

## 3. 공통 정책 (요약)

| 항목 | 정책 | 근거 |
|------|------|------|
| Git source of truth | **NTFS** (`F:\dev\python-krtour-map*`). 편집·커밋·PR은 Windows Git. | AGENTS.md, ADR |
| 테스트 실행 | **WSL ext4**로 rsync 후 PostGIS/testcontainers 구동. | dev-environment.md |
| `scripts/*.sh` 실행 | WSL 또는 Git Bash. PowerShell은 `.sh` 직접 실행 대신 WSL 위임. | dev-environment.md §2.3 |
| 4 게이트 | `ruff check` + `mypy --strict` + `lint-imports` + `pytest -q` (DTO/admin/frontend 변경 시 OpenAPI/frontend 추가) | ADR-014/032 |
| main 직접 push | **금지** — feature branch + PR + **CI green 후** 머지 | ADR-021/038 |
| import 루트 | `from krtour.map import ...` (flat 금지) | ADR-022 |
| 결정·기록 5종 | 코드 바꾸면 `decisions/resume/journal/tasks/SPRINT` 중 관련된 것 갱신 | agent-guide.md §2 |

전체 룰은 `SKILL.md` §4(22개), `CLAUDE.md` §5(절대 금지 5개).
