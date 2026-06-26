# dagster-boundary.md — kor-travel-map 독립 Dagster 책임 경계

본 문서는 ADR-045 이후 kor-travel-map 독립 프로그램의 Dagster 책임 경계다.

핵심 변경:

- Dagster는 kor-travel-map 독립 프로그램 책임이다.
- kor-travel-map Docker 프로그램이 자체 Dagster webserver/daemon/metadata DB를 가진다.
- 외부 서비스는 kor-travel-map Dagster를 직접 제어하지 않고 kor-travel-map OpenAPI를
  호출한다. 각 외부 서비스가 자체 Dagster를 운영하더라도 kor-travel-map Dagster와
  별개다.
- FastAPI admin API는 feature update request를 만들고, Dagster가 이를 실행한다.
- 메인 라이브러리 `kortravelmap` 자체는 여전히 Dagster를 import하지 않는다.
  Dagster 코드는 별도 패키지 `packages/kor-travel-map-dagster/`에 둔다.

## 1. 책임 매트릭스

| 책임 | 위치 |
|------|------|
| Dagster install / daemon / scheduler | kor-travel-map 독립 프로그램 |
| `@asset`, `@op`, `@job`, `@schedule`, `Definitions` | kor-travel-map Dagster 패키지 |
| Asset/job 이름, dataset_key 매핑, group 구조 | kor-travel-map Dagster |
| Cron schedule (시각, frequency) | kor-travel-map Dagster |
| Asset/job dependency graph | kor-travel-map Dagster |
| `ConcurrencyConfig` 또는 pool 설정(provider 쿼터 보호) | kor-travel-map Dagster |
| Retry policy (`tenacity`/Dagster retry) | kor-travel-map Dagster |
| Run failure 알림 (Slack, Sentry) | kor-travel-map 운영 설정 |
| Dagster metadata DB | `kor_travel_map_dagster` |
| Feature update request queue | kor-travel-map API + `ops.feature_update_requests` |
| Import job progress | kor-travel-map API + `ops.import_jobs` |
| Dagster resource 정의 (engine, file_store, provider clients) | kor-travel-map Dagster |
| **provider 호출 자체** | provider 라이브러리 직접(ADR-006). 단 `kor-travel-concierge-youtube`는 형제 앱 REST export pull(ADR-053) |
| **raw → DTO 변환 (순수 함수)** | **본 라이브러리 (`providers/<name>.py`)** |
| **DB 적재 (raw SQL upsert/COPY)** | **본 라이브러리 (`infra/*_repo.py`)** |
| **객체 저장소 업로드** | **본 라이브러리 (`infra/file_store.py`)** |
| **sync state 갱신** | **본 라이브러리 (`infra/sync_repo.py`)** |
| **import_jobs 큐 관리** | **본 라이브러리 (`infra/jobs_repo.py`)** |
| Dedup scoring / Record Linkage | 본 라이브러리 (`core/scoring.py`) |
| 정합성 검증 룰 (F1~F8) | 본 라이브러리 (`core/integrity.py`, T-201) |
| 외부 사용자/여행계획/POI 도메인 | 외부 서비스 |
| 외부 서비스에서 feature update 요청 | kor-travel-map OpenAPI 호출 |

요약:
- **본 라이브러리**: 변환 + 저장 + 검증 (Dagster 없이도 호출 가능한 함수)
- **kor-travel-map API**: OpenAPI, admin UI, queue 생성, 진행 상태 조회/취소
- **kor-travel-map Dagster**: provider sync, feature update, offline upload load,
  consistency/dedup jobs 실행
- **외부 서비스**: OpenAPI client 소비자

## 1.1 현재 구현된 Feature 적재 asset

`packages/kor-travel-map-dagster`는 1차로 이미 구현·검증된 provider 변환 함수만
Dagster asset으로 연결한다. provider API 호출은 resource가 record iterable을
제공하고, asset은 `raw record → FeatureBundle → 주소/좌표 검증 → PostGIS 적재`
흐름만 소유한다.

