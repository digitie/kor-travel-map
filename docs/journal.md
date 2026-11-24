## 2026-11-24 — Map Dagster freeze 도구 리뷰 후속(#1541)

- 따라잡기 판정(P2): Dagster 1.13 run-status sensor 감싸개(`run_status_sensor_definition.py`)는 사건 하나에 사용자
  함수가 값을 돌려주면 그것을 내고 tick을 끝낸다. `feature_update_request_failure_sensor`는 실패 사건마다
  `SkipReason(message)`를 돌려주므로 그 tick은 SKIPPED(사유 있음)이고 사건 하나를 처리했다. 처리할 사건이 없던 tick은
  감싸개가 아무것도 내지 않아 daemon이 사유 없이 SKIPPED로 남긴다(`_daemon/sensor.py`). 도구는 tick의 `skipReason`을
  함께 읽고 사유 없는 SKIPPED만 센다. feature_operation_* sensor는 `SkipReason`을 내지 않는다(reaction → SUCCESS).
  가짜 webserver 시험으로 먼저 재현했다(사유 있는 SKIPPED 두 번에 FREEZE_OK).
- Valkey 상태 schedule(P2·P3): `weather_state`·`transport_state` 모듈의 job은 `kor_travel_map_client`를 요구하지 않고
  operation tag가 없어(run-status sensor가 panel-only로 지나간다) Map PG를 읽지도 쓰지도 않는다(HTTP export·Valkey만).
  freeze가 이 12개를 멈추면 창 동안, 그리고 Dagster가 놓친 tick을 따라잡지 않아 하루 한 번 도는 3개(locations·
  rest_areas·airports)는 unfreeze 뒤 최대 약 24시간 낡았다. 보충 실행(unfreeze가 launchRun) 대신 대상에서 뺐다 — 창 안
  낡음도 없애고 mutation을 늘리지 않는다. 접두어(`STATE_JOB_PREFIXES`)로 schedule을 launcher·이어 하기 거부·FREEZE_OK
  판정에서 빼고, run 대기에서 그 job run을 세지 않는다. 스냅샷은 전부 적어 이전 판 스냅샷도 그대로 되살린다.
  `packages/kor-travel-map-dagster/tests/test_freeze_skips_state_jobs.py`가 접두어 = 상태 job·schedule, 그 job의 PG 경로
  없음을 정의로 대조한다(루트 시험은 경고를 오류로 바꿔 Definitions 로드의 BetaWarning을 억제해야 해서 패키지 시험에 둠).
  열린 #1542(상태 job 상류 신호)도 PG 경로를 더하지 않는다(diff 확인).
- 창 안 회전 안내(P2): 안내대로 회전 전용 파일로 새 도구를 부르면 FREEZE_OK 상태에서 freeze가 "이미 얼어 있다"(3),
  unfreeze가 스냅샷 없음(2)으로 늘 실패했다. 회전 스크립트는 저장소에 없고(호스트 전용), 창 안에서는 창 freeze가 이미
  덮으므로 중첩 freeze가 필요 없다. 그 거부는 얼어 있는 상태를 스냅샷하는 사고를 막는 의도된 안전 장치라 도구가 아니라
  안내를 고쳤다 — "회전의 freeze·unfreeze 단계를 뺀다". 거부 메시지도 그렇게 알린다.
- P3: 자동 회전 스크립트의 종료 코드 규칙(0 회전·3 아무것도 안 바뀜·1/2 스냅샷 있으면 unfreeze로 접기)을 README에
  적고, freeze가 1·2로 끝나면 `rollback:` 두 줄을 찍는다. `--resume`은 스냅샷 RUNNING인 launcher가 다시 켜진 것을
  거부하지 않으므로(prod에서는 Map schedule 대부분이 스냅샷 RUNNING) runbook의 "거부(3)로 알린다"를 고치고 `note:`로
  이름을 남긴다.
- 시험: `tests/unit/test_n150_dagster_freeze.py` 46건(+8), `test_freeze_skips_state_jobs.py` 2건 — 로컬 WSL venv(dagster
  1.13.24). n150 접속·실제 freeze는 하지 않았다.

## 2026-11-24 — Map Dagster 전체 freeze 도구·미기동 schedule 6개 활성 반영(수집 실패 감사 §4 #10·#11)

- #10: n150 `~/freeze.py`는 산사태 schedule과 update-request 큐 sensor 둘만 멈춰, PG에 쓰는 나머지 Map
  instigator 약 42개(MOIS·consistency·GC·file scan·feature 적재 schedule)가 운영 창 안에서 그대로 돌았다.
  `scripts/n150/dagster-freeze.py`(표준 라이브러리, host `python3`)로 저장소 정본을 만들었다. `freeze`는 Map
  location의 모든 schedule·sensor 상태·코드 기본값·저장 여부(`canReset`)를 스냅샷(절대 경로, 0600, fsync 뒤 rename)한
  뒤 launcher(schedule·non-run-status sensor)를 멈추고 Map run(repository tag로 좁힘) 0을 기다린다. 그다음
  run-status sensor마다 run 0 뒤 SKIPPED tick(처리할 사건 없음)을 서로 다른 두 시각에 보는지 보고 run을 다시 센다 —
  `feature_operation_success_sensor`는 completion job run을 **낸다**(적대 리뷰 H1). 그 뒤 run-status sensor를 멈추고,
  그 사이 run이 생기면 되살린 채 1로 끝난다. launcher 정지 실패·대기 초과도 run-status sensor를 켜 둔 채 1.
  기존 스냅샷은 `--resume`(24시간 안)일 때만 이어 쓰고, 스냅샷이 RUNNING으로 적지 않은 것이 지금 RUNNING이거나,
  새 스냅샷인데 RUNNING launcher가 0이면(이미 얼어 있음 — 다른 경로로 재실행) 거부한다(3, 리뷰 H2). `unfreeze`는
  스냅샷의 RUNNING만 되살리되(run-status sensor 먼저) 저장 상태가 없던 기본 RUNNING은 `reset`으로(저장된 행이
  코드 기본값을 덮지 않게, 리뷰 M2), STOPPED(MOIS continuation 등)는 그대로, 스냅샷 없거나 비었거나 count가 다르면
  거부, `missing`은 `--accept-missing`으로만 마치고, 성공하면 스냅샷을 `.restored-<UTC>`로 옮긴다. 주소·인증은
  env에서 읽고 출력하지 않는다(잘못된 URL도 원문 없이 2, Basic Auth는 https·loopback에만, redirect 안 따라감).
  PinVi·concierge location은 읽지도 바꾸지도 않는다. mutation 인자·반환형은 n150 Dagster 1.13.24 introspection으로
  확인했다(`stopSensor(jobOriginId, jobSelectorId)`). 같은 introspection으로 보면 `writer_drain_service.py`의
  `stopSensor(id, sensorOriginId, sensorSelectorId)`·`... on SensorState`는 이 버전 스키마와 맞지 않는다(범위 밖, 기록만).
- #11: 미기동 6개(TourAPI 관광지 daily·표준 지역특화거리·전통시장·국가유산 item·concierge YouTube·transport
  주유소)는 `DISABLED_FEATURE_LOAD_SCHEDULES`에 넣을 문서화된 보류 사유가 없었다(관광지·시장·특화거리는
  T-TOURAPI-LOAD·T-MARKET-LOAD의 "켜기"만 남은 상태, 국가유산 item·YouTube는 기록 없음, 주유소 place는 ADR-114의
  "열린 결정"이지 중지 결정이 아님). 소유자 결정으로 부모가 2026-11-24 prod에서 6개를 켰다. 코드 기본 상태는
  저장소 관례대로 STOPPED 그대로 두고 `schedules.py` 주석·`test_prod_enabled_schedules_are_built_but_start_stopped`로
  기록했다. cron은 바꾸지 않았다(prod가 지금 그 값으로 돈다).
- 시험: `tests/unit/test_n150_dagster_freeze.py` 38건(가짜 webserver에 n150 Map location 실제 구성 61개 + PinVi
  location, 6개 RUNNING 포함 스냅샷·복원). n150 읽기 전용 `status`·`freeze --dry-run`·스냅샷 없는 `unfreeze` 거부
  확인(instigator 61·RUNNING 59, 6개 모두 RUNNING, run-status sensor 8개의 tick 조회), 상대 경로 거부. 실제 freeze/unfreeze는
  돌리지 않았다. 적대 리뷰 2인(상태 기계·운영/보안) 지적을 반영했다.
## 2026-11-24 — import job event clock을 slot으로 나눔(감사 §1.2·#1544 남은 구조 문제, alembic 457)

- 근거(n150 Map DB 읽기 전용 조회): 10-22 큐 요청 12건 중 8건이 `LockNotAvailableError` + `INSERT INTO
  ops.import_job_events`로 끝났다. 8건 모두 04:55~05:04Z claim 직후 약 30초(Dagster 엔진 `lock_timeout`)에 실패했고,
  04:47:51~06:04:08Z 76분 동안 refresh transaction을 연 앞 요청(04:47:52Z `job.heartbeat` event를 쓰고 같은 transaction에서
  적재)과 정확히 겹친다. 전역 singleton `ops.import_job_event_clock`의 row lock이 commit까지 남은 탓이다. 공용 PG에
  `pg_stat_statements`는 없고(`log_lock_waits=on`), 컨테이너 로그는 11-23 재시작 이후뿐이라 그 창의 lock wait 로그는 없다.
- 457: `ops.import_job_event_clock_slots`(identity slot). event statement trigger가 다른 transaction이 잡지 않은 가장 작은
  slot을 `FOR UPDATE SKIP LOCKED`로 골라 +1, 모두 잡혀 있으면 새 slot. reader(`/v1/ops/live` `event_clock_revision`)는
  `SUM(revision)` — 의미·값이 종전과 같다(commit된 event statement 수, 옛 값은 slot 1로 이관). guard는 trigger 밖
  INSERT/UPDATE/DELETE/TRUNCATE 거부. migration은 옛 표를 ACCESS EXCLUSIVE로 잡아(1초) 진행 중인 event transaction이
  없을 때만 값을 옮긴다. 후보 비교(sequence·별도 transaction·지연 잡기·job별 행)는 `data-model.md` §9.1.1 event clock.
- 시험: integration `test_import_job_event_clock_slots.py` — 긴 event transaction 중 다른 job event가 `lock_timeout` 2초
  아래서 기다리지 않음(main 456에서는 55P03), late commit·rollback·UPDATE statement 감지, slot 수 상한, guard,
  `ktm_curation_command_owner`의 새 slot, 456→457 이관(진행 중 writer면 lock timeout으로 거부).
- 적대 리뷰 2인 반영: ① migration이 `ktm_feature_runtime`에 새 표 권한을 직접 준다(별도 process인 ACL 조정 전
  창에서 runtime event 기록이 42501로 전부 실패하던 것 — 실측). ② transaction이 처음 고른 slot을 transaction-local
  설정에 기억해 다시 쓴다(긴 transaction이 더 낮은 slot을 계속 쥐어 동시 3개에 slot 5개가 되던 것). ③ guard 시험은
  23514만 받고 TRUNCATE는 소유자로, slot 시험에 `lock_timeout`(회귀 시 10분 hang 대신 2초 실패).
- 남은 것: `ops.ops_live_topic_revisions`(provider_sync·dataset_projection·dagster_schedules)도 같은 singleton 꼴이지만
  432 snapshot 잠금 순서와 ADR-065 causal receipt에 묶여 있어 이번에 바꾸지 않았다. 큐 경로에서는 cache target 요청의
  `poi_cache_targets` 갱신이 그 행을 잡는다.

## 2026-11-24 — 큐 요청 일시 실패 재발행·상한과 실패 원인 기록(감사 §4 #15·§1.3 P1, alembic 456)

- 배경(`docs/reports/2026-11-23-collection-failure-audit.md`): ① 큐 요청은 일시 DB 오류에도 한 번에 `failed`로
  닫혔다(10-22 한꺼번에 넣은 13건이 `import_job_events` INSERT lock timeout으로 실패 — 전역 단일 행
  `import_job_event_clock`을 긴 적재 transaction이 commit까지 쥔다). ② worker run이 claim 전에 실패하면(launch 실패 —
  n150 fd 고갈) failure sensor가 generation만 +1해 15초 뒤 곧바로 새 run을 냈고 상한·backoff가 없었다. ③ 실패 원인이
  Map DB에 남지 않았다 — request는 `ProviderDatasetRefreshFailure: provider refresh asset execution failed` 한 줄(원인은
  `__cause__`에만), operation root는 `{"kind":"dagster_run_terminal","status":"FAILURE"}` 한 줄.
- alembic 456: `ops.feature_update_requests.retry_count`(≥0)·`next_dispatch_at`. 큐 peek은 `next_dispatch_at <= now()`인
  것만 집는다. 재발행 SQL은 claim 전 `queued`(+run 없음) 또는 그 run의 `running`을 같은 문장에서 queued·generation+1·
  retry_count+1·`next_dispatch_at = now() + min(30분, 60초 × 2^n) × [0.5, 1.0)`로 돌린다. 상한(`FEATURE_UPDATE_MAX_RETRIES`=5,
  약 31분)을 넘으면 같은 상태 술어에서 `failed`로 닫는다(claim 전 `queued`도 — 종전 `finish_update_request`는 running만
  닫아 launch 실패 request가 영원히 재발행됐다). `advance_update_request_generation_after_pre_start_failure`는 지웠다.
- executor: 실패를 `infra/failure_summary.py`로 요약한다 — SQLSTATE(55P03·40001·40P01·08xxx·57P0x·53300)·
  `connection_invalidated`·asyncpg 연결 예외로 **일시 DB 실패**를 가르고(명시적 `__cause__`·`orig`만 따른다,
  `__context__`는 정리 중의 다른 실패일 수 있어 따르지 않는다), 메시지는 SQL 본문·bind parameter·serviceKey·token·DSN
  비밀번호·Bearer를 걷고 300자로 자른다. 일시 DB 실패면 request를 **종결하지 않고** `FeatureUpdateTransientFailure`(분류·
  실패 단계)를 올린다 — 실패한 phase는 이미 되감겼고, 같은 연결로 terminal 쓰기를 하면 끊긴 연결에선 그것도 실패하고
  lock 경합이면 같은 lock을 다시 기다린다. 결정적 실패는 종전대로 닫되 `error_message`가 가장 안쪽 원인을 덧붙이고
  (`… ← 원인 Type: msg`, 머리는 종전 `Type: msg` 그대로), **모든** 실패가 terminal import job event
  (`FEATURE_UPDATE_EXECUTION_FAILED` 또는 provider의 좁은 code)에 분류·원인 연쇄·실패 단계·Dagster run id를 남긴다.
- Dagster 큐 op: `FeatureUpdateTransientFailure`와 claim 전 일시 DB 실패를 **새 연결로** `reschedule_update_request_after_failure`
  에 넘긴다 — 재발행이면 run SUCCESS + output metadata(`retry_scheduled`·다음 발행 시각), 상한이면 `failed`로 닫고 run
  FAILURE. failure sensor: `RUN_FAILURE` 이벤트의 `first_step_failure_event`에서 실패 step·오류 타입·메시지·가장 안쪽 원인을
  storage를 다시 읽지 않고 꺼내(`dagster/run_failure_detail.py`) 메시지와 payload에 싣는다. claim 전 실패는 backoff 재발행
  (상한), claim 뒤 실패(run이 도중에 죽음)는 재발행하지 않고 `FEATURE_UPDATE_RUN_FAILED`로 닫으며 PinVi relay에도
  `failed`를 낸다(종전에는 relay event가 없었다). 재발행 뒤의 PinVi "running" 재통지는 같은 payload라 replay로 접힌다.
- operation root(`dagster_run_terminal`): FAILURE 상태 sensor 반영 때 `failure_reason`·`failed_step`·`error_type`·`error`·
  `cause`를 더한다(reconcile·completion 경로는 이벤트가 없어 종전 모양). member attempt event(`feature_operation.attempt`)의
  `error`에도 분류·메시지·원인·step·run id를 싣는다(종전 code·type뿐).
- 관리자 화면: 실행 상세 이벤트 목록이 위 code 넷의 payload에서 승인된 필드만(분류·DB 실패 종류·실패 단계·실패 step·
  재발행 n/5·다음 발행·Dagster run) 보여 준다(`components/feature-update-failure-detail.tsx`). API·OpenAPI 변경 없음.
- 남은 구조 문제(이번에 고치지 않음): `import_job_event_clock` 단일 행을 긴 적재 transaction이 쥐는 것 — 재발행은 경합을
  분 단위로 기다려 줄 뿐 원인을 없애지 않는다.
- 시험: unit `tests/unit/test_failure_summary.py`, Dagster `test_run_failure_detail.py`·`test_sensors.py`(재발행·상한·결정적·
  원인 메시지), integration `test_feature_update_transient_retry.py`(backoff·peek 숨김·상한·owner·executor 미종결·terminal
  event·sensor 경로 상한), `test_feature_update_repo.py` 재발행 API로 이관, mocked e2e `ops-pipeline.spec.ts`
  "큐 요청 실패 원인·재발행 일정". head-schema.sql·migration graph·forward-only 목록 갱신.
## 2026-11-24 — 다건 호출 provider 호출 단위 재시도·쿼터 결과 코드 분류(감사 §4 #15·§1.3 P0/P1)

- 배경: `upstream_retry.py`의 설명과 달리 적용처는 KHOA 하나뿐이었다. 국가유산(행사 14달·본체 상세 ~4,000건)·
  산림청 페이지·TourAPI 축제/관광지 페이지·서울 책방·표준데이터 공개 파일·concierge export·MCST slug·MOIS LOCALDATA
  업종은 5xx·timeout 한 번에 asset(또는 op) 전체가 실패했고 step 재시도가 처음부터 다시 돌았다
  (`docs/reports/2026-11-23-collection-failure-audit.md` §1.3 P0).
- 새 판정 `dagster/upstream_transient.py`: HTTP 상태가 있으면 408·425·429·500·502·503·504만 일시 오류(2xx·3xx
  상태는 무시 — visitkorea·krforest가 결과 코드 오류에 200을 싣는다), 없으면 lib 분류(`retryable`,
  `failure_kind` network·server·timeout), 그다음 전송 계층 예외, 분류 속성 없는 lib의 일시 오류 타입 선언
  (datagokr `TransportError`·mois `MoisServerError`·mcst `McstNetworkError`), 마지막으로 명시적 `__cause__`.
  쿼터 소진은 언제나 거절. `Retry-After`(header 초·HTTP-date, `retry_after` 속성)를 읽는다.
- `upstream_retry`: `jitter`(equal jitter, 기본 꺼짐 — 상태 job 시험 결정성 유지), `retry_after`(대기 하한, 120초를
  넘으면 예산을 쓰지 않고 원 예외). 예산은 fetcher(dataset)마다 settings 비례 예산(`provider_upstream_retry_budget_*`,
  hard cap 32)이다 — run 공유 예산을 넓히던 첫 판은 적대 리뷰가 "settings 0으로 끄는 스위치가 먹지 않고 같은 run의
  transport·weather 상한까지 올린다"로 잡아 KHOA가 쓰던 방식으로 되돌렸다.
- 호출 지점 정책 `provider_fetchers.provider_call_with_retry`(ADR-006 — client를 감싸지 않고 public 메서드 하나를
  넘긴다): 시도 2회, 15초 기준 backoff + jitter. 적용: 국가유산 행사 달·목록 페이지·상세, 산림청 페이지(휴양림·
  산사태), TourAPI 축제·관광지 페이지, 서울 책방 페이지(키가 경로라 label에 넣지 않음, `SeoulOpenDataError.
  status_code` 추가), 표준데이터 공개 파일(재시도 단위 = 파일 하나, 행 중복 없음), concierge export 페이지,
  MCST slug(CSV를 다 받은 뒤 내보낸다 — 재시도 때 앞 행 중복 없음), MOIS LOCALDATA 업종(업종마다 한 번 commit,
  실패 시도는 session close가 버리고 upsert는 멱등), KHOA(같은 helper로 수렴). 시도마다 `note_upstream_request`
  (페이지네이터가 첫 시도를 세는 자리는 `count_retries=True`로 재시도만 더 센다). MCST slug 실패의 `retryable`도 같은
  판정을 쓴다. 결정적인 httpx 전송 오류(`UnsupportedProtocol`·`LocalProtocolError`)는 재시도하지 않고, datagokr
  `FILE_METADATA_CHANGED`(받는 중 파일이 바뀜)는 파일 단위로 다시 받는다.
- 쿼터(§1.3 P1): datagokr·krheritage `ApiErrorResponse.code`, mois `MoisError.result_code`가 `22` 또는
  메시지 `LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS`면 일일 쿼터(`quota_exhaustion.RESULT_CODE_QUOTA_ATTRIBUTES`,
  모듈 한정). 핀 SHA 소스로 신호가 이미 예외에 있음을 확인해 provider 수정은 필요 없었다.
- 남김: datagokr fileData(odcloud) `iter_pages`는 provider 안 순회라 호출 단위로 못 끊는다(해당 dataset은 활용신청
  미완으로 꺼져 있다). 단건 호출(knps·산림청 SHP)은 step 재시도로 충분해 두었다.
- 시험: `packages/kor-travel-map-dagster/tests/test_provider_call_retry.py`(분류 표·Retry-After·jitter·예산 공유·
  fetcher 9곳·실물 datagokr/krheritage/mois 예외 계약). OpenAPI·migration 없음.

## 2026-11-23 — R4 전환 계획 제외 옵션: 정밀도 미달 쌍을 계획 파일을 고치지 않고 뺀다

- 배경: R4 준비 계획(읽기 전용, `plan_sha256 3f93a4b7…`)의 표본 판정에서 `barrier_free_places` collapse
  (0.94~0.96 — 한 복합 건물 주소의 다른 시설이 0 m로 접힘)와 `world_restaurants` collapse(0.81~0.92 — 다른
  주소의 체인 지점이 접힘)가 게이트 0.97을 못 넘었다. 계획기·실행기 어느 쪽에도 쌍을 빼는 길이 없었고
  `plan.json`을 손으로 고치는 것은 설계 위반이다.
- `mcst-theme-plan --exclude <dataset>:<action>`(반복). dataset은 dataset_key 또는 slug(`_csv` 생략 가능)로
  받아 dataset_key로 기록한다. 제외된 행은 `keep`으로 다시 쓰지 않고 계획의 `excluded_items`에 원래 action·
  대상·`row_revision` 그대로 남긴다(효과는 `keep`과 같다) — 판정(보고서 `by_dataset`·표본)과 운영 결정
  (`exclusions`)을 섞지 않아 표본 감사가 제외 전후로 같은 숫자를 본다. `exclusions`·`excluded_items`가
  `plan_sha256`에 들어 승인한 sha가 "하지 않을 것"까지 고정한다(아무 행도 빼지 않는 제외도 sha를 바꾼다).
- 실행기: `--exclude`를 다시 받아 계획의 제외와 정확히 같을 때만 돈다(리허설 포함, DB 접근 전 종료 코드 2).
  `load_transition_plan`은 제외 쌍의 행이 `items`에 있거나, 제외에 없는 쌍이 `excluded_items`에 있거나,
  남는 전환이 제외된 Feature를 대상으로 하거나, 같은 Feature가 두 번 있으면 거부한다.
  `execute_transition_batch`도 제외 쌍의 행을 받으면 잠금·쓰기 전에 거부한다(라이브러리 직접 호출 방어).
- sha 정의가 바뀌어 이전 형식 계획 파일은 "옛 형식"으로 거부한다 — 운영 창에서 어차피 새로 뽑는다. 계획은
  여전히 `SET TRANSACTION READ ONLY` 하나이고 제외는 읽은 뒤 메모리에서만 적용한다.
- 시험: unit `tests/unit/test_mcst_theme_plan_exclude.py`(파싱·계획 내용·sha·변조 거부·실행기가 `items`만
  넘김·불일치 거부), integration `test_excluded_pair_is_left_untouched`(실 PostGIS: 제외 행 active·revision
  불변·사건·장부 0, 같은 batch의 attach는 전환). OpenAPI·migration·PinVi 재vendor 없음.

## 2026-11-23 — 관리자 프런트 ui 0.2.5(입력·선택 컨트롤 focus 정본화)와 Map 덧대기 제거

