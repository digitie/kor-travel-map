# codegraph + Agent Worktree 운영 룰

본 문서는 AI 에이전트(Claude Code / ChatGPT Codex / Google Antigravity 2.0 등)가
본 저장소에서 작업할 때 **고정 worktree** + **codegraph 로컬 인덱스**를
어떻게 운영하는지 박는다. `AGENTS.md` §"에이전트 worktree + codegraph",
`SKILL.md` §"개발 환경 (PC, WSL)", `CLAUDE.md` §"5. 의존 스택"이 본 문서를
참조한다.

## 1. 왜 agent별 고정 worktree인가

여러 AI 에이전트가 동시에 한 저장소에서 일할 때 발생하는 문제:

1. **브랜치 컨텍스트 충돌** — Codex가 `feat/visitkorea`에서 작업 중인데
   Claude가 같은 디렉토리에서 `feat/kma`로 `git switch` 하면 Codex의
   uncommitted 변경/IDE 상태가 깨진다.
2. **빌드 캐시 무효화** — `.venv`/`.mypy_cache`/`.pytest_cache`는 브랜치별로
   다른 의존 트리/타입 캐시를 갖는다. 브랜치를 자주 바꾸면 매번 재구축.
3. **codegraph 인덱스 동기화 비용** — `codegraph sync`는 변경된 파일만
   재인덱스하지만, 매번 브랜치를 갈아끼우면 diff가 커져 sync 비용 폭증.

해결: **agent별 worktree 1개 고정**, **작업마다 그 worktree 안에서 브랜치만
새로** 딴다. 각 worktree는 자기 `.venv` / `.codegraph/` / IDE state를 갖는다.

## 2. 워크트리 명명 규약

| AI 에이전트 | worktree 디렉토리 이름 |
|------------|----------------------|
| ChatGPT Codex | `geo-codex` |
| Claude Code (본 SDK 포함) | `geo-claude` |
| Google Antigravity 2.0 | `geo-antigravity` |

`geo-*` 접두사는 본 저장소가 다루는 도메인(지리/지도)에서 따왔다. 형제
저장소(`python-kraddr-geo`, `python-knps-api` 등)도 동일 접두사를 사용한다.

워크트리 디렉토리는 메인 repo 디렉토리의 **형제**(sibling)로 생성한다. 본
저장소 표준 위치(`~/dev/python-krtour-map/`) 기준:

```
~/dev/
├── python-krtour-map/        # main (메인 작업 디렉토리, 'main' 브랜치)
├── python-krtour-map-v1/     # 기존 v1 보존 worktree (참고용)
├── geo-codex/                # ChatGPT Codex 전용
├── geo-claude/                # Claude Code 전용
└── geo-antigravity/          # Google Antigravity 2.0 전용
```

NTFS에서 작업한다면 `F:\dev\` 하위에 동일 구조로 둔다(WSL ext4 우선 정책은
`docs/dev-environment.md` 참조 — agent worktree도 ext4 base 권장).

## 3. 최초 setup (worktree마다 1회)

```bash
# 1) 메인 repo 디렉토리로 이동
cd ~/dev/python-krtour-map

# 2) 자기 agent에 해당하는 worktree 생성 (예: Claude Code)
git fetch
git worktree add ../geo-claude main

# 3) worktree로 들어가서 venv + 의존성 셋업
cd ../geo-claude
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"

# 4) codegraph CLI 전역 설치 — npm 글로벌 (어느 OS든 동일하게 동작)
npm i -g @colbymchenry/codegraph

# 5) worktree 안에서 codegraph 인덱스 최초 생성 + 초기 인덱싱
codegraph init -i

# 6) (선택) AI 에이전트(Claude Code / Codex CLI / Cursor / opencode / Hermes)에
#     codegraph MCP 서버 연결. 글로벌·자동 감지 모드:
codegraph install --yes
#   또는 특정 에이전트 + 로컬 (현 worktree에만) 설정:
#   codegraph install --target claude-code --location local
```

`codegraph init -i`는 다음을 수행한다:
- `.codegraph/` 디렉토리 생성 + `codegraph.db` (SQLite + FTS5) 초기 인덱스 빌드
- `-i` 플래그가 없으면 인덱스 빌드는 생략, 디렉토리만 생성

`codegraph install`은 별도 단계다 — 설치된 에이전트의 MCP 설정(Claude Code의
경우 `~/.claude.json` 또는 worktree 로컬 `.claude/`)에 codegraph 서버 등록을
추가한다. **에이전트마다 1회**만 하면 된다(글로벌 설치 시).

`.codegraph/` 디렉토리는 `.gitignore`에 박혀 있다(본 저장소 `.gitignore` 참조).
**커밋하지 않는다**. 각 worktree가 자기 인덱스를 갖는다.

## 4. 작업 사이클 (PR 1건마다)

```bash
# 0) 자기 worktree에 들어와 있다고 가정 (Claude는 ~/dev/geo-claude/)
cd ~/dev/geo-claude

