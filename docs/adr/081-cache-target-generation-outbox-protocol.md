# ADR-081: cache target generation과 pull outbox 전파

- **상태**: accepted
- **날짜**: 2026-07-31
- **결정자**: 사용자 + Codex
- **출처**: ADR-074, `T-VN-41A/B/C`

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

### 1. 서로 다른 네 단조값

| 값 | 소유자와 의미 |
|---|---|
| `feature_update_requests.generation` | Map queue worker의 내부 CAS. 외부 event 순서나 ETag가 아니다. |
| `poi_cache_targets.lock_version` | Map target resource strong ETag. admin 및 service 조건부 write의 기준이다. |
| `restore_epoch BIGINT` | Map stream control이 소유하는 양의 복구 세대. restore fence가 현재 값에 1을 더한다. |
| `source_generation BIGINT` | PinVi desired-state transaction이 만든 양의 target 세대. target 자연키별 단조 비교한다. |
| `target_sequence BIGINT` | 같은 `(restore_epoch, source_generation, target)`에 속한 Map 결과 event의 순서다. |

event 의미 순서는 target partition의
`(restore_epoch, source_generation, target_sequence)`다. 전역 `relay_order`와 opaque cursor는
delivery prefix와 paging에만 쓰며 상태 신선도 판단에 사용하지 않는다.

### 2. source head와 불변 이력

Map DB는 다음 정규화 상태를 둔다.

- stream control/epoch 이력: `external_system`별 현재 epoch, fence 상태, ETag revision, barrier receipt.
- source head: `(external_system, target_key)`별 마지막 epoch/generation, target UUID 또는 durable
  tombstone, 마지막 source event/command.
- source event ledger: producer `event_id`, Idempotency-Key command UUID, operation, 자연키, epoch,
  generation, canonical request fingerprint와 적용 결과를 불변 보존한다.
- refresh membership: request가 시작할 때 target UUID와 epoch/generation을 캡처해 늦은 job 결과가
  새 target 세대의 결과로 가장하지 못하게 한다.

같은 event/key/body는 최초 결과를 replay한다. 같은 event 또는 Idempotency-Key의 다른 body는
`409`다. 낮은 generation과 과거 epoch는 projection을 바꾸지 않는다. active target row가 삭제·재생성돼도
head/tombstone은 남아 stale resurrection을 차단한다. 기존 target에는 가짜 epoch 0을 백필하지 않고 첫
권위 snapshot이 identity를 채택한다.

### 3. restore fence

`GET /v1/service/cache-target-streams/{external_system}`은 stream control과 raw strong ETag를
반환한다. `POST .../restore-fences`는 ServiceToken, principal에 결박된 `consumer_id`, UUID
`Idempotency-Key`, 직전 `If-Match`, `expected_restore_epoch`, 사유를 요구한다.

한 Map transaction 안에서 replay claim, control row CAS, epoch `N+1`, 기존 claim 무효화,
barrier event/receipt를 함께 commit한다. 신규 성공은 `201`, exact replay는 `200`, `If-Match`
누락은 `428`, stale ETag는 `412`, key/body 또는 expected epoch 불일치는 `409` RFC 7807이다.
이미 더 높은 epoch가 있으면 새로 증가시키지 않고 최신 control과 full snapshot reconcile을 사용한다.

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
claim 하나만 허용하고, 더 낮은 nonterminal `relay_order`를 건너뛰지 않는다.

PinVi는 event inbox dedupe와 target tuple CAS, DB cache generation, consumer checkpoint를 한
transaction에 commit한 뒤에만 `POST /v1/service/cache-target-event-acks`를 호출한다. ACK의
`through_cursor`는 claim 안의 contiguous global `relay_order` prefix다. target tuple은 semantic
precedence에만 사용한다. consumer DB commit 뒤 ACK 전에 죽으면 같은 `event_id`가 재전달되며 side
effect는 0회 추가다.

`POST /v1/service/cache-target-event-nacks`는 transient 실패를 즉시 lease 해제+bounded backoff로,
permanent 또는 최대 attempt 실패를 dead letter+stream block으로 전이한다. 이 전이는 claim의 첫
미ACK event에만 허용하며, 중간 poison event 앞의 contiguous prefix는 먼저 ACK해야 한다. 그렇지
않으면 mutation 없이 `409 dead_letter_requires_prefix_ack`다. blocked event 뒤 순서는 ACK할 수
없다. service dead-letter GET과 Idempotency-Key+If-Match replay는 같은
`event_id/relay_order/semantic tuple/fingerprint`만 재활성화한다. snapshot checksum이 다시 맞기 전에는
consumer를 ready로 바꾸지 않는다.

