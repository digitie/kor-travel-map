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

**v2 Sprint 1 scaffolding 종료 / Sprint 2 진입 준비**. v1은 `v1` 브랜치
보존, main은 orphan으로 v2 새로 시작. T-014 (코드 작성 단계 진입) 승인 +
PR#17~#26 머지로 Sprint 1 산출물 완료:
- `src/krtour/map/` PEP 420 namespace + category 144건 + dto (Feature +
  5 detail + Coordinate + Source* + FeatureBundle) + core (exceptions +
  ID helpers `make_feature_id`/`make_source_record_key`/`make_payload_hash`) +
  infra skeleton (`crs.py` + `db.py`)
- `.github/workflows/{ci,lint,openapi}.yml` + import-linter 4 계약 활성
- review report (`docs/reports/pr-1-21-review.md`) P0 4건 해소

ADR 현황: **001~034 accepted** (029는 ADR-043으로 supersede). **035~043
proposed** (2026-05-27 사용자 지시 — 운영 단계 진입에 따른 9건 일괄):
- 035 REST API admin 운영 확장 / 036 maplibre-vworld-js v0.1.0 분리
- 037 frontend TanStack Query + Zustand / 038 GitHub Actions CI/CD 재활성화
- 039 CLI mutex (advisory lock) / 040 Backup/Restore + 핫스왑 UI
- 041 kraddr-base 코드 흡수 + 폐기 / 042 datagokr 표준데이터 축제 1차 source
- 043 `@krtour/map-marker-react` npm 게시 보류 (ADR-029 supersede)

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

**개발 환경**: PC 개발은 **WSL ext4** 위에서 (`~/dev/python-krtour-map/`).
NTFS 마운트에서 직접 `git`/`pytest` 실행 금지 — 형제 라이브러리
(`python-kraddr-geo`/`python-kraddr-base`)와 동일 정책. 자세히는 `README.md`
§"개발 환경 (PC, WSL)" + `AGENTS.md` + `docs/dev-environment.md`.

**Claude Code 전용 worktree**: `~/dev/geo-claude/`(메인 repo의 형제).
작업마다 worktree 안에서 브랜치만 새로 (`git switch -c feat/<topic> main`).
worktree마다 [codegraph](https://github.com/colbymchenry/codegraph) 인덱스
1개를 두고(`codegraph init -i` 최초 1회), 이후엔 `codegraph sync`로 증분
동기. `.codegraph/`는 `.gitignore`. 자세히는 `docs/codegraph-worktree.md` +
`AGENTS.md` §"에이전트 worktree + codegraph". ChatGPT Codex는 `geo-codex`,
Google Antigravity 2.0은 `geo-antigravity` worktree를 쓴다.

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
