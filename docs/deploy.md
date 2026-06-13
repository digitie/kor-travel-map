# 배포 메모

본 문서는 ADR-045/047 기준 독립 kor-travel-map app 배포의 현재 1차 기준이다. 상세 운영
자동화는 후속 T-209b/T-209e에서 확장한다. `T-209e-a/b/c` 기준 cold backup script,
staging restore script/runbook, admin backup/restore router와 plan-only UI가 제공된다.

## 서비스

| 서비스 | 기본 포트 | 역할 |
|--------|-----------|------|
| `api` | `12301` | `kor-travel-map-api` FastAPI, OpenAPI/public/admin/debug/ops 라우터 |
| `frontend` | `12305` | Next.js admin UI |
| `dagster` | `12302` | kor-travel-map-owned Dagster UI/code location |
| `postgres` | host `5432`, container `5432` | 독립 `kor_travel_map` PostGIS DB |
| `rustfs` | API `12101`, console `12105` | S3 호환 객체 저장소(선택, backup 대상) |

Prometheus 성능 메트릭은 별도 포트를 열지 않고 `api`의 같은 host 포트 `12301`에서
`GET /metrics`로 노출한다. 이 endpoint는 공개 REST(`/v1/features`·`/v1/categories`·
`/v1/providers`·`/v1/public`), `/admin`, `/ops`, `/debug`, system route의 HTTP 요청
수/지연 시간/응답 크기/예외와 DB query 수/지연 시간을 함께 제공한다.
`kor-travel-docker-manager` 관측 스택은 Prometheus `12601`, cAdvisor Exporter
`12602`, Grafana `12605`를 사용하며, Prometheus가
`http://<kor-travel-map-api>:12301/metrics`를 pull scrape한다. 앱이 Prometheus로 능동
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
frontend 이미지는 루트 `package-lock.json`과 `npm ci`로 재현 가능한 workspace
의존성 설치를 사용한다.

## 백업

백업 대상은 TripMate와 분리된 `kor_travel_map` app DB, `kor_travel_map_dagster` Dagster
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
로컬 Docker/venv 기본 Postgres host 포트는 `5432`이며, `KOR_TRAVEL_MAP_PG_DSN`을
명시하지 않으면 `scripts/load-env.sh`가 `127.0.0.1:5432/kor_travel_map` DSN을 채운다.

## 보안 경계

`kor-travel-map-admin`은 ADR-005에 따라 코드 레벨 인증을 넣지 않는다. 외부 노출이
필요하면 Cloudflare Tunnel, SSO 게이트웨이, VPN, IP allowlist 같은 네트워크 계층에서
보호한다.

Docker compose의 host publish는 기본 `KOR_TRAVEL_MAP_DOCKER_BIND_HOST=127.0.0.1`로
localhost에만 열린다. API, Dagster, RustFS console처럼 코드 인증이 없는 운영 surface를
외부 interface에 열어야 하는 배포는 위 네트워크 보호가 먼저 완료된 뒤
`KOR_TRAVEL_MAP_DOCKER_BIND_HOST=0.0.0.0`을 명시한다.

## 아직 남은 운영 확장

- Dagster provider public client live fetcher 실제 연결(T-RV-04b).
- staging restore smoke/count check와 hot-swap 자동 실행.
- T-RV-19/20/21 및 offline-upload 후속처럼 router/schema/운영 hardening에 남은
  항목.
