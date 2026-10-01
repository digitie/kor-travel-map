# journal.md — 작업 일지 (역시간순)

## 2026-10-01 — Map에서 날씨 feature·기상특보 notice 기능 삭제(ADR-105): 같은 브랜치 `feat/remove-map-kma-dagster`

ADR-104(KMA Dagster 경로 제거) 작업 중 소유자 결정이 넓어졌다: weather kind 기능 전부와 날씨 출처 notice(KMA 특보)만
지우고, UI에서도 지우고, 데이터와 관련 스키마도 지운다. 정의(kind·DTO·enum·`make_feature_id`·DB kind 값)는 남긴다.
산림청 산사태 예보와 KREX 교통공지는 날씨 출처가 아니라 남긴다. **배포 전 백업은 소유자가 명시적으로 면제했고, 삭제는
되돌릴 수 없다.** 정기 백업은 이 결정과 무관하다.

- **prod 읽기 전용 실측(12:00Z 전후).** `feature.features` 0행(모든 kind), weather fact·summary·notice 0,
  `source_entities`·`source_records` 0, `ops.current_summary_runs` weather 2,875(매분 schedule의 receipt)·price 5,
  weather·KMA 카탈로그 dataset 12·operation 18·scope 13. notice provider별 행도 0이라 지워지는 notice도 남는 notice도
  현재는 행이 없다. 그래서 402가 prod에서 실제로 지우는 것은 summary run 2,875행과 카탈로그 상태뿐이다.
- **나눈 작업.** Dagster(W1), 라이브러리·API·OpenAPI(W2), migration 402·스키마 산출물(W4), C7/D1/D2(W5), UI(W3), 교차
  정리(W6)를 파일 소유를 갈라 병렬로 했다. 정본 결정은 `WEATHER-REMOVAL-SPEC`(작업 메모)에 두고 모두 같은 정체성 규칙을
  썼다: weather = 카탈로그 `capabilities.produces ∋ "weather"`, 날씨 notice = notice이면서 provider `python-kma-api`.
- **402가 하는 일과 근거**는 migration docstring과 ADR-105에 있다. 지운 스키마 넷은 `head-schema.sql` 전수 검색으로
  weather 전용임을 확인했다. 공유 표 `ops.current_summary_runs`는 남기고 CHECK만 `price`로 좁혔다.
- **게이트에서 잡은 것.** (1) API guard가 `app.routes`로 경로를 셌는데 n150에서는 sub-app mount 때문에 `/metrics`
  하나만 보여 **빈 집합에서 빨갰다** — main에서의 빨강도 그 이유였을 수 있어, OpenAPI `paths`로 바꾸고 main에서 다시
  잰다. (2) squash 경계 검사가 root(`400`)만 허용해 401·402를 겨누는 통합 테스트를 retired 대상으로 봤다 — active
  graph의 revision을 허용하게 고쳤다. (3) PinVi rollout pending receipt의 OpenAPI sha를 재핀했다(`latest_weather` 소멸 —
  PinVi vendor는 다음 짝에서).
- **C7.** KMA 위에 서 있던 러너를 KMA 없이 돌게 했다: read-auth, schedule-write(allowlist
  `feature_place_krairport_airports_monthly_schedule` — fetcher가 번들 정적 데이터만 읽어 upstream 호출 0), POI
  `@c7-causal`. n150 `.d2-live.env`의 `E2E_C7_SCHEDULE`을 그 값으로 바꿔야 러너가 시작한다. D2는 price feature 하나만
  심는다. 둘 다 prod에서만 돌 수 있어 이번에 실행하지 못했다.
- **n150 게이트(브랜치 소스를 PYTHONPATH로, main과 대조).** unit+lint 3,026 passed / 14 failed — 14건은 main에서도
  같은 환경 실패(`test_docker_dagster_runtime` 13: node 의존, `test_c7_prod_live_runner_process` INT-130 1). API 1,217
  passed, Dagster 624 passed, ruff·mypy --strict 3패키지·lint-imports·migration graph `--check` 통과. frontend
  type-check 통과, vitest 380/381(실패 1은 main과 같은 maplibre worker 파일 부재), lint·build는 n150 node_modules가
  main에서도 깨져 판정 불가(W3가 로컬 eslint 통과를 확인). 통합 테스트는 n150 디스크 대기로 testcontainers PostGIS가
  `pg_ctl` shutdown checkpoint에서 죽어(교체된 이유) 하네스에서만 PGDATA를 tmpfs로 두고 돌렸다: 영향 파일 30개
  307 passed, `head-schema.sql`은 `KTM_WRITE_HEAD_SCHEMA=1` 재생성 결과와 바이트 동일. 통합 전량(glibc 이미지)은
  1,110 passed / 3 failed / 19 errors — 19 errors는 bootstrap 묶음의 알려진 n150 환경 실패, docker effect 2건은 main에서도
  같이 실패, `test_tvn34_public_projection_spine`의 EXPLAIN 1건은 단독 재실행에서 통과(공유 DB 통계 순서 의존).
- **빨강 실측.** 브랜치의 guard를 main 소스에 대고 돌렸다: Dagster 5/7 빨강(나머지 둘은 카탈로그 하한·남는 notice
  양성 검사), API 3/5 빨강(나머지 둘은 축 유도 하한·남는 notice preview 양성 검사), UI 4/6 빨강(W3, HEAD 파일 복원),
  DB는 `test_weather_removal_migration.py`가 401에서 19개 제거 검사가 0이 아님을 먼저 단언한다.
- **배포 영향.** 공유 plane Map location의 instigator 11개 중 `current_weather_summary_refresh_minutely_schedule`
  (RUNNING) 하나가 사라지고 sensor 10은 남는다. 옛 Map 전용 instance(`kor_travel_map_dagster`)의 같은 schedule 상태 행도
  쓰이지 않게 된다. 402의 `DROP INDEX`가 `feature.features`에 ACCESS EXCLUSIVE를 잡으므로 매분 schedule과 겹치지 않게
  배포한다(새 코드에는 그 schedule이 없으니 code server 교체 뒤 migration이면 겹칠 일이 없다).

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

## 2026-09-30 — 공유 Dagster plane 준비의 적대 리뷰 반영: 브랜치 `feat/dagster-shared-stage0`

- **run 상세 범위 판정이 한 번도 발화하지 않았다(HIGH).** 소속을 `Run.tags`의 `.dagster/repository`로 읽었는데,
  GraphQL은 hidden `.dagster/*` tag를 걸러 낸다(`GrapheneRun.resolve_tags`의 `TagType.HIDDEN`). 그래서 "다른
  location → not_found" 갈래는 죽은 코드였고, 테스트는 오지 않는 tag를 가짜로 넣어 초록이었다. n150 12702에서 run
  하나를 조회해 보니 `tags`에 `.dagster/*`가 없었고, `repositoryOrigin`은 `__repository__` /
  `kortravelmap.dagster.definitions`로 왔다. 이제 run 상세는 `repositoryOrigin`을 묻고 selector와 비교한다. origin이
  없으면 not_found다. fixture도 실제 모양으로 고쳤다(hidden tag 없음, origin 있음). 응답 tag를 읽는 다른 자리도
  감사했다. MOIS precheck(coverage tag), dataset schedule(operation key), C7 live helper(request tag)는 모두 보이는
  tag만 읽는다. run 완주 게이트는 SQL `run_tags`를 직접 읽으므로 hidden tag가 있다. `RunsFilter.tags`도 storage를 보므로
  tag filter 자체는 옳다(같은 실측에서 Map 값은 run을 돌려주고 틀린 값은 0건).
- **CI가 constraints 없이 설치했다(MED).** 네 workflow의 저장소 설치 17곳이 모두 `-c docker/constraints-dagster.txt`를
  읽는다. `test_image_python_constraints.py`가 workflow를 훑어 이를 결박한다. 헤더의 "정확한 버전"도 고쳤다. 이
  파일은 나열한 패키지만 고정하고, 전체 freeze가 아니다.
- **범위 검사가 옛 drain 쿼리를 통과시켰다(MED).** 종전 검사는 `filter:` 글자만 봤다. 그래서
  `filter: {statuses: [...]}`처럼 repository tag 없는 리터럴 filter도 통과했다. 이제 `runsOrError` 선택은
  `filter: $runsFilter`여야 하고, 같은 operation이 `$runsFilter: RunsFilter!`와 `repositoryOrError(repositorySelector:
  $repositorySelector)`를 싣고 있어야 한다. bare `runsOrError {`도 잡는다. 훑는 범위를 API·Dagster·core·scripts
  (`lib`·`n150`, `.sh`)·admin UI `.ts`로 넓혔다. 옛 모양 다섯 개가 각각 빨갛게 나오는지 detector 자체를 테스트한다.
- **run 조회의 location 오타가 조용했다(LOW).** runs 패널, MOIS precheck, writer drain의 run 조회가 같은 요청에
  `repositoryOrError`를 싣는다. `Repository`가 아니면 각각 오류 응답, `DAGSTER_QUERY_FAILED`,
  `DAGSTER_PROTOCOL`로 멈춘다. 이전에는 빈 목록이 "run 없음"과 구분되지 않았다. drain이면 아무것도 기다리지 않고
  통과할 수 있었다. drain의 끝나지 않은 상태 집합에는 `STARTING`을 더했다.
- **pool 이름 변경 배포(MED).** 옛 이름으로 도는 run이 있으면 새 이름 run이 한 번 겹친다. OpiNet과 KREX notice에는
  advisory lock이 있지만 `kor_travel_geo` pool의 23개 job에는 없다. 그래서 배포 전제를 두었다. pool job의
  QUEUED·STARTING·STARTED run이 0건이거나, writer drain 아래에서 배포해야 한다. 이 전제를 runbook·CHANGELOG·resume
  체크리스트에 적었다. 검사 명령은 pool job 목록을 live `assetNodes { pools jobNames }`에서 유도한다. n150 실측은
  pool job 27개(`__ASSET_JOB` 포함), 끝나지 않은 run 0건이었다. 이번 한 번만 필요한 전제라 `scripts/n150`에 스크립트로
  두지는 않았다.

## 2026-09-29 — 공유 Dagster plane의 Map 쪽 준비(stage 0 + 3.1): 브랜치 `feat/dagster-shared-stage0`

계획은 `F:\dev\handoff\dagster-shared-plan.md`(Manager 쪽 정본은 `docs/platform-topology.md` §7). 배포 변경은 없다 —
Map은 나중에 Manager pinned pair와 chain17로 나간다.

- **stage 0 — 이미지 버전 고정.** Map은 lockfile 없이 `pip install ".[providers]"`로 설치해 왔고, `dagster>=1.9,<2`는
  하한일 뿐이라 실제 버전은 빌드한 날 PyPI가 준 것이었다. 공유 host(webserver/daemon)보다 높은 dagster가 code-server에
  끼어드는 것은 Dagster 호환 정책 밖이다. `docker/constraints-dagster.txt`에 목표 집합을 `==`로 적고(dagster family
  1.13.24, dagster-postgres 0.29.24, grpcio 1.84.0, grpcio-health-checking 1.81.1, protobuf 6.33.6, pydantic 2.13.5 /
  core 2.46.5 / settings 2.15.0, SQLAlchemy 2.0.54, psycopg 3.3.6(+binary, pool 3.3.3), psycopg2-binary 2.9.13, asyncpg
  0.31.0) API·Dagster Dockerfile이 둘 다 `-c`로 읽는다. 값은 n150 live 이미지(`3d0411dd`)와 같다. n150에서
  `uv pip compile`(Python 3.12, 두 이미지의 설치 인자 그대로)로 해소 가능함을 확인했다. Python은 기존 digest 핀
  3.12.13 그대로다(3.12.14로의 digest bump는 계획상 선택이라 하지 않았다). `test_image_python_constraints.py`가 핀
  형식·누락·family 일치·pyproject 범위 포함·두 Dockerfile의 `-c`와 COPY 순서를 본다.
- **3.1 — code location 범위 조회.** API의 Dagster GraphQL이 전부 `repositoriesOrError`(전 repository)와 filter 없는
  `runsOrError`였다. 공유 webserver에서는 다른 프로젝트 것이 섞이고, **writer drain은 다른 프로젝트의 schedule/sensor를
  멈추고 run을 끊는다.** 이제 `DagsterUrls`가 settings의 repository selector를 들고 다니고, 조회는
  `repositoryOrError(repositorySelector)`와 `runsOrError(filter: {tags: [.dagster/repository=__repository__@<loc>]})`다
  (요약·pipeline overview/runs/schedules·schedule 명령·dataset schedule index·MOIS precheck·writer drain). run 상세는
  다른 code location의 run을 `not_found`로 답한다. 프로젝트별 webserver에서도 selector가 유일한 repository를 가리키므로
  오늘 배포와 호환된다. admin UI 운영 홈의 Dagster 링크는 `/locations/kortravelmap.dagster.definitions`(Dagster UI는
  `__repository__`면 경로에 location만 쓴다 — live 번들에서 확인), C7 live helper 둘과 run 완주 게이트도 같은 selector로
  좁혔다. `test_dagster_code_location_is_one_name.py`가 이름을 쓰는 자리(settings 기본값·`.env.example`·UI 상수·C7
  helper·게이트)를 `docker/workspace.yaml`과 대조하고, API src·scripts에 `repositoriesOrError`와 filter 없는
  `runsOrError`가 돌아오지 못하게 한다.
- **pool 접두사.** pool 이름공간과 `default_limit`은 instance 전역이다. `opinet_api`·`krex_notice_snapshot`·
  `kor_travel_geo`(geo 프로젝트와 겹칠 이름)를 `kor_travel_map.` 접두사로 바꿨다. 배포 직후 옛 이름 슬롯을 잡은 run과 새
  이름 run이 한 번 겹칠 수 있다.
- **D4 확인(읽기 전용, n150 12:40Z 무렵).** live GraphQL의 schedule 34·sensor 10 전부 live 상태 = 코드 `default_status`,
  metadata DB `jobs` 11행 전부 `DECLARED_IN_CODE`. DB에만 켜진 instigator가 없어 코드 변경은 없다.
- 남긴 것: 7개 run-status sensor가 `monitor_all_code_locations=True`라 공유 daemon에서는 다른 프로젝트 run 이벤트도
  평가한다. `kor_travel_map.operation_key` tag가 없으면 `panel_only`로 끝나 정확성 문제는 없고 비용만 든다 — 끌지는
  C3e 설계 결정이라 별도로 판단한다. 공유 plane의 env 이름(`KOR_TRAVEL_DAGSTER_SHARED_PG_URL`)·URL 재지정은 cutover
  때 Manager rendering 몫이다.

## 2026-09-29 — Map DB를 공용 PostgreSQL로 옮겼다

소유자가 위험을 받아들이고(결정 C) Map 전용 인스턴스(12700)를 공용 인스턴스(11000)로 합치기로 했다. superuser는 새로
만들지 않았다(S1): Map 부트스트랩이 superuser를 요구하는 것은 새 DB를 만들 때 한 번뿐이라, Manager가 그 one-shot에만
공용 admin 자격증명을 secret 파일로 넣는다(n150 Compose v5.2.0에서 env·inspect·argv에 드러나지 않음을 먼저 실험으로 확인).
Map 전용 튜닝(1GB 버퍼, 모든 DB prewarm 등)은 소유자 지시로 공용 인스턴스 전체에 적용했다.

순서가 곧 안전장치였다. 먼저 Manager M1(펜스: 인스턴스 admin 소유 DB는 절대 drop하지 않는다, rebuild는 PostgreSQL 서비스를
재생성하지 않는다, Map DB는 PUBLIC CONNECT를 닫고 연결 상한을 건다)을 넣고 12700에서 새 pair로 검증했다. 공용 튜닝(MT)과
이전(M2)은 창 안에서만 머지·설치했다 — main에 미설치로 두면 누군가의 설치가 공용 재생성을 무장시키기 때문이다.

창은 스크립트로 돌았다. 공용 재생성은 CHECKPOINT·`stop --time 300`·설정 read-back·20분 tenant 게이트로 감쌌고, 이전은
writer fence → 12700에서 감사 dump → 12700 clean stop(보존) → M2 설치·`.env` 편집(G 잠금) → `--adopt-live-databases`
rebuild → V1~V9로 갔다. 공용 인스턴스의 반복 재시작 원인(고아가 된 헬스체크 프로세스를 PID 1 postmaster가 입양)은
전날 다른 세션의 Manager #433이 이미 막아 두었다.

## 2026-09-29 — MP 적대 리뷰 2차: compose 경고로 새던 비밀 조각, 탐지기 다듬기, fixture 대상 대조

- **MED(둘, 같은 결함)**: `repin.sh` 3단계와 `chain16.sh` E 단계가 Map API를 `docker compose … ps`로
  찾으면서 stderr를 흘렸다. compose는 `ps`에서도 project `.env`를 해석한다. `/opt/.env`의 따옴표 없는 값에
  든 `$`의 꼬리를 변수 이름으로 읽어 `The "<꼬리>" variable is not set` 경고를 찍는데, n150에서 그 꼬리는
  UI 관리자 비밀번호 hash의 조각이었다. chain16은 repin 출력을 `2>&1 | tail -12`로 옮기므로 한 사이클에
  여덟 줄이 운영 로그(`/root/chain17-<tag>.log`)에 남는다. 옛 `docker ps --filter label=…`은 compose를
  읽지 않았으니 MP가 새로 연 경로다. 두 조회에 D2 러너와 같은 `2>/dev/null`을 붙였다(실패는 `|| die`·64-hex
  검사가 잡는다). 새 검사 `test_compose_calls_keep_compose_warnings_out_of_the_output`은 `scripts/n150`의
  모든 compose 호출이 stderr를 버리거나(`2>/dev/null`) 잡는지(`capture_output=True`) 본다 — 세 스크립트의
  redirect·capture를 하나씩 지우면 각각 빨갛다.
  - Map 밖(소유자 몫): `/opt/.env`의 `*_UI_ADMIN_PASSWORD_HASH` 넷을 작은따옴표로 감싸거나 `$$`로 바꾼다
    (CLI compose 모델이 값을 망가뜨린다). 조각이 리뷰 transcript에 한 번 찍혔으므로 Map UI 관리자 비밀번호
    교체도 권한다.
- **탐지기(LOW 둘)**: 넓던 규칙 둘(`host:port/`, `-p`/`--port`)이 `curl …:12701/healthz`·`ssh -p 22`를
  잡고, 공용 instance로 가는 모양 다섯(`docker compose … exec`, `docker container exec`, 키워드
  `host=`/`port=`, `PGHOST`/`PGPORT`, `postgres:` 서버 이미지)은 놓쳤다. 규칙을 좁혀 바꿨다: DSN 문자열
  (`postgres(ql)(+drv)://`), libpq 연결 키워드·env, PostgreSQL 서버 이미지. exec는 compose·container 형태도
  보고, 값 있는 flag(`-e X=1`)를 target으로 읽지 않는다. exec 허용은 이름 목록이 아니라 **유도**다 — 같은
  스크립트가 API 조회 결과로만 대입한 변수(`API="$(docker compose … ps …)"`, `api = apis[0]`)에만 허용하고,
  다른 대입이 하나라도 있으면 빠진다. 리뷰가 실측한 모양을 두 자기 검사 목록에 넣었다.
- **판정 도구 읽기 전용(LOW)**: `adjudicate.sh` COUNT_PROGRAM의 "아무것도 쓰지 못한다"를 검사로 바꿨다. 같은
  wrapper에 INSERT를 넣어 돌리면 `read-only transaction`으로 거부되고 행이 남지 않는다. `readonly=True`를
  빼거나 ROLLBACK까지 COMMIT으로 바꾸면 빨갛다.
- **다섯째 잔여물 줄(LOW, 원래부터)**: fixture의 provider dataset(`admin-live-{run_id}-{kind}`)을 센다. source
  계보와 refresh policy가 모두 그 아래 달리므로, dataset 쪽만 남은 BLOCKED lane이 네 줄 0으로 `clear-blocked`
  되지 않는다. 양성 대조는 fixture의 `_dataset_key`로 심고 다른 run·운영 dataset을 이웃으로 둔다.
- **fixture 대상 대조(LOW)**: D2 러너 `validate_runtime`이 lock·state 전에 fixture DSN의 host·port·DB·query를
  API 컨테이너의 `KOR_TRAVEL_MAP_PG_DSN`과 대조한다(사용자·비밀번호는 다를 수 있다). 확인 키 셋(DB 이름·login·
  head)은 다른 instance의 같은 이름 사본에서도 맞으므로, 이동·롤백 직후 repin 없이 러너만 돌 때 API가 읽지
  않는 사본을 고치는 것을 막는다. 값은 출력하지 않는다.
- 작은 것: bootstrap 모듈의 `create_labels` import를 skip guard 밖으로(없으면 19건이 조용히 skip이 아니라
  실패), `_postgis_image.py` 주석은 MT 설치 전의 정본이 실행 중인 공용 컨테이너의 `.Image`임을 적었다.
- n150 대상 실행(`cfb1eb45` + 이 변경): 대상 unit 141 passed, ruff 초록. count 모듈 alpine·glibc 각 **4 passed**,
  bootstrap 모듈 alpine·glibc 각 **19 passed**(client 잔여 0). 변이는 모두 빨갛다 — compose redirect·capture
  제거 셋, adjudicate에 넣은 공용 instance 모양 여덟(compose exec 둘, container exec, 이름만 맞춘 `api=` 셸·
  python 재대입, 키워드 connect, `PGPORT`, `postgres:` 이미지), 러너 대조 무력화·호출 제거·사용자까지 비교,
  count의 readonly 제거·COMMIT·dataset 0·run 무시, labels import 이름 변경(19 errors, skip 아님).
- 전량: lint 검사 하나(`test_adjudicate_only_clears_a_lane_that_is_really_stopped`)가 줄 수 확인을 `4`로 박아
  빨개졌다. 리터럴 대신 COUNT_PROGRAM이 실제로 세는 줄 수와 확인이 같은지 보게 했다(확인을 4로 낮추거나 여섯째 줄을
  더하면 빨갛다). n150 `b91a41a6`: ruff 초록, `mypy --strict` 일곱 대상 초록, lint-imports 4 kept, unit+lint
  **3079 passed / 15 skipped / 14 failed** — 14건 모두 main(`90b1e5e0`)에서 같은 node로 실패한다(node_modules
  없는 체크아웃의 frontend 검증 13, `test_lifecycle_preserves_signal_exit_status[INT-130]`). GitHub
  `postgis-only.yml`(run 36456439859, `66a1cb3a`): glibc **1163 passed / 12 skipped**, alpine 첫 시도는
  `test_public_partial_indexes_have_exact_state_predicate_and_explain_proof` 1건(planner 선택, 알려진 flake — n150
  단독 3회씩 이 브랜치·main 모두 passed), 실패 job 재실행 **1157 passed / 18 skipped**.

