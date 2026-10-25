# journal 아카이브 — 2026-10-01 ~ 2026-10-12 (c)

> 220 KiB 경계에 근접한 live 기록을 완전한 절 단위로 분리했다(docs/tasks-rule.md §8). 본문은 상대 링크의 기준 경로만 바꿨다. 읽기 전용 이력이다.

## 2026-10-12 — MOIS ADR-108 통합 테스트 resource 누락·직접 호출 tag 실패

- PR CI 통합 두 lane이 `test_dagster_assets_validate_coordinates_and_load_to_postgis` 하나로 붉었다 —
  `Dagster resource 없음: mois_load_plan`. 테스트가 asset을 `build_asset_context`로 직접 부르며 resource dict를
  손으로 만든다. 운영 경로는 빠질 수 없다: `definitions.py`가 resource를 등록하고 asset이
  `required_resource_keys`로 선언하며(누락이면 Dagster가 정의 load에서 거부) 큐 runner도 plan을 넣는다. 그래서
  기본값을 두지 않고 fixture에 운영 기본 plan(전 업종 = 월간 schedule 경로)을 넣었다. 다른 직접 호출은
  `test_mois_assets.py`(이미 plan 제공)뿐이고 scripts에는 없다.
- 그 뒤에 숨은 두 번째 실패: `build_asset_context`의 run id `EPHEMERAL`은 instance에 없어 결과 tag 쓰기가
  `DagsterRunNotFoundError`로 터진다(로컬 probe로 확인). `_tag_run_outcome`이 그 예외만 삼킨다 — 실제 run에서는
  나지 않는다. 진짜 `build_asset_context`로 부르는 단위 테스트를 더했다(mutation RED 확인).
- 검증(로컬): dagster MOIS·assets·definitions·resources·runner 138 passed, ruff·mypy strict. 통합은 CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 OpenAPI admin 계약 재핀(description만)

- PR CI의 vnext 계약 테스트 2건이 붉었다 — `openapi.json`(full-admin)이 diff freeze baseline·T-VN-40 receipt와 달랐다.
  merge-base 대비 바뀐 것은 `POST /v1/ops/pipeline/requests`의 409·502·503 응답 description 세 줄뿐이다(schema·
  operation·status code 불변). user/service spec bytes는 그대로라 그 두 핀은 손대지 않았다.
- 생성 스크립트는 없다 — 2026-10-05 ADR-107 선례(acde37264)대로 `openapi-diff-v1.json` admin baseline sha256 +
  revisions 항목, `consumer-rollout-v1.json` T-VN-40 pending receipt의 `map_full_openapi_sha256` + blocking_reason
  문장, 테스트의 `ARTIFACT_SHA256` 두 상수를 갱신했다. 검증(로컬): vnext·contract 단위 135 passed.
- PinVi 측: `apps/api/tests/contract/kor-travel-map-openapi-admin.json`이 full-admin bytes를 vendor한다 — receipt가
  이미 pending(exact re-vendor 대기)이라 이번 bytes도 그 re-vendor에 포함된다. PinVi는 이 operation을 호출하지
  않는다(`/v1/ops/pipeline/*` 읽기만). PinVi 변경은 이 작업 범위 밖이다.

## 2026-10-12 — MOIS ADR-108 narrow 리뷰 MED 1·LOW 3 반영

- **MED-1.** run 전체 비율을 업종 degraded가 있어도 언제나 잰다. 무엇이든 degraded면 조회 50행 미만 업종의 빈 답에도
  표식을 쓰지 않는다 — 큰 업종 하나를 degraded로 만든 지역 장애가 작은 업종들에 남긴 빈 답이 30일 가려지지 않게.
- **L-1.** 다시 풀린 표식 닫기 실패는 `IntegrityFindingPersistenceError`로 정규화해 경고만 남긴다(`transaction_destroyed`면 올린다).
- **L-3.** 연속 degraded 사슬은 최근 500 run까지 보고, 그 안에서 완료 run에 닿지 못하면 degraded로 본다(닫힌 쪽).
- **L-4.** ADR-108 남는 위험에 "문턱 아래·5% 아래 지역 장애는 여전히 표식이 되어 최대 30일 조회되지 않는다"를 되살렸다.
- 검증(로컬): MOIS 적재기 72 passed. mutation 4종(표본 미달 업종 표식·run 전체 판정 생략·사슬 상한 열린 쪽·닫기 실패
  전파) 전부 RED. 통합 테스트는 CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 최종 리뷰 MED 1·LOW 3 반영

- **MED-1.** 표식이 문턱 초과(probe 통과) chunk와 degraded 업종에도 쓰여, 실제 지역 장애가 다음 run에서 표식으로 가려져
  봉인·sync 성공이 남고 overdue도 울리지 않았다. 표식은 run 끝에 한 번, degraded가 아닌 업종에서 문턱 초과가 없던 chunk의
  행에만 쓴다(run 전체 degraded면 쓰지 않는다). 그런 행은 표식 없이 매 run 다시 조회돼 geo가 회복될 때까지 degraded가
  지속된다. 연속 degraded 판정은 직전 완료 전체 run까지의 사슬 전체(`budget_exhausted` 포함)를 본다. ADR-108 정정.
- **LOW.** 로그 문구(degraded 업종은 표식 없이 다음 run이 다시 조회; off 모드 주석은 표식 30일 반영). 다시 풀린 행의 열린
  표식을 닫는다(SELECT 뒤 있을 때만 UPDATE — statement trigger hot row 보호). 표식 기록 실패가 `transaction_destroyed`면
  올린다.
- 검증(로컬): ruff·mypy strict·lint-imports·OpenAPI drift. MOIS 적재기 67 + 관련 498(전체 `tests/lint` 포함) + API 240 passed.
  mutation 5종(문턱 초과 chunk 표식·degraded 업종 표식·사슬을 완료 run만·표식 닫기 제거·destroyed 삼킴) 전부 RED — 앞의 둘은
  지역 장애 테스트에서 서로를 가려 각자 전용 테스트를 더했다. 통합 테스트(표식 닫기 SQL 포함)는 CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 최종 설계: 역지오코딩 불가 표식·조회 행 분모·연속 degraded·SLA

- **원인.** 해상·매립지·잘못된 TM 좌표는 정상 geo에서도 늘 빈 답이라 적재되지 않고 매 run 다시 조회돼, 정상 상태에서
  조회 창·비율을 지배하고 건강한 업종을 매달 degraded로 만든다(MED-1). degraded는 tag·로그로만 보였다(MED-2). 비율이
  미변경 행으로 희석됐다(LOW-1).
- **표식.** geo가 건강할 때(chunk가 장애 판정 없이 commit) 빈 답을 받은 행을 finding `mois_reverse_geocode_unresolvable`
  (info, dedupe key = slug::mng_no, payload.source_record_key = 현재 payload)로 남기고, 다음 run은 같은 payload의 열린 표식이
  30일 안이면 조회·적재하지 않는다(`mois_known_unresolvable`). 새 표 대신 finding 표를 재사용한 이유는 ADR-108 §3a-3.
