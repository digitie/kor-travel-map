# Docker 독립 app runbook

본 문서는 ADR-045/047/056 기준 kor-travel-map 독립 프로그램을 로컬에서 빌드·기동·스모크하는
절차다. 고정 포트는 API `12701`, admin UI `12705`, Dagster `12702`이다.
PC 개발 환경에서 host `5432`는 `kor-travel-docker-manager`가 소유한
공유 PostgreSQL/PostGIS 서버 인스턴스다. RustFS S3 API는
`12101`, console은 `12105`다. 공유 PostGIS만 쓰고 RustFS는 local로 띄우려면
`KOR_TRAVEL_MAP_DB_EXTERNAL=true`를 사용한다. 공유 PostGIS/RustFS를 모두 쓰면
`KOR_TRAVEL_MAP_INFRA_EXTERNAL=true`로 local infra 서비스를 띄우지 않는다.

## 0. 실행 셸

이 runbook의 `npm run docker:build`, `npm run docker:buildx`, `npm run docker:up`,
`npm run docker:backup`, `npm run docker:restore`, `npm run admin:stack`,
`npm run ports:stop`은 루트
`package.json`에서
`bash scripts/*.sh`를 실행한다.
`scripts/*.sh`는 Bash 전용 문법(`source`, array, `BASH_SOURCE`)을 사용하므로
PowerShell에서 `.sh` 파일을 직접 실행하지 않는다.

권장 순서:

1. WSL 셸에서 실행한다.
2. Windows에서 실행해야 한다면 Git Bash를 사용하고, `bash`, `docker`, `npm`이 같은
   셸에서 보이는지 확인한다.
3. PowerShell에서는 다음처럼 WSL에 위임한다.

```powershell
wsl bash -lc "cd /mnt/f/dev/kor-travel-map-codex && npm run docker:up"
```

## 1. 환경변수

provider 실행 키는 루트 `.env`, API auth/route/backup 설정은 API 전용 `.env`에
분리한다. 두 파일 모두 git에 커밋하지 않는다. API 전용 파일은 Compose 기동의 필수
입력이라 없으면 API를 인증 기본값으로 시작하지 않고 즉시 실패한다.

```bash
cp .env.example .env
chmod 600 .env
cp packages/kor-travel-map-api/.env.example packages/kor-travel-map-api/.env
chmod 600 packages/kor-travel-map-api/.env
```

Compose frontend는 root `.env`에서 UI login/session/BFF 변수만 명시적으로 전달하며 root
파일 전체를 `env_file`로 읽지 않는다. `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET`은 BFF 공유
secret의 단일 정본이며 API와 frontend server가 같은 이름을 직접 읽는다. 이 값과 password
hash, session secret이 없으면 Compose 해석 단계에서
실패한다.

`scripts/load-env.sh`와 `docker-compose.yml`은 기존 provider repo에서 쓰던 키 이름을
Dagster/provider 실행용 환경변수로 매핑한다. REST API backend는 provider credential을
받지 않으며 dataset preview는 fixture-only다. Compose의 API service도 root `.env`를
`env_file`로 읽지 않아 provider secret을 process environment에 보유하지 않는다.
기존 설치를 갱신할 때는 BFF 공유 secret만 root `.env`에 두고 나머지
`KOR_TRAVEL_MAP_API_*` auth/route/backup 값을 API 전용 파일로 옮긴 다음 기동한다.
CORS/metrics도 API 전용 파일이 정본이며 root
`.env.example`과 `scripts/load-env.sh`는 이 runtime 설정을 더 이상 주입하지 않는다.
`KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED`의 standalone 기본값은 `false`다. Compose opt-in은
api service의 `environment` interpolation 입력인 shell 또는 root project `.env`에서만 `true`를
명시한다. package API `.env`(`env_file`)의 같은 값은 service `environment`보다 우선하지 않는다.
직접 API process를 기동할 때만 package API env가 입력이다. 승인된 Docker Manager production은
canonical service의 literal `true`를 사용한다. 설정 enablement와 각 요청의
`AdminProxyContext.actor` 감사는 서로 대체하지 않는다.

| 입력 키 예                                        | 실행 시 export                                                                                              |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `DATA_GO_KR_SERVICE_KEY`, `KMA_API_KEY`           | `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY`                                                                     |
| `OPINET_API_KEY`                                  | `KOR_TRAVEL_MAP_OPINET_API_KEY`                                                                             |
| `KEX_GO_API_KEY`, `KREX_API_KEY`                  | `KOR_TRAVEL_MAP_KREX_EX_API_KEY`, `KOR_TRAVEL_MAP_KREX_GO_API_KEY`                                          |
| `KOR_TRAVEL_GEO_VWORLD_API_KEY`, `VWORLD_API_KEY` | `NEXT_PUBLIC_VWORLD_API_KEY`, `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY` |
| `KOR_TRAVEL_GEO_VWORLD_API_KEY`, `VWORLD_API_KEY` | `NEXT_PUBLIC_VWORLD_API_KEY`, `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`, `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY` |