## 2026-09-28 — Map DB를 공용 instance로 옮기기 전에 Map 쪽에서 할 일(MP): glibc 정렬, 두 번째 CI lane, 유도된 DB 접근

소유자가 Map의 두 DB를 공용 instance `kor-travel-shared-postgres`로 옮기기로 결정했다(결정 C, ADR-103 ·
Manager ADR-53). 이동 자체는 Manager의 창에서 하고, 이 PR은 Map 쪽 준비다. 창 전에 새 pair로 핀해야 한다.

- **collation**: 공용 instance는 glibc 이미지(PG 16.9·PostGIS 3.5.2, `en_US.utf8`)다. alpine(musl)에서는 default
  collation이 byte 순서와 같아서 순서가 digest·잠금·Python `sorted()` 비교에 들어가는 text 키가 지금까지 무방비였다.
  evidence export와 backup twin(`principal_id`), evidence restore(lease 재구축·`FOR UPDATE`), curation collection
  advisory lock, cache target source head `FOR KEY SHARE` capture와 member 조회에 `COLLATE "C"`를 걸었다.
  - feature update scope 잠금은 일부러 두었다. DB 함수 `lock_feature_update_request_member_scopes`가 같은 default
    collation 순서로 잠그므로, 한쪽에만 `COLLATE "C"`를 걸면 오히려 잠금 순서가 갈린다.
  - 탐지기 `test_collation_sensitive_orderings_glibc.py`는 lane 이미지 위 최소 표면에서 `'a-b'`·`'ab'`·`'B'`·`'a'`를
    흘린다. advisory lock 순서는 `search_path` 앞 schema에 같은 이름의 함수를 두어 기록하고, row lock 순서는
    `INSERT … SELECT … FOR KEY SHARE`의 삽입 순서로 잰다. alpine lane에서는 skip, 공용 glibc digest에서는 판별력이
    없으면 실패한다.
- **CI**: `integration` job을 `lane: alpine`·`lane: glibc` 두 leg으로 나눴다. 이미지 정본은
  `tests/integration/_postgis_image.py`(`KTM_TEST_POSTGIS_IMAGE`)다. 값이 있는데 digest 모양이 아니면 조용히
  alpine으로 떨어지지 않고 실패한다. main에 required check가 없으므로 두 leg 초록은 리뷰가 확인한다.
- **n150 스크립트**: `adjudicate.sh`는 Map API 컨테이너 안에서 그 컨테이너의 DSN으로 읽기 전용으로 세고,
  `repin.sh` 3단계는 D2 fixture DSN을 그 DSN에서 유도한다. instance 이름·port·superuser 문자열은 없다.
- glibc lane을 n150에서 처음 전량으로 돌리자 두 가지가 나왔다(1139 passed / 20 failed).
  - bootstrap-on-existing-db 19건이 `/usr/bin/sleep: not found`로 죽었다. 테스트가 스크립트를 **서버 컨테이너
    안에서** 돌렸는데, Debian 기반 공용 이미지에는 `/usr/local/bin/psql`도 `/usr/bin/sleep`도 없다. 운영은
    Manager one-shot(`postgres:16-alpine`)이 TCP로 붙으므로 문제는 테스트 모양이었다. 서버 network를 나눠 쓰는
    alpine client 컨테이너에서 돌리게 바꿨다 — 두 lane 모두 19 passed.
  - head 오라클(`alembic/head-schema.sql`)이 헤더 빈 줄 하나로 어긋났다. pg_dump 16.10+는 `\restrict` fence
    뒤에 빈 줄을 하나 더 쓰고, 공용 instance의 16.9는 fence를 쓰지 않는다. 정규화가 fence 뒤 빈 줄도 걷게 했고,
    alpine lane 재생성이 커밋본과 바이트까지 같다.
- n150 부하(load 16~20)에서 docker API가 60초를 넘겨 testcontainers가 `ReadTimeout`으로 죽는 일이 잦았다.
  테스트 하네스에만 docker-py timeout을 늘리는 플러그인을 얹어 돌렸다(코드 변경 아님). alpine lane 첫 전량에서는
  bootstrap 모듈 19건이 알려진 부팅 경합(`not yet accepting connections`)으로 죽었고, 단독 실행은 19 passed다.
- 두 수정 뒤 n150 전량(`0fd7de1c`): glibc **1161 passed / 12 skipped / 0 failed**, alpine 1154 passed / 18 skipped /
  1 failed(`test_public_partial_indexes_have_exact_state_predicate_and_explain_proof` — 단독 재실행은 이 브랜치와
  main 모두 passed). unit·lint 세션의 실패 16건은 main과 같은 집합이다(node_modules 없는 체크아웃·git 아닌 트리).
- 적대 리뷰 반영:
  - **adjudicate 잔여물 측정의 양성 대조.** 종전 테스트는 빈 스키마에서 키 넷과 0만 봐서, 늘 0을 내는 프로그램도
    초록이었다(n150 실측: 변이 `always_zero`·`no_wildcards`·`count_nothing`·`WHERE true` 넷이 살아남았다). 0은 이
    판정에서 위험한 방향이다 — `clear-blocked`가 잔여물이 남은 lane을 지운다. 세어야 할 행은 migrated DB에 둘 수
    없다: session이 나눠 쓰고, `ops.feature_requests`는 삭제가 막혔고, alias CHECK가 `e2e_live_acceptance::`를
    거부한다. 그래서 같은 cluster에 버리는 DB를 만들고, 프로그램이 읽는 열만 실제 타입(catalog에서 읽는다)으로
    만들어 `ktm_feature_schema_owner`로 커밋해 둔다. 소유 이름은 D2 fixture의 `_admin_fixture_name`에서 온다.
    그 run_id의 네 줄이 모두 1, 다른 run_id는 소유분 0이다. 위 넷과 `SET LOCAL ROLE` 제거까지 다섯 변이가 모두 빨갛다.
  - n150 스크립트 셋(`repin.sh`·`chain16.sh` M01·`adjudicate.sh`)이 Map API 컨테이너를 D2 러너와 같은 compose
    project(`/opt/kor-travel-docker-manager`)에서 정확히 하나로 찾는다. service 라벨만으로는 같은 라벨을 단 다른
    stack을 집고, chain16은 `head -1`이었다.
  - `repin.sh` 3단계는 임시 파일을 소비자처럼 `set -a; .`로 읽은 값이 API DSN과 같을 때만 rename한다. 문자 검사는
    `~`를 받는데 대입의 `:` 뒤 `~`는 tilde 확장된다(`:~:pw@` → `:/root:pw@`). 옛 read-back은 바이트를 비교해 통과했다.
  - 인스턴스 탐지기를 이름에서 효과로 옮겼다: PostgreSQL client, DSN `host:port/`, port flag, 유도한 API가 아닌
    곳으로의 `docker exec`. 공용 instance의 이름으로 적은 줄도 이제 빨갛다.
  - 수동 `postgis-only.yml`과 로컬 `verify-all-gates.sh`도 glibc lane을 돈다. 게이트가 둘이 되자 geo live probe
    검사가 두 줄을 합쳐 보던 탓에 변이 R11·R11b가 살아남았다(n150 전량에서 드러남). 이제 게이트마다, 그 게이트가
    쓴 로그로 사후 단언을 요구한다. `test_ci_workflows`는 통합 suite를 도는 모든 workflow job에 두 lane이 있는지
    본다. bootstrap client 컨테이너는 testcontainers label(Ryuk)·`--rm`·`sleep 7200`을 갖는다.
  - 결과: GitHub `postgis-only.yml` dispatch(`3234b3d1`, run 36421797357) glibc **1162 passed / 12 skipped**, alpine
    **1156 passed / 18 skipped**. `ci.yml`의 두 leg는 PR이 열려야 돈다. n150 대상 실행은 두 lane 모두 count 모듈
    3 passed, bootstrap 모듈 19 passed(client 잔여 0).
- Manager ADR 번호 정정: #433이 ADR-52(공용 instance의 `init`·exec probe·grace)가 되어, 이 이동의 Manager ADR은
  **ADR-53**이다. ADR-103 `관련`, `CLAUDE.md`, `integration-map.md`, `deploy.md`, `rest-api.md`와 이 절·resume을
  고쳤다. main의 docs 커밋 #1286 위로 리베이스했다(journal·resume 충돌은 양쪽을 모두 남겼다).
  - 리베이스 뒤(`8b0941a8`): GitHub `postgis-only.yml` dispatch(run 36450175854) glibc **1162 passed / 12 skipped**,
    alpine **1156 passed / 18 skipped**. n150: ruff 초록, `mypy --strict` 일곱 대상 초록(공유 venv에 dev extra
    `types-PyYAML`이 없어 scratch target으로 보탰다), lint-imports 4 kept. unit+lint 3044 passed / 15 skipped /
    15 failed — 14건은 main(`90b1e5e0`)에서도 같은 node로 실패한다(node_modules 없는 체크아웃의 frontend 검증 13,
    `test_lifecycle_preserves_signal_exit_status[INT-130]`), 1건(`test_orchestrator_guardian_lock_…`)은 단독
    재실행에서 passed. gate mirror·mutation battery 17 passed.

## 2026-09-28 (저녁) — 공용 PostgreSQL은 크래시한 것이 아니라 고아를 입양했다

Map DB를 공용 인스턴스로 옮기는 계획을 검토하다가, 공용 인스턴스가 오늘 새벽 한 번이 아니라 67시간 동안 다섯 번
재시작했다는 것이 드러났다. 매번 로그는 "server process (PID N) exited with exit code 2"였고, 그 PID는 로그에 한
줄도 남기지 않았다.

원인을 네 갈래(PG 로그, 호스트·Docker 이벤트, 클라이언트, PG 16.9·moby 소스)로 조사하고 반박 검증을 붙였다. 결론은
"백엔드가 죽은 것이 아니다"였다.
- 컨테이너에 `init`이 없어 postmaster가 PID 1이다.
- 헬스체크 `CMD-SHELL pg_isready`는 sh → Perl 래퍼 → 실제 pg_isready로 자식을 만든다.
- 호스트가 멈칫하면(다섯 번 모두 Manager 재구축·chain17 중) 5초 timeout이 나고, Docker는 exec의 main PID인 `sh`만
  죽인다. 남은 pg_isready는 postmaster에 입양되고, 서버가 응답하지 못하면 exit 2로 끝난다.
- PG16 `CleanupBackend`는 BackendList를 찾기 전에 종료코드부터 보고 전체를 리셋한다.

어제 Dagster에서 본 CMD-SHELL 고아와 같은 계열이다. Dagster에서는 좀비가 쌓였을 뿐인데, Postgres에서는 고아 하나가
전 테넌트 재시작으로 증폭된다. `pg_postmaster_start_time()`은 크래시-재시작에서 바뀌지 않아 이 사건들을 가렸다.

고침(`init: true`와 exec 형식 `pg_isready -t 2`)은 소유자가 지시한 공용 튜닝과 같은 재시작에 넣는다. Map을 옮기기 전에
이것이 먼저 들어가야 Map이 이 위험을 물려받지 않는다.

## 2026-09-28 — M05가 끝까지 갔다: 마지막 벽은 부하가 아니라 PinVi의 빈 Dagster 저장소였다

healthcheck 폭주를 잡은 뒤에도 M05의 PinVi `app-dagster`는 unhealthy였다. 부하 탓으로 보기 쉬웠지만 원인은
PinVi #558의 회귀였다. app compose의 dagster가 `PINVI_DAGSTER_PG_URL`을 받지 못했고 `pinvi_dagster` DB도 없어서,
한가한 호스트에서도 뜰 수 없었다. PinVi #570이 bootstrap 스크립트와 one-shot `app-dagster-db-init`을 넣었다.

새 pair(Map `a18d9274` + PinVi `c5be9eb4`, pinset `8c9f9ad1`)로 회전해 chain17을 돌렸다. t63a는 D1 한 건이
15초 poll에 걸렸고(같은 Map이 직전과 직후 사이클에서 통과), t63b는 ACL 40/40, D1 11, D2 passed였다.
Manager `88599eb9` 설치 뒤 실행 identity가 바뀌었으므로 리허설(p9r `rehearsed`)부터 했다. 실제 실행 p9는
약 11분 만에 `passed`/`completed`로 끝났다. Manager #428로 포트를 고정한 덕에 이미지 빌드가 캐시를 탔다.

