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

## 지금 무엇이 사실인가 — `T-VN-FINAL-REBUILD`

원문 규칙은 이렇다.

> B1~B3 중 하나라도 false면 정확한 Map/PinVi source와 일곱 image를 새 pinset으로
> 고정하고 H46H rebuild를 새 generation으로 다시 수행해 새 immutable v6/v8 journal을
> 발행한다. B4만 false인 경우에도 기존 journal을 새 host attestation으로 덮거나
> 재사용할 수 없다.

generation `8eedf171…` 이후 최소 5개 pinset(`3d8d63e1`·`7035b0b1`·`82850711`·
`5592a1d4`·`9b6eab1e`)에서 **새 image·새 Manager source로 rebuild가 다시 실행됐다.**
따라서 B3/B4는 반복적으로 false다. 배리어는 열리지 않았다.

이 배리어는 `T-VN-41F1D-D1`/`-E`/`-D2` → `T-VN-41C` 순서의 선행이므로
(`tasks-done.md`:25), 잘못된 `[x]`는 네 개 하위 task에 "착수해도 된다"는 근거를
형식적으로만 만들어 줬다.

---

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

## Wave 2 상세 — 구조 전환

> 실행 순서는 31A~C(freeze) → 32~38(shadow, 두 lane 병렬) → 40 → 39(cutover 마지막)다.
> ADR-066~075가 목표 스펙 정본이다. 각 migration task는 forward-only 격리 clone에서 검증하고,
> 명시적 downgrade 수용 조건이 없는 한 전진 뒤 rollback하지 않는다.
```

### `docs/tasks.md`에서 이관한 판정 근거 (2026-09-04)

> `docs/tasks-rule.md` §5는 "task당 위치는 하나 — `docs/tasks.md`에 한 줄, 해제 조건은
> `docs/tasks-acceptance.md`에 한 절. 본문을 중복하지 않는다"고 정한다. `docs/tasks.md`의
> 이 항목은 한 줄 규약을 어긴 742자 산문이었고, 그 내용은 이 절이 소유해야 할
> 판정 근거·재개 조건이었다. 아래는
> 그 본문을 **원문 그대로** 옮긴 것이다 — 요약·축약·삭제 없음(2026-09-04 이관).

**배리어는 열리지 않았다.** `030b12fc…`의 공식 `rebuild-pinned --confirm --json`을 정확히 한 번 실행해 seven-runtime과 v6/v8 committed 증적, Map application `300`·Map Dagster·PinVi `20260824_0101` schema head를 확인한 것은 사실이나, 이 task의 해제 조건 B1~B4는 삭제 직전 **전부 미체크**였고(`git show 6d671ef1^:docs/tasks.md` 739~752행) 평면화가 그 체크박스를 지운 다음 날 `b3bbd3a3`이 `[ ]`→`[x]`로 바꿨다 — 조건이 충족된 것이 아니라 사라진 것이다. generation `8eedf171…` 이후 `3d8d63e1`·`7035b0b1`·`82850711`·`5592a1d4`·`9b6eab1e` 등 최소 5개 pinset에서 새 image·새 Manager source로 rebuild가 다시 실행됐으므로 B3/B4는 반복적으로 false다. 해제 조건 원문은 [`docs/tasks-acceptance.md`](tasks-acceptance.md) 참조. historical `cbb`·`52`·`06045`·`68d99705`·`285618c0`·`37932169`·`31fe73ad`·`b22bfb8c`·`89330403`·`c6c73cdf` candidate는 재시도하지 않는다.

## T-VN-41F1D-D1

```markdown
- [~] **T-VN-41F1D-D1 — 최종 격리 리허설·provenance attestation** *(공동, docs-only)*

  > H46H의 fresh rebuild와 data-independent UI/provenance subset은 committed됐다. 남은 D1
  > 후속은 `T-VN-FINAL-REBUILD` barrier가 현재 candidate를 유지한다고 판정한 뒤 실행한다.

  C3가 결선된 새 generation에서 schema head, canonical `409` receipt, finalize와 **데이터
  비의존** 관리자 UI smoke(로그인 포함)를 기록한다. 2026-08-06 n150 rebuild는 committed했고
  Map application `0087_route_area_subtypes`, Map Dagster `29b539ebc72a`, PinVi `20260804_0049`와
  fixture `finalized`/정확한 `409 PIPELINE_CANCELLATION_UNSAFE`를 확인했다.

  **선행**: T-VN-33 merge와 `T-VN-FINAL-REBUILD`의 current candidate 확인이다. H46H가 이미
  수행한 `rebuild-pinned --confirm`의 v6/v8 evidence를 사용하되, 이전 C3의 pin·smoke는 새
  schema acceptance 증거로 재사용하지 않는다. Manager의 tracked Map source가 병합 SHA와 같고, Map API/UI/Dagster/daemon 및 PinVi
  API/Web/Dagster 일곱 image의 immutable ID·각 schema head·resolved compose/pinset/OpenAPI
  provenance가 candidate에 attest되어야 한다. v6 active generation과 v8 journal만 실행
  authority이며 이전 compatible-pair manifest를 재사용하지 않는다.
```

## T-VN-41F1D-E

**2026-09-06 완료.** 남았다고 적힌 "n150 data-dependent 실행"은 D2가 pinset `48166bd2`에서
수행했다 — lane이 v6 manifest·v8 journal·host attestation을 검증기에 넘기고 세 해시를
`result.json`에 남긴 뒤 `phase: passed`로 닫혔다. 검증기가 대조하는 축이 아래 열거와 일치한다.

`run-c7-prod-live-e2e.sh`(6-spec C7 prod gate)는 v6/v8 전환 이후 돌지 않았고 **앞으로도 이
baseline에서는 돌 수 없다** — `docs/runbooks/c7-prod-live-e2e.md`가 스스로
`[보존 이력 · 실행 금지]`이고 "300 baseline의 n150 배포에는 사용하지 않는다"고 적는다.
`T-VN-M01`의 restore 축과 같은 계열이다. 되살릴 조건: 300 baseline에 맞는 C7 prod gate 운영
순서가 생기면 그때 다시 세운다.

`/etc/kor-travel-map/`의 v6/v8 pinset 쌍 여섯은 같은 포맷의 이력이고 롤백 입력이라 퇴역
대상이 아니다. 퇴역한 것은 **포맷**이다 — v4/v5/v7이 `retired-de5206dc/`에 있다.

```markdown
- [x] **T-VN-41F1D-E — 구 generation 퇴역·v6/v8 attestation 전환** (2026-09-06 완료)

  > 2026-08-25 — **저장소측(unit·script contract) 완료**. 남은 것은 F1D-D 순서를 따르는
  > n150 data-dependent 실행뿐이다. `E2E_C7_COMPATIBLE_PAIR_MANIFEST`가
  > `E2E_C7_PINNED_RUNTIME_MANIFEST` + `E2E_C7_REBUILD_JOURNAL`로 바뀌었고, runtime role은
  > 다섯에서 **일곱**으로(PinVi web/dagster 추가), host attestation은 version 3 → 4로,
  > 세 schema head와 pinset이 generation 값과 exact 대조된다. 2026-08-25에는 Manager의
  > manifest v6/journal v8에 맞춰 application `300` candidate evidence, application/Dagster
  > DB identity, root/finalize result, application/metadata permit까지 exact 검증하도록 올렸다.
  > 최종 보강에서는 PinVi DB의 PostgreSQL system identifier·name/OID·owner-login identity와 Dagster
  > metadata LOGIN role의 connection limit·password expiry·role/database-local setting 잔여까지
  > 같은 journal/permit field set으로 결박해 **세 DB identity**를 committed resume에서 재대조한다.
  > journal은 phase `committed` + candidate 전체 동등 + cancel probe `finalized`를 요구한다. v4를 억지로
  > 넣어 통과하는 경로는 만들지 않았고, runner 계약 테스트가 v4 env 부재를 단언한다.
  > 변이(phase/candidate/candidate evidence/DB identity/result/permit/cancel probe/schema
  > head/journal digest/pinset/image 대조/manifest version)가 전부 red임을 실측했다. 실행 전제: v6/v8은
  > `require_rebuildable_mode`가 걸려 rehearsal/rebuildable에서만 생성된다(n150은 해당).
  > 과거 v5/v7 파일은 보존 이력일 뿐 current runner 입력이 아니며, 현 세대 v6/v8 문서는
  > H46H의 committed fresh rebuild가 이미 만들었고, D1/F1D-E가 이를 후속 검증에 사용한다.

  `run-c7-prod-live-e2e.sh`와 `run-admin-feature-live-acceptance.sh`가 요구하는 v4
  `E2E_C7_COMPATIBLE_PAIR_MANIFEST`를 제거한다. root-owned snapshot은 v6
  `PinnedRuntimeManifest.active_generation`, 일곱 immutable image·Map/PinVi revision·세 schema
  head·pinset·application `300` candidate evidence를 확인하고 v8 journal/host attestation과
  함께 발행한다. v4/v5 manifest와 v7 journal을 억지 입력해
  통과하는 compatibility 경로는 만들지 않는다. final schema merge/재적재와 독립적으로 unit·script
  contract까지 완료하고, 실제 n150 data-dependent 실행은 위 F1D-D 순서를 따른다
  (그 순서는 `T-VN-FINAL-REBUILD` 배리어 뒤에 열린다).

### T-VN-FINAL-REBUILD — 주요 개발 완료 후 최종 acceptance 배리어 (2026-08-20 신설)

> **범위 정정(2026-08-26)**: H46H baseline의 파괴적 fresh rebuild는 사용자 승인에 따라
> 이미 실행·committed됐다. 이 task는 후보가 바뀌어 rebuild를 다시 해야 하는 경우가 아니면
> 재실행하지 않고, 남은 D1/D2/F1D-E와 41C의 최종 acceptance 순서·barrier를 소유한다.
```

## T-VN-41F1D-D2

```markdown
- [x] **T-VN-41F1D-D2 — data-dependent admin/PinVi live E2E** *(공동, docs-only)*

  > D1/F1D-E와 `T-VN-FINAL-REBUILD` current-candidate 확인 뒤에 실행한다. H46H baseline 완료만으로
  > 이 data-dependent acceptance를 완료 처리하지 않는다.

  D2는 H46H fresh rebuild를 다시 실행하거나 기존 application DB를 복구하지 않는다. production
  DB·dump/export·자격증명은 fixture source로 사용할 수 없으며, synthetic 또는 승인된
  non-production seed/ETL만 허용한다. current exact candidate와 같은 final `300` schema의
  승인된 일회용 non-production DB에서, manifest가 밝힌 고정 ID 또는 run-scoped owned ID만
  사용해 **고정 curated/feature ID를 요구하는** admin live UI·PinVi mutating E2E를 실행한다.
  실행 직전 fixture DB의 identity/name/OID/owner와 schema head를 exact 대조하고, production
  DB identity·자격증명과 같으면 즉시 중단한다. `fixed` mode에서는 allowlist의 fixture ID가
  provisioning 뒤 정확히 존재하고 manifest checksum/content와 일치해야 하며, 누락·불일치·추가
  ID가 있으면 중단하고 이 고정 fixture row를 run cleanup으로 삭제하지 않는다.
  `run_scoped_owned` mode에서는 provisioning 전에 해당 ID가 없어야 하며 collision이면 중단하고,
  이 mode가 생성한 allowlisted row·FK만 cleanup 대상이다. fixture provisioning·실행·cleanup은
  [`admin-feature-live-acceptance.md`](runbooks/admin-feature-live-acceptance.md)의 Map-owned
  root helper와 격리 DB 경계만 사용하며 direct table `INSERT`는 허용하지 않는다.

  **DB 경계 개정 (2026-09-04, 소유자 판정 — 대상은 배포 DB다).** 위 문단의 "승인된 일회용
  non-production DB"와 실행 런북의 `E2E_LIVE_ALLOW_PROD=1` + 배포 DB `CONFIRM_*` exact 일치가
  정면으로 충돌했다(2026-09-04 조사). 소유자는 **배포 DB**를 대상으로 정했다. 두 문장이
  실제로는 충돌하지 않는다 — 이 저장소는 이미 **n150을 실 production이 아니라고** 못박아 뒀다
  (`T-VN-H43`: "n150은 실 production이 아니며 손상 시 재적재가 정책이다", 사용자 지시
  2026-08-06). 따라서:

  - D2의 대상은 n150 **배포** Map/PinVi DB이고, 실행 수단은
    [`admin-feature-live-acceptance.md`](runbooks/admin-feature-live-acceptance.md)의
    `E2E_LIVE_ALLOW_PROD=1` lane이다. 격리 대안
    (`scripts/run-admin-feature-clone-live-acceptance.sh`, 18701/18705)은 런북이 없으므로 정본이 아니다.
  - "production DB identity·자격증명과 같으면 즉시 중단한다"는 **실 production**을 가리키는 것으로
    읽는다. n150 배포 DB는 그 대상이 아니다. 런북이 요구하는
    `E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE`/`_LOGIN_ROLE`/`_ALEMBIC_REVISION` exact 대조가
    "엉뚱한 DB에 쓰지 않는다"는 보호를 그대로 수행한다.
  - 나머지 불변식(fixture만 소유, direct `INSERT` 금지, Map API runtime role read-only 유지,
    root-only DSN을 browser/API route에 넘기지 않음, 종료 시 소유 row 0건 확인)은 **그대로 유지한다.**
    바뀐 것은 대상 DB의 분류뿐이다.

  **열린 판정 해소 (2026-09-06, 실행으로).** 런북 §1의 fixture 소유 모델(8-ID, place 6 +
  weather/price 2)은 2026-07-20 계약이고 실제 spec은 2026-08-09~12에 **단수 name-keyed**
  (API 1 + helper 2, ID는 서버 발급)로 재작성됐다. `fixed`/`run_scoped_owned` mode 결박은
  코드에 0건이다. 2026-09-06 통과 실행이 **구현 쪽 모델로** 닫혔다 — 소유 ID 8건을
  `owned_feature_id_sha256`으로 기록하고 종료 시 전부 0으로 회수했다. 따라서 정본은
  구현이다. 런북 §1의 8-ID 문장은 그 기술(記述)로 남고 결박은 아니다.

  fixture manifest에는 source/seed identity와 checksum, 허용 ID 목록, active generation,
  v6 manifest digest, v8 journal/host-attestation digest, exact Map/PinVi pair SHA, 일곱 image
  ID, 세 schema head, service OpenAPI SHA를 기록한다. 이 값은 실행 직전 active v6/v8와
  host attestation에 exact equality여야 하며, 누락·불일치·stale generation·이전 journal
  재사용이면 E2E를 시작하지 않는다. manifest는 `fixed` 또는 `run_scoped_owned` ID mode 하나를
  단일 선택하고 그 mode의 checksum·cleanup identity를 함께 결박한다. 종료 뒤에는 그 run이 만든
  owned row·FK·container residue·pending/dead 상태만 정리·검증하고, cleanup과 evidence가 모두
  통과하기 전에는 D2/41C receipt를 승격하지 않는다. 기존 application 전체의 내용·건수·업무상
  무결성을 대조하지 않는다.

  **선행: T-VN-40 완료**(사용자 판단 2026-08-08). T-VN-40B가 admin/public/PinVi consumer를
  `curation_collections/items` 정본만 읽도록 전환했으므로, fixture도 그 final read 경로를
  사용한다. 전량 provider/ETL 재적재는 D2 fixture를 준비하는 선택지일 수 있으나 H46H의
  일반 release gate가 아니며, 새 candidate를 만들지 않는 한 `rebuild-pinned --confirm`을
  다시 실행하지 않는다. D1은 데이터 비의존 provenance/UI 계약을, D2는 명시된 fixture의
  data-dependent 계약을 각각 소유한다.
