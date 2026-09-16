# tasks-acceptance 아카이브 — `T-VN-39-DEPLOY` (완료)

> `T-VN-39-DEPLOY`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-09-16).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 2개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

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
