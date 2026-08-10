# T-VN-40 — 큐레이션 단일 writer 상세 설계

- 상태: 설계 초안 — 구현/DDL 실행 금지
- 기준: T-VN-36 final head `858a1684`
- 상위 결정: ADR-063, ADR-069, ADR-071, ADR-092(proposed)
- 실행 단위: T-VN-40A/B/C 단일 forward-only implementation PR/release
- 작성일: 2026-08-11

## 1. 설계 경계

이 문서는 T-VN-40 구현의 사전 계약이다. 아래 relation, procedure, API는 **설계 이름과
acceptance**이며, 이 문서 PR에서 migration이나 application code를 생성하지 않는다. T-VN-32~38
join barrier와 ADR-092 human acceptance 전에는 이 문서의 어떤 DDL도 적용하지 않는다.

구현 때 A/B/C는 별개 release가 아니다. maintenance window에서 구 API/Dagster를 완전히 멈추고,
같은 PR의 ordered migration을 적용한 뒤 final binary만 시작한다. 새 candidate schema만 가진
중간 binary, legacy overlay를 쓰는 new binary, compatibility view/trigger를 가진 중간 서비스는
허용하지 않는다.

## 2. relation 역할과 소유권

| relation | 수명 | writer | reader | 금지 |
|---|---|---|---|---|
| `curated_themes`, `curated_sources`, `curated_source_rules` | catalog/rule input | typed catalog command | candidate refresh, admin | rule이 public membership을 직접 만들기 |
| `theme_feature_candidates` | 자동 후보의 현재 lifecycle | provider refresh, admin promote/reject, merge command | admin candidate API만 | public/API/PinVi 직접 read, runtime raw DML |
| `theme_feature_candidate_transitions` | 후보 전이의 보존 audit | candidate command trigger만 | admin timeline | UPDATE/DELETE/TRUNCATE, candidate와 FK cascade |
| `curation_collections`, `curation_items` | 공식·수동 membership | typed import/manual/promotion command | public/admin Feature aggregate, PinVi | legacy trigger 또는 source rule direct write |
| `curated_features`와 legacy snapshot | transition overlay | 없음 | 없음 | T-VN-40 final head 이후 relation/ACL/reference 존재 |

`curation_items.status='candidate'`는 공식 source item이 아직 운영자 검토 중인 경우에만 쓴다.
이는 자동 rule 결과인 `theme_feature_candidates.state='open'`과 다른 domain이다. public inclusion은
collection이 `published`/`public`, item이 `included`, item source가 present, 연결 Feature가
ADR-067 public predicate를 만족하는 경우에만 성립한다.

## 3. 후보 data model

### 3.1 `feature.curated_source_rules` 보강

T-VN-40은 rule 자체에 다음을 추가한다.

```sql
ALTER TABLE feature.curated_source_rules
  ADD COLUMN row_revision bigint NOT NULL DEFAULT 1,
  ADD CONSTRAINT ck_curated_source_rules_revision_positive
    CHECK (row_revision >= 1),
  DROP CONSTRAINT ck_curated_source_rules_action,
  ADD CONSTRAINT ck_curated_source_rules_action
    CHECK (default_action IN ('candidate', 'ignore'));
```

- catalog command는 실제 내용 변경 때만 `row_revision`을 1 증가시킨다. 직접 `UPDATE`와
  no-op timestamp write는 DB trigger/ACL로 거부한다.
- legacy `default_action='curated'`는 preflight에서 정확히 계수한다. backfill은 이를
  `candidate`로 바꾸고 자동 collection item 생성은 하지 않는다.
- rule의 `theme_id`, `source_id`, selector, region/category/kind, enabled, priority가 후보
  판단 input이다. candidate row에는 이 값을 중복 저장하지 않고 `rule_id`와
  `rule_row_revision`만 저장한다.

### 3.2 rule generation receipt

후보 withdrawal은 Dagster run id 문자열이나 incremental refresh의 “없음”을 근거로 하지 않는다.
T-VN-40은 rule evaluation의 complete input을 명시하는 generation receipt를 둔다.

