# T-VN-40 — 큐레이션 단일 writer 상세 설계

- 상태: 구현 정본 — A/B/C 단일 PR 진행 중
- 기준: T-VN-36 merge head `c76ceb7a`
- 상위 결정: ADR-063, ADR-069, ADR-071, ADR-092(accepted)
- 실행 단위: T-VN-40A/B/C 단일 forward-only implementation PR/release
- 작성일: 2026-08-11

## 1. 설계 경계

이 문서는 T-VN-40 구현의 정본이다. 아래 relation, procedure, API의 이름과 acceptance는
같은 draft PR #974에서 구현한다. T-VN-32~38 join barrier와 ADR-092 human acceptance는
2026-08-13 충족됐다.

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
이는 자동 rule 결과인 `theme_feature_candidates.review_state='open'`과 다른 domain이다. public inclusion은
collection이 `published`/`public`, item이 `included`, item source가 present, 연결 Feature가
ADR-067 public predicate를 만족하는 경우에만 성립한다.

## 3. 후보 data model

### 3.1 catalog revision·archive·observation 분리

T-VN-40은 retained catalog 세 relation 모두에 operator semantic CAS revision과 archive 축을
추가한다. source polling heartbeat는 operator ETag를 churn시키지 않도록 별도 observation revision을
쓴다. ADR-092가 폐기한 자동 공개 의미 `default_curated`는 theme/API/generated type에서 물리 삭제한다.

```sql
ALTER TABLE feature.curated_themes
  ADD COLUMN row_revision bigint NOT NULL DEFAULT 1,
  ADD COLUMN archived_at timestamptz,
  ADD COLUMN owner_kind text,
  ADD COLUMN owner_provider_dataset_id bigint,
  ADD CONSTRAINT ck_curated_themes_revision_positive CHECK (row_revision >= 1);

ALTER TABLE feature.curated_sources
  ADD COLUMN row_revision bigint NOT NULL DEFAULT 1,
  ADD COLUMN observation_revision bigint NOT NULL DEFAULT 1,
  ADD COLUMN archived_at timestamptz,
  ADD CONSTRAINT ck_curated_sources_revision_positive CHECK (row_revision >= 1),
  ADD CONSTRAINT ck_curated_sources_observation_revision_positive
    CHECK (observation_revision >= 1);

ALTER TABLE feature.curated_source_rules
  ADD COLUMN row_revision bigint NOT NULL DEFAULT 1,
  ADD COLUMN archived_at timestamptz,
  ADD COLUMN owner_kind text,
  ADD COLUMN owner_provider_dataset_id bigint,
  ADD CONSTRAINT ck_curated_source_rules_revision_positive
    CHECK (row_revision >= 1);
```

위 SQL은 **expand block**이다. manifest와 ownership collision 분류 전에는
`default_curated`를 DROP하거나 legacy `default_action='curated'`를 거부하는 CHECK를 설치하지 않는다.
backfill 뒤 final block이 theme/rule `owner_kind`를 `operator|provider_dataset`으로 NOT NULL 고정하고,
provider-owned이면 `owner_provider_dataset_id`가 exact provider dataset FK로 non-null, operator-owned이면
NULL인 XOR CHECK를 VALIDATE한다. concierge theme/rule ownership은 slug 추측이 아니라 immutable
backfill manifest로 분류하며 unknown/collision은 중단한다. provider sync는 provider-owned row만 변경하고
owner 두 열은 UPDATE 불가다. 그 뒤 `curated → candidate` 변환, action CHECK `NOT VALID → VALIDATE`,
마지막에 theme `default_curated` DROP을 수행한다.

- catalog command는 실제 operator-owned 내용 변경 때만 `row_revision`을 1 증가시킨다. 직접
  `UPDATE`와 no-op timestamp write는 DB trigger/ACL로 거부한다. theme/source/rule GET·list DTO는
  revision을 반환하고 단건 GET은 raw strong ETag를 낸다. PATCH/archive는 `If-Match` 필수이며
  missing=428, mismatch=412다.
- source의 `last_checked_at`, `last_source_modified_at`, `next_expected_at`, `row_count`, freshness
  observation은 provider-only `refresh_curated_source_observation`이 갱신하고
  `observation_revision`만 1 증가시킨다. 동일 count 재관측도 실제 heartbeat이므로 observation
  revision은 증가하지만 operator `row_revision`/ETag는 유지한다. operator source PATCH와 concurrent
  provider observation은 서로의 필드를 덮지 않는다.
- archive는 `archived_at`의 NULL→server timestamp 전이만 허용한다. unarchive와 hard delete는
  T-VN-40 scope에 없고 archived catalog는 generation/promotion input에서 제외한다.
- legacy `default_action='curated'`는 preflight에서 정확히 계수한다. backfill은 이를
  `candidate`로 바꾸고 자동 collection item 생성은 하지 않는다.
- rule의 `theme_id`, `source_id`, selector, region/category/kind, enabled, priority가 후보
  판단 input이다. candidate row에는 이 값을 중복 저장하지 않고 `rule_id`와
  `rule_row_revision`만 저장한다.

### 3.2 rule generation receipt

후보 eligibility removal은 Dagster run id 문자열이나 incremental refresh의 “없음”을 근거로 하지 않는다.
T-VN-40은 rule evaluation의 complete input을 명시하는 generation receipt를 둔다.

