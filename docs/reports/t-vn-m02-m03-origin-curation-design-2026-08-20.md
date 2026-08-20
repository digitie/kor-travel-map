# T-VN-M02/M03 — 생성 provenance 보존과 curation 동시 생성 설계

- 상태: proposed — DB/curation 전문 적대 검토 반영, M03 import 행별 child command 결정
- 기준: `origin/main` `546b92e54b7e83dfd8378d372340a67e5a1ea38e`
- 선행: T-VN-M01 foundation `14792385`, T-VN-40C `0225_tvn40c_physical_removal`
- 관련: ADR-066, ADR-074, ADR-090, ADR-093, T-VN-M01~M05
- 작성일: 2026-08-20

## 1. 결론

M02와 M03는 M01 foundation만으로는 구현할 수 없다. 현재 ORM과 HTTP 계약에는
`feature.manual_feature_identity_claims`와 `feature.feature_creation_origins`가 있으나,
실제 Alembic head에는 두 relation과 manual wrapper가 없다. `alembic/env.py`의 temporary
metadata-only ledger가 이를 명시적으로 숨기고 있으며, 만료 revision은 이미
`0226_m01_manual_feature_create`로 고정돼 있다.

따라서 이 lane의 첫 코드 변경은 다음 세 작업을 섞지 않는 순서로 진행한다.

1. **M01 DB tranche** — `0226_m01_manual_feature_create`로 M01 relation, append-only
   trigger, ACL, backup/restore four-relation manifest와 manual writer를 실제 DB에 만든다.
   같은 commit에서 temporary Alembic ledger와 pre-0226 sentinel을 제거한다.
2. **M02** — M01 evidence의 제한된 read model, Feature patch/state와 hard-purge fence,
   backup/restore를 지나는 불변 검증을 만든다. evidence base table의 runtime direct SELECT를
   넓히지 않는다.
3. **M03** — 기존 curation item create와 별개인 하나의 command/procedure에서 manual Feature와
   `curation_items`를 함께 만든다. 이 때만 `manual_curation` origin domain을 추가한다.

route flag는 이 세 tranche와 paired PinVi fence, ACL 및 restore 검증이 모두 끝날 때까지
`false`다. 단계 사이에 "부분 활성화"하거나, M03의 origin을 기존 M01 route에서 추론하지 않는다.

## 2. 관찰한 현재 경계

### 2.1 M01 foundation은 DB migration이 아니다

`ManualFeatureIdentityClaimRow`와 `FeatureCreationOriginRow`는 각각 canonical UUID,
exact identity tuple, domain command causation, immutable origin을 선언한다. 그러나 현재
head에는 relation/procedure가 없어 manual route는 `503 MANUAL_FEATURE_CREATE_NOT_READY`로
fail-closed한다. 이 상태에서 M02 read route나 M03 write route만 추가하면 catalog와 ORM,
API가 다시 갈라진다.

`0226`은 실제 `0225` 뒤로만 이어지는 forward-only migration이다. byte-frozen
`0200_schema_baseline.py`, `alembic/baseline/schema.sql`, `alembic/baseline/seed.sql`은
이번 lane에서도 변경하지 않는다.

### 2.2 기존 curation item create는 Feature를 만들지 않는다

T-VN-40의 `feature.create_curation_item_command`는 `feature_id`가 없어도
`place_name`이 있으면 item을 만들 수 있다. 반대로 `feature_id`가 있을 때는 active,
non-suppressed Feature와 link decision을 검증한다. 이 procedure가 받는 command operation은
`admin.curation-item.create`이며, M01 wrapper는
`admin.feature.create.manual-v1` command, `manual_admin` origin, 전용 principal을 hard-code한다.

따라서 application transaction에서 두 기존 procedure를 단순히 연달아 부르는 방식은
origin과 causation을 거짓으로 만들거나, terminal result/replay를 두 command로 분열시킨다.
M03의 combined writer가 이 둘을 대신 소유해야 한다. 더구나 M01 manual create는
`READ COMMITTED`를 명시 검증하지만, T-VN-40 item/import create는 `SERIALIZABLE` policy와
`40001` whole-transaction retry를 소유한다. 따라서 M03가 M01 HTTP/wrapper를 기존 curation
transaction에서 호출하면 isolation error가 나고, HTTP를 분리 호출하면 atomicity를 잃는다.

### 2.3 source record 부재는 허용되지만 M01 입력 부재는 허용되지 않는다

`curation_items.source_record_key`는 nullable이므로 provider source record 없는 manual Feature를
link할 수 있다. 그러나 M01 Feature는 `kind`, `name`, `category`, 대한민국 범위의 non-null
`coord`를 요구한다. 현행 curation CSV/import row에서 그 값을 추정하거나, title/address로
좌표를 합성해서는 안 된다. 기존 import는 계속 unlinked item을 표현할 수 있어야 하며,
M03의 manual-create branch는 explicit `manual_feature` input을 가진 새 versioned payload에서만
열린다.

