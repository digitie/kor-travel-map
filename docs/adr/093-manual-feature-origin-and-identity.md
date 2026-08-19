# ADR-093: 수동 Feature의 origin과 exact identity claim을 분리한다

- **상태**: proposed
- **날짜**: 2026-08-19
- **결정자**: Codex 초안, human review pending
- **관련**: ADR-066, ADR-068, ADR-074, ADR-075, ADR-083, ADR-086, ADR-090, ADR-092,
  T-VN-M00~M05

## 컨텍스트

ETL provider가 발행하지 않는 장소를 admin/API로 만들어야 한다. 예시는 태화강 국가정원,
반디랜드&태권도원, 청풍호처럼 curation 대상은 있지만 provider place Feature가 없는 경우다.

현재 `POST /v1/admin/features`는 이미 존재하지만 body `feature_id`, body `idempotency_key`, caller가
고를 수 있는 3축 상태와 nullable 좌표를 받는다. `_create_feature_id()`는 caller key 또는 이름·좌표로
`user_request` legacy ID를 만든다. 성공과 replay는 `200`/`ETag` 계약이다.

또한 admin UI BFF와 PinVi는 같은 endpoint와 같은 종류의 admin proxy 자격을 사용한다. actor header도
둘 다 보낼 수 있다. 이 경계에서 route 이름이나 actor 문자열로 origin을 정하면 PinVi 생성까지
`manual_admin`으로 영구 오분류된다.

HTTP replay key는 전송 멱등성이고, 같은 실체 판정은 데이터 불변식이다. 둘을 한 키로 사용하면 caller가
새 key를 보낼 때마다 중복 방지가 무력화된다. 반대로 이름·좌표를 canonical ID에 다시 넣으면
ADR-068/083의 UUID cutover가 되돌아간다.

## 결정

### 1. canonical identity와 exact claim

canonical Feature identity는 서버 발급 UUIDv7이다. 이름, 분류, 주소, 좌표, origin,
`Idempotency-Key`는 UUID 재료가 아니다. current text PK가 남아 있는 동안의 `f_*`는
`source_type=user_request`, `source_natural_key=manual::<uuid>`로 만든 opaque legacy alias다.

생성 시점 exact duplicate는 별도 `feature.manual_feature_identity_claims` relation이 소유한다.
DB 단일 함수가 kind, NFC/trim/ASCII-lower/C-collation name, numeric 6자리 좌표를 계산하고
`(feature_kind,name_key,lon_e6,lat_e6)` unique 제약으로 동시 생성의 단일 승자를 정한다. category는
identity에 넣지 않는다. claim은 이름·좌표 patch나 Feature purge 뒤에도 append-only로 남는다.

### 2. verified origin과 command causation

생성 provenance는 별도 `feature.feature_creation_origins` relation이 소유한다. M01에서 허용하는 값은
`manual_admin` 하나다. origin은 같은 UUID·command의 claim을 composite FK로 참조하고, claim과
origin의 command 열은 모두 `ops.domain_commands`를 `ON DELETE RESTRICT`로 참조한다.

origin에는 transport principal ID와 human actor를 분리해 저장한다. 전자는 고정값
`admin-ui-bff.manual-feature-create.v1`, 후자는 locked domain-command actor다. API body, actor 문자열,
reason prefix로 origin이나 principal을 선택하지 않는다.

`manual_pinvi`와 `manual_curation`은 각 queue/writer 및 인증 경계를 실제로 배포하는 M04/M03에서만
CHECK domain에 추가한다. 과거 admin/PinVi 공유 경계에서 만들어진 행에는 origin을 추정하지 않는다.

### 3. admin UI BFF 생성 전용 자격

기존 `AdminBFF` 인증만으로 create를 허용하지 않는다. `POST /v1/admin/features`는 기존 gate와
`AdminFeatureCreateBFF` API-key scheme을 OpenAPI의 같은 security requirement object에서 AND로
요구한다. 2차 header는 `X-Kor-Travel-Map-Admin-Feature-Create-Token`이다. API는
`KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256` digest만, admin UI BFF는 server-only raw token만
가진다. PinVi에는 이 token을 배포하지 않는다.

기존 AdminBFF만 가진 caller는 `403 ADMIN_FEATURE_CREATE_SCOPE_REQUIRED`이고 DB에 command나 Feature를
쓰지 않는다. PinVi의 `new_place` direct create는 M01 활성화보다 먼저 제거하며 M04 queue 전에는 PinVi가
`503 MAP_FEATURE_REQUEST_QUEUE_UNAVAILABLE`로 fail-close한다.

### 4. HTTP와 domain-command version

body `feature_id`, body `idempotency_key`, `operator`, 초기 3축 상태는 제거한다. 좌표는 required,
non-null이다. initial state는 `active/published/valid`로 고정한다.

새 operation은 `admin.feature.create.manual-v1`이다. 기존 `admin.feature.create`의 `200` terminal result를
새 body로 replay하지 않기 위해 이름을 분리한다. command registry는 `success_status=201`,
`replay_headers=('ETag','Location')`다. 신규 성공과 exact replay는 canonical UUID만 담은 같은 201 body,
ETag, Location을 반환하고 replay 응답에만 `Idempotency-Replayed: true`를 더한다.

