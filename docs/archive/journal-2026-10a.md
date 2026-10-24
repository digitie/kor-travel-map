# journal 아카이브 — 2026-10-01

> live `docs/journal.md`에서 분리한 과거 기록(docs/tasks-rule.md §8). 읽기 전용 이력이다.

## 2026-10-01 — Map Dagster의 KMA 적재 경로 제거(ADR-104): 브랜치 `feat/remove-map-kma-dagster`

소유자 결정: KMA는 kor-travel-weather가 소유하고, Map은 KMA data.go.kr 오퍼레이션을 다시는 부르지 않는다
(data.go.kr 키를 weather와 함께 쓰고 오퍼레이션당 일일 한도가 빠듯하다).

- **끄던 것이 능력을 남기고 있었다.** `DISABLED_FEATURE_LOAD_SCHEDULES`는 schedule을 만들지 않고 큐의 targeted
  요청만 건너뛰었다. Dagster UI launch·백필, `provider_dataset` 큐 요청, C7의 `external_system:c7-e2e` 요청은
  그대로 KMA를 불렀고, 카탈로그는 KMA refresh operation 5개를 enabled로 들고 있었다.
- **지운 것.** `dagster/kma_weather.py`(asset 5), KMA job·schedule, resource 셋, `fetch_kma_weather_alerts`, 큐
  runner spec·handler binding 5, KMA settings 넷, KMA 대상 좌표 조회(client 4·repo 4), asset 라벨·API cron 힌트,
  `providers.kma`의 Dagster 설정 파서 둘. `DISABLED_FEATURE_LOAD_SCHEDULES`에서 KMA 이름이 빠졌다(AirKorea 등 때문에
  목록은 남는다).
- **남긴 것.** `providers.kma` 변환·정체성 계약(이미 적재된 KMA feature 읽기, `/ops/datasets` fixture preview),
  카탈로그 행·scope·dataset(`is_active`), preview operation, 공개/운영 KMA 특보 이력 API.
- **DB.** `401_retire_map_kma_refresh` — provider `python-kma-api`의 `refresh`·`feature_load`를 `is_enabled=false`.
  이 저장소 관례(`_UPGRADE_STATEMENTS`)를 따르고 receipt head CHECK에 `400`·`401`을 더했다(graph 전체를 받아야 한다는
  lint 계약; `head-schema.sql` 동기화). 400 스쿼시 뒤 첫 child migration이라, 300~313 체인에 맞춰 박힌 migration lint
  하한 다섯(롤 전환 ≥5, 문장 ≥100 등)이 대상이 없는데 빨갰다 — 하한을 "소스 텍스트에 보이는 것을 추출도 전부 본다"로
  옮겼다.
- **재도입 방지.** `test_map_dagster_has_no_weather.py`가 시드 카탈로그에서 KMA operation key를 provider로 유도해
  Definitions(job·schedule·sensor·asset)·handler registry·큐 runner를 보고, 효과 축으로 Map 런타임 소스의 KMA client
  import와 KMA data.go.kr 경로(`1360000`)를 본다. DB 축은 `test_head_enables_no_kma_load_operation`.
  **각 검사를 한 번씩 빨갛게 만들었다**: main 소스에 대고 돌리면 job·asset·launch·소스 넷이 각각 KMA job 5개 /
  `kma_weather_alert_records` / registry의 KMA key 5개 / `import kma` 위치로 빨갛다. 하한 검사는 KMA 행을 뺀 시드로
  빨갛다. 처음 판의 sensor 축은 `RunStatusSensorDefinition`에 `job_names`가 없어 **효과가 아니라 AttributeError로**
  빨갰다 — 그 빨강은 아무것도 증명하지 않으므로 target의 `job_name`을 읽게 고치고 main에서 다시 KMA job 이름으로
  빨개지는 것을 확인했다.
- **prod 읽기 전용 실측(09:00Z 전후).** 공유 plane `dagster_shared`의 Map instigator는 sensor 10 + schedule 1
  (`current_weather_summary_refresh_minutely_schedule`), 옛 `kor_travel_map_dagster`도 같은 11개 — KMA instigator·
  KMA run 0. `dagster_shared`의 KMA schedule 5·run 63(전부 FAILURE)은 weather location 것이다. Map DB(rev `400`)는 KMA
  refresh 5·preview 4가 enabled, KMA feature·sync state·멤버십 가진 import job·요청 0. 그래서 배포가 바꾸는 것은
  Dagster 정의 목록(KMA job 5 소멸, instigator 변화 없음)과 카탈로그의 enabled 5행뿐이다.
