# ADR-063 — Feature 관측과 큐레이션 collection을 분리한다

- 상태: accepted
- 날짜: 2026-07-13
- 결정자: human + Codex
- 관련: GitHub #665, T-230, ADR-069

## 컨텍스트

`feature.features`는 물리 장소의 현재 정본이지만 provider 원천과 큐레이션은 서로
다른 수명과 식별 규칙을 가진다. 운영 DB에는 이미 한 Feature에 여러 source record가
연결된 사례와 같은 좌표의 여러 Feature가 대량으로 존재한다.

기존 `feature.curated_features`는 테마·묶음 제목·장소 membership을 한 행에 담고
`(theme_id, feature_id)`를 유일하게 만들었다. 따라서 같은 장소가 `2023-2024
한국관광 100선`과 `2025-2026 한국관광 100선`에 동시에 포함되는 사실을 표현할 수
없었다. 큐레이션 지도는 `DISTINCT ON (feature_id)`로 대표 한 행만 남겨 서로 다른
테마와 회차를 숨겼다.

`provider_sync.source_records`는 payload 변경마다 새 행을 보존하지만
`source_links`도 record version마다 생긴다. 이 때문에 현재 provider 관측과 과거
payload 이력이 같은 배열에 섞이고, 기본 상세 조회가 현재값 전부를 안정적으로
정의하기 어렵다.

## 결정

### 1. Feature는 물리 장소 정본으로 유지한다

- 좌표가 같다는 이유만으로 Feature를 자동 병합하지 않는다. 같은 건물 안의 서로
  다른 업소처럼 동일 좌표가 정상인 경우가 있기 때문이다.
- 논리적으로 같은 장소라는 dedup 결정이 내려진 경우에만 master Feature로 병합한다.
- 서로 다른 Feature가 같은 화면 좌표에 있으면 지도는 기존 겹친 마커 선택 흐름으로
  모두 보여준다.

### 2. provider entity와 payload version을 분리한다

`provider_sync.source_entities`를 추가한다.

- identity는 `(provider, dataset_key, source_entity_type, source_entity_id)`다.
- `current_source_record_key`가 현재 immutable payload version을 가리킨다.
- `first_seen_at`, `last_seen_at`으로 entity 수명을 기록한다.
- `source_records`는 `source_entity_key` FK 아래 immutable 이력을 계속 보존한다.
- `source_links`는 Feature와 `source_entity_key`를 연결한다. 같은 provider entity의
  payload 변경은 link를 늘리지 않는다.
- 한 Feature에는 MOIS와 MCST처럼 여러 `primary` 관측이 동시에 존재할 수 있다.

기본 Feature 상세의 `observations[]`는 entity별 현재 record 전부를 반환한다. 과거
payload는 별도 cursor pagination 이력 API에서 반환한다. 같은 payload를 다시 관측한
시점도 현재성에 포함하므로 current와 이력 순서는 `last_seen_at`, `fetched_at`,
`imported_at`, record key 내림차순을 사용한다. 따라서 `A → B → A` 재관측에서도 마지막
관측 A가 current가 된다.

### 3. 큐레이션 collection과 item을 분리한다

`feature.curation_collections`는 다음을 소유한다.

- 안정 `collection_key`
- theme, title, `edition_key`, description
- source, 공개 범위, 상태, metadata

`feature.curation_items`는 collection의 공식 item과 기존 Feature의 선택적 연결을
소유한다.

- `UNIQUE (collection_id, external_item_id, feature_id)` active 제약
- 원천 item 안정키, source record provenance, 순서, 표시 제목·요약
- 선정 상태, 관계, 재사용 정책, metadata
- collection과 item 각각 신뢰된 admin actor의 `created_by`, `updated_by`
- 공식 항목 자체는 항상 저장하며 기존 Feature를 확정하지 못한 경우 `feature_id`는
  null이다. 이 행은 공식 장소명과 주소 hint를 보존한다.

이에 따라 같은 Feature는 서로 다른 collection에 제한 없이 포함될 수 있고, 한 공식
선정 항목이 복합 장소라면 같은 `external_item_id`를 여러 Feature에 연결할 수 있다.
같은 Feature가 한 collection의 서로 다른 하위 코스에 속할 때는 코스별 원천 item
안정키를 보존한다.

### 4. REST는 Feature aggregate와 collection을 정식 계약으로 제공한다

- Feature 단건과 batch의 각 Feature DTO는 `observations[]`, `curations[]`를 반환한다.
- 큐레이션 지도·목록은 Feature별 group과 모든 active membership을 반환한다.
- theme/source/edition 필터는 group을 고르는 `EXISTS` 조건이다. 선택된 group의
  `curations[]`는 관련 active membership 전부를 보존한다.
