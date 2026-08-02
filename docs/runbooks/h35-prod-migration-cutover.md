# H35 prod 마이그레이션 cutover 보정 runbook

> 상태: **구현 검증·최종 승인 전 실행 금지**
>
> 대상: `0063_pipeline_root_id`에서 `0078_cache_target_gc_observe`로 가는 H35 cutover
>
> 관계: `T-VN-H35`, `T-VN-41`, Docker-manager generation 7

이 문서는 적대 감사 두 번에서 `NO_GO`였던 과거 H35 runbook과 그때의 부분 helper를 실행 절차로
인정하지 않는다. 이를 대체하는 다섯 typed helper도 독립 검증·격리 리허설·최종 exact HEAD
적대 리뷰 1건·사용자 승인이 모두 끝나기 전에는 prod에서 실행하지 않는다.

## 1. 단일 소유 경계

Docker-manager가 cutover orchestration의 유일한 소유자다. 한 프로세스가 전 구간 전역 lock과
mode `0600` durable journal을 잡고 다음을 직렬 실행한다.

1. writer fence와 mutation-zero 증명
2. Map app DB·Map Dagster DB·Pin DB와 manager state/env/manifest의 결합 백업
3. Map helper `preflight` → `migrate` → `csv5`
4. generation 7 bootstrap·initial·enable·canary 뒤 final all-writer stop
5. Map helper `gc` → `verify`
6. forward 경계 확정 또는 결합 복원

Map 저장소는 자격증명과 운영 경로를 모르는 다섯 helper만 제공한다. helper는 lock/journal,
backup/restore, container/process stop/start/recreate, ingress, image tag, daemon enablement를 다루지
않는다. helper가 runtime을 재기동하거나 외부 event를 내면 그 phase는 실패다.

Pin writer fence와 Pin DB 복원은 Docker-manager/Pin 경계의 책임이다. Map helper가 Pin DB를
직접 읽거나 쓸 수 없다.

## 2. 절대 불변식

- cutover window 전체가 **하나의 manager process·하나의 global lock·하나의 transaction UUID**에
  결속된다. phase마다 lock을 놓았다 다시 잡는 방식은 금지한다.
- unfinished journal이 하나라도 있으면 deploy, capture, rollback, backup, enable, canary, GC를
  포함한 다른 모든 전역 mutation은 fail-close한다.
- Map API, Map Dagster web/daemon/schedule/sensor와 Pin의 모든 DB writer가 fence 대상이다.
  ingress 차단이나 실행 중 transaction 0만으로 writer fence를 주장하지 않는다.
- old daemon은 실패·복원 경로를 포함해 자동 재기동하지 않는다. manager가 exact 이전
  enablement와 image identity를 검증한 뒤 명시적으로만 복원한다.
- `0064`, `0068`, `0069`는 `autocommit_block()` 때문에 partial state가 가능하다.
  `0070`부터 `0078`까지는 revision별 transactional이다. 실패 시 무조건 downgrade하거나
  처음부터 재실행하지 않고, 같은 transaction UUID의 partial probe로 forward 재개 가능성을
  먼저 판정한다.
- normal image-only rollback은 rollback이 아니다. schema/data/manager state가 함께 움직인 뒤
  옛 image만 올리면 계약이 갈라지므로 금지한다.
- receipt나 journal에 DSN, credential, host, 운영 경로, env 원문, raw payload를 쓰지 않는다.
- H35 완료 전 prod 네트워크에서 helper나 candidate runtime을 실행하지 않는다.

## 3. 상태 머신

manager journal의 상태는 아래 순서만 허용한다. 모든 transition은 이전 receipt digest와 exact
release provenance를 검증한 뒤 원자적으로 기록한다.

```text
opened
  -> writers_fenced
  -> backup_verified
  -> map_preflight_verified
  -> map_schema_0078
  -> csv5_restored
  -> generation7_bootstrapped
  -> initial_verified
  -> enabled
  -> canary_verified
  -> final_writers_stopped
  -> map_gc_verified
  -> map_verified
  -> forward_committed
  -> closed
```

