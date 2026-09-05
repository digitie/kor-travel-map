# journal.md — 작업 일지 (역시간순)

## 2026-09-05 — 새 DB가 helper의 미결박 가정 셋을 한꺼번에 드러냈다

`af6d7061`로 rebuild한 뒤 D1은 통과했고 D2는 seed에서 9.8초 만에 죽었다. 원인은 셋이고
전부 같은 계열이다 — helper가 **단언만 하고 결박하지 않은** 가정들이다.

    1. preflight가 `SET ROLE` 전에 `public.alembic_version`을 읽었다 → permission denied
    2. `entity.provider`/`entity.dataset_key`가 `source_entities`에 없다 (provider_datasets의 컬럼)
    3. `await session.execute(...).mappings()`가 coroutine에 `.mappings()`를 불렀다

### 왜 지금까지 안 드러났나

1번은 어제 배포 DB에 손으로 준 `GRANT SELECT ON public.alembic_version TO
ktm_feature_migrator`가 가려 주고 있었다. **rebuild가 DB를 계약대로 새로 만들면서 그
grant를 지웠다.** 즉 아래 "부수로 고친 것" 절이 적은 REVOKE는 이미 불필요하다 — 오늘
실측: `public.alembic_version`의 aclitem은 정확히 8개이고 소유자와 `ktm_feature_runtime`
밖의 항목이 없다. `application-destination-alembic-version.sql`의 exact-ACL 계약을
그대로 만족하므로 final permit도 성공 sentinel을 낸다.

여기서 배울 것은 **out-of-band DB 패치는 다음 rebuild에 증발한다**는 것이다. DB가 선언된
계약으로 수렴하는 건 좋은 성질이지만, 그런 패치에 기대는 순간 그 위의 green은 근거를 잃는다.

2·3번 경로는 **한 번도 실행된 적이 없었다.** D2가 늘 그 앞에서 죽었기 때문이다.

### 값을 치른 방식 — 그리고 그것도 고쳤다

원인 셋을 알아내는 데 배포 스택에서 `docker create`를 손으로 세 번 재현해야 했고,
불완전한 재현은 매번 **다른 틀린 오류**를 냈다. 이유는 supervisor가 helper 컨테이너의
stdout만 증거 파일에 쓰고 **stderr를 버렸기** 때문이다 — helper는 실패 원인을 stderr에
내므로 남는 것은 0바이트 파일이었다. 같은 파일의 probe/executor 경로는 처음부터 두
스트림을 함께 읽는다. 계약은 있었고 helper 경로만 어긋나 있었다. 이제 stderr를
`<output>.stderr`에 root 0600으로 남기고, 게이트가 `docker logs`를 거두는 **모든** 경로가
stderr를 소비하는지 본다.

### 붙인 탐지기

- `tests/lint/test_admin_feature_fixture_sql_is_bound.py` — helper SQL에서 alias→관계를
  유도해 baseline 컬럼 집합과 대조하고, preflight가 role escalation 전에 관계를 읽지
  않는지 AST로 본다. 덮지 못하는 범위(bare column 목록·뷰·모호한 alias)를 독스트링에
  명시하고, 대신 실제 결함 형태를 되살려 red가 되는지 매 실행 확인한다.
- `tests/lint/test_d2_lane_is_type_checked.py` — 러너가 적재하는 Python 파일을 유도해
  CI·로컬 mypy 인자와 대조한다. lane에 파일이 늘면 mypy도 늘라고 말한다.
- `tests/lint/test_admin_feature_lane_preserves_failure_diagnostics.py` — 위의 stderr 계약.
- lane 세 모듈을 `mypy --strict`에 편입했다. 3번 결함을 mypy가
  `Maybe you forgot to use "await"?`로 즉시 잡는 것을 변이로 실측했다. 편입 비용은
  오류 1건(`SecretStr | None` 미검사)이었다.
- preflight가 이제 **두 번째** role 가정(`ktm_manual_feature_procedure_owner`)도 증명한다.
  그 가정은 종전에 `_seed` 한복판, 이미 쓰기가 일어난 뒤에야 실행됐다.

### 적대 리뷰 2인

리뷰어가 게이트 자신의 함수를 실행해 사각 다섯을 실증했다(숫자 포함 관계 2개를 파서가
놓침, `_REFERENCE`에 IGNORECASE 부재로 대문자 SQL이 자기검사를 전부 통과한 채 공허해짐,
`FROM a AS x, b AS y`의 둘째 항 누락, alias 충돌 시 last-write-wins로 인한 오탐,
escalation 순서 검사가 주석에 속음). 전부 재측정하고 고쳤다.

두 번째 리뷰어의 CRITICAL(임시 GRANT가 남아 프로덕션 API/Dagster 기동을 막는다)은
journal 기록에 근거한 타당한 추론이었으나 **실측으로 반증됐다** — 위에 적은 대로 rebuild가
이미 지웠다. 미러 감사의 경로형 mypy 사각(L2)과 낡아버린 코드 주석(L3)은 실재해서 고쳤다.

## 2026-09-05 — D2를 실제로 돌렸고, M04가 깨뜨린 계약에서 막혔다

D2(`ktdm-d2-001`)를 배포 스택에 실행했다. 13분 만에 `fixture-seed-failed`로 막혔고, 원인을
끝까지 추적했다. **배포 DB 잔여물은 0건**이다(`feature.features`에서 run id·`e2e_live_acceptance`
모두 0). seed가 쓰기 전에 죽었다.

### 오늘 발행한 신뢰 경계는 전부 통과했다

`BLOCKED.json`이 그것을 기록한다 — `host_attestation_sha256 40bde4b8…`,
`pinned_runtime_manifest_sha256 9f6ddfc4…`, `rebuild_journal_sha256 9a52683b…`,
`playwright_image_id sha256:2c5ee9ef…`, `source_commit 8078b110…`. attestation·snapshot 둘·
executor image·env가 실제 러너에게 수용됐다.

`owned_feature_ids`도 기록됐다 — `e2e_live_acceptance::<run_id>::{marker::draft, marker::inactive,
marker::hidden, correction, weather, price, search::alpha, search::beta}` **8개**. 런북 §1의
"8-ID" 서술은 소유 참조 키 기준으로 **정확했다**. 앞선 조사가 "API 1 + helper 2"라 한 것은
*행 수*를 센 것이고, 둘은 서로 다른 것을 세고 있었다.

### 진짜 원인 — M04가 helper의 FK 계약을 조용히 무효화했다

러너는 실패 사유를 가린다(`values redacted`). 게다가 supervisor는 helper 컨테이너의 **stdout만**
`direct-seed.json`에 쓰고 **stderr는 버린다**(`admin_feature_live_supervisor.py:349-360`). 그래서
파일이 0바이트였고 사유가 남지 않았다 — 이번 세션에서 고친 Manager preflight 침묵과 같은 계열의
관측 결함이다.

supervisor의 `docker create` 인자를 그대로 재현해(`--entrypoint python`, `--read-only`,
`--volumes-from <api>:ro`, API 런타임 env + `KOR_TRAVEL_MAP_PG_DSN=<fixture DSN>`) 읽기 전용
`audit`을 돌려 사유를 꺼냈다. 재현이 세 번 불완전했고 그때마다 다른 오류가 나왔다 — env만 준
경우 `ADMIN_PROXY_SECRET`, 볼륨을 뺀 경우 `final permit unavailable`. 둘 다 내 재현의 인공물이었다.

충실히 재현하니 진짜 사유가 나왔다:

    RuntimeError: feature FK topology가 단일 feature_id 계약과 다릅니다
    (admin_feature_live_fixture.py:525)

실측으로 범인을 특정했다:

    ops.feature_requests.resolved_feature_id (uuid) -> feature.features.feature_uuid (uuid)

helper는 "`feature.features`로 들어오는 **단일 컬럼** FK는 모두 `feature_id`를 가리킨다"고
단언한다(composite FK는 이미 제외한다). 그런데 이 FK는 단일 컬럼이면서 `feature_uuid`를
가리키고, **타입이 uuid↔uuid로 정당하다.** 스키마가 틀린 게 아니라 helper의 계약이 낡았다.

출처도 확정했다 — `alembic/retired_versions/0200-0236/0233_tvn_m04_feature_request_queue.py`,
즉 **`T-VN-M04`의 feature request 큐**가 넣었다. helper는 그 속성을 단언만 하고 스키마에
**결박하지 않았고**, migration이 조용히 무효화했다. D2가 그 뒤로 돌지 않아 아무도 몰랐다.
이 저장소가 DO NOT 15로 규정한 결함 계열 그대로다.

### 부수로 고친 것 — fixture login role 권한

전용 fixture login role이 배포에 **없어서** `ktm_feature_migrator`를 썼다(멤버십상 유일하게
`SET ROLE ktm_feature_schema_owner`가 가능한 LOGIN role이고, `KOR_TRAVEL_MAP_MIGRATOR_PG_DSN`의
role과도 일치했다). 그런데 confirm 쿼리가 `SET ROLE` **전에** `public.alembic_version`을 읽는데
그 권한이 없었다. 모든 role이 `rolinherit=false`(의도된 설계)라 멤버십으로는 안 된다.

    GRANT SELECT ON public.alembic_version TO ktm_feature_migrator;

새 권한을 준 것이 아니다 — migrator는 이미 `SET ROLE`로 그 테이블을 읽을 수 있었다. 되돌리려면
`REVOKE SELECT ON public.alembic_version FROM ktm_feature_migrator`.

> **2026-09-05 정정 — 이 REVOKE는 이미 불필요하다.** `af6d7061` rebuild가 DB를 계약대로 새로
> 만들면서 이 grant를 지웠다(실측: aclitem 정확히 8개, 계약 두 arm 밖 항목 없음). 그리고 이
> grant가 사라졌기 때문에 helper의 진짜 결함이 드러났다. 정본 해결은 위 2026-09-05 항목의
> preflight 순서 수정이다 — DB를 계약 밖으로 미는 대신 코드를 계약에 맞췄다.

### 남은 판정

helper를 고치면 Map revision이 바뀌고, 그러면 pinset·generation·attestation이 전부 따라
바뀐다(attestation의 `repository_commit`·`source_commits.map`이 v6의 `map_source_revision`과
exact여야 한다). 즉 **helper 한 줄을 고치는 값이 rotate-pair → rebuild(일곱 image) → 재발행 →
D1 재실행 → D2**다. 그 판단은 소유자 몫이다.

lane은 `BLOCKED`(`phase: fixture-seed-failed`, `recovery_attempt: 0`)로 남아 있다. 잔여물이
0건이므로 `recover`는 깨끗하게 끝날 것이나, 런북 §5가 운영자 확정을 요구하므로 실행하지 않았다.

## 2026-09-04 — 구세대 artifact를 퇴역시키고 41C를 재분류했다

### 퇴역 (F1D-E 위생)

`/etc/kor-travel-map/`의 구세대 셋을 활성 경로에서 뺐다 — `c7-compatible-pair-v4.json`,
`c7-pinned-runtime-generation-v5-pr197.json`, `c7-pinned-runtime-rebuild-v7-pr197.json`.
셋 다 pinset `de5206dc` / Map `e420c89e` / PinVi `27fe2043`의 것이고 Map 저장소에 참조가 없다.

**삭제가 아니라 `retired-de5206dc/`(root 0700)로 옮겼다.** 퇴역의 목적은 활성 경로에서 빼는
것이고, 이 파일들은 과거 세대의 증거이기도 하다. 옮기면 목적을 달성하면서 되돌릴 수 있다.
옮긴 뒤 검증기를 다시 돌려 현 세대 attestation이 여전히 PASS임을 확인했다 — 신뢰 경계를
건드리지 않았다는 것을 주장이 아니라 실행으로 확인했다.

활성 경로에 남은 것은 현 세대 셋(v6 사본·v8 사본·attestation)과 오늘 재발행의 롤백용 백업뿐이다.

### 41C 재분류

`T-VN-41C`의 줄은 "paired acceptance를 **완료한다**"였는데, 조사와 반증이 확립한 사실은 다르다.

- reconciliation은 **구현이 남아 있다**. 충족 근거로 인용된 #1026은 버그픽스이고, 인용문
  자체가 reconciliation을 잔여로 명시한다.
- cache-target 1-b/1-c는 현 런타임에 env/principal이 **하나도 없어** 실행조차 되지 않는다.
- 1-a는 production 호출자가 **0건**이라 전환할 흐름 자체가 없다.
- GC 실측 근거는 폐기 세대(head `0225`)의 것이고 그 스크립트는 exit 2 stub이다.

즉 41C는 acceptance task가 아니라 **구현 후 acceptance**다. acceptance로 이름 붙여 두면
백로그가 남은 일을 실제보다 작게 말한다. 줄을 그렇게 고쳤다.

다만 `T-VN-M04`가 41C에 위임한 격리 범위(paired request→approval receipt)는 `e2e025`로 값까지
재현 확인됐다 — 이 한 조각은 실재하는 성과이고, 41C 전체가 미착수라는 뜻이 아니다.

## 2026-09-04 — 사슬의 단일 blocker를 풀었다: attestation v4 재발행, 검증기 PASS

E와 D2의 첫 검증이 참조하는 host attestation v4가 구세대(`e420c89e`/pinset `de5206dc`)여서
n150 실행이 한 줄도 진행되지 않았다. 현 candidate `e6b52db4`용으로 재발행했고 저장소의
검증기가 **살아 있는 runtime과 대조해 통과**했다.

    manifest_sha256    9f6ddfc4…
    journal_sha256     9a52683b…
    attestation_sha256 40bde4b8…

