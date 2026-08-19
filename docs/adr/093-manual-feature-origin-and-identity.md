# ADR-093: 수동 Feature 생성 origin과 identity를 별도 정본으로 둔다

- **상태**: proposed
- **날짜**: 2026-08-19
- **결정자**: Codex 초안, human review pending
- **관련**: ADR-048, ADR-074, ADR-075, ADR-083, ADR-086, ADR-090, ADR-092, T-VN-M00~M05

## 컨텍스트

ETL provider가 발행하지 않는 장소를 admin/API로 만들어야 한다. 예시는 태화강 국가정원,
반디랜드&태권도원, 청풍호처럼 curation 대상은 있지만 provider place Feature가 없는 경우다.

현재 `POST /v1/admin/features`는 존재하지만 `source_type="user_request"`와 body
`idempotency_key` 또는 이름·좌표 조합으로 `feature_id`를 만든다. 또한 admin BFF와 PinVi는 같은
endpoint, 같은 proxy 인증 경계, 검증 없는 actor header를 사용하므로 서버가 호출자를 origin으로
구분할 수 없다.

1차 M00 초안은 origin을 호출 경로에서 파생하고 자연키를 opaque하게 만들었으나, 두 결정 모두
안전하지 않았다. 구별 불가능한 origin은 영구 오분류가 되고, opaque natural key는 같은 실체
중복을 DB가 막지 못한다.

## 결정

1. M01의 수동 Feature origin은 `manual_admin` 하나다. `manual_pinvi`와 `manual_curation`은
   별도 인증·command 경계가 생긴 뒤에만 값 domain에 추가한다.
2. HTTP `Idempotency-Key`는 ADR-074 replay key로만 사용한다. manual source natural key는 서버가
   이름, region, kind, category, 좌표 cell을 정규화해 만든다. body `idempotency_key`와 명시
   `feature_id`는 신규 manual create identity에 참여하지 않는다.
3. `feature_id`는 `make_feature_id(source_type="manual_admin", source_natural_key=<manual-v1>)`로
   서버가 만든다.
4. 수동 origin과 중복 방지는 `feature.manual_feature_origins` side relation이 소유한다. 이
   relation은 `feature_id`, `feature_uuid`, `origin`, `source_type`, `source_natural_key`,
   normalized name, region, coordinate cell, `ops.domain_commands.command_id`, actor를 immutable하게
   보존한다.
5. `admin.feature.create`는 serializable domain command로 실행한다. 같은 region/name 생성은
   advisory lock으로 직렬화하고, exact duplicate는 unique constraint로, 100m 이내 fuzzy duplicate는
   procedure guard로 409를 반환한다.
6. 기존 state audit의 `transition_kind='initial'`은 유지한다. manual origin을 transition kind enum에
   넣지 않는다.
7. `published` manual Feature는 좌표와 region이 필요하다. 좌표 없는 수동 Feature는 draft 또는
   suppressed까지만 허용한다.

## 근거

origin은 복구와 중복 판정의 감사 기준이다. 서버가 실제로 구분할 수 없는 값을 enum에 미리 넣으면
"구분되고 있다"는 거짓 정본이 된다.

HTTP replay key는 전송 재시도와 최초 terminal result 재생을 위한 키다. 같은 실체 판정과 섞으면
caller가 매번 새 UUID를 보낼 때마다 DB 중복 방지가 무력화된다.

기존 `feature.features`는 provider·admin·public projection의 핵심 row라 origin 컬럼을 급하게
섞기보다 수동 생성 identity side relation에서 시작하는 편이 M01 범위를 작게 유지한다. M02는 이
relation을 확장하거나 canonical origin relation으로 승격할 수 있다.

## 결과(긍정)

- admin과 PinVi를 구분할 수 없는 현 상태에서 잘못된 origin이 영구 기록되지 않는다.
- 같은 manual natural key와 가까운 중복 후보를 DB transaction 안에서 막을 수 있다.
- runtime은 raw table DML 없이 security-definer procedure만 실행한다.
- M02~M05가 origin 노출, PinVi 요청 큐, curation 동시 생성, provider 발행 뒤 중복 판정을
  순차적으로 얹을 수 있다.

## 결과(부정)

- 같은 이름의 서로 다른 장소가 같은 region/category/100m cell에 있으면 M01은 409로 막고 admin
  판단을 요구한다.
- 기존 body `idempotency_key` 의미를 바꾸거나 제거해야 하므로 OpenAPI와 PinVi 호출부 확인이
  필요하다.
- `contracts/vnext` freeze artifact와 current migration을 함께 갱신해야 한다.

## 후속

- T-VN-M01: `manual_admin` 생성 path, side relation, duplicate/error/ACL/OpenAPI/freeze gate 구현.
- T-VN-M02: origin 보존 정본을 `manual_admin` 외 origin까지 확장하고 read/API 노출 여부 결정.
- T-VN-M03: curation item 생성 중 missing Feature를 같은 transaction으로 생성.
- T-VN-M04: PinVi 요청 큐와 별도 인증 경계 뒤 `manual_pinvi` origin 추가.
- T-VN-M05: provider Feature가 나중에 발행한 같은 실체를 dedup 후보로 올리고 자동 병합하지 않음.
