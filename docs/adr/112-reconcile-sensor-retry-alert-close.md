# ADR-112 — reconcile sensor는 DB root가 생긴 run만 지나가고, 멈춤은 경과 시간으로 알리고, 정한 실패만 닫는다

- 상태: proposed (설계만. 구현은 소유자가 승인한 뒤 같은 항목 `T-RECONCILE-RETRY`에서 한다. 아래 "열린 결정"이 승인 대상이다)
- 날짜: 2026-10-20
- 결정자: Claude (소유자 승인 대기)
- 관계: ADR-111 결정 4(이 설계를 후속으로 넘겼다), ADR-107(공용 Dagster 런타임), ADR-021(forward-only)
- 설계 입력: PR #1319의 세 판과 리뷰 결과(ADR-111 결정 4 목록, journal 2026-10-13 ADR-111 항목). 마지막 판 코드는
  커밋 `6d0ebfc98`에 있고 `294f744f8`이 되돌렸다. 최종 리뷰의 L1~L4는 저장소 어디에도 내용이 적혀 있지 않다. 그래서
  아래 대응 표에 넣지 못했다.

## 컨텍스트

`feature_operation_reconciliation_sensor`(30초 주기)는 두 쪽을 돈다.

- **Dagster page**: run storage를 insertion 순서로 훑는다. 300초 settle을 지난 Map run을 run마다 **한 번씩** 본다.
  이 page가 맡는 일은 "operation run마다 DB root가 있다"를 보장하는 것이다. 이미 끝난 run이면 terminal 반영도 한다.
- **DB page**: 아직 끝나지 않은 DB root(`ops.import_jobs` active root)를 keyset으로 훑는다. 끝까지 가면 처음으로 돌아간다.
  root가 한 번 생기면 이 sweep이 끝날 때까지 몇 번이든 다시 집는다. 즉 root가 있는 run에는 이미 **내구성 있는 재시도 큐**가 있다.

main은 단순하다. run 하나의 반영이 예외를 내면 tick 전체가 실패하고, 두 cursor가 모두 제자리에 남고, 30초 뒤 같은
일을 다시 한다. 멈춰도 알림이 없고 닫는 경로도 없다. tick 시간 상한도 없다. client의 `statement_timeout`이 600초이고,
한 tick이 각 쪽 200건씩 처리할 수 있다. 2026-10-12에는 이 구조가 53200을 30초마다 되풀이했다. 원인은 406이
없앴으므로 급한 일은 아니다.

이 설계는 이미 있는 모델에 기댄다. 새 표도, run별 상태도 만들지 않는다.

1. ensure와 terminal reconcile은 짧은 트랜잭션 두 개다. **ensure가 commit되면 root가 있다.**
2. root가 active로 남아 있는 한 DB page가 그 root를 다시 집는다.
3. Dagster `RunRecord.end_time`은 run이 끝난 뒤 바뀌지 않는다.
4. reconcile은 취소 marker가 있는 root에 `blocked/cancellation`을, 이미 terminal인 root에 `blocked/terminal`을 돌려준다.
   둘 다 예외가 아니다.
5. Dagster는 sensor context에 직전 tick 완료 시각(`last_tick_completion_time`, Dagster 1.13에 있음)을 준다.

## 결정

### 1. watermark가 run을 지나가는 규칙은 하나다(잃지 않는다)

Dagster watermark는 run R이 다음 셋 중 하나에 해당할 때만 R을 지나간다.

- (a) panel-only다(operation key가 없다). 또는 관측 오류다(`FeatureOperationObservationError`). 둘 다 main과 같다.
- (b) **이번 tick에 R의 ensure가 commit됐다.** 뒤따른 terminal reconcile이 실패해도 지나간다. 그 root는 active로
  남아 DB page가 맡는다. 이미 terminal이거나 `blocked`이면 반영됐거나 다른 소유자(취소 coordinator)가 있다.
- (c) 결정 4의 닫기가 R에 대한 내구성 있는 기록을 commit했다.

셋 다 아니면 Dagster page는 **R에서 멈춘다.** watermark는 R 바로 앞 run에 남고, R이 머리(head)가 된다. 미뤄 두는 표가
없으니 넘치는 일도 없다. 그 tick에는 R 뒤의 run을 보지 않는다.

