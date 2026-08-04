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
때만 API에서 스크립트를 실행한다. 세 host script는 DB command identity와 API가 미리 만든
Docker fence가 없으면 실행을 거부하므로 직접 `npm run docker:*`로 mutation하지 않는다.

## 1. 전제

백업 스크립트는 `docker compose` standalone stack을 기준으로 동작한다. Postgres
서비스는 `pg_dump`를 위해 실행 중이어야 하지만, 일관된 cold snapshot을 위해 write
path는 먼저 멈춘다.

```bash
docker compose stop api frontend dagster dagster-daemon rustfs
```

`postgres`는 멈추지 않는다. RustFS는 멈춘 뒤 같은 named volume을
`rustfs-perms` service로 읽어 tar archive를 만든다.

## 2. 백업 실행

Admin UI `/admin/backups` 또는 `POST /v1/admin/backups`의 `execute=true` command로
실행한다. UUID `Idempotency-Key`, 인증 actor, 정규화 request fingerprint로 DB execution과
256-bit `effect_token`을 먼저 고정한다. 기본 저장 위치는
`data/backups/backup-<Idempotency-Key>/`이며 request의 `backup_id`로 바꿀 수 있다.

write service가 실행 중이면 스크립트는 기본적으로 중단한다. 운영자가 의도적으로
best-effort snapshot을 남길 때만 다음 opt-in을 사용한다.

API request에서 `allow_running=true`를 명시한다.

이 opt-in 산출물은 진단용 best-effort snapshot이다. vNext cutover rollback 기준점으로 사용할 수
없다. rollback 기준점은 write fence 뒤 생성하고, fence 이후 write가 있으면 검증된 PITR 또는
forward journal replay를 함께 준비한다(ADR-075). upstream 재수집은 정본·감사·3년 weather 이력의
복구 수단이 아니다.

`scripts/docker-backup.sh`, `scripts/docker-restore.sh`,
`scripts/docker-restore-swap.sh`는 `scripts/with-pg-advisory-lock.py`를 통해
PostgreSQL advisory lock `maintenance:backup-restore`를 잡고 실행된다. lock이 이미
잡혀 있으면 실행은 실패한다. lock bypass 환경변수는 지원하지 않는다.

Admin API도 script wrapper 자체가 lock owner다. API connection이 잡은 lock을 env로
child에 위임하지 않는다. 다만 API는 같은 lock을 짧게 잡아 global Docker fence를 생성·검증한
뒤에만 DB phase를 `effect_started`로 전이한다. fence는 고정 이름
`kor-travel-map-maintenance-effect-fence-v1`과 exact effect token/command/operation/input
digest/source revision/Image ID label을 가진다. canonical compose `postgres` container의 local
immutable `sha256:` Image ID만 `--pull=never`로 사용하며 network none, read-only rootfs,
capability 전체 제거, `no-new-privileges`, 비 root user, PID 제한을 적용한다.
create의 destination reservation은 같은 maintenance lock 안에서 exact fence 획득에 성공한
뒤, `effect_started` 전이 직전에만 만든다. foreign fence면 backup root는 바뀌지 않는다.
reservation 실패 때는 DB phase가 여전히 `prepared`임을 근거로 exact 자기 fence만 해제하며,
그 해제까지 증명하지 못하면 자동 진행하지 않고 manual reconciliation으로 남긴다.

host script는 mutation 전에 pre-acquired fence의 exact identity·running·hardened shape를 다시
검사한다. foreign fence가 이미 있으면 새 command는 `prepared`에 남고 mutation 0건으로
`409 BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED`를 반환한다. Docker daemon 작업은
local CLI 종료만으로 취소를 증명할 수 없으므로
effect 시작 뒤에는 non-interruptible supervised 작업이다. wrapper는 `SIGTERM`/`SIGINT`를
호출자 detach로만 기록하고 child에는 전달하지 않는다. stdout/stderr는 API pipe가 아니라
임시 파일에 spool하고 direct child와 child process group이 자연 terminal에 도달한 뒤에만
출력을 재생하고 lock을 해제한다.

API cancellation은 bounded하게 호출 task를 끝내고 timeout은
`504 BACKUP_COMMAND_TIMEOUT`을 반환하지만 wrapper communication은 background에서 계속된다.
DB execution phase는 `effect_started`에 남는다. wrapper/API container가 `SIGKILL`, OOM,
rollout으로 사라져 PostgreSQL lock이 풀려도 daemon fence는 유지된다. marker 없는 동일
command 재시도는 host script를 호출하지 않고
`409 BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED`로 끝난다. 다른 command도 같은 fence에서
막힌다. host script가 create-once marker를 남긴 뒤 재시도하면
외부 효과를 반복하지 않고 marker proof로 `effect_succeeded`와 terminal response를 확정한다.
동일 key의 stale `prepared` 요청은 maintenance lock 획득 뒤 execution을 다시 읽는다. 이미
`effect_started`면 fence를 다시 채택하거나 phase UPDATE를 반복하지 않고 recovered 상태로
기존 marker 확인·manual reconciliation 경로에 합류한다.
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
없는 기존 DB·volume의 단순 health를 완료 provenance로 인정하지 않는다. `effect_started`에서
marker가 없으면 target 존재 여부와 관계없이 자동 재실행하지 않는다.

### 3.1 hard crash 수동 reconciliation

409 응답의 `details`에 command ID, operation, effect kind, effect token, input digest와 fence
name이 있다. 먼저 `docker inspect kor-travel-map-maintenance-effect-fence-v1`의 exact labels,
Image ID, hardened shape와 실제 DB/volume/artifact 상태를 대조한다. workload가 계속 실행
중이거나 terminal을 증명할 수 없으면 fence와 command를 그대로 둔다.

