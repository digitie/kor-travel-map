# T-VN-41A~C 구현 완결 계획

## 목적

`T-VN-41A`의 source generation·restore epoch, `T-VN-41B`의 transaction-coupled
outbox, `T-VN-41C`의 PinVi pull relay·대조·consumer enable 준비를 하나의 Map 구현 PR과
짝을 이루는 PinVi 소비자 PR로 완결한다. Map의 기존 producer foundation(PR #917, migration
`0075`~`0079`)을 다시 만들지 않는다. T-VN-36 최종 fence 위에서 실제 writer·service API·권한
경계·consumer가 여전히 함께 동작하는지를 검증하고, 빠진 결선을 보완한다.

실제 n150 consumer enable은 구현 PR의 성공만으로 수행하지 않는다. immutable image·OpenAPI pin·빈
격리 DB의 snapshot/backfill checksum과 consumer runtime 증명이 모두 갖춰진 뒤 별도 live gate에서만
enable한다.

## 단일 정본과 경계

- 프로토콜·순서·실패 규칙은 ADR-081이다.
- Map은 source head/event ledger, stream control, outbox/delivery, fixed snapshot과 recovery
  receipt의 유일한 정본이다.
- PinVi는 source write에 접근하지 않고 service OpenAPI의 read/claim/ack/nack/snapshot/recovery
  경로만 소비한다. Map과 PinVi DB를 하나의 transaction으로 묶지 않는다.
- `ops.ops_live_topic_revisions`와 cache invalidation 신호는 outbox를 대체하지 않는다.
- consumer는 기본 비활성이며, Map source write는 PinVi 네트워크·relay I/O를 기다리지 않는다.

## 구현 순서

1. **A — source generation/restore epoch**
   - `0075`~`0079`의 stream/head/source-event/refresh-membership DDL과 source writer를 T-VN-36
     head에서 재검증한다.
   - target key NFC·trim·길이 검증, `(restore_epoch, source_generation)` 단조성, tombstone과
     idempotency body-conflict를 integration test로 고정한다.
   - restore fence는 stream lock 아래 epoch 증가, 과거 claim/delivery/reconciliation supersession,
     immutable receipt replay를 원자적으로 보장한다.

2. **B — transaction-coupled outbox**
   - target state/link/refresh 결과와 네 종류의 outbox event가 같은 Map transaction에서
     commit/rollback하도록 모든 실제 writer call-site를 전수 대조한다.
   - stream → head/target/link 잠금 순서와 trigger의 relay-order 할당을 보존한다. source write
     rollback 시 head/event/outbox가 모두 남지 않고, commit 시 event가 반드시 하나 생기는지를
     테스트한다.
   - event immutable ledger와 mutable delivery/lease/dead-letter를 분리하고, restore supersession이
     과거 epoch의 nonterminal delivery만 terminal로 바꾸는지를 검증한다.
   - `queued`를 포함한 refresh 상태 전이는 request/member snapshot/outbox를 같은 transaction에
     기록한다. executor가 시작되기 전 취소·정지돼도 consumer가 상태와 exact tuple을 관측할 수 있어야 한다.
   - 기존 admin target resource는 PinVi relay writer가 아니다. `pinvi`의 admin PUT/DELETE는
     source protocol required로 거부하고, 수동 소유 external system만 그 ETag CAS 경로를 사용한다.

3. **C — paired pull relay/reconciliation**
   - Map service API의 exact `cache-target:command`, `read`, `claim`, `ack`, `nack`, `snapshot`,
     `restore-fence`, `recovery` scope와 OpenAPI generation 7을 재export한다.
   - PinVi는 immutable inbox dedupe + target tuple CAS + consumer checkpoint를 한 PinVi DB
     transaction으로 만들고, 그 성공 뒤에만 ACK한다.
     같은 PR은 sync disabled 상태에서 raw ETag/expected epoch/Idempotency-Key CAS를 수행하는
     `pinvi-cache-target-restore-fence` one-shot command를 추가한다. command는 POST 전 raw ETag/control
     tuple을 immutable local receipt에 기록해 Map commit 뒤 응답 유실에도 같은 key/body의 exact replay `200`을
     완료한다. 동일 key의 병렬 실행이 Map `201`과 `200`을 각각 받아도 terminal payload·ETag가 같으면 먼저
     기록된 durable receipt로 수렴하고, receipt와 재조회 stream의 `fenced` tuple을 대조하지만 ordinary writer를
     열지 않는다.
     이 Map PR은 해당 구현을 중복하지 않고 clean PinVi worktree에서 command publisher, event consumer,
     sync worker 및 restore-fence regression을 실행해 Map contract compatibility를 확인한다. nack/dead-letter/
     replay와 strict per-stream prefix도 그 consumer의 불변식으로 유지한다.
   - fixed snapshot/Merkle reconciliation은 begin → writer backfill → seal → consumer completion
     순서를 지키며 checksum mismatch, duplicate, gap, stale restore epoch을 fail-closed한다.
   - current-main rebase 뒤 Map service OpenAPI SHA-256은
     `c6f9aba6ab4b815c394e5e1cb5fb4a2c3488d147d5bb1a7e21b92c1796f4aebd`다. PinVi는 이 service
     bytes를 exact vendor로 재고정한다. `consumer-rollout-v1.json`의 T-VN-41 receipt는
     `pending → candidate_verified → complete` 세 상태만 허용한다. `candidate_verified`는 n150
     격리 후보 archive·양 image ID·compatible-pair attestation·live evidence digest와 두 source
     commit을 모두 고정하지만, `final_c7_required=true`로 final main C7과 consumer enable을
     명시적으로 막는다. `complete`는 final main source/image의 C7 attestation까지 다시 통과한 뒤에만
     허용한다.

## 필수 검증

- Map fresh PostGIS migration: source write·delete·restore·rollback·outbox/delivery concurrent
  interleaving, claim/ack/nack/dead/replay, snapshot/reconciliation integration.
- PinVi actual consumer DB: duplicate delivery, out-of-order event, post-commit pre-ACK crash replay,
  dead-letter prefix block, restore epoch replacement, full snapshot Merkle/count/high-watermark.
- service OpenAPI export/check, generation-7 pin, Map/PinVi golden vector 및 scope matrix.
- 두 독립 적대 리뷰가 DB/transaction·consumer/auth/recovery 관점에서 P0=0을 확인한다.
- n150은 final implementation 이후 파괴적 isolated lane에서만 수행하며, 결과·Map/PinVi SHA·schema
  head·snapshot identity를 redacted receipt로 남긴다.

## 완료 정의

이 PR만으로 consumer를 production enable했다고 주장하지 않는다. Map의 A/B 정본과 PinVi C consumer가
각각 코드·contract·test에서 결선되고, paired pin과 두 적대 리뷰가 끝난 뒤 n150 isolated live gate를
통과해야 `T-VN-41A~C`를 완료로 표시한다.
