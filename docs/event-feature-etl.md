# event-feature-etl.md — VisitKorea (TourAPI) 축제·행사 ETL

본 문서는 VisitKorea(TourAPI)의 축제/행사 데이터를 `event` feature로 정규화하는
ETL이다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-visitkorea-api` |
| dataset_key | `visitkorea_festival_events` |
| Feature.kind | `event` |
| source_entity_type | `festival` |
| 상세 테이블 | `feature_event_details` |
| 코드 entrypoint | `krtour.map.providers.visitkorea` (변환), `krtour.map.events` (loader) |
| 갱신 주기 | 1일 1회 (`VISITKOREA_FESTIVAL_FULL_SCAN_INTERVAL_DAYS=1`) |
| 기본 page size | 1000 |

## 2. 범위 / 책임

- `python-visitkorea-api`: TourAPI REST 호출, typed model (`SearchFestivalItem`),
  pagination (`iter_pages`).
- `python-krtour-map`: typed model → `Feature(kind=event)` + `EventDetail` +
  `SourceRecord` + `SourceLink` 변환, 이미지 → RustFS, DB 적재.
- TripMate: Dagster asset wiring, schedule, retry, 알림.

## 3. Provider 경계

`python-visitkorea-api`의 public client + typed model 직접 사용. wrapper 금지
(ADR-006). 부족한 endpoint는 provider 라이브러리에서 먼저 안정화.

## 4. dataset 매핑

| 항목 | 값 |
|------|----|
| natural key | `content_id` (VisitKorea PK) |
| FeatureKind | `event` |
| detail table | `feature_event_details` |
| category | event는 `EventDetail.event_kind`(`festival`/`concert`/`exhibition` 등)로 1차 분류. `features.category` 컬럼에는 `01000000` `TOURISM` (대분류) 또는 행사 성격에 맞는 `01040*` (문화시설) 카테고리 — 공식 카테고리 트리는 `docs/category.md` §4 |
| source_role | `primary` |
| marker_icon | `star` |
| marker_color | `P-11` (자홍) |

## 5. 주소·좌표

- 좌표: `item.mapx` (lon), `item.mapy` (lat) → `PlaceCoordinate(lat, lon)`. 없으면
  None (event는 좌표 nullable 허용).
- 주소: `item.addr1`, `item.addr2`, `item.zipcode` → `kraddr.base.Address`.
- **`item.area_code` / `item.sigungu_code` / `item.l_dong_regn_cd` /
  `item.l_dong_signgu_cd`는 TourAPI 자체 코드 — 법정동코드로 저장 X**.
  raw/payload에만. 좌표 reverse geocoding으로 법정동코드 확정.

## 6. 파일 (RustFS)

```python
def festival_to_file_sources(item, *, feature_id, source_record_key):
    sources = []
    if item.first_image:
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=item.first_image,
            role="primary", display_order=0,
            provider="python-visitkorea-api",
            dataset_key="visitkorea_festival_events",
            source_record_key=source_record_key,
        ))
    if item.first_image2 and item.first_image2 != item.first_image:
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=item.first_image2,
            role="thumbnail", display_order=1,
            provider="python-visitkorea-api",
            dataset_key="visitkorea_festival_events",
            source_record_key=source_record_key,
        ))
    return sources
```

자세한 RustFS 패턴은 `docs/feature-files-rustfs.md`.

## 7. DB 적재

### 7.1 collect

```python
from krtour.map.providers.visitkorea import festival_to_bundles

async def collect_visitkorea_festival_events(
    client: AsyncVisitKoreaClient,
    *,
    fetched_at: datetime,
    event_start_date: str = "20000101",
    page_size: int = 1000,
    max_pages: int | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    bundles = []
    async for page in client.aiter_pages(
        client.asearch_festival, event_start_date=event_start_date,
        page_no=1, num_of_rows=page_size, max_pages=max_pages,
    ):
        for item in page.items:
            bundle = await festival_to_bundle(
                item, fetched_at=fetched_at, reverse_geocoder=reverse_geocoder,
            )
            bundles.append(bundle)
    return bundles
```

### 7.2 load

```python
from krtour.map.events import VisitKoreaFestivalLoadResources, load_visitkorea_festival_result

resources = VisitKoreaFestivalLoadResources(
    client=visitkorea_client,
    session=async_session,
    rustfs_store=rustfs_store,
    reverse_geocoder=reverse,
)
result = await load_visitkorea_festival_result(resources, run)
```

`load_feature_rows()` 내부 적재 순서:
1. `source_records`
2. `features`
3. `feature_event_details`
4. `feature_files` (RustFS 업로드 완료 후 메타)
5. `feature_opening_periods` / `feature_special_days` (있을 시)
6. `source_links`
7. `provider_sync_state`

commit/rollback은 caller.

## 8. Dagster

| 항목 | 값 |
|------|----|
| asset 이름 (TripMate) | `feature_event_visitkorea_festivals` |
| JOB_SPEC | `krtour.map.providers.visitkorea.JOB_SPEC` |
| suggested cron | `0 3 * * *` (매일 03:00 KST) |
| group | `features_event` |
| ConcurrencyConfig | `visitkorea_api: max_concurrent=1` |

자세한 패턴은 `docs/dagster-boundary.md` §2.

## 9. 검증

### 9.1 fixture 시나리오 (≥ 3)

- `festival_full_scan_seoul_2026_05.json` — 정상 (5건, 이미지 있음)
- `festival_full_scan_empty_response.json` — totalCount=0
- `festival_full_scan_missing_image.json` — `first_image` 없음
- `festival_full_scan_no_coord.json` — `mapx`/`mapy` 없음
- `festival_full_scan_special_chars.json` — 한글-한자 혼합 제목

### 9.2 통합 테스트

- testcontainers PostGIS에 적재 → `feature_event_details` row 검증.
- 같은 입력 2회 적재 → idempotent (rows count 동일, updated_at만 갱신).
- 이미지 업로드 → MinIO testcontainer로 PUT 호출 확인.

### 9.3 EXPLAIN

`features_in_bounds(kinds=[event])` 쿼리가 `idx_features_kind_category`와
`idx_features_event_end` 사용 확인.

## 10. 후속

- TourAPI `searchFestival2` 응답의 `playtime` 구조화 → `EventDetail.opening_hours`
  (별도 PR, 패턴은 `docs/feature-opening-hours.md`).
- 상세 정보 endpoint (`detailIntro1`, `detailInfo1`) 추가 적재 검토 (v2 1차
  범위 외).
- `python-visitkorea-api`에서 부족한 typed field는 그쪽 PR로 안정화.
