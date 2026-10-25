# 430 전체 PG gate의 첫 원인 수정

## 현재 상태

최종 후보7f40 CI glibc는118FAIL/1768PASS/23SKIP/30ERROR(978.50초)였다.
원문 전체4MB와 모든148개 node는 원장에 보존했다. 이 결과를 분리된 owned 시험의
성공으로 덮지 않는다. Alpine도 같은148개 node가 실패했다(118FAIL/1762PASS/29SKIP/30ERROR,1269.76초).
운영 배포는 보류 상태이며 다음 owned 결과와 원 CI를 분리한다.

## 실제 canonical projector 문제

`recompute_provider_field_candidates`는 private projector를 호출한다. 원 projector의
INSERT ON CONFLICT는 기존 base와 값이 같아 UPDATE가0건이어도 BEFORE INSERT를 먼저
실행한다. 낮은 순위 provider의 정상 SH 관측이 unchanged foreign winner를 재투영할 때
strict guard의 own dataset 검사에 걸렸다. 기존 scalar 두 순서 시험이 이 경로로 실패했다.

새430 sidecar는 완전히 같은 base(provider/entity/record/hash/JSON/geometry/observed_at)가
있으면 INSERT문 자체를 건너뛴다. 실제 변경은 기존 UPSERT/WHERE와 Feature projection을
그대로 실행한다. owner/security/search_path/ACL/guard·권한·한도 변경0이고412 원본은 보존했다.
원 UPSERT와 나머지 body는 조건부 블록을 역제거하면 전체 byte가 같다.
반복 foreign winner의 base revision/updated clock이 그대로인지와, 같은 manifest Feature의
진짜 foreign base 변경이 계속23514/rollback되는지 새 paired source 두 개를 추가했다.
실행 전 두 source 리뷰가 필요하며 실제 통과를 선기록하지 않았다.

## 시험 계약/정리 원인

- canonical 관리자 tree cleanup은 첫 raw tracking UPDATE 전에 정본 P EX→L을 취득한다.
  같은 helper를 부르는 reconcile 시험의 finally가 본체 결과를 cleanup23514로 덮던 원인이다.
- tracking prefix 시험은 정상 finalizer 입력을 새 RC로 실행하며 L-only 및 actual P waiter의
  원23514/55P03 단언을 유지한다. 별도 SERIALIZABLE 조기거부 시험은 그대로다.
  430이 교체한 세 body는 실제430 공식 golden 전체본문에 대조하고 나머지는424 inverse를 유지한다.
- registered legacy finish negative fixture는 kernel claim 전에3s/900ms를 명시한다.
  원6개23514/private marker 부정 단언은 그대로다.
- reset fixture는 해당 testcase가 생성한 `reset-plan:` ready attempt만 정본 typed cancel로
  해제한다.60초 lease owner가 다음 case를 막던 연쇄를 제거하며 기존 reset/CAS/rollback
  단언과 owner 비교는 변경하지 않는다.

공유 conftest/기대값 삭제/실패 숨김/blanket runtime prefix 추가0이다. Root가 별도 소유한
batch/pipeline cancellation 정리 파일은 이 브랜치에서 편집하지 않는다.

## 검증과 남은 수용

25 unit PASS1.82초와 관련63개 통합 수집을 확인했다. 최초 Ruff 줄길이/비동기 파일읽기
정적 실패는 수정 전 로그로 보존했다. 실제 SQL 설치/paired·원모듈 회귀/새 공식 golden 및
전체 두 PG CI의 재수용은 미완이다. 추가 canonical/TVN40의 raw seed·RC 변경과 오래된
source-only RR 시험의 새 prefix 경계도 원로그 callsite를 계속 분류한다.

원 CI log SHA: `89f14fecf6522541a947e78024fc9f050cacecdb742eb48d32a6f51cb0018fc0`.
148 node inventory SHA: `d9ae88e8360872d8962b55b9e785be69acb6b62db069532e798932cf3d77d737`.

## old RR fixture와 winner handoff의 별도 범위

