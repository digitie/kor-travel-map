# agent-workflow — 표준 1-PR 작업 흐름

본 repo를 편집하는 **모든 AI 에이전트 공용** 절차. 한 task = 한 feature branch =
한 PR = CI green 후 머지. 에이전트별로 다른 값(worktree, `sandbox/<agent>`)은
[README §2 표](./README.md#2-에이전트별-분기-공유-표)를 본다.

> 요지: **NTFS worktree를 source of truth로 두고, 순수 Git을 제외한 작업은 WSL에서
> `/mnt/f/...` 경로로 실행한 뒤 PR로 머지한다.** Playwright e2e만 Windows 호스트
> 브라우저에서 실행한다.

## 1. 진입 (5분)

1. 자기 worktree로 이동 (예: Claude → `F:\dev\kor-travel-map-claude`).
2. `CLAUDE.md`/`AGENTS.md` → `SKILL.md` → `docs/sprints/README.md` →
   `docs/resume.md`("다음 한 작업") → `docs/journal.md` 최신 3건 → 관련 ADR.
3. `codegraph sync`(init 아님) — 인덱스 증분 동기. 컴포넌트(특히 `Feature` DTO /
   `make_feature_id` / provider 변환) 수정 전 `codegraph impact`/`callers`로 영향도
   확인.

## 2. 브랜치

```
git -C <worktree> fetch origin
git -C <worktree> switch -c feat/<topic> main      # 또는 origin/main
```

- worktree는 영속, **브랜치만 새로**. 메인 trunk(`F:\dev\kor-travel-map`)는 안 만짐.
- `sandbox/<agent>` 위에서 **직접 작업/커밋하지 않는다** — 반드시 `feat/*`·`fix/*`·
  `docs/*`·`chore/*` 브랜치. (실수로 `sandbox/<agent>`에 커밋했으면
  [failure-patterns §B1](./agent-failure-patterns.md) 복구법.)

## 3. 편집 (NTFS worktree, WSL 실행)

- 코드/문서는 **NTFS worktree**가 원본이다. 다만 `rg`/`sed`/`python`/`uv`/`npm`/
  `docker`/`gh` 같은 순수 Git 외 명령은 WSL에서
  `/mnt/f/dev/kor-travel-map-<agent>`로 이동해 실행한다. provider 라이브러리
  (`python-*-api`)는 `/mnt/f/dev/` 로컬 우선 조회(ADR-044) — GitHub 404는
  "미존재" 근거 아님.
- 변경 분류별 동시 갱신 문서(agent-guide.md §2 "결정·기록 5종"):
  코드만 바꾸고 `decisions/resume/journal/tasks/SPRINT` 중 관련된 게 하나도 안 바뀌면
  그 PR은 불완전.

## 4. 검증 (WSL) — 4 게이트

게이트는 WSL에서 실행한다. 기본은 NTFS worktree의 WSL 마운트 경로를 직접 쓰며,
ext4 mirror는 성능·격리 필요 시에만 선택한다.

```bash
cd /mnt/f/dev/kor-travel-map-<agent>
.venv/bin/ruff check .                 # 1) lint/format
.venv/bin/mypy --strict src            # 2) 타입 (필요 시 packages/.../src 도)
.venv/bin/lint-imports                 # 3) 의존 계층 (4 contracts)
.venv/bin/python -m pytest -q          # 4) 전체 테스트 (testcontainers PostGIS)
```

- **debug-ui 라우터/DTO 변경 시** OpenAPI drift 게이트 추가:
  `python packages/kor-travel-map-api/scripts/export_openapi.py --profile all`
  로 admin/user spec을 재생성 후 `--profile all --check`로 EXIT=0 확인 —
  재생성본을 NTFS로 복사해 커밋.
- **Playwright e2e**는 하이브리드: 서버(backend `:12301` + frontend `:12305`)는 WSL,
  Playwright(chromium)는 **Windows 호스트**에서. `docs/dev-environment.md` §8.1.
- 로컬 green을 맹신하지 말 것 — WSL venv가 누락된 `[dev]` extra를 가릴 수 있다
  ([failure-patterns §A1](./agent-failure-patterns.md)).

## 5. 커밋 + PR

```
git -C <worktree> add <관련 파일만>     # claude.json 등 무관 파일 제외
git -C <worktree> commit -m "<type(scope): summary>" -m "<본문: 무엇/왜/게이트 결과>"
git -C <worktree> push -u origin feat/<topic>
gh pr create --base main --head feat/<topic> --title ... --body ...
```

- 커밋/PR 본문에는 **실제 게이트 결과**(예: `ruff clean / mypy N files / import-linter
  4 kept / M passed`)를 적되, **반드시 실행해서 본 수치만**. 안 돌린 결과를 적지
  않는다([failure-patterns §A2](./agent-failure-patterns.md)).
- 커밋 trailer: `Co-Authored-By:` 한 줄. PR 본문 끝: `🤖 Generated with ...`.
- Windows Git을 WSL 비대화 세션에서 쓸 때 `rebase --continue`/`merge --continue`는
  Vim이 열려 멈출 수 있다. 항상 명령 단위 editor 우회 옵션을 붙인다:
  `git.exe -C <worktree> -c core.editor=true rebase --continue`
  ([failure-patterns §B4](./agent-failure-patterns.md)).
- PR 생성 직후 `mcp-telegram` MCP로 Telegram에 **짧은 작업 요약 + PR 링크**를
  보낸다. CI 실패 수정처럼 같은 PR을 갱신한 경우에는 새로 완료된 단위 작업과
  같은 PR 링크를 다시 보낸다. PR이 없는 로컬 셋업/조사 작업이면 "PR 없음"과
  적용 위치를 명시한다. credential은 각 worktree의 로컬 `.env.mcp-telegram`에만
  둔다(`docs/codegraph-worktree.md` §6.5).

## 6. CI green → 머지

```
gh pr checks <N> --watch              # lint + pytest unit/integration/fixture + openapi/frontend
gh pr merge <N> --merge --delete-branch
```

- **CI green 전 머지 금지**(ADR-021/038). 3.11/3.12/3.13 모두 통과 확인 — 버전별
  실패가 흔하다([failure-patterns §A3](./agent-failure-patterns.md)).

## 7. 머지 후 동기화

머지 후 자기 worktree의 `sandbox/<agent>`와 WSL 미러를 main에 맞춘다:

```
git -C <worktree> switch sandbox/<agent>
git -C <worktree> fetch origin && git -C <worktree> merge --ff-only origin/main
git -C <worktree> branch -D feat/<topic>
git -C <worktree> push origin sandbox/<agent>
# WSL 미러도 main으로:
#   cd ~/dev/kor-travel-map && git fetch origin && git reset --hard origin/main
```

- WSL 미러가 main보다 뒤처져 보이면 `git reset --hard origin/main`
  ([failure-patterns §B2](./agent-failure-patterns.md)).

## 8. 1-PR 체크리스트

- [ ] feature 브랜치(`sandbox/*` 아님)에서 작업
- [ ] 4 게이트 WSL에서 실제 실행, 전부 green (DTO/admin/frontend 변경이면 OpenAPI/frontend도)
- [ ] 결정·기록 5종 중 관련 문서 갱신 (CHANGELOG는 사용자 가시 변경 시)
- [ ] 무관 파일(claude.json 등) 스테이징 제외
- [ ] PR 본문에 실측 게이트 수치
- [ ] CI 3버전 green 확인 후 머지 → sandbox/<agent> + WSL 동기화
