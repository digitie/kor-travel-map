# T-VN-40 — 큐레이션 쓰기 모델 단일화 설계 계획

- 상태: 구현 진행 중 — A/B/C 단일 PR
- 기준: T-VN-36 merge head `c76ceb7a`
- 관련: ADR-063, ADR-069, ADR-071, ADR-092(accepted), T-VN-40A~C
- 작성일: 2026-08-11

상세 relation/command/ACL/API/migration 계약은
[`t-vn-40-curation-write-model-detailed-design-2026-08-11.md`](t-vn-40-curation-write-model-detailed-design-2026-08-11.md)를
따른다. 2026-08-13 사용자 승인으로 barrier와 ADR acceptance가 충족됐으며, 구현은 같은
draft PR #974에서만 진행한다.

## 1. 범위와 시작 조건

T-VN-32~38 join barrier는 T-VN-36 PR #973의 `main` 병합(`c76ceb7a`)으로 해소됐고,
2026-08-13 사용자가 ADR-092와 구현 시작을 승인했다. 40A~C는 하나의 forward-only
implementation PR/release로 구현한다. A/B/C는 review와 검증의
순서를 위한 logical phase일 뿐, phase별 migration·writer·consumer를 별도 PR로 merge하지 않는다.

목표는 하나다. 자동 source-rule 후보와 소비자에게 보이는 공식·수동 큐레이션 membership을
서로 다른 relation과 writer로 분리하고, legacy `feature.curated_features` overlay의 양방향
동기화를 완전히 제거한다.

## 2. 현재 inventory와 목표 정본

| 역할 | 현재 relation/경로 | 문제 | T-VN-40 이후 정본 |
|---|---|---|---|
| 테마·source·rule catalog | `curated_themes`, `curated_sources`, `curated_source_rules` | candidate와 public 선택이 `default_action`에 섞임 | catalog input만 유지 |
| 자동 후보/선별 상태 | `curated_features`, `curated_repo.py`, Dagster refresh | 후보·공개·operator state가 한 row에 섞임 | `theme_feature_candidates` + transition audit |
| 공식·수동 membership | `curation_collections`, `curation_items`, `curation_repo.py` | legacy projection trigger와 역동기화 | collection/item만 소비자 membership 정본 |
| 전환기 연결 | `legacy_projection_id`, curated trigger/function, legacy snapshots | 두 writer가 서로를 바꾸며 drift 가능 | 제거 |
| public/admin REST | `/v1/curated-features`, `/v1/curations*`, admin curated route | 후보와 membership 계약이 겹침 | public은 `/v1/curations*`만; 후보는 admin 전용 |
| producer/merge | `curated_features_refresh`, `curated_repo.py`, `merge_repo.py` | legacy overlay 직접 DML | named candidate/collection command |

구현 전 inventory gate는 다음 source를 fail-closed로 목록화해야 한다.

- `src/kortravelmap/infra/curated_repo.py`, `curation_repo.py`, `merge_repo.py`,
  `runtime_privileges.py`, `models.py`
- migration trigger/function/index/constraint/ACL, legacy snapshots와 foreign key
- `packages/kor-travel-map-dagster` curated refresh asset·schedule
- Map API routers, OpenAPI exports, user client, admin frontend, mocked/live fixtures
- PinVi user/admin-detail vendor, curation/weather consumers와 consumer-rollout receipt

단순 `rg curated_features`만으로 완료를 주장하지 않는다. feature schema object의
`pg_depend`, `pg_get_viewdef`, `pg_get_functiondef`, trigger definition, index predicate,
grant를 모두 catalog gate에 포함한다.

## 3. 목표 데이터·writer 계약

### 3.1 자동 후보

`feature.theme_feature_candidates`는 rule 결과의 현재 lifecycle 행이다.

- identity: `rule_id`, `source_entity_key`, `feature_id`의 exact unique. 같은 entity의 새
  source record는 새 후보가 아니라 같은 행의 evidence 갱신이다.
- required provenance: 현재 `source_record_key`, canonical raw payload digest, source rule
  revision/digest, provider dataset, generation time.
