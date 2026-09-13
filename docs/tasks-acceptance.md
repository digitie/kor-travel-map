# 열린 task의 acceptance criteria (복원본)

> `docs/tasks.md`는 2026-08-27 커밋 `6d671ef1`(`docs: flatten active task order`)에서
> 991줄 → 30줄로 평면화됐다. 그 커밋은 **완료 항목을 `tasks-done.md`로 옮긴 것이
> 아니라, 아직 열려 있는 항목의 acceptance criteria를 지웠다.** 같은 커밋은
> `tasks-done.md`를 건드리지 않았으므로(`1 file changed`) 지워진 기준은 어디로도
> 이관되지 않았고 git history에만 남았다.
>
> 그 결과가 실제 사고로 이어졌다. `T-VN-FINAL-REBUILD`의 해제 조건 B1~B4는 삭제 직전
> **전부 미체크**였는데(`git show 6d671ef1^:docs/tasks.md` 739~752행), 조건이 문서에서
> 사라진 다음 날 `b3bbd3a3`이 그 task를 `[ ]` → `[x]`로 바꿨다. 조건이 충족된 것이
> 아니라 **조건 자체가 사라진 뒤 완료 처리**된 것이다. `tasks-done.md`에도 완료
> 엔트리가 없다(교차참조 1건뿐).
>
> 본 문서는 그 기준을 되살린다. `tasks.md`는 평면 목록으로 두고(평면화의 이점은
> 유지한다), 각 항목의 판정 근거는 여기가 소유한다.
>
> **복원 원본**: `git show 6d671ef1^:docs/tasks.md`
> **작성**: 2026-08-30

> **과거 기록 아카이브** (규약 §8 — 과거 검색은 `rg <패턴> docs/archive/`)
>
> | 절 | 파일 | 크기 |
> | --- | --- | --- |
> | `T-VN-M05` · `T-VN-M05-ACTIVATION` (완료) | [archive/tasks-acceptance-m05.md](archive/tasks-acceptance-m05.md) | 약 47 KB |


> **닫힌 task의 acceptance는 여기 없다.** 규약 §8대로
> [`archive/tasks-acceptance-2026-09a.md`](archive/tasks-acceptance-2026-09a.md)로
> 분리했다(31개 절). 이 파일은 **열린 task**만 갖는다 — 제목이 말하는 바다.

## T-VN-FINAL-REBUILD

