# Admin Feature targeted production live 인수·복구

이 runbook은 issue #741·#785와 `T-VN-15`의 남은 production 증거를 한 번의 owned
Feature lane에서 검증한다. strict `T-ADM-C7`의 상태·증거에는 mutation을 섞지 않지만,
실행 전 신뢰 경계는 C7 host attestation v4와 pinned runtime manifest v5 + rebuild
journal v7을 그대로 재사용한다. C7 성공을 대신하거나 C7보다 넓은 배포 조합을 허용하지 않는다.

## 1. 불변식

- 실행은 root, 단일 orchestrator, Playwright worker 1개로 제한한다.
- 운영 기존 row를 fixture로 빌리지 않는다. `run_id`에서 파생한 Feature ID 8개만 소유한다.
  place 6개는 admin API로 생성·승인·soft-delete하고, weather/price 2개만 전용 helper가
  transaction으로 만들고 물리 삭제한다.
- browser의 모든 API 호출은 same-origin `/api/proxy` BFF를 통한다. public API key를 URL이나
  browser state에 넣지 않는다.
- `BLOCKED.json`과 `ACTIVE.json`은 고정 root state에만 원문 identity를 저장한다. 보존
  evidence와 이슈 코멘트에는 run/Feature/container/cursor/secret 원문을 남기지 않는다.
- 정상·실패·복구 종료 모두 API-owned pending request 0건, API-owned Feature `deleted`,
  direct Feature/value 0/0/0, 모든 `feature.features(feature_id)` FK reference 0건,
  label/name 기반 Docker container 0건을 확인한다.

## 2. 신뢰 snapshot 설치

대상 commit을 먼저 확정한다. 다음 네 파일을 Git archive에서 추출해 commit별 immutable
directory에 basename으로 설치한다.

```text
/usr/local/lib/kor-travel-map/admin-feature-live-acceptance/<40-hex>/
  admin_feature_live_fixture.py
  admin_feature_live_state.py
  admin_feature_live_supervisor.py
  run-admin-feature-live-acceptance.sh
  source-manifest.json
```

- directory: `root:root 0555`
- runner: `root:root 0555`
- Python 세 파일과 manifest: `root:root 0444`
- 기존 snapshot은 in-place 수정하지 않는다. 별도 임시 directory에서 파일·manifest·mode를
  완성한 뒤 원자적으로 배치한다.

`source-manifest.json`은 다음 exact schema다. `files`는 네 source만 포함하며 manifest
자신은 포함하지 않는다.

```json
{
  "files": {
    "admin_feature_live_fixture.py": "<sha256>",
    "admin_feature_live_state.py": "<sha256>",
    "admin_feature_live_supervisor.py": "<sha256>",
    "run-admin-feature-live-acceptance.sh": "<sha256>"
  },
  "repository_commit": "<40-hex>",
  "version": 1
}
```

runner는 `/`부터 snapshot까지 root 소유·비쓰기 ancestor, exact directory 경로, exact 5-file
set, mode, commit, SHA256을 state 생성 전에 검증한다. 같은 commit의 strict C7 snapshot에는
`scripts/lib/c7_prod_attestation.py`가 root-owned 상태로 있어야 하며, host attestation
`/etc/kor-travel-map/c7-prod-live-e2e-attestation.json`의 orchestrator hash와 일치해야 한다.

## 3. 실행 환경과 attestation

실제 값은 gitignore된 prod local runbook에서 읽고 shell environment로만 전달한다. URL,
password, service 이름, image ID, host identity는 이 문서와 evidence에 복사하지 않는다.

```bash
export E2E_BASE_URL='<production-ui-origin>'
export NEXT_PUBLIC_KOR_TRAVEL_MAP_API='<production-api-origin>'
export E2E_DAGSTER_URL='<production-dagster-origin>'
export E2E_ADMIN_PASSWORD='<admin-password>'
export E2E_LIVE_ALLOW_PROD=1
export E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1
export E2E_C7_EXPECTED_GIT_COMMIT='<40-hex>'
export E2E_C7_PINNED_RUNTIME_MANIFEST='<root-owned-pinned-runtime-generation-v5.json>'
export E2E_C7_REBUILD_JOURNAL='<root-owned-pinned-runtime-rebuild-v7-<pinset>.json>'
export E2E_C7_PLAYWRIGHT_IMAGE='sha256:<64-hex>'
export E2E_C7_EXPECTED_UI_ORIGIN_SHA256='<64-hex>'
export E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256='<64-hex>'
export E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256='<64-hex>'
export E2E_C7_MAP_API_SERVICE='<compose-service>'
export E2E_C7_UI_SERVICE='<compose-service>'
export E2E_C7_DAGSTER_WEB_SERVICE='<compose-service>'
export E2E_C7_DAGSTER_DAEMON_SERVICE='<compose-service>'
export E2E_C7_PINVI_API_SERVICE='<compose-service>'
export E2E_C7_PINVI_WEB_SERVICE='<compose-service>'
export E2E_C7_PINVI_DAGSTER_SERVICE='<compose-service>'
```