- **남긴 일.** C7 러너 가족(`run-c7-prod-live-e2e.sh`, `ops-c7-*` spec)은 KMA 위에 서 있다 — KMA write spec은 이제
  요청 단계에서 거부되고, 러너는 schedule allowlist의 KMA schedule이 2026-09-09부터 없어 이미 돌 수 없었다. 배포 게이트
  (chain16 D1·D2)는 이 러너를 쓰지 않는다. `python-kma-api` 의존 핀, Manager compose의 `KOR_TRAVEL_MAP_KMA_WEATHER_*`
  env도 후속.

## 2026-10-01 — flip 전 drain 절차 정정(공유 Dagster plane cutover 완료): 브랜치 `docs/shared-plane-drain`

Map은 2026-10-01 05:54Z cutover로 05:58Z부터 공유 plane에서 돈다. C7은 06:02Z GREEN이었다.

- **runbook이 틀린 drain을 권했다.** #1290이 `docs/runbooks/docker-app.md`에 "writer drain으로 새 run을 막고 run이
  terminal이 될 때까지 기다린다"고 적었다. 코드(`writer_drain_service.py`)는 그렇게 하지 않는다. Map의 RUNNING
  instigator를 **전부** 멈추므로 operation을 종결 반영할 reconcile sensor와 run-status sensor도 멈추고,
  `min(15초, dagster_termination_timeout_seconds/2)` grace 뒤 남은 run을 `SAFE_TERMINATE`로 끊는다. 그래서 "active
  operation 0건"을 만들 수 없다.
- **실제로 쓴 절차를 적었다.** 창 전 in-flight load가 스스로 끝나게 두고 330초(reconcile lag 300 + 주기 30) 기다리며
  새 load·요청을 시작하지 않는다 → `ops.import_jobs`의 `queued`/`running`·`dagster_run_id` 있음·비격리·
  `provider_feature_load_run`/`feature_update_request` 건수 0을 게이트로 본다 → queue는 닫지 않는다
  (`DISABLED_FEATURE_LOAD_SCHEDULES` 불필요, run 없는 요청은 새 queue sensor가 집는다). Manager cutover script는 게이트를
  precheck와 fence·run-cancel 뒤 switch 전에 두 번 보는데, 두 번째는 snapshot이고 cancel된 `feature_update_request`
  run은 어느 sensor도 종결시키지 않아 손으로 정리한다. 정본은 Manager topology §7과 `scripts/dagster-shared-cutover.sh`.
- **writer drain의 자리.** 원래 용도(Manager cache-target diagnostic/cutover의 writer fence 직전 producer 비우기,
  ADR-082)로는 유효하다고 적었다. pool 이름 변경 배포 전제의 drain 설명("run이 끝나기를 기다린다")도 "grace 뒤 끊는다"로
  고쳤다. 다른 Map 문서에 flip용으로 writer drain을 권한 곳은 없었다(CHANGELOG·journal의 기존 언급은 pool 이름 변경용).

## 2026-10-01 — Map이 공유 Dagster plane에 오르기 전의 차단 항목: 브랜치 `feat/dagster-shared-map-prep`

리뷰가 Map flip 전에 고칠 것 셋을 짚었다. 셋 다 오늘의 Map 전용 instance에서도 같은 결과여야 먼저 머지·배포할 수 있다.

