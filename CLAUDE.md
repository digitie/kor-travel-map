# CLAUDE.md — 1쪽 진입 요약

이 파일은 Claude(Claude Code, Claude Agent SDK)가 가장 먼저 읽어야 할 1쪽 요약이다.
정식 정책·결정은 `AGENTS.md`, `SKILL.md`, `docs/adr/README.md`가 갖는다.

> **OpenAI Codex / Google Antigravity** 등 `AGENTS.md` 컨벤션을 따르는 AI agent는
> `AGENTS.md`를 entry로 사용한다. 본 라이브러리는 CLAUDE.md + AGENTS.md 두
> 파일만 AI agent entry로 박는다 (Copilot/Cursor 등 IDE-side 룰 파일은 두지
> 않음 — drift 회피).

## 1. 이 저장소가 하는 일

`kor-travel-map`은 한국 공공 API (`python-*-api`) 결과를
`Feature`(place/event/notice/price/weather/route/area) 계약으로 정규화하고
PostgreSQL + PostGIS에 저장·조회·병합하는 한국 여행 지도 데이터 시스템이다.
Python core(`import kortravelmap as ktm`)는 정규화·적재 엔진이고, 외부 경계는
OpenAPI다 — `api`/`dagster`가 이 core를 내부에서 import하고 PinVi는 HTTP로만 호출한다.

vNext 재설계는 **정확성·보안 → 단일 정본/설계적 우월성 → 단순성 → 확장성 → 실측 성능 →
호환성** 순이며, 기존 계약은 계획된 PinVi cutover 외에는 상위 원칙보다 우선하지 않는다
(ADR-066~075).

운영 모델·서비스 구성·역할은 `AGENTS.md` §역할, 배포명·import root·CLI·DB·버킷 등
identity table은 `AGENTS.md` §식별자가 정본이다.

## 2. 현재 기준

> **진척/스프린트 상태·"다음 한 작업"의 단일 정본은 `docs/resume.md` + 백로그
> `docs/tasks.md`다.** 백로그는 2026-06-09부터 **진행/예정은 `docs/tasks.md`(상단에
> 열린 항목 인덱스), 완료·아카이브는 `docs/tasks-done.md`**로 분리됐다. 이 1쪽 요약에는 자주 바뀌는 PR 번호·스프린트 완료여부를
> 박지 않는다(반복 drift 회피 — `docs/reports/docs-consistency-audit-2026-06-06.md`
> DA-D-01). 아래는 잘 바뀌지 않는 기준값만 둔다.

- v1은 `v1` 브랜치 보존, main은 orphan으로 v2 재시작(ADR-001); v1 스펙은 루트 `kor-travel-map-spec.docx`.
- ADR 현황·작성 규약은 `docs/adr/README.md`(다음 후보 번호도 그 상단이 정본 —
  여기 박지 않는다, DA-D-01 drift 회피). 고정 기준값만 아래 둔다.
- **고정 포트(ADR-047)**: API `12701` · admin UI `12705` · Dagster `12702` ·
  Postgres host `5432` · RustFS S3 `12101`/console `12105`.
  ⚠️ **Postgres `5432`는 저장소 standalone 스택 기준이다.** n150 prod의 map DB는
  2026-08-16부터 **전용 인스턴스 `127.0.0.1:12703`**(`kor-travel-map-postgres`,
  loopback 전용)이고, `5432`는 **kor-travel-geo의 인스턴스**다. prod에서 `5432`로
  붙으면 오류 없이 **다른 DB에 연결된다** — 이 함정에 실제로 빠져 잘못된 DB를
  정본으로 보고 결론을 낸 적이 있다(2026-08-15). 자세히는
  `docs/integration-map.md`.
- **geocoding 정본**: kor-travel-geo REST v2 `POST /v2/{reverse,geocode}`, 로컬 기본
  `http://127.0.0.1:12501`(ADR-046/047).
- **frontend 정본**: Next.js 16 + React 19 + `maplibre-gl` + in-repo VWorld style
  builder(`src/lib/vworld-style.ts`). maplibre-vworld-js dep는 #476(T-MAP-VWORLD-04)에서
  제거됨 — ADR-036(v0.1.3 핀)은 무효, 정본은 `docs/architecture/debug-ui-package.md`.
  Playwright e2e는 n150 Linux 환경 우선, Windows 호스트 브라우저는 fallback.
