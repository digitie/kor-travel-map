# AGENTS.md

> 본 파일은 **OpenAI Codex / Google Antigravity** 등 `AGENTS.md` 컨벤션을
> 따르는 AI agent의 표준 entry다. Claude Code는 별도 `CLAUDE.md` (1쪽 요약)
> 가 있으나 정식 정책·결정은 본 파일·`SKILL.md`·`docs/adr/README.md`가 갖는다.

## 목표

`kor-travel-map`은 대한민국 국내 여행 정보를 취합·저장·제공하는 범용 데이터 툴이다.

1. **수집**: 외부 API·파일·웹 페이지·관리자 수동 입력 소스에서 국내 여행 관련 정보를
   주기적 또는 수동으로 취합해 저장·관리한다.
2. **범위**: 관광·숙박·편의·행사·날씨 등 여행에 도움이 되고 위치(좌표/지점) 형태로
   표현할 수 있는 정보를 다룬다.
3. **제공**: 저장한 정보는 REST API로 외부에서 활용할 수 있다.
4. **운용**: 비전문가도 다룰 수 있는 데이터 수집·관리·백업·복원용 admin UI와 CLI
   인터페이스를 제공한다.

## Think Before Coding

- 요청이 모호할 때는 해석을 조용히 정하지 말 것
- 중요한 가정은 숨기지 말고 드러낼 것
- 해석에 따라 구현 방향이 크게 달라지면 그 차이를 먼저 표면화할 것
- 안전하게 진행하기 어려울 정도로 혼란스러우면 추측하지 말고 확인할 것

## Simplicity First

- 요청을 완전히 해결하는 최소한의 코드만 작성할 것
- 요청되지 않은 기능을 추가하지 말 것
- 일회성 용도를 위해 추상화를 만들지 말 것
- 구체적인 필요 없이 설정 가능성이나 유연성을 늘리지 말 것
- 구현이 문제에 비해 커졌다고 느껴지면 줄일 것

## Surgical Changes

- 요청을 처리하는 데 필요한 코드만 변경할 것
- 작업이 요구하지 않으면 주변 로직까지 다시 쓰지 말 것
- 관련 없는 코드의 포맷, 이름, 스타일을 건드리지 말 것
- 사용자가 더 넓은 변경을 원한 것이 아니라면 기존 패턴을 맞출 것
- 관련 없는 문제를 발견하면 패치에 섞지 말고 따로 언급할 것

## Goal-Driven Execution

- 모호한 요청을 구체적이고 검증 가능한 결과로 바꿀 것
- 버그 수정은 재현 없이 바로 신뢰하지 말 것
- 리팩터링은 동작 보존을 전제로 전후 기대를 확인할 것
- 넓고 막연한 점검보다 목적이 분명한 검증을 선호할 것
- 완전한 검증이 불가능하면 무엇이 아직 미검증인지 밝힐 것

## Practical Bias

- 비단순 작업에서는 성급함보다 신중함을 우선할 것
- 변경 내역은 리뷰 가능한 범위와 요청 범위에 가깝게 유지할 것
- 아주 단순하고 명백한 한 줄 작업은 과하게 무겁게 다루지 말 것

## 문서 언어 정책

이 저장소의 모든 Markdown/RST 문서는 한국어로 작성한다. 공식 API 필드명, 코드 식별자,
명령어, URL, 라이브러리·제공자 원문, 환경변수처럼 그대로 보존해야 하는 값만 영어를
유지한다. 신규 문서와 기존 문서 모두 동일 규칙을 우선한다.

**예외(ADR-059)**: `.claude/`, `.agents/`, `.codex/`, `.opencode/` 아래의 벤더링된 상위(upstream)
agent/skill 원문은 본 규칙의 예외다 — 원문 동기화 충실성을 위해 영어 원문을 유지하되,
본 저장소 관례(context 발견은 entry 문서 + codegraph이며 `context-manager` agent는
존재하지 않는다)에 맞게 적응한다. 근거·범위는 `.claude/agents/README.md` 참조.

