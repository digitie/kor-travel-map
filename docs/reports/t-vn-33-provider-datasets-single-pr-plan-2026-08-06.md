# T-VN-33 — DB 소유 provider dataset 단일 PR 실행 설계

- 상태: P0 보완 계약 검증 완료, 적대 재리뷰 대기
- 날짜: 2026-08-06
- 범위: `T-VN-33A`·`T-VN-33B`·`T-VN-33C`를 **하나의 PR**로 완료한다.
- 선행 검토: 적대적 설계 리뷰 2인(스키마·마이그레이션). 초기안은 공통 P0 네 건으로
  NO-GO였고, 이 문서의 결정으로 해소했다.

## 목표와 비목표

`provider × dataset`의 identity·활성 상태·운영 capability는 PostgreSQL 한 곳이
소유한다. source lineage와 dataset 조작 화면은 이 정본을 조인해 읽고, 코드에 남는
registry는 실행 handler를 찾는 projection일 뿐 pair를 생성하거나 목록의 정본이 되지
않는다.

이번 PR은 33A의 schema/backfill, 33B의 모든 writer/reader cutover, 33C의 legacy
write fence·제거 manifest를 함께 끝낸다. 기존 API/문서 호환은 유지 목표가 아니다.
다만 Wave 순서를 깨지 않기 위해 `notice_states`의 typed range 전환은 T-VN-37,
weather/price 사실·summary 재모델링은 T-VN-38에서 한다. 이 둘은 provider 문자열을
새로 쓰지 않게 하는 임시 shim을 만들지 않고, 해당 task에서 자신의 identity를
`provider_dataset_id`로 원자 전환한다.

## P0 반영 결정

### 1. dataset과 operation의 DB 정본

`provider_sync.provider_datasets`는 다음을 가진다.

- `provider_dataset_id bigint GENERATED ALWAYS AS IDENTITY` PK와
  `(provider, dataset_key)` UNIQUE.
- `provider`, `dataset_key`, `display_name`, `source_kind`, `is_active`.
  identity 문자열은 trim·NFC·길이 112를 DB CHECK로 강제하며, update는 금지한다.
  rename은 `is_active=false`와 새 row 생성으로만 한다.
- versioned `capabilities jsonb`. DB 함수
  `provider_sync.is_valid_provider_dataset_capabilities(jsonb)`와 CHECK가 최상위 키를
  검증한다. 최소 shape는 아래이며 확장은 `extensions` object 안에서만 허용한다.

  ```json
  {
    "schema_version": 1,
    "produces": ["place"],
    "refresh": {
      "target_selector": "none"
    },
    "preview": {"kind": "fixture"},
    "extensions": {}
  }
  ```

  `schema_version`은 JSON number `1`, `produces`는 feature/값/enrichment 산출 종류의
  중복 없는 문자열 배열, `target_selector`는 `none|poi_cache_targets`, `preview.kind`는
  `fixture|none`으로 DB에서 검사한다. refresh의 enable 여부와 허용 scope는 JSON에
  중복하지 않고 operation table만 소유한다. capability·active 상태 변경은 `updated_at`
  trigger가 갱신한다.

`provider_sync.provider_dataset_operations`는
`(provider_dataset_id, operation_key)`를 PK로 하여 enabled operation, operation kind,
허용 scope를 저장한다. refresh operation만 중복 없는 canonical scope 배열을 가지며,
external-system scope는 capability의 `target_selector='poi_cache_targets'`와 DB trigger로
결박한다. Dagster/Python registry는 `operation_key → handler`만 binding한다.
빈 DB는 versioned Alembic seed가 dataset·capability·operation을 같이 넣는다. 새 provider
dataset은 새 seed migration과 handler를 같은 PR에 넣어야 하며, runtime의 자동 `INSERT`는
오타를 새 정본으로 승격하므로 금지한다. API catalog는 이 두 테이블의 DB projection으로
교체하고, seed DB의 active operation 집합과 handler binding 집합의 exact-set test를 둔다.

### 2. immutable record와 mutable observation을 분리

