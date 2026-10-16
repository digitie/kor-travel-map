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
> - ~~Step D detail: debug-ui `GET /debug/mois-license/{license_id}`~~ (2026-09-03 제거 — 운영에서 도달 불가였고 UI 호출부도 없었다. raw payload는 `GET /v1/features/{feature_id}/sources`가 제공한다) +
>   `feature_repo.get_primary_source_detail` (캐시만, 적재 없음).
> - CLI: `ktmctl import mois <file> --mode {bulk|incremental|closed} [--cursor]`.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-mois-api` |
| dataset_key | `mois_license_features_bulk` |
| Feature.kind | `place` |
| source_entity_type | `license_place` |
| 상세 테이블 | `feature_places` |
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

## 13. 재개형 적재와 운영 절차 (ADR-108)

> §9의 단일 transaction 흐름은 **더 이상 Dagster 경로가 아니다.** Dagster
> `feature_place_mois_licenses`는 `kortravelmap.dagster.mois_chunked_load`로 적재한다.
> 결정과 근거는 [ADR-108](../adr/108-mois-resumable-chunked-load.md).

### 13.1 동작 요약

| 항목 | 값 |
|------|----|
| commit 단위 | 업종 하나 안의 최대 500행 chunk(`MOIS_LOAD_CHUNK_SIZE`) |
| 재개 키 | `source_entity_id`(`{slug}::{mng_no}`) + `raw_payload_hash` — 이미 같은 payload로 적재돼 있고 primary feature가 active면 변환·지오코딩 없이 재관측만 |
| 지오코딩 | chunk 좌표를 중복 없이 모아 bounded 동시 선조회(`KOR_TRAVEL_MAP_MOIS_GEOCODE_CONCURRENCY`, 기본 2), run 수명 LRU 5만 좌표. 원천 `legal_dong_code`가 있는 행은 조회하지 않는다 |
| run 크기 | `KOR_TRAVEL_MAP_MOIS_LOAD_RUN_BUDGET_SECONDS`(기본 14,400초)까지만 새 chunk 시작 → 정상 종료 + run tag `kor_travel_map.mois_load.outcome=budget_exhausted` |
| 이어 달리기 | `feature_place_mois_licenses_continuation_sensor`(기본 **STOPPED**) — 마지막 run이 성공·`budget_exhausted`면 같은 run_config로 다음 run. 실패 run은 잇지 않는다 |
| retry | 1회, 5분 뒤(재시도도 이어 간다). 재관측 충돌은 run 안에서 그 chunk만 최대 2회 다시 |
| 시간 기준 | run 시작(run record `start_time`) — 상한은 `min(설정, run 상한 tag - 30분)` |
| 소실 하한 | 데이터 무효 drop을 업종 누적·관측 200행 이상에서만 판정(> 50%면 commit 전 실패). 지오코더 원인 drop은 따로 세고 다음 run이 다시 시도 |
| geo 장애 | 최근 조회 20건 이상 중 80% 이상이 빈 답이면 고정 기준점과 마지막 좋은 좌표를 둘 다 다시 묻고, 하나라도 빈 답이면 chunk 적재 전 upstream 장애로 실패(행을 버리지 않는다). 둘 다 답하면 계속 |
| 빈 답 행 | 어느 검증 모드에서도 적재하지 않는다(off 포함) — 다음 run이 다시 시도 |
| 역지오코딩 불가 표식 | run 끝에, degraded가 아닌 업종에서 문턱 초과가 없던 chunk의 빈 답 행만(무엇이든 degraded면 조회 50행 미만 업종도 제외) finding `mois_reverse_geocode_unresolvable`(info)로 기억한다. 같은 payload면 30일 동안 조회·적재하지 않는다(`mois_known_unresolvable`). payload가 바뀌거나 30일이 지나거나 finding을 닫으면 다시 조회하고, 풀리면 표식을 닫는다 |
| degraded | **조회한 행** 대비 빈 답 비율이 업종 또는 run(조회 50행 이상)에서 `KOR_TRAVEL_MAP_MOIS_GEOCODE_DEGRADED_RATIO`(기본 5%) 초과, 또는 같은 업종에서 "문턱 초과 + probe 통과" 3회 → run은 실패하지 않지만 봉인·sync 성공 없음, tag `kor_travel_map.mois_load.geocode_degraded`, metadata `mois_geocode_degraded*`·`mois_geocoded_rows`·`mois_geo_probes`·`mois_geo_probe_passes` |
| 연속 degraded | 직전 완료 전체 run까지의 사슬(`budget_exhausted` 포함) 중 degraded 전체 run이 있으면(최근 500 run 안에서 완료 run에 닿지 못하면 degraded로 본다) degraded로 끝난 이번 완료 run은 FAILURE(재시도 없음) — 붉은 run |
| freshness SLA | migration 405가 MOIS bulk policy에 `stale_after_minutes=57600`(40일) — 봉인·sync 성공이 그보다 오래 없으면 `/v1/ops/datasets`가 overdue |
| 봉인·sync 성공 | 전 업종을 한 run 안에서 끝까지 본 run만(`outcome=complete` + 전 업종) |
| 큐 경로 | MOIS뿐인 요청은 접수 시 409 `PROVIDER_DEDICATED_JOB_ONLY`. 섞인 요청은 MOIS를 건너뛰고 `done` + error_message로 남긴다. 실행할 것이 MOIS뿐인 cache target 요청은 `failed` + `error_code=PROVIDER_DEDICATED_JOB_ONLY` |
| 이어 달리기 정지 | 실패 run, 미종료 run 존재, 마지막 run이 상한의 절반 이상을 받고도 새 행 0건(`…records_converted=0`, `…budget_seconds`·`…budget_available_seconds`)으로 상한 도달 |
| 원천 SQLite | `/opt/dagster/state/mois/mois_source.db`(이미지 기본값, appuser 소유). 운영 compose가 그 디렉터리에 named volume을 붙인다 |

run 결과 metadata: `mois_load_outcome`, `mois_load_slugs_completed`, `mois_load_stopped_in_slug`,
`mois_load_records_{seen,unchanged,converted}`, `mois_load_chunks_committed`,
`mois_reverse_geocode_{live_calls,cache_hits,prefetch_failures}`. 업종 하나가 끝날 때마다
run 로그에 `MOIS 업종 <slug> 완료`가 남는다.

### 13.2 업종 하나로 검증하기 (전체 적재 전, prod)

**전제.** (1) 이 변경을 담은 Map pair가 회전돼 있다. (2) Manager의 MOIS 원천 volume 변경이
설치돼 code-server가 `/opt/dagster/state/mois`에 volume을 갖는다. (3) n150 사전 점검
(`~/preflight.sh`)이 PASS다. 이어 달리기 sensor는 **끈 채로** 둔다.

1. **원천 sync.** `mois_localdata_source_sync` job을 한 번 돌린다(전국 42업종, 실측 약 24분·5GB).
   Map API의 schedule "지금 실행" 또는 Dagster UI. 끝나면 `<db>.synced` marker가 생긴다.
2. **작은 업종 고르기.** code-server 컨테이너에서 영업중 행 수를 읽기 전용으로 센다.

   ```bash
   docker exec <map-dagster-code-server-container> python -c "import os,sqlite3; c=sqlite3.connect('file:'+os.environ['KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH']+'?mode=ro', uri=True); print(c.execute('SELECT service_slug, count(*) FROM mois_place_master WHERE is_open = 1 GROUP BY 1 ORDER BY 2').fetchall())"
   ```

   수십~수백 행인 PROMOTED 업종(예: `yacht_marinas`, `international_convention_facilities`,
   `tourist_railways`) 하나를 고른다.
3. **한 업종만 적재.** 공용 Dagster GraphQL(`http://127.0.0.1:11002/graphql`, n150 안에서)에
   run_config로 업종을 준다. Map API의 "지금 실행"은 run_config를 비워 **전 업종**을 돌리므로
   이 단계에 쓰지 않는다.

   ```bash
   cat > /tmp/mois-one-slug.json <<'JSON'
   {"query": "mutation($p: ExecutionParams!) { launchRun(executionParams: $p) { __typename ... on LaunchRunSuccess { run { runId } } ... on RunConfigValidationInvalid { errors { message } } ... on PythonError { message } } }",
    "variables": {"p": {
      "selector": {"jobName": "feature_place_mois_licenses_job",
                   "repositoryName": "__repository__",
                   "repositoryLocationName": "kortravelmap.dagster.definitions"},
      "runConfigData": {"resources": {"mois_load_plan": {"config": {"service_slugs": ["yacht_marinas"]}}}},
      "executionMetadata": {"tags": [
        {"key": "kor_travel_map.trigger_kind", "value": "manual"},
        {"key": "kor_travel_map.operator", "value": "<operator>"},
        {"key": "kor_travel_map.reason", "value": "ADR-108 one-slug verification"}]}}}}
   JSON
   curl -sS -H 'Content-Type: application/json' --data @/tmp/mois-one-slug.json http://127.0.0.1:11002/graphql
   ```

   기대: run SUCCESS, tag `kor_travel_map.mois_load.outcome=complete`,
   `mois_load_records_seen` = 2단계의 행 수, `mois_load_records_unchanged=0`. 업종 선택 run이므로
   sync 성공·봉인은 남지 않는다(정상).
