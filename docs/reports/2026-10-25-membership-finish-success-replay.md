# 성공 root의 후속 membership 완료 호출

## 문제와 범위

entry guard가 통과한 뒤 다른 executor가 child seal과 root SUCCESS를 commit할 수 있다.
SDK0 재개 runner가 원 receipt를 복원해도 공개 wrapper의 후속
finish_dagster_feature_membership는 root done을 먼저 차단해 실패했다.
원 함수는 실행 중 root의 이미 done인 member에는 쓰기 없이 noop을 반환했다.

이번 변경은 공통 repository 함수의 정상 완료 재관측에만 한정한다.
Airport 전용 decoder·receipt 판단을 공통 wrapper에 복제하지 않는다.
API·DTO·권한·SQL procedure·transaction ownership·runner는 바꾸지 않는다.

## 허용하는 한 경계

기존 P EX → L → root 및 cancellation-root 잠금을 그대로 취득한다.
root가 done이면서 Dagster 상태가 SUCCESS인 경우에만 frozen selection의
정확한 dataset/scope/operation member를 해석한다. member도 done이어야 한다.
추가 SELECT EXISTS는 원 root/child/member UUID와 run ID, 단일 membership,
root/child의 취소 ID·취소 요청 시각·격리 부재를 재확인한다.

그때만 원 operation을 noop으로 반환하며 seal·finish·추가 event·상태 DML은 없다.
root가 failed·cancelled이거나 done이지만 SUCCESS가 아니면 기존대로 차단한다.
root 취소 ID 검사도 기존 우선순위를 유지한다. 없는 frozen member는 불변식 오류,
끝나지 않은 child 또는 안전성 재확인 실패는 terminal 차단이다.
격리 root는 기존 조회에서 부재로, 격리 child는 frozen member 부재로 거부된다.
실행 중 root의 기존 member done noop와 정상 신규 완료 경로는 그대로다.

정상 종료 뒤의 원완료 읽기는 새 성공 권위를 만들지 않는다.
특히 authoritative_snapshot_complete=True 호출이라도 새 receipt를 만들거나
과거 비권위 완료를 권위 완료로 바꾸지 않는다. snapshot 결과 복원과 receipt 증명은
별도 typed runner가 담당하고, 이 함수는 저장된 tracking 완료만 읽는다.

## 영향과 확인

기존 Codegraph index의 정확 production 심볼과 current source 직접 참조를 함께 확인했다.
client의 한 repository 호출과 Dagster 공개 wrapper 두 call site가 영향 경계다.
오래된 index의 SQL 미분석·alias 및 fake execute 간선 한계는 유지한다.
새 index·container는 만들지 않았다. private 영향도 원장 SHA256은
e7fb3adef5b76462902fbb992572ca420542aad1499f9a3a94f88480c56c3a43이다.

수정 전 직접 회귀는 5 FAIL/6 PASS였다. 그중 정상 완료 재호출이 blocked로 반환되는
원 반례와, 새 계약인 frozen membership 오류/추가 재확인 미도달을 분리해 보존했다.
수정 후 새 11개와 기존 계약 시험을 합쳐 64 PASS다. Ruff와 제품 모듈 strict mypy도 통과했다.
통합 시험 3개는 정본 ensure → member finish → reconcile의
SUCCESS·FAILURE·CANCELED 이후 호출과 tracking/receipt 전체 불변을 준비했다.
SUCCESS에서는 dataset/scope/operation 세 축의 다른 member 거부도 확인하도록 했다.
이 3개는 정본 scalar_container/scalar_engines의 자원 제한과 자동 회수를 재사용한다.
공유 migrated_engine을 기동하지 않는다. Root의 명시 승인으로 고정 687febfdc source에서
한 번 실행하여 3 PASS/skip0, XML suite 13.986초를 확인했다.
SUCCESS는 정확 member noop·다른 triple 세 축 오류·tracking/receipt 전체 불변,
FAILURE/CANCELED는 terminal 차단과 같은 상태 불변을 통과했다.
이는 같은 outer transaction의 실제 lifecycle 검증이며 물리 두 worker commit 경합 실증은 아니다.

실제 Git 2508개 blob/mode와 SDK 53개 전후 대조, 34개 import 경로·SHA,
head430을 확인했다. 정확 CID와 UUID label은 부재, 익명 volume 1개 부재,
runner 최종 global scalar label 0과 정리를 확인했다. 슬롯 반환 뒤 독립 읽기에서도
정확 CID/UUID/volume 부재와 source/SDK 전체를 재확인했다.
원 raw 8개·XML·result의 SHA는 private 원장
map430-membership-finish-replay-687-actual-facts.json에 보존했다.
Root/J 소스 검토는 각각 독립 통과했으며 수정 전 회귀 FAIL도 그대로 남겼다.

base는 cdfdc7aa39698e0fcf3749c0da72497bb5ff510b이다.
기존 PR1410 head/branch와 W 소유 runner는 수정하지 않았다.
최종 430 통합·최종 후보 live UI 검증은 별도 미완이고 운영 변경은 없다.