`source_records`는 raw snapshot만 보관한다. `source_entity_key`, `raw_data`,
`raw_payload_hash`, `fetched_at`, `imported_at`만 새 row에 쓴다. raw data는 object이고
payload hash는 lowercase hex 1~64자, entity type/id는 trim·NFC·길이 512를 실제 DDL CHECK로
강제한다. 모든 `UPDATE`는 trigger가 거부한다.

재관측은 raw record를 갱신하지 않는다.

- `source_entities.first_seen_at/last_seen_at`은 entity row lock 아래 단조로 갱신한다.
- `source_entity_heads`는 entity당 정확히 한 current record와 `observed_at`,
  `expires_at`를 가진다. head의 `(source_entity_key, current_source_record_key)` composite
  FK가 다른 entity record를 가리키는 것을 막는다.
- writer는 entity upsert/lock → record `ON CONFLICT DO NOTHING` → deterministic head
  upsert 순서의 한 transaction이다. **incoming `observed_at`**(이번 적재가 실제로
  관측을 완료한 시각)가 head 승격의 권위 축이며 동률은 `source_record_key`로만
  결정한다. 따라서 과거 raw snapshot을 오늘 다시 관측해도 immutable record 시각을
  바꾸지 않고 current head로 승격할 수 있다. `expires_at`은 더 새 `(observed_at,
  source_record_key)` 전이에서만 바뀌며, 더 이른 만료로의 수정도 새 관측 사실이면
  허용한다. stale 관측은 head·만료를 전혀 바꾸지 못한다.
- deferred constraint trigger가 “record가 하나 이상인 entity에는 head가 정확히 하나”를
  commit 시 검사한다. purge는 head를 먼저 유효한 다음 record로 옮기거나 entity와 함께
  제거하는 전용 경로만 사용한다.

따라서 기존 `last_seen_at`/`expires_at`, `source_version`, raw name/address/좌표의
의미를 source record에 다시 두지 않는다. provider 변환은 필요한 원천 필드를 canonical
`raw_data` envelope에 넣고, 현재 관측 만료·재관측 시각은 head가 소유한다. source record
key는 기존 결정식 입력으로 계산하되, 저장 후에는 opaque key로만 취급한다.

### 3. source link와 legacy fence

`source_role='primary'`만 primary 판정이다. migration preflight는 legacy
`is_primary_source`와 role의 불일치를 오류로 중단한다(의미를 조용히 버리지 않는다).
cutover 뒤 reader와 DTO/writer는 boolean을 참조하지 않으며, 물리 열이 남아 있는 기간에는
trigger가 role에서만 파생해 직접 boolean write를 거부한다.

`source_entities`의 legacy provider/dataset/current-pointer, `source_records`의
denormalized identity와 파생 raw 열은 기존 row의 forensic snapshot으로만 남긴다. 새 writer는
이 열에 값을 쓰지 않고 DB fence가 값을 거부한다. 모든 normal reader는
`source_entities → provider_datasets`와 `source_entity_heads`만 조인한다. 정확한
column/constraint/index/trigger/repository/query 목록은 cutover 전에
[`t-vn-33-source-lineage.md`](../removal-manifests/t-vn-33-source-lineage.md)에 고정하고
T-VN-39에서만 물리 삭제한다.

`is_active=false` dataset은 역사 row를 읽을 수는 있으나 기존 row 갱신을 포함해 entity,
operation, policy, sync state, membership, upload, curation/integrity/POI/enrichment write를
전혀 받을 수 없다. direct FK child는 `BEFORE INSERT OR UPDATE` 공용 guard로, indirect
lineage child는 entity→dataset join 공용 guard로 SQLSTATE `23514`를 낸다. parent row는
`FOR SHARE`로 잠가 deactivate와 child write를 직렬화한다. T-VN-33에는 generic bypass를
두지 않으며, purge는 T-VN-39의 별도 권한 경계에서만 설계한다. final-schema rebuild는
새 DB를 만드는 경로라 guard 우회가 아니다.

