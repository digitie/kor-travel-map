# T-VN-M05 — 수동/Provider 중복 판정과 paired 참조 재결합 설계

## 목적과 경계

M01~M04 origin(`manual_admin`, `manual_curation`, `manual_request`) Feature와 provider가
나중에 발행한 Feature가 같은 실체일 수 있다. M05는 이 쌍을 **후보로 기록하고 admin이
명시적으로 판정**하게 한다. 점수는 후보 우선순위일 뿐 자동 action 권한이 아니다.

다음은 M05 범위 밖이다.

- provider끼리의 기존 `ops.dedup_review_queue` 정책 변경
- `merge_from_review()`의 generic master 선정·source link 재배치
- Map DB에 대한 외부 소비자 직접 접근 또는 Map의 외부 DB 직접 변경
- bulk 판정, implicit survivor, auto-merge

## 기존 경로를 쓰지 않는 이유

| 기존 표면 | M05에서 배제하는 이유 |
| --- | --- |
| `list_dedup_refresh_features()` | `source_links`와 primary source를 INNER JOIN하므로 manual origin Feature가 입력에서 사라진다. |
| `core.dedup.find_dedup_candidates()` | `auto_merge` 분류를 내며 기존 큐 의미를 공유한다. M05는 같은 score components만 재사용하되 결과를 항상 `candidate`로 고정한다. |
| `ops.dedup_review_queue` | pending 행과 decision reason을 update하며 rerun 증거를 덮는다. |
| `merge_from_review()` | master 자동 선택, source link 이동, loser cascade가 provider lineage·수동 origin 보존과 충돌한다. |

## Map 불변 evidence 모델

`0231_m05_manual_provider_dedup`는 아래 여섯 relation을 추가한다. case·resolution·event·ACK와
subscription은 append-only evidence이며 `RESTRICT` FK를 갖는다. lease만 delivery를 위한 mutable
operational state다.
raw table DML은 runtime login에서 거부한다.

revision은 `0231_m05_manual_provider_dedup`이고 정확한
`down_revision = 0230_tvn_m04_feature_request_queue`다. C05→M01→M04 graph가 착지한 뒤에만 적용한다.

적용된 evidence revision은 변경하지 않는다. service ACK lease lock, admin evidence reader 및 paired
consumer의 immutable initial cursor provisioning은 후속
`0232_m05_reconciliation_delivery`에서 forward-only로 추가한다.

| relation | 한 행의 의미 | 핵심 불변식 |
| --- | --- | --- |
| `ops.manual_provider_dedup_cases` | 특정 manual/provider Feature와 그때의 evidence fingerprint가 만든 한 episode | manual origin/claim, provider dataset/entity와 immutable source record/raw hash, 당시 head snapshot, 양 UUID·row revision, canonical snapshots, score components/version/distance를 생성 시점 값으로 보존한다. 같은 **미종결** fingerprint만 idempotent다. |
| `ops.manual_provider_dedup_resolutions` | case의 유일한 terminal 판단 또는 detector의 `superseded` marker | case당 하나만 허용한다. admin 판단은 서로 다른 unique command FK·actor·reason이 필수이고 detector supersede만 command 없이 `superseded_by_case_id`와 ingestion causation이 필수다. |
| `ops.feature_reference_reconciliation_events` | merge/detach가 외부 참조에 요구하는 immutable action | resolution당 0 또는 1행이다. monotonic `event_sequence`(gap 허용), canonical envelope/schema version/SHA-256, old feature pair, optional replacement pair, state transition/command, occurred-at를 고정한다. |
| `ops.feature_reference_reconciliation_acks` | service principal이 local receipt를 commit한 뒤 남기는 ack | `(event_id, principal_id)` unique이며 update/delete 불가다. ack command FK와 stored event SHA-256/local receipt SHA-256가 필수다. |
| `ops.feature_reference_reconciliation_subscriptions` | provision된 service principal의 immutable initial delivery cursor | principal, read/ack scope와 historical replay 시작점을 고정하므로 backup evidence root에 포함한다. |
| `ops.feature_reference_reconciliation_leases` | principal의 현재 single-worker delivery lease와 acked-through cursor | evidence가 아닌 mutable operational state다. live lease는 한 worker만 보유하며 cursor 앞의 event를 건너뛸 수 없고 subscription initial cursor보다 낮아질 수 없다. |

