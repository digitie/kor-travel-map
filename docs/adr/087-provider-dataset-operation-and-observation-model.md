# ADR-087: DB 소유 dataset operation과 immutable observation head

- 상태: accepted
- 날짜: 2026-08-06
- 결정자: human, AI agent

## 컨텍스트

ADR-069는 provider dataset을 DB 정본으로 정하고 source record를 immutable lineage로
정했지만, capability의 최소 shape·빈 DB bootstrap·operation binding·재관측 시각의
소유자를 충분히 고정하지 않았다. 그 상태에서 단순 FK 추가를 하면 코드 catalog가 여전히
pair 정본으로 남고, 동일 raw payload 재관측이 immutable record를 UPDATE하는 모순이 생긴다.

## 결정

1. `provider_datasets`가 identity, active 상태, typed display/source metadata와 versioned
   capability를 DB에서 소유한다. capability는 versioned 산출 metadata(`produces`)만 가지며
   `schema_version`은 JSON number로 고정한다. 실행 enable/preview/refresh/scope를 JSON에
   중복하지 않는다. identity rename은 금지하며 deactivate + 새 row 생성만 허용한다.
2. dataset의 실행 가능 operation은 `provider_dataset_operations`과 refresh scope 정규 child
   `provider_dataset_operation_scopes`에 저장한다. sync state, job/request member, offline
   upload은 `(provider_dataset_id, sync_scope)` FK로 이 child만 참조한다. 코드 registry는
   operation key의 handler binding일 뿐 dataset/pair/capability의 정본이 아니다. 빈 DB는
   versioned migration seed로 bootstrap하고 active DB operation과 handler의 exact set을 검증한다.
3. raw snapshot은 `source_records`에 append-only로 저장한다. 재관측 시각·현재 만료는
   `source_entities`와 `source_entity_heads`가 소유한다. head는 same-entity composite FK와
   deferred completeness trigger로 정확히 하나의 current record를 보장한다. incoming
   `observed_at`이 head 승격의 권위 시간이라 기존 raw snapshot을 재관측해도 raw UPDATE 없이
   head를 전진시킬 수 있으며, stale 관측은 expiry를 포함해 head를 바꾸지 못한다.
4. multi-dataset operation은 scalar dataset FK가 아니라 membership table로 표현한다. event의
   pair는 job/member에서 파생한다. provider-only audit/file은 fake dataset을 만들지 않는
   명시적 예외다.
5. legacy provider/dataset/raw-derived/primary-boolean columns은 T-VN-33C에서 normal read와
   write에서 fence하고, exact removal manifest를 T-VN-39에 넘긴다. compatibility shim과
   long-lived dual write는 만들지 않는다.
6. inactive dataset을 참조한 canonical child/membership의 insert/update/delete와 ownership
   clear·active dataset 간 재귀속은 공용 DB trigger가 SQLSTATE `23514`로 거부한다. direct FK
   child는 parent row shared lock으로 deactivate와 직렬화하고, indirect lineage child는
   entity→dataset join guard를 쓴다. job/request parent lifecycle도 member 전체를 검사한다.
   T-VN-33에는 generic bypass가 없고 purge 권한 경계는 T-VN-39에서 별도로 정한다.
   단, non-deferrable `ON DELETE CASCADE`로 삭제되는 indirect child는 parent row가 이미
   사라진 경우에만 referential action으로 판별해 허용한다. parent가 남은 standalone child
   DELETE는 기존 active guard를 반드시 통과한다.
   import event는 job/member 복합 FK로 다른 job의 member를 참조할 수 없고, source record와
   dataset을 함께 가진 integrity violation은 양자의 dataset 일치도 DB가 검증한다. enrichment
   review는 dataset ID를 중복 저장하지 않고 source entity에서 소유권을 유도한다.

## 결과

- DB를 조회하는 모든 UI/API/ETL 경로가 같은 dataset identity·capability를 사용하며,
  정규화되지 않은 code catalog drift는 fail-closed test로 발견된다.
- raw payload의 history와 mutable freshness가 섞이지 않아 UPDATE 금지와 재관측이 동시에
  성립한다.
- 구현 범위가 넓어 migration은 expand/constraint/cutover 세 revision으로 나뉘며, cutover 뒤
  rollback은 final-schema rebuild/ETL 재실행으로 한정된다.

## 관련 결정

ADR-063의 feature observation, ADR-069의 provider dataset 정본, ADR-075의 DDL 규율을
구체화한다. 이들 결정을 supersede하지 않는다.