target freeze에서 이미 직접 guard를 검증하는 물리 경계는
`provider_dataset_operations`, `source_entities`, `notice_states`,
`feature_weather_values`, `current_weather_summary`다. 이번 PR에서 새로 정규화하는
각 table/membership도 같은 trigger를 붙이며, indirect 소유자인 `source_records`와
`source_links`는 `source_entities`의 guard를 통해서만 새 dataset에 귀속될 수 있다.
`contracts/vnext/tvn33-reference-ownership-v1.sql`은 이번 PR matrix의 모든 새 relation,
FK, parent-lock guard를 executable DDL로 고정한다. import event는 `(job_id,
import_job_dataset_id)` 복합 FK로 동일 job의 member만 참조한다. integrity violation이
dataset과 source record를 모두 가지면 source entity를 통해 같은 dataset이어야 하며,
enrichment review는 dataset ID를 중복 저장하지 않고 source entity ownership에서 dataset을
유도한다.

### 4. FK 수렴 matrix

아래는 “9개”라는 옛 최소치를 대신하는 전수 소유 매트릭스다. `이번 PR` 행은
`provider_dataset_id` 또는 정규 membership으로 storage identity를 바꾸며, 문자열은 API
표시용 join projection에서만 만든다.

| 소유 영역 | 이번 PR 처리 | 정규형 |
|---|---|---|
| source entity/record/head/link | 이번 PR | dataset → entity → immutable record + head |
| `provider_sync.provider_sync_state` | 이번 PR | `(provider_dataset_id, sync_scope)` PK |
| notice lifecycle/lineage | 이번 PR | scope가 dataset FK를 소유, lineage는 scope FK |
| `feature.curated_sources`/rules | 이번 PR | source가 dataset FK, rule의 중복 `dataset_key` 제거 |
| refresh policy·offline upload | 이번 PR | dataset FK + scope/checksum identity |
| import job·feature update request | 이번 PR | `ops.import_job_datasets`/`feature_update_request_datasets` membership; root는 member 없음, child 또는 direct request는 1개 이상 |
| import job event | 이번 PR | pair 문자열 제거, job/member join에서 파생 |
| integrity observation scope/run·violation | 이번 PR | scope/run은 dataset FK, violation은 nullable dataset FK 또는 source record에서 파생 |
| POI cache-target feature link | 이번 PR | nullable dataset FK; pair가 없는 generic relation은 NULL |
| enrichment review·managed source file | 이번 PR | pair가 있으면 dataset FK; provider-only file/audit은 명시적 provider-wide 예외이고 가짜 dataset을 만들지 않음 |
| `notice_states` | T-VN-37 | typed range 전환과 함께 dataset FK |
| weather/price history·summary | T-VN-38 | 각 fact identity/summary 전환과 함께 dataset FK |

`import_jobs` root와 multi-dataset request에 단일 FK를 억지로 두지 않는다. member table이
exact pair·scope·member lifecycle을 소유한다. `import_job_events`는 event payload의 pair를
identity로 쓰지 않으며 job/member로 파생한다. provider-only 감사는 dataset FK의 예외임을
명시하고 fake dataset row를 만들지 않는다.

### 5. backfill과 membership의 결정 경계

- seed는 code catalog가 아니라 migration의 versioned data다. 모든 현행 pair의 union을
  dataset row로 만들며, 실제 operation handler가 없는 historical-only pair는
  `is_active=false`·operation 없음으로 seed한다. runtime pair 자동 등록은 없다.
- import job root는 pair를 갖지 않는다. `ops.import_job_datasets` member가 exact dataset과
  scope를 소유하고, pair-specific event는 반드시 그 member FK를 갖는다. root-level event는
  member가 NULL일 수 있으나 provider/dataset 문자열을 쓰지 않는다.
- feature update request도 생성 시점에 resolver가 active dataset member snapshot을 만들고,
  geographic request의 다중 실행은 그 member 집합만 사용한다. direct request는 정확히 하나의
  member를 갖고, 새 pair가 dispatch 중 자동으로 늘어나지 않는다.
- expand 이전에 API/Dagster writer를 drain하고 A/B/C 전체를 하나의 maintenance boundary로
  적용한다. long-lived dual write는 만들지 않는다. source record/head backfill이 끝난 뒤에만
  immutable/head completeness trigger를 설치한다.
