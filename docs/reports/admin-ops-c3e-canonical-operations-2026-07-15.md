# C3e canonical operation 영속화 설계

> 상태: 문서 gate PR #696 병합, C3e-A1 구현·로컬 검증 완료, PR/CI 대기
> 범위: T-ADM-C3e, 이슈 #679, ADR-064
> 선행: PR #689(C3b root projection), PR #695(C3d 계층 취소)

## 1. 목표와 복구 결과

schedule, manual, sensor, backfill, update request로 시작한 provider 작업을
`/ops/pipeline`과 `/ops/datasets`가 같은 DB operation으로 조회하게 한다. Dagster
GraphQL 응답은 실행 엔진의 보조 관측값일 뿐 목록 cursor나 correlation 정본이 아니다.

Claude Code worktree와 branch, stash, reflog를 조사했으나 C3e 구현 diff는 없었다. 남은
산출물은 설계 기록뿐이므로 코드를 가져온 것으로 오인하지 않고, 그 기록을 C3d가 머지된
현재 스키마와 두 명의 적대적 리뷰 결과에 맞춰 다시 고정한다.

## 2. 닫힌 결정

### 2.1 제3 operation 테이블을 만들지 않는다

operation root는 다음 두 종류뿐이다.

- `update_request`: `ops.feature_update_requests.request_id`가 root다. 연결된 import job은
  실행 상태를 보조하는 member이며 별도 root로 중복 표시하지 않는다.
- `import_job`: request가 소유하지 않는 `ops.import_jobs.job_id`가 standalone root다.
  Dagster provider asset은 이 테이블에 `kind='provider_feature_load_run'`인 root와
  `kind='provider_feature_load'`인 pair child를 남긴다.

공통 correlation key는 `(kind, id)`다. `id`는 각 root의 기존 UUID PK이므로
`correlation_id` 복제 컬럼을 추가하지 않는다. `dagster_run_id`는 nullable 실행 엔진
속성이며 PK, cursor, 단독 correlation id로 사용하지 않는다. 단, 아래
`provider_feature_load_run` root의 실행 멱등키에는 partial unique로 사용한다.

### 2.2 exact provider/dataset pair가 identity 정본이다

`ops.import_jobs`에는 다음 nullable 실컬럼을 추가한다.

| 컬럼 | 계약 |
|------|------|
| `provider` | 단일 dataset operation의 canonical provider. 빈 문자열 금지 |
| `dataset_key` | 단일 dataset operation의 canonical dataset. 빈 문자열 금지 |
| `trigger_kind` | `schedule\|manual\|sensor\|update_request\|backfill\|system`; actor가 아니며 legacy unknown은 `NULL` |
| `operation_registry_version` | feature-load run identity registry version. 신규 run root만 non-NULL |
| `dagster_run_status` | raw Dagster run status. feature-load root만 nullable non-NULL이며 terminal 뒤 불변 |

`provider`와 `dataset_key`는 둘 다 non-NULL이거나 둘 다 NULL이어야 한다. 단일
`sync_scope` 컬럼은 추가하지 않는다. requested/effective scope와 active request 멱등성은
이슈 #686/T-ADM-C45X의 소유 범위이며, C3e의 dataset coverage는 provider/dataset 수준이다.

Dagster run 하나는 `kind='provider_feature_load_run'`인 standalone root 한 건이다. 선택된
exact pair마다 `kind='provider_feature_load'`인 child를 만들고 `parent_job_id`로 run root에
연결한다. root는 provider/dataset이 NULL이고 child는 두 값이 모두 non-NULL이다. 같은 run을
공유하는 MCST 13종이나 임의 multi-asset manual 실행도 pipeline에는 root 하나로 접히며,
datasets는 같은 root의 pair child를 조회한다.

root 멱등키는 `dagster_run_id`, child 멱등키는
`(parent_job_id, provider, dataset_key)`다. 각각 신규 kind에만 적용하는 partial unique index와
`INSERT ... ON CONFLICT`로 동시 진입과 step retry가 같은 행을 돌려준다. `dagster_run_id`를
모든 import job에 적용하는 전역 unique는 금지한다.

child와 parent의 kind/trimmed non-empty `dagster_run_id`/`created_at` 일치는
`provider_feature_load`에만 적용하는 deferrable
constraint trigger로 강제한다. generic batch hierarchy는 parent/child가 서로 다른 run일 수 있어
전역 composite FK를 쓰지 않는다. root `trigger_kind`, registry version, terminal/marker 상태는
ensure가 lineage lock 안에서 검증한다. parent가
`provider_feature_load_run`이 아니거나 run/trigger/selection이 다르거나 terminal/marked root에
child를 붙이려 하면 부분 mutation 없이 `FEATURE_OPERATION_INVARIANT_CONFLICT`로 실패하고 별도
짧은 transaction의 `ops.system_log`에 redacted conflict를 남긴다.

standalone hierarchy가 여러 identity를 포함할 수 있으므로 read model은 exact
`provider_datasets[]` pair relation을 보존한다. 각 항목은 `provider`, `dataset_key`, 선택된
import job member의 `operation_member_id`, pair `status`를 가진다. root `status`는 run 전체
lifecycle이고 child
`status`는 해당 pair 결과이므로 서로 덮어쓰지 않는다. 기존 `providers[]`와
`dataset_keys[]`는 검색·표시용 독립 배열일 뿐 pair를 복원하는 데 쓰지 않는다. 배열의
cross-product는 어떤 API와 SQL에서도 만들지 않는다.

update request root는 owned import child의 실컬럼 exact pair를 우선하고,
`scope.type='provider_dataset'` direct pair를 fallback으로 보완한다. 같은 pair가 둘 다 있으면
child 한 항목으로 접고, fallback 항목은 `operation_member_id=NULL`과 request root status를
사용한다. provider/dataset 독립 배열에서 새 pair를 만들지 않는다.

