# Task 취소 뒤 advisory 잠금 진단 준비

기준은 frozen 9088a504379186b5f8078cc3c606132f433d93f2이다. 첫 실제 실행은 task 취소,
pool 반환과 새 checkout까지 통과한 뒤 PID 118의 advisory 2행 때문에 실패했다.
당시 mode/granted/backend 상태는 저장하지 않아 영구 누수나 일시 전파 지연으로 단정하지
않는다. holder 해제 뒤 fresh/replay 요청과 runner의 정상 후검증은 도달하지 않았다.
원 FAIL과 별도 읽기 전용 source/SDK 후관찰, 정확 소유 container·volume 정리 증거는
서로 구분해 보존한다.

이번 변경은 별도 worktree의 진단 시험만 소유한다. 최초 _no_advisory_locks SQL과
rows == [] 단언은 그대로이며, 최초 실패 이후에만 holder를 유지한 채 최대 4.5초,
최대 18개의 새 읽기 전용 트랜잭션으로 관측한다. 각 statement 1초/lock 250ms를
유지한다. target PID와 holder PID의 advisory classid/objid/objsubid/mode/granted,
backend_start/state/query_start/wait_event_type/wait_event를 기록한다.
최대 128행과 초과 표지만 저장하며 query 본문·자격증명은 읽거나 출력하지 않는다.

관측은 XML user property에 남긴다. target 잠금이 사라지거나 관측 오류·상한이 생겨도
원 최초 AssertionError를 그대로 다시 발생시킨다. 정상 경로에는 새 대기나 재시도가
없다. pytest 전체 35초, task 정리 2초와 engine 정리 3초는 바꾸지 않는다.
새 관측은 원 실패 시점과 원인 사이의 시간을 직접 소급 증명하지 않으며, holder가
유지된 동안의 후속 상태만 설명한다.

제품 코드·권한·SQL·fixture·정리 절차는 변경하지 않았다. 실제 PG 진단은 두 독립
source/binding 검토와 별도 슬롯 승인 전까지 미실행이다. 정상 fresh/replay까지의
전체 수용이나 production cleanup 수정 완료로 해석하지 않는다.
