# Runbook — T-VN-H35 prod 마이그레이션 cutover (0063 → 0068)

이 문서는 `docs/tasks.md`의 **T-VN-H35 11단계**를 n150 production에서 실행하는 유일한
운영 순서다. **요구 정본은 task 본문이고 이 runbook은 그 11단계를 명령·게이트·실패
분기로 옮긴 것이다.** 실제 host·URL·계정·비밀번호·token·hash는 gitignore된
`docs/deploy-runbook.local.md`·`docs/prod-access.local.md`에만 둔다.

**이 절차는 hybrid다.** 척추는 direct 안의 **검증 게이트·복구 설계**이고, 이식한 것은
ktdctl(`kor-travel-docker-manager` 라이브러리) 쪽의 **build seam과 fence 층**이다. 근거:

- `ktdctl` CLI는 분해할 수 없다 — `pinvi-pair deploy`는 `recreate=True`를 하드코딩하고
  (`backend/src/kor_travel_docker_manager/services/cli.py:117-134`), `ensure --build`는
  production에서 `assert_c6c_mutation_allowed`가 capability 없이 호출돼 fail-closed되며
  (`compose_service.py:2626` → `c6c_deployment.py:541`), `capture`는 v4 manifest 존재로
  거부된다(`c6c_deployment.py:4299-4327`).
- 그러나 라이브러리 seam `_prepare_c6c_candidate_pair(cfg, build=True, …)`
  (`compose_service.py:3263-3322`)는 **build-only이고 실행 컨테이너를 전혀 보지 않는다**
  (`docker inspect <container>` 호출 없음, image inspect만) — **cold fence 아래에서도
  성립한다.** step 2/3의 유일한 sanctioned 경로다.
- 반대로 검증 게이트는 direct 안이 옳았다 — H36 판별자, 0068 최종 index shape, rename-swap
  복구 설계가 그것이다.

> **모든 실측값은 2026-07-30 읽기 전용 조사(8축) 결과다.** 이 문서에 박힌 image ID·OCI
> revision·row count·구조 md5는 **기대값이 아니라 대조 기준**이다. 실행 시점에 값이
> 다르면 **문서를 고치지 말고 중단하고 조사한다** — 그 자체가 out-of-band 변경의 증거다.
> raw probe 산출물은 `n150:/home/digitie/h35c/`에 있다.

관련: [`docker-app.md`](./docker-app.md) §8(cutover DDL) ·
[`c7-prod-live-e2e.md`](./c7-prod-live-e2e.md)(같은 배포 경계의 파괴적 실행 규약) ·
[`invalid-index-recovery.md`](./invalid-index-recovery.md)(0064/0068의 CONCURRENTLY 잔재) ·
[`../backup-restore.md`](../backup-restore.md) ·
[`../integration-map.md`](../integration-map.md).

---

## 1. 선행 조건 체크리스트

**전부 통과하기 전에는 step 0에도 들어가지 않는다.** 각 항목의 "없으면"이 실제 파손이다.

| # | 조건 | 확인 방법 (전부 `[R]`) | 없으면 |
|---|------|------------------------|--------|
| **P1** | **디스크 여유 ≥ 40 GiB** | `df -B1 --output=avail /` | step 5의 22.3 GiB scratch 복원 또는 step 10의 rollback DB가 disk full → **같은 파일시스템에 동거하는 geo·concierge·pinvi가 동시 장애**. 현재 실측 53.7 GiB(88% used)로 **미달이다** → step 0 선행 |
| **P2** | 잔여 restore DB **처리 방침 확정** | `kor_travel_geo_restore` 31.5 GiB · `kor_travel_map_restore` 38 MB · `kor_travel_map_dagster_restore` 25 MB · `kor_travel_map_restore_manual` 7.5 MB · `ktc_t1*` ~28개 | P1을 만족시킬 수단이 없다. `DROP DATABASE`는 **비가역**(§5 H-1) — 소유자·용도 확인이 승인 전제 |
| **P3** | prod cluster **superuser 도달 경로** | `docker exec kor-travel-geo-postgres psql -U addr -d postgres -Atc "select current_user, rolsuper from pg_roles where rolname=current_user"` → `addr\|t` | step 10 복구 경로가 없다 = **rollback 없음**. `krtour_map`은 `rolsuper=false`·`rolcreatedb=false`이고 6개 스키마·extension 5개 owner가 전부 `addr`이므로 `pg_restore`가 extension/owner에서 중단된다 |
| **P4** | P3의 **무자격증명 근거 재확인** | `docker exec kor-travel-geo-postgres tail -12 /var/lib/postgresql/data/pg_hba.conf` → `local all all trust` + `host all all 127.0.0.1/32 trust` + `host all all ::1/128 trust`(마지막 줄만 `all all all scram-sha-256`) | §3.4의 형식 이탈(PGSERVICEFILE/PGPASSFILE 미사용)에 근거가 없어진다. **동시에 이것이 fence에 인증 층이 없다는 뜻이다** — §8 L5의 존재 이유 |
| **P5** | `$CACHE_MGR/.env` **변경 성격 확정 + freeze** | 02:42 변경은 `KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH` **1키만**(`len=87 sha8=3bc99f5d` → `2f2a19e6`), 추가·삭제 0. `2f2a19e6`는 live UI 컨테이너 값과 일치 = 02:37 out-of-band UI recreate 뒤의 **정렬**이다 | window 중 이 파일을 다시 만지면 `_revalidate_compose_environment_snapshot`이 transaction을 중단시킨다. **H35 window 동안 `.env`·`docker-compose.yml` 변경 금지** |
| **P6** | 실행 pair가 manifest와 **drift 없음** | step 1의 `_pair_matches(_inspect_current_pair(cfg), manifest.active)` | 누군가 out-of-band recreate를 했다는 뜻 → 진행 금지, 상태 보존 |
| **P7** | prod alembic head가 **`0063_pipeline_root_id`** | `docker exec kor-travel-geo-postgres psql -U addr -d krtour_map -Atc "select version_num from public.alembic_version"` | 다른 값이면 **비인가 migration**이다. step 4로 진행하지 말고 상태를 보존해 조사한다(task step 3 명시) |
| **P8** | **outage 창 합의** | off-box HAProxy 소유자 통보. n150에는 maintenance surface가 없다(§8) | 공개 URL이 maintenance 페이지가 아니라 **502/503·tcp reset**을 낸다. 합의 없이 시작하면 예고 없는 장애다 |
| **P9** | 도구 준비 | §3.3 표의 "작성 대상" 7개가 실제로 존재 | 절차가 명령으로 뒷받침되지 않는다 |
| **P10** | `$T` 확정 | `git -C $MAP_CTX rev-parse origin/main` **그리고** `git -C $MAP_CTX merge-base --is-ancestor 653d82a2 $T` (H36 포함) | H36이 없는 이미지를 배포하면 step 7의 유일한 명시 게이트가 원리적으로 실패한다. task 명시로 **H36이 H35보다 먼저**다 |

**금지(전 구간).** `docker image prune` — reclaimable 24.28 GB 안에 step 1의 rollback image
set이 들어 있다. `docker builder prune`(73.8 GB reclaimable)은 **step 2 build 성공 이후 ·
step 5 복원 이전에만**, 승인 아래(§5 H-8).

---

## 2. 단계 지도와 fence 구간

| step | 무엇 | 표기 | fence |
|------|------|------|-------|
| 0 | 디스크 회수 (신규·선행) | `[W][S]` ⛔ | — |
| 1 | rollback image set 고정 + baseline bundle | `[W]`(태그만) | — |
| 2 | candidate build-only (컨테이너 0개) | `[W]`(이미지·태그만) | — |
| 3 | H36 게이트 offline 확인 + H36 pre 측정 + prod head 재확인 | `[R]` | — |
| 4 | **cold writer fence 진입** (5층) | `[W][S]` ⛔ | **진입** |
| 5 | 백업·복원 gate (+5.5 scratch 리허설) | `[W]`(scratch·파일) | 유지 |
| 6 | API candidate recreate → 0064~0068 적용 | `[W]` ⛔ **비가역 시작** | 유지 |
| 7 | fence 안 구조 실증 | `[R]` | **유지(여기까지 필수)** |
| 8 | post-migration bundle · daemon preflight | `[W]`(scratch·파일) | 유지 |
| 9 | 비-daemon 3 service recreate·health | `[W]` | 유지 |
| 10 | (실패 시) 복구 분기 — DB rename swap + exact rollback image | `[W]` ⛔ | 유지 |
| 11 | forward-only cutover · manifest 재정합 · fence 해제 | `[W]` ⛔ | **해제** |

**fence는 step 4-7 통과부터 step 11-6까지 끊기지 않는다.** task step 4가 "dump·migration·
구조 smoke가 끝날 때까지"라고 못 박았고, **컨테이너 정지만으로는 step 6부터 유지가
불가능하다** — candidate API가 `network_mode: host`로 `0.0.0.0:12701`에 되살아나므로
LAN·off-box HAProxy·PinVi가 다시 write 가능해진다. 그 구멍을 §8의 L2(iptables)가 덮는다.

---

## 3. 공통 기반

### 3.1 경로·상수

```bash
CACHE_MGR=/home/digitie/.cache/c7-final.pihf0x9o/manager   # prod compose project 루트
MAP_CTX=/home/digitie/.cache/c7-final.pihf0x9o/map         # map build context
H35=/home/digitie/h35/run                                  # mode 700, owner digitie
T=ddd1308cf7350862ded97df8ca0ff72d70ec2c73                 # P10에서 재확인
RB_REV=c8ed6164381fccd35df1840427e5a682f2a2789d            # 현행 map 4 service revision
```

- compose project = `kor-travel-docker-manager`, 단일 파일 `$CACHE_MGR/docker-compose.yml`
  (858줄). override 파일이 존재하면 mutation이 거부된다(`compose_service.py:2310-2313`).
  **map 저장소의 `docker-compose.external-infra.yml`은 이 배포에서 쓰이지 않는다.**
- prod DB = **같은 compose project의 형제 service** `kor-travel-geo-postgres`
  (`postgis/postgis:16-3.5`, image id `8b33190b6486`, `network_mode: host`, PGDATA bind
  `/home/digitie/kor-travel-geo-data/pgdata-final-20260529`, `:5432`). 대상 DB는
  **`krtour_map`(22.27 GiB) / `krtour_map_dagster`(744 MiB)** 이고 `kor_travel_map*`은
  별개의 잔여 DB다. `wal_level=replica`·**`archive_mode=off`(PITR 없음)**.
- 현행 5 service identity (step 1에서 재측정해 대조):

| service | container | image ID | revision |
|---|---|---|---|
| `kor-travel-map-api` | `kor-travel-map-api-latest` | `sha256:40d6d30d6496…` | `c8ed6164…` |
| `kor-travel-map-ui` | `kor-travel-map-ui-latest` | `sha256:262ea36ac6b0…` | `c8ed6164…` |
| `kor-travel-map-dagster` | `…-dagster-latest` | `sha256:c9d0a44998b3…` | `c8ed6164…` |
| `kor-travel-map-dagster-daemon` | `…-daemon-latest` | `sha256:d8def28e364e…` | `c8ed6164…` |
| `pinvi-api` (HELD, 미접촉) | `pinvi-api-latest` | `sha256:817136819f08…` | `6a035695…` |

- **현행 active 이미지에는 immutable 태그가 하나도 없다.** retention 네임스페이스
  `kor-travel-docker-manager/c6c-retention/<svc>:<64hex>` 5개는 **전부 rollback
  pair(`b0c95672`/pinvi `58e12959`)** 몫이고, `c8ed6164` pair는 `:latest-main` 5개 +
  실행 컨테이너만이 유일한 참조다. **step 1이 태그를 만들기 전에 build하면
  `docker image prune` 한 번에 소멸한다.**

### 3.2 compose driver — 라이브러리 seam만 쓴다

**raw `docker compose`를 쓰지 않는다.** 모든 compose mutation은
`$H35/bin/h35ctl.py`(작성 대상)가 manager 라이브러리를 통해 발화한다. 이유 두 개:

1. `$CACHE_MGR/.env:38` `KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH`는 **quote 없이 `$` 3개**를
   포함한다(pbkdf2 salt). `docker compose --env-file <그 .env>`를 쓰면 hash가
   **fp `432b92a2` len 66**으로 훼손된다(정답 = live = fp `2f2a19e6` len 87, 실측) →
   UI admin login이 깨진다. 라이브러리 경로는 `dotenv_values`(braces-only 보간) →
   **process env** → `--env-file /dev/null --project-directory $CACHE_MGR -f -`(stdin)이라
   그 경로가 **구조적으로 불가능**하다(`compose_service.py:1461-1491`, `2126-2131`).
2. stdin materialization·volume graph freeze·protected-value 검증·`config_files=-`
   라벨 동일성·retention 계약이 sanctioned deploy와 동일하게 유지된다.

호출 규약 (모든 step 공통):

```bash
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && \
  HOME=/home/digitie ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py <step> [--confirm]'
```

- **`sudo`로 실행하지 않는다** — `HOME=/root`가 되면 manifest 경로가 사라진다.
  production에서 `KTDM_C6C_STATE_ROOT`/`KTDM_C6C_COMPATIBLE_PAIR_MANIFEST`/
  `KTDM_C6C_DEPLOYMENT_LOCK` override는 전부 거부된다(`c6c_deployment.py:671-709`).
- `--confirm` 없으면 모든 mutation step은 **계획만 출력한다**(dry-run 기본).
- lock은 **step 단위로** 잡고 놓는다(`c6c_deployment_lock(get_c6c_deployment_lock_path())`,
  `run()`이 `_HELD_DEPLOYMENT_LOCKS` contextvar로 재진입한다 — `c6c_deployment.py:619-651`).
  22 GB dump 중 프로세스가 죽으면 window 전체 보유는 stale lock이 된다. 대신 **모든
  mutation step이 진입 시 기대 pre-state를 재검증한다.**
- driver의 핵심 seam (전부 배포 rev `c7328ed9`에서 시그니처 확인):

```python
tx, _ = compose_service._capture_transaction_unlocked(derive_manifest_path=True)
assert_manager_mutation_allowed(environment=tx.environment.effective)
cfg = load_c6c_deployment_config_from_environment(tx.environment.effective)
# build-only:   _prepare_c6c_candidate_pair(cfg, build=True, build_provenance=prov, transaction=tx)
# service 정지: compose_service.run(["stop", …], mutation_capability=_COMPATIBLE_PAIR_MUTATION_CAPABILITY, transaction=tx)
# service recreate: compose_service._run_up_stage(result, stage, services, build=False,
#     recreate=True, no_deps=True, wait=False, environment=env,
#     mutation_capability=_COMPATIBLE_PAIR_MUTATION_CAPABILITY, redact_config=cfg, transaction=tx)
```

`wait=False`가 필수다 — `_run_up_stage`의 `--wait --wait-timeout 120`은 하드코딩이고
(`compose_service.py:3540`) 0064~0068이 120초를 넘기면 마이그레이션은 계속 도는데 stage가
실패한다. health는 별도 폴링으로 본다.

**금지 명령 (driver·runbook 양쪽에 명시).**
`docker compose … up|create|run|start kor-travel-map-api`(`--no-deps` 무관) ·
`up --build` · `docker run/create <candidate-api>`(entrypoint override 없이) ·
`ktdctl pinvi-pair deploy [--build]` · `ktdctl pinvi-pair rollback` ·
`ktdctl ensure map --build` · **`--remove-orphans`**(같은 project에 geo/concierge/monitoring
17개가 함께 있다) · `--env-file <그 .env>` · `docker image prune` ·
`dagster schedule wipe` · `scripts/docker-backup.sh`.

### 3.3 도구

| 파일 (`n150:/home/digitie/h35c/` 또는 `$H35/bin/`) | 역할 | 상태 |
|---|---|---|
| `h35_instigation.py` | step 4 `record`/`pause`/`verify` + step 11 `restore`. `canReset` 기반 저장값 판별 | **존재** — `record`·`verify`·양쪽 dry-run 실검증 |
| `h35_fence_probe.py` | 13개 fence 게이트, fail-close, exit code 판정 | **존재** — 실검증(`FENCE_DIRTY`, `map_owned_app_backends`만 미충족) |
| `h35-structural-gate.sql` | G01~G20 구조 게이트 | **존재** — pre(0063) 값 실측 완료 |
| `h35d_key.sql` | K01~K03 `collection_key` shape 게이트 | **존재** — pre 실측 완료 |
| `h35ctl.py` | §3.2 driver | **작성 대상** |
| `h35-identity-52.sql` | 52 테이블 `count(*)` + `sum(hashtextextended(t::text,0))` | **작성 대상** |
| `h35_changes_collect.py` | step 8 concierge `changes` 전량 수집 | **작성 대상** |
| `h35_env_negcheck.py` | scratch 컨테이너 env 음성 검사 | **작성 대상** |
| `h35_mk_preview_conf.py` | H36 preview용 `curl --config` 생성(mode 600) | **작성 대상** |
| `partial-state.sql` | step 6 부분 적용 probe | **작성 대상** |
| `h35_record_rollback.py` | step 1 identity 채취 | **작성 대상** |

### 3.4 비밀 취급 — 그리고 형식 이탈의 근거

