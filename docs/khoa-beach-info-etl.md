# khoa-beach-info-etl.md — KHOA 해수욕장정보 → place ETL

본 문서는 KHOA(국립해양조사원) 해수욕장 정보를 `place` feature로 적재하는 ETL이다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-khoa-api` |
| dataset_key | `khoa_oceans_beach_info` |
| Feature.kind | `place` |
| source_entity_type | `beach` |
| 상세 테이블 | `feature_place_details` |
| 코드 entrypoint | `krtour.map.providers.khoa`, `krtour.map.beaches` |
| 갱신 주기 | 1일 1회 |
| data.go.kr | `15058519` |
| endpoint | `http://apis.data.go.kr/1192000/service/OceansBeachInfoService1/getOceansBeachInfo1` |

## 2. 범위 / 책임

- `python-khoa-api`: REST 호출, typed model (`OceanBeachInfo`), pagination.
- `python-krtour-map`: typed model → `Feature(kind=place)` + `PlaceDetail`,
  이미지 → RustFS.
- TripMate: Dagster, schedule.

## 3. dataset 매핑

| 항목 | 값 |
|------|----|
| natural key | `시도\|구군\|정점명` 조합 |
| FeatureKind | `place` |
| category | `TOURISM_NATURE_BEACH` (`01050100`) — `krtour.map.category` |
| place_kind | `beach` |
| marker_icon | `swimming` |
| marker_color | `P-07` (하늘색) |
| `KHOA_OCEANS_BEACH_INFO_FULL_SCAN_INTERVAL_DAYS` | 1 |

## 4. 필드 매핑

| provider 필드 | DTO 저장 위치 |
|--------------|--------------|
| `sidoNm` | feature 이름 prefix + natural key 부분 |
| `gugunNm` | feature 이름 + natural key 부분 |
| `staNm` | feature 이름 본체 + natural key 부분 |
| `lat`, `lon` | `Feature.coord` (WGS84) |
| `beachWid` (해변 폭) | `feature_place_details.facility_info["beach_width_m"]` |
| `beachLen` (해변 길이) | `facility_info["beach_length_m"]` |
| `beachKnd` (해변 종류) | `facility_info["beach_type"]` |
| `linkAddr` (관련 URL) | `features.urls.homepage` |
| `linkNm` (관련 사이트명) | detail payload |
| `linkTel` (연락처) | `PlaceDetail.phones[0]` |
| `beachImg` (이미지 URL) | RustFS 적재 후보 (`FeatureFileSource`) |
| 전체 row | `source_records.raw_data` |

## 5. 주소·좌표

- 좌표: WGS84 그대로 (`PlaceCoordinate(lat, lon)`).
- 주소: 기본 `Address(display_address=f"{sidoNm} {gugunNm}")` — 시도/구군 한글만.
- reverse geocoder 권장 — 정확한 `legal_dong_code` + `road_name_code` 보강.

## 6. 파일 (RustFS)

```python
def khoa_beach_to_file_sources(item, *, feature_id, source_record_key):
    if not item.beach_img or not item.beach_img.startswith(("http://", "https://")):
        return []                            # 상대 경로/파일명만은 payload만
    return [FeatureFileSource(
        feature_id=feature_id, source_url=item.beach_img,
        role="primary", display_order=0, file_type="image",
        provider="python-khoa-api",
        dataset_key="khoa_oceans_beach_info",
        source_record_key=source_record_key,
    )]
```

## 7. DB 적재

```python
from krtour.map.beaches import (
    collect_khoa_oceans_beach_info,
    load_khoa_oceans_beach_info_result,
    collect_and_load_khoa_oceans_beach_info,
)

async def run_khoa_beach_full_scan(client, async_session, rustfs_store, reverse_geocoder):
    result = await collect_and_load_khoa_oceans_beach_info(
        async_session, client,
        rustfs_store=rustfs_store, reverse_geocoder=reverse_geocoder,
    )
    await async_session.commit()
    return result
```

전국 시도 (`SIDO_NM` 17종)를 순회하며 각 시도별 page 끝까지. 페이지당
기본 `numOfRows` 1000.

## 8. MOIS 충돌 정책

MOIS 인허가에 같은 위치 / 명칭 해수욕장이 있는 경우:
- MOIS: 영업/시설 정보 우선
- KHOA: 공식 위치/특성/이미지 우선
- 두 feature를 `sibling_group_id`로 묶고 dedup_review_queue에 후보로.

자세한 dedup 패턴은 ADR-016 + `docs/data-model.md` §9.2.

## 9. Dagster

| 항목 | 값 |
|------|----|
| asset 이름 | `feature_place_khoa_beaches` |
| JOB_SPEC | `krtour.map.providers.khoa.JOB_SPEC` (beach) |
| suggested cron | `0 2 10 * *` (매월 10일 02:00 — 해수욕장 신규/변경 드뭄) |
| group | `features_place` |
| ConcurrencyConfig | `khoa_api: max_concurrent=1` |

(`khoa_coastal_notices`는 별도 — `docs/notice-feature-etl.md`)

## 10. 검증

### 10.1 fixture (≥ 3)

- `oceans_beach_info_donghae.json` — 정상 (강원도 동해안 5건, 이미지 있음)
- `oceans_beach_info_no_image.json` — `beachImg` 빈 값
- `oceans_beach_info_no_phone.json` — `linkTel` 없음
- `oceans_beach_info_empty_sido.json` — 빈 시도 (페이지 0)
- `oceans_beach_info_relative_image_path.json` — 상대 경로 (skip 확인)

### 10.2 통합 테스트

- 17 시도 모두 page 1까지 수집 → seed 데이터로 적재.
- 이미지 PUT → MinIO testcontainer.
- 같은 station 적재 2회 → idempotent.

## 11. 후속

- 해수욕장별 marine 지수 (수온, 파고, 적조) — `weather-feature-normalization.md`의
  `beach_marine` weather_domain.
- 해수욕장 운영기간 (개장일/폐장일) → `feature_special_days`로 비개장일 표시.
- 해수욕장 안전 공지 → `docs/notice-feature-etl.md`의 `khoa_coastal_notices`.