```sql
CREATE TABLE feature.theme_candidate_generations (
  generation_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  rule_id uuid NOT NULL
    REFERENCES feature.curated_source_rules(rule_id) ON DELETE RESTRICT,
  rule_row_revision bigint NOT NULL CHECK (rule_row_revision >= 1),
  generation_kind text NOT NULL CHECK (
    generation_kind IN ('provider_full_snapshot', 'rule_reconcile', 'legacy_backfill')
  ),
  source_job_id uuid REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT,
  generation_key text NOT NULL UNIQUE,
  state text NOT NULL DEFAULT 'running'
    CHECK (state IN ('running', 'succeeded', 'failed')),
  source_head_set_hash text
    CHECK (source_head_set_hash ~ '^[0-9a-f]{64}$'),
  observed_candidate_count bigint NOT NULL DEFAULT 0
    CHECK (observed_candidate_count >= 0),
  withdrawn_candidate_count bigint NOT NULL DEFAULT 0
    CHECK (withdrawn_candidate_count >= 0),
  started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  completed_at timestamptz,
  CONSTRAINT ck_theme_candidate_generations_shape CHECK (
    (state = 'running' AND completed_at IS NULL AND source_head_set_hash IS NULL)
    OR
    (state = 'succeeded' AND completed_at IS NOT NULL AND source_head_set_hash IS NOT NULL)
    OR
    (state = 'failed' AND completed_at IS NOT NULL)
  ),
  CONSTRAINT ck_theme_candidate_generations_source_job CHECK (
    (generation_kind = 'provider_full_snapshot' AND source_job_id IS NOT NULL)
    OR generation_kind <> 'provider_full_snapshot'
  )
);

CREATE INDEX idx_theme_candidate_generations_rule_completed
  ON feature.theme_candidate_generations
    (rule_id, completed_at DESC, generation_id DESC)
  WHERE state = 'succeeded';

CREATE TABLE feature.theme_candidate_generation_observations (
  generation_id uuid NOT NULL
    REFERENCES feature.theme_candidate_generations(generation_id) ON DELETE RESTRICT,
  candidate_id uuid NOT NULL,
  source_entity_key text NOT NULL,
  feature_id text NOT NULL,
  source_record_key text NOT NULL,
  candidate_input_hash text NOT NULL
    CHECK (candidate_input_hash ~ '^[0-9a-f]{64}$'),
  observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (generation_id, candidate_id),
  CONSTRAINT uq_theme_candidate_generation_observation_identity
    UNIQUE (generation_id, source_entity_key, feature_id)
);
CREATE INDEX idx_theme_candidate_generation_observations_candidate
  ON feature.theme_candidate_generation_observations (candidate_id, generation_id DESC);
```

`provider_full_snapshot` generation은 complete authoritative provider load의 `ops.import_jobs`
receipt와 matching dataset/source scope를 procedure가 검증한 경우에만 성공할 수 있다. incremental
load는 generation을 만들거나 withdrawal을 호출할 수 없다. `rule_reconcile`은 rule revision 변경
후 existing current heads 전체를 다시 판단하는 explicit job이고, `legacy_backfill`은 migration
only다. `generation_key`는 rule revision, job/reconcile identity, canonical input을 합친 immutable
key라 duplicate replay를 구분한다.

`source_head_set_hash`는 rule scope의 ordered `(source_entity_key, current_source_record_key)` set을
procedure가 직접 SHA-256으로 계산한 값이다. generation은 `SERIALIZABLE` transaction에서
rule/source-head/link/Feature/candidate를 같은 lock order로 처리한다. 각 match는 durable
`theme_candidate_generation_observations` 한 행을 남긴다. 따라서 candidate input hash가 동일하면
candidate 자체의 `updated_at`/`row_revision`을 바꾸지 않아도 generation coverage를 증명할 수 있다.
성공 completion은 해당 rule의 `open` candidate 중 completion generation observation이 없는 행만
withdraw한다. head가 진행 중 바뀌면 transaction은 `40001`로 retry한다. candidate list와 promotion
procedure도 current source head를 다시 확인하므로, incomplete/old generation의 open row가 실제
promotion을 통과할 수 없다.