객체 저장소는 `KOR_TRAVEL_MAP_OBJECT_STORE_*`를 사용한다. Docker 내부 endpoint는
`KOR_TRAVEL_MAP_DOCKER_OBJECT_STORE_ENDPOINT_URL`(기본 `http://rustfs:9000`)로 주입하고,
host/browser 공개 URL은 `KOR_TRAVEL_MAP_OBJECT_STORE_PUBLIC_BASE_URL`(기본
`http://127.0.0.1:12101/kor-travel-map`)을 사용한다. offline upload 원본 bucket은
`KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET`(기본 `kor-travel-map-uploads`)이다.
로컬 venv stack도 Docker compose와 같은 RustFS 개발 credential 기본값
`kor-travel-map-dev-access` / `kor-travel-map-dev-secret`을 사용한다.
Postgres host 포트 기본값은 `KOR_TRAVEL_MAP_POSTGRES_HOST_PORT=5432`이며,
`scripts/load-env.sh`는 `KOR_TRAVEL_MAP_PG_DSN` 미설정 시
`postgresql+asyncpg://kor_travel_map:kor_travel_map@127.0.0.1:5432/kor_travel_map`을 쓴다.
Dagster metadata는 같은 Postgres container 안의 별도 DB `kor_travel_map_dagster`를 쓴다.
`dagster-db-init` 서비스가 기동 때마다 DB 존재를 보장하고, Dagster webserver/daemon은
`KOR_TRAVEL_MAP_DAGSTER_PG_URL`(`KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL`)을 통해
`dagster-postgres` storage에 연결한다.

공유 DB 모드는 `kor-travel-docker-manager`가 이미 `kor-travel-geo-postgres:5432`를
띄운 상태에서 사용한다. 이때 kor-travel-map compose는 local Postgres를 띄우지 않고,
local RustFS와 API/frontend/Dagster만 띄운다.

```bash
KOR_TRAVEL_MAP_DB_EXTERNAL=true bash scripts/docker-up.sh
```

공유 인프라 모드는 `kor-travel-docker-manager`가 이미 `kor-travel-geo-postgres:5432`와
`tripmate-rustfs:12101`을 모두 띄운 상태에서 사용한다. 이때 kor-travel-map compose는 API,
frontend, Dagster webserver/daemon만 띄운다.

```bash
KOR_TRAVEL_MAP_INFRA_EXTERNAL=true bash scripts/docker-up.sh
```

공유 DB 비밀번호가 기본값과 다르면 `.env`에 `KOR_TRAVEL_MAP_POSTGRES_PASSWORD`를 두거나
컨테이너 관점 DSN을 직접 지정한다. 공유 Postgres에는 `kor_travel_map`과
`kor_travel_map_dagster` DB가 미리 있어야 한다.
공유 DB host 포트는 `KOR_TRAVEL_MAP_EXTERNAL_POSTGRES_HOST_PORT`로 override하며,
기본값은 `5432`다. 이 값은 standalone local Postgres publish 포트인
`KOR_TRAVEL_MAP_POSTGRES_HOST_PORT`와 분리되어 있다.

```bash
KOR_TRAVEL_MAP_EXTERNAL_POSTGRES_HOST_PORT=5432
KOR_TRAVEL_MAP_EXTERNAL_DOCKER_PG_DSN=postgresql+asyncpg://kor_travel_map:...@host.docker.internal:5432/kor_travel_map
KOR_TRAVEL_MAP_EXTERNAL_DOCKER_DAGSTER_PG_URL=postgresql://kor_travel_map:...@host.docker.internal:5432/kor_travel_map_dagster
KOR_TRAVEL_MAP_EXTERNAL_DOCKER_OBJECT_STORE_ENDPOINT_URL=http://host.docker.internal:12101
```

`docker-compose.yml`의 host publish는 기본
`KOR_TRAVEL_MAP_DOCKER_BIND_HOST=127.0.0.1`이다. API/frontend/Dagster/Postgres/RustFS
컨테이너 내부 프로세스는 컨테이너 네트워크 접근을 위해 `0.0.0.0`에 listen할 수
있지만, host의 모든 interface로 publish하지 않는다. 외부 접근이 필요하면 VPN,
SSO 게이트웨이, Cloudflare Tunnel, IP allowlist 같은 네트워크 보호를 먼저 구성한 뒤
`KOR_TRAVEL_MAP_DOCKER_BIND_HOST=0.0.0.0`을 명시한다.

