# ADR-074: Domain-owned replay, revision, outbox 쓰기 안전성

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-10

## 컨텍스트

일부 pipeline·schedule command에는 append-only replay ledger와 CAS가 있지만 다른 write에는
같은 의미가 없다. transport retry, stale admin 수정, cache-target 세대 역전이 서로 다른
오류를 만들며 하나의 범용 ledger로 합치면 lifecycle이 더 불명확해진다.

## 결정

1. 재시도가 필요한 각 command domain은 `(principal namespace, operation, Idempotency-Key)`와
   정규화 body fingerprint, 최초 결과를 저장하는 append-only ledger를 소유한다(D-10-1 3요소 key).
   같은 key/같은 body는 결과를 replay하고 다른 body는 409다.
2. mutable resource는 단조 `row_revision`과 `If-Match`를 사용한다. `If-Match` 누락은 428,
   stale write는 412다(D-10-3). consumer는 편집을 시작한 snapshot의 feature ID,
   `row_revision`, 응답 header의 raw strong `ETag`를 불변 편집 기준으로 함께 보존한다. mutation
   직전에 최신 revision을 다시 읽어 기준을 자동 rebasing하는 동작은 금지한다. 기존 policy
   revision은 resource-specific 선례로 유지한다.
3. cache target은 `(external_system, target_key)` identity, 단일 canonical coordinate,
   `source_generation`과 restore epoch을 가진다. 낮은 generation은 적용하지 않는다.
4. DB commit 뒤 외부 전파는 transactional outbox와 멱등 relay가 담당한다. critical write path에서
   원격 consumer 성공을 기다리지 않는다.
5. pipeline exact-scope active operation UNIQUE와 Idempotency-Key replay는 각각 업무 single-flight와
   HTTP 재시도 책임으로 직교한다.
6. admin의 네트워크 재시도 가능 command는 정적 inventory에서 누락 없이 분류한다. 공통
   `ops.domain_commands`는 actor·operation·UUID key·canonical request fingerprint를
   immutable claim으로, `ops.domain_command_results`는 최초 terminal HTTP 결과를 append-only로
   저장한다. DB-only command는 업무 변경과 claim/result를 한 transaction에 둔다.
7. 객체 저장소·Dagster·filesystem·host script처럼 DB 밖 효과가 있는 command는 도메인별
   execution table에서 `prepared → effect_started → effect_succeeded`를 단조 전이한다. terminal
   result는 효과별 output digest/proof가 있어야만 기록한다. `pending`은 성공으로 추정하지 않는다.
8. backup/create/restore/swap은 동일 session advisory lock
   `maintenance:backup-restore`를 host wrapper process가 fail-fast로 획득하고 child script
   전체 수명 동안 보유한다. wrapper는 `TERM`/`INT`를 직접 받아 DB session을 유지한 채
   child process group에 전달하고 제한 시간 뒤 `KILL`로 올린 다음 group 소멸과 direct child
   reap을 확인한 후에만 종료한다. API task 취소·timeout도 wrapper의 return code가 아니라
   pipe communication 완료를 기준으로 `TERM → bounded wait → KILL → bounded reap`한다.
   API connection에서 획득한 lock을 env flag로 child에게 위임하지 않는다. API 내부 delete도
   같은 key를 effect·proof·terminal commit 전체에 직접 보유한다.
9. host completion marker는 backup root의 전용 `0700` 디렉터리에서 `O_NOFOLLOW`,
   `O_EXCL`, file/dir `fsync`, Linux `renameat2(RENAME_NOREPLACE)`로 한 번만 생성한다.
   marker는 command/operation/effect/target identity, input digest, effect-specific output
   digest, 완료 시각을 포함한다. 기존 marker는 exact proof가 같을 때만 재사용하며 덮어쓰지 않는다.
10. caller 지정 backup destination은 `command_id + input_digest + backup_id` reservation을
    빈 `0700` 디렉터리에 먼저 fsync하고 `RENAME_NOREPLACE`로 공개한 뒤에만 effect를 시작한다.
    exact reservation·marker가 없는 기존 artifact나 restore target의 단순 health는 새 command의
    provenance가 아니므로 성공 결과로 채택하지 않는다.

## 근거

resource lifecycle에 맞는 안전장치를 각 domain이 소유해야 replay 결과와 동시성 의미가 분명하다.
revision과 outbox는 lost update와 dual-write를 별도로 해결한다.

admin UI는 `412`를 자동 재시도하지 않는다. 작성 중인 draft와 실패한 편집 기준을 보존하고,
운영자가 명시적으로 최신 snapshot을 다시 불러온 경우에만 새 편집 기준과 form을 교체한다.
초기 기준을 만들 때 revision과 detail 사이에 경쟁 갱신이 보이면 제한 횟수만 다시 읽고, 끝내
같은 `row_revision`을 얻지 못하면 mutation을 활성화하지 않는다.

## 결과

- **긍정**: 재시도, 경쟁 수정, 순서 역전, 외부 전파 실패를 구분하고 복구할 수 있다.
- **부정**: command별 ledger와 outbox 운영·purge가 필요하다.
- **부정**: 외부 효과 command는 별도 execution 상태·proof 저장과 process-restart 복구
  분기가 필요하고, backup/restore 동시 요청은 fail-fast `409`로 다시 시도해야 한다.
- **전환/rollback**: domain별로 독립 도입한다. relay는 backfill/reconciliation 뒤 enable하고 실패 시
  소비를 중단해 outbox를 보존한다. revision을 이해하지 못하는 consumer는 해당 resource cutover
  전에 선배포한다.

## 기존 결정과의 관계

ADR-065의 POI target ETag·generation 의미를 확장하고, canonical pipeline/schedule의 기존
append-only audit와 exact-scope 제약을 회귀 기준선으로 유지한다.