## 역할

이 저장소(GitHub 이름 `kor-travel-map`, Python 패키지 `kortravelmap` — ADR-022)는 여러 한국
공공 API 라이브러리(`python-*-api`)에서 올라오는 여행 지도 데이터를 단일 `Feature`
계약으로 정규화·저장·조회·수정·삭제할 수 있게 하는 **kor-travel-map 독립 프로그램 +
내부 Python 라이브러리**다.

ADR-045(2026-06-01) 이후 운영 모델은 **Docker 독립 프로그램 + 독립 DB/Dagster +
OpenAPI 경계**다. 외부 소비자는 kor-travel-map DB에 직접 접근하거나 `kor-travel-map`을
운영 코드에서 직접 import하지 않고, OpenAPI 기반 HTTP 계약으로만 호출한다.

REST/OpenAPI backend는 별도 Python 패키지 `kor-travel-map-api`, admin UI는
`kor-travel-map-admin`로 분리되어 있다(ADR-055). API/Dagster 내부에서는 메인
라이브러리를 import해 `AsyncKorTravelMapClient`를 호출한다. 인증·ServiceToken·
포트 등 cross-repo 계약 정본은 `docs/integration-map.md` §3.

이전(v1) 구현은 `v1` 브랜치에 보존, main은 orphan으로 v2 재시작(ADR-001).

## 식별자 (혼동 방지 — 본 표가 정본, ADR-054)

전환 정본은 `docs/package-identity-rename.md`. 형제 프로젝트는 `kor-travel-geo`,
`kor-travel-concierge`, `kor-travel-docker-manager`.

| 항목 | 값 |
|------|----|
| GitHub 저장소 이름 | `kor-travel-map` |
| PyPI distribution | `kor-travel-map` |
| Python import (메인) | `import kortravelmap as ktm` 또는 `from kortravelmap import ...` |
| Python import (REST API) | `from kortravelmap.api import ...` — 별도 dist kor-travel-map-api 내부에서만; 메인 라이브러리 `src/kortravelmap`에는 `.api` 하위 패키지 없음 (ADR-055) |
| CLI 명령 | `ktmctl ...` |
| 환경변수 prefix | `KOR_TRAVEL_MAP_*` (env는 underscore 표준 유지) |
| PostgreSQL DB 이름 (개발/운영 기본) | `kor_travel_map` (ADR-045 — 공유 DB 아님) |
| Dagster metadata DB 기본 | `kor_travel_map_dagster` |
| Postgres schema | `feature`, `provider_sync`, `ops` (kor-travel-map 내부 schema 분리) |
| PostGIS extension schema | `x_extension` (ADR-008) |
| REST API 패키지 | `kor-travel-map-api` (별도 **Python** 패키지, monorepo 내 `packages/kor-travel-map-api/`, ADR-055) |
| Admin UI 패키지 | `kor-travel-map-admin` (Next.js frontend, `packages/kor-travel-map-admin/frontend/`) |
| Category 모듈 출처 | `kortravelmap.category` (구 `kraddr.base.categories`에서 이전, ADR-023) |
| Address DTO + 행정코드 utility | `kortravelmap.dto.Address` + `kortravelmap.core.address` (구 `kraddr.base`에서 흡수, ADR-041 — `PlaceCoordinate`는 제외, 좌표는 `Coordinate`로 단일화) |
| Provider 라이브러리 git URL/sha 핀 status | `docs/architecture/provider-contract.md` §12 표 (Sprint별 그룹화, kma/datagokr는 Protocol 박힘) |
| ADR 현황 | ADR-001~059 전부 accepted; 상세·색인은 `docs/adr/README.md`. 다음 후보 번호 = ADR-060. |
| Sprint plan | `docs/sprints/SPRINT-1.md` ~ `SPRINT-5.md` |
| Provider 구현 순서 (ADR-034) | 축제→날씨→유가→휴게소→국립공원/트래킹→국가유산→**MOIS**→휴양림/수목원→박물관/미술관 |

