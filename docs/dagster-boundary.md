# dagster-boundary.md — krtour-map 독립 Dagster 책임 경계

본 문서는 ADR-045 이후 krtour-map 독립 프로그램의 Dagster 책임 경계다.

핵심 변경:

- Dagster는 krtour-map 독립 프로그램 책임이다.
- krtour-map Docker 프로그램이 자체 Dagster webserver/daemon/metadata DB를 가진다.
- 외부 서비스는 krtour-map Dagster를 직접 제어하지 않고 krtour-map OpenAPI를
  호출한다. 각 외부 서비스가 자체 Dagster를 운영하더라도 krtour-map Dagster와
  별개다.
- FastAPI admin API는 feature update request를 만들고, Dagster가 이를 실행한다.
- 메인 라이브러리 `krtour.map` 자체는 여전히 Dagster를 import하지 않는다.
  Dagster 코드는 별도 패키지 `packages/krtour-map-dagster/`에 둔다.

## 1. 책임 매트릭스

| 책임 | 위치 |
|------|------|
| Dagster install / daemon / scheduler | krtour-map 독립 프로그램 |
| `@asset`, `@op`, `@job`, `@schedule`, `Definitions` | krtour-map Dagster 패키지 |
| Asset/job 이름, dataset_key 매핑, group 구조 | krtour-map Dagster |
| Cron schedule (시각, frequency) | krtour-map Dagster |
| Asset/job dependency graph | krtour-map Dagster |
| `ConcurrencyConfig` 또는 pool 설정(provider 쿼터 보호) | krtour-map Dagster |
| Retry policy (`tenacity`/Dagster retry) | krtour-map Dagster |
| Run failure 알림 (Telegram, Slack, Sentry) | krtour-map 운영 설정 |
| Dagster metadata DB | `krtour_map_dagster` |
| Feature update request queue | krtour-map API + `ops.feature_update_requests` |
| Import job progress | krtour-map API + `ops.import_jobs` |
| Dagster resource 정의 (engine, file_store, provider clients) | krtour-map Dagster |
| **provider 호출 자체** | provider 라이브러리 직접 (ADR-006) |
| **raw → DTO 변환 (순수 함수)** | **본 라이브러리 (`providers/<name>.py`)** |
| **DB 적재 (raw SQL upsert/COPY)** | **본 라이브러리 (`infra/*_repo.py`)** |
| **객체 저장소 업로드** | **본 라이브러리 (`infra/file_store.py`)** |
| **sync state 갱신** | **본 라이브러리 (`infra/sync_repo.py`)** |
| **import_jobs 큐 관리** | **본 라이브러리 (`infra/jobs_repo.py`)** |
| Dedup scoring / Record Linkage | 본 라이브러리 (`core/scoring.py`) |
| 정합성 검증 룰 (F1~F8) | 본 라이브러리 (`core/integrity.py`, T-201) |
| 외부 사용자/여행계획/POI 도메인 | 외부 서비스 |
| 외부 서비스에서 feature update 요청 | krtour-map OpenAPI 호출 |

요약:
- **본 라이브러리**: 변환 + 저장 + 검증 (Dagster 없이도 호출 가능한 함수)
- **krtour-map API**: OpenAPI, admin UI, queue 생성, 진행 상태 조회/취소
- **krtour-map Dagster**: provider sync, feature update, offline upload load,
  consistency/dedup jobs 실행
- **외부 서비스**: OpenAPI client 소비자

## 1.1 현재 구현된 Feature 적재 asset

`packages/krtour-map-dagster`는 1차로 이미 구현·검증된 provider 변환 함수만
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

공통 resource:

- `krtour_map_client`: `AsyncKrtourMapClient`.
- `reverse_geocoder`: kraddr-geo REST v2 기반 `ReverseGeocoder`.
- `fetched_at`: batch 기준 aware `datetime`(없으면 KST 현재 시각).
- `strict_address`: 기본 `True`. 주소/좌표 검증 error가 있으면 적재 전 중단.

## 2. 표준 Job/Asset 패턴

