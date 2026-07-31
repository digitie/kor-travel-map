# cache target generation/outbox 운영 runbook

ADR-081 producer foundation과 paired PinVi consumer의 준비·복구·검증 순서다. Map PR만 merge된
상태에서는 consumer를 켜지 않는다. 실제 credential과 prod 주소는 gitignored local runbook에만 둔다.

## 1. 사전 조건

1. Map/PinVi exact source commit과 pinned service OpenAPI SHA를 기록한다.
2. Map DB의 단일 Alembic head와 `alembic check`를 확인한다.
3. ServiceToken principal을 consumer, restore-fence, recovery replay scope로 분리하고 서로 다른
   external system이나 admin route에 사용할 수 없는지 확인한다.
4. Map target stream은 blocked/dead 0이고 PinVi consumer flag는 off여야 한다.
5. snapshot serializer/Merkle golden vector가 양쪽 exact commit에서 모두 통과해야 한다.

## 2. 최초 backfill과 enable

1. PinVi writer를 fence한 repeatable-read snapshot에서 desired target과 tombstone, source generation,
   source payload fingerprint를 만든다.
2. Map fixed snapshot을 끝까지 page한다. 모든 page의 `snapshot_id`, epoch, high-watermark, count,
   Merkle root가 첫 page와 같지 않으면 폐기하고 다시 시작한다.
3. 두 source projection의 count와 Merkle root를 비교한다. mismatch면 consumer를 켜지 않고 leaf
   identity/fingerprint 차이를 조사한다.
4. PinVi inbox/replica/checkpoint를 한 transaction에 backfill하고 같은 snapshot을 다시 비교한다.
5. credential, principal, OpenAPI SHA, epoch, checksum gate가 모두 green일 때만 consumer flag를 켠다.
6. claim→PinVi DB commit→ACK 순서를 확인하고 backlog가 contiguous하게 줄어드는지 본다.

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
- permanent 또는 max-attempt NACK: event는 dead letter가 되고 stream은 blocked다. 뒤 cursor를 수동
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
4. transient/permanent NACK, max attempt, dead block, ETag+Idempotency replay.
5. restore fence N+1, full backfill, 과거 epoch event 거부.
6. target/link/refresh DB rollback 시 대응 outbox 0행.
7. admin UI에서 backlog/dead/reconciliation 상태와 replay 결과 확인.

evidence에는 Map/PinVi commit, image ID, migration head, snapshot ID/epoch/high-watermark/count/Merkle,
fixture event ID만 남긴다. token, cookie, raw payload, 실데이터 screenshot과 trace는 종료 즉시 폐기한다.

## 6. 중지와 forward recovery

문제가 생기면 consumer flag를 끄고 claim을 중단하되 outbox와 dead letter를 삭제하지 않는다. 이미
적용한 schema를 downgrade하지 않고 forward fix한다. snapshot mismatch나 unknown event type/hash는
자동 보정하지 않는다. exact source와 DB evidence를 확인한 뒤 replay 또는 full reconcile을 선택한다.
