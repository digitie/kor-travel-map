# mois-feature-etl.md — `python-mois-api` 활용 feature 적재 (full lifecycle)

본 문서는 `python-mois-api`(행정안전부 지방행정 인허가정보 OpenAPI + localdata
파일 다운로드 라이브러리)를 활용한 본 라이브러리(`kor-travel-map`)의 feature
적재 전체 흐름이다. 4 step lifecycle + 195 업종 슬러그 카탈로그를 다룬다.

> **license `place` 승격의 1차 흐름만 다루는** 좁은 가이드는
> [`docs/etl/mois-license-feature-etl.md`](mois-license-feature-etl.md)가 별도로 있다.
> 본 문서가 상위 개요. 두 문서가 충돌하면 본 문서가 정답.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| 외부 provider | `python-mois-api` (PyPI distribution), `import mois` (ADR-024) |
| GitHub | `digitie/python-mois-api` |
| 본 라이브러리 변환 모듈 | `kortravelmap.providers.mois` (ADR-022) |
| 본 라이브러리 loader 모듈 | `kortravelmap.mois` |
| canonical provider name | `python-mois-api` (legacy alias `python-krmois-api`, `krmois`, `mois`) |
| Feature.kind | `place` (1차) |
| source_entity_type | `license_place` |
| 상세 테이블 | `feature_place_details` |
| dataset_key prefix | `mois_*` |
| 의존 ADR | ADR-024 (naming), ADR-022 (namespace), ADR-006 (no wrapper), ADR-003 (function library) |

## 2. 외부 라이브러리 책임 분리

| 책임 | 위치 |
|------|------|
| OpenAPI 195개 업종 호출 (`{slug}/info`, `{slug}/history`) | `python-mois-api` `MoisClient` |
| 호출당 페이지 순회 (`numOfRows ≤ 100`) | `python-mois-api` `iter_records`, `iter_updated`, `iter_history_at` |
| 조건 파라미터 `cond[FIELD::OP]=value` | `python-mois-api` `Condition` + `ConditionOperator` |
| `file.localdata.go.kr` 195+13 = 208종 파일 다운로드 | `python-mois-api` `LocalDataFileClient` |
| CP949 CSV → typed `LocalDataRecord` | `python-mois-api` |
| EPSG:5174 → WGS84 좌표 변환 | `python-mois-api` (`pyproj` 기반) |
| 날짜/시각/숫자 정규화 | `python-mois-api` `mois.convert` |
| **SQLite/SpatiaLite source DB 적재** (`mois_place_master`, `mois_place_detail`, `mois_batch_sync_log`) | `python-mois-api` `sync_localdata_source_db` |
| 영업중/폐업 row iterator | `python-mois-api` `iter_open_place_records`, `iter_closed_place_records` |
| 디버그 UI | `python-mois-api`의 **별도 패키지** `mois-debug-ui` (mois-api ADR-007) |
| **source DB → feature DB 승격 (영업중만)** | **본 라이브러리** `kortravelmap.mois.load_*` |
| 폐업/취소 trigger로 feature 삭제 | **본 라이브러리** `delete_mois_license_features_*` |
| Dagster asset wiring / cron / 알림 | kor-travel-map Dagster (`packages/kor-travel-map-dagster/`, ADR-045) |

## 3. lifecycle 4 step

```
[Step A] localdata 파일 → mois_place_master (source DB)
            ↓ 주 1회 full + 일 1회 incremental
[Step B] iter_open_place_records → kor_travel_map.features (영업중만)
            ↓ 주 1회 full sync + delete_not_in
[Step C] iter_updated (이력조회) → 변경 row만 source DB UPSERT → feature 반영
            ↓ 일 1회 야간
[Step D] MoisClient.get cond[MNG_NO::EQ] → admin/사용자 detail (on-demand)
            (feature DB write 없음, 캐시만)
```

### 3.1 Step A — source DB sync (mois-api 자체)

**메인 라이브러리 변환 계층은 관여하지 않는다**. ADR-045 이후 kor-travel-map Dagster
asset이 `python-mois-api`의 `sync_localdata_source_db()`를 직접 호출한다.

```python
# packages/kor-travel-map-dagster/assets/mois_source_db_sync.py
from mois import LocalDataFileClient
from mois.db import sync_localdata_source_db

@asset(group_name="source_db", retry_policy=...)
async def mois_source_db_full(ctx, mois_async_session):
    async with LocalDataFileClient() as files:
        result = await sync_localdata_source_db(
            mois_async_session, files,
            service_slugs=ALL_195_SLUGS,
            sync_kind="localdata_full",
            commit=True,
        )
    ctx.add_output_metadata({
        "scanned": MetadataValue.int(result.scanned_count),
        "upserted": MetadataValue.int(result.upserted_count),
        "open": MetadataValue.int(result.open_count),
        "closed": MetadataValue.int(result.closed_count),
    })
    return result
```

