# AGENTS.md

> 본 파일은 **OpenAI Codex / Google Antigravity** 등 `AGENTS.md` 컨벤션을
> 따르는 AI agent의 표준 entry다. Claude Code는 별도 `CLAUDE.md` (1쪽 요약)
> 가 있으나 정식 정책·결정은 본 파일·`SKILL.md`·`docs/decisions.md`가 갖는다.

## 문서 언어 정책

이 저장소의 모든 Markdown/RST 문서는 한국어로 작성한다. 공식 API 필드명, 코드 식별자,
명령어, URL, 라이브러리·제공자 원문, 환경변수처럼 그대로 보존해야 하는 값만 영어를
유지한다. 신규 문서와 기존 문서 모두 동일 규칙을 우선한다.

## 역할

이 저장소(GitHub 이름 `python-krtour-map`, Python 패키지 `krtour.map` — ADR-022)는 여러 한국
공공 API 라이브러리(`python-*-api`)에서 올라오는 여행 지도 데이터를 단일 `Feature`
계약으로 정규화·저장·조회·수정·삭제할 수 있게 하는 **krtour-map 독립 프로그램 +
내부 Python 라이브러리**다.

ADR-045(2026-06-01) 이후 운영 모델은 **Docker 독립 프로그램 + 독립 DB/Dagster +
TripMate OpenAPI 연동**이다. TripMate는 krtour-map DB에 직접 접근하지 않고,
`python-krtour-map`을 운영 코드에서 직접 import하지 않는다. TripMate ↔ krtour-map
사이는 OpenAPI 기반 HTTP 계약으로 연결한다.

디버그 UI/REST는 **별도 Python 패키지** `krtour-map-admin`로 분리되어 있다
(ADR-020/035/045). 본 monorepo 안의 `packages/krtour-map-admin/`에 위치하고,
메인 라이브러리를 import해서 API/Dagster 내부에서 `AsyncKrtourMapClient`를 호출한다.
별도 인증 키를 요구하지 않는다(내부망 전용, ADR-005).

이전(v1) 구현은 `v1` 브랜치에 보존되어 있다. master(main)는 v2 사양으로 처음부터
다시 구현한다(ADR-001).

## 식별자 (혼동 방지)

| 항목 | 값 |
|------|----|
| GitHub 저장소 이름 | `python-krtour-map` |
| PyPI distribution | `python-krtour-map` |
| Python import (메인) | `from krtour.map import ...` (ADR-022, PEP 420 implicit namespace `krtour`) |
| Python import (디버그 UI) | `from krtour.map_admin import ...` (별도 distribution, 같은 `krtour` namespace) |
| CLI 명령 (있다면) | `krtour-map ...` |
| 환경변수 prefix | `KRTOUR_MAP_*` (env는 underscore 표준 유지) |
| PostgreSQL DB 이름 (개발/운영 기본) | `krtour_map` (ADR-045 — TripMate 공유 DB 아님) |
| Dagster metadata DB 기본 | `krtour_map_dagster` |
| Postgres schema | `feature`, `provider_sync`, `ops` (krtour-map 내부 schema 분리) |
| PostGIS extension schema | `x_extension` (ADR-008) |
| 디버그 UI 패키지 | `krtour-map-admin` (별도 **Python** 패키지, monorepo 내 `packages/krtour-map-admin/`, ADR-020) |
| Category 모듈 출처 | `krtour.map.category` (구 `kraddr.base.categories`에서 이전, ADR-023) |
| Address DTO + 행정코드 utility | `krtour.map.dto.Address` + `krtour.map.core.address` (구 `kraddr.base`에서 흡수, ADR-041 — `PlaceCoordinate`는 제외, 좌표는 `Coordinate`로 단일화) |
| Provider 라이브러리 git URL/sha 핀 status | `docs/provider-contract.md` §12 표 (Sprint별 그룹화, kma/datagokr는 Protocol 박힘) |
| ADR accepted | 001~047 전부 (text on main). 029는 ADR-043으로 supersede. ADR-045는 Docker 독립 프로그램 + OpenAPI 연동으로 ADR-003 운영 모델을 supersede. ADR-046은 ADR-045 이행 시 구 모델 호환 shim 금지. ADR-047은 standalone 고정 포트(API 9011, admin UI 9012, Dagster 9013). |
| ADR proposed | (없음) — 다음 후보 번호는 ADR-048. |
| Sprint plan | `docs/sprints/SPRINT-1.md` ~ `SPRINT-5.md` |
| Provider 구현 순서 (ADR-034) | 축제→날씨→유가→휴게소→국립공원/트래킹→국가유산→**MOIS**→휴양림/수목원→박물관/미술관 |