frontend 컨테이너에는 `NEXT_PUBLIC_*`만 주입한다. 서버용 API 키는 API/Dagster
프로세스 환경변수로만 둔다. Dagster 임베드용 공개 URL은
`NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL`(기본 `http://127.0.0.1:12702`)이다. 로컬 API가
Dagster GraphQL을 조회할 때는 `KOR_TRAVEL_MAP_API_DAGSTER_URL`을 쓴다. Docker API
컨테이너는 같은 이름의 컨테이너 환경변수를 갖지만, 값은 compose에서
`KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL`(기본 내부 서비스명
`http://dagster:12702`)로 주입한다. `.env`의 로컬 `127.0.0.1` 값이 컨테이너 안으로
새지 않게 하기 위한 분리다. Dagster telemetry는 embedded 관리 화면의 첫 실행 안내와
외부 telemetry 호출을 피하기 위해
`DAGSTER_DISABLE_TELEMETRY=yes`를 기본값으로 둔다. Docker Dagster 이미지는
`docker/dagster.yaml`을 포함하며, 이 파일은 telemetry 비활성화와 Postgres metadata
storage, 고아 run 자동 회수(`run_monitoring`)를 함께 설정한다. 재기동 뒤 schedule은
`RUNNING`인데 새 run이 계속 `QUEUED`이면 `STARTED`/`STARTING` 장기 잔존 run이 동시성 슬롯을
점유하는지 먼저 확인한다. 정상 설정에서는 시작·취소 10분, 실행 6시간을 넘긴 run을 daemon이
종료 상태로 전환해 슬롯을 되돌린다. 단, 최신성이 중요한 KREX notice와 OpiNet place/price
job은 `dagster/max_runtime=7200` run tag로 2시간 상한을 적용한다. 이 tag는 schedule과
수동 실행이 공유하는 job 정의에 있다.

`run_monitoring`은 worker 소멸을 즉시 감지하지 않고 실행 시간 상한이 지난 run만 처리하며,
이미 쌓인 `QUEUED` run을 만료시키지 않는다. 장기 정체를 복구하거나 같은 상태에서 배포할 때는
다음 순서를 지킨다.

1. Dagster daemon을 먼저 중지해 backlog가 provider로 한꺼번에 실행되지 않게 한다.
2. 상태별 run 수와 가장 오래된 시각을 확인하고, 정체 기간에 쌓인 `QUEUED` run을 취소한다.
   worker가 없는 장기 `STARTED`/`STARTING`도 종료 상태로 정리한다. 현재 실행 중인 정상 run은
   생성 시각과 worker 존재를 확인하기 전 임의로 종료하지 않는다.
3. daemon을 다시 시작한 뒤 queue와 in-progress 수가 설정 상한 아래인지 확인한다.
4. 최신성이 중요한 notice와 OpiNet 가격 job을 각각 한 번 명시적으로 실행한다. notice는 현재
   feed 부재 항목이 종료됐는지, OpiNet은 오늘(KST) `observed_at`/`collected_at` 행이 생겼는지
   DB와 UI 양쪽에서 확인한다.

운영 host별 명령·접속값과 실제 취소 스크립트는 tracked 문서에 넣지 않고
`docs/deploy-runbook.local.md`를 따른다.

같은 설정의 `concurrency.pools`는 pool 기본 한도를 run 단위 1개로 둔다. 현재
`feature_place_opinet_stations`와 `feature_price_opinet_stations`가 같은 `opinet_api`
pool을 사용하므로 둘을 동시에 수동 실행해도 하나만 시작해야 한다. 배포 후 Dagster UI/API에서
두 OpiNet run을 함께 제출해 둘 다 즉시 `STARTED`가 되면 이미지의
`$DAGSTER_HOME/dagster.yaml` 반영 여부를 먼저 확인한다.
KREX notice도 별도 `krex_notice_snapshot` pool을 사용해 snapshot reconcile을 직렬화한다.
여기에 KREX notice 10분 schedule은 같은 provider/dataset tag의 `QUEUED`/`STARTING`/
`STARTED`/`CANCELING` run이 있으면 해당 tick을 skip해 새 backlog 생성을 예방한다. Dagster
schedule tick 상세의 skip 사유에는 기존 run 상태와 id가 남는다. 이는 배포 전에 이미 쌓인
queue를 지우지는 않으므로 위 복구 절차는 여전히 필요하다. 수동 run과 schedule tick의 동시
제출처럼 조회 직후 생기는 경합은 pool이 Dagster 실행을 직렬화하고, pool 우회 경로까지 아래
PostgreSQL advisory lock이 최종 방어한다.

실제 최종 방어는 provider 실행 함수의 PostgreSQL advisory lock이다. targeted feature update
worker는 asset pool을 거치지 않고 같은 함수를 직접 실행하므로, OpiNet place/price와 KREX
notice는 fetch→load/reconcile→sync 성공 전체에서 각각 고정된 provider lock을 공유한다. pool과
coalescing은 불필요한 run 시작·queue 누적·DB lock 대기를 줄이는 운영 제어다. worker process가
비정상 종료돼도 connection 종료와 함께 session lock이 풀린다.

OpiNet은 `provider_dataset` 이외 targeted feature update에서
`global_provider_not_targetable` 사유로 정상 skip되는 것이 기대 동작이다. 현재 lowTop 조회가
요청 범위를 소비하지 못하므로 이를 강제로 실행하면 같은 전국 window만 반복해 quota를
고갈시킨다. system schedule이나 provider-wide 수동 run이 갱신을 맡고, Dagster materialization
metadata의 `today_values_count`가 `price_values_upserted`보다 작으면 당일 price 성공으로
합치지 않아 다음 정식 run이 다시 시도한다. 두 값이 같아도 `latest_observed_at`이 cursor
`loaded_at`과 같은 KST 날짜가 아니면 재시도해야 한다. `already_succeeded_today_kst` skip은
같은 KST 날짜에 적재값 전체가 당일 가격인 뒤에만 정상이다.