```python
# packages/krtour-map-dagster/assets/visitkorea_festivals.py (후보 위치)
from dagster import asset, FreshnessPolicy, RetryPolicy, AssetExecutionContext
from krtour.map import AsyncKrtourMapClient
from krtour.map.dto import ProviderSyncState

@asset(
    group_name="features_event",
    freshness_policy=FreshnessPolicy(maximum_lag_minutes=24 * 60),  # 일 1회
    retry_policy=RetryPolicy(max_retries=5, delay=60, backoff="exponential"),
    deps=[],  # 다른 asset 의존 없으면
)
async def feature_event_visitkorea_festivals(
    ctx: AssetExecutionContext,
    visitkorea,                # Dagster resource: provider client
    krtour_map_client: AsyncKrtourMapClient,  # Dagster resource
) -> "FeatureLoadResult":
    """raw → bundles → upload files → load → sync state."""
    
    # 1. provider 호출 (provider 라이브러리 직접)
    items = list(await visitkorea.search_festival(...))
    ctx.log.info("fetched", extra={"count": len(items)})

    # 2. 변환 (본 라이브러리 순수 함수)
    bundles = list(
        krtour_map_client.providers.visitkorea.festival_to_bundles(
            items, fetched_at=ctx.run.created_timestamp,
        )
    )

    # 3. 적재
    result = await krtour_map_client.load_feature_bundles(bundles)
    ctx.add_output_metadata(result.as_metadata())

    # 5. sync state
    await krtour_map_client.upsert_sync_state(ProviderSyncState(
        provider="python-visitkorea-api",
        dataset_key="visitkorea_festival_events",
        last_success_at=kst_now(),
        cursor={"last_pageNo": items[-1].pageNo if items else None},
    ))
    return result
```

5단계는 표준. provider별 차이는 1, 2, 3에 한정 (4, 5는 동일).

## 3. Dagster 없이도 호출 가능 (테스트/디버그)

본 라이브러리의 모든 helper는 Dagster context 없이 호출 가능:

```python
# 통합 테스트 또는 디버그 스크립트
async def main():
    settings = KrtourMapSettings()
    engine = create_async_engine(settings.pg_dsn.get_secret_value())
    client = AsyncKrtourMapClient(engine=engine, ...)
    
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

`krtour.map.providers.<name>` 모듈마다 `DATASET_KEY: Final[str]` 상수 노출.
krtour-map Dagster asset/job이 이 상수를 import해서 dataset_key를 일관 사용:

```python
# packages/krtour-map-dagster/assets/visitkorea_festivals.py
from krtour.map.providers.visitkorea import DATASET_KEY as VISITKOREA_FESTIVAL_DATASET_KEY

# asset 이름 / Dagster metadata에 사용
ctx.log.info("loaded", extra={"dataset_key": VISITKOREA_FESTIVAL_DATASET_KEY})
```

전체 dataset_key 카탈로그는 `docs/provider-contract.md` §3.

## 5. asset/job 명명 규약

krtour-map Dagster의 asset/job 이름 표준:

| asset 이름 | dataset_key | group |
|-----------|-------------|-------|
| `feature_event_visitkorea_festivals` | `visitkorea_festival_events` | `features_event` |
| `feature_place_mois_licenses` | `mois_license_features_bulk` | `features_place` |
| `feature_place_opinet_stations` | `opinet_fuel_station_details` | `features_place` |
| `feature_place_khoa_beaches` | `khoa_oceans_beach_info` | `features_place` |
| `feature_place_krheritage_heritage` | `krheritage_heritage_features` | `features_place` |
| `feature_area_krheritage_gis_spca` | `krheritage_gis_spca` | `features_area` |
| `feature_event_krheritage_events` | `krheritage_event_list` | `features_event` |
| `feature_place_krforest_recreation` | `krforest_recreation_forests` | `features_place` |
| `feature_route_krforest_trails` | `krforest_trails` | `features_route` |
| `feature_place_krex_rest_areas` | `krex_rest_areas` | `features_place` |
| `price_krex_rest_area_fuel` | `krex_rest_area_prices` | `features_price` |
| `weather_kma_short_forecast` | `kma_short_forecast` | `features_weather` |
| `weather_kma_ultra_short_nowcast` | `kma_ultra_short_nowcast` | `features_weather` |
| `notice_krex_traffic` | `krex_traffic_notices` | `features_notice` |
| `notice_kma_weather_alerts` | `kma_weather_alerts` | `features_notice` |
| `notice_krforest_safety` | `forest_safety_notices` | `features_notice` |
| `notice_khoa_coastal` | `khoa_coastal_notices` | `features_notice` |
| `feature_dedup_review` | (운영) | `features_quality` |
| `feature_consistency_reports` | (운영, T-201) | `features_quality` |
| `feature_purge_weather_old` | (운영) | `features_purge` |
| `feature_purge_notice_old` | (운영) | `features_purge` |

## 6. ConcurrencyConfig (provider 쿼터)

```python
# packages/krtour-map-dagster/definitions.py
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

## 7. Resource 정의 (krtour-map Dagster)