DB page에서 항목 하나가 실패하면 그 항목만 건너뛴다. 다음 sweep이 다시 집는다. 이 설계에서 "다시 집는다"를 가정하는 곳은
여기뿐이다. 항목이 DB에서 왔으므로 이 가정은 참이다(A-H1의 금지는 DB root가 **없는** run에 대한 것이다).

### 2. tick 시간에 상한을 둔다

- tick 예산은 시작부터 **40초**다. Dagster의 sensor 평가 timeout 기본값은 60초다. `DAGSTER_SENSOR_GRPC_TIMEOUT_SECONDS`가
  더 작게 설정되어 있으면 예산은 그 값의 2/3이다. Dagster page가 앞의 절반까지 쓰고, DB page가 나머지를 쓴다.
- client 호출 하나하나를 남은 예산으로 `asyncio.timeout`에 감싼다. 남은 예산이 5초보다 적으면 새 호출을 시작하지 않는다.
  timeout은 그 항목의 일시 실패로 센다(결정 1·4).
- Dagster run storage를 읽는 동기 호출(`get_run_records`, `get_run_record_by_id`, `get_runs_count`)은 전용 daemon thread
  executor에서 같은 timeout으로 돈다. loop가 끝날 때 이 executor는 기다리지 않는다. `asyncio.run`의 기본 executor 종료는
  남은 thread를 기다리므로 상한을 무너뜨린다.
- page마다 tick당 실패 예산을 **3회**로 둔다. Dagster page에서 (b)로 지나간 실패도 센다. 예산을 다 쓰면 그 tick에는
  그 page를 멈춘다(A-H2).
- cursor는 모든 분기에서 return 전에 `update_cursor`한다. `MapRunScopeMismatch`만 예외다. 이것은 설정 오류라 계속
  FAILURE로 보인다. DB page 목록 조회가 실패하면 DB cursor는 그대로 두고 Dagster 쪽 진척은 commit한다(M2). Dagster
  storage 읽기가 실패하면 watermark는 그대로 두고 DB page는 돈다.
- **한계.** 이 sensor 안에서 terminal reconcile(root 완결) 한 번은 남은 예산(약 35초)보다 오래 돌 수 없다. 더 오래
  걸리는 완결은 매번 취소된다. timeout은 닫는 목록에 없으므로 결정 3의 알림으로 올라간다. → 열린 결정 O1.

### 3. 멈춤은 경과 시간으로 알린다

횟수는 세지 않는다. 멈춘 것마다 바뀌지 않는 시계 하나를 쓴다. 실패 서명이 번갈아 바뀌어도 시계는 처음으로 돌아가지 않는다(H3).

| 멈춘 것 | 시계 시작 |
|---|---|
| Dagster page 머리(root가 없을 수 있음) | cursor `head.first_failed_at` — 그 run_id가 머리에서 처음 실패한 시각. 머리 run_id가 같은 동안 유지 |
| DB page root. Dagster run은 terminal인데 이번 시도 뒤에도 root가 active(실패든 `blocked/cancellation`이든) | Dagster `end_time`. 첫 실패 시각보다 늦을 수 없으므로 알림은 첫 실패에서 N분이 지나기 **전이나 그때** 온다 |
| DB page root. Dagster run이 아직 active | 알리지 않는다. root가 run을 active로 이미 기록했으니 늦어진 반영이 없다. run이 끝나면 위 줄의 시계를 탄다 |
| DB page root. Dagster run을 찾을 수 없음(지워짐) | root `created_at`(run은 root보다 먼저 있었다). 알리기만 하고 닫지 않는다 |

- **STALL_AFTER = 15분.** 실패 종류와 상관없이 같은 값이다. gate 바쁨, lock_timeout 55P03, 53xxx, timeout이 모두
  같은 시계를 탄다(B·H2). 55P03 같은 일시 실패도 15분 넘게 이어지면 알린다.
- **알림이 가는 곳**: `ops.system_logs`에 `level=error`, `source=feature_operation`,
  `event=feature_operation.reconcile_stalled`로 남긴다. message는 **이벤트 이름으로 시작한다**. 그래서 admin 로그 화면의
  `q` 검색에 걸린다(B). detail에는 멈춘 항목을 최대 20건 담는다(run_id, Dagster status, SQLSTATE 또는 예외 class, 경과,
  `gate_busy`인지 `lock_wait`인지, 조치 문구). 총 건수도 함께 담는다. 한 tick에 최대 한 행이다.