### 3.3 현재 후보 relation

```sql
CREATE TABLE feature.theme_feature_candidates (
  candidate_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  rule_id uuid NOT NULL
    REFERENCES feature.curated_source_rules(rule_id) ON DELETE RESTRICT,
  source_entity_key text NOT NULL
    REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT,
  feature_id text NOT NULL
    REFERENCES feature.features(feature_id) ON DELETE RESTRICT,
  source_record_key text NOT NULL
    REFERENCES provider_sync.source_records(source_record_key) ON DELETE RESTRICT,
  rule_row_revision bigint NOT NULL CHECK (rule_row_revision >= 1),
  source_record_hash text NOT NULL
    CHECK (source_record_hash ~ '^[0-9a-f]{1,64}$'),
  candidate_input_hash text NOT NULL
    CHECK (candidate_input_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL DEFAULT 'open'
    CHECK (state IN ('open', 'promoted', 'rejected', 'withdrawn')),
  rank_score numeric(10,4) NOT NULL DEFAULT 0,
  proposal_title text,
  proposal_summary text,
  match_evidence jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(match_evidence) = 'object'),
  row_revision bigint NOT NULL DEFAULT 1 CHECK (row_revision >= 1),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_theme_feature_candidates_rule_entity_feature
    UNIQUE (rule_id, source_entity_key, feature_id)
);

CREATE INDEX idx_theme_feature_candidates_rule_open_keyset
  ON feature.theme_feature_candidates
    (rule_id, updated_at DESC, candidate_id DESC)
  WHERE state = 'open';
CREATE INDEX idx_theme_feature_candidates_feature_state
  ON feature.theme_feature_candidates (feature_id, state, candidate_id);
CREATE INDEX idx_theme_feature_candidates_source_entity
  ON feature.theme_feature_candidates (source_entity_key, candidate_id);
```

후보는 삭제·재삽입으로 lifecycle을 표현하지 않는다. `withdrawn → open` 재출현도 같은
identity 행의 versioned transition이다. candidate refresh는 `candidate_input_hash`가 동일하면
`updated_at`/`row_revision`을 바꾸지 않는다. `source_record_hash`는 caller가 신뢰하는 값이
아니라 locked current `source_records.raw_payload_hash`에서 procedure가 읽어 기록한다.

현재 candidate row의 source/entity/Feature FK는 `RESTRICT`다. Feature/source hard purge가 필요한
경우에는 먼저 state-owner 전용 purge command가 current candidate를 `withdrawn`으로 전이하고 row를
삭제하며, append-only transition/generation observation에는 FK cascade를 두지 않는다. runtime의
직접 candidate delete와 migration의 `CASCADE`는 금지한다.

`proposal_title`, `proposal_summary`, `rank_score`, `match_evidence`는 rule/source에서 유도된
후보 설명이다. 공식 collection item의 title, summary, sort order, relation, reuse policy를
갱신하지 않는다. `match_evidence`에는 raw payload 전체나 인증 민감값을 넣지 않으며, allowed
key/size/type validation을 procedure에 명시한다.

### 3.4 append-only transition audit

