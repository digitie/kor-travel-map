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
| `postgres` | standalone host `5432` · **n150 prod `12700`** | 독립 `kor_travel_map` PostGIS DB. 아래 ⚠️ |
| `rustfs` | API `12101`, console `12105` | S3 호환 객체 저장소(선택, backup 대상) |

> ⚠️ **postgres 포트는 배포 형태에 따라 다르다.**
>
> | 형태 | 포트 | listen | 비고 |
> |---|---|---|---|
> | 저장소 standalone compose | `5432` | 컨테이너 기본 | 로컬 개발·CI |
> | **n150 prod** | **`12700`** | **`127.0.0.1` 전용** | `kor-travel-map-postgres`, host network |
>
> prod는 두 단계로 옮겼다. 2026-08-15 커토버(#46)가 kor-travel-geo와 공유하던
> 인스턴스에서 map 전용 인스턴스(`12703`)로 뺐고, 2026-08-17에 **네 프로젝트를 각각
> 전용 인스턴스로 나누면서** 포트를 대역 규칙에 맞춰 `12700`으로 옮겼다.
>
> **왜 DB만 나누는 것으로 부족했나** — role·ACL·확장은 DB가 아니라 **cluster 전역**이라
> DB를 나눠도 principal이 격리되지 않는다. map을 전용 인스턴스로 옮긴 뒤에도 통합
> 인스턴스에 `ktm_` 역할 7개가 남아 있었고, map migrator 자격증명으로
> `kor_travel_geo`(33GB)에 실제로 접속됐다. 같은 이유가 docker-manager ADR-35가
> map을 분리한 근거였고, 그 근거는 concierge·pinvi에도 그대로 적용된다.
>
> ⚠️ **prod에 `5432`를 듣는 것은 이제 없다.** 옛 문서를 보고 `5432`로 붙으면 연결
> 자체가 실패한다(예전에는 조용히 geo 인스턴스에 붙었다). 자세히는
> `docs/integration-map.md`.

**호스트 `12xxx` 대역 배치**(2026-08-17 n150 실측). 새 포트를 잡을 때는 자기 프로젝트의
100번대 안에서 고른다 — 대역을 넘으면 다른 프로젝트와 충돌한다.

| 대역 | 소유 | 사용 중 |
|---|---|---|
| `121xx` | RustFS | 12101 S3 · 12105 console |
| `122xx` | Grafana | 12205 |
| `123xx` | cAdvisor | 12301 |
| `124xx` | Prometheus | 12401 |
| `125xx` | kor-travel-geo | **12500 postgres** · 12501 api · 12502 dagster · 12505 ui |
| `126xx` | kor-travel-concierge | **12600 postgres** · 12601 api · 12602 mcp · 12605 web |
| **`127xx`** | **kor-travel-map** | **12700 postgres** · 12701 api · 12702 dagster · 12705 ui |
| `128xx` | PinVi | **12800 postgres** · 12801 api · 12802 dagster · 12805 web |
| `129xx` | kor-travel-docker-manager 자체 | 12901 api · 12905 web |

**DB는 각 대역의 `x00`이다** (2026-08-17). 프로젝트마다 전용 PostgreSQL 인스턴스를
쓰며, 통합 인스턴스는 없다. 새 포트를 잡을 때는 자기 프로젝트의 100번대 안에서 고른다.

Prometheus 성능 메트릭은 별도 포트를 열지 않고 `api`의 같은 host 포트 `12701`에서
`GET /metrics`로 노출한다. 이 endpoint는 공개 REST(`/v1/features`·`/v1/categories`·
`/v1/providers`·`/v1/public`), `/admin`, `/ops`, `/debug`, system route의 HTTP 요청
수/지연 시간/응답 크기/예외와 DB query 수/지연 시간을 함께 제공한다.
`kor-travel-docker-manager` 관측 스택은 Grafana `12205`, cAdvisor Exporter
`12301`, Prometheus `12401`을 사용한다. 앱은 Prometheus로 능동 연결하지 않고
pull scrape 대상이 된다.

`/metrics`는 scrape identity 경계다(ADR-066 결정 4, T-VN-02).
`KOR_TRAVEL_MAP_API_METRICS_TOKEN`이 설정되면 `Authorization: Bearer <token>`이
일치해야 하고, production profile은 metrics endpoint 활성 시 이 token(앞뒤 공백
없는 32자 이상, admin secret·service/ops token과 다른 값)을 필수화한다 —
compose는 host env `KOR_TRAVEL_MAP_API_METRICS_TOKEN`을 hard-require로 전달한다.
token 미설정 local-dev는 기존 open scrape를 유지한다.

> **현재 상태(중요)**: `kor-travel-docker-manager`의
> `config/prometheus/prometheus.yml`에는 아직 **map-api(:12701) scrape job이
> 없다**(현재 job은 prometheus·cadvisor·kor-travel-geo-api/ui뿐). 즉 위 12701
> scrape는 "목표"이며, 이 배포에서 **인증과 함께 job을 신규 추가**해야 한다.

**배포 전제 — zero-gap 순서(반드시 이 순서로)**:

1. **먼저** kor-travel-docker-manager에 git 밖의 전용 secret 파일을 read-only로
   mount하고, Prometheus scrape config에 map-api job을 `credentials_file`과 함께
   **추가**한다. 변경 전 API(현재 `/metrics` 무인증)는 이 헤더를 무시하므로 이
   단계는 무해하다. 아래 host secret 파일은 `chmod 600`으로 관리하고 repository
   안에 만들지 않는다. 추적 중인 `config/prometheus/prometheus.yml`의
   `credentials:`에 실제 token을 직접 쓰면 안 된다.

   ```yaml
   - job_name: kor-travel-map-api
     metrics_path: /metrics
     authorization:
       type: Bearer
       credentials_file: /run/secrets/kor_travel_map_metrics_token
     static_configs:
       - targets:
           - 127.0.0.1:12701
   ```

   docker-manager compose에는 예를 들어 host의
   `/etc/kor-travel-map/secrets/metrics-token`을 위 container 경로에 read-only로
   mount해야 한다. 이 mount가 없는 현재 docker-manager 상태에서는 배포하지 않고
   선행 변경으로 먼저 반영한다.

2. **그다음** root `.env`에 `KOR_TRAVEL_MAP_API_METRICS_TOKEN`(secret 파일과
   같은 값)을 넣고 API를 배포한다.

순서를 뒤집으면(토큰 먼저, scrape config 나중) 그 사이 scrape가 401로 gap이
생긴다 — 조용한 유실이 아니라 scrape 실패로 드러난다.

`kor-travel-docker-manager`가 인프라를 이미 구동하는 환경에서는 kor-travel-map의
local `postgres`/`rustfs` 서비스를 함께 띄우면 포트가 충돌한다. 이때는
`KOR_TRAVEL_MAP_INFRA_EXTERNAL=true bash scripts/docker-up.sh`를 사용해 API, Web UI,
Dagster만 올리고, 컨테이너는 docker-manager가 띄운 인프라에 연결한다.

⚠️ **연결 대상 포트는 `5432`가 아니다.** docker-manager는 2026-08-17부터 프로젝트별
전용 PostgreSQL을 띄우며 map의 DB는 **`12700`**이다(위 대역표). RustFS만 `12101`로
그대로다. 옛 문서를 보고 `host.docker.internal:5432`로 붙으면 연결 자체가 실패한다 —
그 포트를 듣는 것이 없다.

`api`, `frontend`, `dagster`는 Docker compose healthcheck를 가진다. `frontend`는
`api`의 `service_healthy` 이후 시작한다.

## 최소 배포 절차

```bash
cp .env.example .env
chmod 600 .env
cp packages/kor-travel-map-api/.env.example packages/kor-travel-map-api/.env
chmod 600 packages/kor-travel-map-api/.env
npm run docker:build
npm run docker:up
```

스모크는 `docs/runbooks/docker-app.md` §6을 따른다.

> **dev vs prod**: 위 `npm run docker:*`는 **이 저장소에서 직접 띄우는 dev/standalone
> 경로**다(기본 Docker host 네트워크 + `127.0.0.1`의 12xxx 고정 포트 + 포트 가드 —
> `docs/dev-environment.md` §0). **prod는 `kor-travel-docker-manager`로 기동하고 공식
> 도메인(reverse proxy, 아래 §프로덕션 도메인)을 적용한다.** 별도 지시가 없으면 dev를
> 의미한다. host 모드를 끄려면 `KOR_TRAVEL_MAP_DOCKER_NETWORK=bridge`.
frontend 이미지는 루트 `package-lock.json`과 exact npm 12.0.1의 clean `npm ci`로 재현 가능한
workspace 의존성 설치를 사용한다. install은 Redocly patch, `npm ls --all --json`
0-problem tree-integrity verifier, 실제 Next/Sharp optimizer smoke까지 통과해야 한다.

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

## vNext write-fence cutover와 rollback (ADR-075)

vNext schema/API 전환은 일반 image 교체가 아니라 데이터 보존 작업이다. 배포 전 정본·감사·파생
데이터를 분류하고, production clone에서 restore/PITR 또는 forward journal replay와 shadow
checksum을 검증한다. upstream 재수집은 닫힌 feed, quota, 3년 weather 이력을 복원하지 못하므로
정본 복구책으로 인정하지 않는다.

배포 순서는 다음과 같다.

1. target ADR·DDL·OpenAPI SHA와 KTM/PinVi compatible commit pair를 freeze한다.
2. PinVi typed consumer를 비활성 상태로 선배포하고 contract smoke를 통과시킨다.
3. write fence를 열기 전에 background writer, Dagster, API mutation, outbox relay를 모두 식별한다.
4. fence 또는 검증된 delta capture를 활성화하고 drain 뒤 backup/checksum을 남긴다.
5. shadow backfill 검증 후 KTM DB/API를 전환하고 PinVi 기능을 활성화한다.
6. 양방향 smoke와 reconciliation을 통과한 뒤 soak한다. legacy column/table/alias 제거는 별도 PR이다.

Rollback은 fence 이후 write가 없을 때만 old snapshot restore를 허용한다. write가 있었다면 PITR 또는
forward journal로 해당 delta를 이전 schema에 적용하고 checksum을 다시 맞춘 뒤 writer를 연다.
복구 경로가 검증되지 않았거나 어느 쪽 identity/lineage라도 불일치하면 서비스를 read-only로 유지하고
forward-fix한다. lock acquisition timeout과 실제 중단 시간은 별도로 기록한다.

## T-VN-33 (0084~0091) 배포 — 단발·forward-only

prod alembic head는 `0083`이고 `0084`~`0091`이 한 번에 올라간다. 되돌리는 revision은
없다(`0090`/`0091`의 `downgrade()`가 `RuntimeError`를 던진다). 아래는 이 구간에만
해당하는 사항이며, 위 ADR-075 절차와 함께 읽는다.

**중간 커밋 지점이 하나 있다.** `0090`이 concurrent index를 만들려고
`autocommit_block()`에 들어가는데, 이때 바깥 트랜잭션이 커밋된다. 그 시점의
`alembic_version`은 아직 `0089`다. 따라서 이후 `0091`이 실패하면 **`0084`~`0090`의
DDL은 남고 stamp만 `0089`인** 상태가 된다. 재시도는 `0090`부터 다시 도는 것을
전제로 하며, `0090`의 DDL은 모두 그 재실행에 안전하도록 작성돼 있다
(constraint는 `DROP ... IF EXISTS` 선행, index는 `DROP INDEX CONCURRENTLY IF EXISTS`
선행, `ADD COLUMN`은 `IF NOT EXISTS`). **`alembic_version`을 손으로 고치지 말 것** —
그대로 `alembic upgrade head`를 다시 실행하면 된다.

**`0091`은 중단될 수 있고, 그 경우 통째로 롤백된다.** `0091`은 preflight 4개를 갖고
있고 어느 하나라도 걸리면 `RAISE`한다. `0091`에는 `autocommit_block`이 없으므로
그 revision의 작업은 전부 되돌아간다(위의 `0090`까지는 남는다). preflight가 걸리면
메시지의 `HINT`가 지시하는 데이터를 정리한 뒤 재시도한다. 대표적으로:

- `source_links.is_primary_source`와 `source_role='primary'`가 어긋난 행 → 어느 쪽이
  옳은지 판단해 `source_role`을 맞춘다(살아남는 열이다).
- offline upload의 scope가 refresh operation 둘 이상으로 해석되는 경우 → upload에
  operation을 명시한다.

**긴 lock을 잡는 구간.** `0089`가 `source_entities` 전 행을 UPDATE하고(실측 731k /
359MB) 조건에 따라 `source_records`(733k / 1.25GB)를 재작성한다. `0090`은 두 테이블에
non-concurrent UNIQUE를 만든다. 유지보수 창에서 돌린다.

## 환경변수

루트 `.env`와 API 전용 `packages/kor-travel-map-api/.env`는 배포 환경의 secret store,
systemd `EnvironmentFile`, 또는 Docker secret로 관리한다. git에는 각 `.env.example`만
둔다. provider key는 루트 파일에 기존 provider repo 이름을 그대로 둘 수 있고,
`scripts/load-env.sh`/`docker-compose.yml`이 Dagster 실행용 이름으로 매핑한다. API auth,
route, backup, CORS, metrics 설정은 API 전용 파일에만 둔다. 이 파일이 없으면 Compose는
인증 기본값으로 기동하지 않고 실패한다.
공식 standalone compose에서 `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED` 미설정 값은 `false`다.
파괴적 조작이 필요한 standalone Compose는 shell 또는 root project `.env`의 interpolation
입력으로 `true`를 명시한다. package API `.env`의 같은 값은 service `environment`에 의해
덮이므로 Compose opt-in 근거가 아니다. Docker Manager가 소유하는 승인된 production 형상은
canonical API service에 literal `true`를 주입한 뒤 raw/resolved/runtime 검증으로 이를 증명한다.
라이브 조작의 actor는 admin BFF 인증 principal로 별도 감사된다.
PC 개발 환경에서 host `5432`는 `kor-travel-docker-manager`가 소유한
공유 PostgreSQL/PostGIS 서버 인스턴스다. `scripts/load-env.sh`는 bootstrap owner로
`KOR_TRAVEL_MAP_PG_DSN`을 합성하지 않는다. API/Dagster runtime, Alembic migrator,
Dagster metadata DSN은 각각 ignored deployment env 또는 vault에 명시해야 하며 누락한
Compose 기동은 fail-closed 한다. 외부 DB/infra overlay는 ownership bootstrap을 자동 실행하지
않으므로 dedicated map DB의 role·ownership transfer도 운영자가 사전 provision한다.
bootstrap은 PostgreSQL system object까지 건드리는 `REASSIGN OWNED`를 쓰지 않고 map application
object만 명시 transfer한다. API entrypoint는 Alembic 뒤 migrator `SET ROLE` 경로로 runtime ACL
inventory를 재조정한다. `ALTER DEFAULT PRIVILEGES` fallback은 없으므로 state/audit future table이
runtime DML을 자동으로 얻지 않는다.
공유 DB만 쓰고 RustFS는 local compose로 띄우는 Docker 기동은
`KOR_TRAVEL_MAP_DB_EXTERNAL=true`
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

운영 노드의 root `.env`와 API 전용 `packages/kor-travel-map-api/.env`에 나누어 채우는 값:

- `NEXT_PUBLIC_KOR_TRAVEL_MAP_API` / `NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL` —
  프론트(브라우저)가 호출할 API/Dagster 주소. **Next.js build-time inline**이라 도메인을
  바꾸면 frontend 이미지를 **재빌드**한다(`npm run docker:build`).
- API 전용 `.env`의 `KOR_TRAVEL_MAP_API_CORS_ALLOW_ORIGINS` — 프론트 origin(예:
  `["https://<map-host>"]`)을 허용해야 브라우저 cross-origin fetch가 통과한다. root
  `.env` 값은 API container로 전달하지 않으며, API 전용 파일의 기본값은 localhost(`:12705`)다.
- `KOR_TRAVEL_MAP_OBJECT_STORE_PUBLIC_BASE_URL` — feature 파일/업로드 이미지의 **브라우저
  노출 주소**(`https://<s3-api-host>/<bucket>`). API 컨테이너→RustFS 내부 통신은 docker
  네트워크(`http://rustfs:9000`)를 그대로 쓰므로 외부에 노출되는 것은 이 public URL뿐이다.

API→Dagster GraphQL 호출은 docker 내부망(`http://dagster:12702`,
`KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL`)을 쓰므로 public 도메인을 추가하지 않는다.

- `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL` — 프론트(브라우저)가 호출할 kor-travel-geo
  REST API 주소(주소→좌표 lookup 등). **build-time inline**이라 변경 시 재빌드.
- `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY` — 프론트(브라우저)의 kor-travel-geo v2 호출용
  VWorld 호환 형식의 `key` query 값. geo가 Map frontend consumer에 발급한 전용 키를
  넣으며 `NEXT_PUBLIC_VWORLD_API_KEY`를 대입하지 않는다.
- `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL` — 백엔드(API/Dagster)의 server-side 정/역
  지오코딩 보강 주소. **비우면 geocoding이 꺼져 좌표만 적재**한다. geo가 같은 docker
  호스트에 있으면 `http://host.docker.internal:12501`이 프록시 왕복을 피해 더 효율적이다.
- `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY` — 백엔드(API/Dagster/CLI)의
  kor-travel-geo public endpoint key. URL query가 아니라 `X-KTG-API-Key` header로만
  보내며 geo admin trusted-proxy secret/role은 Map에 주입하지 않는다.
  `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`와 같은 geo-issued consumer credential을 별도
  server-only env에 주입할 수 있지만 VWorld provider key로 fallback하지 않는다.
  geo console(`<geo-console-host>`, `:12505`)은 운영 콘솔 reverse-proxy 라우트일 뿐
  앱 env가 아니다.

## 보안 경계

현재 `kor-travel-map-admin`은 ADR-060의 로그인/BFF와 네트워크 계층을 사용한다. vNext production은
ADR-066에 따라 route policy matrix와 필수 secret을 앱에서도 fail-closed로 검사하며, infra SSO,
VPN, IP allowlist는 그 위의 추가 경계다. debug/operator/raw route를 네트워크 보호만 믿고 열지 않는다.

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
- admin UI(`kor-travel-map-admin`)를 디버그 전용에서 프로덕션 admin/유지보수 surface로 확장한
  결정은 유지한다. 과거에는 네트워크 계층만으로 보호했지만 ADR-060의 로그인/BFF와 ADR-066의
  production fail-closed app gate가 이를 supersede했다. 네트워크 SSO/IP allowlist와 bind host
  기본 `127.0.0.1`도 defense-in-depth로 계속 사용한다. 프로덕션에서 노출되는
  라우터는 prefix를 `/admin/...`·`/ops/...`(운영)와 `/debug/...`(디버그)로 분리하고,
  운영 라우터는 읽기 우선 + 쓰기는 explicit confirmation을 요구한다(구 ADR-035).

## 아직 남은 운영 확장

- Dagster provider public client live fetcher 실제 연결(T-RV-04b).
- staging restore smoke/count check와 hot-swap 자동 실행.
- T-RV-19/20/21 및 offline-upload 후속처럼 router/schema/운영 hardening에 남은 항목.
- 자동 failover, Postgres streaming replication, RustFS 다중 노드 복제는 T-108 범위 밖이다.
  현재 T-108은 deterministic multi-platform build까지를 닫는다.
