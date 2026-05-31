# CLAUDE.md — 1쪽 진입 요약

이 파일은 Claude(Claude Code, Claude Agent SDK)가 가장 먼저 읽어야 할 1쪽 요약이다.
정식 정책·결정은 `AGENTS.md`, `SKILL.md`, `docs/decisions.md`가 갖는다.

> **OpenAI Codex / Google Antigravity** 등 `AGENTS.md` 컨벤션을 따르는 AI agent는
> `AGENTS.md`를 entry로 사용한다. 본 라이브러리는 CLAUDE.md + AGENTS.md 두
> 파일만 AI agent entry로 박는다 (Copilot/Cursor 등 IDE-side 룰 파일은 두지
> 않음 — drift 회피).

## 1. 이 저장소가 하는 일

`python-krtour-map`은 TripMate의 지도 데이터 정규화·저장 **함수 라이브러리**다.
한국 공공 API (`python-*-api`) 결과를 `Feature`(place/event/notice/price/weather/
route/area) 계약으로 정규화하고 PostgreSQL + PostGIS에 저장한다.

**Python import**: `from krtour.map import ...` (PEP 420 implicit namespace
`krtour`, ADR-022). PyPI distribution은 `python-krtour-map`.

TripMate ↔ 라이브러리는 **함수 직접 호출**. HTTP가 아니다. 디버그 REST/UI는
**별도 Python 패키지** `krtour-map-debug-ui` (`packages/krtour-map-debug-ui/`,
ADR-020)로 분리되어 있고, 인증 없이 내부망에서만 사용한다. 메인 라이브러리는
FastAPI 의존이 없다.

## 2. 현 단계

**v2 Sprint 3 완료 / Sprint 4 진입 준비**. v1은 `v1` 브랜치 보존, main은
orphan으로 v2 새로 시작. 2026-06-01 현재 main은 PR#114까지 머지됨:
- Sprint 2~3: provider 변환, PostGIS 적재/조회, consistency report, dedup queue,
  `AsyncKrtourMapClient`, KNPS/krheritage, debug UI `/features` 구현 완료
- geocoding 정본: kraddr-geo REST `/v1/address/*`, 로컬 기본 `http://127.0.0.1:8888`
- frontend 정본: Next.js 16 + React 19 + `maplibre-vworld-js#v0.1.2`, Windows
  Playwright e2e 최신 14/14
- 다음 작업: Sprint 4 4a — MOIS Step A/B bulk 변환 + dedup queue 본격 운영

