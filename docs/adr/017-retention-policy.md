# ADR-017: 보관 정책

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 (SPEC V8 D-12)
- **컨텍스트**: 데이터별 보관 기간 차이가 크다. 일률 정책은 DB 비대를 부른다.
- **결정**:
  - `place` — 무기한 (폐업 시 `status='inactive'`)
  - `event` — 종료일 +20년
  - `notice` — 종료일 또는 발표일 +1년
  - `price_values` — 카테고리별 기본 10년 (`price_points.retention_days`)
  - `weather_values` — 계획 기준일 +30일, 참조 trip 0건 시 즉시 삭제
  - `route` / `area` — 무기한
  - `source_records` — 대응 feature 보존 기간 이상
- **근거**: SPEC V8 D-12.
- **결과 (긍정)**: 운영 비용 통제. 사용자 가시 데이터 충분.
- **결과 (부정)**: purge job 필요 — Dagster asset로 위임.
- **후속**: `docs/architecture/data-model.md`에 정책 + purge SQL 표준 예시.
