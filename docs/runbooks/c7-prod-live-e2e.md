# [보존 이력 · 실행 금지] C7 production live E2E 실행·복구

> 이 문서는 retired C7/rebuildable workflow의 과거 기록이다. `300` baseline의 n150 배포에는
> 사용하지 않는다. `pinvi-pair rebuild-pinned`, DB restore/PITR, old image restart, raw Alembic
> 편집은 H46H handoff의 대안이 아니다. 현행 sequence는 `T-VN-H46H` 설계 문서와
> `docs/backup-restore.md`를 따른다.

> **ADR-102 결정 6 (2026-09-26) — attestation 체인 제거.** 아래 §1의 2번, §2.2의 root 소유
> `c7-runner` snapshot 설치, §2.3의 host attestation과 v5/v6 manifest·v7/v8 journal 사본,
> §3 5번의 attested document evidence 복제는 **더 이상 러너의 동작이 아니다.** 러너
> (`scripts/run-c7-prod-live-e2e.sh`)는 핀된 SHA의 평범한 `git archive` 체크아웃에서 돌고,
> `E2E_C7_PINNED_RUNTIME_MANIFEST`·`E2E_C7_REBUILD_JOURNAL`을 요구하지 않는다. 실행 전
> runtime preflight는 `scripts/lib/c7_prod_runtime.py`가 caller env와 `docker inspect`만으로
> 한다 — origin 세 개, compose service 일곱의 running/healthy·compose project·cursor secret
> 위생, Map 네 image의 OCI revision == `E2E_C7_EXPECTED_GIT_COMMIT`, executor image label.
> 떠 있는 image가 핀된 세대인지는 Manager가 대조한다. evidence manifest는 v3(attested digest
> 없음)이고, 감사기는 v1·v2 archive를 legacy로 계속 인정한다. n150 호스트 스크립트는
> `scripts/n150/`이 정본이다.

> **2026-10-01 — KMA lane 퇴역(ADR-104/105).** Map은 weather를 더 적재하지 않고 KMA catalog
> operation은 거절된다. 그래서 KMA exact-scope 3-spec(`ops-c7-kma-{active,cap,empty}-write`)과
> contract preflight, queue sensor barrier(`sensor.json`), KMA journal(`kma.json`), grid cap
> 대조(`kma_weather_max_grids_per_run`), C7 Dagster GraphQL client와 그 Basic Auth bind를
> 지웠다. 옛 schedule allowlist(`feature_weather_kma_short_forecast_hourly_schedule`)는
> 2026-09-09에 사라져 그날부터 러너가 돌 수 없었다. 현재 C7 blocking gate는
> `ops-c7-read-auth` + `ops-c7-schedule-write` + `poi-cache-targets-write`의 `@c7-causal`
> 한 건이다. schedule allowlist는 `feature_place_krairport_airports_monthly_schedule`
> (공항 fetcher는 krairport 번들 정적 데이터만 읽어 tick이 나가도 upstream 호출이 0)이고,
> 러너 env에서 `E2E_DAGSTER_JOB`·`E2E_DAGSTER_RUN`·`E2E_KMA_SCOPE_WRITE`·
> `E2E_QUEUE_SENSOR_BARRIER`·`E2E_DAGSTER_BASIC_AUTH_FILE`이 빠졌다. runtime journal은
> `{schedule,targets,poi}.json`이다 — `targets.json`은 read-auth의 dataset_projection
> invalidation 시나리오가 만드는 POI target 하나의 소유·복원 journal이다. 아래 §2.4, §4의
> KMA·sensor 서술은 이 날짜 이전 기록이다.

