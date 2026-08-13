# ADR-092 — 큐레이션 membership과 자동 후보를 분리해 단일 쓰기 정본으로 만든다

- 상태: accepted
- 날짜: 2026-08-11
- 결정자: human + Codex
- 관련: ADR-063, ADR-069, ADR-071, T-VN-40A~C

## 컨텍스트

`feature.curated_features`는 source rule이 만든 자동 후보, 운영자 선별 상태, 공개 테마
membership, legacy REST projection을 한 행에 함께 보관한다. 반면 ADR-063에서 도입한
`feature.curation_collections`와 `feature.curation_items`는 공식·수동 collection과 item을
보관한다. 전환기의 양방향 trigger와 `legacy_projection_id`는 두 모델을 동기화하지만,
어느 쪽이 operator-owned 공개 membership의 정본인지와 자동 후보가 public인가를 단일하게
정의하지 못한다.

이 상태에서는 source rule refresh, admin 선별, collection import, Feature merge, Dagster
refresh가 서로 다른 relation을 갱신한 뒤 trigger에 의미 보존을 맡긴다. 특히 `candidate`는
공개 collection item이 아니어도 되는데 legacy overlay의 상태값으로 함께 취급된다. T-VN-36의
base/effective field 정본과 마찬가지로, 이 경계도 한 write 모델과 명시적 command로 수렴해야
한다.

## 결정

### 1. 소비자용 큐레이션 정본은 collection/item 하나다

`feature.curation_collections`와 `feature.curation_items`만 공식·수동 큐레이션 membership의
정본으로 둔다. public Feature aggregate의 `curations[]`, `/v1/curations*`, admin collection
관리, PinVi 소비자는 이 두 relation만 읽는다. collection item은 ADR-063의 source-presence,
archive, import/link decision 규칙을 계속 소유한다.

자동 source rule 결과는 collection item을 직접 만들거나 public membership으로 승격하지
않는다. 운영자 또는 명시적 import command가 collection과 item identity를 선택한 경우에만
canonical item을 만든다. 이 command는 candidate와 target collection을 함께 잠그고 하나의
transaction에서 candidate promotion과 item write receipt를 남긴다.

### 2. 자동 후보는 별도 lifecycle relation으로 분리한다

새 `feature.theme_feature_candidates`는 source rule의 자동 판정만 보관한다. 후보의 안정
identity는 rule·현재 source entity·Feature의 조합이며, source record key와 payload digest는
현재 관측 증거로만 갱신한다. 한 후보 행은 운영자 판단 `review_state`(`open`, `promoted`,
`rejected`)와 현재 rule-qualified 관측 `eligibility_present` 두 축을 가진다. UI의
`withdrawn`은 `eligibility_present=false`인 투영 상태이지 운영자 결정을 덮는 네 번째
값이 아니다. 이 축은 raw source 존재 여부가 아니라 current head/link/Feature effective
projection이 해당 rule을 지금 만족하는지를 뜻한다.
`theme_feature_candidate_transitions` append-only audit은 두 축 변경의
actor, reason, source evidence, transaction correlation을 보존한다.

- rule refresh만 `eligibility_present`를 바꿀 수 있다. provider evidence는 현재
  source-entity head와 Feature link를 확인해야 한다.
- admin은 `open → promoted` 또는 `open → rejected`만 command로 수행한다. promotion은 어떤
  collection에 넣을지 명시해야 하며, source rule이 이를 대신 결정하지 않는다.
- source가 사라지거나 rule/Feature effective selector에서 제외되면
  `eligibility_present=false`가 되지만 `review_state`와 기존 collection item을
  삭제·비공개로 바꾸지 않는다. public membership 수명은 collection/item 정책이 소유한다.
- 다시 나타난 동일 안정 identity는 새 행을 만들지 않고 audited `false → true` 전이로
  복원한다. `promoted`/`rejected` 판단도 보존하며 새로운 source record와 digest를 증거로 남긴다.

`curated_source_rules.default_action`의 legacy `curated` 의미는 후보 생성으로 이관한다.
migration 전 existing 값을 계수·감사하고, collection으로 자동 승격된다는 해석을 허용하지
않는다. rule, theme, source catalog는 후보의 input metadata로 유지하며 T-VN-40에서 불필요한
이름 변경은 하지 않는다.

