# C3e canonical operation 영속화 설계

> 상태: 문서 gate·C3e-A1/A2/B1/B2/B3/C·C3e-I1 actual PostGIS 교차 회귀·C3e-I2 n150
> prod 일방향 전환과 live UI E2E 완료, #679 CLOSED
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

update request root도 owned import member의 실컬럼 exact pair만 사용한다.
`scope.type='provider_dataset'` direct pair는 linked typed job pair와 DB에서 항상 같고,
nullable `sync_scope` metadata만 보강한다. pair는 항상 non-null `operation_member_id`와 member
status를 가진다. provider/dataset 독립 배열에서 새 pair를 만들지 않는다.

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

- Dagster→DB: 공개 `get_run_records(cursor=run_id, ascending=True)`의 run storage insertion
  order(`storage_id`, `run_id`)를 최대 200개 page cursor로 사용해 등록 job의 missing root도
  ensure/reconcile한다. run 생성 transaction과 Dagster daemon/DB clock skew 상한을 함께 덮는
  300초 settled lag를 적용한다. insertion page SQL에는 `created_before`를 섞지 않고 ID 연속 page를
  읽은 뒤, Python에서 첫 unsettled `create_timestamp` 직전의 contiguous settled prefix만 처리·
  전진한다. 따라서 낮은 storage ID가 clock-ahead이고 높은 ID가 먼저 settled여도 낮은 ID를
  건너뛰지 않는다. 운영 중 과거 storage ID나 생성 시각을 인위적으로 삽입하는 writer는 금지하고,
  최초 non-empty cursor는 아래 maintenance drain에서만 설정한다. 빈 storage는 Python clock
  sentinel 대신 `null` insertion cursor를 유지한다. page의 모든 DB write가 commit된 뒤에만 명시
  sensor cursor를 갱신한다. process crash는 같은 page를 멱등 재생하고 DB 장애는 cursor를
  전진시키지 않는다. 따라서 run-status sensor 내부 event cursor가 side-effect 예외 뒤 전진해도
  유실되지 않는다.
- DB→Dagster: 이미 DB에 있는 queued/running feature root를 다시 읽어 active/terminal status를
  reconcile한다. Dagster가 unavailable/not-found면 base 상태를 유지하고 관측 오류만 남긴다.

두 sensor의 outer 평가 경계는 Dagster scan/lookup과 DB list/write 예외 원문 및 exception chain을
framework로 전파하지 않는다. `error_type`만 운영 로그에 남기고 양방향 cursor를 전진시키지 않아
DSN·credential 유출 없이 다음 tick에서 같은 page를 재시도한다.

