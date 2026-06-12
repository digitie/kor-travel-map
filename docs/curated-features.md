# curated_features — 테마형 feature 계약

> **상태**: 2026-06-12 문서 계약. DB/API/Admin UI/Dagster 구현 전.
> **정본 범위**: 테마 중심 데이터 소스, `curated_features` 데이터 모델, TripMate
> `curated_trip_plans` 복사 계약, admin UI·REST·Dagster 설계.

## 1. 결정 요약

- `curated_features`는 `feature.features`를 복제하지 않는 **overlay**다. 원천 POI는
  계속 `feature.features`가 소유하고, 테마·데이터 소스·선정 상태·TripMate 복사
  메타데이터만 별도 테이블이 소유한다.
- TripMate 정본 테이블명은 `app.curated_trip_plans` /
  `app.curated_plan_pois`다. `/notice-plans`와 `notice_plan_id`는 TripMate 내부
  호환 API alias일 뿐이며, 신규 문서·DB·ORM 기준으로 쓰지 않는다.
- krtour-map `curated_features` 1건은 TripMate `curated_trip_plans` 1건으로
  복사된다. 하위 장소·정류점·추천 POI는 TripMate `curated_plan_pois`가 받는다.
- TripMate는 krtour-map DB를 직접 읽지 않는다. TripMate는 krtour-map REST API를 호출해
  필요한 snapshot을 자기 DB에 복사한다. `krtour-ai-agent`는 이 복사 flow에 관여하지 않는다.
- 구현 전까지 `openapi.user.json`에는 포함하지 않는다. 구현 PR에서 DTO/schema 추가 후
  `scripts/export_openapi.py`를 다시 실행한다.

## 2. 테마형 데이터 소스 조사 결과

### 2.1 바로 후보화 가능한 기존 source

`python-mcst-api` provider는 이미 16개 dataset을 `Feature`로 정규화한다. 이 중
세계음식점, 독립서점, 카페가 있는 서점, 도서관 계열은 첫 curated 후보로 쓸 수 있다.
나머지 MCST 테마 source도 admin 기본 규칙으로 후보화할 수 있다.

| dataset_key | slug | 테마 | 현재 상태 |
|-------------|------|------|-----------|
| `mcst_world_restaurants` | `world_restaurants` | 세계음식점 | 구현됨 |
| `mcst_independent_bookstores` | `independent_bookstores` | 독립서점 | 구현됨 |
| `mcst_cafe_bookstores` | `cafe_bookstores` | 카페가 있는 서점 | 구현됨 |
| `mcst_public_libraries` | `public_libraries` | 공공도서관 | 구현됨 |
| `mcst_small_libraries` | `small_libraries` | 작은도서관 | 구현됨 |
| `mcst_media_famous_places` | `media_famous_places` | 미디어 촬영지 | 구현됨 |
| `mcst_barrier_free_places` | `barrier_free_places` | 무장애 관광지 | 구현됨 |
| `mcst_pet_friendly_culture_facilities` | `pet_friendly_culture_facilities` | 반려동물 동반 가능 문화시설 | 구현됨 |
| `mcst_leisure_activity_facilities` | `leisure_activity_facilities` | 레저활동 시설 | 구현됨 |
| `mcst_leisure_camping_facilities` | `leisure_camping_facilities` | 레저 캠핑 시설 | 구현됨 |
| `mcst_leisure_classes` | `leisure_classes` | 레저 클래스/강습 | 구현됨 |
| `mcst_family_infant_culture_facilities` | `family_infant_culture_facilities` | 가족/영유아 동반 문화시설 | 구현됨 |
| `mcst_multilingual_guide_culture_facilities` | `multilingual_guide_culture_facilities` | 다국어 안내 문화시설 | 구현됨 |
| `mcst_small_theaters` | `small_theaters` | 소공연장 | 구현됨 |
| `mcst_meeting_seminar_facilities` | `meeting_seminar_facilities` | 회의/세미나 시설 | 구현됨 |
| `mcst_recommended_travel_destinations` | `recommended_travel_destinations` | 추천 여행지 | 구현됨 |

