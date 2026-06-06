# 배포 메모

본 문서는 ADR-045/047 기준 독립 krtour-map app 배포의 현재 1차 기준이다. 상세 운영
자동화는 후속 T-209b/T-209e에서 확장한다. `T-209e-a/b` 기준 cold backup script와
staging restore script/runbook은 제공되며, admin router/hot-swap UI는 후속이다.

## 서비스

| 서비스 | 기본 포트 | 역할 |
|--------|-----------|------|
| `api` | `9011` | `krtour-map-admin` FastAPI, OpenAPI/admin/debug/ops 라우터 |
| `frontend` | `9012` | Next.js admin UI |
| `dagster` | `9013` | krtour-map-owned Dagster UI/code location |
| `postgres` | host `15433`, container `5432` | 독립 `krtour_map` PostGIS DB |
| `rustfs` | API `9003`, console `9004` | S3 호환 객체 저장소(선택, backup 대상) |

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

백업 대상은 TripMate와 분리된 `krtour_map` app DB, `krtour_map_dagster` Dagster
metadata DB, RustFS volume의 3종 묶음이다. cold backup은 write path를 멈춘 뒤 실행한다.

```bash
docker compose stop api frontend dagster dagster-daemon rustfs
npm run docker:backup
npm run docker:restore -- <backup_id>
```

restore 기본 대상은 `krtour_map_restore`, `krtour_map_dagster_restore`,
`krtour-map-rustfs-restore`라 운영 DB/volume에 직접 쓰지 않는다. 산출물과 검증 절차는
`docs/backup-restore.md`를 따른다.

## 환경변수

`.env`는 배포 환경의 secret store, systemd `EnvironmentFile`, 또는 Docker secret로
관리한다. git에는 `.env.example`만 둔다. provider key는 기존 provider repo 이름을
그대로 둘 수 있고, `scripts/load-env.sh`/`docker-compose.yml`이 실행용
`KRTOUR_MAP_ADMIN_*` 이름으로 매핑한다.
로컬 Docker/venv 기본 Postgres host 포트는 `15433`이며, `KRTOUR_MAP_PG_DSN`을
명시하지 않으면 `scripts/load-env.sh`가 `127.0.0.1:15433/krtour_map` DSN을 채운다.

## 보안 경계

`krtour-map-admin`은 ADR-005에 따라 코드 레벨 인증을 넣지 않는다. 외부 노출이
필요하면 Cloudflare Tunnel, SSO 게이트웨이, VPN, IP allowlist 같은 네트워크 계층에서
보호한다.

## 아직 남은 운영 확장

- Dagster provider public client live fetcher 실제 연결(T-RV-04b).
- RustFS/객체 저장소를 포함한 admin restore router, hot-swap UI.
- T-RV-19/20/21 및 offline-upload 후속처럼 router/schema/운영 hardening에 남은
  항목.
