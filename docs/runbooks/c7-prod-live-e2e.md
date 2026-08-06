# C7 production live E2E 실행·복구

이 문서는 `T-ADM-C7`의 n150 파괴적 live UI E2E를 실행하는 유일한 운영 순서를
정의한다. 실제 host, URL, 계정, 비밀번호, token, hash는 gitignore된
`docs/deploy-runbook.local.md`와 `docs/prod-access.local.md`에만 둔다.

## 1. 완료로 인정하는 경계

C7은 다음 조건을 모두 만족해야 완료다.

1. Manager v5 pinned-runtime manifest의 `active_generation`과 v7 rebuild journal의
   committed `candidate`가 완전히 같고, Map API·UI·Dagster web·Dagster daemon 및
   PinVi API·web·Dagster image가 실제 일곱 runtime container image와 각각 일치한다.
2. host runner/helper/attestation 검증 모듈/상태 감사기는 exact commit의 root-owned Git archive snapshot으로
   고정되고, API·UI·Dagster web·Dagster daemon·
   PinVi API·web·Dagster의 image/command/environment hash가 root-owned attestation과
   일치한다.
3. Map API image 안에서 `ktm-application-schema head`가 출력한 ADR-085 installed artifact head와
   Map DB Alembic `current`가 v5 active generation의 단일 `map_application_head`에 각각 정확히
   같고 `alembic check`가 통과한다. source checkout·cwd·bind mount·`alembic heads`는 image head
   증거가 아니다. Map Dagster·PinVi head는 같은 generation과 final-schema reload receipt에 exact
   결박한다.
4. root-owned final-schema reload receipt가 같은 manifest/journal 및 세 schema head에 결박되고,
   source reload·ETL reload가 모두 성공했으며 canonical dataset availability가 available이다.
5. Playwright는 host Chromium이 아니라
   `mcr.microsoft.com/playwright:v1.60.0-noble@sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948`
   기반의 C7 executor image에서 실행한다. executor label의 Git commit도 실행 checkout과
   같아야 한다.
6. 실제 Dagster repository에 `feature_update_request_worker` job이 정확히 하나 있고,
   각 terminal request의 `runOrError.jobName`과 request/generation/scope/sensor tag가
   해당 실행과 일치한다.
7. sensor·schedule·KMA·POI 상태가 원래 값으로 정확히 복구되고, redacted 결과와 복구
   증거가 root-owned evidence 디렉터리에 보존된다.

단순 HTTP 200, Playwright pass 수, container `running`만으로는 완료 처리하지 않는다.

## 2. 실행 전 순서

### 2.1 runtime generation과 DB 전환

1. Map API·Dagster writer를 maintenance fence로 막고 동일 배포 mutation window를
   독점한다.
2. 기존 env/compose bytes·mode·owner와 모든 대상 container image/command/environment hash를 기록한다.
   개발 단계에서는 중간 DB preimage backup/PITR·restore를 correctness 경로로 사용하지 않는다.
3. 배포할 clean commit에서 Map API image를 먼저 만든다.
   `KOR_TRAVEL_MAP_GIT_COMMIT=$(git rev-parse HEAD)`를 build arg로 전달해 API·UI·Dagster
   image의 `org.opencontainers.image.revision`을 같은 commit으로 고정한다.
4. 해당 image의 migration-only 경로로 `alembic upgrade head`를 실행한다. 이 시점부터
   구 image 재시작은 rollback이 아니다. 실패하면 새 image forward-fix 또는 DB
   final schema source/ETL 재적재 receipt를 새로 만들기 전에는 data-dependent live E2E를 허용하지 않는다.
5. installed `ktm-application-schema head` 출력과 DB `current`가 generation의
   `map_application_head`에 각각 정확히 같은지, 이어서 `alembic check`를 확인한다.
6. `start_unpaired_import_job(kind="c6c_cancel_probe", trigger_kind="system")` 정식
   repository 경로로 owned cancel fixture를 만들고 transaction을 commit한다. raw SQL
   fixture는 금지한다.
7. UI credential을 UI-only exact-image recreate로 먼저 회전하고 새 로그인→보호 화면→
   로그아웃→재차단 및 구 credential 401을 확인한다. 실패하면 저장한 env/config/image로
   UI만 정확히 복구한다.