non-empty run storage에서 sensor cursor가 `None`이면 자동 latest cutover하지 않고 unready로
fail-closed한다. 운영자가 maintenance drain에서 명시 cursor JSON을 설정해야 한다. 현재 insertion
cursor가 가리키는 Dagster run은 삭제·retention 대상에서 제외한다. anchor가 이미 삭제됐으면 sensor를
정지하고 maintenance drain 뒤 `dagster:null`로 bounded full audit를 시작하거나, 누락 분류를 끝낸
최신 surviving insertion cursor로 명시 재설정한 다음 readback 후 재개한다. sensor는 anchor의
존재와 `storage_id` exact 일치를 매 tick 확인하며, 불일치하면 양방향 cursor를 전진시키지 않는다.

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
reconcile_dagster_feature_run(*, dagster_run_id, trigger_kind, terminal_status,
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

신규 writer는 payload/event fallback을 만들지 않는다. pair가 없는 orchestration은
`enqueue_unpaired_import_job`/`start_unpaired_import_job`, exact pair 작업은 required
`ProviderDatasetOperationKey`를 받는 `enqueue_provider_dataset_import_job`/
`start_provider_dataset_import_job`만 사용한다. 네 함수 모두 reserved feature kind를 거부한다.
offline validate/load/reserve, MOIS bulk/incremental/closed, exact
`provider_dataset` feature-update member는 호출 시 canonical pair를 넘긴다. multi-scope update
request, batch aggregate root, consistency/MV child처럼 단일 pair가 아닌 작업은 NULL이다.
batch attach는 identity를 추론·덮어쓰지 않고 기존 child 실컬럼을 보존한다. event append는
항상 같은 INSERT 시점의 job 실컬럼 pair만 복사하며 호출자가 다른 non-NULL pair를 주면 atomic
equality predicate로 거부한다. stored pair가 NULL인 신규 job에 explicit event pair를 주는
event-only identity도 거부한다.

신규 feature-load root/child `created_at`은 sensor 처리 시각이 아니라 Dagster run record의
timezone-aware authoritative create timestamp다. child도 같은 값을 사용한다. STARTED/terminal을
늦게 reconcile해도 root와 아직 시작/종료 시각이 없는 child의 `started_at`/`finished_at`은
Dagster authoritative timestamp를 사용한다. wrapper가 이미 완료한 child의 pair 완료 시각은
덮지 않는다. DB 실제 기록 시각이 필요한 감사에는 `ops.system_log.created_at`을 쓰며
timeline은 engine create 시각으로 안정화한다. 필수 engine timestamp가 없거나 유효하지
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

`pipeline_repo`가 cycle-safe component, 양방향 1:1 canonical request root,
standalone partition 규칙을 유일하게 소유한다. request job은 parent/load batch 없는 root이고
같은 job의 다중 request와 nested request anchor는 DB가 거부한다. 다음 네 소비자는 동일 root
CTE와 exact pair projection을 사용한다.

- `GET /v1/ops/pipeline/overview`: 상태 count와 최근 24시간 failure를 raw import job 행이 아니라
  canonical root 단위로 집계한다.
- `GET /v1/ops/pipeline/executions`: 기존 keyset `(created_at DESC, id DESC, kind DESC)` 유지.
- `GET /v1/ops/datasets`: 공용 CTE 위에서 provider/dataset별 최신 root를 한 batch query로
  계산한다. paginated first page를 전체 dataset 최신값으로 오인하지 않는다.
- `GET /v1/ops/datasets/detail?provider=...&dataset_key=...`: exact pair query로
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
- exact `provider_datasets[]`의 non-null member id/status; 표시용
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
`depth DESC, created_at DESC, job_id DESC` 첫 행을 고르고 `operation_member_id`와 member
status를 쓴다. typed member가 없으면 pair도 없다. event-only 과거 job은 실행 root로는 보존하지만 pair가 없으므로
`provider_datasets=[]`이고 dataset latest에서는 제외한다.

모든 request scope는 `ops.is_valid_feature_update_scope`가 강제하는 여섯 canonical JSON
shape 중 하나이다. 필수/추가 키, JSON type, 문자열 trim·길이, 배열 크기,
좌표·반경·bbox 범위는 OpenAPI 입력과 같다. 저장 경계는 `match`/`scope_mode`
기본값을 채우고 nullable field의 JSON `null`을 제거한다. 0052 CHECK와 trigger가
`provider_dataset` scope pair와 linked job typed pair를 일치시키므로 direct scope는 독립
pair가 아니라 같은 pair의 target/`sync_scope` metadata다. 저장된 `providers[]`와
`dataset_keys[]`는 표시·단일축 필터용 배열이며 pair를 복원하지 않는다.
`update_policy`도 repository canonicalizer와 `ops.is_valid_feature_update_policy` CHECK가
같은 허용 키를 강제한다. `mode='refresh_existing'`와 boolean override 5개만 저장하며,
Python `None`은 키 생략으로 정규화하고 unknown key·JSON `null`·잘못된 타입은 거부한다.
`import_job_events.provider`/`dataset_key`는 감사 endpoint의 filter 메타데이터로만 남고 runtime
projection identity에는 사용하지 않는다.

## 5. 일방향 전환과 배포 preflight

호환 writer/read model은 두지 않는다. 새 Dagster가 migration보다 먼저 뜨면
`UndefinedColumn`으로 실행이 유실될 수 있으므로 다음 일방향 전환 순서를 고정한다.

1. API/admin launch maintenance를 켜고 schedules/sensors와 Dagster UI/manual/backfill ingress를
   막는다.
2. Dagster `QUEUED|STARTING|STARTED|CANCELING`과 DB active feature root/child가 모두 0일 때까지
   구 run을 소진한다.
3. 구 Dagster webserver, daemon, code location을 모두 정지한다.
4. API image를 먼저 배포해 migration 0051/0052와 typed-only reader를 적용한다.
5. column/CHECK/constraint trigger/index/Alembic single head를 검증하고 첫 backfill을 실행한다.
6. Dagster 전 구성을 새 image로 재기동하고 same-run/pair 멱등성, catalog identity,
   recent/timeline 일치를 확인한다.
7. 모든 tracking sensor가 RUNNING인지 확인하고 reconciliation cursor를 maintenance drain에서
   관측한 최신 run storage insertion cursor(빈 storage면 `null`)로 초기화한 뒤 첫 tick/page
   commit과 cursor readback을 확인한다. 300초 settled lag보다 긴 미완료 run 생성 transaction과
   daemon/DB clock skew가 없음을 함께 확인한다.
8. Dagster run retention/delete 정책에서 현재 insertion cursor anchor를 제외했는지 확인한다.
9. 구 writer 소진을 다시 확인하고 0051 backfill 결과와 아래 손실 분류를 기록한다.
10. API/Dagster readback 뒤 UI를 재기동하고 ingress/schedules를 재개한다.

0052는 첫 동작으로 `ops.import_jobs`, `ops.feature_update_requests`를 그 순서로
`ACCESS EXCLUSIVE` 잠근 뒤 immutable `ops.is_valid_feature_update_scope`, filter validator,
update policy validator를 생성하고 여섯 scope와 provider/dataset filter array 및 policy의 완전한 shape를 repair와 같은
transaction에서 점검한 뒤 두 filter를 JSONB에서 typed `TEXT[]`로 전환한다. malformed/persisted
dry-run이 있으면 migration이 request ID와 함께 중단하므로
scope/filter/policy를 정상화하거나 잘못 저장된 요청을 명시적으로 제거한 뒤 다시 적용한다. jobless 또는 linked
job kind/pair 불일치는 0052가 request별 canonical job을 만들어
재연결하고 이전 job ID를 audit payload에 보존하므로 데이터 삭제 대상이 아니다. 단, 해당 request/job에
cancellation marker 또는 frozen cancellation member가 있으면 동결 집합을 임의로 바꾸지 않고
request ID와 함께 중단하므로 기존 취소를 terminal로 정리한 뒤 재시도한다. request가
`running`이거나 source job의 양방향 parent/child connected component에 DB `queued|running` 또는
Dagster active raw status가 하나라도 있는 relink도 중단한다. maintenance drain 뒤 전체
branch lifecycle을 terminal로 정리해야 한다. persisted row의 `dry_run` 컬럼은 0052가
제거하며 실제 생성(201)과 미리보기(200)는 독립 HTTP endpoint다.

```sql
SELECT request_id, scope
FROM ops.feature_update_requests
WHERE dry_run
ORDER BY request_id;
```

scope shape는 구 DB에 validation 함수가 없으므로 수동 SQL로 일부만 느슨하게 재구현하지
않는다. migration이 함수 생성 뒤 전체 행을 검증하고, 실패 시 정확한 request ID를 출력한다.

0052 downgrade는 schema rollback이다. upgrade가 만든 canonical job과 request relink는 구 schema에서도
유효한 감사 데이터이므로 원래 nullable job ID로 역변환하거나 synthetic job을 삭제하지 않는다.
`migration_source_job_id`는 사후 추적용이며 자동 데이터 복원 지시자가 아니다.

0051 적용 뒤 typed pair가 남지 않은 event-only job을 다음 SQL로 분류한다. 결과의 job 수와
유효 pair 수를 배포 기록에 남긴다. `unexpected_exact_untyped`는 0이어야 하며, `multi_pair`,
`partial_or_invalid`, `linked_request_untyped`는 의도적으로 pair read model에서 제외한다. raw event와
global/job event timeline은 삭제하지 않는다.

```sql
WITH event_identity AS (
  SELECT
    event.job_id,
    count(*) FILTER (
      WHERE event.provider IS NOT NULL OR event.dataset_key IS NOT NULL
    ) AS identity_event_count,
    count(*) FILTER (
      WHERE event.provider IS NOT NULL
        AND event.dataset_key IS NOT NULL
        AND event.provider = btrim(event.provider)
        AND event.dataset_key = btrim(event.dataset_key)
        AND event.provider <> ''
        AND event.dataset_key <> ''
    ) AS valid_event_count,
    count(DISTINCT ROW(event.provider, event.dataset_key)) FILTER (
      WHERE event.provider IS NOT NULL
        AND event.dataset_key IS NOT NULL
        AND event.provider = btrim(event.provider)
        AND event.dataset_key = btrim(event.dataset_key)
        AND event.provider <> ''
        AND event.dataset_key <> ''
    ) AS valid_pair_count
  FROM ops.import_job_events AS event
  GROUP BY event.job_id
), request_links AS (
  SELECT request.job_id, count(*) AS request_count
  FROM ops.feature_update_requests AS request
  WHERE request.job_id IS NOT NULL
  GROUP BY request.job_id
), residual AS (
  SELECT
    job.job_id,
    coalesce(event.identity_event_count, 0) AS identity_event_count,
    coalesce(event.valid_event_count, 0) AS valid_event_count,
    coalesce(event.valid_pair_count, 0) AS valid_pair_count,
    coalesce(link.request_count, 0) AS request_count
  FROM ops.import_jobs AS job
  LEFT JOIN event_identity AS event ON event.job_id = job.job_id
  LEFT JOIN request_links AS link ON link.job_id = job.job_id
  WHERE job.provider IS NULL AND job.dataset_key IS NULL
)
SELECT
  CASE
    WHEN request_count > 0 AND identity_event_count > 0
      THEN 'linked_request_untyped'
    WHEN identity_event_count = 0 THEN 'no_event_identity'
    WHEN valid_event_count <> identity_event_count THEN 'partial_or_invalid'
    WHEN valid_pair_count > 1 THEN 'multi_pair'
    ELSE 'unexpected_exact_untyped'
  END AS category,
  count(*) AS job_count,
  sum(valid_pair_count) AS valid_pair_count
FROM residual
GROUP BY category
ORDER BY category;
```

rollback 호환성은 지원하지 않는다. 배포 중단 시 신규 launch를 막고 새 image의 schema와 writer를
그대로 유지한 채 원인을 수정해 재배포한다.

## 6. PR 단위 병렬 작업

문서 PR이 CI green으로 머지된 뒤 Agent A/B가 다음 순서로 진행한다.

| task/PR | 담당 | 범위 | 의존 |
|---------|------|------|------|
| `T-ADM-C3e-A1` | Agent A | 0051, model/jobs writer matrix, frozen repo/client types·method, 멱등 lifecycle, C3d run-backed queued 확장 | 문서 PR |
| `T-ADM-C3e-A2` | Agent A | 공용 pipeline root/exact-pair projection, overview canonical count/DTO 원자 전환, datasets batch query | C3e-A1 |
| `T-ADM-C3e-B1` | Agent B | immutable operation registry/version, exact selection·run identity tag, trigger 판정 | C3e-A1 |
| `T-ADM-C3e-B2` | Agent A | provider guard, public wrapper pair completion, MCST callback | C3e-B1 뒤 B3와 병렬 |
| `T-ADM-C3e-B3` | Agent B | active/terminal sensors, NOT_STARTED/MANAGED scan, 양방향 reconcile watermark | C3e-B1 뒤 B2와 병렬 |
| `T-ADM-C3e-C` | Agent A | 실제 DB/FastAPI datasets grid·detail과 pipeline REST의 canonical 동일성 통합 증거 | C3e-A2, B1과 병렬 |
| `T-ADM-C3e-I1` | Codex 통합 | 실제 PostGIS B2 wrapper→B3 terminal 교차 회귀, 두 적대 리뷰, 로컬 gate | A1/A2/B1/B2/B3/C |
| `T-ADM-C3e-I2` | Codex 통합 | n150 migration·sensor/cursor readback, 일정/수동/갱신/import 4종 동일-root 증거, #679 종료 | C3e-I1 |

복구 감사에서 C3e-B 고유 구현이 없음을 확인했으므로 B1과 C를 최신 main에서 먼저 병렬
작업한다. B1 병합 직후 B2/B3는 origin/main에 rebase하고 Dagster package 안에서도 wrapper와
sensor 소유 파일을 분리해 병렬 작업한다. 모든 branch는 착수, handoff, push 직전과 선행 PR
merge 직후 rebase 상태를 확인한다. C는 A2가 이미 완료한 production REST/OpenAPI를 중복
수정하지 않고 교차 통합 테스트만 소유한다.

### C3e-A2 구현 기록

`pipeline_repo`의 C3b cycle-safe lineage를 유일한 계보 정본으로 유지하면서 request branch와
standalone partition을 canonical root로 먼저 확정하고 exact pair를 별도 관계로 계산했다. 실컬럼
identity member는 `depth DESC, created_at DESC, job_id DESC`로 하나를 고르며 direct request
scope는 같은 typed pair의 `sync_scope` metadata만 보강한다. 표시 배열은 결정적으로 정렬하지만
pair filter에는 사용하지 않아 provider/dataset 교차곱을 차단한다. event는 감사 전용이며 이
projection에서 읽지 않는다.

executions, 단건 detail, overview, 모든 dataset latest batch와 dataset detail recent가 이 공용 CTE를
사용한다. feature run의 `projected_job`은 root 자체이고 pair child 상태는
`provider_datasets[]`만 소유한다. overview는 canonical root의 `operations_by_status`,
`active_operations`, `failed_operations_24h`로 원자 전환했다. pair/provider-only/dataset-only
필터는 identity access-path index를 대상으로 하는 EXPLAIN 회귀를 두었다. 1차 적대 리뷰 뒤에는
production caller가 사라진 request/job 조립 DTO·helper·query를 제거하고 1,005개 canonical root의
keyset 전수 순회, 모든 dataset latest, overview 합계가 누락 없이 일치하도록 고정했다. 또한
status/latest/detail raw SQL 각각에 EXPLAIN gate를 둔다. 최종 성능 리뷰에서는 선택 조회가 전체
graph를 먼저 투영하던 구조를 반려하고, typed/direct/request-array identity를 자연 planner의
index로 seed한 뒤 해당 connected component와 관련 request만 canonicalize하도록 분리했다.
production-like unrelated cardinality와 `ANALYZE`를 둔 gate는 selective pair/provider/dataset 및
UUID detail에서 base job/request `Seq Scan`과 과도한 actual row/loop를 차단하고 event relation
접근 자체를 금지한다.
2차 적대 리뷰에서는 request detail scalar가 array 첫 원소를 독립 선택해 가짜 pair를 만들 수 있던
경로와 request trigger 누락을 제거했다. scalar pair도 linked typed job에서만 읽고 non-exact
provider/dataset 배열은 root 표시·단일 필터에만 남긴다. 이후 DB-boundary 리뷰에서 event fallback과
jobless direct fallback을 모두 제거했다. 0052는 request job FK를 `NOT NULL/RESTRICT`로 바꾸고
jobless·scope 불일치·reserved Dagster kind row를 request별 canonical job으로 재연결한다. 6종
scope, typed provider/dataset `TEXT[]`, update policy의 exact canonical shape CHECK, canonical job kind/scope pair
교차검증 trigger, import kind/pair 불변 trigger가 typed job 단독 정본을 DB에서 강제한다.
persisted dry-run 컬럼은 제거하고 200 preview와 201 생성 endpoint를 분리한다.
relink 전에는 source의 양방향 connected component 전체에서 active/cancellation 상태를 fail-closed한다.
typed identity가 없는 event-only sibling은 root timeline에는 남지만 pair filter/latest에서 제외된다.
영향도 평가는 codegraph에서
`list_pipeline_executions` 19개, `PipelineExecution` 7개,
`list_latest_dataset_executions`·`DatasetLatestExecution` 각 11개,
`get_pipeline_status_counts` 9개, `PipelineStatusCounts` 12개, 상세의 `OpsImportJob` 34개 symbol을
확인했고 `PipelineOverviewData`의 직접 영향은 3개였다. 테스트·정적 gate는 사용자 계약에
따라 적대 리뷰 2회 반영 뒤 실행했다.

#### C3e-A2 로컬 gate 기록

과거 테스트 전 snapshot은 적대 리뷰를 통과했지만 이후 UI/DB clean-cut 변경으로 승인을
무효화했다. 최신 source·generated artifact를 두 리뷰어가 다시 승인하기 전에는 테스트를
최종 결과로 기록하지 않는다.

- admin UI의 구 `/admin/feature-update-requests` 목록·상세 redirect route는 clean-cut으로
  삭제하고 client 구현을 정본 `/admin/features/update-requests` route 내부로 이동했다.
- `feature_update_requests.job_id`는 unique FK이며 job INSERT/request DELETE deferred trigger가
  reverse orphan을 commit 시점에 차단한다. request의 `job_id`는 immutable이고 canonical job은
  parent/load batch가 없는 root다. generic writer는 reserved kind의 생성·일반 lifecycle을 거부한다.
  migration은 unlinked terminal component 전체에 명시적 격리 시각·사유를 기록하되 원래
  `kind`·`payload`를 보존하고, active/cancellation component에서는 fail-closed한다.
- 0052의 request→job FK는 SQLAlchemy naming convention이 실제 생성한
  `fk_feature_update_requests_job_id_import_jobs`를 upgrade/downgrade에서 동일하게 사용한다.
  새 CHECK 이름은 Alembic `op.f(...)`와 ORM `conv(...)`로 완성된 이름임을 표시해 convention의
  이중 prefix를 제거했다.
- migration fixture는 0051의 canonical unpaired root와 same-run typed pair child 불변식을
  만족한다. active relink preflight truth table은 source DB 상태, raw Dagster 상태, request
  cancellation, jobless request, child active 상태를 서로 다른 행으로 격리해 각 차단 조건을
  독립 검증한다.
- SQLAlchemy text SQL의 `:null` test bind 오해를 제거했다. direct-exact selective EXPLAIN은
  배경 seed 분포와 `ANALYZE`를 보강해 identity index access path가 실제 선택성을 갖는 조건에서
  검증되도록 했다.

과거 migration/repository/Python/API/Dagster/frontend/build/mocked Playwright 결과는 위 변경으로
모두 무효화했다. 최신 적대 리뷰 2인 승인 뒤 전체 gate를 재실행해 이 절을 실제 결과로 갱신한다.
live n150/prod는 C3e-I2/C7 최종 gate로 남긴다.

A2는 PR #705의 8개 CI gate green 뒤 main에 병합했고 `docs/tasks-done.md`로 이동했다.

### C3e-B2 구현·로컬 gate 기록

B2는 B1 immutable registry를 실제 provider 실행 경계에 연결했다. 모든 live provider resource는
provider I/O 전에 authoritative Dagster run record의 run id·job·resolved asset selection·run
config·canonical identity/version tag·trigger를 exact match로 검증한다. resource 초기화와 public
wrapper 양쪽에서 멱등 ensure를 수행해 초기화 뒤 취소 marker나 identity drift가 생겨도 fetch 전에
fail-closed한다. 각 public asset과 KMA wrapper는 raw 성공 뒤 자기 exact pair만 완료하고, 재시도
실패 event에는 redacted 오류만 남긴다.

MCST raw runner는 nullable async pair-completion callback으로 앞선 pair 성공을 보존하며,
`FeatureUpdateAssetRunner` direct 경로는 operation tracking을 만들지 않는다. 취소 marker 선점,
terminal·selection drift, naive Dagster timestamp는 child나 provider I/O 없이 typed conflict로
닫는다. KNPS 비기본 point/geometry dataset은 `settings.model_copy(update=...)`로 provider fetcher와
asset resource에 같은 snapshot을 전달하고 실제 `Definitions` 구성까지 회귀로 고정했다.

테스트 전에 두 적대 리뷰어의 지적을 모두 반영했고 최종 판정은 각각 S1/S2/S3 0건이다. focused
7개 파일 260건(1 skip), migration 0001→0052를 포함한 실제 PostGIS canonical operation 30건,
Dagster package 전체 428건(1 skip), main unit 1,366건을 통과했다. Ruff, strict mypy 136개 소스,
import 계약 4/4와 staged diff check도 통과했다. B2 wrapper 결과를 B3 sensor가 실제 terminal DB
상태로 닫는 교차 검증은 C3e-I1에서 완료했다. 일정·수동·갱신·import 4종 동일-root 증거와
이슈 #679 종결, n150/prod 검증은 `T-ADM-C3e-I2`에서 완료했다.

### C3e-I1 실제 PostGIS 교차 회귀·로컬 gate 기록

production 코드는 변경하지 않았다. 실제 migration 0001→0052를 적용한 PostGIS에서
`test_b2_single_wrapper_success_is_closed_by_b3_terminal_record`는 단일 provider wrapper 성공을
B3 SUCCESS record가 root/member 완료·진행률 100·engine 시각·수동 trigger를 보존하며 한 번만
닫는지 검증한다. `test_b2_mcst_partial_attempt_is_preserved_by_b3_failure_record`는 MCST 13개
exact pair의 identity·job·기존 완료 시각을 동결하고 active pair만 실패로 닫으며 redacted attempt
event의 identity·payload를 보존하고 raw 오류를 노출하지 않는지 검증한다.

적대 리뷰 2인이 명시적 manual seam, event identity, MCST 전체 pair freeze, 실패 cleanup을 보강한
최종 source를 다시 검토했고 각각 S1/S2/S3 0건으로 판정했다. focused 실제 PostGIS 32건,
`pytest -m 'not live'` 1,902건(5 deselected), Ruff, strict mypy 136개 소스, import 계약 4/4를
통과했다. raw 전체 실행은 로컬 외부 `kor-travel-geo` reverse endpoint가 HTTP 400을 반환해 live
5건이 실패했고 191건 통과 시점에 중단했으므로 not-live green과 명확히 분리한다. 이 로컬 외부
서비스 실패와 분리한 n150 migration·sensor/cursor·4종 동일-root·live UI 검증은 아래 C3e-I2에서
완료했다.

### C3e-I2 n150 prod 전환·live UI 기록

maintenance 전 pg_dump는 259,608,395 bytes이고 SHA-256은
`0c01693808a0cc94dcbe1dce9a04c5996364c642ac4fa3f1df77d87c08667167`이다. 취소된 두 Dagster
run에 연결된 legacy active request 1건을 감사 row 삭제 없이 terminal `cancelled`로 명시 정리한 뒤
0051/0052를 일방향 적용했다. Alembic single head, 0048 재수렴 `updated=0`, payload run identity
missing/mismatch 0, 0051 예상 밖 exact untyped 0을 확인했다. request validation/identity/duplicate,
quarantine marker, active canonical/raw Dagster feature run 불일치는 모두 0이다.

새 Dagster webserver/daemon을 각각 재빌드하고 tracking sensor 8개와 update queue/failure sensor
2개를 모두 RUNNING으로 복원했다. reconciliation insertion cursor는 maintenance anchor
`storage_id=5160`에서 `5175`로 전진했고 최근 5개 tick은 panel-only/DB observation error 0으로
끝났다. run retention/delete 정책은 구성되어 있지 않다. schedule은 배포 전 snapshot과 같은
34 RUNNING·3 STOPPED다.

admin manual KMA nowcast, 자연 schedule KREX traffic notices, feature update KMA nowcast,
standalone MOIS incremental import를 실제 실행해 모두 terminal로 닫았다. 각 실행은 datasets 상세와
pipeline 상세의 `execution/root(kind,id)`가 정확히 일치했다. 공식 Playwright 1.60.0 컨테이너와
worker 1로 provider consistency 112건, Dagster round-trip 4건, feature update 8건, offline upload
6건, import action 3건, home dashboard 5건을 통과했다. heavy direct launch와 queued standalone
cancel은 전제 미충족으로 각각 skip했다. 최종 합계는 138 passed·2 skipped이며 로그인 POST 200와
Set-Cookie, 오답 비밀번호 401도 확인했다. 전체 증거를 이슈 #679에 기록하고 완료로 닫았다.

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
- 6종 malformed scope·provider/dataset filter shape·persisted dry-run·reserved Dagster kind의
  active/cancellation relink는 0052 preflight/migration에서 request ID와 함께 차단되고,
  terminal reserved kind는 canonical job으로 repair되며 Python/DB whitespace canonicalization이 일치
- whitespace legacy event는 valid sibling pair를 오염시키거나 자체 pair가 되지 않음
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