| asset 이름 | resource key | dataset_key | group |
|-----------|--------------|-------------|-------|
| `feature_event_datagokr_cultural_festivals` | `datagokr_cultural_festivals` | `datagokr_cultural_festivals` | `features_event` |
| `feature_place_opinet_stations` | `opinet_stations` | `opinet_fuel_station_details` | `features_place` |
| `feature_place_krex_rest_areas` | `krex_rest_areas` | `krex_rest_areas` | `features_place` |
| `feature_notice_krex_traffic_notices` | `krex_traffic_notices` | `krex_traffic_notices` | `features_notice` |
| `feature_place_krheritage_items` | `krheritage_items` | `krheritage_heritage_features` | `features_place` |
| `feature_event_krheritage_events` | `krheritage_events` | `krheritage_event_list` | `features_event` |
| `feature_place_mois_licenses` | `mois_license_records` | `mois_license_features_bulk` 기본 | `features_place` |
| `feature_place_knps_points` | `knps_point_records` | `knps_point_dataset_key` resource | `features_place` |
| `feature_geometry_knps_records` | `knps_geometry_records` | `knps_geometry_dataset_key` resource | `features_geometry` |
| `feature_place_krforest_recreation_forests` | `krforest_recreation_forests` | `krforest_recreation_forests` | `features_place` |
| `feature_place_krforest_arboretums` | `krforest_arboretums` | `krforest_arboretums` | `features_place` |
| `feature_place_standard_museums` | `standard_museums` | `datagokr_museums` | `features_place` |
| `feature_place_standard_tourist_attractions` | `standard_tourist_attractions` | `datagokr_tourist_attractions` | `features_place` |
| `feature_place_standard_parking_lots` | `standard_parking_lots` | `datagokr_parking_lots` | `features_place` |
| `feature_place_khoa_beaches` | `khoa_beaches` | `khoa_beaches` | `features_place` |
| `feature_place_krairport_airports` | `krairport_airports` | `krairport_airports` | `features_place` |
| `feature_weather_airkorea_air_quality` | `airkorea_stations`, `airkorea_air_quality` | `airkorea_air_quality` | `features_weather` |
| `feature_event_visitkorea_enrichment` | `visitkorea_festival_events` | `visitkorea_festival_events` | `features_event` |
| `feature_place_kor_travel_concierge_youtube` | `kor_travel_concierge_youtube_features` | `youtube_place_candidates` | `features_place` |
| `feature_weather_kma_ultra_short_nowcast` | `kma_ultra_short_nowcast` | `kma_ultra_short_nowcast` | `features_weather` |
| `feature_weather_kma_ultra_short_forecast` | `kma_ultra_short_forecast` | `kma_ultra_short_forecast` | `features_weather` |
| `feature_weather_kma_short_forecast` | `kma_short_forecast` | `kma_short_forecast` | `features_weather` |
| `feature_weather_kma_mid_forecast` | `kma_mid_forecast` | `kma_mid_forecast` | `features_weather` |
| `feature_notice_kma_weather_alerts` | `kma_weather_alerts` | `kma_weather_alerts` | `features_notice` |
| `feature_place_mcst_culture` | `mcst_culture_records` (파일데이터 13) | `mcst_<slug>` 13종 (`MCST_FILE_DATASETS`) | `features_place` |

curated overlay asset(`curated_source_metadata` / `curated_feature_candidates` /
`curated_feature_status_sweep` / `curated_pinvi_copy_snapshots`)은 별도 group
`curated_features`로 묶이며, provider 원천 asset 이후 실행된다 — 카탈로그는
`docs/curated-features.md` §7.

`feature_place_krairport_airports`와 `feature_weather_airkorea_air_quality` asset은
현재 §10 정기 schedule이 없다(on-demand 전용 — Dagster UI/API 수동 실행 또는 feature
update request로만 적재).

`kortravelmap.providers.datagokr_file_data`는 설계상 직접 feature 적재 asset이
없다(누락 아님). 그 fileData source는 `curated_source_rules`를 통해 curated
overlay로 들어간다(`docs/curated-features.md`).

공통 resource:

- `kor_travel_map_client`: `AsyncKorTravelMapClient`.
- `reverse_geocoder`: kor-travel-geo REST v2 기반 `ReverseGeocoder`.
  - ADR-058/F-01로 `reverse_geocoder`는 **필수**다 — base resource는
    `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL` 미설정 시 `RuntimeError`를 낸다(조용히
    None을 주지 않는다 — feature_id 결정성 보장).
  - blast radius = `_COMMON_RESOURCE_KEYS`를 `required_resource_keys`로 갖는 모든
    feature-load asset(위 §1.1 provider asset들 + `feature_notice_kma_weather_alerts`
    + `feature_place_mcst_culture`)이 base URL 미설정 시 resource init에서 함께
    실패한다(asset 본문 진입 전 차단).
  - 예외(영향 없음) = 4개 KMA 예보 asset(`feature_weather_kma_ultra_short_nowcast`
    / `feature_weather_kma_ultra_short_forecast` / `feature_weather_kma_short_forecast`
    / `feature_weather_kma_mid_forecast`)은 `_KMA_WEATHER_RESOURCE_KEYS`/
    `_KMA_MID_RESOURCE_KEYS`를 쓰며 `reverse_geocoder`를 포함하지 않는다. curated_*
    / maintenance / offline_upload / sensors / batch_dag도 이 key를 쓰지 않는다.