```python
# packages/krtour-map-dagster/resources.py
from dagster import resource, ResourceDefinition
from krtour.map import AsyncKrtourMapClient

@resource(config_schema={...})
def krtour_map_client_resource(init_context):
    settings = KrtourMapSettings()
    engine = create_async_engine(settings.pg_dsn.get_secret_value())
    file_store = create_file_store(settings)
    kraddr_geo = AsyncAddressClient(...)
    providers = {...}
    return AsyncKrtourMapClient(
        engine=engine, file_store=file_store,
        kraddr_geo_client=kraddr_geo, providers=providers,
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
3. `run_mode=queued`이면 Dagster sensor가 queued request를 claim한다.
4. `run_mode=now`이면 API가 즉시 Dagster run을 만들 수 있으나 request/job row는
   먼저 저장한다.
5. Dagster run은 provider 호출, DTO 변환, 적재, dedup refresh, consistency check를
   수행하고 progress를 `ops.import_jobs`에 갱신한다.
6. API는 `GET /admin/feature-update-requests/{id}`와
   `GET /admin/import-jobs/{job_id}`로 진행 상태를 제공한다.

세부 OpenAPI 계약은 `docs/openapi-admin-contract.md`.

## 8. EtlJobSpec helper (선택, 본 라이브러리 제공)

krtour-map Dagster가 asset/job 정의할 때 참고용으로, 본 라이브러리가 `EtlJobSpec` dataclass를
제공할 수 있다:

```python
# krtour.map.dto.etl
from dataclasses import dataclass

@dataclass(frozen=True)
class EtlJobSpec:
    """provider별 ETL 메타데이터.
    
    krtour-map Dagster 정의 시 참고용. 메인 라이브러리에는 Dagster import 없음."""
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
# krtour.map.providers.visitkorea
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

krtour-map Dagster는 위 spec을 참고해 asset/schedule을 정의 (메인 라이브러리의
직접 Dagster 의존성은 아님).

## 9. import_jobs 큐와 Dagster의 관계

본 라이브러리의 `ops.import_jobs` 테이블은 Dagster run storage와 **중복이 아니라
분리**:

| 큐 | 용도 |
|----|------|
| Dagster run storage (`krtour_map_dagster`) | Dagster run/event/asset metadata |
| `ops.import_jobs` (`krtour_map`) | admin/OpenAPI에서 보는 작업 진행률과 취소 상태 |
| `ops.feature_update_requests` (`krtour_map`) | 지리 범위/provider 범위 업데이트 요청 |

운영 시 정기 적재와 사용자 트리거 update 모두 Dagster가 실행한다. admin API는
OpenAPI 계약과 queue/progress를 관리한다. 둘 다 advisory lock으로 race를 방지한다
(ADR-011/039).

## 10. 정기 schedule 가이드 (krtour-map Dagster)

| asset group | suggested cron | 비고 |
|-------------|---------------|------|
| KMA short forecast | `*/30 * * * *` | 30분 간격 |
| KMA ultra short nowcast | `*/10 * * * *` | 10분 간격 |
| KMA mid forecast | `0 6,18 * * *` | 일 2회 |
| KMA weather alerts | `*/10 * * * *` | 10분 |
| KREX traffic notices | `*/5 * * * *` | 5분 |
| KREX rest area weather | `0 * * * *` | 시간 |
| KREX rest area prices | `0 6,14,22 * * *` | 일 3회 |
| KREX rest area places | `0 2 1 * *` | 월 1회 |
| AirKorea | `0 * * * *` | 시간 |
| KHOA beach info | `0 2 10 * *` | 월 1회 (해수욕장 신규/변경 드물다) |
| KHOA coastal notices | `0 * * * *` | 시간 |
| KHOA marine index | `0 * * * *` | 시간 |
| VisitKorea festivals | `0 3 * * *` | 일 1회 |
| MOIS license bulk (full) | `0 2 5 * *` | 월 1회 (주간 운영 시 0 2 * * 1) |
| MOIS license incremental | `0 3 * * *` | 일 1회 (이력조회 기반) |
| OpiNet stations | `0 3 1 * *` | 월 1회 |
| OpiNet prices | `0 6,14,22 * * *` | 일 3회 |
| KRforest recreation forests | `0 2 1 * *` | 월 1회 |
| KRforest trails | `0 2 1 * *` | 월 1회 |
| KRforest mountain weather | `0 * * * *` | 시간 |
| KRforest safety notices | `*/30 * * * *` | 30분 |
| KRheritage heritage | `0 2 * * 1` | 주 1회 |
| KRheritage event | `0 3 * * *` | 일 1회 |
| KRheritage GIS spca | `0 2 1 * *` | 월 1회 |
| data.go.kr standard 5종 | `0 2 1 * *` | 월 1회 |
| dedup review enqueue | `0 4 * * *` | 일 1회 |
| consistency reports (T-201) | `0 5 * * *` | 일 1회 |
| purge weather old (>30d) | `0 6 * * *` | 일 1회 |
| purge notice old (>1y) | `0 6 * * 0` | 주 1회 |

운영 임계값은 SPEC V8 v8_0 + 실제 부하 기반으로 krtour-map 운영자가 조정한다.

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

