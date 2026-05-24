# krheritage-feature-etl.md — 국가유산청 → place/area/event ETL

본 문서는 국가유산청(`python-krheritage-api`) 데이터를 `place`/`area`/`event`
feature로 적재하는 ETL이다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-krheritage-api` (legacy alias: `python-kheritage-api`) |
| dataset_key (heritage) | `krheritage_heritage_features` (또는 `search_list`) |
| dataset_key (event) | `krheritage_event_list` (또는 `event_list`) |
| dataset_key (GIS) | `krheritage_gis_spca`, `krheritage_gis_3070426` |
| Feature.kind | `place`, `area`, `event` |
| source_entity_type | `heritage`, `heritage_event` |
| 상세 테이블 | `feature_place_details`, `feature_area_details`, `feature_event_details`, `feature_files` |
| 코드 entrypoint | `krtour.map.providers.krheritage`, `krtour.map.heritage` |
| 갱신 주기 (place/area) | 주 1회 |
| 갱신 주기 (event) | 1일 1회 |

## 2. dataset_key 카탈로그

| dataset_key | 출처 | feature |
|-------------|------|---------|
| `krheritage_heritage_features` (alias `search_list`) | `SearchKindOpenapiList` + `SearchKindOpenapiDt` | `place` 또는 `area` |
| `krheritage_gis_spca` | `gis-heritage.go.kr/openapi/xmlService/spca.do` | 좌표/경계 보강 |
| `krheritage_gis_3070426` | 좌표/면적/규제범위/media metadata 공공데이터 GIS | `area` 경계/detail 보강 |
| `krheritage_event_list` (alias `event_list`) | `selectEventListOpenapi` | `event` |
| `15145324` (data.go.kr id) | 고시/공고 후보 | (향후) `notice` 보강 |
| `15041861` (data.go.kr id) | 무형유산 행사 후보 | (향후) `event` 보강 |

## 3. natural key

- place / area: `ccbaKdcd-ccbaAsno-ccbaCtcd` (3 코드 조합)
- event: provider event id `sn`

## 4-pre. 카테고리 매핑 (`docs/category.md` §4)

| 유산 유형 | 권장 category code | Tier path |
|----------|-------------------|-----------|
| 전통사찰 | **`01070100`** `TOURISM_HERITAGE_TEMPLE` | 관광 > 국가유산 > 전통사찰 |
| 궁궐·왕릉 | **`01070200`** `TOURISM_HERITAGE_PALACE_ROYAL_TOMB` | 관광 > 국가유산 > 궁궐·왕릉 |
| 사적·기념물 | **`01070300`** `TOURISM_HERITAGE_HISTORIC_SITE` | 관광 > 국가유산 > 사적·기념물 |
| 한옥·민속마을 | **`01070400`** `TOURISM_HERITAGE_HANOK_FOLK_VILLAGE` | 관광 > 국가유산 > 한옥·민속마을 |
| 미분류 유산 (대분류만) | **`01070000`** `TOURISM_HERITAGE` | 관광 > 국가유산 |
| 천연기념물 (자연) | **`01020400`** `TOURISM_NATURAL_LANDSCAPE_WATERFALL_CAVE` 또는 보존지 area_kind | 자연경관 계열 |
| 무형유산 행사 | event는 카테고리 외 — `EventDetail.event_kind="intangible_heritage"` | n/a |

marker_icon: `monument` / `religious-buddhist` / `castle` / `village` (유형별).
marker_color: `P-07` (자홍 / 보라 계열).

## 4. kind 판정 룰

| 유산 유형 | FeatureKind | 비고 |
|----------|-------------|------|
| 국보 / 보물 / 등록문화유산 | `place` | 대부분 단일 건물/객체 |
| 사적 / 사적 및 명승 / 명승 | `area` | GIS geometry 있으면 |
| 매장유산 | `area` | 발굴지 구역 |
| 천연기념물 | `place` (경계 없음) / `area` (서식지/보호구역 GIS 있음) | 케이스별 |
| 무형유산 — 전수교육관/공연장 | `place` | 시설 |
| 무형유산 — 공연/교육 프로그램 | `event` | 기간성 |

`provider 분류 → kind` 매핑 함수 (`_classify_heritage_kind(item)`):
```python
def _classify_heritage_kind(item) -> FeatureKind:
    if item.ccba_kdcd in ("11", "12"):       # 국보/보물
        return FeatureKind.PLACE
    if item.ccba_kdcd in ("13",):            # 사적
        return FeatureKind.AREA
    if item.ccba_kdcd in ("16",):            # 명승
        return FeatureKind.AREA
    if item.ccba_kdcd in ("15",):            # 천연기념물
        return FeatureKind.AREA if item.has_boundary() else FeatureKind.PLACE
    if item.ccba_kdcd in ("17", "18"):       # 등록문화유산/시도 등
        return FeatureKind.PLACE
    if item.ccba_kdcd in ("31",):            # 무형
        return FeatureKind.PLACE
    return FeatureKind.PLACE                  # default