- **같은 알림이 되풀이되지 않게 상태 없이 막는다.** 어떤 항목의 시계가 `STALL_AFTER + k·1시간` 경계를 직전 tick 완료
  시각과 지금 사이에 넘었을 때만 그 행을 쓴다. 매 tick에는 `context.log.error` 요약만 남긴다. system log 쓰기가
  실패하면 Dagster 로그만 남는다. 알림은 결정 1의 진행을 막지 않는다.

### 4. 정한 실패만 닫는다

**닫을 수 있는 실패 목록** — `CLOSABLE`:

- SQLSTATE class `22`(data exception)
- SQLSTATE class `23`(integrity constraint violation)
- `FeatureOperationInvariantConflict`(run identity·selection 불변식 위반)

이 셋은 같은 입력으로 다시 해도 같은 답이 나오는 실패다. 나머지는 모두 다시 시도하고 알리기만 한다. 여기에는 `P0001`,
`42xxx`(배포로 고칠 수 있다), `53xxx`, `55P03`, `KMG01`(결정 5), `40001`·`40P01`, `57014`, `08xxx`, SQLSTATE가 없는 예외,
timeout이 들어간다. #1319의 22/23/P0 목록에서 `P0`을 뺐다. `P0001`은 일반 `RAISE`라서 결정적인 실패인지 보장할 수 없다.

**닫는 조건**: 이번 tick의 마지막 실패가 `CLOSABLE`에 들고, 그 항목의 시계(결정 3)가 `STALL_AFTER` 이상이다. 횟수는 보지 않는다.

**닫는 동작**: DB 함수 하나 `abandon_dagster_feature_run(run_id, dagster_status, end_time | None, failure)`를 한
트랜잭션으로 부른다. 무엇을 할지는 DB 상태가 정한다.

| DB 상태 | 함수가 하는 일 | 그 뒤 sensor |
|---|---|---|
| root 없음 | `reconcile_abandoned` system log 한 행을 남긴다. 이 행이 내구성 있는 기록이다(run_id·operation_key·failure·first_failed_at) | 지나간다(결정 1c). **닫을 수 있는 머리는 root가 없어도 영구히 잡히지 않는다**(H1) |
| root에 취소 marker가 있음(취소 중) | 아무것도 하지 않는다. 취소 coordinator가 맡는다 | root가 있으므로 지나간다. 멈춤 알림은 결정 3대로 계속된다(A-L3). 조치 문구는 취소 coordinator를 가리킨다 |
| root가 이미 terminal | 아무것도 하지 않는다 | 지나간다 |
| root active, Dagster terminal | 기존 `_TERMINAL_OPERATION_COMMAND_SQL`로 root와 끝나지 않은 member를 `failed`로 둔다. `dagster_run_status`는 Dagster의 실제 terminal 값이다. error_message와 `reconcile_abandoned` 로그(provider_dataset_ids, 조치 "dataset을 다시 실행")를 남긴다 | DB page가 더는 보지 않는다 |
| root active, Dagster active | 아무것도 하지 않는다. 돌고 있는 run의 root는 닫지 않는다 | root가 있으므로 지나간다. run이 끝난 뒤 다시 판단한다 |

`CLOSABLE`에 들지 않는 실패가 머리에서 계속되면 머리를 잡고 알린다. 잃지 않는 쪽을 진척보다 앞에 둔 의도적 선택이다.
원인은 운영자가 고친다. 닫는 함수는 #1319 마지막 판의 `abandon_dagster_feature_run`(커밋 `6d0ebfc98`)을 되살린다.
다만 그 판이 conflict로 끝냈던 "root 없음" 분기를 위 표의 첫 줄로 바꾼다.

### 5. gate 경합에는 전용 SQLSTATE를 쓴다