4. **재개 확인.** 3단계를 그대로 한 번 더 돌린다. 기대: `mois_load_records_unchanged` =
   `mois_load_records_seen`, `mois_load_records_converted=0`, `mois_reverse_geocode_live_calls=0`.
   이것이 "다시 돌려도 이미 적재된 것은 지오코딩·적재하지 않는다"의 실증이다.
5. **(선택) 상한 정지·이어 달리기.** 수천 행 업종으로 `"run_budget_seconds": 60`을 함께 주면
   첫 chunk 뒤 `budget_exhausted`로 끝난다. sensor를 잠시 켜면 같은 run_config로 이어 달려
   `complete`로 끝나는지 본다. 확인 뒤 sensor를 다시 끈다.
6. **적재 확인(읽기 전용).** 공용 PG의 Map DATABASE에서:

   ```sql
   SELECT count(*) FROM provider_sync.source_entities AS e
   JOIN provider_sync.provider_datasets AS d USING (provider_dataset_id)
   WHERE d.provider = 'python-mois-api' AND d.dataset_key = 'mois_license_features_bulk'
     AND e.source_entity_id LIKE 'yacht_marinas::%';
   ```

   3단계 행 수에서 주소/좌표 검증으로 버린 행(`address_validation_dropped_count`)을 뺀 값이다.