8. Manager의 v5 pinned-runtime generation을 확정하고, rebuild journal v7이
   `phase=committed` 및 finalized cancellation probe receipt를 남겼는지 확인한다.
   generation 또는 journal 확정이 mutation 뒤 실패하면 임의 rollback 성공을 꾸미지 않고
   Map 네 runtime과 PinVi 세 runtime을 중지한 채 operator-required로 남긴다.

### 2.2 실행 checkout과 Playwright executor

GitHub에서 직접 최신 branch를 다시 해석하지 않는다. CI green으로 병합된 exact commit을
n150 source checkout에 fetch한 뒤, root shell의 `git archive <exact commit>`으로 runner, helper,
attestation 검증 모듈, 상태 감사기 네 파일만
immutable snapshot에 배치한다. 파괴적 실행은 user-writable checkout의 script를 직접 `sudo`하지 않는다.

```bash
git rev-parse HEAD
git status --porcelain=v1
scripts/build-c7-playwright-image.sh

commit="$(git rev-parse HEAD)"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]]
sudo env SOURCE_REPO="$PWD" C7_COMMIT="$commit" /bin/bash -o pipefail -ceu '
  parent=/usr/local/lib/kor-travel-map/c7-runner
  destination="$parent/$C7_COMMIT"
  install -d -o root -g root -m 0755 "$parent"
  test ! -e "$destination"
  temporary="$(mktemp -d "$parent/.install.XXXXXX")"
  trap '\''rm -rf -- "$temporary"'\'' EXIT
  git -c safe.directory="$SOURCE_REPO" -C "$SOURCE_REPO" archive --format=tar \
    "$C7_COMMIT" \
    scripts/run-c7-prod-live-e2e.sh \
    scripts/audit-c7-prod-live-state.py \
    scripts/lib/c7-prod-runner-lifecycle.sh \
    scripts/lib/c7_prod_attestation.py |
    tar --no-same-owner -xf - -C "$temporary"
  chown -R root:root "$temporary"
  find "$temporary" -type d -exec chmod 0755 {} +
  find "$temporary" -type f -exec chmod 0555 {} +
  mv -T -- "$temporary" "$destination"
  trap - EXIT
'
```

script는 ignored/untracked file을 포함할 수 없는 exact Git archive context로 build한다. `git status`가
비어 있지 않거나 executor label/image ID가 root attestation과 다르면 실행하지 않는다. runner에는
tag가 아니라 script가 출력한 `sha256:<64>` executor image ID를 전달한다.
attestation의 `orchestrator_files`에는 위 snapshot의 runner/helper/attestation 모듈/상태 감사기 상대경로와
SHA-256을 정확히 기록한다. runner bootstrap은 검증 모듈을 한 번 읽어 owner/mode/ancestor/hash를
확인한 동일 bytes만 실행한다. 그 모듈은 다시 전체 snapshot의 exact shape와 네 파일 hash를 검증한다.
runner는 `/usr/local/lib/kor-travel-map/c7-runner/<commit>` 외 위치, root 외 owner,
group/other writable ancestor, mode `0555`, hash 불일치를 모두 거부한 뒤에만 helper를 source한다.

### 2.3 root-owned attestation

`/etc/kor-travel-map/c7-prod-live-e2e-attestation.json`은 배포가 끝난 뒤 local-only
절차로 원자 생성한다. mode는 `0600`, owner는 `root:root`, version은 runner가 요구하는
정확한 version 5여야 한다. 이 version은 host attestation document 계약이며
Manager pinned-runtime manifest version과 다르다. Manager canonical pinned-runtime manifest는
정확한 version 5이며 `active_generation` 하나만 가진다. generation은
`map_api_image_id`, `map_ui_image_id`, `map_dagster_image_id`,
`map_dagster_daemon_image_id`, `pinvi_api_image_id`, `pinvi_web_image_id`,
`pinvi_dagster_image_id`, Map·PinVi source revision, Map application·Dagster와 PinVi schema
head, `pinset_sha256`, `recorded_at`의 exact set이어야 한다. 같은 generation을 가진
version 7 rebuild journal은 `phase=committed`와 finalized `pinvi_cancel_error` 409
cancellation receipt를 가져야 한다. 구 version 또는 누락·추가 필드는 호환 변환 없이
거부한다. capture 직후 manifest와 journal bytes를
root-owned `0600` snapshot으로 만들고, runner에는 그 absolute path를 전달한다. 원본과 snapshot
SHA-256이 다르면 실행하지 않는다. attestation에는 다음 비민감 증거만 넣는다.

