# Runbook — T-VN-H35 prod 마이그레이션 cutover (0063 → 0068)

이 문서는 `docs/tasks.md`의 **T-VN-H35 11단계**를 n150 production에서 실행하는 유일한
운영 순서다. **요구 정본은 task 본문이고 이 runbook은 그 11단계를 명령·게이트·실패
분기로 옮긴 것이다.** 실제 host·URL·계정·비밀번호·token·hash는 gitignore된
`docs/deploy-runbook.local.md`·`docs/prod-access.local.md`에만 둔다.

**이 절차는 hybrid다.** 척추는 direct 안의 **검증 게이트·복구 설계**이고, 이식한 것은
ktdctl(`kor-travel-docker-manager` 라이브러리) 쪽의 **build seam과 fence 층**이다. 근거:

- `ktdctl` CLI는 분해할 수 없다 — `pinvi-pair deploy`는 `recreate=True`를 하드코딩하고
  (`backend/src/kor_travel_docker_manager/cli.py:117-134` — `services/` 하위가 아니다,
  `c7328ed9` `git ls-tree` 실측), `ensure --build`는
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

> **개정 2026-07-30 (실행 전 적대 감사 반영, 판정 NO_GO → 수정).** 3개 렌즈 감사와 검증자
> 2인이 실행 불가·자기모순 게이트를 확정했고 이 문서는 그 지적대로 고쳐졌다. 위 "중단하고
> 조사한다" 규칙이 실제로 발동한 항목이 하나 있다 — **디스크 여유가 53.7 → 84.2 GiB로
> 변했다.** 조사 결과 원인은 확정됐다: P2가 최대 회수 대상으로 지목했던
> `kor_travel_geo_restore`(31.5 GiB)가 그 사이 **누군가에 의해 회수됐다**(53.7 + 31.5 ≈
> 84.2로 산술이 정확히 맞고, `pg_database` 재열거에서 그 DB가 부재). 그래서 P1은 이미
> 통과이고 step 0은 **조건부**로 강등됐다(§4). 이 문단 자체가 그 조사 기록이다.
>
> 감사에서 **runbook이 옳다고 확인된 것은 고치지 않았다** — §3.4 형식 이탈 논증, §11 G10의
> 명시 예외, step 2의 "컨테이너 0개" 4겹 논증과 `docker ps -a` 스냅샷 게이트, step 1의
> retention 전제(`ensured 5`/`_owned_references 10`), §12 gateway 음성통제 설계,
> step 9에서 `_verify_map_runtime_source_provenance(include_api=False)`를 쓰지 않는 판단,
> §18-3(0066이 `uq_curation_items_identity`를 다시 지운다)이 그것이다.

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
| **P1** | **디스크 여유 ≥ 40 GiB** | `df -B1 --output=avail /` | step 5의 22.3 GiB scratch 복원 또는 step 10의 rollback DB가 disk full → **같은 파일시스템에 동거하는 geo·concierge·pinvi가 동시 장애**. **2026-07-30 실측 `90,358,456,320` = 84.2 GiB(`df -h` 466G/362G/85G avail/82%)로 이미 통과다.** 실행 시점에 재측정해 40 GiB 미만일 때만 §4 step 0(조건부)을 탄다 |
| **P2** | 잔여 restore DB **처리 방침 확정** — P1 미달일 때만 | `kor_travel_map_restore` 38 MB · `kor_travel_map_dagster_restore` 25 MB · `kor_travel_map_restore_manual` 7.5 MB · `ktc_t1*` ~28개 (**합계 ≈ 70 MB**) | 회수 여력이 사실상 없다 → `docker builder prune`(H-10)이 먼저다. `DROP DATABASE`는 **비가역**(§16 H-1) — 소유자·용도 확인이 승인 전제. ⛔ **`kor_travel_geo_restore`(31.5 GiB)는 이미 존재하지 않는다**(2026-07-30 `pg_database` 재열거). 지금 31 GB급으로 남은 것은 **형제 서비스 kor-travel-geo의 운영 DB `kor_travel_geo`(32 GB, owner `addr`) 하나뿐이고 이것은 회수 대상이 아니다** — 이름이 `_restore` 한 토큰만 다르므로 §4의 대상 열거를 **눈으로 읽고** 지목하지 않으면 운영 DB를 지운다 |
| **P3** | prod cluster **superuser 도달 경로** | `docker exec kor-travel-geo-postgres psql -U addr -d postgres -Atc "select current_user, rolsuper from pg_roles where rolname=current_user"` → `addr\|t` | step 10 복구 경로가 없다 = **rollback 없음**. `krtour_map`은 `rolsuper=false`·`rolcreatedb=false`이고 6개 스키마·extension 5개 owner가 전부 `addr`이므로 `pg_restore`가 extension/owner에서 중단된다 |
| **P4** | P3의 **무자격증명 근거 재확인** | `docker exec kor-travel-geo-postgres tail -12 /var/lib/postgresql/data/pg_hba.conf` → `local all all trust` + `host all all 127.0.0.1/32 trust` + `host all all ::1/128 trust`(마지막 줄만 `all all all scram-sha-256`) | §3.4의 형식 이탈(PGSERVICEFILE/PGPASSFILE 미사용)에 근거가 없어진다. **동시에 이것이 fence에 인증 층이 없다는 뜻이다** — §8 L5의 존재 이유 |
| **P5** | `$CACHE_MGR/.env` **변경 성격 확정 + freeze** | 02:42 변경은 `KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH` **1키만**(`len=87 sha8=3bc99f5d` → `2f2a19e6`), 추가·삭제 0. `2f2a19e6`는 live UI 컨테이너 값과 일치 = 02:37 out-of-band UI recreate 뒤의 **정렬**이다 | window 중 이 파일을 다시 만지면 `_revalidate_compose_environment_snapshot`이 transaction을 중단시킨다. **H35 window 동안 `.env`·`docker-compose.yml` 변경 금지** |
| **P6** | 실행 pair가 manifest와 **drift 없음** | step 1의 `_pair_matches(_inspect_current_pair(cfg), manifest.active)` | 누군가 out-of-band recreate를 했다는 뜻 → 진행 금지, 상태 보존 |
| **P7** | prod alembic head가 **`0063_pipeline_root_id`** | `docker exec kor-travel-geo-postgres psql -U addr -d krtour_map -Atc "select version_num from public.alembic_version"` | 다른 값이면 **비인가 migration**이다. step 4로 진행하지 말고 상태를 보존해 조사한다(task step 3 명시) |
| **P8** | **outage 창 합의** | off-box HAProxy 소유자 통보. n150에는 maintenance surface가 없다(§8) | 공개 URL이 maintenance 페이지가 아니라 **502/503·tcp reset**을 낸다. 합의 없이 시작하면 예고 없는 장애다 |
| **P9** | 도구·산출물 루트 준비 | **§3.6이 통째로 통과** — 산출물 루트 `$H35/{bin,secrets,sql}` 존재(mode 700) + §3.3 표의 "작성 대상" 6개 + `secrets/` 5종 + `sql/` 6종이 실제로 존재 | 절차가 명령으로 뒷받침되지 않는다. **2026-07-30 실측: `/home/digitie/h35/run` 자체가 없고 작성 대상 6개도 0개 존재** → §3.6이 step 0/1보다 먼저다 |
| **P10** | `$T` 확정 | `git -C $MAP_CTX rev-parse origin/main` **그리고** `git -C $MAP_CTX merge-base --is-ancestor 653d82a2 $T` (H36 포함) | H36이 없는 이미지를 배포하면 step 7의 유일한 명시 게이트가 원리적으로 실패한다. task 명시로 **H36이 H35보다 먼저**다 |

**금지(전 구간).** `docker image prune` — reclaimable 24.28 GB 안에 step 1의 rollback image
set이 들어 있다. `docker builder prune`(73.8 GB reclaimable)은 **step 2 build 성공 이후 ·
step 5 복원 이전에만**, 승인 아래(§5 H-8).

---

## 2. 단계 지도와 fence 구간

| step | 무엇 | 표기 | fence |
|------|------|------|-------|
| **0′** | **산출물 루트·비밀 파일·도구 생성 (§3.6, 전 단계 선행)** | `[W]`(n150 파일만) | — |
| 0 | 디스크 회수 — **조건부. P1 재측정이 40 GiB 미만일 때만** | `[W][S]` ⛔ | — |
| 1 | rollback image set 고정 + baseline bundle | `[W]`(태그만) | — |
| 2 | candidate build-only (컨테이너 0개) | `[W]`(이미지·태그만) | — |
| 3 | H36 게이트 offline 확인 + H36 pre 측정 + prod head 재확인 | `[R]` | — |
| 4 | **cold writer fence 진입** (5층) | `[W][S]` ⛔ | **진입** |
| 5 | 백업·복원 gate (+5.5 scratch 리허설) | `[W]`(scratch·파일) | 유지 |
| 6 | API candidate recreate → 0064~0068 적용 | `[W]` ⛔ **비가역 시작** | 유지 |
| 7 | fence 안 구조 실증 | `[R]` | **유지(여기까지 필수)** |
| 8 | post-migration bundle · daemon preflight (**8-1은 prod API 정지 = prod 변경**) | `[W]`(8-1 prod 정지 + scratch·파일) | 유지 |
| 9 | 비-daemon 3 service recreate·health | `[W]` | 유지 |
| 10 | (실패 시) 복구 분기 — DB rename swap + exact rollback image | `[W]` ⛔ | 유지 |
| 11 | forward-only cutover · manifest 재정합 · fence 해제 | `[W]` ⛔ | **해제** |

**fence는 step 4-7 통과부터 step 11-6까지 끊기지 않는다.** task step 4가 "dump·migration·
구조 smoke가 끝날 때까지"라고 못 박았고, **컨테이너 정지만으로는 step 6부터 유지가
불가능하다** — candidate API가 `network_mode: host`로 `0.0.0.0:12701`에 되살아나므로
LAN·off-box HAProxy가 다시 write 가능해진다. **그 구멍을 §8의 L2(iptables)가 덮는다 — 단
off-box에 한해서다.**

> ⚠️ **L2는 loopback을 덮지 않는다 (감사 확정, 이전 판본의 과대 진술을 정정).** L2 체인의
> 첫 두 규칙이 `-i lo -j RETURN` / `-s 127.0.0.0/8 -j RETURN`이므로 **on-box loopback은
> 설계상 통과**다(그래야 smoke·H36 게이트가 성립한다). L5(`CONNECTION LIMIT 0`)는 6-0에서
> 원복되고 L3는 step 6에서 설계상 깨진다. 따라서 **step 6-0부터 step 11-6까지 on-box
> loopback writer를 막는 층은 하나도 없다.** 실측상 host-network `pinvi-api`가 이 구간
> 내내 running이고 `PINVI_KOR_TRAVEL_MAP_ADMIN_BASE_URL=http://127.0.0.1:12701` +
> ops cancel/read token을 갖고 있다. 완화 요인은 두 개다 — (a) L2가 12801/12805도 비-loopback
> 에서 막으므로 **off-box에서 PinVi UI/API를 구동해 그 write를 유발할 수 없고**,
> `pinvi-dagster`(유일한 자동 발화원)는 4-4에서 정지된다, (b) 남는 것은 host 위 사람·잔여
> 프로세스의 직접 호출뿐이다. 그럼에도 **이 구간의 write는 step 10을 타면 전부 영구
> 소실된다**(`archive_mode=off`) — 그래서 §16 **H-6이 이것을 승인 항목으로 명명한다.**
> 정지를 선택할 수 있으면 4-4에서 `pinvi-api`도 함께 내리는 것이 더 강한 형태다(§8.2 각주).

---

## 3. 공통 기반

### 3.1 경로·상수

```bash
CACHE_MGR=/home/digitie/.cache/c7-final.pihf0x9o/manager   # prod compose project 루트
MAP_CTX=/home/digitie/.cache/c7-final.pihf0x9o/map         # map build context
PINVI_CTX=/home/digitie/.cache/c7-final.pihf0x9o/pinvi     # pinvi build context (2-1이 clean 확인)
H35=/home/digitie/h35/run                                  # mode 700, owner digitie (§3.6이 만든다)
T=ddd1308cf7350862ded97df8ca0ff72d70ec2c73                 # P10에서 재확인
RB_REV=c8ed6164381fccd35df1840427e5a682f2a2789d            # 현행 map 4 service revision
```

> ⛔ **이 5개는 문서 안의 읽기 편의용 이름일 뿐 셸 변수가 아니다.** `wsl ssh n150 '…'`의
> 작은따옴표 안에서는 로컬 확장이 막히고 **원격 셸에는 정의가 없어 `$CACHE_MGR`은 빈
> 문자열이 된다**(실측: `cd $CACHE_MGR` → `cd`(=`$HOME`) → `./.venv/bin/python` 부재).
> **본문의 모든 명령은 절대경로를 인라인으로 쓴다.** 이전 판본이 18곳에서 이 규칙을 어겼고
> 감사가 BLOCKER로 확정했다 — 지금은 0곳이다.

**원격 셸 인용 규약 (2026-07-30 실측으로 확정).**

| 형태 | 쓰는 곳 | 왜 |
|---|---|---|
| `wsl ssh n150 '…절대경로만…'` | 리터럴 SQL이 없는 모든 명령 | 로컬 확장을 막고 원격에 문자 그대로 전달 |
| `wsl ssh n150 "docker exec -i … psql … -f -" <<'SQL' … SQL` | **SQL 문자열 리터럴(`'…'`)이 필요한 모든 psql 호출** | heredoc이 로컬에서 stdin으로 흘러 ssh → `docker exec -i` → `psql -f -`로 그대로 도달한다. 인용 지옥이 없다 |
| `wsl ssh n150 '… -f - < /home/digitie/h35/run/sql/<name>.sql'` | 재사용하는 SQL | §3.6이 만든 파일. 위와 등가이고 재현 가능 |

> ⛔ **`\x27`을 쓰지 않는다.** 원격 bash의 큰따옴표 안에서 `\x27`은 확장되지 않고 psql에
> 문자 그대로 전달돼 `ERROR: syntax error at or near "\"`가 난다(실측 재현). 이전 판본이
> 6곳(5-0·5-1·6-0b·10-3·10-5)에서 이 형태를 썼고 **그중 둘이 rollback 분기의 첫 명령과
> swap 직전 검사**였다. 전부 위 heredoc/`-f -` 형태로 교체했다.

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
- driver의 핵심 seam (배포 rev `c7328ed9`에서 **전수 대조**했고, `_run_up_stage`
  한 건에서 이전 판본이 필수 keyword를 빠뜨렸던 것을 아래에서 정정했다):

```python
tx, _ = compose_service._capture_transaction_unlocked(derive_manifest_path=True)
assert_manager_mutation_allowed(environment=tx.environment.effective)
cfg = load_c6c_deployment_config_from_environment(tx.environment.effective)
# build-only:   _prepare_c6c_candidate_pair(cfg, build=True, build_provenance=prov, transaction=tx)
# service 정지: compose_service.run(["stop", …], mutation_capability=_COMPATIBLE_PAIR_MUTATION_CAPABILITY, transaction=tx)
```

**`_run_up_stage`는 래퍼를 통해서만 부른다.** 시그니처(`compose_service.py:3507-3524`)의
`capture_output: bool`은 **기본값이 없는 keyword-only**이고(`wait: bool = False`와 달리),
`result`는 **미리 형상이 잡힌 dict**여야 한다(`:3568` `result["command"].append`, `:3569-3571`
`result["stages"].append`, `:3577-3578` `result["stdout"] += / result["stderr"] +=`,
`:3583-3584` `result["success"]/["returncode"]`). sanctioned deploy도
`_activate_pair_sequentially`의 `:3844` 호출에서 `:3852` `capture_output=True`를 **명시**한다.
빠뜨리면 `TypeError: _run_up_stage() missing 1 required keyword-only argument:
'capture_output'`으로 **step 6(비가역 시작점)·9·10-6·11-2가 첫 줄에서 죽는다.**

```python
# $H35/bin/h35ctl.py 안의 정본 래퍼. 본문의 `up_stage(...)`는 전부 이것을 가리킨다.
def up_stage(cfg, tx, stage: str, services: list[str],
             env: dict[str, str]) -> tuple[bool, dict]:
    result: dict = {                       # ← 사전 형상이 계약이다 (deploy의 :2991-3009와 동형)
        "success": True, "returncode": 0,
        "command": [], "stages": [], "stdout": "", "stderr": "",
    }
    ok = compose_service._run_up_stage(
        result, stage, services,
        build=False, recreate=True, no_deps=True,
        wait=False,                        # ← 필수. 아래 근거
        capture_output=True,               # ← 필수 keyword. 기본값이 없다
        environment=env,
        mutation_capability=_COMPATIBLE_PAIR_MUTATION_CAPABILITY,
        redact_config=cfg,                 # stdout/stderr redaction
        transaction=tx,
    )
    return ok, result
```

