# Airport 예약 asset의 SDK0 배선

## 첫 작은 checkpoint

Root 수용 native apply078ba765와 gateway60565·관측7410·후처리6304를 포함한
부모ab10989 위에 client 전용 TX 파일과 순수 시험을 추가했다. 현재 source는
복구 read/register/claim/seal의 작은 I/O 경계만 구현한다. 실제 Airport entry,
plan/apply/postprocess 연결은 아직 없으며 수집 경로를 바꾸거나 활성화하지 않는다.

모든 새 함수는 원 unbound client만 받는다. queue executor에 결합된 client는
session을 열기 전에 거부한다. client가 READ COMMITTED TX의 시작·commit·rollback을
소유하고 Dagster/infra가 commit하지 않는다. 전체30초, statement30초/lock1초를
상한으로 두며 기존 더 짧은 서버 설정을 보존한다. lease는300초 한 값이다.
RR read-only 준비용 내부 경계는 statement3초를 사용한다.

runtime pins가 없는 경우에도 먼저 canonical member SD에서 실제 부재를 확인한다.
등록 존재/비정상 반환은 오류이며 legacy 적재로 바꾸지 않는다. 정상 pins의 읽기는
기존 gateway를 재사용하여 원 artifact/context/result와 정확한 상태를 한 번 읽는다.
등록/claim/seal은 기존 typed SD를 그대로 호출한다. duplicate 등록·lease 시각을
새 권위로 승격하지 않는다. commit 응답 유실·DB 오류·취소는 그대로 전파하며
내부 자동 재시도나 candidate 결과 반환은 없다.

독립 순수16개가5.53초에 통과했고 Ruff2파일/strict mypy1파일을 통과했다.
실제 Task.cancel, commit 응답 오류, 각 단계 오류, bound client의 SQL0,
명시 runtime 부재의 등록 존재/부재를 대조했다. DB와 session은 대역이며
실제 rollback/서버 lock 해제·PG/권한 수용은 아니다.

## 런타임 pin과 다음 배선

기존 Docker build는 `KOR_TRAVEL_MAP_GIT_COMMIT`을 OCI revision과
`KOR_TRAVEL_MAP_IMAGE_REVISION`으로 공급한다. 현재 WT HEAD를 런타임에서 읽는
fallback은 두지 않는다. Python `uv.lock`이나 SDK inventory runtime 정본 파일은
현재 없고 provider surface manifest는 실제 installed inventory가 아니다.
Root가 실제 image revision/installed dependency·source inventory receipt를 검증해
명시 typed runtime으로 공급하는 경계를 맡는다. 누락된 hash를 상수로 대신하지 않는다.
새 등록 opt-in은 기본 OFF이며 기존 등록의 SDK0 복구 판단과 별개다.

첫 구현은 실제 tracked scheduled Airport만 대상으로 한다. 예약 run의 canonical
root/child/member는 guard의 실제 ensure mutation에서 고정한다. Airport run 첫
분기에서 SDK generator 소비보다 먼저 읽고, 미등록만 한 번 bounded EOF를 수집한다.
등록 전 미지원은 같은 입력으로 기존 EX를 사용한다. 등록 뒤에는 implicit EX/refetch가
없다. 실제 Root backend와 plan/apply/후처리/봉인 source 합성 후 독립 검토가 필요하다.

queue direct context에는 D root/child/member·run/retry guard가 없고 executor가
request/job을 잠근 외부 TX에 client를 결합한다. 첫 scope에서는 queue를 legacy EX로
유지하며 이를 SH 수용으로 세지 않는다. typed atomic seal commit 후 예약 wrapper는
기존 fresh member done→noop을 사용하므로 별도 완료 bool/외부 DTO를 추가하지 않는다.

신규 파일과 기존 Airport entry의 signature 불변 범위여서 Codegraph signature
영향도 평가 예외에 해당한다. 기존 converter/DTO/shared client/schema는 수정하지 않는다.
공유 journal/resume·설정·build·whole430 wrapper는 Root 소유다. 별도 PR·운영 변경은 없다.
실제 PG/전체430 설치·ACL·unknown commit 재개·원 run worker 종료·collector 배선/CI 및
운영 동시 쓰기 수용은 모두 미완이다.

## 짧은 서버 제한 보존

Root backend26c2e5를 상속한 뒤 client의 일반 deadline setter와 중복 cap SQL을
공통 `apply_bounded_transaction_limits`로 교체했다. 일반 setter가 기존의 더 짧은
lock timeout을 먼저 늘릴 수 있던 source 경계를 제거한다. RR은3초, 나머지는30초를
명시하고 기존 서버 값·호출자 마감·고정 cap의 최솟값을 적용한다. client 순수18개가
4.54초에 통과했다. 이 결과는 SQL 대역의 호출/제한 전달 검사이며 실제 PG 실행은 아니다.

