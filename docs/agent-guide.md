# agent-guide.md — 에이전트 작업·문서화 가이드

이 문서는 AI 에이전트가 본 저장소에서 작업할 때의 행동 지침이다. `AGENTS.md`,
`SKILL.md`와 함께 읽는다.

## 1. 첫 5분 진입 프로토콜

새 세션이 들어오면 이 순서로 컨텍스트를 확보한다:

1. `README.md` — 정체성, 빠른 시작, 문서 지도
2. `SKILL.md` — DO NOT 룰, 도메인 어휘
3. `docs/sprints/README.md` — Sprint 1~5 + ADR-034 9단계 순서
4. `docs/architecture/architecture.md` 목차 — 의존 방향, 데이터 흐름
5. `docs/resume.md` — "다음 한 작업"
6. `docs/journal.md` 최신 3건 — 직전 컨텍스트
7. 관련 ADR (`docs/adr/README.md` — ADR-001~059 전부 accepted, 다음 후보 060)
8. 직결 docs (provider 추가면 `docs/architecture/provider-contract.md`, 현재 sprint면
   `docs/sprints/SPRINT-N.md` 등)
9. **운영 runbook** (`docs/runbooks/`) — 에이전트 공용. 실제 작업 시작 전
   [agent-workflow.md](runbooks/agent-workflow.md)(표준 1-PR 흐름)와
   [agent-failure-patterns.md](runbooks/agent-failure-patterns.md)(반복 실패 회피)는
   훑고 들어간다. 게이트가 깨지면 failure-patterns부터 본다.

5~10분 안에 위 9개를 훑으면 거의 모든 작업의 정합성 판단이 가능하다.

### 1.1 코드 수정 우선순위

본 저장소에서 코드 작성·수정은 **최소 코드 변경**이나 **기존 임시 계약과의
호환성**보다 완성도, 최적 구조, 확장성, 안정성을 우선한다. 문제를 발견하면
호출부만 맞추는 shim, 임시 adapter, 런타임 추정값으로 덮기 전에 데이터 모델,
migration, DTO, repository, API schema, 테스트가 같은 계약을 공유하는지 먼저 본다.
PR scope는 작게 유지하되, 그 scope 안에서는 production으로 이어질 구조를 택한다.

### 1.2 자기 worktree로 이동

본 저장소는 **에이전트별 고정 worktree** 정책을 쓴다 (`docs/codegraph-
worktree.md`). 새 세션 진입 후 컨텍스트 확보 직전에 자기 worktree로 이동:

```bash
# 어떤 AI 에이전트인지에 따라:
git.exe -C F:/dev/kor-travel-map-codex status       # ChatGPT Codex
git.exe -C F:/dev/kor-travel-map-claude status      # Claude Code
git.exe -C F:/dev/kor-travel-map-antigravity status # Google Antigravity 2.0
```

