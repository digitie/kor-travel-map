# ADR-112 — reconcile sensor는 root가 생긴 run만 지나가고, 멈춤은 경과 시간으로 알리고, 정한 실패만 닫는다

- 상태: accepted (2026-10-21). O1은 2026-10-20, O2~O5는 2026-10-21 소유자가 권고대로 수락했다. 결정 0-1은 #1345로,
  결정 1~7은 같은 항목 `T-RECONCILE-RETRY`의 둘째 하위 단계로 구현했다(맨 아래 "구현 결과").
- 날짜: 2026-10-20 (같은 날 적대 리뷰 2회를 반영했다. 반영 내용은 맨 아래 "리뷰 반영" 절에 있다), 2026-10-21 수락·구현
- 결정자: Claude (소유자 수락 2026-10-20·21)
- 관계: ADR-111 결정 4(이 설계를 후속으로 넘겼다), ADR-107(공용 Dagster 런타임), ADR-021(forward-only)
- 설계 입력: PR #1319의 세 판과 그 리뷰(ADR-111 결정 4의 목록, journal 2026-10-13 ADR-111 항목). 마지막 판 코드는 커밋
  `6d0ebfc98`에 있고 `294f744f8`이 되돌렸다. 최종 리뷰의 L1~L4는 저장소 어디에도 내용이 적혀 있지 않아 대응 표에 넣지 못했다.

## 컨텍스트

`feature_operation_reconciliation_sensor`는 30초마다 두 쪽을 돈다.

- **Dagster page**: run storage를 insertion 순서로 훑는다. 300초 settle을 지난 Map run을 run마다 **한 번씩** 본다.
  이 page가 맡는 일은 "operation run마다 DB root가 있다"를 보장하는 것이다. 이미 끝난 run이면 terminal 반영도 한다.
- **DB page**: `queued`·`running`이면서 취소 marker도 quarantine도 없는 root를 keyset으로 훑는다(`_ACTIVE_ROOTS_PAGE_SQL`).
  끝까지 가면 처음으로 돌아간다. 이런 root는 몇 번이든 다시 집으므로, 이미 **내구성 있는 재시도 큐**가 있는 셈이다.
  취소 marker가 붙은 root는 이 page에 오지 않는다. 그 root는 취소 coordinator가 맡는다.

main의 동작은 이렇다. run 하나의 반영이 예외를 내면 tick 전체가 실패하고, 두 cursor가 제자리에 남고, 30초 뒤 같은 일을
다시 한다. 알림도, 닫는 경로도, tick 시간 상한도 없다. client의 `statement_timeout`은 600초이고 `lock_timeout`은 30초다.
2026-10-12에는 이 구조가 53200을 30초마다 되풀이했다. 원인은 406이 없앴으므로 급한 일은 아니다.

이 설계가 기대는 사실은 셋이다.

1. ensure와 terminal reconcile은 짧은 트랜잭션 두 개다. 둘 중 하나라도 mutation을 돌려주면 그 run의 root가 있다.
2. 위의 DB page sweep.
3. root 완결 `feature.finalize_provider_curation_root`를 부르는 곳은 둘이다. reconcile(`reconcile_dagster_feature_run` →
   `_finalize_authoritative_curation_root`)과 취소 coordinator(`ops.transition_provider_cancellation_job_command`, API의
   `transition_pipeline_cancellation_member`를 거친다)다.

## 결정

### 0. 구현 전제 — 큰 완결이 sensor tick 안에 들어가야 한다

