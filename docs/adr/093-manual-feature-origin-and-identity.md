# ADR-093: 수동 Feature 생성 origin과 identity를 별도 정본으로 둔다

- **상태**: proposed
- **날짜**: 2026-08-19
- **결정자**: Codex 초안, human review pending
- **관련**: ADR-066, ADR-068, ADR-074, ADR-075, ADR-083, ADR-086, ADR-090, ADR-092, T-VN-M00~M05

## 컨텍스트

ETL provider가 발행하지 않는 장소를 admin/API로 만들어야 한다. 예시는 태화강 국가정원,
반디랜드&태권도원, 청풍호처럼 curation 대상은 있지만 provider place Feature가 없는 경우다.

현재 `POST /v1/admin/features`는 이미 존재하지만 body `feature_id`, body `idempotency_key`,
caller가 고를 수 있는 3축 상태를 받는다. `_create_feature_id()`는 caller key 또는 이름·좌표로
`user_request` legacy ID를 만든다. 또한 admin BFF와 PinVi는 같은 endpoint, 같은 proxy 인증 경계,
검증 없는 actor header를 사용하므로 서버가 호출자를 origin으로 구분할 수 없다.

1차 M00 초안은 origin을 호출 경로에서 파생하고 자연키를 opaque하게 만들었으나, 두 결정 모두
안전하지 않았다. 구별 불가능한 origin은 영구 오분류가 되고, opaque natural key는 같은 실체 중복을
DB가 막지 못한다.

## 결정

1. M01은 신규 API가 아니라 기존 `POST /v1/admin/features`의 clean cutover다.
2. canonical Feature identity는 ADR-068/083의 서버 발급 UUID다. 이름, 분류, 주소, 좌표, origin은
   canonical ID 재료가 아니다. current text PK가 남아 있는 동안의 `f_*` 값은 legacy alias일 뿐이다.
3. HTTP `Idempotency-Key`는 ADR-074 replay key로만 사용한다. body `idempotency_key`, body
   `feature_id`, body `operator`, caller가 고르는 초기 3축 상태는 신규 manual create 계약에서 제거한다.
4. exact duplicate는 `feature.manual_feature_identity_claims`가 소유한다. DB가 `kind`, 정규화한
   `name_key`, `lon_e6`, `lat_e6`를 계산하고 unique 제약으로 동일 장소 생성을 한 건만 허용한다.
   category는 duplicate identity에 넣지 않는다.
5. 생성 origin은 별도 `feature.feature_creation_origins`가 소유한다. M01에서 허용하는 값은
   `manual_admin` 하나이며, admin UI BFF 전용 proxy credential 경계에서만 기록한다.
6. `manual_pinvi`와 `manual_curation`은 각 경계를 실제로 배포하는 M04/M03에서만 CHECK domain에
   추가한다. M01에서 PinVi 직접 create는 닫힌다.
7. 기존 generic state procedure의 `transition_kind='initial'` 의미는 유지한다. M01은 별도
   SECURITY DEFINER wrapper로 claim, origin, core, initial state, subtype, field override,
   domain-command terminal result를 한 transaction에 묶는다.

## 근거

HTTP replay key는 전송 재시도와 최초 terminal result 재생을 위한 키다. 같은 실체 판정과 섞으면
caller가 매번 새 UUID를 보낼 때마다 DB 중복 방지가 무력화된다.

legacy `f_*` 값을 다시 의미 기반 identity로 만들면 ADR-068/083의 UUID cutover가 되돌아간다.
따라서 manual duplicate 판정은 canonical ID 생성과 분리된 claim 관계가 맡고, `f_*`는 current
bridge 또는 alias lookup으로만 남긴다.

origin은 복구와 중복 판정의 감사 기준이다. 서버가 실제로 구분할 수 없는 값을 enum에 미리 넣으면
"구분되고 있다"는 거짓 정본이 된다. 과거 admin/PinVi 공유 경계에서 만들어진 행도 origin을 추정하지
않는다.

## 결과(긍정)

- admin과 PinVi를 구분할 수 없는 현 상태에서 잘못된 origin이 영구 기록되지 않는다.
- canonical UUID와 duplicate reservation이 분리되어 이름·분류·좌표 보정이 identity를 바꾸지 않는다.
- 같은 exact manual claim은 DB transaction 안에서 한 건만 생성된다.
- runtime은 raw table DML 없이 security-definer procedure만 실행한다.
- M02~M05가 origin 노출, PinVi 요청 큐, curation 동시 생성, provider 발행 뒤 중복 판정을
  순차적으로 얹을 수 있다.

## 결과(부정)

- 같은 장소인데 이름 표기나 좌표가 exact 규칙 밖으로 달라진 경우는 M01에서 자동 차단하지 않는다.
  M05의 후보 검토가 필요하다.
- 기존 body `idempotency_key`, `feature_id`, `operator`, 초기 상태 선택을 제거해야 하므로 OpenAPI,
  admin UI, PinVi 직접 호출부를 함께 정리해야 한다.
- admin UI BFF 전용 credential 배포 전에는 M01 create를 열 수 없다.
- `contracts/vnext` freeze artifact와 current migration을 함께 갱신해야 한다.

## 후속

- T-VN-M01: UUID 발급, exact claim, `manual_admin` origin, 전용 BFF 인증, error/ACL/OpenAPI/freeze gate 구현.
- T-VN-M02: origin/claim read model, patch·state·backup·restore·purge 불변 검증.
- T-VN-M03: curation item 생성 중 missing Feature를 같은 transaction으로 생성.
- T-VN-M04: PinVi 요청 큐와 별도 인증 경계 뒤 `manual_pinvi` origin 추가.
- T-VN-M05: provider Feature가 나중에 발행한 같은 실체를 dedup 후보로 올리고 자동 병합하지 않음.
