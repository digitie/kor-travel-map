# ADR-014: 테스트 4단계 + Coverage 목표

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: 사용자 요청 "테스트케이스는 최대한 촘촘하고 다양하고 꼼꼼하게".
- **결정**:
  - `tests/unit/` — DB 없음, Fake repo. `pytest`, `pytest-asyncio`,
    `hypothesis`.
  - `tests/integration/` — testcontainers PostGIS (`postgis/postgis:16-3.5-alpine`).
  - `tests/e2e/` — 디버그 API + integration DB. `httpx.AsyncClient`.
  - `tests/fixtures/` — replay fixture (provider 호출 녹화/재생).
  - Coverage 목표: `core/ 90%+, infra/ 80%+, providers/ 70%+, 전체 80%+`.
  - 모든 raw SQL은 통합 테스트에서 EXPLAIN 결과로 인덱스 사용 검증.
  - 모든 provider 변환 함수는 fixture 기반 회귀 ≥ 3개 (정상/엣지/실패).
- **근거**: kor-travel-geo 테스트 분리 패턴 + 사용자 요청.
- **결과 (긍정)**: 회귀 차단 + 성능 회귀 차단.
- **결과 (부정)**: 통합 테스트는 Docker 필요 → CI runner 정책 결정 필요.
- **후속**: `docs/test-strategy.md`에 상세 사양.
