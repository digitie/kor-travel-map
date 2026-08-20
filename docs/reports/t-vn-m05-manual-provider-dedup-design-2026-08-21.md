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

`0231_m05_manual_provider_dedup`는 아래 네 relation을 추가한다. 모든 evidence table은
append-only trigger와 `RESTRICT` FK를 갖고, raw table DML은 runtime login에서 거부한다.

| relation | 한 행의 의미 | 핵심 불변식 |
| --- | --- | --- |
| `ops.manual_provider_dedup_cases` | 특정 manual/provider Feature와 그때의 evidence fingerprint가 만든 한 episode | manual origin/claim, provider dataset/entity/current record/hash, 양 UUID·row revision, canonical snapshots, score components/version/distance를 생성 시점 값으로 보존한다. 같은 fingerprint만 idempotent다. |
| `ops.manual_provider_dedup_resolutions` | case의 유일한 terminal 판단 또는 detector의 `superseded` marker | case당 하나만 허용한다. admin 판단은 domain command FK·actor·reason이 필수이고 detector supersede만 command 없이 허용한다. |
| `ops.feature_reference_reconciliation_events` | merge/detach가 외부 참조에 요구하는 immutable action | resolution당 0 또는 1행이다. monotonic `event_sequence`, old feature pair, optional replacement pair, action, occurred-at를 고정한다. |
| `ops.feature_reference_reconciliation_acks` | service principal이 local receipt를 commit한 뒤 남기는 ack | `(event_id, principal_id)` unique이며 update/delete 불가다. ack command FK와 local receipt hash가 필수다. |

case fingerprint는 다음 canonical input의 SHA-256이다.

1. manual Feature `feature_id`/UUID/row revision와 immutable creation origin/command;
2. provider Feature `feature_id`/UUID/row revision, provider dataset, source entity/head/source
   record/raw payload hash;
3. 두 Feature의 canonical `{kind,name,category,coord}` snapshot;
4. scorer id `manual-provider-v1`, name/spatial/category/total score와 distance.

동일 fingerprint의 재탐지는 같은 pending case를 반환한다. row revision/source head/scorer가
바뀌면 detector는 종전 pending case에 `superseded` resolution을 append하고 새 case를 쓴다.
따라서 과거의 점수·근거·판단은 갱신되지 않는다.

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

| decision | Map mutation | event |
| --- | --- | --- |
| `kept` | 없음 | 없음 |
| `merged` | provider는 그대로, manual만 canonical retire transition | `rebind`: manual pair → provider pair |
| `manual_retired` | manual만 canonical retire transition | `detach`: manual pair, replacement 없음 |

generic merge procedure, source link/record 변경, provider Feature retire와 automatic survivor는 어느
branch에도 없다. merge와 retire는 admin destructive kill-switch와 `AdminBFF`를 함께 요구한다.

## service reconciliation contract

Map은 두 service endpoint를 추가한다.

| endpoint | 역할 | 인증/멱등성 |
| --- | --- | --- |
| `GET /v1/service/feature-reference-reconciliations` | 해당 principal이 아직 ack하지 않은 event를 `event_sequence` keyset 순서로 읽는다. | 전용 `feature-reference-reconciliation:read` token scope |
| `POST /v1/service/feature-reference-reconciliations/{event_id}/acks` | consumer의 이미 commit된 local receipt hash를 append-only ack로 기록한다. | 전용 `feature-reference-reconciliation:ack` scope + UUID `Idempotency-Key` |

event response는 `event_id`, `event_sequence`, case/resolution id, `rebind|detach`, old
`{feature_id, feature_uuid, row_revision}`, optional replacement pair, occurred-at을 가진다. Map은
consumer 이름을 event, role, route, settings 식별자에 넣지 않는다. service token principal만 ack
identity다.

ack는 event byte/hash·principal·receipt hash를 다시 확인해 exact replay만 허용한다. 소비자는
Map ack보다 먼저 자신의 transaction을 commit한다. ACK 직전 crash는 같은 event를 다시 받아 local
receipt의 payload hash를 검증한 뒤 재-ack할 수 있다.

## 첫 consumer의 durable 처리

PinVi는 이 generic service spec의 첫 consumer다. 새 local immutable receipt는 event payload hash와
Map event id/sequence를 PK로 보존하며, 한 transaction에서 다음을 수행한다.

1. old `{feature_id, feature_uuid}` pair가 정확히 같은 `trip_day_pois`와
   `curated_plan_pois`를 `FOR UPDATE`로 수집한다.
2. `rebind`는 두 column을 replacement pair로 함께 바꾼다. `detach`는 reference column을
   비우고 보존된 snapshot은 남긴다. 영향을 받은 row id/old/new pair/count root를 immutable
   impact rows에 보존한다.
3. partial pair, source pair 불일치, pending correction/closure target reference가 있으면 local
   commit과 Map ack를 하지 않는다. operator가 먼저 그 독립 workflow를 정리해야 한다.
4. local receipt와 impact root가 commit된 뒤에만 Map ack를 호출한다.

terminal `feature_suggestions.kor_travel_map_ref`는 과거 command receipt라 수정하지 않는다.
pending correction/closure의 target은 자동 재지정하지 않아 잘못된 Map mutation을 막는다.

## ACL·backup·restore

M05는 detector, admin decision, reconciliation service를 분리한 executor role과 하나의
SECURITY DEFINER owner를 둔다. bootstrap은 pre-0226 frozen graph를 건드리지 않고 0231 이후
phase에서 role membership·routine owner·cross-owner grants를 repair한다. runtime catalog
preflight는 API/Dagster가 네 evidence relation에 raw SELECT/DML을 못 함과 intended procedure만
EXECUTE 가능함을 모두 검증한다.

backup manifest schema version을 올리고 case/resolution/event/ack canonical JSONL count+SHA-256
roots를 동일 application snapshot에서 캡처한다. restore는 no-owner/no-privileges 뒤 ownership,
ACL, procedure preflight를 복구한 다음 네 root를 재계산해야 한다. evidence FK는 hard purge와
cascade delete를 막는다.

## paired rollout과 검증

1. Map migration/ACL/API/admin UI와 service OpenAPI를 release하되 decision flag는 off로 둔다.
2. PinVi가 exact service spec을 vendor하고 local receipt migration/worker/UI impact projection을
   release한다. raw token/digest는 consumer runtime 전용 경계를 유지한다.
3. isolated Map+PinVi stack에서 M04 manual request → provider candidate → admin decision →
   PinVi rebind/detach → Map ack의 전 과정을 실행한다. 기존 shared/prod service 또는 mock은
   completion 근거가 될 수 없다.
4. 두 전문 적대 리뷰, Map/PinVi CI, fresh upgrade, restore drill, ACL negative test, replay/crash
   injection, OpenAPI vendor byte proof가 모두 green일 때만 flag를 켠다.
