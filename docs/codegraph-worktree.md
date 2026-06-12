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
| ChatGPT Codex | `python-krtour-map-codex` |
| Claude Code (본 SDK 포함) | `python-krtour-map-claude` |
| Google Antigravity 2.0 | `python-krtour-map-antigravity` |

`python-krtour-map-` 접두사는 본 저장소(`python-krtour-map`) 이름에서 따왔다 — 한 머신에서 여러 저장소의 worktree가 `F:\dev\` 아래 공존할 때 어느 저장소의 worktree인지 1:1로 식별하기 위함. (이전엔 `krtour-map-*`을 썼으나 통일성을 위해 `python-krtour-map-*`로 프리픽스를 일치시켰다.)

워크트리 디렉토리는 메인 repo 디렉토리의 **형제**(sibling)로 생성한다. 본 저장소 표준 위치(`F:\dev\python-krtour-map\`) 기준:

```
F:\dev\
├── python-krtour-map/            # main (메인 작업 디렉토리, 'main' 브랜치)
├── python-krtour-map-v1/         # 기존 v1 보존 worktree (참고용)
├── python-krtour-map-codex/      # ChatGPT Codex 전용
├── python-krtour-map-claude/     # Claude Code 전용
└── python-krtour-map-antigravity/ # Google Antigravity 2.0 전용
```

NTFS (`F:\dev\`) 하위에 동일 구조로 둔다. 메인 코드의 원본이 NTFS에 위치하고,
순수 Git을 제외한 실행은 WSL에서 `/mnt/f/dev/python-krtour-map-<agent>` 경로로
수행한다. WSL ext4 복사는 대량 I/O 성능·격리 필요 시에만 선택한다.

## 3. 최초 setup (worktree마다 1회)

```powershell
# Windows PowerShell에서 실행
# 1) 메인 repo 디렉토리로 이동
cd F:\dev\python-krtour-map

# 2) 자기 agent에 해당하는 worktree 생성 (예: Claude Code)
git fetch
git worktree add -b sandbox/claude ../python-krtour-map-claude main

# 3) 이후 Git 외 셋업은 WSL에서 실행
wsl
cd /mnt/f/dev/python-krtour-map-claude
uv venv --python 3.11
uv pip install -e ".[dev]"

# 4) codegraph CLI 전역 설치 — WSL npm 글로벌
npm i -g @colbymchenry/codegraph

# 5) worktree 안에서 codegraph 인덱스 최초 생성 + 초기 인덱싱
codegraph init -i

# 6) (선택) AI 에이전트에 codegraph MCP 서버 연결
codegraph install --yes
```

`codegraph init -i`는 다음을 수행한다:
- `.codegraph/` 디렉토리 생성 + `codegraph.db` (SQLite + FTS5) 초기 인덱스 빌드
- `-i` 플래그가 없으면 인덱스 빌드는 생략, 디렉토리만 생성

`codegraph install`은 별도 단계다 — 설치된 에이전트의 MCP 설정에 codegraph 서버 등록을 추가한다. **에이전트마다 1회**만 하면 된다(글로벌 설치 시).

`.codegraph/` 디렉토리는 `.gitignore`에 박혀 있다(본 저장소 `.gitignore` 참조). **커밋하지 않는다**. 각 worktree가 자기 인덱스를 갖는다.

## 4. 작업 사이클 (PR 1건마다)

```powershell
# 0) 자기 worktree에 들어와 있다고 가정 (Claude는 F:\dev\python-krtour-map-claude/)
cd F:\dev\python-krtour-map-claude

# 1) 최신 main 동기
git fetch
git switch main
git pull --ff-only

# 2) 새 작업 브랜치
git switch -c feat/<topic> main

# 3) codegraph 인덱스 동기 (재초기화 X, 증분 sync)
codegraph sync

# 4) <작업 / 코드 작성 / 테스트>는 WSL에서 실행
cd /mnt/f/dev/python-krtour-map-claude
uv run pytest tests/unit -q
uv run ruff check .
uv run mypy --strict src/krtour/map
```
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

## 5. CodeGraph Commands (CLI 빠른 참조)

```bash
# 인덱싱 초기화 (worktree마다 1회)
codegraph init -i

# 동기화 상태 확인 (Files / Nodes / Edges / DB Size / 최신 여부)
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

