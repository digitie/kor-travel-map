# journal 아카이브 — 2026-10-13 (d)

> live journal이 220 KiB 경계를 넘어 가장 오래된 완전한 절 둘을 분리했다(docs/tasks-rule.md §8). 본문은 상대 링크의 기준 경로만 바꿨다. 읽기 전용 이력이다.

## 2026-10-13 — 고속도로 돌발 job pool 고갈(prod run `bfd18ef5`): 브랜치 `fix/highway-incidents-pool`

- 증상: 2026-10-12 12:09Z 수동 첫 적재가 807초 뒤 실패. 4회 시도 모두 step 시작 30초 만에 `get_notice_snapshot_watermark`
  (lock 안 첫 DB 호출)에서 `QueuePool limit of size 1 overflow 0 reached, timeout 30`. 같은 캠페인의 주유소·휴게소 job은 성공.
- 원인: `provider_run_lock`이 advisory lock용 session으로 pool의 유일한 연결을 끝까지 쥔 채, 본문 client 호출이 각자 새
  session(두 번째 연결)을 열었다. 2026-10-05 ADR-107(acde37264)이 Dagster `kor_travel_map_client`를 `pool_size=1,
  max_overflow=0`으로 줄이면서 드러났다(그 전 기본 5+10에서는 조용했다). 2026-10-03 ADR-106이 주유소 asset의 lock을
  걷어내 lock을 쓰는 asset은 고속도로 돌발 하나만 남았다 — 그래서 그것만 죽었다. 공용 Dagster에서 이 job은 이 run 한 번뿐이고
  성공한 적이 없다. 10분 schedule(STOPPED)의 coalescing은 RunRequest 발행 여부만 정하므로 켜도 매 tick 같은 자리에서 죽는다.
  큐 경로는 client를 executor 연결에 결합하므로 영향 없다.
- 못 잡은 이유: asset 단위 테스트의 fake client lock은 연결을 쥐지 않았고, 통합 테스트는 기본 pool(5+10) engine을 썼다.
- 수정: lock을 잡은 연결에 client의 session factory를 lock 구간 동안 묶는다(객체 identity 유지 — guard identity 대조와
  `context.resources` 재조회 때문에 복사본은 안 된다). 전역 pool 상향은 하지 않았다 — ADR-107 runbook의 "DB 연결 1개" 계약을
  지키고, 본문은 원래 순차다. 같은 결함의 `cache_target_snapshot_gc` drain(prod 미실행, 잠복)도 같은 방식으로 고쳤다.
