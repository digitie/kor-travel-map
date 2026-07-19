# C7 production live E2E 실행·복구

이 문서는 `T-ADM-C7`의 n150 파괴적 live UI E2E를 실행하는 유일한 운영 순서를
정의한다. 실제 host, URL, 계정, 비밀번호, token, hash는 gitignore된
`docs/deploy-runbook.local.md`와 `docs/prod-access.local.md`에만 둔다.

## 1. 완료로 인정하는 경계

C7은 다음 조건을 모두 만족해야 완료다.

1. `T-ADM-C6c` compatible-pair capture가 성공했고 Manager v3 manifest의 active
   Map·PinVi image가 실제 두 API container image와 일치한다.
2. host runner/helper/attestation 검증 모듈/상태 감사기는 exact commit의 root-owned Git archive snapshot으로
   고정되고, API·UI·Dagster web·Dagster daemon·
   PinVi API의 image/command/environment hash가 root-owned attestation과 일치한다.
3. Map DB의 Alembic current가 image의 유일한 head와 같고 `alembic check`가 통과한다.
4. Playwright는 host Chromium이 아니라
   `mcr.microsoft.com/playwright:v1.60.0-noble@sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948`
   기반의 C7 executor image에서 실행한다. executor label의 Git commit도 실행 checkout과
   같아야 한다.
5. 실제 Dagster repository에 `feature_update_request_worker` job이 정확히 하나 있고,
   각 terminal request의 `runOrError.jobName`과 request/generation/scope/sensor tag가
   해당 실행과 일치한다.
6. sensor·schedule·KMA·POI 상태가 원래 값으로 정확히 복구되고, redacted 결과와 복구
   증거가 root-owned evidence 디렉터리에 보존된다.

단순 HTTP 200, Playwright pass 수, container `running`만으로는 완료 처리하지 않는다.

## 2. 실행 전 순서

### 2.1 C6c와 DB 전환

1. Map API·Dagster writer를 maintenance fence로 막고 동일 배포 mutation window를
   독점한다.
2. DB backup/PITR recovery point와 기존 env/compose bytes·mode·owner, 모든 대상
   container image/command/environment hash를 기록한다.
3. 배포할 clean commit에서 Map API image를 먼저 만든다.
   `KOR_TRAVEL_MAP_GIT_COMMIT=$(git rev-parse HEAD)`를 build arg로 전달해 API·UI·Dagster
   image의 `org.opencontainers.image.revision`을 같은 commit으로 고정한다.
4. 해당 image의 migration-only 경로로 `alembic upgrade head`를 실행한다. 이 시점부터
   구 image 재시작은 rollback이 아니다. 실패하면 새 image forward-fix 또는 DB
   restore/PITR만 허용한다.
5. `current == unique heads`와 `alembic check`를 확인한다.
6. `start_unpaired_import_job(kind="c6c_cancel_probe", trigger_kind="system")` 정식
   repository 경로로 owned cancel fixture를 만들고 transaction을 commit한다. raw SQL
   fixture는 금지한다.
7. UI credential을 UI-only exact-image recreate로 먼저 회전하고 새 로그인→보호 화면→
   로그아웃→재차단 및 구 credential 401을 확인한다. 실패하면 저장한 env/config/image로
   UI만 정확히 복구한다.
8. Manager의 `pinvi-pair capture --verified-compatible --build`를 실행한다. manifestless
   capture가 mutation 뒤 실패하면 임의 rollback 성공을 꾸미지 않고 두 API를 중지한 채
   operator-required로 남긴다.

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
정확한 version 3이어야 한다. active/rollback pair에는 Map·PinVi source revision이 필수다.
Manager canonical compatible-pair manifest도 capture 직후 bytes를
root-owned `0600` snapshot으로 만들고, runner에는 그 absolute path를 전달한다. 원본과 snapshot
SHA-256이 다르면 실행하지 않는다. attestation에는 다음 비민감 증거만 넣는다.

- machine-id·hostname·공개 UI/API WebSocket/Dagster GraphQL origin의 SHA-256
- compose project 이름의 SHA-256
- clean repository commit
- Map·PinVi source commit과 각 immutable image의 `org.opencontainers.image.revision`
- root-owned runner/helper/attestation 검증 모듈/상태 감사기 상대경로 4개의 SHA-256(`orchestrator_files`)
- C6c compatible-pair manifest bytes의 SHA-256과 contract generation
- Map API·UI·Dagster web·Dagster daemon·PinVi API별 image ID, canonical
  `{Path,Args,Entrypoint,Cmd}` command SHA-256,
  정렬된 environment 전체의 SHA-256
- C7 Playwright executor image ID와 고정 base image reference

environment hash는 값 자체를 출력하지 않고 container inspect 결과를 정렬한 canonical
JSON bytes에서 계산한다. attestation 작성 명령과 실제 값은 local runbook에만 둔다.

## 3. runner 실행

`/usr/local/lib/kor-travel-map/c7-runner/<exact-commit>/scripts/run-c7-prod-live-e2e.sh`의
root-owned snapshot만 root로 실행한다. 모든 URL·credential·service 이름·
origin hash·Git commit·manifest path·executor image ID와 destructive opt-in은 명시 env로
전달한다. runner가 요구하는 env 목록은 `require_env` 구간이 정본이며 기본 credential과
기본 production URL은 없다.

runner는 아래 순서를 지킨다.

1. env/command/root-owned orchestrator snapshot/host/runtime/compatible-pair/Alembic을 read-only 검증하고 UI login을
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
   Playwright report, attachment와 auth storage는 생성하거나 evidence로 복사하지 않는다. 비밀값이 없는 root runtime
   attestation과 compatible-pair snapshot은 함께 복제하고 manifest hash로 결박한다.
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
   `412`, UUID drift, 응답 유실은 자동 삭제하지 않는다.
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

evidence manifest의 Git commit, service image ID, compatible manifest hash, Alembic head,
spec별 결과, 복구 검증 hash를 `docs/journal.md`와 issue 코멘트에 비밀 없이 요약한다.
그 증거가 모두 있을 때만 `T-ADM-C6c`, `T-ADM-C7`과 #684/#694/#712/#719를 닫는다.
