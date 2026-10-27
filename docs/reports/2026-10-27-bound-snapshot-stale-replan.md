# bound snapshot의 정확 stale 뒤 재계획 복구

## 첫 범위와 아직 미재현인 경계

현재 Airport/Rest 실제 asset은 저장 artifact와 executor fence를 가진 전용 coordinator를
호출한다. 선택 stale로 atomic apply TX가 rollback된 뒤에도 기존 expired-plan reset은
READY lease가 유효하면55P03으로 거부한다. 이는 정적 코드에서 확인한 경계이며,
아래 실제 PG 재현 전에는 운영 장애가 발생했다고 단정하지 않는다.

첫 checkpoint는 기존 제품 코드 그대로 두고 Airport 실제 등록·plan·atomic apply에서
manifest Feature revision을 낡게 하여 정확40001→전체 rollback→liveREADY55P03을
관찰할 통합 시험 source다. 새 SQL/운영 실행은 아직0이며 source 두 독립 리뷰 후
소유 격리 PG에서만 재현한다. 실패하면 원 증거를 보존하고 실제 지점부터 교정한다.

## 제안하는 작은 제품 변경

기존 expired reset의 lease guard·ACL을 약화하지 않는다. 현재 executor generation/fence와
정확 bound attempt/owner/manifest에만 적용하는 typed rolled-back reset을 별도 additive
SQL로 추가하는 안을 검토한다. protocol→parent/scope→attempt→control 정렬 잠금 뒤
prepared control/READY plan/현재 owner·epoch를 검사한다. 살아 있는 apply가 있으면
기존 잠금 deadline으로 거부하고, 완료/취소/새 owner를 되돌리지 않는다.

이후 기존 Airport/Rest의 선택 ReplanRequired catch에만 연결한다. SDK0 read·storedbytes,
MAX_REPLANS3, executor lease/fence, 취소·원 결과·postprocess·child/root seal과
30초/reader3초/lock1초 상한을 유지한다. generic unbound cancel이나 전체 snapshot·지역·
새 identity·retire·profile enable은 범위가 아니다. T-CWRITE-01~09는 모두 미완이다.

구현/실제 재현/두 독립 적대 리뷰/최종 CI 및 운영 효과 수용은 아직 완료되지 않았다.

## 첫 source 확인

Ruff check/format과 fixture 설정을 실행하지 않는 collect-only1개(7.70초)가 통과했다.
실제 PG 재현·새 typed SQL 구현·운영 호출은 아직0이다. 기존 typed reset을 약화하지 않는다.