```markdown
- [x] **T-VN-FINAL-REBUILD — fresh rebuild 완료 후 최종 acceptance 배리어** (2026-09-04 해제)

  H46H가 승인된 `ktdctl pinvi-pair rebuild-pinned --confirm`으로 Map application·Map Dagster·PinVi
  **세 DB를 fresh 재생성**하고 일곱 runtime을 고정 candidate로 재기동했으며, v6
  `pinned-runtime-generation-v6.json`과 v8 `pinned-runtime-rebuild-v8-<pinset>.json`을 남겼다.
  이 task는 해당 committed generation을 D1/F1D-E/D2/41C acceptance에 연결한다. provider
  source·ETL 전량 재적재는 사용자가 정한 대로 release gate가 아니며, 필요할 때만 별도 운영
  데이터 준비로 수행한다.

  **왜 후속을 분리하는가.** v6 generation은 Map/PinVi source revision과 일곱 image ID에
  결박된다. 후보가 바뀌면 H46H rebuild를 새 generation으로 다시 수행해야 하지만, 현재
  committed generation에서는 data-dependent/consumer acceptance만 순서대로 진행한다.

  **배리어 해제 조건.** 종전의 B1~B3(head·OpenAPI·image 입력에 대한 "미반영 변경이
  없을 것")는 **삭제했다** — 같은 문단의 실행 시점 대조가 셋을 정확히 덮는다. 덮임의
  실제 메커니즘(R1-S7 정밀화): B1은 schema head equality, B2는 source pair preflight
  (`_source_pair_preflight`)가 대조하는 **pinned-release OpenAPI blob SHA**, B3은
  **`pinset_sha256` equality**(candidate SHA와 일곱 image ID를 한 digest로 결박)다.
  사람이 "미반영 변경 없음"을
  선언하는 조건은 검증 불가능한 채로 매 병합마다 배리어를 다시 닫아 반복 단가만 키웠다
  (`docs/reports/map-stall-root-cause-2026-08-31.md` §2·§3 I-3, 적대 검증 STRENGTHENED).
  판정은 아래 한 문장이 소유한다.

  **각 실행은 candidate SHA·image ID·schema head·OpenAPI SHA와 v6/v8/host-attestation
  digest를 단순 기록하지 않고 active generation과 exact equality로 대조하며, 누락·불일치면
  시작·receipt 승격·consumer enable을 모두 거부한다.** candidate가 낡았으면 그 대조가
  실행 시작 시점에 fail-close하고, 그때만 새 pinset을 고정해 H46H rebuild를 새
  generation으로 다시 수행한다.

  - [x] B4. **현 candidate의 runtime/attestation 입력을 바꾸는 미반영 변경이 없다.** raw/resolved
    Compose hash, profile, container command, 값 비노출 environment/보안 환경 매핑 hash, mount/network,
    runtime role·ACL, Manager runner와 attestation/verifier contract가 달라지면 false다.
    image·migration·OpenAPI가 같아도 이 입력이 달라지면 이전 v6/v8 journal/evidence를 재사용하지
    않는다. **B4만 유지하는 이유**: 이 표면들은 위 실행 시점 대조 4축(candidate SHA·image
    ID·schema head·OpenAPI SHA)에 포함되지 않아 중복 논증이 성립하지 않는다.

  B4가 false면 이전 journal을 재사용하지 않고 새 immutable v6/v8 journal을 발행한 뒤
  진행한다. 실측상 이 조건이 막는 것은 디버깅이 아니라 **낡은 verifier 계약 아래 발행된
  journal의 재사용**뿐이다(2026-08-27~29 Manager 코드 커밋 132건이 B4 아래에서 그대로
  진행됐다).

  **새 candidate rebuild가 필요한 경우에만 하는 선행 준비.**
  - [ ] n150 디스크 여유 — 일곱 image 재빌드 분. 2026-08-20 기준 101G free(78%)이고
    dangling volume 52GB·구 playwright image 약 43GB가 추가 회수 가능하다.
  - [ ] 고정 release candidate(Map/PinVi 커밋과 일곱 image)를 먼저 확정한다.

  **이 배리어가 푸는 것 (순서대로).**
  1. **완료** — 현 세대 기준의 v6/v8 문서가 H46H committed generation으로 생성됐다. 구 v5/v7
     문서는 퇴역 입력이며 현재 verifier에 사용할 수 없다.
  2. `T-VN-41F1D-D1` — 일곱 image·세 schema head·pinset attestation과 데이터 비의존 UI smoke.
  3. `T-VN-41F1D-E`의 n150 data-dependent 실행(저장소측 계약은 2026-08-20 완료).
  4. `T-VN-41F1D-D2` — 고정 ID를 요구하는 admin/PinVi mutating live E2E.
  5. `T-VN-41C` receipt `pending → candidate_verified` → 최종 prod gate·production
     consumer enable.

  **실행 전제.** v6/v8은 `require_rebuildable_mode` 아래에서만 생성된다(n150은
  `rehearsal`/`rebuildable`이라 해당). ktdm의 state root는 Manager owner 소유 `0700`이라
  runner가 요구하는 root 소유 `0600`을 그대로 만족하지 않으므로, 두 문서의 root 소유 사본을
  만들어 `E2E_C7_PINNED_RUNTIME_MANIFEST`/`E2E_C7_REBUILD_JOURNAL`로 넘긴다(runbook 참조).

### B4 판정 (2026-09-04) — **TRUE, 소유자 서명 완료**

> 소유자가 2026-09-04에 서명했다. 아래가 그 근거이며, 마지막 문단의 해석 문제도 함께
> TRUE로 정리됐다. 배리어는 열렸고 `docs/tasks-done.md`가 완료 이력을 소유한다.

B4는 "현 candidate의 runtime/attestation **입력**을 바꾸는 미반영 변경이 없다"이다.
그 입력 중 셋은 v8 journal이 **해시로 담고 있어** 산문이 아니라 재계산으로 판정된다.
active generation은 `e6b52db4`(Map `8078b110` + PinVi `357da189`), `recorded_at`
`2026-09-03T14:07:27Z`, v8 journal `created_at` `2026-09-03T14:07:28Z`, `phase: committed`,
`journal_generation 33`이다.

**1. 측정한 것 (2026-09-04 n150, 읽기 전용)**

| 입력 | journal 기록 | 재계산 | 판정 |
|---|---|---|---|
| `environment_sha256` | `b670154a…` | `sha256(/opt/kor-travel-docker-manager/.env)` = `b670154a…` | 동일 |
| `compose_sha256` | `1cd6f2e0…` | `sha256(/opt/kor-travel-docker-manager/docker-compose.yml)` = `1cd6f2e0…` | 동일 |

`.env`는 mtime이 오늘로 바뀌었지만(설치가 재검증하며 만졌다) **바이트가 동일**하다 —
installer가 `.env` 바이트 보존을 스냅샷으로 단언한다.

**2. 유도한 것 — `resolved_compose_sha256`**

resolved 문서는 (원본 compose 바이트 + `.env` 바이트 + Manager 렌더링 코드)의 함수다.
앞의 둘이 동일함을 측정했으므로 남는 변수는 렌더링 코드뿐이다. generation 시점 직전
커밋(`c4b509c`)부터 현재 `main`까지의 소스 변경은 **정확히 세 파일**이다:

    backend/src/kor_travel_docker_manager/services/pinned_runtime_sources.py
    scripts/m05_isolated_e2e.py
    scripts/run-m05-isolated-e2e-once

그리고 다음 네 모듈은 **무변경**이다 — resolved compose·profile·container command·
환경 매핑·mount/network·runtime role/ACL과 generation/journal 발행 verifier를 소유하는
모듈 전부다:

    compose_service.py · c6c_deployment.py · pinned_runtime_generation.py
    runtime_execution_registry.py

따라서 `resolved_compose_sha256`은 구성상 변할 수 없다. `docker compose config`로
확인하지 않았다 — 이 저장소가 금지하는 명령이고, 위 유도가 그것을 대신한다.

**3. `pinned_runtime_sources.py` 변경이 materialize 결과를 바꾸는가 — 아니다**

diff는 **303 추가 / 1 삭제**이고, 삭제된 한 줄은 `_promote_staging_worktree`의 독스트링이다.
본문이 바뀐 기존 함수는 넷뿐이며 전부 비-의미론적이다:

- `_promote_staging_worktree` — "등록만 남고 경로가 없는" 상태를 **진단으로 올리는
  선판정 추가**(fail-close만 늘린다)
- `_root_git_environment` / `_source_owner_git_environment` — `GIT_OPTIONAL_LOCKS=0` 추가
  (index 쓰기 억제. 체크아웃 내용에 영향 없음)
- 나머지는 격리 harness 전용 신규 함수(일회용 worktree 3종 + 헬퍼)

revision·tree·clean 검증 경로는 한 줄도 바뀌지 않았다.

**4. 실행 시점 대조가 새 verifier 아래에서 통과했다**

이 절이 B1~B3를 삭제하며 판정을 넘긴 "실행 시점 대조"가 현재 verifier로 실제 돌았다.
`e2e025`(Manager `b3217edc`)의 `_source_pair_preflight`가 committed generation manifest의
`pinset_sha256`과 `map_application_head`를 exact 대조해 통과했고, M04/M05 attestation이
`status: passed`로 발행됐다(`scope: isolated`, `version: 4`,
`m04_server_side_chain_verified: true`).

**5. 판단이 필요한 한 가지**

B4 조문은 "Manager runner와 attestation/verifier contract가 달라지면 false"라고 적는다.
문자 그대로면 위 세 파일이 바뀌었으니 false다. 그러나 같은 절이 그 조문의 실효를
**"낡은 verifier 계약 아래 발행된 journal의 재사용"**으로 한정하고, 실측 근거로
"2026-08-27~29 Manager 코드 커밋 132건이 B4 아래에서 그대로 진행됐다"를 든다. v6/v8 journal을
발행하는 verifier는 `compose_service.py`/`pinned_runtime_generation.py`이고 **둘 다
무변경**이다. 바뀐 셋은 journal을 발행하지 않고 **소비**하며, 소비 대조는 4번에서
통과했다.

문자 그대로 읽으면 B4가 매 Manager 커밋마다 false가 되어, B1~B3를 삭제하며 이 절이
명시적으로 배격한 병리("검증 불가능한 선언이 매 병합마다 배리어를 다시 닫아 반복 단가만
키웠다")를 그대로 재생산한다. 그래서 **TRUE를 권고한다.**

반대 판정(strict reading)을 택하면 조치는 하나다 — `ktdctl pinvi-pair rebuild-pinned
--confirm`으로 현재 Manager 아래 새 v6/v8 journal을 발행한 뒤 진행한다. 비용은 rebuild
1회(일곱 image 재빌드)다. 어느 쪽이든 **이번 실행의 attestation은 폐기되지 않는다** —
pinset과 execution identity가 그대로이기 때문이다.

### F1D-E blocker — host attestation v4 재발행 (2026-09-04 **완료, 검증기 PASS**)

`docs/runbooks/admin-feature-live-acceptance.md` 서두는 "실행 전 신뢰 경계는 C7 host
attestation v4와 pinned runtime manifest v6 + rebuild journal v8을 그대로 재사용한다"고 적는다.
그런데 n150의 `/etc/kor-travel-map/c7-prod-live-e2e-attestation.json`(root 0600)은 **구세대
전체**다 — `repository_commit e420c89e`, `source_commits.pinvi 27fe2043`,
`pinned_runtime_pinset_sha256 de5206dc`, heads `0236_tvn41s_compaction_drained`/`20260821_0061`,
`rebuild_transaction_id 0c523fc4`. 현 candidate `e6b52db4`용 v4는 존재하지 않는다.

저장소에는 **검증기만** 있다 — `scripts/lib/c7_prod_attestation.py`의
`verify_runtime_attestation_payloads`가 18개 top-level 키를 `_exact_dict`로 검사하고
`version != 4`를 거부한다. 생성기·런북·ktdctl 명령은 두 저장소 어디에도 없다. 이 파일은
**운영자가 직접 쓰는 선언**이고, 검증기가 그 선언을 살아 있는 runtime과 exact 대조해
증명한다. 그래서 "서명 위조"가 아니라 선언을 짓는 일이며, 값이 틀리면 검증이 fail-close한다.

필드별 출처는 이렇게 확정된다.

| 필드 | 현 candidate 값 / 출처 | 상태 |
|---|---|---|
| `version` | `4` | 확정 |
| `repository_commit`, `source_commits.map` | `8078b110db4bedd89cf2e6ee7a9d57b210cd224c` | 확정 |
| `source_commits.pinvi` | `357da1897c2df2c86e5f3376e212451cf0f019ab` | 확정 |
| `pinned_runtime_pinset_sha256` | `e6b52db4…` | 확정 |
| `rebuild_transaction_id` | `4ee990ca-2676-4188-ada3-369ddc579911` (v8 journal) | 확정 |
| `schema_heads` 3종 | `303_m05_payload_hash_domain` · `29b539ebc72a` · `20260824_0101` | 확정 |
| `machine_id_sha256`, `hostname_sha256` | n150에서 측정 | 측정 가능 |
| `ui_origin_sha256`, `api_ws_origin_sha256`, `dagster_graphql_url_sha256` | 배포 origin에서 측정 | 측정 가능 |
| `compose_project_sha256` | 배포 compose project 이름에서 측정 | 측정 가능 |
| `service_runtime` 7 role | 실행 중 컨테이너에서 측정(command/image 등) | 측정 가능 |
| `pinned_runtime_manifest_sha256`, `rebuild_journal_sha256` | **v6/v8의 root-owned 0600 사본**의 sha256 | **선행 작업 필요** |
| `orchestrator_files` 4종 | `8078b110`의 `audit-c7-prod-live-state.py`·`lib/c7-prod-runner-lifecycle.sh`·`lib/c7_prod_attestation.py`·`run-c7-prod-live-e2e.sh` sha256 | **snapshot 설치 필요** |
| `playwright_base`, `playwright_image_id` | `8078b110`으로 빌드한 C7 executor image | **빌드 필요** |

즉 18키 중 **13키는 지금 값이 확정되거나 측정 가능**하고, 남은 5키가 세 가지 선행 작업
(v6/v8 0600 사본 · `8078b110` snapshot 설치 · C7 executor image 빌드)에 달려 있다.

**실행 결과 (2026-09-04).** 선행 셋을 모두 수행하고 attestation을 재발행했다. 저장소의
검증기가 살아 있는 runtime과 대조해 **통과**했다 — 선언이 맞다는 것을 내 주장이 아니라
`verify_trusted_runtime_attestation`이 증명한다.

    manifest_sha256    9f6ddfc4d57135a672a1934ba9525bd9119da19da0d301b47e4c50771ca79bab
    journal_sha256     9a52683bfb181983f393b6f354b6eedb34496caec305cfc4119da09c7f1c0c61
    attestation_sha256 40bde4b8718f25af0f7c1f8163c8ebd72e07a55a4ee0bcac85299f8d41da2d6a

- v6/v8 root:root 0600 사본 → `/etc/kor-travel-map/c7-pinned-runtime-{generation-v6,rebuild-v8}-e6b52db4.json`
- `8078b110` c7-runner snapshot → 4파일 147KB, 디렉터리 0755 / 파일 0555 root:root.
  4개 중 **3개는 구세대와 해시가 같다** — 바뀐 것은 `c7_prod_attestation.py`
  (`6e6765b8…` → `ca17c8d7…`) 하나뿐이다.
- C7 executor image → `sha256:2c5ee9ef4a9c5809c3d4b090fe25ad13fd09688e2fbac47cccf16fa0a4b53ded`
  (`io.kortravelmap.c7.repository-commit = 8078b110…`)
- 구세대 attestation은 `.bak-e420c89e-20260904T123809Z`로 보존했다.
- admin lane snapshot도 `8078b110`으로 설치했다 —
  `/usr/local/lib/kor-travel-map/admin-feature-live-acceptance/8078b110…/`(디렉터리 0555,
  py·manifest 0444, 러너 0555, root:root). `admin_feature_live_state.py`는 구세대와 해시가
  같고(`412ec717…`) 나머지 셋만 바뀌었다.

**D2 실행 준비 상태 (2026-09-04).** 신뢰 경계와 snapshot은 전부 갖춰졌고, 남은 것은 운영자만
줄 수 있는 값 하나다.

| 필요 | 상태 |
|---|---|
| host attestation v4 (현 세대) | 발행 완료, 검증기 PASS |
| v6/v8 root 0600 사본 | 설치 완료 |
| c7-runner snapshot `8078b110` | 설치 완료 |
| admin lane snapshot `8078b110` | 설치 완료 |
| C7 executor image | 빌드 완료 (`sha256:2c5ee9ef…`) |
| `E2E_C7_*` env 9종 | 값 전부 확정 |
| `E2E_ADMIN_USERNAME` / `E2E_ADMIN_PASSWORD` | 확보 |
| **`E2E_ADMIN_FEATURE_FIXTURE_PG_DSN`** | **없음 — root 전용 fixture login role의 DSN** |
| `E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_LOGIN_ROLE` | 없음(위 role 이름) |

`CONFIRM_DATABASE`는 `kor_travel_map`, `CONFIRM_ALEMBIC_REVISION`은
`303_m05_payload_hash_domain`으로 v6/v8이 이미 밝힌다. root 소유 파일을 뒤져 자격증명을 찾지
않았다 — 런북도 그 값을 운영자가 shell env로만 넘기라고 정한다.

**착수 전 소유자 판정이 필요한 것 셋.** 아래는 측정으로 풀리지 않는다.

1. **C7 런북은 퇴역했는데 그 attestation은 D2의 신뢰 경계로 남아 있다.**
   `docs/runbooks/c7-prod-live-e2e.md` 머리글은 `[보존 이력 · 실행 금지]`이고 "`300` baseline의
   n150 배포에는 사용하지 않는다"고 적는다. 그런데 admin-feature lane이 그 산출물을 재사용한다.
   신뢰 경계를 C7에서 떼어낼지, C7 attestation만 현행 세대로 재발행할지가 판정이다.
2. **D2 조문과 실행 런북이 정면 충돌한다.** 조문은 대상 DB가 non-production 일회용이고
   production identity와 같으면 즉시 중단하라 하고, 런북은 `E2E_LIVE_ALLOW_PROD=1`과 배포 DB
   `CONFIRM_*` exact 일치를 요구한다. 격리 대안(`run-admin-feature-clone-live-acceptance.sh`,
   18701/18705)은 런북이 없다. 어느 쪽이 정본인가.
3. **attestation 발행을 누가 소유하는가.** 이 파일은 지금 사람이 손으로 쓴다. 생성기를 만들면
   "선언"이 "유도"가 되어 검증의 독립성이 약해진다 — 검증기가 대조할 대상이 같은 코드에서
   나오기 때문이다(이 저장소가 DO NOT 15로 규정한 이중 선언의 반대 방향 위험). 손으로 유지할지,
   유도하되 검증 입력과 분리할지가 설계 판정이다.

## T-VN-41C

**2026-09-06 실측 상태 — 종전 서술 정정.** 다섯 축을 병렬 조사하고 각 발견을 반증에
부쳤다. 원장이 41C를 "reconciliation 구현이 남았다"로 재분류(2026-09-04)한 것은
**근거 사슬이 어긋난 결과**였다: 근거로 인용한 `tasks-done.md` 문장은 reconciliation의
*구현*이 아니라 *live acceptance*를 잔여로 적는다.

| 요구 | 상태 | 근거 |
|---|---|---|
| relay: lease | **구현 있음** | `cache_target_outbox_repo.py` — lease token/만료 컬럼, 상한 300초 상수 |
| relay: retry | **구현 있음** | `nack` → `attempt_count` 증가, `max_attempts=5` 초과·permanent error면 dead 전이 |
| relay: dead-letter | **구현 있음** | 조회/상세/목록 API + ETag |
| relay: replay | **구현 있음** | service·admin 양쪽 endpoint, 격리 live spec이 admin replay를 실제로 클릭 |
| DB 대조 reconciliation | **구현 있음** | 5-status 상태기계(`preparing/running/succeeded/failed/superseded`) 전이 5/5, natural-key head 두 번 server-cursor scan + Merkle root 고정 |
| snapshot concurrency 1 | **구현 있음** | external_system별 lock |
| `429/503 Retry-After` backoff · `413` non-retry | **구현 있음** | 서버 발행 + 소비자 파싱·분류 |
| credential별 gateway limit | **미확인** | 세 저장소에 없다. 저장소 밖(HAProxy 등) 설정일 가능성 — 확인되지 않았다 |

**남은 것 셋.**

1. **런타임 결선.** 배포 Map API 컨테이너에
   `KOR_TRAVEL_MAP_API_CACHE_TARGET_SERVICE_PRINCIPALS`가 **키 자체로 없다**. 배포 토큰으로
   `/v1/service/cache-target-streams/pinvi`를 부르면 401 `CACHE_TARGET_SERVICE_TOKEN_INVALID`
   인 반면 같은 토큰이 `/v1/features`에서는 422다(인증 통과). ops read 표면은 200으로 살아
   있고 그 값이 relay 관계 19개 **전부 0행**임을 보인다 — 이 세대에서 relay가 한 번도 흐른
   적이 없다. Manager `.env`에는 cache-target 키 10개가 **존재하지만** 값이 전부 inert이고
   compose가 어느 컨테이너에도 매핑하지 않는다. 즉 "env가 하나도 없다"는 컨테이너 기준으로만
   참이다.
2. **enable 경계 구현.** PinVi config가 `PINVI_ENVIRONMENT=production`에서 sync enable을
   startup `ValueError`로 거부하며 이유를 스스로 적는다 — "root-owned final C7 enable
   boundary가 구현될 때까지". 그 boundary는 **Manager 저장소에 없다**(Manager 전체에서
   `CACHE_TARGET`은 5개 파일뿐이고 전부 inert 기본값의 정의·검증·생성 상수다).
3. **구조적 순환 — 2026-09-07 소유자 판정으로 (c)를 택했다.** cache-target을 켜면 `.env`
   바이트가 바뀌어 `environment_sha256`이 달라지고 v8 journal 결박이 깨진다. 그런데 다시
   rebuild하려면 Manager `require_rebuildable_mode`가 요구하는
   `_REBUILDABLE_CACHE_TARGET_DEFAULTS`(정확히 그 inert 값들)를 만족해야 한다. **현
   lifecycle(rehearsal/rebuildable)에서 enable과 pinned rebuild는 상호배타다.**

   | 선택지 | 대가 | 판정 |
   |---|---|---|
   | (a) lifecycle을 옮긴다 | pinned rebuild 능력을 잃는다 | 채택 안 함 |
   | (b) Manager가 cache-target 축을 `environment_sha256` 결박에서 분리한다 | Manager 계약 변경 | 채택 안 함 |
   | (c) **enable을 실 production 전환 시점까지 미룬다** | 41C가 그때까지 보류 | **채택** |

   따라서 41C는 **보류**다. n150은 실 production이 아니고 rehearsal/rebuildable lifecycle의
   rebuild 능력이 D1/D2/M01 계열의 실행 수단이므로, 그것을 잃으면서 아직 소비자가 없는
   흐름을 켜는 것은 값이 맞지 않는다. 같은 형식의 선례가 원장에 있다 — `T-VN-H43`이
   "n150은 실 production이 아니며 손상 시 재적재가 정책"이라는 이유로 보류다.

**재개 조건과 그때의 순서.** 실 production 전환이 결정되면 이 절을 그대로 다시 세운다.
남은 다섯 조각은 이렇다:

1. Manager가 cache-target env를 컨테이너에 렌더링한다(현재 `.env`의 10개 키가 어느 compose
   `environment:` 블록에도 매핑돼 있지 않다).
2. Map `KOR_TRAVEL_MAP_API_CACHE_TARGET_SERVICE_PRINCIPALS`에 4역할 registry를 넣는다.
3. PinVi가 기다리는 **root-owned final C7 enable boundary**를 Manager에 구현한다 — 그것이
   없으면 PinVi config가 production에서 sync enable을 startup `ValueError`로 거부한다.
4. PinVi `..._CACHE_TARGET_SYNC_ENABLED`를 켜고 4역할 토큰·3핀을 준다.
5. 그 뒤에 acceptance 다섯 축(누락·중복·restore epoch 전환 live 증명, 호출 cadence)을
   측정한다. 클라이언트측 코드는 이미 있다 — 남은 것은 live 증거이지 구현이 아니다.

**보류 중 유지되는 사실.** relay·reconciliation 구현은 회귀 없이 유지돼야 한다. 그것을
지키는 것은 저장소의 unit/integration 테스트이고, 배포 런타임에서는 ops read 표면이
살아 있어 relay 관계 19개가 0행임을 언제든 확인할 수 있다.

**정정할 두 문장.**

- 본문이 "n150 GC 실측"을 완료로 위임한 근거는 **폐기 세대**(head `0225`)의 것이고,
  재실행 스크립트 `scripts/verify-tvn41c-cache-target-gc.sh`는 5줄짜리 `exit 2` stub이다.
  게다가 그 수치는 `0231`(material/receipt 분리 + `eligible_items` 셈 재작성) **이전**이라
  세대 문제가 아니라 계약 문제다. 다만 D2의 restore 축과 달리 **수행 가능한 형태다** —
  퇴역한 것은 step ① 하나이고 활성 대체물이 있으며 GC 도메인의 스키마·job·schedule은 head
  `303`에서 그대로 유효하다.
- receipt 승격(`pending → candidate_verified`)이 요구하는
  `map_service_openapi_sha256 == pinvi_service_vendor_sha256`은 지금 **성립하지 않는다**.
  저장소의 후보 archive(`contracts/vnext/t-vn-41-candidate-manifest-v1.json`)는 옛 후보
  `77821001`/`e8e0fec`에 핀돼 있고 그 sha는 `c6f9aba6…`인데, 현 트리의
  `packages/kor-travel-map-api/openapi.service.json`은 `99ba6c17…`다.

**표기 주의.** `1-a`/`1-b`/`1-c`는 어느 정본에도 정의가 없다 — 2026-09-04 커밋이 범례 없이
처음 쓴 표기이고 Map·PinVi·ADR·integration-map·contracts 어디에도 대응 문서가 없다. 이
표기로 잔여를 세지 마라.

```markdown
- [~] T-VN-41C — **relay·reconciliation·consumer enable**

  lease/retry/dead-letter/replay가 있는 relay와 DB 대조 reconciliation을 추가한다. backfill checksum
  뒤 critical path 밖에서 PinVi 소비를 enable하고 누락·중복·restore epoch 전환을 live로 증명한다.
  완료된 command scope 분리, snapshot materialization, outbox ordering·GC, n150 GC 실측과 relay
  종결성 회귀는 `tasks-done.md`의 2026-08-25 정합성 이관 항목이 소유한다.
  - [~] PinVi command writer가 CAS source GET과 refresh `Location` polling에서 consumer credential로
    전환하고, restore clone은 sync disabled 상태에서 immutable pre-CAS receipt를 써 응답 유실 exact replay까지
    완료한다. 동일 key의 병렬 `201`/`200`도 terminal payload·ETag가 같으면 한 durable receipt로 수렴한다.
    T-VN-41S로 Map service OpenAPI SHA가 바뀐 뒤 PinVi #465가 service/full-admin exact vendor를
    새 Map artifact에 다시 고정했고, Docker-manager #207이 당시 H300 v5 source pinset과
    canonical digest `14a9a512836a48489146dc2bb0a04de309cf451b274b934d79805d171f83a193`를
    병합했다. Docker-manager #219는 PinVi #477 squash source를 다음 후보 pinset으로 별도
    회전했다. 따라서 남은 isolated live acceptance는 새 후보가 committed된 exact pair에서만
    진행한다.

    **조사 기록(2026-08-21) — service spec `410` 선언(T-VN-41S에서 이월)과 당시 대응안.**
    아래의 “아직/막는 것” 표현은 조사 당시 상태를 기록한 것이며, 현재 반영 상태는 마지막 문단을 따른다.

    - 바뀌는 산출물은 **셋**이다. `openapi.service.json`, `openapi.json`(전체 spec도 service
      route를 담는다), 그리고 그 둘에서 생성되는 admin frontend `src/api/types.ts`
      (`.github/workflows/frontend.yml`의 `gen:types:check`가 gate한다). `openapi.user.json`은
      그대로다.
    - 재생성은 서버·DB 없이 된다:
      `python packages/kor-travel-map-api/scripts/export_openapi.py --profile all --output ... --user-output ... --service-output ...`
      `openapi-drift` CI가 같은 명령을 `--check`로 돌려 문자열 비교하므로 재생성본을 함께 커밋해야 한다.
    - **PinVi를 먼저 머지한다.** PinVi의 `contract-pin-consistency`는 `map_release_revision`을
      full SHA로 checkout하므로 **미머지 Map 브랜치에서도 vendoring이 성립한다**(실제로 PinVi가
      Map main에 없는 `037e2469`를 핀하고 있다). Map을 먼저 올리면 `pinvi_service_vendor_sha256`에
      PinVi main이 갖고 있지 않은 해시를 적게 되어 계약이 거짓이 된다.
    - **당시 함께 고쳐야 할 것 — spec이 거짓을 말했다.** `0229`~ 이후 코드가 강제하는 admission
      상한은 `item 500,000 / material 56 MiB`인데, route docstring 3곳
      (`routers/cache_target_streams.py`)과 거기서 생성된 두 spec은 당시
      `1,000,000 / 512 MiB`라고 적었다. 누락이 아니라 **틀린 서술**이었고, 소비자가 읽을 수 있는
      유일한 문서였다. 이 문제는 #1051에서 `410` 선언과 함께 Map service/full spec 및 admin
      타입을 재생성해 해소했다.
    - **당시 막힘 셋(현재 반영 상태는 마지막 문단 참조).** 당시 (1)만 truthfulness 문제였고
      (2)(3)은 spec bytes가 움직이는 순간 바로 red가 되는 hard gate였다.
      1. `contracts/vnext/tvn40-live-acceptance-v1.json`이 T-VN-40 receipt의
         `map_commit`/`pinvi_commit`과 결박돼 있는데 당시 `pending` 가드가 없었다. receipt는
         `complete`이고 `map_commit`의 spec 해시는 옛 값이라, spec을 바꾸면 그 주장이 거짓이 됐다.
         대응안은 (a) 새 pair로 n150 paired live acceptance를 재실행해 재봉인하거나 (b) 교차 결박에
         `state == "complete"` 가드를 두고 T-VN-40을 `pending`으로 되돌리는 것이었다.
      2. 당시 `tests/unit/test_vnext_contract_artifacts.py`가 세 spec 파일 해시를 T-VN-40
         deployment receipt와 대조했으므로 spec 변경 시 receipt 갱신이 필요했다.
      3. 당시 같은 파일이 T-VN-41 receipt의 `map_service_openapi_sha256`를 현재 tree 해시 및
         `pinvi_service_vendor_sha256`와 **`pending` 갈래에서도** 등치시켰다. 그래서 PinVi를
         먼저 머지해야 한다고 판단했다.

    active paired receipt는 `pending`으로 되돌렸으며, 기존 `77821001`/`e8e0fec` 후보 archive·image·Live UI
    증거는 이전 service bytes의 이력일 뿐이다. Map 쪽은 이번 PR에서 실제 runtime 410 선언과 상한 설명을
    service/full spec에 반영했고, PinVi #465 vendor 병합·적대 재리뷰·CI는 완료됐다. 새 exact pair의
    Docker-manager pinset과 n150 isolated evidence를 통과한 뒤에만 `candidate_verified` 승격과
    후속 reconciliation/cutover로 진행한다.
  - [~] Map/PinVi exact head로 n150 isolated live UI recovery와 최종 prod gate를 통과한다.
    **선행: `T-VN-FINAL-REBUILD`** — 현 candidate의 v6/v8 문서가 없으면 새 live runner가 읽을 attested
    input 자체가 없다(사용자 결정 2026-08-20으로 주요 개발 완료 후로 미뤘다).
    후보 Live UI recovery와 `blocked → ready` stream/replay/reconciliation 결박은 통과했다. 최종 prod
    gate는 별도 final main C7·production consumer enable 경계이며, PinVi system별 snapshot concurrency 1,
    `429/503 Retry-After` backoff, `413` non-retry, credential별 gateway limit 또는 동등한 외부 rate-limit과
    실제 호출 cadence를 함께 증명한다.

