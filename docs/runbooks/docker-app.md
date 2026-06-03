# Docker 독립 app runbook

본 문서는 ADR-045/047 기준 krtour-map 독립 프로그램을 로컬에서 빌드·기동·스모크하는
절차다. 고정 포트는 API `9011`, admin UI `9012`, Dagster `9013`이다. RustFS는
로컬 compose에 포함하며 S3 API는 `9003`, console은 `9004`를 쓴다.

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
| `DATA_GO_KR_SERVICE_KEY`, `KMA_API_KEY` | `KRTOUR_MAP_ADMIN_KMA_SERVICE_KEY`, `KRTOUR_MAP_ADMIN_DATAGOKR_SERVICE_KEY` |
| `OPINET_API_KEY` | `KRTOUR_MAP_ADMIN_OPINET_SERVICE_KEY` |
| `KEX_GO_API_KEY`, `KREX_API_KEY` | `KRTOUR_MAP_ADMIN_KREX_SERVICE_KEY` |
| `KRADDR_GEO_VWORLD_API_KEY`, `VWORLD_API_KEY` | `NEXT_PUBLIC_VWORLD_API_KEY` |

객체 저장소는 `KRTOUR_MAP_OBJECT_STORE_*`를 사용한다. Docker 내부 endpoint는
`KRTOUR_MAP_DOCKER_OBJECT_STORE_ENDPOINT_URL`(기본 `http://rustfs:9000`)로 주입하고,
host/browser 공개 URL은 `KRTOUR_MAP_OBJECT_STORE_PUBLIC_BASE_URL`(기본
`http://127.0.0.1:9003/krtour-map`)을 사용한다. offline upload 원본 bucket은
`KRTOUR_MAP_OFFLINE_UPLOAD_BUCKET`(기본 `krtour-uploads`)이다.

frontend 컨테이너에는 `NEXT_PUBLIC_*`만 주입한다. 서버용 API 키는 API/Dagster
프로세스 환경변수로만 둔다. Dagster 임베드용 공개 URL은
`NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL`(기본 `http://127.0.0.1:9013`)이다. 로컬 API가
Dagster GraphQL을 조회할 때는 `KRTOUR_MAP_ADMIN_DAGSTER_URL`을 쓴다. Docker API
컨테이너는 같은 이름의 컨테이너 환경변수를 갖지만, 값은 compose에서
`KRTOUR_MAP_DOCKER_ADMIN_DAGSTER_URL`(기본 내부 서비스명
`http://dagster:9013`)로 주입한다. `.env`의 로컬 `127.0.0.1` 값이 컨테이너 안으로
새지 않게 하기 위한 분리다. Dagster telemetry는 embedded 관리 화면의 첫 실행 안내와
외부 telemetry 호출을 피하기 위해
`DAGSTER_DISABLE_TELEMETRY=yes`를 기본값으로 둔다. 로컬 `scripts/run-admin-stack.sh`는
`DAGSTER_HOME/dagster.yaml`이 없으면 `telemetry.enabled: false` 설정 파일을 만들고,
Docker Dagster 이미지는 같은 설정 파일을 포함한다.

## 2. 포트 정리

기동 전에 고정 포트를 점유한 프로세스를 종료한다.

```bash
npm run ports:stop
# 또는
scripts/stop-fixed-ports.sh 9011 9012 9013 9003 9004
```

## 3. Docker 이미지 빌드

```bash
npm run docker:build
# 내부 실행: docker compose build api frontend dagster
```

이미지는 다음 파일에서 만든다.

- `docker/api.Dockerfile`
- `docker/frontend.Dockerfile`
- `docker/dagster.Dockerfile`

## 4. Docker stack 기동

```bash
npm run docker:up
# 내부 실행: docker compose up -d --build postgres rustfs rustfs-init api frontend dagster
```

API 컨테이너는 Postgres healthcheck 이후 `alembic upgrade head`를 실행하고 uvicorn을
띄운다. `rustfs-init`는 `krtour-map`과 `krtour-uploads` bucket을 생성한다. Postgres
host 포트 기본값은 `15433`이다.

## 5. 로컬 venv stack 기동

Docker 대신 현재 `.venv`와 npm workspace로 띄울 때는 다음을 사용한다.

```bash
npm run admin:stack
```

이 명령도 먼저 `9011`, `9012`, `9013` 점유 프로세스를 종료한 뒤 API, Next.js dev,
Dagster dev를 백그라운드로 시작한다. 로그는 기본 `.codex_tmp/admin-stack/`에 남는다.

## 6. 스모크

```bash
curl -fsS http://127.0.0.1:9011/debug/health
curl -fsS -I http://127.0.0.1:9012/ | sed -n '1,8p'
curl -fsS -I http://127.0.0.1:9013/ | sed -n '1,8p'
curl -fsS -I http://127.0.0.1:9003/ | sed -n '1,8p' || true
docker compose ps
```

RustFS console은 `http://127.0.0.1:9004`다. 접근 키는 `.env`의
`KRTOUR_MAP_OBJECT_STORE_ACCESS_KEY_ID` /
`KRTOUR_MAP_OBJECT_STORE_SECRET_ACCESS_KEY`를 사용한다.

Dagster `definitions`의 일부 asset resource는 운영 구현이 주입되기 전까지 missing
resource로 남는다. UI와 code location 로딩은 가능하지만 실제 live provider 실행은
후속 resource 구현(T-208b 후속) 이후가 정본이다.

## 7. 중지

```bash
docker compose down
npm run ports:stop
```

볼륨까지 지울 때만 다음을 사용한다.

```bash
docker compose down -v
```