이 계층은 C3d 취소 경계이기도 하다. 같은 Dagster run의 pair 하나에서 취소를 시작해도
canonical root와 모든 child가 frozen scope에 포함되고 run terminate는 한 번만 호출된다.
dataset 한 개만 골라 공유 run의 나머지 pair를 살려 두는 부분 취소는 지원하지 않는다.

### 2.3 payload와 Dagster tag를 identity 정본으로 쓰지 않는다

신규 asset wrapper는 provider 모듈의 canonical 상수와 runtime dataset resource를
사용한다. payload의 `provider`, `dataset_key`, `request_id`를 operation identity나 계보에
사용하지 않는다. schedule/run tag는 pre-resource failure 복구용으로 같은 정본 registry에서
생성한 exact pair만 허용하며, 임의 tag를 신뢰해 row를 만들지 않는다.

현재 schedule spec의 `opinet`, `krex`, `krheritage`, `mois`, `knps` alias와 KNPS placeholder
dataset은 canonical catalog identity가 아니다. C3e에서 provider 상수/runtime resource와
정렬하고, 전체 feature-load spec의 exact pair가 catalog에 존재하는지 전수 테스트한다.
MCST처럼 한 asset이 여러 dataset을 다루면 registry에 pair 목록을 명시하고 하나의 run
root 아래 pair child를 만든다. asset selection을 권위 있게 exact pair로 복구할 수 없는
임의 user-code job은 DB canonical coverage 대상이 아니며 Dagster 보조 패널에만 남긴다.
반대로 registry에 등록된 feature-load job/asset selection은 registry version, resolved snapshot,
run config 또는 identity tag가 누락·불일치하면 임의 작업으로 강등하지 않는다. guard가 provider
resource factory보다 먼저 typed error로 fail-closed하고 provider I/O와 DB load가 모두 0임을
보장하며 redacted durable conflict를 남긴다.

identity registry는 immutable `registry_version`과 Dagster job/asset selection을 key로 한다.
일반 asset은 static exact pair, data.go.kr fileData job은 job별 고정 run config pair, MCST는
고정 13 pair, KNPS는 launch 시 허용 catalog 안에서 해석한 settings/run-config dataset snapshot을
사용한다. launch code는 registry version과 해석된 비민감 identity snapshot을 run tag에
넣고 sensor는 job/selection, run config/settings snapshot, registry version이 서로 일치할 때만
신뢰한다. 임의 tag 단독 값은 거부한다. sensor는 provider resource를 초기화하지 않고 DB와
Dagster run record만 사용하므로 원래 resource init 실패를 반복하지 않는다.

### 2.4 wrapper만 tracking을 소유한다

tracking은 decorated public Dagster asset wrapper에서만 수행한다. `_load`,
`run_feature_*`, client loader, `_record_feature_sync_success`에는 넣지 않는다.
`FeatureUpdateAssetRunner`는 raw `run_feature_*`를 직접 호출하므로 이 경계를 지켜야 기존
`update_request` root와 별도의 standalone root가 생기지 않는다. `assets.py`뿐 아니라
KMA와 MCST를 포함해 `FEATURE_LOAD_SCHEDULE_SPECS`가 가리키는 모든 asset을 전수 적용한다.

MCST는 public wrapper 하나가 13 pair를 순차 처리하므로 raw runner에 DB tracker를 넣지 않고
wrapper가 nullable `on_pair_done(provider, dataset_key)` async callback을 주입한다. raw runner는
빈 row를 정상 확인한 pair와 `_load`가 성공한 pair 직후 callback을 호출하고, callback을 주지
않은 `FeatureUpdateAssetRunner` 경로는 tracking side effect가 0이다. 후반 pair가 최종 실패해도
앞에서 완료 callback이 commit된 child는 `done`을 유지하고 아직 완료되지 않은 child만 최종
run 상태를 따른다. future multi-pair asset도 같은 wrapper-owned callback 경계를 사용한다.

`trigger_kind` 판정은 신뢰도가 높은 명시 신호부터 적용한다.

1. feature update request tag → `update_request`(단, raw runner는 wrapper를 우회)
2. admin manual tag 또는 명시 manual launch → `manual`
3. Dagster schedule name/tag → `schedule`
4. Dagster sensor name/tag → `sensor`
5. Dagster backfill id/tag → `backfill`
6. 명시 internal system 실행 → `system`

registry에 등록된 feature-load job인데 automation/backfill tag가 없으면 Dagster UI/CLI manual
launch로 판정한다. job/selection 자체가 registry에 없으면 absence를 manual로 추측하지 않는다.

job definition에는 provider/dataset identity tag만 넣고 schedule trigger tag를 넣지 않는다.
schedule, manual launch, sensor가 각 실행을 만들 때 trigger tag를 별도로 넣어 manual 실행을
schedule로 오분류하지 않는다. 빈 값과 알 수 없는 값은 거부한다. legacy row는 거짓
`system`으로 채우지 않고 NULL을 유지한다.

### 2.5 retry와 failure의 최종 소유자를 분리한다