- Feature group은 `page_size`/`cursor`, collection 목록은
  `(updated_at DESC, collection_id DESC)` keyset `page_size`/`cursor`를 사용하며 모두
  한 페이지 최대 500건이다.
- public collection/item 및 Feature aggregate는 공개·게시·포함 상태만 반환하고 actor
  감사 필드를 제외한다. public `item_count`도 공개 포함 건수만 뜻하며 내부 후보·거절
  건수와 `public_item_count`는 노출하지 않는다. admin collection 상세는 미연결·비공개·보관 item까지 반환하며
  admin collection/item과 Feature 상세에는 `created_by`, `updated_by`를 포함한다.
- admin item은 단건 `PATCH`로 명시적 `feature_id=null`을 포함한 부분 수정을 지원하고,
  `DELETE`는 물리 삭제 대신 item을 보관한다.
- item `POST`는 create-only이며 같은 active identity는 409다. PATCH에서 계약상 nullable인
  필드 외에 명시적 `null`을 보내면 422다. public collection의 hidden/deleted Feature
  연결은 공식 표기만 남긴 미연결 item으로 투영한다.
- DB UUID 식별자는 API 경계에서 검증해 잘못된 값은 422로 거절한다. 생성·`PATCH`는
  active 상태만 허용하고 archive 전환은 `DELETE`로 단일화한다.
- `distinct_by_feature`처럼 데이터를 조건부로 버리는 옵션은 제거한다.

### 5. 큐레이션 CSV는 전용 원자적 import다

- 범용 offline Feature upload와 분리한다. 큐레이션 import는 Feature를 만들거나
  위치를 수정하지 않는다.
- CSV template에는 collection/theme/title/edition/source/item 안정키와 기존
  `feature_id` 또는 이름·주소 매칭 hint를 둔다. 좌표는 identity로 사용하지 않는다.
- 매칭 우선순위는 `feature_id` 정확 일치 → 정규화 이름+주소 유일 일치다.
- 0건 또는 2건 이상 후보는 `unmatched`/`ambiguous`로 반환하고 공식 항목은 미연결
  상태로 저장한다. 잘못된 Feature를 강제로 고르지 않는다.
- CSV 형식 오류는 전체 commit을 막고 rollback한다. preview와 commit은 같은
  정규화 결과를 사용한다.
- dry-run은 쓰기 없이 예상 `inserted`/`updated`/`removed`와 삭제 예정 item 전체를
  `removals[]`로 반환해 authoritative replace의 삭제 범위를 commit 전에 확인하게 한다.
- 이름 후보는 입력 행 전체를 `jsonb_to_recordset` 기반 한 번의 batch query로 매칭한다.
  명시한 `feature_id`는 정확히 조회하고, 이름은 대소문자 무시 정확 일치와 선택적 주소
  hint로 최대 3개 후보를 반환한다.
- commit은 파일에 포함된 collection을 원자적으로 replace한다. CSV에서 빠진 item,
  A→B 연결 변경, 연결↔미연결 변경을 함께 반영하고 `inserted`/`updated`/`removed`를
  반환한다. 같은 파일 재업로드는 세 값이 모두 0이고 관련 `updated_at`도 바꾸지 않는
  완전한 no-op이다.
- 한 파일 안의 동일 미연결 안정키 또는 연결·미연결 혼합 identity는 commit 전에
  거절한다. 한 공식 복합 장소를 여러 Feature에 연결한 행은 허용한다.
- Feature 후보 해소 뒤 실제 identity도 다시 검사한다. 해소 결과가 연결·미연결로 섞이거나
  같은 membership으로 중복되면 dry-run에 행 오류를 반환하고 commit 전체를 막는다.
- 여러 collection의 authoritative replace가 경합하지 않도록 import transaction은
  전용 advisory lock으로 직렬화한다. 대상 collection row lock은 UUID 정렬 순서로
  획득하고, 수동 item 추가·수정·보관도 해당 collection row를 먼저 잠근다. commit
  `removals[]`는 lock 안의 실제 `DELETE ... RETURNING` 결과라 `removed`와 일치한다.

### 6. 호환 계층은 만들지 않는다

현재 계약을 사용하는 외부 소비자가 없다는 사용자 결정에 따라 새 public/admin UI와
Feature aggregate는 collection/item 계약만 사용한다. DB migration은 기존 운영
큐레이션을 새 구조로 변환한다. 기존 source-rule 자동화 writer가 남아 있는 전환 기간에는
`curated_features` 변경 trigger가 collection/item을 즉시 동기화해 split-brain을 막는다.
신규 공식·수동 큐레이션의 정본은 collection/item이며 public 응답은 감사 주체를 노출하지
않고, admin write 감사 주체는 신뢰된 admin proxy context에서만 가져온다.

### 7. 표현력이 큰 데이터를 조용히 버리는 downgrade는 금지한다