## 개발 환경 정책 (PC, WSL)

PC 개발은 **NTFS (`F:\dev\python-krtour-map`)** 위에서 수행한다. 모든 코드 수정과 git 관리는 NTFS에서 이루어지며, 테스트 및 실행이 필요할 때만 WSL ext4(`~/sandbox/python-krtour-map/` 등)로 복사하여 구동하는 정책을 따른다. 형제 라이브러리 (`python-kraddr-geo` / `python-kraddr-base` / `python-knps-api` 등)와 **동일 정책**.

- **코드/가상환경**: NTFS (`F:\dev\python-krtour-map/`).
- **데이터(`data/`)**: NTFS의 프로젝트 디렉토리 (`F:\dev\python-krtour-map\data\`).
- **테스트**: 테스트 수행 시 WSL 내의 ext4 디렉토리로 소스코드를 복사하여 WSL 및 Docker 환경에서 통합 테스트(PostGIS)를 구동한다. **단, 디버그 UI Playwright e2e는 서버(backend `:9011` + frontend `:9012`)만 WSL에 띄우고 Playwright(chromium)는 Windows 호스트에서 실행한다** — WSL에 chromium system lib(`libasound.so.2` 등)가 없고 sudo가 비밀번호를 요구해 자동 설치가 불가하기 때문. 자세히는 `docs/dev-environment.md` §8.1 + `packages/krtour-map-admin/frontend/README.md` §"e2e (Playwright)".
- **카피 정책**: 테스트 실행 및 배포 전 NTFS -> WSL ext4로 rsync 하여 동기화한다. Git의 source of truth는 NTFS다.

자세한 절차는 `docs/dev-environment.md`. Windows 재설치/WSL 초기화/새 세션 인수인계
시 `docs/windows-reinstall-recovery.md`도 함께 읽는다.

## 에이전트 공용 runbook (필독)

`docs/runbooks/` — Claude/Codex/Antigravity가 **공유**하는 운영 runbook. 작업 전
두 개는 훑는다:

- `docs/runbooks/agent-workflow.md` — 표준 1-PR 흐름(worktree → 브랜치 → NTFS 편집 →
  WSL 4 게이트 → PR → CI green → 머지 → 동기화) + 갱신 필수 문서.
- `docs/runbooks/agent-failure-patterns.md` — 본 repo 반복 실패 패턴(CI/로컬 괴리,
  자연키 `::`, 스키마 한정, upstream drift, 테스트 격리 등)과 회피·복구. 게이트가
  깨지면 여기부터.

인덱스: `docs/runbooks/README.md`. 환경 1차 문서는 `docs/dev-environment.md` /
`docs/codegraph-worktree.md` / `docs/agent-guide.md`.

## 에이전트 worktree + codegraph (필수)

여러 AI 에이전트가 동시에 한 저장소에서 일할 때 발생하는 브랜치 컨텍스트
충돌·캐시 무효화·codegraph 인덱스 sync 비용 문제를 막기 위해, 각 AI
에이전트는 **자기 전용 git worktree** + **로컬 codegraph 인덱스 1개**를
가진다. 자세히는 `docs/codegraph-worktree.md`.

| AI 에이전트 | 고정 worktree 디렉토리 |
|------------|----------------------|
| ChatGPT Codex | `F:\dev\python-krtour-map-codex` |
| Claude Code (본 SDK 포함) | `F:\dev\python-krtour-map-claude` |
| Google Antigravity 2.0 | `F:\dev\python-krtour-map-antigravity` |

운영 룰:

- 메인 repo 디렉토리(`F:\dev\python-krtour-map\`)의 **형제로** worktree 생성:
  `git worktree add -b sandbox/claude ../python-krtour-map-claude main`.
- 작업마다 **그 worktree 안에서 브랜치만 새로** 딴다 — worktree 자체는
  고정. `git switch -c feat/<topic> main`.
- 각 worktree에 [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)
  인덱스가 **딱 1번** 만들어진다 (`codegraph init -i`). 이후 브랜치/pull
  후에는 **재초기화 대신 `codegraph sync`로 증분 동기**.
- `.codegraph/` 디렉토리는 `.gitignore`에 박혀 있다 — 커밋하지 않는다.
- CI는 codegraph를 돌리지 않는다(에이전트 컨텍스트 절약용 도구).

작업 사이클(PR 1건):

```bash
git.exe -C F:/dev/python-krtour-map-claude fetch
git.exe -C F:/dev/python-krtour-map-claude switch main
git.exe -C F:/dev/python-krtour-map-claude pull --ff-only
git.exe -C F:/dev/python-krtour-map-claude switch -c feat/<topic> main
codegraph sync              # 인덱스 증분 동기 (init 아님)
# ... 작업 / 필요 시 NTFS -> WSL rsync 후 pytest / ruff / mypy / lint-imports ...
git.exe -C F:/dev/python-krtour-map-claude push -u origin feat/<topic>
gh pr create --title "..." --body "..."
```

최초 설치(worktree마다 1회):

```bash
npm i -g @colbymchenry/codegraph   # CLI 전역 (어느 OS든 동일)
cd /mnt/f/dev/python-krtour-map-<agent>
codegraph init -i                   # .codegraph/ + SQLite 인덱스 생성
codegraph install --yes             # (선택) MCP 서버를 자기 AI 에이전트에 등록
```

자주 쓰는 커맨드 (`docs/codegraph-worktree.md` §5에 전체):

- `codegraph init -i` — 인덱싱 초기화 (worktree마다 1회)
- `codegraph status` — 동기화 상태 확인
- `codegraph sync` — 브랜치 전환/pull 후 증분 동기
- `codegraph impact <file>` / `callers <sym>` / `callees <sym>` — 영향도

### MCP 서버 등록 (`.claude.json` 등)

`codegraph install --yes`로 자동 등록하거나, 수동으로 `~/.claude.json` (Linux/
macOS) / `C:\Users\<user>\.claude.json` (Windows)의 `mcpServers`에 다음 블록을
추가:

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

`codegraph` 글로벌 설치를 회피하려면 `npx -y @colbymchenry/codegraph serve
--mcp`로 대체. WSL2 `/mnt`에서는 `--no-watch`를 args에 추가(파일 watcher 느림
해소). Codex CLI / Cursor / opencode / Hermes 등 다른 에이전트는 `codegraph
install --print-config <target>`으로 각자 snippet 출력. 자세히는
`docs/codegraph-worktree.md` §6.

### Telegram 작업 완료 알림 MCP

각 에이전트 worktree의 MCP 설정에는 `mcp-telegram` 서버를 등록한다. Telegram
credential은 각 worktree 루트의 로컬 파일 `.env.mcp-telegram`에만 저장하고,
이 파일은 `.gitignore`의 `.env.*` 규칙으로 커밋하지 않는다. tracked 설정은
`scripts/mcp_telegram_start.py` wrapper를 통해 로컬 env 파일을 읽는다.

단위 작업이 완료되어 PR을 만들면, 최종 응답 전 `mcp-telegram` MCP로 Telegram에
간단한 완료 요약과 PR 링크를 보낸다. PR이 없는 문서/로컬 셋업 작업이라면 PR 링크
대신 브랜치/커밋 또는 "PR 없음"을 명시한다. 자세한 설치와 로그인 절차는
`docs/codegraph-worktree.md` §6.5, 작업 흐름상 발송 시점은
`docs/runbooks/agent-workflow.md` §5를 따른다.

### Code Style & Rules — 수정 전 영향도 평가 (필수)

본 라이브러리는 krtour-map API/Dagster 내부에서 직접 호출되는 **Python API**를
제공하므로 한 함수/DTO 시그니처 변경이 호출자 여러 곳을 깨뜨릴 수 있다.
코드 컴포넌트(특히 `Feature` DTO / `make_feature_id` / provider 변환 함수 /
`core/scoring.py` / `infra/models.py`)를
수정하기 **전에** codegraph로 영향도를 평가한다:

- MCP 환경: `codegraph_explore` MCP 도구로 호출자/의존/영향을 한 번에.
- CLI 환경: `codegraph callers <sym>` + `codegraph impact <file>` +
  `codegraph callees <sym>` 조합.

예외: 신규 파일만 추가하고 기존 심볼 시그니처가 그대로일 때(예: 새 provider
변환 함수 추가)는 생략 가능. 자세히는 `docs/codegraph-worktree.md` §7.

작업 전 반드시 다음을 읽는다:

1. `README.md` — 프로젝트 개요와 빠른 시작
2. `SKILL.md` — DO NOT 룰, 자주 묻는 작업, 도메인 어휘
3. `docs/sprints/README.md` — Sprint 1~5 계획 + ADR-034 9단계 순서
4. `docs/architecture.md` — 의존 방향, 계층, 데이터 흐름
5. `docs/resume.md` — 현재 진척도와 "다음 한 작업"
6. `docs/decisions.md` — 관련 ADR (특히 accepted ADR 027~044)
7. 이번 작업과 직결된 docs 항목 (provider 추가면 `docs/provider-contract.md`,
   현재 sprint면 해당 `docs/sprints/SPRINT-N.md` 등)

## 지시 우선순위

1. 사용자 요청
2. 이 `AGENTS.md`
3. `SKILL.md`
4. `docs/architecture.md`, `docs/decisions.md`, `docs/data-model.md`,
   `docs/backend-package.md`, `docs/performance.md`, `docs/test-strategy.md`,
   `docs/agent-guide.md`, `docs/provider-contract.md`
5. `README.md` 및 나머지 `docs/`
6. 기존 코드와 테스트
7. 최소한의, 되돌릴 수 있는 가정

## TripMate ↔ krtour-map 경계 (ADR-045)

- **TripMate는 krtour-map을 OpenAPI로 호출한다**. 운영 코드에서
  `python-krtour-map`을 직접 import하지 않는다.
- TripMate는 krtour-map PostgreSQL/PostGIS DB에 직접 연결하지 않는다.
- krtour-map은 Docker 독립 프로그램으로 실행되며 독립 DB(`krtour_map`)와 독립
  Dagster metadata DB(`krtour_map_dagster`)를 가진다.
- OpenAPI는 우선 admin UI 기준으로 작성하고, TripMate 연동 시 필요한 공개/사용자
  API를 보완·확장한다.
- `AsyncKrtourMapClient`는 krtour-map API/Dagster 내부 구현과 테스트용 Python API로
  유지한다.
- feature 업데이트는 OpenAPI로 요청한다. 예: 특정 좌표 중심 반경 `n` km 안 feature,
  또는 반경 `n` km와 교차/포함되는 시군구의 feature 업데이트를 즉시 실행하거나
  queue에 넣는다.
- 외부 앱 POI 기반 캐시 갱신은 좌표만으로 식별하지 않는다. 반드시
  `external_system + target_key + 좌표 + radius_km`를 받아 저장하고, target 삭제 시
  targeted update에서 제외한다. 여러 target 반경의 교집합 feature/provider scope는
  한 번만 업데이트한다.
- provider별 update 주기/rate limit은 provider API 프로젝트의 로컬 문서/코드
  (`F:\dev\python-*-api`, ADR-044)를 근거로 DB/설정에 저장한다. override도 rate
  limit을 넘을 수 없다.

## 디버그/관리 REST API 정책 (ADR-005 + ADR-020 + ADR-035 + ADR-040 + ADR-045)

디버그 + admin REST는 **별도 패키지** `krtour-map-admin`에 둔다. 메인
라이브러리 `python-krtour-map`은 FastAPI/Uvicorn 의존이 없다.

- **위치**: `packages/krtour-map-admin/src/krtour/map_admin/` (본 monorepo
  내, 별도 `pyproject.toml`).
- **운영 범위 (ADR-035, accepted 2026-05-27)**: 디버그 + admin + 유지보수 +
  프로덕션 운영 UI. 라우터 prefix로 시각적 분리:
  - `/debug/...` — 개발자용 (fixture replay, EXPLAIN 등)
  - `/admin/...` — 운영자용 (jobs / dedup-review / backup 등 — ADR-040)
  - `/ops/...` — 옵저버빌리티 (consistency / metrics / rustfs-usage)
- **인증**: 별도 키 없음 (ADR-005 그대로). 네트워크 계층(Cloudflare Tunnel /
  SSO 게이트웨이 / IP allowlist)에서 보호. 코드에 인증 로직 침투 금지.
- **메인 라이브러리 의존**: `pip install -e packages/krtour-map-admin`만
  설치하면 `python-krtour-map`을 자동으로 의존성으로 가져간다.
- **TripMate는 Python 의존하지 않는다** — TripMate는 OpenAPI client만 사용한다.
- `KRTOUR_MAP_ADMIN_HOST` 기본 `127.0.0.1`. `0.0.0.0` 바인드 시 경고 로그.
- 자세한 사양은 `docs/debug-ui-package.md`, `docs/debug-ui-admin-workflows.md`,
  `docs/openapi-admin-contract.md`, `docs/backup-restore.md`.

### Frontend stack (ADR-025 + ADR-026 + ADR-036 + ADR-037)

- **지도**: `maplibre-vworld-js` 별도 라이브러리(현재 v0.1.2, ADR-036). 공통
  기능은 상류, TripMate 전용 확장만 본 저장소(`packages/krtour-map-admin/
  frontend/` + 향후 `packages/tripmate-map-extensions/`).
- **앱 프레임워크**: Next.js 16 + React 19 + TypeScript. `next lint`는 Next.js
  16에서 제거되어 ESLint flat config(`eslint.config.mjs`)를 직접 실행한다.
- **서버 상태**: TanStack Query — 모든 `/debug/...`, `/admin/...`, `/ops/...`,
  `/features/...` 응답은 useQuery/useMutation hook으로 래핑 (ADR-037).
- **클라이언트 상태**: Zustand — map viewport / 카테고리 filter / fixture
  playback 상태 (ADR-037).
- **Form/검증**: React Hook Form + Zod.
- **UI primitive**: shadcn/ui.
- **공통 marker/category 매핑**: `packages/map-marker-react/` (npm 게시는
  보류, ADR-043 — `"private": true`, git URL share만).
- **Frontend 작업 후 검증**: React Doctor 실행 후 결과 검토 및 개선 필수.

## Provider API 사용 원칙

- 외부 API 관련 작업은 단순 전달용 wrapper/adapter/gateway 지양 원칙을 먼저
  확인하고 문서/코드에 반영한 뒤 진행한다.
- 본 라이브러리는 안정된 `python-*-api` public client와 typed model을 직접 사용한다.
  새 facade를 만들지 않는다. `KmaWrapper`, `GeoAdapter`, `OpiNetGateway` 같은
  계층 금지.
- 부족한 endpoint, typed model, pagination, cursor, exception, raw payload
  보존 규칙은 TripMate나 본 저장소에 임시 facade를 만들지 않고 해당
  `python-*-api` 저장소에서 먼저 안정화한다.
- 단순 전달용 alias도 만들지 않는다.
- 허용 경계: provider model → `Feature`, `SourceRecord`, `WeatherValue`,
  `PriceValue`로 바꾸는 순수 함수와 저장소 repository까지.
- **관련 라이브러리는 로컬 `F:\dev\` (WSL `~/dev/`)를 먼저 탐색한다 (ADR-044).**
  provider/형제 라이브러리(`python-*-api`, `maplibre-vworld-js` 등)의 client·
  model·codes·스펙 확인은 **로컬 체크아웃이 1차 source** (`Glob`/`Read`로
  `F:\dev\python-*-api/src/...`). GitHub 원격 fetch는 로컬에 없을 때만 fallback
  — GitHub 404/private는 "미존재" 근거가 아니다 (PR#53에서 `python-datagokr-api`
  를 404로 오판해 잘못 보류한 사고 방지).
- **데이터 정합성(코드 매핑 / 필드 의미 / 단위 / 분류값)의 1차 책임은 각
  provider 라이브러리에 있다 (ADR-044).** 예: OpiNet 제품코드 의미는
  `python-opinet-api`가 authoritative — 본 lib는 신뢰·미러만 하고 재정의하지
  않는다. 불일치 발견 시 provider 라이브러리(+공식 API 스펙) 기준으로 정렬하고
  필요하면 해당 라이브러리에 직접 PR로 수정한다.

## 데이터 저장 원칙

- **Postgres 16 + PostGIS 3.5 + pg_trgm + pgcrypto**가 1차 저장소. 모든 공간/검색
  기능을 PostGIS와 pg_trgm으로 처리한다. SpatiaLite/SQLite 대안은 없다.
- **SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg**가 표준 스택. 동기 인터페이스는
  추가하지 않는다(ADR-002).
- **ORM 모델은 매핑만**. 쿼리는 `infra/*_repo.py`의 raw SQL (`sqlalchemy.text()`).
  EXPLAIN 친화 + 인덱스 hint 자유 (ADR-004).
- **이미지/문서/provider 첨부**는 DB에 직접 저장하지 않는다. S3 호환 객체 저장소
  (RustFS 우선, MinIO/Ceph/R2 swap)에 저장하고 `feature_files` 1:N 메타데이터.
- **공간 쿼리 술어에서 좌표 형변환 금지**. 입력 좌표는 CTE에서 한 번만
  `ST_Transform`해서 상수로 굳히고, 술어는 인덱스 있는 컬럼(`coord_5179` 등)을
  그대로 사용한다. 자세한 패턴은 `docs/performance.md`.

## 성능 설계 원칙 (설계 단계부터)

- 모든 신규 table은 **인덱스 설계를 ADR과 함께 결정**한다. "나중에 튜닝" 금지.
- 시계열 적재(`price_values`, `weather_values`)는 `observed_at`/`valid_at` 기준
  `BRIN` 인덱스 + 시간순 bulk insert.
- 65,535 파라미터 한도 초과 가능성 있는 bulk insert는 처음부터
  `psycopg.AsyncConnection.cursor().copy()` 패턴 사용. 안전 마진 30k.
- 작업 큐 상태는 `import_jobs` 테이블 영속화. in-memory 신뢰 금지.
- 자세한 가이드는 `docs/performance.md`.

## 테스트 정책 (촘촘하게)

- 테스트는 `tests/unit/` (Fake repo) + `tests/integration/` (testcontainers
  PostGIS) + `tests/e2e/` (디버그 API + integration DB) + `tests/fixtures/`
  (replay) 4단계.
- Coverage 목표 (최종): **`core/` 90%+, `infra/` 80%+, `providers/` 70%+,
  `dto/` 100% branch, 전체 80%+**. 단계적 상향 schedule은 **ADR-032**
  (Sprint 1 50% → Sprint 4 80% 도달, `docs/test-strategy.md §2`).
- 모든 ETL provider 변환 함수는 fixture 기반 회귀 테스트 ≥3개 (정상/엣지/실패).
- 모든 raw SQL은 통합 테스트에서 EXPLAIN 결과로 `Index Scan` 또는 `Bitmap Heap
  Scan` 사용을 확인한다. 풀스캔 발견 시 PR block.
- 자세한 사양은 `docs/test-strategy.md`.

## 절대 하지 말 것 (DO NOT)

`SKILL.md` §4가 최신본이지만 핵심은 다음과 같다:

1. **의존 방향 역행 금지** — 메인 패키지: `dto → core → infra → providers →
   client → cli` 한 방향. `import-linter`가 CI에서 강제. `krtour.map.api`는
   존재하지 않는다 (ADR-020 — 디버그 REST는 별도 패키지).
2. **동기 인터페이스 추가 금지** — `AsyncKrtourMapClient`만. 동기는 호출자가
   `asyncio.run`으로 감싼다 (ADR-002).
3. **`pg_trgm.similarity_threshold` 전역 변경 금지** — 트랜잭션 내부 `SET LOCAL`.
4. **ORM에 비즈니스 로직 금지** — `infra/models.py`는 매핑만. 쿼리는
   `infra/*_repo.py`의 raw SQL (ADR-004).
5. **좌표 순서 혼동 금지** — 외부 인터페이스는 모두 `(lon, lat)`.
   PostGIS도 `ST_MakePoint(lon, lat)`.
6. **카테고리/마커 매핑 하드코드 금지** — `category_mappings` DB 또는 settings.
7. **응답 셰입 임의 변경 금지** — 라이브러리 DTO는 `data/meta/error` 같은 HTTP
   래핑 키를 갖지 않는다. 래핑은 호출자 책임.
8. **외부 API 키 평문 커밋 금지** — 모두 `SecretStr`. `.env` 권한 600 또는
   systemd `EnvironmentFile`/vault.
9. **provider adapter/wrapper 신규 생성 금지** — public client 직접 사용.
10. **`feature_id` raw string concat 금지** — 항상 `make_feature_id(...)`.
11. **공간 쿼리 술어에서 `ST_Transform` 금지** — 인덱스 무효화.
12. **SQLAlchemy bulk `insert().values(rows)` 파라미터 폭주 금지** — 65,535 한도,
    안전 마진 30k. 초과 시 `psycopg.copy_*`.
13. **작업 큐 상태를 in-memory만 신뢰 금지** — `import_jobs` 영속화.
14. **디버그 API/UI 패키지에 인증 추가 금지** — 내부망 전제. 외부 노출이
    필요해지면 네트워크 계층(SSO 게이트웨이/IP allowlist/Cloudflare Tunnel)에서
    보호. 코드/응답에 인증 로직 침투 X.
15. **메인 라이브러리(`krtour.map`)에 FastAPI/Uvicorn import 금지** — ADR-020.
    HTTP 서버 코드는 `packages/krtour-map-admin/`에만.
16. **데이터/원천 파일을 git에 커밋 금지** — `data/`는 `.gitignore`. NTFS에 보관.
17. **main에 직접 push 금지** — 모든 변경은 feature branch + PR (ADR-021).
    `git push origin main` 절대 금지. 핫픽스도 단명 branch를 통해. 브랜치 명명:
    `feat/<topic>` / `fix/<topic>` / `chore/<topic>` / `docs/<topic>` /
    `refactor/<topic>` / `adr/<short>`.
18. **`from krtour_map import ...` (flat) 사용 금지** — 항상 `from krtour.map
    import ...` (ADR-022). `src/krtour_map/` 디렉토리 만들지 말 것 —
    `src/krtour/map/`.
19. **`src/krtour/__init__.py` 만들지 금지** — PEP 420 implicit namespace.
    파일이 생기는 순간 `krtour-map-admin` 같은 자매 distribution과 충돌.
    CI에서 차단 체크.
20. **CLI 중복 실행이 위험한 명령에 mutex 없이 머지 금지** (ADR-039 accepted) —
    `import`/`dedup-merge`/`backup`/`restore`/`alembic upgrade` 등은 PostgreSQL
    advisory lock(`pg_try_advisory_lock`)으로 mutex 가드. read-only / `--dry-run`
    은 예외. lock key: `hash(f"krtour-map:{command}:{scope}")`.
21. **`@krtour/map-marker-react` npm registry 게시 금지** (ADR-043) —
    `packages/map-marker-react/package.json` `"private": true`. 외부 사용처는
    git URL share만.
22. **`PlaceCoordinate` kraddr-base에서 import 금지** (ADR-041) — 좌표 DTO는
    `krtour.map.dto.Coordinate` 단일 source. kraddr-base 흡수 작업에서 명시적
    제외 대상.

## 작업 후 체크리스트

- [ ] **수정 전 영향도 평가** (MCP `codegraph_explore` 또는 CLI `codegraph
      callers`/`impact`/`callees`) — 컴포넌트 시그니처 변경 시 필수
      (`docs/codegraph-worktree.md` §7).
- [ ] `pytest -q` (unit + integration 일부) 통과
- [ ] `ruff check .` / `mypy --strict` / `lint-imports` 통과
- [ ] **GitHub Actions CI green 통과 후 머지** (ADR-038, 2026-05-27 재활성화) —
      `.github/workflows/{ci,lint,openapi}.yml` 모두 통과 + 1 review approval.
- [ ] `docs/journal.md`에 작업 항목 추가 (역시간순)
- [ ] `docs/resume.md`의 진척도 갱신
- [ ] 의사결정이 있었다면 `docs/decisions.md`에 ADR 추가
- [ ] 사용자 가시 변경이면 `CHANGELOG.md` 갱신
- [ ] DTO/스키마 변경이면 `scripts/export_openapi.py` 재실행
       (디버그 API 라우터 노출 시점부터 적용)
- [ ] CLI 명령 추가 시 mutex 필요 여부 확인 (ADR-039 — write/bulk/restore는
      advisory lock 박음)

## 검증

```bash
# 단위 + lint
python -m pytest tests/unit -q
python -m ruff check .
python -m mypy src/krtour/map
lint-imports

# 통합 (PostGIS testcontainers 필요)
python -m pytest tests/integration -q

# 전체
python -m pytest -q
```

## 코드 작성 단계

본 저장소는 **T-014 (Sprint 1 진입)** 승인 (2026-05-25, PR#16) 이후
**코드 작성 단계**다.

> **현재 진척·스프린트 상태·"다음 한 작업"의 단일 정본은 `docs/resume.md`,
> 백로그는 `docs/tasks.md`다.** 이 문서에는 자주 바뀌는 PR 번호/완료여부를 박지
> 않는다(반복 drift 회피 — `docs/reports/docs-consistency-audit-2026-06-06.md`
> DA-D-01). 운영 모델·ADR·포트·frontend stack 같은 **불변 사실**은 위 "TripMate
> ↔ krtour-map 경계" / "디버그·관리 REST API 정책" / "Frontend stack" 절,
> `CLAUDE.md §2`, `docs/decisions.md`를 정본으로 본다. 패키지는
> `krtour-map-debug-ui` → `krtour-map-admin` rename 완료(ADR-020 amendment), 구
> 이름/env/import 호환 shim은 만들지 않는다(ADR-046).

**계속 유효한 코드 작성 가이드**:
- 모든 신규 코드는 `import-linter` 의존 방향 (`category → dto → core →
  infra → providers → client → cli`) 준수.
- `src/krtour/__init__.py`는 **절대 만들지 말 것** (PEP 420 implicit namespace,
  `tests/lint/test_no_namespace_init.py`가 차단).
- DTO/schema 변경 시 OpenAPI export와 admin/user schema drift 여부를 함께 확인.
- write/bulk/restore 계열 CLI 명령은 ADR-039 advisory lock 필요 여부를 확인.
