# journal 아카이브 — 2026-07-01 ~ 2026-07-12

> `docs/journal.md`에서 분리한 과거 기록(역시간순). 현행 정본은
> [`docs/journal.md`](../journal.md)이며, 전체 아카이브 목록도 거기에 있다.
> 이 파일은 읽기 전용 이력이다 — 새 엔트리는 `docs/journal.md` 상단에 추가한다.

## 2026-07-12 (codex) — admin 큐레이션/Feature/이슈 화면 밀도 정리

- **큐레이션 UI**: 큐레이션 상세·관리의 위치 지도 높이를 키우고 동일 좌표 정규화 경로로 마커를 표시하도록
  정리했다. 위치/장소 대조/큐레이션 상세의 반복 설명 문구와 선택 후보 요약의 중복 메타를 제거하고,
  상세 화면 상단 제목은 고정 "큐레이션 상세" 대신 항목 이름과 상태를 표시하도록 바꿨다.
- **큐레이션 흐름**: 상태별 긴 설명은 본문에서 제거해 상태 칩 tooltip으로 옮기고, "이 화면의 동작 방식"은
  도움말 아이콘 다이얼로그로 분리했다.
- **관리 화면 밀도**: admin Feature 목록과 이슈 목록 필터를 한 줄 가로 스크롤 필터 바로 압축하고,
  Feature 목록의 반복 설명 문구를 제거했다.
- **검증(로컬)**: admin frontend `lint` 0 error(기존 warning 4), `type-check` 통과,
  `NEXT_PUBLIC_*` 로컬값 주입 production build 통과.

## 2026-07-12 (codex) — curated source rule `detail_selector` 응답 500 수정

- **원인**: 운영 `/v1/admin/curated-source-rules?limit=200` 500은
  `CuratedSourceRule` dataclass에 0042의 `detail_selector`가 추가됐지만,
  API `CuratedSourceRuleView`가 해당 필드를 허용하지 않아 Pydantic `extra_forbidden`으로
  실패한 것이었다.
- **수정**: rule view/create/patch 계약에 `detail_selector`를 추가하고, rule view 변환은
  attribute 기반 검증으로 변경했다. `update_curated_source_rule()`도 `detail_selector` JSONB
  patch/clear를 허용하도록 정렬했다.
- **검증(로컬)**: curated routes/repo unit 10 passed, ruff 변경 파일 clean,
  mypy --strict 변경 source 2개 clean, OpenAPI `--profile all --check` 통과.

## 2026-07-10 (codex) — Feature 지도 기본 weather/notice 필터와 초기화 버튼 복원

- **수정**: `/features` 지도 kind 필터 기본값을 `weather`, `notice` 선택 상태로 변경하고,
  `초기화` 버튼을 항상 표시하되 기본값과 같을 때는 비활성화되도록 했다. 버튼 동작은 전체 해제가
  아니라 기본 `weather`/`notice` 선택 복원으로 정리했다.
- **저zoom 확인 보강**: 기본 zoom의 `/v1/features/in-bounds` 클러스터 요청이 선택된 kind를 반복
  `kind=` 파라미터로 보내는지 mocked/live e2e를 보강했다.
- **검증(로컬)**: frontend `type-check`, e2e type-check, 변경 파일 ESLint 통과. 로컬 WSL
  Playwright는 브라우저 다운로드가 `ubuntu26.04-x64` 미지원이라 mocked browser 실행은 n150 live
  e2e에서 대체 검증 예정.

## 2026-07-09 (codex) — feature weather API 경로 정리

- **결정 보정(ADR-062)**: weather는 독립 리소스보다 feature의 공용 속성/시계열에 가깝기 때문에,
  직전 `/v1/weather/*` 공개 경로를 feature API 하위로 옮긴다.
- **API**: forecast timeline은 `/v1/features/weather/forecast`(좌표 기준)와
  `/v1/features/{feature_id}/weather/forecast`(feature 기준), 기상특보 이력은
  `/v1/features/weather/alerts`로 노출한다. 기존 `/v1/features/{feature_id}/weather` card API는 유지.

## 2026-07-09 (codex) — 공개 Weather API와 3년 이력 보존

- **결정(ADR-062)**: weather value 보존 정책을 30일에서 기본 3년으로 변경. 같은
  `valid_at`에 대해 `issued_at`이 다른 예보 snapshot을 보존해 3시간 전/1일 전 발표 예보와 현재
  발표 예보를 비교할 수 있게 한다.
- **API**: 외부 시스템용 weather forecast/history API를 추가했다. 기존
  `/v1/features/{feature_id}/weather` card API는 호환 유지.
- **DB/지도**: 새 테이블 없이 `feature_weather_values`와 KMA alert `source_records`를 재사용하고,
  3년 timeline 조회용 보조 인덱스를 추가했다(0043). Feature 지도 weather marker는 zoom 14 이상
  개별 marker에서 현재기온이 없으면 중기/단기 예보 지표도 라벨로 표시한다.
- **검증**: API unit/OpenAPI 8 passed, weather_repo integration 9 passed, ruff 변경 파일 clean,
  mypy --strict 135 source clean, import-linter 4 kept, OpenAPI `--profile all --check` 통과,
  frontend/user-client generated type check 및 type-check 통과, frontend lint 0 errors(기존 warning 4).

## 2026-07-09 (codex) — Claude Code PR #638 2차 사후 리뷰: 파일 검색 정합성

