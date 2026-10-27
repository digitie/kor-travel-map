# 공유 Feature의 동일 artifact 재계획 검증

## 범위와 현재 상태

PR #1421의 문서 head `3e962183` 위에서 시작해 최신 CommonAA 부모 합성 `e23c277d`를
정상 merge한 후속 시험이다. 정확 source `e35f5dc3`은 두 독립 source/합성/수정 리뷰와
owned PG2case(24.80초, skip0)를 통과했다. 이 PR은 생산 Python·SQL·API와 운영 OFF 설정을
바꾸지 않으며 최종 CI·병합은 아직 대기한다. 상위 T-CWRITE-01–09, 운영 CPU/RSS 개선과
일반 수집 coordinator 구현은 미완이다.

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
- 최종 양쪽 source head, rank winner/base의 원천 lineage, 원 primary links와 완료 결과 지문,
  완료 replay source DML0을 확인한다. 실패 시 기존 pidfd 소유권 검증/유한 회수를 재사용한다.

## 유지하는 한도와 남은 일

기존 public statement 상한30초/lock1초와 reader3초를 넓히지 않는다. 새 child의
기본 statement3초는 public `_arm_deadline`의 LEAST 규칙 때문에 apply에서도 유지된다.
child 전체30초·CPU20초/RAM1536MiB, owned PG CPU2/RAM1536MiB/PID256 및
실행150초/감시160초/회수15초도 유지한다.

초기 순수20개는2.36초, serializer 보강 뒤21개(새 분류9·hashseed1·기존 IPC/회수6·ledger5)는
6.76초에 통과했다. 최신 CommonAA private import 환경의 최종 source 순수21개도7.00초에
통과했다. 통합2case의 전이 fixture는 각각6개이며 collection에서 미정의0을 확인했다.
두 독립 리뷰와 최신 main 의존성 합성 뒤 실행한 실제 PG 결과는 아래에 분리해 기록한다.

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


## 첫 실제 PG 실패와 관찰용 bind 정정

최신 CommonAA를 정상 합성한 `f691a8e1`의 첫 owned PG는 두 case 모두 실패했다
(2FAIL, pytest28.02초). 정확 participant-scope 대기와 leader commit, 선택된40001,
READY 계획 불변 확인 뒤 `pg_xact_status(CAST(:xid AS xid8))`의 관찰용 bind에서 멈췄다.
asyncpg의 xid8 codec은 정수를 요구하는데 시험이 `str(xid)`를 넘겨 DataError가 났다.
반환받은 정수 xid를 그대로 전달하는 한 줄만 고쳤다. 다른 observer의 `::text` 비교용
문자열과 생산 SQL/Python은 바꾸지 않는다.

첫 원결과 `map-shared-feature-replan-owned-r2-fe46c0d59c2242dbadf7fd964c57f045/result.json`
SHA256은 `07a621f17eab06975cb6b66581ba03c13299e6a04e89ab22487a996e0afde219`다.
정확 owned CID 없음·anonymous volume1개 없음·전체 scalar label0의 cleanup은 PASS다.
이 첫 실행에서는 관찰용 쿼리가 실패했으므로 aborted 상태 확인과 cancel·동일 artifact
재계획·완료 replay의 양성 수용은 미도달이었다. 이 한계를 보존하고 한도/자원 확대 없이
두 좁은 source/adapter 리뷰 뒤 아래의 별도 재시험을 실행했다.

## 실제 PG 수용

정확 source `e35f5dc3ae47b13d046044361d6a713ad2156cd3`을 고정한 별도 owned r3 실행은
2PASS·error0·skip0, pytest24.80초다. 기존 첫2FAIL과 PG 전 순수실패2회는 위 이력에 남긴다.

| 경우 | 초기 capture 순서 | 선두 apply | 실제 확인 |
| --- | --- | --- | --- |
| rank winner 선두 | 0→1 | dataset0 | 정렬 participant-scope tuple·leader transactionid 대기→40001→aborted→동일 artifact 재계획 |
| rank loser 선두 | 1→0 | dataset1 | 같은 대기·rollback·재계획, rank0 winner/base/lineage 보존 |

각 경우는 서로 다른 spawn OS process 둘과 각 pool1을 사용한다. `23514`·`55P03`를 정상
stale로 받아들이지 않고, 정확 무constraint `manifest source changed; replan` 40001만
받는다. source 쓰기 전에 실패한 follower의 전체 apply TX가 실제 aborted임과 READY 계획
불변·원천 쓰기0을 확인했다. control binding이 없는 계획만 public cancel해 자기 scope의
owner/lease를 비우고 foreign scope를 보존했다. 새 attempt/key·현재 manifest는 달라지지만
원 bytes와 input digest는 같다. 양쪽 새 head, 원 primary links, rank0의 name/phones base
원천 key/hash와 저장된 완료 결과 지문을 확인했다. 완료 replay는 같은 result_digest를
반환하며 source DML0이다.

모든2582 tracked source의 Git blob/mode 전후 검산, 실제 project import59파일과 SDK53파일
전후 정규화 바이트 검산을 통과했다. Common은 shared venv를 바꾸지 않은 private target의 정확
`aa232ad5f255233184de80eceaab2e9b6ccb00c9`이며 actual package·distribution root·direct_url
commit/hash 및19 source bytes를 runner/실제 pytest의 전후 네 지점에서 동일하게 확인했다.
SDK는 source import 검증 범위이며 별도 network 계측이나 운영 CPU/RSS 효과를 주장하지 않는다.

원결과는 `map-shared-feature-replan-owned-r3-b8c292e032ad4dc493c429d0f5fdd98a/result.json`,
SHA256 `35aeb74c7ade4d97921e9e2fa003b4b3cc1e3a3577f9ae2560b1fd83707d7739`다.
이 원장이 핀한12개 artifact의 해시·JUnit2 proof·source/import/Common 증거를 직접 검산했다.
정확 owned CID 없음·anonymous volume1개 없음·전체 scalar label0 정리도 PASS다. Root와 W의
별도 실제수용 검산은 각각 `e2c3140a…979ef30`, `c4441b13…550b759` 원장에 남는다.

이것은 알려진 한 Feature와 두 primary dataset의 시험 조율 한 번이다. 일반 운영 재시도
coordinator, 전체 identity/link/retire writer 전환·phantom closure, 운영 성능 개선과 활성화는
아직 구현·수용하지 않았다. 최신 Common의 운영 이미지 갱신도 이 격리 시험의 배포가 아니다.
