# ADR-069: DB 소유 provider dataset과 immutable lineage 정본

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-5

## 컨텍스트

provider·dataset identity와 capability가 코드 registry, sync state, source entity/record,
operation registry에 반복된다. `source_records`의 denormalized identity는 부모 entity와
일치하도록 강제되지 않아 cross-entity lineage를 만들 수 있다.

## 결정

1. DB가 소유하는 `provider_sync.provider_datasets`를 provider×dataset identity, capability,
   활성 상태의 정본으로 둔다.
2. `source_entities`는 `provider_dataset_id`와 source-native identity의 유일성을 가진다.
   `source_records`는 entity FK, immutable raw payload, payload hash, 수집 시각만 저장하고
   provider/dataset/type/id 중복 컬럼을 제거한다.
3. 현재 record는 entity의 검증된 head pointer로 표현한다. head FK는 같은 entity의 record만
   가리키도록 composite FK 또는 동등한 DB 제약으로 보장한다.
4. `provider_catalog`은 DB capability projection, `operation_registry`는 실행 가능한 operation
   projection으로 명확히 분리한다. 문자열 목록을 별도 정본으로 만들지 않는다.
5. provider/dataset을 참조하는 sync·policy·request·audit 테이블은 `provider_dataset_id` FK로
   수렴시키고 FK 열에는 필요한 인덱스를 둔다.

## 근거

정규화한 identity를 한 곳에서 소유하면 추가 provider가 기존 테이블 의미를 늘리지 않고도
참여하며, lineage 불일치를 DB가 거부한다.

## 결과

- **긍정**: provider capability, source lineage, 실행 가능 operation의 책임이 분명해진다.
- **부정**: 여러 테이블과 코드 registry를 단계적으로 이관해야 한다.
- **전환/rollback**: 전환기에는 denormalized identity에 composite FK를 먼저 추가한 뒤 shadow
  `provider_dataset_id`를 backfill한다. consumer 전환 전에는 구 컬럼을 제거하지 않으며 rollback은
  shadow FK 사용을 중단하는 것으로 한정한다.

## 기존 결정과의 관계

ADR-063의 immutable observation history와 curation collection 중 observation lineage를
확장한다. curation 결정은 변경하지 않는다.