event-backed `QUEUED|STARTING|STARTED|CANCELING` 각각의 run-status sensor 집합이 권위 있는
selection 전체 root/child ensure의 1차 소유자다. 각 sensor는
`monitor_all_code_locations=True`로 registry에 등록된
모든 feature-load job을 감시하고 QUEUED/STARTING은 DB `queued`, STARTED/CANCELING은
`running`으로 관측·전이한다. Dagster event mapping이 없는 `NOT_STARTED|MANAGED`는 run-status
sensor로 가장하지 않고 periodic scan과 guard가 queued-like observed status로 처리한다.
비등록 임의 user-code job이라 identity를 확정할 수 없으면 DB row를 만들지 않고 보조
패널-only conflict를 남긴다. 등록 job/selection의 registry identity가 누락·불일치하면 canonical
작업으로 가장하지 않는 동시에 guard에서 fail-closed로 실행을 중단한다. 모든 live
provider record resource는 가벼운 DB-only `feature_operation_guard` resource에 의존하며, 이
guard가 provider resource factory보다 먼저 같은 ensure/marker 검사를 수행한다. 따라서 marker가
먼저면 provider resource/fetcher I/O가 시작되지 않는다. wrapper ensure는 raw runner 호출
직전의 마지막 멱등 fallback이다. C3d와 같은 lineage-global→canonical root lock 순서를 쓰고
root marker가 있으면 새 child를 붙이지 않는다. multi-asset wrapper가 동시에 진입해도 첫
transaction이 selection pair 전체를 만들고 나머지는 같은 행을 읽는다. 성공한 자기 pair
child만 `done`으로 끝낸다. asset body exception은 child event를 남기되 root나 child를 즉시
`failed`로 바꾸지 않는다. 같은 Dagster run의 step retry가 같은 running child를 재사용하고
최종 성공으로 `done`을 기록할 수 있어야 하기 때문이다.

run root의 terminal 전이는 feature-load 전용 `run_status_sensor`가 소유한다. success sensor는
registry selection과 DB child set이 정확히 같고 모든 child가 wrapper/callback으로 이미
`done`일 때 root만 `done`으로 끝낸다. running/missing child를 성공으로 승격하지 않는다.
child set 자체가 다르면 새 child를 보정 생성하지 않고 structural conflict를 기록하되, 이미
terminal인 Dagster run 아래 active root와 알려진 active child는 한 transaction에서
`tracking_invariant` failed로 닫아 영구 active 상태를 남기지 않는다. set은 같아도 child가 하나라도
`done`이 아니면 같은 invariant failure로 active root/child를 닫고, 이미 `failed|cancelled`인 terminal
child는 덮어쓰지 않으며 raw Dagster `SUCCESS`는 별도로 보존한다. failure
sensor는 아래 규칙으로 남은 행과 root를 `failed`로
끝낸다. Dagster UI/CLI에서
직접 중단해 C3d marker가 없는 `CANCELED` run은 row가 없으면 authoritative selection을 먼저
ensure하고 active `queued|running` child와 root를 `cancelled`로 CAS 전이한다.
C3d marker가 하나라도 있으면 coordinator가 정본이므로 sensor는 어떤 base 상태도 덮지 않는다.

pair child는 queued/running에서 `progress=0`, 성공하면 `progress=100`이다. root progress는 매
pair 완료와 terminal reconcile transaction에서 `floor(100 * done_child_count / total_child_count)`로
다시 계산한다. 정확한 `SUCCESS`는 100이고 partial failure/cancel은 이미 완료한 pair 비율을
보존한다. `current_stage`는 `queued|loading|completed|failed|cancelled|tracking_invariant`의 고정
어휘를 사용한다. failure/cancel reconcile은 root와 대상 active child의 redacted error/stage 및
authoritative finish time을 함께 기록한다.

- 같은 run의 기존 active `queued|running` root/child만 `failed`로 CAS 전이한다.
- wrapper body 전 resource 초기화가 실패해 row가 없으면 static operation registry/selection이
  제공하는 canonical selection 전체 pair로 root/child를 한 transaction에서 ensure한다.
- 같은 run의 `done`, `failed`, `cancelled` 행과 cancellation marker가 있는 행은 덮지 않는다.
- 같은 run에서 일부 child가 done이고 일부가 queued/running이면 active child와 root만 failed로
  끝낸다.
- sensor 중복 전달은 같은 결과를 반환하고 쌍둥이 row/event를 만들지 않는다.
- 비등록 임의 user-code selection에서 identity를 복구할 수 없으면 canonical DB 기록 성공으로
  가장하지 않고 Dagster 보조 패널-only 실행으로 남긴다. 등록 job/selection의 identity
  누락·불일치는 guard 단계에서 fail-closed로 막고 provider I/O/DB load를 시작하지 않는다.

`SUCCESS`를 `done`으로 닫는 조건은 authoritative registry selection과 DB child set이 정확히
같고 root run/trigger/registry version 불변식도 일치할 때뿐이다. 누락/추가/mismatch child가
있으면 root를 `done`으로 가장하지 않고 invariant conflict와 system log를 남기며, 존재하는
active root/child를 원자적으로 `tracking_invariant` failed로 닫는다. terminal
event delivery를 놓치거나 daemon이 재시작한 경우에는 주기적 provider-resource-free
reconciliation sensor가
두 방향으로 복구한다.

- Dagster→DB: 등록 job의 run을 `(engine_created_at, run_id)` total order watermark 뒤부터 page로
  읽어 missing root도 ensure/reconcile한다. page의 모든 DB write가 commit된 뒤에만 명시 sensor
  cursor를 갱신한다. process crash는 같은 page를 멱등 재생하고 DB 장애는 watermark를 전진시키지
  않는다. 따라서 run-status sensor 내부 event cursor가 side-effect 예외 뒤 전진해도 유실되지
  않는다.
- DB→Dagster: 이미 DB에 있는 queued/running feature root를 다시 읽어 active/terminal status를
  reconcile한다. Dagster가 unavailable/not-found면 base 상태를 유지하고 관측 오류만 남긴다.

generic
`recover_stale_running_jobs`는 두 feature-load kind를 항상 제외하므로 장시간 정상 run을
heartbeat 만료만으로 failed 처리하지 않는다.
`claim_next_import_job`도 두 kind를 제외해 generic queue worker가 Dagster-owned queued row를
집어가지 않는다. tracking/reconciliation sensor는 모두
`DefaultSensorStatus.RUNNING`으로 정의한다.

