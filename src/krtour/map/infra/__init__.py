"""``krtour.map.infra`` — DB 어댑터 + 객체 저장소 + sync state.

``infra/``는 SQLAlchemy 2 async + GeoAlchemy2 + asyncpg + raw SQL (`sqlalchemy.
text()`)을 사용한다. ORM 모델은 매핑만 — 모든 쿼리는 `infra/*_repo.py`의
raw SQL (ADR-004).

**Sprint 1 PR#21 (본 PR)**:
- ``crs.py`` — ``pyproj.Transformer`` singleton (ADR-030 narrow cache,
  ``transformer_4326_to_5179`` / ``transformer_5179_to_4326``).
- ``db.py`` — async engine + session factory (``make_async_engine`` /
  ``make_async_session_factory`` / ``normalize_async_dsn``).
- ``tests/integration/conftest.py`` — testcontainers PostGIS fixture base
  (``pg_container`` / ``pg_engine`` / ``pg_session`` / ``feature_schema``).

**Sprint 2 첫 provider 적재 직전 PR**:
- ``models.py`` — SQLAlchemy 2 매핑 (``Feature``/``PlaceDetail``/...)
- ``feature_repo.py`` — raw SQL repository (``_SQL`` 상수 + ``text()``)
- ``source_repo.py``/``sync_repo.py``/``jobs_repo.py``
- ``file_store.py`` — S3 호환 객체 저장소 (RustFS)

ADR 참조
--------
- ADR-002 — async-only (SQLAlchemy 2 async + asyncpg)
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL (EXPLAIN 친화 + 인덱스 hint 자유)
- ADR-007 — PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- ADR-008 — extension은 ``x_extension`` schema에 격리
- ADR-011 — 작업 큐 ``ops.import_jobs`` 영속화 + advisory lock + SKIP LOCKED
- ADR-012 — 공간 쿼리 입력 좌표 1회 변환, 반경은 ``coord_5179`` (meter)
- ADR-013 — bulk insert ``psycopg.copy_*`` 우선, 30k 안전 마진
- ADR-015 — 객체 저장소 S3 호환 (RustFS 1차, MinIO/Ceph/R2 swap)
- ADR-030 — ``functools.cache`` narrow 예외 (``pyproj.Transformer`` singleton)
"""

from __future__ import annotations

from krtour.map.infra.crs import (
    EPSG_UTM_K,
    EPSG_WGS84,
    project_to_4326,
    project_to_5179,
    transformer_4326_to_5179,
    transformer_5179_to_4326,
)
from krtour.map.infra.db import (
    make_async_engine,
    make_async_session_factory,
    normalize_async_dsn,
)

__all__ = [
    # crs (ADR-012 + ADR-030)
    "EPSG_WGS84",
    "EPSG_UTM_K",
    "transformer_4326_to_5179",
    "transformer_5179_to_4326",
    "project_to_5179",
    "project_to_4326",
    # db (ADR-007)
    "make_async_engine",
    "make_async_session_factory",
    "normalize_async_dsn",
]