## RR 계획과 RC 원 적용

client 전용 파일에 등록 입력의 RR evidence/순수 assessment와 같은 snapshot의 정본
membership 지문을 읽는 계획 경계를 추가했다. Feature revision·source head·membership의
3N manifest를 기존 kernel 함수로 작성하고, claim/seal/등록 binding은 한 RC TX에서
확정한다. lease300초/whole scope/SH 모드를 명시한다. 이미 binding된 ready plan은 원
attempt/owner/manifest를 재사용하며, 다른 상태나 입력 지문이면 새 attempt로 덮지 않는다.
J8d4c의 typed reset SD는 정확한 old attempt/owner/manifest와 현재 executor fence만 전달한다.
만료 판정과 reset/needs_read 결과는 서버가 결정한다. SD 설치는 전체430 합성 의존이다.

실제 적용은 Root의 기존 native apply를 새 RC TX에서 호출한다. native apply가 잠금 뒤
fresh427과 실제 decoded artifact/Geo 의미를 재검증하고 원14 counter+retired를 저장한다.
알려진 evidence race만 재계획 진단으로 구분하며, 다른 DB/입력 오류·취소·commit 응답
유실은 전파한다. 이 client 함수들은 EX fallback/SDK 재호출·자체 재시도를 수행하지 않는다.

기존18개와 새15개 순수 시험을 합한33개가3.18초에 통과했다. 정본 converter/codec/decoder를
사용한 전체 진단, 3N 내용, 한 TX binding 오류 rollback 경로, 기존 ready 재사용·불일치
거부, typed reset의 세 원 binding 값, apply 오류와 commit 응답 유실을 확인했다.
SQL/session/kernel 명령은 대역이며 실제 PG 수용은 아니다. Ruff와 strict mypy도 통과했다.
Dagster runner/첫 Airport entry 분기·SDK 수집/같은 입력 EX fallback·재계획 상한·최종 봉인은
아직 배선하지 않았다. 기존 asset와 모든 공유파일은 그대로다.

### 같은 executor의 reset 뒤 새 계획 key

Root 리뷰에서 a137의 key가 snapshot/executor generation만 사용하여 typed reset 뒤
새 attempt의 unique key와 충돌하는 P1을 확인했다. 기존 source 수용은 이 finding의
HOLD로 정정한다. 새 attempt UUID를 key에 포함하여 최대 generation에서도128B 안에 둔다.
claim/manifest/bind는 계속 같은 TX이므로 응답 유실 뒤에는 실제 SDK0 binding을 읽으며
새 무관 attempt를 성공으로 추측하지 않는다. 순수 DB 대역이 실제 unique key 중복을
거부하도록 한 반례가 수정 전1FAIL2.51초, 수정 후1PASS2.82초다. 같은 generation에서
reset 결과 뒤 새 plan key가 달라지는 것을 확인했다. 실제 reset/unique 제약 PG는 미실행이다.

## 예약 SDK0 runner의 첫 배선

원 Airport entry의 첫 분기와 그 asset의 runtime resource 한 key만 추가했다. 다른
asset/queue/일반 client의 동작은 바꾸지 않는다. 실제 schedule guard의 ensure 결과에서
root/child/member UUID와 frozen membership을 얻고, 현재 guard의 natural dataset resolver와
같은 exact membership을 확인한다. 원 unbound client·schedule만 지원하고 queue bound
client/직접 context는 기존 EX를 유지한다. verified runtime이 없어도 실제 artifact 부재를
먼저 확인하며, 기등록 입력은 pin 누락·불일치 시 실패한다. 새 시계·원천 iterator·Geo 소비는
이후다. 별도 DB profile 권위를 발명하지 않고 등록 전 실제 입력의427 RR assessment로 판단한다.

새 strict 입력은 원 converter/Geo reuse로 한 번만 소비하여 전체 EOF를 관측한다.2730개와
기존 typed1MiB budget 안에서 Transport 정본 presence를 별도 복사에 부착한다. 원 EX tuple은
그대로 보존한다. 상한 초과는 소비한 prefix와 남은 iterator를 이어 기존 EX loader로 넘기며,
전체 입력의 codec/관측/assessment 미지원도 같은 원 tuple을 EX로 보낸다. EOF 오류는 등록이나
재수집으로 바꾸지 않는다. runtime/관측 bytes 등록 뒤에는 EX fallback과 SDK refetch가 없다.

등록 token을 첫 claim의 previous로 전달한다. 기등록 prepared는 원 tuple로 계획·apply하고
반드시 저장된 원 result를 다시 읽는다. applied/postprocessed는 원14+retired·관측 generation·
fetched_at·validation·GeoStats를 복원하여 Root backend 한 sameTX coordinator와 atomic seal에
넘긴다. durable child_sealed는 실제 저장 receipt와 원 bytes의 일치를 재검증하여 효과 없이
재생한다. 기존 scheduled wrapper의 fresh done→noop은 전체430의 client 두 RC 설정이 전제다.

