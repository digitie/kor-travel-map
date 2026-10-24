# EX full-refresh context 후보 단일 조회(423, 부분 체크포인트)

## 문제와 구현

기존 `_exclusive_provider_refresh_context`는 같은 applying attempt/manifest 조건으로 count와 row SELECT를 따로 수행했다. 새423은 최대2행의 단일 SELECT에서 첫 행을 명시적으로 보관하고 0/복수는 false로 반환한다. 정확1행만 기존 protocol EX → candidate assertion → primary entity STRICT SELECT → 공개 scalar assertion 순서로 진행한다. 기존420 역사 파일, 이후 검증 본문, SQLSTATE, 권한·함수 서명·search_path·기본 EX 정책은 바꾸지 않는다. 예외를 정상0행 경로로 사용하거나 새로운 캐시/GUC를 추가하지 않는다.

마이그레이션은 원래 prosrc SHA256 `3dd92fbb11e8d8c8cdfdf3fb5e90f0a04a19b80d7d89ae95505a0733edfc2361`와 단일 catalog 함수의 signature/owner/언어/SECURITY DEFINER/volatile/결과/search_path를 확인한 뒤 기존 소유자로 CREATE OR REPLACE한다. protocol EX와30초 statement/1초 lock 상한을 유지하고 더 짧은 기존 설정을 보존한다. 기존 effective feature CREATE 권한이 있으면 GRANT/REVOKE를 모두 생략한다. 없을 때만 임시 CREATE를 부여·회수하고 GUC를 원복한다. 새 runtime EXECUTE나 테이블 권한은 없다.

## 영향도 범위

함수 서명은 그대로이며 기존 핵심 Python 컴포넌트는 수정하지 않는다. 정본 SQL caller인420 full-refresh validator/base-field validator/active mutation guard와421 legacy stamp writer를 직접 대조했다. Codegraph는 SQL SD 본문을 해석하지 않으므로 이 수동 SQL inventory를 graph PASS로 부르지 않는다.

## 동시성 경계

411 begin은 scope/attempt·source/head/link·Feature 잠금을 획득하고 같은 TX에서 applying/apply_txid를 기록한다. runtime의 ops attempt/manifest 직접 DML은 닫혀 있고 append는 preparing만, cancel은 applying 거부, 정리는 terminal만 허용한다. 따라서 일반 역할의 정상 진입 경로에서는 같은 TX의 applying 후보가 기존 두 RC 조회 사이 외부 writer에 의해 바뀌지 않는다. 이후 검증의 개별 RC statement는 그대로 유지한다. 명시적인 stateowner/schemaowner의 고권한 직접 변경까지 sandbox한다고 주장하지 않는다.

## 현재 실제 확인과 미완

- migration/역할/sidecar/receipt/graph/forward-only와 CREATE 권한 단위 회귀를 합쳐66 PASS, 기존1 skip(6.79초). 첫 초안은 revision35자 때문에2 FAIL/62 PASS였고 원 로그를 보존했다. 32자 이하 이름으로 고쳤으며 검사 기준은 그대로다.
- 첫 checkpoint의 무조건 CREATE GRANT는 상속 권한이 있는 경우 direct grant를 남길 수 있어 고쳤다. 원 upgrade fake-bind는 해당 경로1 FAIL/나머지1 PASS였고, 수정 뒤 두 경로2 PASS(0.36초)다. 실제 PG ACL 검증으로 세지 않는다.
- 고정 source `c6bb7943`에서 실제 경계9개가9 PASS(15.406초, 실패·오류·skip0)였다. 일반 runtime private EXECUTE 거부와 명시 owner catalog, 0·정확1·복수·optional dataset·SH·다른 TX·완료 replay를 확인했다. 복수는 두 dataset의 정본 claim/seal/begin으로 만들었으며 applying/txid 직접 쓰기가 아니다. 별도 고권한 manifest 부정 fixture는40001/23514와 savepoint 복구만 확인한다. 외부 public stamp writer의 실제 blocker PID 관계·55P03·새 TX 복구 및 business rollback을 확인했다. 복합 오류 전체 최초 실패순서/P0002/P0003 실측은 포함하지 않는다. 기존420 이후 검증 tail의 byte 동일 근거와 구분한다.
- 위9개 최초 감사 실행은 도구가 testcontainers의 실제 `{'5432': None}` 표현을 예상하지 못해 create RPC 전 setup오류9개로 멈췄다. 이 한 TCP 표현만 허용하는 수정 뒤 새 UUID로 실제9개를 실행했다. 첫 실패를 제품·시험 성공으로 다시 세지 않는다.
- 별도 공식 fresh bootstrap/oracle은1 PASS(20.551초, skip0)다. 기존 canonical `application_300_config`/덤프/비교 함수를 바꾸지 않고 감사 출력 경로만 분리했으며 runtime reconcile을 호출하지 않았다. 첫 시도는 외부 감사 시험의 `-c pyproject.toml` 누락으로 async fixture setup오류1개였고, 원 donor와 같은 설정 경로만 복구했다. 원 실패·실제9개·공식1개는 별도 원장이다.
- 공식 덤프와 두 번째 덤프는 동일하다. 부모422의1,641개 블록과 비교해1,639개가 byte 동일하며 context 함수 본문1개와 receipt의423 허용 literal1개만 바뀌었다. 전체 기존 ACL/함수 header·owner·config는 보존했다. 새 덤프를 `alembic/head-schema.sql`에 반영했다. 이는 이전422 오라클과 새423이 완전히 같다는 주장이 아니다.
- 두 실행 모두 정확한 owned CID·UUID label·익명 볼륨 정리를 확인했다. 자원2 CPU/1536MiB RAM·swap동일/PID256, 전체2378 Git blob/mode·SDK53 파일 전후·실제9개 project import hash를 검사했다. SDK import 확인을 실제 converter 동작 증거로 세지 않는다.
- 새 오라클 반영 뒤 offline lint373개와 기존 CREATE 단위2개를 함께 확인해375 PASS/기존6 skip(31.09초)이었다. 앞 정적66개와 중복 합산하지 않는다.
- 합성 source `a8cb6e56`에서 fresh schema423의 실제 API startup1 PASS(19.081초, skip0)를 별도 확인했다. 실제 uvicorn lifespan과 runtime DB preflight를 켜고 dependency override 없이 고정 GET3개(health200/무인증 admin403/정상 인증 admin200)를 확인했다. 준비 health poll1회는 별도이며 HTTP mutation·외부 HTTP 요청은0이다. 정본 runtime 역할·6개 실제 project import/Git hash·2379 archive blob/mode를 확인했다. SDK53은 준비 전과 실행 후 별도 대조했다. API/프론트 제품 tree는 기존 e5와 같으며 새19UI·BFF browser·C1 직접 효과를 검증한 것으로 세지 않는다.
- API는 고유 systemd unit의 1 CPU/1536MiB/PID128/60초와 PG 2 CPU/1536MiB/PID256 자원 아래 실행했다. API unit absent/PID0·정확 CID/UUID0·임시 lab/config 폐기를 확인했다. 외부 container metadata 변화0은 비원자 관찰이며 host network 격리를 보장하지 않는다. 생성된 lab 자격 증명이 포함될 수 있는 private raw audit는 보존하므로 모든 비밀이 폐기됐다고 쓰지 않는다. 운영 자격 증명은 사용하지 않았다.
- 비용은 아래 별도 함수 A/B 감사로 정산한다. 새 최종 HEAD의 전체 CI는 미완이고 기존0bac/c6bb/a8cb 세대와 섞지 않는다. collector 배선·운영 활성화는0이다. 원장은 `map423-owned-nine-r2-acceptance.json`, `map423-official-oracle-r2-acceptance.json`, `map423-api-startup-smoke-final-acceptance.json`이다.