## 2. 포트 정리

기동 전에 고정 포트를 점유한 프로세스를 종료한다.

```bash
npm run ports:stop
# 또는
scripts/stop-fixed-ports.sh 12701 12705 12702 12101 12105
```

## 3. Docker 이미지 빌드

```bash
npm run docker:build
# 내부 실행: docker compose build api frontend dagster dagster-daemon
```

frontend 이미지는 루트 `package-lock.json`을 build context에 포함하고
exact npm 12.0.1의 `npm ci --workspaces --include=optional`로 의존성을 설치한다. install 전에
`.npmrc`와 `scripts/patch-redocly-openapi-core.mjs`를 복사하며 postinstall이 Redocly exact
version·원문을 검사해 안전 minimatch API를 적용한다. dependency install script는 검토한
`esbuild@0.28.1`과 `unrs-resolver@1.12.2`만 허용하고 새 package/version은
`strict-allow-scripts`로 거부한다. `--ignore-scripts` 결과는 배포 검증으로 인정하지 않는다.
install 직후 `scripts/verify-next-sharp.mjs`가 Next image optimizer의 실제 SVG→WebP 변환으로
Sharp ABI를 확인한다. `scripts/verify-npm-tree.mjs`는 `npm ls --all --json`의 종료코드와
`problems` 0개를 모두 검사한다.
C7 Playwright image도 세 검증 script와 같은 lockfile을 사용하며 browser/client Playwright
1.60.0을 맞춘다. `package.json` 또는 workspace `package.json`을 바꾼 PR은 Linux에서 npm
12.0.1 지원 Node(`^22.22.2 || ^24.15.0 || >=26.0.0`)와 exact npm 12.0.1로 clean install,
audit high, tree-integrity verifier, optimizer smoke, lockfile 갱신과 frontend/C7 Docker 빌드를
함께 검증한다.

runtime 이미지는 root로 실행하지 않는다. `api`와 `dagster` 이미지는 builder stage에서
Python 패키지를 설치하고 runtime stage에서 `appuser`로 실행한다. `frontend` 이미지는
Next.js `.next/standalone` 산출물만 runner stage로 복사하고 `nextjs` 사용자로
`server.js`를 실행한다. Dockerfile을 바꾸는 PR은 multi-stage/non-root/standalone
회귀 테스트를 함께 갱신한다.

이미지는 다음 파일에서 만든다.

- `docker/api.Dockerfile`
- `docker/frontend.Dockerfile`
- `docker/dagster.Dockerfile`

### 3.1 T-108 multi-platform registry build

N150 16GB(x86_64)와 Odroid M1S(ARM64) 양쪽 배포용 이미지는 buildx로 같은 tag에 묶는다.
기본 platform은 `linux/amd64,linux/arm64`이고 출력은 registry push다.

```bash
KOR_TRAVEL_MAP_IMAGE_TAG="$(git rev-parse --short=12 HEAD)" npm run docker:buildx
```

`docker-buildx.sh`는 실행 worktree의 exact 40자 `HEAD`를 frontend build arg와 OCI
`org.opencontainers.image.revision` label에 함께 박는다. admin UI의 `/api/build-info`는
같은 빌드 SHA와 실제 frontend build 입력의 결정적 SHA-256을 반환한다. E2E runner는 clean
worktree에서 digest를 독립 계산하므로 tag/SHA만 같고 실제 코드가 다른 이미지는 통과할 수 없다.
mocked checkpoint runner는 외부 image/container를 입력받지 않는다. clean `HEAD`의
tracked 파일만 `git archive`로 분리한 context에서 frontend image를 직접 빌드하고, 그
immutable image ID에서 검증용 container를 직접 생성·기동한다. 외부 image의
entrypoint/CMD·mount를 신뢰하지 않으며, 검증용 container는 loopback host network의
정확한 IPv4 `127.0.0.1` `E2E_BASE_URL` port에서
read-only·cap-drop·no-new-privileges로 실행하고 성공·실패·종료 신호에 정리한다.
Docker build와 모든 container lifecycle, 장시간 Playwright child는 별도 process
group의 비동기 managed child로 실행한다. parent 종료 신호가 오면 mode-600 env/build
context를 먼저 unlink하고 child를 bounded 종료한 뒤 container와 runner별 임시 image
tag를 정리한다. BuildKit layer cache는 재실행 성능을 위해 유지한다. 실행 전후 동일
worktree HEAD/status/source digest와 container/image/build-info를 재검증한다. source
digest에는 `.dockerignore`와 실제
`NEXT_PUBLIC_*` build arg가 포함되며, empty 값의 fallback도 build wrapper와 동일하다.
nested `.env*`와 `.cache`는 Docker context와 digest 양쪽에서 제외한다. 공개 build-info
응답을 복제하거나 exact image의 entrypoint를 바꾼 fake server는 테스트를 시작할 수 없다.

기본 image:

- `ghcr.io/digitie/kor-travel-map-api:<tag>`
- `ghcr.io/digitie/kor-travel-map-admin:<tag>`
- `ghcr.io/digitie/kor-travel-map-dagster:<tag>`