두 feature-load kind는 tracking client의 reserved kind다. generic enqueue/start뿐 아니라
`finish_import_job`, `heartbeat_import_job`, `cancel_import_job`, payload update, requeue,
batch/load-batch attach와 모든 generic lifecycle/progress/stage writer는 대상 kind를 fail-closed로
거부한다. 허용 예외는 append-only event/audit와 같은 cancellation id marker를 확인한 C3d terminal
writer뿐이다. A1은 `ops.import_jobs` direct-write SQL inventory를 전수해 이 우회를 막는다.

C3d frozen cancellation member에는 import job의 nullable `operation_kind`와
`requires_run_termination`을 저장한다. generic queued member는 이 값이 false라 기존처럼 DB-only
취소한다. 두 feature-load kind의 `queued + dagster_run_id non-NULL` member는 true인 run-backed
active로 분류해 generic queued 즉시 DB cancel 대상에서 제외한다. running+run-id와 동등하게
frozen run, reservation, pending/cancel_failed, unresolved retry 집합에 포함하고 같은 run을 한 번만
reserve/terminate한다. terminate 실패/응답 불명이면 base queued를 보존하고 attempt를 retryable로
끝내며, retry는 같은 frozen queued member를 복사하고 hierarchy를 다시 탐색하지 않는다.
authoritative `CANCELED`만 active base를 cancelled로 확정한다. QUEUED→STARTED 경쟁 뒤 `SUCCESS`가
관측되면 frozen provider pair의 `initial_status`가 전부 `done`일 때만 root를 done으로 닫는다. 하나라도
non-done이면 active root/child를 `tracking_invariant` failed로 닫고 기존 terminal child는 보존한다.
`FAILURE`는 active root/child만 failed로 닫고 이미 완료·실패·취소된 child를 덮지 않는다. C3e-A1은
이 C3d 상태기계와 불변식 검사를 함께 확장한다. C3d terminal writer는 같은 cancellation id marker CAS로 feature
member status와 child/root progress·stage·redacted error, run root의 `dagster_run_status`,
authoritative engine timestamps를 함께 갱신해 C3e sensor가 marker 때문에 blocked된 뒤 canonical
필드가 stale하게 남지 않게 한다. cancellation detail member는
nullable `operation_kind`와 `requires_run_termination`을 그대로 노출하며 OpenAPI/admin generated
type도 같은 PR에서 갱신한다.

STARTED/guard/wrapper ensure, pair done, attempt event, terminal reconcile은 모두 C3d marker
CAS와 direct-write SQL inventory 대상이다. cancel marker가 먼저면 ensure row/provider I/O가
0이고, ensure가 먼저면 selection child 전부가 frozen scope에 포함된다. 반대 lock 순서는
허용하지 않는다.

Dagster cancellation은 C3d coordinator와 base marker CAS가 우선한다. failure sensor가
취소된 operation을 새 failed standalone root로 부활시키면 안 된다.

### 2.6 Agent A/B frozen client 계약

C3e-A1이 다음 main-package immutable type과 `AsyncKorTravelMapClient` method를 먼저 머지한다.
repository 함수는 주입된 session에서 commit하지 않고, client method가 호출당 짧은 transaction
하나를 소유한다. provider I/O 중 transaction을 유지하지 않는다.

```python
DagsterFeatureRunStatus = Literal[
    "QUEUED", "NOT_STARTED", "MANAGED", "STARTING", "STARTED", "CANCELING",
    "SUCCESS", "FAILURE", "CANCELED",
]
ProviderDatasetOperationKey(provider: str, dataset_key: str)
DagsterFeatureOperationMember(job_id: str, pair: ProviderDatasetOperationKey,
                              status: ExecutionState)
DagsterFeatureOperation(root_job_id: str, dagster_run_id: str,
                        status: ExecutionState, dagster_run_status: DagsterFeatureRunStatus,
                        created_at: datetime, started_at: datetime | None,
                        finished_at: datetime | None,
                        trigger_kind: TriggerKind, registry_version: str,
                        members: tuple[DagsterFeatureOperationMember, ...])
DagsterFeatureOperationMutation(outcome: Literal["applied", "noop", "blocked"],
                                block_reason: Literal["cancellation", "terminal"] | None,
                                operation: DagsterFeatureOperation)
DagsterFeatureOperationPage(items: tuple[DagsterFeatureOperation, ...],
                            next_cursor: DagsterFeatureOperationCursor | None)

ensure_dagster_feature_operation(*, dagster_run_id, trigger_kind,
    selected_pairs, registry_version, engine_created_at, engine_started_at,
    observed_status
) -> DagsterFeatureOperationMutation
finish_dagster_feature_pair(*, dagster_run_id, pair) -> DagsterFeatureOperationMutation
append_dagster_feature_attempt_event(*, dagster_run_id, pair, attempt_number,
    outcome, error) -> ImportJobEvent
reconcile_dagster_feature_run(*, dagster_run_id, terminal_status,
    selected_pairs, registry_version, engine_created_at, engine_started_at,
    engine_finished_at, error
) -> DagsterFeatureOperationMutation
list_reconcilable_dagster_feature_runs(*, cursor, page_size
) -> DagsterFeatureOperationPage
```

`DagsterFeatureRunStatus`는 main package가 소유한 문자열 Literal이며 Dagster package를 import하지
않는다. 실행 엔진 enum 변환은 Dagster package 경계에서만 한다.

