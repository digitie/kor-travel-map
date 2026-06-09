# tasks-done.md — 완료/아카이브 task 이력

> 완료(`[x]`)·폐기·머지 history 아카이브. **진행 중/예정 task는 [`docs/tasks.md`](tasks.md)**.
> (2026-06-09 분리 — tasks.md 길이 축소. 분리 기준: 열린 `[ ]` 항목이 없는 섹션·Phase는 여기로.)

## 문서 정합성 백로그 (T-DA, 2026-06-06)

문서 전수 정합성 감사 결과. 전체 지적·근거·파일위치·의사결정은
**`docs/reports/docs-consistency-audit-2026-06-06.md`** 가 정본. task id는 `T-DA-NN`,
사용자 결정은 `DA-D-NN`. 사용자 결정(DA-D-01 포인터 대체 / DA-D-02 한 PR 반영)에
따라 T-DA-01~10은 **본 배치에서 반영 완료**.

- ~~**T-DA-01** CLAUDE.md §2 "현 단계" 전면 stale(PR#149/Sprint4 완료)~~ ✅ DA-D-01(A)
  포인터 대체.
- ~~**T-DA-02** CLAUDE.md geocoding 로컬 포트 `8888`~~ ✅ → `9001`(`.env.example` 정합).
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
  apply_kraddr_geo_address/manual_override)~~ ✅ **구현 완료(2026-06-07)**. ADR-046
  주소/좌표 이슈 운영자 수동 처리 API. `routers/admin_issues.py`(목록 keyset cursor +
  단건 detail + PATCH 7 action) + 신규 `infra/feature_address_repo.py`(feature.features
  UPDATE + `ops.feature_overrides` upsert) + kraddr-geo `geocoding` 정/역지오코딩.
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
- ~~**T-RV-01/02** Dagster 운영 형상 (D-2): metadata를 별도 `krtour_map_dagster`
  Postgres DB로 (현재 SQLite 폴백) + `dagster dev`→webserver/daemon 분리.~~
  ✅ `dagster-db-init`, `dagster` webserver, `dagster-daemon`,
  `docker/dagster.yaml` Postgres storage, `dagster-postgres` dependency와 compose
  회귀 테스트를 추가했다.
- ~~**T-RV-03** Dagster `krtour_map_client` resource engine dispose 누수.~~
  ✅ generator resource로 전환해 run/tick 종료 시 `AsyncEngine.dispose()`를 호출하고,
  running event loop 안에서도 teardown이 동작하는 회귀 테스트를 추가했다.
- **T-RV-04** Dagster provider 서비스키 resource 미구현(D-15, feature-load asset
  provider fetcher 기본 wiring 미완료).
  - ✅ **T-RV-04a**: provider record key별 guard resource와
    `KRTOUR_MAP_*` credential env mapping을 등록했다. 기본 `defs`는 더 이상 generic
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
        `mois_source_db_path`, env `KRTOUR_MAP_MOIS_SOURCE_DB_PATH`)에 sqlite Session 열고
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
  Docker RustFS bucket init을 구현했다. API `9003`, console `9004`, bucket
  `krtour-map`/`krtour-uploads` 기준으로 실제 put/get smoke를 확인했다.
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
- **T-208d** (2026-06-03): `packages/krtour-map-dagster`에 Feature 적재 asset 9개의
  KST schedule과 asset job을 등록했다. 모든 schedule은 `Asia/Seoul` 기준이고,
  외부 API 호출 분산을 위해 분/요일을 나눴으며 기본 status는 `STOPPED`다.
- **T-207g** (2026-06-03): OpenAPI export를 admin 전체
  `packages/krtour-map-admin/openapi.json`과 TripMate/user subset
  `packages/krtour-map-admin/openapi.user.json`으로 이원화했다. CI drift gate는
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
  `AsyncKrtourMapClient.execute_feature_update_request()`로 실행하고, 실패 시
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
  RustFS dev compose 예시 host port `9003`/`9004` 정렬.