### 3. writer와 권한 경계를 명시한다

candidate refresh, candidate promotion/rejection, collection import/manual item mutation,
merge target 이동은 각각 named repository/DB command로만 수행한다. runtime의 raw
`INSERT`/`UPDATE`/`DELETE`는 candidate lifecycle, collection membership, legacy overlay에
허용하지 않는다. command owner는 fixed `search_path`, authenticated actor 또는
provider-derived principal, expected revision, source/current-head proof를 검증한다.

provider refresh와 Feature merge는 관계 row lock보다 먼저 **transaction 전체**가 영향 주는
Feature id set을 materialize·dedupe·정렬하고 첫 DML 전에 모든 advisory fence를 공통 획득한다.
bundle 순서대로 하나씩 lock하지 않는다. 그 뒤 lock 순서는 curated theme/source/rule → source
dataset/entity/head → source link → Feature → candidate → collection → item으로 고정한다. source refresh와 promotion, Feature
merge와 candidate reassignment, import와 manual item mutation의 two-session deadlock/serialization
test를 요구한다. 기존 40P01 1회 retry는 이 lock-order 계약의 대체물이 아니다.

### 4. legacy overlay는 forward-only로 제거한다

T-VN-40A/B/C는 순차 논리 단계이되 **하나의 forward-only implementation PR/release**로만
병합한다. 새 legacy write와 양방향 sync trigger를 먼저 막고, consumer가 canonical membership
또는 admin candidate API로 옮긴 뒤 같은 release에서 `feature.curated_features`를 물리 제거한다.
`legacy_projection_id`, legacy detail snapshot, legacy cursor/API, trigger/function/index/ACL과
legacy overlay를 참조하는 merge/Dagster code는 같은 final removal manifest로 삭제한다.

redirect, dual-write, trigger shim, 읽기 compatibility view는 만들지 않는다. cutover 뒤 rollback은
old binary와 new data를 섞어 재가동하는 방식이 아니라 fresh clone/reload만 허용한다.

## 근거

- 후보와 공식 membership의 lifecycle·공개 의미·writer가 다르므로 하나의 status enum으로
  표현하면 상태 전이와 권한이 섞인다.
- collection/item은 공식 source identity와 운영자 결정을 이미 보존하므로 consumer model을
  새로 만들 필요가 없다.
- candidate를 explicit command로 promotion하면 source rule의 점수와 공개 선택을 독립적으로
  감사할 수 있다.
- trigger 동기화 제거는 두 정본의 drift를 사후 복구하는 대신 한 정본에서만 쓰게 한다.

## 결과(긍정)

- public/API/PinVi는 후보·거절 데이터를 우연히 노출하지 않고 canonical membership만 본다.
- admin은 후보 검토와 collection 편집을 분리한 UI와 audit을 제공할 수 있다.
- merge와 provider refresh가 어떤 relation의 row를 public으로 만들 수 있는지 명확해진다.
- T-VN-39 final cutover 전에 legacy overlay catalog reference를 0으로 만들 수 있다.

## 결과(부정)

- source rule refresh, admin UI/API, Dagster asset, merge, OpenAPI/PinVi, live fixture를 함께
  전환해야 한다.
- 기존 `curated` rule과 legacy 행은 migration preflight와 checksum 대조가 필요하다.
- T-VN-32~38 join barrier는 T-VN-36 PR #973의 `main` 병합(`c76ceb7a`)으로 해소됐고,
  2026-08-13 사용자가 ADR-092와 A/B/C 단일 PR 구현을 승인했다. A/B/C를 독립 PR로 나눠
  병합할 수 없다는 제약은 유지한다.

## 후속

- T-VN-40 설계 계획의 writer inventory, exact removal manifest, checksum/ACL/consumer test
  matrix를 review한다.
- 40A에서 current legacy row와 canonical item의 cardinality·orphan·public
  projection checksum을 고정한다.
- 40B에서 candidate relation과 admin-only contract를 도입하고 public/PinVi를 canonical
  membership으로만 검증한다.
- 40C에서 legacy relation과 모든 catalog reference를 삭제한 fresh migration 및 n150 destructive
  live gate를 실행한다.
