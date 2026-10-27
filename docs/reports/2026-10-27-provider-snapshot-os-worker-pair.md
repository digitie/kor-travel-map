# 두 독립 OS worker의 snapshot 원자성 시험

## 범위와 상태

2026-10-27, 기준 main `0324cab3`에서 Airport1/Rest2의 저장된 관측을 적용하는
실제 `multiprocessing` spawn worker 2개의 제한 시험을 추가한다. 생산 Python/SQL,
스키마432, 운영 설정·새 profile OFF, 30초 원자 구간·reader3초·lock1초를 바꾸지 않는다.
상위 **T-CWRITE-01–09는 모두 미완료**다. 이 문서는 구현·검증 중 원장이다.

기존 동일 프로세스의 두 PG session 시험을 대체하지 않는다. 기존 등록·claim·정적
원 입력/후처리 helper를 재사용하고, 부모의 engine/client를 제거한 불변 case와 자체
격리 fixture DSN을 256KiB 상한의 private Pipe로만 보낸다. child마다 새 pool1을 만들며
DSN·원문은 argv/env/log로 내보내지 않는다. 외부 SDK·Geo·운영 접속은 수행하지 않는다.

## 검증할 동작

- 실제 spawn PID·부모 PID·Linux starttick을 검산하고, 별도 backend start와 XID를 확인한다.
- leader는 실제 적용·필수 후처리 뒤 미commit 상태를 hold한다. 이 상태에서 follower의
  실제 source apply가 반환해야 한다. leader를 Airport/Rest 양 방향으로 검사한다.
- follower가 정본 begin-postprocess SQL에서 leader XID를 기다리고, 정확 blocker가
  leader 하나이며 leader가 global topic relation을 잠근 사실을 확인한 뒤 hold를 해제한다.
- 두 정본 coordinator의 commit ACK 뒤 원 결과·receipt·counter 증가를 대조한다.
  apply/postprocess TX가 각 worker의 XID와 같아야 하며, child seal은 이후 별도 TX다.
- 시작 직후 identity/pidfd 저장 실패도 회수 경로에 포함한다. 자기 PID/starttick 및 pidfd만
  사용하며, 전체 자식2 회수에 공유15초를 둔다. 한 자원 정리 오류가 다른 자식·Pipe·FD
  정리를 건너뛰지 않고 원 primary 예외를 보존한다. foreign PID에는 신호를 보내지 않는다.

프로세스 주소공간/CPU 개별 제한은 합산 메모리·호스트 CPU 제한이 아니다. 기존 owned PG의
CPU2·RAM1536MiB·swap 동일·PID256, 외부 phase150초/parent160초/cleanup15초 상한을
늘리지 않는다. 부모와 두 child의 합산 CPU/RSS 및 운영·ARM 비용 감소는 아직 측정하지 않았다.

## 현재 검증 결과

- 신규 통합 시험2 node collection: PASS, 21.77초. PG fixture·worker 실행은 하지 않았다.
- IPC 상한·child 오류/잘못된 profile·foreign identity 거부·시작 중간 실패 회수·개별 close
  오류의 순수 회귀6개: PASS, 6.68초. 외부 호출·Docker·PG 실행0.
- 신규 두 시험 파일 Ruff: PASS.
- 두 독립 적대 리뷰, 같은 상한의 실제 owned PG, 전체 CI는 아직 대기다.
  이 결과를 실제 두 worker 성공이나 운영 동시 쓰기 완료로 해석하지 않는다.

## 후속과 제외

최종 source 두 리뷰 → 같은 상한의 단독 owned PG → 최종 CI 순으로 검증한다.
실제 Dagster worker 감독·SIGKILL·wire 단절·shared Feature 양성 경합·지역 분할·전체 writer
확대·215개/실 upstream·운영 활성화·CPU/RSS 효과는 별도 수용 항목이다.
이 PR은 시험/문서만 추가하므로 API/UI/운영 배포 변경은 없다.