## 개발 환경 정책 (PC, WSL)

핵심 규칙: 순수 `git` 명령만 Windows/NTFS host에서 실행하고, 파일 탐색·코드/문서
수정·테스트·lint·build·Docker·Python/Node/npm·`gh`는 WSL `/mnt/f/dev/kor-travel-map-
<agent>`에서 실행한다. 디버그 UI Playwright e2e만 예외로 Windows 호스트에서 실행한다
(서버는 WSL). Git source of truth는 NTFS. 절차 정본은 `docs/dev-environment.md`,
복구는 `docs/windows-reinstall-recovery.md`.

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

## 에이전트 worktree + codegraph

각 AI 에이전트는 자기 전용 git worktree(아래 표) + 로컬 codegraph 인덱스 1개를
가진다. 작업마다 그 worktree 안에서 브랜치만 새로 딴다(`git switch -c feat/<topic>
main`). 셋업·작업 사이클·자주 쓰는 커맨드·MCP 등록 snippet 정본은
`docs/codegraph-worktree.md`.

| AI 에이전트 | 고정 worktree 디렉토리 |
|------------|----------------------|
| ChatGPT Codex | `F:\dev\kor-travel-map-codex` |
| Claude Code (본 SDK 포함) | `F:\dev\kor-travel-map-claude` |
| Google Antigravity 2.0 | `F:\dev\kor-travel-map-antigravity` |

**수정 전 영향도 평가 (필수)**: 코드 컴포넌트(특히 `Feature` DTO /
`make_feature_id` / provider 변환 함수 / `core/scoring.py` / `infra/models.py`)
시그니처 변경 전에 codegraph로 영향도를 평가한다 — MCP `codegraph_explore` 또는
CLI `codegraph callers`/`impact`/`callees`. 신규 파일만 추가하고 기존 심볼
시그니처가 그대로면 생략 가능. 자세히는 `docs/codegraph-worktree.md` §7.

## 지시 우선순위

1. 사용자 요청
2. 이 `AGENTS.md`
3. `SKILL.md`
4. `docs/architecture/architecture.md`, `docs/adr/README.md`, `docs/architecture/data-model.md`,
   `docs/architecture/backend-package.md`, `docs/architecture/performance.md`, `docs/test-strategy.md`,
   `docs/agent-guide.md`, `docs/architecture/provider-contract.md`
5. `README.md` 및 나머지 `docs/`
6. 기존 코드와 테스트
7. 최소한의, 되돌릴 수 있는 가정

## 외부 경계 (ADR-045)

> cross-repo 연동의 1장 정본(포트·연동 방향·인증·envelope 차이·계약 정본 위치)은
> **`docs/integration-map.md`** (T-217d). 분기 drift 점검은
> `docs/runbooks/cross-repo-audit-checklist.md`.

- **외부 소비자는 kor-travel-map을 OpenAPI로 호출한다**. 운영 코드에서
  `kor-travel-map`을 직접 import하지 않는다.
- 외부 소비자는 kor-travel-map PostgreSQL/PostGIS DB에 직접 연결하지 않는다.
- kor-travel-map은 Docker 독립 프로그램으로 실행되며 독립 DB(`kor_travel_map`)와 독립
  Dagster metadata DB(`kor_travel_map_dagster`)를 가진다.
- OpenAPI는 우선 admin UI 기준으로 작성하고, 외부 연동 시 필요한 공개/사용자
  API를 보완·확장한다.
- `AsyncKorTravelMapClient`는 kor-travel-map API/Dagster 내부 구현과 테스트용 Python API로
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

## 디버그/관리 REST API · Frontend stack

디버그 + admin + public REST는 별도 패키지 `kor-travel-map-api`에 둔다(메인
라이브러리는 FastAPI 의존 없음). 라우터 prefix는 `/debug` `/admin` `/ops`로 분리.
사양 정본은 `docs/architecture/debug-ui-package.md` + `docs/architecture/rest-api.md`. Frontend stack(지도/
프레임워크/상태관리 등)은 `docs/architecture/architecture.md`가 정본.

