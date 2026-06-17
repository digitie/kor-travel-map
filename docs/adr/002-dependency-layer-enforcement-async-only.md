# ADR-002: 의존 계층 강제 + async-only API

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude
- **컨텍스트**: v1은 모듈 간 import 방향이 명시되지 않아 `infra` → `dto` 역참조,
  순환 import가 일부 발생했다. 동기/비동기 인터페이스도 혼재했다.
- **결정**:
  - 의존 방향 `dto → core → infra → providers → client → api/cli` 한 방향.
    (현행 체인은 ADR-020으로 `api` 제거 + ADR-023으로 최하단 `category` 추가 →
    `category → dto → core → infra → providers → client → cli`. 본문은 채택 당시
    표기.)
  - `import-linter` 계약으로 CI에서 강제.
  - 동기 인터페이스 신규 추가 금지. `AsyncKorTravelMapClient`만. 호출자가
    `asyncio.run`으로 감싸야 하면 호출자가 책임.
- **근거**:
  - 계층 강제는 리팩토링 자유도를 높인다 (단위 테스트가 Protocol에만 의존).
  - async-only는 FastAPI/SQLAlchemy 2/httpx/asyncpg 스택과 정합.
  - `kor-travel-geo` ADR-002와 동일 패턴.
- **결과 (긍정)**: 단위 테스트가 Fake repo로 100% 가능. 의존 그래프가 안정.
- **결과 (부정)**: 동기 호출자는 명시적으로 `asyncio.run`을 써야 한다.
- **후속**: `pyproject.toml`의 `[tool.importlinter]`에 계약 박힘. CI 워크플로에
  `lint-imports` 추가 (코드 작성 단계).
