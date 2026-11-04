# journal 아카이브 — 2026-10-13 (f)

> live journal이 220 KiB 경계를 넘어 가장 오래된 완전한 절 셋을 분리했다(docs/tasks-rule.md §8, #1444 리뷰 PR). 세 절에 상대 링크가 없어 본문은 바꾸지 않았다. 읽기 전용 이력이다.

## 2026-10-13 — 공용 PG lock table 고갈(53200) 근본 수정 — Feature advisory fence 전역 gate(ADR-111): 브랜치 `fix/bulk-curation-locks` (PR #1319)

2026-10-12 09:25Z부터 root `97ac4e01-…`의 `feature.finalize_provider_curation_root`가 dataset 99(`transport_fuel_stations`,
11,820 Feature)의 링크 Feature마다 `pg_advisory_xact_lock('feature-write:<id>')`를 잡다가 공용 PG(`max_locks_per_transaction=64`)
lock table을 고갈시켜 SQLSTATE 53200으로 롤백됐고, reconcile sensor가 30초마다 무한 재시도하며 같은 cluster 전 tenant를
깨뜨렸다(12:59:54Z prod sensor 정지 — 운영자 조치, 이 PR 범위 밖). 같은 패턴이 프로시저 여덟 곳에 더 있었다.

- **설계(ADR-111).** 전역 gate `feature-write-all`: 대량 writer 9개(finalize root·receipts, materialize, curated
  source/rule/theme create·patch·archive)는 종전 Feature 잠금 루프 자리에서 gate **배타** 1회, 단건 writer 6개(approve
  request, curation item create/patch/archive, manual item, promote candidate)는 `feature-write:<id>` 바로 앞에 gate **공유**.
  순서 `curation-import → feature-curation-write → feature-write-all → feature-write:<id> → curation-catalog-write`.
  "Feature 잠금을 그냥 지운다"는 기각 — curated theme/source/rule 명령·promote·approve는 `feature-curation-write`를 잡지
  않아 증명이 성립하지 않는다(ADR §3). Python은 `feature-write`를 잡지 않는다.
- **migration `406_feature_write_gate`.** 사이드카 15개(`_406_<루틴>.sql`) = head 원문에서 잠금 몇 줄만 바꾼 사본
  (생성 후 head 원문과 diff해 잠금 줄 외 차이 0 확인). 소유자 창 `ktm_curation_command_owner` →
  `ktm_feature_request_procedure_owner` → `ktm_feature_schema_owner`로 끝남(RESET ROLE 없음). receipt head CHECK에 406.
  head-schema.sql은 n150에서 `KTM_WRITE_HEAD_SCHEMA=1`로 재생성(+25/−121, 잠금 줄과 CHECK만).
- **sensor 하드닝.** 결정적 SQLSTATE(08·40·57 class와 53300·55P03·55006 제외) 실패는 tick을 종전대로 실패시키되
  cursor `last_failure{run_id, SQLSTATE, count}`만 갱신(watermark 불변). 같은 run·같은 SQLSTATE 5연속 + terminal run이면
  `abandon_dagster_feature_run`이 기존 terminal 전이(`failed`/stage `failed`)로 root를 닫고 `feature_operation.reconcile_abandoned`
  error 로그. 새 상태·컬럼 없음(`quarantined_at`은 migration 소유라 쓰지 않음). ledger가 비면 cursor 모양은 종전 그대로.
- **테스트(효과 결박).** `tests/integration/test_feature_write_gate_lock_budget.py` — lock table 칸 수(설정에서 유도)의
  2배 Feature를 한 dataset에 링크하고 root 완결, 그 트랜잭션의 advisory lock 수 < 16. n150 실측: 405 스키마(406 제거)에서
  `asyncpg OutOfMemoryError: out of shared memory`로 **red**, 406에서 green. `tests/lint/test_feature_write_lock_order.py` —
  head 전 루틴(203)을 중첩 CALL까지 펼쳐 Feature 잠금 스칼라·gate 선행·전역 순서·공유→배타 승격 금지; 406 전 head에서
  위반 24건으로 red, 심은 위반 셋으로 탐지기 red 확인. sensor unit 6건(상한 도달·일시 SQLSTATE 미계수·다른 실패 리셋·
  진행 중 run 미닫힘·닫기 실패 재시도·cursor 하위호환).
- **열린 것.** `finalize_provider_curation_receipts`는 호출자 없음(지우지 않고 같이 고침). 서로 다른 dataset 대량 writer는
  이제 직렬화된다. 배포·sensor 재시작은 운영자 몫.
- **적대 리뷰 2건 반영(같은 브랜치, #1318 위로 리베이스).** 둘 다 잠금 순서·교착 결함은 찾지 못했고 CI가
  빨갰다. (1) BLOCKER — 통합 검사가 세션 공유 DB에 1.5만 Feature·active dataset·done job을 남겨 뒤의
  `test_mois_loader.py` 2건(glibc lane)을 깼다 → 그 모듈만의 DB를 같은 컨테이너에 만들어 head까지 올리고 지운다;
  active rule 하나를 걸어 중첩 materialize도 같은 규모로 돌린다(`observed_candidate_count == Feature 수`).
  (2) HIGH — 53200은 cluster의 다른 tenant가 일으킬 수 있으니 세면 안 된다(406 전에 sensor가 켜지면 2분 반 만에
  97ac4e01을 닫는다) → root를 닫는 SQLSTATE는 22/23/P0 허용 목록뿐, 그 밖은 cursor `retry_after`로 30s→15분 backoff.
  (3) MED — root 완결은 `feature-curation-write`를 든 채 gate를 기다리지 않는다(`pg_try_advisory_xact_lock`, 바쁘면 55P03);
  단건 writer 여섯은 `SET lock_timeout TO '5s'`, API는 55P03 → 503 `LOCK_TIMEOUT`(OpenAPI 바이트 불변, openapi-drift 초록).
  abandon 통합 검사(root failed/failed, done member 그대로, 로그 1행에 `provider_dataset_ids`·`action`, 두 번째 호출
  blocked/terminal). rollback 시 cursor 처리 ADR에 기록. (4) LOW — 대량 명령 여섯의 죽은 범위 재검사(두 scan + 40001)
  제거, 호출자 없고 gate 앞에서 행을 갱신하던 `finalize_provider_curation_receipts` DROP, lint가 `ops`·`provider_sync`
  호출과 행 쓰기의 trigger까지 펼친다(심은 trigger 위반으로 red 확인). ADR-111에 새 Feature에도 gate를 잡는 이유.
- **함정.** 시드의 `created_at`·`started_at`을 `clock_timestamp()` 두 번으로 넣어 μs 차이로
  `ck_import_jobs_ck_import_jobs_feature_engine_timeline`에 걸렸다 — 한 문장의 `now()`로.
- **델타 리뷰 반영(00630d19 위).** 마이그레이션·테스트는 GO, 재시도 논리에 HIGH 하나. (H1) 실패한 run 하나가
  tick 전체를 실패시켜 두 cursor가 멈추고 DB page에 닿지 못했다 — 42xxx·54000·SQLSTATE 없는 예외 같은 영구 실패면
  15분 backoff 아래 reconcile 전체가 무기한 선다. → run별 `deferred` 표로 실패한 run만 미뤄 두고 watermark·같은 page·
  DB page를 계속 돌며, 미뤄 둔 run은 시각이 되면 run_id로 다시 집는다(표 최대 200). 변이 확인: 앞 run이 계속 실패해도
  뒤 run과 DB page run이 같은 tick에 반영된다(`test_a_parked_run_does_not_block_the_others`). (M1) 같은 실패 5연속에
  `feature_operation.reconcile_stalled`를 한 번. (M2) 닫기는 `applied`일 때만 표에서 지우고, `blocked`면 표에 남겨 다시
  닫지 않고 멈춘 run으로 올린다(잘못된 "failed로 닫음(outcome=blocked)" 로그 제거). (M3) rollback은 `deferred` 키만 뺀
  cursor `--set`(prod는 null cursor 초기화 거부라 `--delete` 금지), 405 재배포 약속 대신 fix forward. (M4) 55P03은
  30초 고정 backoff, ADR에 "공유 보유자도 try를 막는다". (L) `_sqlstate`/`sqlstate_of`는 `orig`·`__cause__`만;
  API는 typed `DBAPIError` 처리기(55P03만, 나머지는 다시 던져 종전 500); lint는 lock 문장의 어떤 FROM도 scan으로 —
  그래서 `patch_curation_item_command`의 두 Feature 잠금을 `LEAST`/`GREATEST` 두 스칼라 문장으로 바꿨다. CHANGELOG·
  journal·resume에 남아 있던 diff3 base 표지(`|||||||`) 세 줄 제거.
- **3차 리뷰 — 미뤄 두는 표를 걷어내고 단순하게.** run별 `deferred` 표가 새 손실 경로(넘침으로 버린 Dagster 쪽 run은
  watermark가 이미 지나 DB page에도 없으면 영영 사라진다)와 재시도 폭주(tick당 실패하는 무거운 완결 최대 ~600건, 평가
  timeout 60초를 넘겨 cursor가 안 써지는 tick)를 만들었다. 소유자 원칙(단순하게)대로 걷어냈다: Dagster page는 **실패한
  머리 run에서 멈추고** watermark를 마지막으로 반영한 run에 둔다(건너뛰는 것이 없으니 잃는 것도 없다). cursor에는
  `head_failure` 하나, 물러선 동안 Dagster page를 통째로 쉰다. DB page는 매 tick 실패 3회·20초 예산 안에서 돌고 실패는
  기록하지 않는다(keyset이 다시 집는다). 닫기 규칙은 그대로(22/23/P0·머리·terminal·5회), `blocked/terminal`은 지나가고
  `blocked/cancellation`은 다시 한다. 55P03은 멈춤 보고 제외. `reconcile_stalled` 메시지에 이벤트 이름(`q` 검색)과
  running/terminal에 맞는 조치 문구. 실행 manifest 해석은 카탈로그 부재(`FeatureOperationInvariantConflict`)만 guard 거부로
  — 일시 실패가 관측 오류로 둔갑해 watermark를 지나가던 구멍(테스트 대역이 `LookupError`를 던져 가리고 있었다). 변이 확인
  둘: watermark를 지나가게 바꾸면, DB 예산을 없애면 해당 테스트가 빨개진다. journal 2026-09-16~19 7건을 아카이브로(§8,
  분리 전후 본문 sha256 `97fd54c2…` 동일). runbook은 pair 명시·preflight·systemd-run·원장/cursor 확인으로.
- **분할 결정 — sensor 재시도 설계를 되돌리고 후속으로.** 최종 리뷰(6d0ebfc98)가 backpressure 판에서도 HIGH 셋을 더 찾았다
  (DB root 없는 닫을 수 있는 머리의 영구 고착, 모든 lock_timeout 55P03을 gate 바쁨으로 봄, 서명이 번갈아 바뀌면 횟수
  초기화) — 설계가 매 판 새 구멍을 냈다. 406이 고착의 원인을 없애므로 sensor·`abandon_dagster_feature_run`·
  `reconcile_stalled`/`reconcile_abandoned` 로그와 그 테스트·대역을 origin/main으로 되돌렸다. main sensor에서 55P03은
  그냥 tick 실패 → 30초 뒤 재시도이고 닫는 경로가 없다. manifest 해석의 guard 축소는 남겼다 — main sensor에서 일시
  실패가 이제 다른 DB 실패처럼 tick을 실패시킬 뿐 관측 오류로 watermark를 지나가지 않는다. 리뷰 결과는 ADR-111 결정 4와
  `T-RECONCILE-RETRY`(해제 조건: 잃지 않음·tick 시간 유계·경과 시간 알림·gate 전용 SQLSTATE·명시 목록만 닫기)로.
- **migration 번호.** #1319가 406(`406_feature_write_gate`)을 쓰므로 Track 1(ADR-109)의 계획 번호를 하나씩 민다 — `feature_geocode_stamps` 406 → 407, `kor_travel_geo_releases` 407 → 408(tasks·acceptance·ADR-109·address-geocoding).

## 2026-10-13 — admin e2e 전체가 로드 단계에서 죽던 결함(ESM 전용 `@kor-travel/ui`): 브랜치 `fix/e2e-esm-kor-travel-ui`

n150 chain16 D1(Map `c4d17343`)이 테스트를 하나도 돌리기 전에 `Error: Package subpath './navigation' is not defined by
"exports" in …/@kor-travel/ui/package.json`으로 끝났다(require stack `src/lib/auth.ts:1` ← `e2e/auth-session.ts:5` ←
`e2e/live/auth.setup.ts:4`). acde3726(2026-10-06)이 `auth.ts`에 `@kor-travel/ui/navigation` import를 넣었는데, vendored
`kor-travel-ui-0.1.0-dev.6.tgz`는 `"type":"module"`이고 `exports`에 `types`+`import` 조건만 있다. admin frontend는
`"type":"module"`이 아니라 Playwright가 e2e TS를 CJS로 변환해 `require()`하므로 그 subpath를 해석하지 못한다. Next·tsc·
eslint·vitest는 모두 ESM/번들러 해석이라 통과했다.

- **영향 범위(n150 실측, `playwright test --list`).** `c4d17343`에서 mocked(`playwright.config.ts`)·live·cache-target-streams
  세 config 모두 rc=1 — mocked `e2e/auth.setup.ts`도 같은 `auth-session.ts`를 쓴다. 즉 10-06 이후 D1·M05 등 live와 mocked
  checkpoint 모두 로드 불가였다. CI가 못 잡은 이유: GitHub 워크플로 어디서도 Playwright spec을 로드하지 않는다
  (`frontend.yml`은 "e2e는 서비스가 필요해 n150에서 돈다"며 제외).
- **수정.** `SESSION_COOKIE_NAME`을 import 없는 `src/lib/session-cookie.ts`로 옮기고 `auth.ts`는 재export, e2e 두 곳
  (`e2e/auth-session.ts`, `e2e/live/cache-target-streams-isolated.live.spec.ts`)은 새 모듈에서 가져간다. 대안이던 frontend
  `"type":"module"`(Playwright ESM 로드)은 next/eslint/postcss config와 스크립트 전체의 모듈 해석을 바꿔 범위가 크다.
- **재발 방지(효과 결박).** frontend 패키지 `e2e:list` = 세 config의 `playwright test --list`, `frontend.yml`이 vitest 뒤에
  실행한다. 서비스·브라우저 없이 spec import 그래프를 실제로 require한다. n150에서 `c4d17343` 사본은 세 config 모두 rc=1
  (같은 오류), 이 브랜치는 rc=0(mocked 271 tests/28 files, live 1142/28, cache-target-streams 1/1) — 검사가 이 결함에서
  빨갛게 되는 것을 확인했다.
- **첫 live 실행(`bb602ea7`).** n150 prod 대상 읽기 전용 D1 4 spec(`--workers=1`): 11건 중 9 passed, 2 failed — live
  `auth.setup.ts`를 포함해 전부 로드·실행됐다(이전엔 0건). 처음엔 두 실패를 "무관·범위 밖"으로 적었으나 적대 리뷰
  (HIGH-2)가 chain16 D1은 spec 하나만 실패해도 죽으므로 둘을 남기면 D1이 계속 빨갛다고 짚어 **이 PR에서 고쳤다**(아래).
- **리뷰 반영 1 — `home-dashboard-roundtrip`(spec 결함).** 첫 실행 행을 `getByRole("row", {name: kind})`로 찾아 첫 페이지에
  같은 kind가 여럿이면(prod `import_job` 8행) strict mode 위반이었다. id(`shortId`)+kind 필터로 찾고 `toHaveCount(1)`.
- **리뷰 반영 2 — `admin-scenario-catalog` "pipeline live UI calls datasets catalog…"(실제 prod 결함).** 화면에 "Dagster
  연결 불가 — 응답 전체 대기 상한 초과"와 큐 sensor 차단 alert가 떠 `queueOperational=false`, 갱신 요청 dialog(=
  `/v1/ops/datasets` 호출)가 렌더되지 않았다. 원인은 PinVi #581과 같다: overview·schedules·summary 세 GraphQL 문서의
  `ticks(limit: 3)`가 `afterTimestamp` 없이 instigator의 전체 tick 이력을 읽는다(공유 `dagster_shared.job_ticks` 약 40만
  행). 수정: `dagster_graphql`에 `SCHEDULE_TICK_WINDOW_SECONDS`(2일)·`SENSOR_TICK_WINDOW_SECONDS`(1시간)·
  `MAX_TICKS_IN_WINDOW`(300)와 `tick_window_variables()`를 두고 세 문서가 `afterTimestamp: $scheduleTicksAfter|$sensorTicksAfter`를
  싣는다. OpenAPI 변경 없음(PinVi 재vendor 불필요). spec은 전제(overview HTTP 성공, 큐 sensor 차단 alert 부재)를 먼저 단언해
  원인을 메시지로 낸다.
- **실측(n150, 127.0.0.1:11002, 읽기 전용, 문서별).** overview(sensor tick만): 창 없음은 이 시점 4회 모두 **HTTP 500 at
  15.1~15.4초**(webserver statement timeout; 앞서 cold 10.0초·warm 1.3초도 봤다) → 창 있음 **0.08~0.12초**(같은 시각 교차
  측정 4회). 단 디스크 대기가 큰 순간(load 12~14, iowait 44~52%) 창 있음 첫 호출 1회가 27.4초였다 — 창은 읽는 행 수를 줄일 뿐
  n150의 I/O 정체까지 없애지는 못한다. schedules: 창 있음 0.18~0.24초. summary: 창 있음 0.20~0.22초(2일 창 기준; 62일
  창일 때 0.27~0.54초·0.50~0.53초). 오늘은 Map schedule이 전부 STOPPED라 schedule 쪽 행은 거의 없다.
- **schedule 창 2일(리뷰 4라운드 MED).** 처음엔 월간 cron(`10 3 1 * *`)을 덮으려 62일(최장 주기 2배)로 두었으나, Dagster
  `get_ticks`는 `selector_id = X OR (selector_id IS NULL AND origin = Y)`라 인덱스 순서 scan을 못 하고 창 안 전 행을 읽어
  정렬한다 — 비용은 창 안 tick 수에 비례한다. 같은 sensor 하나의 EXPLAIN ANALYZE(`BEGIN READ ONLY`): 창 안 211행 0.45초,
  9,690행 cold **7.4초**, 33,971행 warm 0.14~0.22초. 62일은 schedule이 전부 STOPPED인 오늘만 쌌고, `*/10` schedule
  (`feature_notice_transport_highway_incidents_ten_minute_schedule`) 하나가 켜지면 8,900행 → 7초대로 돌아간다. 검토한
  대안: schedule마다 자기 cron으로 창을 잡는 것(두 번째 요청·별칭 문서·cron 파서가 세 호출 지점에 필요)보다, **창 하나 +
  비용 상한 테스트**가 단순하다 — `test_schedule_window_cost_is_bounded_by_the_densest_cron`이 배포 Definitions의 최단 cron
  간격으로 창 안 tick 수(`*/10` × 2일 = 288)를 `MAX_TICKS_IN_WINDOW` 이하로 강제해, 더 조밀한 schedule을 더하면 창을 줄일지
  상한을 올릴지 고르게 한다(sensor도 같은 상한, 15초 × 1시간 = 240). 대가: 주간·월간 schedule은 마지막 tick이 2일보다
  오래면 `recent_ticks`가 비고, 1시간 넘게 멈춘 sensor도 그렇다. 관리자 UI는 RUNNING인데 비면 "최근 2일/1시간 tick 없음"으로
  표시한다(`src/lib/dagster-tick-window.ts`; 값은 같은 테스트가 API 창과 대조). sensor `typeSpecificData.lastTickTimestamp`로
  멈춤을 드러내는 안은 응답 DTO에 필드를 더해야 해(OpenAPI 변경 → PinVi 재vendor) 이번엔 표지로 그쳤다. 운영자 cron
  override(`load_schedule_cron_overrides`)는 정의에 없어 테스트가 못 본다 — override 간격이 2일보다 길면 같은 빈 목록, `*/10`보다
  조밀하면 비용이 그만큼 커진다.
- **효과 결박 테스트.** `tests/unit/test_dagster_tick_window.py`가 세 문서를 Map code location을 in-process로 실은 Dagster
  (1.13.24)에 실행해 storage `get_ticks`가 받는 `after`를 기록한다. main의 문서로 되돌리면 세 건 모두 빨갛다(n150 실측:
  summary는 `after=None`, overview·schedules는 batch 경로로 빠져 `get_ticks` 0건). 시계를 고정하고 instigator 종류별
  `after` 다중집합을 대조해 두 변수를 바꿔치기해도 빨갛다. 창 비용 상한(위), sensor 창 ≥ 10×최장 최소 간격, tick 선택 문서
  목록(`Assign`·`AnnAssign` 모두), UI 표지 값도 본다. 기존 router·service 테스트는 시계를 고정해 호출 지점 변수까지 대조한다.
- **리뷰 반영 3 — 게이트·config.** `scripts/verify-all-gates.sh`에 `e2e:list` 게이트(빠져서 CI pytest의
  `test_gate_script_covers_every_ci_blocking_command`가 빨갰다, HIGH-1). `e2e:list`의 live 실행은
  `e2e/reporter-load-check.ts`로 커스텀 reporter 둘(C7 redacted, mocked failure)을 **로드만** 한다(인스턴스·훅 없음 — n150에서
  파일 0개 확인, reporter에 ESM 전용 import를 넣으면 rc=1). `playwright.live.config.ts`의 top-level `testIgnore`가 chromium
  project의 `testIgnore`에 대체돼 격리 전용 `cache-target-streams-isolated` spec이 live suite에 들어가 있었다 — project-level로
  옮겨 live 목록이 1142/28 → 1141/27. CI 단계는 `forbidOnly`로 `test.only`도 잡는다(n150에서 `CI=1` 변이로 확인);
  `verify-all-gates.sh`도 `CI=1`로 같은 조건에서 돈다. `scripts/n150/chain16.sh` D1은 `--list` 개수만큼 passed여야 초록이고
  skipped·did not run·interrupted도 실패로 본다(전에는 failed/flaky 줄이 없으면 초록).
- **D1 재실행(브랜치 사본, prod 읽기 전용).** 11건 중 **10 passed, 1 failed**. `home-dashboard-roundtrip`은 이제 통과한다. 남은 1건은 `admin-scenario-catalog`의 새 전제 단언이 "큐 sensor 차단 alert — Dagster 상태 스냅샷을 신뢰할 수 없습니다"로 정확히 원인을 내며 실패한 것이다 — prod Map API가 아직 창 없는 문서를 쓰기 때문이고, 이 PR의 API 수정은 배포 뒤에야 live에 보인다. 배포 전 증명으로 이 브랜치의 세 문서를 그대로 prod Dagster에 보냈다(위 실측). **D1 11/11은 Map API 배포 뒤 재실행으로 확인할 일이다.**

## 2026-10-13 — chain17 B 단계가 같은 Map·새 PinVi 회전을 건너뛰던 결함: 브랜치 `fix/chain17-rotate-when-pinvi-changes`

n150 chain t1013e(2026-10-13 09:11Z)에서 `/root/chain17-pv.sh`(운영자 변형, `PINVI_OVERRIDE` 추가본)가 B 단계에서
`원장 map == MAP`만 보고 "이미 회전됨 — 건너뛴다"를 택했다. 인자로 준 새 PinVi `2fa1c166`은 회전되지 않았고, 원장의
옛 PinVi `97f2baf2`로 재구축·C6c 스모크가 돌아 1분 만에 같은 실패가 재현됐다. 수동 `rotate-pinned-pair c4d17343 2fa1c166
"<reason>"`은 성공했다 — registry는 같은 Map·다른 PinVi 회전을 허용하고 pair 전체가 같을 때만 거부한다. 즉 건너뛰어도
되는 조건은 "원장 map·pinvi 둘 다 인자와 같다" 하나뿐인데 스크립트는 절반만 보고 있었다.

- **수정(`scripts/n150/chain17.sh`, 정본 — ADR-102 결정 6).** (1) B 단계 skip 조건을 `map == MAP && pinvi == PINVI`로,
  하나라도 다르면 `rotate-pinned-pair`를 부른다. 회전 뒤 검증도 map·pinvi 둘 다 원장과 대조한다(map만 보면 같은 구멍이
  거기서 다시 열린다). 원장 읽기는 기존 `ktdctl pin show | awk` 패턴을 `pin <key>` 한 helper로 묶어 0·B 단계가 같이 쓴다.
  (2) 운영자가 `/root/chain17-pv.sh`로 손수 들고 있던 `PINVI_OVERRIDE`를 정본에 흡수했다 — README가 "호스트 사본을 손으로
  고치지 않는다"고 못박는데 변형이 호스트에만 있었고, 이 결함은 그 변형에서만 드러난다(정본은 PinVi를 늘 원장에서 읽어
  map만 봐도 pair가 같았다). 생략하면 원장의 **현재** pinvi를 그대로 다시 핀하므로, 원장과 다른 PinVi를 올릴 때는
  같은 Map이든 새 Map이든 `PINVI_OVERRIDE`가 필요하다 — 헤더·README가 "같은 Map일 때만"으로 좁게 읽히던 것을 적대
  리뷰(MED)가 잡아 그렇게 고쳤다. (3) launcher 경로를 `ROTATE` 변수로 올렸다(`KTDCTL`·`DRIVER`와 같은 꼴) — 테스트가
  stub으로 바꿔 끼우는 자리이고, 리터럴은 상단 한 곳에만 있다. (4) 리뷰 LOW 둘도 반영: 0단계 pinvi 출처 라벨이
  `${X:+..}${X:-..}` 결합으로 override 때 `PINVI_OVERRIDE<sha>`로 붙어 찍히던 것(`-pv` 변형에서 그대로 옮겨온 표시
  결함)을 `PINVI_SOURCE` 한 변수로; B 단계는 원장을 못 읽은 빈 값을 "다른 pair"로 보지 않고 비교 전에 그 사유로 멈춘다
  (전에는 회전을 시도해 '회전 실패'로 원인이 가려졌다).
