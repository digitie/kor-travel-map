# kor-travel-map vNext 재설계 정본 — 설계 결정·목표 구조·실행 계획

> 작성일: 2026-07-16 (전면 개정판)
> 기준: KTM `origin/main@2150d67d` · PinVi `origin/main@48085afb`
> 전신: 본 문서는 PR #702(원 리뷰 §1~10) → #703(§11 Claude 다관점) → #704(§12 Codex 재검토
> 병합본 위 §13 대질·수렴) → #707(§14 Codex 재보강)의 **왕복 리뷰 4회를 소화한 최종 정본**이다.
> 왕복 세부(§11~§14의 개별 논증·정정 이력)는 git 이력(위 PR들)에 보존되며, 본 문서는 그
> **최종 유효 판정과 실행 계획만** 담는다. 충돌 시 본 문서가 우선한다.

## 0. 지도 원칙 — 모든 후속 작업에 적용

본 재설계와 그 반영 작업 전체에 다음 우선순위 서열을 적용한다.

1. **정확성·보안** (공개 경계, 데이터 무결성, 인증) — 타협 불가.
2. **설계적 우월성** — 도메인마다 정본(source of truth)은 하나. 같은 사실을 두 곳에 저장하거나
   두 경로로 판정하지 않는다.
3. **코드 단순성·유지보수성** — 1~2인이 운영 가능한 코드량과 개념 수를 유지한다. 계층·추상화는
   실제 문제를 제거할 때만 추가한다.
4. **확장성** — provider·feature 종류·소비자 추가가 스키마/계약 변경 없이 가능하도록 설계한다.
5. **성능** — 실측 기반. 추측 최적화 금지, 측정된 병목만 해소한다.
6. **하위 호환성·기존 문서 계약** — 위 1~5보다 후순위다. 기존 ADR·계약·엔드포인트는 본 문서의
   결정과 충돌하면 **supersede 대상**이며, 유일한 예외는 계획된 cutover 절차(D-11)를 거치는
   라이브 소비자(PinVi) 전환뿐이다. 무계획 파괴는 하지 않되, 계약 보존을 이유로 설계를 굽히지
   않는다.

적용 범위: **코드, REST API, DB Schema 수정을 전부 포괄**한다. 이 문서를 이행하는 에이전트는
"기존 계약이라서 유지"라는 이유를 사용하지 말고, 유지가 필요하면 그 근거(라이브 소비자·데이터
보존·비용)를 명시해야 한다.

### 0.1 이 문서의 사용법 (후속 에이전트 지시)

이 문서는 **반영(전개)을 위한 단일 입력**이다. 후속 에이전트는:

1. §7 반영 매핑표에 따라 각 섹션을 실제 문서(ADR, tasks.md, architecture/*)로 전개한다.
2. ADR 번호는 반영 시점의 `docs/adr/README.md` "다음 후보"를 따른다(본 문서의 D-번호는 논리
   식별자다).
3. 코드 작업은 §6 실행 계획의 task 단위(PR 1개=task 1개)로 진행하고, 각 PR은 이 저장소의 관례
   (적대적 리뷰 → CI green → merge, CI-parity 게이트)를 따른다.
4. 본 문서와 기존 문서가 충돌하면 본 문서를 따르되, 반영 PR에서 해당 기존 문서를 함께
   갱신(supersede 표기)한다.

## 1. 판정 확정 요약 — 왕복 리뷰의 최종 유효 결론

4회 왕복(§11~§14)에서 검증·정정을 거쳐 확정된 사실 판정. 각 항목은 실코드/실 DDL/scratch
PostGIS 재현으로 확증됐다.

| # | 확정 판정 | 근거 요지 |
|---|---|---|
| F-1 | **공개 상태 오분류는 양방향이다**: provider-retired(inactive+deleted_at)는 공개/서비스 batch에서 `missing`으로 은닉되고, admin-inactive·draft·broken(deleted_at 미세팅)은 `found`로 노출된다 | `_is_public_feature`가 hidden/deleted 2종+`deleted_at IS NULL`만 검사(`features.py:63,487-492`); provider retire는 deleted_at 세팅(`feature_repo.py:1491-1492`), admin deactivate는 미세팅(`admin_feature_repo.py:1365-1379`) |
| F-2 | **HTTP 멱등성은 미해결**: Idempotency-Key ledger 부재, change-request는 매 호출 새 uuid row(재시도 replay 없음). `generation`(0052)은 Dagster run-owner CAS이지 Feature HTTP revision이 아니고, `data_version`은 provider upsert에서 0 고정이라 ETag validator로 쓸 수 없다 | `admin_feature_repo.py:1502,2029-2065`; `feature_repo.py:238-240` |
| F-3 | **route 경계 결함**: legacy `curated`/`ops`/`ops_live`/`ops_logs`/`dagster` 라우터 무의존 mount, **`mois_detail`이 무게이트로 `source_records.raw_data` 반환**, `/metrics`·debug ETL(기본 True flag 외 게이트 없음, `etl_live_preview_enabled` 설정은 **코드에서 미소비**), WebSocket 인증 전 accept, secret 미설정 시 local-dev/무검증 통과(fail-open) | `app.py:487-488,513,530-531,622-626`; `auth.py:115-116,137-138,181-183`; `settings.py:56-58,94,194` |
| F-4 | **actor 미신뢰**: 다수 admin write가 body `operator`를 저장하고, auth-event는 body를 principal보다 우선(`body.actor or context.actor`) | `admin_features.py:146,262,273,289,523,872`; `admin_auth.py:201` |
| F-5 | **Feature ID(64-bit SHA-1 prefix)는 정본 identity로 부적합**: 코드 주석의 "10^9건 충돌 ~3e-11"은 birthday bound(≈2.7%) 오인. 게다가 bjd/category가 해시 입력이라 보정만으로 재키잉 발생(코드가 자인) | `ids.py:68-70,149-154` |
| F-6 | **source lineage denorm 미정합**: head-pointer deferrable FK는 존재하나, `source_records`의 denorm identity 4튜플(provider/dataset/type/id)이 부모 entity와 일치하도록 강제하는 composite FK는 없다(entity A에 provider B record 연결 가능) | `models.py:422-430,510-521` |
| F-7 | **weather/price 비대칭**: weather는 semantic UNIQUE·source FK·range CHECK 전무(price는 보유). PG16에서 UNIQUE는 `NOT VALID` 불가 — `CREATE UNIQUE INDEX CONCURRENTLY`(+writer conflict target 배포와 **같은 cutover**)로 도입해야 한다 | `0017` vs `0034` DDL; PG16 문법 사실 |
| F-8 | **공간·조회 결함**: `include_geometry`가 응답이 아닌 **결과집합**을 바꿈(EXPLAIN 재현 2220→2221행), `&&`-only MBR false positive 실재, bbox LATERAL이 kind 무관 매행 실행, GiST 6개(자동 full 3 + 수동 partial 3)로 write ~1.6×, `include_total=false`여도 COUNT 무조건 실행, cursor가 query 파라미터 미포함(재사용 시 조용한 누락/중복) | `feature_repo.py:689,828,963,3534,3766-3788`; `models.py:190-207,274-284`; scratch EXPLAIN 실측 |
| F-9 | **notice cast 취약**: `detail->>'valid_end_time'` timestamptz 직접 cast — 오염 row 1건이 모든 공개 read를 500으로 만들 수 있고, lineage anti-join이 모든 공개 read의 상시 hot-path 비용 | `feature_repo.py:533-539,638` |
| F-10 | **Alembic metadata ≠ schema**: weather/price/log/api-key/auth-event 등 table이 `models.metadata`에 없고 `include_object` 콜백도 없어 clean DB `alembic check`가 실패(PostGIS object까지 drop 후보) | `env.py:54,65,82` |
| F-11 | **migration 방식은 이미 두 가지가 공존**: 0051은 additive(add_column+backfill), 0052는 maintenance clean-cut(EXCLUSIVE lock·신규 table·in-place type 변경·열 제거). "전부 additive"도 "전부 clean-cut"도 아니다 — **변경 유형별 DDL 규율(D-12)이 정답** | `0051`:97-386 vs `0052`:27-74,450-466,2304-2348 |
| F-12 | **rollback은 snapshot 보존만으로 불성립**: 쓰기 재개 후 old snapshot 복원은 사이 write를 유실한다. 현재 도구는 cold backup뿐(WAL archiving/PITR/journal 0건) → write-freeze 유지 또는 forward journal replay가 완료 조건 | `docs/backup-restore.md`; scripts/ 실태 |
| F-13 | **재취득은 유일 복구 전략이 될 수 없다**: 3년 보존 weather·창이 닫힌 feed는 upstream이 재서빙하지 않고, 전국 재수집은 quota(OpiNet 실증)·WAL(MOIS 실증)·시간에서 비현실적. 정본 이관은 DB-to-DB, 검증된 파생만 재계산 | ADR-062; 운영 실증(quota·WAL 사고 이력) |
| F-14 | **PinVi 소비측 결함**: batch transport 실패를 전건 broken으로 오판(`missing` 배열 미소비), TripMap이 cluster 폐기, weather POI별 N+1, Idempotency-Key/If-Match 미전송, `TripDayPoi.version`이 soft delete에서 미증가(→ generation으로 부적합) | PinVi `trip_view_builder.py:152-167`; `TripMapView.tsx:158`; `poi.py:169-171` |
| F-15 | **PinVi 라이브 소비 전제**: 운영상 소비 중으로 간주하되(공유 n150 가동·운영 노트), cutover preflight에서 runtime 증거(`/version`·`api_call_logs` nonzero·smoke)로 최종 확정한다 | §13.3↔§14.6 합의 위치 |
| F-16 | **curation 정본이 두 개**: legacy `curated_features`와 신규 `curation_collections/items`가 title/status/relation을 중복 저장하고 trigger가 legacy→신규 단방향만 동기화 — legacy 수정이 collection을 강제 `published`/`archived_at=NULL`로 되돌릴 수 있다(왕복 4회에서 반박된 적 없는 유효 진단) | §구판 P1-7; migration trigger 실태 |

**유지가 확정된 기존 설계**(재설계에서 버리지 않는다): immutable `source_records` 분리,
WGS84+5179 이중 표현과 GiST 반경 조회, keyset pagination, RFC7807 problem+json(+중앙 핸들러의
stack 미노출), PinVi의 OpenAPI HTTP 경계(직접 DB/패키지 접근 금지), canonical operation
영속화(0050~0052, ADR-064 계열).

## 2. 설계 결정 (ADR 후보)

각 결정은 독립 ADR로 전개 가능한 형태다. 형식: 컨텍스트 → 결정 → 근거 → 영향.
**공통 원칙**: §0의 서열. "기존 계약 유지"는 결정 사유가 될 수 없다.

### D-1. 인증·라우트 경계 — fail-closed + route policy matrix

- **컨텍스트**: F-3. 인증 게이트가 라우터별로 산발 배선되고 기본값이 전부 fail-open이라, 설정
  하나 빠지면 스케줄 변경·ETL 실행·내부 상태가 열린다.
- **결정**:
  1. 모든 Starlette route와 WebSocket을 `public-unauthenticated`(liveness/version) /
     `public-keyed` / `service` / `operator` / `debug` / `metrics` 중 하나로 분류하는
     **route policy matrix를 코드에서 생성**하고, 미분류 route가 있으면 CI를 실패시킨다.
  2. **production profile은 fail-closed**: service/admin/operator secret이 없거나 debug live가
     인증 없이 켜져 있으면 **기동 자체가 실패**한다. `local-dev` fallback은 non-production
     profile에서만 허용.
  3. legacy `curated`/`ops`/`ops_live`/`ops_logs`/`dagster` 라우터에 즉시 게이트 배선(C6b 삭제
     전까지의 방어). `etl_live_preview_enabled`를 실제 live 분기에 연결하고 기본 off.
  4. `/metrics`는 scrape identity 또는 management 경계로 제한. WebSocket은 짧은 수명 서명
     ticket / same-site session / BFF proxy 중 하나로 인증 후 accept.
  5. **물리적 3-app/listener 분리는 하지 않는다**(측정 후 재검토) — 단일 app + 그룹별 의존성
     주입 + **공개 경로 전용 read-only DB role**로 동일한 실질을 달성한다.
- **근거**: 위협의 실체는 "분리 부재"가 아니라 fail-open 기본값과 배선 누락이다. 단일 N150
  1~2인 운영에서 3개 배포 유닛은 §0-3(단순성) 위반.
- **영향**: `app.py`/`auth.py`/`settings.py` 재작성, route matrix 생성기+CI 게이트 신설,
  runbook의 노출 전제 갱신.

### D-2. actor 정본 — 인증 principal에서만 파생

- **컨텍스트**: F-4. body `operator`/`actor`를 감사 기록에 저장해 신뢰 CIDR 내 위조가 가능하다.
- **결정**: 모든 write의 actor는 인증 principal(AdminProxyContext 등)에서만 파생한다. request
  body의 operator/actor 필드는 **스키마에서 제거**한다. 비동기 검수는 제출 actor와 승인 actor를
  각각 principal에서 보존한다.
- **영향**: admin 계열 스키마/서비스 전반, auth-event 기록 경로(`body.actor or context.actor`
  제거), PinVi admin client의 필드 제거.

### D-3. 공개 상태 모델 — 직교 상태 + 단일 공개 정본

- **컨텍스트**: F-1. status·deleted_at·user_deleted_at·user_change_status 4축이 결합 제약 없이
  공존하고, endpoint마다 다른 술어를 쓴다. 결과: retired 은닉 + draft/broken 노출의 양방향
  오분류.
- **결정**:
  1. 상태를 직교 3축으로 재모델링: `lifecycle_state(active|retired)`,
     `publication_state(draft|published|suppressed)`, `quality_state(valid|quarantined)`.
     soft-delete 시각은 lifecycle 전이 시각으로 흡수한다.
  2. 공개 정본은 **하나의 술어**: `published AND active AND valid`. 이를
     `feature.public_features` view(+동일 술어 partial index)로 물화하고, **모든** 공개/서비스
     read(단건·batch·bbox·search·nearby·cluster·tile·collection)가 이 정본만 사용한다.
  3. service batch는 **item-state 계약**을 반환한다:
     `found | retired | suppressed | missing | unchanged` (+ `revision`). transport 실패는 503이며
     item을 `missing`으로 합성하지 않는다.
- **근거**: 오분류는 endpoint별 땜질(`status='active'` 추가)로는 재발한다(§구판 10 "피해야 할
  방식"과 동일 결론). 정본 하나 = §0-2.
- **영향**: features 테이블 상태 컬럼 재편(D-12 절차), 전 공개 SQL의 술어 교체, OpenAPI의
  item-state 스키마, PinVi의 state 소비(D-10).

### D-4. Feature identity — UUID 정본 + natural UNIQUE + alias

- **컨텍스트**: F-5. 64-bit 해시 prefix가 정본 PK이고 mutable 속성(bjd/category)이 해시 입력이다.
- **결정**:
  1. 정본 PK를 **UUID surrogate**로 전환한다(UUIDv7 채택 시 애플리케이션 generator를 정본으로
     명시 — PG16 `gen_random_uuid()`는 v4).
  2. provider natural identity는 `source_entities` UNIQUE로 강제한다.
  3. 기존 `f_*` 결정적 ID는 **alias 테이블**(indexed, redirect 의미 포함)로 보존해 외부 참조를
     끊지 않는다. 외부 소비자는 ID를 파싱하지 않고 byte-for-byte 보존한다(`split("@")`류 제거).
  4. 행정코드·kind·category는 전부 **변경 가능한 속성**으로 강등한다.
- **근거**: 재키잉은 dedup 단절·소비자 dangling을 만든다. alias 병행이 §구판 §8 big-bang의
  re-key보다 안전하며, alias 테이블 자체가 문서 왕복에서 합의된 expand-contract 장치다.
- **영향**: features PK·전 FK 체인, notice-lineage SQL의 in-SQL 해시 재계산 제거, PinVi 저장
  ID의 alias-map 이관(명시 ID 필드만; `feature_snapshot`은 by-value 보존, unmatched 0건 게이트).

### D-5. source lineage — provider_datasets 정규화 + denorm 제거

- **컨텍스트**: F-6. provider/dataset 문자열이 최소 9개 테이블에 FK 없이 반복되고, record의
  denorm identity가 부모 entity와 어긋날 수 있다.
- **결정**:
  1. `provider_sync.provider_datasets`를 **영속 identity 정본 테이블**로 신설한다. **DB가 정본을
     소유**하고, 코드 registry(provider_catalog)는 "현재 활성 callable subset" 검증만 담당한다
     (정본 복제 금지).
  2. 계층: `provider_datasets → source_entities → source_records(immutable)` +
     `source_entity_heads`(current pointer 분리로 순환 FK 제거).
  3. 최종 스키마에서 record의 denorm identity 열은 **제거**한다(전환기에는 정합 composite FK가
     안전장치 — 최종형이 아님을 명시). `source_role` 단일 필드로 primary 판정을 일원화
     (`is_primary_source` 제거).
- **영향**: source 계열 테이블 재편(D-12 절차), 9곳의 문자열 참조 FK화, canonical operation
  (0051)의 provider/dataset 컬럼도 이 정본을 참조하도록 후속 정렬.

### D-6. Feature core — typed subtype + DB 강제 제약

- **컨텍스트**: F-8·§구판 P1-2. core가 JSONB monolith이고 kind별 geometry/필수 필드를 DB가
  강제하지 않는다(route에 Point, coord-geom 325km 이격, 빈 문자열 ID 전부 저장 가능했음).
- **결정**:
  1. core에는 UUID·kind·name·category FK·직교 상태·row_revision만 남긴다.
  2. kind별 subtype 테이블(point/route/area)로 geometry를 강제: route=MultiLineString,
     area=MultiPolygon, point류=Point + `ST_IsValid`·`NOT ST_IsEmpty`·anchor 일치 CHECK.
  3. category는 `(kind, code)` FK. 잔여 JSONB에는 최소 `jsonb_typeof` CHECK.
  4. filter/sort에 쓰는 필드(기간·가격대 등)는 typed column/range로 승격.
- **영향**: features 분해(가장 큰 스키마 작업 — Wave 2), 공개 read는 D-3 정본 view 경유라
  소비자 영향 국소화.

### D-7. override 모델 — field-level 단일화

- **컨텍스트**: §구판 P1-5. user_request whole-row 동결과 field-level `feature_overrides`가
  이중 체계로 공존해, 이름 수정 하나가 provider의 좌표·폐업 갱신까지 영구 동결한다.
- **결정**: provider base projection + **field-level override 단일 체계** + effective
  projection의 3층으로 수렴한다. whole-row 동결(`data_origin='user_request'` CASE 분기)은
  제거하고, user 변경은 change request/history를 정본으로 두고 override로만 반영한다.
- **영향**: upsert SQL 대폭 단순화(거의 전 열의 CASE 제거 — §0-3 직접 기여), 변경 이력 4중
  복제(features.user_change_* / feature_versions / overrides / change_requests) 해소.

### D-8. weather/price — bitemporal 의미 + 대칭 제약 + current summary

- **컨텍스트**: F-7·§구판 P1-6. weather는 제약 전무, card는 "가장 먼 미래", marker는 "now
  최근접"으로 같은 데이터가 화면마다 다르고, asof가 발행시각을 바운드하지 않아 미래지식이 샌다.
- **결정**:
  1. weather semantic identity에 **native tuple UNIQUE**(`UNIQUE NULLS NOT DISTINCT`, PG16) —
     도입은 `CREATE UNIQUE INDEX CONCURRENTLY` + **writer conflict-target 코드와 같은 cutover**.
  2. `valid_from<=valid_until` CHECK, payload object CHECK(price 포함), source FK, 부모 kind FK.
  3. 시간 의미를 bitemporal로 명시: `target_at`(유효 시각)과 `known_at`(발행/수집 cutoff —
     발행 시각뿐 아니라 observation의 `collected_at`까지 포괄하는 "시스템이 안 시점"으로 정의,
     historical은 `issued_at<=known_at` 강제). card/marker의 선택 규칙을 하나의 정의로 통일.
  4. **current weather/price summary 테이블**(적재 파이프라인이 갱신)로 bbox의 매행 LATERAL을
     LEFT JOIN으로 치환한다. 이는 D-3 공개 정본 view와 **병존**한다(막는 결함이 다름 — 대체
     관계 아님).
  5. partition/hypertable·event clock 직렬화는 retention·write/read **실측 후** 결정.
- **영향**: weather 테이블 제약 추가(D-12 절차: ~30M행이라 STORED 추가·rewrite 금지, expression
  index/summary 우선), weather_repo 선택 SQL 재작성, `effective_at` STORED는 **신규 테이블에만**.

### D-9. 공개 REST 표면 — 정본 projection + 완결 계약

- **컨텍스트**: F-1·F-8·F-9·§구판 P0-4/P0-6/P1-11/P1-12. raw payload 공개, silent truncation,
  no-op 옵션, 무조건 COUNT, cursor 재사용 누락.
- **결정**:
  1. 공개 detail은 **kind-discriminated typed DTO**만. `raw_data`/`raw_payload_hash`/
     `source_record_key`는 operator 표면(`/features/{id}/sources`)으로 이동. service batch 기본
     projection은 `trip_card` 고정(서버 정의 enum, raw 선택 불가).
  2. 지도 계약: 응답에 `mode(items|clusters)`·`truncated`·`coverage`·deterministic
     `cluster_key`+drill-down 명시. **MVT는 측정 후**(현 소비 규모 300건에서 도입하지 않음).
  3. `include_geometry`는 serialization만 제어(candidate 술어는 option 무관 단일) —
     route/area는 `&& envelope AND ST_Intersects`.
  4. `include_total`을 repo까지 전달(false면 COUNT 미실행). cursor에 **canonical query
     fingerprint + version byte**를 넣고 불일치는 `CURSOR_QUERY_MISMATCH` 거부(HMAC은 인가
     미탑재이므로 도입하지 않음 — 측정/위협 변화 시 재검토).
  5. weather 단건은 부모 공개 확인(없으면 404), **`POST /v1/features/weather:batch`**(set-based,
     item별 `found|no_data|retired`, 전체 `unavailable` 분리)로 PinVi N+1 제거. 범용
     feature-context batch는 측정 후.
  6. no-op 옵션(해수욕장 quality/forecast)은 **삭제**(구현 시점에 재도입).
  7. notice 공개 판정은 typed `notice_states`(`valid_during tstzrange`+`is_current` partial
     UNIQUE)로 이전 — 즉시 완화는 방어적 cast(Wave 0).
  8. ETag/조건부 GET: **`row_revision`**(D-10과 함께 도입하는 단조 증가 revision)을
     validator로 사용(F-2: data_version은 부적합). request_id/duration은 header로 이동.
  9. OpenAPI는 표면별 생성(수기 29-allowlist 폐기) — 신규 public route가 자동 편입되지 않으면
     CI 실패.
- **영향**: features/public_views/curated 라우터 재작성, user-client 재생성, PinVi typed 소비.

### D-10. write 안전성 — Idempotency-Key ledger + row_revision/If-Match

- **컨텍스트**: F-2·F-14. 재시도 중복(PinVi가 5xx 재시도)과 동시 수정 덮어쓰기를 막는 계약이
  없고, 기존 컬럼(generation·data_version·TripDayPoi.version)은 전부 validator로 부적합하다.
- **결정**:
  1. command POST: `(principal, route, Idempotency-Key)` UNIQUE ledger + canonical request hash.
     같은 key·같은 body는 저장된 결과 replay, 같은 key·다른 body는 409.
  2. PATCH/DELETE: **`row_revision`**(신설, 모든 write에서 단조 증가) 기반 `If-Match` — 누락
     428, stale 412. 비동기 검수는 승인 시점에 base revision 재검사.
  3. 우선 도입 표면: 갱신요청/변경요청 create(중복 실발생) → correction PATCH/DELETE → 조회
     ETag(D-9-8) 순.
  4. PinVi: 모든 재시도에 동일 Idempotency-Key 유지, POI 전파는 outbox
     sequence(+restore epoch)를 generation으로 사용(`TripDayPoi.version` 미신뢰 — F-14),
     relay 상태·주기 reconciliation job 포함. cache-target 동기화는 **critical path에서 분리**.
- **영향**: idempotency ledger 테이블, 전 write 라우터, PinVi client/relay.

### D-11. cutover 방식 — shadow vNext + write-fence 순차 전환

- **컨텍스트**: F-11·F-12·F-13. big-bang(§구판 8)도, 영구 dual-serve도 아니다. 라이브 소비자
  (PinVi, F-15)와 단일 호스트 제약에서 성립하는 유일한 경로.
- **결정** (구조 전환 wave의 표준 절차):
  1. **target freeze**: 본 문서 §3~5를 ADR/OpenAPI/DDL 테스트로 고정.
  2. **보존 등급 분류**: immutable records·weather/price history·override·curation·감사는
     **DB-to-DB 이관**, 재생 가능한 projection/index만 rebuild. **upstream 재취득을 유일한
     복구 전략으로 삼지 않는다**(F-13) — 정본은 DB-to-DB 이관이며, 검증된 완전 파생
     projection/cache에 한해 재계산 또는 선택적 재취득을 허용한다.
  3. **복구 선행 검증**: cold snapshot의 staging restore + count/checksum/대표 query 통과를
     cutover 착수 조건으로.
  4. **shadow vNext 구축**: UUID 컬럼+alias 등 신규 구조를 side-by-side로 backfill, 새 구조에서
     visibility matrix·계약·planner-default EXPLAIN·p95를 **먼저** 통과.
  5. **write-fence cutover**: maintenance window에 쓰기를 멈추고(fence) 마지막 delta 반영 →
     KTM·PinVi를 순차 전환(원자 아님 — 5단계 절차) → **rollback window 동안 write-fence를
     유지하거나 forward journal replay를 준비**(F-12: 이것 없이는 rollback이 데이터를 유실한다).
     rollback 단위는 양 DB+manifest 전 이미지이며 RPO/RTO를 명시한다.
  6. **soak 후 제거**: reconciliation·운영 지표 통과 후 legacy schema/route를 삭제한다. 영구
     dual-serve를 만들지 않는다.
- **영향**: 이관 스크립트·검증 gate·runbook. PinVi와의 전환 조율(preflight에서 F-15 확정).

### D-12. DDL·성능 규율 — 변경 유형별 고정 절차

- **컨텍스트**: F-11(0051 additive vs 0052 clean-cut 공존이 실증), F-8(성능 게이트 부재),
  F-10(metadata drift).
- **결정**:
  1. DDL 절차를 유형별로 고정한다:
     | 변경 유형 | 절차 |
     |---|---|
     | CHECK/FK 추가 | `ADD CONSTRAINT … NOT VALID` → 배경 `VALIDATE` |
     | UNIQUE/대형 index | `CREATE (UNIQUE) INDEX CONCURRENTLY`(alembic autocommit_block) + writer conflict-target 코드와 동일 cutover |
     | 소형 ops 테이블 수술 | drain + `ACCESS EXCLUSIVE`(0052 방식) — **단, lock 획득 상한(≠중단 상한)과 실제 중단 시간을 production clone에서 실측한 수치를 PR에 첨부** |
     | 대형 테이블 type/PK 교체·STORED 추가 | shadow column/table + backfill(즉시 rewrite 금지 — F-7의 ~30M weather) |
  2. Alembic 정합: 모든 애플리케이션 소유 테이블을 metadata에 매핑(또는 `include_object` 명시
     제외)하고, **빈 PostGIS DB → `upgrade head` → `alembic check` exit 0**을 CI 게이트로.
  3. 중복 GiST 제거: `spatial_index=False` + 공개 술어 partial만 유지(write 1.6× 실측 근거).
     시간상관 테이블은 partition 이전에 **BRIN-on-time** 우선.
  4. 성능 게이트 계층화: 매 PR = planner-default EXPLAIN 스모크·query-count·response-shape
     회귀 / release·cutover = 100만+ 분포 fixture·`EXPLAIN (ANALYZE, BUFFERS)`·N150 실측
     p95/buffer/byte budget. "query 수가 batch item 수에 비례하지 않는다" 검사를 상시 포함.
- **영향**: alembic env·CI·성능 테스트 재편(`enable_seqscan=off` 단언은 회귀 감시용으로 강등).

## 3. 목표 DB Schema

| 영역 | 정본 | 핵심 제약·인덱스 | 관련 결정 |
|---|---|---|---|
| Feature core | `features`: UUID PK, kind, name, category FK, 직교 3상태, row_revision | non-empty CHECK, 상태 결합 CHECK, category `(kind,code)` FK | D-3·D-4·D-6 |
| Feature alias | `feature_aliases`: 구 `f_*` ID → UUID (redirect 의미) | alias UNIQUE, lookup index | D-4 |
| 공간 subtype | kind별 point/route/area 테이블, canonical 4326 + generated 5179 | GeometryType·`ST_IsValid`·`NOT ST_IsEmpty`·anchor CHECK, 공개 술어 partial GiST만 | D-6·D-12 |
| provider 정본 | `provider_datasets`(DB 소유) → `source_entities` → `source_records`(immutable) + `source_entity_heads` | natural UNIQUE, 순환 FK 제거, denorm 열 제거(최종), `source_role` 단일 | D-5 |
| effective 값 | provider base + field-level `feature_overrides` → `effective_features` projection | override field-path UNIQUE, whole-row 동결 제거 | D-7 |
| 공개 정본 | `public_features` view/projection (`published∧active∧valid`) | 동일 술어 partial index, 전 공개 SQL이 이것만 사용 | D-3 |
| notice | `notice_states`: typed lineage + `valid_during tstzrange` + `is_current` | current partial UNIQUE, range GiST, hot path에서 JSON cast/anti-join 제거 | D-9-7 |
| weather/price | typed history(bitemporal) + `current_*_summary` | tuple UNIQUE(NULLS NOT DISTINCT, CONCURRENTLY), range·payload CHECK, source/kind FK, BRIN-on-time | D-8 |
| operation | `ops.import_jobs` canonical operation(0050~0052 기존 유지) + provider_datasets FK 후속 정렬 | 기존 identity UNIQUE/트리거 유지 | D-5, ADR-064 계열 |
| curation | `curation_collections/items` **단일 write model** — legacy `curated_features`·단방향 trigger·legacy route는 제거, 후보는 `theme_feature_candidates` 분리 | archive 상태·`archived_at` 결합 CHECK | F-16 |
| idempotency | `idempotency_ledger`: (principal, route, key) UNIQUE + request hash + 결과 | replay/409 판정 | D-10 |
| POI target | canonical point 1개 + generated 파생, membership/provider-scope 분리, `source_generation` 단조 적용 | external identity UNIQUE, generation 비교 적용 | D-10·§구판 P1-8 |

## 4. 목표 REST API

```text
public-api  (public-keyed; liveness/version만 unauthenticated)
  GET  /v1/features/{feature_id}            # typed kind-discriminated detail, ETag(row_revision)
  GET  /v1/features/search                  # include_total 실전달, fingerprint cursor
  GET  /v1/features/nearby
  GET  /v1/features/in-bounds               # mode/truncated/coverage/cluster_key 명시
  GET  /v1/categories                       # catalog-revision ETag
  GET  /v1/collections, /v1/collections/{id}

service-api  (service token)
  POST /v1/features:batchGet                # item-state: found|retired|suppressed|missing|unchanged (+revision)
  POST /v1/features/weather:batch           # set-based, target_at/known_at bitemporal
  PUT/DELETE /v1/service/cache-targets/{system}/{key}   # source_generation 단조
  POST /v1/service/refresh-requests         # Idempotency-Key, 202+operation resource
  GET  /v1/service/refresh-requests/{id}

operator-api  (admin principal, If-Match/Idempotency-Key)
  /v1/features/{id}/sources|observations    # raw lineage는 여기로만
  /v1/feature-change-requests               # principal actor, revision 재검사
  /v1/ops/datasets/*, /v1/ops/pipeline/*    # ADR-064 신규 그룹(기존 유지)
  /v1/provider-datasets                     # D-5 정본 관리

제거: no-op beach 옵션, 수기 OpenAPI allowlist(표면별 생성으로 대체),
      공개 표면의 raw_data/raw_payload_hash/source_record_key, body operator/actor.
측정 후: MVT tile, feature-context:batch(범용), cursor HMAC, 물리 listener 분리.
```

오류·캐시 계약: RFC7807 유지, `Retry-After`는 409(advisory-lock 경합 — 기존 C3 계약 승계)·
429(rate quota)·503(upstream unavailable, stable code)에 명시, ETag/304(row_revision·catalog
revision), `CURSOR_QUERY_MISMATCH`, rate quota는 edge/app 중 정본 위치를 정하고
`429+Retry-After` contract test(§14 합의 — "app rate limiter 부재=DoS 확정"이 아니라 정본화가
완료 조건).

## 5. 목표 코드 구조

- **단일 FastAPI app 유지** + route policy matrix(D-1) + 그룹별 dependency + 공개 전용 read-only
  DB role. 물리 분리는 측정 후.
- 라우터는 schema/service/query 경계 분리(C2R·C3a에서 확립된 패턴을 전 표면에 적용). 삭제
  예정(legacy) 라우터에서 공유하는 로직은 중립 모듈로 이식 후 삭제(C6b 전제 유지).
- upsert 경로: whole-row 동결 CASE 제거(D-7)로 `_UPSERT_FEATURE_SQL` 대폭 단순화. bbox SQL:
  candidate 술어 단일화 + LATERAL→summary JOIN(D-8·D-9)으로 이중 SQL 복제 제거.
- 공개 판정·notice 판정·상태 전이는 각각 **한 곳**(view/typed table/상태 머신)으로 수렴 —
  endpoint별 재구현 금지.
- PinVi측: typed 생성 client(수기 dict mapper 제거), transport/missing/state 분리, cluster 렌더,
  weather:batch 소비, outbox relay. (PinVi repo 작업은 별도 계획으로 전개하되 계약은 본 문서가
  정본.)

## 6. 실행 계획

### 6.1 T-ADM(ADR-064) 체인과의 관계

진행 중인 admin-ops 통합은 **본 재설계의 선행 구현부**다(canonical operation·admin 게이트·
schema/service 경계). 순서 원칙:

- **T-ADM 잔여를 먼저 종결한다**: C3e-B1∥C3e-C → (B2∥B3) → C3e-I → C45X(#701, alembic **0053
  재번호** 필요)·C4R(#698) 리뷰·rebase·merge → C4(#683)·C5(#691) rebase·merge → C6a→C6b→C7A→C7.
  오픈 PR 4건은 전부 main과 conflicting이므로 C3e 종결 후 일괄 rebase가 확정 절차다.
- **0052(projection access-path 정리) 배포 전**: production clone rehearsal로 중단 시간·WAL
  발생량·전후 checksum을 실측·첨부한다(§8.1의 ops-수술형 규율을 0052 자신에게 소급 적용).
- 본 재설계 Wave 0은 T-ADM과 **표면이 겹치지 않아 병행 가능**(공개 API·auth 기본값·PinVi측).
  Wave 1 이후는 C6b(legacy 삭제)와 순서 조율 — legacy 라우터 게이트 배선(W0-3)은 C6b가 삭제할
  파일에 대한 임시 방어이므로 최소 diff로.

### 6.2 Wave 0 — 즉시 (P0, 테이블 변경 0 — 유일한 DDL은 T-VN-04의 CREATE VIEW, 전부 가역)

| ID | task | 내용 | 관련 |
|---|---|---|---|
| T-VN-01 | fail-closed 전환 | production profile secret 필수·기동 거부, local-dev fallback 격리 | D-1, F-3 |
| T-VN-02 | route policy matrix | 전 route/WS 분류 생성기 + 미분류 CI 실패 + `/metrics`·debug ETL live(`etl_live_preview_enabled` 실배선)·WS ticket | D-1 |
| T-VN-03 | legacy 라우터 게이트 배선 | curated/ops/ops_live/ops_logs/dagster 즉시 방어(최소 diff, C6b 삭제 전 임시) | D-1 |
| T-VN-04 | 공개 predicate 통일(1차) | 기존 상태 위에 `public_features` view(CREATE VIEW만 — 전용 인덱스는 T-VN-34) + 전 공개 SQL 교체 — **양방향 오분류(F-1) 동시 해소** | D-3 |
| T-VN-05 | raw payload 경계 | 공개 DTO에서 raw 계열(`raw_data`·`raw_payload_hash`·`source_record_key`·**`mois_detail` passthrough**) 제거, observations를 operator 표면으로, batch `trip_card` 고정 | D-9 |
| T-VN-06 | notice 방어적 cast | 오염 row 1건의 공개 read 500 차단(완화 — 재설계는 W2) | D-9-7, F-9 |
| T-VN-07 | no-op 옵션 삭제 + actor principal(1차) | beach 옵션 제거; auth-event `body.actor` 우선 제거 등 최소 수정 | D-2, F-4 |
| T-VN-08 | PinVi false-broken 수정 | transport 실패↔missing 분리(stale 유지), `split("@")` 제거, status/state 소비 준비 | D-10, F-14 |

### 6.3 Wave 1 — 조기 (P1, additive, 구조 전환 비의존)

| ID | task | 내용 | 관련 |
|---|---|---|---|
| T-VN-11 | service batch item-state | 5-state envelope + revision (503≠missing) | D-3 |
| T-VN-12 | Idempotency-Key ledger | create 계열 replay/409 — **#701(C45X)의 refresh-request 재사용 계약(`reused_active_request`)과 조율, 이중 멱등 장치 도입 금지** | D-10 |
| T-VN-13 | row_revision + If-Match | 신설 revision, correction PATCH/DELETE, 이후 ETag/304 | D-10, D-9-8 |
| T-VN-14 | 지도 completeness | mode/truncated/coverage/cluster_key + include_geometry serialization화 + candidate 술어 단일화 + `ST_Intersects` | D-9 |
| T-VN-15 | search 계약 | include_total 실전달 + cursor fingerprint/version | D-9 |
| T-VN-16 | weather:batch + 부모 404 | set-based batch, bitemporal 파라미터, PinVi N+1 제거 | D-8·D-9 |
| T-VN-17 | weather 무결성 가드 | tuple UNIQUE(CONCURRENTLY, writer 동시 cutover) + range/payload CHECK(NOT VALID→VALIDATE) + source FK | D-8, F-7 |
| T-VN-18 | 중복 GiST 제거 + BRIN | spatial_index=False, partial만 유지(전후 write 실측 첨부), 시간상관 BRIN | D-12 |
| T-VN-19 | alembic 정합 CI | metadata 매핑/include_object + 빈 DB `upgrade→check` exit 0 게이트 | D-12, F-10 |
| T-VN-20 | actor principal 전면 + body 필드 제거 | D-2 완결(스키마에서 operator/actor 제거) | D-2 |
| T-VN-21 | 성능 게이트 계층화 | planner-default 스모크 확대, query-count 게이트, release 프로파일 정의 | D-12 |

### 6.4 Wave 2 — 구조 전환 (shadow + write-fence cutover, D-11 절차)

| ID | task | 내용 | 관련 |
|---|---|---|---|
| T-VN-31 | target freeze | §3~5를 ADR/OpenAPI/DDL 테스트로 고정 | D-11 |
| T-VN-32 | UUID identity | UUID 컬럼+backfill+alias 테이블, notice-lineage SQL 재작성, PinVi alias-map 이관 계획 | D-4 |
| T-VN-33 | provider_datasets 정본 | 테이블 신설(DB 소유)+9곳 FK화+denorm 제거(전환기 composite FK 경유) | D-5 |
| T-VN-34 | 직교 상태 모델 | 3축 컬럼+결합 CHECK, 4축 레거시 흡수, public_features를 실체화 | D-3 |
| T-VN-35 | typed subtype 분해 | kind별 geometry 테이블+제약, category FK | D-6 |
| T-VN-36 | override 단일화 | whole-row 동결 제거, field-level 일원화, upsert 단순화 | D-7 |
| T-VN-37 | notice_states | typed range 재설계, hot-path anti-join 제거 | D-9-7 |
| T-VN-38 | current summary | weather/price current 테이블 + bbox LATERAL 치환 | D-8 |
| T-VN-39 | cutover 실행 | 보존 분류→복구 검증→shadow 검증→write-fence 전환→soak→legacy 제거 (KTM·PinVi 조율, preflight로 F-15 확정) | D-11 |
| T-VN-40 | curation write model 단일화 | `curation_collections/items`만 정본으로: legacy `curated_features` write 경로·단방향 trigger·legacy route 제거, 후보는 `theme_feature_candidates` 분리 | F-16, §3 |
| T-VN-41 | cache-targets 실배선 | canonical POI target 스키마+outbox 설치 → backfill → reconciliation job → enable(critical path 분리) — §4 `cache-targets` 표면과 D-10-4의 실행부 | D-10, §3 |

### 6.5 Wave 3 — 측정 후

MVT tile, 범용 feature-context:batch, cursor HMAC, weather partition/hypertable·event clock
직렬화, 물리 listener/process 분리, 매 PR 대규모 fixture. 각각 **도입 조건(측정 지표)을 먼저
정의**하고 지표가 충족될 때만 착수한다.

### 6.6 하드닝 백로그 (wave 배정 유동 — 각 항목 PR 1개 규모)

순서 제약이 약한 보안·운영 하드닝 항목. Wave 1 틈새 또는 관련 T-VN task에 합류시켜 처리한다.

- public API key를 URL query에서 header로 이동(로그·referrer 유출 차단).
- `admin_destructive_enabled` 기본값 False화(현행 기본 True는 fail-open).
- CORS를 표면(public/service/operator)별로 분리 설정.
- `coord_5179` generated column의 PROJ 버전 pin + drift 검사 + REINDEX runbook.
- CONCURRENTLY 실패로 남는 INVALID index 탐지·drop runbook(모든 CONCURRENTLY task의 전제).
- admin 목록 API OFFSET pagination → keyset 전환.
- PinVi contract test를 필드 레벨(required/type/enum)로 강화 + OpenAPI SHA manifest 검증.

### 6.7 공통 규율

- PR 1개=task 1개, 적대적 리뷰(2인 또는 지시된 인원)→CI green→merge. migration 포함 PR은
  단일 head·번호 경합 확인(현 head 0052, 오픈 #701이 0053 예약).
- **T-VN task의 수용 기준 정본**: 각 task가 참조하는 D-결정 본문 + §8 검증 게이트다. task 표의
  "내용" 칸은 요약이며 계약을 재정의하지 않는다. 특히 T-VN-21은 §8.3 계층 3단 전부,
  T-VN-31은 §3~§5의 freeze 산출물(ADR·OpenAPI diff·DDL 테스트) 존재가 완료 조건.
- 각 wave 종료 시 §8 검증 게이트 통과를 확인하고 journal/resume 갱신.
- Wave 0·1은 T-ADM과 병행 가능하나 같은 파일 충돌 시 T-ADM 우선(먼저 종결).

## 7. 후속 반영 매핑표 — 이 문서 → 실제 문서 전개

| 본 문서 | 대상 파일 | 반영 방식 |
|---|---|---|
| §0 지도 원칙 | `AGENTS.md`/`CLAUDE.md` 참조 한 줄 + 신규 ADR 서문 | 인용(원문은 본 문서 유지) |
| D-1·D-2 | `docs/adr/0NN-route-policy-fail-closed.md` (1건) | 신규 ADR; ADR-005(ops 무인증)·ADR-060 일부 supersede |
| D-3 | `docs/adr/0NN-orthogonal-publication-state.md` | 신규 ADR; ADR-017의 place 유지 규정은 **이관 문서(data-model 계열 architecture 문서)** 갱신으로 반영(ADR 원문은 포인터만) |
| D-4 | `docs/adr/0NN-feature-uuid-identity.md` | 신규 ADR; ADR-057(concierge stable id)와 관계 명시, `docs/etl/feature-id-determinism.md`는 **개정**(UUID 정본·기존 ID는 alias로 강등) |
| D-5 | `docs/adr/0NN-provider-datasets-canonical.md` | 신규 ADR; ADR-063 확장 |
| D-6·D-7 | `docs/adr/0NN-feature-subtype-decomposition.md`, `0NN-field-level-override.md` | 신규 ADR **2건 확정**(D-6/D-7 각 1건 — 독립 채택·독립 rollback 가능해야 함) |
| D-8 | `docs/adr/0NN-weather-bitemporal.md` | 신규 ADR; ADR-062(3년 보존)와 정합 명시 |
| D-9·D-10 | `docs/adr/0NN-public-rest-contract.md`, `0NN-write-safety.md` | 신규 ADR; `docs/architecture/rest-api.md` 전면 개정 |
| D-11·D-12 | `docs/adr/0NN-cutover-and-ddl-discipline.md` | 신규 ADR; `docs/deploy.md`·runbook에 write-fence/rollback 조건 추가 |
| §3 | `docs/architecture/postgres-schema.md` | "목표(vNext)" 섹션 신설(현행 서술과 구분) |
| §4 | `docs/architecture/rest-api.md` + `docs/integration-map.md` | 목표 표면 섹션 신설; PinVi 계약 변경분은 integration-map에 cutover 조건부로 |
| §6 | `docs/tasks.md` | `T-VN-*` 블록 신설(§6.1의 T-ADM 선행 관계 명시), tasks-rule 준수 |
| §8 | `docs/architecture/performance.md` + CI workflow | 게이트 정의 이관 |
| 전체 | `docs/journal.md`·`docs/resume.md` | 반영 작업 자체의 엔트리 |

반영 시 주의: (1) ADR 번호는 반영 시점 README의 다음 후보 사용. (2) 기존 ADR을 supersede할 때
원문을 삭제하지 말고 상태·후속 포인터만 갱신. (3) tasks.md의 T-ADM 블록은 건드리지 않고 T-VN
블록을 별도 추가. (4) 본 문서는 반영 완료 후에도 "재설계 정본"으로 유지하며, 반영 PR들이 본
문서의 해당 섹션에 반영 PR 번호를 역기입한다.

## 8. 검증 게이트

### 8.1 DB 정합 (Wave별 완료 조건)

- 빈 ID/name/category, 잘못된 JSONB shape, kind-geometry 불일치, coord-anchor 이격, 역전
  range, semantic 중복, cross-entity record 연결, 상태 불가능 조합이 **DB에서** 거부된다.
- 빈 PostGIS DB → `alembic upgrade head && alembic check` exit 0 (CI 상시).
- migration PR: DDL 유형별 절차(D-12 표) 준수 + ops-수술형은 clone 실측(중단 시간·WAL·checksum)
  첨부.

### 8.2 API 계약

- 전 공개 route가 동일 visibility matrix 사용(상태별 fixture로 detail/bbox/tile/search/nearby/
  collection 교차 검사) — F-1 양방향 모두.
- 공개 스키마·payload에 raw provider 필드 0건. batch가 5-state를 구분하고 503에서 소비자
  snapshot이 stale로 유지된다(broken 합성 금지).
- opaque ID byte-for-byte 보존, cursor mismatch 거부, `include_total=false`에서 COUNT 0회,
  미구현 옵션은 OpenAPI에 없음.
- Idempotency replay 1-operation, stale If-Match 412, 조건부 GET 304.
- route policy matrix에 미분류 route 0건, production 기동이 secret 없이는 실패.

### 8.3 성능 (계층)

- 매 PR: planner-default EXPLAIN 스모크(hot query), "query 수 ≠ batch item 수 비례" 검사,
  response-shape 회귀.
- release/cutover: 100만+ 실분포 fixture, `EXPLAIN (ANALYZE, BUFFERS)`, 서울 밀집 viewport·전국
  low-zoom·100km nearby·상용 검색어·200건 batch, N150 기준 p95·shared read·byte budget.
- 인덱스 변경 PR은 before/after write 비용 실측 첨부(GiST 6→partial 정리에서 ~1.6× 개선 실측
  선례).

## 9. 부록 — 판정 이력 포인터

본 문서의 결정 근거가 된 왕복 리뷰 원문: PR #702(§1~10 원 리뷰), #703(§11 5관점 검증 —
scratch EXPLAIN·write 실측 포함), #704(§13 대질 — retired/missing·멱등성·UNIQUE NOT VALID 판정),
#705·#706(0052 clean-cut·C3e 재분할의 물적 근거), #707(§14 — 양방향 오분류·write-fence·DDL
유형표). 세부 논증이 필요하면 해당 PR diff의 구판 §11~§14를 참조한다.