`wait=False`가 필수인 근거는 **하나뿐이다** — `_run_up_stage`가 `wait=True`일 때
`args.extend(["--wait", "--wait-timeout", "120"])`를 **하드코딩**하고
(`compose_service.py:3540`), 0064~0068이 120초를 넘기면 마이그레이션은 계속 도는데 stage만
실패로 접힌다. health는 별도 폴링으로 본다. (이전 판본이 근거로 얹었던 "entrypoint 재시도
예산 60초"는 **사실 오류였다** — §10에서 삭제·정정했다.)

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
| `h35ctl.py` | §3.2 driver (`up_stage` 래퍼 포함) | **작성 대상** (`$H35/bin/`) |
| `h35-identity-52.sql` | 52 테이블 `count(*)` + `sum(hashtextextended(t::text,0))` | **작성 대상** (`$H35/bin/`) |
| `h35_changes_collect.py` | step 8 concierge `changes` 전량 수집 | **작성 대상** (`$H35/bin/`) |
| `h35_env_negcheck.py` | scratch 컨테이너 env 음성 검사 — `--stdin`/`--env-file` 두 모드 | **작성 대상** (`$H35/bin/`) |
| `h35_mk_preview_conf.py` | H36 preview용 `curl --config` 생성(mode 600) | **작성 대상** (`$H35/bin/`) |
| `partial-state.sql` | step 6 부분 적용 probe | **작성 대상** (`$H35/bin/`) |

**`h35_record_rollback.py`는 작성 대상에서 제외했다** — §5 어디에서도 호출되지 않는
유령 항목이었다(감사 지적). step 1의 identity 채취는 1-2/1-3/1-5의 명시 명령과 1-6의
`SHA256SUMS` 결속이 수행한다. **작성 대상은 7개가 아니라 6개다**(P9가 세는 값).

**`h35_env_negcheck.py`의 두 모드 판정 기준 (이전 판본은 `--env-file` 모드의 기준이
없었다).** 어느 모드든 위반 1건이면 exit 1, 값은 출력하지 않고 **키 이름 + 위반 사유만**
낸다.

| 모드 | 입력 | 실패 조건 |
|---|---|---|
| `--stdin` | `docker inspect … {{range .Config.Env}}` | 어떤 값의 `sha256[:8]`도 `67c3f5db`(prod DB password 지문)와 같지 않을 것 · 어떤 값도 `127.0.0.1:5432`를 포함하지 않을 것 |
| `--env-file <path>` | 기동 **전**의 `--env-file` 원본 | 위 두 조건 **그대로** + `*_DSN`/`*_URL`/`*_URI` 계열 값의 host가 `h35-scratch-pg` 이외일 것 0건 + `KOR_TRAVEL_MAP_DOCKER_PG_DSN`·`DAGSTER_PG_*` 키가 prod 호스트/DB 이름(`krtour_map`, `krtour_map_dagster`, `127.0.0.1`, `localhost`)을 포함하지 않을 것 |
| `--fingerprint-only` | resolved config stdin | 값을 절대 착지시키지 않고 `{키: sha8/len}` + `divergent_keys`만 출력 |

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
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie ./.venv/bin/python \
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
(주석은 정반대로 적혀 있다). **`/home/digitie/h35/rehearsal/`** 로 개명해 이름으로 무효를
못 박는다(`[sudo]`, §16 H-2). `$H35`(=`/home/digitie/h35/run`) **밑이 아니다** — 산출물
루트에 무효 dump를 두지 않는다. **형식·툴체인만 재사용 가능하다** — TOC가 `TABLE DATA`
정확히 52건 + extension 5 + SEQUENCE SET 6으로 content-complete·owner/ACL 보존형임을
증명한다.

### 3.6 step 0′ — 산출물 루트·비밀 파일·SQL 생성 `[W]`(n150 파일만) — **모든 단계보다 먼저**

**목적.** 이 절이 없으면 step 1-2가 **첫 리다이렉트에서 `No such file or directory`로
죽는다**(실측: `/home/digitie/h35/run` 부재). 소비만 있고 생성 주체가 없던 파일
(`curl-login.conf`·`scratch.env`·`scratch-api.env`·`scratch-daemon.env`·`pg_service.conf`·
`pgpass`·`initdb.d/*`)의 생성 주체를 여기서 확정한다. **prod에는 아무 영향이 없다.**

```bash
# 0′-1 [W] 루트 3개. umask가 먼저다 — 이후 모든 리다이렉트가 mode 600으로 착지한다
wsl ssh n150 'umask 077; mkdir -p /home/digitie/h35/run/bin /home/digitie/h35/run/secrets \
  /home/digitie/h35/run/sql /home/digitie/h35/run/secrets/initdb; \
  chmod 700 /home/digitie/h35/run /home/digitie/h35/run/bin \
            /home/digitie/h35/run/secrets /home/digitie/h35/run/sql \
            /home/digitie/h35/run/secrets/initdb'

# 0′-2 [W] 재사용 SQL 9종 — \x27 문제를 구조적으로 없앤다 (§3.1 인용 규약)
wsl ssh n150 'umask 077; cat > /home/digitie/h35/run/sql/connlimit-set0.sql' <<'SQL'
ALTER DATABASE krtour_map CONNECTION LIMIT 0;
ALTER DATABASE krtour_map_dagster CONNECTION LIMIT 0;
SQL
wsl ssh n150 'umask 077; cat > /home/digitie/h35/run/sql/connlimit-reset.sql' <<'SQL'
ALTER DATABASE krtour_map CONNECTION LIMIT -1;
ALTER DATABASE krtour_map_dagster CONNECTION LIMIT -1;
SQL
wsl ssh n150 'umask 077; cat > /home/digitie/h35/run/sql/connlimit-verify.sql' <<'SQL'
SELECT datname, datconnlimit FROM pg_database
 WHERE datname LIKE 'krtour_map%' ORDER BY datname;
SQL
wsl ssh n150 'umask 077; cat > /home/digitie/h35/run/sql/statdb.sql' <<'SQL'
SELECT datname, xact_commit, tup_inserted, tup_updated, tup_deleted
  FROM pg_stat_database
 WHERE datname IN ('krtour_map', 'krtour_map_dagster')
 ORDER BY datname;
SQL
wsl ssh n150 'umask 077; cat > /home/digitie/h35/run/sql/sessions-app.sql' <<'SQL'
SELECT pid, usename, state, xact_start FROM pg_stat_activity
 WHERE datname = 'krtour_map' AND pid <> pg_backend_pid();
SQL
wsl ssh n150 'umask 077; cat > /home/digitie/h35/run/sql/sessions-both-count.sql' <<'SQL'
SELECT count(*) FROM pg_stat_activity
 WHERE datname IN ('krtour_map', 'krtour_map_dagster');
SQL
wsl ssh n150 'umask 077; cat > /home/digitie/h35/run/sql/violations-status-payload-md5.sql' <<'SQL'
SET TimeZone='UTC'; SET DateStyle='ISO, MDY'; SET IntervalStyle='postgres';
SET extra_float_digits=3; SET bytea_output='hex';
SELECT 'G19b_violations_status_payload_md5' AS gate,
       left(md5(string_agg(issue_id::text || '|' || status || '|'
                           || coalesce(resolved_at::text, 'NULL') || '|' || payload::text,
                           E'\n' ORDER BY issue_id)), 8) AS value8
  FROM ops.data_integrity_violations;
SQL
wsl ssh n150 'umask 077; cat > /home/digitie/h35/run/sql/rollback-create-db.sql' <<'SQL'
CREATE DATABASE krtour_map_h35rb OWNER krtour_map TEMPLATE template0
  ENCODING 'UTF8' LC_COLLATE 'en_US.utf8' LC_CTYPE 'en_US.utf8';
CREATE DATABASE krtour_map_dagster_h35rb OWNER krtour_map TEMPLATE template0
  ENCODING 'UTF8' LC_COLLATE 'en_US.utf8' LC_CTYPE 'en_US.utf8';
SQL
wsl ssh n150 'umask 077; cat > /home/digitie/h35/run/sql/rollback-swap.sql' <<'SQL'
ALTER DATABASE krtour_map          RENAME TO krtour_map_h35broken;
ALTER DATABASE krtour_map_dagster  RENAME TO krtour_map_dagster_h35broken;
ALTER DATABASE krtour_map_h35rb          RENAME TO krtour_map;
ALTER DATABASE krtour_map_dagster_h35rb  RENAME TO krtour_map_dagster;
SQL

# 0′-3 [W] 비밀 파일 6종 + initdb 1종. **값은 process env에서 읽어 넣고 argv/문서에 싣지 않는다**
#   (a) curl-login.conf — UI admin login POST. 1-4 / step 9 / 10-6이 소비한다
#       PW=$(docker inspect kor-travel-map-ui-latest --format '{{range .Config.Env}}…')
#       형태로 컨테이너에서 읽어 heredoc 변수로만 흘린다. 파일 mode 600, 사용 후 shred -u.
wsl ssh n150 'umask 077; /home/digitie/h35/run/bin/h35ctl.py mk-login-conf \
  --container kor-travel-map-ui-latest \
  --out /home/digitie/h35/run/secrets/curl-login.conf'
#       내용 형식(값 자리는 driver가 채운다):
#         url      = "http://127.0.0.1:12705/api/auth/login"
#         request  = "POST"
#         header   = "Content-Type: application/json"
#         data     = "{\"username\":\"…\",\"password\":\"…\"}"
#
#   (b)(c)(d) scratch 3종 — **throwaway 자격증명만.** prod 값을 넣지 않는다
wsl ssh n150 'umask 077; /home/digitie/h35/run/bin/h35ctl.py mk-scratch-secrets \
  --out-dir /home/digitie/h35/run/secrets'
#       생성물: scratch.env(POSTGRES_USER=addr / POSTGRES_PASSWORD=<throwaway> /
#                 POSTGRES_INITDB_ARGS=--locale=en_US.utf8 --encoding=UTF8)
#               scratch-api.env   (KOR_TRAVEL_MAP_DOCKER_PG_DSN=…@h35-scratch-pg:5432/krtour_map, 그 외 최소)
#               scratch-daemon.env(DAGSTER_PG_* → h35-scratch-pg, app DSN 동일 host)
#               pg_service.conf(비밀 없음: [ktm-scratch-app] host=h35-scratch-pg dbname=krtour_map user=addr
#                                          [ktm-scratch-dagster] … dbname=krtour_map_dagster)
#               pgpass(h35-scratch-pg:5432:*:addr:<throwaway>)
#               initdb/01-roles-dbs.sql(CREATE ROLE krtour_map LOGIN PASSWORD '<throwaway2>';
#                                        CREATE DATABASE krtour_map / krtour_map_dagster OWNER krtour_map …)
#
#   (e) 권한 확정
wsl ssh n150 'chmod 600 /home/digitie/h35/run/secrets/* /home/digitie/h35/run/secrets/initdb/*; \
  ls -l /home/digitie/h35/run/secrets /home/digitie/h35/run/secrets/initdb'

# 0′-4 [W] 작성 대상 도구 6개 배치 (§3.3) 후 존재 확인 = P9
wsl ssh n150 'ls -l /home/digitie/h35/run/bin/h35ctl.py /home/digitie/h35/run/bin/h35-identity-52.sql \
  /home/digitie/h35/run/bin/h35_changes_collect.py /home/digitie/h35/run/bin/h35_env_negcheck.py \
  /home/digitie/h35/run/bin/h35_mk_preview_conf.py /home/digitie/h35/run/bin/partial-state.sql'
```

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| 루트 3개 | `/home/digitie/h35/run/{bin,secrets,sql}` 전부 mode **700**, owner `digitie` | 없거나 mode가 다르면 step 1-2가 죽거나 비밀이 group/other에 열린다 |
| `sql/` 9개 | 위 heredoc 9개 파일 존재, mode 600 | 없으면 5-0·5-1·6-0b·10-3·10-5가 실행 불가 |
| `secrets/` | `curl-login.conf`·`scratch.env`·`scratch-api.env`·`scratch-daemon.env`·`pg_service.conf`·`pgpass` + `initdb/01-roles-dbs.sql`, 전부 mode **600** | 644면 `umask`가 적용되지 않았다 |
| `scratch-*.env` 음성 검사 | `h35_env_negcheck.py --env-file <각각>` 통과 | prod DSN/지문이 섞였다 → 5.5·8-5가 prod에 붙는다 |
| `bin/` 6개 | 6개 전부 존재·실행 가능 = **P9 통과** | 하나라도 없으면 그 단계의 실행 주체가 없다 |
| prod 무영향 | `docker ps` 21행 불변, `alembic_version=0063_pipeline_root_id` | 변했다면 이 절이 prod를 건드린 것이다(있을 수 없다) |

**실패 시 분기.** 이 절의 실패는 전부 무해하다 — 고쳐서 다시 만든다. **P9가 통과하기
전에는 step 0/1에 들어가지 않는다.**

---

## 4. step 0 — 디스크 회수 **(조건부. 기본은 실행하지 않는다)** `[W][S]` ⛔

> ⛔ **이 단계는 P1이 실제로 미달일 때만 존재한다.** 2026-07-30 실측 avail = **84.2 GiB**로
> 임계 40 GiB를 **이미 통과했다** — 그때는 **0-1만 기록용으로 돌리고 0-2는 발화하지 않으며
> 곧장 §3.6 → step 1로 간다.** 이전 판본은 "53.7 GiB이므로 미달"이라는 **산술 오류**(53.7 ≥
> 40)로 이 단계를 무조건 선행으로 두었고, 그 잘못된 결론이 비가역 `DROP DATABASE`(H-1, PITR
> 없음)를 정당화했다. 게다가 그 판본이 이름으로 지목한 최대 회수 대상
> `kor_travel_geo_restore`(31.5 GiB)는 **이미 존재하지 않는다.**

**목적(조건부).** 0-1 재측정이 40 GiB 미만일 때만, step 5의 22.3 GiB scratch 복원과
step 10의 rollback DB가 disk full로 실패하는 것을 막는다. 그 실패는 동거하는
geo·concierge·pinvi를 함께 죽인다.

**명령.**

```bash
# 0-1 [R] 재측정 + 회수 후보 열거. **이것은 항상 돌린다(기록용)**
wsl ssh n150 "docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -A -F '|' -f -" <<'SQL'
SELECT datname,
       pg_size_pretty(pg_database_size(datname)) AS size,
       datdba::regrole::text AS owner
  FROM pg_database
 ORDER BY pg_database_size(datname) DESC
 LIMIT 15;
SQL
wsl ssh n150 'df -B1 --output=avail /; df -h /; docker system df'

# 0-2 [W][S] ⛔ **0-1의 avail이 42949672960(40 GiB) 미만일 때만.** 승인 후 사람이 실행
#     대상은 `*_restore` / `*_restore_manual` / `ktc_t1*` 로 한정한다(합계 ≈ 70 MB, 실측).
#     docker exec kor-travel-geo-postgres psql -U addr -d postgres -c "DROP DATABASE <name>"
```

> ⛔⛔ **0-2 발화 전에 반드시 눈으로 읽어야 하는 것.** 지금 이 cluster에서 31 GB급으로 남은
> DB는 **`kor_travel_geo`(32 GB, owner `addr`) 하나뿐이고 이것은 형제 서비스
> kor-travel-geo의 운영 DB다 — 회수 대상이 아니다.** 이전 판본이 지목한
> `kor_travel_geo_restore`와 이름이 `_restore` 한 토큰만 다르다. **`DROP DATABASE`의 인자를
> 0-1 출력에서 복사해 붙이지 말고, 이름 전체를 소리 내어 대조한 뒤 손으로 친다.** 이것이
> 이 저장소가 반복한 "identity를 한 축 덜 잡음" 패턴의 정확한 발현 지점이다.

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| 0-1 `df -B1 --output=avail /` | ≥ `42949672960` (40 GiB). **2026-07-30 실측 `90,358,456,320` = 84.2 GiB** | 미달일 때만 0-2로 간다. 미달 상태로 **step 5 진입 금지** |
| 0-1 상위 15개 DB 열거 | `kor_travel_geo` 32 GB(운영, 보존) / `krtour_map` 22.3 GiB(대상 DB) / `krtour_map_dagster` 749 MB / 나머지 `*_restore*` 합계 ≈ 70 MB | `kor_travel_geo_restore`가 **다시 나타나면** 누군가 복원한 것이다 → 중단·조사 |
| 0-2를 돌렸다면: 회수 대상이 어떤 task 산출물도 아님 | 소유자(`datdba`)·용도 확인 기록 | 확인 없이 지우면 타 task 산출물이 사라진다 |

**실패 시 분기.** 40 GiB에 도달하지 못하면 **`DROP DATABASE`보다 `docker builder prune`
(74.02 GB reclaimable, 실측)이 먼저다** — 대가는 캐시 소실로 인한 재빌드 지연뿐이고
이미지에는 무영향이다(§16 H-10). **단 step 2 build 성공 이후·step 5 복원 이전에만.**
`docker image prune`은 전 구간 금지. 그래도 미달이면 H35를 시작하지 않는다.

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
#   보조 축 G19b — 게이트 파일 밖이다(§11 박스). pre 실측 5c16deff…
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F "|" \
  -f - < /home/digitie/h35/run/sql/violations-status-payload-md5.sql \
  >> /home/digitie/h35/run/gate-pre.txt'

# 1-4 [R] 현행 smoke — API 200 / Dagster web 200 / login POST 200 / UI build-info는 **401 기대**
wsl ssh n150 'curl -sS -o /dev/null -w "api=%{http_code}\n"     http://127.0.0.1:12701/health'
wsl ssh n150 'curl -sS -o /dev/null -w "dagster=%{http_code}\n" http://127.0.0.1:12702/'
wsl ssh n150 'curl -sS -o /home/digitie/h35/run/buildinfo-pre.json \
  -w "buildinfo=%{http_code}\n" http://127.0.0.1:12705/api/build-info'
wsl ssh n150 'curl -sS --config /home/digitie/h35/run/secrets/curl-login.conf \
  -o /dev/null -w "login=%{http_code}\n"'

# 1-5 [R] ktdctl 쪽 baseline
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/ktdctl status pinvi --json > /home/digitie/h35/run/ktdctl-status-pre.json'

# 1-6 [R] **manifest/compose/.env checksum + bundle 결속** (task step 1 "redacted checksum" 요구)
#   파일 sha256은 비밀 노출이 아니다 — §3.4의 "보간된 config를 착지시키지 않는다"와 무관하다
wsl ssh n150 'sha256sum \
  /home/digitie/.cache/c7-final.pihf0x9o/manager/docker-compose.yml \
  /home/digitie/.cache/c7-final.pihf0x9o/manager/.env \
  "$(HOME=/home/digitie /home/digitie/h35/run/bin/h35ctl.py manifest-path)" \
  > /home/digitie/h35/run/config-checksums-pre.txt'
wsl ssh n150 'cd /home/digitie/h35/run && sha256sum containers-pre.txt gate-pre.txt \
  buildinfo-pre.json ktdctl-status-pre.json config-checksums-pre.txt candidate-pair.json 2>/dev/null \
  | tee SHA256SUMS.step1 >/dev/null; chmod 600 SHA256SUMS.step1; cat SHA256SUMS.step1'
```

**직후 검증과 반증.**

| 검증 | 통과값 | 실패했다면(= 다른 값) |
|---|---|---|
| `rep.ensured` / `rep.removed` | **5 / 0** — active 5개가 신규 태깅됨 | `ensured != 5`면 이미 태그가 있었다는 뜻 = 전제가 다르다 |
| `_owned_references` | 정확히 **10개**(active 5 + rollback 5) | 10이 아니면 retention 상태가 기대와 다르다 → 중단 |
| retention ref 5개의 `.Id` | `containers-pre.txt`의 `.Image` 5개와 문자 단위 일치 | 다른 ID/`No such image` → 기록이 잘못됐다 |
| `_pair_matches` | True (P6) | False = out-of-band recreate 발생 → 진행 금지, 상태 보존 |
| `alembic_version` | `0063_pipeline_root_id` 정확히 1행 | 다른 값 → **비인가 migration**(P7) |
| **UI `/api/build-info` (baseline 축)** | **`401`** — 그리고 그것이 정상이다 | **200이나 503이 오면 중단·조사한다.** 근거는 아래 박스 |
| 4개 map revision | 전부 `c8ed6164…` | 하나라도 다르면 현행이 이미 혼재 배포 상태 |
| 1-6 checksum | `docker-compose.yml`·`.env`·`compatible-pair-v4.json` 3줄 채취 + `SHA256SUMS.step1` 생성 | 채취 실패 = P5의 "window 중 변경 금지"에 **탐지 수단이 없어진다** → step 2로 가지 않는다 |

> ### `/api/build-info` 게이트는 **비대칭**이다 — baseline 401 / candidate 200
>
> 이전 판본은 baseline에 `200 + revision == c8ed6164…`를 요구하고 실패값으로 `503`만
> 열거했다. **둘 다 성립하지 않는다 — 실측은 `401`이고, 그것이 정상이다.** 절차 전체의 첫
> 게이트가 원리적으로 통과 불가였고("어떤 항목이든 실패하면 step 2로 가지 않는다"),
> 감사가 이것을 최상위 BLOCKER로 확정했다.
>
> **근거 — 세 축이 독립으로 일치한다(2026-07-30 실측).**
>
> 1. **live 응답**: `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:12705/api/build-info`
>    → **401** (`{"error":"AUTH_REQUIRED"}`). 같은 시점 `api=200`, `dagster=200`,
>    `/admin` → **307**(로그인 리다이렉트) — 즉 **UI 자체는 정상이고 그 경로만 없다.**
> 2. **실행 중 이미지의 번들**:
>    `docker exec kor-travel-map-ui-latest grep -rl "build-info" /app/.next/server` →
>    **출력 없음.** 배포 리비전의 서버 번들에 그 문자열이 **아예 없다** = route 부재의
>    직접 증거이며, 라벨이나 git 조회에 의존하지 않는 축이다.
> 3. **소스**: `git ls-tree c8ed6164 -- …/frontend/src/app/api/` → `auth/`·`geo/`·`proxy/`
>    3개뿐(**`build-info/` 없음**). `git show c8ed6164:…/middleware.ts` → `PUBLIC_EXACT_PATHS`
>    **없음**, public 접두사는 `/api/auth/`·`/_next/`·`/favicon.ico`뿐 → 세션 없는 `/api/*`는
>    **전부 401**. `PUBLIC_EXACT_PATHS = new Set(["/login","/api/build-info"])`와 `route.ts`는
>    **candidate 쪽에만** 있다.
>
> | 축 | 어디 | 통과값 | 실패값의 의미 |
> |---|---|---|---|
> | baseline | 1-4 (`c8ed6164`) | **401** **그리고** 번들 grep 결과 **빈 출력** | **200** = 이미 candidate UI가 떠 있다 → out-of-band 배포, 중단·조사. **503** = UI가 `$T`도 `c8ed6164`도 아닌 제3의 빌드. **번들에 `build-info`가 있는데 401** = middleware만 다른 빌드 |
> | candidate | step 9 / 10-6 (`$T`) | **200** + `revision == $T`(40-hex) + `source_digest` 64-hex = 2-3 선계산값 | 503/401 = §13 참조 |
>
> **candidate 쪽 통과값은 `$T`로만 쓴다 — 리터럴 커밋을 여기 박지 않는다.** `$T`는 P10이
> 실행 시점에 `git -C $MAP_CTX rev-parse origin/main`으로 고정한다. 이 문서가 기록한
> 2026-07-30 값은 `ddd1308c…`이고 같은 날 `origin/main`과 일치했다. **단 target 표기가
> 갈린 흔적이 있다 — n150에 `h35-deploy-0add95a5.sh`(mtime 01:11)가 남아 있고 운영 대화에서
> `0add95a5`가 target으로 언급됐다.** 실측 대조 결과: `0add95a5`는 `ddd1308c`의 **조상**이고
> (`merge-base --is-ancestor` YES, PR #894 vs #896), **두 커밋 모두 H36(`653d82a2`)을 포함하며
> 둘 다 `api/build-info/` route를 갖는다** — 따라서 이 게이트의 설계는 어느 쪽이든 성립한다.
> 그러나 **어느 커밋을 배포하는지는 P10에서 하나로 확정해야 하고**, 확정 전에는 step 2에
> 들어가지 않는다(§17-16).
>
> **따라서 baseline UI identity는 build-info가 아니라 다른 축으로 잡는다** —
> `containers-pre.txt`의 image ID `262ea36ac6b0…` + 라벨
> `org.opencontainers.image.revision == c8ed6164…` + step 1의 immutable retention 태그
> 세 개다. step 9/10의 UI identity 기준은 **candidate 쪽 200에 걸려 있으므로 무의미해지지
> 않는다.** (§17-9는 이로써 해소됐다.)

**반증성의 근거.** 지금 active 이미지에는 immutable 태그가 **하나도 없다**(실측). 통과가
곧 "이제 `c8ed6164`가 `:latest-main` 없이도 보존된다"는 증거다.

**쓰지 않는 기준.** "`docker ps` 5/5 Up" — 현행이 실제로 그러니 항상 통과하고 아무것도
반증하지 못한다. **"baseline `/api/build-info` 200"** — 배포 리비전에 그 route가 없어
원리적으로 불가능하다(위 박스).

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
# 2-1b [R] **PinVi worktree도 clean이어야 한다** — `_derive_c6c_build_provenance`는
#   map과 PinVi **양쪽**의 clean HEAD와 exact git root를 요구한다
#   (`compose_service.py:120-140` → `_clean_repository_revision:175-192`
#    "build context worktree is not clean" raise). 이전 판본은 map만 확인했다
wsl ssh n150 'git -C /home/digitie/.cache/c7-final.pihf0x9o/pinvi status --porcelain=v1 \
  --untracked-files=normal'          # 반드시 빈 출력
wsl ssh n150 'git -C /home/digitie/.cache/c7-final.pihf0x9o/pinvi rev-parse --verify HEAD'  # 6a035695…

# 2-2 [R] UI 빌드 인자 완전성 게이트 — 값은 출력하지 않고 sha8/len만 (§3.4)
#   NEXT_PUBLIC_VWORLD_API_KEY / NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY 가 비면 exit 1
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py buildargs-gate'

# 2-3 [R] 기대 frontend source digest 선계산
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/map && node scripts/frontend-source-digest.mjs'

# 2-4 [R] 컨테이너 집합 스냅샷
wsl ssh n150 'docker ps -a --filter label=com.docker.compose.project=kor-travel-docker-manager \
  --format "{{.Names}} {{.CreatedAt}} {{.Image}}" | sort > /home/digitie/h35/run/containers-pre-build.txt'

# 2-5 [W] build-only
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step2 --confirm'
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
   떴다면 `docker/api-entrypoint.sh:216` `while ! alembic upgrade head; do`가 즉시 돌아
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
| 2-1b PinVi worktree | `status --porcelain=v1` **빈 출력** + HEAD `6a035695…` | dirty면 `_derive_c6c_build_provenance`가 `PinVi build context worktree is not clean`으로 raise해 **map build까지 abort된다**(2-5가 시작조차 못 한다) |

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
# 3-0 [R] candidate 이미지 ID 3개를 **원격에서** 채취한다.
#   ⛔ `candidate-pair.json`은 n150에만 있다 — `wsl ssh` 밖에서 `jq`를 돌리면 빈 문자열이
#      되고 3-1/3-2/3-3/5.5/8-5가 전부 인자 없이 발화한다(이전 판본의 결함).
CAND_API=$(wsl ssh n150    'jq -r .map_image_id                /home/digitie/h35/run/candidate-pair.json')
CAND_DG=$(wsl ssh n150     'jq -r .map_dagster_image_id        /home/digitie/h35/run/candidate-pair.json')
CAND_DAEMON=$(wsl ssh n150 'jq -r .map_dagster_daemon_image_id /home/digitie/h35/run/candidate-pair.json')
CAND_UI=$(wsl ssh n150     'jq -r .map_ui_image_id             /home/digitie/h35/run/candidate-pair.json')
# 셋 다 `sha256:`로 시작하는 64-hex여야 한다. 하나라도 빈 문자열이면 여기서 멈춘다
test -n "$CAND_API" && test -n "$CAND_DG" && test -n "$CAND_DAEMON" && test -n "$CAND_UI" \
  || { echo "candidate image id 채취 실패 — step 2의 candidate-pair.json을 확인한다"; exit 1; }

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
#   ⛔ `grep -c`는 **키 존재 개수(1)** 만 낸다 — loopback이 빠져도 항상 1이므로 통과 기준을
#      만들어내지 못한다(이전 판본의 결함). 값 자체를 출력한다. 이 값은 비밀이 아니다
wsl ssh n150 'docker inspect kor-travel-map-api-latest \
  --format "{{range .Config.Env}}{{println .}}{{end}}" \
  | grep "^KOR_TRAVEL_MAP_API_ADMIN_TRUSTED_PROXY_CIDRS="'
#   2026-07-30 실측: KOR_TRAVEL_MAP_API_ADMIN_TRUSTED_PROXY_CIDRS=["127.0.0.1/32","::1/128"]
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
| 3-5 pre 응답 | HTTP 200. **그리고 3행 모두 `candidates`가 비어 있지 않을 것(후보 ≥ 1건)** = `status ∈ {valid, ambiguous}`. 3행이 `status="valid"` + `resolved_feature_id` 채워짐이면 pre→post가 가장 선명하게 갈린다 | 403 = 인증 3층 중 결락 → 게이트 설계 수정 후 재시도. pre에서 이미 `ambiguous`면 **`resolved_feature_id is null` 축은 그 행에서 비판별**이므로 기록하고 step 7에서 `review_required`/`name_only_match` 축만 쓴다. **어느 행이든 `unmatched`(후보 0건)면 그 행은 step 7 판정에서 제외한다** — 아래 박스 |
| 3-6 | 출력 문자열에 **`127.0.0.1/32`가 포함**(실측 `["127.0.0.1/32","::1/128"]`) | 불포함 → API 직접 호출로 preview를 할 수 없다 → step 4에서 UI를 세우면 안 되는 분기가 된다(설계 재검토). §17-10은 이로써 해소됐다 |

> **"후보 ≥ 1건"을 전제 게이트로 올리는 이유 (감사 지적, LOW → 게이트화).**
> `curations.py:674-689`의 상태 결정은 `if not matches: row_status = "unmatched"`가
> `review_required` 가지보다 **먼저** 오고, `_unlinked_issue:552-557`도 `if not matches:`면
> `unmatched`를 낸다. 따라서 **후보가 0건이면 candidate 이미지도 `unmatched`를 내고 두 강
> 판별자(`review_required`, `name_only_match`)가 동시에 부재한다** — 그 상태로 step 7에
> 들어가면 §11 실패 분기가 "이미지가 H36을 담고 있지 않다"는 **거짓 결론**을 낸다.
> 완화 요인은 실측으로 확인됐다 — `feature.features`에서 이름 정확 일치 남이섬 1건 / 청남대
> 1건(`like` 기준 각각 59 / 20)이므로 후보 0건은 실무상 개연성이 낮다. 그래도 **3-5가 그
> 사실을 실제로 측정하고 통과 조건에 올린다.**

**쓰지 않는 기준.** `docker run <cand> alembic current` — 새 컨테이너의 기본 CMD를 타므로
step 2 위반이고 DB 접속도 필요하다. `site-packages/../../../../app/alembic/…` 경로 —
`/usr/app/alembic/…`으로 오해석돼 **항상 실패한다.** 이미지 안 정본 경로는
`/app/alembic/versions`다(`api.Dockerfile:42` `COPY alembic ./alembic` — `:41`은
`COPY alembic.ini ./`다. 이전 판본의 off-by-one을 정정).

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
| **L2** on-box port | `H35FENCE` iptables/ip6tables `INPUT 1` `[S]` | 4-3 → 11-6 | **비-loopback의** 12701/12702/12705/12801/12805. step 6/9에서 컨테이너가 되살아나도 유지된다 — 이 층이 없으면 off-box fence는 step 6에서 구멍이 난다. ⛔ **loopback은 설계상 통과(§2 박스)** |
| **L2b** on-box DB포트 | `H35FENCE` **맨 앞** `-s 172.17.0.0/16 -p tcp --dport 5432 REJECT` `[S]` | 4-3 → 11-6 | **docker bridge 컨테이너 → gateway(`172.17.0.1`) → 호스트 `0.0.0.0:5432`.** 실측으로 이 경로가 열려 있고 app DB를 실제로 읽었다(아래 박스). **L2는 이것을 덮지 않는다 — 5432가 dport 목록에 없다** |
| **L3** 컨테이너 | map 4개 compose stop + `ktdctl action pinvi-dagster stop` | 4-4/4-6 → step 6/9/11의 각 recreate | 자기 자신이 만드는 write |
| **L4** instigator | schedule 34 + sensor 10 = **44건 pause** | 4-5 → 11-5 | schedule/sensor 발화 |
| **L5** 인증·접속 | `ALTER DATABASE … CONNECTION LIMIT 0` | 5-0 → 6-0, **그리고 10-2b → 10-5 재적용** | **dump 창과 swap 창의 신규 비-superuser 접속 전부** |

> **어느 구간도 덮지 못하는 창이 하나 남는다 — 정직하게 기록한다.** **step 6-0(L5 원복)부터
> step 11-6까지 on-box loopback writer를 막는 층은 없다.** 남는 것은 L4(map instigator
> pause)와 L3의 나머지 3 service 정지뿐이고, host-network `pinvi-api`는 이 구간 내내
> running이며 map admin base URL + ops cancel/read token을 갖고 있다(실측). 이 창의 write는
> **step 10을 타면 전부 영구 소실된다**(`archive_mode=off`). §16 **H-6이 이것을 승인
> 항목으로 명명**하며, 4-4는 아래 각주로 "pinvi-api도 정지"라는 더 강한 형태를 제시한다.

> ### ⛔⛔ L2가 덮지 못하는 두 번째 경로 — **docker bridge → gateway → 호스트 `:5432`** (실측 확정)
>
> **이것은 이론이 아니다. 2026-07-30에 bridge 컨테이너에서 prod app DB를 실제로 읽었다.**
>
> ```
> docker network inspect bridge --format "{{range .IPAM.Config}}{{.Gateway}}{{end}}" → 172.17.0.1
> ss -ltn 'sport = :5432'                                 → LISTEN 0.0.0.0:5432 · [::]:5432
> docker run --rm --network bridge postgres:16 \
>   pg_isready -h 172.17.0.1 -p 5432 -t 6                 → "172.17.0.1:5432 - accepting connections" (rc=0)
> docker run --rm --network bridge -e PGPASSWORD=… postgres:16 \
>   psql -h 172.17.0.1 -U krtour_map -d krtour_map -Atc "…count(*) from feature.curation_items"
>                                                          → krtour_map|krtour_map|3530
> ```
>
> **의미.** `kor-travel-geo-postgres`가 `network_mode: host`로 `0.0.0.0:5432`에 바인딩하므로
> **bridge 네트워크의 임의 컨테이너가 gateway IP를 경유해 app DB에 직접 붙을 수 있다.**
> 이 트래픽은 FORWARD가 아니라 **INPUT**을 타고, 실측 `iptables -S INPUT` = `-P INPUT ACCEPT`
> (규칙 0개) · `DOCKER-USER` 비어 있음이므로 아무 층도 이를 막지 않는다.
>
> **L2는 이 경로를 덮지 않는다.** L2가 REJECT하는 것은 dport **12701/12702/12705/12801/12805**
> 이고 **5432는 그 목록에 없다.** 즉 L2는 "앱 포트로 들어오는 off-box 요청"만 막고,
> "DB 포트로 들어오는 컨테이너 요청"은 통과시킨다.
>
> **인증 층도 방어가 되지 않는다.** `pg_hba`의 마지막 줄 `host all all all scram-sha-256`이
> 172.17.x 출발지에 적용되는 것은 맞지만(즉 무자격 접속은 아니다), **app DSN·비밀번호는
> 여러 컨테이너 env에 흔히 들어 있고 위 실측이 바로 그것으로 성공했다.** "자격증명 장벽이
> 있다"를 이 경로의 방어로 계산하지 않는다.
>
> **덮는 방법 = §12 8-5의 scoped reject를 fence 층으로 승격한다.** 규칙은 아래 형태이고
> **4-3에서 H35FENCE를 세울 때 함께 넣는다**(step 8까지 미루지 않는다):
>
> ```bash
> # L2b [W][S] docker bridge subnet → 호스트 :5432 차단. **loopback RETURN보다 앞(-I … 1)**
> wsl ssh n150 'sudo -n iptables -I H35FENCE 1 -s 172.17.0.0/16 -p tcp --dport 5432 \
>   -j REJECT --reject-with tcp-reset'
> ```
>
> **규칙 배치 근거(요구된 명시).** `-I H35FENCE 1`은 이 규칙을 체인 **맨 앞**에 넣어
> `-i lo -j RETURN` / `-s 127.0.0.0/8 -j RETURN`보다 먼저 평가되게 한다. 두 RETURN이 이
> 경로를 실제로 무력화하지는 않는다 — **gateway 트래픽의 출발지는 `172.17.x`이고 입력
> 인터페이스는 `docker0`이지 `lo`가 아니므로** 두 RETURN 어느 쪽에도 매치되지 않는다.
> 그럼에도 맨 앞에 두는 이유는 (a) 이후 누군가 RETURN 범위를 넓혀도 이 규칙이 살아남고,
> (b) 순서가 곧 문서화된 의도이기 때문이다. **출발지 subnet + dport 매칭이므로
> host-network인 map/geo/concierge/pinvi에는 영향이 없다**(그들의 트래픽은 loopback이다).
> `h35-scratch`처럼 **별도 subnet을 쓰는 network는 그 subnet도 함께 넣어야 한다** — §12 8-5가
> `docker network inspect h35-scratch`로 실제 subnet을 읽어 같은 형태로 추가한다.
>
> **음성통제.** 규칙 투입 **후** 위 `pg_isready`를 다시 돌려 **rc != 0**임을 확인한다.
> 그것이 이 경로에 대한 유일한 반증이다(§12 8-5 (2)).

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

# 4-2b [R] ★ **fence 투입 전 양성 대조군** — 이것 없이는 4-3b가 아무것도 반증하지 못한다
wsl ssh n150 'sudo -n iptables -S | grep -c H35FENCE'     # **0** 이어야 한다 (baseline 깨끗)
wsl ssh n150 'ip -o -4 addr show scope global'            # 워크스테이션에서 라우팅되는 주소만 추린다
# 워크스테이션에서 — 위에서 추린 각 주소에 대해 **지금은 반드시 성공해야 한다**
#   curl -sS -m 5 -o /dev/null -w "%{http_code}\n" http://<addr>:12701/health   # 200
# 200을 받지 못한 주소는 **fence와 무관하게 도달 불가**이므로 4-3b의 판정 대상에서 제외하고
# 그 사실을 기록한다. docker bridge gateway(172.x)·`br-*`·`::1`이 여기 걸린다

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

# 4-3c [W][S] ★ L2b — docker bridge → 호스트 :5432 차단. **체인 맨 앞(-I … 1)**
#   근거·배치 이유는 §8.1의 L2b 박스. 이것 없이는 bridge의 임의 컨테이너가 fence를 우회해
#   app DB에 직접 write할 수 있다(실측으로 읽기 성공 확인됨)
wsl ssh n150 'docker network inspect bridge --format "{{range .IPAM.Config}}{{.Subnet}}{{end}}"'  # 172.17.0.0/16
wsl ssh n150 'sudo -n iptables -I H35FENCE 1 -s 172.17.0.0/16 -p tcp --dport 5432 \
  -j REJECT --reject-with tcp-reset'
# 4-3d [R] ★ L2b 음성통제 — **투입 후 반드시 실패해야 한다**
wsl ssh n150 'docker run --rm --network bridge postgres:16 \
  pg_isready -h 172.17.0.1 -p 5432 -t 6; echo "exit=$?"'      # exit != 0 (투입 전 실측은 rc=0)

# 4-3b [R] **4-2b에서 200을 받은 주소 전부**에 대해 각각 실패를 확인한다 (하나만 보면 안 된다)
wsl ssh n150 'sudo -n iptables -S | grep -c H35FENCE'   # > 0 (체인이 실제로 걸렸다)
# 워크스테이션에서 — 4-2b가 200을 준 각 주소에 대해 반드시 실패해야 한다
#   curl -sS -m 5 http://<addr>:12701/health ; echo "exit=$?"      # exit != 0 (tcp reset)
#   curl -sS -m 10 -o NUL -w "%{http_code}\n" https://map.digitie.mywire.org/health   # 502/503
# n150에서 — 반드시 성공해야 한다
wsl ssh n150 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:12701/health'   # 200

# 4-4 [W] PinVi Dagster 정지 — ktdctl CLI 그대로 (pinvi-dagster는 _C6C_RUNTIME_IDENTIFIERS 밖)
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/ktdctl action pinvi-dagster stop --json'
#   pinvi-web·pinvi-api는 켜 둔다 (pair identity 보존 + run_ui_auth_smoke의 pinvi-web login shell GET)
#   ⚠️ **이것이 §2 박스의 loopback 창을 남기는 선택이다.** pinvi-api는 host-network이고
#      PINVI_KOR_TRAVEL_MAP_ADMIN_BASE_URL=http://127.0.0.1:12701 + ops cancel/read token을
#      갖고 있다. **더 강한 형태를 택하려면 여기서 함께 내린다**:
#        wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
#          ./.venv/bin/ktdctl action pinvi-api stop --json'
#      대가: step 9의 `run_ui_auth_smoke` pinvi-web login shell GET과 §15 11-3의
#      `_require_services_ready([… ,"pinvi-api"])`가 실패하므로 **11-6 이전에 되살려야 하고**,
#      그 recreate는 pair identity 무변화를 다시 증명해야 한다. 정지를 택하지 않으면
#      §16 H-6의 승인 항목(write 영구 소실 구간)을 그대로 받는다.

# 4-5 [W] 44건 pause — **sensor 10개 먼저, 그 다음 schedule 34개**. 10분 안에 끝내야 한다
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py pause \
  --snapshot /home/digitie/h35/run/enablement-baseline.json'              # DRY RUN
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py pause \
  --snapshot /home/digitie/h35/run/enablement-baseline.json --confirm'
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py verify \
  --snapshot /home/digitie/h35/run/enablement-baseline.json --target paused'

# 4-6 [W] map 4개 정지 — daemon → web → ui → api
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step4-stop --confirm'
#   compose_service.run(["stop", daemon, dagster, ui, api],
#       mutation_capability=_COMPATIBLE_PAIR_MUTATION_CAPABILITY, transaction=tx)
#   ← pinvi-api를 뺀 것만이 sanctioned deploy와 다르다
#     (`_activate_pair_sequentially`의 `["stop", _PINVI_API_SERVICE, *_MAP_RUNTIME_SERVICES]`,
#      `compose_service.py:3831`/`:3837`. 이전 판본의 `deploy:3826` 인용은 오프바이-몇이었다)

# 4-7 [R][S] fence 확정 게이트 (ss -tnp가 sudo 필요)
wsl ssh n150 'python3 /home/digitie/h35c/h35_fence_probe.py'
#   `--pgpass`는 생략한다. 생략 시 probe는 `-e PGPASSWORD`를 **값 없이 forward**하는 경로로
#   폴백하고, P4의 `local/127.0.0.1 trust` 때문에 실제로 접속된다. **호출자 환경에
#   `PGPASSWORD`가 설정돼 있으면 그 값이 컨테이너로 전달되므로**, 이 창에서는
#   `env | grep -c PGPASSWORD` → 0을 먼저 확인한다(형식 이탈을 산출물에 남기지 않기 위해)
wsl ssh n150 'env | grep -c "^PGPASSWORD=" || true'                    # 0이어야 한다
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
0건"과 직접 충돌한다. 게다가 **map API 쪽에는 sensor mutation이 없다** —
`packages/kor-travel-map-api/` 전체에서 `startSensor|stopSensor|resetSensor` **0 hit**이다.

> **인용 정정 (이전 판본은 "저장소 전체 0 hit"이라 적었고 그것은 거짓이다).** 저장소에는
> 이미 GraphQL sensor mutation을 직접 치는 **검증된 헬퍼**가 있다 —
> `packages/kor-travel-map-admin/frontend/e2e/live/_ops-c7-dagster-sensor.ts`
> (`:63 startSensor`, `:72 stopSensor(id:)`, `:83 resetSensor(sensorSelector:)` 외 5 hit).
> **결론은 그대로 유지된다** — map API `/ops`에 sensor 표면이 없으므로 직접 GraphQL이
> 유일하게 정합한 채널이다. 그리고 이 헬퍼는 `h35_instigation.py`의 **선례이자 대조
> 구현**이다: `stopSensor`는 id, `startSensor`/`resetSensor`는 selector를 받는다는 형태가
> 그대로 일치하므로, `h35_instigation.py` 작성 시 이 파일의 mutation 문자열을 정본으로 쓴다.
> (e2e 헬퍼 자체는 H35 window에 **실행하지 않는다** — live prod를 건드린다.)

### 8.3 직후 검증과 반증

| 검증 | 통과값 | 실패했다면 |
|---|---|---|
| 4-1 record | `schedules 37 (stored RUNNING 34 / STOPPED 3)`, `sensors 10 (stored RUNNING 3 / DECLARED_IN_CODE 7 / STOPPED 0)`, `effective_running_total 44`, `in_flight_runs 0` | 개수가 다르면 코드↔prod 불일치 → 복원 계획이 틀어진다 |
| 4-3b 외부 도달 | 모든 non-loopback 주소에서 **exit != 0** | 200이 오면 fence가 경로에 없다. 주소를 하나라도 빼먹으면 그 경로가 구멍이다 |
| 4-3b loopback | 200 | 실패면 L2 규칙이 loopback을 잘못 막았다 → smoke·H36 게이트가 전부 불가 |
| **4-3d L2b 음성통제** | `pg_isready -h 172.17.0.1` **exit != 0** | **exit 0 = bridge 컨테이너가 여전히 prod DB에 도달한다** → fence는 이 경로에 대해 존재하지 않는 것이다. **step 5로 가지 않는다.** 투입 **전** 실측이 rc=0(도달)이었으므로 이 게이트는 양성 대조가 이미 확보돼 있다 |
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
`map_owned_app_backends`면 정지 누락 컨테이너를 찾고, `unmapped_app_backends`면 소켓 소유자를
특정하지 못한 것(fail-close)이므로 **fence를 유지한 채 조사한다.** fence를 풀고 나중에 다시
거는 것은 dump 창을 다시 여는 것이므로 재측정으로 다시 시작해야 한다.

> ⛔ **`non_map_app_backends`는 실패 분기로 쓸 수 없다 (이전 판본의 존재하지 않는 분기).**
> `h35_fence_probe.py`는 그 값을 **계산해 보고하지만 `fatal` 13개
> (`app_write_xid_backends`, `app_open_tx_backends`, `map_owned_app_backends`,
> `unmapped_app_backends`, `ss_lines_without_pid`, `inflight_runs`, `backfills_in_flight`,
> `held_concurrency_slots`, `pending_steps`, `open_started_ticks`, `app_open_import_jobs`,
> `app_advisory_locks`, `app_schedule_claims`)에는 넣지 않는다**(n150 실물 확인). 즉
> `non_map_app_backends`가 0이 아니어도 verdict는 `FENCE_CLEAN`이다 — **정체불명 idle
> writer는 이 probe로 자동 판정되지 않는다.** 따라서 4-7의 판정은 `verdict`만 보지 말고
> **보고서의 `non_map_app_backends` 값을 사람이 눈으로 읽어 0인지 확인한다**(0이 아니면
> `verdict`와 무관하게 step 5로 가지 않는다). probe를 고칠 수 있으면 그 키를 `fatal`에
> 추가하는 것이 정본 해법이지만, 이 window에서는 도구를 바꾸지 않고 판정 절차로 닫는다.

---

## 9. step 5 — 백업·복원 gate (+ 5.5 리허설) `[W]`(scratch·파일) / prod는 `[R]`

**목적.** "SHA-256과 `pg_restore --list`만 확인하고 끝내지 않고" 격리 scratch에 **실제로
복원해** pre-migration head·핵심 schema/row count를 대조한다. 이 게이트를 통과한 dump만이
step 10의 복구 경로다.

**명령.**

```bash
# 5-0 [W] L5 인증 층 — dump 창 동안 신규 비-superuser 접속을 전부 거부한다 (superuser는 예외)
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -v ON_ERROR_STOP=1 \
  -f - < /home/digitie/h35/run/sql/connlimit-set0.sql'
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -A -F "|" \
  -f - < /home/digitie/h35/run/sql/connlimit-verify.sql'                       # 0 / 0
# 음성 통제: 반드시 실패해야 한다
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U krtour_map -d krtour_map -Atc "select 1"; \
  echo "exit=$?"'                       # exit != 0 ("too many connections for database")

# 5-1 [R→W] custom dump ×2 — owner/ACL 보존. `--no-owner`/`--no-privileges` 금지
#   ⛔ `--verbose`를 쓰지 않는다 — 진행 메시지가 stderr로 나가 `.err` 게이트를 무의미하게
#      만든다(실측: 단일 테이블 schema-only도 stderr 80줄. 22 GB면 수천 줄).
#      step 8-2가 이미 `--verbose` 없이 같은 형태다 — 두 절을 여기서 통일한다.
wsl ssh n150 'umask 077; mkdir -p /home/digitie/h35/run/bk0063; chmod 700 /home/digitie/h35/run/bk0063'
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -A -F "|" \
  -f - < /home/digitie/h35/run/sql/statdb.sql > /home/digitie/h35/run/bk0063/statdb-pre.tsv'
wsl ssh n150 'docker exec kor-travel-geo-postgres pg_dump -U addr -d krtour_map \
  --format=custom --compress=6 --no-tablespaces --lock-wait-timeout=30s \
  > /home/digitie/h35/run/bk0063/krtour_map.dump 2> /home/digitie/h35/run/bk0063/krtour_map.err'
wsl ssh n150 'docker exec kor-travel-geo-postgres pg_dump -U addr -d krtour_map_dagster \
  --format=custom --compress=6 --no-tablespaces --lock-wait-timeout=30s \
  > /home/digitie/h35/run/bk0063/krtour_map_dagster.dump 2> /home/digitie/h35/run/bk0063/krtour_map_dagster.err'
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -A -F "|" \
  -f - < /home/digitie/h35/run/sql/statdb.sql > /home/digitie/h35/run/bk0063/statdb-post.tsv'
# .err 판정 — 0 바이트가 기대값이고, 그렇지 않으면 치명 문자열 0건이어야 한다
wsl ssh n150 'cd /home/digitie/h35/run/bk0063 && wc -c krtour_map.err krtour_map_dagster.err && \
  grep -cE "pg_dump: error|FATAL|PANIC" krtour_map.err krtour_map_dagster.err'   # 0 0 / 0 0
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
#   scratch.env / initdb/01-roles-dbs.sql은 §3.6 0′-3이 이미 만들었다 (mode 600)
#   ⛔ `pg_restore`는 `psql`과 달리 **bare 인자를 conninfo로 받지 않는다** — 첫 비옵션 인자를
#      입력 아카이브로 해석하므로 `-d`가 없으면 파일 인자가 2개가 되어
#      `pg_restore: error: too many command-line arguments`로 즉사한다(실측).
#      같은 문서 10-3은 `-d`를 올바로 쓴다 — 이전 판본은 5-2만 형식이 틀렸다
wsl ssh n150 'docker run --rm --network h35-scratch -u "$(id -u):$(id -g)" \
  -v /home/digitie/h35/run/secrets:/pgconf:ro -v /home/digitie/h35/run/bk0063:/bk:ro \
  -e PGSERVICEFILE=/pgconf/pg_service.conf -e PGPASSFILE=/pgconf/pgpass -e HOME=/tmp \
  postgres:16 pg_restore -d "service=ktm-scratch-app" -j 4 --exit-on-error \
  --no-tablespaces --verbose /bk/krtour_map.dump'
#   dagster DB 동일(`-d "service=ktm-scratch-dagster"`) → 이후 vacuumdb --analyze-in-stages
#   (여기서는 `--verbose`를 남긴다 — 복원 진행 로그는 판정 기준이 아니라 사람이 읽는 용도다)

# 5-3 [R] 동일성 대조
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F "|" \
  -f - < /home/digitie/h35/run/bin/h35-identity-52.sql > /home/digitie/h35/run/identity-prod-0063.txt'
wsl ssh n150 'docker run --rm --network h35-scratch -u "$(id -u):$(id -g)" \
  -v /home/digitie/h35/run/secrets:/pgconf:ro -v /home/digitie/h35/run/bin:/work:ro \
  -e PGSERVICEFILE=/pgconf/pg_service.conf -e PGPASSFILE=/pgconf/pgpass -e HOME=/tmp \
  postgres:16 psql -d "service=ktm-scratch-app" \
  -X -q -A -F "|" -f /work/h35-identity-52.sql > /home/digitie/h35/run/identity-scratch-0063.txt'
wsl ssh n150 'diff -u /home/digitie/h35/run/identity-prod-0063.txt \
  /home/digitie/h35/run/identity-scratch-0063.txt; echo "diff_exit=$?"'

# 5.5 [W] **필수** candidate migration 리허설 — 기본 entrypoint/CMD 미기동
#   기동 **전에** env 음성 검사를 게이트로 돌린다 (`--env-file` 모드 판정 기준은 §3.3)
wsl ssh n150 'python3 /home/digitie/h35/run/bin/h35_env_negcheck.py \
  --env-file /home/digitie/h35/run/secrets/scratch-api.env'
#   ⛔ `time`을 쓰지 않는다 — API 이미지의 `/bin/sh`는 **dash**이고 `time` 키워드도
#      `/usr/bin/time` 패키지도 없다(실측: `sh: 1: time: not found`, exit 127).
#      소요 시간은 `date +%s` 전후로 직접 잰다. 5.5는 H-5의 유일한 리허설이므로
#      이 한 단어가 비가역 지점의 사전 게이트를 통째로 무효화했었다
wsl ssh n150 "docker run --rm --network h35-scratch \
  --env-file /home/digitie/h35/run/secrets/scratch-api.env \
  --entrypoint sh $CAND_API -c 'cd /app && \
    S=\$(date +%s) && alembic upgrade head; RC=\$?; E=\$(date +%s); \
    echo \"rehearsal_rc=\$RC elapsed_s=\$((E-S))\"; exit \$RC'"
#   출력 예: rehearsal_rc=0 elapsed_s=417  ← 이 값이 §17-3 outage 창 산정의 유일한 실측 근거다
#   (파이프를 걸지 않는다 — exit code가 가려진다. 출력은 그대로 읽어 산출물에 옮겨 적는다)
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
| `*.err` | 두 파일 **0 바이트**(`--verbose` 없음 → 정상 성공에서 실제로 0이다). 0이 아니면 **`pg_dump: error`/`FATAL`/`PANIC` 매칭 0건**이어야 진행 가능하고 내용을 산출물에 남긴다. dump 선두 5바이트 `PGDMP` | 치명 문자열이 1건이라도 있으면 dump가 깨끗하지 않다 → 복구점 자격 없음. **step 8-2와 동일 기준이다** |
| TOC | `TABLE DATA` **52건** + `EXTENSION` 5 + `SEQUENCE SET` 6, `Dumped from 16.9` | 개수 부족 = content-incomplete |
| 파일 권한 | `digitie:digitie` mode 600 | root:root/644면 `umask`·`-u`가 적용되지 않았다(기존 dump의 실제 결함) |
| `statdb` delta | `tup_inserted/updated/deleted` **전부 0**(`xact_commit`만 증가 — read-only 세션) | 0이 아님 = **fence에 구멍** → 복구점 자격 없음 |
| `--lock-wait-timeout=30s` | 타임아웃 없이 완료 | 타임아웃 = 예기치 않은 writer 뒤 대기 → **fail-fast**(무한 대기가 아니다) |
| 5-3 `diff_exit` | **0** | ≠0 = 복원 불충실 |
| scratch head | app `0063_pipeline_root_id` / dagster `29b539ebc72a` | 다르면 dump가 잘못됐다 |
| Dagster instance identity | `instance_info.run_storage_id = cb6ccdf7-3794-4199-826b-9c6de7327b2d` | Dagster DB 동일성의 최강 marker |
| 구조 md5 3종 | `index_defs c017d4cc66bc040af67d3b7f711a1bb6`(210) / `constraint_defs 2d7ca59420eb0573a5923588a2e3fd38`(291) / `column_defs a55e089dbf855e9c1df309454c5e9e83` | 불일치 = 스키마 유실 |
| owner/ACL | 테이블 owner `krtour_map` 55 / `addr` 2, 스키마 ACL `{addr=UC/addr, krtour_map=UC/addr}`(`public`은 `krtour_map=UC/pg_database_owner`) | 불일치 = `--no-owner` 계열 오염 |
| 5.5 env 음성 검사 | `h35_env_negcheck.py --env-file` 통과 (§3.3의 `--env-file` 판정 기준) | 위반 = **candidate alembic이 prod DB에 붙는다.** 이 게이트가 5.5의 유일한 방어다 |
| 5.5 리허설 | `rehearsal_rc=0` + scratch head `0068_integrity_last_seen` + `h35-structural-gate.sql` post 열 전부 일치 + **`elapsed_s` 기록** | 실패 = prod에서 같은 실패가 난다. **여기서 잡는 것이 step 6에서 잡는 것보다 무한히 싸다** |

**5.5를 필수로 두는 이유.** 이것이 없으면 **0064~0068이 22 GB 실데이터에 처음 도는 곳이
prod**다. step 6은 (a) 첫 실행, (b) 중간에 비가역 0065/0066, (c) 실패 시
`unless-stopped`로 무한 재시도를 한꺼번에 맞는다. 5.5는 디스크
추가 소요 0(step 8이 어차피 같은 scratch를 reset한다)에 **prod 실행을 두 번째로 만들고
step 6 예산의 실측 근거를 준다.** 5.5는 step 2의 금지를 어기지 않는다 — 금지 대상은
**candidate 기본 entrypoint/CMD**이고 여기서는 `--entrypoint sh -c '…'`로 대체하며,
fence 확정(4-7)과 verified dump(5-3) **이후**에 **scratch에만** 붙인다.

> **그러나 5.5는 이 절차에서 `alembic upgrade head`가 처음 발화하는 지점이다.** §16이
> step 6을 "첫 비가역"으로 적은 것은 **prod 기준**이고, 5.5는 scratch 기준의 첫 실행이다.
> 대상이 scratch DB뿐이라 prod에는 비가역이 아니지만, **주입 env가 잘못되면 그 순간
> prod가 대상이 된다.** 그래서 §16에 **H-5a**를 신설해 (a) `h35_env_negcheck.py --env-file`
> 통과, (b) `--network h35-scratch` 단독, (c) `scratch-api.env`에 prod DSN·지문 부재를
> 승인 전제로 올렸다. 이 시점 L5(`CONNECTION LIMIT 0`)가 아직 유효해 비-superuser prod
> 접속이 막히는 것은 **부수적 보호일 뿐 설계된 방어가 아니다**(superuser `addr`는
> `datconnlimit` 예외다) — 방어는 (a)~(c)다.

**쓰지 않는 기준.** sha256 + `pg_restore --list`만 — task 명시 거부.
`scripts/docker-backup.sh` — prod에 존재하지 않는 standalone `postgres` service를
하드코딩(`:85,:117`)하고 `--no-owner`(`:121`) `--no-privileges`(`:122`)로 스키마 USAGE/CREATE
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

**목적.** fence 안에서 `docker/api-entrypoint.sh:216`의 `while ! alembic upgrade head`가
0064~0068을 forward 적용하게 한다. **여기가 prod 기준 첫 비가역 지점이다**(§16 H-4/H-5).

**명령.**

```bash
# 6-0 [W] L5 원복 — candidate API가 krtour_map으로 접속해야 한다
#   ⛔ 이 순간부터 step 11-6까지 on-box loopback writer를 막는 층이 없다(§2 박스, §16 H-6)
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -v ON_ERROR_STOP=1 \
  -f - < /home/digitie/h35/run/sql/connlimit-reset.sql'
# 6-0b [R] 우리 자신의 세션을 모두 닫는다 — 0064/0068이 CREATE INDEX CONCURRENTLY를 쓴다
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -A -F "|" \
  -f - < /home/digitie/h35/run/sql/sessions-app.sql'                   # 0행이어야 한다

# 6-1 [W] ⛔ recreate — wait=False (120초 상한을 타지 않는다)
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step6 --confirm'
```

```python
env = hybrid_env({api: cand.map_image_id,                     # ← API만 candidate
                  ui:  m.active.map_ui_image_id,
                  dagster: m.active.map_dagster_image_id,
                  daemon:  m.active.map_dagster_daemon_image_id},
                 cand.map_source_revision, m.active.pinvi_image_id, m.active.pinvi_source_revision)
ok, res = up_stage(cfg, tx, "h35_map_api", [_MAP_API_SERVICE], env)   # ← 정의는 §3.2
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
#   ⛔ **발동 조건은 시간이 아니라 `RestartCount` 증가다** (아래 박스). 오래 걸린다는
#      이유만으로 발동하면 autocommit 구간 한복판에서 스스로 부분 상태를 만든다
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py stop-api --confirm'
wsl ssh n150 'docker logs --tail 400 kor-travel-map-api-latest > /home/digitie/h35/run/step6-fail.log'
# 6-F2 [R] partial-state probe
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -A -F "|" \
  -f - < /home/digitie/h35/run/bin/partial-state.sql > /home/digitie/h35/run/gate-partial.txt'
# 6-F3 [W] **같은 image·같은 command로 재개**
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step6 --confirm'
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

> ### ⛔ 마이그레이션 1회 시도에는 **시간 상한이 없다** (이전 판본의 사실 오류를 삭제·정정)
>
> 이전 판본은 "컨테이너 1회 기동당 예산은 30회×2초 = 60초이고, 그 안에 끝나지 않는 DDL은
> 재시작 경계를 넘는다"고 적었다. **거짓이다.** `docker/api-entrypoint.sh:212-224` 실측:
>
> ```sh
> retries="${KOR_TRAVEL_MAP_MIGRATION_RETRIES:-30}"          # :212
> sleep_seconds="${KOR_TRAVEL_MAP_MIGRATION_RETRY_SLEEP_SECONDS:-2}"   # :213
> attempt=1                                                   # :214
> while ! alembic upgrade head; do                            # :216
>   if [ "$attempt" -ge "$retries" ]; then … exit 1; fi
>   attempt=$((attempt + 1)); sleep "$sleep_seconds"
> done
> ```
>
> 재시도는 **`alembic upgrade head`가 실패해 종료했을 때만** 일어난다. `30`은 **실패
> 횟수**이고 `2`는 실패 사이 sleep일 뿐이다 — **40분 도는 upgrade도 아무도 끊지 않는다.**
> 벽시계 60초도, 재시작 경계도 없다.
>
> **왜 이 정정이 안전에 직결되는가.** 틀린 모델을 믿으면 운영자가 "60초를 넘겼다"를 근거로
> **6-F1(stop-api)을 조기 발동**하고, 그 순간이 0064/0068의 `autocommit_block()` 한복판이면
> **스스로 부분 상태를 만든다.** 6-F1의 발동 조건은 **오직 `RestartCount` 증가**(= entrypoint가
> 실제로 `exit 1` 후 `unless-stopped`로 재기동해 무한 반복에 들어간 상태)이거나 사람이
> `docker logs`에서 확정한 영구 실패다. **소요 시간은 발동 조건이 아니다** — 6-2 폴링으로
> `alembic_version`이 전진하는지만 본다.
>
> (`KOR_TRAVEL_MAP_MIGRATION_RETRIES`/`…_RETRY_SLEEP_SECONDS`가 **배포 compose에 0 hit**이라
> prod에서 조정 불가한 것은 사실이고 그대로 유지한다. 그리고 `wait=False`의 근거는
> `_run_up_stage`의 하드코딩 `--wait --wait-timeout 120`(`compose_service.py:3540`)
> **하나로 충분하다** — 위 예산 모델은 애초에 필요 없었다.)

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
| G02 `ops.data_integrity_violations.last_seen_at` | **ABSENT** | **`NO/now()`** — 게이트 SQL이 내는 것은 `is_nullable \|\| '/' \|\| coalesce(column_default,'NULL')` **뿐**이므로 통과값도 그 형식으로만 쓴다. (이전 판본이 함께 요구한 `timestamptz`·"NULL 행 0"은 **이 SQL이 산출하지 않는다** — 타입은 G02b, NULL 행 수는 G11의 `ck_…_last_seen_not_null` validated 여부로 각각 본다) | 직접 |
| G02b `last_seen_at` 타입·NULL 행 (**보조, 별도 명령**) | ABSENT | `timestamptz` + NULL 행 **0**. 아래 8-0b 인라인 SQL로 측정 | 직접 |
| G03 `uq_violations_open_dedupe_key` | **ABSENT** | 존재 + valid, pred `((status = ANY (…)) AND (payload ? 'dedupe_key'))` | 직접 |
| G04 `curation_items` unique 표면 | `curation_items_pkey`, `uq_curation_items_active_identity` | **`curation_items_pkey` + `uq_curation_items_component_identity` + `uq_curation_items_active_source_feature` + `uq_curation_items_legacy_projection_id` 4개.** `uq_curation_items_active_identity`(0063)와 `uq_curation_items_identity`(0065 중간산물) **둘 다 없어야 한다** | 직접 |
| G05 `curation_items` 신규 컬럼 | NONE | `external_component_id:NO`, `legacy_projection_id:YES`, `operator_updated_at:YES`, `operator_updated_by:YES`, `source_present:NO`, `source_updated_at:NO` | 직접 |
| G06/G07 price index | `idx_price_values_feature_product_observed` valid | `idx_price_values_feature_observed_identity`만, indexdef `(feature_id, observed_at DESC, provider, price_domain, product_key)` | 직접 |
| G08 invalid index | NONE | NONE | **부분적용 탐지 전용** |
| G09 unvalidated constraint | NONE | NONE | 동일 |
| G10 잔재 인덱스 | `ops.uq_enrichment_review_candidate` **존재**(무관) | **`ops.uq_enrichment_review_candidate` 정확히 1건만** — 즉 pre와 문자 단위 동일. 이 SQL의 술어는 `%\_ccnew%`/`%\_ccold%`/`%candidate%` **셋뿐**이고 `ops.uq_enrichment_review_candidate`가 세 번째에 항상 걸리므로 "0건"은 원리적으로 불가능하다. **"0068이 명시 DROP하는 이름 0건"은 이 SQL에 없는 축이므로 G12로 본다** | 동일 |
| G11 violations constraint | `fk_…_feature_id_features` `confdeltype='c'` | 같은 이름 `confdeltype='n'`(SET NULL) + validated. `fk_…_feature_id_set_null`·`ck_…_last_seen_not_null` **부재**(RENAME/DROP됨) | 직접 |
| G12 violations index | **8개** — `idx_violations_{detected_brin,feature,feature_detected,provider_status_detected,source_record,status_detected,type_status}` + `pk_data_integrity_violations` | **9개** = `…_seen` 3개 + 나머지 5 + **`uq_violations_open_dedupe_key`**, `…_detected` 3개 **부재**, 전부 valid | 직접 |
| G13 `curation_items` trigger/check | NONE | `ck_curation_items_external_component_id_canonical`(validated) + `trg_curation_items_legacy_component_identity` + `fk_curation_items_legacy_projection_id_curated_features`(deferrable, deferred) | 직접 |
| G14 row counts | `collections=71 items=3530 curated=3044 violations=3` | **전부 불변** | 직접(0065 DELETE 0행 주장의 반증 지점) |
| **G15 migrated_from collections** | **`migrated_from=52 legacy_key=52`** (2026-07-30 실측) | **`migrated_from=52 legacy_key=52` — 불변** | **직접. 런북이 반복 주장하는 "52행"의 범위를 직접 재는 유일한 축이다.** 0065는 그 52행의 `collection_key` **형식만** 바꾸고(K01: 0→52) 집합의 크기와 `metadata.migrated_from`은 건드리지 않는다. 값이 52를 벗어나면 0065가 의도보다 넓게/좁게 발화한 것이다 |
| G16 concierge identity | `entities=1020 linked_features=1020 max_last_seen=2026-07-14 12:32:51Z` | **불변** | 직접(H35는 materialize 안 함) |
| K01 0065 UUID key shape | **0** | **52** (`^legacy:<uuid>:<uuid>:[0-9a-f]{32}$`) | 직접 |
| **K02 legacy prefix total** | **52** | **52 — 불변** (0065의 새 key도 `legacy:`로 시작한다) | 직접. K01과 짝을 이뤄 "형식만 바뀌고 집합은 그대로"를 고정한다 |
| K03 key part census | `2parts=3 3parts=68` | `2parts=3 3parts=16 4parts=52` | 직접 |
| **K04 quarantine shape** | **0** | **0** | 0065가 쓰는 `legacy:quarantine:<uuid>…` **staging namespace의 잔여 0건**. >0 = migration이 중간 상태로 멈췄다 |
| **K05 split/conflict suffix** | **0** | **0** | 0065는 `collection_key` 충돌 시에만 `:split:legacy` / `:conflict:<n>`을 붙인다. >0이면 **K01=52가 성립할 수 없다**(그 행은 strict UUID shape를 벗어난다) — K01·K02와 상호 검증된다 |
| **K06 null/blank title** | **0** | **0** | 0065/0066이 title을 건드리지 않는다는 주장의 반증 지점 |
| **K07 active identity 술어** | **`(archived_at IS NULL)`** | **`ABSENT`** | 직접. 0065가 `uq_curation_items_active_identity`를 drop하므로 술어 조회가 ABSENT여야 한다 — G04와 독립인 두 번째 축 |
| **K08 archived items** | **0** | **0** | 0065의 `DELETE FROM feature.curation_items`가 **0행**이라는 주장의 전제(=tombstone 부재)를 직접 잰다 |
| **K09 archived curated** | **0** | **0** | 동일 |
| G17/G18 소형 md5 | `curation_items 6c399ae4…` / `collections 7fa901ee…` | **변경**(0065/0066 UPDATE) | 직접 |
| **G19 violations md5** | `14d23812…` | **⚠️ 변경 — 그것이 정상이다.** 아래 박스 | **행 전체 해시라 판별력이 약하다. 방향(변경)만 본다** |
| **G19b status/payload md5 (신설, 별도 명령)** | **`5c16deff…`** (2026-07-30 실측) | **불변** | **직접. "0068의 두 번째 UPDATE가 0행"이라는 주장의 유일한 반증 축이다** |
| G20 open import_jobs | `aed9818b…:running:c6c_cancel_probe` | 동일 1건 | fence 예외 |
| 유령 override | `ops.dagster_schedule_overrides`에 `feature_notice_krex_traffic_notices_monthly_schedule`(cron `7 * * * *`) 1건, 실제 schedule 이름과 불일치 = 무효 | **매칭 0건 유지** | main으로 올릴 때 이름이 바뀌면 조용히 활성화된다 |

> ### ⛔ G19 통과값을 "불변"에서 **"변경(예상)"** 으로 뒤집는다 — 그리고 G19b를 신설한다
>
> 이전 판본의 G19 통과값 "**불변**"은 **0068이 성공하면 반드시 거짓이 된다.** 게이트 SQL
> 실물은 `md5(string_agg(t::text, E'\n' ORDER BY t::text))` = **행 전체(`t::text`) 해시**인데,
> `0068_integrity_last_seen.py`가 같은 테이블에
> `ADD COLUMN IF NOT EXISTS last_seen_at timestamptz` + `SET DEFAULT now()`를 하고
> `UPDATE … SET last_seen_at = detected_at WHERE last_seen_at IS NULL`로 **prod 3행 전부**를
> 채운다. **컬럼이 하나 늘면 모든 행의 `t::text`가 넓어지므로 md5는 반드시 변한다.**
> 이전 판본의 근거("0068의 UPDATE는 `LIKE 'address_validation:%'` 0행")는 **두 번째** UPDATE만
> 해명하고 `ADD COLUMN`과 **첫 번째** UPDATE를 빠뜨렸다. 성공했을 때 실패를 보고하는
> 게이트였고, 이것은 §11이 스스로 열거한 "정상 배포에서도 실패하는 기준"의 정확한 예다.
>
> **그래서 축을 둘로 나눈다.**
>
> - **G19**(기존 SQL 그대로) → 통과값 **"변경"**. `14d23812…`와 **같으면 오히려 실패**다
>   (컬럼이 안 붙었다는 뜻). 방향만 보는 약한 축이다.
> - **G19b**(신설) → `issue_id|status|resolved_at|payload` 투영의 md5. **0068의 두 번째
>   UPDATE(`status='resolved'`, `resolved_at`, `payload ||= dedupe_key_migration`)가 건드리는
>   컬럼만** 담고 `last_seen_at`은 담지 않는다. 그 UPDATE가 0행이면 **불변**이고, 1행이라도
>   맞으면 반드시 변한다 — **"0행"이라는 주장의 유일한 반증 축이다.**
>   pre 실측 = **`5c16deff…`**(2026-07-30). SQL은 §3.6이 만든
>   `$H35/sql/violations-status-payload-md5.sql`이고 pre는 step 1-3에서, post는 여기서 잰다.
>
> ```bash
> # G19b/G02b — 구조 게이트 파일 밖의 보조 축 2개. pre는 1-3, post는 여기
> wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F "|" \
>   -f - < /home/digitie/h35/run/sql/violations-status-payload-md5.sql \
>   >> /home/digitie/h35/run/gate-post.txt'
> wsl ssh n150 "docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F '|' -f -" <<'SQL'
> SELECT 'G02b_last_seen_type_and_nulls' AS gate,
>        coalesce((SELECT data_type FROM information_schema.columns
>                   WHERE table_schema='ops' AND table_name='data_integrity_violations'
>                     AND column_name='last_seen_at'), 'ABSENT')
>        || ' nulls=' || (SELECT count(*) FROM ops.data_integrity_violations
>                          WHERE last_seen_at IS NULL)::text AS value;
> SQL
> #   post 통과값: `timestamp with time zone nulls=0`
> ```

**`diff -u gate-pre.txt gate-post.txt`의 판정 기준 (이전 판본은 정의하지 않았다).**
`diff`는 사람이 읽는 형태이고 **자동 assert가 아니다.** 판정은 이렇게 한다 —
**위 표의 모든 행이 표에 적힌 방향과 정확히 일치해야 하고, 표에 없는 라벨이 출력에
나타나면 그 자체가 실패다.** 게이트 파일이 내는 라벨은 `h35-structural-gate.sql`의
**G01~G20 20개**와 `h35d_key.sql`의 **K01~K09 9개** = **총 29개**이고, 위 표는 이제 그
29개를 **전부** 덮는다(이전 판본은 G15와 K02·K04~K09 **8개가 누락**돼 있었고, `diff`가
그 8행을 출력해도 무엇을 통과로 볼지 정의되지 않았다). **불변이어야 하는 행 14개**는
G08·G09·G10·G14·G15·G16·G20·K02·K04·K05·K06·K08·K09,
**변경되어야 하는 행 16개**는 G01·G02·G03·G04·G05·G06·G07·G11·G12·G13·G17·G18·G19·K01·K03·K07이다.
게이트 파일 **밖**의 보조 축 2개(**G02b 변경 / G19b 불변**)는 `diff` 대상이 아니라 위
인라인 명령으로 따로 잰다 — `gate-pre.txt`/`gate-post.txt`에 append하므로 `diff`에도
나타나지만, 판정은 이 문단의 방향으로 한다.

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
| 3행의 `candidates` | 비어 있지 않음 | 리졸버가 죽으면 빈 배열 | **전제 게이트.** 아래 |

> ⛔ **`candidates`가 빈 행은 이 표의 판정 대상에서 제외한다.** 후보가 0건이면
> `curations.py:674-689`가 신·구 이미지 **양쪽에서** `unmatched`를 내고
> `name_only_match`(`:574`)도 방출되지 않아 **두 강판별자가 동시에 부재한다** — 그 상태를
> "이미지가 H36을 담고 있지 않다"로 읽으면 거짓 결론이다. **3-5가 pre에서 이미 3행 모두
> 후보 ≥ 1건임을 확인했어야 하고**(§7 3-5 통과 조건), 여기서 다시 확인한다. 세 행 모두
> 후보 0건이면 H36 실효 판정은 **이 게이트로 할 수 없으므로** step 3-1의 content 축
> (`H36_CODE`/`H36_STATUS`/`GUARD`)으로 판정하고 그 사실을 산출물에 기록한다.

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
# 8-1 [W] ⚠️ **prod** candidate API 재정지 → writer 0건 재확인 (이 줄만 prod 변경이다)
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py stop-api --confirm'
wsl ssh n150 'python3 /home/digitie/h35c/h35_fence_probe.py'          # FENCE_CLEAN
#   ⛔ verdict만 보지 않는다 — 보고서의 `non_map_app_backends`도 **0인지 눈으로 읽는다**(§8.3)

# 8-2 [W] 0068 immutable dump bundle (§9 5-1과 같은 형태, 새 디렉터리. `--verbose` 없음)
wsl ssh n150 'umask 077; mkdir -p /home/digitie/h35/run/bk0068; chmod 700 /home/digitie/h35/run/bk0068'
wsl ssh n150 'docker exec kor-travel-geo-postgres pg_dump -U addr -d krtour_map \
  --format=custom --compress=6 --no-tablespaces --lock-wait-timeout=30s \
  > /home/digitie/h35/run/bk0068/krtour_map.dump 2> /home/digitie/h35/run/bk0068/krtour_map.err'
#   dagster DB 동일 → pg_restore --list → SHA256SUMS → chmod 600

# 8-2b [R] ★ **prod 0068 identity 채취** — 8-4의 대조 상대. 이전 판본에는 이 명령이 없었다
#   (step 5에는 identity-prod-0063.txt가 있는데 0068 쪽 짝이 없어 "대조"가 성립 불가였다)
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map -X -q -A -F "|" \
  -f - < /home/digitie/h35/run/bin/h35-identity-52.sql \
  > /home/digitie/h35/run/identity-prod-0068.txt'

# 8-3 [R] concierge changes 전량 수집 — cursor 없이 시작해 끝까지 한 번
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35_changes_collect.py \
  --base-url http://127.0.0.1:12601 --limit 500 \
  --out /home/digitie/h35/run/concierge-changes.json'

# 8-4 [W] ★ scratch reset → 0068 dump 복원 → identity 대조 (별도 clone 만들지 않는다)
#   (a) 같은 scratch pair를 **비운다** — 새 volume/network를 만들지 않는다(디스크 제약, 아래)
wsl ssh n150 'docker rm -f h35-scratch-pg'
wsl ssh n150 'docker volume rm h35-scratch-pgdata && docker volume create h35-scratch-pgdata'
wsl ssh n150 'docker run -d --name h35-scratch-pg --network h35-scratch \
  -v h35-scratch-pgdata:/var/lib/postgresql/data \
  -v /home/digitie/h35/run/secrets/initdb:/docker-entrypoint-initdb.d:ro \
  --env-file /home/digitie/h35/run/secrets/scratch.env \
  postgis/postgis:16-3.5 \
  -c shared_preload_libraries=pg_stat_statements \
  -c shared_buffers=1GB -c maintenance_work_mem=1GB -c max_wal_size=4GB'
wsl ssh n150 'until docker exec h35-scratch-pg pg_isready -U addr -q; do sleep 2; done; echo scratch_ready'
#   (b) 0068 bundle을 복원한다 — `-d` 필수(5-2와 같은 형식)
wsl ssh n150 'docker run --rm --network h35-scratch -u "$(id -u):$(id -g)" \
  -v /home/digitie/h35/run/secrets:/pgconf:ro -v /home/digitie/h35/run/bk0068:/bk:ro \
  -e PGSERVICEFILE=/pgconf/pg_service.conf -e PGPASSFILE=/pgconf/pgpass -e HOME=/tmp \
  postgres:16 pg_restore -d "service=ktm-scratch-app" -j 4 --exit-on-error \
  --no-tablespaces --verbose /bk/krtour_map.dump'
#   dagster DB 동일(`-d "service=ktm-scratch-dagster"`)
#   (c) identity 대조 — 8-2b의 prod 0068 대 scratch 0068
wsl ssh n150 'docker run --rm --network h35-scratch -u "$(id -u):$(id -g)" \
  -v /home/digitie/h35/run/secrets:/pgconf:ro -v /home/digitie/h35/run/bin:/work:ro \
  -e PGSERVICEFILE=/pgconf/pg_service.conf -e PGPASSFILE=/pgconf/pgpass -e HOME=/tmp \
  postgres:16 psql -d "service=ktm-scratch-app" -X -q -A -F "|" \
  -f /work/h35-identity-52.sql > /home/digitie/h35/run/identity-scratch-0068.txt'
wsl ssh n150 'diff -u /home/digitie/h35/run/identity-prod-0068.txt \
  /home/digitie/h35/run/identity-scratch-0068.txt; echo "diff0068_exit=$?"'   # 0이어야 한다

# 8-5 [W] candidate Dagster daemon을 scratch pair에만 붙여 실제 기동
#   ★ 순서가 뒤집혔다 — **scoped reject를 먼저 얹고, 도달 불가를 확인한 뒤에** 기동한다
SUB=$(wsl ssh n150 'docker network inspect h35-scratch -f "{{(index .IPAM.Config 0).Subnet}}"')
wsl ssh n150 "sudo -n iptables -C H35FENCE -s $SUB -p tcp --dport 5432 -j REJECT --reject-with tcp-reset \
  || sudo -n iptables -I H35FENCE 1 -s $SUB -p tcp --dport 5432 -j REJECT --reject-with tcp-reset"
wsl ssh n150 'python3 /home/digitie/h35/run/bin/h35_env_negcheck.py \
  --env-file /home/digitie/h35/run/secrets/scratch-daemon.env'         # 기동 **전** 게이트
#   $CAND_DAEMON은 3-0에서 채취했다 (`.map_dagster_daemon_image_id`). 빈 문자열이면 3-0으로
#   돌아간다 — 이전 판본은 이 변수의 대입이 문서 어디에도 없어 `-c`가 이미지로 파싱됐다
wsl ssh n150 "docker run -d --name h35-scratch-daemon --network h35-scratch \
  --env-file /home/digitie/h35/run/secrets/scratch-daemon.env $CAND_DAEMON"
```

> **scratch daemon이 "pause·pending/running run 0" 상태에서 뜨는 근거 (task step 8의 조건절 —
> 이전 판본은 이 의존을 한 번도 진술하지 않았다).** 8-4가 복원하는 것은 **8-2의 0068
> dump**이고, 그 dump는 **4-5에서 44건을 pause한 뒤·fence 안에서** 떠졌다. 따라서 scratch
> Dagster DB의 `instigators`/`job_ticks`/`runs`는 **pause된 상태 그대로**이고 in-flight run이
> 0이다(4-7 `FENCE_CLEAN`의 `inflight_runs`·`pending_steps`·`open_started_ticks`가 그것을
> 이미 게이트했다). **이 의존은 순서에 걸려 있다** — 8-4가 다른 시점 dump로 reset되거나
> 8-2보다 먼저 실행되면 scratch daemon이 schedule을 발화시켜 H30B에 넘길 clean identity를
> 스스로 오염시킨다. **8-2 → 8-4 순서를 바꾸지 않는다.**

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

**격리 증명 — 판별력 있는 음성통제.** ⛔ **순서가 중요하다: reject를 먼저 얹고, 그 다음
(2)가 실패함을 확인해야 통과다.** 이전 판본은 "(2)를 돌려 도달하면 reject를 얹는다"였는데,
**bridge→gateway 도달은 이미 실측으로 확정됐으므로**(§8.1 L2b 박스) 그 순서에서는 (2)가
반드시 "도달"을 보고하고 게이트가 아니라 경고에 그친다.

```bash
# (0) ★ 선행 — scratch subnet에도 scoped reject를 얹는다 (8-5에서 이미 투입했다면 확인만)
SUB=$(wsl ssh n150 'docker network inspect h35-scratch -f "{{(index .IPAM.Config 0).Subnet}}"')
wsl ssh n150 "sudo -n iptables -C H35FENCE -s $SUB -p tcp --dport 5432 -j REJECT --reject-with tcp-reset \
  || sudo -n iptables -I H35FENCE 1 -s $SUB -p tcp --dport 5432 -j REJECT --reject-with tcp-reset"
wsl ssh n150 'sudo -n iptables -S H35FENCE'     # 규칙 순서를 눈으로 확인 — reject가 RETURN보다 앞

# (1) network 열거 — h35-scratch 단독
wsl ssh n150 'docker inspect h35-scratch-daemon --format "{{json .NetworkSettings.Networks}}"'

# (2) ★ 실제 위험 경로: docker gateway IP를 통한 호스트 0.0.0.0:5432 도달
#     (0) **이후**에 돌린다. 통과값은 "도달 불가"다
GW=$(wsl ssh n150 'docker network inspect h35-scratch -f "{{(index .IPAM.Config 0).Gateway}}"')
wsl ssh n150 "docker run --rm --network h35-scratch postgres:16 \
  pg_isready -h $GW -p 5432 -t 6; echo exit=\$?"                  # **exit != 0 이어야 한다**

# (3) 대조군 — 같은 network에서 scratch 서버에는 반드시 닿아야 한다
wsl ssh n150 'docker run --rm --network h35-scratch postgres:16 \
  pg_isready -h h35-scratch-pg -p 5432 -t 6; echo exit=$?'        # **exit 0 이어야 한다**

# (4) env 지문 음성 검사
wsl ssh n150 'docker inspect h35-scratch-daemon --format "{{range .Config.Env}}{{println .}}{{end}}" \
  | python3 /home/digitie/h35/run/bin/h35_env_negcheck.py --stdin'
#   어떤 값의 sha256[:8]도 67c3f5db(prod DB password 지문)와 같지 않고
#   어떤 값도 '127.0.0.1:5432'를 포함하지 않는다 → 위반 시 exit 1
```

> **왜 `127.0.0.1:5432` 프로브를 통과 기준으로 쓰지 않는가.** bridge 컨테이너에서
> `127.0.0.1`은 **자기 loopback**이므로 5432에 아무것도 없어 **격리가 깨져 있어도 항상
> 실패한다** — 도달 가능한 경로를 검사하지 않는 **비-증명**이다. 실제 위험 경로는
> **docker gateway IP**이고, prod DB는 `kor-travel-geo-postgres`가 `network_mode: host`로
> `0.0.0.0:5432`에 바인딩한다(실측 `ss -ltn 'sport = :5432'` → `0.0.0.0:5432`·`[::]:5432`).
> (2)+(3)의 조합만이 "격리는 되어 있고 필요한 연결은 살아 있다"를 동시에 증명한다.
>
> **`--internal` network는 이 경로를 막지 않는다 — 실측으로 확정됐다.** host 자신에게
> 향하는 트래픽은 FORWARD가 아니라 **INPUT**을 타고, INPUT은 정책 `ACCEPT`에 규칙이
> 0개다. 기본 `bridge`에서 실제로 `pg_isready -h 172.17.0.1` rc=0과
> `psql … -c "select … count(*) from feature.curation_items"` → `3530` 응답을 받았다
> (§8.1 L2b 박스). 따라서 **scoped reject는 조건부 보정이 아니라 필수 선행이다.**

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
| 8-4 (c) identity 대조 | **`diff0068_exit=0`** — prod 0068과 scratch 0068의 52 테이블 count/행해시가 전량 일치 | ≠0 = bundle이 prod 0068을 재현하지 못한다 → **H30B에 넘기지 않는다.** 이것이 task step 8의 "DB identity를 대조" 요구의 이행 지점이다 |
| 음성통제 (0) | `iptables -S H35FENCE` 출력에서 scratch subnet reject가 **loopback RETURN보다 앞** | 뒤에 있으면 순서 의도가 문서와 다르다 → 재삽입 |
| 음성통제 (1)(2)(4) | 단독 network / **(2) `exit != 0`** / 위반 0건 | **(2)가 0 = 격리 실패**(reject가 안 걸렸거나 subnet이 틀렸다) → **daemon을 즉시 정지하고** 규칙을 고친 뒤 재검증. (4) 위반 = prod credential 누출 |
| 대조군 (3) | **`exit 0`** | ≠0 = 대조군이 죽었다 → (2)의 실패가 무의미해진다(둘 다 실패면 network 자체가 죽은 것) |
| preflight 후 | daemon stop → **같은 pair를 signed 0068 bundle로 다시 reset·복원**(8-4 (a)(b)(c)를 그대로 재실행) → `diff0068_exit=0` 재확인 → H30B 인수 identity 복구 | preflight가 scratch metadata(heartbeat/tick)를 바꿨으므로 이 reset이 필수다. **별도 clone은 만들지 않는다** — task 명시 요구다. (디스크 근거: `krtour_map` 22.33 GiB + `krtour_map_dagster` 0.73 GiB = **23.06 GiB**이고 두 벌이면 46.1 GiB다. 현재 avail 84.2 GiB에서는 물리적으로 가능하지만 **하지 않는다** — 이전 판본의 "22.3+22.3 > 53.7 GiB — 디스크상 필수 제약"은 **산술이 틀렸고**(44.66 < 53.7) 근거로 성립하지 않았다. **금지의 근거는 task 문구이지 디스크가 아니다**) |

> **task 문구 축소 (기록 필수).** "prod credential·**network** 없이"는 이 호스트에서 완전
> 달성 불가하다 — 같은 호스트의 docker gateway 때문이며 **이제는 추정이 아니라 실측이다**
> (bridge 컨테이너가 `172.17.0.1:5432`로 prod app DB를 실제로 읽었다). 달성 가능한 형태는
> **"prod credential/DSN 미주입 + scratch DSN 한정 + scoped reject 선행 + 그 뒤의 판별력 있는
> 음성통제"** 까지다. 산출물에 이 문구로 좁혀 기록한다 — **"필요 시"가 아니라 "선행"이다.**
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
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step9 --confirm'
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
| UI `/api/build-info` | **200** + `revision == $T` + `source_digest ==` 2-3 선계산값 (**candidate 축이므로 200이 맞다** — baseline 401과 비대칭이다, §5 박스) | **503 `BUILD_REVISION_UNAVAILABLE`** = route가 읽는 **`process.env.NEXT_PUBLIC_KOR_TRAVEL_MAP_GIT_COMMIT`**(`route.ts:33`)이 비었다. build arg `KOR_TRAVEL_MAP_GIT_COMMIT`이 `frontend.Dockerfile:51,59`에서 `NEXT_PUBLIC_…`로 재노출되는 경로가 끊긴 것이다(revision이 40-hex 아니거나 digest가 64-hex 아니면 503). **401** = candidate가 아니라 baseline UI가 아직 떠 있다. `source_digest` 불일치 = 소스 트리 불일치 |
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
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step10-stop --confirm'
#   compose_service.run(["stop", dagster, ui, api], mutation_capability=…, transaction=tx)

# 10-2 [W] ⛔ 디스크 확보 — step 8의 scratch를 먼저 버린다 (23.1 GiB 회수)
#   ★ 이 순간 H30B 인수물의 절반(clean scratch identity)이 비가역으로 사라진다 (§16 H-7)
wsl ssh n150 'docker rm -f h35-scratch-daemon h35-scratch-pg; docker volume rm h35-scratch-pgdata'
wsl ssh n150 'df -B1 --output=avail /'                      # **≥ 32 GiB** (재산정, 아래 박스)

# 10-2b [W] ★ L5 재적용 — swap 창 동안 신규 비-superuser 접속을 다시 막는다 (H-6 TOCTOU)
#   L5는 6-0에서 -1로 원복됐고 그 뒤 재적용된 적이 없다. 10-5의 RENAME은 연결이 1건이라도
#   있으면 거부되므로, 확인과 RENAME 사이의 재접속이 곧 재시도 유발 요인이다
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -v ON_ERROR_STOP=1 \
  -f - < /home/digitie/h35/run/sql/connlimit-set0.sql'
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -A -F "|" \
  -f - < /home/digitie/h35/run/sql/connlimit-verify.sql'      # 0 / 0

# 10-3 [W] rollback DB를 새 이름으로 복원 (superuser addr, 자격증명 없음 — P4)
#   ⛔ superuser는 datconnlimit 예외이므로 10-2b가 이 복원을 막지 않는다
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -v ON_ERROR_STOP=1 \
  -f - < /home/digitie/h35/run/sql/rollback-create-db.sql'
wsl ssh n150 'docker run --rm --network host -u "$(id -u):$(id -g)" \
  -v /home/digitie/h35/run/bk0063:/bk:ro -e HOME=/tmp -e PGCLIENTENCODING=UTF8 postgres:16 \
  pg_restore -h 127.0.0.1 -p 5432 -U addr -d krtour_map_h35rb \
  -j 4 --exit-on-error --no-tablespaces --verbose /bk/krtour_map.dump'
#   krtour_map_dagster_h35rb 동일(`-d krtour_map_dagster_h35rb`, `/bk/krtour_map_dagster.dump`)

# 10-4 [R] swap 전 복원 검증
wsl ssh n150 'docker exec kor-travel-geo-postgres psql -U addr -d krtour_map_h35rb -Atc \
  "select version_num from public.alembic_version"'          # 0063_pipeline_root_id
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d krtour_map_h35rb -X -q -A -F "|" \
  -f - < /home/digitie/h35/run/bin/h35-identity-52.sql > /home/digitie/h35/run/identity-h35rb.txt'
wsl ssh n150 'diff -u /home/digitie/h35/run/identity-prod-0063.txt \
  /home/digitie/h35/run/identity-h35rb.txt; echo "diffrb_exit=$?"'      # 0이어야 한다
# 10-4b [R] ★ step 1의 config checksum 되대조 — P5 freeze의 유일한 탐지 수단
wsl ssh n150 'sha256sum -c /home/digitie/h35/run/config-checksums-pre.txt'   # 전부 OK

# 10-5 [W] ⛔ swap — **연결 0건이 요구된다**(10-2b의 L5가 그것을 유지한다)
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -A \
  -f - < /home/digitie/h35/run/sql/sessions-both-count.sql'   # 0이어야 한다
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -v ON_ERROR_STOP=1 \
  -f - < /home/digitie/h35/run/sql/rollback-swap.sql'
#   네 RENAME이 **한 psql 호출·한 트랜잭션**으로 커밋된다(실측: `ALTER DATABASE … RENAME`은
#   트랜잭션 블록 안에서 허용된다). postgres DB에 접속한 세션에서 실행한다.
#   krtour_map_h35broken / krtour_map_dagster_h35broken 은 **증거로 보존한다** (지우지 않는다)

# 10-5b [W] ★ L5 원복 — swap이 끝났으므로 앱이 다시 붙어야 한다
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -v ON_ERROR_STOP=1 \
  -f - < /home/digitie/h35/run/sql/connlimit-reset.sql'
wsl ssh n150 'docker exec -i kor-travel-geo-postgres psql -U addr -d postgres -X -A -F "|" \
  -f - < /home/digitie/h35/run/sql/connlimit-verify.sql'      # -1 / -1
#   ⛔ 이것을 빠뜨리면 10-6의 recreate가 "too many connections"로 영원히 unhealthy가 된다

# 10-6 [W] exact rollback image ID로 비-daemon 3개 recreate
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step10-restore-3 --confirm'
#   env = compose_service._pair_image_environment(m.active)   ← 값이 곧 step 1의 exact set
#   ⛔ driver가 up_stage 호출 **전에** env의 4개 image ID가 m.active와 문자 단위 일치하는지
#      assert한다 — candidate ID가 섞이면 그 entrypoint가 복원 DB를 다시 0068로 올린다.
#      검증표의 사후 탐지만으로는 늦다
#   up_stage(…, [api, ui, dagster], env) → poll_health ×3          ← 정의는 §3.2
#   → _verify_running_image_source_provenance(expected_revision=m.active.map_source_revision)
#   → run_map_ops_smoke(cfg) and run_map_ui_auth_preflight(cfg) → assert db_head()=="0063_…"

# 10-7 [W] 위가 전부 green인 뒤에만 exact 이전 daemon
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step10-restore-daemon --confirm'

# 10-8 [R] pair 무결성 복구 확인 — 여기서 sanctioned 기계가 살아난다
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step10-assert'
#   assert _pair_matches(_inspect_current_pair(cfg), m.active)
#   reconcile_pair_references((m.active, m.rollback), cwd=get_project_root())   # candidate 태그 정리

# 10-9 [W] ★ **rollback 분기 전용 enablement 복원** — §15 11-5를 가리키지 않는다
#   (11-5는 forward-only 확정 **이후** 단계다. task step 10은 "step 4에 기록한 enablement를
#    복원한다"를 rollback 분기 자체의 요구로 명시했다)
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py restore \
  --snapshot /home/digitie/h35/run/enablement-baseline.json'            # DRY RUN
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py restore \
  --snapshot /home/digitie/h35/run/enablement-baseline.json --confirm'
wsl ssh n150 'python3 /home/digitie/h35c/h35_instigation.py verify \
  --snapshot /home/digitie/h35/run/enablement-baseline.json --target baseline'
#   복원 mutation 매핑은 §15의 표와 동일하다(SCHEDULE RUNNING 34 → startSchedule /
#   STOPPED 3 → 아무것도 안 함 / SENSOR RUNNING 3 → startSensor /
#   DECLARED_IN_CODE 7 → **resetSensor**). `startSensor`를 7개에 쓰면 저장값이 영구 변질된다
# 10-10 [W] daemon health green 확인 → **그 다음에만** fence 해제 (§15 11-6과 같은 역순 절차)
wsl ssh n150 'docker inspect kor-travel-map-dagster-daemon-latest \
  --format "{{.State.Status}} {{.RestartCount}}"'                       # running / 0
#   그 뒤 11-6의 fence 해제 블록을 그대로 실행한다(L2b·scratch subnet reject 포함)
```

> ### 10-2의 `≥ 24 GiB`를 **`≥ 32 GiB`** 로 재산정한다
>
> 실측 크기: `krtour_map` **23,976,006,115 B(22.33 GiB)** + `krtour_map_dagster`
> **785,715,683 B(0.73 GiB)** = **23.06 GiB**. 이전 임계값 24 GiB는 **순수 데이터만 겨우
> 맞는 값**이라 아래 셋을 담지 못한다.
>
> | 항목 | 근거 | 개산 |
> |---|---|---|
> | 복원 대상 데이터 | 위 실측 | 23.1 GiB |
> | `pg_restore -j 4` 인덱스 재구축 임시 정렬 파일(`base/pgsql_tmp`) | 4 병렬 × `maintenance_work_mem` 초과분이 디스크로 흐른다 | ≈ 4~6 GiB |
> | 복원 중 생성되는 WAL | `wal_level=replica`, `archive_mode=off`라 아카이브로 빠지지 않고 `max_wal_size`까지 쌓인다 | ≈ 2~4 GiB |
> | **합계** | | **≈ 30~33 GiB → 임계 32 GiB** |
>
> **파손 DB 보존분(22.3 GiB)은 이 임계에 포함되지 않는다** — swap 시점에 이미 디스크에
> 있던 것이 이름만 바뀌기 때문이다. 다만 **swap 직후의 정상 여유**는
> `avail(10-2) − 23.1`이 되고 여기에 `kor_travel_geo` 32 GB가 동거한다는 점을 승인자가
> 알아야 한다(§16 H-6). 2026-07-30 기준 avail 84.2 GiB에서는 넉넉하다.
>
> **`*_h35broken`의 폐기 조건·시점 (이전 판본에는 없었다).** 다음 **셋이 모두** 성립한
> 뒤에만 `DROP DATABASE krtour_map_h35broken` / `…_dagster_h35broken`을 **별도 승인 아래**
> 실행한다 — 그때까지는 지우지 않는다.
> 1. rollback 원인 분석이 끝나 산출물(`step6-fail.log`, `gate-partial.txt`, `gate-post.txt`)에
>    기록됐고, 파손 DB에서 더 뽑을 것이 없다고 판단됐다.
> 2. `bk0068` bundle이 `SHA256SUMS` 검증을 통과한 상태로 보존돼 있다(파손 DB의 내용이
>    bundle로 대체 가능하다는 뜻).
> 3. H35 재시도 일정이 확정됐거나 T-VN-H35가 공식 중단됐다.
>
> **디스크 압박만을 이유로 지우지 않는다** — 그 경우 `docker builder prune`(74 GB)이 먼저다.

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
| 10-2 `df` | **≥ `34359738368`(32 GiB)** | 미달 → **복원을 시작하지 않는다.** `docker builder prune`(74 GB)이 먼저다 |
| 10-2b L5 재적용 | `datconnlimit = 0/0` | 걸리지 않았으면 10-5의 TOCTOU가 열린 채로 들어간다 |
| 10-4 head + identity | `0063_pipeline_root_id` + **`diffrb_exit=0`**(52 테이블 count/행해시가 `identity-prod-0063.txt`와 전량 일치) | 불일치 → **swap하지 않는다.** 복원이 불충실하면 swap은 파손을 확정할 뿐이다 |
| 10-4b config checksum | `sha256sum -c` **전부 OK** | 불일치 = **H35 window 중 `.env`/`docker-compose.yml`/manifest가 바뀌었다**(P5 위반) → rollback이 다른 pair·다른 환경으로 갈 수 있다. 원인을 먼저 확정한다 |
| 10-5 연결 수 | **0** | >0 → `ALTER DATABASE … RENAME`이 거부된다. 10-2b가 걸려 있는데도 >0이면 superuser 세션이 남은 것이다(우리 자신을 포함) |
| 10-5b L5 원복 | `datconnlimit = -1/-1` | 원복하지 않으면 10-6의 앱이 접속하지 못해 **영원히 unhealthy**가 된다 |
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
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/python /home/digitie/h35/run/bin/h35ctl.py step11 --confirm'
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
wsl ssh n150 'cd /home/digitie/.cache/c7-final.pihf0x9o/manager && HOME=/home/digitie \
  ./.venv/bin/ktdctl action pinvi-dagster start --json'
#   4-4에서 pinvi-api도 내렸다면 여기서 함께 되살리고 `.Image`·revision 무변화를 재확인한다
wsl ssh n150 'sudo -n iptables -L H35FENCE -v -n > /home/digitie/h35/run/fence-counters.txt; \
  sudo -n iptables -D INPUT -j H35FENCE; sudo -n iptables -F H35FENCE; sudo -n iptables -X H35FENCE'
#   `-F H35FENCE`가 L2b(172.17.0.0/16 → :5432)와 scratch subnet reject까지 함께 지운다 —
#   체인 안에 있으므로 별도 삭제가 필요 없다. `-S`로 잔여 0건을 확인한다
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
| **H-1** | **step 0** 잔여 restore DB `DROP DATABASE` — **조건부. 기본은 발생하지 않는다** | superuser 권한으로 실행되고 `archive_mode=off`라 PITR이 없다. **자격증명 장벽이 없어 오작동 여지가 더 크다**(P4) | ⛔ **선결: 0-1 재측정 avail이 40 GiB 미만일 것.** 2026-07-30 실측 84.2 GiB에서는 **이 항목 자체가 발생하지 않으므로 승인 대상이 아니다.** 발생 시에만 — 소유자(`datdba`)·용도 확인, 해당 DB가 어떤 task 산출물도 아님, 회수 목록을 `*_restore`/`*_restore_manual`/`ktc_t1*`로 한정, **`kor_travel_geo`(형제 서비스 운영 DB)가 목록에 없음을 이름 전체로 대조**, `docker builder prune`을 먼저 시도했음 |
| **H-2** | **step 0/3.5** root 소유 rehearsal dump 이동·권한 변경 `[sudo]` | 파일 위치·권한 | 그 dump가 rollback source로 **쓰이지 않음**을 명시 |
| **H-3** | **step 2** `:latest-main` 5개 이동 + 범위 밖 `pinvi-api` rebuild | 태그 이동 자체는 되돌릴 수 있으나, **step 1의 immutable 태그가 없는 상태에서 하면 `c8ed6164` pair가 dangling이 되어 `docker image prune` 한 번에 소멸한다** | build 전 `_owned_references == 10` assert 통과. pinvi 부작용(image ID 이동, build 실패가 map build를 abort)을 승인 항목으로 명시 |
| **H-4** | **step 4-2/4-3** off-box maintenance + on-box `H35FENCE` 투입 = **공개 outage 시작** | maintenance 페이지가 아니라 502/503·tcp reset이다. PinVi도 Map API 의존이 끊긴다 | outage 창 합의(P8). 문서·통보에 "maintenance"라 쓰지 않고 **planned outage**로 기록 |
| **H-5** | **step 6** candidate API 첫 기동 = **0064~0068 적용** | 0065의 `collection_key` **52행 재작성**·`source_updated_at` **3,530행 UPDATE(WHERE 없음)**·`operator_updated_*`/`legacy_projection_id` 3,044행, 0066의 `external_component_id` backfill은 **downgrade로 복구되지 않는다.** 0064/0068의 `autocommit_block()`이 **부분 적용 상태**를 만든다 | 5-3 identity `diff_exit=0`으로 검증된 0063 dump, step 1 rollback image set 태그 검증, **5.5 리허설 통과**, P3/P4의 복원 경로 실증, `RestartCount` 게이트 준비 |
| **H-5a** | **step 5.5** scratch 리허설 = 이 절차에서 `alembic upgrade head`가 **처음 발화**하는 지점 | prod에는 비가역이 아니다(대상이 scratch DB뿐). **그러나 주입 env가 틀리면 그 순간 대상이 prod가 되고, 그 경우 §16 H-5와 동일한 비가역이 승인 없이 발생한다** | `h35_env_negcheck.py --env-file scratch-api.env` 통과(§3.3 판정 기준), `--network h35-scratch` 단독, `scratch-api.env`에 prod DSN·`67c3f5db` 지문 부재. **L5는 부수적 보호일 뿐 방어로 계산하지 않는다**(superuser는 `datconnlimit` 예외) |
| **H-6** | **step 10-5** `ALTER DATABASE … RENAME` swap | prod DB 실체 교체. **dump 시각 이후의 모든 write가 영구 소실**되고 `archive_mode=off`라 roll-forward 수단이 없다. 파손 0068 DB는 증거로 남지만 **두 번째 복구점이 아니다** | 10-4 `diffrb_exit=0` + 10-4b config checksum OK, **10-2b의 `CONNECTION LIMIT 0` 재적용**, 연결 **0건**, `df` **≥ 32 GiB**(재산정), 파손 DB 보존 이름·**폐기 조건 3개**(§14 박스) 확정, 그리고 아래 **write 소실 구간**을 승인자가 명시적으로 받아들일 것 |
| **H-6a** | **step 6-0 → step 11-6 구간의 on-box loopback write** | 이 구간에는 loopback writer를 막는 층이 **하나도 없다**(L2는 loopback을 RETURN하고 L5는 6-0에서 원복된다, §2·§8.1). host-network `pinvi-api`가 이 구간 내내 running이고 map admin base URL + ops cancel/read token을 갖는다. **여기서 발생한 write는 step 10을 타면 전부 영구 소실된다** — 복구점(bk0063)이 그 이전이기 때문이다 | 승인자가 이 구간의 존재와 소실 범위를 알고 있을 것. 완화 선택지 둘 중 하나를 **명시적으로 선택**: (a) 4-4에서 `pinvi-api`도 정지(대가: step 9 `run_ui_auth_smoke`·11-3 `_require_services_ready`가 11-6 전 복구를 요구), (b) 정지하지 않고 잔여 위험을 수용. **선택 결과를 산출물에 기록한다** |
| **H-4a** | **step 4-5** 44건 pause + `enablement-baseline.json` | 저장값 `DECLARED_IN_CODE` 7개는 **GraphQL `InstigationStatus` enum에 없어** `canReset`으로만 판별된다 — **이 파일이 없으면 원래 값을 잃어 복원 자체가 불가능해진다**(§15). 파일 1개가 유일 복구 경로다 | 4-1 record 산출물의 **사본 2벌**(`$H35/enablement-baseline.json` + `$H35/SHA256SUMS.step1`에 결속), 개수 대조(`schedules 37` / `sensors 10` / `effective_running_total 44`), pause **전에** 사본이 확보돼 있을 것 |
| **H-7** | **step 10-2** 디스크 순서 결합 | 23.1 GiB 복원 공간(+임시공간·WAL 포함 32 GiB 임계)을 만들려면 step 8의 scratch를 먼저 폐기해야 한다 → **rollback을 시작하는 순간 H30B 인수물의 절반(clean scratch identity)이 비가역으로 파괴된다.** 재구축은 signed bundle로만 가능하고 그 자체가 다시 23 GiB를 요구한다 | 이 결합을 승인자가 알고 있음. rollback이 공짜가 아니라는 점의 정확한 형태다. (2026-07-30 avail 84.2 GiB에서는 **폐기 없이도 임계를 만족할 수 있다** — 10-2에서 `df`를 먼저 재고 32 GiB 이상이면 scratch를 남겨 둔 채 진행해 이 결합을 회피한다) |
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
지점을 함께 적는다. **번호는 감사 이전 판본과 맞춰 유지하고, 해소된 항목은 지우지 않고
"해소" 표시와 실측값을 남긴다** — 무엇이 왜 바뀌었는지가 산출물의 일부다.

1. **off-box HAProxy의 소유자·maintenance 절차·backend 구성·통보 경로** — n150 밖이라 전부
   미확인. L1은 이 runbook의 통제 밖이며 L2/L2b가 우리가 보증하는 층이다.
2. ✅ **해소(2026-07-30 실측).** ~~bridge 컨테이너에서 docker gateway IP를 통한 호스트
   `0.0.0.0:5432` 도달 가능성~~ → **도달한다. 확정 사실이다.**
   `bridge` gateway = `172.17.0.1`, `ss -ltn 'sport = :5432'` → `0.0.0.0:5432`·`[::]:5432`,
   `docker run --network bridge postgres:16 pg_isready -h 172.17.0.1 -p 5432` → **rc=0
   "accepting connections"**, 이어서 `psql -h 172.17.0.1 -U krtour_map -d krtour_map`로
   **`feature.curation_items` 3530행을 실제로 읽었다.** `iptables -S INPUT` = `-P INPUT
   ACCEPT`(규칙 0개), `DOCKER-USER` 비어 있음. `pg_hba` 마지막 줄 `host all all all
   scram-sha-256`이 적용되지만 **DSN·비밀번호가 컨테이너 env에 흔히 있으므로 인증 층을
   방어로 계산하지 않는다.**
   → **결과: §12 8-5의 scoped reject는 조건부가 아니라 필수 선행이고**(§12 음성통제 (0)),
   같은 경로를 fence 층 **L2b**로 승격해 4-3c에서 투입한다(§8.1). "prod network 없이"는
   달성 불가로 확정됐고 §18-2의 축소 문구가 그 기록이다.
3. **소요 시간·산출 크기 전부** — dump 소요, 23.1 GiB scratch 복원 소요, 0064~0068 실행
   시간, outage 창 길이. 유일한 실측 근거는 기존 dump 1.13~1.21 GiB / 약 3분이다.
   **outage 창은 §9 5.5 리허설의 `elapsed_s` 실측으로만 확정된다** — 그전에 창 길이를
   약속하지 않는다. (이전 판본이 여기 걸어 두었던 "30회×2초=60초 예산" 모델은 **사실
   오류로 삭제됐다** — §10 박스. 마이그레이션 1회 시도에는 시간 상한이 없다.)
4. **`ALTER DATABASE … RENAME`의 prod cluster 실동작·소요** — 미리허설. §16의 가장 약한
   지점 그 자체다.
5. **dagster catch-up 배제 결론의 버전 갭** — `Scheduler.start_schedule`이
   `start_timestamp=now`로 `instigator_data`를 교체한다는 결론은 CI 이미지의 dagster
   **1.13.13** 소스에서 읽었고 prod는 **1.13.15**다. mutation surface·`canReset`·enum은
   live 1.13.15 introspection으로 확인했으므로 **재검증 대상은 이 한 결론뿐이다.**
6. **`pg_hba.conf`의 trust 항목**은 2026-07-30 실측값이다. P4에서 **재확인 없이 복구 경로의
   전제로 쓰지 않는다.**
7. ✅ **해소.** ~~`_owned_references`의 호출 시그니처~~ → `c6c_image_retention.py:151`
   **`_owned_references(*, cwd: str) -> set[str]`**(배포 rev `c7328ed9` 실측).
   짝인 `ensure_pair_references`는 `:116`, `reconcile_pair_references`는 `:173`이고
   **둘 다 `cwd=`가 필수 keyword**다. step 2의 "유일한 방어"(`== 10` assert)가 미확인 함수에
   얹혀 있던 상태가 해소됐다.
8. **`run_map_ops_smoke` / `run_map_ui_auth_preflight` / `run_ui_auth_smoke` /
   `validate_runtime_secret_isolation` / `_inspect_c6c_runtime_configs`의 인자 계약** —
   호출 위치와 위치인자 개수는 확인됐으나(`c6c_deployment.py:1907`/`:2704`/`:2764`/`:3817`,
   `compose_service.py:4784`) **전체 시그니처는 여전히 미확인**. driver 작성 시 소스 재확인.
   (`_run_up_stage`만은 §3.2에서 전수 대조를 마쳤다 — 그것이 이 목록에서 유일하게 **틀린
   채로 본문에 박혀 있던** 항목이었다.)
9. ✅ **해소(2026-07-30 실측). 폐기 항목.** ~~현행 UI의 `/api/build-info` 응답 — 503일
   가능성이 배제되지 않았다~~ → **401이다. 200도 503도 아니다.**
   `curl … :12705/api/build-info` → **401**, `/admin` → 307(UI 자체는 정상),
   `docker exec kor-travel-map-ui-latest grep -rl "build-info" /app/.next/server` → **빈 출력**
   (실행 중 이미지 번들에 그 문자열이 없다), `git ls-tree c8ed6164 …/src/app/api/`에
   `build-info/` 부재, `c8ed6164:middleware.ts`에 `PUBLIC_EXACT_PATHS` 부재.
   → **결과: step 1-4 게이트를 baseline 401 / candidate 200 비대칭으로 재작성했다**(§5 박스).
   "503이면 step 9/10의 UI identity 기준이 무의미해진다"는 서술도 폐기된다 — **candidate
   축은 200으로 정상 동작하므로 무의미해지지 않는다.** baseline UI identity는 image ID +
   revision 라벨 + retention 태그 세 축으로 잡는다.
10. ✅ **해소(2026-07-30 실측).** ~~prod API 컨테이너의 `admin_trusted_proxy_cidrs` 실제 값~~
    → `KOR_TRAVEL_MAP_API_ADMIN_TRUSTED_PROXY_CIDRS=["127.0.0.1/32","::1/128"]`
    (기본값과 동일, override 없음). **loopback이 포함되므로 H36 게이트를 API 직접 호출로 할
    수 있다.** 3-6의 명령도 `grep -c`(항상 1)에서 **값 출력**으로 교체돼 이 결론을 실제로
    산출한다.
11. **step 2의 좁은 대안 seam** — `compose_service.run(["build", 4 map svc],
    environment={4×`*_IMAGE`, `KOR_TRAVEL_MAP_GIT_COMMIT`, **prov.compose_environment()},
    transaction=tx)`가 `:latest-main` 이동과 pinvi rebuild를 **실제로** 회피하는지 미검증.
    회피하더라도 `_require_expected_source_provenance`·`_inspect_c6c_candidate_pair`의
    attestation을 별도로 불러야 한다. 이 runbook은 sanctioned seam
    `_prepare_c6c_candidate_pair`를 쓰고 부작용을 H-3으로 승인 처리한다.
12. **잔여 restore DB의 소유자·용도** — 여전히 미확인. **단 규모는 확정됐다** — 남은
    `*_restore*` 3개의 합계는 ≈70 MB이고, P2가 최대 대상으로 지목했던
    `kor_travel_geo_restore`(31.5 GiB)는 **이미 존재하지 않는다**. H-1이 발생할 때만
    확인 대상이며, 현재 실측에서는 H-1 자체가 발생하지 않는다.
13. ✅ **해소(부분).** ~~`.env` 02:42 변경의 이력 — 누가 왜 했는지 미확인~~ → **on-box에
    답이 남아 있다.** `/home/digitie/h35/h35_align.sh`(mtime **07-30 02:42**, 헤더에 "live
    컨테이너의 해시를 cache `.env`로 복사"라는 목적이 적혀 있다)와
    `$CACHE_MGR/.env.bak-h35align-20260730T024212Z`(02:41)가 존재한다. 즉 **02:37
    out-of-band UI recreate 뒤의 정렬 스크립트**이고 P5의 서술과 일치한다. **남은 미확인은
    "누가 그 스크립트를 돌리기로 결정했는가"뿐**이고, 이것은 절차의 전제가 아니라 이력이다.
    P5의 freeze 요구와 1-6의 checksum 채취·10-4b 되대조가 이후의 탐지 수단이다.
14. **§3.3의 "작성 대상" **6개** 도구는 존재하지 않는다**(실측 0개 존재. 이전 판본은 7개로
    셌으나 `h35_record_rollback.py`는 호출처가 없어 제외했다). **P9와 §3.6이 그 게이트다.**
    산출물 루트 `/home/digitie/h35/run`과 `secrets/`·`sql/`도 §3.6이 만들기 전에는 없다.
15. **`0.0.0.0:12702` Dagster GraphQL이 무인증이고 `hasStartPermission`/`hasStopPermission`이
    true다.** 우리가 pause 채널로 의존하는 것과 같은 이유로 네트워크상의 누구든 schedule을
    끄거나 run을 launch할 수 있다. H35 범위 밖이지만 **L2 fence가 이 표면도 함께 막는다**는
    점만 기록한다 — 해제 후에는 다시 열린다.
16. 🆕 **배포 target 커밋 표기가 갈려 있다.** 이 문서의 `$T`는 `ddd1308c…`이고 2026-07-30
    `git rev-parse origin/main`과 일치한다. 그런데 n150에 `h35-deploy-0add95a5.sh`(mtime
    01:11)가 남아 있고 운영 대화에서도 `0add95a5`가 target으로 언급됐다. 실측 대조 결과
    **`0add95a5`는 `ddd1308c`의 조상**이고(PR #894 vs #896), **두 커밋 모두 H36(`653d82a2`)을
    포함하며 둘 다 `api/build-info/` route를 갖는다** — 따라서 게이트 설계는 어느 쪽이든
    성립한다. **그러나 어느 것을 배포할지는 확정되지 않았다.** P10에서 하나로 고정하고
    산출물에 기록하기 전에는 step 2에 들어가지 않는다. 확정되면 §11 K01/K03·§13 revision
    기대값이 그 커밋 기준으로 재확인돼야 한다.
17. 🆕 **`h35_fence_probe.py`의 `non_map_app_backends`가 `fatal`에 없다**(실측 확인). 도구를
    이 window에서 고치지 않기로 했으므로 **판정 절차로 닫았다** — 4-7/8-1에서 verdict와
    별도로 그 값을 사람이 읽는다(§8.3). **자동 판정으로 승격하려면 probe 수정이 필요하고,
    그것은 H35 범위 밖이다.**
18. 🆕 **§3.6이 만드는 도구·비밀 파일의 실제 동작은 미검증이다.** 이 문서는 `h35ctl.py`의
    서브커맨드(`manifest-path`·`mk-login-conf`·`mk-scratch-secrets`·`buildargs-gate`·
    `resolved-config`·`step1`…`step11`)와 `h35_env_negcheck.py`의 두 모드 **계약만** 정의했다.
    작성 후 **dry-run으로 각 서브커맨드가 실제로 그 계약을 지키는지 확인하기 전에는 P9를
    통과로 보지 않는다.** 특히 `up_stage` 래퍼는 §3.2의 `result` 사전 형상과
    `capture_output=True`를 그대로 구현해야 한다.
19. 🆕 **L2b(`-s 172.17.0.0/16 --dport 5432 REJECT`)를 실제 투입했을 때의 부작용은
    미검증이다.** 같은 파일시스템·같은 호스트에 geo/concierge/pinvi/monitoring 컨테이너가
    17개 함께 있고, 그중 **bridge network에서 호스트 `:5432`로 붙는 것이 있으면 그것도 함께
    끊긴다.** 4-3c 투입 직후 `docker ps`로 다른 프로젝트 컨테이너의 health가 변하지 않는지
    확인하고, 변하면 그 컨테이너를 식별해 산출물에 기록한 뒤 승인 아래 진행한다.
    (map/geo/concierge/pinvi의 주 경로는 `network_mode: host` = loopback이므로 영향받지
    않을 것으로 보이나 **실측하지 않았다.**)

---

## 18. task 본문 정정 사항 (산출물에 함께 기록)

1. **"prod ingress를 maintenance 상태로 두고"** → n150에 maintenance surface가 없다.
   **off-box HAProxy maintenance + on-box `H35FENCE`** 로 대체하고 문구를
   **planned outage**로 고친다(§8).
2. **step 8 "prod credential·network 없이"** → 같은 호스트의 docker gateway 때문에 network
   격리는 완전 달성 불가이며 **이제는 추정이 아니라 실측이다**(§17-2: bridge 컨테이너가
   `172.17.0.1:5432`로 prod app DB를 실제로 읽었다). **"prod credential/DSN 미주입 +
   scratch DSN 한정 + scoped reject 선행 + 그 뒤의 판별력 있는 음성통제"** 로 좁힌다(§12).
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
6. ~~**`docker/api-entrypoint.sh`의 정확한 줄은 `:215`**~~ → ⛔ **이 "정정"은 철회한다.
   task 본문의 `:216`이 옳았다.** 실측(배포 rev `c8ed6164`·candidate 양쪽 동일):
   `:212 retries=`, `:213 sleep_seconds=`, `:214 attempt=1`, **`:216 while ! alembic upgrade
   head; do`**. 이전 판본은 §6-4·§10 목적문·이 항목 세 곳에서 `:215`로 적었고 **모두
   `:216`으로 고쳤다.** "정정 사항" 절의 유일하게 검증 가능한 줄 번호 주장이 틀린 채
   산출물에 박히는 것은 이 저장소가 반복한 identity 오류 유형 그대로다 — 그래서 항목을
   지우지 않고 철회 기록으로 남긴다.
   (유지되는 사실: retries 30 / sleep 2s이고 둘 다 env로 tunable하지만 **배포 compose에 그
   키가 0 hit이라 prod에서 조정 불가**하다. 단 **그것이 마이그레이션 시간 상한을 뜻하지는
   않는다** — §10 박스.)
7. **`ops.dagster_schedule_overrides`에 유령 override 1건**
   (`feature_notice_krex_traffic_notices_monthly_schedule`, cron `7 * * * *`). 실제 schedule
   이름이 `..._ten_minute_schedule`이라 지금은 무효지만 **이름이 바뀌면 조용히 활성화될 수
   있다** → §11에 "override 매칭 0건 유지"를 넣었다.
8. **`collection_key` 계약 문서화**(blocker 아님) — 0045→0065에서 형식이 두 번 바뀐 불안정
   business key다. admin create·저장·검색과 CSV upsert에는 쓰지만 **외부의 장기 참조·path
   identity는 `collection_id`를 써야 한다.** `docs/integration-map.md`에 경계를 명시한다.
9. **`scripts/docker-backup.sh` 정정** — `:80,:85,:117`의 standalone `postgres` service
   하드코딩과 **`:121` `--no-owner` · `:122` `--no-privileges`**(이전 판본의 `:119-121`은
   오프바이-원이었다)는 prod에 대해 둘 다 틀렸다.
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
