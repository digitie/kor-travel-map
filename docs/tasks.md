# tasks.md — 백로그

진행 중/예정(`[ ]`) task만 두는 백로그. 완료·아카이브는
[`docs/tasks-done.md`](tasks-done.md), 진척·"다음 한 작업"은
[`docs/resume.md`](resume.md)가 정본이다. 작성·유지 규약은
[`docs/tasks-rule.md`](tasks-rule.md)를 따른다.

## 진행 중인 작업 인덱스

- **진행 중 — admin ops 통합 재작성 (ADR-064)**
  - [ ] `T-ADM-C6c` — **PinVi legacy ops caller canonical 전환 + 인증 계약 복구**
  - [ ] `T-ADM-C7` — **live e2e 재작성 + n150 검증** (C6c 뒤)
- **예정 — vNext 재설계 (`T-ADM-C6c`/`C7` 종결 뒤 시작)**
  - [ ] `T-VN-01` — **production fail-closed 전환**
  - [ ] `T-VN-02` — **route policy matrix와 미분류 CI gate**
  - [ ] `T-VN-03` — **잔여 운영 read·debug·public-key gate**
  - [ ] `T-VN-04` — **공개 predicate 단일화 1차**
  - [ ] `T-VN-05` — **공개 raw payload 경계 제거**
  - [ ] `T-VN-06` — **notice 방어적 cast**
  - [ ] `T-VN-07` — **no-op 옵션 삭제와 principal actor 1차**
  - [ ] `T-VN-08` — **PinVi false-broken 수정**
  - [ ] `T-VN-11` — **service batch 5-state 계약**
  - [ ] `T-VN-12` — **domain-owned Idempotency-Key 전개**
  - [ ] `T-VN-13` — **Feature row revision과 If-Match**
  - [ ] `T-VN-14` — **지도 completeness와 exact spatial predicate**
  - [ ] `T-VN-15` — **search total과 cursor fingerprint**
  - [ ] `T-VN-16` — **weather batch와 부모 404**
  - [ ] `T-VN-17` — **weather 무결성 제약**
  - [ ] `T-VN-18` — **중복 GiST 제거와 BRIN 감사**
  - [ ] `T-VN-19` — **Alembic metadata 정합 CI**
  - [ ] `T-VN-20` — **principal actor 전면 전환**
  - [ ] `T-VN-21` — **3단 성능 gate**
  - [ ] `T-VN-31` — **vNext target freeze**
  - [ ] `T-VN-32` — **UUID identity shadow 전환**
  - [ ] `T-VN-33` — **provider dataset 정본 전환**
  - [ ] `T-VN-34` — **직교 상태 모델 전환**
  - [ ] `T-VN-35` — **typed subtype 분해**
  - [ ] `T-VN-36` — **field override 단일화**
  - [ ] `T-VN-37` — **typed notice state**
  - [ ] `T-VN-38` — **weather·price current summary**
  - [ ] `T-VN-39` — **KTM·PinVi write-fence cutover**
  - [ ] `T-VN-40` — **curation write model 단일화**
  - [ ] `T-VN-41` — **cache-target generation·outbox 전파**
  - [ ] `T-VN-51` — **MVT tile 도입 조건 측정**
  - [ ] `T-VN-52` — **범용 feature-context batch 도입 조건 측정**
  - [ ] `T-VN-53` — **cursor HMAC 도입 조건 측정**
  - [ ] `T-VN-54` — **weather partition·hypertable·event clock 측정**
  - [ ] `T-VN-55` — **물리 listener/process 분리 측정**
  - [ ] `T-VN-56` — **대규모 fixture 실행 주기 측정**
  - [ ] `T-VN-H01` — **public API key header 전환**
  - [ ] `T-VN-H02` — **destructive admin 기본값 fail-closed**
  - [ ] `T-VN-H03` — **surface별 CORS 분리**
  - [ ] `T-VN-H04` — **PROJ pin·drift·REINDEX runbook**
  - [ ] `T-VN-H05` — **INVALID concurrent index 복구 runbook**
  - [ ] `T-VN-H06` — **admin 목록 keyset 전환**
  - [ ] `T-VN-H07` — **PinVi field-level contract와 OpenAPI SHA 검증**
