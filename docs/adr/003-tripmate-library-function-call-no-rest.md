# ADR-003: TripMate ↔ 라이브러리는 함수 호출 (REST 없음)

- **상태**: accepted, **TripMate 연동/운영 배포 모델은 ADR-045로 superseded**
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: SPEC V8은 TripMate Admin / Dagster asset / API 라우터에서
  feature 데이터를 사용한다. 라이브러리를 별도 HTTP 서비스로 띄울지, 같은
  process에서 함수 호출할지 결정 필요.
- **결정**: TripMate는 본 라이브러리를 `pip install`하고 `AsyncKorTravelMapClient`를
  함수 호출한다. HTTP는 사용하지 않는다.
- **근거**:
  - 두 코드베이스가 같은 운영 환경(Odroid 단일 노드)에서 동작.
  - HTTP layer overhead 없음, 직렬화/역직렬화 비용 없음.
  - DB connection pool/transaction 공유 가능.
  - Pydantic DTO를 그대로 주고받음 — 타입 안전성 유지.
- **결과 (긍정)**: 운영 단순화 + 성능 향상 + 디버깅 용이.
- **결과 (부정)**: 라이브러리 변경 시 TripMate 재배포 필요 (단일 venv).
- **후속**: 라이브러리는 자체 client/engine을 생성하지 않고 모두 주입받는다.
  단, TripMate와의 운영 연동은 2026-06-01 ADR-045 이후 함수 직접 호출이 아니라
  Docker로 운영되는 독립 kor-travel-map 프로그램의 OpenAPI 호출을 기준으로 한다.
  `AsyncKorTravelMapClient`는 독립 프로그램 내부 구현과 단위/통합 테스트용 public
  Python API로 유지한다.