provider repo(`python-*-api` 13종)는 2026-06-22부로 전부 public이라 Dagster build는
`GITHUB_TOKEN` 없이 `.[providers]` full ETL 이미지를 빌드한다. 토큰은 선택사항이며
(미인증 rate-limit 회피 / provider가 다시 private 될 때 대비), 주어지면 BuildKit
secret으로만 받고 build arg나 image layer에 남기지 않는다.

단일 platform smoke만 하려면 다음처럼 `docker` output을 사용한다.

```bash
KOR_TRAVEL_MAP_DOCKER_PLATFORMS=linux/amd64 \
KOR_TRAVEL_MAP_BUILDX_OUTPUT=docker \
  npm run docker:buildx
```

## 4. Docker stack 기동

```bash
npm run docker:up
# 내부 실행: docker compose up -d --build postgres dagster-db-init rustfs rustfs-init api frontend dagster dagster-daemon

KOR_TRAVEL_MAP_INFRA_EXTERNAL=true bash scripts/docker-up.sh
# 내부 실행: docker compose -f docker-compose.yml -f docker-compose.external-infra.yml up -d --build api frontend dagster dagster-daemon
```

API 컨테이너는 Postgres healthcheck 이후 `alembic upgrade head`를 실행하고 uvicorn을
띄운다. 기동 마이그레이션에는 두 가지 통제가 있다 (2026-08-03 prod 0072 사고 후속,
PR #931):

- `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD` — 설정 시, 이미지가 담은 alembic head가 이
  값과 다르면 **DB 연결 전에** 기동을 거부한다(chain이 모자란 이미지의 배포 차단).
  set-but-empty도 거부한다. 표준 compose는 이 값을 넣지 않는다(local-dev 불필요) —
  production 결선은 배포 orchestrator compose가 명시 값으로 소유한다.
- DB의 revision이 이미지 chain에 없으면(stale 이미지 재배포) retry 없이 즉시 실패한다 —
  `alembic current`로 선판정. 연결 실패 같은 일시 오류는 종전대로 retry 루프
  (`KOR_TRAVEL_MAP_MIGRATION_RETRIES`, 기본 30회)가 처리한다.
- `KOR_TRAVEL_MAP_MIGRATION_MODE`는 존재하지 않는다 — 설정돼 있으면 기동을 거부한다. `dagster-db-init`는 `kor_travel_map_dagster` DB 존재를 보장한다. `dagster`는
Dagster webserver, `dagster-daemon`은 schedule/sensor daemon이다. `rustfs-init`는
`kor-travel-map`과 `kor-travel-map-uploads` bucket을 생성한다. host `5432` 공유 DB를 쓰려면
`KOR_TRAVEL_MAP_DB_EXTERNAL=true` 또는 `KOR_TRAVEL_MAP_INFRA_EXTERNAL=true` 모드로
local Postgres를 띄우지 않는다.

Compose healthcheck 기준은 다음과 같다.

- `api`: 컨테이너 내부 `GET /health`
- `frontend`: 컨테이너 내부 Next.js root(`:12705`)
- `dagster`: 컨테이너 내부 Dagster webserver root

`frontend`는 `api`가 `service_healthy`가 된 뒤 시작한다. `docker compose ps`에서
`api`, `frontend`, `dagster`가 `healthy`인지 확인한 뒤 smoke를 진행한다.

## 5. 로컬 venv stack 기동

Docker 대신 현재 `.venv`와 npm workspace로 띄울 때는 다음을 사용한다.

```bash
npm run admin:stack
```

이 명령도 먼저 `12701`, `12705`, `12702` 점유 프로세스를 종료한 뒤 API, Next.js dev,
Dagster webserver, Dagster daemon을 백그라운드로 시작한다. 로컬 `DAGSTER_HOME`
기본값은 `.dagster`이며, 실행 때마다 `docker/dagster.yaml`을
`$DAGSTER_HOME/dagster.yaml`로 설치해 Docker와 같은 `storage.postgres`
(`KOR_TRAVEL_MAP_DAGSTER_PG_URL`) instance config를 공유한다. 시작 전에
`kor_travel_map_dagster` DB 존재도 확인/생성하므로 schedule/run/event metadata가
`$DAGSTER_HOME` 아래 SQLite로 폴백하면 회귀다. 로그는 기본 `.codex_tmp/admin-stack/`에
남는다.

`admin:stack`도 API 전용 `packages/kor-travel-map-api/.env`를 필수로 읽는다. API는
package 디렉터리를 cwd로 사용하고 scoped API 설정+DB/object-store 공유 설정만 받으며,
frontend는 `NEXT_PUBLIC_*`와 UI/BFF 설정만 받는다. 두 process는 빈 환경에서 allowlist를
채우므로 root `.env`의 provider loader credential을 상속하지 않는다. Dagster
webserver/daemon만 main `KOR_TRAVEL_MAP_*` provider 설정을 받는다. root
`KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET`이 비어 있거나 주변 공백을 포함하면 process를 시작하기
전에 실패하고, launcher가 검증된 같은 값을 두 process에 각각 주입한다.
상대 `KOR_TRAVEL_MAP_API_BACKUP_ROOT`는 project root 기준 절대경로로 정규화한다. API env의
inline comment와 root proxy secret 주변 공백도 모호한 값으로 간주해 기동 전에 거절한다.

## 6. 스모크

```bash
curl -fsS http://127.0.0.1:12701/health
curl -fsS -I http://127.0.0.1:12705/ | sed -n '1,8p'
curl -fsS -I http://127.0.0.1:12702/ | sed -n '1,8p'
curl -fsS -I http://127.0.0.1:12101/ | sed -n '1,8p' || true
docker compose ps
```

RustFS console은 `http://127.0.0.1:12105`다. 접근 키는 `.env`의
`KOR_TRAVEL_MAP_OBJECT_STORE_ACCESS_KEY_ID` /
`KOR_TRAVEL_MAP_OBJECT_STORE_SECRET_ACCESS_KEY`를 사용한다.

Dagster `definitions`의 일부 provider asset resource는 운영 구현이 주입되기 전까지
missing resource로 남는다. UI와 code location 로딩은 가능하고,
`offline_upload_store`는 RustFS/S3 기본 resource가 구현되어 있다. 실제 live provider
client resource wiring은 후속이다.

## 7. 중지

```bash
docker compose down
npm run ports:stop
```

로컬 `npm run admin:stack`으로 띄운 `dagster-daemon`은 포트를 열지 않으므로 필요하면
pid 파일로 종료한다. 다음 `admin:stack` 실행도 같은 pid 파일을 보고 이전 daemon을
먼저 정리한다.

```bash
kill "$(cat .codex_tmp/admin-stack/dagster-daemon.pid)" 2>/dev/null || true
rm -f .codex_tmp/admin-stack/dagster-daemon.pid
```

볼륨까지 지울 때만 다음을 사용한다.

```bash
docker compose down -v
```

## 8. Cold backup / staging restore

ADR-045 D-5 기준 백업 대상은 `kor_travel_map` app DB, `kor_travel_map_dagster` Dagster
metadata DB, RustFS volume의 3종 묶음이다.

일관된 RustFS snapshot을 위해 write path를 먼저 멈추고 Postgres는 실행 상태로 둔다.

```bash
docker compose stop api frontend dagster dagster-daemon rustfs
npm run docker:backup
```

기본 산출물은 `data/backups/<UTC timestamp>/` 아래에 생성된다.

```text
postgres/kor_travel_map.dump
postgres/kor_travel_map_dagster.dump
rustfs/rustfs-data.tar.gz
meta/manifest.json
meta/SHA256SUMS
```

검증과 수동 cold restore 경계는 `docs/backup-restore.md`를 따른다. admin router와
plan-only hot-swap restore UI는 `/admin/backups`에서 제공한다.

staging cold restore는 운영 DB와 운영 RustFS volume에 직접 쓰지 않고 기본 staging
대상(`kor_travel_map_restore`, `kor_travel_map_dagster_restore`,
`kor-travel-map-rustfs-restore`)으로 복원한다.

```bash
npm run docker:restore -- <backup_id>
```

기존 staging 대상이 있으면 중단한다. 다시 만드는 것이 의도라면
`KOR_TRAVEL_MAP_RESTORE_RECREATE=1`을 명시한다. 자세한 대상 override와 검증 절차는
`docs/backup-restore.md`를 따른다.

### 8.1 vNext production cutover gate

ADR-075/T-VN-39 cutover에서는 §8 cold backup만으로 rollback 가능하다고 판정하지 않는다.

- target ADR·DDL·OpenAPI SHA와 KTM/PinVi compatible image tag를 먼저 기록한다.
- API mutation, Dagster/daemon, admin write, outbox relay를 모두 fence하고 active writer 0건과
  queue/drain 상태를 확인한다.
- production clone에서 restore/PITR 또는 forward journal replay, shadow row count·checksum·FK/
  semantic duplicate 0건을 검증한다.
- PinVi consumer를 먼저 배포한 뒤 KTM DB/API를 전환하고, typed contract와 principal 401/403/422,
  read/write smoke를 수행한다.
- map API 재생성 전 `KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET`이 API container에만 공백 없는
  32자 이상으로 주입됐고 admin/service/ops/metrics credential과 다른지 확인한다. 실제 값은
  출력하거나 저장소에 기록하지 않는다. `/v1/features/search`는 첫 page cursor로 같은 query의
  다음 page를 조회하고, filter 변경·서명 변조가 각각 typed 422인지 확인한다. rotation 직후 기존
  cursor 무효화는 의도된 동작이며 배포 기록에 남긴다.
- rollback window에는 fence를 유지한다. fence 이후 delta가 있으면 old snapshot만 복원하지 말고
  검증된 journal/PITR을 적용한다. upstream 재수집으로 정본·감사·weather 이력을 대체하지 않는다.
- soak와 reconciliation 전에는 legacy table/column/alias와 backup을 제거하지 않는다.

실패한 DDL은 lock 획득 시간과 보유 시간을 구분해 기록한다. `CREATE INDEX CONCURRENTLY` 실패 시
INVALID index를 찾아 제거하며, UNIQUE writer conflict target을 index보다 먼저 전환하지 않는다.

### 8.2 weather 0060 semantic UNIQUE cutover

0060은 dedup과 UNIQUE 사이에 writer가 들어오는 것을 허용하지 않는다. 아래 절차는 API mutation,
Dagster schedule/sensor/manual/backfill ingress를 service 단위로 막고, migration의 DB lock을 마지막
불변식으로 사용한다. frontend까지 멈춰 admin write 진입점을 닫는다.

```bash
docker compose stop frontend api dagster dagster-daemon
test -z "$(docker compose ps --status running -q frontend api dagster dagster-daemon)"
```

DB에서 기존 write transaction, semantic duplicate, 제약 위반, index/constraint 상태를 확인한다.
첫 쿼리가 0행이 아니면 임의 종료하지 말고 소유 작업을 drain/취소한 뒤 다시 확인한다.

```sql
SELECT a.pid, a.application_name, a.state, l.mode
FROM pg_locks l
JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.relation = 'feature.feature_weather_values'::regclass
  AND l.granted
  AND l.mode IN (
      'RowExclusiveLock', 'ShareRowExclusiveLock',
      'ExclusiveLock', 'AccessExclusiveLock'
  );

SELECT c.relname, i.indisvalid, i.indisready, i.indisunique
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_index i ON i.indexrelid = c.oid
WHERE n.nspname = 'feature'
  AND c.relname = 'uq_weather_value_identity';

SELECT count(*) AS duplicate_losers
FROM (
    SELECT row_number() OVER (
        PARTITION BY feature_id, provider, weather_domain, forecast_style,
                     metric_key, issued_at, valid_at, observed_at
        ORDER BY collected_at DESC NULLS LAST,
                 updated_at DESC NULLS LAST,
                 weather_value_key DESC
    ) AS rn
    FROM feature.feature_weather_values
) ranked
WHERE rn > 1;

SELECT count(*) FILTER (
           WHERE valid_from IS NOT NULL AND valid_until IS NOT NULL
             AND valid_from > valid_until
       ) AS range_violations,
       count(*) FILTER (
           WHERE jsonb_typeof(payload) <> 'object'
       ) AS payload_violations,
       count(*) FILTER (
           WHERE source_record_key IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM provider_sync.source_records AS sr
                 WHERE sr.source_record_key = w.source_record_key
             )
       ) AS orphan_source_records
FROM feature.feature_weather_values AS w;

SELECT conname, convalidated
FROM pg_constraint
WHERE conrelid = 'feature.feature_weather_values'::regclass
  AND conname IN (
      'ck_weather_value_range',
      'ck_weather_value_payload_object',
      'fk_weather_value_source_record'
  )
ORDER BY conname;
```

migration 전 세 violation count는 모두 0이어야 한다. 0이 아니면 실행하지 말고 authoritative
source와 대조한 승인된 data repair 또는 cutover 전 backup/PITR 복원을 선택한다. 임의 삭제·NULL
치환으로 통과시키지 않는다. migration도 같은 위반을 writer lock 아래 재검사해 destructive
commit 전에 SQLSTATE `23514`로 실패한다.

migration은 5초 안에 `SHARE ROW EXCLUSIVE`를 얻지 못하면 전체 rollback한다. lock을 얻은 뒤
dedup과 non-concurrent UNIQUE를 같은 transaction에서 commit한다. 과거 실패의 동명 index/constraint는
그 전에 5초 timeout의 짧은 autocommit DDL로만 정규화해 main build 동안 `ACCESS EXCLUSIVE`를
보유하지 않는다. fresh 0059에는 정리 DDL이 없다. 따라서 새 실행은 INVALID index를 남기지 않는다. 세 VALIDATE도
각각 session-level 5초 lock timeout을 적용하고 성공·실패 뒤 RESET한다.

배포할 API image ID와 OCI revision, root-only runtime env snapshot, compose network를 먼저 exact
검증한다. tag나 mutable compose build를 migration 입력으로 쓰지 않는다. 다음 immutable image
명령을 `upgrade` 한 번과 read-only 확인에 동일하게 사용한다.

```bash
readonly MAP_API_IMAGE_ID='sha256:<64-hex-image-id>'
readonly MAP_NETWORK='<compose-project>_default'
readonly MAP_API_ENV_FILE='/root/<root-only-api-runtime-env>'

sudo test "$(stat -c '%U:%G %a' "$MAP_API_ENV_FILE")" = 'root:root 600'
sudo docker image inspect "$MAP_API_IMAGE_ID" \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
sudo docker run --rm --pull never --network "$MAP_NETWORK" \
  --env-file "$MAP_API_ENV_FILE" --entrypoint alembic \
  "$MAP_API_IMAGE_ID" upgrade head
sudo docker run --rm --pull never --network "$MAP_NETWORK" \
  --env-file "$MAP_API_ENV_FILE" --entrypoint alembic \
  "$MAP_API_IMAGE_ID" current
sudo docker run --rm --pull never --network "$MAP_NETWORK" \
  --env-file "$MAP_API_ENV_FILE" --entrypoint alembic \
  "$MAP_API_IMAGE_ID" heads
sudo docker run --rm --pull never --network "$MAP_NETWORK" \
  --env-file "$MAP_API_ENV_FILE" --entrypoint alembic \
  "$MAP_API_IMAGE_ID" check
```

`current`와 유일한 `heads`가 같고 `check`가 성공한 뒤 다음을 모두 확인한다.

```sql
SELECT i.indisvalid, i.indisready, i.indisunique, i.indnullsnotdistinct
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_index i ON i.indexrelid = c.oid
WHERE n.nspname = 'feature'
  AND c.relname = 'uq_weather_value_identity';

SELECT conname, convalidated
FROM pg_constraint
WHERE conrelid = 'feature.feature_weather_values'::regclass
  AND conname IN (
      'ck_weather_value_range',
      'ck_weather_value_payload_object',
      'fk_weather_value_source_record'
  )
ORDER BY conname;

SELECT count(*) AS duplicate_losers
FROM (
    SELECT row_number() OVER (
        PARTITION BY feature_id, provider, weather_domain, forecast_style,
                     metric_key, issued_at, valid_at, observed_at
        ORDER BY collected_at DESC NULLS LAST,
                 updated_at DESC NULLS LAST,
                 weather_value_key DESC
    ) AS rn
    FROM feature.feature_weather_values
) ranked
WHERE rn > 1;

SELECT count(*) FILTER (
           WHERE valid_from IS NOT NULL AND valid_until IS NOT NULL
             AND valid_from > valid_until
       ) AS range_violations,
       count(*) FILTER (
           WHERE jsonb_typeof(payload) <> 'object'
       ) AS payload_violations,
       count(*) FILTER (
           WHERE source_record_key IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM provider_sync.source_records AS sr
                 WHERE sr.source_record_key = w.source_record_key
             )
       ) AS orphan_source_records
FROM feature.feature_weather_values AS w;
```

정상은 index boolean 네 값과 세 `convalidated`가 모두 true이고 **post-check의**
`duplicate_losers=0`, violation 세 값이 모두 0이다. 최초 preflight의 duplicate 수는 migration이
제거할 예상 loser이므로 0보다 클 수 있다. 실패하면 service fence를 유지하고 Alembic
current, 위 index, 세 constraint validity를 다시 캡처한다.

- violation이 하나라도 남으면 같은 corrupt row를 둔 재시도를 금지한다. authoritative source 기반
  repair 또는 cutover 전 restore/PITR 후 preflight부터 다시 수행한다.
- current가 0059인데 valid UNIQUE와 NOT VALID/일부 VALID constraint가 있으면 VALIDATE lock timeout
  등 autocommit 뒤 실패다. violation 0과 active writer 0을 다시 확인한 뒤 **같은 immutable image**의
  `upgrade head`를 재실행한다. 0060은 exact 세 constraint/index를 별도 짧은 retry transaction으로
  정규화한 뒤 writer-only main cutover를 다시 수행한다.
- 동명 INVALID index가 있으면 과거 concurrent 구현의 잔재다. 다음 원자 cleanup 뒤 preflight와 같은
  immutable image migration을 재실행한다.

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';
LOCK TABLE feature.feature_weather_values IN SHARE ROW EXCLUSIVE MODE;
DROP INDEX IF EXISTS feature.uq_weather_value_identity;
COMMIT;
```

새 API/Dagster image와 migration head/check, semantic upsert smoke가 모두 성공한 뒤에만
Dagster web/daemon→API→frontend 순서로 재기동한다. 구 writer image는 다시 기동하지 않는다.

0060 `alembic downgrade`는 지원하지 않는다. dedup loser와 semantic conflict-target writer를
DDL만으로 원자 복원할 수 없기 때문이다. 0060 이전으로 돌아가야 하면 writer fence를 유지한 채
cutover 전 backup/PITR과 그 backup에 대응하는 구 API·Dagster image를 함께 복원하고, old semantic
writer smoke가 성공한 뒤에만 서비스를 연다.

## 9. T-108 양 노드 배포 경계

T-108의 양 노드 운영은 같은 image tag를 N150 16GB(x86_64)와 Odroid M1S(ARM64)에 배포할
수 있게 만드는 데서 닫는다. 사용자 재지시에 따라 **streaming replication은 하지 않는다**.
운영 DB 복구성은 cold backup/restore와 hot-swap restore 훈련으로 검증한다.

권장 배치:

| 노드                                | 역할      | platform      |
| ----------------------------------- | --------- | ------------- |
| N150 16GB / NVMe 1TB / Ubuntu 26.04 | 운영 후보 | `linux/amd64` |
| Odroid M1S                          | 운영 후보 | `linux/arm64` |

두 노드는 같은 registry tag를 pull한다. 어느 노드를 실제 active host로 둘지는 외부
운영 runbook에서 결정한다. Postgres streaming replication, 자동 failover, VIP/DNS 전환,
RustFS 다중 노드 복제는 이 저장소 T-108 범위에 넣지 않는다.