> 두 attested input은 ktdm이 rebuildable transaction에서 만든 v5/v7 문서의 **root 소유
> 0600 사본**이어야 한다. ktdm의 state root는 Manager owner 소유 `0700`이라 그대로는
> verifier의 root-owned 요구를 만족하지 않는다. 사본을 만들 때 내용은 바꾸지 않는다 —
> verifier가 두 파일의 SHA256을 attestation과 대조하므로 한 바이트만 달라도 멈춘다.

root snapshot의 C7 verifier는 mutation 전에 다음을 actual runtime과 exact 비교한다.

- host machine ID·hostname, compose project, 공개 UI/API/Dagster origin
- v5 active generation의 일곱 immutable image ID(Map API/UI/Dagster web/daemon,
  PinVi API/web/dagster)와 세 schema head(map application·map dagster·pinvi), pinset digest
- v7 rebuild journal이 **이 세대를 commit했다는 것** — phase `committed`, candidate가
  manifest active generation과 전체 동등, cancel probe `finalized`
- Map/PinVi source commit, OCI source revision, command hash, environment hash
- Playwright executor image와 base image identity
- Map API의 `profile=production`, features route `true`, 중복 없는 cursor signing secret
  1개(32자 이상·공백 없음), admin/service/ops read/ops cancel/metrics/VWorld credential과의 분리
- Map UI·Dagster web·Dagster daemon·PinVi API에 cursor signing secret이 없다는 음성 계약

caller가 임의 OCI label이나 자체 생성 attestation으로 이 경계를 우회할 수 없다. 검증 성공
출력은 pinned runtime manifest·rebuild journal·host attestation의 SHA256 세 개뿐이며
result에 hash로만 남는다.

## 4. 실행 순서

compose project directory에서 필요한 env를 보존해 commit별 runner를 실행한다.

```bash
sudo --preserve-env=E2E_BASE_URL,NEXT_PUBLIC_KOR_TRAVEL_MAP_API,E2E_DAGSTER_URL,E2E_ADMIN_PASSWORD,E2E_ADMIN_USERNAME,E2E_LIVE_ALLOW_PROD,E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE,E2E_C7_EXPECTED_GIT_COMMIT,E2E_C7_PINNED_RUNTIME_MANIFEST,E2E_C7_REBUILD_JOURNAL,E2E_C7_PLAYWRIGHT_IMAGE,E2E_C7_EXPECTED_UI_ORIGIN_SHA256,E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256,E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256,E2E_C7_MAP_API_SERVICE,E2E_C7_UI_SERVICE,E2E_C7_DAGSTER_WEB_SERVICE,E2E_C7_DAGSTER_DAEMON_SERVICE,E2E_C7_PINVI_API_SERVICE,E2E_C7_PINVI_WEB_SERVICE,E2E_C7_PINVI_DAGSTER_SERVICE \
  /usr/local/lib/kor-travel-map/admin-feature-live-acceptance/<40-hex>/run-admin-feature-live-acceptance.sh run
```

`/var/lib/kor-travel-map/admin-feature-live-acceptance`의 orchestrator lock과 Docker lifecycle
barrier를 잡은 뒤 다음 순서로 실행한다.

1. `BLOCKED.json`에 run identity·owned ID 8개·phase를 durable 기록한다.
2. exact API image를 `network=none`, read-only, capability 0으로 띄우되 cursor secret을 빼고
   dummy credential·production profile·features=true를 넣는다. Alembic 전에 exit 1과 generic
   cursor-secret 누락 문구가 정확히 나오는지 확인한다.
3. exact API image의 env/volume/network를 복제한 standalone labeled helper가 hidden
   weather/price Feature와 value 각 1건을 seed한다. inspect한 environment는 중복 없는
   name/value map으로 memory에서만 보유하고, Docker child process env와 `--env NAME`으로
   전달한다. 값이 argv·journal·파일에 기록되는 env snapshot은 만들지 않으며
   `docker compose exec`도 사용하지 않는다.