`forward_committed` 전에는 결합 복원만 허용한다. 그 뒤에는 옛 DB/state/env/manifest 복원을
거부하고 forward fix만 허용한다. 어떤 실패에서도 runtime 자동 재기동이나 fence 자동 해제는
하지 않는다.

## 4. Map typed helper 계약

계획 CLI는 다음 다섯 operation만 가진다.

```text
python scripts/h35/h35_cutover.py preflight
python scripts/h35/h35_cutover.py migrate
python scripts/h35/h35_cutover.py csv5
python scripts/h35/h35_cutover.py gc
python scripts/h35/h35_cutover.py verify
```

request는 stdin의 단일 JSON이고 receipt는 stdout의 단일 JSON line이다. DB 연결은 manager가
고정한 candidate image의 기존 runtime env로 주입한다. request에는 DSN·credential·host path를
넣지 않는다. `csv5`는 exact source revision의 image에 포함된 canonical 5-file bundle만 읽고
임의 host path를 받지 않는다.

성공·거부·실패 모두 stderr는 비어 있고 stdout은 JSON 한 줄뿐이어야 한다. argv/request를
검증하기 전의 실패는 `contract_version`, `status=failed`, 비밀 없는 stable `error_code`만 가진
좁은 error envelope를 쓴다. raw argv, stdin, 예외 메시지·클래스·traceback은 반사하지 않는다.

공통 receipt key는 다음과 같다.

| key | 계약 |
| --- | --- |
| `contract_version` | 최초 구현은 `h35-map/v1` |
| `operation` | `preflight`, `migrate`, `csv5`, `gc`, `verify` 중 하나 |
| `transaction_id` | manager가 발급한 UUID; window 전체에서 동일 |
| `status` | `accepted`, `rejected`, `failed` |
| `source_revision` | candidate Map exact 40-hex revision |
| `database_identity` | backup identity와 결속되는 비밀 없는 opaque digest |
| `request_digest` | canonical request SHA-256 |
| `prior_receipt_digest` | 직전 phase receipt SHA-256; 첫 phase만 `null` |
| `schema_before`, `schema_after` | exact Alembic revision |
| `forward_boundary` | 관측값. 경계 결정·영속은 manager만 수행 |
| `row_counts` | phase별 exact 수치 map |
| `checks` | 이름·기대·관측·통과 여부를 가진 typed check 목록 |
| `runtime_mutation_count` | 항상 `0`이어야 함 |
| `external_event_count` | 항상 `0`이어야 함 |
| `cache_target_evidence` | `preflight`/`migrate`/`csv5`/`gc`는 `null`; accepted `verify`만 exact object |

같은 `transaction_id + request_digest + prior_receipt_digest` 재호출만 멱등 receipt를 재발급할 수
있다. 하나라도 다르면 DB mutation 전에 거부한다. receipt 순서는
`preflight(null)` → `migrate(preflight)` → `csv5(migrate)` → `gc(csv5)` → `verify(gc)`다.
Docker-manager는 key와 타입을 임의 확장하지 않고 receipt 전체와 digest를 journal에 저장한다.

### 4.1 live DB identity v1

helper는 각 phase의 DB mutation 전에 `pg_control_system()` 접근 권한과 `alembic_version` 정확히
1행을 확인하고, request 값을 echo하지 않고 live DB에서 다음 바이트를 다시 만든다. 모든 필드는
ASCII subset UTF-8이며 prefix, 각 separator와 마지막 terminator는 모두 NUL(`0x00`)이다.

```text
b"h35-db-identity-v1\0"
+ canonical_transaction_uuid + b"\0"
+ b"map_application\0"
+ current_database() + b"\0"
+ pg_control_system().system_identifier(decimal) + b"\0"
```