```

## T-VN-D2-API-AUDIT

```markdown
- [x] T-VN-D2-API-AUDIT — D2 fixture helper의 `api-audit` 경로를 실행 가능하게 만든다 (2026-09-06 완료)
```

**2026-09-06 완료.** 러너가 `api-audit`을 실제로 부르고 `ktdm-d2-008`이 `phase: passed`로
닫혔다 — lifecycle 56 = 7 operation × 8 phase(`helper-api-audit` 8개), evidence
`phase: evidence-validated`, api-audit counts 3·1·7·3 / FK 18·8. feature_id 규칙은 서로
다른 실행이 만든 Feature **셋**으로 배포 DB에서 확인했다. 상세는
[`docs/tasks-done.md`](tasks-done.md).

`purge`는 여전히 열려 있지 않다 — hard purge는 `T-VN-M02`가 fence하고, supervisor 허용
목록은 호출자가 생길 때 함께 연다(게이트가 단언한다).

**왜 열었는가.** `run-admin-feature-live-acceptance.sh`는 `run_helper`를 `seed`·`cleanup`·
`audit`으로만 부른다. `api-audit`과 `purge`는 helper에 구현돼 있으나 **한 번도 실행된 적이
없고**, 그래서 그 안의 계약이 검증된 적이 없다. 2026-09-06 적대 리뷰가 셋을 찾았고 둘은
고쳤다(operation 이름·성공 status를 `domain_command_registry`에서 유도). 남은 하나가 이
항목이다.

**남은 결함.** `_admin_fixture_feature_id`가 `{name}:{lon:.6f},{lat:.6f}`를 자연키로
`feature_id`를 재계산한다. M01 이후 서버는 `manual::{feature_uuid}`를 쓰고 그 uuid는
서버가 발급하는 **랜덤 UUIDv7**이라, run_id만으로는 원리적으로 재계산할 수 없다. 따라서
`_inspect_api_owned`의 `feature_id != expected_feature_id` 대조와
`_audit_complete_api_owned`의 `feature_ids != (feature_id,)`는 항상 실패한다.

**왜 D2와 분리하는가.** 같은 함수를 clone 러너의 content digest 계약이 함께 쓴다 —
`scripts/run-admin-feature-clone-live-acceptance.sh`가 셸 안에서 같은 규칙을 재현하고
`tests/unit/test_admin_feature_live_acceptance.py`가 두 파생의 일치를 단언한다. 즉 이
수정은 두 lane의 계약을 함께 판단해야 하고, D2 완주 경로에는 필요하지 않다.

**해제 조건.**

1. `_admin_fixture_feature_id`가 **행의 `feature_uuid`로** 서버 규칙을 재현한다
   (`category="manual_feature_v1"`, `source_natural_key=f"manual::{uuid}"`). 재계산이
   아니라 재현이므로 랜덤 uuid에도 성립하고, router 규칙이 바뀌면 여전히 실패한다.
2. clone 러너의 content digest가 같은 규칙으로 옮겨지거나, D2와 clone이 서로 다른 규칙을
   쓴다는 사실이 두 곳에 명시된다. 어느 쪽이든 `tests/unit/test_admin_feature_live_acceptance.py`의
   두 파생 일치 단언이 실제를 반영해야 한다.
3. 러너가 `api-audit`을 실제로 부르고, 그 실행이 배포 스택에서 통과한다. 부르지 않으면
   1·2가 다시 잠복한다 — **이 항목의 요지가 그것이다.**
4. 변이 검증: operation 이름·성공 status·feature_id 규칙을 각각 되돌리면 게이트가 red가
   된다.

**새 helper action을 더할 때 함께 고쳐야 하는 곳 — 다섯이다** (2026-09-06에 전부 CI
게이트가 됐다). `run_helper api-audit`을 더하면 `helper-api-audit` operation과
`direct-api-audit.json`(+ stderr sibling)이 생긴다.

| 곳 | 안 고치면 | 언제 알게 되나 |
|---|---|---|
| `run-admin-feature-live-acceptance.sh`의 `LANE_OPERATIONS` | `run_supervisor`·`run_executor`가 `die` | **즉시** |
| `admin_feature_live_supervisor.py`의 `--helper-action` **choices** | argparse가 **exit 2** — lifecycle도 출력 파일도 쓰기 **전**이라 lane에 아무 흔적이 없다 | 배포 스택 실행 1회, 게다가 **엉뚱한 곳**을 가리킨다 |
| `admin_feature_live_state.py`의 해당 mode `required_operations` | lifecycle 파일 이름 대조에서 죽는다 | 배포 스택 실행 1회 |
| 같은 파일의 해당 mode `expected_names` | 파일 집합 exact 대조에서 죽는다 | 배포 스택 실행 1회 |
| 호출을 `recover_run`에도 두면 **recovery 쪽 두 집합** | normal/recovery는 별개 계약이다 | recovery 실행 1회 |

**둘째가 이 표를 다섯 줄로 만든 이유다.** 2026-09-06에 앞의 넷만 고치고 `ktdm-d2-007`을
돌렸더니 이렇게 나왔다:

    lifecycle 48개 = 6 operation × 8 phase     helper-api-audit은 0개
    direct-api-audit.json 없음
    runner die: "owned fixture cleanup left residue"

설치된 스냅샷도 러너 호출부도 멀쩡했고, 실패는 cleanup residue를 가리켰지만 실제
잔여물은 0이었다(독립 측정). 원인은 supervisor의 인자 검증이었다. **흔적을 남기지 않는
실패는 진단을 한 겹 멀게 한다.**

이제 두 게이트가 다섯을 덮는다:

- `tests/lint/test_lane_operations_are_declared_once.py` — `run_new`/`recover_run`
  각각의 호출부에서 산출물 이름과 operation 집합을 유도해 검증기의 두 집합과 각각
  exact 대조
- `tests/lint/test_supervisor_accepts_every_helper_action.py` — 러너 호출부의 action을
  유도해 supervisor 허용 목록과 helper 구현 action에 양방향 결박

착수할 때 그 둘이 시키는 대로 함께 고쳐라 — CI에서 먼저 red가 난다.

## T-VN-PAIR-V2

**2026-09-07 실측 — 종전 서술의 과소·과대 계상을 함께 정정한다.** 네 축을 병렬 조사하고
48건을 반증에 부쳐 27건이 정정됐다. 아래는 반증을 통과했거나 정정된 것만 적는다.

**과소 계상 — 소비자는 하나가 아니라 셋이다.**

| 소비자 | 지점 | 성질 |
|---|---|---|
| `apps/api/app/core/config.py` | `_load_m05_pair_provenance` 봉투 단언, **모듈 스코프에서 호출** | v2를 먹이면 `import app.core.config`가 `RuntimeError`로 죽는다 — 요청 오류가 아니라 **컨테이너 기동 실패**(실측 재현) |
| `scripts/m05_activation_attestation.py` | 같은 봉투 단언 복사본 | `AttestationError` |
| `scripts/m05_activation_receipt.py` | 같은 봉투 단언 복사본 | `ReceiptError` |

config.py는 봉투 검사 한 줄로 끝나지 않는다 — `source_revision`이 반환 튜플과 6개 모듈
상수로 흘러가고, 그 상수가 활성화 receipt 대조(`:1792-1795`)와 Map image digest
대조(`:1853-1861`)에 쓰인다. 편집 규모는 **약 50~70줄, 지점 6~7개**다.

**과대 계상이었던 것 — 조사 1차에서 "최대 blocker"로 지목했으나 반증됐다.**

- 서명된 활성화 receipt는 blocker가 **아니다**. TTL 상한 7일·기본 24시간으로 만료가 하드
  강제되고 매 활성화마다 새로 서명되므로 보존할 장기 receipt가 없다.
- 되돌리기 위험도 v2가 만드는 것이 아니다. stale `source_revision`이 Manager preflight에
  거부되는 성질은 **v1에서 이미 상시적**이고, 지워지는 두 값은 커밋된 계약 파일과 그
  15개 커밋 이력에 평문으로 남아 있어 n150 root 전용 상태가 아니다.
- Map 원장이 비용을 기록하지 않는다는 것도 사실이 아니다. 기록은 있고(resume.md·tasks.md·
  journal.md 여러 곳) 부족한 것은 **건별 회계**다.

**실제로 남는 안전 공백 하나.** Manager의 **v2 회전 preflight는 아무 대조도 없이 통과**
시킨다(`m05_isolated_e2e.py:2165-2172`). 그래서 "v2 계약 + v1-only 소비자" 조합을 회전
전에 잡지 못하고, 그 조합은 컨테이너 기동 실패다. §5/§7의 Manager 작업에서 이것을 함께
닫아야 한다 — 회전 시점에 target revision의 Map blob digest를 계약과 대조하면 된다.

**비용(왜 하는가).** 2026-09-01 이후 Map 변경으로 강제된 재핀 **12건**, **12건 전부
rebuild 동반**. 그중 **10건은 상류 admin OpenAPI가 바이트 동일**한 채 revision 라벨만
옮겼다(상류 blob sha256이 12개 핀에 걸쳐 두 값뿐). v2는 그 두 필드를 계약에서 걷어내므로
그 10건의 계약 diff가 사라진다.

**선행은 끝나 있다.** Manager dual-read는 구현·배포 완료(n150 `/opt/.../m05_isolated_e2e.py`
확인)이고 v2 happy-path 테스트도 있다. 생성기의 되돌림은 커밋된 JSON이 v2가 되는 순간
자기 무장해제하므로 **생성기 변경은 순서상 마지막**이다.

**해제 조건 7항의 소유자 배분** — 소비자 3(§1 dual-read+사용처 열거, §2 v1 계약 그대로
기동, §4 v2 게이트+양방향 변이) · 생성기 1(§3 `--write` v2 재생성) · Manager 3(§5 preflight
실측, §6 회전→rebuild→격리 e2e, §7 v1 분기 제거).


```markdown
- [x] T-VN-PAIR-V2 — PinVi M05 pair 계약 v2 이행 (2026-09-07 완료)
```

**왜 여는가.** Map revision이 두 곳에서 선언된다 — pin registry(정본)와 PinVi가
vendoring한 pair 계약. Manager의 회전 preflight가 둘을 exact 대조하므로, 어긋나면
회전이 거부된다. 거부 자체는 옳다(2026-09-02에 71분 rebuild를 다 태운 뒤 거부당한
사고를 앞으로 당긴 것이다). 문제는 **Map의 어떤 변경이든 PinVi 커밋을 강제한다**는
것이고, 그것이 곧 새 pinset과 rebuild다. 이중 선언 결함 계열(`AGENTS.md` DO NOT 15).

**진짜 관문은 생성기가 아니라 소비자다(2026-09-05 실측).** PinVi의
`scripts/generate_m05_pair_contract.py`는 **이미 v2를 계산한다** — `build_contract`가
`{"map": surfaces, "version": 2}`를 만든다. 그런데 곧바로 `_in_committed_envelope`가
커밋된 v1 봉투로 되돌린다. 이유가 코드에 적혀 있다: 소비자
`apps/api/app/core/config.py`의 `_load_m05_pair_provenance`가 **모듈 스코프**에서
`set(raw) == {"map", "runtime_image_digests", "version"}`과 `version == 1`을 단언하고,
surface마다 `source_revision`을 요구한다. 계약만 뒤집으면 PinVi API 컨테이너가
**import에서** 죽는다. Manager 격리 preflight는 v1/v2를 함께 읽으므로 회전 전에 잡지
못하고, 실패는 rebuild를 태운 뒤에야 드러난다.

즉 이 작업의 크기는 "생성기 한 줄"이 아니라 **소비자 이행**이다.
`_load_m05_pair_provenance`가 돌려주는 `source_revision`과 `runtime_image_digests`의
downstream 사용처를 먼저 세어야 한다(`scripts/m05_activation_attestation.py`,
`apps/api/tests/unit/test_m05_*`).

**완료 (2026-09-07).** §1~§7 전부 닫혔다.

| 항목 | 상태 |
|---|---|
| §1 소비자 dual-read | **완료** — PinVi #538 |
| §2 v1 계약 그대로 기동 | **완료** — pinset `78cad481…` |
| §3 계약 v2 재생성 | **완료** — PinVi #539 (version 2, `runtime_image_digests` 제거, `source_revision` 0건, digest 16개 무변경) |
| §4 v2 게이트 + 변이 | **완료** — PinVi 9건 · Manager 12건 전부 red |
| §5 PinVi 커밋 없이 새 Map 수용 | **완료** — 정적·실행 양쪽 |
| §6 회전 → rebuild → 격리 e2e | **완료** — `status: passed` |
| §7 Manager v1 분기 제거 | **완료** — Manager #323 |

**§3의 실제 선행은 "생산자 배선"이었고, 그것을 두 번 틀렸다.** 원장은 소비자를
하나로 봤지만 셋이었고(1차 정정), 배선을 하고 나서도 **전문 리뷰어 2명의 적대
검토**가 P0 두 건을 잡았다. 둘 다 "사본을 걷어냈으면 정본을 가리켜야 한다"를
반쯤만 한 데서 나왔다.

| # | 무엇을 틀렸나 | 어떻게 드러났을 것인가 |
|---|---|---|
| P0-1 | evidence의 네 표면 블록은 **attestation이 계약을 복사한 것**인데, receipt가 5키 완전 일치를 리터럴로 요구했다 | v2로는 **어떤 receipt도 만들 수 없다** — 회전·rebuild·repin·D1을 다 태운 뒤 마지막에 막힌다 |
| P0-2 | `service` 표면 revision의 정본을 pin registry로 착각했다. 정본은 PinVi `kor-travel-map-service-provenance-v1.json` | digest는 전부 일치해 preflight도 `_pair`도 통과하고, **71분 rebuild 뒤 PinVi 컨테이너가 기동 실패** |

**표면마다 생산자를 이름 대어 정한다** (attestation `_surface_revisions`, receipt
`surface_revisions`, Manager `_service_release_revision`):

| 표면 | v1 | v2 정본 |
|---|---|---|
| admin·full·user | 계약이 선언 | Map pinned revision (Manager pin registry) |
| service | 계약이 선언 | PinVi service-provenance 계약 |

**픽스처가 두 P0을 다 가리고 있었다.** receipt 테스트가 evidence의 표면 블록을 손으로
적어 **실제 생산자가 낼 수 없는 문서**를 만들고 있었다. 이제 vendored 계약에서 그대로
가져온다 — 계약이 v1이든 v2든 픽스처가 자동으로 그 모양을 따른다.

**Manager 안전 공백도 함께 닫았다.** 종전 원장이 지목한 대로
(v2 회전 preflight가 무조건 통과) 회전 대상 Map revision의 네 표면 blob digest를
계약과 대조하도록 앞으로 당겼다 — 격리 e2e가 rebuild **뒤에** 하던 그 대조다.

**§5 — v1이었다면 71분이 따라왔을 자리.** Map `main`이 pinned `631f1abc`에서 5커밋
앞섰는데 세 표면 blob이 전부 바이트 동일하고 v2 계약의 네 digest와 일치했다.
회전 preflight가 그 Map revision을 **PinVi 커밋 없이** exit 0으로 수용했고, 어긋난
revision(`db319a47`)에는 두 digest를 찍으며 거부했다(음성 대조).

**§6 실측 (pinset `b229446a`).**

| 단계 | 결과 |
|---|---|
| 회전 | rotation #40, pinset `b229446ac273…` |
| rebuild | `success: true`, `phase: committed` |
| 격리 M05 e2e | **`status: passed`**, `phase: completed`, m04·m05 attestation 해시 존재, cleanup 정상 |

**§6에서 PAIR-V2와 무관한 선행 결함 하나가 드러났다.** Playwright runner 이미지 핀이
v1.62.1인데 PinVi lockfile은 1.63.0이었다(회전 **전** pinned PinVi도 이미 1.63.0이었으므로
이 회전이 만든 드리프트가 아니다). 두 값이 어긋나면 `/ms-playwright` 캐시가 적중하지
않아 본문 브라우저 기동에서 무조건 소각인데,
`_assert_playwright_runner_matches_pinned_source`가 **실행권 소비 전에** 잡았다 —
게이트가 설계대로 동작해 한 사이클을 아꼈다(Manager #322).

**§7 — 걷어낸 뒤 변이 검증이 공허한 게이트 둘을 찾았다.**

1. `_pair`가 v1을 다시 받도록 되돌려도 초록이었다 — v1 거부를 확인하는 테스트가 없었다.
2. `"pair contract v2 must not declare a source revision"` 전용 검사는 **도달할 수
   없었다.** 바로 위 entry 스키마 검사가 먼저 잡기 때문이고, dual-read 도입 때부터
   그랬다. 그 검사와 어휘를 걷고 기존 테스트가 실제 진단을 단언하게 고쳤다.

진단 어휘 게이트도 양방향으로 만들었다(allowlist 항목이 실제로 발신되는지도 본다) —
한 방향만 보니 죽은 어휘가 넷 쌓여 있었다.

**§7 뒤 확인 실행.** v1 분기를 걷어낸 Manager(`0406b14d`)로 같은 pinset에서 격리 M05 e2e를 한 번 더 돌려 `status: passed`를 다시 받았다 — 걷어낸 것이 회귀를 만들지 않았다는 증거다(rebuild는 pinset이 그대로라 불필요했다).

**되돌리는 방법.** v1 pinset으로 재개해야 하면 Manager #323을 revert한다. 그 판단에
필요한 신호는 거부 메시지가 낸다: `pair contract version is unsupported`.

**해제 조건.**

1. 소비자 이행이 먼저다. `apps/api/app/core/config.py`가 v1·v2를 **함께** 읽고, v2에서는
   `source_revision`·`runtime_image_digests` 없이 동작한다. 그 두 값의 downstream
   사용처가 전부 대체되거나 제거된 것을 사용처 열거로 보인다.
2. 1이 병합돼 PinVi API 컨테이너가 **v1 계약 그대로** 정상 기동한다. dual-read이므로
   이 시점에 계약은 아직 v1이다 — 소비자만 앞서 나간다.
3. 그 뒤에 계약을 v2로 재생성한다(`--write`). `map.full`/`map.admin`에서
   `source_revision`이, 최상위에서 `runtime_image_digests`가 사라진다. 나머지 digest는
   그대로다.
4. PinVi 게이트가 v2 계약에 `source_revision`이 **없음**을 단언한다. 되살리면 red가
   되는 것을 변이로 보인다. 그리고 `config.py`를 v1-only로 되돌리면 red가 되는 것도
   함께 보인다 — 소비자와 계약이 한쪽만 움직이면 깨져야 한다.
5. Manager `--rotation-preflight`가 **PinVi 커밋 없이** 새 Map revision을 수용한다.
   실측으로 보인다 — 같은 PinVi revision + 다른 Map revision으로 preflight를 통과시킨다.
6. 그 pinset으로 회전 → rebuild → 격리 M05 e2e가 `status: passed`.
7. 6이 green인 뒤에야 Manager의 v1 분기를 뗀다. **먼저 떼지 않는다** — 현재 pinset으로의
   재개 경로가 즉시 막힌다(Manager 주석이 그 이유를 적는다).

**하지 않는 것.** v1 계약 파일을 지우지 않는다. 파일명이 `-v1`을 담고 있으나 그것은
경로이지 버전 선언이 아니다 — 버전은 문서 안의 `version` 필드다. 경로를 바꾸면 Manager가
읽는 위치와 갈라진다.

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

## T-VN-M01

```markdown
- [x] **T-VN-M01 — admin Feature 생성 API clean cutover** (2026-09-06 완료). Map PR #1029
  (merge `57c9d99a`)에 `0226_m01_manual_feature_create`의 DB/ACL/backup manifest와 API·Admin BFF가
  함께 착지했다. PinVi direct-create fail-close는 [PinVi #458](https://github.com/digitie/pinvi/pull/458)로
  완료됐다. 남은 것은 `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false`를 유지한
  route 활성화 전 fresh restore/ACL/live gate다.
```

**활성화 전제 셋** (설계 문서 §1). 셋을 모두 만족하기 전에는 플래그를 `true`로 바꾸지
않는다. **2026-09-06에 셋 다 닫혔고 플래그는 `true`다.**

| 전제 | 상태 |
|---|---|
| PinVi `new_place` 직접 create 제거 배포 | **완료** (PinVi #458) |
| M01 DB/API/admin UI + 최소 backup·restore·ACL reconciliation 배포 | DB/API/UI 완료(#1029). ACL reconciler는 API 부팅마다 실행. **ACL 축 55/55**(rebuild 앞뒤 두 번). **restore 축은 300 baseline이 대체**(아래) |
| 전용 BFF 자격 성공 · PinVi/일반 AdminBFF 거부 · DB zero-write smoke | **완료** — 성공 201, 거부 4/4 403, witness 8관계 증분 0 |

**ACL 축 — 2026-09-05 배포 런타임 실측 통과(55/55).** `scripts/m01_activation_preflight.py`가
설계 §8.1~8.3을 재실행 가능한 형태로 확인한다. 아무것도 쓰지 않으므로(catalog
`has_*_privilege`/`pg_has_role`만) 활성화 전 프로덕션에서 그대로 돌린다. §8.2가
**"restore 뒤 동일"**을 요구하므로 restore·rebuild 뒤에도 다시 돌린다. 확인 내용:

    role 속성(NOLOGIN NOINHERIT) · membership exact option(admin/inherit/set)
    교차 멤버십 부재 · runtime login의 owner SET ROLE 불가
    claim/origin direct SELECT/INSERT/UPDATE/DELETE/TRUNCATE 부재(API·Dagster·PUBLIC)
    relation owner = ktm_feature_schema_owner
    wrapper  create_admin_manual_feature_with_initial_state  api=true  dagster=false public=false
    generic  create_feature_with_initial_state               api=false dagster=true  public=false

**restore 축 — 300 baseline이 대체했다(소유자 판정 2026-09-06).** 설계 §10.3은
`pg_restore --no-owner --no-privileges` 뒤 owner repair·ACL reconciler·§8.3 재통과를
요구한다. 그런데 그 설계(2026-08-19) **이후**의 300 baseline 결정이 복구 경로를 없앴다 —
`scripts/docker-restore.sh`·`docker-restore-verify.sh`·`docker-restore-swap.sh` 셋 다 본문
없이 종료하며 이유를 이렇게 적는다:

    restore is disabled: backup artifacts are audit-only under the 300 baseline
    Alembic archive replay, previous-revision restore, and hot swap are unsupported

즉 검증된 복구 형식이 존재하지 않으므로 이 전제는 **수행 가능한 형태가 아니다.** 같은
방향의 운영 결정이 원장에 이미 있다 — `T-VN-H43`이 "n150은 실 production이 아니며 손상 시
재적재가 정책"이라 적는다. 그래서 restore 축을 활성화 전제에서 **뺀다.**

되살릴 조건: 300 baseline에 맞는 검증된 restore 경로가 생기면 §10.3을 그대로 다시 세운다.
그때 §8.3 재통과는 `scripts/m01_activation_preflight.py`가 그대로 수행한다 — 그 스크립트를
남긴 이유가 이것이다.

**남은 순서 — 2026-09-06 기준 셋 다 수행됐다.**

| 단계 | 결과 |
|---|---|
| (1) 플래그 활성화 | `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=true` (`/opt/kor-travel-docker-manager/.env`, 2026-09-05T20:27:59Z, 백업 `.env.bak-pre-m01-activation-20260905T202759Z`). `environment_sha256`이 바뀌므로 rebuild가 따라왔다 |
| (2a) 거부 축 | `scripts/m01_activation_live_gate.py` — 잘못된 자격 조합 넷이 전부 **403**: 자격 없음 · admin proxy secret만(일반 AdminBFF) · create token만 · proxy secret + 틀린 create token. body는 **유효한 것**을 보낸다 — 422가 아니라 자격 때문에 거부됐음을 보이려면 body 검증보다 자격 검증이 먼저 돌아야 한다 |
| (2b) zero-write 축 | 같은 스크립트가 거부 실행 전후로 witness 8관계(`feature.features`·`feature_places`·`feature_state_transitions`·`manual_feature_identity_claims`·`feature_creation_origins`·`ops.feature_overrides`·`domain_commands`·`domain_command_results`) count를 대조 — **증분 0** |
| (2c) 성공 축 | 플래그가 켜져야 관측 가능하다고 적었던 그것이다. 배포 스택에서 `POST /v1/admin/features` → **201**(2026-09-05 실측). D2 lane이 매 실행 재관측한다 |
| (3) D2 | 이제 503에 막히지 않는다. 잔여는 D2 자신의 lane 완주다 |

**ACL 축은 rebuild 뒤에도 다시 측정했다.** §8.2가 "restore 뒤 동일"을 요구하므로 활성화
rebuild 앞뒤로 각각 돌려 **두 번 다 55/55**였다. 즉 플래그 활성화가 ACL 계약을 흔들지
않는다는 것이 값으로 남아 있다.

**아직 이 배포에서 한 번도 돌지 않은 것.** backup 축은 저장소에 구현돼 있으나
(`scripts/docker-backup.sh`가 4관계 count·PK 순 canonical JSONL SHA-256 root를 manifest에
쓴다) 이 배포에는 backup root 설정도 산출물도 없다(2026-09-06 실측). 활성화 전제로 세지
않지만 사실로 남긴다 — `T-VN-H49` 계열이 소유한다.

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

## T-VN-M03

```markdown
- [~] **T-VN-M03 — curated 동시 생성** (결정 3, 구현 병합). #1029의 `0228` combined
  Feature+curation writer가 SERIALIZABLE 원자성, exact conflict, `manual_curation` origin과
  runtime/Dagster 권한 분리를 고정했다. import 행별 child-command와 격리 live acceptance를 남긴다.
```

**판정: 충족 — 2026-08-31 `docs/tasks-done.md`로 이관.** 남겼던 두 조건이 닫혔다:
import 행별 child-command는 `302_m03_child_issuance` + `curation_repo` 발급 배선
(실 PostGIS 통합 2/2), 격리 live acceptance는
`curation-import-manual-child.live.spec.ts`(n150 격리 스택, 2 passed).

## T-VN-M04

```markdown
- [x] **T-VN-M04 — 범용 Feature 요청 큐** (결정 2, 구현 병합). #1029의 `0233` service submit/admin
  approve·reject queue와 `manual_request` origin, OpenAPI/ACL/restore gate가 정본이다. 첫 consumer
  PinVi #458과 Map #1051 service re-vendor를 반영한 PinVi #465는 병합됐지만 paired
  request→approval receipt와 isolated acceptance는 `T-VN-41C`에서 완료한다.
```

**2026-09-07 전수 조사 — 위임이 dangling pointer다.**

`docs/tasks.md`와 이 문서가 "남은 paired request→approval receipt와 isolated
acceptance는 `T-VN-41C`가 소유한다"고 적어 왔다. 그런데 **§T-VN-41C 어디에도 "M04"가
없다** — 받는 절이 그 범위를 수락한 적이 없다. 게다가 41C는 보류라 잔여를 세지
않으므로, 위임이 유효했다면 이 범위는 아무도 세지 않는 상태였다.

위임한 물건은 이미 산출됐다 — `T-VN-PAIR-V2` §6의 e2e-03 m04 attestation이
`scope: isolated`·`status: passed`이고 `map_pending_receipt_sha256`·
`pinvi_approval_sha256`을 담는다.

**선행**: 위임 문장을 걷고 이 절이 자기 해제 조건을 갖는다. 그 조건은 위 산출물로
판정 가능해야 한다.

**2026-09-07 — 위임을 걷고 판정 가능한 조문을 세운다.**

위임 문장은 dangling pointer였다(위 참조). 아래가 이 절의 해제 조건이며, 전부 이미
산출된 물건으로 판정한다.

```markdown
- [x] **M04-1 — 큐 표면이 병합됐다.** `/v1/service/feature-requests`(SERVICE)와
  `/v1/admin/feature-requests{,/{id},/{id}/approve,/{id}/reject}`(OPERATOR)가
  `route_policy.py`·`openapi.json`에 있고, service 번들(`openapi.service.json`)에는
  service 경로만 노출된다. DB 권한은 submit=service_executor /
  approve·reject=admin_executor로 `runtime_privileges.py`에서 갈린다.
- [x] **M04-2 — origin이 `manual_request`다.** `models.py`의 origin_kind CHECK와
  `feature_request_repo.py`의 `manual_request_v1`, 통합 테스트
  `test_feature_request_submit_then_admin_approval_creates_only_manual_request_feature`
  와 `…_direct_relation_access_and_invalid_payload_are_denied`.
- [x] **M04-3 — restore evidence를 뜬다.** `scripts/docker-backup.sh`가 app snapshot에서
  `feature_requests.jsonl`을 캡처하고 count/sha256을 남기며
  `test_docker_backup_runbook.py`가 고정한다. (restore 쪽이 그 해시를 대조·거부하는지는
  이 절의 범위가 아니다 — backup/restore 축은 `T-VN-H49` 계열이 소유한다.)
- [x] **M04-4 — paired request→approval receipt가 격리에서 실측됐다.** 단일 격리 실행의
  **두 서명**이 같은 `feature_request_id`로 서로를 가리킨다.
  (a) `m04-attestation.json` — `scope=isolated`·`status=passed`·`version=2`,
      `map_pending_receipt_sha256`·`pinvi_approval_sha256`이 marker가 아니라 PinVi API
      재조회로 독립 재계산돼 일치(`_pinvi_m04_approval_snapshot` ↔
      `_validate_m04_ui_marker`), PinVi 컨테이너 라벨이 pinset의 PinVi revision과
      `io.pinvi.build.environment=isolated`에 결박.
  (b) `m05/attestation.json` — `m04_server_side_chain_verified=true`,
      `m04_attestation_sha256`이 (a)의 파일 해시와 동일,
      `m04_map_request_sha256`·`m04_map_provenance_sha256`·`m04_map_feature_uuid`가
      Map `/v1/admin/feature-requests/{id}`=approved와
      `/v1/admin/features/{uuid}/creation-provenance`.origin_kind=`manual_request`에서
      나온 값.
- [x] **M04-5 — reject도 실제로 호출된다.** admin reject가 pending→rejected 전이를 만들고
      사유·resolution command를 보존하며 **Feature를 만들지 않는다**는 것을 통합 테스트
      `test_feature_request_admin_rejection_closes_the_request_without_a_feature`가
      프로시저를 직접 불러 보인다.
```

**M04-4 판정 근거 — `/root/pairv2-e2e-03`** (Manager `0406b14d`, pinset `b229446a`,
Map `2099b8a6`, PinVi `f62e7ef1`):

| | 값 |
|---|---|
| `feature_request_id` | `24cdee5f-ef1a-4876-8be3-7460db79ce05` |
| m04 attestation | `950762d6…` (`scope=isolated`, `status=passed`, `version=2`) |
| m05 attestation | `ac818411…` (`m04_server_side_chain_verified=true`) |
| Map feature uuid | `01a07ab9-a007-74c4-9cf9-4629987034a7` |
| leaf `result.json` | `status=passed`, `phase=completed` |

해시 사슬은 **독립 재계산으로 확인했다** — n150에서 9개 파일을 `sha256sum`해
`result.json`의 값과 대조했고 전부 일치했다(적대 리뷰 2가 수행). `/root/pairv2-e2e-02`
(Manager `d36847e2`)도 같은 형태로 passed다.

**M04-5는 이 조사가 만든 것이다.** reject는 라우터·프로시저·ACL·OpenAPI에 전부
있었으나 **호출하는 테스트가 없었다.** 승인만 검증된 큐는 "거절이 무엇을 남기는지
아무도 모르는" 상태이고, 그대로 닫으면 reject 회귀는 운영에서만 드러난다.

## T-VN-H34

```markdown
- [x] T-VN-H34 — **H25A/H25B 미충족 AC 마무리**

  H25A가 H25B로, H25B가 다시 여기로 넘긴 항목들이다. **어느 열린 task도 소유하지 않는 상태를
  만들지 않기 위해** 명시적으로 모은다.
  - **주소 축 시군구 단위 대조** — ~~미충족~~ → **위 도구에 통합(완료)**. 다만 **천장이 실증됐다**:
    전수 8건의 결함이 **행정구역 축으로는 전부 통과**한다(주차장·카페·펜션이 대상과 같은
    시군구에 있다). 시군구 축은 *기각*에 쓸 수 있어도 *확정*의 충분조건이 아니라는 본문 서술이
    맞았고, **카테고리 축이 추가로 필요하다는 것이 새 발견이다.**
    > **문구 정정(2026-07-29)** — 이 항목을 "`metadata.region`을 시군구까지 본다"로 읽으면
    > **실행 불가**다. `region`은 `강원`·`충북` 같은 **시도 약칭뿐**이라 시군구를 담을 수 없다.
    > 실제로 가능한 축은 **정지오코딩 결과의 시군구코드 ↔ feature `sigungu_code` 대조**이며,
    > 청풍호에서 손으로 한 것이 바로 그것이다(제천 `43150` 일치). 따라서 이 항목은 아래
    > "정지오코딩 세션 고정"과 **같은 도구로 함께** 해결된다 — 별개 축이 아니다.
    >
    > **천장도 같이 기록한다**: 시군구까지 내려가도 같은 시군구 안의 다른 대상은 구분되지
    > 않는다(청풍호 vs 청풍호반케이블카). 시군구 축은 *기각*에는 쓸 수 있어도 *확정*의
    > 충분조건이 아니다.
  - **provider provenance** — ~~설계 또는 불가 확정~~ → **불가로 확정(2026-07-31, 실측)**.
    > CSV 5개 486행은 `provider`/`dataset_key`/`source_item_key`/`source_component_key`가
    > **전부 채워져 있다**. 그런데 그 값이 `provider_sync.source_entities`에 **하나도 없다** —
    > 10종 조합 전부 provider 이름조차 **0 hit**다(`korea-tourism-organization`,
    > `korea-heritage-agency`, `korea-arboreta-and-gardens-institute`,
    > `korea-institute-of-aids-to-navigation`). `source_entities`의 provider는 전부
    > `python-*-api` 계열(`python-mois-api` 977,908 / `data.go.kr-standard` 21,102 …)이다.
    > **CSV의 provider는 캠페인 주관기관이고 source_entities의 provider는 수집 라이브러리라
    > 서로 다른 네임스페이스다.** `source_item_key`(`arboretum-2026-001` 등)도
    > `source_entity_id`/`source_entity_key`/`current_source_record_key` 어디에도 0 hit.
    > 공식 CSV는 provider 파이프라인을 거치지 않고 직접 적재되므로 `source_entities`에 대응
    > 행이 **없는 것이 정상**이다. 조인 경로를 만들려면 기관↔라이브러리 매핑을 발명해야 하고
    > 그건 의미가 없다.
    >
    > **본문 전제 정정** — "미연결 행에서 전부 NULL"은 맞지만 전체 모집단으로 읽으면 틀린다.
    > 실측: active 3,530건 중 `source_record_key` 보유 **3,044건**. NULL은 공식 CSV 적재분
    > **486건**뿐이고 링크 222 / 미연결 264로 갈린다.

    > **정정 (2026-07-31, #910/`0072` 반영) — 내가 틀린 것은 실측이 아니라 범위다.**
    > 위 실측(CSV provider = 캠페인 주관기관 / `source_entities` provider = 수집 라이브러리,
    > 서로 다른 네임스페이스)은 **그대로 유효하고 #910도 같은 판단을 한다** — `0072`가 기존
    > link를 `match_basis='legacy_unattributed'` · `resolver_version='pre-0072-unknown'` ·
    > evidence "기존 link의 선택 근거를 안전하게 복구할 수 없음"으로 backfill한다.
    > 즉 "기존 링크의 근거는 추정하지 않는다"는 결론은 동일하다.
    >
    > 틀린 것은 거기서 **"따라서 이 AC는 달성 불가"로 건너뛴 것**이다. AC 원문은
    > "provider provenance — **설계 또는 불가 확정**"이었는데 나는 "설계" 갈래를
    > **기존 스키마 안에서만** 탐색했다("조인 경로를 만들려면 기관↔라이브러리 매핑을
    > 발명해야 한다"). **스키마 변경을 검토 범위에서 뺀 것이 오류다.**
    >
    > #910이 택한 축은 provider 귀속이 아니라 **import 행위(act) 귀속**이다 —
    > `curation_import_batches`(어떤 바이트를 누가 언제) / `curation_import_rows`(그 batch의
    > 어느 행이 어느 item이 됐는가) / `curation_link_decisions`(그 link를 누가 무슨 근거로
    > accept 했는가). 이 축은 provider 파이프라인을 거치지 않는 공식 CSV 적재에도
    > **정의상 항상 존재한다** — 사람이 파일을 올린 행위 자체가 출처다.
    > 내가 "공식 CSV는 provider 파이프라인을 거치지 않으므로 대응 행이 없는 것이 정상"이라고
    > 쓴 그 문장이 **다른 provenance 축이 필요하다는 신호**였는데, 나는 그것을 AC 종료
    > 신호로 읽었다.
    >
    > 따라서 이 항목은 "불가"가 아니라 **"기존 스키마 안에서는 불가 / 새 축으로 해소(#910)"**다.
  - **preview/commit·REST/UI 실데이터 검증** — ~~미충족~~ → **REST는 실증 완료(2026-07-31)**,
    preview는 **prod 미배포로 측정 불가**.
    > `GET /v1/curations/features/{id}` 실측(prod, service token):
    > `국립세종수목원` **6건**(공식 3 + concierge legacy 3) / `진해보타닉뮤지엄` 1건 /
    > `청풍호` 1건. `GET /v1/features/{id}` 200, `GET /v1/curations/collections` 200에
    > 공식 collection **19건** 공개. **링크는 화면·API에 실제로 반영돼 있다** — 그래서 위
    > 카테고리 결함도 공개 표면에 그대로 노출된다(진해보타닉뮤지엄이 카페로, 청풍호가 펜션으로).
    >
    > **import preview의 H36 게이트 동작은 prod에서 잴 수 없다** — 배포 이미지가 `c8ed6164`라
    > `_adopted_match`가 없고 `0066`의 `external_component_id`도 없다.
    >
    > **2026-08-13 갱신**: 이 blocker는 사라졌다. 두 심볼 모두 head에 있고
    > (`curations.py`의 `_adopted_match`, `curation_repo.py`의 `external_component_id`),
    > 가리키던 `T-VN-H35` 배포는 소멸했다(`tasks-done.md` — "이 항목 아래의 cutover
    > 설계는 전부 이력이다. 실행하지 마라"). 현재 배포 소유자는 `T-VN-35/34/36-deploy`이고,
    > 측정은 `T-VN-36-live`의 격리 clone(실 prod 데이터, `0104`)에서 `dry_run=true`
    > preview 한 번으로 가능하다.
    >
    > 측정 실수 기록: ① 원격 셸에서 명령치환이 깨져 토큰이 비었고 401을 엔드포인트 인증
    > 문제로 오독할 뻔했다(스크립트 파일로 해결). ② 응답 구조가 `data.feature`+`data.curations`인데
    > `data`를 리스트로 기대해 **"0건"으로 잘못 보고**했다. 둘 다 그럴듯한 값이 나와 확인하지
    > 않았으면 틀린 결론이 됐다.
  - **정지오코딩 세션 고정** — ~~신설~~ → **완료**: [`scripts/h25b_verify_links.py`](../scripts/h25b_verify_links.py).
    판정 축 3개(행정구역 시도코드 대조 / **카테고리 정합성**(신규) / 동명 유일성).
    현재는 `--scope public`로 운영 public repository 정본을 훑고, 과거 H25B 내부 승인
    5건은 `--scope approved`로 명시 분리한다. 단위 테스트는
    [`tests/unit/test_h25b_verify_links.py`](../tests/unit/test_h25b_verify_links.py).

    **전수 실행 결과(222건 링크, 2026-07-31)**: 모순 **8건** / 무모순 214건.
    → **처리 완료(2026-08-18)** — 아래 표 뒤 「처리 결과」 참조.
    8건은 전부 **카테고리 축에서만** 걸린다 — 행정구역 축으로는 10건 전부 통과한다.
    고유 feature 5개:
    | curation | feature category | 판정 |
    | --- | --- | --- |
    | `태화강 국가정원`(2캠페인 3행) | `06010000` TRANSPORT_PARKING | 그 관광지의 **주차장**에 붙음 |
    | `반디랜드&태권도원`(2행) | `06010000` TRANSPORT_PARKING | 동일 |
    | `김해가야테마파크` | `06010000` TRANSPORT_PARKING | 동일 |
    | `진해보타닉뮤지엄` | `02020100` FOOD_CAFE_COFFEE | 카페에 붙음 |
    | `청풍호` | `03050200` LODGING_PENSION_RURAL | 농어촌펜션에 붙음 |

    **장소는 맞고 유형이 틀린 것**이다(좌표·주소가 대상과 일치). H33이 해제한 3건처럼
    *다른 장소*에 붙은 오링크가 아니므로 **링크 해제가 아니라 올바른 feature로 재연결하거나
    카테고리를 고치는 것**이 맞다.

    ### 처리 결과 (2026-08-18)

    사용자 승인은 **"올바른 Feature로 재연결"**이었다. prod에서 후보를 전수 조사한 결과
    **재연결이 가능한 것은 5개 중 1개뿐**이었다. 승인에 "맞는 Feature가 DB에 없으면 결국
    해제로 떨어진다"가 명시돼 있어 그 fallback을 따랐고, 한 건은 **어느 쪽도 아닌 것**으로
    판정했다.

    | 항목 | 조사 결과 | 처리 |
    |---|---|---|
    | `김해가야테마파크` | `f_global_p_54ab91…` **`01010400`(관광지)** 존재 | **재연결** |
    | `태화강 국가정원` | 정원 자체가 DB에 없다 — 주차장 6개와 "…태화강국가정원점" 식당들뿐 | 해제(3행) |
    | `반디랜드&태권도원` | 후보 0건(질의 결과 빈 집합) | 해제(2행) |
    | `청풍호` | 전망대(`01050300`)·케이블카(`01080200`)는 호수가 아니라 호수의 **시설** | 해제(1행) |
    | `진해보타닉뮤지엄` | **링크가 맞다** — 이름·주소가 정확히 그 박물관이고 Feature가 하나뿐 | **유지** |

    `01010400`이 관광지 축인 근거(prod place 표본): 죽성드림성당세트장 · 연미산 자연 미술
    공원 · 머루 와인 동굴 · 깡깡이 예술마을 · 메타버스 체험관. 후보였던 `01000000`은
    관광지가 아니다 — place 표본이 사계절즉석국수 · 부전동촌국수 · 서가원이다.

    **진해보타닉뮤지엄을 해제하지 않은 이유.** 해제는 "이 항목에 맞는 Feature가 없다"는
    뜻인데 여기서는 맞는 Feature가 **있고 링크도 그것을 가리킨다**. 틀린 것은 그 Feature의
    category다(MOIS가 휴게음식점으로 인허가). 해제하면 맞는 링크를 지우고 문제는 그대로
    남는다.
    - [~] **T-VN-H34A — Feature category 보정** — MOIS 인허가 업종이 실제 시설 성격과 다른 경우.
      2026-08-27의 [책임 경계 조사](reports/t-vn-h34a-category-ownership-audit-2026-08-27.md)는
      source category를 Map에서 덮어쓰지 않는다는 결론을 확정했다. 다음은 승인된 read-only
      source snapshot에서 같은 패턴의 후보·원천 record reference를 전수화하고, 각 후보를
      provider 정합성 수정 또는 별도 Map 표시/큐레이션 정책 설계로 분리하는 일이다. 박물관·미술관이
      부속 카페 인허가로 `02020100`에 묶이는 사례를 keyword 자동보정하지 않는다.

    **부수로 고친 것 — manifest 카운트가 파생되지 않았다.** `refresh_manifest`의 docstring이
    "손으로 유지하면 CSV를 고칠 때마다 어긋난다, 그러니 **파생시킨다**"고 하는데 실제로
    파생하는 것은 `sha256`·`rows`뿐이었다. `linked_rows`/`unresolved_rows`는 손으로
    유지됐고, CSV 7행을 고친 뒤 스크립트를 돌려도 카운트가 **222 그대로**였다. 그 값이
    `_h35_csv5.py`의 `csv5_manifest_counts_mismatch` 게이트 입력이라 방치하면 게이트가
    거짓말을 한다. CSV에서 파생하도록 고쳤고(216/270) `EXPECTED_CSV_ACCEPTED`도
    222 → **216**으로 맞췄다 — 적대 검증이 "이 상수와 충돌해 shipped 코드가 죽는다"고
    지목한 지점이다.

    - [ ] **T-VN-H34B — prod curation import 반영.** CSV는 저장소 정본이고 실제 링크는 curation import가
      반영한다. import를 돌려야 공개 표면(3,265건)에서 사라진다.

    > **판정 로직을 두 번 고쳤다(기록)**. ① 동명 다수를 *모순*으로 셌다 → 222건 중 30건이
    > 모순으로 잡히고 그중 20건이 이 축 단독이었다. 동명 다수는 반증이 아니라 **그 축으로
    > 확정할 수 없다**는 뜻이다(30→10). ② 카테고리 기대를 `01`(TOURISM)만으로 좁혔다 →
    > `장태산자연휴양림`·`거창 항노화힐링랜드`(`03030000` LODGING_RECREATION_FOREST)가
    > 오탐이 됐다. 숙박을 갖춘 휴양림이 그렇게 분류되는 건 정당하다. 축을 "관광이어야 한다"에서
    > **"명백히 대상일 수 없는 유형인가"** 로 뒤집었다(10→8). 두 회귀 모두 단위 테스트로 고정했다.

> **issue #673 이력** — 이슈는 2026-08-07에 닫혔다. 당시의 457건·`0072` 관련 판정은
> 현 prod 상태를 설명하는 기준이 아니며, 남은 Feature category 보정·저장소 CSV의 prod import는
> 열린 `T-VN-H34A/B`가, 새 Feature 생성 경로는 `T-VN-M00`~`M03`이 소유한다.

### T-VN-H42~H45 — 운영 연속성 (0072 사고 후속: 재적재 수렴 → 강건화 → 백업 → 복원 드릴)

> 2026-08-04 prod 폐기·재생성(head `0078`) 후속. 2026-08-05 이미지 `c0afaa4e` 배포로
> head `0082`(UUID shadow 3종) 적용 완료 — **다만 2026-08-13 실측 prod head는 `0087`이고
> feature는 1,008,852행이다**(이 문단이 5 revision 뒤처져 있었다). 따라서 최신 H43
> baseline `2026-08-05-h43-postdeploy-0083.dump`(731,765행)는 두 head·약 27만 행 뒤처진
> 복구점이며, `0104`가 `feature_versions`/`data_origin`/`feature_change_requests`를
> 물리 삭제하므로 H44의 복원 실증도 `0083` 기준이라는 점을 함께 읽어야 한다.
> prod는 `archive_mode=off`라 **PITR이 없다 — dump가 유일 복구점**이다. codex 소관 41C prod enable은 H42 판정 + docker-manager
> 재pin 뒤(Lane B T-VN-41 절 경계 주석).
```

**2026-09-07 전수 조사 — 남은 두 조건이 존재하지 않는 데이터를 전제한다.**

n150 `kor_travel_map`은 2026-09-07 03:23 UTC에 pinned rebuild가 새로 만든 **빈 DB**다
(`feature.features` 0행). 남은 H34A(전수 후보 조사)와 H34B(prod import)는 둘 다 prod
데이터를 전제하므로 지금은 판정 자체가 불가능하다.

그리고 "재적재하면 된다"가 성립하지 않는다 — **pinned rebuild가 매번 application DB를
새로 만든다.** 재적재는 다음 rebuild까지만 유효하므로, lifecycle을 바꾸지 않는 한
prod 데이터를 전제한 해제 조건은 구조적으로 닫히지 않는다.

코드는 남아 있지 않다 — preview/commit 엔드포인트, provenance 3표, manual-feature
writer, kill-switch 전부 배포 완료다.

**소유자 판정.** 범위를 저장소 CSV 수준으로 재정의할 것인가, 아니면 lifecycle 변경을
선행 항목으로 세울 것인가.

**2026-09-07 소유자 판정 — 범위는 저장소 CSV까지다. 그 범위에서 닫는다.**

prod 데이터를 전제하던 조건들은 **구조적으로 닫히지 않는다** — pinned rebuild가 매번
application DB를 새로 만들기 때문에 재적재해도 다음 rebuild까지만 유효하다. 소유자가
범위를 저장소 CSV 수준으로 한정했다.

**범위 안 — 충족(4/4).**

| 조건 | 근거 |
|---|---|
| (1) 주소 축 시군구 대조 | `scripts/h25b_verify_links.py:210-313`의 `_sigungu_*`와 `axes["sigungu"]` 판정 + `tests/unit/test_h25b_verify_links.py` |
| (2) provider provenance | #910 import-act 축으로 해소 — `alembic/versions/301_m03_import_manual_feature_children.py`, 배포 DB에 세 표 실재 |
| (4) 판정 축 3개 도구화 | 같은 스크립트의 행정구역·카테고리·동명 유일성 3축(`--scope public/approved`) |
| (5) 카테고리 모순 8건 처리 + manifest 파생 | CSV 실측 — 재연결 1(김해가야테마파크)·유지 1(진해보타닉뮤지엄)·해제 6, `manifest.json` linked 216 / unresolved 270 |

**범위 밖으로 밀려난 것 — 지우지 않고 여기 남긴다.**

아래 넷은 **미완이며, 재개하려면 lifecycle 판정이 선행한다**(현 rehearsal/rebuildable
lifecycle에서는 prod 데이터가 rebuild마다 사라진다). 다시 세울 때 이 목록에서 꺼낸다.

- (3) preview/commit·REST/UI **실데이터** 검증 — 현 prod는 `curation_items` 0행,
  `curation_collections` 0행이라 같은 응답이 나올 수 없다. 원장이 지정한 측정 수단
  `T-VN-36-live`의 기반 `0104` 계보는 `300` baseline이 흡수했다.
- (6) `T-VN-H34A` 카테고리 충돌 후보 **전수화** — 책임 경계 조사(#1082)만 병합됐고,
  다음 단계는 `feature.features` 0행·`provider_sync.source_records` 0행이라 수행 불가.
- (7) `T-VN-H34B` prod curation import — 전제("공개 표면 3,265건에서 6행이 사라진다")가
  이미 거짓이다. FK `curation_items_feature_id_fkey` 때문에 features가 빈 동안 CSV의
  linked 216행은 착지할 수 없다. **실행 경로 자체는 배포돼 있다.**
- 잔여 절 "없는 것은 Feature로 추가"(태화강 국가정원·반디랜드&태권도원·청풍호 3건) —
  수단은 갖춰졌다(`CURATION_CSV_OPTIONAL_HEADERS`, `ops.curation_import_manual_feature_children`,
  배포 API의 manual-feature create 활성). 실행이 prod 데이터에 걸린다.

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

## Lane C 상세 — 사문화 정리·미구현 dataset (2026-08-17 신설)

> 다른 lane과 barrier를 공유하지 않는다. 아무 때나 착수할 수 있다.

### C7 후속 검증 잔여
```

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

## 이슈 종결 추적

> landing task와 완료 조건이 동일한 열린 이슈만 함께 닫는다. LIVE-01 후속 OPEN 7건은 Lane A
> `T-VN-H16`/`T-VN-H17`에서 독립 재검증해 **7건 전부 close**했다. 6건은 H16
> (dm#63·#70·map#712·#719·#777·#694), map#684는 H17에서 조건 #8을 "write/error UI 엣지는
> mock, read·URL·freshness + write 계약은 live"로 명시 축소한 뒤 close했다.

- **task로 승격**: map #673=`T-VN-H28A/B`, map #819=`T-VN-H27`(2026-08-22 종결·`tasks-done.md` 이관).
- **종결**: map #738은 lane 분배 정본을 본 문서로 이관해 닫혔다. map #930(geo key
  미결선 — dagster job 고착)은 docker-manager compose 결선(#114 트랙) + 3 컨테이너
  env 실측 + krex job 연속 SUCCESS로 2026-08-05 close.
### T-VN-H49 — 4분할 인스턴스 백업 운영 잔여
```

## T-FE-MOCK-FLAKE

```markdown
- [x] **T-FE-MOCK-FLAKE** — mocked checkpoint 해소, n150 live GET-only 잔여

  **초기 관찰(2026-08-21)**: System logs 표의 첫 columnheader `생성`이 15초 안에
  보이지 않았다(`admin-ops.spec.ts:744`, 당시 위치). 앞선 filter control 단언은 모두
  통과하므로 표 mount 전에 header를 단언하는 순서 문제로 보였고, n150 5회 실행 중 2회
  실패했다. 부하가 높을 때 재현됐으며 mocked config가 `retries: process.env.CI ? 1 : 0`이라
  **로컬은 재시도가 없어** 느린 렌더가 곧 실패가 됐다.

  당시 이 spec은 완료된 C7 browser evidence 이식이 건드리지 않았고 mocked checkpoint는
  CI 잡이 아니라 수동 게이트였다. 따라서 표/행이 도착한 뒤 header를 단언하도록 고정하고,
  재시도로 덮지 않는 방향으로 처리했다. 아래 PR #1059에서 실제 mock 응답 부재까지 해소했다.
  2026-08-21 PR #1045에서 표별 locator scope와 body row 준비 대기, `aria-busy` 해제 대기를
  추가했다(`09d47cf7` → `d208b76a`). 전문 리뷰어 2명이 누적 diff를 재검토해 P0/P1/P2
  0건을 확인했다. 이후 self-owned mock backend가 로그 두 stream을 응답하지 않아
  `aria-busy=true`가 15초 유지되던 경계를 PR #1059에서 생성 OpenAPI 타입 기반 BFF mock으로
  고정했다. targeted `/v1/ops/logs` 1회와 5회 반복(총 6/6)이 통과했다. mocked checkpoint
  부분은 해소됐다. 이후 기준선 경계 정리로 현재 suite가 284개가 됐는데 failure manifest가
  285개로 남아 reporter gate를 fail-closed 한 drift를 PR #1077에서 재고정했다. exact clean
  checkout의 self-owned checkpoint D는 284/284 passed, manifest 일치, reporter gate true와
  runner exit 0으로 끝났고, owned container·network·image·임시 runtime은 모두 정리됐다.
  2026-08-26 n150에서 현재 local-only 런북 자격증명으로
  `logs.live.spec.ts`만 `--workers=1 --retries=0`으로 다시 실행했으나, auth setup이
  다시 `401`으로 중단되어 두 `GET` 전용 본문은 시작하지 않았다. 임시 브라우저 세션·실패
  산출물은 즉시 폐기했다. 따라서 현 배포 runtime과 일치하는 승인된 읽기 전용 자격증명과
  허용 origin을 값 비노출으로 제공받은 뒤에만 재개한다. 자격증명을 추측·회전·우회하거나
  기존 스모크 자격증명을 재사용하지 않는다.
- `T-C7-SCOPE-REGISTRY`와 `T-C7-LIVE-SERIAL`은 PR #1038에서 완료했다. scope 선언
  주체·조회 표면을 `integration-map.md` §3.7과 ADR-088 결과에 정본화했고,
  `external_system:c7-e2e` live write 3종에는 cross-worker `mkdir` 잠금을 결선했다.

**2026-09-07 전수 조사 — 아래 §의 2026-08-26 서술이 낡았다. 그러나 항목은 열려 있다.**

낡은 부분: "auth setup이 401로 중단되어 두 GET 전용 본문이 시작조차 못 했다"는 현재
사실이 아니다. n150 실측으로 `logs.live.spec.ts:30`(system/API 목록 실제 REST 렌더)과
`:50`(필터·페이지 크기 GET-only 조작)이 배포 스택에서 **4회** 통과했다 —
`~/d1-live.log`(2026-09-04, `11 passed 1.3m`), `~/d1-live-{c72456f6,bbd65766,2127bcf7}.log`
(09-05~06, 각 `11 passed`). 전부 `Running 11 tests using 1 worker`이고 CI env 미설정이라
`retries: 0`이다.

낡지 **않은** 부분: 그 실행이 이 항목을 닫지는 않는다. 2026-08-26 기록이 같은 겹침을
이미 검토하고 **명시적으로 기각**했다 — "H46H의 data-independent 실제 UI 11개 통과를
무효화하지 않지만, 실제 logs acceptance를 완료로 승격할 근거도 아니다". 해제 조건은
"승인된 **읽기 전용** 자격증명"을 요구하는데 D1 스모크는 admin 자격증명으로 돌았다.

mocked 절반은 HEAD에서 재확인했다 — `e2e/mocked-failure-manifest.json`의
`discoveredTests` 284와 `testInventorySha256`이 현 suite와 exact 일치한다.

**소유자 판정.** admin 자격증명으로 돈 D1 스모크가 조문의 "승인된 읽기 전용
자격증명" 요건을 갚는가. 갚지 않는다면 그 자격증명은 소유자만 줄 수 있다.

**2026-09-07 소유자 판정 — D1 실측이 자격증명 요건을 갚는다. 항목을 닫는다.**

AC7이 요구한 "배포 runtime과 일치하는 승인된 자격증명 + 허용 origin"은
`T-VN-41F1D-D1` 실행이 갚는다는 판정이다. 그 실행에서 `[setup] authenticate admin (live)`이
통과했고(로그인 POST 200 = 공개 origin 허용까지 통과), 자격증명은 0600 파일로만 두고
실행 후 삭제됐으며 로그에 남지 않았다(`grep -c PASSWORD = 0`).

**충족 근거.**

| 조건 | 상태 | 근거 |
|---|---|---|
| AC1 mocked flake 근본 수리 | 충족 | `admin-ops.spec.ts`의 표별 locator scope + `aria-busy` 해제 대기(PR #1045) |
| AC2 생성 OpenAPI 타입 기반 BFF mock | 충족 | PR #1059. `e2e/tsconfig.json`이 mock을 `src/api/types.ts`에 컴파일 타임 결박하고 CI `type-check`가 매 PR 검사 |
| AC4 reporter gate drift 해소 | 충족 | **HEAD에서 재계산 확인** — `mocked-failure-manifest.json` `discoveredTests` 284, `testInventorySha256`이 현 suite와 exact 일치 |
| AC6 n150 live GET-only 실행 | 충족 | `logs.live.spec.ts:30`·`:50`이 배포 스택에서 **4회** 통과(`~/d1-live.log` 외 3건, 각 `Running 11 tests using 1 worker`, CI env 미설정이라 `retries: 0`) |
| AC7 승인된 자격증명 | **충족(소유자 판정)** | 위 |

**남는 잔여를 감추지 않는다.** AC3(mocked targeted 6/6)과 AC5(284/284 전량 통과)의
receipt는 2026-08-21~26 것이고, 그 체크아웃은 현 HEAD보다 frontend/src 커밋 5개 뒤다
(`8078b110` `/v1/debug` 표면 제거 등이 `src/api/types.ts` 158줄·`src/lib/proxy.ts` 17줄을
바꿨다). mocked checkpoint는 CI job이 아니라 **수동 게이트**라 자동 재검증이 없다.

그 위험을 기계가 덮는 범위는 분명하다 — CI `type-check`가 매 PR에서 mock↔생성 타입
drift를 잡고, AC4의 manifest 결박은 HEAD에서 방금 재계산했다. 덮지 못하는 것은
"현 HEAD에서 284개가 실제로 통과하는가"이며, 그것이 이 항목의 잔여 위험이다.

## Lane B 상세 — b1 PinVi 결합·후속

### T-VN-41 — cache-target generation·outbox 전파

> PR [#975](https://github.com/digitie/kor-travel-map/pull/975)는 merge
> `4672aa966cd473f17fd4f69ee8066276f7be900d`로 병합됐고 CI 8개가 모두 성공했다.
> source generation·restore epoch(`T-VN-41A`)과 transaction-coupled outbox writer
> (`T-VN-41B`)는 독립 완료로 이관했다. 남은 `T-VN-41C`는 final exact-pair evidence와
> production consumer enable·reconciliation 종결 AC를 소유한다.
```

## T-VN-39 — **완료(2026-09-11, #1197 `e8c66c47`)**

> 이 절은 판정 근거로 남긴다. 착지 실측은 아래 "착지 확인"이고, 후속 셋은
> `T-VN-39-DEPLOY` · `T-VN-39-ECHO` · `T-VN-39-PROVIDER-PAGINATION`이 소유한다.

**착지 확인(head-schema 실측).** feature_id류 컬럼 52개가 uuid이고, text로 남은 셋은
정당한 생존자다 — `manual_feature_purge_records.legacy_feature_id` ·
`ops.tvn36_legacy_freeze_preflight_manifest.legacy_feature_id` · plpgsql 지역변수
`v_legacy_feature_id`. shadow `feature_uuid` 컬럼 0개.
`ck_feature_aliases_legacy_alias_shape`가 주소 등록부를 지킨다.
게이트: GitHub CI 9종 전량 · n150(provider 실제 설치) dagster 575 · api 1,223 ·
lint+unit 2,832 · 제품 SQL 786문 head Parse · live(DB→API→브라우저, 필터 3갈래
200/200/422).


```markdown
- [ ] T-VN-39 — **KTM·PinVi write-fence cutover**

  consumer-first 배포, write fence와 순차 전환을 수행한다. **T-VN-33C의 legacy
  column/index/route/repository/trigger/table은 서비스 전 단계 원칙에 따라 같은 final-schema
  migration에서 이미 물리 삭제한다.** 따라서 이 task는 T-VN-33 보존·rollback·removal을
  소유하지 않는다. 이후 task가 만든 held component만 그 task의 manifest와 함께 판단하며,
  intermediate data는 backup/restore가 아니라 최종 schema ETL로 재생성한다.

**2026-09-07 전수 조사 — 유일한 실질 blocker는 미구현 대체물이다.**

removal manifest (c)의 대체물 `provider_sync.notice_states`가 **구현된 적이 없고, 그
구현을 소유하는 열린 항목이 없다.** 대체 대상 두 테이블은 현행 정상 writer 경로이므로
그것부터 옮기지 않으면 물리 제거가 성립하지 않는다.

규모 실측(prod): text/varchar `%feature_id%` 컬럼 40개, `feature.features` 참조 FK
34개, `feature_id`를 언급하는 인덱스 57개, baseline `schema.sql`에서 `feature_id`
언급 900줄. **이 백로그에서 가장 큰 축이다.**

manifest (b) provider_sync source lineage는 **이미 제거 완료**이므로 충족 처리해도
된다.

**2026-09-08 소유자 판정 — 계약을 개정해 (c)를 뺐다.**

**대체를 정당화한 결함이 이미 없다.** manifest 항목이 대는 이유는 하나,
"문자열 시각 판정"이다. 그런데 두 표의 시각 컬럼은 전부 typed다 —
`notice_lineage_states.changed_at`·`valid_until`, `notice_lifecycle_scopes.applied_at`이
모두 `timestamp with time zone`이고 writer도 `CAST(:closed_at AS timestamptz)`와
`>= scope.applied_at`로 typed 비교를 쓴다. 저장소에 남은 `pg_input_is_valid`는
`_frozen_h35_ended_notice_hidden_sql` 하나뿐이고, 그것은 0079 세대 표면을 리허설용으로
**일부러 글자 그대로 보존한** 함수다(그 docstring이 "현행 코드가 이 형태를 되살리는 것을
막기 위해 이 함수 안에만 존재한다"고 적는다). 즉 살아 있는 결함이 아니라 박제다.
문자열 시각 판정은 `T-VN-35B`와 `T-VN-37D`가 이미 없앴다.

**fence가 처음부터 없었다.** 이 항목의 `fenced_by`는 `T-VN-37B`인데 그런 항목은 원장에
**존재한 적이 없다.** 다른 여섯 entry는 전부 실재하는 fence를 가리킨다(34C·32C·33C·
36D·38C·40C) — (c)만 유일하게 fence 없이 등록돼 있었다. 그 fence가 소유했어야 할
`tstzrange` 표현은 `T-VN-37D`가 다른 표(`feature.feature_notices.valid_during`)에 이미
착지시켰다.

**새로 짓는 쪽의 값이 없다.** `notice_states`가 주는 것은 정규화(`valid_during` +
`is_current` 부분 유니크 + GiST)인데, 그 값을 사려면 살아 있는 writer 경로
(`feature_repo.py:3226-3500`)를 통째로 재작성하고 freeze 계약을 재계산해야 한다. 그런데
두 표 모두 **prod 0행**이고, 성능 문제는 `T-VN-37`이 이미 해결했다(20.4초 → 0.19초,
118.4초 → 0.36초). 해결된 문제를 위해 살아 있는 경로를 재작성하는 셈이고, 그 근거 문장은
이미 거짓이다.

**목표 상태 기술은 지우지 않는다.** `contracts/vnext/target-schema-v1.sql`의
`notice_states` DDL과 invariant는 "**채택되지 않음**" 표시만 달고 남긴다 — 정합성 요구가
생기면 다시 꺼낼 값이 있고, 지우면 같은 논의를 처음부터 다시 해야 한다(오늘
`b2543d68`이 지운 실측 기록을 되살린 것과 같은 이유다).

**이 판정이 틀릴 수 있는 지점.** `notice_states`가 성능이 아니라 **정합성**을 위한
것이었다면 판단이 뒤집힌다 — `is_current` 부분 유니크와 range 중첩 금지는 지금 두 표가
선언적으로 강제하지 못하는 불변식이다. 다만 그것을 요구하는 조문을 저장소에서 찾지
못했고, manifest가 대는 이유도 "문자열 시각 판정" 하나뿐이었다.

**2026-09-09 실측 — 본체는 재타입이 아니라 멱등 앵커 교체다.**

`feature_id`를 uuid로 바꾸면 둘 중 하나가 **반드시** 일어난다. provider가 계산한
`f_*`를 그대로 보내면 22P02이고, 새 UUIDv7을 보내면
`create_feature_with_initial_state`의 `ON CONFLICT (feature_id) DO NOTHING`이 **영원히
걸리지 않아** 매 ETL마다 중복 Feature가 생긴다. 후자는 DDL 초록·1회 적재 테스트 전부
초록이고, 증상은 **두 번째 ETL**에서 처음 나온다.

**앵커 축을 두 번 틀렸고 두 번 다 실측이 잡았다.**

1차(09-08): `provider_sync.source_links`의 `source_role='primary'`에
`UNIQUE (source_entity_key)`를 심었다가 **통합 1179건 중 17건이 빨개졌다** —
identity 이행 중에는 구·신 Feature가 둘 다 primary이고
`tests/integration/test_notice_lifecycle.py:529`가 그 형태를 의도적으로 재현한다.

2차(09-09): 되돌린 뒤 조사가 **축 자체가 틀렸다**는 것을 보였다.
`src/kortravelmap/providers/opinet.py`는 `source_entity_id`가 제품별
(`f"{uni_id}:{prodcd}"`, :689)이고 `source_natural_key`는 주유소별(`uni_id`, :697)이며,
그 경로 docstring이 "단일 제품 가격을 **같은 price anchor feature에 누적**"이라
명시한다(:762). entity → Feature가 정당하게 **N:1**이므로, entity를 축으로 삼으면 새
제품코드마다 새 Feature가 주조된다 — 재키가 고치려던 중복을 재키가 만든다.

**확정 축**: `(provider_dataset_id, feature_kind, natural_key)`.
`make_feature_id` 입력(`bjd_code|kind|category|source_type|source_natural_key`)에서
ADR-068 결정 2가 배제하라고 한 `bjd_code`·`category`만 뺀 것이다. 착지처는
`provider_sync.provider_feature_identities`(308)이고, `feature.features`로 가는 FK를
두지 않는다 — claim이 Feature보다 먼저 서야 하기 때문이며
`feature.manual_feature_identity_claims`가 같은 이유로 같은 모양이다.

**규모**는 숫자를 박지 않는다(2026-09-08의 "인덱스 57"이 실측 59와 어긋났다). 산출
쿼리로 둔다 — `information_schema.columns`의 `%feature_id%` 비-uuid 컬럼,
`pg_constraint`의 `confrelid='feature.features'::regclass`, `pg_indexes`의
`feature_id|feature_uuid` 언급.

**부수 발견**: `tests/integration/test_khoa_{rekey_hardening,recategorize_cleanup}.py`는
제품 코드를 0줄도 타지 않았다 — `_cleanup_sql()`이 아카이브 상수를 읽어 부분문자열만
확인하고 자기 파일의 SQL을 반환한다. 삭제했고, 삭제 전후 유닛·lint가
`244 failed / 2508 passed`로 동일했다.

**남은 것.** 이 항목의 소유자 판정 대기는 사라졌다. `T-VN-39`에 남는 것은 legacy TEXT
`feature_id` PK 제거 하나이고, **그것은 판정 대상이 아니다** — 대체 identity
(`feature_uuid` + unique 둘)와 fence 트리거가 이미 prod에 있고 `feature.features`가
0행이라 데이터 이행 위험이 없다. 남은 것은 컬럼 37 · FK 34 · 인덱스 57의 rekey 공학이다
(2026-09-07 조문이 적은 "컬럼 40개"는 `pg_catalog`/`information_schema`를 뺀 실측에서
37개다).

## T-VN-39-DEPLOY

```markdown
- [x] T-VN-39-DEPLOY — **재키 착지본 prod Map 배포와 D2 재핀** (2026-09-12 완료)
```

**무엇이 참이면 닫히는가.**

1. [x] prod Map이 `e8c66c47` 이후 revision으로 돌고, `alembic_version`이 `309`다.
   — 2026-09-11 실측: live 컨테이너 revision `3891f632`(= main),
   `head=309_t39_feature_id_rekey`, `feature.features.feature_id`가 `uuid`,
   `/health` 200. pinned rebuild는 `success/committed`, pinset `98ae83df`.
2. [x] D2 재핀 사이클이 완주한다 — rotate → rebuild → 이미지 → repin → preflight →
   D1 → D2. 각 단계 증적이 남는다. — **2026-09-11 완주.** 회전(pinset `98ae83df`)·
   rebuild(`success/committed`, head `309`)·executor 이미지(라벨 `3891f632` 일치)·
   repin·M01 ACL preflight(**55/55**)·D1(**11 passed**)·
   **D2(`phase: passed`, `status: complete`, `recovery_attempt: 0`)**.
   `validation.json`이 `evidence-validated`(mode normal, reports_passed 2,
   FK 제약 23), `direct-api-audit.json`이
   `feature_ids == feature_uuids == ["01a09088-…"]`(canonical UUIDv7) +
   `foreign_key_references: 7`. 사후 prod 잔여물 0.

   **다섯 겹이었다.** legacy 주소를 `uuid[]`에 바인드 → 309가 지운 create payload
   슬롯 → 309가 지운 컬럼 투영 → 사라진 legacy 재현 규칙 → 306이 봉인한 raw DELETE.
   앞의 셋은 사이클을 태워 가며 드러났고, 마지막 두 겹(증거 검사기 둘)은 **적대
   리뷰가 사이클 전에** 잡았다 — 그 둘을 모르고 돌렸으면 70분을 더 태웠다.
3. [x] PinVi token pair 규약을 지킨 배포다(rebind 없이). — 네 번의 회전 모두 PinVi
   revision을 핀 원장에서 그대로 가져왔고(`f62e7ef1`), 세 OpenAPI 표면이 바이트
   동일이라 재벤더링이 필요 없었다. `pinvi-pair deploy`/`rebind`를 부르지 않았다.
4. [x] 배포 뒤 provider 적재 asset이 최소 한 바퀴 돌아 claim·alias가 실제로 발급된다 —
   재키의 핵심 축이 운영 데이터에서 성립하는 것을 본다. — **2026-09-12 충족.**

   `feature_place_standard_museums_job`이 prod에서 적재를 끝냈다. 여섯 축이 정확히
   맞물린다 — `entities=1047 · heads=1047 · links=1047 · features=1047 ·
   claims=1047 · aliases=1047`(`records=1072`는 entity당 버전이 쌓인 것이고, head가
   가리키는 record는 결측 0). 고아·불일치 여섯 검사 **전부 0**이다:
   feature 없는 link·claim·alias, link 없는 feature, **claim 없는 feature**, 없는
   record를 가리키는 head.

   그리고 그 값들이 재키가 설계한 축 그대로다:

   - **claim** = `(provider_dataset_id, feature_kind, natural_key) → feature_id`
     (예: `dataset=2 kind=place natural_key=대전대학교박물관::… → 01a092b5…`).
     `ON CONFLICT (feature_id)`의 결정적 축이 사라진 자리를 이것이 대신한다(ADR-098).
   - **legacy `f_*`는 주소로 생존** —
     `f_1111010600_p_98434503e9869507 → 01a092b7…`.

   **2026-09-12 정정.** 이 조문을 한 번 "막혀 있다"로 적었다. run 상태가 FAILURE였고
   compute-log 쓰기 실패가 로그에 있었기 때문인데, **데이터를 보지 않고 run 상태만
   보고 판정했다.** 적재 트랜잭션은 온전히 커밋돼 있었다. `T-VN-DAGSTER-STORAGE`는
   실재하는 결함이지만(run이 FAILURE로 표시되고 compute log가 남지 않는다) 적재를
   막고 있던 것은 아니다.

   지나온 겹은 넷이었다: 특화거리 상류 미승인(소유자 제외), `KREX_GO_API_KEY`
   미주입(주입), seal ACL 유실(`T-VN-CURATION-SEAL-ACL` 수정·배포), 그리고 내 호출
   방식(`asset materialize`는 operation key 태그를 싣지 않는다 — 정식 경로는
   `dagster job launch`이고 key는 job 이름이다).
   2026-09-11 첫 적재가 `permission denied for function
   current_provider_curation_input_set`로 멈췄다(`T-VN-CURATION-SEAL-ACL`). 그 앞의
   두 시도는 상류 문제였다 — 특화거리는 data.go.kr 활용신청 미승인(403,
   `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`, 데이터셋 15017322), krex 휴게소는
   `KOR_TRAVEL_MAP_KREX_GO_API_KEY` 미주입(2026-09-11 채웠다 — 값은 이미 호스트에
   있던 data.go.kr 키와 같다).

   **특화거리(data.go.kr 15017322)는 소유자 판정으로 제외한다(2026-09-11).** 활용신청이
   승인되지 않아 403(`SERVICE_KEY_IS_NOT_REGISTERED_ERROR`)이고, 신청을 기다리지 않는다.
   이 조문은 **다른 asset 하나**로 충족한다 — 같은 키로 관광지·박물관미술관·주차장·
   문화축제 넷이 이미 200을 받는다(2026-09-11 전수 실측).

   **2026-09-11 — 네 겹을 지나 다섯째에서 멈췄다.** 성격이 전부 달랐다: 특화거리는
   상류 미승인(위 판정), krex는 `KREX_GO_API_KEY` 미주입(주입 완료), 박물관은 seal
   ACL 유실(`T-VN-CURATION-SEAL-ACL` — 수정·배포·실측 완료), 그다음은 내 호출 방식
   (`asset materialize`는 operation key 태그를 싣지 않는다; 정식 경로는
   `dagster job launch`이고 key는 job 이름이다). 정식 경로로 제출한 run은
   `/opt/dagster/dagster_home/storage` 쓰기 불가로 실패했다 —
   **`T-VN-DAGSTER-STORAGE`**가 그 축을 소유하며, 이 조문은 그것에 막혀 있다.

   ACL 수정이 실물로 들었다는 것은 별도로 확인했다 — 배포 후 적재 login은 seal을
   실행할 수 있고(`true`) API login은 못 한다(`false`). 자매 claim 해석기는 API도
   `true`이므로 그 대비가 좁힌 grant가 경계를 지켰음을 보인다.
5. 배포 뒤 정본 generation(`/var/lib/kor-travel-docker-manager-public/`
   `pinned-runtime-generation-v6.json`)의 `map_source_revision`과 네 image id가
   **실제로 돌고 있는 컨테이너와 같다.** 이 검사를 여기 두는 이유는 2026-09-11에
   그 둘이 조용히 갈라진 적이 있기 때문이다 — 정본은 `2099b8a6`/`c10d6782`를
   가리키는데 live는 rehearsal state가 얹은 `cf65e973`/`0169fe90`이었다.
   레지스트리는 배포를 기록하지만 **실물을 강제하지는 않는다.**
   — 2026-09-12 최종 실측: live revision `488a29e1`(= main), image 5종 **불일치 0**.

**회전 전제조건.** 회전은 `rotate-pinned-pair MAP PINVI`로만 들어간다. `PINVI`에는
**핀된 revision**(`ktdctl pin show`의 `pinvi`)을 넘긴다 — PinVi `origin/main`은 아직
pair 계약 v1이라 preflight가 `pair contract version is unsupported: 1`로 거부한다.
v2 계약은 revision이 아니라 digest만 담으므로, Map의 세 OpenAPI 표면
(`openapi.json` · `openapi.service.json` · `openapi.user.json`)이 핀된 revision과
**바이트 동일**하면 PinVi 재벤더링 없이 Map만 전진한다. 다르면 그때는 PinVi가 먼저
재벤더링해야 하고, 그것이 T-VN-40이 기다리는 그 선행조건이다.

**주의.** 이 배포는 provider 핀 8종 상향(khoa async 전환 포함)을 함께 싣는다.
해수욕장 asset이 async generator로 바뀌었으므로 첫 실행 로그를 확인한다.

## T-VN-DAGSTER-STORAGE

```markdown
- [ ] T-VN-DAGSTER-STORAGE — **prod Dagster run이 compute-log storage에 쓸 수 없다**
```

**무엇이 참이면 닫히는가.**

1. [x] prod에서 provider asset job 하나가 `SUCCESS`로 끝난다 — run launcher에 제출한
   run이 step 실패 없이 완주한다. **2026-09-12 충족.**

   `feature_place_standard_museums_job`이 정식 경로(`dagster job launch`)로 제출돼
   `SUCCESS`로 끝났다. **이 prod에서 provider 적재 job이 SUCCESS로 끝난 첫 사례다.**

   run 이력이 뒤집혔다 — 2026-09-11에는 조회 시점 8건이 **전부 실패**였는데,
   수정 배포 뒤에는 `SUCCESS 23 · FAILURE 1`이다. 그 FAILURE 1건은 08:09의
   `current_weather_summary_refresh`로, rebuild가 스택을 내리던 순간에 걸린 run이다.
   스택이 올라온 08:22 이후의 run은 전부 성공했다.

   로컬 쓰기 자리도 실물로 확인했다 — 컨테이너 안에서 `uid=999(appuser)`가
   `/opt/dagster/state/{artifacts,compute_logs}`를 소유하고, compute log가 실제로
   쌓이고 있다. 종전에는 그 자리가 봉인된 `DAGSTER_HOME` 아래라 만들 수조차 없었다.

   적재 축도 다시 맞물린다: `claims 1047 · aliases 1047 · links 1047`
   (`features 1048`은 D2가 남긴 은퇴 행 1개를 포함한다 — §T-VN-D2-RESIDUE).
2. 그 성질이 배포마다 유지된다. storage 부착이 pinned runtime generation의 함수라면,
   generation이 바뀔 때 함께 따라오는 것이 증적으로 보인다.
3. 이 축을 재는 검사가 있다 — 지금은 "컨테이너가 healthy"만 보고 "run이 완주한다"는
   아무도 보지 않는다. healthy와 실행 가능은 다른 사실이다.
4. 봉인 검사기와 배에 실리는 `dagster.yaml`이 서로를 본다 — 같은 key 집합을 각자
   들고 있으면서 CI가 어긋남을 못 보는 상태가 아니어야 한다. 2026-09-12에 정확히
   그 상태가 prod 스택을 내렸다.
5. **UI에서 step의 stdout/stderr가 보인다.** 지금은 한 세대 안에서도 비어 있다 —
   `dagster`(webserver)와 `dagster-daemon`이 각자 code location을 안고 도는 별개
   컨테이너이고 `/opt/dagster/state`에 공유 volume이 없다. `DefaultRunLauncher`가
   띄우는 run worker는 daemon 컨테이너의 자기 경로에 쓰고, webserver는 자기
   컨테이너의 같은 경로를 읽는데 거기엔 아무것도 없다(없으면 `ensure_dir`이 빈
   디렉터리를 만들어 그것을 watch한다). **"run이 왜 죽었나"를 UI로 확인하는 경로가
   없다** — 이번 사고를 가린 것과 같은 종류의 맹점이다. 공유 named volume 하나로
   조문 5와 아래 "알려진 한계"가 함께 닫히지만, compose는 pinned runtime 표면이라
   prod가 복구된 뒤 별도 사이클에서 검사부터 붙여 넣는다.

**무엇이 관측됐나 — 2026-09-11.**

**범위 정정(2026-09-12).** 이 결함은 run을 FAILURE로 **표시**하고 compute log를
남기지 못하게 한다. 그러나 **적재 자체를 막지는 않는다** — 같은 run이 남긴 데이터가
정합성 검사 여섯 축을 0건으로 통과했다(§T-VN-39-DEPLOY 조문 4). 그래서 이 task는
"적재가 안 된다"가 아니라 **"run의 성공/실패 신호와 compute log를 믿을 수 없다"**를
소유한다. 신호를 믿을 수 없다는 것은 그 자체로 운영 결함이다 — 2026-09-12에 나는
정확히 그 신호를 믿고 조문 4를 "막혀 있다"로 잘못 적었다.

정식 경로(`dagster job launch` → run launcher 제출, operation key = job 이름)로 제출한
run이 step 실패로 끝났다:

    PermissionError: [Errno 13] Permission denied: '/opt/dagster/dagster_home/storage'
    Exception initializing logger write stream: PermissionError ...

실물:

| | |
|---|---|
| 컨테이너 사용자 | `uid=999(appuser)` |
| `/opt/dagster/dagster_home` | `dr-xr-xr-x root root` — appuser가 쓸 수 없다 |
| `.../storage` | **없다** |
| 마운트 | `dagster-storage-permit` (읽기 전용, generation `461cafcc…` 산출물) |

prod Dagster storage는 별도 관리 컴포넌트다 — `/usr/local/bin/ktm-dagster-storage`가
`verify-identity`와 sealed launch contract를 갖고, entrypoint가 `storage_input_preflight`
로 argv를 대조한다. 즉 storage 부착은 pinned runtime이 통제하는 축이고, 현
generation에서 그것이 붙지 않았다.

**재키가 만든 것이 아니다.** 이 prod의 Dagster run 이력은 전부 실패다(조회 시점
8건 중 7 FAILURE + 1 진행). `feature.features`가 0행이었던 것과 앞서 찾은 seal ACL
유실이 같은 사실의 다른 면이다 — **이 prod에서 provider 적재가 한 번도 완주한 적이
없다.** 그래서 이 조건도 그때부터 있었고 아무도 관측하지 않았다.

**조문 3이 그 구멍을 겨냥한다.** 배포 사후점검은 컨테이너 healthy와 정본/실물 image
일치를 보지만, "run이 완주한다"는 보지 않는다. 그 둘은 다른 사실이다.

**무엇이 관측됐나 — 2026-09-12. 고침이 결함이 됐다.**

#1216(`dagster.yaml`에 `local_artifact_storage`/`compute_logs` 선언)이 머지된 뒤 첫
회전 사이클이 prod 스택을 내린 상태에서 죽었다. `docker/dagster-storage-migrate.py`의
`_validate_dagster_config`가 최상위 key 집합을 **정확히 5개로** 봉인하고 있었다.

    06:34:05  …kor-travel-map-dagster-storage-migrate-run-dc953676ad41  기동
    06:34:07  task-delete                                              (2초)
    06:34:09  pinned runtime rebuild Compose run command failed (exit 1)

#1219가 봉인을 그 둘만큼 넓히되, 두 `base_dir`가 이미지가 appuser에게 넘긴
`/opt/dagster/state` 안인지까지 본다 — key를 허용하는 것으로 끝내면 "로컬로 새지
않는다"는 봉인의 뜻이 그 구멍으로 빠져나간다.

**조문 4 — 봉인 검사기와 배에 실리는 config가 서로를 본다.** 기존
`test_dagster_storage_rejects_alternate_top_level_storage_keys`는 실제 `dagster.yaml`을
읽으면서도 이 어긋남을 못 잡았다. **거절되는 것**만 보기 때문이다 — 두 파일이
어긋나면 그 거절은 이유만 바뀐 채 여전히 일어난다. #1219가 **통과하는 것**을 보는
검사를 심었고, 변이 ②(검사기만 되돌림)에서 그 하나만 빨갛다.

**알려진 한계.** `/opt/dagster/state`에는 volume이 없다. artifact와 compute log는
컨테이너 재생성마다 사라지고, 애초에 컨테이너 경계를 넘지도 못한다(조문 5).
run/event/schedule storage는 postgres이므로 조문 1·2에는 영향이 없다.

**호스트 dev 스택도 같은 파일을 읽는다.** `scripts/run-admin-stack.sh`가
`docker/dagster.yaml`을 바이트 그대로 호스트 `DAGSTER_HOME`에 깐다. #1216의
`base_dir`는 이미지 안에만 있는 경로라 그대로 두면 dev에서 같은 PermissionError가
난다. #1219가 설치 뒤 두 경로만 `$DAGSTER_HOME` 아래로 옮기고, 그 요구를
`dagster.yaml`이 선언한 key 집합에서 유도하는 검사를 붙였다.

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
2. [~] **분자가 있다.** KMA 격자 job은 `upstream_requests_min`을 asset
   metadata로 내보낸다(격자 하나 = 요청 하나, 재시도는 세지 못하므로 하한).
   bulk/페이지네이션 fetcher는 아직 세지 않는다. `settings.log_api_calls`는
   **지웠다** — 읽는 코드가 없었고, 그 표는 provider 호출이 아니라 Map API로
   들어오는 요청을 기록한다.
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
것 — 폭주 상한, 4배 배수 제거, 분자 만들기, 오도하는 문구 지우기 — 만 먼저
했고, 그 사이에 분모가 들어왔다.

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

## T-VN-39-D2-FIXTURE

```markdown
- [x] T-VN-39-D2-FIXTURE — **D2 fixture의 소유 핸들을 재키 뒤 앵커로 옮긴다** (2026-09-11 완료)
```

**무엇이 참이면 닫히는가.**

1. `scripts/admin_feature_live_fixture.py`의 provider fixture가 자기 Feature를
   **정본 uuid**로 들고 다닌다 — `CAST(:feature_ids AS uuid[])` 바인드 10곳에
   legacy 주소가 들어가지 않는다.
2. D2 lane이 seed → 감사 → cleanup을 완주하고 `RESULT.json`이 남는다.
3. 잔여물 0이 실측으로 확인된다(`/root/adjudicate.sh`의 네 counter).

**무엇이 깨졌나 — 2026-09-11 실측.**

D2 direct seed가 이렇게 죽는다:

    asyncpg.exceptions.DataError: invalid input for query argument $1:
    ['f_global_w_47c05e70793daee8', ...] (invalid UUID: length must be
    between 32..36 characters, got 27)

    SELECT (SELECT count(*) FROM feature.features
            WHERE feature_id = ANY(CAST($1 AS uuid[]))) AS features, ...

**질의는 uuid 축으로 옮겼는데 값의 출처는 안 옮겼다.** 이것이 T-VN-39가 고치려던
바로 그 부류이고, 하네스 자신이 그 부류로 남아 있었다.

**왜 alias로 우회할 수 없나.** 이 seed는 core 프로시저를 직접 부른다. ADR-098 결정
6과 309(`trg_features_legacy_alias` 영구 제거)에 따라 **alias가 생기지 않고 그것이
정상이다** — 하네스 주석이 스스로 그렇게 적고 있다. 그래서
`make_feature_id(...)`가 만든 `f_global_*` 주소는 재키 뒤 **DB 키가 전혀 아니다.**

**왜 재계산도 안 되나.** `candidate_feature_uuid()`는 비파생 랜덤 UUIDv7이다
(0083). run_id에서 유도할 수 없다. 이 파일은 같은 문제를 API-owned 경로에서 이미
한 번 풀었고, 그 답이 "재계산이 아니라 **재현**"이었다 — 소유권 키로 **조회**한다.

**그래서 해는 T-VN-39가 만든 앵커다.** provider 경로의 Feature identity는
`provider_sync.provider_feature_identities`의
`(provider_dataset_id, feature_kind, natural_key)` claim이 소유한다(ADR-098). 이
fixture의 natural key는 `{run_id}:{kind}`이고 dataset은 `_ensure_dataset`가 run별로
만든다. 즉 소유 uuid는 그 claim 한 번의 조회로 **재현**된다 — seed 전에는 행이
없으므로 빈 집합이 되어 "이미 존재하는가" 사전 검사도 그대로 성립한다.

**범위.** `_feature_ids(run_id)`의 소비자 전부(바인드 10곳)와 seed payload의
`feature_id` 슬롯. payload는 admin 경로처럼 후보 uuid를 실어야 한다.

**주의 — prod에 쓴다.** 이 lane은 prod feature DB에 seed하고 지운다. 고친 뒤
첫 실행은 잔여물 counter 넷을 전후로 재고 증거를 남긴다.

**2026-09-11 — 자매 lane에도 같은 부류가 남아 있다(이 절의 것이 아니다).**
적대 리뷰가 `scripts/admin_feature_clone_live_state.py`에서 둘을 더 짚었다:
`_API_OWNED_AUDIT_FOREIGN_KEY_REFERENCES = 8`(같은 alias 한 행을 더 센다)과,
evidence 키 집합을 `feature_ids` 없이 **정확히** 요구하는 검사(그 키는 #1176부터
나오고 있다). clone lane은 D2와 다른 소비자이므로 여기서 고치지 않는다 — 그 lane을
다시 돌릴 때 함께 본다.

## T-VN-39-ECHO

```markdown
- [x] T-VN-39-ECHO — **API 패키지 conftest의 echo-resolve를 재키 뒤 세계로**
```

**무엇이 참이면 닫히는가.**

1. [x] `packages/kor-travel-map-api/tests/conftest.py`의 autouse resolver가 참조를
   **정본 uuid**로 풀어 준다(`feature_id=ref`가 아니라). — `canonical_ref()`가 그
   사상을 세운다: legacy 주소는 결정적 파생 uuid로, 이미 uuid인 참조는 그대로.
2. [x] 그 위에서 이 패키지 테스트가 전부 초록이다. — 2026-09-11 n150 전량
   **1223 passed / 0 failed**. 함께 움직인 자리는 27곳이었다(47은 추정치였다).
3. [ ] ~~`test_curations_router._install_post_rekey_resolver` 같은 자체 resolver
   설치가 불필요해지고 제거된다.~~ **2026-09-11 — 이 조문이 틀렸다. 삭제한다.**

**왜 3이 틀렸나 — echo가 할 수 없는 일을 요구한다.**

그 resolver를 쓰는 세 테스트는 필터 표면의 **3분기**를 잰다:

| 입력 | 기대 |
|---|---|
| 해석되는 참조 | 200 + 정본 uuid |
| 어떤 Feature도 가리키지 않는 참조 | **422**, repo는 호출조차 되지 않는다 |
| 형식은 맞으나 없는 uuid | 200, 그대로 통과 |

전역 echo는 **모든** 참조를 "해석 성공"으로 만든다. 그래서 2·3번 축은 echo 밑에서
구조적으로 관측될 수 없고, echo를 "미해석은 None"으로 바꾸면 임의의 참조를 쓰는
나머지 1200여 건이 전부 깨진다. 두 요구는 같은 fixture 안에서 양립하지 않는다.

지우면 잃는 것이 정확히 무엇인지도 분명하다 — 재키 적대 리뷰가 마지막에 찾아낸
결함(`22P02`가 `DataError`로 와서 `except ValueError`를 지나 500이 된다)의 **단위
커버리지가 그 세 테스트다.** 검사기를 없애 조문을 만족시키는 것은 이 작업이 고치려던
바로 그 함정이다.

그래서 규약을 반대로 고정한다: **echo는 해석의 *값*을 모사하고, 해석의 *실패*는 각
테스트가 자기 resolver로 모사한다.** conftest docstring이 그렇게 적고 있다.

**왜 재키 PR과 나눴나.** 섞으면 그 27곳의 변경이 재키 diff와 구분되지 않는다. 그리고
이 축의 실효 검증은 설계상 통합이 소유한다
(`tests/integration/test_feature_identity_boundary.py`).

## T-VN-39-PROVIDER-PAGINATION

```markdown
- [x] T-VN-39-PROVIDER-PAGINATION — **provider 종료 조건 퇴화를 upstream에서 고친다** (2026-09-11 완료)
```

**무엇이 참이면 닫히는가.**

1. `python-datagokr-api`의 `services/pagination.py:iter_pages`가 짧은 페이지 종료에
   `total` 가드를 되돌린다(예: `len(items) < num_of_rows and seen >= total`).
2. `python-krheritage-api`의 `services/search.py:iter_pages`도 같다.
3. 두 리포에 그 성질을 고정하는 회귀 테스트가 있다 — "행 하나가 걸러진 만재 페이지"
   에서 계속 페이지네이션하는 것을 본다.
4. Map 핀을 그 커밋으로 올린다. Map 쪽 `_iter_datagokr_standard`/
   `_iter_krheritage_details` 우회는 **그대로 둔다** — 방어는 중복이어도 좋다.

**근거.** 2026-09-11 실측: datagokr `b8f1254`가 `reached_known_end`
(= `total_count <= page_no * num_of_rows`) 가드를 떨어뜨렸고, 같은 범위가
`standard.py:list`에 행 단위 `except ValidationError: continue`를 넣었다. 둘이
겹치면 18,000건 데이터셋이 999건에서 예외 없이 끝난다. krheritage는
`if len(result.items) < page_size: return` 하나뿐이고 결측 key row를 skip한다.
Map은 위임을 끊어 스스로를 지켰으나 **다른 소비자는 노출돼 있다.**

**2026-09-11 진행.** 1·2·3은 닫혔다 — datagokr `0f1f236`(PR #16), krheritage
`b86a094`(PR #10). krheritage는 `total` 가드가 아예 없었으므로 되돌릴 것이 없었고,
대신 **행이 아니라 페이지 수**로 세게 했다(`page >= ceil(total/page_size)`). 이쪽이
엄밀히 낫다 — 행을 세면 걸러진 행 때문에 `seen`이 `total`에 영원히 못 미쳐 tail에서
매번 여분 요청이 붙지만, 페이지를 세면 걸러져도 정확히 끝난다. datagokr은 이미
`total_pages` 가드가 있어 그것을 살리고 짧은 페이지 규칙만 `total`로 조건화했다.
회귀 테스트 8건(두 리포 4건씩) + 기존 82건 통과. **4도 닫혔다** — 두 PR이 머지됐고
Map 핀 3자리를 올렸다(#1204 `7b2e9ecf`). 표면 manifest는 `pinned_sha` 둘만 바뀌어
공개 멤버 집합이 불변임이 함께 증명된다.

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

## T-VN-M05-EXECUTION-IDENTITY-V6

> **완료 — 2026-08-31 `docs/tasks-done.md`로 이관.** 아래는 판정 근거 보존용이다.

**문제**: v5 `pinset_sha256`의 해시 입력은 `(release_version, Map revision, PinVi
revision)`뿐이고 **Manager revision이 빠져 있다.** terminal은 pinset 기준 무조건·영구
차단이므로, Manager만 고치면 같은 pinset이 나와 이미 차단된 상태가 된다. 새 candidate를
만들 유일한 레버가 Map/PinVi source 변경이었고, 둘 다 결함이 없었으므로 **의미 없는 Map
문서 커밋이 nonce로 쓰였다.**

- [x] A1. v6 execution identity = SHA-256({v5 source pinset, canonical Manager repo URL,
  trusted 설치 Manager revision}). Manager revision은 CLI/환경 입력이 아니라
  `.ktdm-source-revision` + `.ktdm-release-manifest.json`의 root no-follow 일치로만 얻는다.
- [x] A2. v5 history/block은 읽기 전용으로 보존한다(제자리 재계산은 audit 변조다).
- [x] A3. execution ledger·terminal block·public generation binding·PinVi isolated
  admission·Map attestation이 v6 identity를 쓴다.
- [x] A4. **Manager-only 수정만으로 새 candidate가 성립한다.** 판정 근거: 2026-08-29~30에
  같은 Map/PinVi pair(`3916ebfd`/`b6af59f2`) 위에서 **Map 커밋 0개로 9개 candidate**가
  실행됐고 phase가 단조 전진했다. v5 시대에는 candidate마다 Map 문서 PR이 필요했다.

**판정: 충족.** 남은 것은 문서 이관뿐이다.

## T-VN-M05-MAP-HEALTH-TRANSPORT

**규명된 원인**: 경합이 아니었다. Manager driver가 생성한 Compose override가
`ports: !reset`을 썼는데, Compose에서 `!reset`은 "지우고 아래 값으로 교체"가 아니라 해당
attribute를 default(빈 list)로 되돌리는 태그다. 의도는 `!override`였다. 그래서
`services.api`에 `ports` key가 아예 없는 상태로 렌더링됐고(`api_has_ports=false`, rendered
config 실물에서 확인), 컨테이너 내부 healthcheck와 `up --wait`는 통과하는데 **host publish
socket이 애초에 존재하지 않았다.** driver는 없는 포트에 1초 간격 6회 재접속하고 종료했다.

이것이 `41be91fe`·`5512ce12`·`b46743ea`·`9b6eab1e` 네 candidate가 서로 다른
Map/PinVi/Manager revision에서 **동일 지점**에 멈춘 이유다 — Map/PinVi source와 무관한
정적 결함이므로 source를 바꿔서는 통과할 수 없었다.

- [x] B1. rendered Compose override가 Map API의 host loopback publish를 실제로 남긴다
  (`!reset` → `!override`).
- [x] B2. 같은 결함을 execution 소비 전에 잡는 preflight가 있다 — Manager
  `scripts/m05_isolated_e2e.py`의 `runtime_loopback_publish_invalid`(Docker inspect
  바인딩 확인)와 `runtime_loopback_publish_config_invalid`(rendered config 확인).
  (원 인용 SHA `1f20ab36`은 세 저장소 어디서도 해석되지 않아 file 참조로 교체했다.)
- [x] B3. 후속 candidate가 Map health를 통과한다. 2026-08-30 Compose `!override` 보정
  이후 phase가 `map_subscription_http_failed` → `runtime_command_failed` → PinVi 경계로
  전진했다.
- (귀속) B4. Map `/health`의 성공 종료 관측 의무는 그 사건을 소유한
  `T-VN-M05-ACTIVATION`의 A3에 귀속했다 — 같은 사건 하나를 두 task가 각자 기다리는
  중복 부기였다(`docs/reports/map-stall-root-cause-2026-08-31.md` §3 I-6).

**판정: 충족(수리 측 완료, 관측 의무는 ACTIVATION에 귀속) — 2026-08-31
`docs/tasks-done.md`로 이관.**

## T-VN-M05-ADMISSION-TERMINAL

- [x] C1. `7035b0b1`(`runtime_setup_admission`)과 `3d8d63e1`(제어면 terminal) 두 사례를
  재실행 금지 목록과 함께 보존한다.
- [x] C2. Manager `03a3300…`이 모든 runtime pin mutation을 active global mutation에서
  거절하고 trusted launcher의 inherited-lock fallback만 허용한다.
- (귀속) C3. 후속 candidate에서 admission 경계 통과가 확인됐다 — 2026-08-30 Compose
  `!override` 보정 이후 admission을 넘어 Map subscription·PinVi runtime까지 도달했다.
  성공 종료 receipt로의 최종 고정 의무는 그 사건을 소유한 `T-VN-M05-ACTIVATION` A3에
  귀속했다(중복 부기 해소, 위 MAP-HEALTH-TRANSPORT B4와 같은 근거).

**판정: 충족(수리 측 완료, 관측 의무는 ACTIVATION에 귀속) — 2026-08-31
`docs/tasks-done.md`로 이관.**

## T-VN-M05-ROLE-CATALOG-RESET

> **완료 — 2026-08-31 `docs/tasks-done.md`로 이관.** 아래는 판정 근거 보존용이다.

- [x] D1. `31fe73ad`·`b22bfb8c`·`c6c73cdf` 세 candidate를 각각 `target_not_isolated`·
  `foreign_membership`·`foreign_membership` terminal로 보존하고 재시도하지 않는다.
- [x] D2. 재시도 금지가 문서로 선언돼 있다.

**판정: 충족. 실행 잔여 없음 — `tasks-done.md` 이관 대상이다.** (이 항목이 왜 열려
있었는지는 문서에 근거가 없었다. 조건을 적고 나니 닫을 수 있다는 것이 드러난다.)

### 측정 오류 정정 (2026-09-08)

**"n150에 예약 백업이 아예 없다"는 틀렸다.** `digitie`의 crontab에 셋이 매일 돈다:

```
CRON_TZ=UTC
15 3 * * * KTDM_BACKUP_ROOT=/home/digitie/backups ... run-standalone-backup.sh geo_dagster 4
30 3 * * * KTDM_BACKUP_ROOT=/home/digitie/backups ... run-standalone-backup.sh concierge  7
55 3 * * * KTDM_BACKUP_ROOT=/home/digitie/backups ... run-standalone-backup.sh pinvi      7
```

`/home/digitie/backups`에 세 role 모두 dump + `.sha256` + `.manifest` 삼종이 보존 정책대로
있고(각 12·21·23 파일), 로그는 2026-08-21부터 **18일 연속 성공, 실패 0건**이며 GC가 하루
한 건씩 지운다. 즉 "주기 백업이 최근 성공과 bounded retention으로 수렴한다"는 부모 전제는
**수렴할 대상이 돌지 않는 상태가 아니라 이미 돌고 있었다.**

**왜 틀렸나.** `backup_root_for_role()`은 `KTDM_BACKUP_ROOT`가 없으면 `~/backups`로 떨어진다.
cron은 그 값을 명시하지만, **root로 실행한 `ktdctl db-backup list`는 `/root/backups`를 본다.**
2026-09-07 실측이 root로 돌았고, 그래서 "백업 0건"으로 읽혔다 — 실제로는 다른 디렉터리를
보고 있었다. `sudo ls /root/backups`는 지금도 원장이 적은 그대로다(`map_application` 1건,
`map_dagster` 1건, `pinvi` 2건).

**이 정정이 뒤집지 않는 것.** `map_application`은 어느 cron에도 없다 — 그것은 `T-VN-H43`의
의도된 보류다. 그리고 M05-2가 근거로 삼은 사실, 즉 **manual-feature evidence를 담은
`map_application` backup이 만들어진 적이 없다**는 그대로다: home root의 것은 2026-08-22
(614MB, 300 이전 세대), root의 최신 것은 2026-09-07 23:26에 내가 만든 것이다.

**교훈은 도구가 아니라 관측 지점이다.** 같은 명령이 실행 사용자에 따라 다른 곳을 본다.
"없다"를 기록하기 전에 **어디를 봤는지**를 함께 기록해야 한다.


## T-VN-H49-GEO-DAGSTER

- [ ] E1. `geo_dagster` metadata DB의 standalone dump가 주기 실행된다.
- [ ] E2. dump의 SHA-256과 크기가 manifest에 기록된다.
- [ ] E3. bounded retention이 적용되고 초과분이 실제로 삭제된다.
- [ ] E4. 복원 리허설을 한 번 수행하고 결과를 `docs/backup-restore*`에 기록한다.

(원문 근거: `git show 6d671ef1^:docs/tasks.md` 504~522행의 H49 하위 AC 4건을 인스턴스별로
나눈 것 중 geo_dagster 몫이다.)

## T-CI-DOCKERFILE-BUILD

- [x] C1. Map CI가 `docker/*.Dockerfile`을 실제로 빌드한다 — 현재
      `.github/workflows/`에 `docker build`가 **0건**이라 Dockerfile 결함이 n150
      격리 e2e나 pinned rebuild에서야 드러나고 피드백 루프가 한 시간이다.
- [x] C2. registry 없이 돈다(`KOR_TRAVEL_MAP_BUILDX_OUTPUT=oci` + 단일 platform).
      arm64는 굽지 않는다 — 배포 대상이 amd64뿐이다.
- [x] C3. `scripts/docker-buildx.sh`를 경유한다. 현재 그 스크립트를 **호출하는 곳이
      저장소에 없어** 자체가 검증되지 않는다; CI에서 돌리면 Dockerfile과 빌드
      스크립트가 함께 산다.
- [x] C4. trigger 경로가 Dockerfile의 `COPY` 대상에서 **파생**된다. 손으로 나열하면
      한쪽만 늘어나 조용히 빠진다(2026-09-03 `frontend.Dockerfile` 워크스페이스
      매니페스트 누락과 같은 계열).
      **구현 시 결정**: 파생 대신 **필터를 두지 않는 쪽**을 택했다. 필터가 없으면
      파생할 것도 뒤처질 것도 없어 이 조건의 목적(누락 불가)이 더 강하게 달성된다.
      비용은 PR당 job 하나이고 기존 20분짜리 unit job과 병렬로 돌아 전체 대기시간을
      늘리지 않는다. `test_the_workflow_has_no_path_filter`가 필터가 다시 생기는 것을
      막는다.
- [x] C5. 새 Dockerfile이 생기면 이 job이 자동으로 그것을 포함하거나, 포함되지 않았을 때
      깨진다. `test_every_production_dockerfile_is_built`가 `docker/*.Dockerfile`과
      `build_one` 호출 집합을 대조한다(런타임 아닌 c7-playwright는 사유와 함께 면제).
      탐침 Dockerfile을 넣어 실제로 깨지는 것을 확인했다.

(근거: 2026-09-03 `frontend.Dockerfile`이 선언된 워크스페이스 셋 중 둘만 복사하는
결함이 #1137까지 숨어 있었다. `frontend.yml`은 전체 체크아웃에서 같은 npm 명령을
돌리므로 영원히 통과했고, Dockerfile 경로는 CI에서 한 번도 빌드되지 않았다.)

- [x] C6. 이 job이 실제 PR에서 초록으로 도는 것을 한 번 확인한다. **충족**(2026-09-04):
      #1142에서 `production Dockerfiles build`가 13분 55초에 pass했고 같은 커밋의
      나머지 8개 job도 전부 초록이었다. 그 PR은 `cac35134`로 머지됐다.
      (C1~C5가 모두 `[x]`인데 task는 `[~]`로 열려 있었다 — 그 이유인 잔여 요구가
      `docs/tasks.md` 본문에만 있고 해제 조건 파일에는 없었다. 아래 이관 본문의
      "**남은 것**: 이 job이 실제 PR에서 초록으로 도는 것을 한 번 확인한다."를
      그대로 조건으로 세운 것이며, 새로 지어낸 조건이 아니다.)

### `docs/tasks.md`에서 이관한 구현 근거 (2026-09-04)

> `docs/tasks-rule.md` §5는 "task당 위치는 하나 — `docs/tasks.md`에 한 줄, 해제 조건은
> `docs/tasks-acceptance.md`에 한 절. 본문을 중복하지 않는다"고 정한다. `docs/tasks.md`의
> 이 항목은 한 줄 규약을 어긴 584자 산문이었고, 그 내용은 이 절이 소유해야 할
> 판정 근거·재개 조건이었다. 아래는
> 그 본문을 **원문 그대로** 옮긴 것이다 — 요약·축약·삭제 없음(2026-09-04 이관).

Map CI가 프로덕션 Dockerfile을 한 번도 빌드하지 않았다(`.github/workflows/`에 `docker build` 0건). 그래서 Dockerfile 결함은 n150 격리 e2e나 pinned rebuild에서야 드러나고, 그 피드백 루프는 한 시간이다 — 2026-09-03 `frontend.Dockerfile`의 워크스페이스 매니페스트 누락(#1137)이 그렇게 숨어 있었다. `scripts/docker-buildx.sh`는 `KOR_TRAVEL_MAP_BUILDX_OUTPUT=oci` + 단일 platform으로 registry 없이 돌릴 수 있고, 현재 그 스크립트를 **호출하는 곳이 저장소에 없다** — CI에서 돌리면 Dockerfile과 빌드 스크립트를 함께 살린다. trigger 경로는 파생 대신 **필터를 두지 않는** 쪽으로 해결했다(필터가 없으면 뒤처질 것이 없다). `.github/workflows/docker-images.yml` 신설 + 게이트 6건. **남은 것**: 이 job이 실제 PR에서 초록으로 도는 것을 한 번 확인한다.

## T-VN-M02-TRUNCATE-FENCE

- [x] **T-VN-M02-TRUNCATE-FENCE — hard-purge fence의 TRUNCATE 우회를 닫거나, 닫지 않는 이유를 박는다** (2026-09-08 충족, migration 307)

**2026-09-07 실측으로 드러난 구멍이다.** manual Feature hard-purge fence는
`feature.features`의 **BEFORE DELETE row trigger**다. 그런데 같은 표에 BEFORE TRUNCATE
문 트리거가 없다. claim·origin·`ops.domain_commands`에는 no_truncate 트리거가 있다.

**2026-09-08 재실측 — 위 서술의 두 문장이 틀렸다.**

1. ~~`TRUNCATE feature.features CASCADE`가 fence를 통째로 우회한다~~ — **실제로는
   중단된다.** `feature.features`만 TRUNCATE하는 것은 FK 때문에 불가능하고, `CASCADE`가
   끌어오는 30-table 폐포 중 **10개에 켜진 BEFORE TRUNCATE 가드**가 있다
   (`feature_aliases`·`curation_import_rows`·`curation_link_decisions`·
   `theme_feature_candidates`·`curation_cutover_identity_mappings`·
   `curation_import_manual_feature_children`·M05 evidence 넷). **진짜 결함은 다른 것이다** —
   fence는 그 거부에 아무 기여도 하지 않고, 호출자가 받는 진단은
   `T-VN-32C legacy write fence: feature_aliases TRUNCATE 금지`라 manual Feature와 무관한
   이유를 댄다.
2. ~~통합 테스트 24곳이 그 경로에 의존해 무비용이 아니다~~ — **14곳이고, 비용은 0이다.**
   전부 `tests/integration/_db_cleanup.py`를 지나고 그 헬퍼가
   `SET LOCAL session_replication_role = replica`(`:49`)로 돌아 origin 트리거를 전부
   억제한다. 저장소 안에 증거가 있다 — `test_db_cleanup.py`가 위 가드 7개를 포함한
   CASCADE를 **성공으로** 단언하고 CI에서 초록이다.

**원장이 놓친 더 큰 구멍.** `ops.feature_requests`(M04 외부 제출)는 TRUNCATE 가드도
append-only row 가드도 **아예 없다**. `ops.feature_update_requests`·`_datasets`는 DELETE
가드만 있고 TRUNCATE 가드가 없다.

**실제 노출은 훨씬 작다.** 121개 테이블에서 TRUNCATE 권한을 가진 로그인 롤은 컨테이너
superuser 하나뿐이고(`schema.sql`에 `GRANT ... TRUNCATE`가 0건), 그 행위자는
`SET session_replication_role`이나 `ALTER TABLE ... DISABLE TRIGGER`로 **기존 DELETE
fence도 똑같이** 무력화한다. 따라서 origin-enabled 트리거는 보안 바닥을 0만큼 올린다 —
정직한 위협 모델은 적대자가 아니라 **실수**다. 바닥을 실제로 올리는 것은 `ENABLE ALWAYS`
뿐이고, 그것은 `_db_cleanup.py`에 명시 `DISABLE TRIGGER` 네 줄을 요구한다.

**변이 검증의 함정.** "트리거 제거 → red"는 **공허하다** — 이웃 가드가 먼저 raise하므로
지금도 red다. 새 트리거의 **고유 제약 이름/메시지**를 단언해야 한다.

**해제 조건.**

1. 다음 중 하나를 택하고 그 근거를 이 절에 적는다 — (a) BEFORE TRUNCATE 문 트리거를
   더하고 통합 테스트의 정리 경로를 다른 수단으로 바꾼다, (b) 트리거를 더하지 않기로
   하고 "fence는 DELETE 경로만 막는다"를 계약으로 명시한다.
2. (a)를 택하면 우회가 실제로 막히는지 **변이 검증**으로 보인다 — 트리거를 되돌리면
   red가 되어야 한다.
3. 어느 쪽이든 `docs/adr/`의 관련 결정문에 fence의 적용 범위를 한 문장으로 박는다.
4. `ops.feature_requests`를 함께 판정한다 — 위 재실측이 드러낸, 원장이 몰랐던 구멍이다.

**2026-09-08 충족 — (a)를 택했다(migration 307).**

**(a)를 택한 이유는 진단이다.** 재실측이 보인 대로 TRUNCATE는 이미 중단됐고, 결함은
fence가 그 거부에 기여하지 않고 진단이 엉뚱한 이유를 댄다는 것이었다. (b)를 택하면
그 오진이 계약으로 굳는다.

**`ENABLE ALWAYS`다.** origin-enabled 트리거는 보안 바닥을 0만큼 올린다 — TRUNCATE
가능한 로그인 롤은 superuser 하나뿐이고 그 행위자는 `SET session_replication_role` 한
줄로 기존 DELETE fence까지 무력화한다. 정직한 위협 모델은 적대자가 아니라 **실수**이고,
실수를 막는 유일한 변형이 ALWAYS다.

대가인 `_db_cleanup.py`의 명시 DISABLE은 **비용이 아니라 개선**이다. 종전에는 `replica`
한 줄이 무엇을 우회하는지 말하지 않은 채 전부 껐다. 되돌릴 때 `ENABLE ALWAYS`를 써야
한다는 것까지 게이트가 결박한다 — 그냥 `ENABLE`이면 origin으로 내려앉아 남은 세션 내내
우회 가능해지고, 그 상태는 겉보기에 정상이라 아무 테스트도 실패하지 않는다.

**306이 열린 뒤라 이 선택이 가능해졌다.** 이전이라면 더 강한 fence는 "지울 방법이 아예
없다"를 굳히는 것이었다. 이제는 감사되는 삭제 경로가 있으므로 **감사되지 않는 경로만**
막는 것이 된다. 그래서 이 항목과 §T-VN-H49의 purge 판정은 함께 읽어야 한다.

**4항 — `ops.feature_requests`.** TRUNCATE와 DELETE를 막는다. `UPDATE`는 막지 **않는다**
— 라우터가 `status`/`resolved_at`/`resolved_by_actor`를 정당하게 갱신하고
(`_FEATURE_REQUEST_TABLE_ACL`이 그 컬럼만 GRANT한다), 여기서 막으면 M04 해결 경로가
통째로 죽는다. 그 과잉을 막는 축을 따로 뒀다. `feature_update_requests`·`_datasets`는
TRUNCATE만 더한다(DELETE 가드는 이미 있다).

**2항의 함정을 피했다.** "트리거 제거 → red"는 공허하다 — 이웃 가드가 먼저 raise하므로
지금도 red다. 그래서 모든 단언이 **고유 제약 이름**을 본다. 변이 8축 전부 RED
(features_trigger · features_origin_only · requests_truncate · requests_delete ·
update_requests_truncate · delete_guard_overreaches · cleanup_downgrades ·
preflight_rejects_always).

**실측이 잡은 것 셋.** 새 SECURITY DEFINER 함수는 `db.py` startup preflight가 배포를
막았고, 회수는 **소유자만** 할 수 있어 audit writer 소유로 만들어야 했다(기존 guard
주석이 같은 함정을 적어 뒀다). `ENABLE ALWAYS`는 `tgenabled='A'`인데 M05-2 D단계
preflight가 그것을 "꺼짐"으로 읽고 있었다 — `'A'`는 origin보다 **강한** 상태다. 그리고
`test_mois_loader`의 다섯 번째 전역 조회를 찾았다.

3항의 ADR 기재는 ADR-093 개정문(2026-09-08)이 purge 경계를 적으면서 함께 담는다.

**T-VN-M02와 같은 fence다.** `T-VN-M02`의 "지워지지 않는 write"는 바로 이 fence가 유일한
삭제 경로를 거부하기 때문에 생긴다(admin API의 `DELETE`는 soft retire다). (a)를 `ENABLE
ALWAYS`로 택하면 그 되돌릴 수 없음이 **더 강해진다** — 두 항목을 따로 판정하면 안 된다.

## T-VN-M05-ONESHOT-CONSUME

- [x] **T-VN-M05-ONESHOT-CONSUME — 격리 acceptance 성공이 execution identity를 소비하게 한다** (2026-09-08 충족, Manager #335)

**2026-09-07 실측으로 드러난 구멍이다.** 격리 M05 one-shot은 **본문 실패에만** 강제된다
— `_block_terminal_m05_execution`이 본문 phase에 `phase=None`(무조건 차단)을 남기지만,
`run-m05-isolated-e2e-once`의 **성공 분기**(`case 0)`)는 `exit "$driver_status"`뿐이고
`pin block-execution`이 없다. 그래서 **같은 execution identity에서 acceptance 본문을 두
번 돌릴 수 있다.**

**단순히 성공에도 무조건 차단을 걸면 안 된다.** 지금 상태는 `phase=None` 하나뿐이라
"소각(burned)"과 "소비(consumed)"가 구분되지 않고, 성공에 같은 것을 쓰면 방금 성공한
leaf가 `--verify-leaf`의 L8("terminal 차단 아님")에서 실패한다. 승격 근거가 스스로를
무효화하는 셈이다.

**해제 조건.**

1. 소비 상태를 소각과 **구분해서** 기록한다(예: scoped phase 또는 별도 필드).
   `is_unconditionally_blocked_current()`가 소비를 소각으로 세지 않아야 한다.
2. `_assert_current_m05_execution_is_runnable`이 **소비된 identity의 본문 재실행을
   거부**한다. 복구 경로는 rebind 또는 회전이며 그 사실을 진단 메시지가 말한다.
3. `--verify-leaf`의 L8이 소비된 identity의 leaf를 계속 통과시킨다.
4. 변이 검증: 성공 시 소비 기록을 지우면 red, 소비를 소각으로 취급하면 L8 게이트가 red.

**2026-09-08 충족 — 넷 다(Manager #335).**

scoped phase `execution_identity_consumed`로 남긴다. 그러면 셋이 동시에 성립한다:
`is_unconditionally_blocked_current()`가 소각으로 세지 않아 배포·회전이 안 막히고(소비는
"승격됐다"이지 "오염됐다"가 아니다), L8이 `entry.phase is None`만 보므로 통과한 leaf가
계속 검증되고, runnable assert가 이것만 따로 보고 재실행을 막는다.

**`result.json`에 키를 더하지 않았다.** 런처가 키 집합을 정확히 강제해
(`set(value) != expected_keys` → degraded → 무조건 소각) 그 계약을 건드리면 통과한
1~2시간 실행이 타 버린다.

**적대 리뷰가 내 변이 검증이 놓친 축을 잡았다(P1).** `has_block_for_current(phase=...)`
에서 `phase=`를 떼면 그 술어가 **모든** 차단 기록을 잡아, 인프라 phase로 scoped 기록이
남은 identity가 영구히 거부되고 진단은 엉뚱하게 `execution_identity_consumed`가 된다 —
#330이 넣고 #331이 되돌린 회귀와 같은 부류다. **내 9축은 "지우기"만 쟀고 "약화"를 재지
않았다.** 갈리는 유일한 상태(소비가 아닌 scoped 기록 하나)를 만드는 축을 더했다.

그리고 리뷰가 내 테스트 하나를 공허하다고 잡았다 — "아무 문자열이나 phase면 scoped
기록이 된다"를 재는 것이라 어떤 줄도 빨갛게 만들지 못했다. 지웠다.

**2항의 진단**은 `_PAIR_DIAGNOSTICS`가 아니라 상위 집합에 넣는다. 그 집합은 pair 실패
전용이고 "안의 모든 문자열이 발신된다"를 기존 테스트가 양방향으로 결박하므로, 다른
phase의 진단을 섞으면 그 결박이 거짓이 된다.
## T-VN-M05-RELITIGATION

**2026-09-07 신설.** #1189가 M05-3 탐지기를 붙이면서 드러난 것이다 — 계약 자체의
성질이지 탐지기의 결함이 아니다.

`feature.record_manual_provider_dedup_candidate`의 멱등성은 `evidence_fingerprint`가
같고 **그 case가 아직 미해결일 때만** 성립한다(baseline `schema.sql` 8180~8186행:
`LEFT JOIN ... resolutions` + `WHERE resolution.case_id IS NULL`). 그래서 admin이
`kept`로 판정한 쌍을 탐지기가 다시 보면 지문이 같아도 **새 case가 만들어진다.**
그 상태로 탐지를 주기화하면 admin 큐가 쳇바퀴가 되므로 #1189의 job에는 스케줄을
달지 않았다.

**어느 방향으로도 틀릴 수 있다는 것이 이 항목의 어려운 점이다.**
너무 세게 막으면 증거가 **실제로 바뀌었는데도** 새 후보가 안 올라오는 영구 침묵이
되고, 너무 약하게 막으면 무관한 필드 patch가 `row_revision`을 올릴 때마다 supersede
폭풍이 난다. 둘 다 조용히 실패한다.

- [x] **R1 — 판정된 쌍이 같은 증거로 다시 올라오지 않는다.**
  admin이 `kept`/`merged`/`manual_retired`로 판정한 case와 **지문이 같은** 후보는
  새 case를 만들지 않는다. 억눌렸다는 사실은 삼키지 않고 receipt나 실행 요약에 남는다.
- [x] **R2 — 증거가 바뀌면 다시 올라온다.**
  Feature의 score-facing 값(`kind`/`name`/`category`/`lon`/`lat`)이나 provider의
  current source head가 바뀌면 지문이 달라져 새 후보가 된다. R1의 차단이 이것을
  덮지 않는다. **두 방향 모두 게이트가 있어야 한다** — 한 방향만 재면 반대 방향
  결함이 조용히 통과한다.
- [x] **R3 — 무관한 변경이 재발행을 부르지 않는다.**
  score와 무관한 필드 patch로 `row_revision`만 올라간 경우 새 case가 생기지 않는다.
- [x] **R4 — 차단이 detector 권한을 넓히지 않는다.**
  탐지 로그인은 `ops.manual_provider_dedup_cases`를 읽을 수 없다(`_OPS_TABLE_PRIVILEGES`가
  빈 튜플). 그러므로 차단은 프로시저 안에서 일어나야 하고, detector에게 case 조회
  권한을 주는 방식은 채택하지 않는다.
- [x] **R5 — 차단이 켜진 뒤에야 스케줄을 단다.**
  R1~R4가 충족되면 #1189의 `manual_provider_dedup_detection` job에 스케줄을 붙이고,
  그때 job description의 "스케줄 없음" 문구를 함께 걷는다.
**2026-09-08 — R1~R5 충족(migration 305).**

차단 키를 `evidence_fingerprint`로 잡으면 안 됐다. 그 지문에는 두 Feature의
`row_revision`과 `source_head_observed_at`이 들어 있어 **score와 무관한 필드 patch
하나**로 달라진다. 판정을 실제로 좌우하는 것만 넣은 `decision_fingerprint`를 따로
뒀다 — snapshot에서 `row_revision`을 뺀 것 + provider의 현재 source 내용
(`raw_payload_hash`) + `scorer_id`.

**변이 검증이 설계를 한 번 고쳤다.** 처음엔 `source_record_key`도 넣었는데, 그것을
빼는 변이가 초록이어서 왜인지 보니 **같은 내용을 다시 fetch하면 record key만
바뀐다** — 넣으면 그때마다 차단이 풀린다. 내용을 뜻하는 것은 `raw_payload_hash`
하나다.

`superseded`는 차단 근거가 아니다. 탐지기가 만든 resolution이므로 그것으로 차단하면
탐지기가 자기 자신을 영구히 침묵시킨다.

**두 방향 모두 게이트가 있다**(통합 6건, 변이 다섯 축 전부 RED):

| 되돌린 것 | 어느 방향이 깨지나 | 결과 |
|---|---|---|
| 차단 자체 제거 | 과소차단(쳇바퀴) | RED ×2 |
| 지문에 `row_revision` 복원 | 과소차단 | RED |
| 지문을 `feature_uuid`만으로 축소 | **과잉차단(영구 침묵)** | RED |
| provider `raw_payload_hash` 제거 | 과잉차단 | RED |
| `superseded`도 차단 근거로 | 탐지기 자기 침묵 | RED |

R5로 탐지 job에 일간 스케줄(04:20 KST, 기본 `STOPPED`)을 붙였고, job description의
"스케줄 없음" 문구를 걷었다. 억눌린 수는 `suppressed_case_count`로 보고된다 —
세지 않으면 "후보가 없다"와 "이미 판정됐다"가 같아 보인다.

## T-VN-M05-VERIFY-RECEIPT

**2026-09-07 신설.** 3차 적대 리뷰가 잡았다 — `--verify-leaf`는 **아무것도 쓰지 않는다.**
print만 하고 return하므로, 승격 근거가 원장에 붙인 출력 텍스트로만 남는다. 조문이
"승격은 문서 행위가 아니다"라며 배격한 상태 — 기계 증적 없이 사람이 옮긴 문장 — 가
정확히 검증 **결과**에 남아 있다.

그리고 그 근거는 셋 중 무엇이 먼저 와도 재현 불가가 된다: `pin rotate-pair`(의도된
성질), execution history 500칸 링에서 binding이 밀려남, leaf identity 소각.

- [x] **V1 — 검증이 root-owned receipt를 남긴다.** (2026-09-08, Manager #335)
  `--verify-leaf`가 통과·실패 모두에 대해 검증 시각·검증기 revision·leaf 경로·읽은
  registry 파일 경로·정의표의 **모든 축**(현재 15줄) 각각의 결과와 detail을 root-owned 0600 파일로 남긴다 — 축이 늘면 receipt도 함께 는다.
  **실패도 남긴다** — 통과만 남기면 "검증한 적 없다"와 "검증했는데 떨어졌다"가 같아 보인다.
- [x] **V2 — receipt가 그 시점의 대조 입력을 함께 싣는다.** (2026-09-08, Manager #335)
  pinset·Map/PinVi revision·binding의 Manager revision·claim 이름을 값으로 싣는다.
  나중에 pin이 움직여 재현이 불가능해져도 **무엇과 대조해 통과했는지**는 남는다.
- [x] **V3 — receipt가 원장 인용을 대체한다.** (2026-09-08 충족)
  조문이 출력 텍스트를 옮겨 적는 대신 receipt 경로와 그 sha256을 인용한다. 옮겨 적기가
  사라져야 이 항목의 요지가 달성된다.

  **2026-09-08 — 승격 정의를 개정하고(소유자 승인) 배포된 빌드로 실측했다.**

  `install-ktdm-trusted-release`로 `ee281b5`(#335)를 n150에 설치하고
  `pin rebind-execution`으로 재결박한 뒤(`execution_binding: manager_drift → current`)
  두 승격 후보를 검증했다. **둘 다 15축 전부 PASS, exit 0.**

  | leaf | receipt | sha256 |
  |---|---|---|
  | `/root/pairv2-e2e-02` | `/var/lib/kor-travel-docker-manager/m05-verify-receipts/pairv2-e2e-02-20260908T045824773930Z.json` | `b65b1d79ccca2c30fe989625bba8c23b9e49f69cbc7ffd3a8ae93220e5ba027c` |
  | `/root/pairv2-e2e-03` | `…/m05-verify-receipts/pairv2-e2e-03-20260908T045803209001Z.json` | `06f8383d54afd157b1923f170cec7bf323ab74603b3a287d423b07228e9a6365` |

  디렉터리와 파일 모두 `root:root`, 각각 `0700`/`0600`.

  **재배포가 과거 증적을 무효화하지 않았다** — 설치본은 `ee281b5`인데 두 leaf의 binding
  Manager revision은 `d36847e2`/`0406b14d`다(`is_installed=False`). L4·L5가 설치 revision이
  아니라 **registry binding**에서 파생하도록 만든 설계가 정확히 이 경우를 위한 것이었고,
  이번 배포가 그것을 처음으로 실증했다.

  receipt가 싣는 것: `pinned_pair`(pinset·Map·PinVi revision), `leaf_binding`(execution
  identity·binding Manager revision·`is_current_execution`), `ledger_claim_name`,
  `registry_paths` 셋, `verifier`(설치 revision + **검증기 스크립트 자신의 sha256**
  `8ef83e0a…`), `coverage`, 축 15개 각각의 결과와 detail.

  **이 표가 종전의 30줄 전사를 대체한다.** 해시는 옮겨 적을 수 없다 — 위조하려면
  root-owned 0600 파일을 만들어야 하고, V4가 receipt를 통과 조건에서 배제하므로 그렇게
  만들어 둬도 승격되지 않는다.
- [x] **V4 — receipt 자체가 위조 문턱을 낮추지 않는다.** (2026-09-08, Manager #335)
  receipt는 검증의 **기록**이지 근거가 아니다. `--verify-leaf`가 receipt의 존재를
  통과 조건으로 삼지 않는다(그러면 receipt를 만들어 두는 것으로 통과할 수 있다).

**2026-09-08 — V1·V2·V4 충족, V3는 열려 있다(Manager #335).**

`--verify-leaf`는 정말로 아무것도 쓰지 않았다. **V2가 요구하는 값은 전부 이미
지역변수로 살아 있었고** print 문자열에만 들어갔다 버려지고 있었다 — 모아서 receipt로
내는 것이 대부분의 일이었다.

**가장 날카로운 지점은 신뢰 경계 거부였다.** 그 경로는 한 문장만 인쇄하고 `return 1`이라
`checks`가 빈 채로 끝났다. receipt를 붙였어도 내용이 비었을 것이고, "실패도 남긴다"가
가장 필요한 실패 종류가 바로 그것(leaf가 가짜라는 판정)이다.

**조문 문구 하나를 정정한다.** V1이 "정의표의 **모든 축**(현재 15줄)"이라 적었는데,
15줄은 **full-pass 경로에서만** 맞다. 조기 종료 경로는 16번째 식별자를 내고 L3~L8을
억제해 4~8줄이 된다. receipt는 잰 축을 그대로 싣고 `coverage`로 **어디서 멈췄는지**를
말한다 — 그것이 "모든 축"의 실현 가능한 형태다.

**V3가 남은 이유.** 이 조문은 receipt **경로와 sha256을 원장이 인용**할 것을 요구하는데,
그러려면 배포된 빌드로 실제 검증을 한 번 돌려야 한다. #335가 머지되고
`install-ktdm-trusted-release`로 배포한 뒤(그 자체가 execution identity를 바꿔 rebind를
부른다) 실행할 일이다.

**그리고 V3는 조문끼리 충돌한다.** §T-VN-M05-ACTIVATION의 승격 정의가 "**그 출력을 이
절에 기록한다**"고 **명령**한다. V3를 채우려면 그 문장도 함께 고쳐야 하며, 그것은 승격
정의의 개정이므로 소유자 판정이다.

**변이 검증**(초기 9축 + 적대 리뷰 후속 5축 = 14축 전부 RED). 넷은 처음에 공허했다 —
소비·marker 배선이 `finally` 안에 인라인이라 직접 잴 수 없었다. 이 파일이 이미 같은
이유로 `driver_exit_code`를 꺼낸 전례가 있어 같은 방식으로 추출했다.