`observed_status`는 `QUEUED|NOT_STARTED|MANAGED|STARTING|STARTED|CANCELING`, `terminal_status`는
`SUCCESS|FAILURE|CANCELED`만 허용하고 `error`는 비밀을 제거한 구조체다.
이 전체 observed 집합을 run-status sensor 하나가 구독한다는 뜻은 아니다. event-backed status는
해당 sensor가, `NOT_STARTED|MANAGED`는 periodic scan/guard가 같은 client 계약으로 넘긴다.
ensure의 base 전이는 absent+queued-like→queued, absent/queued+STARTED/CANCELING→running뿐이다.
raw status도 queued-like→STARTED/CANCELING→terminal 방향으로만 전이하고 terminal 뒤에는
불변이다. 기존 running에 늦은 queued-like/STARTED는 `noop`이며 역전이하지 않는다. terminal은
`blocked(terminal)`, marker는 `blocked(cancellation)`이다.
ensure/reconcile은 pair를 정규화·정렬·중복 제거하고 빈 selection을 거부한다. 기존 root/child,
trigger, registry version, parent/run, marker, terminal 불변식이 다르면 ensure/attach 경로에서는 typed
`FeatureOperationInvariantConflict(code, dagster_run_id, root_job_id?)`를 던지고 부분 mutation을
남기지 않는다. terminal reconcile의 selection/identity mismatch는 active 상태를 방치하지 않고
known active root/child를 한 transaction에서 `tracking_invariant` failed로 닫은 mutation 결과와
durable conflict를 반환한다. 일치하는 marker/terminal root는 예외로 위장하지 않고
`outcome='blocked'`와
명시적 `block_reason`을 반환하며 새 child/provider I/O가 0이다. 이미 적용한 동일 write는
`noop`이다. `append_*_attempt_event`는 terminal 상태를 바꾸지 않는다. B는 A1 merge 뒤 이
계약을 compile target으로 쓰며 A2 projection과 병렬 진행한다.

reconcile 목록은 cancellation marker 없는 `queued|running` feature run root만
`(created_at ASC, root_job_id ASC)` keyset으로 최대 200개 반환한다. cursor는 두 값을 가진
immutable internal type이며 HTTP cursor가 아니다. page 끝의 `next_cursor=None`은 sweep 완료를
뜻하며 다음 tick은 beginning부터 다시 시작한다. 그러므로 이전 sweep에서 active였던 장기 run의
후속 terminal과 scan 도중 과거 `engine_created_at`으로 늦게 삽입된 root도 다음 sweep에서 다시
관측한다. B는 repository를 직접 import하지 않고 이 client method로 DB→Dagster scan을 구현한다.

## 3. migration 0051과 backfill

0051은 import job에 nullable `provider`, `dataset_key`, `trigger_kind`,
`operation_registry_version`, `dagster_run_status`, pair/trim/shape/timeline CHECK와 feature-kind 전용 parent/run constraint
trigger를 추가한다. cancellation member에는 nullable `operation_kind`와
`requires_run_termination BOOLEAN NOT NULL DEFAULT false`를 추가한다. true는 non-NULL run id이고
`initial_status='running'`이거나 (`initial_status='queued'`이고 두 feature-load operation kind 중
하나)일 때와 정확히 같다. 0051은 기존 import member의 operation kind와 running+run-id 사실을
백필하고 신규 snapshot writer가 값을 권위 있게 채운다. legacy kind가 빈 값·공백·trim 불일치면
identity를 고쳐 쓰지 않고 operation kind를 NULL로 남겨 진단 count를 기록한다. 기존 generic
`parent_job_id ON DELETE SET NULL` 계약은 바꾸지 않는다. import job index는 다음과 같다.

```sql
CREATE INDEX idx_import_jobs_provider_dataset_created
  ON ops.import_jobs (provider, dataset_key, created_at DESC, job_id DESC)
  WHERE provider IS NOT NULL AND dataset_key IS NOT NULL;

CREATE INDEX idx_import_jobs_dataset_created
  ON ops.import_jobs (dataset_key, created_at DESC, job_id DESC)
  WHERE dataset_key IS NOT NULL;

CREATE INDEX idx_import_jobs_provider_created
  ON ops.import_jobs (provider, created_at DESC, job_id DESC)
  WHERE provider IS NOT NULL;

CREATE UNIQUE INDEX uq_import_jobs_feature_run
  ON ops.import_jobs (dagster_run_id)
  WHERE kind = 'provider_feature_load_run'
    AND parent_job_id IS NULL
    AND dagster_run_id IS NOT NULL;

CREATE UNIQUE INDEX uq_import_jobs_feature_run_pair
  ON ops.import_jobs (parent_job_id, provider, dataset_key)
  WHERE kind = 'provider_feature_load'
    AND parent_job_id IS NOT NULL
    AND provider IS NOT NULL
    AND dataset_key IS NOT NULL;
```

`pipeline_cancellation_runs`에는 authoritative `engine_started_at`/`engine_finished_at`과 terminal
result 전용 순서 CHECK를 추가한다. crash resume는 이 두 값을 그대로 재사용하며 API detail/OpenAPI/admin
type에도 raw terminal status와 분리해 노출한다. 기존 run에는 권위 있는 Dagster 관측 시각 근거가
없으므로 두 시각을 추측해 백필하지 않고 NULL로 유지하며, 0051 이후 terminal observation만 실제
관측값을 채운다. identity 백필은 payload를 읽지 않는다.

- 연결 request 전체가 정확히 1건이고 그 행이 string·trimmed non-empty `provider_dataset` exact
  pair인 legacy job만 두 identity와 `trigger_kind='update_request'`를 채운다.
- request linkage가 없는 job의 identity-bearing event가 모두 complete·trimmed pair이고 distinct
  `(provider, dataset_key)`가 정확히 하나일 때만 두 identity 컬럼을 채운다. 양쪽 NULL event만
  비식별 event로 무시하며 partial/blank가 하나라도 섞이면 NULL을 유지한다.
