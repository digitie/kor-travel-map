# cache-target Map writer-drain control plane

## 1. 목적과 경계

T-VN-41D는 cache-target diagnostic과 최초 cutover의 writer fence 앞에서 Map Dagster
producer를 안전하게 비우는 **Map 소유** control plane이다. Docker Manager는 전역
lock, frozen Compose, 전체 writer stop, backup/restore와 journal을 소유한다. 반면
schedule/sensor의 원래 상태, Dagster run의 terminal-cancel 판단과 그 복구 증적은 Map만
소유한다.

이는 공개 REST, admin UI, 기존 `/v1/ops` cancel/schedule endpoint의 확장이 아니다.
Manager가 frozen resolved Compose에서 candidate Map API image를 one-shot runner로만
실행하는 private typed command다. 따라서 별도 장기 token을 만들지 않고, cache-target
4-role token registry와 ops/admin/service token을 재사용하지 않는다. runner의 stdin/stdout
경계에는 credential, run ID, GraphQL 원문, schedule/sensor 이름을 내보내지 않는다.

## 2. 상태와 호출 계약

Manager journal의 상태는 다음 순서를 강제한다.

```text
prepared -> writers_fencing -> writers_draining [fsync]
         -> writers_drained [fsync] -> writers_stopping [fsync]
         -> writers_fenced
```

`writers_fencing`은 frozen Compose·현재 compatible pair·Map command image만 읽어
검증한다. 첫 Map mutation 전에는 반드시 `writers_draining`을 fsync한다. Map command는
다음 입력만 받는다.

```json
{
  "contract_version": "ktm-cache-target-writer-drain/v1",
  "operation": "begin|attest|restore",
  "owner_kind": "diagnostic|cutover",
  "owner_id": "canonical-lowercase-uuid",
  "lease_id": "canonical-lowercase-uuid 또는 begin에서는 없음",
  "prior_receipt_sha256": "attest/restore의 64자 lowercase sha256"
}
```

출력은 하나의 secret-free receipt JSON이다. Map 내부 DB에는 exact instigation/run
identity를 저장할 수 있지만, Manager journal과 CLI JSON에는 `lease_id`, receipt SHA-256,
상태, bounded count만 남긴다. Manager는 receipt의 canonical digest, owner, contract
revision 및 terminal status를 검증한 뒤에만 다음 phase로 진행한다.

`begin`은 다음을 idempotent하게 수행한다.

1. owner가 같은 active lease가 있으면 같은 receipt를 재현하고, 다른 owner의 active
   lease가 있으면 fail-close한다.
2. 모든 Map schedule/sensor의 identity와 이전 running/stopped 상태를 durable하게 기록한다.
3. running instigation을 pause한 뒤, Map-owned run만 bounded grace window에서 기다린다.
   grace 뒤 처음 관측되는 각 run은 run별 CAS reservation 뒤 한 번의 typed terminal-cancel로
   수렴시킨다. pause와 이미 enqueue된 late run은 원자적이지 않으므로 terminal poll마다 새로
   보인 run도 같은 CAS 경로로 넣되, dispatch 결과가 불명확한 run은 재전송하지 않고 `attest`로
   실제 terminal 상태를 판정한다.
4. active lease, paused instigation, Map Dagster nonterminal run 0을 같은 receipt로
   attest한 경우에만 `drained`를 반환한다.

`attest`는 lease·snapshot digest·paused instigation·nonterminal run 0을 다시 확인하며,
어느 하나라도 달라지면 stop을 시작하지 않는다. `restore`는 lease에 기록된 **기존 running
상태만** 정확히 되돌린 후 재attest한다. 이미 restore된 lease의 같은 요청은 같은 terminal
receipt를 재현한다. 다른 owner, snapshot/receipt digest 불일치, unknown phase 또는 restore
실패는 새 mutation·journal archive를 막는다.

## 3. durable schema

Map application DB의 `ops` schema가 lease 정본이다. 데이터는 small, update-heavy control
state이므로 event-log JSON을 한 행에 누적하지 않고 lease·instigation·run을 정규화한다.

