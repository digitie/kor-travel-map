# debug-ui-admin-workflows.md - 디버그 UI + Admin 운영 콘솔 구현 사양

본 문서는 `krtour-map-admin`를 **디버그 UI이자 admin/운영 콘솔**로 구현하기
위한 상세 사양이다. `docs/debug-ui-package.md`는 패키지 경계와 라우터 정책의
기준이고, 본 문서는 실제 화면, API, 진행 상태, 검토 흐름을 AI agent가 바로
구현할 수 있도록 풀어 쓴 작업 지시서다.

관련 결정:

- ADR-005: 인증 없음, 내부망/네트워크 계층 보호.
- ADR-020: 메인 라이브러리와 별도 Python 패키지.
- ADR-031: OpenAPI export drift gate.
- ADR-035: debug UI를 프로덕션 admin/유지보수 UI로도 운영.
- ADR-037: frontend 서버 상태는 TanStack Query, 클라이언트 상태는 Zustand.
- ADR-039: write/bulk/restore 계열 명령은 PostgreSQL advisory lock.
- ADR-045: Docker 독립 프로그램, 독립 DB/Dagster, TripMate OpenAPI 연동.

## 1. 목표

`krtour-map-admin`는 ADR-045 이후 단순 보조 UI가 아니라 Docker에서 실행되는
krtour-map 독립 프로그램의 admin frontend/backend다. TripMate와는 OpenAPI로
통신하고, 자체 PostgreSQL/PostGIS DB와 자체 Dagster를 가진다.

`krtour-map-admin`는 다음 업무를 한 화면 체계에서 처리한다.

1. 모든 `Feature`를 목록/지도에서 확인하고 검색, 필터, 소팅, 페이지 크기 변경을
   지원한다.
2. 운영자가 `Feature`를 수동 추가하고, 기존 feature를 비활성화하거나 영구 삭제할
   수 있다.
3. provider를 강제로 호출해 preview, dry-run, 실제 적재를 수행하고 진행률과 로그를
   확인한다.
4. provider별 상태, cursor, 최근 성공/실패, 다음 실행 시각, 결측/중복 발생량을
   확인한다.
5. provider 적재 중 발생한 중복 후보와 결측/정합성 이슈를 지도 뷰와 테이블 뷰로
   검토하고 처리한다.
6. 오프라인 파일을 업로드해 schema/좌표/주소/중복 검증을 수행하고, 검증/적재 진행률
   확인과 취소를 지원한다.
7. feature 상세 화면에서 원천 payload, 위치, 주변 feature, source link, 파일,
   정합성 이슈, 수동 override를 한 번에 확인한다.
8. OpenAPI로 Dagster feature update request를 만들고, 특정 feature/좌표 반경/시군구
   범위/provider dataset 업데이트를 즉시 실행하거나 큐에 넣는다.
9. 외부 앱 POI/cache target을 고유 key + 좌표로 등록하고, key 기준 주변 feature 조회와
   targeted cache update를 수행한다.

## 2. 비목표와 금지 사항

- 인증, 세션, 권한을 애플리케이션 코드에 넣지 않는다. 접근 제어는 Cloudflare
  Tunnel, SSO gateway, IP allowlist, SSH tunnel 등 네트워크 계층 책임이다.
- TripMate 사용자용 지도 UI를 만들지 않는다. 본 UI는 개발자/운영자 전용이다.
- 메인 패키지 `krtour.map`에 FastAPI, Uvicorn, React, Next.js 의존을 추가하지
  않는다.
- provider wrapper, adapter, gateway를 만들지 않는다. `python-*-api` public client와
  typed model을 직접 사용하고, 본 라이브러리는 raw/model -> DTO 변환과 적재만
  담당한다.
- frontend에서 DB에 직접 접근하지 않는다. 모든 접근은 backend REST API를 통한다.
- destructive action을 batch로 먼저 열지 않는다. 비활성화/영구삭제는 단건부터
  구현하고, batch action은 운영 로그와 undo 정책이 정리된 뒤 별도 PR로 확장한다.

## 3. 라우터 prefix 정책

기존 ADR-035 prefix를 따른다.

| Prefix | 용도 | 예 |
|--------|------|----|
| `/debug/...` | 개발자용 진단, fixture, EXPLAIN, provider preview | `/debug/etl/...`, `/debug/geocoding/...` |
| `/features/...` | 지도/상세에서 공통으로 쓰는 feature 조회 | `/features`, `/features/{feature_id}`, `/features/nearby` |
| `/admin/...` | 운영자가 데이터를 변경하거나 작업을 실행하는 기능 | `/admin/features`, `/admin/import-jobs`, `/admin/providers/.../runs` |
| `/ops/...` | 관측, 로그, 지표, consistency report | `/ops/error-logs`, `/ops/consistency`, `/ops/metrics` |

기존 구현 주의:

- 현재 `GET /features`는 bbox 기반 지도 목록으로 구현되어 있다. 이 계약을 깨지
  않는다.
- 전역 검색/소팅/페이지네이션용 admin 목록은 `GET /admin/features`로 새로 둔다.
- 새 `/admin/*`, `/ops/*` 라우터는 OpenAPI export를 동반한다.

## 4. Frontend 정보 구조

Frontend 표준 stack:

- Next.js 16 App Router + React 19 + TypeScript.
- TanStack Query: `/features`, `/admin`, `/ops`, `/debug` 서버 상태와 mutation.
- Zustand: map viewport, 지도/테이블 view mode, filter draft, selected feature,
  offline upload wizard 같은 클라이언트 상태.
- Zod: API 응답 parsing, 좌표/bbox, form schema 검증.
- React Hook Form: 수동 feature 추가, provider 실행, offline upload, issue resolve
  같은 form 상태.
- shadcn/ui: Button, Input, Select, Dialog, Sheet, Tabs, Table, Badge, Toast,
  Form, DropdownMenu 등 공통 UI primitive.
- `maplibre-vworld-js`: VWorld 지도.
- `@krtour/map-marker-react`: category/maki marker.

Frontend 작업 후에는 `react-doctor` 실행, 결과 검토, 개선 반영이 필수다. 자세한
명령과 완료 기준은 `docs/openapi-admin-contract.md` §10.

### 4.1 주요 페이지