> 2026-10-21 갱신: 이 전제는 결정 0-1(#1345)로 풀렸다. sensor tick 안에서는 더 이상 완결 CALL이 일어나지 않는다. 그래서
> 결정 2의 서버 쪽 상한은 sensor의 ensure·FAILURE/CANCELED reconcile·abandon·알림처럼 짧은 트랜잭션에만 걸리고, 완결은
> completion sweep run이 statement_timeout(600초) 아래에서 한다. 아래 본문은 결정 당시의 기록이다.

결정 2는 sensor 안에서 도는 완결 한 번에 서버 쪽 상한을 건다. 머리에서는 약 15초, DB page에서는 약 30초다.

main은 다르다. sensor 평가가 timeout으로 끝나도 서버의 완결은 최대 600초까지 돌아 commit될 수 있다. 이 설계에서는 상한에
닿으면 취소되고 sweep마다 다시 시도된다. 그 사이에도 시도할 때마다 `feature-curation-write`를 기다리며 잡는다.

그래서 **구현 전에 prod 완결 소요를 읽기 전용으로 잰다**(`pg_stat_statements`의 `CALL
feature.finalize_provider_curation_root` 평균·최대 등). 최대가 15초에 가깝게라도 나오면, 완결을 sensor 밖(run의 마지막
단계나 별도 job)으로 옮기는 항목부터 끝내고 이 설계를 구현한다. 이 전제가 서지 않으면 이 설계는 main보다 나쁘다(2차
리뷰 H1). → O1

### 0-1. O1 결론 — 완결은 별도 completion sweep run이 한다 (소유자 수락 2026-10-20)

실측(O1)이 조건에 해당해 소유자가 "완결을 sensor 밖으로 먼저"를 수락했다. 이 절은 그 하위 단계만 정한다. 결정 1~7은
여기서 구현하지 않는다(O2~O5 열림). 아래는 설계 적대 리뷰 1회를 반영한 판이다(절 끝 "0-1 리뷰 반영").

- **근거 하나 더.** kor-travel-common `address_dagster.py`(31행)의 원칙 "sensor 안에서 provider 호출·무거운 트랜잭션을
  하지 않는다"와 같은 방향이다.
- **어디서.** 별도 job `feature_operation_completion`(op 하나, config 없음). run 하나는 **sweep 한 번**이다. reconcile
  sensor의 DB page와 같은 목록(`list_reconcilable_dagster_feature_runs` — active, 취소 marker·quarantine 없음)을 끝까지
  한 번 훑고, Dagster run이 SUCCESS인 root마다 지금 sensor가 하던 terminal 반영(ensure → `reconcile_dagster_feature_run`, 그
  안의 SUCCESS 완결 CALL)을 **같은 함수로** 한다. 한 root의 실패는 다음 root를 막지 않고 run도 실패시키지 않는다(root마다
  error 로그와 output metadata `failed_run_ids`). 목록 조회 자체가 실패할 때만 run이 FAILURE다. repo·SQL·procedure·client는
  바꾸지 않는다. migration도, API·OpenAPI 변화도 없다.
- **sensor가 하는 일.** run-status sensor(success)와 reconcile sensor의 Dagster page는 SUCCESS run에 ensure만 한다(root가
  있게 하는 짧은 트랜잭션). reconcile sensor의 DB page는 SUCCESS인 active root에 아무 DB 호출도 하지 않는다(root는 이미
  있다). FAILURE·CANCELED는 지금처럼 sensor 안에서 reconcile한다 — 그 경로는 완결을 부르지 않는다(target이 `done`일 때만
  부른다). 그래서 sensor tick 안에서 완결 CALL이 일어나는 자리가 없다.
- **요청은 둘.**
  - 1차 — success sensor가 SUCCESS run마다 sweep 하나를 낸다(run_key `feature-operation-completion:success:<run>`).
    아직 step을 시작하지 않은 sweep(QUEUED·NOT_STARTED·MANAGED·STARTING)이 있으면 그 sweep이 이 root를 볼 것이므로 내지
    않는다. 이미 시작한 sweep은 이 root를 지나쳤을 수 있으므로 새로 낸다.
  - 뒷받침 — reconcile sensor의 DB page가 "Dagster SUCCESS인데 root가 active"를 하나라도 보면, 가장 최근 sweep이 진행 중이
    아니고 끝난 지 15분이 지났을 때 sweep 하나를 낸다(run_key `feature-operation-completion:backstop:after:<직전 sweep>`).
    "SUCCESS인데 active"가 곧 "완결이 없다"이므로 새 상태·열·표가 필요 없다. run이 끝난 뒤 완결 전에 무엇이 죽어도(sensor·
    code server 재시작, 놓친 이벤트, sweep의 실패·취소·프로세스 사망) root는 active로 남고 이 뒷받침이 다시 집는다.
- **직렬화.** op가 pool `kor_travel_map.feature_operation_completion`을 선언한다. `concurrency.pools.default_limit: 1`·
  `granularity: run`이므로 sweep은 인스턴스 전역에서 하나씩 돈다. 여분 요청은 QUEUED로 기다렸다가 할 일이 없으면 곧 끝난다.
  완결은 어차피 lineage advisory lock 하나로 직렬화되므로 동시에 여럿 돌려도 빨라지지 않는다. 이 직렬화는 기존 Map
  pool(`GEO_HEAVY_POOL` 등)과 같은 instance 설정에 기댄다. n150 공용 plane의 설정(Manager
  `config/dagster-shared/dagster.yaml`)을 2026-10-20 읽기 전용으로 확인했다: `pools.default_limit: 1`·`granularity: run`이고,
  전역 `max_concurrent_runs: 2`다. 그래서 pool을 기다리는 sweep은 QUEUED로 남아 슬롯을 먹지 않지만, 도는 sweep은 전역 슬롯
  둘 중 하나를 잠깐 쓴다. 그 설정이 없는 instance에서는 sweep이 겹칠 수 있다. 그래도 데이터는 안전하고, 겹친 쪽이 lock 대기나
  40001로 실패할 뿐이며 다음 sweep이 다시 집는다.
- **경쟁은 실패로 끝날 수 있다(무해하지만 조용하지는 않다).** SUCCESS reconcile은 SERIALIZABLE이다. 첫 문장(lineage lock
  대기) 시점에 snapshot을 잡으므로, 그 사이 다른 트랜잭션(취소 coordinator 등)이 root를 바꿨다면 `blocked/*`가 아니라
  40001로 끝난다. 데이터는 롤백되고 아무것도 쓰이지 않는다. root가 terminal이 되었거나 marker가 붙었으면 다음 sweep 목록에서
  빠지므로 다시 시도되지 않는다. sweep 둘이 겹치지 않는 것은 pool이 맡는다.
- **취소 coordinator.** 바꾸지 않는다. marker가 붙은 root는 목록에 오지 않으므로 sweep이 손대지 않는다. coordinator의
  `already_terminal`·SUCCESS 완결(API 트랜잭션 안)은 이 단계 밖이다. 다만 SUCCESS와 완결 사이 구간이 길어진 만큼 그 경로를
  타는 경우가 늘 수 있다.
- **"Dagster SUCCESS, 완결 없음" 구간.** 그동안 root는 `running`이다. `done`은 지금처럼 완결과 같은 트랜잭션에서만 생긴다.
  그래서 "root가 done이면 완결됐다"는 불변식이 그대로다. 대가는 지연이다. root가 done으로 보이기까지 run 큐 대기와 기동
  시간이 더해진다. 그 구간에 입력이 바뀌면 `stale_input`으로 끝날 가능성도 그만큼 는다(지금도 있는 경로다).
- **이 단계가 풀지 않는 것.** 완결은 여전히 lineage lock을 잡은 채 돈다. 큰 완결 동안 run 안의 member 완료·ensure·취소가
  그 lock을 기다리고 `lock_timeout`(30초)에 걸릴 수 있다. 이 단계가 없애는 것은 "sensor 평가 timeout 안에 완결을 끝내야
  한다"는 제약뿐이다. sweep도 대상 run의 manifest를 **지금** catalog로 다시 해석한다(sensor와 같다). 구간이 길어진 만큼
  catalog drift가 `tracking_invariant`로 끝나는 경우가 늘 수 있다.
- **SUCCESS ensure의 identity conflict.** client가 이미 `feature_operation.invariant_conflict` 행을 남긴다. conflict가 root를
  가리키면(`root_job_id`가 있다) sensor는 삼키고, sweep이 지금과 같은 reconcile로 `tracking_invariant`를 닫는다. root를
  가리키지 않는 conflict(quarantine 등)는 지금처럼 올린다 — 지금의 reconcile도 그 경우 같은 conflict로 끝났다. ensure가
  `blocked`를 돌려줘도 이유가 `terminal`일 때만 요청을 생략한다. ensure는 child marker로도 막히지만 reconcile은 root marker로만
  막히므로, child marker만 있는 root는 지금처럼 sweep이 완결한다.
- **고칠 수 없는 root.** sweep마다 그 root만 실패하고(error 로그), sweep run은 SUCCESS로 끝난다. 1차 요청은 SUCCESS run마다
  나가므로 그 root는 SUCCESS run 빈도로 다시 시도된다(뒷받침 15분은 SUCCESS run이 없을 때의 하한이다). root 하나가 FAILURE
  run을 쌓아 진짜 실패를 묻지 않게 하려고 run을 실패시키지 않았다. 멈춤 알림과 닫기는 결정 3·4(O2·O5)의 몫이다.
- **operation key 없는 run의 상태 이벤트.** 상태 sensor는 그런 run(sweep 자신 포함)에 `None`을 돌려준다. Dagster가 같은
  tick에서 다음 이벤트로 넘어가므로 sweep 이벤트가 success sensor의 tick을 하나씩 먹지 않는다.
- **sweep run의 성질.** `kor_travel_map.operation_key` tag를 달지 않는다. 그래서 두 sensor는 이 run을 `panel_only`로 본다.
  실행 상한은 1시간(`RecoveryPolicy`)이다. 넘기면 run monitoring이 슬롯을 돌려주고 남은 root는 다음 sweep이 집는다. 자동
  재시도는 두지 않는다.

기각한 자리는 넷이다.

- **run의 마지막 step.** Map operation run은 asset job 여럿에 MOIS 이어 달리기와 geo 릴리스 run까지 있고, asset 부분
  선택 실행도 있다. 그래서 모든 job에 마지막 step을 끼워야 한다. 게다가 step 안에서는 Dagster SUCCESS가 아직 없다. procedure가
  `dagster_run_status='SUCCESS'`를 요구하므로 migration으로 그 조건을 풀어야 하고, 그 step 뒤에 run이 실패하면 DB에 거짓
  `done/SUCCESS`가 남는다.
- **root를 먼저 done으로 두고 완결만 뒤로.** `done`의 뜻이 바뀐다. stale input이면 `done`이 `failed`로 뒤집혀 보인다.
  완결이 빠진 done root를 찾을 새 술어도 필요하다.
- **root마다 completion run 하나(대상 tag·run_key·동시 상한).** 초안이었다. run 수가 operation run 수만큼 늘고, 대상별 이력
  조회·재시도 규칙·동시 상한을 sensor가 들고 있어야 한다. 완결이 lock 하나로 직렬화되므로 동시 상한 2는 둘째 run을
  `lock_timeout` 실패로 만들 뿐이었다(리뷰 M1).
- **DB page만 요청.** DB page는 Dagster page 뒤에 돈다. Dagster page가 tick을 실패시키면(anchor 삭제 등) 모든 완결이 선다
  (리뷰 H1). success sensor를 1차 요청자로 두고 DB page는 뒷받침으로만 둔다.

#### 0-1 리뷰 반영 (2026-10-20, 설계 적대 리뷰 1회)

- H1 Dagster page 실패가 모든 완결을 세운다 → success sensor를 1차 요청자로 했다.
- H2 중복·coordinator 경쟁은 `blocked`가 아니라 40001로 끝난다 → 문구를 고치고, pool로 sweep 겹침을 없앴다.
- M1 동시 상한 2는 lock 대기 실패만 만든다, 대상별 기제는 과결박 → root별 run을 버리고 sweep 하나 + pool로 바꿨다.
- M2 고칠 수 없는 root가 5분마다 run을 띄운다 → 뒷받침 간격 15분, 알림은 결정 3 몫으로 적었다.
- M3 구간이 길어져 stale_input·coordinator 완결이 는다 → success sensor 1차 요청으로 구간을 줄이고 남는 위험을 적었다.
  `dagster/priority`는 넣지 않았다(필요하면 실측 뒤).
- M4 lineage lock은 그대로다 → "이 단계가 풀지 않는 것"에 적었다.
- M5 DB page가 SUCCESS root에 ensure를 되풀이해 conflict 행을 쌓는다 → DB page는 SUCCESS root에 DB 호출을 하지 않는다.
- L1 conflict를 다 삼키면 앞으로 생길 root 없는 conflict를 잃는다 → root를 가리키는 conflict만 삼킨다.
- L2 6시간 상한은 길다 → 1시간. L3 manifest 재해석 → 적었다. L4 대상 location 검사 → sweep은 DB 목록에서 대상을 고르므로
  해당 없음. L5 run_key는 sensor별로만 dedupe된다 → 두 요청자의 key 접두사를 나누고 겹침은 pool이 막는다. L6 daemon 재기동
  때 밀린 root → sweep 하나가 차례로 처리한다.

#### 0-1 코드 리뷰 반영 (2026-10-20, 적대 리뷰 2회)

- child marker만 있는 root가 1차 요청에서 빠졌다(ensure는 child marker로도 `blocked`) → `block_reason == "terminal"`일 때만
  생략한다.
- operation key 없는 run의 상태 이벤트가 SkipReason을 돌려 sensor tick을 하나씩 먹었다 → `None`을 돌려준다.
- 고칠 수 없는 root 하나가 SUCCESS run마다 FAILURE sweep을 쌓는다 → root 실패는 로그·metadata로 남기고 run은 SUCCESS.
- 시작 전에 취소된 sweep(`end_time` 없음)이 뒷받침을 영영 막는다 → 그때는 바로 낸다.
- sweep 목록 조회 오류 원문이 Dagster 로그에 남는다 → 오류 종류만 싣는다. `applied`만 완결로 센다. 뒷받침을 낼 때도 tick
  요약을 로그로 남긴다.
- 공용 plane의 pool 설정이 확인되지 않았다 → 읽기 전용으로 확인해 위 "직렬화"에 적었다.
- 한 tick에서 sweep 여럿을 낼 수 있다는 지적은, run-status sensor가 값을 돌려준 이벤트 하나에서 tick을 끝내므로 해당하지
  않는다(다른 리뷰가 Dagster 소스로 확인).

### 1. watermark가 run을 지나가는 규칙(잃지 않는다)

Dagster watermark는 run R이 다음 셋 중 하나일 때만 R을 지나간다.

- (a) R에 operation key가 없다(panel-only). main과 같다.
- (b) **이번 tick이 끝났을 때 R의 root가 있다.** ensure·reconcile·닫기 중 어느 호출이든 R에 대해 mutation(`applied`·
  `noop`·`blocked/*`)을 돌려줬다는 뜻이다. root를 가리키는 identity conflict(`root_job_id`가 있다)도 그 root를 잠근 채
  읽은 결과이므로 같이 친다. 뒤따른 호출이 실패해도 지나간다. active root는 DB page가 맡고, 취소 marker가
  붙은 root는 취소 coordinator가 맡는다. (0-1 뒤로 SUCCESS run의 Dagster page 반영은 ensure 하나뿐이다. 완결은
  completion sweep이 하고, 그동안 root는 active라 DB page와 sweep이 다시 집는다.)
- (c) 결정 4의 닫기가 R에 대한 내구성 있는 기록, 곧 `ops.system_log`의 `feature_operation.reconcile_abandoned` 한 행을
  commit했다.

셋 다 아니면 Dagster page는 **R에서 멈춘다.** watermark는 R 바로 앞 run에 남고, R이 머리(head)가 된다. run을 미뤄 두는
표가 없으므로 넘치는 일도 없다.

operation key가 있지만 관측 오류로 root를 만들 수 없는 run도 **머리 실패**로 다룬다. 관측 오류는 trigger를 해석할 수
없거나, catalog에 없거나, enabled membership이 없거나, timestamp가 없는 경우다. main은 이런 run을 Dagster 로그 한 줄만
남기고 바로 지나간다. 이 설계는 이런 run이 catalog 설정이나 배포로 고쳐질 수 있다고 보고, 같은 15분 시계를 다 탄 뒤에야
(c)로 닫는다. 머리는 한 번에 하나뿐이므로 `reconcile_abandoned` 행은 15분에 한 행을 넘지 않는다.

Dagster run storage 읽기가 실패해도 머리 실패다. anchor가 사라졌거나, 순서가 어긋났거나, 읽기가 시간 안에 끝나지 않은
경우다. 이때 머리는 watermark 다음 자리이고, 시계의 key는 watermark run_id다. 이 실패는 닫지 않는다.

DB page에서는 항목 하나가 실패하면 그 항목만 건너뛴다. 다음 sweep이 다시 집는다.

### 2. tick 시간 상한은 서버에서 건다

- **예산.** sensor 본문이 시작한 때부터 **고정 40초**다. Dagster의 평가 timeout은 60초이고, 남는 20초는 code server
  thread 대기와 resource 초기화 몫이다. 이 값을 환경 변수에서 끌어내지 않는다. 그 변수는 daemon 쪽에 있다.
  공용 plane에서는 모든 tenant의 sensor가 thread `num_workers: 4`를 나눠 쓴다(Manager
  `config/dagster-shared/dagster.yaml` 154·157행). 긴 tick 하나가 다른 tenant의 sensor를 막으므로 상한이 짧아야 한다.
- **page별 마감.** Dagster page는 시작 + 20초, DB page는 시작 + 40초에 마감한다. 호출 하나의 상한은 **그 page의 마감**까지
  남은 시간이다. 남은 시간이 5초보다 적으면 새 호출을 시작하지 않는다.
- **서버 쪽 timeout.** sensor가 여는 DB 트랜잭션마다 `set_config('statement_timeout', 남은 − 3초, true)`와
  `set_config('lock_timeout', min(30초, 남은 − 4초), true)`를 건다. SERIALIZABLE 트랜잭션에서는 **`SET TRANSACTION
  ISOLATION LEVEL` 바로 다음**에 건다. 그보다 먼저 쿼리를 보내면 25001이 난다. client가 같은 호출 안에서 따로 여는
  트랜잭션(invariant conflict 기록 등)에도 같은 값을 넘긴다. 시간이 넘으면 **Postgres가 statement를 취소**한다. client 쪽
  `asyncio.timeout`(남은 시간 + 3초)은 그 뒤를 받치는 보조 장치일 뿐이다.
- **Dagster run storage 읽기.** 동기 읽기는 계속 다시 쓰는 **worker 하나짜리 executor**에서 돈다. 앞 tick의 읽기가 아직
  그 worker를 잡고 있으면 이번 tick은 storage를 읽지 않고 storage 실패(머리 시계)로 센다. 그래서 thread가 쌓이지 않는다.
  다만 읽기 하나가 영영 돌아오지 않으면 code server를 재시작할 때까지 Dagster page가 선다. 그동안 머리 시계가 알린다.
- **cursor와 실패 횟수.** DB page가 일찍 멈추면 DB cursor는 **마지막으로 방문한 항목**에 둔다. DB page 목록 조회가
  실패하면 DB cursor는 그대로 두고 Dagster 쪽 진척은 commit한다(M2). tick당 실패 횟수 예산은 두지 않는다. 시간은 위
  상한이 묶고, 한 tick의 실패 로그만 3줄로 자른다.
- **return 전 commit.** 모든 분기에서 return 전에 `update_cursor`한다. `MapRunScopeMismatch`만 예외로 계속 FAILURE다.
  COMMIT 도중 시간이 끝나 결과를 모르면 실패로 다룬다. 다음 tick의 ensure가 멱등이라 결과는 그때 맞춰진다.

### 3. 멈춤은 경과 시간으로 알린다

횟수는 세지 않는다. 시계는 둘이고 둘 다 cursor에 있으며, 모양도 같다.

```
{run_id, first_failed_at, last_failure, alerted_at}
```

`last_failure`에는 SQLSTATE와 constraint 이름, 또는 예외 class가 들어가고, `gate_busy`·`lock_wait` 분류도 함께 담는다.
실패 서명이 번갈아 바뀌어도 run_id가 같으면 시계는 처음으로 돌아가지 않는다(H3).

- **`head`** — Dagster page의 머리다. 머리가 지나가면 지운다.
- **`db_watch`** — DB page에서 실패하는 root 가운데 **하나만** 지켜본다. 비어 있으면 그 tick에서 처음 실패한 root를
  잡는다. 다음 셋 중 하나가 되면 지운다.
  - 그 root가 성공했거나 닫혔다.
  - 매 tick 시작의 짧은 읽기에서 더는 active가 아니다. 판정은 `_ACTIVE_ROOTS_PAGE_SQL`과 같은 술어(active, 취소 marker
    없음, quarantine 없음)로 한다.
  - **닫을 수 없는 실패로 이미 알림을 냈다.** 이때는 슬롯을 다음에 실패한 root에게 넘긴다. 그래서 고칠 수 없는 root
    하나가 슬롯을 영영 잡지 못한다(2차 리뷰 H2).

  슬롯을 넘겨준 root와 슬롯에 들지 못한 root는 시계 없이 sweep마다 재시도만 한다. 넘겨준 root가 다시 슬롯을 잡으면
  시계가 처음부터 다시 돈다. 그래서 그런 root의 알림은 슬롯이 한 바퀴 돌 때마다 되풀이되고, 알림이 늦어질 수는 있어도
  사라지지는 않는다.

시계는 **처음 본 실패 시각**, 곧 실패한 호출이 돌아온 시각에서 시작한다. Dagster `end_time`은 쓰지 않는다. sensor가 멈춰
있었거나 DB가 내려가 있던 시간을 실패로 세지 않기 위해서다.

- **STALL_AFTER = 15분.** 실패 종류와 상관없이 같은 값이다. gate 바쁨, lock 대기 55P03, 53xxx, timeout이 모두 들어간다
  (B·H2). 그래서 55P03 같은 일시 실패도 15분 넘게 이어지면 알린다.
- **알림.** 시계가 15분을 넘었고, 그 시계의 `alerted_at`이 비었거나 한 시간 넘게 지났으면 `ops.system_log`에 한 행을 남기고
  `alerted_at`을 갱신한다.
  - 행 내용은 `level=error`, `source=feature_operation`, `event=feature_operation.reconcile_stalled`다. detail에는 시계,
    `last_failure`, 조치 문구를 담는다.
  - message는 **이벤트 이름으로 시작한다.** 그래야 admin 로그의 `q` 검색에 걸린다(B).
  - 시계마다 따로 줄이므로 서로 다른 멈춤이 서로의 알림을 늦추지 않는다.
  - 매 tick에는 `context.log.error` 요약만 남긴다. system log 쓰기가 실패해도 결정 1의 진행은 막지 않는다.
- **취소 marker가 붙은 root**는 이 sensor가 보지 않는다. 그 root가 멈췄을 때 알리는 일은 취소 coordinator의 몫이고, 이
  ADR의 범위 밖이다.

### 4. 정한 실패만 닫는다

**CLOSABLE**, 곧 닫을 수 있는 실패는 아래 목록뿐이다.

- SQLSTATE class `22`(data exception).
- `23502`(not null).
- `23514` 가운데 constraint가 다음 다섯 중 하나인 것.
  - `ck_tvn40_provider_curation_root`
  - `ck_tvn40_provider_curation_child_set`
  - `ck_tvn40_provider_curation_root_replay`
  - `ck_tvn40_provider_terminal_members`
  - `ck_tvn40_provider_terminal_receipts`

  다섯 모두 reconcile이 취소 root lock을 든 뒤에 내는 receipt·terminal 불일치라, 경합으로 생기는 실패가 아니다.
  `ck_tvn40_provider_operation_membership`("not active canonical scope")은 운영자가 dataset을 끄기만 해도 나므로
  **넣지 않는다**.
- `FeatureOperationInvariantConflict`(run identity·selection 불변식 위반).
- 결정 1의 operation key가 있는 관측 오류. 머리에서만 해당한다.
- `db_watch` root의 Dagster run이 storage에 없는 경우(지워졌다). `dagster_status = NULL`로 닫는다.

나머지는 모두 재시도와 알림만 한다. `P0001`, `42xxx`, `53xxx`, `55P03`, `40xxx`, `57014`, `08xxx`, 위에 없는 `23xxx`,
SQLSTATE가 없는 예외, timeout, storage 읽기 실패가 여기에 든다. constraint 이름·sqlstate·message는 asyncpg 오류
(`exc.orig.__cause__`)의 `constraint_name`·`sqlstate`·`message`에서 읽는다. `str(exc)`에서 읽지 않는다.

**닫는 조건.** 시계(`head` 또는 `db_watch`)가 `STALL_AFTER` 이상이고, 그 run의 `last_failure`가 CLOSABLE이다. 닫는 대상은
시계를 가진 이 두 run뿐이다.

**닫는 동작.** `abandon_dagster_feature_run(run_id, dagster_status | None, end_time | None, failure, first_failed_at)`를 한
트랜잭션으로 부른다. 실제로 무엇을 할지는 DB 상태가 정한다.

| DB 상태 | 함수가 하는 일 | 그 뒤 sensor |
|---|---|---|
| root 없음 | `reconcile_abandoned` system log 한 행. 이것이 내구성 있는 기록이다 | 지나간다(1c). 닫을 수 있는 머리는 root가 없어도 영구히 잡히지 않는다(H1) |
| root에 취소 marker | 아무것도 하지 않는다(취소 coordinator 몫) | 지나간다(1b) / `db_watch`를 지운다 |
| root가 이미 terminal | 아무것도 하지 않는다 | 지나간다 / `db_watch`를 지운다 |
| root active, Dagster terminal 또는 run 없음 | 기존 `_TERMINAL_OPERATION_COMMAND_SQL`로 root와 끝나지 않은 member를 `failed`로 둔다. `dagster_run_status`에는 Dagster의 실제 값을 넣고, run이 없으면 NULL을 넣는다(procedure가 이 열을 늘 쓰므로 "손대지 않기"는 migration 없이 할 수 없다. NULL은 CHECK가 허용하고, repo의 operation 읽기도 받는다). Dagster 종료 시각이 root·member 시작보다 앞서면(시각이 어긋난 run) 그 시각은 버린다. error_message와 `reconcile_abandoned` 로그를 남긴다(provider_dataset_ids, 조치 "dataset을 다시 실행") | `db_watch`를 지운다 |
| root active, Dagster active | 아무것도 하지 않는다. 돌고 있는 run의 root는 닫지 않는다 | 지나간다(1b). run이 끝난 뒤 다시 판단한다 |

이 함수는 #1319 마지막 판의 `abandon_dagster_feature_run`(`6d0ebfc98`)을 되살린 것이다. 그 판에서 conflict로 끝났던
"root 없음" 분기를 표의 첫 줄로 바꾸고, "run 없음" 경우를 더했다.

**CLOSABLE이 아닌 실패가 머리에서 계속될 때**(42xxx, P0001, 53xxx, storage 실패 등): 이 설계는 머리를 잡아 두고 한 시간마다
알린다. 진척보다 잃지 않는 쪽을 앞에 두는 선택이다. 그동안에도 그 뒤 run들의 status sensor와 run 안의 guard는 그대로
돈다. 막히는 것은 놓친 이벤트를 메우는 일뿐이다. 운영자는 원인을 고치거나, 같은 abandon 함수를 `failure="operator"`로
부르는 수동 명령(`ktmctl reconcile-abandon <run_id> --dagster-status <STATUS|missing>`)을 쓴다. acceptance의 괄호 문구는
O5(i) 수락에 따라 "알리고 수동으로 넘길 경로가 있다"로 고쳤다.

### 5. gate 경합은 표지로 가른다(migration 없음)

root 완결이 gate를 잡지 못하면 고정 문구 `feature-write-all gate is busy; provider curation root retries later`와
SQLSTATE `55P03`으로 끝난다. 406 SQL과 head-schema의 문구가 같다. sensor는 asyncpg 오류의 **sqlstate가 55P03이고 message가
`feature-write-all gate is busy`로 시작할 때만** "gate 바쁨"으로 본다. 다른 55P03은 모두 "lock 대기 timeout"이다. **55P03이라고
모두 gate 바쁨으로 보지는 않는다**(H2).

표지는 이름이 아니라 효과에 결박한다. 통합 검사 하나가 다른 연결에서 gate를 배타로 잡아 둔 채 실제 procedure를 불러 분류가
`gate_busy`로 나오는지 본다. 같은 검사가 `lock_timeout`으로 끝난 55P03이 `lock_wait`로 가는지도 본다. procedure 문구가
바뀌면 이 검사가 빨개진다. 두 분류 모두 닫지 않고 같은 15분 시계를 탄다. 분류는 알림 문구에만 쓰인다.

전용 SQLSTATE를 고르지 않은 이유는 완결의 다른 호출자인 취소 coordinator와, API의 55P03 → 503 처리까지 바꿔야 하기
때문이다 → O3.

### 6. 재시도 간격

물러섬(backoff)은 따로 두지 않는다.

- 머리는 매 tick 다시 해 본다. 머리에서 실패하는 run은 root가 아직 없는 run이라 대개 가벼운 ensure에서 실패한다. 무거운
  완결은 ensure가 끝난 뒤에 오고, 그때는 root가 있으니 이미 지나간다.
- DB page의 실패 root는 sweep마다 다시 해 본다. 비용은 결정 2의 서버 쪽 상한이 묶고, 큰 완결은 결정 0이 미리 sensor 밖으로 뺀다.

geo #590의 lock 재시도(물러섬 없이 경과 시간으로만 상한을 둔다)와 같은 모양이다.

그래서 `retry_after` 필드가 없다. acceptance의 "retry_after는 실패 시각 기준"에는 해당하는 필드가 없는 셈이다. 그 취지는
시계가 지킨다. `first_failed_at`은 실패한 호출이 돌아온 시각이지 tick이 시작한 시각이 아니다(M3) → O2.

### 7. cursor

기존 키는 그대로 두고 선택 키 둘 `head`, `db_watch`를 더한다. 둘 다 결정 3의 고정 모양이다.

- 비어 있는 키는 쓰지 않는다. 그래서 아무 일도 없을 때 cursor 바이트가 main과 같다(`sort_keys`·구분자 동일).
- 커져도 고정 모양 두 항목이라 크기에 상한이 있다(A-M3).
- `version`은 1 그대로다. parser는 선택 키가 있어도 없어도 받는다.

**되돌릴 때**: main parser는 선택 키를 거부한다. 되돌리기 전에 선택 키를 뺀 cursor를 `dagster sensor cursor --set`으로
써 둔다. `--delete`는 쓰지 않는다. 비어 있지 않은 storage에서는 null cursor 초기화가 거부되기 때문이다. 이 설계에는
migration이 없다.

## 해제 조건 대응 (tasks-acceptance §T-RECONCILE-RETRY)

| 조건 | 이 설계에서 맡는 곳 |
|---|---|
| 잃지 않는다(root 없는 run, 넘침, 재시작 포함) | 결정 1. 지나가는 경우는 (a)(b)(c)뿐이고 넘칠 표가 없다. 관측 오류도 머리 시계를 탄 뒤 (c) 기록을 남기고서야 지나간다. 시계는 cursor에 있어 재시작해도 남는다. 내구성 있는 log 한 행을 "잃지 않음"으로 친다(O5(ii) 수락) |
| tick 시간 유계, cursor commit이 DB page 목록 조회에 결박되지 않음 | 결정 0·2. 고정 40초, page별 마감, 서버 쪽 statement·lock timeout, executor 하나, 모든 분기에서 commit |
| 경과 시간 알림, 서명이 바뀌어도 초기화 안 됨, 55P03도 지속되면 알림 | 결정 3 |
| gate 경합과 lock_timeout 구별 | 결정 5(효과에 결박한 표지) |
| 명시 목록만 닫기, root 없음·취소 중·이미 terminal에서 할 일 | 결정 4의 목록과 표. 취소 marker root는 DB page에 오지 않는다(결정 3 마지막 줄) |
| retry_after는 실패 시각 기준, cursor는 비면 같은 바이트, 커져도 유계 | 결정 6·7 |

## #1319 결함 대응

| 결함 | 이 설계 |
|---|---|
| A-H1 넘침으로 버린 root 없는 run이 사라짐 | 표가 없다. 머리로 잡힌다 |
| A-H2 tick당 실패 예산 없음 | 횟수 대신 page별 마감과 서버 쪽 timeout(결정 2) |
| A-M1 manifest 일시 실패가 guard 거부로 감싸짐 | ADR-111이 이미 고쳤다 |
| A-M2 관측 오류를 30초마다 영구 재시도 | 관측 오류는 머리 시계 15분 뒤 (c)로 닫힌다 |
| A-M3 cursor가 수십 KB | 고정 모양 두 항목 |
| A-L3 취소로 막힌 닫기가 영구 `blocked` | 취소 marker root는 닫지 않고, 이 sensor의 대상도 아니다 |
| B 55P03 대기를 멈춤으로 오인, `q`로 검색 안 됨 | 처음 본 실패에서 15분이 지나야 알린다. message가 이벤트 이름으로 시작한다 |
| H1 닫을 수 있는 머리도 root가 없으면 영구히 잡힘 | 결정 4 표의 첫 줄 |
| H2 모든 55P03을 gate 바쁨으로 봄 | 결정 5 |
| H3 서명이 바뀌면 횟수 초기화 | 횟수가 없다 |
| M1 tick 상한이 실제로 없음 | 결정 2(서버 쪽 timeout) |
| M2 cursor commit이 DB page 조회에 결박됨 | 결정 2 |
| M3 `retry_after`가 tick 시작 기준 | 필드 없음. 시계는 실패 시각 기준이다 |

## 기각한 대안

- **run별 parking 표**: A-H1·A-H2·A-M3.
- **실패 횟수로 알리고 닫기**: H3.
- **Dagster page에서 실패한 run을 건너뛰고 DB page가 다시 집기를 기대하기**: root가 없는 run은 DB page에 오지 않는다.
- **client 쪽 `asyncio.timeout`만으로 상한 걸기**: 서버에서는 완결이 gate를 든 채 계속 돈다.
- **Dagster `end_time`을 시계로 쓰기**: sensor가 멈췄거나 DB가 내려간 시간까지 실패로 센다.
- **root별 실패 시각을 DB에 남기기**: 새 열과 쓰기 경로가 생기고, 그 쓰기는 DB가 아플 때 실패한다.
- **gate 전용 SQLSTATE**: 결정 5.

## 열린 결정 (소유자)

- **O1 결정 0의 전제.** prod 완결 소요를 잰 결과로, 그대로 구현할지 먼저 완결을 sensor 밖으로 옮길지 정한다.
  **실측(2026-10-20, n150 공용 PG `11000`, 읽기 전용).** `pg_stat_statements`에는 `CALL
  feature.finalize_provider_curation_root` 항목이 없다(통계 2026-09-28 reset 뒤 dealloc 1,058회 — 밀려났거나,
  n150 daemon이 멈춘 뒤(마지막 sensor tick 2026-10-17 08:18Z) 호출이 없다). `log_min_duration_statement=-1`이라 PG 로그도 없다. 대신
  - prod root는 `ops.curation_provider_root_receipts` **4건뿐**이고 모두 `generation_count=0`(child receipt 1개)이다
    (2026-10-12~13). 무거운 root의 완결 소요는 prod에서 잴 수 없다.
  - 그중 2건은 reconcile tick 안에서 commit됐다. tick 시작→commit **6.06 s·7.67 s**(tick 전체 6.31·7.69 s) — 완결만의
    시간은 이보다 작다. 나머지 2건은 reconcile tick 밖에서 commit됐다(어느 경로인지는 확인하지 않았다).
  - `feature_operation_reconciliation_sensor` tick 소요(2026-10-01~17, `dagster_shared.job_ticks`): SKIPPED 17,225건
    평균 1.60 s·p99 12.07 s·최대 127.25 s, FAILURE 18건 최대 62.94 s(60 s 평가 timeout 부근).

  판단 근거로는 상한만 준다: 세대 0인 root도 tick 기준 6~8 s로 머리 예산 15 s의 절반에 닿고, tick p99가 12 s다. 세대가 있는
  root는 더 길다고 봐야 한다. 그래서 "최대가 15 s에 가깝게라도 나오면" 조건에 해당한다고 보고 **완결을 sensor 밖으로 옮기는
  항목부터** 하는 쪽을 권한다(소유자 결정).
  **결론(2026-10-20 소유자 수락).** 완결을 sensor 밖으로 먼저 옮긴다. 모양은 결정 0-1이다.
- **O2 값과 물러섬 — 수락 2026-10-21.** STALL_AFTER 15분, 예산 40초 고정(Dagster page 마감 +20초, DB page +40초), 시계마다
  알림 한 시간에 한 행, 물러섬 없이 tick·sweep마다 재시도, `retry_after` 필드 없음.
- **O3 표지 대 전용 SQLSTATE — 수락 2026-10-21.** 표지(55P03이면서 message가 `feature-write-all gate is busy`로 시작)로
  가른다. migration도 전용 SQLSTATE도 없다. 효과는 통합 검사가 실제 procedure로 결박한다.
- **O4 Dagster SUCCESS인 root를 `failed`로 닫기 — 수락 2026-10-21.** CLOSABLE 실패가 15분 이어지면 Dagster SUCCESS여도
  `failed`로 닫는다. 그 run의 큐레이션 완결은 버려지고 다음 run이 다시 한다.
- **O5 acceptance 읽기 둘 — 수락 2026-10-21.** (i) 설계를 유지한다. CLOSABLE이 아닌 실패로 막힌 머리는 잡아 두고 한
  시간마다 알리며, 수동 abandon(`failure="operator"`)으로 넘긴다. acceptance 괄호 문구를 "닫을 수 없는 머리를 영구히
  잡지 않는다"에서 "알리고 수동으로 넘길 경로가 있다"로 고쳤다. (ii) root 없이 닫은 run은 `reconcile_abandoned`
  system log 한 행을 "잃지 않음"으로 친다.

## 구현 범위 (승인 뒤 같은 항목)

- `feature_operation_sensors.py`: 결정 1~3, 6, 7. storage executor.
- client·repo: 트랜잭션별 timeout 인자(isolation 문 다음 `set_config`, 보조 트랜잭션 포함),
  `abandon_dagster_feature_run`(root 없음·run 없음 분기 포함), `reconcile_stalled` 기록, active-root 술어로 root 하나를 읽는
  짧은 읽기.
- migration 없음.
- 검사: 해제 조건 한 줄마다 하나씩 두고, 변이로 맞는 층에 결박됐는지 확인한다. 예를 들어 (b)를 "ensure를 시도했다"로
  느슨하게 하면 root 없는 run 손실 검사가 빨개져야 하고, `set_config('statement_timeout', …, true)`를 빼면 "서버 쪽 완결이 예산 안에
  끝난다" 통합 검사가 빨개져야 한다. abandon은 다섯 분기 통합 검사, SERIALIZABLE SUCCESS reconcile에 timeout을 넣은 검사, gate 표지는 결정 5의 실제 procedure 검사를 둔다.
- 결과를 `docs/architecture/dagster-boundary.md` §9.1에 반영하고 상태를 accepted로 올린다.

## 리뷰 반영 (2026-10-20, 적대 리뷰 2회)

초안이 받은 HIGH 넷과 그 반영은 다음과 같다.

- client만 끊는 timeout은 서버의 완결을 멈추지 못한다 → 서버 쪽 `SET LOCAL`로 바꿨다.
- 완결이 sensor 전용이라는 전제가 틀렸다(취소 coordinator도 부른다) → 전용 SQLSTATE를 버리고 표지로 바꿨다.
- 항목별 시간 창 dedupe와 재시도 throttle이 page 방문 주기와 겹쳐 영원히 발화하지 않을 수 있다 → 둘 다 지우고 cursor
  시각 하나로 바꿨다.
- `end_time` 시계가 첫 실패를 이미 15분 지난 것으로 만든다 → 처음 본 실패 시각으로 바꿨다.

MED·LOW는 다음과 같이 반영했다. 취소 marker root가 DB page에서 빠진다는 전제를 바로잡았다. (b)를 "root가 있다"로
넓혔다. storage 실패도 머리 시계를 탄다. 예산은 고정 상수로 하고 executor는 하나로 뒀다. 일찍 멈출 때의 DB cursor
자리를 정했다. CLOSABLE을 좁혔다.

2차 리뷰의 HIGH 셋은 다음과 같이 반영했다.

- 서버 쪽 상한이 오래 걸리는 완결을 영영 못 끝내게 한다 → 결정 0(구현 전제·측정)과 O1.
- `db_watch` 슬롯 하나를 고칠 수 없는 root가 영영 잡는다 → 알림을 낸 뒤 슬롯을 넘긴다. 지워진 run은 닫을 수 있게 했다.
- `SET LOCAL`을 맨 앞에 두면 SERIALIZABLE에서 25001이 난다 → isolation 문 다음 `set_config`로 순서를 못 박았다.

2차 리뷰의 MED·LOW는 다음과 같이 반영했다. `23514`를 constraint 이름 다섯으로 좁히고 membership 검사는 뺐다. 관측 오류는
바로 지나가지 않고 머리 시계를 탄 뒤 닫는다. 그 덕에 abandoned 행은 15분에 한 행을 넘지 않는다. page별 마감으로 호출
상한을 잰다. 알림 throttle은 시계마다 `alerted_at`으로 둔다(`last_stall_alert_at`은 없앴다). liveness 읽기는 active-root
술어를 쓴다. 표지는 asyncpg 오류의 message·sqlstate에서 읽는다. 보조 트랜잭션에도 timeout을 건다. storage worker가 걸린
경우의 한계를 적었다. 실패 횟수 예산은 없앴다.

## 구현 결과 (2026-10-21, `T-RECONCILE-RETRY` 둘째 하위 단계)

- **sensor** `packages/kor-travel-map-dagster/.../feature_operation_sensors.py`: 결정 1(`_reconcile_dagster_page`,
  `_RootSeen`), 2(`_Tick` — page별 마감, 호출마다 `transaction_deadline` + `asyncio.timeout(남은+3초)`, storage 읽기는
  slot 하나짜리 `call_with_deadline`, 모든 분기 commit, 실패 로그 3줄), 3(`head`·`db_watch` 시계, `_alert_if_due`,
  `db_watch`는 알림 뒤 슬롯을 넘긴다), 5(`_classify_failure`의 표지), 6(물러섬 없음), 7(cursor 선택 키).
- **client·repo**: `kortravelmap.infra.transaction_limits`(트랜잭션 범위 `set_config` — SERIALIZABLE이면 isolation 문
  다음, 보조 트랜잭션 포함), `abandon_dagster_feature_run`(다섯 분기 + run 없음 → `dagster_run_status` NULL),
  `record_feature_operation_reconcile_stalled`, `is_reconcilable_dagster_feature_run`(`_ACTIVE_ROOTS_PAGE_SQL`과 같은
  술어로 root 하나). migration 없음, API·OpenAPI 변화 없음(PinVi 재vendor 불필요).
- **수동 닫기**: `ktmctl reconcile-abandon <run_id> --dagster-status <STATUS|missing> [--finished-at ISO]`
  (`failure="operator"`). 같은 run의 ensure와는 DB lineage advisory lock이 직렬화한다(ADR-039, 별도 CLI mutex 없음).
  DSN은 provider executor(Dagster runtime 로그인)여야 한다.
- **completion sweep**: 트랜잭션마다 `client_connection_check_interval=10s`(geo #591과 같은 자리) — sweep worker가 죽으면
  서버가 완결 CALL을 ~10초 안에 취소해 lineage lock을 600초까지 붙들지 않는다. sensor 트랜잭션은 statement_timeout이
  묶으므로 걸지 않는다.
- **kor-travel-common 경계**: 범용 도구(`call_with_deadline`(slots), `pg_error_info`, `StallClock`·`observe_failure`·
  `due_alert`·`mark_alerted`)는 `kortravelmap.dagster.retry_common` 한 모듈에 같은 이름·의미로 두었다. common에 같은 API가
  머지되면 그 import로 바꾸고 핀을 올린다. 트랜잭션 SQL·CLOSABLE 목록·gate 표지·abandon·cursor 키는 소비자(Map) 몫이다.
- **lock_timeout**: min(30초, 남은 − 4초)를 그대로 둔다. odroid tenant의 5초로 낮출지는 소유자 확인 대기다.
- **알려진 성질**: 슬롯을 넘겨받은 root가 다시 첫 실패 root로 슬롯을 잡으면 시계가 처음부터 돈다. 그래서 같은 root의
  `db_watch` 알림은 15분+α 주기로 되풀이될 수 있다(시계마다는 한 시간에 한 행). 설계가 받아들인 대가다(결정 3).
- **되돌릴 때**: main parser는 선택 키(`head`·`db_watch`)를 거부한다. 되돌리기 전에 선택 키를 뺀 cursor를
  `dagster sensor cursor --set`으로 써 둔다(`--delete` 금지, 결정 7).
