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
| 상세 테이블 | `feature_events` | (별도 row 없음 — enrichment 갱신만) |
| 코드 entrypoint | `kortravelmap.providers.standard_data.cultural_festivals_to_bundles` | `kortravelmap.providers.visitkorea.festival_to_enrichment_links` |
| 갱신 주기 | 1일 1회 (표준데이터 announce 주기) | 1주 1회 (enrichment 충분) |
| 기본 page size | 1000 | 1000 |

## 2. 범위 / 책임

- `python-visitkorea-api`: TourAPI REST 호출, typed model (`SearchFestivalItem`),
  pagination (`iter_pages`).
- `kor-travel-map`: typed model → `Feature(kind=event)` + `EventDetail` +
  `SourceRecord` + `SourceLink` 변환, 이미지 → RustFS, DB 적재.
- kor-travel-map Dagster: asset wiring, schedule, retry, 알림.

## 3. Provider 경계

`python-visitkorea-api`의 public client + typed model 직접 사용. wrapper 금지
(ADR-006). 부족한 endpoint는 provider 라이브러리에서 먼저 안정화.

## 4. dataset 매핑

### 4.1 1차 — datagokr 전국문화축제표준데이터

| 항목 | 값 |
|------|----|
| natural key | **`name::address` 파생** (ADR-009 `::`) — 원천에 관리번호 컬럼이 **없어** `정규화(축제명)::도로명주소(없으면 지번주소, 둘 다 없으면 빈 문자열)`로 파생한다 (#374). enrichment(visitkorea)의 natural key는 `content_id` |
| FeatureKind | `event` |
| detail table | `feature_events` |
| category | `01090000` 축제·행사. 세부 종류는 `EventDetail.event_kind`로 구분하며 기존 legacy ID seed는 유지한다. |
| source_role | `primary` |
| marker_icon | `star` |
| marker_color | `P-11` (자홍) |

### 4.2 원천 한국어 컬럼 → `CulturalFestivalItem` Protocol 필드

Protocol 필드명은 provider 실모델 `PublicCulturalFestival`(`python-datagokr-api`)
필드명 **그대로**다 (ADR-044 — provider lib가 데이터 정합성 1차 책임, 본 lib는
미러). 종전 Protocol이 발명했던 `management_no`/`road_address`/`festival_name`
류 필드는 #374에서 제거됐다.

| 한국어 컬럼 | Protocol 필드 | 매핑 |
|------------|--------------|------|
| 축제명 | `fstvl_nm` | `Feature.name` — 정규화 후 비면 해당 row **skip** |
| 개최장소 | `opar` | `EventDetail.venue_name` |
| 축제시작일자 | `fstvl_start_date` | `EventDetail.starts_on` |
| 축제종료일자 | `fstvl_end_date` | `EventDetail.ends_on` |
| 축제내용 | `fstvl_co` | `SourceRecord.raw_data`만 |
| 주관기관명 | `mnnst_nm` | `EventDetail.payload['organizer_name']` |
| 주최기관명 | `auspc_instt_nm` | `SourceRecord.raw_data`만 |
| 후원기관명 | `suprt_instt_nm` | `SourceRecord.raw_data`만 |
| 전화번호 | `phone_number` | `EventDetail.tel` (dash 정규화) |
| 홈페이지주소 | `homepage_url` | `SourceRecord.raw_data`만 |
| 관련정보 | `relate_info` | `SourceRecord.raw_data`만 |
| 소재지도로명주소 | `rdnmadr` | `Feature.address.road` + `SourceRecord.raw_address` + 자연키 |
| 소재지지번주소 | `lnmadr` | `Feature.address.legal` (도로명 없을 때 자연키 fallback) |
| 위도 / 경도 | `latitude` / `longitude` (`float`) | `Feature.coord` (`Decimal(str(...))` 변환) |
| 데이터기준일자 | `reference_date` | `SourceRecord.raw_data`만 |
| 제공기관코드 | `instt_code` | `SourceRecord.raw_data`만 |
| 제공기관명 | `instt_nm` | `EventDetail.payload['provider_org_name']` |

## 5. 주소·좌표

- 좌표: `item.mapx` (lon), `item.mapy` (lat) → `Coordinate(lon=..., lat=...)`. 없으면
  None (event는 좌표 nullable 허용).
- 주소: `item.addr1`, `item.addr2`, `item.zipcode` → `kortravelmap.dto.Address`.
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

자세한 RustFS 패턴은 `docs/architecture/feature-files-rustfs.md`.

## 7. DB 적재

### 7.1 collect — 1차 (datagokr 표준데이터, PR#34 구현, ADR-042)

```python
from datetime import datetime, timezone, timedelta
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

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


# 호출 예시 (kor-travel-map Dagster asset 측):
# fetched = datetime.now(tz=KST)
# bundles = await collect_datagokr_cultural_festivals(
#     datagokr_client, fetched_at=fetched, reverse_geocoder=kor_travel_geo,
# )
# await krtour_client.load_feature_bundles(bundles)
```

`cultural_festivals_to_bundles`의 시그니처/Protocol은 `src/kortravelmap/providers/
standard_data.py`. fixture/test는 `tests/unit/test_providers_standard_data.py`
(PR#34, 14 case).

### 7.1.5 collect — 2차 enrichment (visitkorea TourAPI, PR#51 구현)

```python
# visitkorea TourAPI는 이미지/상세설명/contentId 매핑만 갱신 — Feature/Source
# Record 본체는 생성하지 않는다. festival_to_enrichment_links가 datagokr로
# 적재된 feature_id와 visitkorea contentId를 source_links(role='enrichment')로
# 잇는다. (PR#51 구현 완료)
from kortravelmap.providers.visitkorea import festival_to_enrichment_links

# 매칭(datagokr festival ↔ visitkorea)은 이름/지역 fuzzy(ADR-016)이므로
# FestivalMatcher plug-in으로 주입 — match() -> None이면 해당 item 생략.
# links = festival_to_enrichment_links(
#     visitkorea_items, matcher=scoring_matcher, fetched_at=datetime.now(KST),
# )
# 각 원소는 FestivalEnrichment(source_record + source_link[role=enrichment]).
# FeatureFileSource DTO는 Sprint 2-3 — 지금은 이미지 URL이 raw_data에만 보존.
```

시그니처/Protocol(`VisitKoreaFestivalItem` / `FestivalMatcher` / `FestivalMatch`
/ `FestivalEnrichment`)은 `src/kortravelmap/providers/visitkorea.py`. 테스트는
`tests/unit/test_providers_visitkorea.py` (PR#51, 8 case).

### 7.2 load

```python
from kortravelmap.events import VisitKoreaFestivalLoadResources, load_visitkorea_festival_result

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
3. `feature_events`
4. `feature_files` (RustFS 업로드 완료 후 메타)
5. `feature_opening_periods` / `feature_special_days` (있을 시)
6. `source_links`
7. `provider_sync_state`

commit/rollback은 caller.

## 8. Dagster

| 항목 | 값 |
|------|----|
| asset 이름 (PinVi) | `feature_event_visitkorea_festivals` |
| JOB_SPEC | `kortravelmap.providers.visitkorea.JOB_SPEC` |
| suggested cron | `0 3 * * *` (매일 03:00 KST) |
| group | `features_event` |
| ConcurrencyConfig | `visitkorea_api: max_concurrent=1` |

자세한 패턴은 `docs/architecture/dagster-boundary.md` §2.

## 9. 검증

### 9.1 fixture 시나리오 (≥ 3)

- `festival_full_scan_seoul_2026_05.json` — 정상 (5건, 이미지 있음)
- `festival_full_scan_empty_response.json` — totalCount=0
- `festival_full_scan_missing_image.json` — `first_image` 없음
- `festival_full_scan_no_coord.json` — `mapx`/`mapy` 없음
- `festival_full_scan_special_chars.json` — 한글-한자 혼합 제목

### 9.2 통합 테스트

- testcontainers PostGIS에 적재 → `feature_events` row 검증.
- 같은 입력 2회 적재 → idempotent (rows count 동일, updated_at만 갱신).
- 이미지 업로드 → MinIO testcontainer로 PUT 호출 확인.

### 9.3 EXPLAIN

`features_in_bounds(kinds=[event])` 쿼리가 `idx_features_kind_category` 사용 확인.
행사 기간 필터는 subtype 인덱스 `idx_feature_events_period`
(`feature.feature_events (starts_on, ends_on)`, ADR-086)를 탄다.

## 10. 후속

- TourAPI `searchFestival2` 응답의 `playtime` 구조화 → `EventDetail.opening_hours`
  (별도 PR, 패턴은 `docs/architecture/feature-opening-hours.md`).
- 상세 정보 endpoint (`detailIntro1`, `detailInfo1`) 추가 적재 검토 (v2 1차
  범위 외).
- `python-visitkorea-api`에서 부족한 typed field는 그쪽 PR로 안정화.


## #1439 행사 품질 경계

표준축제·국가유산 행사는 시작·종료일과 행사장 이름이 없거나 기간이 역전되면 새 행을
`quarantined`로 생성한다. 원문과 기존 자연키·legacy ID seed·색상은 보존하며 날짜를
수집 연도나 주소로 만들어 채우지 않는다. 종료된 정상 행사는 격리하지 않는다.

중복 후보는 행사 기간·장소를 이름 점수보다 먼저 비교한다. 다른 회차는 제외하고,
근거가 부족하면 자동 병합 제안을 수동 검토로 낮춘다. 실제 병합도 Feature 부모 잠금 뒤
typed 행사 행을 다시 잠가 비교하므로 오래된 검토 큐나 명시 master 요청이 다른 회차를
우회 병합할 수 없다. 날짜 불명 행사의 명시적 수동 판단은 허용한다.