- state: `open`, `promoted`, `rejected`, `withdrawn`만 허용한다. 변경은 append-only
  `theme_feature_candidate_transitions`에 old/new state, actor, reason, causation,
  source evidence를 같은 transaction으로 남긴다.
- source refresh는 current source-entity head와 Feature link를 잠근 상태에서만
  open/withdrawn을 결정한다. provider가 candidate를 collection에 넣지 않는다.
- promotion은 target `collection_id`와 expected candidate/item revision을 명시한 admin
  command다. canonical item create/update와 candidate `promoted` transition은 원자적이다.

candidate row의 `feature_id`는 merge에서 일반 direct update로 바꾸지 않는다. merge command가
Feature master/loser, candidate identity collision, collection item linkage를 lock order에 따라
처리한다. 충돌은 자동 승계가 아니라 explicit merge policy와 audit을 요구한다.

### 3.2 공식·수동 membership

`curation_collections/items`는 유일한 public/admin membership 정본이다. source import, manual
item edit, archive, link decision, Feature aggregate `curations[]`는 이 relation만 쓰고 읽는다.
candidate는 collection item의 대체물이 아니며 public response에 노출하지 않는다.

promotion이 canonical item을 만들 때, item의 official external identity·source presence·accepted
link decision은 기존 ADR-063 규칙을 따른다. candidate score/title/summary는 audit 또는
operator suggestion일 뿐 item metadata를 무조건 overwrite하지 않는다.

### 3.3 권한·동시성

runtime role에는 candidate, collection/item, legacy overlay의 raw lifecycle/membership DML을
주지 않는다. 각각의 named procedure/repository가 authenticated principal 또는
provider-derived principal, fixed `search_path`, expected revision, source/current-head proof를
검증한다. procedure owner와 runtime의 table/function privileges는 catalog assertion으로 고정한다.

provider load와 Feature merge는 relation을 잠그기 전에 영향받는 Feature id 각각의 정렬된
`pg_advisory_xact_lock(hashtextextended('tvn40:feature:' || feature_id, 0))`을 공통 획득한다.
merge는 master/loser 두 key를 lexical 순서로, provider refresh는 target 한 key를 잡는다. 그 뒤
전체 row lock order는 다음과 같다.

```
provider dataset/entity/head → source link → Feature → candidate → collection → item
```

refresh/promotion, merge/promotion, import/manual item edit, source-head advance/promotion의
two-session regression은 40P01/재시도 없이 직렬화 또는 정의된 409/40001 결과를 보여야 한다.

## 4. 단일 PR 안의 구현 단계

구현 PR은 40A → 40B → 40C 순서의 migration/command/consumer/removal을 모두 포함하고, final
head에서만 실행·review·merge한다. 중간 head를 서비스에 배포하거나 compatible reader/writer로
보존하지 않는다. 이를 위해 40A의 preflight/fence, 40B의 candidate+consumer cutover, 40C의
physical removal은 같은 PR의 ordered migration과 final acceptance에 함께 들어간다.

### 40A — legacy writer inventory·write fence

1. legacy row의 theme/source/rule/status/Feature/source-record cardinality, canonical item link,
   public projection을 immutable preflight manifest로 export한다.
2. `curated_features`를 직접 쓰는 repository, trigger, Dagster, merge, admin command를
   inventory하고 new legacy write를 DB/ACL/static gate로 막는다.
3. canonical collection/item과 legacy overlay의 mapping을 checksum으로 대조한다. ambiguous
   legacy row는 자동 변환하지 않고 quarantine/reject manifest로 분리한다.
4. 40B procedure와 candidate schema를 적용하기 전까지 어떤 consumer cutover도 켜지 않는다.

### 40B — candidate lifecycle 분리·consumer cutover

1. `theme_feature_candidates`와 immutable transition audit, source proof, named refresh/promotion/
   reject command를 만든다.
2. source rule의 `curated` default action과 existing legacy candidate rows를 candidate lifecycle로
   backfill한다. 자동 collection item 생성은 금지한다.
3. admin candidate review API/UI를 별도로 제공한다. promotion은 collection selection과
   candidate/collection/item revision을 요구하며 canonical item, trusted accepted link decision,
   item pointer, candidate transition을 같은 transaction에서 기록한다.