kernel은 기존 CONSTRAINT 없는40001 RAISE의 정확 message 집합만 typed replan으로 구분한다.
임의40001·다른 constraint·연결/commit 불명·stale executor는 여기에 포함하지 않는다. replan은
SDK0 read→exact old binding reset→read 뒤에만 계속하고 최대3회다. 아직 active인 plan의
55P03은 전파하여 lease를 기다리는 기존 step 재시도로 남긴다. fence 검사 전 old owner cancel로
우회하지 않는다. stale executor/원 입력 불일치·superseded는 공식 nonretryable Failure로
올리며 기존 run wrapper가 실패 attempt를 기록한다. 취소와 commit 불명은 원 예외로 전파한다.

quota 정리는 실제 부재+verified runtime+새 strict 입력에서만 fetch 전 독립 RC TX로
`collect_expired_provider_snapshots(16)`을 한 번 호출한다. 실제 terminal+7일·ledger 판정은
기존 SD 권위다. 기등록 복구/기본OFF/queue는 GC0이며 무한 drain·새 maintenance job은 없다.
GC 실패는 등록/SDK 전에 전파한다.

이 source의 client/runner 순수67개가6.92초, 기존 definitions/Transport fetcher/HTTP timeout
51개가8.52초에 통과했다. DTO·codec·관측·후처리는 정본을 사용하지만 DB와 SDK 호출은 대역이다.
원 시각·generation·기등록 SDK0·첫 token·EOF/fallback·취소·commit 불명·reset 상한/GC 경계를
검사했으며 실제 DB effect·SH 실행·전체 run 완료를 증명하지 않는다. Ruff와 strict mypy를
동기화한다. assets의 원문은 선언한 첫 분기와 resource key를 역제거하면 AST 전체가 같다.

Root native apply의 새 fenced capture 권한 seam, shared430/migration/ACL·client RC/API RC·
실제 root/member lifecycle을 최종 상속해야 한다. source 두 적대 리뷰·actual PG SDK0 재시작/
fresh capture·후처리/seal·unknown commit·whole-worker death·전체 CI/운영 수용은 아직 미완이다.
현재 배포·설정 활성화·PG 실행·새 standalone PR은 없다.

실제 `_geo_load_context`는 `GeoCallStats.observed_data_tokens`의 builtin set을 그대로
참조하므로 이 경로에 frozenset 변환은 없다. 정본 Geo tuple을 이 helper로 조합하여 codec과
observation을 함께 통과하는 회귀를 추가했다. 기존 asset retry 정책은3회·60초·exponential로
실제 설치 Dagster의 `calculate_delay(1..3)`가60/180/420초(누적660초)를 반환하여
300초 lease 만료 뒤 세 번째 재시도 기회를 제공한다. 정적 수열 가정과 달라진 실제값을
순수 회귀로 고정했으며, 지연 수치에 대한 첫 반례1FAIL은 보존한다. 별도
RetryRequested·지연 확대·새 주기는 추가하지 않는다. 일반 lock timeout/unknown commit을
lease busy와 동일시하지 않으며 stale fence의 nonretryable 분리는 유지한다.

## 실제 caller 회귀 source checkpoint

합성 `3f5983244d0e0ff6a413af3f20e2b4b825b6dded` 위 신규 integration 파일만 추가했다. 첫 사례는 실제 ephemeral Dagster의 STARTED run/event와 schedule tag, 실제 resolver/guard 및 public tracking wrapper를 사용한다. 원 converter·저장 Geo 재사용·427 진단·등록·계획·apply·후처리·atomic seal 뒤 동일 run의 retry 번호를 바꾸어 SDK/Geo/새 시계 금지 sentinel로 원 bytes·결과·관측 세대·cursor·완료 행의 재사용을 확인하도록 작성했다. SDK 입력은 synthetic 한 행이며 설치 image runtime receipt·실제 SDK HTTP·worker 강제 종료의 증거가 아니다.

둘째 사례는 같은 설치의 공개 client plan/reset 경로로 첫 ready attempt의 **자기 lease만** 관리자 fixture에서 만료시킨다. 기존 cancelled attempt를 보존한 채 같은 snapshot generation/fence에서 새 attempt/owner/idempotency key가 실제 unique 제약을 통과하는지 확인한다. 완료 attempt를 reset하거나 epoch/결과를 재작성하지 않는다. 각 사례의 실패 원문은 유지하며 아직 ready인 자기 plan만 정리한다.

새 2개는 collect-only 2건/5.14초와 Ruff를 확인했으며 **실제 PG는 아직 실행하지 않았다**. runner 제품 7개 파일·공유 schema/ACL·기존 fixture는 변경하지 않았다. 두 source 검토와 소유 harness/CPU 슬롯 이후의 실제 결과를 별도로 정산한다.