본 라이브러리는 dict로 반환한다. krtour-map Dagster 패키지가 `MetadataValue.*`로
변환한다. 메인 라이브러리는 Dagster를 import하지 않는다.

## 12. 정합성 게이트 패턴 (T-200, kraddr-geo ADR-017 미러)

운영 진입 후 검토할 batch DAG 패턴:

```
[root job: load_batch_id=UUID, parent_job_id=NULL]
  ├── child: feature_event_visitkorea_festivals (parent_job_id=root)
  ├── child: feature_place_mois_licenses (parent_job_id=root)
  ├── child: ... (병렬)
  └── 모두 완료 후:
      [gate: consistency_check (parent_job_id=root)]
        ↓ severity_max != ERROR
      [mv_refresh (strategy='swap')]
```

- root job은 `ops.import_jobs`에 등록
- child job 모두 완료 → consistency_check 실행
- severity != ERROR이면 `mv_refresh`로 swap
- ERROR이면 `feature_consistency_reports`에 기록 + 알림

**도입 시점은 ADR-033** (accepted, T-014에 묶어 전환) — 두 단계로 분할:

- **Phase 1 (Sprint 3~4, T-201a)** — ✅ **구현 완료 (2026-05-29)**: 스키마
  (`alembic 0003`, `ops.feature_consistency_reports`) + F1~F3 critical 케이스
  (orphan source / detail 누락 / CRS drift) — `infra/consistency.py`
  `run_consistency_checks`. Dagster 게이트 **미적용** — 검증만(관측).
- **Phase 2 (Sprint 5 운영 진입 직전, T-201b)**: F4~F8 + Dagster 게이트 +
  swap 차단. dry-run report 첨부 후 점진 enable. 위 흐름(child 완료 →
  `consistency_check` → `severity_max != ERROR`이면 swap)을 Phase 2에서 wiring.

자세한 구현은 T-200/T-201에서.

## 13. 운영 알림 (krtour-map)

메인 라이브러리는 알림 sink를 결정하지 않는다. krtour-map 운영 프로그램이:
- Dagster `RunStatusSensor`로 run failure → Sentry/Telegram/Slack
- `data_integrity_violations.severity='critical'` 신규 row → 알림
- `import_jobs.state='failed'` 신규 row → 알림
- provider `last_error` 빈도 threshold 초과 → 알림

본 라이브러리는 위 테이블/로그만 충실히 기록.

## 14. 로컬 디버그 (Dagster dev)

```bash
# krtour-map Dagster 패키지에서
dagster dev -m krtour.map_dagster.definitions

# 또는 docker compose
docker compose up krtour-map-dagster-webserver krtour-map-dagster-daemon
```

메인 라이브러리 단독으로는 Dagster를 띄우지 않는다 (의존성 X). Dagster 실행 코드는
krtour-map 독립 프로그램 패키지에 둔다. 디버그 / 적재 검증은 admin API
(`krtour.map_admin`) 또는 직접 Python 스크립트로도 가능하다.

## 15. 본 라이브러리가 노출하는 helper 요약

`AsyncKrtourMapClient`:
- `.providers.<name>.<entity>_to_bundles(items, fetched_at=...) -> Iterable[FeatureBundle]`
- `.upload_feature_files(sources) -> list[FeatureFile]`
- `.load_feature_bundles(bundles, *, prune_existing=False) -> FeatureLoadResult`
- `.upsert_sync_state(state) -> ProviderSyncState`
- `.get_sync_state(provider, dataset_key, sync_scope='global') -> ProviderSyncState | None`
- `.enqueue_import_job(kind, payload) -> ImportJob`
- `.claim_next_import_job() -> ImportJob | None`
- `.update_import_job(job_id, *, state, progress, current_stage, error_message) -> None`
- `.healthz() -> HealthCheck`

dataclasses:
- `FeatureBundle`, `FeatureLoadResult` (with `.as_metadata()`)
- `ProviderSyncState`, `ImportJob`, `ImportJobState`
- `EtlJobSpec` (옵션, asset 정의 참고용)

## 16. 비책임 (다시 확인)

본 라이브러리는:
- `dagster` package를 import하지 않는다
- `@asset` / `@op` / `@job` / `@schedule` 데코레이터 사용 안 함
- Dagster repository / Definitions 정의 안 함
- ScheduleDefinition, SensorDefinition 정의 안 함
- Dagster `Config`, `RunConfig` 정의 안 함

위는 모두 krtour-map Dagster 패키지 책임이다.

본 라이브러리는 **순수 함수와 DTO + DB 적재 helper**만 제공 → Dagster 없이도
import해서 사용 가능 → 단위 테스트가 Dagster 의존 없이 빠르게 동작.