`database`는 `[a-z][a-z0-9_]{0,62}`, system identifier는 ASCII decimal 1~32자리만 허용한다.
위 바이트의 SHA-256 lowercase hex가 `database_identity`다. golden vector는 transaction
`00000000-0000-0000-0000-000000000001`, database `kor_travel_map`, system identifier
`12345678901234567890`일 때
`9bca9b82ad2304759581ebf16e724461fcfd7c657e2b41ce5ae3ae54847dee5a`다. 두 저장소 구현은 이
vector가 다르면 실행 전에 실패해야 한다. receipt에는 요청값이 아니라 live 재계산값만 쓴다.

## 5. exact phase gate

### 5.1 `preflight`

- schema: `0063_pipeline_root_id`
- 공개 item: **3,265**
- `0075`가 새 제약을 만들기 전에 기존 행 전체를 검사한다.
  - identity 구성요소 null/blank/비정규 값 0
  - NFC가 아닌 identity 0
  - 앞뒤 공백이 있는 identity 0
  - 길이 상한 위반 0
  - 예정 CHECK 위반 0
  - 예정 FK orphan 0
- Map API/Dagster 및 Pin writer fence receipt가 모두 같은 transaction UUID와 DB identity에
  결속됐는지 manager가 먼저 확인한다. helper는 fence를 만들지 않고 입력 증거만 검증한다.

하나라도 다르면 mutation 0으로 종료한다.

### 5.2 `migrate`

- 정확한 선형 head: `0078_cache_target_gc_observe`
- 공개 item: **3,043**
- `0064`·`0068`·`0069` partial probe가 최종 shape인지 확인한다.
  - invalid/candidate index 0
  - 임시 constraint/column/index 잔여 0
  - Alembic version과 실제 schema shape 불일치 0
- `0070`~`0078`은 각 revision의 transaction 완료 증거를 남긴다.

재진입은 partial state가 해당 revision의 명시적 forward-resume 전제와 일치할 때만 허용한다.
다른 shape는 자동 downgrade·자동 복원 없이 fail-close한다.

### 5.3 `csv5`

- canonical CSV 파일 수: **5**
- accepted: **222**
- rejected: **0**
- 공개 item: **3,265**
- CSV bundle identity와 SHA-256이 candidate source revision의 manifest와 exact해야 한다.
- 같은 transaction UUID의 동일 bundle 재호출은 새 decision/item을 누적하지 않는다.

`3,043` 상태에서 CSV5가 성공하지 못하면 새 runtime을 시작하지 않는다.

### 5.4 `gc`

- 기존 `AsyncKorTravelMapClient.drain_expired_cache_target_snapshots`만 호출한다.
- observation run ID는 outer cutover transaction UUID에서 결정적으로 파생하며 retry도 같다.
- 새 ledger나 `0079`를 만들지 않는다. 기존 session advisory lock, batch transaction,
  `ON CONFLICT DO NOTHING` observation을 그대로 쓴다.
- retry 승인 기준은 attempt별 삭제 건수가 아니다. 최종 expired·unreferenced item/header backlog 0,
  GC 전후 referenced item/header 보존, stored observation과 fresh referenced count 일치다.
- `cache_target_evidence`는 `null`이고 runtime mutation과 외부 event는 0이다.

### 5.5 `verify`

- schema: `0078_cache_target_gc_observe`
- 공개 item: **3,265**
- `0075`~`0078` 검증:
  - identity/NFC/trim/length CHECK와 FK가 최종 이름·shape로 존재하고 validate됨
  - generation outbox·source receipt·snapshot GC·GC observation table/constraint/index가 exact
  - outbox/receipt 자연키 및 monotonic/unique 계약 위반 0
  - invalid index와 orphan FK 0
  - bounded GC와 observation retention 설정이 schema/config 계약과 일치