- machine-id·hostname·공개 UI/API WebSocket/Dagster GraphQL origin의 SHA-256
- compose project 이름의 SHA-256
- clean repository commit
- Map·PinVi source commit과 각 immutable image의 `org.opencontainers.image.revision`
- root-owned runner/helper/attestation 검증 모듈/상태 감사기 상대경로 4개의 SHA-256(`orchestrator_files`)
- v5 pinned-runtime manifest와 v7 rebuild journal bytes의 SHA-256, generation의
  three schema heads와 pinset hash
- Map API·UI·Dagster web·Dagster daemon·PinVi API·web·Dagster별 image ID, canonical
  `{Path,Args,Entrypoint,Cmd}` command SHA-256,
  정렬된 environment 전체의 SHA-256
- C7 Playwright executor image ID와 고정 base image reference

environment hash는 값 자체를 출력하지 않고 container inspect 결과를 정렬한 canonical
JSON bytes에서 계산한다. attestation 작성 명령과 실제 값은 local runbook에만 둔다.
attestation은 각 role의 compose service와 immutable container ID도 함께 보유한다. caller가 전달한
service env, compose `ps` 결과, inspect ID가 모두 이 binding과 같아야 하며 UI/API WebSocket/Dagster
GraphQL endpoint는 각각 Map UI/API/Dagster web role에 정확히 결박된다. runner는 위 일곱 runtime role의 image ID를 host attestation과 비교한 뒤, Map 네 role와
PinVi 세 role를 manifest active generation image ID와 각각 비교한다. 각 OCI revision은
generation의 해당 Map 또는 PinVi source revision과 같아야 하며, journal candidate와
manifest generation의 불일치도 거부한다.

### 2.4 Docker Manager 전역 lease/TOCTOU 경계 (Map 구현 범위 밖)

Map runner는 Docker Manager의 compose/container lifecycle을 조작하거나 lease를 흉내 내지
않는다. final C7 시작 전에 Manager가 제공해야 하는 다음 **원자 capture interface**가
전역 deployment lease 아래에서 성공해야 한다. 이는 Map의 local attestation을 대체하지
않으며, Manager 구현 전에는 final C7을 승인할 수 없다.

입력은 `contract="c7-final-generation-capture.v1"`와 예상 active generation canonical
SHA-256 하나다. 출력은 하나의 linearizable 응답으로 다음 exact record를 가져야 한다.

```json
{
  "contract":"c7-final-generation-capture.v1",
  "lease_epoch": 1,
  "pinned_runtime_manifest_sha256":"<64-lowercase-hex>",
  "pinned_runtime_rebuild_journal_sha256":"<64-lowercase-hex>",
  "active_generation_sha256":"<64-lowercase-hex>",
  "runtime_roles": {
    "map_api":{"compose_service":"<name>","container_id":"<64-hex>","image_id":"sha256:<64-hex>"},
    "map_ui":{"compose_service":"<name>","container_id":"<64-hex>","image_id":"sha256:<64-hex>"},
    "map_dagster_web":{"compose_service":"<name>","container_id":"<64-hex>","image_id":"sha256:<64-hex>"},
    "map_dagster_daemon":{"compose_service":"<name>","container_id":"<64-hex>","image_id":"sha256:<64-hex>"},
    "pinvi_api":{"compose_service":"<name>","container_id":"<64-hex>","image_id":"sha256:<64-hex>"},
    "pinvi_web":{"compose_service":"<name>","container_id":"<64-hex>","image_id":"sha256:<64-hex>"},
    "pinvi_dagster":{"compose_service":"<name>","container_id":"<64-hex>","image_id":"sha256:<64-hex>"}
  }
}
```

Manager acceptance는 다음 네 가지다.

1. response를 만들 때와 root-owned manifest/journal snapshot을 publish할 때까지 하나의
   전역 lease epoch를 유지한다. 중간 recreate, image pull, compose apply, container replacement는
   모두 같은 lease에서 배제한다.
2. response의 두 bytes hash와 generation hash는 snapshot의 canonical bytes에서 다시 계산한 값과
   같고, rebuild journal candidate는 manifest active generation과 exact 같아야 한다.
3. seven role의 service/container/image는 같은 capture 시점의 inspect 결과이며, image가
   active generation의 해당 image와 정확히 같아야 한다. 중복 container 또는 role 누락은 실패다.