4. Feature aggregate, public `/v1/curations*`, collection admin, user client, frontend, PinVi는
   canonical collection/item만 읽도록 전환한다. `/v1/curated-features`와 legacy admin surface는
   같은 release에서 제거하며 redirect/no-op parameter를 두지 않는다.
5. legacy curated detail/trip-copy snapshot cache와 admin snapshot path는 새
   `curation-items/{id}/detail-snapshot` direct typed projection으로 대체한다. 새 cache는 만들지
   않으며 PinVi는 canonical item identity만 사용한다.
6. Map OpenAPI exact export 뒤 PinVi user와 admin-detail subset을 같은 Map head로 re-vendor하고,
   compile/no-legacy contract receipt를 consumer rollout manifest에 pin한다.

### 40C — legacy surface fence·제거

1. canonical membership/candidate checksum, API/UI/PinVi cutover, n150 soak acceptance를 확인한다.
2. legacy `curated_features`, `legacy_projection_id`, sync trigger/function, legacy snapshot,
   cursor/DTO/router/client/UI/Dagster/merge branch, index/constraint/ACL/preflight key를
   one-way manifest로 제거한다.
3. `DROP ... RESTRICT`와 catalog zero gate로 남은 dependency를 발견한다. compatibility view,
   dual-write, held binary rollback은 허용하지 않는다.
4. old binary rollback 대신 fresh clone/reload만 runbook에 기록한다. T-VN-39 전에는 normal
   routing이 legacy relation을 참조하지 않아야 한다.

## 5. 완료 검증 matrix

| 범주 | 필수 evidence |
|---|---|
| mapping | legacy/canonical/candidate row counts, orphan zero, duplicate identity zero, ambiguous quarantine exact count |
| candidate | current-head mismatch 거부, initial materialize와 same-state `source_refresh`·`source_reopen`·withdraw exact audit matrix, promotion/reject, immutable transition audit, merge collision |
| membership | CSV/import/manual item/archive/link decision이 candidate와 독립, promotion은 trusted accepted decision/pointer를 원자 기록, public·PinVi snapshot은 published/public collection+trusted link+public Feature만 반환 |
| writer fence | runtime raw candidate/item/legacy DML 42501, procedure command 1 audit, bigint domain-command claim 결박, candidate/collection/item expected revision 412/409, catalog grants exact |
| consumer | public/admin OpenAPI에서 legacy surface 없음, frontend generated types/check, PinVi exact paired vendor compile/no-legacy assertion |
| removal | relation/column/view/function/trigger/index/ACL/static source legacy reference zero; 0074 PK rekey CASCADE/guard 예외 zero; staged removal manifest SHA |
| performance | public collection aggregate와 candidate admin keyset query의 production-shape `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` |
| live | n150 fresh PostGIS→ETL, candidate review→promotion→public collection, merge, withdrawn source, recovery/cleanup, PinVi probe |

## 6. 명시적 비목표와 recovery

- T-VN-40은 T-VN-36 field override registry를 재설계하지 않는다. curation writer는 그
  Feature state/public projection 계약을 소비할 뿐이다.
- automatic candidate를 public collection으로 보이게 하는 compatibility shim을 만들지 않는다.
- legacy row를 보존하려고 새 API status나 view를 유지하지 않는다. 필요한 이력은 export/audit
  relation과 removal manifest에 보전한다.
- cutover 후 오류 recovery는 old binary 재기동이 아니라 fresh clone/reload 및 canonical
  manifest 재적용이다.

## 7. 구현 시작 전 승인 질문

ADR-092의 다음 사항은 barrier 해소 뒤 **단일 A/B/C implementation PR** 전에 human approval로
accepted 해야 한다.

1. candidate stable identity를 `(rule_id, source_entity_key, feature_id)`로 고정한다.
2. source rule의 `curated` action은 automatic public membership이 아니라 candidate creation으로
   해석한다.
3. public legacy curated endpoint를 redirect 없이 제거하고 candidate API는 admin 전용으로 둔다.
4. legacy overlay와 bidirectional sync를 held compatibility 없이 final release에서 물리 삭제한다.
