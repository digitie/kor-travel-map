# 백업/복구 runbook

본 문서는 ADR-040과 ADR-045 D-5 기준 `kor-travel-map` standalone Docker app의
백업/복구 절차다. 백업 단위는 TripMate와 분리된 **3종 묶음**이다.

- 애플리케이션 Postgres DB: `kor_travel_map`
- Dagster metadata Postgres DB: `kor_travel_map_dagster`
- RustFS 객체 저장소 볼륨: feature file bucket `kor-travel-map`, offline upload bucket
  `krtour-uploads`

현재 구현 범위는 `T-209e` cold backup, staging restore, smoke/count 검증,
admin router/UI, restore hot-swap env 전환 자동화다. Admin UI는 `/admin/backups`에서
artifact 목록, backup/restore/swap command plan을 보여준다. host command 실행은 기본
비활성(`KOR_TRAVEL_MAP_ADMIN_BACKUP_COMMAND_ENABLED=false`)이며, 운영자가 명시 opt-in할
때만 API에서 스크립트를 실행한다.

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
wsl bash -lc "cd /mnt/f/dev/kor-travel-map-codex && npm run docker:backup"
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
KOR_TRAVEL_MAP_BACKUP_ROOT=/mnt/f/dev/kor-travel-map/data/backups \
KOR_TRAVEL_MAP_BACKUP_ID=manual-20260605-standalone \
npm run docker:backup
```

write service가 실행 중이면 스크립트는 기본적으로 중단한다. 운영자가 의도적으로
best-effort snapshot을 남길 때만 다음 opt-in을 사용한다.

```bash
KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING=1 npm run docker:backup
```

`scripts/docker-backup.sh`, `scripts/docker-restore.sh`,
`scripts/docker-restore-swap.sh`는 `scripts/with-pg-advisory-lock.py`를 통해
PostgreSQL advisory lock `maintenance:backup-restore`를 잡고 실행된다. lock이 이미
잡혀 있으면 실행은 실패한다. 로컬 실험에서만 mutex를 의도적으로 끄려면
`KOR_TRAVEL_MAP_MAINTENANCE_LOCK_DISABLED=1`을 사용한다.

## 3. 산출물 구조

백업 디렉터리는 다음 파일을 가진다.

```text
data/backups/<backup_id>/
  postgres/kor_travel_map.dump
  postgres/kor_travel_map_dagster.dump
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
pg_restore --list postgres/kor_travel_map.dump >/tmp/kor-travel-map-app.list
pg_restore --list postgres/kor_travel_map_dagster.dump >/tmp/kor-travel-map-dagster.list
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
| app DB | `kor_travel_map_restore` |
| Dagster metadata DB | `kor_travel_map_dagster_restore` |
| RustFS data | Docker volume `kor-travel-map-rustfs-restore` |

```bash
npm run docker:restore -- <backup_id>
# 또는
KOR_TRAVEL_MAP_RESTORE_BACKUP_ID=<backup_id> npm run docker:restore
```

스크립트는 먼저 `meta/SHA256SUMS`를 검증한 뒤 `pg_restore --clean --if-exists
--no-owner --no-privileges`로 두 DB를 복원하고, `rustfs/rustfs-data.tar.gz`를 staging
Docker volume에 푼다. 복원이 끝나면 기본적으로 `scripts/docker-restore-verify.sh`를
호출해 staging DB/volume smoke/count를 확인한다. 기존 staging 대상이 있으면
기본적으로 중단한다. 의도적으로 새로 만들 때만 다음 opt-in을 사용한다.

```bash
KOR_TRAVEL_MAP_RESTORE_BACKUP_ID=<backup_id> \
KOR_TRAVEL_MAP_RESTORE_RECREATE=1 \
npm run docker:restore
```

대상 이름은 staging 환경별로 바꿀 수 있다.