## 3. M02 — evidence read와 불변

### 3.1 read model

M02의 admin read model은 Feature의 current canonical UUID를 입력으로 받고 다음 provenance
snapshot만 반환한다.

| 구분 | 반환값 |
|---|---|
| claim | `feature_id`, `feature_kind`, `name_key`, `lon_e6`, `lat_e6`, `claim_basis`, `claimed_at`, `claimed_by_command_id` |
| origin | `origin_kind`, `creation_command_id`, `creator_principal_id`, `created_by_actor`, `created_at`, `invoker_role`, `procedure_definer` |

이 표면은 admin API에서만 읽는다. public/service OpenAPI와 PinVi snapshot에는 origin, actor,
exact normalized name/coordinate claim을 추가하지 않는다. base relation의 SELECT를 API/Dagster
runtime에 직접 주지 않고, closed signature의 typed reader(view 또는 SECURITY DEFINER function)를
manual read executor에만 부여한다. reader는 현재 `feature.features` row를 먼저 확인하므로,
hard-purge 뒤 남아 있는 evidence를 일반 feature detail route에서 탐색하게 만들지 않는다.

새 HTTP route와 response exact shape는 implementation commit에서 OpenAPI와 generated admin type에
같이 고정한다. non-manual Feature에는 invented origin을 돌려주지 않으며, 존재하는 Feature지만
creation evidence가 없을 때의 response는 explicit absence로 표현한다. 이 null/404 구분은
route body를 정할 때 separately test한다.

### 3.2 불변식

M02는 다음을 SQL catalog와 실제 mutation으로 함께 검증한다.

1. `claim`/`origin`의 모든 semantic column은 explicit `NOT NULL`이고, exact/composite
   uniqueness와 command FK는 유지된다.
2. claim/origin은 UPDATE, DELETE, TRUNCATE를 stable `42501`로 거부한다. API/Dagster/public은
   direct SELECT/DML/TRUNCATE와 owner/`SET ROLE` 우회를 얻지 않는다.
3. 수동 Feature의 normal patch와 3축 state transition은 core/subtype/state audit만 바꾸며,
   claim tuple과 origin snapshot을 바꾸지 않는다. 입력 body/header로 origin, principal,
   creation command를 덮어쓸 수 없다.
4. M02 계약 전에는 manual claim/origin Feature의 hard purge를
   `409 MANUAL_FEATURE_PURGE_NOT_READY`로 계속 막는다. evidence relation은 feature FK가 없으므로
   future purge가 core row를 지워도 cascade하거나 정리하지 않는다. 현 curation item의
   `ON DELETE SET NULL` link가 만든 history/public projection 효과, state/If-Match와 전용
   privilege를 M02가 명시해 검증하기 전에는 raw `DELETE FROM feature.features`를 운영 경로로
   허용하지 않는다.
5. backup manifest는 한 consistent snapshot에서 claim, origin, 그들이 참조하는
   `ops.domain_commands`, `ops.domain_command_results`의 count와 PK-order canonical JSONL
   SHA-256 root를 함께 기록한다. `--no-owner --no-privileges` restore 뒤 owner repair,
   closed ACL reconciliation, 두 runtime login preflight를 통과하기 전 service를 열지 않는다.

M02는 origin kind를 넓히지 않는다. `manual_request`는 M04의 separate authenticated queue,
`manual_curation`은 아래 M03 writer와 같은 migration에서만 추가한다.

## 4. M03 — curation과 manual Feature의 하나의 command

### 4.1 명시적 input과 operation

admin item create/curation import의 missing-Feature branch는 nullable `feature_id`를 암묵적
신호로 쓰지 않는다. 새 versioned input은 다음 XOR를 강제한다.

- existing link: `feature_id`만 제공한다.
- manual create and link: `manual_feature` object만 제공한다.

`manual_feature`는 M01과 같은 required `kind`, `name`, `category`, `coord`와 허용된
detail/marker/reason만 담는다. caller-owned UUID, identity key, origin, principal, 3축 state는
금지한다. 기존 CSV v1/import plan은 이 object를 만들지 않으므로 종전처럼 unlinked 또는
candidate item만 처리한다. M03가 import input을 확장할 경우에는 explicit manual object를
운반하는 새 versioned row/plan contract와 preview validation을 같이 낸다.

single-item combined command operation은 existing `admin.curation-item.create`를 재해석하지 않는
새 versioned 이름을 쓴다. 하나의 domain command와 하나의 terminal result가 Feature UUID,
curation item UUID, 두 row revision을 함께 봉인한다. 동일 key/body replay는 두 identity와
headers를 byte-identical하게 돌려주고, same key/different body는 기존 domain-command conflict로
닫는다.