주기: 주 1회 full (예: `0 2 * * 1`). source DB는 영업중/폐업 모두 영구 보존
(감사/이력 분석용).

### 3.2 Step B — feature 승격 (`mois_license_features_bulk`)

source DB의 영업중 row 중 **승격 슬러그**만 feature로.

```python
# PinVi apps/etl/assets/feature_place_mois_licenses.py
from mois.db import iter_open_place_records
from kortravelmap import AsyncKorTravelMapClient

@asset(
    group_name="features_place",
    deps=[mois_source_db_full],            # source DB sync 후
)
async def feature_place_mois_licenses(
    ctx, mois_async_session, kor_travel_map_client: AsyncKorTravelMapClient,
):
    promoted_slugs = kor_travel_map_client.providers.mois.PROMOTED_SERVICE_SLUGS
    snapshot_keys: set[str] = set()

    async for batch in _batched(
        iter_open_place_records(mois_async_session, service_slugs=promoted_slugs),
        size=kor_travel_map_client.providers.mois.DEFAULT_BATCH_SIZE,
    ):
        bundles = list(
            kor_travel_map_client.providers.mois.license_records_to_bundles(
                batch, fetched_at=ctx.run.created_timestamp,
            )
        )
        result = await kor_travel_map_client.load_feature_bundles(bundles)
        snapshot_keys.update(b.source_record.source_entity_id for b in bundles)

    # snapshot 외 feature 삭제
    deleted = await kor_travel_map_client.delete_mois_license_features_not_in(snapshot_keys)
    ctx.log.info("snapshot_sync_complete",
                 extra={"snapshot": len(snapshot_keys), "deleted": deleted})
```

`dataset_key`: **`mois_license_features_bulk`**.

### 3.3 Step C — incremental refresh (`mois_license_features_history`)

이력조회(`{slug}/history`)로 변경분만 source DB UPSERT 후 feature 반영.

```python
@asset(group_name="features_place")
async def feature_place_mois_licenses_incremental(
    ctx, mois_client, mois_async_session, kor_travel_map_client,
):
    sync_state = await kor_travel_map_client.get_sync_state(
        provider="python-mois-api",
        dataset_key="mois_license_features_history",
    )
    since = sync_state.cursor.get("last_modified_at") if sync_state else _default_since()
    promoted_slugs = kor_travel_map_client.providers.mois.PROMOTED_SERVICE_SLUGS

    changed_mng_nos: set[str] = set()
    for slug in promoted_slugs:
        # source DB UPSERT (mois-api API 직접 호출 + 본 라이브러리는 reconcile만)
        async for row in mois_client.iter_updated(slug, since=since, source_modified=True):
            await _upsert_to_source_db(mois_async_session, row, slug=slug)
            changed_mng_nos.add(row["MNG_NO"])

    # 변경된 row만 feature 재승격
    async for batch in _batched(
        iter_open_place_records(
            mois_async_session,
            service_slugs=promoted_slugs,
            mng_nos=changed_mng_nos,           # 신규 fields 필요 (mois-api 후속)
        ),
        size=500,
    ):
        bundles = list(kor_travel_map_client.providers.mois.license_records_to_bundles(batch))
        await kor_travel_map_client.load_feature_bundles(bundles)

    # 폐업 처리
    closed = [r for r in source_db_rows if r.status_category == "CLOSED"]
    if closed:
        await kor_travel_map_client.delete_mois_license_features_for_records(closed)

    await kor_travel_map_client.upsert_sync_state(ProviderSyncState(
        provider="python-mois-api",
        dataset_key="mois_license_features_history",
        cursor={"last_modified_at": kst_now().strftime("%Y%m%d%H%M%S")},
        last_success_at=kst_now(),
    ))
```

`dataset_key`: **`mois_license_features_history`**. 주기: 일 1회 (예: `0 3 * * *`).

### 3.4 Step D — on-demand detail (`mois_license_detail`)

관리자/사용자가 특정 사업장 detail을 요청하면 OpenAPI 직접 호출. **feature DB
write 없음**. 캐시만 (TTL 15분 권장).

```python
# PinVi apps/api/app/routers/admin.py
@router.get("/admin/mois/places/{mng_no}")
async def get_mois_place_detail(
    mng_no: str,
    slug: str = Query(...),                  # 사업장 slug
    mois_client = Depends(get_mois_client),
):
    rows = await mois_client.get(
        slug, conditions={"MNG_NO": ("EQ", mng_no)},
    )
    if not rows:
        raise HTTPException(404)
    return {"data": rows[0]}
```

`dataset_key`: **`mois_license_detail`** (운영 로그용; feature DB 미반영).

## 4. 195 업종 카탈로그 (요약)

`OPENAPI_SERVICES` 카테고리 7종 × 약 28업종 = 195건. 본 라이브러리에서 승격
대상은 **40종 안팎** (식음/숙박/관광/문화/MICE/스포츠/레저 + 일부 편의).