- `runtime_mutation_count = 0`, `external_event_count = 0`
- final all-writer stop 뒤 HTTP 없이 하나의 repeatable-read DB view에서 PinVi stream을 검증한다.
- 최신 unexpired snapshot의 restore epoch, header/item count, snapshot item·live source head Merkle
  root와 material watermark를 같은 view에서 다시 계산해 mixed·stale·invalid hash를 거부한다.
- active reconciliation, delivery 없는 outbox, active claim, non-terminal delivery backlog가 각각 0이다.
- `gc`의 deterministic observation이 존재하고 fresh referenced count와 같아야 한다.

accepted `verify.cache_target_evidence`는 아래 exact key만 가진다.

| key | exact 계약 |
| --- | --- |
| `contract_version` | `ktm-cache-target-final-evidence/v1` |
| `external_system` | `pinvi` |
| `stream_state` | `ready` |
| `consumer_id` | 비어 있지 않은 canonical 문자열 |
| `restore_epoch`, `control_version` | 양의 정수 |
| `stream_control_etag`, `high_watermark_cursor` | 비어 있지 않은 canonical 문자열 |
| `snapshot_count` | 0 이상 정수 |
| `snapshot_merkle_root` | lowercase SHA-256 hex |
| `reconciliation_backlog_count` | `0` |
| `outbox_backlog_count` | `0` |
| `claim_backlog_count` | `0` |
| `delivery_backlog_count` | `0` |

## 6. writer fence 완전성

구현 전에 writer registry를 한 곳에서 생성하고 테스트가 전수성을 강제한다. 최소 집합은 다음을
포함하며 이름을 예시 service 목록으로 하드코딩하지 않는다.

- Map API의 admin/public/ops write route와 background write task
- Map Dagster daemon, schedule, sensor, queued/running run, 직접 실행 가능한 materialization
- Map migration/API entrypoint처럼 DB를 변경할 수 있는 one-shot process
- Pin API/Dagster/worker와 Map 또는 Pin DB에 쓰는 cache-target command 경로
- manager가 실행할 backup/migrate/CSV/bootstrap/initial/enable/canary/GC operation

fence는 writer capability registry와 실제 process/container/transaction을 대조한다. 알려지지 않은
writer나 새 write route가 registry 밖에 있으면 cutover가 시작되지 않는다.

## 7. 백업과 네트워크 없는 리허설

manager backup receipt는 Map app DB, Map Dagster DB, Pin DB, manager state/env/manifest를 하나의
transaction UUID로 결속한다. 각 DB의 identity, schema head, dump SHA-256, restore 검증 결과가
없으면 `backup_verified`가 될 수 없다. env 원문은 저장하지 않고 허용된 redacted digest만 쓴다.

구현 merge 뒤 최신 **writer-fenced prod dump**를 사용해 격리 clone 리허설을 한 번 수행한다.

1. prod 네트워크와 credential을 주입하지 않은 scratch pair에 결합 백업을 복원한다.
2. Map app DB를 `0063`에서 `0078`까지 올린다.
3. `3,265 → 3,043 → accepted 222/rejected 0 → 3,265`를 exact하게 재현한다.
4. `0075` preflight와 `0075`~`0078` schema/index/outbox/GC 검증을 모두 통과한다.
5. manager journal 중단 지점마다 같은 transaction UUID 재개와 stale receipt 거부를 검증한다.
6. 리허설 중 runtime restart와 외부 event가 모두 0임을 증명한다.

dump가 최신 writer-fenced identity가 아니거나 schema/transaction UUID가 receipt와 다르면 재사용하지
않는다. 리허설 성공은 prod 실행 승인이 아니다.

## 8. rollback과 forward 경계

### `forward_committed` 전

fence를 유지한 채 candidate runtime을 모두 내리고 다음을 하나의 manager 복원 transaction으로
되돌린다.

1. Map app DB
2. Map Dagster DB
3. Pin DB
4. manager state/env/manifest
5. 위 identity와 결속된 옛 image set을 **마지막에** recreate