case fingerprint는 다음 canonical input의 SHA-256이다.

1. manual Feature `feature_id`/UUID/row revision와 immutable creation origin/command;
2. provider Feature `feature_id`/UUID/row revision, provider dataset, source entity/head/source
   record/raw payload hash;
3. 두 Feature의 canonical `{kind,name,category,coord}` snapshot;
4. scorer id `manual-provider-v1`, name/spatial/category/total score와 distance.

동일 fingerprint의 재탐지는 같은 pending case를 반환한다. global unique는 두지 않아 종전
`superseded` fingerprint가 재등장해도 새 episode를 만들 수 있다. row revision/source head/scorer가
바뀌면 detector는 global curation fence → 미종결 case lock → UUID 정렬 Feature lock → source proof의
고정 순서로 현재 proof를 다시 계산한 뒤, 종전 pending case에 `superseded` resolution을 append하고 새
case를 같은 transaction에서 쓴다. terminal case를 supersede하지 않으며 과거 점수·근거·판단은 갱신하지
않는다. provider source head/link/Feature 변경도 detector proof와 같은 transaction에서 commit하거나
detector가 이 재검증을 수행해야 한다.

## 후보 탐지

전용 repository는 `feature.feature_creation_origins`가 manual origin인 active/published/valid
Feature와, primary `source_link`·provider dataset·current source record가 있는
active/published/valid Feature를 따로 읽는다. provider query의 INNER JOIN을 manual 쪽에 재사용하지
않는다.

새 순수 scorer는 기존 `name_similarity`, `spatial_similarity`, `category_similarity`와 동일한
ADR-016 가중치를 계산하지만 `classify_decision()`/`select_master()`는 호출하지 않는다.
`THRESHOLD_MANUAL` 이상인 모든 쌍은 점수와 무관하게 `candidate`다. 대규모 provider scope는
행정구역/공간 grid로 먼저 block하고, complete set이 아니라는 사실과 detector input count를 case
receipt에 남긴다.

provider executor procedure는 candidate evidence만 append할 수 있다. admin executor와 API runtime은
detector relation의 직접 INSERT/UPDATE 권한을 얻지 않는다.

DB 제약은 다음을 명시적으로 둔다. case는 두 Feature identity pair, manual
`(feature_id, creation_command_id)` origin/claim, provider `(source_entity_key, source_record_key)`와
raw hash를 `RESTRICT` FK 또는 동등한 definer validation으로 결박한다. 이를 위해 필요한 origin/claim
composite unique를 먼저 추가한다. resolution은 `UNIQUE(case_id)`, `UNIQUE(command_id)`, decision별
command/actor/reason nullability CHECK, `superseded_by_case_id` FK를 가진다. event는
`UNIQUE(resolution_id)` 및 rebind의 exact replacement pair / detach의 null replacement CHECK를 가진다.
모든 evidence FK는 cascade를 금지한다.

## admin 판단과 동시성

`POST /v1/admin/manual-provider-dedup-cases/{case_id}/decisions` body는 다음을 모두 필수로 받는다.

- `decision`: `kept` | `merged` | `manual_retired`
- `expected_case_fingerprint`, manual/provider `expected_row_revision`
- `survivor_feature_id` (`merged`일 때 필수이며 case의 provider Feature와 같아야 함)
- 비어 있지 않은 `reason`, UUID `Idempotency-Key`

procedure의 고정 순서는 global feature-curation write advisory fence → case row `FOR UPDATE` →
manual/provider Feature UUID 정렬 `FOR UPDATE` → provider source entity/head/record proof다. 그 뒤
origin·source hash·모든 expected revision을 다시 대조한다. 하나라도 다르면
`STALE_MANUAL_PROVIDER_DEDUP_CASE` 409을 반환하며 resolution, Feature, event 모두 쓰지 않는다.
stale은 standard domain-command claim/result에 canonical 409 outcome을 durable하게 남겨 exact replay를
제공하되 M05 resolution/Feature/state transition/event/ack에는 절대 행을 만들지 않는다.