### 2.2 책·음식 테마 확장 후보

아래 표는 data.go.kr과 로컬 `python-*-api` provider 범위를 함께 본 결과다.
`최근 수정일`은 공공데이터포털 페이지 확인 기준이다. 실제 적재 구현 PR에서는 provider
라이브러리의 typed model·pagination·raw 보존을 먼저 정렬한 뒤 이 문서의 메타데이터를
DB seed 또는 migration data로 옮긴다.

| 후보 dataset_key | 테마 | 제공기관 | source URL | 최근 수정일 / 갱신 | 상태·비고 |
|------------------|------|----------|------------|--------------------|-----------|
| `mcst_used_bookstores` | 중고서점 | 한국문화정보원 | https://www.data.go.kr/data/15100298/openapi.do?recommendDataYn=Y | 2025-08-13 / 실시간 | `python-mcst-api` 보강 후보. JSON+XML, 제한 없음 |
| `mcst_independent_bookstores` | 독립서점 | 한국문화정보원 | https://www.data.go.kr/data/15138901/openapi.do?recommendDataYn=Y | 2025-08-13 / 실시간 | 이미 구현. XML, 제한 없음 |
| `mcst_cafe_bookstores` | 카페가 있는 서점 | 한국문화정보원 | https://www.data.go.kr/data/15138904/openapi.do?recommendDataYn=Y | 2025-08-13 / 실시간 | 이미 구현. XML, 제한 없음 |
| `mcst_children_bookstores` | 아동서점·복합문화공간 | 한국문화정보원 | https://www.data.go.kr/data/15089405/fileData.do?recommendDataYn=Y | 2025-08-14 / 연간 | `python-mcst-api` 또는 `python-datagokr-api` 보강 후보. 506행, 2023년 조사 한계 |
| `datagokr_seoul_bookstores` | 서울 책방 | 서울특별시 | https://www.data.go.kr/data/15084328/fileData.do | 2025-12-02 / 수시·1회성 | `python-datagokr-api` 파일데이터 후보. 555행, 서울 자체 URL 보유 |
| `datagokr_gyeonggi_muslim_friendly_restaurants` | 무슬림 친화 음식점 | 경기관광공사 | https://www.data.go.kr/data/15099378/fileData.do | 2025-09-23 / 수시·1회성 | `python-datagokr-api` 후보. 51행, 2024-05 기준 조사 한계 |
| `datagokr_ansan_world_restaurants` | 안산 다문화 세계맛집 | 경기도 안산시 | https://www.data.go.kr/data/15152605/fileData.do | 2025-11-20 / 수시·1회성 | `python-datagokr-api` 후보. 44행, 다국어 설명 포함 |
| `datagokr_jeju_local_restaurants` | 제주 향토음식점 | 제주특별자치도 | https://www.data.go.kr/data/15043695/fileData.do?recommendDataYn=Y | 2025-11-20 / 연간 | `python-datagokr-api` 후보. 62행, 차기 등록 예정 2026-11-20 |
| `standard_special_streets` | 음식·문화 특화거리 | 지방자치단체 | https://www.data.go.kr/data/15017322/standard.do | 2025-12-03 / 연간 | area/anchor source로 유용. 108개 제공기관 병합, 개별 POI보다 테마 구역 메타 |

## 3. 데이터 모델

Schema는 `feature`에 둔다. 테마형 큐레이션은 feature 도메인의 표시·복사 정책이므로
`provider_sync`나 `ops`가 아니라 `feature` 소유다.

### 3.1 `feature.curated_themes`

| 컬럼 | 의미 |
|------|------|
| `theme_id` | UUID PK |
| `theme_slug` | 안정 slug. 예: `bookstore-cafes`, `world-food`, `barrier-free` |
| `theme_name` | 한국어 표시명 |
| `theme_description` | admin/TripMate 설명용 요약 |
| `theme_group` | `books`, `food`, `accessibility`, `family`, `pet`, `culture` 등 |
| `default_curated` | provider 적재 시 기본 후보화 여부 |
| `visibility` | `admin_only` / `public` / `tripmate` |
| `metadata` | 아이콘, 색상, 정렬, TripMate category hint |
| `created_at` / `updated_at` | 표준 timestamp |

