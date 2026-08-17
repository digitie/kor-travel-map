# cache target generation/outbox 운영 runbook

ADR-081 producer foundation과 paired PinVi consumer의 준비·복구·검증 순서다. Map PR만 merge된
상태에서는 consumer를 켜지 않는다. 실제 credential과 prod 주소는 gitignored local runbook에만 둔다.

## 1. 사전 조건

1. Map/PinVi exact source commit과 service OpenAPI SHA가 PinVi compatible pair의 **contract generation
   7**로 이미 pin돼 있어야 한다. generation 6이거나 exact pair/SHA가 다르면 command writer, backfill,
   refresh command와 consumer를 모두 켜지 않는다.
2. Map DB의 단일 Alembic head와 `alembic check`를 확인한다.
3. 한 canonical `(consumer_id, sorted external_systems)` binding마다 다음 exact 역할 token 네 개가 각각
   하나인지 확인한다: command=`{command}`, consumer=`{read,claim,ack,nack,snapshot}`,
   restore=`{restore-fence}`, recovery=`{recovery,recovery-replay}`. command token은 source PUT/DELETE와
   refresh create만, consumer token은 read/relay/snapshot만 호출해야 한다. 제거된
   `cache-target:consumer`가 registry에서 수용되거나 command token으로 consumer/restore/recovery
   route가 허용되면 중단한다. 같은 `consumer_id`를 서로 다른 system tuple의 binding으로 나누지 말고
   필요한 system을 한 sorted union으로 합친다. 역할 token 원문은 public VWorld/API key를 포함한 다른
   configured credential과 공유하지 않는다.
4. Map target stream은 blocked/dead 0이고 PinVi consumer flag는 off여야 한다.
5. snapshot serializer/Merkle golden vector가 양쪽 exact commit에서 모두 통과해야 한다.

## 2. 최초 backfill과 enable

1. PinVi writer를 fence한 repeatable-read snapshot에서 desired target과 tombstone, source generation,
   source payload fingerprint를 만든다.
2. `cache-target:recovery` principal로 stream ETag를 조건부 전송해 reconciliation begin을 호출한다.
   stream이 아직 없으면 `If-None-Match: *`로 시작하고, 응답의 `preparing` request ID,
   reconciliation ETag, body의 `stream_entity_tag`를 각각 기록한다.
3. `cache-target:command` principal로 PinVi writer snapshot의 desired target/tombstone을 Map service
   PUT/DELETE로 backfill한다. 이때 restore epoch는 begin receipt와 같아야 하며 claim consumer는 아직
   켜지 않는다. PUT/DELETE의 최신 ETag를 다시 읽어 CAS를 이어갈 때는 command token이 아니라
   `cache-target:read`가 든 consumer token으로 source GET을 호출한다. refresh create의 `Location`을
   polling할 때도 같은 consumer token으로 refresh GET을 호출한다.
4. begin에서 받은 request ID와 reconciliation ETag를 `If-Match`로 보내 seal을 호출한다. seal body에는
   PinVi writer snapshot에서 계산한 `expected_restore_epoch`, `expected_item_count`,
   `expected_merkle_root`를 넣는다. Map의 현재 source heads와 다르면 `412`로 실패하고 request는
   `preparing`으로 남아야 한다.
5. service stream read의 active reconciliation descriptor에서 request ID와 fixed snapshot identity,
   epoch, count, root, high-watermark를 읽는다. descriptor가 없거나 seal receipt와 다르면 중단한다.
6. request-bound snapshot endpoint를 끝까지 page한다. 모든 page의 `snapshot_id`, epoch,
   high-watermark, count, Merkle root가 descriptor와 같지 않으면 폐기하고 다시 시작한다. 일반
   snapshot endpoint에서 새 snapshot을 만들어 completion에 사용하지 않는다.
7. 두 source projection의 count와 Merkle root를 비교한다. mismatch면 consumer를 켜지 않고 leaf
   identity/fingerprint 차이를 조사한다.
8. PinVi inbox/replica/checkpoint를 한 transaction에 backfill하고 같은 snapshot을 다시 비교한다.
9. `cache-target:snapshot` principal로 request/system/consumer/snapshot/epoch/root를 exact 결박한
   completion receipt를 UUID Idempotency-Key와 함께 제출한다. exact replay 외 다른 body/key 조합은
   실패해야 한다.
10. Map이 `ready`/enabled로 전이한 receipt와 credential, OpenAPI SHA gate가 모두 green일 때만 PinVi
   consumer flag를 켠다.
11. claim→PinVi DB commit→ACK 순서를 확인하고 backlog가 contiguous하게 줄어드는지 본다.

## 3. restore epoch 전환

1. source writer와 claim consumer를 먼저 fence한다.
2. `GET /v1/service/cache-target-streams/{external_system}`의 raw ETag와 현재 epoch를 보존한다.
3. UUID Idempotency-Key, 직전 `If-Match`, `expected_restore_epoch`, 사유로 restore-fence command를
   호출한다. 응답이 유실되면 같은 key/body로 replay한다.
4. `201` 또는 exact `200` replay receipt에서 epoch가 정확히 N+1이고 기존 claim이 무효화됐는지
   확인한다. `412`에서는 자동 rebase하거나 다시 증가시키지 않고 control을 다시 읽어 full reconcile한다.