| relation | 핵심 열 | 불변식/색인 |
| --- | --- | --- |
| `ops.cache_target_writer_drain_leases` | opaque UUID PK, `owner_kind`, `owner_id`, `state`, `snapshot_sha256`, `receipt_sha256`, `created_at`, `updated_at`, `restored_at`, secret-free failure code | `(owner_kind, owner_id)` unique; `draining|drained|restoring`는 partial unique index로 전역 하나만 허용 |
| `ops.cache_target_writer_drain_instigations` | `(lease_id, kind, selector_id)` PK, durable state/origin identity, `was_running`, pause/restore 결과 | lease FK와 `(lease_id, kind, selector_id)` B-tree; raw GraphQL payload 없음 |
| `ops.cache_target_writer_drain_runs` | `(lease_id, dagster_run_id)` PK, initial status, cancel reservation/result, terminal status | lease FK; terminal cancel의 한 번 실행과 crash resume을 CAS로 보장 |

모든 timestamp는 `TIMESTAMPTZ`, 상태는 진화 가능한 `TEXT CHECK`, snapshot/receipt digest는
lowercase SHA-256 `TEXT CHECK`로 둔다. active lease lookup과 owner replay는 B-tree index를
사용한다. lease가 terminal이면 history는 보존하되, migration/DB restore 경로는 active lease가
남은 상태에서 downgrade나 새 drain을 허용하지 않는다.

## 4. crash recovery와 cutover 경계

`writers_draining`은 attempt budget을 소비하는 durable mutation boundary다. begin 성공 뒤
Manager receipt fsync 전 crash, grace timeout, cancel 응답 유실, `writers_drained` fsync 실패,
다른 diagnostic ID 시작은 모두 같은 owner lease의 `attest → restore`를 먼저 수행한다.

writer stop 뒤 crash한 diagnostic/cutover recovery는 Map Dagster webserver만 먼저
recreate하고(daemon은 계속 정지), private runner로 `restore`한다. 그 receipt와 prior
compatible pair attestation이 맞은 뒤에만 daemon을 포함한 writer를 재기동한다. 이 순서가
없으면 schedule을 먼저 열어 새 run을 만들 수 있으므로 archive/resume하지 않는다.

cutover에서 backup bundle이 commit되기 전 drain 실패는 DB restore나 full runtime coupled
rollback으로 처리하지 않는다. Map lease exact restore와 pair re-attestation만 하는
pre-backup recovery다. backup bundle 이후 실패만 기존 DB backup/restore coupled rollback을
사용한다. 이 rollback이 Map application/Dagster DB를 `drained` lease와 paused instigation으로
복원한 경우에도, Manager는 Map Dagster webserver만 먼저 세운 뒤 같은 lease의 `restore` receipt를
durable journal에 기록한다. 그 뒤에만 daemon을 포함한 old runtime을 열고 prior pair를
re-attest한다. 개발 중간 데이터는 recovery 대상이 아니며 file source 또는 ETL 재실행으로
재생성한다. 단, 최종 schema의 backup/restore rehearsal은 계속 필수다.

## 5. 격리 검증

실제 production host-mode Compose는 프로젝트명을 바꿔도 고정 port·host mount를 공유하므로
격리 rehearsal로 사용하지 않는다. 이 task는 다음 순서를 고정한다.

1. Map lease repository/GraphQL client는 fake Dagster와 isolated Postgres에서 pause, late
   run, timeout/cancel, receipt-loss, crash resume, exact restore를 검증한다.
2. Manager model/orchestration은 frozen runner receipt를 fake로 주입해 phase, attempt budget,
   pre-backup recovery, journal tamper와 no-generic-compose-bypass를 검증한다.
3. 별도 ephemeral Compose project의 fake Map private command로 실제 frozen runner의
   `begin → attest → restore` stdin/argv/receipt 경계를 rehearsal한다. fixture는 전용 network와
   temporary bind mount만 쓰며 canonical production `.env`, host network, production
   database/bucket을 참조하지 않는다. webserver-only restore와 pair 재기동 순서는 Manager
   orchestration phase 회귀에서 따로 검증한다.

production/n150 검증은 위 세 단계와 별도 명시 승인을 모두 통과한 뒤의 다음 단계다.