# 변경 영향 분석 (수정 전 영향도 평가에 사용 — §7 참조)
codegraph impact src/krtour/map/dto/feature.py

# AI 에이전트용 컨텍스트 빌드 (markdown 출력)
codegraph context "Add visitkorea festival provider"
```

본 라이브러리에서 자주 쓸 쿼리 예시는 `SKILL.md` §"자주 묻는 작업"의
"새 provider 추가" 행을 참조.

## 6. MCP 서버 등록 (AI 에이전트 통합)

codegraph는 MCP(Model Context Protocol) stdio 서버로도 동작한다. 본 PC의
`.claude.json`(Windows: `C:\Users\<user>\.claude.json`, Linux/macOS:
`~/.claude.json`)에 다음 블록을 추가하면 Claude Code 세션이 자동으로
codegraph MCP 도구(`codegraph_query`, `codegraph_callers`, `codegraph_explore`
등)를 인식한다.

### 6.1 권장 (codegraph CLI 글로벌 설치된 경우)

```json
{
  "mcpServers": {
    "codegraph": {
      "type": "stdio",
      "command": "codegraph",
      "args": ["serve", "--mcp"]
    }
  }
}
```

이 snippet은 `codegraph install --print-config claude`에서 출력되는 공식
형태와 동일하다. `codegraph install --yes`로 자동 등록할 수도 있다(`.claude
.json`을 직접 편집하는 대신).

### 6.2 대안 (`npx`로 매번 fetch — 글로벌 설치 회피)

`npm i -g`를 쓰고 싶지 않거나, 여러 PC에 빠르게 굴리고 싶을 때:

```json
{
  "mcpServers": {
    "codegraph": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@colbymchenry/codegraph", "serve", "--mcp"]
    }
  }
}
```

`npx -y`는 매 실행마다 캐시된 패키지를 쓰거나 없으면 fetch한다 — 첫 실행이
약간 느릴 수 있다. 글로벌 설치한 경우는 §6.1을 우선.

### 6.3 다른 에이전트 (Codex CLI / Cursor / opencode / Hermes)

`codegraph install --print-config <target>`으로 각 에이전트별 snippet을
얻는다. `<target>`은 `codex` / `cursor` / `opencode` / `hermes`. 또는
`codegraph install --target <id> --location global --yes`로 자동 등록.

### 6.4 WSL2 `/mnt` 위에서 운영할 때

WSL2가 `/mnt/f/`(NTFS)를 마운트한 경우 파일 시스템 watcher가 매우 느리다.
`--no-watch`를 추가해서 auto-sync를 끄고, 대신 `git switch`/`pull` 후
명시적으로 `codegraph sync`를 호출한다:

```json
"args": ["serve", "--mcp", "--no-watch"]
```

본 저장소 정책상 `.codegraph/`는 WSL ext4 또는 NTFS 네이티브(Windows
PowerShell 기준)에 두는 게 권장 — §8 참조.

### 6.5 Telegram 완료 알림 MCP

단위 작업 완료 시 사용자가 Telegram으로 짧은 요약과 PR 링크를 받을 수 있도록
각 agent worktree에 `mcp-telegram` MCP 서버를 등록한다. credential은 절대
tracked 설정이나 문서에 쓰지 않고, 각 worktree 루트의 로컬 파일
`.env.mcp-telegram`에만 둔다. 이 파일은 `.gitignore`의 `.env.*` 규칙으로
커밋되지 않는다.

설치:

```bash
# WSL/Codex 런타임
uv tool install mcp-telegram