| decision | Map mutation | event |
| --- | --- | --- |
| `kept` | 없음 | 없음 |
| `merged` | provider는 그대로, manual만 canonical retire transition | `rebind`: manual pair → provider pair |
| `manual_retired` | manual만 canonical retire transition | `detach`: manual pair, replacement 없음 |

generic merge procedure, source link/record 변경, provider Feature retire와 automatic survivor는 어느
branch에도 없다. merge와 retire는 admin destructive kill-switch와 `AdminBFF`를 함께 요구하며 이
kill-switch 검사는 repository DB session을 만들기 전에 body의 decision을 보고 수행한다. `kept`도
`AdminBFF`와 evidence revalidation은 필수지만 kill-switch는 필요 없다. M05 repository, router,
detector에는 `find_dedup_candidates`, `classify_decision`, `select_master`, `merge_from_review`,
`apply_feature_merge` 또는 generic dedup queue의 import/call이 없어야 한다.

`merged`/`manual_retired`는 resolution, manual canonical retire transition, state-transition
causation, reconciliation event를 **하나의 procedure transaction**에서 함께 commit한다. `kept`와
`superseded`에는 event가 없으며 event의 old pair, provider replacement pair, state transition과
command는 resolution/action과 정확히 같아야 한다. manual 후보의 근거는
`feature_creation_origins`뿐이며 M04 `resolved_feature_id`를 origin 근거로 쓰지 않는다.

## service reconciliation contract

Map은 admin 조회 두 개와 service endpoint 두 개를 추가한다.

| endpoint | 역할 | 인증/멱등성 |
| --- | --- | --- |
| `GET /v1/admin/manual-provider-dedup-cases` | immutable evidence case의 pending/terminal filter와 stable keyset page를 읽는다. | `AdminBFF`; cursor는 `(created_at, case_id)`이며 bulk/action 없음 |
| `GET /v1/admin/manual-provider-dedup-cases/{case_id}` | case, resolutions, event와 principal별 ACK/oldest-unacked age를 읽는다. | `AdminBFF` |

| endpoint | 역할 | 인증/멱등성 |
| --- | --- | --- |
| `GET /v1/service/feature-reference-reconciliations` | worker lease를 취득/연장하고 해당 principal의 acked-through prefix 다음 event 하나를 읽는다. | 전용 `feature-reference-reconciliation:read` token scope + UUID `X-Reconciliation-Worker-Id` |
| `POST /v1/service/feature-reference-reconciliations/{event_id}/acks` | lease holder가 consumer의 이미 commit된 local receipt hash를 append-only ack로 기록하고 acked-through cursor를 전진한다. | 전용 `feature-reference-reconciliation:ack` scope + UUID `Idempotency-Key` + 같은 worker id |

event response는 저장된 canonical envelope 그대로의 `payload_schema_version`, `event_id`,
`event_sequence`, UTC `occurred_at`, `event_sha256`, case/resolution id, `rebind|detach`, old
`{feature_id, feature_uuid, row_revision}`, optional replacement pair를 가진다. Map은
live Feature join으로 event를 재조립하지 않는다. consumer 이름을 event, role, route, settings
식별자에 넣지 않으며 service token 검증 결과의 principal만 ack identity다.

event의 old `row_revision`은 retire **전** case evidence revision으로 이름을
`old_feature_row_revision_before_transition`으로 고정한다. retire 자체의 결과는 별도
`manual_retire_transition_id`와 `manual_retire_row_revision_after_transition`으로 기록한다.

