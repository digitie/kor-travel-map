# expired plan reset의 applying holder 정본 guard fixture

## 후속 최종 CI·머지 상태

이 fixture를 포함한 최종29f1594b의 전체 CI는5 workflow/10 check 모두 성공했고
Map #1411은5f3506a로 머지됐다. glibc1905 PASS/23 SKIP, Alpine1899 PASS/29 SKIP이며
두 lane 모두 원 실패 node를 포함한다. 아래의 전체 CI 미완 표기는 당시 단일회귀
checkpoint의 한계로 보존한다. 이후 최종 pair의 공식 배포·schema430/0102·7 healthy를
수용했지만 첫 공개 읽기 UI는 Map 로그인401로 실패해 PinVi 미도달이다. 후속 공개 R7 인수·
원 일정 복원도 별도 수용했으며 해당 초기 실패는 보존한다. [운영 정산](2026-10-25-pinvi-admin-feature-read-scope.md).
최종 CI 수용 SHA-256은
`18be481471666782b9a3893726eab8c342016f9e223d9f475db9614d43a9c2db`다.

## 원 실패와 원인

Map860967df의 glibc CI는1904통과·23skip·1실패, Alpine은1898통과·29skip·1실패였다. 두 실패는 test_applying_holder_blocks_reset_then_rollback_allows_expired_reset의 실제 holder begin에서 발생한 strict statement guard definition drift 23514이며 waiter 생성 전이다. 원 로그와 원 source를 보존한다.

해당 테스트가 받던 scalar_engines는 정본300→head bootstrap과 runtime ACL만 구성한다. strict guard33개는 자동 설치하지 않는다. _registered가 재사용하는 등록 준비 역시 guard를 설치하지 않는다. 이 파일의 다른 reset 경로는 apply begin을 호출하지 않으므로 해당 설치 전제를 요구하지 않는다.

holder는 ops.begin_provider_snapshot_apply의 실제7개 인자를 호출한다. 정본430 begin은 kernel begin 뒤 _assert_strict_sh_data_guard_inventory()의 기본 require-all 검증을 수행한다. 설치되지 않은 guard를 정상 drift 오류로 거부한 것이며, 이 원장만으로 기존 trigger 정의가 변경됐다고 단정하지 않는다.

## 최소 수정

해당 한 테스트만 기존 tests.integration.test_strict_sh_data_guards.strict_engines를 명시적으로 받는다. 이 정본 fixture는 owned 관리자 트랜잭션에서 P EX를 먼저 잡고 schema-owner 역할로 기존 private installer를 호출한다. 다른 테스트·공유 fixture·제품 SQL·정본 inventory·권한은 변경하지 않는다.

원 적용 holder→reset waiter의 실제 blocker 관측·55P03·holder rollback→lease 만료→정확 reset·취소 상태·binding null 단언,35초 전체 상한과3초/900ms SQL 상한을 그대로 유지한다. 가짜 applying 행이나 guard disable, 임의 DDL/GRANT를 추가하지 않는다.

## 검증과 한계

수정 전 CodeGraph 영향도는 해당 테스트 함수와 파일의2node/1edge이며 pytest의 동적 fixture 주입은 별도로 정본 source와 직접 대조했다. 소스 역치환은 새 fixture import와 이 테스트의 fixture 변수명만 복구하면 부모 전체가 같아야 한다.

Ruff·정확 한 node collection과 Root/J 독립 소스 검토를 통과했다. c265f90c 고정본의 fresh owned PG430에서 해당 한 case가15.044초에 통과했다. 원35초 전체 상한·3초/900ms SQL 상한·blocker/55P03/rollback/reset 단언은 유지했다. 운영 변경과 추가 재실행은0이다.

실제 XML은1 PASS·실패/오류/skip0이고, 실제 import 원장의37개 모듈을 고정 Git source와 대조했다. tracked2523개 mode/blob·SDK53개는 실행 전후 및 별도 읽기 전용 후관찰에서 같았다. 원raw8개 SHA를 재계산했고, 정확 CID 부재·UUID/global scalar label0·anonymous volume1개 부재를 저장 결과와 별도 Docker 조회로 확인했다.

실행기 완료 요약에는 donor의 tests=3·actual_project_imports=34 상수가 남았다. 원 result를 고치지 않고 별도 수용 원장 map-reset-guard-fixture-owned-r1-actual-acceptance.json에 XML1/import37을 직접 검산해 기록했다. 실행 중에도 len(cases)==1과 len(imports)==37을 검사하고 통과했으며, 이 두 요약 필드는 실제 수로 사용하지 않는다.

원 glibc/Alpine CI 각1 FAIL은 보존한다. 이 실행은 수정한 한 case의 cold guard 설치 전제를 검증한 것이며 전체 CI 재수용·물리적 worker commit 경합·운영 배포·기존8609 후보 UI/build의 새 실행을 뜻하지 않는다. 최신 최종 통합 후 정확 head의 CI는 별도로 필요하다.
