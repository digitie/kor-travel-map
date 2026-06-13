# agent-failure-patterns — 반복 실패 패턴과 회피·복구

본 repo에서 AI 에이전트가 **실제로 반복한** 실패와 그 회피/복구법. 모든 에이전트
(Claude/Codex/Antigravity) 공용 — 새 세션이 같은 함정을 다시 밟지 않게 한다.
출처: 세션 transcript + `MEMORY.md`(WSL venv, Playwright e2e) + PR 회고.

> 사용법: 게이트가 깨지거나 이상하면 먼저 여기서 증상을 찾는다. 각 항목은
> **증상 → 원인 → 회피/복구**.

## A. CI ↔ 로컬 괴리

### A1 — 로컬 mypy/pytest green인데 CI lint red

- **증상**: WSL에서 4 게이트 통과했는데 CI `lint`(mypy --strict)만 red.
- **원인**: WSL 테스트 venv에는 debug-ui 설치(`pip install -e packages/...`)로 들어온
  **전이 의존성**(`httpx`/`alembic` 등)이 깔려 있다. CI lint는 `pip install -e ".[dev]"`
  만 하므로, 메인 패키지가 TYPE_CHECKING-only로 쓰는 stub 패키지가 `[dev]`에 없으면
  로컬은 통과·CI는 실패. (PR#113에서 httpx를 `[dev]`에 추가해 해결.)
- **회피/복구**: 새 `TYPE_CHECKING` import를 추가하면 그 stub을 `[dev]` extra에도
  넣었는지 확인. lint 의심 시 로컬을 믿지 말고 `gh run view <id> --log-failed`로
  실제 step 확인. (`MEMORY.md` wsl-test-venv-masks-dev-extras.)

### A2 — 돌리지 않은 게이트 결과를 보고

- **증상**: "테스트 통과"라고 적었는데 실제로는 실행이 취소/뒤섞여 안 돌았음.
- **원인**: 한 메시지에서 병렬 tool 호출이 취소되거나 출력이 섞일 수 있다.
- **회피**: 검증 명령은 **한 번에 하나씩**, 결과를 실제로 읽고 나서 보고. 길거나
  불안하면 결과를 파일로 남겨 Read로 확인. **안 본 수치는 적지 않는다** — 커밋/PR
  본문 수치는 전부 실측만.

### A3 — Python 버전별 CI 실패 (3.11 only 등)

- **증상**: 로컬(3.12) green, CI `pytest (3.11)`만 red.
- **원인**: 버전 한정 API 사용. 실제 사례: `typing.Protocol.__protocol_attrs__`는
  **3.12+ 전용** — 3.11엔 없어 AttributeError.
- **회피**: 버전 비의존 코드. Protocol 멤버 열거가 필요하면 `__protocol_attrs__`
  대신 **명시 필드 집합**을 쓴다. CI는 3.11/3.12/3.13 모두 green 확인 후 머지.

### A4 — OpenAPI drift 게이트 red (debug-ui 라우터 변경)

- **증상**: 라우터/DTO 추가 후 CI `openapi-drift` red.
- **회피/복구**:
  `python packages/kor-travel-map-api/scripts/export_openapi.py --profile all`로
  `openapi.json`/`openapi.user.json`을 재생성 →
  `python packages/kor-travel-map-api/scripts/export_openapi.py --profile all --check`로
  EXIT=0 확인 → **재생성본을 NTFS로 복사**해 커밋. WSL에서 재생성했으면 그 파일을
  NTFS로 cp 해야 커밋에 들어간다.

## B. Git / worktree / 브랜치

### B1 — `sandbox/<agent>`에 직접 커밋해 버림

- **증상**: feature 브랜치를 안 만들고 작업 → 커밋이 `sandbox/<agent>`에 얹힘.
- **복구**(force-push 불필요): 커밋을 feature 브랜치로 옮기고 sandbox를 되돌린다.
  ```
  git branch feat/<topic>            # 현재 HEAD(커밋 포함)에 브랜치 생성
  git reset --hard origin/main       # sandbox/<agent>를 main으로 되돌림
  git switch feat/<topic>
  git push -u origin feat/<topic>
  ```
- **회피**: 작업 시작 시 `git switch -c feat/<topic> main` 먼저.

### B2 — WSL 미러가 main보다 뒤처짐

- **증상**: WSL `~/dev/kor-travel-map` HEAD가 머지된 main보다 옛 커밋.
- **복구**: `cd ~/dev/kor-travel-map && git fetch origin && git reset --hard
  origin/main`. WSL은 실행 샌드박스라 hard reset 안전(원본은 NTFS).

### B3 — 무관 파일이 커밋에 섞임

- **증상**: `claude.json` 등 세션 파일이 staged.
- **회피**: `git add`에 **관련 파일만 명시**(`git add -A` 지양). 커밋 전 `git status -sb`
  확인.

### B4 — Windows Git rebase/merge continue가 Vim을 열고 멈춤

- **증상**: WSL 비대화 세션에서 `git.exe ... rebase --continue` 또는
  `merge --continue` 실행 후 `Vim: Warning: Output is not to a terminal` 메시지가
  나오고 프로세스가 대기한다.
- **원인**: Windows Git의 editor 설정이 비대화 환경에서도 실행된다. 단순
  `GIT_EDITOR=true git.exe ...`는 Windows Git/셸 경계에서 기대대로 적용되지 않을 수
  있다.
- **회피**: continue류 명령은 처음부터 editor를 명령 단위로 우회한다.
  ```
  git.exe -C F:/dev/kor-travel-map-codex -c core.editor=true rebase --continue
  git.exe -C F:/dev/kor-travel-map-codex -c core.editor=true merge --continue
  ```
- **복구**: 이미 멈췄으면 해당 `git.exe ... rebase --continue` 프로세스를 종료한 뒤
  위 명령으로 재실행한다.
  ```
  ps -ef | rg "git.exe .*rebase --continue|git.exe .*merge --continue"
  kill <pid>
  git.exe -C F:/dev/kor-travel-map-codex -c core.editor=true rebase --continue
  ```
- **원칙**: AI agent는 rebase/merge continue에서 항상 `-c core.editor=true`를 붙인다.
  커밋 메시지를 바꿀 필요가 없으면 `commit --amend --no-edit`,
  `merge --no-edit`처럼 non-interactive 옵션을 우선한다.

## C. 도메인 계약 (자연키 / 스키마 / upstream)

### C1 — 자연키에 `|` 사용 → make_feature_id 거부

- **증상**: `make_feature_id`/`make_source_record_key`가 `|` 포함 성분을 거부.
- **회피**: 자연키 구분자는 **`::`**(ADR-009). 예: `{slug}::{mng_no}`,
  `{alert_id}::{region}`. provider 라이브 테스트의 합성 키도 `::`.

### C2 — raw SQL에서 스키마 미한정

- **증상**: `relation "features" does not exist`.
- **원인**: 테이블은 스키마에 격리됨(ADR-008). raw SQL은 스키마 한정 필요:
  `feature.features`, `provider_sync.{source_records,source_links,provider_sync_state}`,
  `ops.{dedup_review_queue,import_jobs,feature_merge_history,feature_consistency_reports}`.
- **참고**: ORM(`FeatureRow`)은 스키마 인지하지만 `text()` 쿼리는 직접 써야 함.

### C3 — `source_role` / `status` CHECK 위반

- **증상**: `violates check constraint "ck_source_links_..."` 등.
- **회피**: `source_role`는 `primary/base_address/base_coordinate/enrichment/correction/
  duplicate_candidate/media/weather_context`만(‘secondary’ 없음). feature `status`는
  `draft/active/inactive/hidden/broken/deleted`. dedup queue status는
  `pending/accepted/rejected/merged/ignored`.

### C4 — upstream provider 필드 drift (본 lib 책임 아님)

- **증상**: provider 라이브러리 파싱 에러(예: krex `restAreaNm/serviceAreaName is
  required` — data.go.kr이 `entrpsNm`으로 rename).
- **분계(ADR-044)**: 데이터 정합성 1차 책임은 **각 provider 라이브러리**. 본 lib는
  신뢰·미러하고, 불일치 시 그 라이브러리를 고친다(필요 시 upstream PR) — 본 lib에
  방어 코드를 넣지 않는다. 로컬 체크아웃이 뒤처졌으면 `git -C F:\dev\python-<p>-api
  pull`부터.

### C5 — 증분(Step B)에서 snapshot prune 하면 오삭제

- **증상**: 증분 적재가 "사라진" record를 비활성화 → 멀쩡한 feature 삭제.
- **원인**: 증분은 전체 snapshot이 아니라 delta. Step A(bulk)만 prune한다. 폐업은
  Step C(closed)의 책임. 증분 loader는 upsert만.

## D. Python / 타입 / 테스트 함정

### D1 — `normalize_phone_number`는 무효 입력에 원본 반환

- **증상**: 쓰레기 전화번호가 `None`이 아니라 그대로 통과.
- **원인**: 정규화는 provenance 보존용이라 숫자 부족 시 원본을 돌려줌(None 아님).
- **회피**: 품질이 필요한 경로(enrichment)는 **자릿수≥9** 등 자체 검증 추가.

### D2 — `runtime_checkable` Protocol isinstance가 불안정

- **증상**: 모든 멤버 `hasattr`=True인데 `isinstance(obj, SomeProtocol)`=False.
- **원인**: Protocol이 `@property`와 일반 method를 섞어 선언 + 대상이 `__getattr__`
  동적 객체일 때 isinstance 결과가 신뢰 불가.
- **회피**: 변환 코드는 isinstance가 아니라 **attribute 접근**으로 duck-type. 테스트도
  isinstance 대신 대표 필드 접근으로.

### D3 — `Result.rowcount` mypy --strict 에러

- **증상**: `"Result[Any]" has no attribute "rowcount"`.
- **회피**: 코드베이스 컨벤션 — UPDATE/DELETE에 `RETURNING <id>` 붙이고
  `len(result.fetchall())`(또는 `bool(result.fetchall())`)로 영향 행 카운트.

### D4 — commit하는 테스트가 다른 테스트를 오염

- **증상**: 단독 실행은 green, 전체 실행 시 fail(예상 0건인데 이전 테스트가 남긴 행).
- **원인**: `migrated_session`은 rollback 격리지만, **CLI/엔진을 직접 만드는 테스트는
  commit**한다 → 행이 잔존.
- **회피**: commit하는 테스트는 teardown에서 관련 테이블 `TRUNCATE ... RESTART
  IDENTITY CASCADE`. 새 테이블 적재 시 TRUNCATE 목록에 **추가**(예: cursor 테스트면
  `provider_sync.provider_sync_state`도).

### D5 — ruff E501: CJK(한글) 폭

- **증상**: 한글 포함 라인이 100자 이하로 보이는데 E501.
- **회피**: 한글 라인은 더 짧게. 긴 type alias 주석은 추론에 맡겨 제거. 자동수정
  가능한 건 `ruff check --fix`(WSL) 후 NTFS로 동기.

### D6 — `from __future__ import annotations`와 forward-ref

- module-level 변수 주석도 PEP 563로 지연 평가되므로, 뒤에 정의된 타입을 따옴표 없이
  참조해도 된다(ruff UP037이 따옴표 제거 요구). 단 런타임에 그 주석을 evaluate하는
  코드가 없을 때만.

## E. 검증 우선순위 (요약)

1. 게이트는 **WSL에서 실제로** 돌린다(로컬 green ≠ CI, §A1).
2. 결과는 **읽고 나서** 보고한다(§A2).
3. 머지 전 CI **3 버전** green(§A3) + drift(§A4).
4. provider 데이터 이슈는 **그 provider 라이브러리**에서 고친다(§C4).

## F. Admin frontend 실행 함정 (WSL Node / Next.js / Playwright)

### F1 — WSL 셸에서 Windows `npm`을 잡음

- **증상**: "WSL에서 실행"했는데 프로세스가 `/mnt/c/Program Files/nodejs/npm` 또는
  Windows `node.exe`로 떠 있다. `next dev`가 Ready를 찍어도 WSL `ss -ltnp`에
  `:12305` listener가 없다.
- **원인**: 비대화 WSL 셸이 nvm을 source하지 않아 `node`는 없고 Windows `npm`만
  PATH에 남아 있다.
- **회피**: frontend 명령 전 반드시 확인한다.
  ```bash
  command -v node
  command -v npm
  ```
  두 경로 모두 `/home/.../.nvm/...` 같은 **WSL 경로**여야 한다.
  `/mnt/c/Program Files/nodejs/...`가 나오면 즉시 중단하고 WSL Node를 활성화한다.
  ```bash
  export NVM_DIR="$HOME/.nvm"
  . "$NVM_DIR/nvm.sh"
  nvm use 20.20.2
  hash -r
  command -v node npm
  ```

### F2 — Windows npm으로 만든 `node_modules` 때문에 Linux optional native package 누락

- **증상**: WSL Node로 `next build` 시 `Cannot find module
  '../lightningcss.linux-x64-gnu.node'` 또는 `@next/swc` 계열 Linux native binary
  누락 에러.
- **원인**: Windows npm 실행으로 `lightningcss-win32-x64-msvc` 같은 Windows optional
  dependency만 설치되어 있고, WSL/Linux optional dependency가 없다.
- **복구**: WSL Node가 활성화된 상태에서 install을 다시 수행한다.
  ```bash
  export NVM_DIR="$HOME/.nvm"
  . "$NVM_DIR/nvm.sh"
  nvm use 20.20.2
  npm install -w packages/kor-travel-map-admin/frontend --include=optional
  npm -w packages/kor-travel-map-admin/frontend run build
  ```
  그래도 native package가 계속 꼬이면 ignored artifact인 `node_modules/`를 WSL에서
  지우고 WSL npm으로 다시 설치한다. Windows npm으로 frontend 서버를 실행하지 않는다.

### F3 — `npm run dev`의 hardcoded hostname과 `0.0.0.0` 요청 혼동

- **증상**: 사용자가 `0.0.0.0` 바인드를 요구했는데 `npm run dev` 기본 script
  (`--hostname 127.0.0.1`)를 그대로 실행한다.
- **회피**: `0.0.0.0`이 필요하면 script에 인자를 덧붙여 중복 hostname을 만들지 말고,
  WSL Node 활성화 후 Next.js를 명시적으로 실행한다.
  ```bash
  cd packages/kor-travel-map-admin/frontend
  npx next dev --port 12305 --hostname 0.0.0.0
  ```
  production 확인은 다음처럼 한다.
  ```bash
  npx next start --port 12305 --hostname 0.0.0.0
  ```

### F4 — `env PATH=...$PATH`가 Windows 경로 공백에서 깨짐

- **증상**: `env: ‘Files’: No such file or directory`.
- **원인**: `$PATH` 안의 `/mnt/c/Program Files/...`가 unquoted `env PATH=...$PATH`
  인자에서 공백 기준으로 쪼개진다.
- **회피**: Windows PATH를 섞지 말고 WSL 최소 PATH를 명시하거나, nvm을 source하는
  `bash -lc`를 사용한다.
  ```bash
  REPO="/mnt/f/dev/kor-travel-map-codex"  # 자기 에이전트 worktree 경로로 교체
  export REPO
  setsid -f bash -lc '
    cd "$REPO/packages/kor-travel-map-admin/frontend"
    export NVM_DIR="$HOME/.nvm"
    . "$NVM_DIR/nvm.sh"
    nvm use 20.20.2 >/dev/null
    exec npx next dev --port 12305 --hostname 0.0.0.0
  ' > "$REPO/.codex_tmp/kor-travel-map-admin-frontend.log" 2>&1
  ```

### F5 — workspace binary 위치 오판

- **증상**: `env: ‘./node_modules/.bin/next’: No such file or directory`.
- **원인**: npm workspace가 의존성을 루트 `node_modules`로 hoist한다. frontend
  패키지 내부 `node_modules/.bin/next`가 없을 수 있다.
- **회피**: frontend 디렉토리에서 `npx next ...`를 쓰거나, 루트 binary를 쓴다.
  ```bash
  cd packages/kor-travel-map-admin/frontend
  npx next dev --port 12305 --hostname 0.0.0.0
  # 또는
  "$(git rev-parse --show-toplevel)/node_modules/.bin/next" dev --port 12305 --hostname 0.0.0.0
  ```

### F6 — `.next/dev/lock` 권한 에러를 반복 재시도

- **증상**: `An IO error occurred while attempting to create and acquire the
  lockfile`, `Permission denied (os error 13)`.
- **원인**: 이전 Next dev/build artifact가 NTFS 위 `.next/dev/lock`에 남아 있거나
  Windows/WSL Node 실행이 섞였다.
- **복구**: 반복 재시도하지 말고 dev artifact를 먼저 지운다.
  ```bash
  rm -rf packages/kor-travel-map-admin/frontend/.next
  ```
  그 다음 WSL Node 확인(F1) → Linux optional dependency 확인(F2) → 서버 기동(F3).

### F7 — `pkill -f`가 자기 셸까지 죽임

- **증상**: `pkill -f 'next dev --port 12305'`를 포함한 명령 자체가 종료되고 이후
  명령이 실행되지 않는다.
- **원인**: `pkill -f`가 현재 shell command line까지 pattern match한다.
- **회피/복구**: 먼저 port listener PID를 확인하고 정확한 PID만 kill한다.
  ```bash
  ss -ltnp | rg ':(12301|12305)\b'
  kill <pid>
  ```
  또는 log/PID 파일을 남긴 경우 그 PID만 종료한다. broad `pkill -f`는 마지막
  수단으로만, 현재 명령줄에 같은 pattern이 들어가지 않게 분리해 실행한다.

### F8 — 백그라운드 서버 기동 후 검증 없이 보고

- **증상**: PID를 출력했지만 실제로 listener가 없거나 프로세스가 바로 종료됨.
- **회피**: 서버 기동 보고 전 항상 세 가지를 확인한다.
  ```bash
  ss -ltnp | rg ':(12301|12305)\b'
  curl -fsS http://127.0.0.1:12301/debug/health
  curl -fsS -I http://127.0.0.1:12305/ | sed -n '1,8p'
  ```
  `Ready` 로그만 믿지 않는다. 실제 listener와 HTTP 200/health 응답을 확인한다.

### F9 — Playwright 실행 위치 혼동

- **증상**: WSL에서 `npm run e2e`를 돌리려 하거나, Windows에서 frontend 서버까지
  띄우려 한다.
- **정본**: 서버 2개는 WSL, Playwright Chromium만 Windows.
  - WSL: backend `:12301`, frontend `:12305`.
  - Windows PowerShell: `cd packages\kor-travel-map-admin\frontend; npm run e2e`.
  `playwright.config.ts`에는 `webServer`가 없으므로, Windows e2e 전 WSL 서버가 이미
  떠 있어야 한다.

### F10 — Windows stale Node가 `:12305`을 점유해 Playwright가 다른 서버를 봄

- **증상**: WSL에서 `curl http://127.0.0.1:12305/`는 200인데, Windows Playwright나
  Windows `curl.exe http://127.0.0.1:12305/`는 `Internal Server Error` 또는 이전
  빌드 화면을 본다. e2e가 `/`, `/etl`, `/features`에서 동시에 이상하게 실패한다.
- **원인**: 과거에 Windows Node(`C:\Program Files\nodejs\node.exe`)로 띄운 Next.js
  프로세스가 Windows `127.0.0.1:12305`을 직접 점유하고 있다. 이 경우 WSL
  `0.0.0.0:12305` 서버가 떠 있어도 Windows localhost-forwarding이 붙지 못한다.
- **확인**:
  ```bash
  cmd.exe /c "netstat -ano | findstr :12305"
  powershell.exe -NoProfile -Command "Get-Process -Id <PID> | Select-Object Id,ProcessName,Path"
  ```
  정상 forwarding이면 `ProcessName`이 `wslrelay`다. `node`이고 path가
  `C:\Program Files\nodejs\node.exe`면 stale Windows 서버다.
- **복구**:
  ```bash
  powershell.exe -NoProfile -Command "Stop-Process -Id <PID> -Force"
  # 그 다음 WSL에서 frontend를 다시 띄워 wslrelay를 새로 붙인다.
  ```
  이후 반드시 Windows에서 직접 확인한다.
  ```bash
  cmd.exe /c "curl.exe -sS -D - http://127.0.0.1:12305/ -o NUL"
  ```
  Windows `curl.exe`가 200을 보기 전에는 e2e를 돌리지 않는다.
