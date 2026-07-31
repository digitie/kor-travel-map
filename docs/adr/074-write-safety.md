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
8. backup/create/restore/swap은 DB execution에 무작위 256-bit `effect_token`을 immutable
   identity로 저장한다. API는 `maintenance:backup-restore` session lock 안에서 고정 이름의
   global Docker fence를 먼저 원자 생성·inspect하고 그 뒤에만 `prepared → effect_started`를
   commit한다. 기존 foreign/mismatched fence가 있으면 새 command는 `prepared`에 남고 외부
   mutation은 시작하지 않는다. API가 fence 생성 뒤 transition 전에 종료되면 같은
   `prepared` command만 exact running fence를 다시 채택할 수 있다.
9. Docker fence는 canonical compose `postgres` container의 local immutable `sha256:` Image
   ID만 사용하고 `--pull=never`로 만든다. 고정 name, `effect_token`, command ID, operation,
   effect kind, input digest, marker key, backup ID, fence source revision, Image ID label을
   모두 inspect한다. fence는 network none, read-only rootfs, capability 전체 제거,
   `no-new-privileges`, 비 root user, PID 제한을 적용한다. host script는 mutation 전에 이
   pre-acquired exact running shape를 다시 검증한다.
10. host wrapper는 같은 advisory lock을 fail-fast로 획득하고 child script 전체 수명 동안
    보유한다. Docker daemon 외부 효과는 local CLI 종료로 취소됐다고 증명할 수 없으므로
    effect가 시작된 뒤에는 non-interruptible supervised 작업이다. wrapper는 `TERM`/`INT`를
    호출자 detach 요청으로만 기록하고 child에는 전달하지 않으며 API pipe와 분리된 임시
    spool을 쓴다. direct child와 process group이 자연 terminal에 도달한 뒤에만 lock을
    해제한다. API cancellation/timeout은 bounded 반환하되 wrapper communication은 background에서
    유지한다.
11. wrapper/API container가 `SIGKILL`, OOM, rollout으로 함께 사라져 PostgreSQL lock이
    해제돼도 Docker fence는 daemon에 남아 동일 command와 다른 command의 mutation을 모두
    막는다. marker 없는 `effect_started`는 script를 다시 호출하지 않고
    `409 BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED`로 fail-close한다. missing/foreign/
    mismatched/terminal-without-marker evidence는 자동 채택하지 않는다. 실제 target과 output
    identity를 외부 운영자가 검증한 뒤 exact marker를 먼저 기록하고, marker proof 뒤 exact
    fence만 해제한 다음 같은 key로 terminal result를 회수한다. workload 자체의 exact
    terminal을 증명할 수 없으면 manual 상태를 유지한다. API 내부 delete는 같은 advisory
    key를 effect·proof·terminal commit 전체에 직접 보유한다.
12. host completion marker는 backup root의 전용 `0700` 디렉터리에서 `O_NOFOLLOW`,
   `O_EXCL`, file/dir `fsync`, Linux `renameat2(RENAME_NOREPLACE)`로 한 번만 생성한다.
   marker는 command/operation/effect/target identity, input digest, effect-specific output
   digest, 완료 시각을 포함한다. 기존 marker는 exact proof가 같을 때만 재사용하며 덮어쓰지 않는다.
13. caller 지정 backup destination은 `command_id + input_digest + backup_id` reservation을
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
- **부정**: 외부 효과 command는 execution 상태·proof·Docker fence를 함께 운영해야 한다.
  hard crash 뒤 workload terminal을 exact 증명할 수 없으면 자동 복구하지 않으므로 운영자가
  target/output을 대조하고 marker를 기록할 때까지 backup/restore/swap 전체가 fail-close한다.
- **전환/rollback**: domain별로 독립 도입한다. relay는 backfill/reconciliation 뒤 enable하고 실패 시
  소비를 중단해 outbox를 보존한다. revision을 이해하지 못하는 consumer는 해당 resource cutover
  전에 선배포한다.

## 기존 결정과의 관계

ADR-065의 POI target ETag·generation 의미를 확장하고, canonical pipeline/schedule의 기존
append-only audit와 exact-scope 제약을 회귀 기준선으로 유지한다.