```sql
CREATE TABLE feature.theme_feature_candidate_transitions (
  transition_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  candidate_id uuid NOT NULL,
  feature_id text NOT NULL,
  rule_id uuid NOT NULL,
  source_entity_key text NOT NULL,
  from_state text,
  to_state text NOT NULL
    CHECK (to_state IN ('open', 'promoted', 'rejected', 'withdrawn')),
  transition_kind text NOT NULL CHECK (
    transition_kind IN (
      'source_materialize', 'source_withdraw', 'admin_promote',
      'admin_reject', 'merge_retarget', 'legacy_backfill'
    )
  ),
  candidate_row_revision bigint NOT NULL CHECK (candidate_row_revision >= 1),
  rule_row_revision bigint NOT NULL CHECK (rule_row_revision >= 1),
  provider_dataset_id bigint,
  source_record_key text,
  source_record_hash text,
  collection_id uuid,
  curation_item_id uuid,
  command_id uuid,
  actor text,
  reason_code text,
  causation_ref jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(causation_ref) = 'object'),
  invoker_role text NOT NULL,
  candidate_procedure_definer text NOT NULL,
  audit_writer_definer text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_candidate_transition_initial_shape CHECK (
    (transition_kind IN ('source_materialize', 'legacy_backfill') AND from_state IS NULL)
    OR
    (transition_kind NOT IN ('source_materialize', 'legacy_backfill')
      AND from_state IN ('open', 'promoted', 'rejected', 'withdrawn'))
  ),
  CONSTRAINT uq_candidate_transition_candidate_revision
    UNIQUE (candidate_id, candidate_row_revision)
);

CREATE INDEX idx_candidate_transitions_candidate_keyset
  ON feature.theme_feature_candidate_transitions
    (candidate_id, transition_id DESC);
CREATE INDEX idx_candidate_transitions_command
  ON feature.theme_feature_candidate_transitions (command_id)
  WHERE command_id IS NOT NULL;
```

이 audit에는 candidate/Feature/source relation FK를 두지 않는다. final hard purge 뒤에도 source
evidence와 actor를 보존하기 위해서다. runtime에는 table sequence를 포함한 모든 direct
`INSERT`/`UPDATE`/`DELETE`/`TRUNCATE` 권한이 없고, trigger function owner만 insert한다.
UPDATE/DELETE/TRUNCATE를 거부하는 guard와 catalog assertion을 함께 둔다.

## 4. state transition과 named command

### 4.1 허용 전이

| from | command | to | 필수 증거 | collection side effect |
|---|---|---|---|---|
| 없음 | provider source materialize | `open` | enabled rule, current source head, Feature link | 없음 |
| `open` | provider refresh | `open` | 같은 current source evidence, input hash 변경 | 없음 |
| `open` | admin promote | `promoted` | strong ETag, command claim, target collection/item identity | canonical item create/update 하나 |
| `open` | admin reject | `rejected` | strong ETag, authenticated actor/reason | 없음 |
| `withdrawn` | provider refresh | `open` | newer/current source evidence | 없음 |
| `open` | completed snapshot withdrawal | `withdrawn` | completed authoritative operation, rule scope absence proof | 없음 |
| `promoted`/`rejected` | source refresh | 같은 state | source evidence만 갱신 | 없음 |
| 모든 상태 | merge command | 정의된 target 상태 | master/loser collision policy와 audit | canonical item은 별도 merge policy |

`promoted → open`, `rejected → open`의 자동 재평가는 허용하지 않는다. 새 rule intent가 필요하면
rule revision을 올린 뒤 명시 admin reopen command를 future task로 설계하거나 새 rule을 만든다.
T-VN-40 initial scope는 그런 reopen UX를 만들지 않는다.

### 4.2 source materialization procedure

provider refresh의 external entrypoint는 아래 signature를 사용한다. context의 principal, dataset,
source hash는 input 문자열을 믿지 않고 procedure가 locked catalog/source row에서 derive한다.

```sql
CALL feature.materialize_theme_feature_candidate(
  p_rule_id uuid,
  p_feature_id text,
  p_source_entity_key text,
  p_source_record_key text,
  p_generation_id uuid,
  p_rank_score numeric,
  p_proposal_title text,
  p_proposal_summary text,
  p_match_evidence jsonb,
  p_context jsonb,
  OUT o_candidate_id uuid,
  OUT o_row_revision bigint,
  OUT o_inserted boolean
);
```

procedure는 running generation, rule, provider dataset/entity/current-head, source link, Feature,
candidate 순서로 `FOR UPDATE`/`FOR SHARE` lock을 얻는다. `p_source_record_key`가 current head가
아니거나 linked Feature/rule source와 맞지 않으면 `23514`로 거부한다. generation의 rule revision이
현재 rule과 다르면 412에 매핑되는 domain SQLSTATE를 내고 stale provider evidence를 audit하지
않는다.