event 생성은 resolution transaction의 global feature-curation advisory fence 안에서만 일어난다.
따라서 `event_sequence`을 얻은 transaction이 먼저 commit하는 순서가 고정된다. sequence는 rollback
gap을 허용하므로 `acked_through + 1`이 아니라 해당 principal의 cursor보다 큰 event 중 실제
`MIN(event_sequence)`만 다음 event다. principal은 token/HTTP header가 아닌 token verification이
반환하는 안정적 server-side principal ID이고, token rotation 뒤에도 같은 subscription/ack cursor를
쓴다. activation 때 immutable `initial_event_sequence`와 scope를 가진 subscription으로 provision하며
first consumer는 flag가 off인 `0` cursor에서 시작한다. subscription의 stable principal ID가
lease/ack의 FK다. 이후 consumer는 historical replay 여부를 activation procedure의 명시 cursor로만
정한다.

`GET`은 subscription/lease row를 잠그고, live lease가 다른 worker에 있으면 retryable 409을 낸다.
lease는 UUID worker id, increment-only `lease_epoch`, 만료시각을 응답에 돌려주며 ACK은 같은 worker와
epoch를 모두 제시해야 한다. 다음 event가 없으면 204, expiry 뒤에는 새 worker가 같은 다음 event를
다시 받을 수 있다. ACK body는 `event_sha256`, `local_receipt_sha256`, `lease_epoch`를 필수로 받고
lease holder·정확히 다음 실제 sequence·stored event hash·principal·receipt hash를 대조한다. 같은
`(event, principal, event hash, receipt hash)`만 exact replay로 200이며 하나라도 다르면 409이고
ack/cursor 변경은 없다. Idempotency-Key 재사용 body 불일치, ACK 응답 유실 뒤 새 key 재시도, 동시
ACK도 one-write 또는 exact replay만 허용한다. 새 key의 semantic replay는 기존 ack를 읽어 200만
돌리고 새 domain command/evidence를 쓰지 않는다. 소비자는 Map ack보다 먼저 자신의 transaction을
commit한다. ACK 직전 crash는 lease expiry 뒤 같은 event를 다시 받아 local receipt의 payload hash를
검증한 뒤 재-ack할 수 있다. 낮은 sequence의 미commit transaction보다 높은 sequence가 먼저
가시화되는 경쟁도 integration test로 고정한다.

## 첫 consumer의 durable 처리

PinVi는 이 generic service spec의 첫 consumer다. 새 local immutable `delivery_attempt`는 event와
attempt sequence를 PK로 하여 `blocked|applied` attempt, block fingerprint/row root/해소 관측값을
보존한다. 별도 immutable final `applied receipt`만 event id/sequence와 payload hash를 unique로
보존하고 Map ACK의 `local_receipt_sha256`는 이 final receipt만 참조한다. 따라서 blocked attempt가
strict prefix를 영구 정지시키지 않으며, operator 해소 뒤 같은 event를 재검사할 수 있다. 한
transaction에서 다음을 수행한다.

1. old `{feature_id, feature_uuid}` pair가 두 column 모두 정확히 같은 `trip_day_pois`를 `FOR UPDATE`로
   수집한다. `curated_plan_pois` 중 curation receipt의 six-column composite FK에 묶인 행은
   feature pair만 바꾸거나 비우면 receipt FK가 깨지므로 **M05에서 절대 수정하지 않는다**.
2. `rebind`는 두 column을 replacement pair로 함께 바꾼다. `detach`는 reference column을
   비우고 `feature_link_broken_at`을 기록하며 보존된 snapshot은 남긴다. 영향을 받은 row
   id/old/new pair/count root를 immutable impact rows에 보존하고 detach 뒤 cache-target refresh를
   요청하지 않는다.
3. 한 column만 맞는 partial pair, source pair 불일치, receipt-bound `curated_plan_pois`,
   correction/closure target의 비종결 `pending|approved` 상태가 있으면 row를 같은 transaction에서
   `FOR UPDATE`로 고정해 immutable blocked receipt를 남기고 Map ack를 하지 않는다. `rejected`,
   `added`, `duplicate`만 target block의 종결 상태다. terminal `kor_travel_map_ref`는 변경하지
   않는다. operator가 먼저 독립 curation/correction protocol 또는 해당 workflow를 정리해야 한다.