| 표면 | 방식 | 왜 안전한가 |
|---|---|---|
| prod DB 읽기·dump·복원 | `docker exec kor-travel-geo-postgres psql/pg_dump -U addr` (컨테이너 unix socket) 또는 pinned client `postgres:16` + `--network host` + `-h 127.0.0.1 -U addr` | **자격증명이 존재하지 않는다** — P4의 `local all all trust` + `host all all 127.0.0.1/32 trust` 실측. argv·env·파일 어디에도 비밀이 없다 |
| compose 실행 | 전부 `compose_service.run(…, transaction=tx)` | §3.2-1 |
| admin proxy secret / UI admin password / concierge API key | `docker inspect`·`cfg`에서 읽어 **process env** → `curl --config <mode 600>`, 사용 후 `shred -u` | argv 미노출, `ps` 미노출, artifact에 header 미포함 |
| scratch DB | **throwaway 자격증명만.** `pg_service.conf`(비밀 없음, mode 600) + `pgpass`(throwaway, mode 600, 종료 후 shred) | prod 비밀이 scratch 경로에 없다 |
| artifact | env는 **키 이름 + `len` + `sha256[:8]`만** | task step 1 명시 |

> **형식 이탈 기록 (감사 대상).** task step 5는 "`PGSERVICEFILE`/`PGPASSFILE` 기반의 pinned
> PostgreSQL client"를 명시한다. 이 runbook은 **prod 쪽에서 그 형식을 쓰지 않고 컨테이너
> local trust / `127.0.0.1/32` trust로 대체한다.** 근거는 P4의 실측이며, 목적("비밀을
> argv/log에 싣지 않는다")은 **비밀이 존재하지 않음**으로 더 강하게 만족된다. 또한 `-U addr`
> dump는 owner/ACL 충실도가 더 높고 §8 L5(`CONNECTION LIMIT 0`)와 양립한다(superuser는
> `datconnlimit` 예외). client pinning 근거는 "서버 컨테이너 내장 pg_dump가 서버와 정확히
> 동일한 16.9"(실측: `Dumped from 16.9 / Dumped by pg_dump 16.9`)로 갈아 끼운다.
> **이 문단을 산출물에 함께 넣지 않으면 감사에서 무근거 우회로 읽힌다.**

**절대 금지.** `-e PGPASSWORD=<literal>`(→ `docker inspect`·`docker run` argv 노출) ·
`psql "postgresql://user:pass@…"`(→ argv) · `. $CACHE_MGR/.env`(`set -u`에서
`line 38: $3: unbound variable`로 즉사) · `set -x`/`bash -x` ·
**보간 완료된 `docker compose config` 결과를 디스크에 남기는 것**(task step 1 명시 금지).
env 대조가 필요하면 stdin 파이프로만 흘리고 `{키: sha8/len}`과 `divergent_keys`만 남긴다:

```bash
# 착지 금지. `> resolved.json` 형태를 쓰지 않는다.
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py resolved-config \
  | python3 /home/digitie/h35/run/bin/h35_env_negcheck.py --fingerprint-only \
      --live-container kor-travel-map-ui-latest > /home/digitie/h35/run/ui-env-fp.json'
```

`$CACHE_MGR/.env`에는 `KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH` 원문과
`${KOR_TRAVEL_MAP_DOCKER_PG_DSN:-postgresql+asyncpg://krtour_map:…@127.0.0.1:5432/krtour_map}`
(`docker-compose.yml:410`)이 들어 있으므로 `config` 출력은 **비밀 원문 그 자체**다.

### 3.5 폐기 대상 산출물

`/home/digitie/h35/backup/krtour_map-20260730T010600Z.dump`(1.21 GB, `root:root` mode 644)는
**rollback source로 쓰지 않고 signed bundle에도 넣지 않는다.** 무효 사유: (a) fence 없이 떴다
(01:06 이후 write 전부 소실, `archive_mode=off`로 roll-forward 없음), (b) `krtour_map_dagster`
dump가 호스트 어디에도 없다, (c) `SHA256SUMS`·manifest·`pg_restore --list`·복원 시도 0건,
(d) step 1 결속 없음, (e) 생성 스크립트 `h35_backup.sh`가 mode 775 + argv에 password 리터럴
(주석은 정반대로 적혀 있다). `$H35/rehearsal/`로 개명해 이름으로 무효를 못 박는다
(`[sudo]`, §5 H-2). **형식·툴체인만 재사용 가능하다** — TOC가 `TABLE DATA` 정확히 52건 +
extension 5 + SEQUENCE SET 6으로 content-complete·owner/ACL 보존형임을 증명한다.

---

## 4. step 0 — 디스크 회수 (선행, 신규) `[W][S]` ⛔

**목적.** P1을 만족시킨다. 이 단계 없이는 step 5 또는 step 10이 disk full로 실패하고,
그 실패는 동거하는 geo·concierge·pinvi를 함께 죽인다.

**명령.**

```bash
# 0-1 [R] 회수 후보 열거
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d postgres -X -A -F "|" -c \
  "select datname, pg_size_pretty(pg_database_size(datname)), datdba::regrole::text \
     from pg_database order by pg_database_size(datname) desc limit 15"'
wsl ssh n150 'df -B1 --output=avail /; docker system df'

# 0-2 [W][S] ⛔ 승인 후 사람이 실행 — DROP DATABASE (krtour_map은 rolcreatedb=false라 재생성 불가)
#     docker exec kor-travel-geo-postgres psql -U addr -d postgres -c "DROP DATABASE <name>"
```

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| `df -B1 --output=avail /` | ≥ `42949672960` (40 GiB) | 미달 → **step 5 진입 금지.** 값이 곧 판정이다 |
| 회수 대상이 어떤 task 산출물도 아님 | 소유자·용도 확인 기록 | 확인 없이 지우면 타 task 산출물이 사라진다 |

**실패 시 분기.** 40 GiB에 도달하지 못하면 `docker builder prune`(73.8 GB reclaimable)을
승인 아래 쓴다 — **단 step 2 build 성공 이후·step 5 복원 이전에만**(캐시 소실로 재빌드가
느려지므로). `docker image prune`은 전 구간 금지. 그래도 미달이면 H35를 시작하지 않는다.

---

## 5. step 1 — rollback image set 고정 + baseline bundle `[W]`(태그만)

**목적.** candidate build 전에 현행 pair를 **비-컨테이너 참조로 고정**한다. 이것이
성립하기 전의 어떤 build도 `c8ed6164` pair를 dangling으로 만든다(§3.1).

**명령.**

```bash
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step1 --confirm'
```

driver가 하는 일 (`deploy_compatible_pinvi_pair`의 step 5, `compose_service.py:3010-3017`과
**동일 함수**):

```python
with c6c_deployment_lock(get_c6c_deployment_lock_path()):
    tx, cfg = open_tx()
    m = load_pair_manifest(tx.manifest_path)                 # 9키 엄격 검증
    for p in (m.rollback, m.active):
        assert p.contract_generation == cfg.contract_generation      # "c6c-ops-v1"
        compose_service._require_pair_image_provenance(p)            # 로컬 존재 + 라벨 일치
    assert compose_service._pair_matches(compose_service._inspect_current_pair(cfg), m.active)
    rep = reconcile_pair_references((m.active, m.rollback), cwd=get_project_root())
```

같은 bundle에 결속할 read-only 산출물:

```bash
# 1-2 [R] 5개 컨테이너 identity (env는 키 이름 + sha8/len만)
wsl ssh n150 'for c in kor-travel-map-api-latest kor-travel-map-ui-latest \
    kor-travel-map-dagster-latest kor-travel-map-dagster-daemon-latest pinvi-api-latest; do \
  docker inspect "$c" --format "{{.Name}} {{.Image}} \
{{index .Config.Labels \"org.opencontainers.image.revision\"}} \
{{index .Config.Labels \"com.docker.compose.config-hash\"}} \
{{index .Config.Labels \"com.docker.compose.project.config_files\"}} \
{{index .Config.Labels \"com.docker.compose.project.working_dir\"}} {{.RestartCount}}"; \
done > /home/digitie/h35/run/containers-pre.txt'

# 1-3 [R] 0063 구조 baseline + collection_key shape
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F "|" \
  -f - < /home/digitie/h35c/h35-structural-gate.sql > /home/digitie/h35/run/gate-pre.txt'
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F "|" \
  -f - < /home/digitie/h35c/h35d_key.sql >> /home/digitie/h35/run/gate-pre.txt'

# 1-4 [R] 현행 smoke — login POST 200 / API 200 / Dagster web 200 / UI build-info
wsl ssh n150 'curl -sS -o /dev/null -w "api=%{http_code}\n"     http://127.0.0.1:12701/health'
wsl ssh n150 'curl -sS -o /dev/null -w "dagster=%{http_code}\n" http://127.0.0.1:12702/'
wsl ssh n150 'curl -sS http://127.0.0.1:12705/api/build-info'
wsl ssh n150 'curl -sS --config /home/digitie/h35/run/secrets/curl-login.conf \
  -o /dev/null -w "login=%{http_code}\n"'

# 1-5 [R] ktdctl 쪽 baseline
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/ktdctl status pinvi --json \
  > /home/digitie/h35/run/ktdctl-status-pre.json'
```

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면(= 다른 값) |
|---|---|---|
| `rep.ensured` / `rep.removed` | **5 / 0** — active 5개가 신규 태깅됨 | `ensured != 5`면 이미 태그가 있었다는 뜻 = 전제가 다르다 |
| `_owned_references` | 정확히 **10개**(active 5 + rollback 5) | 10이 아니면 retention 상태가 기대와 다르다 → 중단 |
| retention ref 5개의 `.Id` | `containers-pre.txt`의 `.Image` 5개와 문자 단위 일치 | 다른 ID/`No such image` → 기록이 잘못됐다 |
| `_pair_matches` | True (P6) | False = out-of-band recreate 발생 → 진행 금지, 상태 보존 |
| `alembic_version` | `0063_pipeline_root_id` 정확히 1행 | 다른 값 → **비인가 migration**(P7) |
| UI `/api/build-info` | 200 + `revision == c8ed6164…` + `source_digest` 64-hex | **503 `BUILD_REVISION_UNAVAILABLE`** = 현행 UI가 이미 revision 라벨 없이 빌드된 것 → step 9/10의 UI identity 기준이 무의미해진다 |
| 4개 map revision | 전부 `c8ed6164…` | 하나라도 다르면 현행이 이미 혼재 배포 상태 |

**반증성의 근거.** 지금 active 이미지에는 immutable 태그가 **하나도 없다**(실측). 통과가
곧 "이제 `c8ed6164`가 `:latest-main` 없이도 보존된다"는 증거다.

**쓰지 않는 기준.** "`docker ps` 5/5 Up" — 현행이 실제로 그러니 항상 통과하고 아무것도
반증하지 못한다.

**실패 시 분기.** 어떤 항목이든 실패하면 **step 2로 가지 않는다.** 태그만 만들어진 상태는
무해하므로 되돌릴 필요가 없다. `_pair_matches` 불일치는 상태 보존 + 조사 대상이다.

**UI 특이사항(기록 필수).** `kor-travel-map-ui-latest`는
`/home/digitie/reset-map-ui-admin-password.sh`(root, **`docker create`** — compose 아님)가
2026-07-30 02:37:37Z에 out-of-band recreate했고 라벨을 원본에서 복사했다:
`config_files=/home/digitie/kor-travel-docker-manager/docker-compose.yml`,
`working_dir=/home/digitie/kor-travel-docker-manager`(다른 3개는 `config_files=-`,
`working_dir=$CACHE_MGR`). image ID는 manifest `.active.map_ui_image_id`와 같으므로
identity는 보존됐다. **step 9의 recreate가 이 라벨을 compose 기준으로 정규화한다** — 복구
대상이 아니라 정정 대상이며, 그 변화 자체를 candidate manifest에 기록한다.

---

## 6. step 2 — candidate build-only (컨테이너 0개) `[W]`(이미지·태그만)

**목적.** `$T`(H36 포함 main tip)로 API·UI·Dagster web·Dagster daemon 이미지를 준비하고
immutable candidate 참조를 만든다. **candidate 컨테이너를 만들지도 기동하지도 않는다.**

**명령.**

```bash
# 2-1 [R] 빌드 컨텍스트를 목표 revision으로 (clean HEAD가 provenance 원천)
wsl ssh n150 'git -C /home/digitie/.cache/c7-final.pihf0x9o/map fetch origin --prune'
wsl ssh n150 'git -C /home/digitie/.cache/c7-final.pihf0x9o/map checkout --detach \
  ddd1308cf7350862ded97df8ca0ff72d70ec2c73'
wsl ssh n150 'git -C /home/digitie/.cache/c7-final.pihf0x9o/map status --porcelain=v1 \
  --untracked-files=normal'          # 반드시 빈 출력
wsl ssh n150 'git -C /home/digitie/.cache/c7-final.pihf0x9o/map merge-base --is-ancestor \
  653d82a2 HEAD && echo H36_INCLUDED'

# 2-2 [R] UI 빌드 인자 완전성 게이트 — 값은 출력하지 않고 sha8/len만 (§3.4)
#   NEXT_PUBLIC_VWORLD_API_KEY / NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY 가 비면 exit 1
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py buildargs-gate'

# 2-3 [R] 기대 frontend source digest 선계산
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/map && node scripts/frontend-source-digest.mjs'

# 2-4 [R] 컨테이너 집합 스냅샷
wsl ssh n150 'docker ps -a --filter label=com.docker.compose.project=kor-travel-docker-manager \
  --format "{{.Names}} {{.CreatedAt}} {{.Image}}" | sort > /home/digitie/h35/run/containers-pre-build.txt'

# 2-5 [W] build-only
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step2 --confirm'
```

driver (`deploy`의 step 6·8, `compose_service.py:3019-3040`과 **동일 함수·동일 순서**):

```python
with c6c_deployment_lock(get_c6c_deployment_lock_path()):
    tx, cfg = open_tx()
    assert owned_reference_count() == 10, "step1 retention이 없다"        # 재검증 = 유일한 방어
    prov = _derive_c6c_build_provenance(tx.environment.effective,
                                        compose_path=tx.environment.compose_path)
    assert prov.map_source_revision == T                                  # dirty worktree면 abort
    pair, build = compose_service._prepare_c6c_candidate_pair(
        cfg, build=True, build_provenance=prov, transaction=tx)           # ← 컨테이너 무변경
    ensure_pair_references((pair,), cwd=get_project_root())               # immutable candidate tag
    json.dump(asdict(pair), open(f"{ART}/candidate-pair.json", "w"), sort_keys=True)
```

**"candidate API 기동 0회"를 어떻게 보장하는가 — 네 겹.**

1. **경로 자체가 컨테이너를 만들지 않는다.** build는 `_prepare_c6c_candidate_pair:3300`의
   `self.run(["build", …])` 한 곳, 컨테이너 생성은 `_run_up_stage:3536`의 `args=["up","-d"]`
   한 곳이며 **build 경로 어디에도 `create`/`run`/`start`가 없다.** 주석 `:3271`이
   "container 변경 없이 build/attest한다"고 명시한다.
2. **driver가 `up`/`create`/`run`/`start`를 어떤 형태로도 발화하지 않는다.**
   `ktdctl pinvi-pair deploy`도 부르지 않는다 — `deploy`는 build 직후
   `_activate_pair_sequentially`로 넘어가 중간 종료점이 없다.
3. **step 3의 검사가 기본 entrypoint를 대체한다** — `--entrypoint sh -c '…'`가
   `Entrypoint=null` / `Cmd=["./docker/api-entrypoint.sh"]`(`api.Dockerfile:52`)를 **둘 다**
   덮고 `--network none`이라 5432에 도달 자체가 불가하다.
4. **사후 반증.** 아래 검증표 + step 3의 prod head. candidate API가 한 번이라도 기본 CMD로
   떴다면 `docker/api-entrypoint.sh:215` `while ! alembic upgrade head; do`가 즉시 돌아
   head가 전진하므로 **`0063` 유지가 위반의 직접 부재 증거**다.

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| `docker ps -a`(project 필터) 목록 | `containers-pre-build.txt`와 **글자 단위 동일**(21행, Created 시각 포함) | 새 행/Created 변경 = **step 2 위반** |
| candidate 이미지 참조 컨테이너 | `docker ps -a --filter ancestor=<CAND_API_ID> -q \| wc -l` → **0** | 0이 아니면 위반 |
| candidate 4개 `org.opencontainers.image.revision` | 4개 모두 `$T` | `development` = `KOR_TRAVEL_MAP_GIT_COMMIT` 주입 실패(seam은 `provenance.compose_environment()`로 항상 주입하므로 이 경로에서는 발생 불가 — raw `docker compose build`를 쓰지 않는 이유다). 그러면 UI `/api/build-info`도 503이 된다 |
| `_owned_references` | **15개**(active 5 + rollback 5 + candidate 5). candidate 태그는 `…c6c-retention/<svc>:<image id 64hex>` = 태그 자체가 image ID이므로 immutable이고 rollback 태그와 다르다 | 15가 아니면 태깅 실패 |
| **이전 pair 보존** | `docker image inspect <c8ed6164 retention ref> --format '{{.Id}}'` 5건이 여전히 유효 | 무효 = 이전 pair를 잃었다 → 즉시 중단 |
| candidate UI 이미지의 `FRONTEND_SOURCE_DIGEST` | 2-3의 선계산값과 동일 | 다르면 빌드 소스가 `$T`가 아니다 |

**인정하고 승인 항목에 올리는 부작용 2개** (§5 H-3):

- `_prepare_c6c_candidate_pair`는 `["build", *_MAP_RUNTIME_SERVICES, _PINVI_API_SERVICE]`를
  **하드코딩**하므로(`compose_service.py:3301`) build env에 `*_IMAGE`가 없어
  **`:latest-main` 5개가 그 자리에서 candidate로 옮겨간다.** task step 2의 금지는
  "기본 tag를 덮어 **이전 pair를 잃는** build"이고, step 1의 retention 태그가 먼저
  성립했으므로 **잃지 않는다** — 그것이 `_owned_references == 10` 사전 assert가 유일한
  방어인 이유다.
- 같은 이유로 **범위 밖 `pinvi-api`도 rebuild되어 `pinvi-api:latest-main`이 이동한다.**
  소스는 HELD `6a035695` 그대로라 revision 라벨은 같고 image ID만 달라진다. 실행 중
  `pinvi-api-latest`는 건드리지 않으며 현 image `817136819f08…`은 step 1의 retention 태그가
  잡고 있다. **pinvi build 실패는 map build까지 abort시킨다.**

**실패 시 분기.** build 실패는 무해하다(컨테이너 무변경) — 원인 수정 후 재실행한다. 단
**재실행 전에 `_owned_references`에 `c8ed6164` 5개가 살아 있는지 다시 확인한다.** 부분
실패 상태에서 태그가 사라지면 그 시점부터 이전 pair가 dangling이다.

---

## 7. step 3 — H36 게이트를 DB와 단절해 확인 `[R]`

**목적.** 커밋 라벨이 아니라 **image layer 내용**으로 H36·0064~0068·H28A 규칙 교체를
확인하고, 그 직후 prod head가 여전히 `0063`인지 확인한다. 그리고 step 7 게이트의
**반증 상대값(pre)** 을 구 이미지로 떠 둔다.

**명령.**

```bash
CAND_API=$(jq -r .map_image_id            /home/digitie/h35/run/candidate-pair.json)
CAND_DG=$( jq -r .map_dagster_image_id    /home/digitie/h35/run/candidate-pair.json)

# 3-1 [R] API 이미지 offline 검사 — env 0개, network 0개, entrypoint+CMD 둘 다 override
wsl ssh n150 "docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --entrypoint sh $CAND_API -c '
  set -e
  P=/usr/local/lib/python3.12/site-packages/kortravelmap
  F=\$P/api/routers/curations.py
  test -f \"\$F\"; sha256sum \"\$F\"
  echo H36_CODE=\$(grep -c \"name_only_match\" \"\$F\")
  echo H36_STATUS=\$(grep -c \"review_required\" \"\$F\")
  echo GUARD=\$(grep -c \"def _adopted_match\" \"\$F\")
  echo NEW_DTO=\$(test -f \$P/dto/admin_evidence.py && echo 1 || echo 0)
  echo MIG=\$(ls /app/alembic/versions/006[4-8]_*.py | wc -l)
  ls /app/alembic/versions/0068_integrity_last_seen.py'"

# 3-2 [R] Dagster 이미지 — H28A 규칙 교체
wsl ssh n150 "docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --entrypoint sh $CAND_DG -c '
  V=/usr/local/lib/python3.12/site-packages/kortravelmap/dagster/validation.py
  echo NEW_RULE=\$(grep -c provider_address_region_disagreement \$V)
  echo OLD_RULE=\$(grep -c provider_address_mismatch \$V)'"

# 3-3 [R] 라벨·CMD는 컨테이너 없이
wsl ssh n150 "docker image inspect $CAND_API --format \
  '{{index .Config.Labels \"org.opencontainers.image.revision\"}} {{json .Config.Entrypoint}} {{json .Config.Cmd}}'"

# 3-4 [R] 직후 prod head 재확인
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d krtour_map -Atc \
  "select version_num from public.alembic_version"'

# 3-5 [R] H36 pre 측정 — **구 이미지(c8ed6164)** API에 같은 요청을 떠 둔다 (fence 전이라 API가 살아 있다)
wsl ssh n150 'python3 /home/digitie/h35/run/bin/h35_mk_preview_conf.py \
  --container kor-travel-map-api-latest \
  --csv /home/digitie/.cache/c7-final.pihf0x9o/map/resources/curations/korean-tourism-100-2025-2026.csv \
  --out /home/digitie/h35/run/secrets/curl-preview-2025.conf'
wsl ssh n150 'sha256sum /home/digitie/.cache/c7-final.pihf0x9o/map/resources/curations/korean-tourism-100-*.csv \
  > /home/digitie/h35/run/h36-csv.sha256'
wsl ssh n150 'curl -sS --config /home/digitie/h35/run/secrets/curl-preview-2025.conf \
  -o /home/digitie/h35/run/h36-preview-pre-2025.json -w "%{http_code}\n"'
# 2023-2024 CSV 도 동일하게 1회

# 3-6 [R] API 컨테이너의 admin proxy 신뢰 CIDR 확인 (step 7 게이트 실행 가능성)
wsl ssh n150 'docker inspect kor-travel-map-api-latest \
  --format "{{range .Config.Env}}{{println .}}{{end}}" | grep -c "ADMIN_TRUSTED_PROXY_CIDRS"'
```

**`curl --config` 파일 내용** (mode 600, 사용 후 `shred -u`. 비밀은 argv에 싣지 않는다):

```
url     = "http://127.0.0.1:12701/v1/admin/curations/import?dry_run=true"
request = "POST"
header  = "X-Kor-Travel-Map-Admin-Proxy-Secret: <값>"
header  = "X-Kor-Travel-Map-Actor: h35-cutover"
form    = "file=@/…/korean-tourism-100-2025-2026.csv;type=text/csv"
```

> **URL·인증 정정 (task 실행 가능성의 전제).** 올바른 경로는
> **`POST /v1/admin/curations/import?dry_run=true`** 다 —
> `app.py:804-808`이 `include_router(admin_curations_router, prefix="/v1", dependencies=admin_dependencies)`,
> `routers/curations.py:35`가 `admin_router = APIRouter(prefix="/admin/curations")`,
> `:623`이 `@admin_router.post("/import")`다. `/admin/curations/import`는 404다.
> **인증은 3층 전부 필요하다**(`auth.py:199-239` `require_admin_frontend`):
> (a) peer가 `admin_trusted_proxy_cidrs`에 속함(기본 `["127.0.0.1/32","::1/128"]`,
> `settings.py:315-319` → **loopback 호출이면 통과**), (b)
> `X-Kor-Travel-Map-Admin-Proxy-Secret`(`auth.py:65`), (c)
> `X-Kor-Travel-Map-Actor`(`auth.py:64`, `:232-237` 없으면 403).
> 셋 중 하나라도 없으면 403이고, 그러면 pre 측정도 얻지 못해 step 7의 "반증 가능해야 한다"가
> 무너진다. `dry_run=true`는 write 0건이다 — `curations.py:790` `if not dry_run:` 아래에서만
> `import_curation_rows`+commit이 일어난다.

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| `H36_CODE` | ≥ 1 | 0 = candidate가 H36을 담고 있지 않다. **`c8ed6164`에서 이 문자열은 0 hit(git 실측)이므로 이 값은 실제로 before/after를 가른다** |
| `H36_STATUS` | ≥ 1 (`ImportRowStatus` Literal에 `review_required` 존재, `curations.py:385-392`) | 0 = 구 Literal → step 7의 1차 판별자가 없다 |
| `GUARD` | 1 (`_adopted_match`, `curations.py:511-528`) | 0 = 구 무가드 `matches[0] if len(matches)==1` |
| `NEW_DTO` / `MIG` | 1 / **5** | 0 / <5 = 빌드 소스가 `$T`가 아니다. `c8ed6164`에는 `admin_evidence.py`·0064~0068이 **전부 없다**(실측) |
| `NEW_RULE` / `OLD_RULE` | ≥1 / 0 | 구 규칙 유지 = #673 회복 불가 |
| 3-3 | `$T` / `null` / `["./docker/api-entrypoint.sh"]` | 라벨 불일치 → 중단. **라벨 단독은 빌드 컨텍스트를 증명하지 않는다**(task 명시)이므로 3-1의 content 축과 반드시 병용 |
| 3-4 prod head | **`0063_pipeline_root_id`** | 다른 값 → step 4로 진행하지 말고 **비인가 migration으로 취급, 상태 보존·조사**(task step 3 명시) |
| 3-5 pre 응답 | HTTP 200. 3개 행이 `status="valid"` + `resolved_feature_id` 채워짐이면 pre→post가 가장 선명하게 갈린다 | 403 = 인증 3층 중 결락 → 게이트 설계 수정 후 재시도. pre에서 이미 `ambiguous`/`unmatched`면 **`resolved_feature_id is null` 축은 그 행에서 비판별**이므로 그 사실을 기록하고 step 7에서 `review_required`/`name_only_match` 축만 쓴다 |
| 3-6 | `127.0.0.1/32` 포함 | 불포함 → API 직접 호출로 preview를 할 수 없다 → step 4에서 UI를 세우면 안 되는 분기가 된다(설계 재검토) |

**쓰지 않는 기준.** `docker run <cand> alembic current` — 새 컨테이너의 기본 CMD를 타므로
step 2 위반이고 DB 접속도 필요하다. `site-packages/../../../../app/alembic/…` 경로 —
`/usr/app/alembic/…`으로 오해석돼 **항상 실패한다.** 이미지 안 정본 경로는
`/app/alembic/versions`다(`api.Dockerfile:41` `COPY alembic ./alembic`).

**실패 시 분기.** 3-1~3-3 실패 → step 2로 되돌아가 `$T`·build arg를 고친다(prod 무영향).
3-4 실패 → **fence에 들어가지 않는다.** 3-5가 403 → 게이트를 고친 뒤 다시 pre를 뜬다.
pre 없이 step 7에 들어가면 그 게이트는 "실패해도 통과하는 기준"이 된다.

---

## 8. step 4 — cold writer fence 진입 `[W][S]` ⛔

**목적.** dump 시각부터 구조 smoke 종료까지 **app DB에 정상 write가 들어올 수 없는 상태**를
만들고 유지한다. 이것이 없으면 step 5의 dump는 복구점이 아니다(task step 4 명시).

> **용어 정정.** "prod ingress를 maintenance 상태로 두고"는 n150에서 **구현 표면이 없다** —
> :80/:443 리스너 0개, `nginx`/`caddy`/`haproxy`/`traefik`/`cloudflared` 전부 inactive이며
> `/etc/{nginx,caddy,haproxy,cloudflared}` 부재, 컨테이너가 12701/12702/12705를
> `0.0.0.0`에 직결 바인딩(`network_mode: host`), 앱 코드에 maintenance/read-only 스위치
> 0 hit. 프록시는 **호스트 밖**(HAProxy, `map.digitie.mywire.org`)이다. → 클라이언트가 받는
> 것은 maintenance 페이지가 아니라 **502/503·tcp reset**이다. 이 문서에 "maintenance"라고
> 쓰지 않고 **계획된 outage 창**으로 기록한다.

### 8.1 fence 5층 — 무엇이 어느 구간을 덮는가

| 층 | 수단 | 유지 구간 | 막는 것 |
|---|---|---|---|
| **L1** off-box | HAProxy maintenance backend ⛔ | 4-2 → 11-6 | 공개 URL. **통제권이 우리에게 없다** |
| **L2** on-box port | `H35FENCE` iptables/ip6tables `INPUT 1` `[S]` | 4-3 → 11-6 | 비-loopback의 12701/12702/12705/12801/12805. **step 6/9에서 컨테이너가 되살아나도 유지된다 — 이 층이 없으면 fence는 step 6에서 구멍이 난다** |
| **L3** 컨테이너 | map 4개 compose stop + `ktdctl action pinvi-dagster stop` | 4-4/4-6 → step 6/9/11의 각 recreate | 자기 자신이 만드는 write |
| **L4** instigator | schedule 34 + sensor 10 = **44건 pause** | 4-5 → 11-5 | schedule/sensor 발화 |
| **L5** 인증·접속 | `ALTER DATABASE … CONNECTION LIMIT 0` | 5-0 → 6-0 | **dump 창의 신규 비-superuser 접속 전부** |

> **L2·L5가 1차 수단인 이유 — fence에 인증 층이 없다.** `pg_hba.conf`가
> `local all all trust` + `host all all 127.0.0.1/32 trust`이므로(P4 실측) **host의 어떤
> 프로세스도, 어떤 host-network 컨테이너도 무자격으로 `krtour_map`(및 superuser `addr`)에
> 접속해 write할 수 있다.** L3/L4만 두면 게이트가 전부 사후 관측
> (`pg_stat_activity`, `ss -tnp`→cgroup→container, tuple delta)에 그친다 — "이미 붙은
> writer를 본다"이지 "새 writer가 붙는 것을 막는다"가 아니다. `h35_fence_probe.py`의
> fail-close도 **탐지이지 차단이 아니다.** L2가 포트를, L5가 접속을 실제로 막는다.
> 그리고 sanctioned smoke URL이 전부 loopback이므로(`PINVI_KOR_TRAVEL_MAP_ADMIN_BASE_URL=`
> `http://127.0.0.1:12701`, `load_c6c_deployment_config_from_environment:791-836`의
> 12801/12705/12805) **L2와 smoke는 양립한다.**

### 8.2 명령 — 순서가 강제된다

```bash
# 4-1 [R] enablement 기록 — canReset 기반. GraphQL status만 보면 step 11이 7개를 영구 변질시킨다
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py record \
  --out /home/digitie/h35/run/enablement-baseline.json'

# 4-2 [W] ⛔ off-box HAProxy maintenance (n150 밖, 별도 소유자)

# 4-3 [W][S] on-box H35FENCE — off-box를 신뢰하지 않는 두 번째 벽. **4-6보다 먼저**
wsl ssh n150 'sudo -n iptables -N H35FENCE 2>/dev/null; \
  sudo -n iptables -F H35FENCE; \
  sudo -n iptables -A H35FENCE -i lo -j RETURN; \
  sudo -n iptables -A H35FENCE -s 127.0.0.0/8 -j RETURN; \
  sudo -n iptables -A H35FENCE -p tcp -m multiport \
    --dports 12701,12702,12705,12801,12805 -j REJECT --reject-with tcp-reset; \
  sudo -n iptables -A H35FENCE -j RETURN; \
  sudo -n iptables -C INPUT -j H35FENCE 2>/dev/null || sudo -n iptables -I INPUT 1 -j H35FENCE'
wsl ssh n150 'sudo -n ip6tables -N H35FENCE 2>/dev/null; \
  sudo -n ip6tables -F H35FENCE; \
  sudo -n ip6tables -A H35FENCE -i lo -j RETURN; \
  sudo -n ip6tables -A H35FENCE -s ::1/128 -j RETURN; \
  sudo -n ip6tables -A H35FENCE -p tcp -m multiport \
    --dports 12701,12702,12705,12801,12805 -j REJECT --reject-with tcp-reset; \
  sudo -n ip6tables -A H35FENCE -j RETURN; \
  sudo -n ip6tables -C INPUT -j H35FENCE 2>/dev/null || sudo -n ip6tables -I INPUT 1 -j H35FENCE'

# 4-3b [R] 모든 주소를 열거해 각각 실패를 확인한다 (192.168.1.14만 검증하면 안 된다)
wsl ssh n150 'ip -o addr'
# 워크스테이션에서 각 주소에 대해 — 반드시 실패해야 한다
#   curl -sS -m 5 http://<addr>:12701/health ; echo "exit=$?"      # exit != 0 (tcp reset)
#   curl -sS -m 10 -o NUL -w "%{http_code}\n" https://map.digitie.mywire.org/health   # 502/503
# n150에서 — 반드시 성공해야 한다
wsl ssh n150 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:12701/health'   # 200

# 4-4 [W] PinVi Dagster 정지 — ktdctl CLI 그대로 (pinvi-dagster는 _C6C_RUNTIME_IDENTIFIERS 밖)
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/ktdctl action pinvi-dagster stop --json'
#   pinvi-web·pinvi-api는 켜 둔다 (pair identity 보존 + run_ui_auth_smoke의 pinvi-web login shell GET)

# 4-5 [W] 44건 pause — **sensor 10개 먼저, 그 다음 schedule 34개**. 10분 안에 끝내야 한다
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py pause \
  --snapshot /home/digitie/h35/run/enablement-baseline.json'              # DRY RUN
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py pause \
  --snapshot /home/digitie/h35/run/enablement-baseline.json --confirm'
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py verify \
  --snapshot /home/digitie/h35/run/enablement-baseline.json --target paused'

# 4-6 [W] map 4개 정지 — daemon → web → ui → api
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step4-stop --confirm'
#   compose_service.run(["stop", daemon, dagster, ui, api],
#       mutation_capability=_COMPATIBLE_PAIR_MUTATION_CAPABILITY, transaction=tx)
#   ← pinvi-api를 뺀 것만이 deploy:3826과 다르다

# 4-7 [R][S] fence 확정 게이트 (ss -tnp가 sudo 필요)
wsl ssh n150 'python3 /home/digitie/h35c/h35_fence_probe.py --pgpass <생략 가능>'
```

**강제되는 순서.** ① **4-5는 4-6보다 먼저** — dagster web을 내리면 GraphQL pause/restore
채널이 사라진다(`POST http://127.0.0.1:12702/graphql`이 유일하게 정합한 채널). ② **4-3은
4-6보다 먼저** — step 6에서 API가 다시 뜨므로 컨테이너 정지만으로는 유지가 안 된다.
③ sensor 먼저 — `feature_operation_reconciliation_sensor`는 run 0건이어도 **30초마다 스스로
깨어나 app DB에 write한다.** ④ `*/10 * * * *`
(`feature_notice_krex_traffic_notices_ten_minute_schedule`, `schedules.py:187`) 때문에
**30시간 안에 20분 이상 무발화 창이 0개**다 — "조용한 시간대 선택" 전략은 성립하지 않고
pause가 필수다.

**pause mutation은 selector가 아니라 id를 받는다** — 그래서 4-1이 `state_id`를 기록한다:

```graphql
mutation { stopSensor(id: "<jobOriginId>::<selectorId>") { __typename } }
mutation { stopRunningSchedule(id: "<jobOriginId>::<selectorId>") { __typename } }
```

**map API `/ops` 경로는 step 4에서 쓸 수 없다** — `dagster_schedule_service.py:162,176,196,210`
이 sanctioned 래퍼이지만 `:509`/`:832`에서 `ops.dagster_schedule_active_claims`에 advisory
lock을 잡고 `ops.dagster_schedule_audit_events`에 write한다 = "app 역할 write transaction
0건"과 직접 충돌한다. 게다가 **sensor mutation이 아예 없다**(저장소 전체 0 hit).

### 8.3 직후 검증과 반증

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| 4-1 record | `schedules 37 (stored RUNNING 34 / STOPPED 3)`, `sensors 10 (stored RUNNING 3 / DECLARED_IN_CODE 7 / STOPPED 0)`, `effective_running_total 44`, `in_flight_runs 0` | 개수가 다르면 코드↔prod 불일치 → 복원 계획이 틀어진다 |
| 4-3b 외부 도달 | 모든 non-loopback 주소에서 **exit != 0** | 200이 오면 fence가 경로에 없다. 주소를 하나라도 빼먹으면 그 경로가 구멍이다 |
| 4-3b loopback | 200 | 실패면 L2 규칙이 loopback을 잘못 막았다 → smoke·H36 게이트가 전부 불가 |
| 4-5 verify | `--target paused` 통과 | `effective_status == RUNNING`이 하나라도 남으면 `MISMATCH` + exit 1 |
| 4-7 probe | `verdict FENCE_CLEAN` (13개 게이트) | **fence 미적용 실측은 `FENCE_DIRTY, failed_checks ['map_owned_app_backends']`이고 12개는 이미 0이다** → 정지 후 0이 되어야 하는 것은 `map_owned_app_backends` 하나뿐이며 fence 전/후가 반증 가능하게 갈린다 |
| tuple delta | 60초 간격 2회, `krtour_map`·`krtour_map_dagster` 양쪽 `tup_inserted/updated/deleted` **delta 0** | 0이 아니면 구멍이다. **fence 없이는 실제로 움직인다**(실측: `provider_sync.source_records 1,112,976→1,112,981`, `feature.feature_weather_values 15,994,284→15,994,756`, dagster `xact_commit +8`) |

핵심 질의의 확정형:

```sql
-- (1) app 역할 write transaction 0건. usename만으로는 두 DB를 구분할 수 없다 → datname 필수
SELECT count(*) FROM pg_stat_activity
 WHERE datname='krtour_map' AND usename='krtour_map' AND backend_type='client backend'
   AND pid <> pg_backend_pid() AND backend_xid IS NOT NULL;        -- 0 (write를 이미 한 tx)
SELECT count(*) FROM pg_stat_activity
 WHERE datname='krtour_map' AND usename='krtour_map' AND backend_type='client backend'
   AND pid <> pg_backend_pid() AND xact_start IS NOT NULL;         -- 0 (보수적)

-- (2) pending/running run 0건 — Dagster DB(krtour_map_dagster)이며 app DB와 별개다
SELECT count(*) FROM runs
 WHERE status IN ('QUEUED','NOT_STARTED','MANAGED','STARTING','STARTED','CANCELING');   -- 0
SELECT count(*) FROM bulk_actions WHERE status IN ('REQUESTED','IN_PROGRESS','CANCELING'); -- 0
SELECT count(*) FROM concurrency_slots WHERE run_id IS NOT NULL AND deleted=false;         -- 0
SELECT count(*) FROM pending_steps;                                                       -- 0
SELECT count(*) FROM job_ticks WHERE status='STARTED';   -- ★ daemon 정지 **후에만** 검사

-- (3) app 큐 잔여 — 죽은 C6C fixture 1건은 명시 예외
SELECT count(*) FROM ops.import_jobs
 WHERE status IN ('queued','running','starting')
   AND job_id <> 'aed9818b-fcde-419d-849f-f4380d098dc9';           -- 0
SELECT count(*) FROM ops.dagster_schedule_active_claims;            -- 0
SELECT count(*) FROM pg_locks WHERE locktype='advisory';            -- 0
```

**map 소유 writer container/process 0건은 3중 조인이 필요하다** — `application_name`이 전부
빈 문자열이고 모든 컨테이너가 `network_mode: host`라 `client_addr`이 전부 `127.0.0.1`이므로
DB만 봐서는 소유자를 특정할 수 없다: `pg_stat_activity.client_port` →
`sudo ss -H -tnp state established '( dport = :5432 )'` → host PID →
`sudo cat /proc/<pid>/cgroup` → 64-hex → `docker inspect --format '{{.Name}}'`.
`ss`에 `users:`가 없는 소켓은 **fail-close**. 프로브 자신의 소켓은 `inet_client_port()`로
제외한다(이 처리 전 1건 오탐이 났다).

**정상 상태에서도 실패하므로 쓰지 않는 기준 4개.**

| 기준 | 왜 버렸나 |
|---|---|
| `job_ticks.status='STARTED'` 0건을 daemon 가동 중 검사 | daemon이 살아 있으면 sensor 평가 tick이 **상시 1건** 존재한다(실측 03:38:56) → 정지 후에만 검사 |
| `pg_current_wal_lsn()` delta 0 | 공유 cluster라 geo/concierge/pinvi가 계속 WAL을 만든다. fence가 완벽해도 실패 → DB 단위 tuple counter로 교체 |
| `pg_stat_activity.state='active'` 0건 | idle-in-transaction 쓰기를 놓친다(실패해도 통과) → `backend_xid IS NOT NULL` |
| `ops.import_jobs` running 0건 | `status='running'` 1건이 **257시간 stale**로 영구 존재한다(`aed9818b…`, `kind='c6c_cancel_probe'`, `dagster_run_id IS NULL`) → 그대로 쓰면 fence를 영원히 못 건다 |

**fence 확립 직후 `[R]` baseline 재측정 (step 5/7의 대조 기준).** 52개 테이블 `count(*)` +
`sum(hashtextextended(t::text,0))`, 구조 md5 3종, sequence 6개, extension 5개, owner/ACL.
GUC 5개 고정: `SET TimeZone='UTC'; SET DateStyle='ISO, MDY'; SET IntervalStyle='postgres';
SET extra_float_digits=3; SET bytea_output='hex';` 전 테이블 ≈ 70초(실측). 구조 md5는
`pg_depend deptype='e'`로 extension member 2개(`pg_stat_statements` view)를 제외해야 잡음이
없다. **2026-07-30에 fence 없이 측정한 값(§10 표)은 shape 참조용이고, gate 기준은 이
재측정값이다.**

**실패 시 분기.** 4-7이 `FENCE_DIRTY`면 **step 5로 가지 않는다.** 실패한 게이트가
`map_owned_app_backends`면 정지 누락 컨테이너를 찾고, `non_map/unmapped_app_backends`면
정체불명 writer가 붙은 것이므로 **fence를 유지한 채 조사한다.** fence를 풀고 나중에 다시
거는 것은 dump 창을 다시 여는 것이므로 재측정으로 다시 시작해야 한다.

---

## 9. step 5 — 백업·복원 gate (+ 5.5 리허설) `[W]`(scratch·파일) / prod는 `[R]`

**목적.** "SHA-256과 `pg_restore --list`만 확인하고 끝내지 않고" 격리 scratch에 **실제로
복원해** pre-migration head·핵심 schema/row count를 대조한다. 이 게이트를 통과한 dump만이
step 10의 복구 경로다.

**명령.**

```bash
# 5-0 [W] L5 인증 층 — dump 창 동안 신규 비-superuser 접속을 전부 거부한다 (superuser는 예외)
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d postgres -c \
  "ALTER DATABASE krtour_map CONNECTION LIMIT 0; ALTER DATABASE krtour_map_dagster CONNECTION LIMIT 0"'
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d postgres -X -A -F "|" -c \
  "select datname, datconnlimit from pg_database where datname like \x27krtour_map%\x27"'   # 0 / 0
# 음성 통제: 반드시 실패해야 한다
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U krtour_map -d krtour_map -Atc "select 1"; \
  echo "exit=$?"'                       # exit != 0 ("too many connections for database")

# 5-1 [R→W] custom dump ×2 — owner/ACL 보존. `--no-owner`/`--no-privileges` 금지
wsl ssh n150 'umask 077; mkdir -p /home/digitie/h35/run/bk0063; chmod 700 /home/digitie/h35/run/bk0063'
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d krtour_map -X -A -F "|" -c \
  "select datname,xact_commit,tup_inserted,tup_updated,tup_deleted from pg_stat_database \
     where datname in (\x27krtour_map\x27,\x27krtour_map_dagster\x27)" \
  > /home/digitie/h35/run/bk0063/statdb-pre.tsv'
wsl ssh n150 'docker exec kor-travel-geo-postgres pg_dump -U addr -d krtour_map \
  --format=custom --compress=6 --no-tablespaces --lock-wait-timeout=30s --verbose \
  > /home/digitie/h35/run/bk0063/krtour_map.dump 2> /home/digitie/h35/run/bk0063/krtour_map.err'
wsl ssh n150 'docker exec kor-travel-geo-postgres pg_dump -U addr -d krtour_map_dagster \
  --format=custom --compress=6 --no-tablespaces --lock-wait-timeout=30s --verbose \
  > /home/digitie/h35/run/bk0063/krtour_map_dagster.dump 2> /home/digitie/h35/run/bk0063/krtour_map_dagster.err'
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d krtour_map -X -A -F "|" -c \
  "select datname,xact_commit,tup_inserted,tup_updated,tup_deleted from pg_stat_database \
     where datname in (\x27krtour_map\x27,\x27krtour_map_dagster\x27)" \
  > /home/digitie/h35/run/bk0063/statdb-post.tsv'
wsl ssh n150 'for f in krtour_map krtour_map_dagster; do \
  docker run --rm --network none -u "$(id -u):$(id -g)" \
    -v /home/digitie/h35/run/bk0063:/bk:ro postgres:16 \
    pg_restore --list "/bk/$f.dump" > "/home/digitie/h35/run/bk0063/$f.toc"; done; \
  cd /home/digitie/h35/run/bk0063 && sha256sum *.dump *.toc *.tsv > SHA256SUMS && chmod 600 *'

# 5-2 [W] 격리 scratch pair — prod cluster에 DB를 만들지 않는다
wsl ssh n150 'docker network create --internal h35-scratch; docker volume create h35-scratch-pgdata'
wsl ssh n150 'docker run -d --name h35-scratch-pg --network h35-scratch \
  -v h35-scratch-pgdata:/var/lib/postgresql/data \
  -v /home/digitie/h35/run/secrets/initdb:/docker-entrypoint-initdb.d:ro \
  --env-file /home/digitie/h35/run/secrets/scratch.env \
  postgis/postgis:16-3.5 \
  -c shared_preload_libraries=pg_stat_statements \
  -c shared_buffers=1GB -c maintenance_work_mem=1GB -c max_wal_size=4GB'
#   scratch.env(mode 600): POSTGRES_USER=addr, POSTGRES_PASSWORD=<throwaway>,
#                          POSTGRES_INITDB_ARGS=--locale=en_US.utf8 --encoding=UTF8
#   initdb.d: CREATE ROLE krtour_map LOGIN PASSWORD '<throwaway2>';
#             CREATE DATABASE krtour_map         OWNER krtour_map TEMPLATE template0
#                    ENCODING 'UTF8' LC_COLLATE 'en_US.utf8' LC_CTYPE 'en_US.utf8';
#             CREATE DATABASE krtour_map_dagster OWNER krtour_map TEMPLATE template0 …;
wsl ssh n150 'docker run --rm --network h35-scratch -u "$(id -u):$(id -g)" \
  -v /home/digitie/h35/run/secrets:/pgconf:ro -v /home/digitie/h35/run/bk0063:/bk:ro \
  -e PGSERVICEFILE=/pgconf/pg_service.conf -e PGPASSFILE=/pgconf/pgpass -e HOME=/tmp \
  postgres:16 pg_restore "service=ktm-scratch-app" -j 4 --exit-on-error \
  --no-tablespaces --verbose /bk/krtour_map.dump'
#   dagster DB 동일(service=ktm-scratch-dagster) → 이후 vacuumdb --analyze-in-stages

# 5-3 [R] 동일성 대조
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F "|" \
  -f - < /home/digitie/h35/run/bin/h35-identity-52.sql > /home/digitie/h35/run/identity-prod-0063.txt'
wsl ssh n150 'docker run --rm --network h35-scratch … postgres:16 psql "service=ktm-scratch-app" \
  -X -q -A -F "|" -f /work/h35-identity-52.sql > /home/digitie/h35/run/identity-scratch-0063.txt'
wsl ssh n150 'diff -u /home/digitie/h35/run/identity-prod-0063.txt \
  /home/digitie/h35/run/identity-scratch-0063.txt; echo "diff_exit=$?"'

# 5.5 [W] **필수** candidate migration 리허설 — 기본 entrypoint/CMD 미기동
#   기동 **전에** env 음성 검사를 게이트로 돌린다
wsl ssh n150 'python3 /home/digitie/h35/run/bin/h35_env_negcheck.py \
  --env-file /home/digitie/h35/run/secrets/scratch-api.env'
wsl ssh n150 "docker run --rm --network h35-scratch \
  --env-file /home/digitie/h35/run/secrets/scratch-api.env \
  --entrypoint sh $CAND_API -c 'cd /app && time alembic upgrade head'"
```

**scratch 서버는 `postgis/postgis:16-3.5`(prod 서버와 동일 image id `8b33190b6486`)여야
한다.** dump TOC에 `EXTENSION postgis`·`postgis_topology`·`pg_trgm`·`pgcrypto`·
`pg_stat_statements` 5개와 `topology`/`x_extension` 스키마 데이터가 있다. `postgres:16`은
**client 전용**이다. `role addr`(superuser) + `krtour_map`을 미리 만들어야 TOC의
`SCHEMA - feature addr`·`ACL - SCHEMA feature addr`·`TABLE DATA topology topology addr` 복원이
성립한다 — 그래서 **owner/ACL 충실도까지 게이트에 포함된다.**

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| 5-0 음성 통제 | `psql -U krtour_map` **실패** + `datconnlimit = 0/0` | 성공 = L5가 걸리지 않았다 |
| `*.err` | 두 파일 **0 바이트**, dump 선두 5바이트 `PGDMP` | 비어 있지 않으면 dump가 깨끗하지 않다 |
| TOC | `TABLE DATA` **52건** + `EXTENSION` 5 + `SEQUENCE SET` 6, `Dumped from 16.9` | 개수 부족 = content-incomplete |
| 파일 권한 | `digitie:digitie` mode 600 | root:root/644면 `umask`·`-u`가 적용되지 않았다(기존 dump의 실제 결함) |
| `statdb` delta | `tup_inserted/updated/deleted` **전부 0**(`xact_commit`만 증가 — read-only 세션) | 0이 아님 = **fence에 구멍** → 복구점 자격 없음 |
| `--lock-wait-timeout=30s` | 타임아웃 없이 완료 | 타임아웃 = 예기치 않은 writer 뒤 대기 → **fail-fast**(무한 대기가 아니다) |
| 5-3 `diff_exit` | **0** | ≠0 = 복원 불충실 |
| scratch head | app `0063_pipeline_root_id` / dagster `29b539ebc72a` | 다르면 dump가 잘못됐다 |
| Dagster instance identity | `instance_info.run_storage_id = cb6ccdf7-3794-4199-826b-9c6de7327b2d` | Dagster DB 동일성의 최강 marker |
| 구조 md5 3종 | `index_defs c017d4cc66bc040af67d3b7f711a1bb6`(210) / `constraint_defs 2d7ca59420eb0573a5923588a2e3fd38`(291) / `column_defs a55e089dbf855e9c1df309454c5e9e83` | 불일치 = 스키마 유실 |
| owner/ACL | 테이블 owner `krtour_map` 55 / `addr` 2, 스키마 ACL `{addr=UC/addr, krtour_map=UC/addr}`(`public`은 `krtour_map=UC/pg_database_owner`) | 불일치 = `--no-owner` 계열 오염 |
| 5.5 리허설 | scratch head `0068_integrity_last_seen` + `h35-structural-gate.sql` post 열 전부 일치 + **소요 시간 기록** | 실패 = prod에서 같은 실패가 난다. **여기서 잡는 것이 step 6에서 잡는 것보다 무한히 싸다** |

**5.5를 필수로 두는 이유.** 이것이 없으면 **0064~0068이 22 GB 실데이터에 처음 도는 곳이
prod**다. step 6은 (a) 첫 실행, (b) 30회×2초 고정 재시도 예산, (c) 중간에 비가역
0065/0066, (d) 실패 시 `unless-stopped`로 무한 재시도를 한꺼번에 맞는다. 5.5는 디스크
추가 소요 0(step 8이 어차피 같은 scratch를 reset한다)에 **prod 실행을 두 번째로 만들고
step 6 예산의 실측 근거를 준다.** 5.5는 step 2의 금지를 어기지 않는다 — 금지 대상은
**candidate 기본 entrypoint/CMD**이고 여기서는 `--entrypoint sh -c '…'`로 대체하며,
fence 확정(4-7)과 verified dump(5-3) **이후**에 **scratch에만** 붙인다.

**쓰지 않는 기준.** sha256 + `pg_restore --list`만 — task 명시 거부.
`scripts/docker-backup.sh` — prod에 존재하지 않는 standalone `postgres` service를
하드코딩(`:85,:117`)하고 `--no-owner --no-privileges`(`:119-121`)로 스키마 USAGE/CREATE
그랜트를 벗긴다. **그 dump를 prod로 되복원하면 앱이 죽는다.**

**명시 한계.** `pg_dumpall --globals-only`는 범위 밖이다(같은 cluster 안에서의 rollback이라
role은 살아 있다는 전제). scratch의 `addr`/`krtour_map` role은 합성값이고 bundle의 identity
주장은 **DB 내부 객체 한정**이다. 이 전제를 artifact에 기록한다.

**실패 시 분기.** 5-3 `diff_exit != 0` → **step 6에 들어가지 않는다.** dump를 다시 뜬다
(fence 유지 중이므로 두 번째 dump도 같은 복구점이다). 5.5 실패 → 원인을 고칠 수 있으면
forward 수정 후 재시도, 고칠 수 없으면 **H35를 중단하고 fence를 §12 역순으로 해제한다**
(이 시점까지 prod는 무변경이므로 rollback이 필요 없다).

---

## 10. step 6 — API candidate recreate → 0064~0068 forward 적용 `[W]` ⛔

**목적.** fence 안에서 `docker/api-entrypoint.sh:215`의 `while ! alembic upgrade head`가
0064~0068을 forward 적용하게 한다. **여기가 첫 비가역 지점이다**(§5 H-4).

**명령.**

```bash
# 6-0 [W] L5 원복 — candidate API가 krtour_map으로 접속해야 한다
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d postgres -c \
  "ALTER DATABASE krtour_map CONNECTION LIMIT -1; ALTER DATABASE krtour_map_dagster CONNECTION LIMIT -1"'
# 6-0b [R] 우리 자신의 세션을 모두 닫는다 — 0064/0068이 CREATE INDEX CONCURRENTLY를 쓴다
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d krtour_map -X -A -F "|" -c \
  "select pid,usename,state,xact_start from pg_stat_activity \
     where datname=\x27krtour_map\x27 and pid<>pg_backend_pid()"'      # 0행이어야 한다

# 6-1 [W] ⛔ recreate — wait=False (120초 상한을 타지 않는다)
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step6 --confirm'
```

```python
env = hybrid_env({api: cand.map_image_id,                     # ← API만 candidate
                  ui:  m.active.map_ui_image_id,
                  dagster: m.active.map_dagster_image_id,
                  daemon:  m.active.map_dagster_daemon_image_id},
                 cand.map_source_revision, m.active.pinvi_image_id, m.active.pinvi_source_revision)
ok, res = up_stage(cfg, tx, "h35_map_api", [_MAP_API_SERVICE], env)
poll_health("kor-travel-map-api-latest", timeout=1800)        # RestartCount 증가는 즉시 실패
```

```bash
# 6-2 [R] 진행 폴링 — health가 아니라 alembic_version을 본다 (30초 간격)
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d krtour_map -Atc \
  "select version_num from public.alembic_version"; \
  docker inspect kor-travel-map-api-latest \
    --format "{{.State.Status}} {{.RestartCount}} {{.State.Health.Status}}"; \
  docker logs --tail 40 kor-travel-map-api-latest'
```

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| 컨테이너 `.Image` | `cand.map_image_id`와 문자 단위 동일 | rollback ID = recreate가 image override를 못 받았다 |
| 라벨 `org.opencontainers.image.revision` | `$T` | `c8ed6164…`/`development` |
| **`RestartCount`** | **0** | ≠0 = entrypoint가 `exit 1` 후 `unless-stopped`로 재시작해 **마이그레이션 무한 반복 중**이다 → 즉시 6-F1 |
| `alembic_version` | `0068_integrity_last_seen` | `0063`(전혀 안 돌았다) / `0064~0067`(중간) / 부분 상태 |
| health | `healthy` | `unhealthy` 지속 = alembic이 아직/영구 실패. **uvicorn은 head 도달 후에만 exec되므로 health와 head는 함께 움직인다** |
| `NOT indisvalid` 인덱스 | 0 | >0 = CONCURRENTLY 잔재 → [`invalid-index-recovery.md`](./invalid-index-recovery.md) |

**여기서 fence probe를 게이트로 쓰지 않는다.** `map_owned_app_backends`가 **0이 아니라 >0**
이어야 정상이다(candidate API가 DB에 붙어야 한다) — 그대로 쓰면 정상인데 실패한다.
step 6~7 구간의 fence 근거는 **L2 iptables + L4 pause + L3의 나머지 3 service 정지**다.

**실패 시 분기 (downgrade 금지 — task 명시).**

```bash
# 6-F1 [W] 상태 동결 — 무한 재시도 루프를 멈춘다
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py stop-api --confirm'
wsl ssh n150 'docker logs --tail 400 kor-travel-map-api-latest > /home/digitie/h35/run/step6-fail.log'
# 6-F2 [R] partial-state probe
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -A -F "|" \
  -f - < /home/digitie/h35/run/bin/partial-state.sql > /home/digitie/h35/run/gate-partial.txt'
# 6-F3 [W] **같은 image·같은 command로 재개**
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step6 --confirm'
```

`partial-state.sql`이 잡아야 하는 두 상태 (근거: `alembic/env.py`에 `transaction_per_migration`
이 없어 0064~0068이 원래 한 트랜잭션인데 `0064`의 `autocommit_block()`이 그 트랜잭션을
커밋한다):

| 시나리오 | 관측값 |
|---|---|
| 0064만 적용, 0065 실패 | `alembic_version='0063_pipeline_root_id'` **인데** `idx_price_values_feature_observed_identity` 존재 + `idx_price_values_feature_product_observed` 부재 |
| 0068 중간 실패 | `alembic_version='0067_integrity_dedupe_key'` **인데** `last_seen_at` 컬럼 존재, `ck_data_integrity_violations_last_seen_not_null` 또는 `fk_data_integrity_violations_feature_id_set_null` 잔존, `idx_violations_*_seen` 일부만 존재, `indisvalid=false` 인덱스 존재 |

0064·0068은 이 부분 상태를 감지해 forward 재실행하도록 작성됐다(0068: `ADD COLUMN IF NOT
EXISTS`, `DO $migration$ IF NOT EXISTS` 가드, `DROP INDEX CONCURRENTLY IF EXISTS` 선행).
**재시도 예산은 고정이다** — `KOR_TRAVEL_MAP_MIGRATION_RETRIES`/`…_RETRY_SLEEP_SECONDS`는
entrypoint에서 env로 tunable하지만 **배포 compose에 그 키가 0 hit**(실측)이라 prod에서
조정 불가하다. 즉 컨테이너 1회 기동당 예산은 30회×2초 = 60초이고, 그 안에 끝나지 않는
DDL은 재시작 경계를 넘는다 — `wait=False` 폴링이 필수인 이유다.

**forward 재개가 반복 실패하면** step 10(복구 분기)으로 간다. **Alembic downgrade는 하지
않는다** — 0065의 52행 `collection_key` 재작성·3,530행 `source_updated_at` UPDATE와 0066의
`external_component_id` backfill은 downgrade로 복구되지 않는다.

> **0065의 tombstone 의미론 경고.** `DELETE FROM feature.curation_items`는 이번 적용에서
> **0행**이다(`archived_at IS NOT NULL` 0건, `status='archived'` 0행 — 실측). 그러나
> 의미론은 위험하다: tombstone이 하나라도 있는 identity 그룹에서 survivor는 tombstone이고
> 같은 그룹의 **active membership까지 삭제되며 백업 테이블을 만들지 않는다.** step 7의
> `curation_items` 행 수 **불변(3530)** 게이트가 이 발화를 직접 탐지한다.

---

## 11. step 7 — fence 안 구조 실증 `[R]`

**목적.** 0068 도달과 **최종 shape**를 반증 가능하게 실증하고, H36 게이트가 실효임을
확인한다. fence는 이 절이 끝날 때까지 유지된다(task step 4의 하한).

**명령.**

```bash
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F "|" \
  -f - < /home/digitie/h35c/h35-structural-gate.sql > /home/digitie/h35/run/gate-post.txt'
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F "|" \
  -f - < /home/digitie/h35c/h35d_key.sql >> /home/digitie/h35/run/gate-post.txt'
wsl ssh n150 'diff -u /home/digitie/h35/run/gate-pre.txt /home/digitie/h35/run/gate-post.txt'
```

**구조 게이트 — pre(0063) → post(0068)** (pre는 전부 2026-07-30 실측):

| gate | pre | post 요구값 | 반증성 |
|---|---|---|---|
| G01 alembic head | `0063_pipeline_root_id` | `0068_integrity_last_seen` | 직접 |
| G02 `ops.data_integrity_violations.last_seen_at` | **ABSENT** | `is_nullable=NO`, `timestamptz`, `default now()`, NULL 행 0 | 직접 |
| G03 `uq_violations_open_dedupe_key` | **ABSENT** | 존재 + valid, pred `((status = ANY (…)) AND (payload ? 'dedupe_key'))` | 직접 |
| G04 `curation_items` unique 표면 | `curation_items_pkey`, `uq_curation_items_active_identity` | **`curation_items_pkey` + `uq_curation_items_component_identity` + `uq_curation_items_active_source_feature` + `uq_curation_items_legacy_projection_id` 4개.** `uq_curation_items_active_identity`(0063)와 `uq_curation_items_identity`(0065 중간산물) **둘 다 없어야 한다** | 직접 |
| G05 `curation_items` 신규 컬럼 | NONE | `external_component_id:NO`, `legacy_projection_id:YES`, `operator_updated_at:YES`, `operator_updated_by:YES`, `source_present:NO`, `source_updated_at:NO` | 직접 |
| G06/G07 price index | `idx_price_values_feature_product_observed` valid | `idx_price_values_feature_observed_identity`만, indexdef `(feature_id, observed_at DESC, provider, price_domain, product_key)` | 직접 |
| G08 invalid index | NONE | NONE | **부분적용 탐지 전용** |
| G09 unvalidated constraint | NONE | NONE | 동일 |
| G10 잔재 인덱스 | `ops.uq_enrichment_review_candidate` **존재**(무관) | `%_ccnew%`/`%_ccold%` 0건 + 0068이 명시 `DROP … IF EXISTS`하는 이름 0건. **`ops.uq_enrichment_review_candidate`는 명시 예외** | 동일 |
| G11 violations constraint | `fk_…_feature_id_features` `confdeltype='c'` | 같은 이름 `confdeltype='n'`(SET NULL) + validated. `fk_…_feature_id_set_null`·`ck_…_last_seen_not_null` **부재**(RENAME/DROP됨) | 직접 |
| G12 violations index | `…_detected` 3개 + 나머지 5 | `…_seen` 3개 + 나머지 5, `…_detected` 3개 **부재**, 전부 valid | 직접 |
| G13 `curation_items` trigger/check | NONE | `ck_curation_items_external_component_id_canonical`(validated) + `trg_curation_items_legacy_component_identity` + `fk_curation_items_legacy_projection_id_curated_features`(deferrable, deferred) | 직접 |
| G14 row counts | `collections=71 items=3530 curated=3044 violations=3` | **전부 불변** | 직접(0065 DELETE 0행 주장의 반증 지점) |
| G16 concierge identity | `entities=1020 linked_features=1020 max_last_seen=2026-07-14 12:32:51Z` | **불변** | 직접(H35는 materialize 안 함) |
| K01 0065 UUID key shape | **0** | **52** (`^legacy:[0-9a-f-]{36}:[0-9a-f-]{36}:[0-9a-f]{32}$`) | 직접 |
| K03 key part census | `2parts=3 3parts=68` | `2parts=3 3parts=16 4parts=52` | 직접 |
| G17/G18 소형 md5 | `curation_items 6c399ae4…` / `collections 7fa901ee…` | **변경**(0065/0066 UPDATE) | 직접 |
| G19 violations md5 | `14d23812…` | **불변**(0068 UPDATE는 `LIKE 'address_validation:%'` 0행) | 직접 |
| G20 open import_jobs | `aed9818b…:running:c6c_cancel_probe` | 동일 1건 | fence 예외 |
| 유령 override | `ops.dagster_schedule_overrides`에 `feature_notice_krex_traffic_notices_monthly_schedule`(cron `7 * * * *`) 1건, 실제 schedule 이름과 불일치 = 무효 | **매칭 0건 유지** | main으로 올릴 때 이름이 바뀌면 조용히 활성화된다 |

**H36 게이트 실효 확인 — preview** (`[R]`, `dry_run=true`는 write 0건):

```bash
wsl ssh n150 'python3 /home/digitie/h35/run/bin/h35_mk_preview_conf.py \
  --container kor-travel-map-api-latest \
  --csv /home/digitie/.cache/c7-final.pihf0x9o/map/resources/curations/korean-tourism-100-2025-2026.csv \
  --out /home/digitie/h35/run/secrets/curl-preview-2025.conf'
wsl ssh n150 'sha256sum -c /home/digitie/h35/run/h36-csv.sha256'     # step 3과 같은 입력임을 고정
wsl ssh n150 'curl -sS --config /home/digitie/h35/run/secrets/curl-preview-2025.conf \
  -o /home/digitie/h35/run/h36-preview-post-2025.json -w "%{http_code}\n"'
# 2023-2024 CSV 도 동일하게 1회
```

대상 3행: `kt100-2023-2024-025`, `kt100-2025-2026-024`(남이섬 ×2),
`kt100-2025-2026-036`(청남대). CSV에서 세 행의 `feature_id`·`address_hint`가 **둘 다 빈 칸**
임을 확인했다(`korean-tourism-100-2023-2024.csv:27`, `-2025-2026.csv:26,39`) — 따라서
`_adopted_match`(`curations.py:511-528`)의 가드가 **반드시** 발화한다.

| 판별자 | 통과값 | 구 이미지(`c8ed6164`)라면 | 강도 |
|---|---|---|---|
| HTTP status | 200 | — | — |
| 3행의 `status` | **`review_required`** (`curations.py:686`) | **구 `ImportRowStatus` Literal에 없는 값이다** | **강. 이미지 전용** |
| 3행의 `issues[].code` | **`name_only_match`** (`curations.py:574`) | 이 문자열이 이미지에 **0 hit**(git 실측) | **강. 후보 수와 무관한 이미지 전용** |
| 호출 자체의 200 | 200 | 0063 스키마 + candidate 코드 조합에서는 `preview_curation_import`가 0066 신규 컬럼 `external_component_id`를 참조해 실패한다(`curation_repo.py:2604`) | **강. 코드↔스키마 일관성의 양성 증명** |
| 3행의 `resolved_feature_id` | `null` | step 3-5 pre가 `valid`+채워짐이었던 행에서만 판별력이 있다 | 조건부 |
| 3행의 `candidates` | 비어 있지 않음 | 리졸버가 죽으면 빈 배열 | 중(리졸버 생존) |

> **`unmatched`/`ambiguous`를 통과 기준에 쓰지 않는다.** 두 값은 **구 이미지도 낸다**
> (`c8ed6164`는 `row_status = "unmatched" if not matches else "ambiguous"`, 가드 없음) —
> "실패해도 통과하는 기준"의 정확한 예다. 판별자는 `review_required`와 `name_only_match`
> 둘뿐이다.

**정상 배포에서도 실패하므로 쓰지 않는 기준 5개.**

| 기준 | 왜 버렸나 |
|---|---|
| `uq_curation_items_identity` 존재 | 0065(`:1330-1336`)가 만들고 **0066(`:21,135-136` `_OLD_IDENTITY`)이 다시 지운다.** task 본문만 읽고 박으면 정상 배포가 실패 판정된다 |
| `curation_items` 행 수 **감소** | 0065의 DELETE가 **0행**이다 → **불변(3530)** 이 옳다 |
| `collection_key LIKE 'legacy:%'` 개수 52 | **pre도 이미 52다**(실측) → K01 정규식(0→52)·K03 census로 교체 |
| "이름에 `candidate`가 든 인덱스 0건" | `ops.uq_enrichment_review_candidate`가 **pre에 이미 존재한다** → 명시 예외 |
| `resolved_feature_id is null` 단독 / 라벨 단독 / `docker ps healthy` 단독 | 후보 2개 이상이면 구 이미지도 통과 / 라벨은 빌드 컨텍스트를 증명하지 않는다 / UI의 `NEXT_PUBLIC` 키가 비어도 통과한다 |

**실패 시 분기.** 구조 게이트 실패 → 부분 적용이면 6-F3으로 forward 재개, 최종 shape가
다르면(예: `uq_curation_items_identity` 잔존 = 0066 미완) 그 migration만 forward 재실행한다.
H36 게이트 실패(`name_only_match`·`review_required` 부재) → **이미지가 H36을 담고 있지
않다.** step 3-1이 통과했는데 여기서 실패하면 실행 중 image ID가 candidate가 아니므로
step 6 검증표부터 다시 본다. 게이트가 반복 실패하고 forward 수정이 불가하면 step 10.

---

## 12. step 8 — post-migration 격리 bundle · daemon preflight `[W]`(scratch·파일)

**목적.** H30B에 넘길 **0068 상태의 signed bundle**과 concierge export artifact를 만들고,
candidate Dagster daemon이 실제로 기동 가능함을 **격리된 곳에서** 증명한다.

**명령.**

```bash
# 8-1 [W] candidate API 재정지 → writer 0건 재확인
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py stop-api --confirm'
wsl ssh n150 'python3 /home/digitie/h35c/h35_fence_probe.py'          # FENCE_CLEAN

# 8-2 [W] 0068 immutable dump bundle (§9 5-1과 같은 형태, 새 디렉터리)
wsl ssh n150 'umask 077; mkdir -p /home/digitie/h35/run/bk0068; chmod 700 /home/digitie/h35/run/bk0068'
wsl ssh n150 'docker exec kor-travel-geo-postgres pg_dump -U addr -d krtour_map \
  --format=custom --compress=6 --no-tablespaces --lock-wait-timeout=30s \
  > /home/digitie/h35/run/bk0068/krtour_map.dump 2> /home/digitie/h35/run/bk0068/krtour_map.err'
#   dagster DB 동일 → pg_restore --list → SHA256SUMS → chmod 600

# 8-3 [R] concierge changes 전량 수집 — cursor 없이 시작해 끝까지 한 번
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35_changes_collect.py \
  --base-url http://127.0.0.1:12601 --limit 500 \
  --out /home/digitie/h35/run/concierge-changes.json'

# 8-4 [W] scratch reset → 0068 dump 복원 → identity 대조 (별도 clone 만들지 않는다)
# 8-5 [W] candidate Dagster daemon을 scratch pair에만 붙여 실제 기동
wsl ssh n150 'python3 /home/digitie/h35/run/bin/h35_env_negcheck.py \
  --env-file /home/digitie/h35/run/secrets/scratch-daemon.env'         # 기동 **전** 게이트
wsl ssh n150 "docker run -d --name h35-scratch-daemon --network h35-scratch \
  --env-file /home/digitie/h35/run/secrets/scratch-daemon.env $CAND_DAEMON"
```

**concierge `changes` 계약** (정본 `kor-travel-concierge/docs/feature-export-api.md:59-70`,
소비자 강제 `packages/kor-travel-map-dagster/src/kortravelmap/dagster/provider_fetchers.py:148-166`):

```
GET {BASE}/api/v1/features/changes?limit=500                        # 1회차: cursor 미지정
GET {BASE}/api/v1/features/changes?limit=500&cursor=<next_cursor>   # 반복
Header: X-API-Key   (mode 600 파일에서. query ?key= 금지 — access log 노출)
Response: {"items":[…], "next_cursor":"<opaque>", "has_more":bool}
```

- `limit` clamp 1..500(`settings.py:470-473`) → 1,477건이면 **500+500+477 = 3 페이지**.
- endpoint는 **`changes`**(기본값). `snapshot`은 active upsert만 반환해 철회를 전파하지
  않으므로 쓰지 않는다.
- cursor 불변식: `has_more=false` → 종료 / `has_more=true`인데 `next_cursor`가 없거나 str이
  아니면 **오류** / `next_cursor == 직전 cursor`면 **오류**(단조 전진) / cursor는 opaque,
  해석·가공 금지.
- **`scripts/h28b_recovery_check.py:33-47`의 `or not batch` 종료 조건을 쓰지 않는다** —
  `has_more=true` + 빈 페이지를 조용히 종료로 처리한다.
- 페이지마다 envelope 보존: `{page_index, request_cursor(1페이지는 null), next_cursor,
  has_more, item_count, items[원문 그대로, operation 포함]}`. **header/credential 절대
  미포함.** `operation ∈ {upsert, reject, tombstone}`.
- canonical JSON(`sort_keys=True`, `ensure_ascii=False`, 고정 separators, 개행 1개) →
  sha256 → `bk0068/SHA256SUMS` + `candidate-pair.json`과 **하나의 manifest로 결속**.

**격리 증명 — 판별력 있는 음성통제** (기존 두 계획의 비-증명을 교체한다):

```bash
# (1) network 열거 — h35-scratch 단독
wsl ssh n150 'docker inspect h35-scratch-daemon --format "{{json .NetworkSettings.Networks}}"'

# (2) ★ 실제 위험 경로: docker gateway IP를 통한 호스트 0.0.0.0:5432 도달
GW=$(wsl ssh n150 'docker network inspect h35-scratch -f "{{(index .IPAM.Config 0).Gateway}}"')
wsl ssh n150 "docker run --rm --network h35-scratch --entrypoint sh $CAND_DAEMON -c \
  'python -c \"import socket;s=socket.socket();s.settimeout(3);
   print(\\\"gw\\\", s.connect_ex((\\\"$GW\\\",5432)))\"'"        # **0이 아니어야 한다**

# (3) 대조군 — 같은 컨테이너에서 scratch 서버에는 반드시 닿아야 한다
wsl ssh n150 "docker run --rm --network h35-scratch --entrypoint sh $CAND_DAEMON -c \
  'python -c \"import socket;s=socket.socket();s.settimeout(3);
   print(\\\"scratch\\\", s.connect_ex((\\\"h35-scratch-pg\\\",5432)))\"'"   # **0이어야 한다**

# (4) env 지문 음성 검사
wsl ssh n150 'docker inspect h35-scratch-daemon --format "{{range .Config.Env}}{{println .}}{{end}}" \
  | python3 /home/digitie/h35/run/bin/h35_env_negcheck.py --stdin'
#   어떤 값의 sha256[:8]도 67c3f5db(prod DB password 지문)와 같지 않고
#   어떤 값도 '127.0.0.1:5432'를 포함하지 않는다 → 위반 시 exit 1
```

> **왜 `127.0.0.1:5432` 프로브를 버렸는가.** bridge 컨테이너에서 `127.0.0.1`은 **자기
> loopback**이므로 5432에 아무것도 없어 **격리가 깨져 있어도 항상 실패한다** — 도달 가능한
> 경로를 검사하지 않는 비-증명이다. 실제 위험 경로는 **docker gateway IP**이고, prod DB는
> `kor-travel-geo-postgres`가 `network_mode: host`로 `0.0.0.0:5432`에 바인딩하고 있다.
> (2)+(3)의 조합만이 "격리는 되어 있고 필요한 연결은 살아 있다"를 동시에 증명한다.
> `--internal` network는 외부 라우팅을 구조적으로 줄이지만 **host 자신에게 향하는 트래픽은
> FORWARD가 아니라 INPUT을 타므로 완전 보증이 아니다** — 그래서 (2)가 첫 실측이다.

**(2)가 `0`을 반환하면 = 도달 가능** → 다음을 얹고 **다시 (2)를 돌려 실패를 확인한 뒤에만**
진행한다(subnet 한정이므로 host-network인 map/geo/concierge/pinvi에는 영향이 없다):

```bash
SUB=$(wsl ssh n150 'docker network inspect h35-scratch -f "{{(index .IPAM.Config 0).Subnet}}"')
wsl ssh n150 "sudo -n iptables -I H35FENCE 1 -s $SUB -p tcp --dport 5432 -j REJECT --reject-with tcp-reset"
```

**필수 사실 — scratch pair는 app DB를 반드시 포함한다.** compose가 dagster·dagster-daemon
양쪽에 `KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED=true`를 박으므로
`schedule_overrides.py:53-86`이 code location 로드 시 **app DB의
`ops.dagster_schedule_overrides`를 읽고 실패하면 로드를 실패시킨다**(`if required: raise`).
Dagster DB만 있는 scratch로는 candidate daemon이 기동조차 못 한다.

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| bundle | `SHA256SUMS` 검증 통과, `TABLE DATA` 52건, `*.err` 0바이트, mode 600 | 개수 부족 = content-incomplete |
| pre-materialize Feature | **1,020** (`source_entities` provider=`kor-travel-concierge-youtube`/dataset=`youtube_place_candidates`/type=`extracted_place_candidate`), `count(DISTINCT source_links.feature_id)`=1,020, `max(last_seen_at)`=`2026-07-14 12:32:51Z` | 다르면 H35 중 materialize가 돌았다(금지) |
| concierge 수집 | `sum(item_count) == 1477`, 마지막 페이지 `has_more=false`, cursor chain 단조 전진·중복/역행 0, `operation` 분포 기록 | 1477 미달/초과, cursor 정체 → 오류 |
| payload 결속 | canonical JSON sha256이 bundle manifest와 하나로 묶임 | **producer에 durable snapshot/version identity가 없으므로 count만 기록한 live 재조회는 같은 입력으로 인정하지 않는다**(task 명시) — payload sha256이 유일한 identity다 |
| daemon preflight | `.Image == cand.map_dagster_daemon_image_id`, revision `$T`, scratch DB에 `daemon_heartbeats` 7종이 신선하게 기록 | 라벨 불일치 / heartbeat 없음 / code location 로드 실패 |
| 음성통제 (1)(2)(4) | 단독 network / `gw != 0` / 위반 0건 | (2)가 0 = **격리 실패** → 위 scoped reject 후 재검증. (4) 위반 = prod credential 누출 |
| 대조군 (3) | `scratch == 0` | ≠0 = 대조군이 죽었다 → (2)의 실패가 무의미해진다 |
| preflight 후 | daemon stop → **같은 pair를 signed 0068 bundle로 다시 reset·복원** → H30B 인수 identity 복구 | preflight가 scratch metadata(heartbeat/tick)를 바꿨으므로 이 reset이 필수다. 별도 clone은 만들지 않는다(22.3+22.3 > 53.7 GiB — 디스크상 필수 제약) |

> **task 문구 축소 (기록 필수).** "prod credential·**network** 없이"는 이 호스트에서 완전
> 달성 불가하다 — 같은 호스트의 docker gateway 때문이다. 달성 가능한 형태는 **"prod
> credential/DSN 미주입 + scratch DSN 한정 + 판별력 있는 음성통제(+필요 시 scoped
> reject)"** 까지다. 산출물에 이 문구로 좁혀 기록한다.
>
> **bundle의 주장 범위.** step 9 이후 `run_map_ops_smoke`의 cancel POST와
> request_id/system_log 기록으로 `bk0068`과 live prod는 갈라진다. bundle은 **point-in-time
> snapshot이며 live prod의 주장이 아니다** — 이 문구를 H30B 인수에 박는다.
> `pg_dumpall --globals-only`가 범위 밖이므로 identity 주장은 **DB 내부 객체 한정**이다.

**실패 시 분기.** bundle/수집 실패는 prod 무영향이므로 재시도한다. 격리 음성통제 실패는
**daemon 컨테이너를 즉시 정지**하고 원인을 없앤 뒤 재기동한다(그 사이 prod로 write가
갔는지 §11 G16·G14로 확인한다).

---

## 13. step 9 — prod 비-daemon candidate recreate·health `[W]`

**목적.** API·UI·Dagster web을 각 service에 고정한 immutable candidate image ID로 recreate
하고 identity·health를 candidate manifest와 대조한다. **prod Dagster daemon과 44건 pause는
계속 유지한다.**

**명령.**

```bash
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step9 --confirm'
```

```python
env = hybrid_env({api: cand.map_image_id, ui: cand.map_ui_image_id,
                  dagster: cand.map_dagster_image_id,
                  daemon: m.active.map_dagster_daemon_image_id},      # daemon은 아직 구 image
                 cand.map_source_revision, m.active.pinvi_image_id, m.active.pinvi_source_revision)
ok, res = up_stage(cfg, tx, "h35_non_daemon", [api, ui, dagster], env)
for c in (cfg.map_container, cfg.map_ui_container, "kor-travel-map-dagster-latest"):
    poll_health(c, timeout=900)
    compose_service._verify_running_image_source_provenance(
        c, label=c, expected_revision=cand.map_source_revision)
smoke_api = run_map_ops_smoke(cfg)                 # deploy가 쓰는 그 함수
smoke_ui  = run_map_ui_auth_preflight(cfg)         # login POST 포함
```

```bash
# smoke — 비밀은 curl --config로만
wsl ssh n150 'curl -sS -o /dev/null -w "api=%{http_code}\n"     http://127.0.0.1:12701/health'
wsl ssh n150 'curl -sS -o /dev/null -w "dagster=%{http_code}\n" http://127.0.0.1:12702/'
wsl ssh n150 'curl -sS http://127.0.0.1:12705/api/build-info'
wsl ssh n150 'curl -sS --config /home/digitie/h35/run/secrets/curl-login.conf \
  -o /dev/null -w "login=%{http_code}\n"'
```

**`_verify_map_runtime_source_provenance(rev, include_api=False)`를 쓰지 않는다** — daemon까지
검사하므로 **이 단계에서 반드시 실패한다**(정상 배포에서도 실패하는 기준의 전형). 컨테이너별
`_verify_running_image_source_provenance`를 쓴다.

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| 3개 컨테이너 `.Image` | candidate ID와 문자 단위 동일 | rollback ID 잔존 = **"UI만 이전 image로 남긴 상태"** → task가 금지한 다음 단계 진행 |
| 3개 라벨 revision | `$T` | `c8ed6164…`/`development` |
| `RestartCount` | 0 | ≠0 = 기동 실패 반복 |
| UI `/api/build-info` | 200 + `revision == $T` + `source_digest ==` 2-3 선계산값 | **503 `BUILD_REVISION_UNAVAILABLE`** = 빌드에 `KOR_TRAVEL_MAP_GIT_COMMIT` 누락(route.ts는 revision이 40-hex 아니거나 digest가 64-hex 아니면 503). `source_digest` 불일치 = 소스 트리 불일치 |
| login POST | 200 + `Set-Cookie` 세션 | 403 `AUTH_MISCONFIGURED`/401 = UI admin hash 훼손(`--env-file <.env>` 위반 또는 out-of-band 발산) |
| `run_map_ops_smoke` / `run_map_ui_auth_preflight` | 통과 | deploy가 쓰는 같은 함수이므로 실패는 계약 위반이다 |
| daemon | 여전히 `Exited` + `.Image == m.active.map_dagster_daemon_image_id` | running = fence 파손 |
| 44건 pause | `verify --target paused` 통과 | 하나라도 RUNNING = fence 파손 |
| UI 라벨 정규화 | `config_files=-`, `working_dir=$CACHE_MGR`로 **변경됨** | **정상 결과다.** 변경 사실 자체를 manifest에 기록한다(§5 step 1 UI 특이사항 — 복구 대상이 아니라 정정 대상) |

**UI에만 있는 추가 게이트가 필요한 이유.** `docker/frontend.Dockerfile:55-56`의
`NEXT_PUBLIC_VWORLD_API_KEY=` / `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY=` 기본값이 **빈
문자열**이라, 값이 비어도 healthcheck·login·`/api/build-info`가 **모두 200이고 지도 타일만
죽는다.** 그래서 step 2-2에 build-arg 완전성 게이트를 두었다(값은 sha8/len으로만 기록).

**쓰지 않는 기준.** old container를 `docker start` — task 금지이고 image ID pin recreate가
아니면 identity를 주장할 수 없다. `--wait` 없는 recreate 직후 즉시 smoke — 아직 기동 중이라
정상인데 실패한다(그래서 여기서는 `poll_health(timeout=900)`을 쓴다. step 6과 달리
마이그레이션이 없으므로 긴 폴링이 안전하다).

**실패 시 분기.** 세 service 중 하나라도 candidate identity·health를 만족하지 못하면
**step 11로 가지 않는다.** 원인이 이미지·환경이면 그 service만 다시 recreate한다. DB가
이미 0068이므로 **구 이미지로 그 service만 되돌리는 것은 해가 아니라 파손이다**(구 upsert가
`ON CONFLICT (…) WHERE archived_at IS NULL`을 명시하는데 0065가 그 partial 인덱스를
drop했다) — 되돌릴 필요가 있으면 step 10 전체를 탄다.

---

## 14. step 10 — cutover 전 실패 복구 분기 `[W]` ⛔

**목적.** forward 재개가 불가능할 때, fence를 유지한 채 **검증된 0063 dump + step 1의 exact
rollback image set**으로 되돌린다. **`ktdctl pinvi-pair rollback` 사용 금지.**

**왜 ktdctl rollback을 쓸 수 없는가.** step 6 이후 실행 pair가 `manifest.active`(c8ed6164)와
다르다. `_inspect_current_pair`(`compose_service.py:4572-4579`)가 4개 map 이미지의 OCI
revision 동일을 요구하므로 daemon(구) ≠ API(candidate)에서 `"kor-travel-map-dagster-daemon
running image revision differs from Map API"`로 raise하고, 그 뒤
`_pair_matches(current, manifest.active)`(`:4450-4453`)도 실패한다. `_production_preflight`
(`:3180-3184`)도 같은 이유로 `deploy`를 거부한다. 또 rollback은 5개를 **한 번에** 올려
task가 요구한 "비-daemon 먼저 green → 그 다음 daemon" 단계화를 표현할 수 없다.

**설계: in-place 파괴 복원이 아니라 rename swap.** `archive_mode=off`(PITR 없음)이므로
in-place 복원이 중간에 실패하면 남는 것이 없다. rename swap은 (a) 준-원자적이고 (b) **파손된
0068 DB를 증거로 보존하며** (c) 복원 검증을 swap 전에 끝낼 수 있다.

**명령.**

```bash
# 10-1 [W] fence 유지한 채 candidate 전부 내린다
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step10-stop --confirm'
#   compose_service.run(["stop", dagster, ui, api], mutation_capability=…, transaction=tx)

# 10-2 [W] ⛔ 디스크 확보 — step 8의 scratch를 먼저 버린다 (22.3 GiB 회수)
#   ★ 이 순간 H30B 인수물의 절반(clean scratch identity)이 비가역으로 사라진다 (§16)
wsl ssh n150 'docker rm -f h35-scratch-daemon h35-scratch-pg; docker volume rm h35-scratch-pgdata'
wsl ssh n150 'df -B1 --output=avail /'                      # ≥ 24 GiB

# 10-3 [W] rollback DB를 새 이름으로 복원 (superuser addr, 자격증명 없음 — P4)
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d postgres -c \
  "CREATE DATABASE krtour_map_h35rb OWNER krtour_map TEMPLATE template0 \
     ENCODING \x27UTF8\x27 LC_COLLATE \x27en_US.utf8\x27 LC_CTYPE \x27en_US.utf8\x27"'
wsl ssh n150 'docker run --rm --network host -u "$(id -u):$(id -g)" \
  -v /home/digitie/h35/run/bk0063:/bk:ro -e HOME=/tmp -e PGCLIENTENCODING=UTF8 postgres:16 \
  pg_restore -h 127.0.0.1 -p 5432 -U addr -d krtour_map_h35rb \
  -j 4 --exit-on-error --no-tablespaces --verbose /bk/krtour_map.dump'
#   krtour_map_dagster_h35rb 동일

# 10-4 [R] swap 전 복원 검증
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d krtour_map_h35rb -Atc \
  "select version_num from public.alembic_version"'          # 0063_pipeline_root_id
#   + 52 테이블 count/행해시 == step 5의 scratch 검증값 == 4-7 직후 baseline

# 10-5 [W] ⛔ swap — **연결 0건이 요구된다**(fence가 보장한다)
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d postgres -X -A -c \
  "select count(*) from pg_stat_activity where datname in \
     (\x27krtour_map\x27,\x27krtour_map_dagster\x27)"'        # 0이어야 한다
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d postgres -c \
  "ALTER DATABASE krtour_map RENAME TO krtour_map_h35broken; \
   ALTER DATABASE krtour_map_h35rb RENAME TO krtour_map"'
#   dagster DB 동일. postgres DB에 접속한 세션에서 실행한다.
#   krtour_map_h35broken / krtour_map_dagster_h35broken 은 **증거로 보존한다** (지우지 않는다)

# 10-6 [W] exact rollback image ID로 비-daemon 3개 recreate
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step10-restore-3 --confirm'
#   env = compose_service._pair_image_environment(m.active)   ← 값이 곧 step 1의 exact set
#   up_stage(…, [api, ui, dagster], env) → poll_health ×3
#   → _verify_running_image_source_provenance(expected_revision=m.active.map_source_revision)
#   → run_map_ops_smoke(cfg) and run_map_ui_auth_preflight(cfg) → assert db_head()=="0063_…"

# 10-7 [W] 위가 전부 green인 뒤에만 exact 이전 daemon
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step10-restore-daemon --confirm'

# 10-8 [R] pair 무결성 복구 확인 — 여기서 sanctioned 기계가 살아난다
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step10-assert'
#   assert _pair_matches(_inspect_current_pair(cfg), m.active)
#   reconcile_pair_references((m.active, m.rollback), cwd=get_project_root())   # candidate 태그 정리

# 10-9 [W] enablement 복원 → daemon health green 확인 → 그 다음에만 fence 해제 (§15 11-5/11-6)
```

**`pg_restore`의 두 함정 (둘 다 실행 불가로 이어진다).**

1. **`pg_restore -j`는 stdin/pipe 아카이브를 지원하지 않는다** — seekable 파일 또는 디렉터리
   아카이브가 필요하다. `docker exec -i … pg_restore … < dump`는 `-j`와 함께 쓸 수 없다.
   그래서 위는 dump를 **bind-mount한 파일 경로**로 넘긴다.
2. **객체가 가득한 live DB에 `--clean` 없이 복원하면 첫 객체에서 `already exists` →
   `--exit-on-error`로 즉사한다.** 그래서 in-place가 아니라 **새 DB + rename swap**이다.

**권한 함정.** `krtour_map`으로 복원하면 dump TOC의 `CREATE EXTENSION postgis`(non-trusted,
superuser 필요)와 `ALTER SCHEMA feature OWNER TO addr`에서 중단된다 —
`krtour_map`은 `rolsuper=false`·`rolcreatedb=false`이고 6개 스키마·extension 5개 owner가
전부 `addr`다. **`-U addr`가 필수이며, P4에 따라 자격증명 장벽 없이 도달 가능하다.**

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| 10-4 head + identity | `0063_pipeline_root_id` + 52 테이블 count/행해시가 step 5 검증값과 전량 일치 | 불일치 → **swap하지 않는다.** 복원이 불충실하면 swap은 파손을 확정할 뿐이다 |
| 10-5 연결 수 | **0** | >0 → `ALTER DATABASE … RENAME`이 거부된다. fence가 새고 있다는 뜻이므로 원인을 먼저 없앤다 |
| 10-6/10-7 identity | 4개 컨테이너 `.Image`가 `h35-pair`의 rollback ID, revision `c8ed6164…` | candidate ID 잔존 = **candidate entrypoint가 복원 DB를 다시 0068로 올려버린다** |
| 10-6 head | `0063_pipeline_root_id` | 0068 = candidate 이미지를 썼다 |
| 10-8 `_pair_matches` | **True** | False = 복원이 pair identity를 재현하지 못했다 |
| `_owned_references` | 정확히 **10개** | 15 = candidate 태그가 남았다 → `reconcile` 재실행 |
| gate 전 항목 | `gate-post` == **`gate-pre`와 완전 동일**(md5 G17/G18/G19 포함 — dump 복원이므로 byte-level 동일해야 한다) | 불일치 = 복원이 다른 시점의 것이다 |
| `ktdctl status pinvi --json` | `ktdctl-status-pre.json`과 일치 | 불일치 = pinvi 쪽이 움직였다 |

**이 분기의 종료 상태 = manifest 무편집 + retention 무잔여 + sanctioned 기계 완전 무손상.**
manifest는 이 분기에서 **한 글자도 쓰지 않는다** — 그래서 10-8 통과 시점에
`ktdctl pinvi-pair deploy`/`rollback` 왕복이 **자동으로 되살아난다**. `:latest-main` 5개는
candidate를 가리킨 채 남지만 `_require_pair_image_provenance`는 태그가 아니라 image ID를
보므로 무해하다.

**금지.** "새 candidate entrypoint를 복원 DB에 다시 실행"은 rollback이 아니다(task 명시).
`c7-deploy-asdigitie-c8ed6164-pv.sh`의 `rollback_all`(`:189-214`)은 `pinvi-api-latest`를
recreate 요구 없음(`N`)으로만 분류해 pinvi recreate를 검증하지 않으므로 이 시나리오에
쓸 수 없다.

**실패 시 분기.** 10-3 복원 실패 → prod `krtour_map`은 아직 0068 그대로이므로 **아직
아무것도 잃지 않았다.** 원인(권한·디스크·dump 손상)을 고쳐 재시도한다. 10-5 이후 실패 →
`krtour_map_h35broken`이 남아 있으므로 역방향 rename으로 되돌릴 수 있다(단 그 DB는
0068이므로 rollback 목적에는 쓸 수 없다 = **두 번째 복구점이 아니다**).

---

## 15. step 11 — forward-only cutover · manifest 재정합 · handoff `[W]` ⛔

**목적.** 구조·health·격리 daemon 게이트가 모두 green이면 forward-only를 확정하고, prod를
정상 상태로 되돌린 뒤 **manifest를 재정합해 sanctioned 배포 기계를 복구한다.**

**11-1 전제 게이트 `[R]` ⛔.** 세 green이 모두 손에 있어야 한다 — step 7 구조 green,
step 9의 세 service health green, step 8의 isolated daemon runnable gate green.
**이 시점부터 옛 dump 복원을 금지하고 실패는 forward 수정으로만 처리한다.**

```bash
# 11-2 [W] prod candidate daemon을 writer pause 상태로 시작 — **반드시 candidate 이미지로**
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/python \
  /home/digitie/h35/run/bin/h35ctl.py step11 --confirm'
```

```python
with c6c_deployment_lock(get_c6c_deployment_lock_path()):
    tx, cfg = open_tx(); m = load_pair_manifest(tx.manifest_path); cand = load_candidate()
    shutil.copy2(tx.manifest_path, f"{ART}/compatible-pair-v4.json.bak")   # 바이트 사본 보관

    final = new_image_pair(                        # ← raw CompatibleImagePair(...) 금지
        cand.map_image_id, m.active.pinvi_image_id, cfg.contract_generation,
        map_ui_image_id=cand.map_ui_image_id,
        map_dagster_image_id=cand.map_dagster_image_id,
        map_dagster_daemon_image_id=cand.map_dagster_daemon_image_id,
        map_source_revision=cand.map_source_revision,
        pinvi_source_revision=m.active.pinvi_source_revision)
    env = compose_service._pair_image_environment(final)
    ok, res = up_stage(cfg, tx, "h35_daemon", [_MAP_DAGSTER_DAEMON_SERVICE], env)
    poll_health("kor-travel-map-dagster-daemon-latest", timeout=600)   # healthcheck 없음 → running만
    compose_service._verify_map_runtime_source_provenance(cand.map_source_revision, include_api=False)

    # 11-3 deploy의 _verify_active_contract 중 **비파괴 부분만**
    compose_service._require_services_ready(
        ["kor-travel-map-api","kor-travel-map-ui","kor-travel-map-dagster",
         "kor-travel-map-dagster-daemon","pinvi-api"], transaction=tx)
    compose_service._validate_resolved_compose_contract(
        cfg, environment_override=env, expected_pair=final, transaction=tx)
    assert compose_service._pair_matches(compose_service._inspect_current_pair(cfg), final)
    smoke = {"map": run_map_ops_smoke(cfg), "ui": run_ui_auth_smoke(cfg)}
    validate_runtime_secret_isolation(
        compose_service._inspect_c6c_runtime_configs(cfg, SERVICES, transaction=tx), cfg)
    assert pinvi_container_identity() == baseline_pinvi_identity()   # 건너뛴 검증의 보상

    # 11-4 ⛔ manifest 커밋 — deploy:3080-3082과 동일 함수·동일 순서
    updated = manifest_with_active_pair(m, final)      # active←final, rollback←c8ed6164 pair
    assert updated.rollback == m.active
    compose_service._require_pair_image_provenance(updated.active)
    compose_service._require_pair_image_provenance(updated.rollback)
    write_pair_manifest(tx.manifest_path, updated)     # ★ 인자 순서는 (path, manifest)
    reconcile_pair_references((updated.rollback,), cwd=get_project_root())
```

> **manifest 재정합은 선택이 아니다.** 하지 않으면 `_production_preflight`
> (`compose_service.py:3180-3184`)가 이후 모든 `ktdctl pinvi-pair deploy`/`rollback`을
> **영구 fail-close**하고, `capture`는 v4 manifest 존재(`c6c_deployment.py:4299-4327`)와
> 비어 있지 않은 retention namespace로 이중 차단돼 **복구 경로가 수동 JSON 편집밖에
> 남지 않는다.**
>
> **시그니처 (배포 rev `c7328ed9`에서 직접 확인).**
> `write_pair_manifest(path: str, manifest: CompatiblePairManifest)`(`:4350`) — **path가
> 먼저다.** `c6c_state_paths(values: Mapping[str,str]) -> tuple[str,str]`(`:671`) — **문자열
> 인자도 `.compatible_pair_manifest` 속성 접근도 틀렸다.** 이 runbook은 그 함수를 우회하고
> `tx.manifest_path`(deploy가 쓰는 그 값)를 쓴다. 직접 부를 때는
> `manifest_path, lock_path = c6c_state_paths(tx.environment.effective)`다.
> `new_image_pair(map_image_id, pinvi_image_id, contract_generation, *, map_ui_image_id,
> map_dagster_image_id, map_dagster_daemon_image_id, map_source_revision,
> pinvi_source_revision)`(`:3938-3972`)가 `_validate_image_id`×5·`_validate_source_revision`×2
> ·contract-generation 정규식을 강제한다 — raw `CompatibleImagePair(…)`는 그 검증을 전부
> 우회하므로 쓰지 않는다. `ensure_pair_references`/`reconcile_pair_references(pairs, *, cwd)`
> (`c6c_image_retention.py:116`/`:173`) — **`cwd=`는 필수 keyword다.**
>
> **daemon도 반드시 candidate 이미지여야 한다.** `_inspect_current_pair`(`:4572-4579`)가
> 4개 map 이미지의 OCI revision 동일을 요구하므로, daemon만 `c8ed6164`로 남기면 이후 어떤
> manifest 정합도 성립하지 않는다.
>
> **건너뛴 sanctioned 검증 1개와 그 차이 (동등성을 주장하지 않는다).**
> `run_pinvi_canonical_smoke`는 "한 compatible-pair transaction의 **파괴적** cancel probe
> 1회"(`c6c_deployment.py:497-499`)이고 그 대상이 `.env:94`
> `KTDM_C6C_CANCEL_PROBE_JOB_ID=aed9818b-fcde-419d-849f-f4380d098dc9` = prod
> `ops.import_jobs`의 그 fixture 행이다. H35는 PinVi 컨테이너·이미지를 바꾸지 않으므로
> 보상 검증은 "step 1 baseline 대비 `pinvi-api-latest`의 `.Image`·
> `org.opencontainers.image.revision` 무변화"다. **즉 "deploy가 인정하는 pair"와 "우리가
> manifest에 적는 pair"의 검증 집합은 정확히 같지 않다.** 이 차이를 산출물에 명시한다.
> `run_ui_auth_smoke`의 pinvi-web login shell GET은 비파괴이므로 건너뛰지 않는다.

```bash
# 11-5 [W] enablement 복원 — **대칭이 아니다**
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py restore \
  --snapshot /home/digitie/h35/run/enablement-baseline.json'            # DRY RUN
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py restore \
  --snapshot /home/digitie/h35/run/enablement-baseline.json --confirm'
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py verify \
  --snapshot /home/digitie/h35/run/enablement-baseline.json --target baseline'
```

| 기록된 **저장** 상태 | 개수 | 복원 mutation |
|---|---|---|
| SCHEDULE RUNNING | 34 | `startSchedule(scheduleSelector:)` |
| SCHEDULE STOPPED | 3 | **아무것도 하지 않는다** |
| SENSOR RUNNING | 3 | `startSensor(sensorSelector:)` |
| SENSOR **DECLARED_IN_CODE** | **7** | **`resetSensor(sensorSelector:)`** |

selector = `{repositoryName:"__repository__", repositoryLocationName:"kortravelmap.dagster.definitions",
scheduleName|sensorName:"…"}`.

> **`startSensor`를 7개에 쓰면 저장 상태가 RUNNING으로 영구 변질된다.** GraphQL
> `InstigationStatus` enum에는 `RUNNING`/`STOPPED` 두 값뿐이고 **세 번째 저장값
> `DECLARED_IN_CODE`가 없어** `sensorState.status`가 7개를 `RUNNING`으로 접어버린다.
> 동작은 같지만 코드 `default_status`와의 결속이 끊겨 이후 코드 변경이 반영되지 않는다.
> **판별자는 `canReset`이다**(실측 완전 일치: `canReset=false` ⇔ 저장값
> `DECLARED_IN_CODE` ⇔ `feature_operation_{queued,starting,started,canceling,success,failure,canceled}_sensor`
> 7개). 그래서 4-1의 기록이 `canReset` 기반이어야 하며, **그 기록이 없으면 원래 값을 잃어
> 복원 자체가 불가능해진다.** `dagster` CLI에는 **`reset` 서브커맨드가 없어** 복원 수단이
> 될 수 없고(`dagster schedule {list,start,stop,restart,wipe,…}` /
> `dagster sensor {list,start,stop,cursor,preview}`), map API `/ops` 경로는 §8.2의 이유로
> 쓸 수 없다 → **직접 GraphQL이 유일하게 정합한 채널**이다. **`dagster schedule wipe` 금지**
> (모든 schedule을 끄고 tick 히스토리를 삭제한다).
>
> cursor는 세 mutation 모두 보존된다(`stop_sensor`/`reset_sensor`가 `with_status`만 하고
> `instigator_data`를 유지) → `feature_operation_reconciliation_sensor`의 watermark가
> 살아남는다. catch-up 폭주도 없다 — `Scheduler.start_schedule`이
> `ScheduleInstigatorData(cron, get_current_timestamp())`로 `instigator_data`를 교체하고
> scheduler가 `start_timestamp_utc = max(start_timestamp, latest_tick.timestamp+1,
> last_iteration_timestamp)`를 쓴다(§17-5의 버전 갭 참조).

```bash
# 11-6 [W][S] fence 해제 — 역순. **daemon health green 전에는 해제하지 않는다**(task 명시)
wsl ssh n150 'cd $CACHE_MGR && HOME=/home/digitie ./.venv/bin/ktdctl action pinvi-dagster start --json'
wsl ssh n150 'sudo -n iptables -L H35FENCE -v -n > /home/digitie/h35/run/fence-counters.txt; \
  sudo -n iptables -D INPUT -j H35FENCE; sudo -n iptables -F H35FENCE; sudo -n iptables -X H35FENCE'
wsl ssh n150 'sudo -n ip6tables -D INPUT -j H35FENCE; sudo -n ip6tables -F H35FENCE; \
  sudo -n ip6tables -X H35FENCE'
# off-box HAProxy maintenance 해제 ⛔
```

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| daemon | `.Image == cand.map_dagster_daemon_image_id`, revision `$T`, `running` | 구 image = manifest 정합 불가 |
| `daemon_heartbeats` | 7종(ASSET·BACKFILL·FRESHNESS·MONITORING·QUEUED_RUN_COORDINATOR·SCHEDULER·SENSOR)이 5~40초 이내로 신선 | 없음/stale = daemon이 실제로 일하지 않는다 |
| `_pair_matches(current, final)` | True | False = manifest를 쓰면 안 된다 |
| `compatible-pair-v4.json` | `version=4`, `.active` = candidate map 4 + pinvi `817136819f08…`/`6a035695…`, `.rollback` = c8ed6164 pair, `contract_generation="c6c-ops-v1"`, mode 600, **9키 정확 일치** | `load_pair_manifest`(`:3973-4014`)가 키 집합을 엄격히 강제하므로 오작성은 다음 로드에서 즉시 거부된다 = 자기 검증 |
| `_owned_references` | **5개**(c8ed6164 pair만) | 배포 성공 후의 sanctioned 정상 상태와 같은 shape여야 한다 |
| ktdctl 왕복 복구 | read-only로 `load_pair_manifest → _require_pair_image_provenance → _inspect_current_pair → _pair_matches` → True (**실제 rollback은 실행하지 않는다**) | False = 다음 배포가 fail-close된다 |
| 11-5 verify | `--target baseline` 통과 — effective 44건 RUNNING **그리고 저장값**(RUNNING 34 / STOPPED 3 / RUNNING 3 / DECLARED_IN_CODE 7)까지 일치 + cron 대조 | 저장값 불일치 = §15의 변질이 일어났다 |
| fence 해제 | 워크스테이션에서 `http://<addr>:12701/health` → **200**, 공개 URL 200. `iptables -S INPUT \| grep -c H35FENCE` → 0 | 해제 실패 |
| **fence 사후 증거** | `fence-counters.txt`의 REJECT pkts **> 0** | 0이면 "fence가 실제로 경로에 있었다"를 증명하지 못한다(트래픽이 없었을 수도 있으므로 단독 결정 근거로 쓰지 말고 4-3b 결과와 병용) |

**H30B handoff.** H35에서 **concierge materialize를 실행하지 않는다**(task 명시). 넘기는
것은 `bk0068` signed bundle + `concierge-changes.json`(payload sha256 결속) + clean scratch
identity 세 개뿐이다. 실제 1,020→1,477 회복과 authenticated `/admin/issues` 검증은
export artifact를 network-free로 재생하고 격리 DB만 사용하는 **T-VN-H30B**가 수행한다.

**실패 시 분기.** 11-1 전제 게이트가 하나라도 red면 **step 10으로 간다**(아직
forward-only가 아니다). 11-4 manifest 쓰기가 실패하면 `write_pair_manifest`가 이전 바이트를
복원한다(tmp + `os.replace` + fsync, 0600). 그래도 상태가 의심되면
`compatible-pair-v4.json.bak`으로 되돌리고 **manifest 재정합만 별도 승인 아래 재시도한다** —
이 시점 prod는 이미 정상 서비스 중이므로 fence를 다시 걸지 않는다.

---

## 16. 비가역 지점과 사람 승인

**승인 없이 통과하지 않는다.** 각 항목의 "승인 전에 손에 있어야 하는 것"이 전부 갖춰진
뒤에만 진행한다.

| # | 지점 | 무엇이 비가역인가 | 승인 전에 손에 있어야 하는 것 |
|---|---|---|---|
| **H-1** | **step 0** 잔여 restore DB `DROP DATABASE` | superuser 권한으로 실행되고 `archive_mode=off`라 PITR이 없다. **자격증명 장벽이 없어 오작동 여지가 더 크다**(P4) | 소유자·용도 확인, 해당 DB가 어떤 task 산출물도 아님, `df` 실측, 회수 목록 |
| **H-2** | **step 0/3.5** root 소유 rehearsal dump 이동·권한 변경 `[sudo]` | 파일 위치·권한 | 그 dump가 rollback source로 **쓰이지 않음**을 명시 |
| **H-3** | **step 2** `:latest-main` 5개 이동 + 범위 밖 `pinvi-api` rebuild | 태그 이동 자체는 되돌릴 수 있으나, **step 1의 immutable 태그가 없는 상태에서 하면 `c8ed6164` pair가 dangling이 되어 `docker image prune` 한 번에 소멸한다** | build 전 `_owned_references == 10` assert 통과. pinvi 부작용(image ID 이동, build 실패가 map build를 abort)을 승인 항목으로 명시 |
| **H-4** | **step 4-2/4-3** off-box maintenance + on-box `H35FENCE` 투입 = **공개 outage 시작** | maintenance 페이지가 아니라 502/503·tcp reset이다. PinVi도 Map API 의존이 끊긴다 | outage 창 합의(P8). 문서·통보에 "maintenance"라 쓰지 않고 **planned outage**로 기록 |
| **H-5** | **step 6** candidate API 첫 기동 = **0064~0068 적용** | 0065의 `collection_key` **52행 재작성**·`source_updated_at` **3,530행 UPDATE(WHERE 없음)**·`operator_updated_*`/`legacy_projection_id` 3,044행, 0066의 `external_component_id` backfill은 **downgrade로 복구되지 않는다.** 0064/0068의 `autocommit_block()`이 **부분 적용 상태**를 만든다 | 5-3 identity `diff_exit=0`으로 검증된 0063 dump, step 1 rollback image set 태그 검증, **5.5 리허설 통과**, P3/P4의 복원 경로 실증, `RestartCount` 게이트 준비 |
| **H-6** | **step 10-5** `ALTER DATABASE … RENAME` swap | prod DB 실체 교체. **dump 시각 이후의 모든 write가 영구 소실**되고 `archive_mode=off`라 roll-forward 수단이 없다. 파손 0068 DB는 증거로 남지만 **두 번째 복구점이 아니다** | 10-4 복원 검증 green, 연결 **0건**, `df` ≥ 24 GiB, 파손 DB 보존 이름 확정(`krtour_map_h35broken`) |
| **H-7** | **step 10-2** 디스크 순서 결합 | 22.3 GiB 복원 공간을 만들려면 step 8의 scratch를 먼저 폐기해야 한다 → **rollback을 시작하는 순간 H30B 인수물의 절반(clean scratch identity)이 비가역으로 파괴된다.** 재구축은 signed bundle로만 가능하고 그 자체가 다시 22 GiB를 요구한다 | 이 결합을 승인자가 알고 있음. rollback이 공짜가 아니라는 점의 정확한 형태다 |
| **H-8** | **step 11-1** forward-only 확정 | 이 시점부터 **옛 dump 복원 금지**, 실패는 forward 수정만 | step 7 구조 green + step 9 세 service health green + step 8 isolated daemon gate green, step 8 bundle 서명 완료 |
| **H-9** | **step 11-4** `compatible-pair-v4.json` 커밋 | 잘못 쓰면 `_production_preflight`가 이후 모든 `deploy`/`rollback`을 **영구 fail-close**하고 `capture`는 이중 차단되어 **복구 경로가 수동 JSON 편집밖에 남지 않는다** | 11-2/11-3 전부 green, `_pair_matches(current, final)` True, `_require_pair_image_provenance` 양쪽 통과, `new_image_pair` 검증 통과, **현 manifest 바이트 사본 보관**, 건너뛴 `run_pinvi_canonical_smoke`와 보상 검증의 차이를 산출물에 기록 |
| **H-10** | `docker builder prune` (73.8 GB reclaimable) | 캐시 소실로 재빌드가 느려지는 것만이 대가 — 이미지에는 무영향 | step 2 build 성공 이후 · step 5 복원 이전. **`docker image prune`은 전 구간 절대 금지**(reclaimable 24.28 GB 안에 step 1의 rollback image set이 있다) |

**가역인 것 (승인 대상 아님).** step 1의 태그 5개(추가만) · step 2의 build(컨테이너 무변경)
· step 3의 offline 검사(env 0·network 0) · **`0064`**(인덱스만 바꾸고 DML 0건, `downgrade()`도
대칭이라 완전 가역) · `CONNECTION LIMIT 0`(`-1`로 원복) · `H35FENCE`(체인 제거).

**이 절차의 가장 약한 지점 (정직한 기록).** forward 경로는 반증 가능한 게이트로 촘촘히
덮여 있지만 **복구 경로는 prod에서 리허설되지 않는 단발성 연산에 의존한다.** 22.3 GiB
`pg_restore` + `ALTER DATABASE RENAME`은 **이미 상황이 나빠진 뒤에** 처음 실행되고, scratch
서버에서는 재현되지 않는다(다른 서버·다른 `shared_buffers`·다른 동거 워크로드). 구조적
해소책은 하나뿐이다 — **`archive_mode=on` + WAL 아카이브를 사전에 켜서 진짜 PITR을
확보하는 것**(§18-3, H35 밖 선행 작업).

---

## 17. 아직 확인되지 않은 것

억지로 채우지 않는다. 아래는 **자료에 없어서 미확인인 항목**이고, 각각 실행 중 첫 측정
지점을 함께 적는다.

1. **off-box HAProxy의 소유자·maintenance 절차·backend 구성·통보 경로** — n150 밖이라 전부
   미확인. L1은 이 runbook의 통제 밖이며 L2가 유일하게 우리가 보증하는 층이다.
2. **bridge 컨테이너에서 docker gateway IP를 통한 호스트 `0.0.0.0:5432` 도달 가능성** —
   실측되지 않았다. **§12의 음성통제 (2)가 첫 측정이다.** 도달하면 scoped reject를 얹고
   재검증해야 하며, 그전까지 "prod network 없이"를 충족했다고 기록하지 않는다.
3. **소요 시간·산출 크기 전부** — dump 소요, 22.3 GiB scratch 복원 소요, 0064~0068 실행
   시간, outage 창 길이. 유일한 실측 근거는 기존 dump 1.13~1.21 GiB / 약 3분이다.
   **outage 창은 §9 5.5 리허설 실측으로만 확정된다** — 그전에 창 길이를 약속하지 않는다.
4. **`ALTER DATABASE … RENAME`의 prod cluster 실동작·소요** — 미리허설. §16의 가장 약한
   지점 그 자체다.
5. **dagster catch-up 배제 결론의 버전 갭** — `Scheduler.start_schedule`이
   `start_timestamp=now`로 `instigator_data`를 교체한다는 결론은 CI 이미지의 dagster
   **1.13.13** 소스에서 읽었고 prod는 **1.13.15**다. mutation surface·`canReset`·enum은
   live 1.13.15 introspection으로 확인했으므로 **재검증 대상은 이 한 결론뿐이다.**
6. **`pg_hba.conf`의 trust 항목**은 2026-07-30 실측값이다. P4에서 **재확인 없이 복구 경로의
   전제로 쓰지 않는다.**
7. **`_owned_references`의 호출 시그니처** — `c6c_image_retention.py:151-170`에 존재하는
   것은 확인됐으나 driver에서 어떻게 열거할지는 미확인. `h35ctl.py` 작성 시 소스 재확인.
8. **`run_map_ops_smoke` / `run_map_ui_auth_preflight` / `run_ui_auth_smoke` /
   `validate_runtime_secret_isolation` / `_inspect_c6c_runtime_configs`의 인자 계약** —
   이름과 호출 위치는 확인됐으나 전체 시그니처는 미확인. driver 작성 시 소스 재확인.
9. **현행 UI의 `/api/build-info` 응답** — 503일 가능성이 배제되지 않았다. **step 1-4가 첫
   측정이며, 503이면 step 9/10의 UI identity 기준이 무의미해진다.** candidate 쪽
   `FRONTEND_SOURCE_DIGEST` 결속도 실행 실측이 없다.
10. **prod API 컨테이너의 `admin_trusted_proxy_cidrs` 실제 값** — 기본값은
    `["127.0.0.1/32","::1/128"]`(`settings.py:315-319`)이지만 env override 여부는 미확인.
    **step 3-6이 첫 측정이며, loopback이 빠져 있으면 H36 게이트를 API 직접 호출로 할 수
    없다.**
11. **step 2의 좁은 대안 seam** — `compose_service.run(["build", 4 map svc],
    environment={4×`*_IMAGE`, `KOR_TRAVEL_MAP_GIT_COMMIT`, **prov.compose_environment()},
    transaction=tx)`가 `:latest-main` 이동과 pinvi rebuild를 **실제로** 회피하는지 미검증.
    회피하더라도 `_require_expected_source_provenance`·`_inspect_c6c_candidate_pair`의
    attestation을 별도로 불러야 한다. 이 runbook은 sanctioned seam
    `_prepare_c6c_candidate_pair`를 쓰고 부작용을 H-3으로 승인 처리한다.
12. **잔여 restore DB의 소유자·용도** — 미확인. H-1 승인 전 확인 대상.
13. **`.env` 02:42 변경의 이력** — 변경 내용은 UI hash 1키 정렬로 확인됐고 그 값이 live와
    일치하지만, **누가 왜 했는지는 미확인**이다.
14. **§3.3의 "작성 대상" 7개 도구는 존재하지 않는다.** P9가 그 게이트다.
15. **`0.0.0.0:12702` Dagster GraphQL이 무인증이고 `hasStartPermission`/`hasStopPermission`이
    true다.** 우리가 pause 채널로 의존하는 것과 같은 이유로 네트워크상의 누구든 schedule을
    끄거나 run을 launch할 수 있다. H35 범위 밖이지만 **L2 fence가 이 표면도 함께 막는다**는
    점만 기록한다 — 해제 후에는 다시 열린다.

---

## 18. task 본문 정정 사항 (산출물에 함께 기록)

1. **"prod ingress를 maintenance 상태로 두고"** → n150에 maintenance surface가 없다.
   **off-box HAProxy maintenance + on-box `H35FENCE`** 로 대체하고 문구를
   **planned outage**로 고친다(§8).
2. **step 8 "prod credential·network 없이"** → 같은 호스트의 docker gateway 때문에 network
   격리는 완전 달성 불가. **"prod credential/DSN 미주입 + scratch DSN 한정 + 판별력 있는
   음성통제"** 로 좁힌다(§12).
3. **step 7의 "0068 최종 shape"에 `uq_curation_items_identity`가 있어서는 안 된다.**
   0065(`:1330-1336`)가 만들고 **0066(`:21,135-136`)이 다시 지운다.** task 본문만 읽고
   존재를 성공 기준으로 박으면 정상 배포가 실패 판정된다(§11 G04).
4. **`feature_place_kor_travel_concierge_youtube_monthly_schedule`은 prod에서 STOPPED다**
   (저장 상태 STOPPED, 2026-06-30 03:18:09 생성). task 본문의 "월 1회(`40 3 3 * *`)라
   **2026-08-03**에 회복"은 성립하지 않는다 — **배포해도 저절로 돌지 않는다.** step 11-5의
   복원은 이것을 STOPPED로 되돌려 놓으므로, 명시적 start 또는 수동 launch는 **H30B의
   결정 사항**으로 넘긴다. 다른 2개도 STOPPED: `managed_file_scan_six_hourly_schedule`,
   `mois_localdata_source_sync_weekly_schedule`.
5. **`com.docker.compose.project.working_dir` 라벨은 비어 있지 않다.** api/dagster/daemon/
   pinvi-api = `$CACHE_MGR`(`config_files=-`), **UI만**
   `/home/digitie/kor-travel-docker-manager`(out-of-band `docker create`). step 9의 recreate가
   이것을 정규화한다(§13).
6. **`docker/api-entrypoint.sh`의 정확한 줄은 `:215`** `while ! alembic upgrade head; do`
   (retries 30, sleep 2s. 둘 다 env로 tunable하지만 **배포 compose에 그 키가 0 hit이라
   prod에서 조정 불가**).
7. **`ops.dagster_schedule_overrides`에 유령 override 1건**
   (`feature_notice_krex_traffic_notices_monthly_schedule`, cron `7 * * * *`). 실제 schedule
   이름이 `..._ten_minute_schedule`이라 지금은 무효지만 **이름이 바뀌면 조용히 활성화될 수
   있다** → §11에 "override 매칭 0건 유지"를 넣었다.
8. **`collection_key` 계약 문서화**(blocker 아님) — 0045→0065에서 형식이 두 번 바뀐 불안정
   business key다. admin create·저장·검색과 CSV upsert에는 쓰지만 **외부의 장기 참조·path
   identity는 `collection_id`를 써야 한다.** `docs/integration-map.md`에 경계를 명시한다.
9. **`scripts/docker-backup.sh` 정정** — `:80,:85,:117`의 standalone `postgres` service
   하드코딩과 `:119-121`의 `--no-owner --no-privileges`는 prod에 대해 둘 다 틀렸다.
   "staging 복원 후 swap" 전제를 prod rollback에 가져오면 스키마 그랜트가 소실된다.
10. **머지 = 배포가 아니다.** H30A 완료 기록이 prod 상태를 주장하는 것으로 읽히지 않게
    관련 문서를 함께 고친다(task 명시).

---

## 19. 관련 문서

- `docs/tasks.md` — **T-VN-H35 11단계(요구 정본)**. 이 runbook은 그 이행 절차다.
- [`docker-app.md`](./docker-app.md) §8 — production cutover DDL 기록·원자 정리.
- [`c7-prod-live-e2e.md`](./c7-prod-live-e2e.md) — 같은 배포 경계의 파괴적 실행·attestation·
  `BLOCKED.json` 복구 규약. compatible-pair manifest v4의 9키 계약도 여기에 있다.
- [`invalid-index-recovery.md`](./invalid-index-recovery.md) — 0064/0068의 `CONCURRENTLY`
  잔재(INVALID index) 탐지·drop·재빌드.
- [`../backup-restore.md`](../backup-restore.md) — 독립 app cold backup/restore 경계
  (**prod external-infra 배포에는 적용되지 않는다** — §18-9).
- [`../integration-map.md`](../integration-map.md) — 포트·연동 방향·인증·계약 정본 위치.
- [`agent-failure-patterns.md`](./agent-failure-patterns.md) — "실패해도 통과하는 기준" /
  "정상인데 실패하는 기준"의 일반 패턴.
- `docs/adr/075-cutover-and-ddl-discipline.md` §6 — 수술형 DDL·lock 규율.