### 5. DB writer, 동시성, 권한

M01은 별도 SECURITY DEFINER wrapper를 둔다. exact claim은
`ON CONFLICT ON CONSTRAINT ... DO NOTHING`으로 시도한다. loser는 다음 statement에서 winner UUID를
조회해 `exact_conflict` outcome으로 반환한다. raw 23505와 aborted transaction 안에서 UUID를 조회하지
않는다.

winner만 generic initial-create procedure를 부른다. generic 결과의 `o_inserted=true`와 반환 ID가
claim과 같음을 검사한 뒤 origin을 넣는다. subtype, field override, terminal result까지 같은 외부
transaction이며 어느 단계 실패도 전체 rollback이다.

신규 역할은 manual wrapper owner, API-only manual executor, Dagster-only generic-create executor로
분리한다. API는 wrapper만, Dagster는 generic create만 실행할 수 있다. claim/origin relation은
runtime direct SELECT/DML/TRUNCATE가 모두 없고 wrapper owner만 SELECT/INSERT한다. 두 relation의
UPDATE/DELETE row trigger와 TRUNCATE statement trigger는 stable 42501 diagnostic으로 mutation을 막는다.

### 6. current/target, 이관, 복원

claim/origin은 처음부터 UUID 열만 사용한다. current wrapper는 legacy text ID와 canonical UUID를 모두
반환하고 T-VN-39 target wrapper는 UUID만 반환한다. parity는 catalog equality가 아니라 current
`feature_uuid` → target `feature_id` semantic mapping으로 검증한다.

legacy claim backfill은 first initial transition → old domain command/result → 같은 command의
`ops.feature_overrides` `core.name`/`core.coord`를 연결한다. 각 evidence가 정확히 1행이고 actor,
operation, UUID가 일치해야 한다. missing·duplicate·exact 충돌은 permanent DDL/INSERT 전에 migration을
중단한다. legacy origin은 0건이다.

M01 활성화 전 backup manifest는 claim, origin, 참조 command/result를 같은 pg_dump snapshot의 count와
SHA-256 root로 검증한다. `pg_restore --no-owner --no-privileges` 뒤 bootstrap owner repair와 ACL
reconciliation을 다시 실행한다. cache-target `restore_epoch`는 DB 복원 정본이 아니라 복원 후 downstream
invalidation fence다. M02 purge 계약 전 manual claim/origin Feature의 hard purge는 닫는다.

## 근거

canonical UUID와 exact reservation을 분리하면 이름·좌표 보정이 identity를 바꾸지 않으면서도 같은
생성 실체의 concurrent duplicate를 DB unique 제약으로 막을 수 있다. HTTP idempotency ledger는 응답
유실 재생만 소유하므로 두 의미가 섞이지 않는다.

origin은 복구와 운영 판정의 감사 기준이다. 서버가 실제로 구분할 수 없는 값을 enum에 미리 넣으면
“구분되고 있다”는 거짓 정본이 된다. 별도 2차 transport 자격과 DB executor 역할을 함께 닫아야 route
hard-code가 인증되지 않은 배선 가정에 머물지 않는다.

claim↔origin↔command FK와 append-only trigger는 procedure 검증만으로는 남는 privileged write·restore
오류를 선언적으로 막는다. same-snapshot manifest와 owner/ACL 복구는 `--no-owner --no-privileges`
restore 뒤에도 그 불변식을 되살린다.

## 결과(긍정)

- canonical UUID와 duplicate reservation, transport idempotency의 책임이 분리된다.
- exact 경합 loser가 transaction abort 없이 기존 canonical UUID를 안정적으로 받는다.
- PinVi와 일반 AdminBFF가 `manual_admin` origin을 제조할 수 없다.
- origin과 claim의 command causation이 FK로 고정되고 purge 뒤에도 evidence가 남는다.
- current text bridge와 final UUID target의 의도된 차이를 명시적으로 검증할 수 있다.

## 결과(부정)

- 같은 장소인데 이름 표기나 좌표가 exact 규칙 밖으로 다르면 M01이 자동 차단하지 않는다. M05의
  fuzzy 후보 검토가 필요하다.
- 기존 create body와 200 response가 깨지므로 admin UI, OpenAPI, PinVi direct caller를 함께 정리해야 한다.
- 역할 세분화, backup manifest, ACL reconciliation 때문에 M01 migration 범위가 넓어진다.
- M04 queue 전까지 PinVi 신규 장소 승인은 503으로 닫힌다.

## 후속

- T-VN-M01: UUID, exact claim, `manual_admin`, 전용 BFF 인증, 201 replay, ACL/error/OpenAPI/freeze,
  최소 backup·restore·hard-purge fence 구현.
- T-VN-M02: origin/claim read model과 patch·state·purge 전체 불변, 운영 restore drill.
- T-VN-M03: curation item 생성 중 missing Feature를 같은 transaction으로 생성.
- T-VN-M04: PinVi 요청 queue와 별도 인증 경계 뒤 `manual_pinvi` 추가.
- T-VN-M05: provider Feature가 나중에 발행한 같은 실체를 dedup 후보로 올리고 자동 병합하지 않음.
