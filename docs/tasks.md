# tasks.md — 백로그

이 문서는 작업 백로그다. 우선순위 순. 각 작업은 `T-NNN` 번호로 식별한다.

> **완료/아카이브 task는 [`docs/tasks-done.md`](tasks-done.md)로 분리**(2026-06-09). 본 파일은 **진행 중/예정(`[ ]`) + 가이드**만 둔다. 완료된 Phase·백로그는 archive 참조.

## 진행 중인 작업 인덱스 (열린 `[ ]` 항목)

> 총 21건. 상세는 아래 각 섹션. 완료 이력은 [`tasks-done.md`](tasks-done.md).

- **다음 (우선순위 순)**
  - [ ] 공통 maki marker / category 매핑 npm 패키지 추출
  - [ ] `python-knps-api` provider 등록 / KNPS 적재 준비
  - [ ] TripMate 측 후속 작업 추적
- **보류 (v2 1차 범위 외)**
  - [ ] Materialized View 도입 검토
  - [ ] pg_prewarm 부팅 후 warm-up
  - [ ] streaming ETL (Kafka/Redpanda) 대응
- **Phase 6 — TripMate 연계/정리 (일부 TripMate repo)**
  - [ ] T-210a
  - [ ] T-210b
  - [ ] T-210c
  - [ ] T-210d
  - [ ] T-210e
- **Phase 6.7 — Feature 사용자 요청 CRUD/versioning (2026-06-08, `T-215`)**
  - [ ] T-215b — admin UI feature change queue 화면.
  - [ ] T-215c — frontend generated type/e2e workflow 보강.
- **Phase 6.8 — REST API 정합성 심화 (2026-06-09, `T-216`, ADR-048)**
  - [ ] T-216a — `/v1` clean cut(admin/ops/debug 포함).
  - [ ] T-216b — pagination 단일화.
  - [ ] T-216c — envelope payload/meta 분리.
  - [ ] T-216d — parameter/error/좌표 정합성.
  - [ ] T-216e — 명명 통일(경로+응답 본문, 본질 기준).
  - [ ] T-216f — 코드/DB 명명 전파(surrogate만).
  - [ ] T-216g — 단일 정본 수렴 + 버전 거버넌스.
- **Phase 7 — ADR-045 전체점검/튜닝 (ADR-045 잔여 task 완료 후 시작)**
  - [ ] T-212e

## 진행 중

**진행 중**: Sprint 5 운영 진입 마무리. main은 ADR-045 독립 프로그램화 핵심
구현(T-205~T-209), 정합성 Phase 2(T-201b), 운영 게이트(T-202~T-204), TripMate
요구사항 후속(T-213a~h), T-RV-04b provider live wiring, T-212a inventory,
T-212b admin UI 완결성, T-212c API/error/log contract, T-212d seeded PostGIS
성능 baseline, T-209e backup/restore 최종 safety automation까지 merged 또는 PR
진행 범위로 닫았다. REST API v1 정리 후속은 `T-214`로 분리했다.

Sprint 5 종료까지 남은 작업은
`docs/reports/sprint5-final-task-breakdown-2026-06-07.md`를 정본으로 상세화했다.
권장 순서는 **T-212e 실데이터 full reload → T-214 REST API v1 정리 →
T-210 TripMate 연계 정리 → Sprint 5
closure**다. T-207b는 사용자 결정에 따라 구현하지 않는다.

### 현재 기준 보강 필요 체크포인트 (2026-06-03)