## 후속 검증 범위

실제9개 밖의 모든 복합 최초 오류순서·cancel57014를 검증 완료로 확대하지 않는다. 이후 tail은 원문 보존했지만, 모든 SQLSTATE의 실제 회귀와는 별개다. 완료한 API startup의 preflight/HTTP 읽기와 기존 UI 제품 byte 보존, 새 SQL 동작의 증거를 구분한다. 운영 DB에 fixture를 쓰지 않았으며 최종 정확 CI·실제 collector/worker·큰 입력·운영 수용은 여전히 별개다.

## 비용과 범위

선행 stamp active100에서 context 호출5100이 기록됐지만 이번423의 새 개선 수치가 아니다. C1은 context 호출 수나 중복 candidate 검증 횟수를 줄이지 않는다. C2의 private scalar helper 추출·guard 이동은 범위 밖이다.

T가 고정 source `c6bb7943` archive와 owned DB1개에서 synthetic native100 insert를 A/B/B/A/A/B 순으로1회 실행했다(6/6 PASS, 전체135.04초). A는 기존420 함수 본문, B는423 본문이며 같은423 DB의 함수만 바꾼 비교다. 두 배포판 전체 비교나 a8cb의 batch phase 전체 성능 검증이 아니다. 최종 a8cb와 B의 SD 본문은 byte 동일하고, main1398 phase 변경은 승인 부모 blob 그대로 합성했다.

| 단계 중앙값(각3표본) | A | B |
| --- | ---: | ---: |
| apply wall | 11.527125s | 11.083977s |
| apply PG CPU | 10.631956 core-s | 10.334668 core-s |
| deferred constraints wall | 4.166930s | 4.573570s |
| deferred constraints PG CPU | 4.392365 core-s | 4.573256 core-s |
| 각 trial 두 구간 합 wall | 15.694055s | 15.657547s |
| 각 trial 두 구간 합 PG CPU | 15.024321 core-s | 14.907924 core-s |

각 표본의 서로 겹치지 않는 apply/deferred 구간을 먼저 더한 뒤 중앙값을 구했다. 합은 planning·commit·실제 collector 전체 시간이 아니다. apply는 줄었지만 deferred는 반대 방향이며, 표본 범위가 겹치고 차이가 작아 **뚜렷한 전체 CPU 개선은 입증하지 못했다**. 같은 DB의 warm cache·aborted tuple·attempt 누적·첫 A WAL 차이·함수 교체의 계획 이력이 남는다. RSS 전후 관측은 peak나 전용 메모리가 아니다. 기존10.4초·instrumented42초와 개선율을 비교하지 않는다.

모든 trial의 business rollback·fresh TX cancel·pool1 role/GUC 복원을 확인했고 원423 pg_get_functiondef·OID/owner/ACL/config/defaults를 복원했다. Git2378 blob/mode·SDK53 파일 전후·7개 actual import와 runtime backend0·정확 CID/UUID/global scalar0·익명 volume1 제거를 확인했다. SDK import pin은 실제 provider100 실행 증거가 아니다. 최종 원장은 `map423-context-ab-r1-final-acceptance.json`이며 별도 재실행0이다. 전체 SH collector/coordinator·large input·ARM·운영 효과는 주장하지 않는다.