| Route | 목적 | 기본 API |
|-------|------|----------|
| `/` | 운영 홈. 최근 job, provider 실패, 열린 이슈, dedup pending 요약 | `/admin/dashboard`, `/ops/error-logs` |
| `/features` | feature 운영 목록. 지도/테이블 전환 | `/admin/features`, `/features`, `/features/nearby` |
| `/features/new` | 수동 feature 추가 | `POST /admin/features` |
| `/features/[feature_id]` | 상세, 위치, 주변 feature, 원천, 이슈, 조치 | `/features/{feature_id}`, `/features/nearby` |
| `/admin/providers` | provider별 상태 목록 | `/admin/providers` |
| `/admin/providers/[provider]` | provider 상세, dataset 상태, 강제 호출 | `/admin/providers/{provider}` |
| `/admin/import-jobs` | 적재/검증 job 목록 | `/admin/import-jobs` |
| `/admin/import-jobs/[job_id]` | 진행률, 단계별 로그, 취소 | `/admin/import-jobs/{job_id}` |
| `/admin/dedup-review` | 중복 후보 검토 | `/admin/dedup-review` |
| `/admin/issues` | 이슈 있는 feature 지도/테이블 | `/admin/issues/features` |
| `/admin/offline-imports` | 오프라인 파일 업로드, 검증, 적재 | `/admin/offline-uploads` |
| `/admin/feature-update-requests` | 좌표/반경/시군구/provider 기준 업데이트 요청 | `/admin/feature-update-requests` |
| `/admin/poi-cache-targets` | 외부 POI/cache target 등록/삭제/정책 관리 | `/admin/poi-cache-targets` |
| `/admin/provider-refresh-policies` | provider별 update 주기/rate limit 정책 | `/admin/provider-refresh-policies` |
| `/ops/error-logs` | provider/API/job 에러 로그 | `/ops/error-logs` |
| `/ops/consistency` | consistency report와 위반 샘플 | `/ops/consistency/reports` |
| `/debug/etl` | provider 변환 preview | 기존 `/debug/etl/*` |
| `/debug/geocoding` | kraddr-geo reverse/geocode 점검 | 기존 `/debug/geocoding/*` |

### 4.2 네비게이션 그룹

- **Features**: `/features`, `/features/new`, `/admin/issues`.
- **Providers**: `/admin/providers`, provider 상세, provider 강제 실행.
- **Jobs**: `/admin/import-jobs`, job 상세, offline upload job.
- **Review**: `/admin/dedup-review`, missing data queue, consistency samples.
- **Ops**: `/ops/error-logs`, `/ops/consistency`, `/ops/metrics`.
- **Debug**: `/debug/etl`, `/debug/geocoding`, `/debug/explain`, `/debug/fixtures`.

## 5. 공통 UX 규칙

### 5.1 지도와 테이블 전환

Feature 검토 화면은 항상 지도 뷰와 테이블 뷰를 전환할 수 있어야 한다.

- 뷰 전환 상태는 URL query와 Zustand에 동시에 반영한다.
  - 예: `/features?view=map&status=active&kind=place`
  - 예: `/features?view=table&q=국립공원&page_size=100`
- 지도 뷰에서는 현재 지도 중심점과 bbox가 1차 기준이다.
- 테이블 뷰에서는 `name asc`가 기본 정렬이다.
- 테이블 뷰는 검색어, 소팅, 페이지 크기 변경이 즉시 가능해야 한다.
- 같은 필터 상태에서 지도 뷰와 테이블 뷰를 오가도 선택 feature와 검색 조건이
  유지되어야 한다.

### 5.2 페이지 크기

테이블 페이지 크기 옵션:

```
25, 50, 100, 200, 500
```

기본값은 `50`이다. 운영자가 고른 값은 URL query `page_size`와 localStorage에 저장한다.
500을 넘는 대량 다운로드는 UI 목록이 아니라 별도 export job으로 처리한다.

### 5.3 검색/필터/정렬 query 표준

모든 목록 API는 가능한 한 같은 query 이름을 쓴다.

| Query | 의미 |
|-------|------|
| `q` | 이름, 주소, feature_id, source id 부분 검색 |
| `kind` | 반복 가능. `place`, `event`, `notice`, `price`, `weather`, `route`, `area` |
| `category` | 8자리 category code. 반복 가능 |
| `status` | `draft`, `active`, `inactive`, `hidden`, `broken`, `deleted` |
| `provider` | canonical provider name |
| `dataset_key` | provider dataset key |
| `issue_type` | 결측/중복/정합성 이슈 타입 |
| `severity` | `info`, `warning`, `error`, `critical` 또는 `OK`, `WARN`, `ERROR` |
| `page_size` | 25, 50, 100, 200, 500 |
| `cursor` | keyset pagination cursor |
| `sort` | 정렬 컬럼 |
| `order` | `asc` 또는 `desc` |

offset pagination은 초기 구현에서는 허용할 수 있으나 MOIS bulk 이후 큰 테이블에서는
느려진다. 최종 목표는 keyset cursor다.

### 5.4 공통 상태 표시

목록과 상세에는 다음 badge를 공통으로 노출한다.

- `status`: active, inactive, hidden, broken, deleted.
- `kind`: place, event, notice, price, weather, route, area.
- `provider`: primary source provider.
- `issues`: duplicate pending, missing coordinate, missing address, consistency
  warning, provider failed, manual override.
- `updated_at`: 마지막 갱신 시각, KST 표시.
- `last_updated_at`: API 응답에 항상 포함하는 KST aware 최신 갱신 시각.

목록 API는 `feature.detail` JSONB, source raw payload, file payload를 반환하지 않는다.
이 값은 `GET /features/{feature_id}` 같은 상세 API에서만 반환한다.

## 6. Feature 운영 목록

### 6.1 Backend API

#### `GET /admin/features`

전역 feature 검색, 필터, 정렬, 페이지네이션.

Query:

| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `q` | string | 없음 | `name`, 주소 JSON, `feature_id`, source id 검색 |
| `kind` | string[] | 전체 | feature kind 반복 파라미터 |
| `category` | string[] | 전체 | category code 반복 파라미터 |
| `status` | string[] | `active` | status 반복 파라미터 |
| `provider` | string[] | 전체 | primary source provider |
| `dataset_key` | string[] | 전체 | source dataset |
| `has_coord` | boolean | 없음 | 좌표 보유 여부 |
| `has_issue` | boolean | 없음 | 열린 이슈 보유 여부 |
| `issue_type` | string[] | 전체 | 이슈 타입 |
| `updated_from` | datetime | 없음 | KST aware |
| `updated_to` | datetime | 없음 | KST aware |
| `page_size` | int | 50 | 25/50/100/200/500 |
| `cursor` | string | 없음 | keyset cursor |
| `sort` | string | `name` | `name`, `updated_at`, `created_at`, `kind`, `status`, `provider`, `issue_count` |
| `order` | string | `asc` | `asc`, `desc` |

응답:

```json
{
  "data": {
    "items": [
      {
        "feature_id": "f_1111010100_p_abcd1234...",
        "kind": "place",
        "name": "광화문",
        "category": "01070300",
        "status": "active",
        "lon": 126.9769,
        "lat": 37.5759,
        "address_label": "서울특별시 종로구 ...",
        "primary_provider": "python-krheritage-api",
        "primary_dataset_key": "krheritage_heritage_features",
        "issue_count": 0,
        "issues": [],
        "updated_at": "2026-06-01T10:12:00+09:00"
      }
    ],
    "next_cursor": "opaque-cursor-or-null"
  },
  "meta": {
    "count": 50,
    "page_size": 50,
    "sort": "name",
    "order": "asc",
    "duration_ms": 18
  }
}
```