`theme_slug`는 unique다. 화면/REST는 slug를 받을 수 있지만 DB FK는 `theme_id`를 쓴다.

### 3.2 `feature.curated_sources`

| 컬럼 | 의미 |
|------|------|
| `source_id` | UUID PK |
| `provider` | canonical provider name |
| `dataset_key` | provider dataset key |
| `source_name` | 공공데이터명 또는 내부 source 이름 |
| `source_url` | data.go.kr/culture.go.kr/provider 문서 URL |
| `source_kind` | `openapi` / `filedata` / `standard` / `internal` |
| `license` | 이용허락범위 원문 또는 `metadata.license_url` |
| `update_cycle` | `realtime`, `daily`, `weekly`, `annual`, `one_time`, `unknown` |
| `last_source_modified_at` | 공공데이터 포털 수정일 또는 provider 문서 기준일 |
| `last_checked_at` | krtour-map이 metadata를 마지막 확인한 시각 |
| `next_expected_at` | 차기 등록 예정일 또는 운영상 다음 확인 시점 |
| `row_count` | 포털 전체 행 또는 마지막 적재 row 수 |
| `freshness_note` | "2024-05 조사", "기관 병합 시차 있음" 같은 한계 설명 |
| `provider_status` | `implemented`, `provider_needed`, `manual_only`, `deprecated` |
| `metadata` | 원문 컬럼명, 다운로드 URL, API 유형, contact 등 |

`provider + dataset_key`는 unique다. 같은 공공데이터가 파일/API 두 표면을 함께 제공하면
`source_kind`와 `metadata.surface`로 구분한다.

### 3.3 `feature.curated_source_rules`

provider 적재 직후 어떤 feature를 기본 후보로 둘지 정의한다.

| 컬럼 | 의미 |
|------|------|
| `rule_id` | UUID PK |
| `theme_id` | `curated_themes` FK |
| `source_id` | `curated_sources` FK |
| `dataset_key` | 빠른 필터용 중복 컬럼 |
| `place_kind` | `detail.place_kind` 조건. nullable이면 dataset 전체 |
| `category` | category 조건. nullable이면 무시 |
| `region_scope` | 특정 sido/sigungu 한정 JSONB |
| `default_action` | `candidate` / `curated` / `ignore` |
| `priority` | 같은 feature가 여러 theme에 걸릴 때 정렬 |
| `enabled` | rule 활성 여부 |
| `metadata` | rule 근거, admin 표시용 설명 |

사용자가 계획 단계에서 기본값으로 curated 지정하는 경우는 `default_action='curated'`로 둔다.
admin이 이후 특정 feature를 해제하면 `feature.curated_features` row의 수동 상태가 rule보다
우선한다.

### 3.4 `feature.curated_features`

`feature.features`에 대한 overlay 본체다.

| 컬럼 | 의미 |
|------|------|
| `curated_feature_id` | UUID PK |
| `theme_id` | `curated_themes` FK |
| `feature_id` | `feature.features(feature_id)` FK. nullable 허용 여부는 구현 시 결정하되 1차는 NOT NULL |
| `source_id` | `curated_sources` FK |
| `source_record_key` | provider 원천 record 추적 |
| `curation_status` | `candidate` / `curated` / `rejected` / `archived` |
| `selection_origin` | `source_rule` / `admin` / `external_api` |
| `selected_by` / `selected_at` | 선정자·시각 |
| `rejected_by` / `rejected_at` | 제외자·시각 |
| `rejection_reason` | 제외 사유 |
| `rank_score` | 테마 내 정렬 점수 |
| `display_title` | feature name override. 기본은 `features.name` |
| `display_summary` | TripMate plan summary 후보 |
| `tripmate_relation` | TripMate 복사 시 역할. 아래 enum 참고 |
| `tripmate_copy_policy` | `copy_allowed` / `copy_blocked` / `manual_review` |
| `metadata` | 배지, 추천 문구, 원천 한계, 외부 id |
| `created_at` / `updated_at` | 표준 timestamp |
| `archived_at` | soft archive |