- 리뷰(PR #1314 @ffa0986e) 반영: H1 — GC drain 수정이 `tests/unit/test_cache_target_snapshot_gc_client.py` 3건을
  깼다(fake connection에 실제 `make_connection_session_factory`가 불림, 내 전체 unit run이 그 commit보다 먼저 시작됐다).
  테스트가 그 함수를 lock 연결일 때만 fake factory를 주도록 바꾸고 engine-bound factory는 호출되면 실패시켜 "lock 연결
  위에서만 session을 연다"를 단언한다. L3 — `connection_advisory_lock`/`discard_connection_on_failure`(infra): 획득·본문
  실패·해제 실패 때 lock 연결을 invalidate해(server가 lock을 푼다) lock을 쥔 채 pool로 돌아가지 않게 한다. 본문 실패 때는
  unlock을 시도하지 않아 원래 예외를 가리지 않는다. L4 — asset 통합 테스트를 Dagster runtime login으로. mutation 5종 RED.
- 남은 것(미수정): 큐 경로 strict 실패 증거(`feature_update_evidence_client`)는 executor 연결 밖에서 별도 commit하려고
  두 번째 연결을 요구한다 — 실패 경로에서만, 설계 결정이 필요하다.
- 검증(로컬 WSL + testcontainers PostGIS): 회귀 테스트 4종(단위 SQLite pool 1/0 2건, 통합 lock·asset 전체·GC drain) 모두
  수정 전 client에서 prod와 같은 TimeoutError로 RED 확인. dagster 패키지 679 passed, 관련 통합 executor·notice·advisory·GC
  통과, ruff·mypy --strict·lint-imports 통과.

## 2026-10-13 — weather 잔재 정리(ADR-104/105 후속): 브랜치 `chore/weather-remnant-cleanup`

소유자 승인 정리. 세 갈래 스캔이 live weather 경로는 없고 죽은 코드와 낡은 문서만 남았다고 봤다. PR·머지·배포는 하지 않았다.

- **지운 코드.** `core.ids.make_weather_value_key`·`WEATHER_VALUE_KEY_HASH_LENGTH`와 `core` 재수출,
  `tests/unit/test_ids_weather.py`(호출자 0, grep 전수). `core.scoring.SOURCE_PRIORITY`의 `python-kma-api`·
  `python-airkorea-api` 항목(읽는 곳은 `source_priority()` 하나, master 선정 후보에 그 provider feature가 402/403 뒤
  남지 않는다). `test_export_openapi.py`의 `_CURATED_*` 상수 다섯 개 — `"weather"` variant만 죽은 게 아니라 #1023이
  소비 테스트를 지운 뒤 블록 전체가 아무도 읽지 않았다. admin frontend `vworld-map-view`·`poi-cache-targets`의
  weather 라벨·색(`Record<string,string>` + `??` fallback이라 kind union과 무관; dedup-review 표는 이미 깨끗했다).
- **남긴 것(결정).** `FeatureKind.WEATHER`·kind CHECK, `WeatherValue` DTO·weather enum(API 재도입 방지 검사가 기댄다),
  provider alias, baseline/seed/legacy migration, frozen H35 SQL(`feature_repo`의 KMA 분기 포함), maki weather 아이콘,
  `SourceRole.WEATHER_CONTEXT`(migration 필요 → 백로그).
- **문서.** ADR-062·072 superseded by ADR-104/105(본문 유지, 머리 노트), README 색인. ADR-105의 소유 참조를 ADR-068
  (Feature UUID)에서 ADR-104로 정정. integration-map(service resource는 `/v1/features/batch`뿐), live 인수 runbook
  (owned ID 7개 = place 6 + price 1, `_owned_ids` 대조), ETL 배너 다섯, architecture·data-model(§8.2 제거 노트,
  `current_summary_runs` CHECK는 402 이후 `'price'`)·feature-model·public-views(`latest_weather` 행)·poi-cache·test-strategy.
  stale 주석: maki.ts·mois.py·client docstring·dto/bundle.py.
- **백로그.** `T-WX-VNEXT-FREEZE`(계약↔계약 대조라 지워진 weather 표를 못 잡는다 — 확인함), `T-WX-SOURCEROLE`,
  `T-WX-DTO`, 그리고 스캔 중 찾은 `T-WX-NOTICE-CLOSE`(`close_notice_features`의 production 호출자 0). Manager compose
  `KOR_TRAVEL_MAP_KMA_*` env 제거는 외부 추적(Manager 저장소에서 진행 중).
- 검증(로컬 WSL ext4 사본 + uv venv, n150은 IO 포화라 쓰지 않았다): ruff check(CI 경로) 통과, mypy --strict
  main 153·api 67·dagster 30 통과, lint-imports 4 kept, `check_prod_redaction` 통과. pytest: core import 단위 704 passed,
  `tests/lint` 303 passed(+ `test_sealed_runtime_tree_ship` 2건은 git이 필요해 실제 worktree에서 2 passed),
  `test_export_openapi.py` 11 passed. frontend: admin type-check·touched ESLint 0 경고·vitest 46파일 391 passed,
  map-marker-react vitest 4 passed·typecheck 통과. 최종 게이트는 GitHub CI다.
- 기존 결함(이번 변경과 무관, 기록만): `make_feature_id` doctest 기대값이 origin/main에서도 틀린다(CI는 doctest를
  돌리지 않는다). 로컬 ruff의 `format --check`는 손대지 않은 줄 다수에 diff를 낸다(CI format step은 `if: false`).
- **journal 분리(규약 §8).** 이 항목으로 `journal.md`가 225,613 bytes가 돼 CI의
  `test_every_docs_markdown_stays_within_readable_limit`(225,280)이 붉었다. 가장 오래된 2026-09-11~09-13 5개 절을
  `archive/journal-2026-09b.md`로 옮겼다(하단 인덱스 표 갱신, 현행 창 2026-09-14~). 옮긴 절에 상대 링크는 없다.
  바이트 보존 검산: 새 live 문서에서 인덱스 행·창 문구를 되돌리고 옮긴 블록을 제자리에 넣으면 원본과 byte 단위로 같다.

