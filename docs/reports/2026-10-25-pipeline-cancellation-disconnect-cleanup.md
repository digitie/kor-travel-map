# Pipeline task 취소의 원 backend 종료 보강

535a의 owned 두 API task 취소 사례는 원 시간·zero-row 단언을 유지해 모두 통과했다.
최종 exact CI/live UI·운영 배포와 전체 활성화 수용은 별도 미완이다.

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
업무 상한이 아니다. 아래 owned 2회귀에서 원 3초/zero-row 조건을 통과했지만
별도 readback 시간의 일반 상한이나 모든 장애의 종료를 증명하지 않는다.
SQLAlchemy observer checkout의
취소 회수도 하위 driver 종료를 기다릴 수 있으므로 단순 asyncio deadline을 모든 network
blackhole에서의 절대 wall 상한으로 주장하지 않는다. 확인 실패는 false와 elapsed/error
종류 로그로 남기고 원 caller CancelledError를 우선한다. 정상 응답 중 연결 정리 불확실성은
별도 DB 일시 실패 503/Retry-After로 분류하고 Dagster 실패로 바꾸지 않는다.

PostgreSQL의 disconnect check는 kernel이 알려 주는 단절을 질의 중 점검한다. 임의 network
blackhole 전체를 해결하는 keepalive 보증은 아니다. 동기 terminate는 client 측 동작이고
server 종료 확인은 별도의 readback 결과로만 인정한다.

## 제품 실행 전 정적 검증과 실패 정산

순수 단위 45개 PASS, Ruff 대상 5파일 및 mypy 제품 2파일 PASS를 확인했다.
실제 task/P 대기 원 단언은 바꾸지 않았다. 추가 integration은 실제 K 성공+commit 뒤
반환 전 barrier에서 caller를 취소해 root/attempt 불변, server advisory 0, pool 1의 새
checkout, fresh/replay 200을 요구한다. b0b91 제품 후보의 실제 두 integration은
1FAIL/1PASS였다. 당시에는 아래 수정의 실제 PG가 미실행이었고, 최종 535a 결과는
마지막 절에서 별도로 정산한다.

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


## 첫 제품 실행과 interrupted invalidation 보강

b0b91 owned 실행의 K real-commit-gap은 1.104초 PASS다. P 대기는 최초 단언에서
old PID118 advisory 2행 때문에 FAIL이고, 그 case의 fresh/replay는 도달하지 않았다.
전체 XML은 1FAIL/1PASS·14.822초(console 15.55초)이며 소유 PG 정리는 통과했다. cleanup 로그의 confirmed=false/
elapsed=0만으로 원래 예외의 종류를 확정하지 않는다. 원 FAIL 및 성공 case는 분리 보존한다.

별도 순수 재현에서 실제 SQLAlchemy QueuePool/Connection과 SQLite DBAPI를 사용했다.
do_terminate의 native close 앞에 CancelledError를 주입하면 connection은 invalidated=true/
closed=false, captured proxy의 driver/dbapi는 None인데 원 native는 열린 상태가 된다.
기존 소유권 검사는 이를 거부해 캡처한 원 native도 종료하지 않았다. 이 재현은 실제 PG
실패의 가능한 분기이며 원 실행의 원인을 직접 소급 확정하는 증거는 아니다.

새 검사는 None를 원 Connection의 invalidated && !closed 상태에서만 허용한다.
다른 nonnull driver는 원 driver가 이미 닫혔어도 항상 거부한다. 정상 반환된 연결·raw
proxy를 같은 native로 재checkout한 실제 SQLAlchemy 회귀에서도 다음 소유자의 연결을
종료하거나 invalidate하지 않는다. 이미 dbapi가 비워진 proxy의 invalidate는 생략한다.
late connection.connection 조회·새 backend unlock은 추가하지 않았다.

기존41개에 이 interrupted-invalidation, 정상/raw 반환 후 실제 same-native recheckout,
닫힌 원 driver와 다른 현 driver를 구분하는 4회귀를 더해 순수45개가 PASS했다.
원 35초/3초/zero-row 단언은 그대로다. 이 수정의 최종 실제 결과는 아래에 기록한다.


## 최종 535a 제품 두 사례 수용과 남은 경계

두 독립 source/binding 검토 뒤 동일 고정 자원으로 실행한 owned PG 1회에서
2PASS/0FAIL/0ERROR/0SKIP을 확인했다. XML suite 16.270초이며 P 대기 case 15.084초에는
공유 fixture setup이 포함된다. K commit-gap case는 1.143초다. 이를 cleanup 자체의
시간이나 성능 개선율로 해석하지 않는다.

두 case 모두 최초 advisory zero-row 단언과 caller 취소 3초·시험 35초 제한을 유지했다.
취소된 요청 뒤 pool 1의 새 checkout, fresh/replay HTTP 200, 동일 결과·시도 1개와 외부
HTTP 0을 통과했다. K gap은 실제 pg_try_advisory_lock 성공과 commit 뒤 caller가 결과를
받기 전 barrier에서 취소했다. P holder를 먼저 풀어 단언을 통과시키지 않았다.

실제 source535a/schema429, tracked2437 전체 bytes·mode/OID 후검증, SDK53 의존성 pin 후검증,
실제 project import15와 pycache 부재를 각각 확인했다. 정확 소유 CID/UUID/scalar label 0,
anonymous volume 1개 부재로 정리됐다. SDK 체크는 실제 provider HTTP 재수집 증거가 아니다.
Root의 별도 fresh cleanup 관찰과 T의 독립 raw/XML/source/SDK 대조를 함께 보존했다.

원 9088/808a 실패, 100ms 설정 단독 실패와 b0b91의 1FAIL/1PASS는 각각 보존하며 최종
성공으로 재해석하거나 합산하지 않는다. 이 수용은 새 실제 Uvicorn/live UI나 prod 배포,
무한 network blackhole의 hard wall, 모든 hierarchy 크기·collector/SH 활성화 수용을
뜻하지 않는다. 최신 exact CI, live UI 및 사용자 전체 수용에 필요한 merge/deploy 단계는
별도로 남아 있다.

수용 원장: Root 92dabe43172653b93f58f1fc0586eba65e8d06ccc1d11257b6dacfa9e025502a,
T eddcc7e88493fe72cce65373abc0f499bbdb0071188d6dd159ff08fdee5d5a30.


## 최초 정확 CI의 계약 핀 정산

a216f362의 첫 CI는 Python 3.11/3.12/3.13에서 각각 3,827 PASS·7 SKIP와 같은 두 계약 핀 검사 FAIL을 냈다. 기존 503 응답 description 두 곳의 DB 연결 정리 문구를 OpenAPI에 반영하면서 vNext admin baseline과 pending T-VN-40 receipt의 full-admin SHA를 함께 갱신하지 못한 원인이다. PG 통합 lane은 실행되지 않았다. 원 CI 로그는 보존하며 제품 회귀 실패나 PG PASS로 계산하지 않는다.

이번 수정은 두 정본 SHA와 그 artifact freeze 상수 및 변경 사유만 원자 갱신한다. user/service spec·제품·통합시험은 그대로이며, PinVi re-vendor·paired live 검증 전 receipt는 계속 pending이다. 새 정확 CI와 live UI·배포 수용은 별도 미완이다.
