# 제한 native worker의 실제 SIGKILL 복구 검증

## 범위와 기존 시험의 구분

기능 부모 PR1375의 `e9554ab5b6b48125575a563f82a18d7a170d9f81`을 기준으로,
프로덕션 source·DDL·설정 변경 없이 전용 통합 시험 한 건을 추가했다. 기존 `worker-loss`
표시는 RuntimeError/CancelledError 주입 뒤 context rollback인 만큼 실제 사망 증거가
아니다. 기존 시험 ID와 보고서 문구도 그 범위로만 정정했다.

새 시험은 고유 scalar PostGIS의 정본 full bootstrap/schema412와 runtime ACL을 사용한다.
기존 seed/bundle/sealed-plan helper를 재사용하고 source·head·후보·winner·finish는 실제
native helper로 실행한다. 운영·공유 DB·외부 DSN·원천 호출·배포·flag 변경은 0건이다.

## 실제 사망과 불변식

spawn한 worker는 실제 native가 completed receipt를 반환한 뒤에도 caller TX를 commit하지
않고 대기한다. 부모는 OS PID/PPID/starttime/UUID handshake와 pidfd, PG PID/backend_start/
xid/application_name/대상 DB 및 정확 protocol SH 잠금을 확인한다. 이때 외부에서 읽은
12개 대상 표의 scope hash는 사전 값과 같아야 한다.

부모가 해당 pidfd에만 SIGKILL을 보내고 exitcode=-9·join을 확인한다. 자식의 exception/
finally/정상 rollback을 이용하지 않는다. 5초 상한으로 backend 소멸·해당 PID의 잠금 0을
확인하고 protocol EX try-lock 및 dataset/head/link/Feature NOWAIT 재선점으로 잔류 잠금이
없음을 반증한다. 원시 이력·head·후보·투영·attempt/manifest/anchor의 scope hash도 그대로다.

동일 artifact/attempt/owner/sealed digest로 한 번 재시도하여 기대 winner와 원래 result digest,
새 raw key 1개·완료 attempt 1개를 확인한다. 그 뒤 completed receipt 재호출은 source DML
진입 시 즉시 실패하도록 spy를 설치하며, 전체 scope hash·result digest가 유지되어야 한다.

## 소유권과 상한

PostGIS는 UUID name/label/실제 생성 ID, 2CPU·memory1536MiB·memory+swap1536MiB
(추가 swap0)·PID256을 확인한다. 부모 pytest는 child 한 개만 spawn하며 child의 CPU20초,
주소공간1536MiB·core dump0, handshake12초·TX 대기20초·join5초·시험45초 제한을 둔다.
주소공간 제한은 RSS 측정이나 절감 주장이 아니다. DSN/DTO는 신뢰한 부모의 private Pipe로만
전달하고 argv/env·로그에는 넣지 않는다. child 오류는 고정 stage와 예외 class만 알린다.
일부 standalone Python의 pidfd wrapper 미제공 환경에서는 같은 Linux libc pidfd API를
사용하며 PID 기반 kill로 대체하지 않는다. 예외 때도 정확한 child만 종료·join하고 fixture가
자체 생성 container를 정리한다. 기존 프로세스·컨테이너·원본 파일은 건드리지 않는다.

## 실제 검증과 증거

- 최종 전용 실제 PG **1 passed(14.64초)**. SIGKILL exitcode=-9, backend·잠금0,
  rollback scope hash 동일, 같은 artifact 복구 completed, 재호출 DML0/raw1/완료attempt1.
- 현재 test source SHA256: `1ef46a893187184ae14afc872a85a3d2d4d28cd9240a6e00e5de1c3e0b22b360`.
- 새 시험 Ruff PASS, strict mypy(`--follow-imports=silent`) 1 file PASS. 기존 untyped helper의
  구현은 바꾸지 않고 재사용 경계의 Callable 타입만 명시했다.
- 로그 SHA256: `ee7e3a4b7989f87bbee655718d4e972a248ee1339ffff8fb3d377edddbe11e3b`. 로그·sanitized proof JSON은 별도 로컬 감사
  보관소에 동일 bytes로 보존했다. 정확 container ID의 SDK NotFound와 해당 UUID label의
  잔존0을 확인했다. 실제 종료한 child는 join/close했다.
- 예비 r1은 Python pidfd wrapper 부재로 **skip**, r2는 초기 주소공간768MiB가 기존 가상메모리
  약876MiB보다 작아 **MemoryError 실패**, r3는 detail dict 입력을 거부하는 정본 DTO의
  **ValidationError 실패**였다. libc pidfd/1536MiB 상한/명시 DTO 객체 Pipe 전달로 시험
  하네스만 고쳤다. r4의 1 PASS(14.75초)는 중간 증거이며 최종 수치는 위 실행만 쓴다.
  실패·skip 로그도 보존했고 성공 수에 더하지 않는다.
- 독립 리뷰 P2로 초기 검사는 protocol key/granted만 보아 SH 모드를 직접 입증하지 못함을
  확인했다. `pg_locks.mode=ShareLock` 조건을 추가한 뒤 위 최종 실행을 통과했다. 이전
  14.60초의 1 PASS 로그·proof는 보존하며 새 최종 실행과 합산하지 않는다.

두 독립 리뷰·정확 CI는 별도 gate다. 이 시험은 commit 전의 제한 name/phones TX 사망 복구이며
Dagster 실제 worker 감독·lease 만료 후 새 owner·네트워크 blackhole·PG/host 사망·전체 collector/
Geo/region/shared Feature·ARM 비용·운영 활성화·전체 T-CWRITE acceptance를 대신하지 않는다.
기본 OFF·정책 seed0·자동 수집 배선0과 취소된 Weather/Transport export 운영 활성화 상태를 유지한다.