CSV/import plan의 multi-row create는 이 single-item command를 그대로 재사용하지 않는다. claim의
`claimed_by_command_id`와 origin의 `creation_command_id`는 각각 unique이므로, 하나의
`admin.curation.import` receipt로 여러 manual Feature를 만들 수 없다. **2026-08-20 사용자 결정으로
M03 import는 행별 child command를 발급한다.** 각 typed manual row는 stable child command/terminal
result 하나를 갖고, 그 child 하나만 Feature+item 한 쌍과 claim/origin을 소유한다. outer import
receipt만으로 여러 provenance 행을 만드는 우회는 금지한다.

### 4.2 combined DB writer

새 SECURITY DEFINER procedure는 다음 순서를 한 external transaction으로 실행한다.

1. session user, curation writer scope와 creation scope, locked command operation/actor를 검증하고
   `SERIALIZABLE` isolation, collection 및 필요한 advisory locks를 얻는다. `40001`은 current
   curation command policy처럼 outer transaction 전체를 재시도한다.
2. M01과 같은 server UUIDv7, opaque legacy bridge ID, DB exact identity claim을 만든다.
   exact conflict는 curation item을 만들지 않고 deterministic conflict로 전체 command를 rollback한다.
3. fixed initial Feature tuple과 subtype/initial override를 만들고, generic result UUID/inserted
   parity를 확인한다.
4. `feature_creation_origins`에 `manual_curation`, route-bound principal, locked command actor를
   넣는다. `manual_admin` procedure나 request actor로 이 값을 위장할 수 없다.
5. same command으로 `curation_items`, link decision, collection revision/effect를 쓰고 response를
   봉인한다. `source_record_key`는 `NULL`로 보존한다.

어느 fault, curation identity conflict, stale collection revision, Feature validation, terminal
result 실패도 claim/origin/core/subtype/item/link decision/effect를 남기지 않는다. 반대로 success는
각각 정확히 한 행이다.

기존 curation procedure와 M01 manual wrapper를 application code에서 순차 호출하거나, 일반
AdminBFF actor/route 문자열만으로 `manual_curation`을 발급하는 방식은 금지한다. 새 procedure의
closed signature, owner, executor privilege와 operation check가 origin의 인증 근거다.

### 4.3 origin domain과 ACL

M03 migration에서만 `ck_feature_creation_origins_kind`를
`manual_admin|manual_curation`으로 확장한다. curation origin은 M03 combined procedure에서만
insert 가능하고, `manual_admin` writer는 계속 `manual_admin` 하나만 쓴다. M04 전에는
`manual_request`를 constraint, reader, OpenAPI enum 어느 곳에도 넣지 않는다.

`manual_curation` CHECK는 value 목록만 넓히지 않는다. `(origin_kind,
creator_principal_id, invoker_role, procedure_definer)` 조합을 허용 쌍으로 닫아 cross-pair를
거부한다. M03 wrapper는 `manual_curation`과
`admin-ui-bff.manual-curation-feature-create.v1`을 상수로 넣고, M01 wrapper는 기존
`manual_admin` pair만 넣는다.

Admin BFF의 existing curation authorization만으로 creator origin을 추정하지 않는다. M03 route는
M01의 `AdminFeatureCreateBFF` capability와 curation admin authorization을 같은 OpenAPI security
requirement object에서 AND로 요구한다. PinVi/general AdminBFF/shared credential은 zero-write로
거부한다. API runtime에는 combined procedure execute만 주고, Dagster/provider executor에는 주지
않는다. claim/origin base relation의 direct privilege를 이 이유로 넓히지 않는다.

current bridge에서 claim/origin은 canonical UUID를 쓰지만 `curation_items.feature_id`는 current
text `f_*` FK다. combined writer는 item에는 wrapper의 verified legacy output을, origin/response에는
canonical UUID를 쓰며 T-VN-39 UUID-only target parity를 별도 fixture로 고정한다.

M03 combined create의 exact duplicate는 existing winner에 item을 자동 연결하지 않고 `409`으로
끝낸다. winner의 existing origin/claim causation을 새 curation command로 재해석할 수 없기
때문이다. 운영자는 이후 existing-feature item route에서 명시 link를 선택한다. initial state는
M01과 같은 `active/published/valid` 고정 tuple을 쓴다.

## 5. 구현·검증 순서

1. `0226` physical DDL, temporary Alembic ledger 제거, role bootstrap two-phase provisioning,
   M01 backup/restore/ACL/current-target freeze를 실제 DB로 완결한다.
