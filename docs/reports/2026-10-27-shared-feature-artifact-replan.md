# 공유 Feature의 동일 artifact 재계획 검증

## 범위와 현재 상태

PR #1421의 정확 문서 head `3e962183` 위에 쌓은 후속 시험이다. 생산 Python·SQL·API와
운영 OFF 설정을 바꾸지 않는다. 두 독립 source 리뷰, owned PG와 최종 CI는 아직 대기한다.
상위 T-CWRITE-01–09, 운영 CPU/RSS 개선과 일반 수집 coordinator 구현은 미완이다.

## 검증하는 경계

- canonical source identity를 가진 두 dataset과 기존 primary link를 한 Feature에 연결한다.
  두 capture 순서와 두 apply 선두를 바꿔 rank winner의 결정성을 확인한다.
- spawn한 독립 OS worker 둘이 각 pool1로 먼저 각자의 READY 계획을 확정한다.
  leader를 source DML 직후 정지하고 follower의 실제 participant-scope tuple 및
  leader transactionid 대기를 관측한다. Feature 행 대기나 DML 중첩을 가정하지 않는다.
- leader commit 뒤 follower가 받은 정확 `manifest source changed; replan`의 무constraint
  `40001`만 정상 stale로 취급한다. `23514`·`55P03`·일반 serialization/연결 오류는 실패다.
- 전체 apply TX의 aborted 상태, READY 계획/lease 잔존과 source DML0을 확인한다.
  snapshot control binding이 없는 시험 계획만 public cancel로 정리한다. bound
  Airport/Rest의 typed reset·유효 lease를 우회하지 않는다.
- bytes가 완전히 같은 bundle(원천 key/raw/hash/fetched/imported/presence 포함)로
  새 attempt/idempotency key와 현재 DB manifest를 만든다. input digest는 같고,
  stale manifest는 달라야 한다. SDK·Geo·운영 호출은 하지 않는다.
- 최종 양쪽 source head, rank winner/base의 원천 lineage, 원 primary links와 완료 receipt,
  완료 replay source DML0을 확인한다. 실패 시 기존 pidfd 소유권 검증/유한 회수를 재사용한다.

## 유지하는 한도와 남은 일

기존 SQL30초/lock1초와 reader3초, worker별 CPU20초/RAM1536MiB,
owned PG CPU2/RAM1536MiB/PID256 및 실행150초/감시160초/회수15초를 늘리지 않는다.
순수 회귀20개(새 분류9·기존 IPC/회수6·ledger5)가 2.97초에 통과했다. 통합2case의
전이 fixture는 각각6개이며 collection에서 미정의0을 확인했다. 실제 DB 수용이나 운영
효과는 주장하지 않는다. 두 독립 source 리뷰 뒤에만 owned PG를 실행한다.

이 시험은 시험이 직접 조율하는 한 번의 재계획이다. 현재 public scalar apply/batch에는
unbound READY 정리→동일 artifact 재계획→유한 재시도를 소유하는 일반 coordinator가 없다.
그 생산 구현과 실제 전 writer 전환은 후속 별도 설계·리뷰 대상이다.