- 연결 request가 하나라도 있으면 invalid/ambiguous/다른 scope를 event가 되살리지 못한다. event
  fallback은 request linkage 0건일 때만 허용한다.
- pair가 0개 또는 2개 이상이면 두 컬럼을 NULL로 남긴다. provider와 dataset을 따로
  집계해 가짜 조합을 만들지 않는다.
- provider만 또는 dataset만 확인되는 부분 identity는 둘 다 NULL로 정규화한다. payload
  scalar/nested 값은 identity 백필에 사용하지 않는다.
- 과거 schedule/manual Dagster run은 DB operation row 자체가 없으므로 복원할 수 없다.
  이 한계는 coverage에서 숨기지 않는다.
- 신뢰 가능한 실행 신호가 없는 legacy job의 `trigger_kind`는 NULL로 둔다.

신규 generic writer는 payload/event fallback을 만들지 않는다. `enqueue_import_job`과
`start_import_job`은 reserved feature kind를 거부하며, 다른 kind에는 optional typed
`provider_dataset`과 `trigger_kind`를 받고 둘을 실컬럼에
같이 쓴다. offline validate/load/reserve, MOIS bulk/incremental/closed, exact
`provider_dataset` feature-update member는 호출 시 canonical pair를 넘긴다. multi-scope update
request, batch aggregate root, consistency/MV child처럼 단일 pair가 아닌 작업은 NULL이다.
batch attach는 identity를 추론·덮어쓰지 않고 기존 child 실컬럼을 보존한다. event append는
기본적으로 job 실컬럼 pair를 상속하며 호출자가 다른 non-NULL pair를 주면 거부한다. stored pair가
NULL인 신규 job에 explicit event pair를 주는 event-only identity도 거부한다.

신규 feature-load root/child `created_at`은 sensor 처리 시각이 아니라 Dagster run record의
timezone-aware authoritative create timestamp다. child도 같은 값을 사용한다. STARTED/terminal을
늦게 reconcile해도 root와 아직 시작/종료 시각이 없는 child의 `started_at`/`finished_at`은
Dagster authoritative timestamp를 사용한다. wrapper가 이미 완료한 child의 pair 완료 시각은
덮지 않는다. DB 실제 기록 시각이 필요한 감사에는 `ops.system_log.created_at`을 쓰며
cursor/timeline은 engine create 시각으로 안정화한다. 필수 engine timestamp가 없거나 유효하지
않으면 canonical row를 만들지 않고 보조 conflict로 남긴다.

downgrade는 신규 index, feature constraint/identity trigger, cancellation member/import CHECK와
`ck_pipeline_cancellation_runs_engine_times`를 먼저 제거한 뒤 cancellation run의
`engine_started_at`/`engine_finished_at`, `operation_kind`/`requires_run_termination`, import 신규
컬럼을 제거한다. 이 필드가 필요한 감사 이력은 먼저 export한다. downgrade
전에 신 writer를 모두 중지하고 0051을 아는 migration image로 active feature root/child와 active
cancellation이 0인지 안전성 검사를 거친다는 운영 순서를 명시한다. old C3d가 해석하지 못하는
queued run-backed `cancel_failed` history가 하나라도 있으면 export/명시 정리 전 downgrade를
fail-closed한다.

## 4. 공용 root projection과 REST 계약

`pipeline_repo`가 C3b의 cycle-safe component, nearest request anchor, duplicate owner,
nested anchor, standalone partition 규칙을 유일하게 소유한다. 다음 네 소비자는 동일 root
CTE와 exact pair projection을 사용한다.

- `GET /v1/ops/pipeline/overview`: 상태 count와 최근 24시간 failure를 raw import job 행이 아니라
  canonical root 단위로 집계한다.
- `GET /v1/ops/pipeline/executions`: 기존 keyset `(created_at DESC, id DESC, kind DESC)` 유지.
- `GET /v1/ops/datasets`: 공용 CTE 위에서 provider/dataset별 최신 root를 한 batch query로
  계산한다. paginated first page를 전체 dataset 최신값으로 오인하지 않는다.
- `GET /v1/ops/datasets/{provider}/{dataset}`: provider+dataset filter로
  `list_pipeline_executions`를 호출해 최근 canonical root를 반환한다.

`dataset_status_repo`의 독자 recursive SQL과 payload `request_id` 계보는 제거한다. grid와
detail이 반환하는 `(kind, id)`, root status, projected job은 같은 시점의 pipeline timeline과
동일해야 한다. overview 전체 count는 timeline의 canonical root count와 같고 feature-load child
수만큼 부풀지 않는다. 기존 import/update 분리 count는 호환하지 않고 `operations_by_status`,
queued+running root 합계 `active_operations`, `failed_operations_24h` canonical root 집계로
교체한다. 기존 `active_import_jobs`/`active_update_requests`도 제거한다.

pipeline root/detail/projected job과 datasets latest/recent는 다음 정보를 같은 의미로 노출한다.

- stable `(kind, id)` correlation key와 `detail_url`
- root `status`와 별도 `projected_job.status/progress/current_stage`
- nullable `dagster_run_id`, raw `dagster_run_status`, `trigger_kind`, authoritative engine 시각
- feature-load root의 nullable `operation_registry_version`
- exact `provider_datasets[]`의 member id/status/status_source; 표시용
  `providers[]`/`dataset_keys[]`
- C3d cancellation overlay(있을 때)

datasets의 `latest_execution_coverage`와 `recent_runs_coverage` literal은
`db_recorded_canonical_operations`로 바꾼다. detail은 pipeline과 동일한 total order cursor를
`recent_runs_next_cursor`로 반환하고 전체 이력 `pipeline_history_url`도 제공한다. 이는 0051
이후 DB에 영속된 provider/dataset-level operation coverage를 뜻하며 과거 GraphQL-only
run이나 #686의 exact sync scope coverage를 주장하지 않는다.

