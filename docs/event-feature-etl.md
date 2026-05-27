# event-feature-etl.md — 전국문화축제표준데이터 + VisitKorea 축제·행사 ETL

본 문서는 축제/행사 데이터를 `event` feature로 정규화하는 ETL이다.

**ADR-042 (2026-05-27) 이후 1차 source 변경**: 종전 VisitKorea TourAPI 단독에서
**전국문화축제표준데이터(`data.go.kr-standard` via `python-datagokr-api`)** 를
1차로, VisitKorea TourAPI는 enrichment(이미지/상세설명/contentId 매핑) 2차로
재구성. visitkorea contentId 매핑이 좋지만 좌표/일자 nullable이 많고 표준
데이터가 행안부 announce 기반으로 안정 → primary 교체. 본 문서의 §1~§4는
1차 source 기준, visitkorea 관련 절은 enrichment 책임으로 보존.

## 1. 문서 정보

| 항목 | 값 (1차) | 값 (enrichment) |
|------|----------|-----------------|
| provider | `data.go.kr-standard` | `python-visitkorea-api` |
| provider 라이브러리 | `python-datagokr-api` | `python-visitkorea-api` |
| dataset_key | `datagokr_cultural_festivals` | `visitkorea_festival_events` |
| Feature.kind | `event` | (enrichment만) |
| source_entity_type | `cultural_festival` | `festival` |
| source_role | `primary` | `enrichment` |
| 상세 테이블 | `feature_event_details` | (별도 row 없음 — enrichment 갱신만) |
| 코드 entrypoint | `krtour.map.providers.standard_data.cultural_festivals_to_bundles` | `krtour.map.providers.visitkorea.festival_to_enrichment_links` |
| 갱신 주기 | 1일 1회 (표준데이터 announce 주기) | 1주 1회 (enrichment 충분) |
| 기본 page size | 1000 | 1000 |

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

### 7.1 collect — 1차 (datagokr 표준데이터, PR#34 구현, ADR-042)

```python
from datetime import datetime, timezone, timedelta
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

KST = timezone(timedelta(hours=9))


async def collect_datagokr_cultural_festivals(
    client: "AsyncDataGoKrClient",     # python-datagokr-api
    *,
    fetched_at: datetime,
    page_size: int = 1000,
    max_pages: int | None = None,
    reverse_geocoder: "ReverseGeocoder | None" = None,
) -> list[FeatureBundle]:
    """전국문화축제표준데이터 page iter → list[FeatureBundle].

    `python-datagokr-api`의 `AsyncDataGoKrClient`는 본 라이브러리가 직접 의존
    하지 않는다 — 호출자가 client + 호출 결과를 본 함수에 넘긴다.
    """
    bundles: list[FeatureBundle] = []
    async for page in client.aiter_pages(
        client.aiter_cultural_festivals,
        page_no=1, num_of_rows=page_size, max_pages=max_pages,
    ):
        # cultural_festivals_to_bundles는 모든 row를 한 fetched_at으로 묶음.
        bundles.extend(
            cultural_festivals_to_bundles(
                page.items,
                fetched_at=fetched_at,
                reverse_geocoder=reverse_geocoder,
            )
        )
    return bundles


# 호출 예시 (TripMate Dagster asset 측):
# fetched = datetime.now(tz=KST)
# bundles = await collect_datagokr_cultural_festivals(
#     datagokr_client, fetched_at=fetched, reverse_geocoder=kraddr_geo,
# )
# await krtour_client.load_feature_bundles(bundles)
```

`cultural_festivals_to_bundles`의 시그니처/Protocol은 `src/krtour/map/providers/
standard_data.py`. fixture/test는 `tests/unit/test_providers_standard_data.py`
(PR#34, 14 case).

### 7.1.5 collect — 2차 enrichment (visitkorea TourAPI, Sprint 2 끝물 별도 PR)

```python
# visitkorea TourAPI는 이미지/상세설명/contentId 매핑만 갱신 — Feature/Source
# Record 본체는 생성하지 않는다. festival_to_enrichment_links가 datagokr로
# 적재된 feature_id와 visitkorea contentId를 source_links(role='enrichment')로
# 잇는다. (Sprint 2 끝물 PR로 구현 예정)
from krtour.map.providers.visitkorea import festival_to_enrichment_links  # 미구현
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
