# public-views-api — TripMate T-130 공개 뷰용 kor-travel-map API 사양

> **상태**: 구현됨(2026-06-12, T-222b). `openapi.user.json` 사용자 profile과
> `@kor-travel-map/map-user-client` 생성 타입에 포함한다.
> 후속 소비/픽스처 동기화는 `docs/tasks.md` T-222c.
> **목적**: TripMate T-130(`/public/*`)이 요구하는 해수욕장/축제 공개 조회 뷰를
> kor-travel-map 쪽 사용자 API 계약으로 먼저 고정한다.

## 1. 경계

- kor-travel-map은 feature 정본과 도메인 뷰를 제공한다.
- TripMate는 자기 `/public/*` 라우터에서 이 API를 서버측으로 호출해 비로그인
  사용자에게 재가공한다. TripMate 사용자/세션/여행계획 데이터는 포함하지 않는다.
- 별도 인증 없는 공개 노출은 TripMate 책임이다. kor-travel-map의 `/v1/public/*`는
  기존 `/v1/features/*` 조회와 같은 내부망/API `12701` 경계에 둔다.
- 응답 envelope, error, pagination은 `docs/rest-api.md`의 ADR-048 규약을 따른다.

## 2. 엔드포인트

### 2.1 `GET /v1/public/beaches`

해수욕장 공개 목록 뷰.

질의 파라미터:

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `sido_code` | string | 없음 | 시도 코드 |
| `sigungu_code` | string | 없음 | 시군구 코드 |
| `q` | string | 없음 | 이름/주소 검색 |
| `page_size` | int | 50 | 최대 200 |
| `cursor` | string | 없음 | keyset cursor |
| `include_quality` | bool | false | 수질 최신값 포함 |
| `include_forecast` | bool | false | KHOA/KMA index·weather 요약 포함 |

응답 `data.items[]`: `BeachPublicView`.

### 2.2 `GET /v1/public/beaches/map-markers`

지도 layer용 경량 marker.

질의 파라미터:

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `min_lon`, `min_lat`, `max_lon`, `max_lat` | number | 없음 | 있으면 bbox 제한 |
| `sido_code`, `sigungu_code` | string | 없음 | 행정구역 제한 |
| `max_items` | int | 500 | 최대 2000 |

응답:

```json
{
  "data": {
    "layer_key": "beach",
    "display_name": "해수욕장",
    "marker_icon": "beach",
    "marker_color": "P-07",
    "items": [
      {
        "feature_id": "f_global_p_...",
        "name": "광안리 해수욕장",
        "lon": 129.118,
        "lat": 35.155,
        "sigungu_code": "26110"
      }
    ]
  },
  "meta": {
    "duration_ms": 8,
    "request_id": "01J..."
  }
}
```

### 2.3 `GET /v1/public/beaches/{feature_id}`

해수욕장 단건 상세. `BeachPublicView` 1건을 반환한다. `feature_id`는 불투명 문자열이다.

### 2.4 `GET /v1/public/festivals/monthly`

월별 활성 축제 뷰.

질의 파라미터:

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `year` | int | 현재 KST | 기준 연도 |
| `month` | int | 현재 KST | 기준 월 |
| `sido_code`, `sigungu_code` | string | 없음 | 행정구역 제한 |
| `page_size` | int | 12 | 최대 50 |
| `cursor` | string | 없음 | keyset cursor |
| `include_months` | bool | true | 전후 월 count summary 포함 |

기간 판정:

- `EventDetail.starts_on <= month_end`
- `EventDetail.ends_on IS NULL OR EventDetail.ends_on >= month_start`
- `status='active'`

응답 `data.months[]`는 기준 월의 전월/당월/익월 summary이고, `data.items[]`는
`FestivalPublicView`다.

### 2.5 `GET /v1/public/festivals/map-markers`

축제 지도 layer용 marker.

질의 파라미터:

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `year`, `month` | int | 현재 KST | 기간 겹침 기준 |
| `min_lon`, `min_lat`, `max_lon`, `max_lat` | number | 없음 | bbox 제한 |
| `max_items` | int | 500 | 최대 2000 |

### 2.6 `GET /v1/public/festivals/{feature_id}`

축제 단건 상세. `FestivalPublicView` 1건을 반환한다.

## 3. 스키마

### 3.1 `BeachPublicView`