- `fetched_at`: batch 기준 aware `datetime`(없으면 KST 현재 시각).
- 주소 검증 모드: `strict`|`drop`|`off` 문자열, 기본 `strict`
  (`KorTravelMapSettings.dagster_address_validation`, #376). `strict`는 주소/좌표
  검증 error가 있으면 적재 전 중단한다. 구 `strict_address: bool`은 back-compat로
  남는다(`True`→`strict`, `False`→`off`).

## 2. 표준 Job/Asset 패턴

```python
# packages/kor-travel-map-dagster/assets/visitkorea_festivals.py (후보 위치)
from dagster import asset, RetryPolicy, AssetExecutionContext
from kortravelmap import AsyncKorTravelMapClient
from kortravelmap.infra.sync_state_repo import SyncState  # infra dataclass, not dto

# 주기성은 FreshnessPolicy가 아니라 §10 cron schedule로 잡는다(현재 freshness 미사용).
@asset(
    group_name="features_event",
    retry_policy=RetryPolicy(max_retries=5, delay=60, backoff="exponential"),
    deps=[],  # 다른 asset 의존 없으면
)
async def feature_event_visitkorea_festivals(
    ctx: AssetExecutionContext,
    visitkorea,                # Dagster resource: provider client
    kor_travel_map_client: AsyncKorTravelMapClient,  # Dagster resource
) -> "FeatureLoadResult":
    """raw → bundles → upload files → load → sync state."""
    
    # 1. provider 호출 (provider 라이브러리 직접)
    items = list(await visitkorea.search_festival(...))
    ctx.log.info("fetched", extra={"count": len(items)})

    # 2. 변환 (본 라이브러리 순수 함수)
    bundles = list(
        kor_travel_map_client.providers.visitkorea.festival_to_bundles(
            items, fetched_at=ctx.run.created_timestamp,
        )
    )

    # 3. 적재
    result = await kor_travel_map_client.load_feature_bundles(bundles)
    ctx.add_output_metadata(result.as_metadata())

    # 5. sync state — `upsert_sync_state`는 아직 미구현(후속 PR)이므로 현재는
    #    cursor를 전진시키는 `record_sync_success`(SyncState 반환)를 쓴다.
    await kor_travel_map_client.record_sync_success(
        provider="python-visitkorea-api",
        dataset_key="visitkorea_festival_events",
        cursor={"last_pageNo": items[-1].pageNo if items else None},
    )
    return result
```

5단계는 표준. provider별 차이는 1, 2, 3에 한정 (4, 5는 동일).

## 3. Dagster 없이도 호출 가능 (테스트/디버그)

본 라이브러리의 모든 helper는 Dagster context 없이 호출 가능:

```python
# 통합 테스트 또는 디버그 스크립트
async def main():
    settings = KorTravelMapSettings()
    engine = create_async_engine(settings.pg_dsn.get_secret_value())
    client = AsyncKorTravelMapClient(engine=engine, ...)
    
    # provider 직접 호출
    visitkorea = AsyncVisitKoreaClient(...)
    items = list(await visitkorea.search_festival(...))
    
    # 라이브러리 변환 + 적재
    bundles = list(client.providers.visitkorea.festival_to_bundles(items))
    result = await client.load_feature_bundles(bundles)
    print(result)

asyncio.run(main())
```

이래서 unit/integration 테스트가 Dagster 의존 없이 빠르게 돈다 (`docs/test-
strategy.md`).

## 4. dataset_key 표준 (본 라이브러리 제공)

`kortravelmap.providers.<name>` 모듈마다 `DATASET_KEY: Final[str]` 상수 노출.
kor-travel-map Dagster asset/job이 이 상수를 import해서 dataset_key를 일관 사용:

```python
# packages/kor-travel-map-dagster/assets/visitkorea_festivals.py
from kortravelmap.providers.visitkorea import DATASET_KEY as VISITKOREA_FESTIVAL_DATASET_KEY

# asset 이름 / Dagster metadata에 사용
ctx.log.info("loaded", extra={"dataset_key": VISITKOREA_FESTIVAL_DATASET_KEY})
```

전체 dataset_key 카탈로그는 `docs/architecture/provider-contract.md` §3.

## 5. asset/job 명명 규약

kor-travel-map Dagster의 asset/job 이름 **명명 가이드라인**이다. 실제 구현된 asset
정본은 §1.1이며, 아래 표에서 `feature_<kind>_<provider>_<entity>` 형식과 group이
실제와 다른 행(예: `weather_*`/`notice_*` 접두, `feature_route_krforest_trails`,
`forest_safety_notices`, `khoa_coastal_notices` 등)은 아직 미구현이거나 **forward-
looking 예시**다 — §1.1과 충돌하면 §1.1을 따른다.

| asset 이름 | dataset_key | group |
|-----------|-------------|-------|
| `feature_event_visitkorea_enrichment` | `visitkorea_festival_events` | `features_event` |
| `feature_place_mois_licenses` | `mois_license_features_bulk` | `features_place` |
| `feature_place_opinet_stations` | `opinet_fuel_station_details` | `features_place` |
| `feature_place_khoa_beaches` | `khoa_beaches` | `features_place` |
| `feature_place_krheritage_items` | `krheritage_heritage_features` | `features_place` |
| `feature_area_krheritage_gis_spca` (forward-looking) | `krheritage_gis_spca` | `features_area` |
| `feature_event_krheritage_events` | `krheritage_event_list` | `features_event` |
| `feature_place_krforest_recreation_forests` | `krforest_recreation_forests` | `features_place` |
| `feature_route_krforest_trails` (forward-looking) | `krforest_trails` | `features_route` |
| `feature_place_krex_rest_areas` | `krex_rest_areas` | `features_place` |
| `price_krex_rest_area_fuel` (forward-looking) | `krex_rest_area_prices` | `features_price` |
| `feature_weather_kma_short_forecast` | `kma_short_forecast` | `features_weather` |
| `feature_weather_kma_ultra_short_nowcast` | `kma_ultra_short_nowcast` | `features_weather` |
| `feature_notice_krex_traffic_notices` | `krex_traffic_notices` | `features_notice` |
| `feature_notice_kma_weather_alerts` | `kma_weather_alerts` | `features_notice` |
| `notice_krforest_safety` (forward-looking) | `forest_safety_notices` | `features_notice` |
| `notice_khoa_coastal` (forward-looking) | `khoa_coastal_notices` | `features_notice` |
| `feature_dedup_review` | (운영) | `features_quality` |
| `feature_consistency_reports` | (운영, T-201) | `features_quality` |

## 6. ConcurrencyConfig (provider 쿼터)

```python
# packages/kor-travel-map-dagster/definitions.py
from dagster import Definitions, ConcurrencyConfig

defs = Definitions(
    assets=[...],
    resources={...},
    asset_concurrency_configs={
        "opinet_api":    ConcurrencyConfig(max_concurrent=1),
        "kma_api":       ConcurrencyConfig(max_concurrent=1),
        "datagokr_api":  ConcurrencyConfig(max_concurrent=2),
        "visitkorea_api": ConcurrencyConfig(max_concurrent=1),
        "krheritage_api": ConcurrencyConfig(max_concurrent=1),
        "kakao_local":   ConcurrencyConfig(max_concurrent=2),
        # 객체 저장소 (S3 호환)는 max_concurrent 4~8 정도 (provider 아님)
        "object_store_uploader": ConcurrencyConfig(max_concurrent=8),
    },
)
```

provider별 max_concurrent는 그 provider의 분당 쿼터 / 안전 마진으로 결정.

## 7. Resource 정의 (kor-travel-map Dagster)

```python
# packages/kor-travel-map-dagster/resources.py
from dagster import resource, ResourceDefinition
from kortravelmap import AsyncKorTravelMapClient

@resource(config_schema={...})
def kor_travel_map_client_resource(init_context):
    settings = KorTravelMapSettings()
    engine = create_async_engine(settings.pg_dsn.get_secret_value())
    file_store = create_file_store(settings)
    kor_travel_geo = AsyncAddressClient(...)
    providers = {...}
    return AsyncKorTravelMapClient(
        engine=engine, file_store=file_store,
        kor_travel_geo_client=kor_travel_geo, providers=providers,
        settings=settings,
    )

@resource
def visitkorea_resource(init_context):
    return AsyncVisitKoreaClient(service_key=...)

# ... 나머지 provider
```

본 라이브러리는 resource 정의를 노출하지 않는다 — Dagster 의존하지 않으므로.

## 7.1 OpenAPI 기반 feature update queue

Admin UI 또는 외부 서비스는 Dagster를 직접 호출하지 않고 다음 OpenAPI를 호출한다.

```http
POST /admin/feature-update-requests
```

대표 scope:

- `feature_ids`: 특정 feature 목록.
- `center_radius`: 특정 좌표 중심 반경 `n` km 안 feature.
- `sigungu_by_radius`: 특정 좌표 중심 반경 `n` km와 교차/포함되는 시군구의 feature.
- `bbox`: 지도 bbox 안 feature.
- `provider_dataset`: 특정 provider/dataset/sync_scope.

처리 흐름:

1. API가 scope를 검증하고 대상 feature/provider/dataset을 계산한다.
2. API가 `ops.feature_update_requests`와 `ops.import_jobs` row를 만든다.
3. `run_mode=queued`이면 Dagster sensor가 queued request를 peek하고 worker run을
   만든다. 실제 request/import job 상태 전이는 worker가 수행한다.
4. `run_mode=now`도 request/job row를 먼저 저장하고, 같은 sensor queue에서 감지한다.
5. Dagster run은 provider 호출, DTO 변환, 적재, dedup refresh, consistency check를
   수행하고 progress를 `ops.import_jobs`에 갱신한다.
6. API는 admin `GET /admin/feature-update-requests/{id}`와
   `GET /ops/import-jobs/{job_id}`로 진행 상태를 제공한다.

세부 OpenAPI 계약은 `docs/architecture/openapi-admin-contract.md`.

## 8. EtlJobSpec helper (선택, 본 라이브러리 제공)

kor-travel-map Dagster가 asset/job 정의할 때 참고용으로, 본 라이브러리가 `EtlJobSpec` dataclass를
제공할 수 있다:

```python
# kortravelmap.dto.etl
from dataclasses import dataclass

@dataclass(frozen=True)
class EtlJobSpec:
    """provider별 ETL 메타데이터.
    
    kor-travel-map Dagster 정의 시 참고용. 메인 라이브러리에는 Dagster import 없음."""
    provider: str
    dataset_key: str
    source_entity_type: str
    feature_kind: FeatureKind | None       # 단일 kind면
    full_scan_interval_days: int | None
    interval_minutes: int | None
    suggested_concurrency: int = 1
    suggested_group_name: str = "features_misc"
    description: str = ""
```

provider 모듈마다 `JOB_SPEC: Final[EtlJobSpec]` 노출:

```python
# kortravelmap.providers.visitkorea
JOB_SPEC = EtlJobSpec(
    provider="python-visitkorea-api",
    dataset_key="visitkorea_festival_events",
    source_entity_type="festival",
    feature_kind=FeatureKind.EVENT,
    full_scan_interval_days=1,
    interval_minutes=None,
    suggested_concurrency=1,
    suggested_group_name="features_event",
    description="VisitKorea (TourAPI) 축제/행사 일 1회 전체 스캔",
)
```

kor-travel-map Dagster는 위 spec을 참고해 asset/schedule을 정의 (메인 라이브러리의
직접 Dagster 의존성은 아님).

## 9. import_jobs 큐와 Dagster의 관계

본 라이브러리의 `ops.import_jobs` 테이블은 Dagster run storage와 **중복이 아니라
분리**:

| 큐 | 용도 |
|----|------|
| Dagster run storage (`kor_travel_map_dagster`) | Dagster run/event/asset metadata |
| `ops.import_jobs` (`kor_travel_map`) | admin/OpenAPI에서 보는 작업 진행률과 취소 상태 |
| `ops.feature_update_requests` (`kor_travel_map`) | 지리 범위/provider 범위 업데이트 요청 |

운영 시 정기 적재와 사용자 트리거 update 모두 Dagster가 실행한다. admin API는
OpenAPI 계약과 queue/progress를 관리한다. 둘 다 advisory lock으로 race를 방지한다
(ADR-011/039).

feature update request 큐는 T-208e 이후 다음 흐름을 따른다.

1. `feature_update_request_queue_sensor`가 15초 간격으로
   `AsyncKorTravelMapClient.peek_update_requests(limit=10)`를 호출한다.
2. Sensor는 DB 상태를 바꾸지 않고 한 tick에 최대
   `FEATURE_UPDATE_SENSOR_MAX_RUN_REQUESTS=10`개 request id를 Dagster `RunRequest`
   config/tag에 담아 `feature_update_request_worker` 배치를 요청한다(15초당 최대 10
   RunRequest).
3. Worker op `execute_feature_update_request`가
   `AsyncKorTravelMapClient.execute_feature_update_request()`를 호출해 request/import job
   상태 전이와 provider refresh runner 실행을 한 흐름으로 처리한다.
4. Worker run 실패는 `feature_update_request_failure_sensor`가 감지해
   `fail_update_request()`를 best-effort 호출하고, 선택 notifier resource에 알림
   payload를 전달한다.

offline upload load job은 T-208h 이후 다음 흐름을 따른다.

1. Admin API/UI가 원본 파일을 RustFS 등 객체 저장소에 보존하고
   `ops.offline_uploads` row를 만든다. D-14 기준 운영 버킷은 `kor-travel-map-uploads`이며,
   원본은 만료 없이 보존한다.
2. 운영자가 admin UI에서 load를 누르면 admin API가 Dagster GraphQL `launchRun`으로
   `offline_upload_load` job을 `upload_id` config와 함께 실행한다. Dagster UI에서
   같은 job을 수동 실행할 수도 있다.
3. Op `load_offline_upload`는 `offline_upload_store` resource로 `storage_key` bytes를
   읽고, `byte_size`와 `checksum_sha256`을 검증한다.
4. 현재 첫 구현은 JSON/JSONL `FeatureBundle` dump만 지원한다. parser는 kind별 detail
   DTO hydrate 후 `FeatureBundle` validation을 수행한다.
5. `AsyncKorTravelMapClient.run_offline_upload_load_job()`이 provider/dataset/scope advisory
   lock을 잡고 `ops.import_jobs` + `ops.offline_uploads` 상태 전이와 PostGIS 적재를 한
   transaction으로 처리한다.
6. 기본 `offline_upload_store` resource는 `KOR_TRAVEL_MAP_OBJECT_STORE_*`와
   `KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET`에서 RustFS/S3 호환 client를 만든다.
7. Multipart `/admin/offline-uploads*` 기본 API/UI는 T-208h에서 구현됐다.
   CSV/TSV column mapping과 validation wizard는 후속 T-208i다.

## 10. 정기 schedule 구현 (kor-travel-map Dagster)

`packages/kor-travel-map-dagster/src/kortravelmap/dagster/schedules.py`가
현재 schedule이 필요한 Feature 적재 asset의 provider별 schedule을 등록한다. 모든 schedule은
`execution_timezone="Asia/Seoul"`이고, 같은 시각에 외부 API 호출이 몰리지 않도록
분/요일을 분산한다. 기본 status는 로컬 개발 중 실 provider 호출을 막기 위해
`STOPPED`이며, 운영 배포에서 필요한 schedule만 enable한다.

| schedule | asset job | cron | 비고 |
|----------|-----------|------|------|
| `feature_event_datagokr_cultural_festivals_daily_schedule` | `feature_event_datagokr_cultural_festivals_job` | `10 3 * * *` | 전국문화축제 일 1회 |
| `feature_place_opinet_stations_monthly_schedule` | `feature_place_opinet_stations_job` | `5 3 1 * *` | OpiNet 주유소 월 1회 |
| `feature_price_opinet_stations_twice_daily_schedule` | `feature_price_opinet_stations_job` | `18 6,18 * * *` | OpiNet 주유소 유가 일 2회 |
| `feature_place_krex_rest_areas_monthly_schedule` | `feature_place_krex_rest_areas_job` | `20 2 1 * *` | KREX 휴게소 월 1회 |
| `feature_price_krex_rest_areas_twice_daily_schedule` | `feature_price_krex_rest_areas_job` | `28 6,18 * * *` | KREX 휴게소 유가 일 2회 |
| `feature_notice_krex_traffic_notices_quarter_hour_schedule` | `feature_notice_krex_traffic_notices_job` | `7,22,37,52 * * * *` | KREX 교통공지 15분 |
| `feature_weather_krex_rest_areas_hourly_schedule` | `feature_weather_krex_rest_areas_job` | `35 * * * *` | KREX 휴게소 관측 기상 시간당 |
| `feature_place_krheritage_items_weekly_schedule` | `feature_place_krheritage_items_job` | `15 2 * * 1` | 국가유산 item 주 1회 |
| `feature_event_krheritage_events_daily_schedule` | `feature_event_krheritage_events_job` | `25 3 * * *` | 국가유산 행사 일 1회 |
| `feature_place_mois_licenses_weekly_schedule` | `feature_place_mois_licenses_job` | `35 4 * * 1` | MOIS bulk 주 1회 |
| `feature_place_knps_points_semiannual_schedule` | `feature_place_knps_points_job` | `45 3 1 1,7 *` | KNPS point 반기 1회 |
| `feature_geometry_knps_records_semiannual_schedule` | `feature_geometry_knps_records_job` | `15 4 1 1,7 *` | KNPS geometry 반기 1회 |
| `feature_place_kor_travel_concierge_youtube_daily_schedule` | `feature_place_kor_travel_concierge_youtube_job` | `40 3 * * *` | kor-travel-concierge YouTube 후보 일 1회 |
| `feature_weather_kma_ultra_short_nowcast_hourly_schedule` | `feature_weather_kma_ultra_short_nowcast_job` | `45 * * * *` | KMA 초단기실황 시간당 |
| `feature_weather_kma_ultra_short_forecast_hourly_schedule` | `feature_weather_kma_ultra_short_forecast_job` | `50 * * * *` | KMA 초단기예보 시간당 |
| `feature_weather_kma_short_forecast_hourly_schedule` | `feature_weather_kma_short_forecast_job` | `20 * * * *` | KMA 단기예보 시간당 |
| `feature_weather_kma_mid_forecast_hourly_schedule` | `feature_weather_kma_mid_forecast_job` | `25 * * * *` | KMA 중기예보 시간당 |
| `feature_notice_kma_weather_alerts_hourly_schedule` | `feature_notice_kma_weather_alerts_job` | `15 * * * *` | KMA 기상특보 시간당 |
| `feature_place_mcst_culture_weekly_schedule` | `feature_place_mcst_culture_job` | `30 4 * * 2` | MCST 문화 파일데이터 13종 주 1회 |
| `mois_localdata_source_sync_weekly_schedule` | `mois_localdata_source_sync` | `0 4 * * 1` | MOIS LOCALDATA source DB sync 주 1회 |
| `curated_features_refresh_daily_schedule` | `curated_features_refresh` | `55 4 * * *` | curated overlay metadata/rule/sweep/cache refresh 일 1회 |
| `consistency_dedup_refresh_daily_schedule` | `consistency_dedup_refresh` | `45 5 * * *` | DB 기준 dedup 후보 refresh + F1~F7 consistency report |

운영 임계값은 SPEC V8 v8_0 + 실제 부하 기반으로 kor-travel-map 운영자가 조정한다.
T-208f 기준 maintenance schedule도 기본 `STOPPED`다. 로컬 개발에서 자동으로 큐와
리포트를 갱신하지 않고, 운영자가 Dagster UI/API에서 scope config와 함께 수동 실행하거나
배포 환경에서 schedule을 enable한다.

purge job/schedule은 현재 구현되어 있지 않다. RustFS/offline-upload 원본은 ADR-045
D-14 기준 만료 없이 보존하므로, TTL·삭제 정책과 실제 job이 함께 구현되기 전까지
Dagster schedule 표에 purge 항목을 추가하지 않는다.

## 11. Asset materialization metadata

`FeatureLoadResult.as_metadata()`가 Dagster metadata로 변환:

```python
{
  "features_upserted": MetadataValue.int(150),
  "source_records_upserted": MetadataValue.int(152),
  "source_links_upserted": MetadataValue.int(150),
  "files_uploaded": MetadataValue.int(45),
  "weather_values_upserted": MetadataValue.int(0),
  "price_values_upserted": MetadataValue.int(0),
  "duration_ms": MetadataValue.int(2340),
  "first_feature_id": MetadataValue.text("f_..."),
  "last_feature_id": MetadataValue.text("f_..."),
}
```

본 라이브러리는 dict로 반환한다. kor-travel-map Dagster 패키지가 `MetadataValue.*`로
변환한다. 메인 라이브러리는 Dagster를 import하지 않는다.

## 12. 정합성 게이트 패턴 (T-200, kor-travel-geo ADR-017 미러)

T-205d 이후 `ops.import_jobs`는 `load_batch_id`와 self-FK `parent_job_id`를
갖는다. T-200은 이 컬럼을 사용해 batch root와 기존 실제 source load import job을
연결하고, consistency gate를 통과한 경우에만 `mv_refresh` 단계를 기록한다.

```
[root job: load_batch_id=UUID, parent_job_id=NULL]
  ├── child: offline_upload_load 또는 feature_update_request import job
  ├── child: ... (기존 runner가 실제 실행을 끝낸 import job id)
  └── 모두 완료 후:
      [gate: consistency_check (parent_job_id=root)]
        ↓ severity_max != ERROR
      [mv_refresh (strategy='swap')]
```

- root job은 `ops.import_jobs`에 `load_batch_id=UUID`, `parent_job_id=NULL`로 등록한다.
- Dagster job 이름은 `full_load_batch_consistency_gate`, op 이름은
  `run_full_load_batch_consistency_gate`다.
- `child_job_ids`로 받은 실제 import job은 같은 `load_batch_id`와 root
  `parent_job_id`를 저장한다.
- child job이 모두 `done`이면 `consistency_check` import job을 만들고
  `run_consistency_checks(batch_id=load_batch_id)`를 실행한다.
- `severity_max=ERROR`이면 `mv_refresh`를 만들지 않고 root/gate job을 `failed`로 닫는다.
- `severity_max=OK/WARN`이면 `mv_refresh` job을 만든다. 현재 schema에는 운영 MV가
  없으므로 `materialized_views=[]` 기본 실행은 `skipped:no_materialized_views` payload를
  남긴다. `materialized_views=["schema.view"]`를 주면 `swap`은 현재
  `REFRESH MATERIALIZED VIEW CONCURRENTLY`로 매핑된다.
- `swap`/`concurrently` 전략으로 넘기는 MV는 refresh identity `UNIQUE` 인덱스와 최초
  비-concurrent populate가 끝난 상태여야 한다. T-101로 실제 MV를 도입할 때 migration
  체크리스트에 `CREATE UNIQUE INDEX`와 최초 `REFRESH MATERIALIZED VIEW schema.view`를
  포함한다.
- `plan_only=true`는 DB write 없이 child job 존재 여부만 확인한다.

**도입 시점은 ADR-033** (accepted, T-014에 묶어 전환) — 두 단계로 분할:

- **Phase 1 (Sprint 3~4, T-201a)** — ✅ **구현 완료 (2026-05-29)**: 스키마
  (`alembic 0003`, `ops.feature_consistency_reports`) + F1~F3 critical 케이스
  (orphan source / detail 누락 / CRS drift) — `infra/consistency.py`
  `run_consistency_checks`. Dagster 게이트 **미적용** — 검증만(관측).
- **Phase 1.5 (ADR-045 T-208f)** — ✅ **구현 완료 (2026-06-03)**:
  `consistency_dedup_refresh` Dagster maintenance job. DB에 적재된 feature를
  provider/dataset scope로 다시 읽어 pair/sibling dedup 후보 큐를 갱신한 뒤 현재
  `run_consistency_checks()`가 평가하는 F1~F7 report를 저장한다. 도입 당시 범위는
  F1~F4였고, 여전히 **관측/refresh** 단계이며 `severity_max=ERROR`여도 materialized
  view swap 차단은 하지 않는다.
- **Phase 1.75 (ADR-045 T-200)** — ✅ **구현 완료 (2026-06-04)**:
  root/child import job batch 연결, `consistency_check` gate, ERROR 시 `mv_refresh`
  차단, `mv_refresh` 추적 job을 구현했다. F5~F8 violation gate와 실제 MV 카탈로그는
  아직 별도다.
- **Phase 2 (Sprint 5 운영 진입 직전, T-201b)**: F5~F8 + 실제 운영 MV 카탈로그/refresh
  정책, dry-run report 첨부, admin UI 승인/거절/재시도 UX를 붙인다. dry-run report
  산출 경로는 `ktmctl consistency-report`이며, 기본은 `persist=false`라 DB에
  report row를 쓰지 않는다.

운영 enable 전 report 산출 예:

```bash
kor-travel-map --dsn "$KOR_TRAVEL_MAP_PG_DSN" consistency-report \
  --known-file-objects /path/to/rustfs-objects.jsonl \
  --output docs/reports/t-201b-phase2-dry-run-report-YYYY-MM-DD.md
```

`--persist`를 붙이면 같은 결과를 `ops.feature_consistency_reports`에도 저장한다.
`--fail-on-error`는 CI/운영 preflight에서 `severity_max=ERROR`일 때 exit 1로 실패시킨다.

구현 위치:

- 메인 라이브러리: `src/kortravelmap/infra/batch_dag.py`
- client wrapper: `AsyncKorTravelMapClient.run_batch_dag_consistency_gate(...)`
- Dagster: `packages/kor-travel-map-dagster/src/kortravelmap/dagster/batch_dag.py`

## 13. 운영 알림 (kor-travel-map)

메인 라이브러리는 알림 sink를 결정하지 않는다. kor-travel-map 운영 프로그램이:
- Dagster `RunStatusSensor`로 run failure → Sentry/Slack
- `data_integrity_violations.severity='critical'` 신규 row → 알림
- `import_jobs.status='failed'` 신규 row → 알림
- provider `last_error` 빈도 threshold 초과 → 알림

본 라이브러리는 위 테이블/로그만 충실히 기록.

## 14. 로컬/운영 Dagster 기동

```bash
# 운영/Docker compose 기준
docker compose up dagster dagster-daemon

# 로컬 venv에서 webserver/daemon을 직접 나누어 띄울 때
export DAGSTER_HOME=.dagster
export KOR_TRAVEL_MAP_DAGSTER_PG_URL=postgresql://kor_travel_map:kor_travel_map@127.0.0.1:5432/kor_travel_map_dagster
dagster-webserver -m kortravelmap.dagster.definitions -h 0.0.0.0 -p 12702
dagster-daemon run -m kortravelmap.dagster.definitions
```

메인 라이브러리 단독으로는 Dagster를 띄우지 않는다 (의존성 X). Dagster 실행 코드는
kor-travel-map 독립 프로그램 패키지에 둔다. 디버그 / 적재 검증은 admin API
(`kortravelmap.api`) 또는 직접 Python 스크립트로도 가능하다.

Docker compose는 `dagster-db-init`로 같은 Postgres container 안에
`kor_travel_map_dagster` DB를 보장하고, `docker/dagster.yaml`의 `storage.postgres` 설정으로
run/event/schedule metadata를 영속화한다. `dagster dev`는 로컬 단일 프로세스 편의
명령으로만 사용할 수 있고 운영 compose에서는 사용하지 않는다.

로컬 `npm run admin:stack`도 같은 기준을 따른다. 시작 전 `kor_travel_map_dagster` DB
존재를 확인/생성하고, `docker/dagster.yaml`을 `$DAGSTER_HOME/dagster.yaml`로 설치한 뒤
`dagster-webserver`와 `dagster-daemon`을 별도 프로세스로 띄운다. `$DAGSTER_HOME`에
`schedules/schedules.db*`가 생기면 Postgres instance config를 읽지 못한 회귀로 본다.

feature update worker 실행에는 `kor_travel_map_client`와 `feature_update_runner` resource가
필수다. 실패 알림은 선택 resource `feature_update_failure_notifier`로 연결한다.

## 15. 본 라이브러리가 노출하는 helper 요약

`AsyncKorTravelMapClient`:
- `.providers.<name>.<entity>_to_bundles(items, fetched_at=...) -> Iterable[FeatureBundle]`
- `.upload_feature_files(sources) -> list[FeatureFile]`
- `.load_feature_bundles(bundles, *, prune_existing=False) -> FeatureLoadResult`
- `.record_sync_success(provider, dataset_key, sync_scope='default', cursor, ...) -> SyncState` (cursor 전진; `upsert_sync_state`는 후속 PR 미구현)
- `.get_sync_state(provider, dataset_key, sync_scope='default') -> SyncState | None`
- `.enqueue_import_job(kind, payload, load_batch_id=None, parent_job_id=None) -> ImportJob`
- `.claim_next_import_job() -> ImportJob | None`
- `.update_import_job(job_id, *, state, progress, current_stage, error_message) -> None`
- `.run_batch_dag_consistency_gate(child_job_ids, ..., plan_only=False) -> BatchDagRunResult`
- `.healthz() -> HealthCheck`

dataclasses:
- `FeatureBundle`, `FeatureLoadResult` (with `.as_metadata()`)
- `SyncState` (infra dataclass, dto 아님), `ImportJob`
- `EtlJobSpec` (옵션, asset 정의 참고용)

## 16. 비책임 (다시 확인)

본 라이브러리는:
- `dagster` package를 import하지 않는다
- `@asset` / `@op` / `@job` / `@schedule` 데코레이터 사용 안 함
- Dagster repository / Definitions 정의 안 함
- ScheduleDefinition, SensorDefinition 정의 안 함
- Dagster `Config`, `RunConfig` 정의 안 함

위는 모두 kor-travel-map Dagster 패키지 책임이다.

본 라이브러리는 **순수 함수와 DTO + DB 적재 helper**만 제공 → Dagster 없이도
import해서 사용 가능 → 단위 테스트가 Dagster 의존 없이 빠르게 동작.
