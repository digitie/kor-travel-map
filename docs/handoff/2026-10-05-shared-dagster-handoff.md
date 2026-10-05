# 인계 — 2026-10-05 (공용 Dagster 완주 이후)

> 이 문서는 Claude Code 세션이 끝나고 다음 에이전트(Codex 등)가 이어받도록 정리한 인계본이다.
> 상태·TODO·운영 절차·실제로 밟은 함정을 담았다. 운영 값(호스트명·IP·비밀)은 넣지 않았다(#508 redaction).
> 이 문서의 n150 보조 스크립트는 `docs/handoff/n150-scripts/`에 있다. n150에는 같은 이름의 사본이
> `~digitie/`(= `~/`)에 이미 있으며, 그 사본에는 실제 호스트가 들어 있다.

## 0. 원칙(소유자 지시, 계속 유효)

- **언어:** 사용자에게는 한국어로 보고한다. **비밀값은 출력하지 않는다**(DSN·비밀번호·토큰).
- **머지:** main에 직접 push하지 않는다. feature branch → PR → **CI 전량 green** → 머지한다.
  PR은 머지 직전에 연다. 문서만 바뀐 PR은 CI를 기다리지 않고 바로 머지해도 된다.
- **적대 리뷰:** 머지되는 모든 변경에 붙인다. HIGH·MED가 0이 될 때까지 고친다.
- **테스트:** n150에서 돌린다(CI-parity). 로컬 PC는 디스크와 메모리를 보호한다.
- **범위:** "다른 서비스 신경쓰지말고 진행", "롤백 신경쓰지마"(롤백 경로는 만들지 않는다). Map은 transport의
  consumer이므로 계약 핀·vendored OpenAPI·repin은 두지 않는다. 필요하면 transport API를 Map에 맞게 고친다.
- **사전 점검:** n150에서 변경 작업을 시작하기 전에 반드시 사전 점검을 돌린다(§4.1). FAIL이면 시작하지 않는다
  (2026-10-04 지시: "실패가 잦은데 미리 최대한 사전에 체크해서 진행해").

## 1. 현재 prod 상태 (2026-10-05)

| 대상 | 버전 | 비고 |
|---|---|---|
| Map | `13f87577` (#1297 포함, 2026-10-05 04:05Z 회전) | D1·D2 GREEN(t71a), deploy-status `committed` |
| PinVi | `80c92b6c` | Map과 pinned pair |
| Manager | `e2a1a5b4` (#462) | 설치·rebind·`pin verify` 0, instance digest `ff189facb6d6cf1a` |
| transport | `c6105233` (#64·#65·#66·#68·#69) | 공용 plane 합류, admin 게이트, code-server start_period 600s, crash 로그·DB 오류 redaction, Dagster op 실패를 redact된 Failure로 공용 event log에 기록 |
| weather | `2e53dc72` (#71·#73·#74·#75) | 특보 skip-locked, nowcast 결측 센티넬, skip 경보, python-kma-api `12e7f1f1` |

- **공용 Dagster plane:** weather·pinvi·geo·map·transport 5개 tenant가 모두 하나의 storage DB `dagster_shared`
  (공용 webserver·daemon·gateway)에서 돈다.
- **code-server:** 5개 모두 `dagster code-server start`다. reload가 정의를 다시 읽으므로 C7 schedule-write가 통과한다.
  Manager compose `x-dagster-code-server-probe`의 liveness probe와 orphan run reaper가 붙어 있다.
  transport의 compose는 이 probe를 **글자 그대로 복사**해 쓰고, 컷오버 스크립트가 일치 여부를 검사한다.
  Manager의 probe를 바꾸면 transport 쪽도 같은 PR 쌍으로 맞춘다.
- **C7:** Map `bafec797`에서 GREEN(공용 plane, schedule-write 포함).
- **옛 프로젝트별 Dagster 메타DB 5개**(`kor_travel_{geo,map,transport,weather}_dagster`, `pinvi_dagster`):
  - 최종 dump를 n150 `/root/dagster-stage4-20261003/`에 두었다(SHA256SUMS·toc 포함).
  - 5개 모두 `ALLOW_CONNECTIONS false`다.
  - Manager #459가 옛 DB 의존(storage migrate, db-init grant, C6c, 백업 role)을 모두 걷어냈다.
  - crontab의 옛 백업 줄(`geo_dagster`, `transport_dagster`)도 지웠다.

### 이번 묶음에서 머지된 PR
- **Manager:**
  - #456: reloadable code-server, probe, reaper
  - #457: transport 공용 plane 합류
  - #458: probe LOW(monotonic, 부팅 직후 hang kill, 고유 temp)
  - #459: 옛 메타DB 의존 제거
  - #460: healthcheck `start_period`. code-server는 600s, map-api·map-ui·pinvi-api는 300s, `start_interval`은 5s
  - #461: C6c smoke cold-start 재시도
- **transport:**
  - #64: 공용 plane 합류, dagster 1.13.24로 고정
  - #65: probe 재복사
  - #66: `/v1/transport/admin/*` 게이트, collector 원문 숨김
- **weather:** #71. KMA 특보가 잠긴 지점을 건너뛰고, 굶는 지점이 있거나 skip 비율이 10%를 넘고 5곳 이상이면 run을 partial로 끝낸다.
- **Map:**
  - #1294: Map→transport API 전환
  - #1296: transport 소비 경로 LOW
  - #1297: D2 fixture restored 감사 — 2026-10-05 04:05Z 회전(t71a)으로 배포했다

## 2. 진행 중이던 작업 — 완료(2026-10-04 23:00Z)

- **weather `kma_ultra_short_nowcast_job` 수정과 배포가 끝났다.** weather PR #73(`2575071a`)을 머지하고 배포했다.
  배포 뒤 첫 정시 run(23:00Z)이 SUCCESS로 끝났다. 이 job은 2026-09-30 이후 처음 성공했다.
  - **원인:** 오프라인 관측소의 KMA 결측 센티넬(-998, -998.9, -999)이 검증에 걸려 run 전체가 실패했다.
  - **수정:**
    - |값| ≥ 900인 값, 빈 값, 공백 값은 `missing`으로 보고 그 지표만 건너뛴다. NaN과 Inf는 `invalid`로 본다.
    - 다음 경우 run을 `partial`로 끝낸다(경보 대상).
      - missing이 16건 이상이면서 10%를 넘을 때. prod에서는 10% 쪽이 결정하고, 관측소 약 17~34곳이 빠지는 규모다.
      - invalid가 1건이라도 있을 때.
    - 받아들인 값이 0건이면 `failed`로 끝낸다.
    - 메트릭 `ktw_sync_values_skipped_total`을 추가했다.
  - **경보 규칙 완료(weather PR #74 `4e9c5b96`, 2026-10-05 00:33Z 배포).** `KorTravelWeatherValuesInvalid`(missing이 아닌
    skip이 1건이라도 있으면 즉시)와 `KorTravelWeatherValuesMissingHigh`(3h30m 창에서 60 초과가 1h 지속)를 추가했다.
    양쪽 차분은 10분 `max_over_time`으로 평활해 scrape 공백이나 카운터 dip에 오발하지 않는다.
    skip 카운터는 worker를 import할 때 0으로 미리 만든다.
    alertmanager가 없으므로 firing은 Prometheus 화면에만 보인다.
  - **후속(LOW):**
    - 이미 저장된 센티넬 값을 조회해야 한다. 범위를 좁혀서 볼 것.
    - python-kma-api의 `float_or_none`이 |v| ≥ 900일 때 None을 돌려주도록 고친다.
- 참고: weather main에는 Codex의 #72(`8ed94e7`)가 들어갔다. fact/raw 게시를 작은 batch로 나누는 변경, 특보 메모리 변경, admin Dagster UI가 포함돼 있다.
  §3-2의 청크 축소 권고 일부가 이미 반영된 셈이다.

## 3. TODO (우선순위순)

1. **weather nowcast 수정과 배포:** §2.
2. **weather 다른 job의 lock timeout 정책(소유자 결정 필요).**
   - 대상: openweathermap·open_meteo·weatherapi(current/forecast), airkorea_realtime_measurement, kma_ultra_short_forecast.
     지점 lock timeout 한 번에 run 전체가 실패한다.
   - 지점 skip을 도입하면 "적재한다"는 약속이 바뀌므로 그 전에 소유자에게 묻는다.
   - 권고: `chunked_publish.py`의 `PUBLISH_CHUNK_VALUES`를 5000에서 1000~2000으로 낮춰 lock 보유 시간을 줄인다.
     특보 스케줄을 `:05`에서 `:40`으로 옮기는 안도 있다.
3. ~~Map #1297 배포~~: 2026-10-05 04:05Z에 완료했다(t71a, D1·D2 GREEN). python-kma-api 결측 helper(#31)를 추가했고, weather는 이를 사용한다(#75).
4. **소유자 확인 필요(저장소 밖):** OPNsense HAProxy의 Map UI backend `timeout server`를 30초에서 약 120초로 올려야 한다.
   - 2026-10-04 D2의 admin create가 약 30초 만에 edge에서 끊긴 것으로 추정한다.
   - 그 create가 DB에서 30초나 걸린 원인도 별도로 조사해야 한다. 당시 feature insert가 +12초, override가 +29초였고 load는 약 9였다.
5. **2026-10-19 무렵:** weather DEFAULT 파티션(약 38GB) purge. weather 저장소의 purge_default 스크립트를 dry-run한 뒤 `--execute`한다.
6. **2026-11-02 무렵:** 옛 메타DB 5개를 `DROP DATABASE`한다(dump는 위 경로). 그 전에 접속 0건을 확인한다.
7. **LOW 후속:** 대부분 끝났다(2026-10-05).
   - Manager #462에서 끝낸 것:
     - Map locator 경고 logger를 공용 `dagster.yaml`에 추가했다.
     - C6c smoke의 Map 요청 시간을 누적 180s로 묶었다. 각 호출의 첫 시도는 항상 10s를 다 쓴다.
     - `IncompleteRead`·`HTTPException`을 감싼다.
   - transport #68에서 끝낸 것: code-server start_period 600s, crash 로그 filter, 저장되는 오류의 sanitize.
   - transport #69(2026-10-05 배포): Dagster op 실패를 redact된 `Failure`로 바꿨다. frame 위치와 예외 chain 타입은 metadata에 남기고, 전체 traceback은 stderr에 redact해서 남긴다. 그래서 공용 event log에는 원문이 기록되지 않는다.
     **배포 전에 이미 `dagster_shared`에 남은 원문 실패 레코드를 정리할지는 소유자가 결정한다.**
   - Map #1304: standalone `docker-compose.yml`도 `code-server start`와 load-aware probe를 쓴다. 로컬 전용이라 배포하지 않는다.
     후속: entrypoint에서 `api grpc` 허용을 제거한다(별도 변경).
   - 큐 경로 503은 재큐잉하지 않기로 결정했다(문서화됨).
8. **n150 디스크:** 2026-10-05에 `/`가 91%까지 찼다.
   - build cache prune(48h·24h)과 dangling image prune을 했다. 다른 세션의 빌드로 다시 92%까지 올랐다가, 2026-10-05에 89%로 낮췄다.
   - 쓰지 않는 태그 이미지가 약 74GB 남아 있다. 퇴역 보관 이미지(옛 postgis 등)가 섞여 있을 수 있으므로 지우기 전에 소유자에게 확인한다.
   - preflight는 90%를 넘으면 FAIL을 낸다.

## 4. n150 운영 절차

### 4.1 사전 점검 (필수)
```bash
sudo bash ~/preflight.sh <rebuild|chain|deploy-transport|deploy-weather|deploy> [--allow-runs]
```
`PREFLIGHT_PASS`일 때만 시작한다. 원본은 `docs/handoff/n150-scripts/preflight.sh`다. 저장소 사본은 공개 확인 대상을
`MAP_UI_HOST`·`MAP_API_HOST`·`PINVI_API_HOST` 환경변수로 받는다.

점검 항목:
- **자원:** load ≤ 8/9, MemAvailable ≥ 4G, `/tmp`(tmpfs = RAM) ≤ 50%, `/` ≤ 90%, iowait
- **겹치는 작업:** rebuild·chain·deploy unit, 빌드, pytest
- **공용 plane:** 관련 run(STARTED)
- **Manager:** pin verify, deploy-status가 `committed`가 아니면 경고
- **C6c leak 위험:** Manager `.env`의 `KOR_TRAVEL_CONCIERGE_REPO_DIR`, `/opt/kor-travel-concierge`
- **서비스:** unhealthy 컨테이너, 공개 엔드포인트 200, Docker Hub auth

### 4.2 접속·스크립트 실행
- 이 PC(Windows)에서는 `MSYS_NO_PATHCONV=1 wsl bash -c "ssh n150 '…'"`로 들어간다.
- **여러 줄 명령은 따옴표를 겹쳐 쓰지 말고** 스크립트 파일로 만든다. `scp`로 `n150:~/`에 올린 뒤 `sudo bash ~/x.sh`로 실행한다.
  겹친 따옴표(`\$var`, `$(…)`)는 거의 항상 깨진다.
- `/tmp`는 tmpfs(7.5G, RAM)다. 다른 세션이 남긴 잔여물로 82%까지 찬 적이 있고, 그때 업로드와 테스트가 실패하고 부하가 올랐다.
  `/tmp/ktm-lint`는 공유 체크아웃이므로 지우지 않는다.
- **공용 Postgres:** 컨테이너 `kor-travel-shared-postgres`, 컨테이너 안 127.0.0.1:11000.
  - 사용자는 `$POSTGRES_USER`, 비밀번호는 `$POSTGRES_PASSWORD_FILE`에 있다.
  - psql을 쓰려면 스크립트를 `docker cp`로 넣고 그 안에서 `PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"`로 실행한다.
- **공용 Dagster GraphQL:** n150 `http://127.0.0.1:11002/graphql`. job 상태는 `n150-scripts/dagster-job-status.py`로 본다.

### 4.3 Manager 설치
```bash
bash ~/install-mgr.sh <full-sha>
sudo /opt/kor-travel-docker-manager/backend/.venv/bin/ktdctl pin rebind-execution \
  --expected-manager-revision <sha> --reason "manager install <sha> (...)" --confirm   # 가끔 exit 1 → 재시도
sudo /opt/kor-travel-docker-manager/backend/.venv/bin/ktdctl pin verify
```
설치만으로는 컨테이너가 바뀌지 않는다. code-server의 env나 probe가 바뀌었다면 아래 방법으로 반영한다.
반영하기 **전에** 진행 중인 run이 0건인지 확인한다(재생성하면 진행 중인 run이 끊긴다).
- **map·pinvi:** pinned rebuild(§4.4)로 반영한다.
- **weather·geo:**
  `docker compose --project-directory /opt/kor-travel-docker-manager -p kor-travel-docker-manager up -d --no-deps <svc>`

### 4.4 Map·PinVi pinned pair
- **새 Map 커밋:**
  `/root/chain17.sh <MAP_SHA> "<reason>" ktdm-rebuild-<tag> d2-execbuild-<tag> d2-d2-<tag> <tag>`
  이 명령이 회전, rebuild, executor, 재핀, M01, D1, D2를 차례로 돈다.
- **같은 쌍 재검증:** `/root/chain16.sh <MAP> <PINVI> d2-execbuild-<tag> d2-d2-<tag> <tag>`
- **D1부터 다시(빌드 생략):** `/root/chain16-fromF.sh <MAP> <PINVI> unused d2-d2-<tag> <tag>`
- **tag는 재사용하지 않는다.** 마지막으로 쓴 tag는 t70a~t70f, g1004a~c다.
- **rebuild는 `~/guarded-rb.sh <tag>`로만 돌린다.** 이 스크립트는 rebuild가 실패하면 Map·PinVi 컨테이너 6개를 곧바로
  `docker start`하고, 공개 엔드포인트와 deploy-status를 출력한다.
  - **배경:** pinned rebuild는 실패하면 서비스를 멈춘 채로 끝난다. deploy-status가 `committed`가 아니면 같은 쌍이어도
    Map·PinVi를 멈추는 full 경로로 간다. 2026-10-04에 이 때문에 장애가 세 번(약 13~35분) 났다.
  - **원인과 수정:** healthcheck 창이 부하 걸린 cold start보다 짧았던 것이 원인이고, #460에서 고쳤다.
- chain16 executor 빌드의 제한 시간은 40분이다. 시간이 초과돼도 이미지 라벨이 핀과 맞으면 다음 단계로 진행한다.
- **D1:** 부하가 걸리면 `auth.setup`이 30s를 넘거나 MOIS precheck poll이 15s를 넘기는 간헐 실패가 난다. 재시도로 통과한다.
- **D2 BLOCKED:** 상태 파일은 `/var/lib/kor-travel-map/admin-feature-live-acceptance/BLOCKED.json`(v4)이다.
  - 실행 identity(이미지·커밋)가 바뀐 뒤에는 `recover`를 쓸 수 없다. runbook §6의 운영자 판정 절차를 따른다.
  - 2026-10-04 사례: 감사된 purge 경로(`feature.purge_manual_feature`)로 정리하고, 정본 `scripts/n150/adjudicate.sh`를 실행했다.
    증거: `adjudicated-20261004T110949Z`.
- **D2 키 갱신:** Map 마이그레이션 head가 바뀌면 `/root/.d2-live.env`의 `E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_ALEMBIC_REVISION`을
  손으로 고친다. 현재 값은 `404_transport_provider_identity`다.

### 4.5 transport 배포
1. 로컬 WSL에서 origin/main을 detach 체크아웃한 worktree로 들어가 `DEPLOY_STAGE_ONLY=true ./scripts/deploy-server14.sh`를
   실행한다(stage만 한다).
2. n150에서 `n150-scripts/transport-deploy-unit.sh`의 `<CANDIDATE_SHA>`와 `<sha4>`를 채워 실행한다.
   이 스크립트는 `systemd-run --no-block`으로 **TimeoutStartSec=7200** unit을 띄워 `deploy-server14-remote.sh`를 돌린다.
   빌드에 약 36분 걸리고, 그 뒤 transport run drain을 최대 30분 기다린다. 1시간 제한이었을 때 실패한 적이 있다.
3. admin UI가 바뀌었다면 `./scripts/deploy-transport-admin-server14.sh`를 돌린다. Docker Hub TLS timeout이 나면 재시도한다.
4. 배포 스크립트는 transport 이미지의 dagster 버전을 공용 호스트와 대조해, 다르면 거부한다.
   호스트 dagster를 올릴 때는 transport 고정 버전도 함께 올린다.

### 4.6 weather 배포
- **알림 규칙(`deploy/prometheus/alerts.yml`)이 바뀌었다면 배포 뒤 반드시**
  `docker kill --signal=SIGHUP kor-travel-weather-prometheus`를 보낸다. 배포 스크립트는 SIGHUP을 보내지 않는다.
  Manager의 weather `ensure`는 보낸다. 그런 다음 14104 `/api/v1/rules`에서 새 규칙이 올라왔는지 확인한다.
- systemd unit은 **`--uid=digitie`**로 띄운다. root로 실행하면 weather 체크아웃에서 git이 dubious ownership으로 거부한다.
- ghcr.io나 Docker Hub의 TLS timeout은 일시적인 경우가 대부분이니 재시도한다. preflight가 둘 다 WARN으로 미리 알려 준다.
`n150-scripts/weather-deploy.sh <merge-sha>`를 실행한다.
- 하는 일: 호스트의 weather 체크아웃을 ff-only로 올린다. Manager compose로 weather api와 code-server를 build·migrate·up한다.
  마지막에 orphan run을 정리한다.
- 바깥 ssh 래퍼는 자주 timeout으로 끊긴다. 결과는 `/root/weather-*/`의 `build.out`·`migrate.out`·`up.out`과 컨테이너 상태로 확인한다.
- weather는 항상 run이 떠 있다. code-server를 재생성하면 진행 중인 수집 한 주기가 끊긴다(허용됨).

### 4.7 C6c env_file leak 함정
- 다른 세션이 Manager `.env`에 `KOR_TRAVEL_CONCIERGE_REPO_DIR`를 넣거나 `/opt/kor-travel-concierge` symlink를 만든 적이 두 번 있다.
- 그러면 compose의 concierge env_file이 실제 concierge `.env`를 읽는다. 그 파일은 Manager와 비밀값을 공유하므로 C6c 검사가
  **모든 pinned rebuild를 거부한다**.
- 현재는 주석 처리했다(소유자 승인). 사전 점검이 이 상태를 확인한다.

## 5. 참고
- 상세 진행 로그와 사고 기록(2026-10-03 22:51Z와 2026-10-04 01:45Z의 Map·PinVi 다운)의 정본은
  [`docs/journal.md`](../journal.md), 그리고 각 저장소 PR 본문이다.
- Manager 쪽 공용 plane 정본: Manager 저장소 `docs/platform-topology.md` §7(4단계 절차·안전 순서 포함).