### 4.1 승격 슬러그 (`KOR_TRAVEL_MAP_MOIS_PROMOTED_SLUGS`)

| 묶음 | slug |
|------|------|
| **식음** (6) | `general_restaurants`, `rest_cafes`, `tourist_restaurants`, `tourist_entertainment_restaurants`, `foreigners_entertainment_restaurants`, `bakeries` |
| **숙박** (8) | `tourist_accommodations`, `lodgings`, `tourist_pensions`, `rural_homestays`, `foreigner_city_homestays`, `general_campgrounds`, `auto_campgrounds`, `hanok_experience` |
| **관광/문화** (9) | `tourism_businesses`, `tourist_cruises`, `city_tour_businesses`, `tourist_railways`, `museums_and_art_galleries`, `performance_halls`, `tourist_performance_halls`, `tourist_theater_entertainment`, `traditional_temples` |
| **테마파크/휴양** (5) | `amusement_facilities_other`, `general_amusement_facilities`, `comprehensive_amusement_facilities`, `special_resorts`, `comprehensive_resorts` |
| **MICE** (2) | `international_convention_facilities`, `international_convention_planners` |
| **스포츠/레저** (9) | `golf_courses`, `ski_resorts`, `yacht_marinas`, `horse_riding`, `sledding`, `swimming_pools`, `ice_rinks`, `comprehensive_sports_facilities`, `registered_sports_facilities` |
| **쇼핑/도시여가** (선택, 3) | `large_scale_retail_stores`, `movie_theaters`, `public_baths` |

총 **42종**. 코드는 `kortravelmap.providers.mois.PROMOTED_SERVICE_SLUGS:
frozenset[str]`로 상수화.

### 4.2 제외 슬러그 (`KOR_TRAVEL_MAP_MOIS_EXCLUDED_SLUGS`)

여행 도메인 무관 → 본 라이브러리에서 가져오지 않는다:

| 묶음 | 사유 |
|------|------|
| 미용/세탁 (4) | 여행 도메인 무관: `beauty_salons`, `barber_shops`, `laundries`, `medical_laundry` |
| 주유/LPG (3) | OpiNet이 더 정확: `oil_retailers`, `petroleum_alt_fuel_retailers`, `lpg_equipment_manufacturers` |
| 동물 (4) | 의료/사육: `animal_hospitals`, `animal_pharmacies`, `pet_grooming`, `animal_boarding` |
| 오락/도시여가 (8) | 사회적 가치 낮음: `billiard_halls`, `video_viewing_rooms`, `karaoke_rooms`, `dance_halls`, `dance_academies`, `pc_bangs`, `film_screenings`, `golf_practice_ranges` |
| 의료/안경 (2) | 응급/지역 의원은 별도 의료 dataset 검토: `optical_shops`, `over_the_counter_medicine_stores` |
| 자원환경 (44) | 거의 모두 skip (목재/계량기/가스/하수/폐기물 사업자) |
| 기타 (32) | 행정/광고/직업/장례 (전부 skip 또는 보조) |
| 식품 공급망 (27) | 식음 직접 아님: `contract_catering`, `food_freezing_refrigeration`, ... |
| 문화 공급망 (15) | 배급/제작: `game_distributors`, `film_producers`, ... |
| 동물 공급망/사육 (12) | 사육/도축/사료 |
| 건강 시설 (8) | 부속의료기관/산후조리/의료법인 등 (의료 dataset 별도 검토) |

총 **약 159종** 제외 (전체 195 - 승격 약 42 = 제외 약 153 + 카테고리 자유 4건).

제외 slug 정확한 set은 코드 상수 (`kortravelmap.providers.mois.EXCLUDED_SERVICE_SLUGS`).
새 slug 추가 시 ADR + 표 갱신.

### 4.3 후속 검토 (skip 분류이지만 별도 dataset 검토 후보)

| 묶음 | 후보 |
|------|------|
| 의료 (POI) | `hospitals`, `clinics`, `pharmacies` (응급/지역 의원 dataset) — 별도 ADR + dataset_key `mois_medical_*` |
| 도시 여가 (제한적) | `local_culture_centers`, `cultural_art_corporations` |
| 동반동물 (반려 동반 여행) | `animal_hospitals`, `pet_grooming` (선택) |

위 결정 보류 — 현 단계 PROMOTED_SLUGS만 1차 범위.

## 5. dataset_key 카탈로그

| dataset_key | step | 주기 | 입력 source | 출력 |
|-------------|------|------|------------|------|
| `mois_license_features_bulk` | B | 주 1회 | `iter_open_place_records` | snapshot 동기화 + delete_not_in |
| `mois_license_features_history` | C | 일 1회 | `iter_updated` (LAST_MDFCN_PNT) | 변경 row UPSERT |
| `mois_license_features_closed` | B/C 부속 | 주 1회 | `iter_closed_place_records` | feature 삭제 |
| `mois_license_detail` | D | on-demand | `MoisClient.get` cond[MNG_NO::EQ] | 캐시만, feature DB 미반영 |