`provider_feature_load_run`의 `projected_job`은 임의 pair child가 아니라 root 자체로 고정한다.
따라서 pair child insertion order나 UUID가 root의 status/progress/current_stage를 바꾸지 않는다.
pair별 상태는 `provider_datasets[]`만 정본이며 임의 child 하나를 run 대표로 선택하지 않는다.

root/base lifecycle은 `queued|running|done|failed|cancelled`, child pair lifecycle도 같은
어휘, C3d cancellation workflow/result와 raw Dagster status, freshness, `trigger_kind`는 각각
별도 필드로 유지한다. Dagster `SUCCESS`를 root `done` 대신 노출하거나 cancellation 결과로
base 상태를 덮지 않는다.

`provider_datasets[]`는 `(provider ASC, dataset_key ASC)`로 정렬한다. 같은 pair member가
여러 개면 canonical branch 안에서 실컬럼 identity가 있는 행만 대상으로
`depth DESC, created_at DESC, job_id DESC` 첫 행을 고른다. 이 member가 있으면
`status_source='member'`, `operation_member_id`와 member status를 쓴다. 없고 request direct
scope 또는 legacy exact event fallback만 있으면 `status_source='root'`, member id NULL,
canonical root status를 쓴다.

## 5. mixed-version 배포

새 Dagster가 migration보다 먼저 뜨면 `UndefinedColumn`으로 실행이 유실될 수 있으므로 다음
순서를 고정한다.

1. API/admin launch maintenance를 켜고 schedules/sensors와 Dagster UI/manual/backfill ingress를
   막는다.
2. Dagster `QUEUED|STARTING|STARTED|CANCELING`과 DB active feature root/child가 모두 0일 때까지
   구 run을 소진한다.
3. 구 Dagster webserver, daemon, code location을 모두 정지한다.
4. API image를 먼저 배포해 migration 0051과 mixed reader를 적용한다.
5. column/CHECK/constraint trigger/index/Alembic single head를 검증하고 첫 backfill을 실행한다.
6. Dagster 전 구성을 새 image로 재기동하고 same-run/pair 멱등성, catalog identity,
   recent/timeline 일치를 확인한다.
7. 모든 tracking sensor가 RUNNING인지 확인하고 reconciliation cursor를 maintenance cutover
   시각으로 명시 초기화한 뒤 첫 tick/page commit과 cursor readback을 확인한다.
8. 구 writer 소진을 다시 확인하고 backfill을 재실행한다.
9. API/Dagster readback 뒤 UI를 재기동하고 ingress/schedules를 재개한다.

구 writer가 만든 event-only row는 실컬럼 우선 + exact event pair fallback으로 읽는다. payload
fallback은 두지 않는다. quiesce 없이 생긴 pure Dagster run 누락 창을 정상 coverage로 간주하지
않는다. rollback은 신규 launch 차단 → 신 Dagster/API 모두 정지 → 0051을 아는 migration
image가 active feature root/child와 관련 `in_progress|retryable` cancellation 0을 fail-closed 확인 후
downgrade → 구 API → 구 Dagster 순서다.

## 6. PR 단위 병렬 작업

문서 PR이 CI green으로 머지된 뒤 Agent A/B가 다음 순서로 진행한다.

| task/PR | 담당 | 범위 | 의존 |
|---------|------|------|------|
| `T-ADM-C3e-A1` | Agent A | 0051, model/jobs writer matrix, frozen repo/client types·method, 멱등 lifecycle, C3d run-backed queued 확장 | 문서 PR |
| `T-ADM-C3e-A2` | Agent A | 공용 pipeline root/exact-pair projection, overview canonical count/DTO 원자 전환, datasets batch query | C3e-A1 |
| `T-ADM-C3e-B` | Agent B | Dagster registry/tag, QUEUED/STARTED ensure, guard/wrapper/callback, terminal/reconcile sensors | C3e-A1 뒤 A2와 병렬 |
| `T-ADM-C3e-C` | Agent A | datasets grid/detail canonical 소비, REST schema, OpenAPI/admin types | C3e-A2 |
| `T-ADM-C3e-I` | Codex 통합 | A1/A2/B/C rebase, 교차 회귀, 두 적대 리뷰, CI, #679 종료 | A1/A2/B/C |

Agent B는 A1에 고정한 interface를 기준으로 A2와 병렬 작업한다. A1 merge 직후 B/A2는
origin/main에 rebase한다. 모든 branch는 착수, handoff, push 직전과 선행 PR merge 직후 rebase
상태를 확인한다. 파일 소유는 A1이 migration/main infra와 cancellation API, A2가 공용
projection과 pipeline overview API/OpenAPI, B가 Dagster package, C가 datasets API/OpenAPI를
맡도록 분리해 병렬 edit 충돌을 최소화한다.

## 7. 구현 전 수용 테스트

- migration up/down/single head, exact-one-pair backfill, multi-pair 보류, blank 정규화,
  old-event/new-column 동시 가시성
- same run root 동시 ensure 2회가 root 1행, same pair 동시 ensure가 child 1행,
  same run/different pair가 root 1행+child 2행
- cancel marker 선점 시 QUEUED/STARTED/guard/wrapper/sensor ensure child 0·provider I/O 0,
  ensure 선점 시
  selection child 전부 frozen scope 포함, 반대 lock 순서 0
- feature-kind parent constraint trigger, parent kind/run/create-time/trigger/registry mismatch conflict,
  root/child identity update와 root-first delete 거부, terminal/marked root child attach 거부와
  durable system log