### T-VN-41F1J — C6c cancel-probe fixture 수명주기 복구

> 2026-08-06 F1D의 `cancel=404`는 Manager/PinVi read·cancel relay 문제가 아니라, 정적
> `KTDM_C6C_CANCEL_PROBE_JOB_ID`에 대응하는 Map import job이 없다는 실측으로 판정했다.
> fixture 생성·소비·종결과 durable 상태는 Map이 소유하고, Manager는 service OpenAPI로
> transaction ID만 전달한다. PinVi에는 기존 `ops:cancel` 외 권한을 주지 않는다(ADR-084).
```

**2026-09-07 조사 — 구현 위치를 여기 박아 둔다.** relay·reconciliation은 구현이 끝나
있다: lease·retry·dead-letter·replay 4/4가 `cache_target_outbox_repo.py`에, 5-status
상태기계와 DB 대조(server-cursor scan 2회 + Merkle root)가
`cache_target_reconciliation_repo.py`에 있고 라우터가 끝까지 부른다. 종전에
`docs/tasks.md` 한 줄이 이 사실을 들고 있었으나 규약 §5 정리로 여기로 옮겼다.

## T-VN-M02

```markdown
- [~] **T-VN-M02 — origin 보존과 불변** (결정 4, 구현 병합). #1029의 `0227` provenance reader,
  immutable claim/origin ACL과 named hard-purge fence, unit/integration 회귀가 정본이다.
  ~~evidence를 남긴 상태에서의 purge 정책·backup/restore 실측 및 live acceptance가 남아
  있다.~~ **2026-09-08 정정 — 셋 중 둘은 이미 이 절의 것이 아니다**(아래 §잔여 참조).
  남은 것은 live acceptance 하나다. PinVi M05 paired
  attestation이 소비하는 Admin provenance 최상위 identity는 opaque `feature_id`와 별도 `feature_uuid`를
  함께 반환해야 하며, UUID-only projection을 재사용하지 않는다. reader/immutable claim UUID는 모두
  최상위 `feature_uuid`와 같지 않으면 fail-close한다. PinVi consumer도 이 반환 UUID를 M05 case의
  manual/old UUID와 각각 대조하기 전에는 paired live receipt를 승격할 수 없다.
