# EX full-refresh context 후보 단일 조회(423, 부분 체크포인트)

## 문제와 구현

기존 `_exclusive_provider_refresh_context`는 같은 applying attempt/manifest 조건으로 count와 row SELECT를 따로 수행했다. 새423은 최대2행의 단일 SELECT에서 첫 행을 명시적으로 보관하고 0/복수는 false로 반환한다. 정확1행만 기존 protocol EX → candidate assertion → primary entity STRICT SELECT → 공개 scalar assertion 순서로 진행한다. 기존420 역사 파일, 이후 검증 본문, SQLSTATE, 권한·함수 서명·search_path·기본 EX 정책은 바꾸지 않는다. 예외를 정상0행 경로로 사용하거나 새로운 캐시/GUC를 추가하지 않는다.

마이그레이션은 원래 prosrc SHA256 `3dd92fbb11e8d8c8cdfdf3fb5e90f0a04a19b80d7d89ae95505a0733edfc2361`와 단일 catalog 함수의 signature/owner/언어/SECURITY DEFINER/volatile/결과/search_path를 확인한 뒤 기존 소유자로 CREATE OR REPLACE한다. protocol EX와30초 statement/1초 lock 상한을 유지하고 더 짧은 기존 설정을 보존한다. feature CREATE 임시 권한과 GUC를 원복한다. 새 runtime EXECUTE나 테이블 권한은 없다.

## 영향도 범위

함수 서명은 그대로이며 기존 핵심 Python 컴포넌트는 수정하지 않는다. 정본 SQL caller인420 full-refresh validator/base-field validator/active mutation guard와421 legacy stamp writer를 직접 대조했다. Codegraph는 SQL SD 본문을 해석하지 않으므로 이 수동 SQL inventory를 graph PASS로 부르지 않는다.

## 동시성 경계

411 begin은 scope/attempt·source/head/link·Feature 잠금을 획득하고 같은 TX에서 applying/apply_txid를 기록한다. runtime의 ops attempt/manifest 직접 DML은 닫혀 있고 append는 preparing만, cancel은 applying 거부, 정리는 terminal만 허용한다. 따라서 일반 역할의 정상 진입 경로에서는 같은 TX의 applying 후보가 기존 두 RC 조회 사이 외부 writer에 의해 바뀌지 않는다. 이후 검증의 개별 RC statement는 그대로 유지한다. 명시적인 stateowner/schemaowner의 고권한 직접 변경까지 sandbox한다고 주장하지 않는다.

## 현재 실제 확인과 미완

- migration/역할/sidecar/receipt/graph/forward-only 정적 검사64 PASS, 기존1 skip(6.66초). 첫 초안은 revision35자 때문에2 FAIL/62 PASS였고 원 로그를 보존했다. 32자 이하 이름으로 고쳤으며 검사 기준은 그대로다.
- 기존420 이후 검증 원문은 byte 동일하다. 새 함수의 role/ACL 실제 catalog 보존, migration 실적용·공식 head oracle, 실제0/1/2행·후속 오류 순서·timeout/동시성 회귀는 아직 실행하지 않았다. 현재 head-schema는 부모422 원본이며 새423 oracle 수용을 주장하지 않는다.
- 두 독립 소스 리뷰와 root의 CPU 슬롯 뒤에만 owned PG를 실행한다. 공개 API/UI·collector 배선·운영 활성화는0이다.

## 실제 시험 계획(미실행)

1. 기존 owned bounded fixture의 실제 claim/manifest/seal/begin과 공개 full-refresh 경로를 이용해0행 거부/정확1행 성공 및 기존 caller 회귀를 확인한다. 같은 TX에서 정본 수명주기로 복수 matching attempt를 구성할 수 있는지 먼저 확인한다. 불가능하면 권한 우회 fixture로 실제 경로를 꾸미지 않고 제한을 명시하며, 순수 PL/pgSQL 루프의0/1/2행 임시 fixture 검증과 구분한다.
2. candidate membership40001/closure23514가 primary STRICT 및 scalar revision 오류보다 먼저 실패하는 순서를 보존한다. 이후 primary STRICT P0002/P0003, revision40001/shared entity23514/target23514를 가능한 정본 fixture에서 대조한다. timeout55P03/cancel57014를 fallback으로 삼키지 않는다.
3. 실제 함수 owner/ACL/config/signature를 적용 전후 비교하고 protocol/epoch/attempt 잠금과 원자 rollback·같은 연결 GUC 복구를 확인한다. 기존 unmodified canonical bootstrap으로 공식 oracle을 생성·비교한다.

## 비용과 범위

선행 stamp active100 관찰에서 context 호출5100이 기록됐지만 이는 이번423의 개선 수치가 아니다. C1은 context 호출 수나 중복 candidate 검증 횟수를 줄이지 않는다. 실제 CPU/elapsed 개선은 미측정이며 반복 SELECT 한 번 절감의 효과를 추측하지 않는다. C2의 private scalar helper 추출·guard 이동, 전체 SH collector/coordinator·large input·운영 수용은 범위 밖이다.
