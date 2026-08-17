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

> ⚠️ **이 스크립트는 n150 prod에 쓸 수 없다.** prod는 저장소 standalone stack이 아니라
> `kor-travel-docker-manager`가 띄우는 **프로젝트별 전용 PostgreSQL**에서 돈다
> (2026-08-17, docker-manager ADR-37). 서비스명이 `postgres`가 아니고 포트도 다르다.
>
> | | standalone | n150 prod |
> |---|---|---|
> | 서비스/컨테이너 | `postgres` | `kor-travel-map-postgres` |
> | 포트 | `5432` | **`12700`** (loopback 전용) |
> | 대상 DB | `kor_travel_map`, `_dagster` | 같음 |
>
> prod 백업은 컨테이너 안에서 포트를 명시해 직접 뜬다. **`-p`를 빠뜨리면 컨테이너
> 기본값(5432)을 찾아 실패한다** — host network라 소켓도 그 포트에 없다.
>
> ```bash
> docker exec kor-travel-map-postgres \
>   pg_dump -h 127.0.0.1 -p 12700 -U kor_travel_map -d kor_travel_map \
>   -Fc --compress=6 -f /tmp/map.dump
> docker cp kor-travel-map-postgres:/tmp/map.dump <대상>/
> ```
>
> 산출물은 `~/backups/kor-travel-map/`에 `<날짜>-<태그>.dump` + `.sha256` +
> `.manifest`(alembic head와 주요 row count)로 둔다 — 기존 관례 그대로다. 권한은
> `600`이다(`docs/external-apis.md` §1.1 — dump는 DB 전체를 담는다).
>
> **다른 세 인스턴스도 각자 백업 주체가 필요하다**(geo `12500` 33GB · concierge
> `12600` · pinvi `12800`). 그 셋은 이 저장소 소관이 아니므로 docker-manager 쪽에
> 절차를 둔다 — 현재 미비이고 별건이다.

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

### 2.1 ⛔ per-database dump가 담지 않는 것 — 새 인스턴스로 옮길 때 반드시 함께 옮긴다

`pg_dump -d <db>`는 **그 데이터베이스 안의 것만** 담는다. 아래 넷은 그 밖(cluster 전역
또는 compose 설정)이라 빠지고, **빠져도 복원은 성공한다.** 증상은 런타임에야 나온다.

2026-08-15 전용 인스턴스 이행에서 넷 다 실제로 걸렸다 — **리허설이 ①②를, 커토버 후
실제 ETL 실행이 ③④를** 드러냈다. ③④가 리허설을 통과한 이유는 아래 "왜 카탈로그 비교로는
안 잡혔나"에 적는다.

**① `ALTER DATABASE … SET`** — 특히 `search_path`.

prod `kor_travel_map`은 DB 수준에 `search_path=public, x_extension`이 걸려 있다.
복원본은 postgis 템플릿에서 온 `"$user", public, topology`를 물려받아 **`x_extension`이
빠진다.** 그러면 `geometry`·`st_transform`을 스키마 없이 쓰는 SQL이 런타임에 깨진다.

카탈로그 비교에서는 **타입 표기 차이**로 보인다 — `format_type()`이 search_path에 따라
다르게 찍기 때문이다. 리허설 실측: digest 2486행 중 24행이 `geometry` vs
`x_extension.geometry`로 어긋났고, `ALTER DATABASE`를 적용하자 **2486행 전 행 일치**가 됐다.
즉 이 차이를 "표기일 뿐"이라고 넘기면 진짜 결손을 넘기는 것이다.

```sql
-- 원본에서 읽어 그대로 옮긴다
SELECT d.datname, array_to_string(s.setconfig, ' | ')
  FROM pg_db_role_setting s JOIN pg_database d ON d.oid = s.setdatabase
 WHERE s.setrole = 0;
```

**② 역할 비밀번호(SCRAM 해시).**

역할을 `CREATE ROLE`로 새로 만들면 비밀번호가 없다. 앱 DSN은 비밀번호로 붙으므로
**네 서비스가 동시에 인증 실패**한다. 평문을 알 필요는 없다 — 해시를 그대로 옮긴다.

```sql
-- 원본에서: 그대로 실행 가능한 문장을 만든다
SELECT format('ALTER ROLE %I PASSWORD %L;', rolname, rolpassword)
  FROM pg_authid WHERE rolname ~ '^ktm_' AND rolpassword IS NOT NULL;
```

역할 **속성**(LOGIN/NOINHERIT)도 따로 옮긴다. 특히 psql은 boolean을 `t/f`가 아니라
`true/false`로 내므로, `[ "$v" = t ]` 같은 비교는 빗나가 역할이 전부 NOLOGIN으로
만들어진다(리허설에서 실제로 그랬다).