source-only old RR의 첫 INSERT가 missing-P23514에서 중단되던 source는 history record를
별도 정확EX seed로 준비하고, old RR snapshot→외부 cutover→명시 P EX→원head UPDATE로
정렬했다. 원40001/head불변 단언은 그대로며 fresh first-party 진입 성공을 주장하지 않는
수동 old-RR 부정 시험이다. canonical lifecycle의 직접 성공 TX도 RC로 바꾸고, 별도
SER 조기거부 시험은 유지했다. 제품/guard 변경은 앞선 no-op sidecar 외에 없다.

정본 winner는 `removed` 후보를 지원하므로 A 제거→B 실제 handoff는 일반 의미에 포함된다.
현재 shared/exclusive scalar API는 자동 fallback을 하지 않으며, 진짜 foreign base 변경은
계속23514다. 최초 durable Airport의 unchanged raw profile에서는 그런 변경을 진입 전
배제하지만 일반 remove policy의 handoff는 별도 fresh EX plan/apply가 필요하다.
no-op 수정으로 이 경계의 SH 지원까지 완료했다고 주장하지 않는다. 기존 foreign 변경
부정 시험은 유지하며 EX handoff paired proof는 별도 미완이다.

추가 actual source는 canonical policy2의 `omitted_policy=remove`와 양 provider의 정본
후보 capture를 사용한다. SH에서 A name 제거→B winner 선택은23514/원head·base rollback을
확인하고 그 ready plan을 typed cancel한 뒤 새EX attempt로 같은 raw/hash/관측시각을 적용한다.
B winner 출처·A removed 상태·own phones·원시각 및 두 attempt의 cancelled/completed까지
대조할 계획이며19개 scalar 수집/Ruff만 확인했다. 실제 결과는 아직 미완이다.

## 첫 owned64 결과와 fixture 문자열 정정

고정2471의64개를 한 fresh owned PG에서 실행해61PASS/3FAIL(34.15초)을 얻었다.
tracking25/RC11/reset9 및 기존 scalar16은 통과했다. 새 scalar3개는 SQL 문자열 말미의
`COLLATE "C"` 닫는 따옴표가 Python triple quote에 흡수되어42601에서 중단됐다.
원64 전체는 FAIL로 보존하며 새 paired no-op/foreign 변경/EX handoff 본체 수용은 미완이다.
정정은 세 SQL 문자열의 닫는 delimiter를 다음 줄로 분리하는 시험 코드뿐이며 제품 SQL과
원assert는 그대로다. 원result SHA80d87d1b7ff3ef5e33799959b900df5e605e2cd4f36ccfdc9ec559ecd62f425b를 보존했다.

원runner의 성공 분기 postcheck는 실행되지 않았다. 별도 실제 postcheck로 Git2514파일,
SDK53파일, 실제19import hash 및 원raw8개 hash를 확인했다. exact CID 부재/UUID0/
전체 scalar label0/owned volume1부재를 다시 조회했고 PG 슬롯을 반환했다.
이 보충 확인은 원runner PASS나 paired3 성공으로 세지 않는다.

새3만 고정9c4f로 재시험한 결과1PASS/2FAIL(19.33초)이다. unchanged foreign winner
positive는 본체 통과했다. 나머지 두 case는 SH23514/rollback·원본불변 단언 뒤 finally의
typed cancel TX에서 statement timeout 미설정으로 kernel cap23514가 발생했다. 두 cleanup
TX에만 기존 apply와 같은8초 상한을 명시하며 제품guard/원단언을 유지한다. EX handoff
후반은 이 cleanup 실패로 미도달이므로 성공으로 세지 않는다. 원r2 결과와 정확정리는 보존한다.

고정1b008의 남은2 재시험은1PASS/1FAIL(17.62초)이다. SH 제거 rollback→typed cancel→
fresh EX로 같은 입력 적용→B winner/own phones/원시각 및 attempt 상태까지 handoff 본체는
통과했다. 마지막 raw base 변경 부정은 runtime에 raw UPDATE grant가 없어42501로 먼저
거부됐다. 기존 strict 시험의 managed-base 경계와 같이 admin 연결의 정본 begin 후
명시 SchemaOwner로 UPDATE하며 원23514/message/rollback 단언을 그대로 검증한다.
관리 SQL 증거를 일반 runtime raw 권한이나 guard 성공으로 혼동하지 않는다.

## paired 결과와 실제 공식 golden

