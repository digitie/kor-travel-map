# journal 아카이브 — 2026-09-01 ~ 2026-09-10

> live `docs/journal.md`에서 분리한 과거 기록(docs/tasks-rule.md §8). 읽기 전용 이력이다.

## 2026-09-10 — 묶음으로 쪼개 돌면 보이지 않는 부류

T-VN-39의 통합 스위트를 아홉 묶음으로 쪼개 돌렸다. 이유는 좋았다 — pytest-timeout이
없어서 advisory lock 데드락 하나가 런 전체를 무한정 붙들고, 파일마다 `timeout`을
걸면 그 파일만 잃고 나머지는 계속 간다. 실제로 그 방식이 19분짜리 정지 두 번을
막았다.

그런데 그 쪼갬이 **세션 공유 DB에 쌓이는 상태**를 통째로 가렸다. 아홉 묶음이 전부
초록이었고, PR을 열자 CI의 한 세션 전량 런이 곧바로 네 건을 빨갛게 만들었다:

    count_features_missing_identity == (0, 21, 0, 0)

둘째 축은 "주소 없는 provider claim"을 센다. 21건이 어디서 왔는지 단언은 말하지
않았다 — 숫자 하나만 들고 있었다. 이 저장소가 sha256 카탈로그 대조에서 이미 겪은
부류다: "맞지 않는다"만 말하고 어느 줄인지는 말하지 않는 실패.

그래서 **먼저 진단을 붙였다.** 주소 없는 claim을 최대 열둘까지 실패 메시지에 싣게
하고 다시 돌렸다. 답이 한 번에 나왔다 — 전부 `DAGSTER-OPINET-001` ·
`DAGSTER-KNPS-POINT-001` 같은 dagster asset 테스트의 claim이었다.

### 원인은 FK가 없다는 사실 하나였다

`provider_sync.provider_feature_identities`에는 `feature.features`로 가는 FK가 없다
(dataset FK 하나뿐). 그래서 정리 도우미가 도는

    TRUNCATE feature.features, ... RESTART IDENTITY CASCADE

가 claim을 **데려가지 않는다.** commit하는 테스트가 지나간 자리마다 부모 없는 claim이
쌓이고, 그 상태를 identity 불변식이 "주소 없는 claim"으로 세므로 **다른 파일이 대신
죽는다.** `test_notice_lifecycle.py`는 이 함정을 이미 한 번 밟고 자기 자리에서 명시
DELETE를 넣어 뒀는데, 그 교훈이 열여섯 개의 정리 목록에 퍼지지 않았다.

호출부 목록마다 이름을 더 적게 하는 길은 택하지 않았다 — 잊는 것이 기본값이 되기
때문이고, 이미 열여섯 파일이 각자 목록을 들고 있다. 대신 도우미가 호출부 TRUNCATE
**뒤에** 부모 없는 claim만 거둔다. feature가 살아 있는 claim은 건드리지 않으므로
어떤 테스트의 의미 있는 상태도 잃지 않고, "feature는 있는데 주소가 없다"는 진짜
결함은 불변식이 계속 잡는다.

### 남는 규칙

**쪼개서 빠르게 도는 하네스는 그 자체가 프록시다.** 이 브랜치가 오래 걸린 이유가
"범위를 프록시에서 유도했다"였는데, 마지막에 같은 실수를 측정 방식에서 한 번 더
했다. CI가 실제로 도는 방식(한 세션 전량)과 다르게 재면, 다른 것을 재는 것이다.
쪼갠 하네스로 초록을 얻었으면 머지 전에 **한 번은 CI와 같은 방식으로** 돌려야 한다.

**그리고 숫자만 돌려주는 단언은 절반만 일한다.** 0이 아닐 때 "누구인지" 말하지
않으면, 실패는 원인을 가리키지 않는 채로 남고 사람이 다시 찾아야 한다. 관측을
숫자로 줄이는 것은 비교를 쉽게 하려는 것이지 증거를 버리려는 것이 아니다.

## 2026-09-10 — 보안 권고 셋이 머지를 막았고, 핀은 네 자리에 있었다

T-VN-39의 파이썬 게이트가 전부 초록인 채로 프론트 게이트만 빨갰다. 원인은 이 PR과
무관했다 — `maplibre-gl`(critical, XSS sanitizer 우회) · `next`(critical, RCE 둘) ·
`sharp`(high) 권고가 새로 공개됐고, lock은 바뀐 것이 없으니 main도 같은 얼굴이었다.

