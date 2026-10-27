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

기존 public statement 상한30초/lock1초와 reader3초를 넓히지 않는다. 새 child의
기본 statement3초는 public `_arm_deadline`의 LEAST 규칙 때문에 apply에서도 유지된다.
child 전체30초·CPU20초/RAM1536MiB, owned PG CPU2/RAM1536MiB/PID256 및
실행150초/감시160초/회수15초도 유지한다.

초기 순수20개가2.36초에 통과했고, serializer 보강 뒤에는21개(새 분류9·hashseed1·기존
IPC/회수6·ledger5)가6.76초에 통과했다. 통합2case의 전이 fixture는 각각6개이며 collection에서
미정의0을 확인했다. 실제 DB 수용이나 운영 효과는 주장하지 않는다. 두 독립 source 리뷰와
부모 PR의 최신 main 의존성 합성 뒤에만 owned PG를 실행한다.

### PG 실행 전 시험 자체의 정정 이력

초안의 `model_dump_json`은 presence frozenset의 process별 hash 순서가 달라질 수 있었다.
기존 native canonical encoder를 재사용해 집합 순서를 고정하고, 동일한 전체 artifact bytes를
서로 다른 hashseed1/2 프로세스에 stdin으로 전달하는 회귀를 추가했다. 첫 회귀 초안은 각
프로세스에서 새 DTO를 만들어 created_at이 달라져20PASS1FAIL(7.39초)이었다. 같은 bytes로
바꾼 뒤에는 ADR-018의 typed detail 복원 누락으로20PASS1FAIL(4.47초)이었다. 시험 decoder에서
PlaceDetail을 명시 생성해 고쳤으며 이후21PASS다. 이 두 실패에서 실제 PG/운영 호출은0이다.

이 시험은 시험이 직접 조율하는 한 번의 재계획이다. 현재 public scalar apply/batch에는
unbound READY 정리→동일 artifact 재계획→유한 재시도를 소유하는 일반 coordinator가 없다.
그 생산 구현과 실제 전 writer 전환은 후속 별도 설계·리뷰 대상이다.
