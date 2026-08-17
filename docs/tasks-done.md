# tasks-done.md — 완료/아카이브 task 이력

> 완료(`[x]`)·폐기·머지 history 아카이브. **진행 중/예정 task는 [`docs/tasks.md`](tasks.md)**.
> (2026-06-09 분리 — tasks.md 길이 축소. 분리 기준: 열린 `[ ]` 항목이 없는 섹션·Phase는 여기로.)

## 2026-08-16 — T-VN-H46A alembic squash 병합

- [x] T-VN-H46A — **alembic squash: 체인 109개 → `0200_schema_baseline`**

  PR [#978](https://github.com/digitie/kor-travel-map/pull/978)이 `main`에 병합됐다. 정본은
  `alembic/versions/0200_schema_baseline.py` docstring과
  `alembic/legacy_versions/README.md`이며, 빈 PostGIS DB catalog 동등성·ACL digest·legacy
  execution/build artifact 차단을 CI로 고정한다. 남은 VWorld fallback과 daemon drift는 열린
  `T-VN-H46C`·`T-VN-H46D`가 각각 소유한다.

## 2026-08-13 — T-VN-34/35/36 Wave 2 최종 배포·인수 완료

> 2026-08-13 n150 prod에서 `0087_route_area_subtypes` →
> `0104_tvn36_final_fence` forward migration과 runtime 배포를 완료했다. 이력·정확한
> 측정값은 [`resume.md`](resume.md)의 같은 날짜 기록과
> [`journal.md`](journal.md)의 배포 기록이 정본이다. squash 후 실행 정본은
> `0200_schema_baseline`과 bridge다.

- [x] T-VN-34A/B/C — **직교 상태 schema·public projection·writer/API/UI cutover**

  final stacked cutover와 fresh clone live 인수를 마쳤다. 3축 상태 계약, public
  projection, runtime principal 분리는 이후 legacy write-fence까지 유지한다.

- [x] T-VN-36A/B/C/D·live — **field override 단일화·destructive fence·격리 clone 인수**

  effective projection 단일화와 기존 field-level freeze 경로 제거를 완료했고,
  candidate-head clone live 인수도 통과했다.

- [x] T-VN-35/34/36-deploy — **`0104` prod cutover**

  1,008,852 feature를 보존한 in-place migration(1시간 32분 39초) 뒤 api/ui/dagster/daemon
  4개 런타임이 healthy 상태로 전환됐다. post-deploy baseline dump와 manifest를 남겼다.
  여기서 남겨뒀던 "공유 PostgreSQL에서 전용 인스턴스로의 이전"은 **2026-08-17에
  완료**됐다 — prod PostgreSQL을 프로젝트별 전용 instance 4개로 나눴고(geo `12500` ·
  concierge `12600` · **map `12700`** · pinvi `12800`, 전부 loopback) `5432`를 듣는 것은
  이제 없다. 근거는 docker-manager **ADR-37**, 경과는 `docs/resume.md` 2026-08-17 항목.

## 2026-08-12 — T-VN-38 weather·price current summary 병합

> PR [#971](https://github.com/digitie/kor-travel-map/pull/971), merge
> `8dc2b24a`. 최종 source `bef509d` 기준 CI 8개와 n150 전용 clone live를 다시
> 통과한 뒤 머지했다. 남은 held-component 제거는 `T-VN-39`가 소유한다.

- [x] T-VN-38A — **weather current summary**

  bitemporal 원본 이력을 유지하면서 canonical dataset/source revision 기준의 current
  weather summary와 reconciliation을 도입했다.

- [x] T-VN-38B — **price current summary**

  `provider + price_domain + product_key` identity의 current price summary와
  restore/backfill generation 구분을 도입했다. weather와 같은 transaction advisory lock으로
  전역 projection의 오래된 winner 역전을 막았다.

- [x] T-VN-38C — **bbox/detail set-based cutover**

  weather/price read를 summary set join으로 전환하고, freshness·cardinality·EXPLAIN 및
  9개 frozen artifact의 CRLF byte guard를 고정했다. Dagster raw provider response는
  `date`·`time`·`Decimal`과 immutable mapping을 JSON 보존 가능 형태로 정규화한다.

  검증: GitHub CI 8/8 green(3 Python unit matrix, PostGIS integration, fixture replay,
  lint, OpenAPI, frontend), 적대 리뷰 2인 P0/P1=0. n150 전용
  `ktm-tvn38-db:18732` clone에서 main/recovery Live UI E2E 각각 2/2, `phase=passed`,
  BLOCKED 없음, startup migration 불변과 production compose 제외를 실증했다.

## 2026-08-12 — T-VN-33 provider dataset 삼중 identity 정본 전환 병합

> PR [#966](https://github.com/digitie/kor-travel-map/pull/966), merge
> `9bbb74d`. 상세 설계·결함 회고는
> [`reports/t-vn-33-provider-datasets-single-pr-plan-2026-08-06.md`](reports/t-vn-33-provider-datasets-single-pr-plan-2026-08-06.md)와
> `journal.md` 2026-08-11 기록이 정본이다.

- [x] T-VN-33 — **provider dataset·operation 정본과 immutable observation/head 전환**

  `33-A`~`33-E`를 하나의 forward-only PR로 완료했다. versioned dataset/operation seed,
  canonical `(provider_dataset_id, sync_scope, operation_key)` membership, immutable source
  entity/record/head, writer·reader·admin projection cutover 및 legacy physical fence를
  `0089`~`0092`로 일괄 적용했다.

  검증: 로컬 CI mirror 25/25와 GitHub CI 8/8 green, 적대 리뷰 3렌즈 P0/P1=0. n150
  격리 DB에서 fresh migration·API live 12/12·admin UI live 10/10을 확인했다.

## 2026-08-12 — T-VN-37 notice 계보 key 물화 병합

> PR [#968](https://github.com/digitie/kor-travel-map/pull/968), merge `490a2482`.
> empty range 표현은 별도 보류 task `T-VN-37D`로 남긴다.

- [x] T-VN-37 — **계보 key 물화 + 인덱스 probe**

  notice scope의 `source_records.lineage_key`를 DB 트리거로 파생하고 표현식 인덱스와
  materialized reconcile CTE로 JSON 재계산 병목을 제거했다. 결과 집합과 reconcile 종료
  상태를 유지하면서 대규모 목록과 reconcile 시간을 각각 20.4초→0.19초,
  118.4초→0.36초로 줄였다.

## 2026-08-12 — T-VN-H45 KMA/airkorea 호출 강건화 완료 이관

- [x] T-VN-H45 — **KMA/airkorea 대량 순차 upstream 호출 강건화**

  간헐 오류율과 N격자 all-or-nothing 재시도로 생기던 생존확률 붕괴를 단건 호출 경계의
  유한 재시도로 고쳤다. 평문 HTTP 종료는 upstream 정본 HTTPS 전환과 pin 갱신으로
  해결했고 KMA 4종 SUCCESS·55,755 값 유입을 실증했다. airkorea 504는 upstream
  `SERVICETIMEOUT_ERROR`로 분류해 관찰만 한다. 다건 fetcher와 quota telemetry 확장은
  열린 `T-VN-H45-후속`으로 분리했다.

## 2026-08-06 — T-VN-41F1D-C3 Manager dynamic fixture n150 결선

- [x] **T-VN-41F1D-C3 — Map fixture lifecycle의 v5 durable transaction 결선**

  Manager PR #167의 최신 Map typed-subtype pin으로 n150 파기형 `rebuild-pinned` generation을
  committed했다. Map application `0087_route_area_subtypes`, Map Dagster `29b539ebc72a`, PinVi
  `20260804_0049` schema head 및 일곱 runtime container health를 확인했다. Manager v7 journal은
  Map fixture `armed → consumed → finalized`와 PinVi canonical cancel의 정확한
  `409 PIPELINE_CANCELLATION_UNSAFE` outcome을 기록했다.

  Map UI 로그인 POST는 `200`과 session cookie를 반환했고, n150 data-independent live UI E2E는 운영 홈·
  파이프라인 catalog 6건, Feature 목록·지도 초기 surface 10건을 통과했다. 새 DB에 source/ETL data를
  의도적으로 적재하지 않았으므로 고정 curated/feature ID를 요구한 suite 실패는 C3 runtime failure와
  분리해 F1D-D에서 final-schema ETL 재적재 뒤 재실행한다.

## 2026-08-06 — T-VN-35 A-D kind별 typed subtype 분해 병합

> 2026-08-06 A-D 단일 PR로 종결(ADR-086). 원안 대비 **재해석 2건**이 있고, 근거는
> 실측이다 — 아래 각 항에 적었다. 정본 설계는 `docs/adr/086-typed-feature-subtypes.md`.

- [x] T-VN-35A — **feature core·point subtype** → *배타 arc + place subtype*

  `UNIQUE(feature_id, kind)` + subtype의 `kind` 상수 CHECK + `(feature_id, kind)` 복합 FK로
  배타 arc를 만들고 `feature_places`를 분리했다(alembic 0085). shadow 병행은 하지 않는다 —
  subtype이 단일 정본이다.

  **재해석**: point subtype은 만들지 않고 `coord` 3컬럼을 core에 남겼다. coord는 4개 kind가
  공유해 kind 상수 CHECK를 걸 수 없어 배타 arc가 깨지고, place 96.6%·event 82%가 non-null이라
  거의 모든 read가 조인을 강제당하며, bbox/nearby 술어가 `idx_features_coord_gist` 너머로
  밀린다. 대신 geometry 계약 강화(35C)로 목적을 달성했다.

- [x] T-VN-35B — **event·notice subtype**

  `feature_events`/`feature_notices`(alembic 0086). notice 유효기간이 typed `timestamptz`가
  되어 read 필터의 문자열 파싱 + `pg_input_is_valid` 방어 cast가 사라졌다. "혼합 kind row
  거부"는 배타 arc가 선언적으로 구현한다 — subtype 행이 있는 동안 core `kind` 변경이 FK
  위반으로 막힌다.

  **주의**: DB CHECK로 `valid_end_time >= valid_start_time`을 걸지 않았다. provider가 미래
  시행 공지를 철회하면 end < start인 **실재 상태**가 나오고(실측: start 2026-07-13 /
  end 2026-06-02), CHECK를 걸면 KREX notice ETL asset이 죽는다. 불변식은 DTO가 선언값에
  대해 유지하고, DB 표현은 T-VN-37A의 `tstzrange`(empty range 허용)가 맡는다.

- [x] T-VN-35C — **route·area subtype**

  `feature_routes`(MULTILINESTRING NOT NULL)/`feature_areas`(MULTIPOLYGON NOT NULL),
  core `geom` 제거(alembic 0087). "geometry가 필수인 kind"와 "없어야 하는 kind"가 술어가
  아니라 테이블 구조로 갈린다. prod route/area 0행이라 이관 비용·회귀 위험 모두 0.

  **재해석**: `parent_feature_id`·`sibling_group_id`는 core에 남겼다 — prod 사용 0행이고
  place도 장래 부모를 가질 수 있어 route/area 전용으로 내릴 근거가 없다.

- [x] T-VN-35D — **repository/API projection cutover**

  core `detail` JSONB 제거 + `feature.features_detailed` 조립 뷰 신설. writer는 subtype에만
  쓰고 reader는 뷰를 읽는다 — 값이 두 곳에 있지 않으므로 drift라는 개념이 사라진다.
  merge 경로에 cross-kind 거부를 신설했다(종전 부재).

  검증: 조립 detail이 원본과 place·event·price·weather **731,620행 md5 바이트 동일**(notice도 `valid_start_time` 145/145 동일)(이 대조가
  `jsonb_strip_nulls` null 소실과 `EventDetail.sigungu_code` 누락 2건을 잡았다).
  플랜은 술어가 subtype GiST를 타도록 hot path만 UNION ALL로 직접 참조한다(뷰 컬럼을
  술어에 쓰면 Hash Left Join 2단 퇴화 — admin bbox 4158ms → 411ms 실측).

## 2026-08-06 — T-VN-41F1J-A Map-owned cancel-probe fixture 병합

- [x] **T-VN-41F1J-A — Map fixture schema·service API·격리**

  PR #960에서 `ops.c6c_cancel_probe_fixtures`와 fixture 전용 repository/service API를 병합했다.
  Map은 transaction ID마다 running/no-Dagster-run import job을 멱등 생성하고, 일반 PinVi 취소가
  만든 canonical cancellation 뒤 consume/finalize를 원자적으로 기록한다. `armed → consumed →
  finalized` receipt는 exact unsafe outcome을 포함하며, fixture kind는 worker·stale recovery·일반
  ops projection과 직접 event 삽입에서 격리된다. `ops:fixture` capability는 Map API와 Docker
  Manager에만 결박한다. 새 v5 Manager transaction에서 이 lifecycle을 실제 실행한 F1D-C3의 n150
  receipt는 상단 완료 이력에 기록한다.

## 2026-08-06 — T-VN-41F1D-C0a 후보 Map application schema head artifact 병합

- [x] **T-VN-41F1D-C0a — 설치 package 기반 정적 application head 계약**

  PR #963에서 후보 API image의 `ktm-application-schema head`가 installed package의 immutable graph
  artifact만 읽어 단일 Alembic head를 JSON으로 attest하게 했다. cwd/source mount/Alembic 실행/DB/application
  import는 경계 밖이며, AST generator equality·cycle·side-effect·ambiguous head 회귀를 고정했다.
  Docker Manager는 이 application head를 Dagster storage/PinVi head와 함께 reset 전에 attest한다.

## 2026-08-06 — T-VN-41F1D-C0 후보 Dagster storage migration artifact 완료

- [x] **T-VN-41F1D-C0 — 후보 Dagster storage migration artifact**

  `ktm-dagster-storage head`가 후보 이미지에 실제 설치된 Dagster package의 storage
  graph 단일 head를 JSON으로 attest하고, `migrate`가 동일 image의
  `DAGSTER_HOME`/`dagster.yaml`/metadata DSN으로 `dagster instance migrate`를 실행한
  뒤 `public.alembic_version`의 정확히 한 `version_num`을 strict 대조한다. Map
  application Alembic·source SHA·lock pin은 어느 경로에서도 storage head가 아니다.
  Compose one-shot 성공을 webserver/daemon의 선행 조건으로 연결했고, 외부 DB·infra·host
  overlay도 같은 순서를 유지한다. 실제 후보 image의 빈 격리 PostgreSQL 검증에서 head,
  migration 결과, `public.alembic_version`이 모두 `29b539ebc72a`로 일치했다. Docker
  Manager F1D-C2는 이 image command만 호출해 candidate를 attest·migrate한다.

## 2026-08-05 — T-VN-H42 provider 재적재 완주·수렴 검증 (41C 선행 조건 충족)

> 2026-08-07 `tasks.md`↔실상태 재대조에서 이관. 판정 자체는 2026-08-05
> (journal 2026-08-05 (5) — 최종 수치 고정) 완료됐고 열린 하위 항목이 남아 있지 않다.
> 함께 신설됐던 H43/H44는 열린 잔여가 있어 `tasks.md`에 남는다.

- [x] T-VN-H42 — **provider 재적재 완주·수렴 검증 (+ H35 prod live 검증 잔여)**
      — **2026-08-05 판정 완료** (journal (5) — 최종 수치 고정·41C 선행 조건 충족)

  **41C prod consumer enable의 선행 조건**. 완료 실측(2026-08-05): MOIS 702,955
  3중 일치(source=links=features)·opinet 934(용인·수원 bbox — 전국 bbox quota 소진
  재발 금지 준수)·unlinked 0건·공개 API/admin/quarantine live smoke green·소실됐던
  공개 API key 재발급. KMA 4종+airkorea 만성 실패는 구조 결함으로 **H45 분리**.

  - [x] 잔여 provider 로드 — MOIS bulk(dedup 룰 검증 후)·opinet bbox 완주.
    KMA/airkorea 축은 H45 판정으로 연동, khoa 등 잔여 transport 실패군은 스케줄
    수렴 감시 지속.
  - [x] CSV 재import(authoritative replace) — 486행 재통과, 미해석 290→270
    (구성: H31 구조 확정 103 + visitkorea/khoa 스케줄 수렴 대기 — 상시 운영).
  - [x] 공개 표면 **최종 수치 고정**(2026-08-05 00:30Z): features 731,724 =
    public = aliases · weather_values 56,310 · curation 4,910/링크 4,640.

## 2026-08-05 — 재생성 수렴·Wave 2 UUID 착지 일괄 아카이브 (배포 c0afaa4e)

> prod 재생성 수렴(H42)·`0082` 배포 완료 시점의 일괄 정리. H30/H32/H22/T-VN-31 절 전체와
> H25A/H34R/H40/H35/H31/32A/32B 상세를 이관했다(각 항목의 완료 근거·수치는 본문 보존).
> H35는 2026-08-04 재정의판(폐기·재생성 대체)으로 종결 — 아래 본문 중 cutover 설계는 이력이다.

### T-VN-H30 — 주소 검증 관측 durable화·회복 실적재 검증 (H28 후속, 부분완료)

- [x] T-VN-H30A — 검증 finding을 `ops.data_integrity_violations`에 durable 기록 (#888, dedupe 부분 유니크 인덱스 0067 — **prod 미적용, H35 참조**) → [`tasks-done.md`](tasks-done.md)

- [x] T-VN-H30B — **회복을 격리 snapshot의 실제 적재·인증 API로 재검증** *(2026-08-04 재정의·완료)*

  ## 완료 기록 (2026-08-04, 재정의판 전 acceptance 충족)

  - **snapshot**: `n150:~/backups/krtour_map_0078_20260804T023104Z.dump` 6.9M,
    sha256 `b5ab83dd…f18ffe`, 2026-08-04T02:31:05Z, head `0078_cache_target_gc_observe`,
    features 7,056 · curation_items 4,910 · source_records 7,097. dev box scratch에 복원
    (pg_restore 오류 0줄, superuser 확장 4종 사전 생성).
  - **artifact**: concierge `/api/v1/features/changes` 전량 8 page / 1,481 rows / 3.37MB,
    cursor chain 검증(내장 has_more/next_cursor 룰) 통과, JSONL sha256 기록. 이후 replay는
    이 파일만 입력(**live concierge 무접촉**).
  - **회복 실증**: scratch에서 concierge scope 1,481건을 `status='inactive'`로 결손 주입
    (active 7,056→5,575) → `build_asset_context` resource override로
    `run_feature_place_kor_travel_concierge_youtube` 직접 호출(network-free replay,
    `strict_address='drop'`, geo reverse만 결선) → **active 1,481 완전 복원, id 집합
    교집합 1,481 / 신규 0 / 미복구 0**. **2회차 replay 변화 0(멱등)**.
  - **finding**: run3 sync 수치 `observed=105 unique=105 upserted=105 unrecorded=0`.
    violation 분포(scratch 전체): reverse_geocode_failed 272(unlinked) /
    reverse_geocode_unavailable 105(linked) / provider_address_region_disagreement 52(linked) /
    admin_code_stale_{sido 51·emd 7·sigungu 2}(전부 linked) — **dual grade 축 실작동 증거**.
    linked = feature_id non-null로 실측.
  - **인증 실호출**: scratch 실 API 서버(local-dev)에서
    `GET /v1/admin/issues?status=open&issue_type=admin_code_stale_sido` — FK target
    (`f_5183032036_p_…` 등) 정상 해석, `last_seen_at` 반환 정합.
  - 정직 각주: replay 세션 중 geo 호출 105건이 간헐 unavailable로 기록됨(1,376건 성공) —
    그 세션의 finding은 unavailable 계열로 관측됐고 stale 계열 `last_seen`은 snapshot
    시대 값이 최신. 판정 왜곡 없음(회복 실증은 feature 축, finding 축은 분포·수치 기록).
  - 하네스: 전용 replay CLI가 저장소에 없어 조사 후 신규 조립
    (`test_concierge_assets.py`의 `build_asset_context` 패턴 + 순수 변환 모듈). 스크립트는
    dev box `~/h30b/`(h30b_replay.py·h30b_final.py)와 세션 scratchpad에 보존.

  ### (이하 재정의 원문)

  ## 재정의 (2026-08-04, 사용자 결정 "b")

  종전 acceptance는 **H35가 서명한 post-migration bundle** 복원을 전제했는데, 그 전제가
  두 겹으로 소멸했다 — H35 재정의로 서명 bundle이 존재하지 않게 됐고, 검증 대상이던
  7/30 격리 snapshot(`0063` 시대)의 데이터 시대가 폐기·재생성으로 끝났다. 회복 실증의
  목적(#673의 남은 절반 — 데이터 유실 후 finding 파이프라인이 실제로 복원되는가)은
  재생성과 무관하게 유효하므로 **현 재생성 prod(`0078`) 기준으로 재정의**한다.

  재검증 acceptance (재정의판):
  - **재생성 prod에서 새 격리 snapshot을 뜬다** — writer-quiesced 필요 없음(스케줄 사이
    창이면 충분), dump identity(sha256)·시각·migration head(`0078_cache_target_gc_observe`)
    를 기록한다. 폐기 전 아카이브(`krtour_map_0072_*.dump`)는 **이 task의 대상이 아니다**
    (구 시대 데이터 — H22C 픽스처 용도로만).
  - 격리 scratch DB에 복원 후(신규 DB는 superuser 확장 4종 사전 생성 — H35 실행 기록
    참조) 같은 scope의 `feature.features` 적재 직전/직후 수와 복구된 feature id 집합을
    기록한다.
  - 같은 run의 finding `observed/unique/upserted`, linked/unlinked 수를 함께 기록한다.
  - 인증된 `GET /v1/admin/issues?issue_type=…` 실호출(격리 스택의 실 API 서버)로 최신
    `last_seen_at`·최신 FK target을 확인한다.
  - concierge `changes` export는 **재생성 시대의 실 export artifact**를 쓴다 —
    SHA-256·page/cursor chain·행 수 검증 후 live credential/network 없이 resource
    override로 ordered item을 재생한다. artifact 외 입력 금지, prod 무변경 원칙 유지.
  - Dagster DB pair 복원·서명 identity 검사 항목은 **삭제** — 서명 주체(H35 helper)가
    사문화됐고, run 이력 DB는 회복 실증의 대상이 아니다.

- [x] T-VN-H30C — **타 provider `AdminEvidence` 무장** (2026-08-03 완료)

  MOIS만 무장했으나 **탐지 증가는 0건**이다. MOIS는 payload에 `legal_dong_code`가 있으면
  역지오코딩을 아예 호출하지 않으므로 `obs_code`와 `claim_code`가 **상호배타**이고
  `grade == "dual"`이 구조적으로 불가능하다 — staleness 축이 영원히 발화하지 않는다.
  `unarmed`→`claim_only` 재라벨 이상의 값이 없다.

  > **정정** — 직전 판에 "나머지 provider는 payload 법정동코드가 없어 무장 대상이 아니다"라고
  > 적었으나 **거짓**이다. 적대 리뷰가 반증했다:
  > `providers/krforest.py:182` `ForestSpatialItem.region_code`(원천
  > `python-krforest-api` `_REGION_CODE_KEYS`에 `법정동코드`/`EMD_CD` 포함, 역지오코딩도 함),
  > `python-visitkorea-api` `models.py:90` `l_dong_regn_cd`/`l_dong_signgu_cd`.
  > 두 provider가 실제로 `dual`을 낼 수 있는 후보다.

  재작업 시: krforest·visitkorea를 조사해 무장하고, MOIS는 reverse를 강제하지 않는 한
  staleness 대조가 불가능함을 설계 문서(`docs/architecture/address-geocoding.md`,
  `dto/admin_evidence.py`)에 고정한다. provider 고유 코드(VisitKorea `areaCode` 등)는 넣지 않는다.

  ## 결과 (2026-08-03)

  **krforest arboretums만 무장했다. visitkorea는 무장하지 않는 것이 옳다는 판정이다.**

  판정 기준을 "payload에 행정코드가 있는가"에서 **"obs·claim 두 축이 동시에 성립하는가"**로
  바꿨다. `admin_code_stale_*`는 `grade == "dual"`일 때만 발화하므로 그것이 실질 기준이다.

  | provider | dual | 근거 |
  | --- | --- | --- |
  | krforest arboretums | **가능** | `_resolve_address`의 reverse 조건에 payload 코드가 없다 |
  | krforest recreation_forests | 불가 | payload에 행정코드 필드 자체가 없음(제공기관코드뿐) |
  | visitkorea | 불가 | reverse 미호출 + `FeatureBundle` 미생성(enrichment-only) — 실을 자리가 없다 |
  | MOIS | 구조적 불가 | `legal_dong_code`가 있으면 reverse를 건너뛰어 obs/claim 상호배타 |

  **선행 게이트를 prod에서 실측했다** — arboretum 205건 **전량**이 `region_code`를 갖고
  전부 8자리 숫자(`emd`)다. 조사가 우려한 세 리스크(전량 null / 자릿수 혼재 /
  `"4173025000.0"` 형태 오염)가 모두 해소됐다.

  구현:
  - `_resolve_address`가 `(address, reverse_geo, reverse_attempted)`를 반환하도록 바꿨다.
    obs 축은 **좌표 reverse 결과만**이어야 한다 — `address`는 `address_resolver`(주소
    문자열 정지오코딩)로도 채워져 그대로 쓰면 claim_text와 출처가 같아진다(`mois.py` 선례).
  - `_claim_from_region_code`가 숫자·지원 길이(10/8/5/2)만 통과시킨다. 원천이 길이·숫자
    검증을 전혀 하지 않으므로 거르지 않으면 DTO validator의 ValueError로 **asset 전체가
    죽는다**.
  - 휴양림 경로는 `admin_evidence=None` 유지.

  회귀 8종을 추가하고 변이로 falsifiability를 확인했다(무장 제거 시 관련 테스트가 죽는다):
  dual+staleness 발화 / 코드 일치 시 미발화 / 길이 디스패치 4종 / 미지원 형태 12종 무예외
  거부 / obs 오염 금지 / 휴양림 claim 부재 / **무장 부수효과 중립성**(MOIS 무장이
  `reverse_geocode_not_attempted`를 새로 터뜨린 전례가 있어 고정).

  문서 정정도 함께 했다 — `address-geocoding.md` §8 표의 "MOIS reverse **필수**"는 코드와
  정면 모순이라 조건부로 고치고, §8.1에 provider별 무장 조건표를 신설했다. §7.1의
  `providers/visitkorea.py :: festival_to_bundles` 예시는 **실재하지 않는 함수**라
  개념 예시임을 명시했다(그대로 두면 "visitkorea에 이미 bundle 경로가 있다"는 오인이 재발).

### T-VN-H32 — 주소 검증 finding 자동 close (H30A 후속)

H30A가 durable ledger를 붙였으나 **자동 close는 일부러 넣지 않았다**. 1차 설계의 sweep
("이번 run이 보고하지 않는 finding을 닫는다")을 적대 리뷰가 실측으로 기각했다.

- `_load()`는 provider에 따라 **배치마다** 호출된다(MOIS는 1000건 단위 ~977회). 배치 단위
  sweep은 "이 배치에 없는 것"을 닫아, 한 run이 자기 finding 대부분을 스스로 resolved 처리한다.
- sweep이 행을 부분 unique index 밖으로 밀어내 다음 run이 **새 행**을 만든다 — 막으려던
  단조 증가를 재생산한다(3개 논리 finding → 2 run 후 6행, 실측).
- `bundles=[]`인 `_load()`는 OpiNet 일일 스킵·MOIS 무레코드 fallback의 **제어 흐름
  sentinel**이라, 빈 finding 집합이 큐 전체를 닫는다.

- [x] T-VN-H32 — **run marker 기반 close** (2026-07-31, #912로 superseded)

  **marker는 시각이 아니라 `run_id`다.** 처음엔 `last_seen_at < run_started_at`으로 짰는데
  `dagster/definitions.py:99`에서 `fetched_at` resource가 **`None`**이라 `_fetched_at()`이
  **호출할 때마다 새 `now()`**를 반환한다. run-end hook에서 그 값을 marker로 쓰면 이번 run의
  upsert보다 나중 시각이 되어 **자기 finding을 스스로 닫는다** — 기각된 실패모드를 시각 축으로
  재현하는 것이다. `run_id`는 그 시계 함정이 없다.

  upsert가 `payload.observed_run_id`를 찍고, close는
  `COALESCE(payload->>'observed_run_id','') <> :run_id`인 것만 닫는다.
  **빈 `run_id`는 술어가 모든 행에 참이 되므로 `ValueError`로 fail-closed**한다.

  호출 지점은 `assets.py`의 `_record_feature_sync_success` — **8개 asset 공통, 배치 루프 밖,
  run당 1회**이고 MOIS처럼 배치를 도는 asset도 `result is not None`(실제로 배치를 처리함)일
  때만 닿는다. `bundles=[]` sentinel 경로(OpiNet 일일 스킵·MOIS 무레코드 fallback)는 이 hook을
  거치지 않으므로 빈 관측 집합이 큐를 닫는 일이 없다. close 실패는 적재를 되돌리지 않는다 —
  관측 위생이지 적재 계약이 아니다.

  술어별 방어: `status='open'`(**`acknowledged` 불가침**) / `provider`·`dataset_key`(provider 경계)
  / `dedupe_key LIKE 'av2\_%'`(같은 provider의 **다른 subsystem** finding, 예 `curation_mislink:…`를
  쓸어버리지 않음) / **단일 statement**(`trg_data_integrity_violations_ops_live_revision`이
  statement 단위라 finding마다 UPDATE를 돌리면 `ops_live` hot row에 배타 락을 N번 잡아
  `/admin/issues` 쓰기를 막고 데드락까지 만든다 — batch upsert와 같은 이유).

  **retention**: `purge_resolved_integrity_findings(retention='90 days')` +
  dagster op `purge_resolved_integrity_findings`. `feature_repo.purge_expired_notices`(1년)와
  같은 패턴이되 finding은 운영 신호라 분기 회고에 필요한 만큼만 둔다.
  `acknowledged`는 어떤 경우에도 지우지 않는다.

  > **flap은 아직 관측되지 않았다.** close를 켜면 resolved가 쌓이기 시작하고, 재발하는 finding은
  > 부분 유니크 인덱스 밖으로 나갔다 돌아오며 사이클마다 새 행을 남긴다. 지금은 prod finding이
  > 3건뿐이라 flap 비율을 측정할 데이터가 없다. **A(시간 기준)로 시작하고, 첫 몇 run에서
  > resolved 증가율을 재서 dedupe_key별 상한(B)이 필요한지 판단한다** — 관측되지 않은 문제에
  > 선제 대응하지 않는다.

  검증: 통합 테스트 **15 passed**(기각된 3모드 미재현 / `acknowledged` 불가침 / 다른 subsystem
  미침범 / provider 경계 / 빈 `run_id` fail-closed / `resolution` 스탬프·멱등 / retention 양방향),
  n150 CI-parity **2278 passed**, `mypy --strict` **196 files clean**.

- [x] T-VN-H32R — **PR #908 사후 감사의 close·retention 불변식을 보강한다 (#911~#913)**

  exact head `312b1b4b` 적대 리뷰에서 기존 H32 완료 판정을 뒤집는 P1 두 건과 P2 한 건이
  재현됐다. `record_sync_success`는 provider 적재 성공일 뿐 absence를 부정 증거로 쓸 수
  있는 완전한 관측 receipt가 아니다. MOIS empty fallback과 finding 저장 불완전에서도
  close가 호출되고, 단일 mutable `observed_run_id`는 A upsert→B upsert→A close 교차에서
  A가 실제 관측한 finding을 resolved 처리한다. retention op도 어떤 Dagster job에 없었다.

  - [x] **#911** — source snapshot이 authoritative·complete이고 현재 run finding 전량이
    durable하게 기록됐다는 typed receipt가 있을 때만 close한다. empty/partial/transform·load
    일부 실패/finding 저장 실패·`unrecorded_count > 0`은 모두 close 0회로 fail-close한다.
  - [x] **#912** — migration 0071이 provider/dataset scope, external run generation,
    run별 dedupe-key observation set을 정규화한다. scope row lock이 generation 배정과
    authoritative fence를 직렬화하고, current run과 더 새 partial run의 관측은 immutable
    anti-join으로 sweep에서 보호한다. A/B 교차·역순·동시 allocation을 실제 PostgreSQL로
    검증한다.
  - [x] **#913** — resolved purge op을 `MAINTENANCE_JOBS`와 schedule이 실제 실행하는 graph에
    등록하고 Definitions node·execute-in-process의 retention config/metadata를 검증한다.

  migration은 PR #906의 0070 landing 뒤 단일 head를 기준으로
  `0071_integrity_observations`에 추가했다.

- [x] T-VN-H25A — **미연결 membership evidence manifest** (전제 정정 포함)

  prod 단일 snapshot에서 존재 여부·lifecycle/merge·공식 collection 범위 정합을 대조했다.
  주요 산출: 전제 반증(§1·§2), CSV 217/269 vs DB 225/261로 **같은 모집단이며 DB가 8건 앞섬**(§3),
  미연결의 지배 원인은 수목원이 아니라 **등대 103건**(105 중 2건만 링크, §4).
  자체 matcher는 결함이 확인돼 후보 등급 산출에는 쓰지 않는다 — CSV `metadata_json`의
  `feature_match_confidence`(review 183 / unmatched 86)가 기준선이다(§5·§6).

  **미충족 AC — 산출물을 바꿔 닫았음을 명시한다.** 전제가 반증된 이상 원래 형태의 후보
  manifest는 의미가 줄었고, 실행 가능한 잔여 작업은 아래 H25B로 이관했다. `[x]`는 "AC 전부
  충족"이 아니라 "전제 반증·재측정으로 종결"의 뜻이다.

  | AC 항목 | 상태 | 이관 |
  | --- | --- | --- |
  | lifecycle/merge history 대조 | 충족 | — |
  | 동일 DB snapshot | 충족 (prod 단일) | — |
  | 좌표 근접만으로 자동 승인 안 함 | 충족 | — |
  | CSV/DB target 미변경 | 충족 | — |
  | provider provenance 대조 | 부분 — `source_record_key` 유무(0건)만 확인, `provider_sync.source_entities` 미조인 | H25B ② |
  | 이름 대조 | 부분 — matcher 결함(괄호·`&` 복합명·포함 방향·`status='active'` 한정) 확인 후 등급 산출에서 배제 | H25B ② |
  | 주소 대조 | **미충족** — `address_hint`가 486행 전부 비어 축이 없음. `region`(118/269 보유)은 미반영 | H25B ② |
  | candidate·confidence·근거 manifest 산출 | **미충족** — JSON 미커밋, 리포트 표로 대체 | H25B ② |

- [x] T-VN-H34R — **H34 링크 evidence를 linked target·공개 snapshot에 결박한다 (#914)**

  - [x] `place_name`과 linked `feature_name`을 동일 정규화 함수로 exact 비교하고, 동명
    후보 query는 count가 아니라 candidate `feature_id`를 반환해 현재 링크와 결박한다.
    linked-name mismatch는 독립 axis/evidence이며 무관한 동명 Feature로 pass할 수 없다.
  - [x] `--scope public`은 공개 curation 정본(`source_present`, included,
    collection published/public/unarchived, theme public, `feature.public_features`)을
    repository 함수로 재사용한다. H25B 내부 승인 5건은 `--scope approved`로 분리한다.
  - [x] 대상 rows와 name candidate evidence를 read-only repeatable-read transaction
    하나에서 읽고 결과에 scope, 대상 수, snapshot identity를 기록한다.
  - [x] linked-name mismatch와 source removed/excluded/draft/admin-only/private-theme/
    inactive 공개 경계를 회귀 테스트로 고정한다. 실제 migrated PostgreSQL에서 별도
    connection의 committed fixture를 `audit_database()`로 읽어 transaction isolation과
    read-only metadata까지 검증한다.

- [~] T-VN-H40 — **concierge curation provenance 복구 (H35 배포 선행 blocker)**
      — **구현·검증 완료(`0073`+`0074`, PR #919/#925). 남은 것은 H35 배포 시 실행뿐이다.**

  `0072_curation_provenance`가 기존 link를 전부 `accepted + legacy_unattributed`로 이관하고,
  `_trusted_link_sql()`이 `match_basis <> 'legacy_unattributed'`를 요구한다. 이 술어는 public
  collection count/detail·Feature group/detail/list 경로에 **실제로 적용**되므로, 배포 직후
  기존 공개 curation 링크가 공개 표면에서 사라진다. **fail-close 자체는 ADR-063이 명시한
  의도된 동작이다**(legacy/unattributed link는 admin 감사 대상으로만 남긴다).

  문제는 **복구 경로가 없다는 것**이다. 현재 존재하는 경로는 셋뿐이다:
  authoritative CSV 재import(`csv_explicit_feature_id`) / admin 수동 검토(`admin_review`) /
  이미 non-legacy accepted decision이 있던 merge 대상(제한된 `forward_recovery`).

  - **공식 CSV 222건**은 exact CSV + provenance sidecar를 새 계약으로 재import하면 첫 경로로 복원된다.
  - **concierge projection 3,044건은 일괄 복원 경로가 코드에도 `tasks.md`에도 없다.**
    `0065`의 `sync_curated_feature_collection()`은 `curation_items.feature_id`/projection을
    쓰지만 `curation_import_rows`·`curation_link_decisions`를 만들지 않고,
    `apply_curated_source_rules()`도 `feature.curated_features`만 갱신한다.
    → **후속 task로 분리된 것이 아니라 누락이다**(PR #910 작성자 확인).

  > **축소 창은 "최대 한 달"이 아니라 무기한이다.** `40 3 3 * *`는 concierge **원천 Feature
  > 적재** 스케줄이라 실행돼도 trusted decision을 만들지 않는다.
  > `curated_features_refresh_daily_schedule`은 기본 STOPPED이고 수동 실행해도 현재
  > writer/trigger가 decision을 추가하지 않는다. **별도 복구를 구현·실행하기 전까지 회복되지 않는다.**
  > (초안에서 내가 "월 1회 스케줄이라 최대 한 달"이라 적은 것은 스케줄 이름만 보고
  > 자연 회복을 가정한 오류다.)

  ## 조사로 확정된 것 (2026-07-31)

  **`match_basis` 허용값은 4개다**(`0072` `ck_curation_link_decisions_basis`):
  `csv_explicit_feature_id` · `admin_review` · `legacy_unattributed` · **`forward_recovery`**.
  그 생성 경로는 **merge 승인 한 곳뿐**이다(`merge_repo.py:339`, `:451`).
  (이 문단은 처음에 "복구용 축이 이미 있으니 **새 값을 만들 필요가 없다**"고 적었으나
  아래 판정에서 뒤집혔다 — `forward_recovery`는 "합쳐진 대상의 결정을 이어받는다"는
  merge 전용 의미라 projection에 빌려 쓰면 의미가 왜곡된다. `0073`은 `source_rule`을 더한다.)

  **`0065`가 `sync_curated_feature_collection()`의 최신 정의다.** `0066`~`0072` 어느 것도
  이 함수를 갱신하지 않는다(전수 확인). 그 함수가 `curation_items`에 쓰는 어느 경로에도
  `accepted_link_decision_id`가 **없다**. 그래서 트리거가 만드는 projection은 항상
  decision 없이 태어나고, `_trusted_link_sql()`에서 제외된다.
  → **#910 답변의 진단이 코드로 확인됐다.**

  > **정정(2026-07-31 실행 확인)** — 위 문단은 처음에 "`curation_items`를 DELETE 후
  > INSERT한다(`0065:892`)"고 적었는데 **틀렸다.** `0065` 파일에는 이 함수 정의가 두 번
  > 나오고 `:835`는 **downgrade가 되돌리는 옛 본문**이다. 실제 최신 정의(`:28`)는 DELETE 없이
  > targeted UPDATE 여러 개 + `INSERT ... ON CONFLICT DO NOTHING`을 쓴다. 컨테이너에 `0072`를
  > 올리고 직접 확인했다 — projection UPDATE 후 item의 `ctid`는 바뀌지만
  > `accepted_link_decision_id` 포인터는 **살아남는다**(재작성이 아니라 갱신).
  >
  > 이 오독은 결론을 두 개 바꿀 뻔했다: ① `fk_curation_link_decisions_item`이
  > `ON DELETE RESTRICT`라 "0072 배포 후 concierge writer가 통째로 죽는다"고 볼 뻔했다 —
  > 직접 DELETE는 실제로 RESTRICT에 막히지만(확인함) 트리거가 DELETE를 하지 않으므로
  > 그 경로는 발생하지 않는다. ② "재삽입마다 decision이 누적된다"는 우려도 같은 이유로
  > 성립하지 않는다. 그래도 누적 축은 **회귀 테스트로 고정했다** — 미래에 writer가 바뀌면
  > 되살아나는 위험이기 때문이다.

  ## 실증 (2026-07-31, 격리 restore clone — prod 무접촉)

  prod 백업(`20260731T065308Z`)을 포트 노출 없는 임시 컨테이너에 복원하고 `0064~0072`를
  적용해 **직접 셌다.** 그전까지 이 수치는 "코드상 확정·실행 미검증"이었다.

  ```
  배포 전  linked_items(active)          3,266
  배포 후  linked_items(active)          3,266    ← 링크 자체는 남는다
           decision 보유                 3,266
           legacy_unattributed decision  3,266    ← 전부 이 값
           ** 공개 노출 가능(trusted)        0    ← 전멸
  alembic  0064 → 0072  소요 1,754초 (29분)
  ```

  **내 예상치 "3,265 → 264"가 틀렸다.** 264는 `feature_id IS NULL`이라 애초에 링크가 아니었다.
  trusted 링크 기준으로는 **3,266 → 0**이다. 즉 `T-VN-H40` 없이 배포하면 **공개 curation이
  전멸한다.**

  그리고 **마이그레이션 29분은 `ktdctl deploy`의 `--wait-timeout 120`(하드코딩)을 14배
  초과한다** — B′ 경로(마이그레이션을 배포와 분리)의 근거가 추정이 아니라 실측이 됐다.

  > **정정 (2026-08-01) — 이 1,754초는 배포 시간의 근거로 쓸 수 없다.**
  > 같은 절차를 `0074`까지 포함해 다시 재니 개발 환경(WSL)에서 **79.9초**가 나왔다.
  > 22배 차이의 원인을 조사하니 **측정 조건 자체가 배포 조건과 다르다**:
  > `scripts/h35/h35_migrate.sh`는 마이그레이션 **전에 dagster-daemon을 정지시키는데**,
  > 1,754초 측정도 이번 n150 재측정도 **dagster가 도는 상태에서** 쟀다.
  > n150 실측 시도 중 확인한 그 시점 호스트 상태 — 4코어에 load average 11.6,
  > iowait 44.7%, 동시에 T-VN-41 lane의 Playwright buildx 빌드 + 제품 스택 2벌 라이브
  > 검증 + prod dagster ETL이 함께 돌고 있었다(누적 I/O 66GB read/91GB write 유발로
  > 판단해 측정을 중단하고 정리했다).
  >
  > **결론: 두 수치 모두 경합을 잰 것이고 어느 쪽도 배포 시간이 아니다.** 다만
  > **B′ 경로 자체는 유지한다** — 배포 절차가 이미 dagster를 멈추고 시간 제한 없는
  > 일회성 컨테이너로 마이그레이션을 돌리므로, 정확한 초수를 몰라도 `--wait-timeout 120`
  > 리스크가 구조적으로 제거된다. 즉 이 수치는 **B′의 근거로 필요하지 않다.**
  > (하드웨어 무관한 논리 결과 — trusted 3,043/공백 223, H41 FK CASCADE 동작 — 는
  > 격리 clone에서 정상 검증됐다.)

  ## 판정 (2026-07-31 prod 실측) — **근거는 실재한다. `legacy_unattributed`는 틀린 분류다.**

  ```
  curated_features            3,044
    source_record_key   3,044 / 3,044  (100%)  → provider_sync.source_records FK 100% 도달
    selection_origin    3,044 / 3,044  (100%)  → source_rule 3,043 / admin 1
    content_version     3,044 / 3,044  (100%)
  provider              kor-travel-concierge-youtube 3,044
  legacy collection 링크 3,044 (전부 source_record_key 보유)
  ```

  **결손 0건이다.** 각 링크에 대해 "이 provider record에서 이 rule로 나왔다"가 **완전히
  재구성된다**. `0072` backfill의 evidence 문구 *"기존 link의 선택 근거를 안전하게 복구할 수
  없음"* 은 이 3,044건에 대해서는 **사실이 아니다**.

  `0072`가 틀린 게 아니라 **범위를 넓게 잡았다** — `feature_id IS NOT NULL`이면 무조건
  `legacy_unattributed`로 이관했고, 그 안에 근거가 완전한 3,044건이 섞였다.

  > **내 초안 두 가지가 틀렸다.**
  > ① **`forward_recovery` 재사용은 의미 왜곡이다.** 그 값은 merge 경로에서 "합쳐진 대상의
  >    결정을 앞으로 이어받는다"는 뜻인데(`merge_repo.py:325-460`), concierge projection은
  >    merge와 무관하다. 이름을 빌려 쓰는 것이다.
  > ② **"트리거가 자동 발급하면 fail-close가 무력화된다"는 우려는 조건부로만 맞다.**
  >    근거 유무를 구분하지 않고 전부 승격하면 그렇다. 그러나 `selection_origin='source_rule'`과
  >    `source_record_key` FK를 **검증한 것만** 승격하면 게이트는 남는다 — 근거 없는 링크는
  >    여전히 제외된다.

  ## 확정 설계 — `0073`로 `match_basis`에 `source_rule` 추가

  `0072`의 `ck_curation_link_decisions_basis`는 4값(`csv_explicit_feature_id` ·
  `admin_review` · `legacy_unattributed` · `forward_recovery`)만 허용한다. 여기에
  **`source_rule`** 을 더한다. 이유는 위 판정 그대로 — 근거의 성격이 기존 4값 어디에도
  해당하지 않는다.

  `curation_link_decisions`의 NOT NULL 컬럼과 CHECK(실측):

  | 컬럼 | 제약 | `source_rule` decision이 채울 값 |
  | --- | --- | --- |
  | `curation_item_id` | NOT NULL, FK→items RESTRICT | projection의 item |
  | `feature_id` | NOT NULL | `curated_features.feature_id` |
  | `decision_kind` | `IN ('accepted','revoked')` | `accepted` |
  | `match_basis` | CHECK 4값 → **5값으로 확장** | `source_rule` |
  | `resolver_version` | `= btrim() AND <> ''` | `curated_features.content_version` |
  | `evidence` | `jsonb_typeof = 'object'` | `{source_record_key, selection_origin, content_version, provider}` |
  | `actor` | `= btrim() AND <> ''` | `curated_features.selected_by` (없으면 `source_rule:<provider>`) |
  | `supersedes_decision_id` | self와 달라야 함 | 재삽입 시 직전 decision |

  ## 두 갈래

  **① one-shot** — 기존 3,044건에 `source_rule` decision을 append하고 포인터를 채운다.
  **검증 술어를 명시한다**: `selection_origin='source_rule'` **그리고**
  `source_record_key`가 `provider_sync.source_records`에 도달할 것. 둘 중 하나라도 실패하면
  **승격하지 않고 `legacy_unattributed`로 남긴다** — 그게 fail-close를 지키는 지점이다.
  실측상 3,044건 전부 통과하지만, **술어를 조건 없이 통과시키는 게 아니라 실제로 검사한다.**

  **② ongoing** — `sync_curated_feature_collection()`(`0065`가 최신 정의, `0066`~`0072`
  아무도 안 고침)이 `curation_items`를 INSERT할 때 같은 transaction에서 decision도 만든다.
  그 함수는 `NEW`(=`curated_features` 행)를 갖고 있으므로 위 표의 값을 **전부 채울 수 있다** —
  DB 트리거에 actor/evidence 맥락이 없다는 일반론이 여기서는 해당하지 않는다.

  > **누적 축** — `0072`의 append-only 트리거가 decision UPDATE/DELETE를 막으므로, 발급
  > 조건이 느슨하면 decision이 단조 증가한다. 처음엔 "트리거가 item을 DELETE 후 INSERT하니
  > 재삽입마다 쌓인다"고 봤으나 그 전제는 위 정정대로 **틀렸다**. 그래도 갱신 1회마다
  > 1건씩 쌓는 설계는 얼마든지 가능하므로 **회귀 테스트로 고정한다**(`0067` dedupe 계열).
  >
  > **FK 순환** — `curation_items.accepted_link_decision_id` → `curation_link_decisions` →
  > `curation_items`가 서로를 참조한다. `0072`가 그 FK를 DEFERRABLE INITIALLY DEFERRED로
  > 만든 이유가 이것이고, 트리거 안에서 둘을 만들 때 그 성질에 의존한다.

  ## ⚠ 배포 전 남은 것 두 개 (2026-08-01 prod 실측 + 적대 검토)

  `0073`만으로는 H40이 닫히지 않는다. **읽어서 넘길 수 없는 수치가 둘 있다.**

  ### ① 공개 노출 item 3,265 → **3,043**. 222건이 어두워진다 (격리 clone 실증)

  `0073`의 승격 술어는 concierge projection만 통과시킨다. 격리 restore clone에서
  배포 전/후를 **공개 목록 술어 그대로** 셌다:

  ```
  배포 전 (0063, prod 현재)          공개 노출 item  3,265
  마이그레이션 직후 (0064~0074)      공개 노출 item  3,043   ← -222
  ```

  어두워지는 222건 — 전부 **공식 CSV 큐레이션**이다:

  | collection | 건수 |
  | --- | --- |
  | `korean-tourism-100:2025-2026` | 58 |
  | `korean-tourism-100:2023-2024` | 51 |
  | `arboretum-garden-stamp-tour:2026` | 44 |
  | `heritage-visit-campaign:*` (11개 route) | 67 |
  | `lighthouse-stamp-tour:*` | 2 |

  > **정정 — 앞서 "223건"이라고 적은 것은 틀렸다.** 그 223번째는
  > `[빵이네] 강원도여행정보`(`selection_origin=admin`, **`item_status='rejected'`**)인데,
  > 공개 목록 술어가 `i.status = 'included'`를 요구하므로(`curation_repo.py:589`)
  > **애초에 공개 표면에 없던 항목**이다. 내 공백 측정 쿼리가 `status <> 'archived'`만
  > 걸러 `rejected`를 포함시킨 오류였다. 실제 공개 공백은 **222**다.

  이들은 `curated_features` 행이 없고(projection이 아니다) `source_record_key`도
  없다. 대신 `metadata`에 `feature_match_reasons`·`feature_match_partial`·
  `official_place_name`을 갖고 있고, **`resources/curations/*.csv` 5개 파일이 정확히
  222행에 `feature_id`를 채워 두고 있다**(486행 중 222행 — DB 링크 수와 일치).

  > **처음에 `metadata`의 `feature_match_partial=false`(199건)로 승격 대상을 가르려
  > 했는데, 그건 마이그레이션에 휴리스틱을 새기는 것이다.** `0072`는 이미 이 부류를
  > 위해 `csv_explicit_feature_id` basis와 import batch/row 계보를 만들어 뒀다.
  > 정본 CSV를 **재import하면** 설계된 경로로 진짜 import 계보와 함께 근거가 붙는다.

  **결론 — 배포 절차에 단계를 하나 넣는다.** 마이그레이션(`0064~0074`) 직후,
  **새 이미지를 올리기 전에** 공식 curation CSV 5개를 재import한다. 구 이미지는
  `_trusted_link_sql`을 모르므로 그 구간에도 계속 서빙한다 → **공개 표면 공백 0**.
  배포 게이트: 재import 후 **공개 노출 item = 3,265**(배포 전과 동일)인지 확인한다.

  #### 게이트 실증 — 격리 clone에서 재현 완료 (2026-08-01)

  실제 import 경로(`parse_curation_csv` → `resolve_feature_matches` →
  `_adopted_match` → `import_curation_rows`; HTTP/인증만 제외)를 격리 clone에 태웠다:

  ```
  배포 전 baseline                   공개 노출 item  3,265
  마이그레이션 직후 (재import 전)     공개 노출 item  3,043   (-222)
  CSV 재import 후                    공개 노출 item  3,265   (±0)  ← PASS
  ```

  CSV 222행 **전량 채택**(미채택 0), `csv_explicit_feature_id` decision 222건 생성.
  파일별 채택: arboretum 44 / heritage 67 / kt100-2023 51 / kt100-2025 58 / lighthouse 2.

  > **게이트 값으로 "trusted link 수"를 쓰면 안 된다.** 링크 수 기준으로는 3,265가
  > 나오는데(3,043 + 222), 위 `rejected` 1건 때문에 "3,266이어야 한다"는 기대와
  > 어긋나 **정상 배포에서도 FAIL**이 뜬다. 게이트는 반드시 **공개 목록 술어로 센
  > item 수**(`status='included'` + collection public/published + theme public +
  > trusted decision)를 쓴다.

  #### 재import가 정말 복구하는지 — 코드 경로로 확정 (2026-08-01)

  "재import하면 붙는다"는 처음엔 **추론이었다.** #907/#910이 자동 링크를 조였으므로
  조인 resolver가 이 222건을 더 이상 채택하지 않을 가능성이 실재했다. 경로를 따라가
  확정했다:

  1. `_RESOLVE_FEATURES_BATCH_SQL`(`curation_repo.py:1608`)의 UNION 첫 분기는
     `requested.feature_id IS NOT NULL`일 때 **그 feature_id로 정확히 1행**만 낸다
     (`deleted_at IS NULL AND status NOT IN ('deleted','hidden')` 조건). 이름 기반
     후보 탐색(둘째 분기)은 `feature_id IS NULL`일 때만 돈다.
  2. `_adopted_match`(`routers/curations.py:618`)는 *"CSV가 명시한 exact Feature ID만
     자동 채택한다"* — `row.feature_id`가 있고 `len(matches) == 1`이면 채택한다.
  3. 채택되면 `import_curation_rows`가 `match_basis='csv_explicit_feature_id'` decision을
     만들고 `supersedes_decision_id`로 직전 결정을 이으며 `accepted_link_decision_id`를
     채운다(`curation_repo.py:3324` 부근).

  **#907/#910이 제거한 것은 `address_hint` 단독 자동 링크이고, 명시 `feature_id`
  경로는 그대로다.** 따라서 CSV 222행(전부 `feature_id` 보유)은 대상 Feature가 살아
  있는 한 전량 복구된다 — 이것이 `0073`에 휴리스틱을 넣지 않고 재import로 미룬 근거다.

  ### ② 모든 dedup 병합이 abort한다 — `T-VN-H41` (신규, `0072` 결함)

  `merge_repo._DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL`은
  `curation_items.curation_item_id`를 **새 UUID로 재작성**한다. `0072`의
  `fk_curation_link_decisions_item`은 `ON DELETE RESTRICT` + `ON UPDATE NO ACTION`이라,
  decision이 달린 item이면 그 UPDATE가 FK 위반을 내고 **병합 전체가 롤백된다.**

  `0072`만 적용한 컨테이너에서 재현했다 — `0073`이 만든 결함이 아니다. 다만 `0072`가
  미배포라 **이번 배포와 함께 prod에 도달**한다. 그리고 기존 merge 통합 테스트의
  curated 픽스처가 **전부 `selection_origin='admin'`** 이라 0073 트리거가 merge
  경로에서 한 번도 안 돌았고, 그래서 이번 검토에서 나온 merge 결함 3건이 모두 green으로
  통과했다. prod 모양(`source_rule`) 테스트를 추가해 `xfail(strict=True)`로 고정했다 —
  **xfail 제거가 H41의 완료 조건**이다.

  고치는 길은 두 갈래였다:
  - (a) 관련 FK에 `ON UPDATE CASCADE`. append-only 트리거가 RI cascade의 UPDATE를
    막으므로, "`curation_item_id`만 바뀌는 UPDATE는 이력 변경이 아니다"는 예외를
    명시해야 한다.
  - (b) merge의 detach가 PK를 재작성하지 않게 바꾼다. `0045` 전환 트리거의 UUID 충돌을
    피하려고 재작성하는 것이라(주석 `merge_repo.py:770-773`) 대안 설계가 필요하다.

  **(a)로 결정하고 구현 완료** (2026-08-01, `0074_curation_item_rekey_cascade`,
  같은 브랜치·PR #919). 애초 생각한 것보다 관련 FK가 많았다 — `fk_curation_link_decisions_item`
  하나가 아니라 **4개**: `fk_curation_import_rows_item` · `fk_curation_link_decisions_item` ·
  `fk_curation_link_decisions_import_row`(합성 — import row 쪽도 캐스케이드된 뒤에야
  다시 일관됨) · `fk_curation_link_decisions_supersedes`(자기참조 합성 — supersedes 사슬
  전체가 같은 item이라는 불변식을 강제).

  append-only 트리거 예외는 `curation_item_id` **하나만** 바뀐 `UPDATE`만 통과시킨다.
  첫 구현이 `NEW.curation_item_id`를 정적으로 참조해 그 컬럼이 없는
  `curation_import_batches`에서 `UndefinedColumnError`로 죽었는데, **기존** 테스트
  `test_link_provenance_is_append_only_fail_closed_and_recoverable`가 잡았다 — jsonb
  동적 조회로 고쳤다. `models.py`의 ORM FK 선언도 `onupdate="CASCADE"`로 맞췄다(안
  그러면 `alembic check` drift로 걸린다 — 실제로 걸렸다).

  `apply_feature_merge()`를 실제로 부르는 xfail 테스트가 **XPASS로 전환**돼 수정을
  1차 확인했고, 변이 2회(CASCADE 제거 / 예외 무조건 통과로 넓힘)로 falsifiability도
  확인했다. 적대적 리뷰어 2명 + 검증을 붙였다(별도 리포트).

  ## 구현 완료 (2026-08-01, `0073_curation_source_rule`)

  확정 설계대로 넣었다. 설계에서 **바뀐 것 하나**: 트리거를 `curated_features`가 아니라
  **`curation_items`** 에 단다(`trg_curation_items_source_rule_decision`).
  `sync_curated_feature_collection()`은 link을 만드는 지점이 **둘**(신규 item INSERT,
  `source_change` 시 `feature_id` UPDATE)이고 merge/detach 불변식이 얽힌 800줄이라,
  그 안을 두 군데 고치는 것보다 불변식이 실제로 사는 자리 — "feature_id를 가진 item에는
  근거가 있어야 한다" — 에 거는 편이 두 지점을 모두 덮고 앞으로 생길 writer도 덮는다.

  검증 술어는 **4조건**으로 늘렸다(설계의 2조건 + link 정합성 2개):
  `selection_origin='source_rule'` · `projection.feature_id = item.feature_id` ·
  `projection.source_record_key = item.source_record_key` · 그 key가
  `provider_sync.source_records`에 도달. 하나라도 실패하면 `legacy_unattributed`로 남는다.

  **함께 고친 것 — 승인 근거 판정이 두 곳에 다른 모양으로 있었다.** 공개 표면은
  denylist(`<> 'legacy_unattributed'`), merge 재타게팅은 whitelist(3값 열거,
  `merge_repo._MOVE_CURATION_ITEMS_SQL`). 값이 늘 때 whitelist만 뒤처지면 **공개 표면은
  노출하는 link을 merge가 `revoked`로 끊는다** — 어느 쪽도 오류를 내지 않아 "링크가
  언젠가 사라짐"으로만 나타난다. `infra/curation_link_basis.py` 한 곳으로 모으고
  양쪽 다 whitelist로 맞췄다(모르는 근거를 기본 신뢰하지 않는 쪽이 `0072` 원칙과 같은 방향).

  게이트: unit **1821 passed** · 관련 integration **91 passed** ·
  `ruff`/`mypy --strict`(123 files)/`lint-imports`(4 kept). 새 통합 테스트 6건은
  **변이 2회로 falsifiability를 확인**했다 — 검증 술어에서 `selection_origin`을 빼면
  fail-close 테스트 2건이, 재진입 가드를 빼면 누적·멱등 테스트 3건이 죽는다.

  곁가지로 `test_alembic_upgrade.py`가 head revision을 리터럴로 박고 있어 마이그레이션을
  추가할 때마다 깨졌다. ScriptDirectory에서 계산하도록 바꿨다.

  할 일 (2026-08-03 기준 — 4항목 중 3 완료, 1은 H35 실행 대기):

  - [x] **before/after exact count 확정** — 격리 restore clone에서 `0063→0078`을 적용해
        **공개 목록 술어 그대로** 셌다. 예상치 `3,265→264`는 폐기한다.
        `preflight 3,265 → migrate 3,043 → csv5 3,265`. 세부는 runbook §10.1.
  - [x] **one-shot 복구 경로** — `0073_curation_source_rule`. `legacy_unattributed`를 이름만
        바꾸거나 public 술어를 완화하지 **않았다**. `match_basis`에 `source_rule`을 더하고
        **검증 4조건**(`selection_origin='source_rule'` · projection↔item `feature_id` 일치 ·
        `source_record_key` 일치 · 그 key가 `provider_sync.source_records`에 도달)을 통과한
        3,043건만 append했다. `forward_recovery` 재사용은 의미 왜곡이라 하지 않았다.
  - [x] **ongoing writer 연결** — `trg_curation_items_source_rule_decision`을 `curation_items`에
        달았다. `sync_curated_feature_collection()`은 link 생성 지점이 둘이고 merge/detach
        불변식이 얽힌 800줄이라, 불변식이 실제로 사는 자리에 걸어 두 지점과 미래 writer를
        함께 덮는다.
  - [ ] **H35 실행 시**: writer reopen 전에 CSV 재import(3.5 단계)를 돌리고, 공개 표면
        3,265 복원과 #673의 미적재 457 회복을 **각각 별도 기준으로** 검증한다.
        → 재import가 222건을 전량 복원하는 것은 실 prod 데이터로 확인했다(runbook §10.1).

  **파생 발견**: `0072`의 `fk_curation_link_decisions_item`이 `ON UPDATE NO ACTION`이라
  merge의 legacy-conflict detach(`curation_item_id` 재작성)가 FK 위반으로 abort한다.
  `0074_curation_item_rekey_cascade`로 해소했다(`T-VN-H41`).

- [ ] T-VN-H35 — **prod 마이그레이션 지연 해소 (0064~0078)**

  ## ⛔ 재정의 (2026-08-04) — cutover는 사건으로 소멸했다. 폐기·재생성으로 대체한다

  **이 항목 아래의 cutover 설계(0063 전제)는 전부 이력이다. 실행하지 마라.**

  2026-08-03, pin(`map_release_revision=4a764a4f`)과 달리 **7/31 빌드(`0bdecb1f`,
  alembic head `0072`) 이미지가 배포**됐고, `docker/api-entrypoint.sh`의 무조건
  `alembic upgrade head`가 prod를 `0063 → 0072`로 올린 뒤 오류 없이 끝났다. `0073`
  (링크 3,043건 복구)이 이미지에 없어 **공개 큐레이션 표면이 3,265 → 0건**이 됐다.
  이 문서가 경고했던 "공개 curation 표면이 배포 직후 전멸한다(실증)"가 정규 cutover
  절차 **밖에서** 그대로 실현된 것이다. 상세: kor-travel-docker-manager#109.

  **사용자 결정: 데이터를 복구하지 않는다. 폐기 후 재생성한다** (서비스 전이므로 데이터를
  살릴 필요 없음). 빈 DB에 `alembic upgrade head`를 걸면 곧장 `0078`로 생성되고, `0063 →
  0078` 데이터 마이그레이션 위험 구간(0072 전멸 창 포함)이 통째로 사라진다. 이 경로는 CI
  integration(PostGIS) job이 매번 검증한다.

  따라서:
  - **typed cutover helper(`_h35_schema.py`·`_h35_contract.py`·`scripts/h35/`)는 사문화됐다** —
    `PRE_SCHEMA=0063`·`EXPECTED_PRE_PUBLIC=3265`·`EXPECTED_MIGRATED_PUBLIC=3043`이 소스
    상수라 재생성 후 preflight부터 영구 거부된다. (prod가 `0072`가 된 시점에 이미 거부
    상태였다.) 제거/축소는 후속 정리 task로 잡는다.
  - **"결합 barrier" 항목은 취소한다** — cutover 자체가 없어졌다.
  - tvn41(T-VN-41)은 **무영향** — 스택 3개 전부 자체 map-db(`kor_travel_map`)를 쓰고 prod
    무참조, live spec 기대값은 env 주입(2026-08-04 실측). 오히려 재생성 후 prod가 `0078`이
    되면 41C "PinVi consumer enable"의 schema 선행조건이 충족된다.

  ### 남은 실행 (= 현 H35)

  1. [x] 사고 시점 dump 아카이브 — `n150:~/backups/krtour_map_0072_20260803T203706Z.dump`
     1.2G, sha256 `bbba5216…379f`. **복원 검증 완료**(격리 clone, pg_restore 오류 0줄,
     1,817초; postgis 이미지는 init 완료 후 **새 DB를 만들어** 복원해야 한다 — `POSTGRES_DB`
     에는 확장이 미리 심어져 충돌). H22C 파괴적 live e2e의 실데이터 픽스처 후보로도 쓴다.
  2. [x] 재발 방지 게이트 — PR #931(`KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`; 2차 적대
     리뷰 F2로 `MODE=none`은 도입 전 제거 — 명분이던 H35 helper가 사문화돼 소비자 없는
     fail-open 스위치였다). Docker-manager 쪽 image↔pin 일치 검사는 이슈 #109로 요청.
     **주의(2차 리뷰 F1)**: prod compose(manager 소유)는 고정 `environment:` 목록이라
     호스트 export만으로는 이 env가 컨테이너에 **전달되지 않는다** — 게이트를 켜려면
     manager compose에 명시 값 결선이 필요하다(별도 이슈로 요청). 그 전까지 게이트는
     표준 compose·local-dev에서 꺼져 있는 것이 정상이다.
  3. [x] **완료(2026-08-04)** — `main@2b2dee95`로 3 이미지 재빌드(head=`0078` 수동 게이트
     통과) → `krtour_map` DROP/CREATE → compose recreate(→`0078` 10초) → 3컨테이너 healthy.
     실측 함정 2건: manager `.env`가 root 소유(sudo compose), **신규 DB 확장은 superuser
     사전 생성 필요**(`CREATE EXTENSION`은 superuser 전용, CI는 testcontainers superuser라
     못 잡음 — postgis·pg_trgm·pgcrypto·pg_prewarm + `GRANT USAGE`; #109에 절차 기록).
  4. [~] 데이터 재적재 — **concierge 축 완료**: provider job + `curated_features_refresh`
     성공, features 1,481 · curated 4,424 · **공개 표면 4,424건 복구**(전부 `source_rule`).
     geo API key 결선 공백은 `/tmp` override로 해소(영구 결선은 manager #114).
     **CSV5 486행 적재 완료(2026-08-04)** — 공개 표면 trusted **4,620**(source_rule 4,424 +
     csv_explicit 196), 미해석 290행은 대상 feature 적재 후 재import 필요.
     잔여(나머지 provider ETL 일일 스케줄 수렴 + 290행 재import)의 완주·수렴 검증은
     **`T-VN-H42`가 소유**한다.
  5. [ ] 재적재 안정화 후 H34 잔여 실행 해제(H30B는 재정의판으로 완료).
     **prod live 검증(공개 API·admin UI live 스모크·quarantine 0·공개 표면 최종 수치
     고정)은 이번 사이클에 수행하지 못했다 — `T-VN-H42` AC로 이월(2026-08-04).**
     codex 41C "prod consumer enable"은 재pin(#109 — `2b2dee95` 완료) + `T-VN-H42` 완료
     후가 경계(그 전 격리 스택 작업은 병행 무방).

  ---

  ### (이하 이력) H35×T-VN41 cutover 보정 subtask (2026-08-02)

  과거 2,841줄 H35 runbook은 적대 감사 두 번에서 `NO_GO`였고 현재 `scripts/h35/`도
  `0072`/`0078` 일부를 잘못 검증한다. 그대로 실행하지 않는다. 새 정본은
  [`runbooks/h35-prod-migration-cutover.md`](runbooks/h35-prod-migration-cutover.md)다.

  **공통 계약**: Docker-manager가 backup/migrate/CSV/bootstrap/initial/enable/canary/GC/final fence/
  verify/Pin finalize 전체의 one-process global lock과 mode `0600` durable journal을 소유한다.
  canonical 후반 순서는 `csv5 → canary → gc → exact 5-writer final fence → Map verify → PinVi final
  boundary`다. exact writer 5개는 Map API·Map Dagster web·Map Dagster daemon·PinVi API·PinVi
  Dagster다. Map은 credential/path-free
  `preflight`·`migrate`·`csv5`·`gc`·`verify` helper와 typed receipt만 제공하고 runtime을 재기동하지
  않는다. Map API/Dagster와 Pin writer를 모두 fence하며 old daemon 자동 재기동은 금지한다.
  exact gate는 **공개 3,265 → migration 3,043 → CSV5 accepted 222/rejected 0 → 공개 3,265**다.

  문서 exact head 뒤 다음 두 단위는 같은 파일을 소유하지 않아 병렬 가능하다.

  - [x] **Agent A — Map helper**: `scripts/h35/h35_cutover.py`, typed request/receipt, `0064`/`0068`/
    `0069` partial probe, `0070~0078` transactional 확인, CSV5 멱등성, 기존 client 기반 bounded GC,
    PinVi final DB evidence. orchestration·runtime 수정 금지.
  - [x] **Agent B — 검증**: 실제 PostGIS에서 helper `0063→0078→CSV5→GC→verify`, GC replay,
    generation-7 stream/source/snapshot/reconciliation/outbox/delivery/claim을 재현했다. 구조 catalog
    동명이형·drop·invalid/not-ready/disabled/function drift와 stale/expired/mixed/Merkle/backlog/chain-skip를
    mutation 0으로 거부한다. scope validator는 top/0074/0052 exact regprocedure 전체를 fingerprint하고,
    여섯 scope valid/invalid truth table와 delegate별 body/config/속성/signature/result drift를 실제
    PostGIS에서 검증한다. 최신 writer-fenced prod dump clone 리허설은 결합 barrier에 남긴다.
  - [ ] **결합 barrier**: PR #923 merge 뒤 양쪽을 최신 `origin/main`에 rebase하고, Docker-manager
    typed journal/receipt와 결합한 최종 exact HEAD를 적대 리뷰어 1명이 승인한다. 구현·검증·manager
    결합 전에는 리뷰를 요청하지 않으며, 그 전에는 n150 실행 금지.

  `0075` 적용 전 existing-row identity/NFC/trim/length/CHECK/FK 위반이 전부 0이어야 한다.
  `0075~0078`의 schema/index/outbox/source receipt/GC observation을 최종 verify한다. 일반 image-only
  rollback은 불안전하다. forward 경계 전에는 Map app·Dagster·Pin DB와 manager state/env/manifest를
  결합 복원한 뒤 옛 image를 마지막에 올리고, 경계 뒤에는 옛 restore를 거부한다.

  > **범위 갱신 (2026-07-31)** — `0070_domain_command_ledger`·
  > `0071_integrity_observation_generations`가 이미 main에 있고 #910이 `0072_curation_provenance`를
  > 더한다. **간극은 9개**다.
  >
  > **`0070`·`0071`·`0072`는 `autocommit_block()`을 쓰지 않아 all-or-nothing이다** —
  > 부분 적용 창은 `0064`·`0068`·`0069`에만 있다. `0072` 도중 죽으면 DB는 `0071`에 깨끗이
  > 남고 재실행이 처음부터 다시 한다.
  >
  > `0072` 실측(prod `0063` 기준): 파괴적 statement **0개**. backfill은 `feature_id IS NOT NULL`
  > **3,266행**에 decision 행 생성 + `curation_items` UPDATE. `curation_item_id` PK 1:1 조인이라
  > `feature_id IS NULL` 264행은 술어상 도달 불가. append-only 트리거 6개는 **전부 신규
  > 테이블에만** 붙어 기존 쓰기 경로를 깨지 않는다.
  >
  > ⚠ **`0072` downgrade는 단방향 손실이다** — `curation_link_decisions`를 drop하므로
  > cutover 이후 기록된 **진짜 provenance까지** 사라지고 재구성이 불가능하다
  > (#910의 존재 이유가 "0072 이전 상태는 근거를 복구할 수 없다"이기 때문).
  >
  > ⛔ **배포 선행 blocker: `T-VN-H40`(concierge provenance 복구).** PR #910 작성자 확인 결과
  > 복구 경로가 **누락**이고 축소 창이 **무기한**이다. H40 완료 전에는 `0072` 포함 배포를
  > 진행하지 않는다. 이 상태를 "허용 가능한 일시 축소"로 기록해서는 안 된다.
  >
  > ⚠ **공개 curation 표면이 배포 직후 전멸한다(실증).** 격리 restore clone에서
  > `0064~0072` 적용 후 **공개 노출 가능(trusted) 링크 = 0**(배포 전 3,266). 소요 **1,754초**.
  > 자세한 것은 `T-VN-H40` 실증 절.
  >
  > ⚠ **공개 curation 표면이 배포 직후 급감할 수 있다.** `_trusted_link_sql()`이
  > `match_basis <> 'legacy_unattributed'`를 요구하는데 `0072` backfill이 기존 링크를 전부
  > 그 값으로 기록한다. 코드상 확정·실행 미검증이며 #910에 확인 요청을 남겼다
  > (PR #910 코멘트). **#673의 concierge 표면과 겹치므로 배포 전 답을 받아야 한다.**

  > ## 2026-07-31 중단 시점 상태 — **다음 사람이 여기서 이어받는다**
  >
  > **prod는 무손상이다.** `c8ed6164` / alembic `0063` / 5 런타임 healthy. 배포 시도 2회는
  > 전부 fail-closed로 막혔고 마이그레이션은 한 줄도 적용되지 않았다.
  >
  > ### 확보된 것
  > - **writer-quiesced 백업** (복구점 자격 있음 — `inflight_runs=0`·`app_write_tx=0` 확인 후 채취):
  >   - `n150:/home/digitie/h35/backup/krtour_map-20260730T213912Z.dump` 1,168 MiB `sha256=629d1669f8cd3c67…`
  >   - `…/krtour_map_dagster-20260730T213912Z.dump` 65 MiB `sha256=7e331c42b578fdef…`
  >   - `…/baseline-20260730T213912Z.txt` — `alembic=0063` / features 1,030,613 / curation_items 3,530 /
  >     curation_collections 71 / curated_features 3,044 / source_entities 1,035,869 / violations 3
  >   - 그 이전 `20260730T010600Z` dump는 **fence 없이 떠서 무효**다. 쓰지 마라.
  > - **선행 조건 실측 완료**: 디스크 avail **80.7 GiB**(P1 임계 40 통과) / superuser `addr`
  >   자격증명 없이 도달(`addr|t`) / `pg_hba`는 local·127.0.0.1·::1 `trust`, 마지막 줄만
  >   `all all all scram-sha-256` / `archive_mode=off`(**PITR 없음 — dump가 유일 복구점**) / server 16.9.
  > - **자격증명 정합** cache `.env` ↔ live 해시 바이트 동일(지문 `2f2a19e6`).
  > - **runbook** [`runbooks/h35-prod-migration-cutover.md`](runbooks/h35-prod-migration-cutover.md)
  >   — 11단계 절차. **감사 2회 모두 NO_GO**다. 마지막 커밋은 2차 지적을 반영하다 중단한
  >   **미완 상태**이니 그대로 실행하지 마라.
  >
  > ### ⛔ B(단순 `ktdctl deploy`) 경로를 막는 실측
  > `compose_service.py:3540`이 `--wait --wait-timeout 120`을 **하드코딩**한다. 그런데
  > `docker/api-entrypoint.sh:216`이 uvicorn 기동 **전에** `alembic upgrade head`를 돌리고,
  > `0069` 하나만 **8~18분**(1,640만 행 `feature_weather_values`에 CIC 2개, ~3.4 GB)이다.
  > → `ktdctl pinvi-pair deploy`는 120초에 실패 판정하고 **마이그레이션이 도는 중인 컨테이너를
  > 뜯으며 자동 롤백을 발동한다.** `0064`/`0068`/`0069`가 `autocommit_block()`을 쓰므로 그 순간
  > 부분 적용 상태가 남는다. **그대로 실행하면 안 된다.**
  >
  > ### 권고 경로 **B′** (마이그레이션과 배포를 분리)
  > 1. ~~writer-quiesced 백업~~ ✅ 완료
  > 2. **candidate build-only** — 라이브러리 seam `_prepare_c6c_candidate_pair(cfg, build=True, …)`.
  >    실행 컨테이너를 보지 않아 fence 아래에서도 성립한다. ktdctl CLI는 분해 불가
  >    (`cli.py:122`가 `recreate=True` 하드코딩 / `ensure --build`는 production fail-closed /
  >    `capture`는 v4 manifest 존재로 거부).
  > 3. **마이그레이션을 일회성 컨테이너로 적용** — `--entrypoint sh -c 'alembic upgrade head'`,
  >    writer 정지 상태, 시간 제한 없음.
  > 4. **`ktdctl pinvi-pair deploy`** — 이 시점엔 이미 head라 entrypoint의 upgrade가 no-op이고
  >    120초 안에 healthy가 된다. **자동 롤백 기계가 그대로 살아 있다.**
  > 5. 실증(아래 검증 항목).
  >
  > 3→4 사이에 prod가 **새 스키마 + 구 이미지**로 잠깐 돈다. `0069` 방향은 무해하지만
  > **`0065`가 arbiter 인덱스를 바꾸므로 그 창에 curation write가 들어오면 깨진다** — writer를
  > 멈춘 채 곧바로 4로 넘어간다.
  >
  > ### 확정된 최종 순서 (2026-08-01, H40/H41 반영)
  > 범위가 `0064~0072`에서 **`0064~0074`**로 늘었고, 3과 4 **사이에** CSV 재import가 들어간다.
  >
  > | # | 단계 | 왜 이 위치인가 |
  > | --- | --- | --- |
  > | 1 | writer-quiesced 백업 | 유일 복구점(`archive_mode=off`) |
  > | 2 | candidate build-only | fence 아래 성립 |
  > | 3 | `alembic upgrade head` (일회성 컨테이너, dagster 정지, 시간제한 없음) | `--wait-timeout 120` 회피 |
  > | **3.5** | **공식 curation CSV 5개 재import** | `0072`가 어둡게 만든 **223건**을 되살린다. 이 시점엔 구 이미지가 서빙 중이고 구 이미지는 `_trusted_link_sql`을 모르므로 **사용자에게 보이는 공백이 0**이다. 4 이후로 미루면 그 순간부터 223건이 사라진다. |
  > | 4 | `ktdctl pinvi-pair deploy` | 이미 head라 entrypoint upgrade가 no-op |
  > | 5 | 실증 | 아래 게이트 |
  >
  > **3.5의 중단 게이트**: 재import 후 **공개 노출 item = 3,265**(배포 전과 동일)이어야
  > 한다. 3,043이면 재import가 안 붙은 것이고, 그 상태로 4를 진행하면 안 된다.
  > 격리 clone에서 이 세 수(3,265 → 3,043 → 3,265)를 실제로 재현했다.
  >
  > **"trusted link 수"를 게이트로 쓰지 마라** — 링크 수로는 `rejected`인
  > `[빵이네] 강원도여행정보` 1건 때문에 3,265가 나오는데, 그걸 3,266으로 기대하면
  > **정상 배포에서도 FAIL**이 뜬다. 공개 목록과 같은 술어로 센다:
  >
  > ```sql
  > SELECT count(*)
  > FROM feature.curation_items item
  > JOIN feature.curation_collections c ON c.collection_id = item.collection_id
  > JOIN feature.curated_themes t ON t.theme_id = c.theme_id
  > WHERE item.archived_at IS NULL AND c.archived_at IS NULL
  >   AND item.status = 'included'
  >   AND c.status = 'published' AND c.visibility = 'public'
  >   AND t.visibility = 'public'
  >   AND EXISTS (SELECT 1 FROM feature.curation_link_decisions td
  >               WHERE td.decision_id = item.accepted_link_decision_id
  >                 AND td.curation_item_id = item.curation_item_id
  >                 AND td.feature_id = item.feature_id
  >                 AND td.decision_kind = 'accepted'
  >                 AND <trusted_basis_sql('td.match_basis')>)
  > ```
  >
  > `<trusted_basis_sql(...)>`는 `curation_link_basis.trusted_basis_sql()`이 만드는
  > 술어를 그대로 넣는다 — basis 값을 게이트에 하드코딩하면 값이 늘 때 게이트만 뒤처진다.
  > **배포 전 baseline은 `0072` 이전이라 decision이 없으므로** 그 EXISTS 대신
  > `item.feature_id IS NOT NULL`로 센다(같은 3,265가 나온다).
  >
  > ### 배포 target
  > **실행 시점 `origin/main`**(사용자 확정, 0069 포함). main이 계속 전진하므로
  > `/home/digitie/h35/h35b_mkdeploy.sh`가 실행 시점에 target을 확정해 배포 스크립트를 생성한다
  > (검증된 원본에서 **커밋 상수 2줄만** 교체 — flock·자격증명 검증·자동 롤백 보존).
  >
  > ### 실증 항목 (반증 가능해야 한다)
  > `alembic_version = 0069_weather_series_catalog` / `uq_violations_open_dedupe_key` 존재 /
  > `last_seen_at`·`source_present`·`external_component_id` 컬럼 존재 / 이미지에 H36
  > `_adopted_match` 존재 / dagster에 `DROPPABLE_ISSUE_CODES` 존재 / 오링크 3건 미연결 유지 /
  > `GET /v1/curations/collections` 200. 스크립트는 `/home/digitie/h35/h35_verify.sh`
  > (배포 전 baseline에서 6항목이 `★FAIL`로 나오는 것을 확인했다 = 반증 가능).
  > **`features`·`source_entities` 행 수는 고정 통과값으로 쓰지 마라** — 하루 +37 드리프트가 실측됐다.



  prod alembic head `0063_pipeline_root_id` vs 저장소 head **`0068_integrity_last_seen`**
  (0063→0064→0065→0066→0067→0068 단일 체인, 분기 없음). 즉 간극은 **5개**다.
  H30A(`0067` dedupe 부분 유니크 인덱스)를 포함해 **머지된 마이그레이션이 prod에 반영되지
  않았다**. H30A가 주장한 dedupe·`/admin/issues` 접기는 현재 prod에서 성립하지 않는다.

  > **정정(2026-07-30)** — 이 항목은 처음에 `0064~0067`(4개)로 적혀 있었다. 실제 head는
  > `0068_integrity_last_seen`(`down_revision=0067`)이라 **0064~0068 5개**다.
  > `ops.data_integrity_violations.last_seen_at` 컬럼이 prod에 없는 것도 그래서다.

  **이 task는 issue #673의 유일한 결정적 blocker다.** #673("concierge 후보 410건 영구
  미적재")의 규칙 교체는 `T-VN-H28A/B`로 머지됐지만 **prod에 배포되지 않았다** —
  실측으로 prod dagster 컨테이너는 아직 옛 규칙(`provider_address_mismatch`)을 담고 있고,
  live export **1,477**건 대비 prod 적재는 **1,020**건(**457건 미적재**)이다.
  `max(last_seen_at)`이 2026-07-14(이슈 제기일)로 그 뒤 materialize가 돈 적이 없다.
  배포해도 회복은 즉시가 아니다 — 스케줄이 월 1회(`40 3 3 * *`)라 **2026-08-03** 또는
  수동 트리거 시점이다. #673의 남은 절반(실적재 before/after 실증)은 `T-VN-H30B`가 담당한다.

  > **⚠ 마이그레이션만 올리면 안 된다 — 이미지도 함께 올려야 한다.**
  > prod는 "DB만 뒤처진 불일치"가 아니라 **코드·스키마가 일관되게 0063에 고정된 상태**다
  > (배포 이미지 revision `c8ed6164`). 벌어진 간극은 DB↔코드가 아니라 **저장소↔배포**다.
  > 특히 `0065`는 `uq_curation_items_active_identity`(partial, `WHERE archived_at IS NULL`)를
  > drop하고 partial이 아닌 `uq_curation_items_identity`를 만드는데, **지금 도는 이미지의
  > upsert는 `ON CONFLICT (…) WHERE archived_at IS NULL`을 명시**하므로 이미지를 둔 채
  > 마이그레이션만 적용하면 arbiter 추론이 실패해 curation import·admin item 쓰기가 깨진다.
  > `0065`에는 중복 정리용 `DELETE FROM feature.curation_items`도 들어 있다.

  **실측으로 위험도가 재평가됐다(읽기 전용 조사, 2026-07-30)**:
  - `0065`의 `DELETE FROM feature.curation_items`는 **0행**이다. tombstone dedupe가
    `archived_at IS NOT NULL`을 요구하는데 prod에 그런 행이 **0건**이고, 직전 statement가
    새로 만드는 tombstone도 0건(`status='archived'` 0행)이다. 이번 적용에서는 발화하지 않는다.
    다만 **의미론은 위험하다** — tombstone이 하나라도 있는 identity 그룹에서 survivor는
    tombstone이고 같은 그룹의 **active membership까지 삭제**되며, 백업 테이블을 만들지 않는다.
  - 새 유니크 인덱스 `uq_curation_items_identity`의 충돌 그룹 **0개** → 생성 성공한다.
  - `0065`가 `curation_collections.collection_key` **52개를 재작성**한다
    (`legacy:<theme_uuid>:<source_uuid>:<md5(title)>` 형태, 전부 `published`/`public`).
    실체는 concierge YouTube 장소 후보이고 그 안의 공개 item이 3,044건이다.

    > **정정** — 나는 이걸 "외부 계약이 바뀐다 — PinVi 등 소비자가 참조하면 깨진다"고
    > 적었다. **현재 runtime identity lookup 소비자는 없어 52행 재작성으로 깨지는 호출은
    > 확인되지 않았다.** 위험을 확인하지 않고 단정했다.
    > - `collection_key`를 **조회 키로 받는 엔드포인트가 0개**다 — 전부 `collection_id`
    >   UUID 경로다. 다만 admin collection 생성의 필수 입력·저장 필드이고 목록 검색 대상이므로
    >   단순 출력 필드라는 종전 설명은 틀렸다.
    > - e2e live의 하드코딩 `OFFICIAL_COLLECTION_KEYS` 19개와 재작성 52개의
    >   **교집합 0개**다. 19개는 `created_by='admin'`이고 `migrated_from` metadata가 없어
    >   0065의 `WHERE metadata @> '{"migrated_from":…}'`에서 아예 제외된다.
    > - CSV import는 `ON CONFLICT (collection_key)`로 upsert하지만 CSV의 키
    >   (`korean-tourism-100:2023-2024` 등)가 재작성 대상이 아니라 그대로 매칭된다 —
    >   **중복 collection 생성 없음**.
    > - PinVi runtime client·kor-travel-concierge·kor-travel-docker-manager에는
    >   `collection_key` identity lookup이 없다. PinVi pinned OpenAPI snapshot의 schema
    >   field hit는 소비 호출이 아니며 0 hit 주장에 포함하지 않는다. dagster asset/CLI도
    >   runtime lookup이 없다.
    > - 재계산은 **멱등**이다(`(theme_id, source_id, md5(title))` 기반, prod에 NULL/blank
    >   title 0건, base_key 중복 0건이라 `:split:`/`:conflict:` 접미사 미발생).
    >
    > 남는 것은 계약 **문서화** 권고뿐이다(blocker 아님): `collection_key`는 0045→0065에서
    > 형식이 두 번 바뀐 **불안정 business key**다. admin create·저장·검색과 CSV upsert에는
    > 쓰지만 외부의 장기 참조·path identity는 `collection_id`를 써야 한다.
    > `docs/integration-map.md`에 이 경계를 명시한다.
  - `0065` 후반 quarantine 블록도 **no-op**이다 — canonical-only item(`legacy_projection_id
    IS NULL`)이 prod에 0건이다. 새 유니크 인덱스 위반 행도 0건.
  - `0065`의 대량 UPDATE: `source_updated_at` **3,530행 전량**(WHERE 없음),
    `operator_updated_*` 3,044행, `legacy_projection_id` 3,044행.
  - **트랜잭션 경계 함정**: `alembic/env.py`에 `transaction_per_migration`이 **없어**
    0064~0068이 원래 한 트랜잭션이지만, `0064`의 `autocommit_block()`(CREATE/DROP INDEX
    CONCURRENTLY)이 그 트랜잭션을 커밋한다. 따라서 0065가 실패하면 **0064만 적용된 채
    `alembic_version`은 0063에 남는다**. 0068도 column/default 추가와 constraint validate/
    concurrent index 단계에 `autocommit_block()`을 쓰므로, 실패 시 **version은 0067인데
    0068의 column·constraint·candidate index 일부가 남는 상태**가 가능하다. 0064와 0068은
    이 부분 상태를 감지해 forward 재실행하도록 작성됐고 integration test가 0068/0067
    재개를 고정한다.
  - `0064`는 인덱스만 바꾸고 DML 0건, `downgrade()`도 대칭이라 **완전 가역**이다.

  **선행 조사에서 constraint/data blocker는 확인되지 않았다.** 그러나 0065의 52행 key
  재작성·3,530행 UPDATE와 0066 backfill은 비가역이며, 0064/0068 autocommit은 부분 적용
  상태를 만든다. `collection_key` 재작성으로 깨지는 runtime lookup 소비자는 확인되지 않았다.

  **`0069_weather_series_catalog` 실측 분석(2026-07-31)** — 배포 target에 새로 포함됐다:
  - **파괴적 statement 0개.** DELETE·TRUNCATE·컬럼 삭제·타입 변경·WHERE 없는 UPDATE 전부 없다.
    `downgrade()`가 **완전 대칭**이라 **0064~0069 중 유일하게 완전 가역**이다.
  - 유일한 DML은 자기가 방금 만든 빈 테이블에 `INSERT … SELECT DISTINCT … ON CONFLICT DO NOTHING`
    (**7,796행**). 기존 테이블에 **행·컬럼 변경 0건**.
  - 기존 구조 게이트 중 통과값이 바뀌는 것은 **`alembic_version` 하나뿐**이다(→ `0069_weather_series_catalog`).
  - 대가는 위험이 아니라 **시간(+8~18분)과 디스크(+3.4 GB)**다. CIC 2개가 1,640만 행
    `feature_weather_values`를 색인한다(ShareUpdateExclusive만 잡아 읽기·쓰기를 막지 않는다).
  - ⚠ **새 이미지 + 0069 미적용** 조합에서 기존 공개 엔드포인트
    `GET /features/{feature_id}/weather`가 503이 아니라 **500**을 낸다(#901이 batch 쿼리로
    재배선했고 그 SQL이 `weather_metric_series`를 hard JOIN한다). 반대 방향(스키마 적용 + 구
    이미지)은 무해하다. entrypoint가 upgrade 성공 뒤에만 uvicorn을 exec하므로 정상 경로에서는
    발현하지 않지만, **alembic을 건너뛰고 API를 강제 기동하면 발현한다.**
  - `autocommit_block()` 2회 + CIC 2개 → 부분 적용 가능 지점이다. `upgrade()`는 재진입 가능하게
    작성됐고(`IF NOT EXISTS`/`ON CONFLICT DO NOTHING`/`indisvalid` 확인 후 재빌드) entrypoint의
    재시도 루프가 자동으로 돌린다. 다만 **재시도마다 16.4M행 DISTINCT 스캔(60~100초)과
    3.4 GB 인덱스 재빌드를 처음부터** 한다.

  **배포 역학 실측(2026-07-30)**:
  - **`docker/api-entrypoint.sh:216`이 `alembic upgrade head`를 재시도 루프로 직접 돌린다**
    (uvicorn 기동 **전**). 이는 부분 migration 상태에서 새 API가 serving되는 것을 막는
    **기동 gate**이지 DB migration을 원자화하지 않는다. 새 이미지로 API를 recreate하면
    entrypoint가 0064~0068을 forward 재시도하고 head에 도달한 뒤에만 서비스한다.
  - **`docker/dagster-entrypoint.sh`는 마이그레이션을 하지 않는다**(`alembic upgrade` 0 hit).
    dagster는 스키마를 소비만 하므로 API 뒤에 올린다.
  - prod는 external-infra 모드라 local `postgres` service를 띄우지 않는다.
    `scripts/docker-backup.sh`는 standalone compose의 `postgres`를 하드코딩하므로 prod
    복구 수단이 아니다. H35는 배포 전에 external DB용 백업·복원 검증 경로를 먼저 만든다.

  남은 할 일:
  1. **rollback image set 고정** — candidate build 전에 현재 API·UI·Dagster web·Dagster
     daemon 네 service의 실제 container image ID·OCI source revision과 배포
     manifest/compose의 redacted checksum을 기록한다(두 Dagster service가 같은 image ID여도
     service별 결속을 생략하지 않는다). 기존 image ID에 rollback 전용 immutable tag를 붙여
     prune 대상에서 제외하고, 현재 `alembic_version=0063`과 login/API/Dagster smoke를 같은
     manifest에 결속한다. env 비밀 원문이나 `docker compose config`의 비밀 확장 결과는
     산출물에 넣지 않는다.
  2. **candidate 이미지 build-only** — main 최신(H36 게이트 포함)으로 API/dagster/UI를
     기존 rollback tag와 다른 immutable candidate tag에 준비한다. compose 기본 tag를 덮어
     이전 pair를 잃는 build는 금지한다. 이 단계에서는 candidate service의
     `docker compose create/run/up`을 모두 금지한다. 특히 API 기본
     `docker/api-entrypoint.sh`는 serving 전에 `alembic upgrade head`를 실행하므로,
     cold fence와 verified dump보다 먼저 candidate 기본 entrypoint/CMD를 단 한 번도
     시작하지 않는다.
  3. **H36 게이트를 DB와 단절해 확인** — 커밋 라벨만 보지 말고 image layer를 offline으로
     검사하거나, DB credential/env를 주입하지 않은 `--network none --entrypoint` override로만
     candidate image 안의 `_adopted_match` 존재를 확인한다. candidate API의 기본
     entrypoint/CMD를 쓰거나 prod network에 붙여 검사하지 않는다. 검사 직후 현재 배포
     도구 또는 pinned PostgreSQL client의 read-only query로 prod
     `alembic_version=0063_pipeline_root_id`가 그대로인지 확인하고, 달라졌다면 step 4로
     진행하지 말고 비인가 migration으로 취급해 상태를 보존·조사한다. 라벨은 빌드 컨텍스트를
     증명하지 않는다.
  4. **cold writer fence** — prod ingress를 maintenance 상태로 두고 기존 app DB write
     schedule/sensor의 enablement를 기록한 뒤 모두 pause하고, pending/running run 0건을
     확인한다. 기존 API·Dagster web·Dagster daemon을 정지하고 map 소유 writer
     container/process 0건과 app 역할의 active write transaction 0건을 확인한 시점부터
     dump·migration·구조 smoke가 끝날 때까지 fence를 유지한다. dump 뒤 정상 write가 생길
     수 있는 상태에서는 복원을 복구 경로라고 부르지 않는다.
  5. **prod external DB 백업·복원 gate 실행** — 비밀을 argv/log에 싣지 않는
     `PGSERVICEFILE`/`PGPASSFILE` 기반의 pinned PostgreSQL client로 app·Dagster DB를 custom
     dump한다. SHA-256과 `pg_restore --list`만 확인하고 끝내지 않고, 격리 scratch DB에
     실제 복원해 pre-migration head·핵심 schema/row count를 대조한다. standalone
     `scripts/docker-backup.sh`를 prod에서 호출하지 않는다.
  6. **API candidate recreate** → fence 안에서 entrypoint가 0064~0068을 forward 적용한다.
     실패하면 downgrade하지 않고 `alembic_version`과 0064/0068 partial-state probe를
     기록해 같은 image/command로 재개한다.
  7. **fence 안 구조 실증(반증 가능해야 한다)**:
     - `alembic_version = 0068_integrity_last_seen`
     - 0068의 `last_seen_at` column/default/NOT NULL·FK·세 concurrent index가 모두 최종
       shape이며 invalid/candidate index와 임시 constraint가 남지 않음
     - `uq_violations_open_dedupe_key` 인덱스 존재 / `last_seen_at` 컬럼 존재
       (둘 다 지금은 **없음**이 확인돼 있어 before/after가 갈린다)
     - curation import **preview**가 오링크 3건을 여전히 미연결로 두는지
       (H36 게이트 실효 확인. 실패했다면 `resolved_feature_id`가 채워져 값이 달라진다)
  8. **post-migration 격리 bundle·daemon preflight** — candidate API를 다시 정지해
     prod app·Dagster DB writer 0건을 재확인한 뒤, 0068 상태의 app·Dagster DB를 H30B용
     immutable custom dump bundle로 만든다. SHA-256·`pg_restore --list`와
     pre-materialize Feature **1,020**, head·schema/content identity를 기록한다. 실제
     concierge `changes` export도 cursor 없이 시작해 끝까지 한 번 수집하고, ordered page
     envelope마다 request cursor·`next_cursor`·`has_more`와 item 원문(operation 포함)을
     credential/header 없이 canonical JSON artifact로 보존한다. cursor chain의 전진·종료와
     전체 **1,477행**을 확인하고 payload SHA-256을 DB dump·candidate image manifest와
     하나로 결속한다. producer에는 durable snapshot/version identity가 없으므로 count만
     기록한 live 재조회는 같은 입력으로 인정하지 않는다. step 5에서 쓴 같은 scratch DB pair를
     reset·복원해 DB identity를 대조하고, candidate Dagster daemon을 prod credential·network
     없이 이 scratch pair에만 연결해 모든 app DB write schedule/sensor pause·pending/running
     run 0 상태에서 실제 기동한다. image ID·OCI revision·heartbeat/health 검증 뒤 정지하고,
     preflight가 scratch metadata를 바꿨다면 같은 pair를 signed DB bundle로 다시 reset해
     H30B 인수 identity를 복구한다. 별도 clone은 만들지 않는다.
  9. **prod 비-daemon candidate recreate·health** — API·UI·Dagster web을 각 service에
     고정한 immutable candidate image ID로 recreate한다. 세 service의 실제 container
     image ID·OCI revision과 login POST·API·Dagster web health를 candidate manifest에
     대조한다. prod Dagster daemon과 app DB write schedule/sensor는 계속 정지·pause한다.
     old container를 단순 start하거나 UI만 이전 image로 남긴 상태에서는 다음 단계로 가지
     않는다.
  10. **cutover 전 실패 복구 분기** — forward 재개가 불가능해 verified dump를 복원할 때는
     fence를 유지한 채 candidate를 모두 내린다. DB를 0063 dump로 복원하고 step 1의 exact
     rollback service image ID·manifest/compose checksum으로 API·UI·Dagster web을
     recreate한다. 이전 set의 `alembic_version=0063`, 세 실행 service identity와
     login/API/Dagster web smoke가 green임을 확인해 rollback을 확정한 뒤 exact 이전 daemon을
     시작하고 step 4에 기록한 schedule/sensor enablement를 복원한다. daemon identity·health가
     green인 뒤에만 fence를 해제한다. 새 candidate entrypoint를 복원 DB에 다시 실행하는
     절차는 rollback이 아니다.
  11. **forward-only cutover·prod 정상화·H30B handoff** — 구조·세 prod service health와
      step 8의 isolated daemon runnable gate가 모두 green이면 forward-only cutover를
      확정한다. 이 시점부터 옛 dump 복원을 금지하고 실패를 forward 수정으로만 처리한다.
      prod candidate daemon을 writer pause 상태로 시작해 실제 image ID·OCI revision·health를
      확인한 뒤 step 4에 기록한 schedule/sensor enablement와 API·Dagster/UI ingress를
      복원한다. H35에서는 concierge materialize를 실행하지 않는다. prod를 정상 상태로
      돌려놓고 step 8의 signed post-migration DB·concierge export bundle과 clean scratch
      identity만 H30B에 넘긴다. 실제 1,020→1,477 회복과 authenticated `/admin/issues`
      검증은 export artifact를 network-free로 재생하고 격리 DB만 사용하는 다음 단일 소유
      task `T-VN-H30B`가 수행한다.

  > **⚠ 비가역 지점** — 사람 승인이 필요하다.
  > - `0065`의 `collection_key` 52행 재작성과 `source_updated_at` 3,530행 UPDATE,
  >   `0066`의 `external_component_id` backfill은 **downgrade로 복구되지 않는다**.
  >   검증된 external DB dump와 0063-compatible rollback image set·배포 manifest를 함께
  >   보존한 bundle이 유일한 복구 경로다.
  > - `0064`와 `0068`의 `autocommit_block()` 때문에 **부분 적용 상태가 가능하다**.
  >   entrypoint가 실패 시 재시도하므로 forward recovery를 우선하고 꼭 필요한 경우가
  >   아니면 Alembic downgrade하지 않는다. 계속 실패하면 API가 기동하지 않아 장애가
  >   조용히 숨지는 않지만, DB가 자동으로 원상복구되는 것도 아니다.
  > - 이미지 교체는 다운타임을 만든다.
  **머지 = 배포가 아니라는 점을 문서에도 반영한다** — H30A 완료 기록이 prod 상태를
  주장하는 것으로 읽히지 않게. (H36이 이 task보다 **먼저**다.)

  <details><summary>원래 정의 (완료 전)</summary>

  H25B가 정지오코딩으로 확인한 오링크가 **DB에는 그대로 남아 있다**(`status=included`,
  archived 아님). `/admin/curations` 계열 화면과 공개 projection이 남이섬 자리에 서울 중구
  사무소를, 청남대 자리에 전남 영암 시설을 노출하고 있을 수 있다.
  대상: `kt100-2023-2024-025`, `kt100-2025-2026-024`(남이섬), `kt100-2025-2026-036`(청남대).

  **전수 확인 결과 이 축으로 잡히는 오링크는 3건이다** (`scripts/h33_mislink_detect.py`, 재현 가능).
  CSV 링크 222행 시도 불일치 **0건**, DB `curation_items` 링크 전수 **3건**(남이섬 ×2, 청남대).
  근거 산출물: [`reports/h33-mislink-2026-07-29.json`](reports/h33-mislink-2026-07-29.json)
  (`db_linked_rows` 3269 / `db_region_codeable` 112 / `db_sido_mismatch` 3).
  CSV 쪽이 0건인 것은 **그 3건을 역반영에서 뺐기 때문**이지, 축이 안 도는 게 아니다.

  > **정정** — H25B 리포트 초안은 호미곶·오륙도를 들어 "오탐이 계통적이니 유형 전수를
  > 대상으로 하라"고 적었으나 **철회했다**. 그 이름의 서울 소재 feature가 *존재할 뿐*
  > curation에 링크돼 있지 않다. *실제 오링크*(고칠 데이터, 3건)와 *매칭 함정*(방어할 대상,
  > 다수)을 뭉갠 것이다.

  **스키마 변경은 권고하지 않는다** — 탐지 축인 `metadata.region`이 DB 링크 3,269건 중
  **112건(3%)**에만 있어, 그걸로 만든 제약·뷰는 97%를 검사하지 못하면서 검사한 것처럼 보인다.
  CHECK는 교차 테이블이라 애초에 불가하고, 실제 결함도 3건이다. 대신 H30A의
  `ops.data_integrity_violations` ledger에 finding으로 방출하면 migration 없이 dedupe와
  `/admin/issues` 노출을 얻는다.

  할 일: 3건 unlink + 공개 projection 노출 여부 실증 + ledger 방출.
  **커버리지 한계를 함께 기록한다** — region 없는 링크는 이 축으로 판정되지 않는다.

  </details>

  **남는 커버리지 한계**(고친 3건이 전부라는 뜻이 아니다): `region`이 있는 링크만 본다 —
  해제 후 기준 **3,266건 중 109건(3.3%)**. 즉 **96.7%인 3,157행은 이 축으로 아예 검사되지
  않는다.** 시도는 맞고 시군구만 다른 오링크도 안 잡히고, `sido_code`가 NULL인 2건은
  건너뛴다. "0건"은 부재의 증명이 아니다.

  > 초안은 여기에 "존재하지 않는 feature를 가리키는 링크는 세지 않는다"도 한계로 적었으나
  > **뺐다** — `curation_items_feature_id_fkey`가 `ON DELETE SET NULL`이라 그런 행은 애초에
  > 생길 수 없고 prod 실측도 0건이다(리뷰 지적). 존재할 수 없는 위험을 한계 목록에 얹으면
  > 불확실성의 모양이 실제와 달라진다.

- [x] T-VN-H31 — **등대 공급원 부재 — provider 신설 취소로 종결** (2026-08-03)

  > **`address_hint` 계약 변경 (2026-07-31, #909/#910)**
  > #907이 `address_hint` 매칭을 **공백 토큰 AND**로 고치고(직렬화 jsonb 통짜 substring이라
  > 다중 토큰이 매칭 안 되던 역전을 수정) 등대 105행을 출처 확인해 채웠다.
  > **#910이 그 자동 링크를 fail-close로 막았다** — `address_hint` 단독으로는 자동 채택하지
  > 않고, 구조화 주소 matcher와 행별 provenance(`0072`)를 요구한다.
  >
  > 즉 "주소가 있으면 링크를 연다"는 내 전제가 **근거로 불충분하다**는 판정이다.
  > 채워 넣은 105행의 주소 자체는 버려지지 않고 sidecar provenance
  > (`lighthouse-stamp-tour.provenance.json`)로 옮겨 **행별 근거**를 갖는다.
  >
  > 등대 feature 공급원 부재는 **그대로 남는다** — CSV에 `feature_id`가 2건뿐이라
  > 새 계약으로 재import해도 105 중 2만 복원된다.

  공식 curation 미연결 261건 중 **103건이 등대**이며 105개 중 2개만 링크됐다. ADR-034 9단계
  provider 순서에 등대를 공급하는 provider가 없다 — curation 매칭으로는 해소되지 않는다.

  **범위 확인(2026-07-30)**: 등대 **스탬프투어 자체는 이미 들어 있다** —
  `resources/curations/lighthouse-stamp-tour.csv`에 6시즌 105행
  (아름다운 15 / 역사 16 / 재미있는 18 / 풍요로운 17 / 힐링 16 / 해돋이 23).
  빠진 것은 스탬프투어가 아니라 **등대 feature 공급원**이다. 이름 매칭으로는 103건 중 89건이
  상호가 `등대`인 **가게**에 붙는데, 그게 실제 등대 데이터가 DB에 없다는 증거다.

  **결정(사용자 지시, 2026-07-30) — 등대는 API가 없다. 저장소 CSV가 정본이고 불변값으로 읽는다.**
  갱신은 파이프라인 밖에서 **사람이 CSV를 직접 편집**한다. 이건 기존 provider 패턴과 다르므로
  아래를 지켜야 한다.

  - **새 소스 종류다.** 기존 `src/kortravelmap/providers/*`는 전부 외부 `python-*-api`
    레코드를 받는 **순수 변환 함수**이고(ADR-006), 저장소 상주 CSV를 feature 공급원으로 쓰는
    선례가 없다 — `resources/`에는 `curations/`뿐이다. **API가 존재하지 않기 때문에** 두는
    의도적 예외이며, ADR로 남긴다(다음 후보 **ADR-080**).
  - **변환은 순수 함수로.** `providers/`에는 `Mapping` → `FeatureBundle` 변환만 두고
    **파일 읽기는 호출자(cli/dagster)가** 한다 — 기존 provider 모듈과 같은 모양을 유지하고
    의존 방향(`… → geocoding → providers → client → cli`)을 지킨다.
  - **feature_id가 재적재마다 흔들리면 안 된다.** 사람이 좌표를 보정하는 편집이 예상되므로
    `make_feature_id`의 자연키를 **좌표가 아닌 안정 식별자**(항로표지번호 등 CSV의 불변 열)로
    잡는다. 좌표를 키에 넣으면 편집 한 번에 링크가 전부 끊긴다 —
    `T-VN-H33`/`T-VN-H36`에서 겪은 문제와 같은 계열이다.
  - CSV의 `provider` 열은 이미 `korea-navigation-aids-agency`로 적혀 있다. 그 이름을 쓸지,
    정적 소스임을 드러내는 이름을 쓸지 확정한다.
  - **CSV 자체의 무결성 게이트**를 둔다 — `resources/curations/manifest.json`이 sha256을
    갖는 것처럼, 손편집이 조용히 깨지지 않게 행 수·필수 열·좌표 범위를 검사한다.
    (H25B에서 manifest sha를 손으로 유지하다 게이트가 깨진 전례가 있다.)
  - 링크는 **자동으로 붙이지 않는다** — `T-VN-H36`이 이름 단독 자동링크를 금지했다.
    등대 feature가 적재되면 CSV `feature_id`를 채우는 것은 별도 판정 절차다.

  ~~할 일: 등대 원천 데이터 확보·CSV 스키마 확정 → 변환 함수 + 적재 경로 → 무결성 게이트 →
  ADR-080 → 링크 판정(별도).~~

  ## 판정 — **provider 신설은 취소됐다 (사용자 지시)**

  > **"등대 etl provider 은 취소, csv 기반 큐레이티드만 남김. 큐레이티드의 미정합 자료는
  > 관광목적의 테마 장소이므로 등대가 아니더라도 문제가 없음. 다른 소스에서 위치 찾아서
  > 반영할 것."**

  이 지시로 위 "할 일"의 핵심(변환 함수 + 적재 경로 = provider 신설)과 **ADR-080이 함께
  취소**된다. 저장소 상주 CSV를 feature 공급원으로 쓰는 새 소스 종류를 만들지 않는다.

  **"다른 소스에서 위치 찾아서 반영"은 이행됐다** — #907이 105행 `address_hint`를 전량
  채웠다(현재 CSV 실측: 105행 중 address_hint 105, feature_id 2).

  그런데 **#910이 그 주소로 자동 링크하는 것을 fail-close로 막았다.** 링크하려면 CSV에
  `feature_id`가 명시돼 있어야 하는데, 그러려면 등대 feature가 DB에 있어야 하고, 그것을
  공급할 provider가 방금 취소된 것이다. 즉 **103건은 구조적으로 미연결로 남는다.**

  그리고 그것이 **문제가 아니라는 것이 위 지시의 요지**다 — 스탬프투어는 관광 테마이지
  항로표지 대장이 아니다.

  실측 재확인(2026-08-03, prod): 이름에 `등대`가 든 active feature는 상당수가
  `02010100`(음식점) 카테고리의 내륙 가게다(대구 동구·시흥·군포 등). 이름 매칭으로
  링크하면 그런 가게에 붙는다 — `T-VN-H36`이 이름 단독 자동링크를 금지한 이유와 같다.

  **남는 것**: 없음. 등대 105행은 CSV 큐레이션으로 존재하고 주소를 갖는다. 링크 2건은
  유지되고 103건은 미연결로 남되 공개 표면에는 큐레이션 항목으로 정상 노출된다.
  (미연결 자체를 finding으로 세는 축은 `T-VN-H25A`/`H34` 소유이며 여기서 다루지 않는다.)

### T-VN-H22 — 0065 curation owner quarantine 재분류

migration 0065가 원 projection durable link 없는 canonical-only item을 보존한 quarantine은
read/decision/write/UI를 한 PR에 몰지 않는다.

#### 선행 실측 (2026-08-03) — **격리 대상은 0건이고, 구조상 0건이다**

착수 전 규모를 재 보니 **격리될 item이 하나도 없다**. 계획을 세울 때 전제한
"canonical-only item이 격리돼 있다"는 상태가 이 DB에는 존재하지 않는다.

- 라이브 prod(`krtour_map`, 읽기 전용) — `curation_items` 3,530건이 **2×2의 대각선만**
  채운다: legacy-marker collection 52개는 `curated_features` 투영본 3,044건만 담고,
  CSV collection은 네이티브 486건(`korean-tourism-100`·`arboretum`·`lighthouse`·
  `heritage`)만 담는다. 격리는 **비대각 칸**(legacy collection 안의 네이티브 item)을
  요구하는데 그 칸이 비어 있다 → 0건. dangling collection 참조도 0.
- 격리 restore clone에 `0065`를 **실제로 적용**해도 quarantine collection 0개 / item 0건.
- `legacy:quarantine`·`migration_quarantine` marker를 쓰는 코드는 `0065` **하나뿐**이다
  (런타임·다른 migration·admin UI 어디에도 생성 경로가 없음). `0065`는 1회성이므로
  **배포 후에도 영구 0건**이다.

  주의: 처음 낸 "legacy 밖 item 0건"은 3값 논리 버그였다 —
  `NOT (metadata->>'migrated_from' = '…' OR key LIKE 'legacy:%')`에서 키가 없는
  collection은 `NULL OR false = NULL` → `NOT NULL = NULL`로 걸러진다. 격리 건수 자체는
  `0065`와 같은 **긍정형** 술어를 써서 영향이 없었다.

**따라서 H22A/B/C는 대상이 없다.** 셋 다 "격리된 item을 운영자가 재분류한다"가 유일한
목적인데 재분류할 것이 영구히 없다. 세 과제를 지금 구현하면 소비자 없는 계약·UI가 남는다.
조사가 함께 지적한 "배포 직후 `[0065 격리]` collection이 admin UI에 설명 없이 등장한다"는
경고도 collection이 생성되지 않으므로 함께 소멸한다.

- ~~**판정 보류 — 사용자 결정 대기.**~~ → **해제(2026-08-04)**: 사용자 지시 "h22까지
  순차적으로 진행", "h22는 하나의 pr로". 대상이 현재 0건이어도 도구를 갖춘다 — preflight
  게이트(`quarantine_candidates_before`)가 0이 아니게 되는 순간 이 UI가 소비처다.
  세 항목 모두 단일 PR로 구현 완료(아래 각 항목 완료 기록).
- **대신 배포 게이트가 이 전제를 스스로 재게 했다**(#929): H35 **preflight**가
  `quarantine_candidates_before`를 0으로 검사한다. 경계 뒤(`migrate`/`verify`)에는
  `quarantine_collections`·`quarantine_items`를 **관측치로만** 남기고 거부하지 않는다.
  이 값이 0이 아니면 H22를 착수해야 한다는 신호다.

  게이트를 preflight에 둔 이유는 적대 리뷰가 내 첫 설계를 반증했기 때문이다. 나는
  "격리가 생기면 어차피 `public_items_verify`가 깨진다"고 적었는데 **틀렸다** — 격리
  조건(`legacy_projection_id IS NULL`)은 `status`·`source_present`·accepted link 어느 것도
  요구하지 않아 공개 집합과 독립이고, 실제 픽스처에서 격리 1건이 생겨도 공개 수는 3,043
  그대로였다. 즉 경계 뒤 hard check는 **기존 게이트가 통과시키던 상태를 새로 거부**하는
  것이고, 그 지점에는 출구가 없다(csv5는 accepted prior receipt 요구 / migrate 재실행은
  `schema_before=0063` 요구인데 DB는 이미 `0078` / `0065` downgrade는 durable state에
  fail-close → PITR 없는 prod에서 dump 복원만 남는다). `#925`에서 index signature로 겪은
  것과 같은 계열의 함정을 내가 다시 만든 것이었다.

계획상 모호함 3건은 구현에서 이렇게 확정했다:

- **"후보 theme/source"** = 추천이 아니라 **병렬 표시**로 확정. 격리 collection이 0065 때
  복사 보관한 theme/source와 원본 collection의 **현재** theme/source를 나란히 내려준다
  ("자동 target 추정 금지"와 정합). 추천으로 읽는 해석은 폐기.
- 격리 근거는 collection marker 정본 술어(`created_by='migration:0065'` AND
  `metadata @> migration_quarantine`) + `original_collection_id` 역참조로 재구성. 이동된
  item과 수동 추가 item의 구분 불가는 그대로 수용(전체가 재분류 대상이므로 실해 없음).
- 페이지네이션은 ADR-048 `meta.page.next_cursor` 봉투. `/admin/link-audit` shape는 위반
  잔재라 따르지 않았다.

- [x] T-VN-H22A — **quarantine read model·conflict preview** *(2026-08-04, H22 단일 PR)*

  `GET /v1/admin/curations/quarantine`(+`/{id}/items`) — marker 정본 술어 기반 목록 +
  원본/격리 theme·source 병렬 + item별 conflict preview. 충돌 판정은 이동이
  `collection_id`만 바꾸는 UPDATE라는 사실에서 도출 — 위반 가능 제약은 정확히 2개:
  (A) `uq_curation_items_component_identity`(비-partial — archived 상대도 충돌),
  (B) `uq_curation_items_active_source_feature`(양쪽 다 partial 술어 충족 시만). 순수
  SELECT, keyset cursor(`{"v":1,...}` 정확 키 검사), 자동 target 추정 없음.

- [x] T-VN-H22B — **원자적 reclassification command** *(2026-08-04, 같은 PR)*

  `POST .../quarantine/{id}/reclassify` — `move`(target 지정 또는 원본, item subset 지원) /
  `confirm_standalone`(marker 2키만 제거, 나머지 metadata 보존). lock 순서: 전역 advisory →
  collection들 id 오름차순 FOR UPDATE → **lock 후 marker 재검증**(TOCTOU) → items 오름차순
  FOR UPDATE → (A)/(B) 재검사 → 충돌 시 409 fail-close(충돌 목록 detail, 무변경) →
  UPDATE/DELETE(빈 격리 정리). `admin.curation-quarantine.reclassify`를 #906 정적
  inventory(registry 68→69)와 route_policy에 등록 — 사전 심어진 quarantine barrier 충족.
  actor 감사는 `updated_by` + domain ledger.

- [x] T-VN-H22C — **Admin UI·실데이터 파괴적 수용** *(2026-08-04, 같은 PR)*

  H22A/B 계약만 소비하는 `curation-quarantine-panel.tsx`(49B controller/view 관용, 기존
  client 파일 수정은 2줄) — 빈 상태 1급(실데이터 0건이 정상), 격리/원본 병렬 표시,
  conflict 배지, item subset 이동 + AlertDialog, 409 충돌 목록 렌더, 별도 확정. mocked
  spec 6건(BFF 강제·`Idempotency-Key` 헤더 단언, manifest 276→284 재고정 — main의 기존
  drift 278 + 기존 실패 7건은 tvn41 잔여로 별도) + live spec 저술
  (`curation-quarantine-write.live.spec.ts`, 격리 clone 전용·env opt-in — 실데이터
  quarantine이 0건이라 러너가 합성 필요).

  **파괴적 수용은 격리 스택(로컬 postgis + 실 API 서버, HTTP 전 경로)에서 9흐름 실증**:
  목록 병렬·preview 진리표·충돌 포함 move 409 fail-close(무변경 검증)·부분 move·terminal
  replay(`Idempotency-Replayed: true`)·fingerprint 409·전량 move 후 빈 격리 DELETE·
  confirm_standalone(marker 2키만 제거, 기타 metadata 보존)·확정 후 재확정 404.
  참고: 사고 시점 dump(`krtour_map_0072_*.dump`, 복원 검증됨)는 향후 실데이터 픽스처로
  쓸 수 있으나 quarantine 행이 없어 이번 검증은 합성 시드를 썼다.

- [x] T-VN-32C — **PinVi alias-map cutover·legacy write fence·응답 값 전환** (2026-08-05 완료)

  PinVi consumer를 UUID+alias contract로 전환하고 양 저장소 checksum을 맞춘다. legacy write를
  fence하되 legacy ID 제거는 T-VN-39 soak 뒤로 남긴다.

  **전반부 착지(본 branch + PinVi 쌍 branch `feat/tvn32c-uuid-alias`)**:
  ① 이관 표면 — ADR-068 결정 4의 "DB-to-DB 이관"을 service read 2종으로 판단
  (`GET /v1/service/feature-alias-maps`(keyset 페이지)+`/checksum`(merkle
  root) — PinVi 소비는 HTTP-only·cache-target snapshot/merkle 선례,
  `require_service_token`·route_policy SERVICE, read-only라 registry 미등록).
  ② `feature-alias-map-v1` checksum 계약(`core/feature_alias_map.py` 순수:
  NFC-거부 alias·canonical uuid·닫힌 kind, 길이 prefix + domain separation
  leaf(`KTMFAMLEAF\0`)·byte-order 정렬·odd-promotion merkle(`KTMFAMNODE\0`/
  `KTMFAMEMPTY\0`), 파생 검증 분리) + 양 저장소 공용 golden
  `contracts/feature-alias-map-v1-golden.json` — PinVi 독립 구현
  (`app/core/feature_alias_contract.py` — namespace를 basis 문자열에서 재파생)
  이 vendored 사본으로 재계산 대조. ③ legacy write fence — alembic
  `0082_legacy_write_fence`: alias map 불변(UPDATE 전면 거부·직접 DELETE
  거부·feature purge CASCADE만 허용 — removal manifest "alias 유지" fence) +
  identity 불변(feature_id/feature_uuid UPDATE 거부) DB 트리거 fail-close,
  0079 트리거 2종은 재평가 후 **유지**(fill은 0080 CHECK가 요구하는 유일값만
  쓸 수 있는 강제 메커니즘의 일부, AFTER alias는 INV-068-01 원자 보장 —
  0079/0081 docstring), `COLLATE "C"` keyset index(+모델 metadata 정합).
  f_* 신규 발급 fence는 비파생 generator 채택과 불가분이라 **의도적으로
  checksum 게이트 뒤 잔여로 순서 고정**(발급 전환은 신규 행 응답에 UUID 값을
  조기 누출 — rollout "checksum 일치 후 응답 전환" 위반 + upsert idempotency
  재결선 필요). ④ PinVi 이관 준비 — UUID shadow 컬럼 migration
  (`20260804_0049`: trip_day_pois/curated_plan_pois.feature_uuid,
  feature_suggestions.target_feature_uuid) + alias-map client
  (`clients/kor_travel_map_alias_map.py` — keyset 전진·계약 위반 fail-close) +
  검증된 이관 실행기(`services/feature_uuid_cutover.py`,
  `pinvi-feature-uuid-cutover` CLI: pull→독립 root/count·파생 검증→매칭 3열
  rewrite·미매칭은 NULL 유지+보고, dry-run 지원). ⑤ artifact — OpenAPI
  admin/service 재생성(user sha 무변경)·`openapi-diff-v1.json` baseline
  재고정+revisions(이관 표면은 목표 diff 항목 아님 — 존치·폐기는 39 소관)·
  unit sha 상수 재고정.

  **쌍 PR 착지(2026-08-04)**: Map #940 merge `e12494bd` + PinVi #428 merge
  `3ff54b8b`(squash). 유예분 완료 — alias golden 핀 `_UPSTREAM_MAP_COMMIT` =
  merge SHA + contract-pin-consistency byte-diff 단계, service snapshot 재추출
  (`144b4335…` — cache-target operation diff 무변경 실측 → codex n150 paired
  live proof 유효), `_ARTIFACT_COMMIT`/`_FUNCTIONAL_OWNER_COMMIT`/config/
  `.env.example` 회전. ⓪ 사전 스캔 완료 — prod 467,697행 중 canonical UUID
  형태 legacy `feature_id` **0건**(L7 shadowing 클리어, TCP read-only 실측).
  배포 결선 예고는 docker-manager#128(EXPECTED_HEAD=`0082_legacy_write_fence`
  + PinVi 계약 env 2종 — sync enable 시 fail-close 주의, Map 먼저 순서 제약).

  **checksum 게이트 통과(2026-08-05)**: PinVi 배포 + cutover dry→real —
  양 저장소 root 일치(`8bd9534a…`, 731,600) + trip_day_pois 26행 shadow 채움.

  **PR-1 + 쌍 PR + 0083 배포 완주(2026-08-05)**: Map #950 merge `2a8642bd`
  (0083 — 파생 CHECK 해제·선언적 사본 일치 CASCADE FK+UNIQUE·비파생 UUIDv7
  generator app `make_feature_uuid`/SQL `feature.uuid_generate_v7()` 동일
  레이아웃·verify 이원화 fail-close·golden nonderived_v1 개정, 적대 리뷰
  2인 GO) + PinVi #430 merge `6325d814`(파생 등식 폐기 수용·cutover 리터럴
  자기-정본화 opt-in·golden 재vendor `dc0a6595…`+merge SHA 핀·staleness
  golden 감시). prod 배포 게이트 순서 완주(PinVi 선배포 → 사전 점검 0/0 →
  Map api 0083 적용 → dagster·daemon), 사후 검증 정상(`derivation_enforced:
  false`, 731,733) — journal 2026-08-05 (7)·dm#128.

  **PR-2 머지(2026-08-05, #952 `8c5bdcf8`)**: 응답 `feature_id` 값 UUID 전환
  코드 완결 — 전 read 표면 치환(cursor legacy 축·echo 예외 보존, ADR-083
  §5-6), write/scope 경계 해석 전수(W1-W8·S1-S13 + bulk 해석기), admin UUID
  fast-path, curated snapshot 빌더 UUID화, h35 CLI pre-uuid 스키마 변형
  (역사 표면 보존). 적대 리뷰 2인 GO(trip_card echo 등식·scope 해석
  트랜잭션 배치 등 H 2건 반영), CI 8/8.

  **배포 완료(2026-08-05, dm#128)**: ①H30B 게이트 기완료 충족 ②`8c5bdcf8`
  4-이미지 배포(사후 검증: 상세 UUID·batch echo·trip_card 등식 정상)
  ③curated snapshot 활성 500 전량 재물질화(멱등 확인, 비활성 334 동결 보존).

  **잔여**: ④ live e2e fixture 재생성(새 표면 기준, n150 per-file 저부하) →
  ⑤ PinVi user 스냅샷 재고정 PR + 유예 동봉(PinVi CLI
  `--accept-uuid-literals`+runner 출력, `derivation_enforced` cutover 사전
  검사 배선) → ⑥ dagster entrypoint EXPECTED_HEAD 기계 인터록(NEW-5, dm base
  compose 기본값 갱신 동타이밍). 관측: 32B 기간 저장 UUID 표기 scope 레코드
  잔존(재실행 조용한 no-op — 리뷰 L4)·quarantine 재-link 프론트 대조(F6).
  legacy ID·FK 체인 물리 제거는 T-VN-39 removal manifest.
  **운영 점검(상시)**: 0079/0081 트리거 보장은 trigger-respecting 세션
  한정이다 — `session_replication_role=replica`(superuser)는 우회 가능하므로
  `count_features_missing_identity` 정기 관측(0,0 확인)이 alias 결측 방어선
  (32C 리뷰 M4).


### T-VN-31 — vNext target freeze

ADR은 존재하지만 목표 DDL/OpenAPI diff/실행 제약 artifact는 없다. 구현과 freeze를 분리한다.

> **미정 표기 원칙(2026-08-04 freeze)**: ADR·보고서·task 정의가 침묵하는 세부는 artifact에서
> 발명하지 않고 SQL `-- 미정(T-VN-XX 구현 소관)` / JSON `"decision":
> "deferred-to-implementation"`으로 남긴다. freeze의 정직성이 완성도보다 우선한다.
> 적대 리뷰 2건(정합성·실행성)을 같은 브랜치에서 반영했다 — 발명분 회수(state 조합
> CHECK·subtype full GiST·summary bucket identity·price known_at), 정본 명시분 반영
> (user status 3축 diff·weather valid_during range·state transition 흡수처·ADR-073
> 배타 열거 removed), 실행성 보강(invariant phase 태그·파서 fail-open 봉합·diff
> counts 2차 방어·summary surrogate PK).

- [x] T-VN-31A — **목표 DDL·데이터 불변식 freeze** (2026-08-04 완료)

  schema/table/column/type/FK/CHECK/index/view/trigger와 backfill 전후 불변식을 실행 가능한 SQL
  artifact로 고정한다. migration 번호와 구현 SQL은 아직 넣지 않는다.

  완료 기록: `contracts/vnext/target-schema-v1.sql`(빈 PostGIS DB 자기완결 적용, ADR-075 규율
  주석) + `contracts/vnext/target-invariants-v1.sql`(H35 preflight 6종 패턴 + ADR별 불변식,
  `expect: 0` assertion 43개 — machine-readable phase 태그 pre-backfill/post-backfill/both)
  + `contracts/vnext/target-schema-fingerprints-v1.json`
  (H35 7 카테고리 catalog canonical SHA-256, PG16/PostGIS 3.5).

- [x] T-VN-31B — **목표 OpenAPI·consumer diff freeze** (2026-08-04 완료)

  admin/user/PinVi surface별 추가·삭제·rename·enum/status/error 변화를 machine-readable diff로
  고정하고 consumer-first 배포 순서와 호환을 버릴 시점을 명시한다.

  완료 기록: `contracts/vnext/openapi-diff-v1.json`(surface×change, 현행 3 spec baseline
  sha256 핀, 항목별 basis 필수, Wave 0/1 기착지분 제외) +
  `contracts/vnext/consumer-rollout-v1.json`(task별 consumer-first 순서·write-fence·호환
  폐기 시점·PinVi 3 snapshot 재-vendor 여부(ADR-079 규율)·T-VN-39 removal manifest).

- [x] T-VN-31C — **제약 test·복구 preflight freeze** (2026-08-04 완료)

  목표 DDL/OpenAPI를 위반하는 fixture와 shadow checksum, forward recovery, write-fence preflight를
  executable contract로 만든다. 31A/B artifact drift를 CI에서 fail-close한다.

  완료 기록: `contracts/vnext/violation-fixtures-v1.sql` + `expected-rejections-v1.json`
  (8 case — alias 중복·provider 3-tuple 중복·geometry invalid/empty·override active 중복·
  notice is_current 중복·weather NULLS NOT DISTINCT 중복·bitemporal 역전, 기대
  SQLSTATE·제약명. 3축 불가능 조합 case는 CHECK 정의 자체가 미정(T-VN-34A)이라 구현
  PR로 이월) + `contracts/vnext/recovery-preflight-v1.json`(H35 runbook §6 writer
  registry·fence 증거 key·ADR-075 결정 3 forward recovery/PITR 판정·Merkle v1 정의) +
  `tests/integration/test_vnext_target_freeze.py`(빈 PostGIS 적용→불변식 0→fixture 거부→
  fingerprint 재계산 일치) + `tests/unit/test_vnext_contract_artifacts.py`(artifact bytes
  sha256 고정 + spec baseline·operation 실존 검증 + JSON shape — 매 PR unit job fail-close).

- [x] T-VN-32A — **UUID schema·deterministic backfill** (2026-08-04 완료)

  UUID identity와 legacy alias table을 추가하고 같은 snapshot에서 deterministic backfill·UNIQUE/FK
  불변식을 고정한다. 기존 문자열 ID는 아직 제거하지 않는다.

  완료 기록: alembic `0080_feature_uuid_shadow` — `feature.features.feature_uuid`
  (backfill 후 NOT NULL + `uq_features_feature_uuid`) + `feature.feature_aliases`
  (alias PK · legacy `feature_id` text FK · `feature_uuid` · `alias_kind`, freeze
  §4 대응 제약명 정합) + INSERT 트리거 2종(BEFORE fill / AFTER legacy alias 원자
  생성 — repo 2곳 + 테스트 직접 seed 37개 파일 등 전 write 경로를 경로별 SQL 수정
  없이 보장). **freeze 미정 3건 결정**(0079 docstring 근거): ① 생성기 =
  `uuid5(uuid5(NAMESPACE_URL, 'kor-travel-map:feature-uuid:v1'), legacy_id)` —
  DB server default 없음(정본 신규 행 generator·UUIDv7 여부는 32B 소관), ②
  alias_kind = 닫힌 CHECK `('legacy_feature_id')`, ③ alias FK ON DELETE =
  CASCADE(alias/uuid는 파생값·재계산 가능). Python 정본
  `core/ids.feature_uuid_from_legacy` + pgcrypto SHA-1 SQL mirror
  `feature.feature_uuid_from_legacy`(고정 벡터 상호 대조).
  `tests/integration/test_feature_uuid_shadow_migration.py` 8건 — backfill
  완전성·UNIQUE/NOT NULL·alias 1:1·freeze INV-068-01~04 그대로 실행(05는
  provider_dataset_id가 33A 소관이라 제외 명시)·별도 DB 재실행 결정론·downgrade
  무손실 왕복·신규 upsert 원자 생성·명시 uuid 존중 + unit 고정 벡터 2개. 읽기
  경로·기존 문자열 ID 무변경(32A 계약).

- [x] T-VN-32B — **Map consumer-first dual read/write** (2026-08-04 완료)

  repository/API/notice lineage를 UUID 정본으로 읽고 alias를 경계에서만 해석한다. 신규 write는 UUID와
  alias를 원자 생성하고 legacy-only 신규 행을 차단한다.

  완료 기록: ① 경계 alias 해석 단일 메커니즘 — `infra/feature_identity.py`
  `resolve_feature_identity(session, ref)`가 legacy `f_*` alias·canonical UUID
  양쪽을 정본 키 쌍 `FeatureIdentity(feature_id, feature_uuid)`로 해석
  (형식 오류 422 · 미해석 404, UUID-정본 우선/alias fallback 결정적 순서) +
  `kortravelmap.api.feature_ref.resolve_feature_ref_or_error` 공용 경계 헬퍼.
  **removal-슬레이트 표면을 제외한 전 feature `{feature_id}` 경로에 적용** —
  user detail·sources·observations history·weather·price·contained-features·
  **weather/forecast(적대 리뷰 F2로 뒤늦게 편입 — 종전엔 이 경로만 해석을
  건너뛰어 형식 오류에도 200+빈 timeline)** / admin detail·revision·weather·
  price·PATCH·DELETE·deactivate. **의도적 제외 3표면**(적대 리뷰 F3 명시):
  `GET /v1/curations/features/{id}`·`GET /v1/public/{beaches,festivals}/{id}` —
  freeze openapi-diff에서 ADR-073 배타 열거로 removed 슬레이트(T-VN-40B/39
  소관)라 변환하지 않으며, 형식 오류가 422가 아닌 404로 떨어지는 비일관을
  포함한 채 제거 시점까지 동결. 내부 전달·조회는 해석된 정본 키로만
  (ADR-068 결정 3). operator lineage의 별도 존재 확인 쿼리
  (`_operator_feature_or_404`)는 해석 성공이 행 존재를 함의하므로 제거.
  ② dual read — alembic `0081_uuid_dual_read`가 `public_features` view에
  `feature_uuid`를 재고정(SELECT * 컬럼 목록, 공개 술어 무변경), repo 단건
  (`_FEATURE_ROW_COLUMNS_SQL`)·bbox/in-bounds·search·nearby(coord/by-target)·
  contained·service batch(`base.feature_uuid`)·admin 목록/상세가
  `feature_uuid`를 select 목록에만 추가(join/술어 무변경 — EXPLAIN 회귀 없음).
  응답 additive 노출: user detail/search/in-bounds/nearby item, service
  `POST /features/batch` item(found/retired/suppressed/unchanged) ·
  `POST /features/weather/batch` item(거대 조회 SQL 무변경 —
  `get_feature_uuid_map` 병행 해석), admin 목록/상세. **응답 `feature_id` 값은
  legacy 유지** — 값 전환은 32C(rollout "checksum 일치 후 Map 응답 UUID 전환",
  consumer-first cutover 규율). ③ notice lineage —
  `public_active_notice_feature_identities`가 `{feature_id: feature_uuid}` 쌍을
  반환하는 단일 표면(기존 `public_active_notice_feature_ids`는 **제거** —
  잔여 호출자 전부 identities로 이행). ④ 신규 write — **dual 기간 정본
  generator 결정: uuid5 파생(`expected_feature_uuid`), UUIDv7은 legacy id
  소멸(32C 이후) 전 미채택**(결정론 = 양 저장소 checksum 전제). 이 규칙을
  app 검사에만 두지 않고 `0080`이 CHECK 2종
  (`ck_features_feature_uuid_dual_derivation` ·
  `ck_feature_aliases_uuid_dual_derivation`)으로 **DB 층에서 강제**(fail-close
  by construction — 32A의 "임의 명시 uuid 존중" 열린 계약을 의도적으로 닫음,
  해당 32A 테스트 재정의). provider upsert·admin add SQL은 `feature_uuid`를
  writer 명시 INSERT + RETURNING 대조(`verify_feature_uuid` →
  `FeatureIdentityInvariantError`) — 관측 계층. 0079 트리거 2종은 raw SQL
  seed 경로 편의 fill로 유지(파생 강제는 CHECK가 담당, 트리거 제거는 32C
  write fence 시점 재평가 — 0079 docstring 갱신). CHECK 2종은 dual 기간 한정
  fence로 32C에서 비파생 generator 채택과 함께 제거한다. ⑤ OpenAPI 3 spec
  재생성 + `openapi-diff-v1.json` baseline sha 재고정·`revisions` 개정 기록
  (diff 항목/counts 무변경 — ADR-068 값 전환 항목은 32C 목표 상태로 존치).
  **32C/39 이월 명시**: 내부 FK 체인(source_links/curation/price/weather 등)의
  UUID 조인 재작성과 referencing table shadow uuid 컬럼(rollout이 legacy FK
  체인 fence를 32C, 제거를 39로 고정), 응답 `feature_id` 값 UUID 전환,
  legacy write fence·트리거/CHECK 제거, PinVi vendored snapshot 재추출(32C 쌍
  PR), service/weather **batch body**의 feature 참조 UUID 해석(경로 참조와의
  비대칭 — 적대 리뷰 F4, 값 전환과 같은 시점), legacy ID 물리 제거(T-VN-39 removal manifest). 검증: unit 1,981(identity
  순수 계약 11 신규) · api 1,069(경계 dual/422/additive/404 재정의) · 신규 통합
  9(`test_feature_identity_boundary.py` — 양형식 해석·미존재·형식 오류·
  view/단건/bbox/batch/notice 병행 노출·upsert/admin-add 원자성·CHECK drift
  거부·alias 결측 invariant 관측) · 32A migration 8(명시 uuid fail-close
  재정의) + feature_repo 26 + freeze 3 + alembic 일관성/공개 view/notice/
  nearby/in-bounds 회귀 73 + perf gate tier1 shape 재고정(feature_uuid 의도적
  계약 변경) + H35 rehearsal(h35 도구의 head 등호 고정을 campaign target 앵커로
  수정 — 32A가 head를 전진시켜 생긴 본 branch 잠복 회귀, h35 81건 green) ·
  전체 통합 suite에서 32B 무관 잔여 실패는 live kor-travel-geo 인증 미결선
  env 5건(base 재현)과 pipeline cancellation lock-poll env 1건(base 재현)·
  suite 부하 flake 1건(단독 green)뿐 · export --check drift 0 · ruff/mypy
  --strict(main+api)/lint-imports clean.


## 2026-08-04 — T-VN-41D Map durable writer-drain control plane

- [x] **T-VN-41D — Map durable writer-drain control plane** (Manager T-049F / issue #115)

  migration `0079`이 Map application DB에 lease·instigation snapshot·owned run CAS를
  정규화했다. frozen Compose one-shot API image의 private `begin|attest|restore` command만
  schedule/sensor pause·late run terminal cancel·exact restore를 수행하며 Manager에는 opaque
  lease와 receipt SHA-256만 전달한다. begin 응답 유실·new owner recovery·backup rollback은
  daemon을 열기 전에 restore receipt와 prior pair attestation을 요구한다. public REST/OpenAPI,
  existing cache-target token, admin/ops command, production/n150은 사용하지 않았다. strict
  command 5건, isolated PostgreSQL 3건, Manager regression 143건, ephemeral Docker Compose
  rehearsal 1건을 통과했다.

## 2026-07-31 — T-VN-CI-PG 임의 ref PostGIS 수동 gate

- [x] **T-VN-CI-PG — workflow_dispatch 전용 PostGIS integration 경로**

  `.github/workflows/postgis-only.yml`은 GitHub UI의 branch/tag 선택기 또는
  `gh workflow run postgis-only.yml --ref <ref>`로 지정한 ref를 checkout한다. Python
  3.13에서 메인·REST API·Dagster 패키지를 editable로 설치하고 Docker testcontainers 기반
  `pytest tests/integration -q --no-cov`만 실행한다. `contents: read` 최소 권한과 30분 timeout을
  고정했으며 기존 `ci.yml`의 Python matrix·coverage 합산·fixture replay는 변경하지 않았다.
  pinned `actionlint 1.7.7` 검증과 diff check를 통과했다.

## 2026-07-31 — T-VN-12A/B/C/D domain command idempotency

- [x] **T-VN-12A/B/C/D — 재시도 가능한 write command의 단일 ledger 전환 (PR #906)**

  정적 registry가 55개 write route의 retryability와 ledger 등록 완전성을 검사하고,
  Feature·curation·review와 import·offline·backup/restore command를 actor-scoped
  `Idempotency-Key`, canonical body fingerprint, terminal replay와 `409` conflict로 통일했다.
  migration `0070_domain_command_ledger`는 DB-only transaction과 외부 효과 execution을
  분리하고, backup/restore/swap의 immutable effect token·Docker fence·secure marker·수동
  reconciliation 경계를 정본으로 만든다. Admin UI는 actor 경계에서 stable command key를
  생성·폐기하며 body surrogate dedupe를 제거했다.

  단일 적대 리뷰어의 최종 exact head `b2169512` 판정은 P0/P1/P2 0건이었다. Python
  3.11/3.12/3.13, lint, OpenAPI drift, fixture replay, frontend build와 PostGIS integration
  8개 check가 모두 성공했고, PR #906은 merge commit `01aa335f`로 `main`에 반영됐다.

## 2026-07-31 — T-VN-H31R curation 주소·행별 provenance fail-close

- [x] **T-VN-H31R — DB/REST/admin 경계의 curation provenance 완결 (#909, PR #910)**

  주소 후보를 구조화 field·Unicode literal hierarchy·versioned alias로 제한하고
  `address_hint` 단독 자동 링크를 제거했다. migration `0072_curation_provenance`는
  import batch/row/link decision을 append-only 정규화하며 DB immutable trigger,
  batch→row `RESTRICT`, same-item composite FK와 exact current pointer를 강제한다.
  official 등대 import는 sidecar를 hard-require해 행별 durable provenance를 저장하고,
  batch/current-row 조회와 stable cursor link audit를 REST/OpenAPI/admin type으로 제공한다.

  Feature merge는 trusted accepted link만 재승인한다. external item별 canonical
  survivor/provider/operator winner를 결정적으로 하나만 고르고 loser current를 coalesce한다.
  source-absent component history는 legacy 정본 동기화 뒤 master로 옮겨 active unique와
  projection/current pointer를 함께 보존한다. 단일 적대 리뷰의 최초 P1 2건·P2 3건·P3 1건과
  재리뷰 신규 P2 1건을 모두 닫았고 exact `e69f8926` 최종 판정은 P0/P1/P2/P3 0건이다.
  관련 unit/API/실 PostgreSQL 195건, merge 29건, legacy projection clean DB 5회 반복,
  admin frontend 286건과 정적/OpenAPI/보안 gate가 통과했다.

## 2026-07-31 — PR #732 설계 결정의 현재 정본 반영

- [x] **T-VN-DOC-732 — 인증·canonical ops·C6c/C7 문서 정합성**

  닫힌 미병합 PR #808의 오래된 task snapshot은 가져오지 않고, PR #732가 확인한
  header-only public 인증, principal-only actor, canonical datasets/pipeline과
  compatible-pair 설계를 최신 main에 선택적으로 반영했다. ADR-060·076, REST 카탈로그,
  cross-repo 통합 지도, 성능 문서와 C7 runbook이 현재 OpenAPI 및 완료된 production
  cutover를 같은 상태로 설명한다.

  C6c/C7 관련 Map·Manager·PinVi issue를 다시 대조해 완료 이슈는 모두 closed임을
  확인했다. 남은 Map #819는 외부 HAProxy `timeout tunnel` 운영 설정이 필요한 별도 보류
  항목이므로 이 문서 task에서 닫지 않는다. 코드·DB·runtime 변경과 새 live 실행은 없다.

## 2026-07-30 — Lane B b1 T-VN-16C sparse weather 생산자·소비자

- [x] **T-VN-16C Map 생산자 — sparse 다중 날짜 weather batch**

  `POST /v1/features/weather/batch`를 날짜별 실제 Feature만 받는
  `targets[{target_at, feature_ids}]` 계약으로 전환했다. 고유 parent의 spatial 후보를
  한 번 계산하고 target별 bitemporal fact로 source를 고른 뒤 target-local
  `card_key`·`cards[]`로 metric 반복을 제거했다. planning/source-series/metric/payload와
  PostgreSQL `statement_timeout`을 독립 제한하며 timeout은 DB 취소 완료 뒤 503으로
  변환한다.

  실데이터 40 target × 5 Feature는 200 pair·공유 card 40개·11,763 metric을 5.77초에
  반환했다. 적대 리뷰어 2명의 최종 finding은 P0/P1/P2 0건이며, 보존
  `ktm-tvn45-db`의 sparse found·401·422·`active→hidden→retired`·cleanup/audit 0을
  파괴적 API Live로 검증했다.

  PinVi PR #421은 Trip view를 sparse batch 단 한 번으로 소비하고 31일
  `not_requested`·worker fan-out을 제거했다. target/card strict ordering과 7-state
  projection을 owner/shared Web 경로에 함께 적용하고 vendored OpenAPI를 Map #902와
  맞췄다. 장기 여행 파괴적 Live UI와 전체 gate를 통과한 뒤 merge commit
  `e79a09d46e5500437418be29e0df341dcad139bd`로 병합됐다.

## 2026-07-30 — Lane B b1 T-VN-16B PinVi weather batch 소비

- [x] **T-VN-16B — PinVi weather batch 소비 cutover** (PinVi PR #420)

  Trip 상세/공유 view의 단건 weather N+1을 날짜별 Map batch projection으로 전환했다.
  `found|no_data|retired|suppressed|missing|unavailable|not_requested`를 day-scoped
  union으로 구분하고, 고유 날짜 31개·worker 4개·view 전체 10초 budget과 부모 request
  취소 전파로 outbound를 제한했다. Web은 서버 view만 렌더하며 단건 weather를 호출하지
  않는다.

  적대 리뷰어 2명의 최종 finding은 P0/P1/P2 0건이었다. 재사용
  `ktm-tvn45-db`에서 실제 parent 여섯 상태, weather found/no_data/retired,
  weather-only 503→복구, 단건 요청 0회와 활성 Trip 잔존 0건을 파괴적 Live UI로
  통과했다. PinVi PR #420은 전체 CI green 뒤 squash merge됐고 merge commit은
  `9eb95c6f0e02eeec11ff7b49a4ca8ab2654758c2`다. 날짜 fan-out과 31일 상한 제거는
  `T-VN-16C`로 분리했다.

## 2026-07-30 — Lane B b1 T-VN-16A set-based weather batch

- [x] **T-VN-16A — Map set-based weather batch**

  service-token 전용 `POST /v1/features/weather/batch`가 중복 없는 Feature ID 1~200개를
  한 PostgreSQL statement에서 순서 보존 조회한다. `target_at`/`known_at` snapshot,
  `current`/24시간 `timeline`, `found|no_data|retired`를 구분하고 단건 weather도 같은
  repository를 재사용한다. metric은 provider/domain과 원래 유효 구간·선택
  `effective_at`을 보존하며, 만료 range와 known-at 이후 forecast를 current에서 제외한다.

migration `0069_weather_series_catalog`는 physical-series registry, series exact-prefix
effective-time index와 공개 `kind='weather'` 전용 partial GiST를 한 번만 만든다. 후속 DDL
실패 재시도는 valid index를 재사용하고 invalid 잔재만 다시 만든다. 실데이터 clone에서
단건 17.8ms, 200건 1.27s, weather fact Seq Scan 0을 확인했다.

큰 delta 적대 리뷰어 2명이 range 만료, provider/domain 동률 결정성, 대형 index 이중 build와
재시도 rebuild를 찾아 회귀와 함께 닫았고 최종 P0/P1/P2는 모두 0이었다. 파괴적 Live에서 새
series FK를 helper가 모르던 실패를 해당 지점에서 재현해 exact fingerprint/parent lock/FK
audit를 추가했다. main·recovery가 모두 통과하고 소유 Feature/change request/weather/price/
series 잔여는 0이다. 새 clone·dump·checkpoint·downgrade 없이 `ktm-tvn45-db`를 head
`0069_weather_series_catalog`, healthy 상태로 보존했다.

## 2026-07-30 — Lane B b1 T-VN-H39 schedule pending barrier

- [x] **T-VN-H39 — Mocked schedule command pending barrier**

  workers=8에서 600ms 응답 지연보다 pending 단언이 늦게 시작하던 schedule command
  테스트를 `scheduleActionResponseGate`로 전환했다. route가 `commandBodies`를 기록해 요청
  도달을 증명한 뒤 테스트가 응답을 잡아두고, `finally`에서 반드시 해제한다. pending과
  release 뒤에 같은 5개 control(사유·즉시 실행·시작/중지·기본값 복귀·cron)을 각각
  disabled/enabled로 대칭 검증하며 timeout은 늘리지 않았다.

격리 포트에서 실패 spec은 setup 포함 **2/2**, frontend Vitest **278 passed**,
TypeScript·ESLint가 통과했다. exact production image checkpoint D workers=8은
**276/276**, manifest 일치, child exit 0·reporter gate true로 끝났고 owned
container/network/image는 모두 0건이다.

작은 delta 적대 리뷰어 1명은 release 뒤 cron/stop만 복원 확인해 나머지 control의
sticky-disabled 회귀를 놓치는 P2를 찾아, 동일 locator 집합의 대칭 상태 helper로 고정했다.
DB는 사용하지 않았고 보존 `ktm-tvn45-db`는 healthy·`0068_integrity_last_seen`라 다음 DB
작업에 재사용한다.

## 2026-07-30 — Lane B b1 T-VN-H38 failure fingerprint 완전성

- [x] **T-VN-H38 — Mocked failure manifest retry/error fingerprint 완전성**

  reporter는 deterministic failure와 expected flaky의 모든 non-passed retry, 모든
  `TestResult.errors`와 각 오류의 중첩 `cause`, result에 없는 leaf/parent step error를 각각
  검증한다. `failed`와 실제 Playwright test timeout인 `timedOut`만 실패 증거로 인정하고,
  `skipped`·`interrupted`와 expected failure의 passed-only 결과는 원인 증거 누락으로
  fail-closed한다.

  Playwright timeout은 ANSI를 제거한 exact generic envelope, 같은 timeout 값, 같은 hook의
  strict descendant result leaf를 함께 만족할 때만 wrapper를 제외한다. path 없는 test-body
  envelope도 같은 timeout leaf가 실제 result에 있을 때만 제외해, caught locator 뒤 별도
  hang·beforeEach 뒤 독립 afterEach timeout·soft assertion 뒤 별도 body hang을 숨기지 않는다.
  result에 직접 있는 parent error뿐 아니라 result에 없는 step-only parent도 자체 stage로
  검사한다. Playwright 1.60은 boxed propagation과 boxed 내부의 독립 재투척을 reporter
  metadata로 구별할 수 없으므로, descendant stage를 빌려주는 추론을 금지하고 fail-closed한다.

retry/error 합성 회귀 **28 passed**, frontend Vitest 전체 **278 passed**, TypeScript·ESLint가
통과했다. exact production image checkpoint D workers=4는 **276/276**, manifest 일치,
child exit 0·reporter gate true로 끝났고 owned container/network/image는 모두 0건이다.
report에는 retry·실제 result error index·cause depth·status·category·source
basename/line만 남기며 error text와 `TestStep.title`의 실제 입력값은 기록하지 않는다.

적대 리뷰어 2명은 skipped retry와 expected flaky 누락, `timedOut`/unexpected-pass false-red·
false-green, boxed propagation/독립 재투척의 식별 불가능성, hook/body/afterEach envelope
인과, ANSI title 비밀 노출을 실제 Playwright 1.60 probe와 합성 반례로 찾아 모두 회귀로
고정했다.
workers=8 exact D에서 600ms 지연보다 pending 단언이 늦게 시작한 schedule command 1건은
제품 회귀가 아닌 별도 동기화 결함으로 분리해 `T-VN-H39`로 등록했다. DB는 사용하지 않아
`ktm-tvn45-db`를 clone·restore·migration·downgrade 없이 보존했다.

## 2026-07-30 — Lane B b1 T-VN-H37 Mocked checkpoint 결정성

- [x] **T-VN-H37 — Mocked checkpoint 종료 판정·고병렬 flaky 진단**

  checkpoint runner는 reporter의 원래 `result.status`·gate 판정·발견 test 수와 Playwright
  child exit status/signal, 실행 전후 postcondition, cleanup 실패를 서로 다른 redacted
  issue code로 남긴다. manifest가 일치해도 child가 nonzero면
  `playwright_child_nonzero`로 실패하며 원인 없는 exit가 되지 않는다. cleanup은 1초 Docker
  client 종료코드 대신 exact 소유 container/network/image가 실제로 사라졌는지를 제한
  polling해, daemon 정리가 늦은 정상 상태와 실제 잔존을 구분한다.

  workers=8에서 재현된 change review 목록은 BFF 응답 완료를 기다린 뒤 row를 단언하고,
  pipeline create pending 검증은 700ms 시간 지연 대신 테스트가 직접 해제하는 response
  barrier를 쓴다. 단순 timeout 증가는 없다.

합성 종료 판정 회귀 **4 passed**, checkpoint 격리 회귀 포함 **13 passed**, 배포 자동화
단위 **8 passed**, frontend Vitest 전체 **259 passed**, TypeScript·ESLint가 통과했다.
exact production image checkpoint D는 동일 SHA에서 workers=8과 workers=4가 각각
**276/276**, manifest 일치, child exit 0·reporter gate true로 끝났고 매 실행 뒤 owned
container/network/image는 모두 0건이다. 이 task는 DB를 사용하지 않아
`ktm-tvn45-db`를 clone·restore·migration·downgrade 없이 그대로 보존했다.

적대 리뷰에서 child signal을 test failure로 분류하던 P2를 infrastructure failure(exit 2)로
정정하고, assertion 실패 시에도 response gate를 `finally`에서 해제하며 filesystem cleanup
실패 뒤 Docker cleanup을 계속하도록 보강했다. reporter가 첫 retry/error fingerprint만
검사하는 기존 잔여 위험은 범위 확장 규칙에 따라 `T-VN-H38`로 분리했다.

## 2026-07-30 — Lane B b1 T-VN-11A/B service batch 5상태 호환 쌍

- [x] **T-VN-11A — Map 5-state batch projection**

  service-token 전용 `POST /v1/features/batch`가 최대 200개 ID를 순서 보존 set-based
  snapshot으로 조회한다. `found|retired|suppressed|missing|unchanged` 각 arm은 PostgreSQL
  `bigint` 범위 revision을 가지며 `found`만 고정 `trip_card` projection을 반환한다. 중복 ID와
  범위 밖 validator는 422, upstream DB 실패는 503이다. 200개 planner gate는 PK index와
  frozen response shape를 검증한다.

- [x] **T-VN-11B — PinVi typed consumer cutover**

  PinVi는 같은 OpenAPI snapshot을 vendor해 다섯 arm을 exhaustively decode한다. 최대 200개
  chunk, generation/revision fence를 가진 bounded LRU cache, transport-only `unverified`
  fallback, Web·Map·Mobile 공용 상태 resolver와 canonical `coord` snapshot을 사용한다. 서로
  다른 저장소라 하나의 GitHub PR 대신 생산자·소비자 호환 PR 쌍으로 검증하고 Map → PinVi
  순서로 landing한다.

적대 리뷰에서 지도 좌표 shape 불일치, out-of-order cache rollback, 동일 revision 상태 복구를
막는 negative fence, chunk 상한·revision 범위, 실제 실패한 planner-default gate, DB 장애의
500 누출, 문서 drift를 찾아 모두 수정했다. service perf target **3 passed**, DB 장애 503
OpenAPI/단위 회귀를 고정했다. 재사용 `ktm-tvn45-db`에서 다섯 상태와 강제
503·복구를 파괴적 Live UI로 검증했고 지도 포인트 4곳도 확인했다. fixture는 원복하고 전용
container/listener는 제거했으며 clone은 healthy `0068_integrity_last_seen`로 보존했다.

## 2026-07-30 — Lane B b0 T-VN-49A/B/C/D React 구조 debt 완결

사용자 지시에 따라 네 단계는 브랜치와 PR을 나누지 않고 한 번에 구현·검증했다. 이 완료
아카이브도 H49 코드와 같은 merge commit으로만 `main`에 들어간다.

- [x] **T-VN-49A — Feature·review admin 상태기계 분해**

  dedup/enrichment/admin features/change requests/new feature를 query·mutation·form·panel
  책임으로 나눴다. dedup/new feature의 결합 상태는 reducer로 옮겼다.

- [x] **T-VN-49B — admin data-ops 상태기계 분해**

  curation collections/files/issues/offline uploads/POI cache targets를 분해하고 issues의
  결합 상태를 reducer로 옮겼다. offline upload form은 파일·form·create mutation을 직접
  소유해 상위 controller의 거대 prop 전달을 제거했다.

- [x] **T-VN-49C — public map·home 분해**

  curated feature map/features map/home에서 domain state와 표현 section을 분리했다.
  지도 adapter나 단순 전달 wrapper를 새로 만들지 않았다.

- [x] **T-VN-49D — ops pipeline·datasets 분해와 구조 예외 제거**

  datasets/logs/execution detail/timeline/request/schedule을 분해했다. request dialog는
  scope·target·execution form 경계와 좁은 memoized section으로 재구성했고 render 중
  상태 변경을 파생 상태로 대체했다. `no-giant-component` 19개와
  `prefer-useReducer` 3개 exact 예외는 모두 제거했다. 실제 transport lifecycle인
  `live.ts`와 외부 event effect인 datasets의 규칙별 최소 예외만 남겼으며 verifier가
  그 exact 목록을 고정한다.

적대 리뷰어 2명이 authored 전체 delta를 검토했다. 늦은 geocode/reverse 응답이 최신 입력을
덮는 문제, reset 뒤 stale 응답 재유입, request/offline-upload의 flat prop-bag 우회,
enrichment callback identity churn을 찾아 모두 수정했고 전체 재검토 P0~P2는 0건이다.
지연 geocode가 사용자가 나중에 바꾼 도로명 코드를 보존하는 Playwright 회귀도 추가했다.

검증은 React Doctor **280 files, 0 issues**, Vitest **254 passed**, TypeScript·ESLint·production
build green이다. Mocked checkpoint D는 serial과 workers=4에서 각각 **275/275**, expected/
actual failure·flake·skip과 종료 자원 모두 0이다. 보존 clone을 새로 복제하거나 복원하지 않고
`ktm-tvn45-db`를 재사용한 파괴적 Live UI는 main/recovery 각각 **2/2**, `complete/passed`다.
active acceptance Feature·nonterminal request·FK와 runner container/network/image/listener/
BLOCKED는 모두 0이고 clone은 healthy다. 기존 v5 checkpoint가 정상 soft-delete audit 6행
때문에 더는 exact하지 않아 현 상태로 baseline만 다시 서명했으며 Alembic downgrade와 full
restore는 실행하지 않았다.

## 2026-07-30 — Lane A a1 T-VN-H30A/H33/H36: curation 오링크 해소와 자동링크 금지

PR #888(H30A) · PR #890(H33/H36). 세 task 모두 적대 리뷰로 **결론이 되돌아간** 이력이
본문에 남아 있다 — 특히 H33은 `[x]` → `[~]` → `[x]`로 두 번 움직였고, 그 원인이
"측정 도구의 산물을 데이터의 성질로 읽은 것"이었다. 그 기록을 지우지 않고 옮긴다.

- [x] T-VN-H30A — **검증 finding을 `ops.data_integrity_violations`에 durable 기록**

  migration `0067_integrity_dedupe_key` + `0068_integrity_last_seen`,
  `sync_integrity_findings()`와 `record_address_validation_findings()`로 구현한다.
  PR #888 사후 감사에서 확인된 결함까지 현재 Lane B PR에서 보강했다.

  - `jsonb ||`는 shallow merge라 재실행 시 `EXCLUDED`의 null이 1회차 증거를 덮어썼다
    (durable ledger 안에서 증거 소실). `jsonb_strip_nulls`로 차단.
  - key는 `source_record_key`나 원천 id 문자열을 직접 싣지 않는다.
    provider/dataset/`source_entity_type`/`source_entity_id`/violation code 전체의
    `av2_<sha256>`(68 bytes)로 고정해 payload 변경·entity type 재사용·B-tree 행 크기 한계를
    함께 차단한다.
  - `ops.data_integrity_violations`에 statement 트리거가 있어(실측) finding당 INSERT가
    `ops_live` revision 단일 행에 배타 락을 잡고 트랜잭션 끝까지 유지했다 — admin 쓰기 차단·
    동시 run 직렬화·데드락. `dedupe_key` 정렬 후 `unnest` 단일 statement로 접어
    트리거 1회·잠금 순서 1개로 고정한다.
  - recurrence는 최초 `detected_at`을 보존하고 별도 `last_seen_at`을 갱신한다.
    `/admin/issues` cursor도 최신 관측 시각을 쓴다. FK target은 최신 recurrence로 갱신하고,
    Feature 삭제는 `ON DELETE SET NULL`이라 ledger 행을 지우지 않는다.
  - client 결과는 `observed/unique/upserted`를 구분해 내부 중복을 미기록으로 오산하지 않는다.
    DB 기록 실패는 typed error이며 strict 경로는 validation `Failure` 전에 fail-closed한다.

  > **자동 close는 없다** — 배치마다 sweep하면 같은 run의 다른 batch finding을 닫고,
  > 부분 unique index 밖으로 밀린 행이 다음 run에 다시 생성되며, 빈 bundle sentinel이 큐를
  > 전부 닫는다. `T-VN-H32`에서 run marker 기반으로 별도 설계한다.

- [x] T-VN-H33 — **curation_items 오링크 3건 정리 (H25B 파생)**

  **`[x]` → `[~]` → `[x]`로 두 번 움직였다.** 처음 닫은 근거("import가 재링크하지 않는다")가
  적대 리뷰 실측으로 반증돼 되돌렸고(아래 "철회"), `T-VN-H36`이 그 재링크 경로를 실제로
  막은 뒤에야 닫았다. **지금 닫는 근거는 "안 될 것이다"가 아니라 "막았고 측정했다"다** —
  `T-VN-H36`이 커밋 CSV 486행 전수 재생으로 이 3건이 자동 링크 대상에서 빠지는 것을
  확인했다(`reports/h36-link-impact-2026-07-29.json`).

  `scripts/h33_unlink_mislinks.py` (dry-run 기본, `--apply`로 쓰기).
  - **노출 실증** — 해제 전 남이섬 feature(서울 중구 사무소)에 한국관광100선 **2건**,
    청남대 feature(전남 영암)에 **1건**이 붙어 응답에 나왔다.
    표면은 `/v1/curations/*`이며 **익명 공개가 아니라 `RoutePolicy.PUBLIC_KEYED`** —
    public API key 보유자에게 열린 표면이라는 한정 아래 읽어야 한다.

    > **🔴 철회 — "해제 후 0건"의 근거가 반증 불가능했다.**
    > 초안 확인 스크립트는 `/v1/curations/features/{feature_id}`만 호출했는데, 이 엔드포인트는
    > curation이 없으면 200+빈 배열이 아니라 **404**를 낸다. 스크립트가 `curl -s`로 status를
    > 버리고 에러 본문을 파싱해 "0건"을 출력했으므로, **존재하지 않는 feature_id를 넣어도
    > 같은 출력이 나온다**(리뷰 실측). 오타·삭제·401이 전부 "해소됨"으로 읽혔다.
    > 이 세션에서 반복된 "측정 도구의 산물을 데이터의 성질로 읽기"와 같은 형태다.
    >
    > 대체 증거는 `scripts/h33_verify_public_exposure.py`다 — negative control(없는 id)과
    > 구별되지 않으면 **스스로 경고**하고, 반증 가능한 표면을 근거로 쓴다:
    > 컬렉션 상세가 200으로 item 110·114건을 돌려주고 그 안의 대상 3건이 `feature_id=null`,
    > `q=남이섬` 검색은 5 group을 내놓는 **양성 대조**를 가지며 그 안에 오링크 feature가 없다.
    > 즉 **item은 공개 응답에 그대로 있고 feature 링크만 끊겼다** — 해제이지 삭제가 아니다.
    > 부수로 e2e 기대값도 확인된다: 공식 19개 컬렉션 public membership 합계 **486 유지**
    > (`item_count`가 미연결 item도 세므로 unlink가 기대값을 깨지 않는다).
  - **탐지기 재실행** ([after 산출물](reports/h33-mislink-after-2026-07-29.json)) —
    `db_linked_rows` **3269→3266**, `db_region_codeable` **112→109**, `db_sido_mismatch` 3→0.

    > **"3→0"만 인용하면 안 된다.** 탐지기 모집단은 `ci.feature_id is not null` inner join이라
    > **링크를 끊으면 그 행이 모집단에서 빠진다** — 0은 관측이 아니라 정의다(리뷰 지적).
    > 엉뚱한 행을 끊었어도, item을 지웠어도 0이 나온다. 정보를 가진 숫자는 오히려
    > `3269→3266`·`112→109`, 즉 **정확히 대상 3행만 빠졌다**는 사실이다.
  - **ledger 방출** — `ops.data_integrity_violations`에 `curation_feature_region_mismatch`
    3건. **`open`이다**(초안은 `resolved`였으나 철회 — 아래). `feature_id` 컬럼은 비우고
    payload에만 남긴다: 이 FK가 `ON DELETE CASCADE`라 문제의 feature를 지우면 "잘못
    링크돼 있었다"는 기록까지 같이 사라진다.
  - **재실행 안전** — `--apply` 재실행은 "이미 해제" 3건으로 끝나고 finding만 갱신한다.
    지목한 오링크 `feature_id`를 가진 행만 대상으로 하며, 형제 행(같은 item의 다른
    component)은 정상으로 보고 경보를 울리지 않는다.

  > **🔴 철회 — "재링크되지 않는다"는 틀렸다.**
  > 초안은 *"공식 CSV import가 `feature_id = EXCLUDED.feature_id`로 덮어쓰는데 이 3행은
  > CSV가 비어 있으니 다시 링크되지 않는다"*고 적고 그 근거로 task를 닫았다.
  > **적대 리뷰가 prod에서 실측으로 반증했다.** `EXCLUDED.feature_id`까지만 읽고 거기
  > 무엇이 들어오는지 보지 않은 것이다 — 빈 `feature_id`는 링크를 막는 게 아니라
  > `curation_repo._RESOLVE_FEATURES_BATCH_SQL`의 **이름 자동매칭을 켠다**
  > (`WHERE requested.feature_id IS NULL AND lower(f.name) = lower(requested.place_name)`,
  > `address_hint`도 비어 있어 주소 필터는 건너뛴다). 단일 매칭이면 그 id가 그대로
  > `EXCLUDED.feature_id`가 된다.
  > **커밋된 CSV의 빈 264행 중 단일 매칭으로 해석되는 건 정확히 이 3행뿐이고, 전부 방금
  > 끊은 그 feature로 되돌아간다** — prod에 `남이섬`·`청남대`라는 이름의 live feature가
  > 각각 하나뿐이고 그게 바로 틀린 그 feature이기 때문이다.
  > 게다가 import는 `metadata = EXCLUDED.metadata`로 무조건 덮으므로 위에서 남긴 사유도
  > 지워진다. 그래서 finding을 `resolved`가 아니라 `open`으로 되돌렸다.
  > 지금 당장 되살아나지는 않는다 — prod가 `0063`이라 HEAD의 import SQL이 참조하는 컬럼이
  > 없어 import 자체가 실패한다. **`T-VN-H35`가 마이그레이션을 적용하는 순간 되살아나므로
  > H36이 H35보다 먼저여야 한다.**
  >
  > **덧붙인 정정 — 나는 배포되지 않은 코드로 prod 동작을 주장했다.** 위 인용
  > (`feature_id = EXCLUDED.feature_id`)은 **브랜치 코드**다. 배포 중인 이미지
  > (`kor-travel-map-api-latest`, revision `c8ed6164`, 2026-07-27)의 `_UPSERT_ITEM_SQL`은
  > `ON CONFLICT (collection_id, external_item_id, feature_id) WHERE archived_at IS NULL`이고
  > **SET 절에 `feature_id`가 아예 없다** — 그 코드에서는 재링크가 안 일어난다.
  > 즉 "지금 prod는 안전하다"는 맞지만 **내가 댄 이유는 prod에 존재하지 않는 코드였다.**
  > 같은 커밋에서 "머지 ≠ 배포"를 교훈으로 적어 놓고 마이그레이션에만 적용하고
  > **코드 주장에는 적용하지 않았다**(리뷰 지적).

  > **부수 발견 — prod가 마이그레이션 4개 뒤처져 있다.** ledger 방출을 붙이다가
  > `ON CONFLICT`가 두 번 실패했다. 원인은 코드가 아니라 **prod alembic head가
  > `0063_pipeline_root_id`**라는 것이었다 — H30A가 만든 dedupe 부분 유니크 인덱스(`0067`)가
  > **prod에 존재하지 않는다**. H30A의 dedupe 효과는 현재 prod에서 작동하지 않는다.
  > → `T-VN-H35`로 분리한다. 또 `source_record_key`에는 `provider_sync.source_records`
  > FK가 걸려 있어 curation 키를 넣을 수 없다(ledger가 provider 적재 전제로 설계됨).

- [x] T-VN-H36 — **curation import가 이름만으로 자동 링크한다 (H33 파생, H35보다 선행)**

  **완료(2026-07-29)**. `_adopted_match`로 **CSV `feature_id`가 빈 행은 후보 수와 무관하게
  링크하지 않는다**. 후보는 버리지 않고 `candidates`로 계속 노출하므로 운영자가 preview에서
  보고 admin에서 직접 링크할 수 있다 — 자동으로 붙는 것만 없앴다.

  **AC 결과**

  | AC | 결과 |
  | --- | --- |
  | H33의 3건이 import 후에도 미연결 | ✅ 막히는 자동링크가 **정확히 그 3건** |
  | 정당한 링크 손실 수치 | ✅ **0건**. 막히는 3건 전부 region 불일치(강원→서울 ×2, 충북→전남) |
  | 미연결 사유 구분 | ✅ `unmatched`(후보 없음) vs `name_only_match`(이름만 맞는 후보 있음). 사유 문장에 후보 소재 시도명이 들어간다 |
  | e2e 기대값 | ✅ 486 불변 — `item_count`가 미연결 item도 세므로(실측) 링크가 줄어도 membership은 안 바뀐다. 기대값 갱신 불필요 |
  | 반증 가능성 | ✅ 아래 |
  | 배포 순서 | ✅ **H35 이미지에 반드시 포함**. 아래 |

  근거 산출물: [`reports/h36-link-impact-2026-07-29.json`](reports/h36-link-impact-2026-07-29.json)
  (`scripts/h36_link_impact.py`, 커밋 CSV 486행 전수 + prod 리졸버 SQL 재생, 읽기 전용).
  빈 264행의 후보 분포는 **0건 256 / 2건 이상 5 / 1건 3**이다.

  **반증 가능성** — 이 세션에서 반복해 무너진 지점이라 명시한다.
  - 변경이 아무것도 안 막았다면 `blocked_autolinks`가 0으로 나온다.
  - 링크를 통째로 껐다면 `csv_specified`(222)가 0이 된다 — 이 값은 리졸버가 아니라
    **CSV 파일**에서 오므로 두 숫자가 같이 움직이지 않는다.
  - 리졸버 조회가 죽었다면 후보 분포가 전부 0이 된다.
  - 테스트에도 대조를 넣었다: **음성 대조**(후보 0건은 여전히 `unmatched` — 리졸버가 통째로
    죽은 것과 구분), **양성 대조**(CSV가 `feature_id`를 적은 행은 그대로 링크 — "링크 기능을
    껐다"면 실패). 대조 없이 "전부 미연결"만 보면 성공과 고장이 구별되지 않는다.

  **배포 순서 — 이 변경은 `T-VN-H35` 이미지에 포함돼야 한다.**
  H35의 인수에는 commit 모드 import 실행이 들어간다(live spec의 `palaceComponents`
  단언은 `0066` backfill이 `legacy:<uuid>`로 채우는 값을 실제 import로 덮어야 성립한다).
  그 실행 시점에 이 게이트가 이미지에 없으면 3건이 그 자리에서 되살아난다.

  **표면 비용 0** — SQL·DTO·openapi·마이그레이션 무변경. `code`는 openapi에서 자유
  문자열(`CurationImportIssueView.code: str`)이라 새 코드를 늘려도 생성 타입·프런트
  수기 union·배지 맵이 안 바뀐다. `ImportRowStatus`(enum) 확장은 그 5지점 연쇄를 부르므로
  **일부러 피했다**. 후보 시도명은 `FeatureMatch.address` jsonb에 이미 있어(리졸버가 이미
  SELECT한다) 리졸버 SQL을 넓히지 않았다.
  기존 테스트 **23건 무손상**(27 passed) — 라우터 import 테스트 중 비어 있지 않은 후보를
  돌려주는 것은 하나뿐이고 그건 `feature_id` 명시 경로다.

  <details><summary>원래 정의 (완료 전)</summary>

  `curation_repo._RESOLVE_FEATURES_BATCH_SQL`은 CSV `feature_id`가 비면
  `lower(f.name) = lower(place_name)` 단독으로 후보를 찾고, 단일 매칭이면 그대로 링크한다.
  `address_hint`가 비면 주소 필터도 걸리지 않는다. **지역 교차검증이 없다.**
  H33이 끊은 3건이 정확히 이 경로로 되살아난다(prod 실측: 빈 264행 중 단일 매칭 3행 =
  H33 대상 3건, 전부 틀린 feature로 복귀).
  또 `metadata = EXCLUDED.metadata`가 무조건 덮어써서 "링크 금지" 사유를 남길 자리도 없다.

  선택지: (a) 리졸버에 시도/시군구 교차검증 추가, (b) import가 존중하는 명시적 "링크 금지"
  표식, (c) 이름 단독 매칭 시 자동 링크 대신 `review`로 떨어뜨리기.
  **H35(마이그레이션 적용)보다 먼저 해야 한다** — 지금은 prod가 `0063`이라 import 자체가
  실패해 우연히 막혀 있을 뿐이다.

  **당시 AC(역사 기록 — 열린 task checkbox 아님)**
  - 이름 단독 일치만으로는 자동 링크되지 않는다. H33이 끊은 3건이 import 후에도
        미연결로 남는 것을 **실데이터로** 확인한다(preview 경로로, prod 쓰기 없이).
  - 정당한 링크를 과도하게 잃지 않는다 — 현재 링크 222건 중 이 변경으로
        재현되지 않는 건이 몇 건인지 **수치로** 제시한다. 0이 아니어도 되지만 밝혀야 한다.
  - 자동 링크되지 않은 행에 **왜**가 남는다(import 리포트 issue 또는 metadata).
        운영자가 "그냥 안 붙었다"와 "지역이 어긋나 막았다"를 구분할 수 있어야 한다.
  - e2e 라이브 기대값(공식 19컬렉션 membership 486, `OFFICIAL_FILES` 행 수)에 대한
        영향을 밝힌다. 바뀐다면 기대값도 같은 PR에서 갱신한다.
  - 검증이 **반증 가능**하다 — 변경이 실패했다면 다른 결과가 나오는 측정인지
        (negative control / 양성 대조) 명시한다. 이 세션에서 반복된 실수다.
  - 배포 순서: prod가 `0063`/이미지 `c8ed6164`라는 사실이 이 변경의 적용 순서에
        미치는 영향을 기록하고, H35와의 선후를 확정한다.

  **비목표**: 미연결 264건을 사람이 링크하는 작업 자체(그건 `T-VN-H34`/`T-VN-H31`).
  여기서는 **잘못 붙는 것을 막는 것**까지만 한다.

  </details>

  > **부수 정정 — "prod는 import 자체가 실패한다"는 틀렸다.** H33 작업 중 나는
  > *prod가 `0063`이라 HEAD의 import SQL이 참조하는 컬럼이 없어 import가 실패하므로 3건이
  > 당장 되살아나지는 않는다*고 적었다. 조사 결과 **배포된 이미지(`c8ed6164`)의 import
  > 코드에는 `source_present`/`external_component_id` 참조가 0건**이라 prod 스키마와
  > 정합하며 **오늘도 정상 동작한다**. 또 CSV import는 `_UPSERT_ITEM_SQL`이 아니라
  > `_BULK_UPSERT_ITEMS_SQL`을 탄다(전자는 admin 단건 POST 전용). 즉 "HEAD 코드를 prod
  > 스키마에 돌리면 실패한다"가 참일 뿐, 내가 그걸 "prod에서 import가 실패한다"로 옮겨
  > 적은 것이다. **또 배포되지 않은 코드를 prod 동작으로 읽었다.**

## 2026-07-29 — Lane B b0 T-VN-48 mocked drift·격리 clone Live 완료

- [x] **T-VN-48A~C** — 최초 273-test baseline의 deterministic drift 89건을
  Feature·검토 15건, ops 5건, auth/shell 69건으로 고정하고 단계별로 제거했다.
- [x] **T-VN-48D** — checkpoint D를 exact `823ba52b`에서 serial과 workers=4로 각각
  **274/274** 통과했다. expected/actual failure·flake·skip은 모두 0이고, 종료 뒤 self-owned
  container/network/image와 loopback listener도 0건이다.
  - [x] **D.1~D.3** — restore 전용 owner를 정규화하되 원본 owner invariant는 별도 검증하고,
    fail-closed dump를 정확히 하나일 때만 재사용하며, PostGIS `extconfig` OID를 안정적인
    schema+relation identity로 바꿨다. 실제 schema-only restore에서 extension digest
    동등성을 확인했다.
  - [x] **D.4** — 경량 v5 baseline과 선택적 full restore certification을 분리했다. v5는
    custom archive 구조·dump SHA256·clone snapshot·write fence를 서명하고
    `full_restore_verified=false`를 명시한다. 이번 최종 gate는 migration/schema/복구 계약이
    바뀌지 않아 이미 보유한 dump와 clone을 재사용하고 전체 restore를 반복하지 않았다.
  - [x] **D.5~D.6** — Feature 승인으로 정상 증가한
    `ops.ops_live_topic_revisions.dataset_projection` 한 행을 시작값으로 정규화하되,
    서명 dump의 직전 행을 대입한 전체 digest가 checkpoint와 정확히 같고 revision이 `+1`인
    경우만 허용했다. `direct-cleanup-running → recovery-resource-finalizing`의 정확한
    forward-recovery만 인정해 UI·fixture를 반복하지 않고 기존 evidence에서 완료했다.
  - [x] **D.7** — production MapLibre의 늦은 실제 `idle` event가 raster `sourcedata`
    계측에 섞이던 Mocked race를 repaint+idle+rAF barrier로 제거했다. 최초 serial은 이 한 건만
    실패한 273/274였고, 실패 spec 수정 뒤 같은 gate를 재개해 serial/parallel 모두 통과했다.
  - [x] **D.8** — PR CI가 `record_address_validation_findings()`의 typed
    `IntegrityFindingSyncResult` 계약과 Dagster asset 테스트 double 12개의 구 `int` 반환
    drift를 세 Python 버전에서 공통 검출했다. 모든 double을 실제 결과 타입으로 맞추고 Dagster
    package 전체 **510 passed, 1 skipped**, coverage **83.66%**와 Ruff를 통과했다.
- [x] **파괴적 Live** — 보존 clone의 본 acceptance와 recovery-only가 각각 **2/2**다.
  result는 `complete/recovered`, raw→normalized 전체 content 증명과 topic revision `+1`을
  기록했다. active acceptance Feature·pending change request·direct weather/price/FK,
  BLOCKED/quiescence/scratch/temp DB·role, runner container/network/image는 전부 0이다.
  v5 custom dump는 다음 task 재사용 판정 대상으로 보존했다.
- [x] **리뷰·감사** — branch-authored delta는 적대 리뷰 2인과 국소 후속 검토에서 P0~P2
  0건이며, 규칙 변경 전에 완료한 issue #881의 Claude Code PR #888 사후 감사 수정도 같은
  변경 집합에 포함했다.

## 2026-07-29 — Lane A a1 T-VN-H28A/B: #673 주소 검증 규칙 교체 (한 PR)

> **정정 (적대 리뷰 반영)** — 아래 "payload 행정코드 == geo 행정코드이므로 전부 오탐"이라는
> 근거는 **무효**다. concierge의 payload 코드는 같은 kor-travel-geo /v2/reverse를 같은 좌표로
> 호출한 캐시본이라 자기 자신과의 비교였다. 결론(380건 좌표 오류 아님)은 유지되지만 근거는
> 독립 축(provider 원천 텍스트 + 정지오코딩)으로 다시 세웠다 — 375건은 텍스트에 행정구역
> 토큰이 없어 좌표와 무관하게 통과 불가, 4건은 축약·단계 차이, 1건은 143 m 경계.
> 이름 축은 **삭제하지 않고** 결함만 고쳐 warning으로 유지한다(전 provider 적용).
> 상세: docs/reports/concierge-address-mismatch-evidence-2026-07-29.md

- [x] **T-VN-H28A** — 운영과 동일한 코드 경로(live concierge export → 실 geo reverse 주입 변환
  → `validate_feature_bundles_address`)로 재기준화했다. 증거:
  [`reports/concierge-address-mismatch-evidence-2026-07-29.md`](reports/concierge-address-mismatch-evidence-2026-07-29.md).
  - 1,430/410 → **1,477/380** (현상 유효).
  - drop 380건이 **전부 오탐**: payload 시군구코드 == geo 시군구코드 380/380. 진짜 불일치 **0건**.
    후보 전체(1,477)로 넓혀도 코드 불일치 0건.
  - 380/380이 payload에 시군구·법정동 코드를 **모두** 보유 — 권위 축이 있는데 규칙이 안 썼다.
  - 실패의 365/380은 `부산 기장 조방국밥`처럼 **행정구역명이 없는 짧은 주소**. 규칙이 잰 것은
    좌표-주소 일치가 아니라 provider 주소 문자열의 완전성이었다.
  - reverse 최근접 거리 `<10m` 210 / `<100m` 136 / `<1km` 34 — 좌표는 정확했다.
- [x] **T-VN-H28B** — 이름 축을 판정에서 제거하고 행정코드 교차검증으로 교체했다.
  - `AdminEvidence`(신규 DTO): 판정 두 축(좌표 reverse 코드 / payload 선언 코드)을 `Address`로
    **병합하기 전에** 보존한다. 병합 후에는 출처를 알 수 없어 교차검증이 원천 불가능했다.
  - 규칙: 코드 대 코드 접두 비교. 두 축이 모두 있을 때만 판정하고 없으면 **'통과'가 아니라
    '증거 없음'**으로 집계(`evidence_grade`). 리(8:10)는 `_bjd_code_from_emd_code`가 합성할 수
    있어 비교하지 않는다(8자리 캡).
  - **drop을 severity가 아니라 code allowlist로 전환**. 새 error 규칙이 추가돼도
    `DROPPABLE_ISSUE_CODES`를 명시적으로 고치기 전에는 영구 손실이 구조적으로 불가능하다.
    (`provider_address_mismatch`가 바로 그 방식으로 380건을 조용히 파괴했다.)
  - **batch 전멸 위험 제거**: payload에 `sigungu_code`만 있고 `legal_dong_code`가 없으면
    `Address._check_code_consistency`가 `ValidationError`를 던져 **1건이 1,477건 전체를**
    죽일 수 있었다(건별 격리 없음). `_address()`가 bjd에서만 유도하도록 바꿔 구조적으로
    불가능하게 하고, 건별 격리 옵션도 추가했다.
  - **회복 검증(live)**: 같은 export를 새 코드로 → **380 drop → 0, 1,477/1,477 적재, 손실 0.**
    교차검증 성립 1,372/1,477(92%), 행정코드 불일치 0건.
  - **replay 장치는 만들지 않았다** — 코드로 확인한 결과 불필요하다. drop은 적재 **전** 단계라
    dropped 후보는 `source_entities`에 행이 없고, concierge cursor는 영속화되지 않아 매
    materialize가 ledger 전량을 재생한다. 규칙만 고치면 자동 회복된다.
  - 검증: n150 CI-parity — ruff / mypy --strict(core 117·dagster 23) / dagster 494 passed +
    1 skipped / 관련 unit 179 passed. 신규 회귀 25건.
## 2026-07-29 — issue #881: Claude Code PR #882~#884 사후 감사

- [x] **PR #884 geo 인증·오류 계약 재감사** — backend가 VWorld public key를 URL query로
  계속 전송해 httpx INFO URL과 traceback frame에서 비밀이 노출될 수 있던 구조를 제거했다.
  Map API/Dagster/CLI는 geo public endpoint에 `X-KTG-API-Key` header만 사용하며
  credential은 `SecretStr`로 보관한다. admin trusted-proxy principal을 위임하지 않고
  transport/status 원본 예외도 연결하지 않는다.
- [x] **typed problem code 보존** — `GeoAuthNotConfiguredError`와 `GeoRequestError`가
  `/admin/issues`, offline-upload validation, feature-update HTTP adapter를 지나도 각각
  `GEO_AUTH_NOT_CONFIGURED`(503), `PROVIDER_ERROR`(502)로 유지되게 중앙 handler와 경계별
  problem+json 회귀 테스트를 추가했다.
- [x] **PR #882/#883 문서·계약 재감사** — PinVi가 읽지 않는
  `openapi-sha256.json`은 탐지력 없는 파생 산출물이므로 export/test/file을 제거했다.
  소비자 freshness는 실제 핀 commit의 spec/subset 비교만 정본으로 유지한다.
  완료된 H07C/H07D/H21/H29는 active backlog에서 제거하고 H27은 OPNsense 운영자 작업과
  quiet 2주기 검증 한 경로로만 정리했다.

## 2026-07-29 — Lane A a1 T-VN-H21: geo 인증 결선 검증·비밀 유출 차단

- [x] **T-VN-H21** — kor-travel-geo live 인증 결선을 검증 가능하게 만들고, 그 과정에서 드러난
  API key 유출 경로를 막았다. dedup 5건은 **브랜치 코드로** 실서비스에서 재통과(5 passed).
  후속 issue #881 감사에서 URL query 자체가 남긴 2차 유출 경로를 확인해 위 trusted proxy
  header 계약으로 교체했다. 아래는 PR #884 최초 landing 당시의 검증 이력이다.
  - 열린 질문이었던 "인증 뒤 runtime drift"는 **없음**으로 종결: 실 geo에 대해 reverse
    (status=OK, cand=11)·geocode(status=OK, conf=1.000) 응답이 기존 Pydantic 모델로 무손실
    파싱됐고, 배포된 Map api 컨테이너의 key가 geo 컨테이너 `KTG_VWORLD_API_KEY`와 동일함을 확인했다.
    → 원래 blocker는 배포 결선 결함이 아니라 **ad-hoc/CLI 실행 환경에 값이 없던 것**이었다.
  - **설계 전환(적대 리뷰 2명 합치)**: 호출 지점마다 preflight를 붙이는 최초 구현은 7곳 중 1곳만
    보호해 사실상 장식이었고, 이를 막으려 둔 AST 스캐너조차 같은 모듈 내 동명 변수 mutation으로
    우회됨이 **실제로 시연**됐다. `require_api_key` 기본 `True`로 **생성 시점** 검증에 옮겨
    CLI/API/Dagster/live test 4경로가 별도 조치 없이 보호된다(ADR-060 결과 절에 반영).
  - **오분류 수정**: 결선 누락을 `ValueError`로 던지면 기존 `except ValueError` 사다리에 걸려
    `/admin/issues`는 422, offline-upload는 409, feature-update는 422로 나갔다 — 없애려던
    좌표-vs-결선 오진을 API 안에서 재생산하는 상태였다. `GeoAuthNotConfiguredError` → 503
    (base_url 미설정과 동일 등급)으로 정정.
  - **비밀 유출 차단**: `str(httpx.HTTPStatusError)`가 `?key=<SECRET>` URL을 담고 그 문자열이
    502 detail·로그로 나갔다. query 제거한 `GeoRequestError`로 wrap. 회귀 테스트가 곧바로
    2차 결함을 잡아냄 — `from None`은 `__cause__`만 지우고 `__context__`에 원본이 남는다.
    except 블록 **밖에서** 던져 chaining 자체를 만들지 않게 고쳤고, 실 401 응답으로 확인했다.
  - 그 밖에: 128자 초과 key 사전 차단, CLI는 traceback(exit 1) 대신 stderr + `_EXIT_INVALID`(2),
    과장된 주석("요구한다" 무조건 / "route 처리 전에") 정정.
  - 검증: n150 CI-parity green — ruff / mypy --strict ×3(core·api·dagster) / lint-imports 4 kept,
    unit 1675 passed(잔여 3건은 main과 동일한 docker 바이너리 부재), api 792 passed,
    dagster 477 passed. live: 결선 차단·정상 좌표·오류 좌표·잘못된 키 4분기 + dedup 5 passed.

## 2026-07-29 — Lane A a1 T-VN-H29: 통합검색 map-import POI 좌표 null 복구

- [x] **T-VN-H29** (PinVi PR #418) — kor-travel-map curated import POI가 GET /search에서만 좌표
  null이던 실제 사용자 가시 버그를 고쳤다. 발견 경위는 T-VN-H07D 적대 리뷰의 소비자 전수 감사.
  - 근인: search.py::_snapshot_coord가 중첩 feature_snapshot["coord"]만 읽었는데, Map
    CuratedFeatureDetailFeatureSnapshotView는 extra=forbid이고 coord property가 아예 없어
    (H07D typed view) 좌표는 top-level lon/lat으로 온다 → 구조적으로 항상 None.
  - 비대칭이 힌트: 같은 payload를 admin_pois/kasi는 정상 해석해, admin·일출입 화면은 좌표가
    보이는데 통합검색만 null이었다.
  - 수정: 다섯 번째 추출기를 만들지 않고 정본 extract_feature_coord에 위임(기존 동작의 상위집합).
  - 회귀 위험 실증(리뷰어 2명): 비-map snapshot은 전부 중첩 coord이고 top-level
    x/y/geometry/location payload는 0건. 응답 계약도 기존 _coord/_float가 이미 처리. 같은 컬럼에
    admin/trips.py가 이미 같은 추출기를 써 표면 간 해석이 오히려 일치하게 됐다.
  - 리뷰 반영: 계약 게이트 주석·통합 문서의 "알려진 열화" 서술이 이 PR로 거짓이 되어 해소 기록으로
    정정. 커버리지도 배선(결과 dict→PlaceSearchResult.coord)·nullable lon/lat·0.0 좌표 보존까지 확장.
  - 검증: n150 CI-parity green(ruff/format/mypy), 신규 회귀 10 passed, 전체 unit 685 passed.

## 2026-07-29 — Lane A a0 T-VN-H07C: v5 승격 기각으로 종결 (a0 완료)

- [x] **T-VN-H07C** (#812) — 배포 compatible-pair에 pinned OpenAPI SHA를 넣는 v5 승격을 양
  저장소에 구현하고 테스트를 baseline까지 맞춘 뒤, 적대 리뷰 2명의 실증으로 **기각**했다
  (ADR-079). manifest는 v4 유지.
  - 근거 1: 제안 필드는 map_source_revision의 순수 함수라 추가 탐지력이 0이다. attestation은
    이미 그 revision을 운영자 제시 commit과 배포 이미지 OCI revision 라벨에 결박한다.
  - 근거 2: v5 전환 즉시 rollback이 무력화되고, 기존 프로덕션 이미지 revision에는 digest 파일
    blob이 없어 capture 자체가 불가능하다 — 운영자가 manifest 없는 상태에 갇힌다.
  - 유지: Map per-surface digest manifest(map#880, 207a6364)는 소비자 freshness 용도로 남는다.
    PinVi가 독립 사본과 대조하므로 그쪽에서는 실질 탐지력이 있다(H07B/H07D).
  - 폐기: docker-manager v5 브랜치, Map attestation v5 브랜치. 운영 문서·런북 무변경.
  - 규율 정정: OpenAPI 변경 완료 조건에서 재-capture/attestation 제거, per-surface digest 갱신 +
    소비자 스냅샷 재-vendor로 대체.

## 2026-07-28 — Lane A a0 T-VN-H07D: admin detail-snapshot 계약 + freshness 게이트 실효화

- [x] **T-VN-H07D** (#815 close) — cross-repo 2 PR. **① Map** PR #878(`5c0e0cae`), **② PinVi**
  PR #416(`8ea83358`).
  - **문제**: PinVi 큐레이션 import 런타임이 소비하는 admin detail-snapshot의 계약이 **OpenAPI로
    표현조차 되지 않았다**. PinVi가 읽는 plan-level 필드가 전부 free-form `dict[str, Any]`
    (`theme`/`content`/`source`/`feature_snapshot`) 안이라 스펙에 `{"type":"object"}`로만 나왔고,
    PinVi가 호출하는 경로는 `include_in_schema=False` 숨은 alias라 스펙 기반 게이트가 볼 수 없었다.
  - **① Map**: 생성부가 고정 key로 만드는 payload를 **typed view 4종**으로 전환.
    **etag는 repo payload dict 기준이라 그 dict을 손대지 않아 etag·캐시 계약 불변.**
    계약 게이트 9건(필드 핀 / 컨테이너 `$ref` 결합 / **alias 라우트 등록** / 생성부↔view 정합
    populated·all-null / **endpoint HTTP** 문서경로·alias × populated·all-null).
    `openapi.json` + frontend `types.ts` 동시 재생성.
  - **② PinVi**: 경로·응답 스키마의 **전이적 폐포 + securityScheme**만 결정적으로 추출한 subset
    (19 KB, full 1.1 MB 대비)을 vendor하고, 실제 소비 필드의 consumer 계약과 admin 인증 헤더
    header-only 계약을 고정. exact property 집합은 producer 소유라 중복 고정하지 않는다.
  - **freshness(핵심)**: 기존 live-compare는 sibling 체크아웃 부재로 skip되어 CI에서 항상
    green이었다. `contract-pin-consistency`(차단, `aggregate-ci.yml` required check 등록)가 Map을
    **핀 커밋**으로 체크아웃해 user는 byte, admin은 재추출로 **실제 비교**한다. 핀 자체의 뒤처짐은
    매일 도는 비차단 `contract-staleness`가 Map main과 비교해 알린다(H07B의 174-commit 사례).
  - **적대 리뷰 각 2명**. Map: 재생성 산출물 `types.ts` 누락(머지 blocker)과 `feature_snapshot`
    소비 여부 오판을 잡아 네 번째 typed view로 확장. PinVi: **"차단"이라던 job이 required check에
    없어 실제로는 아무것도 막지 못하던 것**을 잡아 실효화하고, job 이름을 증명 대상에 맞게
    `contract-pin-consistency`로 정정, `continue-on-error`가 죽이던 예약 알림 경로 복구,
    subset의 securityScheme 누락 보완, 계약상 불가능해진 e2e fixture 교정.
  - **검증**: 양쪽 n150 CI-parity green(Map api 790 passed / PinVi unit 675 passed),
    freshness 양쪽 실증, PinVi integration을 testcontainers로 실제 실행(1 passed),
    실제 CI에서 신규 게이트 pass(9s) 확인.
  - **파생 등록**: `T-VN-H29`(PinVi 통합검색의 map-import POI 좌표 null — `_snapshot_coord`가
    `coord`만 읽는데 Map view에 `coord`가 없어 구조적으로 항상 None).

## 2026-07-28 — Lane A a0 T-VN-H07B: PinVi consumer contract landing

- [x] **T-VN-H07B** — 오래 열린 PinVi #403(base 13 commits 뒤)을 재감사해 residual만 남기고
  **PinVi PR #415**로 landing했다(#403은 대체·종결). 재감사 핵심: #403은 Map producer 테스트를
  복사해 **공개 curated 표면**을 고정했으나 PinVi user client는 그 경로를 호출하지 않는다
  (`_CLIENT_PATHS`에 curated 없음, ADR-049/Map PR #533이 public `*-copy` 폐지, 큐레이션 런타임
  표면은 admin `/v1/admin/curated-features/{id}/detail-snapshot` = H07D 소유, producer exact
  고정은 H07A 소유). curated pin을 전량 제거하고 **PinVi가 실제로 읽는 필드**의 typed consumer
  contract(21 schema)로 대체했다.
  - **스냅샷 재동기화**: H07A의 실제 user OpenAPI SHA와 대조해 vendored 핀이 stale임을 확인
    (`91b30f40`@`cf1f0bba`, Map main보다 174 commits 뒤) → Map main `8880c29b`(H07A `259a9ec5`
    포함)/`0a7f1684`로 갱신. 실제 drift는 구조 1건(`external_component_id`, Map 0066) + 설명
    3건뿐이고 PinVi 소비 스키마는 구조 변화 0건.
  - **사슬 전체 고정**: 경로→컨테이너(`_ENDPOINT_DATA_SCHEMAS` 13경로 + `_CLIENT_PATHS` 일치
    가드) → 컨테이너→item(`items.$ref`)·map value(`found`→`FeatureDetailResponse`) → 필드
    type/format/enum/required/nullable. envelope `meta`(`Meta`/`ClusterMeta`/`PageMeta`)도
    client가 `data`로 re-projection해 소비하므로 함께 고정. `/v1/public/*`는 `model_validate`로
    객체 전체를 검증해 `app/schemas/public.py` `model_fields` ⊆ 계약을 강제(자기참조 검사 제거).
    `_SCHEMA_FIELDS`는 계약 표에서 파생. **exact property 집합은 의도적으로 비고정**(consumer가
    producer의 additive 변경에 false-red 나면 안 됨 — 0066이 실제 사례).
  - **검증**: n150 CI-parity clean clone `74b199d` — ruff/ruff format(343)/mypy --strict(196)
    green, 계약 11 passed, 전체 unit **665 passed**(base 661 대비 +4; 실패 20건은 base
    `417da20`에서 동일 실증된 기존 docker 의존 실패). **변이 테스트 30건 전부 검출**.
  - **리뷰**: 적대 2명 → 재리뷰 → 최종 확인(block) → 해제 확인(cleared). 최종 확인이 잡은 오기
    (`data.get("cluster_unit")`을 "항상 None인 잠재 버그"로 기록)를 정정 — client가
    `meta.cluster.cluster_unit`을 의도적으로 re-projection하며 기존 green 테스트가 non-None을
    단언한다. 같은 오독으로 빠졌던 meta 필드도 함께 고정했다.
  - PinVi 문서(`docs/integrations/kor-travel-map-rest-api.md` §8)는 같은 PR에 포함.

## 2026-07-28 — Lane B T-VN-46 npm optional tree 무결성 완결

- [x] **T-VN-46** — npm 10.9.4가 제외된 FreeBSD/WASM optional parent의 자식 6개를
  root `extraneous`로 남기는 Arborist 현상을 동일 lockfile에서 재현했다. npm 12.0.1과
  지원 Node 하한 22.22.2로 전환해 direct dependency 추가나 `npm ls` 출력 필터 없이
  `problems` 0건으로 만들고 기존 6-package allowlist를 제거했다.
- root `allowScripts`는 실제 install script가 필요한 `esbuild@0.28.1`과
  `unrs-resolver@1.12.2`만 exact version으로 허용한다. `.npmrc`의
  `strict-allow-scripts=true`와 `engine-strict=true`가 신규 script와 미지원 Node/npm을
  fail-close한다. workflow와 frontend/C7 Docker image도 같은 npm 12.0.1 계약을 사용한다.
- n150 clean install에서 audit 0, unreviewed install script 0, npm tree 0 problems,
  ESLint·React Doctor 0 diagnostics, Sharp SVG→WebP, admin/user OpenAPI codegen drift,
  두 type-check와 production build를 통과했다. npm 12 package-lock-only 재실행 drift도 0이다.
- 적대 리뷰어 2명이 exact 구현 head `378c6524`를 검토해 stale unit/doc, bare
  `allowScripts`, 과도하게 넓은 Node engine을 보강했고 최종 P0/P1/P2 0건을 확인했다.
- 재사용 실데이터 clone에서 candidate API/UI/C7 image로 파괴적 admin Feature acceptance를
  인증 setup 포함 **2/2, 37.9초** 통과했다. API-owned non-deleted Feature와 pending change
  request, weather/price fixture는 모두 0건이다. clone은
  `0066_curation_component_identity`, health 정상이고 다음 task 재사용 판정 전까지 보존한다.
  Playwright 상태/cookie·raw trace·screenshot·민감 로그·임시 env/session secret과 candidate
  container는 실행 직후 폐기했다.

## 2026-07-28 — Lane A a0 T-VN-H07A: Map #814 residual contract landing

- [x] **T-VN-H07A** — 오래 열린 Map #814(base 95 commits behind)를 최신 main 위 residual로
  재감사·landing했다(squash @ 259a9ec5). stale `docs/tasks.md` commit 2건과 main T-VN-05R가
  이미 소유한 union discriminator/mapping/oneOf 구조 assertion을 제거하고, main에 없는
  field-level 잔여만 남겼다: PinVi가 REST로 소비하는 curated feature variant 7·detail 5·
  PublicCuratedAddress·PublicCurationCollection/Item/CurationFeature/FeatureCurationGroup
  schema의 exact property/required 집합, 필드별 JSON type/format/enum/discriminator const/$ref
  대상을 생성 OpenAPI 기준으로 고정. n150 CI-parity가 base drift(migration 0066
  `external_component_id` required 추가)를 검출해 현행 계약으로 재조정했다. 적대적 리뷰어 2명
  (tautology·redundancy / contract-fidelity)이 전 schema를 실제 pydantic 생성 스키마·
  `openapi.user.json`과 대조해 land 판정했고, phones array element type 고정(nit)을 반영했다.
  n150 pytest 11 green + GitHub CI(lint/mypy/lint-imports·openapi-drift·pytest matrix·
  integration PostGIS) green. test-only OpenAPI 계약이라 admin-UI 표면 없음 — live 검증은 n150
  게이트가 실제 생성 OpenAPI에 대해 계약을 실행하는 것으로 갈음. PR #814.

## 2026-07-28 — PR #869 후 task 전면 재감사

- [x] **T-VN-REAUDIT-0728** — `tasks.md`·완료 이력·실코드와 Map/PinVi/
  docker-manager/geo의 열린 PR·이슈를 대조하고, 큰 task를 독립 PR·검증 단위로 분해했다.
  Agent A/B 소유 경계, migration·OpenAPI·frontend 충돌 barrier, Wave 2 freeze/join/final
  cutover 순서와 실패 지점 재개 규율을 고정했다. 적대적 리뷰어 2명이 legacy 조기 물리 삭제,
  compatible-pair 재-capture, idempotency·frontend ordering, H21 첫 blocker 표현과 문서 예외
  범위를 바로잡은 뒤 잔여 P0/P1/P2 0건을 확인했다.

## 2026-07-28 — Lane B T-VN-45 features map Live 라운드트립 완결

- [x] **T-VN-45 (#871)** — `/features` 실데이터 input-roundtrip을 실제
  `/v1/admin/features/in-bounds`의 `items`/`clusters` 계약으로 전환했다. 모든 새 query key의
  요청 bbox·kind·zoom과 성공 응답 본문을 검증하고, 취소된 요청도 URL 계약 검사를 건너뛰지
  않는다. cache hit는 새 HTTP 응답을 강제하지 않고 map idle 뒤 마지막 성공 응답의 전체
  point `feature_id` 집합·server cluster key/count/centroid와 실제 DOM이 일치할 때만
  수렴한다.
- **false-green 제거**: point marker, server cluster, coincident popup row에 각각
  `data-feature-id`/`data-cluster-key`를 노출했다. 식별자가 없는 marker도 빈 값으로 exact
  비교에 남겨 실패시키고, cluster는 표시 count와 MapLibre projection 기준 DOM 중심 좌표를
  1.5px 이내로 검증한다. 상세 클릭은 선택한 ID의
  `/v1/admin/features/{feature_id}`와 `AdminFeatureDetailResponse.data.feature`만 허용한다.
- **파괴적 Live UI**: n150 격리 prod clone에서 지도 저배율 cluster·서울/부산 items·kind
  필터·상세 클릭을 실패 지점별로 재개해 통과했다. 별도 write workflow는 실제 add 승인,
  update 승인, update 거절, 비활성화, delete 승인을 모두 수행해 인증 setup 포함 **2/2**
  (**48.3초**)를 통과했다. 최신 합성 Feature는 `deleted`이고 `deleted_at`/
  `user_deleted_at`가 모두 채워졌으며, 전체 합성 감사 범위는 non-deleted Feature **0건**,
  pending change request **0건**이다.
- **Live spec 동반 복구**: 파괴적 검증 중 확인한 ADR-066 이전 `operator` 입력, 접힌 고급
  JSON 섹션, 구 create/review/preview 접근성 이름과 번역 상태, 동시 필터 변경의 비결정적
  이름 검색을 현행 UI 계약에 맞췄다. admin 목록은 필터·정렬을 먼저 확정한 뒤 exact
  `feature_id` PK 검색 응답 본문과 row를 함께 단언한다. 적대 리뷰 뒤 update nested field
  보존, 비기본 `marker_icon=park`의 unchanged PATCH omission/결과 보존과 inactive exact 목록
  요청/응답까지 추가로 고정했다.
- **재개용 resource**: clone `ktm-tvn45-db`, dump와 redacted checkpoint는 PR 머지 뒤 다음
  task 착수 전 재사용 판정을 위해 보존했다. Playwright 인증 상태/cookie·raw trace·실데이터
  screenshot·민감 로그·임시 env/session secret은 재사용하지 않고 Live 종료 직후 폐기했다.
  `PGPASSWORD` metadata가 남아 있던 중지 상태의 clone transient container 8개도 제거했다.
  clone migration head는
  `0063_pipeline_root_id`, Feature **1,030,469건**, POI cache target **90건**이며 파괴적
  실행 후 clone health는 정상이다. 호환성·오염·디스크 판정 결과는 다음
  `resume.md`/`journal.md` 갱신에 기록한다.

## 2026-07-27 — Lane B T-VN-47 React Doctor + durable curation 완결

- [x] **T-VN-47** — React Doctor full scan을 269개 파일·actionable 진단 0건으로 만들었다.
  WebSocket cleanup·nested updater 부수효과·반복 helper·상태 파생·접근성 진단을 근인으로
  정리했다. frontend root의 `doctor.config.json`과 exact verifier가 shadow config·ignore,
  command/scope 축소와 package-level 우회를 거부한다. giant component 19개·reducer 후보 3개는
  별도 구조 설계가 필요해 exact scoped debt `T-VN-49`로 이관했다.
- [x] **T-VN-H13 후속 완결** — #862의 조건부 upsert를 source 누락·삭제→재등장·Feature merge까지
  확장했다. migration 0065가 `source_present`/`source_updated_at`과
  `operator_updated_by`/`operator_updated_at`을 분리하고 archived/NULL까지 포함한 exact identity
  unique를 강제한다. legacy projection은 `legacy_projection_id`로 durable item과 연결하며, stable
  collection key는 mutable slug 대신 theme/source UUID와 title hash를 사용한다. 중복 semantic
  collection은 `:split:<collection_id>`로 보존하고 임의 admin key 충돌도 migration 양방향에서
  덮어쓰지 않는다.
- **과거 drift 복구**: 0064 theme slug 재사용으로 collection owner가 탈취된 active/archived
  projection은 명시적 `legacy_projection_id`로 원 theme에 복구한다. canonical-only item은 원
  projection durable link가 없고 external identity도 theme 간 공유될 수 있으므로 자동 owner
  복구를 하지 않는다. upgrade 전 old projection 삭제 여부와 관계없이 모든 legacy-marker
  collection에서 `draft/admin_only` quarantine에 보존한다. admin PATCH로 mutable marker가 지워진
  이력도 immutable `legacy:` key namespace로 판별한다. exact `legacy:quarantine:<UUID>` key와
  immutable migration creator가 모두 일치하는 산출물만 재격리하지 않아 정상 `quarantine:` theme
  slug와 migration 왕복 identity를 함께 보존한다. mutable quarantine metadata에
  `migrated_from`이 추가돼도 upgrade·downgrade key rewrite에서 같은 결합을 제외한다.
  `source_record_key IS NULL`인 DELETE→새 UUID 재삽입도 기존 external identity와 operator
  tombstone을 재사용한다. legacy cross-title 이동은 target collection 뒤 source parent를
  잠그지 않고 item만 잠가 A→B/B→A 교착을 제거한다.
- **리뷰·검증**: 사용자 지시에 따라 단독 적대 리뷰어 1명이 PR840 이후 Claude Code 작성 PR
  #841~#845·#847~#850·#852~#857·#859~#864와 이번 exact code를 함께 감사했다. migration
  upgrade→downgrade→re-upgrade, 수동 base/split/staging key 선점, archived owner repair,
  canonical-only owner 증거 부재, 오래된 projection의 후속 owner 탈취, owner 간 동일 external identity,
  upgrade 전 old projection 삭제, metadata marker 제거, 정상 `quarantine:` theme slug,
  mutable quarantine metadata와 왕복 identity, null-source tombstone, 실제 두
  transaction 교차 이동을 포함한 관련 unit/integration/API 144건과 외부 geo live 5건을 제외한
  backend 전체 2,392건이 통과했다. static·frontend 전체 gate와 격리 실데이터 destructive Live UI
  근거는 같은 날짜 `journal.md` 항목을 정본으로 한다. curation exact code `7e2920aa`의 최종
  리뷰는 신규 P0–P2 0건·reviewer PostgreSQL 46/46이다.
- [x] **T-VN-H23** — T-VN-47 전체 실데이터 clone에서 발견한 0053 legacy active scope 중복
  blocker를 같은 PR에서 해결했다. 동일 scope의 queued job은 실제 dispatch 정렬로 winner 하나를
  보존하고 나머지를 기존 오류 문맥과 winner ID가 남는 `cancelled` terminal 상태로 전환한다.
  running 하나는 우선 보존하되 running 둘 이상 또는 cancellation audit marker가 걸린 중복은
  mutation 전에 fail-close한다. 실데이터와 같은 queued/now/now, running+queued, multiple-running,
  cancellation attempt/member 원자 보존과 downgrade/re-upgrade를 PostgreSQL 회귀로 고정했다.
  같은 단독 적대 리뷰어가 cancellation audit 훼손 가능성을 찾아 보강했으며 exact code
  `ca313d32`에서 잔여 P0–P2 0건을 확인했다.
- [x] **T-VN-H24** — 복합 공식 source item의 durable identity를 Feature target과 분리했다.
  `(collection_id, external_item_id, external_component_id)`가 membership을 식별하고
  `feature_id`는 nullable·mutable target으로만 둔다. CSV/API/UI/OpenAPI에 component key를
  전파하고 legacy UUID·operator/source/archive 이력을 첫 authoritative import에서 같은 행으로
  승계한다. 모호한 legacy 후보와 같은 source item의 active Feature 중복은 mutation 전에
  fail-close한다. 0064→0066 연속 업그레이드는 0065의 지연 FK·trigger event를 0066 첫 DDL 전에
  명시적으로 검사·소진해 단일 Alembic transaction에서도 안전하게 전진한다. n150 prod 격리
  clone에서 0036→0066 forward migration, 실제 UI CSV preview/commit과 REST/admin/지도 검증,
  공식 19 collections·486 source-present memberships, component 2/2, operator adoption 2,
  duplicate target 0, prod 불변을 확인했다. 실패 시 clone/build/import checkpoint를 보존해
  처음부터 반복하지 않고 실패 단계부터 재개했으며 성공 뒤 clone을 삭제했다.
- [x] **T-VN-H26 / #868** — main에 이미 반영된 c6c canonical
  `KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET` direct alias와 회귀를 재확인했다. 남은 수용 조건인 기존
  `KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET` fallback을 추가했다. 두 값이 함께 있으면 canonical이
  우선하며, 어느 값도 없으면 `None`, canonical로 로드된 secret에 잘못된 admin 헤더는 `403`이다.
  사용자 지시에 따라 이 추가 작업만 적대적 리뷰 예외로 처리했다.

## 2026-07-27 — Lane B T-VN-44 frontend lint·schedule recovery·가격 identity

- [x] **T-VN-44 (#858)** — frontend full ESLint를 0 warning gate로 고정하고 schedule 응답 유실
  복구, 가격 series identity `provider + price_domain + product_key`, migration 0064와 격리
  실데이터 Live UI를 완료했다. 세부 구현·검증은 같은 날짜 `journal.md` 항목과 CHANGELOG를 따른다.

## 2026-07-27 — T-VN-H20 prod admin credential 회전 완료 (login 200 검증)

- [x] **T-VN-H20** — prod admin password/hash 회전. credential-safe 스크립트(auth.ts와 동일 pbkdf2_sha256
  310k iter/256bit 파생)로 새 강한 password 생성 — 평문→gitignored `docs/prod-access.local.md`, hash→repo
  밖 scratch, stdout엔 경로·길이만(값 비노출). prod `.env`의 `KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH`를
  base-compose로 UI만 recreate(R2: `-f docker-compose.yml --no-deps --force-recreate`, override 배제)해
  회전. **검증**: 새 pw→login 200 + 오키/기존→401, 배포 컨테이너 hash 87자, UI healthy.
  - **인시던트+복구(투명)**: 최초 회전에서 hash를 `.env`에 raw로 써서 docker-compose가 `$310000$salt$hash`의
    `$<salt>`/`$<hash>`를 변수 interpolation→salt/hash 소거(배포 20자)→admin UI 일시 로그인 불가.
    python diag(.env 87 vs container 20 MISMATCH)로 규명→`$`→`$$` escape 재작성→recreate→87자 복원→200 확인.
    매 단계 `.env` 타임스탬프 백업(롤백 가능). **교훈**: compose `.env`의 `$` 포함 값은 `$$` escape 필수.
  - 잔여(사용자 판단): local doc stale 섹션(초기 미배포 gen) 삭제, session secret 미회전(기존 세션 만료까지
    유효 — 완전 폐기 시 별도 회전), n150 `.env.h20-*bak.*` 롤백 백업 정리.

## 2026-07-27 — Lane B b4 하드닝 3건 완결 (H13·H14·H15)

각 항목 적대 리뷰어 2명(blocker 0) + 회귀 테스트 + CI green(pytest/dagster/PostGIS) 후 머지.
(Lane A가 Lane B b4를 사용자 지시로 순차 대행.)

- [x] **T-VN-H13** — curation authoritative 재적재가 운영자 override 보존 (#699 → PR #862).
  `_BULK_UPSERT_ITEMS_SQL` ON CONFLICT DO UPDATE·WHERE + `_PREVIEW_IMPORT_COUNTS_SQL` 비교에서
  status/curation_relation/reuse_policy 제거 → CSV 재적재가 운영자 admin PATCH 편집을 리셋하지 않고
  provider 파생 필드만 갱신. 회귀 테스트(편집 보존 + provider 갱신 + preview/removed 카운트).
- [x] **T-VN-H14** — KREX traffic notice snapshot bounded retry self-heal (#700 → PR #863).
  연속 2 snapshot 완전일치 즉시-실패 → sliding bounded-retry(상한 4, 총 최대 5 snapshot, inter-retry
  delay 0.5s) + typed `KrexTrafficNoticeSnapshotUnstable`. 휘발성 feed 일시 불일치를 self-heal해 run
  반복 실패·notice 신선도 정체 완화. 안정 feed는 2 snapshot 즉시 yield(무변경). 테스트 3종(transient/
  persistent/exact-boundary).
- [x] **T-VN-H15** — c7 attestation IPv6 public origin bracket 정규화 + zone-id 거부 (#805 → PR #864).
  `_public_origin`이 IPv6 host를 bracket 없이 `f"{host}{port}"`로 재구성(모호)하고 zone-id 미거부하던
  것을 `[address.compressed]` bracket+canonical + `"%"` scope 거부로 수정. `run-c7-prod-live-e2e.sh`의
  병렬 canonicalizer도 동일 미러링(divergence 방지). domain/IPv4 무변경(기존 해시 보존).

## 2026-07-27 — T-VN-H19 public API key 양성 production runtime 실증 (C2 갭 종결)

- [x] **T-VN-H19** — #854에서 "등가 충족"으로 처리했던 C2(public-key→curated 200)의 DB lookup+hash
  compare 양성 분기를 n150 production(map=c8ed6164)에서 credential-safe 직접 실증. admin-BFF
  `POST /v1/admin/public-api-keys`로 임시 key 발급(평문 1회, 값 비출력) → **valid key 200 PASS**,
  wrong key **401 PASS**, `POST .../{id}/revoke` **200**, 폐기 후 same key **401 PASS**(revoke lifecycle).
  key 값은 출력·기록 안 하고 key_id·status만 증거. → **경계 매트릭스 14/14, T-VN-03+T-ADM-C6c 전체
  완료**("C2 전까지 완료 금지" 조건 해소). 증거: reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md §1 C2.

## 2026-07-27 — T-VN-H12 live acceptance status marker 좌표 run-unique jitter (live 검증 완료)

- [x] **T-VN-H12** — `admin-feature-acceptance-write.live.spec.ts`의 status marker 좌표를 `sha256(RUN_ID)`
  ±0.25° run-unique jitter(`STATUS_MARKER_LON/LAT`) + `recenterMapTo`로 전환해 죽은 run leftover의
  supercluster 병합(marker aria-label 소실, P2)을 제거. base `LON`/`LAT`는 127.5/36.5 고정 유지
  (weather/price/correction/search는 seeding helper `admin_feature_live_fixture.py` `_LON`/`_LAT` 고정과
  좌표 동기 필요 — featureId/query 단언이라 supercluster 무관).
  - **경과**: #855(shared base jitter, merged) → **n150 c7-v6 live 검증에서 weather/price seeding desync
    발견**(공식 runner latent bug: helper 고정 seed vs spec jitter 조회) → #859에서 **status-only jitter로
    국한 수정**(rebase over #858, merged `baa04c08`).
  - **검증**: n150 c7-v6 live(map=c8ed6164/pinvi=6a035695) status marker 단계 통과(recenter 실증) +
    e2e type-check + 4각도 적대 정적검증. weather/price는 고정 base = LIVE-01 통과 baseline이라 무변경
    (full official-lane 재검증 불필요 — behavioral 변경은 status marker에 국한). cleanup featureId 기반이라
    leftover 0.
  - **교훈**(journal 2026-07-27): 정적 적대검증이 이 회귀를 놓친 이유 = 외부 Python seeding helper의 좌표
    계약을 정적 모델에 못 넣음. cross-process 좌표 계약은 live 검증 필요.

## 2026-07-27 — T-VN-H17 map#684 조건 #8 검증범위 축소 후 종결 (LIVE-01 후속 7/7 close)

- [x] **T-VN-H17** — H16에서 keep-open된 map#684를 **조건 #8 검증범위 명시 축소**로 종결(사용자 결정:
  조건 축소). #684 조건 1~7 + owner 후속은 코드+mock+live로 충족. 조건 #8("mock e2e와 n150 live e2e에서
  검증")을 다음으로 확정: **live(n150)** = read/freshness/URL-복원/invalid-fail-closed
  (`ops-c7-read-auth.live.spec.ts`) + datasets **write 계약**(effective-scope refresh POST·active projection·
  reused_active_request, `ops-c7-kma-active-write.live.spec.ts`, T-ADM-C7 GREEN); **mock** = write-path
  **UI 엣지 전이 2건**(refresh done-terminal freshness invalidation `ops-datasets.spec.ts:1817`,
  polling 404/503 재시도 `:2440`). 근거: 반복 done-terminal은 prod Dagster refresh quota 소모 파괴적,
  404/503은 prod 인위 유발 곤란한 client-state 엣지 — write **계약**은 이미 C7 live 실증이라 UI 엣지는
  mock 적정. map#684 close. → **LIVE-01 후속 OPEN 7건 전부 종결**.

## 2026-07-27 — T-VN-H16 LIVE-01 후속 OPEN 이슈 7건 재검증 → 6 close / 1 keep

- [x] **T-VN-H16** — LIVE-01 후속 OPEN 7건의 독립 완료조건을 현재 main/배포·smoke 증거로 재검증
  (이슈당 1 에이전트 병렬 + 회의적 기본값). **6건 close, 1건 keep-open**:
  - **close**: `dm#70`(features routes 플래그 compose 명시, C6c smoke 교차확인) · `dm#63`(prod API env
    결선 PR #64, creds SET) · `map#777`(C7 attestation manifest v4 exact 강제 `c7_prod_attestation.py:423`) ·
    `map#712`(datasets fail-closed S2 active projection + 회귀 테스트 + C7 n150 live) · `map#719`(exact-scope
    이력 PR #728 filter-before-limit + continuation) · `map#694`(live E2E 의미 단언, PR #724 결함 surface 제거).
    각 이슈에 근거(file:line/PR/smoke) 포함 종결 코멘트 게재.
  - **keep-open**: `map#684` — 조건 1~7 충족이나 조건 #8의 write-path **live** 전이 2건(refresh done-terminal
    freshness invalidation·execution polling 404/503 재시도 UI)이 mock e2e에만 존재, n150 live lane 미구동
    → `T-VN-H17`로 잔여 구체화.

## 2026-07-27 — principal 경계 부분 실증 + PinVi #392 종결

- [x] **PinVi #392 observation-read principal** — PinVi 관측 caller가 ops:read로 200에 도달하고
  no-token은 401로 거부됨을 production에서 직접 실증했다. 배포=**map c8ed6164 / pinvi 6a035695**
  (둘 다 healthy, production profile).
- **부분 증거(T-VN-03/T-ADM-C6c 전체 완료 아님)**: 실행한 경계 smoke 13건은 모두 PASS했다.
  - curated: C1 keyless→401 · C3 service→200 · C4 admin-bff→200 · C4n secret-no-actor→401.
    C2 public-key→200은 DB lookup·hash compare 양성 runtime 분기를 직접 실행하지 않았으므로 미검증이다.
  - ops 6: O1 keyless→401 · O2 service-only→401 · O3 cancel-token→403 · O4 admin-bff→200 ·
    O5 ops:read→200 · O6 invalid→403.
  - MOIS: M1 production unmount→404.
  - 배포 전 정적 감사(워크플로우 `tvn03-c6c-readiness-audit`, 6차원 병렬+적대 반증): route policy
    exception 0, curated/ops/MOIS wiring, OpenAPI full/user 계약 일치 확인.
  - 증거: [t-vn-03-c6c-boundary-smoke-2026-07-27.md](reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md).
  - C2는 열린 `T-VN-H19`에서 credential-safe 임시 key로 직접 실증한다. 그 전까지
    T-VN-03/T-ADM-C6c를 완료로 이관하지 않는다.

## 2026-07-27 — Lane B b0 T-VN-43 admin frontend npm 보안 0건 전환

- [x] **T-VN-43 (#851, merge `d0e7077ffb0cee4139997b8143371b1418bfd784`)** — clean npm audit의
  low 2·moderate 7·high 7을 모두 제거하고 Node/npm·Next/PostCSS/Sharp·Playwright를 exact pin했다.
  사용하지 않는 shadcn CLI/MCP·form graph를 제거하고 npm tree/effective ESLint/Redocly patch/실제
  Next-Sharp optimizer를 fail-close gate로 고정했다. Python 2,355 tests와 frontend type/build/Vitest,
  격리 Docker mocked 24/24, 운영 API에 연결한 공식 CSV 5종 파괴적 Live UI 4/4를 n150에서 통과했다.
  #840 이후 Claude PR 전문 감사 1명과 독립 적대 리뷰어 2명의 최종 finding은 P0~P3 0건이었다. 상세
  `docs/journal.md` 2026-07-27(codex).

## 2026-07-27 — T-VN-H06 admin 목록 keyset 런타임 검증 완결

- [x] **T-VN-H06** — admin dedup/enrichment 목록을 OFFSET → keyset+fingerprint cursor로 전환.
  - **backend**(#813, merge `9d29606e`): `admin_feature_repo.py` keyset 술어
    `(total_score, review_id) < (:cursor_score::numeric, :cursor_review_id::uuid)`,
    `_REVIEW_CURSOR_VERSION` fingerprint, composite index `idx_dedup_status_score`/
    `idx_enrichment_review_status_score`. 2차 적대 리뷰 P3 반영(가변 score 재스캔 재정렬 tradeoff
    docstring + active-cursor EXPLAIN 케이스 `test_t212d_perf_explain.py`, seq-scan 회귀 가드).
    CI `pytest integration (PostGIS)` green.
  - **e2e 검증**(#852 + 후속 Codex 보강): 현행 UI에 맞춘 spec drift 수정에 더해 네 deferred filter의
    원자적 수렴과 decision PATCH의 `reviewed_by` 비전송을 전 경로에서 음성 단언했다. n150 Linux
    Playwright에서 dedup 14 + enrichment 9 + auth setup 1, 합계 **24/24**를 통과해 기존 Windows-only
    증거를 대체했다. network-mocked 목록 검증이라 task의 파괴적 live 예외를 적용하며, keyset 실백엔드
    동작은 #813의 pytest integration(PostGIS) EXPLAIN 가드가 커버한다.

## 2026-07-27 — T-VN-LIVE-01 targeted live acceptance lane n150 PASSED (04A/58/15 종결)

- [x] **T-VN-LIVE-01 (+T-VN-04A #741·T-VN-58 #785·T-VN-15)** — targeted admin-feature live
  acceptance lane(#792 구현)을 n150 production(map=c8ed6164/pinvi=6a035695)에서 파괴적 실행 →
  **PASSED**(rc=0, phase=passed, recovery_attempt=0, BLOCKED/ACTIVE 없음, active leftover 0).
  검증 범위: inactive/draft/hidden marker + hidden weather/price 카드 + public 비누출 + T-VN-15
  search total/continuation/CURSOR_QUERY_MISMATCH·FEATURE_SEARCH_CURSOR_TAMPERED 422 + #785 stale
  raw If-Match 412·dirty draft 보존·명시적 reload. **규명·수정 연쇄**(비-redact c7-v6 재현):
  helper host-network(#842) · map nav/zoom-contract·panel(#843) · Codex PR 리뷰 DSN/signal(#844) ·
  검색 pg_trgm 격리 32-hex(#845) · kind=place 격리(#848, cross-kind seed weather cluster). 인시던트
  복구(공유 pinvi DB migration → manifest trap) 후 c8ed6164로 재-cut. issue #741·#785 closed.
  적대 리뷰어 2명 반영(#848 P3 정정·P2→T-VN-H12 추적). 상세 `docs/journal.md` 2026-07-27.

## 2026-07-27 — Lane B b0 T-VN-42 지도 control·query identity·live recovery 하드닝

- [x] **T-VN-42 (#846)** — `/features`·`/curated-features` 상세 패널의 bottom-right `ScaleControl`
  비겹침 계약(공용 Playwright bounding-box assertion), live 전역 `reducedMotion` 제거 후 MapLibre
  `moveend`까지 클릭마다 대기하는 zoom helper, items/clusters in-bounds query key를 HTTP와 동일한
  정수 zoom·원본 bbox·명시적 mode로 통일, 서버 정수 zoom 기준과 UI cluster/items 분기 단일 함수화.
  #840 이후 Claude Code PR(#841~#845) 재감사로 #844 BLOCKED clear 신호 경쟁과 #845 cross-version
  recovery 가능성을 BLOCKED v3(source commit·API/Playwright image·pair·attestation hash 기록 +
  recovery runtime exact 대조로 mutation 전 cross-version cleanup 거부) 계약으로 차단. 상세
  `docs/journal.md` 2026-07-26(codex).

## 2026-07-26 전면 감사 정리 — C7 종결 + vNext Wave 0/1 합류 + 독립 하드닝 + Wave 3 측정

11-agent 전수 감사(2026-07-26)로 실코드 기준 완료 확정한 항목. C7 COMPLETE @ d5693269
(공식 6-spec prod gate full GREEN, `docs/journal.md` 2026-07-26).
- [x] **T-VN-08 — PinVi false-broken 수정** — PinVi PR #409(merge `423a8a3`): 외부 Feature
  해석을 `found|missing|unverified|not_linked`로 분리하고 transport·typed Map 실패는 마지막 snapshot을
  유지하는 `unverified`로 처리했다. opaque feature ID를 그대로 strict batch 계약에 전달해 구분자
  parsing을 제거했다. n150 실데이터 파괴적 live UI E2E는 web Map popup의 연결 장애→복구를
  검증했고, mobile 소비자는 TypeScript/type-check로 계약을 검증했다. 적대 리뷰어 2명 P0/P1/P2
  없음, CI 6-check green 후 squash merge. 5-state producer 계약은 별도 `T-VN-11`로 계속한다.

- [x] **T-ADM-C7-SCHEDCHURN** — 근인은 render churn이 아니라(오진), cron 저장 응답 유실 후
  frozen-idempotency 복구가 필요해질 때 cron 수정 dialog(Base UI)가 열린 채 남아 페이지 전체가
  inert가 되어 모든 schedule 컨트롤이 접근 불가가 되던 것. fix=`schedule-panel.tsx`(복구 필요
  순간 dialog close) + spec 하드닝(canReset·robustClick·settle-gate·시작 confirm alertdialog
  locator). 적대 리뷰어 2명 반영 → prod 재배포 후 재검증 GREEN → schedule-write blocking gate
  재편입. PR #838. 상세 `docs/journal.md` 2026-07-26.
- [x] **T-ADM-C7-POICAUSAL** — C7 게이트가 항상 poi-cache `@c7-causal`에서 red였던 원인은
  backend가 아니라 test-side 2중 버그: (1) `POI_HEADING` 영문 상수가 개편 B(`d8818994`) 한국어
  h1 통일 이후 stale → `gotoPoiTargets` 15s timeout; (2) `expectCausalDatasetProjectionUpdate`의
  `page.evaluate` 콜백 `connectionId` destructure 누락 → 상시 `ReferenceError`(cbe133c2 이래,
  heading 버그가 가림). PR #839(main d5693269) → 재-cut → 공식 게이트 full GREEN(6 spec 전부
  passed). **C7 COMPLETE at d5693269.**
- [x] **T-VN-SYNC-02 — integration/t-vn → main 최종 합류** — PR #790(2026-07-19, merge commit
  d93cb16e, base=main/head=integration/t-vn ancestry 보존, CI 8-check green). T-VN-57(#787) 선행
  머지 gate 준수. compatible-pair v4 activation은 2026-07-26 C7 재-cut으로 완결(map=d5693269 /
  pinvi=e60d1711, attestation self-verify PASS, 공식 6-spec gate GREEN). `integration/t-vn`
  통합 브랜치 규율은 본 합류로 폐지(이후 base=main).
- [x] **T-VN-57 — public route policy·OpenAPI security·user surface 단일 정본** (#784 closed) —
  PR #787: `_PUBLIC_CURATED_PATHS`/`USER_OPERATIONS` 수기 정본 제거, `build_route_policy_matrix`
  단일 정본화, runtime↔full↔user 양방향 전수 대조 CI(`test_export_openapi.py` — drift는
  ValueError로 거부), PUBLIC_KEYED=[PublicApiKey,ServiceToken]/PUBLIC_UNAUTHENTICATED=[]/
  SERVICE=[ServiceToken] 정확 선언, user-client TS 재생성.
- [x] **T-VN-59 — public weather·curation raw lineage 계약 분리** (#786 closed) — PR #788:
  public/operator DTO 분리(`PublicWeatherAlertHistoryItem` vs `AdminWeatherAlertHistoryItem`,
  `PublicCurationItemView` vs `AdminCurationItemView` — 상속 없음), user OpenAPI 재귀
  reachable-schema 금지 게이트(`USER_RESPONSE_FORBIDDEN_PROPERTIES` fail-closed, cycle/allOf/
  oneOf negative 테스트 포함), 수기 public curation client 동시 갱신.
- [x] **T-VN-H02R — standalone destructive fail-close·backup principal 감사 완결** (#796
  closed 2026-07-26) — PR #804 + companion docker-manager #68: compose 기본
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED:-false`, backup create/delete/restore/swap actor =
  `AdminProxyContext.actor`만, `RestoreSwapRequest.operator` 제거(+422 회귀), principal별
  registry 이벤트·resolved-compose default false/explicit true 회귀. migration 없음(요구대로).
- [x] **T-VN-H03R — route wiring startup gate·public CORS exact preflight 완결** (#798 closed) —
  PR #803: `create_app()`에서 `assert_route_policy_wiring()` fail-closed, `PUBLIC_CORS_REQUEST_HEADERS`
  닫힌 allowlist(CORS safelist + If-None-Match + X-Kor-Travel-Map-Api-Key), route별 exact-method
  CORS, 비허용 preflight 400 + ACAO 미방출, `KNOWN_WIRING_EXCEPTIONS == ()` 회귀.
- [x] **T-VN-H08 — Tier-2 p95 nearest-rank 산식 정확화** (#799 closed) — PR #801:
  `_nearest_rank_percentile` = `sorted(values)[ceil(p×n)-1]` 공용 helper(실행시간·shared read
  blocks 공용), n=1/20/30/100 fixture로 index·값 고정. release evidence 재생성은 이전 evidence가
  존재하지 않아 vacuous — 실제 1M+ 실분포 측정은 cutover(T-VN-39) 시 release 리포트로 수행.
- [x] **T-VN-H09 — weather semantic upsert collected_at 단조성** (#797 closed) — PR #802:
  `weather_repo.py` upsert `WHERE EXCLUDED.collected_at >= … AND ROW(…) IS DISTINCT FROM ROW(…)`
  (ADR-072 0060 승자 규칙 정합), current-row 선택 근거 ADR-072에 기록, NULL(비허용)/동률(내용
  다르면 later-write wins)/no-op(동일 replay 물리 UPDATE 없음) 정책 문서화, T1→T2/T2→T1/동률/
  backfill 통합 회귀.
- [x] **T-VN-51~56 — Wave 3 도입-조건 측정** — PR #816: 여섯 확장 후보(MVT/범용 batch/cursor
  rotation/weather partition·hypertable/물리 listener/대규모 fixture 주기) 전부 측정·판정 완료.
  T-VN-51~55는 명시 트리거로 유예, T-VN-56은 현행 2계층(per-PR tier-1 + release tier-2) 확정.
  정본 `performance.md` §8.4 + `reports/t-vn-51-56-adoption-measurement-2026-07-21.md`.

## C7 prod-live 게이트 확정 · schedule-write descope (2026-07-26, `T-ADM-C7`·`T-ADM-C7RUN`)

- [x] **T-ADM-C7 — live e2e 재작성 + n150 prod-live 검증 완결.** C7 prod-live 게이트를
  **read-auth·kma-active-write·kma-empty-write·kma-cap-write 4-spec**로 확정(green)하고 n150
  production에 대해 파괴적 live로 실행했다(현 prod: cron=20, RUNNING; 실행 부수효과 2건 복구 완료).
  WS 인증 close saga(C7W/X/Y/Z, read-auth 7/7), kma-write 계약(C7PV/C7PW), detail perf·running-race
  (#829)까지 실 코드 blocker를 모두 해결·머지했다. `ops-c7-schedule-write`는 app-side render churn
  때문에 blocking gate에서 **descope**했다(후속 열린 task `T-ADM-C7-SCHEDCHURN`). Map PR #837 +
  docker-manager PR #74 squash-merge. 상세: `docs/journal.md` 2026-07-26.
- [x] **T-ADM-C7RUN — 공식 러너 GREEN 확정 (2026-07-26 CLOSED).** "외부 data.go.kr KMA 502가 유일
  blocker" 진단은 폐기(오류)됐고, verbose-iterate(non-redacting reporter + browserFetch DIAG 계측)로
  masked blocker를 순차 규명·수정했다: preview provider_dataset 노출(#824), create-body `update_policy`
  과명세(#825), detail `/v1/ops/datasets/detail` O(roots²) timeout recency-bound(#828/#829),
  running-race fast-completion tolerate(#829), root_id lineage(#834), gate restructure(#835),
  empty-write queue-sensor UI-gate flake 하드닝(#837). 후반 flaky UI/timing까지 통과 확정. Map PR #837
  + docker-manager PR #74 머지.

## C7 kma-write live 계약 수정 (2026-07-22~23, `T-ADM-C7PV`·`T-ADM-C7PW`)

- [x] **T-ADM-C7PV — kma-active-write preview provider_dataset WYSIWYG(sync_scope)** (PR #824) —
  preview가 0-feature dataset(`kma_ultra_short_nowcast`)에서 `matched_scope.provider_datasets`를
  생략해 C7 `assertExactKmaPreviewBody`가 throw + 다음 UI `toContainText(sync_scope)`도 실패했다.
  `scope_repo` provider_dataset 브랜치가 요청 pair를 0-feature 포함 항상, 요청 `sync_scope`와 함께
  노출하도록 executor `_provider_dataset_scopes`와 parity를 맞췄다. verbose-iterate live harness로 검증.
- [x] **T-ADM-C7PW — kma-active-write create-body update_policy 테스트 과-명세** (PR #825) —
  UI는 create body에 `update_policy`를 안 보내는데(계약상 optional, absent≡{}) 테스트가 `{}` 기대 →
  `_ops-c7-admin-api.ts` `buildKmaRequest`의 `update_policy: {},` 삭제. clean v6 harness가
  kma-active-write 전 flow(create→run-now→terminal→grids→fingerprint→overflow×49) 통과 검증(2 passed).

## C7 ops-live WS 인증 close saga (2026-07-20~22, `T-ADM-C7W`·`T-ADM-C7X`·`T-ADM-C7Y`·`T-ADM-C7Z`·`T-VN-H11`)

- [x] **T-ADM-C7W — Chromium ops-live 인증 거절 close code 4401 복구** (#806 closed · PR #807) —
  변조된 subprotocol을 제시한 실제 Chromium이 handshake 실패 `1006` 대신 application close `4401`을
  관측하도록 transport-level subprotocol selector를 두고, 인증·nonce·application loop 미진입 상태로
  data frame 없이 `4401` close. selector 없음/단일/복수/길이초과 회귀 고정.
- [x] **T-ADM-C7X — ops-live subscribe-after-hello로 만료 ticket 4408 clean 전달** (#817 closed · PR #818).
- [x] **T-ADM-C7Y — ops-live reject-close accept↔close settle env-tunable 0.25s** (PR #821).
- [x] **T-ADM-C7Z — C7 live e2e 복구-leg passthrough를 route.continue로 (Sec-Fetch 보존)** (PR #823).
- [x] **T-VN-H11 — ops-live 인증 close의 proxy 전달 경계 분리** (#809 closed · PR #807/#810) —
  Uvicorn accept 101과 close frame coalescing에 대해 accept 성공 뒤 bounded settle window(배포 조합
  한정 best-effort)와 accept~close 단일 bounded child task 보호를 두었다. 위 4개 WS auth saga와 함께
  공식 러너 `ops-c7-read-auth` 7/7 통과로 검증. 별건 HAProxy WS 백엔드 `timeout tunnel` 미설정
  운영버그는 issue #819로 분리 등록.

## C7 manifest v4 provenance · PostGIS topology check 오탐 (2026-07-19, `T-ADM-C7P`·`T-ADM-C7F`)

- [x] **T-ADM-C7P — C6c manifest v4·Map 4-image C7 provenance 동기화** (issue #777 · PR #778,
  `d2104f15`) — compatible-pair manifest를 v4로 clean-cut하고 active/rollback pair에 Map API·UI·
  Dagster web·daemon 네 immutable image ID와 하나의 Map source revision을 결박했다. C7 attestation이
  네 Map image ID를 실제 compose runtime role과 각각 exact 비교하고, manager manifest v3는 거부한다.
  2026-07-26 C7 prod-live 게이트 green(runtime attestation 통과)으로 활성 검증됨.
- [x] **T-ADM-C7F — prod PostGIS topology 객체의 Alembic check 오탐 제거** (PR #791, `6fa914c2`) —
  shared Postgres infra owner의 `postgis_topology`(`topology.layer`·`topology.topology`)를
  `include_schemas=True` autogenerate가 삭제 대상으로 오인하던 `alembic check` 오탐을, extension-owned
  객체만 명시 제외하고 head migration 뒤 topology extension을 설치한 production-equivalent integration
  gate로 함께 고정했다.

## vNext 독립 하드닝 — public API key header 전환 (2026-07-20, `T-VN-H01`, integration/t-vn)

- [x] **T-VN-H01 public API key를 URL query에서 header로 이동** (#794) — 공개 REST API key를
  `?key=` 쿼리에서 clean-cut하고 `X-Kor-Travel-Map-Api-Key` 헤더로만 받는다(access log·Referer
  유출 차단, breaking change). OpenAPI `PublicApiKey` security scheme을 apiKey-in-header로 바꾸고
  `openapi.json`/`openapi.user.json`과 admin·user-client `types.ts`를 재생성했다. route policy
  분류(PUBLIC_KEYED)는 불변. PinVi·admin consumer는 헤더 전송으로 전환해야 한다(cross-repo
  coordination — T-VN-20 PinVi 패턴).

## destructive admin 기본값 fail-closed (2026-07-20, `T-VN-H02`)

- [x] **T-VN-H02 — destructive admin 기본값 fail-closed.** `admin_destructive_enabled`
  기본값을 `True`→`False`(fail-closed)로 내리고, 문서화된 env alias
  `KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED`가 실제로 바인딩되도록 `validation_alias`를 추가했다.
  Docker compose는 컨테이너 기본 true를 주입해 기존 배포를 유지한다(배포 전제: 파괴적 작업이
  필요한 배포는 host env로 이 값을 유지). PR #793.
  이후 standalone compose까지 default false로 닫는 `T-VN-H02R`(#796)이 이 배포 예외를
  clean-cut으로 대체한다.

## surface별 CORS 분리 (2026-07-20, `T-VN-H03`)

- [x] **T-VN-H03 — surface별 CORS를 표면 정책으로 분리.** route policy matrix(T-VN-02)의
  분류를 재사용해 browser-facing public 표면(public-unauthenticated·public-keyed)에만 CORS를
  적용하고, service(server-to-server token)·operator(admin BFF same-origin proxy)·metrics·debug
  표면은 `Access-Control-Allow-Origin`을 내보내지 않는다. app-global `CORSMiddleware`를 route
  policy로 게이트하는 표면 범위 미들웨어(`kortravelmap.api.cors.SurfaceScopedCORSMiddleware`)로
  구현했고, 경로 판정은 비-public 매칭 시 무조건 제외하는 security-safe 규칙을 쓴다. CORS는
  미들웨어라 OpenAPI spec 무관(drift 없음). PR #795.

## coord_5179 PROJ pin · INVALID index 복구 runbook (2026-07-20, `T-VN-H04`·`T-VN-H05`)

- [x] **T-VN-H04 — `coord_5179` PROJ 버전 고정·drift 검사·REINDEX runbook.** `docs/runbooks/coord-5179-proj-pin.md` 추가 — PROJ-bound STORED generated 컬럼의 drift 탐지 SQL(저장 `coord_5179` vs 현재 PROJ `ST_Transform(coord,5179)` 비교), `SET coord=coord` keyset batch 재계산, `REINDEX INDEX CONCURRENTLY idx_features_coord_5179_gist`. image tag `postgis/postgis:16-3.5-alpine`가 PROJ를 pin. performance.md §7.1·postgres-schema.md §4.1·runbooks README에서 링크. SQL은 postgis 16-3.5 컨테이너로 검증. PR #800.
- [x] **T-VN-H05 — CONCURRENTLY 실패 INVALID index 탐지·drop runbook.** `docs/runbooks/invalid-index-recovery.md` 추가 — `pg_index.indisvalid=false` 탐지 SQL(pg_class/pg_namespace join으로 index·table 이름), `DROP INDEX CONCURRENTLY IF EXISTS` + 원 DDL 재실행, 0061 self-heal·0060 non-concurrent 원자성 맥락. performance.md §8.3(§6.6 dangling ref 대체)·postgres-schema.md §8.2·runbooks README에서 링크. SQL은 postgis 16-3.5 컨테이너로 검증. PR #800.

## vNext main 동기화 (2026-07-20, `T-VN-SYNC-01`)

- [x] **T-VN-SYNC-01 — latest main을 integration/t-vn에 동기화.**
  `main@d2104f15`를 `integration/t-vn@22bf35a5` 위 전용 branch에서 merge하고, 양쪽 문서 이력,
  API image OCI revision label과 production profile, 완료/미완 task 정본을 함께 보존했다.
- [x] **migration과 CI 계약 확인.** Alembic `0058 → 0059 → 0060 → 0061 → 0062` 단일 chain을
  유지했고 lint, OpenAPI drift, Python 3.11/3.12/3.13, fixture replay, PostGIS integration,
  frontend type-check/build의 CI 8개를 모두 통과했다.
- [x] **PR #781 병합 완료.** PR head `aa976f13ae747d75fe67318d9c41fb2bddfddb04`를 merge commit
  `a45bc3ac401e5675811f1031a4592991498d899f`로 `integration/t-vn`에 반영했다. 이후 최종
  integration→main 합류는 열린 `T-VN-SYNC-02`가 담당한다.

## C7 prod runner attestation·복구 경계 (2026-07-19, `T-ADM-C7H`)

- [x] **T-ADM-C7H — 파괴적 live 실행 전 runtime을 exact attestation에 결박.** C6c compatible-pair,
  clean source commit과 OCI revision, Map API/UI/Dagster web·daemon/PinVi API의 실제
  image·command·environment, compose project, 단일 Alembic head/check, UI login을 read-only로
  대조한 뒤에만 `BLOCKED.json`과 mutation journal을 만든다.
- [x] **root 실행 파일과 복구 증거를 fail-closed로 고정.** runner/helper/attestation 모듈/상태
  감사기 네 파일을 exact Git archive와 root-owned SHA-256에 묶었다. 실패·signal 경로는
  runtime/journal/sentinel을 보존하고 INT/TERM은 130/143으로 종료한다. Playwright container는
  bridge/private IPC, durable creator/outcome/CID와 별도 검증형 stop 도구만 사용한다.
- [x] **단일 적대 리뷰와 실행형 gate 완료.** 최종 P0~P3 잔여 없음 판정 뒤 C7 대상 55건,
  전체 unit 1,529건, Ruff, strict mypy, import 계약, exact-commit immutable executor build를
  통과했다. PR #754와 보안 후속 PR #762는 각각 CI 8개가 모두 성공한 뒤 merge commit
  `b9f23a42`, `bece2c32`로 `main`에 반영됐다. 실제 배포·파괴적 browser 증거는 열린
  `T-ADM-C7` n150 gate가 담당한다.

## C7 mocked UI projection·pagination 수용 증거 (2026-07-19, `T-ADM-C7M`)

- [x] **T-ADM-C7M — datasets summary를 이름 있는 영역의 exact projection으로 검증.**
  `/ops/datasets` mocked E2E는 행·실패·SLA 초과·미실행·이슈 요약을 summary landmark 안에서
  검증한다. 같은 문자열로 표 행을 오염해도 summary 영역에 잘못 투영되지 않는 negative fixture를
  포함해 페이지 전역 문자열 검색으로 생기는 거짓 양성을 차단했다.
- [x] **pipeline continuation의 요청·응답·DOM 경계를 함께 고정.** 실행과 전역 event를 각각
  6+6 두 페이지로 주입하고 exact provider/dataset/scope/page size와 null/expected cursor 요청,
  페이지별 전체 DOM identity 배열, 전체 정렬, 페이지 간 서로소와 마지막 continuation 종료를
  검증한다.
- [x] **mock 증거와 live 수용 범위를 분리.** 6+6 fixture는 `page_size=50`의 실제 overflow가 아니라
  cursor plumbing 증거다. canonical page size를 넘는 51건 이상의 실제 continuation은 열린
  `T-ADM-C7` n150 live E2E가 담당한다.
- [x] **PR #755 병합 완료.** 단일 적대적 리뷰의 query-scope 지적을 exact validator와 cursor 관측
  검증으로 반영한 뒤 targeted mocked E2E 3건을 통과했다. 문구·fixture 설명 후속까지 포함한
  PR #755는 CI 8개 게이트가 모두 통과한 뒤 merge commit `54150c91`로 `main`에 반영됐다.

## vNext 재설계 Wave 0~1 (2026-07-19, `T-VN-*`, integration/t-vn)

> C7 종결 전까지 `integration/t-vn` 통합 브랜치에 누적. 각 task는 적대 리뷰(실전 결함 반영)
> + GitHub CI + n150 CI-parity 게이트를 거쳐 병합. 세부는 각 PR diff와 journal.

- [x] **T-VN-01 production fail-closed** (#740) — production profile secret 누락 시 기동 거부.
- [x] **T-VN-02 route policy matrix + 미분류 CI gate + /metrics 경계** (#747, +#742 수렴).
- [x] **T-VN-04 공개 predicate 단일화** (#743) — `feature.public_features` view, F-1 양방향 봉인.
- [x] **T-VN-05 raw payload 경계 제거** (#752) — 공개 DTO raw/lineage를 operator 표면으로.
- [x] **T-VN-06 notice 방어적 cast** (#746) — 오염 timestamp의 공개 read 500 차단.
- [x] **T-VN-07 no-op 옵션 삭제 + actor principal 1차** (#748).
- [x] **T-VN-13 Feature row_revision + If-Match/ETag** (#772, 리뷰 후속 #776) — 낙관적 동시성(428/412/304).
- [x] **T-VN-14 지도 completeness + exact ST_Intersects** (#763) — mode/truncated/coverage.
- [x] **T-VN-17 weather 무결성 제약** (#756) — semantic UNIQUE와 writer cutover 기반 도입.
- [x] **T-VN-18 중복 GiST 제거 + BRIN 감사** (#759) — write 1.2~1.3x 개선 실측.
- [x] **T-VN-19 Alembic metadata 정합 CI** (#753) — 빈 DB upgrade→check 게이트.
- [x] **T-VN-20 principal actor 전면 전환** (#757) — body actor 위조 경로 제거.
- [x] **T-VN-21 3단 성능 gate** (#760) — planner-default EXPLAIN·N+1·shape 회귀.
- codex 후속 병합: #745(curation), #749(metrics), #750(beach doc), #751(manual-link, main).

## vNext 적대 리뷰 후속 (2026-07-19, `T-VN-*R`, integration/t-vn)

- [x] **T-VN-05R public curated raw lineage 우회 차단** (#774, issue #765) — 공개 전용
  allowlist DTO/projection과 strict kind별 detail로 admin raw 계약과 공개 계약을 분리했다.
- [x] **T-VN-14R cluster/items exact 후보집합 단일화** (#773, issue #768) — PR #763 후속으로
  교차 geometry의 cluster count/items universe와 canonical 행정코드 귀속을 일치시켰다.
- [x] **T-VN-17R weather UNIQUE writer race 봉인** (#771, issue #766) — migration 0060을
  transactional non-concurrent UNIQUE cutover로 정정해 dedup과 writer fence를 원자화했다.
- [x] **T-VN-21R release benchmark 측정 정확성** (#775, issue #767) — 실제 public batch
  cardinality, matched/returned 구분과 top-level shared read 단일 합산을 고정했다.

## POI target causal receipt·조건부 삭제 (2026-07-18, `T-ADM-C7C`)

- [x] **T-ADM-C7C — mutation과 live invalidation을 transaction-coupled receipt로 결박.** POI target
  PUT/DELETE는 원본 transaction에서 증가한 `dataset_projection_revision`을 반환한다. C7 live
  E2E는 같은 기존 socket의 새 update frame에서 `live_revision >= receipt`만 causal 증거로 인정하며
  snapshot·top-level fingerprint revision은 제외한다.
- [x] **server-owned version과 exact `If-Match`로 재생성 경쟁을 차단.** Alembic 0058의 양수
  BIGINT `lock_version` trigger와 target UUID로 strong `ETag`/body `entity_tag`를 만든다. DELETE는
  누락 `428`, weak·wildcard·결합/중복/malformed `422`, stale UUID/version `412`, 실제 부재 `404`를
  구분하고 active natural-key row lock 뒤 UUID+version이 모두 같은 행만 soft-delete한다.
- [x] **parent→link lock order와 UI retry를 완결.** executor는 모든 active parent를 UUID 순서로
  `FOR KEY SHARE` 잠근 뒤 link를 교체한다. UI/BFF는 `If-Match`/`ETag`를 보존하고 stale `412`에서
  list·nearby·datasets·pipeline을 refetch해 같은 target UUID의 최신 tag로만 재시도한다.
- [x] **적대 리뷰·로컬 gate 완료.** 두 독립 리뷰어가 최종 기능 diff를 승인했다. root unit
  1,435건, API 520건, 실제 PostgreSQL migration/up-down·2-session 경쟁 8건, frontend unit
  212건, mocked POI E2E 10건을 통과했다. Ruff, strict mypy 115+52파일, import 계약 4/4,
  admin/user OpenAPI·생성 타입 drift, type-check·lint(오류 0)와 31-route production build도 green이다.
  실제 same-socket causal 증거와 destructive cleanup은 최종 `T-ADM-C7` n150 live E2E에서 수행한다.

## Admin exact-scope 조작·이력 UI 소비 (2026-07-18, `T-ADM-C7B-UI`)

- [x] **T-ADM-C7B-UI — exact provider/dataset/scope를 조작과 이력의 단일 정본으로 소비.**
  `/ops/datasets`는 잘못되거나 사라진 dataset/scope deep link를 다른 행으로 폴백하지 않고
  fail-closed한다. provider-only URL은 실제 선택 tuple로 canonicalize한 뒤에만 갱신·정책
  mutation을 허용한다.
- [x] **활성 실행·최근 종료·이력 continuation을 독립 표시.** `active_execution`과 최근 terminal
  `latest_execution`을 분리하고, exact scope의 `run_history`·`event_history`와 서버가 반환한
  `canonical_url`을 그대로 사용한다. scope 전환 중 정책 draft를 보존하며 orphan 또는
  `mutable=false` 행은 draft를 표시하되 저장을 차단한다.
- [x] **pipeline filter를 URL controlled state로 완결.** provider/dataset tuple이 불완전해지거나
  상위 축이 바뀌면 stale dataset/scope와 cursor를 같은 전이에서 제거한다. browser
  Back/Forward도 exact filter state에 반영하며 dataset-wide capability에는 명시적
  `sync_scope` 입력을 막고 서버 정규화에 맡긴다.
- [x] **적대 리뷰와 frontend gate 완료.** 독립 리뷰어 2인이 P0/P1/P2/P3 잔여 0건으로 승인했다.
  Vitest 26 files·210 tests, 앱·E2E type-check, lint 오류 0건과 31-route production build를
  통과했다. Playwright와 issue #712/#719 종결은 최종 `T-ADM-C7` n150 live E2E에 남긴다.

## Admin active projection·exact-scope 이력 API (2026-07-18, `T-ADM-C7B-API`)

- [x] **T-ADM-C7B-API — 활성 실행과 마지막 종료 실행을 독립 projection으로 완결.**
  datasets grid/detail은 같은 DB statement snapshot에서 exact
  `(provider,dataset_key,sync_scope)`별 queued/running `active_execution`과 최근 terminal
  `latest_execution`을 각각 선택한다. 논리 `dataset_wide`는 typed scope와 과거 NULL scope를
  같은 total order로 비교하고, `target_grids`·`external_system:*`에는 unscoped 실행을 추측하지
  않는다.
- [x] **Alembic 0057로 event identity와 exact-scope access path를 고정.** visible event의
  provider/dataset을 immutable owning job에서 복구하고 canonical direct update event에만 typed
  `sync_scope`를 backfill한다. INSERT trigger와 check constraint가 owner pair/scope를
  복사·불변화하며, `(provider,dataset_key,sync_scope,occurred_at DESC,event_id DESC)` partial
  index가 scope 조건을 cursor·`ORDER BY`·`LIMIT` 전에 적용한다. provider namespace 밖에서 의미가
  없는 dataset-only event filter는 REST/repository에서 `422`/`ValueError`로 거부하고, 읽기 경로가
  사라진 `idx_import_job_events_dataset_time`은 제거했다.
- [x] **실행·event continuation 계약을 typed cursor로 완결.** dataset detail은 `run_history`와
  `event_history`를 각각 `{items,next_cursor,canonical_url}`로 반환하고 pipeline 목록·event stream도
  같은 canonical URL을 사용한다. run/event cursor는 전체 filter fingerprint에 묶어 다른
  job/level/provider/dataset/scope에서 재사용하면 DB 조회 전에 typed `422`로 닫고, strict parser가
  거부하는 scope와 불완전한 provider/dataset tuple도 fail-closed한다.
- [x] **적대 리뷰와 로컬 gate 완료.** DB/API 적대 리뷰어 2인이 테스트 전에 최종 변경을 검토해
  P0/P1/P2/P3 잔여 0건으로 승인했다. migration 0057·수정 EXPLAIN·pipeline/jobs/dataset
  projection·feature executor·ORM metadata/repository의 실제 PostgreSQL 순차 gate 81건,
  root unit/lint 1,430건, API 504건과 frontend unit 210건을 모두 통과했다. Ruff, strict
  mypy 167개 소스, frontend type-check·lint, admin/user OpenAPI·생성 타입 drift도 green이다.
  issue #712/#719는 최종 `T-ADM-C7` n150 live 증거 뒤 종결한다.

## Admin 갱신 정책 동시성 완결 (2026-07-18, `T-ADM-AUD-718`)

- [x] **T-ADM-AUD-718 — BIGINT revision CAS를 DB부터 UI까지 완결.** Alembic 0056으로
  `ops.provider_refresh_policies.revision`을 양수 BIGINT로 추가했다. 신규 생성은
  `expected_revision=null`, 기존 갱신은 정확한 revision 일치가 필수이며 성공할 때만 원자적으로
  1 증가한다. `source_kind`는 생성 뒤 불변이고 최댓값은 overflow 전에 typed 소진 `409`로 닫는다.
- [x] **충돌 복구와 JavaScript 정밀도 경계를 고정.** HTTP revision은 정규화된 10진 문자열이며
  불일치 응답은 현재 정책과 revision을 포함한다. UI는 작성 기준·최신 관측값·지연 응답 세대를
  분리해 background refetch와 다른 scope cache가 초안을 덮지 못하게 하고, 명시적 3-way 조정 뒤
  최신 revision으로만 다시 저장한다.
- [x] **적대 리뷰와 로컬 gate 완료.** DB/API와 frontend 리뷰어가 최종 제품 SHA
  `b7b600447368d8ed79bc1a8b56772af881104bf3`을 S1/S2/S3 0건으로 승인했다. root unit
  1,411건, API 489건, 실제 PostGIS migration/schema 14건·CAS 저장소/API 23건·집중 10건과
  독립 row-lock 경쟁 3회, Ruff, strict mypy 115+52파일, import 계약 4/4를 통과했다. 같은 SHA의
  frontend Vitest 212건, type-check, lint 오류 0건, OpenAPI/admin type drift와 31-route production
  build도 통과했다. issue #718은 PR #727의 수용조건과 CI를 재확인한 뒤 2026-07-18 닫았다.

## KMA 빈 target fail-closed·exact-scope event (2026-07-18, `T-ADM-AUD-686`)

- [x] **T-ADM-AUD-686 — 유효 target 0건을 provider I/O 전에 종결.** 직접 runner와 정규
  Dagster KMA grid asset 3종은 target mapping·dedupe·cap·cursor preflight를 통과한 뒤에만
  credential·provider import·public client를 사용한다. 유효 target이 없으면 feature/weather와
  provider sync state를 변경하지 않고 canonical operation을 실패시키며, 같은 transaction에
  `kma.target_scope_empty` event를 정확히 한 번 기록한다.
- [x] **원자성·이력 경계를 회귀 계약으로 고정.** active duplicate loser와 terminal replay는
  operation/event를 늘리지 않고, event 기록 실패는 request/job/event 전체를 rollback한다.
  dataset event는 canonical event→job→request JOIN에서 effective `sync_scope`를
  cursor·`ORDER BY`·`LIMIT` 전에 제한하며 다음 cursor와 canonical history URL을 반환한다.
  migration은 추가하지 않았고 이 join-derived 경계는 후속 C7B-API/0057이 승계한다.
- [x] **적대 리뷰와 로컬 gate 완료.** 두 독립 리뷰어가 제품 SHA `c07259fb`를 S1/S2/S3
  0건으로 승인했다. 테스트 격리·generated type 동기화를 반영한 최종 SHA에서 root unit
  1,413건, API 485건, Dagster 475건(1 skip), 실제 PostGIS 집중 6건, frontend Vitest
  185건을 통과했다. Ruff, strict mypy 115+52+23파일, import 계약 4/4,
  OpenAPI admin/user·generated type drift, frontend type-check·lint(오류 0, 기존 경고 6),
  31-route production build도 통과했다. #686은 #701/#726/#728/#729의 전체 수용조건과
  CI를 재확인한 뒤 2026-07-18 닫았다.

## Admin ops-live 인증·무효화 완결 (2026-07-17, `T-ADM-C7A`)

- [x] **T-ADM-C7A — same-origin 실시간 갱신 경계를 완결.** 로그인 session과
  `Origin`·Fetch Metadata를 모두 검사하는 ticket BFF, HMAC 서명 subprotocol ticket, DB nonce
  단일 소비와 60초 연결 lease를 구현했다. 없음·변조 ticket은 `4401`, handshake 전 만료는
  data frame 없이 `4408`로 닫으며 공유 secret은 local launcher와 API container에서 앞뒤
  공백 없이 32자 이상이어야 기동한다.
- [x] **transaction-coupled invalidation과 복구 상태 모델 고정.** Alembic 0055로
  `ops.ops_live_ticket_claims`와 `ops.ops_live_topic_revisions`를 추가했다. provider 상태·정책,
  schedule override·audit·claim resolution, integrity issue·POI cache target 변경을 원본
  transaction과 함께 topic revision에 반영하고 pipeline/datasets canonical query key를
  무효화한다. malformed·비단조 frame은 오염 socket을 폐기하고 새 ticket/socket에서 exact
  `replace`를 다시 보낸다. 연속 두 번 실패는 standby, 세 번째부터 polling fallback으로 전환한다.
- [x] **적대 리뷰와 로컬 gate 완료.** backend/DB/security와 frontend 상태 모델 리뷰어가 제품
  변경을 테스트 전에 승인했다. 정확한 최종 제품 SHA에서 root unit 1,411건, API 484건,
  실제 PostGIS migration/schema 14건과 C7A 집중 9건, frontend unit 185건, Ruff, strict mypy
  115+52파일, import 계약 4/4, OpenAPI/admin/user type drift, base·host Compose rendering과
  production build를 통과했다. 실제 browser의 close code·재연결은 최종 `T-ADM-C7` n150
  파괴적 live E2E에서 검증한다.

## Admin legacy surface clean-cut (2026-07-17, `T-ADM-C6b`)

- [x] **T-ADM-C6b — 운영 표면을 pipeline/datasets 두 화면으로 clean-cut.** legacy REST
  operation 28개와 `/ops/import-jobs*`, `/ops/providers`, `/admin/features/update-requests*`,
  `/admin/dagster`, `/etl` UI를 redirect·호환 shim 없이 삭제했다. canonical
  `/v1/ops/pipeline/*`, `/v1/ops/datasets/*`, 관측 read와 public provider read 2종만 유지했다.
- [x] **provider credential과 BFF 런타임 경계 분리.** API/frontend는 process별 env allowlist와
  package-scoped API env를 사용하고 provider 비밀은 Dagster에만 둔다. bridge mode는 전용
  control-plane network의 frontend 고정 주소 `/32`만 신뢰하며 host mode는 loopback으로
  덮어쓴다. root raw env 예제의 inline comment와 API package secret 중복은 fail-closed한다.
- [x] **계약·검증 완료.** 두 독립 적대 리뷰어가 최종 제품 및 테스트 보강을 S1/S2/S3 0건으로
  승인했다. root unit 1,410건, API 450건, Dagster 457건(1 skip), 실제 PostGIS 92건,
  frontend unit 142건, Ruff, strict mypy 115+51파일, import 계약 4/4, OpenAPI/admin/user type
  drift, base·host Compose rendering과 production build를 통과했다. live UI는 최종
  `T-ADM-C7` n150 gate에서 검증한다.

## Admin datasets 이슈 의미 통일 (2026-07-17, `T-ADM-C7B-720`)

- [x] **T-ADM-C7B-720 — dataset/provider open issue를 단일 행 의미로 통합.** `이슈 있음`
  필터·정렬·행 badge는 dataset 또는 provider open issue가 하나라도 있으면 선택한다. 요약은
  dataset을 `(provider,dataset)`, provider를 provider 단위로 중복 제거해 scope 반복 행을
  한 번만 집계한다.
- [x] **네 소유 조합과 frontend-only 경계를 고정.** provider-only, dataset-only, both,
  neither를 unit과 mocked E2E 계약에 추가했고 API·OpenAPI·DB는 변경하지 않았다. 두 독립
  리뷰어가 최종 SHA를 S1/S2/S3 0건으로 승인했으며 unit 5건, type-check, lint와 production
  build를 통과했다. #720은 본문 수용조건을 재확인한 뒤 2026-07-18 닫았다.

## Admin 통합 화면 링크 정본화 (2026-07-17, `T-ADM-C6a`)

- [x] **T-ADM-C6a — 존치 화면과 API 링크를 두 운영 화면으로 재배선.** import job,
  update request, load batch, provider/dataset과 홈·Feature·큐레이션·로그의 링크를
  `/ops/pipeline`·`/ops/datasets`로 전환했다. provider/dataset/scope와 canonical root
  identity를 보존하고 caller query가 엔티티 identity를 덮어쓰지 못하게 했다.
- [x] **선택 조회와 실시간 갱신 계약 보강.** load batch와 parent UUID deep link는 전용
  partial index에서 member를 먼저 선택한 뒤 root component를 확장한다. ops-live query key,
  import job HATEOAS와 live scenario catalog도 두 통합 화면 계약으로 맞췄다.
- [x] **적대 리뷰·회귀 검증.** 두 독립 리뷰어가 최종 SHA를 S1/S2/S3 0건으로 승인했다.
  root unit 18건, API 140건, 실제 Postgres 통합 22건, frontend unit 27건과 Ruff, strict
  mypy 115파일, import 계약 4/4, type-check, lint, production build를 통과했다.

## Admin pipeline 통합 화면 (2026-07-17, `T-ADM-C5`)

- [x] **T-ADM-C5 — `/ops/pipeline` 실행·스케줄 조작 단일 표면.** canonical root 기준
  상태 strip·타임라인·Dagster run·전역 event·schedule audit/claim·feature update 요청을
  한 화면에 통합했다. provider/dataset pair와 request root/projected job을 분리해 표시하고,
  URL 상태·1페이지 자동 갱신·신규 실행 배지·degraded 경계를 일관되게 적용했다.
- [x] **멱등·동시성·불확실 결과 폐루프.** Alembic 0054로 feature update idempotency와
  schedule command audit/active claim/resolution ledger를 append-only로 고정했다. DB clock 기반
  lease와 advisory lock, 120초 operation timeout, mutation guard를 사용하며 응답 유실 뒤에도
  동일 command/request를 복원한다. mutation 이후 결과가 불확실하면 claim을 보존하고 운영자가
  audit 근거로 명시 해소하기 전 재실행하지 않는다.
- [x] **적대 리뷰와 회귀 검증.** 의미 있는 최종 제품 커밋과 session 복원 변경을 backend/UI
  적대 리뷰어 2명이 각각 재검토해 S1/S2/S3 0건으로 승인했다. append-only cleanup은 테스트
  transaction에만 제한하고 실제 trigger 검증은 유지했다. #693·#716의 지적을 구현과 회귀
  테스트로 흡수했다.

## Admin datasets 통합·scope 폐루프 (2026-07-17, `T-ADM-C45X-B`·`C4R`·`C4`)

- [x] **T-ADM-C45X-B — sync_scope·active request 백엔드 정본.** PR #701에서 direct
  update의 typed scope·dispatch intent, active 유일성·멱등 재사용, KMA exact target과
  scope별 cursor/failure를 완결하고 병합했다.
- [x] **T-ADM-C4R / C45X-U — C4 UI 소비 계약과 scope 폐루프.** PR #698에서
  datasets projection과 pipeline history를 exact 3원 scope로 정렬하고, dataset-wide 기본
  state와 orphan/stale scope를 구분했다. active `external_system:*` 첫 실행, 기존 active
  operation 재사용 링크, 정책·preview·freshness·schedule degrade를 fail-closed UI에 연결했다.
- [x] **T-ADM-C4 — `/ops/datasets` 통합 화면.** 검색·상태 그리드, URL/history 기반 drawer,
  정책 편집, fixture preview, 지금 갱신과 scope별 이력을 한 화면에 구현했다. 두 적대 리뷰어의
  최종 판정은 S1/S2/S3 0건이고 mocked production UI E2E 47건이 통과했다. #684/#686/#712의
  운영 종결은 `T-ADM-C7` n150 live 증거 뒤 수행한다.

## C3e n150 운영 종결 (2026-07-16, `T-ADM-C3e-I2`)

- [x] **T-ADM-C3e-I2 — migration·sensor/cursor·4종 동일-root·live UI 검증.** 배포 전
  pg_dump(259,608,395 bytes, SHA-256
  `0c01693808a0cc94dcbe1dce9a04c5996364c642ac4fa3f1df77d87c08667167`) 뒤 n150 prod에
  0051/0052를 일방향 적용했고 Alembic single head와 0048 재수렴 `updated=0`, 예상 밖 exact
  untyped `0`, request validation/identity/quarantine 불일치 `0`을 확인했다. tracking sensor
  8개와 update sensor 2개는 모두 RUNNING이며 reconciliation cursor는 maintenance anchor
  `storage_id=5160`에서 `5175`로 전진하고 최근 5개 tick이 관측 오류 0으로 끝났다. 스케줄은
  기존 snapshot인 34 RUNNING·3 STOPPED로 정확히 복원했다. 일정·수동·갱신·standalone import가
  datasets/pipeline 상세에서 같은 `(kind,id)` root를 반환했고 모두 terminal이다. 공식 Playwright
  1.60.0 컨테이너로 provider consistency, Dagster/update request, offline upload, import action,
  home dashboard를 실제 prod에 실행해 138건 통과·전제 미충족 2건 skip을 기록했다. 최종 DB와
  Dagster active run은 0이고 이슈 #679에 전체 증거를 남긴 뒤 완료로 닫았다.

## C3e B2→B3 실제 PostGIS 교차 회귀 (2026-07-16, `T-ADM-C3e-I1`)

- [x] **T-ADM-C3e-I1 — public wrapper 결과와 terminal sensor의 단일 lifecycle 검증.** 실제
  migration 0001→0052를 적용한 PostGIS에서 단일 provider wrapper 성공과 MCST 부분 성공·실패를
  B2 public 경계로 기록한 뒤 B3 terminal record로 닫았다. 단일 성공은 root/member 완료·진행률
  100·engine 시각과 수동 trigger를, MCST 실패는 13개 exact pair의 identity·job·완료 시각 보존,
  active pair만 실패 처리, redacted attempt event 보존과 raw 오류 비노출을 고정했다. 두 적대
  리뷰어의 최종 판정은 각각 S1/S2/S3 0건이다. focused 32건, live 제외 전체 1,902건(5 deselected),
  Ruff, strict mypy 136개 소스, import 계약 4/4를 통과했다. raw 전체 실행에서는 외부
  `kor-travel-geo` reverse endpoint가 HTTP 400을 반환해 live 5건만 실패했으며 C3e seam 실패와
  분리했다. n150 migration·sensor/cursor·4종 동일-root 증거와 이슈 #679 종결은
  `T-ADM-C3e-I2`에 남겼다.

## C3e Dagster provider guard·public wrapper tracking (2026-07-16, `T-ADM-C3e-B2`)

- [x] **T-ADM-C3e-B2 — authoritative provider guard와 exact-pair tracking.** 모든 live
  provider resource가 I/O 전에 실제 Dagster run record의 job·asset selection·run config·tag와
  B1 registry identity를 대조하고, 각 public asset/KMA wrapper가 마지막 ensure와 자기 exact pair
  완료를 소유하게 했다. MCST는 nullable pair-completion callback으로 부분 성공을 보존하며 direct
  `FeatureUpdateAssetRunner`는 tracking 0을 유지한다. 취소 marker·identity drift·naive timestamp는
  fail-closed하고, 비기본 KNPS point/geometry 설정은 provider fetcher와 asset resource가 같은
  `model_copy` snapshot을 사용한다. 적대 리뷰어 2명의 최종 판정은 S1/S2/S3 0건이다. focused
  260건(1 skip), 실제 PostGIS canonical operation 30건, Dagster 전체 428건(1 skip), main unit
  1,366건과 Ruff·strict mypy 136개 소스·import 계약 4/4를 통과했다. B2→B3 실제 terminal DB
  연쇄는 `T-ADM-C3e-I1`에서 완료했고, 이슈 #679 종결과 n150 증거는 `T-ADM-C3e-I2`에 남겼다.

## C3e Dagster run sensor·양방향 복구 (2026-07-16, `T-ADM-C3e-B3`)

- [x] **T-ADM-C3e-B3 — active/terminal sensor·양방향 reconcile.** QUEUED부터
  CANCELED까지 7개 run-status sensor와 NOT_STARTED/MANAGED·누락 event를 복구하는 30초
  periodic sensor를 기본 RUNNING으로 등록했다. public Dagster insertion cursor는 300초
  settle lag와 연속 settled prefix를 사용하고, DB active-root keyset은 마지막 page에서 처음으로
  wrap한다. cursor anchor 삭제·변조, 비어 있지 않은 storage의 무cursor 시작, scan/list/write
  실패는 fail-closed하며 cursor를 전진시키지 않는다. terminal trigger·selection 불변식 위반은
  같은 transaction에서 root/child를 `tracking_invariant`로 닫는다. 적대 리뷰어 2명 최종
  S1/S2/S3 0건 승인 뒤 focused 101건과 수정 후 52건, 실제 PostGIS 27건, Dagster 전체
  342건(1 skip), main unit 1,366건, Ruff·strict mypy·import 계약 4/4를 통과했다.

## C3e Dagster operation registry (2026-07-16, `T-ADM-C3e-B1`)

- [x] **T-ADM-C3e-B1 — immutable registry·run identity.** 33개 feature-load job과
  53개 exact provider/dataset 선택지를 canonical manifest와 내용 기반 digest version으로
  고정했다. KNPS launch snapshot, fileData 4종의 두 resource config, MCST 13-pair identity,
  trigger 분리와 exact coalescing을 schedule/admin/projection 경계에 연결했다. 등록 job의
  누락·교차 identity는 fail-closed하고 비등록 job만 panel-only로 유지한다. 적대 리뷰 2인
  S1/S2 0건 승인 뒤 main unit 1,366건, API 513건, Dagster 308건(1 skip), focused 159건,
  Ruff·strict mypy·import 계약 4/4를 통과했다. 실제 Dagster context의 override guard와
  provider tracking은 B2로 이관했다.
## C3e REST canonical 교차 통합 (2026-07-16, `T-ADM-C3e-C`)

- [x] **T-ADM-C3e-C — datasets/pipeline 실제 DB·REST 교차 증거.** 실제 migration을 적용한
  PostgreSQL에 canonical operation을 commit하고 요청별 새 FastAPI session으로 datasets grid/detail과
  pipeline 2페이지가 같은 root·member·상태·engine 시각·projected job을 반환함을 고정했다.
  exact-pair decoy, 인증, cursor, schedule, slash·예약문자 복합키도 검증한다. detail/preview/
  refresh-policy는 고정 path와 `provider`/`dataset_key` query로 clean-cut 전환했으며 OpenAPI와
  admin 생성 타입을 함께 갱신했다. 적대 리뷰 2인 S1/S2 0건 승인 뒤 API 503건, router 13건,
  실제 DB 통합 1건, Ruff·strict mypy·OpenAPI/type drift·frontend type/lint gate를 통과했다.
## C3e 실행 재분할 문서화 (2026-07-16, `T-ADM-C3e-D2`)

- [x] **T-ADM-C3e-D2 — C3e-B 복구 감사와 병렬 PR 재분할.** Claude Code의 branch,
  reflog, stash, remote와 고아 worktree blob을 감사해 C3e-B 고유 구현이 없음을 확인했다.
  B를 registry/run identity, guard/wrapper/MCST, sensor/reconcile의 B1/B2/B3 PR로 나누고,
  A2에서 제품 구현이 끝난 C는 실제 DB/FastAPI REST 교차 통합 증거 PR로 축소했다. 문서-only
  변경이므로 사용자 지시에 따라 추가 적대 리뷰 없이 rebase·CI green 뒤 병합한다.

## Admin ops 통합 기반 (2026-07-14~15, `T-ADM-C1`~`C3c`)

- [x] **T-ADM-C1 — 플랜·ADR-064·task 분해.** Dagster job/provider 운영 표면을
  `/ops/pipeline`과 `/ops/datasets` 두 페이지로 통합하는 정본 계획과 병렬 PR 경계를 확정했다.
- [x] **T-ADM-C2 / C2R — datasets backend와 차단 계약 보강** (PR #676/#688,
  issue #678). 그리드·상세·refresh policy·typed preview, 서버 계산 freshness,
  schedule 시각 분리, canonical latest batch, provider/dataset 이슈 분리, orphan mutation
  차단을 완결했다.
- [x] **T-ADM-C3 — pipeline backend** (PR #677). overview·root execution·detail/cancel·
  event·Dagster run·schedule·request API와 `dagster_run_id` 실컬럼을 추가했다.
- [x] **T-ADM-C3a — 공용 application service/schema 추출** (issue #682, PR #687).
  삭제 예정 router의 private symbol 의존을 제거하고 신·구 표면의 공용 경계를 만들었다.
- [x] **T-ADM-C3b — canonical root projection** (issue #679, PR #689). recursive lineage,
  nearest request owner, standalone partition, deterministic projected job과 keyset cursor를
  구현했다. C3e가 typed identity 정본으로 후속 강화한다.
- [x] **T-ADM-C3c — Dagster run detail/failure 계약 이식** (issue #681, PR #687/#690).
  opaque event cursor, failure 구조, 404/502/503 RFC7807과 공용 query service를 완결했다.

## C3e canonical operation 영속화 (2026-07-15, `T-ADM-C3e-A1`)

- [x] **T-ADM-C3e-A1 — 0051·operation repository frozen 계약**.
  `ops.import_jobs`에 exact pair·trigger·registry version·raw Dagster status와 feature operation
  구조 제약·partial index를 추가하고, payload를 읽지 않는 보수적 backfill을 적용했다. frozen
  repository/client lifecycle, direct writer identity, feature operation의 authoritative engine 시각,
  C3d run-backed queued 취소 경계를 적대 리뷰 2회와 전체 로컬 gate로 고정했다. 상세 구현·검증
  기록은 `docs/journal.md`와 `docs/resume.md`의 2026-07-15 A1 항목을 따른다.

## C3e 공용 projection·request/job 단일 정본 (2026-07-16, `T-ADM-C3e-A2`)

- [x] **T-ADM-C3e-A2 — canonical root/exact-pair projection과 0052 clean-cut.**
  pipeline/grid/detail/overview를 같은 cycle-safe root와 typed pair member에 연결하고,
  feature update request lifecycle을 canonical import job 한 행으로 통합했다. request/job 양방향
  1:1, 6종 scope·typed filter·update policy, 격리 component, 전용 writer/CAS를 DB와 Python에서
  함께 강제한다. event 감사 부분 index와 statement-level live revision clock을 추가했으며,
  두 적대 리뷰어 승인 뒤 전체 Python/DB/frontend gate와 n150 mocked E2E 501건을 통과했다.

## C3e canonical operation 문서 gate (2026-07-15, `T-ADM-C3e-D`)

- [x] **T-ADM-C3e-D — canonical provider operation 문서 계약** (#679, PR #696).
  Claude Code worktree의 설계 기록을 C3d 정본 위에서 복구하고, Dagster run root 한 건과 exact
  provider/dataset child, retry/terminal 소유권, frozen client 계약, 0051 migration·backfill/down,
  C3d queued run-backed 취소, 공용 projection·mixed-version 순서를 구현 전에 고정했다. 적대 리뷰
  2인의 S1/S2 0건 승인과 CI green 뒤 문서 PR을 병합해 C3e-A1/A2/B/C의 compile target으로 삼았다.

## Pipeline 계층형 취소 완결 (2026-07-15, `T-ADM-C3d`)

- [x] **T-ADM-C3d — 실제 계층형 취소·Dagster terminate** (#680, PR #695).
  C3b canonical root의 frozen scope, base marker, 정규화 attempt/member/run, run별
  at-most-once terminate reservation, crash resume, authenticated audit, marker CAS와
  `Retry-After`/RFC7807/OpenAPI/admin types를 완결했다. pre-start generation 복구,
  browser invalidation/live E2E 계약, production bound-client DB 탈출 차단까지 하위
  `T-ADM-C3d-P1R`·`R2A`·`R2B`·`R2C`로 반영했다. 두 적대 리뷰와 로컬 전체 gate,
  GitHub Actions 8/8 green 뒤 merge commit
  `28dfe224dee9c7a09775293b37be6795edb92651`로 main에 반영했고, 수용 증거를 남긴 뒤
  이슈 #680을 닫았다.

## 최근 2일 Claude Code PR 사후 적대 리뷰 (2026-07-15, `T-ADM-RV-CLAUDE-2D`)

- [x] **T-ADM-RV-CLAUDE-2D — 닫힘 여부와 무관한 Claude Code PR 상세 리뷰·이슈화.**
  공동작성 trailer와 Claude session 근거가 있는 PR #672, #674, #675, #676, #677,
  #683, #691, #692를 각각 상세 리뷰했다. review-fix 전용 PR은 없었고, Claude 근거가 없는
  #664, #666~#671, #687~#690은 제외했다. pipeline UI 상태 격리·sensor fail-closed·URL
  복원은 #693, live UI E2E 의미 단언은 #694로 묶어 새 이슈를 만들었다. 기존 #682,
  #684, #685, #686에는 재현 근거와 보강 수용 기준을 남겼으며, #687로 완료되지 않은
  actor/problem/schedule 범위 때문에 #682를 다시 열었다.

## 지도 신선도·provider 실행·고zoom 성능 반복 장애 수정 (2026-07-13, `T-231`)

- [x] **T-231 — notice/OpiNet 반복 장애 근본 수정과 지도 응답성 보강.** KREX notice를
  strict pagination·lineage 검증을 거친 동일한 2회 연속 snapshot으로만 반영하고, 부재 공지
  종료·재등장 복원·공개 active 필터를 일관 적용했다. Dagster 고착 run 슬롯 고갈은 monitoring,
  provider pool·DB advisory lock, KREX tick coalescing으로 차단했다. OpiNet raw/변환 0건과
  전일·혼합 가격 성공 오인, scope를 무시한 targeted 전국 재조회도 실패/skip/cursor 계약으로
  교정했다. AirKorea/KMA marker, 과거 유가 표기·단일 시계열 점, Feature/큐레이션 고zoom
  로딩을 함께 보강했다. KREX upstream 수정은 `python-krex-api` PR #11에 선반영했다. 적대적
  리뷰 2회 후 S1/S2 잔여 0건이며 전체 로컬 Python/API/Dagster/frontend/OpenAPI 게이트를
  통과했다. PR merge·n150 운영 복구와 live E2E 인수 결과는 `docs/resume.md`의 다음 작업으로
  추적한다.

## 큐레이션 CSV·다중 관측 aggregate 계약 (2026-07-13, `T-230`)

- [x] **T-230 — 큐레이션 CSV·다중 source/연도 aggregate 계약 구현** (#665, PR #666).
  provider entity/current record와 immutable observation 이력, 회차형 collection/item schema를
  Alembic 0044/0045로 구현했다. admin 수동 입력·CSV 양식·preview·원자적 멱등 import와
  지도·목록·상세·REST의 다중 관측/다중 membership 표시를 추가하고 등대 category도 등록했다.
  공식 CSV 5종은 collection 19개·membership 486행이며, n150 기존 Feature에 225행을 연결하고
  261행은 원천 안정키·장소명·주소 hint를 가진 미연결 item으로 보존했다. 전체 로컬 게이트와
  적대적 리뷰(HIGH/MEDIUM 잔여 0), n150 Alembic 0045, 로그인, 실제 DB/REST, prod live Playwright
  4건, 동일 CSV 두 번째 dry-run 변경 0건을 통과했다. 정본 계획·결과는
  `docs/reports/t-230-curation-multi-observation-plan.md`다.

## UI live e2e 재실행 (2026-06-21, `T-UI-E2E-LIVE-20260621`)

- [x] **T-UI-E2E-LIVE-20260621 — UI live e2e 재실행 + 하네스 안정화.**
  live stack 기준 전체 Playwright e2e를 재실행했다. 1차는 629 passed / 1 failed였고,
  실패는 `home-density-matrix.spec.ts`의 공통 `gotoHome()`이 full `load` 이벤트를 기다리다
  live static asset 지연에 걸린 하네스 문제였다. `waitUntil: "domcontentloaded"`로 조정 후
  `npm run type-check:e2e`, 실패 케이스 단독 재현, 리베이스 후 현재 브랜치 별도 live stack에서
  전체 live UI e2e **631 passed**로 닫았다.
  정본 `docs/reports/ui-live-e2e-rerun-2026-06-21.md`.

## maplibre-vworld-js dependency 제거 (2026-06-18, `T-MAP-VWORLD-04`)

- [x] **T-MAP-VWORLD-04 — `maplibre-vworld-js` dependency 제거** (#475).
  `digitie/maplibre-vworld-react` `a7cb0f8` 기준으로 admin web 지도 경계를
  `vworld-map-core`/`vworld-map-web` 모델에 맞췄다. admin frontend와
  `@kor-travel-map/map-marker-react`에서 `maplibre-vworld` package dependency,
  `maplibre-vworld/style.css` import, Vite external/global 선언을 제거하고,
  `package-lock.json`에서 `maplibre-vworld` 및 전용 transitive를 제거했다.
  `VWorldMapView`는 maxZoom clamp, redacted error logging, stable marker click
  callback을 보강했다. 검증: admin type-check, marker typecheck/build,
  admin vitest 27 passed, ESLint 0 errors(기존 warnings 6), Next build, Windows
  Playwright 지도 e2e 5 passed. 정본 리포트:
  `docs/reports/maplibre-vworld-js-dependency-removal-2026-06-18.md`.

## OpenAPI 에러 본문 RFC7807 problem+json 기계 계약 보강 (2026-06-18, `T-452`)

- [x] **T-452-openapi-problem-json — OpenAPI 4xx/5xx problem+json 선언.**
  생성 `openapi.json`/`openapi.user.json`이 에러 응답을 `422 application/json`
  (`HTTPValidationError`)로만 선언하던 under-spec(#452/#444 잔여)을 해소했다. `create_app`의
  custom `app.openapi()`가 모든 operation의 4xx/5xx·`default` 응답을 `application/problem+json`
  (`ProblemDetail`/`ProblemDetailError`, `code`·`request_id` 확장 멤버 포함)으로 선언하고, FastAPI
  자동 422도 problem+json으로 대체하며 orphan 검증 schema를 제거한다. 핸들러별 `responses=`
  대신 중앙 핸들러(`_error_response`)와 대칭인 중앙 openapi 주입을 택했다. 산출물 재생성
  (`export_openapi.py --profile all`) + frontend/user-client `gen:types` 동반, `--check` drift
  gate·`gen:types:check`로 고정. 정본 `docs/architecture/rest-api.md §1.5`,
  회귀 테스트 `test_export_openapi.py::test_openapi_declares_rfc7807_problem_json_error_responses`.

## admin TanStack 테이블 이행 후속 종결 (2026-06-18, `T-ADMIN-TANSTACK`)

- [x] **T-ADMIN-TANSTACK — admin UI TanStack 테이블 이행 후속 종결.**
  이행 본체는 PR #454(정본 `docs/reports/admin-tanstack-table-migration-2026-06-17.md`). 잔여
  2건이 모두 해소되어 종결한다.
  - **(a) backend-의존 e2e 라이브 실행 ✅**: 라이브 Docker 스택(api :12701 / dagster :12702 /
    migrated frontend :12705)에서 전 spec 실행 → PR #458/#459 후 **57 passed / 0 failed**
    (2026-06-17, `docs/resume.md`). admin-ops/curated/features-new 포함 backend-의존 표면 무회귀
    확인. (사용자 결정: 이미 검증됨 → 재실행 생략.)
  - **(b) bulk 동작 정책 가드 ✅**: main에 이미 구현됨 — dedup bulk는
    `enableRowSelection` pending-only + `decideBulk` 방어적 필터로 **완료 review 재결정 차단**,
    curated bulk archive는 `window.confirm("선택한 N건을 보관할까요?")` **일괄 confirm**.
    enrichment는 단일 행 pending-only(bulk 표면 없음 — 가드 불필요).

## 외부/보류 task won't-do 종결 (2026-06-18)

사용자 지시로 아래 task를 **진행하지 않음(won't-do)** 으로 종결했다. 산출물 없이 백로그에서만
정리한다(`docs/tasks.md` 외부 추적 섹션 제거 + 보류에서 T-103 제거).

- [x] **T-019 — PinVi Kakao Maps → maplibre-vworld 교체 / SPEC supersede 추적** (won't-do, PinVi repo 외부).
  본 저장소 책임은 ADR-026/043 reference와 `@kor-travel-map/map-marker-react` 계약 유지로 한정한다.
- [x] **T-210b — PinVi 문서 supersede** (won't-do, PinVi repo 외부).
- [x] **T-210c — PinVi `apps/etl` 레거시 Dagster 이관/삭제** (won't-do, PinVi repo 외부).
- [x] **T-210d — PinVi httpx OpenAPI client 신규** (won't-do, PinVi repo 외부).
  PinVi-side 정렬 작업으로 본 저장소는 OpenAPI 계약(정본 `docs/integration-map.md`)만 책임진다.
- [x] **T-103 — streaming ETL(Kafka/Redpanda) 대응** (won't-do).
  `docs/architecture/performance.md §9.4` 기준 — 초 단위 latency를 실제로 요구하는 provider 증거가
  없어 도입하지 않는다. 필요 신호가 생기면 신규 task로 재개한다.

## maplibre-vworld-react 지도 전환 (2026-06-17, `T-MAP-VWORLD`)

- [x] **T-MAP-VWORLD-01 — 계획 및 Task 생성** (#465, PR #468).
  `digitie/maplibre-vworld-react` `a7cb0f8` 기준으로 admin `features` 지도 전환 범위를
  정했다. 전체 외부 모노레포 vendoring 없이 필요한 `VWorldMapView`/React marker 모델만
  admin UI 내부에 얇게 이식하는 방향이다. 정본 계획은
  `docs/reports/maplibre-vworld-react-migration-plan-2026-06-17.md`.
- [x] **T-MAP-VWORLD-02 — admin features 지도를 VWorldMapView 기반으로 전환** (#466).
  직접 `maplibre-gl` 인스턴스와 marker 배열을 관리하던 `features-client.tsx`를
  `VWorldMapView`/`VWorldMarker` 컴포넌트 모델로 전환했다. bbox 동기화, kind 필터
  refetch, marker/table 선택 상세 패널, VWorld key 미설정 fallback을 유지했다.
  Windows localhost forwarding이 실패하는 e2e 환경을 위해 `NEXT_ALLOWED_DEV_ORIGINS`
  기반 dev origin 추가 허용도 넣었다.
- [x] **T-MAP-VWORLD-03 — 지도 e2e 라이브 검증 및 후속 수정** (#467).
  PR #469 merge 후 main 기준으로 Windows Playwright 지도 e2e를 재실행했다.
  `features-map-interactions.spec.ts`는 **5 passed / 0 failed**였고 추가 수정할
  회귀는 없었다. 정본 리포트는
  `docs/reports/maplibre-vworld-react-e2e-2026-06-17.md`.

## T-212e 후속 라이브 검증 (2026-06-14, `T-229`)

- [x] **T-229 — T-212e 후속 라이브 검증** (arm64 buildx만 잔여).
  T-225가 분리한 커버리지 갭을 실데이터(features 1,095,665)로 라이브 검증했다. T-212e
  데이터가 옛 claude postgres(15433)에 잔존 + 격리 복원본 `krtour_map_restore` 존재라
  복원 불필요했고, 운영 데이터 무손상 원칙으로 **복원본에만** 검증했다. **curated
  오버레이 완전 검증**: `curated_features_refresh` 4-asset RUN_SUCCESS → curated_features
  0→**86,341** 후보(테마 7종, MCST source 카운트 정합), admin API 실제 서빙, 사용자
  표면은 미선택 후보 숨김(선택 게이트), curated-themes/sources 200, tripmate-copy는
  선택 시 생성(0). `/metrics` 200, smoke breadth 전 표면 응답(200/정상404). AS-01/
  API-11/12 실데이터 해소. arm64 multi-arch buildx는 당시 환경 제약으로 검증하지 못했으나,
  2026-06-29 사용자 결정으로 추가 추적하지 않는다. codex 스택은 사용자 지시로
  강제종료 후 external-infra 재기동. 정본 `docs/reports/t-229-curated-live-verify-2026-06-14.md`.

## T-212e closure 재검증 (2026-06-13, `T-225`)

- [x] **T-225 — T-212e closure 재검증.**
  라이브 full reload 재실행 없이 현재 main(`25b286b`, #434 포함) 기준 문서/코드 증거
  대조로 닫았다(인수기준 충족). 5개 차원 교차검증 + 각 gap 반증(서브에이전트 18).
  **T-212e closure 유효**: 실패 provider 6건 수정 전부 main 존재(pin SHA 일치),
  리포트 무결성 정합(MCST 13종 102,121, 이슈 #397/#407/#409 close + 보강 PR 머지,
  broken link 없음), identity는 #429가 리포트까지 재작성해 이미 post-rename,
  패키지 분리(#430)·#434 포트 재기준은 데이터 closure에 영향 없음. 착수 가정이던
  "구 이름 drift"는 실재하지 않았다. 남은 라이브 검증 커버리지 갭(curated 오버레이,
  Prometheus `/metrics`/arm64 buildx, smoke breadth)은 후속 **T-229**로 분리.
  정본 `docs/reports/t-225-t212e-closure-recheck-2026-06-13.md`.

## 운영 배포 자동화 (2026-06-13, `T-108`)

- [x] **T-108 — 운영 배포 자동화 (pinvi T-108 이식).**
  pinvi 원문은 Odroid M1S + N150 16GB 양쪽, multi-platform Docker build,
  streaming replication을 포함했으나, 사용자 재지시에 따라 kor-travel-map에서는
  **streaming replication은 하지 않는다**. 본 저장소 범위는 N150 16GB(`linux/amd64`)와
  Odroid M1S(`linux/arm64`)에 같은 image tag를 배포할 수 있는 buildx 자동화로 닫았다.
  `scripts/docker-buildx.sh`, `npm run docker:buildx`, `.env.example`,
  `docs/deploy.md`, `docs/runbooks/docker-app.md`, ADR-056이 정본이다.

## 태스크 문서 정리 (2026-06-13, Codex)

- [x] **태스크 문서 전반 정리.**
  `docs/tasks.md`를 열린 `[ ]` task만 남기는 백로그로 축소하고,
  `docs/resume.md`를 현재 상태 + 다음 한 작업 중심으로 다시 정리했다.
  중복 완료 체크박스와 오래된 Sprint 2/3 미완료 표기가 현재 인수인계에 노출되지
  않도록 완료 묶음은 이 파일에 요약 아카이브한다.

## 패키지 정체성 / 메트릭 후속 (2026-06-13, `T-226`/`T-227`)

- [x] **T-226 — 배포명/임포트명 재정의: `kor-travel-map` / `kortravelmap`.**
  ADR-054와 `docs/package-identity-rename.md` 기준으로 public distribution
  `kor-travel-map`, Python import root `kortravelmap`, 권장 예시
  `import kortravelmap as ktm`, CLI `ktmctl`, DB `kor_travel_map`,
  Dagster metadata DB `kor_travel_map_dagster`, RustFS bucket/prefix
  `kor-travel-map` 계열로 clean cut했다. `T-226a` 문서 정본,
  `T-226b` 실행계획, `T-226c/d/e` 코드·runtime·소비자 문서 전파가 모두 완료됐다.
- [x] **T-227 — Prometheus 성능 메트릭 표면.**
  `kortravelmap.api` FastAPI app에 `GET /metrics`를 추가했다. HTTP 요청 total/duration,
  in-progress, response size, exception count, DB query count/duration,
  process/runtime metrics를 Prometheus exposition format으로 제공하고
  `surface=public/admin/ops/debug/system/other` label로 공개 REST와 운영 REST를 분리했다.

## API/admin 패키지 분리 (2026-06-13, `T-228`)

- [x] **T-228 — `kor-travel-map-api` backend와 `kor-travel-map-admin` frontend 분리.**
  FastAPI/OpenAPI backend를 `packages/kor-travel-map-api/`로 이동하고,
  `kor-travel-map-admin`은 Next.js admin frontend만 소유하도록 정리했다.
  `KOR_TRAVEL_MAP_API_*`, `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`,
  `packages/kor-travel-map-api/openapi*.json` 기준으로 Docker/CI/scripts/docs를 갱신했다.

## Admin UI 접근성/e2e 보강 (2026-06-10, `T-218`)

- [x] **T-218 — admin UI 상세 구현 점검 + a11y/e2e 완비.**
  화면별 상세 점검과 a11y/e2e 보강을 완료했다. 정본은
  `docs/reports/t-218-admin-ui-hardening-plan-2026-06-10.md`와
  `docs/runbooks/admin-ui-screen-checklist.md`.
  - [x] `T-218a` — 공통 폼 a11y wrapper와 `validateForm` util 도입.
  - [x] `T-218b` — 좌표 scope, offline upload, issue manual override 폼에
        visible label/error/focus 경로 적용.
  - [x] `T-218c` — `/admin/backups` e2e 신설로 admin/ops 16/16 화면 커버 달성.
  - [x] `T-218d` — 위험 액션 음성 경로 e2e 보강.
  - [x] `T-218e` — `Alert` live-region 정합성 보강.
  - [x] `T-218f` — 화면별 상세 회귀 점검 체크리스트 작성.

## Sprint 5 운영 진입 완료 묶음 (2026-06-07~10)

- [x] **T-200~T-204 — 운영 진입 기반.**
  Batch DAG + 정합성 게이트, `ops.feature_consistency_reports`, pre-commit hook,
  PR CI workflow, branch protection 가이드를 완료했다.
- [x] **T-212a~d — ADR-045 전체점검/튜닝 선행 묶음.**
  전체 inventory + Playwright/e2e gap matrix, admin UI 완결성, API endpoint/error/log
  contract, DB/API/frontend 성능 튜닝과 read-heavy 재측정을 완료했다.
- [x] **T-216a~g — REST API 정합성 심화.**
  `/v1` clean cut, pagination 단일화, envelope payload/meta 분리,
  parameter/error/좌표 정합성, 명명 통일, 코드/DB surrogate 명명 전파,
  단일 정본과 버전 거버넌스를 완료했다.
- [x] **T-RV-50~55 — T-RV-04b provider/admin 후속 프로그램.**
  `maplibre-vworld-js` v0.1.3 정합, dedup 수동처리 UI/기본 scope,
  visitkorea 축제 enrichment, krforest 휴양림/수목원, datagokr 박물관/미술관,
  관광지·주차장·KHOA 해수욕장·AirKorea 대기질·공항 provider 후속을 완료했다.

## 실데이터 full reload 최종 검증 (2026-06-12, `T-212e`)

- [x] **T-212e — 실데이터 전체 재적재 + offline upload 실데이터 검증 + 최종 리포트.**
  정본은 `docs/reports/t-212e-live-full-reload-final-2026-06-12.md`.
  - 빈 DB(WSL 재설치로 환경 전체 재구축)에서 전 provider Dagster 적재
    **1,095,665 features**(MOIS bulk 980,970 / MCST CSV 13종 102,121 /
    주차장 18,294 / knps_trails 618 등) + weather values 92,923.
  - `full_load_batch_consistency_gate` 최종 report `99159eea` severity_max
    OK, `ops.data_integrity_violations` 0.
  - offline upload 실데이터 CSV/TSV/JSONL 3포맷 종단 `loaded` + #397→#417
    DELETE lifecycle live 검증(좀비 2건 삭제 → 동일 checksum 재업로드 201).
  - Windows Playwright e2e **33/33**, API smoke 17/17, backup→staging
    restore 검증값 운영 정확 일치(1,095,665), 대표 read P99 수집
    (in-bounds 442ms — 클러스터 MV ADR 재판단 입력).
  - 실측 적발 수정: krtour #392/#393/#400/#408/#410/#411/#413/#416/#417/
    #420/#424 + provider 5 repo(datagokr·krheritage·kma·mcst·knps)
    이슈→PR→머지. 이슈 #397/#407/#409 close.

## curated_features + TripMate import (2026-06-12, `T-223`)

- [x] **T-223 — curated_features + TripMate curated_trip_plans import 계약/구현.**
  T-223a~d 전부 완료. 정본은 `docs/curated-features.md`.
  - [x] **T-223a — 문서 계약 정리.**
    책/음식 테마 source 조사, overlay DB 모델, REST/Admin UI/Dagster,
    TripMate 1:1 복사 계약을 정리했다.
  - [x] **T-223b — provider 보강.**
    `python-mcst-api` 중고서점 CSV(provider PR#11),
    `python-datagokr-api` 서울 책방·무슬림 친화 음식점·안산 세계맛집·제주 향토음식점
    fileData + 전국지역특화거리 표준데이터 서비스(provider PR#10)를 반영하고,
    kor-travel-map 변환 함수와 단위 테스트를 추가했다.
  - [x] **T-223c — kor-travel-map DB/API/Dagster/Admin UI.**
    `feature.curated_*` 테이블, seed source/rule, `/v1/curated-*`,
    `/v1/admin/curated-*`, source rule apply, TripMate copy snapshot, OpenAPI/user-client,
    Dagster `curated_features` group, `/admin/curated-features` UI를 구현했다.
  - [x] **T-223d — TripMate 연동.**
    TripMate PR #184(`5966628192a1f7b0c359a6435011f3e2f3f04469`)에서
    krtour REST snapshot을 `app.curated_trip_plans` / `app.curated_plan_pois`로
    복사하고 source version/etag/item provenance를 저장하는 admin import를 머지했다.
    `kor-travel-concierge`는 curated trip plan 생성에 관여하지 않는다.

## TripMate T-130 공개 해수욕장/축제 뷰 API (2026-06-12, `T-222`)

- [x] **T-222 — TripMate T-130 공개 해수욕장/축제 뷰 API.**
  T-222a~c 전부 완료. 정본은 `docs/public-views-api.md`와 TripMate PR#183.
  - [x] **T-222a — API 사양 초안.**
    `/v1/public/beaches*`, `/v1/public/festivals*`, 스키마, category drift,
    KHOA index/축제 월별 집계 결정점을 정리했다.
  - [x] **T-222b — kor-travel-map 백엔드/OpenAPI/user-client 구현.**
    `/v1/public/beaches*`, `/v1/public/festivals*`를 추가하고 user OpenAPI와
    `@kor-travel-map/map-user-client` 타입을 재생성했다. 해수욕장은
    `detail.place_kind='beach'`를 1차 판별로 쓰며, KHOA provider category
    `01020300`은 보조 정보로 유지한다.
  - [x] **T-222c — TripMate 소비 문서/픽스처 동기화.**
    TripMate `/public/beaches*`와 `/public/festivals*`가 krtour
    `openapi.user.json` 기반 schema/client를 소비하도록 연결했다(TripMate PR#183).

## Admin UI/UX 연결성 + 실시간성 (2026-06-12, `T-221`)

- [x] **T-221 — admin UI/UX 시나리오 연결성 + 실시간성 보강.**
  T-221a~e 전부 완료. 정본 점검은
  `docs/reports/admin-ui-scenario-linkage-recheck-2026-06-11.md`.
  - [x] **T-221a — feature 상세/수동 작성 흐름.**
    `/features/[feature_id]` 1급 상세 route와 `GET /v1/admin/features/{feature_id}`,
    `/admin/features/new` 수동 feature 작성 화면(지도 좌표 선택, kor-travel-geo
    geocode/reverse, kind별 form, nearby 중복 후보)을 구현했다.
  - [x] **T-221b — import job 상세/event/cancel.**
    `ops.import_job_events`, `/ops/import-jobs/[job_id]`, job event timeline,
    `POST /v1/ops/import-jobs/{job_id}/cancel`을 연결했다.
  - [x] **T-221c — admin live signal channel.**
    `WS /v1/ops/live` topic 다중화와 frontend TanStack Query invalidation을 구현했다.
  - [x] **T-221d — provider 상세/refresh policy.**
    `/ops/providers` 상세, `provider_dataset` update request, `provider_refresh_policies`
    편집 UI/API를 구현했다. 중복 provider run endpoint는 만들지 않는다.
  - [x] **T-221e — ops logs + debug 재판정.**
    `/ops/logs`에 job event stream을 붙이고, `/debug/explain`·`/debug/fixtures` REST/UI는
    만들지 않는 것으로 정리했다.

## Provider Dagster 완결 — KMA/MCST (2026-06-11, `T-219`/`T-220`)

- [x] **T-219 — KMA weather Dagster 파이프라인 완결.**
  T-219a~c 전부 완료. asset 5종(실황/초단기/단기/중기/특보) + KST schedule +
  cursor/credential guard를 구현했다. 정본은
  `docs/reports/kma-mcst-provider-plan-2026-06-11.md` §2.
  - [x] **T-219a — weather 대상 격자/feature 매핑 조회 기반.**
    `parse_weather_extra_points`(lon,lat;… 파서 + 한국 bbox 검증)와
    `kma_weather_extra_points`/`kma_weather_max_grids_per_run` 설정,
    `list_active_target_coords`(poi_cache_targets),
    `list_active_place_coords`(deleted_at IS NULL — D-12 read 정합)를 추가했다.
    LGT 메트릭은 기등록 확인 후 노후 docstring만 정정했다.
  - [x] **T-219b — 초단기실황/초단기예보/단기예보 asset+schedule.**
    `map_dagster.kma_weather` asset 3종, KST cron(45분/20·50분/02~23시 8회),
    `kma_weather_client` resource(credential guard), cursor `base_datetime` skip/failure 기록,
    fake client 테스트 12종을 추가했다. `python-kma-api@ab1a0b8` 핀 활성화.
  - [x] **T-219c — 중기 + 특보.**
    mid asset(설정 주입 `kma_mid_region_features` JSON — 육상/기온 reg_id 분리,
    미설정 skip, `kma_datagokr_client` resource)과 특보 record resource
    `kma_weather_alert_records`(전국 108, rolling window)→notice 적재를 구현했다.
    ASOS/해수욕장(beach_*)/APIHub 표면 + 특보 구역별 fan-out·좌표 enrichment는
    1차 범위 밖 백로그 비고로 남겼다.
- [x] **T-220 — MCST(python-mcst-api) 신규 provider 풀스택.**
  T-220a~c 전부 완료. 변환/Dagster/fixture·문서를 구현했고 marker `P-12`,
  `DATA_GO_KR_SERVICE_KEY` 공유 기준을 문서화했다. 정본은 같은 리포트 §3과
  `docs/mcst-feature-etl.md`.
  - [x] **T-220a — `providers/mcst.py`.**
    slug 메타표 16종(`MCST_CULTURE_DATASETS` 14 + `MCST_LIBRARY_DATASETS` 2,
    dataset_key `mcst_<slug>`), 공용 `culture_records_to_bundles`,
    `library_records_to_bundles`(한국어 컬럼 방언 관대 조회), 단위 테스트 11종을 추가했다.
    category 신설 없이 기존 코드 매핑과 `place_kind` 세부 구분을 사용한다.
  - [x] **T-220b — Dagster 배선.**
    fetch 2종(`(slug, record)` 튜플 스트림, dataset당 `mcst_max_items_per_dataset` 상한),
    record resource 2종(live), `mcst_features.py` asset 2종(slug별 분리 `_load`,
    `McstLoadResult` 합산 metadata), 주 1회 schedule 2종, definitions 배선을 구현했다.
  - [x] **T-220c — fixture/문서.**
    ETL preview fixture 2종(공용 변환 대표 — independent_bookstores/public_libraries),
    `docs/mcst-feature-etl.md`, external-apis §3.14, provider-contract §3/§12,
    `python-mcst-api@d06e8d2` 핀, CHANGELOG를 갱신했다. dedup pair는 실데이터
    매칭 품질 확인 후 재검토한다.

## Phase 6.7 — Feature 사용자 요청 CRUD/versioning (2026-06-08, `T-215`)

- [x] **T-215a — place/event feature 추가·수정·삭제 admin API + versioning.**
  `/admin/features`에 `POST`, `/admin/features/{feature_id}`에 `PATCH`/`DELETE`,
  `/admin/features/change-requests*` 승인/거절 API를 추가했다.
  `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE=require_review|immediate` 설정에 따라
  요청을 `pending`으로 보관하거나 같은 transaction에서 바로 적용한다. provider 적재는
  `data_origin='provider', data_version=0`, 사용자 요청은
  `data_origin='user_request', data_version=1`로 구분하고
  `feature.feature_versions` snapshot을 남긴다. 사용자 요청 삭제는 soft delete이며
  provider 재적재나 snapshot 누락 정리로 되살리지 않는다.
- [x] **T-215b — admin UI feature change queue 화면.** (2026-06-09)
  `/admin/features/change-requests` 화면을 추가해 `GET /admin/features/change-requests`
  목록, add/update/delete 요청 form, approve/reject 동작을 연결했다. 목록 meta에
  `review_mode`를 추가해 `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE` 현재값을 빈 큐에서도
  표시한다. 기존 정본 mutation endpoint만 사용하며 새 중복 REST 표면은 만들지 않았다.
- [x] **T-215c — frontend generated type/e2e workflow 보강.** (2026-06-09)
  OpenAPI 생성 schema 타입 기반 route mock으로 pending→approve→applied, immediate mode
  create, update/delete 요청 생성, soft delete 적용 표시와 action delete 필터 e2e를 추가했다.
  Next RSC prefetch는 mock 범위에서 제외해 document/API 요청을 분리했다.


## Phase 6.6 — REST API v1 정리 후속 (2026-06-08, `T-214`)

전 표면 계약 정본은 `docs/rest-api.md`, TripMate 소비 view는 `docs/tripmate-rest-api.md`.
기준 입력은 `docs/reports/api-endpoint-review-2026-06-08.md`와 TripMate
`docs/integrations/kor-travel-map-rest-api.md`. 사용자 결정으로 `/tripmate/feature-update-requests*`는
admin 영역으로 이동한다.

- [x] **T-214a — REST API 정본 문서 작성.**
  Versioning, envelope, parameter 규약, endpoint naming, 중복 처리, 누락 API를
  종합해 `docs/tripmate-rest-api.md`를 목표 `/v1` 계약과 현재 구현 gap 중심으로
  재작성했다. `docs/openapi-admin-contract.md`, `docs/tripmate-integration.md`,
  `docs/poi-cache-update-targets.md`, `docs/architecture.md`의 충돌 문구도 정리했다.
- [x] **T-214b — 사용자/서비스 API `/v1` prefix 도입.** (2026-06-09)
  `features`/`categories`/`providers` 라우터를 `application.include_router(..., prefix="/v1")`로
  `/v1/*` 노출(`/features/*`(batch 포함)·`/categories`·`/providers/{provider}/last-sync`).
  구 unversioned 경로는 유지하지 않는다(clean cut, alias 없음). liveness `/health`·`/version`은
  비버저닝 유지. `USER_OPERATIONS`·OpenAPI 두 profile·frontend 호출부(`api/features.ts`·
  `api/poiCacheTargets.ts`)·generated type·e2e mock·테스트 일괄 갱신. admin/ops/debug의
  `/v1` 이동은 ADR-048/T-216a에서 처리한다.
- [x] **T-214c — `/tripmate/feature-update-requests*` 제거, admin-only 전환.**
  user OpenAPI와 `USER_OPERATIONS`에서 `POST/GET /tripmate/feature-update-requests*`를
  제거하고 `/admin/feature-update-requests*`만 정본으로 남긴다. TripMate 사용자 제안 큐는
  TripMate app DB 소유로 문서화하고, 운영자 승인 뒤 admin API 호출로 연결한다.
- [x] **T-214d — `/tripmate/*` namespace 제거, batch를 `POST /features/batch`로 일반화.**
  (2026-06-09, 사용자 지시 — kor-travel-map은 TripMate 전용이 아니다.) `tripmate_router` 제거,
  batch를 `features_router`의 `POST /features/batch`로 옮기고 service-token을 route-level
  gate로 유지(ServiceToken scheme 보존). `USER_OPERATIONS`·OpenAPI 두 profile·frontend
  generated type·테스트·문서 일괄 갱신. `/v1` prefix 부여는 T-214b/T-216a에서. 응답은 list
  `items[]`와 충돌하지 않게 `data={found:{feature_id:Feature},missing[]}`로 정렬(후속).
- [x] **T-214e — pagination/parameter 일관성 정리.** (2026-06-09)
  규약 확정: **페이지 가능한 목록 = `page_size`+`cursor`**(search·nearby·admin/ops),
  **bounded 지도 조회 = `limit`**(`/features` flat·`/features/in-bounds` — 뷰포트 로드),
  다중 값 = 단수 반복 query parameter, bbox = `min_lon/min_lat/max_lon/max_lat` 4-float.
  코드: `/v1/features/search`의 CSV `bbox` 제거 → 4-float, `limit`→`page_size`,
  `_parse_bbox_csv` 삭제. `/features` flat은 bounded map이라 `limit` 유지(admin/지도 호환).
  (envelope `meta.page`·`total` opt-in·2-티어 캡 등 심화는 T-216b/c, ADR-048.)
- [x] **T-214f — POI cache target write 표면 결정.** (2026-06-09)
  **결정: TripMate 직접 write 미허용 — admin/operator flow만.** POI cache target
  upsert/delete는 `/admin/poi-cache-targets*`(인프라 SSO + kill-switch)로만 수행하고,
  service-safe `/v1/poi-cache-targets/*` write 경로는 **추가하지 않는다**. TripMate는 등록된
  target 기준 read(`GET /v1/features/nearby/by-target`)만 소비. (rest-api.md·
  tripmate-rest-api.md 명시.)
- [x] **T-214g — error/idempotency/rate-limit/deprecation header 규약 명시.** (2026-06-09)
  규약을 `docs/rest-api.md`에 단일 표로 고정: `X-Request-ID`(구현됨 — 모든 응답),
  problem+json `code` enum(§4), `Retry-After`(LOCK_BUSY/RATE_LIMITED), `Idempotency-Key`·
  `RateLimit-*`·`Deprecation`/`Sunset`(규약 정의 + 적용 시점 명시; idempotency/rate-limit
  구현은 T-216 외부 변경 호출에서). 실제 problem+json 본문 전환은 T-216d.
- [x] **T-214h — endpoint naming cleanup.** (2026-06-09)
  `/debug/health`·`/debug/version` **제거**(ADR-048 clean cut — 공용 `/health`·`/version`과
  중복). `health.py`/`version.py` 라우터 삭제, app.py/__init__ 정리, 상태확인은
  `/health`·`/version`(public_status) + `/ops/health-deep`(readiness)로 수렴. frontend
  `useHealth`/`useVersion`을 public `/health`·`/version`(envelope) 소비로 repoint.
  `dedup-review`/`enrichment-review` **복수화는 T-216e(major 컷)로 이월** — 본 task에선
  결정만(소비자 영향 큰 path 개명은 ADR-048 명명 묶음에서 일괄).


## 문서 정합성 백로그 (T-DA, 2026-06-06)

문서 전수 정합성 감사 결과. 전체 지적·근거·파일위치·의사결정은
**`docs/reports/docs-consistency-audit-2026-06-06.md`** 가 정본. task id는 `T-DA-NN`,
사용자 결정은 `DA-D-NN`. 사용자 결정(DA-D-01 포인터 대체 / DA-D-02 한 PR 반영)에
따라 T-DA-01~10은 **본 배치에서 반영 완료**.

- ~~**T-DA-01** CLAUDE.md §2 "현 단계" 전면 stale(PR#149/Sprint4 완료)~~ ✅ DA-D-01(A)
  포인터 대체.
- ~~**T-DA-02** CLAUDE.md geocoding 로컬 포트 `8888`~~ ✅ → `12201`(`.env.example` 정합).
- ~~**T-DA-03** CLAUDE.md ADR "001~046 / 다음 047"~~ ✅ → "001~047 / 다음 **048**".
- ~~**T-DA-04** AGENTS.md "코드 작성 단계"(PR#156) stale~~ ✅ 포인터 대체.
- ~~**T-DA-05** sprints/README "현 위치"(PR#149) + Sprint5 "🟡 진입 준비"~~ ✅ 포인터
  대체 + "🟢 진행 중".
- ~~**T-DA-06** category 개수 "141건" 표기(코드=144)~~ ✅ category.md/debug-ui-package.md/
  decisions.md 라벨을 **144**로 통일(§4 트리는 이미 ADR-027 3건 포함 완성 상태였음).
- ~~**T-DA-07** architecture.md 큰그림 의존체인에서 `category` 누락~~ ✅ 추가.
- ~~**T-DA-08** decisions.md ADR-025 "Next.js 15"/"port 8610" 현행 교차참조 없음~~ ✅
  현행 기준 note 추가(역사 본문 보존).
- ~~**T-DA-09** decisions.md ADR-002 체인이 `api` 포함·`category` 누락~~ ✅ 현행 체인
  note 추가.
- ~~**T-DA-10** decisions.md ADR-036 제목 `v0.1.0`~~ ✅ 현행 핀 v0.1.2 note 추가.
- ~~**T-DA-12** CLAUDE.md §5 "전체 22개 룰은 SKILL.md §4"(실제 26개)~~ ✅ → **26개**.
- ~~**SKILL.md 2차 스윕**: §8 ADR "001~046/047" + §9 "코드 작성 단계" 상태 블록
  (PR#149/Sprint4 완료)~~ ✅ T-DA-01/03과 동일 처리(포인터 대체 + 001~047/048).
- ~~**README.md 3차 스윕**: 상단 "현재 상태"(PR#155/#156/Sprint4 완료) 블록 + "빠른 시작
  (Sprint 4 완료…)" 헤더~~ ✅ T-DA-01과 동일 처리(DA-D-01(A) 포인터 대체, 기준값만
  유지). entry doc 4종(CLAUDE/AGENTS/SKILL/README) 상태 블록 drift 모두 정리 완료.
- **T-DA-11** `openapi-admin-contract.md` ↔ 구현 endpoint/error/log 전수 대조 —
  외부 노출 API 한정으로 **수행함**(감사 §8 = 아래 T-DA-13~17). 라우터별 세부
  contract 전수는 계속 `T-212a`/`T-212c`로 위임.

### 외부 노출 API 일관성/완결성 (감사 §8, 2026-06-06 추가)

생성 spec(`openapi.json` 35 path / `openapi.user.json` 7 path) ↔ contract 문서 대조.
코드 영향이 있어 본 문서 PR과 분리(결정 DA-D-03/04 확정 후 반영).

- ~~**T-DA-13** (MED, 빠진 기능, **DA-D-04 = T-212 묶음**) `/admin/issues`
  GET/GET{id}/PATCH(resolve/ignore/reopen/retry_geocode/retry_reverse_geocode/
  apply_kor_travel_geo_address/manual_override)~~ ✅ **구현 완료(2026-06-07)**. ADR-046
  주소/좌표 이슈 운영자 수동 처리 API. `routers/admin_issues.py`(목록 keyset cursor +
  단건 detail + PATCH 7 action) + 신규 `infra/feature_address_repo.py`(feature.features
  UPDATE + `ops.feature_overrides` upsert) + kor-travel-geo `geocoding` 정/역지오코딩.
  `{data, meta}` envelope. 단위 14 + PostGIS 통합 3 테스트. 목록 `q`(message/feature_id/
  source_record_key ILIKE) + `bbox`(연결 feature 4326 GiST `&&`) 필터도 구현 완료
  (`ops_repo` 확장 + 통합 테스트). admin UI(승인/거절 화면)는 **T-212b** 별도 에이전트
  후속.
- ~~**T-DA-14** (LOW, doc) contract §4 표 `admin-providers` 미구현 표기 누락~~ ✅
  "(미구현 — T-207b 취소, feature-update-requests provider_dataset scope 대체)" 표기.
- ~~**T-DA-15** (MED, API 일관성, **DA-D-03 = 전면 통일**) list 응답 셰입 이원화
  (`{data,meta}` vs `{count,items,next_cursor}`) → 전면 envelope 통일~~ ✅ 3 flat list
  라우터 모두 `data.{items,next_cursor}` + `meta.{count,duration_ms}`로 통일.
  - [x] `/admin/feature-update-requests` (#250, 2026-06-06).
  - [x] `/admin/offline-uploads` (#251, 2026-06-06).
  - [x] `/admin/poi-cache-targets` (2026-06-06).
- ~~**T-DA-16** (MED, API 일관성, **DA-D-03 = 전면 통일**) 단건 응답 envelope 불일치
  (bare object 6종 + import-jobs/{id} `{data}`만) → `{data,meta}` 통일~~ ✅ 감사 열거
  단건 전부 통일 완료(추가 발견 nux-seen은 T-DA-18로 분리).
  - [x] `/admin/feature-update-requests/{id}`·`/tripmate/feature-update-requests/{id}`
    → `{data, meta}` (#250, 2026-06-06).
  - [x] `/admin/offline-uploads/{id}` → `{data, meta}` (#251, 2026-06-06).
  - [x] `/admin/poi-cache-targets/{id}` → `{data, meta}` (#252, 2026-06-06).
  - [x] `/ops/metrics` → `{data: OpsMetricsData, meta:{duration_ms}}`,
    `/ops/import-jobs/{job_id}` → `meta.duration_ms` 추가 (#253, 2026-06-06).
  - [x] `/ops/dagster/summary` → `{data: DagsterSummaryData, meta}`,
    `/debug/mois-license/{id}` → `{data, meta(cached, duration_ms)}` (2026-06-06).
- ~~**T-DA-18** (LOW, API 일관성, **DA-D-03 추가 발견**) `POST /ops/dagster/nux-seen`
  flat bare → `{data, meta}`~~ ✅ `DagsterNuxSeenData` + envelope, 4 return을
  `_nux_seen_response` 헬퍼로 wrap. 프런트 `useMarkDagsterNuxSeen` 본문 미소비라
  소비측 무변(2026-06-06). **DA-D-03 전면 통일(T-DA-15/16/18) 코드 전환 완료.**
- ~~**T-DA-17** (INFO) contract 문서 구현/미구현 혼재 표기~~ ✅ §4 표·§4.1 미구현 배지
  반영(전체 endpoint 상태 컬럼화는 T-212c).
- **DA-D-03 = 전면 통일** (확정) — 코드 전환은 별도 PR(T-DA-15/16). 본 PR은 표준 문서화.
- **DA-D-04 = T-212 묶음** (확정) — `/admin/issues`는 T-212b/c. 본 PR은 미구현 배지.


## 코드 리뷰 후속 백로그 (PR#181~#233, 2026-06-06)

직전 리뷰(#153~#179) 이후 머지된 비-T-RV 실질 PR(정합성 Phase 2 F5~F8 / T-200
batch gate / 운영 게이트 T-202~204 / T-208i 등)을 상세 리뷰한 결과. T-RV-\* 구현
PR과 T-DA 문서 PR(#227/#230)은 리뷰 생략. 정본은
**`docs/reports/pr-181-233-review-2026-06-06.md`**. 신규 지적은 **전부 LOW**(관측
전용 WARN 케이스의 count 의미/성능) — 운영 진입을 막지 않는다. (검토 중 세운 F5
join fan-out·F7 score 스케일 risk는 schema PK/CHECK로 해소 = 결함 아님.)

- ~~**T-RV-38** (LOW, consistency F8) `infra/consistency.py:529-557` — file row가
  `feature_missing` + `metadata_missing_object` 동시 충족 시 count 2 증가(distinct
  orphan보다 과다).~~ ✅ `count`는 distinct metadata/object row 기준으로 dedup하고,
  세부 문제유형은 `sample_ids`와 `metadata`에 보존한다.
- ~~**T-RV-39** (LOW, consistency F4/WARN) `infra/consistency.py:400-410` — F4 임계
  초과 시 `count=pending`(백로그 전체 수)이 `total_violations`/`by_severity.WARN`에
  혼입.~~ ✅ 임계 초과형 `count=1`, 실제 pending/threshold는
  `metadata.pending_count`/`summary.case_metadata.F4`에 분리한다.
- ~~**T-RV-40** (LOW perf, consistency F6) `infra/consistency.py:146-185` — F6가
  `feature.features`를 LATERAL `jsonb_path_query`로 4회 풀스캔.~~ ✅
  `candidate_features` CTE로 삭제되지 않고 detail 후보가 있는 feature를 한 번만 읽고,
  4개 JSONPath period 추출은 단일 `CROSS JOIN LATERAL` 안으로 모았다.
- ~~**T-RV-41** (LOW 전제, batch_dag) `infra/batch_dag.py:454-460` — `CONCURRENTLY`
  refresh는 MV UNIQUE 인덱스 + 사전 populate 전제. 현재 MV 없어 latent.~~ ✅
  **`T-101`** MV 도입 체크리스트와 performance/Dagster 문서에 UNIQUE 인덱스 +
  최초 비-concurrent populate 전제를 고정했다.


## 코드 리뷰 후속 백로그 (PR#153~#179, 2026-06-04)

리뷰 없이 머지된 ADR-045 구현 배치(#153~#179)를 영역별 상세 리뷰한 결과.
전체 지적·근거·파일위치는 **`docs/reports/pr-153-179-review-2026-06-04.md`** 가
정본. task id는 `T-RV-NN`. 권장 처리 순서는 리포트 §5.

**HIGH (운영/계약/보안 — 선반영):**
- ~~**T-RV-01/02** Dagster 운영 형상 (D-2): metadata를 별도 `kor_travel_map_dagster`
  Postgres DB로 (현재 SQLite 폴백) + `dagster dev`→webserver/daemon 분리.~~
  ✅ `dagster-db-init`, `dagster` webserver, `dagster-daemon`,
  `docker/dagster.yaml` Postgres storage, `dagster-postgres` dependency와 compose
  회귀 테스트를 추가했다.
- ~~**T-RV-03** Dagster `kor_travel_map_client` resource engine dispose 누수.~~
  ✅ generator resource로 전환해 run/tick 종료 시 `AsyncEngine.dispose()`를 호출하고,
  running event loop 안에서도 teardown이 동작하는 회귀 테스트를 추가했다.
- **T-RV-04** Dagster provider 서비스키 resource 미구현(D-15, feature-load asset
  provider fetcher 기본 wiring 미완료).
  - ✅ **T-RV-04a**: provider record key별 guard resource와
    `KOR_TRAVEL_MAP_*` credential env mapping을 등록했다. 기본 `defs`는 더 이상 generic
    `_missing_resource`로 죽지 않고, resource materialize 시 provider/package/env
    안내를 내며 secret 값을 숨긴다.
  - **T-RV-04b**(✅ 완료 2026-06-08, provider 순차 wiring): provider public client live fetcher를
    실제 record iterable로 연결. 패턴 = `provider_fetchers.fetch_<provider>(settings)`
    (lazy provider import, credential 없으면 guard 메시지) + `resources.
    build_provider_record_live_resource(spec, fetch)`로 해당 resource_key만 guard→live 교체.
    - [x] **datagokr_cultural_festivals**(festival, #261) — `DataGoKrClient.festival.
      iter_all()`. dagster 단위 테스트(fake client) + 37 dagster suite green.
    - **나머지 6종은 설계 결정 선행 필요** — 적합성 감사
      `docs/reports/t-rv-04b-provider-fetcher-audit-2026-06-07.md`. 요약:
      - [x] **krheritage_events**(2026-06-07) — **ADR-044 재조정 + wiring**. 검증 결과
        `HeritageEvent` 필드명(starts_on/ends_on/place/tel_name/address)이 krtour Protocol
        (start_date/venue_name/...)과 불일치 + `raw` 부재. 조치: **upstream PR**
        `python-krheritage-api#4`(HeritageEvent.raw 주입, sibling 모델 정합, merged) +
        krtour `KrHeritageEvent` Protocol/transform을 provider 필드명에 맞춰 재정렬(+테스트).
        fetcher = `HeritageClient.event.iter_months()`(provider 기본 rolling window
        months_back=1/ahead=12). dagster fetcher 단위(fake) + 39 dagster suite green.
      - [x] **krex_rest_areas**(2026-06-07) — ADR-044 재정렬 + **option 2 파생 자연키**.
        `RestArea`에 안정 id·address 없음(사용자 결정: 안정키 있으면 사용·없으면 파생) →
        `_rest_area_natural_key`=`name::route_name::direction`(`|`는 ADR-009 예약 → `::`).
        Protocol을 RestArea 필드명(route_name/lat/lon/phone_number)으로 재정렬, uni_id/address
        제거. admin etl_fixtures/etl_live 어댑터도 갱신. provider 측 안정 id/address 노출은
        **upstream 이슈 `python-krex-api#7`**로 분리(AI agent 작업용). fetcher=`restarea.
        list_all` 페이지네이션, dagster 단위 + 통합 green.
      - [x] **krex_traffic_notices**(2026-06-07) — ADR-044 재정렬: Protocol을 `Incident`
        실제 shape(route_no/incident_type/message/started_at/ended_at/raw)로, krtour-side
        파생(notice_id=`::` 복합키+payload_hash, title 합성, notice_type=normalize, valid_from·
        until=방어적 파싱, severity=None, source_agency="한국도로공사", coord=None).
        coordless notice는 raw_address=route로 strict 검증 통과. fetcher=`traffic.incident`
        페이지네이션(`krex_ex_api_key`). **잔여(krtour follow-up)**: EX `incidentType`
        숫자코드→notice_type 매핑 테이블(현재 대부분 "traffic" 기본값). 일시적 incident의
        영속 Feature 적재 = 재실행 갱신 + `valid_until` 만료(설계 메모).
      - [x] **opinet_stations** — provider 보강 + krtour wiring(bbox+POI-타깃) 완료(2026-06-08).
        조사 결론(2026-06-07): OpiNet OpenAPI에 지역/전국 bulk 주유소 목록 엔드포인트가
        **물리적으로 없음**(station 반환은 aroundAll 반경≤5km/lowTop10 top20/detailById 단건뿐,
        나머지는 코드/가격 집계). `python-opinet-api#7` 코멘트로 결론 기록.
        - [x] **provider 보강**(`python-opinet-api#8` merged, **v0.2.0**): `iter_stations_in_bbox()`
          (sync+async) — bbox를 aroundAll 반경 격자(`radius*√2`)로 덮고 `uni_id` dedup하는
          **근사 enumeration**. 한계(면적 비례 호출수 급증→bounded 권장, tel/lpg_yn 부재→detail
          N+1) README/docstring 명시.
        - **krtour wiring 후속** — 사용자 결정(2026-06-08): **bbox + POI-타깃 둘 다 지원**. 3 PR:
          - [x] **opinet-1 ADR-044 재정렬**(2026-06-08) `OpinetStationItem` Protocol을 provider
            `Station` 필드명(uni_id/name/brand/address_road/address_jibun/lon·lat float)에 정렬,
            `tel`/`lpg_yn`은 `StationDetail` 한정이라 Protocol 필수에서 빼고 transform이 `getattr`로
            보강(`Station`이 그대로 만족). `stations_to_bundles`/ETL fixture/etl_live 어댑터/단위·통합
            테스트 갱신. 게이트: ruff/mypy(map 85/admin 26)/unit+lint 965(coverage 81%)/full 1168 green.
          - [x] **opinet-2 bbox fetcher**(2026-06-08): settings `opinet_scope_mode`(disabled/bbox/
            poi_cache_target) + `opinet_scope_bbox` + `opinet_scope_radius_m` + `fetch_opinet_stations`
            (`OpinetClient.iter_stations_in_bbox`, uni_id dedup, finally close) + resource guard→live
            (기존 `feature_place_opinet_stations` asset 그대로 소비). poi_cache_target 모드는 명확
            guard로 opinet-3 대기. 게이트: ruff/mypy(map 85/dagster 13/admin 26)/lint-imports/unit+lint
            965(coverage 81%)/full 1168/dagster 85 green.
          - [x] **opinet-3 POI-타깃**(2026-06-08): `fetch_opinet_stations`의 `poi_cache_target`
            분기 연결. `_opinet_poi_target_bboxes`가 `settings.pg_dsn`(async)→sync psycopg DSN으로
            `ops.poi_cache_targets`의 opinet 활성 target(lon/lat/radius_km, update_enabled,
            non-deleted) 조회 → `_center_radius_to_bbox`(위경도 근사)로 bbox 변환 → 기존
            `_enumerate_opinet_stations`로 enumerate(target 간 uni_id dedup). 단위(math/enumerate/
            empty) + 통합(`test_opinet_poi_scope` 실 PostGIS seed→조회) 테스트. **→ T-RV-04b 완전 종료.**
            - **리뷰 수정(#304, 2026-06-08)**: `external_system`은 provider명이 아니라 외부 호출자
              (tripmate 등) — `='opinet'` 필터 제거(실제 등록 target 누락 P1). active 정의를
              `scope_repo`와 동일하게(`deleted_at` 없음 + `update_enabled` + `refresh_policy<>'disabled'`
              P2) + opinet `provider_overrides` `targeted_policy='disabled'` 옵트아웃 제외. 통합
              테스트를 tripmate/kakao + disabled/update-off/deleted/optout seed로 회귀 보강.
              게이트: ruff/mypy(3pkg)/lint-imports/dagster 87/coverage 81%/POI 통합 green.
      - [x] **mois_license_records**(Phase B, 2026-06-07) — clean match(provider `PlaceRecord`이
        `MoisLicensePlaceRecord` Protocol 전부 충족, 재조정 불요). fetcher
        `fetch_mois_license_records`가 미리 sync된 MOIS 소스 SQLite DB(설정
        `mois_source_db_path`, env `KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH`)에 sqlite Session 열고
        `mois.db.iter_open_place_records(service_slugs=PROMOTED_SERVICE_SLUGS)` stream. DB
        부재 시 명확 실패. dagster 단위(temp-DB 실측 + guard) green.
        - [x] **mois Phase A(소스 DB sync)**(2026-06-07) — `mois_source_sync.py`:
          순수 helper `sync_mois_source_db(settings, service_slugs=None)` + Dagster op
          `mois_localdata_source_sync` + job + 주간 schedule(STOPPED, `0 4 * * 1` KST).
          provider `mois.create_sqlite_schema` → keyless `LocalDataFileClient` →
          `sync_localdata_source_db(service_slugs=PROMOTED_SERVICE_SLUGS, commit=True)`로
          LOCALDATA 다운로드→소스 DB 적재. **정정: 공개 파일 포털(`file.localdata.go.kr`)
          이라 API key 불요(네트워크만 필요)** — provider `LocalDataFileClient`에 key
          파라미터 없음. dagster 단위(fake mois 5 + op + schedule) green. 실데이터 검증은
          T-212e.
      - [x] **knps_point/geometry**(2026-06-07) — **provider 보강**으로 해결. 사용자
        지시(적극 수정)대로 `python-knps-api#7`(merged, v0.2.0)에 헤더 정규화 typed
        record(`KnpsPlaceRecord`/`KnpsGeoRecord`) + `read_place_records`/`read_geo_records`
        추가. krtour는 best-guess 컬럼 매핑 폐기, provider typed record 직접 소비.
        fetcher는 **async generator**(다운로드/파싱 async)이고 live builder를
        `Iterable | AsyncIterator`로 확장. dataset key(`knps_visitor_centers`/`knps_trails`)는
        settings 값을 fetcher/asset이 공유(`SETTINGS_VALUE_RESOURCES`). keyless라 credential
        불요. dagster 단위(fake knps client) green. 실 fetch 검증은 T-212e.


## 최근 완료 (2026-05-31~2026-06-03)

- **T-208h** (2026-06-03): `/admin/offline-uploads*` backend와 admin UI 기본
  upload 화면을 추가했다. JSON/JSONL `FeatureBundle` 파일을 RustFS/S3 store에 쓰고,
  `ops.offline_uploads` row 생성/list/detail, Dagster GraphQL
  `offline_upload_load` launch까지 연결했다. CSV/TSV validation/column mapping은
  T-208i로 남긴다. WSL live smoke에서 upload → Dagster `SUCCESS` → DB
  `loaded/done/progress=100`을 확인했고, Windows Playwright `admin-ops.spec.ts`는 새
  `/admin/offline-uploads` route 포함 6/6 통과했다.
- **T-208b 후속** (2026-06-03): RustFS/S3 호환 `offline_upload_store` resource와
  Docker RustFS bucket init을 구현했다. API `12101`, console `12105`, bucket
  `kor-travel-map`/`krtour-uploads` 기준으로 실제 put/get smoke를 확인했다.
- **T-208f** (2026-06-03): `consistency_dedup_refresh` Dagster maintenance job을
  추가했다. DB에 적재된 provider/dataset scope를 다시 읽어 pair/sibling dedup 후보를
  큐에 upsert하고, 이어서 F1~F4 consistency report를 저장한다. schedule은
  `consistency_dedup_refresh_daily_schedule`이며 기본 `STOPPED`다.
- **T-211b** (2026-06-03): admin frontend 전역 app shell/navigation, 운영 홈
  dashboard, `/ops/import-jobs`, `/ops/consistency`, `/admin/dedup-review`,
  `/admin/feature-update-requests`, `/admin/poi-cache-targets` 화면을 최신 REST/Dagster
  계약에 맞춰 구현했다. `/admin/dagster`는 Dagster webserver embed와 자체 summary
  UI를 함께 보여주며 schedules/sensors 정보를 노출한다.
- **T-211a** (2026-06-03): admin UI 최신화 선행 gap audit과 typed frontend API
  layer를 추가했다. `/ops/import-jobs` 정본, `/features/nearby/by-target` 범위,
  backend gap을 문서화하고 화면 구현 선행 조건을 정리했다.
- **T-208d** (2026-06-03): `packages/kor-travel-map-dagster`에 Feature 적재 asset 9개의
  KST schedule과 asset job을 등록했다. 모든 schedule은 `Asia/Seoul` 기준이고,
  외부 API 호출 분산을 위해 분/요일을 나눴으며 기본 status는 `STOPPED`다.
- **T-207g** (2026-06-03): OpenAPI export를 admin 전체
  `packages/kor-travel-map-api/openapi.json`과 TripMate/user subset
  `packages/kor-travel-map-api/openapi.user.json`으로 이원화했다. CI drift gate는
  `--profile all --check`로 두 산출물을 함께 검증한다.
- **T-207e** (2026-06-03): `GET /features/in-bounds`, `GET /features/search`,
  `GET /features/{feature_id}` envelope 상세, `POST /tripmate/features/batch`를
  연결. 기존 `GET /features` bbox raw 응답은 admin frontend 호환용으로 유지하고,
  TripMate/public 응답은 `{data, meta}` envelope로 분리했다.
- **T-207d** (2026-06-03): `/ops/metrics`, `/ops/import-jobs`,
  `/ops/import-jobs/{job_id}`, `/ops/consistency/reports`,
  `/ops/consistency/issues` backend를 연결. `infra.ops_repo`는 import job,
  consistency report, data integrity issue를 read-only keyset cursor로 조회한다.
- **T-207c** (2026-06-03): `/admin/features` 목록/비활성화, `ops.feature_overrides`
  `prevent_provider_reactivation`, provider upsert status 보호, `/admin/dedup-review`
  목록/결정/merge backend를 연결. 이후 T-215a에서 사용자 요청 기반 place/event
  추가·수정·soft delete API를 붙였다. hard delete와 별도 audit log는 여전히 후속이다.
- **PR#168** (merged 2026-06-03): Dagster `feature_update_request_queue_sensor` +
  `feature_update_request_worker` + failure sensor. queued/now request를
  `AsyncKorTravelMapClient.execute_feature_update_request()`로 실행하고, 실패 시
  request/import job 실패 전이와 notifier payload를 보강.
- **PR#167** (merged 2026-06-03): `/admin/poi-cache-targets` admin API와
  `/features/nearby/by-target` summary 조회. target CRUD/list/detail/delete,
  PostGIS `coord_5179` 거리 조회, filter/sort/cursor, OpenAPI export, unit/integration
  테스트.
- **PR#166** (merged 2026-06-03): `/admin/feature-update-requests` admin API. POST(dry-run/actual),
  GET(list/detail), cancel, run-now 재큐잉, OpenAPI export, list filter 통합 테스트.
- **PR#165** (merged 2026-06-03): `infra.feature_update_executor`, `cache_target_keys`
  resolver, target link 재계산, provider refresh policy skip, runner 기반 DB 적재 통합
  테스트.
- **PR#164** (merged 2026-06-03): `alembic 0009`로
  `ops.data_integrity_violations`, `ops.poi_cache_targets`,
  `ops.poi_cache_target_feature_links`, `ops.provider_refresh_policies`를 추가하고,
  ORM row + raw SQL repo + PostGIS 통합 테스트를 구현.
- **PR#163** (merged 2026-06-03): T-206a-geo 검증 완료 문서화 +
  RustFS dev compose 예시 host port `12101`/`12105` 정렬.
- **PR#162** (merged 2026-06-03): `AsyncKorTravelMapClient` feature update request
  메서드 4종 + top-level client export + RustFS 포트 12101/12105 문서 정렬.
- **T-206a-geo 확인** (2026-06-03): `kor-travel-geo` main의
  `/v2/regions/within-radius` 구현과 optional 실제 PostGIS 테스트를 재검증.
  WSL targeted test `15 passed, 1 skipped`, 로컬 12201 server smoke는 `sigungu`
  `11650`(서초구) contains 응답 확인.
- **PR#161** (merged 2026-06-03): `infra.feature_update_repo` request/import job
  lifecycle repository + kor-travel-geo REST API 로컬 포트 12201 문서/설정 정렬.
- **PR#160** (merged 2026-06-03): `infra.scope_repo` scope resolver.
- **PR#159** (merged 2026-06-03): `ops.feature_update_requests` Alembic 0008 +
  ORM 매핑 + DDL 계약 통합 테스트.
- **PR#158** (merged 2026-06-02): Docker API 컨테이너의 Dagster URL을
  `KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL` 기본값(`http://dagster:12302`)로 분리.
- **PR#157** (merged 2026-06-02): admin UI `/admin/dagster` + backend
  `GET /ops/dagster/summary` + Dagster webserver embed.
- **PR#156** (merged 2026-06-02): Docker 이미지/compose, API `12301`, admin UI
  `12305`, Dagster `12302` 고정 포트, `.env` key mapping, 기동/포트 종료 스크립트.
- **PR#155** (merged 2026-06-02): kor-travel-map-owned Dagster Feature ETL 1차.
  `packages/kor-travel-map-dagster/` code location과 9개 Feature asset runner, PostGIS
  적재 통합 테스트.
- **PR#114** (merged 2026-05-31): geocoding live 기본 포트 정합(현재 12201),
  Next.js 16 + `maplibre-vworld-js#v0.1.2`, GDAL 3.8.4 고정, Windows Playwright
  e2e 14/14, 관련 문서 갱신.
- **PR#110~#112**: Windows Git + NTFS source-of-truth 정책, WSL 실행/Playwright
  분리, journal/resume 정책 로그 보강.
- **PR#96~#100**: Sprint 4 prep, `/features` UX 보강, map-marker-react 구현,
  direct-main push revert와 통합 검증 보고서 재적용.


## 완료 이력 (Sprint 2)

- **PR#49** (merged 2026-05-28): `maplibre-vworld` v0.1.0 의존 핀 정합 — 기존
  `^1.0.0`은 이중 오류(버전 미존재 + npm 미게시) → `github:digitie/maplibre-
  vworld-js#v0.1.0` git URL+tag 핀 + `zod ^4.4.3`(peer) + ADR-036 amendment.
- **PR#48** (merged 2026-05-28): agent worktree 접두사 `geo-*` → `kor-travel-map-*`
  일괄 rename (7 normative docs) + 본 `tasks.md` 최신화 (PR#19~#47 반영).
- **PR#47** (merged 2026-05-28): 디버그 UI ETL preview `?source=live` 활성화 +
  8 provider API key(`SecretStr`) settings + `.env.example`. KMA 3 dataset
  (short/nowcast/ultra_short_forecast) 실 호출, 나머지 8은 framework(501).
  `etl_live.py` httpx async loader + LIVE_LOADER_REGISTRY. **CI red 3종 동반
  해소**: httpx dep 누락 / Alembic 1.18 `path_separator` deprecation /
  Alembic 1.18 async migration commit 안 됨(env.py) / coord_5179 assert
  대소문자. 450+21 green.
- **PR#46** (merged): KMA weather_alerts → notice FeatureBundle (alert×region
  fan-out) + krex TRAFFIC_NOTICE_CATEGORY 99000000 정정 + ETL preview registry
  11 dataset.
- **PR#45** (merged): Sprint 2 §2.4 krex 휴게소 multi-kind — 4 Protocol + 4
  변환(rest_areas place / prices food|fuel / weather observed / traffic notice)
  + 동일 feature_id 통합 검증.
- **PR#44** (merged): 디버그 UI ETL preview 라우터 3종 (`providers`/`{provider}/
  datasets`/`{provider}/{dataset}/preview`) + frontend `etl/page.tsx`. dry-run.
- **PR#43** (merged): Sprint 2 §2.3 마무리 — opinet `stations_to_bundles`
  (gas station place Feature, category 06020000).
- **PR#42** (merged): Sprint 2 §2.3 진입 — `PriceValue` DTO + `PriceDomain` +
  `make_price_value_key` + opinet `prices_to_values`.
- **PR#41** (merged): KMA `ultra_short_forecast_to_weather_values`
  (getUltraSrtFcst) + LGT(낙뢰) metric.
- **PR#40** (merged): `python-*-api` 라이브러리 status sweep — pyproject
  `[providers]` extra Sprint 그룹화 + provider-contract §12 git URL/sha 표.
- **PR#39** (merged): KMA `ultra_short_nowcast_to_weather_values` + `core/
  weather.py` pure 헬퍼 5종.
- **PR#38** (merged): Sprint 2 §2.2 진입 — `WeatherValue` DTO + 3 enum
  (WeatherDomain/ForecastStyle/TimelineBucket, ADR-010) + `make_weather_value_
  key` + KMA `short_forecast_to_weather_values`.
- **PR#37** (merged): ADR-041 본격 구현 — `python-kraddr-base` 의존 제거,
  `Address` DTO 보강 + `core/address.py` (bjd/phone/한글 정규화 utility).
- **PR#36** (merged): 디버그 UI frontend skeleton — Next.js 15 + React 19 +
  TanStack Query + Zustand (ADR-037) + map-marker-react `private:true` (ADR-043).
- **PR#35** (merged): 디버그 UI backend 첫 라우터 — `create_app` factory +
  `/debug/health` + `/debug/version` + `openapi.json` drift gate 활성 (ADR-031).
- **PR#34** (merged): Sprint 2 §2.1 datagokr 표준데이터 축제 1차 source
  (`cultural_festivals_to_bundles`, ADR-042).
- **PR#30~33** (merged): agent worktree + codegraph 룰 docs / codegraph MCP /
  거버넌스 보강 + ADR-035~043 proposed→accepted 일괄 전환.
- **PR#28~29** (merged): Sprint 2 prep — `infra/models.py` + Alembic 첫 2
  revision / `core/scoring.py`(ADR-016) + `core/providers.py`.
- **PR#19~27** (merged): Sprint 1 scaffolding (dto/core/infra) + review P0/P1
  해소. 상세는 `docs/journal.md`.
- **upstream knps-api PR#1** (https://github.com/digitie/python-knps-api/pull/1):
  maki icon 정정 (shelter / barrier).


**Phase 1 — DB 스키마 (alembic/models)**
- [x] T-205a — `alembic 0008` + `FeatureUpdateRequestRow` (`ops.feature_update_requests`,
  DDL은 `openapi-admin-contract.md §6.1`). 본 PR은 schema/ORM/DDL 검증까지만 포함하고
  scope resolver/repository는 T-206에서 분리.
- [~] T-205b — ~~`feature.sigungu_boundaries`~~ **취소**(D-11: 경계는 kor-travel-geo
  소유, kor-travel-map은 REST 호출). → T-206a-geo로 대체.
- [x] T-205c — (Phase 2) `ops.data_integrity_violations`
  (F5~F8) / `ops.poi_cache_targets` + `_feature_links` /
  `ops.provider_refresh_policies`. 본 PR에서 `alembic 0009`, ORM row, raw SQL repo,
  PostGIS schema/repo 통합 테스트를 추가했다. `cache_target_keys` scope와 provider별
  update 주기/rate limit enforcement는 T-206d 실행 본체에서 사용한다.
- [x] T-205d — `import_jobs` batch 컬럼(`load_batch_id`/`parent_job_id`, T-200 연계, D-6).
  `alembic 0012`, ORM, `jobs_repo`, `/ops/import-jobs` 조회·필터, admin UI 목록
  표시, migrated PostGIS 통합 테스트를 추가했다.


**Phase 2 — 로직 (scope resolver + 큐 브리지)**
- [x] T-206a — `infra/scope_repo.py` (resolve feature_ids/center_radius/bbox/
  sigungu_by_radius/provider_dataset + `count_features_matching_scope` dry_run).
  `sigungu_by_radius`는 kor-travel-geo `/v2/regions/within-radius` 호출(D-11).
  DB repo는 kor-travel-geo client를 직접 import하지 않고 async resolver를 주입받는다.
  `cache_target_keys` resolver는 T-206d에서 `ops.poi_cache_targets` 기반으로 완료.
- [x] T-206a-geo — (형제 repo `kor-travel-geo`) `POST
  /v2/regions/within-radius` 엔드포인트와 optional PostGIS 실데이터 테스트가
  `kor-travel-geo` main(PR #114/#115 계열)에 반영됨을 재검증했다. kor-travel-map은
  REST v2 계약/로컬 포트 `12201`/resolver 주입 경계를 유지한다.
- [x] T-206b — `infra/feature_update_repo.py` (enqueue/claim/start/finish/get/list/cancel,
  advisory lock + SKIP LOCKED, keyset cursor D-10).
- [x] T-206c — `AsyncKorTravelMapClient` feature-update 메서드 4종.
- [x] T-206d — request 실행 본체(scope→provider/dataset 역추적 refresh, D-6/D-8).
  runner 주입형 `infra.feature_update_executor`, `cache_target_keys` resolver, target
  link 재계산, provider refresh policy skip, `AsyncKorTravelMapClient` 실행 메서드.


**Phase 3 — FastAPI 라우터 (`kor-travel-map-admin` 패키지)**
- [x] T-207a — `/admin/feature-update-requests` CRUD + cancel + run-now (§5).
  실제 provider/Dagster 직접 실행 대신 `run_mode='now'` request 재큐잉까지 연결했다.
- [x] T-207f — `/admin/poi-cache-targets` + `/features/nearby/by-target` (Phase 2,
  PR#167). target CRUD/list/detail/delete와 by-target summary/cursor 조회를 연결했다.
- [x] T-207b — `/admin/providers/{p}/datasets/{d}/runs` (§7). 사용자 결정에 따라
  구현하지 않음으로 닫는다. provider run 상세는 T-207d `/ops/*`와 Dagster UI/summary
  경로에서 필요한 만큼 다룬다.
- [x] T-207c — `/admin/features` 검토/병합/override/deactivate (D-8).
  `/admin/features` 목록과 deactivate, active status override, provider upsert
  재활성화 방지, `/admin/dedup-review` 목록/accepted/rejected/ignored/merged 전이를
  연결했다. 이후 T-215a에서 `POST /admin/features`, `PATCH`/`DELETE /admin/features/{id}`
  사용자 요청 API를 추가했다. `DELETE`는 user-request soft delete이며, hard delete와
  별도 admin audit log는 후속 작업으로 남긴다.
- [x] T-207d — `/ops/*` consistency/jobs/metrics. `GET /ops/metrics`,
  `GET /ops/import-jobs`, `GET /ops/import-jobs/{job_id}`,
  `GET /ops/consistency/reports`, `GET /ops/consistency/issues`를 연결했다.
- [x] T-207e — `/features/*` + `/tripmate/features/batch` (사용자, `tripmate-rest-api.md`, D-7).
  `GET /features/in-bounds`, `GET /features/search`, envelope 상세, TripMate batch
  상세 조회를 연결했다. 기존 `GET /features` raw bbox 응답은 admin frontend 호환용으로
  유지한다.
- [x] T-207g — OpenAPI export 이원화(admin/user) + drift gate (ADR-031 amend, D-3).
  `scripts/export_openapi.py --profile all`이 admin 전체 spec과 TripMate/user subset
  spec을 함께 생성하고, CI drift gate도 두 산출물을 모두 비교한다.


**Phase 4 — Dagster (kor-travel-map 독립 구현)**
- [x] T-208a — `packages/kor-travel-map-dagster/` 골격 + definitions. 메인
      `kortravelmap`은 Dagster를 import하지 않고 별도 `kortravelmap.dagster`
      package가 code location을 제공.
- [~] T-208b — resources(DB/client/provider 9 + kor-travel-geo/rustfs, D-15). 1차:
      `kor_travel_map_client`, `reverse_geocoder`, `fetched_at`, provider record iterable
      resource 계약 구현. `offline_upload_store` resource key는 T-208g에서 추가한다.
      RustFS/S3 호환 `offline_upload_store` 기본 resource와 Docker RustFS bucket init은
      후속 T-208b 작업으로 구현했다. 실제 provider client resource wiring은 남는다.
- [x] T-208c — provider load asset 9종(이미 구현·검증된 Feature provider 변환 함수
      연결) + 주소/좌표 검증 + `AsyncKorTravelMapClient.load_feature_bundles` PostGIS
      적재 통합 테스트.
- [x] T-208d — schedules(KST cron, 부하 분산).
      현재 구현된 Feature 적재 asset 9개의 provider별 `ScheduleDefinition`과 asset job을
      등록했다. 기본 status는 `STOPPED`.
- [x] T-208e — sensors(feature_update_requests 폴링 + run_failure → 알림, D-6).
      `feature_update_request_queue_sensor`는 `peek_next_update_request()`로 queued/now
      request를 감지하고, `feature_update_request_worker`가 request id별 실행을 맡는다.
- [x] T-208f — consistency/dedup refresh job.
      `consistency_dedup_refresh` job이 `refresh_dedup_candidates` →
      `run_consistency_check` 순서로 실행된다. dedup refresh는 pair/sibling scope config를
      받고, consistency report는 `ops.feature_consistency_reports`에 저장한다.
- [x] T-208g — offline upload load job (D-14).
      `ops.offline_uploads`(alembic 0011), `infra.offline_upload_repo`,
      `kortravelmap.offline_upload` JSON/JSONL `FeatureBundle` parser/load
      orchestration, `AsyncKorTravelMapClient.run_offline_upload_load_job`,
      Dagster `offline_upload_load` job을 추가했다.


**Phase 4.2 — Offline upload admin UI 선행**
- [x] T-208h — `/admin/offline-uploads*` API + 기본 upload 화면.
      RustFS/S3 store에 JSON/JSONL `FeatureBundle` 파일을 저장하고,
      `ops.offline_uploads` row 생성/list/detail/load 실행까지 admin UI에서 연결한다.
- [x] T-208i — CSV/TSV validation + column mapping wizard.
      CSV/TSV 업로드 허용, preview/header/sample endpoint, validation import job,
      column mapping, kor-travel-geo address geocode/reverse 보강, load 전 validation gate,
      admin UI validation panel, Dagster load parser 연계를 추가했다. `bjd_code`가 없는
      provider/offline row는 resolver가 있으면 kor-travel-geo REST v2 geocode/reverse 결과로
      보강한다.


**Phase 4.5 — Admin UI 최신화 (사용자 지시로 T-208d 이후 최우선)**
- [x] T-211a — admin UI 최신 문서/현재 구현 gap audit + 선행 API/데이터 계약 보강.
      `docs/admin-ui-modernization-gap-audit.md`를 추가하고, frontend에
      `/admin/features`, `/ops/import-jobs`, `/ops/metrics`, `/ops/consistency`,
      `/admin/dedup-review`, `/admin/feature-update-requests`,
      `/admin/poi-cache-targets`, `/features/nearby/by-target` typed hook layer를
      추가했다. `/admin/import-jobs` 과거 표기는 `/ops/import-jobs` 정본으로
      정리했다.
- [x] T-211b — admin UI 최신화 구현. Dagster 관리 화면 embed와 별개로 자체 UI에서
      schedule/sensor/job/run/asset 상태를 꾸며 보여주고, feature/update request/ops
      화면을 최신 문서 기준으로 보완한다. React Doctor 검증 필수.


**Phase 5 — Docker / 배포**
- [x] T-209a — `docker-compose.yml` 1차(api/frontend/dagster/postgres) + 고정 포트
  API `12301`, frontend `12305`, Dagster `12302`, Postgres host `5432`.
- [x] T-209b — 기동 순서 1차(postgres health → API `alembic upgrade head` →
  api/frontend/dagster). 2026-06-04 Codex 후속으로 `scripts/run-admin-stack.sh`가
  시작 전 `alembic upgrade head`를 실행하고, `setsid` detached 실행 + URL 기준
  readiness로 API/frontend/Dagster를 유지하도록 보정했다. Dagster metadata DB 분리/init와
  daemon/schedule 운영은 `T-209b-a`에서 완료했다.
- [x] **T-209b-a — Dagster schedule/run/event storage PostgreSQL 강제 전환.**
  Docker standalone과 로컬 admin-stack 모두 `docker/dagster.yaml`의 unified
  `storage.postgres` instance config를 사용한다. Dagster 공식 instance config 기준에서
  이 key는 run/event/schedule-sensor tick metadata를 함께 PostgreSQL에 저장하므로,
  `KOR_TRAVEL_MAP_DAGSTER_PG_URL`이 단일 source다.
  - Docker 이미지는 기존처럼 `docker/dagster.yaml`을 포함하고, `dagster` webserver와
    `dagster-daemon`이 같은 `DAGSTER_HOME`/`KOR_TRAVEL_MAP_DAGSTER_PG_URL`을 공유한다.
  - `scripts/run-admin-stack.sh`는 시작 전 `kor_travel_map_dagster` DB 존재를 확인/생성하고,
    `docker/dagster.yaml`을 `$DAGSTER_HOME/dagster.yaml`로 설치한다.
  - 로컬 admin-stack도 `dagster dev` 대신 `dagster-webserver`와 `dagster-daemon`을
    분리 실행하고, daemon pid가 살아 있는지 readiness 뒤 확인한다.
  - `$DAGSTER_HOME/schedules/schedules.db*` 생성은 회귀로 문서화했고,
    compose/local script 회귀 테스트를 추가했다.
- [x] T-209c — Dockerfile 3종(api/frontend/dagster).
  frontend Dockerfile은 T-RV-28에서 root `package-lock.json` 기반 `npm ci`로 전환했다.
- [x] T-209d — `docs/runbooks/docker-app.md` + `docs/deploy.md`.
- [x] T-209e — backup/restore 독립 DB 묶음(ADR-040 amend, D-5).
  `T-209e-a`에서 `npm run docker:backup`과 `docs/backup-restore.md`를 추가해
  `kor_travel_map` app DB + `kor_travel_map_dagster` Dagster metadata DB + RustFS volume cold
  backup 산출물과 검증 절차를 고정한다. `T-209e-b`에서 `npm run docker:restore`와
  `scripts/docker-restore.sh`를 추가해 backup 산출물을 staging DB/volume
  (`kor_travel_map_restore`, `kor_travel_map_dagster_restore`, `kor-travel-map-rustfs-restore`)으로
  복원하는 비파괴 cold restore 자동화를 고정한다. `T-209e-c`에서
  `/admin/backups`, `/admin/restore/{backup_id}` router와 `/admin/backups` UI를 추가해
  artifact 목록과 backup/restore/swap command plan을 노출한다. 최종 잔여로
  `scripts/with-pg-advisory-lock.py` 기반 `maintenance:backup-restore` mutex,
  `scripts/docker-restore-verify.sh` staging smoke/count 검증,
  `scripts/docker-restore-swap.sh` restore hot-swap env 전환을 추가했다.


**Phase 6.5 — TripMate 요구사항 대조 후속 (2026-06-06, `T-213`)**

정본 리포트는 `docs/reports/tripmate-requirements-reconcile-2026-06-06.md`. TripMate
문서의 기준 kor-travel-map commit이 `b775c74`라 현재 `origin/main`과 차이가 크므로, 단순
호환 shim이나 최소 수정이 아니라 ADR-045 OpenAPI 독립 프로그램 모델 기준으로 완성도,
안정성, 확장성, 성능을 우선한다.

- [x] **T-213a — TripMate 요구사항 대조 리포트 작성.**
  TripMate `docs/kor-travel-map-requirements.md` K-1~K-14를 현재 user OpenAPI 7개 path,
  repo/client 구현, ADR-045/046 경계와 대조해 이미 충족/부분 충족/신규 task를 분리한다.
- [x] **T-213b — 일반 좌표 기준 `/features/nearby` 구현.** (claude, 2026-06-06)
  `GET /features/nearby`(`lon`/`lat`/`radius_m`≤100km/`kind[]`/`category[]`/`status[]`/
  `provider[]`/`sort`/`page_size`/`cursor`) + repo `features_nearby` + client
  `features_nearby`를 추가했다. 입력 좌표를 `origin` CTE에서 1회만 5179로 변환하고
  술어는 STORED `coord_5179`에 `ST_DWithin`/거리 정렬(ADR-012, by-target nearby와 동일
  candidates CTE — row/cursor/page helper 재사용). 응답 `{data:{origin,items,
  next_cursor}, meta}`, user OpenAPI subset 포함(`export_openapi.py` USER_OPERATIONS).
  검증: 격리 WSL sandbox에서 OpenAPI 재생성/drift green, ruff/mypy/lint-imports,
  admin router unit(검증 422 + spec presence), client unit, **PostGIS 통합 4건**
  (필터/거리·cursor·invalid·EXPLAIN ADR-012 stored-coord_5179 술어 확인). 참고: 소량
  테스트 데이터에서 planner가 GiST 대신 seqscan을 고를 수 있어 인덱스 *이름*은
  단언하지 않고 술어 대상 컬럼/per-row transform 부재로 ADR-012를 검증한다.
- [x] **T-213c — bbox clustering(`cluster_unit`) 설계/구현.** (claude, 2026-06-06)
  **설계 결정: 서버 행정구역 rollup**(client-side·grid bucket 대신) — feature에 이미
  있는 `sido_code`/`sigungu_code`/`legal_dong_code`를 GROUP BY해 geometry 계산 없이
  region별 count + 평균 좌표(대표 마커 위치)를 낸다. repo `cluster_features_in_bbox`
  (cluster_unit allowlist→고정 코드 컬럼, bbox는 stored `coord` GIST `&&`, ADR-012
  술어 변환 없음) + `/features/in-bounds`에 `cluster_unit`(sido|sigungu|eupmyeondong)
  쿼리 추가, 미지정 시 `zoom`으로 유도(≤7=sido/≤10=sigungu/≤13=eupmyeondong/≥14=개별).
  응답 `data.clusters[]`(cluster_unit None이면 `items`, 아니면 `clusters`,`items=[]`).
  검증: router unit 4(cluster/zoom 유도/고줌 개별/invalid 422), PostGIS rollup 통합 2
  (sigungu·sido count+centroid, invalid), 격리 sandbox에서 OpenAPI drift/frontend
  types/ruff/mypy/lint-imports green.
- [x] **T-213d — `AsyncKorTravelMapClient` read parity 보강.** (claude, 2026-06-06)
  `get_features`(→`get_feature_rows_by_ids`), `search_features`(→repo
  `search_features`), `features_nearby_poi_cache_target`(→repo 동명 함수) 3개 read
  메서드를 `AsyncKorTravelMapClient`에 추가했다. 기존 repo 함수에 위임만 하므로 새 SQL/
  스키마 없음. TripMate 운영은 계속 OpenAPI만 쓰지만, API/Dagster 내부와 테스트가
  admin `/features/{batch,search,nearby-by-target}`와 같은 read path를 재사용한다.
  DB 미접근 unit test 3건(repo/세션 monkeypatch pass-through). **T-213b/e/g의 선행
  기반.**
- [x] **T-213e — weather card/시계열 사용자 API.** (claude, 2026-06-06)
  `feature.feature_weather_values` 테이블 신설(**alembic 0017**, PK=결정적
  `weather_value_key` ADR-010, card 복합 인덱스 + valid_at BRIN ADR-013, feature FK
  CASCADE). `infra/weather_repo.py`: `load_weather_values`(멱등 upsert) +
  `build_weather_card(feature_id, asof, freshness_seconds)` — (forecast_style,
  metric_key)별 `COALESCE(valid_at,observed_at,issued_at)` 최신 DISTINCT ON, asof 필터,
  `source_styles` trace, `is_stale`(기본 6h). `GET /features/{feature_id}/weather` user
  spec 포함 + client `build_weather_card`/`load_weather_values`. 검증: PostGIS 통합 2
  (load/card/asof/freshness/idempotent/empty) + alembic upgrade 0017 체인 + router unit 2.
  격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/lint-imports green.
  **→ T-213a~h 전부 완료.**
- [x] **T-213f — category catalog HTTP/runtime 표면.** (claude, 2026-06-06)
  `GET /categories`(`routers/categories.py`) — 144건 정적 카탈로그(code/depth/tier/
  label/path/maki_icon/...)를 노출. `include_counts`/`active_only`면 repo
  `category_feature_counts`로 DB 분포(`db_feature_count`/`db_active`) 합침. 정적
  카탈로그는 모듈 로드 시 1회 구성(ADR-030). user OpenAPI subset 포함, frontend
  types 재생성. drift gate는 `@kor-travel-map/map-marker-react` `maki.ts`가 **name→glyph**
  구조라 ADR-029 원안의 category↔TS 1:1이 아니라 **완화형**(TS maki name kebab 유효성
  + 핵심 provider maki 글리프 커버 + Python 카탈로그 self-consistency)으로 적용
  (`tests/unit/test_category_catalog_contract.py`). 부수: `category/__init__.py`
  docstring tier 개수(34/73/29)·`category.md` icon 개수(57) 코드 기준 reconcile.
  검증: 격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/lint-imports +
  admin router 3·main contract 3·PostGIS counts 1건 green.
- [x] **T-213g — provider export + sync state/last-sync 표면.** (claude, 2026-06-06)
  `kortravelmap.providers`에 knps/krheritage 변환 함수·dataset/provider 상수 re-export.
  `AsyncKorTravelMapClient`에 `get_sync_state`/`list_sync_states`(read) +
  `record_sync_success`/`record_sync_failure`(write, 1 transaction) helper 추가.
  `GET /providers/{provider}/last-sync`(`routers/providers.py`) — `sync_state_repo.
  list_sync_states`(provider + dataset_key/sync_scope 필터) 기반, `items[]`(dataset/
  scope/status/last_success_at/last_failure_at/consecutive_failures) 반환, **내부
  cursor 비노출**, 매칭 0건이면 404. user OpenAPI subset 포함, frontend types 재생성.
  검증: router unit 3(spec/404/200 cursor-exclude), providers export unit 1, PostGIS
  list 통합 1, client unit, 격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/
  lint-imports green.
- [x] **T-213h — public health/version.** (claude, 2026-06-06)
  `GET /health`(liveness, 의존 없는 정적 200, `{data:{status,service},meta}`) +
  `GET /version`(`{data:{version, kor_travel_map_version, openapi_version, commit},meta}`,
  commit=env `KOR_TRAVEL_MAP_GIT_COMMIT`)를 `routers/public_status.py`로 추가. liveness는
  DB 장애에도 동작해야 하므로 `features_routes_enabled`와 무관하게 **항상 mount**.
  user OpenAPI subset 포함, frontend types 재생성. router unit 5(spec presence/
  liveness/version/env commit/feature-off 시에도 mount). **deep readiness**(DB/RustFS/
  Dagster `/ops/health-deep`)는 후속 — liveness를 DB-free로 유지하기 위해 분리.


## 완료

- [x] T-000 — git v1 보존 + main orphan 재시작 (완료: 2026-05-24)
- [x] T-001 — v2 핵심 docs 작성 (완료: 2026-05-24)
  - AGENTS.md, README.md, SKILL.md, CLAUDE.md
  - .env.example, pyproject.toml, .gitignore, .gitattributes, LICENSE
  - docs/architecture.md
  - docs/decisions.md (ADR-001 ~ ADR-019)
  - docs/data-model.md, performance.md, test-strategy.md
  - docs/backend-package.md, agent-guide.md, dev-environment.md
  - docs/windows-reinstall-recovery.md
  - docs/feature-model.md, provider-contract.md, external-apis.md
- [x] T-001b — ADR-020 + 디버그 UI 별도 패키지로 분리 (완료: 2026-05-24)
  - decisions(ADR-020), architecture, backend-package, debug-ui-package(신규),
    AGENTS, SKILL, CLAUDE, README, pyproject(`[api]` 제거 + forbidden 계약 추가),
    .env.example, test-strategy 갱신
  - `packages/kor-travel-map-admin/` pyproject + README skeleton
- [x] T-002 ~ T-011 — v1 docs를 v2 기준으로 일괄 이전 (완료: 2026-05-24, PR#2)
  - 14개 신규 docs (weather/files-rustfs/opening-hours/kraddr-base-types/
    address-geocoding/dagster-boundary/postgres-schema/debug-fixture-workflow/
    feature-db-initialization/tripmate-integration + provider ETL 10건)
- [x] T-001c — ADR-021/022/023 + PR-only workflow + `kortravelmap` namespace +
      kraddr-base category 이전 (완료: 2026-05-24, PR#1)
  - AGENTS/SKILL/CLAUDE/architecture/agent-guide 일괄 갱신
  - `docs/category.md` 신설
  - import-linter 계약 placeholder
- [x] T-016 — `python-mois-api` 활용 feature 적재 4단계 lifecycle docs +
      ADR-024 canonical name 정정 (완료: 2026-05-24, PR#3)
  - `docs/mois-feature-etl.md` 신설 + 195 슬러그 카탈로그
  - 일괄 krmois→mois rename (`mois-license-feature-etl.md` 등)
- [x] T-015 — forest rename + category Tier 1~4 catalog + KNPS data.go.kr
      카탈로그 + 모든 ETL doc category 정보 audit (완료: 2026-05-25, PR#5)
  - `outdoor-feature-etl.md` → `forest-feature-etl.md` (git mv)
  - `docs/category.md` Tier 1~4 상세 테이블 (141건)
  - KNPS dataset 7건 카탈로그 + 옵션 A/B 비교 (옵션 B 권고)
- [x] T-017a — ADR-025 디버그 UI frontend = `maplibre-vworld-js` + ADR-025
      사용자 보강 (key 공유 + upstream 직접 PR) + ADR-026 TripMate 사용자 UI도
      maplibre-vworld 통일 (완료: 2026-05-25, PR#6 merged)
  - `docs/decisions.md` ADR-025 + ADR-026
  - `docs/debug-ui-package.md` §14 frontend 사양
  - `packages/kor-travel-map-admin/frontend/` skeleton
  - `docs/tripmate-integration.md` §14.5 사용자 UI 지도 stack
  - `docs/external-apis.md` Kakao Maps SDK 미사용 처리
  - `docs/forest-feature-etl.md` §11.6 ADR-026 → ADR-027 후보 재번호
- [x] T-017b — ADR-025 2차 사용자 보강 (frontend 빌드 도구 Vite → **Next.js**
      정정) (완료: 2026-05-25, PR#11 merged)
  - `docs/decisions.md` ADR-025 §사용자 보강 2차 추가
  - `docs/debug-ui-package.md` §14 Next.js 전환 + 운영 옵션 3가지
  - `packages/kor-travel-map-admin/frontend/` skeleton 일괄 Next.js 전환
    (package.json / .env.example / .gitignore / README / **next.config.js**
    신설), `VITE_*` → `NEXT_PUBLIC_*`
  - `docs/external-apis.md` / `docs/tripmate-integration.md` §14.5 / `docs/
    tasks.md` (T-100 재해석) 동기
- [x] T-013 — `CHANGELOG.md` 초기 엔트리 정리 (완료: 2026-05-25, PR#10 merged)
  - ADR-024~033 + T-101~103 + 명명 일치화 + 코드 변경 모두 inline
- [x] T-013b — 잔존 `krmois` → `mois` 명명 sweep (완료: 2026-05-25, PR#10
      merged) — 4건 정리 (forest §11.1 / mois-license §payload / journal 2건),
      ADR-024 narrative 등 역사 기록 컨텍스트는 유지
- [x] T-014a — Sprint 1 진입 계획 작성 (완료: 2026-05-25, PR#10 merged)
  - `docs/sprints/README.md` (Sprint 1~5 표 + 공통 진입 게이트)
  - `docs/sprints/SPRINT-1.md` (진입 조건 + 산출물 + DoD + Sprint 2 진입)
  - 실제 Sprint 1 진입 PR은 T-014 본체로 계속 pending (사용자 승인 필요)
- [x] T-017c — ADR-029 (proposed) + `@kor-travel-map/map-marker-react` skeleton
      (완료: 2026-05-25, PR#10 merged)
  - `docs/decisions.md` ADR-029 본문 (MIT, monorepo 위치, peer deps,
    drift gate, 배포 정책)
  - `packages/map-marker-react/` skeleton (`package.json` / `README.md` /
    `vite.config.ts` / `.gitignore`)
  - 실 코드는 T-017 본체 (Sprint 2)
- [x] T-018a — `python-knps-api` upstream scaffold 모니터링 + 본 라이브러리
      ADR-028 (proposed) 작성 (완료: 2026-05-25, PR#12 merged)
  - upstream `digitie/python-knps-api` `6e36990` scaffold 확인
  - `docs/decisions.md` ADR-028 본문
  - `docs/knps-feature-etl.md` 신설 (feature 적재 계약)
  - `docs/forest-feature-etl.md §11` 갱신 (외부 API 표면 + 채택 ✅ 표기)
  - `docs/provider-contract.md` / `docs/external-apis.md` / `pyproject.toml`
    동기
- [x] T-018b — upstream knps-api 측 PR — maki icon 정정 (완료: 2026-05-25,
      knps-api PR#1 open, https://github.com/digitie/python-knps-api/pull/1)
  - `docs/knps-feature-etl.md §4` shelter / barrier 정정 (본 라이브러리
    ADR-027 정합 + Maki 표준 호환)
  - 양방향 PR 워크플로 적용 사례 (ADR-028 §D)
- [x] T-012a — T-101~103 상세 분석을 `docs/performance.md`에 inline (완료:
      2026-05-25, PR#10 merged)
  - §9.3 T-101 (PostGIS MV), §9.4 T-103 (streaming ETL), §9.5 T-102
    (pg_prewarm) — 도입 조건, 부작용, ROI, 절차
- [x] T-012b — ADR-030/031/032/033 enforcement 코드 (완료: 2026-05-25, PR#10
      merged)
  - `pyproject.toml`: import-linter 차단 계약 (cachetools/async_lru/
    aiocache/diskcache + kafka/aiokafka/confluent_kafka/faust), coverage
    Sprint별 schedule 주석
  - `packages/kor-travel-map-api/scripts/export_openapi.py` skeleton
    (ADR-031, `--check` drift gate)


## 폐기 / 재해석

- ~~T-100~~ — "디버그 UI 별도 Next.js 패키지 분리" — **부분 재해석** (PR#11
  2026-05-25):
  - 원래 의도 = Next.js로 별도 패키지화. 실제 구현 = Python 패키지로 분리
    (T-001b, ADR-020) + frontend는 그 안의 `frontend/` 하위에 **Next.js**
    (ADR-025 2차 보강).
  - 즉 "Next.js 미채택"이라고 한 PR#7의 기록은 잘못됨 — ADR-025 2차 보강
    으로 Next.js 채택 확정.


## 머지 history (참조)

| PR | branch | 머지 일자 | 핵심 |
|----|--------|----------|------|
| #1 | `chore/pr-workflow-namespace-rename-category-migration` | 2026-05-24 | ADR-021/022/023 |
| #2 | `docs/v1-to-v2-feature-ports` | 2026-05-24 | T-002~T-011 (14 docs) |
| #3 | `feat/mois-feature-etl` | 2026-05-24 | ADR-024 + mois-feature-etl.md |
| #4 | (merged via #3 lineage) | 2026-05-24 | 동일 |
| #5 | `feat/forest-knps-category` | 2026-05-25 | T-015 (forest rename + KNPS 카탈로그 + category Tier 1~4) |
| #6 | `feat/debug-ui-maplibre-vworld` | 2026-05-25 | ADR-025 + ADR-025 사용자 보강 + ADR-026 |
| #7 | `chore/tasks-md-update` | 2026-05-25 | tasks.md 백로그 |
| #8 | `docs/adr-030-031-032-033-proposed` | 2026-05-25 | ADR-030/031/032/033 proposed |
| #9 | `docs/adr-027-forest-category-expansion` | 2026-05-25 | ADR-027 proposed |
| #10 | `docs/pr10-t012-t018-codify` | 2026-05-25 | ADR-029 + T-013/14a/17c/12a/12b + 명명 sweep + 코딩 |
| #11 | `docs/pr11-debug-ui-nextjs` | 2026-05-25 | ADR-025 2차 보강 (Vite → Next.js) |
| #12 | `docs/pr12-knps-api-integration` | 2026-05-25 | ADR-028 + knps-feature-etl.md |
| #13 | `chore/tasks-md-pr12-merged-update` | 2026-05-25 | tasks.md 백로그 갱신 (PR#12 머지 후) |
| #14 | `docs/pr14-impl-order-sprint-plans` | 2026-05-25 | ADR-034 provider 9단계 + Sprint 2~5 plan |
| #15 | `docs/pr15-governance-sweep` | 2026-05-25 | governance docs sweep + DO NOT bug fix 3건 |
| #16 | `feat/sprint1-entry-adr-accepted` | 2026-05-25 | T-014 Sprint 1 진입 — ADR 027~034 일괄 accepted + fail_under=50 |
| #17 | `feat/sprint1-pr17-scaffolding` | 2026-05-25 | `src/kortravelmap/` PEP 420 scaffolding + `settings.py` + smoke |
| #18 | `feat/sprint1-pr18-category-migration` | 2026-05-25 | `category/` 144건 (kraddr-base 이전 + ADR-027 3건) + 16 tests |
| #19 | `feat/sprint1-pr19-dto-foundation` | 2026-05-25 | `dto/` Feature + 5 detail + NOTICE_TYPES 14 (ADR-027) + AreaDetail hazard_zone + KST + 27 tests |
| #20 | `feat/sprint1-pr20-core-exceptions-id` | 2026-05-25 | `core/` exceptions 7종 + `make_feature_id` (ADR-009) + 42 tests |
| #21 | `feat/sprint1-pr21-infra-skeleton` | 2026-05-25 | `infra/crs.py` + `infra/db.py` + testcontainers PostGIS conftest |
| #22 | `feat/sprint1-pr22-ci-import-linter` | 2026-05-25 | CI workflows + import-linter 4 계약 + ADR-002 위반 해소 (dto/_time.py) |
| #23 | `docs/pr23-review-report` | 2026-05-25 | `docs/reports/pr-1-21-review.md` 종합 리뷰 |
| #24 | `fix/pr24-dto-strictness-p0` | 2026-05-25 | review P0-1/2/3 — detail dict 거부 + datetime aware + category 정규식 |
| #25 | `docs/pr25-knps-keyless-sync` | 2026-05-25 | python-knps-api keyless(`06da125f`) 반영 + ADR-028 amendment §H |
| #26 | `feat/pr26-source-record-bundle-dto` | 2026-05-25 | review P0-4 — ID helper 2종 + SourceRecord/Link/FeatureBundle DTO |
| #27 | `docs/pr27-p1-docs-drift-sweep` | 2026-05-25 | review P1 docs drift sweep |
| #28 | `feat/pr28-infra-models-alembic` | 2026-05-26 | `infra/models.py` + Alembic 첫 2 revision (0001/0002) + 통합 테스트 6 |
| #29 | `feat/pr29-core-scoring-providers` | 2026-05-26 | `core/scoring.py`(ADR-016) + `core/providers.py` (canonical 18종) |
| #30~31 | `docs/pr30-31-codegraph-worktree` | 2026-05-27 | agent worktree + codegraph 룰 docs + MCP 등록 |
| #32~33 | `docs/pr32-33-adr-035-043` | 2026-05-27 | 거버넌스 보강 + ADR-035~043 proposed→accepted |
| #34 | `feat/pr34-datagokr-festivals` | 2026-05-27 | Sprint 2 §2.1 datagokr 축제 1차 source (ADR-042) |
| #35 | `feat/pr35-debug-ui-routers` | 2026-05-27 | 디버그 UI `create_app` + health/version + openapi drift gate |
| #36 | `feat/pr36-frontend-skeleton` | 2026-05-27 | Next.js 15 frontend skeleton + TanStack/Zustand (ADR-037) |
| #37 | `feat/pr37-kraddr-base-absorb` | 2026-05-28 | ADR-041 — Address DTO 보강 + `core/address.py` |
| #38 | `feat/pr38-kma-short-forecast` | 2026-05-28 | `WeatherValue` DTO + 3 enum + KMA 단기예보 1차 |
| #39 | `feat/pr39-kma-nowcast` | 2026-05-28 | KMA 초단기실황 + `core/weather.py` pure 헬퍼 5종 |
| #40 | `docs/pr40-provider-status-sweep` | 2026-05-28 | `python-*-api` 라이브러리 status sweep |
| #41 | `feat/pr41-kma-ultra-short-forecast` | 2026-05-28 | KMA 초단기예보 (getUltraSrtFcst) + LGT |
| #42 | `feat/pr42-pricevalue-opinet` | 2026-05-28 | `PriceValue` DTO + opinet 가격 1차 |
| #43 | `feat/pr43-opinet-stations` | 2026-05-28 | opinet `stations_to_bundles` (gas station Feature) |
| #44 | `feat/pr44-etl-preview-router` | 2026-05-28 | 디버그 UI ETL preview 라우터 (fixture dry-run) |
| #45 | `feat/pr45-krex-multi-kind` | 2026-05-28 | Sprint 2 §2.4 krex 휴게소 4 dataset multi-kind |
| #46 | `feat/pr46-kma-weather-alerts` | 2026-05-28 | KMA weather_alerts → notice + krex category fix + ETL 11 dataset |
| #47 | `feat/pr47-etl-live-source` | 2026-05-28 | ETL preview `?source=live` (KMA 3) + 8 provider key + CI red 3종 해소 |
| #48 | `docs/pr48-worktree-rename-tasks-sweep` | 2026-05-28 | worktree `geo-*`→`kor-travel-map-*` rename + tasks.md 최신화 |
| #49 | `feat/pr49-maplibre-vworld-v010` | 2026-05-28 | maplibre-vworld v0.1.0 의존 핀 정합 (git URL+tag, zod ^4.4.3, ADR-036 amendment) |
| #50 | `docs/pr50-sprint-task-resume-consolidation` | 2026-05-28 | Sprint/task/resume 일관성 재정비 |
| #51~#95 | (Sprint 2 잔여 + Sprint 3) | 2026-05-28~30 | visitkorea enrichment / KMA mid_forecast / ETL live 11 / KNPS·krheritage provider / geocoding REST / `feature_repo` 적재 / consistency F1~F3 / `AsyncKorTravelMapClient` / `/features` debug UI + frontend / dedup queue |
| #96~#114 | (Sprint 4 prep) | 2026-05-30~31 | `/features` UX / `map-marker-react` / geocoding v2 회귀 / NTFS+Windows Git 정책 / Next.js 16 + `maplibre-vworld-js#v0.1.2` |
| #115~#132 | (Sprint 4a) | 2026-05-31~06-01 | MOIS Step A bulk + Step B incremental(cursor) / advisory lock + `ops.import_jobs` / CLI mutex + `status` / `ktmctl import mois`(NDJSON) / dedup self-sibling / geocoder live 재검증 |
| #133 | `feat/cli-dedup-merge` | 2026-06-01 | `ktmctl dedup-merge` + merge primitive + `ops.feature_merge_history`(alembic 0007) + `core.scoring.select_master` (ADR-016) |
| #134 | `feat/step-b-incremental` | 2026-06-01 | MOIS Step B 증분 적재 + `infra/sync_state_repo`(cursor) |
| #135 | `chore/dedup-fp-measurement` | 2026-06-01 | dedup FP 측정 리포트 + 회귀 가드 (가중치 변경 없음) |
| #136 | `feat/step-c-closed` | 2026-06-01 | MOIS Step C 폐업/취소 → feature inactive |
| #137 | `feat/step-d-detail-router` | 2026-06-01 | MOIS Step D on-demand 상세 (debug-ui `/debug/mois-license/{id}`, 캐시만) |
| #138 | `feat/dedup-fp-ops-stats` | 2026-06-01 | dedup 운영 FP 통계 (`status_repo.dedup_fp_stats` + `ktmctl status`) |
| #139 | `feat/consistency-f4` | 2026-06-01 | ADR-033 F4 — dedup 백로그 baseline WARN |
| #140 | `feat/place-phone-enrichment` | 2026-06-01 | Place 전화번호 보강 (`kortravelmap.enrichment`) |
| #141 | `chore/coverage-bar-80` | 2026-06-01 | coverage gate 75→80 (실측 94.12%) — Sprint 4 종료 |
| #142 | `docs/agent-runbooks` | 2026-06-01 | 에이전트 공용 runbook (`docs/runbooks/` agent-workflow + failure-patterns) |
| (post) | (main) | 2026-06-01 | admin OpenAPI cache 문서 (ADR-045 후속) |
| knps-api #1 | `docs/knps-feature-maki-icons` | **open** | maki icon 정정 (shelter / barrier) |
