# tasks.md — 백로그

이 문서는 작업 백로그다. 우선순위 순. 각 작업은 `T-NNN` 번호로 식별한다.

## 진행 중

**진행 중**: Sprint 5 운영 진입 마무리. main은 ADR-045 독립 프로그램화 핵심
구현(T-205~T-209), 정합성 Phase 2(T-201b), 운영 게이트(T-202~T-204), TripMate
요구사항 후속(T-213a~h), T-RV-04b provider live wiring, T-212a inventory,
T-212b admin UI 완결성, T-212c API/error/log contract, T-212d seeded PostGIS
성능 baseline, T-209e backup/restore 최종 safety automation까지 merged 또는 PR
진행 범위로 닫았다.

Sprint 5 종료까지 남은 작업은
`docs/reports/sprint5-final-task-breakdown-2026-06-07.md`를 정본으로 상세화했다.
권장 순서는 **T-212e 실데이터 full reload → T-210 TripMate 연계 정리 → Sprint 5
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
- [ ] **T-RV-53 휴양림/수목원(krforest) feature-load**(points 1·2·3·4): provider `python-krforest-api`
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
- [ ] **T-RV-54 박물관/미술관(standard_data) feature-load**(points 1·3·4): provider `datagokr`
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
  목록/결정/merge backend를 연결. 수동 feature 생성과 영구 삭제는 audit log 설계 후
  후속으로 남긴다.
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
  연결했다. `POST /admin/features` 수동 생성과 `DELETE /admin/features/{id}` 영구 삭제는
  `ops.admin_audit_log` 설계 후 후속 작업으로 남긴다.
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

**Phase 6 — TripMate 연계/정리 (일부 TripMate repo)**
- [ ] T-210a — `docs/tripmate-rest-api.md` 확정(본 PR 1차) → 구현 시 OpenAPI 동기.
      Sprint 5 closure 전 `openapi.user.json`과 실제 TripMate 요구사항을 다시 대조한다.
- [ ] T-210b — TripMate 문서 supersede(직접 import/공유 DB/owned Dagster, TripMate repo).
      대상 문서 목록과 치환 문구는 PR 본문에 남기고, krtour-map repo에는 링크/요약만 둔다.
- [ ] T-210c — TripMate `apps/etl`에 남은 레거시 Dagster 문서/스켈레톤은
      krtour-map-owned Dagster(T-208)로 이관하거나 삭제.
- [ ] T-210d — TripMate httpx OpenAPI client 신규(직접 import 제거, TripMate repo).
- [ ] T-210e — `openapi-typescript` client 생성 (D-4 timing).
      T-212e 최종 검증 뒤 API shape가 안정된 commit 기준으로 진행한다.

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
      - 상세 리포트: `docs/reports/t-212d-perf-baseline-2026-06-08.md`.
- [ ] T-212e — 실데이터 full reload + offline upload 실데이터 검증 + 최종 리포트.
      DB를 비운 뒤 처음부터 다시 로드하고, provider 실데이터와 offline upload
      CSV/TSV/JSONL 실데이터 적재, kraddr-geo bjd 보강, Playwright e2e, API smoke,
      Dagster 상태를 모두 확인한다.
      provider별 성공/실패/skip, import job/Dagster run id, consistency report id,
      backup/restore smoke 결과를 `docs/reports/t-212e-live-full-reload-final-*.md`에
      남긴다.

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
- **001~047 accepted**. **다음 후보 번호 = ADR-048**:
  - **ADR-048+** — 신규 provider 추가 절차 표준 (체크리스트)
  - 후속 `@krtour/map-marker-react` npm 게시 자동화 ADR (현재 ADR-043 보류)
  - (필요 시) ADR — Sprint 3 SHP/GeoJSON parsing 위치 결정 (`krtour.map.
    providers.knps` vs upstream `[geo]` extra)
  - (필요 시) ADR — MV 도입 (T-101 Sprint 5 시범 결과 후)
  - (필요 시) ADR — pg_prewarm 운영 정책 (T-102)

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