withdrawal은 arbitrary caller array나 dataset operation id가 아니라 succeeded full-snapshot
generation completion에서만 일어난다. completion procedure가 rule scope와 source job receipt를
검증한 뒤 그 generation에서 관측되지 않은 `open` candidate만 `withdrawn`으로 전이한다.
incremental operation과 failed/running generation은 withdrawal path를 호출할 수 없다.

### 4.3 promotion/rejection procedure

promotion과 rejection은 generic `PATCH state`가 아니라 각각 typed command다.

```sql
CALL feature.promote_theme_feature_candidate(
  p_candidate_id uuid,
  p_collection_id uuid,
  p_external_item_id text,
  p_external_component_id text,
  p_place_name text,
  p_address_hint text,
  p_item_title text,
  p_item_summary text,
  p_sort_order integer,
  p_curation_relation text,
  p_reuse_policy text,
  p_item_status text,
  p_expected_candidate_revision bigint,
  p_expected_collection_revision bigint,
  p_command_id uuid,
  p_reason_code text,
  p_principal text,
  OUT o_candidate_id uuid,
  OUT o_candidate_revision bigint,
  OUT o_curation_item_id uuid,
  OUT o_curation_item_revision bigint
);

CALL feature.reject_theme_feature_candidate(
  p_candidate_id uuid,
  p_expected_candidate_revision bigint,
  p_command_id uuid,
  p_reason_code text,
  p_principal text,
  OUT o_candidate_id uuid,
  OUT o_candidate_revision bigint
);
```

이 signature를 위해 T-VN-40은 `curation_collections`와 `curation_items`에
`row_revision bigint NOT NULL DEFAULT 1 CHECK (row_revision >= 1)`을 추가한다. typed collection
writer가 실제 값 변경 때만 1 증가시키며, 모든 admin mutation은 strong ETag에서 이 revision을
사용한다. `p_item_status`는 `candidate`/`included`만 허용한다. `included`가 곧 public 노출을
뜻하지는 않으며 public predicate는 collection/item/Feature 상태를 함께 확인한다.

promotion은 open candidate, active domain-command claim, target collection, existing/new item
identity를 같은 transaction에서 lock한다. duplicate external component identity 또는 active
source-feature uniqueness가 충돌하면 409로 rollback하고 candidate event도 남기지 않는다. command
replay는 같은 result를 반환하되 revision/event를 추가로 만들지 않는다. rejection은 non-empty
reason code를 요구하고 collection item을 바꾸지 않는다.

### 4.4 import, manual item edit, merge

existing CSV import와 manual collection item command는 candidate state를 바꾸지 않는다. canonical
item을 user가 만들었다고 candidate가 `promoted`로 암묵 전환해서는 안 된다. candidate promotion은
항상 command receipt로 provenance를 남긴다.

Feature merge는 candidate/current item을 동시에 raw UPDATE하지 않는다. `merge_theme_candidates`는
master/loser Feature lock 뒤 candidate identity conflict를 분류한다.

- winner identity가 없으면 candidate를 master로 retarget하고 transition audit을 남긴다.
- 같은 `(rule, entity, master)` candidate가 있으면 deterministic winner를 고른 뒤 loser를
  `withdrawn`으로 전이하고 conflict provenance를 남긴다.
- `promoted` candidate가 가리키는 canonical item은 existing curation merge policy로 별도로
  처리한다. candidate merge가 collection item의 operator fields를 overwrite하지 않는다.

## 5. ACL과 procedure ownership

`ktm_curation_command_owner`라는 dedicated NOLOGIN/NOINHERIT role을 만든다. 이 role은 필요한
candidate/current source/catalog/collection relation에만 최소 `SELECT`/`INSERT`/`UPDATE`를 받고,
`SECURITY DEFINER` routine은 fixed `search_path = pg_catalog, feature, provider_sync, ops`와
schema-qualified dependency를 사용한다. `PUBLIC`은 모든 command의 `EXECUTE`가 없다.

