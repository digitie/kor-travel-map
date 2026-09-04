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
- [~] **T-VN-FINAL-REBUILD — fresh rebuild 완료 후 최종 acceptance 배리어**

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

  - [ ] B4. **현 candidate의 runtime/attestation 입력을 바꾸는 미반영 변경이 없다.** raw/resolved
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

```markdown
- [~] **T-VN-41F1D-E — 구 generation 퇴역·v6/v8 attestation 전환**

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
- [ ] **T-VN-41F1D-D2 — data-dependent admin/PinVi live E2E** *(공동, docs-only)*

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

## T-VN-41C

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

## T-VN-M01

```markdown
- [~] **T-VN-M01 — admin Feature 생성 API clean cutover** (결정 1, 구현 병합). Map PR #1029
  (merge `57c9d99a`)에 `0226_m01_manual_feature_create`의 DB/ACL/backup manifest와 API·Admin BFF가
  함께 착지했다. PinVi direct-create fail-close는 [PinVi #458](https://github.com/digitie/pinvi/pull/458)로
  완료됐다. 남은 것은 `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false`를 유지한
  route 활성화 전 fresh restore/ACL/live gate다.
```

## T-VN-M02

```markdown
- [~] **T-VN-M02 — origin 보존과 불변** (결정 4, 구현 병합). #1029의 `0227` provenance reader,
  immutable claim/origin ACL과 named hard-purge fence, unit/integration 회귀가 정본이다. evidence를
  남긴 상태에서의 purge 정책·backup/restore 실측 및 live acceptance가 남아 있다. PinVi M05 paired
  attestation이 소비하는 Admin provenance 최상위 identity는 opaque `feature_id`와 별도 `feature_uuid`를
  함께 반환해야 하며, UUID-only projection을 재사용하지 않는다. reader/immutable claim UUID는 모두
  최상위 `feature_uuid`와 같지 않으면 fail-close한다. PinVi consumer도 이 반환 UUID를 M05 case의
  manual/old UUID와 각각 대조하기 전에는 paired live receipt를 승격할 수 없다.
```

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
- [~] **T-VN-M04 — 범용 Feature 요청 큐** (결정 2, 구현 병합). #1029의 `0233` service submit/admin
  approve·reject queue와 `manual_request` origin, OpenAPI/ACL/restore gate가 정본이다. 첫 consumer
  PinVi #458과 Map #1051 service re-vendor를 반영한 PinVi #465는 병합됐지만 paired
  request→approval receipt와 isolated acceptance는 `T-VN-41C`에서 완료한다.
```

## T-VN-M05

```markdown
- [~] **T-VN-M05 — provider 발행 시 중복 판정** (결정 4 후단). 수동 Feature와 같은 실체를
  provider가 발행하면 dedup 후보로 올리고 **자동 병합하지 않는다.** admin이 병합/유지/수동본
  폐기를 고른다. 2026-08-21 사용자 선택은 paired cutover이며, ADR-097과
  `t-vn-m05-manual-provider-dedup-design-2026-08-21.md`가 immutable evidence·service event/ack·첫
  consumer rebind 계약을 소유한다.
```

## T-VN-M05-ACTIVATION

> 이 task는 `6d671ef1` 평면화 **이후**에 만들어져 복원할 원문이 없다. 아래는
> `docs/tasks.md`의 해당 줄이 이미 산문으로 서술하고 있는 재개 조건을 판정 가능한
> 형태로 옮긴 것이며, 새로 지어낸 조건은 없다.
>
> 종전에 이 task는 해제 조건이 **하나도 없는 채로** 게이트를 통과했다. 게이트가 이름
> 접두사만 보고 부모 `T-VN-M05`가 덮는다고 판정했는데, 그 섹션은 provider dedup
> 이야기이고 activation과 아무 관계가 없다.

```markdown
- [ ] **A1 — 회전은 원자적이다.** 재개는 새 Map revision·새 PinVi provenance·새 Manager
  source를 trusted `ktdctl pin rotate-pair`로 **함께** 결박한 새 pinset에서만 시작한다.
  terminal로 차단된 pinset·source pair·Manager source·output leaf는 재실행하지 않는다.
- [ ] **A2 — 실행은 단 한 번이다.** 회전 뒤 trusted `run-pinned-rebuild-once`가 current
  public generation을 만든 다음, 새 root-owned leaf에서 n150 isolated M04/M05 launcher를
  정확히 한 번 실행한다.
- [ ] **A3 — 승격 전제 셋을 모두 만족한다.** 최신 CI green · 전문 적대 리뷰 두 건 GO ·
  terminal 아님. 셋 중 하나라도 아니면 M04/M05 live acceptance attestation을 승격하지 않는다.
  성공 종료 receipt는 완료 이관된 `T-VN-M05-MAP-HEALTH-TRANSPORT`(Map `/health` 통과)와
  `T-VN-M05-ADMISSION-TERMINAL`(admission 경계 통과)의 관측 의무를 **함께 봉인한다** —
  같은 사건 하나를 세 task가 각자 기다리던 중복 부기를 여기 하나로 접었다.
- [ ] **A4 — 경계는 공개 API만 쓴다.** pinning·pair 결박·one-shot 계약은 Docker Manager
  trusted `ktdctl`과 `runtime-pins`·`pinned-runtime/generation` 공개 API만 사용한다.
  PinVi isolated Compose는 Manager가 transaction·pinset·세 source revision에 결박해 private
  `0600`으로 발급한 admission receipt를 no-follow 검증할 때만 허용하며, legacy 환경변수
  marker·수동 Compose는 권한이 아니다.
```

AC: A1~A4가 모두 참인 단일 실행에서 M04/M05 live acceptance attestation이 승격돼야 한다.
공개 registry의 고정 phase가 `runtime_setup`인 동안에는 이 task가 열려 있다.

### `docs/tasks.md`에서 이관한 재개 조건 원문 (2026-09-04)

> `docs/tasks-rule.md` §5는 "task당 위치는 하나 — `docs/tasks.md`에 한 줄, 해제 조건은
> `docs/tasks-acceptance.md`에 한 절. 본문을 중복하지 않는다"고 정한다. `docs/tasks.md`의
> 이 항목은 한 줄 규약을 어긴 1233자 산문이었고, 그 내용은 이 절이 소유해야 할
> 판정 근거·재개 조건이었다. 아래는
> 그 본문을 **원문 그대로** 옮긴 것이다 — 요약·축약·삭제 없음(2026-09-04 이관).

`a3f6a8f3…`·`22563762…`·`c700bd2e…`·`fa28a6e7…`·`5512ce12…`·`41be91fe…`·`b46743ea…`·`5ad3b08c…`·`5592a1d4…`에 이어 Map `35a43317…`·PinVi `fed16a5c…`·Manager `eed1920…`·pinset `82850711…`도 trusted `ktdctl pin rotate-pair`, 단발 pinned rebuild, registry/public generation `match` gate 뒤 n150 isolated M04/M05 launcher를 정확히 한 번 실행해 terminal로 차단됐다. 공개 registry의 고정 phase는 `runtime_setup`이며 HTTP·컨테이너·환경·output leaf 원문은 열지 않는다. 모든 terminal pinset과 각 source pair·Manager source·output leaf는 재실행하지 않는다. 후속 Manager는 isolated runtime setup의 ordinary exception을 raw detail 없이 더 좁은 allowlist phase로 수렴시켜 다음 immutable candidate의 보정 범위만 좁힌다. 이후 pinning·pair 결박·one-shot 계약은 Docker Manager trusted `ktdctl`과 `runtime-pins`·`pinned-runtime/generation` 공개 API만 사용한다. PinVi isolated Compose는 Manager가 transaction·pinset·세 source revision에 결박해 private `0600`으로 발급한 admission receipt를 no-follow 검증할 때만 허용하며, legacy 환경변수 marker·수동 Compose는 권한이 아니다. 재개 시에만 새 Map revision·새 PinVi provenance·새 Manager source를 atomic `pin rotate-pair`로 함께 결박한다. 회전 뒤에는 trusted `run-pinned-rebuild-once`가 current public generation을 만든 후 새 root-owned leaf에서 한 번만 실행하며, 최신 CI·전문 적대 리뷰 두 건·terminal 아님을 모두 만족해야 M04/M05 live acceptance attestation을 승격한다.

## T-VN-H34

```markdown
- [ ] T-VN-H34 — **H25A/H25B 미충족 AC 마무리**

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

## T-VN-H49

```markdown
- [~] T-VN-H49 — **주기 실행·bounded retention·off-box 증거 완성**

Map 인스턴스의 baseline 3건과 절차 문서화, Docker Manager #177의
6-role standalone backup primitive, Geo application DB의 앱 레벨 schedule env 결선
(PR #181, merge `969eff18`)까지 완료했고 #177도 닫혔다. 그러나 이 task의
운영 AC인 주기 실행·bounded retention·off-box 증거는 남아 있다.

- [~] Geo application DB 첫 자동 백업은 4.71 GB artifact와 sha256 verify까지 성공했다.
  다만 `scheduled_backup`과 retention janitor가 계속 RUNNING이며 최근 성공·bounded retention으로
  수렴하는지는 운영 증거가 더 필요하다. application DB에 standalone cron을 중복 설치하지 않는다.
- [ ] 별도 `geo_dagster` metadata DB(`T-VN-H49-GEO-DAGSTER`)와
  concierge(`12600`, `T-VN-H49-CONCIERGE`)·pinvi(`12800`, `T-VN-H49-PINVI`)에 standalone
  create → sha256 검증 → list → GC를 실행하고 cron/systemd timer 및 최신 dump + sha256 +
  manifest 증거를 남긴다.
- [ ] off-box 사본 자동화를 결선한다(`T-VN-H49-OFFBOX`). Map application/Dagster 주기화는
  #148의 재적재 정책 결정을 따르며 이 task가 임의로 활성화하지 않는다.
- [ ] 위 운영 AC를 닫은 뒤 `docs/backup-restore.md` §1의 외부 instance 경고를 현행화한다
  (`T-VN-H49-OFFBOX`).

AC: 필요한 외부 DB마다 최신 dump + sha256 + manifest, 주기 실행과 보존 GC, off-box 사본
증거가 있고 절차가 문서화되어야 한다. PR #181 병합만으로 H49를 완료 처리하지 않는다.

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
- [~] **T-FE-MOCK-FLAKE** — mocked checkpoint 해소, n150 live GET-only 잔여

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

## Lane B 상세 — b1 PinVi 결합·후속

### T-VN-41 — cache-target generation·outbox 전파

> PR [#975](https://github.com/digitie/kor-travel-map/pull/975)는 merge
> `4672aa966cd473f17fd4f69ee8066276f7be900d`로 병합됐고 CI 8개가 모두 성공했다.
> source generation·restore epoch(`T-VN-41A`)과 transaction-coupled outbox writer
> (`T-VN-41B`)는 독립 완료로 이관했다. 남은 `T-VN-41C`는 final exact-pair evidence와
> production consumer enable·reconciliation 종결 AC를 소유한다.
```

## T-VN-39

```markdown
- [ ] T-VN-39 — **KTM·PinVi write-fence cutover**

  consumer-first 배포, write fence와 순차 전환을 수행한다. **T-VN-33C의 legacy
  column/index/route/repository/trigger/table은 서비스 전 단계 원칙에 따라 같은 final-schema
  migration에서 이미 물리 삭제한다.** 따라서 이 task는 T-VN-33 보존·rollback·removal을
  소유하지 않는다. 이후 task가 만든 held component만 그 task의 manifest와 함께 판단하며,
  intermediate data는 backup/restore가 아니라 최종 schema ETL로 재생성한다.

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