1. ~~**MOIS 4a 진입**~~ ✅ 완료 — MOIS Step A~D lifecycle + dedup-merge +
   `feature_merge_history`(alembic 0007) + dedup 운영 통계 + ADR-033 F4 +
   Place phone enrichment (PR#133~#142). coverage 80% 달성.
2. ~~**dedup queue 운영화**~~ ✅ 1차 — dedup-merge 명령 + 운영 FP 통계
   (`status_repo.dedup_fp_stats`) + F4 baseline. 실 운영 데이터로 가중치 재조정은
   큐가 채워진 뒤(MOIS bulk 운영 후).
3. **ADR-045 독립 프로그램 전환 반영** — krtour-map은 Docker 독립
   프로그램 + 독립 DB/Dagster + TripMate OpenAPI 연동을 기준으로 구현한다. D-1~D-16
   의사결정은 전부 완료됐고, 구 모델 호환 shim은 만들지 않는다(ADR-046). Admin API는
   `docs/openapi-admin-contract.md`, POI/cache target은
   `docs/poi-cache-update-targets.md` 기준.
4. **문서 최신성 유지** — provider 주소 보강용 geocoding endpoint 정본은
   kraddr-geo REST v2 `POST /v2/reverse`, `POST /v2/geocode`, 로컬 포트는
   `http://127.0.0.1:9001`. geocoding 전용 디버깅 화면은 kraddr-geo 프로젝트에서
   관리하고, krtour-map-admin에는 두지 않는다. frontend 현재 기준은 Next.js 16 +
   `maplibre-vworld-js#v0.1.2`.
5. **고정 포트** — krtour-map 독립 프로그램 로컬/standalone 포트는 API `9011`,
   admin UI `9012`, Dagster `9013`이다(ADR-047). 해당 포트를 점유한 프로세스는
   `scripts/stop-fixed-ports.sh`로 종료하고 재기동한다.
6. **RustFS 포트** — 로컬 RustFS 표준은 S3 API `9003`, console `9004`다. 객체
   저장소 endpoint/public URL 예시는 `9003`을 기준으로 작성하고, console 링크는
   `9004`만 사용한다.
7. **admin Dagster 운영 화면** — `/admin/dagster`는 `GET /ops/dagster/summary` 자체
   요약 UI, schedule/sensor tick history, `GET /ops/dagster/runs/{run_id}` failure
   drilldown, Dagster webserver embed를 제공한다. Dagster NUX 처리는
   `POST /ops/dagster/nux-seen`으로 분리해 GET 부수효과를 만들지 않는다. T-208e는
   queue/sensor 실행 연결을 Dagster package에 추가한다.
8. **feature update request 큐** — T-205a에서 `ops.feature_update_requests` 테이블과
   ORM 매핑을 추가했고, T-206b에서 request/import job lifecycle repo, T-206c에서
   `AsyncKrtourMapClient` 표면을 추가했다. T-206d는 runner 주입형 실행 본체이며,
   T-207a는 admin REST 생성/조회/취소/run-now 재큐잉을 연결했고, T-207f는
   POI/cache target REST와 by-target 주변 feature 조회를 연결했다. T-208e는
   Dagster sensor/job으로 request 실행을 연결한다.
9. **scope resolver** — T-206a에서 `feature_ids`, `center_radius`, `bbox`,
   `sigungu_by_radius`, `provider_dataset` dry-run/count resolver를 구현했다.
   `cache_target_keys`는 T-206d에서 active POI/cache target 기반 resolver와 target
   link 재계산으로 연결한다.
10. **admin UI #9 우선순위** — T-208i는 CSV/TSV preview/validation/load gate를 닫는
    마지막 offline upload 선행 task다. 이후 admin UI 완성도 보강은 T-212 전체점검
    묶음에서 table CRUD, 지도뷰, 이슈 승인/거절, API debug/test, Dagster 모니터링,
    시스템 로그까지 한 번에 gap audit한다.
    T-RV-19에서 `/admin/poi-cache-targets` 목록은 keyset cursor와 frontend
    이전/다음 pagination을 사용하고, target 등록 request의 `provider_overrides`와
    `metadata`는 typed/상한 schema로 검증한다.
11. **CI 기준** — PR 생성 후 GitHub Actions 결과를 확인하고, 실패가 있으면 같은
    브랜치에서 원인/수정/재검증을 반영한 뒤 머지한다.
12. **검증 기준** — WSL unit/integration/live pytest + Windows Playwright e2e + GitHub
   Actions green 후 머지.
13. **코드 수정 원칙** — 최소 코드 수정이나 임시 호환성보다 완성도, 최적 구조,
   확장성, 안정성을 우선한다. schema/DTO/repository/API/test가 같은 계약을 공유하도록
   수정하며, 필요한 구조 변경은 task/PR 단위로 작게 쪼개 진행한다.


## T-RV-50 시리즈 — T-RV-04b 완전 마무리 + 후속 (데이터소스 전수 + dedup UI + maplibre)

> 사용자 지시(2026-06-07): T-RV-04b 및 후속 관련 모든 task가 완료될 때까지 진행.
> ① 계획된 모든 데이터소스 구현/테스트(visitkorea·휴양림/수목원·박물관/미술관 — knps/krheritage는
> 완료) ② 라이브러리 수정은 `python-*-api` 직접 PR+머지 ③ 데이터소스별 admin(debug) UI 상세
> ④ MOIS 중복 가능 소스는 MOIS dedup + 수동 처리 UI ⑤ 축제 datagokr(기본)↔visitkorea(enrichment)
> dedup도 같은 UI ⑥ maplibre-vworld-js 최신 dependency 업데이트 ⑦ 우선순위 가이드 중 T-RV-04b
> 관련/후속은 task화 후 진행. **provider 라이브러리 surface는 조사 완료(2026-06-07)** — 아래 각
> task에 client/모델 명시.

**현 상태(조사 결론)**: 9단계 ADR-034 중 1~7 완료(축제 datagokr / 날씨 / 유가(opinet bbox 보강) /
휴게소 / 국립공원·트래킹 knps / 국가유산 krheritage / MOIS A+B). 미구현 = **8 휴양림/수목원
(krforest, 모듈 없음)** · **9 박물관/미술관(standard_data는 festival만)** · **visitkorea 축제
enrichment(모듈 있음, 미wiring)**. dedup 인프라(scoring/queue/admin router+page)는 성숙하나
**merge master 선택 UI 미완 + 기본 scope 미설정**.

- [x] **T-RV-50 maplibre-vworld-js 최신화**(point 6, 2026-06-07): `v0.1.2..main` diff = **docs-only**
  (src/dist 동일). maplibre repo에 **v0.1.3** patch 릴리스 cut(`maplibre-vworld-js#47` merged + tag) —
  consumer feature catalog 동기화(#46)·tasks(#45) 캡처, 기능 변경 없음. frontend 핀
  `#v0.1.2`→`#v0.1.3`. **코드 수정 불필요**(public API 동일). 로컬 검증: `npm ls`로 v0.1.3 resolve
  확인 + `tsc --noEmit` + `next build` 13 페이지(/features maplibre 포함) green. 기능 동일이라
  e2e 거동 불변(CI type-check+build 게이트로 검증).
- **T-RV-51 dedup 수동처리 UI 완성 + 기본 scope**(point 4 foundation, 세분화):
  - [x] **T-RV-51a (frontend) merge master 선택 UI**(2026-06-07): `dedup-review`에 merge 액션 추가 —
    inline master 선택 패널(`A: <name>·좌표✓` / `B: <name>·좌표✓` / **자동 선정** / 취소). 자동 선정은
    `master_feature_id` 미전달 → backend `select_master`(좌표→updated_at→provider 우선순위). 수동
    선택 시 feature A/B의 `feature_id` 전달. API/types 변경 없음(계약 기구현). type-check/eslint/
    next build green. 기존 e2e(render smoke) 유지.
  - [x] **T-RV-51b (backend) 기본 dedup scope baked**(2026-06-07): maintenance.py에
    `DEFAULT_DEDUP_SCOPE_PAIRS`(현재 **knps↔krheritage** 1쌍 — 동일 사찰/문화재 중복) +
    `DEFAULT_DEDUP_SIBLING_SCOPES`(현재 없음) 추가. `refresh_dedup_candidates_op`은 op_config의
    pairs/sibling_scopes가 **둘 다 비면** 기본값을 적용 → Dagster run config 없이도 cross-provider
    dedup 실행. canonical provider name 사용. dagster 단위(빈 config→기본 pair 적용) green.
    **krforest↔MOIS·museum↔MOIS pair는 해당 데이터소스 PR에서 이 tuple에 append.**
- [x] **T-RV-52 visitkorea 축제 enrichment wiring**(points 1·5·5.1)(2026-06-08 완료): datagokr
  축제(1차)에 visitkorea(2차) 이미지/overview/homepage enrichment. 52a provider + 52b krtour
  wiring + 52c review 큐/admin API/frontend(자동 매칭 실패분 수동 검토) 전부 완료.
  - [x] **T-RV-52a (provider)**(2026-06-07) `python-visitkorea-api#17`(merged, **v0.2.0**) — `TourItem`에
    `event_start_date`/`event_end_date`(searchFestival `eventstartdate`/`eventenddate` promote, str
    YYYYMMDD) + `overview`/`homepage`(detailCommon 보강용, list 응답엔 None) 필드 추가 → krtour
    `VisitKoreaFestivalItem` Protocol 4필드 속성 존재 충족. ruff/mypy/pytest 96 passed. **overview/
    homepage는 detailCommon에서만 오므로 52b 매칭 item에 한해 N+1 detail 호출로 보강.**
  - [x] **T-RV-52b (krtour)**(2026-06-07) 3 PR로 세분:
    - **52b-1** `ScoringFestivalMatcher`+`FestivalCandidate`(providers/visitkorea, 이름 Jaro-Winkler
      유사도 임계 0.90). - **52b-2** `EnrichmentLoadResult`+`load_source_record_links`(infra) +
      `client.load_enrichment_links`. - **52b-3** `fetch_visitkorea_festival_events`(sync, KrTourApiClient
      iter_pages, 올해 1월~) + `client.load_festival_enrichment`(한 transaction: datagokr 축제 candidate
      `list_dedup_refresh_features` 로드 → matcher → `festival_to_enrichment_links` → load) +
      `feature_event_visitkorea_enrichment` asset(EnrichmentLoadResult 반환) + resource + definitions.
      dagster 66 + unit 932 + coverage 80.68% green. **overview/homepage N+1 detail 보강은 후속**
      (현재 list 기반 enrichment = 이미지+content_id+event date; matched feature에 SourceRecord/Link).
  - **T-RV-52c (review 큐+UI)** 축제 datagokr↔visitkorea 매칭/enrichment를 dedup-review와 **같은
    방식**으로 수동 검토. 3 PR로 세분:
    - [x] **52c-1 (backend domain/infra)**(2026-06-08) 이름 유사도 점수 밴드 분류 +
      `ops.enrichment_review_queue` 영속화. `ScoringFestivalMatcher.best_match`(임계 비의존) +
      `festival_to_review_candidates`(auto ≥0.90 / review-band [0.70,0.90) / drop <0.70,
      `FestivalMatchPlan`) (providers/visitkorea). migration `0019_enrichment_review_queue` +
      `EnrichmentReviewQueueRow`(models) + `infra/enrichment_review_repo.py`(enqueue/pending/decide,
      accept→ENRICHMENT link 적재, ADR-020상 generic `EnrichmentReviewInput`로 provider 비의존) +
      client `refresh_festival_enrichment_reviews`/`list_pending_enrichment_reviews`/
      `resolve_enrichment_review`. 게이트: ruff/mypy(map 84/dagster 13/admin 25)/lint-imports/unit+lint
      959(coverage 81%)/integration(enrichment_review_repo 7 + client 6) green.
    - [x] **52c-2 (admin API)**(2026-06-08) `GET /admin/enrichment-review`(pending list, status/
      provider/score/q 필터 + name_score cursor) + `PATCH /admin/enrichment-review/{review_key}`
      (accept→enrichment 적재/reject/ignore, 이미 검토 시 409). `list_enrichment_reviews`
      (admin_feature_repo, 1차 feature join) + `enrichment_review` router(app/routers 등록) +
      Pydantic 모델 + OpenAPI 재생성(openapi.json만, /admin은 user profile 제외). 게이트:
      ruff/mypy(map 84/dagster 13/admin 26)/lint-imports/unit+lint 959(coverage 81%)/admin 220/
      dagster 75 + drift-check + integration(list_enrichment_reviews) green.
    - [x] **52c-3 (frontend)**(2026-06-08) dedup-review와 유사한 `admin/enrichment-review` 페이지
      (pending list + accept/reject/ignore; 병합 없으니 master 선택 UI 없음, 1차/2차 양측 표시) +
      `src/api/enrichment.ts` 훅(`useEnrichmentReviews`/`useEnrichmentDecisionMutation`) + nav 항목
      (admin-shell) + e2e smoke(admin-ops.spec). 게이트: gen:types:check(drift 0)/tsc/next build
      (route 등록 확인)/eslint green. **→ T-RV-52c 전체 완료.**
- [x] **T-RV-53 휴양림/수목원(krforest) feature-load**(points 1·2·3·4) — **완료(2026-06-07, sub-task a~d 전부 머지; 실데이터 fetch 검증은 T-212e)**. provider `python-krforest-api`
  `ForestClient().travel.standard_recreation_forests()`→`StandardRecreationForest`(institution_code
  stable id / name / address / lat·lon WGS84 / phone / homepage), 수목원/식물원은 SHP file
  (`recreation_forest_arboretums()`→`ForestSpatialPoint`). env `DATA_GO_KR_SERVICE_KEY`. (READY 판정.)
  - [x] **T-RV-53a (krtour)**(2026-06-07) `providers/krforest.py` 신설 — Protocol
    `RecreationForestItem`/`ForestSpatialItem` + `recreation_forests_to_bundles`(place,
    category `LODGING_RECREATION_FOREST` 03030000, place_kind `recreation_forest`) +
    `arboretums_to_bundles`(category `TOURISM_BOTANICAL` 01030000, place_kind `arboretum`).
    좌표 float→`Decimal` 변환, 안정키 `institution_code`(없으면 `name::sido` 또는 `name::region`
    파생, ADR-009 `::`). `PlaceDetail`(phones/facility_info). `providers/__init__` re-export.
    단위 9건(happy/derived-key/arboretum/PRIMARY/결정성/naive reject/reverse bjd) green.
    게이트: ruff/mypy(81 files)/lint-imports/unit 914 passed/coverage 80.53%.
  - [x] **T-RV-53b (krtour)**(2026-06-07) `fetch_krforest_recreation_forests`/`fetch_krforest_arboretums`
    (async generator — `ForestClient`는 async, recreation은 `iter_pages` 페이지네이션, arboretum은
    `travel.recreation_forest_arboretums()` SHP) + `feature_place_krforest_recreation_forests`/
    `feature_place_krforest_arboretums` asset + resource spec/guard→live override + definitions 등록.
    credential = `data_go_kr_service_key`. dagster 단위(fake ForestClient 3 + asset 등록 + live key)
    green(62 passed). arboretum SHP는 provider geo extra 의존 — 실 fetch 검증 T-212e.
  - [x] **T-RV-53c (dedup)**(2026-06-07) `DEFAULT_DEDUP_SCOPE_PAIRS`에 자연휴양림↔MOIS pair 추가:
    left `{krforest, krforest_recreation_forests}` ↔ right `{mois, categories 03010100(관광숙박)/
    03020100(전문리조트)/03020200(종합리조트)}`로 MOIS side를 LODGING 카테고리로 좁혀 대규모 비교 회피.
    **수목원(arboretum)은 MOIS PROMOTED 슬러그에 식물원/수목원이 없어 dedup 후보가 없으므로 pair
    미추가**(SOURCE_PRIORITY krforest=45 기존). dagster 단위(기본 pair 2건 검증) green.
  - [x] **T-RV-53d (admin debug UI)**(2026-06-07) krforest를 ETL preview 레지스트리에 등록 —
    `etl_fixtures.FIXTURE_REGISTRY`에 `krforest_recreation_forests`/`krforest_arboretums` 2 entry
    (fixture dataclass + builder + `*_to_bundles` convert) 추가 → `/debug/etl/providers`·
    `/debug/etl/{provider}/{dataset}/preview`에 자동 노출(dry-run place FeatureBundle). admin mypy
    25 files + etl router 25 passed + preview 실행(count 2/1, kind place) 확인. dedup은 dedup-review
    UI(T-RV-51a)에 자동 노출(53c scope). **NOTE: ETL preview 레지스트리는 Sprint-2 provider만 있었고
    knps/krheritage/mois도 미등록 — 후속 정리 후보.**
- [x] **T-RV-54 박물관/미술관(standard_data) feature-load**(points 1·3·4) — **완료(2026-06-07, sub-task a~d 전부 머지; 실데이터 fetch 검증은 T-212e)**. provider `datagokr`
  `client.museum_art.iter_all()`→`PublicMuseumArtGallery`(instt_code / fclty_nm / fclty_type /
  rdnmadr·lnmadr / lat·lon / phone / homepage). (READY 판정.)
  - [x] **T-RV-54a (krtour)**(2026-06-07) `standard_data.py` 확장 — `museums_to_bundles`(place) +
    `PublicMuseumArtItem` Protocol. category는 `fclty_type`으로 박물관(`01040100`)/미술관(`01040200`)
    분기, 미상 시 부모 `01040000`. place_kind `museum`, 좌표 float→Decimal, 안정키 `instt_code`
    (없으면 `name::road` 파생). `providers/__init__` re-export. 단위 7건(박물관/미술관 category 분기/
    파생키/미상 fallback/PRIMARY/결정성/naive/reverse) green. ruff/mypy(81)/lint-imports/unit 921/
    coverage 80.64%.
  - [x] **T-RV-54b (krtour)**(2026-06-07) `fetch_standard_museums`(sync generator —
    `DataGoKrClient.museum_art.iter_all()`, datagokr client sync) + `feature_place_standard_museums`
    asset(`museums_to_bundles` 소비) + resource spec/guard→live + definitions 등록. credential
    `data_go_kr_service_key`. dagster 단위(fake museum_art 2 + asset 등록 + live key) green(64 passed).
  - [x] **T-RV-54c (dedup)**(2026-06-07) `DEFAULT_DEDUP_SCOPE_PAIRS`에 박물관/미술관↔MOIS pair 추가:
    left `{data.go.kr-standard, datagokr_museums}` ↔ right `{mois, categories [01040000]}`. MOIS
    `museums_and_art_galleries`는 `01040000`으로 적재되므로 그 카테고리로 좁힘. dagster 단위(기본
    pair 3건) green.
  - [x] **T-RV-54d (admin debug UI)**(2026-06-07) `etl_fixtures.FIXTURE_REGISTRY`에
    `data.go.kr-standard/datagokr_museums` entry(fixture+convert) 추가 → ETL preview 노출.
    admin mypy 25 + etl router 25 passed + preview 실행(count 2, cats 01040100/01040200) 확인.
- **T-RV-55 우선순위 가이드 후속(point 7, 사용자 결정: 보조까지 전부)**: ADR-034 보조 dataset.
  - [x] **T-RV-55a 관광지(tourist_attraction)**(2026-06-07) — datagokr `tourist_attraction.iter_all()`
    →`PublicTouristAttraction`. `standard_data`에 공용 `_standard_place_to_bundle` helper +
    `tourist_attractions_to_bundles`(place, category `TOURISM 01000000`, place_kind
    `tourist_attraction`) + `PublicTouristAttractionItem` Protocol. fetcher/asset/resource/definitions
    + tourist↔MOIS dedup(left datagokr_tourist_attractions ↔ MOIS `tourism_businesses` 01000000) +
    ETL preview 등록. 게이트: ruff/mypy(3 pkg)/lint-imports/unit 936+coverage 80.74%/dagster 68 green.
  - [x] **T-RV-55b 주차장(parking)**(2026-06-08) — datagokr `parking.iter_all()`→`PublicParkingLot`.
    `parking_lots_to_bundles`(place, category `TRANSPORT_PARKING 06010000`, place_kind `parking`,
    공용 `_standard_place_to_bundle` 재사용) + `PublicParkingLotItem` Protocol. 안정키 `prkplce_no`
    (없으면 instt_code→name::road). fetcher/asset/resource/definitions + ETL preview. **MOIS dedup
    없음**(MOIS PROMOTED에 주차장 슬러그 없음). 게이트: ruff/mypy(3pkg)/lint-imports/unit 939
    (coverage 80.81%)/dagster 70 green + parking preview(cat 06010000) 확인.
  - [x] **T-RV-55c khoa 해수욕장**(2026-06-08) — provider `python-khoa-api` `KhoaClient.oceans_beach_info
    (sido)`→`OceanBeachInfo`. 신규 `providers/khoa.py`(`beaches_to_bundles`, place, category
    `COAST_ISLAND 01020300`, place_kind `beach`) + `OceanBeachInfoItem` Protocol. 도로명 주소 없어
    좌표 reverse만으로 bjd 보강, admin=sido+gugun, 안정키 `name::sido::gugun` 파생. fetcher(시도별
    `OCEANS_BEACH_INFO_DEFAULT_SIDO_NAMES` 순회 페이지네이션)/asset/resource/definitions/ETL preview.
    MOIS dedup 없음(해수욕장 슬러그 없음). 게이트: ruff/mypy(map 82/dagster 13/admin 25)/lint-imports/
    unit 942(coverage 80.92%)/dagster 72 + khoa preview(01020300/beach) green. (해양공지는 후속.)
  - **T-RV-55d airkorea 대기질** — place feature 아님(측정값) → **사용자 결정(2026-06-08): 지금
    구현, station=weather feature**. 기존 WeatherValue 패턴 재사용(`WeatherDomain.AIR_QUALITY` 기존
    정의, `feature.feature_weather_values` 재사용). 2 PR:
    - [x] **55d-1 (provider)**(2026-06-08) `providers/airkorea.py`: `air_quality_stations_to_bundles`
      (측정소→**weather kind** FeatureBundle, category `99000000`=KMA 특보와 동일 비place placeholder,
      detail 없음) + `AirQualityStationItem` Protocol; `air_quality_to_weather_values`(측정 row→오염
      물질별 `WeatherValue`, domain `air_quality`/style `observed`, PM10/PM2_5/O3/NO2/SO2/CO/CAI,
      grade→severity, KMA value 변환 미러) + `AirQualityMeasurementItem` Protocol. 결측 오염물질/
      미매핑 측정소 skip. 게이트: ruff/mypy(map 85/dagster 13/admin 26)/lint-imports/unit+lint 965
      (coverage 81%, airkorea.py 96%) green.
    - [x] **55d-2 (orchestration)**(2026-06-08) client `load_air_quality`(측정소 bundle +
      WeatherValue를 한 transaction에 적재, FK 선결) + `AirQualityLoadResult`(infra/feature_repo) +
      dagster `fetch_airkorea_stations`/`fetch_airkorea_air_quality`(시도별 17개 순회) +
      `feature_weather_airkorea_air_quality` asset(measurements×stations 조인 → load) + resource
      spec×2/guard→live + definitions + ETL preview×2(stations FeatureBundle / air_quality
      WeatherValue). 게이트: ruff/mypy(map 85/dagster 13/admin 26)/lint-imports/unit+lint 965
      (coverage 81%)/full 1168/admin 224/dagster 79 + airkorea preview(weather kind/air_quality)
      green. **→ T-RV-55 + T-RV-04b 후속 program 전체 완료.**
  - [x] **T-RV-55e krairport 공항**(2026-06-08) — provider `python-krairport-api`
    `KrairportClient.airports(active=True)`(번들 정적 메타데이터, **keyless**)→`AirportMetadata`.
    신규 `providers/krairport.py`(`airports_to_bundles`, place, category `TRANSPORT_AIRPORT
    06050000`, place_kind `airport`) + `AirportMetadataItem` Protocol. 좌표 = provider
    `Coordinate`(`.lat`/`.lon`) 중첩 객체 `_coord_of` 추출(None 안전), 도로명 주소 없어 좌표
    reverse로 bjd 보강, 안정키 = 공항 코드(IATA). fetcher(keyless, key 있으면 kac/iiac 주입)/
    asset/resource(setting_names 없음→항상 live)/definitions/ETL preview. MOIS dedup 없음(공항
    슬러그 없음). 게이트: ruff/mypy(map 83/dagster 13/admin 25)/lint-imports/unit 951(coverage
    81%, krairport.py 97%)/dagster 73 + krairport preview(06050000/airport) green.

각 task는 작은 독립 PR + origin/main rebase + 격리 WSL sandbox + (provider 수정 시 해당 repo
PR+머지 선행) + (endpoint/OpenAPI 추가 시 frontend `types.ts` 재생성) + 게이트 전수(ruff/mypy/
lint-imports/pytest/coverage, frontend type-check/e2e). 실데이터 검증은 T-212e.

- ~~**T-RV-05/11** D-6 run-now 409 LOCK_BUSY+retry_after 미구현 + claim 락경합/
  빈 큐 미구분(run-now 작업 조용히 누락).~~
  ✅ `run_mode=now` enqueue/run-now 재큐잉에 scope advisory lock preflight를 추가하고,
  executor가 실행 중 같은 scope lock을 보유한다. lock 경합은 admin API에서
  `409 LOCK_BUSY` + `Retry-After` + `retry_after_seconds` details로 응답한다.
  `claim_next_update_request`는 queue lock 경합 시 `FeatureUpdateQueueLockBusy`를
  올려 빈 큐와 구분한다.
- ~~**T-RV-06** 에러 envelope `{error:{code,message}}` 전무(테스트가 `detail` 고착).~~
  ✅ app-level `HTTPException`/`RequestValidationError` handler,
  `{error:{code,message,details,request_id}}`, `X-Request-ID`, router test 교정 반영.
- ~~**T-RV-07** admin/ops 라우터 무조건 mount(DB 없는 부팅에서 write 노출).~~
  ✅ `admin_routes_enabled`/`ops_routes_enabled`를 추가하고 unset이면
  `features_routes_enabled`를 따르게 해 DB 없는 부팅 검증에서 features/admin/ops
  surface를 함께 닫는다.
- ~~**T-RV-08** D-7 공개 응답 내부 필드 누출(nearby/by-target, FeatureDetail).~~
  ✅ public `FeatureDetailResponse`에서 SRID/parent/sibling 내부 필드를 제거하고,
  `/features/nearby/by-target`에서 target 운영 필드와 provider/dataset 내부 식별자를
  제거했다. `openapi.user.json` 누출 회귀 테스트를 추가했다.
- ~~**T-RV-09** offline-upload 업로드 크기 상한 없음 + 전체 버퍼링(OOM/DoS).~~
  ✅ `KRTOUR_MAP_OFFLINE_UPLOAD_MAX_BYTES` + `413` + bounded read 회귀 테스트 반영.
- ~~**T-RV-10** keyset cursor float/decimal 정밀도·정렬축 불일치(행 skip/dup).~~
  ✅ `/features/search`는 DB score text cursor와 `(-score, feature_id)` row-tuple
  비교로 `ORDER BY score DESC, feature_id ASC`와 같은 축을 사용한다.
  `/admin/dedup-review`는 `NUMERIC` score를 string cursor로 운반하고 predicate와
  `ORDER BY` 모두 `review_key::text`를 사용한다. 동점 다중 페이지 walk
  integration test를 추가했다.
- ~~**T-RV-27** admin API `0.0.0.0` 노출(ADR-005/.env 모순)~~ ✅
  Docker compose host publish 기본값을 `KRTOUR_MAP_DOCKER_BIND_HOST=127.0.0.1`로
  제한했다. 컨테이너 내부 listen은 유지하되 host 모든 interface 노출은
  `KRTOUR_MAP_DOCKER_BIND_HOST=0.0.0.0` 명시 opt-in과 네트워크 보호 전제 문서로만
  허용한다.

**MED (정확성/일관성):**
- ~~**T-RV-12** dedup pair 순서 독립 unique/DB check.~~
  ✅ `ops.dedup_review_queue`에 `feature_id_a < feature_id_b`
  `ck_dedup_pair_order`를 추가하고, `dedup_repo` upsert가 pair를 canonicalize한다.
  migration은 기존 self-pair 제거, unordered duplicate 정리, canonical 방향 정규화를
  수행한다.
- ~~**T-RV-13** UUID default 스키마 표준화.~~
  ✅ bare `gen_random_uuid()` default가 남아 있던 ops 테이블 4곳을
  `x_extension.gen_random_uuid()`로 통일하고, 기존 DB default ALTER migration과
  Postgres catalog integration test를 추가했다.
- ~~**T-RV-14** dedup merge review row `FOR UPDATE` 누락.~~
  ✅ `merge_from_review`와 admin `merge_dedup_review`의 review row 조회에
  `FOR UPDATE`를 추가하고, 자동/수동 merge 경로가 row lock을 기다리는지 Postgres
  integration test로 검증한다.
- ~~**T-RV-15** scope resolver 무한정/dry-run materialize.~~
  ✅ `count_features_matching_scope`는 `feature_ids`, `center_radius`, `bbox`,
  `sigungu_by_radius`, `provider_dataset`에서 전체 feature row를 들지 않고
  count/provider/sigungu 집계를 별도 SQL로 계산한다. feature list는 기본 1000개
  preview로 제한하고 truncation metadata를 matched scope에 남긴다.
- ~~**T-RV-16** dedup refresh master 선정 신호 부재/keyset 없음.~~
  ✅ `Feature`/`feature.features`에 `coord_precision_digits`를 추가하고, DB trigger와
  check constraint로 coord/precision 의미를 강제한다. `list_dedup_refresh_features`는
  `updated_at DESC, feature_id DESC` keyset cursor와 partial index를 사용하며,
  `DedupRefreshFeature`는 `updated_at`, `coord_precision_digits`,
  `as_master_candidate()`를 노출한다.
- ~~**T-RV-17** 상태전이 가드.~~
  ✅ `admin_feature_repo.deactivate_feature`는 deleted/soft-deleted feature를
  inactive로 부활시키지 않고 `FeatureStateConflict`를 올린다.
  `integrity_violation_repo.set_status`는 terminal 상태(`resolved`/`ignored`)의 재오픈을
  막고 멱등 terminal 재호출 시 `resolved_at`을 보존한다. `offline_upload_repo`는
  validation/load mark/finish 전이에 source-state guard를 추가하고, `loaded`에서
  다시 `loading`으로 돌아가는 중복 Dagster launch 경로를 차단한다.
- ~~**T-RV-18** router substring 기반 status 매핑.~~
  ✅ `MergeNotFoundError`/`MergeConflictError` 하위 타입을 추가해
  `/admin/dedup-review` merge 404/409를 문구 substring이 아니라 타입으로 매핑한다.
  feature update request 라우터는 `SigunguResolverUnavailable`으로 kraddr-geo 설정
  누락을 503으로 매핑하고, 미분류 enqueue/merge 예외의 내부 메시지를 500 응답에
  노출하지 않는다.
- ~~**T-RV-20** feature update request schema 검증.~~
  ✅ `POST /admin/feature-update-requests`는 `scope.type` discriminator 기반 6개
  scope 모델을 검증하고, `update_policy`는 알려진 필드만 허용한다.
  `providers`/`dataset_keys`에는 list 상한을 추가했고, admin frontend 생성 payload도
  `center: {lon, lat}` 계약으로 맞췄다.
- ~~**T-RV-28** frontend Docker npm lockfile 미커밋 + `npm install`.~~
  ✅ root `package-lock.json`을 커밋하고, frontend Docker build를
  `npm ci --workspaces --include=optional`로 전환했다. `.gitignore`/`.dockerignore`도
  lockfile 포함 기준으로 정리했다.
- ~~**T-RV-26** Docker compose healthcheck/readiness.~~
  ✅ `api`/`frontend`/`dagster` healthcheck를 추가하고, frontend가 API
  `service_healthy` 이후 시작하도록 `depends_on`을 long form으로 전환했다.
  compose 회귀 테스트로 healthcheck와 readiness order를 고정했다.
- ~~**T-RV-36** Dagster package dependency hygiene.~~
  ✅ Dagster 패키지 runtime dependencies에 같은 릴리스의
  `python-krtour-map==0.2.0-dev` 핀과 `boto3`/`botocore` 직접 의존성을 추가했다.
  패키지 로컬 `asyncio_mode="auto"`와 pyproject 회귀 테스트도 추가했다.
- ~~**T-RV-21** Dagster router GET 부수효과/SSRF/client lifecycle.~~
  ✅ `GET /ops/dagster/summary`에서 `setNuxSeen` mutation을 제거하고
  `POST /ops/dagster/nux-seen`으로 분리했다. backend는
  `KRTOUR_MAP_ADMIN_DAGSTER_ALLOWED_HOSTS` allowlist, http/https scheme, `/graphql`
  path를 검증하고, GraphQL 호출은 app-state 공유 `httpx.AsyncClient`를 사용한다.
- ~~**T-RV-22** offline upload object orphan 방지.~~
  ✅ `POST /admin/offline-uploads`에서 RustFS/S3 object write 후 DB metadata insert가
  실패하면 같은 요청에서 방금 쓴 object만 보상 삭제한다. 정상 등록된 원본의 D-14
  무기한 보존 정책은 그대로 유지한다.
- ~~**T-RV-24** offline upload 상태 집합 단일화.~~
  ✅ `krtour.map.core.offline_upload_states`를 단일 source로 두고 router,
  load/validation orchestration, repo 전이 set을 같은 계약으로 맞췄다.
  `cancelled`는 cancel API 전까지 reserved terminal state로 문서화한다.
- ~~**T-RV-23** offline upload checksum idempotency + load TOCTOU.~~
  ✅ 같은 `provider/dataset_key/sync_scope/checksum_sha256` 조합을 DB unique
  constraint로 막고, 중복 upload는 409 structured error로 기존 upload metadata를
  반환한다. `/load`는 Dagster launch 전에 `ops.import_jobs`와
  `offline_uploads.load_job_id`를 같은 트랜잭션에서 선점하고, Dagster launch 실패 시
  job/upload를 failed 상태로 닫는다. Dagster op는 lock busy를 성공 no-op로 보지 않고
  Failure로 기록한다.
- ~~**T-RV-27** admin API bind 노출.~~
  ✅ Docker compose host publish 기본값을 localhost로 제한하고, 모든 interface 노출은
  명시 opt-in + 네트워크 보호 전제로 문서화했다. (리포트 §2)
- ~~**T-RV-34/35** Dagster sensor/asset 실행 품질.~~
  ✅ sensor cursor dead state를 제거하고 tick당 최대 10개 request를 batch `RunRequest`로
  발행한다. failure sensor는 request 실패 상태 반영/알림 예외를 흡수해 sensor 자체
  실패로 번지지 않게 했다. MOIS bulk record는 batch 변환/적재하고, feature-load
  asset과 consistency/dedup maintenance op에 `RetryPolicy`를 추가했다.
- ~~**T-RV-31/32/33** runner savepoint + router DTO 정확성.~~
  ✅ provider runner 1회 실행을 `begin_nested()` savepoint로 격리해 실패 runner의
  partial write를 rollback하고, `AdminFeatureIssueRecord`를 `extra="forbid"`로 닫았다.
  `/features/nearby/by-target`은 repo SQL의 `f.coord IS NOT NULL` +
  `f.coord_5179 IS NOT NULL` 필터로 public `lon/lat: float` 계약을 유지하며 이를
  테스트로 고정했다.
- ~~**T-RV-29/30** user OpenAPI admin path 누출 + frontend generated type drift.~~
  ✅ user spec의 update request 경로를 `/tripmate/feature-update-requests`로 분리하고
  `/admin/*` 경로를 제외했다. `USER_OPERATIONS` 경로/메서드 drift 테스트를 추가했다.
  frontend는 `openapi-typescript` 산출물 `src/api/types.ts`를 커밋하고 API 모듈 DTO를
  `paths`/`components` 파생 타입으로 전환했으며, frontend CI에 `gen:types:check`를
  추가했다.
- ~~**T-RV-25** offline upload store 재사용.~~
  ✅ `request.app.state.offline_upload_store`를 우선 재사용하고, store가 없을 때만
  설정/S3 client를 1회 생성해 캐시한다. create/preview/validate 경로의 app-state store
  재사용 회귀 테스트를 고정했다.

**LOW:** T-RV-37 묶음 cleanup (리포트 §3).
- ~~**T-RV-37f** 잔여 naming/count/runtime 설정 hygiene.~~
  ✅ ADR-047 참조 정상화(no-op), frontend `DebugUi*`/`debug_ui`를 `Admin*`/`admin`으로
  변경, `/features/search` `total_count`를 실제 전체 매칭 수로 채움, offline upload
  encoding은 `None`으로 파서 fallback에 위임, CORS 커스텀 미들웨어를 제거하고
  Dagster repository selector를 설정화했다. `build_offline_upload_store` 중복은
  main infra S3 factory로 통합했고 frontend production `NEXT_PUBLIC_*` 누락은
  fail-fast 처리했다. T-212 `admin_issues.py`와 T-RV-04b는 별도 에이전트 범위라 제외.
- ~~**T-RV-37a** `scripts/*.sh` Bash 전용 실행 셸 문서화.~~
  ✅ `docs/dev-environment.md`, `docs/runbooks/docker-app.md`,
  `docs/runbooks/README.md`에 WSL/Git Bash 실행 기준과 PowerShell WSL 위임 예시를
  추가했다.
- ~~**T-RV-37b** `dagster-boundary.md` purge job/schedule stale 문서 제거.~~
  ✅ 실제 Dagster 패키지에 없는 `feature_purge_*` asset/job 후보와
  `purge notice old` schedule 행을 제거하고, purge는 TTL·삭제 정책과 실제 job 구현이
  함께 들어오기 전까지 schedule 표에 추가하지 않는다고 명시했다.
- ~~**T-RV-37c** `map-marker-react` peer dependency/git pin 정합.~~
  ✅ `maplibre-vworld` peer dependency를 `0.1.2`로 고정해 workspace devDependency의
  `github:digitie/maplibre-vworld-js#v0.1.2`와 의미를 맞췄다. skeleton test script는
  `--passWithNoTests`를 사용하고, README는 ADR-043 registry 게시 보류 기준으로 정리했다.
- ~~**T-RV-37d** `ops_repo._decode_cursor` broad exception 축소.~~
  ✅ base64/UTF-8/JSON/schema/datetime 오류를 구체 예외로 처리하고, invalid cursor가
  DB query 실행 전에 거절되는지 unit test를 보강했다.
- ~~**T-RV-37e** docker 이미지 multi-stage + non-root USER + frontend standalone 출력.~~
  ✅ `api`/`dagster` Python runtime 이미지를 builder/runtime stage로 분리하고
  `appuser`로 실행한다. `frontend`는 Next.js standalone server 산출물을 runner stage에서
  `nextjs`로 실행한다.


## 다음 (우선순위 순)

- [x] T-012 — ADR-020+ 후속 결정 작성 (proposed → **accepted**, 사용자 승인
  2026-05-29) — ADR-030~033 결정자 라인 정정 + 교차 참조 (proposed) → (accepted)
  - **ADR-030 (accepted)** — 라이브러리 in-memory 캐시 금지
    (`functools.cache` 한정 예외) + `import-linter` 계약. PR#10에서
    `pyproject.toml`에 forbidden 계약 박힘 (PR#16 T-014에서 일괄 accepted).
  - **ADR-031 (accepted)** — 디버그 패키지 OpenAPI export 정책
    (첫 라우터부터 활성화). PR#10에서 `scripts/export_openapi.py` skeleton
    박힘 (PR#16 T-014에서 일괄 accepted).
  - **ADR-032 (accepted)** — Coverage 단계적 상향 일정. PR#10에서
    `pyproject.toml` `fail_under=0` + 주석으로 Sprint 1~5 schedule 박음.
    T-014 + Sprint 1 진입 PR에서 `fail_under=50`으로 상향 + accepted.
  - **ADR-033 (accepted)** — `feature_consistency_reports` 단계적
    도입. T-014 + Sprint 3 진입 PR에서 Phase 1 (F1~F3) accepted.
- [x] **T-014 — 코드 작성 단계 진입** (사용자 승인 2026-05-25, 본 PR#16)
  - ADR 027/028/029/030/031/032/033/034 일괄 accepted 전환
  - `pyproject.toml` `fail_under=0→50` 상향 (ADR-032 Sprint 1 bar)
  - Sprint 1 = **active** (`docs/sprints/SPRINT-1.md` 상태 → active)
  - 후속 Sprint 1 scaffolding PR로 실제 코드 작성:
    - [x] PR#17 `src/krtour/map/` PEP 420 scaffolding + `settings.py` +
          6개 layer placeholder + smoke 테스트
    - [x] PR#18 `src/krtour/map/category/` 144건 (kraddr-base 이전 +
          ADR-027 3건 + tests/unit/test_category.py 16 cases)
    - [x] PR#19 `src/krtour/map/dto/` Feature + 5 detail (place/event/
          notice/route/area) + Coordinate + Address + URLs + OpeningHours +
          `core/types.py` KST/kst_now + ADR-027 적용 (`NOTICE_TYPES` 14건 +
          `AreaDetail.area_kind='hazard_zone'`) + ADR-018 detail discriminator
          + ADR-019 KST aware datetime + 27 dto cases. WeatherValue/
          PriceValue/SourceRecord은 Sprint 2 PR로 연기.
    - [x] PR#20 `src/krtour/map/core/` exceptions 7종 (ADR backend-package.md §5)
          + `make_feature_id` (ADR-009 결정적 SHA1) + tests 42건. scoring stub은
          dto Coordinate 의존 위해 후속 PR로.
    - [x] PR#21 `src/krtour/map/infra/crs.py` (pyproj.Transformer 4326↔5179
          singleton, ADR-030 narrow cache) + `infra/db.py` (async engine +
          session factory + DSN 정규화) + `tests/integration/conftest.py`
          (testcontainers PostGIS, ADR-007/008) + `test_pg_smoke.py` (extension
          격리 + schema + ST_Transform). pyproj>=3.6 dep. 25 unit + 6 integration.
    - [x] **PR#22 (본)** `.github/workflows/{ci,lint,openapi}.yml` + import-linter
          4 계약 활성화 (`tests/lint/test_import_linter.py`) + ADR-002 위반 1건
          실 해소 (KST/kst_now 정의 core/types.py → dto/_time.py 이전).
          ruff/mypy/import-linter all green. **Sprint 1 scaffolding 종료점.**
    - [x] PR#28 `infra/models.py` + Alembic 첫 2 revision (0001/0002) +
          통합 테스트 6 case (Sprint 2 prep, 2026-05-26 merged).
    - [x] **후속 (PR#29 merged)**: `core/scoring.py` (Record Linkage ADR-016) +
          `core/providers.py` (CANONICAL_PROVIDER_NAMES 18종). `core/weather.py`
          + `kst_now` 통합은 Sprint 2 KMA PR(#38~#39)에서 완료.
- [ ] T-017 — **공통 maki marker / category 매핑 npm 패키지 추출** (ADR-029
      proposed, PR#10 merged) — 실 코드는 Sprint 2
  - **ADR-029 (proposed, PR#10 merged)** — `@krtour/map-marker-react` (MIT
    license, monorepo `packages/map-marker-react/`).
  - PR#10에서 skeleton 박힘 (`package.json` / `README.md` / `vite.config.ts`
    / `.gitignore`).
  - 실제 코드 (`src/categoryMaki.ts`, `<MakiMarker>` 등)는 Sprint 2 PR.
  - drift gate: `tests/unit/test_category_maki_consistency.py` (Python ↔ TS
    1:1 검증, Sprint 2 코드 작성).
- [ ] T-018 — **`python-knps-api` provider 등록 / KNPS 적재 준비**
  - **외부 repo keyless file-only 전환 완료** (2026-05-25):
    `digitie/python-knps-api` `06da125f` (PR#3+#4). 공개 API:
    `KnpsClient`, `KnpsConfig`, `FileDataset`, `CatalogEntry`,
    `FileArtifact`, `FileMember`, `CsvPreview`, `CsvPreviewRow` + 예외 계층 +
    catalog helper. 삭제: `ApiEndpoint`, `Page`, `raw_endpoint`,
    `api_endpoint(s)`.
  - **ADR-028 accepted + amendment §H (PR#25)** — keyless, 14건 모두
    file dataset, `KNPS_SERVICE_KEY`/`DATA_GO_KR_SERVICE_KEY` 사용 안 함.
  - **ADR-027 accepted + 코드 적용 완료** — category 144건,
    `NOTICE_TYPES` 14건, `AreaDetail.area_kind='hazard_zone'`.
    PR#25에서 `protected_area`와 `facility_road` DTO 계약 추가.
  - `krtour.map.providers.knps` 모듈 신설은 Sprint 3 (ADR-034 7단계).
    SHP/CSV parsing·geometry 추출은 **knps-api 책임** (ADR-028 Amendment I /
    ADR-044). 본 lib는 record(좌표·WKT) Protocol로 소비만. PR#77/#78 구현 완료.
  - 후속 ADR: `access_restriction`/`fire_alert` notice source 결정
    (산림청/소방청/scrape). KNPS는 notice source 아님.
- [ ] T-019 — **TripMate 측 후속 작업 추적** (ADR-026 + ADR-029 후속, 본
      저장소 외)
  - TripMate `apps/web` Kakao Maps → maplibre-vworld 교체 PR (TripMate
    저장소). Next.js stack 유지, 마커 import만 `@krtour/map-marker-react`
    교체.
  - SPEC V8 v8_3 Kakao Maps 섹션에 "superseded by python-krtour-map ADR-026"
    표기 (SPEC 저장소)
  - 본 저장소는 ADR-026/029 reference만 책임. 작업 자체는 미트래킹.


## 보류 (v2 1차 범위 외)

- [ ] T-101 — **Materialized View 도입 검토** (feature + 7 detail flatten)
  - 상세 분석: `docs/performance.md §9.3` (도입 조건, 부작용, ROI).
  - 도입 조건: read >> write 비율 실측 (Sprint 5 이후 24h 로그) + Phase 2
    정합성 게이트(ADR-033)가 이미 작동 + 디스크 ×2 수용.
  - 도입 전제: `REFRESH MATERIALIZED VIEW CONCURRENTLY` 대상 MV마다 refresh identity
    `UNIQUE` 인덱스를 migration에 포함하고, 생성 직후 최초 1회는 비-concurrent
    `REFRESH MATERIALIZED VIEW schema.view`로 populate한 뒤 Dagster `swap`/
    `concurrently` 전략에 연결한다(T-RV-41).
  - 도입 절차: 하나의 hot path 시범 (예: `mv_features_place_with_detail`) →
    UNIQUE 인덱스 + 최초 populate → 1주 운영 + EXPLAIN diff → 확장 판단 → ADR 신설.
- [ ] T-102 — **pg_prewarm 부팅 후 warm-up**
  - 상세 분석: `docs/performance.md §9.5` (장점, 조건, 부작용, ROI).
  - 도입 조건: 명시적 P99 SLO + 재배포 빈도 높음 + `shared_buffers`가 핫
    데이터 fit (Odroid 기본 512MB는 일부만 가능).
  - 도입 절차: `CREATE EXTENSION pg_prewarm SCHEMA x_extension;` (ADR-008)
    + `autoprewarm = on` background 모드 + `/health` `prewarm_completed:bool`
    노출.
- [ ] T-103 — **streaming ETL (Kafka/Redpanda) 대응** — 본 라이브러리는
      consumer 미보유 (ADR-003)
  - 상세 분석: `docs/performance.md §9.4` (시나리오, 비용, 라이브러리 위치).
  - streaming consumer가 실제로 필요해지면 krtour-map 독립 프로그램 영역
    (`packages/krtour-map-dagster` 또는 별도 worker)이 소유한다. TripMate
    `apps/etl`이 krtour-map provider 적재 consumer를 소유하지 않는다(ADR-045/046).
  - 메인 라이브러리는 받은 message → DTO 변환 → `load_feature_bundles()` 호출의
    *함수*만 제공한다.
  - 본 PR#10에서 `pyproject.toml` `import-linter` forbidden 계약에
    `kafka`/`aiokafka`/`confluent_kafka`/`faust` 추가 → 본 라이브러리 의존
    차단.
  - 도입 조건: 특정 provider가 진짜 초 단위 latency를 요구하는 증거.
    추측만으로 도입 금지.


## Sprint 5 운영 진입 직전 (kraddr-geo 패턴 미러)

- [x] T-200 — **Batch DAG + 정합성 게이트** (kraddr-geo ADR-017 미러)
  - **ADR-045**: Dagster는 **krtour-map 소유**(TripMate 아님). asset 작성은
    krtour-map, TripMate는 OpenAPI queue 제어만. 상세 T-208(`adr045-standalone-plan.md`).
  - `ops.import_jobs`에 `load_batch_id UUID`, `parent_job_id UUID` 컬럼 추가
    (T-205d 완료, alembic `0012_import_jobs_batch_columns`)
  - `infra.batch_dag.run_batch_dag_consistency_gate` + Dagster
    `full_load_batch_consistency_gate` job 구현. 기존 provider/offline 적재가 만든
    실제 import job id를 `child_job_ids`로 받아 root batch 아래 연결하고, child가 모두
    `done`일 때만 `consistency_check`를 실행한다.
  - `severity_max=ERROR`이면 `mv_refresh`를 만들지 않고 root/gate job을 `failed`로
    닫는다. `OK/WARN`이면 `mv_refresh` job을 만들고, 현재 MV 카탈로그가 없으면
    `skipped:no_materialized_views` payload로 명시 기록한다.
  - `plan_only=true`는 DB write 없이 child job 존재 여부를 확인한다. 실제 phase stop/resume
    UI/API는 T-212 admin 전체점검에서 화면/운영 UX와 함께 보강한다.
- [x] T-201 — **`ops.feature_consistency_reports` 도입** (T-201a Phase 1 ✅ 2026-05-29: alembic 0003 + `infra/consistency.py` F1~F3 관측; T-201b Phase 2 ✅ 2026-06-06: F4~F8 + Dagster 게이트 + dry-run report CLI)
  - 컬럼: `report_id UUID PK, batch_id UUID, started_at, finished_at,
    severity_max TEXT, cases JSONB, summary JSONB`
  - 케이스 F1~F8 (`python-krtour-map-spec.docx` B.18 참고)
  - Dagster 일 1회 검사 + admin `/admin/integrity` 페이지 연동
  - T-201b 진행: F4 dedup backlog WARN은 Sprint 4b에서 추가됨. 2026-06-05 Codex는
    F6 opening_hours 모순 ERROR와 F5 provider last_success SLA WARN을
    `run_consistency_checks()`에 추가했고, 이어서 F7 cross-provider dedup score 회귀
    WARN을 큐 저장 baseline 대비 현재 `core.scoring` 재계산 기준으로 정렬했다. 2026-06-06
    Codex는 F8 file object orphan WARN을 `feature_files` metadata와 객체 저장소 snapshot
    비교로 추가했다. 이번 PR은 `krtour-map consistency-report` dry-run CLI와
    `docs/reports/t-201b-phase2-dry-run-report-2026-06-06.md` 산출물을 추가해 T-201b를
    닫는다.
- [x] T-202 — **pre-commit hook 정착**
  - `src/` 또는 `tests/` 수정 시 `docs/journal.md` 갱신 강제 (`BYPASS=1` 일회 우회)
  - `lint-imports` / `ruff format --check` / `mypy --strict`
  - `.pre-commit-config.yaml`, `scripts/check_journal_update.py`,
    `scripts/run-precommit-check.sh`로 local hook을 고정했다.
- [x] T-203 — **PR CI 워크플로**
  - `.github/workflows/ci.yml` — unit / integration / fixture_replay 분리 jobs
  - `.github/workflows/openapi.yml` — `--check` drift 검증 (디버그 UI 패키지)
  - `.github/workflows/lint.yml` — ruff/mypy/lint-imports
  - 기존 `pytest (Python X)` check 이름은 유지하고 unit job으로 좁혔다. PostGIS
    integration, fixture replay, OpenAPI drift, frontend build check는 모든 PR에서 생성된다.
- [x] T-204 — **GitHub branch protection 설정 가이드** (운영자용)
  - main: require PR + 1 approval + status checks + restrict force-push
  - ADR-021 §결정의 운영 정책을 별도 매뉴얼로
  - `docs/runbooks/branch-protection.md`로 always-on required check와 T-203 이후 승격할
    path-filtered check를 분리해 문서화했다.


## ADR-045 독립 프로그램화 (실행 계획: `docs/adr045-standalone-plan.md`)

> codex가 admin OpenAPI/스키마/큐 테이블/Docker 서비스 목록을 문서로 명세함
> (`openapi-admin-contract.md` 등). 아래는 그걸 **코드/배포로 구현**하는 세분 task.
> D-1~D-16 의사결정은 `docs/adr045-open-decisions.md`에 모두 확정돼 있다.
> 각 task는 1-PR.
>
> **완료 Phase(1~5, 6.5 등)는 [`tasks-done.md`](tasks-done.md)로 이동**(2026-06-09 분리).
> 아래엔 **열린 항목이 남은 Phase(6, 6.6~6.8, 7)**만 둔다 — 그래서 Phase 번호가 건너뛴다.


**Phase 6 — TripMate 연계/정리 (일부 TripMate repo)**
- [ ] T-210a — `docs/tripmate-rest-api.md` 확정(본 PR 1차) → 구현 시 OpenAPI 동기.
      Sprint 5 closure 전 `openapi.user.json`과 실제 TripMate 요구사항을 다시 대조한다.
      2026-06-08 Codex가 API endpoint review와 TripMate 소비자 문서를 종합해
      `docs/tripmate-rest-api.md`를 `/v1` 목표 계약 기준으로 재작성했다. 실제
      OpenAPI/라우터 동기화는 `T-214`에서 진행한다.
- [ ] T-210b — TripMate 문서 supersede(직접 import/공유 DB/owned Dagster, TripMate repo).
      대상 문서 목록과 치환 문구는 PR 본문에 남기고, krtour-map repo에는 링크/요약만 둔다.
- [ ] T-210c — TripMate `apps/etl`에 남은 레거시 Dagster 문서/스켈레톤은
      krtour-map-owned Dagster(T-208)로 이관하거나 삭제.
- [ ] T-210d — TripMate httpx OpenAPI client 신규(직접 import 제거, TripMate repo).
- [ ] T-210e — `openapi-typescript` client 생성 (D-4 timing).
      T-212e 최종 검증 뒤 API shape가 안정된 commit 기준으로 진행한다.


**Phase 6.6 — REST API v1 정리 후속 (2026-06-08, `T-214`)**

전 표면 계약 정본은 `docs/rest-api.md`, TripMate 소비 view는 `docs/tripmate-rest-api.md`.
기준 입력은 `docs/reports/api-endpoint-review-2026-06-08.md`와 TripMate
`docs/integrations/krtour-map-rest-api.md`. 사용자 결정으로 `/tripmate/feature-update-requests*`는
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
  (2026-06-09, 사용자 지시 — krtour-map은 TripMate 전용이 아니다.) `tripmate_router` 제거,
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


**Phase 6.7 — Feature 사용자 요청 CRUD/versioning (2026-06-08, `T-215`)**

- [x] **T-215a — place/event feature 추가·수정·삭제 admin API + versioning.**
  `/admin/features`에 `POST`, `/admin/features/{feature_id}`에 `PATCH`/`DELETE`,
  `/admin/features/change-requests*` 승인/거절 API를 추가했다.
  `KRTOUR_MAP_ADMIN_FEATURE_CHANGE_REVIEW_MODE=require_review|immediate` 설정에 따라
  요청을 `pending`으로 보관하거나 같은 transaction에서 바로 적용한다. provider 적재는
  `data_origin='provider', data_version=0`, 사용자 요청은
  `data_origin='user_request', data_version=1`로 구분하고
  `feature.feature_versions` snapshot을 남긴다. 사용자 요청 삭제는 soft delete이며
  provider 재적재나 snapshot 누락 정리로 되살리지 않는다.
- [x] **T-215b — admin UI feature change queue 화면.** (2026-06-09)
  `/admin/features/change-requests` 화면을 추가해 `GET /admin/features/change-requests`
  목록, add/update/delete 요청 form, approve/reject 동작을 연결했다. 목록 meta에
  `review_mode`를 추가해 `KRTOUR_MAP_ADMIN_FEATURE_CHANGE_REVIEW_MODE` 현재값을 빈 큐에서도
  표시한다. 기존 정본 mutation endpoint만 사용하며 새 중복 REST 표면은 만들지 않았다.
- [ ] **T-215c — frontend generated type/e2e workflow 보강.**
  OpenAPI 타입 기반 mutation hook, pending→approve→applied flow, immediate mode route
  mock, soft delete 표시/필터 e2e를 추가한다.


**Phase 6.8 — REST API 정합성 심화 (2026-06-09, `T-216`, ADR-048)**

T-214/T-215(#317)의 `/v1` 1차 정리 위에 ADR-048 delta를 얹는다. 정본 = `docs/rest-api.md`
(전 표면 단일). 각 항목 1-PR, OpenAPI drift + frontend gen:types 동반. **전환 정책(ADR-048,
무-호환)**: 호환성 미고려 — `/v1` clean cut(구 경로/alias 없음), 외부 read 포함 명명 전면
적용, dual-support/deprecation 창 없음. 소비자(TripMate)는 안정 spec commit을 일괄 추종.

- [ ] **T-216a — `/v1` clean cut(admin/ops/debug 포함).** 사용자 지시(admin도 versioning).
  `/admin`·`/ops`·`/debug`(+외부)를 `/v1`로 mount하고 **구 unprefixed 경로는 제거**(호환 alias
  없음). liveness `/health`·`/version`만 제외. `/debug/health`·`/debug/version` 제거.
  OpenAPI 두 profile + frontend API base + e2e 일괄 갱신. mount 1곳 전환(ADR-046).
- [ ] **T-216b — pagination 단일화.** page-size 파라미터를 `page_size`로 통일
  (`limit`/`run_limit`/`event_limit` 폐기), 2-티어 캡(기본 50/200, 지도 100/500),
  `/features` 평면 cursor화(`limit le=5000` 폐기), `in-bounds` `max_items` 5000→2000.
- [ ] **T-216c — envelope payload/meta 분리.** 라우터별 `*Meta` 중복 → 공유 `Meta`. `data`는
  payload만, 페이지네이션은 **`meta.page{page_size,next_cursor,total}`**(`total` opt-in
  `?include_total=true`). `data.next_cursor`/`data.total_count`/파생 `count` 폐기. in-bounds의
  `cluster_unit`은 `meta.cluster.cluster_unit`, batch id-keyed map은 `data.found`로 둔다.
  **envelope 불변식(ADR-048 #12)**: `meta`·`request_id` 모든 응답에 present,
  `meta.page.next_cursor` 항상 키 존재(소진 시 `null`, omit 금지) — 계약/라우터 테스트로 lock.
- [ ] **T-216d — parameter/error/좌표 정합성.** bbox 분리 float 통일(`search` CSV 제거),
  상태 필드 `state`→`status`, issue/violation noun을 `issue_*`로. 에러 RFC7807
  `application/problem+json`(`code`/`request_id`/`errors[]` top-level 확장, `{error:{}}` 제거).
  **좌표명 cross-repo 정렬 = `lon`/`lat`**(ADR-048 #10; TripMate DEC-07 하향 정렬). **`feature_id`
  값 불변식**(ADR-048 #11)을 외부 계약/테스트에 명시.
- [ ] **T-216e — 명명 통일(경로+응답 본문, 본질 기준).** `dedup-review`→`dedup-reviews`,
  `enrichment-review`→`enrichment-reviews`, `{review_key}`→`{review_id}`,
  `/admin/issues/{violation_key}`→`{issue_id}`. 응답 surrogate `*_key`→`*_id`. action
  sub-resource 규약(ADR-048 #8) 명시. **유지(자연/복합키)**: `cluster_key`(행정코드 자연키 —
  개명 안 함, #316 재리뷰 C), `target_key`, provider 어휘, `feature_id`.
- [ ] **T-216f — 코드/DB 명명 전파(surrogate만).** REST 개명을 물리 컬럼·ORM·repo까지
  end-to-end(테이블별 1-PR migration, codegraph impact 선행): `review_key`→`review_id`,
  `violation_key`→`issue_id`, ops 로그/내부 키 `*_key`→`*_id`, `state`→`status`(import_jobs/
  offline_uploads/feature_update_requests). **경계(개명 금지)**: `cluster_key`(행정코드 자연키),
  provider/source 어휘(ADR-044 — `dataset_key`/`source_record_key`/`source_entity_id`/
  `source_dataset_key`/`raw_*`)·복합 자연키(`target_key`+`external_system`)·canonical `feature_id`.
- [ ] **T-216g — 단일 정본 수렴 + 버전 거버넌스.** `docs/rest-api.md`를 전 표면 계약 단일
  정본으로 두고 `docs/tripmate-rest-api.md`를 소비 매핑 view로 축소(ADR-048 #9). `/vN`
  거버넌스(#13: pre-1.0 in-place breaking, v1.0.0 GA에서 `/v1` 동결→이후 `/v2`+N-1, OpenAPI
  major별 export)를 문서·export 스크립트에 반영.


**Phase 7 — ADR-045 전체점검/튜닝 (ADR-045 잔여 task 완료 후 시작)**

상세 실행 계획은 `docs/reports/adr-045-overall-audit-plan-2026-06-04.md`를 정본으로
한다. 각 항목은 1-PR 단위로 진행하고, 성능 튜닝은 PR 본문과 문서에 튜닝 전/후
측정값, 변경한 인덱스/쿼리/프론트 렌더링 포인트, 남은 병목을 기록한다.

- [x] T-212a — 전체점검 inventory + Playwright/e2e gap matrix.
      `docs/reports/t-212a-inventory-gap-matrix-2026-06-06.md`에서 admin/user OpenAPI
      43/13 path, frontend route 10개, Dagster job/sensor/schedule/resource, DB/API/
      frontend/e2e gap을 최신 main 기준으로 재분류했다. 후속은 T-209e-c, T-212b~e로
      분리한다.
- [x] T-212b — admin UI 완결성 보강.
      table 기반 CRUD, 지도뷰 검토, 이슈 승인/거절, API debug/test, Dagster monitoring
      summary/scraping, 시스템/이슈 로그 확인 화면을 운영자 workflow 기준으로 보완한다.
      상세 분해:
      - `T-212b-1`: `/admin/features` table/detail/map review + weather panel.
      - `T-212b-2`: `/admin/issues` 처리 workflow + `/ops/logs` system/API call log 화면.
      - `T-212b-3`: Dagster schedule/sensor tick/failure 드릴다운 + offline upload/POI
        cache target 주요 mutation e2e.
      - [x] 2026-06-07 Codex: `/admin/features` 운영 table + 상세/weather panel +
        단건 deactivate, `/admin/issues` 목록/상세 + resolve/ignore/reopen/retry/
        apply/manual override, `/ops/logs` system/API-call log 조회 UI, nav/README/e2e
        smoke 추가. `npm run type-check`, `npm run lint`, env 명시 `npm run build`,
        React Doctor 실행 완료.
      - [x] Windows 호스트 Playwright 확인(2026-06-07 Codex):
        `E2E_BASE_URL=http://127.0.0.1:9014 npm -w packages/krtour-map-admin/frontend run e2e -- e2e/admin-ops.spec.ts --reporter=line`
        9 passed.
      - [x] Dagster summary에 schedule/sensor recent tick을 포함하고,
        `/ops/dagster/runs/{run_id}` event/failure detail API와 `/admin/dagster`
        선택 panel을 연결(2026-06-07 Codex).
      - [x] offline upload/POI cache target 주요 mutation e2e(2026-06-08 Codex).
        Playwright route mock으로 `/admin/poi-cache-targets` upsert → target 선택 →
        `/features/nearby/by-target` 조회 → delete, `/admin/offline-uploads`
        CSV multipart upload → preview → validation → Dagster load alert까지 브라우저
        상호작용과 mutation 요청을 고정했다.
- [x] T-212c — API endpoint/error/log contract 정리 (2026-06-07 완료).
      admin/user endpoint shape, error envelope, debug/test endpoint, import job event,
      system log API, route mount 정책을 점검하고 필요한 backend를 구현한다.
      envelope 통일 + health-deep + system/api-call log + error envelope 중앙화 모두 완료.
      - [x] **envelope 전면 통일**(T-DA-15/16/18, #250~#255) — 모든 성공 응답 `{data, meta}`.
      - [x] **`/ops/health-deep`**(T-212c-API-03, 2026-06-07) — DB/PostGIS readiness 점검
        (`{data:{status, checks[]}, meta}`, degraded 시 503). liveness용 public `/health`는
        DB-free 유지. ops 단위 2 + PostGIS 통합 2 테스트.
      - [x] **system/API call log 조회 표면**(T-212c-API-04, 2026-06-07) — 마이그레이션
        `0018_ops_logs`(`ops.system_log`/`ops.api_call_log`) + `infra/log_repo.py`(record +
        keyset cursor list) + `GET /ops/system-logs`·`GET /ops/api-call-logs`(envelope). api-call
        적재는 opt-in middleware(`KRTOUR_MAP_ADMIN_API_CALL_LOG_ENABLED`, 기본 off, best-effort).
        log_repo 단위 + ops_logs 라우터 단위 + 미들웨어 단위 + PostGIS 통합 테스트.
      - [x] error envelope 일관성 — `app.py` 중앙 exception handler(`_error_response` +
        `_status_error_code`)가 모든 `HTTPException`/검증오류를 공통 `{error:{code,message,
        details,request_id}}` + `X-Request-ID`로 통일(기구현). 라우터는 detail만 던지면 됨.
- [x] T-212d — DB/API/frontend 성능 튜닝 (2026-06-08 완료).
      PostGIS/pg_trgm/ops table EXPLAIN, keyset cursor, index 추가/수정, frontend
      table/map 렌더링 병목을 측정하고 개선 결과를 문서화한다.
      1차 PR은 실데이터 없이 seeded PostGIS/testcontainers로 `/features/search`,
      `/features/in-bounds`, `/features/nearby`, `/admin/features`, `/ops/import-jobs`,
      dedup refresh, consistency F6/F8의 EXPLAIN baseline을 모은다. 실 운영 규모 측정은
      T-212e 리포트에서 보강한다.
      - 로컬 live DB 확인 결과 `features/source_records/source_links/import_jobs` 각 1건,
        `consistency_reports`/`dedup_review_queue` 0건, alembic `0016` 상태라 성능
        baseline으로 부적합했다.
      - `0020_t212d_perf_keyset_indexes`로 hot read/keyset 인덱스를 보강하고,
        q 검색은 trigram 후보 CTE, bbox는 공간 후보 CTE, review/consistency 큐는
        UUID tie-breaker keyset으로 정렬축을 고정했다.
      - 통합 테스트 `tests/integration/test_t212d_perf_explain.py`가 3,200 feature +
        provider/source/ops/review live-like seed로 `/features/search`, `/features/in-bounds`,
        `/features/nearby`, `/admin/features`, `/ops/import-jobs`, consistency F4/F6/F7/F8,
        dedup/enrichment review list EXPLAIN 인덱스 사용을 검증한다.
      - 사후 리뷰 보강으로 `/features/in-bounds` `LIMIT` subset 안정성, seqscan hint 없는
        대표 planner 가드, admin sort=name EXPLAIN, review cursor 전체 순회 완전성을 추가했다.
      - 상세 리포트: `docs/reports/t-212d-perf-baseline-2026-06-08.md`.
- [ ] T-212e — 실데이터 full reload + offline upload 실데이터 검증 + 최종 리포트.
      DB를 비운 뒤 처음부터 다시 로드하고, provider 실데이터와 offline upload
      CSV/TSV/JSONL 실데이터 적재, kraddr-geo bjd 보강, Playwright e2e, API smoke,
      Dagster 상태를 모두 확인한다.
      provider별 성공/실패/skip, import job/Dagster run id, consistency report id,
      backup/restore smoke 결과를 `docs/reports/t-212e-live-full-reload-final-*.md`에
      남긴다.


## 우선순위 가이드

- **즉시 (검토 + merge)**: 본 PR#48 (worktree rename + tasks.md sweep) +
  upstream knps-api PR#1 (maki icon 정정)
- **다음 (Sprint 2 잔여 → Sprint 3 진입)**:
  - 디버그 UI ETL preview live 매트릭스 확장 — datagokr 1 + opinet 2 +
    krex 4 + kma_weather_alerts 1 = 8 dataset live loader 등록 (현재 KMA 3만)
  - `maplibre-vworld-js v0.1.0` 정합 — frontend `package.json` 의존 핀 정정
    (`^1.0.0`→git URL `#v0.1.0`, zod `^3`→`^4.4.3`) + docs 버전 갱신 (T-019 관련)
  - KMA `mid_forecast_to_weather_values` (중기예보 텍스트 + AM/PM split)
  - `/features/*` 라우터 + `infra/feature_repo.py` raw SQL (✅ feature_repo 완료
    2026-05-29 — load_bundles/get_feature_row; 라우터+frontend 지도는 후속) 
  - Sprint 2 §2.1 끝물 visitkorea TourAPI enrichment
    (`festival_to_enrichment_links`)
- **Sprint 진행 순서** (ADR-034):
  - Sprint 2 = ① 축제 ✅ → ② 날씨 ✅(mid 잔여) → ③ 유가 ✅ → ④ 휴게소 ✅
    + 디버그 UI 라우터 ✅ (`docs/sprints/SPRINT-2.md`)
  - Sprint 3 = ⑤ 국립공원/트래킹 → ⑥ 국가유산 + 정합성 Phase 1 (F1~F3)
    + ADR-036 maplibre-vworld-js v0.1.0 분리 (`SPRINT-3.md`)
  - Sprint 4 = ⑦ MOIS bulk 4단계 + dedup queue 운영 (`SPRINT-4.md`)
  - Sprint 5 = ⑧ 휴양림/수목원 → ⑨ 박물관/미술관 + Phase 2 F4~F8 + Dagster
    게이트 + 운영 진입 (`SPRINT-5.md`)
- **백그라운드**: T-019 (TripMate `apps/web` 측 Kakao → maplibre-vworld
  교체 모니터링) — upstream `digitie/maplibre-vworld-js` **v0.1.0 릴리스됨**
  (npm 미게시, git URL+tag 핀).
- **장기**: 운영 진입 후 v2.1 검토 (T-101 MV / T-102 pg_prewarm / T-103
  streaming / ADR-045+ 신규 provider)


## ADR 번호 가이드 (현재)

- **accepted (text on main)**: ADR-001 ~ ADR-046 (전부). PR#16에서 027~034,
  PR#33에서 035~043 일괄 accepted 전환. 029→043 supersede. ADR-044 (로컬 우선
  조회 + 정합성 책임) PR#54. **ADR-045** (krtour-map Docker 독립 프로그램 + 독립
  DB/Dagster + TripMate OpenAPI 연동 — ADR-003 함수 직접 호출 모델 supersede,
  2026-06-01). **ADR-046** (ADR-045 이행 시 구 모델 호환 shim 금지, 2026-06-02).
- **001~048 accepted**. **다음 후보 번호 = ADR-049**:
  - **ADR-049+** — 신규 provider 추가 절차 표준 (체크리스트)
  - 후속 `@krtour/map-marker-react` npm 게시 자동화 ADR (현재 ADR-043 보류)
  - (필요 시) ADR — Sprint 3 SHP/GeoJSON parsing 위치 결정 (`krtour.map.
    providers.knps` vs upstream `[geo]` extra)
  - (필요 시) ADR — MV 도입 (T-101 Sprint 5 시범 결과 후)
  - (필요 시) ADR — pg_prewarm 운영 정책 (T-102)
