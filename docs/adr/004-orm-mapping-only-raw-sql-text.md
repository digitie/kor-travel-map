# ADR-004: ORM은 매핑만, 쿼리는 raw SQL `text()`

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude
- **컨텍스트**: SQLAlchemy ORM의 query DSL은 PostGIS spatial 함수, window 함수,
  CTE, EXPLAIN 친화성에서 제약이 있다. `kor-travel-geo`는 ADR-004로
  raw SQL repository 패턴을 채택했다.
- **결정**:
  - `infra/models.py`는 SQLAlchemy ORM 매핑(`Table` 객체 또는 declarative
    mapping)만 둔다. 비즈니스 로직 금지.
  - 모든 쿼리는 `infra/*_repo.py`의 `_SQL` 상수에 `sqlalchemy.text()`로 작성한다.
  - 파라미터는 named bind (`:radius_m`), 결과는 row → Pydantic DTO 변환.
- **근거**:
  - EXPLAIN 결과 그대로 재현 가능.
  - 인덱스 hint, `SET LOCAL`, CTE 자유 사용.
  - 통합 테스트에서 EXPLAIN 결과로 인덱스 사용을 검증 가능.
- **결과 (긍정)**: 성능 튜닝 자유도 + 통합 테스트 인덱스 검증 가능.
- **결과 (부정)**: 컬럼 변경 시 raw SQL 참조도 직접 수정 필요 (통합 테스트로
  방어).
- **후속**: `docs/architecture/performance.md`의 모든 쿼리 패턴에 `text()` 예시 포함.