4. 후속 Map reader는 response의 lease epoch와 role binding을 host attestation에 복사해 runner
   직전과 직후 각각 재검증해야 한다. epoch나 container ID가 달라지면 cleanup보다 먼저 BLOCKED로
   fail-closed하며, Map은 이를 repair하거나 Manager lease를 해제하지 않는다.

이 interface의 구현·global lock 수명·Manager recovery는 `kor-travel-docker-manager`의 후속
작업이다. 이 저장소는 위 read-only acceptance boundary와 root snapshot 검사만 소유한다.
따라서 현 local attestation은 Map 코드 검증 증거일 뿐, 이 capture/reader가 함께 도입되기 전에는
전역 TOCTOU-free final C7 sign-off가 아니다.

### 2.5 final-schema reload receipt 생성·snapshot·attestation 결박

receipt는 **최종 schema**에서 source reload와 ETL reload가 성공하고 canonical dataset availability가
확정된 뒤에만 root가 만든다. 중간 DB preimage, 이전 receipt, source checkout의 임의 JSON을 복사하거나
복원 근거로 삼지 않는다. root shell은 먼저 Manager가 확정한 manifest와 rebuild journal을 각각 별도
`root:root 0600` 파일로 snapshot한다. 이후 root-owned 입력 파일에서 source/ETL 결과만 읽고 다음 exact
receipt를 원자적으로 생성한다.

```json
{
  "version": 1,
  "pinned_runtime_manifest_sha256": "<64-lowercase-hex>",
  "pinned_runtime_rebuild_journal_sha256": "<64-lowercase-hex>",
  "schema_heads": {
    "map_application": "<active-map-application-head>",
    "map_dagster": "<active-map-dagster-head>",
    "pinvi": "<active-pinvi-head>"
  },
  "source_reload": {
    "status":"succeeded",
    "source_snapshot_sha256":"<root-snapshotted-source-output-64-lowercase-hex>",
    "observed_generation_sha256":"<canonical-active-generation-64-lowercase-hex>",
    "observed_map_api_image_id":"sha256:<64-lowercase-hex>",
    "observed_schema_heads":{"map_application":"<head>","map_dagster":"<head>","pinvi":"<head>"},
    "completed_at":"<UTC>"
  },
  "etl_reload": {
    "status":"succeeded",
    "run_id":"<canonical-UUID>",
    "result_sha256":"<root-snapshotted-ETL-result-64-lowercase-hex>",
    "consumed_source_snapshot_sha256":"<source_reload.source_snapshot_sha256>",
    "rebuild_transaction_id":"<committed-v7-rebuild-journal-transaction_id>",
    "observed_generation_sha256":"<canonical-active-generation-64-lowercase-hex>",
    "observed_map_api_image_id":"sha256:<64-lowercase-hex>",
    "observed_schema_heads":{"map_application":"<head>","map_dagster":"<head>","pinvi":"<head>"},
    "completed_at":"<UTC>"
  },
  "canonical_dataset_availability": {"status":"available","dataset_count":1,"feature_count":1,"availability_sha256":"<64-lowercase-hex>"},
  "recorded_at": "<UTC>"
}
```

절차의 입력·출력 경로는 local runbook에서만 정한다. 다음은 그 경로를 비밀 없이 재현하는 최소 순서다.

1. root가 manifest, journal, 그리고 `{source_reload, etl_reload, canonical_dataset_availability}`만 가진
   final reload 입력을 각각 regular file·`root:root 0600`으로 snapshot한다. source output과 ETL terminal
   result bytes의 SHA-256을 각각 `source_snapshot_sha256`, `result_sha256`으로 기록한다. source/ETL 완료 시각,
   count/hash/run ID는 실행 결과를 그대로 사용하며 다시 계산하거나 추측하지 않는다.
2. root가 manifest의 `active_generation` canonical compact JSON SHA-256과 Map API image ID, 세 head를
   **각각의** `source_reload`·`etl_reload`의 `observed_*` field에 넣는다. 따라서 이미 끝난 옛 schema의
   source/ETL output을 새 receipt top-level에 다시 포장하는 것만으로는 verifier를 통과할 수 없다.
   v7 `rebuild_journal.created_at < source_reload.completed_at < etl_reload.completed_at < recorded_at`을
   만족시키고, ETL의 `consumed_source_snapshot_sha256`은 같은 receipt의 source hash와, `rebuild_transaction_id`는
   committed v7 journal의 `transaction_id`와 각각 exact 일치시킨다. compact JSON bytes를 temporary `0600`
   file에 `fsync`한 뒤 `rename`한다.