4. browser가 draft/inactive/hidden marker, correction, 같은 검색 이름을 공유하는 active
   search alpha/beta를 admin change request로 만들고 승인한다. idempotency key는 Feature ID의
   SHA256이라 각 생성이 충돌하지 않는다.
5. #741은 admin bbox/marker/detail/weather·price card/UI panel과 public 404를 확인한다.
   public bbox는 owned 좌표 주위의 좁은 범위에서 `mode=items`, `truncated=false`,
   `coverage.returned < coverage.limit`를 먼저 확인한 뒤 hidden ID 미포함을 단언한다.
6. `T-VN-15`는 BFF search `q + page_size=1`에서 `include_total=false`의 `total=null`과 서로
   다른 두 ID continuation, `include_total=true`의 `total=2`와 continuation을 확인한다.
   query/include_total mismatch는 `CURSOR_QUERY_MISMATCH`, payload 한 글자 변조는
   `FEATURE_SEARCH_CURSOR_TAMPERED`인 `application/problem+json` 422여야 한다.
7. #785는 승인된 competing update로 revision을 전진시키고, UI의 최초 raw `If-Match`가 412를
   받으며 dirty draft를 유지하는지 확인한다. 명시적 reload 뒤에만 새 basis를 사용한다.
8. browser recovery-only cleanup, direct cleanup, FK audit, Docker residue audit, exact evidence
   schema·phase·count·root metadata 검증을 수행한다.
9. 모든 evidence file과 directory를 `fsync`하고 result를 durable 기록한 뒤에만
   `BLOCKED.json`을 지우고 state directory를 `fsync`한다.

Playwright main/recovery report directory는 top-level regular file
`c7-summary.json`, `c7-results.xml`, `c7-summary.html` 정확히 3개만 허용한다. JSON schema와
XML/HTML의 exact redacted row·spec identity를 검증하고 fsync한다. C7 raw `test-results`는
evidence bind가 아니라 container tmpfs `/tmp/kor-travel-map-c7-test-results-<pid>`에 생성되어
container 제거와 함께 사라진다. trace, screenshot, video, URL, response/error body, raw cursor는
보존하지 않는다.

## 5. SIGKILL-safe Docker lifecycle

runner는 barrier flock의 열린 FD를 `setsid` supervisor에 상속한다. 각 helper/executor/probe마다
supervisor가 다음 순서를 단독 소유한다.

1. PID·PGID·SID·`/proc` start ticks와 deterministic name을 `ACTIVE.json`에 `intent`로 fsync
2. label 4개(run hash, actor, recovery attempt, operation)로 `docker create`
3. 반환 CID를 `ACTIVE.json`과 hash-only lifecycle evidence에 fsync
4. prepare → start → wait → exit → force remove → name/CID 부재 확인
5. exact terminal lifecycle과 `ACTIVE.json` terminal을 fsync하고 종료

runner가 SIGKILL돼도 supervisor와 barrier가 살아 있으므로 늦은 create/start/remove가 recovery와
경합하지 않는다. recovery runner는 barrier를 얻을 때까지 기다린 뒤 dead supervisor의 exact
terminal ACTIVE만 읽고 label·CID·name을 대조해 잔여 container를 지운다.

host cgroup/OOM이 runner와 supervisor를 함께 죽여 terminal outcome이 없으면 자동 recovery와
ACTIVE clear를 금지한다. `BLOCKED.json`을 유지하고 운영자가 exact label/name, PID start ticks,
Docker daemon 상태를 조사한 뒤 daemon restart 또는 host reboot로 late operation이 더 없음을
확정해야 한다. terminal이 없는 ACTIVE를 수동 삭제하고 재개하는 판단은 이 lane이 자동화하지
않는다.

## 6. recovery

v3 snapshot 배치 전 고정 state root에 `BLOCKED.json`이 없는지 확인한다. v2 BLOCKED가 남아 있으면
v3 helper로 변환하거나 삭제하지 않는다. v2에는 실행 identity가 없어 자동 호환성 판정이 불가능하므로,
생성 당시 설치 snapshot과 배포 기록을 운영자가 확정해 그 snapshot의 recovery를 먼저 완료한다.
생성 snapshot을 확정할 수 없으면 §5의 ACTIVE/container/DB 소유권을 수동 감사하고 fail-closed 상태를
유지한다. BLOCKED가 완전히 종결된 뒤에만 v3 snapshot을 활성화한다.