# Windows MCP 클라이언트가 직접 실행할 수 있게 사용자 Python에도 설치
/mnt/c/Python314/python.exe -m pip install --user mcp-telegram
```

각 worktree 루트에 로컬 credential 파일을 만든다:

```dotenv
API_ID=<telegram-api-id>
API_HASH=<telegram-api-hash>
# 선택: 알림을 보낼 기본 chat/user/channel 식별자
# TELEGRAM_NOTIFY_CHAT=<chat-id-or-username>
```

최초 1회 Telegram 로그인은 인증번호/2FA 입력이 필요하므로 사람이 실행한다:

```bash
cd /mnt/f/dev/python-krtour-map-<agent>
python3 scripts/mcp_telegram_start.py login
```

Windows 셸에서 로그인할 때는 다음처럼 실행한다:

```powershell
cd F:\dev\python-krtour-map-<agent>
C:\Python314\python.exe scripts\mcp_telegram_start.py login
```

tracked MCP 설정 파일은 다음을 포함한다:

- `.codex/config.toml` — ChatGPT Codex, `cwd=F:\dev\python-krtour-map-codex`
- `claude.json` — Claude Code, `cwd=F:\dev\python-krtour-map-claude`
- `antigravity.json`, `.gemini/mcp.json` — Google Antigravity,
  `cwd=F:\dev\python-krtour-map-antigravity`

각 설정은 `scripts/mcp_telegram_start.py` wrapper를 실행한다. wrapper는 cwd의
`.env.mcp-telegram`을 읽은 뒤 `mcp-telegram start`를 stdio MCP 서버로 실행한다.
작업 PR을 만들고 나면 `mcp-telegram` MCP의 메시지 발송 도구로 다음 정보를 보낸다:

- 작업 제목/브랜치
- 완료 요약 2~4줄
- PR 링크
- 검증 결과 또는 아직 돌리지 못한 게이트

## 7. Code Style & Rules — 수정 전 영향도 평가

본 저장소는 **함수 라이브러리**라서 한 함수/DTO의 시그니처 변경이 호출자
여러 곳을 깨뜨릴 수 있다(특히 `Feature` DTO, `make_feature_id`, provider
변환 함수). 코드 컴포넌트를 수정하기 전에 **반드시** codegraph로 영향도를
먼저 평가한다:

- **MCP 환경 (Claude Code / Codex CLI 등)** — `codegraph_explore` MCP 도구를
  호출해서 대상 심볼의 호출자 / 의존 / 변경 영향을 한 번에 본다. 그
  결과를 바탕으로 PR 범위를 결정.
- **CLI 환경 (사람 직접 작업)** — `codegraph callers <symbol>` +
  `codegraph impact <file>` + `codegraph callees <symbol>` 조합으로
  같은 정보를 얻는다.

이 단계 없이 수정에 들어가면 import-linter 4 계약 위반 / 깨진 호출자 /
잊혀진 테스트 fixture 등이 PR 끝물에서 발견되어 비용이 폭증한다. **변경
이전 영향도 평가는 PR 절차의 일부**다(별도 lint 없이 에이전트가 자가
규율).

예외: 신규 파일만 추가하고 기존 심볼 시그니처가 그대로인 경우(예: 새
provider 변환 함수 추가 — `score_pair`/`make_feature_id` 시그니처 변경 X)
는 영향도 평가를 생략할 수 있다.

## 8. CI / 빌드와의 관계

- `.codegraph/`는 **로컬 전용**. CI(`.github/workflows/`)에서 codegraph를
  돌리지 않는다.
- import-linter / pytest / ruff / mypy는 codegraph와 무관하게 그대로 돈다.
- codegraph는 **에이전트의 컨텍스트 절약용 도구**이지 검증 도구가 아니다.

## 9. Windows Git + WSL 실행과의 호환

`docs/dev-environment.md` §"파일 위치 정책"과 동일 정책:

- **worktree 본체** (코드/`.codegraph/`): NTFS (`F:\dev\python-krtour-map-*`).
- **Git 외 실행**: WSL에서 `/mnt/f/dev/python-krtour-map-*` 경로를 직접 사용한다.
- **테스트 실행**: 기본은 `/mnt/f/...`에서 실행한다. WSL ext4 mirror는 대량 I/O
  성능·격리 필요 시에만 선택하며, `.codegraph/`는 동기화에서 제외한다.

## 10. 사용자가 직접 작업할 때

사용자가 직접 (AI 에이전트 거치지 않고) 작업하는 경우는 메인 worktree
(`F:\dev\python-krtour-map\`)를 그대로 쓴다. `python-krtour-map-*` worktree는 **각 AI
에이전트의 sandbox** — 사용자가 그 안에 들어가서 직접 수정하면 에이전트의
context와 충돌하므로 피한다.

## 11. 참고

- [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph) — 본
  도구 공식 저장소
- [git worktree 공식 문서](https://git-scm.com/docs/git-worktree)
- `docs/dev-environment.md` — Windows Git + WSL 실행 정책 본문
- `AGENTS.md` §"에이전트 worktree + codegraph" — 1쪽 요약