- **리뷰 범위**: Claude Code 관리 UI 개편 스택 #634~#638을 closed/superseded PR(#635~#637)
  포함해 current main(#653 이후) 기준으로 재검토했다. 이전 Codex 후속 #652의 #650/#651 수정은
  반영된 상태로 확인.
- **발견(#655)**: `/admin/files` 검색 placeholder가 `경로 · provider · dataset`을 안내하지만,
  backend `file_registry.list_managed_files(q=...)`는 `path ILIKE`만 검사했다. provider 이름이나
  dataset key 검색이 UI 기대와 다르게 0건이 될 수 있었다.
- **수정**: `q` predicate를 `path/provider/dataset_key` 검색으로 확장하고, 실 PostGIS 통합 테스트에
  provider/dataset 검색 회귀 케이스를 추가했다.

## 2026-07-09 (claude) — Feature 지도 저zoom 서버측 region 클러스터 (#649, #12 잔여) — 라이브 검증 완료

- **배경**: 배치 #12(지도 응답성)의 잔여 인프라. 저zoom에서 개별 feature를 tile로 대량
  조회해 4코어 박스를 포화시키던 것을 서버측 행정구역 rollup으로 대체.
- **핵심 발견**: 백엔드 클러스터링은 이미 완비돼 있었다. `/v1/features/in-bounds`가
  `_resolve_cluster_unit`(zoom ≤7 sido/≤10 sigungu/≤13 읍면동/≥14 개별)로 유도해 `clusters[]`를
  반환하는데, 프론트가 `zoom`을 서버로 안 보내 항상 개별 feature를 받았다. → 엔드포인트 **소비**만.
- **구현(#653, 프론트 3파일)**: `useFeatureClustersInBbox`(정수 zoom, tiling 없이 viewport 1회) +
  `VWorldServerClusters`(서버 `{cluster_key,feature_count,lon,lat}`를 DOM count 버블로 렌더,
  maplibre cluster:true 재군집 미사용, 클릭 시 다음 밴드로 확대) + `clusterMode`(zoom≤13) 분기
  (개별/클러스터 fetch 상호 배타, 상태 배지·목록 안내 문구·지도 오버레이 힌트). 개별 경로
  unmount cleanup(source/layer/marker/listener) 검증.
- **라이브 검증(n150, Playwright)**: z6.5 → **17개 sido 클러스터**(206k~84, "17개 지역 · 968,624건
  집계"), z10 → 27 sigungu, z12.2 → 70 읍면동으로 밴드 refine. z13.7 초과 → 개별 모드 전환("264건
  표시", category 아이콘 마커, 오버레이 사라짐). 네트워크: z≤13은 `/in-bounds?zoom=` 1회, z>13은
  `/v1/features` tiled. 저zoom 968,624건 → 17행 fetch로 즉시 로드.
- **UX(사용자 승인)**: 근접-군집 → 행정구역-군집 / 저zoom 테이블 안내 문구.

## 2026-07-09 (codex) — Claude Code PR #632~#638 사후 리뷰 후속 수정

- **리뷰 범위**: Claude Code 생성 PR #632(opinet stale) · #633(notice lifecycle) ·
  #634~#637(관리 UI 개편 스택, #635~#637 closed/superseded) · #638(통합 머지)을 current
  main(#648) 기준으로 재검토했다. #639~#648에서 이미 보강된 회귀(파일 목록 CAST,
  feature 검색 fast-path, 지도 dedup/성능 등)는 중복 수정하지 않았다.
- **수정 1 — price card `latest_at`(#650)**: stale 지평선 때문에 `current`가 비는 feature도
  history에는 마지막 관측이 남는데, 기존 `latest_at` 계산이 `current`만 보면서 `null`을
  반환했다. `history` 기준으로 마지막 관측 시각을 보존하도록 수정하고 stale-only 통합 테스트를
  보강했다.
- **수정 2 — managed file reappeared 감사 이력(#651)**: `register_file()`이 `deleted/missing`
  복귀만 `reappeared`로 남기고 `orphan→active` 복귀는 이력 없이 지나갔다. orphan 복귀도
  `reappeared` 이벤트를 기록하도록 보강하고 실제 DB 이벤트 통합 테스트를 추가했다.
- **검증**: `pytest -s tests/integration/test_price_freshness_horizon.py
  tests/integration/test_file_registry_list.py -q` → 6 passed, `pytest -s
  tests/unit/test_file_registry.py tests/unit/test_file_registry_scan.py -q` → 28 passed,
  `ruff check` 변경 파일 clean, `mypy --strict` 변경 source 2파일 clean.

## 2026-07-09 (claude) — 사용자 버그/기능 배치(10건) 완결

- **배치 10건 전량 처리** (2026-07-07~09). 9건 코드+배포, 1건(#12 지도 성능)은 클라이언트
  개선분 배포 + 잔여는 인프라 과제로 스코핑:
  - #10 파일 관리 500 (asyncpg CAST, PR #640) — 라이브 `LIST_OK`.
  - #18 운영 log enable (`API_CALL_LOG_ENABLED` override) — `ops.api_call_log` 적재 확인.
  - #14 concierge google/naver/kakao 키 복사 (n150 override).
  - #17 curated 지도 dedup (PR #641).
  - #11 feature 지도 dedup — 렌더 입력 dedup (PR #642).
  - #19 REST API feature_id dedup — curated cross-theme + search float cursor 경계 (PR #643) — 라이브 `all_unique=True`.
  - #16 큐레이션 title 멀티콤보 필터 (PR #644).
  - #13 weather/price 마커 좌표 어긋남 — 라벨 absolute 앵커 (PR #645).
  - #15 concierge YouTube 그룹핑 → curated 테마 source (PR #646 detail_selector + PR #647 sync, ADR-061).
    prod sync 1회 실행: **31 테마(채널 20 + 재생목록 11) · 31 detail_selector rule · 1944 curated feature**
    자동 게시. 멱등(2회차 rules_created=0). on-demand 트리거는 Dagster `concierge_theme_sync` asset.
  - #12 지도 응답성 — `useFeaturesInBbox` outer key viewport 서명 `.toFixed(4)→.toFixed(2)` +
    zoom 성분 제거 + outer staleTime 5s→30s. tile(≥9.7km) 내부 작은 pan이 순수 cache hit이 됨.
- **잔여 인프라 과제(#12)**: 필터 적용·대형 pan 지연은 서버 병목(휴게소 4코어 박스 밀집 bbox tile
  조회, 1M feature). 근본 해법은 **저zoom 서버측 region clustering**(기존 `/v1/features` `cluster_unit`
  엔드포인트 활용 — 저zoom에서 개별 feature 대신 sido/sigungu 집계 렌더) 또는 MV/박스 증설 — UX(군집
  방식) 변경이라 별도 스코프. 클라이언트 파이프라인(per-tile 캐시·keepPreviousData·abort)은 이미 최적.
- **작업 방식**: 로컬 디스크 포화(타 프로젝트 geo 데이터)로 프론트는 n150 빌드/검증, push는 로컬에서.
  prod 설정(#14 키·sync 트리거)은 git 밖 — 배포 런북+메모리에 기록.

## 2026-07-07 (claude) — 파일 관리 목록 500 수정 (asyncpg AmbiguousParameterError)

- **증상**: `/v1/admin/files?sort=downloaded_at&limit=50&offset=0`(파일 관리 기본 뷰)가 항상
  HTTP 500 INTERNAL_ERROR. 라이브 api 컨테이너에서 재현 → `asyncpg.exceptions.
  AmbiguousParameterError: could not determine data type of parameter $3`.
- **원인**: `file_registry.list_managed_files`의 WHERE가 nullable scalar 필터를
  `(:provider IS NULL OR provider = :provider)`처럼 **CAST 없이** 썼다. 값이 None이면 asyncpg가
  bare `$3 IS NULL`의 타입을 못 정해 prepare 단계에서 실패. array 필터(`CAST(:kinds AS text[])`)만
  CAST돼 있었다. 필터가 전부 None인 기본 뷰에서 결정적 500.
- **수정**: 6개 scalar 필터(provider/location/registered_by/q → `CAST(:x AS text)`,
  min_age_days/max_age_days → `CAST(:x AS int)`)를 감쌌다. admin_feature_repo가 이미 쓰는 패턴.
  라이브 prod DB로 수정 쿼리 검증(14행 정상 반환).
- **회귀 가드**: file_registry는 **통합 테스트가 없어**(단위는 가짜 세션이라 SQL prepare 오류를 못
  잡음) 이 asyncpg-전용 버그가 CI를 통과했다. `tests/integration/test_file_registry_list.py`
  추가 — 실 PostGIS로 기본 뷰(all-None) + 각 필터 경로 검증.
- **PR**: (번호) base=main. 배포 시 api 재빌드.

## 2026-07-06 (claude) — 관리 feature 검색 fast-path: 완전한 feature_id → PK 등가

- **문제**: `/v1/admin/features?q=<id>`에 완전한 feature_id를 붙여넣어도 `q_like`(`%id%`)로 처리돼
  1M feature ILIKE 전체 스캔 + `source_records` 상관 서브쿼리(EXISTS)를 타서 14~60s 소요.
- **수정**: `_feature_id_exact_query`가 정규식 `^f_[^_]+_[a-z]_[0-9a-f]{16}$`
  (core.ids `make_feature_id`의 `f_{bjd}_{kind}_{sha1[:16]}`)로 완전한 feature_id를 감지하면
  `:q_exact` 파라미터 + `_admin_features_sql(exact_id=True)`로 q-절을
  `f.feature_id = CAST(:q_exact AS text)`(PK index)로 스왑, ILIKE 체인·EXISTS를 건너뛴다.
  부분 검색어·비-feature_id는 기존 `q_like` ILIKE 경로 유지.
- **범위**: `_admin_features_sql` 한 곳만. 다른 q_like 사이트(feature change-request/dedup/enrichment
  review)는 소형 테이블·EXISTS 없음이라 손대지 않음.
- **검증**: unit 3건(exact-query 감지, fast-path SQL/params 스왑, 일반 검색어 qsr 유지) +
  t212d EXPLAIN 통합(exact_id=True가 features PK 인덱스 사용) 추가. 로컬 CI-parity 컨테이너에서
  ruff check·mypy --strict(99)·lint-imports(4 kept)·pytest tests/unit+lint(1168 passed) green.
  API 계약·OpenAPI·스키마 변경 없음(동일 응답, 속도만). alembic 없음(PK 인덱스 기존).

## 2026-07-05 (claude) — 관리 UI 개편 C: 검증/어시스트·텍스트 절약

관리 UI 개편 C(#636). 인라인 검증(JSON/좌표/정책)·useConfirm 전환·CursorPager 통일·
Dagster/오프라인 업로드 입력 어시스트를 반영하고, 화면 설명문의 영어 전문용어·제목 반복을
간결한 한국어로 정리했다(7개 화면 description + 자명 힌트 제거). type-check·eslint·vitest(57) green.
C 마무리 pass(추가 커밋): 상세 힌트 6건 `hint→help`(HelpTip 아이콘) 전환(providers 소스종류·
curated 표시제목/재사용정책/큐레이션관계·change-requests 중복방지키·dagster 코드위치 새로고침
안내), curated `region_scope`를 시도/시군구 AdminRegionAutoSearch 미니폼으로(원본 JSON은 '고급'
`<details>`), curated/enrichment `JsonBlock`을 공용 `JsonViewer`로 이관. type-check·eslint·vitest(57) green.
남은 후속(단일): 커스텀 모달 2건 공용 Dialog 이관(live 검증 동반), 저중복 화면들의
SectionCard/DetailList/FilterBar 채택 sweep(curated `<dl>`4·gray-box11, enrichment `<dl>`3·gray-box5,
providers gray-box7 등 — providers cursor `<pre>`는 spec가 직렬화를 단언해 JsonViewer 이관 보류).
## 2026-07-05 (claude) — 관리 UI 개편 D: 파일 레지스트리 + 추적 UI

관리 UI 개편의 D 단계(PR-B nav 위에 스택). "provider가 다운로드한 파일·자체 백업 등
시스템 저장 파일을, 단순 리스팅이 아니라 어디에 어떻게 연결됐고 사용 중인지·임시인지·언제
받고 마지막으로 로드됐는지 추적" 요구.

- **DB(0040)**: `ops.managed_files`(파일 1건 = storage_backend/location/path/kind/status/
  provenance FK/시각) + `ops.managed_file_events`(생애 이벤트). `down_revision=0039` —
  notice #633의 0040과 충돌하므로 **최종 통합 시 coordinator가 merge-migration 추가**.
- **계측·reconcile**: 생산/소비 지점(백업·offline 업로드·MOIS sync·provider fetch·dagster)
  hook로 등록/touch. hook 실패가 host op를 깨지 않도록 `registry_guard`로 감싼다. 주기 스캔은
  소유권 분리 — **backup_root=api, mois_source·S3=dagster**(`managed_file_scan` job, 6시간
  STOPPED 스케줄). orphan rule flag-only, purge는 좁은 zombie만.
- **API(`/v1/admin/files`)**: 목록(kind/status/provider/location/기간 필터·total_count),
  요약 집계, 상세(+서버 조립 provenance links·이력 50), 재스캔(backup_root 동기 + offline
  backfill; dagster location은 deferred 안내), zombie purge(파괴적 스위치 게이트 + 서버 재검증).
  TTL 노브는 코어 `KorTravelMapSettings` 직접 읽기(ApiSettings에 없음).
- **UI(`/admin/files`, 시스템 그룹)**: 요약 칩(클릭=필터) + 필터 바 + 목록 + 상세 provenance
  패널(연결 딥링크·이력 타임라인·메타 JsonViewer·zombie purge). 공용 컴포넌트(SectionCard/
  DataTable/DetailList/StatusBadge/EmptyState/HelpTip/JsonViewer) 재사용. 한국어·HelpTip.
- **검증**: ruff/mypy --strict/lint-imports(4 kept) green, dagster defs(41 jobs·37 schedules,
  scan job+schedule 등록)·21 dagster test green, 신규 router 7 test green, openapi.json/
  openapi.user.json·types.ts 재생성, 프론트 type-check·eslint(0 error)·vitest 57 green.
  e2e: nav-mirror 20→21 + scenario-catalog `files` + mocked smoke(`files-page.spec.ts`).
  **머지 금지** — live UI e2e(n150 docker-playwright)는 coordinator 최종 통합에서.

## 2026-07-04 (claude) — 관리 UI 개편 B: nav 그룹·크로스링크·헤딩 정본·spec 정합화

관리 UI 개편(조사→설계 종합→PR A/B/C)의 B 단계. PR-A(공용 컴포넌트) 위에 스택.

- **nav 재편(`admin-shell.tsx`)**: 평면 20링크 → `NAV_GROUPS`(홈 / Feature 관리 /
  수집 파이프라인 / 모니터링 / 시스템) 단일 정본. 라벨 3건 정정(중복 검토/보강 검토/갱신 요청 —
  nav=H1 불변식). 섹션 배지는 NAV_GROUPS longest-prefix로 유도, 클라이언트 `section=` prop
  21곳 삭제(듀얼라우트 3곳만 오버라이드 유지). `breadcrumbs`/`help` prop 추가.
- **헤딩 정본**: Provider 상태·운영 로그·정합성 점검·큐레이션 지도·ETL 미리보기(+AdminShell 편입,
  마지막 셸 밖 페이지 해소)·공개 API 키/로그인 감사(h2)·중복 검수 대기(h2).
- **크로스링크(§2 전체, EntityLink 단일 URL 테이블)**: 이슈 행/상세→feature 상세, 업로드
  validation/load job→작업 상세, feature 상세 Sources→Provider 상태·Issues→이슈 필터·History→
  변경요청 강조, 목록 provider/이슈 셀, 정합성 배치→작업 목록·provider→이슈, 작업 목록 배치/상위,
  작업 상세 load_batch dead-link 수정+갱신요청 상세 딥링크+운영 로그 버튼, 갱신요청 dagster run
  외부링크, 홈 메트릭 카드 4종+최근 작업 행, POI nearby, ETL→Provider 상태, Feature 지도↔큐레이션
  지도 토글, providers 실패 alert→이슈·dataset 패널→생성된 Feature 보기/이벤트 로그, 백업 결과→
  운영 로그, dagster 실패→운영 로그.
- **딥링크 plumbing**: `/ops/logs`(tab=system|api|events·job_id·provider·dataset_key·level),
  `/admin/issues`(feature_id·provider·dataset_key·status + feature_id 필터 입력 신설),
  `/admin/features`(q·kind·status·provider·dataset_key·has_issue + provider/dataset 셀렉트 —
  API 클라이언트가 이미 지원), change-requests/change-reviews `?request_id=` 행 강조.
- **브레드크럼**: feature 상세·큐레이션 상세·갱신 요청 상세·적재 작업 상세 4곳.
- **spec 정합화**: NAV 미러 3곳(home-nav 20개 정본+그룹 헤더 단언, home-density, misc.live) 재작성,
  기존 stale 영문 h1/카드 제목(Providers/Logs/Consistency/Admin issues/Backups/Import jobs/
  Dedup review/Enrichment review/ETL preview/Features/Dedup queue/Issues/POI cache targets/
  Offline uploads/Feature update requests/이슈 상세 등) 29파일 일괄 정정, 신규 링크 스모크 4종
  (홈 카드 href·logs 딥링크 초기화·정합성 배치 링크·이슈 Feature 상세 href) 추가.
- **검증**: tsc(src+e2e) clean · eslint 변경 69파일 0 errors · vitest 57 passed. 라우트 이동/
  리다이렉트/API 변경 없음. Playwright 실행은 최종 게이트(n150 live)에서.
## 2026-07-05 (claude) — 종료 notice를 모든 read 경로에서 기본 제외 + 빈-feed 안전장치 (#633)

사용자 요구: "notice는 수집 시 notice가 없으면 과거 자료를 보여주는 게 아니라
API에 노출하지 않음." #632(2026-07-03)에서 bbox·이름 검색까지만 걸었던 종료 notice
숨김을 **나머지 read 경로 전부**로 확장했다. 종료 판정은 오직 `valid_end_time`이
채워졌는지로만 하므로(last_seen 최신성 무의존) 이후 poll이 실패해도 이미 닫힌
notice는 계속 숨는다.

- **read 술어 확장**(`feature_repo`): 클러스터(`_cluster_bbox_sql`), 주변
  (`features_nearby` 좌표·POI target CTE ×2), 영역 포함
  (`_FEATURES_CONTAINED_IN_AREA_SQL`), 카테고리 카운트
  (`_CATEGORY_FEATURE_COUNTS_SQL`)에 `kind<>'notice' OR valid_end_time IS NULL
  OR valid_end_time>now()` 추가. bbox·이름 검색은 #632에서 이미 적용.
- **admin 목록 방침 전환**: #632에서 "감사 목적 show-everything이라 의도적 미적용"
  했던 `list_admin_features`를 **기본 제외로 전환**하되, 종료분 감사가 필요하면
  `include_ended=true`(API query param) opt-in. router·repo·OpenAPI(admin
  프로필만; user 프로필엔 admin 엔드포인트 없음) 갱신.
- **단건 예외 유지**: `get_feature_row`/by-id 상세는 직접 참조라 종료 notice도
  그대로 200 반환(그 상태를 그대로 노출).
- **빈/실패 feed 안전장치(guard #1)**: KREX notice asset이 fetch 0건이면
  `reconcile_notice_features(active_lineage_keys=None, closed_at=None)`로 넘겨
  feed-소멸 닫기를 **건너뛴다** — 빈 집합(`set()`)을 넘기면 모든 active notice가
  "feed에 없음"으로 판정돼 통째로 종료·비노출되는 사고를 막는다. 진짜 0건이면
  다음 비어있지 않은 run이 닫는다.
- 검증: `test_notice_lifecycle`에 read-경로 기본 제외/`include_ended` opt-in/
  단건 유지 + 빈-feed close-nothing 통합 테스트 2건 추가. t212d EXPLAIN 테스트에
  신규 `:include_ended` bind 반영. ruff·mypy --strict·lint-imports·unit(1131)·
  api(320)·dagster(216)·integration(263, live 5 deselect) 로컬 green.

## 2026-07-03 (claude) — notice 중복 근본 해결: 사건 단위 identity + 라이프사이클 (#632)

notice feature가 "로직을 보강해도 계속" 중복되던 문제의 근본 원인을 잡았다 —
정체성이 발표/스냅샷 단위였다(prod: KREX 6,164건 중 계보 1,317개 ≈ 4.7×,
KMA 특보 43건 전부 발표 단위, valid_end 100% NULL·purge 없음 → 영구 누적).

- **KMA 특보(사건 단위 재키잉)**: 자연키 `{alert_id(tm_fc/seq)}::{region}` →
  `{region_code}::{현상 토큰}`(`kma_alert_natural_key`). 현상 토큰(호우/풍랑/…)
  기준이라 notice_type이 generic으로 접는 특보끼리도 안 붕괴. 재발표·등급
  변경은 같은 feature upsert(발표 이력은 source_records). **해제는 feature를
  만들지 않고** `weather_alert_lift_closures`가 열린 feature의
  `valid_end_time`을 채운다(결합 해제문 현상별 fan-out, 배치 내 최신만).
- **KREX 교통 돌발**: feature_id에서 reverse-geocoded bjd_code 제거 — 이동하는
  정체가 동 경계를 넘을 때 같은 사건이 재키잉되던 잔존 버그(4680f17 이후에도
  1–2건/일 누적). 적재 직후 `reconcile_notice_features`가 ① 같은 계보 중복
  soft-delete(latest 유지) ② 이번 feed에 없는 계보 `valid_end=fetched_at` 종료.
- **일회성 정리**: `0040_notice_dedup_cleanup` — KMA 구세대 전부 + KREX 계보별
  latest 아닌 것 soft-delete(ADR-017, 원문 source_records 보존). 예상 ~4.8k건.
- **read 필터**: `_notice_lineage_sql`에 KMA 분기 추가(구세대 raw_data로도 계보
  합류), bbox 필터에 종료 notice 숨김 추가, 이름 검색도 종료 notice 제외.
  admin 목록은 감사 목적 show-everything이라 의도적으로 미적용.
- **§9 보존 구현**: `purge_expired_notices`(종료/발표 +1년, 기본)를
  maintenance job op로 추가.
- 검증: kma_alerts/krex 단위 테스트(재발표 안정성·해제 closure·결합 해제·배치
  dedupe·좌표 이동 안정성) + `test_notice_lifecycle` 통합(supersede/close/
  bbox 숨김/purge, testcontainers).
- 배포 후: alembic 0040 자동 적용 → KMA/KREX notice asset 재실행 → 중복 계보
  카운트 재확인(오케스트레이터가 prod 검증 예정).
## 2026-07-03 (claude) — OpiNet price staleness 근본 수정: 시군 윈도 로테이션 + 현재가 신선도 지평선

가격 스케줄이 매일 돌아도 price feature 37%(1,066/2,883)가 3–7일 stale로 단조
누적되던 문제의 근본 원인을 찾고 수정했다.

- **원인 (prod 실측)**: `low_top_area` fetcher의 `lowTop10` 호출 상한(180 = 시군
  60개 윈도)이 전국 ~230 시군을 못 덮는데 시군 목록에 로테이션이 없어 **매일 같은
  ~60개 시군의 top-20 저가 주유소만 갱신**(일간 동일 주유소 겹침 93%). top-20/윈도
  밖으로 밀린 주유소는 영구 stale. 쿼터 소진 아님(사용 ~198/1,500), cursor 문제
  아님, UI 타임스탬프 문제 아님.
- **수정 1 — 로테이션**: run 날짜(KST) 기반 결정적 offset(`_opinet_rotation_offset`,
  `toordinal() × 윈도 크기`)으로 시군 목록 회전 → 매일 윈도만큼 전진, 전국 1주기
  ≈ 4일, 호출량 불변. 목록이 한 윈도에 다 들어가면 no-op. round-robin 시도 공정성
  유지.
- **수정 2 — 운영 노브**: `KOR_TRAVEL_MAP_OPINET_LOW_TOP_MAX_CALLS`(기본 180),
  `KOR_TRAVEL_MAP_OPINET_RUN_CALL_BUDGET`(기본 600)를 settings 필드로 노출 — 코드
  변경 없이 커버리지 상향 가능. 쿼터 수학은 `docs/etl/opinet-place-price-etl.md`
  §8.2 (매월 1일 place job 겹침 주의 포함).
- **수정 3 — 신선도 지평선**: `KOR_TRAVEL_MAP_PRICE_STALE_HIDE_DAYS`(기본 4 =
  로테이션 1주기)보다 오래된 관측은 지도 `price_summary` 마커와 price card
  `current`에서 제외(이력·값은 보존, `asof` 과거 시점 질의에는 미적용) — 로테이션
  주기 밖 옛 가격이 현재가처럼 보이지 않게.
- **수정 4 — `is_stale` 임계 정합**: price card `is_stale` 기본 임계(과거 18h)를
  지평선에서 파생(4일 = `DEFAULT_PRICE_STALE_HIDE_DAYS × 86400`)하도록 변경.
  18h 기준이면 로테이션 아래에서 정상 갱신 중인 주유소 대부분이 상세 패널에
  항상 stale 배지로 표시된다(사용자 가시 증상). 이제 `is_stale` ⟺ "지평선 안
  관측 없음" ⟺ `current` 비어 있음 — 단일 노브, 신호 일치. weather card의
  `DEFAULT_WEATHER_FRESHNESS_SECONDS`는 별도 상수라 영향 없음. 지도 마커는
  `is_stale`을 쓰지 않으며(라벨은 `price_summary`) 수정 3의 지평선으로 이미
  정합. 호출별 `freshness_seconds` override는 유지.
- 배포 후 확인: 신선도 분포가 ~4일에 걸쳐 <1d ~25% / 1-4d ~75% 형태로 수렴하는지,
  3–7d 버킷이 0으로 떨어지는지 (`max(observed_at)` 버킷 쿼리).

## 2026-07-03 (claude) — 큐레이션 관리 UX 개편 (라이프사이클 스트립·한국어 액션·워크플로 가이드)

curated feature 관리 화면(UI/UX·워크플로)을 처음 온 운영자도 흐름을 읽을 수 있게 개편했다.
backend/OpenAPI/migration 변경 없음 — admin frontend + e2e만.

- **라이프사이클 스트립**: 후보→큐레이션됨→거절됨/보관됨 4칩(=상태 필터 버튼, aria-pressed)과
  상태별 결과 캡션, '이 화면의 동작 방식' 설명을 목록 상단에 상시 노출. DETAIL은 compact 변형.
- **탭 재구성**: '후보 검토'(필터+목록+검토 패널)와 '소스 규칙'을 탭으로 분리해 한 화면의 인지
  부하를 낮췄다. 빈 목록에는 '소스 규칙 탭 열기'/'새로고침 job 실행' 다음 행동을 제안.
- **동사 통일(한국어)**: 채택/채택 해제/보관/결과 적용/규칙 적용. 상태 전환마다 토스트로 결과를
  설명하고, 채택 토스트는 '큐레이션됨 보기' 필터 점프 액션으로 "행이 어디 갔지?"를 해소.
- **행 단위 pending**: 전역 mutation 잠금을 mutation.variables 기반 행 잠금으로 교체. bulk는
  Promise.allSettled로 성공 N·실패 M 집계 토스트 + 실패 행만 체크 유지.
- **서버 검색**: client 텍스트 필터(현재 페이지만)를 서버 `q` 검색(300ms 디바운스, 전 페이지)으로
  교체하고 카운트 라인을 'page N · 이 페이지 M개 · 페이지 크기 K'로 정직하게 바꿨다.
- **editor dirty 가드**: override 패턴(입력 전엔 서버 값 렌더)으로 refetch 자동 반영 + 입력 중
  다른 작업이 patch하면 Alert('최신 값 불러오기')로만 교체. 수정됨 배지·초기화 버튼. 노출 순위는
  Number.isFinite 검증으로 silent NaN PATCH를 차단(입력을 text+decimal로 전환).
- **장소 대조 검색**: '결과 적용' 시 재사용 정책 allowed 전환을 opt-out 체크박스(기본 on)로
  노출 — 해제하면 PATCH body에서 reuse_policy 생략. metadata에만 저장됨 캡션 상시 표시.
- **소스 규칙**: Apply를 폼 footer '규칙 적용 (후보 생성)'로 이동 + confirm(동작·비되살림 설명) +
  생성/갱신 건수 토스트. sticky Alert 제거, 규칙 저장 토스트, 라벨 한국어(enumOption raw 병기).
- **라벨 sweep**: nav 'Feature 큐레이션'→'큐레이션 관리', 'Curated 지도'→'큐레이션 지도',
  정책·관계 컬럼(한글 라벨+title=raw), 필터 option 텍스트 한국어(**value는 raw enum 유지** — e2e
  locator 안정), filter aria-label은 영문 유지.
- **e2e**: mocked 스펙에 신규 시나리오 12종(토스트 점프/부분 실패/서버 검색/dirty 가드/opt-out/
  규칙 confirm 등) + 전 curated 스펙 locator 이행. live write 스펙의 **이미 stale이던 영문 헤딩**
  (Curated features/Curated feature detail)도 이번 이행에서 수정. live 실행은 n150에서 별도 진행.
- **검증**: `tsc --noEmit`(src+e2e) clean, eslint 변경 파일 0 errors. e2e 실행은 하지 않음(오케스트레이터가
  n150 배포 후 live 실행 예정).

## 2026-07-02 (codex) — Notice 중복/시간과 Curated Feature 지도 후속 수정

notice와 curated feature 운영 화면의 follow-up 회귀를 수정했다.

- **notice 중복**: KREX 교통공지 자연키와 bbox 최신값 lineage에서 `series_no`를 제외했다. 같은 사건의
  series 변경은 새 feature로 보지 않고, 지도에는 최신 source record에 연결된 notice만 남긴다.
- **notice 시간**: 원천 발생일+시각이 있으면 `valid_start_time`에 사용하고, 시각이 없거나 파싱할 수
  없으면 최초 probing 시각(`fetched_at`)을 시작 시간으로 채운다. payload 변경 재수집은 description 등
  본문을 업데이트하되 최초 probing 시작 시각은 보존한다.
- **지도 갱신**: Feature 지도 tile zoom 계산을 `ceil` 기반으로 바꾸고 bbox/zoom signature를 query key에
  포함했다. GeoJSON source data 변경 직후 DOM marker 업데이트도 예약한다.
- **curated 지도**: `/curated-features` 화면을 추가했다. 기존 Feature 지도와 같은 지도/테이블/상세
  형태이며 POI명, 테마명, 제목, 데이터소스 필터를 제공한다.
- **curated 표시**: 기존 큐레이션 목록/상세/위치 검토와 새 지도 화면 모두 실제 `feature_name`을
  주 표시로 쓰고, `display_title`은 보조 제목으로 분리했다.
- **검증**: KREX/curated repo/routes unit 48 passed, feature_repo notice integration 2 passed, 전체
  ruff, `mypy --strict src`, import-linter, OpenAPI drift check, frontend gen:types:check/type-check,
  user-client gen:types:check/type-check, frontend lint(기존 warning 4건), frontend production build
  통과(필수 public env 로컬값 지정). mocked Playwright e2e spec은 추가했지만 WSL Ubuntu 26.04에서
  Playwright Chromium install이 미지원이라 로컬 실행 전 실패했다.

## 2026-07-02 (codex) — 큐레이션 feature theme/title 편집

curated feature의 theme 연결과 theme 아래 세부 POI 묶음 제목(`display_title`) 운영 방식을 정리했다.

- **기본 제목 정책**: data.go.kr, MCST 등 정부·공공기관 source rule 후보는 provider 이름을
  기본 `display_title`로 채운다. `kor-travel-concierge-youtube/youtube_place_candidates`는
  API가 제공하는 `youtube.source_title`을 우선 사용하고, playlist/channel/search 제목은 fallback으로
  유지한다.
- **admin 편집**: Feature 큐레이션 편집 패널과 전용 상세 화면에서 theme와 `display_title`을 함께
  patch할 수 있게 했다. source rule 재적용은 이미 입력된 제목을 덮어쓰지 않고 빈 제목만 채운다.
- **계약 갱신**: admin patch DTO/OpenAPI/generated type, curated repo 단위·통합 테스트,
  route-mocked e2e를 새 정책에 맞췄다.
- **검증**: curated repo unit 6 passed, curated repo integration 7 passed, 전체 pytest 1380 passed,
  전체 ruff, `mypy src/kortravelmap`, import-linter 4 contracts, OpenAPI drift check,
  frontend gen:types:check/type-check/lint(기존 warning 4건), Windows Playwright fallback
  route-mocked curated mutations e2e 21 passed, frontend production build 통과.

## 2026-07-02 (codex) — 큐레이션 theme set 확장과 Source rules job 연결

Feature 큐레이션 화면의 기본 theme set과 운영 실행 경로를 보강했다.

- **테마 seed**: 계절별 여행지 4종(봄꽃, 여름 바다, 가을 단풍, 겨울 눈꽃)과 지역별 여행지 6종
  (서울·수도권, 부산·동남권, 제주, 강원 자연, 전라 맛·문화, 경주·신라 역사)을
  `feature.curated_themes` seed로 추가했다.
- **Source rules UI**: `Source rules` 패널에 `관련 job 실행` 버튼을 추가해
  `/admin/dagster?schedule=curated_features_refresh_daily_schedule`로 이동하고, 작업 자동화 화면이
  해당 스케줄 row를 강조하도록 했다. 운영자는 기존 `즉시 실행` 버튼으로 관련 job을 바로 실행한다.
- **concierge 재확인**: 기존 `kor-travel-concierge-youtube/youtube_place_candidates` source rule이
  `media-places` 큐레이션과 detail snapshot을 만드는 통합 테스트에 확장 테마 seed 검증을 추가했다.
- **검증**: `tests/integration/test_curated_repo.py` 7 passed, Dagster concierge fetcher targeted
  5 passed/72 deselected, curated refresh schedule 등록 1 passed, 전체 ruff, `mypy src/kortravelmap`,
  import-linter 4 contracts, frontend type-check, frontend lint(기존 warning 4건), frontend build 통과.
  Windows Playwright fallback으로 Source rules job link와 Dagster schedule query highlight targeted e2e
  2건을 통과했다. WSL Playwright는 Chromium 바이너리 부재로 실행 전 실패했다.

## 2026-07-02 (codex) — Feature 지도 notice 최신 표시와 source last_seen 이력화

Feature 지도 겹침 선택 메뉴를 시각적으로 정리하고, notice source 이력/중복 재수집 정책을 보강했다.

- **지도 UI**: 겹친 점 마커 팝업의 제목/카운트 pill, feature kind 배지, 색상 dot, hover/focus에 가까운
  행 affordance를 추가했다. 기존 겹침 선택 동작과 e2e selector 텍스트(`겹친 지점 N개`)는 유지했다.
- **notice 최신 표시**: bbox 조회에서 `kind='notice'`는 같은 provider/dataset/entity lineage 중 더
  최근 source record가 다른 feature에 연결된 경우 오래된 feature를 제외한다. KREX 레거시 raw-hash
  feature도 raw_data의 발생일시/노선/방향/지점/유형/series 단서로 묶어 최신 marker만 남긴다.
- **KREX 적재**: 교통공지 자연키에서 raw payload hash를 제거하고 사건 단서 기반 stable key로 바꿨다.
  문구/처리 상태 변경은 같은 Feature에 source_record 이력으로 누적된다.
- **중복 재수집**: `provider_sync.source_records.last_seen_at` 컬럼과 BRIN index를 추가했다. 같은
  `source_record_key` 재수집은 raw payload/Feature/version을 갱신하지 않고 `last_seen_at`만 갱신한다.
- **상세 UI/API**: admin feature 상세 source row에 `last_seen_at`을 노출하고, notice feature 상세에는
  primary source 이력을 `Notice History` 표로 표시한다. OpenAPI와 frontend generated types도 갱신했다.
- **검증**: targeted unit/API 63 passed, Dagster runner/load enrichment 11 passed, integration
  `test_feature_repo_load.py` + `test_mois_loader.py` 28 passed, perf EXPLAIN 7 passed,
  frontend type-check/gen:types:check, OpenAPI drift check, frontend lint(기존 경고 4건),
  frontend unit 45 passed, frontend production build 통과(`NEXT_PUBLIC_KOR_TRAVEL_MAP_API`,
  `NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL` 로컬값 지정), 전체 pytest 1378 passed,
  전체 `ruff check .`, `mypy src/kortravelmap`, import-linter 4 contracts, `git diff --check` 통과.
- **미검증**: mocked Playwright e2e는 현재 WSL의 Playwright Chromium 바이너리 부재와
  `playwright install chromium`의 `ubuntu26.04-x64` 미지원으로 실행되지 않았다. Windows Chrome 직접
  launch도 remote debugging pipe 문제로 실패했다.

## 2026-07-01 (codex) — Feature 작성 폼 장소 종류 최상위화

새 Feature 작성과 변경 요청 작성 화면에서 `장소 종류(place_kind)`를 보조 상세 필드가 아닌 기본 정보
영역의 최상위 입력으로 올렸다.

- **UI 정리**: 공용 `FeatureBasicInfoSection`에 `장소 종류` 입력을 배치하고, `Feature 종류`가
  `place`일 때만 표시한다. 상세 섹션에서는 전화번호·URL·행사 상세만 유지한다.
- **수정 제한**: `area`와 `route` Feature는 수동 생성·수정 대상이 아니므로, 변경 요청 작성 화면에서
  기존 `area`/`route` Feature를 불러오면 경고를 표시하고 요청 생성을 막는다.
- **계약 유지**: API payload는 기존 계약대로 `detail.place_kind`에 저장한다. 화면상의 입력 위치만
  기본 정보로 승격했다.

## 2026-07-01 (codex) — Feature 지도 겹침 선택/주소 코드 입력 후속 보강

Feature 지도에서 겹친 점 마커 선택 팝업이 보이지 않는 회귀와 새 Feature 작성 화면의 주소 입력 후속
요청을 반영했다.

- **지도 선택**: DOM 마커/클러스터 클릭 이벤트가 MapLibre map click으로 버블링되어 겹침 선택 팝업이
  바로 닫힐 수 있던 경로를 막았다. 겹침 선택 팝업은 명시 닫기 또는 후보 선택 때 닫힌다.
- **주소 코드 입력**: 새 Feature 작성과 변경 요청 작성 화면의 시도/시군구/법정동/행정동 코드를
  공용 `AdminRegionAutoSearch`로 통일했다. 결과는 접이식 팝업으로 표시하고, 선택한 코드 계층의
  이름만 노출한다.
- **검증/선택 상태**: 시도 2자리, 시군구 5자리, 법정동/행정동 10자리, 도로명 코드 12자리,
  도로명주소 관리번호 25자리 길이 검증을 추가했다. 역지오코딩/주소 후보 선택 시 주소 검색 필드와
  선택 강조 상태도 함께 갱신한다.

## 2026-07-01 (codex) — Feature 운영 경로 `/admin/features` 일원화

Feature 관련 운영 UI와 API 경로를 `/admin/features/...` namespace로 모으고, 중복/보강 검토
화면의 주요 표면을 맞췄다.

- **UI route**: `/admin/features/curated`, `/admin/features/dedup-reviews`,
  `/admin/features/enrichment-reviews`, `/admin/features/update-requests`와 상세 route를 추가했다.
  기존 `/admin/curated-features`, `/admin/dedup-reviews`, `/admin/enrichment-reviews`,
  `/admin/feature-update-requests`는 새 route로 redirect한다.
- **API route**: curated/dedup/enrichment/update request admin API를
  `/v1/admin/features/...`로 노출하고, 기존 API는 schema에서 숨긴 호환 alias로 유지했다.
  `/v1/admin/features/{feature_id}`보다 구체 route가 먼저 mount되도록 app include 순서를 조정했다.
- **검토 UI**: 중복 검토 테이블을 `리뷰/점수/거리/후보/상태/생성/작업` 순서로 정리하고,
  pending/완료 row 모두 `detail` 버튼으로 상세 비교 다이얼로그에 진입할 수 있게 했다.
  중복/보강 상세 다이얼로그 제목과 상단 metric surface도 같은 구조로 맞췄다.
- **문서/e2e**: frontend API hook, admin nav, 관련 e2e, admin frontend README와 운영 정본 문서의
  경로를 새 namespace로 갱신했다.
- **검증**: ruff targeted clean, OpenAPI drift check 통과, frontend type-check 통과,
  frontend gen:types:check 통과, frontend lint 오류 없음(기존 경고 4건), frontend unit 45 passed,
  API router targeted 35 passed, provider/ops targeted 23 passed
  (공개 키 검증 요구 off, `-s`로 pytest capture 우회),
  `git diff --check` 통과.

## 2026-07-01 (codex) — Feature 작성/변경 요청 폼 공용화

변경 요청 작성 화면의 레이아웃을 새 Feature 작성 화면 기준으로 맞추고, 좌표 미입력 상태의 지도
프리뷰 공백을 제거했다.

- **공용 섹션**: 기본 정보, 좌표 프리뷰, 주소, 상세 입력 섹션을 `feature-form-sections.tsx`로
  분리해 새 Feature 작성과 변경 요청 작성 화면이 같은 컴포넌트를 쓰도록 했다.
- **변경 요청 작성**: `변경 요청 작성` 카드 바로 아래에 `기본 정보`를 배치했다. 본문 시군구 입력은
  새 Feature 작성 화면과 같은 `AdminRegionAutoSearch`를 사용하고, 후보 선택 시 주소·행정코드·좌표를
  함께 채운다.
- **좌표 지도**: 변경 요청 작성 화면의 좌표 프리뷰가 좌표 없음 상태에서도 기본 한국 본토 중심
  지도 뷰를 렌더링한다. 빈 안내 박스 대신 동일한 지도 영역이 보이며, 지도 클릭으로 좌표 입력도
  갱신할 수 있다.
- **검증**: frontend type-check 통과, frontend lint 오류 없음(기존 경고 4건), frontend unit
  45 passed, production build 통과(`NEXT_PUBLIC_KOR_TRAVEL_MAP_API`,
  `NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL` 임시 지정), `git diff --check` 통과.

## 2026-07-01 (codex) — route/Feature 지도/OpiNet 유가 회귀 수정

세션 후속 확인 중 route 적재, Feature 지도 겹침 선택, OpiNet price 전국 분포가 다시 깨진 것을
수정했다.

- **KNPS route**: `knps_trails`의 비매칭 placeholder 제외가 정확히 `비매칭코스`/`Nonmatching Course`
  일치에 의존하던 문제를 보강했다. `비매칭 코스`, `미매칭`, `unmatched`/`nonmatching` 계열 표기와
  `MATCH_YN=N` 같은 매칭 실패 상태값도 route 적재에서 제외한다. 관련 raw key가 아닌 일반 메모에
  `비매칭`이 들어간 정상 route는 유지하는 회귀 테스트를 추가했다.
- **Feature 지도**: 숫자 클러스터 마커 클릭이 항상 확대만 시도하던 것을, 더 이상 의미 있게 확대되지
  않는 zoom에서는 cluster leaves를 읽어 기존 겹침 선택 팝업을 열도록 바꿨다.
- **OpiNet price**: `low_top_area`가 시군구 목록을 서울부터 순차 소비해 `area×product` 호출 상한에
  먼저 걸릴 수 있어, 시도별 시군구를 round-robin으로 섞어 전국 표본이 먼저 잡히도록 바꿨다. compose의
  `api`/`dagster`/`dagster-daemon`에도 `KOR_TRAVEL_MAP_OPINET_SCOPE_*` env 매핑을 명시했다. n150
  배포 후 수동 materialize 중 OpiNet root area 응답의 invalid 시도 코드가 자식 조회로 들어가던
  회귀를 확인해, provider 라이브러리가 허용하는 시도 코드만 자식 조회 대상으로 쓰도록 추가 보강했다.
- **검증**: KNPS provider 53 passed, Dagster provider fetcher 75 passed/1 skipped, Docker Dagster
  runtime 9 passed, ruff targeted clean, frontend type-check, frontend lint(기존 경고 4건), frontend
  unit 45 passed, `docker compose --env-file /dev/null config -q`, `git diff --check` 통과. 추가 보강은
  Dagster provider fetcher 76 passed/1 skipped, targeted ruff, targeted mypy 통과.
- **머지/배포**: PR #619/#620을 CI green 후 main에 머지하고 n150에 재배포했다. 배포 후 Alembic head,
  map 컨테이너 health, 공개 UI 로그인 POST(200 + Set-Cookie, 오답 401), Dagster hotfix 코드 반영을
  확인했다. OpiNet price asset 수동 materialize는 `RUN_SUCCESS`로 끝났고 운영 price feature는 15개
  시도 코드/2,624건으로 분포했다. 활성 `비매칭` route는 0건이다.
- **live e2e**: Windows Playwright live targeted run에서 Feature 지도 마커 렌더와 클러스터 클릭 zoom
  증가가 3 passed(인증 setup 포함)로 통과했다. 실제 점 마커 클릭 상세 패널 round-trip 테스트는 운영
  타일/응답 대기에서 5분 timeout이 나 별도 후속 검증 대상으로 남겼다.