ADR 현황: **001~044 모두 accepted** (029는 ADR-043으로 supersede). 035~043은
**PR#33 (2026-05-27) 일괄 accepted 전환** — 운영 단계 진입에 따른 9건:
- 035 REST API admin 운영 확장 / 036 maplibre-vworld-js 분리 (현재 본 저장소 핀 v0.1.2)
- 037 frontend TanStack Query + Zustand / 038 GitHub Actions CI/CD 재활성화
- 039 CLI mutex (advisory lock) / 040 Backup/Restore + 핫스왑 UI
- 041 kraddr-base 코드 흡수 + 폐기 / 042 datagokr 표준데이터 축제 1차 source
- 043 `@krtour/map-marker-react` npm 게시 보류 (ADR-029 supersede)
- 044 관련 라이브러리 로컬(`F:\dev\`, WSL `~/dev/`) 우선 조회 + 데이터 정합성 책임 분계

다음 후보 번호 = **ADR-045**. ADR-030~033은 2026-05-29 사용자 승인 확정,
ADR-033 Phase 1(F1~F3 정합성) 구현 완료. implementation 시점: 038 즉시 / 042
SPRINT-2 §2.1 / 035·037·043 SPRINT-2 §2.5 / 036 SPRINT-3 후반 / 039·040·041
SPRINT-4 prep.

Sprint 1~5 plan은 `docs/sprints/` 참조. **provider 9단계 구현 순서**
(ADR-034): 축제 → 날씨 → 유가 → 휴게소 → 국립공원/트래킹 → 국가유산 →
**MOIS 인허가** → 휴양림/수목원 → 박물관/미술관. MOIS-독립 먼저, dedup 룰
검증 후 MOIS bulk, 마지막에 MOIS-sibling.

v1 산출물 요약: 저장소 루트 `python-krtour-map-spec.docx` (약 80쪽).

## 3. 진입 순서

1. `AGENTS.md` — 지시 우선순위, DO NOT 룰
2. `SKILL.md` — 도메인 어휘, 자주 묻는 작업
3. `docs/sprints/README.md` — Sprint 1~5 계획 + ADR-034 9단계 순서
4. `docs/architecture.md` — 의존 방향
5. `docs/resume.md` — 다음 한 작업
6. `docs/journal.md` 최신 3건
7. 관련 ADR (`docs/decisions.md`)

## 4. 의존 스택 (v2 확정)

`python-kraddr-geo`와 동일 스택. PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto /
SQLAlchemy 2 async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2 / GeoPandas
+ Shapely 2 + GDAL / Pydantic v2 / FastAPI + Uvicorn / httpx + tenacity / Alembic.

**관련 라이브러리 로컬 우선 조회 (ADR-044)**: 모든 형제 `python-*-api` provider
라이브러리(`python-kma-api`/`python-opinet-api`/`python-krex-api`/`python-
datagokr-api`/`python-visitkorea-api`/`python-knps-api`/`python-krheritage-api`/
`python-mois-api`/`python-airkorea-api`/`python-krforest-api`/`python-khoa-api`
…)와 `maplibre-vworld-js`는 **`F:\dev\` (WSL `~/dev/`) 아래 로컬 체크아웃**되어
있다. provider client·model·스펙을 볼 때는 **로컬을 먼저** `Glob`/`Read`로
조회하고, GitHub 원격 fetch는 로컬에 없을 때만 fallback (GitHub 404/private는
"미존재" 근거 아님). **데이터 정합성(코드/필드/단위 의미)의 1차 책임은 각
provider 라이브러리** — 본 lib는 신뢰·미러하고, 불일치 시 그 라이브러리 기준
으로 정렬(+필요 시 upstream PR).

**개발 환경**: PC 개발의 Git 원본은 **Windows NTFS**
(`F:\dev\python-krtour-map\`)다. 브랜치 전환, 커밋, PR 준비는 Windows
Git(`git.exe`) 기준으로 수행한다. WSL은 PostGIS/testcontainers/e2e 같은 Linux
실행이 필요할 때 NTFS 소스를 ext4 샌드박스로 `rsync`해서 쓴다. 자세히는
`README.md` §"개발 환경 (PC, WSL)" + `AGENTS.md` + `docs/dev-environment.md`.

**Claude Code 전용 worktree**: `F:\dev\python-krtour-map-claude\`(메인 repo의 형제).
작업마다 worktree 안에서 브랜치만 새로 (`git switch -c feat/<topic> main`).
worktree마다 [codegraph](https://github.com/colbymchenry/codegraph) 인덱스
1개를 두고(`codegraph init -i` 최초 1회), 이후엔 `codegraph sync`로 증분
동기. `.codegraph/`는 `.gitignore`. 자세히는 `docs/codegraph-worktree.md` +
`AGENTS.md` §"에이전트 worktree + codegraph". ChatGPT Codex는
`F:\dev\python-krtour-map-codex\`, Google Antigravity 2.0은
`F:\dev\python-krtour-map-antigravity\` worktree를 쓴다.

**codegraph MCP 등록**: `~/.claude.json` (Windows: `C:\Users\<user>\.claude
.json`)의 `mcpServers`에 `codegraph: { type: stdio, command: codegraph,
args: ["serve", "--mcp"] }` 블록을 추가하거나 `codegraph install --yes`로
자동 등록. 이후 Claude Code 세션은 `codegraph_explore` MCP 도구를 자동
인식한다. **컴포넌트(특히 `Feature` DTO / `make_feature_id` / provider
변환 함수) 수정 전에 반드시 `codegraph_explore` 또는 CLI `codegraph
impact`/`callers`/`callees`로 영향도를 먼저 평가**한다 (`docs/codegraph-
worktree.md` §7).

## 5. 절대 금지 (가장 중요한 5개)

1. **main에 직접 push 금지** — 모든 변경은 feature branch + PR + **CI green
   후 머지** (ADR-021 + ADR-038 재활성화).
2. **`from krtour_map import ...` (flat) 사용 금지** — 항상 `from krtour.map
   import ...` (ADR-022, PEP 420 implicit namespace).
3. provider adapter/wrapper 신규 생성 금지 (public client 직접 사용, ADR-006).
4. 의존 방향 역행 금지 — `category → dto → core → infra → providers → client → cli`.
   `krtour.map.api` 없음 (ADR-020).
5. 공간 쿼리 술어에서 `ST_Transform` 금지 (인덱스 무효화, ADR-012).

전체 22개 룰은 `SKILL.md` §4 (ADR-039 CLI mutex / ADR-041 PlaceCoordinate
import 금지 / ADR-043 npm 게시 금지 포함).

## 6. 작업 후 체크리스트 (1줄)

`pytest -q` + `ruff check` + `mypy --strict` + `lint-imports` + `docs/journal.md`
+ `docs/resume.md` (+ ADR/CHANGELOG/OpenAPI 해당 시).