### 13.3 전체 적재

1. `KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS`를 168 이상으로 둔다(운영 env) — 캠페인 중 run이
   Phase A를 다시 받지 않게(주간 sync job이 갱신한다). 소유자 결정 사항이다(ADR-108 열린 결정 2).
2. `feature_place_mois_licenses_continuation_sensor`를 켠다.
3. run_config 없이 `feature_place_mois_licenses_job`을 한 번 띄운다(Map API "지금 실행" 가능).
   이후 run은 sensor가 잇는다. 마지막 run이 `complete`(전 업종)면 봉인·sync 성공이 남는다.
4. 실패 run이 나오면 sensor는 멈춘다. 원인을 본 뒤 같은 job을 다시 띄우면 이어서 적재한다.

> **geo 릴리스 재지오코딩(ADR-109 accepted, 운영은 [runbook](../runbooks/geo-release-regeocode.md) §4).** geo 데이터 토큰이 바뀌면 릴리스 계획에 이 job 항목이
> run_config 없이 들어가지만 **센서는 내지 않는다**(`SENSOR_MANUAL_OPERATION_KEYS`, #1333 리뷰) — 전국 Phase A·
> 50만 행 변환·snapshot 은퇴를 예정 밖에 돌리지 않으려는 것이다. 운영자가 이 job을 수동 실행하고 끝나면 계획
> 항목을 `skip`한다. fetch는 소스 DB가 TTL 안이면 쿼터를 쓰지 않지만 TTL이 지나면 증분 Phase A sync가
> `apis.data.go.kr`를 부른다 — 위 §13.3의 TTL ≥168 권고를 따른다. `source_mode=replay`는 MOIS에 **없다** —
> `source_records.raw_data`가 record 필드 24개(우편번호·건물관리번호·업종별 시설)를 남기지 않아 golden이
> 실패했다(T-GR-08, ADR-109 결정 7 결과). 제외는 `not_called` **스탬프**가 있는 행뿐 — 스탬프 없는 payload-bjd
> 행은 변환되어 스탬프를 받는다. unchanged 판정에 "스탬프 토큰 == 현재
> 토큰" 조건이, 표식 "알려진 불가" 조건에 토큰 일치가 더해진다. 상세는 [`address-geocoding.md`](address-geocoding.md).
