# 코드+문서 전체 정합성 감사 — 2026-06-16 (claude)

사용자 지시("코드와 문서 전체를 다시 읽어 충돌·기능 부족을 확인 후 문서에 반영,
e2e 촘촘 시나리오 포함, 누락 방지 위해 1회 작업 후 재독 검증")에 따른 **2-pass 전수
감사**. **docs-only**(코드 변경 없음) — 충돌은 해당 문서를 정정하고, 기능 갭은 backlog/
known-gap으로 문서화한다.

- **기준 커밋**: origin/main (#443 머지 후).
- **방법**: Round 1 — 6차원 병렬 감사(① core lib+16 provider ② API 22 라우터↔계약
  ③ Dagster ④ **e2e 시나리오** ⑤ ADR↔구현 ⑥ frontend 완결성), 코드 ground-truth 대조
  (file:line 양측). Round 2 — 재독 검증(발견 adversarial 재확인 + completeness critic이
  놓친 것 색출 + 적용 문서 정확성 검증). 발견 ID: 충돌 `C-NN`, 기능 갭 `F-NN`.
- **이전 감사 연속**: `docs-consistency-audit-2026-06-06.md`(T-DA-01~17), `docs-consistency-
  sweep-2026-06-14.md`(T-DA-18~26). 본 감사는 그 이후 **코드↔문서 심층 대조**(2026-06-06이
  T-212a/c로 미룬 endpoint↔contract 전수 포함).
- **e2e 정본**: 별도 `docs/reports/e2e-scenario-coverage-2026-06-16.md`(촘촘 매트릭스).

## 1. 요약 (severity·status)

> status: ✅=본 PR 문서 정정 / 📋=backlog·known-gap 문서화 / ⚖️=결정 필요

### 충돌 (C — 코드↔문서 / 문서↔문서)

| ID | sev | 한 줄 | 정정 대상 | status |
|----|-----|-------|-----------|--------|
| C-01 | HIGH | `openapi-admin-contract.md` §3/§3.1이 **pre-ADR-048 envelope**(error{error}, meta.count) — 코드는 RFC7807 problem+json + Meta{page,cluster} | openapi-admin-contract.md | ✅ |
| C-02 | HIGH | offline-upload bucket `krtour-uploads`→`kor-travel-map-uploads` 미전파(8 문서) | 8 docs | ✅ |
| C-03 | HIGH | screen-checklist "17 route / e2e 전부 커버" — 실제 22 페이지, 5개 미매트릭스 | admin-ui-screen-checklist.md | ✅ |
| C-04 | HIGH | KHOA 해수욕장 category: 코드 `01020300`(COAST_ISLAND) vs 문서 `01050100`(NATURE_BEACH) | khoa-etl/category.md | ⚖️ |
| C-05 | HIGH | KHOA dataset_key 코드 `khoa_beaches` vs 문서 `khoa_oceans_beach_info`(feature_id에 baked) | provider-contract/khoa/dagster-boundary | ✅ |
| C-06 | MED | provider-contract §6 "무조건 결정성" 주장 vs ~11 provider가 reverse-geocoded bjd를 feature_id에 embed | provider-contract.md/decisions.md | ✅(+F-01) |
| C-07 | MED | weather/notice/air-quality anchor가 catalog 밖 `99000000` 사용 — 미문서화 | category.md/notice-etl | ✅ |
| C-08 | MED | feature-model §15~17 DTO(PriceValue/PricePoint/ProviderSyncState/ImportJob/FeatureFile)가 코드와 불일치 | feature-model.md | ✅ |
| C-09 | MED | krex 자연키는 `name::route::direction` 합성인데 ETL 문서가 provider ID 주장 + §3 스니펫 stale | krex-rest-area-etl.md | ✅ |
| C-10 | MED | standard_data dataset_key 코드 `datagokr_*` vs 문서 `standard_*` | provider-contract.md | ✅ |
| C-11 | MED | dagster-boundary §1.1이 10개 asset, §10이 8개 schedule 누락 | dagster-boundary.md | ✅ |
| C-12 | MED | 의존 체인에 `geocoding` 누락(import-linter는 강제) | architecture/CLAUDE/dto | ✅ |
| C-13 | MED | openapi-admin-contract `{issue_key}`·CSV bbox stale → `{issue_id}`·4 float | openapi-admin-contract.md | ✅ |
| C-14 | MED | `/admin/dedup-review`(단수) vs 코드·rest-api `/admin/dedup-reviews`(복수) | debug-ui-admin-workflows/openapi-contract | ✅ |
| C-15 | MED | debug-ui-admin-workflows §4.1이 미존재 route 나열 + manual-create 오기 | debug-ui-admin-workflows.md | ✅ |
| C-16 | MED | AGENTS.md:62 "다음 후보 ADR-057"(stale) — 057 accepted, 다음 058 | AGENTS.md | ✅ |
| C-17 | MED | rest-api.md(단일 계약 정본) §2.5/§2.6이 5+ 구현 endpoint 누락 | rest-api.md | ✅ |
| C-18 | MED | dagster-boundary sensor 설명·strict_address type·패키지 경로 stale | dagster-boundary.md | ✅ |
| C-19 | LOW | `sibling_group_id` 코드 `str` vs 문서 `UUID` | feature-model.md | ✅ |
| C-20 | LOW | architecture §7 모듈표가 미존재 파일 참조(core/protocols.py 등) | architecture.md | ✅ |
| C-21 | LOW | data-model §11 `make_weather_value_key` 시그니처 오류 + `make_price_value_key` 누락 | data-model.md | ✅ |
| C-22 | LOW | category §4.4 maki 카운트 오류(lodging/park/restaurant) | category.md | ✅ |
| C-23 | LOW | rest-api.md가 완료된 T-216a~g를 미완('현재→목표')로 표기 + "공유 DB" 표현 | rest-api.md | ✅ |
| C-24 | LOW | feature-model §4 category=min_length=1(실제 `^\d{8}$`) + geom·coord_precision_digits 누락 | feature-model.md | ✅ |
| C-25 | LOW | issue 'acknowledge' 액션 + GET /admin/dashboard 문서화됐으나 미구현 | debug-ui-admin-workflows.md | ✅ |
| C-26 | LOW | dagster-boundary §5 naming + §2 FreshnessPolicy가 구현과 괴리 | dagster-boundary.md | ✅ |
| C-27 | INFO | 생성 openapi.json이 error를 422 application/json으로만 선언(런타임은 problem+json) | rest-api.md(note) | ✅ |
| C-28 | INFO | debug-ui-package.md 라우터 트리가 미존재 파일 나열 + 신규 라우터 누락 | debug-ui-package.md | ✅ |

### 기능 갭 (F — 의도/결정됐으나 미구현 또는 미문서화)

| ID | sev | 한 줄 | status |
|----|-----|-------|--------|
| F-01 | HIGH | **feature_id 비멱등** — geocoder 의존 ~10 provider(knps/krheritage/mcst/krforest/datagokr_file_data/khoa/airkorea/krairport/opinet/standard_data)는 bjd가 늦게 바인딩돼 geocoder 유무로 feature_id가 global↔code 분기(ADR-057이 concierge만 해결) | 📋 backlog + ADR-057 결과/contract 주석 |
| F-02 | MED | ADR-046 §4가 6 issue type 규정하나 `geocode_failed`/`reverse_geocode_failed`는 **producer 없음**(batch validation 미방출) | 📋 producer-status 주석 + backlog |
| F-03 | MED | `datagokr_file_data` provider는 lib에 있으나 Dagster asset 없음(curated source로만 소비) — 의도인데 미문서화 | ✅ dagster-boundary 주석 |
| F-04 | MED | `airkorea`/`krairport` provider 구현됐으나 전용 ETL 문서 없음(타 provider는 다 있음) | 📋 신규 ETL 문서 2종 |

## 2. HIGH 상세

- **C-01** `openapi-admin-contract.md`가 ADR-048(#317/T-216) **이전 envelope**를 현행처럼 기술
  (error `{error:{code,message,...}}`, list `meta.count`+`data.next_cursor`, "현행 정합(2026-06-06)"
  배지). 코드는 `api/app.py:173-191`(RFC7807 `application/problem+json`) + `api/response.py:30-121`
  (`Meta{duration_ms,request_id,page{page_size,next_cursor,total},cluster{cluster_unit}}`, count 없음).
  정본 `rest-api.md`/`tripmate-rest-api.md`/`public-views-api.md`/`integration-map.md §3`는 이미
  신 envelope으로 정확 — **openapi-admin-contract.md만 stale 아웃라이어**. → §3/§3.1 재작성 +
  "rest-api.md가 단일 계약 정본, 본 문서는 admin 부가 뷰" 배너 + ADR-048/T-216 교차참조.
- **C-02** `settings.py:96-97` 기본값이 이미 `kor-travel-map-uploads`인데 8개 현행 문서가
  `krtour-uploads`를 현행처럼 기술. → 정정(전후 rename 표·journal은 역사라 보존).
- **C-03** `admin-ui-screen-checklist.md:3/31/61`이 "17 route / admin·ops 16 route 전부 e2e 커버".
  실제 `page.tsx` 22개. 매트릭스 누락 5: curated-features, features/new, features/[id],
  import-jobs/[jobId], feature-update-requests/[requestId]. → 22로 정정 + 5행 추가(실 e2e 상태=없음) +
  "전부 커버" 주장 수정. (spec 추가는 e2e 문서 backlog.)
- **C-04 ⚖️ 결정 필요** — KHOA 해수욕장 category. 코드 `khoa.py:66-69` = `01020300`
  (TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND). 문서 `khoa-beach-info-etl.md:32`·`category.md:183/364` =
  `01050100`(전용 해수욕장 코드). 둘 다 marker 'beach'라 지도 렌더는 무관. **본 패스는 코드 미수정**:
  문서를 실제 코드값(01020300)으로 정정하되 **01050100(전용 해수욕장)이 의도였을 가능성**을
  divergence로 명기하고 category 결정을 후속으로 남긴다. (사용자 결정 시 코드 정렬 또는 doc 확정.)
- **C-05** KHOA dataset_key 코드 `khoa_beaches`(khoa.py:64) — `source_type`/`feature_id`/
  `source_record_key`에 baked. 문서 3곳은 `khoa_oceans_beach_info`. → 문서를 `khoa_beaches`로 정정 +
  "이 문자열은 feature_id에 박혀 코드 변경 시 기존 행 re-key" 제약 명기.
- **F-01 (HIGH 기능 갭)** — §3 참조.

## 3. 기능 갭 상세 (backlog)

### F-01 — feature_id 비멱등 (geocoder 의존 provider) — HIGH
`make_feature_id`(core/ids.py:145-154)는 `bjd_code`+`category`를 식별자에 embed한다. **MOIS만**
source-native `legal_dong_code`(mois.py:668)를 쓰고, 나머지 ~10 provider는 bjd를 **optional
reverse_geocoder/address_resolver**(Dagster resource 기본 None — assets.py:880-884)에서 늦게
얻는다. 따라서 geocoder 유무·출력 변동 시 같은 record가 `f_global_…`↔`f_<bjd>_…`로 갈려 재import 시
중복(soft-delete-old + new-feature)이 난다. knps는 category(None→`00000000` sentinel)도 늦게 바인딩.
이는 ADR-057이 **concierge만** 고친 결함 class(krex도 점검됨). 영향 provider: knps, krheritage, mcst,
krforest, datagokr_file_data, khoa, airkorea, krairport, opinet, standard_data.
- **문서 반영**: ADR-057 결과 절 + provider-contract.md §6 "feature_id 안정성" 주석으로 조건부
  결정성 명시. tasks.md backlog: 어느 provider에 ADR-057 anchoring(stable source key + 고정 identity
  category, bjd는 가변 속성)을 적용할지 결정. **코드 변경 없음(docs-only 패스).**

### F-02 — geocode_failed/reverse_geocode_failed issue producer 부재 — MED
ADR-046 §4가 6 issue type을 규정하나 `validation.py`는 `missing_bjd_code`/`missing_address`/
`provider_address_mismatch`/`provider_address_partial_match` 4종만 방출. `geocode_failed`/
`reverse_geocode_failed`는 src/dagster에 **producer 0**(grep). → data-model §9.5·openapi-contract §4.1·
workflows §15 issue-type 표에 "정의됐으나 batch-validation producer 없음(geo 호출시 실패는 미표면)"
주석 + tasks.md backlog.

### F-03 — datagokr_file_data Dagster asset 부재(의도) — MED
`providers/datagokr_file_data.py`는 lib에 있으나 feature-load asset/fetcher/schedule 없음 —
curated source rule로만 소비(`curated-features.md §8`). 의도인데 dagster-boundary 미언급. →
dagster-boundary §1.1에 "datagokr_file_data는 설계상 직접 asset 없음, curated overlay 경유" 1줄.

### F-04 — airkorea/krairport ETL 문서 부재 — MED
두 provider 구현·export됐으나(ADR-034 계획) 전용 ETL 문서 없음. → `docs/airkorea-feature-etl.md`,
`docs/krairport-feature-etl.md` 신규(per-provider 템플릿 + 99000000 sentinel + reverse-geocoded bjd
caveat=F-01 연계).

## 4. ⚖️ 결정 필요 (사용자)

- **DA-D-07 (C-04)** — KHOA 해수욕장 category: (A) 코드값 `01020300`(COAST_ISLAND) 확정 →
  문서를 코드에 정렬, (B) `01050100`(전용 해수욕장) 의도 → 코드 정렬을 backlog로(본 패스는 코드 미수정).
  본 PR은 (A) 방향으로 문서를 코드값에 맞추되 divergence를 명기. 사용자가 (B)면 후속 코드 task 생성.

## 5. e2e 시나리오 커버리지

정본: `docs/reports/e2e-scenario-coverage-2026-06-16.md`. 요지: 33개 e2e 중 22개가
`admin-ops.spec`에 집중, **5개 페이지 ZERO 커버**(curated-features 1192줄 콘솔, features/new 1097줄
폼, 3개 detail 페이지), 나머지는 render-smoke만(mutation/error/cursor/empty 누락). "33/33"은
통과 수치이지 UI 촘촘 커버가 아님. spec 추가는 tasks.md backlog(우선순위: HIGH 5페이지 → MED
mutation/lifecycle → LOW edge).

## 6. 확인했으나 정상 (혼동 방지 기록)

- 생성 `openapi.json`(85 path, /health·/version 외 전부 /v1)은 22-라우터 코드 인벤토리와 정확히 일치 — 기계 정본은 현행.
- `rest-api.md §1.4/§1.5`·`tripmate-rest-api.md §3`·`public-views-api.md`·`integration-map.md §3`는 ADR-048 envelope 정확(problem+json, meta.page.next_cursor) — openapi-admin-contract.md만 stale.
- ADR-034 9단계 provider 순서 **전부 구현**(각 단계 ≥1 Dagster asset, lib에 없는 provider를 참조하는 asset 없음).
- admin/issues **완전 구현**(admin_issues.py, 7 PATCH 액션, /v1 mount) — 2026-06-06 T-DA-13 '미구현' 우려 해소(잔여는 `{issue_key}`→`{issue_id}` 오기 C-13 + 'acknowledge' over-doc C-25).
- coverage gate `fail_under=80` 정합(pyproject==test-strategy==ADR-032).
- 고정 포트(API 12701/admin 12705/Dagster 12702/RustFS 12101·12105/geo 12501/PG 5432) 전 문서 정합(C-23의 '공유 vs 독립' 표현 nuance만).
- ADR 원장 001~057 연속·무갭(AGENTS.md:62 한 줄만 stale=C-16).
- concierge ADR-057 수정(#440) 정확 구현·문서화 — 비-재flag.
- visitkorea enrichment-only(make_feature_id 없음, ADR-042) 정확 문서화.
- MOIS source-native bjd(legal_dong_code) — F-01 위험군 아님, 정확 문서화.
- category catalog 144 정의/144 maki/57 unique — §3.4/§4 정합(§4.4 sub-count만 오류=C-22).

## 7. 적용/추적 분계

- **본 PR 문서 정정(✅)**: C-01~03·05~28 + F-03 → 해당 문서 직접 수정.
- **backlog 문서화(📋)**: F-01(feature_id 비멱등), F-02(issue producer), F-04(ETL 문서 2종),
  e2e 5페이지+depth → `docs/tasks.md`.
- **결정 필요(⚖️)**: C-04(KHOA category) → DA-D-07.
- **Round 2**: 본 보고서·문서 정정의 정확성 재검증 + Round 1이 놓친 것 색출 → §8 반영 완료.

## 8. Round 2 재검증 (재독 — 누락/오류 방지)

Round 1 적용분을 4-에이전트로 재독(코드 재대조 + Round 1이 안 건드린 ~30 문서·16 provider·
e2e 재스캔). Round 1 정정 대부분은 정확(신규 ETL 문서·feature-model 재작성·envelope·ADR
원장·dagster asset/cron·category 카운트 모두 verified clean). **Round 1 정정 자체의 오류 6건 +
Round 1이 놓친 추가 발견 ~14건**을 본 PR에서 추가 반영했다.

### 8.1 Round 1 정정의 오류 교정 (적용)
| ID | sev | 무엇 | 정본 |
|----|-----|------|------|
| RC-1 | HIGH | krex marker를 `car`→`highway-rest-area`로 잘못 고침(틀린값→틀린값) + `P-15` 잔존 | `fast-food`/`P-06` (krex.py:149-150, 카탈로그 maki 미사용·하드코딩) |
| RC-2 | HIGH | **geocoding layer 위치 역전** — `providers → geocoding`(providers 아래)로 삽입 | `infra → geocoding → providers`(providers가 geocoding을 import; pyproject `layers` 배열 정본). CLAUDE/architecture/AGENTS/SKILL 교정 |
| RC-3 | MED | dagster §10 KMA schedule 5종 이름에 cadence 접미사 누락 | `_hourly/_half_hourly/_3h/_twice_daily/_daily_schedule` (schedules.py:151-189) |
| RC-4 | MED | architecture §7이 `PricePoint`(미존재)·`core/types.py` Repository Protocol(허구) 나열 | `PriceValue`만; core/types.py는 KST shim — 교정 |
| RC-5 | MED | openapi LOCK_BUSY 예시가 `retry_after_seconds`를 top-level로 | `details:{retry_after_seconds}` 중첩 (feature_update_requests.py:423) |
| RC-6 | MED | rest-api "limit 더는 없음" 과잉정정 | cursor 표면은 page_size 통일, top-N(curated/refresh-policies)은 `limit` le=500 예외 존속 |

### 8.2 Round 1이 놓친 추가 발견 (적용 / backlog)
| ID | sev | 무엇 |
|----|-----|------|
| R2-04 | HIGH | `standard-data-feature-etl.md` 전반 stale(dataset_key standard_*→datagokr_*, tourist_sites→tourist_attractions; category museum 01040000·tourist 01000000) — C-10이 ETL 문서에 미전파 |
| R2-03 | MED | opinet marker_color `P-02`→`P-08` (opinet.py:102) |
| R2-01 | MED | khoa marker_icon `swimming`→`beach` (khoa.py:187) |
| R2-05 | MED | dagster-boundary가 미존재 `ProviderSyncState`/`ImportJobState` DTO 참조 → `SyncState`(infra) |
| R2-06 | MED | `feature-files-rustfs.md` khoa dataset_key 잔존 stale → `khoa_beaches` |
| R2-07 | MED | forest category leaf(03030101/01030101)→parent(03030000/01030000) + dataset key `kr` 접두 |
| R2-09 | MED | notice-etl가 미구현 `forest_safety_notices`/`khoa_coastal_notices`를 현행처럼 나열 → planned 표기 |
| R2-15 | MED | provider-contract §3/§weather가 미구현 forest 하위 dataset(`krforest_trails`/`mountain_weather`/`safety_notices`/`forest_fire_risk`) + `khoa_coastal_notices`를 현행처럼 나열 → **(계획 — 미구현)** 표기(krforest.py는 recreation_forests/arboretums 2종만 구현) |
| R2-02/08/10/11/13/14 | LOW | khoa 자연키 구분자·order / opinet·krex PricePoint 스니펫 / e2e 카운트 23→22·34→33(본 리포트 자체) / WS `/ops/live` rest-api 누락 / category airkorea cross-ref / dagster curated job명 |
| R2-12 | INFO | airkorea/krairport asset에 schedule 없음(on-demand) — F-03류 |

> **추가 코드 후속(문서 무관)**: `pyproject.toml:244` 주석의 layer 순서가 거꾸로(배열은 정본 정상) —
> 본 패스는 코드 미수정, `T-AUDIT-0616`에 코드 후속으로 기록.