(Step A의 source DB sync는 본 라이브러리 dataset이 아님 — `python-mois-api`
자체가 `mois_batch_sync_log`에서 추적.)

## 6. PlaceDetail 매핑

```python
PlaceDetail(
    feature_id=feature_id,
    place_kind=PROMOTED_PLACE_KIND_BY_SLUG[record.service_slug],   # 예: "restaurant"
    phones=[record.telno] if record.telno else [],
    business_hours=None,                  # mois는 영업시간 X (POI 후속에서)
    facility_info=_facility_info(record),
    license_date=record.license_date,
    biz_number=None,                      # mois는 사업자등록번호 미제공
    payload={
        "mng_no": record.mng_no,
        "status_code": record.status_code,
        "status_name": record.status_name,
        "detail_status_code": record.detail_status_code,
        "detail_status_name": record.detail_status_name,
        "opn_authority_code": record.opn_authority_code,
        # 업종별 specific_data (mois detail JSON)
        "specific_data": record.detail.specific_data,
    },
)
```

### 6.1 `PROMOTED_PLACE_KIND_BY_SLUG`

category 코드는 `docs/architecture/category.md` §4 표 참조. **본 라이브러리는 음식점 세부
업태 분류가 없는 카테고리 체계라서 식음은 대부분 `FOOD_RESTAURANT` 부모(`02010000`)
또는 베이커리 / 카페 leaf에 매핑된다.** 한식/양식 등 세부 매핑은 추가 ADR
없이는 자동 결정 어려움.