> **2026-10-02 — 기준 5 복원(`ops-c7-update-request-write`).** KMA와 함께 사라졌던 "exact-scope
> request → queue sensor → worker run" 경로를 upstream 호출이 0인 dataset 하나로 되살렸다:
> `python-krairport-api` / `krairport_airports`, operation `feature_place_krairport_airports_job`,
> scope `provider_dataset` × `dataset_wide`(그 dataset이 선언한 유일한 scope라 membership이 정확히
> 한 행이다 — migration 없음). 흐름은 §1 5번, journal은 `requests.json`, 필요한 env는 §3.1이다.
>
> - **실제 prod 쓰기다.** worker가 krairport 번들 공항(2026-10 기준 활성 15곳)을 place feature로
>   적재한다. 같은 번들이면 같은 feature로 수렴하는 idempotent upsert(authoritative snapshot)이고,
>   주소는 kor-travel-geo reverse geocode(내부 서비스)로 채운다. data.go.kr 등 upstream 쿼터는 쓰지
>   않는다. prod `feature.features`가 비어 있으면 첫 실행은 공항 feature를 **새로 만든다**.
> - Dagster에는 **읽기 전용** GraphQL만 보낸다(worker job 정의, queue sensor 상태, run identity·
>   status). sensor를 멈추거나 켜지 않는다 — run이 sensor가 띄운 것이라는 사실은 run의
>   `dagster/sensor_name` tag가 증명한다. sensor가 RUNNING이 아니면 request를 만들지 않고 멈춘다.
> - 같은 membership에 다른 활성 request가 있으면 API가 `409 ACTIVE_SCOPE_CONFLICT`로 거절한다.
>   spec은 먼저 그 dataset의 활성 실행 0을 확인하고, 그래도 409면 남의 실행을 건드리지 않고 멈춘다
>   (journal `create_rejected`). 활성 실행이 끝난 뒤 다시 돌린다.
> - 공유 plane gateway의 Basic Auth 파일(`E2E_DAGSTER_BASIC_AUTH_FILE`)을 다시 받는다 —
>   `scripts/n150/README.md`.

이 문서는 `T-ADM-C7`의 n150 파괴적 live UI E2E를 실행하는 유일한 운영 순서를
정의한다. 실제 host, URL, 계정, 비밀번호, token, hash는 gitignore된
`docs/deploy-runbook.local.md`와 `docs/prod-access.local.md`에만 둔다.

## 1. 완료로 인정하는 경계

C7은 다음 조건을 모두 만족해야 완료다.

1. Manager의 rebuildable transaction이 v5 `pinned-runtime-generation-v5.json`과 그 pinset의
   v7 `pinned-runtime-rebuild-v7-<pinset>.json`을 남겼고, active generation의 일곱 image
   (Map API·UI·Dagster web·Dagster daemon, PinVi API·web·dagster)가 실제 일곱 runtime
   container image와 각각 일치한다. journal은 phase `committed`이고 candidate가 active
   generation과 전체 동등해야 한다 — 그래야 이 세대가 파괴적 rebuild를 완주했다는 것이
   증명된다.
2. host runner/helper/attestation 검증 모듈/상태 감사기는 exact commit의 root-owned Git archive snapshot으로
   고정되고, Map API·UI·Dagster web·Dagster daemon과 PinVi API·web·dagster **일곱**의
   image/command/environment hash가 root-owned attestation과 일치한다.
3. Map DB의 Alembic current가 image의 유일한 head와 같고 `alembic check`가 통과한다.
4. Playwright는 host Chromium이 아니라
   `mcr.microsoft.com/playwright:v1.60.0-noble@sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948`
   기반의 C7 executor image에서 실행한다. executor label의 Git commit도 실행 checkout과
   같아야 한다.
5. (2026-10-02 복원, krairport) Map code location에 `feature_update_request_worker` job이 정확히
   하나 있고 `feature_update_request_queue_sensor`가 RUNNING이다. spec이 만든 request는 생성
   응답에서 `queued`·Dagster run 없음이고, queue sensor가 집은 뒤 받은 run은 `jobName`이 worker,
   `dagster/code_location`이 Map, `dagster/sensor_name`이 queue sensor, request id·generation·scope
   type tag가 그 request와 같다. request는 API에서 `done`, run은 Dagster에서 `SUCCESS`이고, 대상
   dataset에 남은 활성 실행이 없으며 최신 실행이 그 request다. 이 증거를 `requests.json`이
   `restored`로 남기고 러너가 키 집합까지 검증한 뒤 UI session으로 request를 다시 읽는다.
