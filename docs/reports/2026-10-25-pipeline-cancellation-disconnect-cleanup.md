# Pipeline task 취소의 원 backend 종료 보강

## 실제 실패와 작은 설정 실험

원 9088 API task 시험은 caller 취소·pool 반환·새 checkout을 통과한 뒤 최초 advisory
zero-row 단언에서 실패했다. fresh/replay 요청은 도달하지 않았다. 808a의 별도 진단은
그 단언을 그대로 유지하고 실패 뒤 holder를 잡은 상태에서만 metadata를 관측했다.
원 backend는 2.819082초까지 K EX granted/P EX waiting으로 보였고 3.073852초에는
activity와 잠금이 모두 사라졌다. 이는 영구 누수의 증거가 아니며 종료 원인을 lock
timeout 하나로 확정하지 않는다.

Root의 d4099 설정 전용 실험은 runtime client_connection_check_interval=100ms
한 줄만 추가했다. 최초 zero-row 단언은 여전히 FAIL이다. 후속 관측 0.006812초에는
원 K/P 행이 있었고 0.262137초에는 backend와 잠금이 없었다. holder의 P SHARE는 계속
유지됐다. 단일 관측이며 평균·최대시간·설정만으로 제품 수정 완료를 주장하지 않는다.
원 FAIL·후속 timeline·별도 source/SDK 후관찰과 소유 container 정리는 각각 보존한다.

## 제품 후보의 경계

정상 hierarchy 크기 상한은 정본에 없으므로 검토 중이던 정상 DB phase 0.5초 제한은
채택하지 않았다. 그 미출시 후보는 private audit에 보존했다. 원 정상 transaction,
SERIALIZABLE 첫 SQL, statement/lock timeout, root/member 정산과 Dagster HTTP 예산을
바꾸지 않는다. 기존 함수 37개 중 연결 수명과 K acquire/release 관련 함수만 변경하고,
public coordinator와 ownership reload의 업무 AST는 연결 context를 역치환하면 같다.

첫 K SQL 전에 원 pool proxy/native driver/PID/backend_start를 고정한다. coordinator
연결에만 disconnect check를 설정하며 기존 비영 값이 100ms보다 짧으면 보존한다.
정상 반환은 원 GUC 문자열을 복원한다. K 시도 전에 소유 가능성을 기록하고 confirmed
false acquisition 또는 confirmed exact unlock 뒤에만 해제한다. 따라서 K SELECT 성공,
commit 불확실성 및 helper 반환 전 caller 취소도 정상 pool 반환으로 빠져나가지 않는다.

caller 취소·invalidated/unknown backend는 캡처한 원 native driver를 동기 terminate한 뒤
pool slot을 회수한다. invalidated connection에서 proxy를 다시 얻거나 새 backend로 unlock을
보내지 않는다. AnyIO shield는 이 cleanup 경계에만 적용한다. 전체 business를 shield하거나
cleanup task를 따로 남기지 않는다.

동일 engine/LOGIN의 새 observer는 catalog SELECT만 읽는다. 원 PID+backend_start가
activity에 없고 그 PID의 advisory 행도 없을 때만 termination confirmed이다. PID 재사용
때 새 backend에 종료 신호를 보내지 않는다. 각 native SELECT는 autocommit의 새 snapshot이며
query 본문·자격증명·타 세션의 SQL은 읽지 않는다. observer는 성공·실패 모두 폐기해
readonly 설정/driver를 pool 재사용에 남기지 않는다.

readback은 공유 0.6초, 개별 native statement 0.1초를 후보 경계로 둔다. 이 값은 정상
업무 상한이 아니며 아직 실제 제품 시험으로 수용하지 않았다. SQLAlchemy observer checkout의
취소 회수도 하위 driver 종료를 기다릴 수 있으므로 단순 asyncio deadline을 모든 network
blackhole에서의 절대 wall 상한으로 주장하지 않는다. 확인 실패는 false와 elapsed/error
종류 로그로 남기고 원 caller CancelledError를 우선한다. 정상 응답 중 연결 정리 불확실성은
별도 DB 일시 실패 503/Retry-After로 분류하고 Dagster 실패로 바꾸지 않는다.

PostgreSQL의 disconnect check는 kernel이 알려 주는 단절을 질의 중 점검한다. 임의 network
blackhole 전체를 해결하는 keepalive 보증은 아니다. 동기 terminate는 client 측 동작이고
server 종료 확인은 별도의 readback 결과로만 인정한다.

## 검증 상태

순수 단위 41개 PASS, Ruff 대상 5파일 및 mypy 제품 2파일 PASS를 확인했다.
실제 task/P 대기 원 단언은 바꾸지 않았다. 추가 integration은 실제 K 성공+commit 뒤
반환 전 barrier에서 caller를 취소해 root/attempt 불변, server advisory 0, pool 1의 새
checkout, fresh/replay 200을 요구한다. 현재 두 integration은 collect-only이며 제품 후보의
실제 PG 결과는 없다. source 두 독립 리뷰와 별도 owned 실행 승인 뒤 수용한다.

OpenAPI는 동일 환경에서 parent export와 candidate export를 각각 비교했다. Pydantic
2.14.1의 Decimal anyOf 세 곳은 parent에서도 tracked와 달라지는 baseline drift다.
새 export delta는 admin 취소 2개 operation의 503 설명뿐이고 service profile 변화는 없다.
그 delta와 정본 openapi-typescript 생성 결과만 변경했다. baseline drift를 새 DTO 변경이나
전체 export --check PASS로 보고하지 않는다.

참고: [PostgreSQL 16 connection settings](https://www.postgresql.org/docs/16/runtime-config-connection.html#GUC-CLIENT-CONNECTION-CHECK-INTERVAL).


## 8f 후보 후속 정정

Root의 순수 재현에서 정상 GUC 복원 중 새 CancelledError가 나면 원 후보는 503 또는
기존 ValueError로 덮었다. 원 8f source와 재현을 보존하고 cleanup finally의 우선순위를
수정했다. 이미 받은 caller 취소가 있으면 그 객체, cleanup에서 처음 취소되면 새 취소
객체를 exact-discard/readback 뒤 재전파한다. 정상 restore barrier의 실제 task.cancel과
성공/도메인 오류 양쪽을 시험한다.

실제 SQLAlchemy engine에 network를 호출하지 않는 async_creator를 넣어 checkout의 연결
실패와 timeout에서 creator finally/pool checkedout 0/새 task 없음도 확인한다. 반복 AnyIO
level 취소, 미확정 cleanup latch와 rollback 뒤 정상 continuation을 별도로 확인한다.
이 주입은 실제 asyncpg connect/drain이나 network blackhole의 hard 상한을 증명하지 않는다.
