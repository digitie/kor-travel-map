# ADR-009: `feature_id` 결정적 생성 (`make_feature_id`)

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude (SPEC V8 D-2)
- **컨텍스트**: 같은 source 데이터가 여러 번 적재되거나 여러 provider에서
  올라올 때 feature가 중복 생성되면 안 된다.
- **결정**:
  - 포맷: `f_{bjd_code}_{kind.value[0]}_{sha1(input)[:16]}`
  - input: `f"{bjd_code}|{kind.value}|{category.value}|{source_type}|{source_natural_key}"`
  - bjd_code 미상 시 `global` 사용.
  - 옵션 `content_hash`: payload 변경 시 새 feature 생성 (기본 None — 동일
    natural key는 같은 feature).
  - 항상 `make_feature_id(...)` 통과. raw string concat 금지.
- **근거**: SPEC V8 D-2 + v1 호환.
- **결과 (긍정)**: idempotent upsert 가능. 같은 입력 → 같은 ID.
- **결과 (부정)**: bjd_code가 변경되면 feature_id가 바뀜 (의도된 동작 — 행정구역
  개편 시 새 feature).
- **후속**: 단위 테스트에 SPEC V8 D-2 입력 예제 fixture 박음.