`ktm_feature_runtime`은 candidate audit 및 candidate/current collection membership table에 direct
DML 권한이 없다. API/Dagster LOGIN은 필요한 named command만 execute한다. public/admin read는
별도 closed view/reader allowlist로 제공하며 raw candidate evidence/payload를 public role에 주지
않는다. runtime reconciler는 다음을 assert한다.

- legacy overlay/snapshot에 `SELECT`/DML privilege가 모두 없다.
- candidate/current membership raw DML과 candidate audit mutation이 모두 42501이다.
- allowed promotion/rejection/materialize/import commands만 execute 가능하고 `PUBLIC` execute는 없다.
- procedure owner는 direct table read/write가 가능하지만 runtime session은 owner/set-role,
  `BYPASSRLS`, `CREATEROLE`, audit trigger disable 권한이 없다.

procedure audit에는 original `session_user`, procedure owner, audit writer owner를 각각 기록한다.
application authenticated actor는 context allowlist로 검증한 `principal`이며 DB session identity와
같은 것으로 주장하지 않는다.

## 6. single-PR migration choreography

### 6.1 deploy gate

1. exact Map/PinVi source SHA, migration head, preflight manifest schema version을 release input으로
   고정한다.
2. API/Dagster writer를 stop하고 old binary가 DB에 연결하지 못하도록 deployment gate를 건다.
3. fresh clone에서 final migration head까지 replay한 뒤 final API/Dagster binary만 startup
   preflight를 통과할 수 있어야 한다.

### 6.2 ordered migration

1. rule revision, candidate/current audit, row revisions, command functions, audit guards를 만든다.
2. all legacy rows와 canonical item mapping을 read-only preflight manifest에 materialize한다.
   unmapped/ambiguous row가 하나라도 있으면 migration은 fail-closed다.
3. legacy source-rule rows를 candidate lifecycle로 one-time backfill하고 immutable transition
   events를 남긴다. row count/key set/checksum을 manifest와 대조한다.
4. final collection/item command와 candidate command를 install하고 runtime ACL/reconciler/preflight를
   final table/function inventory로 바꾼다.
5. Map API/OpenAPI, user client, frontend, Dagster, merge, PinVi consumer가 final command/read model을
   사용한다는 build artifact를 same release에 포함한다.
6. legacy trigger를 disable하는 것이 아니라 dependency를 `DROP ... RESTRICT`로 확인한 뒤 drop한다.
   `legacy_projection_id` FK/index/column, legacy cursor/snapshot, overlay table/index/constraint/ACL,
   old repository/asset/router/client/UI reference를 physical removal manifest대로 삭제한다.
7. ACL reconciliation을 relation drop 뒤 실행하고 final catalog/static/consumer checksums를
   record한다. final service only then starts.

Alembic migration은 forward-only다. data backfill error나 consumer build mismatch는 partial service
rollout으로 복구하지 않는다. transaction abort 후 schema/data를 원 migration head로 유지하고,
correction은 fresh clone/reload input에서 다시 수행한다.

### 6.3 legacy mapping rules

| legacy row | required relation evidence | target | fail-closed condition |
|---|---|---|---|
| `source_rule` + `candidate` + active | exact rule/entity/current record/Feature link | `open` candidate | current proof 또는 unique identity 불명 |
| `source_rule` + `curated` | exact one canonical item and accepted mapping | `promoted` candidate + existing item | item 0/2개 또는 incompatible external identity |
| `source_rule` + `rejected` | exact rule/entity/Feature | `rejected` candidate | actor/reason/evidence missing |
| provider-origin archived/absent | succeeded full-snapshot generation absence receipt | `withdrawn` candidate | incremental/failed generation 또는 source proof missing |
| admin/external overlay row | canonical item mapping only | candidate를 만들지 않음 | canonical item mapping absent |

