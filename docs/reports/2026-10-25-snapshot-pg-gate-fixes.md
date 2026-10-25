# 430 전체 PG gate의 첫 원인 수정

## 현재 상태

최종 후보7f40 CI glibc는118FAIL/1768PASS/23SKIP/30ERROR(978.50초)였다.
원문 전체4MB와 모든148개 node는 원장에 보존했다. 이 결과를 분리된 owned 시험의
성공으로 덮지 않는다. Alpine 원문은 별도 정산한다. 운영 배포는 보류했고 새 PG는 아직0이다.

## 실제 canonical projector 문제

`recompute_provider_field_candidates`는 private projector를 호출한다. 원 projector의
INSERT ON CONFLICT는 기존 base와 값이 같아 UPDATE가0건이어도 BEFORE INSERT를 먼저
실행한다. 낮은 순위 provider의 정상 SH 관측이 unchanged foreign winner를 재투영할 때
strict guard의 own dataset 검사에 걸렸다. 기존 scalar 두 순서 시험이 이 경로로 실패했다.

새430 sidecar는 완전히 같은 base(provider/entity/record/hash/JSON/geometry/observed_at)가
있으면 INSERT문 자체를 건너뛴다. 실제 변경은 기존 UPSERT/WHERE와 Feature projection을
그대로 실행한다. owner/security/search_path/ACL/guard·권한·한도 변경0이고412 원본은 보존했다.
원 UPSERT와 나머지 body는 조건부 블록을 역제거하면 전체 byte가 같다.
반복 foreign winner의 base revision/updated clock이 그대로인지와, 같은 manifest Feature의
진짜 foreign base 변경이 계속23514/rollback되는지 새 paired source 두 개를 추가했다.
실행 전 두 source 리뷰가 필요하며 실제 통과를 선기록하지 않았다.

## 시험 계약/정리 원인

- canonical 관리자 tree cleanup은 첫 raw tracking UPDATE 전에 정본 P EX→L을 취득한다.
  같은 helper를 부르는 reconcile 시험의 finally가 본체 결과를 cleanup23514로 덮던 원인이다.
- tracking prefix 시험은 정상 finalizer 입력을 새 RC로 실행하며 L-only 및 actual P waiter의
  원23514/55P03 단언을 유지한다. 별도 SERIALIZABLE 조기거부 시험은 그대로다.
  430이 교체한 세 body는 실제430 공식 golden 전체본문에 대조하고 나머지는424 inverse를 유지한다.
- registered legacy finish negative fixture는 kernel claim 전에3s/900ms를 명시한다.
  원6개23514/private marker 부정 단언은 그대로다.
- reset fixture는 해당 testcase가 생성한 `reset-plan:` ready attempt만 정본 typed cancel로
  해제한다.60초 lease owner가 다음 case를 막던 연쇄를 제거하며 기존 reset/CAS/rollback
  단언과 owner 비교는 변경하지 않는다.

공유 conftest/기대값 삭제/실패 숨김/blanket runtime prefix 추가0이다. Root가 별도 소유한
batch/pipeline cancellation 정리 파일은 이 브랜치에서 편집하지 않는다.

## 검증과 남은 수용

25 unit PASS1.82초와 관련63개 통합 수집을 확인했다. 최초 Ruff 줄길이/비동기 파일읽기
정적 실패는 수정 전 로그로 보존했다. 실제 SQL 설치/paired·원모듈 회귀/새 공식 golden 및
전체 두 PG CI의 재수용은 미완이다. 추가 canonical/TVN40의 raw seed·RC 변경과 오래된
source-only RR 시험의 새 prefix 경계도 원로그 callsite를 계속 분류한다.

원 CI log SHA: `89f14fecf6522541a947e78024fc9f050cacecdb742eb48d32a6f51cb0018fc0`.
148 node inventory SHA: `d9ae88e8360872d8962b55b9e785be69acb6b62db069532e798932cf3d77d737`.

## old RR fixture와 winner handoff의 별도 범위

source-only old RR의 첫 INSERT가 missing-P23514에서 중단되던 source는 history record를
별도 정확EX seed로 준비하고, old RR snapshot→외부 cutover→명시 P EX→원head UPDATE로
정렬했다. 원40001/head불변 단언은 그대로며 fresh first-party 진입 성공을 주장하지 않는
수동 old-RR 부정 시험이다. canonical lifecycle의 직접 성공 TX도 RC로 바꾸고, 별도
SER 조기거부 시험은 유지했다. 제품/guard 변경은 앞선 no-op sidecar 외에 없다.

정본 winner는 `removed` 후보를 지원하므로 A 제거→B 실제 handoff는 일반 의미에 포함된다.
현재 shared/exclusive scalar API는 자동 fallback을 하지 않으며, 진짜 foreign base 변경은
계속23514다. 최초 durable Airport의 unchanged raw profile에서는 그런 변경을 진입 전
배제하지만 일반 remove policy의 handoff는 별도 fresh EX plan/apply가 필요하다.
no-op 수정으로 이 경계의 SH 지원까지 완료했다고 주장하지 않는다. 기존 foreign 변경
부정 시험은 유지하며 EX handoff paired proof는 별도 미완이다.

추가 actual source는 canonical policy2의 `omitted_policy=remove`와 양 provider의 정본
후보 capture를 사용한다. SH에서 A name 제거→B winner 선택은23514/원head·base rollback을
확인하고 그 ready plan을 typed cancel한 뒤 새EX attempt로 같은 raw/hash/관측시각을 적용한다.
B winner 출처·A removed 상태·own phones·원시각 및 두 attempt의 cancelled/completed까지
대조할 계획이며19개 scalar 수집/Ruff만 확인했다. 실제 결과는 아직 미완이다.
