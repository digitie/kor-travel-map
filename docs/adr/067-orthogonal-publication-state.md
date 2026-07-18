# ADR-067: 직교 상태 모델과 단일 공개 projection

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-3

## 컨텍스트

현행 `status`, `deleted_at`, `user_deleted_at`, `user_change_status`는 의미가 겹치고 결합
제약이 없다. endpoint별 공개 술어가 달라 provider-retired feature가 사라지는 동시에
draft·broken feature가 노출되는 양방향 오분류가 발생한다.

## 결정

1. 상태를 `lifecycle_state(active|retired)`,
   `publication_state(draft|published|suppressed)`,
   `quality_state(valid|quarantined)`의 직교 3축으로 저장한다.
2. 공개 가능한 행은 `active AND published AND valid` 하나뿐이다. 이 술어를
   `feature.public_features` view로 정의하고 같은 술어의 base-table partial index를 둔다.
3. detail, batch, bbox, search, nearby, cluster, 향후 tile, collection 등 모든 공개 payload
   projection은 이 view를 사용한다. service state classifier만 base 상태를 읽되 비공개 payload는
   반환하지 않는다.
4. service batch item은 `found`, `retired`, `suppressed`, `missing`, `unchanged`와
   `revision`을 반환한다. transport 실패는 503이며 `missing`으로 합성하지 않는다.
5. soft-delete 시각은 lifecycle 전이 감사 이력으로 흡수한다. 불가능한 조합은 DB `CHECK`로
   거부하고, 기존 보관 기간은 ADR-017을 따른다.

## 근거

각 endpoint에 조건을 추가하는 방식은 같은 결함을 반복한다. 상태 의미를 분리하고 공개 정본을
한 곳에 두어야 분류와 인덱스가 같은 계약을 사용한다.

## 결과

- **긍정**: 공개 여부와 운영 상태를 독립적으로 바꿀 수 있고 모든 표면이 동일하게 판정한다.
- **부정**: 기존 네 상태 축의 의미를 명시적으로 매핑하는 데이터 이관이 필요하다.
- **전환/rollback**: 먼저 현행 컬럼 위에 view를 도입하고 공개 SQL을 전환한 뒤 shadow 3축을
  검증한다. 3축 전환 rollback은 view를 검증된 이전 projection으로 돌리고 shadow 컬럼은 보존한다.

## 기존 결정과의 관계

ADR-017의 보관 기간과 purge 원칙은 유지한다. 공개 상태와 보관 상태를 같은 필드로 표현하던
부분만 이 ADR이 대체한다.
