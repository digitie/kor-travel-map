# Docker 독립 app runbook

본 문서는 ADR-045/047 기준 kor-travel-map 독립 프로그램을 로컬에서 빌드·기동·스모크하는
절차다. 고정 포트는 API `12301`, admin UI `12305`, Dagster `12302`이다. 기본
standalone compose는 Postgres host `5432`, RustFS S3 API `12101`, console `12105`를
쓴다. `kor-travel-docker-manager`가 공유 PostGIS/RustFS를 이미 구동 중이면
`KOR_TRAVEL_MAP_INFRA_EXTERNAL=true`로 local infra 서비스를 띄우지 않는다.

## 0. 실행 셸

이 runbook의 `npm run docker:build`, `npm run docker:up`, `npm run docker:backup`,
`npm run docker:restore`, `npm run admin:stack`, `npm run ports:stop`은 루트
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

실제 키는 루트 `.env`에 둔다. `.env`는 git에 커밋하지 않는다.

```bash
cp .env.example .env
chmod 600 .env
```

`scripts/load-env.sh`와 `docker-compose.yml`은 기존 provider repo에서 쓰던 키 이름을
실행용 환경변수로 매핑한다.

| 입력 키 예 | 실행 시 export |
|------------|----------------|
| `DATA_GO_KR_SERVICE_KEY`, `KMA_API_KEY` | `KOR_TRAVEL_MAP_ADMIN_KMA_SERVICE_KEY`, `KOR_TRAVEL_MAP_ADMIN_DATAGOKR_SERVICE_KEY` |
| `OPINET_API_KEY` | `KOR_TRAVEL_MAP_ADMIN_OPINET_SERVICE_KEY` |
| `KEX_GO_API_KEY`, `KREX_API_KEY` | `KOR_TRAVEL_MAP_ADMIN_KREX_SERVICE_KEY` |
| `KOR_TRAVEL_GEO_VWORLD_API_KEY`, `VWORLD_API_KEY` | `NEXT_PUBLIC_VWORLD_API_KEY` |

객체 저장소는 `KOR_TRAVEL_MAP_OBJECT_STORE_*`를 사용한다. Docker 내부 endpoint는
`KOR_TRAVEL_MAP_DOCKER_OBJECT_STORE_ENDPOINT_URL`(기본 `http://rustfs:9000`)로 주입하고,
host/browser 공개 URL은 `KOR_TRAVEL_MAP_OBJECT_STORE_PUBLIC_BASE_URL`(기본
`http://127.0.0.1:12101/kor-travel-map`)을 사용한다. offline upload 원본 bucket은
`KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET`(기본 `krtour-uploads`)이다.
로컬 venv stack도 Docker compose와 같은 RustFS 개발 credential 기본값
`kor-travel-map-dev-access` / `kor-travel-map-dev-secret`을 사용한다.
Postgres host 포트 기본값은 `KOR_TRAVEL_MAP_POSTGRES_HOST_PORT=5432`이며,
`scripts/load-env.sh`는 `KOR_TRAVEL_MAP_PG_DSN` 미설정 시
`postgresql+asyncpg://kor_travel_map:kor_travel_map@127.0.0.1:5432/kor_travel_map`을 쓴다.
Dagster metadata는 같은 Postgres container 안의 별도 DB `kor_travel_map_dagster`를 쓴다.
`dagster-db-init` 서비스가 기동 때마다 DB 존재를 보장하고, Dagster webserver/daemon은
`KOR_TRAVEL_MAP_DAGSTER_PG_URL`(`KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL`)을 통해
`dagster-postgres` storage에 연결한다.

공유 인프라 모드는 `kor-travel-docker-manager`가 이미 `kor-travel-geo-postgres:5432`와
`tripmate-rustfs:12101`을 띄운 상태에서 사용한다. 이때 kor-travel-map compose는 API,
frontend, Dagster webserver/daemon만 띄운다.

```bash
KOR_TRAVEL_MAP_INFRA_EXTERNAL=true bash scripts/docker-up.sh
```

공유 DB 비밀번호가 기본값과 다르면 `.env`에 `KOR_TRAVEL_MAP_POSTGRES_PASSWORD`를 두거나
컨테이너 관점 DSN을 직접 지정한다. 공유 Postgres에는 `kor_travel_map`과
`kor_travel_map_dagster` DB가 미리 있어야 한다.

