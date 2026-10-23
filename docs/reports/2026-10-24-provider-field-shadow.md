# ADR115 shadow 원천별 필드 후보 — 첫 구현 단위

## 변경과 미완 경계

같은 Feature/field에 마지막 provider 값 하나만 남기는 기존 base를 복사해 후보 원장으로
간주하지 않는다. additive410 migration에 명시 정책과 source별 shadow 후보를 넣고,
기존 전역 feature-curation-write 아래에서 선택한 정책 revision의 수집을 기록한다.
기본 설정 provider_field_shadow_policy_revision=None은 OFF다. OFF에는 추가 DB SQL과
payload JSON 변환이 없다. 기존 base/effective·override·seal·identity·잠금 범위는 바꾸지 않는다.

아직 T-CWRITE-02 완료가 아니다. 전체 활성 membership backfill/완전성 gate, 실제 provider별
정책·정규화 증거, 결정적 winner 물화·정책 활성화, Geo 일관 그룹, merge redirect와
T-CWRITE-03 scope/epoch/manifest는 후속이다. 운영 seed 정책은 없고 자동 enable하지 않는다.

## 원문·누락·정책

- normalizer가 ProviderFieldPresence로 실제 supplied field paths와 transform revision을
  명시한다. 완성된 Feature DTO의 기본 None을 명시 null로 추정하지 않는다.
- 정책은 dataset/field/revision별 rank, omitted carry_forward/remove, null remove/value를
  명시한다. 운영 provider의 우선순위나 생략 계약은 이 코드가 정하지 않는다.
- R1 값 원문 record/hash와 R2 validated-through current head record/hash를 분리한다.
  R2가 phone을 생략해도 명시 carry 정책이면 R1 값과 원문을 유지하고 R2 검증을 기록한다.
- 미제공 presence, 최초 omitted 값의 원문 부재는 unresolved다. address/행정코드·geometry·
  관계 identity 그룹은 아직 필요한 Geo/merge 증거가 없어 geo_evidence_unsupported로 남긴다.
  이 unresolved를 정상 승인 scope나 신규 원천의 완결로 해석하지 않는다.
- availability=value는 그 field 값의 원천 기록이며 dataset 전체 membership의 활성/승인
  완결을 뜻하지 않는다. 향후 winner는 별도의 현재 membership/head/정책 gate를 모두 검증한다.
- raw payload는 복제하지 않고 immutable source record를 FK로 참조한다. geometry column은
  typed로 준비하지만 첫 단위에서는 Geo 그룹 후보를 승인하지 않는다.

## 권한과 회복

정책과 후보 표의 runtime 직접 DML은 닫고 SECURITY DEFINER typed recorder만 열었다.
recorder는 현재 활성 dataset/head/source link를 같은 transaction에서 잠그고 Feature 행을
검증한다. 정책을 사용한 뒤 같은 revision의 수정/새 field 삽입은 global fence와 trigger로
거절한다. 정책 변경은 새 revision을 준비해야 한다. DDL lock1초/statement30초 상한은
더 짧은 caller 상한을 보존하며 성공 후 원래 설정을 복구한다. migration은 forward-only다.

운영·daemon·scope 전환은 하지 않는다. 이번 shadow ledger는 기존 원문에서 후보를 완전히
복구했다고 주장하지 않으며, 미지원 provider/Geo 필드·기존 누락 후보가 남아 있으면 이후
정책 활성화와 잠금 세분화를 허용하면 안 된다.

## 현재 확인

fresh400→410 및 실제 PG R1/R2 carry, explicit null, presence unknown 3 PASS(14.40초).
OFF 경로 기존 spool/대기 집중22 PASS, strict mypy166파일 PASS. 추가 ACL·오류·실수집 hook·
정확 head-schema/OpenAPI/생성 타입·전체 CI·두 독립 리뷰·실제 HTTP/UI는 아직 진행 중이다.