- **분모.** degraded 비율은 조회한 행 기준(최소 50) — 업종·run 둘 다.
- **드러내기.** 직전 봉인 자격 전체 run도 degraded면 FAILURE(재시도 없음). migration 405가 MOIS bulk policy에 40일 SLA를
  심어 `/v1/ops/datasets` overdue로 보인다(운영자 값 보존). graph artifact는 생성기로, head-schema는 receipt CHECK만.
- **LOW.** 생성 route 주석 정정(seed의 MOIS refresh operation 넷 중 셋은 handler 없음), 죽은 `ensure_mois_source_sync_*`·
  `MOIS_SOURCE_PRECHECK_ERROR_RESPONSES`·`MoisSourceSyncRequired`·테스트(통합 1파일 포함) 제거 — 운영 화면 precheck는 유지.
  비율 설정 `> 0`. 기준점 서울시청 문서화. run 전체 판정 테스트.
- 검증(로컬, n150 미사용): ruff·mypy strict 3패키지·lint-imports·OpenAPI drift·graph `--check`·migration lint. 관련
  테스트 249 + 578(전체 `tests/lint` 포함) passed. mutation 5종(표식 무시·분모 원복·연속 실패 제거·run 판정 제거·표식 미기록)
  전부 RED. 표식 SQL 통합 테스트(`test_fresh_open_marker_matches_only_the_same_payload_and_ages_out`)와 migration 405는 로컬에서
  돌리지 않았다 — GitHub CI가 게이트다.

## 2026-10-12 — MOIS ADR-108 최종 델타 리뷰 MED 1·LOW 2 반영

- **MED-1 지역 geo 장애.** probe가 다른 지역 좌표로 통과해 한 시·도가 통째로 빠진 채 봉인될 수 있었다. 빈 답 행은 어느 모드에서도
  적재하지 않고(off 포함 — 빈 bjd commit은 같은 payload에서 영원히 건너뛰어진다), 업종(관측 200행+)·run 빈 답 비율이
  `KOR_TRAVEL_MAP_MOIS_GEOCODE_DEGRADED_RATIO`(기본 5%)를 넘거나 같은 업종에서 "문턱 초과 + probe 통과"가 3회면 degraded로
  표시한다 — 실패시키지 않고(영구 정지 재발 방지) 봉인·sync 성공을 남기지 않는다. tag `kor_travel_map.mois_load.geocode_degraded`,
  metadata `mois_geocode_degraded*`·`mois_reverse_geocode_empty`·`mois_geo_probes`·`mois_geo_probe_passes`, 경고 로그.
  probe는 고정 기준점과 마지막 좋은 좌표 둘 다 묻는다.
- **LOW.** 생성 route는 MOIS source sync precheck를 부르지 않는다(유일한 MOIS operation이 전용 job 전용이라 도달 불가) —
  409 설명·테스트에서 `MOIS_SOURCE_SYNC_REQUIRED` 제거, 우연히 MOIS dict로 문서화되던 502/503은 실제 원인(geo resolver)으로.
  실행된 scope 없이 `dedicated_job_only`가 섞인 빈 계획은 실패(PinVi target을 갱신됐다고 보고하지 않는다).
- 검증(로컬, n150 미사용): ruff·mypy strict 3패키지·lint-imports·OpenAPI drift·TS 타입(lock 7.13.0) 일치. 지역 장애(drop/off)·off 모드
  재시도·K회 판정·건강한 run 봉인 유지 테스트 포함 296 + 177 passed. mutation 5종(봉인 조건에서 degraded 무시·off 모드 commit·
  K회 판정 제거·probe 좌표 하나·빈 계획 any→all) 전부 RED.

## 2026-10-12 — MOIS ADR-108 델타 리뷰(PR #1312) HIGH 1·MED 1·LOW 4 반영

- **HIGH-1 geo 장애 오판.** drop 모드에서 바다·경계 좌표 행은 적재되지 않아 매 run 다시 변환되고, 재개 run의 조회를 지배해
  비율 판정이 영구 실패를 냈다. 비율이 문턱을 넘으면 `PrefetchingReverseGeocoder.probe_healthy`가 이 run에서 법정동코드를
  받은 마지막 좌표(없으면 서울시청 기준점)를 캐시 없이 다시 묻고, 그것도 빈 답일 때만 장애로 실패한다. 표식 표 대신 probe를
  고른 이유와 대가는 ADR-108 §3a.
- **MED-1 재시도 정체.** run tag에 실제 상한(`…budget_seconds`)과 loop 시작 때 남은 시간(`…budget_available_seconds`)을 남기고,
  0행 정지는 상한 절반 이상을 받은 run에만 적용한다. tag가 없거나 깨지면 이어 달린다.
- **LOW.** (a) 생성 route 409 설명을 실제 409 전부로(dict 병합이 MOIS precheck 설명으로 덮던 것; run-now 설명은 원복),
  OpenAPI·admin 타입은 `openapi-typescript@7.13.0`(lock 버전)로 재생성. (b) plan 선행조건은 큐가 실행할 membership만.
  (c) `policy_disabled`가 먼저, 실패는 건너뛴 것이 전부 `dedicated_job_only`일 때만. (d) `_run_clock_start`가 비숫자·NaN·
  무한·0 이하·미래 start_time을 무시.
- 검증(로컬, n150 미사용): ruff·mypy strict 3패키지·lint-imports·OpenAPI drift·TS 타입 재생성 일치. 테스트 84(새·수정)
  + 377(API 관련) + 163(dagster·lint 관련) passed. mutation 5종(probe 제거·budget tag 무시·any/all·guard 필터 제거·
  start_time 검사 제거) 전부 RED.

## 2026-10-12 — MOIS ADR-108 적대 리뷰 MED 4건·LOW 반영: 브랜치 `feat/mois-chunked-resumable-load`

- **MED-1 소실 하한.** chunk마다 재던 drop 비율 하한을 끄고(`enforce_loss_guard=False`) 업종 누적·최소 표본 200행에서
  데이터 무효(`missing_address`)만 판정한다. 지오코더 원인(`reverse_geocode_failed`)은 따로 세고(다음 run이 다시 변환),
  geo가 최근 20건+ 중 80%+를 빈 답으로 내면 chunk 적재 전 upstream 장애로 실패한다(`PrefetchingReverseGeocoder`의
  최근 창 50건).
- **MED-2 재관측 충돌.** `ProviderEntityReobservationConflict`를 잡아 그 chunk만 run 안에서 최대 2회 다시 확인·적재.
- **MED-3 시간 기준.** run record `start_time`부터 재고, `min(설정, dagster/max_runtime tag - 30분)`. settings 최대값과
  job run 상한의 관계를 테스트로 고정.
- **MED-4 큐.** 정본 `core.feature_operation.DEDICATED_JOB_ONLY_OPERATION_KEYS`. MOIS뿐인 enqueue는 409
  `PROVIDER_DEDICATED_JOB_ONLY`, 섞인 요청은 실행 계획에서 빼고 `done` + error_message, 실행할 것이 MOIS뿐이면
  `failed` + cache target event `error_code=PROVIDER_DEDICATED_JOB_ONLY`(기존 실패 어휘). OpenAPI 409 설명·admin 타입 갱신.
  router 테스트의 큐 sample operation을 MOIS에서 khoa로 바꿨다(MOIS는 이제 큐로 받지 않는다).