**③ 멤버십의 `INHERIT`/`SET` 옵션 (PG16).**

`GRANT a TO b;`만 실행하면 `INHERIT` 옵션이 **member의 `rolinherit`에서 정해진다.**
이 저장소 역할은 전부 NOINHERIT이므로 `inherit=false, set=true`가 된다.

그런데 원본은 `inherit=true, set=false`다 — 역할 자체는 NOINHERIT이면서 **이 멤버십만**
상속하도록 명시돼 있다. 그래야 runtime 역할이 `SET ROLE` 없이 스키마 USAGE를 갖는다.
옵션을 안 옮기면 ETL이 이렇게 죽는다:

```
asyncpg.exceptions.InsufficientPrivilegeError: permission denied for schema provider_sync
```

```sql
-- 원본에서: 옵션까지 담은 GRANT 문을 만든다. boolean은 t/f로 찍히므로 CASE로 편다.
SELECT format('GRANT %I TO %I WITH ADMIN %s, INHERIT %s, SET %s;',
              r.rolname, m.rolname,
              CASE WHEN am.admin_option   THEN 'TRUE' ELSE 'FALSE' END,
              CASE WHEN am.inherit_option THEN 'TRUE' ELSE 'FALSE' END,
              CASE WHEN am.set_option     THEN 'TRUE' ELSE 'FALSE' END)
  FROM pg_auth_members am
  JOIN pg_roles m ON m.oid = am.member
  JOIN pg_roles r ON r.oid = am.roleid
 WHERE m.rolname ~ '^ktm_';
```

**④ compose가 하드코딩한 기본 DSN.**

DB 밖의 문제지만 같은 사고를 낸다. `KOR_TRAVEL_MAP_DAGSTER_PG_URL`은

```yaml
KOR_TRAVEL_MAP_DAGSTER_PG_URL: ${KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL:-postgresql://…@127.0.0.1:5432/kor_travel_map_dagster}
```

로 되어 있는데 그 override 이름이 **`.env`에 아예 없었다.** `.env`만 훑는 방식으로는
안 보인다. 안 고치면 dagster가 계속 **옛 DB에 run을 기록해** 두 DB가 조용히 갈라진다.

```bash
# `.env`가 아니라 compose가 resolve한 값에서 **현재 쓰는 포트가 아닌 것**을 찾는다.
# 찾을 포트를 고정하지 마라 — 2026-08-17에 map이 12703에서 12700으로 옮겼고, 그때
# 이 명령이 `:5432/`만 보고 있어서 12703 잔여 7건을 통째로 놓쳤다(항상 초록이었다).
docker compose config \
  | grep -oE 'postgres[^ ]*://[^ ]+' \
  | grep -oE ':[0-9]{4,5}/[a-z_]+' | sort -u
# 나온 포트가 전부 현재 배치(geo 12500 / concierge 12600 / map 12700 / pinvi 12800)인지
# 눈으로 확인한다. 하나라도 다르면 그 DSN이 죽은 포트를 가리킨다.
```

### 왜 카탈로그 비교로는 ③④가 안 잡혔나

`scripts/compare-schema-catalogs.sh`의 **core digest**는 relation/column/index/constraint를
본다. 스키마 ACL·멤버십 옵션은 그 축에 없고 보조 축과 별도 검사에 있다. 그래서 커토버
직전 "digest 2486행 전 행 일치"가 나왔지만 ③④는 남아 있었다.

**오라클의 일부만 돌리고 전체를 돌린 것처럼 읽지 마라.** 이행에서는 digest 외에
아래를 따로 대조한다.

```sql
-- 스키마 ACL
SELECT nspname, pg_get_userbyid(nspowner), array_to_string(nspacl, ',')
  FROM pg_namespace WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema';

-- 멤버십 옵션 (③)
SELECT m.rolname, r.rolname, am.admin_option, am.inherit_option, am.set_option
  FROM pg_auth_members am JOIN pg_roles m ON m.oid = am.member
                          JOIN pg_roles r ON r.oid = am.roleid;

-- 유효 권한 (가장 직접적이다)
SELECT r.rolname, n.nspname, has_schema_privilege(r.rolname, n.nspname, 'USAGE')
  FROM pg_roles r, pg_namespace n
 WHERE r.rolname ~ '^ktm_' AND n.nspname IN ('feature','ops','provider_sync','x_extension');
```

