# mois-license-feature-etl.md — MOIS 인허가 → place 승격 (Step B 좁은 가이드)

본 문서는 행정안전부 localdata 인허가(MOIS) 데이터의 영업중 row만 `place`
feature로 승격하는 ETL의 Step B 좁은 가이드다. 폐업/취소/제외 업종은 본
라이브러리 feature DB에 보존하지 않는다.

> 전체 4단계 lifecycle (Step A source DB sync, Step B 승격, Step C
> incremental, Step D on-demand)은 `docs/etl/mois-feature-etl.md`가 정답.
> 본 문서는 Step B의 상세 매핑·제외 슬러그·시설 정보만 집중적으로 다룬다.

> **구현 현황 (Sprint 4, 2026-06-01 — PR#115~#137)**: SPRINT-4 §2.1 Step 라벨
> 기준(A=bulk / B=incremental / C=closed / D=detail)으로 **전 단계 구현 완료**.
> - 변환 코어: `providers/mois.py` — `MoisLicensePlaceRecord` Protocol +
>   `license_records_to_bundles`(async, PROMOTED 42 매핑 + EXCLUDED skip) +
>   `license_source_entity_id`(자연키 `{slug}::{mng_no}`).
> - Step A bulk: `mois.sync_mois_license_features_bulk` / `run_mois_license_bulk_job`
>   (advisory lock + `ops.import_jobs` + snapshot soft-delete).
> - Step B incremental: `mois.run_mois_license_incremental_job` (prune 없음 +
>   `provider_sync_state` cursor 전진, `infra/sync_state_repo.py`).
> - Step C closed: `mois.run_mois_license_closed_job` → `inactivate_features_by_
>   source_entity_ids` (status='inactive', ADR-017).
> - Step D detail: debug-ui `GET /debug/mois-license/{license_id}` +
>   `feature_repo.get_primary_source_detail` (캐시만, 적재 없음).
> - CLI: `ktmctl import mois <file> --mode {bulk|incremental|closed} [--cursor]`.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-mois-api` |
| dataset_key | `mois_license_features_bulk` |
| Feature.kind | `place` |
| source_entity_type | `license_place` |
| 상세 테이블 | `feature_place_details` |
| 코드 entrypoint | `kortravelmap.providers.mois` (변환), `kortravelmap.mois` (loader) |
| 갱신 주기 | 주 1회 (full update) |

## 2. 범위 / 책임

- `python-mois-api`: localdata zip 다운로드 + MOIS source DB 갱신, raw/localdata
  detail 보존, 영업중/폐업 iterator (`iter_open_place_records`,
  `iter_closed_place_records`), 주소 EPSG:5174 → WGS84 변환.
- `kor-travel-map`: 영업중 `PlaceRecord` → `Feature(kind=place)` + `PlaceDetail`,
  service slug 필터링, 오래된 MOIS feature 삭제, job metadata.
- kor-travel-map Dagster: MOIS source DB session, feature DB session, reverse
  geocoder, transaction, 알림.

wrapper/adapter/gateway 금지. 누락은 `python-mois-api`에서 먼저.

## 3. 적재 정책

| 정책 | 설명 |
|------|------|
| 영업중만 승격 | `iter_open_place_records()`만. 폐업/취소/미상 제외 |
| 제외 업종 | `MOIS_EXCLUDED_SERVICE_SLUGS` (아래 §4) |
| 주간 full update | snapshot에 없는 feature는 `delete_mois_license_features_not_in(snapshot)` |
| 폐업/취소 처리 | `iter_closed_place_records()` + `delete_mois_license_features_for_records(...)` |
| MOIS 전용 물리 컬럼 | **추가 금지**. 모든 정보는 `Feature.detail` JSONB |

## 4. 제외 service slug

```python
MOIS_EXCLUDED_SERVICE_SLUGS = frozenset({
    # 미용 / 세탁
    "beauty_salons", "barber_shops",
    "laundries", "medical_laundry",
    # 주유 / LPG
    "oil_retailers", "petroleum_alt_fuel_retailers", "lpg_equipment_manufacturers",
    # 동물
    "animal_hospitals", "animal_pharmacies", "pet_grooming", "animal_boarding",
    # 오락
    "billiard_halls", "video_viewing_rooms", "karaoke_rooms",
    "golf_practice_ranges", "dance_halls", "dance_academies",
    "film_screenings", "pc_bangs",
    # 의료 / 안경
    "optical_shops", "over_the_counter_medicine_stores",
})
```

위 업종은 여행 도메인과 거리가 멀거나 다른 source가 더 정확 → MOIS에서는
가져오지 않는다.

## 5. 승격 매핑 (`MOIS_LICENSE_PROMOTION_MAPPINGS`)

service slug → `PlaceDetail.place_kind` + category:

| service slug | place_kind | category prefix |
|--------------|-----------|----------------|
| `general_restaurants` | `restaurant` | `FOOD_*` |
| `chinese_restaurants` | `restaurant_chinese` | `FOOD_RESTAURANT_CHINESE` |
| `tourist_restaurants` | `restaurant_tourist` | `FOOD_RESTAURANT_TOURIST` |
| `cafes` (식품접객-휴게음식점 중) | `cafe` | `FOOD_CAFE` |
| `tourist_hotels` | `lodging_hotel` | `LODGING_HOTEL` |
| `pension_lodging` | `lodging_pension` | `LODGING_PENSION` |
| `traditional_houses` | `lodging_hanok` | `LODGING_HANOK` |
| `tourist_attractions` | `attraction` | `TOURISM_*` |
| `cinemas` | `cinema` | `LEISURE_CINEMA` |
| `golf_courses` | `golf_course` | `LEISURE_GOLF` |
| `swimming_pools` | `swimming_pool` | `LEISURE_SWIMMING` |
| `aquariums` | `aquarium` | `TOURISM_AQUARIUM` |
| `theme_parks` | `theme_park` | `LEISURE_THEME_PARK` |
| `museums` (MOIS 분류) | `museum` | `CULTURE_MUSEUM` |
| ... (전체 매핑은 코드 상수) |

매핑되지 않는 새 slug → ADR + 매핑 추가. 모르는 slug는 적재 skip (`data_integrity_violations`에 `unknown_service_slug` 기록).

## 6. 주소·좌표

- 원본 좌표: EPSG:5174 → WGS84 변환 (`python-mois-api`가 처리).
- 주소: `admin_address` (지번) + `road_address` (도로명) → `kortravelmap.dto.Address`.
- `mng_no` (관리번호 25자): `source_entity_id`.
- **`sigun_code` (관할기관)는 법정동코드 아님** — raw/payload만.
- reverse geocoder **필수** — 정확한 `legal_dong_code` 확정 위해.

## 7. `Feature.detail` 계약 (MOIS 전용)

```python
{
    "selected_source": {
        "provider": "python-mois-api",
        "dataset_key": "mois_license_features_bulk",
        "service_slug": "general_restaurants",
        "mng_no": "...",
        "title": "...",                          # 사업장명
        "local_authority_code": "..."            # 시군구 코드
    },
    "selected_coordinate": {
        "lat": 37.50, "lon": 127.02,
        "epsg5174_x": ..., "epsg5174_y": ...,
        "source": "mois_admin_address"
    },
    "category_confidence": "high",               # high/medium/low
    "match_level": "legal_dong_exact",           # AddressMatchReport
    "visible_status": "visible",
    "visible": True,
    "license_status": "open",
    "license_dates": {
        "license_date": "2010-03-15",
        "permit_date": null,
        "operation_start_date": null
    },
    "address_codes": {
        "legal_dong_code": "1111010100",
        "sigungu_code": "11110",
        "admin_dong_code": "...",
        "road_name_code": "..."
    }
}
```

## 8. `PlaceDetail.facility_info` (업종별)

```python
# 의료
{"bed_count": 30, "inpatient_rooms": 10, "medical_staff": 25, "specialties": ["내과", "정형외과"]}

# 식품
{"food_sanitation_status": "good", "water_facility_type": "municipal",
 "business_type": "일반음식점", "detailed_type": "한식",
 "area_m2": 80.5}

# 숙박
{"facility_size": "medium", "area_m2": 350.0, "floors": 4,
 "building_use": "lodging", "multiple_use": True}

# 문화/레저/체험
{"culture_sports_type": "공연장", "designation_date": "2015-04-20",
 "area_m2": 200.0, "floors": 2}

# 소매
{"sales_method": "retail", "facility_size": "small"}
```

각 업종별 facility fields는 MOIS localdata의 service-specific 컬럼에서 추출.
스키마는 코드 상수 (`MOIS_FACILITY_FIELD_MAP` — `kortravelmap.providers.mois`).

## 9. DB 적재 흐름

```python
from kortravelmap.mois import (
    MOIS_LICENSE_FEATURE_DATASET_KEY,
    collect_and_load_mois_license_features,
    load_mois_license_feature_result,
    delete_mois_license_features_not_in,
    delete_mois_license_features_for_records,
)

async def run_mois_weekly_update(
    mois_session,                # python-mois-api source DB
    feature_session,             # 본 라이브러리 feature DB
    reverse_geocoder,
):
    # 1. source DB 동기화
    await mois_client.sync_localdata_source_db(mois_session, sync_kind="localdata_full")
    
    # 2. 영업중 row 수집 + feature 적재
    open_records = mois_client.aiter_open_place_records(mois_session)
    snapshot_keys: set[str] = set()
    
    async for batch in _batched(open_records, size=MOIS_LICENSE_DEFAULT_BATCH_SIZE):
        result = await collect_and_load_mois_license_features(
            feature_session, batch, reverse_geocoder=reverse_geocoder,
        )
        snapshot_keys.update(result.upserted_source_entity_ids)
    
    # 3. snapshot에 없는 MOIS feature 삭제
    deleted = await delete_mois_license_features_not_in(feature_session, snapshot_keys)
    
    # 4. 폐업/취소 별도 처리
    closed_records = mois_client.aiter_closed_place_records(mois_session)
    async for batch in _batched(closed_records, size=MOIS_LICENSE_DEFAULT_BATCH_SIZE):
        await delete_mois_license_features_for_records(feature_session, batch)
    
    await feature_session.commit()
```

## 10. Dagster

| 항목 | 값 |
|------|----|
| asset 이름 | `feature_place_mois_licenses` |
| JOB_SPEC | `kortravelmap.providers.mois.JOB_SPEC` |
| suggested cron | `0 2 * * 1` (매주 월 02:00 KST) — 또는 `0 2 5 * *` (월 5일) |
| group | `features_place` |
| ConcurrencyConfig | `mois_api: max_concurrent=1` |

## 11. 검증

### 11.1 fixture (≥ 3)

- `license_promoted_restaurant.json` — 정상 (일반음식점 승격)
- `license_excluded_billiards.json` — 당구장 (제외 업종)
- `license_closed_status.json` — 폐업 row (적재 안 됨 확인)
- `license_unknown_slug.json` — 매핑 안 된 slug (skip + violation)
- `license_no_coord.json` — 좌표 변환 실패

### 11.2 통합 테스트

- testcontainers PostGIS 적재 → 영업중 row 개수 일치
- snapshot에서 빠진 feature 삭제 (`delete_mois_license_features_not_in`)
- 폐업 row 적재 시도 → 생성 안 됨
- 같은 입력 2회 → idempotent

## 12. 후속

- 관리번호 공백 row는 fingerprint 정책을 `python-mois-api`에서 먼저 안정화.
- 새 업종 추가는 ADR + `MOIS_LICENSE_PROMOTION_MAPPINGS` 업데이트.
- MOIS sigun_code → 법정동코드 변환 표 (`python-mois-api` 책임).