| slug | place_kind | category 코드 (권고) | Tier path |
|------|-----------|---------------------|-----------|
| `general_restaurants` | `restaurant` | `02010100` `FOOD_RESTAURANT_KOREAN` (기본) 또는 `02010000` 부모 | 식음 > 음식점 > (한식) |
| `rest_cafes` | `cafe` | `02020100` `FOOD_CAFE_COFFEE` 또는 `02020000` 부모 | 식음 > 카페 |
| `tourist_restaurants` | `restaurant_tourist` | `02010000` `FOOD_RESTAURANT` 부모 (관광식당 전용 코드 없음) | 식음 > 음식점 |
| `tourist_entertainment_restaurants` | `restaurant_entertainment_tourist` | `02010800` `FOOD_RESTAURANT_BAR` (주점 trees) | 식음 > 음식점 > 주점 |
| `foreigners_entertainment_restaurants` | `restaurant_entertainment_foreigner` | `02010800` `FOOD_RESTAURANT_BAR` | 동일 |
| `bakeries` | `bakery` | `02011000` `FOOD_RESTAURANT_BAKERY` | 식음 > 음식점 > 베이커리 |
| `tourist_accommodations` | `lodging_tourist_hotel` | `03010100` `LODGING_HOTEL_TOURIST` | 숙박 > 호텔 > 관광호텔 |
| `lodgings` | `lodging_general` | `03040100` `LODGING_MOTEL_GENERAL` (또는 `03010000` 부모) | 숙박 > 모텔 > 일반 |
| `tourist_pensions` | `lodging_pension` | `03050100` `LODGING_PENSION_TOURISM` | 숙박 > 펜션 > 관광펜션 |
| `rural_homestays` | `lodging_rural_homestay` | `03050200` `LODGING_PENSION_RURAL` | 숙박 > 펜션 > 농어촌민박 |
| `foreigner_city_homestays` | `lodging_city_homestay_foreigner` | `03070100` `LODGING_GUESTHOUSE_GENERAL` | 숙박 > 게스트하우스 |
| `general_campgrounds` | `lodging_campground_general` | `03060000` `LODGING_CAMPGROUND` (부모) | 숙박 > 캠핑장 |
| `auto_campgrounds` | `lodging_campground_auto` | `03060100` `LODGING_CAMPGROUND_AUTO` | 숙박 > 캠핑장 > 오토캠핑장 |
| `hanok_experience` | `lodging_hanok` | `03070200` `LODGING_GUESTHOUSE_HANOK` | 숙박 > 게스트하우스 > 한옥체험 |
| `tourism_businesses` | `tourism_business_office` | `01000000` `TOURISM` (대분류 — 전용 코드 없음, 후속 ADR로 신설 검토) | 관광 |
| `tourist_cruises` | `tourism_cruise` | `01080300` `TOURISM_ACTIVITY_CRUISE` | 관광 > 액티비티 > 관광유람선 |
| `city_tour_businesses` | `tourism_city_tour` | `01080000` `TOURISM_ACTIVITY` (부모) | 관광 > 액티비티 |
| `tourist_railways` | `tourism_railway` | `01080200` `TOURISM_ACTIVITY_RAIL_CABLE` | 관광 > 액티비티 > 관광궤도 |
| `museums_and_art_galleries` | `museum_art_gallery` | `01040000` `TOURISM_CULTURAL_FACILITY` (부모) — 박물관/미술관 추정 시 `01040100`/`01040200` 분기 | 관광 > 문화시설 |
| `performance_halls` | `performance_hall` | `01040301` `TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_GENERAL` | 관광 > 문화시설 > 공연장 > 일반 |
| `tourist_performance_halls` | `performance_hall_tourist` | `01040302` `TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_TOURISM` | 동일 > 관광공연장 |
| `tourist_theater_entertainment` | `theater_tourist_entertainment` | `01040302` `TOURISM_CULTURAL_FACILITY_PERFORMANCE_HALL_TOURISM` (공유) | 동일 |
| `traditional_temples` | `temple_traditional` | `01070100` `TOURISM_HERITAGE_TEMPLE` | 관광 > 국가유산 > 전통사찰 |
| `amusement_facilities_other` | `theme_park_other` | `01010400` `TOURISM_THEME_PARK_EXPERIENCE` 또는 `01010000` 부모 | 관광 > 테마파크 |
| `general_amusement_facilities` | `theme_park_general` | `01010102` `TOURISM_THEME_PARK_AMUSEMENT_SMALL` | 관광 > 테마파크 > 놀이공원 > 중소형 |
| `comprehensive_amusement_facilities` | `theme_park_comprehensive` | `01010101` `TOURISM_THEME_PARK_AMUSEMENT_LARGE` | 동일 > 대형 |
| `special_resorts` | `resort_special` | `03020100` `LODGING_RESORT_CONDO` 또는 `03020000` 부모 | 숙박 > 리조트 |
| `comprehensive_resorts` | `resort_comprehensive` | `03020200` `LODGING_RESORT_COMPLEX` | 숙박 > 리조트 > 종합휴양업 |
| `international_convention_facilities` | `mice_convention_facility` | `01000000` `TOURISM` (대분류) — MICE 전용 코드 없음 (후속 ADR) | 관광 |
| `international_convention_planners` | `mice_convention_planner` | 동일 | 동일 |
| `golf_courses` | `golf_course` | `01080100` `TOURISM_ACTIVITY_GOLF` | 관광 > 액티비티 > 골프장 |
| `ski_resorts` | `ski_resort` | `01080400` `TOURISM_ACTIVITY_LEISURE_SPORTS` (스키 전용 코드 없음) | 관광 > 액티비티 > 레저스포츠 |
| `yacht_marinas` | `yacht_marina` | `01080400` `TOURISM_ACTIVITY_LEISURE_SPORTS` | 동일 |
| `horse_riding` | `horse_riding` | `01080400` | 동일 |
| `sledding` | `sledding` | `01080400` | 동일 |
| `swimming_pools` | `swimming_pool` | `01080400` | 동일 (또는 워터파크 카테고리 `01010200`) |
| `ice_rinks` | `ice_rink` | `01080400` | 동일 |
| `comprehensive_sports_facilities` | `sports_facility_comprehensive` | `01080400` | 동일 |
| `registered_sports_facilities` | `sports_facility_registered` | `01080400` | 동일 |
| `large_scale_retail_stores` | `retail_large_scale` | `05050000` `CONVENIENCE_DEPARTMENT_STORE` (백화점) 또는 `05030000` 마트 | 편의 > 백화점 / 마트 |
| `movie_theaters` | `movie_theater` | `01040400` `TOURISM_CULTURAL_FACILITY_CINEMA` | 관광 > 문화시설 > 영화관 |
| `public_baths` | `public_bath` | `04020100` `HOT_SPRING_SPA_SAUNA_BATHHOUSE` | 온천·스파 > 찜질방·사우나 > 목욕장업 |

> 참고: 본 라이브러리 카테고리 체계는 음식점 세부 업태(한식/양식/일식/중식)
> 자동 분류 데이터를 제공하지 않는다. 식음 슬러그는 부모 `02010000` 또는
> 첫 leaf `02010100`(한식)을 기본으로 두고, 향후 자동 분류 데이터가 생기면
> ADR로 매핑 정밀화. **사용자 결정 위임 항목 (검토 부탁)**.

상수는 `kortravelmap.providers.mois.PROMOTED_PLACE_KIND_BY_SLUG: Mapping[str, str]`.

### 6.2 `facility_info` 구성

업종별 mois `specific_data` JSON 필드를 facility_info로 promote:

