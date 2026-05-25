# GitHub Copilot 작업 가이드 — `python-krtour-map`

> 본 파일은 **GitHub Copilot이 자동으로 읽는** 프로젝트별 지시문이다
> (`https://docs.github.com/en/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot`).
> 다른 AI agent (Claude Code, Codex, Cursor 등)도 동일한 정책을 따른다 —
> source of truth는 `AGENTS.md`.

## 진입 순서 (어느 AI agent든)

1. **`AGENTS.md`** — 지시 우선순위, DO NOT 룰, TripMate 경계, 개발 환경 정책 (cross-agent 표준 entry).
2. **`SKILL.md`** — 도메인 어휘, 자주 묻는 작업, 22개 DO NOT 룰.
3. **`CLAUDE.md`** — Claude Code 전용 1쪽 요약 (다른 agent도 참고 가능).
4. **`README.md`** — 프로젝트 정체성, 빠른 시작.
5. **`docs/sprints/README.md`** — Sprint 계획 + ADR-034 구현 순서.
6. **`docs/resume.md`** — 현재 진척도, 다음 한 작업.
7. **`docs/journal.md`** 최신 3건 + 관련 ADR (`docs/decisions.md`).

## 핵심 제약 (반드시 준수)

### 개발 환경 (PC, WSL)

PC 개발은 **WSL ext4** 위에서만 수행한다 (`~/dev/python-krtour-map/`).
NTFS 마운트(`/mnt/<drive>/...`)에서 직접 `git`/`pip`/`pytest`/`uvicorn`/
`alembic`을 실행하지 않는다 — 파일 권한, inotify, 심볼릭 링크, 대량 I/O
성능 모두 저하된다. **형제 라이브러리** (`python-kraddr-geo` /
`python-kraddr-base` / `python-knps-api` 등)와 **동일 정책**.

자세히는 `README.md` §"개발 환경 (PC, WSL)" + `AGENTS.md` §"개발 환경
정책 (PC, WSL)" + `docs/dev-environment.md`.

### 절대 금지 (Top 5)

1. **main 직접 push 금지** — 모든 변경은 feature branch + PR (ADR-021).
2. **`from krtour_map import ...` (flat) 사용 금지** — 항상
   `from krtour.map import ...` (ADR-022, PEP 420 implicit namespace).
3. **provider adapter/wrapper 신규 생성 금지** — public client 직접 사용
   (ADR-006).
4. **의존 방향 역행 금지** — `category → dto → core → infra → providers →
   client → cli`. `krtour.map.api` 없음 (ADR-020).
5. **공간 쿼리 술어에서 `ST_Transform` 금지** — 인덱스 무효화 (ADR-012).

전체 22개 룰은 `SKILL.md` §4.

### 의존 스택 (v2 확정)

`python-kraddr-geo`와 동일. PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto /
SQLAlchemy 2 async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2 /
GeoPandas + Shapely 2 + GDAL / Pydantic v2 / FastAPI + Uvicorn / httpx +
tenacity / Alembic.

## 작업 후 체크리스트

`pytest -q` + `ruff check` + `mypy --strict` + `lint-imports` +
`docs/journal.md` + `docs/resume.md` (+ ADR/CHANGELOG/OpenAPI 해당 시).

---

본 파일은 GitHub Copilot, Cursor (`.cursorrules` mirror), 기타 AI agent가
자동으로 읽도록 박혀 있다. 정책 변경은 `AGENTS.md` (source of truth) 수정
후 본 파일에 sync.
