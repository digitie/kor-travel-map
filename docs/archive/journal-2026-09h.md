# 2026-09-30 작업 기록

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