## 실제 caller2 원장 — source5717

고정 `5717bf78008caae206e6bacc73e24e4fa94d9d0d`의 소유 단일 PG 실행에서 위 2개가 모두 PASS했다. XML 2/0 failure/0 error/0 skip, suite 17.210초(각 16.061·1.106초), pytest 요약 18.12초, 전체 자원·정리 포함 32.267초다. 실제 head430/service role/PG16.14·en_US.utf8를 관측했고 Git 2,500개 mode/blob 및 SDK53개 전후, 실제 project import32개를 대조했다. 정확 CID 부재·해당 UUID0·scalar label0·소유 anonymous volume1 부재를 확인해 PG/CPU 슬롯을 반환했다.

첫 시험은 실제 scheduled canonical guard와 전체 client 배선을 거쳐 child sealed 뒤 동일 run의 retry9 재진입에서도 retry2의 원 observation generation·clock·GeoStats·artifact/result/receipt bytes·cursor와 완료 상태를 유지했다. 둘째 시험은 executor generation1/fence를 유지하고 첫 cancelled attempt 행을 보존한 상태에서 다른 새 attempt/owner/idempotency key를 실제 unique 제약 아래 생성했다. 원 SDK 입력은 synthetic 공항1행이고 저장 Geo 재사용 경로이며, 실제 SDK/Geo HTTP·배포 image receipt·worker 강제 종료·두 dataset 동시 쓰기·queue SH·성능 수용을 입증하지 않는다.

정본 사실 원장은 private audit `map-airport-caller2-owned-r1-actual-facts.json` SHA `24c3b1a5e2ff8940c08c800e7c7ad873a8f629f8b0091def9151a134541c0011`이다. 원 result SHA `f546baaa81858f7121812d70f91c5981172979b77c59f4364b6f374d777a80f0`와 raw8개를 보존했다. 이전의 collect-only 절은 당시 checkpoint 기록으로 남기고 이 실제 결과와 구분한다. 기존 Root GC/후처리/startup 실패·성공을 이 2PASS와 합산하지 않는다.

## claim 전후 상태 전진과 원 결과 복구

T가 고정한 반례에서 초기 read가 `prepared`이고 실제 claim은 이미 `applied`를 반환해도 옛 상태로 plan/apply를 시도했다. 같은 `prepared` 안에서도 다른 worker의 reset/replan으로 binding이 달라질 수 있다. 두 순수 반례는 수정 전 2FAIL로 보존했고, 성공 claim 뒤에는 같은 member의 SDK0 read를 항상 다시 수행하여 snapshot/artifact/context identity와 현재 phase/binding으로만 진행한다. 새 입력이나 SDK 재수집은 없다.

read와 claim 사이에 다른 worker가 child를 seal한 경우는 SQLSTATE `23514`·constraint `ck_provider_snapshot_member_binding`·정확한 member-inactive 메시지 세 항목이 일치할 때만 재조회한다. 동일 snapshot/artifact/context, `child_sealed`, child done, root running 또는 done, 취소·격리 없음과 원 receipt/intent 재검증이 모두 성립해야 DML 없이 원 결과를 복구한다. 하나라도 다르면 원 claim 오류를 재전파한다. 같은 constraint의 input mismatch·다른 constraint·일반 lock timeout은 재분류하지 않는다. 이 inactive-seal 반례의 수정 전 1FAIL도 보존했다. 성공 claim 뒤 sealed를 읽는 경우에도 같은 상태·receipt 검증을 적용한다.

기존 reverse-Geo 정적 검사가 실제 정본 helper의 direct-name 호출을 요구하므로 local import와 호출 표기만 맞췄다. 정본 함수·재사용 의미·기존 검사 자체는 그대로다. 수정 전 lint 1FAIL/2PASS와 수정 뒤 3PASS를 구분한다. client/plan/runner와 해당 lint의 최종 집중 검증은 **91PASS/6.73초**, strict mypy1 및 Ruff2 PASS다. 이전 5717 실제 caller2 PASS는 그 source 세대의 사실로 보존하며, 이 새 제어 흐름은 같은 소유 2사례로 다시 검증한다. 위 race 자체의 실제 물리 경합·worker kill을 순수 대역 결과로 입증했다고 하지 않는다.

공유 repository의 outer finish는 root terminal 검사와 member-done no-op 순서를 별도로 가진다. runner의 immutable 완료 복원과 전체 public wrapper의 terminal 처리는 같은 판정으로 확대하지 않는다. 이 변경은 소유 runner/그 unit/본 보고서만 수정하며 SQL·공유 client·DTO/OpenAPI·기존 함수 signature·Airport 상한·retry 정책은 유지한다.