| 필드 | 타입 | 출처 |
|---|---|---|
| `feature_id` | string | `FeatureDetailResponse.feature_id` |
| `display_name` | string | `Feature.name` |
| `lon`, `lat` | number/null | `Feature.coord` |
| `sido_code`, `sigungu_code`, `legal_dong_code` | string/null | `FeatureDetailResponse` |
| `address` | object | 구조화 `Address` |
| `road_address`, `jibun_address` | string/null | `address`에서 projection |
| `marker_icon`, `marker_color` | string/null | feature marker |
| `beach_kind` | string/null | `detail.facility_info.beach_kind` |
| `beach_width_m`, `beach_length_m` | number/null | KHOA 상세 필드. 현재는 `facility_info`/primary raw payload에 값이 있을 때만 projection |
| `beach_material` | string/null | KHOA 상세 필드. 현재는 `beach_type`/`beach_material` raw key를 projection |
| `emergency_contact` | string/null | `detail.phones[0]` 또는 provider payload |
| `homepage_url`, `image_url` | string/null | `urls.homepage`, `detail.facility_info.image_url`, FeatureFile |
| `latest_water_quality` | object/null | 현재 null. KHOA 수질 값 projection은 후속 marine/weather 확정 후 채움 |
| `upcoming_index_forecasts` | array | 현재 빈 배열. KHOA index forecast projection은 후속 확정 후 채움 |
| `latest_weather` | object/null | 현재 null. `/v1/features/{feature_id}/weather` projection 연결은 후속 |
| `source_providers` | array[string] | SourceLink 또는 provider 요약 |
| `updated_at` | datetime | feature updated_at |

해수욕장 판별 기준:

1. `kind='place'`
2. `detail.place_kind='beach'`
3. category는 1차 판별로 쓰지 않는다(`detail.place_kind='beach'`가 정본 판별). KHOA
   provider category는 DA-D-07(2026-06-16)로 전용 `01050100`(자연명소>해수욕장,
   `TOURISM_NATURE_BEACH`)로 정렬됐다 — 예전 `01020300`(해안/섬 일반)은 오분류였고
   구 feature는 alembic 0027로 정리한다.

### 3.2 `FestivalPublicView`

| 필드 | 타입 | 출처 |
|---|---|---|
| `feature_id` | string | `FeatureDetailResponse.feature_id` |
| `festival_name` | string | `Feature.name` |
| `venue_name` | string/null | `EventDetail.venue_name` |
| `event_start_date`, `event_end_date` | date/null | `EventDetail.starts_on`, `EventDetail.ends_on` |
| `event_status` | string | `scheduled`, `ongoing`, `ended`, `unknown` 계산값 |
| `lon`, `lat` | number/null | `Feature.coord` |
| `address` | object | 구조화 `Address` |
| `road_address`, `jibun_address` | string/null | `address`에서 projection |
| `sido_code`, `sigungu_code` | string/null | feature/address |
| `festival_content` | string/null | primary source raw payload `fstvl_co` 또는 detail payload |
| `organizer_name` | string/null | `detail.payload.organizer_name` |
| `provider_org_name` | string/null | `detail.payload.provider_org_name` |
| `auspc_instt_name`, `suprt_instt_name` | string/null | primary source raw payload |
| `phone_number` | string/null | `EventDetail.tel` |
| `homepage_url` | string/null | `urls.homepage` 또는 visitkorea enrichment |
| `reference_date` | date/null | primary source raw payload `reference_date` |
| `marker_icon`, `marker_color` | string/null | feature marker |
| `source_providers` | array[string] | SourceLink |
| `updated_at` | datetime | feature updated_at |

`event_status` 계산:

- `ongoing`: `starts_on <= today <= ends_on`
- `scheduled`: `starts_on > today`
- `ended`: `ends_on < today`
- `unknown`: 시작/종료일이 부족한 경우

## 4. 구현 결정과 후속

1. 해수욕장 판별은 `detail.place_kind='beach'`를 1차로 쓴다. KHOA provider category는
   DA-D-07로 `01050100`(`TOURISM_NATURE_BEACH`)로 정렬됐고(구 `01020300`은 오분류, 0027
   cleanup), 어느 경우든 공개 view 판별은 category 단일값에 의존하지 않는다.
2. KHOA 해수욕장 폭/길이/재질은 공개 schema에 nullable 필드로 열어 두고,
   현재는 `facility_info` 또는 primary raw payload에 값이 있으면 projection한다.
   provider 모델 보강은 후속 task로 분리한다.
3. 수질·KHOA index·latest weather는 이번 구현에서 null/빈 배열로 고정한다. 별도
   marine 표면 또는 weather metric 확장은 후속 결정으로 둔다.
4. 축제 상세 content/주최/주관/후원/reference_date는 `source_records.raw_data`의
   primary source payload를 함께 읽어 projection한다.
5. `docs/tripmate-rest-api.md`는 이 표면을 TripMate T-130 차단 해소 조건으로 유지한다.

## 5. 테스트 기준

- 공개 해수욕장 list/detail은 `place_kind=beach` 픽스처와 category drift 픽스처를 모두
  포함한다.
- festival monthly는 시작일·종료일 겹침, 좌표 없음, 종료일 없음, multi-month event를
  검증한다.
- 목록은 `meta.page.next_cursor`를 사용하고 `data.next_cursor`를 만들지 않는다.
- TripMate 변환 테스트는 `BeachPublicView`/`FestivalPublicView` 픽스처를 고정해
  `docs/api/public.md` 셰입과 동기화한다.
