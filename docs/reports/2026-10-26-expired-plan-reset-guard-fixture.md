# expired plan reset의 applying holder 정본 guard fixture

## 원 실패와 원인

Map860967df의 glibc CI는1904통과·23skip·1실패, Alpine은1898통과·29skip·1실패였다. 두 실패는 test_applying_holder_blocks_reset_then_rollback_allows_expired_reset의 실제 holder begin에서 발생한 strict statement guard definition drift 23514이며 waiter 생성 전이다. 원 로그와 원 source를 보존한다.

해당 테스트가 받던 scalar_engines는 정본300→head bootstrap과 runtime ACL만 구성한다. strict guard33개는 자동 설치하지 않는다. _registered가 재사용하는 등록 준비 역시 guard를 설치하지 않는다. 이 파일의 다른 reset 경로는 apply begin을 호출하지 않으므로 해당 설치 전제를 요구하지 않는다.

holder는 ops.begin_provider_snapshot_apply의 실제7개 인자를 호출한다. 정본430 begin은 kernel begin 뒤 _assert_strict_sh_data_guard_inventory()의 기본 require-all 검증을 수행한다. 설치되지 않은 guard를 정상 drift 오류로 거부한 것이며, 이 원장만으로 기존 trigger 정의가 변경됐다고 단정하지 않는다.

## 최소 수정

해당 한 테스트만 기존 tests.integration.test_strict_sh_data_guards.strict_engines를 명시적으로 받는다. 이 정본 fixture는 owned 관리자 트랜잭션에서 P EX를 먼저 잡고 schema-owner 역할로 기존 private installer를 호출한다. 다른 테스트·공유 fixture·제품 SQL·정본 inventory·권한은 변경하지 않는다.

원 적용 holder→reset waiter의 실제 blocker 관측·55P03·holder rollback→lease 만료→정확 reset·취소 상태·binding null 단언,35초 전체 상한과3초/900ms SQL 상한을 그대로 유지한다. 가짜 applying 행이나 guard disable, 임의 DDL/GRANT를 추가하지 않는다.

## 검증과 한계

수정 전 CodeGraph 영향도는 해당 테스트 함수와 파일의2node/1edge이며 pytest의 동적 fixture 주입은 별도로 정본 source와 직접 대조했다. 소스 역치환은 새 fixture import와 이 테스트의 fixture 변수명만 복구하면 부모 전체가 같아야 한다.

Ruff와 정확 한 node의 collection을 먼저 확인한다. 제품·기존 원 단언은 그대로이며 실제 PG의 한 case 검증은 두 독립 소스 리뷰와 별도 단일 슬롯 실행 뒤 정산한다. 아직 새로운 PG 실행·운영 변경은0이다. 기존8609 후보 UI/build를 새 시험 준비의 PG 수용으로 대신하지 않는다.
