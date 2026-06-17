# ADR-013: bulk insert는 `psycopg.copy_*` 우선, 안전 마진 30k 파라미터

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude (kor-travel-geo SKILL.md §4-12 미러)
- **컨텍스트**: PostgreSQL 프로토콜은 한 쿼리당 최대 65,535개 파라미터.
  `INSERT ... VALUES (?, ?, ?)` × row 수가 이 한도를 넘으면 에러. v1에서 일부
  적재 path가 이 한도에 부딪혔다.
- **결정**:
  - row × column ≥ 30,000 가능성 있는 적재는 처음부터
    `psycopg.AsyncConnection.cursor().copy("COPY ... FROM STDIN")` 사용.
  - SHP/GeoJSON 적재는 `gdal.VectorTranslate(..., options=["-lco",
    "PG_USE_COPY=YES", "-lco", "FID=feature_id"])` 사용.
  - 안전 마진: 한도의 절반(30k) 권장.
- **근거**: kor-travel-geo 운영 검증. `price_values`, `weather_values`, krheritage
  SHP가 직접 영향.
- **결과 (긍정)**: 대용량 적재 안정성. 메모리도 절감.
- **결과 (부정)**: `psycopg.copy_*`는 SQLAlchemy session과 별도 connection
  관리 필요 → repository 패턴 명시.
- **후속**: `docs/architecture/performance.md`에 표준 예시. `infra/bulk.py` helper.
