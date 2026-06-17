# ADR-028: `python-knps-api` provider 라이브러리 등록

- **상태**: accepted (T-014 Sprint 1 진입 시 전환, 2026-05-25) +
  **amendment 2026-05-25 (keyless, file-only)** — 아래 §H 참조.
- **날짜**: 2026-05-25 (원본) / 2026-05-25 (amendment, knps-api PR#4 후)
- **결정자**: claude 제안 + 사용자 (외부 repo 작성 + downstream 반영)
- **컨텍스트**: `docs/etl/forest-feature-etl.md §11`에서 KNPS dataset 14건 통합
  plan 결정 (옵션 B = 별도 `python-knps-api`, ADR-027 기반 카테고리/notice_type
  적용). 외부에서 `digitie/python-knps-api` 저장소가 사용자 주도로 scaffold
  완료 (`6e36990 Initial KNPS API client scaffold`, public client + catalog
  + Pydantic models + exceptions + httpx async + token bucket). 본 라이브러리
  에서는 이 provider를 정식 등록하고 `kortravelmap.providers.knps` 변환 모듈을
  후속 sprint에서 작성한다.

- **결정**:

  **A. provider 등록**:
  - canonical provider name: `python-knps-api`
  - import: `from knps import KnpsClient, KnpsConfig, ApiEndpoint, FileDataset,
    CatalogEntry, Page, PROVIDER_NAME, KnpsApiError, KnpsAuthError,
    KnpsNoDataError, KnpsParseError, KnpsRateLimitError, KnpsRequestError,
    KnpsServerError, api_endpoint, api_endpoints, catalog_entries,
    file_dataset, file_datasets`
  - 본 라이브러리 변환 모듈: `kortravelmap.providers.knps` (Sprint 2 작성)
  - dataset_key prefix: `knps_*`
  - 라이선스: GPL-3.0-or-later (본 라이브러리와 동일).
  - 인증 env (`knps.config.KnpsConfig.from_env`):
    1. `KNPS_SERVICE_KEY` (우선)
    2. `DATA_GO_KR_SERVICE_KEY` (폴백)
  - `pyproject.toml` `providers` extras에 git URL 주석 추가:
    ```toml
    # "python-knps-api @ git+https://github.com/digitie/python-knps-api.git@<sha>"
    ```

  **B. SHP/GeoJSON 파싱 책임 분리** → **Amendment I(2026-05-29)로 확정**:
  - knps-api는 원본 bytes (`client.files.download(key)`)와 file artifact preview
    를 안정 제공.
  - ~~SHP/GeoJSON 파싱은 본 라이브러리 `kortravelmap.providers.knps`에서 수행~~
    → **knps-api 책임으로 확정** (Amendment I / ADR-044): raw 파일 → typed
    record(좌표·geometry WKT)는 knps-api, 본 lib는 record Protocol 소비만.
  - knps-api 측 `[geo]` extra(placeholder)에 parser 구현 — 미구현 시 upstream
    PR (Sprint 2 진입 시 재검토 → 2026-05-29 확정).

  **C. ADR-027 코드 적용 시기 정렬**:
  - T-018 시점에 ADR-027 (forest 카테고리/notice_type 확장) + ADR-028 (본
    ADR) 모두 accepted 전환.
  - `PLACE_CATEGORY_DEFINITIONS`에 3행 (`03.08` Tier 2 + 2 Tier 3),
    `NOTICE_TYPES` tuple에 `access_restriction`/`fire_alert`,
    `AreaDetail.area_kind` Literal에 `hazard_zone` 일괄 추가.

  **D. 양방향 PR 워크플로** (사용자 결정 2026-05-25):
  - 본 라이브러리 작업 중 knps-api에서 발견한 maki/카테고리/명명/dataset
    정합 이슈는 **upstream PR로 적극 수정** (ADR-025 사용자 보강 2차
    `maplibre-vworld-js` 패턴 미러). 본 라이브러리에 wrapper/패치 도입
    금지 (ADR-006 위배 회피).
  - 예: knps-api PR#1 (`docs/knps-feature-maki-icons`) — `shelter`/`barrier`
    maki icon 정정 (본 라이브러리 ADR-027/ADR-029 매핑 정합).

  **E. 본 라이브러리 신설 docs**:
  - `docs/etl/knps-feature-etl.md` (본 PR#12) — feature 적재 계약. upstream
    knps-api `docs/etl/knps-feature-etl.md`와 정합 유지 (양방향 PR로).

  **F. 14 dataset_key 카탈로그** (provider-contract.md §3에 추가):
  - **API endpoints** (3): `knps_visitor_statistics`,
    `knps_access_restrictions`, `knps_fire_alerts`
  - **File datasets** (11): `knps_park_boundaries`, `knps_trails`,
    `knps_visitor_centers`, `knps_hazard_zones`, `knps_weather_stations`,
    `knps_restrooms`, `knps_cultural_resources`, `knps_campgrounds`,
    `knps_shelters`, `knps_recommended_courses`, `knps_park_photos`
  - knps-api `verification_status` (`verified` / `needs_verification` /
    `planned`) 그대로 존중.

- **근거**:
  - **1기관 1라이브러리 컨벤션 (옵션 B)**: KNPS = 환경부, KFS = 농림식품부 —
    별도 기관. `python-mois-api`, `python-krheritage-api`, `python-khoa-api`,
    `python-krforest-api`와 동일 패턴.
  - **외부 scaffold 완료**: 사용자가 작성한 repo의 공개 API/catalog를
    *그대로 채택*. 본 라이브러리에서 wrapper 만들지 않음 (ADR-006).
  - **PR 양방향 (D)**: maplibre-vworld-js 패턴 (ADR-025 2차 보강) 미러 —
    "본 사용자가 직접 운영하는 저장소 = 외부 의존이 아닌 관리 부담".
  - **knps-api 측 catalog는 source of truth**: 본 라이브러리 docs는
    *downstream 입장*의 ETL 계약만. 카탈로그 자체는 knps-api에 있고 본
    라이브러리는 `from knps import file_datasets` 등으로 직접 사용.

- **결과 (긍정)**:
  - 본 라이브러리 통합 비용 낮음 (Sprint 2 한 PR로 `kortravelmap.providers.knps`
    모듈 작성 + Dagster asset 11종).
  - knps-api의 SHP/GeoJSON parser placeholder는 본 라이브러리에서 처리
    가능 — Sprint 2 진입 시 양쪽 어디에 둘지 cost/benefit 평가 후 결정.
  - ADR-027 정합 (LODGING_MOUNTAIN_SHELTER + area_kind=hazard_zone + generic
    notice_type) — knps-api 측에서 이미 정확히 반영 (PR#1로 maki icon 마저
    정정).
  - 양방향 PR 워크플로로 명명/매핑 drift 0.

- **결과 (부정)**:
  - 외부 repo 의존 — knps-api에 breaking change가 생기면 본 라이브러리도
    영향. 단, 본 사용자 직접 운영 저장소이므로 통제 가능. fragile 시
    `pyproject.toml` git URL을 commit sha로 핀.
  - SHP/GeoJSON parsing 위치 결정이 Sprint 2로 연기 — 본 라이브러리에서
    하면 `pyproj`/`pyshp` 의존 추가, knps-api에서 하면 본 라이브러리는
    `FeatureBundle` 입력만 받음. 양쪽 모두 가능, Sprint 2에서 결정.

- **후속**:
  - `docs/etl/forest-feature-etl.md §11` 갱신 (본 PR#12) — knps-api scaffold
    완료 명기 + 공개 API 표면 (`KnpsClient` 등) 명기.
  - `docs/etl/knps-feature-etl.md` 신설 (본 PR#12) — feature 적재 계약.
  - `docs/architecture/provider-contract.md` 갱신 (본 PR#12):
    - §2 `CANONICAL_PROVIDER_NAMES`에 `python-knps-api` 추가.
    - §3 dataset_key 표에 14건 추가.
    - §4 책임 매트릭스에 한 줄 추가.
  - `docs/external-apis.md` §2 환경변수 카탈로그 (본 PR#12):
    - `KNPS_SERVICE_KEY` 추가 (`python-knps-api` 우선)
    - `DATA_GO_KR_SERVICE_KEY` 비고에 KNPS 폴백 명기.
  - `docs/external-apis.md` §3 provider별 발급 절차 (본 PR#12):
    - §3.13 KNPS 신설 — data.go.kr "국립공원공단" 검색 → API 활용 신청
      → `KNPS_SERVICE_KEY` 환경변수.
  - `pyproject.toml` `providers` extras에 git URL 주석 (본 PR#12).
  - upstream knps-api PR#1 (`docs/knps-feature-maki-icons`) merge 후 본
    라이브러리 동기.
  - T-018 시점에 ADR-027/ADR-028 모두 `accepted` 전환 + 코드 적용 PR.
  - Sprint 2에서 SHP/GeoJSON parsing 책임 위치 결정 (`kortravelmap.providers.
    knps` vs knps-api `[geo]` extra).

### H. Amendment 2026-05-25 (keyless + file-only, knps-api PR#3+PR#4 merged)

knps-api 측 변경 (commit `06da125f`, PR#4 `codex/keyless-file-download-dtos`
merged 2026-05-25):

1. **PR#3 (`aa40541` Remove KNPS OpenAPI surface)** — data.go.kr OpenAPI/REST
   endpoint 표면 전체 삭제. `ApiEndpoint`/`api_endpoint`/`api_endpoints`/
   `raw_endpoint`/`Page` 클래스/함수 모두 제거. 카탈로그는 14건 모두
   `kind="file_dataset"`로 통일.
2. **PR#4 (`3269f22`+`3cac75e`+`80c17ed`)** — keyless file artifact DTOs
   추가. `FileArtifact`/`FileMember`/`CsvPreview`/`CsvPreviewRow` 모델 추가.
   `client.files.inspect_bytes()` / `client.files.download_artifact()` 메서드
   추가. `KnpsConfig`에서 `service_key`/`api_key` 필드 + `from_env` ENV 읽기
   완전 제거 — `timeout` + `max_rps`만 남음.

본 라이브러리 영향 (PR#25 일괄 반영):

- **A 갱신 — provider 등록**:
  - 인증 env 제거 — `KNPS_SERVICE_KEY` / `DATA_GO_KR_SERVICE_KEY` 사용 안 함.
    `external-apis.md §3.8.1`에서 auth 단계 삭제, "data.go.kr 직접 다운로드
    URL (keyless)" 명기.
  - 공개 API import 목록 정정:
    ```python
    # 신규 (삭제: ApiEndpoint, Page, api_endpoint, api_endpoints)
    from knps import (
        KnpsClient, KnpsConfig, CatalogEntry, FileDataset,
        FileArtifact, FileMember, CsvPreview, CsvPreviewRow,
        PROVIDER_NAME, KnpsApiError, KnpsAuthError, KnpsNoDataError,
        KnpsParseError, KnpsRateLimitError, KnpsRequestError, KnpsServerError,
        catalog_entries, file_dataset, file_datasets,
    )
    ```
  - `KnpsClient` 생성: `KnpsClient(timeout=10.0, max_rps=5.0)` 또는
    `KnpsClient.from_env(...)` (env var 읽지 않음, alias). authentication 인자
    없음.

- **F 갱신 — 14 dataset_key 카탈로그**:
  - **모두 file_dataset** (API endpoints 0건). 이전 §F의 "API endpoints (3)
    /File datasets (11)" 분류 무효.
  - 신규 verified 카탈로그 (knps-api `FILE_DATASETS` 14건):
    | key | data.go.kr ID | feature.kind | verification |
    |-----|---------------|--------------|--------------|
    | `knps_park_boundaries` | `15017313` | area (MultiPolygon) | verified |
    | `knps_trails` | `15003467` | route (LineString) | verified |
    | `knps_visitor_centers` | `15003445` | place (Point) | verified |
    | `knps_hazard_zones` | `15003441` | area (Polygon) | verified |
    | `knps_weather_stations` | `15090557` | weather (Point) | verified |
    | `knps_restrooms` | `15003468` | place (Point) | verified |
    | `knps_cultural_resources` | `15003443` | place (Point) | verified |
    | `knps_campgrounds` | `15003469` | place (Point) | verified |
    | `knps_shelters` | `2982556` | place (Point) | verified |
    | `knps_linear_facilities` | `15091972` | route (LineString) | verified |
    | `knps_basic_statistics` | `15087598` | timeseries | needs_verification |
    | `knps_visitor_statistics` | `15107577` | timeseries | verified |
    | `knps_protected_areas` | `15127921` | area (Polygon) | verified |
    | `knps_lod_table_catalog` | `15118945` | metadata | verified |
  - **삭제된 이전 keys** (knps-api에 더 이상 없음): `knps_access_restrictions`,
    `knps_fire_alerts`, `knps_recommended_courses`, `knps_park_photos`.
    이 중 `access_restriction`/`fire_alert` notice는 다른 provider
    (`python-krforest-api`, 산림청 산불경보) 또는 web scraping으로 보완 — 별도
    ADR로 결정 (KNPS 단독 source 아님).
  - 신규 dataset 구현을 위해 DTO 표준값도 확장:
    `AreaDetail.area_kind='protected_area'`,
    `RouteDetail.route_type='facility_road'`.

- **G 신규 — file artifact API 사용 패턴**:
  ```python
  async with KnpsClient(max_rps=5.0) as client:
      # raw bytes — 본 라이브러리의 SHP/CSV parser에 직접 공급
      data: bytes = await client.files.download("knps_park_boundaries")
      # 또는 preview용 (debug UI / 디버깅)
      artifact: FileArtifact = await client.files.download_artifact(
          "knps_trails", preview_rows=5,
      )
      for csv in artifact.csv_previews:
          print(csv.member_name, csv.encoding, csv.headers, csv.rows[:1])
  ```
  - ~~SHP/GeoJSON parsing은 여전히 본 라이브러리 책임~~ → **Amendment I로 정정
    (2026-05-29)**: SHP/CSV 파싱·geometry 추출은 **knps-api 책임** (ADR-044).

- **pyproject.toml `providers` extras**: git URL 핀 active 권고 (코드 작성
  단계 진입):
  ```toml
  "python-knps-api @ git+https://github.com/digitie/python-knps-api.git@06da125f",
  ```

**근거**:
- knps-api 외부 repo가 keyless로 단순화 → 본 라이브러리는 ENV var/auth wiring
  부담 0 (test fixture에서도 API key mock 불필요).
- 14 dataset 모두 verified status → Sprint 3 KNPS 적재 시 needs_verification
  대응 코드 분기 1건 (`knps_basic_statistics`)만.
- notice 도메인 (`access_restriction`/`fire_alert`) 공급원이 knps에서 사라짐
  → ADR-027 generic notice_type은 다른 provider (산림청 RSS, KFS 공시 등)
  에서 채울 수 있도록 후속 ADR (TBD)에서 명시.

**후속 (본 amendment 적용 PR#25)**:
- `docs/etl/knps-feature-etl.md` 재작성 (API endpoints 섹션 삭제, 14 file dataset
  표 갱신, 인증 단계 삭제, FileArtifact API 사용 예시 추가).
- `docs/etl/forest-feature-etl.md §11` 동기 (provider 공개 API 표면 정정, auth env
  삭제).
- `docs/external-apis.md §3.8.1` 정정 (keyless, ServiceKey 단계 삭제).
- `docs/architecture/provider-contract.md` (해당 시) — dataset_key 14건 갱신.
- `pyproject.toml` knps git URL 핀 활성화.
- 후속 ADR (TBD): `access_restriction`/`fire_alert` notice source 결정.

### I. Amendment 2026-05-29 (SHP/CSV 파싱 책임 = knps-api, 결정 B 확정)

§B에서 Sprint 2로 연기했던 "SHP/GeoJSON parsing 위치"를 사용자 결정(2026-05-29)
으로 확정: **raw 파일(SHP ZIP / CSV) → typed record(좌표·geometry WKT 4326)
파싱은 knps-api 책임** (ADR-044 — 데이터 정합성·파싱의 1차 책임은 provider
라이브러리). 본 라이브러리 `providers/knps`는 그 결과를 Protocol로 **소비**만.

- **분계**:
  - knps-api: SHP(ZIP) geometry 디코딩, CP949/euc-kr 인코딩, EPSG:5179→4326
    좌표 변환, geometry를 **WKT(4326)**로 노출. 미구현 시 upstream PR (ADR-025
    보강 패턴, knps-api `[geo]` extra 활용).
  - 본 lib: `KnpsPointRecord`(좌표) / `KnpsGeometryRecord`(geom WKT) Protocol로
    소비 → `Feature` 정규화. geometry 검증·centroid·DTO 조립은
    `core/geometry.py`(shapely). **`pyshp`/SHP 디코딩은 본 lib 의존 아님.**
- **이미 구현 (PR#77/#78)**: `knps_point_records_to_bundles`(place 5건) +
  `knps_geometry_records_to_bundles`(route/area 5건, WKT 입력) + `Feature.geom`
  필드 + `feature_repo` geom 적재. 변환 함수가 처음부터 WKT/좌표 입력이라 본
  amendment로 인한 본 lib **코드 변경 없음** — 문서/주석 정합만.
- **근거**: ADR-006(provider raw, 본 lib 변환)의 "raw"를 ADR-044 기준으로
  "parsed typed record"까지 provider 책임으로 당김 — 형제 provider(kma/opinet/
  datagokr 등)가 모두 typed model을 노출하는 패턴과 일치. SHP byte 핸들링/GDAL
  계열 의존을 provider에 가두어 본 lib 의존 스택을 가볍게 유지.
- **후속**: `docs/etl/knps-feature-etl.md §5` + `providers/knps.py` docstring +
  `docs/tasks.md`/`docs/resume.md` 정합 (본 PR). knps-api 측 record 파싱 API
  (예: `client.files.parse_records(key)`)는 Sprint 3 적재 직전 upstream PR.