```

## 5. 상세 매핑

### 5.1 place (`PlaceDetail`)

- `place_kind` ∈ `heritage_site` / `natural_heritage` / `intangible_heritage_venue`
- payload: 지정일, 관리자, 유산유형, provider 분류

### 5.2 area (`AreaDetail`)

- `area_kind` ∈ `heritage_area` / `natural_heritage_area` / `buried_heritage_area`
- `boundary_source` ∈ `gis_3070426` / `gis_spca`
- `area_square_meters`: 면적 (m²)
- `regulation_scope`: 보호/규제 범위
- `administrative_office`: 관리기관
- `features.geom`: GIS `GeoFeature.geometry`를 PostGIS MultiPolygon으로

### 5.3 event (`EventDetail`)

- `event_kind`: `"heritage_event"` (또는 provider 세분)
- `starts_on`/`ends_on`: 행사 기간
- `venue_name`, `tel`: 장소/연락처
- `content_id`: `sn` (provider event id)
- `area_code`/`sigungu_code`: 행정구역 코드 (있으면)

## 6. 좌표·주소

- 좌표: `longitude`/`latitude` (WGS84). `gis_spca`/`gis_3070426`에서 보강.
- 주소: `location_text` 또는 GIS `properties.address`.
- reverse geocoder 권장 — 정확한 `legal_dong_code` 보강.

## 7. 미디어 (RustFS)

```python
def krheritage_to_file_sources(item, *, feature_id, source_record_key):
    sources = []
    for i, img in enumerate(item.images or []):
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=img.image_url,
            role="primary" if i == 0 else "gallery",
            display_order=i, file_type="image",
            alt_text=img.image_description,
            provider="python-krheritage-api",
            dataset_key="krheritage_heritage_features",
            source_record_key=source_record_key,
        ))
    for v in item.videos or []:
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=v.video_url,
            file_type="video", role="gallery", display_order=len(sources),
            provider="python-krheritage-api",
            dataset_key="krheritage_heritage_features",
            source_record_key=source_record_key,
        ))
    for a in item.narrations or []:
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=a.audio_url,
            file_type="audio", role="gallery", display_order=len(sources),
            provider="python-krheritage-api",
            dataset_key="krheritage_heritage_features",
            source_record_key=source_record_key,
        ))
    for doc in item.files or []:
        if doc.file_url.lower().endswith(".pdf"):
            sources.append(FeatureFileSource(
                feature_id=feature_id, source_url=doc.file_url,
                file_type="document", content_type="application/pdf",
                role="gallery", display_order=len(sources),
                provider="python-krheritage-api",
                dataset_key="krheritage_heritage_features",
                source_record_key=source_record_key,
            ))
    return sources
```

## 8. provider client 호출

- place/area: `client.heritage.aiter_all_details(...)` 또는
  `client.search.aiter_all_details(...)`
- event: `client.event.aiter_months(months_back=1, months_ahead=3, ...)`
- GIS: `await client.gis.spca(...)` → `GeoFeatureCollection`

## 9. Run config keys

```python
{
    "page_size": 100,
    "max_pages": None,
    "ccba_kdcd": None,              # 유산 종류 코드 필터
    "ccba_ctcd": None,              # 시도 코드 필터
    "ccba_asno": None,              # 지정번호 필터
    "st_ccba_asdt": None,           # 지정일 시작
    "st_ccba_aedt": None,           # 지정일 종료
    "ccba_cndt": None,              # 시군구 코드
    "ccba_mnm1": None,              # 명칭 부분 일치
    "search_year": None,            # event 검색 연도
    "search_month": None,           # event 검색 월
    "months_back": 1,               # event 과거 N개월
    "months_ahead": 3,              # event 미래 N개월
}
```

camelCase API key는 provider 호출 직전에 snake_case로 변환.

## 10. DB 적재

```python
from krtour.map.heritage import (
    collect_krheritage_heritage_features,
    load_krheritage_heritage_result,
    collect_krheritage_events,
    load_krheritage_event_result,
)

# place/area
result = await collect_krheritage_heritage_features(
    client, run, reverse_geocoder=reverse, rustfs_store=store,
)
await load_krheritage_heritage_result(async_session, result, rustfs_store=store)
await async_session.commit()

# event
event_result = await collect_krheritage_events(
    client, run, reverse_geocoder=reverse,
)
await load_krheritage_event_result(async_session, event_result)
await async_session.commit()
```

## 11. Dagster

| 항목 | place/area | event |
|------|-----------|-------|
| asset 이름 | `feature_place_krheritage_heritage` + `feature_area_krheritage_gis_spca` | `feature_event_krheritage_events` |
| JOB_SPEC | `krtour.map.providers.krheritage.HERITAGE_JOB_SPEC` | `EVENT_JOB_SPEC` |
| suggested cron | `0 2 * * 1` (주 1회 월요일) | `0 3 * * *` (일 1회) |
| group | `features_place` + `features_area` | `features_event` |
| ConcurrencyConfig | `krheritage_api: max_concurrent=1` | 동일 |

## 12. provider_sync_state cursor 예시

```python
ProviderSyncState(
    provider="python-krheritage-api",
    dataset_key="search_list",
    sync_scope="global",
    cursor={"last_page_no": 25, "last_ccba_kdcd": "11"},
)
```

## 13. API 키 환경변수

```
KHERITAGE_API_KEY=...                    # 옛 이름 (호환)
KRHERITAGE_API_KEY=...                   # 권장
DATA_GO_KR_SERVICE_KEY=...               # data.go.kr 통합 키
```

## 14. 검증

### 14.1 fixture (≥ 3)

- `heritage_place_national_treasure.json` — 국보 (place)
- `heritage_area_with_boundary.json` — 사적 (area + geometry)
- `heritage_event_monthly.json` — 무형유산 행사 (event)
- `heritage_place_natural_monument_no_boundary.json` — 천연기념물 (place fallback)
- `heritage_with_pdf_attachment.json` — 문서 첨부 적재

### 14.2 통합 테스트

- place/area kind 판정 (`_classify_heritage_kind`) 분기 전수 검증
- area의 GeoJSON → `features.geom` PostGIS MULTIPOLYGON 적재
- GIS spca 응답으로 area 면적 보강 (`area_square_meters` 갱신)

## 15. 후속

- 무형유산 행사 dataset (`15041861`) 통합
- 고시/공고 dataset (`15145324`) → notice 변환
- GIS 데이터 정합성 (T-201 케이스 F3: 면적 비교)