6. schedule·C7 target(`targets.json`)·POI 상태가 원래 값으로 정확히 복구되고, redacted 결과와
   복구 증거가 root-owned evidence 디렉터리에 보존된다. 기준 5의 쓰기는 되돌릴 대상이 아니다
   (idempotent upsert) — "복구"는 소유 request가 terminal이라는 뜻이다.

단순 HTTP 200, Playwright pass 수, container `running`만으로는 완료 처리하지 않는다.

## 2. 실행 전 순서

### 2.1 C6c와 DB 전환

1. Map API·Dagster writer를 maintenance fence로 막고 동일 배포 mutation window를
   독점한다.
2. audit-only DB backup artifact와 기존 env/compose bytes·mode·owner, 모든 대상
   container image/command/environment hash를 기록한다. 이 artifact는 restore/PITR 입력이 아니다.
3. 배포할 clean commit에서 Map API image를 먼저 만든다.
   `KOR_TRAVEL_MAP_GIT_COMMIT=$(git rev-parse HEAD)`를 build arg로 전달해 API·UI·Dagster
   image의 `org.opencontainers.image.revision`을 같은 commit으로 고정한다.
4. **[보존 이력 · 실행 금지]** 당시에는 image migration-only path를 실행했다. 현재 `300`
   deployment에는 이 legacy command를 사용하지 않으며, Manager controlled fresh/handoff와
   final permit path만 허용한다.
5. `current == unique heads`와 `alembic check`를 확인한다.
6. `start_unpaired_import_job(kind="c6c_cancel_probe", trigger_kind="system")` 정식
   repository 경로로 owned cancel fixture를 만들고 transaction을 commit한다. raw SQL
   fixture는 금지한다.
7. UI credential을 UI-only exact-image recreate로 먼저 회전하고 새 로그인→보호 화면→
   로그아웃→재차단 및 구 credential 401을 확인한다. 실패하면 저장한 env/config/image로
   UI만 정확히 복구한다.
8. Manager의 `ktdctl pinvi-pair rebuild-pinned --confirm`을 실행해 v5
   `pinned-runtime-generation-v5.json`과 그 pinset의 v7
   `pinned-runtime-rebuild-v7-<pinset>.json`을 만든다.

   > **2026-08-20 — v4 `pinvi-pair capture`는 이 경로에서 퇴역했다(ADR-094).** C7 runner가
   > 읽는 attested input은 v5 manifest + v7 journal 둘이며, v4 compatible-pair manifest를
   > 억지로 넣어 통과하는 경로는 없다(`manifest shape`로 fail-close된다).
   >
   > **파괴형이다.** Map application·Map Dagster·PinVi 세 DB를 재생성하고 일곱 runtime을
   > 재기동한다. 실행 시점·선행조건은 백로그 `T-VN-FINAL-REBUILD`가 소유한다.
   >
   > 두 문서는 `require_rebuildable_mode` 아래에서만 만들어지고(ktdm
   > `KTDM_DEPLOYMENT_ENVIRONMENT=rehearsal` + `KTDM_DEPLOYMENT_LIFECYCLE=rebuildable`),
   > state root는 Manager owner 소유 `0700`이다. runner는 root 소유 `0600`을 요구하므로
   > **내용을 바꾸지 않은 root 소유 사본**을 만들어 §2.3의 두 env로 넘긴다.
   >
   > 세대가 바뀌면 `active_generation`의 일곱 image ID·세 schema head·`pinset_sha256`이
   > 함께 바뀌므로 §2.3 attestation을 재생성해야 한다.

   manifestless
   capture가 mutation 뒤 실패하면 임의 rollback 성공을 꾸미지 않고 Map 네
   runtime과 PinVi API를 중지한 채 operator-required로 남긴다.

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
정확한 version 4여야 한다. 이 version은 host attestation document 계약이며 Manager
pinned runtime manifest version과 다르다. Manager canonical manifest는 정확한 version 5이고
`{version, active_generation}` 두 키만 가진다. `active_generation`은 일곱 image ID
(`map_api_image_id`, `map_ui_image_id`, `map_dagster_image_id`,
`map_dagster_daemon_image_id`, `pinvi_api_image_id`, `pinvi_web_image_id`,
`pinvi_dagster_image_id`), `map_source_revision`, `pinvi_source_revision`, 세 schema head
(`map_application_head`, `map_dagster_head`, `pinvi_head`), `pinset_sha256`, `recorded_at`을
**정확히** 가진다. rebuild journal은 version 7이고 `{version, transaction_id, phase,
candidate, environment_sha256, compose_sha256, resolved_compose_sha256, created_at,
cancel_probe}`를 정확히 가진다. v4 compatible-pair manifest나 누락·추가 필드는 호환 변환
없이 거부한다 — v4를 억지로 넣어 통과하는 경로는 두지 않는다.

