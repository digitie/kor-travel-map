# Docker 독립 app runbook

본 문서는 ADR-045/047 기준 krtour-map 독립 프로그램을 로컬에서 빌드·기동·스모크하는
절차다. 고정 포트는 API `9011`, admin UI `9012`, Dagster `9013`이다.

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

frontend 컨테이너에는 `NEXT_PUBLIC_*`만 주입한다. 서버용 API 키는 API/Dagster
프로세스 환경변수로만 둔다. Dagster 임베드용 공개 URL은
`NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL`(기본 `http://127.0.0.1:9013`)이다. API
컨테이너가 Dagster GraphQL을 조회할 때는 `KRTOUR_MAP_ADMIN_DAGSTER_URL`을 쓰며,
compose 기본값은 내부 서비스명 기준 `http://dagster:9013`이다. Dagster telemetry는
embedded 관리 화면의 첫 실행 안내와 외부 telemetry 호출을 피하기 위해
`DAGSTER_DISABLE_TELEMETRY=yes`를 기본값으로 둔다. 로컬 `scripts/run-admin-stack.sh`는
`DAGSTER_HOME/dagster.yaml`이 없으면 `telemetry.enabled: false` 설정 파일을 만들고,
Docker Dagster 이미지는 같은 설정 파일을 포함한다.

## 2. 포트 정리

기동 전에 고정 포트를 점유한 프로세스를 종료한다.

```bash
npm run ports:stop
# 또는
scripts/stop-fixed-ports.sh 9011 9012 9013
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
# 내부 실행: docker compose up -d --build postgres api frontend dagster
```

API 컨테이너는 Postgres healthcheck 이후 `alembic upgrade head`를 실행하고 uvicorn을
띄운다. Postgres host 포트 기본값은 `15433`이다.

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
docker compose ps
```

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