- `notice_lifecycle_scopes`/`notice_lineage_states`의 dataset FK 수렴은 T-VN-33이다.
  T-VN-37은 새 typed `notice_states`의 range/current materialization만 소유한다.

## 마이그레이션과 rollback 경계

단일 PR 안에서 Alembic revision은 세 개로 분리한다.

1. **A — expand/seed/backfill.** 새 canonical table·nullable FK·membership을 만들고,
   versioned seed와 기존 모든 pair union을 preflight한다. half pair, blank/trim/NFC/length
   위반, normalized collision, record↔entity denorm 불일치, head 불일치, primary role
   불일치는 오류로 중단한다.
2. **B — 제약 연결.** unique/index는 `CREATE INDEX CONCURRENTLY` 전용 autocommit block에서
   만들고 rerun-safe invalid-index 정리를 포함한다. FK/CHECK는 `NOT VALID`로 추가한 뒤
   validate한다. 모든 FK의 access path index와 scheduler/history EXPLAIN gate를 같이 둔다.
3. **C — cutover/fence.** canonical writer/reader를 켜고 legacy write fence와 immutable
   trigger를 설치한다. C 이후 downgrade는 지원하지 않는다. migration downgrade는 controlled
   refusal이며, 개발 DB는 final schema에서 source ETL을 재실행해 재생성한다.

이 PR은 이전 스키마와의 장기 dual-write/compatibility shim을 만들지 않는다. A/B가 실패하면
transaction 또는 rerun-safe cleanup으로 복구하고, C 뒤에는 final-schema rebuild가 유일한
운영 경계다.

## 검증 계약

- 빈 DB `upgrade head` 후 seed된 모든 active operation의 ETL smoke와 DB catalog/handler
  exact-set drift test.
- prior-head fixture migration: pair count, FK orphan 0, source record checksum, entity/head
  exactness, curation/job/request membership 보존.
- half pair·NFC collision·record/entity mismatch·cross-entity head·role/boolean mismatch가
  controlled migration failure가 되는 fixture.
- immutable record update/legacy write/inactive dataset write를 SQLSTATE로 거부하고, 같은
  raw payload의 재관측이 raw UPDATE 없이 entity/head freshness만 전진하는 concurrency test.
- direct guard, notice/curation/import/integrity의 indirect guard, event의 cross-job member,
  integrity violation의 cross-dataset 조합을 각각 executable rejection fixture로 고정한다.
- operation root/multi-dataset member projection, policy/sync/upload/curation/integrity read-write
  integration, static SQL legacy-reader 금지 gate, provider/dataset filter·scheduler·history
  EXPLAIN gate.
- API/OpenAPI 및 Dagster affected suites, 전체 Python gate, 그리고 n150 격리 final-schema
  destructive reload 뒤 live admin UI E2E. data는 보존 대상이 아니며 fixture/ETL로 재생성한다.

## 적대적 리뷰 반영 기록

| 리뷰 구분 | 판정 | 반영 |
|---|---|---|
| 스키마 리뷰 | 2차 NO-GO → 재리뷰 대기 | inactive guard가 기존 row/indirect lineage를 빠뜨리고 capability와 operation이 refresh 상태를 이중 소유한 P0를 발견. direct/indirect all-write guard, parent shared lock, JSON number type, operation-only enable/scope 및 per-guard rejection fixture로 보완했다 |
| 마이그레이션 리뷰 | 2차 NO-GO → 재리뷰 대기 | head completeness 집계 오류, 이번 PR matrix의 target DDL 부재, final removal manifest 부재 P0를 발견. positive history invariant, exact manifest, 전수 ownership DDL·복합 FK·fixture를 추가했다 |

2차 P0가 0이 되기 전에는 implementation을 시작하지 않는다. 이 문서와 ADR-087, target
contract를 함께 갱신했고 빈 PostGIS DB에서 invariant·fixture·정상 history assertion을
실행했다. 동일 두 관점의 적대 재리뷰에서 P0=0 GO를 받은 뒤에만 implementation을 시작하며,
actual migration/model/API cutover 뒤에는 전체 누적 delta를 다시 리뷰한다.