2. M02 typed provenance reader, admin response/OpenAPI, patch/state/purge/restore adversarial tests를
   추가한다. manual origin domain은 여전히 `manual_admin` 하나여야 한다.
3. M03 combined procedure, explicit input/preview, command registry/replay, ACL, admin UI flow와
   current/target freeze를 추가한다. 이 migration에서만 `manual_curation` domain을 연다.
4. fresh upgrade, partial-catalog drift, two-session concurrency, fault injection, no-owner restore,
   API/Dagster catalog preflight, OpenAPI export, backend/frontend CI를 모두 실행한다.

각 checkpoint는 remote feature branch에 push한다. 구현 PR은 draft로 유지하고, M02 DB 불변식과
M03 curation 원자성 전문 리뷰가 같은 reviewed SHA에서 모두 GO가 되기 전에는 route flag나
production credential 배선을 활성화하지 않는다. M01 `READ COMMITTED` writer를 완화하거나,
curation write policy를 낮춰 isolation을 맞추는 방식은 취하지 않는다.

local Docker는 legacy role graph로 `0225`까지만 올리는 restricted migrator를 먼저 실행하고,
그 뒤에만 M01 owner·executor role phase와 `0226` head upgrade를 연다. 재기동 때 relation marker가
완전하면 legacy bootstrap은 M01 repair phase로 승격한다. marker가 partial이면 어느 role도 바꾸지
않는다. external DB/infra overlay는 이 세 local service를 profile로 제외하므로, 운영자는 같은
`legacy bootstrap → 0225 one-shot → M01 phase → application upgrade` 순서를 별도 orchestration으로
사전 완료해야 한다.

## 6. 확정된 M03 import child-command 범위

single-item admin editing은 위 writer 하나와 command 하나로 닫힌다. import는 parent
`admin.curation.import` command가 batch의 preview/commit lifecycle을 소유하고, 실제 manual Feature
생성은 plan row마다 다음의 private child command로 분리한다.

1. preview는 row별 typed `manual_feature` payload와 canonical payload SHA-256을 immutable plan에
   저장한다. `metadata_json`에 untyped input을 숨기지 않는다.
2. child idempotency identity는 retry마다 새로 생기는 `parent_command_id`나 commit 결과인
   `import_row_id`를 쓰지 않는다. locked parent의 `actor + operation + Idempotency-Key + request
   fingerprint`와 immutable `import_plan_id + plan_sha256 + plan_row_number + typed manual payload
   SHA-256`에서 결정적으로 유도한다. child operation은
   `admin.curation-import.manual-feature-row.create-v1`이며 외부 HTTP가 child key를 제공하거나
   child command를 단독 replay하는 route는 없다.
3. child 하나는 `claim → Feature/core/initial state → origin → subtype/override → curation item →
   accepted link decision → child terminal result`를 소유한다. parent command/result에는 ordered row별
   child command ID, Feature UUID, curation item ID와 terminal status의 canonical summary만 남긴다.
4. import commit은 하나의 `SERIALIZABLE` transaction으로 parent와 모든 child mutation/result를 함께
   확정한다. 하나라도 실패하면 parent result, child command/result, claim/origin, Feature, item, link
   decision 모두 rollback한다. `40001`은 기존 parent command decorator가 전체 batch를 재시도한다.
   parent replay는 route/plan 검증보다 먼저 저장된 parent response를 byte-identical하게 반환하며
   child를 다시 검증·생성하지 않는다.
5. `ops.curation_import_manual_feature_children`는 `(import_plan_id, plan_row_number)` PK,
   `UNIQUE(child_command_id)`, `UNIQUE(import_row_id)`를 갖는다. plan claim과 typed payload SHA,
   child command, `(feature_uuid, child_command_id)` claim causation, `(import_row_id, curation_item_id)`
   receipt, `(link_decision_id, curation_item_id, import_row_id)` decision evidence를 FK로 묶고
   append-only trigger로 봉인한다. parent summary는 요청 JSON이 아니라 이 linkage에서 순서대로
   구성한다.

M03 migration은 parent/import-row/child-command의 immutable linkage와 one-row/one-child uniqueness를
선언적으로 만든다. 이 linkage는 claim/origin의 command FK를 대체하지 않는다. 어느 경로에서도
`admin.curation.import` 하나에 여러 claim/origin을 직접 묶거나 manual row를 추론해서는 안 된다.

## 7. 비목표

- provider/manual fuzzy dedup 또는 자동 merge(M05)
- 범용 Feature request queue와 `manual_request` origin(M04, PinVi는 첫 consumer)
- public/service API 또는 PinVi snapshot에 provenance/actor/claim 노출
- M01/M02를 건너뛴 curation CSV 제목·주소 기반 Feature 추정 생성
- frozen `0200` baseline 및 sidecar 변경
