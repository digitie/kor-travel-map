# 백업/복구 runbook

본 문서는 ADR-040과 ADR-045 D-5 기준 `kor-travel-map` standalone Docker app의
백업/복구 절차다. 백업 단위는 외부 서비스와 분리된 **3종 묶음**이다.

- 애플리케이션 Postgres DB: `kor_travel_map`
- Dagster metadata Postgres DB: `kor_travel_map_dagster`
- RustFS 객체 저장소 볼륨: feature file bucket `kor-travel-map`, offline upload bucket
  `kor-travel-map-uploads`

현재 구현 범위는 `T-209e` cold backup, staging restore, smoke/count 검증,
admin router/UI, restore hot-swap env 전환 자동화다. Admin UI는 `/admin/backups`에서
artifact 목록, backup/restore/swap command plan을 보여준다. host command 실행은 기본
비활성(`KOR_TRAVEL_MAP_API_BACKUP_COMMAND_ENABLED=false`)이며, 운영자가 명시 opt-in할
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

이 opt-in 산출물은 진단용 best-effort snapshot이다. vNext cutover rollback 기준점으로 사용할 수
없다. rollback 기준점은 write fence 뒤 생성하고, fence 이후 write가 있으면 검증된 PITR 또는
forward journal replay를 함께 준비한다(ADR-075). upstream 재수집은 정본·감사·3년 weather 이력의
복구 수단이 아니다.

`scripts/docker-backup.sh`, `scripts/docker-restore.sh`,
`scripts/docker-restore-swap.sh`는 `scripts/with-pg-advisory-lock.py`를 통해
PostgreSQL advisory lock `maintenance:backup-restore`를 잡고 실행된다. lock이 이미
잡혀 있으면 실행은 실패한다. lock bypass 환경변수는 지원하지 않는다.

Admin API도 script wrapper 자체가 lock owner다. API connection이 잡은 lock을 env로
child에 위임하지 않는다. Docker daemon 작업은 local CLI 종료만으로 취소를 증명할 수 없으므로
effect 시작 뒤에는 non-interruptible supervised 작업이다. wrapper는 `SIGTERM`/`SIGINT`를
호출자 detach로만 기록하고 child에는 전달하지 않는다. stdout/stderr는 API pipe가 아니라
임시 파일에 spool하고 direct child와 child process group이 자연 terminal에 도달한 뒤에만
출력을 재생하고 lock을 해제한다.

API cancellation은 bounded하게 호출 task를 끝내고 timeout은
`504 BACKUP_COMMAND_TIMEOUT`을 반환하지만 wrapper communication은 background에서 계속된다.
DB execution phase는 `effect_started`에 남는다. 작업 중 동일 command를 재시도하면
`409 BACKUP_MAINTENANCE_BUSY`이고, host script가 create-once marker를 남긴 뒤 재시도하면
외부 효과를 반복하지 않고 marker proof로 `effect_succeeded`와 terminal response를 확정한다.
API worker가 종료돼도 새 session의 wrapper와 임시 spool은 child terminal까지 lock을 유지한다.
wrapper 자체를 `SIGKILL`하는 운영 개입은 이 보장을 우회하므로 정상 취소 절차가 아니다.
API 내부 delete의
filesystem `rmtree`는 같은 lock을 marker proof와 domain command terminal result commit까지
직접 보유한다. 경합은 무기한 대기하지 않고 `409 BACKUP_MAINTENANCE_BUSY`와
`Retry-After: 3`으로 실패한다.

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

Admin command 실행 때는 `data/backups/.domain-command-markers/command-<id>.json`도
생성한다. marker는 최초 완료 증거를 create-once로 보존하며 command/operation/effect/target,
request digest, manifest·`SHA256SUMS` 또는 restore/swap output digest와 UTC 완료 시각을
담는다. 전용 디렉터리 `0700`, 파일 `0600`, owner·regular-file·single-link 검증,
`O_NOFOLLOW|O_EXCL`, file/dir `fsync`, `renameat2(RENAME_NOREPLACE)`를 사용한다. exact
identity/proof가 아닌 기존 marker는 덮어쓰지 않고 중단한다.

호출자가 `backup_id`를 지정한 create는 artifact를 쓰기 전에
`command_id + input_digest + backup_id`를
`data/backups/<backup_id>/.domain-command-reservation.json`에 fsync하고 빈 `0700`
destination을 `RENAME_NOREPLACE`로 선점한다. exact reservation이 없는 기존 경로는 유효한
backup처럼 보여도 새 command가 채택하지 않는다. restore도 exact command/source marker가
없는 기존 DB·volume의 단순 health를 완료 provenance로 인정하지 않는다. marker 없는 재시도는
target이 없을 때만 실행하며 기존 target은 `recreate` 또는 명시적 운영자 reconciliation이
필요하다.

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
Docker volume에 푼다. `pg_restore`는 planner 통계를 보존하지 않으므로 각 DB 복원 직후
`vacuumdb --analyze-in-stages`를 완료해야 다음 단계로 진행한다. 복원이 끝나면 기본적으로
`scripts/docker-restore-verify.sh`를 호출해 staging DB/volume smoke/count와
`feature.features` 통계 생성을 확인한다. 기존 staging 대상이 있으면 기본적으로 중단한다.
의도적으로 새로 만들 때만 다음 opt-in을 사용한다.