선행 셋을 순서대로 했다 — v6/v8의 root:root 0600 사본, `8078b110` c7-runner snapshot(4파일
147KB), C7 executor image 빌드(`sha256:2c5ee9ef…`, 라벨 `repository-commit = 8078b110`).
`service_runtime` 21개 값은 검증기의 정의(`_canonical_json` + `sorted(Config.Env)`)를 그대로
재현해 직접 계산했고, 독립 조사가 낸 값과 전부 일치했다. attestation 파일은 전사 오류를 피하려
**측정에서 직접 생성**했다.

### 내 비판이 반증됐다

착수 전에 나는 이 작업을 "돌지 않을 C7 orchestrator를 결박하는 낭비"로 규정하고, 신뢰 경계를
C7에서 떼는 쪽(분리)을 권고했다. 실측이 그것을 뒤집었다.

- 러너 bootstrap은 **검증 모듈 자신의 해시를 attestation의 `orchestrator_files`와 대조한
  bytes만 exec**한다(자기참조 봉인). orchestrator를 바꿔치기할 수 없게 하는 장치다.
- 그리고 **admin lane이 바로 그 snapshot에서 `c7_prod_attestation.py`를 로드하고**,
  `E2E_C7_PLAYWRIGHT_IMAGE`를 넘겨 그 executor image로 Playwright를 돌린다.

즉 내가 "vestigial"이라 부른 두 필드는 퇴역한 C7이 아니라 **D2 자신의 실행을 보호**한다.
분리는 단순화가 아니라 보안 약화였을 것이다. 권고를 철회한다.

비용 추정도 틀렸다. 18키 중 17키가 이미 확정 가능했고, snapshot 4파일 중 3개는 구세대와
해시가 같았다. 실제로 무거운 것은 이미지 빌드 하나뿐이었다.

### 부수 교훈: 포그라운드 타임아웃은 빌드 실패가 아니다

이미지 빌드 명령이 10분 포그라운드 한도를 넘겨 백그라운드로 갔다가 종료됐고, 출력 파일이
0바이트라 실패로 보였다. 실제로는 docker 데몬이 이어받아 **11:34:01Z에 정상 완료**했다
(스크립트 시작 11:20:52). 상태를 명령의 종료코드가 아니라 **결과물의 타임스탬프와 라벨**로
확인해서 알았다. 죽은 명령을 재실행했다면 1.6GB를 한 번 더 구울 뻔했다.

## 2026-09-04 — 사슬 잔여를 조사했더니 "충족" 주장 20건이 반증됐다

`T-VN-41F1D-E`/`D2`/`T-VN-41C`의 잔여 범위를 확정하려고 조사 3건 + 각 "이미 충족" 주장에 대한
반증 20건을 돌렸다. 결과는 원장이 시사하던 것보다 훨씬 멀다.

### 단일 최대 blocker — host attestation v4를 **발행하는 절차가 없다**

E와 D2의 첫 검증 단계가 여기서 fail-close한다. n150에 v4 산출물이 있긴 하나 그것은
**구세대**의 것이다(`repository_commit e420c89e`, pinset `de5206dc`). 현 candidate
`e6b52db4`용 v4를 만드는 명령·스크립트·런북이 Map·Manager 두 저장소 어디에도 없다.
필요한 결박값은 알고 있다 — `repository_commit`=`8078b110`, `source_commits.pinvi`=`357da189`,
`pinned_runtime_pinset_sha256`=`e6b52db4`, `rebuild_transaction_id`=`4ee990ca-…`, schema head 3개,
v6/v8 root-owned 0600 사본의 sha256 2개, C7 attested 4파일의 sha256, `service_runtime` 7 role.
**값은 다 있는데 그것을 서명된 v4로 묶는 절차가 없다.** 이것이 열리기 전에는 n150 실행이
한 줄도 진행되지 않는다.

### 실행 순서가 틀려 있었다 (내 오류)

D2 자기 조항이 "D1/F1D-E와 배리어 확인 뒤에 실행한다"고 **F1D-E를 선행으로 박는다**. 배리어
해제 목록도 D1 → E → D2 → 41C다. 그런데 2026-09-04에 내가 `docs/resume.md`에 적은 순서는
D1 → D2 → 41C → E였다. 정정했다.

### D2는 조문과 구현이 정면으로 충돌한다

- D2 조문은 대상 DB가 **non-production 일회용**이고 production identity와 같으면 즉시 중단하라고
  적는다. 그런데 실행 런북(`admin-feature-live-acceptance.md`)은 `E2E_LIVE_ALLOW_PROD=1`과
  배포 DB의 `CONFIRM_*` exact 일치를 요구한다. 격리 대안
  (`scripts/run-admin-feature-clone-live-acceptance.sh`, 18701/18705)에는 런북이 없다.
- 런북 §1의 fixture 소유 모델(8-ID, place 6 + weather/price 2)은 2026-07-20 계약이고, 실제 spec은
  2026-08-09~12에 **단수 name-keyed**(API 1 + helper 2)로 재작성됐다. 원장이 stale하다.
- fixture manifest와 `fixed`/`run_scoped_owned` mode 결박은 코드에 **0건**이다.
- PinVi mutating 절반의 실행 수단이 없다(`admin_feature_live_fixture.py`에 pinvi 참조 0건).
- lane state의 `BLOCKED.json` 부재는 정상 종료가 아니라 **상태기계 밖 수동 삭제** 흔적이다
  (recovery가 result 없이 끝났고 `direct-audit.json`·`direct-cleanup.json`이 0바이트).

### 41C도 "구현 충족"이 반증됐다

- relay/reconciliation 충족 근거로 인용된 #1026은 버그픽스이고, 인용문 자체가 reconciliation을
  잔여로 명시한다. GC 실측 근거는 폐기 세대(head `0225`)의 것이고 그 스크립트는 exit 2 stub이다.
- 1-a는 production 호출자가 **0건**이라 전환할 흐름 자체가 없다.
- 1-b/1-c는 구현·회귀만 있고 live가 없으며, 현 런타임에 cache-target env/principal이 **하나도
  없어** 지금은 실행조차 불가능하다.
- receipt는 `pending`이고 production consumer enable은 PinVi 코드가 fail-close한다.
- 다만 `T-VN-M04`가 41C에 위임한 격리 범위(paired request→approval receipt)는 `e2e025`로
  값까지 재현 확인됐다 — 이 한 건은 살아남았다.

### 내 오류 셋을 정정했다

1. B4 서명이 **정본 파일에 반영되지 않았다.** `tasks-acceptance.md`의 배리어가 `[~]`, B4가 `[ ]`,
   "소유자 서명 전이다"가 그대로였다. 판정을 소유한다고 내가 지정한 바로 그 파일이 미갱신이었다 —
   이 저장소가 DO NOT 15로 규정한 이중 선언 결함 그 자체다.
2. `m04_server_side_chain_verified`는 **M05** attestation payload에 있다. M04 payload에는 없다
   (실측 확인). 내가 `tasks.md`의 M04 줄에 M04 증거로 적었다.
3. 위 실행 순서.

### 반증하지 않은 것

조사가 올린 지적 중 ADR 포인터(`ADR-086`→`ADR-084`)와 스크립트 문구 건은 **검증되지 않았다** —
해당 ADR 파일이 존재하지 않고 인용된 줄 번호도 다른 내용이었다. 근거 없이 고치지 않았다.
`c7-prod-live-e2e.md`의 v5/v7 언급은 파일 머리글이 `[보존 이력 · 실행 금지]`로 명시한 과거
기록이므로 그대로 둔다.

## 2026-09-04 — T-VN-41F1D-D1 완료: 데이터 비의존 live UI가 현 generation에서 통과했다

D1의 마지막 요구였던 데이터 비의존 admin UI smoke가 배포 스택에서 **11 passed (1.3m)**로
닫혔다. 이로써 D1의 여섯 요구가 전부 현 candidate `e6b52db4`에서 충족된다.

    [setup]  authenticate admin (live)
    scenario catalog   taxonomy route/API/reflection/risk · admin surface 메타 ·
                       pipeline datasets catalog + 조건부 MOIS precheck · 대표 route smoke
    backups            300 baseline 정책(backup만 opt-in, restore/hot swap 부재) ·
                       backup plan `execute=false` 결과와 UI live region
    운영 홈            pipeline overview·root 목록 실제 응답 렌더 · 존치 화면만 내비게이션 노출
    운영 로그          system/API 목록 실제 REST 렌더 · 필터·페이지 크기 GET-only 조작

실행 spec 4개와 `auth.setup.ts`·`_auth-state.ts`·`playwright.live.config.ts`가 핀 revision
`8078b110`의 것과 **바이트 동일**함을 먼저 확인하고 돌렸다(그래서 낡은 사본으로 검사하는
함정을 피했다). `-write` 접미 spec은 넣지 않았다 — 전체 live suite는 실제 Feature를
생성·삭제한다.

### 운영 메모: n150에서 Playwright를 호스트로 돌리는 법

두 번 헛돌았고 둘 다 환경 문제였다. 다음 사람이 반복하지 않도록 적는다.

- **root로 돌리지 마라.** 브라우저 캐시는 `/home/digitie/.cache/ms-playwright`에 있고
  root 캐시는 비어 있다. root로 돌리면 `chromium_headless_shell-1223 실행파일 없음`으로 죽는다.
- **호스트에 설치할 수 없다.** Playwright 1.60.0은 `ubuntu26.04-x64`를 지원하지 않아
  `playwright install chromium`이 거부된다. 기존 캐시를 쓰는 것 외의 길이 없다(격리 e2e가
  runner **컨테이너**를 쓰는 이유이기도 하다).
- **아티팩트 경로를 넘겨라.** 기본값이 `/tmp/kor-travel-map-playwright/...`인데 root가 한 번
  만들면 digitie가 쓰지 못한다. `PLAYWRIGHT_ARTIFACT_ROOT`로 홈 아래를 지정한다.

자격증명은 0600 파일로만 두고 실행 후 삭제했으며 로그에 남지 않았다(`grep -c PASSWORD` = 0).

## 2026-09-04 — B4 서명, 그리고 D1이 실제로 무엇을 남겼는지

소유자가 B4에 서명해 `T-VN-FINAL-REBUILD` 배리어가 열렸다. 판정 근거는
`docs/tasks-acceptance.md`의 B4 절(재계산 대조)이 소유한다.

배리어가 열리자 `T-VN-41F1D-D1`의 잔여가 정확히 드러났다. D1이 요구하는 것은 여섯이고
그중 다섯은 **이미 현 generation에서 측정된다.**

| D1 요구 | 현 candidate `e6b52db4` 증거 | 판정 |
|---|---|---|
| 일곱 image의 immutable ID | v6 generation 기록과 **실행 중 컨테이너가 일치** (`9c9aeca8`/`af4bdd39`/`6f62557b`×2/`20f83ba4`/`c0ee992d`/`12cd37ad`), 전부 healthy | 측정 |
| 세 schema head | `303_m05_payload_hash_domain` · `29b539ebc72a` · `20260824_0101` | 기록 |
| canonical `409` receipt | v8 `cancel_probe`: `PIPELINE_CANCELLATION_UNSAFE` / `409` / `stage: finalized` | 기록 |
| finalize | v8 `fresh_finalize_operation_plan` + `map_application_300_execution_evidence` | 기록 |
| resolved compose·pinset·OpenAPI provenance | `resolved_compose_sha256 b8a504d6…`, `pinset e6b52db4…`, `e2e025`의 `_pair` OpenAPI exact 대조 | 측정 |
| **데이터 비의존 admin UI smoke(로그인 포함)** | generation **32**에서만 통과했다(11개 테스트, 2026-08-26) | **미실행** |

### 남은 하나가 왜 생략되지 않는가

`e2e025`가 admin UI를 로그인부터 실제로 몰았지만 그것은 **격리 스택**이다. 배포 스택은
같은 일곱 image를 쓰되 origin·reverse proxy·session cookie 등 wiring이 다르고, D1이
attest하려는 것이 바로 그 배포 runtime이다. image·compose·env 해시가 같다는 사실은
**이미지가 같다**는 것이지 **배포 wiring이 산다**는 것이 아니다.

### 무엇이 막고 있나

실행에는 두 가지가 필요하고 둘 다 내가 임의로 만들 수 없다.

1. **admin 자격증명** — 런북이 `export E2E_ADMIN_PASSWORD='<admin-password>'`로 적는다.
   운영자가 넣는 값이며, root 소유 파일을 뒤져 찾지 않았다.
2. **핀 revision `8078b110`의 실행 가능한 체크아웃** — n150의
   `/home/digitie/kor-travel-map`은 `.git`이 없는 낡은 사본(live spec 36개 vs 현재 37개)이고,
   봉인된 핀 worktree에는 `node_modules`가 없다.

실행 범위는 이전 통과 기록과 동일하게 고정한다 — login setup + `admin-scenario-catalog` ·
`backups-restore`(`execute=false`) · `home-dashboard-roundtrip` · `logs` 네 spec(11개 테스트),
`--workers=1`. `-write` 접미 spec은 넣지 않는다(전체 live suite는 실제 Feature를 생성·삭제한다 —
`docs/reports/pr-552-563-review-2026-06-28.md`).

## 2026-09-04 — B4를 선언이 아니라 측정으로 바꿨다, 그리고 원장 중복 넷을 정리했다

### B4는 재계산으로 판정된다

