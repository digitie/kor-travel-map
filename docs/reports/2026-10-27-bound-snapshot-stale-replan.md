# bound snapshot의 정확 stale 뒤 재계획 복구

## 첫 범위와 아직 미재현인 경계

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