정렬 규칙:

- `sort=name&order=asc`는 한글 이름순을 기본으로 한다.
- 같은 이름이면 `feature_id asc`로 tie-break한다.
- `sort=updated_at`은 `updated_at, feature_id` keyset을 쓴다.
- `sort=issue_count`는 열린 이슈 수 desc가 기본이다.

검색 규칙:

- `q`는 빈 문자열이면 무시한다.
- 한글/영문 NFKC 정규화 후 검색한다.
- 이름 검색은 `pg_trgm` 인덱스를 활용한다.
- 주소 검색은 초기에는 JSONB text cast + trigram 또는 별도 generated column 중
  구현 난이도 낮은 방식을 선택하되, EXPLAIN에서 seq scan이 나오면 별도 인덱스
  설계를 추가한다.

### 6.2 Frontend 테이블

필수 컬럼:

- 이름
- kind
- category 표시명
- status
- 주소 요약
- primary provider
- issue badge
- updated_at
- actions

테이블 row click:

- 기본 동작은 `/features/{feature_id}` 상세로 이동.
- `Ctrl`/`Cmd` click은 새 탭 허용.

Row actions:

- 상세 보기
- 지도에서 보기
- 비활성화
- 영구 삭제

비활성화/영구 삭제 버튼은 row hover만으로 숨기지 말고 actions 메뉴에 둔다. 실수 클릭을
막기 위해 destructive action은 확인 모달을 반드시 거친다.

## 7. Feature 지도 목록

### 7.1 기존 `GET /features`

현재 구현된 bbox 목록 API는 지도 뷰의 기본 데이터 소스다.

필수 query:

- `min_lon`
- `min_lat`
- `max_lon`
- `max_lat`

선택 query:

- `kind` 반복 파라미터
- `limit`
- 후속 확장: `status`, `category`, `issue_type`

지도 뷰는 bbox 이동/zoom 변화 시 TanStack Query로 refetch한다. frontend는 좌표를
소수 4자리 정도로 양자화해 지나친 refetch를 줄인다.

### 7.2 `GET /features/nearby`

중심점 주변 feature 조회. feature 상세 검토와 지도 중심 주변 목록에서 사용한다.

Query:

| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `lon` | number | 필수 | WGS84 longitude |
| `lat` | number | 필수 | WGS84 latitude |
| `radius_m` | int | 500 | 50, 100, 250, 500, 1000, 3000 |
| `kind` | string[] | 전체 | 반복 가능 |
| `status` | string[] | `active` | 반복 가능 |
| `exclude_feature_id` | string | 없음 | 현재 feature 제외 |
| `limit` | int | 200 | 최대 500 |
| `sort` | string | `distance` | `distance`, `name`, `updated_at` |

성능 규칙:

- 입력 좌표는 CTE에서 한 번만 `ST_Transform`한다.
- 술어는 `feature.features.coord_5179`에 대해 `ST_DWithin`을 사용한다.
- `ST_Transform(feature.features.coord, ...)`를 술어 안에 넣지 않는다.

## 8. Feature 수동 추가

### 8.1 화면

Route: `/features/new`

폼 섹션:

1. 기본 정보
   - kind
   - name
   - category
   - status: 기본 `draft`, 운영자가 바로 노출하려면 `active`
2. 위치
   - lon/lat 직접 입력
   - 지도 클릭으로 좌표 지정
   - 주소 입력 후 geocode
   - 좌표 입력 후 reverse geocode
3. 주소
   - `Address` DTO 필드
   - 법정동코드, 시도/시군구 code 자동 보강
4. 상세
   - kind별 detail form
   - `PlaceDetail`, `EventDetail`, `NoticeDetail`, `RouteDetail`, `AreaDetail`
5. 출처
   - provider는 항상 `manual`
   - operator memo
   - 원천 URL 또는 참고 메모

### 8.2 Backend API

#### `POST /admin/features`

수동 feature 생성.

요청:

```json
{
  "kind": "place",
  "name": "수동 등록 장소",
  "category": "01070300",
  "status": "draft",
  "coord": {"lon": 126.978, "lat": 37.5665},
  "address": {},
  "detail": {},
  "urls": {},
  "operator": "local-admin",
  "reason": "현장 확인 후 수동 등록",
  "source_note": "운영자 입력"
}
```

처리 규칙:

- `provider='manual'`, `dataset_key='manual_features'`인 `SourceRecord`를 생성한다.
- `source_entity_type='manual_feature'`.
- `source_entity_id`는 서버가 생성한 UUID를 사용한다.
- `make_feature_id(...)`를 사용한다. raw string concat 금지.
- `bjd_code`가 있으면 feature_id bucket에 사용하고, 없으면 `global` fallback을
  허용하되 `missing_bjd_code` issue를 남긴다.
- detail은 자유 dict가 아니라 kind별 Pydantic detail 모델 검증을 반드시 통과해야 한다.
- `SourceLink.source_role='primary'`, `match_method='manual'`,
  `confidence=100`, `is_primary_source=true`.
- 생성 직후 중복 후보 검색을 실행하고 후보가 있으면 `ops.dedup_review_queue`에
  넣는다.

응답:

```json
{
  "data": {
    "feature_id": "f_1111010100_p_...",
    "dedup_candidates": 2,
    "issues": ["missing_bjd_code"]
  },
  "meta": {"duration_ms": 42}
}
```

검증 실패:

- 422: DTO validation error.
- 409: 동일 manual source key 또는 feature_id 충돌.

## 9. Feature 비활성화와 영구 삭제

### 9.1 비활성화

#### `POST /admin/features/{feature_id}/deactivate`

요청:

```json
{
  "reason": "운영상 노출 제외",
  "operator": "local-admin",
  "prevent_provider_reactivation": true
}
```

처리 규칙:

- `feature.features.status='inactive'`로 변경한다.
- `deleted_at`은 설정하지 않는다.
- source records, source links, files, history는 유지한다.
- `prevent_provider_reactivation=true`이면 `ops.feature_overrides`에
  `field_path='status'`, `override_value='"inactive"'`를 active 상태로 남긴다.
  후속 provider 재적재가 status를 다시 active로 덮지 못해야 한다.
- reason은 필수다.

응답에는 변경 전/후 status와 override 생성 여부를 포함한다.

### 9.2 영구 삭제

#### `DELETE /admin/features/{feature_id}`

영구 삭제는 되돌리기 어렵다. UI는 두 단계 확인을 요구한다.