- **LOW.** 이어 달리기: 미종료 run 재확인, 0행 전진이면 정지. sync 성공 = 봉인 조건(`authoritative`).
- 검증(로컬 py3.13 venv, n150 미사용): ruff·mypy strict(core/api/dagster)·lint-imports 통과. 관련 unit/api/dagster/lint
  테스트 MOIS 34·executor+provider+prefetch 52·dagster 관련 109·API router 163·API 관련 249·lint 175 passed.
  mutation 8건(chunk 하한 재활성·충돌 재시도 제거·step 시계·장애 판정 제거·0행 정지 제거·활성 run 재확인 제거 등) 전부 RED.
  통합 테스트는 돌리지 않았다(GitHub CI가 게이트).

## 2026-10-12 — MOIS 재개형 chunk commit 적재(ADR-108): 브랜치 `feat/mois-chunked-resumable-load`

소유자가 2026-10-12에 MOIS 적재 재구성을 승인했다(prod `1a3c4673` 읽기 전용 조사: 42업종 약 98만 행, 순차 역지오코딩
약 35시간 vs run 상한 6시간, 단일 transaction, `/tmp` 원천 SQLite). PR·머지·배포·prod 데이터 실행은 하지 않았다.

- **재개 키 = 원천 내용.** chunk(업종 안 최대 500행)마다 `(slug::mng_no, raw_payload_hash)`를 지오코딩 **전에** 계산해
  "head가 같은 payload이고 primary feature가 active인가"를 묻는다(`find_unchanged_active_source_entities`). 그 행은
  `load_bundle`이 관측 시각 말고 아무것도 바꾸지 않는 행이므로 재관측만 하고(`reobserve_unchanged_source_entities`,
  Phase A marker `synced_at` 기준 — 같은 snapshot 재실행은 다시 쓰지 않는다), 나머지만 변환·적재한다. 둘은 chunk
  transaction 하나(`load_feature_bundles_reobserving`). 새 표·cursor·마이그레이션 없음 — `load_bundle`이 읽는 표·열만 읽는다.
- **지오코딩.** kor-travel-geo에 batch endpoint가 없다(geo origin/main `02a3c2e`: `/v2/reverse`·`/v2/geocode` 단건).
  `PrefetchingReverseGeocoder`가 chunk 좌표를 중복 없이 bounded 동시성(`KOR_TRAVEL_MAP_MOIS_GEOCODE_CONCURRENCY`, 기본 2)으로
  선조회하고 run 수명 LRU(5만)에 둔다. 원천 `legal_dong_code`가 있는 행·이미 적재된 행은 조회하지 않는다. 선조회 실패는
  캐시하지 않는다(변환이 한 번 더 시도, 그래도 실패면 예외).
- **run 크기.** `KOR_TRAVEL_MAP_MOIS_LOAD_RUN_BUDGET_SECONDS`(기본 4시간)에서 새 chunk 시작을 멈추고 tag
  `kor_travel_map.mois_load.outcome=budget_exhausted`. `feature_place_mois_licenses_continuation_sensor`(STOPPED)가 같은
  run_config로 잇는다. retry 1회·5분. 월간 schedule은 활성 run과 합친다. 봉인·sync 성공은 전 업종을 한 run에서 끝까지 본
  run만. 큐 runner는 MOIS를 `dedicated_job_only`로 건너뛴다(큐는 쓰기를 한 transaction에 묶는다).
- **원천 영속.** 이미지가 `/opt/dagster/state/mois`(appuser)를 만들고 기본 경로로 둔다. standalone compose volume도 그리로.
  운영은 Manager 브랜치 `feat/map-mois-source-volume`(internal named volume, 경로·target 같은 변수).
- **검증 경로.** run_config `resources.mois_load_plan.config.{service_slugs, run_budget_seconds}`. 절차는
  `docs/etl/mois-license-feature-etl.md` §13.2.
- 테스트(n150, python:3.13, `-c docker/constraints-dagster.txt`, CI 세션 경계 그대로):
  - 정적: `ruff check`(CI 범위) 통과, `mypy --strict` core 153·api 67·dagster 30 파일 이슈 0, `lint-imports` 4 kept.
  - A unit+lint: 3056 passed / 26 failed — 같은 컨테이너의 main(`bcbd14c2`) 기준선과 실패 집합 동일(docker CLI·node·git 소유권
    환경 25건) + `test_orchestrator_guardian_lock_is_not_inherited_by_external_child` 1건(flock/SIGKILL 타이밍 — 부하 중 같은
    컨테이너에서 2/3 실패, 별도 컨테이너에서 4/4 통과, main도 통과; MOIS 무관).
  - B api: 1236 passed, coverage 78.1%(≥70). C dagster: 626 passed·4 skipped, coverage 82.9%(≥80), `mois_chunked_load.py` 95%.
  - 새 통합 `test_mois_resumable_load_repo.py`: 실 PostGIS 4 passed. 전체 D는 n150 IO 포화(`/proc/pressure/io` full avg300 ≈44%,
    `map-load-phase14` 적재 중)로 PostGIS testcontainer가 120초 안에 뜨지 못해 setup error — 두 번. 부하를 더하지 않으려 중단하고
    IO가 가라앉으면 도는 user unit `mois-gate-d-ready`로 넘겼다(로그 `~/mois-gate-logs/d3-*`). GitHub CI가 정본 게이트다.
  - 실제 python-mois-api(3cdee09)를 깐 상태에서 fetcher 업종 선택 테스트 포함 4 passed(CI는 `providers` extra를 깔지 않아 skip).
  - mutation(일부러 깨기): 재개 건너뛰기 제거 → 4건 RED, 선조회 동시성 1로 → 1건 RED, 시간 상한 제거 → 3건 RED. 모두 원복.

## 2026-10-08 — map-marker-react `roadblock`·`warning` 글리프: 브랜치 `feat/marker-roadblock-symbol`

- **변경.** `packages/map-marker-react/src/maki.ts`의 `MAKI_GLYPH`에 `roadblock`(🚧 U+1F6A7, `construction`과 같은
  글리프 — Unicode 바리케이드는 그것 하나다)과 `warning`(⚠, `alert`와 같음)을 더했다. krex 교통 공지와 krforest_safety
  산사태 예보가 첫 글자 배지("R"·"W")로 떨어지고 있었다. 이 패키지의 "심볼"은 SVG가 아니라 Unicode 글리프 표다.
- **누락 조사.** category catalog 58종은 T-017 gate가 이미 막고 있어 누락 0. catalog 밖 provider 상수 중 표에 없던 것은
  위 둘뿐이었다. 그 경로를 지키는 검사가 없어 `test_provider_direct_marker_icons_are_renderable_by_ts`를 더했다(상수
  값 자체를 import해 대조).
- **CI 사각.** 패키지 자체 vitest(`src/maki.test.ts`)는 admin vitest 범위 밖이라 어떤 워크플로도 돌리지 않았다.
  `frontend.yml`에 `map-marker-react unit tests + typecheck` 단계를 넣고 `scripts/verify-all-gates.sh`에도 미러링했다.