process가 restore 완료와 marker 생성 사이에 종료되면 동일 command retry는 recovery mode로
실행된다. 대상 세 개가 모두 없으면 처음부터 안전하게 재개하고, 모두 있으면
`docker-restore-verify.sh`를 강제로 통과한 뒤 marker만 복구한다. 일부 target만 있으면
partial effect를 성공으로 추정하지 않고 실패한다(`recreate=1`은 전체를 다시 만드는 명시적
예외). API는 input-only marker를 합성하지 않는다.

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

`scripts/docker-restore-verify.sh`는 staging app DB의 `feature.features` row count와 planner
통계 존재 여부, staging Dagster DB의 사용자 table count, staging RustFS volume file count를
확인한다. 통계가 없으면 swap 전에 실패한다. restore script가 기본 호출하므로 별도 재검증이나
수동 restore 후 확인에만 직접 실행한다.

```bash
KOR_TRAVEL_MAP_RESTORE_APP_DB=kor_travel_map_restore \
KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB=kor_travel_map_dagster_restore \
KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME=kor-travel-map-rustfs-restore \
bash scripts/docker-restore-verify.sh
```

추가 API smoke는 staging DB/volume을 사용하는 env 파일이나 별도 compose project에서
API를 띄운 뒤 `docs/runbooks/docker-app.md` §6 절차를 수행한다. 운영 stack의 DSN/volume을
staging 대상으로 바꾸기 전까지 외부 서비스는 영향받지 않는다.

## 7. restore hot-swap env 전환

hot-swap은 운영 DB/volume을 삭제하거나 rename하지 않는다. 검증된 staging 대상 이름을
서비스 env override로 쓰는 project root의 고정 `.env.restore-swap` 파일을 생성한 뒤, 필요하면 compose
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

env 파일 경로 override는 없다. writer는 project root를 owner·mode 기준으로 검증하고
symlink/hardlink destination을 거부하며 `0600` temp를 fsync한 뒤 같은 디렉터리에서
원자 교체한다. DSN user/password/database component는 percent-encode한다. marker의
`swap_planned`는 env 파일만 준비한 상태, `swap_applied`는 compose 적용을 실행한 상태로
분리되고 exact env SHA-256을 output proof에 포함한다.

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
  `KOR_TRAVEL_MAP_API_BACKUP_COMMAND_ENABLED=true`일 때만 실행.
- `POST /admin/restore/{backup_id}` — staging restore command plan 생성. 기본 target은
  `kor_travel_map_restore`, `kor_travel_map_dagster_restore`,
  `kor-travel-map-rustfs-restore`.
- `POST /admin/restore/{backup_id}/swap` — restore swap command plan 생성.
  `execute=true`, `apply=true`를 함께 쓰면 검증 후 env 전환과 compose 재기동까지 실행한다.

Admin API의 command 실행은 `KOR_TRAVEL_MAP_API_BACKUP_COMMAND_ENABLED=true`와 요청별
`execute=true`가 모두 있어야 한다. 따라서 기본 UI/API 사용은 plan-only이며, 운영자가
command/env를 확인한 뒤 명시적으로 실행한다.

네 mutation과 `DELETE /admin/backups/{backup_id}`는 UUID `Idempotency-Key`가 필수다.
같은 인증 actor·operation·key와 같은 request는 최초 terminal response를 재생하고 다른
request는 409다. create는 완전한 artifact checksum을 다시 검증해 crash 뒤 marker를 복구할
수 있다. delete는 새 command의 대상이 처음부터 없으면 claim을 rollback하고 404를 반환하며,
이미 시작된 command만 DB에 동결한 삭제 전 snapshot과 artifact 부재 proof로 완료한다.

## 이관된 결정 (구 ADR)

- 백업 단위(Postgres `feature`/`provider_sync`/`ops` schema + RustFS bucket), 1차 NTFS
  `data/backups/<timestamp>/` + 2차 외부(S3/R2) multi-target, staging hot-swap(staging 복원 →
  smoke/count 검증 → connection pool DSN 교체) restore 패턴, 그리고 admin 라우터
  `GET/POST /admin/backups` · `POST /admin/restore/{id}` · `.../swap`은 모두
  본 runbook §2~§8에 정본화돼 있다 (구 ADR-040에서 결정). 근거: `pg_dump --format=custom`
  + RustFS snapshot이 industry-standard이고, 외부 소비자가 실시간 의존하므로 downtime cost가
  커 hot-swap으로 무중단 전환을 택했다(초기엔 cold restore 허용, dual DB 비용은 단계적 도입으로 완화).
