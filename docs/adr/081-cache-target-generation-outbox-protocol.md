# ADR-081: cache target generation과 pull outbox 전파

- **상태**: accepted
- **날짜**: 2026-07-31
- **결정자**: 사용자 + Codex
- **출처**: ADR-074, `T-VN-41A/B/C`, `T-VN-41S`(#922, 2026-08-18 보강)

## 컨텍스트

현재 cache target은 `(external_system, target_key)` active identity, `lock_version` ETag,
target-feature link와 refresh 결과를 갖지만 외부 정본의 순서를 보존하지 않는다. soft delete 뒤 같은
자연키를 새 UUID로 만들 수 있으므로 target row에 generation 한 칼럼만 추가하면 지연된 delete/upsert가
복구 뒤 상태를 되살릴 수 있다. `ops.feature_update_requests.generation`은 worker queue CAS이고
`poi_cache_targets.lock_version`은 HTTP resource CAS라 외부 source 순서로 재사용할 수도 없다.

PinVi는 별도 DB와 별도 배포 단위다. 두 서비스의 write를 한 transaction으로 묶거나 Map critical
write가 원격 응답을 기다리게 하면 dual-write와 장애 전파가 생긴다. 반대로 live revision 신호나
best-effort callback은 누락·중복·복구 epoch 전환을 재구성하지 못한다.

## 결정

`external_system`과 `target_key`는 trim/길이 조건뿐 아니라 Unicode NFC canonical form을 물리 DB
CHECK와 repository/API 경계에서 강제한다. NFC-equivalent 문자열을 서로 다른 자연키로 저장한 뒤 Merkle
leaf에서 같은 identity로 축약하는 상태는 허용하지 않는다. non-NFC service path는 source write 전에
`422 VALIDATION_ERROR`로 거부한다. source와 `cache_target_keys` refresh scope의 `target_key`는 동일한
512자 상한을 사용하고, 물리 feature-update scope validator도 trim/NFC/길이를 재검증한다.

### 1. 서로 다른 네 단조값

| 값 | 소유자와 의미 |
|---|---|
| `feature_update_requests.generation` | Map queue worker의 내부 CAS. 외부 event 순서나 ETag가 아니다. |
| `poi_cache_targets.lock_version` | Map target resource strong ETag. admin 및 service 조건부 write의 기준이다. |
| `restore_epoch BIGINT` | Map stream control이 소유하는 양의 복구 세대. restore fence가 현재 값에 1을 더한다. |
| `source_generation BIGINT` | PinVi desired-state transaction이 만든 양의 target 세대. target 자연키별 단조 비교한다. |
| `target_sequence BIGINT` | 같은 `(restore_epoch, source_generation, target)`에 속한 Map 결과 event의 순서다. |

event 의미 순서는 target partition의
`(restore_epoch, source_generation, target_sequence)`다. global sequence에서 unique하게 배정한
`relay_order`와 opaque cursor는 external system별 delivery prefix와 paging에만 쓰며 상태 신선도나
서로 다른 stream의 commit 순서 판단에 사용하지 않는다.

### 2. source head와 불변 이력

Map DB는 다음 정규화 상태를 둔다.

- stream control/epoch 이력: `external_system`별 현재 epoch, fence 상태, ETag revision, barrier receipt.
- source head: `(external_system, target_key)`별 마지막 epoch/generation, target UUID 또는 durable
  tombstone, 마지막 source event/command.
- source event ledger: producer `event_id`, Idempotency-Key command UUID, operation, 자연키, epoch,
  generation, canonical request fingerprint, 적용 target UUID와 당시 `lock_version`을 불변 보존한다.
- refresh membership: request가 시작할 때 target UUID와 epoch/generation을 캡처해 늦은 job 결과가
  새 target 세대의 결과로 가장하지 못하게 한다.

같은 event/key/body는 최초 결과를 replay한다. 같은 event 또는 Idempotency-Key의 다른 body는
`409`다. 낮은 generation과 과거 epoch는 projection을 바꾸지 않는다. active target row가 삭제·재생성돼도
head/tombstone은 남아 stale resurrection을 차단한다. 기존 target에는 가짜 epoch 0을 백필하지 않고 첫
권위 snapshot이 identity를 채택한다.
PUT/DELETE replay의 strong ETag는 mutable target row의 현재 version이 아니라 source event ledger에
고정된 apply 시점 `target_id + target_lock_version`으로 복원한다. 따라서 tombstone row가 사후 UPDATE돼도
최초 DELETE receipt가 변하지 않는다.

### 3. restore fence

`GET /v1/service/cache-target-streams/{external_system}`은 stream control과 raw strong ETag를
반환한다. `POST .../restore-fences`는 ServiceToken, principal에 결박된 `consumer_id`, UUID
`Idempotency-Key`, 직전 `If-Match`, `expected_restore_epoch`, 사유를 요구한다.

한 Map transaction 안에서 replay claim, control row CAS, epoch `N+1`, 기존 claim 무효화,
barrier event/receipt를 함께 commit한다. 신규 성공은 `201`, exact replay는 `200`, `If-Match`
누락은 `428`, stale ETag는 `412`, key/body 또는 expected epoch 불일치는 `409` RFC 7807이다.
이미 더 높은 epoch가 있으면 새로 증가시키지 않고 최신 control과 full snapshot reconcile을 사용한다.

epoch `N+1` 전이는 같은 transaction에서 epoch `N+1`보다 낮은 모든 non-delivered delivery
(`pending|retry|leased|dead`)를 terminal `superseded`로 종결한다. 기존 `delivered`는 소비자 적용
receipt이므로 보존한다. supersession은 lease binding을 제거하고 `superseded_at`과 단조
`delivery_version`을 기록하며 fence receipt의 `superseded_delivery_count`에 개수를 고정한다. exact
fence replay는 이 전이를 다시 실행하거나 delivery version을 올리지 않는다. 구 epoch dead letter도
새 epoch에서 복구할 대상이 아니므로 DLQ/replay와 ready 전이의 dead 집계에서 제외한다.

같은 fence transaction은 해당 stream의 active `preparing|running` reconciliation을 terminal
`superseded`로 바꾸고 `phase_version`을 1 올리며 `completed_at`과
`error_code='restore_fenced'`를 기록한다. preparing 출발은 snapshot/root가 계속 `NULL`이고 running
출발은 seal된 snapshot/expected root를 audit로 보존하되 actual root는 `NULL`이다. stream별 active
request는 partial unique index로 최대 하나이며, supersession 뒤 snapshot/seal/completion은
`reconciliation_superseded`로 거부되고 새 epoch begin은 즉시 가능하다. fence receipt는
`invalidated_claim_count`, `superseded_delivery_count`, `superseded_reconciliation_count`,
`superseded_reconciliation_request_id`를 저장한다. service 응답과 exact replay는 이 최초 receipt와
epoch/control/phase version을 그대로 반환하며 terminal 전이를 다시 실행하지 않는다.
DB CHECK와 HTTP DTO는 모두 `superseded_reconciliation_count == 0` iff request ID가 `NULL`,
count가 `1` iff request ID가 UUID인 상관 불변식을 강제한다. OpenAPI 3.1도 object-level
`oneOf`의 `0/null`, `1/format: uuid` 두 branch로 이 관계를 기계 계약화한다.
reconciliation은 `(external_system, request_id)` unique key도 제공하고 fence의
`(external_system, superseded_reconciliation_request_id)`는 이 key를 composite FK로 참조한다.
따라서 전역 UUID가 우연히 유효해도 다른 stream의 reconciliation을 fence receipt로 기록할 수 없다.
request ID가 `NULL`인 receipt는 PostgreSQL `MATCH SIMPLE`과 앞의 count/UUID CHECK를 조합해
`0/null`일 때만 허용한다. referenced reconciliation의 `external_system`을 사후 변경해 fence와
stream 소속을 갈라놓는 update도 같은 FK가 거부한다.
ops recovery operation status 계약에도 `superseded`를 strict enum으로 포함해 consumer가 terminal
대체를 자유 문자열 fallback 없이 판별한다. operation receipt의 `operation_id`도 UUID로 고정해
다른 식별자 namespace나 임의 문자열이 recovery 인과관계에 들어오는 것을 거부한다.

PinVi restore는 restored writer를 열기 전에 이 command를 호출한다. Map 자체 restore/cutover CLI도
복원 payload를 외부에 노출하기 전에 같은 domain 함수를 호출한다. 별도 SQL이나 process-local epoch
생성은 금지한다.

### 4. transactional result outbox

target 적용/삭제, link snapshot 교체, refresh request 상태 전이와 그 결과 event는 같은 Map DB
transaction에서 commit/rollback한다. `ops.ops_live_topic_revisions`는 UI invalidation 신호일 뿐
outbox로 재사용하지 않는다.

outbox event 필수 envelope는 다음과 같다.

```text
event_id, event_type, event_scope, external_system, target_key?, target_id?,
restore_epoch, source_generation, target_sequence, relay_order,
source_payload_fingerprint, occurred_at, typed payload
```

`event_scope='target'`인 state/link/refresh 세 event는 `target_key`, historical
`target_id`, `source_generation`, `target_sequence`를 모두 가진다. tombstone도 outbox
이력에서는 삭제 전 target UUID를 보존하되 source head의 current target UUID는 `NULL`이다.
`cache_target.reconciled`만 `event_scope='stream'`이며 네 target tuple 필드는 모두 `NULL`이다.
빈 snapshot과 tombstone-only snapshot에도 fake target을 만들지 않고 stream event 하나를
기록하며, 이때 `source_payload_fingerprint`는 비교를 통과한 snapshot Merkle root다.
이 event의 typed payload는 추가 필드 없이 아래 여섯 필드를 exact contract로 사용한다.

```text
request_id, snapshot_id, actual_merkle_root, expected_merkle_root, status, version
```

`request_id`는 completion이 terminal 처리한 reconciliation request UUID이고 `snapshot_id`는 그
request에 seal된 fixed snapshot UUID다. 두 root가 같은 성공 receipt만 발행하므로
`source_payload_fingerprint == expected_merkle_root == actual_merkle_root`다. `status`는
`succeeded`, `version`은 `cache-target-reconciliation-v1`이다. 따라서 consumer는 event가 어느
request와 fixed snapshot의 terminal receipt인지 payload만으로도 exact 결박할 수 있다.

`event_type`은 다음 네 값만 허용한다.

- `cache_target.state_applied`
- `cache_target.links_reconciled`
- `refresh_request.status_changed`
- `cache_target.reconciled`

outbox event는 불변이고 target/source event/refresh request/job/domain command identity를 FK 또는
typed nullable linkage로 보존한다. delivery state와 claim/ack 이력은 별도 mutable table이 소유한다.

### 5. ServiceToken pull relay

PinVi에 callback을 push하지 않는다. principal에 결박된 단일 `consumer_id`가
`POST /v1/service/cache-target-event-claims`로 external system별 단일 전역 stream을 pull한다.
claim은 due/retry/만료 lease를 `FOR UPDATE SKIP LOCKED`로 bounded 획득한다. 같은 stream에는 active
claim 하나만 허용하고, 현재 stream `restore_epoch`의 더 낮은 nonterminal `relay_order`를 건너뛰지
않는다. terminal `delivered|superseded`와 과거 epoch event는 claim 대상이 아니다.

PinVi는 event inbox dedupe와 target tuple CAS, DB cache generation, consumer checkpoint를 한
transaction에 commit한 뒤에만 `POST /v1/service/cache-target-event-acks`를 호출한다. ACK의
`through_cursor`는 claim의 `external_system` 안에서 contiguous한 `relay_order` prefix다. 번호는 global
sequence에서 배정되어 전역 unique지만 서로 다른 stream 사이의 commit 순서를 뜻하지 않는다. target tuple은 semantic
precedence에만 사용한다. consumer DB commit 뒤 ACK 전에 죽으면 같은 `event_id`가 재전달되며 side
effect는 0회 추가다.

`POST /v1/service/cache-target-event-nacks`는 transient 실패를 즉시 lease 해제+bounded backoff로,
permanent 또는 최대 attempt 실패를 dead letter+stream block으로 전이한다. 이 전이는 claim의 첫
미ACK event에만 허용하며, 중간 poison event 앞의 contiguous prefix는 먼저 ACK해야 한다. 그렇지
않으면 mutation 없이 `409 dead_letter_requires_prefix_ack`다. blocked event 뒤 순서는 ACK할 수
없다. service dead-letter GET과 Idempotency-Key+If-Match replay는 같은
`event_id/relay_order/semantic tuple/fingerprint`만 재활성화한다. snapshot checksum이 다시 맞기 전에는
consumer를 ready로 바꾸지 않는다. `superseded` event는 dead-letter GET/list에 나타나지 않으며 replay
요청은 `dead_letter_not_found`로 실패한다.

### 6. fixed snapshot과 Merkle v1

`GET /v1/service/cache-target-snapshots/{external_system}`은 page 전체에서 같은
`snapshot_id`, `restore_epoch`, `high_watermark_cursor`, `count`, `merkle_root`를 유지하는 MVCC
snapshot이다. active와 tombstone을 모두 포함한다. leaf row는 다음 다섯 필드만 가진다.
첫 page는 stream control, outbox high-watermark와 모든 source head를 단일 PostgreSQL statement의
MVCC view로 읽어 immutable header/item에 고정한다. 후속 page는 같은 snapshot item만 읽으므로
중간에 새 source write가 commit돼도 count/root/page membership은 바뀌지 않는다.

일반 snapshot의 첫 page는 header/item 저장과 HTTP 성공 응답을 route 소유 transaction 하나로
묶는다. commit이 실패하거나 응답 DTO 검증이 실패하면 snapshot 전체를 rollback하며, commit되지 않은
UUID를 성공 응답으로 내보내지 않는다. 응답은 `created_at`과 `expires_at`을 포함해 cursor 수명을
숨기지 않는다. 같은 external system의 동시 생성은 transaction advisory try-lock으로 single-flight하며,
경합 요청은 대기열을 만들지 않고 `503 snapshot_busy`와 `Retry-After`를 받는다.

모든 source head material 변경은 같은 transaction의 `cache_target.state_applied` outbox relay order를
전진한다. link/refresh 및 stream-scope `cache_target.reconciled` event는 snapshot leaf 밖의 상태만
바꾸므로 material version을 전진시키지 않는다.
재사용 identity는 `(restore_epoch, material_high_watermark_relay_order)`이며 partial index
`(external_system, relay_order DESC) WHERE event_type='cache_target.state_applied'`로 조회한다. snapshot의
내부 header에 capture 당시 material watermark를 global cursor와 별도 저장하고, 현재 material watermark와
exact equality이며 75분보다 긴 수명이 남을 때만 full head 재주사 없이 재사용한다.

snapshot transaction은 advisory single-flight 획득 뒤 **별도 SQL statement**로 stream row `FOR SHARE`
barrier를 먼저 완료한다. 기존 outbox writer가 끝날 때까지 기다리고 transaction 끝까지 새 writer를
막은 뒤, 후속 statement에서 identity/reuse/head를 읽는다. 단일 READ COMMITTED statement에서 lock wait와
subquery를 섞어 pre-wait MVCC head에 post-wait cursor를 결합하지 않는다. `state_applied`, link/refresh,
`cache_target.reconciled`를 포함한 모든 outbox writer transaction은 head/target/link를 읽거나 잠그기
전에 같은 stream row를 `FOR UPDATE`로 잠그며, 잠금 순서는 항상 stream → head/target/link이다.
여러 system을 다루면 `external_system` 정렬 순서로 stream을 먼저 모두 잠근다. 따라서 각
`external_system`의 `high_watermark_cursor`는 같은 stream에서 늦게 commit되는 더 낮은 relay order를
추월하지 않는 commit-safe contiguous prefix다. DB `BEFORE INSERT` trigger가 stream lock을 재확인한
**뒤** 명시적 global sequence에서
`relay_order`를 배정하며, column default/Identity가 trigger보다 먼저 번호를 소비하게 두지 않는다.
application의 사전 stream lock은 trigger가 head/target lock 뒤 stream을 기다리는 역순 교착을 막고,
trigger는 raw SQL이나 미래 writer도 allocation-before-lock 계약을 우회하지 못하게 한다.
barrier 전에 transaction-local `lock_timeout=5s`, `statement_timeout=5min`을 설정한다. hung writer 때문에
기한을 넘기면 advisory single-flight를 해제하고 `503 snapshot_barrier_timeout + Retry-After: 1`로
fail-close한다.
barrier 이후 capture/item persist statement가 5분을 넘기면 별도
`503 snapshot_build_timeout + Retry-After: 1`로 rollback해 lock wait와 build 병목을 구분한다.

`high_watermark_cursor`는 snapshot 생성 시 고정한 external-system-scoped relay prefix다. 재사용 뒤에는 현재 outbox의
exact max가 아니라 안전한 replay lower-bound일 수 있고 절대 상향 수정하지 않는다. consumer는 이
cursor 뒤 event를 모두 다시 읽고 immutable inbox receipt로 중복 제거한다. fresh/reuse 모두 응답 DTO
구성 전 DB clock으로 75분의 server handoff floor를 검사하며 부족하면 `503 snapshot_ttl_too_short`와
`Retry-After: 1`로 실패한다. PinVi는 실제 수신 시 다시 60분 이상을 요구한다. 이 15분 margin은
commit·serialization·network 지연을 흡수하며, 새 snapshot TTL은 2시간이다.

single-flight 안에서 reuse가 실패하면 같은 system의 미만료·미참조 generic snapshot 수를 센다. 두 개가
이미 있으면 세 번째 full copy를 만들지 않고 가장 오래된 expiry까지의 DB-clock 초를
`429 snapshot_capacity_exceeded`와 `Retry-After`로 반환한다. 유효 cursor를 조기 삭제하지 않으면서
generic live storage를 최대 `2 × stream cardinality`로 제한한다. reconciliation이 참조하는 snapshot은
이 admission count에서 제외한다.

T-VN-41S(#922)는 capture를 PostgreSQL server cursor로 두 번 순회한다. 첫 scan은 level stack만 가진
Merkle v1 accumulator로 count/root/canonical material bytes를 `O(log N)` 메모리에서 계산한다. item
1,000,000개 또는 512 MiB를 넘으면 header INSERT 전에 각각
`413 snapshot_item_limit_exceeded`, `413 snapshot_byte_limit_exceeded`로 fail-close한다. 두 번째 scan은
1,000행 batch INSERT와 첫 응답 page만 보관하고 count/byte/root를 첫 scan과 재대조한다. 두 scan은 같은
transaction의 stream share barrier 안에 있어 source membership이 고정되며 불일치는 전체 rollback한다.

reconciliation seal은 exact material identity이고 75분 넘게 남은 generic 또는 이미 request가 참조하는 snapshot이
있으면 같은 header/item을 재사용한다. 만료·미참조 snapshot은 GC가 일부 item을 지웠을 수 있어
재사용하지 않는다. generic/reconciliation별 독립 receipt가 같은 material을 양방향 공유하고 terminal
item을 compact하는 정규화 스키마는 T-VN-40C 예약 revision `0224` 뒤의 `0225+` migration으로 제한한다.
그 전에는 revision 번호 없는 설계 초안만 유지한다. 만료된 일반 snapshot은
reconciliation request가 참조하지 않을 때만 item 1,000행/header 100행 이하의 `SKIP LOCKED` 배치로
정리한다. page reader의 header share lock은 GC가 빈 반복 page를 만드는 race를 막는다. terminal request가
참조하는 snapshot도 checksum 감사 영수증이므로 보존한다.

foreground GC는 요청 transaction의 부수 정리일 뿐 retention 정본이 아니다. hourly
`cache_target_snapshot_gc`는 별도 physical connection의 session advisory try-lock으로 중복 실행을 즉시
skip하고 external system을 keyset round-robin하며 batch마다 새 transaction을 commit한다. 기본 예산은
1,000 item × 2,000 batch, 최대 3,300초, statement timeout 30초다. 한 full round 동안 진척이 없으면
busy-loop 대신 종료한다. 2,000,000 item은 실행당 설정 상한이지 실측 처리량 보장이 아니다. exact
remaining count와 total/unexpired-generic/referenced header·item count는 종료 시 한 번만 관측하고 mutex
skip에서는 unknown이다. backlog/observation retry는 경보 대상이며 기본 `STOPPED` schedule은 consumer
production enable 전에 켜고 n150 처리량을 확인한다.

같은 종료 관측은 snapshot header/item relation의 table/TOAST bytes, index bytes, dead tuple 추정치와
두 relation 중 가장 긴 최근 vacuum lag도 기록한다. 한 relation이라도 vacuum/autovacuum 이력이 없으면
lag를 추정하지 않고 관측 품질 경고를 낸다. Dagster ceiling 초과는 exact reason과 warning을 남기되
성공한 GC를 retry 실패로 바꾸지 않는다.

초기 cutover는 service recovery principal의 `begin → writer backfill → seal` 두 단계로 고정한다.
begin은 stream을 fenced 상태로 만들고 active claim을 끊지만 snapshot을 만들지 않는 `preparing`
reconciliation request만 남긴다. seal은 PinVi가 계산한 expected epoch/count/Merkle root를 body로 받아
같은 transaction에서 Map source heads를 fixed snapshot으로 캡처하고 비교한다. 비교가 맞을 때만
snapshot을 저장하고 request를 `running`으로 전환하며, mismatch는 snapshot 저장과 phase 전이를 모두
rollback한 `412`다. begin 요청의 precondition은 stream control ETag 또는 stream 없음
`If-None-Match: *`이고, begin/seal 응답과 seal `If-Match`는 reconciliation request
`request_id:phase_version` ETag를 사용한다. begin/seal은 모두 UUID `Idempotency-Key`와 precondition
header를 domain ledger에 포함해 exact response replay와 changed-body `409`를 보장한다.
restore fence가 active request를 대체하면 request는 terminal `superseded`가 되며, 구 request의
snapshot 조회·seal·completion으로 새 epoch stream을 다시 열 수 없다.

```text
(external_system, target_key, state, source_generation, source_payload_fingerprint)
```

Map 소유 `target_id`, ETag, `target_sequence`는 leaf에서 제외한다. text는 UTF-8 NFC unsigned byte
lexicographic 순서로 정렬한다. raw JSON이나 float 표기를 hash하지 않고 versioned typed
`cache-target-source-v1` serializer를 사용한다.

`cache-target-source-v1`의 active canonical JSON은 정렬 key·compact separator를 사용한 다음 exact
shape다. 좌표는 0.000001도, 반경은 0.001 km에서 `ROUND_HALF_EVEN`한 뒤 각각 정수
`lon_e6`/`lat_e6`와 metre `radius_m`로 직렬화한다. 입력 float는 거절하고 Decimal·정수·10진 문자열만
허용한다. tombstone은 payload를 재사용하지 않고 아래 deleted shape로 고정한다.

```json
{"coord":{"lat_e6":37566500,"lon_e6":126978000},"radius_m":5000,"state":"active","update_enabled":true,"version":"cache-target-source-v1"}
{"state":"deleted","version":"cache-target-source-v1"}
```

`source_payload_fingerprint`는 위 canonical UTF-8 bytes의 lowercase SHA-256 hex다. 양쪽 독립 구현의
정본 vector는 `contracts/cache-target-source-v1-golden.json`이다.

```text
leaf  = SHA256("KTMCTLEAF\0" || u32be(len(system)) || system
               || u32be(len(key)) || key || state_u8
               || u64be(source_generation) || fingerprint_raw32)
node  = SHA256("KTMCTNODE\0" || left32 || right32)
empty = SHA256("KTMCTEMPTY\0")
```

`state_u8`은 active=1, deleted=2다. 홀수 node는 hash를 복제하지 않고 다음 level로 그대로 승격한다.
Map과 PinVi는 같은 golden vector를 실행하고 pinned service OpenAPI와 함께 drift를 차단한다.

### 7. REST와 운영 경계

PinVi는 admin route나 AdminBFF credential을 사용하지 않는다. service 표면은 다음과 같다.

- `PUT|GET|DELETE /v1/service/cache-targets/{external_system}/{target_key}`
- `POST /v1/service/refresh-requests`, `GET /v1/service/refresh-requests/{request_id}`
- stream control/restore fence, claim/ack/nack, dead-letter/replay, fixed snapshot resource
- stream control의 active reconciliation descriptor와
  `GET /v1/service/cache-target-reconciliations/{request_id}/snapshot`
- `POST /v1/service/cache-target-reconciliations/{request_id}/completions`

target create는 `If-None-Match: *`, update/delete는 앞서 받은 raw strong `If-Match`와 UUID
Idempotency-Key를 보낸다. `412`에서 최신 ETag로 자동 rebase하지 않고 snapshot reconcile 뒤 새 명시적
command를 만든다. 비동기 refresh는 `202`, `Location`, bounded `Retry-After`를 반환한다. write route는
T-VN-12 정적 registry에서 generic DB command, 기존 refresh ledger, outbox lifecycle ledger 중 정확히
하나로 분류한다.

operator는 ops read에서 epoch/claim/backlog/dead/reconciliation 상태를 보고, admin 표면에서 replay와
reconciliation command를 실행한다. ServiceToken registry의 한 binding은 canonical
`(consumer_id, sorted external_systems)`로 식별하고 다음 네 exact 역할 principal을 각각 정확히 하나씩
가진다. scope 비교는 순서가 아니라 집합 동등성이다.

| 호출 역할 | exact scope 집합 |
|---|---|
| command | `{cache-target:command}` |
| consumer | `{cache-target:read, cache-target:claim, cache-target:ack, cache-target:nack, cache-target:snapshot}` |
| restore | `{cache-target:restore-fence}` |
| recovery | `{cache-target:recovery, cache-target:recovery-replay}` |

서로 겹치지 않는 complete binding 여러 개는 서로 다른 `consumer_id`에만 허용한다. 한 `consumer_id`는
전역에서 정확히 한 canonical sorted external-system tuple만 소유하며, 여러 system을 소비하면 분할
binding이 아니라 한 sorted union binding으로 표현한다. external system 하나도 전역에서 한 binding만
소유한다. token digest와 `principal_id`도 전역 unique다. 역할 누락·중복, mixed/partial/extra scope,
비정렬 allowlist, external system 중복 소유는 설정 검증에서 기동을 막는다. 역할 token digest는 설정된
admin proxy/service/ops/metrics/cursor secret과 public VWorld/API key 원문의 SHA-256과도 달라야 한다.
local-dev의 미설정 cursor process fallback은 비교 대상이 아니다. 이 consumer 단일 소유권 때문에 body에
external system이 없는 ACK도 다른 binding의 claim을 같은 consumer identity로 제거할 수 없다. NACK처럼
system이 있는 mutation은 consumer와 system을 모두 검사한다.

기존 `cache-target:consumer`는 read/claim/ack/nack/snapshot의 호환 umbrella로 남기지 않고
enum·validator·인증 fallback에서 clean cut 제거한다. command principal도 consumer·snapshot·recovery
경로를 호출할 수 없다. 따라서 PinVi writer와 relay consumer는 서로 다른 최소 권한 token을 사용한다.
command writer가 PUT/DELETE CAS를 위해 source를 다시 읽거나 refresh `Location`을 polling할 때는 command
credential을 계속 쓰지 않고 consumer credential로 전환한다. admin reconciliation 시작은 active claim을
끊는 복구 mutation이므로 destructive recovery gate가 켜진 경우에만 허용한다.

각 service operation은 OpenAPI의 `x-required-service-scope`로 다음 계약을 기계 판독 가능하게 노출한다.
runtime도 같은 단일 inventory의 exact scope를 사용하며 모든 다른 역할 token은 metadata/domain service를
호출하기 전에 `403`이어야 한다. request-bound seal/completion/snapshot은 scope-only 검사를 먼저 하고,
통과한 경우에만 reconciliation metadata를 읽은 뒤 consumer와 external system 결박을 다시 검사한다.

| method/path | scope | 호출 역할 |
|---|---|---|
| `PUT /v1/service/cache-targets/{external_system}/{target_key}` | `cache-target:command` | command |
| `GET /v1/service/cache-targets/{external_system}/{target_key}` | `cache-target:read` | consumer |
| `DELETE /v1/service/cache-targets/{external_system}/{target_key}` | `cache-target:command` | command |
| `GET /v1/service/cache-target-streams/{external_system}` | `cache-target:read` | consumer |
| `POST /v1/service/cache-target-streams/{external_system}/restore-fences` | `cache-target:restore-fence` | restore |
| `POST /v1/service/refresh-requests` | `cache-target:command` | command |
| `GET /v1/service/refresh-requests/{request_id}` | `cache-target:read` | consumer |
| `POST /v1/service/cache-target-event-claims` | `cache-target:claim` | consumer |
| `POST /v1/service/cache-target-event-acks` | `cache-target:ack` | consumer |
| `POST /v1/service/cache-target-event-nacks` | `cache-target:nack` | consumer |
| `GET /v1/service/cache-target-event-dead-letters/{event_id}` | `cache-target:recovery-replay` | recovery |
| `POST /v1/service/cache-target-event-dead-letters/{event_id}/replays` | `cache-target:recovery-replay` | recovery |
| `POST /v1/service/cache-target-reconciliations` | `cache-target:recovery` | recovery |
| `POST /v1/service/cache-target-reconciliations/{request_id}/seals` | `cache-target:recovery` | recovery |
| `POST /v1/service/cache-target-reconciliations/{request_id}/completions` | `cache-target:snapshot` | consumer |
| `GET /v1/service/cache-target-snapshots/{external_system}` | `cache-target:snapshot` | consumer |
| `GET /v1/service/cache-target-reconciliations/{request_id}/snapshot` | `cache-target:snapshot` | consumer |

reconciliation command는 active claim을 무효화하고 stream을 먼저 halt한 뒤 fixed snapshot을 만든다.
stream control read는 현재 active reconciliation의 request ID와 request에 결박된 fixed snapshot
identity/epoch/count/root/high-watermark를 nullable descriptor로 노출한다. consumer는 그 request ID의
snapshot read만 page하며 일반 snapshot 첫 page를 다시 생성해 completion 근거로 대체할 수 없다.
consumer는 `cache-target:snapshot` principal로 request ID와 external system/consumer ID/snapshot
ID/expected epoch/actual Merkle root를 exact 결박한 completion receipt를 제출한다. UUID
`Idempotency-Key`는 terminal 응답을 재생한다. receipt의 root가 snapshot root와 정확히 같고 epoch이
그대로이며 dead-letter가 0일 때만 `ready`/enabled로 전이하고 stream-scoped
`cache_target.reconciled` event를 같은 transaction에 기록한다. checksum 불일치는 failed receipt를
남기고 fenced/disabled 상태를 유지한다. terminal request에 다른 checksum을 재사용해서 resume할 수
없다. 성공 event는 request UUID와 seal된 snapshot UUID를 payload에 함께 싣고, expected root를
`source_payload_fingerprint`에도 동일하게 기록한다.

one-step admin reconciliation의 operation receipt와 이후 operation 조회는 request에 seal된
`snapshot_id`를 반환한다. live 검증은 요청 전 설정 snapshot이 아니라 이 receipt의 UUID를 기준으로
최종 stream `last_snapshot.snapshot_id`가 같은지 확인한다. service begin처럼 아직 snapshot을 만들지
않은 `preparing` operation에서는 `snapshot_id`가 `null`이다.

### 8. 활성화

Map foundation과 PinVi paired consumer가 모두 merge되기 전에는 relay consumer를 켜지 않는다.
PinVi는 기본 off이며 credential, principal scope, pinned OpenAPI SHA, active epoch, full snapshot,
Merkle/count/high-watermark 일치 중 하나라도 없으면 fail-closed한다. consumer 배포 → contract pin →
restore clone/snapshot backfill → checksum 일치 → consumer enable → duplicate/gap/epoch live → soak 순서다.
production enable 전 PinVi는 snapshot 요청 동시성을 system별 1로 제한하고 `429/503`의
`Retry-After`를 지키며, `413 snapshot_item_limit_exceeded`를 자동 재시도하지 않음을 live로 증명한다.
credential별 gateway limit 또는 동등한 외부 rate-limit과 실제 호출 cadence도 함께 기록한다. 이 gate가
없으면 100,001행 sentinel scan을 반복할 수 있으므로 consumer를 enable하지 않는다.

`cache-target:command`의 exact 분리는 서버 간 인증 의미가 바뀌는 breaking contract다. OpenAPI의
security scheme 형태가 그대로여도 generation 6 pin을 재사용하지 않는다. Map service OpenAPI를 다시
export하고 그 SHA를 PinVi에 pin한 조합부터 **contract generation 7**로 기록한다. generation 7은 command
token이 source PUT/DELETE·refresh create만 성공하고 consumer/restore/recovery 경로는 `403`, consumer
exact scope가 command 경로는 `403`, 제거된 `cache-target:consumer` 설정은 validation error임을 contract
test로 증명해야 한다.

## 근거

자연키 head와 tombstone은 projection row 수명과 source 순서를 분리한다. transaction-coupled outbox와
pull/ack는 critical write latency에서 네트워크를 제거하면서 at-least-once 복구를 가능하게 한다. Map이
restore epoch를 소유하면 restored producer payload가 epoch를 되감을 수 없고, fixed snapshot과 Merkle은
두 DB를 직접 연결하지 않고도 누락·중복을 증명한다.

## 결과

- **긍정**: target/link/update와 event 사이 dual-write가 사라지고 restore 뒤 stale resurrection을 막는다.
- **긍정**: consumer 장애와 poison event가 critical write를 막지 않으면서 운영자가 재현·재생할 수 있다.
- **부정**: source/head/event/outbox/delivery/snapshot 상태와 두 저장소 golden vector 운영이 추가된다.
- **부정**: strict stream prefix는 poison event 해결 전 같은 stream 후속 전파를 의도적으로 멈춘다.
- **전환**: Map PR은 producer foundation일 뿐 `T-VN-41C` 완료가 아니다. PinVi paired PR, contract pin,
  n150 isolated live 증명 전까지 `T-VN-41A/B/C`는 open으로 유지한다.

## 기존 결정과의 관계

ADR-074의 source generation, restore epoch, transactional outbox 결정을 구체화한다. ADR-065의 admin
ETag 계약은 유지하되, 과거의 “PinVi service write 금지”는 ServiceToken 전용 vNext resource에 한해
본 ADR이 supersede한다. admin 권한을 PinVi에 주지 않는 결정은 유지한다.