- **테스트(효과 결박).** 새 `tests/lint/test_chain17_rotates_when_only_pinvi_changes.py`: 스크립트의 B 단계 본문과
  `die`·`say`·`pin` 정의를 잘라 가짜 `ktdctl`(원장 파일)·가짜 `rotate-pinned-pair`(호출 기록 + 원장 갱신) 위에서 bash로
  실행한다. 같은 pair → rotate 호출 0·skip, (같은 map·새 pinvi / 새 map·같은 pinvi / 새 pair) → `rotate MAP PINVI REASON`
  정확히 1회, launcher가 0으로 끝났는데 원장 pinvi가 그대로 → exit 1·C로 가지 않음, 원장이 비어 있거나 pinvi가 없음
  → rotate 호출 0·exit 1. 추출이 빈 본문을 집지 않았는지도 먼저 본다. 기존 `test_n150_host_scripts_drop_attestation_chain.py`의 hard-gate 순서 단언은 launcher **호출** 자리
  (`"$ROTATE" "$MAP" "$PINVI" "$REASON"`)로 옮기고 `ROTATE` 대입값을 대조한다. `bash -n`은 기존 파라미터 테스트가 덮는다.
- **문서.** `scripts/n150/README.md` 표·"무엇이 Manager 쪽인가"에 같은 Map·새 PinVi 사례 한 줄, CHANGELOG `[Unreleased]`.
  ADR-102는 B 단계를 서술하지 않아 손대지 않았다.
- **journal 분리(§8).** 이 엔트리로 `docs/journal.md`가 227,144 B가 되어 상한 225,280 B를 넘었고
  `tests/unit/test_docs_archive_links.py::test_every_docs_markdown_stays_within_readable_limit`이 빨갰다(적대 리뷰 HIGH).
  하단 2026-09-14 6건·2026-09-15 2건(8건, 본문 21,744 B)을 `docs/archive/journal-2026-09c.md`로 옮겼다 — 옮긴 절 본문의
  sha256이 분리 전후 같음(`36527129…`), 상대 링크 없음, 현행 창은 2026-09-16~. 분리 뒤 journal 205 KB.
- **운영 후속(외부).** 머지 뒤 운영자가 `sudo install … scripts/n150/chain17.sh /root/`로 재복사하면 `/root/chain17-pv.sh`는
  필요 없다. 이 PR은 n150을 바꾸지 않았다(`/root/chain17-pv.sh` 읽기만).