`T-VN-FINAL-REBUILD`의 마지막 남은 조건 B4("현 candidate의 runtime/attestation 입력을
바꾸는 미반영 변경이 없다")는 종전에 사람의 선언이었다. 그런데 v8 rebuild journal이 그
입력 중 셋을 **해시로 담고 있다** — `compose_sha256`, `resolved_compose_sha256`,
`environment_sha256`. 그러면 판정은 재계산이다.

측정(2026-09-04, n150 읽기 전용):

    environment_sha256   journal b670154a…  재계산 b670154a…  동일
    compose_sha256       journal 1cd6f2e0…  재계산 1cd6f2e0…  동일

`.env`는 mtime이 오늘로 바뀌었지만 바이트가 같다 — installer가 바이트 보존을 스냅샷으로
단언한다. `resolved_compose_sha256`은 (원본 compose + `.env` + 렌더링 코드)의 함수인데
앞의 둘이 동일하므로 렌더링 코드만 변수다. generation 직전 커밋 `c4b509c`부터 현재
`main`까지 Manager 소스 변경은 **정확히 세 파일**이고, resolved compose·profile·container
command·환경 매핑·mount/network·runtime role/ACL과 journal 발행 verifier를 소유하는 네
모듈(`compose_service.py`·`c6c_deployment.py`·`pinned_runtime_generation.py`·
`runtime_execution_registry.py`)은 **무변경**이다. `docker compose config`는 쓰지 않았다 —
금지 명령이고, 이 유도가 그것을 대신한다.

`pinned_runtime_sources.py` 변경도 materialize 결과를 바꾸지 않는다. diff가 **303 추가 /
1 삭제**이고 그 한 줄은 독스트링이다. 본문이 바뀐 기존 함수는 넷뿐이며 전부 fail-close
추가이거나 `GIT_OPTIONAL_LOCKS=0` 추가다. revision·tree·clean 검증 경로는 한 줄도 바뀌지
않았다.

판정 초안은 **TRUE 권고**이며 `docs/tasks-acceptance.md`의 `T-VN-FINAL-REBUILD` 절에
근거와 함께 뒀다. 남은 판단은 한 가지다 — 조문의 "Manager runner와 verifier contract가
달라지면 false"를 문자 그대로 읽을지 여부. 문자 그대로면 매 Manager 커밋마다 false가 되어,
B1~B3를 삭제하며 이 절이 명시적으로 배격한 병리를 그대로 재생산한다. 소유자 서명이 남았다.

### 원장 중복 넷 — 셋은 낱말 문제, 하나는 실제 위임

조사해 보니 "중복"의 성격이 서로 달랐다.

- **`T-VN-M04` ↔ `T-VN-41C`**: 실제 위임이다. M04의 해제 조건이 이미
  "paired request→approval receipt와 isolated acceptance는 `T-VN-41C`에서 완료한다"고
  적는다. M04 줄이 그 범위를 다시 세고 있었다 → 위임을 줄에 명시했다.
- **`T-VN-M05` / `T-VN-41C` / `T-VN-M05-ACTIVATION`**: 삼중 계상이 아니라 **낱말 충돌**이었다.
  M05의 reconciliation은 dedup 판정 결과의 전파, 41C의 reconciliation은 relay/DB 대조,
  ACTIVATION은 그것을 태우는 실행 수단이다 — 셋 다 다른 것이다 → 각 줄이 자기 범위를
  말하게 했다.
- **`T-VN-H49` 부모/자식**: 부모의 해제 조건이 자식 넷을 자기 체크리스트로 열거한다.
  미배정 잔여는 Geo application DB의 `scheduled_backup`/retention 수렴 증거 하나뿐 →
  부모 줄을 그 잔여로 좁혔다.
- **`T-VN-H49-OFFBOX` ↔ `T-VN-H43`**: H43의 유일한 잔여가 `[보류]`이고
  "현 환경에서 수행하지 않는다"(사용자 지시 2026-08-06)이다. 열린 작업이 아닌데 줄은
  활성처럼 읽혔다 → 보류와 사유·재개 조건·현 소유자(`H49-OFFBOX`)를 줄에 박았다.

넷 다 task를 지우지 않았다. 지워야 할 중복이 아니라 **범위가 흐린 문장**이었기 때문이다.

## 2026-09-04 — 격리 M04/M05가 새 하네스에서 통과했고, 봉인 트리가 처음으로 깨끗이 남았다

`e2e025`가 `status: passed`로 닫혔다. 중요한 것은 통과 자체보다 **끝난 뒤의 상태**다.

    phase                                completed
    driver_phase                         completed
    status                               passed
    m04_attestation_sha256               f08620a9…
    m05_attestation_sha256               37320bb5…
    runtime_provenance_sha256            25a80946…
    pinset_sha256                        e6b52db4… (Map 8078b110 + PinVi 357da189)
    execution_identity_sha256            148f76b1…
    manager_source_revision              b3217edc…
    cleanup_failed                       false
    disposable_run_worktree_retained     false

attestation 본문은 `scope: isolated`, `version: 4`, `m04_server_side_chain_verified: true`,
`impact_count: 1`이다. M04 UI는 `runner_exit_code 0` · `runtime_identity_verified true`,
M05 UI는 assertion 6건 통과다. M04는 admin UI에서 feature request를 실제로 제출했고
(`map_action: submit`, `map_review_mode: feature_request_queue`) pending receipt와 PinVi
approval 해시가 이어졌다 — 데이터가 실제로 흐른 증거다.

### 이번에 달라진 것: 같은 pinset을 다시 돌릴 수 있다

2026-09-03·04에 두 번, **통과 여부와 무관하게** 같은 pinset의 재실행이 불가능해졌다.
러너가 저장소 루트를 컨테이너에 root RW로 마운트해 봉인된 핀 worktree에
`apps/web/node_modules`와 마운트포인트 셋을 남겼고, 다음 preflight의
`_validate_immutable_tree`가 정당하게 거부했기 때문이다. 각각 약 1.5시간을 태웠다.

Manager #315가 실행 루트를 **일회용 체크아웃**으로 옮겼다(같은 bare의 object store에서
재유도 — 사본이 아니다). 이번 실행 후 실측:

    봉인 트리 잔여물          0건
    _validate_immutable_tree  pinvi ACCEPT / map ACCEPT
    일회용 worktree 등록      제거됨 (bare + 핀 worktree만 남음)
    일회용 디렉터리           제거됨
    격리 스택                 컨테이너 0개

즉 `e6b52db4`는 지금 **다시 실행 가능한 상태로 남아 있다.** 이전 두 번은 그렇지 않았다.

### 그리고 그 잔여물이 처음으로 관측됐다

새 receipt 증거 `disposable-run-worktree.json`:

    ignored_entries    3
    untracked_entries  0
    tracked_changes    0
    top_level_names    ["apps", "node_modules"]

이 세 건이 봉인 트리를 오염시키던 바로 그 잔여물이다. `node_modules/`·`test-results/`는
`.gitignore`에 있고 `playwright-report`는 빈 디렉터리라, 러너의 `--untracked-files=all`도
attestation의 `_assert_clean_checkout`도 **넷 전부에 눈이 멀어 있었다** — 유일한 탐지기가
다음 실행의 모드 검사였고 그때는 이미 사이클을 태운 뒤였다. 봉인 트리를 실행에서 빼면서
그 탐지기마저 사라지므로, 삭제 **전에** `--ignored=matching`까지 세어 증거로 남기게 했다.
`tracked_changes 0`은 실행이 추적 파일을 건드리지 않았다는 뜻이다.

### 남은 것은 소유자 판정이다

`T-VN-41F1D-D1`은 자체 해제 조건이 **`T-VN-FINAL-REBUILD` barrier(B4 재판정)가 현재
candidate를 유지한다고 판정한 뒤 실행**하라고 정한다. 그 barrier는 아직 열리지 않았고
(`docs/tasks.md`의 `[~]`), 이번 실행이 그것을 대신하지 않는다. D1이 요구하는 일곱 image
ID·schema head 대조는 격리 e2e attestation이 아니라 **generation attestation**의
산출물이다. 그래서 D1/D2/41C/E는 열어 둔다 — 판정은 소유자 몫이다.

## 2026-09-03 — 침묵사 세 번의 정체와, 이틀 묵은 red의 진짜 이유

격리 e2e가 두 번(18·19), pinned rebuild가 한 번(021) **로그 0바이트**로 사라졌다.
실패가 아니라 침묵이었으므로 먼저 관측을 고쳐야 했다.

### 관측이 먼저 결함이었다

하네스와 런처는 `python -I`로 돈다. `-I`는 `-E`를 함의하므로 `PYTHONUNBUFFERED`가
**무시된다**. stdout이 파이프면 블록 버퍼링이 되고, 프로세스가 시그널로 죽으면
버퍼째 사라진다. 30분을 돌고도 한 줄도 안 남는다. 게다가 rebuild 런처는 자기
stdout을 `result.json`/`stderr.log`로 따로 돌리므로, pty를 물려도 그 두 파일이
0바이트면 아무것도 알 수 없다.

`systemd-run`으로 옮기자 세 번의 침묵이 감추던 것이 **한 줄로** 나왔다:

    run-pinned-rebuild-once[1390161]: pinned rebuild candidate was already claimed

로그인 세션이 아니라 `system.slice`에서 돌고, 종료 사유·시그널·exit code가
journald에 반드시 남는다. 이 저장소의 긴 원격 작업은 앞으로 이 방식으로 띄운다.

### 진단을 한 번 틀렸고, 그대로 적는다

처음에는 **다중 타깃 bake**를 원인으로 봤다. e2e19의 dockerd 트레이스가 그것을
뒷받침했다 — trace `c41fa490…` 하나에 `app-api`의 apt 단계와 `app-web`의
`npm ci`가 동시에 살아 있었고, 2초 뒤 `only one connection allowed`, 5초 뒤
`healthcheck failed fatally`였다. 그 관찰 자체는 사실이고, `compose build`가
타깃을 하나로 묶는 것도 사실이라 PinVi `docker-app.sh`를 서비스별로 나눴다.

그런데 rebuild-021은 **단일 타깃·단일 trace**인데도 죽었다. 더 결정적으로,
`only one connection allowed`는 **성공하는 빌드에서도** 15분에 8건씩 난다(실측).
즉 그 경고는 잡음이었고, rebuild-021의 죽음은 별개다 — 프로세스가 사라졌고
그 결과 claim이 소각됐다. 직렬화 수정은 여전히 옳지만(요청을 나누면 세션이
겹치지 않는다) 침묵사의 원인은 아니었다.

### 소각이 기본값이 아니라 유일한 결과였다

`run-pinned-rebuild-once`는 `ktdctl` 실행 전에 `O_EXCL` claim을 쓰고, 해제는
**자기 프로세스가 살아서 결과를 분류할 때만** 한다. 프로세스 그룹이 죽으면
분류기 자체가 돌지 않으므로 해제 경로는 실행될 수 없다. registry는 이 pinset의
generation이 아직 오르지 않았다고 말하는데도 다음 실행이 `already claimed`로
거부됐다 — 아무것도 소비하지 않은 실행권이 근거 없이 죽었다.