5. Map 자체 restore CLI도 restored payload를 공개하기 전에 같은 domain command를 호출해야 한다.
6. 새 epoch fixed snapshot과 PinVi DB를 원자 reconcile한 뒤에만 writer/consumer를 다시 연다.
7. 지연된 과거 epoch event가 projection과 ACK cursor를 바꾸지 않는지 확인한다.

## 4. lease와 poison event 복구

- ACK 전 consumer crash: lease 만료 뒤 동일 event가 다시 claim돼야 한다. PinVi inbox `event_id`
  UNIQUE와 tuple CAS 때문에 side effect는 추가되지 않아야 한다.
- transient NACK: persisted `Retry-After`/backoff 뒤 같은 event가 재시도된다. 후속 order는 앞서가지 않는다.
- permanent 또는 max-attempt NACK: claim의 첫 미ACK event만 dead letter로 전이할 수 있다. 중간
  poison event라면 앞 contiguous prefix를 먼저 ACK한다. 이를 생략한 NACK은 mutation 없이
  `409 dead_letter_requires_prefix_ack`여야 한다. dead 전이 뒤 stream은 blocked며 뒤 cursor를 수동
  skip하거나 새 event로 복제하지 않는다.
- 복구: dead-letter detail의 ETag와 fingerprint를 대조하고 UUID Idempotency-Key로 replay한다. 같은
  event ID/order/tuple/fingerprint가 pending으로 돌아와 ACK된 뒤 full snapshot Merkle equality를
  재확인한다. 그 전에는 consumer를 ready로 표시하지 않는다.

## 5. n150 isolated live 인수

production DB에 직접 migration을 자동 적용하지 않는다. exact source의 격리 restore clone에서 다음을
모두 증명한다.

1. same command/event 중복 전달의 추가 side effect 0.
2. 의도적으로 한 event를 누락시켜 checksum mismatch를 만들고 exact replay 뒤 equality 회복.
3. consumer DB commit 뒤 ACK 전 강제 종료, expired lease reclaim과 duplicate ACK.
4. transient/permanent NACK, mid-claim prefix-ACK 강제, max attempt, dead block,
   ETag+Idempotency replay.
5. restore fence N+1, full backfill, 과거 epoch event 거부.
6. target/link/refresh DB rollback 시 대응 outbox 0행.
7. admin UI에서 backlog/dead/reconciliation 상태와 replay 결과 확인.

evidence에는 Map/PinVi commit, image ID, migration head, 같은 `external_system`·`consumer_id`의
initial `blocked`/`blocked_event_id`·delivery count와 final `ready`/unblocked·consumer enable·모든
비terminal delivery count `0`, reconciliation request의 terminal snapshot ID/epoch/count/Merkle를
남긴다. token, cookie, raw payload, 실데이터 screenshot과 trace는 종료 즉시 폐기한다.

### 5.1 추적 가능한 Live UI 증거

격리 candidate의 dead-letter fixture와 PinVi recovery worker를 준비한 뒤 admin frontend 디렉터리에서
`npm run e2e:live:cache-target-streams`를 실행한다. 이 명령은 일반 live suite와 분리되어 있으며
다음 환경변수가 모두 정확해야만 destructive recovery를 실행한다.

- 격리 경계: `E2E_ISOLATED_LIVE_EVIDENCE=1`,
  `E2E_ISOLATED_LIVE_DOCKER_NETWORK=1`
- destructive opt-in: `E2E_CACHE_TARGET_STREAM_RECOVERY_WRITE=1`
- 접속·인증: `E2E_BASE_URL`, `E2E_ADMIN_USERNAME`, `E2E_ADMIN_PASSWORD`
- 증거 결박: `E2E_CACHE_TARGET_STREAM_EXTERNAL_SYSTEM`,
  `E2E_CACHE_TARGET_STREAM_DEAD_EVENT_ID`,
  `E2E_CACHE_TARGET_STREAM_EXPECTED_SNAPSHOT_ID`,
  `E2E_CACHE_TARGET_STREAM_EXPECTED_RESTORE_EPOCH`,
  `E2E_CACHE_TARGET_STREAM_EXPECTED_COUNT`,
  `E2E_CACHE_TARGET_STREAM_EXPECTED_MERKLE_ROOT`

대상 URL은 loopback, RFC 1918 주소 또는 격리 Compose의 `candidate-ui`만 허용한다. 일부 opt-in만
지정한 실행은 skip하지 않고 fail-close한다. 스펙은 실제 login POST의 `200`과 `Set-Cookie`, 브라우저의
ops/admin BFF 전용 호출, replay ETag·Idempotency-Key, 최종 ready/backlog 0/dead 0 및 동일
snapshot/count/Merkle을 확인한다. trace, video, screenshot은 생성하지 않으며 종료 시 cookie와 Web
Storage 및 임시 인증 상태를 삭제한다.

## 6. 중지와 forward recovery

문제가 생기면 consumer flag를 끄고 claim을 중단하되 outbox와 dead letter를 삭제하지 않는다. 이미
적용한 schema를 downgrade하지 않고 forward fix한다. snapshot mismatch나 unknown event type/hash는
자동 보정하지 않는다. exact source와 DB evidence를 확인한 뒤 replay 또는 full reconcile을 선택한다.
