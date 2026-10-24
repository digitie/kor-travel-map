# journal 아카이브 — 2026-10-01 (b)

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