**확인 방법 — 스위치 후 실제 job을 한 번 돌린다.** 위 대조를 다 해도 ④처럼 DB 밖의
축은 남을 수 있다. 커토버에서 ③④를 실제로 잡아낸 것은 카탈로그 비교가 아니라 **ETL
1회 실행**이었다. 인증만 확인하는 것으로는 부족하다:

```
PGPASSWORD=<앱 DSN의 값> psql -h 127.0.0.1 -p <새 포트> -U ktm_feature_api_runtime \
  -d kor_travel_map -tAc "SELECT current_user, current_setting('search_path')"
```

이 접속 시험은 ①②를 잡지만 ③④는 통과시킨다 — 접속과 `search_path`는 멀쩡하고
스키마 USAGE에서만 막히기 때문이다.

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
  ⚠️ **2026-08-13 정정**: `weather_values`의 실제 relation은
  `feature.weather_values`가 아니라 **`feature.feature_weather_values`**다
  (T-VN-35 typed subtype 분해에서 개명). 옛 이름으로 조회하면 relation 부재로
  실패한다 — 이 절의 카운트 목록을 그대로 스크립트로 옮기면 그 자리에서 깨진다.
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

## 10. 복원 리허설 드릴 (T-VN-H44)

백업본이 **실제로 복원되는지**를 반복 가능한 드릴로 고정한다.

- **1회차**: 2026-08-05, `2026-08-05-h43-postdeploy-0083.dump`(489MB, 0083·값 전환
  배포 후) 대상, dev box(WSL) 격리 컨테이너에서 전 단계 통과.
- **2회차**: 2026-08-13, `2026-08-13-h43-postdeploy-0104.dump`(586MB, **백업 없는
  in-place 마이그레이션 직후**) 대상, n150 격리 컨테이너(`h44-drill-pg`, :15444).
  복원 341초, `pg_restore` 오류 1건(`schema "x_extension" already exists` — 아래
  절차 3이 정상이라 명시한 그 1건). **manifest 6항목 전 항목 일치**:
  head `0104_tvn36_final_fence` · features 1,008,852 · source_records 1,009,157 ·
  source_links 1,008,852 · feature_weather_values 0 · public_api_keys 1.
  3축 분포도 prod와 동일(`active/published/valid` 1,008,848 +
  `retired/suppressed/valid` 4), `0104`가 지운 두 테이블은 복원본에도 없다.
  → **이 dump는 복구점으로 신뢰할 수 있다.**
  단 절차 5(결손 주입 → replay)는 실행하지 못했다 — 그 축은 3회차 소관이다.

- **3회차**: 2026-08-14/16, 같은 dump 대상. **절차 1~4 전부 통과**했고 절차 5는
  **replay 도중 중단**했다. 얻은 것이 오히려 많다:

  | 절차 | 결과 |
  |---|---|
  | 1~3 복원 | 633초, 오류 1건(문서가 "정상"이라 명시한 `x_extension already exists`) |
  | 4 manifest | **6항목 전 항목 일치** |
  | 5 결손 주입 | features 1,008,852 → 1,008,847 · public 1,008,848 → 1,008,843 (정확히 5) |
  | 5 replay | **문서에 적힌 명령이 성립하지 않았다** → 아래 절차 4 참조 |

  드러난 것 셋. ① `--mode incremental --dataset-key …bulk` 조합은 카탈로그에 없어
  `FeatureOperationInvariantConflict`로 죽는다. ② 성립하는 유일한 경로(전체 스냅샷
  bulk)는 결손 5건을 고치는 수단이 아니라 **dataset 전체 재적재**이고, 단일 트랜잭션에
  **24시간 넘게** 걸린다. ③ `\copy … TO`가 JSON을 깨뜨려 12% 지점에서 3시간 20분이
  통째로 롤백됐다(두 번).

  중단 판단 — 유효한 입력으로 11시간(약 77%)까지 갔고 잔여가 10시간 이상이었다. 남은
  질문이 "커밋까지 가는가" 하나뿐이라 그 값이 비용보다 작았다. **절차 5의 결론은
  "이 경로는 복구 수단이 아니다"이고, 그 결론에는 완주가 필요하지 않다.**

### 왜 격리 컨테이너인가 (원칙)

`pg_restore`는 아카이브 **안의 SQL을 실행한다**. 즉 dump 파일은 수동적인 데이터가
아니라 실행 가능한 입력이고, 그것을 어디에 푸느냐가 **신뢰 경계**다. 그래서 드릴은
항상 일회용(disposable) 격리 인스턴스에서 하고, 끝나면 지운다 — 운영 클러스터에
직접 복원해 "확인만" 하는 경로는 두지 않는다.