DB만, image만, Map만, Pin만 되돌리는 부분 rollback은 금지한다. 복원 뒤에도 old daemon은 자동으로
시작하지 않는다. exact 이전 enablement와 writer registry를 검증한 뒤 별도 승인으로만 정상화한다.

### `forward_committed` 후

옛 backup receipt와 image set을 rollback 입력으로 거부한다. 문제는 새 forward transaction으로
수정한다. GC나 image prune은 canary와 exact release provenance 검증 전에는 실행할 수 없다.

## 9. 구현 분할과 merge barrier

이 문서 commit을 exact 공통 head로 삼아 Map Agent A/B가 병렬 작업할 수 있다.

- **Agent A — helper 구현 소유**: `scripts/h35/h35_cutover.py`와 helper 내부 typed request/receipt,
  다섯 operation, migration partial probe, CSV5 멱등성, 기존 client 기반 GC와 final DB evidence.
  runtime/orchestration 코드는 수정하지 않는다.
- **Agent B — 검증 소유**: helper black-box unit/integration test, writer registry 전수성 test,
  `0063→0078` scratch rehearsal harness와 mutation-zero matrix. Agent A 소유 파일을 수정하지 않는다.
- **Docker-manager worker — orchestration 소유**: one-process lock/journal, backup/restore,
  generation 7 bootstrap/enable/canary, final writer stop, stale receipt 차단, coupled release provenance.

Agent A/B는 이 문서의 receipt key·phase 순서·exact gate를 임의로 바꾸지 않는다. 계약 변경은 먼저
문서 PR에 반영하고 두 작업을 같은 exact head에 rebase한다. 구현·검증·manager 결합이 모두 끝난
최종 exact HEAD만 적대 리뷰어 1명이 검토하며, 그 전에는 리뷰를 요청하지 않는다.

## 10. 구현 완료 전 검증 행렬

| 시나리오 | 기대 결과 |
| --- | --- |
| 각 helper를 올바른 prior receipt로 최초 실행 | 해당 phase만 수행, runtime/external mutation 0 |
| 같은 request 재실행 | 동일 효과·멱등 receipt, 중복 row 0 |
| transaction UUID 또는 prior digest 불일치 | DB/runtime/external mutation 0으로 거부 |
| `0064`/`0068`/`0069` 각 partial checkpoint | 허용 shape만 forward 재개, 나머지 fail-close |
| `0070`~`0078` 중간 실패 | 해당 revision transaction rollback, 이전 head 보존 |
| CSV 5개 중 누락/변조/거부 1건 | accepted gate 실패, runtime 시작 0 |
| GC retry 또는 첫 attempt 중단 | 삭제 건수와 무관하게 final backlog·referenced·observation 상태로 수렴 |
| stale/mixed snapshot 또는 invalid Merkle | `verify` 거부, evidence 발급 0 |
| PinVi non-ready 또는 backlog 1건 이상 | `verify` 거부, HTTP/external event 0 |
| unfinished manager journal에서 다른 operation | 전부 mutation 0으로 거부 |
| pre-forward restore | DB 3종+state/env/manifest+old images 결합 복원 |
| post-forward old restore | mutation 0으로 거부 |
| production attestor/canary injection | 우회 불가, mutation 0으로 거부 |
| cache contract 미설정 기존 경로 | 현재 의미를 보존 |

## 11. 실행 승인 조건

- [ ] PR #923 이후 `origin/main`에 rebase되고 Map/Pin exact release가 고정됨
- [ ] Map Agent A/B 구현과 Docker-manager orchestration이 동일 receipt contract 사용
- [ ] 최신 writer-fenced dump clone의 network-free `0063→0078` 리허설 green
- [ ] 최종 exact HEAD 적대 리뷰 1건 green
- [ ] 모든 mutation-zero matrix green
- [ ] push 전 보안 감사와 CI green
- [ ] 사용자의 명시적 n150 실행 승인

체크 전에는 이 문서를 prod 명령서로 해석하지 않는다.