두 문서 bytes를 root-owned `0600` snapshot으로 만들고, runner에는 그 absolute path 두 개를
전달한다. 원본과 snapshot SHA-256이 다르면 실행하지 않는다. attestation에는 다음 비민감
증거만 넣는다.

- machine-id·hostname·공개 UI/API WebSocket/Dagster GraphQL origin의 SHA-256
- compose project 이름의 SHA-256
- clean repository commit
- Map·PinVi source commit과 각 immutable image의 `org.opencontainers.image.revision`
- root-owned runner/helper/attestation 검증 모듈/상태 감사기 상대경로 4개의 SHA-256(`orchestrator_files`)
- v5 manifest bytes와 v7 journal bytes의 SHA-256, generation의 `pinset_sha256`,
  세 schema head(generation 값과 exact 일치해야 한다)
- 일곱 runtime(Map API·UI·Dagster web·Dagster daemon, PinVi API·web·dagster)별 image ID, canonical
  `{Path,Args,Entrypoint,Cmd}` command SHA-256,
  정렬된 environment 전체의 SHA-256
- C7 Playwright executor image ID와 고정 base image reference

environment hash는 값 자체를 출력하지 않고 container inspect 결과를 정렬한 canonical
JSON bytes에서 계산한다. attestation 작성 명령과 실제 값은 local runbook에만 둔다.
runner는 위 **일곱** runtime role의 image ID를 host attestation과 비교한 뒤, 일곱 전부를
manifest `active_generation`의 일곱 image ID와 각각 비교한다. Map 네 image의 OCI revision은
`active_generation.map_source_revision`, PinVi 세 image는 `pinvi_source_revision`이어야 한다.
세 schema head와 `pinset_sha256`도 attestation과 generation이 exact 일치해야 한다.

### 2.4 KMA 인수 scope (`external_system:c7-e2e`) — 2026-10-01 퇴역

> 아래는 퇴역한 KMA 3-spec의 기록이다. 남은 C7 spec은 `c7-e2e` scope로 갱신을 걸지 않는다.
> 앞 run의 `c7-e2e` target이 남아 있으면 아래 회수 절차로 비우는 것만 여전히 유효하다.

KMA live 3종(`ops-c7-kma-{active,cap,empty}-write`)은 **고정** external system
`c7-e2e`에 cache target을 만들고 `external_system:c7-e2e` scope로 갱신을 건다. run마다
이름을 새로 만들 수 없다 — ADR-088 이후 제출 가능한 `sync_scope`의 정본은
`provider_dataset_operation_scopes` 선언이고(`0224_c7_external_system_scope`가 선언한다),
선언되지 않은 값은 preview/create가 **422**다. run 격리는 `target_key`가 맡는다.