worktree가 아직 없으면 `docs/codegraph-worktree.md` §3 "최초 setup" 참조.
codegraph 인덱스는 `codegraph sync`로 증분 동기(있다면) / `codegraph init -i`
(최초). 사용자가 직접 작업할 때는 메인 worktree(`F:\dev\kor-travel-map\`)를
쓰고 `kor-travel-map-*`에는 들어가지 않는다.

## 2. 결정·기록 5종 (필수 유지)

| 파일 | 역할 | 갱신 시점 |
|------|------|----------|
| `docs/adr/README.md` | ADR 누적 | 결정이 발생할 때마다 |
| `docs/resume.md` | 진척도 + "다음 한 작업" | 작업 마무리마다 |
| `docs/journal.md` | 작업 로그 (역시간순 append) | 작업 끝낼 때마다 |
| `docs/tasks.md` | 백로그 — **진행/예정(`[ ]`)** + 상단 "진행 중인 작업 인덱스" | 작업 추가/시작 시 |
| `docs/tasks-done.md` | 완료·아카이브(`[x]`) + 머지 history 표 (2026-06-09 분리) | 작업 완료/포기 시 + PR 머지 시 |
| `docs/sprints/SPRINT-N.md` | Sprint별 진입/산출물/DoD | Sprint 진입/종료 PR마다 |

코드/문서를 바꿨는데 위 5개 중 관련된 것이 하나도 갱신되지 않았다면 그
PR은 불완전하다.

## 3. ADR 작성 규약

번호: `ADR-NNN` 연번. **현재 다음 번호 = ADR-060** (ADR-035~043 PR#33으로
일괄 accepted 전환됨 2026-05-27, ADR-044~059는 2026-06 accepted).

```markdown
## ADR-NNN: <결정 요약>

- 상태: proposed | accepted | superseded by ADR-XXX
- 날짜: YYYY-MM-DD
- 결정자: <agent | human> 또는 둘 모두

### 컨텍스트
무엇이 문제였고 왜 결정이 필요했는지.

### 결정
무엇을 하기로 했는지. 구체적으로.

### 근거
왜 이 결정인지. 대안과의 비교.

### 결과 (긍정)
- ...

### 결과 (부정)
- ...

### 후속
- 어떤 코드/문서/테스트가 변경되어야 하는지.
```

결정이 뒤집힐 때:
- 새 ADR을 추가하고
- 옛 ADR의 상태를 `superseded by ADR-XXX`로 표시
- **옛 ADR 본문은 지우지 않는다** — 결정 이력을 남긴다.

## 4. journal.md 엔트리 형식

역시간순으로 위에서 아래로 append. 가장 위가 가장 최근.

```markdown
## 2026-05-25 14:30 (claude)
**작업**: ADR-020 추가 (캐시 전략 결정)
**변경 파일**:
- docs/adr/README.md (ADR-020 추가)
- docs/architecture/performance.md §9 갱신
- docs/resume.md 진척도 갱신
**결정**: 라이브러리 in-memory 캐시 도입하지 않음, 호출자 책임
**발견**: PinVi는 Redis를 이미 가지고 있어 외부 캐시는 자연스럽다
**다음**: 코드 작성 단계 진입 전 ADR-020 사용자 확인 받기
```

`작업/변경/결정/발견/다음` 5개 필드를 유지. 빈 필드는 생략 가능.

## 5. resume.md 형식

```markdown
# resume.md

## 현재 상태
현재 상태는 `docs/resume.md`와 `docs/tasks.md`를 정본으로 본다.
ADR 001~059 모두 accepted (다음 후보 060).

## 다음 한 작업
ADR-045 독립 프로그램화(Docker compose + admin-first OpenAPI + 독립 Dagster).

## 진척도
- [x] AGENTS.md / README / SKILL / CLAUDE
- [x] docs/architecture, decisions(ADR-001~049), data-model
- [x] provider 변환, PostGIS 적재/조회, consistency report, dedup queue
- [x] MOIS Step A~D + dedup-merge + feature_merge_history + phone enrichment
- [ ] ADR-045 독립 프로그램화 + Sprint 5 MOIS-sibling provider

## 다음 ADR 후보
- ADR-050: 다음 신규 의사결정

## 차단 사유 / 결정 대기
- (없음)
```

## 6. tasks.md 형식

task 문서(`tasks.md`/`tasks-done.md`) 작성·유지 규약은 [`docs/tasks-rule.md`](tasks-rule.md)가 정본.

## 7. 변경 분류별 체크리스트

### 7.1 ADR 추가만

- [ ] `docs/adr/README.md`에 추가
- [ ] `docs/journal.md` 엔트리
- [ ] `docs/resume.md` "다음 한 작업" 갱신

### 7.2 docs 신규/수정

- [ ] 한국어 산문 (코드 식별자만 영문)
- [ ] 관련 ADR 링크
- [ ] `docs/journal.md` 엔트리

### 7.3 DTO 추가/변경 (코드 단계 진입 후)

- [ ] **수정 전 영향도 평가** — MCP `codegraph_explore` 또는 CLI
      `codegraph callers <sym>` + `codegraph impact <file>`로 호출자 파악
      (`docs/codegraph-worktree.md` §7).
- [ ] `dto/` 모듈 + Pydantic validator
- [ ] `tests/unit/test_dto_*.py` validator branch 100%
- [ ] 관련 통합 테스트
- [ ] `docs/architecture/data-model.md` 갱신 (DDL과 동기)
- [ ] DB schema 변경 시 Alembic migration
- [ ] ADR (어느 정도 큰 변경이면)
- [ ] `docs/adr/README.md` + journal + resume
- [ ] OpenAPI export 재실행

### 7.4 raw SQL 추가/변경

- [ ] `infra/*_repo.py`의 `_SQL` 상수에 추가
- [ ] `tests/integration/`에 EXPLAIN 검증 테스트 1개 이상
- [ ] 인덱스 무효화 회피 확인
- [ ] `docs/architecture/performance.md` 패턴/안티패턴 갱신 (필요 시)
- [ ] journal + resume

### 7.5 provider 추가

- [ ] `providers/<name>.py` 변환 함수 (순수)
- [ ] `tests/fixtures/<name>/` 3개+ fixture
- [ ] `tests/unit/test_providers_<name>.py`
- [ ] `tests/integration/test_load_<name>.py`
- [ ] `docs/<name>-feature-etl.md` (provider별 ETL 문서 — 표준 10섹션)
- [ ] `docs/architecture/provider-contract.md`의 provider 카탈로그 추가
- [ ] `docs/external-apis.md`에 API 키 발급/호출 정책
- [ ] ADR (필요 시 — 새 dataset_key, 새 source_role 등)
- [ ] `pyproject.toml`의 provider extra에 git URL+sha 핀
- [ ] journal + resume

## 7.5 PR 워크플로 (ADR-021, 필수)

main에 직접 push 금지. 모든 변경은 feature branch + PR.

### 7.5.1 시작

```bash
cd ~/dev/kor-travel-map
git checkout main
git pull origin main
git checkout -b feat/<topic>      # 또는 fix/, chore/, docs/, refactor/, adr/
```

### 7.5.2 작업

- 짧은 commit + 명확한 메시지. 첫 줄 70자 이내. 형식 권장 (kor-travel-geo 패턴 미러):
  ```
  <scope>: <verb> <object> (#T-NNN 또는 ADR-NNN 또는 issue)

  본문 — "왜" 위주. 변경 내용은 diff가 알려준다.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
  - `<scope>`: `dto` / `core` / `infra` / `providers/<name>` / `client` / `cli` /
    `docs` / `chore` / `category` / `debug-ui`
  - `<verb>`: `add` / `fix` / `refactor` / `move` / `remove` / `tighten` / `rename` / `document`
- 작업 단위로 `docs/journal.md`, `docs/resume.md`, (필요 시) `docs/adr/README.md`,
  `CHANGELOG.md` 갱신.
- 단위 테스트 + lint + mypy + lint-imports 통과 확인 (코드 작성 단계).

### 7.5.3 PR 작성

표준 PR 본문 (kor-travel-geo `docs/agent-guide.md` 패턴 미러):

```bash
git push -u origin feat/<topic>
gh pr create --title "<scope>: <imperative summary (≤70자)>" --body "$(cat <<'EOF'
## 동기 (Motivation)
- 무엇을 바꾸는지 + 왜 바꾸는지 (한 문단)

## 변경 (Changes)
- 파일/모듈별 핵심 변경
- 새 DTO/엔드포인트/스키마/ADR 있으면 명시

## 영향 (Impact)
- BREAKING 여부 (DTO 시그니처, DB schema, OpenAPI)
- PinVi / 디버그 UI / provider 어느 쪽에 변경 필요한지

## 검증 (Verification)
- [ ] pytest tests/unit -q
- [ ] ruff check . / mypy --strict / lint-imports
- [ ] (해당 시) pytest tests/integration -q
- [ ] (해당 시) EXPLAIN 통합 테스트로 인덱스 사용 검증
- [ ] (해당 시) OpenAPI export check

## 문서 (Docs)
- [ ] docs/journal.md 엔트리
- [ ] docs/resume.md 진척도 갱신
- [ ] ADR 추가 시 docs/adr/README.md
- [ ] 사용자 가시 변경 시 CHANGELOG.md
- [ ] DTO/스키마 변경 시 docs/{data-model,feature-model}.md
- [ ] provider 추가 시 docs/<provider>-feature-etl.md

## 관련 (Related)
- ADR-XXX
- T-NNN
- (외부 issue/spec 링크)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### 7.5.4 브랜치 명명 규약

| prefix | 용도 |
|--------|------|
| `feat/` | 새 기능 (DTO, repository, provider, route 추가 등) |
| `fix/` | 버그 수정 |
| `chore/` | 의존성, 설정, CI, 빌드 등 |
| `docs/` | 문서만 |
| `refactor/` | 동작 변경 없는 재구조화 |
| `adr/` | 결정 단독 PR |
| `agent/<id>/<topic>` | 다중 에이전트가 병행 작업할 때 |

### 7.5.5 리뷰 / merge

- 단일 작성자/검토자라도 PR 페이지에서 변경 한 번 더 확인 후 merge.
- merge 방식: **Squash and merge** 권장 (main 히스토리 깔끔).
- 또는 의미 있는 단위로 commit이 정렬되어 있으면 rebase + merge.
- merge commit 제목: PR 제목과 동일하게.
- merge 후 feature branch는 `gh` UI 또는 `git push origin --delete <branch>`로 삭제.

### 7.5.6 main 직접 push 차단

GitHub branch protection (운영자 수동 설정):
- Require pull request before merging
- Require at least 1 approval (자체 PR은 self-approve 허용 운영 모델)
- Require status checks to pass (lint, test, lint-imports, openapi drift)
- Restrict force-push

운영자가 위를 설정해 두면 `git push origin main`은 서버에서 거부된다.

### 7.5.7 핸드오프

세션이 중단되면 PR 코멘트에 handoff 노트
(`docs/windows-reinstall-recovery.md` §4 포맷). 다음 에이전트/사람은 PR URL과
`docs/resume.md`만 보면 바로 인수받을 수 있다.

## 8. 코드 작성 단계 (Sprint 4 진입 준비)

본 저장소는 T-014 승인 (2026-05-25, PR#16) 이후 **코드 작성 단계**다.
현재 진척은 `docs/resume.md`와 `docs/tasks.md`를 정본으로 본다.
신규 코드는 항상 PR (ADR-021).

기본 작업 절차:
1. 사용자 의도 명확화 (어떤 모듈/계층/메서드인지)
2. ADR이 필요한지 확인 (`docs/adr/README.md` 001~049 모두 accepted, 신규는
   050+)
3. 테스트 우선 작성 (`docs/test-strategy.md` §12 우선순위)
4. 구현 (`pytest -q`/`ruff check`/`mypy --strict`/`lint-imports` 통과)
5. 통합 테스트 + EXPLAIN 검증 (DB 닿는 경우)
6. `docs/journal.md` + `docs/resume.md` 업데이트 (+ ADR/CHANGELOG/OpenAPI
   해당 시)

## 9. Windows Git vs WSL 실행 흐름

- 브랜치 전환, 커밋, push 같은 순수 Git 명령은 Windows NTFS worktree에서
  Windows Git(`git.exe`)로 수행해도 된다.
- 파일 조회·수정·테스트·lint·build·Docker·Python/Node/npm·`gh`/GitHub CLI는 WSL에서
  `/mnt/f/dev/kor-travel-map-<agent>`로 이동해 실행한다.
- Playwright e2e만 Windows 호스트에서 실행한다. 서버는 WSL/Docker 기준이다.
- `data/`는 NTFS에 보관하고 git에는 넣지 않는다.
- WSL ext4 mirror는 대량 I/O 성능·격리 필요 시의 선택 경로다. Git source of truth는
  NTFS다.

상세 절차는 `docs/dev-environment.md`.

## 10. 도움이 안 될 때

- 사용자 요청이 모호하면 `AskUserQuestion` 사용 (최대 4지선다 + Other).
- 코드 작성 요청이 명백히 `AGENTS.md` 규칙과 충돌하면 충돌을 명시하고 대안을
  제시.
- 모르는 도메인 어휘가 나오면 `SKILL.md` §6 검색 → 없으면 사용자에게 질의.
- 같은 결정이 두 번째로 흔들리면 ADR-NNN으로 박는다.

## 11. 다른 에이전트와의 핸드오프

세션이 중단되거나 새 에이전트가 인수받을 때 `docs/journal.md`의 가장 최근
엔트리가 핸드오프 노트 역할을 한다. 다음 단서를 모두 포함:

- 무엇을 했는지
- 무엇이 남았는지
- 어떤 결정이 보류 중인지
- 어떤 파일을 가장 먼저 봐야 하는지

PR 핸드오프 표준 포맷은 `docs/windows-reinstall-recovery.md` 참고.

## 12. 마침

이 가이드는 살아 있는 문서다. 작업하면서 빠진 룰이 발견되면 ADR과 함께 추가
하거나 `agent-guide.md`를 직접 수정한다.
