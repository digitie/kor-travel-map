# 백업/복구 runbook

본 문서는 ADR-040과 ADR-045 D-5 기준 `python-krtour-map` standalone Docker app의
백업/복구 절차다. 백업 단위는 TripMate와 분리된 **3종 묶음**이다.

- 애플리케이션 Postgres DB: `krtour_map`
- Dagster metadata Postgres DB: `krtour_map_dagster`
- RustFS 객체 저장소 볼륨: feature file bucket `krtour-map`, offline upload bucket
  `krtour-uploads`

현재 구현 범위는 `T-209e-a` cold backup 스크립트와 검증 절차다. restore 자동화,
admin router(`/admin/backups`, `/admin/restore/*`), hot-swap UI는 후속
`T-209e-b/c`에서 구현한다.

## 1. 전제

백업 스크립트는 `docker compose` standalone stack을 기준으로 동작한다. Postgres
서비스는 `pg_dump`를 위해 실행 중이어야 하지만, 일관된 cold snapshot을 위해 write
path는 먼저 멈춘다.

```bash
docker compose stop api frontend dagster dagster-daemon rustfs
```

`postgres`는 멈추지 않는다. RustFS는 멈춘 뒤 같은 named volume을
`rustfs-perms` service로 읽어 tar archive를 만든다.

실행 셸은 WSL 또는 Git Bash를 사용한다. PowerShell에서는 직접 `.sh`를 실행하지 않고
WSL에 위임한다.

```powershell
wsl bash -lc "cd /mnt/f/dev/python-krtour-map-codex && npm run docker:backup"
```

## 2. 백업 실행

기본 명령은 다음과 같다.

```bash
npm run docker:backup
# 내부 실행: bash scripts/docker-backup.sh
```

기본 저장 위치는 `data/backups/<UTC timestamp>/`다. 경로와 backup id는 환경변수로
고정할 수 있다.

```bash
KRTOUR_MAP_BACKUP_ROOT=/mnt/f/dev/python-krtour-map/data/backups \
KRTOUR_MAP_BACKUP_ID=manual-20260605-standalone \
npm run docker:backup
```

write service가 실행 중이면 스크립트는 기본적으로 중단한다. 운영자가 의도적으로
best-effort snapshot을 남길 때만 다음 opt-in을 사용한다.

```bash
KRTOUR_MAP_BACKUP_ALLOW_RUNNING=1 npm run docker:backup
```

## 3. 산출물 구조

백업 디렉터리는 다음 파일을 가진다.

```text
data/backups/<backup_id>/
  postgres/krtour_map.dump
  postgres/krtour_map_dagster.dump
  rustfs/rustfs-data.tar.gz
  meta/manifest.json
  meta/SHA256SUMS
```

`manifest.json`은 backup id, 생성 시각, DB 이름, RustFS bucket 이름, 파일 상대 경로를
담는다. `SHA256SUMS`는 세 산출물의 무결성 검증용이다.

## 4. 검증

체크섬은 백업 디렉터리에서 검증한다.

```bash
cd data/backups/<backup_id>
sha256sum -c meta/SHA256SUMS
```

Postgres dump는 list 단계로 읽기 가능한지 확인한다.

```bash
pg_restore --list postgres/krtour_map.dump >/tmp/krtour-map-app.list
pg_restore --list postgres/krtour_map_dagster.dump >/tmp/krtour-map-dagster.list
```

RustFS archive는 파일 목록을 열어 확인한다.

```bash
tar tzf rustfs/rustfs-data.tar.gz | sed -n '1,40p'
```

## 5. 수동 cold restore 절차

restore 자동화가 들어오기 전에는 운영 환경에 바로 덮어쓰지 않는다. 새 staging 환경이나
비어 있는 로컬 compose volume에서 먼저 복원한 뒤 smoke를 수행한다.

1. API, frontend, Dagster daemon/webserver, RustFS를 모두 멈춘다.
2. Postgres에 접속해 대상 DB를 새로 만든다. 기존 운영 DB에 직접 `--clean` restore를
   실행하지 않는다.
3. `pg_restore --clean --if-exists --no-owner --no-privileges`로
   `postgres/krtour_map.dump`와 `postgres/krtour_map_dagster.dump`를 각각 복원한다.
4. RustFS named volume을 비운 staging container에
   `tar xzf rustfs/rustfs-data.tar.gz -C /data`로 풀어 넣는다.
5. `docker compose up -d postgres rustfs rustfs-init api frontend dagster
   dagster-daemon`으로 기동하고 `docs/runbooks/docker-app.md` §6 smoke를 실행한다.

## 6. 구현 잔여

다음 항목은 아직 구현하지 않았다.

- `src/krtour/map/infra/backup.py`와 ADR-039 advisory lock 기반 `backup`/`restore`
  critical section.
- `packages/krtour-map-admin/src/krtour/map_admin/routers/admin_backups.py`.
- `GET /admin/backups`, `POST /admin/backups`, `POST /admin/restore/{backup_id}`,
  `POST /admin/restore/{backup_id}/swap`.
- staging DB restore 후 API smoke/count check와 hot-swap UI.
