# bound snapshot의 정확 stale 뒤 재계획 복구

> 최신 수용(2026-10-27 18시 UTC 관측): #1424의 정확6611 코드는 정상 머지됐고,
> 현재 배포 Map001487에 포함돼 있다. 최신 pair의 DB433/0102·원51상태 복구와
> 공개 UI13·정리를 확인했다. [최신 운영 정산](#현재-배포-포함원51복구공개-ui13-수용)과
> [최종 코드 수용](#정확6611의-최종-ci실제-ui정상-머지-수용)을 구분한다.
> 아래 첫 “현재 단계”와 각 미완 문구는 해당 checkpoint를 작성한 시점의 이력이다.

현재 단계: f29 제품 owned16과 후보 UI14는 통과했다. 전체 CI는 정본 oracle 빈줄과
alpine의 기존 관찰자 cold codec timeout으로 실패해 두 지점만 교정 중이다. 새 head의
실제 pair2·후보UI·CI·머지는 미완이며 원 실패를 보존했다. 운영/profile 활성화는 없다.

## 최초 조사 범위(실제 재현 전 기록)

현재 Airport/Rest 실제 asset은 저장 artifact와 executor fence를 가진 전용 coordinator를
호출한다. 선택 stale로 atomic apply TX가 rollback된 뒤에도 기존 expired-plan reset은
READY lease가 유효하면55P03으로 거부한다. 이는 정적 코드에서 확인한 경계이며,
아래 실제 PG 재현 전에는 운영 장애가 발생했다고 단정하지 않는다.

첫 checkpoint는 기존 제품 코드 그대로 두고 Airport 실제 등록·plan·atomic apply에서
manifest Feature revision을 낡게 하여 정확40001→전체 rollback→liveREADY55P03을
관찰할 통합 시험 source다. 새 SQL/운영 실행은 아직0이며 source 두 독립 리뷰 후
소유 격리 PG에서만 재현한다. 실패하면 원 증거를 보존하고 실제 지점부터 교정한다.

## 제안하는 작은 제품 변경

기존 expired reset의 lease guard·ACL을 약화하지 않는다. 현재 executor generation/fence와
정확 bound attempt/owner/manifest에만 적용하는 typed rolled-back reset을 별도 additive
SQL로 추가하는 안을 검토한다. protocol→parent/scope→attempt→control 정렬 잠금 뒤
prepared control/READY plan/현재 owner·epoch를 검사한다. 살아 있는 apply가 있으면
기존 잠금 deadline으로 거부하고, 완료/취소/새 owner를 되돌리지 않는다.

이후 기존 Airport/Rest의 선택 ReplanRequired catch에만 연결한다. SDK0 read·storedbytes,
MAX_REPLANS3, executor lease/fence, 취소·원 결과·postprocess·child/root seal과
30초/reader3초/lock1초 상한을 유지한다. generic unbound cancel이나 전체 snapshot·지역·
새 identity·retire·profile enable은 범위가 아니다. T-CWRITE-01~09는 모두 미완이다.

구현/실제 재현/두 독립 적대 리뷰/최종 CI 및 운영 효과 수용은 아직 완료되지 않았다.

## 첫 source 확인

Ruff check/format과 fixture 설정을 실행하지 않는 collect-only1개(7.70초)가 통과했다.
실제 PG 재현·새 typed SQL 구현·운영 호출은 아직0이다. 기존 typed reset을 약화하지 않는다.

## 최초 owned 재현 시도의 setup 실패

정확 `d13312a9` source의 최초 실행은1ERROR/41.53초였다. 새 module timeout40초가
Alembic400 baseline 초기 적용 중 만료돼 시험 본문에 도달하지 못했다. 따라서 선택stale,
apply aborted, liveREADY, reset55P03은 아직 실제 관찰하지 않았다. 원 result SHA256은
`5f10c61de932a28fffe46589851df1ddca02f64962ce2ac54344dd5ec92eccb6`이며 원 log/XML을
보존했다. exact 소유 CID·익명 volume1·전체 scalar label0 정리는 통과했다.

기존 Airport scheduled donor와 같은 module50초로만 정정한다. 제품 Python/SQL,
owned 전체150초/감시160초/회수15초·PG CPU2/RAM1536MiB/PID256과
apply30초/reader3초/lock1초는 변경하지 않는다. 이 수정은 원 setup 실패의 원인을
확정하거나 제품 장애를 재현했다는 주장이 아니다. 두 리뷰 후 새 namespace로 한 번만
재시도하며, 실제 재현 전 제품 수정은 하지 않는다.

## 두 번째 시도의 strict 입력 실패와 순수 준비 확인

정확47c83b81의 한 번 재시도는 schema432와 setup을 통과했지만1FAIL/45.29초였다.
원천 artifact에 reader fixture의 frozenset Geo tokens를 그대로 넣고 observation Stats만
별도 set으로 만들어 strict codec이 정상 거부했다. 예약 root/member 준비 뒤 artifact 등록·
plan·선택stale·reset에는 미도달했다. 원 result SHA256은
`66e16db6c6cca38da9501d72267171b7eb9b1c5a4f256e964b9582c4a99ae99d`이고
exact CID·volume1·label0 cleanup PASS와 원 log/XML을 보존한다.

기존 donor와 똑같이 Stats의 builtinset을 GeoLoadContext에도 연결하는 fixture만
고쳤다. strict validator·제품 코드·상한은 변경하지 않았다. 실제 test coroutine 준비 부분을
DB scheduled/registration만 대체해 실행하고 실제 artifact/context encoder와 decoder를
왕복했다. PG0의 순수 준비는0.0182초에 통과했으며 원장 SHA256은
`870bdba44be4ab2a1a2231a78dbdceae56a2af367cef024c77b163893694ccfb`다.
이는 본문의 plan/apply/reset 재현 증거가 아니다. 새 source 두 리뷰 뒤 같은 상한으로
한 번만 격리 실행하며 제품 오류의 실제 재현은 여전히 미완이다.

## 실제 재현 수용과 첫 제품 구현

정확ea2fbcc5의 세 번째 owned 실행은1PASS/skip0/25.52초다. 실제 canonical
Airport plan의 Feature revision을 낡게 하여 정확40001, apply transaction의 aborted,
READY 유효 lease·원 artifact/control 불변, 기존 reset의55P03을 차례로 관찰했다.
원 result SHA256은
`fb7262794f53b24e355e4aa34df1d189dcd5bfcc4c79f8e99c4ae8439066060c`다.
12개 산출물 hash·source2584·실제 선택 import60·SDK53 source 전후·CommonAA19
4지점 전후·exact CID/익명 volume1/전체 label0 정리를 확인했다. SDK는 import/bytes
검증이며 upstream 호출 검증이나 운영 성능 측정이 아니다. 앞선 두 실패는 보존한다.

첫 제품 checkpoint는433 additive typed READY reset, startup SD/ACL 정본 등록과
Airport/Rest 실제 catch 결선이다. SQL은 원 scope/attempt/control 잠금 뒤 현재 executor
lease/generation/fence, exact binding·prepared/READY·미적용 및 scope epoch/owner를
검사한다. 기존 expired reset은 그대로 두고 계획 단계의 오류는 그 경계를 사용한다.
새 reset은 atomic apply await가 선택 stale로 빠져나와 전체 rollback된 catch에만
연결하며, fresh read의 새 plan을 정리하지 않고 원 apply plan을 명시 전달한다.
ACK 불명/rollback 실패/다른 오류에는 새 reset 권한을 주지 않는다.

생산 SDK/Feature DTO·provider converter·기존 심볼 signature는 바꾸지 않는다.
새 typed 함수/client 함수와 기존 catch/inventory 내부 배선만 추가하며 기존 caller는
정적 검색과 실제 재현 경로로 확인했다. codegraph의 signature/core DTO 변경 요건에
해당하는 기존 signature 변경은 없고 전수 호출 그래프 완료라고 주장하지 않는다.
제품의 새 PG 회귀·독립 두 리뷰·CI는 아직 미완이므로 추가 실제 실행/운영 변경은0이다.

### schema433과 혼합 binary의 경계

새 public SECURITY DEFINER 함수는 현재 runtime의 exact SD/ACL 목록에도 포함한다.
이를 모르는432 binary가433 DB에서 재시작하면 unexpected SD surface로 startup이
거부될 수 있다. 그 보호 검사를 완화하거나 함수 권한을 숨기지 않는다. 공식 pair의
drain·schema/image 동일 generation 전환이 필요하며 기존 실행 worker를 남긴 채
혼합 활성화하지 않는다. schema는 forward-only이므로 DB433 이후432 image만으로
되돌리는 방식은 수용 범위가 아니다. profile OFF도 이 startup 계약을 우회하지 않는다.
현재 새 운영 절차나 배포는 실행하지 않았고, 새 함수와 runtime 기대값/구기대값의
권한 거부를 실제 격리 PG에서 검증할 예정이다.

## 첫 제품 순수 회귀

새 migration owner/CREATE window·짧은 timeout 보존·ACL/optional433, 양 client의
원 plan 전달·foreign fresh binding 사전 거부·reset commit ACK 유실, 실제 두 runner의
계획오류/atomic 오류 분리를 포함한 집중 순수138개가16.80초에 통과했다. 첫 호출은
ledger 파일 경로 오기로 수집0/exit4였고 원 로그를 보존한 뒤 올바른 경로로 실행했다.
이 결과는 새 SQL을 실제 PG에서 적용하거나 수집 성능을 측정한 증거가 아니다.
다음은 live apply holder, 현재/옛 executor·binding·취소·권한·혼합 schema와 실제
수집 재계획/원 결과 replay의 통합 source 및 두 독립 리뷰다. 운영 변경은 없다.

### 공식 Manager의 forward 재시도와 no-op 구분

검토한 Manager aeb2의 pair 실패 경로는 새 runtime 중지와 in_progress 보존 후
명시적 forward 재시도이며 자동 구 image rollback이 아니다. rebuild_pinned_runtime의
기존 schema_heads 비교는 같은 committed pair의 수렴 fast-path에 한정된다. 새 pair나
in_progress는 기존 DB identity를 보존해 full forward deploy로 진행하므로 frozen432
metadata 자체가 호환433 재시도를 막는다는 근거는 없다. 별도 Manager 수정은 이 증거만으로
추가하지 않는다. 433 migration 후 구0d60 재시작이나 pin metadata 되돌리기는 DB 복원이
아니며, 같은/호환433 pair의 forward 재배포가 복구 경계다. 실제 운영 전에는 새 source의
433 expected head 자동 발견과 부분실패/재시도 계약을 다시 확인한다.

needs_read는 attempt/control/scope의 timestamp까지 영속 변경0과 source DML0을 뜻한다.
공용 scope helper 안의 INSERT ON CONFLICT DO NOTHING SQL 문장까지0이라고 하지 않는다.

## 제품 통합 실행 전 checkpoint

계획 단계뿐 아니라 양 provider의 반복 선택 atomic stale도 MAX3에서 종료하는 순수
회귀와 기존 더 긴 timeout을 cap으로 줄이는 migration case를 추가해142개/14.08초를
통과했다. 실제 통합 source는 원 기록의 복구 기대값1개와 실제 두 asset2개, READY
needs_read·원 binding/fence·executor lease·canonical 취소·foreign epoch/owner·active
apply holder10개, 별도 작성한 catalog/권한/startup3개로 총16개를 수집했다(10.54초).
새 제품의 실제 PG는 여전히0이다.

실제 caller는 canonical operation/membership·DagsterInstance/guard를 사용하고
등록된 bytes를 SDK0로 읽는다. 새 generation의 최초 apply만 Feature revision을 낡게
하고 실제 catch→typed reset→새 plan→원 결과/postprocess/seal을 통과시킬 source다.
완료 전 reset 거부와 완료 replay의 전체 작은 fixture 상태 불변도 검사한다. 기존
quota를 줄이는 Airport 준비 helper는 쓰지 않고 fresh16/4/8MiB 정책을 유지한다.
owned 실행은 두 실제 caller를 legacy 등록 helper를 쓰는 case보다 먼저 준비·수집하며
한 모듈/한 PG로 원 test함수를 실행할 작은 selector를 별도 검토한다.

별도 ACL 파일은 원 작성자와 source를 교차 읽었고 cold setup marker35만 기존50으로
맞췄다. 구432 SD 기대집합만 모사하는 실제 catalog 검사와 전체 구 binary 기동 검증을
구분한다. 최종 두 source 리뷰·소유 PG·CI·현재main 합성은 아직 미완이다.

## 실행 전 발견한 scope 열 권한과 관측 범위 정정

초기433 source의 CommandOwner는 기존 scope helper EXECUTE만 가지므로 새 직접
scope SELECT에 필요한 권한이 없었다. 실제 제품 PG 전에 정적으로 찾아 SELECT를
epoch/owner 두 값으로 좁히고 WHERE의 provider_dataset_id까지 세 열의 SELECT만
433 migration과 해당 함수 존재 시의 schema-owner ACL에 추가했다. lease 열/UPDATE·
전체 table SELECT·runtime의 직접 표 권한·기존430 frozen ACL은 늘리지 않는다.
실제 ACL source는 다른 열의 CommandOwner 읽기와 service 직접 scope 읽기42501도
검사한다. 이 제품 delta 뒤 순수142개/14.45초와 통합 수집17개/10.38초가 통과했다.

replay 증거는 작은 fixture의 row/timestamp·원 receipt 불변과 실제 native apply
진입 호출이 추가되지 않았다는 값이다. SQL DML 문장 수를 직접 계측한0이라고
기록하지 않는다. needs_read 시험은 성공 reset을 commit한 뒤 같은 인자로 재호출한
idempotence 경계이며 실제 TCP 응답 유실 주입은 아니다. 취소 시험은 canonical 취소를
먼저 commit한 뒤 거부되는 경계다. live holder는 실제 begin_apply의 scope/attempt
잠금과 rollback을 검사하며 그 holder 안에 전체 source DML을 넣었다고 하지 않는다.
전체 source apply/postprocess/seal은 별도의 실제 두 caller case가 담당한다.

owned 실행 후보는 실제 두 caller→현재/외부 owner·lease·취소·holder10개→ACL/startup4개,
총16개다. 기존 legacy 거부+새 typed 복구 회귀1개는 정상 CI에서 별도 fresh 모듈로
유지한다. 새 제품 PG·최종 두리뷰·CI는 여전히 미완이다.

## 첫 제품 owned16 실패와 canonical head 교정

정확3c2aa48의 첫 제품 PG는14PASS/2FAIL(22.46초, XML16/skip0)이었다. 양 실제
caller2와 race10 및 ACL2는 통과했지만 catalog `prokind`의 PostgreSQL 내부 char가
asyncpg에서 bytes로 반환됐고, 설치 graph JSON이432에 머물러 실제433 DB의 public
startup이 fail-closed했다. strict inventory 메시지는 head 불일치 뒤 검사를 건너뛴
초기값이며 별도 guard 손상으로 판단하지 않는다. 원 result SHA256은
`ee26013418b5f16e3e8d03892de4354cb54bfe89dd6699248cfb8f382f85f4a3`다.

정확 CID 부재·익명 volume1 부재·scalar label0 정리는 통과했다. pytest exit1에서
runner가 중단돼 source-after/SDK-post/runner Common-after는 실행되지 않았다.
있는 source-before/SDK-before/실제63imports 및 pytest Common-before/after 증거를
전체 전후 수용으로 확대하지 않는다. 원14artifact와 실패 log/XML은 그대로 보존한다.

catalog 조회를 `prokind::text`로 정규화하고 기존 generator의 `--write`로 graph에433을
반영했다. 기존 artifact-currentness 시험을 확장해 실제 versions의 유일 head와 startup
및 Manager candidate CLI의 계산이 같음을 검사한다. 새 hardcoded head나 guard 예외는
없으며 공식 candidate consumer/시작 검사 코드는 바꾸지 않는다. 제품 source·adapter
두 리뷰 후 같은 상한으로 한 번 재시험하며 그 전 전체 제품 PASS로 세지 않는다.

교정 후 기존 graph-currentness/single-head·n150 candidate 소비 계약과 typed reset/양 runner
순수 회귀145개가25.70초에 통과했다. graph `--check`·Ruff도 통과했으며 첫 Ruff의
두 차례 E501은 수정 전 원 log로 보존했다. 제품 PG 재시험은 아직 실행하지 않았다.

## 교정 source6c의 실제 제품16 수용과 CI 경계

동일 자원·시간 상한의 단일 재시험은16PASS/18.90초(XML16/skip0, JUnit18.304초,
runner27.169초)였다. 원 result SHA256은
`8b4bff8295ab9229001f67747a917124f718e0085196024a9f1537e19099ddf6`이다.
양 실제 caller는 계획2회/reset1회·같은 artifact bytes·현재generation2·정상 후처리와
seal·applied reset 거부를 증명했다. 완료 replay의 작은 원천 rows/receipt는 불변이고
native apply 진입 추가0이며 SQL문장 전체0을 계측했다는 뜻은 아니다.

13개 원 산출물 SHA·2591개 Git mode/blob·실제63 import를 검산했다. 이번 성공에서는
source 전후/SDK53 전후/실제 Common19 네 지점 모두 실행됐다. 정확 CID 부재·익명
volume1 부재·전체 scalar label0 정리도 통과했다. 실제 관측 범위는 local owned PG이고
운영 ARM의 성능·CPU/RSS 감소, TCP ACK 유실 주입, 동시 cancel DML은 증명하지 않는다.
앞선 재현/제품 실패와 setup/fixture 입력 실패는 원장 그대로 유지한다.

동일 source의 정적 검사는 Map mypy196개/Dagster48개 및 import250개·1790의존성의
4계약 전부 통과했다. fresh CI Python3.12는 resume225280B 상한과 ACL인벤토리의
시그니처 리터럴 금지 계약 두 곳에서 실패했다. 실제 제품16 성공과 전체 CI green은
분리하며 원 CI log를 보존한다. 완전한 과거 resume 세 section9620B는 원문 그대로
[archive](../archive/resume-2026-09a.md)로 옮겨 상한을 복구했다.

## CI ACL 선언·문서 상한 교정

시그니처 리터럴 금지 fence는 유지한다. 새3열 scope grant의 조건은 기존 catalog
resolver 관례대로 정확 namespace/name과 function kind 존재 검사로 바꿨다. resolver가
해당 이름의 유일성을 검증하고433 이전 함수 부재에서는 grant를 하지 않는다. 기존
expired reset·frozen430·3열 범위·startup guard는 바꾸지 않았다. 기존 ACL4번째 시험에
함수 catalog 부재·열권한 회수 후 gate가 권한을 추가하지 않고 전체 rollback으로
함수/권한이 복원되는 관측을 더했다. 이는 전체432 DB/구binary 실행이 아니다.

시그니처 fence·typed reset·archive link/크기 순수35개9.73초와 ACL4개 collect-only
4.66초/Ruff가 통과했다. source6c 제품16의 실제 성공은 이 추가 gate 변경까지
승계하지 않고, source/adapter 두 리뷰 뒤 동일 상한 단일 재시험과 fresh CI를 요구한다.

## f29 전체 glibc CI의 oracle 형식 실패

f29의 전체 glibc 통합 시험은1952PASS/23skip/1FAIL(1432.69초), coverage87.64%였다.
실패는 `test_head_schema_artifact_matches_head` 하나이며 정본 `dump_head_schema`가
내보낸 complete diff는 scope.owner의 SELECT grant 뒤 초과빈줄1개뿐이었다. 원 log
SHA256 `49817e0a28885f9efba8b53c2c2c13de8b78e14423daef8bdc6c44c79c6a4ad5`와
job 원장을 보존했다. 정본 live dump 차이 그대로 빈줄1개만 제거하며 parser/비교/fence를
완화하지 않는다. 함수 body·migration·runtime Python·API·UI 코드는 바꾸지 않았다.

독립 local16의 성공은 f29 source 실측이고, 별도 후보 UI14도 f29 build에서 실제
통과했다. 최종 oracle-only head로 수용하려면 전체 코드/입력 동등성과 두 리뷰를
확인해야 하며 새 head를 실제 실행했다고 쓰지 않는다. 새 exact head CI10과 양PG가
통과하기 전 정상 머지는 보류한다. 실행 중인 alpine을 취소/재실행하지 않는다.

## alpine 관찰자 cold-codec 실패의 최소 교정

alpine 전체 CI는1945PASS/29skip/2FAIL(1780.79초), coverage87.62%였다. 추가 실패는
기존 two-writers의 airport 선행 case에서 관찰자 `_exact_blocker`였다. 원 log SHA256은
`8c45e9601e17b5b6f12bddafb9dbbe7f390c06df00f229d2b8bbc2db2b025853`이다. 원 stack은
관찰 SELECT 본문 전에 asyncpg0.31의 int4[] cold-codec introspection/JIT 설정 조회에서
300ms statement timeout을 보고했다. 제품 writer 오류나 pg_locks 본문 비용으로
단정하지 않는다. 두 source apply 완료 barrier는 통과했지만 최종 commit 관측 전에
실패했으므로 해당 case 전체 성공으로 세지 않는다.

SQL에서 exact holder의 `ANY(pg_blocking_pids(...))` membership을 bool로 반환하고
Python은 `is True`로 검사해 배열 codec을 요구하지 않도록 한다. PID/backend_start/
login·Lock·ungranted·holder identity를 모두 유지하고 SQL300ms/outer0.8초/worker1초와
재시도 정책도 그대로다. 관찰비용 개선은 아직 실측하지 않았으며, 두 source 리뷰 뒤
원 airport/rest case 두 개만 같은 소유PG 상한에서 실제 확인한다. 이 test-only 교정과
oracle 빈줄 외 runtime/API/UI/migration code는 변경하지 않는다. 새exacthead 전체CI와
최종 후보 UI 검증까지 기다리며 기존 실패를 덮어쓰거나 통째로 재실행하지 않는다.

정적 영향은 `_exact_blocker`를 쓰는 two-writers·gc-race·registration 세 시험 모듈이며
반환 wait_event 문자열/서명은 유지한다. Ruff/format과 원 pair2 collect-only는 통과했다.
앞선 local PG의 driver는 asyncpg0.32였고 실패한 CI는0.31이므로 이 차이를 숨기지 않는다.
후속 원 pair2는 ABI가 맞는 cached0.31을 private 경로에 고정해 실제 import version/
파일 hash를 확인하며 실행할 계획이고, 아직 실행/원인제거 실측은 하지 않았다.


## 정확6611의 최종 CI·실제 UI·정상 머지 수용

제품 최종 source는6611af8aaff17647fcc172049b4046ce5f5b2cd9다. 이 커밋의 CI10개가
전부 성공했다. 전체 glibc PostGIS는1953PASS/23skip/1446.98초, alpine은
1947PASS/29skip/1802.93초이며 coverage는 각각87.64%/87.62%다. 새 통합4모듈의
17개는 필터 없는 전체 suite 성공과 완전한 skip 목록에 해당 모듈이 없음을 함께 확인했다.
이는 포함·성공의 근거이며 개별 case PASS event를 출력한 로그라고 표현하지 않는다.
f29의 oracle1FAIL·alpine2FAIL, 앞선 setup/입력/제품14PASS2FAIL은 그대로 보존한다.

최종6611의 기존 writer pair 두 case는 CI와 같은 asyncpg0.31을 ABI가 맞는 private
경로에 고정한 소유 PG에서2PASS/19.81초였다. 양 선행 순서의 exact blocker·미커밋
중첩·정상 결과와 seal을 확인했고, source2592/실제63imports/SDK53 전후/Common19
네 지점/정확 CID·익명 volume1·scalar label0 정리를 검산했다. 원 result SHA256은
15f0ec421f8412c315018c6345351ef51886f008fbd13ec24bb28c75787dd634다.
관찰 조건300ms/0.8초/worker1초와 자원 상한은 유지했다. 배경 회귀와의 정확 겹침이나
CPU/RSS·속도 개선율을 측정한 시험은 아니다. f29 owned16은 그 source의 실제 검증으로
구분하고, 변경 없는 제품 runtime947개 mode/blob 동등성과 최종 exact CI를 따로 남긴다.

최종 후보 UI는6611 실제 API/default pool·새 DB433과 f29에서 새로 빌드한 UI를 사용했다.
UI 입력350개의 mode/blob 및 빌드 source 전체2592개를 검산해 source와 build source를
구분했다. 마지막 단일 실행은 실제14 case PASS, JUnit suite73.398초/case73.293초였다.
로그인1회·로그아웃1회·취소2회, 실제 WS2연결/16frames, 정확 세션 쿠키의 HttpOnly·
로그아웃 뒤 쿠키 부재, 같은 browser context의 보호 GET401, cleanup 보호 GET401과
미확인 세션 flag 해제, 5초 재연결 없음·보호 화면 재방문을 확인했다. 소유 DB·API/UI
unit·tunnel·browser/profile 정리는 모두 통과했다. 원 result SHA256은
aa431e0439e26e03f367bb82930aba5a8cc3bda0664ab6c1dbfca3bfc8e87adb다.
이 후보 시험은 운영 공개UI 수용을 대신하지 않는다.

그 앞6611 후보 실행 세 번은 각각 helper75초 내 driver 결과 미회수, 별도 SSH readiness
8초 timeout으로 browser 미진입, readiness200/200·9case 뒤 logout navigation의
응답 body 완료 latch 거부로 실패했다. 세 원 실패와 각 자원 정리는 보존한다.
별도 SSH handshake를 합쳐 같은 두 GET의2초/200 조건을 helper75초 안으로 옮기고,
로그아웃은200 headers 관찰 뒤 실제 쿠키 삭제·보호401로 검증했다. 전역 navigation 오류를
삼키거나14조건·인증·75/15/100/190/210/220초의 나머지 한도를 완화하지 않았다.
세 실패의 미확인 세션 flag를 실제 유효 세션이 남았다는 확인으로 바꾸지 않는다.

두 source 리뷰·별도 실제 결과 검산 뒤, 최신 main/정확 CI head/유일 Alembic433 및
prospective tree를 다시 확인해 #1424를2026-10-27 13:29:37 UTC 정상 머지했다.
merge는c3adc0c695160c13bd6bb0bc291e01629d97fc8a, 부모는 원 main3ca5b61과
정확6611이며 tree36a80acf5b15820714ef90d57f9ea5906d8d1ebc가6611과 같다.
관리자 강제·force·브랜치 삭제는 하지 않았다. 이 정산 PR은 문서만 바꾸며 코드 PR의
exact-head CI를 문서 CI 면제로 대체하지 않는다.

### 문서 P3와 아직 남은 운영 경계

원 archive 생성 커밋의 committed diffcheck는 마지막 빈줄 때문에 exit2였다. 당시의
unstaged diffcheck PASS를 새 파일의 committed-delta PASS로 확대할 수 없어 이 차이를
명시한다. 후속 문서 정산은 원 archive9819B prefix(그 안의 본문9620B SHA256
2393a1b9f660c39dae4c9a592611a8f654d1bcb7064e4270d383664455f58a83)를 그대로
두고 navigation footer를 뒤에 붙여 EOF 경고를 닫는다. 기존 역사 본문은 삭제하지 않는다.

운영 image/schema 전환·공개UI 수용은 아직 미완이며 별도 증거 뒤 추가 정산한다.
433은 forward-only이고432 image/pin만 되돌리는 것은 DB 복구가 아니다. 전체 writer
전환·T-CWRITE-01~09 완료, profile 활성화, 운영 ARM CPU/RSS 저감은 선언하지 않는다.


## 현재 배포 포함·원51복구·공개 UI13 수용

2026-10-27 후속 관측에서 현재 배포는 Map001487ee/PinVid204d2b4/Managerd1468213다.
Map001487의 선조에 정확6611이 포함되고, 두 Map 소스 사이 제품 코드는 같으며
문서4개와 auth 시험만 달라 별도 구6611 이미지를 다시 배포하지 않았다. 저장소
최신 main82bcb2c는 이 배포 뒤 PG18 백업/bootstrap 후속이다. 실제 배포001487과
저장소 최신82b를 같은 release라고 쓰지 않으며82b의 운영 배포도 이번 수용 범위가 아니다.
외부 유지보수의 PG16→18 전환과 현재 pair 배포는 이번 작업자의 공식 rebuild 실행으로
계수하지 않는다.

현재 공식 상태는 committed transaction a1f775ff, 실제6 image와 healthy 상태가
일치한다. 실제 API role의 읽기 전용 조회에서 Map433_snapshot_ready_plan_reset과
PinVi20260917_0102를 확인했고 Map packaged head도433이다. 오래된432 expected head,
PG16 system identifier, 이전 Manager bundle을 현재 복구에 적용하지 않았다.
433은 forward-only이며 구 image/pin 복귀가 DB 복원이라는 의미는 여전히 아니다.

### 중지 실패와 원상복구 범위

첫 pin 명령은 CLI의 사람용 접두문 뒤 JSON을 wrapper가 통째로 해석해 실패했다.
후속 읽기 검산으로 pin 적용을 확인했으며 재회전하지 않았다. 첫 직접 pause의
SSH255와 뒤 durable pause의 ContractError도 성공으로 바꾸지 않는다. 후자는 실제
Map37개만 STOPPED로 바꿨고 failure sensor 하나는 RUNNING이었다. 당시38개 변경이나
첫 PinVi 경계 실패라는 초기 추정은 철회했다. 기존 전체67 원복과 자기 unit 정리를
끝낸 뒤, 별도 검토한 유한 convergence가 원 RUNNING51을 중지했고 재STOP은0이었다.
소스 검토에서 상태 덮어쓰기 가능성은 확인했지만 이번 실행에서 주체·최초 실패 원인을
입증하지 못했다. 특정 STOP ACK 뒤 재RUNNING을 실측했다고 단정하지 않는다.

그 후 별도 유지보수로 Manager/Map/PinVi와 공용 PG가 바뀌어 옛 bundle은 재실행하지
않았다. 현재 committed 상태·schema·runtime와 원 key/ID를 읽기 검산하고 두 독립
소스 리뷰를 거친 작은 복구가 원 RUNNING51만 재시작했다. 원 MapSTOP13과 외부
Concierge3은 보호했다. 정상 ACK가 불명확하면 재시도하지 않는 원 transition을 재사용했다.

실제 복구 unit은17:51:55→17:52:14 UTC에 exit0/PID0으로 끝났고 원67상태를
10초 간격 두 번 확인했다. 독립 fresh 읽기에서도 Map38RUNNING/13STOPPED,
PinVi13RUNNING/Concierge3RUNNING과 모든 key/ID가 원본과 같았다. 실제11 runtime,
공식 committed 상태와 환경 bytes는 전후 같았다. 복구 원 result SHA256은
95c4a79f2a06f4ff4bebf78803ca3b844a4aa3908e1096459bbc2a996b23e2d5,
독립 fresh 원장은25921e696431e4e28ab877a566049466402ccc977dc6ca539f22ecf625c45e01이다.
Root 최종 수용과 자기 unit 정리 원장은 각각
b83d3e184ed8e6bf09ebd9e6913b502ea08b4eb43da63bc48480db27265e6ba2,
44959823a50c3fc31b124a386bce272e9a3657adb5d1d4cf4c54b44942620939다.
제품 배포나 PG rollback은 하지 않았다.

### 현재 공개 UI와 남는 한계

최신 pair의 실제 공개 HTTPS 검증 한 번은45.225초에 Map7+PinVi6 전부 통과했다.
Map은 인증 전401→로그인200/HttpOnly·Secure→hydration→실제 canvas·표·상세·reload→
로그아웃200/보호401을 확인했다. Common 로그인의 SSR disabled→hydrated enabled도
실제로 관찰했다. PinVi는 인증·쿠키/reload·VWorld canvas/성공 타일21개·목록/필터/DTO·
같은 source lineage 상세·로그아웃204/보호401을 확인했다. 각 로그인/로그아웃1회이며
blocked request·page/hydration error는0, 미확인 세션 flag는 false였다.

소유 browser process 부재·profile 제거·SSH exit0과 실제7서비스 전후 key/CID/image/
source/start/restart/health 전부 동일, 실행 모듈106개·Node/Chromium 전후 동일을
확인했다. 운영 business 쓰기는0이며 허용된 auth/session/audit 쓰기와 구분한다.
원 UI result SHA256은9508dfc25e3dfb4b2e573c0238fabce6abb2559d4f464d7ca5f1fc826f85e74a,
독립 수용 원장은debe5d4f6a8c10279bb7c1fd4b35e63391a20afed7ffa23eed3c89ada862b414다.
별도 최종 수용은3dd739a4c4b0c9dc622d37b0e4bdcb165db8dde87fe7c8f930738c5e5c0afc75다.
이는 현재 공개 읽기13개 수용이며 후보 취소14개나 전체 writer/장애/실부하 시험을 대신하지 않는다.

이번 문서 정산은 최신 main을 정상 흡수하되 제품·시험·schema·tasks를 바꾸지 않는다.
T-CWRITE-01~09는 모두 미완이고 CWRITE profile flags는 OFF다. 일반 coordinator와
전체 writer 전환·운영 ARM CPU/RSS 저감은 수용하지 않는다. ADR117의 제안과 별도
후속 작업은 이 제한된 typed 복구 완료와 구분한다. 원 실패·미측정 항목 및
source/build/운영 release의 구분을 보존한다.
