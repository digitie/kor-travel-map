# ADR-068: Feature UUID 정본 identity와 legacy alias

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-4

## 컨텍스트

현행 `f_*` ID는 SHA-1 64-bit prefix이며 `bjd_code`와 `category` 같은 수정 가능한 속성을
입력으로 사용한다. 충돌 확률과 속성 보정에 따른 재키잉 때문에 장기 정본 PK로 사용할 수 없다.

## 결정

1. Feature 정본 PK를 애플리케이션이 생성하는 UUID surrogate로 전환한다. UUIDv7을 채택할 경우
   생성기와 정렬 의미를 코드·테스트에서 고정한다.
2. provider identity는 `(provider_dataset_id, source_entity_type, source_entity_id)`의
   `UNIQUE`로 보장한다. `bjd_code`, `category`, 이름과 좌표는 identity 입력이 아니다.
3. 기존 `f_*` 값은 `feature.feature_aliases(alias, feature_id, alias_kind)`의 legacy alias로
   보존한다. 신규 API는 UUID를 opaque string으로 전달하고 alias lookup은 전환·복구 경계에서만
   제공한다.
4. FK와 외부 참조는 shadow UUID 컬럼을 backfill한 뒤 단계적으로 전환한다. PinVi는 검증된
   alias map으로 소비 데이터를 DB-to-DB 이관한다.

## 근거

surrogate identity와 provider 자연키의 유일성을 분리하면 변경 가능한 표시 속성이 PK를 바꾸지
않고, 충돌 가정을 정본 무결성에서 제거할 수 있다.

## 결과

- **긍정**: Feature identity가 속성 보정과 provider 확장에 독립적이다.
- **부정**: 전 FK와 PinVi 참조를 바꾸는 대규모 shadow migration이 필요하다.
- **전환/rollback**: alias와 양쪽 FK를 유지한 채 read/write를 UUID로 전환한다. soak 전 rollback은
  legacy alias projection으로 되돌리고 UUID 데이터를 보존한다. alias 제거는 별도 PR과 복구
  검증 뒤에만 수행한다.

## 기존 결정과의 관계

ADR-009의 결정적 `f_*` 정본 PK 결정을 supersede한다. 구 ADR-057의 concierge 안정 candidate ID와
구 ADR-058의 geocoder fail-fast는 provider 자연키·수집 정합성 규칙으로 유지하되 Feature PK 생성
규칙은 아니다.