migration 410이 `feature.finalize_provider_curation_root`의 gate try 실패를
`RAISE ... USING ERRCODE = 'KMG01'`로 바꾼다. 바뀌는 것은 그 한 줄뿐이다. class `K`는 PostgreSQL이 구현 정의용으로 남긴
범위다. sensor는 `KMG01`을 "gate 바쁨"(대량 관리 명령이 gate를 들고 있다)으로, `55P03`을 "lock 대기 timeout"(`pg_locks`에서
막는 쪽을 찾아야 한다)으로 나눠 알림 문구에 쓴다. **모든 55P03을 gate 바쁨으로 보지 않는다**(H2). 둘 다 닫지 않고,
둘 다 같은 15분 시계를 탄다. root 완결은 sensor에서만 불린다(`reconcile_dagster_feature_run` →
`_finalize_authoritative_curation_root`). 그래서 API의 55P03 → 503 `LOCK_TIMEOUT` 처리는 영향을 받지 않는다.

### 6. 재시도 간격의 기준은 실패 시각이다

- **머리**: cursor에 `retry_after = failed_at + (30초, 단 failed_at − first_failed_at ≥ 2분이면 5분)`을 둔다. `failed_at`은
  실패한 호출이 돌아온 시각이다. tick 시작 시각이 아니다(M3). `retry_after` 전에는 Dagster page를 통째로 쉰다.
  머리 너머의 run은 어차피 지나갈 수 없기 때문이다.
- **DB page**: Dagster run이 terminal이고 시계가 2분 이상인 root는, `(now − end_time)`의 5분 경계가 (직전 tick 완료
  시각, 지금] 구간에 들 때만 시도한다. 아니면 건너뛰되 방문한 것으로 친다(keyset은 나아간다). 그 밖의 root는 sweep마다
  시도한다. root별 상태는 두지 않는다. 직전 tick 완료 시각이 없으면 시도한다.

### 7. cursor

키는 그대로 두고 선택 키 `head`만 더한다. `head`의 모양은 `{run_id, first_failed_at, retry_after}` 하나로 고정이다.
머리가 없으면 `head`를 쓰지 않는다. 그러면 cursor 바이트가 main과 같다(`sort_keys`·구분자 동일). 커져도 고정 모양
한 항목이라 tick body 크기가 유계다(A-M3). `version`은 1로 둔다. parser는 `head`가 있든 없든 받는다.

**되돌릴 때**: main parser는 `head` 키를 거부한다. 되돌리기 전에 `head`를 뺀 cursor를 `dagster sensor cursor --set`으로
쓴다. `--delete`는 쓰지 않는다. 비어 있지 않은 storage에서는 null cursor 초기화가 거부된다. 410은 forward-only다.
main sensor는 `KMG01`을 다른 실패와 똑같이 tick 실패로 다룬다.

## 해제 조건 대응 (tasks-acceptance §T-RECONCILE-RETRY)

| 조건 | 이 설계에서 맡는 곳 |
|---|---|
| 잃지 않는다. root 없는 run도 포함하고, 넘침·재시작이 있어도 그렇다 | 결정 1. 지나가는 규칙은 (a)(b)(c) 셋뿐이다. 넘칠 표가 없다. 머리 상태는 cursor에 있어 재시작해도 남는다 |
| tick 시간이 유계다. cursor commit이 DB page 목록 조회에 결박되지 않는다 | 결정 2. 40초 예산, 호출마다 timeout, 동기 읽기도 같은 timeout, 모든 분기에서 cursor commit |
| 알림은 경과 시간으로. 서명이 바뀌어도 시계가 그대로다. 55P03도 오래 지속되면 알린다 | 결정 3 |
| gate 경합과 lock_timeout을 가른다 | 결정 5(`KMG01`) |
| 명시 목록만 닫는다. root 없음·취소 중·이미 terminal에서 각각 할 일 | 결정 4의 목록과 표 |
| retry_after는 실패 시각 기준이다. cursor는 비면 바이트가 같고, 커져도 유계다 | 결정 6·7 |

## #1319 결함 대응