- **테스트(n150, node:22.23.1).** marker vitest 4 passed·typecheck 0; admin vitest 46 files/391 passed(첫 실행 1회 exit 1 —
  출력이 잘려 원인 미확인, 재실행 2회 green), admin type-check·lint 0, next build(CI env) 성공. Python: drift 2파일 6 passed,
  새 provider-direct 검사는 `maki.ts`에서 두 키를 지우면 `['roadblock', 'warning']`으로 RED; workflow·mirror 포함 38 passed;
  ruff 통과. npm 게시 없음(ADR-043). kor-travel-transport의 vendored 사본도 같은 내용으로 다시 복사했다.

## 2026-10-07 — entrypoint 봉인에서 `api grpc` 제거: 브랜치 `chore/entrypoint-drop-api-grpc`

- **변경.** `docker/dagster-entrypoint.sh`의 production `/usr/local/bin/dagster` 봉인이 하위 명령 `code-server start`
  하나만 받는다(9-argv, loopback `-h`, 숫자 `-p`, 고정 `-m` 그대로). 최상위 `api grpc`는 location reload를 무시해서
  전환용으로만 남아 있었고, Manager compose(#1295)·standalone compose(#1304)가 모두 옮겨 쓰는 곳이 없다. 거부 문구는
  다른 모양과 같다. local-dev의 preflight 분기에서도 `api grpc`를 뺐다.
- **테스트.** `test_dagster_production_code_server_rejects_other_shapes`에 `api grpc`를 넣어 n150에서 먼저 RED(1 failed)를
  보고 고쳤다. accepts는 `code-server start` 정확한 argv 하나, runtime-preflight 목록에서 `api grpc` 행을 뺐다.
  n150: `ruff check`(CI 범위) 통과, `test_docker_dagster_runtime.py`+code-location+constraints 332 passed / 14 failed —
  실패 14건은 main(8f9dd1cb) 기준선과 같은 집합(frontend dotenv validator·local admin stack 등 환경 의존).
- **실측(throwaway, 운영 Map code-server 이미지 `197597501a0b`, rev 1a3c467).** 새 entrypoint를 읽기전용 마운트:
  `api grpc` → rc=1 + 봉인 문구, `code-server start` → 35초 안에 `ListRepositories` 610 bytes(정상 응답, 오류 없음).
  proxy의 자식 `python -m dagster api grpc --socket …`은 entrypoint를 지나지 않아 영향이 없음을 프로세스 목록으로 확인.
  이미지 자체 entrypoint는 `api grpc`를 여전히 받는다(대조). 컨테이너·임시 파일 정리 완료.
- **배포.** 하지 않았다. 다음 Map pinned-pair 회전 때 반영되며, 운영은 이미 `code-server start`라 안전하다.

## 2026-10-06 — Map·PinVi 공통 Dagster 구현·재구축·live·머지 완료

[Common #28](https://github.com/digitie/kor-travel-common/pull/28) → [Map #1303](https://github.com/digitie/kor-travel-map/pull/1303) → [PinVi #576](https://github.com/digitie/pinvi/pull/576) 순서로 병합했다. Common·Map은 merge commit, PinVi는 main ruleset의 squash-only·linear history 정책에 따라 squash로 병합했다. PinVi 재구축 원본0058369와 검증 HEAD92d0f40는 remote tags codex/pinvi-map-runtime-20261006·codex/pinvi-map-reviewed-20261006 및 유지한 feature branch에 원본 이력을 보존했다. 저장소 설정은 변경하지 않았다. 최종 문서 포함 HEAD의 필수 CI, Common·Map main ancestry와 PinVi 보존 참조, 병합 tree 일치를 확인했다. 실제 paired 재구축, 두 독립 FULL 제품 리뷰·가이드 리뷰·최종 문서 리뷰, Chromium/Firefox×Map/PinVi live UI4건·8캡처, ACL40·D1 11건·D2 normal/attempt0·소유 fixture 정리·잔존0 검증을 완료했다.

머지 후 운영 API/UI/Dagster 여섯 이미지의 healthy 상태·설치 코드·배포 source·committed transaction이 기존 성공 증거와 같음을 실제 read-only 재확인했다. 최종 제품 Common a960bdb/Map1a3c467/PinVi0058369에 문서만 추가됐으며 재구축·장애 주입을 머지 HEAD에서 새로 실행한 것으로 집계하지 않는다. 격리 Map native raise/crash/stall·동시 정상 run·수동 복구는 관련 설치 코드/버전 불변 범위에 한정한다. 공유 운영 worker 장애 주입·운영 RSS 감소율은 미실측이다.

이 요청의 T-COMMON-DAGSTER는 완료 원장으로 이동한다. 기존 외부 transport/HAProxy 및 다른 미완료 task는 유지한다. 다음 작업은 기존 열린 backlog의 우선순위를 따른다.

[머지 후 실제 상태 증거](../reviews/common-dagster-2026-10-05/evidence/final-postmerge-runtime-attestation.json), [가이드·실패·리뷰·수용 이력](../reviews/common-dagster-2026-10-05/README.md). 아래 문단은 각 작성 시점의 이력이며 이 절이 최신 상태다.

## 2026-10-06 — Map·PinVi 공통 Dagster 실제 재구축·live 수용 완료

Common a960bdb, Map 1a3c467, PinVi 0058369의 제품113파일 두 독립 FULL 리뷰와 가이드 리뷰를 통과했다. 공용 Python은 bounded HTTP·경량 child health·실행 복구 정책을 제공하며 앱의 operation/lease/claim·비멱등 쓰기 계약을 유지한다. 요청별 응답4MiB/10초와 정리50ms, DB pool/step 제한·100개 batch를 적용했다. Map tick 조회의 오래된 batch history 정렬 지연은 상태 조건을 명시하여 native indexed LIMIT 경로로 줄였고 실제 summary/UI 복구를 확인했다.

운영 paired 재구축과 설치 source·관련 Common bytes·실제 이미지 identity·여섯 서비스 healthy를 검증했다. Chromium/Firefox×Map/PinVi 실제 UI4건과 캡처8개를 직접 확인했다. ACL40·D1 11건·D2 정상 수용/validator·소유 fixture purge1/7·잔존0/ACTIVE없음/BLOCKED없음까지 통과했다. Common의 ESM export를 읽기 위한 type=module은 별도 테스트 이미지 package.json에만 추가하고 실제 마지막 layer/semantic delta를 증명했다. 앞선 모든 실패·초기 BLOCK와 수정 후 PASS 원문은 보존한다.

격리 native Dagster에서 실제 raise·worker crash·stall/timeout 뒤 수동 재시도와 동시 정상 job을 확인했다. 최종 Map 운영 Dagster 이미지의 관련 설치 코드와 버전이 이전 격리 이미지와 같은지, 실제 최종 이미지 ID가 배포 기록과 맞는지 독립 검증했다. 이 결과는 해당 불변 코드 범위에 한정해 이어받는다. 공유 운영 DB의 worker 장애 주입이나 운영 RSS 감소율 실측으로 설명하지 않는다. 유한 응답·batch·동시성 구조와 합성 메모리 측정은 운영 RSS와 구분한다. 기존 인간 dirty checkout·외부 transport/HAProxy 후속은 보존한다.

도구 제한: Map own CodeGraph의 최종 sync/status는 NTFS disk I/O error로 완료하지 못했다. 기존 격리 인덱스와 SQLite immutable quick_check 정상은 보존했으며 원본 인덱스/프로세스의 강제 정리는 하지 않았다. 마지막 제품 변경은 tick 조회 조건과 C7 테스트 Docker COPY 순서이며 공개 Python/DTO 계약은 유지한다.

다음 한 작업은 문서 포함 exact HEAD CI 통과 후 Common #28 → Map #1303 → PinVi #576 순서로 merge commit 병합하는 것이다. 제품 Git pin의 ancestry를 보존한다. 이 절이 현재 상태이며 아래의 진행 중/NOT_RUN 문단은 이전 시점의 이력이다.

[실제 검증·리뷰 원문과 실패 이력](../reviews/common-dagster-2026-10-05/README.md), [공통 적용 가이드](../runbooks/common-dagster.md).

# journal.md — 작업 일지 (역시간순)

## 2026-10-05 — child health의 reserved metadata marker 차단 채택

Common 경량 probe의 독립 리뷰 반례(pointer/library map의 reserved serdes marker)를 차단하고 정상 default repository __repository__를 허용하는 profile을 API·Dagster 동일 Git revision으로 채택한다. unsupported stateful/custom metadata는 fail-closed하며 가이드에 지원 경계를 명시했다. 두 독립 재리뷰·현재 CI·실제 PinVi/Map paired 재구축/live는 아직 진행 중이다.

## 2026-10-05 — child health의 nested metadata 검증 채택

Common 경량 probe의 독립 리뷰 반례(null/미등록 pointer, 잘못된 executable/entry point 타입)를 반영한 표준 module/file/package profile을 API·Dagster 동일 Git revision으로 채택한다. unsupported stateful/custom metadata는 fail-closed하며 가이드에 지원 경계를 명시했다. 두 독립 재리뷰·현재 CI·실제 PinVi/Map paired 재구축/live는 아직 진행 중이다.

## 2026-10-05 — standalone 자식 저장소 응답 fail-closed 보강

최신 main #1304를 반영한 두 독립 리뷰에서 한 리뷰어가 빈 protobuf/잘못된 JSON이 substring 건강 점검을 통과하는 P2를 실제 reply fixture로 재현했다. 기존 PASS와 BLOCK 원문을 모두 보존한다. Common의 경량 `dagster_health`를 사용하여 proxy 뒤 자식의 정상 class·symbol schema와 wire/JSON을 검증한다. Dagster 전체 import를 피하며 각 RPC 4초·수신 4MiB·channel 정리를 유지한다. standalone은 건강 판정만 하므로 unhealthy 자체를 자동 재시작으로 설명하지 않는다. 새 source pin·두 리뷰·CI·운영 재구축/live는 아직 미완료다.

## 2026-10-05 — 요청 단위 Dagster client의 PostGIS fixture 정렬

Map CI의 glibc·alpine 통합 lane에서 동일한 projection 테스트 한 건이 실패했다. 앱 전역 client 주입을 제거한 뒤 기존 fixture가 실제 연결로 빠진 것이 원인이다. 두 schedule fixture에 요청마다 새 MockTransport client를 주입하고 실제 middleware의 정리를 유지했다. catalog 회귀도 schedule source가 `ok`인지 단언하여 묵시적 degrade를 막는다. 운영 Python·UI 코드는 이전 고정 후보와 동일하다. 실제 PostGIS 관련 22개 검사를 통과했으며 전체 CI를 다시 확인한다.

## 2026-10-05 — Map·PinVi 공통 Dagster 보강 (진행 중)

ADR-107과 [적용·복구 가이드](../runbooks/common-dagster.md)에 따라 공통 Python HTTP/Dagster·로그인·메뉴·대시보드를 채택했다. 요청별 연결·응답/시간 상한·활성 run 별도 조회·step/DB 연결/100개 batch를 적용한다. 쓰기 run 자동 복제 없이 기존 operation/lease/claim 복구 계약을 유지한다. [검증 기록](../reviews/common-dagster-2026-10-05/README.md)의 고정 후보 2인 리뷰·운영 재구축·live·CI·merge를 완료해야 한다. 원래 인간 dirty checkout은 보존했다.

적대적 원본 리뷰의 실패 상세·event cursor 회귀와 손상 Repository의 정상 빈 snapshot 오인을 보강했다. 선택한 run만 상세 조회하며 Docker deps에 고정 Common vendor를 복사한다. UI 390/API shape 24/strict mypy 96 및 production Next build PASS. React Doctor의 불필요한 mapper export를 제거했다. 후속 리뷰의 repository 소속 불일치도 selector identity와 비교하여 fail-closed하고 다른 location의 행을 제거했다. 정상 empty와 외부 name/location을 실제 HTTP 응답 fixture로 구분한다. 검색으로 선택한 run의 행이 숨겨져도 상세에 job/run identity·상태·시간 상한을 명시하여 다른 작업의 실패로 오인하지 않도록 보강했다. 후속 immutable 2인 FULL 리뷰·exact CI·실제 paired 재구축·live gate는 아직 미완료다.

## 2026-10-05 — standalone compose code-server를 `code-server start`로: 브랜치 `chore/standalone-compose-code-server-start`

- **변경.** `docker-compose.yml`의 `dagster-code-server` command가 `dagster api grpc`에서 운영(Manager)과 같은
  `dagster code-server start -h 127.0.0.1 -p ${PORT} -m kortravelmap.dagster.definitions`가 됐다(#1295 봉인이 받는 모양).
  `api grpc`는 location reload를 무시해서 import 때 읽는 schedule override가 반영되지 않는다. host·external-infra
  overlay는 command를 건드리지 않는다.
- **healthcheck.** 옛 probe(`DagsterApi` health → SERVING)는 `code-server start`에서는 proxy만 본다 — proxy health는 자식이
  load error여도 SERVING이다. proxy health 뒤 자식에 전달되는 `ListRepositories`를 raw bytes로 불러
  `SerializableErrorInfo`면 실패한다(dagster import 없음, 4초 deadline 둘). Manager probe의 PID 1 종료·orphan run 정리는
  standalone에 옮기지 않았다(판정만).
- **테스트.** `test_standalone_compose_code_server_is_reloadable_and_sealed`: compose argv 정확 일치 + 그 argv(포트 기본값
  풀어)를 실제 entrypoint 봉인에 넣어 통과 + probe가 `ListRepositories`/`SerializableErrorInfo`를 본다. dagster 프로세스
  서비스 유도 marker를 `dagster api grpc` → `dagster code-server start`로 바꿨다. 먼저 RED(2 failed: argv 불일치,
  유도 서비스 2개) 확인 후 GREEN.
- **n150 증거.** 영향 파일 3개(`test_docker_dagster_runtime.py`·`test_c7_prod_runtime.py`·
  `test_n150_repin_derives_dagster_services.py`) 368 통과/13 실패 — 13건은 main과 같은 집합(n150 checkout에 frontend
  node_modules 없음). CI 범위 ruff 통과. `docker compose config` base·host·external-infra 셋 다 `code-server start`로 렌더.
  live Map dagster 이미지로 일회용 컨테이너(host network, 빈 loopback 포트): 정상 모듈은 compose probe rc=0(~40초),
  `dagster api grpc-health-check` rc=0, `ListRepositories` 응답이 `ListRepositoriesResponse`. 없는 모듈은 compose probe
  rc=1인데 proxy health는 SERVING, `grpc-health-check`는 rc=0 — CLI probe로는 load error를 못 잡는다는 실측. 컨테이너는 치웠다.
- **남은 것.** entrypoint 봉인에서 `api grpc` 제거(이제 어느 compose도 쓰지 않는다).

## 2026-10-05 — 인계 문서와 n150 보조 스크립트를 저장소에 남김

- 세션 교대(다음 에이전트: Codex)를 위해 `docs/handoff/2026-10-05-shared-dagster-handoff.md`에 상태·진행 중 작업·
  TODO 7개·n150 운영 절차·실제로 밟은 함정을 정리했다. 운영 값은 넣지 않았다(#508).
- `docs/handoff/n150-scripts/`: `preflight.sh`(변경 전 사전 점검), `guarded-rb.sh`(실패 시 즉시 docker start하는
  pinned rebuild), `transport-deploy-unit.sh`, `weather-deploy.sh`, `dagster-job-status.py`. n150 `~/`에 실제 호스트가
  든 사본이 있다.
- 2026-10-03~04 사고 요약: 옛 메타DB 차단 뒤 rebuild가 옛 storage migrate에서 실패(→ Manager #459), 부하 cold start가
  healthcheck 창 초과(→ #460), C6c smoke 첫 요청 timeout(→ #461), D2 fixture가 실패 경로 정리를 거부(→ #1297).

## 2026-10-04 — D2 실패 run이 `cleanup-failed`로 굳던 결함: 브랜치 `fix/d2-fixture-restored-audit`

- **무엇이 일어났나.** D2(run `live-20261004102457-782ce6e6b79b`, a68c2b7d)의 main spec이 create 응답을 받지 못해
  실패했다. create 트랜잭션은 10:36:31.7Z에 시작해 약 10:37:01.4Z에 커밋됐다(약 30초). API access log에는 그 POST가
  없다 — 응답 전에 클라이언트가 떠났다. spec `finally`가 Feature를 `:cleanup`으로 은퇴시켰고, helper api-audit은
  완주 사슬과 `:retire` lifecycle override만 받아 `API-owned field override 소유권이 다릅니다`로 죽었다 → BLOCKED
  `cleanup-failed`(원래 `test-failed-restored`). 같은 감사를 부르는 `recover`와 helper `purge`도 구조적으로 통과 불가였다.
  #1296(transport consumer)은 무관하다 — field override·admin create 경로를 건드리지 않는다. 동시 Map Dagster run도 없었다.
- **고침.** lifecycle override의 reason을 **실제로 은퇴시킨 전이의 reason**(`:retire`|`:cleanup`)에 결박했다.
  `api-audit --expect complete|restored`: 러너가 spec 실패 시와 `recover`에서 `restored`를 넘긴다(생략=complete라
  clone lane은 그대로). 복구 증거 검증기는 restored 모양을 받고 purge `purged`를 감사한 개수와 대조한다.
  `feature_uuids` 길이를 `counts.features`에 결박했다(적대 리뷰 LOW1).
- **테스트.** `tests/unit/test_d2_api_owned_restored_audit.py`는 prod에 남은 행을 그대로 옮겼다. 고치기 전 a68c2b7d 코드가
  같은 행에 prod와 똑같은 오류를 낸다는 것을 n150에서 재현했고, 새 테스트는 먼저 빨갛게 확인했다.
- **~30초 절단은 저장소 밖이다.** Playwright(`page.evaluate` fetch 무제한, test 5분), Next proxy route(timeout 없음,
  abort signal만 전달), API(요청 timeout 없음) 어디에도 30초가 없다. D2는 `https://<map-ui-host>`로 가고
  n150에는 443 listener가 없다 → OPNsense HAProxy edge. H27은 `timeout tunnel 1h`만 바꿨으므로 기본 `timeout server`
  30초가 남아 있을 가능성이 가장 높다(라우터 설정은 직접 읽지 못했다 — 추정).
- **현재 BLOCKED 정리.** a68c2b7d로는 lane 복구가 불가능하므로 n150 `~/d2-adjudicate-782ce6e6.sh`(0600, 미실행)에
  판정 스크립트를 두었다: 잔여물 정확 대조 → `feature.purge_manual_feature`(감사되는 purge 명령) → 정본
  `scripts/n150/adjudicate.sh` → 운영자 메모·run dir 사본 보관. `--dry-run`이 먼저다.

## 2026-10-04 — delta 리뷰 반영: 같은 브랜치 `fix/transport-consumer-lows`

- **MED 회귀.** `_TransportTransientStatus`(HTTP 층 재시도를 다 쓴 502/504)가 부모의 `retryable=False`를 물려받아
  새 경계가 짧은 transport 재기동을 terminal로 만들었다(하루치 유가 손실). `retryable=True`·`failure_kind=
  transport_transient_status`. 다른 하위 클래스(NotCurrent True, Malformed·Empty·Hidden·ContractError False)는 의도대로다.
  경계 테스트에 503·502를 "재시도가 남아야 하는" 경우로 넣었다.
- **LOW** 경계의 원인 추적은 `__cause__`만 따른다(`__context__`는 처리 중 난 다른 실패).
- **LOW** locator 경고 logger(`kortravelmap.infra.feature_repo`)를 `docker/dagster.yaml` `managed_python_loggers`에
  더했다(lint로 결박). 공용 Dagster plane에서는 instance 설정이 Manager 쪽이므로 그쪽 목록에도 있어야 run 로그에 보인다.

## 2026-10-04 — transport 소비 후속 적대 리뷰 반영: 같은 브랜치 `fix/transport-consumer-lows`

- **MED locator 한 행이 전체를 죽였다.** `list_primary_place_locator`가 검증 없는 코드 칼럼으로 엄격한 `Address`를
  만들어, `manual_override` 하나(시군구만·오타)가 목록 전체를 `ValidationError`로 실패시켰다 — 모든 가격 run이
  실패하고 override가 provider 보정을 가리므로 저절로 낫지 않는다. 행마다 만들고 걸리면 빈 주소 + feature id 경고.
- **LOW 2·3 `retryable`이 행동을 바꾸지 않았다.** `FEATURE_LOAD_RETRY_POLICY`는 쿼터 말고 모든 예외를 다시 돈다.
  asset 경계가 `retryable=False` transport 실패(hidden·empty·contract·malformed)를 쿼터 소진과 같은 방식으로
  `Failure(allow_retries=False)`로 바꾼다(`raise_terminal_if_transport_unrecoverable`). 503만 재시도로 남는다.
  테스트는 `run_tracked_feature_asset`를 실제로 돌린다(두 갈래 × 네 종류).
- **LOW 6** 바깥 run 예산이 열린 채 다른 예산을 넘기면 `ValueError`(종전은 조용히 무시).
- **LOW 7** 감사 기록 실패·timeout·비-2xx는 `console.warn`(이벤트 종류·결과·오류 이름/HTTP 상태만, 비밀값 없음).
  테스트는 `vi.restoreAllMocks()`로 spy를 되돌린다.
- **LOW 5(수용, 기록).** 가격 feature가 place의 시군구 코드를 갖게 되어 시군구 범위 refresh가 이제 가격
  dataset도 포함한다. 첫 적재는 기존 가격 feature 주소를 한 번 고쳐 쓴다.
- **큐 경로 503(결정: 유지).** 큐 run의 실패한 update request는 원인과 무관하게 그 request로 끝나고 다시 큐에
  넣지 않는다. 다음 schedule/request가 다시 돈다. dagster README·ADR-106에 적었다.

## 2026-10-04 — transport 소비 후속(적대 리뷰 잔여 Low 다섯): 브랜치 `fix/transport-consumer-lows`

- **재시도 예산은 run 하나에 하나.** ADR-106 리뷰 M8은 "run 예산 공유"라고 적었지만 실제로는 fetcher 호출마다
  `RetryBudget()`을 새로 만들었다. 큐 run 하나는 scope 여러 개(주유소·휴게소·돌발·공항)를 돌므로 transport가
  내려가 있으면 scope 수 × 예산만큼 재시도했다. `upstream_retry.sharing_run_retry_budget()`(ContextVar)를
  asset step(`run_tracked_feature_asset`)·큐 op(`execute_feature_update_request`)·scope runner가 열고, 안쪽은 바깥
  예산을 그대로 쓴다. 테스트: 예산 1에서 세 fetcher가 연결 오류면 요청 4건(종전 6건).
- **failure_kind 분류.** 503·`collection` 어긋남(`transport_not_current`)은 `retryable=True`인 step 실패다 — HTTP
  층에서 바로 다시 부르지 않고 `RetryPolicy`가 step을 다시 돈다(경계는 원 예외를 그대로 낸다). 공항 0건은
  계약 위반이 아니라 `transport_empty`, JSON이 아닌 본문은 미분류 `JSONDecodeError`가 아니라
  `transport_malformed_upstream`(`TransportExportMalformed`)이다. 나머지는 `retryable=False`.
- **가격 feature 지역 코드.** transport 이관 뒤 주유소·휴게소 가격 feature는 `Address(road=...)`만 가져 bjd·시도·
  시군구가 비었다(옛 OpiNet 경로는 주유소 place 주소를 그대로 썼다). transport export에는 지역 코드가 없고 가격 job은
  역지오코딩하지 않으므로(M5) `list_primary_place_locator`가 place의 `legal_dong_code`·`admin_dong_code`·`sido_code`·
  `sigungu_code`·행정동 주소를 함께 싣고 가격 feature가 이어받는다. locator 행은 5-tuple이 됐다.
- **관리 UI 로그인 감사.** `recordAuthAuditEvent`의 fetch에 `AbortSignal.timeout(3000)` — 감사 API가 멈춰도 로그인
  응답이 붙잡히지 않는다(vitest).
- **문서.** transport 설정 표(BASE_URL·SERVICE_TOKEN·PAGE_SIZE·TIMEOUT_SECONDS)와 failure_kind 표를 dagster README에,
  integration-map은 peer 주소 게이트(`Host` 아님)·export별 응답 모양으로, settings 설명의 "Host로 닫는다"를 고쳤다.
  dagster README의 옛 `opinet_*`·`krex_*`·`krairport_*` resource/env/schedule 행과 external-apis의 OpiNet·KREX 키 행을
  정리했다. main의 `docs/resume.md`·`docs/journal.md`에 남아 있던 merge 표식 줄(`||||||| parent of 866d318c6`)도 지웠다.
- **RED → GREEN(n150 `~/ci-scratch/ktm-lows`, Python 3.14).** 테스트 커밋 `1bea708d8`: unit 5 실패, dagster 경계 3
  실패 + fetcher 테스트 collection 오류. 수정 head: 같은 표적 191건 통과. 전량: ruff check·lint-imports(4 kept)·
  mypy --strict 세 패키지 통과, unit+lint 3035 통과/16 실패(`test_docker_dagster_runtime.py` 13건은 main과 같은 집합 —
  n150 checkout 환경, 나머지 3건은 부하 아래 signal/lock 타이밍이라 재실행 통과), api 1217·dagster 582 통과,
  vitest RED(1 실패) → GREEN, tsc·eslint 통과.

## 2026-10-02 — Dagster entrypoint가 `code-server start`를 받는다: 브랜치 `fix/dagster-entrypoint-code-server`

- **원인(n150 prod 2026-10-01 21:52Z).** C7 schedule-write spec은 cron override를 `ops.dagster_schedule_overrides`에
  저장하고 location을 reload한다. Map은 override를 definitions import 때 읽는다. 그런데 code-server가 `dagster api
  grpc`라 reload는 "not currently supported" 경고만 남기고 무시됐다 — override가 반영되지 않아 C7이 빨갛다.
- **변경.** production 봉인의 code-server 분기가 하위 명령 `code-server start`도 받는다. 모양(9 argv, loopback `-h`,
  숫자 `-p`, 고정 `-m kortravelmap.dagster.definitions`)은 그대로 정확 일치다. `api grpc`는 Manager compose가 바뀔
  때까지의 전환용으로 남긴다. local-dev 분기도 같은 두 모양에서 runtime preflight를 돈다.
- **`-I`는 자식에 이어지지 않는다.** `code-server start`의 proxy는 자식을 `sys.executable -m dagster api grpc`로
  띄운다(run worker는 `api grpc` 때부터 같았다). user site는 요구된 `PYTHONNOUSERSITE=1`이, `PYTHONPATH`·`PYTHONHOME`·
  `PYTHONUSERBASE`는 기존 거부가 env로 자식까지 막는다. 남는 cwd-on-`sys.path`(`-P`)는 production exec 직전
  `PYTHONSAFEPATH=1`로 막는다(cwd `/app`은 root 0555라 지금도 쓸 수 없지만 기대지 않는다).
- **n150 실측(Manager 브랜치 `fix/dagster-code-server-reloadable`과 함께).** live Map dagster 이미지(1.13.24)로 일회용
  컨테이너를 빈 loopback 포트에 띄웠다: `api grpc`는 reload를 무시(import 1회), `code-server start`는 새 자식 pid로 다시
  import했다. proxy health는 고정 SERVING이라 Manager probe가 자식에 전달되는 `ListRepositories`를 보고 확정된 실패면
  PID 1을 끝낸다(load error·자식 kill 둘 다 재시작 확인).
- **테스트.** 두 모양 수용(자식 env에 `PYTHONSAFEPATH=1`), 섞인 하위 명령·`-h 0.0.0.0`·다른 `-m`·`-f`·추가 인자 거부,
  runtime preflight 매트릭스에 `code-server start`(production·local-dev) 추가.
- **남은 것.** 저장소 자신의 `docker-compose.yml`(standalone)은 `api grpc` 그대로다 — 바꾸면 Manager처럼 probe를
  자식에 묶어야 한다(후속).

## 2026-10-02 — 주유소·휴게소·돌발·공항 원천을 kor-travel-transport export로 이관(ADR-106): 브랜치 `feat/transport-api-sources`

- 소유자 결정: Map에서 transport로 얻을 수 있는 것은 transport API로 바꾸고, 필요하면 transport API를 고친다. OpiNet은
  transport 브라우저 수집본을 쓴다. 공항도 옮긴다. 새 provider 정체성 `kor-travel-transport`(internal) + identity 재지정
  보험. prod Map DB는 비어 있어(예상) shadow 없이 바로 전환한다.
- transport 쪽(`kor-travel-transport` 브랜치 `fix/fuel-latest-prices-incremental` → `feat/map-service-exports`): 최신 유가
  MV가 60초 timeout으로 영구 stale이던 것을 증분 테이블로 고쳤고(0022), 휴게소 기준정보·휴게소 유가 수집기와
  `GET /v1/service/exports/*`(토큰 + loopback Host, 404 은닉), 돌발 활성 집합(수집 실패·30분 정체면 503), 공항 15곳(KPO
  포함)을 더했다(transport ADR-013).
- Map: `providers/kor_travel_transport.py`(계약·엄격 파서), fetcher 5개(`fetch_transport_*`), asset/job/operation 6개를
  `*_transport_*`로 바꿨다. 정규화는 `opinet.py`·`krex.py`·`krairport.py`에 남고 provider 정체성만 바뀐다. migration
  `404_transport_provider_identity`가 새 dataset·operation·scope를 넣고 옛 identity를 옮기고(옛 돌발 entity가 있으면
  중단) 옛 적재를 끄고 계보 함수의 돌발 분기를 옮긴다.
- 지운 것: OpiNet 호출 예산·scope 모드·KST 일일 coalescing·POI target scope, krex 이중 snapshot 안정성 검사, krex rate
  gate 선언, krex/opinet 쿼터 예외 선언, 세 provider 핀, `KOR_TRAVEL_MAP_OPINET_*`·`KOR_TRAVEL_MAP_KREX_*` env.
- 적대 리뷰 반영(같은 날): 신선도를 두 겹으로 — transport는 이력 없음·실패·stale이면 모든 export에서 503,
  Map은 `collection` 플래그·완전 snapshot 0건·돌발 `collected_at` 30분을 다시 재고 `failure_kind`
  (`transport_not_current`·`transport_empty`·`transport_hidden`)로 실패한다(아무것도 지우거나 닫지 않는다).
  404는 자격증명 부재와 갈랐다. 유가 `observed_at`은 transport `collected_at`(마지막 확인)이다 — 오피넷
  `*_DT`(가격을 바꾼 때)를 쓰면 가격을 유지하는 주유소가 4일 지평선 밖으로 사라진다. 유가 job은 주유소를
  역지오코딩하지 않는다(locator로 부모만). UI "과거 날짜" 표식은 가격 도메인으로 고른다. 404 migration은
  옛 preview operation도 끈다. 페이지 상한·cursor 순환 검출·전송 오류 재시도를 더했다.
- C7: 공항 operation은 이제 transport 내부 export를 한 번 부른다. 계약 테스트를 "외부 provider 호출 0"으로 고쳐 적었다
  (`_transport_get`은 공항 export 상수로만 허용, 다른 경로는 빨강).
- 계약 관계(2026-10-03 소유자 결정): Map은 transport export의 소비자다 — pin·vendoring·repin 절차 없음. Map에
  필요한 필드·모양은 transport API를 직접 바꾼다(같은 PR 쌍, 호환 층 없음). 어긋남은 엄격한 런타임 검증이
  `failure_kind`로 실패시킨다. 대표 응답 5종(`tests/unit/golden/kor-travel-transport/`)이 실 파서를 지난다. 처음
  만들었던 vendored OpenAPI·`PIN.json`·repin 스크립트는 같은 날 지웠다.

## 2026-10-02 — ADR-105 적대 리뷰 반영: 같은 브랜치 `feat/remove-map-kma-dagster`

- **MED-1 PinVi가 다음 짝을 막는다.** Manager M05 harness가 OpenAPI hash 불일치를 거부하고 PinVi 계약 테스트가
  `BeachPublicView.latest_weather`를 단언한다. PinVi 브랜치 `chore/map-drop-weather`에서 재vendor한다. 순서: PinVi PR →
  Map PR → pair 회전.
- **MED-2 probe.** `cache_target_snapshot_gc`는 prod에서 돈 적이 없어(schedule STOPPED) 첫 gate가 GC 적체(최대 2,000
  batch)를 health check 안에서 지울 수 있었다. 전용 no-op job `map_run_heartbeat`를 두고 lint를 성질(resource ⊆
  {io_manager}, kortravelmap import 없음, run config 불필요, operation key 없음, in-process 성공)에 결박했다. 옛 기본값으로
  되돌리면 4개가 빨갛다.
- **MED-3 C7 왕복 복원.** KMA write spec이 덮던 "요청 → queue sensor → worker → 종결"을 krairport(번들 정적 데이터,
  upstream 0)로 되살렸다. 실제 prod write(공항 place 15건 멱등)다. 공유 plane Basic Auth 파일을 다시 읽는다.
- **LOW.** 401에 in-flight preflight(같은 upgrade에서 402의 `is_enabled` 필터를 빠져나가던 구멍; 막지 않으면 통과하는
  통합 케이스 추가), 403으로 lineage 함수의 KMA 분기 제거(앱 식과 DB 함수의 분기 집합 일치 unit 테스트 추가), 핀 제거,
  `.env.example` 키·stale docstring·삭제된 schedule mock 정리. frozen H35 replay의 KMA 텍스트는 해시 고정이라 남겼다.
  매분 schedule의 RUNNING 상태 행은 회전 전 stop(runbook)으로 처리한다 — Map에 RUNNING schedule이 0이어도 gate는
  SCHEDULER daemon heartbeat만 보므로 바닥이 빨갛게 고정되지 않는다.
- **n150 게이트(`9de7630`).** unit+lint 3,047 passed / 14 failed(main도 같은 환경 실패 15건 이하), API 1,217, Dagster 624,
  ruff·mypy 3패키지·lint-imports·graph check 통과. 통합 전량 1,106 passed / 2 failed(main에서도 실패하는 docker effect) /
  25 errors(bootstrap 19 환경, glibc collation 6은 단독 재실행 6/6 통과). `test_weather_removal_migration` 3/3(신규 400→402
  in-flight 중단 포함), `test_notice_lineage_key` 전부 통과, `head-schema.sql`은 재생성과 동일. probe lint는 기본값을
  `cache_target_snapshot_gc`로 되돌리면 4/20 빨강. 첫 실행에서 루트 설정의 경고→오류 때문에 setup ERROR 6건이 났다 —
  ERROR는 빨강이 아니므로 필터를 달고 다시 쟀다.

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