```python
def _facility_info(record: PlaceRecord) -> dict:
    base = {
        "service_slug": record.service_slug,
        "category": record.category,
        "subtype_name": record.subtype_name,
        "sales_method_name": record.sales_method_name,
    }
    # 건물/면적
    if record.facility_area or record.total_area or record.total_floor_count:
        base["building"] = {
            "facility_area_m2": record.facility_area,
            "total_area_m2": record.total_area,
            "floors_ground": record.ground_floor_count,
            "floors_underground": record.underground_floor_count,
            "floors_total": record.total_floor_count,
            "use": record.building_usage_name,
        }
    # 의료 (응급/지역 의원 dataset 추가 시 사용)
    if record.bed_count or record.healthcare_worker_count:
        base["medical"] = {
            "bed_count": record.bed_count,
            "sickbed_count": record.sickbed_count,
            "healthcare_worker_count": record.healthcare_worker_count,
            "hospital_room_count": record.hospital_room_count,
            "specialties": record.medical_subject_names,
            "institution_type": record.medical_institution_type_name,
        }
    # 식음
    if record.sanitation_business_status_name or record.water_supply_facility_type_name:
        base["food"] = {
            "sanitation_status": record.sanitation_business_status_name,
            "water_facility_type": record.water_supply_facility_type_name,
            "business_type": record.business_type_name,
            "multi_use": record.multi_use_business_place_yn == "Y",
        }
    # 문화/스포츠
    if record.culture_sports_business_type_name:
        base["culture_sports"] = {
            "type": record.culture_sports_business_type_name,
            "designation_date": record.designation_date,
            "facility_total_scale": record.facility_total_scale,
        }
    return base
```

## 7. 좌표·주소

| mois 필드 | 처리 |
|----------|------|
| `source_x`, `source_y` (EPSG:5174) | `payload.epsg5174` 보존 |
| `lat`, `lon` (WGS84) | `Feature.coord = Coordinate(lon=lon, lat=lat)` |
| `road_address`, `lot_address` | `kortravelmap.dto.Address` (display + road/jibun 분리) |
| `road_zip`, `lot_zip` | `payload.zips` |
| `legal_dong_code` (mois 제공) | `features.legal_dong_code` 직접 사용 |
| `road_name_code` | `features.road_name_code` |
| `building_management_number` | `features.road_address_management_no` |
| `opn_authority_code` (개방자치단체코드) | **법정동코드 아님!** `payload.opn_authority_code`만 |

mois가 `legal_dong_code`를 직접 제공하므로 reverse geocoder는 **검증/보강 용도**
(필요 시):
- legal_dong_code 있으면 그대로 사용
- 없거나 검증 필요 시 좌표 reverse geocoder로 보강
- 충돌 시 `AddressMatchReport(match_level="legal_dong_conflict")` 기록

## 8. provider 변환 함수 (계약)

```python
# kortravelmap.providers.mois
PROVIDER: Final[str] = "python-mois-api"
DEFAULT_BATCH_SIZE: Final[int] = 500
DATASET_KEY_BULK: Final[str] = "mois_license_features_bulk"
DATASET_KEY_HISTORY: Final[str] = "mois_license_features_history"
DATASET_KEY_CLOSED: Final[str] = "mois_license_features_closed"
DATASET_KEY_DETAIL: Final[str] = "mois_license_detail"

PROMOTED_SERVICE_SLUGS: Final[frozenset[str]] = frozenset({...})    # §4.1
EXCLUDED_SERVICE_SLUGS: Final[frozenset[str]] = frozenset({...})    # §4.2
PROMOTED_PLACE_KIND_BY_SLUG: Final[Mapping[str, str]] = {...}       # §6.1
PROMOTED_CATEGORY_BY_SLUG: Final[Mapping[str, str]] = {...}

def license_record_to_bundle(
    record: PlaceRecord,                          # mois.db.PlaceRecord
    *,
    fetched_at: datetime,
    dataset_key: str = DATASET_KEY_BULK,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> FeatureBundle:
    """source DB의 PlaceRecord → FeatureBundle (place + detail + source)."""
    ...

def license_records_to_bundles(
    records: Iterable[PlaceRecord],
    *,
    fetched_at: datetime | None = None,
    dataset_key: str = DATASET_KEY_BULK,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> Iterator[FeatureBundle]:
    ts = fetched_at or kst_now()
    for record in records:
        if record.service_slug in EXCLUDED_SERVICE_SLUGS:
            continue
        if record.service_slug not in PROMOTED_SERVICE_SLUGS:
            continue                              # PROMOTED만
        if not record.is_open:
            continue                              # 영업중만
        yield license_record_to_bundle(record, fetched_at=ts, dataset_key=dataset_key,
                                        reverse_geocoder=reverse_geocoder)
```

`source_entity_id`: `record.mng_no` (25자 관리번호).

`source_natural_key`: `f"{record.service_slug}::{record.mng_no}"` (slug 변경 시
다른 feature로 인식되도록). 구분자는 **`::`** — `make_feature_id` /
`make_source_record_key`는 구성요소 내부 `|`를 금지(ValueError)하므로 `kma`의
`alert_id::region_code` 패턴과 동일하게 맞춘다 (Sprint 4a 구현 시 확정). MOIS
mng_no는 `|`를 포함하지 않는다.

## 9. loader (`kortravelmap.mois`)

