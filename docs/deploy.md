# 배포 메모

본 문서는 ADR-045/047/056 기준 독립 kor-travel-map app 배포의 현재 1차 기준이다.
`T-209e-a/b/c` 기준 cold backup script, staging restore script/runbook, admin
backup/restore router와 plan-only UI가 제공된다. `T-108`로 N150 16GB(x86_64)와
Odroid M1S(ARM64) 양쪽 배포를 위한 multi-platform Docker build 절차를 추가했다.
사용자 재지시에 따라 **streaming replication은 하지 않는다**.

## 서비스

| 서비스 | 기본 포트 | 역할 |
|--------|-----------|------|
| `api` | `12701` | `kor-travel-map-api` FastAPI, OpenAPI/public/admin/debug/ops 라우터 |
| `frontend` | `12705` | Next.js admin UI |
| `dagster` | `12702` | kor-travel-map-owned Dagster UI/code location |
| `postgres` | host `5432`, container `5432` | 독립 `kor_travel_map` PostGIS DB |
| `rustfs` | API `12101`, console `12105` | S3 호환 객체 저장소(선택, backup 대상) |

Prometheus 성능 메트릭은 별도 포트를 열지 않고 `api`의 같은 host 포트 `12701`에서
`GET /metrics`로 노출한다. 이 endpoint는 공개 REST(`/v1/features`·`/v1/categories`·
`/v1/providers`·`/v1/public`), `/admin`, `/ops`, `/debug`, system route의 HTTP 요청
수/지연 시간/응답 크기/예외와 DB query 수/지연 시간을 함께 제공한다.
`kor-travel-docker-manager` 관측 스택은 Grafana `12205`, cAdvisor Exporter
`12301`, Prometheus `12401`을 사용하며, Prometheus가
`http://<kor-travel-map-api>:12701/metrics`를 pull scrape한다. 앱이 Prometheus로 능동
연결하지 않는다.

`kor-travel-docker-manager`가 공유 PostGIS/RustFS를 이미 구동하는 로컬 환경에서는 kor-travel-map의
local `postgres`/`rustfs` 서비스를 함께 띄우면 `5432`/`12101`이 충돌한다. 이때는
`KOR_TRAVEL_MAP_INFRA_EXTERNAL=true bash scripts/docker-up.sh`를 사용해 API, Web UI,
Dagster만 올리고, 컨테이너는 `host.docker.internal:5432` /
`host.docker.internal:12101`로 공유 인프라에 연결한다.

`api`, `frontend`, `dagster`는 Docker compose healthcheck를 가진다. `frontend`는
`api`의 `service_healthy` 이후 시작한다.

## 최소 배포 절차

```bash
cp .env.example .env
chmod 600 .env
npm run docker:build
npm run docker:up
```

스모크는 `docs/runbooks/docker-app.md` §6을 따른다.

> **dev vs prod**: 위 `npm run docker:*`는 **이 저장소에서 직접 띄우는 dev/standalone
> 경로**다(기본 Docker host 네트워크 + `127.0.0.1`의 12xxx 고정 포트 + 포트 가드 —
> `docs/dev-environment.md` §0). **prod는 `kor-travel-docker-manager`로 기동하고 공식
> 도메인(reverse proxy, 아래 §프로덕션 도메인)을 적용한다.** 별도 지시가 없으면 dev를
> 의미한다. host 모드를 끄려면 `KOR_TRAVEL_MAP_DOCKER_NETWORK=bridge`.
frontend 이미지는 루트 `package-lock.json`과 `npm ci`로 재현 가능한 workspace
의존성 설치를 사용한다.

## T-108: 양 노드 배포 자동화

운영 하드웨어는 **N150 16GB / NVMe 1TB / Ubuntu 26.04** 노드와 **Odroid M1S**
노드를 병행 대상으로 둔다. Docker image는 `linux/amd64`와 `linux/arm64`를 같은 tag로
빌드해 registry에 push한다.

```bash
KOR_TRAVEL_MAP_IMAGE_TAG="$(git rev-parse --short=12 HEAD)" \
  npm run docker:buildx
```

기본 image 이름은 다음과 같다.

| 서비스 | 기본 image |
|--------|------------|
| `api` | `ghcr.io/digitie/kor-travel-map-api:<tag>` |
| `frontend` | `ghcr.io/digitie/kor-travel-map-admin:<tag>` |
| `dagster`, `dagster-daemon` | `ghcr.io/digitie/kor-travel-map-dagster:<tag>` |

로컬 단일 platform 검증만 할 때는 다음처럼 `--load` 경로를 쓴다.

```bash
KOR_TRAVEL_MAP_DOCKER_PLATFORMS=linux/amd64 \
KOR_TRAVEL_MAP_BUILDX_OUTPUT=docker \
  npm run docker:buildx
```

