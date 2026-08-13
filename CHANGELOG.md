# CHANGELOG

본 라이브러리의 사용자 가시 변경을 기록한다. [Keep a Changelog](https://keepachangelog.com)
형식을 따른다.

## [Unreleased]

### immutable curation import plan (2026-08-14, T-VN-40)

- **API(admin)**: CSV import를 immutable preview(201+ETag)와 stored-plan commit으로 분리했다. commit은
  `If-Match`와 `Idempotency-Key`를 요구하고 동일 terminal receipt·ETag를 재생한다. preview도 multipart
  byte fingerprint를 먼저 claim하고 SERIALIZABLE 충돌 시 전체 command를 재시도한다.
- **UI(admin)**: preview 결과를 확인한 뒤 같은 plan을 명시적으로 commit한다. quarantine stale 412는
  자동 mutation 재시도 없이 관련 목록·항목·대상을 다시 읽고 운영자의 재실행을 요구한다. 공식 등대
  import는 CSV와 exact provenance JSON sidecar를 함께 업로드하며 plan 412는 재미리보기를 요구한다.
- **DATABASE**: apply row set을 immutable plan과 exact 비교하고 같은 command의 batch/content receipt만
  terminal commit에 결박한다. provenance pointer만 바뀐 item도 item·collection revision을 갱신한다.
- **DATABASE**: PR #977의 `0104_tvn36_final_fence` 뒤 T-VN-40 chain을 재배치하고
  `0121_tvn40_metadata_check`에서 owner shape 제약 검증과 ORM/Alembic metadata 동등성을 닫았다.
- **REMOVED**: preview/commit에서 같은 CSV를 다시 업로드·해석하던 legacy `dry_run` import route를 제거했다.

### retained curation source CAS API (2026-08-13, T-VN-40)

- **API(admin)**: retained source에 단건 GET·conditional 304와 archive DELETE를 추가했다. operator
  create/patch/archive는 raw catalog revision ETag와 If-Match 428/412를 사용하고 provider observation은
  별도 representation ETag에 반영된다.
- **DATABASE**: source operator revision과 provider observation revision을 분리했다. exact done import-job
  membership만 Dagster observation command로 수용하고 archive는 dependent rule candidate를 같은
  SERIALIZABLE transaction에서 reconcile한다. catalog command effect는 append-only claim으로 한 command의
  다중 resource 재사용을 거부한다.
- **REMOVED**: caller가 임의 시점에 legacy overlay를 갱신하던 admin rule apply API와
  `curated_features_refresh` Dagster 일일 asset/job/schedule을 제거했다. 후보 generation은
  authoritative provider terminal receipt 또는 typed catalog command만 시작한다.
- **SECURITY**: provider observation은 authoritative full-snapshot child job을 한 번만 소비하는
  append-only receipt를 사용한다. 동일 job replay는 timestamp/revision을 갱신하지 않으며 catalog
  command effect와 terminal result는 같은 command row lock으로 직렬화한다.

### retained curation theme CAS API (2026-08-13, T-VN-40)

- **API(admin)**: retained theme에 단건 GET과 archive DELETE를 추가하고 create/patch/archive
  응답을 strong `ETag`와 `If-Match` 428/412 경계로 통일했다. create와 terminal replay는 201이다.
- **DATABASE**: theme archive는 affected rule candidate reconcile을 같은 SERIALIZABLE transaction에서
  완료한다. operator catalog revision은 candidate semantic proof와 분리되어 display metadata 변경만으로
  기존 후보가 stale 처리되지 않는다.

### retained curation rule CAS API (2026-08-13, T-VN-40)

- **API(admin)**: retained source rule에 단건 GET과 archive DELETE를 추가하고 create/patch/archive
  응답에 server-owned revision strong `ETag`를 고정했다. patch/archive는 `If-Match`가 없으면
  428, stale이면 412이며 domain-command replay가 원 성공 `ETag`를 그대로 반환한다. BIGINT
  revision은 TypeScript 정밀도 손실을 막기 위해 응답에서 decimal string으로 직렬화한다.
- **DATABASE**: rule create/patch/archive는 실제 API LOGIN 전용 named SECURITY DEFINER command로
  실행되며 catalog CAS, immutable reconcile receipt, candidate generation을 SERIALIZABLE 단일
  transaction으로 결박한다. typed API의 rule action은 `candidate|ignore`만 허용한다.

### PinVi alias-map 이관 표면·legacy write fence (2026-08-04, T-VN-32C 전반부)

- **API(service)**: `GET /v1/service/feature-alias-maps`(canonical keyset
  페이지, limit≤1000) + `GET /v1/service/feature-alias-maps/checksum`(저장소
  전체 merkle root·count)이 추가됐다 — PinVi alias-map DB-to-DB 이관 전용
  read(ADR-068 결정 3의 전환·복구 경계, `X-Kor-Travel-Map-Service-Token`
  게이트). 계약 정본은 `contracts/feature-alias-map-v1-golden.json`
  (`feature-alias-map-v1`) — Map(`core/feature_alias_map.py`)과 PinVi가 독립
  구현으로 같은 golden vector를 재계산해 대조한다. 저장 행이 canonical/파생
  계약을 위반하면 500 `FEATURE_ALIAS_MAP_INTEGRITY`로 fail-close.
- **DATABASE**: `0082_legacy_write_fence` — ① `feature.feature_aliases` 불변
  fence(UPDATE 전면 거부, 직접 DELETE 거부 — feature 행 purge의 FK CASCADE
  경유만 허용), ② `feature.features` identity 불변 fence(`feature_id`/
  `feature_uuid` UPDATE 거부 — 재키잉은 soft-delete + 신규 행), ③ alias-map
  keyset 조회용 `COLLATE "C"` index. 0079 트리거 2종(fill/alias)은 재평가 후
  유지(0080 파생 CHECK와 함께 legacy-only 행 저장을 구조적으로 불가능하게
  하는 강제 메커니즘 — 0081 docstring). legacy ID·CHECK·트리거 제거는 양
  저장소 checksum 일치 뒤(32C 잔여)와 T-VN-39 removal manifest 소관.

### UUID identity dual read/write — Map consumer-first (2026-08-04, T-VN-32B)

- **API**: feature 응답에 `feature_uuid`가 additive로 병행 노출된다(ADR-068 UUID
  정본 identity) — user `GET /v1/features/{id}` detail·search·in-bounds·nearby
  item, service `POST /v1/features/batch` item(found/retired/suppressed/
  unchanged)·`POST /v1/features/weather/batch` item, admin `GET /v1/admin/
  features` 목록·상세. 응답 `feature_id` 값은 legacy `f_*` 유지 — UUID 전환은
  T-VN-32C cutover.
- **API**: 모든 feature `{feature_id}` 경로의 참조가 legacy id와 canonical
  UUID 양쪽을 수용한다(경계 alias 해석 — user detail·sources·observations·
  weather·price·contained-features, admin detail·revision·weather·price·
  PATCH·DELETE·deactivate). 형식 오류(빈 문자열/공백 패딩/256자 초과)는 422,
  미해석 참조는 404.
- **DATABASE**: `0081_uuid_dual_read` — ① `feature.public_features` view 컬럼
  목록을 재고정해 `feature_uuid`를 노출한다(공개 술어 무변경, 무손실
  downgrade). ② dual 기간 파생 규칙 CHECK 2종
  (`ck_features_feature_uuid_dual_derivation`,
  `ck_feature_aliases_uuid_dual_derivation`)을 연결한다 — uuid5 파생값과 다른
  `feature_uuid` write는 DB가 거부한다(T-VN-32C cutover에서 제거되는 한정
  fence).
- **INTERNAL**: 신규 feature write는 writer가 dual 기간 정본 generator(uuid5
  legacy 파생, UUIDv7 미채택 결정)로 `feature_uuid`를 명시 생성하고, 관측값이
  파생 규칙과 다르면 `FeatureIdentityInvariantError`로 fail-close한다
  (legacy-only 신규 행 차단). notice lineage 가시성 판정 표면은
  `public_active_notice_feature_identities`(id→uuid 쌍) 하나로 교체됐다.

### UUID identity shadow — schema·deterministic backfill (2026-08-04, T-VN-32A)

- **DATABASE**: `0080_feature_uuid_shadow` — `feature.features`에 `feature_uuid`
  shadow 컬럼을 추가하고 `uuid5(uuid5(NAMESPACE_URL, 'kor-travel-map:feature-uuid:v1'),
  legacy_feature_id)`로 결정적 backfill 후 NOT NULL + `uq_features_feature_uuid`를
  연결한다. `feature.feature_aliases`(feature당 `alias = feature_id` legacy alias 1행,
  `alias_kind = 'legacy_feature_id'` 닫힌 CHECK, legacy FK `ON DELETE CASCADE`)를
  신설하고, INSERT 트리거 2종이 신규 행의 uuid·alias를 같은 transaction에서 생성한다
  (호출자가 명시한 uuid는 존중). 기존 문자열 `f_*` PK·FK·읽기 경로는 무변경(shadow
  단계, ADR-068)이며 downgrade는 파생 구조물만 제거해 무손실이다. Python 정본은
  `kortravelmap.core.feature_uuid_from_legacy`, SQL mirror는 pgcrypto 기반
  `feature.feature_uuid_from_legacy`(고정 벡터 상호 대조).

### H35 typed cutover GC·최종 cache-target 증적 (2026-08-02, T-VN-H35/T-VN-41)

- **OPERATIONS**: Map cutover helper 순서를 `preflight→migrate→csv5→gc→verify`로 확장했다. `gc`는 기존
  bounded snapshot GC와 `0078` observation만 사용하며 deterministic replay는 attempt별 삭제 수가 아닌
  최종 backlog 0·referenced 보존·fresh observation 수렴으로 승인한다.
- **CONTRACT**: 모든 receipt에 exact `cache_target_evidence` field가 생긴다. accepted `verify`만 PinVi
  ready stream, 양의 restore epoch/control version, 최신 unexpired snapshot header/item/live source
  Merkle·watermark 일치와 reconciliation/outbox/claim/delivery backlog 0을 증명하는
  `ktm-cache-target-final-evidence/v1` object를 반환하고 다른 phase와 거부 응답은 `null`이다.
- **DATABASE/VERIFY**: `0075~0078`의 constraint/index/trigger/function/sequence를 이름이 아니라 canonical
  PostgreSQL semantic catalog로 검증한다. 동명이형 정의, invalid/not-ready index, disabled trigger와
  function/ownership drift를 mutation 0으로 거부한다.
- **DATABASE/VERIFY**: scope validator는 top-level뿐 아니라 필수 `_0074(text,jsonb)`와
  `_0052(text,jsonb)` delegate의 exact schema/name/args/result/body/config/함수 속성/owner까지 고정한다.
  여섯 scope valid/invalid truth table로 legacy delegate chain과 generation-7 경계를 end-to-end 검증한다.
- **REHEARSAL**: 실제 PostGIS에서 `0063→0078→CSV5→GC→verify`, GC replay, generation-7 final state와
  stale/expired/mixed/Merkle/네 backlog 음수 행렬을 검증했다. 운영 순서는 GC 뒤 exact 5-writer final
  fence, Map verify, PinVi final boundary로 고정한다.
- **CLI**: invalid argv/request는 phase별 DB·CSV·GC 구현을 import하기 전에 좁은 오류 envelope로
  종료해, 느린 filesystem에서도 비밀 비반사 process 경계가 timeout에 의존하지 않는다.

### cache-target generation outbox producer foundation (2026-07-31, T-VN-41)

- **SECURITY (breaking)**: source PUT/DELETE와 refresh create는 exact `cache-target:command`만 허용한다.
  기존 `cache-target:consumer` umbrella는 enum·validator·인증 fallback에서 clean cut 제거하며,
  command principal도 consumer·snapshot·restore·recovery 경로를 호출할 수 없다. canonical
  consumer/system binding마다 command, consumer, restore, recovery exact 역할 profile을 각각 하나씩
  요구하고 역할 누락·중복·혼합, system 중복 소유, digest/principal ID 중복을 fail-close한다. 한
  `consumer_id`는 전역에서 하나의 canonical sorted system binding만 소유하고 여러 system은 한 union으로
  표현한다. 설정된 admin/service/ops/metrics/cursor secret과 public VWorld/API key와 같은 원문 token
  digest도 거부한다. 17개 service operation은 OpenAPI `x-required-service-scope`와 같은 runtime scope
  inventory를 사용한다. wrong-role과 request-bound metadata oracle은 service 호출 전에 닫힌다. command
  writer는 CAS source GET과 refresh `Location`
  polling에서 consumer credential로 전환해야 한다. PinVi는 재export한 service OpenAPI를 pin하고
  compatible pair를 contract generation 7로 올려야 한다.
- **DATABASE (breaking)**: migration `0075_cache_target_outbox`로 source generation/restore epoch,
  durable head/tombstone, transaction outbox, delivery/claim/dead-letter, fixed snapshot과
  reconciliation 상태를 정규화했다. 후속 `0076_cache_target_receipt`은 applied source event에 당시
  target `lock_version`을 불변 영수증으로 고정하고 검증 가능한 0075 행만 backfill한다.
- **CORRECTNESS**: target/link/refresh 결과 event는 원본 mutation과 같은 transaction에서
  commit한다. restore swap은 live보다 낮은 epoch와 consumer binding drift를 거부하고 동일
  restore-fence domain 함수가 성공한 뒤에만 cutover env를 노출한다.
  fence가 대체한 reconciliation은 request UUID만 참조하지 않고 stream identity와 함께 composite FK로
  결박해 다른 stream receipt INSERT와 referenced parent stream 변경을 DB에서 거부한다. PUT/DELETE exact
  replay는 mutable target row가 아니라 immutable source receipt의 historical target UUID/version으로
  최초 strong ETag를 exact 반환한다.
- **RELAY**: consumer pull claim, contiguous ACK, bounded NACK/dead/replay와 immutable snapshot
  pagination을 제공한다. checksum mismatch는 stream을 disabled로 유지하고 exact match·동일 epoch·
  dead-letter 0인 completion receipt에서만 resume한다. mid-claim poison은 앞 prefix ACK 전에는
  dead 전이를 거부한다. restore fence는 구 epoch의 모든 non-delivered delivery를 terminal
  `superseded`로 원자 종결해 old pending/retry/lease/dead가 새 epoch claim과 복구를 막지 않게 한다.
  같은 fence는 기존 `preparing|running` reconciliation도 terminal `superseded`로 종결해 새 epoch
  reconciliation이 즉시 시작되게 한다.
- **SNAPSHOT/GC**: generic snapshot first page를 응답 transaction에서 durable commit하고
  `created_at`/`expires_at`, 75분 server handoff TTL, system별 live copy 2개와 100,000 item 상한을
  공개한다. 경합·수명·barrier/build timeout은 retryable `503`, copy capacity는 동적
  `429 Retry-After`, item 초과는 `413`으로 fail-close한다. 만료·미참조 material은 reader-safe
  foreground GC와 기본 중지 상태의 hourly background drain이 bounded batch로 정리한다.
  acquired GC run의 referenced item/header count는 Map DB에 90일간 멱등 보존하며, hourly job이 직전
  적격 baseline 대비 시간당 증가율과 설정 가능한 보존 ceiling 초과를 exact metadata·warning으로
  알린다. 짧은/비전진 run은 증가율 기준선으로 승격하지 않고 count 감소는 직전 acquired 대비
  간격과 무관한 inventory-loss,
  overlap/unavailable/nonforward는 별도 관측 품질 경고로 노출한다.
- **DATABASE/CORRECTNESS (breaking)**: outbox `relay_order` Identity를 제거했다. DB trigger가 system
  stream을 잠근 뒤 명시적 global sequence에서 번호를 배정하고 application은 stream →
  head/target/link 순서로 미리 잠근다. 따라서 번호는 전역 unique지만 commit-safe prefix는 각
  external system 안에서만 성립하며, raw/future writer도 allocation-before-lock을 우회할 수 없다.
  `external_system`/`target_key`는 API·repository·DB에서 trim된 Unicode NFC를 강제해 NFC-equivalent
  durable head/request가 Merkle snapshot이나 refresh lookup을 오염시키는 경로를 닫았다.
  `cache_target_keys` scope의 `target_key` 상한도 root identity와 같은 512자로 합쳤다.
- **CONTRACT**: target event와 stream reconciliation event를 `event_scope`로 분리해 empty 및
  tombstone-only snapshot에도 fake target tuple을 만들지 않는다. `cache_target.reconciled`
  payload의 `request_id`는 새 required field이며 request→fixed snapshot receipt 인과관계를
  `snapshot_id`와 함께 고정한다. admin reconciliation operation receipt도 생성한
  `snapshot_id`를 반환해 후속 stream read가 같은 snapshot에 도달했는지 검증할 수 있다.
  restore-fence 응답은 무효화 claim 수, 대체 delivery 수, 대체 reconciliation 수와 request UUID를
  durable fence receipt 그대로 노출하며 exact replay도 최초 값과 version을 보존한다. HTTP
  DTO와 OpenAPI object-level `oneOf`는 대체 reconciliation 수가 `0`이면 UUID가 `null`,
  `1`이면 `format: uuid`인 상관 불변식을 fail-close한다. recovery operation receipt의
  `operation_id`도 UUID로 좁힌다. target PUT/DELETE response는 non-null UUID `target_id`, `entity_tag`,
  양의 `target_sequence` 전용 DTO로 generation 4-tuple을 완성하며, nullable tombstone identity/sequence는
  GET read projection에만 남긴다.
- **OPENAPI (breaking)**: 공개 사용자와 서버 간 profile을 분리했다.
  `@kor-travel-map/user-client`는 `RoutePolicy.SERVICE` batch 타입을 더는 노출하지 않으며,
  서버 간 소비자는 `openapi.service.json`을 pin한다.

### curation 주소 fail-close·행별 provenance (2026-07-31, T-VN-H31R)

- **DATABASE (breaking)**: migration `0072_curation_provenance`로 import batch/row와
  accepted/revoked link decision을 append-only 정규화하고 current item을 exact row/target에
  composite FK로 결박했다. history는 DB trigger가 UPDATE/DELETE/TRUNCATE를 거부하고,
  import/supersedes FK는 같은 item만 허용한다. 기존 link는 `legacy_unattributed`로 이관한다.
- **CORRECTNESS**: `address_hint`는 preview evidence일 뿐 자동 링크 권한이 아니다.
  구조화 주소 field의 Unicode/literal hierarchy와 versioned alias만 후보 검색에 사용하며,
  public read는 explicit/admin/recovery accepted decision이 없는 link를 fail-close한다.
- **API**: admin import 응답에 `import_batch_id`, item에 link provenance를 추가하고
  official 등대 import의 sidecar hard-require, batch/current-row provenance 조회와 cursor 기반
  `GET /v1/admin/curations/link-audit`를 제공한다.
- **RECOVERY**: 선택적 forward recovery와 Feature merge는 기존 non-legacy accepted link만
  재승인한다. legacy/무결정/revoked link는 공개 불가 상태를 유지한다. duplicate loser
  membership은 삭제하지 않고 revocation+archive tombstone으로 보존하며, loser source가
  이기면 survivor 소유 merge row를 append한다.

### 주소 finding authoritative generation·curation 링크 감사 보강 (2026-07-31, H32R/H34R)

- **DATABASE**: mutable `payload.observed_run_id` sweep을 제거하고 provider/dataset scope,
  external run별 monotonic generation/receipt, run별 immutable dedupe-key observation set을
  migration `0071_integrity_observations`로 정규화했다.
- **CORRECTNESS**: authoritative·complete receipt를 가진 최신 generation만 stale finding을
  닫는다. 현재 run과 더 새 partial run의 관측, 사람이 확인한 `acknowledged`, 다른 subsystem
  finding은 sweep하지 않는다.
- **OPS**: resolved finding 90일 purge가 consistency maintenance job과 daily schedule에서
  실제 실행된다.
- **AUDIT**: H25B 링크 검증은 public repository 정본을 재사용하고 linked name·exact-name
  candidate Feature ID를 현재 링크에 결박한다. read-only repeatable-read DB snapshot의
  모집단·대상 수·identity를 JSON 보고서에 기록한다.
- **CLI (breaking)**: 모호한 `--all`을 제거하고 `--scope public|approved`로 감사 모집단을
  명시한다.

### backup/restore hard-crash effect fence (2026-07-31, T-VN-12)

- **RELIABILITY**: backup/create/restore/swap은 DB의 immutable `effect_token`과 고정 이름
  hardened Docker fence를 mutation 전에 결합한다. API/wrapper가 hard crash해 PostgreSQL
  session lock이 풀려도 daemon fence가 동일·다른 command의 중복 effect를 막는다.
- **BEHAVIOR (breaking)**: marker 없는 `effect_started`는 자동 재실행하지 않고
  `409 BACKUP_EFFECT_MANUAL_RECONCILIATION_REQUIRED`로 fail-close한다. host script 직접
  실행도 DB command identity와 pre-acquired fence가 없으면 거부한다.
- **SECURITY**: fence는 canonical local immutable Image ID만 `--pull=never`로 사용하고
  exact command/input/source labels, network none, read-only rootfs, capability 제거,
  `no-new-privileges`, 비 root user와 PID 제한을 검증한다.
- **CORRECTNESS**: create destination reservation은 exact fence 성공 뒤에만 만들며, 동일
  key의 stale `prepared` retry는 lock 안에서 DB phase를 다시 읽어 500이나 중복 fence
  채택 대신 기존 manual-reconcile/replay 결과로 수렴한다.

### sparse 다중 날짜 weather batch (2026-07-30, T-VN-16C)

- **CHANGED**: `POST /v1/features/weather/batch` 요청을 단일
  `feature_ids + target_at`에서 날짜별 sparse `targets[{target_at, feature_ids}]`로
  전환했다. target은 오름차순 최대 366개, target별 ID 1~200개, 전체 실제 pair
  2,000개이며 Feature ID는 256자 이하다. 응답도 target/item 순서를 보존한다.
- **PERFORMANCE**: 여러 날짜의 parent·nearest source·current·24시간 timeline을
  PostgreSQL statement 한 번에서 계산한다. 고유 parent별 spatial 후보 집합은 한 번만
  계산하되 최종 source는 각 target의 `known_at` fact 적격성으로 결정해 미래에 추가된
  series가 과거 snapshot을 바꾸지 않는다. 날짜에 속하지 않는 Feature의 불필요한
  Cartesian product와 같은 target/source bundle의 metric 반복을 만들지 않는다.
  실데이터 clone의 40 target × 5 Feature(200 pair)는 공유 card 40개·metric 11,763행을
  5.77초에 반환했다.
- **CHANGED**: `found` item은 metric을 반복하지 않고 target-local `card_key`를 참조하며,
  공유 payload는 각 target의 `cards[]`에 한 번만 둔다.
- **RELIABILITY**: DB 진입 전 planning work(`pair + 5 × 고유 Feature`) 2,500,
  fact projection 전 공유 card×physical series 150,000, 전체 metric 20,000행,
  보수적 전체 응답 추정치 8 MiB와 PostgreSQL `statement_timeout` 20초를 독립적으로
  제한한다. 결과 예산 초과는 부분 weather 없이
  `413 WEATHER_BATCH_RESULT_LIMIT_EXCEEDED`, timeout은 DB 취소 완료 뒤
  `503 WEATHER_BATCH_UNAVAILABLE`로 전량 거부한다.

### set-based weather snapshot batch (2026-07-30, T-VN-16A)

- **ADDED**: service-token 전용 `POST /v1/features/weather/batch`가 중복 없는 Feature ID
  1~200개를 한 PostgreSQL snapshot statement로 읽는다. 입력 순서를 보존하며 각 item을
  `found|no_data|retired`로 구분하고, `current`와 24시간 `timeline`을 함께 반환한다.
- **CHANGED**: 단건 `GET /v1/features/{feature_id}/weather`도 같은 batch repository를
  재사용해 parent 404와 빈 weather 판정을 일치시킨다. `asof`는 target time만 바꾸고
  known-at은 요청 시각을 유지한다.
- **API**: metric에 `provider`·`weather_domain`, `valid_at`/`valid_from`/`valid_until`,
  선택 기준 `effective_at`을 노출한다. forecast는 issued/collected known-at cutoff를
  모두 지키고, 만료 range는 current에서 제외한다.
- **PERFORMANCE**: migration `0069_weather_series_catalog`가 physical-series registry,
  exact-prefix effective-time index, 공개 `kind='weather'` 전용 partial GiST를 도입한다.
  실데이터 clone에서 일반 place 단건은 17.8ms, 200건 batch는 1.27s였고 weather fact
  sequential scan 없이 두 인덱스를 사용했다. 후속 DDL 실패 뒤 재시도는 이미 valid인
  대형 index를 재사용해 성공한 단계부터 이어간다.
- **RELIABILITY**: 파괴적 admin Live helper도 registry row의 exact series identity와 FK를
  parent lock 아래 검증하고 cleanup한다. 새 weather child table이 추가돼도 owned fixture
  정리가 조용히 불완전해지지 않는다.

### 큐레이션 import 검토 상태·운영 복구 원자성 (2026-07-30, #893)

- **FIXED**: 주소 hint가 있는 이름+주소 유일 후보는 ADR-063 계약대로 자동 연결한다.
  주소 없는 이름 단독 후보는 `review_required`로 반환해 “후보 다수”와 구분하고 admin UI에
  “수동 검토”로 표시한다.
- **RELIABILITY**: H33 오링크 해제와 integrity finding 기록을 한 transaction으로 묶어
  ledger 실패 시 링크 해제도 rollback한다. 이미 해제됐거나 올바르게 재연결된 행은 허위
  open finding을 만들지 않는다.
- **VALIDATION**: H25B 공식 CSV 역반영은 DB active identity 3-tuple과 기존 `feature_id`를
  전체 파일 쓰기 전에 검증하고, 불일치·누락·중복이면 CSV와 manifest를 바꾸지 않는다.

### 주소 검증 결과 durable 기록 (2026-07-29, T-VN-H30A)

- **OBSERVABILITY**: 주소/좌표 검증 결과가 `ops.data_integrity_violations`에 남아
  **run이 사라져도 증거가 보존되고 `/admin/issues`에서 조회된다**. 이전에는 Dagster run
  metadata에만 있었다. 격리 clone 실증: finding 106건 기록, 재실행에도 106 유지.
- **DATABASE**: migration `0067_integrity_dedupe_key` + `0068_integrity_last_seen`.
  key는 provider/dataset/source entity type+id/violation code 전체의 고정 길이
  `av2_<sha256>`이며 열린 이슈 한정 부분 unique index로 접힌다. `detected_at`은 최초 탐지,
  `last_seen_at`은 최신 recurrence로 분리한다. Feature 삭제는 FK `SET NULL`이라 ledger를
  지우지 않는다.
- **API**: `AsyncKorTravelMapClient.record_address_validation_findings()` 추가.
  `feature_id`/`source_record_key`는 FK이므로 **적재된 대상에만** 연결하고, 적재 전 단계에서
  drop된 행은 id를 payload로만 나른다. 결과는 `observed/unique/upserted`로 구분하고,
  strict 경로의 기록 실패는 typed error로 fail-closed한다.
- **ADMIN/OPS**: issue record에 `last_seen_at`을 추가하고 목록 cursor와 index를 최신 관측
  순서로 바꿨다. recurrence는 실제 `feature_id`/`source_record_key`도 최신 target으로 갱신한다.
- **OBSERVABILITY**: MOIS provider가 `AdminEvidence`를 채운다. MOIS는 payload에 법정동코드가
  있으면 역지오코딩을 호출하지 않아 staleness 대조가 성립하지 않는데, 그 사실이 `claim_only`로
  집계돼 `unarmed`(미계측)와 구분된다.

### 주소 검증을 행정코드 교차검증으로 교체 (2026-07-29, T-VN-H28A/B, #673)

- **FIXED**: provider 후보가 주소 문자열 때문에 영구 미적재되던 문제를 해결했다. 기존 규칙은
  좌표 역지오코딩 시군구명이 provider 주소 문자열에 부분문자열로 없으면 error → drop이었는데,
  실측(kor-travel-concierge 1,477 후보)에서 **380건을 drop했지만 기존 규칙으로 불일치
  근거가 성립한 건은 0건**이었다(전체 후보의 일반적 좌표 정확성을 증명한다는 뜻은 아니다).
  그중 **375건은 provider 주소에 시/군/구 토큰이 아예 없어**(`부산 기장 조방국밥`) 좌표의
  옳고 그름과 무관하게 부분문자열 검사가 통과 불가였고, 4건은 축약·단계 표기 차이,
  나머지 1건은 정지오코딩상 **143 m 경계** 케이스였다. 새 규칙 적용 후 **1,477건 전량 적재**.
- **BEHAVIOR (breaking)**: `provider_address_mismatch` / `provider_address_partial_match`
  issue code는 **발행 중단**됐다(기존 기록은 보존). 같은 축(provider 주소 문자열 ↔ 좌표
  역지오코딩 행정구역명)은 위 세 결함을 고쳐 `provider_address_region_disagreement`
  **warning**으로 계속 방출한다 — `Address.sigungu_name` 기반이라 **모든 provider**에 적용된다.
  추가로 payload 행정코드와 역지오코딩 코드가 어긋나면
  `admin_code_stale_{sido,sigungu,emd}` warning을 낸다. 이는 **위치 검증이 아니라 producer
  캐시 낡음 검출**이다 — 최소 kor-travel-concierge에서 payload 코드는 같은 역지오코딩
  결과의 캐시본이므로 좌표 정확성의 독립 증거가 아니다.
- **BEHAVIOR**: 좌표 역지오코딩이 결과를 내지 못했지만 provider 행정코드로 적재 가능한 경우
  `reverse_geocode_unavailable` warning을 낸다. 좌표 정합성이 미확인 상태임을 드러내되
  적재는 막지 않는다.
- **RELIABILITY**: `strict`와 `ensure_feature_address_valid()`는 **모든 error**에서 run을
  중단한다. 영구 손실 가능성이 있는 `drop` 모드만 명시적 code 화이트리스트
  (`DROPPABLE_ISSUE_CODES` = `reverse_geocode_failed`, `missing_address`)를 적용해, 신규
  error가 검토 없이 레코드 삭제 사유가 되지 않게 한다.
- **FIXED**: provider payload에 시군구코드만 있고 법정동코드가 없을 때 `Address` 코드 정합성
  검증이 예외를 던져 **레코드 1건이 batch 전체 적재를 중단**시키던 경로를 제거했다. 법정동코드가
  있으면 시군구·시도를 거기서만 유도하며, batch 변환에 건별 격리 옵션을 추가했다.
- **OBSERVABILITY**: materialization metadata에 `address_validation_evidence_grades`,
  `address_validation_name_states`, quarantine의 안정 item key·reason code가 추가됐다.
  행정코드/이름축 검증 성립 여부와 필수 필드 누락을 분리해, 판정 불능이나 silent omission을
  “이상 없음”으로 오독하지 않게 한다. `upserts == bundles + quarantine` 불변식도 강제한다.
- **API**: `FeatureBundle.admin_evidence`(`AdminEvidence`) 필드가 추가됐다. 기본 `None`이며
  기존 생성 코드는 영향받지 않는다.

### kor-travel-geo backend 인증·typed 오류 계약 (2026-07-29, T-VN-H21/#881)

- **SECURITY (breaking)**: API/Dagster/CLI가 kor-travel-geo public key를 URL query에 넣던
  경로를 제거했다. backend는 geo public endpoint에 `X-KTG-API-Key` header만 사용하며
  `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`를 결선한다. geo admin trusted-proxy
  secret/role은 Map에 주입하지 않는다.
- **SECURITY**: credential은 `SecretStr`로 보관하며 request URL에는 query가 없다.
  transport/status 원본 httpx 예외도 chain하지 않아 INFO URL·응답·traceback frame에서
  secret이 노출되지 않는다.
- **API**: `GeoAuthNotConfiguredError`와 `GeoRequestError`는 admin issues, offline upload,
  feature-update 경계를 지나도 각각 503 `GEO_AUTH_NOT_CONFIGURED`, 502 `PROVIDER_ERROR`
  problem+json으로 유지된다.
- **CLI**: `import` 명령이 geo 결선 누락 시 traceback(exit 1) 대신 stderr 메시지와
  `exit 2`(`_EXIT_INVALID`)로 끝난다.
- **REMOVED**: 실제 소비자가 읽지 않던 `openapi-sha256.json`과 생성·검사 코드를 제거했다.
  OpenAPI freshness는 소비자가 핀 commit의 spec/subset을 직접 비교하는 게이트로만 검증한다.

### React Doctor·durable curation (2026-07-27, T-VN-47·T-VN-H13·H24)

- **RELIABILITY**: admin frontend React Doctor full scan을 269개 파일·actionable 진단 0건으로 만들었다.
  canonical config와 CI verifier가 shadow config/ignore, 검사 command·범위 축소 및 package-level
  우회를 거부한다.
- **FIXED**: authoritative curation source에서 일시 누락된 item을 삭제하지 않고 비공개
  `source_present=false` membership으로 보존한다. 재등장 시 source 필드만 복원하며 운영자
  status·relation·reuse와 archived tombstone은 유지한다.
- **DATABASE (breaking)**: curation identity를 archived/NULL까지 포함한 exact unique로 바꾸고
  source/operator revision을 분리했다. legacy와 canonical operator intent는 양방향 동기화되며,
  source record가 없는 DELETE→새 UUID 재등장도 기존 membership과 tombstone을 복원한다.
  mutable theme slug 기반 collection key를 theme/source UUID 기반으로 바꾸고, 과거 slug 재사용으로
  탈취된 archived projection owner를 명시적 `legacy_projection_id`로 migration에서 복구한다.
  durable owner link가 없는 canonical-only item은 external identity가 일치해도 추정해 공개하지
  않고 모든 legacy-marker collection에서 `draft/admin_only` quarantine에 보존한다. mutable
  metadata marker가 지워진 이력도 immutable `legacy:` key namespace로 판별한다. reserved
  prefix가 아니라 exact `legacy:quarantine:<UUID>` key와 immutable migration creator 결합만
  재격리하지 않아 정상 `quarantine:` theme slug와 migration 왕복 identity를 함께 유지한다.
  quarantine metadata에 `migrated_from`이 추가돼도 upgrade·downgrade key rewrite는 이를 보존한다.
- **API (breaking)**: legacy curated admin create body에서 `selection_origin`·`selected_by`·
  `rejected_by`를 제거했다. POST/PATCH/DELETE provenance는 admin proxy 인증 principal만 기록한다.
- **CONCURRENCY**: Feature merge가 provider/operator 필드군을 독립 revision으로 reconcile하고
  curation collection을 item보다 먼저 잠가 import/admin writer와의 교착 가능성을 제거한다.
  legacy cross-title identity 조회는 source collection parent를 역순 잠그지 않고 item만 잠근다.
  source revision은 실제 쓰기 시각으로 비교하며, merge가 분리한 legacy projection은 이후
  canonical source membership을 되감을 수 없다.
- **DATABASE**: 0053 migration이 동일 effective scope의 legacy queued feature-update job을
  runtime dispatch 정렬로 하나만 보존하고 나머지를 감사 가능한 `cancelled` terminal로
  정규화한다. running 둘 이상과 cancellation audit marker가 있는 중복은 mutation 전에
  fail-close한다.
- **DATABASE (breaking)**: curation durable identity를 Feature target과 분리한
  `(collection_id, external_item_id, external_component_id)`로 전환했다. null→연결·A→B
  재연결에도 같은 membership UUID와 operator 상태를 보존하며, 같은 source item의 active
  current component가 동일 Feature를 중복 참조하면 DB partial unique가 거부한다. migration의
  `legacy:<UUID>` 다중 membership은 첫 공식 재적재에서 동일 Feature target의 새 component
  identity로 행 자체를 승계해 source 누락 여부와 무관하게 UUID·operator 상태·감사 이력을
  유지한다. 전환기 legacy projection writer의 신규 INSERT도 projection UUID 기반 component를
  부여하되 이후 authoritative identity 승계는 되감지 않는다. archived legacy tombstone은
  identity만 승계해 신규 active UUID 생성을 차단하고 operator/archive 이력을 보존한다.
  같은 source item·Feature에 legacy 승계 후보가 둘 이상이면 preview/commit이 같은 오류로
  fail-close해 임의의 UUID·operator 이력을 선택하지 않는다. theme upsert·collection
  create/import는 공통 write-boundary와 row 생성 전 stable key advisory lock을 공유하고,
  import가 key 정렬 후 Feature를 잠가 theme/key 역전과 미커밋 create+add 교착을 차단한다.
- **API/UI (breaking)**: curation item에 `external_component_id`, CSV template·preview에
  필수 `source_component_key`를 추가했다. 공식 복합 항목은 `component-01` 형식의 안정키로
  펼치고 admin UI가 item/component identity를 함께 표시한다.
- **MIGRATION**: 0064→0066을 한 Alembic transaction에서 연속 적용할 때 0065가 남긴 지연
  FK·trigger event를 0066 backfill 직후 검사·소진한 뒤 DDL을 수행한다. pending trigger event로
  `ALTER TABLE`이 중단되던 실데이터 clone 경로를 회귀 테스트로 고정했다.
- **TESTED**: n150 prod 격리 clone을 0036→0066으로 전진하고 실제 admin UI에서 공식 CSV를
  preview/commit했다. 공식 collection/item 19/486, component 2/2, operator adoption 2,
  duplicate target 0과 prod 불변을 확인했다. clean fixture 기본 기대값은 유지하되 실제
  operator override와 최신 Feature 매칭으로 달라지는 공개 membership·미연결 수는 Live env로
  명시해 실데이터 변화가 회귀를 가장하지 않게 했다.
- **SECURITY (#868)**: 기존 c6c 정본 `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` direct alias를 우선
  유지하면서 `KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET`를 fallback으로 수용한다. canonical-only
  배포의 gate와 잘못된 proxy header `403`, legacy-only·미설정·동시 설정 우선순위를 회귀로 고정했다.

### Admin frontend lint·schedule recovery·가격 series identity (2026-07-27, T-VN-44)

- **FIXED**: 유효한 admin session으로 `/login`에 재진입할 때 Next `ReadonlyHeaders`의 내부
  `headers` 필드를 request wrapper로 오인해 500을 내던 인증 판정을 direct `get()` 우선으로 고쳤다.
- **FIXED**: schedule cron PATCH 응답 유실·409·terminal audit 실패 때 열린 dialog가 페이지를 inert로
  두지 않는다. 편집 dialog를 닫고 관련 control을 잠근 뒤 동일 idempotency claim으로 복구할 수 있다.
  reload/hydration 중 storage 복구가 끝나기 전뿐 아니라 schedule 목록 identity가 바뀌는 scan·confirm
  경계에서도 과거 claim 조작을 fail-closed하고, 최신 목록 scan 뒤 도착한 과거 mutation settle이 상태를
  다시 잠그지 않는다.
- **API (breaking)**: price card `current`와 public/admin 지도 `price_summary`의 cardinality를 제품당
  1건에서 `provider + price_domain + product_key` series당 최신 1건으로 바꿨다. 동일 제품의 여러
  공급원을 버리지 않으며 marker는 중복 제품에 provider/domain을 표시한다.
- **FIXED**: 가격 이력 chart가 같은 product key의 서로 다른 provider·price domain을 별도 색상 series로
  표시한다. exact duplicate list row도 안정적인 occurrence key로 구분한다.
- **PERFORMANCE**: migration 0064가 provider를 누락한 구 index를 concurrent 교체한다. current는 기존 natural-key
  unique index의 역방향 scan을 재사용하고, 전체 series history만 관측순 index 하나로 지원한다. 새
  인덱스를 먼저 만든 뒤 구 인덱스를 제거해 online DDL 동안 적어도 하나의 access path를 유지한다.
  PostgreSQL catalog의 column 순서·정렬·predicate·INCLUDE·valid/ready/live 상태를 검증해 stamp 유실 후
  재실행과 잘못된 동명 index도 안전하게 복구한다.
- **RELIABILITY**: admin frontend full ESLint를 0 warning gate로 고정했다. TanStack compiler 비호환은
  단일 파일·정확한 hook 호출만 허용한다. verifier는 실제 frontend/e2e의 JS·TS 계열 전체 파일 집합과
  모든 function-like AST를 대조해 global/file ignore, module·nested·anonymous directive, legacy directive,
  inline disable, allowlist 확대를 거부한다.

### Admin frontend npm audit 0 전환 (2026-07-27, T-VN-43)

- **SECURITY**: clean admin frontend install의 npm 취약점을 low/moderate/high 합계 16건에서 0건으로
  내렸다. Next 16.2.12, PostCSS 8.5.23, Sharp 0.35.3과 안전한 YAML/glob 전이를 lockfile에 고정하고
  CI가 high 이상 취약점 재유입을 거부한다.
- **CHANGED**: 빌드에 필요하지 않은 shadcn CLI/MCP·React Hook Form/resolver/Zod와 취약 legacy
  Next ESLint preset을 제거했다. generated UI source가 쓰는 Tailwind variant 4개만 프로젝트 CSS가
  소유하며, React Hooks·React-X/React-DOM·Next/import/a11y flat config가 현대 React 계약을 직접
  검사한다.
- **RELIABILITY**: Node 22.23.1/npm 10.9.4와 C7 Playwright 1.60.0을 exact pin했다. Redocly patch는
  frontend/C7 Docker build 모두에서 version·원문 drift를 fail-close하고, 실제 Next image optimizer
  smoke가 Sharp ABI와 SVG→WebP 변환을 검증한다.
- **RELIABILITY**: `npm ls`의 성공 종료코드와 별도로 JSON `problems`를 검사해 Sharp 0.35.3의
  선택적 WASM fallback 6개만 exact allowlist로 허용한다. frontend ESLint gate도 파일 문자열이 아니라
  계산된 effective config에서 canonical React Hooks와 중복 analyzer·severity 계약을 검증한다.

### Admin 지도 control·query identity 하드닝 (2026-07-26, T-VN-42)

- **FIXED**: `/features`와 `/curated-features`의 우측 상세 패널이 MapLibre 우하단
  `ScaleControl`을 덮지 않는다. mocked·live 브라우저 검증은 실제 bounding box 비겹침을
  공용 계약으로 확인한다.
- **FIXED**: admin in-bounds items/clusters cache identity가 HTTP 요청과 같은 원본 bbox·정수 zoom·
  mode·filter를 사용한다. 13.x zoom에서 items UI가 server cluster 응답을 받는 경계 오류와
  반올림 bbox key 충돌을 제거했다.
- **RELIABILITY**: admin feature live recovery는 source commit·API/Playwright image·compatible-pair·
  host attestation으로 고정한 exact execution identity가 다르면 cleanup mutation 전에 거부한다.
  성공 결과에는 canonical identity SHA256과 pair/attestation hash만 남긴다.

### Ops live proxy close 전달 보강 (2026-07-20, T-VN-H11 #809)

- **CHANGED**: 인증 거절 WebSocket은 accept부터 `4401` close까지를 보호된 child task에서
  수행하고, close는 handshake 뒤 10ms의 bounded settle window 후 시도한다. ASGI transport
  flush 보장이 아닌 배포 조합의 best-effort 완화이며, 실제 Uvicorn TCP 반복 회귀와 공개
  Chromium 결과를 인수 기준으로 둔다.
- **RELIABILITY**: accept/close 도중 outer task가 반복 취소돼도 bounded operation을 끝낸 뒤
  취소를 재전파한다. 성공한 accept에는 close를 정확히 한 번 수행한다. pre-handshake accept
  timeout·예외에는 application close를 추가 전송하지 않고
  Uvicorn HTTP fallback에 맡긴다. ticket 없음·변조의 data frame 0건과 인증·nonce 계약은
  바뀌지 않는다.

### Ops live 브라우저 인증 거절 close 복구 (2026-07-20, T-ADM-C7W #806)

- **FIXED**: 변조된 signed WebSocket subprotocol을 제시한 Chromium도 handshake 실패 `1006`
  대신 인증 거절 `4401`을 관측한다. 서버는 요청된 candidate 중 형식·길이 제한을 통과한 단일
  protocol만 transport 협상에 사용하고, 인증·nonce claim·application loop에 진입하거나 data
  frame을 보내지 않은 채 즉시 닫는다.
- **SECURITY**: ticket 없음, 복수 candidate, 형식 위반과 길이 초과 입력은 반사하지 않는다.
  서명·payload·TTL·nonce 검증 경계는 바뀌지 않는다.

### Weather collected_at 단조 upsert (2026-07-20, T-VN-H09 #797)

- **FIXED**: 같은 weather semantic tuple에 더 오래된 provider backfill이 늦게 도착해도 최신
  `collected_at`과 값이 과거로 되돌아가지 않는다. 동률 correction은 실제 내용이 다를 때만
  갱신하고, 완전히 같은 재적재는 물리 UPDATE를 생략한다.
- **CHANGED**: current-row의 `collected_at`은 non-null `TIMESTAMPTZ` latest-wins 계약이다.
  DB schema와 OpenAPI는 바뀌지 않는다.

### Destructive 배포·backup actor 경계 완결 (2026-07-20, T-VN-H02R #796)

- **SECURITY (breaking)**: 공식 standalone Docker compose도 destructive 기본값을 `false`로
  해석한다. 파괴적 조작은 명시적 `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED=true`가 있어야 한다.
- **SECURITY**: backup create/delete/restore/swap의 managed-file event actor를 고정
  `api:admin` 대신 인증된 `AdminProxyContext.actor`로 기록한다.
- **API (breaking)**: 사용되지 않던 `RestoreSwapRequest.operator` 입력을 제거한다.

### Route wiring startup·public CORS exact preflight (2026-07-20, T-VN-H03R #798)

- **SECURITY**: `create_app()`이 route 분류와 실제 dependency wiring을 함께 검증한다. public-keyed/
  operator miswire와 stale exception은 서버 startup을 실패시킨다.
- **SECURITY (breaking)**: public CORS preflight는 route policy matrix의 실제 method와 CORS
  safelist + `If-None-Match` + `X-Kor-Travel-Map-Api-Key`만 허용하고, 성공 응답도 matching
  route의 method만 광고한다. conditional GET의 `ETag`는 browser에 노출한다. 다른 method/header는
  400이며 ACAO를 내보내지 않는다. service/operator 표면의 CORS 비노출은 유지한다.

### destructive admin 기본값 fail-closed (2026-07-20, T-VN-H02)

- **SECURITY (breaking)**: `admin_destructive_enabled` 기본값을 `True`에서 `False`(fail-closed)로
  내렸다. 파괴적 `/admin` 작업(restore/swap·feature deactivate·POI cache target·backup·offline
  upload delete·managed file purge)은 `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED=true`를 명시하지
  않으면 403을 반환한다.
- **FIXED**: 문서화된 env 이름 `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED`가 실제로 필드에
  바인딩되도록 `validation_alias`를 추가했다. 기존에는 env prefix 규칙상 무시되던 이름이었다.
- **DEPLOY (breaking)**: PR #793 단계의 compose 기본 `true` 예외는 T-VN-H02R(#796)이
  clean-cut했다. 코드와 standalone compose 모두 기본 `false`이며 승인된 배포만 `true`를 명시한다.

### Public weather·curation raw lineage clean-cut (2026-07-20, T-VN-59)

- **SECURITY (breaking)**: public forecast row에서 `source_record_key`를 제거하고, public KMA
  alert는 typed 도메인 필드만 반환한다. alert source record identity·provider 원문 payload·
  ingestion timestamp는 새 admin BFF operator endpoint로 이동했다.
- **SECURITY (breaking)**: public curation collection/item에서 자유형 `metadata`를 제거하고,
  public item에서 `source_record_key`를 제거했다. admin collection/item DTO는 두 값을 계속
  제공한다.
- **CHANGED**: user OpenAPI exporter가 모든 public response reachable schema를 재귀 순회해 raw
  lineage field와 curation metadata 재유입을 거부한다. 공개 DTO와 admin/operator raw DTO는
  상속 없는 별도 타입이다.

### Admin correction 편집 기준 고정 (2026-07-20, T-VN-58 #785)

- **FIXED**: Feature 수정·삭제가 제출 직전에 최신 revision을 다시 읽어 stale draft를 새 기준으로
  제출하던 동작을 제거했다. 편집 시작 detail과 raw strong `ETag`를 불변 basis로 고정해 원래
  `If-Match`를 그대로 보낸다.
- **CHANGED**: 서버가 `412 Precondition Failed`를 반환하면 작성 중인 입력을 보존하고 자동
  재시도하지 않는다. 운영자가 명시적으로 최신값을 다시 불러온 경우에만 새 detail과 basis를
  적용한다. DB와 REST/OpenAPI schema는 바뀌지 않는다.

### Public route security·user OpenAPI 단일 정본 (2026-07-20, T-VN-57)

- **SECURITY**: 조립된 route policy matrix에서 모든 `public-keyed` operation의
  `PublicApiKey OR ServiceToken`, `public-unauthenticated`의 무인증, `service`의
  `ServiceToken` OpenAPI 계약을 자동 파생한다. curated 4경로만 별도 처리하던 수동 목록을
  제거했다.
- **CHANGED (breaking)**: user OpenAPI 표면도 같은 route policy와 method metadata에서
  자동 파생한다. 기존 수동 목록에서 누락됐던 `GET /v1/features`와
  `GET /v1/features/{feature_id}/contained-features`가 user spec과 생성 TypeScript에
  포함된다.
- **TEST**: 조립 route ↔ full OpenAPI ↔ user OpenAPI의 path/method/security를 양방향
  비교해 누락·과포함·method/security drift를 거부한다.
### T-VN-03 잔여 route 인증 경계 clean-cut (2026-07-19)

- **SECURITY**: public curated GET 4개를 public API key 경계로, ops metrics/log/
  consistency/deep-health GET 6개를 admin BFF 또는 `OpsToken+ops:read` 경계로 옮겼다.
  MOIS raw debug는 local-dev mount에서도 admin BFF를 요구하고 production에서는 route를
  mount하지 않는다.
- **CHANGED**: route policy wiring exception을 0건으로 만들고 full/user OpenAPI와
  admin/user 생성 TypeScript에 public/operator security 계약을 반영했다. 삭제 route,
  호환 alias, 새 secret/env, DB migration은 추가하지 않았다.

### Feature search COUNT opt-in + signed cursor (2026-07-19, T-VN-15)

- **CHANGED (breaking)**: `/v1/features/search`의 `include_total` 기본값은 `false`다.
  이 모드에서는 COUNT SQL을 실행하지 않고 `meta.page.total=null`을 반환하며,
  `include_total=true`일 때만 같은 정규화 filter의 COUNT를 1회 실행한다.
- **SECURITY**: search cursor를 version·정규화 query fingerprint·keyset을 담은 canonical
  payload와 HMAC-SHA256 서명으로 교체했다. 변조, 알 수 없는 version, 다른 query/filter/page
  계약에 재사용한 cursor는 DB 접근 전에 서로 구분되는 typed RFC7807 422로 거부한다.
- **SECURITY**: production feature surface는 API 전용
  `KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET`(공백 없는 32자 이상)을 필수화한다. 이 값은
  public/admin/service/ops/metrics credential과 공유할 수 없고 API container에만 주입한다.
  local-dev 미설정은 process-local 난수 key를 쓰므로 재시작·multi-worker 연속성을 보장하지 않는다.
- **CHANGED (breaking)**: 내부 `feature_repo.search_features`와
  `AsyncKorTravelMapClient.search_features`는 `limit` 대신 `page_size`, 명시적
  `cursor_signing_key`, `include_total` 계약을 사용한다. 호환 shim은 두지 않는다.

### C6c manifest v4 Map runtime provenance (2026-07-19, T-ADM-C7P)

- **SECURITY**: C7 runtime attestation은 compatible-pair manifest v4의 Map API·UI·
  Dagster web·Dagster daemon image ID를 실제 compose runtime과 각각 exact 비교한다.
  v3 manifest, 누락·추가 필드, role별 image mismatch는 mutation 전에 fail-close한다.

### C7 mocked summary 가시성 검증 보완 (2026-07-19, PR #755 리뷰 후속)

- **FIXED (test)**: `/ops/datasets` 상태 요약의 exact projection이 DOM에 하나만
  존재하는 것뿐 아니라 실제로 보이는지도 mocked E2E에서 검증한다.

### C7 prod 심층 리뷰 보안 후속 (2026-07-19, PR #754)

- **SECURITY**: Docker build context에서 모든 `*.local.md`를 제외하고, C7 Playwright
  executor의 host network/IPC 공유를 bridge network/private IPC로 축소했다.
- **FIXED**: runner가 전체 상태 감사 도구를 통과해야 lock과 mutation 상태를 만들며,
  실패 시 `BLOCKED.json`과 복구 journal/runtime을 보존한다. 성공이 완전히 입증된
  경우에만 runtime과 attestation snapshot을 정리한다.

### C7 prod 실행 경계·증거 보강 (2026-07-19, T-ADM-C7H)

- **SECURITY**: 파괴적 live E2E 전에 exact Git commit의 root-owned runner/helper/attestation module
  archive snapshot,
  C6c compatible-pair manifest와 실제 Map/PinVi
  API image, compose project, Map API/UI/Dagster web·daemon/PinVi API의 image·command·environment,
  단일 Alembic current/head/check를 root-owned attestation과 exact 대조한다. 모든 read-only preflight
  전에는 `BLOCKED.json`이나 mutation journal을 만들지 않는다.
- **SECURITY**: attestation 모듈은 runner bootstrap이 owner/mode/ancestor/hash를 확인한 동일 bytes만
  실행한다. root로 실행하는 runner/helper/module/상태 감사기 4개 hash와 compatible-pair·OCI/runtime
  metadata 변조는 실행형 음수 테스트로 fail-closed를 고정한다. INT/TERM은 130/143으로 종료한다.
- **CHANGED**: C7은 고정 official digest 기반의 commit-labelled Playwright executor image ID에서만
  실행한다. 실제 Dagster `feature_update_request_worker` definition과 terminal run의 request/generation/
  scope/sensor tag를 검증한다. spec별 redacted JUnit/HTML/JSON과 복구 journal은 root-owned evidence로
  보존하고 screenshot, auth storage와 trace ZIP은 생성하지 않는다.
- **ADDED**: `audit-c7-prod-live-state.py`가 secret·UUID를 출력하지 않고 active lock, journal phase,
  partial runtime/temp/evidence 안전성을 점검한다. 자동 sentinel clear는 제공하지 않는다.
- **ADDED**: Map API/UI/Dagster image는 source revision OCI label을 싣고 C7 attestation이 실제 image
  label과 clean checkout을 대조한다. C7 executor는 durable creator/outcome/CID 아래 create/start를
  분리한다. SIGKILL 뒤 남은 C7 container는 creator identity·CID/name·label·run 전용 mount·비활성
  lock을 확인하는 `stop-c7-prod-live-container.py`로만 중지하며 journal/sentinel은 보존한다.
### Admin 지도 비공개 Feature 조회·카드 복원 (2026-07-19, T-VN-04A #741)

- **ADDED**: `GET /v1/admin/features/in-bounds`가 삭제되지 않은 base Feature를 대상으로
  bbox item과 행정구역 cluster를 제공한다. 반복 `status` 필터로 `draft`·`active`·
  `inactive`·`hidden`·`broken`을 선택하며, public active-only projection은 바꾸지 않는다.
- **ADDED**: admin weather/price card endpoint가 비공개 Feature의 존재와 weather anchor를
  admin 경계에서 판정한다. 운영 지도와 상세 화면은 이 경로만 사용하므로 공개 projection의
  404/빈 카드로 비공개 상태가 가려지지 않는다. soft-delete 또는 `status=deleted` target은
  삭제 전 운영 상태와 구분해 404로 fail-closed한다.
- **CHANGED**: Admin Feature 지도에 운영 상태 필터와 truncation 표시를 추가하고, 지도·테이블·
  marker 상세가 동일한 admin in-bounds 결과를 사용하도록 통일했다.

### Tier-2 release benchmark 측정 정확성 (2026-07-19, T-VN-21R #767)

- **FIXED**: `--skip-seed` 200건 batch가 fixture 전용 고정 ID를 조회해 0행을
  성공 측정하던 문제를 제거했다. public projection의 실제 non-notice ID 200개를
  결정적으로 선택하고, 수량이 부족하거나 대표 viewport가 비어 있으면 성공 report
  없이 fail-closed한다. seed의 inactive 분포와 selector 기대도 같은 규칙을 쓴다.
- **FIXED**: `EXPLAIN (BUFFERS)`의 상위 Plan에 이미 포함된 child shared read를
  재귀 합산하던 중복 계산을 제거했다. 각 viewport report는 terminal `LIMIT` 전
  `matched_rows`와 LIMIT 뒤 `returned_rows`/`minimum_returned_rows`를 함께 기록해
  truncation을 보존한다.

### 지도 in-bounds 완결성 + exact 공간 술어 (2026-07-19, ADR-073 D-9-3·D-9-4 T-VN-14)

- **FIXED**: `GET /v1/features/in-bounds`(및 `GET /v1/features`)의 `include_geometry`가
  결과집합(membership)을 바꾸던 버그를 고쳤다(F-8, EXPLAIN 재현 2220→2221행). 이제 후보
  술어가 `include_geometry` 값과 **무관하게 단일·동일**하고, 플래그는 route/area geometry를
  응답 payload에 직렬화할지만 제어한다(같은 feature 집합, payload만 차이).
- **FIXED**: route/area bbox 후보에 exact `ST_Intersects(geom, envelope)`를 추가했다. `&&`
  MBR prefilter만으로 생기던 false positive(경계상자만 겹치고 실제 geometry는 교차하지 않는
  route/area)를 제거한다. geometry가 있는 route/area는 centroid `coord` arm으로 우회하지
  않고 exact geometry arm만 사용하며, geometry가 없는 legacy 행만 coord로 fallback한다.
  point `coord`의 `&&`는 이미 정확해 그대로 두었고, `ST_Transform`은 술어에 넣지 않는다
  (ADR-012 — partial GiST `idx_features_geom_gist`가 `&&`로 구동됨).
- **FIXED**: cluster와 items가 같은 exact 공간 후보 universe를 사용한다. geometry가 bbox와
  교차하지만 centroid가 밖인 route/area도 cluster count에 포함하고, 대표 marker는 bbox와
  실제 교차한 geometry 부분 위에서 계산한다. 행정 경계를 가로지르는 geometry의 cluster
  귀속은 선택 단위의 저장 canonical 행정코드 하나로 고정해 feature당 1회만 집계한다.
- **CHANGED (계약)**: in-bounds 응답 `data`가 지도 완결성 계약을 명시한다 — `mode`(items|
  clusters), `truncated`(bool, F-8 silent truncation 해소), `coverage`(returned/limit),
  cluster 모드의 결정적 `cluster_key`. view 해석 metadata인 `cluster_unit`과
  `drill_down_unit`은 ADR-048 envelope 불변식대로 `meta.cluster`에만 둔다. truncation은
  `max_items+1` 조회로 명시 판정한다. `meta.cluster`가 존재할 때 `cluster_unit`은 필수
  enum이고 `drill_down_unit`은 필수 enum|null인 strict OpenAPI/TypeScript 계약이다.
- **INTERNAL**: bbox 후보 술어를 단일화했다 — 공통 attribute 필터(kind/category/provider)를
  `_bbox_attribute_filter_sql`로, 공통 공간 후보 술어를 `_bbox_candidate_predicate_sql`로
  한 곳에 정의해 경량/geometry/cluster 3변형의 이중 SQL 복제를 제거했다(D-9-4). weather/price
  LATERAL과 인덱스/모델은 건드리지 않았다(T-VN-38/T-VN-18 소유).

### Feature row_revision + If-Match/ETag 낙관적 동시성 (2026-07-19, D-10-3/D-9-8 T-VN-13)

- **ADDED**: migration 0062가 `feature.features`에 server-owned monotonic `row_revision`
  (bigint, DEFAULT 1)과 이를 모든 UPDATE에서 강제 증가시키는 `BEFORE UPDATE` 트리거를
  도입한다(0058 poi lock_version 패턴). `ADD COLUMN ... DEFAULT`는 PG11+ 메타데이터 전용,
  CHECK는 같은 migration transaction에서 NOT VALID→VALIDATE한다. pending change request에는
  제출 시점의 `base_row_revision`을 함께 저장한다. #727 provider-refresh policy revision과는
  별개 자원이다(합치지 않음).
- **ADDED**: public feature detail GET이 `ETag: "<row_revision>"`를 반환하고,
  `If-None-Match`가 일치하면 `304 Not Modified`(본문 없음)로 응답한다. Admin 소비자는 집계형
  detail 응답이 아니라 `GET /v1/admin/features/{feature_id}/revision`에서 같은 strong ETag를
  읽는다.
- **CHANGED (breaking)**: admin feature correction PATCH/DELETE는 정확히 한 개의 canonical
  `If-Match: "<row_revision>"`를 필수로 요구한다. 누락은 `428`, weak·wildcard·결합·중복·
  비정상/범위 초과 값은 `422`, stale 값은 `412`, 실제 부재는 `404`다. change-request 승인은
  호출자가 새 ETag를 보내지 않고 요청에 저장된 `base_row_revision`을 잠금 안에서 검증해,
  제출 뒤 provider 갱신이나 삭제가 끼어든 경우 `412`로 중단한다. add는 중간에 같은 ID가
  생기면 덮어쓰지 않고 충돌한다.
- **CHANGED**: bundled Admin frontend와 PinVi Admin HTTP client가 revision GET의 raw ETag를
  그대로 PATCH/DELETE `If-Match`로 전달하고, `412`를 새로고침 후 재시도가 필요한
  `PRECONDITION_FAILED`로 노출한다.

### 중복 GiST 제거 + weather source-record index (2026-07-19, D-12-3 T-VN-18)

- **CHANGED**: `feature.features`의 geometry 컬럼(coord/coord_5179/geom)에 geoalchemy2가
  자동 생성하던 full GiST 3개를 제거하고(migration 0061 + models
  `spatial_index=False`), 공개 술어 partial GiST 3개(`WHERE deleted_at IS NULL`)만
  유지한다. 공개 조회(bbox/nearby/in-area)는 모두 `deleted_at IS NULL`을 포함해
  partial index를 쓰므로 읽기 영향이 없고, insert/update마다 유지하던 색인이 6→3개로
  줄어 geometry write-cost가 낮아진다(실측 ≈1.2~1.3×).
- **ADDED**: `idx_weather_values_source_record`(partial) — 0060의 weather
  source-record FK(`ON DELETE SET NULL`)가 source_record 삭제 시 대용량 seq-scan하지
  않게 price 패턴을 미러링한 지원 index.

### 3단 성능·DDL gate 인프라 (2026-07-19, ADR-075 D-12-4 T-VN-21)

- **ADDED (CI gate)**: tier-1 성능 gate가 매 PR의 integration job에서 상시 실행된다
  (`tests/integration/test_perf_gate_tier1.py`). hot public query(bbox/in-bounds·nearby·
  search·detail·batch·category counts·cluster rollup)를 **planner 기본 설정으로** EXPLAIN해
  `feature.features` Seq Scan 부재와 기대 index 사용을 검증하고(`enable_seqscan=off` crutch
  금지), public batch read의 SQL 수가 item 수에 비례하지 않음(N+1 가드), 결과 컬럼이 frozen
  snapshot과 일치함(response-shape 회귀)을 확인한다. hot query registry·seed·EXPLAIN helper는
  `tests/integration/perf_gate.py`.
- **ADDED (release 도구, CI 아님)**: tier-2 release/cutover harness
  (`scripts/perf_tier2_release_harness.py`)가 100만+ 실분포 fixture에서 대표 viewport를
  `EXPLAIN (ANALYZE, BUFFERS)`로 재고 p50/p95·shared read blocks·응답 bytes를 JSON으로 기록한다.
- **ADDED (index PR 정책·helper)**: tier-3은 index/DDL 변경 PR이 변경 전후 write 비용·index
  크기를 첨부하도록 요구하고(리뷰 enforce), `perf_gate.measure_index_write_cost` helper를 제공한다.
- **DOCS**: `docs/architecture/performance.md` §8.3(ADR-075 D-12-4)이 세 계층 전체의 **정본**이다.

### weather 무결성 제약 (2026-07-19, ADR-072/075 T-VN-17)

- **ADDED**: migration 0060이 ``feature.feature_weather_values``에 price(0034)
  패턴을 미러링한 무결성 제약을 도입한다 — semantic tuple UNIQUE
  (feature_id, provider, weather_domain, forecast_style, metric_key, issued_at,
  valid_at, observed_at; ``NULLS NOT DISTINCT``), ``valid_from <= valid_until`` range CHECK, payload-object
  CHECK, source-record FK(``ON DELETE SET NULL``). CHECK/FK는 ``NOT VALID`` 후
  ``VALIDATE``, ~30M행이라 테이블 rewrite·STORED 추가 없이 적용한다.
- **CHANGED**: weather upsert writer가 ON CONFLICT 대상을 PK 해시에서 semantic
  tuple index로 전환한다(update-wins). 같은 순간을 다른 tz 표기로 적재해 생기던
  중복이 이제 흡수된다. migration은 `SHARE ROW EXCLUSIVE` writer fence를 먼저 잡고
  기존 중복 dedup(최신 collected_at 우선)과 non-concurrent unique index를 한 transaction으로
  수행한다. 실패 시 모두 rollback되어 INVALID index가 남지 않는다. 기존 CHECK/FK 오염은 첫
  commit 전에 거부하고 VALIDATE lock 대기도 5초로 제한한다. destructive dedup을 되돌릴 수 없는
  0060 downgrade는 Alembic destination 전역 guard로 descendant DDL 전에 차단하고,
  backup/PITR+구 writer image 동시 복구만 허용한다. 과거 partial retry 객체의
  `ACCESS EXCLUSIVE` 정리는 main build와 분리한 짧은 transaction에서만 수행한다.

### body actor 제거 — 감사 actor는 인증 principal에서만 파생 (2026-07-19, ADR-066 D-2 T-VN-20)

- **SECURITY**: 모든 admin write의 감사 actor(operator/actor/created_by/reviewed_by)를
  request body가 아니라 인증 principal(admin BFF의 `X-Kor-Travel-Map-Actor` →
  `AdminProxyContext.actor`)에서만 파생하도록 완결했다(ADR-066 D-2, T-VN-07 slice 완성).
  신뢰 경계 안에서 body가 감사 주체를 위조하던 경로를 제거한다. 대상: admin feature
  create/patch/delete·change-request approve/reject·deactivate(operator), admin issue
  조치(operator), dedup review(reviewed_by), auth-event(actor), curated select/unselect
  (actor), enrichment review(reviewed_by), offline upload create(created_by)·validate
  (operator). 제출·승인이 분리된 흐름(feature change-request)은 제출 principal과 승인
  principal을 각각 그 시점의 principal에서 보존한다.
- **REMOVED (breaking, admin-frontend-only)**: PinVi가 호출하지 않는 admin frontend 전용
  write는 body actor 필드를 schema에서 제거했다 — auth-event `actor`, curated
  select/unselect `actor`, enrichment review `reviewed_by`, offline upload
  `created_by`·validate `operator`. `extra="forbid"`라 옛 caller가 이 필드를 보내면 `422`다.
  admin frontend는 전송을 중단했다(BFF actor header만 사용).
- **DEPRECATED (accept-and-ignore, PinVi 호환)**: PinVi `origin/main` client가 아직 body로
  보내는 필드는 수용하되 무시한다(OpenAPI `deprecated: true`) — admin feature/issue의
  `operator`, dedup review의 `reviewed_by`. 저장 actor는 principal이며 body 값은 무시된다.
  PinVi가 전송을 중단하면(별도 PR, `docs/integration-map.md` §3.3) 제거한다.
### Alembic 제외 정책 구조 검증 보완 (2026-07-19, T-VN-19 리뷰 후속)

- **FIXED (internal)**: metadata 비교에서 임시 제외한 app-owned table 8개의 전체
  column type/nullability와 핵심 constraint/index를 빈 DB migration 통합 테스트로
  고정했다. 인증·운영 table의 핵심 CHECK도 잘못된 row를 실제 거부하는지 검증한다.
- **FIXED (internal)**: 비교 제외 index 4개를 이름 존재만 확인하지 않고 UNIQUE 여부,
  key 순서·표현식, partial predicate까지 PostgreSQL catalog 기준으로 검증한다. 새 ORM
  mapping이 생긴 table이 제외 목록에 남으면 Alembic 시작 단계에서 실패한다.
  `uq_curated_features_theme_feature_active`의 잘못된 `NULLS NOT DISTINCT` metadata 옵션은
  제거해 migration과 일치시키고 Alembic 일반 비교 대상으로 복귀시켰다.

### 공개 curated raw lineage 우회 차단 (2026-07-19, ADR-073 T-VN-05R)

- **SECURITY**: `GET /v1/curated-features`와 단건 상세가 admin DTO를 재사용하지 않고
  공개 전용 `PublicCuratedFeatureView` allowlist를 반환한다. 공개 계약은 `feature_kind`가
  판별자인 `place|event|notice|area|route|price|weather` union이며, 알 수 없는 kind는
  목록에서 제외하고 상세에서 404로 닫는다. `detail.payload`,
  `source_record_key`, DB/source identity, 선정 감사값, 자유형 metadata는 공개 응답과
  `openapi.user.json`/user 생성 타입에서 제거했다.
- **SECURITY**: `address`와 kind별 `detail`을 strict 중첩 DTO로 전환했다. place의
  `phones`, `reviews_link`, `business_hours`, `facility_info`도 검토된 키와 값 형태만 새로
  조립하므로 concierge YouTube/transcript/evidence 미러와 알 수 없는 nested raw 키가
  공개 응답을 우회할 수 없다.
- **REMOVED**: 공개 목록 query에서 내부 identity 필터 `theme_id`, `source_id`, `provider`,
  `dataset_key`를 제거했다. 공개 탐색은 `theme_slug`, 표시 텍스트, 위치 필터만 사용하고
  내부 identity 필터는 admin 목록에만 남는다.
- **UNCHANGED**: `/v1/admin/features/curated*`는 기존 `CuratedFeatureView`를 계속 사용해
  source record와 raw detail, 감사 actor/시각을 보존한다.

### 공개 raw payload 경계 제거 (2026-07-19, ADR-073 T-VN-05)

- **SECURITY**: 공개 feature detail·batch(`GET /v1/features/{id}`,
  `POST /v1/features/batch`)에서 provider raw 경계를 제거했다. raw observation
  lineage(`observations`: raw_data/raw_payload_hash/source_record_key)와
  `detail`의 provider raw passthrough(`payload` — MOIS 인허가의 mng_no/status_code/
  detail_status_*/opn_authority_code/title/epsg5174 포함)가 더 이상 공개 표면에
  노출되지 않는다. DB 컬럼·ETL은 그대로이며 공개 read projection에서만 벗겨낸다.
- **ADDED**: operator 전용 `GET /v1/features/{feature_id}/sources`(admin BFF 인증)
  가 feature의 현재 raw 관측 lineage를 제공한다.
- **CHANGED**: `GET /v1/features/{feature_id}/observations/{source_entity_key}/history`
  가 공개(public-keyed)에서 operator 인증(admin BFF)으로 이동했다. 두 raw lineage
  표면은 비공개/종료 feature도 감사할 수 있게 raw row 존재로 404를 판정한다.
- **CHANGED**: user-facing OpenAPI subset에서 raw observation lineage 표면 2종을
  제외했다(admin spec에는 유지). service batch는 요청 스키마가 `extra=forbid`라
  raw opt-in이 불가하고 고정 typed payload만 반환한다.

### Alembic metadata 정합 CI gate (2026-07-19, ADR-075 D-12-2 T-VN-19)

- **ADDED**: `tests/integration/test_alembic_metadata_consistency.py` — 빈 PostGIS DB →
  `alembic upgrade head` → `alembic check` diff 0건을 상시 검증하는 §8.1 gate. 기존
  integration CI job이 실행하며, 새 migration/table이 metadata 매핑이나 env.py 제외
  목록에서 빠지면 실패해 F-10 회귀를 차단한다.
- **CHANGED (internal)**: `alembic/env.py`에 `include_object` 필터를 추가해 비-app·미모델
  객체를 비교에서 명시 제외한다(blanket ignore 아님, 이름 나열): PostGIS `spatial_ref_sys`,
  ORM 모델이 아직 없는 app table 8개(weather/price/log/api-key/auth-event 계열 + ops-live
  claim/topic), alembic이 round-trip 못하는 partial/expression index 4개.
- **FIXED (internal)**: `models.py` metadata를 배포 DB에 정합화(마이그레이션 없음) —
  DB가 TEXT인데 모델이 String이던 27개 컬럼 Text화, `dagster_schedule_active_claims`의
  누락 컬럼 2개·CHECK 2개·`created_at` 기본값(now→clock_timestamp), `source_records`
  unique 제약명(→`uq_source_records`), `curated_themes.theme_slug` 제약명 명시,
  `import_jobs.queue_sequence`의 SERIAL 위양성 server_default 제거. 런타임 동작 불변
  (repo는 raw SQL 사용, DDL은 migration 소유).

### notice timestamp 방어적 cast (2026-07-19, report §2 D-9-7 (+ T-VN-06 row))

- **FIXED**: `detail->>'valid_end_time'`이 오염된 notice 한 행이 공개 read
  전체(bbox/search/nearby/in-area/cluster/counts/notice detail·batch)를 500으로
  만들지 않는다. 종료 필터가 `pg_input_is_valid`(PostgreSQL 16+) 가드로
  파싱 가능한 값만 cast한다.
- **CHANGED**: 파싱 불가한 `valid_end_time`을 가진 notice는 fail-closed로 공개
  표면에서 제외된다(이전: 500, 노출 아님). JSON null/키 부재는 기존 의미
  (종료시각 없음 = 활성)를 유지한다. typed notice 재설계·오염 관측은 T-VN-37.

### no-op beach 옵션 삭제 + auth-event actor principal 1차 (2026-07-19, ADR-066 D-2/D-9-6 T-VN-07)

- **REMOVED**: `/v1/public/beaches`·`/v1/public/beaches/{feature_id}`의 무동작
  `include_quality`·`include_forecast` query 옵션을 route 서명·OpenAPI(admin/user)·생성
  TS 타입에서 제거했다(D-9-6 — water quality/forecast 미구현, 구현 시점 재도입). 응답
  필드(`latest_water_quality`·`upcoming_index_forecasts`·`latest_weather`)는 모델
  기본값(null/[])으로 유지해 응답 계약은 불변이다. FastAPI가 미지 query 파라미터를
  무시하므로 옛 caller가 옵션을 보내도 정상 200(no 500).
- **FIXED**: 구현 사양 `docs/architecture/public-views-api.md`에서도 삭제된 두 query
  행을 제거했다. PinVi route·Python/TS client·vendored OpenAPI의 소비자 clean-cut은
  별도 PinVi 후속 PR에서 함께 반영한다.
- **SECURITY**: admin auth-event write(`POST /v1/admin/auth-events`)의 감사 actor를
  `body.actor or context.actor`에서 인증 principal(`context.actor`)만으로 좁혔다(ADR-066
  D-2, F-4). request body의 `actor`는 신뢰 경계 안에서 위조 가능했다. 본 slice는
  auth-event 한 경로만 다루며, admin feature/curated/issue/offline/dedup/enrichment
  write의 body-actor 전면 제거와 `actor` 필드 schema 제거는 T-VN-20 소관이라 여기서는
  필드를 유지·무시만 한다.

### route policy matrix + `/metrics` scrape identity 경계 (2026-07-19, ADR-066 T-VN-02)

- **ADDED**: `kortravelmap.api.route_policy` — 전 HTTP route와 WebSocket을
  `public-unauthenticated`/`public-keyed`/`service`/`operator`/`debug`/`metrics` 중 정확히
  하나로 분류하는 명시적 in-code registry(`ROUTE_POLICIES`)와 matrix 생성기. 분류는
  dependency 배선에서 추론하지 않고 registry가 정본이며, 미분류 route는 `create_app` 앱
  구성 검사와 CI(`test_route_policy.py`)가 함께 실패한다. FastAPI 0.136+의 lazy
  `_IncludedRouter`는 OpenAPI 생성기와 같은 공개 helper(`iter_route_contexts`)로
  평탄화한다(WebSocket은 OpenAPI paths에 없어 openapi() 열거로는 불충분). 정책-배선
  일치는 route별 관측 enforcing dependency로 검증하고, 다른 task 소유의 알려진 gap
  (무키 legacy `/v1/curated-*` → public-keyed, 무의존 `/v1/ops/{metrics,system-logs,
  api-call-logs,consistency/*,health-deep}` → operator — 모두 T-VN-03/codex b1 소유,
  PinVi cutover 조율)은 `KNOWN_WIRING_EXCEPTIONS` ledger에만 허용하며 gap이 닫히면
  stale entry가 CI에서 실패해 ledger 축소를 강제한다. ops-live WebSocket은 #725 HMAC
  ticket dependency를 enforcing 인증으로 기록만 하고 재사용한다(중복 구현 없음).
- **SECURITY**: `/metrics`가 scrape identity 경계를 얻었다 (ADR-066 결정 4).
  `KOR_TRAVEL_MAP_API_METRICS_TOKEN` 설정 시 `Authorization: Bearer <token>` 상수시간
  검증(불일치 401), production profile은 metrics endpoint 활성 시 이 token(앞뒤 공백
  없는 32자 이상, admin secret·service/ops token과 distinct)을 기동 필수로 요구한다.
  compose는 admin secret·service token과 같은 hard-require 패턴으로 host env를
  전달한다. **배포 전제(zero-gap 순서)**: kor-travel-docker-manager의
  `config/prometheus/prometheus.yml`에는 현재 map-api(:12701) scrape job이 아예
  없다(prometheus·cadvisor·kor-travel-geo만 존재) — 이 scrape는 신규 추가
  대상이다. (1) **먼저** docker-manager가 repository 밖의 secret 파일을 read-only
  mount하고 scrape config의 `authorization.credentials_file`로 읽도록 변경한 뒤
  map-api job을 추가하고(변경 전 무인증 API는 헤더를 무시하므로 무해), (2)
  **그다음** root `.env`에 같은 값의 metrics token을 넣고 API를 배포한다. 추적 중인
  Prometheus config의 inline `credentials`에는 실제 secret을 쓰지 않는다. 순서를
  뒤집으면 그 사이 scrape가 401 gap이 된다(조용한 파손이 아니라 scrape 실패로
  드러남). token 미설정 local-dev는 기존 open scrape 유지. 상세·YAML 예시는
  `docs/deploy.md`.
- **SECURITY**: metrics token 설정은 RFC 6750 `b64token` ASCII 문자만 허용한다.
  설정 단계에서 비ASCII/공백/구분자 문자를 거부해 Starlette의 latin-1 header decode와
  환경변수 UTF-8 인코딩 불일치로 올바른 token이 항상 401이 되는 구성을 막는다.
- **CHANGED** (ADR-066 D-1, T-VN-02): production profile은 인증 없는 interactive
  docs UI(`/docs`·`/redoc`·swagger oauth2-redirect)를 내린다(`docs_url`/`redoc_url`
  =None). D-1의 "public-unauthenticated=(liveness/version)"을 넓히지 않기 위함이며
  debug 라우터를 production에서 내리는 것과 같은 패턴이다. 기계 판독 공개 계약
  `/openapi.json`(ADR-031 served artifact)은 유지한다. 세 route 모두
  `include_in_schema=False`라 committed `openapi.json` `paths`는 불변(drift 없음).
- **CHANGED** (#742 consolidation): ops pair 검증 정본은 settings production matrix로
  일원화했다. `docker/api-entrypoint.sh`는 production profile + ops surface 활성 +
  ops pair 미구성(양쪽 빈 값 포함)을 migration **전에** settings와 동일 문구로
  거부해 2단계 혼란 실패를 없앴고(entrypoint의 profile 기본값은 Docker image와 같은
  production), settings의 pair provenance 메시지를 entrypoint와 lockstep으로
  정렬했다("must be configured together"). 메시지 lockstep은
  `test_docker_dagster_runtime.py`가 양쪽 소스를 대조해 상시 검증한다.

### 공개 predicate 단일화 — `feature.public_features` view (2026-07-19, ADR-067 T-VN-04)

- **ADDED**: migration 0059가 공개 정본 projection `feature.public_features`
  (`status='active' AND deleted_at IS NULL`) VIEW를 추가했다. bbox/cluster/search/nearby/
  in-area/detail/batch/category counts/notice/weather anchor/public views/curation·curated의
  모든 공개 read가 이 한 정의를 소비한다.
- **SECURITY**: admin-inactive/draft/broken feature가 일부 공개 경로(단건/batch/특보 이력/
  curation collection item)에 노출되고 provider-retired feature가 경로마다 다르게 은닉되던
  F-1 양방향 오분류를 해소했다. 무인증 collection 상세는 비공개·종료·구버전 notice에 연결된
  item을 SQL에서 행째 제외해 복제 저장된 `place_name`/`address_hint`/metadata 우회도 차단한다.
- **SECURITY**: `admin_only` theme와 candidate/rejected overlay가 공개 curated/curation 표면으로
  노출되던 경계를 닫았다. 공개 theme는 `visibility=public`, 공개 overlay는 `curated`만 허용하며
  feature 단건·batch에 결합되는 curation도 같은 theme visibility를 강제한다.
- **CHANGED**: `POST /v1/features/batch`는 모든 비공개 feature를 균일하게 `missing`으로
  분류한다(이전: admin-inactive는 `found`+`status='inactive'`). 5-state typed DTO 전환은
  T-VN-11 — 소비자 조정 노트는 `docs/integration-map.md` §3.2.
- **CHANGED**: `GET /v1/features/{id}/weather`·`/price`는 비공개/미존재 feature에서 404를
  반환한다(이전: 임의 id에 200 + 빈/합성 카드).
- **CHANGED**: `GET /v1/features/weather/alerts`는 anchor를 공개 projection에 LEFT JOIN한다 —
  alert row는 유지되고 비공개 anchor의 `feature_id`/`feature_name`은 null이다. 항상
  `'active'`로 상수화된 응답 필드 `feature_status`는 제거됐다.
- **REMOVED**: `GET /v1/categories`의 `active_only` 파라미터 — counts는 항상 공개
  projection 기준이다.
- **REMOVED**: 공개 `GET /v1/curated-themes`의 `visibility`와
  `GET /v1/curated-features`의 `curation_status` 파라미터 — 관리자 전용 상태를 요청으로
  다시 열 수 없고 각 공개 계약으로 고정된다.
- **CHANGED**: nearby `status` 파라미터는 공개 projection과 교집합으로만 동작한다는 설명이
  OpenAPI에 명시됐다(active 외 값은 빈 결과, 파라미터 정리는 T-VN-11/34).

### production profile fail-closed 기동 검증 (2026-07-19, ADR-066 T-VN-01)

- **SECURITY**: `KOR_TRAVEL_MAP_API_PROFILE=production`이면 `ApiSettings`가 기동 시점에
  fail-closed 검증을 수행한다. admin proxy secret(앞뒤 공백 없는 32자 이상) 누락, ops surface
  활성 상태의 read/cancel token 누락, public features surface의 `public_api_key_required=false`
  또는 service token 누락(앞뒤 공백 없는 32자 이상 필수 — `/v1/features/batch` service surface가
  public key 접근으로 조용히 격하되는 것을 막는다), 인증 없는 `/debug` 라우터 활성은 각각 기동
  거부 사유다. profile matrix 위반은 하나의 에러에 함께 나열되지만, 기존 ops token pair/shape
  검증(둘 중 하나만 설정 등)은 정의 순서상 먼저 단독으로 실패한다. secret 미설정 local-dev
  fallback(admin actor `local-dev` pass-through)은 non-production profile에서만 동작하고,
  production 상태에서는 dependency 수준에서도 403으로 닫힌다.
- **CHANGED**: API Docker image와 compose는 기본 production profile로 기동한다. compose는
  `/debug` 라우터 off와 `public_api_key_required=true`를 컨테이너 기본값으로 함께 주입하고
  (`environment`가 package `.env`보다 우선 — 단 legacy `/v1/curated-*` read는 T-VN-03 전까지
  keyless로 남는 F-3 잔여 gap), `KOR_TRAVEL_MAP_API_SERVICE_TOKEN`을 admin secret과 같은
  hard-require 패턴(`${...:?}`)으로 api 컨테이너에 전달한다. **배포 전제**: n150은 다음 배포에서
  root `.env`에 admin secret·ops token들과 서로 다른 32자 이상 service token을 추가해야 하며,
  없으면 compose 평가가 즉시 실패한다. 로컬 full-stack 검증은
  `KOR_TRAVEL_MAP_API_PROFILE=local-dev`를 host env로 명시해 기존 fallback을 유지하고,
  비-Docker 실행의 코드 기본값은 `local-dev`로 하위호환을 유지한다.

### #744 심층 리뷰 후속 수정 (2026-07-19)

- **FIXED**: resolver snapshot은 활성 `manual` link만 보존한다. target move/delete로
  비활성화된 `manual` row는 같은 `(target_id, feature_id)`가 다시 발견되면 resolver
  relation으로 재분류되며, 다음 빈 snapshot에서 정상 비활성화된다. 명시적 단건 upsert는
  caller가 지정한 relation을 그대로 적용한다.

### #733~#737 심층 리뷰 후속 수정 (2026-07-19)

- **FIXED**: POI cache target upsert의 moved/reject 판정을 active natural-key row
  `FOR UPDATE` lock 아래로 옮겼다. 동시 PUT(`on_conflict="reject"`)의 패자는 승자
  commit 뒤 `PoiCacheTargetConflict`로 거부되며, 승자의 좌표를 `ON CONFLICT UPDATE`로
  조용히 덮어쓰거나 이전 좌표의 active feature link를 남기지 않는다. create 경합의
  재-lock이 다시 비는 극단 3자 경합은 유한 create→재-lock 반복 뒤 명확한 오류로
  실패한다 — `DO UPDATE`는 lock 보유 없이는 실행되지 않는다. receipt와 trigger 소유
  `lock_version` 의미는 그대로다.
- **FIXED**: target-link snapshot sync가 활성 운영자 `relation='manual'` link를 더 이상
  비활성화하지 않는다(resolver link만 교체). snapshot upsert의
  `ON CONFLICT DO UPDATE`도 활성 manual→resolver 재분류를 차단한다. 단건 delete/move
  경로는 기존대로 전체 link를 비활성화한다.
- **CHANGED**: OpenAPI의 canonical ops service 대안 security를 `OpsToken`+`OpsScope`
  AND 결합으로 선언했다 — 런타임이 `X-Kor-Travel-Map-Ops-Scope` 누락을 422로
  거부하는 계약과 일치한다. `openapi.json` 재수출(경로/응답 변화 없음).
- **CHANGED**: C7 prod live runner의 causal POI spec 선택을 한글 제목 grep에서 안정
  `@c7-causal` tag grep으로 교체했다(fail-loud 유지). live Playwright config의
  `E2E_LIVE_WORKERS`는 1 이상 정수만 허용하고 빈 값/garbage는 값을 redact한 명확한
  오류로 실행을 막는다(기본 4).

### C7 prod live runner host Python 계약 (2026-07-18, T-ADM-C7)

- **FIXED**: n150 host가 제공하지 않는 `python` alias에 의존하지 않고 host-side fsync·lock·attestation·
  state 검증을 표준 `python3`로 실행한다. runner는 production state를 만들기 전에 `python3` 존재를
  명시적으로 확인하며, Dagster container 내부 Python 계약은 변경하지 않는다.

### POI target causal receipt·조건부 삭제 (2026-07-18, ADR-065 T-ADM-C7C)

- **ADDED**: Alembic 0058은 POI target에 server-owned BIGINT `lock_version`과 모든 UPDATE에서
  `OLD + 1`을 강제하는 trigger를 추가했다. POI target PUT/DELETE는 source transaction의
  `dataset_projection` revision receipt를 반환하고 GET/PUT/DELETE 성공 응답은 target UUID의
  versioned strong `ETag`를 반환한다. 단건·목록 body `entity_tag`도 header와 정확히 같다.
- **CHANGED**: DELETE는 body `entity_tag`의 `If-Match`를 필수화했다. 누락·형식 오류·UUID/version
  불일치·active target 부재를 각각 RFC7807 `428`·`422`·`412`·`404`로 구분하며, natural key와 UUID가 같은
  active 행을 잠근 뒤 UUID+version이 같은 경우에만 soft-delete한다.
- **FIXED**: admin BFF와 UI가 `If-Match`/`ETag`를 보존해 GET과 DELETE 사이 target이 재생성돼도
  새 UUID의 target을 지우지 않는다.
- **FIXED**: executor가 모든 active parent를 UUID 순서로 `FOR KEY SHARE` 잠근 뒤 link를 교체하고,
  target `FOR UPDATE` delete와 parent→link 순서로 직렬화해 교착과 삭제 뒤 link 재활성화를 막는다.
- **FIXED**: stale DELETE `412`는 list/nearby/dataset/pipeline projection을 모두 refetch한다. 선택
  상태는 target UUID로 최신 row를 파생해 새 opaque tag로 안전하게 재시도한다.

### canonical ops service principal (2026-07-18, ADR-064 T-ADM-C6c)

- **SECURITY**: PinVi server용 `OpsToken` principal을 read와 import-job cancel로 분리했다.
  read token은 canonical datasets/pipeline `GET`, cancel token은
  `POST /v1/ops/pipeline/executions/import_job/{id}/cancel` 한 곳에만 결박한다. scope 문자열만
  바꾸어 schedule/policy/update-request mutation 권한을 얻을 수 없으며 token·scope 오류는 typed
  RFC7807 `401/403/422`로 닫는다.
- **CHANGED**: service principal의 감사 actor는 설정 불가능한 코드 상수 `service:pinvi`를 사용한다.
  요청 actor header는 무시하며 기존 trusted admin frontend BFF와 `/v1/admin/*` 권한은 변경하지
  않는다. 제거된 actor env는 시작 시 거부한다.
- **SECURITY**: n150 production은 `KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=true`와 non-empty
  read/cancel pair를 강제한다. local opt-out은 두 값 모두 absent 또는 모두 explicit empty일 때만
  허용하고 partial/missing+empty/모든 whitespace/다른 trust-boundary secret 재사용을 거부한다.
  API-only ops env가 Dagster webserver/daemon에 유입되면 image entrypoint가 시작을 차단한다.

### exact-scope 조작·이력 UI 소비 (2026-07-18, ADR-064 T-ADM-C7B-UI)

- **CHANGED**: `/ops/pipeline`의 provider/dataset/scope filter를 URL controlled state로
  통일했다. 상위 축 변경과 불완전 tuple은 종속 filter와 cursor를 함께 제거하며 browser
  Back/Forward를 그대로 반영한다.
- **FIXED**: dataset-wide 갱신은 명시적 `sync_scope` 입력과 전송을 차단하고 서버 정규화에
  맡긴다. provider/dataset pair 변경 시 이전 scope를 재사용하지 않는다.
- **CHANGED**: exact tuple이 완성되기 전 dataset/scope filter와 조작을 비활성화하고, 서버가
  반환한 canonical history URL과 active operation link를 그대로 소비한다.

### exact-scope 실행·이벤트 projection (2026-07-18, ADR-064 T-ADM-C7B-API)

- **ADDED**: migration 0057에서 canonical update event의 owner
  `provider`/`dataset_key`/`sync_scope`를 typed 열·불변 trigger·check constraint로 고정하고,
  exact-scope 시간순 partial index를 추가했다.
- **CHANGED**: dataset 상세는 같은 scope의 `active_execution`과 최근 종료
  `latest_execution`을 독립 반환하며, 실행·이벤트 첫 페이지를
  `{items,next_cursor,canonical_url}`로 제공한다. cursor는 전체 filter fingerprint에 묶인다.
- **REMOVED**: provider namespace 밖에서 의미가 없는 dataset-only event 조회를 REST와
  repository에서 거부하고, 읽기 경로가 사라진 `idx_import_job_events_dataset_time`을 제거했다.

### 갱신 정책 revision CAS (2026-07-18, ADR-064 T-ADM-AUD-718)

- **ADDED**: `ops.provider_refresh_policies`에 단조 증가 BIGINT `revision`을 추가했다. 생성은
  `expected_revision=null`, 갱신은 현재 revision 일치가 필수이며 성공 시 원자적으로 1 증가한다.
- **CHANGED**: HTTP에서는 revision을 정규화된 10진 문자열로 전달하고, CAS 불일치는 현재
  record/revision을 포함한 typed RFC7807 `409`로 반환한다. `source_kind`는 생성 뒤
  불변이며 BIGINT 최댓값 갱신은 overflow 대신 typed 소진 `409`로 닫는다.
- **FIXED**: admin 정책 편집 중 background refetch나 다른 운영자의 저장이 발생해도 로컬 초안을
  덮어쓰지 않는다. 작성 기준과 최신 서버 revision을 분리하고 명시적 3-way 조정 후 다시 저장한다.
  조정 전 저장을 차단하고 탭 Back/Forward에도 초안을 유지하며 browser Back으로 drawer를
  닫으면 원래 행으로 focus를 복귀한다.

### KMA 빈 target fail-closed·exact event 증거 (2026-07-17, T-ADM-AUD-686)

- **FIXED**: KMA grid 3종은 target mapping·dedupe·cap 결과가 0건이면 provider client,
  feature/weather 적재, provider sync state를 건드리지 않고 canonical operation을 실패시킨다.
  terminal event `kma.target_scope_empty`는 같은 transaction에 한 번만 기록한다.
- **CHANGED**: 직접 실행과 정규 Dagster schedule 모두 credential 확인·provider import·public
  client 생성을 empty/cursor preflight 뒤로 지연한다. 소유 client close 실패는 먼저 발생한 typed
  failure나 cancellation을 덮지 않는다.
- **ADDED**: dataset 상세 event에 effective `sync_scope`, 다음 cursor, canonical history URL을
  추가하고 pipeline 전역 events에 exact scope filter를 제공한다. 0057 전에는 canonical
  job/request JOIN의 typed job scope에서 파생한다.
- **VERIFIED**: 두 적대 리뷰어의 S1/S2/S3 0건 승인 뒤 root unit 1,413건, API 485건,
  Dagster 475건(1 skip), 실제 PostGIS 집중 6건, frontend unit 185건과 전체 정적·OpenAPI·
  generated type·production build gate를 통과했다. #686은 후속 #726/#728/#729까지의
  수용조건과 CI를 재확인한 뒤 2026-07-18 닫았다.

### ops-live dataset projection·복구 경계 보강 (2026-07-17, ADR-064 T-ADM-C7A)

- **ADDED**: data integrity issue와 POI cache target 변경을 원본 transaction과 함께 증가시키는
  `dataset_projection` live revision/topic을 추가해 다른 tab/process 변경도 inactive dataset
  grid/detail에 반영한다.
- **FIXED**: malformed/비단조 frame을 받은 socket은 즉시 폐기하고 새 ticket/socket에서 exact
  `replace`를 다시 보내도록 했다. datasets의 인증 만료 badge는 `로그인 필요`로 구분한다.
- **SECURITY**: root `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET`가 앞뒤 공백 없이 32자 이상인지 local
  launcher와 API container entrypoint에서 기동 전에 검사한다.

### admin ops legacy REST clean-cut (2026-07-17, ADR-064 T-ADM-C6b)

- **REMOVED**: `/ops/dagster*`, `/ops/providers*`, `/ops/import-jobs*`,
  `/ops/import-job-events`, `/admin/provider-refresh-policies*`,
  `/admin/features/update-requests*`, `/debug/etl*`의 legacy operation 28개를 삭제했다.
- **CHANGED**: admin 실행·event·Dagster·schedule은 `/ops/pipeline/*`, dataset 상태·정책·
  fixture preview는 `/ops/datasets/*`만 사용한다. public provider read 2종은 운영 결합이
  없는 소형 router로 분리해 유지한다.
- **REMOVED**: raw HTTP live ETL loader, REST API 전용 provider credential settings·runtime
  주입, 사용되지 않는 Dagster NUX mutation/schema를 삭제했다. dataset preview는
  fixture-only이며 외부 호출 budget은 0이다.
- **CHANGED**: API container는 package-scoped `.env`만 읽고 root provider credential
  `.env`를 주입받지 않는다. 이 파일은 Compose 필수 입력이며 provider 비밀은 Dagster
  webserver/daemon 경계에만 둔다.
- **CHANGED**: 로컬 `admin:stack`도 process별 `env -i` allowlist를 사용한다. API/frontend는
  provider loader credential을 상속하지 않고 Dagster process만 이를 받는다.
- **CHANGED**: 구 API provider env 9종은 Docker/local 기동에서 fail-closed하고, MOIS
  freshness·file-registry TTL·offline upload prefix는 API와 Dagster가 같은 root 설정을 쓴다.
  Compose frontend도 login/session/BFF env만 명시적으로 전달한다.
- **CHANGED**: BFF 공유 secret은 root `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` 하나만 정본으로
  두고 API/frontend가 같은 이름을 직접 읽는다. API package env의 중복 secret과
  사용되지 않는 fixture provider/dataset 목록 helper도 제거했다.

### datasets 이슈 필터 의미 통일 (2026-07-17, T-ADM-C7B-720)

- **FIXED**: `/ops/datasets`의 `이슈 있음` 필터와 정렬이 dataset issue만 보던 경로를
  제거하고 dataset 또는 provider open issue가 있는 행을 모두 선택한다.
- **CHANGED**: 행 badge와 전체 이슈 요약도 같은 합계 의미를 사용하고, scope 반복 행은
  dataset/provider 귀속 단위로 한 번만 집계한다.

### admin ops UI clean-cut (2026-07-17, ADR-064 T-ADM-C6a/C6b)

- **CHANGED**: import job·갱신 요청·load batch·provider/dataset 딥링크와 홈·Feature·큐레이션·
  운영 로그의 작업 링크를 `/ops/pipeline`과 `/ops/datasets` 두 운영 화면으로 통합했다.
  provider 링크는 `dataset`과 `sync_scope` 선택을 보존한다.
- **CHANGED**: ops-live가 pipeline execution/event/overview와 dataset grid/detail query를
  직접 무효화하도록 바꿨다. import job 응답의 관련 링크와 Dagster run API도 canonical
  pipeline endpoint를 가리킨다.
- **TEST**: load batch·parent UUID deep link의 partial-index access path와 두 통합 화면의
  read/write·cross-surface 반영 시나리오를 회귀 계약으로 고정했다.
- **CHANGED**: 홈은 canonical pipeline root와 pipeline overview의 작업 수를 표시하고,
  운영 로그는 system/API 감사 로그만 소유한다. 작업 event·실행 이력·Dagster run·스케줄은
  `/ops/pipeline`, provider×dataset×scope 상태·정책·preview는 `/ops/datasets`가 소유한다.
- **REMOVED**: 구 `/ops/import-jobs*`, `/ops/providers`,
  `/admin/features/update-requests*`, `/admin/dagster`, `/etl` UI route와 전용 hook/mock E2E를
  redirect·호환 shim 없이 삭제하고 navigation을 두 canonical 운영 화면으로 정리했다.
- **TEST**: offline validation/load와 POI target upsert/delete가 canonical pipeline/datasets
  query를 무효화하는 hook 단위 계약을 추가했다.

### pipeline 운영 화면·조작 원장 통합 (2026-07-17, ADR-064 T-ADM-C5)

- **ADDED**: `/ops/pipeline`에 canonical 작업 상태, root 타임라인, Dagster run, 전역 event,
  schedule 상태·audit·claim 해소와 feature update 요청을 한 화면으로 통합했다.
- **ADDED**: feature update idempotency와 schedule command audit/active claim/resolution을
  append-only DB ledger로 저장하고 DB clock lease·advisory lock·hard timeout을 적용했다.
- **CHANGED**: request root와 projected job의 상태·진행률을 분리하고 provider/dataset pair,
  URL 상태, 1페이지 자동 갱신과 degraded 표시를 canonical pipeline 계약으로 통일했다.
- **FIXED**: 응답 유실·reload·동시 schedule command·mutation 이후 불확실 결과에서 새 identity로
  중복 실행되던 경로를 막고, frozen 제출을 복원해 동일 command/request로 재확인하도록 했다.

### datasets 운영 화면 통합 (2026-07-17, ADR-064 T-ADM-C4R/C4)

- **ADDED**: `/ops/datasets`에 provider×dataset×`sync_scope` 3원 상태 그리드와 상세
  drawer를 추가했다. 정책 편집, fixture ETL preview, 지금 갱신, scope별 실행 이력과
  Feature/issue 링크를 한 화면에서 확인·조작한다.
- **CHANGED**: dataset-wide 기본 state와 exact external scope의 이력을 분리하고, active
  operation 재사용·충돌·terminal 전이를 인라인으로 추적한다. canonical capability가 없거나
  stale/orphan인 scope의 변경·실행은 fail-closed한다.
- **FIXED**: URL 딥링크와 back/forward로 선택·탭을 복원하면서 query-only 전환이 화면 DOM을
  다시 만들지 않게 했다. 상세를 X/Escape로 닫으면 원래 행으로, 행이 사라졌으면 검색 입력으로
  초점이 복귀한다.

### direct update scope·dispatch 정본 (2026-07-16, ADR-064 T-ADM-C45X-B)

- **ADDED**: direct feature update job의 effective `sync_scope`와
  `dispatch_requested_at`을 typed DB 열로 승격했다. active identity는
  `(provider, dataset_key, sync_scope)`로 유일하며 같은 계획은 기존 request를
  `200` 재사용하고 다른 계획은 상세 링크가 있는 `409`로 거절한다.
- **CHANGED**: run-now는 새 request/job을 만들지 않고 기존 queued canonical
  job의 우선 dispatch를 멱등 요청한다. running은 같은 identity를 반환하고
  terminal/cancellation 상태는 거절한다. 목록·상세 UI도 빈 body/200/동일
  request cache 계약으로 전환했다.
- **CHANGED**: KMA grid는 `target_grids` 또는 exact
  `external_system:<name>` target만 조회하고 scope별 cursor와 target membership
  fingerprint를 유지한다. 격자 상한 초과는 provider I/O 전 전체 실패하며,
  실패 상태는 provider transaction rollback 후 별도 transaction에 영속한다.
- **CHANGED**: datasets latest projection을 `(provider, dataset_key, sync_scope)`로
  분리하고 provider state 기본 scope와 조작용 default scope 필드명을 분리했다.
  target scope에는 unscoped 실행을 연결하지 않고, 일반 dataset은 exact/unscoped 후보 중
  실제 최신 실행을 고른다. 의미를 증명할 카탈로그가 없는 orphan scope는 exact-only다.
  target selector의 기본/활성 external-system scope는 state가 없어도 grid/detail에
  `never_run` 행으로 노출한다.
  POI target 및 cache-target request `external_system`은
  trimmed non-empty 112자 이하를 OpenAPI·core·DB·repository에서 강제한다.
- **FIXED**: provider resource init/bind/run/teardown 실패를 typed failure로 통일하고,
  일반 asset은 성공과 같은 `default` state namespace, KMA grid만 선택된 effective
  scope에 실패 상태를 영속한다. non-direct 요청은 provider 또는 dataset filter를
  하나 이상 요구하며 admin UI도 빈 선택을 제출 전에 차단한다.

### Dagster provider guard·public wrapper tracking (2026-07-16, ADR-064 T-ADM-C3e-B2)

- **ADDED**: 모든 live provider resource가 authoritative Dagster run record의 job·asset selection·
  run config·canonical identity/version·trigger를 provider I/O 전에 exact match로 검증한다.
- **CHANGED**: public asset/KMA wrapper가 마지막 ensure와 자기 exact pair 완료를 소유하고,
  MCST는 pair-completion callback으로 부분 성공을 보존한다. direct raw runner는 tracking을
  생성하지 않는다.
- **FIXED**: 취소 marker·runtime identity drift·naive timestamp를 fail-closed하고, 비기본 KNPS
  point/geometry 설정이 provider fetcher와 asset resource에서 서로 달라질 수 있던 경로를 같은
  settings snapshot으로 통일했다.

### Dagster canonical operation run 추적 (2026-07-16, ADR-064 T-ADM-C3e-B3)

- **ADDED**: QUEUED부터 CANCELED까지 7개 run-status sensor와 NOT_STARTED/MANAGED·누락
  event를 복구하는 periodic sensor를 기본 RUNNING으로 등록했다. 모든 추적 경로는 provider
  resource 없이 canonical DB client만 사용한다.
- **CHANGED**: Dagster insertion cursor는 300초 settle lag를 만족하는 연속 ID prefix를 page
  commit 뒤 전진하며, DB active-root keyset은 마지막 page에서 첫 page로 순환한다. cursor anchor
  삭제·변조, 초기 무cursor, Dagster/DB 오류는 fail-closed한다.
- **FIXED**: terminal run의 trigger·selection 불변식 위반, pre-resource 실패, direct cancel,
  partial success가 active root/child를 남기지 않고 원자적으로 terminal 상태가 되도록 보강했다.

### Dagster canonical operation registry (2026-07-16, ADR-064 T-ADM-C3e-B1)

- **CHANGED**: 33개 feature-load job의 asset selection과 53개 provider/dataset 선택지를
  내용 기반 digest version의 immutable manifest로 고정했다. KNPS와 fileData admin Run-now는
  실제 resource config와 canonical manual identity를 Dagster launch에 영속한다.
- **CHANGED**: datasets schedule projection은 실제 `pipelineName`과 canonical identity가
  일치할 때만 MCST 13개 exact pair에 schedule 상태를 펼친다. 등록 job의 누락·교차 identity는
  fail-closed하고 비등록 임의 job만 panel-only로 남긴다.

### canonical root/exact-pair projection (2026-07-15, ADR-064 T-ADM-C3e-A2)

- **CHANGED**: pipeline timeline·detail·overview와 datasets grid/detail이 C3b lineage를
  공유한다. exact `provider_datasets[]`는 typed member의 상태와 member id를 노출하고,
  direct scope는 같은 linked member의 `sync_scope` metadata만 보강한다. import job의 typed provider/dataset pair가
  실행 identity의 유일한 정본이며 event의 같은 필드는 감사 메타데이터로만 남는다.
- **CHANGED**: 모든 feature update request는 canonical import job을 `NOT NULL/RESTRICT` FK로
  소유한다. migration은 writer table을 먼저 잠그고 기존 jobless·scope 불일치 request를 새 job으로
  재연결하되 active/cancellation connected branch는 중단한다. persisted dry-run을 금지하고
  `dry_run` DB 컬럼을 제거했다. DB CHECK/trigger는 OpenAPI와 같은 6종 scope의 exact canonical
  shape를 강제하고 provider/dataset 필터는 JSONB에서 typed `TEXT[]`로 전환해
  32/64개·trimmed non-empty 문자열 규칙을 적용한다. direct pair와
  `kind=feature_update_request` job 일치, non-direct unpaired shape, job kind/pair 불변성을
  강제한다. 기존 reserved Dagster job 연결도 canonical job으로 재연결한다. Python
  client/repository도 같은 validator를 preview와 enqueue 전에 사용한다.
- **CHANGED**: feature update request의 lifecycle·Dagster owner·취소 marker·오류·실행 시각은
  canonical import job 한 행만 소유한다. request는 immutable 입력/감사와 `matched_scope`, 양수
  `generation`만 보존하고, start/heartbeat/finish/requeue는 request+job row lock 아래 generation과
  trimmed non-empty Dagster run owner를 함께 CAS한다. queued job은 owner가 없어야 하고 running
  job은 owner가 반드시 있어야 한다.
- **CHANGED**: 연결 request가 없는 terminal feature-update job의 양방향 연결 component 전체에
  `quarantined_at`과 고정 사유를 기록한다. 원래 `kind`·`payload`는 보존하고 pipeline/legacy ops/live/
  Dagster engine read와 generic writer에서 제외한다. DB trigger는 runtime 격리 표식 생성·변경, 격리 행 UPDATE/DELETE/event
  추가와 새 child attach를 거부한다.
- **CHANGED**: 취소 대상 member identity를 `job_id` 하나로 통일했다. request ID는 root correlation에만
  남고, frozen member는 `(cancellation_id, job_id)` PK와 import job `RESTRICT` FK를 사용한다.
- **CHANGED**: 갱신 요청의 영속 생성은 201 endpoint, 비영속 실행 계획은 별도 200 `/preview`
  endpoint로 분리했다. `sigungu_by_radius.match`는 실제 kor-travel-geo 실행 의미가 있는
  `intersects`만 허용한다.
- **REMOVED**: admin UI의 구 `/admin/feature-update-requests` 목록·상세 redirect route를
  삭제했다. client 구현도 정본 `/admin/features/update-requests` route 아래에서만 소유한다.
- **CHANGED**: feature-load run의 `projected_job`은 root 자체로 고정하고 pair child 상태는
  exact pair에만 둔다. overview는 canonical root 기준 `operations_by_status`,
  `active_operations`, `failed_operations_24h`로 원자 전환했다.
- **CHANGED**: dataset별 최신 실행은 전체 canonical root에서 한 번에 계산하며, 상세 이력은
  pipeline과 같은 keyset cursor와 history URL을 제공한다. provider와 dataset 표시 배열을
  교차 조합하지 않는다.
- **ADDED**: 무필터·dataset-only·exact pair import job event 감사 조회에 각 시간순 index와
  고정-clause query shape를 추가했다. projection용 event identity index와 runtime event fallback은
  제거했다. direct scope JSON expression index도 typed job index로 통합했다.
- **ADDED**: import job event에 직접 격리 marker를 저장하고 visible event 전용 부분 index 여섯
  개를 사용한다. statement-level singleton event clock은 event DML·TRUNCATE commit마다 revision을
  한 번 증가시켜 late commit과 zero-job snapshot도 WebSocket invalidation에서 누락하지 않는다.

### canonical provider operation 영속화 (2026-07-15, ADR-064 T-ADM-C3e-A1)

- **ADDED**: Alembic 0051과 immutable Python API로 Dagster feature load를 run root
  `provider_feature_load_run` 한 건과 exact provider/dataset child
  `provider_feature_load`로 저장한다. typed identity, trigger, registry, raw Dagster
  status와 engine timestamp를 자유 payload와 분리했다.
- **CHANGED**: offline upload, MOIS, exact feature update가 provider/dataset identity를
  실컬럼으로 기록한다. generic import job writer는 canonical reserved kind·parent·target을
  fail-closed하고, canonical lifecycle은 멱등 ensure·단조 상태·terminal invariant로 닫힌다.
- **CHANGED**: 계층형 취소 응답에 frozen `operation_kind`와
  `requires_run_termination`을 추가했다. queued run-backed feature operation도 DB-only로
  취소하지 않고 같은 frozen member의 Dagster terminate·retry·authoritative terminal CAS를
  사용한다.
- **TEST**: 비-live 전체 1,762건, API 473건, Dagster 270건(1 skip), frontend unit
  82건과 Ruff, strict mypy 3패키지, import 계약 4/4, OpenAPI/admin type drift,
  frontend type/lint/build를 통과했다.

### admin ops pipeline Dagster run 상세 (2026-07-15, ADR-064 T-ADM-C3c)

- **ADDED**: `GET /v1/ops/pipeline/dagster-runs/{run_id}`를 추가했다. Dagster event
  cursor를 `after`로 전진 조회하며 `failure_reason`과 `failure_events`는 현재 event
  page 범위로 반환한다.
- **CHANGED**: 개별 run 상세는 성공만 200이다. run 없음은
  `404 DAGSTER_RUN_NOT_FOUND`, 연결·timeout은 `503 DAGSTER_UNAVAILABLE`, 설정·
  GraphQL·upstream HTTP·응답 해석 오류는 `502 DAGSTER_QUERY_FAILED` RFC7807
  problem으로 구분한다.
- **FIXED**: Dagster가 `Run` typename과 함께 빈/불일치 `runId`, 잘못된
  eventConnection pagination shape, 재사용할 수 없는 다음 cursor를 반환하면 정상
  run으로 오인하지 않는다. 신규 route는 502, legacy route는 200 envelope의
  `status=error`로 반환한다.
- **REMOVED**: iframe을 사용하지 않는 새 UI의 `/v1/ops/pipeline/nux-seen`을
  제거했다. legacy `/v1/ops/dagster/nux-seen`은 구 화면 제거 전까지 유지한다.

### admin ops pipeline root projection (2026-07-15, ADR-064 T-ADM-C3b)

- **CHANGED**: `GET /v1/ops/pipeline/executions`가 import job hierarchy를 canonical
  update request root와 standalone partition으로 접는다. request↔job 양방향 1:1과
  request job의 root shape를 DB가 강제하므로 각 job은 정확히 한 root에 귀속된다.
- **CHANGED**: feature update request의 lifecycle 정본을 `ops.import_jobs` 한 곳으로 통합했다.
  request 테이블의 중복 status/run/cancellation/error/time 컬럼을 제거하고 REST·queue·projection·
  cancellation은 unique job JOIN을 사용한다. 재시도 CAS는 timestamp 대신 양수 `generation`을 쓴다.
- **CHANGED**: 목록 item은 저장 순서·중복을 유지하면서 direct scope 누락값을 보완한
  `providers[]`/`dataset_keys[]`, provider/dataset/sync_scope pair를 보존하는
  `provider_dataset`,
  `linked_job_count`, `requested_job_id`, root와 상태를 분리한
  `projected_job`을 반환한다. standalone identity는 자유 payload가 아니라 해당
  미소유 partition의 import job event 실컬럼만 사용한다.
- **CHANGED**: 실행 목록 cursor를
  `(created_at DESC, id DESC, kind DESC)` v2로 교체하고 `dataset_key` filter를
  추가했다. 잘못된 cursor item kind와 UUID는 DB 조회 전 422로 거부한다.
- **TEST**: root unit 1,285건, API 전체 416건, 관련 PostGIS/EXPLAIN
  integration 10건, Ruff, strict mypy 155파일, import 계약 4/4,
  OpenAPI/admin types drift를 통과했다.

### admin ops datasets 계약 보강 (2026-07-15, ADR-064 T-ADM-C2R)

- **CHANGED**: `/v1/ops/datasets`가 provider 호출 가능 시각 `eligible_after`, Dagster
  definition tag와 RUNNING future tick 기반 `schedule.next_scheduled_at`, 명시적
  `stale_after_minutes` 기반 서버 계산 freshness를 서로 다른 필드와 의미로 반환한다.
  Dagster schedule 조회 실패는 DB 그리드 200을 유지하면서 `unknown`으로 degrade한다.
- **ADDED**: 그리드에 연결 request/import job 쌍을 root request 하나로 접은
  `latest_execution` batch projection(direct/parent-child/payload request 계보 포함),
  분리된 `dataset_issues`/`provider_issues`,
  `catalog_state`/`mutable`/`orphan_reason`을 추가했다. orphan 정책 변경은 409와
  `ORPHAN_MUTATION_DISABLED`/`details.mutation_disabled_reason`으로 거부한다.
- **CHANGED**: dataset preview는 `source=fixture`와 `max_items(1..100)`만 받는 typed
  계약으로 제한했다. 응답은 `total_items`/`returned_items`/`truncated`와 timeout,
  `external_call_budget=0`을 포함한다. ADR-044를 위반하던 raw live HTTP preview는
  신규 ops 제품 API에서 제거했다. 미지원·registry 불일치는 각각
  `PREVIEW_NOT_SUPPORTED`·`PREVIEW_REGISTRY_MISMATCH` problem code로 구분한다.
- **ADDED**: Alembic 0049로 `ops.provider_refresh_policies.stale_after_minutes` nullable
  양수 필드를 추가했다. NULL인 기존 정책은 다른 interval에서 SLA를 추론하지 않는다.
  신규/구 정책 PUT 모두 이 필드를 full-upsert에 전달하며 datasets grid의 정책 조회는
  기존 admin 목록 500건 limit과 분리해 전량을 반환한다.
- **CHANGED**: 800줄대 datasets router를 HTTP router, schema, application service,
  Dagster schedule projection, fixture preview 모듈로 분리했다.

### admin ops datasets 그룹 신설 (2026-07-14, ADR-064 T-ADM-C2)

- **ADDED**: `/v1/ops/datasets/*` 신규 REST 그룹(페이지 ② 백엔드) 4 endpoint —
  `GET /ops/datasets`(ETL 카탈로그 기반 provider×dataset×sync_scope 3원 그리드,
  `never_run` 포함 + sync state·refresh policy·미해결 integrity 이슈 카운트 join),
  `GET /ops/datasets/detail?provider=...&dataset_key=...`(scope 배열 상세 —
  cursor·최근 실행(update request+연결 import job 요약)·최근 이벤트·정책·이슈
  카운트), `PUT /ops/datasets/refresh-policy?provider=...&dataset_key=...`(2원 정책
  upsert — 카탈로그/잔존 sync state에 없는 조합은 404),
  `POST /ops/datasets/preview?provider=...&dataset_key=...`(ETL dry-run — 기존
  `/debug/etl` 로직 이식, 응답 식별자 필드는 `dataset_key`).
  `ops_routes_enabled` + `require_admin_frontend` 의존성의 자체 include 블록으로
  마운트한다(조작 포함 그룹 — 무인증 ops 패턴 미승계, ADR-064 결정 3).
- **ADDED**: `KOR_TRAVEL_MAP_API_ETL_LIVE_PREVIEW_ENABLED`(기본 off) — live ETL
  preview(실 provider 호출·쿼터 소모)는 이 opt-in flag 뒤에서만 열린다(403).
  fixture preview는 flag와 무관하게 상시 동작.
- **ADDED**: `kortravelmap.infra.dataset_status_repo` —
  `count_open_integrity_issues_by_dataset`(provider×dataset별 open/acknowledged
  이슈 집계) + `list_ops_import_jobs_by_ids`(타임스탬프 포함 import job 일괄
  조회). 구 라우터 삭제는 범위 아님(T-ADM-C6b) — 기존 `/ops/providers`·
  `/admin/provider-refresh-policies`·`/debug/etl`은 그대로 둔다.

### admin ops 통합 — backend `/ops/pipeline` 그룹 신설 (2026-07-14, ADR-064 T-ADM-C3)

- **ADDED**: `/v1/ops/pipeline/*` 12 endpoint를 신설했다 — overview(Dagster 요약+
  큐/failure sensor 상태+작업/요청 카운트), executions(**DB-only UNION** 실행
  타임라인: `ops.import_jobs` ∪ `ops.feature_update_requests`, 공유 keyset cursor
  `(created_at DESC, id DESC)` + kind discriminator, kind/상태/provider/기간 필터),
  `executions/{kind}/{id}`(+cancel), events(전역 job 이벤트 스트림), dagster-runs
  (보조 패널, `status=unavailable` graceful degrade), schedules(override 병합+sensor)
  + `PATCH`(**`cron_schedule: null` = override 삭제** — 구 default 명령 대체) +
  `commands`(`run|start|stop|reset` 4종 enum), requests(6-type scope union·카탈로그
  refreshable 검증·kor-travel-geo resolver·advisory lock 409/Retry-After·operator/
  reason 계약 전량 승계) + `run-now`(기존 canonical request 우선 dispatch,
  200), nux-seen. 신규 그룹은
  `ops_routes_enabled` + `require_admin_frontend` 게이트로 마운트한다(조작 포함 —
  무인증 ops 패턴 배제). UNION 조회는 `kortravelmap.infra.pipeline_repo`에 있다.
- **ADDED**: Alembic 0048 — `ops.import_jobs.dagster_run_id` TEXT 실컬럼 +
  기존 payload(`dagster_run_id`/레거시 `run_id` 키) 백필 + 부분 인덱스
  (`WHERE dagster_run_id IS NOT NULL`). jobs_repo의 INSERT/UPDATE 경로가 payload의
  run id를 실컬럼으로 승격한다.
- **CHANGED**: `/v1/ops/live`의 `dagster_runs`/`dagster_run:{id}` 스냅샷 SQL을
  실컬럼 `dagster_run_id` 우선 + payload COALESCE 폴백으로 전환했다(hot path
  2s poll — 전례 #639). 폴백은 mixed-version 배포 창(구 dagster 이미지가 0048
  백필 이후 payload-only row 기록) 정확성용이며, 배포 순서(api 먼저)와 백필
  재실행 SQL은 0048 docstring에 명기했다 — 순수 실컬럼 전환은 T-ADM-C6b 재검토.
- **FIXED**: 리뷰 반영 — executions/cancel/run-now의 id·cursor key·events job_id
  UUID 검증(비정형 입력 500→422), PATCH override 삭제·update request cancel의
  operator/reason 구조화 로그(감사 필드 유령 수용 해소), scope advisory
  lock 경합 `409`의 `Retry-After` 런타임 계약, datasets 그룹 `dataset_status_repo`에
  `dagster_run_id` 전파(최근 실행 요약 None 누락 방지).

### Concierge export 소비 계약 정렬 (2026-07-14)

- **CHANGED**: `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_FEATURE_SYNC_ENDPOINT` 기본값을
  `snapshot`에서 `changes`로 전환했다. producer(kor-travel-concierge)의 2026-07
  검수 개편(soft-delete 제거 목록·되돌리기·검수 회수·bulk 처리)으로 `reject`/
  `tombstone` 발행이 일상 흐름이 됐는데, `snapshot`은 active upsert만 반환해 철회가
  소비자에 영구 미전파된다. `changes`는 cursor 없이 시작하면 후보당 1행으로 압축된
  export ledger 전체를 재생해 full sync와 철회 전파를 동시에 만족한다.
- **ADDED**: concierge YouTube 수집 provenance(`youtube.source_type`/`source_value`/
  `source_title`/`source_search_query`/`corrected_search_query`)를 출처 UX 평면 키
  `detail.facility_info.youtube_source_*`로 노출한다(값 없으면 키 생략). nested
  `detail.payload.kor_travel_concierge.youtube` 경로는 기존대로 전체 pass-through.
- **VERIFIED**: 되돌리기(tombstone→inactive→재-upsert) 시 provider self-heal 복구가
  동일 payload fast-path·변경 payload 경로 모두에서 성립하고
  `prevent_provider_reactivation` override가 이를 차단함을 concierge 경로 통합
  테스트로 고정했다.
- **FIXED**: `changes` 재생 도중 producer 검수 전이(되돌리기)로 같은 후보가 구/신
  operation으로 한 스트림에 두 번 관측될 때, '적재 후 일괄 inactivate' 순서가 구
  reject/tombstone으로 신 upsert 상태를 덮던 문제를 후보별 **마지막 관측 item**
  압축(`kor_travel_concierge_latest_items`)으로 수정했다.
- **CHANGED**: producer T-189(2026-07-14)의 행정코드 실데이터
  (`place.address.legal_dong_code`/`sigungu_code` + 유도 `sido_code`)와 additive
  `schema_version`을 소비 계약 미러에 반영했다 — 기존 자리수 검증 경로로 Address에
  실리며 feature_id는 candidate.id 고정(ADR-057)이라 불변, 전 item payload_hash
  재발급으로 다음 materialize에서 전 후보가 재-render된다.

### Notice 계보 수명주기 원자화 (2026-07-14)

- **FIXED**: 대량 적재 뒤 `feature.features` planner 통계가 생성되지 않아 실제 약 102만 행을
  약 970행으로 오인하고 notice lifecycle UPDATE가 5분 이상 걸리던 문제를 수정했다. Alembic
  0047이 reconcile join table을 `ANALYZE`해 정상 join plan을 복원한다. 통계를 보존하지 않는
  `pg_restore` 뒤에도 staged analyze를 강제하고 swap 검증에서 통계 누락을 거부해 재발 경로를
  차단했다.
- **FIXED**: KREX reconcile이 약 1만 개의 동일 scope 계보마다 동일 scope 전체를 다시
  lateral 비교하던 제곱 비용을 제거했다. 동일 scope winner는 이미 만든 set 기반 rank를
  재사용하고, 추가 비교는 다른 provider/dataset 계보를 공유한 Feature에만 수행한다.
- **FIXED**: KREX snapshot에 없는 공지를 scope-local 메모리 집합만으로 닫아, 같은 Feature를
  공유하는 KMA·다른 dataset 공지가 살아 있어도 종료되거나 다음 실행에서 중복 재노출되던
  반복 문제를 영속 계보 상태와 전역 winner 판정으로 수정했다.
- **ADDED**: Alembic 0046에 notice scope watermark/fingerprint와 계보별 발표·해제 상태를
  저장하는 `provider_sync.notice_lifecycle_scopes` / `notice_lineage_states`를 추가했다.
  KMA 예정 종료(`valid_until`)도 발표 상태와 분리해 보존한다. 기존 상태를 알 수 없는 계보는
  열린 공지를 보존하며, 모든 winner가 명시적으로 사라진 마지막 시각에만 종료한다.
- **CHANGED**: KREX 전체 snapshot과 KMA rolling event는 bundle 적재, 계보 상태 전이,
  중복 정리, Feature 종료·재개를 전역 transaction lock 아래 한 transaction으로 반영한다.
  과거 snapshot/event와 같은 시각의 상반 상태는 거부하고 exact snapshot replay는 누락 상태를
  self-heal한다.
- **FIXED**: DB가 수락한 최신 KMA 발표와 일치하는 bundle만 적재해 늦은 과거 payload가 Feature
  본문/source current를 되돌리지 못하게 했다. 예정 종료와 실제 해제를 구분해 과거 특보의
  영구 재개방 및 실제 해제보다 오래 노출되는 문제도 막았다.

### Feature 지도 API JIT 지연 제거 (2026-07-13)

- **FIXED**: 고zoom Feature 지도의 병렬 bbox 조회에서 실제 SQL 실행보다
  PostgreSQL JIT 컴파일이 훨씬 길게 소요되던 문제를 수정했다. API OLTP
  연결에만 ``jit=off``를 적용하고 Dagster/CLI 배치 연결은 PostgreSQL
  기본값을 유지한다.
- **FIXED**: GeoJSON ``setData`` 직후 source tile 교체보다 먼저 marker 조회가
  실행되면 개별 Feature marker가 계속 0개로 남던 회귀를 ``idle`` 시점
  재동기화로 수정했다.

### 지도 신선도·provider 복구와 고zoom 응답성 보강 (2026-07-13)

- **FIXED**: KREX notice를 두 번 연속 조회한 완전 snapshot으로만 반영하고, snapshot에서
  사라진 공지는 종료 처리한다. strict pagination·중복 lineage 검증, 실행 직렬화와 watermark를
  함께 적용해 불완전 응답·역순 실행으로 인한 중복/재노출을 막는다.
- **FIXED**: 동일 원문으로 다시 나타난 provider Feature가 idempotency fast-path 때문에
  ``inactive`` 상태에 남던 문제를 수정했다. 사용자 요청·재활성화 방지 override는 보호하며,
  다중 primary notice 계보도 한 계보의 패배 때문에 다른 활성 계보까지 삭제·비표시하지 않는다.
- **FIXED**: OpiNet 실행의 raw/변환 결과 0건과 전일·혼합 가격을 성공으로 오인하지 않는다.
  요청 범위를 적용할 수 없는 targeted update는 전국 조회 전에 생략하고, provider schedule은
  실제 KST 당일 가격 전체 적재가 확인될 때만 같은 날 실행을 합친다.
- **CHANGED**: Feature 지도에서 AirKorea 대기질과 KMA 날씨를 서로 다른 marker 색상·glyph로
  표시한다. OpiNet 관측일이 오늘이 아니면 지도·목록에 `과거 M/D`를 표시하고, 가격 이력은
  단일·동시각 관측을 포함한 모든 유효 점을 그래프로 그린다.
- **CHANGED**: Feature 고zoom 조회는 viewport tile fan-out을 제한하고 더 적합한 tile zoom으로
  내려가며, marker는 현재 source/viewport만 렌더한다. 큐레이션 지도는 quantized padded bbox와
  이전 데이터 유지·viewport 필터를 사용해 cluster 해제와 pan 중 재조회/DOM 부하를 줄인다.
- **FIXED**: Dagster 고착 실행이 provider 갱신을 장기간 막지 않도록 run monitoring timeout,
  provider pool·DB advisory lock과 KREX schedule coalescing을 추가했다. KREX snapshot 경로에서는
  row별 reverse geocoding을 제거해 10분 주기보다 길던 실행 시간을 줄인다.

### 다중 관측·회차형 큐레이션과 등대 카테고리 (2026-07-13)

- **ADDED**: provider 자연 entity와 immutable payload version을 분리하는
  `provider_sync.source_entities`를 추가했다. Feature 단건/batch/admin 상세는 연결된 entity별
  현재 `observations[]`를 모두 반환하고, 과거 payload는
  `/v1/features/{feature_id}/observations/{source_entity_key}/history`에서 cursor 조회한다.
- **ADDED**: 테마·제목·회차·출처 묶음과 장소 membership을 분리한
  `feature.curation_collections` / `feature.curation_items` 및 `/v1/curations*`,
  `/v1/admin/curations*` API를 추가했다. 같은 Feature의 여러 연도·기관 큐레이션을 지도 marker
  하나의 상세와 REST 배열에서 모두 보여준다.
- **ADDED**: 관리자 큐레이션 수동 입력, UTF-8 CSV 양식 다운로드, dry-run preview와 collection
  단위 원자적 replace import를 추가했다. 삭제·연결 변경을 반영하고 변경 건수에 `removed`를
  포함한다. 기존 Feature를 안전하게 확정하지 못한 공식 항목도 nullable `feature_id`와 공식
  장소명으로 보존한다.
- **ADDED**: 한국관광 100선 2023~2024·2025~2026, 국가유산 방문 캠페인,
  2026 수목원·정원 스탬프투어, 등대 스탬프투어 공식 CSV와 검증 manifest를
  `resources/curations/`에 추가했다.
- **ADDED**: place category `01050400`(`TOURISM_NATURE_LIGHTHOUSE`,
  `관광 > 자연명소 > 등대`)과 지도 marker icon을 추가했다.
- **CHANGED**: `source_links`의 정체성을 payload record가 아닌 provider entity로 바꾸고,
  한 Feature에 서로 다른 primary source를 여러 개 허용한다. 신규 공식·수동 큐레이션은 기존
  평면 `curated_features` 대표 행이 아니라 collection/item 계약을 사용한다.
- **FIXED**: provider current는 `last_seen_at`을 우선해 `A → B → A` 재관측을 정확히 가리키고,
  기존 `curated_features` writer는 migration trigger로 새 collection/item에 즉시 동기화한다.

### Feature 지도 기본 weather/notice 필터와 초기화 버튼 복원 (2026-07-10)

- **CHANGED**: Feature 지도 kind 필터의 기본 선택을 `weather`, `notice`로 변경했다. 저zoom
  클러스터 요청(`/v1/features/in-bounds`)에도 기본/추가 선택 kind가 반복 `kind=` 파라미터로
  전달되는지 live e2e를 보강했다.
- **FIXED**: kind 선택이 기본 상태일 때 숨겨지던 `초기화` 버튼을 항상 렌더하고, 기본
  `weather`/`notice` 선택 상태로 되돌리는 동작으로 정리했다.

### 공개 Weather API와 3년 이력 보존 (2026-07-09)

- **ADDED**: 외부 시스템용 feature weather API
  `/v1/features/weather/forecast`, `/v1/features/{feature_id}/weather/forecast`,
  `/v1/features/weather/alerts`를 추가했다. 좌표/feature 기준 nearest weather anchor의 예보
  timeline과 KMA 기상특보 이력을 REST로 조회한다.
- **CHANGED**: `weather_values` 보존 정책을 30일에서 기본 3년으로 변경했다(ADR-062). 같은
  `valid_at`에 대한 과거 `issued_at` 예보를 보존해 3시간 전/1일 전 발표 예보와 현재 발표 예보를
  비교할 수 있다.
- **CHANGED**: Feature 지도 weather marker가 zoom 14 이상 개별 marker에서 현재기온뿐 아니라
  중기/단기 예보값(`TMN`/`TMX`/`POP`/`SKY` 등)도 라벨로 표시한다.

### 관리 파일 검색 provider/dataset 포함 (2026-07-09)

- **FIXED**: `/admin/files` 검색 입력이 안내하는 `경로 · provider · dataset` 범위와 맞게
  `/v1/admin/files?q=...` backend 검색을 `path`뿐 아니라 `provider`, `dataset_key`까지 확장했다.
  Claude Code 관리 UI 통합 PR #638 2차 사후 리뷰에서 발견한 불일치(#655) 후속.

### Feature 지도 저zoom 서버측 region 클러스터 (2026-07-09)

- **ADDED**: 관리 Feature 지도가 저zoom(≤13)에서 개별 feature를 tile로 대량 조회하지 않고
  기존 `/v1/features/in-bounds`의 **서버측 행정구역 rollup 클러스터**(zoom 유도: ≤7 sido /
  ≤10 sigungu / ≤13 읍면동)를 소비한다(#649, #12 잔여 인프라). 백엔드 클러스터링은 이미 완비돼
  있었고 프론트가 `zoom`을 안 보내 항상 개별 feature를 받던 것 → `useFeatureClustersInBbox`
  hook + `VWorldServerClusters`(count 버블, 클릭 시 다음 밴드로 확대) 추가. 저zoom 전국 뷰가
  1M feature fetch 없이 즉시 로드된다. 클러스터 모드에선 목록 테이블은 안내 문구, 상태 배지는
  "N개 지역 · M건 집계"로 표시. 고zoom(≥14) 개별 feature tiled 경로는 그대로. 군집 방식이
  maplibre 근접-군집 → 행정구역-군집으로 바뀐다(UX 변경).

### Feature 지도 pan 반응성 — 중복 outer refetch 제거 (2026-07-09)

- **CHANGED**: `useFeaturesInBbox` outer query key의 viewport 서명을 `.toFixed(4)`(~11m)에서
  `.toFixed(2)`(~1.1km)로 낮추고 zoom 성분을 제거. tile 최소 폭이 ~9.7km(zoom 12)라 sub-tile pan은
  이미 같은 tile 집합=같은 데이터인데도 과도하게 정밀한 서명이 pan마다 새 outer key를 만들어 tile
  cache가 전부 hit인데도 outer query를 재실행(재merge·재렌더)시켰다. 이제 tile 내부 작은 pan은 순수
  cache hit이 된다. outer `staleTime`도 tile fetchQuery와 같은 30s로 정렬(기존 5s → 조기 만료로
  불필요한 refetch). 순수 클라이언트 캐시 튜닝 — 데이터·계약 불변. 필터 적용·대형 pan의 잔여 지연은
  서버(휴게소 4코어 박스에서 밀집 bbox tile 조회) 병목으로 별도 인프라 과제(저zoom 서버측 region
  clustering). #12 클라이언트 개선분.

### concierge YouTube 그룹핑을 curated 테마 source로 (2026-07-08)

- **ADDED**: concierge YouTube 채널/재생목록 그룹핑을 curated 테마로 자동 동기화하는
  `sync_concierge_themes`(ADR-061). 이미 적재된 concierge 후보 feature의 detail youtube 값에서
  그룹핑을 유도해(별도 API 호출 없음), 그룹핑마다 public `media` 테마(slug `concierge-yt-<channel>`/
  `concierge-pl-<playlist>`) + detail_selector rule(auto-publish)을 upsert하고 후보를 즉시 채운다.
  멱등. on-demand 트리거: Dagster `concierge_theme_sync` asset(수동 materialize). #15 완결.

### 큐레이션 rule detail_selector — 단일 source를 detail 값으로 분할 (2026-07-08)

- **ADDED**: `feature.curated_source_rules`에 `detail_selector`(nullable jsonb) 추가(0042). rule이
  "feature.detail의 특정 path 값이 value와 일치하는 feature만"을 지정할 수 있게 해, 하나의 source를
  detail 값별로 여러 테마에 팬아웃한다. `_APPLY_RULE_SQL`에 `f.detail #>> path = value` 술어 추가.
  concierge youtube 후보를 channel/playlist 그룹핑별 테마로 자동 후보화하기 위한 근간(#15 PR1).
  apply 술어를 지원하는 concierge youtube channel_id/playlist_id 부분 표현식 인덱스도 추가.

### weather/price 마커 좌표 어긋남 수정 (2026-07-08)

- **FIXED**: Feature 지도에서 날씨·유가 마커가 좌표에서 왼쪽으로 어긋나 보이던 문제. 라벨이 붙은
  마커(`createFeatureMarkerElement`)를 `flex [아이콘][라벨]` wrapper로 만들어 maplibre 기본 center
  앵커가 wrapper 중앙(아이콘과 라벨 사이)을 좌표에 놓으면서 아이콘이 라벨 폭 절반만큼 어긋났다.
  라벨을 `absolute`로 아이콘 오른쪽에 띄우고 wrapper 박스를 아이콘 크기로 고정 → 아이콘 중심이
  좌표에 정확히 앵커링된다. 라벨 없는 마커는 원래 정상.

### 큐레이션 관리 title 멀티 필터 (2026-07-08)

- **ADDED**: 큐레이션 관리 검색 필터의 제목(display_title) 필터를 단일 select에서 **멀티 콤보박스**
  (`ComboboxMultiple`, 검색+배지 다중 선택)로 교체. 여러 제목을 동시에 선택해 필터링한다. 백엔드
  `/v1/admin/features/curated`에 `display_titles`(배열) 쿼리 파라미터 추가 → `cf.display_title =
  ANY(...)`. 기존 단일 `display_title`도 호환 유지.

### REST API feature_id dedup — 큐레이션 cross-theme + 검색 페이지 경계 (2026-07-08)

- **FIXED (curated)**: `/v1/admin/features/curated`에 `distinct_by_feature` 쿼리 파라미터 추가.
  같은 물리 feature가 여러 테마로 큐레이션되면((theme_id, feature_id) 부분 UNIQUE가 cross-theme
  중복 허용) 같은 `feature_id`가 테마 수만큼 반환됐다. `distinct_by_feature=true`(지도 경로)면
  `DISTINCT ON (feature_id)`로 rank_score 최고 큐레이션 1건만 반환한다(keyset 페이지네이션 유지).
  관리자 per-curation 목록(기본값)은 모든 큐레이션을 그대로 본다. 큐레이션 지도가 이 파라미터를
  사용 — 지도 중복을 클라이언트가 아니라 API에서 근본 제거(클라이언트 dedup은 방어선 유지).
- **FIXED (search)**: `/v1/features/search` score 커서가 `double precision`으로 캐스팅돼 float4
  `score`와 페이지 경계에서 정밀도 불일치 → 커서 행이 다음 페이지에 재등장(같은 feature_id 중복).
  커서를 `real`로 캐스팅해 경계값을 정확히 일치시켜 해결.
- 근거: 지도/feature 목록 REST 쿼리 6종 적대적 감사(bbox·geometry·cluster·by-ids는 fan-out 불가 확인).

### Feature/Curated 지도 렌더 입력 feature_id dedup 보강 (2026-07-08)

- **FIXED**: Feature 지도에서 같은 `feature_id` feature가 마커/도형으로 중복 렌더될 수 있던
  경로를 막았다. 공용 `VWorldFeatureClusters`가 렌더 입력(`features`)을 `feature_id`로 dedup
  (첫 항목 유지, 중복 없으면 원본 배열 그대로)해 point/geometry GeoJSON·마커 풀이 feature당
  1개만 그리도록 보강. tile 경계 중복·`keepPreviousData` 전환 등에서의 시각적 중복 방어선이며,
  Curated 지도(#7 상단)와도 공통 적용된다.

### 큐레이션 지도 물리 feature 중복 제거 (2026-07-07)

- **FIXED**: 큐레이션 지도에서 같은 물리 feature가 여러 큐레이션 엔트리(테마·소스 등)로 잡히면
  좌표가 같아 마커가 겹쳐 중복으로 보였다("고불개 해변" 사례). 지도 클러스터 입력을 물리
  `feature_id` 기준으로 dedup(가장 최근 큐레이션 엔트리 유지)해 feature당 마커 1개만 그린다.

### 파일 관리 목록 500 수정 — asyncpg 파라미터 타입 (2026-07-07)

- **FIXED**: `/v1/admin/files` 목록이 필터 없는 기본 뷰에서 항상 HTTP 500(파일 관리 페이지
  진입 불가). `list_managed_files`의 nullable scalar 필터(provider/location/registered_by/q/
  min_age_days/max_age_days)를 `CAST` 없이 `:x IS NULL OR col = :x`로 써서 asyncpg가
  `AmbiguousParameterError`(could not determine data type)를 던졌다. array 필터처럼 각 파라미터를
  `CAST(:x AS text|int)`로 감싸 해결. 실 PostGIS 통합 테스트(기본 뷰 + 각 필터 경로) 추가.

### 관리 feature 검색 fast-path — 완전한 feature_id는 PK 등가 (2026-07-06)

- **FIXED**: `/v1/admin/features?q=<완전한 feature_id>` 검색이 1M feature 대상 ILIKE 전체 스캔 +
  `source_records` 상관 서브쿼리로 14~60s 걸리던 것을, 검색어가 완전한 feature_id 형태
  (`f_{bjd}_{kind}_{sha1[:16]}`)면 PK 등가(`f.feature_id = :q_exact`)로 즉시 조회하도록 fast-path 추가.
  부분 검색어는 기존 ILIKE 경로를 그대로 유지한다. API 계약·응답 형태 변경 없음(속도만).

### 관리 UI 개편 C — 검증/어시스트·텍스트 절약 (2026-07-05)

- JSON·좌표·정책 입력 인라인 검증, `window.confirm`→AlertDialog(useConfirm) 일괄 전환,
  페이저를 공용 CursorPager로 통일. Dagster 스케줄 편집에 "다음 3회 실행" 미리보기·분 필드
  인라인 검증, 오프라인 업로드에 provider/dataset·CSV 컬럼 어시스트·미입력 사유 표시.
- 화면 설명문의 영어 전문용어·제목 반복을 간결한 한국어로 정리(7개 화면)하고 자명한 힌트 제거.
### 관리 UI 개편 D — 파일 레지스트리·추적 UI (2026-07-05)

- **ADDED**: 시스템에 적재되는 파일(Provider 다운로드·백업·오프라인 업로드·MOIS 원본)을
  추적하는 파일 레지스트리(`ops.managed_files` + `ops.managed_file_events`, 0040 마이그레이션).
  단순 리스팅이 아니라 각 파일이 어디에(location/backend) 어떻게 연결됐는지(provenance links),
  사용 중인지 임시인지(status/kind), 언제 받고 마지막으로 로드됐는지(downloaded_at/last_loaded_at)를
  본다. 생산/소비 지점 hook 계측(host op 실패 없이 best-effort) + 주기 스캔 reconcile.
- **ADDED**: `/v1/admin/files` 관리 라우터 — 목록(kind/status/provider/location/기간 필터),
  요약 집계, 상세(+provenance links·이력), 재스캔(backup_root 동기 + offline-uploads backfill),
  좁은 zombie purge(파괴적 스위치 게이트). Dagster `managed_file_scan` job(6시간 스케줄).
- **ADDED**: 관리 UI `/admin/files`(시스템 그룹) — 요약 칩(클릭=필터), 필터 바, 목록,
  상세 provenance 패널(연결 항목 딥링크·이력 타임라인·메타). 한국어 + HelpTip.

### 관리 UI 개편 B — nav 그룹·크로스링크 (2026-07-04)

- 사이드바를 작업 지향 4그룹(Feature 관리/수집 파이프라인/모니터링/시스템)으로 재편하고
  섹션 배지·브레드크럼을 nav 정본에서 유도.
- 화면 간 크로스링크/딥링크 전면 연결: 이슈↔feature, 소스↔Provider 상태, 작업↔로그/배치,
  홈 카드↔관리 화면, providers↔이슈/Feature 목록 등. `/ops/logs`·`/admin/issues`·
  `/admin/features`·change-requests가 URL 파라미터 진입 지원.
- H1/헤딩 정본화(Provider 상태·운영 로그·정합성 점검·큐레이션 지도·ETL 미리보기 등) 및
  e2e 스펙 정합화(stale 영문 헤딩 29파일 정정 + 신규 링크 스모크).
### notice 중복 근본 해결 — 사건 단위 identity + 라이프사이클 (2026-07-03, #632)

- **CHANGED**: KMA 특보 notice의 자연키를 발표 단위(`alert_id::region`)에서 **사건
  단위**(`{region_code}::{현상 토큰}`)로 재설계 — 재발표/등급 변경이 같은 feature로
  upsert되고 발표 이력은 source_records에 쌓인다.
- **ADDED**: 특보 **해제**는 feature를 만들지 않고 열린 notice의 `valid_end_time`을
  채운다(`weather_alert_lift_closures` + `close_notice_features`, 결합 해제문 fan-out).
- **FIXED**: KREX 교통 돌발 feature_id에서 reverse-geocoded `bjd_code` 제거 — 이동하는
  정체가 동 경계를 넘을 때 같은 사건이 중복 생성되던 버그.
- **ADDED**: 적재 직후 notice reconcile(`reconcile_notice_features`) — 계보 중복
  soft-delete + feed에서 사라진 사건 `valid_end_time` 종료. 지도/검색 read 경로는
  계보 latest만 + 종료 notice 숨김.
- **ADDED**: 만료 notice purge(§9, 종료/발표 +1년)를 maintenance job op로 구현.
- **MIGRATION**: `0040_notice_dedup_cleanup` — 구세대 identity로 쌓인 중복 notice
  일회성 soft-delete(원문 이력 보존).
### OpiNet price staleness 근본 수정 (2026-07-03)

- **FIXED**: `low_top_area` 가격 수집이 매일 같은 ~60개 시군(top-20)만 갱신해 price
  feature 37%가 3–7일 stale로 누적되던 문제 — run 날짜 기반 **시군 윈도 로테이션**으로
  전국(~230 시군)을 ≈4일 1주기로 순회한다(호출량 불변, ~198/1,500).
- **ADDED**: 수집 커버리지 운영 노브 `KOR_TRAVEL_MAP_OPINET_LOW_TOP_MAX_CALLS`(기본 180),
  `KOR_TRAVEL_MAP_OPINET_RUN_CALL_BUDGET`(기본 600).
- **CHANGED**: `KOR_TRAVEL_MAP_PRICE_STALE_HIDE_DAYS`(기본 4일)보다 오래된 price 관측은
  지도 마커 `price_summary`와 price card `current`에서 제외한다(이력 보존) — 로테이션
  주기 밖 옛 가격이 현재가로 표시되지 않는다.
- **CHANGED**: price card `is_stale` 기본 임계를 18h → 현재가 지평선(기본 4일)에서
  파생하도록 정합 — 로테이션 아래에서 정상 갱신 중인 주유소가 상세 패널에 항상
  stale로 표시되던 증상 해소. `is_stale`은 이제 `current`가 비는 조건과 일치한다
  (weather card 임계는 별도 상수, 영향 없음).

### 큐레이션 관리 UX 개편 (2026-07-03)

- **CHANGED**: 큐레이션 관리 화면을 '후보 검토'/'소스 규칙' 탭과 라이프사이클 스트립(상태 칩=필터,
  상태별 결과 설명)으로 재구성했다. nav 라벨은 '큐레이션 관리'/'큐레이션 지도'로 정리.
- **CHANGED**: 액션 동사를 채택/채택 해제/보관/결과 적용/규칙 적용으로 통일하고 상태 전환마다
  토스트로 결과를 설명한다(채택 토스트는 '큐레이션됨 보기' 필터 점프 제공).
- **CHANGED**: 후보 검색을 서버 `q` 검색(전 페이지, 300ms 디바운스)으로 교체하고 카운트 라인을
  'page N · 이 페이지 M개 · 페이지 크기 K'로 바꿨다.
- **ADDED**: editor dirty 가드 — 입력 중 다른 작업이 같은 항목을 수정하면 경고하고 '최신 값
  불러오기'로만 입력을 교체한다. 노출 순위 숫자 검증으로 잘못된 값 저장을 차단.
- **ADDED**: 장소 대조 검색 '결과 적용'의 재사용 정책 allowed 전환을 opt-out 체크박스로 노출.
- **CHANGED**: 소스 규칙 적용을 confirm+생성/갱신 건수 토스트로 바꾸고 규칙 편집 라벨을
  한국어(enumOption raw 병기)로 정리했다. bulk 채택/보관은 성공/실패 집계+실패 행 체크 유지.

### Notice/Curated Feature 지도 후속 수정 (2026-07-02)

- **FIXED**: KREX notice 중복 표시를 줄이기 위해 `series_no`를 notice 자연키/지도 최신값 lineage에서
  제외하고, 같은 사건의 최신 source record만 지도에 남기도록 보강했다.
- **CHANGED**: notice source에 발생 시간이 있으면 그 시간을 쓰고, 없거나 파싱할 수 없으면 최초
  probing 시각을 `valid_start_time`으로 표시한다. 이후 payload 변경 재수집 때도 최초 probing 시작
  시각은 보존한다.
- **FIXED**: Feature 지도 bbox/tile query key와 DOM marker 갱신을 더 민감하게 조정해 kind 변경,
  확대/축소, source data 변경 시 이전 marker가 오래 남는 현상을 줄였다.
- **ADDED**: `/curated-features` 운영 지도 화면을 추가했다. 필터는 POI명, 테마명, 제목,
  데이터소스이며 지도/테이블/상세에서 curated title이 아닌 실제 feature 정보를 주 표시로 보여준다.
- **CHANGED**: 기존 Feature 큐레이션 목록/상세/위치 검토에서도 `display_title`보다 실제
  `feature_name`을 주 표시로 사용한다.

### 큐레이션 feature theme/title 편집 (2026-07-02)

- **ADDED**: Feature 큐레이션 편집 패널에서 개별 curated feature의 theme와
  `display_title`을 함께 수정할 수 있게 했다.
- **CHANGED**: data.go.kr, MCST 등 정부·공공기관 source rule이 만드는 후보의 기본
  `display_title`은 provider 이름으로 채운다. concierge YouTube source는 API가 제공하는
  `youtube.source_title`을 우선 사용한다.
- **CHANGED**: source rule 재적용은 이미 지정된 `display_title`을 덮어쓰지 않고, 비어 있는
  경우에만 source별 기본 제목을 채운다.

### 큐레이션 테마와 Source rules 실행 연결 (2026-07-02)

- **ADDED**: 기본 큐레이션 theme set에 계절별 여행지 4종과 지역별 여행지 6종을 추가했다.
- **ADDED**: Feature 큐레이션 화면의 `Source rules` 패널에서 관련 Dagster schedule로 이동해
  `curated_features_refresh` job을 바로 실행할 수 있는 버튼을 추가했다.
- **CHANGED**: `kor-travel-concierge-youtube/youtube_place_candidates` seed rule과 import 경로를
  확장 테마 seed와 함께 통합 테스트에서 재확인한다.

### Feature 지도 notice 이력/겹침 메뉴 보강 (2026-07-02)

- **CHANGED**: Feature 지도에서 겹친 점 마커 선택 팝업의 헤더, 후보 행, 종류 배지, hover 상태를
  더 명확한 선택 메뉴 형태로 정리했다.
- **CHANGED**: KREX 교통공지 notice는 같은 사건의 문구/처리 상태 변경을 같은 Feature에 누적하고,
  source record 이력으로 보존한다. Feature 지도 bbox 조회는 같은 notice lineage에서 최신 값만
  표시한다.
- **ADDED**: `provider_sync.source_records.last_seen_at`을 추가해 동일 payload 재수집 시 원문/Feature
  본문은 갱신하지 않고 마지막 확인 시각만 갱신한다. Feature 상세 화면은 notice source 이력을
  별도 `Notice History` 섹션으로 표시한다.

### Feature 작성 폼 장소 종류 정리 (2026-07-01)

- **CHANGED**: 새 Feature 작성과 Feature 변경 요청 작성 화면에서 `장소 종류(place_kind)`를
  상세 정보가 아닌 기본 정보의 최상위 입력으로 표시한다. `Feature 종류`가 `place`일 때만 노출된다.
- **FIXED**: 기존 `area` 또는 `route` Feature를 변경 요청 작성 화면에 불러왔을 때 수동 수정 요청으로
  이어지지 않도록 경고를 표시하고 요청 생성을 막는다.

### Feature 지도/주소 입력 후속 보강 (2026-07-01)

- **FIXED**: Feature 지도에서 겹친 점 마커의 숫자 배지를 클릭했을 때 선택 팝업이 즉시 닫히지 않도록
  마커/클러스터 클릭 이벤트 전파와 팝업 닫힘 동작을 보정했다.
- **CHANGED**: 새 Feature 작성과 Feature 변경 요청의 시도/시군구/법정동/행정동 코드 입력을 같은
  자동검색 팝업으로 통일하고, 코드 길이 검증을 추가했다. 검색 결과는 해당 코드 계층 이름만 표시한다.
- **CHANGED**: 새 Feature 작성 화면의 좌표 지도는 오른쪽 보조 위젯 높이에 맞춰 더 길게 표시하고,
  역지오코딩/주소 후보 선택 시 주소 검색 필드와 선택 강조 상태를 함께 갱신한다.

### Feature 운영 경로 일원화 (2026-07-01)

- **CHANGED**: Feature 큐레이션, 중복 검토, 보강 검토, 갱신 요청 UI를
  `/admin/features/...` 하위 경로로 일원화했다. 기존 `/admin/curated-features`,
  `/admin/dedup-reviews`, `/admin/enrichment-reviews`, `/admin/feature-update-requests`
  화면은 새 경로로 redirect한다.
- **CHANGED**: 관련 admin API의 OpenAPI 정본도 `/v1/admin/features/...` 하위 경로로
  옮기고, 기존 API 경로는 호환 alias로만 남겼다.
- **CHANGED**: 중복 검토 목록/상세 UI를 보강 검토 화면 기준에 맞춰 컬럼 순서와 상세
  진입 버튼, 상세 비교 다이얼로그 구조를 정리했다.

### Feature 작성 폼 레이아웃 공용화 (2026-07-01)

- **CHANGED**: 새 Feature 작성 화면과 Feature 변경 요청 작성 화면의 기본 정보·좌표·주소·상세 입력
  섹션을 공용 컴포넌트로 정리했다. 변경 요청 작성 화면은 `변경 요청 작성` 바로 아래에 `기본 정보`를
  표시한다.
- **FIXED**: 변경 요청 작성 화면의 좌표 미입력 상태에서도 기본 지도 뷰를 표시하고, 좌표 지도 영역
  하단이 빈 안내 박스로 남지 않게 했다.

### Route/지도/OpiNet 회귀 수정 (2026-07-01)

- **FIXED**: KNPS route 적재에서 `비매칭코스`의 변형 표기와 매칭 실패 상태값도 제외하도록 보강했다.
- **FIXED**: Feature 지도에서 숫자 클러스터 마커가 더 이상 의미 있게 확대되지 않으면 겹친 feature 선택
  메뉴를 열도록 수정했다.
- **FIXED**: OpiNet `low_top_area` 유가 적재가 시군구를 서울부터 순차로 소비하다 호출 상한에 걸리지
  않도록 시도별 round-robin 순회로 바꿨다. OpiNet root area 응답에 라이브러리가 자식 조회를 허용하지
  않는 시도 코드가 섞여도 건너뛰도록 보강했다. Docker compose에도 OpiNet scope env 매핑을 명시했다.

### 운영 UI와 MOIS 적재 후속 보강 (2026-06-30)

- **FIXED**: MOIS bulk 적재와 feature update runner가 `mois_localdata_source_sync`를 먼저 실행한
  뒤 `mois_source_db_path`에서 license record를 읽도록 바꿔, MOIS provider 진행 시
  `ProviderCredentialMissing`이 service key 누락으로 잘못 보이던 문제를 수정했다.
- **CHANGED**: 고속도로 교통공지 notice schedule을 10분 주기로 조정했다.
- **CHANGED**: 중복 검토의 provider/dataset/category 필터와 보강 검토의 provider 필터를 다중
  combobox로 바꿨다.
- **ADDED**: 신규 Feature 작성 화면의 시군구 코드 입력에 자동검색 후보 목록을 추가했다.
- **FIXED**: Dagster 실행 시각 표시가 epoch 단위 차이로 비정상 날짜가 되는 문제를 보정하고,
  스케줄 실행 기록을 기본 닫힘 collapsible로 표시한다.
- **CHANGED**: 적재 작업 화면을 한국어 중심으로 정리하고, 작업 진행률/링크/오류/중지 위치와
  payload 표시를 운영자가 읽기 쉬운 형태로 보강했다.
- **FIXED**: 운영 로그의 live 상태 배지가 `live live`처럼 중복 표시되지 않게 했다.
- **FIXED**: Feature 지도 kind 필터의 `초기화`를 명확한 버튼 형태로 표시한다.

### 작업 자동화와 Feature 변경 검수 분리 (2026-06-30)

- **ADDED**: `/admin/dagster` 작업 자동화 화면에서 운영 스케줄 cron 수정, 기본값 복귀, 시작/중지,
  즉시 실행 명령을 수행할 수 있게 했다.
- **ADDED**: Dagster asset 한국어 표시명을 상수로 추가하고, UI에서는 한국어명을 우선 표시하며
  코드 레벨 이름은 보조 텍스트/말줄임/툴팁으로 노출한다.
- **CHANGED**: `Feature 변경` 작성 페이지와 `Feature 검수` 페이지를 분리했다. 검수 페이지는
  목록·필터·상세·승인/반려 흐름에 집중한다.
- **CHANGED**: Admin UI 모바일 메뉴는 선택된 메뉴가 중앙에 오도록 자동 스크롤한다.
- **FIXED**: Dagster code location reload가 지연돼도 스케줄 override 저장이 500으로 실패하지 않고,
  저장 결과와 reload 상태를 분리해 보여준다.

### Feature change requests 편집 UX 보강 (2026-06-29)

- **ADDED**: `/admin/features` 상세 패널에 `편집` 링크를 추가해 선택한 feature를
  `/admin/features/change-requests?action=update&feature_id=...`로 넘기고, change request
  form이 기존 feature 값을 prefill하도록 했다.
- **CHANGED**: Feature change request form의 `category`, `marker_icon`, `marker_color`를
  정의된 카탈로그 기반 dropdown으로 바꿨다. marker color dropdown은 색상 이름·코드·실제 색상을
  함께 보여준다.
- **ADDED**: `lon`/`lat`/`marker_icon`/`marker_color`/`sigungu_code`를 함께 편집하는
  위치/마커 다이얼로그를 추가했다. 지도 우클릭으로 좌표를 선택하면 reverse geocoder 결과의
  시군구 코드와 이름을 함께 표시한다.
- **ADDED**: `sigungu_code` 입력 시 숫자 코드 또는 한글 시군구명 기준으로 geocoder 후보를 즉시
  검색해 최대 10개까지 보여주고, 실제 코드와 일치하면 해당 시군구명을 표시한다.
- **ADDED**: Feature 상세 페이지의 `수정` 링크도 change request update form으로 연결하고,
  prefill 시 주소/행정코드/관계 id/좌표 정밀도/전화·행사·URL 필드를 JSON textarea 밖의
  개별 입력 필드로 채운다.
- **ADDED**: 위치/마커 다이얼로그에 모바일 오래누르기 좌표 선택과 `적용`/`취소` 버튼을 추가해
  데스크톱 우클릭과 모바일 조작을 같은 흐름으로 처리한다.
- **FIXED**: `kor-travel-geo` 조회를 Next.js same-origin `/api/geo/...` 프록시로 보내도록 바꿔
  admin UI의 시군구 검색/역지오코딩이 브라우저 CORS 설정에 흔들리지 않게 했다.
- **FIXED**: enrichment review와 dedup review 상세 다이얼로그의 지도 비교가 두 좌표를 모두
  볼 수 있도록 bounds 기준으로 중심과 축척을 맞춘다.
- **CHANGED**: Admin UI 사이드 메뉴명을 한글 중심으로 정리했다. Feature 계열은
  `Feature 지도`/`Feature 목록`/`Feature 변경`/`Feature 큐레이션`/`Feature 갱신`처럼
  연계되는 기능끼리 같은 접두어를 쓰고, 운영 메뉴는 `적재 작업`, `정합성 점검`, `운영 로그`,
  `백업`, `설정`처럼 직관적인 이름으로 표시한다.
- **DOCS**: Playwright UI/e2e 실행 위치를 WSL 금지, n150 우선, Windows 호스트 브라우저 fallback으로
  명시했다.

### Enrichment review detail 진입 명시화 (2026-06-29)

- **ADDED**: `/admin/enrichment-reviews` 목록 actions 컬럼에 `detail` 버튼을 추가해 상세 비교
  다이얼로그와 VWorld 위치 비교 지도로 진입하는 동선을 명시했다.

### n150 live e2e 실패 보강 (2026-06-29)

- **FIXED**: enrichment review 목록/상세 조회에서 아주 먼 후보 거리의 공간 점수 계산이 numeric
  underflow로 500을 내지 않도록 35km 이상 거리는 `spatial_score=0`으로 clamp한다.
- **FIXED**: admin backup/restore/swap command 시작 시 실행 경로나 command가 없으면 내부 500 대신
  `503 BACKUP_COMMAND_UNAVAILABLE` 문제 응답으로 실패 원인을 노출한다.

### Enrichment review 지도 비교 surface 일원화 (2026-06-29)

- **CHANGED**: enrichment review 목록의 행별 인라인 `지도` 버튼과 별도 지도 panel을 제거하고,
  행 클릭 상세 다이얼로그의 VWorld 위치 비교 지도로 surface를 일원화했다.

### Review 목록 page-only 계약 정리 (2026-06-29)

- **CHANGED**: `GET /v1/admin/dedup-reviews`와
  `GET /v1/admin/enrichment-reviews`에서 사용되지 않던 `cursor` query parameter를 제거하고,
  `page`/`page_size`/`meta.page.total` 기반 계약으로 일원화했다.
- **FIXED**: review 목록 repository와 admin UI에 남아 있던 죽은 `next_cursor` 분기를 제거해
  page 번호 이동과 API 계약이 같은 모델을 사용하도록 맞췄다.

### Agent 개발 환경 문서 정합성 보정 (2026-06-29)

- **FIXED**: `docs/agent-guide.md`, `CLAUDE.md`, `docs/debug-ui-admin-workflows.md`에 남아 있던
  Windows Git/Windows Playwright 표준 문구를 Linux/WSL git 단일 실행과 n150 Linux-first
  Playwright 정책으로 정리했다.

### data.go.kr curated fileData 월간 schedule 보강 (2026-06-29)

- **FIXED**: `DATAGOKR_FILEDATA_DATASETS` 4종 중 기본 dataset 1개만 월간 schedule로 적재되던
  문제를 수정했다. 이제 dataset별 schedule 4개가 같은 `feature_place_datagokr_file_data` asset에
  각 dataset_key resource config를 주입해 모두 월 1회 실행한다.
- **CHANGED**: `datagokr_file_data_records`와 `datagokr_file_data_dataset_key` Dagster resource는
  schedule `run_config`의 `dataset_key`를 우선 사용하고, config가 없을 때만 settings 기본값을 쓴다.

### Enrichment detail source audit 계약 명시 (2026-06-29)

- **FIXED**: enrichment 상세 비교 다이얼로그의 `정리된 datagokr`/`visitkorea` 선택이 실제
  enrichment 적용 데이터를 바꾸는 것처럼 보이던 foot-gun을 제거했다. UI는 이 선택을 기록용으로
  표시하고, API 응답은 `detail_source_effect: "audit_only"`를 내려준다.
- **CHANGED**: `PATCH /v1/admin/enrichment-reviews/{review_id}` 응답에
  `selected_detail_source`와 `detail_source_effect`를 추가해 선택값이 decision reason audit marker로만
  쓰인다는 계약을 OpenAPI에 명시했다.

### Dedup review count 성능 보강 (2026-06-29)

- **FIXED**: dedup review 목록 count가 provider/dataset/kind/category/q 필터가 없을 때
  feature/source join을 materialize하지 않고 `ops.dedup_review_queue`에서 status/score 조건만으로
  집계하도록 했다.
- **ADDED**: dedup review fast count SQL의 EXPLAIN 테스트를 추가해 `idx_dedup_status_score` 사용과
  queue table 단독 계획을 고정했다.

### Admin backup delete 계약과 live e2e 안전 게이트 (2026-06-29)

- **ADDED**: `DELETE /v1/admin/backups/{backup_id}`를 추가해 backup artifact 디렉터리를
  삭제할 수 있게 했다. 이 엔드포인트는 `admin_destructive_enabled` kill-switch를 따른다.
- **CHANGED**: admin live e2e의 실제 write spec은 기본 full run에서 실행하지 않고,
  `E2E_ADMIN_FEATURES_WRITE=1`, `E2E_SETTINGS_WRITE=1` 또는 `E2E_ADMIN_WRITE=1` opt-in이
  있을 때만 실행한다.
- **CHANGED**: admin live scenario catalog의 큰 count는 실행 커버리지가 아니라 surface taxonomy로
  문서화하고, destructive risk는 HTTP method/path/risk metadata로 분류한다.

### Refreshable provider catalog와 MOIS detail runner (2026-06-28)

- **CHANGED**: `/ops/providers` never-run 목록이 새 Feature 생성 여부(`is_feature_load`)가 아니라
  Dagster feature update request 실행 가능 여부(`is_refreshable`) 기준으로 표시된다.
- **ADDED**: MOIS `mois_license_detail` feature update runner dispatch를 추가했다. 상세 API는
  detail source record를 우선 조회하고 없으면 기존 bulk source record로 fallback한다.
- **CHANGED**: OpiNet 가격, KREX 가격/기상, KMA 예보/실황, VisitKorea 축제 보강처럼
  `is_feature_load=False`이지만 runner가 있는 dataset도 운영 실행 목록에 표시된다.
- **UNCHANGED**: 전화번호 보강(`place_phone_enrichment`)은 운영 runner 대상에 추가하지 않는다.

### Feature update provider/Dagster 정렬 (2026-06-28)

- **FIXED**: AirKorea feature update 대상이 standalone `airkorea_stations`로 노출되어 Dagster runner에서
  unsupported provider/dataset으로 실패하던 문제를 수정했다. UI/catalog는 `airkorea_air_quality`를
  feature-load 대상으로 노출하고, 기존 station 요청은 같은 asset alias로 실행한다.
- **FIXED**: OpiNet feature update에서 API key 누락 시 provider client 내부 인증 오류 대신
  `KOR_TRAVEL_MAP_OPINET_API_KEY` 누락 메시지로 실패하도록 했다.
- **ADDED**: MOIS history/closed, 전국지역특화거리표준데이터, data.go.kr curated fileData 4종의
  feature update runner dispatch와 Dagster asset/resource/schedule 연결을 추가했다.

### Review 상세 비교 다이얼로그 (2026-06-28)

- **ADDED**: Dedup review와 Enrichment review 행을 클릭하면 두 자료의 feature/source 상세,
  raw/detail JSON, 거리/score, 기간을 비교하는 다이얼로그를 표시한다.
- **ADDED**: 두 review 상세 다이얼로그는 하나의 VWorld 지도에 양쪽 좌표와 이름 marker를 함께 표시한다.
- **ADDED**: 축제 enrichment 상세에서 관리자가 decision reason에 기록할 `정리된 datagokr` 또는
  `visitkorea` source를 선택할 수 있고, 정리된 target detail이 없으면 VisitKorea가 기본 선택된다.
- **CHANGED**: enrichment accept 요청은 선택된 상세 source를 decision reason에 함께 기록한다. 이 선택은
  실제 enrichment source link 적용 데이터는 바꾸지 않는다.

### Feature update request queue 실행 복구 (2026-06-28)

- **FIXED**: Dagster `feature_update_request_worker`가 기본 `feature_update_runner` 리소스를
  받지 못해 update request가 계속 queue에 머물던 문제를 수정했다. worker는 이제 queued/run-now
  요청을 provider/dataset별 기존 feature load asset 실행으로 dispatch한다.

### Enrichment/Dedup review 검수 UX 보강 (2026-06-27)

- **ADDED**: enrichment review 테이블에 검색, provider/status/score band/page size 필터와 cursor
  pagination을 추가했다.
- **ADDED**: dedup review 테이블에 검색, status/kind/provider/dataset/category/score band/page size
  필터와 cursor pagination을 추가했다.
- **ADDED**: enrichment/dedup review 테이블의 상단과 하단에 첫/이전/다음/마지막 페이지 버튼,
  현재 페이지, 총 페이지, 총 아이템 수, 현재 페이지 아이템 수를 표시한다.
- **CHANGED**: enrichment/dedup review 목록 API는 page 번호 조회와 전체 count(`meta.page.total`)를
  제공한다. 기존 cursor 응답은 호환용으로 유지한다.
- **ADDED**: enrichment review 목록 응답과 UI에 datagokr 대상 feature와 visitkorea source의
  좌표·기간, 두 좌표 사이 거리(`distance_m`), 거리 기반 유사도(`spatial_score`)를 표시한다.
- **ADDED**: enrichment review 행에서 지도 버튼을 누르면 하나의 VWorld 지도에 datagokr와
  visitkorea 좌표를 각 source 이름 marker로 함께 표시한다.
- **CHANGED**: VisitKorea enrichment source record가 TourAPI 좌표를 보존해 review 거리/지도 표시가
  source payload만으로 가능하게 했다.

### Curated place-search 반영 정책 수정 (2026-06-27)

- **FIXED**: admin curated feature에서 장소 검색 결과를 `반영`하면 `reuse_policy`가
  `allowed`로 함께 저장되어 REUSE 컬럼과 편집 패널이 즉시 갱신되도록 했다.

### Feature update request UI live e2e 보강 (2026-06-27)

- **CHANGED**: feature update request create/run-now 및 ops-live update request 이벤트가 feature 지도,
  feature 상세, admin features 목록 query를 invalidate해 갱신 결과가 지도 화면에도 반영되도록 했다.
- **ADDED**: admin feature update request live e2e에 실제 API dry-run preview, validation error,
  `/features` 지도 화면의 `Update` 진입 링크 확인을 추가했다.
- **ADDED**: mocked update request e2e에 form validation과 API 422 에러 alert 케이스를 추가했다.

### Admin curated/features 후속 보강 (2026-06-27)

- **ADDED**: admin curated feature 단건 상세 화면을 추가했다. 목록 우측 검토 패널과 같은 위치 지도,
  place 검색, display 편집, detail snapshot preview를 전용 상세 화면에서 사용할 수 있다.
- **ADDED**: admin features 목록 우측 preview와 `/features/{feature_id}` 상세 화면에 지도 패널을
  추가했다.
- **CHANGED**: admin features 목록의 `detail` 버튼은 상세 route로 바로 이동하고, 기존 `전체 상세`
  버튼은 제거했다.
- **CHANGED**: curated place 검색은 후보 선택만으로 자동 실행하지 않고, 검색 버튼을 눌렀을 때만
  호출한다. 후보를 바꾸면 검색어/결과 패널이 새 후보 기준으로 초기화된다.
- **CHANGED**: curated place 검색 backend는 kor-travel-concierge를 거치지 않고 Kakao Local,
  NAVER Search, Google Places API를 직접 호출한다. 주소/POI 검색용 env는
  `KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY`,
  `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID`,
  `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_SECRET`,
  `KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY`다.
- **CHANGED**: curated UI의 `concierge` 표시명은 중립 표시명으로 바꿨고, 해당 provider 선택 시
  하드코딩된 theme이 아니라 source rule의 실제 theme을 선택한다.
- **FIXED**: OpiNet `low_top_area`가 일부 지역/제품 no-data 예외로 중단되지 않게 하고, bounded
  호출 뒤 sample-grid fallback으로 보강한다.
- **FIXED**: Dagster feature load schedule에 krforest/standard/khoa/krairport/airkorea/visitkorea
  asset schedule을 추가하고, admin Dagster 화면이 asset group의 뒤쪽 asset을 숨기지 않게 했다.

### Feature별 상세 패널 + Dagster 운영 표시 보강 (2026-06-26)

- **ADDED**: feature 상세 패널을 kind별로 분기했다. `weather`는 날씨 정보와 최근 업데이트,
  `price`는 최신 가격/이력 표/그래프, `event`는 기간·장소·연락처, `area`는 면적과 포함 feature,
  `route`는 구간 메타를 표시한다.
- **ADDED**: `/v1/features/{feature_id}/contained-features` API를 추가해 area polygon 안의 point
  feature 목록을 조회할 수 있게 했다.
- **CHANGED**: admin 지도 weather marker가 현재기온 요약을 표시하고, weather marker icon을
  기존 marker metadata대로 렌더한다.
- **CHANGED**: 로그인 후 사용하는 admin 좌측 메뉴를 `/features` 지도 화면에도 노출하고, 데스크톱에서
  접고 펼칠 수 있게 했다.
- **CHANGED**: feature load Dagster schedule을 weather 시간당 1회, 유가 일 2회, 나머지 월 1회로
  정리했다.
- **ADDED**: Dagster run 상세에 실패 원인 요약과 stack 표시를 추가했다.

### OpiNet 전국 저가 유가 scope 추가 (2026-06-26)

- **ADDED**: OpiNet `OPINET_SCOPE_MODE=low_top_area`를 추가했다. 전국 bbox 격자 수집은
  일일 한도 초과 위험이 있어, 시군구별 `lowTop10` 저가 목록으로 전국 price feature 분포를 만든다.
- **ADDED**: `lowTop10` 단일 제품 가격 row를 `kind=price` feature와 `PriceValue`로 적재하는
  변환 경로를 추가했다.
- **FIXED**: 운영 OpiNet `areaCode`/`lowTop10`이 빈 응답을 반환하는 경우 전국 샘플 그리드의
  `aroundAll`로 fallback해 `low_top_area`가 0건으로 끝나지 않게 했다.
- **FIXED**: OpiNet fallback 샘플이 5km 반경 대비 성겨 전국 도심을 놓칠 수 있어, 주요 도심
  anchor를 먼저 조회한 뒤 기존 grid를 보조로 사용하게 했다.
- **FIXED**: N150 운영에서 제주/완도 bbox로 고정되어 유가가 해당 권역에만 보이던 원인을 문서화했다.

### Admin price UI + Dagster 주기 정리 (2026-06-26)

- **ADDED**: `/v1/features/{feature_id}/price` API를 추가해 price feature의 제품별 최신 가격과
  최근 가격 이력을 조회할 수 있게 했다.
- **ADDED**: admin Feature 지도에서 price marker가 휘발유/경유/고급휘발유 최신 가격을 표시하고,
  price feature 선택 시 우측 패널에 가격 요약과 history를 표시한다.
- **CHANGED**: OpiNet/KREX price Feature Dagster schedule은 일 2회로 낮추고, KMA/KREX weather
  관련 Dagster schedule은 시간당 1회 기준으로 정렬했다.

### 가격 시계열 테이블 + OpiNet/KREX 유가 적재 (2026-06-25)

- **ADDED**: `feature.feature_price_values` 테이블과 가격값 upsert repository/client를 추가했다.
  price feature 삭제 시 가격값은 cascade되고, provider raw 추적은 `source_record_key`로 연결된다.
- **ADDED**: OpiNet 주유소 상세 가격과 KREX 휴게소 유가를 `kind=price` feature +
  `PriceValue`로 적재하는 Dagster asset/job/schedule을 추가했다.
- **CHANGED**: 가격 시계열 설계 문서를 기존 `price_points`/`price_values` 초안에서
  `kind=price` anchor feature + `feature_price_values` 정본으로 갱신했다.
- **FIXED**: main의 curated 계약 migration과 N150에 먼저 적용된 가격 시계열 migration이
  같은 parent에서 갈라진 Alembic graph를 no-op merge revision으로 정리했다.

### Curated API 범용 계약 정리 (2026-06-25)

- **CHANGED**: public curated API는 임의 외부 사용자가 curated feature 목록과 상세를 조회하는
  범용 계약으로 정리했다. 공개 surface는 `/v1/curated-features`,
  `/v1/curated-features/{curated_feature_id}`만 유지한다.
- **CHANGED**: curated 상세 재사용 관련 DB/API 명칭을 제품 전용 용어가 아닌
  `curation_relation`/`reuse_policy`/`content_version`과
  `feature.curated_feature_detail_snapshots`로 정리했다. 상세 snapshot preview는 admin API
  `/v1/admin/curated-features/{curated_feature_id}/detail-snapshot`에서만 제공한다.
- **CHANGED**: POI cache target metadata의 외부 POI 식별자는 `external_poi_id`로만 받도록
  OpenAPI와 저장 metadata를 정리했다.

### KNPS 비매칭 탐방코스 route 제외 (2026-06-25)

- **FIXED**: KNPS `knps_trails`의 `비매칭코스`/`Nonmatching Course` placeholder를
  공식 route feature로 적재하지 않도록 제외했다.
- **CHANGED**: N150 운영 DB에서 기존 active `비매칭코스` route 1건을 삭제 처리하고,
  OpiNet 주유소 place feature를 재적재했다.
- **CHANGED**: N150 운영 `kor-travel-docker-manager`의 OpiNet env key와 map DB/role명을
  `KOR_TRAVEL_MAP_*`, `kor_travel_map`, `kor_travel_map_dagster` 기준으로 정리했다.

### Concierge curated source + curated 계약 보강 (2026-06-25)

- **ADDED**: `kor-travel-concierge-youtube/youtube_place_candidates`를 `media-places`
  curated source/rule에 추가했다. source rule 적용 시 기본 `curated` 상태로 선정하고,
  `display_title`은 YouTube source title → playlist title → channel title → 보정/검색어 순서로 채운다.
- **CHANGED**: curated 재사용 계약은 특정 제품명이 아니라
  `curation_relation`/`reuse_policy`/`content_version`과 detail snapshot 기준으로 표현한다.
- **CHANGED**: POI cache target metadata의 외부 POI 식별자는 `external_poi_id`로 표현한다.

### KNPS protected area 한글명 일괄 보정 (2026-06-25)

- **CHANGED**: KNPS `knps_protected_areas`의 영어/로마자 source name을 Gemini 2.5 Flash
  JSON 일괄 번역 결과 기반 한글명 테이블로 보정한다. 런타임은 AI API를 호출하지 않고
  정적 테이블을 사용한다.
- **FIXED**: 라틴 문자와 손상 한글 음절이 섞인 raw `ORIG_NAME`을 정상 한글명으로 오인하지
  않도록 해, `NAME`/번역 테이블 fallback이 동작하게 했다.

### Admin 로그인 form submit 안정화 (2026-06-25)

- **FIXED**: 로그인 form submit이 React state 대신 현재 form value를 읽어 브라우저 자동완성이나
  테스트 자동입력에서 DOM 값과 React state가 어긋나도 빈 password가 전송되지 않게 했다.

### Admin 지도 area 클러스터링 + KNPS area 한글명 보정 (2026-06-24)

- **ADDED**: admin Feature 지도에서 `area` feature도 낮은 줌에서는 centroid marker 기반 cluster에
  포함한다.
- **CHANGED**: `area` polygon/label geometry는 줌 14 이상에서만 요청·표시해 낮은 줌의 대형
  geometry payload와 flicker를 줄인다. 지도 조회 query 전환 중에는 이전 결과를 유지한다.
- **CHANGED**: area/route 중심 tile 조회는 tile 수로 `page_size`를 나누지 않아 area 단독 필터의
  false partial 표시와 누락 가능성을 줄이고, 해당 필터에서는 tile zoom을 한 단계 더 잘게 잡으며
  tile별 `next_cursor`를 이어 받는다.
- **FIXED**: KNPS `knps_protected_areas` source의 한글 raw 이름 후보를 우선 사용하고,
  recoverable CP949/UTF-8 mojibake는 한글명으로 복구하되, 복구 실패한 CJK mojibake는 영어
  fallback을 유지한다.

### Admin 로그인 + public API key 관리 (2026-06-23)

- **ADDED**: admin frontend에 `admin` 단일 계정 로그인 화면을 추가했다. 비밀번호 원문은 저장하지
  않고 gitignored `.env`의 PBKDF2-SHA256 hash와 server-only session secret으로 검증한다.
- **ADDED**: Next.js `/api/proxy` BFF를 통해 FastAPI admin API를 호출하도록 바꾸고,
  FastAPI admin router는 proxy secret이 설정된 환경에서 지정된 frontend proxy header만 신뢰한다.
- **ADDED**: 로그인 시도/로그아웃 기록을 `ops.admin_auth_events`에 저장하고
  `/admin/settings`에서 조회할 수 있게 했다.
- **ADDED**: `/admin/settings`에서 VWorld 호환 32자 public API key를 랜덤 생성/폐기한다.
  DB에는 key hash와 hint만 저장하고, active hash는 TTL cache 후 생성/폐기 시 무효화한다.
- **CHANGED**: public REST surface는 `key` query 검증을 지원하며, trusted admin proxy와
  service-token 요청은 검증을 우회한다. `kor-travel-geo` v2 호출도 `key` query를 붙이며 현재
  운용값은 VWorld API key와 동일하게 둔다.
- **FIXED**: 로그인 rate-limit/audit에서 client-controlled proxy header를 기본적으로 신뢰하지
  않게 하고, 세션 만료 401은 `/login`으로 되돌린다. API key 폐기 요청의 잘못된 UUID는 500 대신
  not found로 처리한다.

### Admin 지도 route/area 표시 + 지도 성능 보강 (2026-06-23)

- **ADDED**: admin Feature 지도에서 point feature는 `marker_icon`/`marker_color` 기반
  maki 마커로 표시하고, `weather` feature는 날씨 아이콘 대신 단순 색상 마커로 표시한다.
- **ADDED**: `route` feature는 GeoJSON 선 + 이름 라벨, `area` feature는 면 채움/외곽선 +
  이름·면적 라벨로 표시한다. 이를 위해 `/v1/features`에 선택적 `include_geometry`
  파라미터와 route/area 지도용 `geometry`, `area_square_meters` 응답 필드를 추가했다.
- **CHANGED**: 지도 클러스터 DOM 마커 갱신을 매 render frame 대신 `moveend`/`zoomend`/
  `sourcedata` 중심으로 줄이고, 낮은 줌에서는 bbox 요청 범위를 더 거칠게 양자화해
  큰 범위 지도 이동 시 불필요한 refetch를 줄였다.
- **CHANGED**: bbox 조회 SQL이 낮은 축척에서 후보 전체를 `MATERIALIZED` CTE로 만든 뒤
  정렬하던 병목을 제거하고, `ORDER BY feature_id LIMIT` 조기 종료가 가능하도록 바꿨다.
- **CHANGED**: admin 지도 표시용 route/area GeoJSON은 원본 geometry를 그대로 보내지 않고
  화면 표시용으로 단순화하고 좌표 정밀도를 제한해 큰 route 응답 크기를 줄였다.
- **CHANGED**: admin 지도 bbox fetch를 WebMercator tile 단위 요청으로 나누고 tile별
  react-query 캐시를 적용해 pan/zoom 시 이미 받은 공간 데이터를 재사용한다.

### krex 고속도로 휴게소 관측 기상을 weather source로 추가 (2026-06-23)

- **ADDED**: 고속도로 휴게소 관측 기상(`restWeatherList`, EX)을 weather-kind Feature로
  적재하는 provider 변환부(`rest_area_weather_records_to_bundles` /
  `rest_area_weather_records_to_values`, `KrexRestAreaWeatherRecord` Protocol) +
  Dagster fetcher(`fetch_krex_rest_area_weather`) + asset(`feature_weather_krex_rest_areas`,
  매시 schedule)를 추가했다. airkorea 대기질 패턴과 동일하게 휴게소를 `unit_code` 안정키 +
  행 내 좌표로 self-contained weather feature로 만들고(place 휴게소와 fuzzy 매칭 안 함,
  ADR-010 — 관측값은 place 아님), 기온/습도/풍속/강수를 metric별 `WeatherValue`로 melt한다.
  `temperature → T1H` 매핑이라 `build_weather_card`의 nearest-temp(`metric_key IN
  ('T1H','TMP')`)가 휴게소를 기온 anchor로 조회 — KMA 격자 기온 빈틈(고속도로 농촌 구간)을
  휴게소 관측값으로 메운다. de-rep(#496)과 동일하게 휴게소당 1 feature(복제 없음).
  EX key(`KEX_GO_API_KEY`)는 traffic_notices가 이미 쓰던 것을 재사용(신규 env 불필요).

### Dagster 이미지: provider repo 전부 public → 토큰 없이 full ETL (2026-06-22)

- **CHANGED**: `docker/dagster.Dockerfile`이 `GITHUB_TOKEN` 유무와 무관하게 항상
  `.[providers]`(provider 13종 포함 full ETL)를 설치하도록 바꿨다. 마지막 private였던
  `python-datagokr-api`가 public으로 전환돼 provider repo가 전부 public이 되었으므로 익명
  clone으로 빌드된다. 직전의 "토큰 없으면 `[providers]` 스킵(live ETL 비활성)"
  graceful-degradation은 제거했다. BuildKit secret `github_token`은 선택사항으로 유지한다
  (미인증 rate-limit 회피 / provider 재-private 대비). 빌드/배포 환경에 토큰 없이도 dagster가
  실데이터 fetch를 수행할 수 있다.

### Admin frontend 요청 취소 전파 (2026-06-22)

- **FIXED**: admin frontend의 API 클라이언트(`src/api/client.ts`)와 모든 read query
  fetcher가 react-query의 `AbortSignal`을 `fetch`로 전달하지 않아, 필터/지도 bbox/목록
  churn으로 query가 취소돼도 in-flight 브라우저 fetch가 계속되던 문제를 수정했다. host당
  커넥션(브라우저 ~6) 포화로 인한 "처음 빼고 느림/무응답" 위험을 제거한다. mutation 경로는
  자동 취소 대상이 아니라 무변경. (kor-travel-concierge #111과 동일 계열 — 본 repo는 BFF
  프록시가 아니라 브라우저 직접 호출 경로.)

### Admin frontend 오류 화면 복구 (2026-06-20)

- **FIXED**: Next App Router segment/global error boundary(`app/error.tsx`,
  `app/global-error.tsx`)를 추가해, 브라우저가 Next 기본 영어 오류 화면
  (`This page couldn’t load`)으로 떨어지던 방어 공백을 보강했다. 앱 자체 한국어 복구
  패널(다시 시도/이전 화면/오류 정보)을 보여 주고, chunk/RSC/network 계열 런타임 오류는
  같은 pathname에서 1회만 hard reload로 복구를 시도한다. (kor-travel-geo #391/T-278 동일 반영.)

### Admin frontend 디자인 정리 (2026-06-18)

- **CHANGED**: admin frontend 공통 디자인 토큰과 primitive를 StyleSeed 규칙에 맞춰
  정리했다. 단일 brand accent, 카드 기반 정보 표면, 낮은 shadow, 명시적 type
  scale, 상태 badge dot+text 패턴을 적용했다.
- **CHANGED**: 운영 홈 KPI/상태 카드의 loading 상태, 숫자+단위 표시, 모바일
  overflow 처리를 개선했다.
- **ADDED**: `docs/architecture/admin-frontend-design-rules.md`에 admin frontend
  디자인 핵심 규칙을 문서화했다.

### Docker 공유 DB 모드 (2026-06-13)

- **ADDED**: `KOR_TRAVEL_MAP_DB_EXTERNAL=true` Docker 기동 모드. PC 개발 환경의
  공유 PostGIS 서버 인스턴스(host `5432`)를 사용하면서 kor-travel-map local RustFS는
  compose로 띄운다.
- **CHANGED**: standalone local Postgres host publish 기본값을 `15432`로 분리했다.
  host `5432`는 공유 DB 서버 인스턴스 기준이다.

### API/admin 패키지 분리 (T-228, 2026-06-13)

- **BREAKING**: FastAPI/OpenAPI backend를 `kor-travel-map-api`
  (`packages/kor-travel-map-api/`, import `kortravelmap.api`) Python 패키지로 분리했다.
  `kor-travel-map-admin`은 Next.js admin frontend 패키지로 남는다.
- **BREAKING**: backend 설정 prefix는 `KOR_TRAVEL_MAP_API_*`, frontend API base URL은
  `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`다. 구 `KOR_TRAVEL_MAP_ADMIN_*` API 설정과
  `NEXT_PUBLIC_KOR_TRAVEL_MAP_ADMIN_API` 호환 shim은 없다.
- **CHANGED**: OpenAPI 기계 정본은 `packages/kor-travel-map-api/openapi.json`과
  `packages/kor-travel-map-api/openapi.user.json`으로 이동했다.

### Prometheus 메트릭 (T-227, 2026-06-13)

- **ADDED**: `GET /metrics` — Prometheus pull scrape용 메트릭 노출 endpoint.
  공개 REST(`/v1/features`·`/v1/categories`·`/v1/providers`·`/v1/public`),
  `/admin`, `/ops`, `/debug`, system route 전반의 HTTP 요청 total, duration
  histogram, 진행 중 요청 gauge, 응답 크기 histogram, 예외 count와 DB query
  count/duration histogram, 프로세스/런타임 메트릭을 제공한다. 기본 scrape target은
  API 포트 `12301`의 `/metrics`이며, 관측 스택 포트는
  `kor-travel-docker-manager` 기준 Prometheus `12601`, cAdvisor `12602`, Grafana
  `12605`를 따른다.

### curated_features Admin UI (T-223c-3, 2026-06-12)

- **ADDED**: admin frontend `/admin/curated-features` — curated 후보 목록,
  select/unselect/archive action, source rule 편집/apply, detail snapshot preview.
- **ADDED**: 선택 후보의 display title/summary, rank score, reuse policy,
  curation relation 편집 표면.

### Offline upload 삭제 lifecycle (#397, 2026-06-12)

- **ADDED**: `DELETE /v1/admin/offline-uploads/{upload_id}` — 업로드 메타데이터
  row 삭제 + 저장 객체 best-effort 삭제(RustFS 교체 등으로 객체가 이미 없는
  "좀비 업로드"도 정리 가능). 진행 중(`validating`/`loading`) 업로드는 409,
  파괴적 admin kill-switch(`admin_destructive_enabled=False`)면 403. row 삭제로
  같은 checksum 재업로드의 멱등 가드(409)가 풀린다.
- **ADDED**: `kortravelmap.infra.offline_upload_repo.delete_offline_upload` +
  `OFFLINE_UPLOAD_IN_PROGRESS_STATES`/`OFFLINE_UPLOAD_DELETABLE_STATES` 상태
  계약. 연관 `ops.import_jobs` row는 audit 기록으로 보존한다.
- **CHANGED**: admin frontend `/admin/offline-uploads` 목록에 행 단위 삭제
  버튼을 추가했다(진행 중 row는 비활성).

### curated_features Dagster group/cache (T-223c-2, 2026-06-12)

- **ADDED**: `feature.curated_feature_detail_snapshots` — curated detail snapshot
  materialize/cache table.
- **ADDED**: `AsyncKorTravelMapClient` curated 배치 표면 —
  source metadata refresh, source rule bulk apply, status sweep, detail snapshot
  materialize.
- **ADDED**: Dagster `curated_features` asset group과 `curated_features_refresh`
  job/schedule.

### curated_features DB/API foundation (T-223c-1, 2026-06-12)

- **ADDED**: `feature.curated_themes`, `curated_sources`,
  `curated_source_rules`, `curated_features` overlay 테이블과 1차 seed source/rule.
- **ADDED**: `GET /v1/curated-themes`, `/v1/curated-sources`,
  `/v1/curated-features*` 공개 조회 API.
- **ADDED**: `/v1/admin/curated-*` backend API — feature select/unselect/archive,
  theme/source/rule create/patch, source rule apply, detail snapshot preview.
- **CHANGED**: `openapi.user.json`과 `@kor-travel-map/map-user-client` 타입에 curated read
  표면을 포함했다.

### 공개 해수욕장/축제 view API (T-222b, 2026-06-12)

- **ADDED**: `GET /v1/public/beaches`, `/v1/public/beaches/map-markers`,
  `/v1/public/beaches/{feature_id}` — 해수욕장 공개 목록/지도/상세 view.
- **ADDED**: `GET /v1/public/festivals/monthly`,
  `/v1/public/festivals/map-markers`, `/v1/public/festivals/{feature_id}` —
  월별 축제 공개 목록/지도/상세 view.
- **CHANGED**: `openapi.user.json`과 `@kor-travel-map/map-user-client` 생성 타입에
  `BeachPublicView`/`FestivalPublicView` 공개 view schema와 경로를 포함했다.

### Ops logs job event 연결 + debug 재판정 (T-221e, 2026-06-12)

- **ADDED**: `GET /v1/ops/import-job-events` — `job_id`/`provider`/`dataset_key`/
  `level` 필터를 지원하는 전역 import job event stream.
- **CHANGED**: admin frontend `/ops/logs`가 system/API log에 더해 Job events 탭과
  job 상세 링크를 제공한다.
- **CHANGED**: `/debug/explain`·`/debug/fixtures` REST/UI는 T-221e 재판정으로
  구현 범위에서 제외하고, EXPLAIN은 테스트/runbook, fixture 저장은 파일 기반 helper와
  `/debug/etl` preview로 정리했다.

### Provider 상세/refresh policy 연결 (T-221d, 2026-06-12)

- **ADDED**: `GET /v1/ops/providers`, `GET /v1/ops/providers/{provider}` —
  provider×dataset sync state, cursor(ops 상세 전용), refresh policy, 최근
  `provider_dataset` update request 링크를 묶는 운영 상세 API.
- **ADDED**: `GET/PUT /v1/admin/provider-refresh-policies*` — provider별 refresh
  interval/rate-limit/source policy 편집 API와 admin UI 편집 패널.
- **ADDED**: admin frontend `/ops/providers`에서 dataset 상세, 정책 편집,
  `provider_dataset` update request 생성/상세 이동을 한 화면에서 처리한다.

### Admin live signal channel (T-221c, 2026-06-12)

- **ADDED**: `WS /v1/ops/live` — `import_jobs`, `import_job:{job_id}`,
  `import_job_events:{job_id}`, `feature_update_requests`, `offline_uploads`,
  `dagster_runs` topic을 다중화하는 admin WebSocket signal 채널.
- **ADDED**: admin frontend import job 목록/상세 화면이 live signal을 받아 관련
  TanStack Query cache를 즉시 invalidate한다. 기존 polling은 fallback으로 유지한다.

### Import job 상세/event/cancel (T-221b, 2026-06-12)

- **ADDED**: `ops.import_job_events` 테이블과
  `GET /v1/ops/import-jobs/{job_id}/events` event timeline API.
- **ADDED**: `POST /v1/ops/import-jobs/{job_id}/cancel` — queued/running job을
  best-effort `cancelled` 상태로 전이하고 cancel event를 기록한다.
- **ADDED**: admin frontend `/ops/import-jobs/[jobId]` 상세 화면. job payload,
  관련 링크(parent/batch/request/upload/Dagster), event timeline, cancel action을
  한 화면에서 확인한다.

### Admin feature 수동 작성 흐름 (T-221a, 2026-06-12)

- **ADDED**: admin frontend `/admin/features/new` — 지도 좌표 선택, kor-travel-geo
  geocode/reverse 후보 적용, `place`/`event` detail form, nearby 중복 후보 확인,
  `POST /v1/admin/features` change-request 생성 흐름.
- **ADDED**: frontend `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL` — 수동 작성 화면에서
  kor-travel-geo REST v2를 호출하는 public base URL.
- **FIXED**: MapLibre mount container에 inline sizing을 보강해 `/features` 지도와
  `/admin/features/new` 지도에서 `maplibregl-map` CSS가 Tailwind absolute sizing을
  무효화하지 않게 했다.

### Admin feature 상세 경로 1차 (T-221a, 2026-06-12)

- **ADDED**: `GET /v1/admin/features/{feature_id}` — feature core snapshot,
  source/raw payload, issue, override, version/change request history, 선택적
  `feature_files` metadata를 묶는 운영자용 상세 API.
- **ADDED**: admin frontend `/features/[featureId]` 상세 화면. `/features` 지도/테이블과
  `/admin/features` 목록에서 새 상세 화면으로 이동할 수 있으며, weather/nearby도 같은
  화면에서 확인한다.
- **CHANGED**: admin OpenAPI와 frontend generated type을 새 상세 API 기준으로 갱신했다.

### MCST provider 재배선 — CSV 파일 다운로드 주경로 (#395, T-220 재배선, 2026-06-12)

- **CHANGED**: `python-mcst-api` pin `d06e8d2` → `ba471ee` — provider가 KCISA
  OpenAPI에서 **CSV 파일 다운로드 주경로**로 재편(provider #6/#7/#9). krtour
  MCST 배선 전체를 keyless `FileDataClient` 표면으로 재작성.
- **CHANGED**: `providers.mcst` — slug 메타표를 `MCST_FILE_DATASETS` 12종(컬럼
  방언 4종: kcisa_common/cntc_resrce/split_coord/korean_address)으로 교체하고
  변환을 `file_rows_to_bundles` 1개로 통합. dataset_key는 `mcst_<slug>` 클린 컷
  (구 키 하위호환 없음 — 빈 DB 재적재 중). 신규 적재 2종: 아동서점
  (`children_bookstores_csv`)·골프장(`golf_courses_status`).
- **ADDED**: `parse_kcisa_coordinates` — 실측 COORDINATES 2형식("N37.5,
  E126.9" 접두형 / "35.8 , 128.6" 평문 lat-lon, 공백 변형 포함) 파서 + 한국
  bbox(lon 124~132, lat 33~43) 검증·순서 뒤집힘 교정. 실패 시 좌표 없음(주소
  단서 경로).
- **REMOVED**: ODCloud 도서관 계열(`mcst_public_libraries`/
  `mcst_small_libraries` dataset, `feature_place_mcst_libraries` asset,
  `fetch_mcst_libraries` fetcher, `mcst_library_records` resource) — provider
  재편으로 경로 소멸. 기사형/통계 3 dataset(`tourism_attractions_csv`/
  `recommended_travel_destinations_csv`/`public_libraries`)은 적재 제외
  (`MCST_EXCLUDED_FILE_DATASETS`에 사유 보존).
- **CHANGED**: Dagster `fetch_mcst_culture_records`가 keyless로 전환(credential
  guard 제거 — `DATA_GO_KR_SERVICE_KEY` 불요), `mcst_max_items_per_dataset`
  기본 5000 → 50000(실측 최대 24,537행의 약 2배 여유). admin ETL preview
  fixture는 방언 대표 3종으로 교체.

### kor-travel-concierge provider identity clean cut (ADR-053, T-224, 2026-06-12)

- **CHANGED**: YouTube 장소 후보 provider를 `kor-travel-concierge-youtube`에서
  `kor-travel-concierge-youtube`로 재정의했다. 외부 소비자와 agent의 직접 관계는 제거하고,
  provider 관계는 kor-travel-map ↔ kor-travel-concierge 사이에만 둔다.
- **CHANGED**: Dagster resource/asset/schedule, settings/env 이름을
  `kor_travel_concierge_*` / `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_*` 기준으로 바꿨다. 구
  `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_*` 호환 shim은 두지 않는다.
- **CHANGED**: Python provider module은 `kortravelmap.providers.kor_travel_concierge`,
  raw payload 보존 key는 `detail.payload.kor_travel_concierge`다.

### Local/Docker 고정 포트 재정렬 (ADR-047 amendment, 2026-06-12)

- **CHANGED**: kor-travel-map standalone 기본 포트를 API `12301`, 관리 보조(Dagster)
  `12302`, Web UI `12305`로 재고정했다.
- **CHANGED**: Postgres host port 기본값을 표준 `5432`로 바꾸고, RustFS S3 API
  기본값을 `12101`로 바꿨다. RustFS console host port는 `12105`를 유지한다.
- **CHANGED**: kor-travel-geo 연동 기본 URL을 API `http://127.0.0.1:12201`로 바꿨고,
  문서에는 kor-travel-geo Web UI `12205`를 함께 명시했다.
- **CHANGED**: Docker compose, Dockerfile expose, `.env.example`, `scripts/load-env.sh`,
  admin/frontend fallback URL, Playwright/e2e/test expectation, runbook 문서의 포트
  기준을 새 값으로 정렬했다.

### 축제 날짜 역전 격리 + datagokr 핀 범프 (#386, T-212e, 2026-06-11)

- **FIXED**: 전국문화축제 실데이터의 시작/종료 역전 row(원천 오타)가
  `EventDetail` 도메인 검증 ValidationError로 dataset 전체 적재를 막던 문제 —
  역전 시 두 날짜를 격리(None)하고 row는 적재(raw_data에 원본 보존).
- **CHANGED**: `python-datagokr-api` pin `f88e62e` → `26a5be3` — 주차장
  `basicTime`/`addUnitTime` 분수값(live `'0.5'`) float 허용(provider #6/PR#7).

### Dagster — mois op/job 동명 충돌로 repository 로드 실패 수정 (#384, T-212e, 2026-06-11)

- **FIXED**: `mois_source_sync` op 이름을 `sync_mois_localdata_source_db`로 변경 —
  job과 동명(`mois_localdata_source_sync`)이라 **repository 전체 로드가
  `DagsterInvalidDefinitionError`로 실패**(웹서버 repo 0개, admin offline upload
  `POST /load` 502 `PipelineNotFoundError`, schedule/sensor 불능)하던 문제.
  2026-06-07 mois Phase A 머지 이후 잠복 — CLI materialize/execute는 전체 로드
  경로를 타지 않아 드러나지 않았다.
- **ADDED**: definitions 테스트에 repository 전체 로드 회귀
  (`load_all_definitions`) — 노드명 충돌류를 CI에서 차단.

### kma pin bump — datagokr 03 NO_DATA 빈 결과 정규화 (T-212e, 2026-06-11)

- **CHANGED**: `python-kma-api` pin `ab1a0b8` → `006fdbe` — datagokr result
  code `03`(NO_DATA)을 예외 대신 빈 결과로 정규화한 provider #18/PR#19 반영.
  T-212e live run에서 특보(getWthrWrnList) rolling window에 특보가 없는 평시
  구간 조회가 `KmaRequestError`로 죽던 문제 해소(run `408ad65f`). 중기예보 등
  같은 unwrap 경로의 datagokr endpoint 전체에 적용.

### krheritage 국가유산 본체 — items live fetcher 배선 + HeritageDetail 재정렬 (#380, T-212e, 2026-06-11)

- **FIXED**: `KrHeritageItem`/`heritage_items_to_bundles`를 provider 실모델
  `krheritage.models.HeritageDetail`(복합키 `key` 중첩 — 신규
  `KrHeritageItemKey` Protocol + `key.natural_key`, 명칭 `name_ko`, 유형
  `category`=ccmaName, 지정일 `designated_at` YYYYMMDD 문자열 방어 파싱)으로
  재정렬했다(ADR-044, #374/#378과 동일 방향). `geom_wkt`/`raw`는 provider에
  없는 발명 필드라 제거 — GIS 경계 보강은 후속, raw_data는 Protocol 필드에서
  구성. 소재지는 `location_text`(detail) 우선 + `region+sigungu` fallback.
  명칭 빈 row는 skip. 천연기념물(15)은 경계 미배선 동안 place.
- **NEW**: Dagster `fetch_krheritage_items` live fetcher + `krheritage_items`
  resource live override(#380 — 종전 guard로 `feature_place_krheritage_items`
  run 실패). khs.go.kr search/detail은 **keyless**(provider transport는
  apis.data.go.kr URL에만 serviceKey 주입) — spec credential 요구 제거.
  settings `krheritage_kind_codes`(기본 `"11,12,13,15,16"` 국보/보물/사적/
  천연기념물/명승)와 `krheritage_max_items_per_run`(기본 5000, detail 1건당
  1콜 보호) 신설.
- **FIXED**: `krheritage_events` live 일부 row의 빈 `sn`이 ADR-009 검증
  ValueError로 run을 깨던 문제(run `bd92b726`) — `sn`이 비면
  `title::starts_on::place` 결정적 fallback 자연키 파생(ADR-009 `::`),
  `sn`도 행사명도 없는 row는 skip.

### krex 교통공지 — 신규 Incident(realTimeSms) shape 재정렬 + krex/khoa pin bump (#378, T-212e, 2026-06-11)

- **FIXED**: `KrexTrafficNoticeItem`/`traffic_notices_to_bundles`를 provider
  `krex.models.Incident` 신규 shape(krex#8/PR#9 — 구 404 endpoint
  `trafficapi/incident` → `openapi/burstInfo/realTimeSms` repoint)으로 재정렬
  (ADR-044). 구 `started_at`/`ended_at`은 provider에 더 이상 없음 —
  `occurred_date`("2023.09.27")+`occurred_time`("09:11:24")에서
  `valid_start_time`을 파생하고(KST, 방어적 파싱), 종료 컬럼이 없어
  `valid_end_time`은 None(만료는 transient refresh + `process_status` payload).
- **CHANGED**: 자연키 `occurred_date::occurred_time::route_no::raw_hash`
  (ADR-009 `::`). 좌표(`latitude`/`longitude` — 원천 키 `altitude`가 경도)
  보유 row는 이제 `Feature.coord` + reverse geocoding, coordless row는
  노선/지점/방향을 `raw_address` 위치 단서로 보존. `point_name`/
  `incident_type_code`/`process_status(_code)` 등 신규 필드 payload 보존.
  admin live loader endpoint/adapter(raw 키 `accDate`/`accType`/`smsText`/
  `nosunNM`/`roadNM` 등)·fixture·테스트 fake 동일 shape 갱신.
- **CHANGED**: providers extra pin bump — `python-krex-api@2504a36`(realTimeSms
  재정렬), `python-khoa-api@0ccb5ed`(snake_case live row 파싱, khoa#5/PR#6).

### Dagster — 주소/좌표 검증 모드 strict/drop/off (#376, T-212e, 2026-06-11)

- **NEW**: settings `dagster_address_validation`(`strict`/`drop`/`off`, 기본 `strict`,
  env `KOR_TRAVEL_MAP_DAGSTER_ADDRESS_VALIDATION`) — `strict_address` resource가 이 값을
  읽는다(bool 하위호환: True→strict, False→off).
- **NEW**: `drop` 모드 — error-severity 검증 row만 격리하고 나머지를 적재. 격리
  건수/feature_id는 run 메타데이터(`address_validation_dropped_*`)로 노출(silent
  cap 금지). 실데이터의 소수 주소↔좌표 불일치가 dataset 전체 적재를 차단하지
  않게 한다(T-212e 박물관/관광지 live run에서 발견).

### datagokr 축제 변환 — provider 실모델 재정렬 (#374, 2026-06-11)

- **FIXED**: `cultural_festivals_to_bundles`/`CulturalFestivalItem`을 provider
  실모델 `PublicCulturalFestival` 필드명(`fstvl_nm`/`opar`/`rdnmadr` 등, 좌표
  `float`)으로 재정렬했다 (ADR-044). 종전 Protocol이 발명한 `management_no`/
  `road_address`/`festival_name` 필드 때문에 live Dagster run이
  `AttributeError`로 실패하던 문제 해결.
- **CHANGED**: 자연키는 원천에 관리번호 컬럼이 없어 `name::address` 파생
  (ADR-009 `::`, museum/mcst 패턴). 축제명 없는 row는 skip. admin ETL
  adapter/fixture도 동일 shape으로 갱신 — `EventDetail.payload`의
  `organizer_name`(주관기관명)/`provider_org_name`(제공기관명) key는 유지.

### Frontend — React Doctor + maplibre-vworld-js 정합 (2026-06-11)

- **CHANGED**: admin frontend React Doctor full scan 기준 optional warning까지 0건이 되도록
  UI primitive export 구조, React 19 ref 전달, iframe sandbox, 미사용 hook export를 정리했다.
- **CHANGED**: `maplibre-vworld-js` consumer pin을 최신 tag `v0.1.3`으로 맞추고,
  `@kor-travel-map/map-marker-react` peer/dev dependency와 root lockfile의 `maplibre-vworld`
  항목을 같은 값으로 정렬했다.

### MCST 신규 provider — KCISA 14 + ODCloud 도서관 2 (T-220, 2026-06-11)

- **NEW**: `providers/mcst.py` — slug 메타표 16종(`mcst_<slug>`) + 공용
  `culture_records_to_bundles`/`library_records_to_bundles`. category는 전부
  기존 코드(place_kind가 세부 구분), marker `P-12`, 자연키 `name::address`.
- **NEW**: Dagster `(slug, record)` 튜플 fetch 2종 + record resource 2종 +
  asset 2종(`feature_place_mcst_{culture,libraries}` — slug별 분리 적재,
  `McstLoadResult` 합산 metadata) + 주 1회 schedule. settings
  `mcst_max_items_per_dataset`(기본 5000).
- **ADDED**: admin ETL preview fixture 2종(`mcst_independent_bookstores`/
  `mcst_public_libraries`), `python-mcst-api@d06e8d2` 핀 활성화, 문서
  `docs/mcst-feature-etl.md`(dedup pair는 실데이터 확인 후 등록 검토 — §6).

### Dagster — KMA 중기예보 + 기상특보 (T-219c, 2026-06-11)

- **NEW**: asset `feature_weather_kma_mid_forecast` — 운영자 주입 매핑
  (`KOR_TRAVEL_MAP_KMA_MID_REGION_FEATURES` JSON, 육상/기온 reg_id 분리)의 region별
  `getMidLandFcst`+`getMidTa`를 SKY/POP/TMN/TMX `WeatherValue`로 적재(일 2회,
  미설정 시 skip). resource `kma_datagokr_client` 신설.
- **NEW**: asset `feature_notice_kma_weather_alerts` — 표준 record-resource
  (`kma_weather_alert_records`, getWthrWrnList 전국 발표관서 rolling window) →
  notice Feature 적재. 종류/등급은 title 토큰 스캔, 특보구역은 1차 발표관서
  단위(구역 enrichment 백로그).
- **CHANGED**: 특보 `SourceRecord.raw_address`에 region명을 채워(위치 단서)
  Dagster 주소 검증(ADR-046 `missing_address`)을 통과하게 했다.
- **ADDED**: settings `kma_mid_region_features`/`kma_weather_alert_lookback_days`,
  파서 `parse_mid_region_features`.

### Dagster — KMA weather 파이프라인 (실황/초단기/단기, T-219b, 2026-06-11)

- **NEW**: Dagster asset 3종 `feature_weather_kma_{ultra_short_nowcast,
  ultra_short_forecast,short_forecast}` + KST schedule — 활성 POI cache target
  좌표(+설정 추가 좌표)의 distinct 격자만 호출(run당 상한, 기본 50)하고 같은
  격자의 미삭제 place feature에 `WeatherValue`를 적재한다(옵션 B, D-12 read
  정합). 같은 base 재실행은 `provider_sync_state` cursor(`base_datetime`)가
  skip하고, 실패는 cursor 미전진 + `record_sync_failure`.
- **NEW**: resource `kma_weather_client`(python-kma-api `KmaClient` live,
  `DATA_GO_KR_SERVICE_KEY` 공유) + settings 값 resource 2종. `providers` extra에
  `python-kma-api@ab1a0b8` 핀 활성화.
- **ADDED**: `AsyncKorTravelMapClient.list_poi_cache_target_coords()` /
  `list_active_place_coords()` read 메서드, KMA dataset_key 상수 3종.

## [Unreleased]

### API — T-216 REST 계약 표면 clean cut (2026-06-09)

- **CHANGED (breaking)**: admin/ops/debug 라우터도 `/v1` prefix로 이동했다. liveness
  `/health`·`/version`만 비버저닝 유지하며, 구 unversioned alias는 두지 않는다.
- **CHANGED (breaking)**: 목록 pagination은 `page_size` + `meta.page.next_cursor`로
  통일하고, `data.next_cursor`/`meta.count`/파생 `count`를 제거했다.
- **CHANGED (breaking)**: REST 표면의 상태/식별자 명명을 `status`, `issue_id`,
  `review_id`, `log_id`로 정리하고, 에러 응답은 `application/problem+json` top-level
  `code`/`request_id`/`errors` 확장으로 통일했다.
- **CHANGED**: `openapi.json`/`openapi.user.json`, frontend generated type/API hook/UI/e2e
  mock을 새 계약 기준으로 재생성·정렬했다.

## [Unreleased]

### DB — pg_prewarm 부팅 후 warm-up 메커니즘 (T-102, 2026-06-09)

- **ADDED**: migration `0022_pg_prewarm_extension` — `pg_prewarm` 확장을 `x_extension`에 생성.
- **ADDED**: `kortravelmap.infra.prewarm.prewarm_relations` — hot relation을 `pg_prewarm`으로
  buffer warm-up하는 명시적 헬퍼(확장 미설치 시 no-op, 존재하지 않는 relation skip).
- **ADDED**: docker-compose postgres `shared_preload_libraries=pg_prewarm` +
  `autoprewarm=on`(background 재기동 자동 warm-up). `/ops/health-deep`에 `prewarm` 컴포넌트.
- 효과는 도입 조건(P99 SLO + shared_buffers fit) 충족 시 큼 — `docs/performance.md §9.5`.

## [Unreleased]

### marker — map-marker-react maki glyph 보강 + Python↔TS drift gate (T-017, 2026-06-09)

- **ADDED**: `tests/unit/test_category_maki_consistency.py` — Python category catalog의 maki
  아이콘 이름(`PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES`)이 전부 TS `packages/map-marker-react/
  src/maki.ts`의 `MAKI_GLYPH`에 존재하는지 검증(drift gate, ADR-029/043).
- **ADDED**: `MAKI_GLYPH`에 Python category가 쓰는 누락 maki 46종(airport/museum/hospital/
  beach 등) 글리프 추가. T-017(maki/category npm share 모듈 추출) 완료.

### Admin UI/API — feature change request 큐 화면 (T-215b, 2026-06-09)

- **NEW**: `/admin/features/change-requests` 화면을 추가해 feature add/update/delete 요청
  생성, 상태/action/q/limit 필터, payload 상세, approve/reject 작업을 한 곳에서 처리한다.
- **CHANGED**: frontend API hook은 기존 REST 표면(`/admin/features` +
  `/admin/features/change-requests*`)만 사용한다. 중복 create/update/delete 별도 endpoint는
  만들지 않았다.
- **CHANGED**: `GET /admin/features/change-requests` 응답 meta에 현재
  `review_mode`를 포함해 큐가 비어 있어도 UI가 운영 모드를 표시한다.

### API — T-214 tail: pagination/parameter·error 규약 + `/debug/health|version` 제거 (T-214e/f/g/h, 2026-06-09)

- **CHANGED (breaking)**: `GET /v1/features/search`의 bbox를 CSV `bbox`에서 분리 4-float
  (`min_lon`/`min_lat`/`max_lon`/`max_lat`)로 바꾸고, `limit`→`page_size`로 통일(T-214e).
  bounded 지도 조회(`/v1/features`·`/v1/features/in-bounds`)는 `limit` 유지.
- **CHANGED (breaking)**: `/debug/health`·`/debug/version` **제거**(T-214h, ADR-048 clean cut) —
  공용 `/health`·`/version` + `/ops/health-deep`과 중복. `health.py`/`version.py` 라우터 삭제,
  frontend status 위젯을 public 엔드포인트로 repoint.
- **결정(T-214f)**: POI cache target write(upsert/delete)는 **admin/operator flow 전용**.
  TripMate 직접 write 미허용 — service-safe `/v1/poi-cache-targets/*` write 경로 안 둠.
- **DOC(T-214g)**: 표준 헤더 규약(`X-Request-ID`/`Retry-After`/`Idempotency-Key`/`RateLimit-*`/
  `Deprecation`/`Sunset`) + 에러 코드 enum을 `docs/rest-api.md §4.1`에 단일 표로 고정.

### API — 사용자/서비스 표면에 `/v1` prefix 도입 (T-214b, 2026-06-09)

- **CHANGED (breaking)**: `features`/`categories`/`providers` 라우터를 **`/v1` prefix**로
  노출한다. `GET /features*`→`/v1/features*`(batch `POST /v1/features/batch` 포함),
  `GET /categories`→`/v1/categories`, `GET /providers/{provider}/last-sync`→
  `/v1/providers/...`. 구 unversioned 경로는 유지하지 않는다(clean cut, alias 없음, ADR-048).
  liveness `/health`·`/version`은 비버저닝 유지. admin/ops/debug의 `/v1` 이동은 T-216a.
- **CHANGED**: `USER_OPERATIONS`·`openapi.json`/`openapi.user.json`·frontend generated type·
  frontend API 호출부·e2e route mock 재정렬.

### API — `/tripmate/*` namespace 제거, batch를 `POST /features/batch`로 일반화 (2026-06-09)

- **CHANGED (breaking)**: `POST /tripmate/features/batch` → **`POST /features/batch`**.
  `/tripmate/*` namespace를 제거했다(kor-travel-map은 TripMate 전용이 아니다). batch는
  `features_router`의 service read로 옮기고 `ServiceToken`(`X-Kor-Travel-Map-Service-Token`)을
  route-level로 유지한다(미설정 시 비강제). 다른 `/features/*` GET은 공용 read 그대로.
- **CHANGED**: `USER_OPERATIONS` allowlist·OpenAPI(`openapi.json`/`openapi.user.json`)·
  frontend generated type을 새 경로로 재생성. (ADR-005/045 D-1·ADR-048·`docs/rest-api.md`·
  `docs/tripmate-rest-api.md` 갱신, tasks T-214d 완료.)

### Admin API/Dagster — offline upload idempotency + load preclaim (2026-06-06)

- **FIXED**: `POST /admin/offline-uploads`가 요청 body 기준 SHA-256 checksum을
  `ops.offline_uploads`에 저장하고, 같은 `provider/dataset_key/sync_scope/checksum`
  조합은 DB unique constraint로 409 중복 응답을 반환한다.
- **FIXED**: `/admin/offline-uploads/{upload_id}/load`는 Dagster launch 전에
  `ops.import_jobs` row를 만들고 `offline_uploads.load_job_id`와 `loading` 상태를
  같은 트랜잭션에서 선점한다. Dagster launch 실패 시 job은 `failed`, upload는
  `load_failed`로 닫힌다.
- **CHANGED**: Dagster `offline_upload_load` op는 advisory lock 미획득을 성공 no-op로
  보지 않고 `Failure`로 기록한다. 이미 `loading + load_job_id`인 preclaimed load는
  기존 job을 재사용한다.
- **TEST**: router 단위, Dagster op 단위, core orchestration 단위와 PostGIS 통합
  테스트로 checksum idempotency, preclaimed job 재사용, 중복 load/lock busy 경로를
  검증했다.

### Admin API — offline upload store reuse (2026-06-05)

- **FIXED**: offline upload `create`/`preview`/`validate` 경로가 요청마다
  `KorTravelMapSettings()`와 boto3 S3 client를 새로 만들지 않고,
  `request.app.state.offline_upload_store`를 우선 재사용한다.
- **CHANGED**: cached offline upload store가 만들어진 경우 FastAPI lifespan 종료 시
  내부 S3 client의 `close()`를 호출한다.
- **TEST**: 같은 app에서 연속 upload 요청이 store를 1회만 생성하는지, shutdown 시
  cached client가 닫히는지 router 단위 테스트로 고정했다.

### Admin API — offline upload state contract (2026-06-05)

- **CHANGED**: offline upload 상태/포맷 집합을 `kortravelmap.core.offline_upload_states`
  단일 계약으로 분리해 router, repository, load/validation orchestration이 같은 값을
  사용하게 했다.
- **CHANGED**: `ops.offline_uploads.state` ORM check constraint도 같은 상태 tuple을
  참조하게 해 DB 모델과 core 상태 계약의 drift를 줄였다.
- **DOCS**: `cancelled`는 현재 offline upload cancel producer가 없는 reserved terminal
  state로 명시하고, load 가능 상태 문서를 실제 API 동작과 맞췄다.
- **TEST**: 상태 집합과 ORM check constraint 단위 테스트를 추가하고 기존 offline upload
  unit/integration/router 회귀 테스트를 유지했다.

### Admin API — offline upload write rollback (2026-06-05)

- **FIXED**: `POST /admin/offline-uploads`가 RustFS/S3 object write 이후
  `ops.offline_uploads` row 생성에 실패하면, 같은 요청에서 방금 쓴 object를 보상
  삭제해 DB metadata 없는 orphan object를 남기지 않는다.
- **TEST**: `S3ObjectStore.delete_object()`와 metadata insert 실패 시 rollback delete
  경로를 단위 테스트로 고정했다.

### Integrity — F7 dedup score regression consistency (2026-06-05)

- **NEW**: ADR-033 Phase 2의 `F7` cross-provider dedup score regression WARN 검사를
  `run_consistency_checks()`에 추가했다.
- **TEST**: 큐 저장 `total_score` baseline 대비 현재 `core.scoring` 재계산 score 하락,
  같은 provider 제외, stable score 경계를 검증하는 PostGIS 회귀 테스트를 추가했다.

### Integrity — F5 provider last_success SLA consistency (2026-06-05)

- **NEW**: ADR-033 Phase 2의 `F5` provider `last_success_at` SLA WARN 검사를
  `run_consistency_checks()`에 추가했다.
- **TEST**: 기본 24시간 SLA 초과, provider refresh policy interval 적용,
  disabled policy 제외를 검증하는 PostGIS 회귀 테스트를 추가했다.

### Admin API/UI — POI cache target cursor/schema 안정화 (2026-06-05)

- **FIXED**: `GET /admin/poi-cache-targets` 목록을 `updated_at DESC, target_id DESC`
  keyset cursor로 바꾸고 `cursor`/`next_cursor` 계약을 추가했다.
- **FIXED**: `PUT /admin/poi-cache-targets/{external_system}/{target_key}`의
  `provider_overrides`와 `metadata`를 typed/상한 schema로 검증한다.
- **CHANGED**: admin UI의 POI cache target 목록이 cursor 기반 이전/다음 pagination을
  사용한다.
- **TEST**: repo cursor unit test와 router validation/list cursor 회귀 테스트를
  추가했다.

### Integrity — F6 opening hours consistency (2026-06-05)

- **NEW**: ADR-033 Phase 2의 `F6` opening hours 모순 검사를
  `run_consistency_checks()`에 추가했다.
- **TEST**: 같은 요일에서 `open.time > close.time`인 period는 ERROR로 검출하고,
  24/7 표현과 다음 요일로 넘어가는 영업 구간은 허용하는 PostGIS 회귀 테스트를 추가했다.

### CI — PR full matrix (2026-06-05)

- **CI**: `ci.yml`의 기존 Python matrix check 이름을 유지하면서 unit/lint/admin/dagster
  unit test job으로 좁히고, PostGIS integration과 fixture replay를 별도 job으로 분리했다.
- **CI**: `openapi-drift`와 frontend build check의 path filter를 제거해 모든 PR에서
  required check 후보가 생성되도록 했다.
- **DOCS/TEST**: T-203 이후 branch protection required check 기준을 문서화하고 workflow
  구조 회귀 테스트를 추가했다.

### Docs — branch protection 운영 절차 (2026-06-05)

- **DOCS**: `docs/runbooks/branch-protection.md`를 추가해 GitHub `main` branch
  protection 설정값과 운영 체크리스트를 문서화했다.
- **DOCS**: 현재 always-on required check와 T-203 이후 승격할 path-filtered
  OpenAPI/frontend check를 분리했다.
- **TEST**: branch protection runbook의 required check와 deferred check 문구를 정적
  회귀 테스트로 고정했다.

### Dev Env — pre-commit hooks (2026-06-05)

- **NEW**: `.pre-commit-config.yaml`을 추가해 staged source/test 변경 시
  `docs/journal.md` 갱신을 요구하고, Python code/test 변경에는 `ruff format --check`,
  `mypy --strict`, `lint-imports`를 실행한다.
- **NEW**: `scripts/check_journal_update.py`와 `scripts/run-precommit-check.sh`를 추가해
  journal gate와 static gate를 repo-local 명령으로 고정했다.
- **DOCS**: 개발환경 문서에 `pre-commit install`, `pre-commit run`,
  `BYPASS=1` 일회 우회 기준과 Windows Git/Git Bash 설치 위치를 추가했다.

### Admin API/UI — feature update request schema 검증 (2026-06-05)

- **FIXED**: `POST /admin/feature-update-requests`의 `scope`를 `type`
  discriminator 기반 6개 scope 모델로 검증하고, legacy root `lon`/`lat`
  `center_radius` payload를 `422`로 거절한다.
- **FIXED**: `update_policy`를 알려진 필드만 허용하는 모델로 고정하고,
  `providers`/`dataset_keys` list 상한을 추가했다.
- **FIXED**: admin frontend 생성 payload를 OpenAPI 계약의
  `center: {lon, lat}` 형태로 맞췄다.
- **TEST**: 라우터 schema/validation 회귀 테스트와 admin/user OpenAPI 산출물을
  갱신했다.

### Ops — standalone cold backup runbook (2026-06-05)

- **NEW**: `npm run docker:backup`이 standalone Docker app의 `kor_travel_map`,
  `kor_travel_map_dagster`, RustFS volume을 하나의 backup bundle로 저장한다.
- **DOCS**: `docs/backup-restore.md`에 산출물 구조, checksum/restore dry-check,
  수동 cold restore 경계를 문서화했다.
- **TEST**: backup script와 runbook의 3종 백업 대상, 비파괴 범위, npm script 연결을
  정적 회귀 테스트로 고정했다.

### Docker — runtime image hygiene (2026-06-05)

- **CHANGED**: `api`와 `dagster` Docker image를 builder/runtime stage로 분리하고
  runtime stage를 non-root `appuser`로 실행한다.
- **CHANGED**: frontend Docker image는 Next.js standalone server 산출물을 runner stage에
  복사하고 non-root `nextjs` 사용자로 실행한다.
- **TEST**: Dockerfile multi-stage/non-root/standalone 회귀 테스트를 추가했다.

### Infra — ops cursor decode hygiene (2026-06-05)

- **FIXED**: `infra.ops_repo` keyset cursor decode가 broad `Exception` catch 대신
  base64/UTF-8/JSON/schema/datetime 오류를 구체적으로 처리한다.
- **TEST**: import job cursor의 wrong-kind, missing field, invalid datetime,
  non-object payload 회귀 테스트를 추가했다.

### Map Marker React — dependency metadata hygiene (2026-06-05)

- **FIXED**: `@kor-travel-map/map-marker-react`의 `maplibre-vworld` peer dependency를
  `0.1.2`로 고정해 workspace devDependency의 git tag pin(`v0.1.2`)과 맞췄다.
- **FIXED**: skeleton 패키지의 `npm run test`가 테스트 파일 없음 상태를 성공으로
  처리하도록 `vitest run --passWithNoTests`를 사용한다.
- **DOCS**: `@kor-travel-map/map-marker-react` README의 npm registry 게시 설명을 ADR-043의
  registry 게시 보류 정책에 맞췄다.

### Admin API/UI — Dagster router hardening (2026-06-05)

- **FIXED**: `GET /ops/dagster/summary`가 더 이상 Dagster `setNuxSeen` mutation을
  호출하지 않는다. NUX 처리는 `POST /ops/dagster/nux-seen`으로 분리했다.
- **SECURITY**: `KOR_TRAVEL_MAP_API_DAGSTER_ALLOWED_HOSTS` allowlist와 http/https scheme,
  GraphQL path 검증으로 Dagster GraphQL URL SSRF 위험을 줄였다.
- **CHANGED**: Dagster GraphQL 호출은 FastAPI app state의 공유 `httpx.AsyncClient`를
  사용한다.
- **TEST**: Dagster router unit test와 OpenAPI schema를 새 계약에 맞춰 갱신했다.

### Docs — Dagster purge schedule cleanup (2026-06-05)

- **DOCS**: 실제 구현 없는 `feature_purge_*` asset/job 후보와 `purge notice old`
  schedule 행을 `docs/dagster-boundary.md`에서 제거했다.
- **DOCS**: purge는 TTL·삭제 정책과 실제 Dagster job이 함께 구현되기 전까지 schedule
  표에 추가하지 않는다고 명시했다.

### Docs — shell script execution context (2026-06-05)

- **DOCS**: `scripts/*.sh` 운영 스크립트가 WSL/Git Bash용 Bash script임을
  `docs/dev-environment.md`와 Docker runbook에 명시했다.
- **DOCS**: PowerShell에서는 `.sh`를 직접 실행하지 않고 `wsl bash -lc ...`로
  위임하는 예시를 추가했다.

### Dagster — package dependency hygiene (2026-06-05)

- **FIXED**: `kor-travel-map-dagster`가 `kor-travel-map==0.2.0-dev`를 명시적으로
  요구해 같은 릴리스의 메인 라이브러리와 함께 설치되도록 했다.
- **FIXED**: Dagster `offline_upload_store` resource가 직접 import하는
  `boto3`/`botocore`를 runtime dependencies에 추가했다.
- **TEST**: Dagster 패키지 로컬 `asyncio_mode="auto"`와 dependency metadata 회귀
  테스트를 추가했다.

### Docker — compose healthcheck/readiness (2026-06-05)

- **FIXED**: Docker compose의 `api`, `frontend`, `dagster` 서비스에 runtime
  healthcheck를 추가했다.
- **FIXED**: `frontend`가 short-form `depends_on` 대신 `api: service_healthy` 이후
  시작하도록 readiness 순서를 명시했다.
- **TEST**: compose healthcheck와 readiness dependency 회귀 테스트를 추가했다.

### Docker — frontend dependency reproducibility (2026-06-05)

- **FIXED**: frontend Docker image가 `npm install`로 floating dependency를 다시
  해석하지 않고, root `package-lock.json` 기반 `npm ci --workspaces --include=optional`
  로 설치한다.
- **DOCS**: Docker runbook과 deploy 메모에 frontend lockfile 갱신/빌드 기준을
  명시했다.

### Admin API — typed error mapping (2026-06-05)

- **FIXED**: feature update request의 kor-travel-geo resolver 설정 누락을 substring
  matching이 아니라 `SigunguResolverUnavailable` 타입으로 `503` 매핑한다.
- **FIXED**: dedup review merge의 not found/conflict를
  `MergeNotFoundError`/`MergeConflictError` 타입으로 `404`/`409` 매핑한다.
- **FIXED**: 알 수 없는 enqueue/merge 예외의 내부 메시지를 admin API `500` 응답에
  그대로 노출하지 않는다.
- **TEST**: feature update/dedup review 라우터 unit test와 merge repo integration
  test를 보강했다.

### Infra/Admin API — 상태전이 guard (2026-06-05)

- **FIXED**: admin feature deactivate가 deleted/soft-deleted feature를 inactive로
  되살리지 않고 `409` conflict로 거절한다.
- **FIXED**: data integrity issue의 `resolved`/`ignored` terminal 상태가 다시
  `open`/`acknowledged`로 돌아가거나 `resolved_at`을 잃지 않도록 막았다.
- **FIXED**: offline upload validation/load mark/finish가 source-state guard를 사용해
  잘못된 완료 처리와 `loaded -> loading` 중복 Dagster 실행 경로를 차단한다.
- **TEST**: admin feature repo/router, integrity issue lifecycle, offline upload
  repo/router/load orchestration focused unit/integration test를 추가했다.

### Infra — dedup refresh master 신호와 keyset paging (2026-06-05)

- **NEW**: `Feature`/`feature.features`에 `coord_precision_digits`를 추가하고,
  DB trigger가 좌표 보유 row의 기본 precision을 6으로 보강하며 좌표 제거 시
  precision을 `NULL`로 정리한다.
- **FIXED**: `list_dedup_refresh_features`가 `updated_at DESC, feature_id DESC`
  keyset cursor를 사용해 `LIMIT` 재실행 시 같은 사전식 앞부분만 반복 조회하지 않는다.
- **NEW**: `DedupRefreshFeature`가 `updated_at`, `coord_precision_digits`,
  `as_master_candidate()`를 노출해 ADR-016 master 선정과 admin 검토 UI가 같은 신호를
  사용할 수 있게 했다.
- **MIGRATION**: alembic `0015_feature_coord_precision`이 컬럼, trigger, check
  constraint, dedup refresh keyset partial index를 추가한다.
- **TEST**: DTO validator, migration trigger, feature load round-trip, dedup refresh
  keyset paging, Dagster config cursor parsing을 검증한다.

### Infra — scope resolver count/preview 분리 (2026-06-05)

- **FIXED**: `count_features_matching_scope`가 `center_radius`, `bbox`,
  `sigungu_by_radius`, `provider_dataset`, `feature_ids` dry-run에서 전체 feature row를
  materialize하지 않고 `count(*)`/provider 집계/sigungu 집계를 별도 SQL로 계산한다.
- **FIXED**: dry-run matched scope는 기본 1000개 preview만 보존하고,
  `feature_preview_count`, `feature_preview_limit`, `feature_preview_truncated`로
  truncation 여부를 기록한다.
- **TEST**: PostGIS integration test로 preview가 1개로 제한되어도 전체
  `feature_count`와 provider/dataset 집계가 3개를 유지하는지 검증한다.

### Infra — dedup merge review row 잠금 (2026-06-04)

- **FIXED**: `merge_from_review`와 admin `merge_dedup_review`가
  `ops.dedup_review_queue` review row를 `FOR UPDATE`로 잠근 뒤 pending 상태를
  확인하도록 바꿔 동시 merge TOCTOU를 차단했다.
- **TEST**: 자동 master 선정 경로와 수동 master 지정 경로가 기존 row lock을
  기다리는지 Postgres `lock_timeout` 기반 integration test를 추가했다.

### Infra — UUID default schema qualification (2026-06-04)

- **FIXED**: `ops.feature_consistency_reports`, `ops.dedup_review_queue`,
  `ops.import_jobs`, `ops.feature_merge_history`의 UUID default를
  `x_extension.gen_random_uuid()`로 스키마 한정해 search_path 의존을 제거했다.
- **MIGRATION**: alembic `0014_uuid_default_schema`가 기존 DB default를
  schema-qualified expression으로 갱신한다.
- **TEST**: Postgres catalog에서 ops UUID default expression이 모두
  `x_extension.gen_random_uuid()`인지 검증하는 integration test를 추가했다.

### Infra — Dedup pair order invariant (2026-06-04)

- **FIXED**: `ops.dedup_review_queue`가 `feature_id_a < feature_id_b` check와
  canonical upsert를 사용해 `(a,b)`/`(b,a)` 대칭 중복을 DB·repo 양쪽에서 차단한다.
- **FIXED**: self-pair dedup 후보는 검토 큐에 넣지 않고 `skipped`로 처리한다.
- **MIGRATION**: alembic `0013_dedup_pair_order_invariant`가 기존 self-pair를 제거하고,
  unordered duplicate pair는 검토 완료 행 우선으로 정리한 뒤 check constraint를
  추가한다.
- **TEST**: reversed pair upsert, self-pair skip, DB check constraint integration
  test를 추가했다.

### Admin/User API — Keyset cursor hardening (2026-06-04)

- **FIXED**: `/features/search` score cursor가 DB score text를 보존하고,
  `ORDER BY score DESC, feature_id ASC`와 같은 `(-score, feature_id)` 축으로 keyset
  비교하도록 바꿨다.
- **FIXED**: `/admin/dedup-review` cursor가 `NUMERIC` score를 문자열로 운반하고,
  predicate와 `ORDER BY` 모두 `review_key::text`를 사용하도록 정렬축을 통일했다.
- **TEST**: 같은 score/total_score를 가진 여러 행을 `page_size=1`로 끝까지 넘기는
  PostGIS integration test를 추가했다.

### Admin API — Feature update lock handling (2026-06-04)

- **FIXED**: `run_mode=now` feature update request 생성/재큐잉 시 동일 scope
  advisory lock이 이미 점유되어 있으면 `409 LOCK_BUSY`와 `Retry-After` 헤더를
  반환한다.
- **FIXED**: feature update executor가 실행 중 scope lock을 보유해 API preflight가
  실제 실행 경합을 감지할 수 있게 했다.
- **FIXED**: `claim_next_update_request`가 queue lock 경합과 빈 큐를 모두 `None`으로
  반환하던 동작을 분리해, lock 경합은 `FeatureUpdateQueueLockBusy` 예외로 드러낸다.
- **TEST**: admin router unit, PostGIS queue/scope advisory lock integration,
  executor scope lock 보유 integration test를 추가했다.

### Ops — Dagster provider resource guard (2026-06-04)

- **NEW**: feature-load provider record key 9개에 기본 guard resource를 등록했다.
  guard는 provider package, dataset, `KOR_TRAVEL_MAP_*` credential env, source env를
  안내하고 secret 값은 노출하지 않는다.
- **NEW**: `KorTravelMapSettings`에 Dagster provider resource용
  `KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY`, `KOR_TRAVEL_MAP_OPINET_API_KEY`,
  `KOR_TRAVEL_MAP_KREX_EX_API_KEY`, `KOR_TRAVEL_MAP_KREX_GO_API_KEY` 설정을 추가했다.
- **DOCS**: 실제 provider public client live fetch wiring은 T-RV-04b 후속으로 남기고,
  현재 기본 guard는 비실행 상태임을 `kor-travel-map-dagster` README에 명시했다.

### Ops — Dagster resource lifecycle (2026-06-04)

- **FIXED**: `kor_travel_map_client` Dagster resource가 생성한 SQLAlchemy `AsyncEngine`을
  run/tick 종료 후 `dispose()`하도록 generator resource로 전환했다.
- **TEST**: fake engine/fake client 기반 resource teardown unit test를 추가했다.

### Ops — Dagster metadata DB and daemon split (2026-06-04)

- **CHANGED**: Docker Dagster runtime을 단일 `dagster dev`에서 `dagster` webserver와
  `dagster-daemon` 서비스로 분리했다.
- **NEW**: `dagster-db-init` 서비스가 같은 Postgres container 안의
  `kor_travel_map_dagster` DB 존재를 보장한다.
- **NEW**: `docker/dagster.yaml`을 추가해 Dagster run/event/schedule metadata를
  `KOR_TRAVEL_MAP_DAGSTER_PG_URL` 기반 `dagster-postgres` storage에 저장한다.
- **TEST**: compose 서비스 분리, Postgres storage 설정, `dagster-postgres` 의존성을
  고정하는 unit test를 추가했다.

### Public API — Response field hardening (2026-06-04)

- **CHANGED**: public `FeatureDetailResponse`에서 `coord_5179_srid`,
  `parent_feature_id`, `sibling_group_id`를 제거했다.
- **CHANGED**: `GET /features/nearby/by-target` 응답에서 target 내부 id/refresh policy와
  주변 feature의 `primary_provider`, `primary_dataset_key`를 제거했다. user OpenAPI
  profile도 같은 fieldset으로 갱신했다.
- **TEST**: router 응답과 `openapi.user.json` schema에 내부 필드가 남지 않는 회귀
  테스트를 추가했다.

### Admin API — Route gates (2026-06-04)

- **NEW**: `KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED`와
  `KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED` 설정을 추가했다. unset이면 둘 다
  `KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED`를 따른다.
- **CHANGED**: DB 없는 부팅 검증에서 `features_routes_enabled=False`를 주면
  `/features/*`뿐 아니라 DB 의존 `/admin/*`, `/ops/*`, `/ops/dagster/*` 라우터도 함께
  mount하지 않는다. 필요하면 admin/ops flag를 명시해 별도로 다시 열 수 있다.
- **DOCS**: T-RV-27(admin API bind/노출)은 production 레벨 hardening 전까지 구현하지
  않고 deferred/skip으로 문서 추적한다.

### Admin API — Error envelope (2026-06-04)

- **CHANGED**: admin API의 `HTTPException`과 request validation error 응답을
  `{error:{code,message,details,request_id}}` envelope로 통일했다.
- **CHANGED**: `X-Request-ID` 요청 헤더가 있으면 같은 값을 응답 헤더와 envelope에
  되돌리고, 없으면 UUID를 생성한다.
- **TEST**: 공통 error envelope unit test를 추가하고, 기존 router error assertion을
  `detail`에서 `error.message` 기준으로 교정했다.

### Admin API — Offline upload 크기 상한 (2026-06-04)

- **NEW**: `KOR_TRAVEL_MAP_OFFLINE_UPLOAD_MAX_BYTES` 설정을 추가했다. 기본값은
  `104857600` bytes(100 MiB)다.
- **CHANGED**: `POST /admin/offline-uploads`는 설정 상한을 초과한 파일을 `413`으로
  거절한다. `Content-Length` 선차단과 `UploadFile.read(max_bytes + 1)` bounded read를
  함께 적용해 무제한 메모리 read를 막는다.
- **TEST**: oversize upload가 객체 저장소/DB 경로로 내려가지 않는 router unit
  regression test와 settings env override test를 추가했다.

### Ops — Batch DAG + consistency gate (2026-06-04)

- **NEW**: `kortravelmap.infra.batch_dag.run_batch_dag_consistency_gate`와
  `AsyncKorTravelMapClient.run_batch_dag_consistency_gate(...)`를 추가했다.
- **NEW**: Dagster `full_load_batch_consistency_gate` job을 추가했다. 기존 실제 source
  load import job을 root batch에 연결하고, child `done` 확인 뒤 consistency gate를
  실행한다.
- **CHANGED**: `severity_max=ERROR`이면 `mv_refresh`를 차단하고 root/gate import job을
  `failed`로 기록한다. OK/WARN이면 `mv_refresh` job을 기록하며, 현재 MV 카탈로그가
  없으면 `skipped:no_materialized_views`로 남긴다.
- **TEST**: unit coverage `800 passed` / `80.59%`, Dagster package `17 passed`, PostGIS
  integration `14 passed`, repo-wide `ruff`/`mypy`/import-linter를 확인했다.

### Ops — admin stack runner 안정화 (2026-06-04)

- **FIX**: `scripts/run-admin-stack.sh`가 시작 전 `alembic upgrade head`를 실행하고,
  API/frontend/Dagster를 `setsid` detached process로 기동하도록 수정했다.
- **FIX**: frontend wrapper PID가 먼저 종료되어도 URL readiness가 성공하면 정상 기동으로
  판단하도록 readiness 검사를 보정했다.

### Ops — import_jobs batch DAG 컬럼 (2026-06-04)

- **NEW**: `ops.import_jobs`에 `load_batch_id`와 `parent_job_id` self-FK를 추가했다.
  T-200 full-load root/child/gate job을 같은 batch로 묶기 위한 선행 스키마다.
- **NEW**: `/ops/import-jobs` 목록/상세 응답에 `load_batch_id`와 `parent_job_id`를
  포함하고, 두 UUID query filter를 추가했다.
- **CHANGED**: admin frontend `/ops/import-jobs` 목록에서 batch/parent id를 표시하고
  필터링할 수 있다.
- **TEST**: unit coverage `792 passed` / `80.56%`, admin package `132 passed`, Dagster
  package `15 passed`, migrated PostGIS integration `13 passed`, `ruff`/`mypy`/
  import-linter, OpenAPI drift, frontend `type-check`/`lint`/`build`, React Doctor를
  확인했다.

### Admin UI — Offline CSV/TSV validation + kor-travel-geo bjd 보강 (2026-06-04)

- **NEW**: `GET /admin/offline-uploads/{upload_id}/preview`,
  `POST /admin/offline-uploads/{upload_id}/validate`,
  `GET /admin/offline-uploads/{upload_id}/validation`을 추가했다.
- **NEW**: CSV/TSV offline upload column mapping, header/sample preview, validation
  issue, validation job payload 저장, load 전 validation gate를 추가했다.
- **NEW**: admin frontend `/admin/offline-uploads`에 CSV/TSV mapping/preview/validation
  panel을 추가했다.
- **CHANGED**: `bjd_code`가 없는 offline/provider 행은 kor-travel-geo REST v2 geocode 또는
  reverse 결과로 법정동코드를 보강한다. resolver가 없거나 결과가 없으면 validation
  issue로 남긴다.
- **CHANGED**: Dagster `offline_upload_load`가 validation job의 column mapping을
  재사용해 CSV/TSV 원본을 PostGIS에 적재한다.
- **FIX**: integration shared testcontainer DB에서 PostGIS extension을 `DROP ... CASCADE`
  해 `feature.features` geometry 컬럼을 지우던 fixture 순서 의존 문제를 수정했다.
- **DOCS**: ADR-045 전체점검 task를 `T-212a`~`T-212e`로 분리하고 실행 계획 문서를
  추가했다.
- **TEST**: unit-only coverage `792 passed` / `80.54%`, integration/admin/dagster
  `293 passed`, targeted backend/provider/router unit `114 passed`, offline upload
  PostGIS integration `4 passed`, repo-wide `ruff`/`mypy`/import-linter, frontend
  `type-check`/`lint`/`build`, React Doctor, admin/ops Playwright e2e `6 passed`,
  OpenAPI drift check를 확인했다.

### Admin UI — Offline uploads API/UI (2026-06-03)

- **NEW**: `POST /admin/offline-uploads`, `GET /admin/offline-uploads`,
  `GET /admin/offline-uploads/{upload_id}`,
  `POST /admin/offline-uploads/{upload_id}/load`를 추가했다.
- **NEW**: admin frontend `/admin/offline-uploads` 화면을 추가했다. JSON/JSONL
  `FeatureBundle` 파일 업로드, state/provider/dataset 필터, 상세 panel, Dagster load
  실행을 지원한다.
- **CHANGED**: `infra.offline_upload_repo`가 API가 생성한 `upload_id`를 받을 수 있고,
  `created_at DESC, upload_id DESC` keyset 목록을 제공한다.
- **CHANGED**: frontend 공통 API client에 `postFormData()`를 추가했다.
- **TEST**: offline upload router unit test, migrated PostGIS list/load integration,
  frontend type-check/lint/build, React Doctor, OpenAPI admin/user drift check를
  수행했다.

### 운영 — RustFS offline upload store wiring (2026-06-03)

- **NEW**: `kortravelmap.infra.file_store.S3ObjectStore`를 추가했다. boto3 호환
  S3 client를 async wrapper로 감싸고, 읽기/쓰기 실패는 `FileStoreError`로 표준화한다.
- **NEW**: `kortravelmap.dagster.resources.offline_upload_store_resource`를 추가했다.
  Dagster `offline_upload_load` job이 `KOR_TRAVEL_MAP_OBJECT_STORE_*`와
  `KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET` 설정으로 RustFS/S3 호환 bucket을 읽는다.
- **CHANGED**: `KorTravelMapSettings`와 `.env.example`의 object store field/env 이름을
  정렬했다. offline upload bucket 기본값은 `krtour-uploads`다.
- **CHANGED**: Docker compose stack에 RustFS API `12101`, console `12105`,
  `rustfs-init` bucket 생성 경로를 추가했다.
- **TEST**: S3 store/resource/definitions/offline upload Dagster unit test,
  `docker compose config --quiet`, 실제 Docker RustFS put/get smoke를 추가했다.

### 운영 — Dagster offline upload load job (2026-06-03)

- **NEW**: `ops.offline_uploads` 테이블과 repository를 추가했다. RustFS 등 객체
  저장소의 원본 파일 메타데이터를 보존하고 validation/load `import_jobs`와 연결한다.
- **NEW**: `AsyncKorTravelMapClient.run_offline_upload_load_job()`을 추가했다. 업로드
  원본 파일을 store resource에서 읽어 size/checksum을 검증하고 JSON/JSONL
  `FeatureBundle`로 파싱한 뒤 PostGIS에 적재한다.
- **NEW**: `offline_upload_load` Dagster job을 추가했다. `upload_id` config와
  `offline_upload_store` resource를 받아 수동 실행한다.
- **TEST**: parser/Dagster unit test와 migrated PostGIS 통합 테스트를 추가했다.
  통합 테스트는 성공 적재와 checksum 실패 시 `import_jobs=failed` /
  `offline_uploads=load_failed` 전이를 검증한다.

### 운영 — Dagster consistency/dedup refresh job (2026-06-03)

- **NEW**: `consistency_dedup_refresh` Dagster job을 추가했다. DB에 적재된
  provider/dataset scope를 pair/sibling 방식으로 다시 읽어 dedup 후보 큐를 갱신한 뒤
  F1~F4 consistency report를 저장한다.
- **NEW**: `AsyncKorTravelMapClient`에 DB 기준 dedup pair/sibling refresh와 consistency
  report 실행 메서드를 추가했다.
- **NEW**: `consistency_dedup_refresh_daily_schedule`을 추가했다. KST `45 5 * * *`,
  기본 status는 `STOPPED`다.
- **TEST**: Dagster job config/metadata unit test와 PostGIS client 경로 integration
  test를 추가했다.

### Admin UI — 최신 운영 화면 구현 (2026-06-03)

- **NEW**: admin frontend에 전역 `AdminShell` navigation, 공통 `StatusBadge`, format
  helper를 추가했다.
- **NEW**: `/ops/import-jobs`, `/ops/consistency`, `/admin/dedup-review`,
  `/admin/feature-update-requests`, `/admin/poi-cache-targets` 화면을 추가했다.
- **CHANGED**: 홈(`/`)을 feature/import job/dedup/integrity issue/Dagster 상태를
  보는 운영 dashboard로 교체했다.
- **CHANGED**: `/admin/dagster`는 Dagster webserver embed와 자체 summary UI를 함께
  제공하며 schedules/sensors 정보를 표시한다.
- **CHANGED**: `/features` header에 jobs/update/target/dedup/Dagster 운영 화면으로
  이동하는 quick link를 추가했다.
- **CHANGED**: `scripts/stop-fixed-ports.sh`가 WSL 일반 PID, WSL root listener,
  Windows `node.exe`/`wslrelay.exe` listener를 감지해 12301/12305/12302 stale 포트를
  정리한다.
- **CHANGED**: `scripts/load-env.sh`의 기본 CORS origin에 WSL IP 기반
  `http://<WSL-IP>:12305`를 포함해, Windows localhost relay가 죽었을 때도
  `E2E_BASE_URL` WSL IP fallback으로 브라우저 검증이 가능하게 했다.
- **CHANGED**: `kortravelmap.api.app`이 설정된 CORS origin에 대해 응답과 preflight
  헤더를 한 번 더 보강해 WSL IP fallback 경로에서도 frontend fetch가 막히지 않게 했다.
- **TEST**: Playwright e2e를 새 home dashboard와 신규 admin/ops route smoke 기준으로
  갱신했다.

### Admin UI — 최신화 선행 API 계약 (2026-06-03)

- **NEW**: `docs/admin-ui-modernization-gap-audit.md`를 추가해 최신 admin UI 요구사항과
  실제 REST/Dagster/frontend 구현 차이를 route별로 정리했다.
- **NEW**: admin frontend에 `/ops/import-jobs`, `/ops/metrics`,
  `/ops/consistency/*`, `/admin/dedup-review`, `/admin/feature-update-requests`,
  `/admin/poi-cache-targets`, `/features/nearby/by-target` typed hook module을
  추가했다.
- **CHANGED**: frontend 공통 API client가 `GET/POST/PUT/PATCH/DELETE` JSON helper와
  query-string builder를 제공한다.
- **CHANGED**: frontend `npm test`가 Playwright e2e spec을 Vitest unit test로
  잘못 수집하지 않도록 `e2e/**`를 제외한다. Playwright는 `npm run e2e`로 실행한다.
- **CHANGED**: 문서의 과거 `/admin/import-jobs` 기본 API 표기를 현재 정본
  `/ops/import-jobs`로 정리했다.

### 운영 — Dagster provider schedules (2026-06-03)

- **NEW**: `packages/kor-travel-map-dagster`에 Feature 적재 asset 9개의 KST schedule과
  asset job을 등록했다.
- **CHANGED**: 모든 provider schedule은 `execution_timezone="Asia/Seoul"`을 사용하고,
  외부 API 호출이 몰리지 않도록 분/요일을 분산한다. 기본 status는 운영자가 명시적으로
  켜기 전까지 `STOPPED`다.
- **TEST**: Dagster `Definitions`에 schedule/job이 등록되고 cron/timezone/tag가
  일치하는지 검증하는 smoke test를 추가했다.

### 운영 — OpenAPI admin/user 이원화 (2026-06-03)

- **NEW**: `packages/kor-travel-map-api/openapi.user.json`을 추가했다. TripMate/user
  client가 사용하는 `/features/*`, `/tripmate/features/batch`,
  `/admin/feature-update-requests` 일부 method만 포함한다.
- **CHANGED**: `packages/kor-travel-map-api/scripts/export_openapi.py`에
  `--profile admin|user|all`과 `--user-output`을 추가했다. 기본 admin export는 기존
  `openapi.json` 경로/동작을 유지한다.
- **CHANGED**: `.github/workflows/openapi.yml` drift gate가
  `--profile all --check`로 admin/user OpenAPI 산출물을 함께 검증한다.
- **TEST**: user profile route filtering, method filtering, schema pruning을 검증하는
  export script unit test를 추가했다.

### 운영 — TripMate/public feature read API (2026-06-03)

- **NEW**: `kor-travel-map-admin`에 `GET /features/in-bounds`,
  `GET /features/search`, `POST /tripmate/features/batch`를 추가했다.
- **CHANGED**: `GET /features/{feature_id}`는 public envelope
  `{data, meta.duration_ms}` 응답으로 전환하고 `updated_at`을 포함한다. 기존
  admin frontend 상세 호출은 envelope를 풀어 읽도록 갱신했다.
- **CHANGED**: `feature_repo.features_in_bbox`에 category filter를 추가하고,
  `get_feature_rows_by_ids`, `search_features`를 추가했다. 검색은 `pg_trgm`
  `%` 연산자와 transaction-local similarity threshold를 사용한다.
- **CHANGED**: `packages/kor-travel-map-api/openapi.json`을 T-207e endpoint 기준으로
  갱신했다.
- **TEST**: `/features`/`/tripmate` 라우터 unit test, feature repo cursor/validation
  unit test, PostGIS batch/search/bbox 통합 테스트, frontend lint/type-check를
  추가·갱신했다.

### 운영 — `/ops/*` consistency/jobs/metrics API (2026-06-03)

- **NEW**: `kor-travel-map-admin`에 `GET /ops/metrics`, `GET /ops/import-jobs`,
  `GET /ops/import-jobs/{job_id}`, `GET /ops/consistency/reports`,
  `GET /ops/consistency/issues`를 추가했다.
- **NEW**: `infra.ops_repo`를 추가했다. `ops.import_jobs`,
  `ops.feature_consistency_reports`, `ops.data_integrity_violations`를 read-only
  keyset cursor로 조회하고, 열린 issue 집계를 제공한다.
- **CHANGED**: `packages/kor-travel-map-api/openapi.json`을 T-207d endpoint 기준으로
  갱신했다.
- **TEST**: `/ops` 라우터 unit test와 PostGIS ops repository 통합 테스트를 추가했다.

### 운영 — Admin feature review/deactivate API (2026-06-03)

- **NEW**: `kor-travel-map-admin`에 `GET /admin/features`,
  `POST /admin/features/{feature_id}/deactivate`, `GET/PATCH /admin/dedup-review`를
  추가했다.
- **NEW**: `alembic 0010`으로 `ops.feature_overrides`를 추가했다. active
  `field_path='status'` override는 `prevent_provider_reactivation` 플래그로 provider
  재적재가 운영자 비활성화를 되살리지 못하게 한다.
- **CHANGED**: `feature_repo.upsert_feature`가 active status override가 있는 feature의
  status/deleted_at을 provider payload로 덮지 않는다.
- **TEST**: admin feature/dedup 라우터 unit test, PostGIS deactivate/override/upsert
  통합 테스트, OpenAPI export를 추가했다.

### 운영 — Dagster feature update sensor (2026-06-03)

- **NEW**: `kor-travel-map-dagster`에 `feature_update_request_queue_sensor`와
  `feature_update_request_worker` job을 추가했다. sensor는 queued request를 상태 변경
  없이 peek한 뒤 request id를 Dagster `RunRequest` config/tag로 전달한다.
- **NEW**: `feature_update_request_failure_sensor`를 추가했다. worker run 실패 시
  request/import job 실패 전이를 보강하고, 선택 notifier resource로 알림 payload를
  전달한다.
- **CHANGED**: `AsyncKorTravelMapClient`와 `infra.feature_update_repo`에
  `peek_next_update_request`를 추가하고, client에 `fail_update_request`를 추가했다.
- **TEST**: Dagster sensor/job unit test와 feature update repo/client PostGIS 통합
  테스트를 추가했다.

### 운영 — POI/cache target admin API (2026-06-03)

- **NEW**: `kor-travel-map-admin`에 `PUT/GET/DELETE /admin/poi-cache-targets`와
  `GET /features/nearby/by-target`를 추가했다. 외부 앱 POI는
  `external_system + target_key + 좌표 + radius`로 식별한다.
- **NEW**: `feature_repo.features_nearby_poi_cache_target`를 추가했다. target의
  `coord_5179` 기준 `ST_DWithin` 거리 조회, kind/category/status/provider 필터,
  `distance`/`name`/`last_updated_at` keyset cursor를 지원한다.
- **TEST**: admin 라우터 unit test와 PostGIS 주변 feature/cursor 통합 테스트를
  추가하고 OpenAPI export를 갱신했다.

### 운영 — Feature update admin API (2026-06-03)

- **NEW**: `kor-travel-map-admin`에 `POST/GET /admin/feature-update-requests`,
  `GET /admin/feature-update-requests/{request_id}`,
  `POST /admin/feature-update-requests/{request_id}/cancel`,
  `POST /admin/feature-update-requests/{request_id}/run-now` 라우터를 추가했다.
- **CHANGED**: `list_update_requests`와 `AsyncKorTravelMapClient.list_update_requests`가
  `scope_type`, `provider`, `dataset_key`, `created_from`, `created_to` 필터를 받는다.
- **TEST**: admin 라우터 unit test, OpenAPI export 갱신, provider/dataset JSONB 필터
  PostGIS 통합 테스트를 추가했다.

### 운영 — Feature update request 실행 본체 (2026-06-03)

- **NEW**: `infra.feature_update_executor`를 추가했다. queued request claim,
  실행 시점 scope 재해석, provider/dataset 실행 계획, provider refresh policy 필터,
  target link 재계산, request/import job terminal 전이를 한 흐름으로 묶는다.
- **NEW**: `cache_target_keys` scope resolver를 추가했다. active POI/cache target
  주변 feature를 PostGIS로 계산하고 missing/deleted/disabled key를 `matched_scope`에
  기록한다.
- **CHANGED**: `AsyncKorTravelMapClient`에
  `execute_next_feature_update_request`와 `execute_feature_update_request`를 추가했다.
  실제 provider 호출은 runner 주입형이며 Dagster sensor 연결은 후속 T-208e에서
  진행한다.
- **TEST**: target 기반 request가 runner를 통해 feature를 DB 적재하고
  `ops.poi_cache_target_feature_links`와 target refresh 타임스탬프를 갱신하는 PostGIS
  통합 테스트를 추가했다.

### 운영 — Phase 2 ops 스키마 (2026-06-03)

- **NEW**: `ops.data_integrity_violations`, `ops.poi_cache_targets`,
  `ops.poi_cache_target_feature_links`, `ops.provider_refresh_policies` 테이블을
  `alembic 0009`로 추가했다.
- **NEW**: `infra.integrity_violation_repo`, `infra.poi_cache_target_repo`,
  `infra.provider_refresh_policy_repo`를 추가했다. 후속 admin API/Dagster 실행 본체가
  공유할 raw SQL repository 표면이다.
- **TEST**: Phase 2 ops schema/repository PostGIS 통합 테스트를 추가했다.

### 운영 — Feature update client 표면 (2026-06-03)

- **NEW**: `AsyncKorTravelMapClient`에
  `enqueue_feature_update_request`, `get_update_request`, `list_update_requests`,
  `cancel_update_request`를 추가했다. Dry-run은 DB write 없이 preview를 반환하고,
  실제 enqueue/cancel은 client가 transaction 경계를 소유한다.
- **CHANGED**: `from kortravelmap import AsyncKorTravelMapClient` top-level import를 실제
  public export로 맞추고, TripMate 직접 import 설명을 ADR-045 OpenAPI 운영 모델
  기준으로 정정했다.
- **DOCS**: RustFS 로컬 표준 포트를 S3 API `12101`, console `12105`로 정리했다.

### 운영 — Feature update request 큐 repository (2026-06-03)

- **NEW**: `infra.feature_update_repo`를 추가했다. Dry-run preview, request enqueue,
  priority 기반 claim, start/finish/cancel, 단건 조회, keyset cursor 목록 조회를
  지원한다.
- **CHANGED**: 실제 실행 request 생성 시 `ops.import_jobs` row를 같은 transaction에
  만들고, claim/start/finish/cancel 상태 전이를 request와 import job에 함께 반영한다.
- **DOCS**: kor-travel-geo REST API 로컬 포트 기준을 `http://127.0.0.1:12201`로 정정했다.

### 운영 — Feature update scope resolver (2026-06-03)

- **NEW**: `infra.scope_repo`를 추가했다. `feature_ids`, `center_radius`, `bbox`,
  `sigungu_by_radius`, `provider_dataset` scope를 feature 집합과 `matched_scope`
  payload로 해석한다.
- **CHANGED**: `sigungu_by_radius` 해석은 `infra`가 kor-travel-geo를 직접 import하지 않고
  주입받은 async resolver의 5자리 `sigungu_code` 결과를 사용한다.

### 운영 — Feature update request 큐 스키마 (2026-06-03)

- **NEW**: `ops.feature_update_requests` 테이블과 `FeatureUpdateRequestRow` 매핑을
  추가했다. Admin/OpenAPI feature update request를 `ops.import_jobs`와 Dagster run에
  연결하기 위한 기반 스키마다.
- **DOCS**: `sigungu_by_radius` scope 설명을 kor-travel-geo REST v2
  `/v2/regions/within-radius` 기준으로 정리했다. kor-travel-map 내부에 행정경계 테이블을
  만들지 않는다.

### Admin UI — Dagster 운영 화면 (2026-06-02)

- **NEW**: backend `GET /ops/dagster/summary`를 추가했다. Dagster GraphQL에서
  version, code location, asset group, schedule/sensor, 최근 run 요약을 읽어 admin
  UI용 DTO로 정규화한다.
- **NEW**: frontend `/admin/dagster` 화면을 추가했다. 자체 운영 요약 카드/asset
  group/recent run 표와 Dagster webserver embed를 한 화면에서 제공한다.
- **CHANGED**: 홈 화면에서 Dagster 상태 요약과 `/admin/dagster` 진입 링크를 표시한다.
- **CHANGED**: `GET /ops/dagster/summary`는 성공 시 Dagster `setNuxSeen`을
  best-effort로 호출해 embedded 관리 화면의 로컬 첫 실행 모달을 접는다.
- **CHANGED**: 로컬/Docker Dagster 실행 기본값에 `DAGSTER_DISABLE_TELEMETRY=yes`를
  추가해 embedded 관리 화면의 외부 telemetry 동작을 줄인다.

### 운영 — Docker 이미지 + 고정 포트 (2026-06-02)

- **NEW**: `docker-compose.yml`과 `docker/{api,frontend,dagster}.Dockerfile`을 추가했다.
  독립 PostGIS, API, admin UI, Dagster를 같은 compose에서 기동한다.
- **CHANGED**: Docker API 컨테이너는 `.env`의 로컬 Dagster URL 대신
  `KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL` 기본값(`http://dagster:12302`)을 내부
  `KOR_TRAVEL_MAP_API_DAGSTER_URL`로 사용한다.
- **CHANGED**: 로컬/standalone 고정 포트를 API `12301`, admin UI `12305`, Dagster
  `12302`으로 표준화했다.
- **NEW**: `.env`의 provider service key를 `KOR_TRAVEL_MAP_API_*`/`NEXT_PUBLIC_*`
  환경변수로 매핑하는 `scripts/load-env.sh`와 포트 종료/로컬 stack/Docker 기동
  스크립트를 추가했다.

### Admin UI — frontend stack 전환 + geocoding admin 표면 제거 (2026-06-02)

- **CHANGED**: `kor-travel-map-admin` frontend를 문서화된 stack 기준으로 재정렬했다.
  Next.js 16 + React 19 + TanStack Query + Zustand + Zod + React Hook Form +
  shadcn/ui + `maplibre-vworld-js`를 기준으로 홈/ETL preview/Feature 지도 화면을
  구성한다.
- **REMOVED**: geocoding 전용 admin/debug 라우터, frontend `/geocoding` 화면,
  관련 e2e/router/live 테스트를 제거했다. geocoding 자체 디버깅은
  `kor-travel-geo` 프로젝트 책임으로 둔다.
- **CHANGED**: `packages/kor-travel-map-api/openapi.json`에서 `/debug/geocoding/*` 경로와
  `GeocodingHealthResponse` schema를 제거했다.
- **DOCS**: React Doctor 실행/검토 기준에 맞춰 `doctor` script와
  `doctor.config.json`을 추가하고, 실제 경고를 검토해 앱 metadata, MapLibre cleanup,
  정렬/폼 오류 표시 코드를 개선했다.

### 문서 — ADR-046 정본 전환 + kor-travel-geo v2 주소 정책 (2026-06-02)

- ADR-045 이행 시 legacy 호환 shim을 남기지 않고 `kor-travel-map-admin`, 독립 DB,
  독립 Dagster, OpenAPI 연동을 정본으로 삼는 ADR-046을 추가했다.
- provider 주소/좌표 정본을 kor-travel-geo REST v2 `POST /v2/reverse`,
  `POST /v2/geocode` 결과로 통일하고, provider 원문 주소는 provenance로 보존하는
  정책을 문서화했다.
- 주소/좌표 매칭 실패, 결측, reverse/geocode 실패를 admin UI `/admin/issues`에서
  재시도·수동 수정·kor-travel-geo 주소 채택·ignore/reopen 할 수 있도록 OpenAPI/UI
  사양을 보강했다.

### 문서 — ADR-045 독립 프로그램/OpenAPI 전환 (2026-06-01)

- kor-travel-map 운영 모델을 Docker 독립 프로그램 + 독립 PostgreSQL/PostGIS DB + 독립
  Dagster + TripMate OpenAPI 연동으로 전환하는 ADR-045를 추가했다.
- Admin 우선 OpenAPI, Dagster feature update request, POI/cache target 기반 주변
  feature 캐시 갱신, provider refresh policy/rate limit, frontend React Doctor 필수
  검증 사양을 문서화했다.

### Sprint 4 — 운영 CLI (2026-06-01~)

- **CHANGED**: coverage 게이트 `fail_under` 75 → **80** 상향 (ADR-032 Sprint 4 목표
  도달, 실측 94.12%). 모든 tier 충족(core/infra/providers/전체 ≥ 목표). Sprint 4b 종료.
- **NEW**: Place 전화번호 보강(`kortravelmap.enrichment`, Sprint 4b 백그라운드 시작) —
  전화번호 없는 MOIS place 후보 발굴(`find_place_phone_candidates`) + 외부 lookup
  결과 보강(`apply_place_phone_enrichment` — `detail.phones` 정규화·dedup·max3 갱신 +
  `source_links(role='enrichment')` 이력). 외부 API(kakao/naver/google) 호출은 호출자
  책임(ADR-006 — 결과 주입). `AsyncKorTravelMapClient.find_place_phone_candidates` /
  `enrich_place_phone` + `infra.feature_repo.{find_place_features_without_phone,
  set_feature_phones}`.
- **NEW**: ADR-033 **F4** 정합성 검사 — `infra.consistency`에 dedup 백로그 baseline
  체크 추가. `ops.dedup_review_queue` 미해소(pending) 수가
  `DEDUP_PENDING_WARN_THRESHOLD`(provisional 1000, `run_consistency_checks(...,
  dedup_pending_threshold=N)`로 override) 초과 시 severity=**WARN**(observe-only —
  적재 차단 없음, Phase 1). F1~F3(행별 정적 SQL)과 달리 임계 초과 집계 케이스.
- **NEW**: dedup 운영 FP 측정 — `infra.status_repo.dedup_fp_stats`(dedup_review_queue
  status별 카운트 → confirmed=merged+accepted / FP=rejected / precision / fp_rate;
  ignored·pending 제외) + `ktmctl status` 출력에 `dedup FP(운영)` 라인 추가.
  운영자가 `dedup-merge`/reject로 큐를 해소하면 실 FP율이 자동 집계된다(검토 완료
  후보 0이면 "검토 완료 후보 없음"). ADR-016 dedup-fp 리포트의 후속 운영 측정 도구.
- **NEW**: MOIS Step D on-demand 상세 — debug-ui `GET /debug/mois-license/{license_id}`.
  적재된 MOIS feature의 원본 provider payload(`source_records.raw_data`) + feature
  core를 조립해 반환하고 프로세스 내 TTL 캐시에 담는다(**캐시만, DB write 없음**).
  `license_id` = `source_entity_id`(`{slug}::{mng_no}`). 신규
  `infra.get_primary_source_detail`(읽기 전용 단건 조회) + `routers/mois_detail`.
  미적재 시 404. `features_routes_enabled` + `debug_routes_enabled` gate.
- **NEW**: MOIS Step C 폐업/취소 처리 — `ktmctl import mois <file> --mode closed
  --cursor <값>`. provider가 `closed`/`cancelled`로 통지한 인허가 record의 대응
  feature를 `status='inactive'`+`deleted_at`으로 전환한다(ADR-017 — place는 무기한
  유지, status만 inactive; 새 feature 생성 없음). `infra.inactivate_features_by_
  source_entity_ids`(soft-delete inverse) + `mois.close_mois_license_features` /
  `run_mois_license_closed_job`(advisory lock + import_jobs + closed dataset cursor)
  + `AsyncKorTravelMapClient` 메서드. `--cursor` 미지정 시 exit 2.
- **NEW**: MOIS Step B 증분 적재 — `ktmctl import mois <file> --mode incremental
  --cursor <값>`. 변경분만 upsert(snapshot prune 없음)하고 성공 시
  `provider_sync.provider_sync_state`의 cursor(`{"last_modified_date": …}`)를 전진
  시킨다(`--sync-scope`로 scope 분리). 신규 `infra/sync_state_repo`
  (get/record_success/record_failure) + `mois.run_mois_license_incremental_job`
  (advisory lock + import_jobs + cursor) + `AsyncKorTravelMapClient` 메서드. `--cursor`
  미지정 시 exit 2. (Step C 폐업 처리는 별도 — 증분은 사라진 record를 비활성화하지
  않는다.)
- **NEW**: `ktmctl dedup-merge <review_key>` — dedup 검토 큐 후보 1쌍 수동 병합
  (ADR-016). master를 `select_master`(좌표 보유 → `updated_at` 최신 → 원천 우선순위
  행안부>TourAPI>사용자)로 자동 선정하고, loser의 `source_links`를 master로 재지정
  (충돌 키는 drop), loser feature를 soft-delete(`status='deleted'`), 신규
  `ops.feature_merge_history`(alembic 0007)에 이력 기록, 큐 행을 `merged` 전이한다.
  `dedup-merge:{review_key}` advisory lock으로 중복 실행 차단(ADR-039), 미획득 시
  skip(exit 3); 미존재/이미 검토된 review_key는 exit 2. `--merged-by`/`--reason`
  옵션. (SPRINT-4 §2.8의 예시 인자 `<feature_id>`는 후보쌍을 유일 식별하는
  `<review_key>`로 구체화.)
- **NEW**: `ktmctl import mois <records-file>` — MOIS 인허가 Step A bulk 적재
  CLI 명령. provider가 export한 provider-neutral **NDJSON snapshot**(한 줄당 JSON
  object)을 record source로 읽어(ADR-006 — provider 라이브러리 미import)
  `run_mois_license_bulk_job`으로 적재한다. `import:python-mois-api:<dataset>`
  advisory lock 단일 워커 직렬화(ADR-039) + `import_jobs` 추적(ADR-011); 다른
  워커가 적재 중이면 skip(exit 3). `--geocoder-url`로 좌표 → bjd_code 역지오코딩
  보강(kor-travel-geo REST) 선택. `--dataset-key`/`--batch-size`/`--source-checksum`
  옵션. (`cli/records.py` NDJSON 리더 + `cli/main.py` import 서브명령.)
### Sprint 3 — DB 적재 오케스트레이션 + dedup + geocoding REST + e2e (2026-05-29~30)

- **PR#115 — PR review 누락 보강 + 문서 정합성 sweep**:
  2026-05-28 이후 PR #45~#114를 재조회하고 review submission이 없던 PR에
  한국어 사후 상세 리뷰를 등록. 당시 문서에서는 구 geocoding REST address endpoint와
  서비스 메타 버전 2.0 표현을 분리하고, accepted ADR을 proposed로 부르던 문구와
  `PlaceCoordinate` 잔존 예시, `docs/tasks.md` 현재 상태 drift를 정정.
- **PR#114 — kor-travel-geo 최신 로컬 포트 정합 + 라이브 검증 보강**:
  `kor-travel-geo` 최신 로컬 정책(`docs/ports.md`)에 맞춰 debug-ui
  geocoding 기본 base URL과 live 테스트 기본값을 `http://127.0.0.1:8888`로
  고정. frontend 의존도 로컬 최신 `maplibre-vworld-js#v0.1.2` + Next.js 16
  기준으로 올리고 `next lint` 제거에 맞춰 ESLint CLI flat config를 추가.
  WSL 시스템 `libgdal 3.8.4`와 맞도록 Python `gdal` binding을
  `==3.8.4`로 고정. `.env.example`/README/debug-ui/address-geocoding 문서를
  함께 갱신.
- **PR#93 — frontend CI 게이트** (`.github/workflows/frontend.yml`): Node 20 +
  workspace `npm install` + `tsc --noEmit` + `next build` (paths 필터). PR#92
  회고에 따라 잠복 syntax/타입 오류를 PR 머지 전에 차단.
- **PR#92 — npm workspace 루트 + frontend WSL 기동 + Windows Playwright e2e 7/7** (#117):
  루트 `package.json`(workspaces: map-marker-react + debug-ui/frontend) +
  frontend `workspace:*` → npm 호환 `*`. `npm install`(419 pkgs, github
  `maplibre-vworld#v0.1.0` 포함) 성공. WSL backend(:8087) + frontend(:8610)
  기동 + Windows `npx playwright test` → home 4 + etl 3 = 7/7 통과 (실 backend
  연동). 검출+수정: `etl/page.tsx` JSDoc 주석의 `*/`가 블록 주석을 조기 종료해
  PR#44부터 잠복했던 빌드 버그 (frontend 미컴파일 환경에서 미검출).
- **PR#91 — Playwright e2e 스위트 + backend 라이브 검증 리포트** (#117):
  `frontend/playwright.config.ts` + `e2e/home.spec.ts`/`etl.spec.ts` (실
  backend `/debug/health`·`/debug/version`·`/debug/etl/*` 연동, role/heading
  + native select nth 선택자). `docs/reports/debug-ui-e2e-2026-05-29.md`에
  backend 5경로 실 HTTP 통과 증거 + 사람용 런북.
- **PR#90 — geocoding python API → REST address API 전환** (#123, 이후 v2로 supersede):
  `kortravelmap.geocoding`을 in-process `AsyncAddressClient` 가정에서
  **kor-travel-geo REST address API**로 재작성. structural Protocol을 실제
  `ReverseResponse`/`GeocodeResponse`/`AddressStructure`(vworld
  `level4LC=bjd_cd` 등)/`GeocodeExtension`으로 교체. 순수 변환
  `reverse_response_to_address` / `geocode_response_to_coordinate` + 새
  `KorTravelGeoRestClient`(httpx 주입, TYPE_CHECKING-only import — 메인 패키지
  런타임 httpx 의존 X). 소비자 계약(`ReverseGeocoder` 등) 유지 →
  provider 무영향. `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL` 설정 추가.
- **PR#89 — `AsyncKorTravelMapClient` 적재/dedup 오케스트레이션** (#122):
  placeholder였던 라이브러리 진입점에 transaction 소유 메서드 구현 —
  `load_feature_bundles`(`infra.load_bundles` 래핑), `sync_dedup_candidates`
  (`core.dedup` + `infra.enqueue_dedup_candidates`), 읽기
  (`get_feature`/`features_in_bounds`/`pending_dedup_reviews`). engine 수명은
  호출자 소유. unit 2 + integration 3 (testcontainers, teardown TRUNCATE).
- **PR#88 — `ops.dedup_review_queue` 적재 + `infra/dedup_repo.py`** (#122):
  alembic 0005 (`ops.dedup_review_queue` — UUID PK, FK→features CASCADE,
  `NUMERIC(5,2)` 0~100 score, `ck_dedup_scores`/`ck_dedup_status`,
  `idx_dedup_status_score`). 점수 0.0~1.0 → 0~100 변환,
  검토완료 행 보존 upsert(`DO UPDATE ... WHERE status='pending'`).
- **PR#87 — `core/dedup.py` cross-provider 중복 후보** (#121):
  `find_dedup_candidates(left, right, *, include_auto_merge)` 순수 함수 —
  `score_pair`(ADR-016)로 cross-score, `KEEP_SEPARATE` 제외, score 내림차순.
  `DedupInput` Protocol(`Feature`가 그대로 만족) + `DedupCandidate` frozen
  dataclass. unit 6.
- **PR#86 — `geometry_area_square_meters` 측지 면적 + krheritage AREA 보강** (#120):
  `pyproj.Geod(ellps='WGS84').geometry_area_perimeter` 측지 면적,
  krheritage AREA 변환기가 `AreaDetail.area_square_meters` 채움 + 단위 4건.

### Sprint 2 prep (2026-05-26, PR#28+)

- **PR#29 — `core/scoring.py` (ADR-016 Record Linkage) + `core/providers.py`**:
  Sprint 2 첫 provider 적재 전 dedup scoring + provider 이름 정규화 인프라.
  - `core/providers.py` — `CANONICAL_PROVIDER_NAMES` 18종 (모든 형제 provider
    + data.go.kr-standard + 외부 보강 3종) + `PROVIDER_ALIASES` 24종 (ADR-024
    krmois→mois 포함) + `normalize_provider_name` (raise on unknown, silent
    fallback 금지) + `is_known_provider` (lenient bool).
  - `core/scoring.py` (ADR-016 SPEC V8 D-14):
    - 가중치 상수: `WEIGHT_NAME=0.45`/`WEIGHT_SPATIAL=0.35`/`WEIGHT_CATEGORY=0.20`
    - 임계값 상수: `THRESHOLD_AUTO=0.85`/`THRESHOLD_MANUAL=0.65`/`SPATIAL_DECAY_METERS=50.0`
    - `normalize_kr_place_name` (NFKC + lower + 괄호 제거 + 모든 공백 제거)
    - `name_similarity` (jellyfish.jaro_winkler_similarity 정규화 후)
    - `haversine_meters` + `spatial_similarity(exp(-d/50))`
    - `category_similarity` (Jaccard)
    - `score_pair(*, ...)` (keyword-only) + `classify_decision(score)` →
      `DedupDecision.AUTO_MERGE/MANUAL_REVIEW/KEEP_SEPARATE`
  - `pyproject.toml`: `jellyfish>=1.0` 본 의존 추가.
  - **238 unit pytest passed** (PR#28 199 + 신규 32 + 미세 변동).
    ruff/mypy(31 src)/import-linter all green.
  - **`core/weather.py`는 Sprint 2 KMA PR (PR#31)으로 연기** — WeatherValue
    DTO 의존.
- **PR#28 — `infra/models.py` (SQLAlchemy 2 + GeoAlchemy2) + Alembic 첫 revision**:
  Sprint 2 첫 provider PR (visitkorea 축제)이 의존할 DB schema + ORM 매핑 + Alembic
  인프라 미리 박음.
  - `alembic.ini` + `alembic/env.py` (async-compatible, asyncpg + NullPool +
    SET search_path = public, x_extension) + `alembic/script.py.mako`.
  - `alembic/versions/0001_initial_schemas_and_extensions.py` — 4 schema
    (feature/provider_sync/ops/x_extension) + 3 extension (postgis/pg_trgm/
    pgcrypto) on `x_extension` (ADR-008). postgis는 image 기본 public 설치
    DROP CASCADE 후 재생성.
  - `alembic/versions/0002_features_and_source_tables.py` — features (ADR-012
    `coord_5179` STORED generated column + 10 indexes incl. GiST/GIN partial)
    + source_records (UNIQUE 5-tuple + 4 indexes incl. BRIN) + source_links
    (FK CASCADE/RESTRICT + 3 indexes) + provider_sync_state.
  - `src/kortravelmap/infra/models.py` — `Base` (naming convention) + 4 row class
    (FeatureRow / SourceRecordRow / SourceLinkRow / ProviderSyncStateRow).
    Geoalchemy2 Geometry(POINT 4326/5179, GEOMETRY 4326) + CheckConstraint
    kind/status/coord_pair.
  - `tests/integration/test_alembic_upgrade.py` — 6 case: 4 schema / 3
    extension on x_extension / features 컬럼 / coord_5179 STORED / source 3
    tables / 핵심 5 인덱스.
  - `pyproject.toml`: `alembic>=1.13` 본 의존 추가.
  - **199 unit pytest passed** (코드 변경 없음 기존 + 통합 신규는 testcontainers
    필요). ruff/mypy/import-linter all green.

### Sprint 1 scaffolding (2026-05-25, PR#17+)

- **PR#26 — review P0-4 ID helpers + SourceRecord/Link/Bundle DTO**:
  Sprint 2 첫 provider 변환 함수 직전 필수 묶음.
  - `src/kortravelmap/core/ids.py` 확장:
    - `make_source_record_key(*, provider, dataset_key, source_entity_type,
      source_entity_id, raw_payload_hash) -> str` — `sr_{sha1[:20]}` 포맷
      (`docs/data-model.md §11`).
    - `make_payload_hash(data, *, length=32) -> str` — canonical JSON 직렬화
      (`sort_keys` + `separators=(",", ":")` + `ensure_ascii=False` +
      `allow_nan=False`) → SHA256 hexdigest prefix. `datetime`/`date`는 ISO
      문자열, `Decimal`은 문자열로 정규화하고 `set`/`bytes`/임의 객체는
      거부한다. 1~64 hex char 길이 조정 가능.
    - `SOURCE_RECORD_KEY_HASH_LENGTH = 20`, `PAYLOAD_HASH_DEFAULT_LENGTH = 32`
      constants.
  - `src/kortravelmap/dto/source.py` 신설 — `SourceRecord` (provider raw payload
    추적, 고유성 `(provider, dataset_key, source_entity_type, source_entity_id,
    raw_payload_hash)`) + `SourceLink` (Feature ↔ Source 1:N 매핑,
    `source_role`/`match_method`/`confidence`/`is_primary_source`).
    DB NOT NULL 계약에 맞춰 `source_record_key`/`fetched_at` 필수,
    `raw_data` 기본 `{}`. datetime aware validator (ADR-019).
  - `src/kortravelmap/dto/bundle.py` 신설 — `FeatureBundle` (feature +
    source_record + source_link 3개 필수). `source_link.feature_id`와
    `source_link.source_record_key` 교차 검증. weather/price/file_sources 필드는
    Sprint 2 DTO 추가와 함께 enable.
  - **dto는 core를 import하지 않는다** (ADR-001/002 — import-linter 자동
    차단). `SourceRecord.key()` 메서드 두지 않음 — 호출자가
    `make_source_record_key(...)`로 계산해서 박는다.
  - 신규 tests: `test_ids_extended.py` + `test_dto_source_bundle.py`
    (e2e flow: raw_payload → payload_hash → source_record_key → feature_id →
    FeatureBundle, mismatch/unsupported payload negative case 포함).
- **PR#25 — KNPS keyless sync (python-knps-api PR#3+#4 반영)**:
  upstream knps-api commit `06da125f` 변경 본 라이브러리 docs/pyproject 일괄
  반영. **ADR-028 amendment §H** 신설 (keyless + file-only).
  - `KNPS_SERVICE_KEY` / `DATA_GO_KR_SERVICE_KEY` 사용 안 함 (인증 제거).
  - 14 dataset 모두 `kind="file_dataset"`. 신규 4건 (`knps_linear_facilities`,
    `knps_protected_areas`, `knps_basic_statistics`, `knps_lod_table_catalog`),
    제거 4건 (`knps_access_restrictions`, `knps_fire_alerts`,
    `knps_recommended_courses`, `knps_park_photos`).
  - 제거된 notice 2종 (`access_restriction`/`fire_alert`)은 산림청/소방청
    별도 source로 이전 (후속 ADR).
  - 공개 API 정정: `ApiEndpoint`/`Page`/`api_endpoint`/`raw_endpoint` 삭제,
    `FileArtifact`/`FileMember`/`CsvPreview`/`CsvPreviewRow` 신규.
  - 변경 docs: `decisions.md` (ADR-028 §H amendment) / `knps-feature-etl.md` /
    `forest-feature-etl.md §11` / `external-apis.md §3.8.1` /
    `provider-contract.md §3`. pyproject git URL 핀 (`@06da125f`) 주석.
  - DTO 정합 보강: `AreaDetail.area_kind='protected_area'`,
    `ROUTE_TYPE_FACILITY_ROAD='facility_road'` 추가. 143 pytest passed.
- **PR#24 — DTO strictness P0 (Sprint 2 진입 전 차단)**:
  Review report (`docs/reports/pr-1-21-review.md`, PR#23 DRAFT) P0-1/2/3 해소.
  - `Feature.detail` `mode="before"` dict 거부 (Pydantic union dict coercion
    차단, ADR-018 진짜 강제)
  - 모든 DTO datetime aware validator 일관 적용:
    - `Feature.created_at/updated_at/deleted_at` (이전 PR#19)
    - `NoticeDetail.valid_start_time/valid_end_time` (신규)
    - `RawDataRef.fetched_at` (신규)
  - `dto/_time.py`에 `check_aware_datetime()` 공용 helper 추가 + 모든 DTO에
    적용. ADR-019 해석 명시: "aware면 OK, naive 거부" (KST 변환은 provider 책임)
  - `Feature.category` `^\d{8}$` 정규식 validator (ADR-023 PlaceCategoryCode
    8자리). strict known-code는 후속 PR (transitional)
  - 신규 tests: `test_dto_time.py` (11 case) + dict reject 3건 split +
    category 8자리 2건 + notice datetime 3건. 141 passed total.
- **PR#22 — CI workflows + import-linter 활성화 (Sprint 1 scaffolding 종료)**:
  - `.github/workflows/ci.yml` — pytest unit + integration (testcontainers
    PostGIS, ADR-007) + coverage XML, Python 3.11/3.12/3.13 matrix +
    `concurrency` group으로 이전 run 자동 cancel.
  - `.github/workflows/lint.yml` — ruff check + mypy --strict
    (`kortravelmap` 전체) + import-linter (4 계약).
  - `.github/workflows/openapi.yml` — ADR-031 drift gate. Sprint 1은
    `continue-on-error: true` (앱 모듈 미존재) — Sprint 2 첫 라우터 PR
    에서 제거.
  - `tests/lint/test_import_linter.py` — pyproject.toml의 4 계약 wrap
    (subprocess로 `lint-imports` 실행). 미설치 시 skip.
  - `pyproject.toml`: `include_external_packages = true` (외부 forbidden
    검증 활성화) + `layers`에서 `kortravelmap.cli` 제거 (모듈 미존재).
  - **ADR-002 위반 1건 실 해소** — `KST`/`kst_now` 정의를
    `core/types.py` → `dto/_time.py`로 이전 (dto/feature.py가 core를
    역참조하던 위반 해소). 공개 API `from kortravelmap.core import kst_now`는
    그대로 (core/types.py shim).
  - `tests/unit/test_dto_*.py` + `test_category.py` —
    `pytest.raises(Exception)` → 구체 예외 type (B017/PT011 해소).
  - **125 passed, 10 skipped** (전체) + ruff/mypy/import-linter all green.
- **PR#21 — `src/kortravelmap/infra/` skeleton (crs + db + testcontainers)**:
  - `src/kortravelmap/infra/crs.py` — `pyproj.Transformer` singleton
    (`@functools.cache`, ADR-030 narrow 예외): `transformer_4326_to_5179` /
    `transformer_5179_to_4326` + `project_to_5179` / `project_to_4326`
    + `EPSG_WGS84` / `EPSG_UTM_K`. `always_xy=True` 강제.
  - `src/kortravelmap/infra/db.py` — `make_async_engine` (SQLAlchemy 2
    AsyncEngine + asyncpg) + `make_async_session_factory` +
    `normalize_async_dsn` (psycopg2/psycopg/postgres → asyncpg 통일).
    `SecretStr` 자동 처리.
  - `tests/integration/__init__.py` + `tests/integration/conftest.py` —
    testcontainers PostGIS 베이스 (`pg_container` session-scope `postgis/
    postgis:16-3.5-alpine`, `pg_engine` 4 schema + 3 extension 자동
    생성, `pg_session` per-test rollback). Docker/testcontainers 미설치
    시 자동 `pytest.skip`.
  - `tests/integration/test_pg_smoke.py` — postgis/pg_trgm/pgcrypto
    `x_extension` 격리 확인 (ADR-008) + 4 schema 존재 + ST_Transform
    4326↔5179이 pyproj와 1m 이내 일치.
  - `tests/unit/test_crs.py` 13 case + `tests/unit/test_db.py` 12 case
    (asyncpg 미설치 환경 4건 자동 skip).
  - `pyproject.toml`: `pyproj>=3.6` 본 의존 추가.
  - **124 passed, 10 skipped** (전체 suite).
- **PR#20 — `src/kortravelmap/core/` 예외 계층 + ADR-009 `make_feature_id`**:
  - `src/kortravelmap/core/exceptions.py` — `KorTravelMapError` 베이스 + 7 도메인
    예외 (`ValidationError`/`FeatureNotFoundError`/`SourceRecordNotFoundError`/
    `DuplicateFeatureError`/`ImportJobConflictError`/`ProviderError`/
    `FileStoreError`). HTTP 매핑은 `docs/debug-ui-package.md §6.4`.
  - `src/kortravelmap/core/ids.py` — `make_feature_id(*, bjd_code, kind,
    category, source_type, source_natural_key, content_hash=None)`. 포맷
    `f_{bjd or 'global'}_{kind[0]}_{sha1[:16]}` (ADR-009 SPEC V8 D-2).
    `usedforsecurity=False` 명시. `|` 구분자 / 빈 문자열 검증.
  - dto 의존 회피 — `kind: str` 타입 (PR#19 `FeatureKind` StrEnum은 str
    서브클래스이므로 그대로 호환, 호출 측 코드 변경 0).
  - `core/__init__.py` — PR#19(`KST`/`kst_now`) + PR#20(exceptions 7 + ids
    2) 통합 export, 총 12 공개 식별자.
  - `tests/unit/test_exceptions.py` 7 case + `tests/unit/test_ids.py` 35
    case (parametrize 포함). **72 passed** (전체 suite).
- **PR#19 — `src/kortravelmap/dto/` Feature + 5 detail + ADR-027 적용**:
  - `core/types.py` — `KST` / `kst_now()` (ADR-019)
  - `dto/_enums.py` — FeatureKind 7 / FeatureStatus 6 / SourceRole 8
  - `dto/coordinate.py` — Coordinate (Korea bounds, frozen)
  - `dto/address.py` — Address basic
  - `dto/urls.py` — FeatureUrls + RawDataRef
  - `dto/opening_hours.py` — OpeningTime/Period/SpecialDay/FeatureOpeningHours
  - `dto/place.py`/`event.py`/`route.py` — Detail 모델 + ROUTE_TYPES 9종 +
    normalize_route_type
  - **`dto/notice.py`** — NoticeDetail + **NOTICE_TYPES 14건** (ADR-027
    `access_restriction`/`fire_alert` 포함) + normalize_notice_type
  - **`dto/area.py`** — AreaDetail + AREA_KINDS 12종 (ADR-027 `hazard_zone`)
  - `dto/feature.py` — Feature (ADR-018 detail discriminator, ADR-019 KST
    aware enforcement, marker_color P-01~P-16 regex)
  - `dto/__init__.py` — 38 공개 식별자 re-export
  - `tests/unit/test_dto_{notice,area,feature}.py` (27 cases)
  - **62 pytest passed** (전체 test suite)
- **PR#18 — `src/kortravelmap/category/` 144건 (ADR-023 이전 + ADR-027)**:
  - `_definitions.py` (~2110줄, kraddr-base 사본 + ADR-027 패치)
  - ADR-027 신규 3건: `LODGING_MOUNTAIN_SHELTER` (Tier 2) +
    `LODGING_MOUNTAIN_SHELTER_KNPS` / `_KFS` (Tier 3) + maki = `shelter`
  - `PLACE_CATEGORY_TIER2_NAMES_BY_TIER1["03"]["08"] = "대피소·산장"`
  - `@cache` on `get_category` (ADR-030 narrow 예외, immutable 카탈로그)
  - `category/__init__.py` re-export 14 식별자
  - `tests/unit/test_category.py` (16 cases) — 144 총건/depth/Tier1/
    ADR-027/maki/helper/cache 검증. **30 passed** (전체 test suite)
  - `docs/category.md` §4.3 depth 통계 정정 (원본 Tier 2/4 swap 오류)
- **PR#17 — `src/kortravelmap/` PEP 420 scaffolding**:
  - `src/kortravelmap/__init__.py` (`__version__ = "0.2.0-dev"`)
  - `src/kortravelmap/py.typed` (PEP 561)
  - `src/kortravelmap/settings.py` — `KorTravelMapSettings(BaseSettings)`
    (pg_dsn / object_store_* / log_*)
  - `src/kortravelmap/{category,dto,core,infra,providers,client}/__init__.py`
    (placeholder, 후속 PR에서 채움)
  - `pyproject.toml`: `pydantic-settings>=2.4` 의존 추가
  - `tests/lint/test_no_namespace_init.py` — ADR-022 PEP 420 enforcement
  - `tests/unit/test_smoke_import.py` — `kortravelmap` + `KorTravelMapSettings`
    smoke (5 cases)

### Sprint 1 진입 (2026-05-25, PR#16)

- **T-014 — 코드 작성 단계 진입**: 사용자 승인. Sprint 1 = **active**.
- **ADR 8건 일괄 proposed → accepted 전환** (ADR-027/028/029/030/031/032/
  033/034). 모두 main에 text on accepted 상태.
- `pyproject.toml` `[tool.coverage.report] fail_under` 0 → **50** (ADR-032
  Sprint 1 bar).
- `docs/sprints/SPRINT-1.md` 상태 → active. SPRINT-2~5.md 상태 → accepted
  (시기 대기).
- 후속 Sprint 1 scaffolding PR sequence (PR#17~#23): `src/kortravelmap/`
  PEP 420 + `category/` 144건 + `dto/` (NOTICE_TYPES 14건 + AreaDetail.
  area_kind hazard_zone) + `core/` + `infra/` + CI workflows + 첫 통합
  테스트.

### 결정 (2026-05-25 — PR#6 ~ PR#10 시기)

- **NEW (accepted)**: ADR-024 — canonical provider name `python-krmois-api`
  → `python-mois-api` (PR#3). v1 내부 alias였던 `krmois`/`pykrmois`는 legacy
  alias로만 보존. `docs/krmois-license-feature-etl.md` → `docs/mois-license-feature-etl.md`
  (git mv).
- **NEW (accepted)**: ADR-025 — 디버그 UI frontend는 `maplibre-vworld-js` 채택
  (React + Vite + TS + `maplibre-vworld` + `maplibre-gl` + `zod`). Kakao
  Maps SDK 미사용. `packages/kor-travel-map-admin/frontend/` skeleton.
  **사용자 보강 (2026-05-25)**: VWorld key는 `KOR_TRAVEL_GEO_VWORLD_API_KEY`
  공유 / maplibre-vworld-js upstream 직접 PR로 적극 수정.
- **NEW (accepted)**: ADR-026 — TripMate 사용자 UI도 `maplibre-vworld` 채택
  (SPEC V8 v8_3 Kakao Maps 섹션 superseded). 두 UI 단일 stack.
- **NEW (proposed)**: ADR-027 — forest 카테고리/notice_type 확장 (PR#9):
  `LODGING_MOUNTAIN_SHELTER` Tier 2 신설 + `area_kind=hazard_zone` +
  generic `notice_type=access_restriction`/`fire_alert`. 사용자 결정으로
  `forest_` prefix 없는 generic 명명. WEATHER_MOUNTAIN_STATION /
  NATURE_ECOLOGY / Tier 1 `08 SAFETY`는 거부.
- **NEW (proposed)**: ADR-029 — `@kor-travel-map/map-marker-react` npm 패키지 추출
  (본 PR#10): 디버그 UI + TripMate 사용자 UI 공통 마커/카테고리 매핑.
  MIT 라이선스 (TripMate proprietary 호환). monorepo
  `packages/map-marker-react/`.
- **NEW (proposed)**: ADR-030 — 라이브러리 in-memory 캐시 금지 (PR#8).
  `functools.cache` 한정 narrow 예외 (PlaceCategoryCode 카탈로그,
  `pyproj.Transformer` singleton). `import-linter` 계약으로 `cachetools` /
  `async_lru` / `aiocache` / `diskcache` 차단.
- **NEW (proposed)**: ADR-031 — 디버그 패키지 OpenAPI export 첫 FastAPI
  라우터 등장 PR부터 즉시 활성화 (PR#8). `openapi.json` 저장소 커밋 +
  CI `--check` drift gate.
- **NEW (proposed, 시기 의존)**: ADR-032 — Coverage 단계적 상향 일정
  (Sprint 1 50% → Sprint 4 80%, PR#8). `dto/`는 Sprint 2부터 100% branch
  항상 강제. T-014 시점에 accepted 전환.
- **NEW (proposed, 시기 의존)**: ADR-033 — `feature_consistency_reports`
  두 단계 분할 도입 (PR#8). Phase 1 (Sprint 3~4) = 스키마 + F1~F3 critical
  (orphan source / detail 누락 / CRS drift, severity=ERROR, 게이트 미적용).
  Phase 2 (Sprint 5) = F4~F8 + Dagster 게이트 + swap 차단. T-014 시점에
  accepted 전환.

### 문서 확장 (2026-05-25)

- `docs/performance.md §9.3/§9.4/§9.5` — T-101 (PostGIS MV) / T-103
  (streaming ETL) / T-102 (pg_prewarm) 상세 분석 inline. 도입 조건, 부작용,
  ROI 평가.
- `docs/sprints/SPRINT-1.md` — 코드 작성 단계 진입 Sprint 1 계획 초안
  (T-014 후속).
- `docs/forest-feature-etl.md §11` — KNPS data.go.kr 통합 plan 7 dataset +
  옵션 A/B/C 비교. PR#5에서 outdoor→forest rename + KNPS dataset 카탈로그
  + 옵션 B (별도 `python-knps-api`) 권고. PR#9 (ADR-027)에서 카테고리/
  notice_type 결정 확정.
- `docs/category.md` §4 — Tier 1~4 전체 141건 카탈로그 (트리/표/maki icon
  분포). ADR-027 적용 후 144건 (`03.08 LODGING_MOUNTAIN_SHELTER` 3건 추가).
- `docs/notice-feature-etl.md` §3/§7 — NOTICE_TYPES 14건 (ADR-027의
  `access_restriction` / `fire_alert` 추가). 마커 스타일 매핑.
- `docs/tripmate-integration.md` §14.5 — TripMate 사용자 UI 지도 stack
  (ADR-026).
- `packages/kor-travel-map-admin/frontend/` — React + Vite + maplibre-vworld
  skeleton (`package.json` / `.env.example` / `.gitignore` / `README.md`).

### 잔존 명명 일치화 (본 PR#10)

- `docs/forest-feature-etl.md:173` 컨벤션 예시: `python-krmois-api` →
  `python-mois-api`.
- `docs/mois-license-feature-etl.md:115` 예시 payload: `krmois_admin_address`
  → `mois_admin_address`.
- `docs/journal.md:151` 컨벤션 예시: `krmois/krheritage/krforest` →
  `mois/krheritage/krforest`.
- `docs/journal.md:475` 옛 provider 목록: `krmois` → `mois (구 krmois)`.
- ADR-024 migration 본문 / journal ADR-024 narrative / mois-feature-etl.md
  의 v1→v2 마이그레이션 표 등 *역사 기록 컨텍스트*의 `krmois` 표기는 그대로
  유지 (rename 사건 자체를 기록).

### 코드 (본 PR#10)

- `pyproject.toml` — ADR-030 `import-linter` forbidden 계약에
  `cachetools` / `async_lru` / `aiocache` / `diskcache` 추가. ADR-032
  `[tool.coverage.report] fail_under = 50` Sprint 1 bar 설정.
- `packages/kor-travel-map-api/scripts/export_openapi.py` — ADR-031
  CLI skeleton (실행은 코드 작성 단계에서).
- `packages/map-marker-react/` — ADR-029 skeleton (`package.json` /
  `README.md` / `.gitignore` / `vite.config.ts`).

### 변경 / 재설계 (v2 design — 초기)

- **NEW**: ADR-021 — main에 직접 push 금지. 모든 변경은 feature branch + PR
  (`gh pr create`). 운영 GitHub branch protection으로 강제.
  `docs/agent-guide.md` §7.5에 PR 워크플로/commit format/PR 본문 표준 박힘.

- **BREAKING**: ADR-022 — Python import 경로 변경.
  - `from kor_travel_map import ...` → `from kortravelmap import ...`
  - `from kor_travel_map_admin import ...` → `from kortravelmap.api import ...`
  - `src/kor_travel_map/` → `src/kortravelmap/`
  - `src/kor_travel_map_admin/` → `packages/kor-travel-map-api/src/kortravelmap/api/`
    (디버그 UI 패키지)
  - T-226 이후 `kortravelmap` public root를 사용한다.
  - PyPI distribution 이름(`kor-travel-map`), CLI(`ktmctl`),
    env prefix(`KOR_TRAVEL_MAP_*`), DB 이름(`kor_travel_map`)는 모두 유지.
  - `pyproject.toml` `packages.find` + `namespaces=true` + `import-linter`
    layers 갱신.

- **NEW**: ADR-023 — `python-kraddr-base`의 category 모듈
  (`kraddr.base.categories`, ~2,072줄, 141 enum)을 본 저장소
  `kortravelmap.category`로 이전.
  - 공개 식별자 전부 유지 (`PlaceCategory`, `PlaceCategoryCode`, `get_category`,
    `iter_categories`, `mapbox_maki_icon_for_category` 등).
  - 의존 계층 최하단 (`category → dto → core → infra → providers → client → cli`).
  - 라이선스 GPL-3.0-or-later 호환. 실제 코드 이전은 코드 작성 단계에서 별도 PR.
  - 사양: `docs/category.md`.

- **BREAKING**: 디버그 REST API/UI를 별도 Python 패키지 `kor-travel-map-admin`
  (`packages/kor-travel-map-admin/`)로 분리 (ADR-020). 메인 라이브러리
  `kor-travel-map`에서 FastAPI/Uvicorn 의존성 제거. `[api]` extra 폐기.
  `kortravelmap.api` 모듈 없음. ADR-005의 위치 부분은 ADR-020으로 superseded
  (인증 없음 + 내부망 전용 정책은 유지).
  - 디버그 UI 실행: `uvicorn kortravelmap.api.app:app --host 127.0.0.1 --port 8087`
  - 환경변수 prefix: `KOR_TRAVEL_MAP_API_*`
  - `import-linter`에 `메인 패키지는 fastapi/uvicorn/starlette import 금지`
    계약 추가.


- **BREAKING**: v1 코드는 `v1` 브랜치로 이동. main은 orphan으로 v2 사양 시작.
  v1 산출물은 `git checkout v1` 또는 `kor-travel-map-spec.docx` (저장소 루트
  약 80쪽) 참고.
- **BREAKING**: TripMate ↔ 라이브러리 연계는 **함수 직접 호출**로 일원화
  (ADR-003). REST 사용 안 함.
- **BREAKING**: 의존 스택 확정 — PostgreSQL 16 + PostGIS 3.5 + SQLAlchemy 2 async
  + GeoAlchemy2 + GeoPandas + Pydantic v2 + asyncpg + psycopg[binary,pool]>=3.2
  (ADR-007).
- **BREAKING**: schema 분리 — `feature`, `provider_sync`, `ops`, `x_extension`
  (ADR-008).
- **BREAKING**: `Feature.detail`은 자유 dict 금지, `DETAIL_MODELS` 분기 강제
  (ADR-018).
- **BREAKING**: 모든 datetime은 timezone aware (KST 기본). naive 입력은
  ValidationError (ADR-019).
- **NEW**: 디버그 REST API (옵션, 인증 없음, 내부망 전용, ADR-005).
- **NEW**: 의존 계층 강제 (`dto → core → infra → providers → client → api/cli`)
  + import-linter CI (ADR-002).
- **NEW**: 작업 큐 영속화 (`ops.import_jobs` + advisory lock + SKIP LOCKED,
  ADR-011).
- **NEW**: bulk insert 30k 안전 마진 룰 + `psycopg.copy_*` 우선 (ADR-013).
- **NEW**: 공간 쿼리 인덱스 최적화 — `coord_5179`(meter) 컬럼 + CTE 1회 변환
  강제 (ADR-012).
- **NEW**: 4단계 테스트 (unit/integration/e2e/fixture) + Coverage 목표 + EXPLAIN
  검증 의무화 (ADR-014).
- **NEW**: 객체 저장소는 S3 호환만 가정, RustFS 1차, MinIO/Ceph/R2 swap 가능
  (ADR-015).
- **NEW**: Record Linkage 가중치 0.45/0.35/0.20 + 임계값 0.85/0.65 박음
  (ADR-016).
- **NEW**: 보관 정책 박음 — place 무기한, event +20y, notice +1y, weather +30d
  (ADR-017).

### 문서

- 새 governance 문서 작성: `AGENTS.md`, `README.md`, `SKILL.md`, `CLAUDE.md`.
- 새 design 문서 작성:
  - `docs/architecture.md`
  - `docs/decisions.md` (ADR-001 ~ ADR-019)
  - `docs/data-model.md`
  - `docs/performance.md`
  - `docs/test-strategy.md`
  - `docs/backend-package.md`
  - `docs/agent-guide.md`
  - `docs/dev-environment.md`
  - `docs/windows-reinstall-recovery.md`
  - `docs/feature-model.md`
  - `docs/provider-contract.md`
  - `docs/external-apis.md`
  - `docs/tasks.md`, `docs/resume.md`, `docs/journal.md`
- `pyproject.toml`에 4단계 스택 의존성 + import-linter 계약 박음.

### 마이그레이션 가이드 (v1 → v2)

v1 사용자는 다음 흐름으로 마이그레이션한다 (코드 작성 단계 진입 후):

1. v1 데이터 dump (현재는 미정 — 코드 작성 단계에서 정의)
2. v2 schema (`feature/provider_sync/ops/x_extension`) 생성
3. detail JSONB 키 매핑 (v1 ↔ v2 차이 — 별도 변환 스크립트)
4. `feature_id` 재계산 (`make_feature_id`의 `bjd_code` 인자가 v2에서 명시적)
5. 보관 정책 적용 → 만료 row 삭제

상세 가이드는 코드 작성 단계 진입 시 별도 문서로 작성.

---

## v1 (역사 보존)

v1은 `v1` 브랜치에 보존. 자세한 v1 변경 이력은 그쪽 `git log`로 확인:

```bash
git checkout v1
git log --oneline
```

v1 마지막 commit: `08205ab Preserve v1 work: docs revamp, providers, debug UI,
spec docx` (2026-05-24).