```python
async def load_mois_license_features_bulk(
    session: AsyncSession,
    records: Iterable[PlaceRecord],
    *,
    file_store: FileStore | None = None,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> FeatureLoadResult:
    """소량 batch UPSERT (단위 테스트/admin trigger 용)."""
    bundles = list(license_records_to_bundles(records, reverse_geocoder=reverse_geocoder))
    return await load_feature_bundles(session, bundles, file_store=file_store)

async def collect_and_load_mois_license_features_bulk(
    session: AsyncSession,
    mois_session: AsyncSession,
    *,
    reverse_geocoder: ReverseGeocoder | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> FeatureLoadResult:
    """전체 영업중 snapshot 적재 + 부재 row 삭제."""
    snapshot_keys: set[str] = set()
    total = FeatureLoadResult.empty()
    async for batch in _batched(
        iter_open_place_records(mois_session, service_slugs=PROMOTED_SERVICE_SLUGS),
        size=batch_size,
    ):
        bundles = list(license_records_to_bundles(batch, reverse_geocoder=reverse_geocoder))
        result = await load_feature_bundles(session, bundles)
        snapshot_keys.update(b.source_record.source_entity_id for b in bundles)
        total = total.merge(result)
    deleted = await delete_mois_license_features_not_in(session, snapshot_keys)
    return total.with_deleted(deleted)

async def delete_mois_license_features_not_in(
    session: AsyncSession,
    snapshot_source_entity_ids: set[str],
) -> int:
    """snapshot에 없는 mois license feature 일괄 soft-delete."""
    ...

async def delete_mois_license_features_for_records(
    session: AsyncSession,
    records: Iterable[PlaceRecord],
) -> int:
    """폐업/취소 row의 feature 삭제 (Step C 동반)."""
    ...
```

bulk insert가 30k 파라미터 초과 가능 → `psycopg.copy_*` 자동 분기 (ADR-013,
`docs/architecture/performance.md` §5).

## 10. Dagster

| asset (PinVi) | dataset_key | step | suggested cron | deps |
|------------------|-------------|------|---------------|------|
| `mois_source_db_full` | (Step A, mois-api 자체 책임) | A | `0 2 * * 1` (주 1회 월) | — |
| `mois_source_db_incremental` | (Step A 옵션) | A | `0 3 * * *` (일 1회) | mois_source_db_full |
| `feature_place_mois_licenses` | `mois_license_features_bulk` | B | `0 4 * * 1` (월 04:00) | mois_source_db_full |
| `feature_place_mois_licenses_incremental` | `mois_license_features_history` | C | `0 5 * * *` (일 05:00) | mois_source_db_incremental |
| `feature_place_mois_licenses_closed_purge` | `mois_license_features_closed` | B/C 부속 | `0 6 * * 1` | feature_place_mois_licenses |

ConcurrencyConfig: `mois_api: max_concurrent=1` (rate limit 보호 + bulk 적재
직렬화).

## 11. provider_sync_state cursor

| dataset_key | cursor 키 | 의미 |
|-------------|----------|------|
| `mois_license_features_bulk` | `last_snapshot_at` | 마지막 full snapshot 시각 |
| `mois_license_features_history` | `last_modified_at` (`YYYYMMDDHHMMSS`) | `LAST_MDFCN_PNT::GTE` 입력 |
| `mois_license_features_closed` | `last_closed_check_at` | 마지막 closed 점검 시각 |

## 12. 검증

### 12.1 fixture (≥ 3 케이스/slug 묶음)

권고 fixture (`tests/fixtures/mois/`):
- `license_promoted_restaurant.json` — `general_restaurants` 영업중 정상
- `license_promoted_hotel.json` — `tourist_accommodations` 영업중
- `license_promoted_traditional_temple.json` — `traditional_temples` 영업중
- `license_excluded_billiards.json` — `billiard_halls` (EXCLUDED → skip)
- `license_excluded_pet_grooming.json` — `pet_grooming` (EXCLUDED → skip)
- `license_closed_status.json` — 폐업 row (적재 안 됨 확인)
- `license_unknown_slug.json` — 매핑 안 된 slug (`data_integrity_violations`)
- `license_no_coord.json` — 좌표 변환 실패 (`Feature.coord=None`)
- `license_history_modified.json` — 이력조회로 받은 변경 row (Step C)

### 12.2 통합 테스트

- testcontainers PostGIS 적재 → 영업중 row 개수 + PROMOTED slug만 적재 확인
- snapshot에서 빠진 feature `delete_mois_license_features_not_in` 동작
- EXCLUDED slug 적재 시도 → skip (feature 생성 안 됨)
- 폐업 row 적재 시도 → skip
- 같은 source record 2회 적재 → idempotent (row count 동일)
- bulk 100k row → `psycopg.copy_*` 분기 자동
- 이력조회 cursor 갱신 → `provider_sync_state.cursor.last_modified_at` 정확

### 12.3 EXPLAIN

`features_in_bounds(kinds=[place])` + `category LIKE 'FOOD_%'` (식음 필터)가
`idx_features_kind_category` 사용 확인.