- **보류/결정 대기**
  - [ ] `T-101` — **Materialized View 도입 검토**

## 현재 상태

`tasks.md`에는 열린 항목만 둔다. 완료된 Sprint/Phase 이력과 감사 세부 해소 항목은
[`docs/tasks-done.md`](tasks-done.md)와 [`docs/journal.md`](journal.md)를 본다. 2026-06-29
정리 기준 `T-229-buildx`는 추가 추적하지 않고, `T-AUDIT-0616` F-01 옵션 A는
ADR-058의 옵션 B 채택으로 필수 진행 백로그에서 제외한다.

## T-ADM-C — admin ops 통합 재작성 (ADR-064)

정본 설계: [`docs/reports/admin-ops-consolidation-plan-2026-07-14.md`](reports/admin-ops-consolidation-plan-2026-07-14.md)
(적대적 설계 리뷰 2인 반영 확정판). dagster job·provider 운영 표면(7페이지+홈 위젯,
4개 인증 게이트 혼재)을 `/ops/pipeline`(실행·작업)·`/ops/datasets`(상태·정책)
2페이지로 통합 재작성한다. 구 표면은 redirect 없이 폐기(공용 `GET /v1/providers`
계열은 PinVi 계약으로 존치).

- [ ] `T-ADM-C6c` — **PinVi legacy ops caller canonical 전환 + 인증 계약 복구**
  (C7 선행, PR #730 재검증에서 확정): PR #724가 `/v1/ops/dagster/summary`,
  `/v1/ops/providers*`, `/v1/ops/import-jobs*`를 clean-cut한 뒤에도 PinVi 최신 main의
  admin client·provider-sync
  proxy·unit test가 해당 경로를 호출하므로, PinVi caller를 `/v1/ops/datasets`와
  `/v1/ops/pipeline` 계약으로 전환하고 양 저장소 contract test를 같은 commit 조합으로 고정한다.
  KTM frontend BFF secret을 공유하거나 trusted frontend `/32`를 넓히지 말고, PinVi server에
  필요한 최소 service/operator principal과 route policy를 명시한다. service 권한은 canonical
  GET read와 exact import-job cancel로 제한하고 schedule/policy/request mutation은 허용하지
  않는다. n150은 `OPS_PRINCIPAL_REQUIRED=true`와 read/cancel non-empty pair를 강제하며 local
  opt-out은 both absent 또는 both explicit empty만 허용한다. 두 token은 모든 whitespace를
  금지하고 서로 및 admin BFF/service token과 달라야 한다. actor는 설정 불가능한
  `service:pinvi` 상수이고 제거된 actor env는 거부한다. OpenAPI는 GET/exact cancel만
  AdminBFF 또는 OpsToken, 나머지 mutation은 AdminBFF 전용으로 정확히 선언하며 API ops env가
  Dagster web/daemon에 들어가면 entrypoint가 fail-closed한다.
  완료 조건은 PinVi production
  코드·테스트의 삭제 경로 0건, canonical success와 principal 없음/오류 scope의 typed
  401/403/422, raw/debug/BFF 우회 0건, 배포 순서와 rollback image가 명시된 cross-repo smoke다.

- [ ] `T-ADM-C7` — **live e2e 재작성 + n150 검증** (C6c 뒤, 의존
  C6b·C7A·C7B-720·AUD-686·C7B-UI·C6c·C7C): 기존 게이트
  체계(PART A/B/C·`finally` 복원) 승계, SAFE provider(kma)·쿼터-민감 provider(OpiNet)
  금지 목록, `/preview` 우선, per-file 저부하 실행표 + 검증 리포트. 임시 POI target을
  생성·복원하며 `external_system:*` 생성/200 재사용/run-now identity, membership
  fingerprint 변화와 grid cap 초과 fail-closed·scope별 durable failure를 검증한다.
  실제 Chrome에서 없음/변조 ticket은 data frame 0건 + `CloseEvent.code===4401`,
  signed-expired ticket은 data frame 0건 + `4408` 후 fresh ticket 재연결을 증거로
  남긴다. n150 host runner는 `python3`를 명시적으로 요구하고, 실행 전 root-owned host/origin
  attestation을 local-only 운영 절차로 provision한다. 운영 종결이 남은 #684/#694/#712/#719는
  최종 live 증거를 첨부한 뒤 닫는다.

병렬 wave는 다음처럼 고정한다. **Wave 1**의 C6b·C7A/0055·C7B-720,
**Wave 2**의 AUD-686·AUD-718/0056, **Wave 3**의 C7B-API/0057,
**Wave 4**의 C7B-UI까지 완료했다. 현재는 누락된 소비자 선전환을 C6c로 복구한 뒤
C7 n150을 수행한다.
C45X-B·C4/C4R·C5·C6a·C6b·C7A·C7B-720·AUD-686·AUD-718·C7B-API·C7B-UI·C7C·C7M은
완료 이력으로 옮겼다. 각 wave 시작·PR 직전·병합 직후 원격 main에 자주 rebase한다.

Alembic은 병렬 branch에서 복수 head를 만들지 않는다. migration 정본은
**C7A `0055` → AUD-718 `0056` → C7B-API `0057`** 단일 chain이며, 후속 migration
소유자는 직전 migration PR이 main에 병합된 뒤 실제 `down_revision`을 확인하고
착수한다. C7B-720·AUD-686·C7B-UI는 migration을 만들지 않는다.

공통 규율: 잦은 rebase(origin/main), task 완료 시 상대 agent 2일치 PR(닫힘 무관,
리뷰 반영 PR 제외) 적대적 리뷰→코멘트→이슈→수정→머지. 각 구현 PR은 테스트 전
적대적 리뷰어 1명의 리뷰를 반영한다. 문서 전용 PR, rebase-only, 변수명 수정·import 정렬 같은
기계적 변경은 추가 적대적 재리뷰 없이 진행한다.

## T-VN — vNext 재설계 전개 (ADR-066~075)

정본은 [`system-structure-api-schema-review-2026-07-16.md`](reports/system-structure-api-schema-review-2026-07-16.md)와
ADR-066~075다. **`T-VN-00`은 별도 task가 아니라 `T-ADM-C6c`의 별칭**이므로 checkbox를
중복 생성하지 않는다. 같은 wave에서 의존성이 없는 task는 agent A/B가 병렬 수행하되
PR 하나가 task 하나만 소유하고 시작·PR 직전·merge 직후 `origin/main`에 rebase한다.
각 코드 PR은 테스트 전에 적대적 리뷰어 1명의 리뷰를 반영한다. 문서 전용·rebase-only·단순
변수명/import 정렬 변경은 추가 적대적 재리뷰 대상이 아니다.

#### Lane 분배 (2026-07-19, issue #738)

KTM 내부 표면은 agent A(Claude), PinVi 결합·C6c cutover 결합·기존
ledger(0054/0055)·POI causal(ADR-065) 기반 위 작업은 agent B(codex)가 소유한다.
A lane은 즉시 착수하고, B lane은 `T-ADM-C6c`/`T-ADM-C7` 종결 뒤 착수한다.

| lane | 담당 | 순서 | 비고 |
|---|---|---|---|
| a1 | Claude | T-VN-01 → T-VN-02 → T-VN-07 → T-VN-19 | 기동 fail-closed → route matrix → actor 1차 → alembic 정합 CI |
| a2 | Claude | T-VN-04 → T-VN-06 → T-VN-05 → T-VN-17 | 공개 predicate view → notice cast → raw payload 경계 → weather 제약 |
| b1 | codex | T-VN-03 → T-VN-11 → T-VN-12 | T-VN-03은 C6c principal cutover와 **같은 배포 단위**(F-17 재발 방지) |
| b2 | codex | T-VN-08 → T-VN-16 → T-VN-41 | PinVi consumer 수정 → weather batch(N+1 제거) → cache-target outbox |

migration 번호는 a2가 0059를 예약했고, 이후 branch는 PR 직전 rebase에서 단일 head를
재확인 후 재번호한다. T-VN-13/14/15/18/20/21과 Wave 2(T-VN-31~40)는 위 lane 소화 후
재분배한다. 같은 파일 충돌 시 먼저 머지된 쪽이 우선하고 나중 PR이 rebase한다.

**통합 브랜치 규율**: `T-ADM-C7` 종결 전까지 모든 T-VN task PR(a·b lane 공통)의 base는
main이 아니라 **`integration/t-vn`**이다. task branch → `integration/t-vn` PR(CI green 후
머지)로 쌓고, main의 변경은 주기적으로 `integration/t-vn`에 merge해 동기화한다
(공유 브랜치이므로 rebase 금지). C7 종결 후 `integration/t-vn` → main PR 1건으로 합류하며,
그 전에는 T-VN 변경이 main에 직접 들어가지 않는다. CI workflow 4종은
`integration/t-vn` 대상 push/PR에도 동일하게 실행된다.

### Wave 0 — P0, 즉시 가역

- [ ] T-VN-01 — **production fail-closed 전환**

  Production profile에서 필수 secret 누락 시 기동을 거부하고 local-dev fallback을 별도 profile로
  격리한다. 수용 기준은 ADR-066과 보고서 D-1·§8이다.

- [ ] T-VN-02 — **route policy matrix와 미분류 CI gate**

  전 HTTP/WS route 분류 생성기, 미분류 CI 실패, `/metrics` management 경계를 구현한다.
  ops-live는 기존 HMAC ticket을 재사용하고 인증을 중복 구현하지 않는다.

- [ ] T-VN-03 — **잔여 운영 read·debug·public-key gate**

  ops metrics/log/consistency와 MOIS raw debug를 operator/debug로, 무키 legacy curated read를
  public-keyed로 옮긴다. PinVi principal 선전환과 같은 cutover에서 수행하며 삭제 route는 복원하지 않는다.

- [ ] T-VN-04 — **공개 predicate 단일화 1차**

  현행 상태 위에 `feature.public_features` view를 만들고 모든 공개 SQL을 그 projection으로
  교체해 retired 은닉과 draft/broken 노출을 동시에 막는다.

- [ ] T-VN-05 — **공개 raw payload 경계 제거**

  공개 DTO의 raw data/hash/source record와 MOIS `detail.payload` passthrough를 제거하고 observation
  lineage를 operator 표면으로 이동한다. service batch는 고정 typed payload만 반환한다.

- [ ] T-VN-06 — **notice 방어적 cast**

  오염된 notice timestamp 한 행이 전체 공개 read를 500으로 만들지 않도록 안전한 1차 완화를
  적용한다. typed notice 재설계는 T-VN-37이 소유한다.

- [ ] T-VN-07 — **no-op 옵션 삭제와 principal actor 1차**

  실제 동작하지 않는 beach 옵션을 OpenAPI와 코드에서 제거하고 auth-event 등 최소 write 경로에서
  body actor 우선을 없앤다.

- [ ] T-VN-08 — **PinVi false-broken 수정**

  transport 실패와 authoritative missing을 분리해 실패 시 stale snapshot을 유지하고 brittle ID
  parsing을 제거한다. 5-state 계약 소비 준비까지 PinVi consumer task로 mirror한다.

### Wave 1 — additive 조기 전개

- [ ] T-VN-11 — **service batch 5-state 계약**

  `found|retired|suppressed|missing|unchanged`와 revision을 반환하고 transport 실패를 503으로 분리한다.
  PinVi typed consumer contract test를 같은 cutover 산출물로 둔다.

- [ ] T-VN-12 — **domain-owned Idempotency-Key 전개**

  기존 pipeline/schedule ledger를 회귀 기준선으로 두고 남은 retryable command에 body fingerprint,
  result replay, key reuse 409를 domain별로 구현한다.

- [ ] T-VN-13 — **Feature row revision과 If-Match**

  Feature에 단조 revision을 추가하고 correction PATCH/DELETE에 `If-Match`/412, read에 ETag/304를
  연결한다. policy revision ledger와 합치지 않는다.

- [ ] T-VN-14 — **지도 completeness와 exact spatial predicate**

  in-bounds의 mode/truncated/coverage/cluster key를 명시하고 `include_geometry`를 serialization으로만
  사용한다. candidate 술어를 하나로 만들고 exact `ST_Intersects`를 적용한다.

- [ ] T-VN-15 — **search total과 cursor fingerprint**

  `include_total=false`에서 COUNT를 실행하지 않고 cursor version·query fingerprint를 검증해 다른
  query 재사용을 typed error로 거부한다.

- [ ] T-VN-16 — **weather batch와 부모 404**

  set-based weather batch와 `target_at`/`known_at` parameter를 제공해 PinVi N+1을 없애고 존재하지
  않는 parent feature를 빈 결과가 아닌 404로 구분한다.

- [ ] T-VN-17 — **weather 무결성 제약**

  semantic UNIQUE를 concurrent writer cutover와 함께 도입하고 range/payload CHECK와 source FK는
  `NOT VALID`→`VALIDATE`로 적용한다.

- [ ] T-VN-18 — **중복 GiST 제거와 BRIN 감사**

  자동 full GiST를 제거하고 필요한 partial GiST만 유지한다. 전후 write 비용과 hot query를 실측하고
  weather/price BRIN은 실제 누락된 시간축만 보강한다.

- [ ] T-VN-19 — **Alembic metadata 정합 CI**

  모든 소유 table mapping/include filter를 정리하고 빈 PostGIS DB의
  `alembic upgrade head && alembic check`를 상시 CI gate로 만든다.

- [ ] T-VN-20 — **principal actor 전면 전환**

  모든 write schema에서 body `operator`/`actor`/`created_by`/`reviewed_by`를 제거하고 제출·승인
  principal을 인증 context에서 보존해 ADR-066의 actor 결정을 완결한다.

- [ ] T-VN-21 — **3단 성능 gate**

  PR planner-default smoke·query-count/shape, release 실분포 분석, index before/after write 비용의
  3단 gate를 CI와 release 절차에 연결한다. 정본은 performance.md의 vNext 절이다.

### Wave 2 — shadow와 write-fence 구조 전환

- [ ] T-VN-31 — **vNext target freeze**

  ADR-066~075, 목표 OpenAPI diff, 목표 DDL과 제약 테스트를 실행 전 고정한다. 이 task는 구현
  변경을 섞지 않고 소비자·복구 preflight의 입력을 확정한다.

- [ ] T-VN-32 — **UUID identity shadow 전환**

  UUID column과 legacy alias를 backfill하고 FK·notice lineage·PinVi alias-map의 consumer-first
  전환을 준비한다. legacy ID 제거는 soak 뒤 별도 단계다.

- [ ] T-VN-33 — **provider dataset 정본 전환**

  `provider_datasets`를 신설하고 참조 table을 FK화하며 source record denormalization을 제거한다.
  전환기에는 composite FK로 entity-record identity 불일치를 먼저 막는다.

- [ ] T-VN-34 — **직교 상태 모델 전환**

  lifecycle/publication/quality 3축과 결합 CHECK를 backfill하고 `public_features` view와 partial index를
  새 정본으로 전환한다.

- [ ] T-VN-35 — **typed subtype 분해**

  core와 point/event/notice/route/area subtype을 typed table·geometry/category 제약으로 분리한다.
  subtype별 독립 shadow 전환과 rollback을 증명한다.

- [ ] T-VN-36 — **field override 단일화**

  whole-row freeze를 field override로 이관하고 effective projection을 대조한 뒤 provider upsert의
  중복 `CASE`를 제거한다. T-VN-35와 독립 rollback 가능해야 한다.

- [ ] T-VN-37 — **typed notice state**

  notice 유효 기간을 typed range와 DB 제약으로 재설계하고 공개 hot path의 cast·lineage anti-join을
  제거한다.

- [ ] T-VN-38 — **weather·price current summary**

  원본 이력을 보존하는 current summary projection을 만들고 bbox/detail의 per-row LATERAL 조회를
  set-based join으로 바꾼다.

- [ ] T-VN-39 — **KTM·PinVi write-fence cutover**

  보존 분류, restore/PITR 또는 journal 검증, shadow checksum, consumer-first 배포, write fence,
  순차 전환, soak, legacy 제거를 ADR-075 절차대로 수행한다.

- [ ] T-VN-40 — **curation write model 단일화**

  `curation_collections/items`만 write 정본으로 남기고 legacy table·trigger·route를 제거한다.
  자동 후보는 `theme_feature_candidates`처럼 별도 lifecycle로 분리한다.

- [ ] T-VN-41 — **cache-target generation·outbox 전파**

  기존 external identity와 exact scope를 유지하면서 source generation/restore epoch, outbox relay,
  backfill·reconciliation을 설치하고 critical path 밖에서 enable한다.

### Wave 3 — 도입 조건을 먼저 측정

- [ ] T-VN-51 — **MVT tile 도입 조건 측정**

  전국 low-zoom 응답 byte·p95와 현재 cluster 계약을 측정하고 MVT가 정한 budget을 유의미하게
  개선할 때만 별도 구현 task를 연다.

- [ ] T-VN-52 — **범용 feature-context batch 도입 조건 측정**

  실제 consumer round-trip과 query count를 측정해 weather 전용 batch를 넘어선 범용 batch의
  필요 조건·최대 크기·응답 shape를 먼저 고정한다.

- [ ] T-VN-53 — **cursor HMAC 도입 조건 측정**

  fingerprint cursor의 위변조 위험과 운영 비용을 측정하고 서명 필요성이 입증될 때 key rotation과
  실패 계약을 포함한 구현 task를 연다.

- [ ] T-VN-54 — **weather partition·hypertable·event clock 측정**

  3년 데이터량, ingest/update 비율, retention query를 실측해 native partition 또는 hypertable 후보와
  event clock 직렬화의 채택 기준을 문서화한다.

- [ ] T-VN-55 — **물리 listener/process 분리 측정**

  단일 app의 resource contention과 장애 격리를 측정해 세 listener가 배포 복잡성보다 큰 이득을
  줄 때만 분리 설계를 연다.

- [ ] T-VN-56 — **대규모 fixture 실행 주기 측정**

  100만+ fixture gate의 시간·비용과 결함 검출률을 수집해 매 PR, nightly, release 중 적절한 실행
  주기를 확정한다.

### 독립 하드닝 — 각 항목 PR 1개

- [ ] T-VN-H01 — **public API key header 전환**

  URL query key를 header로 clean-cut해 로그·referrer 노출을 막고 public OpenAPI와 consumer를 함께
  갱신한다.

- [ ] T-VN-H02 — **destructive admin 기본값 fail-closed**

  `admin_destructive_enabled` 기본값을 False로 바꾸고 production에서 명시적 enable과 감사 로그를
  요구한다.

- [ ] T-VN-H03 — **surface별 CORS 분리**

  public/service/operator surface별 origin·header·method 정책을 나누고 wildcard와 credential 조합을
  거부한다.

- [ ] T-VN-H04 — **PROJ pin·drift·REINDEX runbook**

  `coord_5179` generated 값의 PROJ 버전을 고정하고 drift 검사, 재계산, 공간 index REINDEX와 검증
  순서를 운영 runbook에 추가한다.

- [ ] T-VN-H05 — **INVALID concurrent index 복구 runbook**

  `CREATE INDEX CONCURRENTLY` 실패 뒤 남은 INVALID index를 탐지·검증·drop하는 자동 검사와 운영
  절차를 추가한다.

- [ ] T-VN-H06 — **admin 목록 keyset 전환**

  OFFSET 기반 admin 목록을 stable total-order keyset과 fingerprint cursor로 바꾸고 page 경계
  mutation 회귀를 검증한다.

- [ ] T-VN-H07 — **PinVi field-level contract와 OpenAPI SHA 검증**

  양 저장소 contract test를 required/type/enum 필드까지 강화하고 배포 compatible pair에 pinned
  OpenAPI SHA manifest를 요구한다.

## T-101 — Materialized View 도입 검토

- [ ] T-101 — **클러스터 rollup Materialized View 검토**

`docs/architecture/performance.md §9.3` 기준. detail flatten MV는 제외한다. 1순위
후보는 `mv_feature_cluster_counts`이며, exact-viewport와 region-total 의미 차이를
시범 PR에서 먼저 결정해야 한다. 도입 시 `REFRESH MATERIALIZED VIEW CONCURRENTLY`용
`UNIQUE` 인덱스와 batch gate 연결을 함께 설계한다.
