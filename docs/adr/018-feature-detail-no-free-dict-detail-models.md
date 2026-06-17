# ADR-018: `Feature.detail` 자유 dict 금지 (`DETAIL_MODELS` 분기 강제)

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: Claude (v1 산출물 보강)
- **컨텍스트**: v1은 `Feature.detail: dict | None`이라 자유 dict 우회 path가
  열려 있었다. 결과적으로 detail 필드 변경이 통제되지 않았다.
- **결정**:
  - `Feature.detail`은 `PlaceDetail | EventDetail | NoticeDetail | RouteDetail
    | AreaDetail` 중 하나의 Pydantic 인스턴스를 받는다.
  - DB write는 `.model_dump(mode='json')`만, read는 `DETAIL_MODELS[kind]
    .model_validate(...)`만.
  - 자유 dict 입력은 ValidationError.
- **근거**: Spec V8 D-3~D-12 + 통제 강화.
- **결과 (긍정)**: detail 필드 변경이 ADR과 함께만 가능.
- **결과 (부정)**: 새 필드 추가 시 마이그레이션 + DTO 동시 수정 필요.
- **후속**: 통합 테스트에서 free-dict 입력 케이스가 ValidationError로 끝나는지
  검증.