- **reconcile sensor가 모든 tenant의 run을 읽었다.** `_latest_dagster_watermark`·`_dagster_run_page`가 filter 없이
  `get_run_records()`를 불렀다. 공유 instance에서는 weather·PinVi·geo run을 watermark로 삼고, cursor가 없는 첫 tick은
  남의 run 때문에 "non-empty storage" 오류로 멈춘다. 새 `kortravelmap.dagster.run_scope.map_runs_filter()`가
  `dagster/code_location=<Map location>` tag를 붙이고(location 이름은 #1289와 같은 `docker/workspace.yaml` 정본에 결박),
  reconcile 두 조회와 coalescing schedule 둘(feature-load, 매분 weather summary)이 그것만 쓴다. 남의 run만 있는
  공유 instance의 첫 tick은 Map 범위가 비어 null cursor로 시작한다(fake와 실제 ephemeral run storage 두 테스트).
  Dagster는 remote origin이 있는 run에만 이 tag를 단다 — n150 읽기 전용 실측으로 Map instance의 run 1,825건 전부가
  `kortravelmap.dagster.definitions`를 달고 있었다. 배포된 location 이름이 다르면 reconcile은 0건을 조용히 보지 않고
  오류로 멈춘다(`context.code_location_origin` 대조).
- **run-status sensor 일곱이 `monitor_all_code_locations=True`였다.** 기본값으로 되돌렸다 — Dagster가 run의 remote
  origin을 sensor의 location·repository와 대조한다. Map job은 전부 한 location이라 오늘은 평가 대상이 같다.
- **검사.** 설치된 `DagsterInstance`에서 `RunsFilter`를 받는 조회(`get_runs`·`get_run_records`·`get_run_ids`·
  `get_runs_count`·`get_run_partition_data`)를 유도해, 호출이 `filters=map_runs_filter(…)`인지 AST로 본다.
  location으로 좁힐 수 없는 event·asset·backfill·run tag 조회는 금지 목록이다. `monitor_all_*`도 막는다. 옛 모양
  여섯이 각각 빨갛게 나오는지 detector를 테스트한다. sensor 테스트의 fake run storage는 이제 tag filter를 적용한다 —
  무시하던 fake에서는 좁히지 않은 조회도 초록이었다.
- **API가 공개 Dagster URL을 호출했다.** `KOR_TRAVEL_MAP_API_DAGSTER_GRAPHQL_URL`은 prod에서
  `https://map-dagster…/graphql`이고 API가 그것을 호출·보고했다(C7이 그 sha256을 대조). flip 뒤 공개 URL은 Basic Auth
  gateway다. 새 `KOR_TRAVEL_MAP_API_DAGSTER_INTERNAL_GRAPHQL_URL`이 호출 URL이고(없거나 빈 값이면 공개 URL — 오늘과
  같다), 공개 URL은 보고·링크에만 쓴다. allowlist는 호출 URL에만 걸고 공개 URL은 모양만 본다. 응답 DTO는
  `DagsterUrls.public_graphql_url`, 호출은 `graphql_url`이다. overview·dagster-runs·schedules에서 실제 POST된 URL과
  응답의 URL을 대조하는 효과 테스트가 있다.
- **D2가 없는 service를 가리켰다.** `.d2-live.env`의 `E2E_C7_PINVI_DAGSTER_SERVICE=pinvi-dagster`는 손으로 적은
  값이라 PinVi cutover 뒤 preflight가 cardinality에서 멈췄다. `repin.sh` 3단계가 이제 `ktdctl targets list --json`의
  `dagster.control_plane`과 `runtime_services`에서 유도한다 — 공유면 그 프로젝트의 Dagster runtime service 하나
  (code-server), 전용이면 적힌 값을 확인만 한다. Map flip 때 web·daemon 두 키는 Map code-server를 함께 가리키고,
  preflight는 이 두 role에만 service 공유를 허용한다. 공개 URL·hash는 caller attestation이라 유도하지 않고
  `scripts/n150/README.md`에 flip 값을 적었다.
- **C7 client의 Basic Auth.** 선택 키 `E2E_DAGSTER_BASIC_AUTH_FILE`(소유자 전용, `user:password` 한 줄)을 러너가
  검증하고 executor에 read-only bind로만 건넨다. Dagster에 직접 POST하는 세 자리(queue sensor controller, admin
  helper, 최종 복원 검증)가 그 파일이 있을 때만 `Authorization: Basic`을 붙인다.
- **적대 리뷰 후속(같은 브랜치).**
  - MED-1 첫 부팅 경주: 공유 instance 첫 부팅에서 매분 weather summary schedule이나 queue sensor가 reconcile 첫
    tick보다 먼저 Map run을 만들면 "non-empty storage" 규칙이 영구히 발화했다. 이제 cursor가 없고 Map run이
    `FEATURE_OPERATION_RECONCILE_PAGE_SIZE`(200) 이하면 null cursor로 처음부터 훑는다(반영은 멱등). 그보다 많으면
    (n150 전용 instance 1,825건) 여전히 명시 cursor를 요구한다. flip 전 drain 요구(옛 instance에만 run이 있는 active
    operation을 먼저 끝낸다)는 `docs/runbooks/docker-app.md`에 적었다.
  - L2: location 불일치는 `MapRunScopeMismatch`를 던져 tick이 FAILURE로 보인다(다른 예외처럼 SKIP으로 삼키지 않는다).
  - L3: schedule context에는 code location이 없다. coalescing schedule 둘은 location 상수 대신 Map job이 스스로 다는
    tag(`kor_travel_map.operation_key`·`kor_travel_map.job_kind`)로 좁힌다(`map_owned_runs_filter`, n150 weather
    summary run 1,000/1,000이 tag를 단다). lint는 두 helper만 받는다.
  - L4·L5·L7: `repin.sh`는 토폴로지를 stdin으로 받고, 유도한 service 이름을 `^[a-z0-9][a-z0-9._-]*$`로 확인하고,
    source 대조 전에 물려받은 키를 지운다. Map plane을 `E2E_C7_MAP_DAGSTER_CONTROL_PLANE`(own|shared)로 적고,
    preflight는 `shared`일 때만 web·daemon 공유를 허용한다(없으면 own — 엄격).
- 통합 테스트(`test_canonical_provider_operations`의 fake context 한 줄)는 n150에서 돌리지 않았다(PostGIS 컨테이너를
  prod host에 띄우지 않는다) — CI가 본다.