4. 재검사 때 모든 block 원인이 사라지고 모든 current old pair가 action의 의도대로 새 pair 또는
   detach 상태임이 증명되면 `already_reconciled` no-op applied receipt를 만들 수 있다. 그렇지 않으면
   새 blocked attempt만 남긴다. local final receipt와 impact root가 commit된 뒤에만 Map ack를 호출한다.

terminal `feature_suggestions.kor_travel_map_ref`는 과거 command receipt라 수정하지 않는다.
pending correction/closure의 target은 자동 재지정하지 않아 잘못된 Map mutation을 막는다.

## ACL·backup·restore

M05는 detector, admin decision, reconciliation service를 분리한 executor role과 하나의
SECURITY DEFINER owner를 둔다. two-phase choreography는 `0230` graph/marker 검증 → **M05 role 전부
없음** 검증 → M05 role provisioning(새 NOLOGIN/NOINHERIT owner·detector·admin·service executor만,
object grant 없음) → `0231` evidence upgrade → `0232` delivery upgrade → M05 ownership/ACL/routine marker
repair/검증 순서다.
bootstrap boundary script, `postgres-role-bootstrap.sh`, fresh integration helper와 no-owner/no-privileges
restore repair가 같은 choreography와 partial-marker fail-loud를 공유한다. role 일부, M05 relation 일부,
routine 일부는 어느 phase에서도 허용하지 않는다. pre-0226 frozen graph는 건드리지 않는다. runtime
catalog preflight는 API/Dagster가 네 evidence relation과 lease에 raw SELECT/DML을 못 함, PUBLIC
EXECUTE가 없음, intended procedure만 EXECUTE 가능함을 모두 검증한다.

backup manifest schema version을 v3로 올리고 기존 M01~M04 roots에 case/resolution/event/ack/subscription
canonical JSONL count+SHA-256 roots(안정 PK: case, resolution, event sequence, ack event/principal,
subscription principal)와 event envelope/hash를 더해 동일 application snapshot에서 캡처한다. lease만
immutable evidence root 밖의 mutable operational state다. restore는 no-owner/no-privileges 뒤 M05 ownership/ACL/procedure repair
→ catalog preflight → v3 evidence root 재계산 → 모든 live lease holder/expiry 무효화 → subscription
별 immutable ack의 연속 prefix에서 `acked_through` 재구축 순서로 검증해야 한다. 불연속 ack 또는
event/hash 불일치는 fail-loud다. evidence FK는 모두 `ON DELETE RESTRICT`이고 cascade delete를 막는다.
origin/claim 같은 쌍을 FK로 쓸 때는 정확한 composite UNIQUE를 먼저 마련하고, provider evidence는
mutable current-head FK 대신 immutable entity/source record/raw hash와 당시 head snapshot을 보존한다.
M05 case가 있는 provider Feature/source record의 hard purge도 거절한다.

## paired rollout과 검증

1. Map migration/ACL/API/admin UI와 service OpenAPI를 release하되 decision flag는 off로 둔다.
2. PinVi가 exact service spec을 vendor하고 local receipt migration/worker/UI impact projection을
   release한다. raw token/digest는 consumer runtime 전용 경계를 유지한다.
3. isolated Map+PinVi stack에서 M04 manual request → provider candidate → admin decision →
   PinVi rebind/detach → Map ack의 전 과정을 실행한다. 기존 shared/prod service 또는 mock은
   completion 근거가 될 수 없다.
4. 두 전문 적대 리뷰, Map/PinVi CI, fresh upgrade, restore drill, ACL negative test, replay/crash
   injection, event sequence commit-order race, multi-worker lease/contiguous ACK race, OpenAPI vendor
   byte proof가 모두 green일 때만 flag를 켠다. UI는 default `kept`, provider survivor 고정,
   destructive confirmation/reason, principal별 unacked age를 보여야 하며 generic dedup 화면을
   재사용하지 않는다. consumer blocked reason/attempt/impact는 consumer UI에서만 보인다; Map은
   consumer가 별도 generic report protocol을 도입하기 전까지 unacked age만 보여 completion으로
   오해하지 않는다.
