# ADR115 불변 정책과 원천별 shadow 후보 — 기반 단위

## 변경과 미완 경계

410 migration은 완결된 정책 fieldset과 source별 shadow 후보를 추가한다. 정책 등록은
schema 관리자만 하며 runtime은 typed recorder만 호출할 수 있다. 실제 수집 경로는 아직
이 recorder를 호출하지 않는다. 기본 OFF이며 native load_bundle/settings/FeatureBundle
배선은 별도 후속이다. 기존 base/effective·override·seal·identity·전역 잠금 범위는 그대로다.
공개 API/OpenAPI/TypeScript 타입은 변하지 않고 PinVi 재vendor도 필요 없다.

T-CWRITE-02 전체 완료가 아니다. 전체 활성 membership backfill/완전성 gate, 실제 provider별
우선순위·누락/정규화 증거, 결정적 winner 물화·정책 활성화, Geo 일관 그룹, merge redirect와
T-CWRITE-03 scope/epoch/manifest가 남는다. 운영 정책 seed나 자동 enable은 없다.

## 불변 정책 등록과 잠금 순서

- 정책 한 행은 `(policy_revision, provider_dataset_id)` header와 normalizer_revision,
  정렬된 완결 fieldset JSON이다. 각 field의 명시 rank, omitted carry_forward/remove,
  null remove/value를 검증한 뒤 register_provider_field_shadow_policy 한 호출에서 등록한다.
  fieldset은 최대256개/입력128KiB이며 registry에 없는 필드·중복·빠진/추가 키를 거절한다.
- 동일 revision에 같은 normalizer/fieldset을 다시 등록하면 같은 행을 쓴다. 필드 추가/삭제나
  정책 변경은 첫 capture 전에도 거절한다. UPDATE/DELETE는 불변 trigger가 항상 거절한다.
  별도 field행 DML이나 runtime 정책 등록 권한은 없다. DB/schema 소유자의 DDL 우회 권한은
  기존 신뢰 경계이며 운영 수집 권한에 부여하지 않는다.
- 등록 진입점에서 **global fence를 먼저** 획득하고 나서 INSERT/unique key에 접근한다.
  ROW UPDATE trigger에서 fence를 기다리면 관리자(policy row→global)와 수집(global→policy)이
  교착하므로 그 구조를 쓰지 않는다. 기존 revision은 불변이므로 reader가 fieldset을 읽은 뒤
  추가 필드가 생기는 상황도 없다. RR snapshot에서 새 revision이 보이지 않으면 미설정 또는
  serialization 오류로 실패하며, 일부 필드만 승인한 것으로 간주하지 않는다.
- 후보 recorder도 기존 global fence 아래 현재 dataset/entity/record/head/source link와 Feature를
  검증한다. 실제 dataset/지역별 동시 쓰기는 아직 허용하지 않는다.

## 원문·누락·typed 값

- standalone ProviderFieldPresence가 실제 supplied field paths와 normalizer revision을 명시한다.
  완성 DTO의 기본 None을 원천 explicit null로 추정하지 않는다. 현재 운영 normalizer는 이 증거를
  만들지 않으므로 후속 실제 수집 hook의 enable gate가 필요하다.
- R1의 value record/hash와 R2의 validated-through current head record/hash를 분리한다.
  R2가 phone을 생략해도 명시 carry 정책이면 R1 값·원문을 유지하고 R2 검증만 진행한다.
- 미제공 presence, 최초 omitted 값의 원문 부재는 unresolved다. address/행정코드·geometry·관계
  identity 그룹도 아직 Geo/merge 증거가 없어 unresolved다. 정상 승인 scope로 해석하지 않는다.
- recorder는 registry JSON 종류뿐 아니라 실제 target column의 PG 타입도 검사한다. 소수/범위초과
  integer, 잘못된 UUID/날짜, timezone 없는 timestamp, 숫자/문자열의 손실 변환을 거절한다.
  날짜는 ISO 달력일, timestamp는 명시 offset/Z가 있어야 한다.
- availability=value는 해당 원천 typed 값의 기록이며 dataset 전체 membership·원생 테이블의
  모든 열 CHECK/다중필드 제약·최종 winner eligibility의 승인을 뜻하지 않는다. winner 후속은
  기존 native DML 제약과 현재 membership/head/정책/Geo gate를 모두 유지해야 한다.
- raw payload는 복제하지 않고 immutable source record를 FK로 참조한다. geometry column은
  준비하지만 이 기반 단위에서 Geo 그룹 후보를 승인하지 않는다.

## 권한·마이그레이션·회복

정책·후보 표의 runtime 직접 DML은 닫고 SECURITY DEFINER recorder의 search_path는 pg_catalog로
고정한다. 정책 등록은 schema 관리자 전용이며 후보 recorder owner에게도 등록 EXECUTE가 없다.
DDL lock1초/statement30초 상한은 더 짧은 caller 상한을 보존하며 성공 뒤 원래 설정을 복구한다.
migration은 forward-only다. 오류는 같은 transaction으로 rollback하므로 후보 일부만 남지 않는다.

현재 기본 OFF/운영 변경0이다. 미지원 provider/Geo 필드나 기존 누락 후보가 남아 있으면 정책
활성화와 잠금 세분화를 허용하면 안 된다. 운영 CLI·정책 UI·자동 활성화도 이번 범위에 없다.

## 검증 상태

실제 PG의 R1/R2 carry·explicit null·presence unknown·runtime ACL, 불변 fieldset·재등록·잘못된
정책의 원자 실패, 두 session의 global-first/오래된 RR snapshot을 확인했다. 최종 수치와 source
SHA·전체 CI/두 독립 리뷰/HTTP·UI는 PR 수용 기록에 남기며 현재 모두 완료로 표현하지 않는다.
공개 API/수집 경로는 미변경이므로 운영 효과나 ARM CPU/RAM 절감 수치를 주장하지 않는다.