0044 migration은 연결된 source entity에 immutable record가 둘 이상 있으면 downgrade를
거절한다. 새 entity link 하나만으로는 구 record별 link의 role·confidence·생성 시각을
정확히 복원할 수 없기 때문이다. 운영자는 이력을 먼저 export하고 명시적으로 정리한 뒤에만
구 스키마로 내릴 수 있다.

0045 migration의 downgrade는 기존 `curated_features`만으로 완전히 재구성할 수 있는
legacy collection/item에만 허용한다. 신규 collection, 수동 변경, 연결/미연결 membership,
collection actor 또는 legacy `selected_by`와 일치하지 않는 item actor처럼 구 flat overlay가
표현할 수 없는 행이 하나라도 있으면 PostgreSQL `P0001` 예외로 transaction 전체를 중단한다.
운영자는 먼저 데이터를 export하거나 명시적으로 정리해야 하며 migration이 이를 조용히
삭제해서는 안 된다.

## 근거

- collection과 membership을 분리하면 테마·회차 제목의 중복과 수정 이상을 없앤다.
- entity와 record version을 분리하면 현재 관측 조회가 index lookup으로 단순해지고
  payload history 보존과 충돌하지 않는다.
- Feature aggregate는 admin UI와 외부 REST가 같은 다중성 의미를 공유하게 한다.
- 좌표 자동 병합 금지는 동일 건물의 서로 다른 장소를 오합치하는 위험을 피한다.

## 결과(긍정)

- 같은 장소의 여러 연도·캠페인·provider 정보를 손실 없이 저장하고 한 번에 조회한다.
- 지도 marker 수와 상세 membership 수를 분리해 렌더 성능을 유지한다.
- 공식 CSV를 repo seed와 운영 import 양쪽에서 같은 계약으로 재사용한다.
- provider 현재값과 이력의 의미가 명확해진다.

## 결과(부정)

- migration이 source link와 기존 큐레이션 데이터를 변환해야 한다.
- curated REST/frontend/Dagster 내부 계약을 함께 바꾸므로 변경 범위가 크다.
- 목록 aggregate의 pagination을 먼저 Feature/collection key로 제한한 뒤 배열을 붙이는
  방식으로 구현하지 않으면 page 경계 오류가 생길 수 있다.

## 후속

- migration 전후 행 수와 orphan 여부를 통합 테스트로 검증한다.
- aggregate SQL은 실제 인덱스 사용을 `EXPLAIN` gate로 확인한다.
- Feature merge는 loser의 source entity link와 curation item을 master로 함께 옮긴다.
- n150 prod에서 공식 seed CSV를 적재하고 실제 중복 회차 Feature로 REST/UI live E2E를
  수행한다.

## 개정 (2026-07-18, ADR-069)

immutable entity/record 분리와 collection/item 결정은 유지한다. provider×dataset identity를 각
entity/record에 문자열로 반복하던 부분은 ADR-069의 DB-owned `provider_datasets` FK로 정규화하고,
record는 부모 entity의 identity를 중복 저장하지 않는다. curation lifecycle은 이 개정의 범위 밖이다.

## 개정 (2026-07-27, T-VN-H13b)

authoritative source 누락과 operator archive를 분리한다. CSV에서 빠진 item은 삭제하지 않고
`source_present=false`로 보존하며 재등장 때 제공자 파생 필드만 갱신한다.
`status`·`curation_relation`·`reuse_policy`와 archived tombstone은 operator-owned 상태다.
`collection_id + external_item_id + feature_id` exact identity는 archived/NULL까지 포함한 DB unique로
한 행만 허용해 tombstone과 공개 active row의 공존을 원천 차단한다.

전환기 `curated_features` trigger도 물리 DELETE/INSERT 대신 같은 보존 규칙을 따른다.
legacy와 canonical 양쪽에 operator provenance를 두고, canonical 운영자 수정은 legacy 공개
표면에도 같은 transaction에서 역동기화한다. legacy DELETE 뒤 같은 `source_record_key`가 새
UUID로 재등장하면 기존 source-absent membership을 복원하되 archived tombstone은 보존한다.

Feature merge는 source presence를 OR하고 `source_updated_at`과 `operator_updated_at`을 각각
provider 필드와 operator override의 독립 revision으로 사용하며 tombstone을 최우선한다. merge,
import, admin write는 모두 collection→item 잠금 순서를 지킨다. `source_present=false` 또는
독립 operator provenance는 구 스키마가 표현할 수 없으므로 0065 downgrade는 해당 durable
state가 있으면 `P0001`로 중단한다. 운영 중 revision write는 실제 쓰기 순서를 보존하기 위해
`clock_timestamp()`를 사용한다. merge가 충돌 해소용으로 archive한 legacy projection은 detached
marker로 canonical source에서 영구 분리하고, legacy admin actor는 요청 body가 아니라 인증
principal에서만 받는다.