```sql
CREATE TABLE ops.curation_rule_reconcile_operations (
  operation_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  rule_id uuid NOT NULL
    REFERENCES feature.curated_source_rules(rule_id) ON DELETE RESTRICT,
  operation_kind text NOT NULL CHECK (operation_kind IN ('create','patch','archive')),
  before_rule_revision bigint CHECK (before_rule_revision >= 1),
  after_rule_revision bigint NOT NULL CHECK (after_rule_revision >= 1),
  before_rule_input_hash text CHECK (before_rule_input_hash ~ '^[0-9a-f]{64}$'),
  after_rule_input_hash text NOT NULL CHECK (after_rule_input_hash ~ '^[0-9a-f]{64}$'),
  command_id bigint REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  system_operation_key text,
  actor text NOT NULL CHECK (actor = btrim(actor) AND actor <> ''),
  scope_member_count bigint NOT NULL CHECK (scope_member_count >= 0),
  scope_members_hash text NOT NULL CHECK (scope_members_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_curation_rule_reconcile_operation_origin CHECK (
    (command_id IS NOT NULL AND system_operation_key IS NULL)
    OR (command_id IS NULL AND system_operation_key IS NOT NULL
      AND system_operation_key = btrim(system_operation_key)
      AND system_operation_key <> '')
  ),
  CONSTRAINT ck_curation_rule_reconcile_operation_revision_shape CHECK (
    (operation_kind = 'create'
      AND before_rule_revision IS NULL AND before_rule_input_hash IS NULL
      AND after_rule_revision = 1)
    OR (operation_kind IN ('patch','archive')
      AND before_rule_revision IS NOT NULL AND before_rule_input_hash IS NOT NULL
      AND after_rule_revision > before_rule_revision)
  )
);
CREATE UNIQUE INDEX uq_curation_rule_reconcile_command
  ON ops.curation_rule_reconcile_operations (rule_id, command_id)
  WHERE command_id IS NOT NULL;
CREATE UNIQUE INDEX uq_curation_rule_reconcile_system_operation
  ON ops.curation_rule_reconcile_operations (rule_id, system_operation_key)
  WHERE system_operation_key IS NOT NULL;

CREATE TABLE ops.curation_rule_reconcile_scope_members (
  operation_id uuid NOT NULL
    REFERENCES ops.curation_rule_reconcile_operations(operation_id) ON DELETE RESTRICT,
  member_kind text NOT NULL CHECK (member_kind IN ('source_entity','feature')),
  member_key text NOT NULL CHECK (member_key = btrim(member_key) AND member_key <> ''),
  before_identity_hash text CHECK (before_identity_hash ~ '^[0-9a-f]{64}$'),
  after_identity_hash text CHECK (after_identity_hash ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (operation_id, member_kind, member_key),
  CONSTRAINT ck_curation_rule_reconcile_scope_identity CHECK (
    before_identity_hash IS NOT NULL OR after_identity_hash IS NOT NULL
  )
);

CREATE TABLE feature.theme_candidate_generations (
  generation_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  rule_id uuid NOT NULL
    REFERENCES feature.curated_source_rules(rule_id) ON DELETE RESTRICT,
  rule_row_revision bigint NOT NULL CHECK (rule_row_revision >= 1),
  generation_kind text NOT NULL CHECK (
    generation_kind IN ('provider_full_snapshot', 'scoped_reconcile', 'rule_reconcile', 'legacy_backfill')
  ),
  source_job_id uuid REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT,
  reconcile_operation_id uuid
    REFERENCES ops.curation_rule_reconcile_operations(operation_id) ON DELETE RESTRICT,
  command_id bigint REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  generation_key text NOT NULL UNIQUE,
  rule_input_hash text NOT NULL
    CHECK (rule_input_hash ~ '^[0-9a-f]{64}$'),
  rule_input jsonb NOT NULL CHECK (jsonb_typeof(rule_input) = 'object'),
  generation_input_set_hash text NOT NULL
    CHECK (generation_input_set_hash ~ '^[0-9a-f]{64}$'),
  observed_candidate_count bigint NOT NULL
    CHECK (observed_candidate_count >= 0),
  eligibility_removed_candidate_count bigint NOT NULL
    CHECK (eligibility_removed_candidate_count >= 0),
  completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_theme_candidate_generations_source_job CHECK (
    (generation_kind = 'provider_full_snapshot'
      AND source_job_id IS NOT NULL AND reconcile_operation_id IS NULL AND command_id IS NULL)
    OR (generation_kind IN ('scoped_reconcile','rule_reconcile')
      AND source_job_id IS NULL AND reconcile_operation_id IS NOT NULL)
    OR (generation_kind = 'legacy_backfill'
      AND source_job_id IS NULL AND reconcile_operation_id IS NULL AND command_id IS NULL)
  )
);

CREATE INDEX idx_theme_candidate_generations_rule_completed
  ON feature.theme_candidate_generations
    (rule_id, completed_at DESC, generation_id DESC);
CREATE UNIQUE INDEX uq_theme_candidate_generation_provider_job
  ON feature.theme_candidate_generations (rule_id, source_job_id)
  WHERE generation_kind = 'provider_full_snapshot';
CREATE UNIQUE INDEX uq_theme_candidate_generation_reconcile_operation
  ON feature.theme_candidate_generations (rule_id, reconcile_operation_id)
  WHERE generation_kind IN ('scoped_reconcile','rule_reconcile');

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

`ops.curation_rule_reconcile_operations`에는 command/audit owner 소유의 unconditional
`BEFORE UPDATE OR DELETE` reject trigger와 statement-level TRUNCATE reject trigger를 둔다.
command와 system operation은 exact XOR shape이고 runtime raw INSERT/UPDATE/DELETE/TRUNCATE가 없다.
command owner만 typed catalog command 안에서 INSERT하며 runtime privilege reconciler의 closed
`_OPS_TABLE_PRIVILEGES` inventory가 이 relation을 ordinary broad CRUD 대상에서 제외한다.
generation procedure는 locked operation의 rule/revision/hash/actor를 재검증하고 generation
`command_id`가 operation의 originating command와 같음을 요구한다. system reconcile이면 둘 다
NULL이다. relation owner/trigger owner/ACL/guard definition과 두 partial unique index는 catalog test로
고정한다.
parent에는 위 `scope_member_count`/`scope_members_hash`를 저장하고 child는 writer가 잠근 old/new source
entity/Feature identity와 semantic hash를 durable하게 보존한다. command procedure가 DB relation에서
scope를 만들고 current locked set과 양방향 set-diff 0을 검증한 뒤에만 generation이 읽는다. retry는
같은 operation의 exact scope hash만 허용하고 omission/injection은 409다. parent/child 모두 같은
immutable guard와 ACL을 적용한다. scope hash preimage v1은 child를
`(member_kind, member_key)` UTF-8 byte lexical order로 정렬한 뒤 각 행을
`member_kind NUL member_key NUL before_identity_hash-or-empty NUL
after_identity_hash-or-empty LF`로 NFC 직렬화한 byte stream이다. command procedure는 child INSERT 뒤
DB에서 count와 SHA-256을 다시 계산해 parent 값과 exact equality 및 current locked set 양방향
`EXCEPT` 0을 확인한 경우에만 receipt를 seal한다.

generation receipt는 expected set/count/hash를 먼저 계산한 뒤 의존 observation/transition보다
선행 INSERT한다. 이후 candidate/observation/transition/eligibility removal을 반영하며 어느 단계든 실패하면
receipt까지 transaction rollback된다. 즉시 FK를 유지하고 “나중에 receipt를 넣는다”는 순서를
허용하지 않는다.

`provider_full_snapshot` generation은 complete authoritative provider load의 `ops.import_jobs`
receipt와 matching dataset/source scope를 procedure가 검증한 경우에만 성공할 수 있다. incremental
load 자체는 global generation/absence removal 근거가 아니며, immutable touched-scope operation을
만든 경우에만 `scoped_reconcile`로 그 scope 내부를 평가한다. `rule_reconcile`은 rule revision 변경
후 existing current heads 전체를 다시 판단하는 explicit job이고, `legacy_backfill`은 migration
only다. `generation_key`는 caller namespace가 아니다. procedure가 generation kind별 DB operation
identity, rule id/revision, canonical input hash에서 서버 파생하고 supplied key가 있으면 exact
equality만 검증한다. `provider_full_snapshot`은 `(rule_id, source_job_id)` partial unique이고,
`rule_reconcile`은 immutable `ops.curation_rule_reconcile_operations.operation_id` FK와
`(rule_id, operation_id)` unique를 가진다. 동일 논리 operation에 key A/B를 제출해 receipt를
두 개 만들 수 없다.

`generation_input_set_hash`는 단순 source-head 목록이 아니다. procedure가 rule scope의 ordered
`(source_entity_key, current_source_record_key, raw_payload_hash, source_link feature_id,
feature_uuid, row_revision, lifecycle_state, publication_state, quality_state,
effective_rule_field_digest)` tuple set을 직접 SHA-256으로 계산한다. effective digest에는 해당 rule이
읽는 kind/category/region/typed detail의 T-VN-36 effective value와 winning override lineage가 포함된다.
따라서 head가 그대로여도 admin override/state transition/merge/source-link retarget은 generation
input hash를 바꾸며 exact replay로 오인되지 않는다. `rule_input`은 canonicalization version 3와
selector/region/category/kind/enabled/priority/**`default_action`**, referenced
theme/source id·archive·immutable owner/provider 축의 ordered JSON을 고정해
mutable rule row의 과거 의미를 복원하며 `rule_input_hash`는 그 canonical JSON의 검증 digest다.
operator CAS용 theme/source/rule `row_revision`과 source observation revision은 semantic input에서
제외한다. 따라서 display-only metadata PATCH나 provider observation heartbeat는 catalog ETag만
바꾸고 기존 candidate proof를 stale로 만들지 않는다. archive·owner/provider·selector처럼 rule
평가 의미가 달라지는 축은 version 3 input에 남아 반드시 reconcile generation을 만든다.
`default_action='candidate'`인 rule만 expected match를 materialize한다. `candidate → ignore`는 old scope의
eligibility를 false로 만들고 `ignore → candidate`는 new scope를 materialize하므로 두 방향 모두 semantic
rule update이며 동일 command transaction의 reconcile 대상이다. generation은 `SERIALIZABLE`
transaction에서 처리한다. procedure는 첫 SQL에서
`current_setting('transaction_isolation') = 'serializable'`을 fail-close 검증하며 아니면 `25001`로
거부한다. repository가 뒤늦게 isolation을 바꾸지 않는다. 공통 domain-command policy에
`transaction_isolation='serializable'`을 명시하고 decorator/transaction owner가 `session.begin()` 직후
`begin_domain_command()`의 advisory-lock/ledger SQL보다 먼저 `SET TRANSACTION ISOLATION LEVEL
SERIALIZABLE`을 실행한다. claim, catalog/candidate mutation, generation, terminal receipt는 같은
transaction이다. `40001`은 actor/Idempotency-Key/fingerprint가 같은 전체 command transaction을 처음부터
재실행하며, 이미 commit된 terminal replay와 구분한다. 기본 격리 호출 거부, 실제 첫 SQL 순서,
serialization retry/terminal replay를 PostgreSQL integration으로 고정한다. DB set-based evaluator가 rule
predicate와 T-VN-36 effective fields로 expected match set을 직접 계산하고 각 match는 durable
`theme_candidate_generation_observations` 한 행을 남긴다. 따라서 candidate input hash가 동일하면
candidate 자체의 `updated_at`/`row_revision`을 바꾸지 않아도 generation coverage를 증명할 수 있다.
expected set과 observation set은 같은 procedure가 만들며 exact set-diff 0을 확인한 후, 해당 rule의
모든 `review_state`에서 현재 `eligibility_present=true`이나 observation이 없는 행을 false로 바꾼다.
head가 진행 중 바뀌면 transaction은
`40001`로 retry한다. candidate list와 promotion
procedure도 current source head를 다시 확인하므로, incomplete/old generation의 open row가 실제
promotion을 통과할 수 없다.

generation은 별도 commit되는 lease/claim이 아니다. 하나의 procedure가 candidate/observation/
eligibility transition을 반영한다. 순서는 **expected set/hash 계산 → immutable receipt INSERT →
candidate/observation/transition/eligibility 반영 → 양방향 set-diff 재검증 → commit** 하나뿐이다.
실패/프로세스 종료는 receipt를 포함해 전부 rollback하므로 running/failed/stale lease가 없다. 같은
`generation_key` replay도 procedure가 current expected set과 `rule_input` 및 두 hash를 먼저 다시
계산해 기존 receipt
및 observations와 exact-match할 때만 no-op을 반환하고 하나라도 다르면 409다. generation과
observation relation에는 UPDATE/DELETE/TRUNCATE를 무조건 거부하는 append-only guard를 둔다.
동시에 같은 rule generation을 시작하면 rule row lock과 unique key로 하나만 진행하며, 다른 complete
snapshot은 직렬화된다. caller가 match row를 넘기는 입력은 없으므로 omission/injection 경로도 없다.

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
  source_record_key text NOT NULL,
  rule_row_revision bigint NOT NULL CHECK (rule_row_revision >= 1),
  rule_input_hash text NOT NULL
    CHECK (rule_input_hash ~ '^[0-9a-f]{64}$'),
  source_record_hash text NOT NULL
    CHECK (source_record_hash ~ '^[0-9a-f]{1,64}$'),
  candidate_input_hash text NOT NULL
    CHECK (candidate_input_hash ~ '^[0-9a-f]{64}$'),
  review_state text NOT NULL DEFAULT 'open'
    CHECK (review_state IN ('open', 'promoted', 'rejected')),
  eligibility_present boolean NOT NULL DEFAULT true,
  disposition text NOT NULL DEFAULT 'active'
    CHECK (disposition IN ('active', 'merged')),
  merged_into_candidate_id uuid
    REFERENCES feature.theme_feature_candidates(candidate_id) ON DELETE RESTRICT,
  retired_at timestamptz,
  rank_score numeric(10,4) NOT NULL DEFAULT 0,
  proposal_title text,
  proposal_summary text,
  match_evidence jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(match_evidence) = 'object'),
  row_revision bigint NOT NULL DEFAULT 1 CHECK (row_revision >= 1),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_theme_feature_candidates_rule_entity_feature
    UNIQUE (rule_id, source_entity_key, feature_id),
  CONSTRAINT ck_theme_feature_candidates_disposition CHECK (
    (disposition = 'active' AND merged_into_candidate_id IS NULL AND retired_at IS NULL)
    OR (disposition = 'merged' AND merged_into_candidate_id IS NOT NULL AND retired_at IS NOT NULL)
  ),
  CONSTRAINT fk_theme_feature_candidates_source_record
    FOREIGN KEY (source_entity_key, source_record_key)
    REFERENCES provider_sync.source_records(source_entity_key, source_record_key)
    ON DELETE RESTRICT
);

CREATE INDEX idx_theme_feature_candidates_rule_open_keyset
  ON feature.theme_feature_candidates
    (rule_id, updated_at DESC, candidate_id DESC)
  WHERE disposition = 'active' AND review_state = 'open' AND eligibility_present;
CREATE INDEX idx_theme_feature_candidates_open_keyset
  ON feature.theme_feature_candidates (updated_at DESC, candidate_id DESC)
  WHERE disposition = 'active' AND review_state = 'open' AND eligibility_present;
CREATE INDEX idx_theme_feature_candidates_state_keyset
  ON feature.theme_feature_candidates
    (review_state, eligibility_present, updated_at DESC, candidate_id DESC)
  WHERE disposition = 'active';
CREATE INDEX idx_theme_feature_candidates_feature_state
  ON feature.theme_feature_candidates
    (feature_id, review_state, eligibility_present, candidate_id)
  WHERE disposition = 'active';
CREATE INDEX idx_theme_feature_candidates_source_entity
  ON feature.theme_feature_candidates (source_entity_key, candidate_id);
```