두 노드에 같은 tag를 배포할 수 있게 image manifest만 맞춘다. Postgres
streaming replication은 하지 않는다. 운영 DB 복구성은 cold backup/restore와
hot-swap restore 훈련으로 검증하고, 공유 RustFS는 `kor-travel-docker-manager` 정본을 따른다.

## 백업

백업 대상은 PinVi와 분리된 `kor_travel_map` app DB, `kor_travel_map_dagster` Dagster
metadata DB, RustFS volume의 3종 묶음이다. cold backup은 write path를 멈춘 뒤 실행한다.

```bash
docker compose stop api frontend dagster dagster-daemon rustfs
npm run docker:backup
npm run docker:restore -- <backup_id>
```

restore 기본 대상은 `kor_travel_map_restore`, `kor_travel_map_dagster_restore`,
`kor-travel-map-rustfs-restore`라 운영 DB/volume에 직접 쓰지 않는다. 산출물과 검증 절차는
`docs/backup-restore.md`를 따른다.

## 환경변수

`.env`는 배포 환경의 secret store, systemd `EnvironmentFile`, 또는 Docker secret로
관리한다. git에는 `.env.example`만 둔다. provider key는 기존 provider repo 이름을
그대로 둘 수 있고, `scripts/load-env.sh`/`docker-compose.yml`이 실행용
`KOR_TRAVEL_MAP_API_*` 이름으로 매핑한다.
PC 개발 환경에서 host `5432`는 `kor-travel-docker-manager`가 소유한
공유 PostgreSQL/PostGIS 서버 인스턴스다. `KOR_TRAVEL_MAP_PG_DSN`을 명시하지 않으면
`scripts/load-env.sh`가 `127.0.0.1:5432/kor_travel_map` DSN을 채운다.
공유 DB만 쓰고 RustFS는 local compose로 띄우는 Docker 기동은
`KOR_TRAVEL_MAP_DB_EXTERNAL=true`와 `KOR_TRAVEL_MAP_EXTERNAL_POSTGRES_HOST_PORT=5432`
기준이다. 공유 DB와 공유 RustFS를 모두 쓰면 `KOR_TRAVEL_MAP_INFRA_EXTERNAL=true`를 쓴다.

## 프로덕션 도메인 (reverse proxy)

외부 노출은 reverse proxy(Caddy/nginx/Cloudflare Tunnel 등)가 TLS 종단과 라우팅을
담당한다(§보안 경계). 앱 자체는 도메인을 모르고, 아래 env로만 "브라우저가 어떤 주소로
각 서비스에 닿는지"를 안다. **실 도메인은 git에 올리지 않고 운영 노드의 gitignored
`.env`(또는 `.env.prod`)에만 둔다.** `.env.example`에 변수 목록과 예시(placeholder)가 있다.

| reverse proxy 도메인(예시) | 대상 서비스 | host 포트 |
|---|---|---|
| `<map-host>` | `frontend` (admin UI) | `12705` |
| `<map-api-host>` | `api` (FastAPI) | `12701` |
| `<map-dagster-host>` | `dagster` (Dagster UI) | `12702` |
| `<s3-api-host>` | `rustfs` S3 API | `12101` |
| `<s3-console-host>` | `rustfs` console | `12105` |
| `<geo-api-host>` | `kor-travel-geo` REST API | `12501` |
| `<geo-console-host>` | `kor-travel-geo` Web UI | `12505` |

운영 노드 `.env`에 채우는 값:

- `NEXT_PUBLIC_KOR_TRAVEL_MAP_API` / `NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL` —
  프론트(브라우저)가 호출할 API/Dagster 주소. **Next.js build-time inline**이라 도메인을
  바꾸면 frontend 이미지를 **재빌드**한다(`npm run docker:build`).
- `KOR_TRAVEL_MAP_API_CORS_ALLOW_ORIGINS` — 프론트 origin(예: `["https://<map-host>"]`)을
  허용해야 브라우저 cross-origin fetch가 통과한다. `docker-compose.yml`은 이 env가 있으면
  그대로 쓰고, 없으면 localhost(`:12705`)로 fallback한다.
- `KOR_TRAVEL_MAP_OBJECT_STORE_PUBLIC_BASE_URL` — feature 파일/업로드 이미지의 **브라우저
  노출 주소**(`https://<s3-api-host>/<bucket>`). API 컨테이너→RustFS 내부 통신은 docker
  네트워크(`http://rustfs:9000`)를 그대로 쓰므로 외부에 노출되는 것은 이 public URL뿐이다.

API→Dagster GraphQL 호출은 docker 내부망(`http://dagster:12702`,
`KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL`)을 쓰므로 public 도메인을 추가하지 않는다.

