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

## migration 계약과 최초 검증 이력

425의 정확 prosrc SHA·인자·owner·SECURITY DEFINER·search_path를 대조한 뒤 교체한다.
임시 schema CREATE는 원래 없는 경우에만 부여/회수하고 짧은 caller timeout을 유지한다.
새 SQL은 prefix 제거 시 425 전체 정의와 byte 동일하다. 새 함수/ACL·API/DTO 변경은 없다.
새 migration/sidecar와 공개 signature 불변이므로 AGENTS의 신규 파일 영향도 예외를 적용한다.

최초 초안 단계의 검증 계획은 순수 migration·독립 리뷰·실제 P 경합/SH 거부/정상 EX·rollback·
권한/GUC/OID/ACL·공식 fresh oracle·정확 CI를 각각 수용해야 한다. 기존 부모 head-schema는
426 oracle이 아니다. 실제 collector/strict SH closure/whole capture/RC·복구·운영은 미완이다.

집중 migration 순수6 PASS(최초0.31초), Ruff2파일·strict mypy1파일·문서 redaction을
확인했고 소스 독립 두 리뷰를 거쳤다. 당시 실제 PG·공식 oracle·정확 CI는 미완이었다.


## 첫 실제 bootstrap 실패와 revision 길이 정정

첫40c/r3의 고유 fresh PG는 migration 식별자33자가 Alembic version_num varchar(32)를
넘어 22001로 실패했다. XML25개 모두 setupERROR(26.858초)이며 시험 본문은 실행되지
않았다. 원실패·로그를 보존했고 실제 CID/UUID/볼륨 정리는 완료했다. 이를25 PASS나
426 실행 경합 검증으로 세지 않는다. 운영 배포는 없었다.

식별자와 receipt 허용값·파생 graph만 `426_provider_patch_protocol`(27자)로 정정했다.
SQL sidecar·procedure 본문·기존 검증/권한은 그대로다. 기존 전수 길이 계약 시험도
수정 전1 FAIL(0.20초)로 재현했다. 같은 기존 시험을 다시 실행하며 별도의 중복 검사는
추가하지 않는다. 수정 source·실행기 재결박의 두 리뷰 뒤 새 고유 PG에서 다시 검증한다.


## 두 번째 실제 실행의 catalog 시험 가정 정정

7bcc/r4는 head27 bootstrap을 통과했고25개 중24 PASS/1 FAIL(21.915초)이었다.
직접 P 경합·NOWAIT5행·유한/기본 timeout·GUC/rollback·SH 오류·EX 재진입과 기존15개는
실행됐지만, 새 catalog 시험이 owner의 CREATE를 무조건 false로 가정해 실패했다.
정본 fresh bootstrap은 owner에 USAGE,CREATE를 부여하고 migration은 그 기존 권한을
보존한다. 제품 권한 누수가 아니며 권한 회수나 fixture 변경으로 시험을 통과시키지 않는다.

기대값만 정본 True로 맞추고 실제 runtime/service의 feature CREATE는 False인지
확인한다. 원24/1 실패·시험 후 source/SDK 전체 검증 미실행을 보존하며, 실제 CID/UUID/볼륨
정리는 완료했다. 수정본 두 리뷰·다음 고유 실행 전에는25개 수용 완료로 표시하지 않는다.


## 최종 실제25와 공식 fresh oracle

위 두 원실패는 보존한다. 수정 ed8/r5는 새 고유 PG에서25 PASS/실패·오류·skip0
(23.098초)이었다. 공개 patch의 실제 P 대기·다른 backend의5행 NOWAIT·유한250ms와
기본1초 timeout·SAVEPOINT GUC 복원·전체 rollback/새 retry·bare SH23514·EX 재진입,
기존425의15개 및 catalog owner CREATE 보존/runtime CREATE 거부를 확인했다.
source2395 Git mode/blob·실제9 import·SDK53개 전후 pin도 대조했다.

별도 새 고유 PG의 정본 application300 bootstrap/공식 반복덤프 비교는1 PASS
(20.369초)였다. runtime reconcile는 호출하지 않았다. 새426 oracle SHA256은
`02751bc4c380d6822499905a19d33a3a6b86609cd27a2e52ba01182dcefea827`이다.
부모425의1643개 block 중1641개는 완전히 같고 공개 patch 첫 prefix와 receipt의
허용 head27자만 다르다. 이 둘을 되돌리면 부모 덤프 전체 byte와 같으며 ACL/default ACL도
그대로다. 두 실행 모두 정확 CID·UUID·익명 volume 및 전체 감사 container 정리를 확인했다.

소스와 실행기 두 독립 리뷰·실제25 사실 대조를 거쳤다. 이 검증은 직접 legacy EX 경로의
수용이며 공식 oracle을 교체한다. 최종 부모 CI 수정 상속·정확 전체 CI와 운영 배포는 아직
미완이다. 실제 두 SH collector·57 호출자 폐쇄·fresh RC·whole capture·durable recovery를
완료로 표시하지 않는다. SDK pin 검사는 실제 SDK 변환 실행 증거가 아니다.