- `@kor-travel/ui` 0.2.4→0.2.5·tokens 0.1.5→0.1.6(common #81 `fe141143`, main CI artifact 14782962353
  ZIP `sha256:065bfbdf…`; sha256·SRI가 catalog #82 `ade7b3eb`와 같음)를 vendor하고 guard·`common-ref`를 `ade7b3eb`로
  올렸다. toast 0.1.5는 Map이 쓰지 않아 받지 않았다. ui·tokens 의존 목록은 그대로이고 ui peer만 tokens 0.1.6이다.
- 공통 0.2.5 Input·NativeSelect·SelectTrigger·Textarea·Checkbox·Switch·Badge 등이 FS-7.8 단일 outline 2px·offset 2px
  (`outline-kt-focus`)를 직접 내고 체크박스 터치 영역이 md 미만 44px가 됐다. Map wrapper(`input`·`native-select`·
  `checkbox`·`textarea`·`form-*`)에는 덧대기가 없었다. 중복이던 두 곳을 지웠다: `badge-variants.ts`의
  `focus-visible:outline-2/offset-2/outline-focus`(공통 Badge가 같은 값), 파이프라인 요청 대화상자 dry-run 원시
  `<input type="checkbox">`의 같은 세 클래스(`@layer base` `:focus-visible`이 같은 값을 그린다).
- 시험: vitest `field-focus.test.tsx`는 Input·NativeSelect·Checkbox·링크 Badge의 focus 클래스가 정확히 세 개이고
  체크박스에 `max-md:after:-inset-[15px]`가 있음을 본다. Playwright `admin-shell.spec.ts`에 `/ops/logs` 입력·선택의
  Tab 포커스 2px outline 하나·ring·테두리 변화 없음 검사를 더했다.
- Map admin OpenAPI 변경 없음, 마이그레이션 없음.

## 2026-11-23 — 파이프라인 필터 e2e 간헐 실패: 화면이 router의 늦은 `searchParams`를 읽었다

- 증상: `ops-pipeline.spec.ts` "필터가 executions 쿼리 파라미터로 전달된다"가 가끔 `running|101|`(sync_scope 없음)로 실패.
  n150 mocked e2e 재현(main `5586635a`, `--repeat-each=20 --retries=0`): workers 2에서 2/20·4/20, workers 4·40회
  (고친 첫 판)에서도 5/40. 실패 화면은 provider 101, scope 칸은 활성인데 비어 있었다 — 입력이 사라졌다.
- 원인: 화면이 필터를 router의 `useSearchParams`에서 읽었다. Next 16은 same-route `history.replaceState/pushState`를
  **transition**으로 router 상태에 옮기므로 ① `searchParams`가 방금 쓴 URL보다 늦고 ② 이어진 쓰기가 따로·늦게 commit되며
  ③ 늦은 commit의 `HistoryUpdater`가 그 시점 canonical URL을 브라우저에 다시 써 `window.location`도 잠깐 되돌린다.
  빠른 입력(상태 → ID → scope)에서 두 경로로 scope를 잃었다. (a) provider blur가 draft를 버리면 낡은 URL의 빈 ID가 렌더돼
  scope 칸이 비활성으로 바뀌어 포커스·입력을 잃었다 — 같은 task에서 입력 → 포커스 이동을 하는 새 시험이 main에서
  **20/20** 실패(blur 직후 provider `""`·scope disabled). (b) URL 기준 사본(ref)이 늦은 commit에 덮여 provider 없는 URL을
  만들면 triple 규칙이 scope를 지웠다. stress trace에서 scope가 실린 요청은 0건이었고, provider가 반영된 뒤 status만 있는
  요청이 다시 나온 run도 있었다(router 상태 자체의 일시 역행).
- 고침: `useOwnedSearchParams`(새 파일) — 화면이 쓴 query를 같은 렌더의 상태로 들고, router commit은 우리 쓰기(중간·순서
  뒤바뀜 포함)면 무시하고 우리가 쓴 적 없는 commit만 외부 이동으로 받는다(popstate는 대기 목록을 비운다). 파이프라인
  화면의 모든 URL 읽기·쓰기가 이것을 쓴다. 중간 시도 둘(location 기준, 쓴 query ref + blur 보존)은 workers 4에서 각각
  3/20·2/40 실패로 부족해 대체했다. 재시도·sleep은 더하지 않았다.
- 검증(n150 `~/gate-slot.sh`, io-guard 통과 뒤): 원 시험 + 새 시험 workers 4·`--repeat-each=40 --retries=0` **80/80**(두 차례),
  ops-pipeline·admin-shell·home-nav 전체 193 passed, static(check-deps·lint·doctor·vitest·type-check·build) PASS. vitest
  `use-owned-search-params.test.ts`가 늦은·뒤바뀐 commit 무시와 외부 commit 수용을 고정한다. **frontend 코드 변경 — 운영
  반영은 다음 회전.** OpenAPI·migration 없음.

## 2026-11-23 — 읽기 성능 원장 정리: T-READ-12 완료·T-READ-06 보류·T-READ-07 스냅샷 정정

- `T-READ-12` 완료: 회전 t1122a(Map `7a44cf94`, api·ui·dagster-code-server 이미지 revision 일치, 배포 코드에
  `force_custom_plan` 확인) 뒤 2026-11-22 02:49Z 조용한 창(공용 Dagster instigator 69개 정지·run 0, 측정 뒤 그대로 복원)에서
  probe `--warmup-per-case 90`·30회로 쟀다(측정 이름 tread1122a). zoom 7 sido 집계 server p50/p95 **185/642 → 158/191 ms**
  (이전 tread1121c). pool 15 연결마다 6번째 실행을 넘긴 뒤에도 p95가 custom plan 범위(147–191 ms)라 연결 나이와 무관하다.
  다른 case는 오차 범위(zoom 14 122/185 → 92/118, 부산 맛집 435/538 → 437/543). acceptance 마지막 항목을 닫고 tasks-done으로 옮겼다.
- `T-READ-06` **기준 미달 보류, 브랜치 보존**: `feat/t-read-06-search-keys`(`8ecb449e`, alembic 455 시절, 미머지)는 순서
  동등(평가 묶음 63개 × 3페이지)을 보였지만 운영 사본 부산 맛집 p50 감소가 −25.7%·−24.9%로 40% 기준 미달이다. main에는
  들어가지 않았으므로 revert할 것이 없고 브랜치는 지우지 않는다. 기준 조정 머지 여부는 소유자 결정 — tasks.md 보류 항목으로 옮겼다.
- `T-READ-07` 정정: 2026-11-19 기록의 "첫 스냅샷 미촬영"은 틀렸다. 첫 스냅샷은 2026-11-18 23:02Z(t1118e)에 읽기 전용으로
  찍었다(`features` heap 397 MB·색인 756 MB, HOT 갱신 0/59,249). 둘째는 2026-12-03 무렵.
- `T-READ-02`는 acceptance 마지막 항목(운영 `slow_request` 줄)이 2026-11-19에 이미 닫혀 있고 tasks-done에 있다 — 바꾼 것 없음.
- journal이 215,784 B로 §8의 200 KB 경계를 넘어 있어 2026-10-24~28의 완전한 절 91개를
  [journal-2026-10j.md](archive/journal-2026-10j.md)로 원문 그대로 옮겼다(상대 링크만 재기준화, 역변환으로 원래 구간과 바이트
  일치 확인). live에는 제목 stub을 남겼다.

## 2026-11-22 — 관리자 nav 라벨 = 페이지 제목(SSR 제목 깜빡임)·페이지 경계 버튼 비활성 사유

- 증상: #1533 뒤 서버 렌더 첫 화면의 상단 바 제목은 nav 정본 라벨이고, hydration 뒤에는 페이지가 `AdminPageTitle`로 등록한
  제목이다. 네 화면이 달라 첫 화면에서 제목이 한 번 바뀌었다(`/` 홈→운영 홈, 수동/provider 판정→수동/provider 중복 판정,
  큐레이션 후보→큐레이션 후보 검토, 캐시 전파→캐시 전파 스트림).
- 고침: nav 라벨을 더 설명적인 페이지 제목에 맞췄다(390px drawer·rail에 한 줄로 들어간다). 단위 시험
  `admin-nav-titles.test.ts`가 nav 21개 항목마다 `page.tsx` metadata 제목과 그 화면 `<AdminShell>`의 정적 `title`이 nav 라벨과
  같은지 소스에서 확인한다(찾지 못하면 실패).
- 페이지 경계 버튼(첫 페이지·이전·다음·마지막 페이지)은 native `disabled`라 왜 안 눌리는지 말하지 못했다. 공용 `PagerButton`을
  `focusableWhenDisabled` + 사유("첫 페이지입니다"/"마지막 페이지입니다", 전체 페이지 수 미상)로 바꿔 모든 `OffsetPager`·
  `CursorPager`에 적용했다. 경계에 닿아도 방금 누른 `다음`이 포커스를 잃지 않는다. Playwright `toBeDisabled()`는
  `aria-disabled`도 비활성으로 읽어 기존 계약은 그대로다.
- 시험: e2e `admin-shell.spec.ts` 네 화면의 SSR HTML h1 = hydration 뒤 h1(파서 삽입부터 MutationObserver로 기록한 제목이
  하나뿐), `ops-pipeline.spec.ts` 타임라인 경계 버튼 `aria-disabled`·접근성 설명·tooltip·포커스 유지. OpenAPI·migration 없음.

## 2026-11-22 — 관리자 셸을 루트 레이아웃으로: drawer 이동 뒤 포커스가 BODY로 떨어지던 결함

- 증상(n150 prod 390px 점검): drawer 메뉴를 클릭·Enter로 이동하면 포커스가 `#main-content`가 아니라 BODY. 클릭 때는 약
  200 ms 동안 옛 화면의 main에 머물다 BODY로 떨어졌다.
- 원인: 페이지 client 24곳이 각자 `<AdminShell>`(공통 `AdminShell` 래퍼)을 그렸고 루트 `layout.tsx`에는 셸이 없었다. 경로가
  바뀌면 셸 트리 전체가 다시 마운트된다. 공통 0.2.4 `useDrawer`의 `returnToMain`은 셸 내부 state라, 옛 셸이 drawer 닫힘
  애니메이션(~200 ms) 뒤 `onCloseAutoFocus`로 **옛** main에 포커스를 주고 곧 그 노드가 사라져 BODY가 된다. 공통 셸은
  레이아웃 배치(`navigationKey` + `AdminPageTitle`)를 이미 지원하므로 공통 릴리스는 필요 없었다.
- 고침: `AdminShellFrame`(공통 셸 + 메뉴·브랜드·로그아웃, `navigationKey={pathname}`, SSR 첫 제목은 nav 정본 영역·라벨)을
  루트 레이아웃에 한 번 둔다. `/login`은 셸 없이. 페이지 `AdminShell`은 props 그대로 `AdminPageTitle`로 제목·설명·동작을
  등록하고 본문 여백·meta 줄만 그린다 — 페이지 파일 24곳은 바꾸지 않았다. design.md에 배치 규칙을 적었다.
- 시험: Playwright `admin-shell.spec.ts` 390px drawer 이동(클릭·Enter) 뒤 애니메이션 종료를 기다려 `expect.poll`로
  `document.activeElement`가 `#main-content`이고 셸 노드가 그대로인지 본다(고치기 전 빨강 확인). vitest는 셸 노드·main이
  경로 변경 사이에 같은 노드인지, `/login`은 셸이 없는지. OpenAPI 변경 없음. 배포하지 않았다.

## 2026-11-21 — 관리자 프런트 소수정 셋: drawer e2e flake·모바일 44px 터치 표적·파이프라인 비활성 사유

- `admin-shell.spec.ts` "mobile: 메뉴 버튼이 좌측 drawer를…"의 간헐 실패는 drawer `slide-in-from-left` 도중 `boundingBox().x`를
  잰 것이다(x<0). `data-state=open` → `getAnimations()` finished → `expect.poll(x)==0`으로 바꿨다(임의 sleep 없음).
- 모바일(md 미만) 상단 바 동작은 라벨이 숨어 32px 아이콘 버튼이었다. 셸 동작 래퍼(`map-shell-actions`)와 icon 크기 Button에
  `max-md:min-h-11 max-md:min-w-11`(44px)을 걸었다 — 데스크톱은 h-8 그대로. 메뉴 버튼·drawer 닫기는 공통 셸이 이미 44px.
- `Button`에 opt-in `focusableWhenDisabled`: 사유(`disabledReason`)가 있는 비활성을 native `disabled` 대신 `aria-disabled`로
  두고(활성화는 onClick에서 막음) hover/focus tooltip + 상시 `aria-describedby`(sr-only 형제)로 사유를 노출한다. 파이프라인
  페이지 동작 버튼(헤더 갱신 요청 생성·요청 dialog·스케줄 명령/cron/claim·실행 취소/run-now)에 적용하고 스케줄 잠금
  사유(`scheduleControlsDisabledReason`)를 채웠다. 다른 화면은 그대로(native disabled + `title`).
- 시험: vitest `button.test.tsx`(icon 크기 min-size·opt-in 의미), Playwright 모바일 44px·데스크톱 32px, 파이프라인 사유
  tooltip/설명(`toHaveAccessibleDescription`). OpenAPI 변경 없음. 배포하지 않았다.

## 2026-11-21 — T-READ-12 저배율 집계가 연결 6번째 실행부터 generic plan으로 뒤집힘

- 증상(운영 읽기 전용 조사): `/v1/features/in-bounds` zoom 7 sido 집계(pg_stat_statements queryid
  -1199203723901693282, API mean 480 ms·stddev 370)가 정상상태 ~630 ms, 꼬리 1–4 s, read_timeout 503 하나.
- 원인: asyncpg는 집계 SQL을 연결마다 prepared statement로 재사용하고 `plan_cache_mode=auto`는 6번째 실행부터
  generic plan을 고려한다. generic plan은 bbox 선택도를 기본값으로 봐(rows=1) `idx_feature_cluster_points_coord_gist`
  직렬 scan을 고른다(685–902 ms). custom plan은 Parallel Seq Scan + HashAggregate(147–191 ms). 세션에서
  `force_custom_plan`이면 146–154 ms, 계획 비용 약 7 ms. harness·tier-1 gate는 매번 `EXPLAIN`으로 계획해 이 전환을
  볼 수 없었다.
- 고침: `_CLUSTER_HASH_AGGREGATE_ON_SQL`/`_OFF_SQL`이 `enable_sort`와 같은 문장에서 `plan_cache_mode`를
  `force_custom_plan`으로 두고(transaction-local) 집계 뒤 직전 값으로 되돌린다. harness·tier-1 gate는 같은 상수를
  import하므로 그대로 따라온다. `scripts/read_path_probe.py`에 case별 warm-up(`--warmup-per-case`, 기본 6 × pool 15 =
  90, 분위에서 제외)을 더해 결과가 연결 나이에 흔들리지 않게 했다.
- 시험(n150 gate-slot, testcontainers pg18): 같은 연결에서 sido 집계 8회 뒤 그 prepared statement의 `generic_plans`가
  0이고 EXPLAIN이 HashAggregate·좌표 GiST 없음(전 kind·point-only 두 변형). 고침을 되돌리면(`force_custom_plan` →
  `auto`) 두 변형 모두 `generic_plans` +3·`custom_plans` +5로 빨개진다 — 시드 840행에서도 운영과 같은 6번째 전환이
  재현된다. 관련 통합·probe unit 19 passed.
- 다른 hot 질의 점검(운영 읽기 전용, 2026-11-21 10:39Z, io-guard 0, pg 18.6, `SET LOCAL ROLE ktm_feature_service`,
  harness viewport의 SQL·인자를 SQL `PREPARE` 뒤 같은 연결에서 auto 8회 + `force_custom_plan` 4회, 중앙값 ms):
  sido point-only 108 → **953**(6~8회 1,519·953·620, 강제 custom 114), sido 전 kind 222 → **654**(강제 172) — 고친 대상.
  items in-bounds(같은 `_FEATURES_IN_BBOX_SQL`)는 6번째부터 generic(Nested Loop, `idx_features_coord_gist`)을 고르지만
  갈린다 — 서울 zoom 14 500건은 172 → 83(generic이 더 빠름), 서울 밀집 200건은 52 → 79(6번째 1회 536). 같은 prepared
  statement를 두 화면이 나눠 쓰므로 강제하면 한쪽이 손해라 **고치지 않았다**. 100 km nearby(14/12/11)·카페(146/172/149)·
  부산 맛집(407/429/423)·서울 맛집(166/166/166)은 generic을 한 번도 고르지 않았다(custom 비용이 더 낮다).
- OpenAPI·migration 변화 없음. 배포하지 않았다(부모 통합 회전).

## 2026-11-21 — 관리자 프런트 ui 0.2.4(TabsTrigger focus 정본화)와 Map 탭 override 제거

- `@kor-travel/ui` 0.2.3→0.2.4·tokens 0.1.4→0.1.5(common #79, main pack `9691080c`, docs run 44882394234 artifact
  14698374408; sha256·SRI가 catalog #80과 같음)를 vendor하고 guard·`common-ref`를 `c3f8e6a1`로 올렸다. toast 0.1.4는
  Map이 쓰지 않아 받지 않았다(0.2.3 채택 때와 같음). ui·tokens 의존 목록은 그대로이고 ui peer만 tokens 0.1.5다.
- 공통 0.2.4 TabsTrigger focus가 FS-7.8 단일 outline 2px·offset 2px(`outline-kt-focus`)가 되어 Map
  `components/ui/tabs.tsx`의 0.2.3용 덧대기(`focus-visible:border-transparent`·`ring-0`·`outline-focus`·전환 좁히기)를
  지우고 공통 Tabs를 그대로 다시 내보낸다.
- 시험: vitest `tabs.test.tsx`는 트리거의 `focus-visible:` 변형이 정확히 `outline-2`·`outline-offset-2`·`outline-kt-focus`
  셋이고 ring 유틸·`transition-all`이 없음을 본다. Playwright `admin-shell.spec.ts` 탭 포커스 검사에 테두리 색 불변을 더했다.
- Map admin OpenAPI 변경 없음. 배포하지 않았다(부모 통합 회전).

## 2026-11-21 — T-READ-11 검색 접기 대표 판정이 hashed SubPlan으로 뒤집힌 회귀("부산 맛집" 382→575 ms)

- 증상: n150 prod "부산 맛집" 서버 p50이 기준선(T-READ-01) 382 ms에서 575 ms로 올랐다. 코드 변경이 아니라 계획 변경이다.
- 원인(읽기 전용 EXPLAIN ANALYZE): `dedup_ordered`의 MCST 판정 `EXISTS (…)`를 Postgres가 `ANY`로 바꿔 hashed SubPlan
  대안을 함께 만들고, `source_links`/`source_entities` autoanalyze 뒤 hashed 쪽을 골랐다 — 질의마다 MCST primary
  88,526행 전부로 해시를 지었다(~176 ms). 실제로 판정이 필요한 행은 무리가 둘 이상인 소수다.
- 고침: 판정을 상관 스칼라 부분질의 `(SELECT true … LIMIT 1) IS NOT NULL`(`_SEARCH_DEDUP_DEMOTED_PRIMARY_SQL`)로 —
  LIMIT 스칼라 부분질의는 hashed SubPlan이 될 수 없어 행마다 `source_links` 인덱스로 찍는다. 읽기 전용 실측:
  부산 맛집 585 → 383 ms(같은 51행), 서울 맛집 144 → 157 ms(+13, 수용). OpenAPI·migration 변화 없음.
- 시험: 종전 `EXISTS`로 되돌린 SQL과 같은 행·같은 순서(통합), 판정 SubPlan이 hashed가 아님(계획 모양, 통합).
  함정: pg18 `EXPLAIN (FORMAT JSON)`의 `Subplan Name`에는 "hashed"가 없다 — hashed는 그 SubPlan을 참조하는 식에만
  `(hashed SubPlan N)`으로 찍힌다. 이름만 보던 첫 판은 종전 `EXISTS`에도 초록이었다(n150에서 빨개지게 해 보고 발견).
  고친 판은 VERBOSE 식 참조를 보며, 종전 `EXISTS`는 이 시드에서도 hashed로 계획되어 빨개진다.

## 2026-11-21 — CI 통합 job 35% 정체(6시간 취소)의 원인: nearby 동등성 시험의 통계 공백 + 강제 계획 실행

- 증상: `pytest integration (PostGIS, pg18)`이 `01b602e3`(#1523)부터 35% 줄 뒤에 멈춰 6시간 뒤 취소(run
  44632917554·44667945938, 그리고 다음 push로 취소된 44806776288도 같은 자리에서 1시간 45분 정체). 통과한
  런도 같은 구간(전체 1,815건 중 649~720번)이 **17~23분** 걸렸다 — #1520(T-READ-09, `2e58b828`)부터. 그 전
  (#1519·454)은 1.5분. 즉 #1522(455 trigger·병렬 집계)가 아니라 #1520이 들인
  `tests/integration/test_features_nearby_equivalence.py`가 출처다. #1523은 우연히 겹쳤다.
- 재현(n150, CI와 같은 한 세션 전량, `--durations`, 60초마다 `pg_stat_activity`·`pg_locks` 스냅숏): KNN 시험
  581초, coord page walk 543초, target walk 166초 — 이 셋이 CI의 17~23분이다. 정체 동안 **대기 잠금은 0건**,
  backend는 `active`로 CPU를 썼다 — lock wait·deadlock이 아니다.
- 원인: 그 시험의 `_seed`가 provider 계보 표(`source_links`·`source_entities`·`source_entity_heads`·
  `source_records`)와 `feature_notices`에 1천여 행씩 넣고 `features`만 ANALYZE했다. 세션 DB에서 그 표들은
  한 번도 분석되지 않아(`reltuples = -1`) planner가 행 수를 1로 본다. 그래서 공개 notice 감산 subplan을 색인
  조건 없는 중첩 루프(`pk_source_entity_heads`를 filter로 66만 번 훑기)로 풀었고, 같은 파일의 앞 시험들이
  남긴 상태에서 **행 11개 page 한 문장이 130초**(2.9억 buffer hit)였다(기본 planner 설정, EXPLAIN ANALYZE 실측).
  KNN 시험은 거기에 `enable_seqscan/bitmapscan = off`를 걸고 그 강제 계획을 **실행**했다 — 모든 표의 접근
  경로가 비틀린 계획이라 n150에서 문장 하나 4분+, CI에서는 끝나지 않았다. 비용이 앞 시험이 남긴 표 상태에
  따라 세제곱으로 커져 간헐적이었다.
- 고침: ① `_seed`가 쓴 표 전부를 ANALYZE(transaction 안 ANALYZE는 자기 미commit 행을 센다). ② KNN 시험은
  강제 스위치 아래 계획을 세우기만 하고(실행 안 함) "KNN scan 바로 위가 `Limit`"으로 조기 정지를 본다 —
  후보의 `FETCH FIRST … WITH TIES`를 지우면 빨개지는 것을 확인했다. ③ CI 통합 job에 시험 하나 600초
  (`pytest-timeout`, thread 방식 — 이름과 stack을 찍고 끝낸다)와 job 90분 상한, 수동 PostGIS workflow도 같은
  시험 상한. 결과(n150): coord walk 543→4.3초, target 166→4.1초, KNN 581→0.7초.
- 제품 SQL은 바꾸지 않았다 — 운영 DB는 통계가 있다. 같은 모양(행마다 도는 notice 감산)이 통계 없는 표에서
  무너진다는 것은 시험 시드가 큰 표를 새로 채울 때 함께 ANALYZE해야 한다는 뜻이다.
- 이 절로 journal이 225,297 B가 되어 §8 경계를 넘었다 — 2026-10-24의 완전한 절 23개를
  [journal-2026-10i.md](archive/journal-2026-10i.md)로 원문 그대로 옮겼다(상대 링크만 재기준화, 옮긴 조각과
  원래 구간 바이트 일치 확인). live에는 제목 stub을 남겼다.

## 2026-11-21 — C7 prod GREEN(t1121b, Map `24ffd5a2`) — 네 spec 전부 통과

- 결과: runner rc=0, lane 잔여 없음(audit rc=0), evidence `run-20261120T230130Z-3626497`. spec별 —
  `ops-c7-read-auth` 7/7, `poi-cache-targets-write` @c7-causal 2/2, `ops-c7-update-request-write` 2/2,
  `ops-c7-schedule-write` 2/2. 마지막 GREEN(`bafec797`, 10-03) 이후 첫 GREEN이다.
- 이번 회차에서 고친 것: #1524(파이프라인 "새로고침" 둘 — 공통 Dagster 패널), #1525·#1526(logout 순서가
  acde3726부터 "성공 응답 뒤 close(1000)" — 관측점을 close 호출 기록으로), 그리고 **운영 설정** 하나 — C7의
  `/root/.d2-dagster-basic-auth`가 2026-10-01 값이라 gateway가 401을 냈다(소유자가 10-24 Dagster UI 비밀번호를
  바꿈). 현재 `.env`의 `KOR_TRAVEL_DAGSTER_UI_PASSWORD`로 다시 썼다(root 0600 한 줄, 옛 파일은 `.bak-<UTC>`).
  Dagster UI 비밀번호를 바꾸면 이 파일도 같이 바꿔야 한다.
- 복구: BLOCKED 네 번(t1120b·t1120c·t1121a·t1121b) 모두 runbook §4로 — journal·sentinel을 root 전용
  `/root/c7-recovery-<tag>-<UTC>/`로 복제·SHA-256 기록, 읽기 전용 검증(C7 소유 target 0, schedule RUNNING,
  활성 실행 0) 뒤 runtime·BLOCKED를 그 디렉터리로 **이동**(삭제 없음). 운영 쓰기는 매번 target `restored`.
- 회전: t1120c(`db8497f2`)·t1121a(`9663598b`)·t1121b(`24ffd5a2`), 모두 chain17 + freeze, D1·D2 GREEN, PinVi `716781d0` 그대로.
- 남은 것: main CI의 `pytest integration (PostGIS, pg18)`이 `01b602e3`(#1523)부터 35% 지점에서 6시간 멈춘다
  (#1522 `c5bae138`까지는 통과, #1523은 Python 변경 없음 — 간헐 hang 추정, 원인 미규명). #1524~#1526은 그 위에서 병합했다.

## 2026-11-21 — C7 t1121a: logout 관측점을 `close()` 호출 기록으로(#1525 방식은 page 평가가 막힘)

- #1525(t1121a, Map `9663598b`) 뒤에도 `LAST: 실제 로그아웃` 1건 실패(38.4초, 나머지 6건 GREEN, target `restored`).
  #1525는 /login 문서 이동을 `page.route`로 붙잡고 그 사이 옛 문서에서 close code를 읽으려 했는데, **문서 이동을 붙잡은
  동안에는 page 평가가 진행되지 않는다**(자체 세션 probe: close 대기 5초 timeout, redirect 미완).
- 붙잡지 않으면: logout 응답 200 뒤 24 ms에 /login 문서가 commit되어 close handshake가 끝나기 전에 문서가 바뀐다 —
  JS `close` 이벤트도 Playwright `close` 이벤트도 옛 문서에서 나지 않는다. 결정적인 사실은 앱이 redirect **전에 동기로**
  `close(1000)`을 부른다는 것.
- 고침: init script가 `WebSocket.prototype.close`의 ops live 호출을 같은 탭 sessionStorage에 남기고(click 전 비움),
  /login 도착 뒤 읽는다. 단언은 logout 응답 ok·close 호출 code 1000·|호출−응답| ≤ 2초·ticket/socket 재생성 없음.
  자체 세션 probe로 동일 기제 확인(close 호출 1000, 응답과 -2 ms, 31초 동안 재연결 0).

## 2026-11-21 — C7 t1120c: read-auth 6/7, 마지막 logout 시험은 spec의 순서 가정이 낡음

- #1524 배포(t1120c, Map `db8497f2`) 뒤 C7 `ops-c7-read-auth` 7건 중 6건 통과(count/state·4401·4408 복구·rotation·
  projection 복원 모두 GREEN), `LAST: 실제 로그아웃` 1건이 7.2초에 실패. 운영 쓰기는 target 하나가 `restored`로 끝났다.
- 원인: `acde3726`(2026-10-05)이 로그아웃 순서를 "socket close → logout POST"에서 "logout POST **성공 뒤**
  `publishAdminLogout`(close 1000) → /login"으로 바꿨다(실패한 logout은 live를 유지하고 재시도). spec은 logout
  **응답을 붙잡고** close를 기다려 교착 → 5초 뒤 route handler throw. 마지막 C7 GREEN(`bafec797`, 10-03)은 그 이전이다.
- 고침(spec만): logout 요청은 건드리지 않고 `/login` 문서 이동을 잠깐 붙잡아 옛 문서에서 close code 1000을 읽는다.
  단언은 logout 응답 ok·redirect 전 close 1000·응답 뒤 close 지연 ≤ 2초·ticket/socket 재생성 없음.

## 2026-11-20 — C7 `ops-c7-read-auth` 첫 시험 5초 실패: 파이프라인 화면의 "새로고침" 둘

- t1120b(Map `01b602e3`) C7 첫 시험이 5.06초에 실패했고 나머지는 serial이라 건너뛰었다(journal 모두 `*_pending`, 운영 쓰기 없음).
  기대 시간 상한(15초)보다 짧아 재시도 없는 실패, 즉 strict locator 위반이다.
- 운영 UI에 읽기 전용 Playwright probe(C7 실행 이미지, 로그인·화면 이동·GET 새로고침만)로 재현: 데이터셋 요약·딥링크·
  파이프라인 h1은 모두 통과, `/ops/pipeline`에서 `getByRole("button", { name: "새로고침", exact: true })`가 **2개** —
  상단 바 동작과 실행 탭의 공통 Dagster 운영 패널(`@kor-travel/ui` DagsterOperations, `data-slot="dagster-operations-refresh"`).
- 그 패널은 2026-10-05 `acde3726`에서 들어왔고 마지막 C7 GREEN은 그 전(`bafec797`, 10-03)이라 이번이 그 뒤 첫 C7이었다.
  #1523(공통 AdminShell)의 원인이 아니다. 고침: spec의 새로고침 세 곳을 공통 셸 `data-slot="admin-shell-actions"` 안으로
  한정(`shellRefreshButton`). probe로 두 화면 모두 1개·enabled 확인.
- 남은 일: C7 lane은 BLOCKED 그대로(runbook §4 복구는 소유자), 다음 회전에서 C7 재실행.

## 2026-11-19 — 관리자 프런트 공통 AdminShell(ui 0.2.3) 채택과 버튼 테두리(FS-7.8)

- `@kor-travel/ui` 0.2.1→0.2.3·tokens 0.1.2→0.1.4(common #70·#71, main pack `0e2a3f5a`, SRI는 원장과 같음)를
  vendor하고 guard·`common-ref`를 `d644632e`로 올렸다. toast는 Map이 쓰지 않아 받지 않았다. 0.2.2의 VirtualTable
  변경은 바깥 `min-w-0` 한 줄이다.
- 자체 rail·헤더 셸(`components/admin-shell.tsx`)을 공통 `AdminShell`+`AppMenu`로 바꿨다. lg 이상은 좌측 rail(접힘 키
  `kor-travel-map:sidebar-collapsed`, 기존 "1"/"0" 유지), 그 아래는 상단 바 메뉴 버튼 → 좌측 drawer다(예전엔 메뉴가
  상단 가로 띠로 펼쳐졌다). 맨 위는 한 줄(약 48px) 상단 바: h1 "영역 - 페이지"(영역 = nav 그룹, 홈은 "개요"), 페이지
  설명은 같은 줄에 작게(말줄임, 전체 문장은 title), 동작은 오른쪽 — md 미만에서는 라벨을 숨긴 아이콘 버튼
  (`ShellActionLabel`, 접근성 이름 유지). 워드마크 옆 "admin" 같은 앱 설명은 지웠고 breadcrumbs(2화면)는 상단 바에
  들어가지 않아 없앴다(같은 목적지가 동작 버튼에 있다). 여러 값 요약(`meta`: 백업 저장소·데이터셋 상태)은 본문 맨 위 한 줄.
- nav 정본을 `lib/admin-nav.ts`로 분리하고 페이지 metadata를 "영역 - 페이지 | kor-travel-map"으로 맞췄다. 공통
  `formatAdminTitle`은 `"use client"` 모듈이라 서버 metadata에서 부를 수 없어 같은 규칙을 로컬에 두고 시험으로 둘을 묶었다.
- 버튼 테두리 원인: Map `buttonInteractionClasses`의 **조건 없는 `outline-solid`**. 0.2.1 공통 recipe의
  `outline-none`을 이기려고 붙였는데, twMerge가 `outline-none`을 지운 자리에서 `outline-style: solid`가 상시로 남아
  모든 버튼에 기본 폭(medium = 3px) currentColor outline이 그려졌고, 포커스 때는 그 위에 `focus-visible:border-ring`
  색 테두리까지 겹쳤다. 0.2.3 공통 recipe가 focus를 outline 2px·offset 2px(`--kt-focus`)로 직접 내므로 Map 덧대기
  (`outline-solid`·`focus-visible:outline-*`·`ring-0`)를 모두 지우고 disabled 도달성(`disabled:opacity-100
  disabled:pointer-events-auto`)만 남겼다. globals.css에는 unlayered 버튼 상태 규칙이 없었다(`@layer base`의
  `:focus-visible` 하나와 `font: inherit`만). 옛 `.map-common-menu[data-collapsed]` 접힘 CSS는 AppMenu `compact`로 대체.
- 시험: vitest `admin-shell.test.tsx`(제목 형식·설명·meta·help·nav 21·접힘 키 형식·drawer 열고 링크로 닫힘),
  `admin-nav.test.ts`(공통 함수와 같은 문자열·영역 유도·문서 제목), `button.test.tsx`(7변형 모두 focus outline 한 벌·상시
  outline·ring 없음). Playwright `e2e/admin-shell.spec.ts`(PC 1280·모바일 390: 상단 바 한 줄·작은 설명·문서 제목, 모바일
  drawer 열기·닫기 버튼·메뉴 이동 뒤 닫힘·좌측 x=0·폭 ≤ 280, 쉴 때 outline 없음·Tab 2px 하나·누를 때 테두리 불변,
  모바일 아이콘 동작), `home-nav.spec.ts` 뷰포트 시험을 rail/drawer 기준으로 갱신.
- Map admin OpenAPI 변경 없음. 배포하지 않았다(부모 통합 회전).

## 2026-11-19 — T-READ-10 후속: 좁은 집계 표(alembic 455), T-101 재개

- 소유자 지시(2026-11-19): "전국 시도·전 종류 1,214 → 705 ms, 추가 개선", 목표 p50 < 300 ms. 같은 날 "사전집계도 허용" —
  **T-101 제외(2026-09-07)를 해제**했다. 제외 원문: "하지 않는다. 재개하려면 목표 SLO 정의와, exact-viewport(ADR-073
  accepted 계약) vs region-total 의미 택일이 선행한다 — 후자는 ADR 개정과 PinVi 소비자 계약 변경을 함께 부른다."
  이번 구현은 region-total이 아니라 exact-viewport를 그대로 지키므로 ADR-073·PinVi 계약을 건드리지 않는다.
- 후보 실측(n150 합성 42만 행, 반복을 교차해 잰 p50, 454 기준 약 700 ms):
  - 병렬 집계 — 공개 notice 감산 fragment(상관 subquery)가 scan을 parallel restricted로 묶는다. fragment는 notice가
    아닌 행에서 항상 참이라 notice 몫을 떼면 `Gather → Partial HashAggregate`가 된다. 단독으로 716 → 476 ms, point-only
    266 → 144 ms. 남은 비용은 route 5.8만 행의 `features` PK 조인과 넓은 route heap.
  - (b) 좁은 집계 표 + 병렬 — **채택.** 255 ms(아래).
  - single-pass(features 한 번 + geometry hash join) 611 ms, `parallel_*_cost` 조정·`max_parallel_workers_per_gather` 3 —
    이득 없음(기본값으로 병렬 계획이 나온다). work_mem — 묶음 20~3,500개라 HashAggregate가 기본 64 MB 안에 든다.
  - (a) 데이터 버전 캐시 — 버리지 않았지만 하지 않았다: 집계 결과는 `features`·subtype·`source_links`(provider 필터)·속성
    표·notice(시각) 모두에 달려 값싼 무효화 버전이 없고, harness가 재는 SQL을 줄이지 못한다. 좁은 표로 목표에 닿았다.
  - region rollup(지역별 사전 합계) — 좁은 표로 255 ms에 닿아 더 얹지 않았다(부분 포함 지역의 정확 계산·합계 drift 관리
    비용이 크다).
- 구현: `feature.feature_cluster_points`(Feature당 한 행: kind·category·지역 코드·coord·공개 3축 곱 `public`, route/area
  대표점·정확 범위, 범위 사각형 생성 컬럼) + AFTER ROW trigger 셋(`features` INSERT/관련 열 UPDATE/DELETE,
  route/area INSERT/`geom` UPDATE/DELETE). 각 trigger는 자기 몫 열만 upsert — core와 geometry를 두 transaction이 동시에
  바꿔도 둘 다 남는다. 집계는 (1) notice 아닌 point + bbox 안 route/area(병렬) (2) bbox를 가로지르는 route/area(실제
  geometry, MATERIALIZED) (3) notice(공개 view + fragment)로 묶어 (개수, 좌표 개수, 경도 합, 위도 합)을 합친다.
- 반영 시점: **동기식(지연 0)** — 쓰기 transaction 안에서 이미 맞는다. `tests/integration/test_cluster_points_sync.py`가
  좌표·지역 코드·분류·공개 3축·geometry 갱신/삭제/재삽입·Feature 삭제(cascade)마다 좁은 표 = migration backfill 식,
  집계 = 종전 SQL을 확인한다.
- 실측(n150 합성, 15회 교차 p50; 종전 → 454 → 455):

  | 질의 | 종전 | 454 | 455 |
  |---|---|---|---|
  | 전국 sido 전 kind | 1,297 ms | 711 ms | **255 ms** |
  | 전국 sido point-only | — | 254 ms | **107 ms** |
  | 수도권 시군구 전 kind / point-only | 146 / — ms | 128 / 92 ms | 66 / 37 ms |
  | 서울 읍면동 전 kind / point-only | 106 / — ms | 65 / 92 ms | 39 / 29 ms |

  전국 255 ms 중 약 140 ms는 합성 데이터의 bbox를 가로지르는 route 32개(2만 점짜리 포함)의 실제 교차 계산이다 — prod는
  전국 bbox를 가로지르는 route/area가 4개(2026-11-19 읽기 전용 조회)라 더 낮을 것으로 본다. 동등성: 개수 일치, 평균 좌표
  차 최대 2e-12도.
- 쓰기 영향(n150 합성, 같은 문장을 trigger 켜고/끄고, transaction rollback, 2회): 좌표를 바꾸는 50,000행 UPDATE 7.0~7.4 →
  10.2~10.9 s(+약 40%), 집계와 무관한 열만 바꾸는 50,000행 UPDATE 7.4~7.8 → 7.1~8.1 s(차이 없음 — trigger가 바로 돌아간다),
  INSERT 20,000행 2.2~2.6 → 2.7~2.9 s(+약 10~30%).
- HOT(T-READ-07): `features`에 열·색인을 더하지 않았다. 위 UPDATE 모두 trigger 유무와 관계없이 HOT 0(종전에도 0 —
  `updated_at` 색인). 큐레이션 해시: `features`·subtype 행이 바뀌지 않고 새 표는 어떤 `to_jsonb` 입력에도 없다.
- migration 455(합성 42만 행, tmpfs): 표·함수·trigger 수 ms, backfill 2.1 s, GiST 두 개 0.8 s, ANALYZE 0.4 s. 크기 92 MB
  (heap 58 MB). trigger 생성의 `SHARE ROW EXCLUSIVE`가 commit까지 세 표의 쓰기를 막는다 — prod(디스크)는 10~20 s로 본다.
  적재를 멈춘 뒤 배포한다.
- 적대 리뷰(1회): High 없음. Medium — 상태 전이(features → subtype → 새 표)와 geometry 갱신(subtype → 새 표)의 잠금 순서
  역전으로 deadlock 가능 → `features` trigger 이름을 `trg_features_zz_cluster_point`로 두어 subtype 동기화 뒤에 돌게
  고쳤다. notice·분류 필터·backfill 결합 시험 부족 → 보강. 남긴 Low: SERIALIZABLE 도메인 명령과 같은 Feature의 동시
  geometry 갱신이 새 표 행에서 40001을 낼 수 있다(재시도 대상), area 대표점은 쓰기 때 저장되므로 GEOS 판올림 뒤 새로 계산한
  값과 마지막 자리가 다를 수 있다(454의 route와 같다). TRUNCATE는 문장 trigger로, 복제 역할(`session_replication_role =
  replica`)은 trigger `ENABLE ALWAYS`로 덮었다(CI 통합 런에서 정리 도우미가 남긴 어긋남으로 드러났다). trigger 함수의 PUBLIC
  실행권은 걷었다(런타임 SECURITY DEFINER preflight). `ALTER TABLE … DISABLE TRIGGER`로 이름을 지목해 끄는 경로만 남는다.
- 배포하지 않았다(소유자 묶음 회전).

## 2026-11-19 — T-READ-09 100 km nearby: LATERAL을 page 뒤로, 거리순은 KNN

- 진단(prod `map-api` 컨테이너 안 읽기 전용 트랜잭션, `jit=off`, 몇 회만): "100km nearby"(서울시청, place, 51행) 5.4초 중
  **5.0초가 primary source LATERAL**이었다 — 반경 안 201,401행마다 `source_links→source_entities→provider_datasets→heads→
  records` 5단 join + 정렬을 돌고 나서 51행을 잘랐다. 반경 scan 자체는 0.27초.
- 고친 것(`feature_repo._nearby_sql`, 좌표·by-target 공용):
  1. primary source LATERAL은 `LIMIT`로 잘린 page 행에만 붙인다. provider 필터는 같은 선택 규칙의 상관 subquery(필터가
     있을 때만 돈다).
  2. 거리순 page는 GiST KNN이다. `distance_m`을 `<->`로 계산한다 — PostGIS 3.6의 `<->`(`geometry_distance_centroid`)는
     `ST_Distance`와 **같은 C 함수**(prosrc `ST_Distance`)라 값이 같다. KNN은 정렬 키가 하나일 때만 생기므로(PG18) 후보
     subquery를 `ORDER BY distance_m FETCH FIRST (:limit_plus_one) ROWS WITH TIES`로 자르고 바깥에서 `(distance_m,
     feature_id)`로 다시 정렬한다. WITH TIES가 n번째 거리와 같은 행을 모두 남겨 동률 tiebreak가 종전과 같다.
  3. 반경 술어는 `ST_DWithin` 대신 그것이 펼쳐지는 `&& ST_Expand` + `<-> <= 반경`으로 쓴다. 종전 계획은 `ST_DWithin`
     filter 뒤 20만 행을 27행으로 추정했다(펼친 술어는 50,814행 — 실측 201,401에 훨씬 가깝다). 추정이 틀리면 planner가
     KNN과 bitmap을 잘못 견준다. 두 술어가 갈리는 (행, 반경) 쌍은 prod 133만 쌍 중 0,
     통합 시험(경계 반경 포함)도 0.
  - 시행착오: 정렬 키 둘로는 KNN path가 안 생겼고, 후보에 상한이 없으면 바깥 LIMIT이 정렬 너머로 안 전해져 custom plan이
    전 행 bitmap+정렬(377 ms)을 골랐다(generic plan만 KNN 5 ms).
- prod 읽기 전용 EXPLAIN(t1118e, 다른 작업의 I/O가 겹친 창이라 종전 SQL은 기준선보다 느리게 나왔다): 새 SQL "100km nearby"
  p50 **4.5 ms**(종전 기준선 5,200 ms), 100 km 전 kind 4.2, event 57.7, provider 필터 168, 속성 필터 143, route 37.7,
  5 km 4.1(종전 1,107), 1 km 4.0(종전 189), 300 m 3.9(종전 16.6), 100 km 갱신순 3.8, **이름순 1,248**(종전 ≈ 9초 — 반경 안 전
  행 정렬이라 남는다). prepared statement 10회(custom→generic) 14~16 ms(왕복 포함).
- 동등성: `tests/integration/test_features_nearby_equivalence.py`(종전 SQL oracle, page walk 전체)와 prod 읽기 전용 대조
  6묶음 13 page가 전부 같았다. 회귀 가드: page 행 수 이하의 LATERAL loops, KNN 순서 scan 가능, `<->`=`ST_Distance` 함수
  동일성, 구조 unit 시험. harness `matched_rows`는 KNN 상한도 함께 뗀다.
- 운영 배포는 하지 않았다(소유자의 Map 회전에 싣는다). OpenAPI 변화 없음.

## 2026-11-19 — T-READ-10 저배율 집계 단축(alembic 454 + HashAggregate)

- 진단(운영 `map-api` 컨테이너 안, 읽기 전용 transaction·`jit=off`, `EXPLAIN (ANALYZE, BUFFERS)` 몇 번): 전국 sido 전 kind
  집계 1.6 s 중 geometry 후보 CTE 0.68 s — route geometry 5.8만 개(평균 118점, 표 232 MB)를 요청마다 풀어
  `ST_Intersects`·`ST_XMin`…·`ST_PointOnSurface`를 계산하고, 그 5.8만 행을 `pk_features`로 하나씩 조인(0.17 s)한다.
  point arm은 GiST 순서 heap 읽기 34만 행(0.4~0.7 s), 그 뒤 40만 행 **정렬**(GroupAggregate)이 0.1~0.2 s. 지역 코드는
  이미 `features`에 저장돼 있다 — "질의 때 지역 배정"은 원인이 아니었다.
- 수정: ① route geometry STORED 생성 컬럼 다섯(`marker_point`·`geom_xmin`…, 종전 요청 시 식과 같은 식). bbox 안에
  완전히 든 route는 geometry를 풀지 않고 `ST_Intersects`도 건너뛴다(포함 ⇒ 교차). area는 열을 달지 않았다
  (`to_jsonb(area_row)`가 큐레이션 입력 해시에 통째 들어가 해시가 바뀐다, 422행이라 요청 때 계산해도 작다).
  ② 집계 문장 동안만 `enable_sort = off`(`set_config(..., true)` 후 직전 값 복원) — HashAggregate.
- 기각한 것(같은 n150 합성 DB, 반복 교차 p50): `features (feature_id) INCLUDE (kind, category, 코드 셋, coord)` 덮개 색인
  — 조인이 index-only가 되지만 이득 1~6%(911 → 903 ms)라 색인 하나(약 45 MB·쓰기 증폭)를 더할 값이 없다. 시도 키 덮개
  색인 — planner가 고르지 않았다. 한 번에 훑는(single-pass LEFT JOIN) 변형 — 더 느렸다(1.6 s). 지역 묶음 `COLLATE "C"`
  — 정렬은 빨라지지만 HashAggregate보다 작다. 사전 집계·rollup 표 — T-101(2026-09-07 소유자 제외).
- 실측(n150, 합성 42만 행 = place 35만·route 5.77만(평균 129점)·area 422·event 1.5천, tmpfs PG18, 반복 10회 교차, p50):
  전국 sido 전 kind **1,214 → 705 ms**(−42%), 같은 bbox point-only 397 → 250 ms(−37%), 수도권 시군구 전 kind
  145 → 124 ms·point-only 100 → 85 ms, 서울 읍면동 전 kind 90 → 64 ms·point-only 119 → 91 ms. 처음 목표
  "전 kind < 300 ms"는 닿지 않는다(point-only 기준선부터 365 ms) — acceptance 목표를 800 ms/300 ms로 적었다.
- 동등성: `tests/integration/test_cluster_rollup_equivalence.py`가 종전 SQL 사본과 3단위 × bbox 3 × kind 필터 4를 비교한다
  (변에 닿는 route·1e-7도 넘는 route·MBR만 겹치는 route·bbox를 가로지르는 route·구멍 난 area·비공개·코드 없음 포함, geom
  UPDATE 뒤 한 번 더, 요청 경로 함수도). 개수는 정확히 같고 평균 좌표는 1e-9도 안(계획이 바뀌면 float 합 순서만 다르다).
  bench DB에서도 시도·시군구·읍면동 개수 일치, 좌표 차 1e-12도 안팎.
- 다시 쓰기 비용: 합성 route 5.77만 행·153 MB에서 `ALTER TABLE … ADD COLUMN … STORED` 5.1 s(tmpfs, 같은 표 `VACUUM FULL`
  4.7 s). prod에서 다섯 식만 계산하는 읽기 전용 dry run(운영 `map-api` 컨테이너, 병렬 3)이 7.6 s였다(단일 프로세스면
  약 22 s, NULL 결과 0) — 다시 쓰기·색인 재구축을 더해 prod는 30~60 s `ACCESS EXCLUSIVE`로 본다. 그 동안 route/area를 읽는
  요청이 기다린다.
  migration은 `lock_timeout` 5 s·`statement_timeout` 300 s, route 적재가 돌면 실패하고 다시 돌리면 된다. `features`(42만 행)는
  건드리지 않는다(backfill 없음 — 생성 컬럼이 다시 쓰기 중에 채워진다).
- 배포하지 않았다(소유자의 묶음 회전). 운영 반영 뒤 harness로 acceptance를 닫는다.

## 2026-11-19 — T-READ-01 읽기 기준선(조용한 창·적재 중)과 판정

- 소유자 승인(2026-11-19 KST 아침, 예정 창 대신 지금)으로 운영 `map-api` 컨테이너 안에서 harness
  (`--skip-seed --iterations 30`, `jit=off`·`statement_timeout` 30 s·읽기 전용)와 probe(`--iterations 30`)를 돌렸다.
  generation **t1118e**(Map `8e90e56e`). 보고서 [`reports/2026-11-19-read-baseline.md`](reports/2026-11-19-read-baseline.md),
  원자료 `reports/2026-11-19-read-baseline/{quiet,loaded}/`.
  - 적재 중 run(22:37~22:45Z): harness 도중 공용 Dagster run 4개(PinVi telegram planner, transport highway incidents,
    weather current, weather daily summaries)가 시작돼 probe-2와 겹쳤다. PSI io avg60 최대 1.70.
  - 조용한 창 run(22:47~22:54Z): 공용 Dagster schedule·sensor 69개 정지, active run 0, PSI 0.00~0.17. 계획 §8.1의
    30분 사전 관측은 하지 않았다(두 run 내내 PSI < 5%).
- 판정(두 창 같음): `T-READ-05` **채택 안 함**(부산 맛집 전처리 9.53/382.54 ms = 2.5%. 서울 맛집 23.78/143.94 = 16.5%는
  절대 24 ms라 기록만), `T-READ-06` **채택**(이름 정규화 비중 부산 37%·서울 56%, 상수화 변형 matched 1~5행 차이라
  근사값). `T-READ-07`은 14일 간격 스냅샷이 필요하고 첫 스냅샷을 아직 찍지 않았다.
- 새 발견: "100km nearby" 조용 p50 5,200 ms·p95 5,369 ms — 공개 `/v1/features/nearby`(반경 ≤ 100 km)는 `T-READ-03`
  마감 4.5초에 걸려 503이 된다 → `T-READ-09`. "전국 low-zoom cluster(sido, 전 kind)" p50 1,231 ms·p95 1,311 ms →
  `T-READ-10`. 소유자가 `T-READ-06`·`09`·`10` 구현을 승인했고 다른 에이전트가 병렬로 진행 중이다.
- `T-READ-02` 마지막 항목: 2026-11-18 운영 `map-api` 로그(T-READ-02가 실린 t1118a 이후, 지금 t1118e)에
  `slow_request route=/v1/features/in-bounds … duration_ms=6996` 줄들이 있었다 — 닫는다.
- 이관: `T-READ-01`·`02`·`05` → `tasks-done.md`.

## 2026-11-18 — 운영 회전 t1118a·t1118e(T-READ-02·03·04·08 운영 반영)

- **t1118a**(n150 prod, green): Map `7dc2af78` + PinVi `c21d9c5e`. Map 쪽에 `T-READ-08`(alembic 453, `feature.features`
  표 단위 autovacuum)·`T-READ-02`(느린 요청 로그·pool 지표)·frontend Node 26.13.1(#1511, guard ref `0dec954`)이 실렸다.
  D1 40/40, D2 11/11, rankprobe hit@1 35/44·hit@8 41/44.
- **t1118d**(실패, 운영 불변): 후보 빌드에서 pinvi-web BuildKit이 `frontend grpc server closed unexpectedly`로 죽었다.
  활성화 전 단계라 런타임은 t1118a 그대로였다.
- **t1118e**(n150 prod, green): Map `8e90e56e` + PinVi `0a1d90c7`. `T-READ-03` 공개 읽기 요청 마감 4.5초(#1515)와
  `T-READ-04` 교통 `near-batch`(Map #1516 / PinVi #784 재vendor + client)를 한 pair 회전으로 냈고, PinVi #785도 함께
  실렸다. D1 40/40, D2 11/11, rankprobe는 t1118a와 같다(hit@1 35/44·hit@8 41/44).
  배포 뒤 live e2e — desktop 298/299(SRCH-043 flaky, 재실행 2/2 통과), mobile 164/167(CORE-014·015·016이
  `ERR_NAME_NOT_RESOLVED` DNS 순간 장애로 실패, 재실행 통과), firefox core green.
- acceptance: `T-READ-03` 마지막 항목(운영 PinVi가 `T-READ-PIN-04` 머지 commit `c0090296`을 포함 — t1118a의
  `c21d9c5e`, 그 뒤 t1118e로 Map 반영; 두 generation을 여기 적음)과 `T-READ-04` 마지막 항목(PinVi #784 머지 뒤 한 pair
  회전 t1118e)을 닫았다. `T-READ-02`의 "운영 로그에서 1초 넘는 요청 줄 확인"은 아직 적지 않았다(다음 확인 때).
  `T-READ-05`·`06`·`07`은 그대로 조용한 창의 기준선(`T-READ-01`)을 기다린다. `T-READ-08` ③(적재 24시간 뒤 all-visible)도
  측정 창 몫이다.
- 알려진 문제(Map 원인 아님): 2026-11-17부터 `weather_state_forecast_short`가 3시간마다 실패한다. kor-travel-weather
  `/v1/service/exports/forecasts`가 503 `EXPORT_TEMPORARILY_UNAVAILABLE`를 돌려준다. weather 쪽(Codex 담당) 문제이고,
  Map은 실패 시 아무것도 쓰지 않는다(직전 상태 유지).

## 2026-11-18 — T-READ-04: 교통 묶음 근처 조회(`near-batch`) — PinVi 재vendor와 함께 머지

- `POST /v1/service/transport/{fuel-stations,highway-incidents}/near-batch`(service 표면, 같은
  `require_service_token`). 본문 `points[]`(1~60)·`radius_m`(≤ 50 km)·`limit`(≤ 500, 기본 100), 넘으면 422.
  `ValkeyStateStore.nearby_many`가 포인터 `GET` → meta `HGETALL`+점마다 `GEOSEARCH … WITHDIST COUNT limit+1`
  pipeline 하나 → 라우터의 `HMGET` 한 번. 점 수와 무관하게 왕복 셋, 한 세대. id마다 가장 가까운 거리만 남겨
  (거리, id)순으로 자르고 `truncated`는 기존 근처 조회와 같은 뜻이다. Valkey 장애·적재 전은 기존 route와 같은 503.
- **spec이 바뀐다** — service·full OpenAPI(admin `openapi.json`·`openapi.service.json`)에 route 둘과
  `NearBatchRequest`·`NearBatchPoint`가 더해진다(user 불변). 그래서 **머지하지 않았다**: 머지하면 다음 Map 회전부터
  PinVi 재vendor가 먼저 있어야 해서 `T-READ-02`·`08`의 Map 단독 회전이 막힌다. 순서는 계획 §8.1 그대로 — 이 PR 머지
  → PinVi `T-READ-PIN-01` ③(재vendor + `near-batch` client + 405 fallback) 머지 → Map+PinVi 한 pair 회전.
- 머지 준비(같은 날): main(#1509~#1515)을 합쳤다. 빨갛던 `test_consumer_rollout_shape`는 T-VN-41 pending
  receipt의 `map_service_openapi_sha256`이 현재 `openapi.service.json` sha와 같아야 한다는 단언이었다 —
  첫 판은 T-VN-40만 재핀하고 41(service 전용 receipt)을 빠뜨렸다. 41의 Map service 지문을 새 spec으로 옮기고
  blocking_reason에 한 문장을 더했다. PinVi vendor 지문과 pending 상태는 그대로다(격리 paired 검증 전 승격 없음).
  PinVi `T-READ-PIN-01` ③ PR과 둘 다 CI green일 때 Map → PinVi 순으로 머지하고, 배포는 한 pair 회전이다.
  이 회전에는 main에 먼저 머지된 `T-READ-02`·`03`·`08`(alembic 453)도 함께 실린다.

## 2026-11-18 — T-READ-03: 공개 읽기 요청 마감(머지, 다음 Map 회전에 실린다)

- `perf/t-read-03-public-read-deadline`(T-READ-02 위). PinVi `T-READ-PIN-04`(Map의 503 `READ_TIMEOUT`·`POOL_BUSY`를
  다시 보내지 않음, PinVi #777, 머지 commit `c0090296`)가 운영에 반영된 것을 확인하고 머지했다 — 운영 회전 `t1118a`
  (Map `7dc2af78` + PinVi `c21d9c5e`, green). PinVi `c21d9c5e`는 `c0090296`을 포함한다(GitHub compare: ahead 4, behind 0).
  T-READ-03 자체의 운영 반영 generation은 그 Map 회전 때 여기에 덧붙인다(acceptance 마지막 항목).
- 새 의존성 셋(`api/db.py`)이 옛 의존성을 **감싼다** — `get_public_read_session`(← `get_session`),
  `get_public_read_snapshot_session`·`get_public_read_slow_snapshot_session`(← `get_read_snapshot_session`). 격리 수준·세션
  수명은 옛 의존성이 그대로 정한다. 감싸는 쪽은 **DB에 닿지 않는다**(422로 끝나는 요청은 연결을 꺼내지 않는다) — 마감을
  `session.info`에 싣고, 그 요청의 pool 체크아웃 상한(min(pool 대기 2초, 남은 예산))을 ContextVar로 걸고, 세션
  `after_begin`에서 남은 시간 − 0.3초(바닥 250 ms)를 그 transaction의 `statement_timeout`으로 건다. 체크아웃 상한은
  `TimedAsyncQueuePool`이 읽어 짧게 기다리고 넘으면 503 `POOL_BUSY`(예산이 먼저면 `READ_TIMEOUT`) — 요청을 취소하지
  않으므로 연결이 새지 않는다(첫 판의 `asyncio.timeout` 방식은 의존성에서 연결을 미리 꺼내 422 시험 7건을 깼다). 시계는
  T-READ-02의 `request.state.started_monotonic`. 옛 의존성·엔진 `pool_timeout`·ADR-112 `transaction_limits`는 그대로.
- `infra/public_read_budget.py`: 마감이 없는 세션(Dagster·CLI·admin)에는 아무것도 보내지 않는다. `search_features`는
  마감이 있으면 `SET LOCAL` 둘을 `set_config` 한 문장(+ `statement_timeout`)으로 보내고 본 질의·개수 질의 앞에서 다시
  건다. 마감이 없으면 종전 그대로(문장 수 불변).
- 오류: 공개 예산 표시가 있는 요청의 57014 → 503 `READ_TIMEOUT`(표시 없는 57014는 종전처럼 500). batch route의
  `except SQLAlchemyError`는 표시가 있는 57014를 다시 던진다. 새 응답 선언·schema·enum 없음 — OpenAPI 불변.
- 적용 route(옛 → 새): bbox·in-bounds·nearby·categories·providers 둘·beaches 목록·beach markers·festival markers·
  curations collections·place-attributes는 `get_session` → `get_public_read_session`. search·nearby/by-target·상세·
  contained-features·price·price/snapshot·batch·beach 상세·festival 상세·curations(목록·collection 상세·feature)는
  `get_read_snapshot_session` → `get_public_read_snapshot_session`. festivals/monthly는 → `…_slow_…`. 배선은 단위 시험이
  표로 고정한다(범위 밖 route가 새 의존성을 쓰면 빨강).
- 관리 화면: `/v1/admin/features/in-bounds`(범위 밖)를 쓰고, 공개 route 중 price·contained-features는 client timeout
  없이 부른다 — 그 둘도 4.5초에서 끊긴다(위험 ③).
- 시험: 단위(배선 표·예산 계산), 통합(PostGIS — 문장 둘 요청 마감, pool 고갈 `POOL_BUSY`·누수 없음·`get_session` route는
  종전처럼 대기, 긴 예산, 예산 0, batch 57014, 마감 없는 `search_features`의 `statement_timeout` 불변, 실제 검색 route).

## 2026-11-18 — 공통 guard 호출을 T-029 커밋으로(Common T-417)

- `.github/workflows/common-frontend-policy.yml`의 호출 SHA와 `common-ref`를 `55a921b` → `0dec9543c8c8730ce7b05837f2fbe6c31d4ede65`(Common T-029 병합, 공통 Node 축 26.13.1)로 같이 올렸다. 새 guard는 정책 세 파일과 Node/npm 축을 이 ref에서 읽고, 도구 규칙(`check_node_toolchain`)을 더 돌린다.
- 도구 규칙 입력을 채웠다: `toolchain-manifests`(루트·`map-marker-react`·`kor-travel-map-user-client`), `node-dockerfiles`(`docker/frontend.Dockerfile`). C7 live e2e 이미지는 생산 이미지가 아니라 넣지 않았다.
- 새 검사기가 frontend 이미지에서 걸어 고친 것: `apt-get`(ca-certificates·git) RUN 삭제 — lock에 git 의존성이 없고 Node가 CA를 내장한다; `npm ci --workspaces --include=optional` → `--engine-strict`(optional은 기본 포함이라 설치 트리는 같다); runner의 `groupadd`/`useradd`(`nextjs`) 대신 이미지 내장 비root `node` 사용자(uid 1000). compose에 frontend 볼륨·`user:` 지정이 없어 영향 없음.
- `.nvmrc`·`engines`는 ADR-124(#1507)로 이미 26.13.1이라 이번 축에서 그대로 통과한다(T-024 읽기 전용 실행의 FAIL 두 줄 해소). 의존성·산출물 대조도 같은 ref로 통과(로컬 재현, Node 26.13.1).
- 기존 검증 스크립트와의 겹침: `verify-npm-tree.mjs`(설치 트리 `npm ls` problems 0)·`verify-next-sharp.mjs`(Sharp ABI 실변환)는 설치 결과를 보고, 공통 도구 규칙은 선언·이미지·npm 명령 형식만 정적으로 본다. 겹치지 않으므로 둘 다 남긴다.
- 검증: 공통 검사기 로컬 PASS, 관련 단위 테스트 5개 파일(실패 13건은 node_modules 없는 체크아웃의 dotenv validator 등 환경 — main 기준선과 같은 13건). frontend·docker-images·공통 정책은 PR CI. n150 게이트 `NOT_RUN`(CI 우선).

## 2026-11-18 — dev 포함 npm audit 게이트 한시 완화(GHSA-fc5q-39xc-vjpf)

- 2026-11-17T15:56Z picomatch ReDoS advisory 범위가 `<= 4.0.7`(최신)로 넓어져 frontend 워크플로의
  `npm high 취약점 gate (dev 포함)`이 main과 모든 PR에서 빨갰다. 패치가 없고 picomatch는 dev 도구
  (vite·vitest·tinyglobby·fast-glob/micromatch·@typescript-eslint)로만 들어온다. `audit:high`(`--omit=dev`)는 0건.
- §10.6 2번 절차대로 dev 단계만 완화했다. `audit:*` 스크립트는 그대로 두고, CI 스텝과
  `verify-all-gates.sh`가 새 `audit:dev:known`(`scripts/audit-dev-known-advisories.mjs`)을 돈다 — high 이상 근원
  advisory가 이 하나뿐일 때만 통과, 다른 advisory는 계속 막는다. 테스트가 목록을 이 하나로 고정하고
  목록 밖 high·critical·읽기 실패를 빨갛게 확인한다. `|| true` 거부 단언은 유지.
- 다시 조일 조건(패치된 picomatch를 lockfile·`overrides`로 소비)은 [§10.6](dev-environment.md)에 적었다.

## 2026-11-18 — 읽기 성능 Map 작업: 소유자 결정 적용 결과(문서 전용)

- 머지: `T-READ-08` autovacuum 문턱(alembic 453, #1509), `T-READ-02` 느린 요청 로그·pool 지표(#1510), `T-READ-01` 기준선
  도구(#1512, 실행은 측정 창). 셋 다 Map 회전(spec 불변)으로 나간다 — 배포는 하지 않았다.
- 브랜치만(머지 안 함):
  - `perf/t-read-03-public-read-deadline` — 공개 읽기 요청 마감. PinVi `T-READ-PIN-04`가 머지·**운영 반영**된 것을 확인한
    뒤 머지·배포한다(그 전에는 PinVi가 503 `READ_TIMEOUT`을 세 번 다시 보낸다). 독립 적대 리뷰 1회 반영.
  - `perf/t-read-04-transport-near-batch` — `POST /v1/service/transport/{dataset}/near-batch`. 덧붙이기만 하는 route라 기존
    소비자와 호환되지만 **service·full OpenAPI가 바뀐다**. 머지하면 그 뒤 Map 회전은 PinVi 재vendor 없이 pair gate를 통과하지
    못한다 — 위 둘(08·02)을 Map 단독 회전으로 낼 수 있게 PinVi `T-READ-PIN-01` ③(재vendor + near-batch client + 405 fallback)이
    준비될 때 머지하고 한 pair 회전으로 낸다.
- 대기(측정 뒤, 결정 1):
  - `T-READ-05` — 채택 판정이 측정(전처리 두 질의가 검색 시간의 5% 이상)이다. 코드로 보이는 이득은 따뜻할 때 수 ms로
    추정되고(F-07), 바꾸면 지역 이름 선택(표본 → 최빈값)과 문턱 3만 근처의 좁음/넓음 판정이 달라질 수 있으며 새 refresh에
    기댄다. 측정 없이 이득이 분명하지 않다.
  - `T-READ-06` — 묵은 키 허용은 정해졌지만(결정 3) 채택 판정(이름 정규화 비중 30%)과 되돌림 기준(p50 40%)이 측정이다.
    40만 행 표·refresh·평가 묶음까지 큰 변경이라 측정 전에 하지 않는다.
  - `T-READ-07` — 지울 색인은 14일 간격 두 스냅샷과 읽는 경로로 정한다. 3.6일 창의 "탐색 0"은 근거가 약하고(§4.1) 지운
    색인은 되살리는 비용이 크다. fillfactor 90도 적재 전후 측정으로 정한다.
- 운영 쪽 관측의 남은 몫(Map 코드 밖): 지표 켜기·token(Manager `T-READ-MGR-03`), scrape(`T-READ-MGR-02`), PG
  `pg_stat_statements`·느린 질의 로그(`T-READ-MGR-01` — **공용 PG 재생성 창** 필요).

## 2026-11-18 — T-READ-01: 읽기 기준선 도구(실행은 측정 창에서)

- 소유자 결정(2026-11-18)에 따라 **도구만** 넣었다. 운영 DB·운영 API에서 돌리지 않았다 — 조용한 측정 창은 소유자가
  따로 잡는다.
- `scripts/perf_tier2_release_harness.py`: 연결을 운영 API처럼 `jit=off` + `statement_timeout` 30초로
  (`HARNESS_SERVER_SETTINGS`), `--output <파일>`(`.safe.json`, DSN 없음, 사용한 연결 설정을 함께 적는다), viewport
  6 → 13개(지역 검색 "부산 맛집"·"서울 맛집", 수도권 시군구 집계 zoom 10, 서울시청 읍면동 집계 zoom 12·13 — PinVi 기본
  kind·500건, 서울 개별 행 500건 zoom 14, 상세 1건). 지역 검색은 운영과 같은 `_resolve_search_region` →
  `_search_region_arms` → `_search_region_params` → `_search_score_sql`로 SQL과 인자를 만들고, 전처리 셋(별칭·지역
  표본·지역 행 수)을 따로 잰다. 이름 정규화 비중은 **빼고 잰다** — `compacted`·`hits`의 식을 원래 열·상수로 바꾼
  harness 전용 변형의 p50으로 (i − ii) / i(`region_search[].name_normalization.share`). 비교 키를 모두 같은 상수로
  두면 뒤의 접기(`ST_ClusterDBSCAN` partition)가 후보 전부를 한 무리로 묶어 비용이 달라지므로 비교 키는 정규화하지
  않은 원래 열로 뒀다. 운영 SQL 모양이 바뀌면 변형 생성이 추측하지 않고 실패한다.
- 지역 검색 viewport의 최소 반환 행은 0이다(fixture가 그 지역을 모르면 빈 결과다 — 보고서의 `returned_rows`와
  `region_resolved`가 보여 준다). 다른 새 viewport는 1행 이상이어야 성공 보고서를 낸다(종전 fail-closed 그대로).
- 새 `scripts/read_path_probe.py`: HTTP만(표준 `urllib`, DB·`kortravelmap` import 없음 — 시험). PinVi 모양 요청
  9종(in-bounds zoom 7·10·12·13·14, 검색 셋, 상세 1건)을 30회씩 보내 `meta.duration_ms`와 왕복 시간 p50·p95, status,
  묶음 전후 PSI io `some avg60`을 적는다. service token은 `--token-file` 또는 `KOR_TRAVEL_MAP_PROBE_SERVICE_TOKEN`에서
  읽어 헤더로만 보내고 출력·파일에 쓰지 않는다(시험). loopback이 아닌 대상은 보고서에 `<non-loopback>`으로만 적는다.
- 남은 해제 조건(acceptance `T-READ-01` 둘째~여섯째)은 측정 창의 실행과 보고서다.

## 2026-11-18 — T-READ-02: 요청 도착 시각·느린 요청 로그·pool 대기 지표

- 소유자 결정(2026-11-18)에 따라 측정 없이 가치가 분명한 관측 코드로 진행했다(계획 F-03 — 운영 Map에는 읽기 지연을 볼
  수단이 없다).
- 미들웨어(http 미들웨어 중 가장 바깥)가 `request.state.started_monotonic`을 적고(`T-READ-03`의 요청 마감 기준),
  요청별 DB 누산기(`api/request_timing.py`)를 ContextVar로 건다. cursor 이벤트는 이제 **지표 flag와 무관하게** engine에
  걸려 문장 수·DB 시간을 그 누산기에 더한다. 추가 DB 왕복은 없다(통합 시험 — handler가 보낸 2문장이 그대로 2).
- 느린 요청 로그: `KOR_TRAVEL_MAP_API_SLOW_REQUEST_LOG_MS`(기본 1000, 0이면 끔) 이상이면 WARNING 한 줄 —
  route template·status·`duration_ms`·`db_statements`·`db_ms`·`pool_waits`·`pool_wait_ms`·request id. query string·
  header·좌표는 쓰지 않고, client가 보낸 request id는 `[A-Za-z0-9._:-]{1,64}`가 아니면 `-`로 쓴다.
- pool: `make_async_engine`에 `poolclass` 인자(기본 None = 종전). API engine은 `TimedAsyncQueuePool`(`_do_get`만 감싸
  시간을 잰다 — 크기·overflow·timeout 판정은 부모 그대로). `/metrics`에 `kor_travel_map_db_pool_wait_seconds`
  histogram과 `kor_travel_map_db_pool_checked_out`·`_overflow` gauge(scrape 때 `pool.checkedout()`·`overflow()`).
  세션 의존성은 바꾸지 않았다 — pool 크기 1에서 공개 key 인증 세션 → 읽기 snapshot 세션이 차례로 동작한다(통합 시험).
- OpenAPI 불변(미들웨어·`include_in_schema=False`). Map 회전(spec 불변)으로 나간다. 운영에서 지표를 켜는 것은 Manager
  `T-READ-MGR-03`, 긁는 것은 `T-READ-MGR-02`, PG 쪽 관측(`pg_stat_statements`·느린 질의 로그)은 공용 PG 재생성 창이
  필요한 `T-READ-MGR-01`이다 — Map 코드로 할 수 있는 몫은 이 PR이 전부다.
- 배포는 이 PR에서 하지 않았다. acceptance 마지막 항목(운영 로그의 1초 넘는 요청 줄)은 배포 뒤다.

## 2026-11-18 — T-READ-08: `feature.features` autovacuum 문턱(alembic 453)

- 소유자 결정(2026-11-18, 계획 "소유자 결정" 절)에 따라 측정 없이 개선이 분명한 작업으로 진행했다. 근거는 이미 실측이다
  (2026-11-17 §4.1·F-14 — 통계 창 동안 autovacuum 0회, dead 약 6.3만, all-visible 58%, reloptions 없음).
  acceptance ①의 "설정 전" 수치는 그 실측으로 대신하고, ③(적재 24시간 뒤 all-visible 0.95·`Heap Fetches` 1% 미만)은
  소유자가 잡을 측정 창에서 잰다 — 그때까지 이 작업은 열린 채다.
- alembic `453_features_autovacuum`: `ALTER TABLE feature.features SET (autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_insert_scale_factor = 0.05, autovacuum_analyze_scale_factor = 0.02)`(계획 제안값) + receipt head CHECK.
  forward-only, 마지막 문장 `SET ROLE ktm_feature_schema_owner`.
- 배포 영향: catalog만 바꾼다(표 재작성 없음 — autovacuum storage parameter는 PostgreSQL이 다시 쓰지 않는다). 잠금은 `SHARE UPDATE EXCLUSIVE`라 읽기·적재
  쓰기를 막지 않는다. 그 표에 autovacuum이 돌고 있으면 PG가 `deadlock_timeout` 뒤 취소하므로 그 ALTER만 `lock_timeout`
  5초다(수동 VACUUM·ANALYZE 중이면 5초 뒤 실패 — 재시도). 배포 직후 새 문턱(dead 약 8.9천)을 넘어 있으므로 그 표의
  autovacuum이 한 번 돈다 — heap 약 379 MB·색인 약 720 MB를 비용 상한으로 천천히 훑는다. 그 동안 n150 디스크 I/O가 는다.
- 배포는 이 PR에서 하지 않았다(Map 회전, spec 불변).

## 2026-11-18 — 읽기 성능 계획: 소유자 결정 기록(문서 전용)

- 소유자 결정 셋을 [계획](reports/2026-11-17-read-performance-plan.md) "소유자 결정 (2026-11-18)" 절에 적었다 — ① 코드만 보고도
  개선이 분명한 작업만 지금 하고, 가치가 새 측정에 달린 작업은 소유자가 따로 잡을 조용한 창까지 기다린다(그때까지 운영에서
  측정 job 금지). ② Map과 PinVi는 병렬(PinVi는 다른 에이전트). ③ `T-READ-06`은 refresh 전까지 옛 사전 계산 키로 순위를
  매기는 것을 허용한다 — acceptance `T-READ-06` 셋째 항목을 닫았다.
- 코드·운영 변경 없음.

## 2026-11-17 — 정확 Node 26.13.1 핀(ADR-124, Common T-416 채택)

- 소유자 결정(2026-11-17): Common T-416 "추천안 대로 node는 최신버전으로". 질의 당시 값 22.23.1 대신 nodejs.org 색인의 최신 LTS 줄(26 Lithium) 최신 patch **26.13.1**로 고정했다. 가장 새 항목 `v27.0.0-alpha`는 alpha라 제외. npm은 공통 축 12.0.1 유지(26.13.1 동봉 npm은 11.20.0).
- 루트 `.nvmrc` 신설, 루트·관리자 frontend `engines.node` 정확 `26.13.1`(lock의 두 항목 포함), CI `node-version`, `docker/frontend.Dockerfile`의 `node:26.13.1-bookworm-slim` digest.
- live e2e 실행 이미지(`docker/c7-playwright.Dockerfile`): Playwright base의 Node는 apt major 판이라 정확 `engines` + `engine-strict`에서 `npm ci`가 거절된다. 같은 digest의 공식 이미지에서 `node`만 `/usr/local/bin`으로 복사했다.
- guard 호출(`55a921b`)은 그대로다. 그 판은 `engines`를 읽지 않는다. 공통 축이 26.13.1이 되는 Common T-029 뒤에 T-417로 옮긴다.
- 검증: 관련 단위 테스트 6개 파일 96건 로컬 통과(`test_frontend_dependency_security`·`test_ci_workflows`·`test_c7_prod_live_runner_contract`·`test_dockerfile_workspace_manifest_coverage`·`test_ci_builds_production_dockerfiles`·`test_tvn34c_n150_fresh_live_runner`). frontend build·docker-images는 PR CI. n150 게이트·live e2e는 `NOT_RUN`(prod 배포·e2e 진행 중이라 n150 변경 금지).

## 2026-11-17 — Common 공통화 재조사 계획의 Map 포인터(문서 전용)

- 소유자 요청으로 kor-travel-common이 다섯 저장소를 다시 조사해 계획을 냈다(Common `docs/plan/commonization-plan-2026-11-17.md`, 적대 리뷰 2회 반영). Map 조사 기준은 `f1788da9`.
- Map 몫은 여섯이다: Common `T-480b`(API compose healthcheck를 `kortravelcommon.http_health` exec 형식으로, 선행 없음),
  `T-418`(`components/ui/*` 순수 재수출 shim 제거, 선행 없음), `T-416`(정확 Node/npm 핀 채택 여부 결정 — 소유자에게 질의됐고 답 대기),
  `T-417`(guard 호출 SHA·도구 규칙 이관, `T-416`이 채택일 때), `T-419`(Common `T-025`의 ui·tokens patch 릴리스 당일 재vendor — 그날 옛 guard에 남아 있을 때만),
  `T-415`(선택형 패키지 `@kor-travel/admin-kit` 채택, Common `T-221` 뒤. `T-416` 결정을 기다리지 않는다. 옛 guard면 `T-419` 뒤).
- `docs/tasks.md`에 `T-COMMON-PLAN-20261117` 한 줄, `docs/tasks-acceptance.md`에 같은 이름의 절을 뒀다. 수용 기준 본문은 Common이 소유한다.
- 코드 변경 없음. 진행 중인 작업과 다음 한 작업은 바뀌지 않는다.

## 2026-11-17 — 읽기 성능 계획(Map·weather·transport)

- 소유자 요청으로 세 서비스의 읽기 경로를 코드와 운영 관측으로 검토해 [계획](reports/2026-11-17-read-performance-plan.md)을 썼다. 코드·설정·운영 변경
  없음. 기준 commit은 Map `f1788da9`·weather `e68f16a7`·transport `60095379`·PinVi `b1605949`·Manager `31d56e4e`.
- 측정 창(03:31~05:14Z, 배포·e2e 중, 읽기 전용): n150 PSI io `full` avg10 63%, Map API 프로세스 VmSwap 154 MB(RSS
  14 MB), 운영 Map 지표 꺼짐·PG 느린 질의 로그와 `pg_stat_statements` 없음. PinVi `/metrics`로 `/features/in-bounds`
  38건 중 503이 15건, 상류를 부르지 않는 PinVi route 둘이 평균 1.63초·6.53초. bbox 색인 탐색당 평균 11.7만 색인 행.
  checkpointer write 시간이 버퍼당 약 48 ms. e2e가 끝나지 않아 조용한 호스트의 기준선과 PinVi `app.api_call_log`
  전수 집계는 하지 않았다 — `T-READ-01`·`T-READ-PIN-06`의 일이다.
- odroid(읽기 전용): CPU idle 0%(Dagster run 작업), PG 데이터가 있는 NVMe 남은 공간 1.9 GB — 소유자에게 전달됐다.
- 적대 리뷰 2회 반영. 1회차: `T-READ-03`을 요청 마감 예산·공개 전용 의존성으로 다시 쓰고 PinVi의 재시도 금지
  (`T-READ-PIN-04`)를 선행으로 뒀다. 2회차: Map과 PinVi는 OpenAPI hash가 같아야 회전하므로 spec을 바꾸는
  `T-READ-04`를 "Map 머지 → PinVi 재vendor 머지 → 한 pair 회전"으로 고쳤고 `T-READ-03`은 spec 불변을 요구 사항으로
  했다. PinVi의 요청당 비용·동시 호출 상한(교통·날씨)을 0단계로 올렸고, autovacuum(`T-READ-08`)과 디스크 쓰기 주체
  (`T-READ-MGR-06`)를 더했다. 작업은 30개(Map 8·PinVi 7·Manager 7·weather 4·transport 4)이고 계획 §8이 단계 순이다.
- 원장: `T-READ-01`~`08`. **해제 조건은 acceptance의 같은 ID 절이 소유한다.** 자리를 내려고 닫힌 절 둘
  (`T-VN-M02-TRUNCATE-FENCE`·`T-VN-M05-VERIFY-RECEIPT`, 둘 다 tasks-done에 완료 기록)을
  `scripts/archive_task_ledger_section.py --apply`로 `docs/archive/`에 옮겼다. 도구 검산 통과 — 체크박스 176건·175건이
  두 파일에 그대로, 원장 223,003 → 211,173 bytes. 본문은 도구가 옮긴 그대로다.
- weather·transport·PinVi·Manager `docs/tasks.md`에는 이 계획을 가리키는 한 줄을 둔다(각 저장소 브랜치
  `docs/read-performance-plan-20261117`).

## 2026-11-17 — 관리자 프런트 공통 후보12 채택(ui 0.2.1·tokens 0.1.2·vworld-map-web 1.0.4)

- kor-travel-common #57·#58(동결 `97f8ed98`)이 정책 정본을 올렸다. 공통 guard는 고정 ref와 무관하게 common **main**의 정책·정본을 읽으므로, 옛 산출물로는 guard가 실패한다.
- `packages/kor-travel-map-admin/frontend/vendor`의 ui 0.2.0→0.2.1·tokens 0.1.1→0.1.2·vworld-map-web 1.0.3→1.0.4(Firefox·Safari 바탕지도 누락 수정, maplibre-vworld-react #33)·vworld-map-rn 1.0.1→1.0.2(사용하지 않는 원장 항목, 정본과 맞춤)를 바꿨다. `common-artifacts.json`은 중앙 원장 값으로 맞췄고, lock은 npm 12.0.1 lock-only로 해당 3항목만 갱신했다.
- guard·common-ref는 `55a921b` 그대로 둔다. `97f8ed98`의 guard는 정확 Node/npm 도구 규칙(root `.nvmrc`=22.23.1, `engines.node` 정확값, common ADR-018)도 검사하는데 Map root는 범위(`^22.22.2 || ^24.15.0 || >=26.0.0`)를 선언하고 `.nvmrc`가 없어 실패한다(CI 실측). 그 이관은 engine-strict 아래 개발 Node를 22.23.1로 고정하는 별도 결정이다.
- ui·tokens는 내장 정책만 바뀌어 화면·CSS 변화가 없다. `VWorldMapHandle` 구현이 없어 rn 1.0.2의 `paddingPx` 확장은 해당 없다.

## 2026-11-17 — 공개 월별 축제 bbox 필터(PinVi 추천 여행 주변 축제)

- `GET /v1/public/festivals/monthly`에 선택 bbox(`min_lon`/`min_lat`/`max_lon`/`max_lat`, 4값 함께·일부만이면 422).
  목록과 `months` count 모두 `coord && ST_MakeEnvelope(…, 4326)`(GiST, 변환 없음 — ADR-012)로 좁히고 시도·시군구와 AND.
  map-markers와 같은 술어 조각(`_PUBLIC_FESTIVAL_BBOX_WHERE_SQL`)을 공유한다. 페이징은 기존 keyset cursor 그대로.
- 동기: PinVi `/notice-plans/{id}/highlights`가 시도 첫 50건만 읽어 바쁜 달에 근처 축제를 놓쳤다. user·full OpenAPI
  additive 변경(service 불변) — PinVi user 재vendor. 배포는 PinVi와 함께(PinVi는 옛 Map에서도 응답 좌표로 다시 거른다).

## 2026-11-16 — 북카페 재적재가 기존 행을 바꾸지 못한 원인: 재투영 scope 누락

- 증상: #1501 배포(t1116d) 뒤 `feature_place_mcst_culture_job` run `78380ace` SUCCESS인데 '카페 에무' 등이
  `01040000`/`museum` 그대로.
- 운영 실측(읽기 전용): dataset 50 `mcst_cafe_bookstores_csv` head 1,059건 전부 11:14Z에 관측 전진(run이 처리함),
  현재 record hash는 10-23 것 그대로 → `became_current` 거짓 → 본문 미기록. 활성 1,054건 `01040000`, 원본이 바뀐
  5건만 `02020000`. base 소유자는 dataset 50 자신이고 override 없음.
- 원인: 같은 원본 재투영은 `_CATEGORY_REPROJECTION_SCOPES`에 든 dataset만 한다. #1501이 그 scope를 빠뜨렸다.
- 수정: scope에 `mcst_cafe_bookstores_csv` 추가 + `_FIXED_FEATURE_CATEGORIES` ⊂ scope 단위 검사 + 통합 재투영
  검사에 북카페 형태 추가. prod 반영은 배포 뒤 북카페 dataset 재적재 한 번.

## 2026-11-16 — MCST 북카페를 카페로 표시

- 소유자 결정: `cafe_bookstores_csv`(북카페) 행의 표시 분류를 01040000 문화시설 → 02020000 카페.
- 목록 분류 `spec.category`는 feature_id seed라 그대로 두고 `_structured_category`의 고정 표시 분류로만 바꾼다.
  ID를 바꾸면 재적재가 새 행을 만들고 기존 행이 고아로 남는다. 회귀 검사 `test_cafe_bookstore_is_cafe_but_keeps_list_seeded_feature_id`.
- prod 반영은 배포 뒤 MCST `cafe_bookstores_csv` 재적재가 필요하다.

## 2026-11-16 — SRCH-002 "안동장" 첫 행은 Map 순위가 아니다

- PinVi live e2e(20261112-125734) SRCH-002: 서울 화면에서 "안동하회마을" 첫 행이 "안동장". prod Map(451) 직접 실측은 안동하회마을 1위(rank 10000108, 품음 단계 1·목적지 일치), 서울 중식당 안동장은 trigram만(0.22, 단계 2) 24위였다.
- 원인은 PinVi `region_biased_items`: bbox 없이 전국 40건을 받아 화면 안 행을 최대 limit//2개 앞으로 당긴다 — 일치 단계를 모르므로 유사도만 행이 이름 일치를 넘는다. Map은 q+bbox를 단계 안 가중으로 이미 처리한다(서울 bbox로도 안동하회마을 1위). 고칠 곳은 PinVi(bbox를 Map에 넘기고 클라이언트 재정렬 제거).
- Map 쪽은 그 계약을 회귀 검사로 고정: `test_bbox_never_lifts_a_similarity_only_row_over_a_name_match`.
- 분류 라벨: "카페 에무"=MCST 북카페 CSV 데이터셋 고정 분류 01040000(문화시설, 정책), 캠핑장=MOIS 유원시설 인허가 "수원산 오토캠핑장 트램펄린" 01010400(데이터 그대로 맞음). 롯데호텔 서울·김포국제공항은 main(#1499+452)로 숙박·공항이 첫 행임을 prod DB에 main 코드로 확인.

## 2026-11-12 — 접기 대표 회귀(#1495 후속)

- 배포 뒤 rankprobe: 접기 대표를 순위로만 골라 관광 그룹 0의 MCST 촬영지 행(01000000)이 MOIS 호텔 행을 숨겼다. 대표 = (구체 분류, 비MCST, 순위), 자리는 무리 최솟값. 원천 조회는 둘 이상 무리에만.

## 2026-11-12 — D2 fixture가 Feature 쓰기 gate를 긴 대기로 먼저 잡는다

- t1112b(Map aa38c30a) D2는 spec 2/2 통과 뒤 helper `purge`가 55P03(lock timeout)으로 죽어 `purge-failed` BLOCKED.
  gate 함수가 세션 `lock_timeout` 0을 1초로 바꿔 잡는데, 같은 시각 큐 적재(krforest 산사태 notice)가 쓰기 단계에서 gate를 쥐고 있었다.
  UI(#1496)·검색(#1481) 회귀 아님. lane은 runbook §6 `recover`(identity 일치)로 정리(잔여 TVN36 1건 purge), D2 재실행 GREEN.
- 고침: fixture `seed`·`cleanup`·`purge`가 DB를 건드리기 전에 `execute_with_lock_wait`로 gate를 600초 상한으로 먼저 잡는다.
  뒤의 procedure 획득은 같은 transaction 재진입이다. 회귀 검사 `tests/unit/test_d2_fixture_gate_lock_wait.py`(수정 전 red 확인). 다음 회전에 실린다.

## 2026-11-11 — 예보 단기 전량 ReadTimeout 원인·page size

- 단기 위치 약 1,450곳이 limit 2,000 페이지 하나에 들어 요청 하나가 artifact 전부(cold 약 1,174초)를 읽다 300초 timeout. 예보 page size 200으로 나눔. 초단기 상한 600→1,800초. 초단기 808건 거부는 weather 원천 coverage였다.

## 2026-11-12 — 검색 3단계 main 병합과 C11 검증 보존

- 검토된720과 upstream5742b45의 이력을 merge로 보존했다. incoming 코드·검사16개는 main 원문 그대로다.
- frontend/root package·lock·vendor·C11 Scope2 payload는720과 동일하여 D286/286·unit440·Doctor0 증거를 재사용한다.
- backend 검색·SQL·migration·archive 단위104PASS. Dagster 대상은 로컬 redis 의존성 누락으로 수집불가 원시를 보존했고 새 정확 HEAD CI로 확인한다. 실제 DB/Dagster 작업은 실행하지 않았다.

## 2026-11-12 — C11 D의 정렬 버튼 회귀 검사 보강

- C11 새 이미지 D에서 정렬1건이 원 실행/재시도 모두 옛 로컬 bg-brand 클래스 단언으로 실패했다.
  원286검사·실패/trace/report를 taskroot validation/c11-map-weather-20261112/에 보존한다.
- 공통 Button은 bg-primary를 쓰고 Map의 primary는 기존 brand 토큰에 연결된다.
  해당 검사만 aria-pressed·공통 variant·실제 brand 배경색과 비선택 대비를 함께 확인하도록 보강한다.
  정렬 GET/cursor 단언·286 inventory·retry/timeout·앱 runtime·lock/vendor는 유지한다.
- 부모 batch1 frozen6b 이후 테스트1파일/이 기록만 별도 delta다. 수정 후 전체 D를 새 source로 재검증한다.
  첫 D285PASS/1FAIL을 최종 성공으로 집계하지 않는다. Weather 새 build/20+5도 같은 슬롯2에서 이어 실행한다.

## 2026-11-12 — main 검색 2단계 병합과 C11 runtime 기준 보존

- origin/main cb38c33b40d3b041a0b6df3fb50f340d1c98839a의 검색 순위2단계 변경을 merge한다.
  기존925/e4/f55/C11 f569 commit은 재작성하지 않는다. 문서 충돌2개는 incoming 새 절과 기존 이력/보관 인덱스를 함께 보존했다.
- 비문서9개는 incoming 원문과 동일하고 frontend 전체·root package/lock/vendor는 f56976ec9adf7482e66299195aea0cd381eca667와 같다.
  유입 category/feature repository/속성 SQL 및 archive 링크 단위123PASS. DB/수집기 lifecycle·실제 migration은 실행하지 않았다.
- C11의 전체440·Doctor0·lint/type·local/external canonical guard·npm peer0을 n150 f569 source로 확인했고,
  새 production 이미지의 정식D286 strict/전체runner cleanup과 Weather20+5는 같은 슬롯2에서 진행 중이다.
  이 merge에서 UI를 바꾸지 않았으므로 frontend 전체를 다시 설치/빌드하지 않는다. 원 리뷰/CI delta는 별도 재확인한다.

## 2026-11-12 — 검색 순위 3단계(검색 인지도, alembic 451)

- 1차 설계(이웃 300 m 안 이름 포함 행의 원천)는 prod 여주 846행에 59 s — 쌍마다 정규화. 같은 이름 해시 결합 + 국가유산 이름 낱말 해시 결합으로 바꿔 전체 34만 행 5.3 s(읽기 전용 실측). 분포: 0(MOIS 단독) 195,651 · 1 95,401 · 2~6 약 5만 · 7~9 94. 신륵사(여주) 6, (제천) 4.

## 2026-11-12 — 검색 순위 2단계(실효 그룹·중복 접기)

- 상위 8개의 25%가 같은 장소 반복(MCST 4종·TourAPI·표준데이터). 첫 접기는 행 쌍 반조인(`OR NOT EXISTS`)이라 후보 제곱 — "강화 펜션" 44 s. 대표 거리 창 함수 → 적대 리뷰(휴게소 상·하행 접힘, 다른 도시 무리 미접힘) 뒤 키별 DBSCAN 무리 + feature_id 해시 반조인.

## 2026-11-12 — C11 정본과 FocusScope fix2 채택

integration-11-review 단일pack의 원장7개·vendor7개를 동일 bytes로 동기화한다.
공통 producer a35481349d6747b4f13b958ae64d9c0bbd0b5413,
FocusScope source1752a539c8d5ae57961a0fa2702d2573d48fefe7의
1.3.1+kortravel.fix.2를 runtime file 직접 의존성과 root override로 연결한다.
Lightning CSS fix.4는 dev 필수이며 지도9a bytes를 유지한다. RN은 vendor/원장에만 두고 웹에 설치하지 않는다.
중앙 workflow 실행 코드는55a921b55d248106cbe320e7f5305f3d3cdb60fe를 유지한다.
C10 checkpoint·원925/e4·원 A/B와 전후 실패 로그를 보존한다.
n150 슬롯2에서 기존 cache를 재사용해 명시 file 설치/실제 UI94+tokens25+Scope15 bytes,
외부 C11 canonical guard 및 최종 frontend gate를 검증 중이다.
검증 완료·독립2리뷰·CI·merge·부모 go 전까지 배포하지 않는다. DB/API/RustFS/Dagster lifecycle 변경 없음.

## 2026-11-12 — A 검토의 공통 Button variant/size 전달 수정

- 원A의 A-CONS-P2-02를 같은 SSR 대조로 재현했다. ghost/link/outline·icon-xs metadata가
  default로 남고 ghost/link에 primary 채움이 남았다. Common 직접 호출은 정상이다.
- variant/size를 공통 primitive로 전달하고 로컬 전체 CVA 색상/크기 recipe는 공통 정본에 위임했다.
  Map에는 focus outline·disabled 설명 도달성 정책만 남겼다. loading root/라벨/포커스·접근성 이름과
  활성화 차단은 유지한다. Link용 buttonVariants도 같은 공통 크기를 사용한다.
- 새 회귀8개는 수정 전6FAIL/2PASS, 수정 후8PASS. 기존adapter21개를 포함해29PASS,
  세 파일 타입·scoped lint PASS, 실제 Map source 전체 Doctor325files 진단0이다.
  기존 Geo 도구/동일 c9 Common Button 원문을 읽기 재사용한 경량 fixture임을 구분한다.
- b102의 GitHub Python3.11/3.12/3.13 unit+lint 단계는 모두 PASS를 확인했다.
  전체 API/Dagster job 완료 및 중앙 정책 PASS와 혼동하지 않는다.
- C10은 metadata/hash checkpoint만 유지한다. disabled fieldset Scope fix2의 C11과 부모 n150 슬롯 전까지
  Map/Weather heavy 설치/build/browser는 보류한다. C11에서 실제 Map 기존432+새8 전체·Doctor/build/
  D286 strict+cleanup을 확인하며, 현재29개를 전체440개 성공으로 집계하지 않는다.
- taskroot validation/map-A-button-closure-20261112/에 before/after SSR·8개·21개·type/lint/Doctor를 보존한다.
  원A/B raw와925/e4/b102 이력은 그대로 두고 원 reviewer closure용 별도 delta를 제공한다.

## 2026-11-12 — B 검토의 CI 계약·문서 크기 실패 수정

- e4 CI와 같은7개 실패를 원 단언 그대로 재현했다. 원시 job 로그와 before7FAIL을
  taskroot validation/map-B-closure-20261112/에 보존한다. 원925/e4·B원문은 수정하지 않는다.
- verify-all-gates에 공통 의존성 명령을 실제 mirror하고 기본 npm/고정 npm의 workspace script를
  같은 감사 규칙으로 읽는다. 명령 삭제·workspace 바꿔치기 변이도 검출한다. 면제는 추가하지 않았다.
- root override 계약은 정본의 CSS와 추후 C10 FocusScope만 명시적으로 direct file/override/모든 lock copy와
  대조한다. 미등록 override·stock 중첩 copy·SRI/선언 drift는 거부한다. package/lock/vendor는 아직 불변이다.
- Playwright runner 계약은 frontend 선언 버전과 immutable64자리 digest를 대조한다.
  Geo 안내 문장은 제품 literal을 유지하며 파서가 포매터 줄바꿈을 읽고 식/문구 drift는 검출한다.
- 관련7개 모듈90PASS(정상/변이 대조군 포함). 전체 backend unit은 기존 WSL venv의
  common/redis/pyshp/timeout plugin 누락으로 collection10오류다. 원시 로그를 보존하고 정확 HEAD CI에서 재검증한다.
- 오래된 완전한 절을 journal-2026-10g/resume-2026-09e에 원문 그대로 보관하고 인덱스/링크를 남겼다.
  옮긴 절을 되넣어 기존 문서가 byte-exact로 재구성됨을 확인했다. 한도225280은 바꾸지 않았다.
- C10은 다음 별도 후보 채택 단계다. n150 heavy 슬롯은 부모 배정 대기이며
  공통·UI runtime·lock/vendor 재포장·운영 API/DB/Dagster lifecycle은 수행하지 않았다.

## 과거 기록 아카이브

> 현행 작업 창(2026-10-01~) 이전 기록은 아래로 분리했다. 검색은
> `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
| [journal-2026-10j.md](archive/journal-2026-10j.md) | 2026-10-24 ~ 2026-10-28 | 91건 | 66211 bytes |
| [journal-2026-10i.md](archive/journal-2026-10i.md) | 2026-10-24 | 23건 | 24611 bytes |
| [journal-2026-10h.md](archive/journal-2026-10h.md) | 2026-10-22 ~ 2026-10-24 | 15건 | 27854 bytes |
| [journal-2026-10g.md](archive/journal-2026-10g.md) | 2026-10-14 ~ 2026-10-22 | 19건 | 47365 bytes |
| [`journal-2026-10f.md`](archive/journal-2026-10f.md) | 2026-10-13 | 3건 | 23787 bytes |
| [`journal-2026-10e.md`](archive/journal-2026-10e.md) | 2026-10-13 | 2건 | 21540 bytes |
| [`journal-2026-10d.md`](archive/journal-2026-10d.md) | 2026-10-13 | 2건 | 7200 bytes |
| [`journal-2026-10c.md`](archive/journal-2026-10c.md) | 2026-10-01 ~ 2026-10-12 | 28건 | 53974 bytes |
| [`journal-2026-10b.md`](archive/journal-2026-10b.md) | 2026-10-01 | 1건 | 6 KB |
| [`journal-2026-10a.md`](archive/journal-2026-10a.md) | 2026-10-01 | 1건 | 6 KB |
| [`journal-2026-09h.md`](archive/journal-2026-09h.md) | 2026-09-30 | 1건 | 4 KB |
| [`journal-2026-09g.md`](archive/journal-2026-09g.md) | 2026-09-28 ~ 2026-09-29 | 6건 | 22 KB |
| [`journal-2026-09f.md`](archive/journal-2026-09f.md) | 2026-09-26 ~ 2026-09-27 | 14건 | 31 KB |
| [`journal-2026-09e.md`](archive/journal-2026-09e.md) | 2026-09-20 ~ 2026-09-25 | 8건 | 27 KB |
| [`journal-2026-09d.md`](archive/journal-2026-09d.md) | 2026-09-16 ~ 2026-09-19 | 7건 | 22 KB |
| [`journal-2026-09c.md`](archive/journal-2026-09c.md) | 2026-09-14 ~ 2026-09-15 | 8건 | 22 KB |
| [`journal-2026-09b.md`](archive/journal-2026-09b.md) | 2026-09-11 ~ 2026-09-13 | 5건 | 26 KB |
| [`journal-2026-09a.md`](archive/journal-2026-09a.md) | 2026-09-01 ~ 2026-09-10 | 23건 | 84 KB |
| [`journal-2026-08d.md`](archive/journal-2026-08d.md) | 2026-08-29 ~ 2026-08-31 | 14건 | 25 KB |
| [`journal-2026-08c.md`](archive/journal-2026-08c.md) | 2026-08-28 ~ 2026-08-28 | 21건 | 20 KB |
| [`journal-2026-08a.md`](archive/journal-2026-08a.md) | 2026-08-14 ~ 2026-08-27 | 124건 | 200 KB |
| [`journal-2026-08b.md`](archive/journal-2026-08b.md) | 2026-08-01 ~ 2026-08-14 | 89건 | 166 KB |
| [`journal-2026-07c.md`](archive/journal-2026-07c.md) | 2026-07-26 ~ 2026-07-31 | 60건 | 167 KB |
| [`journal-2026-07a.md`](archive/journal-2026-07a.md) | 2026-07-13 ~ 2026-07-24 | 115건  | 219 KB |
| [`journal-2026-07b.md`](archive/journal-2026-07b.md) | 2026-07-01 ~ 2026-07-12 | 28건   | 45 KB  |
| [`journal-2026-06a.md`](archive/journal-2026-06a.md) | 2026-06-10 ~ 2026-06-30 | 172건  | 219 KB |
| [`journal-2026-06b.md`](archive/journal-2026-06b.md) | 2026-06-02 ~ 2026-06-10 | 179건  | 220 KB |
| [`journal-2026-06c.md`](archive/journal-2026-06c.md) | 2026-06-01 ~ 2026-06-02 | 36건   | 53 KB  |
| [`journal-2026-05a.md`](archive/journal-2026-05a.md) | 2026-05-24 ~ 2026-05-31 | 90건   | 218 KB |
| [`journal-2026-05b.md`](archive/journal-2026-05b.md) | 2026-05-24 ~ 2026-05-24 | 3건    | 7 KB   |


### Rest432 후속: 실제 원자성 및 공식 스키마

- 실제 원자성11개 PASS: 오류·취소 전체 rollback/동일 plan 복구/성공 commit 응답경계 SDK0.
  초기quota3행·사용량0/guard33 단언과 정확 시험 DB·볼륨 정리를 확인했다. Rest215·두 writer는 미완이다.
- 정본 package graph 누락1F28P를 공식 generator로 수정하고29P, 두 명 검토 후 반영했다.
- 별도 fresh 공식 schema432 생성·재비교1P27.459초, dump a55cf046. 예상2추가/5변경만이며
  역치환은 기존431 전체 bytes exact다. startup ACL/metadata 및 최종 CI/live·배포는 진행 중이다.


### 2026-11-04 — #1448 중간 구현
- #643/#1444 최신 본문·댓글을 다시 읽었다. 추가 변경 없음. WSL 검증·머지만 수행한다.
- python-mcst-api PR #20 merge SHA로 consumer pin을 갱신했다.
- MCST 적재 직후 dataset별 causal seal을 완료하고, 재시도에서 done member는 재적재하지 않는다.
- fetch/load 실패를 dataset별로 모으고 성공 member에는 실패 attempt를 쓰지 않는다.
- WSL MCST 단위 22건·변경 source mypy 통과. 실제 PG·UI·두 독립 리뷰·최종 CI는 진행 중이다.


### 2026-11-04 — #1448 선택 경계·실제 PG/UI 보완
- 두 독립 예비 적대 리뷰의 범위 밖 적재(P1), 비선택·비활성 필수 resolve, 일시 DB/SDK 네트워크 재시도, SDK 코드명, UI 원인 누락을 수정했다.
- frozen ID만 표시 key로 연결하고 변환·적재 전에 선택 집합을 적용한다. 완료·중복·외부 callback 거부와 완료 command 실패를 구분한다.
- MCST root 상세에 하위 작업 이벤트를 시간순 cursor로 합쳐 실패 원인·작업 이동을 제공한다. cursor는 child 포함 여부에도 묶이며 기존 다른 조회는 유지한다.
- dataset 이벤트에도 기존 payload를 전달하는 additive admin API 필드를 추가했다. 진단 UI는 허용한 code/phase/reason/retryable만 렌더링한다.
- 실제 PG wrapper 12/13 및 좁힌 manifest·비선택 비활성 회귀 2건, 관련 lifecycle/ops PG 54건, 관련 API 198건, targeted Dagster 112건을 통과했다.
- 실제 공식 keyless golf CSV를 Map 기본 factory로 1행 제한 조회(14열·필수7열)했다. MockTransport SDK 승인·CAPTCHA·메타·네트워크·ZIP 모호성·HTML 오류를 별도로 검증했다.
- 실제 WSL PG/API/Next/Chromium에서 관리자 로그인·12/1 요약·원인·하위 작업 응답 후 이동 4흐름 통과. root/child 스크린샷을 직접 검사했다. 원본 API 응답 대체 없음.
- WSL 폐쇄 포트가 reject 대신 drop되는 경우를 허용하도록 fail-closed 테스트의 psycopg OperationalError 하위 ConnectionTimeout 표기를 보완했다. 제품 연결 정책은 그대로다.
- 전체 API 1,600건·main unit/lint 3,643건·frontend 418건, frontend type/lint를 통과했다. 이후 최종 head의 전체 CI·두 독립 재리뷰를 진행한다.


### 2026-11-04 — #1448 최종 타입 경계 보완
- CI strict API mypy에서 조건부 kwargs의 bool dict 추론 오류를 확인했다. 같은 조건을 명시적 bool 인자로 전달하도록 보완했다.
- API 72개·Dagster 38개 파일 strict mypy 및 pipeline API 162개를 다시 통과했다. 최종 CI는 새 head에서 확인한다.


### 2026-11-04 — #1448 최종 적대 리뷰 보완
- 앞선 영구 수집 실패와 후속 완료 기록의 일시 실패를 함께 보존한다. 아직 loop에 도달하지 않은 fetch 실패도 집계하며 영구 실패가 하나라도 있으면 전체 재시도는 닫힌다.
- 원문 예외 연쇄를 억제하고 실제 Dagster 오류 직렬화에서 sentinel 미노출을 확인했다. dataset 순서 두 경우 모두 양성 통과, 직전 구현은 새 단언 2건 모두 실패했다.
- SDK 승인·quota 경계·MCST 회귀·schedule fail-closed 114건 통과. 실제 PostgreSQL 전체 1,624건 통과·기존 조건부 skip14. 실제 wrapper/narrow 2건과 관련 lifecycle/ops54건 포함.
- 최신 source로 실제 WSL PG/API/Next/Chromium 5흐름을 재검증했다. root/child 작업 이동은 실제 child 응답과 event job ID까지 대조했고 dataset 이력에서도 같은 원인을 확인했다. API 응답 대체 없음. 스크린샷 직접 검사 및 소유 스택 종료.
- additive admin payload 변경에 맞춰 OpenAPI baseline과 기존 pending consumer receipt의 SHA만 재핀했다. pending 상태·배포 차단 사유는 보존하며 운영 검증을 완료로 바꾸지 않았다.
- provider 원본은 immutable pin SHA를 읽어 표면 manifest --check를 통과했다. 기존 형제 checkout은 읽기만 했고 수정하지 않았다. 계약·표면 검사 43건 통과.
- 최종 head의 두 독립 재리뷰와 CI 후에만 머지한다. 운영 접근·배포·테스트 없음.

## 2026-11-12 — origin/main 병합·925c 리뷰 기준 보존

- 기존 리뷰 commit925c48c74는 재작성하지 않고 origin/main41de16d을 merge한다.
  충돌한 CHANGELOG/journal/resume3개는 양쪽 기록을 모두 남겼다.
- main의 검색 지역 별칭·낱말 덮기 SQL/cursor v6·alembic450과 관련 테스트12개 제품/검사 파일은
  incoming 원문과 일치한다. frontend 전체·root package/lock·vendor는925c와 동일하다.
- 검색/SQL/forward-only 마이그레이션/속성 SQL 단위4개 파일171개 통과,
  유입 Python 파일 ruff와 application migration graph --check 통과.
  DB/API/Dagster lifecycle이나 실제 migration은 실행하지 않았다.
- 부모 workflow는925c에서 이미 커밋·push했다. 원A/B는925c immutable 기준으로 계속하고
  이번 merge-only delta는 별도 재검토한다. common49와 후속 C10/FocusScope 산출물 정책은
  부모/Harvey 소유이며 이번 병합에서 common/산출물은 수정하지 않는다.
- 남은 gate는 정확 merge HEAD CI·delta recheck·최종 release freeze·main merge/부모 go다.
  Map UI-only 배포는 공식 Manager pin/receipt 승격 경로 확정 후에만 진행한다.
  증거는 taskroot validation/map-merge-20261112/에 보존한다.

## 2026-11-12 — c9 정식 D 전체 runner·cleanup exit0 확정

- exact e3ea216c128c3e7ef5346b17db6d4ec3fd5272a0의 새 production 이미지로
  정식 D286/286·flake0·skip0·strict inventory 일치를 확인했다.
- 전체 runner passed/exit0/issues[]이며 독립 exact 조회도 소유 container/network/image 잔존0이다.
  과거 후보6 cleanup exit2와 c8 unit431/1 원시 로그는 그대로 보존했다.
- c9 전체 unit432, reporter/cleanup37, lint/type, Doctor324files 진단0, guard/canonical,
  npm tree/NextSharp/CSS 공개 API 모두 통과했다. 전체 unit은 worker2로 실행했다.
- 사용5개 artifact·원장·lock은 최신 integration-9-review와 일치한다.
  UI/tokens installed checker byte 일치도 확인했다. 후속 commit은 문서만 갱신한다.
- 원시 증거와 프로세스·정리 증거는 taskroot validation/map,
  최종 인계는 AGENT-HANDOFF-codex-map-weather.md다.
  부모 중앙 workflow는 보존·제외하고 독립2리뷰/CI/merge/부모 go 뒤 UI 배포한다.

## 2026-11-12 — c9 정책 검사기와 동일 runtime 산출물 동기화

- integration-9-review의 사용5개 vendor/원장/lock SHA512를 대조했다.
  UI·tokens의 이전 c8과 다른 archive member는 check-dependencies.mjs 하나씩뿐이다.
  runtime·CSS bytes와 core/web/Lightning CSS fix.4는 그대로다.
- explicit npm12 lock-only 설치로 같은 파일명 UI/tokens의 integrity를 갱신했다.
  실제 설치·guard·Doctor·fresh286 D와 cleanup exit0는 n150 전용 cached checkout에서 확인한다.
- c8 단위검사431통과/1실패 원시 로그를 보존했다. 수동중복판정의 실패 안내 대기를 재검증하며
  실패/skip 허용이나 타임아웃 완화 없이 원인을 확인한다. 부모 중앙 workflow는 제외·보존한다.

## 2026-11-12 — c8 동일 산출물 채택과 정식 D 정리 gate 재검증

- 공통670a753의 integration-8-review UI/tokens와 동일 core/web, Lightning CSS fix.4를
  원장 SHA512 대조 후 채택했다. root/frontend 직접 dev 의존성과 root $lightningcss override를 연결했다.
- 같은 파일명의 이전 UI/tokens integrity가 npm 기본 lock-only에 남아 명시 package install로 갱신했다.
  WSL Map node_modules는 만들지 않고 실제 설치/검증은 n150 기존 전용 checkout을 재사용한다.
- Docker 지연 삭제는 최대5분의 제한된 부재 재조회로 확인한다. 소유 label/ID 검사는 유지하고
  성공한 빈 조회만 인정한다. CLI close 뒤 stdout을 판정하며 남은 예산을 각 조회 timeout에 전달한다.
- 정식 D 전체286개와 모든 gate는 후속 결과를 원시 로그와 함께 기록한다. 부모 workflow는 제외·보존한다.

## 2026-11-11 — Map 정식D 브라우저286통과·Docker 후행 정리 인계

- exact9d187a61d에서 D 브라우저286/286·flake0·manifest일치, Playwright child exit0.
  runner는 n150 Docker removing 지연으로 cleanup_container_remaining exit2였다.
  후행 exact 조회에서 소유 container/network/image 잔존0과 worker/runner 종료를 확인했다.
- unit427·reporter32·lint/type/build33routes·Doctor322files0·최신 localcanonical 통과.
  원시exit2는 보존하고 인프라 gate 재확인은 부모 CI에 인계한다.
- 부모소유 workflow는 커밋에서 제외·보존. 최종pack/foundation CI/독립2리뷰/merge/부모go 뒤 배포한다.
  [검증·실제배포계획](reports/common-unification-20261111.md), taskroot의 전용handoff/리뷰패킷 참조.

## 2026-11-11 — Map 전체 브라우저 통과와 checkpoint gate 정렬

- exact1ce5a1148에서 286/286 통과·flake0을 확인했다. A는 과거 실패 재현 단계이므로
  성공 상태를 거부했다. 기존 manifest도 284개에 머물러 실제286개 inventory와 달랐다.
- 실패·skip 허용 목록은 빈 상태로 유지하고 관측한286개 identity hash만 재고정했다.
  정식 성공 checkpoint D로 다시 검증한다.
- Docker 정리 CLI 1초 제한 때문에 제거 확인이 실패했다. 소유권·ID·잔존 검사는 유지하고
  명령 제한을30초로 늘려 지연된 daemon 응답을 기다린다. 운영 자원은 수정하지 않는다.

## 2026-11-11 — Map 두 번째 checkpoint285/286와 마지막 fixture 정렬

- 지도/탭 포커스/History/초안 복원은 통과했다. 남은1개는 orphan run의 summary fixture누락이다.
- summary/list/detail에 같은 실패 run을 넣고 공통 상세 버튼 이름으로 검사한다.
  e2e 타입/lint/spec로딩 통과. 앱runtime source변경은없다.
- 부모소유 common-frontend-policy.yml은제외·보존, localcanonical은최신외부policy와원장으로통과.

## 2026-11-11 — 후보6 브라우저 회귀와 fixture 보완

- 첫 checkpoint230통과/56실패를 보존했다. 지도 public mapStyle 복구는 브라우저에서 확인됐다.
- 지도/URL 탭을 Enter·Space 확정으로 지정하고 중복 History 기록을 막았다.
  Alert data-variant와 Radix data-state 검사, canonical transport/Dagster 조회 fixture를 보완했다.
- unit427/427·lint/type/Doctor0/guard 재통과. exact 후속 checkpoint 결과를 별도로 기록한다.

## 2026-11-11 — common 후보6와 키 없는 지도 public mapStyle 복구

- common `a14301c` / upstream `9a7a348`의 동일 tgz·원장을 설치했다. core는 1.0.1로
  갱신하고 1.0.0 활성 참조·vendor를 제거했다. 라이선스/NOTICE/src 동봉 원본 bytes를 보존했다.
- Map wrapper는 빈 키·공백·CHANGE_ME에 모듈 상수 style을 전달하고 실제 키는 upstream 기본 style을 쓴다.
  자체 지도 생성자·가짜 키·비공개 소스 import는 추가하지 않았다.
- 자동완성 기존 2건과 형태 회귀 6건을 포함한 unit427/427, lint/type/build33routes/Doctor0/
  AST·원장 guard/npm tree/NextSharp 통과. n150 exact checkpoint와 최종 freeze/review/CI는 후속 gate다.
- [후보6 검증 기록](reports/common-unification-20261111.md), [산출물 출처](third-party-common.md).

## 2026-11-11 — 관리자 common Radix/VirtualTable·지도 public API 통합 후보

- 모든 admin 표를 common VirtualTable로 연결하고 Radix primitive/검색 Popover를 채택했다.
  최신 exact 의존성, Zod/RHF/Zustand/Pretendard 실제 사용과 CI AST/무결성·Doctor gate를 적용했다.
- candidate5 lint/type/build/guard/Doctor 진단 0. unit 419/421 통과, common LoginForm 자동완성
  2건은 부모 수정 요청. 최종 freeze·n150 격리 e2e·독립 리뷰·CI/merge/부모 go 전 배포하지 않는다.
- [구현·검증·배포 계획](reports/common-unification-20261111.md), [ADR-123](adr/123-common-admin-ui.md).

## 2026-11-12 — 검색 순위 1단계(alembic 450)

- 11-11 e2e의 "일반 질의에서 기대 행이 밀림"을 prod 읽기 전용으로 재현: 10건 중 다수는 기대값 문제였고, 진짜 결함은 영종 별칭(옛 중구)·분류 낱말 tail 일치·붙여 쓴 나머지("서프카페")·인천공항 별칭 부재. 44질의 평가 hit@1 39→40(450 적용 시 41). 적대 리뷰 반영: 한 글자 낱말 제외, 닻·긴 나머지는 문자·숫자 수로 판정.

## 2026-11-11 — ADR-122 개정: weather 멤버십 digest·clock epoch

- 세대마다 멤버십 장부(만료 묶음 유지)를 두고 증분 뒤 weather digest와 비교, 다르면 전량. 전량도 못 보는 미래 시각 없는 행이 있으면 검증 불가 사슬로 표시해 하루 주기에 맡긴다. epoch 바뀌면 전량.

## 2026-11-10 — ADR-122 weather 예보 증분 적재

- 단기·외부 전량이 odroid eMMC cold 1,174·674초라 run이 ReadTimeout. since 증분을 지금 Valkey 세대에 병합(기준 세대 CAS), cursor는 세대 meta. since엔 tombstone이 없어 24시간마다 전량. migration 없음.

## 2026-11-10 — 박물관·관광지도 공개 파일

- 박물관 403·관광지 00, 둘 다 파일로. 파일 행에 INSTT_CODE(기관 코드, 박물관 215·관광지 164개)가 실려 키가 지자체로 뭉칠 뻔했다(리뷰 HIGH) — 세 표준 dataset 키에서 instt_code 제외.

## 2026-11-11 — 영문 괄호 이름 검색·대피소 現 표식

- 별칭 행 대신 검색 SQL이 끝 라틴 괄호에서 한글·영문 이름을 떼어 이름 일치로 본다(migration 없음). 짧은 한글+긴 괄호는 후보도 못 돼 ILIKE 팔 추가. knps-api a472a37 핀; 같은 raw 재적재가 이름을 안 고쳐 고친 이름을 해시에 넣었다.

## 2026-11-11 — 촬영지 미분류 회귀(dataset 48)

- 원인은 #1480이 아니라 5fcb015(11-04 "실제 MCST 분류 반영")다. 테마 목록의 업종 없는 행을 미분류로 내렸고, 촬영지 CSV는 TYPE이 8,803/8,803 비어 있다. 11-10 재적재(같은 원천 head 재투영)가 처음으로 그것을 운영에 반영했다. 촬영지 fallback을 목록 분류(관광 Tier 1)로 — 캠핑 목록과 같다. 운영 복구는 핫픽스 회전 뒤 dataset 48 재적재(손 SQL 없음).

## 2026-11-10 — 축제 원천 TourAPI 단독(449)

- 소유자: 표준데이터 축제 아예 쓰지 않음(키 403). TourAPI searchFestival2가 1차 event(879건, 좌표 100%). 449가 표준축제·보강 op 끄고 비활성, 1,296건 퇴역. PinVi 참조는 삭제된 시험 여행뿐(M05 없음). detailCommon2는 관광지 600+축제 300.

## 2026-11-10 — 주차장 키 403 → 공개 파일

- 운영 키가 주차장·박물관 Open API에서 403(관광지는 00). 주차장 파일 18,994행·고유 17,878, prod 키 17,986 중 17,875 일치(은퇴 경로 아님). 박물관·관광지는 다음 PR.

## 2026-11-10 — #1475 admin 부분 검색 3~12 s

- 원인: lower(name) keyset을 36만 행 걸으며 행마다 ILIKE, all은 raw_data 505 MB 전 스캔. 447 비부분 trigram 6개로 후보 id를 먼저 모으고(≤2,000) 넘치면 종전 훑기. raw_data 검색 제거. D2 run_id 6~12 s→약 50 ms.

## 2026-11-11 — #1468 A R4 전환 실행기

- 실행기 `ktmctl mcst-theme-transition`(계획 파일 sha 확인, batch = transaction 하나, protocol EX), 장부 `ops.mcst_theme_transition_batches`·`_items`, M05 사건 출처 일반화(`origin_kind` + 출처별 생성 열 FK, payload 모양 그대로 — PinVi 재vendor 불필요).
- 적대 리뷰 반영: batch 정체에 크기 포함, error 하나면 batch 되감고 멈춤, 사건 writer가 장부를 command·전이·병합 이력과 대조, 퇴역 master 병합 거부, 대상 quality 확인, 패자의 열린 dedup 검토 행 닫기, before_state에 대상 link·curation 행 전체.
- 표본(규칙 고치기 전): 대부분 목록 ≈100%, 레저활동·촬영지·반려 collapse가 낮았다(부속 시설 `…3관`·`…야영장`, 번호 동, 100m 넘는 한쪽 지점). 이름 쌍 거절 규칙을 더하고 표본은 회전 뒤 다시 뽑는다.

## 2026-11-10 — #1468 A R1·R3 구현·R2 운영 dry-run

- 붙임 엔진(owner·sticky·redirected·matched·created·ambiguous·unresolved), 전환 계획기 `ktmctl mcst-theme-plan`, migration 446, 속성 필터·응답·catalog·판정 조회 API.
- R2(운영 읽기 전용, 리뷰 반영 뒤 3분): MCST 88,007 → retire 20,396·attach 7,501·collapse 7,073·keep 51,064·ambiguous 1,973(대부분 비MCST master끼리 동점 — B dedup 뒤 줄어든다). PinVi 참조 1,020행(161 Feature, 전부 attach/collapse — rebind 가능).
- 첫 계획 질의가 `publication_state IN (...)` 때문에 부분 GiST 색인을 못 써 30분 넘게 돌아 취소했다(색인 조건 그대로 쓰도록 고침). tier 2 동점을 ambiguous로 보던 규칙이 ambiguous의 3/4를 만들었다.
- 적대 리뷰 반영: 강등은 MCST link만(MOIS 승자 판정 회귀), 부재 가드 강화, 비병합 퇴역은 owner로, 빈 snapshot 손실 가드, 계획기의 비MCST master 제외·사슬 collapse 차단·물려받은 attach 분류 재확인.

## 2026-11-10 — 운영 검색 점검(#1476~#1478)

- 역·공항 1위가 MCST 촬영지·영상 후보 01000000이었다(그룹 0 < 1). 고유 이름 목적지의 이름 일치를 그룹 0으로, 시장도 목적지 그룹으로. 일반철도 행은 operator가 비어 지하철역(174). 여수엑스포는 transport 좌표 null(transport#179). 504는 PinVi 도달 전.

## 2026-11-10 — 휴양림 ↔ MOIS 숙박은 휴양림 master

- 소유자 결정: 산림청 자연휴양림 dataset 보정 55(MOIS 50 위). #1472 뒤 이 쌍은 MOIS가 이겼다. 수목원 115쌍도 그대로 휴양림 master.

## 2026-11-10 — #1468 D 국가유산 행사 회차 묶음

- prod 5,286행=행사 1,316개(같은 행사가 seqNo를 바꿔 반복, 좌표 0). 행사명·단체·지역·장소로 묶고 회차는 payload에. 좌표는 같은 시군구 동명 장소 Feature(310개, 23.6%)→번지 정지오코딩. 옛 키는 retire, PinVi 참조 0.

## 2026-11-10 — #1468 B·C dedup 재가동·원천 겹침 쌍

- prod 병합 0건: master 선정이 좌표→updated_at→원천이라 원천 순위가 사실상 안 쓰였다. 원천을 updated_at 앞으로, 표준데이터 35·MCST 20·YouTube 5, dataset 보정(KNPS 문화자원·수목원·산림청 등산로 40).
- 쌍 3개: 캠핑 MOIS↔KNPS·휴양림=수목원(이름 일치)·등산로↔KNPS 탐방로(선형 겹침). MCST 쌍 4개는 ADR-121 attach로 넘김. 반경 blocking·DB 반경 읽기. 기본 schedule RUNNING. migration 없음.

## 2026-11-10 — #1459 TourAPI 문화시설(14)·레포츠(28)

- 같은 dataset·snapshot에 14(2,753)·28(3,717)을 더했다. 레포츠 52%가 캠핑장(AC05)이라 0306으로, LS011900 중 '…길'은 트레킹. 상세 예산 600 유지 → 전량 약 32일. migration 없음.

## 2026-11-10 — ADR-121 accepted (소유자 결정)

- D1=b(master 없는 속성 행은 목록 무관 MCST 장소 하나, master 생기면 병합), D2(반려 업종 약 20,396 미적재·기존 Feature는 R4 퇴역), D3(촬영지는 큐레이션 `media-places` 후보→운영자 승격·공개).
- 설계 단순화: 공용 식별 namespace를 버리고 tier 2 붙임 + 기존 목록 앵커 + 병합 이력 redirect로 같은 효과. 부재 처리는 enrichment link만(primary 부재 퇴역은 현행 유지). 수렴 병합은 적재 밖 계획·executor.

## 2026-11-10 — #1459 여행지 검색 별칭(444)·분류 override 준비

- 별칭 7행(리움·리움미술관·수성못·김포공항·퍼플섬·사천바다케이블카·사천케이블카). 정본 이름은 prod 읽기 전용과 TourAPI searchKeyword2로 확인했다. 퍼플섬·케이블카는 #1465 적재 뒤에 닿는다.
- 분류 override 3건은 코드가 아니라 운영 작업이다 — docs/runbooks/1459-category-overrides.md.

## 2026-11-10 — #1468 A MCST 테마 목록 속성화 설계(ADR-121)

- 운영 읽기 전용 실측: MCST active 88,007. 겹침의 대부분은 MCST끼리(무장애↔가족 약 8천), 속성 목록의 비MCST master 일치는 4~13%(업종 master 미적재). 반려 목록의 20,396은 약국·용품·병원·미용 업종.
- 설계: 속성은 source link에서 유도(catalog 2표 + 붙임 판정표), 적재 시점 붙임 규칙 `theme-attach-v1`, 목록 무관 식별 namespace, `attribute` 필터·응답 필드, 전환 계획표·M05 사건 출처 일반화, PinVi 재vendor 순서. 적대 리뷰 2인 반영. 소유자 결정 D1(master 없는 속성 행: 보류 vs MCST 장소 유지)·D2·D3 대기.

## 2026-11-09 — KNPS 대피소 공식 원본 확인과 핀 상향

- 공식 원본을 직접 받았다. 기존 카탈로그 URL(FILE_000000000377005)은 2013년 중첩 SHP 8건(한라산 7·오대산 1)뿐이라 중청·장터목·세석이 없었다. 포털 현재 배포본은 FILE_000000003681543(_20230928): 평면 SHP 22건, UTF-8, EPSG:5186.
- PR18 파서는 현재 배포본을 DBF 필드명 10 bytes 잘림(`시설물\xeb`)으로 거부했다. provider PR19가 잘린 끝만 제거·대피소 전용 필드(시설물명/위치.주소/순번)·전부 이름 없음 시 실패·카탈로그 갱신을 했다.
- Map은 핀만 올리고 공식 fixture로 public client→Map 변환 회귀를 고정했다(22 place, 03080100/mountain_shelter, 중청 좌표). 주소·tel은 Map이 쓰지 않는다(역지오).
- source_id가 2013 ID_CD에서 순번 기반 `shp:` hash로 바뀐다. KNPS point loader는 snapshot에서 빠진 행을 retire하지 않지만(리뷰 지적), 운영 knps_shelters(provider_dataset 57)는 identity 0·03080100 feature 0이라 남을 옛 행이 없다(읽기 전용 확인).

## 2026-11-09 — MOIS 숙박 우선 적재·상호 정규화

- 감사: 12/42종만 적재. 업종을 숙박→관광→레저→대량 식음 순으로, 상호의 법인 표기를 걷고(442 통칭 별칭), 숙박 계열 세 업종의 같은 시설은 lodgings 하나로, 좌표 없는 행은 geo 정지오코딩. 업종 선택 run은 다른 업종을 은퇴시키지 않음을 확인.

## 2026-11-09 — #1459 TourAPI 관광지 적재 경로

- 운영 키로 KorService2가 200, 관광지 12,560건. 목록 cat1~3이 비어 신 분류 lclsSystm으로 매핑했다. 상세는 오퍼레이션당 1,000/일이라 run 예산 600·저장값 재사용. 산막이옛길(28)·태권도원·세종도서관(14)은 관광지가 아니다.

## 2026-11-09 — 전통시장·특화거리 공개 파일 원천(키 없음)

- 소유자: 두 표준데이터 파일은 활용신청 없이 받는다. 포털 공개 경로(`download/columList.json`→`standard.json`)를 provider PR#24 `9922dd2`로 넣었다(미머지 PR#22 주차장과 같은 경로·검산 + CP949/BOM·기형 행 거부). 실측 1,393·274행.
- Map: 두 fetcher를 키 없는 파일로, 선언 미달·0행 실패, 특화거리도 snapshot 은퇴·공용 정지오코더, 특화거리 disabled 해제. migration 없음.

## 2026-11-09 — #1459 지역 검색·좌표 결측 fallback

- prod: 좌표 없는 공개 행 24,863건(9 dataset). 번지 주소가 있는 축제·주차장·국가유산 2,313건은 asset이 reverse만 넘긴 탓이다.
- 지역 토큰→시군구 순위 자리(해석 19 ms, 질의 warm 10~250 ms), 번지 주소 정지오코딩, 좌표 없는 행 검색 제외, concierge 해수욕장 검증.

## 2026-11-09 — #1459 전통시장 표준데이터 적재 경로

- 원천은 공공데이터포털 15012894(소상공인시장진흥공단, 연간) 표준 Open API `tn_pubr_public_trdit_mrkt_api`다. 필드명은 공식 명세, 단위 fixture는 같은 페이지 미리보기 실제 행이다. provider PR#23(`649fa1a`)로 `traditional_market`을 더했다.
- Map: category `05.07 전통시장`(category.md §12), 자연키 `시장명::시도시군구`, 좌표 없으면 도로명→지번 정지오코딩, snapshot 은퇴(0행은 실패), MOIS 대규모점포·관광지 dedup pair, migration 439, 월간 schedule(STOPPED).
- 적대 리뷰 A: 부분 snapshot(2페이지 빈 응답)이 시장 400곳을 은퇴시킬 수 있어 선언 건수 미달을 실패로 바꿨다. 주소 편집에 흔들리던 키를 시군구까지로 줄였다.
- 운영 키는 이 API(그리고 기존 특화거리)에 활용신청이 없어 HTTP 403이다(박물관은 200). 적재 전에 소유자가 활용신청해야 한다.

## 2026-11-09 — #1459 휴게소·철도역·여객선 항구·공항 검색(ADR-120)

- prod 읽기 전용: 휴게소 place 215·공항 15는 이미 있으나 휴게소 이름이 "강릉(인천)"꼴이고, 공항은 관광 그룹이 이름 일치보다 앞서 "설해원(양양국제공항)"에 밀렸다. 역·항구 transport place는 0(T3 export는 운영 503, 꺼짐).
- 휴게소·역·항구 표시 이름, 역 노선 묶음(500 m), dataset 둘(438), 분류 06060000, 목적지 이름 일치 순위(cursor v4).

## 2026-11-07 — Valkey 상태 쓰기 일시 실패 재시도

- n150 sda flush 대기로 weather_state_daily_summaries가 step 재시도 3회 모두 `세대 쓰기 실패: TimeoutError`(2 s)로 죽었다. step 재시도는 원천을 다시 받아 같은 자리에서 또 죽는다. 세대 묶음·meta·포인터 교체·잠금 해제를 그 자리에서 3회(1·2·4 s) 다시 한다. 응답만 잃은 교체는 CAS가 이 세대를 돌려주면 성공으로 본다.

## 2026-11-07 — 통합 테스트 PG 비내구·tmpfs

- n150 sda flush 포화의 최상위 기록자가 test gate PG(fsync on)였다. 모든 테스트 cluster를 `_disposable_pg.make_nondurable`로 fsync·synchronous_commit·full_page_writes off + `/var/lib/postgresql` tmpfs(기본 3g, `KTM_TEST_PG_TMPFS_SIZE`)로 띄운다. unit 가드·서버 효과 검사 추가.

## 2026-11-07 — #1455 저배율 in-bounds cluster 집계

- prod 읽기 전용 EXPLAIN: 전국 bbox route/area cluster가 `feature_id = ANY(5.8만 배열)` 선형 대조와 view geom 산출식 3중 평가로 15~30 s, PinVi 기본 kind도 쓰지 않는 등산로 후보를 매번 계산했다.
- point/geometry arm UNION ALL·대표점 1회·bbox 내부 geometry는 교차 생략·point-only 변형. 군집 수·개수 동일(좌표 차 ≤8e-6°).
- prod SQL: z7 PinVi 2.9→0.25 s, route/area 12~15→1.0~1.3 s. 22 s 느린 요청 중에도 작은 요청은 0.010 s라 단일 worker가 막히지 않는다(async DB).

## 2026-11-07 — KNPS 대피소 미적재 후속

- 사용자가 다른 미적재 KNPS로 범위를 확대했다. Claude Code의1452/1453과 완료된1회 적재·정책 결정을 먼저 읽고 대피소 upstream17만 남았음을 확인했다.
- source draft18과 Map draft1454를 먼저 만들었다. 구 공급자2676c74의 실제 public ZIP 파싱 실패3건, 첫 수정88f의 전역ID 불일치4건을 소비자에서 재현했다. source 보안·지리 리뷰 지적은 provider에서 보완하고 소비자 wrapper는 추가하지 않는다.
- geo 선택 의존성을 명시하며 핀 생성기·프로토콜 검사도 extras를 읽게 했다. CI 설치와 로컬 unit 게이트는 pyproject의 단일 KNPS 요구사항을 사용한다. 연결 회귀42개가 통과했다.
- 운영/SSH/provider live 호출은 없고 공식 fixture 검증과 운영 재적재는 Claude Code에게 남긴다.

## 2026-11-06 — #1450 Option A: KNPS 보호지역 지정 allowlist

- 보호지역은 여행 관련 지정만 DESIG_ENG 표로 category를 준다(국립공원 중복 제외). 역지오 실패 행은 drop으로 센다.
- 위험지역(POINT)·선형시설(일반명)은 싣지 않고 schedule도 없다. 대피소는 knps-api#17.

## 2026-11-06 — #1450 KNPS dataset별 schedule·운영 1회 적재

- 원인: KNPS job은 dataset 5개를 묶는데 월간 schedule은 노브 dataset 하나만 돌렸다. 운영 갱신 요청으로 경계 21·화장실 325·야영장 36·문화자원 554건을 적재했다.
- 남은 넷(선형 이름 없음·위험 POINT·보호 해상 134 역지오 실패·대피소 ZIP)은 T-KNPS-DATA-GAPS.

## 2026-11-05 — #668 명령 조정 첫 구현·실패 우선 검증

- draft1451을 먼저 만들고 새 API 부재1실패, 기존PATCH 지문의 생략/명시NULL 충돌1실패를 확인했다.
- 동일actor/op/key 잠금에서 부재 claim+terminal409를 커밋하고 늦은 원래 요청을 막는다. 처리중 claim은 pending, 검증한 terminal은 completed로 반환한다. expected_actor는 인증 context와 비교만 하며 권한 선택에 쓰지 않는다.
- PATCH에만presence 보존 지문v2를 적용한다.437은기존v1을수정하지않고1/2를허용한다. 원래PATCH와조정 모두버전검사를먼저해과거v1을자동확정하지않는다. 다른명령v1은유지한다.
- API관련단위29·실제HTTP/auth/PostgreSQL 핵심1개·mypy247파일을통과했다. 초기라우팅정책미등록과바뀐helper테스트signature2건은보완했다. 아직경합/권한/과거지문/실패확장·OpenAPI·두최종리뷰·전체CI·머지는남아있다.
- 운영접근/배포/시험은없고최종prod는Claude Code담당이다.

## 2026-11-05 — Pinvi #668 명령 조정 계약 착수

- Pinvi#667/PR681(cb3b2f6)을 두 최종 리뷰·CI15성공·WSL 실제UI/RustFS 검증 후 병합했다. 다음은#668이며 최신Map mainad75031에서 시작한다.
- 단순 부재 조회는 늦은 옛 명령을 막지 못하므로 actor/operation/key 잠금 아래 영구 중단 결과와 기존 terminal/pending을 구분한다. Pinvi는 해제 후 새 승인 attempt 키를 써야 한다.
- 설계·검증 계획은 docs/execplan/pinvi-668-feature-command-reconciliation.md. draft먼저/자주push, WSL·두 독립 리뷰·CI 후 소유자Map부터 머지한다. 운영 접근·배포·시험은 없고 최종prod는Claude Code 담당이다.

## 2026-11-04 — #1444 묶음(#1445~#1448) 리뷰 보완

- f88b0759(운영)..dd0238c3를 두 독립 적대적 리뷰(데이터·적재 / API·계약)로 다시 봤다. 마이그레이션 추가 없음(head 436), ST_Transform 없음.
- 운영 원본 읽기 전용 모의: MCST 반려동물 20,396건·촬영지 8,803건이 미분류로 옮겨 간다. 행사 85건(KHA 장소 없음 82·종료일 없음 1, 축제 기간 없음 2)이 재적재 때 격리된다. 운영에 KHA fallback 키 행은 0건이다.
- 하회마을·고씨동굴은 운영 Map 검색(현행·신규 코드 모두)에서 이미 별칭 대상이 1위다. #1443의 4위 관측은 Map 순위로 재현되지 않았다.
- 고친 것: 회차 비교는 겹치지 않는 기간만 different(장소·종료일 차이는 검토), KHA fallback 종료일 변경 적재, MOIS 업태 필드의 무관 슬러그 해시 변동 제거, MCST 미도달 dataset 재시도 표기, 변경 장부·검색 테스트 대조군. 모두 수정 전 실패를 확인했다.
- journal이 220 KiB를 넘어 가장 오래된 2026-10-13 절 셋을 `archive/journal-2026-10f.md`로 바이트 그대로 옮겼다(tasks-rule §8).
- 남긴 것: 행사 품질 격리의 자동 해제는 소유자 결정(T-EVENT-QUARANTINE-RELEASE). admin OpenAPI digest가 바뀌었으므로 회전 전 PinVi 재vendor가 필요하다.

## 2026-11-04 — MCST 승인 복구·데이터셋별 적재 완료 보존 착수 (#1441/#1442)

- 최신 Pinvi #643 본문/댓글과 Map #1444를 다시 읽었다. 남은 Map #1441/#1442를 같은 소비자 PR로 처리한다.
- 공급자 python-mcst-api #20을 00a78df로 병합했다. 두 최종 전문 적대적 리뷰·전체 CI·WSL 오프라인 113개/14 subtest 및 공식 공개 골프장 키 없는 live가 통과했다. 실제 SDK가 541행·14열을 읽었고 원문 CSV는 커밋하지 않았다.
- Map은 공급자 핀을 실제 병합 커밋으로 올리고 기존 요청 계측 세션과 승인 경로의 호환성을 확인한다.
- 각 데이터셋 load가 커밋되면 기존 frozen membership과 인과적 seal로 즉시 완료한다. 늦은 다른 fetch/load 실패로 완료 결과를 되돌리지 않고 재시도는 이미 완료된 membership을 다시 적재하지 않는다.
- 전체 run 실패 사실은 보존하고 실제 성공/실패와 원인·진척을 데이터셋별로 표시한다. 다른 provider의 완료 정책이나 보호된 baseline을 바꾸지 않는다.
- 초안 PR을 먼저 만들고 실패 우선·실제 PG runtime·운영 화면의 로컬 UI·두 독립 전문 적대적 리뷰와 최종 CI 뒤 병합한다. 운영 접속·배포·검증은 하지 않는다.

## 2026-11-04 — 실제 분류 UI 검증·성능 하네스 파라미터 보완

- Map 5fcb015 → Pinvi 5048156 → Chromium 실제 UI 13항목을 통과했다. 공개 CSV의 실제 열·분류 tuple을 재현한 fixture로 호텔·카페·펜션·박물관, TYPE이 빈 촬영지의 미분류, 공백이 다른 국가유산 우선 순위와 행사 상세를 확인했다. 이름·주소·좌표는 테스트 값이며 원문 CSV를 저장소에 넣지 않았다.
- 배경 타일만 고정했고 제품 HTTP mock·dependency override는 없다. 모든 소유 서버·테스트 DB 컨테이너를 종료했다.
- 두 독립 전문 리뷰어가 제품 5fcb015에서 잔여 P0/P1/P2 없음으로 판정했다.
- 전체 단위 검사에서 성능 하네스의 새 alias_compact bind 누락 1개를 발견했다(나머지 3,642 통과·조건부 6 skip). 하네스 3곳을 보완하고 관련 17개·Ruff·main mypy 174파일을 통과했다. 전체 단위·PG·최종 CI를 이어간다.

## 2026-11-04 — 실제 MCST 분류 형식·공백 별칭 보완

- 공개 공식 CSV 5종을 다시 확인했다. 촬영지 원천은 CATEGORY가 없고 TYPE도 비어 있어 물리 업종을 확정할 수 없었다. 혼합 시설에서 불명·충돌은 미분류로 표시하고, 알려진 캠핑 전용 원천은 캠핑 분류를 유지한다. 이름·브랜드로 추정하지 않는다.
- 실제 반려동반여행/펜션·박물관·미술관·문예회관, 반려동물식당카페/카페·식당, 공원·전시/기념관 등 구조화된 값을 반영한다. 촬영 매체 FORMAT을 업종으로 사용하지 않는다. 기존 식별자·원문·색상은 유지한다.
- 별칭의 공백 차이로 국가유산이 테마 원천보다 뒤에 나오는 두 경우를 재현했다. 기존 GIN 후보에서 원래 이름 정규화 일치로 순위를 계산하며 목록·총계·페이지 이동을 함께 검증한다. 순위 의미 변경으로 cursor v3를 사용한다.
- 새 실제 형식 회귀는 수정 전 11개 단언 실패, 공백 별칭은 2개 실패였다. 수정 후 관련 단위 123개·PG 33개를 통과했다. 별도 PG에 비일치 1만 행을 넣은 실제 SQL의 기본 실행계획에서 GIN 사용·features 전체 스캔 없음, 실행 6.855ms를 확인했다(운영 성능 수치가 아니다).
- 이전 15b75fe/222e521 리뷰·전체 테스트로 이번 추가 변경을 승인하지 않는다. 새 독립 전문 적대적 리뷰 두 명·WSL 전체 관련 검사·실제 UI·최종 CI를 진행한다.
- Pinvi #643 최신 본문에 추가된 #663 상세 카드 지연도 후속 범위에 포함했다. 운영 접속·배포·검증은 하지 않는다.

## 2026-11-04 — Feature 품질 최종 WSL 검증

- 제품 15b75fe의 독립 전문 적대적 리뷰 A/B 모두 잔여 P0/P1/P2 없음이다.
- 최종 WSL 전체 PG 통합 1,617개 통과·조건부 14개 skip(743.78초), 전체 unit/lint 3,631개 통과·조건부 6개 skip, 관련 API 48개를 통과했다. API 카테고리 회귀의 이전 145개 고정값을 146개로 맞추고 행사 path·star 아이콘을 명시적으로 검증했다. 이 보완에는 제품 코드 변경이 없다.
- 실제 Map 15b75fe → Pinvi 80593b4 → Chromium UI 11항목을 통과했다. 별도 테스트 DB·정상 앱 lifespan·실제 HTTP를 사용했고 배경 raster 타일만 고정했다. 제품 API mock·dependency override는 없다. 행사 기간·장소 모달, 업종 라벨 5종, 격리 행 공개 제외를 확인하고 소유 fixture 서버·컨테이너를 종료했다.
- 관련 안전 결과는 소비자 PR #662의 `docs/reviews/pinvi-1439-event-local-live.json`에 보존한다. 최종 테스트/문서 커밋의 exact HEAD 리뷰와 CI 후 Map → Pinvi 순서로 병합한다. 운영 접속·배포·검증은 하지 않았다.

## 2026-11-04 — 적대적 리뷰의 회차 비교/관리자 보정 충돌 수정

- 두 최종 리뷰어가 KHA fallback guard의 effective 값 비교를 지적했다. 동일 원문이 관리자 보정 때문에 거부되거나, 반대로 보정값과 같은 다른 원천 회차가 통과할 수 있었다.
- 해당 source entity 소유의 provider base로 회차를 비교한다. 품질 격리는 기존대로 override가 반영된 표시값을 사용한다.
- b19d08b의 실제 guard 본문을 실행한 음성 대조에서 관리자 장소 보완 뒤 동일 원문·연락처만 변경한 원문 재수집, 관리자 종료일 보정이 다른 회차를 가리는 경우 등 3개 실패·정상 대조 1개를 확인했다. 수정 후 재투영·ACL·회차 실제 runtime PG 18개를 통과했다.
- 기존 전체 PG는 리뷰 보완을 위해 434개 통과·5개 조건부 skip 시점에 중단했다. 최종 소스로 전체 PG 및 두 exact HEAD 리뷰·CI를 다시 진행한다.

## 2026-11-04 — #1438/#1439 현재 원본 재투영·품질 전이 검증

- 현재 primary 원본의 명시적 7개 dataset만 분류·marker base를 재투영한다. 소유 원천이 다른 base·override·주소·상세·팔레트·퇴역 상태를 보존하고 두 번째 실행은 무변경이다.
- 실제 Dagster 역할의 base 조회 권한 누락을 재현했다. protected table의 DML 금지는 유지하고 필요한 5열 SELECT만 허용한다. 436 catalog marker 이전의 봉인 baseline은 그대로 두며 열 권한 drift를 reconcile에서 제거한다. 열 제한은 행 제한이 아니며 내부 공통 runtime에 적용된다.
- KHA fallback 동일 키의 다른 기간 유입을 실제 PG에서 재현·거부하고 rollback 뒤 기존 원문/head/base/표시 보존을 확인했다. 기존 행사 격리는 override가 반영된 표시 정보를 사용하고 자동 해제하지 않는다.
- 전체 unit/lint 3,631개·조건부 skip 6개, main 174개 파일 mypy, import-linter 4계약, CI 범위 Ruff 및 OpenAPI all-profile drift 검사를 통과했다. 분류/ACL/검색 PG 28개, 확장 재투영/ACL 거부·반복 reconcile PG 15개를 통과했다. 새 repair·merge guard를 끈 음성 대조는 5개 단언 실패·오류 0개였다.
- 별칭 전국 검색은 현행 migration 436 seed와 source 순위가 WSL 실제 PG에서 기대 순서를 만족했다. 운영 결과와의 차이는 최종 Claude Code 검증 시 alias seed·원천 분류·배포 revision을 확인해야 한다. 운영 접근·배포는 수행하지 않았다.
- 초안 #1447에서 두 독립 전문 적대적 최종 리뷰와 전체 PG/CI를 이어간다. Pinvi 정본 행사 필드 투영은 별도 소비자 PR에서 연결한다.

## 2026-11-04 — #1439 행사 분류·격리·회차 병합 경계

- 축제·행사 category `01090000`(star)를 추가하고 기존 legacy seed·자연키·팔레트를 유지한다. 신규 행사 필수 정보 누락은 원문을 보존해 격리한다.
- 단위 수정 전 8개 회차 오판 단언 실패·정상 2개 통과를 확인했고, 수정 후 관련 145개와 6개 소스 타입 검사를 통과했다. 실제 PG18 runtime 역할의 직접 병합·거부 시 상태/이력 불변·DB 후보 날짜 전파·기존 오케스트레이션 관련 16개도 통과했다.
- 동일 raw head의 기존 분류 재투영·기존 행사 품질 전이·별칭 검색 검증은 초안 #1447에서 이어간다. 아직 완료나 병합을 선언하지 않는다.

## 2026-11-04 — #1438 구조화된 시설 분류 회귀

- MCST 혼합 시설 4종·캠핑 CSV의 CATEGORY1/2/3로 업종을 결정하며, 불명·충돌은 기존 fallback을 유지한다. 이름·브랜드로 업종을 추정하지 않는다.
- MOIS는 기존 승격 업종의 명시적 업태만 세분화하고 세 분류 근거를 새 원본에 보존한다. legacy ID seed·자연키·팔레트는 유지하며, payload hash 사전 계산과 실제 변환을 일치시킨다.
- 수정 전 MCST 9개·MOIS 11개 단언 실패를 재현했다. 원본 동일 head의 기존 행 재투영, 행사 정합성, 검색 실제 PG 검증은 같은 초안 #1447에서 이어간다.
- 운영 접근·배포는 하지 않는다. 완료 표시는 두 독립 적대적 리뷰·WSL 및 CI 후에만 갱신한다.

## 2026-11-03 — PinVi #643 관리자 조회 연계 (#648/#651)

## 2026-11-04 — #1438·#1439·#1443 Feature 분류·행사·검색 순위 묶음 착수

- Pinvi #643 최신 본문과 댓글의 Map #1444 연결을 다시 읽고, #1441·#1442·#1443도 전체 범위에 반영했다. #1443은 분류·행사와 같은 Feature 품질 묶음에 포함하며 CSV 파싱·데이터셋 완료 상태(#1441·#1442)는 후속 별도 묶음으로 진행한다.
- 구조화된 원천 분류를 provider 범위에서 정규화하고 기존 UUID·자연키·legacy seed를 보존한다. 행사 필수 정보·회차 정합성과 동명 다른 회차 오병합 방지, 별칭·전국 검색 순위를 실패 우선 fixture로 검증한다.
- Pinvi의 정본 행사 필드 투영은 소비자 연결에서 확인한다. 운영 8건이 실제 중복인지 판정하거나 임의 병합하지 않는다. 동일 원본 재투영·두 번 실행의 멱등성과 override·퇴역 상태 보존도 검증한다.
- 초안 PR 우선·수시 원격 커밋·독립 전문 적대적 리뷰 두 명·WSL 및 CI 후 순차 일반 병합한다. 운영 접속·배포·검증은 사용자 지시에 따라 수행하지 않는다.


## 2026-11-04 — Pinvi #643 과거 날씨 요약·오래된 정보 표시 묶음 착수

- Geo 주소 검색 PR #622의 CI·두 독립 리뷰·WSL 검증과 병합을 마쳤다. 다음은 Map #1440과 Pinvi #642의 날씨 품질 묶음이다.
- Map은 가까운 요약 후보에 표본이 없을 때 유효한 다음 후보를 가리는 경로를 수정한다. 기존 부분별 상태·선택 출처·신선도·전날 비교를 보존하고 실제 Valkey 왕복을 검증한다.
- Pinvi의 카드 stale 전파·배지는 소비자 저장소에서 처리한다. 사용자 지시에 따라 초안 PR을 먼저 만들고 두 독립 적대적 리뷰, WSL 검증과 CI 후 병합하며 운영 접속·배포·검증은 하지 않는다.


**작업**: 한국어 관리자 Feature 검색에 이름·주소·ID만 검색하는 명시적 범위를 추가하고,
중복 검토 목록을 기존 ops read principal로 조회할 명시적 읽기 경계를 제공한다.
기존 operator 쓰기 권한을 public/service token으로 확장하지 않는다.
**검증**: 기존 희소 질의는 원천 48건을 한 번 읽었다. 제한 범위는 비일치 후보의 원천 접근 0과 현재 원천·기본 전체 검색·페이지 이동을 WSL PG18로 검증한다. 2026-11-04 WSL 관련 API·권한·PG18 회귀 154개와 main/API mypy, CI 범위 ruff, import-linter 4계약을 통과했다. 전체 unit/lint 3,587개 통과(조건부 6개 건너뜀). 리뷰의 OpenAPI token+scope AND 조건 누락을 보완하고 관련 계약·인증 53개를 통과했다. 독립 리뷰어 두 명의 최종 소스 검토에 차단 사항이 없다. 생성 frontend 타입 누락을 CI에서 발견해 재생성하고 drift 검사를 통과했다. 전체 API 1,596개·coverage 77.90%(기준 70%)를 통과했다.
전체 통합 CI는 1,589개 통과·14개 건너뜀·신규 테스트 1개 실패였다. 선행 잠금 테스트가 커밋한 주소 행과의
간섭을 WSL에서 같은 순서로 재현했다. 테스트별 고유 이름·주소로 격리한 뒤 관련 11개를 통과했다.
리뷰의 음성 대조가 행별 이름으로 인한 동률 cursor 검증 약화를 찾아, 페이지 테스트 세 행은 같은 전용 이름을 유지한다.
API 구현·스펙은 보존하며 전체 통합 검증·최종 CI를 다시 진행한다.
운영 배포·테스트는 사용자 지시대로 Claude Code가 최종 담당한다.
**이전**: PinVi PR #659(d6e0ddc)로 관리자 제안 큐 세 항목을 머지했다.
**다음**: Map 읽기 변경 머지 후 PinVi 소비자 경로·오류 표시를 연결하고 남은 데이터·지도·날씨·알림을 진행한다.

## 2026-11-03 — weather_state 503 페이지 재시도

weather 503(읽기 경합 `EXPORT_TEMPORARILY_UNAVAILABLE`·이전 `EXPORT_NOT_READY`·code 없음)은 그 페이지만 같은
cursor로 최대 3번 다시 묻는다(5·10·20초, `Retry-After` 우선; 대기+가장 긴 요청이 run 상한 −60초 안, 순회당 대기 합
60초, run 재시도 예산 공유). 소진하면 종전처럼 step 재시도.

## 2026-11-02 — feature 검색 순위·별칭(alembic 436)·주차장 표시 이름

PinVi live e2e(봉화·영주·안동)에서 "하회마을"이 서울 음식점 셋, "고씨동굴"이 고씨네·단양 고수동굴, "도산서원"이
주차장·미디어 명소를 국가유산보다 먼저 냈다(prod 읽기 전용 실측). 소유자 "권장안 대로".

- 순위 `rank`: 일치 단계(별칭 → 이름이 검색어를 품음 → 유사도) → bbox 안 → 분류 그룹 → 이름 일치(첫 낱말 지역명을
  뗀 일치 포함 — "안동 도산서원") → Tier 1만 있는 코드 뒤. q와 함께 온 bbox는 가중(필터 아님). cursor v2(keyset에
  rank, 상한 21911). 별칭 팔은 trigram GIN `=`로 BitmapOr(prod 35 ms).
- 분류 그룹은 Tier 1 표 + 교통 목적지 접두 예외: 관광 0 → 숙박·온천·기차역·지하철역·휴게소·공항 1 → 식음 2 →
  그 밖 3. 리뷰 2인이 "서울역" 역이 "롯데리아 서울역점"보다 뒤인 것을 짚었고, 3번째 리뷰가 정류장 전체·의료까지
  올린 것은 소유자 순서를 넘는다고 짚어 기차·지하철역·휴게소·공항만 남겼다. 관광 부분 일치는 여전히 앞이고, 의료는
  맨 뒤라 "서울대병원점" 음식점이 "서울대병원"보다 앞선다(소유자 판단 대상).
- 이름 비교 키는 보이는 이름(주차장 표시 이름)에서, NFC·Python `isspace` 공백 집합 제거·소문자로 만든다. SQL은
  `translate`로 같은 집합을 지운다(PG `\s`는 NBSP를 놓친다). 양쪽 다 소문자 뒤 다시 NFC(자모·결합 부호). 436 CHECK도
  같은 집합. 지역명 tail은 앞뒤 공백을 걷고 집합 어느 문자에서든 자른다. tier-2 하네스 bind 누락도 고쳤다.
- 436 `feature.feature_search_aliases`: 정규화 검색어 → Feature **이름**(id는 환경·재적재마다 달라 migration이 못 심는다).
- 주차장 표시 이름은 응답 모델 before-validator — 저장 값·ETag·OpenAPI 불변. backlog: T-HERITAGE-ENRICH·T-DEDUP-MEDIA-HERITAGE.
- 이 절을 더하자 journal이 220 KiB를 넘어 가장 오래된 2026-10-13 두 절을 `archive/journal-2026-10e.md`(머리말 포함
  21,540 B)로 옮겼다(§8, 본문 그대로·상대 링크 없음). resume도 같은 이유로 가장 오래된 네 절을
  `archive/resume-2026-09b.md`로 옮겼다.

## 2026-11-02 — weather_state 하한·W5 상한 실측 조정

단기 하한 1,000곳·90%→250곳·65%, W5 상한 900→2,700초. 근거는 resume 같은 날.

## 2026-10-28 — run-status sensor tick 실패로 cursor 엿새 정지(#1434)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — ADR-117: SH 스냅샷·스칼라 정책 경로 퇴역(alembic 435)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — T-PG18-CI: prod coord_5179 PROJ 7→9 drift 검사 clean

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — T-PG18-CI: CI·compose를 PG18 공용 digest 한 lane으로(ADR-118, #1431)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — #1426의 main 병합 뒤 resume 크기 경계 복구

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — #1426의 main 충돌·기존 통합 회귀 호환 교정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — 현재 배포·원51복구·공개 UI13 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — typed stale 복구 코드의 최종 CI·후보UI·정상 머지

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — Codex PR 통합 리뷰의 비잠금 항목(WI-5~11)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — alpine 관찰자 cold-array codec 경계 최소 교정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 실제 제품16·후보UI14 뒤 head oracle 빈줄1개 교정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — typed reset 실제 제품16 통과, CI 계약 교정 중

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 첫 제품 PG14PASS/2FAIL 보존과 canonical head 교정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — typed reset scope 권한을3열로 제한하고 통합17개 수집

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — typed bound reset 통합 source16개와 순수142개

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 새 typed reset의 순수 경계138개 통과

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 실제 stale→rollback→live READY reset 거부 재현과 첫 제품 경계

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — bound 재현의 strict Geo 입력 연결만 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — bound snapshot 첫 재현은 baseline setup timeout으로 미도달

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — bound snapshot stale 뒤 live lease 재계획 경계 조사

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — Common 최신 제품 공식 pair 배포·공개 UI13 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 동시 쓰기 제한 시험 두 PR의 최종 CI·정상 병합

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — snapshot OS worker pair 최종 CI·정상 병합 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 공유 Feature의 동일 artifact 재계획 실제 PG 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 공유 Feature 첫 실제 PG의 xid8 관찰 bind 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 공유 Feature의 동일 artifact 재계획 시험 착수

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — snapshot OS worker pair의 제한 실제 PG 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — Codex PR 통합 리뷰의 비잠금 항목(WI-5~11)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — Codex PR 리뷰 정리: tracking 장부는 L만, 단건 writer는 regime 진입(434)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — kor-travel-common 최신(`aa232ad5`) 반영: 브랜치 `chore/common-latest-map`

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 제한 단위의 최종 CI·배포·공개 UI 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — byte quota 최종 CI 실패와 문자열 선검사 비용 보강

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest 중복 검증 제거의 PG·후보 UI 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest 최종 두 PostGIS 시간초과 보강 중

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest reader 제품 PG 통과와 로그아웃 이동 경합 보강

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest reader 조회에 한정한 JIT 비활성화 초안

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 최종 CI 실패와 최소 수정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 추가 물리 경합·후보 UI 수용과 CI 잔여 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 설계 누락 경합·계측 시험 보강

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 quota/GC·복구 재검증 통과

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 실제215·두 writer 검증

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — 431 reader 배포·공개 UI·원 일정 복원 완료

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 선택 A 구현 첫 checkpoint

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 · Rest431 최종 CI와 main 반영 정산

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 · Rest431 최종 제품과 격리 후보 추가 인수

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 · Map/PinVi 배포·공개 읽기·일정 복원 정산

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 단일 export 영속 재관측 설계 초안

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 CI의 unordered presence 비교 결함 수정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 관리 직접SQL 음성 실제 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 실제215 fit와 최종 공식 golden

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 원64 비용 계량과 A1 source

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 통합 source와 실제 lab 준비

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 430 복구 후보 실제 UI와 CI 비교 기준 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Rest431 reader 미호출 source

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 휴게소431 명시 profile 설계·계량 경계

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 430 복구 후보 실제 UI와 CI 비교 기준 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 휴게소431 명시 profile 설계·계량 경계

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 · expired reset applying holder의 정본 fixture 회귀

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 · 전용 읽기 동결 소비 계약 정렬

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 · Feature read/create 중복 자격 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 · PinVi admin Feature 전용 읽기

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 snapshot 잔여 fixture 실제 확인

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — PostGIS 추적 fixture 정리

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 430 복구 후보 실제 UI와 CI 비교 기준 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 430 전체 PG gate 첫 원인 수정 준비

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 공항 snapshot 원자적 후처리 구현 중

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 · cancellation 원 backend cleanup 후보

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 API task 취소·pool 경계 시험 소스

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 비활성 strict SH guard429 owned 검증

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 인덱스 metadata 반사 표현식과 실제 검사 정산

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — capture 권한 인벤토리 CI 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 제한된 현재집합 capture(428, 구현 중)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 공항427 key/index 보강

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 공항427 SQL/decoder source

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 공항 reader Geo 계약(427, 부분)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 가격 추이 본문 읽기 Low 3건(#1365 리뷰 후속)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 현행 기록 크기 경계 재분리

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 공개 provider patch P-first(426)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Provider base UPDATE-first 후보(425, 미수용)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — tracking P→L prefix(424, 부분)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Place projection 예산 검사 추출

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 첫 동시 수집 후보 설계(미구현)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — EX context 단일 조회(423)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — scalar batch 내부 실행 단계 분리

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 전체 snapshot 동시 쓰기·복구 설계(미구현)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Heritage bounded evidence reader 입력 계약(부분)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — SH 운영 후보 크기 실측

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Geo stamp SQL writer 권한 경계(421)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 실제 SH 수집 연결의 설계 초안(A4)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — main 419 보존과 EX 적재 연결 420 재검증

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 제한 primary place의 명시 EX 전체 적재(A3 checkpoint)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR-114 결정 7 퇴역 1단계(T-STATE-03): 브랜치 `feat/adr114-retire-pg-transport`

- 소비자 확인(읽기 전용 실측): prod Map transport 출처 Feature 26,293건(주유소 place 11,820·유가 11,822·휴게소 215·휴게소 유가
  219·돌발 2,202·공항 15), 병합·curation·override·POI 링크 0. Valkey 다섯 데이터셋 `loaded`·fresh. PinVi main `ff64b65`은 교통
  레이어를 Map service REST로만 읽지만 일반 in-bounds 기본 kind(`place·event·notice·price`)·검색·근처가 PG transport를 여전히
  돌려받는다(교통 레이어와 중복, 장소 이름 검색은 PG에만 있다). PinVi DB의 Map feature 참조는 전체 0행. C7 운영 게이트가 공항
  job을 안전 대상으로 쓴다.
- 그래서 세 단계로 나눴다(ADR-114 "결정 7 이행"): ① 유가 둘·돌발 하나의 PG 적재 코드 제거 + migration `419`(operation 종류
  불문 끔, Feature `system` 퇴역 = `retired`·`suppressed` + 재활성화 막는 lifecycle override, dataset·lineage·가격 fact는 남김,
  queued/running·공유 primary·기존 lifecycle override preflight) → ② 장소 셋 → ③ 물리 삭제. 장소 적재는 계속 돈다.
- API 표면 변화 없음(OpenAPI 재생성·PinVi 재vendor 불필요). Codex 수집 fence·shadow 원장 코드는 읽기만 했다(퇴역 프로시저는
  advisory lock을 잡지 않는다).
- 검사(n150 일회용 python:3.13): ruff·mypy --strict(279)·lint-imports 초록, unit+lint+api 4,817 passed·29 failed(기준선 환경
  실패 그대로 — docker runtime 23·sealed tree 2·tick window 3·smoke settings 1), 통합(transport·retire·notice·price·mois·
  tvn34c/35·phase2·catalog 등 -k) 290 passed(1 error는 컨테이너에 docker CLI 없음). 첫 실행에서 revision id 40자(>32)와 사후
  조건 SQL의 없는 열(`context`)을 잡아 고쳤다.
- 적대 리뷰 2회(HIGH 1·MED 2·LOW 3·운영 1) 반영: (F1) prod 409→411(현 417)이 한 트랜잭션이면 410 FK 잠금을 퇴역 내내 쥔다 →
  `alembic_version` xmin으로 같은 트랜잭션을 감지해 퇴역 대상이 있을 때 거부, runbook A·B. (F2) 대상 scope 행 `FOR UPDATE`(FK
  KEY SHARE와 충돌) 뒤 preflight, operation 먼저 끔, 사후 in-flight 재확인. (F3) scope 잠금 5초·DDL 1초·퇴역 statement_timeout 0.
  (F4) 공유 출처 검사 역할 무관. (F5) 대상 셋 고정·옛 provider 잔여 fail closed. (F6) 상태 문맥 GUC 정리·docstring. 문서 drift 넷.
- 재리뷰(fix-delta): F2의 scope 행 `FOR UPDATE`는 경주를 닫지 못한다 — BEFORE INSERT 활성 가드가 plain SELECT로 `is_enabled`를
  읽고 FK 대기는 그 뒤라, 411 도중 들어온 INSERT가 켜진 값을 보고 통과해 commit 뒤 성공한다. member 표 둘을 `SHARE`로 잠그도록
  바꿨다(INSERT가 문장 시작에서 기다리고 commit 뒤 가드가 거부). 퇴역 루프 lock_timeout 60초. 두 연결 순서 강제 통합 검사(도중
  INSERT 거부) 추가. runbook B1 upsert 예시·B5 사후 member 0 확인·A 건너뜀 crash-loop 복구.
- main 병합(#1379·#1383·#1385 — ADR-115 revision 411~416): 이 migration을 `417_retire_pg_transport_values`(down 416)로 다시
  번호 매겼다. 415부터 `transition_feature_state`가 scoped write 프로토콜 gate를 배타로 잡으므로 417은 그 gate를 member 표 잠금보다
  **먼저** 잡는다(교착 회피, 돌고 있는 쓰기가 있으면 30초에 실패). runbook A는 head 416 pair, 3a 큐 sensor 정지 명령(공용 daemon)·
  417 창 새 run 실패/503 안내. 경주 검사는 inserter의 미허가 RowExclusiveLock이 `ops.import_job_datasets`에 있음을 잰다.
- main 병합 뒤 journal이 220 KiB를 넘어(228,797 bytes) 가장 오래된 2026-10-01 기록을
  아카이브로 옮겼다(tasks-rule §8 — 섹션 본문 바이트 보존, 상대 링크 없음). diff3 base 마커 줄 셋도 지웠다. (main이 2026-09-30분을 `journal-2026-09h.md`, 가장 오래된 2026-10-01 한 절을 `journal-2026-10a.md`로 따로 옮겨 그것을 따랐고, 남은 2026-10-01 두 절을 `journal-2026-10b.md`로 옮겼다.)
- 두 번째 main 병합(#1386·#1387 — ADR-115 `417_protocol_ex_reentry`): 이 migration을 `418_retire_pg_transport_values`(down
  417)로 다시 번호 매겼다(당시 runbook A는 head 417 pair).
- 세 번째 main 병합(#1388 — ADR-115 `418_creation_protocol`): 이 migration을 `419_retire_pg_transport_values`(down 418)로 다시
  번호 매겼다. runbook A는 head 418 pair.

## 2026-10-24 — 한 sealed attempt의 scalar 원자 batch(A2)

- 같은 dataset의 기존 primary place 여러 개를 한 TX/finish1회로 적용하는 별도 entry를 추가했다. snapshot seal·실제 collector 배선·same-dataset 병렬 수용은 아니다.
- 최종146 PASS(새PG20/unit10+부모116)·lint377(기존6skip)/Ruff/mypy2/import4 통과, 두 코드리뷰·정확CI·실UI는 미완이다. 총1MiB/manifest8192·협력적30s/입력독점소유 계약과 한계는 [A2 보고서](reports/2026-10-24-native-scalar-batch.md)에 있다. 기본OFF/seed0/운영0.

## 2026-10-24 — 국가유산 native 적격성 선행 계약(A1, #1390)

- 안정 composite ID의 본체 이름 presence와 저장 typed projection 재정규화·지원 외 불변 진단을 추가했다. eligible은 DB 적용 승인이 아니며 collector/Geo/whole-TX seal·정책은 바꾸지 않는다.
- 격리된 고정SDK public 모델·Map fetcher service fixture 포함98 PASS, native 예산 후속075 합집합116 PASS(실PG 포함), mypy3/import4/Ruff 통과. 정확CI·독립2리뷰는 진행 중이며 PG/실UI/운영 수용으로 세지 않는다. [범위와 실패](reports/2026-10-24-heritage-native-eligibility.md).
- 기존 EX 진입은 별도 #1389이며 부모 합성 시 양쪽 기록을 보존한다. 기본OFF/seed0/운영0, 내구 artifact/full bundle/실제 collector 배선은 후속이다.

- EX 부모 합성으로 journal225349B가 되어 가장 오래된 2026-10-01 한 절5764B를 [아카이브](archive/journal-2026-10a.md)로 원문 이동했다. 원문 SHA/부모 합집합은 A1 보고서에 기록했다.

## 2026-10-24 — 제한 scalar의 같은 의미 EX 실행 진입

- SH와 같은 source/head→후보→winner→receipt를 기존 protocol EX·curation 전역 fence 아래 수행하는 별도 내부 entry를 추가했다. legacy loader fallback·collector 배선·정책 활성화는 아니다.
- 실제PG/기존native/artifact16 PASS(28.51초): SH/EX 결과 동등·정확 gate 대기·실패/취소 rollback·55P03 복구·완료 replay0DML·mode 대체 거부. 적대리뷰 P2의 legacy장기hint를 소비해 짧은상한을 유지했다. 최종두리뷰·정확CI·최신UI는 후속이다. [범위와 증거](reports/2026-10-24-scalar-exclusive-semantic-entry.md).
- 선행 #1386·#1387은 각각 두리뷰·정확CI5개·실UI5/18(별도HTTP2) 뒤 main에 머지됐다. 기본OFF/seed0/운영0, 전체수집전환·후속전파는 미완이다.

## 2026-10-24 — 생성 SQL의 protocol-first 진입과 승인 복구(418)

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — protocol EX 재진입 비용 개선(417)

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 큐레이션 import의 protocol-first 진입

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — field override 진입 보강(416)

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 파일 레지스트리의 백업 링크 복구

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — state/lifecycle SQL first-entry 폐포(415)

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 통합 전체 CI의 시험 격리 보완(#1379)

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 구현 합집합 수용(#1379)

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — M05 중복 후보·판정의 protocol-first 보강(414)

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 제한 native scalar 비용 실측(#1376)

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 구현과 전체 수용 범위 구분

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 SQL 직접 진입 413 실제 검증

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 기존 SQL 직접 호출의 잠금 순서 보강 착수

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 제한 native scalar 실제 DML 중첩

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 제한 scalar winner·정합성 검증(#1373)

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 운영·관리 다중 reader 후속

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 순수 다중 조회의 snapshot 고정

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 범위 커널·기존 writer fence 통합

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 실제 동시 쓰기 구현 착수

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR-114 2단계 재리뷰 Low·main 재기반(#1365 뒤): 브랜치 `feat/adr114-valkey-weather`

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR-114 2단계 리뷰 반영(#1367): 브랜치 `feat/adr114-valkey-weather`

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR-114 2단계: weather 현재·예보·세 구간 요약 Valkey·service REST: 브랜치 `feat/adr114-valkey-weather`

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 T-CWRITE-01: 격리 쓰기 기준선 runner

[완전한 원문](archive/journal-2026-10i.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 공용 지도 작업면 채택 후보

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 가격 추이 프록시 transport T4 정렬(T-STATE-01-T4): 브랜치 `feat/transport-fuel-price-history-t4`

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — geo 재시도에 ReadError·WriteError 추가: 브랜치 `fix/geo-retry-readerror`

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 shadow 실제 수집 연결: 명시 scope·MCST 이름

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 T-CWRITE-02: 불변 정책과 shadow 후보 기반

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — ADR115 선행: 같은 transaction fence 재진입 SQL 절감

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 수집 CI 선행 Next 보안 게이트 복구

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 멈춤 진단 오탐 정정: 브랜치 `fix/stall-watchdog-progress`

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 여섯 프로젝트 npm 보안·버전 정합

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-23 — MCST 6시간 상한·멈춤: 브랜치 `fix/mcst-geo-stall`

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-23 — geo 부하 줄이기 0단계(ADR-116, T-GEOLOAD-00): 브랜치 `feat/skip-geocode-unchanged`

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-23 — ADR-114 1단계: transport 현재 상태 Valkey·service REST: 브랜치 `feat/adr114-valkey-transport`

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-23 — ADR-115 실제 동시 쓰기 설계·작업 원장

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-22 — T-LOAD-LOCK-WAIT 2안(ADR-113): 스트리밍 snapshot은 다 받은 뒤 짧게 쓴다: 브랜치 `fix/short-curation-lock-hold`

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-22 — T-LOAD-LOCK-WAIT 1안: 적재가 fence를 길게 기다린다: 브랜치 `fix/load-curation-lock-wait`

[완전한 원문](archive/journal-2026-10h.md)은 크기 상한에 따라 분리했다.

## 2026-10-22 — prod 첫 적재 실패 2건: 브랜치 `fix/highway-evidence-krheritage-address`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-21 — T-RECONCILE-RETRY 하위 단계 2: reconcile sensor 결정 1~7(ADR-112 accepted): 브랜치 `feat/reconcile-retry-alert-close`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-20 — T-RECONCILE-RETRY 하위 단계 1: 완결을 sensor 밖으로(ADR-112 결정 0-1): 브랜치 `feat/finalize-out-of-sensor`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-20 — weather 잔재 정리 2건(T-WX-NOTICE-CLOSE·T-WX-VNEXT-FREEZE): 브랜치 `chore/wx-notice-close-vnext-freeze`

- 소유자 지시("4 진행"). `close_notice_features`(client·repo)와 그 함수만 쓰던 통합 테스트 1건을 지웠다. 공유 헬퍼
  `_persist_notice_lineage_events`·`_reconcile_persisted_notice_scope`는 event-bundle 경로가 계속 쓴다.
- vNext 동결 계약은 재동결하지 않고 rev 300 당시 기록으로 둔다(ADR-105 후속 한 줄, freeze 테스트 docstring 범위 절).

## 2026-10-20 — T-RECONCILE-RETRY 설계안 ADR-112(doc-only): 브랜치 `docs/t-reconcile-retry`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-20 — T-TEST-PLANNER-INDEX 원장 이관(doc-only)

- PR #1336(`e937b38d`, main 반영 완료)이 통합 planner flake 고정(REINDEX in test txn + 25k draft rows + lock_timeout 30s,
  20/20 n150 연속 통과)을 실었으나 `tasks.md`→`tasks-done.md` 이관이 그 PR을 못 탔다. 이번 doc-only PR이 그 이관을
  싣는다 — 코드 변경 없음, acceptance §T-TEST-PLANNER-INDEX는 그대로 둔다.

## 2026-10-19 — production MapLibre worker asset 누락 복구 (PR #1340)

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-19 MOIS 장애 격리 수용

PR1340: 실제 SYN DROP/native retry 기본값으로 FAILURE308.365초(<1440), 복구500행·재수집HTTP0 PASS. REST/prefetch/loader173검사와 namespace4검사 PASS. 운영 전체job/실DB 검증은 아니며 daemonOFF 유지. [범위와 한계](reports/2026-10-19-mois-network-drill.md).

## 2026-10-19 — MOIS 연결 실패 조기 전파

- 500행 typed 오류 선조회 지연을 재현하고 실행중 task 취소·회수를 보강했다. 관련89회귀 PASS이며 실제 네트워크/native retry 수용은 준비 중이다. [근거](reports/2026-10-19-mois-network-drill.md).

## 2026-10-19 — T-MAP-02 현재 설치 세대 수용

- T-MAP-02 — timeout 구현523d98cc가 포함된 e937b38d의 API/CS 설치3파일 hash와
  현재 image/CID/StartedAt을 확인했다. 과거 첫 generation UUID는 미회수이며
  현재 설치세대 묶음으로 수용한다. 불필요 재배포·운영 변경0.
  Map API/CS·PinVi API 실제 기존 키 reverse3/3 PASS, PinVi CS 직접 역할은 제외.
  [범위와 증거](reports/2026-10-19-installed-timeout-acceptance.md).
  전원단절 drill·자동 실행·운영 변경토큰 전량 수용은 별도다.

## 2026-10-18 — Geo 기준점 실제 UI 수용

- 실제 관리자 UI 8/8 PASS: 최초 baseline plan 1/상세 items 0, 동일 토큰 감지에서 같은 기준점 유지.
- 실행 중 세 이미지의 revision label e937b38d와 DB head 409를 관찰했다.
- daemon OFF·현재 run/물리 worker 0·컨테이너 lifecycle 유지. 실제 변경 토큰 replay/resume·자동 실행은 미검증.
- [검증 기록](reports/2026-10-18-geo-baseline-live.md). 문서만 변경하며 사용자 지시로 CI를 생략한다.

## 2026-10-17 — T-MAP-02 timeout 설명 정합(문서만): 브랜치 docs/track2-http-timeout-contract-20261017

- tasks.md의 낡은 connect 2 s를 실제 기본 4 s로 정정했다. read·write·pool 기본은 geo 10 s·transport 30 s다
  (settings.py, geocoding.geo_http_timeout, dagster/provider_fetchers.transport_http_timeout).
- transport의 요청 재시도는 upstream_retry.DEFAULT_UPSTREAM_ATTEMPTS=2·
  PROVIDER_BOUNDARY_BASE_DELAY_SECONDS=15.0 및 run 예산을 따르며, 이 숫자들은 요청 전체 deadline이 아니다.
- 구현 커밋 523d98ccf36f90aaead9ac33ab353a0839293621(#1325)은 최신 main
  e937b38d176cfeb759daca629395f51c1a6a4d5f(#1336)의 조상이다. 제품 중복 패치는 하지 않았다.
- 실제 배포·장애 drill은 수행하지 않았다. T-MAP-02는 acceptance의 첫 prod 배포 generation 근거를 확인할 때까지 열린다.

## 2026-10-17 — 통합 planner flake 결정화(T-TEST-PLANNER-INDEX): 브랜치 `fix/t-test-planner-index`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — geo 릴리스 재지오코딩 구현 반영 문서(T-GR-07, doc-only): 브랜치 `docs/t-gr-07-geo-release-docs`

- **무엇.** ADR-109 accepted(구현 기록 표·열린 결정 13개 결론), runbook `geo-release-regeocode.md` 신규, 정본 문서의
  "ADR-109 proposed, 미구현" 표식 제거, T-GR-01~06·08 `tasks-done.md` 이관(T-GR-07은 머지가 조건).
- **문서가 코드와 달랐던 자리.** `address-geocoding.md` §5의 센서 위치(`sensors.py` → `geo_release_sensor.py`)·커서(없음 —
  기준선은 계획 표 행)·`kor_travel_geo_client` resource(만들지 않음 — `open_geo_client`)·run_key 다섯째 칸(`provider_dataset_id`
  → `position`)·상수 이름, ADR-108의 "릴리스 센서가 MOIS 이어 달리기를 대신한다"(MOIS는 이제 센서가 내지 않는다).
  geo ADR-069는 그 저장소에서 2026-10-13 accepted(GitHub 원문 확인).

## 2026-10-16 — admin UI geo 릴리스 화면(T-GR-06, ADR-109 결정 8): 브랜치 `feat/t-gr-06-geo-releases-ui`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — records resource replay 모드(T-GR-08, ADR-109 결정 7): 브랜치 `feat/t-gr-08-replay-mode`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — geo 릴리스 센서(T-GR-05, ADR-109 결정 5): 브랜치 `feat/t-gr-05-geo-release-sensor`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — geo 릴리스 계획 표·계획 함수·admin API(T-GR-04, ADR-109 결정 5·8): 브랜치 `feat/t-gr-04-geo-release-plan`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — 적재 경로의 geo 재해석(T-GR-03, ADR-109 결정 4·6): 브랜치 `feat/t-gr-03-stale-stamps`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — `docker-buildx.sh`의 `$!` 경주(고아 tar writer): 브랜치 `fix/buildx-archive-pid-race`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-16 — run-scoped geo 현재 토큰 resource·`geo_applied` 배선(T-GR-02): 브랜치 `feat/t-gr-02-geo-dataset-resource`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-15 — 지오코딩 스탬프 표·geo 데이터셋 토큰(T-GR-01, ADR-109 결정 1~3): 브랜치 `feat/t-gr-01-geocode-stamps`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-15 — geo·transport client connect timeout 분리(T-MAP-02, ADR-110 결정 3): 브랜치 `feat/t-map-02-connect-timeout`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-15 — ADR-110 사실 갱신: geo·weather·transport가 실제로 odroid로 갔다: 브랜치 `docs/adr-110-odroid-facts`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-15 — journal·tasks-done 다음 경계 분리(T-GR-00-LEDGER): 브랜치 `docs/t-gr-00-ledger`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-14 — D2 fixture `Alembic revision confirmation mismatch`: 확인 키를 repin이 API 이미지 head에서 유도: 브랜치 `fix/d2-fixture-alembic-head`

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

## 2026-10-14 — chain16 D1 판정이 ANSI 커서 제어 때문에 11/11 통과를 실패로 읽음: 브랜치 `fix/chain16-d1-ansi`

- 증상: 배포(Map 4931f9c0 + PinVi 2fa1c166) 뒤 chain16 F(D1)가 `11 passed (32.2s)`를 냈는데 `!! D1: 목록 11건이 전부 passed가 아니다`로 중단.
- 원인: Playwright line reporter가 진행 줄을 `ESC[1A ESC[2K`로 덮어써 마지막 줄이 `^[[1A^[[2K  11 passed`가 되고, #1318의 판정 `grep -qE "^ *$D1EXPECT passed"`가 줄머리 앵커에서 실패.
- 수정: `scripts/n150/chain16.sh` D1 출력에서 ANSI CSI 시퀀스를 `sed`로 걷어낸 뒤 판정. 판정 규칙(목록 수 == passed, skipped/did not run도 실패)은 그대로.

## 2026-10-14 — chain16 C단계(C7 executor 이미지) 실패 원인 규명 + `file:` 의존성 COPY 게이트: 브랜치 `fix/c7-executor-vendor-tgz` (PR #1320)

[완전한 원문](archive/journal-2026-10g.md)은 크기 상한에 따라 분리했다.

[과거 기록 아카이브로](#과거-기록-아카이브)