별도 PR로 먼저 닫았다(#1198). `maplibre-gl`은 5.x 전체가 영향 범위라 백포트가 없어
메이저를 올려야 했는데, **마이그레이션은 한 줄이었다** — v6가 default export를
없앤 것이 전부고, `vworld-map-view.tsx`를 namespace import로 바꾸니 타입 오류
열하나 중 열이 따라 사라졌다. 이름이 풀리지 않아 `source`가 `any`가 되고, 그래서
`.then` 콜백이 문맥 타입을 잃었던 것이다.

### 같은 숫자가 네 자리에 박혀 있었다

버전을 올리자 **관계없는 얼굴로** 두 번 죽었다.

    AssertionError: 검증되지 않은 Next 버전입니다.  (scripts/verify-next-sharp.mjs)
    AssertionError: {'@next/env': '16.3.4'} == {'@next/env': '16.2.12'}
                                              (tests/unit/test_frontend_dependency_security.py)

선언 둘(루트 `overrides`, 프론트 `dependencies`)에 더해 검사 스크립트와 유닛 테스트가
같은 숫자를 각자 들고 있었다. 권고 하나에 고칠 자리가 넷이고, 하나를 잊으면 보안과
무관한 메시지로 죽는다.

두 자리 모두 **명제를 다시 물어서** 풀었다. 검사가 지켜야 할 것은 "버전이 특정
숫자인가"가 아니라 셋이다 — 정확한 핀인가(범위 금지) · 선언들이 서로 같은가 ·
lock이 그것과 같은가. 셋 다 버전이 움직여도 그대로 성립한다. ABI 스모크(실제 이미지
최적화 1회)는 그대로 남겼다. 그것이 진짜로 재는 것이다.

### 지도 라이브러리 메이저는 실행해서 확인했다

타입 검사와 빌드는 "컴파일된다"까지만 말한다. mocked Playwright 스위트(spec 30개)를
**두 버전에 같은 조건으로** 돌리고 실패 집합을 뺐다.

| | maplibre | Next | 결과 |
|---|---|---|---|
| 기준선 | 5.24.0 | 16.2.12 | 276 passed / 8 failed |
| bump | 6.9.0 | 16.3.4 | 276 passed / 8 failed |

`comm`으로 뺀 결과가 양쪽 모두 빈 집합이었다 — **같은 8건이 양쪽에서 같은 이유로
빨갛다**(넷은 nav 링크 수·metric 밀도라 지도와 무관하고, 나머지는 임시 하네스가
라이브 geo/weather 없이 도는 데서 온다). 기준선 없이 8건만 봤다면 bump 탓으로 읽고
없는 회귀를 쫓았을 것이다.

첫 판은 172건이 통째로 빨갰는데 `E2E_ADMIN_PASSWORD`를 주지 않아 로그인이 실패한
것이었다. **하네스 결함과 회귀는 실패 개수로 구분되지 않는다** — 하나를 고치면
전부 초록이 되는 종류인지부터 물어야 한다.

## 2026-09-10 — 초록인 검사와 결함 없는 코드는 다른 사실이다

T-VN-39가 live e2e까지 초록이 된 뒤, 머지 전에 적대 리뷰를 돌렸다(6축 × 2명,
opus5/xhigh). blocker 2건과 major 8건이 나왔다. blocker와 축(axis) major는 예상한
부류였는데 — 값이 새거나, 값이 못 들어가거나, 표기가 어긋나거나 — **탐지기 major
넷은 그렇지 않았다.** 넷 다 이 브랜치가 만든 검사이고, 넷 다 초록이었고, 넷 다
아무것도 못 보고 있었다.

가장 아픈 것이 FK 액션 검사다. 재키는 타입 불일치 때문에 FK 40개를 떨어뜨리고 34개를
되살린다. `ON DELETE CASCADE` 하나를 빠뜨리면 DDL은 조용히 성공하고, 실패는 한참
뒤에 엉뚱한 얼굴로 온다(`fk_feature_aliases_feature`가 NO ACTION이 되면 모든 purge가
100% 실패하고, 메시지는 전혀 다른 CHECK를 가리킨다). 그래서 검사를 세웠고, 그 검사는
"떨어뜨리기 전 모습"을 `head-schema.sql`에서 읽었다.

**head-schema는 마이그레이션을 전부 적용한 뒤 뜬 덤프다.** 즉 309가 만든
`ADD CONSTRAINT`가 곧 head의 그 줄이다. 둘을 맞대는 것은 자기 자신과 맞대는 것이고,
CASCADE를 빠뜨리면 양쪽이 **함께** 바뀌어 검사는 초록으로 남는다. 막으려던 바로 그
사고에 대해 검사는 구조적으로 눈이 멀어 있었다.

고치는 방법은 하나뿐이다 — 정본을 **함께 움직이지 않는 것**으로 바꾼다. 재키 이전
(308)의 FK 222개 액션을 얼려 `contracts/vnext/`에 두고 sha로 핀했다. 그리고 검사가
실제로 보는지 확인하려고 CASCADE를 떼고 head-schema까지 함께 고쳐(옛 판이 정확히
눈감던 조합) 돌려 봤다. 새 축은 빨강, 옛 축은 초록. 그것이 증명이다.

같은 부류가 셋 더 있었다.

- **Parse 오라클이 SQL 조립기 45개 중 6개만 불렀다.** "인자가 전부 bool이거나
  기본값"이라는 조건에 안 걸리는 함수를 조용히 건너뛰었고, 몇 개를 건너뛰었는지
  아무 데도 적히지 않았다. 인자 표를 만들고(도메인이 모듈에 있으면 리터럴 대신
  거기서 뽑는다), `X | None` 필터의 켜짐/꺼짐 전조합을 만들고, 표에 없는 것도 대역
  인자로 불러 보고, **조용히 빠지는 길 자체를 없애는** fence를 세웠다. 43/45 호출,
  수집 문장 587 → 780.
- **축 비교 검사의 사면이 `legacy_feature_id`를 삼켰다.** 상대가 "feature 식별자로
  읽히는가"를 `feature_id` 부분문자열로 재고 있었는데, text로 남은
  `legacy_feature_id`가 거기 걸렸다. uuid와 맞대면 42883인데 검사는 초록이었다.
  이제 양쪽 축을 다 보되, "text가 아님"을 "uuid임"으로 읽지 않는다 — plpgsql 변수는
  덤프에서 타입을 읽을 수 없으므로 **적극적 uuid 신호**가 있을 때만 판정한다.
- **테스트가 `str()`로 계약 위반을 덮었다.** `PhoneEnrichmentCandidate.feature_id`는
  text 계약이고 docstring이 그 값을 그대로 다음 단계에 넘기라고 지시하는데, 테스트가
  비교 축을 맞추려고 `str(...)`을 씌웠다. 그 한 번의 변환이 driver의 `uuid.UUID`
  도착을 통째로 가렸다. 표기를 맞추지 말고 **표기를 재야** 한다.

### 남는 규칙 둘

**하나.** 검사가 초록인 것과 결함이 없는 것은 다른 사실이고, 그 둘을 가르는 유일한
방법은 검사에 결함을 **일부러 넣어 보는 것**이다. 이번에 그렇게 해서 항진명제를
찾았다. 새 검사를 세웠으면 그 자리에서 한 번 빨갛게 만들어 본다.

**둘.** 하한(floor)은 "판단 대상 수"가 아니라 **"대상을 실제로 몇 개 보았는가"**에
건다. 앞의 것은 결함이 고쳐지는 순간 0이 되어 빨개지고, 뒤의 것만 "검사가 비었다"를
말한다. 이 저장소는 이 실수를 이미 한 번 했고(본문 축 검사의 `seen >= 1`), 같은
모양이 새 검사 셋에 다시 나올 뻔했다.

## 2026-09-10 — 이 부류는 실행이 필요 없었다

T-VN-39 재키가 오래 멈춰 있었던 이유를 한 문장으로 줄이면 이렇다: **범위를 오라클이
아니라 프록시에서 유도했고, 그 결과를 통합 스위트 한 바퀴로만 잴 수 있다고 믿었다.**

두 번째가 틀렸다. 남아 있던 실패의 지배적 부류는 SQLSTATE로 보면 전부 한 곳을
가리킨다 — 42883·42P08·42P18·42703·42804·42P01. 전부 PostgreSQL이 **Parse 단계**에서
낸다. 행이 하나도 없어도, 픽스처를 하나도 세우지 않아도 난다.

그래서 제품 SQL 587문을 모아 head 스키마에 물리는 검사를 세웠다
(`tests/integration/test_product_sql_parses_against_head.py`). **첫 실행 33초, 20건.**
그중 여덟이 진짜였고, 같은 여덟을 통합 스위트로 찾으면 9묶음 × 최대 20분이며 그나마
실패 하나가 DB 픽스처를 죽이면 뒤가 통째로 가려진다 — 실제로 두 번 그렇게 가려졌다.

수집은 모듈을 **import해서** 한다. AST로 문자열을 긁으면 f-string 합성과 `+` 연결을
놓치고, 그것이 또 하나의 프록시가 된다. 조각은 이름 규약이 아니라 **포함 관계**로
가린다 — 품는 문장이 사라지면 조각이 자동으로 다시 검사 대상이 된다. 그런데도 첫 판이
`kortravelmap.api`를 통째로 놓쳤다(editable 설치의 finder hook은 `pkgutil`이 열거하지
못한다). **검사기 자신의 시야도 프록시일 수 있다** — 패키지별 수집 하한을 단언으로
박아 그 침묵을 닫았다.

### 오라클이 검사기의 틀린 전제를 반증했다

`test_procedure_calls_match_their_signature.py`는 docstring에 이렇게 적어 두고 개수만
셌다: *"PostgreSQL은 OUT 자리의 타입을 해석에 쓰지 않는다."* head 오라클이
`NULL::text` 하나 때문에 통째로 안 맞는 `CALL`을 집어내면서 그 전제가 무너졌다. SQL에서
부르는 `CALL`은 OUT 자리도 함수 해석에 넣는다. 검사를 타입까지 넓히자 테스트 SQL에서
같은 부류 셋이 더 나왔다.

### 그래도 실행이 필요한 부류가 있다 — 값

Parse 오라클이 초록인 채로 남아 있던 결함 넷은 전부 **문장의 모양은 옳고 값이 틀린**
자리였다.

- `_upsert_feature_subtype`이 subtype writer에 DTO의 legacy 주소를 넘겼다 — 신규
  provider Feature 적재 **전량**. 실패 89건 중 71건이 이 한 줄이었다.
- `_apply_provider_feature_field_patch`가 같은 실수를 기존 Feature 갱신 갈래에서
  했다. 한 갈래를 고치자 다른 갈래가 드러났다.
- weather·price 값 적재에 legacy→정본 해석이 아예 없었다. producer 넷이 모두 같은
  결함이었고, 고치는 자리를 **적재기**로 잡았다 — producer는 정본 키를 알 수 없고
  (한 transaction 안에서 발급된다), 값 키 해시가 그 필드를 먹으므로 producer를
  바꾸면 기존 행 전체가 다음 적재에서 중복이 된다.
- 드라이버가 주는 `uuid.UUID`가 `str` 계약으로 새는 자리 셋.

`_apply_provider_feature_field_patch`의 결함은 **단위 테스트가 초록으로 덮고
있었다** — 세션 대역이 프로시저의 `o_feature_id`로 DTO의 legacy 주소를 돌려줬고,
그래서 호출자의 identity 대조가 둘 다 legacy로 통과했다. 대역이 정본을 흉내 내지
않게 고치고, **무엇을 받았는지**도 함께 단언했다.

### 조정기는 head 전용이 아니다

`0236 → 300` handoff이 "300 destination catalog does not match the immutable
reference"로 멎었다. 메시지는 어느 줄인지 말하지 않는다(sha256 비교다). 같은 절차를
재현해 catalog의 **행**을 떨어뜨리고 main 조정기 판과 diff했다 — 26,536줄 중 어긋난
것은 **둘**이었다. 309가 shadow 컬럼을 지우며 인벤토리에서 `feature_uuid`를 뺐는데,
컬럼이 아직 살아 있는 300에서 컬럼 단위 ACL 두 줄이 사라진 것이었다.

reference는 release 절차만 다시 만들 수 있다. **바꿀 수 없는 쪽이 reference이고
맞춰야 하는 쪽이 조정기다.** 표는 `to_regclass`, 컬럼은 `pg_attribute`로 조건부로
만든다. 고친 조정기의 300 catalog가 main 판과 byte 동일임을 실측으로 확인했다.

### 픽스처가 운영이 만들 수 없는 값을 심고 있었다

`ck_feature_aliases_legacy_alias_shape`가 통합 런에서 8건을 거부했다. 거부된 값은
`f_1100000000_p_idboundary0001`처럼 **읽기 좋은 이름을 digest 자리에 넣은 가짜
provider id**다. 제약을 느슨하게 하는 대신 픽스처를 현실에 맞췄다 — 픽스처가 운영이
만들 수 없는 값을 심으면 그 테스트가 지키는 것은 존재하지 않는 계약이다.

읽어서 알아볼 수 있는 이름은 `tests/integration/_feature_ids.py`가 되살린다. 이름을
**키가 아니라 씨앗**으로 써서 라벨당 하나의 canonical uuid를 유도한다. 정렬 순서를
의미로 쓰는 자리에는 쓰면 안 된다는 것을 모듈이 스스로 적어 둔다.

### 적대 리뷰

파일 묶음별로 에이전트 10명이 고치고 10명이 적대적으로 재검했다(opus5/xhigh).
**약화 0건 · 축 오판 0건.** 돌려받은 지적은 전부 받았다 — 기대값이 질의 입력과 같아진
자리, 예외 부류만 고정해 역할 오류까지 삼키던 자리, legacy 주소가 다르다는 것만
증명하던 시드 가드, 그리고 제품 결함을 우회하려고 테스트가 미리 해석해 넘기면서
**dagster ingest 접합부를 태우는 테스트가 저장소에서 사라진 것**.

## 2026-09-08 — 조문이 가리킨 것은 번들이 아니라 복원된 데이터베이스였다

M05-2를 판정하려고 300 baseline restore 정책부터 검토했다. **조사가 앞선 판정 둘을
뒤집었다.** 조문의 다섯 단계는 "전부 새로 지어야 하는 코드"가 아니라 커밋 `b2543d68`
직전에 거의 그대로 있었고 그 커밋이 지웠다(`docker-restore-verify.sh` 416줄 → 7줄).
정책 근거도 "스크립트 두 줄"이 아니라 문서·설계 리포트·저널에 있고 2026-08-26 소유자
결정까지 남아 있었다.

**지배적 손실은 사고가 아니라 계획된 재구축이었다.** `pinvi-pair rebuild-pinned`가 Map
revision이 바뀔 때마다 application DB를 파기·재생성한다. 그런데 manual-feature writer는
2026-09-05에 prod에서 켜졌고 **그 evidence를 담은 backup이 n150에서 한 번도 만들어진 적이
없었다.** restore를 켜도 이 손실은 막히지 않는다 — rebuild lifecycle 문제이지 restore
문제가 아니다. 그래서 담는 것(A)이 선행이었다.

**초안에서 이 항목을 `[x]`로 적었다가 되돌렸다.** 근거가 두 요구를 비껴갔기 때문이다.
"lease를 evidence root에 담지 않으므로 fencing token이 되살아날 자리가 없다"는 **번들에
대해서만** 참이다. `pg_dump`는 스키마 전체를 담으므로 복원본에는 lease 행이 dump 시점의
`worker_id`·`lease_epoch`을 달고 그대로 돌아온다. 복원본은 원본의 **사본**이라 같은 쌍이
양쪽에서 동시에 유효하다. 조문이 말한 "live lease holder/expiry 무효화"는 그 행을
가리켰지 번들을 가리키지 않았다. `acked_through_sequence`도 같은 행의 컬럼이었다.

그 둘은 과결박이 아니라 split-brain과 cursor 후퇴를 막는 **진짜 안전 요구**였다. 완화할
일이 아니라 지을 일이어서 D단계를 지었다. 무효화는 holder를 지우는 데서 그치지 않고
`lease_epoch`을 **올린다**. n150에서 진짜 ack 프로시저로 쟀다 — 옛 토큰이
`lease_conflict`를 받고 cursor가 밀리지 않는다.

**실행이 아니면 못 찾았을 것들.** C단계에서 셋(`--no-owner --no-privileges`가 질문 자체를
불가능하게 했고, `search_path` 미고정으로 PostGIS 함수 495건이 거짓 양성, ACL 미정규화로
1건 더). D단계에서 넷 — 그중 하나는 **내가 지어낸 컬럼 이름**이었다(`origin.command_id`,
실제는 `creation_command_id`). 건강한 DB에서 preflight가 빈 목록이어야 한다는 단언이
그것을 잡았다.

**mutation 열 축 중 둘이 처음에 공허했다.** dry-run 단언이 롤백되는 트랜잭션에서 돌아
몰래 쓰는 구현을 못 잡았고, 연속 prefix 축은 정상 이력에 구멍이 없어 `max(...)`와 갈리지
않았다. **정상 상태만 재면 검증기를 통째로 비워도 초록이다** — 이번 세션에서 반복해 겪은
그 양상이다. 둘 다 고쳐서 열 축 전부 RED다.

**부수로 순서 의존 하나를 드러냈다.** 새 모듈이 알파벳 순으로 먼저 돌면서 정본 구독을
만들자 기존 M05 테스트의 두 단언이 조용히 무의미해졌다(`P0002` → `23514`). 구독은
append-only singleton이라 그 성질들은 pristine DB에서만 관찰 가능하다. 관찰과 구독 생성을
session scope fixture 하나가 소유하게 바꿨다 — 세 배치 순서에서 36건 모두 통과한다.

## 2026-09-07 — 원장을 믿지 않고 15항목을 실측했더니 55건이 틀려 있었다

`T-VN-PAIR-V2`를 닫은 뒤 남은 열린 항목 전부를 8축으로 실측하고 판정마다 반증에
부쳤다(75 에이전트). 원장 서술과 실제가 다른 곳이 **55건**이었다.

**가장 나쁜 것은 낡은 식별자가 현재형으로 서 있는 것이었다.** `T-VN-M05-ACTIVATION`
줄이 두 pinset 전의 값을 인용하고 있었다. 원인은 중복이다 — 규약 §5는 tasks.md entry를
"제목 + 1~3문장"으로 정하는데 6개 항목이 최대 703자까지 부풀어 acceptance 본문을 통째로
들고 있었다. **한 사실이 두 곳에 적히면 한 곳만 갱신되고, 갱신 안 된 쪽을 읽은 사람이
틀린 작업을 한다.** 정리하고 길이 게이트를 걸었다.

**"즉시 착수 가능"이라던 셋이 실제로는 착수할 수 없었다.** H49 자식들의 마지막 조건은
복원 리허설 1회였는데, 돌려 보니 `rehearse-restore`가 **한 번도 동작한 적이 없었다** —
`docker cp`가 host 소유권(root:root 0600)을 보존하는데 `pg_restore`는 컨테이너 postgres로
돈다. 모든 백업이 root 0600이라 role을 바꿔도 같다. 더 나아가 **n150에 예약 백업이 아예
없다**(crontab·timer·logrotate 전부 부재, 세 인스턴스는 백업 0건). H49 부모의 전제인
"주기 백업이 수렴한다"는 수렴할 대상이 돌지 않는다.

> **2026-09-08 정정.** 굵게 쓴 저 문장이 틀렸다. `digitie` crontab에 셋이 매일 돌고
> 2026-08-21부터 18일 연속 성공했다. root로 실행한 조회가 `/root/backups`를 봤고 cron은
> `KTDM_BACKUP_ROOT=/home/digitie/backups`를 쓴다 — **다른 디렉터리를 보고 "없다"고 적었다.**
> `crontab·timer·logrotate 부재`는 root에 대해서만 사실이다. 상세는
> `docs/tasks-acceptance.md` §T-VN-H49 측정 오류 정정.

**승격이 기계적으로 불가능했다.** M04/M05 승격을 판정하려고 적대 리뷰 2건을 돌렸더니
둘 다 NO_GO였고, P0는 "원장이 정의한 승격 경로(PinVi 서명 receipt 발급)가 isolated
scope를 받지 않는다"였다 — 그 분기는 어느 진입점에서도 도달 불가한 死코드이고, 덮는다는
테스트는 소스 문자열 grep이었다. 소유자가 정의 변경을 택했고, 나는 그것을 문서 문장이
아니라 **재계산 가능한 대조**(`--verify-leaf`)로 만들었다. 서명은 근거에서 뺐다 —
키가 실행마다 새로 생성돼 실행과 함께 사라지므로 사후 진위를 주지 못한다.

**같은 패턴이 세 번 나왔다.** 위임이 dangling pointer이거나(M04 → 41C가 수락한 적 없음),
조문이 없거나(M05), 조문이 도달 불가능한 것을 요구한다(M05-ACTIVATION). 세 경우 모두
**증거는 이미 있었고 판정할 문장이 없었다.**

내 게이트도 두 번 틀렸다 — 하나는 정당한 다른 용법까지 금지해 CI를 빨갛게 만들었고,
하나는 도달 불가능한 코드를 덮는다고 주장했다(변이 검증이 잡았다).

## 2026-09-07 — pair 계약 v2: 이중 선언 하나를 걷는 데 적대 리뷰 두 라운드가 들었다

`T-VN-PAIR-V2` 완주. 계약에서 필드 둘을 빼는 일이었는데, 실제 작업은 **그 값을 누가
만드는가를 표면마다 이름 대어 정하는 것**이었고 나는 그것을 두 번 틀렸다.

**틀린 것 하나 — evidence는 Manager 산출물이 아니었다.** receipt의 스키마 검사가
evidence 표면 블록에 `source_revision`을 요구했다. 나는 주석에 "evidence는 v1·v2 모두
revision을 싣는다"고 적었는데 사실이 아니었다 — 그 블록은 **attestation이 계약을 그대로
복사한 것**이다. v2 계약에서는 그 키가 없으므로 v2로는 **어떤 receipt도 만들 수 없었다.**

**틀린 것 둘 — service 표면의 정본은 pin registry가 아니었다.** 네 표면을 뭉뚱그려
pinned Map revision으로 채웠는데, service의 정본은 PinVi
`kor-travel-map-service-provenance-v1.json`이고 v1 pair 계약이 그것을 세 번째로 선언하고
있었을 뿐이다. digest는 전부 일치해서 회전 preflight도 격리 preflight도 통과하고,
**71분 rebuild가 끝난 뒤 PinVi 컨테이너가 기동에 실패**했을 것이다.

**두 결함을 픽스처가 가리고 있었다.** receipt 테스트가 evidence의 표면 블록을 손으로
적어 실제 생산자가 낼 수 없는 문서를 만들고 있었다. 이제 vendored 계약에서 그대로
가져온다 — 계약이 v1이든 v2든 픽스처가 자동으로 그 모양을 따른다. **소비자의 기대에
맞춘 픽스처는 생산자의 출력을 검증하지 않는다.**

**변이 검증이 공허한 게이트를 네 번 잡았다.** §7에서 둘(`_pair`의 v1 거부에 테스트가
없었고, 전용 검사 하나는 **도달할 수 없는 코드**였다 — 위의 스키마 검사가 먼저 잡는다),
그리고 회전 게이트에서 둘(대역이 인자를 무시해 저장소·revision을 잘못 지목해도 초록).
게이트를 쓴 다음 **되돌려서 빨간불을 보는 것**이 게이트를 쓰는 일의 절반이다.

**내 게이트가 CI를 한 번 빨갛게 만들었다.** `assert "expected_revision=map_source_revision," not in source`가
너무 넓어서, 같은 문자열의 **정당한 다른 용법**(checkout HEAD 대조)까지 금지했다. 원인은
절차 누락이다 — 단언을 추가한 뒤 변이 하네스만 돌리고 깨끗한 통과 실행을 하지 않았다.

**§6에서 무관한 선행 결함 하나가 드러났고, 그것도 좋은 실패였다.** Playwright runner 핀이
1.62.1인데 PinVi lockfile은 1.63.0이었다(회전 전부터 그랬다). 어긋나면 본문 브라우저
기동에서 무조건 소각인데 `_assert_playwright_runner_matches_pinned_source`가 **실행권
소비 전에** 잡았다.

측정: 회전 preflight가 Map 5커밋 전진을 PinVi 커밋 없이 수용(exit 0), 어긋난 revision에는
두 digest를 찍으며 거부. rebuild `phase: committed`, 격리 M05 e2e `status: passed` —
v1 분기를 걷어낸 Manager로 한 번 더 돌려 같은 결과를 받았다.

## 2026-09-06 — 원장이 나를 틀린 작업으로 보냈다. 41C는 구현이 남은 게 아니었다

D2를 닫고 `docs/resume.md`가 적은 "다음 한 작업"을 따라 `T-VN-41C`에 착수했다. 다섯 축을
병렬로 실측하고 각 발견을 반증에 부치자 두 가지가 드러났다.

### 1. 순서 정본이 서로 모순이었다

    docs/tasks-acceptance.md:34      D1 → E → D2 → 41C
    docs/tasks-acceptance.md:89-96   같은 순서(배리어 5단계)
    docs/tasks-done.md:87            같은 순서
    docs/resume.md:23, :63           41C → F1D-E   ← 뒤집혀 있다

즉 41C의 선행은 `T-VN-41F1D-E`인데 resume.md만 반대로 적었고, **CLAUDE.md가 resume.md를
"다음 한 작업의 단일 정본"으로 지정**하므로 그것을 따른 나는 선행을 건너뛰었다. 더 나쁜
것은 이것이 재발이라는 점이다 — 2026-09-04 journal이 같은 오류를 "내 오류"로 정정했는데
resume.md에 다시 들어와 있었다.

**배울 것.** 정본을 여러 파일에 두면 그중 하나만 틀려도 전체가 틀린다. 이 저장소는 그
결함 계열을 `AGENTS.md` DO NOT 15로 이미 이름 붙여 뒀다(이중 선언). 순서도 같은 계열이다.

### 2. "reconciliation은 구현이 남아 있다"가 거짓이었다

2026-09-04에 41C를 "acceptance가 아니라 구현이 먼저"로 재분류했고 그 근거로
`tasks-done.md`를 인용했다. 그런데 인용된 문장은 reconciliation의 **구현**이 아니라
**live acceptance**를 잔여로 적는다. 근거 사슬이 어긋나 있었다.

실측하면 relay 넷이 전부 있다 — `cache_target_outbox_repo.py`에 lease(만료 컬럼 + 상한
300초), retry(`attempt_count`/`max_attempts=5`), dead-letter(조회·상세·목록 + ETag),
replay(service·admin 양쪽). reconciliation도 5-status 상태기계 전이가 5/5이고 DB 대조는
natural-key head를 두 번 server-cursor scan해 Merkle root로 고정한다. 라우터가 repo를
끝까지 부른다.

남은 것은 **런타임 결선**, **enable 경계 구현**, 그리고 **구조적 순환**이다. 셋째가 가장
무겁다: 켜면 `environment_sha256`이 바뀌어 rebuild가 필요한데, Manager가 rebuild를 하려면
cache-target 값이 inert여야 한다. **현 lifecycle에서 enable과 rebuild는 상호배타**이고
이건 코드로 풀 문제가 아니라 소유자 판정이다.

### 부수로 드러난 것

- `1-a`/`1-b`/`1-c` 표기는 어느 정본에도 정의가 없다. 2026-09-04 커밋이 범례 없이 처음
  썼고 세 저장소·ADR·integration-map·contracts 어디에도 대응이 없다. 이 표기로 잔여를 세면
  세는 사람마다 다른 것을 센다.
- 41C 본문이 "n150 GC 실측"을 완료로 위임하는데 그 러너는 5줄 `exit 2` stub이고 수치는
  `0231` **이전** 세대의 것이다. 위임 문장이 현재 거짓이다.
- receipt 승격이 요구하는 `map_service_openapi_sha256 == pinvi_service_vendor_sha256`이
  성립하지 않는다. 후보 archive는 옛 후보(`77821001`/`e8e0fec`, sha `c6f9aba6…`)에 핀돼
  있고 현 트리는 `99ba6c17…`다.

### 조사 자체의 한계

세션 한도로 반증 41건과 종합이 돌지 못했다(28건만 실행, 10건 반증·18건 통과). 위의
결론은 반증을 통과했거나 **내가 직접 재현한** 것만 적었다 — relay 넷의 존재, 5-status
전이, GC stub 5줄, 순서 모순 네 인용, 후보 archive의 sha 불일치는 전부 직접 확인했다.
반증이 돌지 못한 발견은 원장에 넣지 않았다.


## 2026-09-06 — D2가 닫혔다. 스펙이 아니라 **증거 계약**에서 열두 번 걸렸던 것

`T-VN-41F1D-D2`가 오래 진전이 없던 이유를 근본에서 보면 두 겹이었다.

### 1. 바깥 겹 — 해제 조건에 없던 의존

D2 스펙의 첫 write가 `POST /v1/admin/features`인데 배포 API가
`KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false`로 `MANUAL_FEATURE_CREATE_NOT_READY`
503을 냈다. 즉 D2는 `T-VN-M01` **활성화**에 의존하는데 원장의 어느 줄도 그렇게 적지
않았다. 2026-09-05 실행이 그것을 값으로 드러냈다.

M01의 활성화 전제 셋 중 restore 축은 **수행 가능한 형태가 아니었다** — 설계(2026-08-19)
이후의 300 baseline 결정이 `docker-restore*.sh` 셋을 본문 없이 종료하게 만들었기 때문이다
(`restore is disabled: backup artifacts are audit-only under the 300 baseline`). 소유자가
"300 baseline이 대체한 것으로 보고 활성화"로 판정했고, 나머지 두 축을 측정으로 닫았다:

    ACL 축     scripts/m01_activation_preflight.py  55/55, 활성화 rebuild 앞뒤로 두 번
    거부 축    scripts/m01_activation_live_gate.py  잘못된 자격 조합 넷 전부 403
    zero-write 같은 스크립트가 witness 8관계 count 대조 — 증분 0
    성공 축    POST /v1/admin/features → 201 (플래그가 켜져야 관측 가능하다던 그것)

플래그는 `2026-09-05T20:27:59Z`에 `true`가 됐다(백업
`.env.bak-pre-m01-activation-20260905T202759Z`). `.env`가 바뀌면 `environment_sha256`이
바뀌므로 rebuild가 따라왔고, 그래서 ACL 축을 rebuild 뒤에 한 번 더 측정했다 — §8.2가
"restore 뒤 동일"을 요구하기 때문이다.

### 2. 안쪽 겹 — 스펙은 통과하는데 lane이 실패했다

활성화 뒤 D2는 **스펙 자체를 통과했다**(main·recovery 각
`{"counts":{"passed":2},"result":"passed"}`). 그런데도 lane은 실패했다. 이후의 결함은
전부 증거 계약 쪽이었고, 하나를 고치면 다음 하나가 드러났다. `_validate_evidence`가
**정확한 파일명 집합**과 action별 추가 키를 요구하는데 그 검증은 **스펙이 통과한 뒤에야**
돈다. 그래서 결함이 병렬로 보이지 않고 직렬로만 드러난다 — 배포 스택 실행 한 번에
하나씩. 열둘을 그렇게 지났다:

    seed FK 계약 → preflight role escalation → helper SQL 컬럼 → await 우선순위 →
    executor 격리 가드 → M01 kill-switch → create body state 축 → 201을 실패로 읽던 헬퍼 →
    seed FK 기대값 → .stderr 파일 집합 → executor.log 파일 집합 → summary_run_ids 키

**여기서 배울 것.** 직렬 노출 자체는 검증기의 결함이 아니다(증거는 실행이 끝나야
존재한다). 결함은 그 직렬 비용을 아무도 세지 않은 것이다. 열두 번의 배포 스택 실행이
필요했다는 사실이 "게이트를 로컬에서 유도해 미리 깨뜨려라"는 요구를 값으로 만든다.
그래서 열두 결함마다 `tests/lint/`에 탐지기를 남겼다 — 각각 유도 → 결박 → 탐지
(`AGENTS.md` DO NOT 15)이고, 전부 변이로 red를 확인했다.

### 3. 그 탐지기들도 적대 리뷰에 부쳤다

5개 축·74 에이전트가 68건을 냈고 34건이 확인됐다. 게이트 품질 쪽에서 **실제 과허용
둘**이 실측됐다:

- create body 게이트가 모델 필드를 `\nclass X(`부터 다음 `\nclass `까지 텍스트로 잘라
  긁었다. 두 클래스 사이의 **모듈 수준 함수 본문까지** 쓸어 담아 `try`가 "모델 필드"로
  잡혔다. 스펙이 그런 이름을 보내도 green이었다. → AST로 클래스 본문의 `AnnAssign`만
  세고, base 이름을 리터럴로 박는 대신 `class X(Base)`를 따라간다.
- executor env 게이트가 요구 env를 가드 **한 함수** 본문에서만 유도했다. 요구가 헬퍼로
  빠지면 유도 집합이 조용히 줄고 `missing == []`이 공허해진다. → 가드가 부르는 같은
  모듈 함수를 따라가 본문을 합친다.

자기검사도 동어반복("필드가 있다")에서 전제 확인(모델 계열이 실제로 `extra="forbid"`인가)
으로 바꿨다. 전제가 무너지면 이 대조 전체가 의미를 잃으므로 red로 알려야 한다.

### 4. 그래서 닫혔다

pinset `48166bd2…`(Map `ab3640f8` + PinVi `f72eedf1`)에서 lane이 `phase: passed` /
`status: complete`로 끝났다(2026-09-06T01:47:03Z, runner exit 0, 1분 43초).

    스펙      main·recovery 각 {"counts":{"passed":2},"result":"passed"}
    evidence  phase=evidence-validated  파일집합 exact(10) lifecycle 48 FK제약 18 리포트 2
    cleanup   direct-cleanup·direct-audit 모두 features/price_values/weather_values 0, FK 0
    잔여물    lane과 독립으로 재측정 — 소유 row 0, 라벨 컨테이너 0, afla 이름 컨테이너 0
    선행      ACL preflight 55/55 · D1 11 passed(29.9초), 같은 pinset

lane의 자기 신고를 그대로 받지 않고 잔여물을 **따로** 셌다. `SET ROLE
ktm_feature_schema_owner` 없이는 `permission denied for schema feature`가 난다 —
Map 역할이 전부 NOINHERIT이라 그렇다. 그 자체가 M01 ACL 계약이 살아 있다는 증거다.

남긴 것 하나: `feature.features` 전체가 1건인데 그것은 2026-09-05 내 422 격리 probe가
만든 Feature다. `suppressed`로 눌러 뒀고 hard purge는 `T-VN-M02`까지 fence돼 있어
지우지 않는다. acceptance 소유 row는 0이다.

### 다음 결함을 미리 깨뜨리는 게이트

이번 비용의 정체는 "계약 위반이 스펙 통과 뒤에만 보인다"였다. 그래서 그 대조를
CI로 끌어왔다 — `tests/lint/test_lane_operations_are_declared_once.py`가 러너 호출부에서
`$RUNTIME_DIR` 산출물 이름과 operation 집합을 유도해 검증기와 exact 대조한다.
stderr 접미사는 검증기 상수가 아니라 supervisor(파일을 실제로 만드는 쪽)에서 읽는다 —
두 소비자를 서로 대조하면 둘이 같이 틀려도 green이기 때문이다. 같은 커밋에서
`assert_container_residue_zero`의 operation 목록 이중 선언도 없앴다.


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