```

**2026-09-07 전수 조사 — spec이 미병합 브랜치에만 있다(유실 위험).**

live acceptance spec은 `origin/feat/m01-m02-live-acceptance`에만 있고 main에는 없다
(main 대비 **64 behind / 2 ahead**, 2파일 +138줄). 그 브랜치가 정리되면 작업이
사라진다 — **회수가 가장 먼저다.** 병합만으로는 닫히지 않는다: spec은
`E2E_MANUAL_CREATE_WRITE=1` opt-in 격리 스택 전용이라 기본 skip이다.

이 절이 세는 것 중 **backup/restore 축은 이 항목의 것이 아니다** — §T-VN-M01이 그 축을
자기 전제에서 빼면서 `T-VN-H49` 계열로 넘겼다. 이 절만 계속 세고 있어 과대 계상이다.

**소유자 판정** 둘: purge 정책(evidence cascade/orphan·권한·409 계약)과
backup/restore 소유권.

**2026-09-07 소유자 판정 — 과대 계상분을 삭제한다.**

이 절이 세던 **backup/restore 축은 이 항목의 것이 아니다.** §T-VN-M01이 그 축을 자기
전제에서 빼면서 `T-VN-H49` 계열로 넘겼는데 이 절만 계속 세고 있었다. 소유자 판정으로
이 절의 범위에서 삭제한다 — 소유는 `T-VN-H49`(+ 자식들)이다.

**이 절에 남는 것은 둘이다.**

1. **live acceptance spec 회수** — spec이 `origin/feat/m01-m02-live-acceptance`에만
   있고 main에 없다(main 대비 64 behind / 2 ahead, 2파일 +138줄). 브랜치가 정리되면
   작업이 사라지므로 판정과 무관하게 먼저 한다. 회수해도 닫히지 않는다: spec은
   `E2E_MANUAL_CREATE_WRITE=1` opt-in 격리 스택 전용이라 기본 skip이다.
2. **purge 정책** — evidence cascade/orphan·권한·409 계약. **소유자 판정 대기.**

**2026-09-07 소유자 판정 — purge 정책을 `T-VN-H49` 계열로 이관한다. 이 절에는 live
acceptance 축만 남는다.**

**2026-09-08 잔여 정정 — 이 절이 세던 셋 중 둘이 해소됐는데 문장이 따라가지 않았다.**

| 이 절이 잔여로 적던 것 | 실제 |
|---|---|
| purge 정책 | **닫혔다** — 2026-09-08 소유자 판정과 migration 306(§T-VN-H49) |
| backup/restore 실측 | **이 항목의 것이 아니다** — 2026-09-07 판정으로 `T-VN-H49` 계열 |
| live acceptance spec 회수 | **끝났다** — spec이 main에 있다(`packages/kor-travel-map-admin/frontend/e2e/live/admin-manual-feature-create.live.spec.ts`) |
| live acceptance **실행** | **유일한 잔여** |

**그 하나가 막힌 이유는 셋이고, 그중 하나는 306이 절반 풀었다.**

1. prod에서 돌리면 안 된다 — prod UI가 `admin`이라 spec의
   `created_by_actor === "e2e-admin"`이 구조적으로 실패한다. 이 축은 그대로다.
2. ~~cleanup이 없어 지워지지 않는 write가 남는다~~ — **306이 풀었다.** 그 되돌릴 수
   없음은 hard-purge fence가 유일한 삭제 경로를 거부해서 생긴 것이었고, 이제 감사되는
   `feature.purge_manual_feature`가 있다. 다만 1번 때문에 여전히 prod에서 돌리지 않는다.
3. 격리 스택이 **사라졌다**(2026-09-08 실측). `~/ktm-live-301`은 정지가 아니라
   컨테이너도 볼륨도 없고, 체크아웃은 alembic head `302`(저장소는 `307`)이며 `e2e/live/`에
   그 spec 자체가 없다. **재기동이 아니라 재구축이 선행이다.**

그리고 spec은 `E2E_MANUAL_CREATE_WRITE=1` opt-in이라 병합만으로는 돌지 않는다.

**왜 이관인가 — 순서 때문이다.** hard-purge fence의 무조건 거부는 코드가 스스로
**잠정**이라고 적는다(`tests/integration/test_tvn_m01_manual_feature_create.py:180`
"restore proof가 생기기 전에는"). 되돌릴 수 없는 삭제 경로를 restore proof보다 먼저
여는 것은 순서 역전이고, 그 restore proof를 소유하는 곳이 H49다. purge는
backup/restore가 갚히기 전에는 **원리적으로 판정할 수 없다.**

**상세검토 결과 — 구현 축은 전부 충족이다(2026-09-07 4축 실측 + 반증).**

| 조건 | 상태 |
|---|---|
| `0227` provenance reader | 충족 — main + n150 prod DB 실측 |
| immutable claim / origin ACL | 충족 |
| named hard-purge fence | 충족 — `trg_features_manual_feature_hard_purge_fence` → `feature.reject_manual_feature_hard_purge()`, prod 배포·enabled |
| unit/integration 회귀 | 충족 — 정적 계약 2 + router unit 5 + 실 PostGIS 통합 1 |
| PinVi 소비자 계약 3조건 | 충족 — 응답이 최상위 `feature_id`(opaque)와 `feature_uuid`를 required로 병행, 불일치 시 `AdminManualFeatureInvariantError` fail-close, PinVi `_m04_server_side_chain`이 두 축을 M05 case의 manual/old와 **각각** 대조한 뒤에만 승격. `/root/pairv2-e2e-03`가 `m04_map_feature_uuid` + `m04_server_side_chain_verified: true`를 담고 `status: passed` |

**미병합 브랜치 둘의 처분(실측 확정).**

- `feat/tvn-m02-origin-immutability` — **회수 대상이 아니다.** tip 트리 해시가 병합된
  #1029(`57c9d99a`)와 동일하고(`c388f52b…`) 두 커밋 사이 `git diff --stat`이 빈 출력이다.
  38개 고유 커밋 전부가 squash로 들어갔다. 지워도 잃을 것이 없다.
- `feat/m01-m02-live-acceptance` — **spec 파일만 회수했다.** 그 spec은 저장소 전체에서
  그 브랜치에만 있었고(전 리모트 스캔 결과 1개), main의 어떤 live spec도
  `/creation-provenance`를 부르지 않았다. 같은 브랜치의 문서 커밋(`f14c58c1`)은
  가져오지 않았다 — 빈 ```` ```markdown ```` 펜스 2줄을 넣는 흠이 있고, 본문이 주장하는
  잔여 조건(fresh restore·backup/restore)은 2026-09-06/09-07 판정으로 이미 무효다.

**이 절에 남는 조건 — 하나.**

- [ ] **live acceptance 실행** — `admin-manual-feature-create.live.spec.ts`가
  `E2E_MANUAL_CREATE_WRITE=1`로 격리 스택에서 완주한다. **배포 prod에서 돌리지 않는다**
  — prod UI는 `KOR_TRAVEL_MAP_UI_ADMIN_USERNAME=admin`이라 spec의
  `created_by_actor === "e2e-admin"` 단언이 구조적으로 실패하고, spec은 cleanup을 하지
  않아 지워지지 않는 write를 prod DB에 남긴다.

  **왜 지워지지 않나(2026-09-08 규명).** admin API의 `DELETE /{feature_id}`는 soft
  `action="retire"`이고 hard purge는 `trg_features_manual_feature_hard_purge_fence`가
  거부한다. 즉 이 항목의 prod 불가는 `T-VN-M02-TRUNCATE-FENCE`와 **같은 fence**에서 온다 —
  두 항목을 따로 판정하면 안 된다.

  실행처는 n150 `~/ktm-live-301`이다. ~~그 스택은 이미 `e2e-admin`·create token·flag가
  spec과 맞다(현재 정지 상태 — 재기동이 선행한다).~~ **2026-09-08 재실측 — 정지가 아니라
  없다.** 컨테이너도 볼륨도 존재하지 않고(`ktm-live-301-pg` 부재, `ktm_live_301` 볼륨 부재),
  그 체크아웃은 alembic head **302**(저장소는 305)이며 `e2e/live/`에 해당 spec 자체가 없다.
  설정 산물(`~/.ktm-live-301-admin-pw`, `.env`, `live301-start.sh`)과 runner 이미지는
  남아 있으므로 재구축은 가능하지만 **재기동이 아니라 재구축이 선행이다.**

## T-VN-H49