```bash
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
`NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL`(기본 `http://127.0.0.1:12302`)이다. 로컬 API가
Dagster GraphQL을 조회할 때는 `KOR_TRAVEL_MAP_ADMIN_DAGSTER_URL`을 쓴다. Docker API
컨테이너는 같은 이름의 컨테이너 환경변수를 갖지만, 값은 compose에서
`KOR_TRAVEL_MAP_DOCKER_ADMIN_DAGSTER_URL`(기본 내부 서비스명
`http://dagster:12302`)로 주입한다. `.env`의 로컬 `127.0.0.1` 값이 컨테이너 안으로
새지 않게 하기 위한 분리다. Dagster telemetry는 embedded 관리 화면의 첫 실행 안내와
외부 telemetry 호출을 피하기 위해
`DAGSTER_DISABLE_TELEMETRY=yes`를 기본값으로 둔다. Docker Dagster 이미지는
`docker/dagster.yaml`을 포함하며, 이 파일은 telemetry 비활성화와 Postgres metadata
storage를 함께 설정한다.

## 2. 포트 정리

기동 전에 고정 포트를 점유한 프로세스를 종료한다.

```bash
npm run ports:stop
# 또는
scripts/stop-fixed-ports.sh 12301 12305 12302 12101 12105
```

## 3. Docker 이미지 빌드

```bash
npm run docker:build
# 내부 실행: docker compose build api frontend dagster dagster-daemon
```

frontend 이미지는 루트 `package-lock.json`을 build context에 포함하고
`npm ci --workspaces --include=optional`로 의존성을 설치한다. `package.json` 또는
workspace `package.json`을 바꾼 PR은 WSL Node/npm으로 lockfile을 함께 갱신한 뒤
Docker 빌드를 검증한다.

runtime 이미지는 root로 실행하지 않는다. `api`와 `dagster` 이미지는 builder stage에서
Python 패키지를 설치하고 runtime stage에서 `appuser`로 실행한다. `frontend` 이미지는
Next.js `.next/standalone` 산출물만 runner stage로 복사하고 `nextjs` 사용자로
`server.js`를 실행한다. Dockerfile을 바꾸는 PR은 multi-stage/non-root/standalone
회귀 테스트를 함께 갱신한다.

이미지는 다음 파일에서 만든다.

- `docker/api.Dockerfile`
- `docker/frontend.Dockerfile`
- `docker/dagster.Dockerfile`

## 4. Docker stack 기동

```bash
npm run docker:up
# 내부 실행: docker compose up -d --build postgres dagster-db-init rustfs rustfs-init api frontend dagster dagster-daemon

KOR_TRAVEL_MAP_INFRA_EXTERNAL=true bash scripts/docker-up.sh
# 내부 실행: docker compose -f docker-compose.yml -f docker-compose.external-infra.yml up -d --build api frontend dagster dagster-daemon
```

API 컨테이너는 Postgres healthcheck 이후 `alembic upgrade head`를 실행하고 uvicorn을
띄운다. `dagster-db-init`는 `kor_travel_map_dagster` DB 존재를 보장한다. `dagster`는
Dagster webserver, `dagster-daemon`은 schedule/sensor daemon이다. `rustfs-init`는
`kor-travel-map`과 `krtour-uploads` bucket을 생성한다. Postgres host 포트 기본값은
`5432`이다.

Compose healthcheck 기준은 다음과 같다.

- `api`: 컨테이너 내부 `GET /health`
- `frontend`: 컨테이너 내부 Next.js root(`:12305`)
- `dagster`: 컨테이너 내부 Dagster webserver root

`frontend`는 `api`가 `service_healthy`가 된 뒤 시작한다. `docker compose ps`에서
`api`, `frontend`, `dagster`가 `healthy`인지 확인한 뒤 smoke를 진행한다.

## 5. 로컬 venv stack 기동

Docker 대신 현재 `.venv`와 npm workspace로 띄울 때는 다음을 사용한다.

```bash
npm run admin:stack
```

이 명령도 먼저 `12301`, `12305`, `12302` 점유 프로세스를 종료한 뒤 API, Next.js dev,
Dagster webserver, Dagster daemon을 백그라운드로 시작한다. 로컬 `DAGSTER_HOME`
기본값은 `.dagster`이며, 실행 때마다 `docker/dagster.yaml`을
`$DAGSTER_HOME/dagster.yaml`로 설치해 Docker와 같은 `storage.postgres`
(`KOR_TRAVEL_MAP_DAGSTER_PG_URL`) instance config를 공유한다. 시작 전에
`kor_travel_map_dagster` DB 존재도 확인/생성하므로 schedule/run/event metadata가
`$DAGSTER_HOME` 아래 SQLite로 폴백하면 회귀다. 로그는 기본 `.codex_tmp/admin-stack/`에
남는다.

## 6. 스모크

```bash
curl -fsS http://127.0.0.1:12301/health
curl -fsS -I http://127.0.0.1:12305/ | sed -n '1,8p'
curl -fsS -I http://127.0.0.1:12302/ | sed -n '1,8p'
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
