"""``krtour.map.infra`` — DB 어댑터 + 객체 저장소 + sync state.

``infra/``는 SQLAlchemy 2 async + GeoAlchemy2 + asyncpg + raw SQL (`sqlalchemy.
text()`)을 사용한다. ORM 모델은 매핑만 — 모든 쿼리는 `infra/*_repo.py`의
raw SQL (ADR-004).

**Sprint 1 PR#21에서 실제 코드 작성 예정** — 본 PR#17은 placeholder.

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
"""

from __future__ import annotations

__all__: list[str] = []
# Sprint 1 PR#21에서 채워질 예정:
#   - testcontainers PostGIS 통합 테스트 베이스 (conftest.py)
#   - infra/models.py — SQLAlchemy 2 매핑 (Feature/PlaceDetail/...) 최소
#   - infra/feature_repo.py skeleton — raw SQL placeholder
#
# Sprint 2~ 에서 추가:
#   - infra/sync_repo.py (ProviderSyncState)
#   - infra/jobs_repo.py (import_jobs + advisory lock)
#   - infra/file_store.py (S3 호환 객체 저장소)
#   - infra/crs.py (pyproj.Transformer singleton, ADR-030 narrow cache)
