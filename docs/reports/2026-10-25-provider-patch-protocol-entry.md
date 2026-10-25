# 공개 provider patch의 protocol 진입 보강(426)

## 범위

기존 `apply_provider_feature_field_patch`는 source evidence와 Feature를 먼저 잠갔다.
직접 SQL 호출도 첫 실행문에서 기존 protocol EX를 얻도록 prefix 한 줄을 추가한다.
425의 UPDATE-first·fallback·인자검사·오류 순서·provider 검증·권한·owner는 그 뒤 그대로다.
protocol 경합/SH에서 EX 승격 거부가 기존 본문 검사보다 먼저 발생하는 점은 의도된 변경이다.
이는 legacy EX 진입 보강이며 실제 두 dataset SH collector를 활성화하지 않는다.

기존 protocol helper가 미설정 lock_timeout을1초로 제한하고 유한 caller cap은 보존한다.
Feature별 advisory lock을 추가하거나 tracking L을 data path에 새로 묶지 않는다.
수동 선행 row/advisory 잠금의 과거 취득 순서를 증명하는 기능은 아니다.

## migration과 남은 검증

425의 정확 prosrc SHA·인자·owner·SECURITY DEFINER·search_path를 대조한 뒤 교체한다.
임시 schema CREATE는 원래 없는 경우에만 부여/회수하고 짧은 caller timeout을 유지한다.
새 SQL은 prefix 제거 시 425 전체 정의와 byte 동일하다. 새 함수/ACL·API/DTO 변경은 없다.
새 migration/sidecar와 공개 signature 불변이므로 AGENTS의 신규 파일 영향도 예외를 적용한다.

현재는 구현 초안이다. 순수 migration 검증·독립 리뷰·실제 P 경합/SH 거부/정상 EX·rollback·
권한/GUC/OID/ACL·공식 fresh oracle·정확 CI를 각각 수용해야 한다. 기존 부모 head-schema는
426 oracle이 아니다. 실제 collector/strict SH closure/whole capture/RC·복구·운영은 미완이다.

집중 migration 순수6 PASS(최초0.31초), Ruff2파일·strict mypy1파일·문서 redaction을
확인했고 소스 독립 두 리뷰를 거쳤다. 실제 PG 수용·공식 oracle·정확 CI는 미완이다.


## 첫 실제 bootstrap 실패와 revision 길이 정정

첫40c/r3의 고유 fresh PG는 migration 식별자33자가 Alembic version_num varchar(32)를
넘어 22001로 실패했다. XML25개 모두 setupERROR(26.858초)이며 시험 본문은 실행되지
않았다. 원실패·로그를 보존했고 실제 CID/UUID/볼륨 정리는 완료했다. 이를25 PASS나
426 실행 경합 검증으로 세지 않는다. 운영 배포는 없었다.

식별자와 receipt 허용값·파생 graph만 `426_provider_patch_protocol`(27자)로 정정했다.
SQL sidecar·procedure 본문·기존 검증/권한은 그대로다. 기존 전수 길이 계약 시험도
수정 전1 FAIL(0.20초)로 재현했다. 같은 기존 시험을 다시 실행하며 별도의 중복 검사는
추가하지 않는다. 수정 source·실행기 재결박의 두 리뷰 뒤 새 고유 PG에서 다시 검증한다.