```bash
KOR_TRAVEL_MAP_RESTORE_BACKUP_ID=<backup_id> \
KOR_TRAVEL_MAP_RESTORE_APP_DB=kor_travel_map_restore_20260606 \
KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB=kor_travel_map_dagster_restore_20260606 \
KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME=kor-travel-map-rustfs-restore-20260606 \
npm run docker:restore
```

스크립트는 `KOR_TRAVEL_MAP_RESTORE_APP_DB == KOR_TRAVEL_MAP_POSTGRES_DB` 또는
`KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB == KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB`이면 즉시 실패한다.
운영 DB에 직접 `--clean` restore를 실행하는 경로는 제공하지 않는다.

## 6. staging restore 검증

`scripts/docker-restore-verify.sh`는 staging app DB의 `feature.features` row count,
staging Dagster DB의 사용자 table count, staging RustFS volume file count를 출력한다.
restore script가 기본 호출하므로 별도 재검증이나 수동 restore 후 확인에만 직접 실행한다.

```bash
KOR_TRAVEL_MAP_RESTORE_APP_DB=kor_travel_map_restore \
KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB=kor_travel_map_dagster_restore \
KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME=kor-travel-map-rustfs-restore \
bash scripts/docker-restore-verify.sh
```

추가 API smoke는 staging DB/volume을 사용하는 env 파일이나 별도 compose project에서
API를 띄운 뒤 `docs/runbooks/docker-app.md` §6 절차를 수행한다. 운영 stack의 DSN/volume을
staging 대상으로 바꾸기 전까지 TripMate는 영향받지 않는다.

## 7. restore hot-swap env 전환

hot-swap은 운영 DB/volume을 삭제하거나 rename하지 않는다. 검증된 staging 대상 이름을
서비스 env override로 쓰는 `.env.restore-swap` 파일을 생성한 뒤, 필요하면 compose
서비스를 그 env로 다시 띄운다.

```bash
KOR_TRAVEL_MAP_RESTORE_APP_DB=kor_travel_map_restore \
KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB=kor_travel_map_dagster_restore \
KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME=kor-travel-map-rustfs-restore \
bash scripts/docker-restore-swap.sh
```

기본 실행은 `.env.restore-swap`만 만든다. 즉시 적용하려면 다음 opt-in을 사용한다.

```bash
KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY=1 bash scripts/docker-restore-swap.sh
```

생성되는 env는 다음 세 값을 덮어쓴다.

- `KOR_TRAVEL_MAP_DOCKER_PG_DSN`
- `KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL`
- `KOR_TRAVEL_MAP_RUSTFS_VOLUME`

`docker-compose.yml`의 RustFS named volume은 `KOR_TRAVEL_MAP_RUSTFS_VOLUME`으로 실제
Docker volume name을 바꿀 수 있게 되어 있다. 기본값은 기존
`kor-travel-map-rustfs`라서 일반 기동은 그대로 동작한다.

## 8. Admin API/UI

Admin API는 다음 경로를 제공한다.

- `GET /admin/backups` — `data/backups/<backup_id>` artifact + manifest 목록.
- `GET /admin/backups/{backup_id}` — artifact 단건 상세.
- `POST /admin/backups` — backup command plan 생성. `execute=true`는
  `KOR_TRAVEL_MAP_ADMIN_BACKUP_COMMAND_ENABLED=true`일 때만 실행.
- `POST /admin/restore/{backup_id}` — staging restore command plan 생성. 기본 target은
  `kor_travel_map_restore`, `kor_travel_map_dagster_restore`,
  `kor-travel-map-rustfs-restore`.
- `POST /admin/restore/{backup_id}/swap` — restore swap command plan 생성.
  `execute=true`, `apply=true`를 함께 쓰면 검증 후 env 전환과 compose 재기동까지 실행한다.

Admin API의 command 실행은 `KOR_TRAVEL_MAP_ADMIN_BACKUP_COMMAND_ENABLED=true`와 요청별
`execute=true`가 모두 있어야 한다. 따라서 기본 UI/API 사용은 plan-only이며, 운영자가
command/env를 확인한 뒤 명시적으로 실행한다.
