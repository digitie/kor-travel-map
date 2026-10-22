# journal 아카이브 — 2026-09-28 ~ 2026-09-29

> live `docs/journal.md`에서 분리한 과거 기록(docs/tasks-rule.md §8). 읽기 전용 이력이다.

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