`curation_status`가 `rejected`/`archived`인 row는 provider 재적재나 rule 재평가로 되살리지
않는다. 같은 `theme_id + feature_id`의 active row는 하나만 허용한다.

`tripmate_relation` 후보:

- `primary_stop` — curated trip plan의 중심 장소
- `food_stop` — 식당·맛집
- `cafe_stop` — 카페·북카페
- `bookstore_stop` — 서점·도서관
- `nearby_option` — 주변 선택지
- `accessibility_support` — 무장애/다국어/편의 지원
- `pet_support` — 반려동물 동반
- `family_support` — 가족·영유아 동반
- `theme_area_anchor` — 특화거리 같은 구역 anchor

### 3.5 인덱스 기준

- `UNIQUE (theme_id, feature_id) WHERE archived_at IS NULL`
- `INDEX (curation_status, updated_at DESC, curated_feature_id DESC)`
- `INDEX (theme_id, curation_status, rank_score DESC)`
- `INDEX (source_id, curation_status)`
- `INDEX (feature_id)`
- `GIN (metadata jsonb_path_ops)`는 admin 검색·배지 필터가 실제로 필요해질 때만 추가한다.

## 4. REST API 계약

공용 read는 TripMate 복사와 외부 조회를 위한 표면이고, write는 운영/agent가 호출하는
관리 표면이다. 전 표면은 기존 규칙대로 `/v1` + `{data, meta}` envelope를 쓴다.

### 4.1 공용 read

```
GET /v1/curated-themes
GET /v1/curated-sources
GET /v1/curated-features
GET /v1/curated-features/{curated_feature_id}
GET /v1/curated-features/{curated_feature_id}/tripmate-copy
```

`GET /v1/curated-features` 주요 query:

- `theme_slug`
- `theme_id`
- `source_id`
- `provider`
- `dataset_key`
- `curation_status` 기본 `curated`
- `region_code` 또는 `sido_code`/`sigungu_code`
- `bbox`는 기존 표준인 `min_lon/min_lat/max_lon/max_lat`
- `page_size`/`cursor`

`tripmate-copy` 응답은 TripMate import에 필요한 snapshot을 닫힌 형태로 제공한다. TripMate는
이 응답을 `app.curated_trip_plans` 1건과 `app.curated_plan_pois` N건으로 복사한다.

### 4.2 Admin/write

```
GET    /v1/admin/curated-features
POST   /v1/admin/curated-features
PATCH  /v1/admin/curated-features/{curated_feature_id}
DELETE /v1/admin/curated-features/{curated_feature_id}
POST   /v1/admin/curated-features/{curated_feature_id}/select
POST   /v1/admin/curated-features/{curated_feature_id}/unselect
GET/POST/PATCH /v1/admin/curated-themes
GET/POST/PATCH /v1/admin/curated-sources
GET/POST/PATCH /v1/admin/curated-source-rules
POST   /v1/admin/curated-source-rules/{rule_id}/apply
```

외부 write가 필요한 경우에도 별도 `/tripmate/*` namespace를 만들지 않는다.
TripMate admin이나 운영 자동화는 인프라 보호 + service/admin token 정책으로 위 표면을
호출한다. 사용자용 TripMate public client와 `krtour-ai-agent`는 직접 write하지 않는다.

## 5. TripMate 복사 계약

TripMate import payload의 최소 구조:

```json
{
  "curated_feature_id": "01J...",
  "version": 3,
  "etag": "sha256:...",
  "updated_at": "2026-06-12T10:00:00+09:00",
  "theme": {
    "theme_slug": "world-food",
    "theme_name": "세계음식점"
  },
  "plan": {
    "title": "안산 세계음식 탐방",
    "summary": "안산 다문화 음식거리의 세계음식점 큐레이션",
    "destination_name": "경기도 안산시",
    "region_code": "41270",
    "category": "food"
  },
  "source": {
    "provider": "python-mcst-api",
    "dataset_key": "mcst_world_restaurants",
    "source_name": "한국문화정보원_세계음식 음식점",
    "source_url": "https://www.data.go.kr/..."
  },
  "items": [
    {
      "curated_feature_item_id": "01J...",
      "feature_id": "f_...",
      "relation": "food_stop",
      "sort_order": 1,
      "day_index": null,
      "memo": "원천 설명 또는 운영자 추천 문구",
      "feature_snapshot": {
        "name": "식당명",
        "category": "02010000",
        "lon": 126.0,
        "lat": 37.0,
        "address": {}
      },
      "source_record_key": "sr_..."
    }
  ]
}
```

TripMate 저장 권장 컬럼:

- `curated_trip_plans.source_system = 'krtour-map'`
- `curated_trip_plans.source_curated_feature_id`
- `curated_trip_plans.source_curated_feature_version`
- `curated_trip_plans.source_etag`
- `curated_trip_plans.source_imported_at`
- `curated_plan_pois.source_curated_feature_item_id`
- `curated_plan_pois.source_feature_id`

TripMate는 `feature_id`를 파싱하지 않는다. krtour-map item에 `feature_id`가 없는
미정규화 anchor를 허용하게 될 경우 TripMate도 nullable로 저장하고, `curated:<id>` 같은
가짜 feature id를 만들지 않는다.

## 6. Admin UI 요구사항

Admin UI는 기존 feature/admin 화면 위에 다음 흐름을 붙인다.

- feature 목록·상세에서 "curated 후보/선정/제외" 상태를 볼 수 있어야 한다.
- 테마별 후보 목록에서 bulk select/unselect, status filter, source filter, region filter를 제공한다.
- source rule 화면에서 "이 provider dataset은 기본 candidate/curated"를 지정할 수 있어야 한다.
- 사용자가 계획 단계에서 기본 curated로 지정한 rule은 `default_action='curated'`로 보이고,
  개별 feature 제외는 rule보다 우선한다.
- `rejected`/`archived` row는 "되살리기"를 명시 action으로만 처리한다.
- TripMate copy preview에서 `curated_trip_plans`와 `curated_plan_pois`로 들어갈 snapshot을
  그대로 확인할 수 있어야 한다.

## 7. Dagster 묶음

Dagster asset group은 `curated_features`로 둔다. provider 원천 asset이 먼저 실행되고,
그 다음 curated rule apply와 metadata refresh가 실행된다.

권장 asset:

- `curated_source_metadata` — source URL, 수정일, row_count, license, update_cycle refresh
- `curated_feature_candidates` — `curated_source_rules`를 feature에 적용
- `curated_feature_status_sweep` — deleted/inactive feature와 curated overlay 정합성 점검
- `curated_tripmate_copy_snapshots` — TripMate copy endpoint와 같은 snapshot materialize/cache

중요 규칙:

- `rejected`/`archived`는 자동 rule apply가 되살리지 않는다.
- provider reload로 feature snapshot이 바뀌면 `curated_features.updated_at`과 copy `version`을 올린다.
- source metadata refresh가 공공데이터포털 수정일을 바꿨다면 admin UI와 TripMate copy payload에
  새 값을 노출한다.

## 8. 구현 순서

1. provider 보강이 필요한 source를 `python-mcst-api` / `python-datagokr-api`에서 먼저 정렬한다.
2. krtour-map DB migration으로 `feature.curated_*` 테이블과 seed source metadata를 추가한다.
3. repository + REST read/write DTO를 구현하고 `openapi.user.json` / `openapi.json`을 재생성한다.
4. Dagster `curated_features` group과 rule apply asset을 추가한다.
5. Admin UI에 curated 후보 선택/해제, source rule, TripMate copy preview를 붙인다.
6. TripMate는 krtour-map REST를 호출해 `curated_trip_plans` /
   `curated_plan_pois`로 복사한다.