후보는 삭제·재삽입으로 lifecycle을 표현하지 않는다. source 재출현도 같은 identity 행의
`eligibility_present=false → true` transition이며 `review_state`를 보존한다. candidate refresh는
`candidate_input_hash`가 동일하면
`updated_at`/`row_revision`을 바꾸지 않는다. `source_record_hash`는 caller가 신뢰하는 값이
아니라 locked current `source_records.raw_payload_hash`에서 procedure가 읽어 기록한다.

현재 candidate row의 source/entity/Feature FK는 `RESTRICT`다. T-VN-40은 candidate hard purge를
제공하지 않는다. merge collision loser는 삭제하지 않고 `disposition='merged'`, winner pointer,
server `retired_at`을 기록한 durable tombstone으로 남긴다. source/Feature hard purge는 이 history를
보존하거나 별도 post-service retention task가 명시적으로 정리하기 전까지 fail-close한다. runtime과
command owner 모두 candidate DELETE가 없고 migration `CASCADE`도 금지한다.
모든 live list/count/generation/promotion/rejection predicate는 `disposition='active'`를 필수로 하고,
merged tombstone은 별도 admin history query에서만 읽는다. DB procedure는 merged row의
promote/reject/refresh/restore/remove를 거부한다. merge guard는 winner가 self가 아니고 같은
rule/source entity이며 active disposition이고, winner가 다른 tombstone을 가리키지 않아 chain/cycle이
없음을 locked row로 검증한다.

`proposal_title`, `proposal_summary`, `rank_score`, `match_evidence`는 rule/source에서 유도된
후보 설명이다. 공식 collection item의 title, summary, sort order, relation, reuse policy를
갱신하지 않는다. `match_evidence`에는 raw payload 전체나 인증 민감값을 넣지 않으며, allowed
key/size/type validation을 procedure에 명시한다.

### 3.4 append-only transition audit