| 결함 | 이 설계 |
|---|---|
| A-H1 넘침으로 버린 root 없는 run이 사라진다 | 표가 없다. root 없는 run은 머리로 잡힌다 |
| A-H2 tick당 실패 예산이 없다 | page마다 실패 3회, 40초 예산 |
| A-M1 manifest 일시 실패가 guard 거부로 감싸진다 | ADR-111이 이미 고쳤다(main) |
| A-M2 관측 오류를 30초마다 영구히 재시도한다 | 관측 오류는 main대로 (a)로 지나간다. DB page의 Dagster 관측 실패는 sweep 주기로만 다시 보고, 멈춤 알림을 탄다(결정 3 마지막 줄) |
| A-M3 cursor가 수십 KB가 된다 | `head` 한 항목뿐이다 |
| A-L3 취소로 막힌 닫기가 영구 `blocked`가 된다 | 취소 중 root는 닫지 않고 지나간다. 알림은 취소 coordinator를 가리킨다 |
| B 55P03 대기를 멈춤으로 잘못 알리고, 이벤트 이름이 `q`로 검색되지 않는다 | 15분 시계를 넘어야 알린다. message가 이벤트 이름으로 시작한다 |
| H1 닫을 수 있는 머리도 root가 없으면 영구히 잡힌다 | 결정 4 표 첫 줄 |
| H2 모든 55P03을 gate 바쁨으로 본다 | 결정 5 |
| H3 서명이 바뀌면 횟수가 초기화된다 | 횟수를 쓰지 않는다. 시계를 쓴다 |
| M1 tick 시간 상한이 실제로는 없다 | 결정 2 |
| M2 cursor commit이 DB page 조회에 결박된다 | 결정 2 |
| M3 `retry_after`가 tick 시작 기준이다 | 결정 6 |

## 기각한 대안

- **run별 parking 표** — A-H1·A-H2·A-M3. 넘침 경로가 손실을 만든다.
- **실패 횟수로 알리고 닫기** — H3. 서명이 바뀌면 초기화된다.
- **Dagster page에서 실패한 run을 건너뛰고 DB page가 다시 집기를 기대하기** — root가 없는 run은 DB page에 없다.
- **root별 실패 시각을 DB에 남기기** — 새 열과 쓰기 경로가 생긴다. 그 쓰기는 DB가 아플 때 실패한다. `end_time`과
  `head`만으로 충분하다.

## 열린 결정 (소유자)

- **O1 sensor 안의 root 완결 시간 상한.** 결정 2에 따라 sensor 안에서 완결 한 번은 약 35초를 넘을 수 없다. main도
  평가 timeout 60초에 걸리기는 같다. 다만 지금은 timeout 뒤에도 code server 쪽 실행이 끝까지 가서 commit될 수 있다.
  이 설계에서는 취소된다. 큰 dataset(MOIS 등)의 완결이 이 상한을 넘는다면 완결을 run의 마지막 단계로 옮기는 별도
  항목이 필요하다. 구현 전에 prod 완결 소요를 읽기 전용으로 잰다. 예: `pg_stat_statements`의 `CALL
  feature.finalize_provider_curation_root` 평균·최대.
- **O2 값.** `STALL_AFTER` 15분(알림과 닫기에 같은 값), 예산 40초, 실패 예산 3회, 재시도 30초 → 5분.
- **O3 `KMG01` 대 표지.** 전용 SQLSTATE는 migration 하나가 든다. 55P03을 그대로 두고 message 표지로 가르면 migration은
  없지만 문구에 결박된다. 이 설계는 SQLSTATE를 고른다.
- **O4 Dagster SUCCESS인 root를 `failed`로 닫기.** 패널에는 `failed`와 raw `SUCCESS`가 함께 보인다. 그 run의 큐레이션
  완결은 버려지고, 같은 dataset의 다음 run이 다시 완결한다(#1319 abandon 문구 "dataset을 다시 실행"). 이렇게 닫아도
  되는지 정한다.

## 구현 범위 (승인 뒤 같은 항목)

- `feature_operation_sensors.py`: 결정 1~3, 6, 7.
- repo·client: `abandon_dagster_feature_run`(root 없음 분기 포함), `reconcile_stalled` 기록.
- alembic 410: `KMG01`.
- 테스트: 해제 조건 한 줄마다 검사 하나를 둔다. 그리고 각 검사가 맞는 층에 결박됐는지 변이로 확인한다. 예를 들어
  (b)를 "ensure 시도"로 느슨하게 하면 root 없는 run 손실 검사가 빨개져야 하고, 예산을 없애면 tick 시간 검사가 빨개져야 한다.
  root 없음·취소 중·terminal·active 네 분기의 abandon 통합 검사도 둔다.
- 결과를 이 ADR과 `docs/architecture/dagster-boundary.md` §9.1에 반영하고, 상태를 accepted로 올린다.