- `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL` — 프론트(브라우저)가 호출할 kor-travel-geo
  REST API 주소(주소→좌표 lookup 등). **build-time inline**이라 변경 시 재빌드.
- `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL` — 백엔드(API/Dagster)의 server-side 정/역
  지오코딩 보강 주소. **비우면 geocoding이 꺼져 좌표만 적재**한다. geo가 같은 docker
  호스트에 있으면 `http://host.docker.internal:12501`이 프록시 왕복을 피해 더 효율적이다.
  geo console(`<geo-console-host>`, `:12505`)은 운영 콘솔 reverse-proxy 라우트일 뿐
  앱 env가 아니다.

## 보안 경계

`kor-travel-map-admin`은 ADR-005에 따라 코드 레벨 인증을 넣지 않는다. 외부 노출이
필요하면 Cloudflare Tunnel, SSO 게이트웨이, VPN, IP allowlist 같은 네트워크 계층에서
보호한다.

Docker compose의 host publish는 기본 `KOR_TRAVEL_MAP_DOCKER_BIND_HOST=127.0.0.1`로
localhost에만 열린다. API, Dagster, RustFS console처럼 코드 인증이 없는 운영 surface를
외부 interface에 열어야 하는 배포는 위 네트워크 보호가 먼저 완료된 뒤
`KOR_TRAVEL_MAP_DOCKER_BIND_HOST=0.0.0.0`을 명시한다.

## 이관된 결정 (구 ADR)

- 로컬/개발/compose 기본 포트는 API `12701` · Dagster `12702` · admin UI `12705` ·
  Postgres host `5432`(container도 `5432`, standalone publish 기본값 `15432`) ·
  의존 대상 kor-travel-geo `12501`/`12505`로 고정한다 — 외부 OpenAPI 경계, Windows
  Playwright, WSL 서버, Docker compose가 같은 주소를 바라보게 하기 위함이다(구 ADR-047,
  위 §서비스에서 결정). 추가로 `scripts/stop-fixed-ports.sh`가 기동 전 `12701`/`12705`/
  `12702` listener를 종료해 stale Next.js/uvicorn/Dagster 프로세스가 검증을 오염시키지
  않게 한다(`npm run ports:stop`) (구 ADR-047).
- `.env`의 provider service key 이름은 그대로 두고, `scripts/load-env.sh`와
  `docker-compose.yml`이 실행용 `KOR_TRAVEL_MAP_API_*`/`NEXT_PUBLIC_*` 이름으로 한 번
  매핑한다(평문 키는 git 미커밋) — provider repo별 키 이름이 이미 다르므로 표준 env
  이름으로 매핑하면 운영 실수가 준다(구 ADR-047, 위 §환경변수에서 결정).
- Docker image는 `linux/amd64`(N150 16GB)와 `linux/arm64`(Odroid M1S)를 같은 tag로
  buildx 빌드하고, DB HA(streaming replication·자동 failover·VIP/DNS 전환·RustFS 다중
  노드 복제)는 범위 밖으로 두며 운영 DB 복구성은 cold backup/restore와 hot-swap restore
  훈련으로 확인한다 — 같은 manifest여야 두 노드 배포 절차가 갈라지지 않고, DB HA는 운영
  토폴로지 확정 후 별도로 다루는 편이 낫기 때문이다(구 ADR-056, 위 §T-108에서 결정).
- admin UI(`kor-travel-map-admin`)는 디버그 전용을 넘어 프로덕션 admin/유지보수 운영
  surface로 확장하되, 인증 로직은 코드에 넣지 않고 네트워크 계층(Cloudflare Tunnel/SSO/
  IP allowlist + bind host 기본 `127.0.0.1`)에서만 보호한다 — 별도 admin 앱을 만들면
  인증·DB·디버깅이 중복되고, 인증을 코드에서 떼면 인프라 보안 정책이 바뀌어도 코드를
  고칠 필요가 없기 때문이다(구 ADR-035, 위 §보안 경계에서 결정). 프로덕션에서 노출되는
  라우터는 prefix를 `/admin/...`·`/ops/...`(운영)와 `/debug/...`(디버그)로 분리하고,
  운영 라우터는 읽기 우선 + 쓰기는 explicit confirmation을 요구한다(구 ADR-035).

## 아직 남은 운영 확장

- Dagster provider public client live fetcher 실제 연결(T-RV-04b).
- staging restore smoke/count check와 hot-swap 자동 실행.
- T-RV-19/20/21 및 offline-upload 후속처럼 router/schema/운영 hardening에 남은 항목.
- 자동 failover, Postgres streaming replication, RustFS 다중 노드 복제는 T-108 범위 밖이다.
  현재 T-108은 deterministic multi-platform build까지를 닫는다.