같은 날 정리한 것:
- **안 쓰는 전용 PostgreSQL 퇴역**(Manager #429). 목록에서 지운 것은 geo·concierge·pinvi 전용 인스턴스와
  airport-db다. n150에서 실제로 내린 것은 접속 0이던 `pinvi-postgres` 하나이고, 데이터 디렉터리는 남겼다.
  그 과정에서 Manager 백업 cron이 9/20 무렵부터 매일 실패하고 있었음을 찾았다. cron은 git이 아닌 배포 사본을 돌리는데,
  그 사본이 compose 모델보다 뒤처져 있었다.
- **공용 PostgreSQL의 원인 미상 재시작**(03:28:57Z). 백엔드 하나가 exit code 2로 끝났다(보통 SIGQUIT 처리 경로다).
  postmaster가 모든 연결을 끊고 재초기화했다. 디스크 대기 속에서 pre-fsync에 82초가 걸렸다. OOM 흔적은 없다.
  그 시각 이 세션의 에이전트는 n150 임시 사본에서 가짜 대역 단위 테스트만 돌리고 있었다.
  Map을 공용으로 옮기는 계획은 이 영향 범위를 따져야 한다.
- `CLAUDE.md`와 `docs/integration-map.md`는 여전히 "프로젝트별 전용 인스턴스 넷"이라고 적고 있었다.
  실측(공용 11000 + map 12700)으로 고쳤다.

## 2026-09-27 — Dagster healthcheck 폭주: 셸 래퍼가 남긴 고아들

M05가 n150 과부하로 연달아 멈춘 원인을 좁혀 보니, 운영 Dagster 스택 넷(Map·PinVi·geo·weather)의 healthcheck였다.
- 적대 리뷰가 메커니즘을 바로잡았다. docker는 컨테이너마다 probe를 하나씩만 돌린다. 문제는 `CMD-SHELL`이다.
  timeout 때 `sh`만 죽고, 그 아래 dagster-import Python은 고아로 계속 돈다. PID 1인 dagster는 고아를 거두지 않는다.
  exec 형식 probe 컨테이너는 좀비가 0이었다.
- CLI `dagster api grpc-health-check`는 deadline이 없다. weather code-server가 멈추자 probe가 끝없이 쌓였다.
  weather 수집이 하루 반 동안 사실상 멈춰 있었다.

Manager #426(`7bda04db`)의 내용:
- 모든 Dagster probe를 exec 형식 `python -I`로 바꿨다.
- code-server는 같은 gRPC health 호출을 `grpc_health`로 직접 한다(0.5초, deadline 8초).
- daemon은 120초 주기에 timeout 60초, retries 2다.
- 12개 서비스 모두 `init: true`다.

반영: Map·PinVi는 같은 pair 수렴으로, geo·weather는 `-p`/`--project-directory`를 명시한 호스트 직접 재생성으로 했다.
결과: 좀비 565 → 40, 동시 probe 47 → 1, weather code-server 복구.

이 PR은 Map 자체 compose(local dev와 n150 격리 스택)에 같은 계약을 넣고, `test_docker_dagster_runtime.py`가 exec 형식과
`init`을 command에서 유도한 서비스마다 요구한다.

## 2026-09-27 — minio/mc가 사라진 날: 세 저장소의 rustfs-init과 M05가 부딪힌 n150의 한계

M05 port(Manager #424) 뒤 첫 실제 격리 실행 p1은 claim과 Map fresh-init 사슬까지 통과했다. 그다음
`rustfs rustfs-init api frontend` 기동에서 `pull access denied for minio/mc`로 멈췄다. Docker Hub의 `minio/mc`와
`minio/minio` 저장소가 통째로 사라진 것이다. Map·PinVi·Manager 세 compose가 모두 이 이미지로 버킷을 만들고 있었다.
- PinVi는 digest로 핀했지만 저장소가 없으면 digest도 받을 수 없다.
- Manager는 rustfs 재생성 뒤 `run --rm rustfs-init`을 돌리고, 실패하면 mutation을 롤백한다. 즉 rustfs 재생성 자체가 막혀 있었다.

**고친 방법**: 새 클라이언트 이미지를 들이지 않았다. 각 저장소의 rustfs 서비스 이미지에 curl(8.19/8.21)이 이미 있어서,
`curl --aws-sigv4 aws:amz:us-east-1:s3 -X PUT <ep>/<bucket>`으로 버킷을 만든다.
- 이미 있는 버킷은 200(RustFS 실측) 또는 409 `BucketAlreadyOwnedByYou`로 성공이다. 4xx는 코드와 S3 본문을 남기고 즉시 실패한다.
- 적대 리뷰가 하나를 더 잡았다. RustFS는 `/health/live`가 200이 된 뒤에도 약 1.7초 동안 PUT에 `503 waiting for storage_quorum`을 준다.
  옛 mc는 minio-go가 이것을 안에서 재시도했다. 그래서 000·5xx 재시도와 요청 상한(connect 5s, max 30s)을 넣었다.
- Map의 `docker-compose.host.yml`은 스크립트 사본 대신 endpoint env 한 줄만 바꾼다.

**사이클**: 새 pair(Map `a18d9274` + PinVi `fd07903f`)로 회전해 chain17을 돌렸다. t62b는 rebuild `deployed`,
ACL 40/40, D1 11, D2 passed로 초록이었다. t62a에서는 pinvi-web 빌드가 37분 동안 `Build Steps 0/0`, I/O 0으로 보여
buildx bake를 끊었다. 나중에 docker.sock의 `/debug/pprof/goroutine?debug=2`로 보니, 같은 상태의 빌드는
`exportLayers → computeBlobChain → overlay.WriteUpperdir → gzip`에 있었다. node_modules 레이어를 파일 단위로 압축하는 중이었다.
**조용함은 정지의 증거가 아니었다.**

**M05는 n150 한계에 부딪혔다.** p2~p4는 모두 본문 진입 전 인프라 phase에서 멈췄다(scoped 차단, 실행권 미소비).
Map과 PinVi `rustfs-init`은 셋 다 `Exited (0)`이었다.
- p2: PinVi web export 약 40분 → `commit failed: context deadline exceeded`.
- p3·p4: PinVi `app-dagster`가 HEALTHCHECK 한도(약 150초)를 넘겨 unhealthy.

원인을 좁히니 운영 Dagster 스택들의 healthcheck였다. `dagster-daemon liveness-check`와 `dagster api grpc-health-check`는
주기마다 dagster를 import하는 Python을 띄운다(각 수 초, CPU 95%). 부하가 오르면 10초 타임아웃을 넘겨 다음 주기와 겹친다.
p4 도중 이런 프로세스가 47개 동시에 돌았고 load는 137까지 갔다. PID 1이 자식을 거두지 않는 Dagster 컨테이너들에는 좀비가
565개 쌓여 있었다. M05 빌드 부하가 이 되먹임에 불을 붙였다. 운영 서비스라 내리지 않았다. healthcheck 경량화와 `init: true`를
소유자 결정으로 올린다.

## 2026-09-27 — C6c 보호 참조를 표에서 규칙으로: 운영 데이터로 미리 돌려 본 것이 배포를 살렸다

Manager ADR-51 결정 5를 두 PR로 끝냈다. 대상은 UI·API 사용자가 compose env를 고칠 때 비밀이 엉뚱한 서비스로 새지
않게 하는 C6c 보호 참조다. 먼저 규칙을 옛 표 검사와 **나란히** 세웠고(P-1), 그다음 표를 지웠다(P-2).

- **규칙**: 설치기가 git에서 쓴 읽기 전용 사본 `.ktdm-release-compose.yml`이 원본이다. 후보가 어떤 자리(서비스 env key,
  다른 필드, 최상위 항목)에서 참조하는 보호 변수는 원본이 같은 자리에서 참조하는 것의 부분집합이어야 한다. 보호
  변수는 이름이 민감하거나, 값이 `.env` 비밀을 담는 변수다.
- **P-1에서 드러난 것**: 옛 표는 공유 PostgreSQL 비밀과 geo·concierge·weather·transport 비밀을 하나도 몰랐다.
  `grafana`에 `${KOR_TRAVEL_SHARED_POSTGRES_PASSWORD}`를 얹어도 통과했다.

값진 순간은 두 번 다 "운영 데이터로 미리 돌려 보기"에서 나왔다.
- **P-2의 거짓 양성**: 표 대신 파생 이름으로 bind 파일 내용을 스캔하게 바꾸자, n150의 실제 `rustfs-init` 스크립트가
  거부됐다. 스크립트가 자기가 쓰는 env 이름을 적었을 뿐이다. 이대로 머지했다면 모든 배포가 막혔을 것이다. 내용
  스캔은 이제 비밀 **값**만 찾는다. 옛 Map role bootstrap 면제 주석이 이미 그 원칙을 말하고 있었다.
- **적대 리뷰의 우회로**: 변수 이름 파서가 `str.isalnum()`을 써서 `$..._PG_DSNé`를 모르는 이름으로 읽었다.
  compose는 DSN을 치환한다. resolved 스캔을 지운 뒤라 막는 것이 없었다. 이름을 ASCII로 좁혔다. resolved 문서에는
  "비밀 값은 원본의 보호 참조 자리에만" 백스톱을 다시 세웠다.

n150 검증:
- 매 단계 `pin verify` 0, M05 preflight 0, 같은 pair 수렴 `converged`, 컨테이너 42개 재생성 0이다.
- 설치된 compose는 통과한다. 공유 비밀을 grafana로 옮긴 후보와 Map API 토큰을 map-ui로 옮긴 후보는 거부된다.
- 사본은 git과 바이트가 같다.

## 2026-09-27 — 실패 출력을 봉인에서 원문으로: 스크러버 하나, 채널 하나

Manager ADR-51 잃는 보장 G를 세 PR로 끝냈다. 순서는 "가리는 쪽 먼저"였다. G-1에서 스크러버 하나(`secret_scrub.py`)를
CLI·API 출력 경계에 먼저 세웠다. 그다음 G-2가 재구축 경로의 봉인을 풀어 원문 tail을 싣고, G-3이 M05의 opt-in forensic
증거 파일들을 "항상 캡처, 가린 `stderr.log` 하나"로 바꿨다. 순서를 거꾸로 하면 원문이 가림보다 먼저 나간다.

리뷰가 잡은 것은 이번에도 "출력 자리"였다. G-2에서 `compose config`의 stderr tail이 `ComposeCandidateContractError`를
타게 되자, 그것이 `ValueError`라서 `ktdctl action`·`ensure`의 `print(str(exc))`가 가리지 않은 채 냈다. 그래서 CLI의
예외 출력 20곳을 helper 하나로 모았다. 테스트는 원문 출력 자리가 없다는 사실을 본다. 스크러버의 원천도 고쳤다.
`.env`와 프로세스 환경을 합치면 한쪽 값이 사라진다 — compose는 프로세스 환경을, 스크러버는 `.env`를 앞세웠다.
이제 합치지 않은 key·값 쌍을 모은다.

G-3의 가장 값진 발견은 우연한 검사였다. M05의 fresh-init 진단 override는 서비스에 entrypoint만 얹었다. 서비스가
없으면 compose가 그 override를 거부했고, 그것이 claim 전에 났다. override를 걷으면 이 검사도 조용히 사라지고,
핀된 Map(서비스 이름이 `db-application-schema-fresh`로 바뀜)에서 M05가 실행권을 쓴 뒤에야 죽는다. 이제 claim 전에
명시적으로 본다. 생성 비밀은 목록 대신 생성·기록 시점에 스스로 등록된다. 옛 목록은 열한 개를 놓쳤다. 새 테스트는
driver가 **실제로 쓴** env 파일을 자식이 통째로 에코하게 하고, 민감 값이 하나도 새지 않는지 본다.

n150 검증:
- 재구축 probe(일부러 거부시킨 실행): JSON은 `{"status":"failed","stage":"environment_admission"}`이다. traceback
  마지막 줄에 진짜 원인이 있고, 비밀 71개 중 누출은 0이다.
- M05 negative probe 둘: 원인 문구가 나오고 누출은 0이다.
- 같은 pair 수렴: 두 번 다 `converged`, 컨테이너 42개 재생성 0이다.
- 맞춰서 `scripts/n150/chain17.sh`도 원인을 숨기지 않게 했다. 회전 preflight 사유와 회전 실패 출력 전체를 보이고,
  재구축이 실패하면 stage와 `stderr.log` 끝 80줄을 보인다. 회전 종료값을 보게 되면서 재실행 경로가 생겼다. C에서 실패한 뒤 다시 돌리면 같은 pair 회전을 registry가 거부하므로, 원장이 이미 그 Map이면 B를 건너뛴다(리뷰가 잡았다).

## 2026-09-27 — 소스 봉인을 걷어냈다: SHA가 곧 증명, 이름 붙은 디렉터리가 곧 캐시

Manager ADR-51 잃는 보장 E를 세 PR로 끝냈다. 순서는 이번에도 "읽는 쪽 먼저"였다. E-1에서 재구축의 Map 계약
reader를 git이 아니라 파일 읽기로 옮겨 두지 않았다면, E-3에서 source가 `.git` 없는 archive가 되는 순간 모든
재구축이 `candidate_contract`에서 죽었을 것이다 — 그런데 그 reader를 부르는 유일한 테스트는 함수를 통째로
대역으로 바꾸고 있어서 CI는 초록이었을 것이다([낡은 테스트 대역이 계약 파손을 가린다]).

E-2에서 M05는 archive가 아니라 실행별 checkout을 쓴다. PinVi attestation이 진짜 clean checkout과 Map의 service
릴리스 blob을 요구하기 때문이다. 적대 리뷰가 잡은 가장 중요한 것은 테스트의 맹점이었다 — full-path harness의
checkout 대역이 preflight 트리를 그대로 복사해서, body가 Map compose나 `--map-source-root`를 옛 트리로 되돌려도
모든 테스트가 통과했다. 이제 두 checkout이 생긴 뒤 preflight 트리를 치워 버린다(변이 3종이 red).

E-3의 해석 하나: "실행마다 fetch"를 "없을 때만 fetch, 같은 revision은 재사용"으로 읽었다. 디렉터리 이름이 SHA이니
재사용이 곧 증명이고, 같은 pair 수렴이 네트워크 없이 끝난다. 대신 재사용이 git 없이 이뤄지므로 두 가지를 더했다 —
이름을 붙이기 전에 `os.sync()`, 기록이 손상되면 거부하지 않고 다시 만들기(거부하면 수동 삭제 전까지 모든 재구축이
막힌다). 또 `tarfile`의 `data` 필터가 디렉터리 mode를 적용하지 않아 M05의 umask 077을 따르면 이미지 안에 0700
디렉터리가 구워질 뻔했다 — 디렉터리를 0755로 고정하고 변이로 확인했다.

E-2 검증 삼아 실제 M05를 한 번 돌렸는데 claim 전 단계에서 거부됐다. E-2 탓이 아니라 Map #1259가 지운
`docker-compose.local-dev.yml`과 옛 role을 M05 driver가 아직 쓴다 — 9월 23일 이후 M05 전체 실행은 가능하지 않았다.
정기 게이트가 preflight까지만 보기 때문에 아무도 몰랐다.

## 2026-09-27 — 설치기를 1,887줄에서 196줄로: 레이아웃을 먼저 옮기고 나서 설치기를 바꿨다

Manager ADR-51의 잃는 보장 D(설치기)를 끝냈다. D-1/D-2와 같은 순서를 따랐다 — **설치 root가 symlink여도
모든 소비자가 도는 코드(I-1)를 옛 설치기로 먼저 깔고**, 손으로 한 번 레이아웃을 옮긴 뒤, 새 설치기(I-2)를
그 위에 설치했다. 거꾸로 하면 새 설치기가 만든 symlink를 옛 코드(재구축 root·M05·rebind·관리자 비밀번호)가
`lstat`으로 거부해 모든 mutation이 멈춘다.

핵심 규칙은 하나였다: **compose 프로젝트 루트는 resolve하지 않는다.** 풀린 release 경로가
`--project-directory`에 들어가면 상대 bind source가 `/opt/ktdm-release-<sha>`로 굳어 설치마다 컨테이너가
재생성되고, 그 release가 GC되면 재시작에서 깨진다. n150에서 compose v5.2와 venv가 symlink 경로를
그대로 쓰는지 먼저 봤고, 인수에서는 같은 pair 수렴 뒤 컨테이너 42개의 bind 문자열과 생성 시각이 그대로인지를
봤다. 반대로 비교하는 쪽은 양쪽을 다 풀어야 했다 — operator bind의 backend 소스 가드는 한쪽만 풀고 있어서
symlink root에서 조용히 통과하고 있었다(I-1에서 고침).

적대 리뷰가 I-1에서 한 건(revision을 읽는 두 곳이 root 소유·쓰기 금지 검사까지 지웠다), I-2에서 일곱 건을
확정했다. I-2의 가장 쓸모 있던 지적은 재기동 한도였다 — 깨진 release가 `StartLimitBurst`를 넘기면 그
직후의 롤백 설치가 `systemctl start`에서 거절되어 backend가 내려간 채 남는다. `reset-failed`를 먼저 부른다.
반박된 보안 지적 몇 개(운영자 소유 clone에서 root가 설치기를 실행한다, `python -m venv`가 cwd를 import한다)도
한두 줄이라 받아들였다 — 이제 설치기는 root 소유 clone만 받고 git도 root로 돈다.

부수 효과: 옛 헬퍼가 설치본 안에서 `npm ci && npm run build`를 돌려 release마다 790MB가 쌓였는데, 프론트
유닛은 운영자 홈의 사본에서 돈다 — 아무도 쓰지 않는 빌드였다. 새 release는 83MB다.

## 2026-09-27 — 봉인을 걷어낸 체인으로 한 바퀴: D 완료와 최종 인수

Manager ADR-51 D를 세 PR로 끝냈다. 순서가 핵심이었다 — **읽는 쪽을 먼저 옮기고(D-1), 그다음 쓰기를
멈추고(D-2), 마지막에 mount를 걷는다(D-3)**. 거꾸로 하면 v6 쓰기를 멈춘 첫 새 pair 배포 뒤 M05가
"pinset이 다르다"로 막힌다. D-1은 n150에서 v6 파일 둘을 잠시 치워도 `pin verify`와 M05 preflight가
그대로 0인 것으로 "아무도 읽지 않는다"를 확인했고, D-3은 네 컨테이너를 다시 만들며 permit 마운트와
env 이름이 사라진 것을 봤다.

적대 리뷰는 D-1에서 문구 하나(v6 동결 이유를 여전히 "M05가 읽어서"로 적음)만 잡았고, D-2·D-3에서는
발견이 없었다. 한 가지 운영 실수: PinVi 문서 PR의 머지가 CI 완료 전에 실패했는데 스크립트가 원격
브랜치를 지워 PR이 닫혔다 — 커밋을 다시 올려 reopen 뒤 머지했다(merge 결과를 확인한 뒤에만 브랜치를
지울 것).

최종 인수로 최신 Map main(`b4fbde1e`)을 새 pair로 chain17에 태웠다. 전진 배포는 같은 DB 위에서 전체
경로를 돌았고(oid 그대로), v6 파일은 D-2 이전 시각 그대로, permit 없이 storage one-shot이 끝났다.
ACL 40/40 → D1 11 passed → D2 passed. 봉인·신뢰 릴리스 단순화(ADR-102 / Manager ADR-51)는 여기서
닫는다.

## 2026-09-27 — 락을 먼저 합치고 나서 줄였다

Manager ADR-51 C를 세 PR로 끝냈다. 결정 6이 순서를 정해 두었다 — rehearsal에서 UI mutator가 다른 락 파일을
잡고 있었으므로, **먼저 모두를 G 하나로 모은 뒤에야** pinned lease와 env 파생 락을 지울 수 있었다. 거꾸로 하면
지우는 순간 한동안 "한 번에 한 mutator"가 깨진다.

C-1에서 드러난 것: CLI의 pin 변이 검사들은 **환경의 우연**으로 초록이었다. CI에는 `/run/lock/...`이 없어서,
n150 비root에서는 읽을 수 없어서 락 없이 진행하는 갈래로 빠졌다. 그 갈래를 지우자 전제가 사라졌고, conftest가
테스트마다 G를 자기 소유 tmp 디렉터리로 옮기게 했다([검사의 전제가 환경의 우연이면]). 그 픽스처의 정리 순서가
다른 테스트의 `os.open` 대역과 부딪혀 한 번 더 고쳤다.

적대 리뷰가 C-3에서 잡은 것 중 기억할 만한 것: 지운 락 경로 대조를 대신한다고 둔 `.env` 대조가 **같은 객체끼리
비교해 실패할 수 없었다**. 재구축의 진짜 보호는 본문 내내 쥔 G와 동결된 snapshot이다 — 없는 보호를 있다고
적느니 지우고 그렇게 적었다. 그 삭제를 정규식으로 하다 한 호출이 `with` 블록의 유일한 문장이라 모듈 전체가
SyntaxError가 된 것도 n150이 잡았다(커밋 전에 파싱 한 번이면 됐다).

n150: 같은 pair 수렴 재구축 중 `lslocks`에 `global-mutation.lock` 하나만 보였다.

## 2026-09-26 (자정 무렵) — Manager B3: 6,900줄을 지우는 동안 리뷰가 잡은 것은 검사와 문구였다

첫 새 pair가 단순화된 체인으로 D2까지 선 뒤, Manager의 v8 journal 시절 코드를 세 PR로 걷어냈다
(#405 carry-over·죽은 증거, #406 journal 모델, #407 journal 시절 관리자·preflight 화면). 지운 것은 약
6,900줄이다. 각 PR에 적대 리뷰를 돌렸고, 잡힌 것은 런타임 결함이 아니라 **검사와 문구**였다.

- PR-1의 "옛 v6/v8 파일을 넘겨받지 않는다" 검사는 `{}` 바이트를 심었는데, 옛 carry-over도 파싱 실패를
  삼켜 None이 되므로 carry-over가 되돌아와도 초록이었다. 옛 코드라면 넘겨받았을 커밋된 세대를 심자
  B2 시점 src에서 빨개졌다 — [검사기 하한은 '본 것'에 건다]의 또 한 예.
- PR-2는 pinset digest를 여전히 "Map과 공유하는 계약"이라 적어 같은 문서의 "Map이 그 코드를 지웠다"와
  모순됐다. 이제 이유는 디스크다(원장·보존 사본·차단 목록·실행 원장이 모두 그 digest로 묶인다).
- PR-3은 현재 세트에 옛 차단 기록이 있을 때 패널 머리가 서버의 `pin verify` 대신 "회전해야 합니다"를
  보였다 — 같은 패널 아래의 "재구축은 경고일 뿐"과 모순.

n150 설치 뒤 `pin verify`·공개 세대 리더·M05 preflight·같은 pair 수렴이 모두 그대로였다. 하나 배운 것:
설치본을 직접 호출해 검사할 때 `python -I`는 서비스의 `PYTHONPATH=backend/src`를 버려 `.env` 경로를
site-packages 기준으로 잘못 잡는다 — preflight가 `MODE_UNVERIFIABLE`로 보였지만 서비스 환경에서는
`rehearsal/rebuildable`이었다.

## 2026-09-26 (늦은 밤) — 봉인 없이 한 바퀴: 첫 새 pair가 D2까지 섰다

M1(#1270)과 M2(#1272)를 머지하고 `/root` 호스트 스크립트를 머지 커밋에서 설치한 뒤, 새 pair(Map
`031205ff`)를 단순화된 체인으로 처음 돌렸다. 회전 전 pair 계약 preflight(유지한 hard gate) → 전진 배포
`deployed` → repin(원장 대조와 이미지 라벨뿐) → ACL 40/40 → D1 11 → **D2 passed**. 전진 배포는 DB를 지우지
않았고(oid 그대로), M1의 storage one-shot이 처음으로 **이미 head인 영속 metadata DB 위에서** 돌았다.
D2는 root 소유 스냅샷이 아니라 D1과 같은 git archive 체크아웃에서 돌았고, BLOCKED/result는 v4였다.

M2에 붙인 `adjudicate.sh`(rebuild가 가로지른 BLOCKED 정리)는 호스트 사본을 옮기다 결함 셋을 드러냈다.
옛 사본은 M2 뒤 늘 실패했고(퇴역한 env 키와 스냅샷 경로), 옮긴 판에도 적대 리뷰가 major 하나를 잡았다 —
러너의 lock을 잡지 않고 ACTIVE·run 컨테이너를 보지 않아, timeout으로 죽은 D2의 BLOCKED(recover의 유일한
앵커)를 지울 수 있었다. 재검증은 lint가 가드 **삭제**만 잡고 `|| true` 같은 **약화**는 놓친다는 것을 보였다.

t59a 로그에는 작은 것이 하나 더 있었다. chain16 step E가 공유 체크아웃 `/tmp/ktm-lint`에서 `fetch` 뒤
M01 preflight를 꺼내는데 fetch 실패(`unresolved deltas`)를 보지 않아, 옛 origin/main 사본이 조용히 돌았다.
배포한 SHA에서 꺼내고 실패하면 멈추게 고쳤다.

## 2026-09-26 (밤) — 배포는 이제 DB를 지우지 않는다: Manager B2 설치, 같은 pair가 45초에 수렴했다

Manager ADR-51 B2(#404)를 머지·설치했다. 재구축 본체가 v8 journal 상태기계에서 **마이그레이션 전진**으로
바뀌었다 — 영속 상태는 `deploy-status.json` 하나, 재개 없음, 리셋은 `--restart`뿐.

**적대 리뷰가 내 수정을 두 번 잡았다.** 1차 리뷰 반영에서 "판정 전에는 PostgreSQL을 멈춰 있을 때만
띄운다"로 바꿨는데, 2차 리뷰(5개 관점이 독립으로 같은 결함에 도달)가 그 변경이 major 둘을 만든 것을
보였다: 떠 있는 DB 컨테이너의 이미지가 바뀌면 `--restart`까지 모든 실행이 같은 자리에서 영구히 막히고,
PGDATA가 바뀐 호스트에서는 **옛 컨테이너로 identity 기준선을 통과한 뒤 새 cluster를 만들어 커밋**했다 —
`--restart` 없는 리셋. 두 PostgreSQL을 판정보다 먼저 `up`하고 전체 경로는 다시 `up`하지 않는 것으로
고쳤다. 3차(2차 수정의 검증)는 다시 minor 둘을 잡았다 — 리셋 여부를 "기준선이 비었는가"로 추측하면
기준선 없이 시작한 `--restart`가 리셋 전에 죽어도 리셋으로 기록된다. 리셋이 끝나면 `step=reset`을
쓰는 것으로 바꿨다. 고친 것마다 결함을 되살려 테스트가 빨개지는 것을 확인했다(변이 18/18).

**n150.** 설치(`13e744b`) → `pin rebind-execution` → 같은 pair(`6511441f`/`b227e77b`)로 첫 전진 배포.
기대한 carry-over(지금 세대를 그대로 넘겨받기)는 일어나지 않았다 — state root에 **옛 계약의 v8 journal
62개가 더는 읽히지 않고**, 읽을 수 없는 journal이 하나라도 있으면 넘겨받지 않는다는 규칙이 걸렸다.
설계된 대안인 "기준선 없는 전체 경로 한 번"으로 갔고(150초, 리셋 없음), DB oid가 t57d가 만든 것과
정확히 같다(1186381 / 1191333 / 430243). ADR-069 토폴로지 PASS, D1 11 passed. **두 번째 실행은
`converged` 45초**, 런타임 컨테이너를 재시작하지 않았다.

## 2026-09-26 (저녁) — 42GB를 비우니 배포가 한 번에 섰다

#401을 설치하고 같은 pair(Map `6511441f` / PinVi `b227e77b`, pinset `e4909e26`)로 chain17을 두 번
더 돌렸다. **t57b**는 pinvi-dagster 빌드 중 BuildKit session healthcheck 실패로 죽었고, **t57c**는
journal 전에 내가 멈췄다 — 둘 다 코드가 아니라 호스트였다. SATA SSD가 91% 차 있었고 IO 압력 `full`이
여전히 50~60%였다. 타임아웃을 늘리는 것은 증상 완화라, 이번에는 원인을 줄였다.

디스크 조사는 후보마다 "지워도 되는가"를 따로 반박하게 했고, 결과를 세 층으로 나눴다. 캐시와 재생성
가능한 것(옛 pinset·리허설 이미지, 고아 볼륨, Manager의 옛 pinset 소스 78개, npm/uv/pip 캐시,
지난 e2e·C7·M05 스크래치)만 지웠다. 42G → 84G(91% → 82%), IO `full`은 약 3%로 떨어졌다. 백업·덤프
(약 31GB)와 다른 세션의 작업 디렉터리(약 18.5GB)는 되돌릴 수 없어 소유자 판단으로 남겼다. 지우는
명령도 추측이 아니라 명시 목록이었다 — `docker volume prune`은 현재 스택이 아닌 이름 붙은 볼륨까지
삼키고, 옛 작업 디렉터리 하나는 다른 worktree들의 git 디렉터리였다.

**t57d**는 같은 pair로 끝까지 섰다. rebuild success → executor 이미지 → repin(verifier PASS) → M01 ACL
preflight 40/40 → **D1 11 passed** → **D2 `phase: passed`**(lane에 BLOCKED/RESULT/ACTIVE 없음).
ADR-069 토폴로지도 확인했다: Map·PinVi 각각 code-server/webserver/daemon healthy, companion 이미지 =
owner 이미지, code location LOADED(Map 48 jobs, PinVi 9 jobs). gRPC 12703/12803은 `ss`에
`[::ffff:127.0.0.1]`로 보인다 — host network에서 dual-stack 소켓이 loopback에 묶인 모습이고, 호스트의
비-loopback IPv4 29개에서 전부 거부되는 것을 직접 확인했다(내 검증 스크립트가 `127.0.0.1:` 표기만 받던 것을
고쳤다).

## 2026-09-26 (오후) — 디스크가 포화된 호스트의 60초, 그리고 배포는 데이터를 지우지 않기로

**t57a.** #399를 설치하고 새 pinset `8451c8a3`으로 chain17을 돌렸다. 후보 빌드 49분 뒤, journal을
쓰기도 전에 `application_candidate`에서 죽었다. 이번에는 봉인된 stage 한 단어가 아니라 #399가 남긴
원인 원문(비밀 가림)이 stderr에 있었다 — `docker run --network none … ktm-application-schema head`가
60초 타임아웃. 같은 명령을 손으로 돌리니 정상 출력(`head: 400`)에 74초, `docker run --rm /bin/true`
하나에 112초였다. n150의 SATA SSD는 92% 차 있고 `/proc/pressure/io`의 `full`이 5분 평균 50%다.
컨테이너 하나 띄우는 데 1~2분이 드는 호스트에서 60초 정적 검사는 멈춤 감지가 아니라 오탐기다.
같은 이유로 ADR-069 뒤 직렬이 된 Map `up --wait`(code-server → webserver → daemon)도 300초로는
위험하다. 둘 다 올렸다(600초, 900초). 디스크 포화 자체는 열린 문제로 남긴다.

**배포 모델.** 봉인·신뢰 릴리스 단순화 설계를 소유자에게 올렸고 잃는 보장 목록 전체가 승인됐다.
하나는 설계의 전제를 바꿨다 — **DB를 배포마다 지우지 않는다.** 설계는 "새 pinset = DB 리셋"을
깔고 있었는데, 재조사해 보니 journal 상태기계의 대부분이 그 리셋 때문에 존재했다(리셋 도중 죽으면
어디서 재개하나, 이 DB가 이번 회차에 만든 그 DB인가). 리셋을 명시적 `--restart`로만 두면 재개도
receipt도 permit도 필요 없어지고, 전역 상태 파일 하나(absent/in_progress/committed)와 멱등
one-shot만 남는다. Map 쪽 결정은 ADR-102로 남겼다: migration forward-only, stamp bridge 없는
재스쿼시 금지, storage one-shot 멱등화, 런타임 `verify-identity`·argv 봉인 제거(loopback 가드만),
C7 attestation 체인 제거(ADR-094 대체). 대가도 함께 적어 두었다 — 배포가 더는 빈 DB 경로를 증명하지 않고,
손으로 만든 drift가 살아남고, 낮은 head로는 되돌릴 수 없다.

## 2026-09-26 — 재구축은 Map code-server를 한 번도 띄운 적이 없었다

어제 항목의 "재시도 예정"은 네 번 더 실패했다(t56c~t56h). 원인은 셋이 겹쳐 있었고, 봉인된
실패 출력 때문에 하나씩 벗겨 내는 데 사이클마다 1~2시간이 들었다.

**1. PinVi가 먼저 막았다 — SQLAlchemy 2.1.0.** 같은 날 나온 2.1.0이 bare `postgresql://`
URL의 기본 driver를 psycopg2에서 psycopg(v3)로 바꿨다. PinVi etl 이미지에는 psycopg2만 있어
dagster-postgres의 동기 엔진이 `ModuleNotFoundError: psycopg`로 죽었다(새로 빌드한 webserver만,
옛 이미지의 code-server·daemon은 멀쩡). Map #1265와 같은 무상한 핀 문제 — pinvi#565로 `<2.1`.

**2. 내 비상 패치가 두 사이클을 날렸다.** 서비스를 살리려고 `/opt` compose의 webserver/daemon
명령을 `-m`으로 되돌린 패치를 두 번 넣었는데 두 번째는 되돌리지 않았다. 그 상태로 t56g·t56h가
돌았고, 새 이미지의 봉인 entrypoint가 `-m` argv를 fail-close해 compose up에서 죽었다. 그 사이클의
journal은 패치본 compose sha(`9296daab…`)를 동결해 pinset `a7cc0414`는 재개 불가다. 신뢰 릴리스
사본(`8ac4ed17…`)으로 원복했고, 이 커밋이 새 pinset을 만든다.

**3. 근본 — `up --no-deps`가 depends_on을 지운다.** Manager의 pinned rebuild는 Map을
`up -d --no-deps --wait kor-travel-map-ui kor-travel-map-dagster kor-travel-map-dagster-daemon`로
띄운다. compose-go는 `--no-deps`에서 호출에 이름이 없는 서비스로의 간선을 지우므로, webserver가
code-server에 `service_healthy`로 의존해도 code-server는 **기동되지 않는다**(dockerd 로그상 어떤
재구축도 띄운 적 없음). 게다가 webserver healthcheck는 빈 `RepositoryConnection`도 통과시켜
`--wait`가 초록이었고, D1의 Dagster 단언은 instance storage의 run 개수뿐이라 code location을 안
본다 — 신뢰 compose로 돈 사이클이 끝까지 갔다면 저장소 0개인 Dagster가 GREEN으로 커밋됐을 것이다.
PinVi code-server·daemon도 같은 이유로 재구축이 정지·재생성한 적이 없어 DB 리셋을 건너 옛
이미지로 옛 코드를 서빙하고 있었다(어제 내가 수동으로 띄운 것).

**수정(Manager #399).** slot 이미지를 그대로 쓰는 비-slot
장기 실행 서비스를 frozen resolved compose에서 파생해("generation companion") owner slot과 같은
stop/up/readiness/image 대조/secret inspection에 태운다. 실제 `docker compose config`로 세 개
(Map code-server, PinVi code-server·daemon)가 나오는 것을 확인했다. 영속 포맷(v6 manifest, v8
journal, 7-slot)은 그대로다. 같은 PR에서 봉인 단순화의 첫 걸음으로 `rebuild-pinned` 실패 시
예외 체인 전체를 `.env` 비밀과 URL userinfo를 가려 stderr에 남긴다(JSON·종료코드는 그대로) —
이번에는 원문을 보려고 설치본 `cli.py`에 계측을 심고 파괴적 재구축을 다시 돌려야 했다. 그리고
PinVi code-server가 host network에서 `-h 0.0.0.0`으로 인증 없는 gRPC를 LAN에 열고 있어
`127.0.0.1`로 묶었다.

첫 커밋의 테스트는 반쪽이었다. 적대 리뷰가 companion 호출처 10곳 중 8곳은 하나씩 지워도 아무
테스트도 안 깨진다는 것을 확인했다 — 이번 결함(호출 하나에서 이름이 빠짐)이 그대로 재발할 수 있는
자리다. `cancel_probe_finalized`에서 commit까지, 이어서 committed 재개까지 도는 테스트를 더하고
n150에서 변이 검사로 10곳 + one-shot 제외 규칙 + 프로세스 환경 리댁션 12개가 각각 빨개지는 것을
봤다. 같은 규칙을 명령으로 검출하다 보니 **geo code-server도 host network에서 `0.0.0.0`**이었다.
geo 이미지의 workspace host를 확인하기 전에는 못 바꾸므로 알려진 예외로 등록하고, 해소되면 예외를
지우라고 빨개지게 했다.

**봉인·신뢰 릴리스 단순화(소유자 지시).** 네 덩어리(설치기 1,887줄, 재구축 실패 봉인, pinset·
journal·실행 레지스트리 결박, Map storage permit/receipt/intent)를 조사해 설계를 만들었다. 적대
리뷰가 짚은 쟁점: UI/API 사용자가 compose env를 직접 편집하므로 C6c 보호 참조 표는 파생 규칙으로
대체해야지 지우면 안 된다, 호스트 스크립트(repin.sh/gen_attest.py)가 v6/v8 파일에 묶여 있다,
committed never-reset 가드는 DB identity 없이는 안전하지 않다, 매 배포 DB 리셋(destructive-by-default)
자체가 상태기계의 근원이다. 잃는 보장 목록을 ADR로 올려 승인받은 뒤 단계적으로 진행한다.

## 2026-09-25 — ADR-069 code-server 분리: PinVi 활성화 + Map 전환(#1264/#397), 재구축 두 자리 수리

**PinVi.** dagster-code-server + webserver(`-w workspace.yaml`) + daemon을 n150에
처음 기동했다. Manager의 compose 주석이 이미 원인을 적어 두고 있었다 — "이
서비스가 없어서 PinVi Dagster는 한 번도 job을 실행한 적이 없다." 활성화
직후 schedule/sensor 0개 자동 기동을 확인하고 안전하게 마쳤다.

**Map.** 같은 패턴(weather/geo/transport/PinVi와 동일)으로 Map도 code-server를
분리했다 — `dagster-code-server`가 유일한 `dagster api grpc` 프로세스이고
webserver/daemon은 `workspace.yaml`로 grpc 접속만 한다. 저장소 두 곳에 걸친
작업(Map #1264, Manager #397)이라 각자 "등록" 누락이 있었다:

1. **SQLAlchemy 2.1.0이 그날 나왔다.** `sqlalchemy>=2.0` 무상한이 mypy
   --strict를 15개 무관한 ORM 조회부 파일에서 26건 깨뜨렸다 — Map #1264와
   무관한 base 자체의 환경 drift(어제 그린이던 커밋이 오늘 그대로 빨갛다).
   `>=2.0,<2.1`로 고정(#1265)해서 닫았다.
2. **C7 attestation 개수 하나.** `dagster-code-server`가 7번째 `build:`
   서비스라 `KOR_TRAVEL_MAP_GIT_COMMIT` 카운트가 6→7로 바뀌어야 했다.
3. **Manager `compose_service.py`의 별도 레지스트리.** `c6c_deployment.py`의
   candidate-protected-value allowlist(#397에서 이미 갱신)와는 **다른**
   자리 — `_validate_map_source_protected_scalar_tree`가 Map 자신의
   compose에서 `KOR_TRAVEL_MAP_DAGSTER_PROFILE`이 나올 수 있는 정확한
   `(service, env-var)` 경로를 고정 목록으로 들고 있다. `dagster-code-server`가
   webserver의 env 블록을 통째로 복사해 이 변수도 들고 왔는데 목록엔 없었다
   — 이 파일 자신의 테스트 주석이 그대로 인용하는 PinVi #356/#358과 같은
   부류다. Manager #398로 등록(+ 해당 테스트 세 개도 함께)했다.

**재구축이 두 번 막혔고, 봉인이 매번 한 단어였다.** launcher(`--json`)는
`{"status":"failed","classification":"prejournal_failure","stage":"..."}` 한
줄만 남긴다 — `/root/rebuild-diag.sh`(9월 12일 사고의 산물)를 그대로 복제해
같은 lock FD를 넘기고 `--json` 없이 재현해서만 원문을 회수했다(첫 번째는
`candidate_contract`/`ComposeCandidateContractError`, 두 번째는 `v6 execution
lifecycle`이 이전 실패를 pinset 단위가 아니라 **(pinset, Manager revision)
조합** 단위로 terminal 취급해 막은 것 — Manager를 고쳐도 같은 pinset을 다시
쓰면 여전히 막힌다. 탈출구는 새 커밋(새 pinset)뿐이라 이 저널 커밋 자체가
그 새 pinset이다.

**끝난 상태 (진행 중).** Map #1264 + Manager #397/#398 전부 머지, n150
Manager는 `6452a4c…`로 재설치·프론트엔드 재빌드까지 완료. 재구축은 이 커밋의
새 pinset으로 재시도 예정 — 결과는 다음 저널/resume 항목.

## 2026-09-24 — prod 전 사이클 GREEN. Map 400 + PinVi 단일 role 둘 다 실사용으로 처음 섰다

어제 (5)에서 남긴 "빌드 영수증 축 빠짐"부터 시작해 Manager 쪽을 세 PR로 닫았다
(#391 직접 buildx build, #392 postgres image id sha256 해석, #393 resume이
재현 안 되는 buildx를 다시 빌드하지 않고 journal을 그대로 씀). 그런데 재구축이
Map 쪽을 다 통과하고 나서 **PinVi 쪽에서 연쇄로 네 번 더 막혔다** — 전부 같은
모양이다: **ADR-46(PinVi M05 다중 role 폐기 → geo와 같은 단일 scoped role)이
인프라 쪽은 다 고쳤는데, 그 인프라가 떠받치던 자리 몇 개를 안 고쳤다.**

**1. pinvi DB owner가 frozen contract와 달랐다.** 공용 control-plane
instance(`kor-travel-shared-postgres`)의 `pinvi` DB가 `pinvi_application_runtime`이
아니라 `shared_admin` 소유였다 — db-init 스크립트가 실제로는 이미 고쳐져 있었는데
(role 먼저 만들고 `createdb -O`), **그 고쳐진 스크립트가 한 번도 다시 안
돌아서** 고치기 전 실행의 산출물이 그대로 남아 있었다(initdb 인자처럼
"생성 시점에만 적용"되는 부류의 함정). `ALTER DATABASE pinvi OWNER TO`로
직접 고쳤다 — DB가 비어 있어(테이블 0개) 데이터 리스크는 없었다.

**2. Map 쪽 `ktm_*` role 19개 정본과 실측이 어긋났다.** live에 21개가
있었는데 그중 `ktm_feature_api_runtime`/`ktm_feature_dagster_runtime`/
`ktm_feature_migrator` 셋은 rev 400 baseline 어디에도 없는 옛 역할 분리의
잔재였고, `ktm_feature_service`(baseline이 요구하는 19번째)는 없었다.
셋을 지우고(스크래치 DB 두 곳의 잔여 ACL만 `DROP OWNED BY`로 먼저 걷어냄)
하나를 만들어 정본과 맞췄다.

**3. PinVi 0101 migration의 fresh 경로가 요구하는 catalog-lock fence 함수가
없었다.** `pinvi_internal.acquire_fresh_0101_database_fence()`는
`pg_authid`/`pg_database`를 ACCESS EXCLUSIVE로 잠그는 SECURITY DEFINER
함수다 — scoped app role은 자기 database를 소유해도 이 catalog 잠금 권한은
가질 수 없다(catalog는 database 소유물이 아니라 cluster 전역이다). ADR-46이
이 함수를 세우던 `bootstrap-pinvi-runtime-role.sh`를 통째로 버리면서 이 한
함수도 같이 버렸는데, 나머지 아홉과 달리 이건 role 분리와 무관하게 fresh
install마다 여전히 필요했다. Manager에 `_ensure_pinvi_fresh_migration_fence`를
추가해 매 rebuild마다 다시 세운다(destructive reset이 매번
`pinvi_internal` schema를 지운다) — kor-travel-docker-manager #394.

**4. PinVi 0101 자신이 자기 migrator 권한을 스스로 거둬가고 있었다.**
`_grant_fresh_runtime_app_privileges` 직후 `_revoke_runtime_alembic_version_privileges`를
무조건 불렀는데, 단일 role 배포에서는 그 대상이 **지금 이 migration을 돌리는
바로 그 connection**이다 — alembic이 트랜잭션 끝에 내부적으로 같은 role로
`alembic_version`을 UPDATE해서 head를 기록하는데 그 직전에 자기 권한을
잘라 "permission denied for table alembic_version"으로 0100+0101 전체가
롤백됐다. legacy 다중 role 배포(managed-but-fresh, `migration_owner`/
`migrator_login`이 설정된 경우)는 여전히 필요해서 — 완전히 지웠다가
`test_0101_can_use_a_separate_nonruntime_migration_owner`가 깨져서 한 번
더 좁혔다 — 두 role이 하나도 안 설정된 진짜 단일 role 경우에만 건너뛴다
(PinVi #564).

**소스 원장(P본)에는 이미 답이 있었다.** #564의 진짜 수정은 PinVi
`origin/main`에 6주 전(8월 5일 pin 대비 9월 21일 merge)에 이미 올라 있었다
— pin이 낡아서 못 쓰고 있었을 뿐이다. `_activate_m05_migration_owner`
자체에 "ADR-46/070: 공용 control-plane은 M05 owner/migrator 분리를
완전히 버린다"는 주석과 함께 단일 role 우회 경로가 이미 있었다. 매번 막힌
자리를 직접 replay(`alembic upgrade head`를 sealed CLI 밖에서 직접
호출)로 실측하지 않았다면 이 넷 중 어느 것도 진짜 원인에 닿지 못했을
것이다 — CLI는 매번 `{"error_code":"...","phase":"..."}` 한 줄만 준다.

**끝난 상태.** pinset `fa6f624e5b06…`(map `f5703bc6…` + pinvi `b60cc8cd…`),
map schema head `400`, dagster head `29b539ebc72a`, pinvi head
`20260917_0102`, 일곱 서비스(map-api/ui/dagster/dagster-daemon,
pinvi-api/web/dagster) 전부 healthy. `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
`312_route_geometry_sidecar` → `400`으로 재구축 **후에** 바꿨다. Manager는
`#394`까지 trusted install로 반영하고 `pin rebind-execution`으로
provenance를 맞췄다.

**PR 목록.** kor-travel-docker-manager #391/#392/#393/#394, pinvi #563(선행,
과거 세션)/#564.

## 2026-09-23 (5) — prod 사이클을 돌렸고, 내 ADR-101 작업이 한 축을 빠뜨린 것을 알았다

두 PR을 머지한 뒤 전 사이클을 기동했다. 세 가지를 배웠고, 셋째가 남은 일이다.

**1. 설치본이 여섯 머지 뒤처져 있었다.** chain17은 Manager revision을 `/opt`의
설치 매니페스트에서 읽는다. 거기 있던 것은 `2dc633dd`(#381 머지 시점)로 ADR-100도
ADR-101도 없었다. 그대로 돌렸다면 옛 compose가 새 Map 이미지에서 삭제된 실행파일을
불렀을 것이다. 사용자 1회 허가를 받아 trusted installer로 `e4d4fa55`를 설치했다.

**2. `.env`에 ADR-100 자격증명 쌍이 없었다.** 재구축이 `prejournal_failure` /
stage `prebuild_snapshot`으로 죽었고 그 한 단어가 남긴 전부였다. 원인은
`KOR_TRAVEL_MAP_SERVICE_PASSWORD`와 `KOR_TRAVEL_MAP_PG_DSN` 부재 — 새 compose가
`${X:?...}`로 요구하므로 해석 단계에서 막힌 것이다.

왜 비어 있었나가 핵심이다. M05를 폐기하면서 **Manager가 `.env`에 role 자격증명을
심던 경로가 사라졌다**(`compose_service.py`의 `prewrite_admission` 주석). 그 전까지는
Manager가 넣었으므로 운영자가 신경 쓸 일이 아니었고, 사라진 뒤에도 runbook이 그
책임을 이어받지 못했다. 이제 적었다(Manager #390).

**3. 내 ADR-101 Manager 작업이 빌드 영수증 축을 빠뜨렸다.** 자격증명을 넣자
재구축이 다음 단계인 `application_builder`에서 죽었다. ADR-101은 Map에서
`scripts/build-application-300-paired-candidate.sh`를 지웠는데(ADR 문서가 명시한다)
Manager의 소비자는 그대로다. 같은 뿌리에서 `DagsterStorageCandidate`도
`paired_candidate_build_receipt_sha256`을 계속 싣는데 Map은 이제 그 필드를 받지
않는다.

내가 범위로 잡았던 (C)(D)(E)는 영수증·fence·phase 기계였고, **빌드 영수증은 다른
축인데 같은 ADR이 지운 것**이었다. 지우는 쪽(Map)과 읽는 쪽(Manager)을 파일 단위로
대조했어야 했다 — ADR 문서 17행이 지운 파일을 이미 열거하고 있었다.

prod는 더 나빠지지 않았다: 두 실패 모두 저널 전이라 후보가 해제됐고 새 pinset에
journal이 없다. 회전은 끝났으므로 재시도는 rebuild 단계부터다.

## 2026-09-23 (4) — 두 ADR을 한 사이클에 머지했다

순서가 계약이었다: **Manager 먼저**(#389 → `e4d4fa5`), 그다음 Map(#1259 →
`eb4882aa4`). Manager의 `docker-compose.yml`이 Map 이미지에서 지워진 실행파일 둘을
절대경로로 부르고 있었고, 그 자리가 fresh DB 복구 경로다 — Map만 머지하면 지금
outage의 복구 경로가 깨진 채로 남는다.

Map PR은 최신 커밋 기준 9개 체크 전부 SUCCESS였다(PostGIS 통합 포함). Manager는 두
체크 전부 SUCCESS.

합계 **−45,343줄**(Map 218 files −39,935, Manager 15 files −5,408).

**남은 것은 prod 복구 사이클 하나다.** 직전 pinset `3705983b`의 journal은
`cancel_probe_finalized`에서 영구 고착이고 탈출구는 새 커밋인데, 이 두 머지가 바로
그것이다.

## 2026-09-23 (3) — 봉인의 건너편을 접었다: 아홉 phase가 한 번의 관측으로

ADR-101이 Map에서 지운 두 실행파일의 **소비자**는 Manager였다. 그 쪽에서 무엇이
사라졌는지 세어 보니, Map에서 지운 것보다 컸다 — 13 files, −4,922줄.

**무엇이 있었는가.** Manager는 삭제된 두 one-shot이 stdout으로 뱉는 JSON 영수증을
파싱했고, 그들에게 root 소유 writer fence를 깔아 주었고, 그 과정을 아홉 개의 durable
phase(`fresh_root_plan_ready` … `application_permit_ready`)로 쪼갰다. 각 phase는
operation plan을 들고 있었고, 그 plan은 "어느 저널 세대에서 썼는가"를 sha256으로
결박했다. 중간에 죽으면 `recover` / `probe-missing` 인자로 같은 실행파일을 다시 불러
"영수증이 있는가 / 없는가"를 되물었다.

**그 전부가 한 가지를 위한 것이었다** — 영수증 파일을 안전하게 재개하기. 파일이
사라지면서 결박할 대상도 사라졌다.

**대신 들어온 것.** one-shot이 끝나면 Manager가 **자기 admin 자격으로**
`public.alembic_version`을 읽는다. 값이 후보 head와 다르면 거부하고, 같으면 저널에
`application_schema_head`로 적는다. 옛 경로에서 "스키마가 올라갔다"의 근거는 결국
"쉘 명령이 0으로 끝났다"였고, 영수증은 그 명령 자신이 쓴 것이라 독립 증거가 아니었다.

**잃지 않은 것.** "이미 끝난 것을 다시 돌리지 않는다"는 여전히 계약이다. 다만 성질이
바뀌었다 — 옛 계약은 "durable intent 이후 **절대** 재실행하지 않는다"였고, 그것은
재실행이 **위험했기 때문에** 필요했다. `alembic upgrade head`는 이미 head면 무연산이고
`runtime_privileges`는 재조정이므로 지금은 안전하다. 그래도 `application_schema_ready`
에서 재개할 때 one-shot 명령이 호출 목록에 **없어야** 한다는 단언은 남겼다. 없으면
phase 자체가 의미를 잃는다.

**두 번 밟은 사고, 둘 다 조용한 종류.**

1. `volumes:` 키만 지웠더니 그 아래 bind mount 세 줄이 앞 `command:` 목록에 흡수돼
   **Prometheus CLI 플래그로 둔갑**했다. YAML은 유효하고 `safe_load`는 통과한다.
   찾은 방법은 단언이 아니라 비교였다 — HEAD 문서와 지금 문서를 service×key로 대조해
   "prometheus.volumes: 3 → None"을 뽑았다.
2. 앵커 구간으로 헬퍼 12개를 지우며 같은 구간에 있던 `_discard_application_300_receipt`
   (빌드 영수증 — 다른 축이다)를 함께 지웠다. 클래스 안에서 메서드 하나를 지우려고 끝
   경계를 `\n\n\n`으로 잡았다가 뒤따르는 세 메서드를 함께 날린 것도 같은 형태다.
   AST로 HEAD와 최상위 이름 집합을 대조하는 검사를 따로 돌려 잡았다.

**이 저장소가 함께 바뀐 자리.** `scripts/lib/c7_prod_attestation.py`가 prod 저널을
Manager와 같은 강도로 재검증하므로 증거 모양의 사본을 들고 있었다 — 새 모양으로 옮겼다.
`scripts/run-tvn34c-n150-fresh-live-e2e.sh`는 final permit 마운트의 존재를 요구하다가
이제 부재를 요구한다.

**게이트.** Manager backend 1,947 passed (n150 CI-parity), ruff 0.16.4 clean. 남은
둘은 이 변경과 무관하다 — `test_compose_ensure_build_command`는 손대지 않은 main에서도
빨갛고, `test_canonical_compose_readiness_matches_real_runtime`은 30초 docker compose
timeout이다(직전 회차에서 같은 코드로 통과).

## 2026-09-23 (2) — 트리거 85개를 지우려다, 내 실측이 정반대로 읽힌 것을 알았다

전수조사가 187개 트리거 중 85개를 "막는 동작을 할 수 있는 principal이 없다"며 삭제
후보로 올렸다. 나는 그 근거를 카탈로그로 확인했다고 보고했다. **확인이 아니라 오독이었다.**
적대 검증이 여섯 그룹을 전부 반박했다 — 삭제 가능한 트리거는 **0개**다.

**무엇을 쟀는가.** `aclexplode`로 124개 표의 TRUNCATE grantee를 뽑았더니
`ktm_feature_schema_owner` 하나였다. 그건 그 124개 표 **전부의 소유자**다. 나는 이것을
"소유자 기본 항목이지 부여가 아니다 → 아무도 TRUNCATE를 못 한다"로 읽었다.

**정반대다.** 소유자야말로 TRUNCATE를 할 수 있는 주체이고, **소유자에게선 REVOKE가
불가능하다.** 그래서 REVOKE가 아니라 트리거를 쓴 것이다. 그리고 그 소유자는 닿을 수 있는
자리에 있다 — `docker/postgres-role-bootstrap.sh:683`이 유일한 운영 LOGIN
`ktm_feature_service`에게 `SET TRUE`를 주고, `alembic/env.py`는 **모든 마이그레이션에서**
`SET ROLE ktm_feature_schema_owner`를 켠다. revision 400 자신이 그 세션 안에서 돈다.

**증거는 CI에 이미 있었다.** `tests/integration/_db_cleanup.py`가 `_no_truncate` 트리거를
**끄고 나서** TRUNCATE를 실행하고, 그게 **성공한다.** 권한이 없다면 트리거를 꺼도 똑같이
`permission denied`로 죽어야 한다. 성공한다는 것이 곧 "principal이 TRUNCATE를 갖고 있고
트리거가 유일한 방벽"이라는 실행 가능한 증명이다. 나는 그 파일을 blast-radius 목록으로만
읽고, **그것이 답이라는 것**을 보지 못했다.

**저장소가 이미 답해 뒀다.** `tests/integration/test_tvn41s_material_fences.py:147`:
"UPDATE fence만 시험하면 나중에 TRUNCATE trigger 둘을 떨어뜨려도 `pytest -q`와
`alembic check`가 모두 초록이다(적대 리뷰 지적)." 그 테스트는 정확히 이번 삭제를 잡으려고
쓰였다. 그리고 `ENABLE ALWAYS` 다섯 줄은 `session_replication_role = replica` 한 줄로
우회하는 행위자가 **있다**는 전제 위에서만 뜻이 있다 — 아무도 못 한다면 쓸 이유가 없는
구문이다.

**교훈은 이미 쓰여 있던 것이다** — 탐지기는 효과에, 그리고 맞는 층에 결박한다. 나는
카탈로그 층(`aclexplode`)에 결박했고, 그 층은 소유자 암묵 권한도 `SET ROLE` 도달성도
superuser 우회도 **구조적으로 보지 못한다.** 효과 층(트리거를 끄면 TRUNCATE가 되는가)에
결박했다면 첫 질문에서 끝났다.

지울 것이 없다는 것은 나쁜 소식이 아니다. 이 트리거들은 과잉 구현이 아니라 소유자를
제약할 수 있는 **유일한** 수단이고, 지웠다면 `TRUNCATE feature.features CASCADE`가
거부에서 전량 삭제로 **ACL 한 글자 안 바뀐 채** 조용히 바뀌었을 것이다.

## 2026-09-23 — 열네 revision을 하나로 접고, 그 체인을 지키던 장치를 같이 걷어냈다

활성 Alembic graph가 revision **하나**가 됐다. `400_schema_baseline.py`가 head
`pg_dump`와 seed를 적용하고 `down_revision = None`이다. revision 14개와 사이드카
111개가 사라졌고, 그 체인을 감시하던 장치가 함께 사라졌다 — 266개 파일,
**-54,018 / +2,349**.

**접을 수 있었던 이유.** 긴 migration 체인이 사는 값은 하나다 — 돌고 있는 DB를 그
자리에서 앞으로 옮길 수 있다는 것. 이 저장소는 돌고 있지 않고 데이터 보존도 요구하지
않으므로 그 값에 사는 사람이 없는데, 비용은 계속 쌓였다. 같은 사실(role graph·ACL·
procedure 본문)이 열네 revision에 흩어져 어긋날 자리가 열네 군데였다.
`runtime_privileges.py`의 조건부 ACL 세 덩어리는 전부 "이 조정기가 두 스키마 상태에서
돈다"는 사정 하나에서 나왔다.

**봉인.** receipt 사슬은 `0236 → 300` 이관이 원본을 건드리지 않았음을 증명하려고
만들었다. 이관이 끝나 증명할 원본이 없고, 남은 것은 빌드 시점 해시와 배포 시점 해시가
같은지 확인하는 파일 다발이었다. 그것이 막은 사고는 없다. 막은 것은 있다 — seed의
`route.geom` 행이 312가 지운 컬럼을 가리키는데 봉인 때문에 **고칠 수 없었다.**

**permit이 지키던 성질은 세 술어로 옮겼다.** `application-schema-final-permit.py`
721줄, root 소유 mount, 서명 파일이 결국 지킨 것은 하나다 — 런타임이 자기 이미지와
다른 스키마의 DB에 붙지 않는다. 런타임 privilege preflight가 이제 그것을 잰다:
적용된 head가 이미지의 head와 같은가, `public.alembic_version`을 읽을 수 있는가,
그리고 **쓸 수는 없는가**(셋째가 없으면 스키마 대신 head를 고쳐 첫째를 통과할 수
있다). 셋을 따로따로 뒤집어 각각 빨개지는 것을 확인했다.

**사이드카는 손으로 만들지 않았다.** 빈 DB를 `313`까지 올려 두 번 떠서 같은지 본
다음 정규화했다. 정규화는 정확히 네 가지 — 매 덤프마다 바뀌는 토큰·버전 주석,
`search_path` 고정(env.py가 트랜잭션 안에서 세운다), `CREATE SCHEMA IF NOT EXISTS`,
그리고 **ACL 블록마다 소유자로 role 전환.** 마지막 것이 load-bearing이다: GRANT는
소유자만 낼 수 있고 ADR-090 role은 NOINHERIT이며, 소유자 아닌 GRANT는 오류가 아니라
경고 후 무시다 — exit 0이 적용의 증거가 되지 못한다.

같은 런에서 head 오라클도 다시 떴는데 커밋돼 있던 파일과 **바이트 동일**했다. 덤프
파이프라인이 기존 오라클을 재현한다는 확인이다.

**대상이 빈 검사 다섯.** role을 바꿔 가며 DDL을 내는 migration을 감시하는 게이트들은
덤프 하나를 적용하는 revision 앞에서 대상이 0이 된다. 하한을 낮추지 않고 — 그러면
"본 것에 하한을 건다"가 무너진다 — 이유와 함께 skip하고 두 번째 revision이 붙는 순간
다시 활성화되게 했다. `test_receipt_head_check_covers_the_graph_head.py`가 이미 쓰던
형태다.

유도형 검사 둘은 **더 나은 오라클로** 옮겼다. purge 제약 분류와 `match_basis` CHECK는
이제 migration의 중간 문자열이 아니라 head 덤프를 읽는다 — DB가 실제로 들고 있는
것에 한 칸 가깝다.

`_OPTIONAL_ROUTINES`는 비웠다. `test_db_procedure_signatures_exist_in_head.py`가
"baseline root에 없는 인벤토리 루틴: []"로 실측했기 때문이다. 이름을 남겨 두면 루틴이
**정말로** 사라지는 날 조용히 건너뛴다.

정본은 ADR-101.

## 2026-09-20 — geometry 한 컬럼이 이사했는데, 그것을 가리키던 자리가 열여섯 곳 남아 있었다

`312_route_geometry_sidecar`가 `feature.feature_routes.geom`을
`feature.feature_route_geometries`로 옮겼다(ADR-099 2단계). 컬럼 하나를 옮기는
변경인데, **그 컬럼을 가리키던 선언이 옛 자리에 얼어 있는 것**이 이 작업의 거의
전부였다. 터진 순서대로:

1. `public_features` 뷰가 컬럼을 참조해 `DROP COLUMN`이 막혔다 — 뷰 교체를 앞으로.
2. `sync_subtype_public_ready`를 스키마 소유자 창에서 바꾸려다
   `must be owner of function`. 롤이 NOINHERIT라 멤버십만으로는 안 된다.
3. 권한 조정기의 fail-close fence — 선언 없는 relation은 거부한다. 300에서도 도는
   조정기라 새 relation의 GRANT는 `to_regclass` 조건부여야 했다.
4. ORM 메타데이터 drift — 표를 만들었으면 모델도 만들어야 한다.
5. plpgsql 프로시저 **셋**이 여전히 `feature_routes.geom`에 쓴다. plpgsql 본문은
   `pg_depend`를 만들지 않아 `DROP COLUMN`이 막지 않는다 — **첫 route 적재**에서
   42703으로 죽는다(적대 리뷰가 blocker로 잡았다).
6. 새 relation에 `derive_subtype_public_ready` 트리거가 없어 `public_ready`가
   영원히 false. route가 **오류 없이** 공개 bbox에서 0건이 된다. provider 적재는
   core 3축을 바꾸는 UPDATE를 내지 않으므로 AFTER 트리거만으로는 안 채워진다.
7. 프로시저 사이드카를 `ALTER PROCEDURE`에서 잘랐는데 그 문자열이 `DO` 블록
   **안에** 있어 달러 인용이 깨졌다 — 통합 **1,096건 오류**. 달러 인용 인식
   분할기로 교체.
8. 세 프로시저는 `ktm_feature_state_procedure_owner` 소유의 SECURITY DEFINER인데
   그 롤의 geometry 권한이 옛 자리에 있었다 — `permission denied for table
   feature_route_geometries`.
9. GiST 인덱스 이름·적재 SQL·권한 단언에 결박된 검사 **여덟 자리**.
10. `test_runtime_subtype_acl_excludes_public_ready`가 없는 컬럼의 권한을 물어
    42703. 관계 이름이 SQL 파라미터 뒤에 숨어 있어 이름 검색으로는 안 보였다.
11. 내 사이드카 테스트가 COMMIT한 행을 안 치워 다른 모듈 셋의 "빈 기준선" 전제를
    깼다(`test_status_repo`, `test_sibling_dedup`).
12. `current_theme_candidate_snapshot`도 `to_jsonb(route)`를 읽는다 — 봉인만
    메우면 `candidate_input_hash`가 geometry 변경을 **조용히** 못 본다.
13. 그 함수가 SECURITY DEFINER로 도는 `ktm_curation_command_owner`의 SELECT.
14. override field-path 레지스트리가 없는 컬럼을 가리키고 CHECK가 새 relation을
    금지. 같은 CHECK를 ORM도 선언하고 있어 한 쪽만 넓히니 카탈로그 대조가 잡았다.
15. 무결성 관측 두 축이 새 relation을 안 셌다. `geom NOT NULL`이 COMMIT 시점
    DEFERRABLE FK로 약해졌으므로 복구 세션이 그 창을 지난다.
16. head 오라클이 낡아, 그것을 정본으로 읽는 lint **열한 개**가 "루틴이
    `feature_routes.geom`을 쓴다"는 없는 세계를 보고 있었다.

**그래서 이름을 옮기는 대신 모델에서 유도하게 바꿨다.**
`GEOMETRY_RELATIONS`/`EXTERNAL_GEOMETRY_KINDS`가 단일 정본이고, 검사·관측·권한·
파라미터가 거기서 나온다. 다음 이사(area)는 dict 값 하나를 바꾸는 일이어야 한다.

### 고치려다 배포 허가 사슬에 부딪힌 것 하나

override field-path 레지스트리를 새 relation으로 옮겼더니 `application_300_fresh_*`
두 건이 **결정적으로** 깨졌다 — `fresh finalize seed receipt does not match
baseline`. `ops.feature_override_field_paths`의 전 행이 rev 300 seed 영수증으로
봉인돼 있고 배포 허가 사슬 셋이 그 해시를 게이트로 쓴다. `target_relation`은 그
해시에 들어가는 컬럼이다.

catalog 쪽은 `_sealed_destination_catalog`가 같은 문제를 이미 겪고 "head 너머에서는
봉인값이 기대값이 아니다"로 풀어 두었는데, seed 쪽에는 그 처리가 없다. 봉인을 다시
뜨려면 살아 있는 0236 컨테이너가 필요하고 그건 막혀 있다.

`minor` 발견 하나 때문에 배포 허가 사슬을 재설계하는 것은 맞바꿈이 나쁘다. 되돌리고
`T-VN-SEED-RECEIPT-HEADAWARE`로 등록했다. 다만 간극을 **예외 목록이 아니라 단언으로**
못 박았다 — 봉인이 풀려 레지스트리를 옮길 수 있게 되면 그 검사가 먼저 빨개진다.
예외는 조용히 늘어나지만 단언은 조용히 늘어나지 않는다.

### 검사도 같은 병을 앓고 있었다

역할 창 lint 셋이 전부 `_migration("309")`에 결박돼 312의 창 넷을 한 문장도 보지
않았고, 롤 유지 lint는 AST만 봐서 312를 **3문장**으로 읽었다(실제 42문장). 둘 다
번호·형태 대신 "있는 것 전부"를 보게 넓혔다.

넓히니 302·304가 거짓 양성으로 올라왔다 — **소유자는 문장열 위에서 움직인다.**
새 `CREATE`는 만든 롤을 소유자로 만들고, `SET ROLE` 이전 구간은 관리 롤로 돈다.
그 모델을 옮겨 적으니 예외 목록 없이 정확해졌다.

그리고 돌연변이 실험이 하나를 더 찾았다 — 롤 유지 lint가 **주석 붙은 `SET ROLE`을
못 봤다.** 문장 분할기는 `;`만 보고 자르므로 주석이 문장 앞에 붙어 오고, 사이드카의
**여는** 창은 거의 언제나 설명 블록 뒤에 온다. 검사는 닫는 쪽만 보고 있었다.
이웃 모듈은 같은 함정을 `_sql_head`로 이미 막고 있었는데, 그 교훈이 옆 파일로
건너오지 않았다.

## 2026-09-19 (4) — 등산로가 한 번도 성공한 적 없는 이유는 봉인의 크기 천장이었다

`feature_route_krforest_mountain_trails_job`이 **4시간18분** 지오코딩을 마치고
적재/봉인에서 죽었다. `ProgramLimitExceededError: total size of jsonb array
elements exceeds the maximum of 268435455 bytes`.

적재와 봉인이 같은 트랜잭션이고 봉인이 마지막이라 57,060행이 통째로 롤백된다.
`mountain_trail_segment`가 0행인 이유가 이것이다 — **한 번도 성공한 적이 없다.**
재시도는 같은 자리에서 죽으며 매번 4시간을 다시 쓴다. 2차 시도를 종료시켰다.

**진단을 두 번 했고 첫 번째가 틀렸다.** 처음에 나는 이 job의 정체를 "geo가 느려서
timeout"으로 읽고 재시도·동시성을 설계하려 했다. 적대 리뷰가 전제를 의심했고 다시
재니 geo는 p50 86ms로 답하고 있었고 5시간 동안 포화 신호를 한 건도 내지 않았다.
죽인 것은 호스트의 I/O 포화(`/proc/pressure/io` full 25%)였고, 그 원인의 일부는
내가 job 7개를 동시에 띄운 것이었다. 그것과 별개로, **끝까지 간 run은 봉인에서
죽었다** — 두 결함이 겹쳐 있었다.

**geometry가 route payload의 98.5%다.** 43 kB 중 나머지가 633 B다. 그래서 소유자
지시(별도 PostGIS 보조테이블)는 정확히 옳은 방향이다. 그런데 같은 함수가 place에도
돈다 — 323 B × MOIS 980,970행 = **302 MB로 geometry 없이도 초과**다. 즉 geometry를
어디로 옮기든 **fold 자체가** 다음 큰 dataset에서 같은 벽에 닿는다.

그래서 순서를 뒤집었다. **봉인 먼저(311), geometry 분리 다음(312).**

311은 배열 **원소의 정의를 한 글자도 바꾸지 않고** 접는 방식만 바꾼다. `jsonb_agg`
하나로 전 행을 모으는 대신 행마다 32바이트 digest를 만들어 정렬 집계한다.
`canonical_input` CTE를 손으로 옮기지 않고 **정본에서 추출해 조립한 뒤 41줄이
바이트 단위로 동일함을 프로그램으로 대조**했다 — head-schema diff에 CTE가 아예
나타나지 않는 것이 그 독립 증거다. 탐지 범위가 1비트도 줄지 않는다.

**해시 값은 달라지므로 세대를 남긴다.** 두 비교 지점은 같은 run의 receipt만
재대조하므로 게이팅은 안전하고, 투입 시점에 진행 중 curation root가 0건임을
실측했다. 그러나 이미 저장된 receipt는 이후 영원히 재계산되지 않는다 — 세대가
없으면 **"공식이 바뀌었다"와 "값이 변조됐다"가 같은 관측으로 보인다.**

**검사는 효과에 걸었다.** 256 MB 데이터를 만들 수 없으니 천장이 *생기는 원인*을
잰다 — 행수는 같고 payload만 1,000배 다른 입력에서 중간 집계 길이가 같은가
(`행수 × 32 B` 고정). 옛 fold가 실제로 100배 넘게 자라는 것을 같은 자리에서
대조군으로 증명해 항진명제가 아님을 보인다.

**게이트 구멍도 하나 닫았다.** 이날 나는 n150에서 `tests/unit tests/lint`만 돌리고
`packages/kor-travel-map-dagster/tests`를 빼먹었다 — Map CI는 그것을 별도 세션으로
돌린다. 그 구멍으로 세 검사가 CI에서 처음 빨개졌고, 메모리에는 그 다섯 세션이
이미 적혀 있었다. 규약이 있어도 따르지 않으면 없는 것과 같다.

## 2026-09-19 (3) — 0행의 이유를 끝까지 따라가니 결함이 둘이었다

`feature.feature_notices`가 저장소 전체에 0행인 것의 원인을 prod에서 따라갔다.
가설은 맞았고, 그 뒤에 **더 나쁜 것**이 있었다.

**가설이 실측이 됐다.** 산사태 feed의 유일한 위치 단서 `ocrnFrcstIssuInsttNm`을
10,562건 전수로 재 보니 97%가 `충청남도 당진시`처럼 시도+시군구, 0.6%가 시도만,
0.1%가 `경기도 산림환경연구소`, 1.5%가 빈 값이었다. **98.5%가 행정구역을 말한다.**
그런데 변환이 모든 notice에 `coord=None`과 빈 `Address()`를 박아 그것을 버렸다.
`_provider_address`가 `None`이 되니 적재기가 "단서 없음"으로 전량을 떨궜다.

값은 자르지 않고 그대로 `Address.admin`에 넣는다. 좌표 없는 row의 주소 단서를
`admin`에 남기는 것은 이 저장소의 기존 관례이고(`providers/mcst.py`), 검증층의
`_provider_address`가 바로 그것을 읽으려고 `road`→`legal`→`admin`을 본다.

**더 나쁜 것: 데이터셋이 통째로 사라져도 job은 SUCCESS였다.** 상류 10,467건을
받아 10,467건을 전부 버리고 notice feature 0건으로 끝났는데 결과는 초록이었다.
`strict_address`가 prod에서 `drop`이고, 그 모드는 "대부분 멀쩡한데 몇 개가 나쁘다"를
전제로 하는데 **전제가 깨진 것을 아무도 세지 않았다.** error 심각도 위반 10,467건이
`ops.data_integrity_violations`에 `open`으로 쌓여 있었고 그것을 읽는 admin 화면도
있었다. **기록은 읽히지 않으면 없는 것과 같다.**

그래서 적재율 하한을 뒀다 — 버린 것이 남긴 것보다 많으면 적재하지 않고 죽는다.
0.5는 측정값이 아니라 의미의 경계이고, 그 사실을 코드에 적었다. 다만 측정과의
거리도 적었다: 같은 날 landslide를 뺀 모든 dataset의 error 탈락률은 0%, landslide도
주소를 살리면 1.5%다. 하한은 정상값의 33배 위에 있다.

이 하한이 막는 것은 소실만이 아니다. drop은 탈락 bundle을
`retire_absent_from_snapshot=True` 적재 **앞에서** 제거하므로, 일시적 장애로 떨어진
행의 **기존 feature가 은퇴**한다. 은퇴는 다음 run의 멱등 upsert로 돌아오지 않는다.

**두 경로에 걸었다.** 적재 경로가 materialize와 chunked stream 둘인데, 이 저장소가
반복해 다친 모양이 "선언을 바꿨는데 그 선언을 얼려 둔 자리를 같이 못 봤다"이다.
chunked 쪽은 batch를 다 흘린 뒤, 그러나 loader가 commit하기 **전에** 던진다.

**죽기 전에 증거를 남기는 계약이 strict 경로에만 있었다.** 그 블록을
`_fail_before_load`로 빼서 하한도 같은 경로를 쓰게 했다. 따로 뒀으면 나중에 생긴
쪽이 기록을 빠뜨린 채 던지기 쉽고, 그 결과는 이유를 모르는 빨간 run이다.

**변이 다섯 가지로 검사가 실제로 빨개지는 것을 확인했다.** 그중 처음 만든 하나는
빨개지지 않았는데, 검사가 항진명제여서가 아니라 변이가 엉뚱한 호출부(strict 경로)를
건드렸기 때문이었다 — 변이를 못 믿으면 "빨갛게 만들어 봤다"도 못 믿는다.

## 2026-09-19 (2) — 적대 리뷰가 내 수정 안에서 같은 모양을 셋 더 찾았다

전문 리뷰어 2인이 다각도로 보고, 발견마다 반증 검증을 붙였다(에이전트 24, 반증
성공 2건). **확정된 것 15건 중 셋이 이 PR이 스스로 막겠다고 선언한 모양이었다.**

**키가 경로에 있으면 예외 메시지가 그것을 나른다.** 서울 열린데이터광장은 인증키를
URL 경로에 받는다. 나는 본문을 예외에 싣지 않도록 신경 썼는데, 그 사이에 낀
`response.raise_for_status()` 한 줄이 URL 전체를 담은 `httpx.HTTPStatusError`를
던진다. 그 메시지는 Dagster step-failure 이벤트와 compute log에 영속 기록되고,
큐 경로는 `from exc`로 체인까지 보존한다. **형제 라이브러리는 이미 그것을 막고
있었다** — `python-datagokr-api`가 `copy_remove_param("serviceKey") + from None`을
쓴다. 이론적 지적이 아니라 확립된 규범에서의 회귀였다.

그리고 그것을 막는다고 이름 붙인 검사가 **그 가지를 한 번도 지나지 않았다.**
테스트 대역의 `raise_for_status`가 무조건 `None`을 돌려줬기 때문이다. 이 저장소가
반복해 다친 "탐지기가 항진명제" 그대로다 — 좌표 축 검사와 INFO-200 종료 검사도
같은 부류였다(전자는 `_validated_lonlat`의 bbox 자동 스왑이 되돌려 주고, 후자는
첫 페이지에서 이미 끝나 두 번째 응답을 소비하지 않는다).

**`if secret is None`은 배포 형상에서 한 번도 발화하지 않는다.** compose가
자격증명을 `${X:-}`로 배선하므로 변수는 **항상 정의되고 값이 빈 문자열**이다.
pydantic은 그것을 `SecretStr("")`로 받고, 모든 provider fetcher의 None 가드가
지나간다. 키 없는 스택이 빠른 실패 대신 무인증 상류 호출을 낸다 — OpiNet처럼
run당 예산이 있는 provider에서는 그 예산만큼 헛돈다. `env_ignore_empty=True`.

**하루 300회 보장이 재시도를 세지 않았다.** Dagster의 step 재시도는 asset을
처음부터 다시 실행하고, 그 실행이 run 예산을 **전부 다시 쓴다**. 공통 정책
(`max_retries=3`)이면 한 job이 최악 네 번 돌아 560회다. 기본 모드를 켠 것이
이 잠복을 실효로 만들었다. OpiNet asset 전용 `max_retries=0`을 두고, 검사는
배수를 리터럴이 아니라 **실제 정책에서 유도**한다 — 누군가 재시도를 되살리면
예산 검사가 함께 빨개진다.

**두 번은 리뷰어가 틀렸다.** (1) "자연키가 바뀌어 기존 서울 책방 feature가 전량
고아가 된다"는 2인이 high/critical로 올렸지만, prod에서 이 dataset의
`source_entities`가 **0건**이다(직접 조회). 적재된 적이 없어 충돌 대상이 없다.
(2) "경고 기준을 `min(ceiling, absolute_ceiling)`으로"는 그렇게 하면 항진명제가
된다 — `ceiling`이 바로 위에서 `needed × 2 + 1`로 유도된 값이다. 반증 검증이
(1)을 잡았고 (2)는 내가 구현하다 잡았다.

**문서도 같은 자리에서 낡아 있었다.** `opinet-place-price-etl.md`는 이 모드의
운영 정본인데 1,500/600/180을 그대로 들고 있었고, `feature.curated_sources`의
서울 책방 행은 죽은 URL과 **뜻이 뒤집힌** freshness_note("서울 열린데이터광장
원천 서비스 종료 안내 노출" — 옮겨 간 바로 그 포털이다)를 들고 있었다. admin
UI와 공개 curation API가 읽는 값이라 마이그레이션 310으로 고쳤다.

**남긴 것 하나.** MCST 부분 실패 run에서 **적재에 성공한 dataset의 membership이
완료 처리되지 않는다** — `raise Failure`가 완료 콜백보다 앞에 있고, 콜백 계약이
exact full snapshot을 요구한다. 증거 원장과 DB 상태가 어긋나지만 큐 경로에는
도달하지 않고(scope당 slug 1개), 이번 변경의 회귀도 아니다(종전에는 13개가
전멸했다). 부분 완료를 표현하려면 두 결박을 함께 풀어야 해 별건으로 둔다.

## 2026-09-19 — 핀을 올리지 않으면 고친 적이 없는 것과 같다

prod에서 32개 provider job을 한 번에 돌려 실패를 전수로 확정한 뒤, 그 원인들을 각각
닫는 작업이다. 이번 묶음이 고친 것은 **네 가지 모두 "선언은 바꿨는데 그 선언을 얼려
둔 자리를 같이 못 봤다"**는 한 가지 모양이다.

**provider 핀.** `python-krforest-api`(표준데이터 gateway가 `{header, body}` 래퍼를
벗어 산림 표준데이터 3종이 파싱에서 전멸)와 `python-mcst-api`(아동서점 CSV 원천이
fileDataNo 282 → 484로 이동) 양쪽 수정을 머지했는데, **이 저장소의 핀을 올리지 않으면
적재는 여전히 0건이다.** 표면 manifest도 함께 재생성했다 — 생성물이라 손으로 고치지
않는다.

**OpiNet은 선택자를 넘기는 것으로 끝나지 않았다.** 기본값이 `disabled`면 배포가
끝나도 적재가 시작되지 않아 운영자가 호스트 `.env`를 손으로 고쳐야 한다. 그 손 편집이
prod와 문서를 어긋나게 만든 자리다. 기본 모드를 `low_top_area`로 두고, compose가 아예
넘기지 않던 호출량 노브 둘도 함께 배선했다. 그리고 **`.env.example`에는 한도를 300으로
정정하기 전의 180/600이 그대로 남아 있었다** — 그 파일을 복사해 쓰면 고친 기본값을
덮고 첫날에 한도를 넘긴다. 검사는 리터럴이 아니라 "최악의 날(매월 1일, price+place)
호출이 무료키 하루를 넘지 않는다"에 결박했다.

**서울 책방은 활용신청으로 되살릴 수 있는 종류가 아니었다.** odcloud가 404
`등록되지 않은 서비스 입니다`를 주는데, 날조한 데이터셋 번호와 **같은 응답**이고
swagger 네임스페이스도 404다. 원천을 서울 열린데이터광장 OA-21062
(`TbSlibBookstoreInfo`)로 옮기고 라이브로 606건을 확인했다. dataset_key와 provider
이름은 **레지스트리 신원**이라 바꾸지 않았다 — provider_dataset row, operation key,
봉인된 300 카탈로그가 전부 그 이름을 쥐고 있다. 바뀐 것은 원천뿐이고 분기는
`_FILE_DATA_SOURCE_OVERRIDES` 한 줄이다. 분기를 fetcher 안에 둔 이유는 호출자가
둘(Dagster resource + feature-update worker)이라 한쪽에만 넣으면 큐로 도는 prod만 죽은
원천을 계속 부르기 때문이다.

이 포털의 함정을 검사로 못박았다. **오류도 HTTP 200으로 주고**, json을 요청해도
인증 실패는 XML로 오며, 범위를 넘기면 서비스 봉투 없이 `RESULT.CODE=INFO-200`만 온다.
그리고 **`XCNTS`가 위도, `YDNTS`가 경도다** — X를 경도로 읽는 통념대로 일반 키 목록에
넣으면 조용히 뒤집힌다.

**MCST asset은 시도하지 않은 dataset까지 적재하고 있었다.** feature-update worker는
fetcher를 slug 하나로 좁혀 부르는데(`_mcst_resources`) asset은 13개를 다 돌았다 —
나머지 12개가 **시도한 적도 없이** 빈 authoritative 적재와 sync-success를 받았다.
처음 적었던 근거("빈 스냅샷이 기존 feature를 전부 은퇴시킨다")는 **틀렸다**: 이
provider는 `retire_absent_from_snapshot`을 넘기지 않는다. 실제 해악은 은퇴가 아니라
**위장**이다 — sync cursor가 전진해 수집 실패가 신선한 성공으로 보이고, curation seal이
관측한 적 없는 집합을 권위로 봉인한다.

**산사태는 상한을 올리는 것으로 닫지 않았다.** 10,562건으로 자라 상한 10장을 먹은
사고에서 상한은 제 일을 했지만(조용한 절단 대신 시끄러운 실패) 그 신호는 job이 죽은
뒤의 신호였다. 발령마다 행이 쌓이는 append-only 피드라 다음 dataset도 같은 길을 간다.
그래서 **여유가 절반 아래로 내려오는 순간 prod가 먼저 말하게** 했다 — 그 지점은 CI
검사가 요구하는 여유(2배)와 같은 자리다. 경고 문구는 "상한을 올려라"가 아니라
"증분 수집으로 바꿀 때인지 보라"다. 증분 전환 자체는 별건이다 — 이 asset은
`load_authoritative_notice_snapshot`으로 `active_lineage_keys` 전체를 대조하므로,
부분 수집으로 바꾸면 화해 계약부터 다시 설계해야 한다.

## 2026-09-16 (3) — 조문이 열려 있는 동안 같은 사고가 세 DB에서 재발했다

`T-VN-H49-BACKUP-STALENESS` 조문 1을 설계하려고 실측하다 **진행 중인 두 번째 사고**를
찾았다. `geo_dagster`·`concierge`·`pinvi` standalone 백업이 **09-12부터 5일째**
`Permission denied`로 실패 중이었다:

```
[2026-09-11T03:15:05Z] [standalone-backup:geo_dagster] done      ← 마지막 성공
/bin/sh: 1: .../run-standalone-backup.sh: Permission denied      ← 이후 전부
```

crontab은 경로를 직접 실행하는데 그 파일이 실행 불가였다(전부
`-rw-rw-r--`). 실행 비트를 세우고 미등록 role
탐침으로 확인했다(`EXIT=2` — 덤프도 GC도 일으키지 않는 경로). 다음 cron부터 실제
백업이 나온다.

**조문 하나가 "아직 아니다"로 열려 있는 동안 같은 형태가 세 DB에서 조용히 재발했다.**
이보다 그 조문의 값을 잘 보여주는 것은 없다.

**근본 원인은 "경보가 없다"보다 앞이었다.** Manager 저장소 어디에도 백업 주기를
선언한 것이 없다 — 기대치가 오직 crontab에만 있고 저장소의 어떤 코드도 crontab을 읽지
않는다. 선언되지 않은 것의 부재는 원리적으로 탐지할 수 없다. 그래서 감시자보다
기대치 모델이 먼저다.

원장의 틀린 문장도 고쳤다: 조문 1의 "(a) api 컨테이너만 마운트한다"는 사실이 아니다 —
**api·dagster 둘 다** `backup_root`가 마운트도 env도 없고, Dagster op의 config schema엔
그 키 자체가 없다. 자동으로 기록되는 F9 행은 **예외 없이 `observed=false`**다.

알림 경로 자체는 소유자 지시로 보류했다. 설계(조사 4 + 안 3 + 채점)는 소유권을
Manager로 이관하고 채널은 ntfy로 확정했으며, 기대치 모델 초안이 그 저장소에 미커밋으로
있다. 재개 시 첫 일은 **채널 실배달 1건의 육안 확인**이다.

## 2026-09-16 (2) — 한 번도 돌지 않았던 spec을 돌렸다

`T-VN-M02`의 마지막 조문은 "live acceptance spec이 격리 스택에서 완주한다" 하나였다.
live301(api `13711` · web `13712` · dagster `13714`)에서 `E2E_MANUAL_CREATE_WRITE=1`로
**2 passed (47.9s)**. 그리고 검사가 초록인 것과 DB가 그렇게 된 것은 다른 사실이라 따로
셌다 — `feature.features` 1 → 2, origin에 `manual_admin` · `e2e-admin` ·
`ktm_feature_api_runtime` · `ktm_manual_feature_procedure_owner` ·
`admin-ui-bff.manual-feature-create.v1`. 로그인한 주체가 BFF를 지나 SECURITY DEFINER
경계 너머 provenance까지 실려 온다는 것이 이 절이 요구한 계약이다.

**이 spec은 한 번도 실행된 적이 없었다.** 오늘 아침 actor 리터럴 결함을 찾은 것도
실행이 아니라 체인을 읽어서였다 — 즉 통과한다는 것이 알려져 있지 않았다. 그래서 이
조문의 값은 "M02를 닫았다"가 아니라 **"이제 그 spec이 실제 게이트가 됐다"**에 있다.

**원장이 또 낡아 있었다.** 2026-09-08 기록은 "컨테이너도 볼륨도 없다, 재구축이
선행이다"였는데 `ktm-live-301-pg`는 5일째 떠 있었고 체크아웃에 spec도 있었으며 앱 DB
head는 `309`로 저장소와 같았다. 실제로 막던 것은 둘이다: 체크아웃을 옮기면 사라지는
`scripts/*.sh` 실행권한, 그리고 **Dagster 메타DB 통째 부재**(`kor_travel_map_dagster`
롤·DB를 만들고 `dagster instance migrate`까지 해야 런처 사전검증을 지난다 — spec은
Dagster를 쓰지 않지만 `run-admin-stack.sh`에 건너뛰기 경로가 없다).

**그리고 같은 것을 한 번 더 찾았다.** `T-VN-LEDGER-ARCHIVE` 조문 2·3도 #1239가 이미
넣은 것이었는데 표기만 열려 있었다. 오늘 원장이 다시 220 KiB를 넘어 그 도구를 실전에서
썼고 — 닫힌 절 둘을 다중집합 보존 검산 뒤에만 옮기고, 넷을 이유와 함께 거절하고,
삭제 게이트가 아카이브 미커밋 상태를 `T-VN-39-DEPLOY#1~#4`로 잡아냈다 — 코드가 있다는
것보다 강한 근거가 생긴 김에 닫았다.

**오늘 하루에 네 번이다.** `T-VN-D2-RESIDUE`(나흘) · `T-VN-DAGSTER-STORAGE` 조문 1
(배포가 증거를 지움) · `T-VN-M02`(여드레) · `T-VN-LEDGER-ARCHIVE`(사흘). 넷 다 **일이
남아서가 아니라 기록이 따라가지 않아서** 열려 있었고, 그동안 "막혀 있다"로 읽혔다.
`docs/tasks-rule.md` §6이 이 형태를 다루지만 규약만으로는 부족하다 — 조문을 닫는 PR이
그 조문을 실제로 닫는지 보는 장치가 없다. 다음에 만들 것이 있다면 그것이다.

## 2026-09-16 — seal ACL을 닫았고, prod가 배포마다 새로 태어난다는 것을 알았다

`T-VN-CURATION-SEAL-ACL` 세 조문을 닫았다(#1239 머지 후 별도 PR). 조문 2는 코드를
읽어 이미 들어가 있었고 조문 1은 2026-09-12 기록이 있었는데, **그 기록의 근거를 다시
재려다 prod DB가 배포 때 새로 만들어진다는 것을 알았다** — `kor_travel_map` 생성
시각이 t44a 배포 시각(2026-09-15 12:29:55Z)이고, 조회 시점 `feature.features` 0행 ·
`source_entities` 0행 · seal 영수증 0건 · Dagster run 897건은 전부 분 단위 날씨
스케줄(배포 후 15시간치)이었다. **`[x]`는 붙어 있는데 그것을 뒷받침하는 관측은 없는
상태였다.**

그래서 현 세대에 `feature_place_standard_museums_job`을 정식 경로로 다시 제출했다.
run `0f70d0d5` `SUCCESS`, `features 1047 · source_entities 1047 · **seal 영수증 1건**`.
영수증은 적재가 seal 함수에서 해시를 받아온 뒤에만 쓰이므로 — 그리고
`finish_provider_feature_membership_command`가 영수증 유무와
`authoritative_snapshot_complete`가 어긋나면 거절하므로 — "EXECUTE가 목록에 있다"가
아니라 **"적재가 그 함수를 실제로 실행했다"**의 증거다. 같은 실행으로
`T-VN-DAGSTER-STORAGE` 조문 1도 현 세대에서 다시 섰다.

조문 3에는 **실 login으로 적재 경로를 태우는** 회귀를 추가했다. 있던 검사 둘 다 조문이
거부하는 모양이었다 — 하나는 migrator가 카탈로그 술어를 묻고, 다른 하나는 실 login으로
접속하지만 그 목록에 seal 함수가 없다. 변이로 차이를 보였다: EXECUTE는 두고 호출부가
함께 거는 표 SELECT만 걷으면 **옛 검사는 초록이고 새 검사만 빨갛다.**

배포가 DB를 새로 만든다는 사실은 특정 task가 아니라 **조문을 쓰는 방식**의 문제라
`docs/tasks-rule.md` §6에 적었다. 전수 확인 결과 실제로 근거를 잃은 조문은
`T-VN-DAGSTER-STORAGE` 조문 1 **하나**였다(prod 실측 근거 4건 중).

그리고 **CI가 잡고 n150 네 세션 게이트가 못 잡은 것**이 하나 있었다 —
`consistency.py`의 `sample_ids=()`(선언은 `list[str]`). 게이트는 전부 pytest이고
mypy가 없다. dataclass는 런타임에 타입을 강제하지 않아 F9 검사 39건이 전부 초록인 채로
통과했다.

## 2026-09-15 — t44a 배포: async 이관이 prod에서 도는 것을 읽었다

`#1235`(provider 13개 async-only)를 `e9b877b39`로 핀했다. 전 사이클 GREEN — 회전
(pinset `bbb330689e38`) · rebuild `phase=committed` · executor 이미지 · repin
**VERIFIER PASS** · M01 ACL **55/55** · **D1 live Playwright 11 passed** · lane 정리 ·
D2 `phase=passed`(`recovery_attempt=0`).

D2의 `host_attestation_sha256`이 repin 단계의 값(`c564e786…`)과 **같다** — 검증된 그
이미지가 그대로 돌았다는 뜻이다.

**배포가 초록인 것과 고친 것이 그 안에 있는 것은 다른 사실이다.** 그래서 이번에도
prod 컨테이너에서 직접 읽었다. **버전 문자열로는 판별되지 않았다** — provider 13개가
전부 `0.1.0`이라 핀이 바뀌었는지 알 수 없다. 그래서 **코드의 성질**을 물었다:

| 무엇 | prod 실측 |
|---|---|
| `krex.DEFAULT_MAX_RPS` / 버킷 capacity | **5.0 / 1.0**(버스트 없음) |
| `KrexClient.close` 존재 | **False** — 동기 표면이 사라졌다 |
| `restarea.list_all`·`aclose`·`mois.sync_localdata_source_db`·`kma forecast.now`·`airkorea.stations` | **전부 coroutine** |
| fetcher 32개 | **async generator 31** + `fetch_mois_license_records` 1(로컬 SQLite라 동기가 맞다) |
| `PROVIDER_RATE_GATES` | `{'krex': 0.2}` — 교대 간격 1/5초 |
| gate 선언 operation | **4건**(krex place·price·weather·notice) |
| gate가 `__call__`에 있나 / 계수기보다 바깥인가 | **True / True** |
| 큐가 건너뛰는 operation | **6**(종전 값 유지) |
| opinet 예산 | **140 / 90**(종전 값 유지) |

`T-VN-KREX-TPS-FANOUT` 조문 4가 이것으로 닫힌다 — **gate가 prod 실행 경계에 실제로
있다.** 조문 3(`provider_refresh_policies.max_concurrent` 집행)은 그대로 열려 있다.


## 2026-09-15 — provider 13개가 async-only가 됐고, 낡은 대역이 세 번 계약 파손을 가렸다

형제 `python-*-api` **13개 전부**가 native async only + 공유 TPS 제어로 재작성됐다.
동기 HTTP bridge·`Async*` 별칭·`aio()`가 사라졌고 모든 네트워크 메서드가 코루틴,
정리는 `aclose()`다. 핀을 올리고 Map을 맞췄다.

**어제 만든 krex TPS 브랜치는 upstream에 흡수됐다.** 새 라이브러리가 그 기본값
(`max_rps=5.0`, `capacity=1` — 버스트 없음)과 검증(`NaN`/`inf`/`bool` 거절)을 그대로
갖고 있다. 실측 확인: 8건 동시 최소 간격 0.2004초, 최악 1초 창 5건. 루프 결박 문제는
**async-only로 가면서 원인 자체가 사라졌다**(`_run_sync`가 없어졌다). 머지하지 않고
접는다 — 남길 것은 코드가 아니라 그 판에서 배운 것이다.

**반대로 Map 쪽 `provider_rate_gate`는 살아남는다.** 새 `rate_limiter=` 주입은 한
이벤트 루프 안에서만 성립하고, Map의 fan-out은 프로세스를 가로지른다.

### 내가 틀린 곳 하나

`kma_weather.py`를 "로컬 헬퍼만 쓰니 무변경"이라고 단정했다 — **grep 결과 앞부분만
보고** 그랬다. 실제로는 결함이 셋이었다:

1. `forecast.now/short/vilage`를 `await` 없이 호출.
2. 코루틴 함수를 `retry_upstream_async`에 넘김 — 그 함수는 `return call()`이라 코루틴
   **객체**를 돌려주고 **그 안의 예외를 재시도가 한 번도 보지 못한다.** 재시도가 사라진
   줄도 모르게 사라진다.
3. 정리가 `close`를 찾는데 실물엔 `aclose`뿐 — 가드가 조용히 통과해 세션이 샜다.

같은 3번 모양이 `feature_update_runner._close_method`에도 있었다. 같은 client의
schedule 경로는 고쳐졌는데 direct/admin 경로만 남아 있었다.

### 낡은 대역이 계약 파손을 가린 세 자리

소스만 바꾸면 40곳이 `TypeError`로 죽는다. 그건 시끄러워서 낫다. **문제는 조용히
통과하는 자리다.**

| 자리 | 무엇이 가려졌나 |
|---|---|
| krheritage | `await`를 빼도 초록 — 250건이 코루틴 객체로 나가는데 단언이 **개수만** 봤다 |
| opinet | fake의 `**_kwargs`가 kwarg 이름 변경을 삼켰다. 실물은 `TypeError` 뒤 조용히 기본 반경 5000m로 떨어질 자리 |
| mcst | 상한이 1이라 row 수 == slug 수 — "slug당 1건"과 "row당 1건"이 같은 수였다 |

**필수 인자만으로는 부족하다** — 기본값이 있는 인자일수록 구멍이 넓다. 셋 다 변이로
빨강을 확인하고 닫았다.

### drift 하나를 더 닫았다

gate의 교대 간격(`1/5`초)과 라이브러리의 `DEFAULT_MAX_RPS`(5)가 서로를 모른 채 각자
`5`를 들고 있었다. Map은 `max_rps`를 넘기지 않으므로 **라이브러리 기본값에 의존한다** —
그쪽이 바뀌면 gate가 조용히 틀린 값이 된다. 형제 소스를 AST로 읽어 둘을 결박했고,
**양쪽 변이**(gate만 바꾸기 / 라이브러리만 바꾸기)로 잡히는 것을 확인했다.

### 판정은 격리가 아니라 기준선으로

dagster 세션 **680 passed / 10 failed**. 같은 하네스로 HEAD를 돌리니 **675 passed /
같은 10 failed** — 실패 집합이 바이트 단위로 동일하고 통과만 5건 늘었다. 남은 10건은
dagster 버전 환경 문제다.


## 2026-09-14 — 분모가 없는 provider를 분모 없이 막았다 (krex TPS 5)

`krex`의 일일 한도는 포털 네 면 어디에도 없었고 남은 길은 문의였다. **기다리는 대신
축을 바꿨다** — 이 provider에서 실제로 조일 수 있는 것은 하루 총량이 아니라 간격이다.
`python-krex-api` `feat/http-tps-limit`이 `KrexHttp`에 token bucket을 넣어 **초당
5건**을 넘기지 않는다(`max_rps` 기본 `5.0`).

**세 번, 그냥 두면 틀렸을 자리가 있었다.**

1. **처음 만든 것은 5 TPS가 아니라 10 TPS였다.** capacity를 `max_rps`로 두면 가득 찬
   버킷에서 5건이 즉시 나가고 그 초에 지속분 5건이 더해진다. 테스트가 창의 **시작점**만
   보고 있어서 초록이었다 — 어느 1초 창이든 보게 고치니 빨개졌다. capacity=1로 낮췄다.
2. **락이 아무것도 막지 않고 있었다.** `asyncio.Lock`을 썼는데 `_run_sync`는 호출마다
   새 이벤트 루프를 만들고 러닝 루프가 있으면 **별도 스레드**에서 돈다. asyncio 락은
   스레드를 전혀 막지 못하면서 막는 것처럼 읽히고, 경합하면 처음 본 루프에 묶여 다음
   루프에서 `RuntimeError`를 낸다(3.14에서 재현 확인). 임계구역 안에서 await하지
   않으므로 `threading.Lock`으로 바꿨다. **동시 호출에서 상한이 지켜지던 것은 락 덕이
   아니라 GIL 덕이었다** — 재는 것과 지켜지는 것이 달랐다.
3. **`KrexClient`가 `max_rps`를 넘기지 않았다.** 버킷이 transport에만 있어서, client만
   쓰는 호출자는 더 낮춰야 할 때 낮출 방법이 없었다. 두 facade 모두에 넣었다.

검사기는 **일곱 변이**로 확인했다 — 상한 끄기 / capacity 되살리기 / 기본값 바꾸기 /
acquire를 재시도 루프 밖으로 / client 미전달 / go 포털만 우회 / 우회하는 새 전송 자리
추가. 각각 다른 테스트가 잡는다. 마지막 것만 AST다: `session.get(...)` 자리가 하나임을
본다. **효과 검사는 지금 있는 경로만 본다 — 새 전송 경로는 아무 테스트도 건드리지 않고
상한을 비켜 간다.** 이 저장소가 분자에서 이미 겪은 형태다(#1229 → #1231).

ruff clean · mypy strict clean · pytest **91 passed**(live 5 deselected).

**그리고 네 번째로 틀린 것은 Map 쪽 결론이었다.** "큐 러너가 scope를 순차 처리하므로
합계 5 TPS"라고 적었는데, 전문 리뷰어 둘이 **독립적으로 같은 자리**를 짚었다. 그
순차성은 run **하나 안에서**의 이야기다:

| 자리 | 값 |
|---|---:|
| 큐 센서 틱당 RunRequest | **10** (`RUNNING`, 15초 틱) |
| `dagster.yaml` `max_concurrent_runs` | **10** |
| `tag_concurrency_limits[…request_id]` | **4** |

request마다 run_key가 다르니 worker run 넷이 동시에 뜨고, run마다 프로세스가 다르니
`KrexClient`도 버킷도 넷이다 → **최대 20 TPS.** 직렬화하는 것이 아무것도 없다:
실행 advisory lock은 request id와 scope key에 걸려 scope가 다르면 둘 다 진행하고,
Dagster pool `KREX_NOTICE_SNAPSHOT_POOL`은 **asset**에 선언됐는데 큐 경로는 asset
wrapper를 우회하며, `ops.provider_refresh_policies.max_concurrent`는 plan payload에
**실리기만 하고 아무도 그 값을 보고 멈추지 않는다.**

**닫혔다고 적은 구멍이 현재 설정으로 열려 있었다.** 배포가 초록인 것과 고친 것이 그
안에 있는 것이 다르듯, **라이브러리가 막는 것과 시스템이 막는 것도 다르다.** 지금
보증되는 것은 "프로세스당 5 TPS"다. 남은 작업은 `T-VN-KREX-TPS-FANOUT`.

**아직 Map에 들어오지 않았다** — krex 핀은 `c6d8717e…` 그대로다(`ddd69cd2`는 그 전
값이다 — 처음에 그것을 적었다). krex PR 머지 후 repin이 따라온다.

## 2026-09-14 — t43a 배포, 그리고 고친 것이 prod에서 살아 있는 것을 봤다

`#1231`·`#1232`·`#1233`을 `e3fddce81`로 핀했다. 전 사이클 GREEN — 회전
(pinset `6ff11b3b6520d05b`) · rebuild `phase=committed` · executor 이미지 ·
repin **VERIFIER PASS** · M01 ACL **55/55** · **D1 live Playwright 11 passed** ·
lane 정리 · D2 `phase=passed`.

**배포로 끝내지 않고 고친 값을 prod에서 읽었다:**

| 무엇 | 종전 | prod 실측 |
|---|---:|---:|
| `opinet_run_call_budget` | 600 | **140** |
| `opinet_low_top_max_calls` | 180 | **90** |
| 큐가 건너뛰는 operation | 0 | **6** |

배포가 초록인 것과 **고친 것이 그 안에 있는 것**은 다른 사실이다. 이 판에서 그
구분을 여러 번 배웠다 — 목록에 이름을 올린 것과 그 이름을 읽는 실행 경계가 있는
것이 달랐고(#1231), 분자를 세는 것과 그 수가 실릴 자리가 있는 것이 달랐다(#1229).

## 2026-09-14 — "이관됐다"가 "옮겨야 한다"는 뜻은 아니었다 (MOIS)

`mois`/localdata 분모를 보러 갔다가 네 번 생각을 바꿨다. 그 순서를 적는다 — 각
단계에서 내가 무엇을 근거로 틀렸는지가 내용이다.

**1. "사이트가 죽었다".** `www.localdata.go.kr`가 WebFetch 2회·브라우저 2회 내내
뜨지 않았다. 그래서 "확인 실패"로 적었다.

**2. "라이브러리가 깨졌다".** 사용자가 "웹사이트 디자인 변경 때문일 수 있으니 확인 후
이슈 있으면 라이브러리 수정"이라고 했다. 보니 라이브러리는 `www`가 아니라
`file.localdata.go.kr`를 쓴다 — **다른 호스트**다. curl로 쳤더니 302 → `/error.html`
→ **403**. "깨졌다"고 적었다.

**3. 그런데 깨진 것은 내 curl이었다.** Referer를 붙이니 200이었다. 그리고 라이브러리
소스를 보니 **이미 Referer를 보내고 있었다.** 실제로 라이브러리 경로를 그대로 실행하니
info 200 · validate 200이다. 내 재현이 라이브러리와 달랐던 것이지 라이브러리가 틀린
것이 아니었다. **호출을 흉내 내지 말고 그 호출을 시켜 봤어야 했다.**

**4. "data.go.kr로 이관됐다"(사용자).** 그러면 파일 호스트를 계속 긁는 것은 레거시에
매달리는 것처럼 보였다. 그래서 두 방식을 비교했고 — 오픈API는 slug마다 활용신청이
필요하고(prod 키로 403) `general_restaurants` 한 slug만 2,129,830행이라 페이지 수천
개였다.

**그리고 세 번째 것을 보고 답이 나왔다.** data.go.kr 파일데이터 상세의 제공형태가
"**기관자체에서 다운로드(제공데이터URL기재)**"이고, 그 URL 필드가
`https://file.localdata.go.kr/file/<slug>/info` — **지금 라이브러리가 쓰는 바로 그
주소**다. 두 데이터셋으로 확인했다(15045016 / 15044967).

**이관은 됐는데 파일 경로는 그대로였다.** data.go.kr이 메타데이터를 들고 실제 파일은
기관 호스트에서 받게 한다. 그래서 옮길 것이 없고, 그 경로는 활용신청이 필요 없으므로
**분모가 없는 것이 정상**이다(krheritage와 같은 이유).

### 남길 것

**깨졌을 때 볼 곳은 data.go.kr 파일데이터 페이지의 URL 필드다.** 그것이 정본이고
`file.localdata.go.kr`는 그 필드의 현재 값일 뿐이다. 지금 그 호스트는 Referer를
요구하고(핫링크 보호), 사람용 포털은 죽어 있다 — 조이는 중이라는 신호다.

그리고 요청 수가 확정됐다: slug당 3(info·validate·download) × 42 = **126요청**으로
전체 스냅샷. 오픈API로 같은 것을 받으면 수만 요청이다.

## 2026-09-14 — 포털을 한 번 보니 저장소가 5배 틀려 있었다 (OpiNet)

"지금 쿼터 이슈가 급한 이유가 뭐야? 공식 자료에서 확인하면 되는 거 아님?"이라는
물음이 맞았다. 두 가지가 동시에 드러났다.

### 급하지 않았다

prod 실측: feature asset materialization **0건**, feature cron schedule 전부 꺼짐.
KMA·에어코리아는 제외 + 큐 경계에서 강제. **지금 prod는 upstream을 거의 부르지
않는다.** 나는 큐 예산 강제 장치를 만들려 하고 있었는데, 이 저장소가 스스로 적은
원칙이 "**측정 전에 상한 숫자를 바꾸지 않는다**"였다. 내가 그것을 어기고 있었다.

### 그리고 보니 5배 틀려 있었다

오피넷 이용안내를 **한 번 열었더니** 일반 API 19종이 `300call/일`이고 1,500call/일은
**유료 프리미엄 3종**이었다. 이 저장소는 무료키 한도를 1,500으로 알고 그 위에 예산
전체를 세웠다:

| 자리 | 종전 | 실제 300 대비 |
|---|---:|---|
| `opinet_run_call_budget` 기본 | 600 | **하루 한도의 2배**(place job과 겹치면 4배) |
| 같은 필드 `le` 상한 | 700 | 설정 한 줄로 하루의 2.3배 |
| `opinet_low_top_max_calls` 기본 | 180 | `get_area_codes`와 합쳐 하루의 66% |

Map이 부르는 네 오퍼레이션은 전부 일반 API 목록에 있다. **켜져 있었다면 첫날에
막혔을 값이다** — prod가 `opinet_scope_mode=disabled`라 잠복해 있었을 뿐이다.

140/300/90으로 내렸고 산수를 테스트로 결박했다(종전 값으로 되돌리면 2건이 빨개지는
것을 확인했다). 대가는 커버리지다 — lowTop 시군 윈도가 60 → 30, 전국 1주기 ≈4일 →
≈8일. run당 cap으로는 "하루 2 run"을 표현할 수 없어서 생기는 손해다.

### 남은 셋도 봤다 — 그리고 "분모가 없다"가 셋 다 다른 뜻이었다

- **`krheritage`: 한도가 존재하지 않는다.** provider 소스가 `serviceKey`를
  `apis.data.go.kr` 호스트에만 주입하고 heritage는 `www.khs.go.kr/cha`다 — **인증키가
  없다.** 키가 없으면 per-key 일일 한도라는 개념이 없다. sweep당 ~3,950요청에 대해
  "몇 %"를 물을 대상이 애초에 없었던 것이다. 위험은 쿼터 소진이 아니라 **과도 호출로
  인한 차단**이고, 그것은 분모가 아니라 간격·동시성의 문제다.
- **`krex`: 한도를 공개하지 않는다.** 인증키는 즉시 발급되는데 OpenAPI 소개·인증키
  발급 어느 페이지에도 수치가 없다. **모르는 것이지 없는 것이 아니다.**
- **`mois`/localdata: 못 봤다.** `www.localdata.go.kr`가 응답하지 않았다. 재시도해야
  한다.

셋을 "분모 없음"으로 뭉쳐 적고 있었는데, 실제로는 **없다 / 모른다 / 안 봤다**로
전부 다르다. 필요한 조치도 다르다 — 첫째는 rate limit, 둘째는 문의, 셋째는 재시도다.

### 교훈

**분자를 만드는 데 하루를 썼는데, 분모 하나를 보는 데는 1분이 걸렸고 그쪽이 더 큰
것을 찾았다.** 계측은 "우리가 얼마나 쓰는가"를 답하지만 그 답이 쓸모 있으려면 분모가
맞아야 한다.

## 2026-09-14 — 사용자가 끈 provider가 살아 있는 경로로 나가고 있었다

`T-VN-QUOTA-ARITHMETIC` 조문 6(마지막)을 닫으러 갔다가 조문보다 큰 것을 찾았다.

### 조문 6은 이미 충족돼 있었다

본문이 "**남은 것은 G(실제 격자 수) 실측**"이라고 적는데, **같은 절의 표가 같은 날
G = 59로 답하고 있었다.** 헤드라인 비율 72%/72%/24%도 반증된 G=300 상한의 열이다.
낡은 조문 하나로 task가 열려 있었던 것이다. 조문이 요구한 것 — 오퍼레이션별 분모,
쿼터 비공유, G, 증폭기 선언, 조문 3, 켠 뒤 볼 분자 — 은 전부 들어와 있었다.

### 그런데 prod는 cron으로 돌지 않는다

instigator state가 11개뿐이고 전부 센서 + 분당 job 하나다. **feature load schedule은
하나도 켜져 있지 않다**(전부 `default_status=STOPPED`, 켜진 적 없음). 살아 있는 것은
`feature_update_request_queue_sensor`다. 즉 쿼터 산수 전체가 **cron 기준으로 쓰였는데
prod의 실제 적재 경로는 큐**다.

그래서 2차 적대 리뷰가 잡은 "큐 runner가 계수기를 열지 않는다"가 **운영상 가장 중요한
blocker**였다. 그때는 그것을 몰랐다.

### 그리고 "껐다"가 참이 아니었다

`DISABLED_FEATURE_LOAD_SCHEDULES`는 2026-09-09 사용자 지시로 KMA·AirKorea 자동 적재를
중지한 기록이다. 그런데 그 목록은 **`FEATURE_LOAD_SCHEDULES` 생성에서 이름을 빼는
것이 전부**였다 — 전 저장소에서 그 상수를 읽는 자리가 그 한 줄뿐이다.

큐 runner에는 꺼진 operation 6개의 spec이 그대로 있고, 실행 전 정책 게이트는
`provider_refresh_policies` row가 없으면 `allow_targeted`로 **fail-open**한다.
baseline seed에 그 row는 **0건**이다. PinVi cache target refresh 하나가 반경 안 KMA
weather feature를 잡으면 격자 순회가 그대로 나간다.

**사용자가 끈 것이 꺼져 있지 않았다.** 기록은 "껐다"고 말하는데 살아 있는 경로에서는
지켜지지 않았다.

이제 큐 경계가 `DISABLED_FEATURE_LOAD_OPERATION_KEYS`를 읽어
`provider_auto_load_disabled`로 건너뛴다. 결박은 목록이 아니라 **효과**에 건다 —
enforcement를 `if False:`로 바꾸면 12건이 빨개지고 대조군 2건은 초록으로 남는 것을
확인했다. "끄는 것은 시계이지 능력이 아니다"는 원칙은 그대로다: 사람이 Dagster UI에서
job을 직접 돌리는 백필은 이 runner를 지나지 않는다.

### 남은 것은 끄지 않은 provider의 총량이다

큐에는 일일 예산이 없다. 상한은 센서 tick당 10 run(15초 간격)뿐이다.

그리고 같은 날 **KMA·에어코리아가 쿼터 평가 대상에서 빠졌다**(사용자 지시). 둘 다
꺼져 있고 이제 큐 경계가 그 결정을 강제하므로, 평가는 **끄지 않은 provider**만
본다. 그러자 그림이 더 나빠졌다 — 남는 provider 중 일일 가드가 있는 것은
**OpiNet 하나뿐**이다(KMA의 cursor skip이 빠지니 그렇다). `krheritage`는 sweep당
~3,950요청인데 분모조차 없고, 나머지 다수는 1,000/op/일이다.

빼고 나서 남은 것이 더 좁아지는 것 — 그것이 이 지시가 실제로 드러낸 것이다.
`T-VN-QUEUE-QUOTA`로 남겼다(`docs/etl/upstream-quota.md` §5).

## 2026-09-14 — 분자를 prod에 올렸고, 거기서는 아직 볼 수 없다는 것을 알았다

`#1229`(`2db70b478`)가 머지됐고 t42a 재핀 사이클이 전 사이클 GREEN이다 — 회전 #50,
rebuild `phase=committed`, repin VERIFIER PASS, M01 ACL 55/55, **D1 live Playwright
11 passed**, D2 `phase=passed`. 분자 모듈이 prod Dagster 이미지에 살아 있는 것도
확인했다(`upstream_requests_min`).

### 그런데 prod의 asset 경로에서는 분자를 관측할 수 없다

배포 뒤 돌아간 run이 `current_weather_summary_refresh`(분당) 하나뿐이다. feature
asset materialization이 **0건**이라 `upstream_requests_min`이 실린 자리가 없다.

이유는 설정이다 — feature load schedule은 전부 `default_status=STOPPED`이고
(`schedules.py`), prod의 instigator state 11개에 feature 스케줄이 하나도 없다.
**즉 오늘 prod는 feature upstream을 거의 부르지 않는다.** 분자를 붙였지만 그것이
0이 아닌 값을 내려면 누군가 스케줄을 켜야 한다.

**그리고 그것이 정확히 어디를 봐야 하는지를 바꾼다.** prod의 살아 있는 적재 경로는
cron이 아니라 **feature update queue**다(`feature_update_request_queue_sensor`만
RUNNING). 큐 경로의 분자는 asset output metadata가 아니라
`ProviderDatasetRefreshResult.metadata`에 실린다 — 2차 적대 리뷰가 잡은 "큐 runner가
계수기를 열지 않는다"가 운영상 가장 중요한 blocker였던 이유다.

이것은 결함이 아니라 **이 task의 다음 단계가 무엇인지를 말해 준다.** 조문 6(KMA
격자 재활성화)이 아직 `[~]`인 이유와 같은 자리다 — 분모·분자·증폭기 선언이 다
끝났으므로, 이제 켜는 판단에 필요한 것은 전부 있다. 켜는 순간 그 판단이 맞았는지를
`upstream_requests_min`이 처음으로 말해 줄 것이다.

**켜지 않고 분자를 검증하려면 쿼터를 쓴다.** 그래서 하지 않았다. 계측의 정확성은
런타임 테스트가(가짜 client로 N번 → 계수 N) 결박하고, prod가 더해 주는 것은
"실제 Dagster 문맥에서 배선이 살아남는가"뿐이다 — 그 축은 스케줄이 켜지는 날
공짜로 확인된다.

## 2026-09-13 — 분자를 세기 시작했고, 적대 리뷰 다섯 판이 각각 blocker를 냈다

분모를 얻은 다음 날의 절반은 분자였다. **"한도의 몇 %를 쓰는가"는 분자 없이는
질문이 되지 않는다.** 그런데 분자는 fetcher가 generator라 값을 흘릴 배선이 없었다 —
요청을 세는 자리(페이지 루프)와 내보내는 자리(asset output metadata) 사이에 인자가
없다. `ContextVar`가 그 배선을 대신한다. 시그니처는 하나도 바꾸지 않았다.

### 1차 리뷰: 배선은 맞는데 **커버리지가 없었다**

계수기는 asset 35개 전부에서 열리는데 세는 자리는 셋뿐이었다. 그래서 OpiNet이
수천 건을 쓰면서 `upstream_requests_min: 0`을 냈다 — 하필 저장소가 유일하게 **한도 대비 run 예산을 코드에 박아 둔** provider다
(`_OPINET_RUN_CALL_BUDGET = 600` vs 무료키 1,500/일, #545). **예산을 짜 둔 자리의
분자가 0이었고**, 그 예산기는 호출마다 정확히 1을 차감하고 있었다. 한 줄이면 됐다. 그리고 그때 내가 갖고 있던 구조 검사는 "asset이 계수 범위 안에서
도는가"를 물었는데 wrapper가 **항상** 열므로 항진명제였다. 같은 실패 형태를 그날
네 번째로 반복한 것이다.

고친 것: (1) 한 번도 기록되지 않았으면 `None` — 계측되지 않은 fetcher가 0으로
위장하지 못한다. (2) 세지 않던 경로를 계측. (3) 검사를 asset이 아니라 **fetcher**
단위로.

### 2차 리뷰: 같은 형태가 **다른 자리에** 남아 있었다

**(a) krheritage detail.** OpiNet에서 고친 것과 정확히 같은 모양이 그대로 있었다.
목록 페이지는 세는데 record당 1 HTTP인 detail은 세지 않았다 — run 하나가 목록 ~45건
+ detail ~4,000건이므로 실린 수가 **실제의 약 1%**였다. 그리고 목록을 세는 덕에
key는 실려 나갔다. 즉 "0으로 위장하지 않는다"는 계약이 여기서는 작동하지 않았다.
두 자릿수가 네 자릿수인 척했다.

**(b) 큐 경로.** 계수기를 여는 자리는 asset wrapper 둘뿐인데, feature-update queue
runner는 wrapper가 아니라 **원본 run 함수**를 직접 부른다. 그 경로에서는 모든
`note_upstream_request()`가 no-op이었다.

**(c) 내가 쓴 문장 하나가 거짓이었다.** "실패 경로에도 함께 실린다" — 실패한 step은
output을 내지 않으므로 `add_output_metadata`로 실은 값은 사라진다. 지금은 쿼터
소진이면 `Failure` metadata가, 그 밖이면 경고 로그가 받는다.

**(d) 면제 사유 둘이 provider 소스와 어긋났다.** `file_data.iter_pages`는 public이고
`iter_all`이 그것을 감싼 것뿐이었다. 행사 창은 14개월로 알 수 있었다 — 비어 있는
달도 요청 1건이라 record 수로는 역산되지 않는다. **못 센다는 선언은 값싸고, 값싼
선언은 계측을 대체하기 시작한다.** 넷이던 면제가 둘로 줄었다.

### 3차: 2차 수정이 **만든** blocker

**MOIS 계수가 항상 no-op이었다.** 2차에서 "MOIS Phase A가 게이트 밖"이라는 지적을
받고 계수를 넣고 게이트 목록에 올렸는데, Phase A는 Dagster **resource init 시점**에
돈다 — 계수기는 compute 안에서야 열린다. 프로덕션 세 경로 전부에서 조용한 no-op이었고,
**게이트와 문서가 그것을 "센다"로 보증했다.** 지적을 게이트 안으로 옮겼을 뿐 계측은
생기지 않은 것이다.

**초크포인트가 유일하지 않았다.** `_add_output_metadata`가 "유일한 자리"라고 적어
뒀는데 op/sensor/maintenance는 `context.add_output_metadata`를 직접 부른다. feature
asset 둘(visitkorea enrichment, concierge YouTube)이 그 길로 새면서 **자기가 센 값을
버리고 있었다.**

**그리고 내가 6곳에 복제한 문장이 거짓이었다** — "OpiNet은 분모를 실측한 유일한
provider". 같은 문서가 "OpiNet 일일 한도 실측이 그다음 단계다"라고 적고 있었다.

### 4차: 규약이 시키는 일을 게이트가 막았다

acceptance 파일이 읽기 한도를 넘어 규약 §8대로 닫힌 절 31개를 아카이브로 옮겼더니,
`check_task_ledger_deletions.py`가 **37건을 "근거 없는 삭제"로 판정**했다. 그 게이트는
감시 3파일만 보고 `docs/archive/`를 모른다. 아카이브 이동은 삭제가 아니라 **이관**이므로
게이트 쪽을 고쳤다.

그리고 3차가 고친 문장 셋이 **다른 파일에서 되살아나 있었다**(새 모듈 head docstring,
acceptance 본문, 런타임 테스트 docstring). 같은 사실을 여러 파일에 복제하면 정정도
복제해야 한다 — 4차가 그 대가를 청구했다.

### 5차: 되돌린 것 하나

4차가 고친 게이트가 **다른 구멍을 열었다.** 아카이브를 "근거"로만 더하면 거기로
옮겨 간 항목이 그 뒤로 영원히 감시 밖이 된다 — 다음 PR이 아카이브에서 통째로 지워도
조용하다. 그리고 확인해 보니 **헤딩으로 자르는 분리 자체가 안전하지 않았다**: 코드
펜스가 섹션 경계를 넘나들어(odd fence 섹션 10개) 같은 줄이 base에서는 체크박스이고
아카이브에서는 아니게 된다. 파서가 보는 것이 달라진다.

그래서 **분리를 되돌리고** 그 문제를 `T-VN-LEDGER-ARCHIVE`로 남겼다. acceptance
파일은 내 추가분을 정본 포인터로 줄여 한도 아래로 내렸다 — 같은 수를 여섯 곳에
복제한 것이 3·4·5차 재발의 공통 원인이었으니 방향도 맞다.

그리고 4차가 자랑스럽게 적은 수정 하나가 **죽은 코드**였다. MOIS Phase A에 건
쿼터 판정은 발화할 수 없다 — `mois` lib은 쿼터 예외도 `failure_kind`도 `status_code`도
갖지 않는다. 걸어 두면 구조 검사가 그 op을 "쿼터 판정을 거는 경계"로 세어 **막았다고
보증한다.** 3차가 없앤 '이름으로 초록'이 같은 자리에서 재발할 뻔했다. 뺐다.

### 이번 판의 교훈은 검사기 쪽이다

(a)를 **내 정적 검사가 통과시켰다.** 그 검사는 "계수 호출 자리가 있는가"만 본다 —
루프 밖 1회도, 도달 불가 분기도, 죽은 중첩 함수도 초록이다. 전이 폐쇄가 bare name
기준이라 모듈 간 동명 함수를 뭉개기까지 했다.

그래서 층을 나눴다. 정적 검사는 **"빠진 진입점이 없는가"**만 지키고(우주는 명시
목록, 하한은 선언에 정확히 — 여유 상수를 쓰지 않는다), 효과는 **가짜 client로 N번
부르게 하고 계수가 N인지 재는 런타임 테스트**가 본다. 그쪽이 (a)를 실제로 잡는
유일한 층이다.

진입점 40개 중 35개가 전부 센다. 못 세는 둘은 upstream 요청이 아예 없고, 부분
계측 셋은 OpiNet bbox enumerate 둘(provider가 격자 셀마다 부르는데 그 셀 수가
provider private이다 — 1로 세면 1과 20,000이 같아진다)과 MOIS asset 경로다.

## 2026-09-13 — 분모를 얻었고, 적대 리뷰가 내 주장 셋을 뒤집었다

`T-VN-QUOTA-ARITHMETIC`은 "쿼터에 대해 이 저장소가 하는 진술 대부분이 근거가 없다"는
task였다. 그 근거의 절반이 오늘 들어왔고, 나머지 절반에서 **내가 새 근거 없는 주장을
만들었다**. 둘 다 적는다.

### 분모는 서비스가 아니라 오퍼레이션마다 걸린다

data.go.kr 마이페이지의 활용신청 상세에 "상세기능" 표가 있고, 거기 **오퍼레이션마다**
일일 트래픽이 따로 적혀 있다. `기상청_단기예보 조회서비스`의 네 오퍼레이션이 각각
10,000/일이고 **공유하지 않는다.** 이 저장소는 반대 가능성을 열어 두고 있었고, 그
차이가 KMA 산수를 3배 갈랐다.

가장 좁은 자리는 KMA가 아니라 **에어코리아(op당 500)** 와 **전국표준데이터·
visitkorea(op당 1,000)** 였다. 그리고 `krheritage`·`opinet`·`krex`·`mois`는 그 포털에
아예 없다 — 분모가 다른 곳에 있고 아직 보지 않았다.

### G도 쟀고, 300은 상한이지 대상 수가 아니었다

`ops.poi_cache_targets`가 **0행**이다(파괴적 rebuild 직후, PinVi 미등록). 설정
extra point 60개가 DFS 격자로 dedupe돼 **G = 59**. 즉 오늘 KMA를 다시 켜면 14%/14%/5%
이고 4배 배수를 전부 얹어도 57%다. 상한 300에 닿아야 72%가 된다.

**숫자 하나를 안 재고 여섯 문단을 썼다면 그 여섯 문단이 다 틀렸을 것이다.**

### 적대 리뷰가 뒤집은 것 셋

**"쿼터 실패가 4배로 청구된다"가 틀렸다.** 쿼터가 소진된 뒤의 재시도는 순회를 다시
도는 것이 아니라 **첫 격자에서 즉사한다** — 격자 루프는 항상 `grids[0]`부터 시작하고
성공 cursor는 완주 뒤에만 전진하므로, 재시도의 첫 호출이 곧바로 code 22를 받는다.
재시도 3회가 사는 것은 순회 3벌이 아니라 요청 3건이다. 내가 지우겠다고 선언한
부류(분모 없는 수량 주장)를 같은 PR 안에서 새로 만들었다.

**판정이 가장 좁은 분모에서 한 번도 발화하지 않았다.** `failure_kind`를 예외에 붙이는
provider lib은 절반뿐이고, 하필 에어코리아·datagokr가 안 붙인다. 속성 하나에 건
판정은 한도 10,000짜리에서만 작동했다.

**krforest 정당화가 거꾸로였다.** "상한을 안 주면 10,000페이지까지 간다"고 적었는데
라이브러리는 반대로 **1페이지로 조용히 잘린다**(`totalCount` 부재 시 `len(items)`로
채움 → 추정치 1). 그리고 저장소 헬퍼로 옮겨도 **그 절단은 그대로다** — 2,500행에서
1,000행에 멈추는 것을 실측했다. 즉 내 수정은 내가 말한 문제를 고치지 않았다.

### 오늘의 규칙

1. **탐지기는 이름이 아니라 효과에 결박한다.** 같은 날 만든 탐지기 셋이 같은 방식으로
   뚫렸다 — 함수 **이름**으로 결박하니 두 실패 분기 중 하나만 지워도 35개가 초록,
   모듈의 **모든 문자열**을 세니 판정을 지우고 docstring에 이름만 남겨도 초록,
   문자열 슬라이스로 파싱하니 삼중따옴표 하나에 검사 구간이 본문 밖으로 밀렸다.
   결박 단위를 `except` 핸들러·`require(...)` 첫 인자·AST로 내리자 같은 변이에서
   36건이 빨개졌다.
2. **변이는 '삭제'가 아니라 '가장 그럴듯한 회피'로 한다.** 절반만 지우기, 이름은
   남기고 호출만 지우기 — 그것이 실제로 일어나는 모양이다.
3. **"고쳤다"는 주장도 재야 한다.** krforest는 옮기기만 하고 고쳤다고 적었다. 실제로
   재 보니 같은 절단을 했다. 옮긴 것과 고친 것은 다른 사실이다.
4. **없는 신호를 있다고 적지 않는다.** krex의 "빈 Page로 시끄럽게 실패한다"는 문장에
   대응하는 코드가 없었다. 빈 Page는 예외가 아니고, 0행이 `record_sync_success`까지
   가서 실패 카운터를 0으로 되돌렸다 — Dagster는 초록, 데이터는 갱신 없음.
5. **분모 없는 문장은 상수다.** 관리자 UI가 32개 schedule 중 31개에 같은
   "rate limit의 90% 이하"를 돌려주고 있었다. 같은 답을 모두에게 주는 것은 그 대상에
   대한 진술이 아니다.

### 배포 — 손으로 만든 경로가 막히고, sanctioned 경로가 왜 있는지 알았다

prod에 올리려고 host-direct `docker compose build`를 썼다가 두 번 막혔다. 두 번째가
결정적이다 — compose는 **대상 서비스만 빌드해도 파일 전체를 보간**하는데 prod
`.env`에 내가 건드리지도 않는 서비스(concierge)의 키가 없었다. 계속하려면 비밀값을
내가 넣거나 "파괴적"이라 표시된 경로를 쓰는 수밖에 없어 거기서 멈추고 `.env`를
원복했다. sanctioned 경로(`run-pinned-rebuild-once`)는 Manager가 env를 통째로
구성해 넘긴다 — 내가 흉내 낼 수 있는 것이 아니었다.

그 다음 정찰이 더 중요한 것을 잡았다. 내가 배포하려던 `e037ab01`은
`refs/pull/1227/head`이고 **#1226을 담고 있지 않았다** — 그것을 핀했다면 같은 날
머지한 run 완주 게이트를 prod에서 되돌리는 것이었다. 핀 원장은 `repository_commit`을
exact로 새기므로 미머지 head를 핀하는 것 자체가 오래 남는 오염이다. 머지 후 main
커밋(`0b60a850`)으로 간 것이 옳았고, `chain17.sh`가 그것을 인자 하나로 받아
회전→rebuild→executor→repin→ACL→D1→D2를 전부 GREEN으로 끌고 갔다.

**리터럴을 들고 있지 않은 스크립트가 재사용된다.** `chain12`는 Manager revision을
본문에 박아 두어 낡자마자 못 쓰게 됐고, `chain17`은 Map만 인자로 받고 PinVi는 핀
원장, Manager는 설치 매니페스트에서 유도해 오늘 그대로 돌았다. 그 주석이 스스로
그 이유를 적어 두었다.

## 2026-09-12 — 고침이 스택을 내렸고, 그 뒤에 진짜 고침이 있었다

`T-VN-DAGSTER-STORAGE`가 닫히는 과정에서 prod가 한 시간 넘게 내려가 있었다. 그 한
시간이 가르쳐 준 것을 적는다.

### 파괴적 rebuild는 실패해도 파괴는 되돌리지 않는다

rebuild는 스택을 먼저 내린다. 그 뒤 단계에서 죽으면 **내려간 채로 남는다.** 06:18에
그렇게 됐고 나는 08:20이 되어서야 스택이 내려가 있다는 것을 알았다 — 원인을 좇느라
`docker ps`를 한 번도 안 봤기 때문이다. 실패를 조사할 때 **무엇이 지금 죽어 있는가**를
먼저 보는 것은 원인 규명보다 앞선다.

### `--json`이 원문을 삼킨다

launcher는 `ktdctl ... --json`으로 부르고, CLI는 봉인 밖 실패의 원문을 JSON에 넣지
않는다. 남는 것은 `{"status":"failed","classification":"unclassified"}` 한 줄과
0바이트 stderr다. 노출 계약으로는 옳지만 **운영자가 이유를 볼 방법이 없다.** 같은
CLI를 `--json` 없이 한 번 더 돌려 회수했다. 47초짜리였으니 값쌌지만 70분짜리였다면
같은 값을 두 번 치렀을 것이다.

### 두 번 틀렸다

**추론을 증거로 착각했다.** 실패 단계를 Manager 소스의 phase 목록에서 읽고 그것을
관측처럼 적었다. 영수증에는 그런 말이 없었다. 나중에 docker daemon 로그가
`…dagster-storage-migrate-run-dc953676ad41` 컨테이너가 2초 만에 죽은 것을 보여
주면서 확정됐지만, 그때 내가 한 것은 확인이 아니라 짐작이었다.

**내가 만든 사실을 세상의 사실로 읽었다.** 원문을 회수하려고 lock을 잡고 CLI를
돌렸는데 launcher처럼 FD를 넘기지 않았다. `c6c_deployment_lock`이 새로 잡으려다 내
flock에 막혀 "another C6c compatible-pair operation is already active"를 냈다.
하마터면 그것을 원인으로 적을 뻔했다 — 어제 pair contract v1 거절에서 같은 실수를
했으니 두 번째다.

### 간헐 실패와 결함은 로그가 같다

봉인을 고친 뒤 rebuild가 다시 죽었다. 이번엔 `pinvi-db-runtime-role` 단계였고 18분을
돌았다. **같은 입력으로 재시도하니 9분 40초에 완주했다** — resume journal에서
이어받았다. 코드를 의심하기 전에 한 번 더 돌리는 것이 이 계열에서는 옳다.

### 그래서 무엇이 달라졌나

수정 전 이 prod의 Dagster run은 **전부 실패**였다. 지금은 `SUCCESS 23 · FAILURE 1`
이고, 그 하나는 rebuild가 스택을 내리던 순간에 걸린 run이다. provider 적재 job이
이 prod에서 처음으로 `SUCCESS`로 끝났고 `claims 1047 · aliases 1047 · links 1047`이
다시 맞물렸다.

### 적대 리뷰가 막은 것

같은 날 D2 lane 변경에서 blocker 2건이 나왔다. 두 렌즈가 **독립적으로 같은 결함**에
도달했다 — purge를 게이트 앞에 두면 실패한 run의 소유 Feature가 사라지고, 복구
lane의 api-audit이 그 행 1건을 요구하므로 `recover`가 구조적으로 통과 불가능해진다.
BLOCKED는 `recover`로만 지워지고 `run`은 BLOCKED가 있으면 막히므로, 배포됐다면 D2가
prod에서 **영구 정지**했을 것이다. 두 줄의 상대 위치가 그것을 갈랐고 둘 다 그냥
helper 호출로 보였다.

## 2026-09-12 — 같은 집합을 각자 들고 있으면 언젠가 어긋난다

`T-VN-DAGSTER-STORAGE`를 고친 #1216이 prod rebuild를 깼다. 고침이 결함이 된 경위를
적는다 — 코드보다 **검사의 모양**에 관한 이야기다.

### 두 파일이 같은 집합을 각자 들고 있었다

`docker/dagster.yaml`의 최상위 key 집합과, `docker/dagster-storage-migrate.py`의
`_validate_dagster_config`가 요구하는 key 집합. 이 둘은 같아야 하는데 서로를 본 적이
없다. #1216이 한쪽에 `local_artifact_storage`/`compute_logs`를 더하자 다른 쪽이
`dagster_storage_target_not_sealed`로 거절했고, 그 사실은 CI에서가 아니라 **prod
rebuild가 스택을 내린 뒤**에 드러났다.

### 검사는 있었다. 통과하는 쪽을 안 봤을 뿐이다

`test_dagster_storage_rejects_alternate_top_level_storage_keys`는 실제
`dagster.yaml`을 읽는다. 그런데 그것이 보는 것은 **거절되는 것**이다 — 임의의 key를
더해 거절을 확인한다. 두 파일이 어긋나면 그 거절은 **이유만 바뀐 채 여전히
일어난다.** 항진명제다.

어긋남을 보려면 **통과하는 것**을 봐야 한다. 배에 실리는 config가 봉인 검사기를
통과하는지 보는 검사 하나를 심었더니, 변이에서 정확히 그것 하나만 빨갛다:

    ① 수정본 전체                    : 42 passed
    ② 검사기만 5-key 봉인으로 되돌림 : 1 failed, 41 passed
    ③ config에서 compute_logs 제거   : 4 failed, 38 passed

②가 핵심이다. 같은 두 파일을 읽는 기존 41건이 어긋남에 눈이 멀어 있었다.

### 진단이 두 번 틀렸다

**한 번은 추론을 증거로 착각했다.** 실패 단계를 Manager 소스의 phase 목록에서
읽고 "`map_dagster_storage_intent_durable`이 실패했다"고 적었다. 영수증에는 그런
말이 없었다 — `{"status":"failed","classification":"unclassified"}` 한 줄과 0바이트
stderr뿐이었다. 나중에 docker daemon 로그가 실제로 그 단계임을 확정해 주었지만,
그때 내가 한 것은 확인이 아니라 짐작이었다.

**한 번은 자기 자신에게 막혔다.** 삼켜진 원문을 회수하려고 `--json` 없이 CLI를
돌렸는데, lock을 잡기만 하고 launcher처럼 FD를 넘기지 않았다. `c6c_deployment_lock`이
새로 잡으려다 내 flock에 막혀 "another C6c compatible-pair operation is already
active"를 냈다. 하마터면 그것을 원인으로 적을 뻔했다 — **내가 만든 사실을 세상의
사실로 읽는 것**이 이 세션에서 두 번째다(어제는 pair contract v1 거절이 그랬다).

### 원문을 삼키는 계약

`--json` 경로는 봉인 밖 실패의 원문을 내지 않는다. 노출 계약으로서는 옳지만,
launcher가 그 경로만 쓰므로 **운영자가 이유를 볼 방법이 없다.** 이번에는 같은 CLI를
비-JSON으로 한 번 더 돌려 회수했다. 47초짜리 실행이면 값싸지만, 70분짜리였다면
같은 값을 두 번 치렀을 것이다.

## 2026-09-11 — 결함을 만든 자리와 그것을 가린 자리는 따로 있었다

T-VN-39가 착지했다(#1197). 마지막 두 라운드에서 배운 것을 적는다.

### 고친 것을 다시 봤다

1라운드 적대 리뷰의 지적을 전부 닫은 뒤, **그 수정 자체**를 5축 × 2인으로 다시
걸었다. 그 절반이 검사기·테스트 하네스를 바꾼 것이라 특히 위험했다 — 검사기가
틀리면 초록이 거짓말을 한다. 25건 중 11건이 반박을 견뎠고 blocker는 없었다.

가장 값진 것이 마지막이었다. uuid 필터 표면 하나가 변환을 못 받아 여전히 500이었다
(`/admin/theme-feature-candidates`). 22P02는 `sqlalchemy.exc.DataError`로 오는데
그것은 `ValueError`가 아니라서 라우터의 422 handler를 그대로 통과한다.

회귀 테스트를 붙이는데 계속 200이 나왔다. 라우터 코드에 helper 호출이 있고,
컴파일된 code object의 `co_names`에도 그 이름이 있고, helper를 직접 부르면 제대로
422를 던지는데, 테스트 안에서만 원문이 통과했다. `.pyc` 캐시·경로 그림자·라우트
중복을 차례로 배제하고 나서야 원인이 나왔다 — 코드가 아니라 API 패키지 conftest의
**autouse** fixture였다:

    async def _resolve(_session, ref):
        return FeatureIdentity(feature_id=ref, ...)   # 재키 이전의 등식

DB 없는 패키지에서 경계 해석을 태우려는 echo-resolve이고 재키 전에는 옳았다.
지금은 `feature_id=ref`가 거짓이고, 이 echo는 **모든** 참조를 "해석 성공"으로
만들기 때문에 그것이 깔린 채로는 "legacy 주소가 uuid로 바뀌는가"도 "없는 참조가
422인가"도 관측할 수 없다. **major #1이 깨뜨린 바로 그 두 축이다.**

즉 결함을 만든 자리와 그것을 가린 자리가 따로 있었고, 검사기를 아무리 고쳐도 이
층에서는 보이지 않았다.

### 개수 세기는 전칭 명제가 아니다

그 구멍을 새 lint도 못 봤다. uuid 쪽 단언이 helper **호출 개수 ≥ 5**뿐이었기
때문이다. "uuid에 바인드되는 feature 필터는 전부 이 helper를 지난다"는 명제를
어디서도 재지 않으므로 변환 안 된 표면이 남아 있어도 초록이다.

개수 세기를 **표면 열거**로 바꿨다 — 라우터에서
`Annotated[str | None, Query()]`로 선언된 `*feature_id` 파라미터를 전부 찾아
하나씩 확인한다. 고친 자리를 되돌려 확인했다: 검사가 그 표면을 이름으로 집는다.
되돌리기 전에는 되돌려도 초록이었다.

### provider 핀 — 조용한 절단이 두 곳에서 동시에 자랐다

형제 리포를 확인해 뒤처진 핀 8종을 올렸다. breaking은 khoa 하나(asyncio 전용
전환)였는데, 정작 무거운 것은 다른 데 있었다.

datagokr가 공용 pagination 헬퍼를 뽑으면서 종료 조건의 `reached_known_end` 가드를
떨어뜨리고, 같은 범위에서 행 단위 `except ValidationError: continue`를 넣었다.
둘이 겹치면 **기형 행 하나가 만재 페이지를 짧게 만들어** 18,000건짜리 데이터셋이
999건에서 끝난다 — 예외도 로그도 없이. 그리고 Map은 그것을
`authoritative_snapshot_complete=True`로 봉인한다.

이 부류를 이 저장소는 이미 안다. `provider_pagination` 모듈이 존재하는 이유가
`python-krex-api`의 똑같은 변화이고, 그 규칙은 "`total_count`가 권위이고 짧은
페이지는 total을 모를 때만 쓰는 대체 휴리스틱"이다. 더 나아가 krheritage 핀은
**정확히 같은 이유로 이미 묶여 있었고** 해제 조건까지 적혀 있었다 — "provider 측에서
total 기반 종료를 복구한 뒤 상향한다."

upstream은 복구하지 않았다. 그래서 기다리는 대신 **Map이 권위를 되찾았다** — 두
경로를 자기 페이지네이터 아래로 옮겨 provider 종료 조건에 대한 위임을 끊었다.
위임을 끊었으므로 보류 조건 자체가 사라졌다.

### CI가 구조적으로 못 보는 자리

khoa 파손을 잡은 것은 CI가 아니라 n150이었다. **CI는 provider extra를 설치하지
않는다**(`pip install -e ".[dev]"`) — 그것은 의도된 절충이지만(provider는 네트워크
의존), 그래서 "sync 진입점이 사라졌다" 같은 실제 파손을 CI 혼자서는 볼 수 없다.
그 빈자리를 `_provider_surface.json`이 메운다 — 핀된 SHA의 공개 표면을 굳혀
대조하고, 핀만 올리고 manifest를 안 고치면 즉시 빨개진다. 이번에 실제로 그랬다.

그리고 Map 쪽 테스트도 못 잡았을 것이다. fake khoa 모듈이 sync 표면을 들고 있어서
실제 provider가 그것을 없앤 뒤에도 초록이었을 것이다. fake를 실제 표면에 맞췄다.

### 규칙 하나를 더 얻었다

**하네스가 흉내내는 표면이 낡으면, 그 축은 초록인 채로 사라진다.** echo-resolve도
fake khoa도 fake datagokr도 전부 같은 모양이었다 — 만들 때는 옳았고, 세상이 바뀐
뒤에는 결함을 가리는 쪽으로만 작동했다. 계약을 바꾸는 작업에서는 **그 계약을
흉내내는 자리**를 함께 세는 것이 범위의 일부다.

### 배포: "막혔다"는 내 오독이었다

prod 배포를 열면서 회전 게이트가 `rotation pair contract version is unsupported: 1`로
거부했다. 나는 그것을 "PinVi가 v2 계약을 main에 올려야 풀린다"로 읽고 T-VN-40
선행조건과 같은 종류의 blocker로 적으려 했다. 틀렸다.

게이트는 **내가 넘긴 PinVi revision**의 계약을 읽는다. 나는 PinVi `origin/main`을
넘겼고 그것이 v1이었다. 핀된 `f62e7ef1`은 2026-09-07에 이미 v2로 회전했다 — 그
revision으로 다시 부르니 preflight가 그대로 통과했다(exit 0).

그리고 v2의 요지가 바로 이 경우다. v2는 revision이 아니라 digest만 담으므로, Map의
세 OpenAPI 표면이 핀된 revision과 바이트 동일하면 **PinVi를 건드리지 않고 Map만**
전진한다. `2099b8a6`와 `3b11c975`(18커밋 차) 사이에서 셋 다 동일했다. 재키는 내부
타입을 바꿨을 뿐 바깥 이름을 바꾸지 않았다는 경계 규칙이 여기서 실물로 갚였다.

교훈은 게이트에 대한 것이다. **거부 메시지는 내가 건넨 인자에 대한 사실이지 세상에
대한 사실이 아니다.** 나는 그 둘을 바꿔 읽고 하마터면 다른 저장소의 작업을
선행조건으로 적을 뻔했다.

### 레지스트리는 배포를 기록하지만 실물을 강제하지 않는다

배포 전 점검 중에 정본과 live가 갈라져 있는 것을 봤다. 정본 generation은
`2099b8a6`/`c10d6782`를 가리키는데, 실제로 돌고 있는 컨테이너는 `cf65e973`(8/27)에
`0169fe90`이었다 — F1D v5 rehearsal state가 03:46에 live 위에 자기 candidate를
얹었고, 정본 generation 파일은 9/7자 그대로였다.

즉 "무엇이 배포됐는가"를 레지스트리에만 물으면 틀린 답을 얻을 수 있다. 그래서
T-VN-39-DEPLOY 완료 조건에 **정본과 실제 컨테이너의 일치**를 넣었다. 배포가 끝나면
둘이 같아야 하고, 같은지는 따로 봐야 한다.

## 과거 기록 아카이브

> 현행 작업 창(2026-09-11~) 이전 기록은 아래로 분리했다. 검색은
> `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
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