소각은 **소비했다는 양성 증거**가 있을 때만 정당하다. 대칭으로, 반대 방향에도
양성 증거가 있으면 되찾을 수 있어야 한다. 증인 둘(registry의 `pending_rebuild`
+ 이전 output에 `result.json` 없음)이 함께 참일 때만 되찾는다(Manager #309).
전역 lock이 동시 실행을 이미 막으므로 그 둘이 함께 참이면 이전 실행은 죽은 것이다.

### main이 이틀째 red였던 진짜 이유는 스키마가 아니었다

`test_dedup_candidate_rejects_uuid_identity_and_accepts_text_feature_id`가
2026-09-01(#1132에서 추가된 날)부터 계속 깨져 있었고 문서에도 없었다. 로컬
PostGIS로 재현해 예외 원문을 보니 스키마는 내내 정상이었다 —
`manual/provider candidate Feature proof is not eligible`, 즉
`ck_m05_candidate_feature_proof`가 제대로 발화했다.

틀린 것은 **읽는 쪽**이다. 이 저장소는 `postgresql+asyncpg`로 도는데, asyncpg
예외는 `.sqlstate`와 `.constraint_name`을 직접 들고 있고 `.diag`가 없다 —
`.diag`는 psycopg의 API다. 세 곳이 `getattr(orig, "diag", None)`으로 constraint
이름을 읽었으니 런타임에서 항상 `None`이었다. 바로 윗줄의 sqlstate는 같은
자리에서 잘 읽히므로 아무도 이상을 느끼지 못한다.

테스트만의 문제가 아니었다. `feature_request_repo`의 `ck_feature_request_pending`
분기가 한 번도 발화하지 않아 이미 처리된 요청 재제출에 상태 충돌 대신 검증
오류가 나갔고, `feature_reference_reconciliation_repo`의 M05 allow-list는 아홉 개
제약이 통째로 죽어 generic writer 오류로 떨어졌다. 정본은 이미 있었다 —
`feature_update_active_repo._driver_constraint_identity`가 두 드라이버를 모두
다루고 예외 체인까지 걷고, 두 모듈은 이미 그것을 import한다. 같은 사실이 네 곳에
선언돼 있었고 그중 셋이 틀렸을 뿐이다(#1139).

여기에 `anyio` 드리프트가 겹쳐 있었다. 미고정 anyio가 새 릴리스로 올라오며
starlette testclient의 `anyio.abc.BlockingPortal` 별칭이 deprecated가 됐고,
`filterwarnings=error`가 그것을 **수집 오류**로 승격시켜 파일 하나가 unit job
전체를 중단시켰다. 같은 커밋 `acd1ff61`이 09-02 12:40에는 통과하고 09-03 04:11
재실행에서 3.11/3.12/3.13 전부 깨지는 것으로 드리프트를 확정했다(#1138).

### 게이트가 있는데 아무것도 막지 않던 것 셋

- **`frontend.Dockerfile`이 워크스페이스 셋 중 둘만 복사했다.** `npm ci
  --workspaces`는 선언된 것을 전부 설치하라는 뜻인데, 매니페스트가 없으면 npm은
  조용히 뺀 트리를 만든다. `frontend.yml`은 전체 체크아웃에서 같은 명령을 돌리므로
  영원히 통과한다 — **Dockerfile 경로는 Map CI에서 한 번도 빌드되지 않는다**(#1137).
- **geo 검증기가 psql 실패를 "완료"로 보고했다.** `psql | tr` 파이프가 종료
  상태를 가렸고 `case`에 빈 값 분기가 없어 `*)`로 떨어졌다(Manager #310).
- **ETL 헬스체크가 `/server_info`를 봤다.** 정적 버전 문서라 code location이
  죽어도 200이다 — PII 보존 job이 멈춰도 컨테이너는 끝까지 healthy였다(PinVi #524).

### 그리고 e2e21이 본문까지 가서, 다음 벽을 보여 줬다

수정을 얹은 e2e21은 처음으로 Map 9 + PinVi 7 컨테이너를 모두 띄우고 M04/M05
본문까지 갔다(1시간 41분). 거기서 남긴 실패는 의미가 있었다 —
`live Map admin OpenAPI does not match the pinned source artifact`.

계약의 digest는 핀된 revision의 blob과 정확히 일치했으므로, 어긋난 것은 **런타임
문서 대 계약**이었다. 핀된 이미지 안에서 직접 문서를 생성해 보니 161 path,
계약은 162 path — 차이는 `/v1/debug/mois-license/{license_id}` 하나였다.

그 라우트는 `debug_routes_enabled` 뒤에 있었다. 그 flag의 **코드 기본값은
`true`**(local-dev)인데 Docker image 기본 profile은 `production`이고, production은
"``/debug`` routes have no authentication"을 이유로 `false`를 강제한다. 즉
`export_openapi.py`가 기본 설정으로 만든 계약은 **운영이 절대 제공하지 않는
라우트**를 기술했고, 실행 중 표면과 계약을 바이트 비교하는 attestation은 운영
구성에서 구조적으로 통과할 수 없었다.

라우트를 지웠다. 도입 이후 admin frontend에 호출부가 한 번도 없었고, 같은 raw
payload는 운영에서 도달 가능한 `/v1/features/{feature_id}/sources`가 이미 준다.
삭제된 라우터만을 위해 있던 `feature_repo.get_primary_source_detail`도 함께
지웠다 — 운영 caller가 0이었고 주석은 존재하지 않는 표면 둘을 가리키고 있었다.

**불변식은 flag가 아니라 표면 위로 옮겼다.** 라우트를 지우면 그 flag를 읽는 코드가
하나도 남지 않는다. 그러면 flag는 아무것도 막지 않는데 문서만 막는다고 말한다 —
오늘 내내 고쳐 온 바로 그 모양이다. production은 이제 마운트된 `/v1/debug` 경로
자체를 기동에서 거부한다.

### 적대 리뷰가 71분짜리 함정을 미리 잡았다

전문 리뷰어 둘(보안·계약 / attestation 체인)이 붙었고, 후자가 **내가 걸어 들어갈
경로**를 짚었다. PinVi의 `generate_m05_pair_contract.py --write`는 v2 봉투를 쓰는데
소비자 `config.py`는 `version == 1`을 **모듈 스코프에서** 요구한다. Manager의 격리
preflight는 v1/v2를 함께 읽으므로 회전 전에 잡지 못하고, 실패는 71분짜리 rebuild를
태운 뒤 "컨테이너가 뜨지 않는다"로만 드러났을 것이다. 생성기가 봉투 판을 정하지
않도록 고쳤다.

전자는 flag가 무력해진 것과 게이트가 정책표 금지로 **교착**을 만드는 것을 짚었다.
둘 다 반영했다 — 강제는 표면 위로, 게이트는 grep이 아니라 AST route 선언 분석으로.

### 이 결함 계열이 하루에 다섯 번 더 나왔다

다중 타깃 bake(두 경로가 같은 교훈을 각자 알아야 했다), Dockerfile 워크스페이스
목록(두 파일이 각자 선언), `docker-app.sh`의 build/verify 목록(한 함수 안에서 두
번), 그리고 constraint reader(네 곳). 규칙은 이미 `AGENTS.md` DO NOT 15에 있다 —
유도 → 결박 → 탐지, 그리고 결박은 가장 이른 지점에.

## 2026-09-02 — rebuild를 실제로 태웠고, 그게 결함 두 개를 드러냈다

보류가 풀려 `rotate-pair → rebuild → e2e17`로 갔다. **첫 rebuild가 실패했고**,
그 실패가 준비 중이던 수정의 실제 사례이자 PinVi 쪽 별개 결함의 발견 경로였다.

### 실측

pinset `cc3c516f`(Map `f58de9f4` + PinVi `5cf41d20`) rebuild가 29분 실행 후
`{"status":"failed","classification":"unclassified"}`로 닫혔다. `stderr.log`는
**0바이트** — `--json`이 원문을 억제한다. journal 미생성,
`generation_public_copy: pending_rebuild`. 아무것도 소비하지 않았는데 launcher는
claim을 유지했다.

### 결함 1 — 봉인 밖 실패가 회전 사이클을 태운다 (Manager #302)

launcher는 `classification` 하나로 claim 해제를 판정한다. 그래서 봉인 밖에서
새는 오류는 곧 소비하지 않은 pinset 소각이다. 그 경로에 **fresh candidate 빌드
분기 전체**가 들어 있었다 — 이 흐름에서 가장 오래 걸리고 가장 잘 실패하는 구간이
하필 분류를 잃는 구간이었다.

고치는 방식도 두 번 틀렸다. 봉인 밖 지점을 **열거**하는 방식은 셋째·넷째가
계속 나왔고, lock 획득처럼 `with` 문으로는 표시조차 못 하는 것도 있었다.
선언을 버리고 **관측**으로 갔다 — journal 경로를 알게 되면 적어 두고 실패 시
그 파일의 존재를 본다.

### 결함 2 — PinVi 프로덕션 web 이미지가 서지 않았다 (PinVi #518)

원문은 비-JSON으로 한 번 더 돌려 얻었다:
`pinned runtime rebuild Compose build command failed (exit 1)`. `pinvi-web`이었고,
원인은 셋이 겹친 것이다.

1. deps 스테이지가 workspace manifest를 **손으로 나열**하는데 `apps/mobile`이
   빠져 있었다 — 루트 `workspaces` glob과의 이중 선언.
2. `npm install`은 그 불일치에서 lockfile 트리를 **조용히 버린다**
   (`npm ci`는 exit 254로 거부한다 — 실측).
3. 그 트리에서 루트는 `tailwindcss@3`, `apps/web`이 쓰는 `4`는 중첩됐는데
   build 스테이지가 루트만 복사했다.

그리고 **CI가 이 이미지를 빌드한 적이 없었다.** 전체 체크아웃에서 `npm ci` 후
`npm run build`만 하므로 *다른 트리*를 검증한다 — CI는 초록인데 이미지는 서지
않고, 그 사실이 1~2시간짜리 rebuild에서야 드러났다. `docker-image` job을
신설해 required로 넣었다.

### 적대 리뷰가 내 수정에서 다시 찾은 것

3회에 걸쳐 리뷰어가 mutation으로 **내 테스트가 공허함**을 증명했다.

- 관측 배선을 어떤 테스트도 걸지 않아 `observe()` 삭제·이동이 통과했다
- `postjournal_failure`를 지워도 1535건이 통과했다
- pinset 식별 **뒤** 경로 계산 실패가 소비된 후보를 해제하고 있었다
- PinVi 쪽에서는 "열거하지 않는다"고 써 놓고 런타임 스테이지에 workspace
  하나를 결박해, 그 중첩이 사라지면 프로덕션 빌드가 죽게 만들어 놨다

전부 반영하고 mutation으로 잡히는 것을 재측정했다.

### 현재

새 pinset `4516a107`(Map `f58de9f4` + PinVi `448f6a3e`)로 회전하고 rebuild
재실행 중. 다음은 e2e17.

## 2026-09-01 — e2e 없이 소각 blocker 5건 선적발: 시뮬레이션 하네스 3종

**문제.** M05 isolated one-shot은 1회에 pinset 소각 + 1~2시간이 든다. 게다가
본문(`m04_m05_e2e`) 진입 후 실패는 **무조건 소각**이라 3개 저장소 revision을
새로 만들고 rebuild부터 다시 해야 한다. e2e13~e2e16이 모두 "한 층 더 깊은
결함 1건 적발 후 소각"으로 끝났고, 결함이 하나씩만 드러나 진척이 선형이었다.

**전환.** 실행 없이 코드 레벨에서 계약을 검증하는 하네스를 세 층으로 세웠다.

1. **정적 parity**(실행 없음) — 두 곳에 따로 선언된 같은 사실을 문자 단위로
   대조하는 테스트. 기존 `_PUBLIC_TERMINAL_PHASES` ↔ launcher `PHASES` 관례를
   일반화했다.
2. **로직 시뮬레이션**(fake docker/HTTP, 실 driver 코드) — Manager 하네스 A.
   mini Compose 렌더러와 fake docker CLI를 붙여 driver 전 경로를 실행하고,
   launcher heredoc에서 receipt 검증기를 추출해 같은 프로세스에서 재현한다.
3. **DB 실행 시뮬레이션**(CI PostGIS testcontainer) — Map 하네스 B. M05 DB
   시나리오 전체를 실 PostGIS에서 재생한다.

**비-vacuous 검증.** 세 하네스 모두 mutation testing으로 확인했다. A는 과거
결함 13건을 재적발했고, C는 34개 mutation 중 11건을 잡았다.

**적발.** 대부분이 같은 결함 클래스였다 — *같은 사실이 두 곳에 따로 선언되고
둘을 잇는 기계가 없다*.

- **`PINVI_M05_LIVE_E2E` 미주입**(PinVi #511): M04 쌍둥이 경로에는 있는데 M05
  경로에만 빠져 있었다. spec이 `beforeAll`에서 중단된다 — 소각.
- **isolated에서 `reviews.json`/`restore.json` 강요**(PinVi #511): 사람 리뷰·복구
  드릴의 외부 증거라 격리 harness는 생산할 수 없는데 생산자·검증자 양쪽이
  6키를 요구했다. UI가 green이어도 봉인에서 죽는다 — 소각.
- **receipt 단발 GET**(Manager #292): 이름과 달리 재시도가 없어 Map decision
  commit과 PinVi worker polling 사이 창에서 404로 죽는다. 수리하며 계약을 다시
  읽어보니 status는 `blocked|applied` 두 값뿐이고 "아직 도착 안 함"은 404였다 —
  종전 구현이 보던 `pending`은 **존재하지 않는 상태**였다.
- **pre-claim phase 집합 분기**(Manager #293): driver는 31개 phase로 claim 전
  종료할 수 있는데 launcher는 5개만 알았다. 보정 가능한 실패가 무조건 소각으로
  승격된다. 적대 리뷰가 내 첫 수정에서 claim **이후**에만 도달 가능한 phase 3개를
  잡아냈다 — 그대로 뒀으면 "실행권 미소비" 주장이 소비 증명 phase를 달고 검증을
  통과했을 것이다.
- **`map_fresh_init_reason` 자유형 진단**(Manager #295): driver가 사람이 읽는
  문자열을 receipt에 싣는데 launcher는 16개 닫힌 enum으로만 받는다. 벗어나면
  ValueError → fallback `pin block-execution` → 소각. #293의 수리가 이 경로에서는
  통째로 무력화된다. 하네스 A가 playwright driverVersion 불일치 경로에서 실측
  재현했다. 어휘를 exit map에서 파생시켜 한 번만 선언하고, 어휘 밖 값은
  `unclassified`로 바꾸지 않고 **필드를 생략**한다 — `unclassified`는 "fresh-init
  runner가 미상 exit code로 죽었다"는 다른 사실이라 무관한 진단에 붙이면 receipt가
  거짓을 주장한다.
- **playwright image 도메인**(PinVi #513): 같은 정규식이 세 곳에 있는데
  `config.py`만 tag를 필수로 요구했다. Manager가 고정한 핀은 digest-only라 같은
  값이 한쪽에서만 거부된다.

**정리.** 소각 blocker 5건이 실행 전에 잡혔다. e2e13~e2e16이 4회에 걸쳐 4건을
잡은 것과 대비된다.


## 2026-09-01 — 303: M05 dedup case의 payload hash 도메인 정합

e2e16(사상 첫 dedup case 기록 경로 실주행)이 적발한 실계약 비정합:
`source_record_raw_payload_hash`(사본)만 64-hex를 강제해, 기본
`make_payload_hash`(32-hex prefix) 규약으로 적재된 **모든** provider
레코드가 M05 case 기록에서 CheckViolation으로 죽는다. 303이 사본 도메인을
원본(`^[0-9a-f]{1,64}$`)과 정합시킨다. 적대 리뷰 2인이 critical을 추가
적발했다 — receipt head CHECK 열거에 303을 더하지 않으면 fresh 설치의
receipt 기록이 프로덕션에서 죽는다(널리기-전용 열거 + `_UPGRADE_STATEMENTS`
모듈 상수 규약 반영). graph artifact는 generator canonical(`--write`)로
재직렬화했고, 사본-도메인 갈라짐을 잡는 lint를 추가했다.

cross-repo 선행 순서(리뷰 지적): 이 head 이동은 Manager committed
generation과 어긋나므로 머지 → rotate-pair → pinned rebuild로 generation을
303으로 재커밋한 뒤에만 isolated one-shot이 성립한다.

## 2026-09-01 - M05 isolated one-shot, 역대 최초 본문 진입 (e2e13)

pair 재핀(#506) 이후 one-shot을 13회 돌리며 잠재 결함을 층위별로 소거했다.
매 회 더 깊이 침투했고, 각 층은 적대 리뷰 2인(opus/xhigh)을 거쳐 Manager/
PinVi에 머지됐다.

- e2e1-2 pair_contract_invalid -> PinVi pair 재핀(#506).
- e2e3 PinVi->Map 네트워크 불통(컨테이너 내부 probe로 timeout 실측) ->
  PinVi docker-app.sh 범용 overlay(#507) + Manager가 첫 up부터 override
  전달(#280; 리뷰가 !reset의 정적 IP 삼킴, /29 만석, stale-pin 무음 우회
  3연쇄를 추가 적발).
- e2e4 정적 IP를 postgres가 동적 선점 -> 상단 배치 규칙(#281).
- e2e5 host publish 포트가 kernel ephemeral 대역과 충돌 -> 20000-29999
  이동 + 하한 런타임 계약(#282).
- e2e6 profile-scoped dagster 잔존이 cleanup 검증을 깨고 실제 phase를
  가림 -> cleanup 프로파일 모델 파생 + driver_phase 정본 복원(#283 -
  리뷰가 '첫 PASS가 receipt 무효로 소각되는' 잠복 critical까지 적발).
- e2e7-9 무증거 실패 -> forensic 전면화: 모든 명령 stderr(#284), ordinary
  exception traceback(#286), scrub 실효화(생성 즉시 등록).
- e2e8 이미지명 추측('No such image') -> rendered compose 모델 파생(#285).
- e2e12 traceback이 익명 예외의 정체를 적중: Ports 키 정확일치가 EXPOSE
  메타데이터(prod 12701)와 원리적으로 충돌 -> published(실 binding) 집합
  비교(#288 + PinVi 이미지 프로젝트 스코프, pair admin==full 가드).
- e2e13: 사상 처음 m04_m05_e2e 본문 진입. 실패는 호스트 정리가 지운
  Playwright runner 이미지 부재 - body라 execution이 무조건 소각됐고,
  runner 핀 digest를 claim 전에 보장하는 #289로 클래스를 제거했다.

일관된 패턴: "PR CI는 green인데 한 번도 실행된 적 없는 경로"의 잠재 결함
들이 침투 깊이에 비례해 드러났다. 남은 미지 표면은 본문 내부(m04 승인
흐름 -> m05 rebind 흐름 -> receipt 서명)뿐이다. 다음 pinset(이 문서 커밋
포함)으로 e2e14를 실행한다.

## 2026-08-31 — M05 rebuild 두 번째 벽: permit evidence의 반쪽 head-인지

#1128로 sealed builder를 고치고 pinset을 재회전(Map 58158472)해 rebuild를 다시
돌렸더니 이번엔 API/Dagster `up`에서 전멸했다 — 컨테이너 로그의 원문은 "final
permit fresh finalize generation is invalid". permit 실물과 레포 계약을 나란히
대조해 확정했다: receipts 블록은 이미 head 인지("root 너머에서는 봉인 digest가
서술하는 상태가 존재하지 않는다")로 고쳐져 있는데, **operation evidence 블록만
pre/post catalog를 봉인 계약과 무조건 대조**하고 있었다. head 302의 fresh 실측
(pre fc32b351/post 00800ab7)은 300 시절 봉인값(5d39c2b2/e7fbf7e7)과 다를 수밖에
없다 — 이전 green permit들(head 300)은 정확히 봉인값과 일치했다.

#1129가 receipts와 같은 원리로 정렬한다: root 너머에서는 post를 receipts의
observed catalog와 교차 결박하고 pre는 well-formed digest만 요구. 적대 리뷰
2인(opus·xhigh) 모두 approve — 반영: 사용 지점 `_require_sha256`(순서 의존 제거),
주석의 앵커를 실제(Manager의 pre==직전 post 결박 + `_verify_database`의 live
재관측)로 교정, malformed pre 음성 테스트 추가. 리뷰가 남긴 후속 과제: head별
destination catalog 재컷으로 봉인 대조 복원, Manager 쪽 동일 교차 검사 대칭.

단위 fixture가 아티팩트 값으로 evidence를 만들어 이 결함을 못 보던 것도 고쳤다
— beyond-root 현실(봉인값 ≠ 실측)을 그대로 모델링하는 테스트가 이제 원본 코드를
정확히 1건 실패시킨다.

## 2026-08-31 — M05 activation rebuild 실패의 근본원인: wheel에 안 실린 package-data

Manager main(5f70770d)을 trusted release로 설치하고 pinset을 원자 회전(Map 13407ba9
· PinVi e0750505)한 뒤 `run-pinned-rebuild-once`를 돌렸더니 `application_builder`
단계 prejournal 실패(수리된 phase-scoped 기계 덕에 pinset은 안 탔다). envelope은
stage만 말하므로, sealed builder를 수동 재현(digitie 권한, 로그 캡처)해 원문을 얻었다:
**"candidate image installed runtime tree가 sealed Git archive와 다르다"** — expected
/observed manifest를 직접 재생성·diff하니 정확히 한 줄, `providers/_provider_surface.json`.

689aecce(Protocol 결박 게이트)가 이 JSON을 `src/kortravelmap/providers/`에 추가했지만
`[tool.setuptools.package-data]`에 등록하지 않아 wheel에서 빠졌다. sealed 게이트는
소스 트리 **전 파일**을 기대하고 이미지에선 `.py`/`.json`/`py.typed`만 관측하므로,
이 클래스(미선언 package-data / 비가시 확장자 / 데이터 전용 디렉터리)는 PR CI 전부
green인 채 Manager rebuild에서만 터진다 — "오랜 기간 진전 없음"을 만들던 late-failure
패턴 그 자체다. #1128이 package-data 한 줄 + 정적 lint 3종
(`tests/lint/test_sealed_runtime_tree_ship.py`)으로 클래스 전체를 PR 시점으로 끌어온다.
negative case 실측: 수정 전 pyproject로 되돌리면 정확히 그 lint 1건만 실패한다.

## 2026-08-31 — 적대 리뷰 2인(opus·xhigh)의 16건 실측 발견과 수리

두 리뷰어가 전부 **실행으로** 검증했다(n150 실 DB probe, 뮤테이션 주입, TestClient).
CONFIRMED HIGH 2건이 특히 무거웠다.

- **F1 부팅 실패**: 302의 recorder EXECUTE grant가 ADR-090 preflight의 exact-set을
  깨서 head=302 DB에서 API가 기동 불가였다(compose는 preflight 강제). 격리 live
  green이 이 게이트를 통과한 증거가 아니었다 — 스택이 preflight를 안 켰던 것.
  db.py 허용 목록에 recorder를 추가했다.
- **F2 kill-switch 우회**: import preview/commit이 단건 manual 생성의
  kill-switch·전용 token을 우회했다. 조건부 가드(assert_manual_feature_create_for_import)
  + BFF의 import 경로 token 부착(구성 시)으로 닫았다.
- **H1/H2/F3 재수렴**: '이미 반영된 manual 행이 든 CSV는 영구 재commit 불가(원문
  DB 메시지 409)' + '완결성 검사가 이전 batch의 item으로도 통과' — 재수렴 설계로
  해소: 같은 typed payload면 이전 child linkage를 재사용(reused=true), linkage 없는
  동일 identity/payload 변경은 원인을 말하는 오류. coverage 가드가 no-op 발급을
  중단시킨다. 통합 테스트가 재수렴(동일 child 재사용, linkage 1개 유지)을 실 DB로
  검증한다.
- **H3 recorder 교차검증**: FK 일곱을 전부 만족하는 '교차된' linkage가 통과하던
  것을 5축(행번호↔receipt·plan payload digest·decision 종류·item↔feature·부모
  actor) fail-close로 봉인.
- **H4/F4 집계**: fresh 생성이 updated로 계상되던 것을 inserted로 보정(preview와
  정합). **F5**: manual 행이 'unmatched/미연결로 남습니다'로 통보되던 것을
  valid→imported(+resolved UUID)로. **F6**: manual_children.feature_id의 legacy
  `f_*` 노출(신규 live spec이 그걸 못박고 있었다)을 UUID 정본 + reused·
  terminal_status로 교체. **F7**: import child origin의 거짓 principal — CHECK
  widen + writer CASE. **F9**: 좌표 서비스 범위(124~132/33~39.5)를 preview가 반환.
  **F10/F11**: 자기참조 단언 실질화, manual_children 라우터 계약 테스트(뮤테이션
  M2 검출). L7은 NOT VALID+VALIDATE로.
- 부수 발견: **충돌 PR은 pull_request 워크플로가 조용히 0건**이다(merge ref 생성
  불가) — #1127이 CI 침묵의 원인이었고 리베이스로 해소했다.

수리 후: mypy --strict core/api·lint-imports·ruff green, M03 통합 3/3(재수렴 포함),
격리 live acceptance 2/2(수리된 계약 — token 가드·UUID 뷰·inserted 보정 실측).

## 2026-08-31 — M03 격리 live acceptance green + 잠복 500 수리

사상 첫 manual-create live harness가 n150 격리 스택(302 head)에서 완주했다:
UI CSV 업로드 → preview(201) → commit(200, `manual_children` 확정값) → admin REST에서
생성 Feature 관측. 전제 두 가지를 실측으로 확인했다 — (1) theme/source는 retained
catalog에 선존재해야 한다(import는 catalog를 만들지 않고 preview가 422 fail-close),
(2) Idempotency-Key는 BFF가 허용 목록으로 전달한다.

acceptance가 최초로 노출한 **잠복 결함**: feature 상세 라우트가 curation item을
`AdminCurationItemView.model_validate(item, from_attributes=True)`로 직검증해
CurationItem에 없는 `command_etag`(그리고 int `row_revision`) 때문에 **curation이
달린 모든 feature 상세가 500**이었다. 기존 테스트가 전부 빈 tuple을 mock해 숨어
있었다. curations 라우터의 `_admin_item_view`(정본)로 교체하고, 실제 item을 실은
회귀 테스트를 추가했다.

## 2026-08-31 — M03 302: import 행별 manual Feature child 발급 완주 (실 DB green)

`301`이 만든 linkage 표를 실제로 채우는 쓰기 계약 셋을 `302`로 확장하고, repo·route를
결선해 통합 테스트가 실 PostGIS에서 완주했다.

- **CSV**: `manual_feature_category`(8자리) typed 열 추가 — writer가 category를
  요구하는데 item 인자에 원천이 없다. 이름은 `place_name`이 소유(비면 preview 거절).
  typed payload가 {kind, category, coord}로 확장돼 child identity에 category가 결박.
- **302 migration**: (1) writer operation 검사를 child operation까지 확장,
  (2) apply가 manual 행 item upsert를 건너뛰고(EXCLUDED.feature_id=NULL이 writer의
  feature 결박을 지우는 경로 차단) 행별 좌표(o_row_receipts)를 반환하며 manual 행의
  decision을 accepted/manual_feature_child로 기록(종전 분기면 'revoked'로 강등됐다),
  (3) linkage 전용 SECURITY DEFINER 기록기(ops, 소유권은 임시 스키마 CREATE grant로
  command owner에 이전), (4) match_basis·receipt head CHECK 확장. 프로시저 본문은
  baseline에서 기계 파생한 sidecar — diff가 수정 지점만 보이고 downgrade가 원본
  바이트로 복원된다.
- **repo/route**: 결정적 child identity(§6.2)로 lock→claim→writer→apply→linkage→
  child result를 한 SERIALIZABLE transaction에 배선. manual 행은 command 경로
  전용(가드), 부분 성공 없음. 부모 응답에 ordered `manual_children` — 요청 JSON이
  아니라 transaction 확정값에서 구성. OpenAPI 재생성.
- **검증**: 신규 통합 테스트가 child command identity·feature/origin·linkage 5축·
  decision 종류·item feature 결박 생존·child terminal result를 실 DB에서 확인.
  mypy --strict core/api green, 통합 회귀(dict 동등 단언 4곳) 반영.
## 2026-08-31 — 적대 리뷰 라운드2: 원장 게이트 3종을 파싱 정본 위에 재작성

라운드1 게이트는 각자 다른 구멍을 갖고 있었다 — 삭제 게이트는 diff 줄 정규식이라
bold/들여쓰기/fence를 못 봤고(R2-S3/S6), coverage 게이트의 covered()는 substring이라
부모 섹션의 산문 언급으로 우회됐고(R2-S2), 사이즈 게이트는 이름 열거라 그 사각지대에서
`tasks-done.md`가 374KB까지 자랐다(R2-S8).

수리: (1) `scripts/task_ledger_lint.py` — fence/HTML 주석 제외·malformed 표기
fail-closed·bold/backtick 허용 ID 추출을 가진 **파싱 단일 정본**. 게이트 전부 이걸
import한다. (2) 삭제 게이트는 diff 줄이 아니라 **base/HEAD 전체 파일의 체크박스 집합
비교**로 전환 — tasks.md 삭제는 done의 `[x]` 실질 엔트리(stub 거부, 40자), acceptance
삭제는 추가 줄의 ID 명시(삭제 근거)를 요구하고, `tasks-acceptance.md`도 감시한다(R2-S7).
push 이벤트 base는 `github.event.before` 우선(all-zero면 origin/main 폴백, R2-S11).
(3) covered()는 정확-토큰 + **list 항목 선언**만 인정(연속 들여쓰기 줄 포함) — 산문
언급·부정문은 덮임이 아니다. (4) 사이즈 게이트는 `docs/**/*.md` rglob. `tasks-done.md`는
2026-08 live + 아카이브 2샤드로 분리했다. (5) journal 훅은 당월 shard + 추가 줄>0만
기록으로 인정(R2-S10). (6) 배리어 덮임 주장은 실제 메커니즘 이름(B2↔pinned-release
OpenAPI blob SHA, B3↔pinset_sha256 equality)으로 정밀화하고(R1-S7), 귀속 부기 B4/C3의
체크박스를 해제했다(R1-S11 — `[x]`는 "기준 충족"으로 읽힌다).

검증: 뮤테이션 4종(무이관 삭제·미언급 기준 삭제·fence 은닉·malformed 표기)과 coverage
뮤테이션 3종(헤딩 제거·산문 언급·list 선언)을 실제로 주입해 전부 잡히는 것을 확인했다.

## 2026-08-31 — 정체 근본원인 감사와 채택 개선 (5-agent 워크플로우)

분석 3인(타임라인 포렌식 / 결박 전수 / 트레드밀 구조) + 적대 리뷰 2인이 진단 4건을
반박하고 완화안 4건을 기각한 뒤 남은 것만 채택했다. 정본은
`docs/reports/map-stall-root-cause-2026-08-31.md` — 기각 처방 9건도 §5에 남겨 재제안을
막는다.

**판정: 정체는 livelock이 아니라 반복 단가의 발산이다.** 한 사이클(pair 회전 + 단발
rebuild + one-shot 실행)의 산출이 terminal phase enum 1개였고, terminal 27개 중
acceptance 본문 도달은 0건 — 후보 예산 전부가 인프라 단계에서 소진됐다. 단가를 만든 세
인자: 관측 결핍(`ports: !reset` 한 줄이 4개 candidate를 태움) × 무조건 소각(phase-scoped
기계가 있는데 배선 안 됨) × 값/상태 고정(head 리터럴 17곳, 봉인 digest 3지점).

이 저장소의 채택분:

- **배리어 B1~B3 삭제**(I-3, STRENGTHENED) — 같은 문단의 실행 시점 exact-equality가
  셋을 정확히 덮는다. B4는 유지 — env/compose/role·ACL 표면은 런타임 대조가 안 덮는다.
- **동일 사건 중복 부기 접기**(I-6) — MAP-HEALTH-TRANSPORT B4·ADMISSION-TERMINAL C3를
  ACTIVATION A3로 귀속, 두 task 완료 이관. 열린 task 25 → 21.
- **원장 게이트 3종**(I-7) — 체크박스 삭제 게이트(선례: 6d671ef1 평면화 다음 날 완료
  처리), live journal(568KB)/resume(376KB) 분리 + 220KB 게이트를 live에도, archive
  shard 기입 인정.

Manager 쪽 채택분(I-1/I-2/I-4/I-5/I-8/I-9)은 Manager PR #278, PinVi 쪽(I-10)은
PinVi #505가 소유한다.
||||||| parent of 09d018d8 (docs: M03 302 완주 기록과 다음 작업(격리 live acceptance))

## 2026-08-31 — head 값 고정을 걷어내고, `301`이 왜 아직 못 올라가는지 실증했다

`T-VN-M03`의 linkage migration을 올리자 무너진 것은 테스트 스냅샷이 아니라 **배포
계약**이었다. `application_head = "300"`이 Map 6곳 + Manager 11곳에 리터럴로 박혀 있었고,
같은 값의 사본이 서로 일치한다는 것을 아무것도 강제하지 않았다.

**head를 파생값으로.** `application_schema_head()`가 migration graph에서 단일 head를
유도하고 head가 0개거나 2개 이상이면 fail-close한다. 배포 executable 넷 + `env.py` +
`api-entrypoint.sh` + `dagster-storage-migrate.py` + `run-admin-stack.sh`가 읽는다. `300`은
`BASELINE_ROOT_REVISION`으로 이름을 따로 받아 남는다 — head가 아니라 역사적 좌표다.

닫은 잠복 파손: `env.py`의 fresh 설치 facet 검증이 head가 움직이면 **조용히 꺼지던** 조건,
`api-entrypoint.sh`의 프로덕션 기동 차단, `dagster-storage-migrate.py`의 DB 판정 arm,
`run-admin-stack.sh`가 자기 DB를 거절하던 자리.

### `301`은 왜 아직 못 올라가는가 — 통합 실행이 실증했다

PostGIS 통합 6건 실패 중 둘이 결정적이다. sealed baseline(`alembic/baseline/*.sha256`)은
`300` 시점의 물리 catalog와 `alembic_version` facet을 고정하는데, **세 지점이 live DB를 그
digest와 exact 대조한다** — fresh installer `:940`, finalize `:418`, final-permit `:602`.

facet 계약 SQL은 조건에 `alembic_version = ARRAY['300']`을 담은 **단일 boolean**이라 head가
움직이면 언제나 `mismatch` 한 값만 낸다. 옮겨갈 digest가 존재하지 않는다.

내가 먼저 넣었던 우회 — facet 대조를 건너뛰고 baseline digest를 receipt에 그대로 적기 —
는 **실패를 downstream으로 미룰 뿐이었다.** finalize와 final-permit이 같은 digest와 다시
대조하므로, fresh 설치가 통과해도 프로덕션 API/Dagster 컨테이너가 기동을 거부한다. 이
결함은 내가 만들었고 적대 리뷰가 잡았다.

우회를 걷어내고 **fail-close**로 바꿨다 — head가 baseline root를 넘어서면 fresh 설치가
거부된다. `301`은 계약을 baseline 너머로 확장하는 작업과 **함께** 올라가야 하므로
`chain/301-carrier`에 분리해 보존한다.

부수 확인: `on_version_apply` 봉인이 `0236 → 300` handoff에서도 불렸다. handoff는 stamp
직후 아직 runtime GRANT를 주지 않았고 facet SQL이 그 ACL을 요구하므로 반드시 mismatch였다
— handoff는 GRANT 뒤에 스스로 같은 facet을 대조하므로 중복이자 파손이었다. 봉인을 fresh
설치로 한정했다. handoff fixture도 baseline root에서 멈추게 했다 — head까지 올린 DB는
실제 `0236` source를 재현하지 못한다.

### 게이트: "비교에 쓰였나"에서 "존재하나"로

스캔을 `docker/` 넷 → 여섯 → 82개로 넓혔는데도 적대 리뷰가 **실행으로 열네 가지**를
우회했다. `iterdir()`이 한 단계만 훑고, 확장자 `.py`/`.sh`만 열고, SQL 주석용
`startswith("--")`가 CLI 장옵션 줄을 통째로 건너뛰고, 비교 토큰 목록이 있었다.

결정적인 것은 마지막이다 — **리터럴과 비교를 다른 줄에 두는 것은 우회가 아니라 그냥
평범한 코드다.** `EXPECTED_HEAD="300"` 다음 줄에 `!= "$EXPECTED_HEAD"`를 쓰면 어느 줄에도
"리터럴 + 비교"가 없다. 그러니 "비교에 쓰였나"를 묻는 규칙은 원리적으로 완결될 수 없다.

묻는 것을 바꿨다 — **리터럴이 존재하나.** 존재만 보면 토큰 목록도, 줄 단위 문맥도,
포매터 reflow도 무관해진다. 훑는 대상도 `rglob` + 텍스트로 읽히는 모든 파일로 바꿔
Dockerfile·compose·확장자 없는 실행 스크립트가 전부 들어온다. 정당한 baseline root
언급만 파일 단위로 **사유와 함께** 면제하고, 죽은 면제·불필요한 면제도 실패다.

Manager 쪽도 같은 규칙으로 바꿨다. 거기서는 `--wait-timeout "300"` 때문에 파일 단위 면제를
뒀다가 그 면제가 곧바로 우회 통로가 됐고(상수 둘을 나란히 두면 통과), **초 단위 인자를
정수 상수로** 바꿔 면제 자체를 없앴다 — head는 revision 문자열이라 형이 다르다.

우회 형태를 하나씩 되짚어 확인했다: CLI 장옵션 · 변수 경유 · 하위 디렉터리 · Dockerfile
`ENV` · 멤버십 튜플 · 확장자 없는 스크립트 · compose · Manager 새 모듈 · `services/` 밖 —
전부 걸리고, 파생값만 쓰는 대조군은 통과한다. Manager `.env.example`에 오래 죽은 head
`0084_c6c_cancel_probe_fixtures`가 실제로 박혀 있던 것도 이때 드러나 제거했다.

## 2026-08-30 — provider 핀 전수 동기화와 Protocol 적합성 게이트

형제 `python-*-api` 18개를 핀↔HEAD로 전수 대조했다. 핀 11개를 올리고 **2개는 의도적으로
보류**했다. datagokr는 검증 실패 행을 조용히 건너뛰게 되면서 동시에 종료 조건에서
`reached_known_end` 논리곱을 지웠고, krheritage는 `page * size >= total`을 짧은 페이지
휴리스틱으로 바꿨다. 둘 다 Map이 provider `iter_all()`에 위임하는 경로라 본 저장소의
페이지네이션 보호가 닿지 않는다. 정본 수정은 provider 쪽 total 기반 종료 복구다(ADR-044).
같은 감사를 받은 krforest·visitkorea는 `has_next_page`를 써서 안전함을 확인했다.

`HeritageDetail.manager` 삭제가 mypy·import-linter·단위 테스트를 모두 green으로 통과한 채
live에서만 터진 이유를 구조로 정리했다. 45개 Protocol의 실모델 결박이 docstring 산문에만
있었고, `cast(Any, ...)` 지연 로드라 정적 검사가 보지 못하며, provider extra가 CI에 설치된
적이 없고, 단위 테스트는 자체 fake를 쓴다. 핀된 SHA에서 provider 표면을 뽑아 굳히는
manifest와 기계가 읽는 결박 선언표를 도입해 CI가 provider 설치 없이 실제 표면을 보게 했다.

Dagster 페이지네이션 6곳의 `len(items) < num_of_rows` 종료 조건을 공용 헬퍼로 옮겼다.
`total_count`가 권위이고 짧은 페이지는 그것이 없을 때만 쓰는 대체 휴리스틱이며, "짧은
페이지인데 아직 다 못 받았다"는 계속 + 경고다. krex/airkorea처럼 끝을 **예외로** 알리는
provider를 위해 `end_of_pages` 훅을 뒀다.

kma `to_grid`가 격자 범위 밖에서 `ValueError`를 던지게 됐다. 한국 영토 극단점 9개를 실제
투영해 전부 격자 안임을 확인했으므로, 격자 밖 좌표는 국외 지점이 아니라 좌표 데이터
오류다. 건너뛰지 않고 typed `KmaWeatherGridCoordinateInvalid`로 실패시킨다.

적대 리뷰 2명이 내가 만든 회귀 둘(khoa 절단, krex 종료 예외)과 내 게이트의 구멍 둘
(mcst 미검사, 상속 Protocol 멤버 미검사)을 찾았다. 전부 실증 후 반영했다.

n150 CI-parity 게이트에서 하위 패키지 테스트가 체크아웃이 아니라 venv 편집형 설치가
가리키는 `/tmp/ktm-lint`(다른 커밋)를 import해 온 것을 실측으로 확인했다. `-c pyproject.toml`로
루트 config를 강제해 고쳤다 — 그 전 판정은 테스트 대상이 아닌 트리에 대한 것이었다.

## 2026-08-29 — Manager-aware M05 execution identity 계약 착수

Map/PinVi v5 source pinset이 Manager revision을 digest에 넣지 않아, Manager의 terminal 보정을 배포해도 같은 source
pair가 이미 terminal pinset으로 막히는 구조를 확인했다. source revision이나 문서 merge로 이를 우회하면 CI·리뷰·one-shot을
불필요하게 소비하고 historical evidence의 의미도 흔들린다.

후속은 Docker Manager `ktdctl`의 v6 execution identity로 분리한다. canonical execution input은 v5 source pinset,
canonical Manager repository URL, trusted installer Manager revision이며, Manager revision은 user-controlled CLI/환경값을
받지 않는다. Map attestation은 새 execution identity를 exact 대조하고, v5 terminal evidence는 legacy audit으로 보존한다.
문서-only merge는 즉시 병합하지만 runtime tuple/pinset을 바꾸지 않는다. raw E2E forensic은 gitignored local 파일에서만 보관한다.

## 2026-08-29 — M05 Map health transport 반복 terminal의 범위 확정

`9b6eab1e…`는 Map `86d38d46…`·PinVi `3b9d6026…`·Manager `1dbd7cc…`를 Docker Manager trusted
`ktdctl`로 pair 결박하고 rebuild/public generation `match` 뒤 M04/M05 E2E를 정확히 한 번 실행한 결과다.
root registry의 terminal phase는 `map_health_transport_failed`, cleanup은 성공이었다. 같은 phase가
`41be91fe…`·`5512ce12…`·`b46743ea…`에서 반복됐으며 모두 PinVi runtime과 M04/M05 business flow 전에
종료했다. 따라서 이 네 후보는 PinVi consumer/provenance 오류가 아니라 Map API container health 이후 host
loopback publish transport 경계의 반복 failure로 분류한다.

Manager `bc99ce1…`은 이 경계의 일시 경합만 동일 candidate 안에서 1초 간격 최대 6회 흡수한다. HTTP status와
응답 계약 오류는 즉시 terminal로 유지한다. Map은 runtime source의 문서 전용 업데이트를 즉시 병합하되, CI와
전문 적대 리뷰를 다시 소비해야 하는 새 candidate는 Manager/PinVi의 실제 입력 변경 뒤에만 만든다.

## 2026-08-29 — M05 반복 후보 억제와 Docker Manager 단일 mutation 경계

사소한 문서 정정이 Map/PinVi provenance와 pinset을 재결박해 CI·전문 리뷰·one-shot을 반복 소비하지 않도록,
runtime source tuple을 candidate 형성 시 동결하는 규율을 정했다. 이후 문서 전용 PR은 즉시 병합해 동결된
candidate를 참조만 하며, 코드·Compose·계약·빌드 입력을 바꿀 때만 새 candidate를 만든다.

pinning·pair 결박·public-copy·rollback·rebuild/E2E는 Docker Manager `ktdctl` 단일 경계에서 수행한다. Manager
`03a3300…`은 모든 runtime pin mutation을 active global mutation과 직렬화하고, 검증된 launcher inherited-lock
terminal fallback 외 외부 write를 거절한다. n150 또는 terminal candidate의 원문 artifact는 건드리지 않았다.

## 2026-08-29 — M05 `3d8d63e1…` 제어면 terminal 보존

Map `0cb126fc5537f29fd3385a89faadde909649c30c`·PinVi
`9372137edf28ecaf1db2adfa9d956fe99d371e8a`·Manager
`712ae8c9acccf02c4e0015116d3c6e070ba7ca71`·pinset
`3d8d63e18dc61c34dc19b465d0b969799ba5d14f0701a19d7dd865232db6fb5b`은 clean trusted release,
root 원자 `ktdctl pin rotate-pair`, 공개 registry·generation `pending_rebuild` gate 뒤 새 root-owned
pinned rebuild를 정확히 한 번 시작했다. 원격 호출의 즉시 종료 상태로 완료를 판정하지 않고, raw leaf를
열지 않은 채 root-global mutation lock 해제 후 공개 `pin verify`를 확인했을 때 generation은 `match`였다.

다만 lock 보유 중 이미 exact pair의 unconditional terminal block이 root registry에 기록돼 이 후보는
M04/M05 launcher를 실행하지 않는다. 이는 runtime 계약의 terminal phase가 아니라 제어면 완료 판정의
실패이며, 해당 pinset·source pair·Manager source·rebuild leaf를 재실행하지 않는다. 후속 후보는 반드시
lock 해제와 공개 exact-pair/generation gate를 먼저 확인한다. 외부 root `pin block`은 active global mutation에서
코드로 거절하며 trusted launcher의 inherited-lock fallback만 예외다. HTTP·container·환경·output leaf·private
receipt 원문은 열거나 보관하지 않았다.

## 2026-08-29 — M05 `7035b0b1…` terminal 보존과 admission 경계

Map `3916ebfd601d97166c55dadfec938c3eeed6bc45`·PinVi
`73870e52fe6e02d02096a2a2dc82346f09be9a3c`·Manager
`291bd161a36e580003ef99dedafd77ee5d400a7e`·pinset
`7035b0b1c62f22fa2f1b93858a0b97de60082d4698966693705f365bd66eb639`는 모든 CI와 exact-head 전문
적대 재리뷰 두 건의 GO 뒤 clean trusted Manager release, 원자 `ktdctl pin rotate-pair`, 단발 pinned
rebuild, 공개 generation `match` gate를 통과했다. 새 root-owned leaf의 n150 isolated M04/M05 launcher는
정확히 한 번 실행됐고, root registry의 exact unconditional terminal entry가 공개한 raw-free fixed phase는
`runtime_setup_admission`이다.

HTTP·container·환경·output leaf·private receipt 원문은 열거나 보관하지 않았으며, 이 pinset·source pair·
Manager source·두 one-shot leaf는 재실행하지 않는다. 이 결과는 runtime setup 전체가 아니라 Manager가 private
admission을 만들고 PinVi가 no-follow로 검증하는 경계로 다음 immutable source 보정 범위를 좁힌다. 이 문서의
merge revision을 PinVi admin·full provenance에 재결박하고, admission 경계를 raw detail 없이 검증·분류하는 새
Manager source의 CI와 exact-head 전문 적대 재리뷰 두 건이 GO일 때만 다음 pair를 만든다.

## 2026-08-28 — M05 `82850711…` terminal 보존과 runtime setup 진단

Map `35a433173dbd42c096ef08adceb1ae3c142444b4`·PinVi
`fed16a5c0f6e78ee32306b3733a7dc1c8a5641f9`·Manager
`eed1920186b5cb61182a955a6281e49230b80a84`·pinset
`8285071126a58e4807a035753261b0d1f0f4e713fa5934e9d1efa7cbf16f3af9`는 필수 CI와 exact-head
전문 적대 재리뷰 두 건의 GO 뒤 trusted `ktdctl pin rotate-pair`로 결박했다. 새 source의 단발
`run-pinned-rebuild-once`와 registry/public generation `match` gate를 통과한 뒤, 새 root-owned
leaf의 n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. exact unconditional terminal entry의
공개 고정 phase는 `runtime_setup`이다.

따라서 pair rotation·source materialization·Map/PinVi HTTP 계약 이전의 isolated runtime 준비 경계가
후속 Docker Manager 보정 범위다. HTTP·container·환경·output leaf·private receipt 원문은 열거나
보관하지 않았고, 이 pinset·source pair·Manager source·output leaf는 재실행하지 않는다. 후속 Manager는
setup 내부의 안전한 세부 경계만 공개 phase로 분리하고 raw exception은 기록하지 않는다. 이 문서의 merge
revision을 PinVi `admin`·`full` provenance에 다시 결박한 새 pair만 다음 one-shot 후보가 될 수 있다.

## 2026-08-28 — M05 `5592a1d4…` terminal 보존과 phase 수렴 보정

Map `757623973c2e6c082b78332fa25c278ef94f9bab`·PinVi
`358f607a039ffab2dabaadc2eddfc19a7e126f5c`·Manager
`a4d60d16650926c0ac5e5b9a3703c14797259ab4`·pinset
`5592a1d4d98d6757b6a5390a7283b64dc1302abb93ab2dc3b58ef1aed84066c0`는 모든 CI와
전문 적대 재리뷰 두 건의 GO 뒤 trusted `ktdctl pin rotate-pair`로 결박했다. 새 source의
`run-pinned-rebuild-once`와 registry/public generation `match` gate를 통과한 뒤, 새 root-owned
leaf의 n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 terminal이었고 root
registry의 exact unconditional entry는 원문 없이 고정 phase `driver_contract_failed`만 공개한다.

HTTP·container·환경·output leaf 원문은 열지 않았으며, 이 pinset·source pair·Manager source·output
leaf는 재실행하지 않는다. 후속 Manager는 unexpected ordinary exception을 무조건 generic phase로
덮어쓰지 않고, 이미 추적 중인 allowlist phase로만 수렴시켜 raw detail 없이 다음 immutable candidate의
수정 범위를 좁힌다. 이 문서의 merge revision은 PinVi `admin`·`full` provenance에 다시 결박한다.

## 2026-08-28 — M05 `5ad3b08c…` terminal 보존과 안전 phase 진단

Map `053904cebdb004ef1376c0c4cf0255efb02e5ba3`·PinVi
`1b29bfea86af92ad8fd946b967fe6cce331c797f`·Manager
`8f41a9bd797440bc867462da70be0d2dddf085f7`·pinset
`5ad3b08c762db115efe113f2254bea415e674d09677c47e28ba6c197b37bafe0`는 trusted `ktdctl
pin rotate-pair`, `run-pinned-rebuild-once`, registry/public generation `match` gate 뒤 n150 isolated
M04/M05 launcher를 정확히 한 번 실행해 root registry의 exact unconditional terminal entry로 차단됐다.
HTTP·container·환경·output leaf 원문은 열지 않았고 해당 source pair·Manager source·output leaf는 재실행하지
않는다.

후속 Manager `a4d60d1…`은 terminal registry의 공개 reason에 raw detail을 쓰지 않고 allowlist fixed phase만
남긴다. 이 Map 기록 revision을 새 PinVi `admin`·`full` provenance와 함께 다시 결박하고, Manager·PinVi CI와
exact-head 전문 적대 리뷰 두 건이 GO인 fresh pair만 다음 one-shot 실행권을 가진다.

## 2026-08-28 — M05 Manager isolated admission 계약 명시

PinVi의 isolated Compose 경로는 trusted Docker Manager `ktdctl`가 transaction·pinset·Manager/Map/PinVi
revision에 exact 결박해 private `0600`으로 발급한 admission receipt를 no-follow 검증할 때만
열리도록 정렬했다. 호출자 환경변수 marker, 수동 Compose, 임의 receipt는 실행 권한이 아니며
legacy marker는 거절한다. receipt 발급·주입은 Manager #256, verifier와 실행 gate는 PinVi #500의
paired 변경이고, 본 문서는 Map 소비자 계약을 같은 규율로 갱신한다. 이 문서 변경은 새 pinset이나
n150 one-shot을 만들지 않는다.

## 2026-08-28 — M05 Docker Manager 공개 generation 계약 정렬

M05의 runtime pinning·Map/PinVi pair 결박·one-shot 실행 정본을 trusted Docker Manager
`ktdctl`로 통일했다. 새 후보는 `pin rotate-pair`의 원자 회전만 사용하며, 인증된
`/api/v1/runtime-pins`와 `/api/v1/pinned-runtime/generation` 공개 사본에서 완전한 이전
committed generation 또는 registry가 Map·PinVi revision과 pinset까지 exact로 차단한 terminal
generation의 `pending_rebuild` 또는 `match`를 확인한다. 새 launcher 뒤에는
`pinset_binding=match`를 다시 요구한다. partial·malformed·phase-scoped block·drift·unknown
generation은 gate를 열지 않는다. private manifest/journal, raw launcher output, 기존 terminal
artifact는 Map이 읽지 않는다.

Map C7 attestation의 manifest v6/journal v8 exact schema·키·version은 Docker Manager 공개
generation 계약과 paired PR로만 바꾼다. 이번 동시 정렬은 journal의 3개 PinVi role extension을
포함한 16-key exact dict와 committed 상태의 catalog reset·lifecycle block 의미까지 검증한다. 이
문서 정렬 자체는 새 n150 candidate나 one-shot을 만들지 않으며, 이전 terminal pinset을 재실행하지 않는다.

## 2026-08-28 — M05 `b46743ea…` terminal 보존 후 대기

Map `6bfa47038b439845662f89524531d2ef72374c2a`·PinVi
`340717de33b3672f7da84795626c4302eddd1176`·Manager
`00c33ad79f8e43b01fe543699428701aa9733c67`·pinset
`b46743ea72d86329d9574c21cc445fb9b33fdeaad07a2704a68a91fd7a0a89fe`는 PinVi·Manager CI와 exact-head 전문 적대
리뷰 두 건의 GO, clean trusted release, atomic pair rotation과 registry/public-copy gate 뒤 n150 isolated
M04/M05 launcher를 정확히 한 번 실행했다. 권위 있는 고정 결과는
`launcher_safe_result_unavailable`이었다. HTTP 원문·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 gate는 exact unconditional terminal entry와 public copy를 확인했다. 이 candidate·source pair·Manager
source·output leaf는 절대 재실행하지 않는다. 사용자 지시에 따라 새 source·pair·pinset 생성이나 후속 n150 실행은
여기서 멈추고, 현재 terminal 기록을 보존한 채 대기한다.

## 2026-08-28 — M05 finalization receipt P1 보정

전문 data-contract 적대 재리뷰는 이전 Manager `862e8bf…`가 main `try`의 unexpected ordinary exception만
`driver_contract_failed` receipt로 수렴하고 cleanup·terminal block의 ordinary exception은 result 없이 전파할 수
있다는 P1을 확인했다. 이 문제는 terminal `41be91fe…`의 raw artifact를 열거나 재실행하지 않고 정적 경계 검토로만
발견했다.

Manager `00c33ad…`는 main·cleanup·terminal block의 ordinary exception을 `BaseException`과 구분해 원문 없이
동일 fixed terminal receipt로 수렴시킨다. cleanup 및 terminal block 오류 주입 회귀도 추가했다. 다음 후보는 이
terminal 기록을 포함한 새 Map revision과 새 PinVi provenance, 이 Manager source를 fresh atomic pinset으로 결박하고
CI·정확한 head 전문 적대 리뷰 두 건을 통과한 경우에만 만든다.

## 2026-08-28 — M05 `41be91fe…` safe launcher terminal 보존

Map `fa55316d858d95367b6a1ca6f17094408b543afe`·PinVi
`f9fce72fbc6ef73f3ec1700ef76995fdfc068e88`·Manager
`cd8b3054d9f49af88ef6f58e9319343c1453df27`·pinset
`41be91feb62feff039452e23a0d889c3b32c3e97e08c28e86ad0a1068ec8ad67`는 최신 CI와 exact-head 전문
적대 리뷰 두 건의 GO, trusted clean Manager release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 exit 1이었고 권위 있는 고정 결과는
`launcher_safe_result_unavailable`이었다. HTTP 원문·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 gate는 exact Map·PinVi·pinset의 unconditional terminal entry와 public copy를 확인했다. 이 candidate와
source pair·Manager source·output leaf는 절대 재실행하지 않는다. 다음 후보는 이 terminal 기록을 포함한 새 Map
revision, PinVi `admin`·`full` paired provenance revision, 예상하지 못한 ordinary driver exception도 원문 없이
`driver_contract_failed` fixed receipt로 남기는 Manager `00c33ad…` source를 새 atomic pinset으로 결박하고 최신
CI와 전문 적대 리뷰 두 건을 다시 통과한 경우에만 만들 수 있다.

## 2026-08-28 — M05 `5512ce12…` safe launcher terminal 보존

Map `73150672d26866122e231c085e9beefe81bfd776`·PinVi
`d8dc386dec7a800b83d457e1753b63f51470afc6`·Manager
`c31c8448fcade3ace84b0dbd0682328283ae20b9`·pinset
`5512ce12ca316e10404b9faf60eba8130815a4c7cdb3b91f4d8c80de1805cc8d`는 최신 CI와 exact-head 전문
적대 리뷰 두 건의 GO, trusted clean Manager release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 exit 1이었고 권위 있는 고정 결과는
`launcher_safe_result_unavailable`이었다. HTTP 원문·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 gate는 exact Map·PinVi·pinset의 unconditional terminal entry와 public copy를 확인했다. 따라서 이
candidate의 source pair·Manager source·output leaf는 절대 재실행하지 않는다. 다음 후보는 이 terminal 기록을
포함한 새 Map revision, 새 PinVi paired provenance, 새 Manager source를 새 atomic pinset으로 결박하고 최신 CI와
전문 적대 리뷰 두 건을 다시 통과한 경우에만 만들 수 있다.

## 2026-08-28 — M05 safe-result 부재 terminal 보존

Map `f90b7c28ee0a51cc5e2dce7a332e7feef9afe477`·PinVi
`fdff06ba746bf2de198fab075a356f88b9f228c9`·pinset
`fa28a6e7d7ee27b7bb6be6cd6c0a04ffc458cda329beca339a4ce6d038480381`은 최신 CI와 전문 적대
리뷰 두 건의 GO, trusted Manager `b45f54d5…` release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 exit 1이었고 허용된 durable safe result는
없었다. 원문 HTTP·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 `pin verify`는 exact pinset이 terminal로 차단됐음을 확인했다. 따라서 `fa28a6e7…`과
`a3f6a8f3…`·`22563762…`·`c700bd2e…`의 source pair·Manager revision·output leaf는 절대 재실행하지 않는다.
다음 후보는 이 terminal 기록을 포함한 새 Map revision과 새 PinVi provenance·새 Manager source를 새 atomic
pinset으로 결박하고, safe result 부재도 원문 없이 고정 분류·보존할 수 있을 때만 만들 수 있다.

## 2026-08-28 — M05 Map health terminal 보존

Map `bbb29d17751aa0ece0b76f3c8724a0073aa9dafc`·PinVi `663e21b4fdc2a4fc5e51a07f7a7532282aaa5423`·
pinset `c700bd2ec2d2c181e60c1dd99a13022ff8a2ce30bb19de3bb871806be80ee1ef`은 최신 CI와 전문 적대
리뷰 두 건의 GO, trusted Manager `4a6e1b0…` release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. durable safe result는 `map_health_http_failed`이고
cleanup은 통과했다. HTTP 원문·컨테이너 로그·환경값은 읽거나 보관하지 않았다.

driver는 이 pinset을 root registry에 조건 없이 terminal 차단했고 이후 `pin verify`가 재실행 불가를 확인했다.
`a3f6a8f3…`·`22563762…`·`c700bd2e…`의 source pair·Manager revision·output leaf는 절대 재실행하지 않는다.
다음 후보는 이 terminal 기록을 포함한 새 Map revision과 새 PinVi provenance·새 Manager source를 새 atomic
pinset으로 결박한 경우에만 만들 수 있다.

## 2026-08-28 — M05 HTTP terminal 보존과 단계 고정 분류 보정

Map `b8d108bd…`·PinVi `50c875f5…`·pinset `22563762…`은 root registry/public-copy gate를 통과한 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. durable result의 고정 분류는
`runtime_http_failed`였고 cleanup은 통과했다. raw HTTP 응답·컨테이너 로그·환경 출력은 읽지 않으며,
동일 pinset·Manager source·output leaf는 어떤 사유로도 재실행하지 않는다. root registry는 이
candidate를 같은 고정 분류로 즉시 terminal 차단했다.

Manager #253은 다음 fresh candidate에서 HTTP 실패를 호출 단계별 허용 enum으로만 기록하도록 보정한다.
새 Map 기록 revision과 PinVi `admin`·`full` paired provenance revision을 atomic `pin rotate-pair`로 함께
회전하고, CI·전문 적대 재리뷰 두 건·registry/public-copy gate가 모두 정합할 때만 새 root-owned
output leaf에서 M04/M05 live E2E를 정확히 한 번 실행한다.

## 2026-08-28 — M05 installed-wheel preflight terminal 보존과 새 pair 조건

Map `e6c08e25…`·PinVi `932fb140…`·pinset `a3f6a8f3…`의 isolated launcher는 trusted release 검증 뒤,
installed wheel의 project-root 계산이 runtime registry보다 먼저 실패해 종료했다. Docker·Compose·DB·driver
ledger 전이었지만 단회 실행권은 이미 사용됐으므로, Manager root registry는 이를 `launcher_preflight` terminal
evidence로 차단했다. 같은 pinset·Manager source·output leaf는 어떤 사유로도 재실행하지 않는다.

Manager #253은 trusted venv의 `python -I`가 `sys.prefix`로 canonical `/opt` root를 인식해 external registry와
public copy를 선택하도록 보정했고 전문 적대 재리뷰 두 건의 GO를 받았다. 다음 candidate는 이 Map 기록 revision과
PinVi 후속 provenance revision을 atomic pair rotation으로 새 pinset에 결박한 뒤, CI와 registry/public-copy gate를
다시 통과해야만 n150 M04/M05 isolated E2E를 정확히 한 번 실행할 수 있다.

## 2026-08-28 — M05 atomic pair rotation과 ledger 선행 gate 반영

Manager 전문 보안 재리뷰는 terminal seed에서 Map·PinVi를 role별로 회전하면 intermediate pinset이
one-shot ledger를 소비할 수 있음을 P1으로 확인했다. Manager PR #253 source `02cc8de…`는 terminal current의
single-role 회전을 거부하고 `pin rotate-pair`의 단일 registry replace로 두 source를 함께 회전한다.
M05 launcher도 source pair preflight 뒤에만 ledger를 claim한다.

따라서 Map `e6c08e25…`·PinVi `932fb140…`의 final `a3f6a8f3…`만 새 candidate가 된다. invalid pair,
intermediate state, static image digest 추측, 과거 terminal candidate 재실행은 여전히 허용하지 않는다.

## 2026-08-28 — M05 Docker Manager runtime pin registry 반영

Docker Manager #251은 Map·PinVi revision과 terminal pinset lifecycle의 정본을 source 상수에서
trusted release 밖 root-owned runtime pin registry로 옮겼다. Map `e6c08e25…`와 PinVi
`932fb140…`은 추적되는 seed를 편집하지 않고 host에서 `pin init` 뒤 atomic `pin rotate-pair`로
`a3f6a8f3…` candidate를 만든다. `cbb577d3…` seed는 terminal historical evidence로 보존한다.

새 candidate는 `pin verify`의 registry·공개 사본 gate, root-owned Manager provenance, PinVi pair의
source/OpenAPI/image identity가 모두 맞을 때만 한 번 실행한다. intermediate state, static image digest
추측, 과거 terminal candidate 재실행은 허용하지 않는다.

## 2026-08-28 — M05 PostGIS baseline digest source 병합

Map PR #1099는 `e6c08e2598a6f8b6fda605be271e8d384213de58`로 병합됐다. Compose `postgres`는
application `300` baseline reference의 immutable PostGIS digest를 직접 사용하고, unit gate는 reference의
repository·image ID와 Compose 값을 exact 비교한다. 전문 적대 리뷰 두 건은 P0/P1 없이 GO했고 lint,
OpenAPI, fixture replay, Python 3.11/3.12/3.13 및 PostGIS 통합 CI가 모두 통과했다.

기존 `29fbcdd…` terminal candidate는 그대로 보존하고 재실행하지 않는다. 다음 단계는 이 병합 revision의
 paired application candidate를 PinVi `admin`·`full` provenance에 결박한 뒤 Manager runtime pin registry를
 회전하는 것이다.
그 새 candidate만 n150 isolated M04/M05 live E2E를 정확히 한 번 실행할 수 있다.

## 2026-08-28 — M05 fresh baseline PostGIS image drift 원인 확정

`29fbcdd…` isolated candidate는 `baseline_reference_invalid`로 terminal 처리됐고 재실행하지 않는다.
원문 Docker log·stderr·환경값은 읽지 않았다. exact Map `9c64e862…`의
`application-reference.json`, manifest sidecar, 그리고 tracked baseline artifact를 정적으로 재검증한
결과, 이전에 기록한 `application-seed.sql` 불일치는 없었으며 모든 declared digest가 실제 bytes와
일치했다. 따라서 그 주장은 철회한다.

n150의 읽기 전용 image identity 확인에서는 Map Compose의 부동 `postgis/postgis:16-3.5-alpine`
태그가 baseline reference가 결박한 immutable PostGIS image와 달랐다. 이 baseline은 catalog receipt를
exact image identity에 결박하므로, 새 fresh DB가 다른 image에서 생성되면 receipt mismatch로
fail-close하는 것이 정상이다. Map Compose를 baseline reference digest에 직접 고정하고, committed
Map revision을 PinVi pair·Manager pinset에 재결박한 새 candidate만 실행한다.

## 2026-08-28 — `c1ad5a3e…` root-owned one-shot committed

PinVi `41a36ee6…`·Map `9c64e862…`의 `c1ad5a3e…` candidate는 exact Manager trusted release에서
root-owned structured launcher로 정확히 한 번 실행돼 `committed` 됐다. durable result는 generation
`8eedf171…`, Map application `300`, Map Dagster `29b539ebc72a`, PinVi `20260824_0101`을 확인한다.
이제 이 immutable pair에서만 isolated M04 승인·Map `rebind`·PinVi terminal receipt/ACK과 signed M05
activation attestation을 실행한다.

## 2026-08-28 — M05 provenance 재결박과 새 one-shot candidate

`030b12fc…`은 Map `9c64e862…` 및 committed API/UI image identity를 사용한 generation으로 보존하며 재실행하지
않는다. `6269138f…`은 durable journal/manifest를 남기지 못한 pre-journal 단회 시도로 보존하며 raw stderr를 읽거나
재실행하지 않는다. `53d4639f…`은 installed launcher execute bit 미보존으로 admission 이전에 끝났고 durable output·ledger·raw stderr가 없어 재시도하지 않는다. PinVi `41a36ee6…`은 M05 attestation pair와 이 실행 경계를 기록하고, Manager `c1ad5a3e…`는
그 exact PinVi/Map source와 canonical hash를 고정한다. 다음 official rebuild는 installer가 executable로 보존한 root-owned structured result launcher로
이 새 pinset에서 단 한 번이며, 성공한 committed generation만
isolated M04/M05 live mutating E2E와 signed activation attestation에 사용한다.

## 2026-08-28 — M05 scoped cleanup generation committed

Manager `519edd9…`, PinVi `69a5ac65…`, Map `9c64e862…`의 `030b12fc…` pinset은 trusted n150 release에서
official `rebuild-pinned --confirm --json`을 정확히 한 번 실행해 committed 됐다. seven-runtime generation과 Map
application `300`·Map Dagster·PinVi `20260824_0101` schema head를 고정 필드만으로 확인했다. historical candidate와
원문 stderr·DB catalog 값은 읽거나 재사용하지 않았다. 다음 단계는 같은 immutable pair의 isolated M04/M05 live
mutating E2E와 activation attestation이며, 성공 전 두 코드 PR은 병합하지 않는다.

## 2026-08-28 — M05 v2 permit scoped external membership cleanup

사용자의 완주 지시에 따라 target 밖 stale membership 철회는 Manager root-owned v2 permit의 exact
`revoke_external_memberships` scope로만 허용한다. permit은 transaction·pinset·PinVi DB identity에 결박되고, PinVi는
legacy permit 또는 다른 scope를 reset 전에 거부한다. PostGIS 회귀는 target→external·external→target 두 방향 모두에서
target membership만 제거되고 external role은 보존됨을 확인한다. Manager `519edd9…`, PinVi `69a5ac65…`, Map
`9c64e862…`의 `030b12fc…`만 다음 n150 official candidate다.

## 과거 기록 아카이브

> 현행 작업 창(2026-08-28~) 이전 기록은 아래로 분리했다. 검색은
> `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
| [`journal-2026-08a.md`](archive/journal-2026-08a.md) | 2026-08-14 ~ 2026-08-27 | 124건 | 200 KB |
| [`journal-2026-08b.md`](archive/journal-2026-08b.md) | 2026-08-01 ~ 2026-08-14 | 89건 | 166 KB |
| [`journal-2026-07c.md`](archive/journal-2026-07c.md) | 2026-07-26 ~ 2026-07-31 | 60건 | 167 KB |
| [`journal-2026-07a.md`](archive/journal-2026-07a.md) | 2026-07-13 ~ 2026-07-24 | 115건  | 219 KB |
| [`journal-2026-07b.md`](archive/journal-2026-07b.md) | 2026-07-01 ~ 2026-07-12 | 28건   | 45 KB  |
| [`journal-2026-06a.md`](archive/journal-2026-06a.md) | 2026-06-10 ~ 2026-06-30 | 172건  | 219 KB |
| [`journal-2026-06b.md`](archive/journal-2026-06b.md) | 2026-06-02 ~ 2026-06-10 | 179건  | 220 KB |
| [`journal-2026-06c.md`](archive/journal-2026-06c.md) | 2026-06-01 ~ 2026-06-02 | 36건   | 53 KB  |
| [`journal-2026-05a.md`](archive/journal-2026-05a.md) | 2026-05-24 ~ 2026-05-31 | 90건   | 218 KB |
| [`journal-2026-05b.md`](archive/journal-2026-05b.md) | 2026-05-24 ~ 2026-05-24 | 3건    | 7 KB   |
