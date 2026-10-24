# state/lifecycle SQL의 protocol-first 폐포(415)

## 변경과 불변 범위

기준은 통합 후보 `52949b5f4183bf63593eaabffe562455113451f4`의 schema414다. 다음5개
SECURITY DEFINER procedure의 첫 BEGIN에 기존 protocol EX를 한 줄씩 넣는다.

- `transition_admin_feature_state`
- `reactivate_admin_feature_state`
- `transition_feature_state`
- `author_lifecycle_override`
- `revoke_lifecycle_override`

outer admin/reactivate → core → lifecycle author를 함께 보강해 내부 호출자가 이미 행을
잠근 뒤 새 EX를 기다리는 역순을 만들지 않는다. direct lifecycle revoke도 같은 진입을 쓴다.
기존 provider load/retire·merge는 이미 Python EX 아래이며, M05는414의 첫 EX 뒤 이 core에
재진입한다. 일반 admin route는 command advisory/claim과 일반 identity 조회 뒤 CALL하므로
Feature/source 행 선점이 없다. Reactivate의 기존 source→link→Feature 순서는 보존한다.

5개 owner와 protocol 함수 owner는 모두 `ktm_feature_state_procedure_owner`다. 추가 EXECUTE
권한은 없으며 PUBLIC/runtime ACL·search_path·서명·본문을 보존한다. 현재 signature/prosrc
SHA256·owner/prokind/SECURITY DEFINER/PLpgSQL와 검토한 첫 BEGIN 모양을 확인한 뒤 원래
정의에 EX 한 줄만 삽입한다. 임시 schema CREATE와 caller의 기존 더 짧은 timeout을 보존하고,
성공 뒤 GUC와 정본 schema owner를 원복한다. 실패는 같은 DDL transaction에서 rollback한다.
receipt 허용 head 목록에415를 추가하고 공식 migration graph/head oracle도 갱신한다.
forward-only이며 기존 본문·정책 seed·자동 수집·Python 업무 source·API/DTO를 바꾸지 않는다.

## field override와 새 identity는 별도

phone/address는1380에서 첫 행 잠금 전 EX를 확보하지만 field author 전체 caller는 다르다.
일반 admin patch의 `_state_for_conflict`는 먼저 Feature를 잠그며, manual 생성은 identity
claim/core/subtype 뒤 author를 부른다. 이 경계까지 닫지 않은 field SQL의 EX 추가는 새
역순을 만들 수 있어415에 섞지 않는다. create/purge/provider patch·catalog·Geo·지역 이동과
임의 외부 caller가 이미 행을 잠근 사용법까지 전수 지원했다고 주장하지 않는다.

active scalar 정책은 현재 name/phones만 지원한다. state/lifecycle5개 진입을 보강해도
lifecycle/publication/quality 또는 lifecycle override를 새로 허용하지 않고 기존23514 거부와
전체 rollback을 유지한다. 제한 scalar 활성화·지원 범위 확대·운영 전환은 별도다.

## 실제 검증

- 전용 UUID name/label/정확 ID PostGIS, 2CPU·memory=memory+swap1536MiB·PID256. 실제
  full bootstrap/runtime ACL reconcile 뒤 fresh runtime으로 실행했다. 공유/운영 DB·원천
  HTTP·배포·flag 변경은0이다.
- 최종 **실제 PG36 + 순수5 = 41 passed(16.63초)**. 각 공개5개의 valid CALL은 실제
  `begin_scoped_feature_write`가 쥔 SH/source/head/Feature 뒤 정확 protocol EX
  mode/key/blocker PID에서 기다리고, finish/commit 후 정상 완료해야 한다.
- 유효 admin retire→core→lifecycle author와 source 검증 reactivate→core의 row revision/
  audit exact identity, 기존 Python provider retire, M05의 실제 `merged`와 `manual_retired`
  2개가415 core에 재진입하는 결과를 확인했다. `kept`만으로 nested state를 수용하지 않는다.
- SH→EX 승격5개는23514·상태/override/audit/source hash 불변·새 caller TX 정상 재호출,
  성공한 CALL의 caller rollback5개는 값/감사 불변·잠금 해제·재호출을 확인했다.
- active scalar 정책에서5개 state/lifecycle 변경을23514로 거부하고 후보/base/effective·
  source·override/audit hash가 유지되는지 확인했다. stale40001·부재P0002·no-op23514와
  비인가 procedure-owner의42501도 실제 PG로 확인했다.
- 5개 prosrc에서 EX 한 줄을 제거한 bytes SHA가414 원문과 같고 owner/search_path/
  runtime EXECUTE·PUBLIC 폐쇄를 대조했다. 실제 fixture의 자원 제한을 inspect하고 최종
  정확 ID의 SDK NotFound·동일 UUID label 잔존0을 확인했다.
- 공식 oracle 기록은 **1 skipped(14.83초)**이며 비교 성공으로 세지 않는다. 비교/metadata
  재검증·전체 lint·정확 CI·독립2리뷰·추가 HTTP/UI는 아직 후속 gate다.
- 변경 Ruff PASS, migration strict mypy1 PASS. 공유 venv/index는 변경하지 않았다.

초기 집중은33 passed/8 failed(21.70초)였다. active-policy 회귀가 전역 guard를 설치한 뒤
기존 M05 seed가 EX 없이 새 행을 쓰는 시험 준비 오류였다. trusted admin seed TX에만 기존
EX를 명시했고 관측 대상 runtime CALL은 바꾸지 않았다. 제품 guard를 완화하지 않았다.
수정 뒤41 passed/17.17초는 중간 실행이며 최종 resource inspect 포함16.63초와 합산하지
않는다. 원본 실패·중간·최종 로그와 정리 증거는 별도 감사 보관소에 보존한다.

기본 OFF·정책 seed0·운영0이다. 전체 SQL writer/identity·membership·Geo·지역·Dagster 감독/
lease/host 장애·운영 ARM 비용과 T-CWRITE 전체 acceptance는 미완이며 mixed binary/drain
확인 전 설치·활성화하지 않는다. 기존 reader/kernel UI12를 이 새 mutation의 UI 수용으로
세지 않는다. 취소된 Weather/Transport export 운영 활성화는 재개하지 않는다.