같은 이유로 **app DB와 Dagster metadata DB는 같은 writer-quiesced window 안에서
함께 dump하고, dump 뒤에 그 window가 유지됐는지 재확인한다.** 두 DB를 따로 뜨면
서로 다른 시점을 가리키는 한 쌍이 만들어지는데, 복원 시점에는 그 어긋남이 보이지
않는다.

### 절차 (1회 드릴 = 5단계)

1. **격리 DB 기동** — `docker run -d --name h44-drill-pg -e POSTGRES_USER=drill
   -e POSTGRES_PASSWORD=drill -p 15444:5432 postgis/postgis:16-3.5-alpine`.
   prod와 같은 이미지 계열을 쓰고 포트는 겹치지 않게 띄운다.
2. **새 DB + 확장 선생성** — `CREATE DATABASE ktm_drill` 뒤
   `CREATE SCHEMA x_extension` + `postgis`/`pg_trgm`/`pgcrypto`/`btree_gist`를
   그 스키마에 생성(ADR-008). **`POSTGRES_DB`에 그대로 복원하지 않는다** —
   init이 심어둔 확장과 dump의 확장 배치가 충돌한다(0072 아카이브 복원 실측).
3. **복원** — `pg_restore -U drill -d ktm_drill --no-owner --no-privileges -j 2`.
   확장 스키마 선생성 때문에 `schema "x_extension" already exists` 오류 1건이
   나고 `errors ignored on restore: 1`로 끝나는 것이 **정상**이다(그 1건 외
   오류가 있으면 실패로 판정).
4. **manifest 대조** — dump와 함께 받은 `.manifest`의 alembic head·row count와
   복원본을 대조한다. 1회차 실측: head `0083_nonderived_uuid_generator` ·
   features/aliases/public 각 731,765 · pair_mismatch 0 · orphan_alias 0 —
   **전 항목 일치**.
5. **결손 주입 → provider replay 회복** — 복원본 **위에서 적재 경로가 살아 있는지**를
   본다. provider가 다시 채울 수 있는 relation에만 결손을 내고, 같은 dataset을 재적재해
   메워지는지 확인한다. 상세는 아래 「절차 5 상세」.

### 절차 5 상세 — 결손 주입 → provider replay (2026-08-14 재작성)

**이 절차가 검증하는 축은 하나다: 복원본 위에서 provider 적재 경로가 실제로 돌아
feature 본문 결손을 메운다.** 백업 산출물이 읽히는지(절차 4)도, identity·운영자 행위
기록·append-only 관측 이력이 복구되는지도 검증하지 않는다 — 뒤의 셋은 애초에 replay
대상이 아니고 백업 복원만이 복구 수단이다(§2의 ADR-075 단서와 같은 이유).

**replay 가능 / 불가능의 경계.** replay 가능 = provider snapshot을 다시 적재하면 같은
값이 다시 써지는 것 — `feature.features` 본문, 5종 typed subtype(`feature.feature_places`
/ `feature_events` / `feature_notices` / `feature_routes` / `feature_areas`),
`feature.feature_base_field_values`가 여기 속한다. 아래는 **replay로 돌아오지 않으므로
결손 주입 대상으로 쓰지 않는다**:

- 운영자 행위 기록 — `ops.feature_overrides`, `ops.domain_commands` /
  `ops.domain_command_results`, `feature.feature_state_transitions`
- 발급물 — `ops.public_api_keys`(§9의 필수 확인 항목과 같은 이유)
- append-only 관측 이력 — `feature.feature_weather_values`, `feature.feature_price_values`

절차:

1. **대상 선정** — 한 provider dataset에서 feature 5건을 고른다. `ops.feature_overrides`에
   active 행이 있거나 `feature.curated_features` / `ops.dedup_review_queue`에 걸린 feature는
   제외한다 — 이들은 `feature.features` 삭제 때 FK CASCADE로 함께 사라지는데 replay가
   복원하지 않는다(전체 CASCADE 목록은 덤프에서
   `rg 'REFERENCES feature.features' alembic/baseline/schema.sql`).

   ```sql
   SELECT f.feature_id, f.feature_uuid, se.source_entity_key
   FROM feature.features f
   JOIN provider_sync.source_links sl
     ON sl.feature_id = f.feature_id AND sl.source_role = 'primary'
   JOIN provider_sync.source_entities se
     ON se.source_entity_key = sl.source_entity_key
   JOIN provider_sync.provider_datasets pd
     ON pd.provider_dataset_id = se.provider_dataset_id
   WHERE pd.dataset_key = :dataset_key
     AND NOT EXISTS (SELECT 1 FROM ops.feature_overrides o
                      WHERE o.feature_id = f.feature_id AND o.status = 'active')
     AND NOT EXISTS (SELECT 1 FROM feature.curated_features c
                      WHERE c.feature_id = f.feature_id)
   LIMIT 5;
   ```

   `feature_uuid`와 `source_entity_key`도 함께 받아 둔다 — 4·5단계에서 쓴다.