```markdown
- [~] T-VN-H49 — **주기 실행·bounded retention·off-box 증거 완성**

Map 인스턴스의 baseline 3건과 절차 문서화, Docker Manager #177의
6-role standalone backup primitive, Geo application DB의 앱 레벨 schedule env 결선
(PR #181, merge `969eff18`)까지 완료했고 #177도 닫혔다. 그러나 이 task의
운영 AC인 주기 실행·bounded retention·off-box 증거는 남아 있다.

- [x] Geo application DB 첫 자동 백업은 4.71 GB artifact와 sha256 verify까지 성공했다.
  `scheduled_backup`과 retention janitor가 최근 성공·bounded retention으로 수렴하는지가
  남아 있었고, **2026-09-11 실측으로 닫혔다.** application DB에 standalone cron을
  중복 설치하지 않는다.

  `/home/digitie/kor-travel-geo/data/backups`에 **09-07·09-08·09-09·09-10 네 건이
  연속으로** 있다(각 ~4.39 GB, `kor_travel_geo_backup_<ts>_zstd3.tar.zst`). 그리고
  2026-09-08 시점에 남아 있던 08-24·08-25는 **지금 없다** — TTL 7일이 지난 뒤
  `keep_min=3`을 새 성공들이 채우자 GC가 실제로 지웠다. "수렴"과 "bounded retention"이
  둘 다 관측으로 성립하므로 이 조문을 닫는다. 남은 것은 off-box 사본뿐이고 그것은
  `T-VN-H49-OFFBOX`가 소유한다.
- [x] 별도 `geo_dagster` metadata DB(`T-VN-H49-GEO-DAGSTER`)와
  concierge(`12600`, `T-VN-H49-CONCIERGE`)·pinvi(`12800`, `T-VN-H49-PINVI`)에 standalone
  create → sha256 검증 → list → GC를 실행하고 cron/systemd timer 및 최신 dump + sha256 +
  manifest 증거를 남긴다.
- [ ] off-box 사본 자동화를 결선한다(`T-VN-H49-OFFBOX`). Map application/Dagster 주기화는
  #148의 재적재 정책 결정을 따르며 이 task가 임의로 활성화하지 않는다.
- [ ] 위 운영 AC를 닫은 뒤 ~~`docs/backup-restore.md` §1의~~ 외부 instance 경고를
  현행화한다(`T-VN-H49-OFFBOX`). **2026-09-08 정정 — 그 §1은 존재하지 않는다.**
  `b2543d68`이 그 파일을 1020줄 → 94줄로 줄이면서 번호 절을 통째로 없앴다(현재 제목은
  전부 무번호다). 갱신 대상은 그 파일의 §현재 지원 범위와, `b2543d68`이 지운 원문을
  되살린 `docs/archive/backup-restore-pre-300.md`의 헤더다.

AC: 필요한 외부 DB마다 최신 dump + sha256 + manifest, 주기 실행과 보존 GC, off-box 사본
증거가 있고 절차가 문서화되어야 한다. PR #181 병합만으로 H49를 완료 처리하지 않는다.

**2026-09-08 실측 — 자식 셋은 충족, geo 부모는 아직 하나가 모자란다.**

`geo_dagster`·`concierge`·`pinvi` 셋 다 `digitie` crontab으로 매일 돌고 **2026-08-21 →
2026-09-08, 19/19 성공·오류 0**이다. GC도 실제로 지운다(각각 18·14·15회). dump +
`.sha256` + `.manifest` 삼종이 보존 정책대로 남아 있다(각 4·7·7건, keep 4·7·7). 이
조문이 요구한 "주기 실행과 보존 GC"가 실측으로 성립하므로 **충족 처리한다.**

geo application DB는 다르다. 예약 artifact가 셋(08-24, 08-25, **09-07**)인데 그중
2026-09-07 것만 디스크 부족 해소 **뒤**의 성공이다. **bounded retention은 이미
보인다** — TTL 7일이 지난 08-24·08-25가 `keep_min=3` 때문에 남아 있는 것이 정확히 그
정책의 동작이다. 남은 것은 "최근 성공으로 수렴한다"뿐이고 그것은 **작업이 아니라
기다림**이다(하루 1회, 2회 더).

**hard purge 정책은 2026-09-08 판정·구현으로 이 계열에서 빠졌다**(migration 306).
이 절에 남는 것은 위 geo 수렴과 off-box 결선 둘이며, **후자만 소유자 판정 대기**다.

**2026-09-07 전수 조사 — 자식 셋은 즉시 착수 가능, 부모는 prod 쓰기에 막혀 있다.**

`-GEO-DAGSTER`·`-CONCIERGE`·`-PINVI`의 유일 잔여는 **복원 리허설 1회와 그 기록**이다.
`ktdctl db-backup rehearse-restore <instance>`로 각 1회 돌리면 되고, cron 시각
(03:15/03:30/03:55 UTC)은 `_role_lock` 충돌 때문에 피한다.

부모(geo application DB)는 고착된 queued `load_jobs` 행 해소가 필요하고 그것은 prod DB
쓰기 또는 geo admin API 호출이다 — 소유자 승인이 선행한다.

원장이 세지 않던 운영 결함 하나: `/opt/kor-travel-docker-manager/.env`에
`KTDM_BACKUP_ROOT`가 없어 trusted installer의 `install_backup_logrotate()`가 skip됐고
`/etc/logrotate.d/kor-travel-docker-manager`가 설치되지 않았다. `-OFFBOX`에서 함께
닫는다.

`-OFFBOX`의 잔여는 코드가 아니라 **운영 결선**이다 — 목적지 호스트·계정·ssh 키가
소유자/운영자 몫이고(Manager GM-08 문서가 그렇게 규정한다), 그 뒤는 env 4개와 root
crontab 한 줄(04:45 UTC)이다.

**기록 위치가 미정이다.** 자식들의 E4는 "docs/backup-restore*"에 남기라고 적지만 Map의
그 파일은 94행으로 축소돼 외부 instance 절차를 담지 않고, 스스로 "n150 운영 backup은
Docker Manager runbook이 정본"이라고 위임한다. 어디에 쓸지가 소유자 판정이다.

**2026-09-07 소유자 판정 — manual Feature hard purge 정책을 이 계열이 수납한다.**

§T-VN-M02에서 이관됐다. **근거는 순서다** — hard-purge fence의 무조건 거부는 코드가
스스로 잠정이라고 적고("restore proof가 생기기 전에는",
`tests/integration/test_tvn_m01_manual_feature_create.py:180`), 그 restore proof가
이 계열의 축이다. 되돌릴 수 없는 삭제 경로를 restore proof보다 먼저 열 수 없다.

**현재 상태는 "정책 미결"이 아니라 purge 경로가 없는 것이다(2026-09-07 실측).**

- 저장소 전체에 `feature.features`를 지우는 제품 코드가 **0건**이다.
  `DELETE /v1/admin/features/{id}`는 `action="retire"` 상태전이다.
- DELETE 권한을 가진 로그인 역할은 `ktm_feature_migrator`(→ `ktm_feature_schema_owner`)
  하나뿐이고 API/Dagster 런타임 역할에는 없다.
- fence는 prod에 배포·enabled이지만 그 DB가 `feature.features` 0행이라 런타임으로
  발화한 적이 없다.

**restore proof가 갚힌 뒤 판정할 것 — 셋.**

1. manual Feature hard purge를 **제품 기능으로 열 것인가.**
2. 연다면 claim/origin을 남길 것인가(= exact 예약
   `uq_manual_feature_identity_claims_exact`가 영구 tombstone이 되어 같은 이름·좌표
   재생성이 차단된다), 아니면 append-only 불변을 조건부로 깰 것인가(ADR-093의 핵심
   결정을 뒤집는 새 ADR이 필요하다).
3. 거부의 HTTP 의미. 현재 `ck_manual_feature_purge_not_ready`는
   `_ADMIN_STATE_CONFLICT_CONSTRAINTS`/`_ADMIN_STATE_VALIDATION_CONSTRAINTS` 어디에도
   없어, 라우터 경로로 도달하면 409가 아니라 **catch-all 500**이 된다. 같은 종류의
   사고가 `ck_features_state_tuple`에서 한 번 있었다고 코드 주석이 기록한다.

**2026-09-08 소유자 판정 — 셋 다 결론이 났다(migration 306).**

**질문 셋 중 둘은 이미 좁혀져 있었다.** Q2는 ADR-093이 두 번 답했다("claim은 Feature
purge 뒤에도 append-only로 남는다" §41, "purge 뒤에도 evidence가 남는다" §150) — 스키마
주석도 claim·origin에 `features` FK를 **의도적으로** 두지 않은 이유를 그렇게 적는다.
"남기지 않는다"는 답은 ADR-093 핵심 결정을 뒤집는 새 ADR을 요구하고 그럴 이유가 없다.
Q3은 정책이 아니라 결함이었다(아래 별도 항).

**Q1 — 연다. 단 UI 버튼이 아니라 자기 복구점을 남기는 운영 명령으로.**

`retire`가 이미 있는 일(오류·중복·품질)에는 쓰지 않는다. purge는 **행이 존재하면 안 되는
경우**로 한정한다. UI 버튼으로 열면 `retire`가 맡아야 할 일이 이쪽으로 샌다.

**소유자가 건 순서 전제는 문자 그대로는 아직 안 맞는다.** "되돌릴 수 없는 삭제 경로를
restore proof보다 먼저 열 수 없다"였는데, M05-2 C·D가 증명한 것은 **복원 메커니즘**이지
복원할 대상이 있다는 것이 아니다 — `map_application`은 어느 주기 백업에도 없고(H43 보류)
restore/swap은 300 baseline 정책으로 닫혀 있다. 그래서 **purge가 자기 복구점을 들고
다니게** 했다: 지우기 전에 cascade로 사라질 행을 전부
`feature.manual_feature_purge_records`에 담는다. 이 우회를 소유자가 승인했고, 그 덕에 이
항목이 H43 보류에 묶이지 않는다.

담을 relation은 `pg_constraint`에서 런타임에 유도한다 — 목록을 박으면 자식이 늘 때마다
갱신을 잊는 순간 purge가 **조용히 데이터를 잃는다**(DO NOT 15).

**Q2 — 남긴다. 다만 tombstone을 관리 가능하게 만든다.**

claim의 두 역할을 나눈다: `purged_by_command_id`(purge 승인 — fence가 이것을 본다)와
`identity_released`(예약 해제 — purge의 **명시 파라미터**). exact 유일성은
`WHERE NOT identity_released` 부분 인덱스가 된다. 해제가 없으면 "잘못돼서 지웠으니 같은
자리에 제대로 다시" 가 영원히 막히고, 그때 복구 수단은 감사 없는 DBA 수술뿐이다.

`mistaken_creation`은 보통 해제하고 payload를 담는다. `erasure_required`는 보통 **쥐고**
payload를 담지 **않는다** — 담으면 삭제의 목적이 무너진다. 두 동기가 정반대를 원하므로
기본값을 두지 않고 운영자가 의도를 말하게 한다.

**append-only 완화 한 줄이 함께 간다**(소유자 승인): claim의 트리거가 저 세 컬럼의
**단조 전이 하나**만 허용한다. 증거 필드는 여전히 불변이고 전이는 command가 원인이라
감사된다. ADR-093에 한 문장을 박았다.

**RESTRICT는 막는 것이 맞다.** `manual_provider_dedup_cases`·
`feature_reference_reconciliation_events`·`theme_feature_candidates`가 이 Feature의
identity를 불변 증거로 인용한다. 다만 raw 23503으로 죽으면 이유를 못 말하므로 프로시저가
먼저 조회해 **무엇이 막는지 이름을 대는** 거부를 낸다.

**definer는 schema owner다.** 이 명령은 본질적으로 `feature.features`의 cascade 자식
전부를 읽고 지운다. 좁은 owner에게 그만큼을 GRANT로 주면 목록이 드리프트하므로, 권한이
아니라 **도달 가능성**으로 좁힌다 — EXECUTE를 PUBLIC에서 회수하고 아무에게도 주지 않는다.

**T-VN-M02와 같은 fence다.** M02 live acceptance의 "지워지지 않는 write"는 바로 이 fence가
유일한 삭제 경로를 거부해서 생긴다. purge가 열리면서 그 cleanup 이야기가 함께 풀린다.

**n150 실측이 잡은 것 넷.** `ON CONFLICT ON CONSTRAINT`가 partial unique index를 가리킬 수
없어 생성 경로 셋이 깨졌고(그중 하나는 302가 이미 교체한 프로시저라 baseline에서 뽑았으면
302를 되돌릴 뻔했다), `::regclass`가 `search_path` 상대라 복구점 키가 스키마 없이
저장됐고, 새 relation은 runtime ACL 선언 없이는 배포되지 않았고, 좌표 index 상한을 두 번
넘겼다. 변이 11축 전부 RED(그중 둘은 처음에 공허해 판별 가능한 축으로 고쳤다).

**아직 아닌 것.** HTTP 라우트는 만들지 않았다 — 제안이 "UI 버튼이 아니라 운영 명령"이었고
호출부는 `kortravelmap.infra.manual_feature_purge_repo`다. 운영 스크립트가
`admin.manual-feature.purge.v1` command를 열어 부른다.

**Q3 — 정책이 아니라 결함이었고, 그 구멍은 한 이름짜리가 아니었다.**

admin state 경로에서 도달 가능한 제약 23개 중 **14개가 분류돼 있지 않았다.** 그중 넷은
프로시저가 명시적으로 raise한다. 그리고 코드 주석이 근거로 인용한 fail-close 테스트
`test_admin_state_error_mapping_names_exist_in_ddl`은 **저장소에 없었다**.

세 집합으로 분류를 강제한다 — conflict(409) / validation(422) / unexpected(버그, raw
재던짐). 셋째는 동작을 바꾸지 않는다. "이건 버그다"라는 **판단**과 "분류를 잊었다"를
구별하려고 있고, 그 구별이 없는 것이 2026-08-12 사고의 구조적 원인이었다. 게이트는 이름을
박지 않고 baseline schema에서 폐포를 유도한다(진입 프로시저 → 호출 추적 → raise되는 이름 +
쓰는 relation의 CHECK). purge 경로에는 같은 모양의 게이트를 처음부터 붙였다.

**분류 하나를 실 DB로 재 보고 되돌렸다.** `ck_feature_reactivation_explicit`를 conflict로
넣었는데, `reactivate_admin_feature_state`가 `reactivation_evidence`를 항상 넣고 patch는
lifecycle_state 변경을 호출부에서 막아 **admin 경로로는 도달할 수 없다.** unexpected로
옮겼다 — 도달 불가능한 값을 conflict로 등록해 두면 "구분되고 있다"는 오해가 남는다.

**2026-09-07 — 자식 셋의 복원 리허설을 실행했다. 셋 다 `verified: true`.**

기록 위치는 소유자 판정으로 **Manager `docs/docker-management.md`**다.

| role | backup | 리허설 | alembic head | 복원 크기 |
|---|---|---|---|---|
| `pinvi` | 기존(2026-08-25) | `verified: true` | `20260821_0061` | 12,104,163 B |
| `geo_dagster` | 이번에 생성 | `verified: true` | `29b539ebc72a` | 59,847,139 B |
| `concierge` | 이번에 생성 | `verified: true` | `20260901_0029` | 78,918,115 B |

**그 리허설은 그동안 한 번도 성공한 적이 없었다** — `docker cp`가 host 소유권
(`root:root 0600`)을 보존하는데 `pg_restore`는 컨테이너 `postgres`(uid 999)로 돈다.
이 셋의 마지막 해제 조건을 막고 있던 것은 원장이 적은 무엇도 아니라 **그 결함**이었다
(Manager #324).

**부모 절의 전제가 성립하지 않는다(2026-09-07 실측).** ~~`geo_dagster`·`concierge`는
백업 0건이라 `create`가 선행해야 했다.~~ **2026-09-08 정정 — 아래 §측정 오류 참조.**
root crontab 없음, backup systemd timer 없음, logrotate 미설치는 사실이다.
그리고 geo application DB의 backup은 **2026-08-25 이후 실패했다** —
`db_backup` job이 디스크 부족으로 7연속 실패(`db=33.9GB × 1.3 = 44.1GB` 요구, 여유
29.8~36.0GB)한 뒤 마지막 job이 `queued`로 12일간 고착됐다. 소유자 승인으로 빌드 캐시와
과거 격리 실행 이미지를 정리해 여유를 49GB → **119GB**로 올리고 그 고착 행을 만료
처리했다. 즉 원장이 적은 "고착 행 해소"는 **증상 처리**였고 원인은 디스크였다.

## T-VN-H43

```markdown
- [~] T-VN-H43 — **prod 백업 체계 수립 (정기 dump·sha256·보존·rollback 기준선)**

  절차 정본은 `docs/backup-restore.md` §9(2026-08-05 신설 — n150 수동 기준선,
  TCP 경로 강제·manifest 필수 항목 `ops.public_api_keys` 포함).

  완료된 기준선 dump·배포 후 기준점·외부 사본·신규 DB 프로비저닝 문서화는
  `tasks-done.md`의 2026-08-25 정합성 이관 항목이 소유한다.
  - [보류] 정기화 — 보존 정책·주기 실행·2차 외부 사본 자동화는 **현 환경에서
    수행하지 않는다**. n150은 실 production이 아니며 손상 시 재적재가 정책이다
    (사용자 지시 2026-08-06). 복원 가능성 자체는 H44가 실증했으므로 열린
    리스크가 아니다. 실 prod 전환 시 manager **#148**(일 1회 dump+sha256+
    manifest·retention·오프박스 반출·배포 직전 fence dump)로 재개한다.

## T-VN-QUOTA-ARITHMETIC

```markdown
- [ ] T-VN-QUOTA-ARITHMETIC — **쿼터에 대해 저장소가 하는 진술 대부분이 근거가 없다**
```

**왜 이 task가 있나.** 형제 저장소 `kor-travel-weather`가 2026-09-12에 정지 원인을
확정했다(커밋 `a0c4dbb`) — 번역하지 않고 인용한다:

> **It was arithmetic, not a hang.** Each external provider swept 1,428 locations with
> one request each, hourly, against free tiers it exceeded by up to **43x**. Throttled,
> a request took **12-17s instead of ~0.3s**, so a *successful* sweep ran **4-13
> hours** — work arriving every hour that takes six to finish can only end one way.

그 뒤 Map을 같은 기준으로 쟀다(3렌즈 감사: 요청량 · 쿼터 · 적합).

**Map의 활성 schedule 산술은 성립한다 — 방어 장치가 아니라 순회 모양 때문이다.**

weather는 **지점당 1요청**으로 훑었다. Map의 상시 고빈도 경로는 전부 집계/bulk
endpoint다 — krex 교통공지 R=2~5, 휴게소 기상 R=1(전국 snapshot), 유가 R≈1,
krforest 3종 R≈1~2. weather와 같은 모양은 KMA 격자 3종뿐이고 그것은 2026-09-09부터
`DISABLED_FEATURE_LOAD_SCHEDULES`로 제거돼 있다. 나머지 27개는 월간이고, 요청당
17초를 대입해도 최악 봉투가 전역 상한의 65%다.

**weather와 구조적으로 다른 것 둘.**

1. **실패 모양.** weather의 vendor는 throttle했다 — run이 *살아서 일하므로* 회수되지
   않고 쌓였다. data.go.kr은 느려지지 않는다: resultCode 22를
   `failure_kind="quota", retryable=False`로 즉시 올린다. Map의 쿼터 초과는 조용한
   큐 포화가 아니라 **시끄러운 즉시 실패**다.
2. **큐 포화가 구조적으로 막혀 있다.** 고빈도·disabled schedule 전부
   `coalesce_active_runs=True`라 한 job이 슬롯 1개를 넘길 수 없다. weather의 "ten runs
   sat STARTED"는 재현되지 않는다 — 재현 가능한 것은 그쪽의 *다른* 증상, **tick이
   생략되고 데이터가 갱신되지 않는 것**뿐이다.

**무엇이 참이면 닫히는가.**

1. [x] **분모가 기록돼 있다.** (2026-09-13) 각 data.go.kr 활용신청의 실제 일일 트래픽 한도가
   상한 옆에 **나눗셈과 함께** 적혀 있다. 지금 그렇게 된 상한은 OpiNet 하나뿐이고,
   활성 schedule 32개 중 31개에 대해 그 분모가 존재하지 않는다.