- **PR#162** (merged 2026-06-03): `AsyncKrtourMapClient` feature update request
  메서드 4종 + top-level client export + RustFS 포트 9003/9004 문서 정렬.
- **T-206a-geo 확인** (2026-06-03): `python-kraddr-geo` main의
  `/v2/regions/within-radius` 구현과 optional 실제 PostGIS 테스트를 재검증.
  WSL targeted test `15 passed, 1 skipped`, 로컬 9001 server smoke는 `sigungu`
  `11650`(서초구) contains 응답 확인.
- **PR#161** (merged 2026-06-03): `infra.feature_update_repo` request/import job
  lifecycle repository + kraddr-geo REST API 로컬 포트 9001 문서/설정 정렬.
- **PR#160** (merged 2026-06-03): `infra.scope_repo` scope resolver.
- **PR#159** (merged 2026-06-03): `ops.feature_update_requests` Alembic 0008 +
  ORM 매핑 + DDL 계약 통합 테스트.
- **PR#158** (merged 2026-06-02): Docker API 컨테이너의 Dagster URL을
  `KRTOUR_MAP_DOCKER_ADMIN_DAGSTER_URL` 기본값(`http://dagster:9013`)로 분리.
- **PR#157** (merged 2026-06-02): admin UI `/admin/dagster` + backend
  `GET /ops/dagster/summary` + Dagster webserver embed.
- **PR#156** (merged 2026-06-02): Docker 이미지/compose, API `9011`, admin UI
  `9012`, Dagster `9013` 고정 포트, `.env` key mapping, 기동/포트 종료 스크립트.
- **PR#155** (merged 2026-06-02): krtour-map-owned Dagster Feature ETL 1차.
  `packages/krtour-map-dagster/` code location과 9개 Feature asset runner, PostGIS
  적재 통합 테스트.
- **PR#114** (merged 2026-05-31): geocoding live 기본 포트 정합(현재 9001),
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
- **PR#48** (merged 2026-05-28): agent worktree 접두사 `geo-*` → `krtour-map-*`
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
- [~] T-205b — ~~`feature.sigungu_boundaries`~~ **취소**(D-11: 경계는 kraddr-geo
  소유, krtour-map은 REST 호출). → T-206a-geo로 대체.
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
  `sigungu_by_radius`는 kraddr-geo `/v2/regions/within-radius` 호출(D-11).
  DB repo는 kraddr-geo client를 직접 import하지 않고 async resolver를 주입받는다.
  `cache_target_keys` resolver는 T-206d에서 `ops.poi_cache_targets` 기반으로 완료.
