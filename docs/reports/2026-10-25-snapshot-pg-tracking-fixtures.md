# snapshot 후보의 추적 잠금 fixture 정합

## 원 실패

후보 7f40e95의 전체 PostGIS 검사는 glibc에서 118실패·1768통과·23skip·30error,
alpine에서 118실패·1762통과·29skip·30error였다. 두 lane의 실패·오류 148개
node ID는 같았다. 이 중 배치·취소 테스트의 finally가 canonical tracking 행을
잠금 없이 지우다 23514로 중단되어, 뒤의 목록 검사에 committed 행이 남았다.
이 문서는 전체 실패가 fixture 때문이라고 주장하지 않는다. 공유 scalar projector의
별도 제품 수정과 나머지 전체 CI 검증은 계속 필요하다.

## 수정

관리용 cleanup transaction은 첫 tracking DML 전에 기존
`lock_provider_feature_finalization`으로 P EX→L을 잡는다. projection 테스트가 직접
만드는 provider root·membership fixture도 같은 규약을 지킨다. 4개 테스트 파일에
13줄을 더했으며 제품 SQL·guard·권한·기대 assert·검사 개수는 바꾸지 않았다.

## 실제 검증

75fda905d016a1d50c42b90693623d60371b29fa에서 배치·취소 phase2·취소 repository·
pipeline projection의 100개를 실제 glibc PostGIS에 실행해 33.18초에 전부 통과했다.
오류·실패·skip은 0이다. 테스트 DB는 schema430이며 2CPU·1536MiB·PID256,
pytest150초·부모160초·정리15초 상한 안에서 실행했다. 소스2512개·SDK53개의
전후 해시와 실제 import16개를 대조했다. 종료 뒤 정확한 CID와 임시 volume 1개의
부재를 확인했다. 운영 DB·이미지·스케줄은 변경하지 않았다.

원 실패와 중간 결과도 남겼다. 첫 배치15개는 통과했고, 나머지85개 중84통과·1실패는
직접 만든 root fixture의 누락 prefix였다. 그 한 곳을 추가한 뒤 위100개가 통과했다.
이 결과를 전체 CI 또는 실제 서로 다른 데이터셋 두 worker 동시 쓰기의 증거로
간주하지 않는다. 관련 원 로그·XML·소스/자원 원장은 배포 감사 기록에 보존했다.


## 잔여 fixture와 실제 검증 추가

후속 source `13866d121d9bb62c899e7d6fd3cd5dac03afe45b`는 원 실패의 남은
fixture 준비·정리를 정식 P EX→L과 RC finalizer 계약에 맞춘다. C6c 정리 TX와
active-request raw cancellation seed는 첫 DML 전에 prefix를 취득한다. 대량 lock-budget
seed도 동일하며 최종 procedure와 legacy protocol 시험의 finalizer 분기만 RC로 바꾼다.
다른 legacy SER 경로와 원 잠금 수/관측 수/오류 분류 단언은 유지한다.

runtime에 내부 attempt 표 SELECT 권한을 더하지 않는다. 실제 typed begin이 반환한
행의 status와 apply_txid를 현재 TX ID와 대조해 applying 상태를 검증한다. event 소유권을
generic job으로 바꾸는 공격은 기존 ownership 불변 trigger가 먼저 23514와 정확 constraint로
거부한다. 이 선행 규칙을 typed 42501 단독 증거로 부르지 않는다. 별도 fresh TX의 원문
message UPDATE 공격을 추가해 실제 typed 42501·정확 constraint를 검증하고, 마지막에
job_id와 message가 모두 원본인지 확인한다. 권한·guard·제품 DML 변경은 없다.

| 고정 실행 | 실제 결과 | 범위 |
| --- | --- | --- |
| residual r3 | 10 PASS/26.99초, skip0 | cleanup·status·consistency·activation·active identity·legacy finalizer |
| residual r6 | 2 PASS/150.23초, skip0 | real gate-busy 분류와 원 2×lock-table 규모의 finalizer |

두 실행은 별개이며 하나의 12 PASS 실행으로 합산하지 않는다. 대량 호출 자체는 123.22초다.
원 150초 감사 실행 한도에는 bootstrap·seed·호출·후처리가 함께 들어갔다. 한도 소진 당시
최종 CALL은 active이고 lock wait나 blocking PID가 없었다. 동일 제품·데이터 수·단언과
2CPU/1536MiB/추가 swap0/PID256을 유지하고 감사 실행 한도만 pytest585초/전체600초로
늘린 r6에서 끝까지 확인했다. 제품 timeout이나 데이터 규모를 낮춘 결과가 아니다.

첫 private 재수출의 conftest fixture 누락, ownership 오류 기대의 실제 실패,
독립 DB 대신 빈 기본 DB를 읽은 감사 observer 실패, 원 150초 소진을 모두 보존했다.
각 성공 실행에서 Git2519파일·SDK53파일 전후와 실제 import30개를 대조했고 정확 CID와
UUID/global label의 부재, 익명 volume1개 정리를 확인했다. 실제 검증 원장 SHA는
`0c9fbef428c15f4bbe3faad6964b3ee00198241a7181ef608c97081b5e093a7f`다.

기존 전체 CI의 glibc/Alpine 실패 이력은 유지한다. 최신 합성 source 전체 CI와 새 실제
UI, 운영 배포·동시 두 데이터셋 실증은 아직 별도 gate다. 운영 DB/이미지/일정은 바꾸지 않았다.