2. [x] **분자가 있다.** (2026-09-13) upstream 진입점 **39개 중 34개**가 요청을
   전부 세고, 그 수가 `upstream_requests_min`으로 asset output metadata에 실린다.
   못 세는 둘은 upstream 요청이 아예 없고(번들 정적·로컬 sqlite), 나머지 둘은
   **부분 계측**으로 선언돼 있다(OpiNet bbox enumerate — provider가 격자 셀마다
   부르는데 그 셀 수가 provider private).

   **배선이 없던 것이 이 조문이 오래 열려 있던 이유였다.** fetcher가 generator라
   "세는 자리"와 "내보내는 자리" 사이에 값을 흘릴 인자가 없었다.
   `kortravelmap.dagster.upstream_requests`가 `ContextVar`로 그것을 대신하고 asset
   경계가 계수기를 연다 — provider fetcher 19곳의 시그니처를 하나도 바꾸지 않는다.
   합치는 자리는 `etl._add_output_metadata` 하나뿐이다(이 패키지의 유일한 metadata
   초크포인트).

   **첫 판은 배선만 맞고 커버리지가 없었다(적대 리뷰 blocker).** 계수기는 asset
   35개 전부에서 열리는데 세는 자리는 셋뿐이라, OpiNet처럼 수천 건을 쓰는 경로가
   `upstream_requests_min: 0`을 냈다 — 하필 **호출량이 가장 크면서 일일 한도는
   아직 실측하지 못한** provider다. 분자가 유일한 가시성인데 그것이 0이었다.
   그리고 그때의 구조 검사는 wrapper가 항상 열어 **항진명제**였다(같은 실패 형태를
   그날 네 번째로 반복했다).

   고친 것 셋. (1) 계수기가 **한 번도 기록되지 않았으면** `None`을 돌려준다 —
   계측되지 않은 fetcher가 0으로 위장하지 못한다. (2) 세지 않던 경로를 계측했다 —
   OpiNet은 `_OpinetCallBudget.spend()`가 이미 호출마다 정확히 1을 차감하고 있었고
   한 줄이면 됐다. (3) 커버리지 검사를 asset이 아니라 **fetcher** 단위로 옮겼다 —
   OpiNet 계수를 지우면 그 두 fetcher가 빨개지는 것을 확인했다.

   결박은 세 겹이다. generator를 **두 겹 지나서도** 계수가 닿는지(배선을 끊으면
   3건 red), 문맥이 **복사되는 경계**(`to_thread`/`create_task`)에서도 보이는지,
   그리고 fetcher마다 계수 호출이 있는지.

   **2차 적대 리뷰가 blocker 둘을 더 잡았고, 그것이 이 조문의 현재 형태를 만들었다.**

   (a) **krheritage detail이 안 세졌다.** 목록 페이지는 세는데 record당 1 HTTP인
   detail은 세지 않아, 실린 수가 실제의 **약 1%**였다(목록 ~45 vs detail ~4,000).
   목록을 세는 덕에 key는 실려 나갔으므로 "0으로 위장하지 않는다"는 계약이 여기서는
   작동하지 않았다 — 두 자릿수가 네 자릿수인 척했다.

   (b) **feature-update queue 경로에서 계수기가 안 열렸다.** 그 runner는 asset
   wrapper가 아니라 **원본 run 함수**를 직접 부른다. 계수기를 여는 자리가 wrapper
   둘뿐이었으므로, 계측된 fetcher가 큐로 돌면 모든 계수가 no-op이 됐다. 이제
   실행 경계가 계수기를 따로 연다 — **여는 자리는 넷**이다(wrapper 둘 + 큐 runner +
   MOIS Phase A op).

   **3차 리뷰가 같은 형태를 한 번 더 잡았다.** MOIS Phase A는 Dagster **resource
   init 시점**에 도는데 계수기는 compute 안에서야 열렸다 — 2차 반영으로 게이트
   안에 들어온 그 항목이 실제로는 세지 않으면서 게이트가 초록을 보증했다. 큐
   runner는 계수기를 `spec.resources()` 앞으로 올려 덮었고, op은 자기 계수기를
   열며, asset 경로(resource init)는 **부분 계측으로 선언**했다.

   그리고 (c) **"실패 경로에도 실린다"는 주장이 거짓이었다.** 실패한 step은 output을
   내지 않으므로 `add_output_metadata`로 실은 값은 사라진다. 지금 남는 자리는 쿼터
   소진의 `Failure` metadata와 그 밖의 실패의 경고 로그다.

   **정적 검사가 (a)를 통과시킨 것이 이 판의 교훈이다.** 그 검사는 "계수 호출 자리가
   있는가"만 본다 — 루프 밖 1회도, 도달 불가 분기도 초록이다. 그래서 손으로 박은
   자리마다 **가짜 client로 N번 부르게 하고 계수가 N인지 재는** 런타임 테스트를 뒀다.
   정적 검사는 "빠진 진입점이 없는가"만 지키고, 하한·우주·면제는 전부 **선언에 정확히**
   결박된다(여유 상수를 쓰지 않는다).

   `settings.log_api_calls`는 **지웠다** — 읽는 코드가 없었고, 그 표는 provider
   호출이 아니라 Map API로 들어오는 요청을 기록한다.
   (원래 조문) 발신 provider 요청 수를 세는 코드가 있다. 지금은 0줄이다 —
   그리고 `settings.log_api_calls`는 "provider client 호출 횟수를 `ops.api_call_log`에
   기록"이라고 적혀 있지만 **프로덕션 reader가 0개**다(실제 writer는 API 패키지의
   inbound 미들웨어이고 별개 설정이다). 카운터 이름에는 하한임을 박아야 한다 —
   lib 내부 요청(krex lookback 루프, krheritage tenacity)은 이 층에서 보이지 않는다.
3. [x] **쿼터성 실패가 재시도를 사지 않는다.** (2026-09-13)

   `kortravelmap.dagster.quota_exhaustion`이 예외 연쇄를 걸어
   `Failure(allow_retries=False)`로 바꾼다. 문자열을 파싱하지 않는다. asset 35개 중
   34개가 지나는 `run_tracked_feature_asset`와 multi-member인
   `feature_place_mcst_culture` 둘에 결박하고, 결박 단위는 함수 이름이 아니라
   **`except` 핸들러**다 — 한 함수 안의 두 실패 분기 중 하나만 지워도 초록이던
   첫 판을 적대 리뷰가 잡았다.

   **"4배"는 틀렸다(적대 리뷰 정정).** 쿼터가 소진된 뒤의 재시도는 순회를 다시
   도는 것이 아니라 **첫 격자에서 즉사한다** — 격자 루프는 항상 `grids[0]`부터
   시작하고(성공 cursor는 완주 뒤에만 전진) 그 첫 호출이 곧바로 code 22를 받는다.
   실제로 아끼는 것은 순회 3벌이 아니라 **요청 3건 + backoff 420초 + 큐 슬롯
   점유 3회 + 실패 attempt 기록 3건**이다. 요청이 4배가 되는 것은 순회 *도중*
   나는 **재시도 가능한** 실패(H45가 겨냥한 쪽)이고 이 변경은 그쪽을 건드리지
   않는다.

   **HTTP 429는 제외한다.** provider lib들이 429와 resultCode 22에 같은
   `failure_kind="rate_limit"`를 붙이는데(visitkorea·mcst·krforest 실측) 이
   저장소 schedule 다수가 월 1회라, 429 한 번에 재시도를 끄면 그 asset은 한 달
   갱신되지 않는다. 예외가 든 HTTP 상태로 가른다.

   **`failure_kind`를 붙이는 provider가 절반뿐이다.** airkorea·datagokr·krairport·
   krex·opinet·krheritage·mois·knps는 붙이지 않는다. 속성 하나에만 걸면
   **가장 좁은 분모에서 한 번도 발화하지 않는다** — 에어코리아가 오퍼레이션당
   500/일이다. `QUOTA_EXCEPTION_TYPES`가 `(모듈, 클래스)` 선언으로 그 구멍을
   메우고, contract 테스트가 그 이름이 실물 lib에 실재하는지 형제 소스로 확인한다.

   **여전히 덮이지 않는 것**: `krheritage`는 쿼터 소진을 알려 주지 않는다
   (`RateLimitError`가 클라이언트 측 limiter이고 lib 안에서 raise되지 않는다).
   아래 "krheritage run 하나가 4 × ~3,950 = 15,800요청"은 이 기제로 닫히지 않는다.
   `datagokr`(전국표준데이터, 1,000/일)도 쿼터 전용 예외가 없다. `FEATURE_LOAD_RETRY_POLICY`
   (`max_retries=3`)가 35개 asset 전부에 붙어 있고, asset 경계가 `failure_kind`를
   예외 **문자열에 녹여**(`f"KMA provider refresh failed: {exc}"`) step 층이 분류를
   보지 못한다. code 22는 자정까지 같은 코드를 주므로 재시도의 성공 확률은 0인데,
   쿼터 소진된 KMA run 하나가 **4 × 300 = 1,200요청**, krheritage run 하나가
   **4 × ~3,950 = 15,800요청**을 쓴다.
4. [x] **선언 없는 증폭기가 없다.** (2026-09-13)

   krex `lookback_hours` 48 → 6(호출 한 번의 요청 상한이 `lookback+1`이다),
   krforest 4곳과 visitkorea를 저장소 공통 헬퍼로 옮기고 `absolute_max_pages`를
   줬다. **OpiNet은 무제한이 아니었다** — 라이브러리가 격자 셀 20,000을 넘으면
   호출 전에 거부하고, 총량을 실제로 묶는 것은 하루 한 번 coalescing이다.

   이 과정에서 **저장소 헬퍼 자체의 결함**이 드러났다: `max_pages`는 천장이 아니라
   바닥이었다(`absorb`가 선언 건수에 맞춰 올린다). upstream이 `total_count`를
   거짓으로 크게 말하면 요청 수가 그 숫자를 따라간다. `absolute_max_pages`를
   더해 닫았다.

   **krforest 정당화가 거꾸로였다(적대 리뷰 정정).** 라이브러리는 유도가 실패할 때
   10,000페이지로 폭주하는 것이 아니라 **1페이지로 조용히 잘린다** — 응답에
   `totalCount`가 없으면 `_http.py`가 `total_count = len(items)`로 채워 추정치가
   1이 된다. 그리고 **저장소 헬퍼로 옮겨도 그 절단은 그대로다**(2026-09-13 실측:
   2,500행 dataset에서 1,000행에서 멈춘다). 종료 규칙을 바꾸면 범위 밖 page에
   예외를 던지는 provider에서 새 실패가 생기므로 고치지 않고 **경고로 들리게** 했다.
   실제 위험은 쿼터 폭주가 아니라 **행 누락이 성공으로 보이는 것**이다.

   **krex의 "시끄럽게 실패"도 없었다(적대 리뷰).** 빈 Page는 예외가 아니라 정상
   반환이고, 적재 경로에 빈 가드가 없어 0행이 `record_sync_success`까지 가서
   `consecutive_failures`를 0으로 되돌렸다. `KrexRestAreaWeatherUnavailable`을
   더했다 — 그 fetcher에는 테스트가 하나도 없었다.

   **visitkorea 라이브러리에서 잃은 '전진하지 않는 페이지네이션' 가드**도
   `ProviderPage.fingerprint` + `ProviderPaginationStalled`로 헬퍼에 복원했다. 세 곳이 Map 코드에서 1줄로 보이는데 provider
   안에서 팬아웃한다 — 휴게소 기상 `latest_weather()`가 최대 **49요청**
   (`lookback_hours=48`), krforest 3종이 `max_pages` 미지정으로 lib 상한 **10,000
   page**, OpiNet bbox/poi_cache_target 모드가 예산 미전달로 무제한.
5. [x] **UI가 근거 없는 보증을 하지 않는다.** (2026-09-13 — `_schedule_note`가
   비율 대신 실측 표를 가리킨다. `tests/lint/test_quota_claims_have_a_denominator.py`가
   비율 주장이 돌아오면 빨개진다.) admin의 schedule note가 두 갈래 모두
   "rate limit의 약 90% 이하를 목표로 한"을 돌려주는데, 그 90%의 분모는 31개
   schedule에 대해 존재하지 않는다. **그 화면이 운영자가 cron을 올리는 화면이다.**
6. [~] **KMA 격자 재활성화의 전제조건이 적혀 있다.** 분모가 들어와 위 표로
   다시 썼다(72% / 72% / 24%, 서로 다른 쿼터). `settings` 설명의 "초과분은 다음
   run으로"도 고쳤다 — 코드는 `KmaWeatherGridLimitExceeded`로 전면 실패한다.
   **남은 것은 G(실제 격자 수) 실측**이다. 300은 상한이고 실제 target 수가 아니다.
   (원래 조문) 켜면 한 활용신청에
   24×300 + 24×300 + 8×300 = **16,800요청/일**이 들어간다. 비교할 수 있는 유일한
   숫자는 근거 없는 어림 "보통 일 ~10,000"(`docs/etl/kma-weather-etl.md`) → 1.68배.
   그리고 `settings`의 설명이 "초과분은 다음 run으로"라고 적지만 코드는 이월하지
   않고 `KmaWeatherGridLimitExceeded`로 **전면 실패**한다.

**바꾸기 전에 측정해야 하는 것.** 이 task의 절반은 코드가 아니라 숫자였다.

| 무엇 | 어떻게 | 상태 |
|---|---|---|
| 각 활용신청의 일일 한도 | data.go.kr 마이페이지 → 활용신청 상세 | **2026-09-13 실측** |
| `VilageFcstInfoService_2.0`의 3 operation이 한 통을 공유하는가 | 같은 화면 | **공유하지 않는다** |
| G = 실제 KMA 격자 수 | `ops.poi_cache_targets`의 활성 target을 `kma.grid.to_grid`로 dedupe | **G = 59** (2026-09-13 prod) |
| dataset별 선언 건수 | 각 endpoint에 `pageNo=1&numOfRows=1` 1요청 | 미측정 |
| Map이 throttle 구간에 들어간 적이 있는가 | Dagster run 지속시간 분포 + asset metadata | 미측정 |