mapping manifest는 each bucket count, stable identity checksum, legacy primary key ↔ candidate/item id,
unmapped cause를 보전한다. “0건이면 무시” 같은 fallback은 없다.

## 7. HTTP/OpenAPI/consumer contract

### 7.1 legacy detail snapshot의 canonical replacement

PinVi가 실제로 소비하는 legacy admin
`GET /v1/admin/features/curated/{curated_feature_id}/detail-snapshot`는 overlay의 단건 wrapper다.
legacy snapshot은 항상 item 하나만 담으므로 `curated_feature_id`를 canonical identity로 보존할
근거가 없다. T-VN-40은 `feature.curated_feature_detail_snapshots`와 trip-copy snapshot cache를
물리 삭제하고, 다음 typed admin endpoint로 바꾼다.

```
GET /v1/admin/curation-items/{curation_item_id}/detail-snapshot
```

이 endpoint는 cache table을 새로 만들지 않고 one repeatable-read query에서
`curation_items → curation_collections → typed Feature/subtype → source record`를 직접 조립한다.
측정 전 materialized cache를 재도입하지 않는다. response는 closed
`CurationItemDetailSnapshot`이며 다음 exact top-level key만 갖는다.

```json
{
  "curation_item_id": "UUID",
  "collection_id": "UUID",
  "row_revision": 7,
  "etag": "sha256:<canonical-json>",
  "updated_at": "RFC3339",
  "collection": {"theme_slug": "…", "theme_name": "…", "title": "…", "edition_key": "…"},
  "item": {"feature_id": "…", "relation": "…", "sort_order": 0, "title": null, "summary": null},
  "feature": {"feature_id": "…", "name": "…", "category": "…", "kind": "…", "lon": 0, "lat": 0,
              "address": {}, "detail": {}, "source_record_key": "…"}
}
```

`collection`/`item`/`feature`의 exact property·nullable/type은 Map OpenAPI와 PinVi typed consumer
test가 freeze한다. endpoint는 `source_present`, `item.status='included'`, linked Feature, required
source record가 없으면 404를 반환하며 candidate/archived item을 PinVi snapshot으로 만들지 않는다.
collection visibility와 Feature public predicate는 PinVi import policy가 요구하는 projection에서
명시한다. legacy `curation_status`, `curated_feature_id`, `items[]`, `day_index`, `memo`는 response에
남기지 않는다. PinVi는 same Map head의 new item id/path/schema로 re-vendor하고 old snapshot path와
types를 compile/static gate에서 0으로 만든다.

### 7.2 public

- public `/v1/curations*`, Feature `curations[]`, PinVi curation consumer는 canonical collection/item
  projection만 쓴다.
- `/v1/curated-features`, its `cursor` kind, theme/source candidate list, legacy `curation_status`
  response/query field는 제거한다. redirect와 no-op parameter는 없다.
- public response에는 candidate id/state/rank/evidence/rejection/actor/audit을 노출하지 않는다.

### 7.3 admin candidate API

| method/path | command/query | required contract |
|---|---|---|
| `GET /v1/admin/theme-feature-candidates` | admin keyset list | `rule_id`, `theme_id`, `source_id`, `state`, `feature_id` AND filter; `updated_at,candidate_id` cursor |
| `GET /v1/admin/theme-feature-candidates/{id}` | detail | current typed Feature summary, rule/source metadata, source evidence digest, state/revision |
| `GET /v1/admin/theme-feature-candidates/{id}/transitions` | audit timeline | descending `transition_id` keyset; actor/evidence only admin |
| `POST /v1/admin/theme-feature-candidates/{id}/promote` | typed promotion | `If-Match`, `Idempotency-Key`, target collection and typed item identity/body, reason code |
| `POST /v1/admin/theme-feature-candidates/{id}/reject` | typed rejection | `If-Match`, `Idempotency-Key`, non-empty reason code |
| `GET /v1/admin/curation-items/{id}/detail-snapshot` | PinVi typed import snapshot | canonical item id only; closed direct projection, no legacy overlay/cache |