같은 배포 env와 commit snapshot으로 실행한다. 최초 실행은 BLOCKED v3에 source commit,
API·Playwright image ID, pinned runtime manifest·rebuild journal·host attestation hash의 exact execution
identity를 기록한다. recovery는 현재 runtime attestation에서 다시 얻은 identity가 BLOCKED와
완전히 같을 때만 attempt를 증가시키며, 하나라도 다르면 mutation 전에 fail-closed한다. 성공 result
v3에는 exact identity의 canonical SHA256과 pair/attestation hash만 남기고 원문은 남기지 않는다.

```bash
sudo --preserve-env=E2E_BASE_URL,NEXT_PUBLIC_KOR_TRAVEL_MAP_API,E2E_DAGSTER_URL,E2E_ADMIN_PASSWORD,E2E_ADMIN_USERNAME,E2E_LIVE_ALLOW_PROD,E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE,E2E_C7_EXPECTED_GIT_COMMIT,E2E_C7_PINNED_RUNTIME_MANIFEST,E2E_C7_REBUILD_JOURNAL,E2E_C7_PLAYWRIGHT_IMAGE,E2E_C7_EXPECTED_UI_ORIGIN_SHA256,E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256,E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256,E2E_C7_MAP_API_SERVICE,E2E_C7_UI_SERVICE,E2E_C7_DAGSTER_WEB_SERVICE,E2E_C7_DAGSTER_DAEMON_SERVICE,E2E_C7_PINVI_API_SERVICE,E2E_C7_PINVI_WEB_SERVICE,E2E_C7_PINVI_DAGSTER_SERVICE \
  /usr/local/lib/kor-travel-map/admin-feature-live-acceptance/<40-hex>/run-admin-feature-live-acceptance.sh recover
```

recovery attempt는 BLOCKED에서 원자적으로 증가한다. 새 fixture를 만들지 않고 다음만 한다.

- terminal ACTIVE drain과 exact owned container removal
- API-owned pending request reject 또는 delete approve, 모든 API-owned Feature `deleted`·public 404,
  exact search query의 `items=[]`, `total=0`, cursor null/absent
- direct weather/price parent와 기존 weather/price child row를 모두 `SELECT ... FOR UPDATE`로 잠근
  같은 transaction 안에서 child value fingerprint·모든 FK reference를 audit하고 두 parent를 삭제
- 삭제 후 direct 0/0/0·FK reference 0, label/name container 0, ACTIVE 없음 확인
- recovery report/evidence exact 검증·fsync, recovered result 기록, 마지막 BLOCKED unlink

`FOR UPDATE` parent lock은 concurrent child insert가 얻는 `KEY SHARE`와 충돌하고 기존 child
row lock은 fingerprint 검사 중 동시 변경을 막으므로 audit와 delete 사이의 창을 닫는다.
fingerprint가 다르면 다른 운영 row일 수 있으므로 아무 것도 삭제하지 않고 BLOCKED를 유지한다.

## 7. 완료 판정

- runner exit 0, `BLOCKED.json`·`ACTIVE.json` 없음
- latest result가 `status=complete`, `phase=passed|recovered`, recovery attempt와 두 attestation
  hash를 포함하고 원문 identity를 포함하지 않음
- normal은 probe/direct seed·cleanup·audit, main/recovery report, 6개 operation × 8개 exact
  lifecycle phase가 있음; recovery는 3개 operation × 8개 phase가 있음
- 모든 evidence directory `root:root 0700`, file `root:root 0600`
- 각 Playwright directory의 exact 3-file redacted report 외 directory·symlink·extra file 없음
- direct audit 0/0/0, FK reference 0, API-owned pending 0, public projection 0
- exact search query의 items 0, total 0, next cursor null/absent
- run label container 0 및 가능한 모든 actor/attempt/operation deterministic name container 0
- 같은 exact tree의 PostgreSQL regression 증거에서 search `include_total=false` COUNT 0회,
  `include_total=true` COUNT 1회. production HTTP 결과만으로 SQL 실행 횟수를 추정하지 않음

이슈에는 실행 시각, exact source commit, pinned generation/journal/attestation hash, passed/recovered,
cleanup/audit/container 0 결과만 적는다. secret·origin·host·run ID·Feature ID·container ID·cursor
원문은 적지 않는다.