### 2026-09-13 실측 — 분모를 얻었고, 그것이 조문 6의 전제를 뒤집었다

**일일 트래픽은 서비스가 아니라 오퍼레이션마다 따로 걸린다.** 활용신청 상세의
"상세기능" 표에 오퍼레이션마다 "일일 트래픽" 열이 있다. `기상청_단기예보
조회서비스`는 `getUltraSrtNcst` / `getUltraSrtFcst` / `getVilageFcst` /
`getFcstVersion` **넷이 각각 10,000/일**이다. 전체 표는
`docs/etl/upstream-quota.md`.

그래서 조문 6의 "한 활용신청에 16,800요청/일 → 1.68배"는 **분모를 잘못 잡은
것**이었다. 오퍼레이션별로 다시 세면:

| schedule | 오퍼레이션 | G=300(상한)일 때 | G=59(오늘 실측)일 때 | 한도 |
|---|---|---:|---:|---:|
| `..._ultra_short_nowcast_hourly` (`45 * * * *`) | `getUltraSrtNcst` | 7,200 (72%) | **1,416 (14%)** | 10,000 |
| `..._ultra_short_forecast_hourly` (`50 * * * *`) | `getUltraSrtFcst` | 7,200 (72%) | **1,416 (14%)** | 10,000 |
| `..._short_forecast_hourly` (`20 * * * *`, cursor skip) | `getVilageFcst` | 2,400 (24%) | **472 (5%)** | 10,000 |

**세 schedule은 서로의 쿼터를 먹지 않는다.** 합산해서 터지는 그림이 아니다.

**그리고 300은 상한이지 대상 수가 아니었다.** prod 실측: `ops.poi_cache_targets`가
**0행**이고(파괴적 rebuild 직후, PinVi 미등록) `KMA_WEATHER_EXTRA_POINTS`의 60점이
DFS 격자로 dedupe되어 **G = 59**다. 오늘 KMA를 다시 켜는 것은 쿼터 관점에서
넉넉하다 — 4배 배수를 전부 얹어도 57%다.

**그런데 72%는 여유가 아니다.** 조문 3의 4배 배수가 여기에 곱해지면 한 번의
재시도 순환이 그 run을 300 → 1,200으로 만들고, 하루 세 번이면 9,900으로 한도에
닿는다. 즉 재시도는 쿼터 초과의 *결과*가 아니라 *원인*이 될 수 있는 구간에 이미
들어와 있었다. **조문 3을 닫는 것이 조문 6의 전제조건이다.**

가장 좁은 자리는 KMA가 아니다 — 에어코리아 **500/op/일**, 전국\*표준데이터와
visitkorea 전부 **1,000/op/일**이다.

`krheritage`(국가유산청) · `opinet` · `krex`(도로공사) · `mois`/`localdata`는
data.go.kr 활용신청이 **아니라서** 이 화면에 없다. 그쪽 분모는 여전히 미측정이고,
"krheritage run 하나가 15,800요청"의 분모도 그래서 아직 없다.

**측정 전에 상한 숫자를 바꾸지 않는다**는 원칙은 유효했다. 분모를 몰라도 정당한
것 — 폭주 상한, 재시도 배수 제거, 분자 만들기, 오도하는 문구 지우기 — 만 먼저
했고, 그 사이에 분모가 들어왔다.

### 2026-09-13 prod 배포 (t41a) — 전 사이클 GREEN