2. **주입** — 고른 5건을 `feature.features`에서 DELETE한다. **`session_replication_role`
   조작은 필요 없다.** subtype·alias·source_link·base field value는 FK CASCADE로 함께
   사라지고, `feature_weather_values` / `feature_price_values`의 immutability 트리거와 alias
   delete fence는 "부모 feature가 이미 없는 cascade"를 유일한 예외로 명시 허용한다
   (`feature.reject_weather_value_mutation`, `feature.reject_price_value_mutation`,
   `feature.fence_feature_aliases_write`).

   **subtype 행만 지우는 변형은 쓰지 않는다.** `load_bundle`은 entity head가 전진했거나
   (`became_current`) feature가 없을 때만 본문을 다시 쓴다 — 같은 payload 재적재는 head의
   `observed_at`만 밀고 본문을 건드리지 않는다(`infra/feature_repo.py`의
   `_UPSERT_SOURCE_ENTITY_HEAD_SQL` 주석이 이 설계를 명시). 그래서 subtype만 비우면 replay가
   그 구멍을 메우지 못한다.

3. **결손 관측** — `ktmctl consistency-report --format json`(read-only)에서
   **F1(orphan source_entity — `source_links` 없음)이 5로 오르는지** 확인한다. feature가
   사라져도 `provider_sync.source_entities` / `source_records`는 남으므로 F1이 이 결손의
   정확한 축이다. `feature.public_features` 카운트도 5 줄어야 한다. F2(subtype 결측)는 0을
   유지한다 — core와 subtype이 함께 사라졌기 때문이다.