`target_grids`를 쓰지 않는 이유: 그 scope는 "모든 활성 cache target + extra points"라
인수가 운영 대상에 provider I/O를 내고 `membership_fingerprint`가 비결정적이 되며,
`provider_sync_state`의 정본 cursor 행을 스케줄 job과 공유한다.

**사전조건(fail-closed).** 세 spec은 시작 직후 `assertC7ScopeIsClean`으로 **세 축**을 본다.
하나라도 걸리면 앞 run의 잔존물이 이 run에 섞이므로 즉시 멈춘다.

| 축 | 막는 것 | 걸렸을 때 |
|---|---|---|
| `c7-e2e`의 활성 target 0건 | 남은 target이 `membership_fingerprint`를 오염 | 아래 회수 절차 |
| 비terminal(queued/running) 요청 0건 | 같은 scope의 생성이 409(active scope conflict) | 파이프라인 화면에서 취소 |
| 현재 base의 sync-state cursor 없음 | 같은 base·같은 membership이면 실행기가 `skipped=true`로 접어 "첫 요청은 실행된다"가 깨짐 | **다음 base rollover(KST 매시 40분) 뒤 재실행** |

셋째 축은 고정 이름이 되면서 새로 생긴 노출이다 — cleanup은 target만 지우고 sync-state 행은
남기므로, **실패 직후 같은 base 안에서 재시도하면** 여기서 선다. 기다리는 것이 맞다.

**직렬 실행이 필수다.** 세 spec이 같은 external system을 공유하므로 병렬로 돌면 서로의 target과
요청을 오염시킨다. runner(`scripts/run-c7-prod-live-e2e.sh`)가 spec별 별도 컨테이너 순차 루프 +
`--workers=1`(+`E2E_LIVE_WORKERS=1`)로 보장한다. **`npm run e2e:live -- e2e/live/`로 직접 돌리지
마라** — `playwright.live.config.ts`의 기본은 `fullyParallel: true` / `workers: 4`다.

**잔존물 회수.** cleanup은 요청이 전부 terminal이고 scope/target 탐색이 완결됐을 때만
target을 지우고, 아니면 `preservedForManualCleanup: true`로 **의도적으로 보존**한다. cap
시나리오는 ~301건을 만들므로 중간 실패 시 그만큼 남을 수 있다. §4 복구를 마친 뒤 다음 run
전에 비운다(admin 자격 필요, prod 쓰기 — 운영자 판단으로 실행):

```bash
# 남은 target 확인 (읽기)
curl -s "$MAP_API/v1/admin/poi-cache-targets?external_system=c7-e2e&include_deleted=false&page_size=500"   -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.data.items | length'
# 개별 DELETE — target_id마다 (전용 일괄 삭제 표면은 없다)
```

비terminal 요청이 남았으면 admin 파이프라인 화면에서 취소한 뒤 다시 확인한다.

## 3. runner 실행

runner를 실행하기 전 Map exact commit은 C7P v5/v7 reader와 해당 generation의 모든 필수
producer/consumer 변경이 main에 함께 병합된 최종 commit이어야 한다. producer 또는
consumer 한쪽만 main에 병합된 중간 commit은 배포·capture·live 실행 대상이 아니다.

`/usr/local/lib/kor-travel-map/c7-runner/<exact-commit>/scripts/run-c7-prod-live-e2e.sh`의
root-owned snapshot만 root로 실행한다. 모든 URL·credential·service 이름·
origin hash·Git commit·manifest path·executor image ID와 destructive opt-in은 명시 env로
전달한다. runner가 요구하는 env 목록은 `require_env` 구간이 정본이며 기본 credential과
기본 production URL은 없다.

runner는 아래 순서를 지킨다.

1. env/command/root-owned orchestrator snapshot/host/runtime/pinned-generation/journal/Alembic을 read-only 검증하고 UI login을
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
   비밀값이 없는 root runtime attestation과 pinned generation·rebuild journal snapshot은
   함께 복제하고 manifest hash로 결박한다(evidence 안 파일명은
   `runtime-attestation.json`, `pinned-runtime-generation.json`,
   `pinned-runtime-rebuild.json`).