# 1) 최신 main 동기
git fetch
git switch main
git pull --ff-only

# 2) 새 작업 브랜치
git switch -c feat/<topic> main
#   브랜치 명명은 AGENTS.md DO NOT #17 참조:
#   feat/<topic> / fix/<topic> / chore/<topic> / docs/<topic> /
#   refactor/<topic> / adr/<short>

# 3) codegraph 인덱스 동기 (재초기화 X, 증분 sync)
codegraph sync

# 4) <작업 / 코드 작성 / 테스트>
pytest -q
ruff check .
mypy --strict src/krtour/map
lint-imports

# 5) commit + PR
git add -A
git commit -m "..."
git push -u origin feat/<topic>
gh pr create --title "..." --body "..."

# 6) PR 머지 후 다음 작업: 위 1)부터 반복.
#    .codegraph/는 그대로 둔다 — codegraph sync로만 따라잡는다.
```

**Key point**: `.codegraph/`는 worktree마다 **딱 한 번** 만들고, 이후에는
`codegraph sync`로만 따라잡는다. **다시 `codegraph init`을 돌리지 않는다**
(시간 + 디스크 낭비).

예외: `.codegraph/codegraph.db`가 손상됐거나(드물게 발생), 인덱스 스키마가
업데이트된 codegraph CLI 새 버전과 호환 안 되면, `.codegraph/` 통째로 지우고
`codegraph init -i` 다시.

## 5. codegraph 자주 쓰는 커맨드

```bash
# 인덱스 상태 확인
codegraph status

# 증분 동기 (브랜치 전환/pull 직후)
codegraph sync

# 전체 재인덱스 (드물게 — DB 손상 시)
codegraph index

# 심볼 쿼리 (AI 에이전트가 자동 호출)
codegraph query "Feature DTO"

# 어디서 부르는지 / 누가 부르는지
codegraph callers normalize_provider_name
codegraph callees score_pair

# 변경 영향 분석
codegraph impact src/krtour/map/dto/feature.py
```

본 라이브러리에서 자주 쓸 쿼리 예시는 `SKILL.md` §"자주 묻는 작업"의
"새 provider 추가" 행을 참조.

## 6. CI / 빌드와의 관계

- `.codegraph/`는 **로컬 전용**. CI(`.github/workflows/`)에서 codegraph를
  돌리지 않는다.
- import-linter / pytest / ruff / mypy는 codegraph와 무관하게 그대로 돈다.
- codegraph는 **에이전트의 컨텍스트 절약용 도구**이지 검증 도구가 아니다.

## 7. WSL ext4 + NTFS data와의 호환

`docs/dev-environment.md` §"파일 위치 정책"과 동일 정책:

- **worktree 본체** (코드/`.venv`/`.codegraph/`): WSL ext4 (`~/dev/geo-*`).
- **data/ symlink**: 각 worktree에서도 NTFS의 `data/`로 심볼릭 링크.
  ```bash
  cd ~/dev/geo-claude
  ln -s /mnt/f/dev/python-krtour-map/data data
  ```

`.codegraph/`는 SQLite 파일이므로 ext4 권장(NTFS에서 직접 운영하면 락/inotify
문제).

## 8. 사용자가 직접 작업할 때

사용자가 직접 (AI 에이전트 거치지 않고) 작업하는 경우는 메인 worktree
(`~/dev/python-krtour-map/`)를 그대로 쓴다. `geo-*` worktree는 **각 AI
에이전트의 sandbox** — 사용자가 그 안에 들어가서 직접 수정하면 에이전트의
context와 충돌하므로 피한다.

## 9. 참고

- [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph) — 본
  도구 공식 저장소
- [git worktree 공식 문서](https://git-scm.com/docs/git-worktree)
- `docs/dev-environment.md` — WSL ext4 + NTFS data 정책 본문
- `AGENTS.md` §"에이전트 worktree + codegraph" — 1쪽 요약