1. 확인 모달에서 영향 범위 표시:
   - source_links cascade 수
   - feature_files 수
   - weather/price/detail rows 수
   - dedup queue references 수
2. `feature_id` 전체를 입력해야 삭제 버튼 활성화.

Query:

| 이름 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `dry_run` | boolean | `true` | true면 영향 범위만 반환 |

요청 body:

```json
{
  "operator": "local-admin",
  "reason": "잘못 등록된 테스트 데이터 영구 제거",
  "confirm_feature_id": "f_1111010100_p_..."
}
```

처리 규칙:

- `dry_run=true`가 기본이다. frontend는 dry-run 결과를 먼저 보여준 뒤 실제 삭제를
  다시 호출한다.
- active feature 삭제는 extra confirmation을 요구한다. 가능하면 먼저 inactive로
  전환하도록 안내한다.
- 실제 삭제는 `feature.features` row delete를 기준으로 하며 FK cascade 정책을 따른다.
- `provider_sync.source_records`는 삭제하지 않는다. 원천 row 보존이 필요하다.
- 삭제 이력은 `ops.feature_merge_history`가 아니라 별도 audit/event log가 필요하다.
  구현 전 `ops.admin_audit_log` 테이블 추가를 검토한다.

스키마 gap:

- 현재 data model에는 일반 admin audit log가 없다. destructive action 구현 전
  `ops.admin_audit_log` 추가가 권장된다.

## 10. Feature 상세

Route: `/features/[feature_id]`

### 10.1 필수 섹션

1. Header
   - name, feature_id, kind, category, status, primary provider, updated_at.
2. 위치
   - `maplibre-vworld-js` 지도.
   - 선택 feature marker.
   - 주변 feature marker.
   - 좌표 없음이면 "좌표 없음" 상태와 주소/geocode action.
3. 상세 데이터
   - kind별 detail JSON을 읽기 좋은 form/table로 표시.
   - raw JSON toggle 제공.
4. 주소
   - `Address` DTO 직렬화 결과.
   - legal/admin dong code.
   - reverse/geocode 재검증 버튼.
5. 원천
   - source links.
   - source records.
   - raw payload hash.
   - fetched/imported time.
6. 파일
   - primary/thumbnail/gallery.
   - RustFS object key, public_url, checksum, dimensions.
7. 이슈
   - 열린 missing/consistency/dedup issue.
   - 처리 action.
8. 변경/운영 이력
   - manual override.
   - deactivate/delete audit.
   - provider job references.

### 10.2 주변 feature 검토

상세 화면에는 "주변 feature" 패널을 둔다.

지도 뷰:

- 중심점은 현재 feature 좌표다.
- 기본 반경은 500m.
- 반경 옵션: 50m, 100m, 250m, 500m, 1000m, 3000m.
- marker 색상:
  - 현재 feature: 강조색.
  - 중복 후보: warning 색.
  - 이슈 보유: error 색.
  - 일반 주변 feature: category marker color.

테이블 뷰:

- 기본 정렬은 `name asc`.
- 검색 가능.
- sort: `name`, `distance`, `kind`, `category`, `status`, `provider`, `updated_at`.
- row action: 상세 열기, dedup 후보로 추가, keep separate 표시.

## 11. Provider 상태와 강제 호출

### 11.1 Provider 목록

Route: `/admin/providers`

#### `GET /admin/providers`

provider별 요약 상태.

응답 item:

```json
{
  "provider": "python-mois-api",
  "display_name": "MOIS 인허가",
  "status": "active",
  "datasets_total": 4,
  "datasets_failed": 1,
  "last_success_at": "2026-06-01T02:10:00+09:00",
  "last_failure_at": "2026-06-01T04:11:00+09:00",
  "consecutive_failures": 2,
  "next_run_after": "2026-06-02T02:00:00+09:00",
  "running_jobs": 1,
  "pending_jobs": 0,
  "open_issues": 182,
  "pending_dedup_reviews": 391,
  "required_secret_status": "missing"
}
```

`required_secret_status`는 값을 노출하지 않는다.

- `ok`: 필요한 key가 설정됨.
- `missing`: 필요한 key 없음.
- `not_required`: keyless provider.
- `unknown`: 아직 provider metadata 없음.

### 11.2 Provider 상세

Route: `/admin/providers/[provider]`

섹션:

- provider metadata
- dataset별 sync state
- 최근 import jobs
- 최근 API error logs
- 최근 source row count
- 결측/중복/정합성 issue summary
- 강제 실행 form

#### `GET /admin/providers/{provider}`

응답에는 dataset별 `ProviderSyncState`를 포함한다.

```json
{
  "data": {
    "provider": "python-mois-api",
    "datasets": [
      {
        "dataset_key": "mois_license_features_bulk",
        "sync_scope": "kr",
        "status": "active",
        "cursor": {},
        "last_success_at": null,
        "last_failure_at": null,
        "consecutive_failures": 0,
        "next_run_after": null,
        "last_job": null,
        "last_counts": {
          "fetched": 0,
          "loaded": 0,
          "skipped_invalid": 0,
          "dedup_candidates": 0,
          "missing_required": 0
        }
      }
    ]
  },
  "meta": {"duration_ms": 12}
}
```

### 11.3 Provider 강제 호출 및 적재

#### `POST /admin/providers/{provider}/datasets/{dataset_key}/runs`

provider를 즉시 실행한다. preview, dry-run, load를 모두 이 endpoint에서 job으로
등록한다.

요청:

```json
{
  "mode": "load",
  "source": "live",
  "sync_scope": "kr",
  "params": {
    "limit": 1000,
    "sigungu_code": "11110"
  },
  "force": true,
  "operator": "local-admin",
  "reason": "MOIS 첫 bulk 샘플 적재"
}
```

필드:

| 이름 | 값 | 설명 |
|------|----|------|
| `mode` | `preview`, `dry_run`, `load` | preview는 변환 결과만, dry_run은 검증/중복까지, load는 DB 적재 |
| `source` | `live`, `fixture`, `offline` | live는 provider API, fixture는 저장 fixture, offline은 업로드 파일 |
| `sync_scope` | string | provider_sync_state PK scope |
| `params` | object | provider dataset별 파라미터 |
| `force` | boolean | next_run_after와 failure backoff 무시 |
| `operator` | string | 감사용 표시명. 보안 식별자 아님 |
| `reason` | string | 강제 실행 사유 |

응답:

```json
{
  "data": {
    "job_id": "c2ef3a84-...",
    "state": "queued",
    "status_url": "/admin/import-jobs/c2ef3a84-..."
  },
  "meta": {"duration_ms": 9}
}
```

처리 규칙:

- `mode=load`와 `source=live`는 advisory lock 대상이다.
- lock key 예: `krtour-map:import:python-mois-api:mois_license_features_bulk:kr`.
- 같은 provider/dataset/scope의 running job이 있으면 409를 반환한다.
- `force=true`는 schedule/backoff만 무시한다. advisory lock은 무시하지 않는다.
- provider client 호출은 provider 라이브러리 public API를 직접 사용한다.
- raw row, 변환 bundle, validation issue, dedup 후보 count를 job summary에 남긴다.

## 12. Import job 진행 상태

### 12.1 Job 상태

`ops.import_jobs.state` 값:

- `queued`
- `running`
- `done`
- `failed`
- `cancelled`

권장 단계(`current_stage`):

1. `queued`
2. `acquiring_lock`
3. `fetching`
4. `normalizing`
5. `validating`
6. `geocoding`
7. `dedup_scoring`
8. `loading`
9. `consistency_check`
10. `finalizing`
11. `done`

`progress`는 0-100 정수다. provider total count를 알 수 없으면 단계별 가중치를
사용한다.

권장 가중치:

| 단계 | 가중치 |
|------|--------|
| acquiring_lock | 2 |
| fetching | 30 |
| normalizing | 15 |
| validating | 15 |
| geocoding | 10 |
| dedup_scoring | 10 |
| loading | 15 |
| consistency_check | 3 |

### 12.2 Job 목록

#### `GET /admin/import-jobs`

Query:

- `state`
- `kind`
- `provider`
- `dataset_key`
- `created_from`
- `created_to`
- `page_size`
- `cursor`
- `sort=created_at|started_at|finished_at|progress`
- `order=desc|asc`

기본 정렬은 `created_at desc`.

### 12.3 Job 상세

#### `GET /admin/import-jobs/{job_id}`

응답:

```json
{
  "data": {
    "job_id": "c2ef3a84-...",
    "kind": "provider_import",
    "state": "running",
    "progress": 37,
    "current_stage": "fetching",
    "provider": "python-mois-api",
    "dataset_key": "mois_license_features_bulk",
    "sync_scope": "kr",
    "counts": {
      "fetched": 12000,
      "normalized": 11890,
      "loaded": 0,
      "skipped_invalid": 110,
      "dedup_candidates": 320,
      "missing_required": 40
    },
    "started_at": "2026-06-01T10:00:00+09:00",
    "heartbeat_at": "2026-06-01T10:04:11+09:00",
    "finished_at": null,
    "error_message": null,
    "recent_events": []
  },
  "meta": {"duration_ms": 8}
}
```

### 12.4 진행 상태 업데이트 방식

최소 구현:

- frontend가 `GET /admin/import-jobs/{job_id}`를 2초 간격으로 polling한다.
- tab focus 시 즉시 refetch한다.
- `state`가 terminal(`done`, `failed`, `cancelled`)이면 polling을 멈춘다.

후속 확장:

- `GET /admin/import-jobs/{job_id}/events`로 단계별 로그를 페이지네이션 조회.
- `GET /admin/import-jobs/{job_id}/stream` SSE로 progress/event streaming.

### 12.5 취소

#### `POST /admin/import-jobs/{job_id}/cancel`

요청:

```json
{
  "operator": "local-admin",
  "reason": "잘못된 scope로 실행"
}
```

처리 규칙:

- `queued` job은 즉시 `cancelled`.
- `running` job은 cooperative cancel이다.
- runner는 stage boundary와 row batch boundary마다 cancel flag를 확인한다.
- 이미 DB에 commit된 row는 자동 rollback되지 않는다. 취소 응답과 job summary에
  partial load 여부를 표시한다.
- cancellation flag는 schema 추가 전에는 `payload.cancel_requested_at`에 저장할 수
  있으나, 정식 구현 전 `ops.import_jobs.cancel_requested_at`,
  `cancel_requested_by`, `cancel_reason` 컬럼 추가를 권장한다.

## 13. 에러 로그 확인

### 13.1 Backend API

#### `GET /ops/error-logs`

provider API 호출, import job, validation, file upload 검증 중 발생한 에러를 한
곳에서 조회한다.

Query:

- `provider`
- `dataset_key`
- `job_id`
- `feature_id`
- `severity`
- `error_code`
- `from`
- `to`
- `q`
- `page_size`
- `cursor`

응답 item:

```json
{
  "log_id": "opaque",
  "occurred_at": "2026-06-01T10:04:00+09:00",
  "severity": "error",
  "provider": "python-mois-api",
  "dataset_key": "mois_license_features_bulk",
  "job_id": "c2ef3a84-...",
  "feature_id": null,
  "stage": "fetching",
  "error_code": "PROVIDER_TIMEOUT",
  "message": "MOIS API timeout",
  "details": {"page": 42, "retry": 3}
}
```

스키마 gap:

- 현재 `ops.api_call_log`는 provider API 호출 로그만 담기 좋고, job stage별 이벤트에는
  부족하다.
- 구현 전 `ops.import_job_events` 추가 권장:

```sql
CREATE TABLE ops.import_job_events (
  event_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  job_id UUID REFERENCES ops.import_jobs(job_id) ON DELETE CASCADE,
  provider TEXT,
  dataset_key TEXT,
  feature_id TEXT,
  stage TEXT,
  level TEXT NOT NULL, -- debug, info, warning, error
  code TEXT,
  message TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_import_job_events_job_time ON ops.import_job_events (job_id, occurred_at DESC);
CREATE INDEX idx_import_job_events_provider_time ON ops.import_job_events (provider, occurred_at DESC);
CREATE INDEX idx_import_job_events_level_time ON ops.import_job_events (level, occurred_at DESC);
```

## 14. 중복 후보 검토

### 14.1 Backend API

#### `GET /admin/dedup-review`

Query:

- `status`: 기본 `pending`
- `provider`
- `dataset_key`
- `kind`
- `category`
- `min_score`
- `max_score`
- `q`
- `bbox`
- `page_size`
- `cursor`
- `sort`: 기본 `total_score`
- `order`: 기본 `desc`

응답 item:

```json
{
  "review_key": "uuid",
  "status": "pending",
  "total_score": 87.2,
  "name_score": 91.0,
  "spatial_score": 82.0,
  "category_score": 100.0,
  "feature_a": {
    "feature_id": "f_...",
    "name": "같은 장소 A",
    "lon": 126.9,
    "lat": 37.5,
    "provider": "python-mois-api"
  },
  "feature_b": {
    "feature_id": "f_...",
    "name": "같은 장소 B",
    "lon": 126.9001,
    "lat": 37.5001,
    "provider": "python-datagokr-api"
  },
  "distance_m": 12.4,
  "created_at": "2026-06-01T11:00:00+09:00"
}
```

#### `PATCH /admin/dedup-review/{review_key}`

요청:

```json
{
  "decision": "merged",
  "master_feature_id": "f_master...",
  "decision_reason": "동일 장소로 확인",
  "reviewed_by": "local-admin"
}
```

`decision`:

- `accepted`: 중복으로 판단했으나 merge는 아직 하지 않음.
- `rejected`: 중복 아님.
- `merged`: master로 병합 완료.
- `ignored`: 현재는 판단하지 않음. 다시 열 수 있어야 한다.

처리 규칙:

- `merged`는 `feature_merge_history`를 남긴다.
- 병합 구현 전에는 `accepted`까지만 먼저 열어도 된다. 이 경우 UI에서 "merge
  pending"으로 표시한다.
- 병합은 destructive 성격이 있으므로 ADR-039 mutex `dedup-merge:{feature_id}`를
  적용한다.

### 14.2 UI

Dedup review는 split view가 기본이다.

- 좌측: 후보 목록.
- 우측: 두 feature 비교.
- 지도: 두 좌표와 거리 line.
- 상세 비교: name, category, address, phones, urls, provider, raw source.
- action: keep separate, duplicate accepted, merge into A, merge into B, ignore.

Keyboard shortcut은 후속으로만 추가한다. 초기 구현은 버튼 기반으로 충분하다.

## 15. 결측치와 정합성 이슈 처리

### 15.1 이슈 타입

Provider 적재와 consistency check는 다음 issue type을 생성하거나 집계한다.

| issue_type | 설명 | 일반 처리 |
|------------|------|-----------|
| `missing_coordinate` | 지도 표시 좌표 없음 | geocode, manual coord 입력, ignored |
| `missing_address` | 주소 없음 또는 파싱 실패 | reverse geocode, manual address 입력 |
| `missing_bjd_code` | 법정동코드 없음 | kraddr-geo 보강, manual code 입력 |
| `missing_category` | category 결정 실패 | category 선택 |
| `invalid_coordinate` | 한국 bbox 밖 또는 좌표 순서 의심 | 좌표 수정, source ignored |
| `detail_validation_error` | kind별 detail DTO 검증 실패 | provider 변환 수정 또는 source ignored |
| `duplicate_pending` | dedup review pending | dedup 처리 |
| `orphan_source_record` | source record가 feature와 연결되지 않음 | 재적재 또는 ignored |
| `provider_fetch_failed` | provider 호출 실패 | 재시도, key/limit 확인 |
| `file_validation_failed` | offline/file source 검증 실패 | 파일 수정 후 재업로드 |
| `stale_provider_sync` | sync가 오래 멈춤 | provider 강제 실행 |

### 15.2 Backend API

#### `GET /admin/issues/features`

이슈가 있는 feature만 모아서 조회한다. 지도/테이블 양쪽에서 사용한다.

Query:

- `issue_type`
- `severity`
- `provider`
- `dataset_key`
- `kind`
- `category`
- `status`
- `bbox` 또는 `min_lon/min_lat/max_lon/max_lat`
- `q`
- `view_mode`: `map` 또는 `table`
- `page_size`
- `cursor`
- `sort`
- `order`

기본 정렬:

- 지도 뷰: severity desc, distance asc 또는 updated_at desc.
- 테이블 뷰: `name asc`.

응답 item은 feature summary와 issue summary를 함께 반환한다.

#### `PATCH /admin/issues/{issue_key}`

결측/정합성 이슈 처리.

요청 예:

```json
{
  "action": "resolve",
  "resolution": {
    "field_path": "coord",
    "value": {"lon": 126.978, "lat": 37.5665}
  },
  "operator": "local-admin",
  "reason": "지도에서 수동 확인"
}
```

`action`:

- `resolve`
- `acknowledge`
- `ignore`
- `reopen`

스키마 주의:

- 현재 구현된 `ops.feature_consistency_reports`는 batch 집계 테이블이다.
- "이슈 1건 = 1행" 운영 큐가 필요하면 `ops.data_integrity_violations`를 실제
  마이그레이션으로 도입해야 한다. `docs/data-model.md §9.5`가 계획 스키마다.

### 15.3 UI

Route: `/admin/issues`

지도 뷰:

- 이슈 보유 feature만 표시한다.
- severity별 marker 강조:
  - critical/error: 빨강
  - warning: 주황
  - info: 회색
- marker 클릭 시 issue detail panel을 연다.
- 결측 좌표 feature는 지도에 직접 표시할 수 없으므로 별도 "좌표 없음" side list에
  노출한다.

테이블 뷰:

- 기본 이름순.
- 검색/소팅/페이지 크기 변경 가능.
- action column:
  - 상세
  - 지도에서 보기
  - 좌표/주소 보강
  - ignored 처리
  - provider 재실행

## 16. 오프라인 파일 업로드와 검증

### 16.1 목적

외부 API가 막혔거나 대량 원천 파일을 수동 확보한 경우, 운영자가 파일을 업로드해
provider 변환/검증/적재 파이프라인을 같은 방식으로 실행한다.

### 16.2 지원 파일 형식

초기 지원:

- CSV
- TSV
- JSON
- JSONL
- GeoJSON
- ZIP 압축 Shapefile

Shapefile ZIP 필수 구성:

- `.shp`
- `.shx`
- `.dbf`
- `.prj`

인코딩:

- UTF-8 우선.
- CP949/EUC-KR fallback은 가능하되 검증 결과에 감지 인코딩을 표시한다.

### 16.3 Backend API

#### `POST /admin/offline-uploads`

multipart upload.

필드:

- `file`: 업로드 파일.
- `provider`: canonical provider.
- `dataset_key`: dataset key.
- `sync_scope`: optional.
- `operator`: optional.
- `reason`: optional.

응답:

```json
{
  "data": {
    "upload_id": "uuid",
    "state": "uploaded",
    "checksum_sha256": "hex",
    "byte_size": 123456,
    "detected_format": "csv"
  },
  "meta": {"duration_ms": 120}
}
```

저장 위치:

- 개발 환경: gitignore된 `data/uploads/<upload_id>/`.
- 운영 환경: RustFS 임시 bucket 또는 `data/uploads`.
- 원본 파일은 git에 절대 커밋하지 않는다.

#### `POST /admin/offline-uploads/{upload_id}/validate`

검증 job 생성.

요청:

```json
{
  "sample_size": 1000,
  "column_mapping": {
    "name": "사업장명",
    "address": "소재지전체주소",
    "lon": "경도",
    "lat": "위도"
  },
  "operator": "local-admin"
}
```

검증 단계:

1. 파일 존재, checksum, size 확인.
2. format parse.
3. schema/header 확인.
4. 좌표 범위 확인.
5. 주소 파싱/geocoding 가능성 확인.
6. provider typed model 또는 structural Protocol 입력 형태로 변환 가능성 확인.
7. DTO validation.
8. dedup dry-run.
9. issue summary 생성.

응답은 import job과 동일하게 `job_id`를 반환한다.

#### `POST /admin/offline-uploads/{upload_id}/load`

검증이 통과한 upload를 실제 적재한다.