- **coverage gate**: ADR-032 단계 상향 일정(Sprint 4 기준 `fail_under=80`).
- **provider 9단계 구현 순서**(ADR-034): 축제 → 날씨 → 유가 → 휴게소 →
  국립공원/트래킹 → 국가유산 → **MOIS 인허가** → 휴양림/수목원 → 박물관/미술관.
  MOIS-독립 먼저, dedup 룰 검증 후 MOIS bulk, 마지막에 MOIS-sibling.
- Sprint 1~5 plan은 `docs/sprints/` 참조.

## 3. 진입 순서

1. `AGENTS.md` — 지시 우선순위, DO NOT 룰
2. `SKILL.md` — 도메인 어휘, 자주 묻는 작업
3. `docs/sprints/README.md` — Sprint 1~5 계획 + ADR-034 9단계 순서
4. `docs/architecture/architecture.md` — 의존 방향
5. `docs/resume.md` — 다음 한 작업
6. `docs/journal.md` 최신 3건
   (5·6은 2026-07-26 전면 감사 이후만 담는다. 그 이전 기록은 `docs/archive/`로 분리했고
   각 파일 상단 "과거 기록 아카이브" 표가 인덱스다 — 과거 검색은 `rg <패턴> docs/archive/`.
   분리·재분리 규약은 `docs/tasks-rule.md` §8.)
7. 관련 ADR (`docs/adr/README.md`)
8. cross-repo 연동(PinVi/kor-travel-concierge/kor-travel-docker-manager) 작업 시
   `docs/integration-map.md` — 포트·연동 방향·인증·계약 정본 위치 1장 정본

## 4. 스택·환경 (정본 포인터)

- **의존 스택**(PostgreSQL+PostGIS / SQLAlchemy 2 async / Pydantic v2 / FastAPI …):
  `docs/architecture/architecture.md`(의존 방향) + `README.md` 의존 표.
- **provider 로컬 우선 조회 (ADR-044)**: 형제 `python-*-api`는
  `F:\dev\`(WSL `~/dev/`) 로컬 체크아웃을 `Glob`/`Read`로 **먼저** 조회, GitHub fetch는
  로컬에 없을 때만 fallback. 데이터 정합성 1차 책임은 각 provider 라이브러리.
- **개발 환경**(Linux/WSL git·gh·codegraph 단일 실행 + n150 우선 Playwright e2e):
  `docs/dev-environment.md`.
- **worktree + codegraph + MCP 등록**(`Feature` DTO / `make_feature_id` / provider 변환
  수정 전 `codegraph_explore`로 영향도 선평가): `docs/codegraph-worktree.md`. Claude Code용
  MCP 서버는 `.mcp.json`에 등록(`codegraph`/`filesystem`).

## 5. 절대 금지 (가장 중요한 5개)

1. **main에 직접 push 금지** — 모든 변경은 feature branch + PR + **CI green
   후 머지** (ADR-021 + ADR-038 재활성화).
2. **`from kor_travel_map import ...` (flat) 사용 금지** — 항상 `import kortravelmap
   as ktm` 또는 `from kortravelmap import ...` (ADR-054).
3. provider adapter/wrapper 신규 생성 금지 (public client 직접 사용, ADR-006).
4. 의존 방향 역행 금지 — `category → dto → core → infra → geocoding → providers → client → cli`.
   `kortravelmap.api` 없음 (ADR-020).
5. 공간 쿼리 술어에서 `ST_Transform` 금지 (인덱스 무효화, ADR-012).

전체 26개 룰은 `SKILL.md` §4 (ADR-039 CLI mutex / ADR-041 PlaceCoordinate
import 금지 / ADR-043 npm 게시 금지 포함).

## 6. 작업 후 체크리스트 (1줄)

`pytest -q` + `ruff check` + `mypy --strict` + `lint-imports` + `docs/journal.md`
+ `docs/resume.md` (+ ADR/CHANGELOG/OpenAPI 해당 시).
