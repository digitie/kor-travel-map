# ADR-071: Field-level override 단일화

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-7

## 컨텍스트

provider upsert의 whole-row 동결과 `ops.feature_overrides`가 같은 보정 책임을 나눠 가진다.
한 필드를 보호하려고 행 전체를 동결하면 다른 provider 최신값이 반영되지 않고 upsert SQL의
분기 수가 계속 늘어난다.

## 결정

1. 수동 보정은 `(feature_id, field_path)` active UNIQUE를 가진 field-level override 한 곳에서
   소유한다.
2. provider base value와 override value를 분리 저장하고 effective projection이 필드별로 합성한다.
   source value 변경 시에도 override와 provenance를 보존한다.
3. whole-row freeze와 provider upsert의 field별 `CASE` 복제를 제거한다. status reactivation 방지는
   직교 상태 전이와 명시적 override 정책으로 표현한다.
4. 허용 `field_path`, 값 type, 적용 가능한 subtype을 registry/DB 제약으로 검증한다.

## 근거

보정 단위를 실제 변경 단위인 필드로 맞추면 provider freshness와 운영자 의도를 동시에 보존하고
upsert 경로를 단순화할 수 있다.

## 결과

- **긍정**: 보정되지 않은 필드는 계속 최신화되고 override 감사·해제가 일관된다.
- **부정**: effective projection 비용과 기존 whole-row 동결 해석의 이관이 필요하다.
- **전환/rollback**: whole-row freeze를 field override로 materialize한 뒤 effective 결과를 대조한다.
  projection 전환은 ADR-070 subtype 전환과 독립적으로 수행하며 rollback 시 기존 freeze 판정을
  다시 사용하되 생성된 override 행은 삭제하지 않는다.

## 기존 결정과의 관계

ADR-046에서 도입한 override 저장 방향(`ops.feature_overrides`)을 완결한다. ADR-070과 독립
채택·독립 rollback한다.
