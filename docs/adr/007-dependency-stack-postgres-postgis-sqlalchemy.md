# ADR-007: 의존 스택 — Postgres + PostGIS + SQLAlchemy 2 async + GeoAlchemy2 + GeoPandas

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: `kor-travel-geo`가 동일 운영 환경에서 PostgreSQL 16 +
  PostGIS 3.5 + SQLAlchemy 2 async + asyncpg + psycopg + GeoAlchemy2 +
  GeoPandas 조합으로 검증되어 있다. 본 라이브러리도 동일 스택을 채택해 운영
  환경을 일원화한다.
- **결정**: v2 의존 스택 확정.
  - DB: PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
  - ORM/SQL: SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2
  - 공간: GeoPandas, Shapely 2, GDAL Python binding
  - 모델: Pydantic v2
  - HTTP (디버그 API): FastAPI + Uvicorn
  - HTTP client: httpx + tenacity
  - 마이그레이션: Alembic
  - Lint/Type: ruff + mypy --strict + import-linter
  - Test: pytest + pytest-asyncio + hypothesis + testcontainers-python + VCR.py
- **근거**: kor-travel-geo와 환경/지식 공유, ARM64 cross-build 모두 검증됨.
- **결과 (긍정)**: 두 라이브러리의 운영자/에이전트가 같은 stack을 다룸.
- **결과 (부정)**: 신규 stack 도입(예: Polars)을 하려면 ADR 필요.
- **후속**: `pyproject.toml`에 의존성 반영. provider 라이브러리 git URL +
  commit sha 핀은 코드 작성 단계에서 ADR과 함께 확정.