`chain17.sh`로 sanctioned 재핀 사이클을 돌렸다(`0b60a850` = #1227 머지 커밋).

```
A. 회전 preflight     OK (OpenAPI 표면 3종 digest 동일)
B. 회전               49번째 · pinset bae61363a6fdd7ff
C. rebuild            success · phase=committed
                      heads 3종 불변 → 마이그레이션 없음이 실측으로 확인됨
0. 핀 원장 대조        map=0b60a850 ✓ pinvi=f62e7ef1 ✓
C. executor 이미지     success · 라벨=0b60a850…
D. repin              repository_commit=0b60a850… · VERIFIER PASS
                      attestation_sha256=10fd0f1f…
E. M01 ACL preflight   failed 0 / total 55
F. D1 (live Playwright) 11 passed (26.0s)
G. lane 정리           BLOCKED 없음
H. D2                 phase=passed · status=complete · recovery_attempt=0 · 잔여물 0
```

배포 뒤 **새 세대에서 run 완주 게이트(#1226)가 15/15 통과**했다 — 탐침 run이 실제로
SUCCESS로 완주했고 필수 daemon 4종이 전부 fresh, 멈춘 run 0건이다.

**UI에서 실제로 바뀐 것**: prod API 컨테이너가 돌려주는 schedule note가
"provider rate limit의 약 90% 이하를 목표로 한 …"에서
"이 저장소가 고른 …기본값입니다. upstream 일일 한도 대비 소비량은 schedule마다
다릅니다 — 실측 한도는 docs/etl/upstream-quota.md에 있습니다."로 바뀌었다.
32개 schedule에 똑같이 붙던 근거 없는 비율이 화면에서 사라졌다.

**배포 경로에서 배운 것 둘.** (1) host-direct `docker compose build`는 이제 쓸 수
없다 — 대상 서비스만 빌드해도 compose 파일 **전체**를 보간하는데 prod `.env`에
다른 서비스(concierge)의 키가 없다. sanctioned 경로(`run-pinned-rebuild-once`)는
Manager가 env를 통째로 구성해 넘긴다. (2) prod postgres는 소켓 기본 경로가 아니라
`127.0.0.1:12700`이고 백업 대상은 `$POSTGRES_DB`(=postgres, 7MB)가 아니라
애플리케이션 DB `kor_travel_map`(44MB)이다.

## T-VN-D2-RESIDUE

```markdown
- [ ] T-VN-D2-RESIDUE — **D2가 run마다 은퇴 Feature 1행을 prod에 남긴다**
```

**무엇이 참이면 닫히는가.**

1. D2가 완주한 뒤 prod에 그 run이 만든 행이 **하나도 남지 않는다** — 또는 남기는
   것이 의도라면 그 의도가 조문으로 적히고, 누적이 유계임을 보이는 정리 경로가 있다.
2. 그 성질을 재는 검사가 있다. lane이 스스로 "통과"라고 적은 뒤의 상태를 보는
   것이어야 한다 — 지금은 lane의 자기 검증이 통과해도 행이 남는다.

**무엇이 관측됐나 — 2026-09-11.**

D2가 `phase: passed`로 완주한 직후 prod에 `E2E TVN36 state fixture {run_id}` 한 행이
`retired/suppressed`로 남아 있었다(`features_total=1`). lane의 자기 잔여물 검사는
통과했다 — 그 검사가 세는 것은 provider fixture 쪽이고, API-owned 행의 삭제는
`purge` action의 몫이기 때문이다.

그런데 **D2는 `purge`를 부르지 않는다.** `admin_feature_live_supervisor.py`의
`--helper-action` 선택지는 `seed`·`cleanup`·`audit`·`api-audit` 넷이고,
`run-admin-feature-live-acceptance.sh`도 그 넷만 부른다. `purge`의 유일한 호출자는
clone lane(`run-admin-feature-clone-live-acceptance.sh`)이며, 그 lane은
`E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_*` 세 변수를 넘기지 않아 helper가 먼저 멈춘다.

즉 **D2를 돌릴 때마다 prod가 은퇴 행 하나씩 늘어난다.** 2026-09-11에는 손으로
306의 감사 경로(`feature.purge_manual_feature`)를 불러 정리했고 잔여물 0을 확인했다.
그 손작업이 규약이 되어서는 안 된다.

**적대 리뷰(2026-09-11)의 완결성 비평이 이것을 지목했다** — purge 경로를 고치는 데
리뷰 한 축을 썼는데, 정작 그 경로는 D2에서 도달 불가였다는 것이 함께 드러났다.

## T-VN-CURATION-SEAL-ACL

```markdown
- [ ] T-VN-CURATION-SEAL-ACL — **적재 seal 함수를 적재 role이 실행할 수 없다**
```

**무엇이 참이면 닫히는가.**

1. `ktm_feature_dagster_runtime`으로 접속한 적재가 curation seal을 통과한다 —
   prod에서 provider asset 하나가 실제로 완주한다.
2. 그 권한이 `infra/runtime_privileges.py`의 렌더링 모델에 들어간다. 마이그레이션에
   직접 `GRANT`만 적고 모델이 모르는 상태로 두지 않는다 — 모르면 다음 재적용에서
   조용히 사라진다(지금이 그 상태다).
3. 이 축을 재는 회귀가 있다. **실 role로** 적재 경로를 태우는 것이어야 한다 —
   migrator/superuser로 도는 통합은 ACL을 구조적으로 관측하지 못한다.

**무엇이 깨졌나 — 2026-09-11 실측.**

prod에서 `feature_place_standard_museums`를 적재하니 상류 조회를 지나 DB 쓰기에서
멈췄다:

    asyncpg.exceptions.InsufficientPrivilegeError:
    permission denied for function current_provider_curation_input_set

**실측 ACL** (prod, head 309):

    owner = ktm_feature_schema_owner
    acl   = ktm_feature_schema_owner=X, ktm_curation_command_owner=X

적재 login role은 `ktm_feature_dagster_runtime`이고 그 목록에 없다. 그리고 runtime
identity는 **설계상 `SET ROLE` 경로를 하나도 받지 않는다**
(`runtime_privileges.py`: "runtime identity는 이 `SET ROLE` 경로를 하나도 받지
않는다"). 즉 우회로가 없다.

**재키 회귀가 아니다.** `alembic/baseline/schema.sql`과 `alembic/head-schema.sql`이
**둘 다** `ktm_curation_command_owner` 하나에만 준다 — prod는 정본과 일치한다. 은퇴한
`0209_tvn40_provider_curation_seal`이 `ktm_feature_runtime`에도 주었으나 그 문장은
baseline으로 접히면서 사라졌고, `runtime_privileges.py`는 이 함수를 **아예 모른다.**

**범위가 좁지 않다.** `capture_provider_curation_input`은 `client.load_feature_bundles`
가 `curation_dataset`을 받을 때 불리고, `dagster/etl.py`는 **snapshot이 아닌 모든**
적재에 그것을 넘긴다. 즉 그 부류 provider 적재가 prod에서 전부 막혀 있다.

**왜 여태 안 보였나.** prod `feature.features`가 0행이었다 — 이 prod에서 provider
적재가 한 번도 성공한 적이 없다. 그리고 통합 테스트는 ACL이 바인드되지 않는
identity로 돈다. 조문 3이 그 구멍을 겨냥한다.

**주의 — 권한 확대다.** runtime login에 함수 EXECUTE를 더하는 변경이므로, 무엇을
열어 주는지(이 함수는 집계 읽기다)와 무엇을 열지 않는지를 먼저 적고 적대 리뷰를
거친다.

## T-101 — Materialized View 도입 검토 (보류)
```

## T-101

```markdown
- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.

### T-VN-H34 잔여 — "없는 것은 Feature로 추가" (2026-08-18 조사)

> 아래의 "경로가 없다"는 문장은 **2026-08-18 조사 당시 상태**다. 이후 Map #1029의
> `0228` M03 combined writer와 `0233` M04 request writer가 병합됐으므로, 현재 Feature
> 생성 경계는 M01/M03/M04가 소유한다. H34의 미연결 membership·좌표·운영 acceptance 잔여만
> 이 절의 active task로 남긴다.

사용자 지시: 재연결 대상이 없던 3건을 **Feature로 추가**하라. **당시 조사 결과**
즉시 추가할 수 없었다 — 그 시점에는 해당 경로가 저장소에 없었다.

**실측.** 세 항목은 prod에 **축제(event)로만** 존재하고 장소 자체는 어떤 provider
dataset에도 없다(kind·lifecycle·publication 무관 전수 검색).

| 항목 | prod에 있는 것 |
|---|---|
| 태화강 국가정원 | `태화강 국가정원 봄꽃축제`·`태화강 대숲 납량축제` 등 event 6건 + 주차장 6건 |
| 반디랜드&태권도원 | **0건**(place/event/area 어디에도 없다) |
| 청풍호 | `제30회 제천청풍호벚꽃축제` event 1건 + 호수 시설(전망대·케이블카) |

**당시 왜 못 만들었나.** `Feature`는 provider ETL이 만드는 것이 계약이었다. 당시
큐레이션이 Feature를 만드는 경로는 없었고, `T-VN-40`의 write model도 **기존 public
Feature에 링크**만 했다 (`docs/reports/t-vn-40-…-plan-2026-08-11.md:161` — "public
Feature만 반환").

당시 만들려면 새 표면이 필요했다:

- **새 `source_type`**(예: `curation_manual`) — `make_feature_id`의 입력이라 ID 체계에 들어간다
- **writer 경로와 소유권** — 누가 갱신하나? provider가 나중에 그 실체를 발행하면 dedup은?
- **lifecycle** — 3축(`lifecycle_state`/`publication_state`/`quality_state`)을 누가 정하나
- **T-VN-40과 충돌** — 그 릴리스가 당시 curation write model을 바꾸는 중이었고, 사용자가
  해당 PR에서 **제외**하라고 한 범위였다

### 결정 (2026-08-18, 사용자) — ETL 무관 Feature는 admin/API로 만든다

1. **ETL과 무관한 Feature는 admin UI/API로 추가할 수 있다.** provider가 발행하지 않는
   실체(국가정원·테마파크 복합·호수 등)가 대상이다.
2. **외부 consumer의 Feature 생성 요청도 같은 API를 쓴다.** PinVi를 포함한 consumer는 직접 만들지 않고 **요청**하며
   admin이 승인한다.
3. **curated Feature를 추가할 때 대상 Feature가 없으면** 이 API로 Feature를 만들고
   curation에도 함께 넣는다.
4. **origin(누가 만들었나)을 구분해 보존한다** — admin 직접 / 외부 요청 승인 / curation
   추가 중 생성. **Feature가 나중에 수정돼도 origin은 바뀌지 않는다.** ETL이 같은 실체를
   발행하는 상황이 되면 admin이 따로 판정한다.

#### 실측으로 보완한 것

**① 표면은 이미 있다. 결선이 없을 뿐이다.**
`ktm_feature_runtime`은 `feature.features`에 **SELECT만** 갖는다(INSERT 없음) — 직접
INSERT는 불가능하다. 그런데 procedure
`feature.create_feature_with_initial_state(p_feature jsonb, p_lifecycle_state,
p_publication_state, p_quality_state, p_context jsonb)`가 **이미 존재하고
`ktm_feature_runtime`에 EXECUTE가 이미 부여돼 있다.** admin 상태 전이용
`transition_admin_feature_state`·`reactivate_admin_feature_state`도 마찬가지다.
→ 새 쓰기 경로를 만드는 일이 아니라 **기존 procedure를 admin API에 잇는 일**이다.

**② "ETL이 엎어쓴다"는 일어나지 않는다 — 진짜 위험은 중복이다.**
`make_feature_id`는 `source_type`을 해시 입력에 넣는다(ADR-009). 수동 Feature와 provider
Feature는 **애초에 다른 `feature_id`**라 ETL이 그 행을 덮어쓸 수 없다. 실제로 생기는 문제는
**같은 실체에 Feature가 둘**이 되는 것이고, 그건 덮어쓰기가 아니라 **dedup/merge** 판정
영역이다. 결정 4의 "ETL이 엎어쓰는 상황"을 그 의미로 새긴다.

**③ curation과 함께 만드는 것은 구조적으로 가능하다.**
`curation_items.source_record_key`는 **nullable**이고 `feature.features`에는 source 쪽 FK가
없다(부모 Feature 자기참조 FK만 있다). 즉 provider source record 없이도 Feature와 curation
item을 만들 수 있다.

#### T-VN-41과의 관계 (2026-08-18 확인 — **직접 겹치지 않는다**)

사용자 질문 "H34 개선이 T-VN-41과 관련 없는지"에 대한 확인. 저장소와 PinVi main을 대조했다.

- **T-VN-41은 cache-target 표면이다.** `(external_system, target_key)` = **PinVi가 등록한 POI**를
  Map Feature에 링크하고, 그 링크·refresh 결과의 순서를 generation·outbox로 보존한다(ADR-081).
  대상 relation은 `poi_cache_targets`·`cache_target_*`이고 `feature.features`를 **쓰지 않는다**
  (`cache_target_outbox_repo.py`에 `feature.features` 참조 0건).
- **H34/M01은 `feature.features`를 만드는 표면이다.** `create_feature_with_initial_state`
  procedure를 admin API에 잇는다. cache-target을 건드리지 않는다.
- **Feature 생성 요청(M04)은 별도 경로다.** 첫 consumer인 PinVi main의
  `feature_requests.py:254`가 `admin_client.create_feature(payload)`로 **`POST /v1/admin/features`**를
  친다(`kor_travel_map_admin.py:3` — "`/v1/admin/features*` change API"). cache-target을 만지지
  않는다(`grep cache_target` 0건). 즉 M04는 41의 outbox를 타지 않고 admin API를 탄다.

**간접 접점 하나 — 미결.** 수동 Feature가 만들어진 뒤 PinVi가 그것을 POI로 **링크**하려면
cache-target 경로를 탄다. 그때 41C의 outbox가 그 링크를 전파한다. 이건 41의 정상 동작이지
H34가 41을 바꾸는 것이 아니다. 다만 **origin이 `manual_*`인 Feature를 41의 reconciliation이
provider Feature와 다르게 취급해야 하는지**(예: provider 재적재로 사라질 수 있는 Feature와
달리 수동 Feature는 restore epoch에서 어떻게 보이나)는 M02(origin 불변)와 41A(restore epoch)를
함께 볼 때 정해야 한다. **`T-VN-41A`/`T-VN-41B`는 PR #975(merge `4672aa96`)로 완료돼
[`tasks-done.md`](tasks-done.md)로 이관됐다** — 따라서 이 항목은 대기가 아니라 **M02 설계의
입력**이다. restore epoch 계약과 ADR-093을 직접 읽어 판정한다.

#### 아직 안 정해진 것

> **2026-08-20 정리**: 아래 7건 중 5건은 ADR-093(proposed, 2026-08-19)과 M04가 이미 닫았다 —
> `source_type=user_request`·`source_natural_key=manual::<uuid>`와 identity claim(§1),
> 초기 3축 상태 제거·좌표 required(§4), command isolation `read-committed`(§5), 범용 Feature
> 요청 큐의 immutable submit·admin resolve 분리(M04)다. 닫힌 것을 "미정"으로 두면 같은 논의를
> 다시 하게 되므로 지웠다. 남은 것은 둘이다.
- **provider가 나중에 같은 실체를 발행하면** — 자동 병합하지 않는다까지는 정해졌다.
  admin에게 무엇을 보여주고 어떤 선택지를 주는지는 미정.
- **공개 표면 노출** — public API/PinVi snapshot에 수동 Feature가 나가는지, 나간다면 소비자가
  origin을 알 수 있어야 하는지.

#### 설계 초안 1차 — 적대 검증에서 무너진 것 (2026-08-18)

설계 초안을 검증자 2명(contract lens / ops lens)이 독립 검토했고 **둘 다 `holds=false`**다.
P1 6건 중 셋이 설계 방향을 바꾼다. 실측 근거가 붙어 있어 그대로 채택한다.

**① "origin은 호출 경로/principal에서 파생한다"는 실행 불가능하다.**
초안은 body로 origin을 받으면 사칭이 영구화되니 서버가 호출 경로에서 파생하자고 했다.
그런데 **PinVi와 admin BFF는 같은 endpoint(`POST /v1/admin/features`)·같은 proxy secret·
검증 없는 `X-Kor-Travel-Map-Actor` 헤더**를 쓴다(`auth.py:205,272-279`; PinVi
`kor_travel_map_admin.py:248-257,518-522`). 서버가 구별할 신호가 **없다.** 이대로 가면 PinVi
승인으로 생긴 Feature가 전부 `manual_admin`으로 **영구·불변** 각인된다 — 초안이 스스로
"불변 컬럼에 추정값을 넣으면 그 추정이 영구 기록"이라며 M01/M02 분리를 반대한 논거가
자기 자신에게 적용된다.
→ **M01은 origin을 `manual_admin` 단일 값으로만 발급한다.** `manual_request`/`manual_curation`은
인증 경계가 실제로 갈린 뒤(별도 route 또는 별도 ops-token scope)에만 값 도메인에 넣는다.
도달 불가능한 값을 미리 등록하면 "구분되고 있다"는 오해까지 영구 기록된다.

**② 자연키를 opaque로 바꾸면 유일한 하드 중복 방지가 사라진다.**
현행은 `feature_id` unique + `ON CONFLICT DO NOTHING`(`schema.sql:1341`) → 409로 같은 실체를
막는다. 초안은 이름·좌표를 자연키에서 빼서 매 요청이 다른 `feature_id`가 되게 했고, 중복
방지를 READ COMMITTED 하의 check-then-act 프리체크로 대체했다 — 동시 요청 2건이 모두 통과한다
(TOCTOU). 게다가 판정 워크플로는 M05로 미뤄져 있어 **M01 머지 시점에 방어가 0**이다.
→ 자연키 opaque화와 **동시에** DB 제약을 둔다: origin `manual_%` 부분 unique index(`lower(name)`,
`sigungu_code`) 또는 `ST_DWithin` EXCLUDE, 또는 `admin.feature.create`에 `serializable`
(`domain_command_registry.py:164-168`이 지원, 40001 재시도 루프 있음).

**③ 새 CHECK가 `PATCH /state`에서 500으로 샌다 — 2026-08-12에 이미 한 번 겪은 유형이다.**
`admin_feature_repo.py:2186-2211`의 23514→도메인 오류 매핑이 **constraint 이름 allow-list**라,
새 CHECK 이름이 거기 없으면 raw re-raise → catch-all 500. 초안의 테스트는 "DB CHECK로 실패"만
요구해 **500이어도 초록**이다. 그리고 근거로 든 fail-close 테스트
`test_admin_state_error_mapping_names_exist_in_ddl`은 **저장소에 없다**(docstring 언급 1건뿐).
→ 새 CHECK 이름을 `_ADMIN_STATE_CONFLICT_CONSTRAINTS`에 넣고, 테스트는 **HTTP status를 단언**한다
(409/422이지 500 아님). "features의 모든 CHECK 이름이 두 집합 중 하나에 있다"는 역방향 fail-close
테스트를 **실제로 만든다.**

**④ `transition_kind='initial'` ⇒ origin 필수 규칙이 기존 integration 테스트 4곳을 즉시 red로 만든다.**
`initial`은 provider 경로가 아니라 비-provider 일반 create kind이고(`schema.sql:1807`),
`test_tvn34c_post_cutover_contract.py:84` 등 fixture 4곳이 origin 없이 CALL한다.
→ 규칙을 "origin이 있으면 `initial`이어야 한다"(역방향)로 약화하거나, fixture 4곳 수정을 구현
순서에 명시한다.

**⑤ `contracts/vnext/*` freeze 갱신이 통째로 빠졌다 — 그런데 freeze 스위트는 green을 유지한다.**
`target-schema-v1.sql:730`이 `create_feature_with_initial_state`를 선언하고 fingerprint는 계약
파일로 만든 DB를 본다(`test_vnext_target_freeze.py:16-18` — "계약이 실제 migration과 갈라져도
green"). 컬럼 축은 의도적으로 닫혀 있다(`:1723-1760`). 즉 **CI가 초록인 채 vNext 목표 계약이
실제 스키마를 서술하지 않게 된다** — 이 저장소가 반복 경계한 바로 그 형태.
→ 구현 순서에 `target-schema-v1.sql` · `target-schema-fingerprints-v1.json` 4카테고리 재계산 ·
`violation-fixtures-v1.sql` + `expected-rejections-v1.json`(신규 거부 케이스) 갱신을 넣는다.
`test_vnext_contract_artifacts.py`의 sha256 상수도.

**⑥ P2 중 결정에 걸리는 것**: `publication_state` 기본값 `published→draft`는 PinVi의 사용자
제보 승인 흐름(`feature_requests.py:242-251`)에 무음 회귀를 낸다 · 3단계 backfill의 전건 UPDATE가
`row_revision` trigger를 100만 번 밟는다 · procedure OWNER 전환과 migration graph artifact 재생성이
선행 조건에 없다 · back-out을 한 줄도 안 다뤘다(forward-only 저장소).

**M00 해소 정본**: 위 finding은
[`T-VN-M00 설계 보고서`](reports/t-vn-m00-manual-feature-create-design-2026-08-19.md)와
proposed ADR-093에서 닫았고, exact checkpoint `2aa17c27`에 API·DB 전문 리뷰 P0~P3 0건 GO를
받았다. 완료 이력은 [`tasks-done.md`](tasks-done.md)가 소유하며 다음 실행 단위는 M01이다.

#### 후속 task
```

---

# 평면화 이후 신설된 task의 해제 조건 (2026-08-30 신규 작성)

아래 다섯은 `6d671ef1` 평면화 **이후**에 만들어져 복원할 원문이 없다. 해제 조건이
처음부터 없었다는 뜻이고, 그래서 "무엇이 참이면 닫히는가"를 아무도 판정할 수 없었다.
`m05-e2e-analysis.local.md`(gitignored forensic)와 공개 receipt에서 확인한 사실로
여기에 처음 적는다. 원시 terminal 출력·private 값은 옮기지 않는다.

**2026-09-07 — 소유자 지시로 하지 않는다(보류/제외).**

규약 §6에 따라 잔여로 계산하지 않는다. 재개하려면 두 선행이 필요하다:

1. **목표 SLO가 저장소 어디에도 정의돼 있지 않다.** 도입 여부를 판단할 기준이 없다.
2. **exact-viewport vs region-total은 의미 택일이다.** 현행은 ADR-073(accepted)이
   "exact spatial predicate"로 못 박은 계약이고, MV는 region-total이다. 바꾸려면
   ADR-073 개정 + PinVi `FeatureCluster` 소비자 계약 변경이 함께 온다 — 시범 PR
   재량이 아니다.

부수 정정: 도입 조건 4(일관성 게이트)는 이미 충족이다. `dagster-boundary.md` Phase
1.5의 "swap 차단 안 함" 서술은 게이트가 아니라 별개 job `consistency_dedup_refresh`를
가리키는 것이므로 drift가 아니다.