3. 대상 parent directory를 `fsync`하고 최종 receipt가 regular file, `root:root`, mode `0600`이며
   `sha256sum`이 기록한 값과 같은지 root가 다시 확인한다. 이 절차의 산출 path만
   `E2E_C7_FINAL_SCHEMA_RELOAD_RECEIPT`로 전달한다.
4. host attestation candidate를 publish하기 직전에 그 SHA-256을
   `final_schema_reload_receipt_sha256` field에 exact 문자열로 넣는다. receipt snapshot과 attestation을
   모두 `root:root 0600` temporary file → `fsync` → atomic `rename`으로 publish하고, runner 전
   `sha256sum <receipt>`가 attestation field와 같은지 재확인한다. 어느 한쪽을 다시 만들면 둘 다
   새 snapshot으로 다시 결박한다.

runner는 receipt의 exact shape, manifest/journal bytes hash, 세 head, 각 reload의 generation/image/head
cryptographic binding, source/ETL 성공, positive canonical dataset/feature count와 timestamp ordering을
다시 검증한다. 따라서 위 절차는 승인 근거를 생성할 뿐 Python verifier를 우회하지 못한다.

## 3. runner 실행

runner를 실행하기 전 Map exact commit은 C7 v5 reader와 해당 generation의 모든 필수
producer/consumer 변경이 main에 함께 병합된 최종 commit이어야 한다. producer 또는
consumer 한쪽만 main에 병합된 중간 commit은 배포·capture·live 실행 대상이 아니다.

`/usr/local/lib/kor-travel-map/c7-runner/<exact-commit>/scripts/run-c7-prod-live-e2e.sh`의
root-owned snapshot만 root로 실행한다. 모든 URL·credential·service 이름·
origin hash·Git commit·manifest/rebuild journal/final-schema reload receipt path(`E2E_C7_FINAL_SCHEMA_RELOAD_RECEIPT`)·executor image ID와 destructive opt-in은 명시 env로
전달한다. runner가 요구하는 env 목록은 `require_env` 구간이 정본이며 기본 credential과
기본 production URL은 없다.

runner는 아래 순서를 지킨다.

1. env/command/root-owned orchestrator snapshot/host/runtime/pinned manifest/rebuild journal/final-schema reload receipt/installed schema artifact·DB Alembic을 read-only 검증하고 UI login을
   domain-state 비파괴 preflight한다. 로그인은 session/auth audit를 만들 수 있지만
   provider/request/POI/schedule state는 바꾸지 않는다.
2. root state lock을 잡고 기존 `BLOCKED.json`, journal, `.state.*`, `runtime.*` residue가
   없음을 확인한다.
3. 모든 preflight가 끝난 뒤에만 `BLOCKED.json`과 durable journal을 만든다.
4. 고정 executor image는 먼저 `docker create --pull=never`로 정지 상태에 만들고, creator
   PID/PGID/session ID/start ticks와 atomic outcome, valid CID, name/label/runtime/security identity를 fsync·검증한
   뒤에만 `docker start --attach`한다. spec은 worker 1, retry 0으로 실행한다.
5. 각 spec은 assertion value/error/stdout/stderr/URL을 버린 redacted JUnit/HTML/JSON만
   spec별 디렉터리에 분리한다. 운영값이 픽셀에 남을 수 있는 screenshot, trace, raw
   Playwright report, attachment와 auth storage는 evidence로 복사하지 않는다. C7 raw
   `test-results` output은 evidence bind 밖 container tmpfs
   `/tmp/kor-travel-map-c7-test-results-<pid>`에만 생성하고 container 제거와 함께 폐기한다.
   비밀값이 없는 root runtime attestation, pinned manifest, rebuild journal, final-schema reload receipt
   snapshot은 함께 복제하고 네 hash로 결박한다.
6. 원격 상태를 다시 읽어 exact restoration을 검증하고 evidence를 fsync한 뒤에만
   journal과 `BLOCKED.json`을 제거한다.

## 4. `BLOCKED.json` 복구

`BLOCKED.json`이 있으면 runner를 재실행하거나 파일을 바로 지우지 않는다.

```bash
sudo python3 scripts/audit-c7-prod-live-state.py
```