관리 owner 부정 마지막1개는 고정6030652에서1PASS로 원23514/message/rollback까지
검증했다. runtime raw UPDATE42501와 managed guard23514를 분리한다. 새3은 서로 다른
fresh 실행에서 각각 통과한 증거이며 최초64실행61PASS/3FAIL을 단일64PASS로 합산하지 않는다.

동일6030652 제품으로 canonical application300→430 fresh bootstrap과 공식 재덤프 비교
1PASS54.22초를 확인했다. runtime reconcile호출0, 실제service역할/SDK53/Git2514·
9import/원raw9 SHA와 정확CID/UUID/global0/volume1부재를 확인했다. 새 실제dump SHA
`87929f98fe54f63a5b8c737b9cc867f92d7fc91d4b4e9ff432053585f0933e4c`를채택했다.
부모dump에대해 projector 정의1개만 역치환하면 전체bytes가 같으며 ACL/owner/기타객체는
모두동일하다. 원412본문과 새430 no-op조건 외의 제품변경0이다.
canonical/TVN40/reconcile 원실패 actual과 전체CI/배포수용은 계속미완이다.

## T-VN-40 직접 시험 호출의 전제 정렬

원 failed callsite별로 finalizer/동일TX ensure→seal·terminal reconcile의 직접 성공/의미
부정 TX만 RC로 정렬한다. ensure만 실행하는 leaf SERIALIZABLE 및 admin command의
SER 계약은 유지한다. provider root를 직접 만드는 두 owned admin seed는 첫 row 이전
정본 P EX→L을 명시한다. raw cancellation42501 부정은 fresh RC의 정본 prefix를 먼저
취득해 typed 권한 검사까지 도달시키며 원42501 단언은 보존한다. 공통fixture/실제
production caller/권한/guard/모든 기존assert 변경0이다. 이 단계 실제 회귀는 아직미완이다.

원4모듈77 고정e807 실제는72PASS/5FAIL43.80초이다. canonical45/reconcile12는
모두통과했다. raw provider 권한부정의 두loop prefix와 sourcecatalog 직접finalizer의
SER시험 전제를 추가정렬하며 기존42501/성공결과 단언은 유지한다. 나머지 세 성공경로는
제품RC finalizer→기존SER source observation의 실제모순이다. fixture로피하지않고
해당내부정의/권한·fresh prefix/capture검증을보존하는 제품수정 별도리뷰가필요하다.
원77 전체FAIL/정확정리를보존하고72와후속을단일77PASS로합산하지않는다.

## legacy catalog의 실제 RC/SER 모순 수정안(source만)

성공 finalizer 세 경로는 `refresh_curated_source_observation`의 원SER 요구에서25001로
실패했다. 그다음 `materialize_theme_candidate_generation`에도 같은 원SER 요구가 있어
두 내부 기존SD를430 sidecar로명시교체한다. 이는제품수정이며fixture허용확대가아니다.
기존SER진입/권한/검증/실본문은그대로이고, RC는현재DB/currentPID의actual granted P EX와
L을둘다이미보유할때만추가허용한다. 새lock취득/승격0이다. generation은추가로
`provider_full_snapshot`만RC이며 `rule_reconcile`은원SER을유지한다. owner는기존
CommandOwner이고새publicEXEC/role/table권한·signature변경0이다.

정본 finalizer는먼저fresh P→L을취득하고immutable childseal와actualroot capture를전부
대조한뒤이두SD를호출한다. 새조건은그내부호출의actualprefix를관측한다. pg_locks로
session/xact과거취득순서를attest하지않고원관리owner경계한계를유지한다. firstparty
helper는이미xact P/L을재취득한다. 별도일반helper/재시도GUC/우회token은추가하지않는다.

고정429 공식dump893e61의두정의를출처와함께fixture로보존했고새RC조건을역제거하면
각본문전체bytes가같다. static29PASS2.11초/Ruff와신규11통합수집만확인했다.
부정source는missingprefix/SH-only/P-only/L-only/다른PID각두정의와RC rule_reconcile을
확인한다. 원성공TVN40 세경로의관측값/생성receipt/취소SUCCESS결과단언은그대로이며
두제품source리뷰뒤이11과원TVN40실패5개를한owned PG에서검증할계획이다.
이새두정의의실제설치/성공/golden갱신은아직미완이고이전projector공식dump와구분한다.