4. **replay** — 삭제한 feature를 만든 provider 적재를 **같은 `dataset_key`로** 다시 돌린다.
   `dataset_key`는 `feature_id`와 `source_entity_key` 계산에 들어가므로 다르면 메우는 게
   아니라 새 feature가 생긴다(`providers/mois.py:license_record_to_bundle`).

   드릴 컨테이너에는 provider API 키도 네트워크도 없으므로 저장된 원문을 되먹인다: 해당
   entity의 `provider_sync.source_records.raw_data`를 NDJSON으로 뽑아 `ktmctl import mois`로
   재주입한다. `load_bundle`이 feature 부재를 보고 본문·subtype·base field value를 다시 만든다.

   ⛔ **`--mode incremental --dataset-key mois_license_features_bulk`는 성립하지 않는다
   (2026-08-14 드릴 3회차 실측).** 이전 판이 그렇게 적어 뒀는데 실행하면 이렇게 죽는다:

   ```
   FeatureOperationInvariantConflict: runtime dataset does not resolve to
   exactly one operation membership   (match_count: 0)
   ```

   membership은 `(operation_key, provider, dataset_key)` triple로 해석되는데, mode별
   operation key와 카탈로그(0089 seed)의 등록이 이렇게 갈린다:

   | mode | 쓰는 operation key | 그 key가 등록된 dataset |
   |---|---|---|
   | `bulk` | `feature_place_mois_licenses_job` (`_BULK_OPERATION_KEY`) | `mois_license_features_bulk` ✅ |
   | `incremental` | `mois_license_incremental_update` | `mois_license_features_**history**` |
   | `closed` | `mois_license_closed_update` | `mois_license_features_closed` |

   즉 incremental은 **history dataset 전용**이다. CLI 도움말도 그렇게 적고 있다
   ("미지정 시 모드별 기본 — bulk=…bulk / incremental=…history"). bulk dataset을
   incremental로 지목하는 조합은 카탈로그에 아예 없다.

   그렇다고 `--dataset-key mois_license_features_history`로 바꾸면 구멍을 메우지 못한다 —
   `dataset_key`가 `source_type=f"{PROVIDER_NAME}:{dataset_key}"`로 `make_feature_id`에
   들어가므로 **다른 feature_id**가 만들어진다(`providers/mois.py:702-717`).

   그래서 성립하는 replay는 **전체 스냅샷 bulk 하나뿐**이다:

   ```
   ktmctl import mois <전체.ndjson> --mode bulk --dataset-key mois_license_features_bulk
   ```

   bulk는 파일에 없는 feature를 soft-delete하므로 **그 dataset의 `source_records` 전부**를
   넣어야 한다. 5건짜리 파일로 돌리면 나머지 98만 건이 soft-delete된다.

   ⚠️ 그래서 이 경로는 **결손 5건만 고치는 수단이 아니라 dataset 전체 재적재**다. 아래
   부분 복원 손실이 5건이 아니라 **dataset 전건에 적용된다**는 뜻이기도 하다 — 운영 복구에
   이 경로를 쓰면 멀쩡한 feature의 detail까지 함께 깎인다.

   ⛔ **그리고 그 전체 재적재는 단일 트랜잭션이고 재개 지점이 없다 (2026-08-14/15 실측).**
   `--batch-size`는 statement 크기만 나눌 뿐 트랜잭션을 끊지 않는다. 98만 건이면
   트랜잭션 하나가 **3시간 넘게** 열려 있고, 그 사이 무엇이든 잘못되면 **전부 롤백된다.**

   드릴 3회차에서 두 번 겪었다. 두 번 다 입력 파일 **12% 지점(119,408번째 줄)의 잘못된
   JSON 한 줄** 때문이었고, 거기 닿기까지 3시간 20분이 걸렸다. 남은 흔적:

   | relation | live | dead |
   |---|---|---|
   | `feature.feature_base_field_values` | 0 | **2,880,150** |
   | `feature.features` | 1,009,004 | 230,417 |
   | `feature.feature_places` | 1,005,109 | 230,417 |

   ⚠️ **그 잘못된 JSON은 추출 방식이 만든 것이다 — 아래를 따르면 재현된다.**
   `\copy (SELECT raw_data::text ...) TO '파일'`은 COPY **TEXT 포맷**이라 백슬래시를
   `\\`로 이스케이프한다. 주소에 큰따옴표가 든 레코드(예: `물태리 290-6 "나"동`)의
   JSON `\"`가 `\\"`가 되어 무효 JSON이 된다. 980,464줄 중 13줄이 그랬다.

   ```bash
   # 나쁨 — COPY 이스케이프가 JSON을 깨뜨린다
   psql -c "\copy (SELECT sr.raw_data::text FROM …) TO '/tmp/full.ndjson'"

   # 좋음 — 이스케이프 없음
   psql -tA -c "SELECT sr.raw_data::text FROM …" > /tmp/full.ndjson
   ```

   그리고 **돌리기 전에 전 줄을 파싱해 본다.** 12% 지점의 오류를 3시간 뒤에 알게 되는
   구조를 그대로 두지 않는다:

   ```bash
   python3 -c 'import json,sys; [json.loads(l) for l in open(sys.argv[1]) if l.strip()]' \
     /tmp/full.ndjson && echo "전 줄 유효"
   ```

   ⛔ **그리고 그 재적재는 98만 건 기준 24시간 넘게 걸린다 (2026-08-15/16 실측).**
   유효한 입력으로 11시간을 돌려 약 77% 지점(lineage 8.1GB / DB 18GB)까지 갔고, 처리율은
   시작 시 약 600 레코드/분에서 계속 떨어져 잔여만 10시간 이상이었다. 드릴은 거기서
   중단했다 — 남은 것이 "커밋까지 가는가" 하나뿐이라 10시간을 더 쓸 값이 없었다.

   이 소요 자체가 결론을 굳힌다. **한 트랜잭션이 24시간 열려 있는 경로는 복구 수단이
   아니다.** 그 사이 vacuum은 죽은 튜플을 못 걷고(드릴 DB가 8GB → 18GB로 불었다), 무엇
   하나만 어긋나도 24시간이 통째로 사라진다.

   운영 함의 셋. (1) 부분 진행이 없으므로 "절반이라도 복구"가 불가능하다. 복구 수단으로
   삼기에는 이 성질만으로도 부적합하고, **정식 복구 수단은 백업 복원이다.**
   (2) 그래도 돌려야 하면 **분리 실행**한다(`docker run -d` / `nohup`) — 터미널에 붙여
   두면 세션이 끊기는 순간 몇 시간이 사라진다.
   (3) 디스크를 원본 DB의 **3배**로 잡는다. 8GB DB가 재적재 중 18GB까지 갔다.

   부수 확인 — 위 dead tuple이 증명하듯 이 경로는 `feature_base_field_values`를
   **실제로 채운다.** prod에서 그 테이블이 0행인 것은 적재 경로 결함이 아니라 provider
   ETL이 2026-08-07 이후 돌지 않았기 때문이다(task #53).

   ⚠️ **이 되먹임은 본문을 부분적으로만 복원한다 (2026-08-14 코드 실측, 드릴 실행 전 확정).**
   `providers/mois.py:_raw_data`는 payload_hash용 canonical dict라 Protocol **45개 필드 중
   22개만** 담는다. NDJSON 래퍼 `cli/records.py:MoisLicenseJsonRecord.__getattr__`는 없는 key를
   **조용히 `None`으로** 돌려주므로 되먹임은 **실패하지 않고** 24개 필드를 잃은 채 성공한다.
   실패보다 이쪽이 위험하다.

   잃는 24개는 전부 category별 상세다. 본문에서는 이렇게 나타난다:

   - `PlaceDetail.facility_info`의 **`building` / `medical` / `food` / `culture_sports` 네 블록
     전체**가 사라지고 `subtype_name`·`sales_method_name`이 `None`이 된다 —
     되먹임 후 남는 key는 `service_slug`, `category` 둘뿐이다.
   - `Address.zipcode`(`road_zip`/`lot_zip`), `Address.road_address_management_no`
     (`building_management_number`)가 `None`이 된다.

   손실 집합과 그 본문 영향은 `tests/unit/test_providers_mois.py`의
   `test_raw_data_round_trip_drops_exactly_the_known_fields` /
   `test_raw_data_round_trip_empties_facility_info_blocks`가 고정한다. `_raw_data`를 넓히면
   그 테스트가 실패하니 **여기 적은 목록도 함께 고쳐라.**

5. **회복 확인** — F1이 0으로 돌아오고 `feature.features` / `feature.public_features` 카운트가
   원복되며 identity 4축(`missing_uuid` / `missing_alias` / `alias_pair_mismatch` /
   `orphan_alias` — `kortravelmap.infra.feature_identity.count_features_missing_identity`)이
   전부 0인지 확인한다.

   **위 네 축만으로는 4단계의 부분 복원을 보지 못한다.** F1도 카운트도 identity도
   `facility_info`를 들여다보지 않기 때문에, detail이 빈 채로 돌아와도 전부 초록이다. 그래서
   1단계에서 `feature_uuid`·`source_entity_key`와 **함께 `facility_info`도 받아 두고**
   5단계에서 대조한다. building/medical/food/culture_sports 블록이 사라졌으면 정상이다 —
   그것이 이 경로의 알려진 한계이지 드릴 실패가 아니다. 그 블록까지 돌려야 하는 복구라면
   replay가 아니라 백업 복원이 수단이다.

   `facility_info`는 `feature.feature_places`의 **최상위 jsonb 컬럼**이다. DTO에서
   `PlaceDetail.facility_info`로 읽는다고 DB에도 `detail` 아래 있는 것이 아니다 —
   그 테이블에 `detail` 컬럼은 없다.

   ```sql
   SELECT feature_id, facility_info FROM feature.feature_places
    WHERE feature_id = ANY(:feature_ids);
   ```

   주소 두 축은 `feature.features`에서 본다 — `address->>'zipcode'`(jsonb)와
   최상위 컬럼 `road_address_management_no`.

   **`feature_uuid`는 원래 값으로 돌아오지 않는다.** 0083 이후 신규 행의 UUID는 비파생 v7이라
   replay는 새 identity를 만든다. 1단계에서 받아 둔 값과 대조해 "본문은 (detail 일부를 뺀 채)
   돌아왔고 identity는 바뀌었다"를 확인하는 것까지가 이 절차의 결론이다.

### ⚠️ relation 개명 대조표 (T-VN-35/36)

2회차 드릴(`0104`)에서 아래 이름의 SQL이 **그 자리에서 깨졌다**. 세대 전환을 문서가 따라오지
않은 것이므로 함정 자체는 유효하고 이름만 바뀌었다. **본문(절차 5·아래 함정)은 2026-08-14에
`alembic/baseline/schema.sql`(`0104` head 기계 덤프) 기준으로 고쳤다** — 이 표는 옛 문서·스크립트를
만났을 때 옮겨 읽는 용도로 남긴다. 표의 대조는 덤프 정적 확인이며, 실행 검증은 3회차 소관이다.

| 옛 이름 | 현행(`0104`) |
|---|---|
| `feature.weather_values` (§9 manifest) | `feature.feature_weather_values` |
| `provider_sync.source_records.lineage_key` | `provider_sync.source_entity_heads.lineage_key` (+ `provider_sync.notice_lineage_states.lineage_key`) |
| 트리거 `trg_source_record_lineage_key` | `trg_source_entity_head_lineage_key` (`source_entity_heads`, `ENABLE ALWAYS`) |
| 트리거 함수 (구세대) | `provider_sync.set_source_entity_head_lineage_key()` |
| 함수 `provider_sync.notice_lineage_key(source_records)` | `provider_sync.notice_lineage_key(head provider_sync.source_entity_heads)` |
| 인덱스 `idx_source_records_lineage` (표현식) | `idx_source_entity_heads_lineage` (일반 컬럼: `lineage_key, observed_at DESC, current_source_record_key DESC`) |

### 함정 (1회차 실측 — 이름은 위 대조표 기준으로 갱신)

- **`pg_restore --disable-triggers`는 계보 트리거의 `ENABLE ALWAYS`를 조용히
  벗긴다.** `trg_source_entity_head_lineage_key`는 `session_replication_role = replica`
  에서도 돌도록 `ENABLE ALWAYS`로 만들어 뒀는데(ADR-087), 그 옵션이 내보내는
  `DISABLE TRIGGER ALL` → `ENABLE TRIGGER ALL` 쌍을 지나면 `tgenabled`가
  `A` → `D` → **`O`(ORIGIN)**가 된다. 오류도 경고도 없다. 그 뒤로는 replica
  세션의 쓰기에서 계보 파생이 통째로 빠진다.
  복원 후 **반드시** 되돌릴 것:
  `ALTER TABLE provider_sync.source_entity_heads
     ENABLE ALWAYS TRIGGER trg_source_entity_head_lineage_key;`
  확인: `SELECT tgenabled FROM pg_trigger
          WHERE tgname='trg_source_entity_head_lineage_key';` → `A`여야 한다.
  (덤프에도 `ALTER TABLE ... ENABLE ALWAYS TRIGGER`가 이 하나뿐이다 —
  `rg 'ENABLE ALWAYS' alembic/baseline/schema.sql`.)
- **복원 뒤 `ANALYZE`를 반드시 돌린다.** `pg_restore`는 planner 통계를 복원하지 않는다.
  `ANALYZE provider_sync.source_entity_heads;` `ANALYZE provider_sync.source_records;`
  (`REINDEX` 뒤에도 같다.)
  1회차의 **221.9ms 대 2.0ms(110배)** 실측은 `lineage_key`가 `source_records`의 표현식
  인덱스였던 구세대 값이다. `0104`에서 `lineage_key`는 `source_entity_heads`의 일반 NOT NULL
  컬럼이라 "표현식 인덱스에 자기 통계가 없다"는 그 기전은 더 이상 성립하지 않는다 —
  현행 세대의 회귀 폭은 미측정이다.
- 값 점검과 복구는 **두 단계**다. 점검은 읽기 전용이어야 한다 — UPDATE를 점검용으로
  돌리면 어긋난 행마다 row lock과 WAL이 나간다.
  점검: `SELECT count(*) FROM provider_sync.source_entity_heads h
          WHERE h.lineage_key IS DISTINCT FROM provider_sync.notice_lineage_key(h);`
  → 0이면 전부 맞다. 0이 아닐 때만 복구:
  `UPDATE provider_sync.source_entity_heads h
     SET lineage_key = provider_sync.notice_lineage_key(h)
   WHERE h.lineage_key IS DISTINCT FROM provider_sync.notice_lineage_key(h);`
  (`notice_lineage_key`는 scope 밖 entity에도 `source_entity_id`를 돌려주므로 전 행에
  안전하게 적용된다.)
- 컨테이너 기본 `/dev/shm`(64MB)이 작아 73만 행 병렬 집계에서
  `could not resize shared memory segment` 가 난다 — 검증 쿼리는
  `SET max_parallel_workers_per_gather=0`으로 돌리거나 `--shm-size=1g`로 띄운다.
- 드릴 종료 후 컨테이너를 반드시 제거한다(`docker rm -f h44-drill-pg`) —
  dev box 디스크 여유가 크지 않다.

### 주기

배포 동반 migration이 있는 릴리스 뒤, 그리고 최소 월 1회. 결과는 journal에
1줄(대상 dump·5단계 통과 여부·이상 항목)로 남긴다.

## 이관된 결정 (구 ADR)

- 백업 단위(Postgres `feature`/`provider_sync`/`ops` schema + RustFS bucket), 1차 NTFS
  `data/backups/<timestamp>/` + 2차 외부(S3/R2) multi-target, staging hot-swap(staging 복원 →
  smoke/count 검증 → connection pool DSN 교체) restore 패턴, 그리고 admin 라우터
  `GET/POST /admin/backups` · `POST /admin/restore/{id}` · `.../swap`은 모두
  본 runbook §2~§8에 정본화돼 있다 (구 ADR-040에서 결정). 근거: `pg_dump --format=custom`
  + RustFS snapshot이 industry-standard이고, 외부 소비자가 실시간 의존하므로 downtime cost가
  커 hot-swap으로 무중단 전환을 택했다(초기엔 cold restore 허용, dual DB 비용은 단계적 도입으로 완화).
