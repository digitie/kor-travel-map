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