workload terminal과 effect-specific output proof를 외부 증거로 확인한 경우에만
`write-domain-command-marker.py`의 해당 effect 인자로 create-once marker를 먼저 기록한다.
그 marker를 다시 검증한 뒤 `docker-domain-command-fence.py release`에 409의 exact identity를
전달해 fence를 해제하고 같은 `Idempotency-Key`로 재시도한다. fence를 먼저 `docker rm`하거나
missing/foreign/mismatched resource를 새 command 결과로 채택하지 않는다. 이 경계는 자동
recovery가 아니라 외부 operator proof다.

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

Admin UI의 restore 실행 또는 `POST /v1/admin/restore/<backup_id>`에 `execute=true`로 요청한다.

스크립트는 먼저 `meta/SHA256SUMS`를 검증한 뒤 `pg_restore --clean --if-exists
--no-owner --no-privileges`로 두 DB를 복원하고, `rustfs/rustfs-data.tar.gz`를 staging
Docker volume에 푼다. `pg_restore`는 planner 통계를 보존하지 않으므로 각 DB 복원 직후
`vacuumdb --analyze-in-stages`를 완료해야 다음 단계로 진행한다. 복원이 끝나면 기본적으로
`scripts/docker-restore-verify.sh`를 호출해 staging DB/volume smoke/count와
`feature.features` 통계 생성을 확인한다. 기존 staging 대상이 있으면 기본적으로 중단한다.
의도적으로 새로 만들 때만 다음 opt-in을 사용한다.

process가 restore 완료와 marker 생성 사이에 종료돼도 동일 command를 자동 recovery mode로
재실행하지 않는다. 대상이 전부 없거나 전부 healthy인 것만으로 effect terminal/provenance를
증명할 수 없기 때문이다. §3.1의 외부 operator proof를 거쳐 marker를 만들거나 manual 상태를
유지한다. API는 input-only marker를 합성하지 않는다.

API request에 `recreate=true`를 명시한다.

대상 이름은 staging 환경별로 바꿀 수 있다.

API request의 `app_db`, `dagster_db`, `rustfs_volume`으로 지정한다.

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

## 9. n150 prod 수동 기준선 (T-VN-H43)

§1~§8의 자동화는 standalone Docker app(`docker compose` 스택 + admin API 결선)
기준이다. **n150 prod는 kor-travel-docker-manager 배포라 admin API backup
command가 결선돼 있지 않다** — 그 결선 전까지의 수동 기준선 절차가 이 절이다.

- **경로/명명**: n150 `~/backups/kor-travel-map/<YYYY-MM-DD>-<label>.dump`
  (+`.sha256`, `.manifest`). manifest에는 alembic head와 핵심 카운트
  (features/source_records/source_links/weather_values/**public_api_keys**)를
  선기록한다 — `ops.public_api_keys`는 2026-08-05 재생성 소실 실측(공개 표면
  전체 401) 이후 **백업 스코프 필수 확인 항목**이다.
- **실행**: api 컨테이너 env의 TCP DSN으로 `postgis/postgis:16-3.5-alpine`
  컨테이너에서 `pg_dump -Fc --no-owner`. pg_dump는 스냅샷 트랜잭션이라 DB
  단독으로는 **내부 일관**이다. 단 write path를 멈추지 않은 live dump는 3종
  묶음(DB/dagster metadata/RustFS) 간 정합을 보장하지 않으므로 §2의 원칙대로
  **vNext cutover rollback 기준점으로는 배포 직전 write fence 뒤 dump를 따로
  만든다** — 이 절의 기준선은 "재생성 수렴 상태의 복구 출발점" 용도다.
- **1차 검증**: `pg_restore -l`로 목차 판독 + `public_api_keys` TOC 존재 확인.
  실복원 드릴은 T-VN-H44(H30B 하네스 재사용 — 별도 DB로 restore → 카운트
  대조 → 공개 표면 smoke) 소관.
- **기준선 실적**: `2026-08-05-h43-baseline.dump` — H42 수렴 완료 직후
  (MOIS 702,955 3중 일치·opinet 934, unlinked 0) 상태. 435MB/54.7s, sha256
  `717790c0…8a04e286`, manifest 실측: alembic head `0078_cache_target_gc_observe`
  · features 731,599 · source_records 732,279 · source_links 731,599 ·
  weather_values 555 · public_api_keys 1. `pg_restore -l` 목차 690항목 판독
  + public_api_keys TOC 존재 확인.
- **잔여**: 2차 외부 사본(S3/R2)과 주기화(cron)·retention은 docker-manager
  결선과 함께 후속 — 지금은 단일 host 사본이므로 디스크 장애에 취약하다는
  한계를 명시해 둔다.

## 이관된 결정 (구 ADR)

- 백업 단위(Postgres `feature`/`provider_sync`/`ops` schema + RustFS bucket), 1차 NTFS
  `data/backups/<timestamp>/` + 2차 외부(S3/R2) multi-target, staging hot-swap(staging 복원 →
  smoke/count 검증 → connection pool DSN 교체) restore 패턴, 그리고 admin 라우터
  `GET/POST /admin/backups` · `POST /admin/restore/{id}` · `.../swap`은 모두
  본 runbook §2~§8에 정본화돼 있다 (구 ADR-040에서 결정). 근거: `pg_dump --format=custom`
  + RustFS snapshot이 industry-standard이고, 외부 소비자가 실시간 의존하므로 downtime cost가
  커 hot-swap으로 무중단 전환을 택했다(초기엔 cold restore 허용, dual DB 비용은 단계적 도입으로 완화).