- [x] T-206a-geo — (형제 repo `python-kraddr-geo`) `POST
  /v2/regions/within-radius` 엔드포인트와 optional PostGIS 실데이터 테스트가
  `python-kraddr-geo` main(PR #114/#115 계열)에 반영됨을 재검증했다. krtour-map은
  REST v2 계약/로컬 포트 `9001`/resolver 주입 경계를 유지한다.
- [x] T-206b — `infra/feature_update_repo.py` (enqueue/claim/start/finish/get/list/cancel,
  advisory lock + SKIP LOCKED, keyset cursor D-10).
- [x] T-206c — `AsyncKrtourMapClient` feature-update 메서드 4종.
- [x] T-206d — request 실행 본체(scope→provider/dataset 역추적 refresh, D-6/D-8).
  runner 주입형 `infra.feature_update_executor`, `cache_target_keys` resolver, target
  link 재계산, provider refresh policy skip, `AsyncKrtourMapClient` 실행 메서드.


**Phase 3 — FastAPI 라우터 (`krtour-map-admin` 패키지)**
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


**Phase 4 — Dagster (krtour-map 독립 구현)**
- [x] T-208a — `packages/krtour-map-dagster/` 골격 + definitions. 메인
      `krtour.map`은 Dagster를 import하지 않고 별도 `krtour.map_dagster`
      package가 code location을 제공.
- [~] T-208b — resources(DB/client/provider 9 + kraddr-geo/rustfs, D-15). 1차:
      `krtour_map_client`, `reverse_geocoder`, `fetched_at`, provider record iterable
      resource 계약 구현. `offline_upload_store` resource key는 T-208g에서 추가한다.
      RustFS/S3 호환 `offline_upload_store` 기본 resource와 Docker RustFS bucket init은
      후속 T-208b 작업으로 구현했다. 실제 provider client resource wiring은 남는다.
- [x] T-208c — provider load asset 9종(이미 구현·검증된 Feature provider 변환 함수
      연결) + 주소/좌표 검증 + `AsyncKrtourMapClient.load_feature_bundles` PostGIS
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
      `krtour.map.offline_upload` JSON/JSONL `FeatureBundle` parser/load
      orchestration, `AsyncKrtourMapClient.run_offline_upload_load_job`,
      Dagster `offline_upload_load` job을 추가했다.


**Phase 4.2 — Offline upload admin UI 선행**
- [x] T-208h — `/admin/offline-uploads*` API + 기본 upload 화면.
      RustFS/S3 store에 JSON/JSONL `FeatureBundle` 파일을 저장하고,
      `ops.offline_uploads` row 생성/list/detail/load 실행까지 admin UI에서 연결한다.
- [x] T-208i — CSV/TSV validation + column mapping wizard.
      CSV/TSV 업로드 허용, preview/header/sample endpoint, validation import job,
      column mapping, kraddr-geo address geocode/reverse 보강, load 전 validation gate,
      admin UI validation panel, Dagster load parser 연계를 추가했다. `bjd_code`가 없는
      provider/offline row는 resolver가 있으면 kraddr-geo REST v2 geocode/reverse 결과로
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
  API `9011`, frontend `9012`, Dagster `9013`, Postgres host `15433`.
- [x] T-209b — 기동 순서 1차(postgres health → API `alembic upgrade head` →
  api/frontend/dagster). 2026-06-04 Codex 후속으로 `scripts/run-admin-stack.sh`가
  시작 전 `alembic upgrade head`를 실행하고, `setsid` detached 실행 + URL 기준
  readiness로 API/frontend/Dagster를 유지하도록 보정했다. Dagster metadata DB 분리/init와
  daemon/schedule 운영은 `T-209b-a`에서 완료했다.
- [x] **T-209b-a — Dagster schedule/run/event storage PostgreSQL 강제 전환.**
  Docker standalone과 로컬 admin-stack 모두 `docker/dagster.yaml`의 unified
  `storage.postgres` instance config를 사용한다. Dagster 공식 instance config 기준에서
  이 key는 run/event/schedule-sensor tick metadata를 함께 PostgreSQL에 저장하므로,
  `KRTOUR_MAP_DAGSTER_PG_URL`이 단일 source다.
  - Docker 이미지는 기존처럼 `docker/dagster.yaml`을 포함하고, `dagster` webserver와
    `dagster-daemon`이 같은 `DAGSTER_HOME`/`KRTOUR_MAP_DAGSTER_PG_URL`을 공유한다.
  - `scripts/run-admin-stack.sh`는 시작 전 `krtour_map_dagster` DB 존재를 확인/생성하고,
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
  `krtour_map` app DB + `krtour_map_dagster` Dagster metadata DB + RustFS volume cold
  backup 산출물과 검증 절차를 고정한다. `T-209e-b`에서 `npm run docker:restore`와
  `scripts/docker-restore.sh`를 추가해 backup 산출물을 staging DB/volume
  (`krtour_map_restore`, `krtour_map_dagster_restore`, `krtour-map-rustfs-restore`)으로
  복원하는 비파괴 cold restore 자동화를 고정한다. `T-209e-c`에서
  `/admin/backups`, `/admin/restore/{backup_id}` router와 `/admin/backups` UI를 추가해
  artifact 목록과 backup/restore/swap command plan을 노출한다. 최종 잔여로
  `scripts/with-pg-advisory-lock.py` 기반 `maintenance:backup-restore` mutex,
  `scripts/docker-restore-verify.sh` staging smoke/count 검증,
  `scripts/docker-restore-swap.sh` restore hot-swap env 전환을 추가했다.


**Phase 6.5 — TripMate 요구사항 대조 후속 (2026-06-06, `T-213`)**

정본 리포트는 `docs/reports/tripmate-requirements-reconcile-2026-06-06.md`. TripMate
문서의 기준 krtour-map commit이 `b775c74`라 현재 `origin/main`과 차이가 크므로, 단순
호환 shim이나 최소 수정이 아니라 ADR-045 OpenAPI 독립 프로그램 모델 기준으로 완성도,
안정성, 확장성, 성능을 우선한다.

- [x] **T-213a — TripMate 요구사항 대조 리포트 작성.**
  TripMate `docs/krtour-map-requirements.md` K-1~K-14를 현재 user OpenAPI 7개 path,
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
- [x] **T-213d — `AsyncKrtourMapClient` read parity 보강.** (claude, 2026-06-06)
  `get_features`(→`get_feature_rows_by_ids`), `search_features`(→repo
  `search_features`), `features_nearby_poi_cache_target`(→repo 동명 함수) 3개 read
  메서드를 `AsyncKrtourMapClient`에 추가했다. 기존 repo 함수에 위임만 하므로 새 SQL/
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
  types 재생성. drift gate는 `@krtour/map-marker-react` `maki.ts`가 **name→glyph**
  구조라 ADR-029 원안의 category↔TS 1:1이 아니라 **완화형**(TS maki name kebab 유효성
  + 핵심 provider maki 글리프 커버 + Python 카탈로그 self-consistency)으로 적용
  (`tests/unit/test_category_catalog_contract.py`). 부수: `category/__init__.py`
  docstring tier 개수(34/73/29)·`category.md` icon 개수(57) 코드 기준 reconcile.
  검증: 격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/lint-imports +
  admin router 3·main contract 3·PostGIS counts 1건 green.
- [x] **T-213g — provider export + sync state/last-sync 표면.** (claude, 2026-06-06)
  `krtour.map.providers`에 knps/krheritage 변환 함수·dataset/provider 상수 re-export.
  `AsyncKrtourMapClient`에 `get_sync_state`/`list_sync_states`(read) +
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
  `GET /version`(`{data:{version, krtour_map_version, openapi_version, commit},meta}`,
  commit=env `KRTOUR_MAP_GIT_COMMIT`)를 `routers/public_status.py`로 추가. liveness는
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
  - `packages/krtour-map-admin/` pyproject + README skeleton
- [x] T-002 ~ T-011 — v1 docs를 v2 기준으로 일괄 이전 (완료: 2026-05-24, PR#2)
  - 14개 신규 docs (weather/files-rustfs/opening-hours/kraddr-base-types/
    address-geocoding/dagster-boundary/postgres-schema/debug-fixture-workflow/
    feature-db-initialization/tripmate-integration + provider ETL 10건)
- [x] T-001c — ADR-021/022/023 + PR-only workflow + `krtour.map` namespace +
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
  - `packages/krtour-map-admin/frontend/` skeleton
  - `docs/tripmate-integration.md` §14.5 사용자 UI 지도 stack
  - `docs/external-apis.md` Kakao Maps SDK 미사용 처리
  - `docs/forest-feature-etl.md` §11.6 ADR-026 → ADR-027 후보 재번호
- [x] T-017b — ADR-025 2차 사용자 보강 (frontend 빌드 도구 Vite → **Next.js**
      정정) (완료: 2026-05-25, PR#11 merged)
  - `docs/decisions.md` ADR-025 §사용자 보강 2차 추가
  - `docs/debug-ui-package.md` §14 Next.js 전환 + 운영 옵션 3가지
  - `packages/krtour-map-admin/frontend/` skeleton 일괄 Next.js 전환
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
- [x] T-017c — ADR-029 (proposed) + `@krtour/map-marker-react` skeleton
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
  - `packages/krtour-map-admin/scripts/export_openapi.py` skeleton
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
| #17 | `feat/sprint1-pr17-scaffolding` | 2026-05-25 | `src/krtour/map/` PEP 420 scaffolding + `settings.py` + smoke |
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
| #48 | `docs/pr48-worktree-rename-tasks-sweep` | 2026-05-28 | worktree `geo-*`→`krtour-map-*` rename + tasks.md 최신화 |
| #49 | `feat/pr49-maplibre-vworld-v010` | 2026-05-28 | maplibre-vworld v0.1.0 의존 핀 정합 (git URL+tag, zod ^4.4.3, ADR-036 amendment) |
| #50 | `docs/pr50-sprint-task-resume-consolidation` | 2026-05-28 | Sprint/task/resume 일관성 재정비 |
| #51~#95 | (Sprint 2 잔여 + Sprint 3) | 2026-05-28~30 | visitkorea enrichment / KMA mid_forecast / ETL live 11 / KNPS·krheritage provider / geocoding REST / `feature_repo` 적재 / consistency F1~F3 / `AsyncKrtourMapClient` / `/features` debug UI + frontend / dedup queue |
| #96~#114 | (Sprint 4 prep) | 2026-05-30~31 | `/features` UX / `map-marker-react` / geocoding v2 회귀 / NTFS+Windows Git 정책 / Next.js 16 + `maplibre-vworld-js#v0.1.2` |
| #115~#132 | (Sprint 4a) | 2026-05-31~06-01 | MOIS Step A bulk + Step B incremental(cursor) / advisory lock + `ops.import_jobs` / CLI mutex + `status` / `krtour-map import mois`(NDJSON) / dedup self-sibling / geocoder live 재검증 |
| #133 | `feat/cli-dedup-merge` | 2026-06-01 | `krtour-map dedup-merge` + merge primitive + `ops.feature_merge_history`(alembic 0007) + `core.scoring.select_master` (ADR-016) |
| #134 | `feat/step-b-incremental` | 2026-06-01 | MOIS Step B 증분 적재 + `infra/sync_state_repo`(cursor) |
| #135 | `chore/dedup-fp-measurement` | 2026-06-01 | dedup FP 측정 리포트 + 회귀 가드 (가중치 변경 없음) |
| #136 | `feat/step-c-closed` | 2026-06-01 | MOIS Step C 폐업/취소 → feature inactive |
| #137 | `feat/step-d-detail-router` | 2026-06-01 | MOIS Step D on-demand 상세 (debug-ui `/debug/mois-license/{id}`, 캐시만) |
| #138 | `feat/dedup-fp-ops-stats` | 2026-06-01 | dedup 운영 FP 통계 (`status_repo.dedup_fp_stats` + `krtour-map status`) |
| #139 | `feat/consistency-f4` | 2026-06-01 | ADR-033 F4 — dedup 백로그 baseline WARN |
| #140 | `feat/place-phone-enrichment` | 2026-06-01 | Place 전화번호 보강 (`krtour.map.enrichment`) |
| #141 | `chore/coverage-bar-80` | 2026-06-01 | coverage gate 75→80 (실측 94.12%) — Sprint 4 종료 |
| #142 | `docs/agent-runbooks` | 2026-06-01 | 에이전트 공용 runbook (`docs/runbooks/` agent-workflow + failure-patterns) |
| (post) | (main) | 2026-06-01 | admin OpenAPI cache 문서 (ADR-045 후속) |
| knps-api #1 | `docs/knps-feature-maki-icons` | **open** | maki icon 정정 (shelter / barrier) |