`If-Match` mismatch는 412, missing candidate/collection is 404, stale source/current-head or identity
conflict is 409, malformed typed input is 422, denied actor is 403이다. successful command response에는
candidate revision, candidate transition id, canonical item id/revision(승격만)을 포함한다. item body는
legacy overlay status가 아닌 canonical item fields만 허용한다.

OpenAPI export 후 Map user/admin spec과 generated user/admin types를 exact head에서 갱신한다. PinVi
user vendor와 admin-detail subset은 동일 Map commit에서 re-extract하고 paired SHA, codegen compile,
legacy endpoint/type zero evidence를 `consumer-rollout-v1.json`에 기록한다.

## 8. performance and correctness gates

| query/operation | required index/proof |
|---|---|
| admin open-candidate list | `rule_id, updated_at DESC, candidate_id DESC WHERE state='open'` keyset `EXPLAIN JSON` |
| Feature candidate review history | candidate transition `(candidate_id, transition_id DESC)` index |
| public Feature/collection aggregate | existing canonical item/collection predicates only; no candidate or legacy overlay join |
| refresh | candidate exact unique lookup; equal input hash does not row rewrite |
| promotion | candidate/collection/item locks and one candidate transition + at most one item mutation |
| merge | ordered two-session source→link→Feature→candidate→collection→item test; no 40P01 |
| removal | `pg_depend`, view/function/trigger/index/ACL/static source zero; `to_regclass('feature.curated_features') IS NULL` |

T-VN-40 final gate has three tiers.

1. disposable legacy-head clone migration and backfill set-diff/checksum checks;
2. fresh final schema integration including runtime API/Dagster LOGIN command/ACL tests and Map/PinVi
   exact consumer contract;
3. n150 isolated fresh PostGIS→ETL destructive candidate refresh→admin promotion→public collection→
   source withdrawal→merge→recovery/cleanup E2E. Playwright runs on n150, not WSL.

## 9. final removal manifest minimum set

The implementation PR must replace this minimum list with actual catalog OIDs/signatures before drop.

- relation: `feature.curated_features`, `feature.curated_feature_detail_snapshots`,
  `feature.curated_tripmate_copy_snapshots` and every legacy-only snapshot relation;
- curation item bridge: `legacy_projection_id`, its FK and
  `uq_curation_items_legacy_projection_id`;
- sync: `feature.sync_curated_feature_collection`,
  `trg_sync_curated_feature_collection`, every reverse-sync function/trigger;
- code: `curated_repo` overlay writer/read models, client exports, curated refresh Dagster asset/schedule,
  legacy merge branches, legacy router/DTO/cursor/frontend/e2e fixture;
- contract: public `/v1/curated-features`, legacy admin curated route/detail-snapshot/OpenAPI/generated
  types/PinVi vendor; replacement is canonical `curation-items/{id}/detail-snapshot` only;
- security: runtime privilege map, preflight allowlist, procedure grants, sequences, views/functions/index
  predicates containing `curated_features`.

`curated_themes`, `curated_sources`, `curated_source_rules`, `curation_collections`,
`curation_items`, import/link-decision history are not removal candidates. Any unexpectedly dependent
relation is a fail-closed manifest expansion requiring PR review, not an ad-hoc `CASCADE` drop.

## 10. acceptance checklist

- [ ] one implementation PR/release contains 40A/B/C; no phase branch or deployment was merged.
- [ ] source-rule `curated` values and every legacy overlay row have a classified manifest result.
- [ ] candidate current source proof, immutable transition audit, raw-DML fence, promotion idempotency and
  lock order have integration regressions.
- [ ] collection/item is the only public/PinVi membership read path; public candidate response is zero.
- [ ] PinVi/admin detail snapshot uses only canonical curation item identity and has no legacy cache/path/type.
- [ ] Map OpenAPI/user/admin generated output and PinVi exact pair compile/check pass.
- [ ] legacy relation/object/API/catalog/static references are zero after final migration.
- [ ] n150 destructive fresh E2E and recovery cleanup evidence are stored only as redacted immutable receipt.