exit `0`은 복구 잔여가 없는 안전한 상태, `3`은 active lock/creator/running C7 container,
`4`는 `BLOCKED.json`·journal·runtime·creator ref/CID 등 수동 복구 필요, `5`는 unsafe/corrupt state다.
`3`이면 실행자를 먼저 확인하고 종료를 기다린다. SIGKILL로 실행자가 사라졌는데 container가
남았으면 다음 도구로 C7 label·이름·run 전용 mount와 lock을 재검증한 뒤 그 container만
stop/remove한다. 이 도구는 journal·runtime·evidence·`BLOCKED.json`을 지우지 않는다.

```bash
sudo python3 scripts/stop-c7-prod-live-container.py
```

감사 도구는 값이나 UUID를 출력하지 않고 root/mode, sentinel, journal 종류별 개수,
`runtime.*`·`.state.*`, evidence 존재 여부만 보고한다. 다음 순서로 수동 복구한다.

1. mutation window를 다시 독점하고 API/Dagster writer를 fence한다.
2. `runtime.*/journals/{sensor,schedule,kma,poi}.json`을 root만 읽을 수 있는 recovery
   evidence로 복제하고 SHA-256을 기록한다. 이전 runner의 root 직하 journal도 있으면 함께 보존한다.
3. sensor와 schedule은 journal의 최초 selector/state와 실제 Dagster GraphQL을 비교해
   복구한다. 소유하지 않은 concurrent state면 덮어쓰지 않는다.
4. KMA request·target과 POI target은 journal의 exact 자연키/UUID/ETag/body를 사용한다.
   KMA final/recovery journal은 v5만 유효하며, `request_id ↔ idempotency entry ↔
   {provider_dataset_id,sync_scope,operation_key}`가 각각 한 번씩 정확히 결박돼야 한다.
   `operation_key`는 canonical `feature_weather_kma_ultra_short_nowcast_job`와 body·active/detail/membership·dataset
   deep-link/query 모두에서 exact 일치해야 한다. v3은 runner가
   첫 write 전에 만드는 빈 bootstrap placeholder만 허용하며 recovery/final journal으로
   변환하거나 해석하지 않는다. `412`, UUID drift, 응답 유실 또는 이 결박 불일치는
   자동 삭제하지 않는다.
5. 공개 UI session으로 schedule/KMA/POI의 최종 read-only equality와 owned scope 0건을
   다시 검증한다.
6. 검증 결과를 evidence에 원자 기록하고 fsync한다. 그 뒤에만 operator가 journal과
   sentinel을 제거한다. 감사 도구는 의도적으로 자동 clear를 제공하지 않는다.

SIGKILL 뒤에는 `container-*.json` creator ref와 `container-*.outcome.json`, empty/partial일 수도 있는
`container-*.cid`를 함께 확인한다. 도구는 creator PID/PGID/session ID/start ticks와 같은 process
group의 잔존 descendant까지 대조해 종료하고, exact
name 또는 valid CID의 container가 `io.kortravelmap.c7.runner=prod-live-e2e` label과 동일한
`runtime.*` bind mount를 가졌을 때만 stop/remove한다. creator가 종료됐고 CID **경로 자체**와 outcome,
name이 모두 없으면 FIFO release 전에 끝난 `resolved-unstarted`로 판정해 ref만 제거한다. empty/partial
CID 경로가 있고 conclusive outcome이나 검증된 exact-name container도 없거나 creator/container 존재 여부가
불확실하면 late create가 끝났다고 추측하지 않고 ref를 보존한 채 exit `4`로 남긴다. 이 경우 audit/stop을
반복하고 ref를 수동 삭제하지 않는다.
그 뒤 `runtime.*`의 auth storage를 root-only로 격리해 cookie 파일을 폐기한다. Playwright trace
ZIP은 cookie를 포함할 수 있으므로 보존하지 않는다.
`.state.*`가 남으면 최종 파일과 bytes를 비교해 commit 여부를 판정하기 전 이동·삭제하지 않는다.

## 5. 완료 기록

evidence manifest의 Git commit, service image ID, pinned manifest·rebuild journal·final-schema reload receipt hash,
installed artifact/DB가 함께 증명한 `map_application_head`,
spec별 결과, 복구 검증 hash를 `docs/journal.md`와 issue 코멘트에 비밀 없이 요약한다.
그 증거가 모두 있을 때만 `T-ADM-C7`과 #684/#694/#712/#719를 닫는다.
