# kor-travel-map vNext 재설계 정본 — 설계 결정·목표 구조·실행 계획

> 작성일: 2026-07-18 (최신 코드 3차 재검증판)
> 기준: KTM `origin/main@13eb8d40` · PinVi `origin/main@48085afb`
> 반영: PR #730(2차, merge `d0609226`) → PR #732(3차, 본 판)
> 정본 전개: PR #736(`docs/vnext-review-propagation`)에서 ADR-066~075와
> architecture/tasks/runbook에 전개했다.
> 전신: 본 문서는 PR #702(원 리뷰 §1~10) → #703(§11 Claude 다관점) → #704(§12 Codex 재검토
> 병합본 위 §13 대질·수렴) → #707(§14 Codex 재보강)의 **왕복 리뷰 4회를 소화한 최종 정본**이다.
> 왕복 세부(§11~§14의 개별 논증·정정 이력)는 git 이력(위 PR들)에 보존되며, 본 문서는 그
> **최종 유효 판정과 실행 계획만** 담는다. PR #708의 전면 재작성은 PR #717에서
> canonical operation 체인(#709/#710/#711/#713/#714/#715), scope 멱등성(#701), datasets
> 통합 UI(#698)까지 1차 재검증했다. 이번 판은 그 뒤의 C5~C7B 구현(#691, #721~#729)과
> PinVi 최신 `origin/main`을 다시 대조한 결과를 기존 판정·결정·실행 계획 안에 직접 반영했다.
> 충돌 시 본 문서가 우선한다.

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

4회 왕복(§11~§14)에서 검증·정정을 거쳐 확정한 사실을 최신 기준선에서 다시 판정했다. 최신
구현이 일부 해소한 항목은 **현재 구현 범위**와 **남은 목표**를 같은 행에 구분했다. 특히
KTM 내부 green만으로 cross-repo 계약이 보존됐다고 간주하지 않고, PinVi `origin/main`의 실제
호출 문자열과 KTM의 현재 OpenAPI route를 정적으로 대조했다.

| # | 확정 판정 | 근거 요지 |
|---|---|---|
| F-1 | **공개 상태 오분류는 양방향이다**: provider-retired(inactive+deleted_at)는 공개/서비스 batch에서 `missing`으로 은닉되고, admin-inactive·draft·broken(deleted_at 미세팅)은 `found`로 노출된다 | `_is_public_feature`가 hidden/deleted 2종+`deleted_at IS NULL`만 검사(`features.py:65,489-494`); provider retire는 deleted_at 세팅(`feature_repo.py:1491-1492`), admin deactivate는 미세팅(`admin_feature_repo.py:1365-1379`) |
| F-2 | **HTTP replay는 두 운영 command군에서 구현됐지만 범용 계약과 Feature revision은 남았다**: 0054는 feature-update create에 `(actor, Idempotency-Key)` append-only ledger·request fingerprint·terminal replay/불일치 409를, schedule command에 append-only audit·active claim·불명 결과 수동 해소를 구현했다. #701의 exact-scope active UNIQUE는 업무 single-flight로 계속 직교하며, #727의 policy `revision` CAS도 갱신 정책 한정이다. 다른 command route와 Feature 행에는 같은 replay/If-Match 계약이 없고, `data_version`은 provider-owned 행에서 0이라 ETag validator가 될 수 없다 | `0054_dagster_schedule_audit.py:24-260`; `ops_pipeline.py:1732-2008`; `0056_provider_refresh_policy_revision.py:23-37`; `feature_repo.py:235-240` |
| F-3 | **운영 인증은 크게 좁아졌지만 route policy는 아직 부분적이다**: #724가 legacy command 28개와 live ETL을 삭제했고 #725가 ops-live에 same-origin BFF 발급 HMAC ticket·DB nonce 단일 소비·60초 lease를 설치했다. Docker entrypoint도 admin proxy secret을 fail-closed한다. 반면 `/v1/ops/{metrics,system-logs,api-call-logs,consistency/*}`는 여전히 무의존 mount이고, **`/v1/debug/mois-license/*`는 무게이트로 `source_records.raw_data`를 반환**하며 `/metrics`도 인증이 없고, 공개 read 중 legacy `/v1/curated-*`만 `require_public_api_key` 의존 없이 mount돼 `public_api_key_required=True`여도 키 없이 열린다(`app.py:548`). 앱 settings 자체는 service/admin/public key 미설정 시 통과하므로 비-Docker production profile과 미분류 route CI가 없다 | `app.py:396-398,523-666`; `ops_live.py:1020-1085`; `mois_detail.py:1-118`; `auth.py:115-233`; `docker/api-entrypoint.sh:24-34` |
| F-4 | **canonical ops actor는 principal로 수렴했지만 legacy admin write가 남았다**: pipeline request/cancel/schedule·curation collection write는 `context.actor`를 쓴다. 반면 admin Feature create/patch/delete/review/deactivate, legacy curated select/unselect, admin auth-event에 더해 data-integrity 이슈 액션, offline upload 생성·검증, dedup/enrichment 검수도 body `operator`/`actor`/`created_by`/`reviewed_by`를 감사 actor로 저장한다. PinVi client는 이 중 admin Feature·curated·auth-event·이슈 액션·dedup 검수에서 해당 필드를 계속 전송한다(enrichment 검수·offline upload는 PinVi 미호출) | `ops_pipeline.py:1369-1992`; `curations.py:865-1065`; `admin_features.py:853-1011`; `curated.py:1123-1174`; `admin_auth.py:187-202`; `admin_issues.py:437,567,616`; `offline_uploads.py:780,838,1146,1165`; `dedup_review.py:432,464`; `enrichment_review.py:381`; PinVi `kor_travel_map_admin.py:260-319,437-455,488-502` |
| F-5 | **Feature ID(64-bit SHA-1 prefix)는 정본 identity로 부적합**: 코드 주석의 "10^9건 충돌 ~3e-11"은 birthday bound(≈2.7%) 오인. 게다가 bjd/category가 해시 입력이라 보정만으로 재키잉 발생(코드가 자인) | `ids.py:68-70,149-154` |
| F-6 | **source lineage denorm 미정합**: head-pointer deferrable FK는 존재하나, `source_records`의 denorm identity 4튜플(provider/dataset/type/id)이 부모 entity와 일치하도록 강제하는 composite FK는 없다(entity A에 provider B record 연결 가능) | `models.py:431-440,519-533` |
| F-7 | **weather/price 비대칭**: weather에는 semantic UNIQUE·source-record FK·`valid_from<=valid_until` CHECK가 없다. price는 semantic UNIQUE·source-record FK·nonnegative CHECK를 보유한다. PG16에서 UNIQUE는 `NOT VALID` 불가 — `CREATE UNIQUE INDEX CONCURRENTLY`(+writer conflict target 배포와 **같은 cutover**)로 도입해야 한다 | `0017` vs `0034` DDL; PG16 문법 사실 |
| F-8 | **공간·조회 결함**: `include_geometry`가 응답이 아닌 **결과집합**을 바꿈(EXPLAIN 재현 2220→2221행), `&&`-only MBR false positive 실재, bbox LATERAL이 kind 무관 매행 실행, GiST 6개(자동 full 3 + 수동 partial 3)로 write ~1.6×, `include_total=false`여도 COUNT 무조건 실행, cursor가 query 파라미터 미포함(재사용 시 조용한 누락/중복) | `feature_repo.py:689,828,963,3534,3766-3788`; `models.py:204-221,288-297`; scratch EXPLAIN 실측 |
| F-9 | **notice cast 취약**: `detail->>'valid_end_time'` timestamptz 직접 cast — 오염 row 1건이 모든 공개 read를 500으로 만들 수 있고, lineage anti-join이 모든 공개 read의 상시 hot-path 비용 | `feature_repo.py:533-539,638` |
| F-10 | **Alembic metadata ≠ schema**: weather/price/log/api-key/auth-event 등 table이 `models.metadata`에 없고 `include_object` 콜백도 없어 clean DB `alembic check`가 실패(PostGIS object까지 drop 후보) | `env.py:54,65,82` |
| F-11 | **migration 방식은 변경 성격별로 더 분화됐다**: 0051은 additive, 0052는 maintenance clean-cut, 0053·0057은 additive shape/backfill에 30초 획득 상한의 `ACCESS EXCLUSIVE`와 trigger/index 원자 교체를 결합했다. 0054·0055는 소형 ops table/append-only trigger 신설, 0056은 소형 table의 revision column+CHECK다. "전부 additive"도 "전부 clean-cut"도 아니며 **lock mode·획득 상한·보유 시간을 별도 판정하는 D-12가 유효**하다 | `0053`:167-194,439-507; `0054`:24-260; `0055`:23-173; `0056`:23-37; `0057`:52-84,249-299 |
| F-12 | **rollback은 snapshot 보존만으로 불성립**: 쓰기 재개 후 old snapshot 복원은 사이 write를 유실한다. 현재 도구는 cold backup뿐(WAL archiving/PITR/journal 0건) → write-freeze 유지 또는 forward journal replay가 완료 조건 | `docs/backup-restore.md`; scripts/ 실태 |
| F-13 | **재취득은 유일 복구 전략이 될 수 없다**: 3년 보존 weather·창이 닫힌 feed는 upstream이 재서빙하지 않고, 전국 재수집은 quota(OpiNet 실증)·WAL(MOIS 실증)·시간에서 비현실적. 정본 이관은 DB-to-DB, 검증된 파생만 재계산 | ADR-062; 운영 실증(quota·WAL 사고 이력) |
| F-14 | **PinVi 소비측 결함**: client는 batch `missing`을 파싱하지만 trip view 소비 계층이 authoritative missing과 transport 실패를 모두 전건 broken으로 축약한다. TripMap은 서버 cluster를 폐기하고, weather는 POI별 N+1이며, admin client는 Idempotency-Key/If-Match를 보내지 않는다. `TripDayPoi.version`도 soft delete에서 증가하지 않아 generation으로 부적합하다 | PinVi `kor_travel_map.py:240-261`; `trip_view_builder.py:131-168`; `TripMapView.tsx:144-159`; `TripWeatherSummary.tsx:123-143`; `services/poi.py:169-171` |
| F-15 | **PinVi 라이브 소비 전제**: 운영상 소비 중으로 간주하되(공유 n150 가동·운영 노트), cutover preflight에서 runtime 증거(`/version`·`api_call_logs` nonzero·smoke)로 최종 확정한다 | §13.3↔§14.6 합의 위치 |
| F-16 | **curation 정본이 두 개**: legacy `curated_features`와 신규 `curation_collections/items`가 title/status/relation을 중복 저장하고 trigger가 legacy→신규 단방향만 동기화 — legacy 수정이 collection을 강제 `published`/`archived_at=NULL`로 되돌릴 수 있다(왕복 4회에서 반박된 적 없는 유효 진단) | §구판 P1-7; migration trigger 실태 |
| F-17 | **#724 clean-cut이 PinVi 선전환보다 먼저 병합돼 현재 cross-repo 계약이 끊겼다**: KTM은 `/v1/ops/dagster/summary`, `/v1/ops/providers*`, `/v1/ops/import-jobs*`를 삭제했지만 PinVi 최신 main의 admin client·provider-sync proxy·unit test는 그대로 호출한다. 같은 버전을 배포하면 provider-sync proxy는 upstream 404를 반환하고 ETL summary는 오류를 모아 degraded/down으로 축약한다. 새 `/v1/ops/{datasets,pipeline}`는 BFF admin gate이고 Docker가 frontend 고정 `/32`만 신뢰하므로 경로만 바꿔도 PinVi service 호출은 403이다. 별도 service/operator principal과 소비자 선배포가 필요하다 | KTM `test_admin_ops_clean_cut.py:8-48`, `docker-compose.yml:117-120`; PinVi `kor_travel_map_admin.py:338-404`, `provider_sync.py:28-141`, `admin_etl.py:359-391`, `test_kor_travel_map_admin_client.py:437-554` |

이번 2차 재검증은 한 종류의 diff review로 끝내지 않고 다음 경계를 교차 확인했다.

| 관점 | 확인 대상 | 이번 판정에 반영한 결과 |
|---|---|---|
| REST/API | `app.py` mount dependency, canonical router, generated OpenAPI, clean-cut test | 삭제/존치 route와 operator gate를 분리하고 PinVi의 실제 legacy caller를 F-17로 승격 |
| DB/동시성 | Alembic 0054~0057, command service·repository test | domain ledger·claim·CAS·exact-scope를 완료 기준선으로 인정하고 범용 ledger 과설계를 철회 |
| 보안/감사 | BFF secret·trusted CIDR, WebSocket ticket, actor 저장 원천 | #725 해소 범위와 잔여 무게이트 read/body actor를 분리 |
| 데이터·성능 | migration lock, exact-scope index·cursor, Feature revision | 30초 lock 획득 상한과 Feature row validator 미해결을 별도 운영 gate로 유지 |
| cross-repo 소비 | PinVi `origin/main` client·proxy·summary builder·unit test | provider-sync 404, ETL degraded/down, canonical route의 403 선행 위험을 재현 가능한 계약 단절로 확정 |
| 운영 | repository 증거와 n150 적용 증거 분리 | 이 판은 정적 코드/계약 검토이며 0053~0057 n150 적용·live E2E는 C6c 뒤 C7에서 검증 |

**유지가 확정된 기존 설계**(재설계에서 버리지 않는다): immutable `source_records` 분리,
WGS84+5179 이중 표현과 GiST 반경 조회, keyset pagination, RFC7807 problem+json(+중앙 핸들러의
stack 미노출), PinVi의 OpenAPI HTTP 경계(직접 DB/패키지 접근 금지), canonical operation
영속화·실행 manifest·양방향 reconcile·typed scope·append-only command audit·exact-scope history
(0050~0057, #709/#710/#711/#713/#714/#715·#701·#691·#725~#729),
provider×dataset×scope datasets 운영 화면(#698·#723).

## 2. 설계 결정 (ADR 후보)

각 결정은 독립 ADR로 전개 가능한 형태다. 형식: 컨텍스트 → 결정 → 근거 → 영향.
**공통 원칙**: §0의 서열. "기존 계약 유지"는 결정 사유가 될 수 없다.

### D-1. 인증·라우트 경계 — fail-closed + route policy matrix

- **컨텍스트**: F-3. 인증 게이트가 라우터별로 산발 배선되고 기본값이 전부 fail-open이라, 설정
  하나 빠지면 내부 상태가 열린다. #724의 legacy command 삭제, #725의 ticket WebSocket,
  Docker admin secret 기동 검사는 올바른 선례다. 남은 문제는 관측/log/consistency와 raw MOIS
  debug read, 무키 legacy `/v1/curated-*` 공개 read, `/metrics`, 비-Docker profile,
  public/service opt-out을 한 정책으로 검증하지 않는 점이다.
- **결정**:
  1. 모든 Starlette route와 WebSocket을 `public-unauthenticated`(liveness/version) /
     `public-keyed` / `service` / `operator` / `debug` / `metrics` 중 하나로 분류하는
     **route policy matrix를 코드에서 생성**하고, 미분류 route가 있으면 CI를 실패시킨다.
  2. **production profile은 fail-closed**: service/admin/operator secret이 없거나 debug live가
     인증 없이 켜져 있으면 **기동 자체가 실패**한다. `local-dev` fallback은 non-production
     profile에서만 허용.
  3. 현재 남은 `/ops/{metrics,system-logs,api-call-logs,consistency/*}`와
     `/debug/mois-license/*`를 operator/debug 정책에, 무키 legacy `/v1/curated-*` 공개 read를
     public-keyed 정책에 배선하고 raw provider payload는 operator projection으로만 반환한다.
     `/ops/*` 관측 route는 PinVi admin proxy가 라이브 소비 중이므로 배선 시점을
     T-VN-00(service/operator principal)과 조율한다. 삭제된 legacy command/live ETL은
     되살리지 않는다.
  4. `/metrics`는 scrape identity 또는 management 경계로 제한한다. WebSocket은 #725의
     same-origin BFF → HMAC subprotocol ticket → DB nonce 단일 소비 → bounded lease를 정본으로
     유지하고 route matrix가 이 예외 인증도 검사한다.
  5. **물리적 3-app/listener 분리는 하지 않는다**(측정 후 재검토) — 단일 app + 그룹별 의존성
     주입 + **공개 경로 전용 read-only DB role**로 동일한 실질을 달성한다.
- **근거**: 위협의 실체는 "분리 부재"가 아니라 fail-open 기본값과 배선 누락이다. 단일 N150
  1~2인 운영에서 3개 배포 유닛은 §0-3(단순성) 위반.
- **영향**: `app.py`/`auth.py`/`settings.py`의 잔여 fail-open 제거, route matrix 생성기+CI 게이트,
  PinVi server-to-server operator principal(D-11/F-17), runbook의 노출 전제 갱신.

### D-2. actor 정본 — 인증 principal에서만 파생

- **컨텍스트**: F-4. canonical pipeline·schedule·curation collection은 principal actor를 쓰지만
  legacy feature·curated status·auth-event와 data-integrity 이슈 액션·offline upload·
  dedup/enrichment 검수는 body `operator`/`actor`/`created_by`/`reviewed_by`를 감사 기록에
  저장해 신뢰 경계 안에서 위조가 가능하다.
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
     `feature.public_features` VIEW로 정의하고 base table에는 같은 술어의 partial index를 둔다.
     모든 공개 read와 service batch의 **payload projection**(단건·batch·bbox·search·nearby·cluster·
     tile·collection)은 이 정본만 사용한다.
  3. service batch는 **item-state 계약**을 반환한다:
     `found | retired | suppressed | missing | unchanged` (+ `revision`). transport 실패는 503이며
     item을 `missing`으로 합성하지 않는다. service-token 전용 state classifier만 base row의
     lifecycle/publication/quality를 읽을 수 있고, 비공개 payload나 raw provider 값은 반환하지 않는다.
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
  denorm identity가 부모 entity와 어긋날 수 있다. 최신 코드에는 API 표시·capability용
  `provider_catalog`와 Dagster 실행 job/asset→exact pair/version용 `feature_operation_registry`가
  각각 존재하므로 둘의 역할도 DB identity와 분리해야 한다.
- **결정**:
  1. `provider_sync.provider_datasets`를 **영속 identity 정본 테이블**로 신설한다. **DB가 정본을
     소유**한다(정본 복제 금지).
  2. 코드 projection은 둘로 역할을 고정한다. `provider_catalog`는 표시·preview·refresh capability,
     `feature_operation_registry`는 실행 가능한 Dagster job/asset·exact pair·manifest version을
     담당한다. 둘 다 DB identity를 참조·검증하며 provider/dataset identity를 독립 소유하지 않는다.
  3. 계층: `provider_datasets → source_entities → source_records(immutable)` +
     `source_entity_heads`(current pointer 분리로 순환 FK 제거).
  4. 최종 스키마에서 record의 denorm identity 열은 **제거**한다(전환기에는 정합 composite FK가
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

- **컨텍스트**: F-7·§구판 P1-6. weather에는 PK·Feature FK·value-present CHECK는 있으나 semantic
  UNIQUE·source FK·시간 range CHECK가 없다. card는 "가장 먼 미래", marker는 "now 최근접"으로
  같은 데이터가 화면마다 다르고, asof가 발행시각을 바운드하지 않아 미래지식이 샌다.
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
  5. 기존 weather/price 시간 BRIN을 먼저 감사·유지하고, partition/hypertable·event clock
     직렬화는 retention·write/read **실측 후** 결정.
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
  5. weather 단건은 부모 공개 확인(없으면 404), **`POST /v1/features/weather/batch`**(set-based,
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

### D-10. write 안전성 — Idempotency-Key protocol + domain ledger + row_revision/If-Match

- **컨텍스트**: F-2·F-14. #701은 active scope single-flight를, 0054/#691은 feature-update create와
  schedule command의 terminal replay·불명 결과 claim을, #727은 refresh-policy CAS를 해결했다.
  이 구현들은 멱등성의 도메인별 상태가 서로 다름을 입증한다. 아직 다른 command route와 Feature
  행의 동시 수정 계약은 없고 기존 generation/data_version/TripDayPoi.version은 validator로
  부적합하다.
- **결정**:
  1. 모든 재시도 가능 command는 `(principal, operation, Idempotency-Key)` + canonical request
     hash를 공통 HTTP 계약으로 사용한다. 같은 key·같은 body는 저장된 결과를 replay하고, 같은
     key·다른 body는 409다.
  2. **저장소는 도메인 lifecycle이 소유한다.** 0054의
     `feature_update_request_idempotency`와 schedule audit/active-claim/resolution을 유지하며,
     그 위에 중복 범용 ledger를 만들지 않는다. 동일한 단순 lifecycle을 공유하는 command가
     실제로 둘 이상일 때만 공용 table/helper를 도입한다. fingerprint·problem code·header 생성은
     공통 유틸리티로 통일할 수 있다.
  3. PATCH/DELETE: **`row_revision`**(신설, 모든 Feature write에서 단조 증가) 기반 `If-Match` — 누락
     428, stale 412. 비동기 검수는 승인 시점에 base revision 재검사.
  4. 전개 순서: 이미 완료된 canonical 갱신요청/schedule은 회귀 기준선으로 고정 → 남은
     create/command route inventory → correction PATCH/DELETE → 조회 ETag(D-9-8). #727 policy
     revision은 Feature row revision이 아니라 해당 resource의 선례로 유지한다.
  5. PinVi: 모든 재시도에 동일 Idempotency-Key 유지, POI 전파는 outbox
     sequence(+restore epoch)를 generation으로 사용(`TripDayPoi.version` 미신뢰 — F-14),
     relay 상태·주기 reconciliation job 포함. cache-target 동기화는 **critical path에서 분리**.
  6. 현행 `(provider,dataset_key,sync_scope)` active partial UNIQUE와 동일 계획 재사용은 **업무
     불변식으로 유지**한다. ledger는 HTTP key/body/result replay를 담당하므로 둘은 직교한다.
     같은 active scope·다른 계획의 409와 같은 Idempotency-Key·다른 body의 409를 별도 계약으로 둔다.
- **영향**: 기존 도메인 ledger 보존, 남은 write 라우터의 protocol 전개, Feature row revision,
  PinVi client/relay. "하나의 범용 table" 자체는 목표가 아니다.

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
  5. **소비자 선전환**: PinVi의 legacy admin `ops/*` 호출자를 canonical datasets/pipeline으로
     옮기고 consumer contract test를 통과한 뒤에만 legacy route를 삭제한다. 이 순서는 #724에서
     실제로 위반됐다(F-17). 즉시 복구는 삭제 route/shim 부활이 아니라 PinVi caller 전환과
     BFF secret 공유가 아닌 명시적 service/operator principal 설치를 우선한다. 이미 최신 KTM이
     배포돼 운영 화면이 필요하면 코드 alias 추가 대신 검증된 pre-#724 image rollback을 임시
     운영 선택지로 둔다. public 계약도 새 응답을 소비하는 PinVi 배포를 먼저 준비한다.
  6. **write-fence cutover**: maintenance window에 쓰기를 멈추고(fence) 마지막 delta 반영 →
     KTM·PinVi를 순차 전환(원자 아님 — 5단계 절차) → **rollback window 동안 write-fence를
     유지하거나 forward journal replay를 준비**(F-12: 이것 없이는 rollback이 데이터를 유실한다).
     rollback 단위는 양 DB+manifest 전 이미지이며 RPO/RTO를 명시한다.
  7. **soak 후 제거**: reconciliation·운영 지표 통과 후 legacy schema/route를 삭제한다. 영구
     dual-serve를 만들지 않는다.
- **영향**: 이관 스크립트·검증 gate·runbook. PinVi와의 전환 조율(preflight에서 F-15 확정).

### D-12. DDL·성능 규율 — 변경 유형별 고정 절차

- **컨텍스트**: F-11(0051 additive, 0052 clean-cut, 0053·0057 lock-protected additive,
  0054~0056 소형 ops DDL 공존이 실증),
  F-8(성능 게이트 부재), F-10(metadata drift).
- **결정**:
  1. DDL 절차를 유형별로 고정한다:
     | 변경 유형 | 절차 |
     |---|---|
     | online/대형 CHECK·FK 추가 | `ADD CONSTRAINT … NOT VALID` → 배경 `VALIDATE` |
     | online/대형 UNIQUE·index | `CREATE (UNIQUE) INDEX CONCURRENTLY`(alembic autocommit_block) + writer conflict-target 코드와 동일 cutover |
     | 소형 ops 테이블 수술 | drain + `ACCESS EXCLUSIVE`(0052/0053 방식). 측정된 maintenance 안에서는 non-concurrent constraint/index 설치 허용 — **단, lock 획득 상한(≠중단 상한)과 실제 중단 시간을 production clone에서 실측한 수치를 PR에 첨부** |
     | 대형 테이블 type/PK 교체·STORED 추가 | shadow column/table + backfill(즉시 rewrite 금지 — F-7의 ~30M weather) |
     `ADD COLUMN` 같은 additive shape도 0053처럼 maintenance lock·trigger 교체를 동반할 수 있다.
     따라서 **additive 여부와 online 여부를 동일시하지 않고** lock mode·획득 상한·보유 시간을
     별도로 판정한다.
  2. Alembic 정합: 모든 애플리케이션 소유 테이블을 metadata에 매핑(또는 `include_object` 명시
     제외)하고, **빈 PostGIS DB → `upgrade head` → `alembic check` exit 0**을 CI 게이트로.
  3. 중복 GiST 제거: `spatial_index=False` + 공개 술어 partial만 유지(write 1.6× 실측 근거).
     시간상관 테이블은 기존 BRIN을 먼저 감사하고, 누락 hot path에만 **BRIN-on-time**을 보강한다.
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
| provider 정본 | `provider_datasets`(DB identity) → `source_entities` → `source_records`(immutable) + `source_entity_heads`; code projection은 capability `provider_catalog`와 executable `feature_operation_registry`로 역할 분리 | natural UNIQUE, 순환 FK 제거, denorm 열 제거(최종), `source_role` 단일 | D-5 |
| effective 값 | provider base + field-level `feature_overrides` → `effective_features` projection | override field-path UNIQUE, whole-row 동결 제거 | D-7 |
| 공개 정본 | `public_features` VIEW/projection (`published∧active∧valid`) | base table의 동일 술어 partial index, 전 공개 payload SQL이 VIEW만 사용 | D-3 |
| notice | `notice_states`: typed lineage + `valid_during tstzrange` + `is_current` | current partial UNIQUE, range GiST, hot path에서 JSON cast/anti-join 제거 | D-9-7 |
| weather/price | typed history(bitemporal) + `current_*_summary` | tuple UNIQUE(NULLS NOT DISTINCT, CONCURRENTLY), range·payload CHECK, source/kind FK, BRIN-on-time | D-8 |
| operation | `ops.import_jobs`가 provider load와 feature refresh lifecycle 정본(0050~0057) + typed/exact `sync_scope`·dispatch intent·active partial UNIQUE·append-only event history 구현, `feature_update_requests`는 입력·감사·generation companion | 기존 identity UNIQUE/트리거·registry·reconcile 유지, provider_datasets FK 후속 정렬 | D-5, D-10, ADR-064 계열 |
| curation | `curation_collections/items` **단일 write model** — legacy `curated_features`·단방향 trigger·legacy route는 제거, 후보는 `theme_feature_candidates` 분리 | archive 상태·`archived_at` 결합 CHECK | F-16 |
| idempotency | `feature_update_request_idempotency` + schedule command audit/active claim/resolution처럼 lifecycle별 append-only 저장소 | `(principal, operation, key)`·request hash·terminal replay/409. 같은 lifecycle이 검증될 때만 공용 저장소 | D-10 |
| POI target | canonical point 1개 + generated 파생, membership/provider-scope 분리. 현행 external-system identity·exact scope 검증 위에 `source_generation` 단조 적용을 보강 | external identity UNIQUE, generation 비교 적용 | D-10·§구판 P1-8 |

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
  POST /v1/features/batch                   # item-state: found|retired|suppressed|missing|unchanged (+revision)
  POST /v1/features/weather/batch           # set-based, target_at/known_at bitemporal
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

현재 `main`에서 `/v1/features/batch`를 PinVi가 실제 소비하고, canonical
`/v1/ops/datasets`·`/v1/ops/pipeline` backend와 두 admin UI, exact-scope 이력, ops-live ticket이
구현돼 있다. 위 표는 이 기반을 유지하면서 응답 state/revision과 service/operator 경계를
교체하는 **목표 계약**이다. 단, PinVi admin server는 삭제된 legacy ops 경로를 아직 호출하고
canonical operator principal도 없으므로 현재 두 저장소 최신 main 조합은 운영 계약이 아니다(F-17).
`features:batchGet` 같은 우월성 없는 경로 개명은 하지 않고 기존 resource path에서 응답 계약만
clean-cut한다. PinVi batch client는 service token 설정 시 이미 해당 header를 보내므로 production에서
이를 필수화하고 public-key/fail-open fallback을 제거하며 5-state envelope를 함께 소비하게 한다.
반면 `/v1/service/*`는 현재 admin-only cache target·update request를 외부 서비스가 안전하게
호출하기 위한 별도 인증 표면이므로 신규 자원으로 둔다.

오류·캐시 계약: RFC7807 유지, `Retry-After`는 409(advisory-lock 경합 — 기존 C3 계약 승계)·
429(rate quota)·503(upstream unavailable, stable code)에 명시, ETag/304(row_revision·catalog
revision), `CURSOR_QUERY_MISMATCH`, rate quota는 edge/app 중 정본 위치를 정하고
`429+Retry-After` contract test(§14 합의 — "app rate limiter 부재=DoS 확정"이 아니라 정본화가
완료 조건).

## 5. 목표 코드 구조

- **단일 FastAPI app 유지** + route policy matrix(D-1) + 그룹별 dependency + 공개 전용 read-only
  DB role. 물리 분리는 측정 후.
- canonical datasets/pipeline은 schema/service/query 분리, exact scope, operation registry,
  reconcile, append-only command audit까지 구현된 **유지 기준선**이다. C6b clean-cut은 끝났으므로
  legacy alias를 되살리지 않고, PinVi caller를 canonical 계약과 명시적 service/operator principal로
  전환한다. 이후 이 패턴을 나머지 표면에 적용한다.
- upsert 경로: whole-row 동결 CASE 제거(D-7)로 `_UPSERT_FEATURE_SQL` 대폭 단순화. bbox SQL:
  candidate 술어 단일화 + LATERAL→summary JOIN(D-8·D-9)으로 이중 SQL 복제 제거.
- 공개 판정·notice 판정·상태 전이는 각각 **한 곳**(view/typed table/상태 머신)으로 수렴 —
  endpoint별 재구현 금지.
- PinVi측: pinned OpenAPI에서 검증되는 typed DTO 경계(수기 transport client는 유지 가능하되
  무검증 dict mapper는 제거), transport/missing/state 분리, cluster 렌더, weather batch 소비,
  outbox relay. (PinVi repo 작업은 별도 계획으로 전개하되 계약은 본 문서가 정본.)

## 6. 실행 계획

### 6.1 T-ADM(ADR-064) 체인과의 관계

admin-ops 통합은 canonical operation·admin gate·schema/service 경계를 이미 구현한 **본 재설계의
유지 기준선**이다. 최신 상태와 남은 순서는 다음과 같다.

- **완료 기반**: C3e-B1/C/B2/B3/I1/I2(#709/#710/#713/#711/#714/#715), typed scope와 active
  operation 재사용(#701), datasets API/UI(#698), C5 pipeline(#691), C6a/b(#722/#724), C7A
  ops-live 인증(#725), 감사 후속과 C7B exact-scope API/UI(#723·#726~#729)가 병합됐다.
- **현재 잔여**: C6b의 소비자 선전환 누락을 `T-ADM-C6c`로 먼저 복구한다. PinVi admin caller와
  contract test를 canonical datasets/pipeline으로 옮기고 explicit service/operator principal을
  설치한 뒤, 그 두 저장소 commit 조합으로 인증·응답 smoke를 통과해야 한다. 그 전에는
  `T-ADM-C7` n150 배포·live E2E를 시작하지 않는다.
- **0053~0057 운영 gate**: repository head와 migration 검증은 완료됐지만 최신 migration의 n150
  적용 증거는 아직 없다. C7에서 production clone의 lock 획득·보유 시간, WAL, 전후 checksum을
  측정하고 maintenance 적용·external/exact scope live 증거를 남긴다. 30초는 lock **획득**
  상한이지 전체 중단 상한이 아니다.
- **겹침 조정**: T-VN-02는 #725의 WebSocket 인증을 재사용하고 route matrix/CI 분류만 소유한다.
  T-VN-03은 삭제된 legacy command가 아니라 현재 노출된 관측/log/consistency와 raw MOIS debug
  read를 방어한다. T-ADM-C6c가 cross-repo 복구의 단일 소유자다.

### 6.2 Wave 0 — 즉시 (P0, 테이블 변경 0 — 유일한 DDL은 T-VN-04의 CREATE VIEW, 전부 가역)

| ID | task | 내용 | 관련 |
|---|---|---|---|
| T-VN-00 | PinVi admin 계약 복구 | `T-ADM-C6c`와 동일 범위: 삭제된 ops caller 0건, canonical datasets/pipeline 전환, BFF secret 공유 없는 service/operator principal, 양 저장소 contract test 후 C7 허용 | D-1·D-11, F-17 |
| T-VN-01 | fail-closed 전환 | production profile secret 필수·기동 거부, local-dev fallback 격리 | D-1, F-3 |
| T-VN-02 | route policy matrix | 전 route/WS 분류 생성기 + 미분류 CI 실패 + `/metrics` 관리 경계. WS는 #725의 ticket 인증을 재사용 | D-1 |
| T-VN-03 | 잔여 운영 read 게이트 | 현재 노출되는 ops metrics/logs/consistency와 raw MOIS debug read를 operator/debug 경계로, 무키 legacy `/v1/curated-*` 공개 read는 public-keyed 정책으로 이동. 삭제된 command/live ETL은 부활 금지. 단 PinVi admin proxy가 `/v1/ops/{metrics,system-logs,api-call-logs,consistency/*}`를 라이브 소비 중이므로(PinVi `kor_travel_map_admin.py:350-565` 및 `admin_etl.py`/`integrity.py`/`debug_logs.py` caller), 경계 이동은 T-VN-00의 service/operator principal 설치·PinVi caller 전환과 같은 cutover로 조율한다(F-17 재발 방지) | D-1, T-VN-00 |
| T-VN-04 | 공개 predicate 통일(1차) | 기존 상태 위에 `public_features` view(CREATE VIEW만 — 전용 인덱스는 T-VN-34) + 전 공개 SQL 교체 — **양방향 오분류(F-1) 동시 해소** | D-3 |
| T-VN-05 | raw payload 경계 | 공개 DTO에서 raw 계열(`raw_data`·`raw_payload_hash`·`source_record_key`·**MOIS raw 부분집합의 `detail.payload` passthrough**(`providers/mois.py`의 `PlaceDetail.payload`)) 제거, observations를 operator 표면으로, batch `trip_card` 고정 | D-9 |
| T-VN-06 | notice 방어적 cast | 오염 row 1건의 공개 read 500 차단(완화 — 재설계는 W2) | D-9-7, F-9 |
| T-VN-07 | no-op 옵션 삭제 + actor principal(1차) | beach 옵션 제거; auth-event `body.actor` 우선 제거 등 최소 수정 | D-2, F-4 |
| T-VN-08 | PinVi false-broken 수정 | transport 실패↔missing 분리(stale 유지), `split("@")` 제거, status/state 소비 준비 | D-10, F-14 |

### 6.3 Wave 1 — 조기 (P1, additive, 구조 전환 비의존)

| ID | task | 내용 | 관련 |
|---|---|---|---|
| T-VN-11 | service batch item-state | 5-state envelope + revision (503≠missing) | D-3 |
| T-VN-12 | Idempotency-Key protocol 전개 | 0054의 도메인 ledger를 회귀 기준선으로 보존하고 남은 command에 key/body/result replay·409를 전개. lifecycle이 다른 저장소를 범용 table 하나로 합치지 않음 | D-10 |
| T-VN-13 | row_revision + If-Match | Feature용 revision 신설, correction PATCH/DELETE, 이후 ETag/304. #727 policy CAS는 resource-specific 선례로만 재사용 | D-10, D-9-8 |
| T-VN-14 | 지도 completeness | mode/truncated/coverage/cluster_key + include_geometry serialization화 + candidate 술어 단일화 + `ST_Intersects` | D-9 |
| T-VN-15 | search 계약 | include_total 실전달 + cursor fingerprint/version | D-9 |
| T-VN-16 | weather batch + 부모 404 | set-based batch, bitemporal 파라미터, PinVi N+1 제거 | D-8·D-9 |
| T-VN-17 | weather 무결성 가드 | tuple UNIQUE(CONCURRENTLY, writer 동시 cutover) + range/payload CHECK(NOT VALID→VALIDATE) + source FK | D-8, F-7 |
| T-VN-18 | 중복 GiST 제거 + BRIN 감사 | spatial_index=False, partial만 유지(전후 write 실측 첨부), 기존 weather/price BRIN 보존·누락 hot path만 보강 | D-12 |
| T-VN-19 | alembic 정합 CI | metadata 매핑/include_object + 빈 DB `upgrade→check` exit 0 게이트 | D-12, F-10 |
| T-VN-20 | actor principal 전면 + body 필드 제거 | D-2 완결(스키마에서 operator/actor 제거) | D-2 |
| T-VN-21 | 성능 게이트 계층화 | planner-default 스모크 확대, query-count 게이트, release 프로파일 정의 | D-12 |

### 6.4 Wave 2 — 구조 전환 (shadow + write-fence cutover, D-11 절차)

| ID | task | 내용 | 관련 |
|---|---|---|---|
| T-VN-31 | target freeze | §3~5를 ADR/OpenAPI/DDL 테스트로 고정 | D-11 |
| T-VN-32 | UUID identity | UUID 컬럼+backfill+alias 테이블, notice-lineage SQL 재작성, PinVi alias-map 이관 계획 | D-4 |
| T-VN-33 | provider_datasets 정본 | 테이블 신설(DB 소유)+9곳 FK화+denorm 제거(전환기 composite FK 경유) | D-5 |
| T-VN-34 | 직교 상태 모델 | 3축 컬럼+결합 CHECK, 4축 레거시 흡수, public_features VIEW 재정의 + base partial index | D-3 |
| T-VN-35 | typed subtype 분해 | kind별 geometry 테이블+제약, category FK | D-6 |
| T-VN-36 | override 단일화 | whole-row 동결 제거, field-level 일원화, upsert 단순화 | D-7 |
| T-VN-37 | notice_states | typed range 재설계, hot-path anti-join 제거 | D-9-7 |
| T-VN-38 | current summary | weather/price current 테이블 + bbox LATERAL 치환 | D-8 |
| T-VN-39 | cutover 실행 | 보존 분류→복구 검증→shadow 검증→write-fence 전환→soak→legacy 제거 (KTM·PinVi 조율, preflight로 F-15 확정) | D-11 |
| T-VN-40 | curation write model 단일화 | `curation_collections/items`만 정본으로: legacy `curated_features` write 경로·단방향 trigger·legacy route 제거, 후보는 `theme_feature_candidates` 분리 | F-16, §3 |
| T-VN-41 | cache-target 전파 완결 | 이미 구현된 external-system identity·exact scope·active target 검증은 유지. `source_generation`(+restore epoch)·outbox relay·backfill·reconciliation을 설치하고 critical path 밖에서 enable | D-10, §3 |

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

- PR 1개=task 1개, 코드 변경은 테스트 전 적대적 리뷰어 1명→CI green→merge. 문서 전용,
  rebase-only, 변수명·import 정렬 같은 기계적 변경은 추가 적대적 재리뷰를 생략한다. migration 포함 PR은
  단일 head·번호 경합 확인(현 head `0057_import_job_event_scope`; #729 기준).
- **T-VN task의 수용 기준 정본**: 각 task가 참조하는 D-결정 본문 + §8 검증 게이트다. task 표의
  "내용" 칸은 요약이며 계약을 재정의하지 않는다. 특히 T-VN-21은 §8.3 계층 3단 전부,
  T-VN-31은 §3~§5의 freeze 산출물(ADR·OpenAPI diff·DDL 테스트) 존재가 완료 조건.
- 각 wave 종료 시 §8 검증 게이트 통과를 확인하고 journal/resume 갱신.
- `T-ADM-C6c`/T-VN-00은 C7의 선행 gate이며 양 저장소의 caller path·principal·응답 계약을 함께
  고정한다. Wave 0·1의 다른 공개 API·PinVi 범위는 T-ADM과 병행할 수 있다. WS 인증은 #725,
  legacy clean-cut은 #724를 기준선으로 삼고 같은 동작을 중복 구현하거나 alias를 부활시키지 않는다.

## 7. 후속 반영 매핑표 — 이 문서 → 실제 문서 전개

| 본 문서 | 대상 파일 | 반영 방식 |
|---|---|---|
| §0 지도 원칙 | `AGENTS.md`/`CLAUDE.md` 참조 한 줄 + 신규 ADR 서문 | 인용(원문은 본 문서 유지) |
| D-1·D-2 | `docs/adr/066-route-policy-fail-closed.md` (1건) | 신규 ADR; ADR-005(ops 무인증) supersede·ADR-060 production 정책 개정 |
| D-3 | `docs/adr/067-orthogonal-publication-state.md` | 신규 ADR; ADR-017의 place 유지 규정은 **이관 문서(data-model 계열 architecture 문서)** 갱신으로 반영(ADR 원문은 포인터만) |
| D-4 | `docs/adr/068-feature-uuid-identity.md` | 신규 ADR; ADR-009 supersede·ADR-057(concierge stable id)와 관계 명시, `docs/etl/feature-id-determinism.md`는 **개정**(UUID 정본·기존 ID는 alias로 강등) |
| D-5 | `docs/adr/069-provider-datasets-canonical.md` | 신규 ADR; ADR-063 확장 |
| D-6·D-7 | `docs/adr/070-feature-subtype-decomposition.md`, `071-field-level-override.md` | 신규 ADR **2건 확정**(D-6/D-7 각 1건 — 독립 채택·독립 rollback 가능해야 함) |
| D-8 | `docs/adr/072-weather-bitemporal.md` | 신규 ADR; ADR-062(3년 보존)와 정합 명시 |
| D-9·D-10 | `docs/adr/073-public-rest-contract.md`, `074-write-safety.md` | 신규 ADR; `docs/architecture/rest-api.md` 목표 표면 개정 |
| D-11·D-12 | `docs/adr/075-cutover-and-ddl-discipline.md` | 신규 ADR; `docs/deploy.md`·runbook에 write-fence/rollback 조건 추가 |
| §3 | `docs/architecture/postgres-schema.md` | "목표(vNext)" 섹션 신설(현행 서술과 구분) |
| §4 | `docs/architecture/rest-api.md` + `docs/integration-map.md` | 목표 표면 섹션 신설; PinVi 계약 변경분은 integration-map에 cutover 조건부로 |
| §6 | `docs/tasks.md` + PinVi cross-repo consumer task | `T-VN-*` 블록 신설, `T-ADM-C6c` PinVi admin HTTP caller/auth contract 복구를 양 저장소에 mirror, tasks-rule 준수 |
| §8 | `docs/architecture/performance.md` + CI workflow | 게이트 정의 이관 |
| 전체 | `docs/journal.md`·`docs/resume.md` | 반영 작업 자체의 엔트리 |

반영 시 주의: (1) ADR 번호는 반영 시점 README의 다음 후보 사용. (2) 기존 ADR을 supersede할 때
원문을 삭제하지 말고 상태·후속 포인터만 갱신. (3) T-VN은 별도 블록으로 전개하되 이미 발생한
cross-repo 차단은 `T-ADM-C6c`와 양 저장소 task에 함께 mirror. (4) 본 문서는 반영 완료 후에도
"재설계 정본"으로 유지하며, 반영 PR들이 본 문서의 해당 섹션에 반영 PR 번호를 역기입한다.

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
- active scope 동시 생성은 operation 1개로 수렴하고 같은 계획만 재사용하며 다른 계획은 409.
- terminal 뒤에도 같은 Idempotency-Key·같은 body는 각 도메인 ledger에서 저장된 동일 결과를
  replay한다. 같은 key·다른 body는 409, stale If-Match는 412, 조건부 GET은 304다.
- route policy matrix에 미분류 route 0건, production 기동이 secret 없이는 실패.
- PinVi production caller에 삭제된 ops path 0건. canonical datasets/pipeline 호출은 명시적
  service/operator principal로 성공하고, principal 없음·잘못된 scope는 typed 401/403/422로 닫힌다.

### 8.3 성능 (계층)

- 매 PR: planner-default EXPLAIN 스모크(hot query), "query 수 ≠ batch item 수 비례" 검사,
  response-shape 회귀.
- release/cutover: 100만+ 실분포 fixture, `EXPLAIN (ANALYZE, BUFFERS)`, 서울 밀집 viewport·전국
  low-zoom·100km nearby·상용 검색어·200건 batch, N150 기준 p95·shared read·byte budget.
- 인덱스 변경 PR은 before/after write 비용 실측 첨부(GiST 6→partial 정리에서 ~1.6× 개선 실측
  선례).

## 9. 부록 — 판정 이력 포인터

본 문서의 결정 근거가 된 왕복 리뷰 원문은 PR #702(§1~10 원 리뷰), #703(§11 5관점 검증 —
scratch EXPLAIN·write 실측 포함), #704(§13 대질 — retired/missing·멱등성·UNIQUE NOT VALID 판정),
#705·#706(0052 clean-cut·C3e 재분할), #707(§14 — 양방향 오분류·write-fence·DDL 유형표)에
보존돼 있고 #708이 이를 현재 구조로 전면 재작성했다. #717은 #698/#701과
#709/#710/#711/#713/#714/#715를 1차 재대조했다. 이번 2차 재검증은 #691(C5),
#721~#729(C6a/b·C7A·감사 후속·C7B)와 PinVi `origin/main@48085afb`의 실제 caller/test를 함께
대조했고, 그 결과는 PR #730으로 병합했다. 3차 재검증은 같은 기준선에서 6관점 병렬
검증(인증/라우트·쓰기 안전성·스키마/마이그레이션·공개 읽기·PinVi cross-repo·문서 정합) +
발견 건별 독립 적대 검증으로 진행해 PR #732로 병합했다. 무키 legacy curated 공개 read(F-3), 잔여 body-actor
4개 route군(F-4·D-2), 존치 ops 관측 route의 PinVi 라이브 소비와 T-VN-03 cutover 조율
(F-17 연계), C3e B2/B3↔PR 대응 정정을 반영했다. 세부 논증은 해당 PR diff와
`docs/tasks-done.md`의 완료 증거를 함께 참조한다.

### 정본 전개 상태 (2026-07-18)

PR #736(`docs/vnext-review-propagation`)에서 §7 매핑을 ADR-066~075, architecture, integration,
deploy/runbook, tasks, entry/status 문서에 전개했다. merge 뒤에도 본 보고서를 설계 근거 정본으로
유지하고 구현 완료 증거는 각 T-VN task와 PR에 기록한다.
