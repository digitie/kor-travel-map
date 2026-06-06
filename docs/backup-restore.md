# 백업/복구 runbook

본 문서는 ADR-040과 ADR-045 D-5 기준 `python-krtour-map` standalone Docker app의
백업/복구 절차다. 백업 단위는 TripMate와 분리된 **3종 묶음**이다.

- 애플리케이션 Postgres DB: `krtour_map`
- Dagster metadata Postgres DB: `krtour_map_dagster`
- RustFS 객체 저장소 볼륨: feature file bucket `krtour-map`, offline upload bucket
  `krtour-uploads`

현재 구현 범위는 `T-209e-a` cold backup 스크립트, `T-209e-b` staging cold restore
자동화, `T-209e-c` admin router/UI다. Admin UI는 `/admin/backups`에서 artifact 목록,
backup/restore command plan, staging restore 후 hot-swap 수동 승인 경계를 보여준다.
host command 실행은 기본 비활성(`KRTOUR_MAP_ADMIN_BACKUP_COMMAND_ENABLED=false`)이며,
운영자가 명시 opt-in할 때만 API에서 스크립트를 실행한다.

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

## 5. staging cold restore 자동화

`npm run docker:restore`는 백업 산출물을 운영 대상이 아닌 staging 대상에 복원한다.
기본 대상은 다음과 같다.

| 구성요소 | 기본 restore 대상 |
|----------|-------------------|
| app DB | `krtour_map_restore` |
| Dagster metadata DB | `krtour_map_dagster_restore` |
| RustFS data | Docker volume `krtour-map-rustfs-restore` |

```bash
npm run docker:restore -- <backup_id>
# 또는
KRTOUR_MAP_RESTORE_BACKUP_ID=<backup_id> npm run docker:restore
```

스크립트는 먼저 `meta/SHA256SUMS`를 검증한 뒤 `pg_restore --clean --if-exists
--no-owner --no-privileges`로 두 DB를 복원하고, `rustfs/rustfs-data.tar.gz`를 staging
Docker volume에 푼다. 기존 staging 대상이 있으면 기본적으로 중단한다. 의도적으로
새로 만들 때만 다음 opt-in을 사용한다.

```bash
KRTOUR_MAP_RESTORE_BACKUP_ID=<backup_id> \
KRTOUR_MAP_RESTORE_RECREATE=1 \
npm run docker:restore
```

대상 이름은 staging 환경별로 바꿀 수 있다.

```bash
KRTOUR_MAP_RESTORE_BACKUP_ID=<backup_id> \
KRTOUR_MAP_RESTORE_APP_DB=krtour_map_restore_20260606 \
KRTOUR_MAP_RESTORE_DAGSTER_DB=krtour_map_dagster_restore_20260606 \
KRTOUR_MAP_RESTORE_RUSTFS_VOLUME=krtour-map-rustfs-restore-20260606 \
npm run docker:restore
```

스크립트는 `KRTOUR_MAP_RESTORE_APP_DB == KRTOUR_MAP_POSTGRES_DB` 또는
`KRTOUR_MAP_RESTORE_DAGSTER_DB == KRTOUR_MAP_DAGSTER_POSTGRES_DB`이면 즉시 실패한다.
운영 DB에 직접 `--clean` restore를 실행하는 경로는 제공하지 않는다.

## 6. staging restore 검증

복원 뒤에는 staging DB/volume을 사용하는 별도 env 파일이나 compose project에서 API를
띄운 뒤 `docs/runbooks/docker-app.md` §6 smoke를 수행한다. 운영 stack의 DSN/volume을
staging 대상으로 바꾸기 전까지 TripMate는 영향받지 않는다.

간단한 DB 검증 예:

```bash
docker compose exec -T postgres psql -U krtour_map -d krtour_map_restore -c '\dt feature.*'
docker compose exec -T postgres psql -U krtour_map -d krtour_map_dagster_restore -c '\dt'
docker run --rm -v krtour-map-rustfs-restore:/data alpine:3.20 \
  sh -c "find /data -maxdepth 2 -type f | sed -n '1,40p'"
```

## 7. Admin API/UI

Admin API는 다음 경로를 제공한다.

- `GET /admin/backups` — `data/backups/<backup_id>` artifact + manifest 목록.
- `GET /admin/backups/{backup_id}` — artifact 단건 상세.
- `POST /admin/backups` — backup command plan 생성. `execute=true`는
  `KRTOUR_MAP_ADMIN_BACKUP_COMMAND_ENABLED=true`일 때만 실행.
- `POST /admin/restore/{backup_id}` — staging restore command plan 생성. 기본 target은
  `krtour_map_restore`, `krtour_map_dagster_restore`,
  `krtour-map-rustfs-restore`.
- `POST /admin/restore/{backup_id}/swap` — 자동 switch를 수행하지 않고 수동 hot-swap
  승인 경계를 반환한다.

## 8. 구현 잔여

다음 항목은 아직 구현하지 않았다.

- ADR-039 advisory lock 기반 `backup`/`restore` critical section.
- staging DB restore 후 API smoke/count check 자동화.
- 운영 DSN/volume hot-swap 자동 실행. 현재는 UI/API에서 manual-required 상태만 반환한다.