### 6. fixed snapshot과 Merkle v1

`GET /v1/service/cache-target-snapshots/{external_system}`은 page 전체에서 같은
`snapshot_id`, `restore_epoch`, `high_watermark_cursor`, `count`, `merkle_root`를 유지하는 MVCC
snapshot이다. active와 tombstone을 모두 포함한다. leaf row는 다음 다섯 필드만 가진다.
첫 page는 stream control, outbox high-watermark와 모든 source head를 단일 PostgreSQL statement의
MVCC view로 읽어 immutable header/item에 고정한다. 후속 page는 같은 snapshot item만 읽으므로
중간에 새 source write가 commit돼도 count/root/page membership은 바뀌지 않는다.

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
- `POST /v1/service/cache-target-reconciliations/{request_id}/completions`

target create는 `If-None-Match: *`, update/delete는 앞서 받은 raw strong `If-Match`와 UUID
Idempotency-Key를 보낸다. `412`에서 최신 ETag로 자동 rebase하지 않고 snapshot reconcile 뒤 새 명시적
command를 만든다. 비동기 refresh는 `202`, `Location`, bounded `Retry-After`를 반환한다. write route는
T-VN-12 정적 registry에서 generic DB command, 기존 refresh ledger, outbox lifecycle ledger 중 정확히
하나로 분류한다.

operator는 ops read에서 epoch/claim/backlog/dead/reconciliation 상태를 보고, admin 표면에서 replay와
reconciliation command를 실행한다. ServiceToken scope는 consumer read/claim/ack/nack/snapshot,
restore-fence, recovery replay로 분리한다. admin reconciliation 시작은 active claim을 끊는 복구
mutation이므로 destructive recovery gate가 켜진 경우에만 허용한다.

reconciliation command는 active claim을 무효화하고 stream을 먼저 halt한 뒤 fixed snapshot을 만든다.
consumer는 `cache-target:snapshot` principal로 request ID와 external system/consumer ID/snapshot
ID/expected epoch/actual Merkle root를 exact 결박한 completion receipt를 제출한다. UUID
`Idempotency-Key`는 terminal 응답을 재생한다. receipt의 root가 snapshot root와 정확히 같고 epoch이
그대로이며 dead-letter가 0일 때만 `ready`/enabled로 전이하고 stream-scoped
`cache_target.reconciled` event를 같은 transaction에 기록한다. checksum 불일치는 failed receipt를
남기고 fenced/disabled 상태를 유지한다. terminal request에 다른 checksum을 재사용해서 resume할 수
없다.

### 8. 활성화

Map foundation과 PinVi paired consumer가 모두 merge되기 전에는 relay consumer를 켜지 않는다.
PinVi는 기본 off이며 credential, principal scope, pinned OpenAPI SHA, active epoch, full snapshot,
Merkle/count/high-watermark 일치 중 하나라도 없으면 fail-closed한다. consumer 배포 → contract pin →
restore clone/snapshot backfill → checksum 일치 → consumer enable → duplicate/gap/epoch live → soak 순서다.

## 근거

자연키 head와 tombstone은 projection row 수명과 source 순서를 분리한다. transaction-coupled outbox와
pull/ack는 critical write latency에서 네트워크를 제거하면서 at-least-once 복구를 가능하게 한다. Map이
restore epoch를 소유하면 restored producer payload가 epoch를 되감을 수 없고, fixed snapshot과 Merkle은
두 DB를 직접 연결하지 않고도 누락·중복을 증명한다.

## 결과

- **긍정**: target/link/update와 event 사이 dual-write가 사라지고 restore 뒤 stale resurrection을 막는다.
- **긍정**: consumer 장애와 poison event가 critical write를 막지 않으면서 운영자가 재현·재생할 수 있다.
- **부정**: source/head/event/outbox/delivery/snapshot 상태와 두 저장소 golden vector 운영이 추가된다.
- **부정**: strict global prefix는 poison event 해결 전 같은 stream 후속 전파를 의도적으로 멈춘다.
- **전환**: Map PR은 producer foundation일 뿐 `T-VN-41C` 완료가 아니다. PinVi paired PR, contract pin,
  n150 isolated live 증명 전까지 `T-VN-41A/B/C`는 open으로 유지한다.

## 기존 결정과의 관계

ADR-074의 source generation, restore epoch, transactional outbox 결정을 구체화한다. ADR-065의 admin
ETag 계약은 유지하되, 과거의 “PinVi service write 금지”는 ServiceToken 전용 vNext resource에 한해
본 ADR이 supersede한다. admin 권한을 PinVi에 주지 않는 결정은 유지한다.