6. 원격 상태를 다시 읽어 exact restoration을 검증하고 evidence를 fsync한 뒤에만
   journal과 `BLOCKED.json`을 제거한다.

### 3.1 C7 env 키 (`/root/.d2-live.env`)

러너 env의 정본은 `scripts/run-c7-prod-live-e2e.sh`의 `validate_environment`다. 그중 손으로 두는
키(repin이 쓰지 않는다)와 기준 5가 새로 요구하는 키:

| 키 | 값 | 비고 |
|---|---|---|
| `E2E_C7_SCHEDULE` | `feature_place_krairport_airports_monthly_schedule` | schedule-write allowlist |
| `E2E_C7_UPDATE_REQUEST_WRITE` | `1` | **2026-10-02 신규.** 기준 5의 실제 prod 쓰기 opt-in |
| `E2E_C7_UPDATE_REQUEST_OPERATION` | `feature_place_krairport_airports_job` | **2026-10-02 신규.** 러너 allowlist와 정확히 같아야 한다 |
| `E2E_DAGSTER_URL` · `E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256` | 공개 GraphQL URL과 그 sha256 | `scripts/n150/README.md` |
| `E2E_DAGSTER_BASIC_AUTH_FILE` | `/root/.d2-dagster-basic-auth` | **2026-10-02 다시 받음.** 공유 plane gateway일 때만, root `0600` `user:password` 한 줄 |
| `E2E_LIVE_ALLOW_PROD` · `E2E_ADMIN_WRITE` · `E2E_C7_READ_AUTH_WRITE` · `E2E_DAGSTER_WRITE` | `1` | 기존 opt-in |

`E2E_C7_REQUEST_STATE_FILE`은 러너가 runtime 디렉터리 안 `journals/requests.json`으로 정해
executor에 넘긴다 — env 파일에 두지 않는다.

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
2. `runtime.*/journals/{schedule,targets,poi,requests}.json`을 root만 읽을 수 있는 recovery
   evidence로 복제하고 SHA-256을 기록한다. 2026-10-01 이전 runner가 남긴
   `{sensor,kma}.json`과 root 직하 journal도 있으면 함께 보존한다(감사기는 계속 센다).
3. schedule은 journal의 최초 state와 admin schedule API를 비교해 복구한다. 옛 `sensor.json`이
   남았으면 그 최초 selector/state와 실제 Dagster GraphQL을 비교한다. 소유하지 않은
   concurrent state면 덮어쓰지 않는다.
4. C7 target(`targets.json`)과 POI target은 journal의 exact 자연키/UUID/ETag/body를 사용한다.
   옛 `kma.json`의 request는 KMA operation이 거절되므로 새로 실행될 수 없지만, 비terminal로
   남았으면 admin 파이프라인 화면에서 취소한다. `412`, UUID drift, 응답 유실은 자동 삭제하지 않는다.
   `requests.json`(기준 5)은 되돌릴 쓰기가 없다 — `request_id`가 있으면 그 request가 terminal인지
   파이프라인 화면에서 확인하고, queued로 남았으면 취소한다(spec의 실패 정리가 이미 시도한다).
   `request_id`가 없고 phase가 `create_intent`·`create_response_lost`면 같은 `idempotency_key`의
   request가 생겼을 수 있으니 krairport dataset의 최신 실행 reason에 journal `run_id`가 있는지 본다.
   `create_rejected`는 남의 활성 request 때문에 아무것도 만들지 않은 것이다.
5. 공개 UI session으로 schedule/target/POI의 최종 read-only equality와 owned scope 0건을
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

evidence manifest의 Git commit, service image ID, pinned generation·rebuild journal hash, Alembic head,
spec별 결과, 복구 검증 hash를 `docs/journal.md`와 issue 코멘트에 비밀 없이 요약한다.
그 증거가 모두 있을 때만 `T-ADM-C6c`, `T-ADM-C7`과 #684/#694/#712/#719를 닫는다.