- STARTED→늦은 QUEUED/STARTING, terminal→QUEUED/STARTED와 duplicate delivery가 역전이 0
- first attempt throw→step retry success가 root 1개+child 1개 done, 최종 failure도 각 1개 failed
- resource-init pre-body failure와 failure sensor 중복 전달이 root 1개+pair별 child 1개 failed;
  등록 job identity drift는 fail-closed/provider I/O·DB load 0, 비등록 arbitrary job만 panel-only
- queued/pre-resource Dagster UI/CLI 직접 `CANCELED`도 selection ensure 후 cancelled,
  C3d marker 시 base mutation 0
- canonical API queued feature root 취소는 Dagster CANCELED·provider I/O 0·terminate 1회,
  terminate 실패는 base queued+retryable/cancel_failed 뒤 같은 frozen member retry,
  QUEUED→STARTED race의 SUCCESS는 frozen pair 전부 done일 때만 root done, 그 외 tracking invariant,
  FAILURE는 active root/child failed이며 generic queued job은 기존 DB-only 취소 유지
- MCST 전반 pair 성공·후반 pair 최종 실패에서 전반 child done, 나머지 failed
- `SUCCESS`에서 child set mismatch 또는 queued/running/failed/cancelled child를 done으로 승격하지
  않고 active root/known active child를 `tracking_invariant` failed로 닫되 기존 terminal child를
  보존해 active 잔존 0
- 장시간 run은 generic stale recovery 제외, missed terminal은 authoritative periodic reconcile
- raw Dagster status는 terminal 뒤 불변이고 C3d marker terminal도 같은 CAS로 갱신하며, late
  reconcile은 engine create/start/finish 시각을 복구하고 완료 pair child 시각은 보존
- feature-load queued row는 generic claim 제외, tracking sensor default RUNNING과 first-cursor
  readiness 뒤 launch 재개
- reserved feature root/child를 generic enqueue/start/finish/heartbeat/cancel/payload/requeue/attach
  writer가 바꾸려 하면 fail-closed하고 append-only event와 same-marker C3d terminal만 허용
- multi-asset/shared-run에서 pipeline root 1개, 취소 scope 전체 child 포함, terminate 1회
- `FeatureUpdateAssetRunner` direct 호출은 standalone tracking root 0개
- failure sensor가 terminal/cancellation marker를 덮지 않음
- 모든 schedule/asset operation registry pair가 canonical provider catalog에 존재
- 1,000개 이상 root에서도 dataset latest 누락이 없고 cycle/nested/duplicate owner가 pipeline과 동일
- provider+dataset filter가 같은 child exact pair만 매칭하며 독립 배열 cross-product가 없음
- feature run의 projected job은 root로 고정되어 pair insertion order/UUID에 무관하고 pair 상태는
  `provider_datasets[]`만 사용
- overview status count/active count/최근 24시간 failure가 canonical root 단위이며 timeline root
  count와 같고 pair child N배 부풀림이 없음
- child done=100, root progress는 완료 pair 비율이며 partial failure/cancel은 비율 보존,
  exact SUCCESS는 100과 안정된 stage 어휘
- dataset detail 최근 10개와 pipeline filter 결과의 id/status/pair status/projected job 일치,
  다음 cursor로 누락·중복 없이 이어짐
- pair/provider-only/dataset-only 조회 index EXPLAIN, OpenAPI admin/user drift, admin generated type drift
- offline/MOIS/exact update writer 실컬럼+event identity, multi/batch aggregate NULL, event mismatch 거부

## 8. C3e-A1 direct-write inventory

`ops.import_jobs`를 쓰는 runtime 경로를 SQL과 호출자 양쪽에서 전수했다. A1 이후 허용 소유자는
다음 표뿐이며, 신규 writer는 이 표에 identity와 cancellation 소유권을 먼저 추가해야 한다.

| writer | 허용 범위 | A1 경계 |
|--------|-----------|---------|
| `feature_operation_repo` | reserved run root/exact-pair child ensure, pair 완료, terminal reconcile | lineage-global→canonical root lock, marker/terminal/identity CAS |
| `jobs_repo` | generic enqueue/start/payload/run bind/batch attach/claim/lifecycle/stale recovery | reserved kind와 reserved parent/target를 typed conflict로 거부; exact pair·trigger는 실컬럼 기록 |
| `feature_update_repo` | update request 소유 generic job lifecycle/requeue | reserved target 사전 거부; exact `provider_dataset`만 실컬럼 pair, 그 외 aggregate는 NULL |
| offline upload/MOIS | validate/load/reserve 및 MOIS 3종 self-driven job | canonical pair와 `manual`/`system` trigger 명시, payload run-id 추론 금지 |
| `pipeline_cancellation_repo` | scope marker와 same-marker terminal CAS | queued run-backed feature member도 terminate/retry 대상으로 동결; generic queued만 DB-only cancel |
| Alembic | 0051 backfill/down safety check | request direct pair와 event exact-one-pair만 백필; payload 미사용 |

`batch_dag`의 root/consistency/MV aggregate는 단일 pair가 아니므로 identity를 NULL로 유지한다.
event append는 저장된 실컬럼 pair를 상속하고 다른 명시 pair를 거부한다. generic claim과 stale
recovery는 두 reserved kind를 제외한다. `rg` direct SQL inventory에서 위 소유자 외 runtime
`INSERT/UPDATE/DELETE ops.import_jobs`는 발견되지 않았다.

## 9. 금지사항

제3 operation 테이블, payload identity, `dagster_run_id` 단독 correlation, 모든 job 대상 전역
unique, 같은 run의 pair별 standalone root, wrapper 아래 `run_feature_*` tracking, body exception
즉시 failed, C3e 단일 `sync_scope`, paginated 목록으로 전 dataset latest 계산,
provider/dataset 독립 배열의 pair 추론을 금지한다.