## Provider API 사용 원칙

- 외부 API 관련 작업은 단순 전달용 wrapper/adapter/gateway 지양 원칙을 먼저
  확인하고 문서/코드에 반영한 뒤 진행한다.
- 본 라이브러리는 안정된 `python-*-api` public client와 typed model을 직접 사용한다.
  새 facade를 만들지 않는다. `KmaWrapper`, `GeoAdapter`, `OpiNetGateway` 같은
  계층 금지.
- 부족한 endpoint, typed model, pagination, cursor, exception, raw payload
  보존 규칙은 본 저장소에 임시 facade를 만들지 않고 해당
  `python-*-api` 저장소에서 먼저 안정화한다.
- 단순 전달용 alias도 만들지 않는다.
- 허용 경계: provider model → `Feature`, `SourceRecord`, `WeatherValue`,
  `PriceValue`로 바꾸는 순수 함수와 저장소 repository까지.
- **관련 라이브러리는 로컬 `F:\dev\` (WSL `~/dev/`)를 먼저 탐색한다 (ADR-044).**
  provider/형제 라이브러리(`python-*-api`, `maplibre-vworld-react` 등)의 client·
  model·codes·스펙 확인은 **로컬 체크아웃이 1차 source** (`Glob`/`Read`로
  `F:\dev\python-*-api/src/...`). GitHub 원격 fetch는 로컬에 없을 때만 fallback
  — GitHub 404/private는 "미존재" 근거가 아니다 (PR#53에서 `python-datagokr-api`
  를 404로 오판해 잘못 보류한 사고 방지).
- **데이터 정합성(코드 매핑 / 필드 의미 / 단위 / 분류값)의 1차 책임은 각
  provider 라이브러리에 있다 (ADR-044).** 예: OpiNet 제품코드 의미는
  `python-opinet-api`가 authoritative — 본 lib는 신뢰·미러만 하고 재정의하지
  않는다. 불일치 발견 시 provider 라이브러리(+공식 API 스펙) 기준으로 정렬하고
  필요하면 해당 라이브러리에 직접 PR로 수정한다.

## 데이터 저장 · 성능 설계 원칙

저장소·스택 정본은 `docs/architecture/data-model.md`, 성능/인덱스 패턴(공간 쿼리 `ST_Transform`
금지, BRIN, `psycopg.copy` 65,535 한도 등)은 `docs/architecture/performance.md`. 개발 룰로서의
요약은 `SKILL.md` §4. 테스트 정책(4단계 구조·coverage·EXPLAIN gate)은
`docs/test-strategy.md`.

## 절대 하지 말 것 (DO NOT)

26개 개발 규칙의 정본은 `SKILL.md` §4. 가장 치명적인 5개만 재기재:

1. **main에 직접 push 금지** — 모든 변경은 feature branch + PR + CI green 후 머지
   (ADR-021 + ADR-038). 브랜치 명명: `feat|fix|chore|docs|refactor|adr/<topic>`.
2. **`from kor_travel_map import ...` (flat) 금지** — 항상 `import kortravelmap as
   ktm` 또는 `from kortravelmap import ...` (ADR-054). `src/kor_travel_map/`·
   `src/krtour/` 디렉토리 부활 금지.
3. **provider adapter/wrapper/facade/alias 신규 생성 금지** — public `python-*-api`
   client 직접 사용.
4. **의존 방향 역행 금지** — `category → dto → core → infra → geocoding →
   providers → client → cli` 한 방향(`import-linter` CI 강제). `kortravelmap.api`
   는 메인 라이브러리(`src/kortravelmap`)에 없다 — HTTP 서버 코드는 별도 dist
   `packages/kor-travel-map-api/`의 `kortravelmap.api`에만.
5. **공간 쿼리 술어에서 `ST_Transform` 금지** — 인덱스 무효화.

## prod 배포 & 보안 감사

**prod(n150) 배포 절차·접속·반복 함정의 정본은 `docs/deploy-runbook.local.md`**
(gitignore된 로컬 전용, 민감정보 포함; 접속/필수 env는 `docs/prod-access.local.md`).
배포 전 반드시 읽는다. 이 런북들은 커밋되지 않으므로 **각 git worktree의 `docs/`에도
같은 경로로 복사**해 둔다(`*.local.md`는 `.gitignore` + `.git/info/exclude`로 무시).

반복적으로 깨져서 강제하는 2건:

- **배포 후 로그인 검증 생략 금지** — prod UI 배포/재생성 뒤 `GET /login 200`만 보지
  말고 **로그인 POST(200 + Set-Cookie)** 와 UI 컨테이너 auth env
  (`${#KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH} != 0`)를 확인한다. 근본원인·복구는 런북.
- **remote 푸시 전 보안 감사 생략 금지** — `git push`(특히 PR 직전) 전에 아래 절차로
  비밀(API 키·세션 시크릿·비밀번호·prod 호스트/도메인 등)이나 `*.local.md`·`.env*`가
  스테이징/커밋에 섞이지 않았는지 확인한다. 통과 전에는 푸시하지 않는다.

### remote 푸시 전 보안 감사 (필수 절차)

1. **스테이징 파일 점검** — `git diff --cached --name-only`에 `*.local.md`,
   `.env`(`.env.example` 제외)·`.env.*`, prod 비밀 파일이 **없어야** 한다.
2. **일반 비밀 스캔**:
   ```bash
   git diff --cached -U0 | grep -nEi '(api[_-]?key|secret|password|passwd|token|pbkdf2_sha256|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY)' \
     && echo '⛔ 의심 항목 — 푸시 중지' || echo '✅ 일반 비밀 패턴 없음'
   ```
3. **docs redaction 가드** — `python scripts/check_prod_redaction.py` (tracked docs에
   prod 도메인/IP 없음; pre-commit·CI에도 박혀 있음).
4. **프로젝트별 민감값 스캔** — `docs/deploy-runbook.local.md` §6의 "푸시 전 추가 스캔"
   grep으로 prod 호스트 IP·도메인·SSH 사용자·관리자 비번 등 **map 구체 민감값**도 검색
   (그 값들은 런북에만 두고 커밋 파일엔 절대 적지 않는다 — `<prod-host>` 등 placeholder만).

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
- [ ] 의사결정이 있었다면 `docs/adr/README.md`에 ADR 추가
- [ ] 사용자 가시 변경이면 `CHANGELOG.md` 갱신
- [ ] DTO/스키마 변경이면 `packages/kor-travel-map-api/scripts/export_openapi.py` 재실행
       (디버그 API 라우터 노출 시점부터 적용)
- [ ] CLI 명령 추가 시 mutex 필요 여부 확인 (ADR-039 — write/bulk/restore는
      advisory lock 박음)
- [ ] **remote push 전 보안 감사** (§prod 배포 & 보안 감사) — 비밀·`*.local.md`·`.env*`
      미혼입 확인 후 푸시

## 검증

```bash
# 단위 + lint
python -m pytest tests/unit -q
python -m ruff check .
python -m mypy src/kortravelmap
lint-imports

# 통합 (PostGIS testcontainers 필요)
python -m pytest tests/integration -q

# 전체
python -m pytest -q
```

## 코드 작성 단계

진척·스프린트 상태·"다음 한 작업"의 정본은 `docs/resume.md`, 백로그는
`docs/tasks.md`(완료·아카이브는 `docs/tasks-done.md`). 구 이름/env/import 호환
shim은 만들지 않는다(ADR-046). DTO/schema 변경 시 OpenAPI export와 admin/user
schema drift 여부를 함께 확인하고, write/bulk/restore 계열 CLI는 ADR-039 advisory
lock 필요 여부를 확인한다.
