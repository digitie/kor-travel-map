# ADR115 shadow 수집 연결 — 명시 scope만 기본 OFF

## 이번 연결과 남은 범위

불변 정책/standalone 후보 기반(PR1361)의 recorder를 실제 load_bundle 끝에 연결한다.
기존 base/effective·source seal·identity·전역 충돌 범위는 바꾸지 않는다. 설정 revision과
(provider,dataset_key) allowlist가 **모두** 있어야 후보 SQL을 실행한다. 기본 None/빈 집합은
OFF이며 기존 DTO typed-patch JSON을 추가로 만들지 않는다. ON이라도 presence가 없으면
추가 전체 patch JSON을 만들지 않고 recorder가 정책 필드를 unresolved로 기록한다.

실제 정규화 증거의 첫 범위는 MCST core.name뿐이다. 기존 extractor가 실제 원천에서 읽어
검증한 이름을 mcst-name-v1 presence로 선언한다. Geo 주소/행정코드·파생 marker·완성 DTO의
기본 None·그 밖의 필드를 supplied로 꾸미지 않는다. 불변 presence 객체 하나를 행마다 공유해
별도 집합/모델을 계속 만들지 않는다. 실제 raw payload/source record는 기존 그대로다.

이것만으로 T-CWRITE-02/실제 동시 쓰기가 완료되지는 않는다. provider 전체 필드의 명시 정책,
전체 active membership backfill/누락 검증, 현재 head/membership 기반 winner, Geo 일관 그룹,
scope/epoch/manifest 및 정책 활성화는 후속이다. 정책 seed/자동 enable/운영 설정 변경은 없다.
Geo 증거 없는 필드는 계속 unresolved이며 unresolved를 정상 승인으로 집계하면 안 된다.

## 적용 경계와 실패

- client가 기존 native 적재 transaction에 설정을 전달하고 recorder는 그 transaction의
  canonical Feature UUID/dataset/entity/record를 쓴다. shadow의 정책/normalizer/타입 검증이
  실패하면 native 쓰기까지 같이 rollback한다. 성공으로 삼키지 않는다.
- 같은 raw가 이미 적재돼 native 본문이 바뀌지 않은 재수집도 후보를 채운다. Feature ID/name/
  row_revision을 shadow를 위해 바꾸지 않는다. R1 원문/R2 검증은 기반 procedure가 관리한다.
- allowlist에 없는 다른 provider/dataset은 같은 revision 설정이 있어도 후보 SQL을 실행하지
  않는다. 정책 등록은 schema 관리자만 할 수 있고 runtime의 직접 정책/후보 DML은 닫혀 있다.
- 공개 API/OpenAPI/TypeScript 계약은 바뀌지 않는다. 내부 FeatureBundle에 optional presence
  metadata만 추가하며 PinVi DTO 재vendor는 필요 없다. 기존 bundle 입력은 계속 유효하다.

## 검증·운영 gate

실제 public client와 실제 PostGIS에서 기존 데이터 재수집/선택scope OFF·ON 및 동일Feature
보존을 확인한다. runtime 권한 경로와 정책 미등록 시 native 원문/Feature의 원자 rollback도
회귀로 둔다. 나머지 MCST 변환/긴 대기 설정과 기본OFF 경로는 기존 회귀를 유지한다.

최종 SHA별 수치·CI·두 독립 리뷰·HTTP/UI는 PR 수용 기록으로 구분한다. 운영 배포/수집 실행은
하지 않았다. 배포하더라도 정책/전체 membership·원문/필드 증거 gate가 완료되기 전에는
shadow enable을 하지 않는다. ARM CPU/RAM 감소나 dataset/지역별 동시 DML 효과는 아직
실측하지 않았으며 이 연결의 결과로 주장하지 않는다.