요청:

```json
{
  "validation_job_id": "uuid",
  "mode": "load",
  "operator": "local-admin",
  "reason": "오프라인 파일 검증 후 적재"
}
```

처리 규칙:

- 검증 job이 `done`이고 severity max가 허용 수준이어야 한다.
- `mode=load`는 import job을 새로 만든다.
- advisory lock은 provider/dataset/scope 기준으로 잡는다.
- 적재 중 취소 가능하다. 취소 semantics는 import job과 동일하다.

#### `POST /admin/offline-uploads/{upload_id}/cancel`

upload validation 또는 load job 취소 요청. 실제 취소는 연결된 job cancel API로
위임한다.

### 16.4 스키마 gap

정식 구현 전 다음 테이블 도입을 검토한다.

```sql
CREATE TABLE ops.offline_uploads (
  upload_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  provider TEXT NOT NULL,
  dataset_key TEXT NOT NULL,
  sync_scope TEXT NOT NULL DEFAULT 'default',
  original_filename TEXT NOT NULL,
  storage_backend TEXT NOT NULL,
  storage_key TEXT NOT NULL,
  byte_size BIGINT NOT NULL,
  checksum_sha256 CHAR(64) NOT NULL,
  detected_format TEXT,
  detected_encoding TEXT,
  state TEXT NOT NULL DEFAULT 'uploaded',
  validation_job_id UUID REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL,
  load_job_id UUID REFERENCES ops.import_jobs(job_id) ON DELETE SET NULL,
  created_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_offline_uploads_provider_dataset
  ON ops.offline_uploads (provider, dataset_key, created_at DESC);
CREATE INDEX idx_offline_uploads_state
  ON ops.offline_uploads (state, created_at DESC);
```

## 17. Dashboard

Route: `/`

운영 홈은 설명 페이지가 아니라 바로 쓸 수 있는 콘솔이어야 한다.

필수 위젯:

- running jobs
- failed jobs in last 24h
- provider failures
- pending dedup reviews
- issue features count
- stale provider sync count
- recent error logs
- recent manual actions

#### `GET /admin/dashboard`

응답:

```json
{
  "data": {
    "running_jobs": 1,
    "failed_jobs_24h": 2,
    "providers_failed": 1,
    "pending_dedup_reviews": 391,
    "open_issue_features": 182,
    "stale_provider_sync": 3,
    "recent_errors": [],
    "recent_jobs": []
  },
  "meta": {"duration_ms": 10}
}
```

## 18. MapLibre VWorld 사용 규칙

- 지도는 `maplibre-vworld-js`를 사용한다. Kakao Maps SDK를 추가하지 않는다.
- 좌표 입력/출력은 외부 인터페이스에서 항상 `(lon, lat)` 순서다.
- marker는 가능하면 `@krtour/map-marker-react`의 category/maki 매핑을 재사용한다.
- 지도 중심과 zoom은 Zustand store에 둔다.
- bbox refetch, nearby refetch는 TanStack Query hook으로 감싼다.
- marker가 1000개를 넘으면 cluster 또는 viewport culling을 적용한다.
- 좌표 없는 feature는 지도에 억지로 표시하지 않고 별도 list로 노출한다.

## 19. Data model 추가 후보 요약

본 사양을 완전히 구현하려면 현 스키마만으로 부족한 부분이 있다. 구현 PR에서 한꺼번에
넣지 말고, 기능별로 작게 나누어 마이그레이션한다.

| 후보 | 목적 | 우선순위 |
|------|------|----------|
| `ops.import_job_events` | job stage별 로그, 에러, progress detail | 높음 |
| `ops.offline_uploads` | 업로드 원본 파일 메타, validation/load job 연결 | 높음 |
| `ops.data_integrity_violations` | feature 단위 이슈 큐 | 높음 |
| `ops.admin_audit_log` | 비활성화, 영구삭제, manual override 감사 | 높음 |
| `ops.provider_run_summaries` | provider/dataset별 최근 count, duration, issue summary | 중간 |

`ops.admin_audit_log` 권장 shape:

```sql
CREATE TABLE ops.admin_audit_log (
  audit_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  operator TEXT,
  reason TEXT,
  before_value JSONB,
  after_value JSONB,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_admin_audit_target ON ops.admin_audit_log (target_type, target_id, created_at DESC);
CREATE INDEX idx_admin_audit_action ON ops.admin_audit_log (action, created_at DESC);
```

## 20. TanStack Query/Zustand 구현 컨벤션

API module:

- `src/api/features.ts`: `/features/*`, `/admin/features`.
- `src/api/providers.ts`: `/admin/providers/*`.
- `src/api/importJobs.ts`: `/admin/import-jobs/*`.
- `src/api/dedup.ts`: `/admin/dedup-review/*`.
- `src/api/issues.ts`: `/admin/issues/*`.
- `src/api/offlineUploads.ts`: `/admin/offline-uploads/*`.
- `src/api/updateRequests.ts`: `/admin/feature-update-requests/*`.
- `src/api/poiCacheTargets.ts`: `/admin/poi-cache-targets/*`,
  `/features/nearby/by-target`.
- `src/api/providerRefreshPolicies.ts`: `/admin/provider-refresh-policies/*`.
- `src/api/ops.ts`: `/ops/*`.

Query key 예:

```typescript
["admin-features", filters]
["feature-detail", featureId]
["nearby-features", lon, lat, radiusM, filters]
["providers"]
["provider", provider]
["import-jobs", filters]
["import-job", jobId]
["dedup-review", filters]
["issue-features", filters]
["offline-upload", uploadId]
["feature-update-requests", filters]
["feature-update-request", requestId]
["poi-cache-targets", filters]
["poi-cache-target", externalSystem, targetKey]
["nearby-features-by-target", externalSystem, targetKey, radiusKm, filters]
["provider-refresh-policies"]
["ops-error-logs", filters]
```

Mutation 후 invalidation:

| Mutation | invalidate |
|----------|------------|
| feature 생성 | `admin-features`, `features`, `feature-detail` |
| feature 비활성화/삭제 | `admin-features`, `features`, `feature-detail`, `issue-features` |
| provider run 생성 | `import-jobs`, `provider`, `providers`, `dashboard` |
| job cancel | `import-job`, `import-jobs`, `dashboard` |
| dedup decision | `dedup-review`, `feature-detail`, `issue-features`, `admin-features` |
| issue resolve/ignore | `issue-features`, `feature-detail`, `dashboard` |
| offline upload validate/load | `offline-upload`, `import-jobs`, `dashboard` |
| feature update request 생성/취소 | `feature-update-requests`, `import-jobs`, `dashboard`, `providers` |
| poi cache target upsert/delete | `poi-cache-targets`, `feature-update-requests`, `nearby-features-by-target`, `dashboard` |

Zustand store:

- map viewport: center, zoom, bounds.
- selected feature id.
- active view mode: map/table.
- feature filters.
- issue filters.
- provider run form draft.
- feature update request form draft.
- offline upload wizard state.

서버 데이터를 Zustand에 복제하지 않는다. 서버 응답은 TanStack Query cache가 source of
truth다.

## 21. 테스트 기준

### 21.1 Backend unit

- `GET /admin/features` query validation.
- sort/page_size/cursor validation.
- `POST /admin/features` manual source record 생성 계약.
- deactivate/delete dry-run/confirmation.
- provider run 중복 lock conflict.
- job cancel state transition.
- dedup decision state transition.
- offline upload validation request validation.
- feature update request scope validation (`feature_ids`, `center_radius`,
  `sigungu_by_radius`, `bbox`, `provider_dataset`).
- poi cache target key/coordinate idempotency validation.
- provider refresh policy override가 rate limit을 넘을 때 422 반환.

### 21.2 Backend integration

PostGIS testcontainers에서 검증:

- `/admin/features` 검색이 `idx_features_name_trgm` 또는 적절한 index를 사용.
- `/features/nearby`가 `coord_5179` GiST index를 사용.
- manual create -> source_records/source_links/features 3테이블 정합.
- deactivate -> provider 재적재가 override를 존중.
- delete dry-run -> 실제 cascade count와 일치.
- provider run -> import_jobs progress/state transition.
- feature update request -> scope resolution -> import_jobs/Dagster run 연결.
- cache target A/B 반경 교집합 -> 같은 feature/provider scope는 한 번만 queue.
- `GET /features/nearby/by-target` -> summary 응답에 detail JSONB/raw payload 없음.
- dedup review -> feature_merge_history 또는 status update.
- issue query -> data_integrity_violations 또는 consistency sample 조회.

### 21.3 Frontend e2e

Windows Playwright 표준 실행 모델을 따른다.

필수 시나리오:

1. `/features` 진입, table view, 검색, page size 변경, 이름순 확인.
2. `/features` map view, marker 클릭, 상세 패널/상세 페이지 이동.
3. `/features/[id]`에서 주변 feature table이 이름순으로 뜨고 sort/search 동작.
4. 수동 feature draft 생성.
5. 비활성화 확인 모달과 reason 필수 검증.
6. 삭제 dry-run 후 feature_id 입력 전 실제 삭제 버튼 disabled.
7. provider 상세에서 강제 run 생성 후 job 상세 진행률 polling.
8. job cancel 요청 후 terminal state 확인.
9. dedup review에서 keep separate 또는 accepted 처리.
10. issue map/table 전환.
11. offline upload validation job 생성과 progress 확인.
12. 좌표 중심 반경 feature update request 생성 후 queued 상태와 job progress 확인.
13. 반경 내 시군구 feature update request dry-run 결과 확인.
14. poi cache target 등록, key 기준 주변 feature 조회, target 삭제 후 update 제외 확인.
15. provider refresh policy 수정 시 rate limit 초과 validation 확인.
16. API error 발생 시 error toast와 로그 링크 표시.

### 21.4 OpenAPI drift

새 라우터/DTO 추가 시:

```bash
python packages/krtour-map-admin/scripts/export_openapi.py \
  --output packages/krtour-map-admin/openapi.json

python packages/krtour-map-admin/scripts/export_openapi.py \
  --check --output packages/krtour-map-admin/openapi.json
```

frontend type generation이 도입된 라우터는 `npm run gen:types`도 함께 실행한다.

### 21.5 React Doctor

frontend 작업이 포함된 PR은 React Doctor를 실행한다.

```bash
cd packages/krtour-map-admin/frontend
npm run doctor
```

아직 `doctor` script가 없으면 첫 frontend PR에서 추가한다. 실행 결과는 단순 첨부가
아니라 검토 후 개선까지 해야 한다. 개선하지 않는 항목은 false positive 또는 의도한
tradeoff 근거를 PR 설명이나 `docs/journal.md`에 남긴다.

## 22. 구현 순서 제안

큰 기능을 한 PR로 묶지 않는다.

1. **Admin feature list**
   - `GET /admin/features`
   - `/features` table view
   - 검색/소팅/page_size
2. **Feature detail/nearby**
   - `GET /features/nearby`
   - 상세 화면 주변 지도/테이블
3. **Manual feature create + deactivate**
   - `POST /admin/features`
   - `POST /admin/features/{id}/deactivate`
   - audit log는 최소 구조라도 먼저 둔다.
4. **Delete dry-run + hard delete**
   - `DELETE /admin/features/{id}?dry_run=true`
   - 실제 delete는 확인 UI와 함께.
5. **Provider status**
   - `GET /admin/providers`
   - `GET /admin/providers/{provider}`
6. **Provider run + import job progress**
   - `POST /admin/providers/{provider}/datasets/{dataset_key}/runs`
   - `/admin/import-jobs`
   - `/admin/import-jobs/{job_id}`
   - cancel.
7. **Error log/events**
   - `ops.import_job_events` migration.
   - `/ops/error-logs`.
8. **Dedup review UI**
   - pending list.
   - decision patch.
   - merge는 별도 PR.
9. **Issue feature view**
   - `ops.data_integrity_violations` migration.
   - `/admin/issues` map/table.
10. **Offline upload**
    - upload metadata.
    - validation job.
    - load job.
11. **Feature update request**
    - `ops.feature_update_requests` migration.
    - `POST /admin/feature-update-requests`.
    - `center_radius`, `sigungu_by_radius` dry-run.
    - Dagster sensor/worker 연결.
12. **POI/cache target**
    - `ops.poi_cache_targets`, `ops.poi_cache_target_feature_links`,
      `ops.provider_refresh_policies` migration.
    - `PUT/DELETE /admin/poi-cache-targets/{external_system}/{target_key}`.
    - `GET /features/nearby/by-target`.
    - `scope.type='cache_target_keys'` dry-run/load.

## 23. 완료 기준

각 기능 PR의 완료 기준:

- OpenAPI drift 없음.
- backend unit/integration 테스트 추가.
- frontend route가 있으면 lint, type-check, build, React Doctor, Playwright e2e 추가.
- destructive action은 dry-run, confirmation, audit log가 있어야 한다.
- provider 실행/적재 action은 advisory lock과 job progress를 가져야 한다.
- feature update request는 OpenAPI로 즉시 실행/큐잉, 진행률 조회, 취소까지 가능해야 한다.
- cache target 기반 갱신은 고유 key 삭제/좌표 conflict/교집합 dedup/rate limit clamp를
  테스트해야 한다.
- 모든 feature 목록/상세 응답에는 KST aware `last_updated_at`이 있어야 한다.
- docs/journal.md와 docs/resume.md 갱신.
- main package 의존 방향과 FastAPI 금지 계약을 건드리지 않는다.
