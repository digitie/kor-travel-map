"""pytest conftest — Sprint 1 (PR#17 scaffolding + PR#21 통합 테스트 베이스).

- 단위 / lint 테스트는 본 conftest의 fixture 사용 안 함 (각 test 모듈 자체 완결).
- 통합 테스트(``tests/integration/``)는 별도 ``tests/integration/conftest.py``의
  ``pg_container`` / ``pg_engine`` / ``pg_session`` fixture 사용 — testcontainers
  PostGIS (``postgis/postgis:16-3.5-alpine``, ADR-007). Docker 또는 testcontainers
  미설치 시 자동 skip.
"""

from __future__ import annotations