## 13. 안티패턴 (PR 차단)

| 안티패턴 | 대안 |
|---------|------|
| `python-mois-api` wrapper class 생성 | `MoisClient` 직접 사용 (ADR-006) |
| KRMOIS 전용 물리 컬럼 추가 (예: `features.opn_authority_code`) | `Feature.detail.payload`에 JSON |
| `opn_authority_code`를 `legal_dong_code`로 저장 | 별도 컬럼/payload (다른 의미) |
| EXCLUDED slug feature 적재 | skip + `data_integrity_violations` 기록 |
| 폐업 row를 feature DB에 보존 | 즉시 삭제, source DB는 보존 |
| `MoisClient.get()`을 Step B/C ETL에서 직접 호출 | source DB iter 사용 |
| ETL에서 매 호출마다 새 `MoisClient` 생성 | Dagster resource로 재사용 |
| `service_key`를 fixture/log에 평문 저장 | `<REDACTED>` 자동 마스킹 |

## 14. 후속 (별도 ADR + PR)

- **의료 dataset 추가**: `hospitals`, `clinics`, `pharmacies` → dataset_key
  `mois_medical_features` (응급/지역 의원 POI 활용). 별도 ADR.
- **반려동물 동반 여행 dataset**: `animal_hospitals`, `pet_grooming` 등 선택적
  추가.
- **mois `validate_address_geocoding_probe` 활용**: 본 라이브러리의 reverse
  geocoder 검증 helper.
- **mois debug UI 연계**: `packages/mois-debug-ui/`의 `/api/places`를 본
  라이브러리 디버그 UI (`kortravelmap.api`)에서 iframe/링크로 연결.
- **source DB 분리 옵션**: source DB(`mois_*`)는 kor-travel-map 운영 경계 안에 둔다.
  PinVi 공유 DB에 두지 않는다(ADR-045/046).

## 15. 환경변수

| 변수 | 사용 |
|------|------|
| `DATA_GO_KR_SERVICE_KEY` | mois OpenAPI 서비스키 (mois-api가 직접 읽음) |
| `MOIS_SQLITE_PATH` | mois-api source DB 경로 (mois-api debug UI 연계 시) |
| `KOR_TRAVEL_MAP_PG_DSN` | 본 라이브러리 feature DB |

mois-api의 환경변수는 mois-api 책임. 본 라이브러리 settings에 중복 정의 X.

## 16. 운영 체크리스트

- [ ] mois-api source DB 부트스트랩 완료 (`sync_localdata_source_db` 1회 full)
- [ ] mois-api `mois_batch_sync_log`에 정기 갱신 기록
- [ ] PROMOTED slug 42종 적재 확인 (`select count(*) ... where provider='python-mois-api'`)
- [ ] EXCLUDED slug 적재 안 됨 확인 (sample slug 1개 직접 cond[OPN_SVC_ID]로 raw 조회 후 feature DB 없음 확인)
- [ ] 폐업 row 적재 안 됨 확인
- [ ] 이력조회 cursor 갱신 정상 (`provider_sync_state.last_success_at`)
- [ ] feature `legal_dong_code` 채움 비율 ≥ 95% (mois 자체 제공 + reverse geocoder 보강)
- [ ] BRIN(updated_at) 인덱스 효율
- [ ] mois debug UI (`http://127.0.0.1:8611`) 운영자 접근 가능 (내부망 only)

## 17. v1 → v2 변경 요약

| v1 | v2 |
|----|----|
| `provider="python-krmois-api"` | `provider="python-mois-api"` (ADR-024) |
| `from krmois import ...` | `from mois import ...` |
| `kor_travel_map.krmois` | `kortravelmap.mois` |
| `kor_travel_map.providers.krmois` | `kortravelmap.providers.mois` |
| `dataset_key="krmois_license_features"` | `dataset_key="mois_license_features_bulk"` (4 step 명시) |
| Step B만 다룸 (license 승격) | Step A/B/C/D 전체 lifecycle |
| 승격 slug 명시 X (제외만) | PROMOTED_SERVICE_SLUGS 42종 명시 (§4.1) |
| `KRMOIS_*` 상수 | `MOIS_*` 상수 |
| 환경변수 `KRMOIS_SERVICE_KEY` | `DATA_GO_KR_SERVICE_KEY` (mois-api 표준) |

마이그레이션 절차 (코드 작성 단계):
1. import path rename
2. 상수 rename (`KRMOIS_*` → `MOIS_*`)
3. `provider` 컬럼 데이터 마이그레이션 SQL (`UPDATE provider_sync.source_records
   SET provider='python-mois-api' WHERE provider='python-krmois-api'` + 종속
   테이블 동일)
4. dataset_key 마이그레이션 (`krmois_license_features` → `mois_license_features_bulk`)
5. integration test로 검증
6. 별도 ADR 또는 ADR-024 §후속에서 절차 박음
