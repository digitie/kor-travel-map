# ADR-008: PostGIS extension은 `x_extension` schema에 격리

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 (kor-travel-geo ADR-018 미러)
- **컨텍스트**: TripMate 단일 DB에 `kor-travel-map`과 다른 도메인이 공존한다.
  PostGIS / pg_trgm / pgcrypto가 `public` schema에 설치되면 dump/restore,
  search_path 관리, schema 충돌이 복잡해진다.
- **결정**:
  - `CREATE SCHEMA IF NOT EXISTS x_extension;`
  - `CREATE EXTENSION postgis WITH SCHEMA x_extension;` (postgis_topology,
    pg_trgm, pgcrypto 동일).
  - 세션 `SET search_path = public, x_extension;` 또는 DSN options.
- **근거**: kor-travel-geo ADR-018. dump/restore 안전성. schema 충돌 회피.
- **결과 (긍정)**: TripMate의 다른 라이브러리(`kor-travel-geo` 등)와 같은
  DB에서 공존 가능.
- **결과 (부정)**: search_path 설정을 잊으면 `function st_makepoint does not
  exist` 같은 에러. 통합 테스트 setup에서 강제.
- **후속**: Alembic env에서 search_path 자동 설정. CI 통합 테스트 fixture에
  포함.