```sql
CREATE TABLE feature.theme_feature_candidate_transitions (
  transition_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  candidate_id uuid NOT NULL,
  from_feature_id text,
  to_feature_id text,
  rule_id uuid NOT NULL,
  source_entity_key text NOT NULL,
  from_review_state text CHECK (from_review_state IN ('open','promoted','rejected')),
  to_review_state text NOT NULL CHECK (to_review_state IN ('open','promoted','rejected')),
  from_eligibility_present boolean,
  to_eligibility_present boolean NOT NULL,
  from_disposition text CHECK (from_disposition IN ('active','merged')),
  to_disposition text NOT NULL CHECK (to_disposition IN ('active','merged')),
  winner_candidate_id uuid,
  transition_kind text NOT NULL CHECK (
    transition_kind IN (
      'eligibility_materialize', 'eligibility_refresh', 'eligibility_restore', 'eligibility_remove', 'admin_promote',
      'admin_reject', 'merge_retarget', 'merge_collapse', 'legacy_backfill'
    )
  ),
  candidate_row_revision bigint NOT NULL CHECK (candidate_row_revision >= 1),
  rule_row_revision bigint NOT NULL CHECK (rule_row_revision >= 1),
  rule_input_hash text NOT NULL CHECK (rule_input_hash ~ '^[0-9a-f]{64}$'),
  candidate_input_hash text NOT NULL CHECK (candidate_input_hash ~ '^[0-9a-f]{64}$'),
  generation_id uuid REFERENCES feature.theme_candidate_generations(generation_id)
    ON DELETE RESTRICT,
  provider_dataset_id bigint,
  source_record_key text,
  source_record_hash text,
  collection_id uuid,
  curation_item_id uuid,
  command_id bigint REFERENCES ops.domain_commands(command_id) ON DELETE RESTRICT,
  actor text,
  reason_code text,
  causation_ref jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(causation_ref) = 'object'),
  invoker_role text NOT NULL,
  candidate_procedure_definer text NOT NULL,
  audit_writer_definer text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_candidate_transition_initial_shape CHECK (
    (transition_kind = 'eligibility_materialize'
      AND from_review_state IS NULL AND from_eligibility_present IS NULL
      AND to_review_state = 'open' AND to_eligibility_present)
    OR
    (transition_kind = 'legacy_backfill'
      AND from_review_state IS NULL AND from_eligibility_present IS NULL)
    OR
    (transition_kind = 'eligibility_refresh'
      AND from_review_state = to_review_state
      AND from_eligibility_present AND to_eligibility_present)
    OR
    (transition_kind = 'eligibility_restore'
      AND from_review_state = to_review_state
      AND NOT from_eligibility_present AND to_eligibility_present)
    OR
    (transition_kind = 'eligibility_remove'
      AND from_review_state = to_review_state
      AND from_eligibility_present AND NOT to_eligibility_present)
    OR
    (transition_kind = 'admin_promote'
      AND from_review_state = 'open' AND to_review_state = 'promoted'
      AND from_eligibility_present AND to_eligibility_present)
    OR
    (transition_kind = 'admin_reject'
      AND from_review_state = 'open' AND to_review_state = 'rejected'
      AND from_eligibility_present AND to_eligibility_present)
    OR
    (transition_kind = 'merge_retarget'
      AND from_review_state IS NOT NULL
      AND from_eligibility_present IS NOT NULL
      AND from_disposition = 'active' AND to_disposition = 'active'
      AND from_feature_id IS DISTINCT FROM to_feature_id)
    OR
    (transition_kind = 'merge_collapse'
      AND from_review_state IS NOT NULL
      AND from_eligibility_present IS NOT NULL
      AND from_disposition = 'active' AND to_disposition = 'merged'
      AND winner_candidate_id IS NOT NULL)
  ),
  CONSTRAINT ck_candidate_transition_kind_shape CHECK (
    (transition_kind IN ('eligibility_materialize','eligibility_refresh','eligibility_restore','eligibility_remove')
      AND rule_row_revision >= 1
      AND generation_id IS NOT NULL
      AND provider_dataset_id IS NOT NULL
      AND source_record_key IS NOT NULL
      AND source_record_hash IS NOT NULL
      AND command_id IS NULL
      AND actor IS NOT NULL AND actor = btrim(actor) AND actor <> '')
    OR
    (transition_kind = 'admin_promote'
      AND generation_id IS NULL
      AND command_id IS NOT NULL AND actor IS NOT NULL
      AND actor = btrim(actor) AND actor <> ''
      AND reason_code IS NOT NULL AND reason_code = btrim(reason_code) AND reason_code <> ''
      AND collection_id IS NOT NULL AND curation_item_id IS NOT NULL)
    OR
    (transition_kind = 'admin_reject'
      AND generation_id IS NULL
      AND command_id IS NOT NULL AND actor IS NOT NULL
      AND actor = btrim(actor) AND actor <> ''
      AND reason_code IS NOT NULL AND reason_code = btrim(reason_code) AND reason_code <> ''
      AND collection_id IS NULL AND curation_item_id IS NULL)
    OR
    (transition_kind IN ('merge_retarget','merge_collapse')
      AND generation_id IS NULL AND command_id IS NOT NULL
      AND actor IS NOT NULL AND actor = btrim(actor) AND actor <> ''
      AND reason_code IS NOT NULL AND reason_code = btrim(reason_code) AND reason_code <> '')
    OR
    (transition_kind = 'legacy_backfill'
      AND generation_id IS NOT NULL AND command_id IS NULL
      AND actor = 'migration:tvn40')
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

`generation_id`는 eligibility/legacy event에서 generation receipt를 가리키는 FK이며 candidate
tombstone과 독립 보존된다. eligibility event의 actor는 caller 문자열이
아니라 locked provider dataset과 operation에서 만든 `provider:<provider_dataset_id>` principal이다.
각 transition은 당시 `rule_input_hash`와 `candidate_input_hash`를 같이 보존해 다음 refresh가 current
candidate row를 덮어써도 과거 판정 근거를 복구한다. exact from/to/kind matrix와 위 shape는 trigger
guard에서 함께 검사하며 SQL `CHECK NULL` 통과에 의존하지 않는다.

이 audit에는 candidate/Feature/source relation FK를 두지 않는다. future retention 뒤에도 source
evidence와 actor를 보존하기 위해서다. runtime에는 table sequence를 포함한 모든 direct
`INSERT`/`UPDATE`/`DELETE`/`TRUNCATE` 권한이 없고, trigger function owner만 insert한다.
UPDATE/DELETE/TRUNCATE를 거부하는 guard와 catalog assertion을 함께 둔다.

`command_id`는 UUID idempotency key가 아니라 `ops.domain_commands.command_id bigint`다. HTTP
adapter는 같은 transaction의 `current_domain_command()` handle을 procedure에 전달하며,
procedure는 operation/actor가 요청한 typed command와 일치하는지 검증한다. 이 FK와 terminal
`domain_command_results`가 exact replay를 candidate/item revision 및 audit transition과 결박한다.
`eligibility_refresh`는 두 축을 그대로 유지하면서 evidence와 revision을 갱신하는 감사
event다. `eligibility_restore`는 review state를 보존한 정확한 `eligibility_present false → true`,
`eligibility_remove`는 정확한 `true → false`다. `eligibility_materialize`는 최초
`(NULL,NULL) → (open,true)`에만 사용한다. DB transition guard는 이 exact matrix를 검사하며,
`promoted`/`rejected` refresh·remove·restore도 review state를 바꾸지 않는다. source-derived
generation은 actor를 locked dataset에서 `provider:<provider_dataset_id>`로 파생하고 reason을
`source_absent|link_missing|feature_not_eligible` 중 하나로 기록한다. rule reconcile은 authenticated
domain command 또는 DB operation actor를 쓰고
`rule_no_match|rule_disabled|catalog_archived|feature_not_eligible|link_retarget` 중 하나를 기록한다.
generation kind와 prior/current rule/head/link/effective digest는 typed causation에 남기며 provider와
reconcile actor를 서로 위조할 수 없다.

## 4. state transition과 named command

### 4.1 허용 전이

| from `(review,present)` | command | to `(review,present)` | 필수 증거 | collection side effect |
|---|---|---|---|---|
| 없음 | provider source materialize | `(open,true)` | enabled rule, current source head, Feature link | 없음 |
| `(R,true)` | provider refresh | `(R,true)` | 같은 current source evidence, input hash 변경 | 없음 |
| `(open,true)` | admin promote | `(promoted,true)` | strong ETag, command claim, target collection/item identity | canonical item create/update 하나 |
| `(open,true)` | admin reject | `(rejected,true)` | strong ETag, authenticated actor/reason | 없음 |
| `(R,false)` | provider reopen | `(R,true)` | newer/current source evidence | 없음 |
| `(R,true)` | completed snapshot eligibility removal | `(R,false)` | completed authoritative operation, rule/source/link/effective mismatch reason | 없음 |
| 모든 상태 | merge command | 정의된 target 상태 | master/loser collision policy와 audit | canonical item은 별도 merge policy |

`R`은 `open|promoted|rejected`다. provider는 review state를 바꾸지 않는다. `promoted → open`,
`rejected → open`의 자동 재평가는 허용하지 않는다. 새 rule intent가 필요하면
rule revision을 올린 뒤 명시 admin reopen command를 future task로 설계하거나 새 rule을 만든다.
T-VN-40 initial scope는 그런 reopen UX를 만들지 않는다.

### 4.2 source materialization procedure

provider refresh의 external entrypoint는 아래 signature를 사용한다. context의 principal, dataset,
source hash는 input 문자열을 믿지 않고 procedure가 locked catalog/source row에서 derive한다.

```sql
CALL feature.materialize_theme_candidate_generation(
  p_rule_id uuid,
  p_generation_kind text,
  p_source_job_id uuid,
  p_reconcile_operation_id uuid,
  p_command_id bigint,
  p_generation_key text,
  p_context jsonb,
  OUT o_generation_id uuid,
  OUT o_observed_candidate_count bigint,
  OUT o_eligibility_removed_candidate_count bigint,
  OUT o_generation_input_set_hash text,
  OUT o_replayed boolean
);
```

단일 procedure는 rule revision/kind/key와 `provider_full_snapshot`의 exact import
job/dataset/scope를 검증한다. expected matches와 기존 eligible candidates를 합친 touched Feature id
전체를 먼저 materialize·dedupe·sort해 advisory prelock하고, curated theme/source/rule → provider
dataset/entity/current-head → source link → Feature → candidate 순서로 잠근다. caller가 candidate row,
score, title, evidence를 제출하지 않는다. procedure 내부의
set-based evaluator가 현재 rule predicate와 T-VN-36 effective projection으로 expected set을 만들고,
각 expected tuple의 candidate input/hash/proposal/evidence를 서버에서 파생한다. 따라서 matching head
누락이나 non-match injection은 입력 표면 자체에 없다.

같은 snapshot에서 expected identity/hash set과 counts를 계산해 immutable generation receipt를 먼저
INSERT하고 candidate upsert/transition, observation set, eligibility 전이를 그 순서로 수행한다. 중간
commit은 없고 실패는
전체 rollback한다. `provider_full_snapshot`/explicit `rule_reconcile`만 **global absence removal**을
허용한다. `scoped_reconcile`은 durable operation member scope 안에서만 add/refresh/restore/remove를
허용하며 scope 밖 candidate는 반드시 보존한다. 같은 key replay는 먼저 현재 canonical set과
두 hash를 재계산해 기존 immutable receipt/observation과 모두 같을 때만 no-op이다. stale same-key는
409, transaction snapshot 중 source/Feature/rule이 바뀌면 `40001`로 retry한다.

runtime entrypoint가 허용하는 kind는 `provider_full_snapshot|scoped_reconcile|rule_reconcile`뿐이다.
`legacy_backfill`은 schema owner가 migration 안에서만 부르는 별도
`backfill_theme_feature_candidates()` procedure로 분리하고 같은 revision 끝에서 DROP한다.
API/Dagster LOGIN이 runtime procedure에 `legacy_backfill`을 제출하면 23514이며 migration actor를
위조할 수 없다.

`scoped_reconcile`은 DB-owned writer receipt가 정확히 열거한 touched source entity/Feature union만
재평가한다. 그 scope에서는 add/refresh/restore/remove가 가능하지만 scope 밖 absence removal은
금지한다. affecting writer matrix는 다음과 같다.

| writer | receipt/scope | generation |
|---|---|---|
| provider full snapshot | exact done/SUCCESS import job dataset+operation membership | provider_full_snapshot; authoritative global absence 허용 |
| provider incremental/current-head advance | same-tx immutable entity operation + touched entity keys | scoped_reconcile; global absence 금지 |
| admin Feature state/field override | bigint domain command + touched Feature id | scoped_reconcile |
| source-link retarget/Feature merge | typed merge command + old/new Feature/entity set | scoped_reconcile after common prelock |
| rule create/semantic patch/archive, theme/source archive | reconcile operation + old/new rule scopes | rule_reconcile |

category/region/kind/typed detail/effective override/3축/head hash/link identity가 바뀌면 같은 transaction의
receipt와 generation으로 candidate add/refresh/remove를 끝낸다. unrelated field exact no-op은 operation,
generation, candidate revision을 만들지 않는다. 정상 writer가 commit됐는데 candidate는 stale인 중간
상태를 허용하지 않는다.

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
  p_expected_item_revision bigint,
  p_command_id bigint,
  p_reason_code text,
  p_principal text,
  OUT o_candidate_id uuid,
  OUT o_candidate_revision bigint,
  OUT o_curation_item_id uuid,
  OUT o_curation_item_revision bigint,
  OUT o_transition_id bigint
);

CALL feature.reject_theme_feature_candidate(
  p_candidate_id uuid,
  p_expected_candidate_revision bigint,
  p_command_id bigint,
  p_reason_code text,
  p_principal text,
  OUT o_candidate_id uuid,
  OUT o_candidate_revision bigint,
  OUT o_transition_id bigint
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

promotion은 canonical item INSERT/UPDATE만으로 끝나지 않는다. 같은 transaction에서
`curation_link_decisions`에 `decision_kind='accepted'`, `match_basis='admin_review'`,
`resolver_version='tvn40-candidate-promotion-v1'`인 append-only 결정을 만들고, evidence에
candidate id/revision, rule revision, source entity/current record hash, bigint command id를 넣는다.
그 뒤 `(decision_id, curation_item_id, feature_id)` exact FK를 만족하는
`curation_items.accepted_link_decision_id`를 해당 결정으로 전진시킨다. 기존 accepted pointer가
있으면 새 결정은 `supersedes_decision_id`로 이를 결박한다. decision append와 item pointer,
candidate `open → promoted` 및 candidate transition 중 하나라도 실패하면 transaction 전체를
rollback한다. 자동 trigger나 legacy overlay가 이 결정을 대신 만들지 않는다.

`p_expected_item_revision`은 existing item update에서 필수이며 create-only 요청에서는 `NULL`이어야
한다. identity에 해당하는 item이 있는데 값이 `NULL`이거나 revision이 다르면 412, create-only
요청에 race로 item이 생기면 409로 rollback한다. collection lock 자체는 lost update를 막는
revision proof가 아니므로 `p_expected_collection_revision`도 실제 locked row와 비교한다. candidate,
collection, item의 세 revision 검증이 모두 끝나기 전에는 어느 row나 audit도 변경하지 않는다.

### 4.4 import, manual item edit, merge

existing CSV import와 manual collection item command는 candidate 두 축을 바꾸지 않는다. canonical
item을 user가 만들었다고 candidate가 `promoted`로 암묵 전환해서는 안 된다. candidate promotion은
항상 command receipt로 provenance를 남긴다.

Feature merge는 candidate/current item을 동시에 raw UPDATE하지 않는다. `merge_theme_candidates`는
master/loser Feature lock 뒤 candidate identity conflict를 분류한다.

- winner identity가 없으면 candidate를 master로 retarget하고 transition audit을 남긴다.
- 같은 `(rule, entity, master)` candidate가 있으면 아래 exact active-candidate collision matrix를
  적용한다. 각 기호는 `review_state`이며 eligibility는 별도 locked evaluator가 산출한다.

| master \ loser | open | rejected | promoted |
|---|---|---|---|
| open | master open | 409 manual resolution | loser promoted를 survivor semantics로 master row에 이관 |
| rejected | 409 manual resolution | master rejected | loser promoted를 survivor semantics로 master row에 이관 |
| promoted | master promoted | master promoted | 동일 canonical item/decision lineage면 master promoted, 다르면 409 |

  survivor `candidate_id`는 항상 기존 master Feature candidate id다. loser는 hard-delete하지 않고
  `merge_collapse` transition 뒤 survivor pointer가 있는 merged tombstone이 된다. open/rejected
  ambiguity와 서로 다른 promoted item은 추측하지 않고 transaction 전체 409다. 모든 3×3 review
  pair × 2×2 eligibility 조합을 parameterized DB test로 고정한다.
- `promoted` candidate가 가리키는 canonical item은 existing curation merge policy로 별도로
  처리한다. 동일 collection/external item/component, active/archived/source-present,
  trusted/untrusted decision, current import pointer, operator fields의 existing merge regression corpus를
  typed procedure에도 그대로 적용한다. provider winner와 operator winner를 분리하고 stable
  `curation_item_id`, import/forward-recovery pointers, superseding accepted/revoked decisions를 모두
  보존하며 item PK rekey는 하지 않는다. candidate merge가 collection item의 operator fields를
  overwrite하지 않는다.

### 4.5 canonical membership·catalog command 전환

runtime raw DML 회수는 후보 table에만 적용할 수 없다. 기존 collection/item/import/quarantine와
retained theme/source/rule catalog writer도 다음 typed `SECURITY DEFINER` command로 같은 PR에서
전환한다.

- catalog: create/update/archive theme·source·rule. 모든 update는 expected row revision과 bigint
  domain command claim을 요구하고 no-op은 revision/audit을 만들지 않는다. rule create와
  selector/region/category/kind/source/theme/enabled/priority/`default_action` 등 candidate
  predicate/hash에 영향 주는
  모든 semantic update, rule/source/theme archive는 영향받는 old+new scope 모든 rule의 empty-set 포함
  `rule_reconcile`을 **같은
  transaction**에서 실행해 candidate eligibility와 originating command id를 원자 결박한다.
  mutation보다 먼저 old+proposed rule set에서 affected existing/expected candidate Feature union을
  nonlocking materialize하고 전부 sorted advisory prelock한다. 그 후 catalog rows를 lock/CAS하고
  old+proposed union을 다시 계산해 prelocked set과 양방향 `EXCEPT` 0인지 검증한다. 다르면 catalog
  mutation/generation 전에 전체 transaction을 retry하고 검증된 set 밖 advisory lock을 추가하지 않는다.
  이후 update, operation receipt, generation 순으로 실행한다. theme/source archive의 다중 rule union도 한
  번에 선잠금하며 catalog row를 잡은 뒤 advisory lock을 요청하지 않는다.
  display-only description/metadata change는 generation 없이 catalog revision만 증가하고, exact no-op은
  어떤 revision/operation도 만들지 않는다. field→predicate/hash/no-op matrix를 migration contract와
  parameterized integration test로 고정한다.
- membership: create/update/archive collection, create/update/archive item, accepted/revoked manual
  link decision. collection/item 각각 strong ETag revision을 검증한다.
- import: import batch/row/decision을 append하고 authoritative item set을 반영하는 하나의 command.
  preview는 immutable `import_plan_id`, normalized rows, payload hash, touched catalog/collection/item
  id+revision vector, active-set checksum, expiry를 저장한다. commit은 caller file을 다시 parse하거나
  match resolution을 반복하지 않고 stored plan만 읽어 전부 lock한 뒤 exact vector를 재검증하며
  mismatch는 412/409
  전체 rollback한다. import는 existing theme/source operator fields나 source observation을 update하지
  않는다. absent catalog는 explicit create-only, existing exact-equal은 reuse, 다른 값은 409 후 별도
  catalog PATCH다. batch hash replay는 exact result만 반환하며 candidate 두 축은 바꾸지 않는다.
- quarantine/recovery: quarantine collection 이동·복구를 별도 typed command로 수행하고 source
  presence 및 accepted pointer revision을 함께 검증한다.
- merge: candidate retarget/conflict와 collection item retarget/link decision을 하나의 typed merge
  command 내부에서 수행한다. normal `merge_repo.py`는 raw curation DML을 갖지 않는다.

각 procedure signature에는 `p_command_id bigint`, authenticated principal, touched relation의 expected
revision을 넣는다. API router는 활성 `current_domain_command()` handle만 전달하고 Dagster/system
job은 별도 DB-owned operation receipt를 사용한다. 기존 repository SQL과 endpoint별 exact
signature는 migration/API contract test에 freeze하며, raw collection/item/catalog/import/link-decision
DML은 runtime 두 LOGIN 모두 42501이어야 한다.

collection create의 optional theme slug도 absent=create-only, existing exact semantic equality=reuse,
existing different=409 규칙을 쓴다. 무조건 upsert로 concurrent operator theme를 덮지 않는다.
collection detail representation은 ordered `(collection row_revision, item_id, item row_revision)` set
hash를 strong HTTP ETag로 사용한다. child create/patch/archive/promotion/import가 바뀌면 hash가 바뀌며
collection row 자체 CAS는 별도 raw row ETag를 body의 `collection_etag`로 제공한다. candidate detail도
`representation_etag`(candidate+rule+Feature semantic revisions)와 command CAS
`candidate_etag`(candidate revision)를 분리하며 promotion/reject `If-Match`는 candidate_etag를 쓴다.
같은 strong ETag가 다른 body를 가리키지 않게 304/cache/concurrent child·Feature·rule tests를 둔다.

HTTP domain-command registry는 다음 공통 규칙을 frozen policy table로 가진다. create operation은
success 201, 나머지는 200이며 모두 `replay_headers=('ETag',)`다. conditional operation은
`fingerprint_headers=('If-Match',)`이고 create-only는 empty다. 대상은 theme/source/rule
create·patch·archive, collection/item create·patch·archive, candidate promote/reject, import commit,
quarantine move-items와 `confirm_curation_quarantine_standalone`, typed merge다. 원 요청 replay는 body와
ETag를 exact 재생하고 같은 idempotency key에서 changed If-Match는 409, missing=428, stale=412다.
revision/transition id는 JSON decimal string이며 command procedure 내부만 bigint를 쓴다.

기존 `POST /v1/admin/curations/import?dry_run=...`는 삭제하고 다음 2단계 HTTP 계약으로 고정한다.

- `POST /v1/admin/curations/imports/preview`: `Idempotency-Key`와 파일 payload를 받아 201,
  immutable `import_plan_id`, plan strong ETag, expiry, normalized change summary를 반환한다. 같은 actor/key와
  같은 content hash는 exact replay, 다른 payload는 409다. content hash가 같아도 다른 actor/key의 plan을
  암묵 공유하지 않는다.
- `POST /v1/admin/curations/import-plans/{import_plan_id}/commit`: `Idempotency-Key`와 exact plan
  `If-Match`를 필수로 받아 200을 반환한다. missing=428, expired/stale plan 또는 touched revision mismatch=412,
  fingerprint mismatch/already terminal different command=409다. terminal result/ETag를 replay하고 같은 plan은
  한 terminal commit만 가진다.

OpenAPI diff, domain-command registry, generated admin types 및 UI는 preview 응답의 stored plan만 commit에
전달한다. 두 번째 file upload나 caller-side resolution은 없다. preview receipt/normalized rows/vector는
UPDATE/DELETE/TRUNCATE 불가이고 commit mutation·import audit·terminal receipt는 한 transaction이다.

정확한 DB command inventory는 다음과 같이 migration contract test에 regprocedure signature와
operation을 freeze한다: catalog theme/source/rule create·patch·archive, collection create·patch·archive,
item create·patch·archive, import preview·commit, quarantine move-items·standalone-confirm·recover,
accepted/revoked link decision, candidate promote·reject, curation-aware Feature merge. 각 command는
`p_command_id bigint`, principal, expected revision/vector를 typed parameter로 받고 operation mismatch는
23514, stale revision은 `23514` + frozen `ck_tvn40_expected_revision` constraint identity→HTTP 412,
identity conflict는 23505→409다. `40001`은 오직 PostgreSQL serialization failure이며 bounded
whole-command retry 전용이다. normal runtime raw DML은 42501이다.

CSV import 및 collection create는 기존 catalog row를 upsert하지 않는다. import preview receipt가
exact revision vector와 set checksum을 고정하고 commit이 이를 재검증하며, absent catalog create-only와
exact-equal reuse 외 conflict는 409다. `ktmctl dedup-merge`는 DB raw client path를 제거하고 동일 HTTP
domain-command/typed merge 경계로 호출하거나 command 자체를 제거한다. legacy raw merge를 남기지 않는다.

Dagster/provider executor의 exact catalog allowlist는 generic admin catalog command가 아니라
`refresh_curated_source_observation(p_provider_dataset_id bigint, p_import_job_id uuid)`와
`sync_concierge_theme_catalog(p_provider_dataset_id bigint, p_import_job_id uuid)` 두 command다. 전자는 source
observation fields/revision만, 후자는 concierge-owned theme/rule semantic subset과 revision만 쓴다.
둘은 provider executor의 DB-owned receipt를 검증하고 필요한 rule generation을 같은 caller
transaction에서 이어 실행한다. provider full-snapshot candidate generation은 독립 daily curated candidate
asset이 호출하지 않는다. `run_tracked_feature_asset`가 typed load result의
`authoritative_snapshot_complete`와 canonical input-set hash를 `finish_dagster_feature_membership`에 전달하고,
그 transaction이 exact child `ops.import_jobs`/`ops.import_job_datasets` member를 `done/SUCCESS`로 닫으면서
authoritative flag/hash를 durable하게 기록한다. 그 뒤 같은 transaction에서 해당
`(provider_dataset_id,sync_scope,operation_key)`에 결박된 enabled rule을 서버 조회해
`provider_full_snapshot` generation으로 fan-out한다. multi-member asset은 각 child result별 typed flag/hash를
전달한다. job id가 없는 manual daily run, untracked asset, caller가 latest-success를 조회해 고른 job은
거부하며 old `curated_features_refresh_daily_schedule`/candidate sweep/snapshot asset과 client export는
제거한다.
failed/cancelled/multi-member mismatch는 global eligibility removal 근거가 될 수 없다. incremental은
DB-owned exact touched-scope operation이 있을 때 그 scope 안에서만 eligibility를 바꾼다.
`rule_reconcile`은 rule update가 만든 immutable operation receipt만 사용한다. 동일 Dagster retry는
같은 server-derived generation key, 새 authoritative load는 새 key다.

두 provider command는 caller가 `source_observation`이나 `canonical_theme_rule_set`을 write source로
제출하지 않는다. provider dataset + immutable job/operation identity와 bounded policy만 받고 locked
Feature/source/head에서 server set-based로 observation/group/theme/rule set과 hash를 파생한다.
concierge-owned theme/rule에는 immutable `owner_kind='provider_dataset'`와
`owner_provider_dataset_id`를 두고 backfill manifest가 manual/provider collision을 분류한다. operator-owned
slug와 충돌하면 409이며 prefix/metadata 추측으로 overwrite하지 않는다.

## 5. ACL과 procedure ownership

`ktm_curation_command_owner`라는 dedicated NOLOGIN/NOINHERIT role과 별도
`ktm_curation_audit_writer`를 만든다. command owner는 필요한
candidate/current source/catalog/collection relation에만 최소 `SELECT`/`INSERT`/`UPDATE`를 받고,
`SECURITY DEFINER` routine은 fixed `search_path = pg_catalog, feature, provider_sync, ops`와
schema-qualified dependency를 사용한다. `PUBLIC`은 모든 command의 `EXECUTE`가 없다.

audit writer만 candidate transition identity sequence와 audit table INSERT를 가지며 command owner는
audit table/sequence를 직접 쓸 수 없다. trigger function은 audit writer가 소유한다.
`ktm_feature_runtime`은 candidate audit 및 candidate/current collection membership table에 direct
DML 권한이 없다. `ktm_curation_admin_executor`와 `ktm_curation_provider_executor`를 별도 NOLOGIN
execute role로 두고 API LOGIN에는 admin/catalog/membership/import/reject/promote/merge 중 허용한
명령만, Dagster LOGIN에는 단일 generation + source observation sync + concierge theme/rule sync만
부여한다. 두 executor는 서로의
procedure EXECUTE를 갖지 않는다. public/admin read는
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

네 role은 Alembic에서 임의 생성·자가 GRANT하지 않는다. `docker/postgres-role-bootstrap.sh`와
integration bootstrap이 schema owner에 command/audit owner membership, API/Dagster LOGIN에 각
executor membership을 선프로비저닝한다. migration은 membership/NOLOGIN/NOINHERIT/admin-option
shape를 assert하고 불일치 시 42501로 중단한다. runtime privilege reconciler와 API/Dagster startup
preflight는 procedure별 EXECUTE allowlist, 교차 executor deny, candidate/audit sequence 보호를
실제 login으로 검증한다.

## 6. single-PR migration choreography

### 6.1 deploy gate

1. exact Map/PinVi source SHA, migration head, preflight manifest schema version을 release input으로
   고정한다.
2. Map API/Dagster writer와 PinVi import API/worker/queued job을 stop/drain하고 old binary가 DB나 old
   snapshot route에 연결하지 못하도록 deployment gate를 건다. zero in-flight receipt, stopped PinVi
   exact SHA, migration-compatible PinVi schema/binary staged 상태를 기록한다.
3. fresh clone에서 final migration head까지 replay한 뒤 final Map API/Dagster binary만 startup
   preflight를 통과할 수 있어야 한다.
4. exact scoped ServiceToken으로 service snapshot/OpenAPI/ETag probe를 통과시킨 뒤 paired PinVi final
   binary를 시작하고 import fence를 해제한다. old/new cross-pair는 fail-closed이며 partial import나 요청
   유실을 허용하지 않는다. 실패 시 old route를 되살리는 rollback 대신 stopped 상태에서 forward fix 후
   동일 receipt로 재검증한다. Docker Manager writer registry에도 PinVi importer stop/drain/start를 넣는다.
5. PR #978 squash 뒤 active graph는 `0200_schema_baseline→0201…0218`만 존재한다. n150의
   기존 `0104_tvn36_final_fence` DB를 새 root에 억지로 연결하거나 stamp하지 않는다. 서비스 전·재적재
   가능 정책대로 writer fence와 최종 backup receipt를 확인한 뒤 application DB를 폐기·재생성하고,
   role bootstrap→fresh `0200→0218`→runtime ACL reconciliation→provider 재적재 순서로만 전환한다.
   기존 0104 DB를 그대로 둔 상태에서는 새 image가 unknown revision으로 fail-close해야 한다.

### 6.2 ordered migration

1. all legacy rows, `default_action='curated'`, theme `default_curated`, canonical item mapping을
   read-only preflight manifest에 먼저 materialize하고 count/key/checksum을 동결한다.
2. theme/source/rule revision·archive columns, candidate/current audit, command functions, audit guards를
   만든다. rule action CHECK는 이 시점에 `NOT VALID`로 추가하며 legacy `curated` 행과
   `default_curated` column을 아직 제거하지 않는다.
   unmapped/ambiguous row가 하나라도 있으면 migration은 fail-closed다.
3. legacy source-rule rows를 candidate lifecycle로 one-time backfill하고 immutable transition
   events를 남긴다. `default_action='curated'`를 mapped `candidate`로 변경한 뒤 new action CHECK를
   VALIDATE한다. row count/key set/checksum을 manifest와 대조한다.
4. final collection/item command와 candidate command를 install하고 runtime ACL/reconciler/preflight를
   final table/function inventory로 바꾼다.
5. Map API/OpenAPI, user client, frontend, Dagster, merge, PinVi consumer가 final command/read model을
   사용한다는 build artifact를 same release에 포함한다.
6. consumer extraction과 manifest equality 후에만 theme `default_curated`와 API/generated field를
   제거한다. legacy trigger를 disable하는 것이 아니라 dependency를 `DROP ... RESTRICT`로 확인한 뒤 drop한다.
   `legacy_projection_id` FK/index/column, legacy cursor/snapshot, overlay table/index/constraint/ACL,
   old repository/asset/router/client/UI reference를 physical removal manifest대로 삭제한다.
   legacy detach만 위해 허용했던 `curation_item_id` PK rekey도 함께 폐기한다. 0074의 네
   `ON UPDATE CASCADE` FK를 `ON UPDATE NO ACTION`으로 되돌리고
   `reject_curation_history_mutation()`을 무조건 거부 guard로 교체한다.
7. ACL reconciliation을 relation drop 뒤 실행하고 final catalog/static/consumer checksums를
   record한다. final service only then starts.

T-VN-40의 static zero gate는 active executable/importable `src/`, API/Dagster packages, active
routers/DTO/client/frontend/generated OpenAPI, Docker/scripts, PinVi vendor/consumer, current docs와
`contracts/vnext/{target-schema,recovery-preflight,consumer-rollout,openapi-diff}`를 exact include한다.
machine-readable artifact의 **active contract field**에는 legacy path/type/column이 없어야 하지만,
`openapi-diff.removed`, recovery pre-backfill 비교축, removal manifest처럼 제거 대상을 증명하는 typed
tombstone은 raw 문자열 zero의 예외가 아니라 필수 증거다. gate는 파일 전체 `rg=0`이 아니라 JSON
pointer/SQL phase별 closed allowlist로 이 증거 위치만 허용하고, active/target 위치에 같은 문자열이
등장하면 실패한다.
fresh replay에 필수인 hash-pinned historical Alembic 0025~T40 이전 revision,
`src/kortravelmap/cli/_h35_schema.py`, frozen H35 rehearsal, `docs/archive/`만 explicit exclusion이다.
각 exclusion은 import graph/build artifact에 들어가지 않음을 검사하고 예상 밖 파일 하나가 생기면
gate가 실패한다. DB final catalog의 relation/dependency/function/trigger/index/ACL zero에는 exclusion이
없다. repository-wide historical static zero는 사용자 지시의 post-T40 Alembic-000 squash에서 승격한다.

Alembic migration은 forward-only다. `0001~0104`는 `alembic/legacy_versions/` 읽기 전용 감사 자료이고
application graph·배포·통합 테스트가 실행해서는 안 된다. data backfill error나 consumer build mismatch는 partial service
rollout으로 복구하지 않는다. transaction abort 후 schema/data를 원 migration head로 유지하고,
correction은 fresh clone/reload input에서 다시 수행한다.

### 6.3 legacy mapping rules

| legacy row | required relation evidence | target | fail-closed condition |
|---|---|---|---|
| `source_rule` + `candidate` + current proof | exact rule/entity/current record/Feature link | `open` candidate; legacy-only projected item archive | current proof 또는 unique identity 불명 |
| `source_rule` + `curated` | exact one canonical item and trusted accepted mapping | `promoted` candidate + existing item 유지 | item 0/2개 또는 incompatible external identity |
| `source_rule` + `rejected` + current proof | exact rule/entity/current record/Feature link | `rejected` candidate; legacy-only projected item archive | actor/reason/evidence missing |
| provider-origin archived | current source head/link로 source presence, 원 selection으로 review state 분리 | candidate 두 축 + `legacy_backfill` audit | archived 원인이 source absence인지 Feature visibility인지 구분 불명 |
| admin/external overlay row | canonical item mapping only | candidate를 만들지 않음 | canonical item mapping absent |

mapping manifest는 each bucket count, stable identity checksum, legacy primary key ↔ candidate/item id,
unmapped cause를 보전한다. “0건이면 무시” 같은 fallback은 없다.

cross-DB PinVi backfill용 exact 1:1 결과는 migration이 immutable
`ops.curation_cutover_identity_mappings(legacy_curated_feature_id uuid primary key, collection_id uuid,
curation_item_id uuid unique, mapping_kind text, source_row_hash text, created_at timestamptz)`에 남긴다.
UPDATE/DELETE/TRUNCATE와 runtime raw write는 금지한다. Map은 maintenance 중에만 exact scoped
`GET /v1/service/curation-cutover/identity-mappings`를 keyset+closed checksum envelope로 제공하고,
Docker Manager는 count/root SHA-256/Map head/PinVi target SHA를 paired receipt에 기록한다. PinVi migration은
이 service artifact만 소비해 old plan/POI identity를 new UUID로 backfill하며 orphan/ambiguous/duplicate가
하나라도 있으면 중단한다. PinVi DB 직접 Map 접근이나 old route 재호출은 허용하지 않는다. PinVi의
mapping checksum과 Map immutable relation checksum이 같아진 뒤에만 cutover fence를 해제한다.

0045 sync가 만든 canonical companion을 official membership으로 오인하지 않는다. collection metadata가
`migrated_from=feature.curated_features`이고 item이 `legacy_projection_id`로 legacy row를 가리키며,
current import row·operator edit·`csv_explicit_feature_id`/`admin_review`/`forward_recovery` accepted
decision이 없는 item은 legacy-only projection이다. legacy `candidate`/`rejected`는 candidate backfill
후 이 item을 archive하고 public set에서 제거한다. 독립 import/admin/forward-recovery evidence가
있는 item은 보존하며 manifest에 근거를 기록한다. legacy `archived`만으로 source absence를 추정하지
않고 locked current head/link로 다시 분류한다. 어느 bucket도 exact하게 분류되지 않으면 migration을
중단한다.

## 7. HTTP/OpenAPI/consumer contract

### 7.1 legacy detail snapshot의 canonical replacement

PinVi가 실제로 소비하는 legacy admin
`GET /v1/admin/features/curated/{curated_feature_id}/detail-snapshot`는 overlay의 단건 wrapper다.
legacy snapshot은 항상 item 하나만 담으므로 `curated_feature_id`를 canonical identity로 보존할
근거가 없다. T-VN-40은 `feature.curated_feature_detail_snapshots`와 trip-copy snapshot cache를
물리 삭제하고, 다음 typed service endpoint로 바꾼다.

```
GET /v1/service/curation-items/{curation_item_id}/detail-snapshot
GET /v1/service/curation-collections/{collection_id}/detail-snapshot
```

이 endpoint는 cache table을 새로 만들지 않고 one repeatable-read query에서
`curation_items → curation_collections → typed Feature/subtype → source record`를 직접 조립한다.
측정 전 materialized cache를 재도입하지 않는다. response는 closed
`CurationItemDetailSnapshot`이며 다음 exact top-level key만 갖는다. HTTP bigint revision/transition
identity는 JavaScript 정밀도 손실을 피하도록 decimal string 또는 opaque ETag/cursor로만 노출한다.

```json
{
  "curation_item_id": "UUID",
  "collection_id": "UUID",
  "row_revision": "7",
  "etag": "sha256:<canonical-json>",
  "updated_at": "RFC3339",
  "collection": {"theme_slug": "…", "theme_name": "…", "title": "…", "edition_key": "…"},
  "item": {"feature_id": "…", "relation": "…", "sort_order": 0, "title": null, "summary": null},
  "feature": {"feature_id": "…", "name": "…", "category": "…", "kind": "…", "lon": 0, "lat": 0,
              "address": {}, "detail": {}, "source_record_key": "…"}
}
```

`collection`/`item`/`feature`의 exact property·nullable/type은 Map OpenAPI와 PinVi typed consumer
test가 freeze한다. endpoint는 canonical membership의 `item.source_present`,
`item.status='included'`,
`item.archived_at IS NULL`, collection `status='published' AND visibility='public' AND archived_at IS
NULL`, public theme, linked `feature.public_features`, 그리고 item/Feature와
exact-match하는 current accepted link decision이 모두 있을 때만 반환한다. accepted decision의
`match_basis`는 `curation_link_basis.TRUSTED_LINK_BASES` whitelist에 들어야 하며
`legacy_unattributed`와 알 수 없는 값은 fail-close한다. 하나라도 없으면 404를 반환해
candidate/미승인/비공개/archived item을 PinVi snapshot으로 만들지 않는다. 이 술어는 public
collection/Feature aggregate의 trusted-link 및 3축 visibility 정본과 같은 SQL helper를 사용하고
별도 축 재구현을 금지한다. legacy `curation_status`, `curated_feature_id`, `items[]`, `day_index`,
`memo`는 response에 남기지 않는다. PinVi는 same Map head의 new item id/path/schema로 re-vendor하고
old snapshot path와 types를 compile/static gate에서 0으로 만든다.

snapshot `etag`은 그 `etag` key 자체를 제외한 closed payload를 canonicalization version 1
(UTF-8, NFC string, lexicographic object keys, array order preserved, decimal-string integers, explicit
null, insignificant whitespace zero)로 직렬화한 SHA-256이다. HTTP header는 strong
`ETag: "sha256:<64hex>"`이고 body `etag`는 quote를 제외한 동일 값이다. `If-None-Match` exact match는
304 empty body, mismatch는 200이다. golden payload/hash/header/304 tests를 Map/PinVi 양쪽에 둔다.

manual `admin_review` item은 `source_record_key`가 없어도 canonical/public membership이 될 수 있다.
따라서 snapshot의 `feature.source_record_key`와 source projection은 nullable이며, trusted accepted
decision과 public Feature가 있으면 manual item도 반환한다. source record key가 있는 item은
record/entity가 exact-match하지 않으면 404지만, 없는 item을 암묵적으로 import 불가로 만들지 않는다.

PinVi의 authoritative discovery/refresh는 collection snapshot route를 쓴다. 첫 page는 ordered active
public item `(curation_item_id,row_revision,item-payload-hash)` 전체의 `item_set_hash`, count, collection
representation ETag, closed collection payload, item snapshot page, opaque `next_cursor`를 반환한다.
`item_set_hash_version='ktm-db-item-set-v1'`은 PostgreSQL이 ordered positional item leaf
`[curation_item_id,row_revision,updated_at,collection/theme/Feature/item/source projection]`의 JSONB text
SHA-256을 만들고, ordered `[curation_item_id,row_revision,leaf_hash]` JSONB vector를 다시 SHA-256한
opaque server receipt다. 이는 canonical JSON v1 response hash가 아니며 PinVi가 재계산하지 않는다.
PinVi는 모든 page의 version/hash/count 동일성, item id 유일성, 마지막 `complete=true`를 검증하고
receipt에 그대로 결박한다. service snapshot 지원 상한은 public item 2,000개이며 DB query는 2,001개에서
중단해 413을 반환한다. collection은 이 상한 안에서 분할해야 하며 API resident page는 최대 201행이다.
cursor는
collection id, collection revision, item set hash, last item key를 서명해 다음 page마다 current set과 exact
equality를 다시 검증한다. 중간 변경이면 409 restart를 반환해 서로 다른 시점의 page를 섞지 않는다.
마지막 page는 `complete=true`; PinVi는 모든 page와 count/hash가 맞을 때만 한 transaction에서 plan/POI
authoritative set을 교체한다. 첫 요청의 `If-None-Match` exact match는 304이며 receipt는 단일 item ETag가
아니라 first-page closed response ETag + item set hash/version에 결박한다. first-page ETag는
`page_size`, items, `next_cursor`, `complete`를 포함한 실제 response에서 `etag`만 제외하고 계산하므로
다른 page size는 같은 validator를 공유하지 않는다. item route는 단건 조회/진단용이고 multi-item
collection completeness의 근거가 아니다.

PinVi persistence mapping은 `collection_id → curated plan`, `curation_item_id → plan POI`다. plan은
`source_collection_id uuid UNIQUE`, POI는 `(plan_id, source_curation_item_id uuid) UNIQUE`를 가지며
source revision은 int4가 아니라 bigint-safe decimal/BigInteger로 저장한다. collection import는 item
snapshot을 keyset으로 전부 가져와 한 plan의 POI set을 authoritative upsert하고, item archive/
source_present=false는 다음 refresh에서 POI를 remove/archive한다. old `source_curated_feature_id`,
`source_curated_feature_version`, `source_curated_feature_item_id`와 old indexes/types는 paired PinVi
migration에서 new UUID identities로 exact backfill 후 물리 제거한다.

PinVi import는 `(actor, collection_id, Idempotency-Key)` immutable receipt에 request fingerprint와 Map
snapshot ETag를 결박한다. service 내부 commit을 제거하고 plan/POI mutation + import receipt + admin
audit를 한 transaction으로 commit한다. exact replay는 stored result, changed fingerprint는 409다.
If-None-Match 304는 mutation/audit 0이며 200 changed ETag만 authoritative refresh한다. concurrent same/
different key, response/audit failure, multi-item pagination, old→new identity backfill을 paired integration과
n150 live에서 검증한다.

### 7.2 public

- public `/v1/curations*`, Feature `curations[]`, PinVi curation consumer는 canonical collection/item
  projection만 쓴다.
- `/v1/curated-features`, its `cursor` kind, public `/v1/curated-themes`, public
  `/v1/curated-sources`, legacy `curation_status`
  response/query field는 제거한다. redirect와 no-op parameter는 없다.
- public response에는 candidate id/review_state/eligibility_present/rank/evidence/rejection/actor/audit을 노출하지 않는다.

### 7.3 admin candidate API

| method/path | command/query | required contract |
|---|---|---|
| `GET /v1/admin/theme-feature-candidates` | admin keyset list | `rule_id`, `theme_id`, `source_id`, `review_state`, `eligibility_present`, `feature_id` AND filter; `updated_at,candidate_id` cursor |
| `GET /v1/admin/theme-feature-candidates/{id}` | detail | current typed Feature summary, rule/source metadata, source evidence digest, 두 축/revision |
| `GET /v1/admin/theme-feature-candidates/{id}/transitions` | audit timeline | descending `transition_id` keyset; actor/evidence only admin |
| `POST /v1/admin/theme-feature-candidates/{id}/promote` | typed promotion | candidate `If-Match`, `Idempotency-Key`, target collection revision, nullable create-only/existing item revision, typed item identity/body, reason code |
| `POST /v1/admin/theme-feature-candidates/{id}/reject` | typed rejection | `If-Match`, `Idempotency-Key`, non-empty reason code |
| `GET /v1/service/curation-items/{id}/detail-snapshot` | PinVi typed import snapshot | canonical item id, exact `ServiceToken` principal/scope only; closed direct projection, no legacy overlay/cache |

`If-Match` mismatch는 412, missing candidate/collection is 404, stale source/current-head or identity
conflict is 409, malformed typed input is 422, denied actor is 403이다. successful command response에는
candidate revision, candidate transition id, canonical item id/revision(승격만)을 포함한다. item body는
legacy overlay status가 아닌 canonical item fields만 허용한다.

candidate `If-Match`와 별개로 promotion body는 `expected_collection_revision` 및
`expected_item_revision`을 명시한다. 후자는 새 item 생성일 때만 `null`이며, 기존 identity 갱신은
현재 revision을 반드시 보낸다. router는 별도 claim을 만들지 않고 active
`current_domain_command().command_id`를 procedure에 전달한다.

admin UI 정본 route는 `/admin/curations/candidates`다. list는 위 AND filters/keyset을 URL state로
보존하고 detail drawer는 representation ETag, raw candidate CAS ETag, timeline을 함께 로드한다.
promotion은 existing collection 선택 또는 create, existing/create-only item identity와 revision을
명시적으로 보여주며 reject는 non-empty reason을 요구한다. 409/412/428은 자동 stale retry하지 않고
새 detail/ETag를 reload한 뒤 사용자가 다시 제출하게 한다. old curated-feature navigation/component와
status UI는 0이다. mocked Playwright와 n150 live에서 promote→public collection→PinVi import,
reject non-public, stale ETag recovery를 검증한다.

snapshot route는 AdminBFF와 admin proxy secret을 받지 않는다. 전용 `ServiceToken` role
`pinvi:curation-snapshot:read`와 route-policy exact binding만 허용하며 public/user/ops/다른 service
scope는 403이다. 고정 actor는 token principal에서 파생하고 caller header 문자열을 신뢰하지 않는다.
OpenAPI export 후 Map user/service/admin spec과 generated types를 exact head에서 갱신한다. PinVi
user/service vendor는 동일 Map commit에서 re-extract하고 paired SHA, codegen compile,
legacy endpoint/type zero evidence를 `consumer-rollout-v1.json`에 기록한다.

## 8. performance and correctness gates

| query/operation | required index/proof |
|---|---|
| admin candidate list | global open+present, state/presence, rule+state, theme/source join, feature filter별 production-shape keyset `EXPLAIN JSON` |
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
   source/rule eligibility removal→merge→recovery/cleanup E2E. Playwright runs on n150, not WSL.

## 9. final removal manifest minimum set

The implementation PR must replace this minimum list with actual catalog OIDs/signatures before drop.

- relation: `feature.curated_features`, `feature.curated_feature_detail_snapshots`,
  `feature.curated_tripmate_copy_snapshots` and every legacy-only snapshot relation;
- curation item bridge: `legacy_projection_id`, its FK and
  `uq_curation_items_legacy_projection_id`;
- legacy PK rekey: 0074에서 추가한 네 `ON UPDATE CASCADE` FK와
  `reject_curation_history_mutation()`의 `curation_item_id`-only UPDATE 예외;
- sync: `feature.sync_curated_feature_collection`,
  `trg_sync_curated_feature_collection`, every reverse-sync function/trigger;
- code: `curated_repo` overlay writer/read models, client exports, curated refresh Dagster asset/schedule,
  legacy merge branches, legacy router/DTO/cursor/frontend/e2e fixture;
- contract: public `/v1/curated-features`, legacy admin curated route/detail-snapshot/OpenAPI/generated
  types/PinVi vendor; replacement is canonical service
  `/v1/service/curation-items/{id}/detail-snapshot` only;
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
