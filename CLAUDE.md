# CLAUDE.md — 1쪽 진입 요약

이 파일은 Claude(Claude Code, Claude Agent SDK)가 가장 먼저 읽어야 할 1쪽 요약이다.
정식 정책·결정은 `AGENTS.md`, `SKILL.md`, `docs/decisions.md`가 갖는다.

## 1. 이 저장소가 하는 일

`python-krtour-map`은 TripMate의 지도 데이터 정규화·저장 **함수 라이브러리**다.
한국 공공 API (`python-*-api`) 결과를 `Feature`(place/event/notice/price/weather/
route/area) 계약으로 정규화하고 PostgreSQL + PostGIS에 저장한다.

TripMate ↔ 라이브러리는 **함수 직접 호출**. HTTP가 아니다. 라이브러리가 노출하는
FastAPI 라우터(`krtour_map.api`)는 **디버그 UI 전용 + 향후 내부 활용**으로
인증 없이 내부망에서만 사용한다.

## 2. 현 단계

**v2 설계 단계**. v1은 `v1` 브랜치 보존, main은 orphan으로 새로 시작.
**별도 요청 전까지 코드 작성 금지**. 본 단계 산출물은 문서/계약/결정뿐이다.

v1 산출물 요약: 저장소 루트 `python-krtour-map-spec.docx` (약 80쪽).

## 3. 진입 순서

1. `AGENTS.md` — 지시 우선순위, DO NOT 룰
2. `SKILL.md` — 도메인 어휘, 자주 묻는 작업
3. `docs/architecture.md` — 의존 방향
4. `docs/resume.md` — 다음 한 작업
5. `docs/journal.md` 최신 3건
6. 관련 ADR (`docs/decisions.md`)

## 4. 의존 스택 (v2 확정)

`python-kraddr-geo`와 동일 스택. PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto /
SQLAlchemy 2 async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2 / GeoPandas
+ Shapely 2 + GDAL / Pydantic v2 / FastAPI + Uvicorn / httpx + tenacity / Alembic.

## 5. 절대 금지 (5개만 다시)

1. provider adapter/wrapper 신규 생성 금지 (public client 직접 사용)
2. 의존 방향 역행 금지 (`dto → core → infra → providers → client → api/cli`)
3. ORM에 비즈니스 로직 금지 (raw SQL `text()`만)
4. 공간 쿼리 술어에서 `ST_Transform` 금지 (인덱스 무효화)
5. 디버그 API에 인증 추가 금지 (내부망 전제)

전체 18개 룰은 `SKILL.md` §4.

## 6. 작업 후 체크리스트 (1줄)

`pytest -q` + `ruff check` + `mypy --strict` + `lint-imports` + `docs/journal.md`
+ `docs/resume.md` (+ ADR/CHANGELOG/OpenAPI 해당 시).
