"""kor-travel-map 소유 provider Feature 적재 Dagster asset."""

import inspect
from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Final, TypedDict, cast

from kortravelmap.client import FestivalEnrichmentReviewRefreshResult
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.geocoding import GeoCallStats, ReverseGeocoder
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    NoticeFeatureLoadResult,
    NoticeReconcileResult,
)
from kortravelmap.infra.integrity_violation_repo import (
    IntegrityObservationReceipt as DurableIntegrityObservationReceipt,
)
from kortravelmap.providers.datagokr_file_data import (
    DATAGOKR_FILEDATA_PROVIDER_NAME,
    file_data_rows_to_bundles,
)
from kortravelmap.providers.khoa import (
    DATASET_KEY_BEACHES,
    KHOA_PROVIDER_NAME,
    beaches_to_bundles,
)
from kortravelmap.providers.knps import (
    KNPS_GEOMETRY_DATASETS,
    KNPS_PLACE_DATASETS,
    knps_geometry_records_to_bundles,
    knps_point_records_to_bundles,
)
from kortravelmap.providers.knps import (
    PROVIDER_NAME as KNPS_PROVIDER_NAME,
)
from kortravelmap.providers.kor_travel_concierge import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
    KOR_TRAVEL_CONCIERGE_SOURCE_ENTITY_TYPE,
    KorTravelConciergeQuarantine,
    kor_travel_concierge_inactive_entity_ids,
    kor_travel_concierge_items_to_bundles,
    kor_travel_concierge_latest_items,
    kor_travel_concierge_upsert_count,
)
from kortravelmap.providers.kor_travel_transport import (
    DATASET_KEY_AIRPORTS,
    DATASET_KEY_FUEL_STATIONS,
    DATASET_KEY_REST_AREAS,
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
)
from kortravelmap.providers.krairport import airports_to_bundles
from kortravelmap.providers.krex import (
    rest_areas_to_bundles,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_ARBORETUMS as KRFOREST_ARBORETUMS_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_DULLE_TRAILS as KRFOREST_DULLE_TRAILS_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_MOUNTAIN_TRAILS as KRFOREST_MOUNTAIN_TRAILS_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_RECREATION_FORESTS as KRFOREST_RECREATION_FORESTS_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    KRFOREST_PROVIDER_NAME,
    arboretums_to_bundles,
    dulle_trails_to_bundles,
    mountain_trails_to_bundles,
    recreation_forests_to_bundles,
)
from kortravelmap.providers.krforest_safety import (
    LANDSLIDE_FORECAST_DATASET_KEY as KRFOREST_LANDSLIDE_FORECAST_DATASET_KEY,
)
from kortravelmap.providers.krforest_safety import (
    LANDSLIDE_FORECAST_SOURCE_ENTITY_TYPE,
    landslide_forecast_issues_to_bundles,
)
from kortravelmap.providers.krheritage import (
    DATASET_KEY_EVENT as KRHERITAGE_EVENT_DATASET_KEY,
)
from kortravelmap.providers.krheritage import (
    DATASET_KEY_HERITAGE as KRHERITAGE_DATASET_KEY,
)
from kortravelmap.providers.krheritage import (
    PROVIDER_NAME as KRHERITAGE_PROVIDER_NAME,
)
from kortravelmap.providers.krheritage import (
    heritage_events_to_bundles,
    heritage_items_to_bundles,
)
from kortravelmap.providers.mois import (
    DATASET_KEY_BULK as MOIS_BULK_DATASET_KEY,
)
from kortravelmap.providers.mois import (
    PROVIDER_NAME as MOIS_PROVIDER_NAME,
)
from kortravelmap.providers.opinet import (
    stations_to_bundles,
)
from kortravelmap.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    DATASET_KEY_MUSEUMS,
    DATASET_KEY_PARKING_LOTS,
    DATASET_KEY_SPECIAL_STREETS,
    DATASET_KEY_TOURIST_ATTRACTIONS,
    STANDARD_DATA_PROVIDER_NAME,
    cultural_festivals_to_bundles,
    museums_to_bundles,
    parking_lots_to_bundles,
    special_streets_to_bundles,
    tourist_attractions_to_bundles,
)
from kortravelmap.settings import KorTravelMapSettings

from dagster import AssetExecutionContext, Backoff, Failure, RetryPolicy, asset

from .etl import (
    AddressFindingObservationReceipt,
    DagsterFeatureLoadResult,
    _add_output_metadata,
    _dagster_run_id,
    load_feature_bundle_batches_for_dagster,
    load_feature_bundles_for_dagster,
)
from .feature_operation_tracking import (
    FeatureOperationGuardUnavailable,
    require_feature_operation_guard,
    run_tracked_feature_asset,
)
from .geo_reuse import transform_reusing_stored_geo
from .mois_chunked_load import MoisLoadPlan, load_mois_license_records_chunked
from .source_replay import (
    apply_replay_provenance,
    ensure_replay_complete,
    is_replay,
    prefetch_replay,
)

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient

    from .resources import GeoDatasetHandle

DATAGOKR_STANDARD_PROVIDER_NAME: Final[str] = "data.go.kr-standard"
"""전국 표준데이터 provider canonical name."""

FEATURE_LOAD_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=Backoff.EXPONENTIAL,
)
"""provider Feature load asset 공통 retry policy."""

MAP_POOL_PREFIX: Final[str] = "kor_travel_map."
"""Map pool 이름의 접두사.

pool 이름공간과 ``concurrency.pools.default_limit``은 Dagster **instance 전역**이다.
여러 프로젝트가 한 instance를 쓰는 공유 plane에서 접두사 없는 이름(``kor_travel_geo`` 등)은
다른 프로젝트의 같은 이름 pool과 슬롯을 나눠 서로를 막는다.
그래서 Map pool은 전부 이 접두사로 시작한다(tag key ``kor_travel_map.*``와 같은 규칙).
"""


GEO_HEAVY_POOL: Final[str] = f"{MAP_POOL_PREFIX}kor_travel_geo"
"""역지오코딩을 대량으로 하는 적재 asset을 인스턴스 전체에서 직렬화하는 pool.

**왜 필요했나 — 원인을 두 번 쟀다.** 2026-09-19에
`feature_place_mcst_culture_job`이 2시간54분·4회 시도 끝에
`GeoRequestError: ReadTimeout`으로 죽었다. 처음에 나는 그것을 "geo가 느리다"로
읽었는데 **틀렸다.** 같은 시각 geo reverse는 p50 86ms로 답했고 5시간 동안
pool 포화 신호(503/E0500)를 한 건도 내지 않았다. 다시 잰 것은 호스트다.

    /proc/pressure/io   full avg300 = 25.5%   ← 1/4 시간 동안 모든 태스크가 막힘
    /proc/pressure/cpu  full avg300 =  0.0%   ← CPU는 병목이 아니다
    04:05:00 최대 동시 run             8건

n150은 4코어이고 단일 회전 디스크를 weather/concierge/geo/airport와 함께 쓴다 —
이 파일이 아니라 `docker/dagster.yaml`이 그 사실을 이미 적어 두었다. 그런데
geo를 대량으로 쓰는 asset 중 pool을 선언한 것은 **하나도 없었다.** cron은 월간
job을 10분 간격으로 엇갈려 두었지만, 한 job이 3시간이면 그 엇갈림은 무의미하다.

**근거 갱신(2026-10-15, ADR-110 결정 6).** geo는 2026-10-14~15 odroid로 옮겨져 위
n150 디스크 대기는 더 이상 geo 쪽 원인이 아니다. pool은 **유지**하되 이유가 바뀌었다 —
**odroid geo CPU 보호**(A55 ×4 1.8 GHz, geo·weather·transport가 함께 쓴다). 대량 역지오코딩
run 둘이 겹치면 그 CPU를 나눠 다른 소비자의 지연이 커진다. 술어와 limit은 그대로다.

`docker/dagster.yaml`의 `concurrency.pools`가 `default_limit: 1`,
`granularity: run`이므로 **이 이름을 선언하는 것만으로** 인스턴스 전역에서 한
번에 하나만 돈다.

**무엇이 여기 들어오고 무엇이 빠지는가는 유도한다.** 대상은
`reverse_geocoder=`를 넘기는 asset 중 schedule spec에 `max_runtime_seconds`가
**없는** 것이다 — 그 값이 있다는 것은 저장소가 그 job을 "지연되면 안 되는
freshness 민감 job"으로 분류했다는 뜻이고, 그런 job을 몇 시간짜리 월간 적재
뒤에 줄 세우면 시간별 수집이 그만큼 멈춘다. (종전에는 매시 수집하던 날씨 asset 둘이
geo를 쓰면서도 이 이유로 빠져 있었다 — 2026-10-01 ADR-105로 asset째 사라져 지금은
해당하는 asset이 없다.)
`tests/lint/test_geo_heavy_assets_declare_the_pool.py`가 이 유도를 고정한다.

**한계 — pool이 덮지 못하는 축.** 이것은 `@asset` 데코레이터에 걸린다. 큐 경로
(`feature_update_runner`)는 asset wrapper를 **우회하고** 원본 run 함수를 직접
부르므로 이 pool을 claim하지 않는다. 즉 예약·수동 실행만 묶인다. 큐 경로에는
별도로 `provider_rate_gate`가 있다.
"""


MOIS_RECORD_BATCH_SIZE: Final[int] = 1000
"""MOIS bulk record를 FeatureBundle로 변환하기 전에 끊어 읽는 record batch 크기."""

_KST = timezone(timedelta(hours=9))
_MISSING: Final = object()


_COMMON_RESOURCE_KEYS: Final[set[str]] = {
    "feature_operation_guard",
    "kor_travel_map_client",
    "reverse_geocoder",
    "kor_travel_geo_dataset",
    "fetched_at",
    "strict_address",
}


async def run_feature_event_datagokr_cultural_festivals(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국문화축제표준데이터 record를 event Feature로 적재한다."""
    source = await _resource_value(context, "datagokr_cultural_festivals")
    records = await _record_list(context, "datagokr_cultural_festivals")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        cultural_festivals_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=DATAGOKR_STANDARD_PROVIDER_NAME,
        dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
        bundles=_replayed(source, bundles),
        # replay는 provider를 관측하지 않았다 — seal(관측 시각 영수증)·sync state를 쓰지 않는다.
        authoritative_snapshot_complete=not is_replay(source),
        record_sync_state=not is_replay(source),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_event",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"datagokr_cultural_festivals"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_event_datagokr_cultural_festivals(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_event_datagokr_cultural_festivals
    )


async def run_feature_place_transport_fuel_stations(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """오피넷 주유소(transport export)를 place Feature로 적재한다.

    transport가 전국 주유소를 8시간마다 수집해 두므로 Map은 OpiNet 쿼터·scope를 신경 쓰지
    않는다(ADR-106). export는 마지막 성공 수집 근처에 본 주유소만 내므로 완전 snapshot이다.
    """
    records = await _record_list(context, "transport_fuel_stations")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        stations_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_FUEL_STATIONS,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"transport_fuel_stations"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_transport_fuel_stations(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_transport_fuel_stations)


async def run_feature_place_transport_rest_areas(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """고속도로 휴게소(transport export)를 place Feature로 적재한다."""
    records = await _record_list(context, "transport_rest_areas")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        rest_areas_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_REST_AREAS,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"transport_rest_areas"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_transport_rest_areas(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_transport_rest_areas)


async def run_feature_place_krheritage_items(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """국가유산 item record를 place/area Feature로 적재한다."""
    records = await _record_list(context, "krheritage_items")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        heritage_items_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    retired = 0

    async def _load_and_retire(
        snapshot_bundles: Sequence[Any],
        geo: GeoLoadContext | None,
    ) -> FeatureLoadResult:
        nonlocal retired
        load, retired = await client.load_authoritative_feature_snapshot(
            snapshot_bundles,
            provider=KRHERITAGE_PROVIDER_NAME,
            dataset_key=KRHERITAGE_DATASET_KEY,
            source_entity_type="heritage",
            retire_geometryless_areas=True,
            geo=geo,
        )
        return load

    result = await _load(
        context,
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        load_all=_load_and_retire,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )
    if retired:
        context.log.info(
            "krheritage geometry 없는 area feature %d건 retired 전이",
            retired,
        )
    return result


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krheritage_items"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_krheritage_items(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_krheritage_items)


async def run_feature_event_krheritage_events(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """국가유산 행사 record를 event Feature로 적재한다."""
    records = await _record_list(context, "krheritage_events")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        heritage_events_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_event",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krheritage_events"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_event_krheritage_events(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_event_krheritage_events)


async def run_feature_place_mois_licenses(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """MOIS 인허가 record를 place Feature로 **재개형**으로 적재한다 (ADR-108).

    업종별·500행 chunk마다 commit하고, 이미 같은 payload로 적재된 행은 지오코딩 없이
    건너뛰며, run 시간 상한에 닿으면 정상 종료한다 — 다음 run(이어 달리기 sensor)이
    그 자리부터 잇는다. 세부는 :mod:`~.mois_chunked_load`.

    provider sync 성공은 **전 업종을 끝까지 본 run**만 기록한다. 부분 run이 성공을 남기면
    "MOIS가 동기화됐다"는 신호가 거짓이 된다. 그리고 미관측 finding의 stale close는 하지
    않는다 — 이 run은 이미 적재돼 있던 행을 다시 검증하지 않으므로 "이번 run이 보지
    못했다"가 "고쳐졌다"를 뜻하지 않는다.
    """
    fetched_at = await _fetched_at(context)
    dataset_key = str(
        await _resource_value(context, "mois_dataset_key", default=MOIS_BULK_DATASET_KEY)
    )
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    strict_address = cast(
        "bool | str",
        await _resource_value(context, "strict_address", default="strict"),
    )
    plan = cast(MoisLoadPlan, await _resource_value(context, "mois_load_plan"))
    records = await _resource_value(context, "mois_license_records")
    if isinstance(records, str | bytes) or not isinstance(records, Iterable):
        raise TypeError("mois_license_records resource는 record iterable이어야 함.")

    outcome = await load_mois_license_records_chunked(
        context=context,
        client=client,
        records=records,
        plan=plan,
        fetched_at=fetched_at,
        dataset_key=dataset_key,
        strict_address=strict_address,
        reverse_geocoder=_reverse_geocoder(context),
        # 첫 지오코딩·"그대로" 판정 **전에** 읽는다(ADR-109 결정 2·4).
        current_dataset=await _current_geo_dataset(context),
    )
    # 봉인과 같은 조건이다 — 본 record가 0건인 "완료"는 sync 성공이 아니다.
    if outcome.authoritative:
        await _record_feature_sync_success(
            context,
            client,
            provider=MOIS_PROVIDER_NAME,
            dataset_key=dataset_key,
            cursor_extra={
                **_feature_result_cursor_extra(outcome.result),
                "mois_load_outcome": outcome.outcome,
                "mois_load_records_seen": outcome.records_seen,
            },
            observation_receipt=None,
        )
    return outcome.result


MOIS_LOAD_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy(max_retries=1, delay=300)
"""MOIS 재개형 적재 retry — 한 번, 5분 뒤.

종전 ``FEATURE_LOAD_RETRY_POLICY``(3회)는 매번 처음부터 다시 했다. 이제 재시도는 commit된
chunk를 건너뛰고 이어 가므로 횟수가 많을 이유가 없고, 같은 원인으로 반복 실패하면 사람이
봐야 한다(이어 달리기 sensor도 실패 run은 잇지 않는다).
"""


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS
    | {"mois_license_records", "mois_dataset_key", "mois_load_plan"},
    retry_policy=MOIS_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_mois_licenses(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_mois_licenses)


async def run_feature_place_knps_points(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """KNPS point/place record를 place Feature로 적재한다."""
    records = await _record_list(context, "knps_point_records")
    fetched_at = await _fetched_at(context)
    dataset_key = str(
        await _resource_value(context, "knps_point_dataset_key", default="knps_visitor_centers")
    )
    if dataset_key not in KNPS_PLACE_DATASETS:
        raise KeyError(f"KNPS point dataset_key가 아님: {dataset_key!r}")
    bundles = await _transform_reusing_geo(
        context,
        knps_point_records_to_bundles,
        records,
        dataset_key=dataset_key,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KNPS_PROVIDER_NAME,
        dataset_key=dataset_key,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"knps_point_records", "knps_point_dataset_key"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_knps_points(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_knps_points)


async def run_feature_geometry_knps_records(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """KNPS route/area geometry record를 Feature로 적재한다."""
    records = await _record_list(context, "knps_geometry_records")
    fetched_at = await _fetched_at(context)
    dataset_key = str(
        await _resource_value(context, "knps_geometry_dataset_key", default="knps_trails")
    )
    if dataset_key not in KNPS_GEOMETRY_DATASETS:
        raise KeyError(f"KNPS geometry dataset_key가 아님: {dataset_key!r}")
    bundles = await _transform_reusing_geo(
        context,
        knps_geometry_records_to_bundles,
        records,
        dataset_key=dataset_key,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KNPS_PROVIDER_NAME,
        dataset_key=dataset_key,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_geometry",
    required_resource_keys=_COMMON_RESOURCE_KEYS
    | {"knps_geometry_records", "knps_geometry_dataset_key"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_geometry_knps_records(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_geometry_knps_records)


async def run_feature_place_krforest_recreation_forests(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국자연휴양림 record를 place Feature로 적재한다(ADR-034 8단계)."""
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(
            context, "krforest_recreation_forests", batch_size=100
        ):
            yield await _transform_reusing_geo(
                context,
                recreation_forests_to_bundles,
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_RECREATION_FORESTS_DATASET_KEY,
        batches=_bundle_batches(),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krforest_recreation_forests"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_krforest_recreation_forests(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_place_krforest_recreation_forests
    )


async def run_feature_place_krforest_arboretums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """휴양림 수목원(SHP) record를 place Feature로 적재한다."""
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "krforest_arboretums", batch_size=100):
            yield await _transform_reusing_geo(
                context,
                arboretums_to_bundles,
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_ARBORETUMS_DATASET_KEY,
        batches=_bundle_batches(),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krforest_arboretums"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_krforest_arboretums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_krforest_arboretums)


async def run_feature_route_krforest_mountain_trails(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """산림청 등산로 SHP route를 적재한다(C05A)."""
    records = await _record_list(context, "krforest_mountain_trails")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        mountain_trails_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_MOUNTAIN_TRAILS_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        source_entity_type="mountain_trail_segment",
        retire_absent_from_snapshot=True,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_route",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krforest_mountain_trails"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_route_krforest_mountain_trails(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_route_krforest_mountain_trails)


async def run_feature_route_krforest_dulle_trails(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """산림청 둘레길 SHP route를 적재한다(C05A)."""
    records = await _record_list(context, "krforest_dulle_trails")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        dulle_trails_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_DULLE_TRAILS_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        source_entity_type="dulle_trail_segment",
        retire_absent_from_snapshot=True,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_route",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krforest_dulle_trails"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_route_krforest_dulle_trails(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_route_krforest_dulle_trails)


async def run_feature_notice_krforest_landslide_forecast_issues(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """산사태 예보발령·해제 notice snapshot을 적재한다(C05D)."""

    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    records = await _record_list(context, "krforest_landslide_forecast_issues")
    fetched_at = await _fetched_at(context)
    bundles = landslide_forecast_issues_to_bundles(records, fetched_at=fetched_at)
    active_lineage_keys = {
        bundle.source_record.source_entity_id
        for bundle in bundles
        if bundle.feature.detail is not None
        and bool(bundle.feature.detail.payload.get("active"))
    }
    reconciled: NoticeReconcileResult | None = None

    async def load_snapshot_atomically(
        validated_bundles: Sequence[Any],
        _geo: GeoLoadContext | None,
    ) -> FeatureLoadResult:
        # notice 활성 집합은 geo를 쓰지 않는다(geo_applied 전부 False) — 스탬프 대상이 아니다.
        nonlocal reconciled
        atomic_load = getattr(client, "load_authoritative_notice_snapshot", None)
        if not callable(atomic_load):
            raise RuntimeError("산사태 notice snapshot은 atomic snapshot load client가 필요하다.")
        outcome = cast(
            NoticeFeatureLoadResult,
            await atomic_load(
                bundles=validated_bundles,
                provider=KRFOREST_PROVIDER_NAME,
                dataset_key=KRFOREST_LANDSLIDE_FORECAST_DATASET_KEY,
                source_entity_type=LANDSLIDE_FORECAST_SOURCE_ENTITY_TYPE,
                active_lineage_keys=active_lineage_keys,
                observed_at=fetched_at,
            ),
        )
        reconciled = outcome.reconcile
        return outcome.load

    result = await _load(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_LANDSLIDE_FORECAST_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        load_all=load_snapshot_atomically,
        geo_applied=GeoApplied(reverse=False, geocode=False),
    )
    if reconciled is None:
        raise RuntimeError("산사태 notice atomic load가 reconcile 결과를 반환하지 않았다.")
    context.log.info(
        "산사태 notice %d건 적재, %d건 종료, %d건 재개.",
        len(bundles),
        reconciled.closed,
        reconciled.reopened,
    )
    return result


@asset(
    group_name="features_notice",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krforest_landslide_forecast_issues"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_notice_krforest_landslide_forecast_issues(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_notice_krforest_landslide_forecast_issues
    )


async def run_feature_place_standard_museums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국박물관미술관표준데이터 record를 place Feature로 적재한다(ADR-034 9단계)."""
    source = await _resource_value(context, "standard_museums")
    await prefetch_replay(source)
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "standard_museums", batch_size=100):
            yield apply_replay_provenance(
                source,
                await _transform_reusing_geo(
                    context,
                    museums_to_bundles,
                    records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
                ),
            )
        ensure_replay_complete(source)

    return await _load_snapshot_batches(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_MUSEUMS,
        batches=_bundle_batches(),
        replay=is_replay(source),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_museums"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_standard_museums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_standard_museums)


async def run_feature_place_standard_tourist_attractions(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국관광지표준데이터 record를 place Feature로 적재한다(ADR-034 보조)."""
    source = await _resource_value(context, "standard_tourist_attractions")
    await prefetch_replay(source)
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(
            context, "standard_tourist_attractions", batch_size=100
        ):
            yield apply_replay_provenance(
                source,
                await _transform_reusing_geo(
                    context,
                    tourist_attractions_to_bundles,
                    records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
                ),
            )
        ensure_replay_complete(source)

    return await _load_snapshot_batches(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_TOURIST_ATTRACTIONS,
        batches=_bundle_batches(),
        replay=is_replay(source),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_tourist_attractions"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_standard_tourist_attractions(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_place_standard_tourist_attractions
    )


async def run_feature_place_standard_parking_lots(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국주차장표준데이터 record를 place Feature로 적재한다(ADR-034 보조)."""
    source = await _resource_value(context, "standard_parking_lots")
    await prefetch_replay(source)
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "standard_parking_lots", batch_size=100):
            yield apply_replay_provenance(
                source,
                await _transform_reusing_geo(
                    context,
                    parking_lots_to_bundles,
                    records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
                ),
            )
        ensure_replay_complete(source)

    return await _load_snapshot_batches(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_PARKING_LOTS,
        batches=_bundle_batches(),
        replay=is_replay(source),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_parking_lots"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_standard_parking_lots(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_place_standard_parking_lots
    )


async def run_feature_place_standard_special_streets(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국지역특화거리표준데이터 record를 place anchor Feature로 적재한다."""
    source = await _resource_value(context, "standard_special_streets")
    await prefetch_replay(source)
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "standard_special_streets", batch_size=100):
            yield apply_replay_provenance(
                source,
                await _transform_reusing_geo(
                    context,
                    special_streets_to_bundles,
                    records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
                ),
            )
        ensure_replay_complete(source)

    return await _load_snapshot_batches(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_SPECIAL_STREETS,
        batches=_bundle_batches(),
        replay=is_replay(source),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_special_streets"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_standard_special_streets(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_place_standard_special_streets
    )


async def run_feature_place_datagokr_file_data(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """data.go.kr curated fileData raw row를 dataset별 place Feature로 적재한다."""
    dataset_key = str(await _resource_value(context, "datagokr_file_data_dataset_key"))
    source = await _resource_value(context, "datagokr_file_data_records")
    records = await _record_list(context, "datagokr_file_data_records")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        file_data_rows_to_bundles,
        records,
        dataset_key=dataset_key,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=DATAGOKR_FILEDATA_PROVIDER_NAME,
        dataset_key=dataset_key,
        bundles=_replayed(source, bundles),
        # replay는 provider를 관측하지 않았다 — seal(관측 시각 영수증)·sync state를 쓰지 않는다.
        authoritative_snapshot_complete=not is_replay(source),
        record_sync_state=not is_replay(source),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS
    | {"datagokr_file_data_records", "datagokr_file_data_dataset_key"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_datagokr_file_data(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_datagokr_file_data)


async def run_feature_place_khoa_beaches(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """해양수산부 해수욕장정보 record를 place Feature로 적재한다(ADR-034 보조)."""
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "khoa_beaches", batch_size=100):
            yield await _transform_reusing_geo(
                context,
                beaches_to_bundles,
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=KHOA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_BEACHES,
        batches=_bundle_batches(),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"khoa_beaches"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_khoa_beaches(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_khoa_beaches)


async def run_feature_place_transport_airports(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """국내 운영 공항(transport export)을 place Feature로 적재한다."""
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "transport_airports", batch_size=100):
            yield await _transform_reusing_geo(
                context,
                airports_to_bundles,
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_AIRPORTS,
        batches=_bundle_batches(),
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"transport_airports"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_transport_airports(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_transport_airports)


async def run_feature_place_kor_travel_concierge_youtube(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """kor-travel-concierge YouTube 장소 후보 export를 place Feature로 적재한다.

    ``operation=upsert``는 bundle 적재, ``reject``/``tombstone``은 대응 feature를
    ``retired/suppressed``로 전이한다(ADR-050 #4, T-217b — MOIS Step C 동형).
    적재 후 retire 순서가 mid-run 검수 전이(되돌리기)의 구 operation으로 신
    상태를 덮지 않도록, 후보별 마지막 관측 item으로 먼저 압축한다.
    """
    records = kor_travel_concierge_latest_items(
        await _record_list(context, "kor_travel_concierge_youtube_features")
    )
    fetched_at = await _fetched_at(context)
    # T-VN-H28B: 건별 격리를 실제로 결선한다. 결선하지 않으면 item 1건의 구성 실패가
    # batch 전체를 죽인다(concierge export는 1회 1,477건 전량 재생이라 손실이 전부다).
    quarantined: list[KorTravelConciergeQuarantine] = []
    # ADR-109 결정 6(a): run-scoped 현재 토큰(첫 지오코딩 전에 읽는다)과 payload 토큰이 같을 때만
    # payload 행정코드를 믿는다.
    current_dataset = await _current_geo_dataset(context)
    bundles = await kor_travel_concierge_items_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
        quarantine=quarantined,
        current_data_token=current_dataset.data_token if current_dataset is not None else None,
    )
    upsert_count = kor_travel_concierge_upsert_count(records)
    accounted_count = len(bundles) + len(quarantined)
    if accounted_count != upsert_count:
        raise Failure(
            description=(
                "concierge upsert 보존 불변식 위반: "
                f"input={upsert_count}, bundle+quarantine={accounted_count}"
            )
        )
    if quarantined:
        # silent cap 금지 — 격리한 건수와 사유를 metadata로 드러낸다.
        # 초크포인트를 지나야 분자도 함께 실린다(concierge cursor 루프가 센다).
        _add_output_metadata(
            context,
            {
                "concierge_quarantined_count": len(quarantined),
                "concierge_quarantined_item_keys": [
                    entry.item_key for entry in quarantined[:20]
                ],
                "concierge_quarantined_reasons": [
                    f"{entry.reason_code}: {entry.message}"[:300]
                    for entry in quarantined[:20]
                ],
            },
        )
    retired_entity_ids = kor_travel_concierge_inactive_entity_ids(records)
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    retired = 0

    async def _load_and_retire(
        snapshot_bundles: Sequence[Any],
        geo: GeoLoadContext | None,
    ) -> FeatureLoadResult:
        nonlocal retired
        load, retired = await client.load_authoritative_feature_snapshot(
            snapshot_bundles,
            provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
            dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
            source_entity_type=KOR_TRAVEL_CONCIERGE_SOURCE_ENTITY_TYPE,
            retired_source_entity_ids=retired_entity_ids,
            geo=geo,
        )
        return load

    result = await _load(
        context,
        provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
        dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        load_all=_load_and_retire,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )
    if retired_entity_ids:
        context.log.info(
            "kor-travel-concierge reject/tombstone %d건 → feature %d건 retired 전이",
            len(retired_entity_ids),
            retired,
        )
    return result


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"kor_travel_concierge_youtube_features"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_kor_travel_concierge_youtube(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_place_kor_travel_concierge_youtube
    )


async def run_feature_event_visitkorea_enrichment(
    context: AssetExecutionContext,
) -> "FestivalEnrichmentReviewRefreshResult":
    """VisitKorea 축제 record를 적재된 datagokr 축제에 매칭해 enrichment를 적재한다.

    feature를 만들지 않는 2차 enrichment(ADR-042) — ``client.load_festival_enrichment``
    가 한 transaction에서 candidate 로드 → 이름 매칭 → enrichment link 적재를 수행.
    """
    records = await _record_list(context, "visitkorea_festival_events")
    fetched_at = await _fetched_at(context)
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    result = await client.refresh_festival_enrichment_reviews(
        records,
        fetched_at=fetched_at,
    )
    # 초크포인트를 지나야 분자가 함께 실린다. 이 asset은 visitkorea fetcher가
    # 센 수를 들고 있으면서 종전에는 `context.add_output_metadata`를 직접 불러
    # 그 값을 버렸다(2026-09-13 3차 적대 리뷰).
    _add_output_metadata(context, result.as_metadata())
    await _record_feature_sync_success(
        context,
        client,
        provider="python-visitkorea-api",
        dataset_key="visitkorea_festival_events",
        cursor_extra=result.as_metadata(),
    )
    return result


@asset(
    group_name="features_event",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"visitkorea_festival_events"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_event_visitkorea_enrichment(
    context: AssetExecutionContext,
) -> "FestivalEnrichmentReviewRefreshResult":
    return await run_tracked_feature_asset(
        context, run_feature_event_visitkorea_enrichment
    )


FEATURE_LOAD_ASSETS: Final = [
    feature_event_datagokr_cultural_festivals,
    feature_place_transport_fuel_stations,
    feature_place_transport_rest_areas,
    feature_place_krheritage_items,
    feature_event_krheritage_events,
    feature_place_mois_licenses,
    feature_place_knps_points,
    feature_geometry_knps_records,
    feature_place_krforest_recreation_forests,
    feature_place_krforest_arboretums,
    feature_route_krforest_mountain_trails,
    feature_route_krforest_dulle_trails,
    feature_notice_krforest_landslide_forecast_issues,
    feature_place_standard_museums,
    feature_place_standard_tourist_attractions,
    feature_place_standard_parking_lots,
    feature_place_standard_special_streets,
    feature_place_datagokr_file_data,
    feature_place_khoa_beaches,
    feature_place_transport_airports,
    feature_place_kor_travel_concierge_youtube,
    feature_event_visitkorea_enrichment,
]
"""현재 구현 완료된 Feature provider 적재 asset 목록."""


def _replayed(source: object, bundles: Sequence[Any]) -> list[Any]:
    """replay면 provenance를 되돌리고 전부 덮었는지 본다(목록 적재 — 쓰기 전). fetch면 그대로."""
    replayed = apply_replay_provenance(source, bundles)
    ensure_replay_complete(source)
    return replayed


async def _load_snapshot_batches(
    context: AssetExecutionContext,
    *,
    provider: str,
    dataset_key: str,
    batches: AsyncIterable[Sequence[Any]],
    geo_applied: GeoApplied,
    replay: bool = False,
) -> DagsterFeatureLoadResult:
    """전체 snapshot을 보관하지 않고 기존 단일 transaction·봉인 계약으로 적재한다.

    ``replay=True``(ADR-109 결정 7)는 provider를 관측하지 않은 run이다 — curation seal(영수증
    ``observed_at``)·authoritative 완료·sync 성공 cursor를 쓰지 않는다. 적재는 같은 한 transaction.
    """
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    strict_address = cast(
        "bool | str", await _resource_value(context, "strict_address", default="strict")
    )

    async def _load_all(
        items: AsyncIterable[Sequence[Any]], geo: GeoLoadContext | None
    ) -> FeatureLoadResult:
        return await client.load_feature_bundle_batches(
            items, curation_dataset=None if replay else (provider, dataset_key), geo=geo
        )

    result = await load_feature_bundle_batches_for_dagster(
        context=context,
        client=client,
        batches=batches,
        provider=provider,
        dataset_key=dataset_key,
        strict_address=strict_address,
        load_all=_load_all,
        authoritative_snapshot_complete=not replay,
        **(await _geo_run_inputs(context, geo_applied)),
    )
    if not replay:
        await _record_feature_sync_success(
            context,
            client,
            provider=provider,
            dataset_key=dataset_key,
            cursor_extra=_feature_result_cursor_extra(result),
            observation_receipt=result.observation_receipt,
        )
    return result


async def _load(
    context: AssetExecutionContext,
    *,
    provider: str,
    dataset_key: str,
    bundles: list[Any],
    authoritative_snapshot_complete: bool,
    source_entity_type: str | None = None,
    retire_absent_from_snapshot: bool = False,
    record_sync_state: bool = True,
    load_all: Callable[[Sequence[Any], GeoLoadContext | None], Awaitable[FeatureLoadResult]]
    | None = None,
    geo_applied: GeoApplied,
) -> DagsterFeatureLoadResult:
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    # bool(True/False) 하위호환 + settings 모드 문자열(strict/drop/off, #376).
    strict_address = cast(
        "bool | str",
        await _resource_value(context, "strict_address", default="strict"),
    )
    result = await load_feature_bundles_for_dagster(
        context=context,
        client=client,
        bundles=bundles,
        provider=provider,
        dataset_key=dataset_key,
        strict_address=strict_address,
        authoritative_snapshot_complete=authoritative_snapshot_complete,
        source_entity_type=source_entity_type,
        retire_absent_from_snapshot=retire_absent_from_snapshot,
        load_all=load_all,
        **(await _geo_run_inputs(context, geo_applied)),
    )
    if record_sync_state:
        await _record_feature_sync_success(
            context,
            client,
            provider=provider,
            dataset_key=dataset_key,
            cursor_extra=_feature_result_cursor_extra(result),
            observation_receipt=result.observation_receipt,
        )
    return result


def _feature_result_cursor_extra(result: DagsterFeatureLoadResult) -> dict[str, object]:
    return {
        "bundles_total": result.load.bundles_total,
        "features_inserted": result.load.features_inserted,
        "features_updated": result.load.features_updated,
        "source_records_inserted": result.load.source_records_inserted,
        "source_links_inserted": result.load.source_links_inserted,
        "source_links_updated": result.load.source_links_updated,
    }


async def _exact_sync_membership(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
    *,
    boundary: str,
    provider: str,
    dataset_key: str,
) -> ProviderDatasetOperationMembership:
    """sync-state 읽기·쓰기에 쓸 **exact** membership을 얻는다.

    T-VN-33 이후 sync state의 정체성은 ``provider_dataset_id + sync_scope +
    operation_key``다(ADR-088 §결정 2). provider/dataset label로는 어느 행을
    가리키는지 결정되지 않는다.

    queue worker가 request를 claim할 때 고정한 typed membership resource가 있으면
    그것을 쓰고, 없으면 guard가 고정한 **실행 manifest** 안에서 고른다.
    **provider나 dataset label에서 membership을 역산하는 fallback은 두지 않는다** —
    그렇게 하면 guard가 고정한 실행 대상과 다른 행에 cursor를 쓸 수 있다.

    카탈로그 drift 검사는 "manifest == 실행 가능 집합"이 아니라 **"manifest ⊆ 실행
    가능 집합"**이다. run은 operation의 실행 가능 scope 중 일부만 실행 manifest로
    선언할 수 있고(``EXECUTION_SCOPES_TAG``), 그때 두 집합은 같지 않다. 같기를
    요구하면 dataset을 여러 개 묶은 operation의 적재가 여기서 죽는다 —
    ``0089_tvn33_expand_seed``는 ``feature_place_knps_points_job``과
    ``feature_geometry_knps_records_job``에 각각 dataset 5개를 결박하는데 asset은
    run 1회에 1개만 적재한다.
    """

    resource_membership = await _resource_value(
        context,
        "feature_update_membership",
        default=None,
    )
    if resource_membership is not None:
        if not isinstance(resource_membership, ProviderDatasetOperationMembership):
            raise FeatureOperationGuardUnavailable(
                boundary=boundary,
                reason="feature_update_membership_wrong_type",
            )
        return resource_membership

    guard = require_feature_operation_guard(context, boundary=boundary)
    if guard.operation_key is None:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="operation_key_missing",
        )
    executable = await client.resolve_feature_operation_memberships(
        operation_key=guard.operation_key,
    )
    if not set(guard.memberships) <= set(executable):
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="membership_snapshot_changed",
        )
    # 한 operation이 여러 dataset을 다루는 경우가 있다(예: KNPS point는 5개).
    # 그래서 "정확히 하나"로는 고를 수 없고, **이번 호출이 적재한 dataset**으로
    # 좁힌다. operation은 여전히 guard가 준 것이므로 label에서 역산하는 것이
    # 아니다 — guard가 고정한 manifest 안에서 고르기만 한다.
    membership = await client.resolve_feature_operation_dataset_membership(
        operation_key=guard.operation_key,
        provider=provider,
        dataset_key=dataset_key,
    )
    if membership not in guard.memberships:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="membership_outside_guard_snapshot",
        )
    return membership


async def _record_feature_sync_success(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
    *,
    provider: str,
    dataset_key: str,
    cursor_extra: dict[str, object],
    observation_receipt: AddressFindingObservationReceipt | None = None,
) -> None:
    record_sync_success = getattr(client, "record_sync_success", None)
    if not callable(record_sync_success):
        context.log.warning(
            "provider sync_state 기록 생략: client가 record_sync_success를 제공하지 않음"
        )
        return
    fetched_at = await _fetched_at(context)
    try:
        asset_key = context.asset_key.to_user_string()
    except Exception:
        asset_key = "direct_invocation"
    cursor = {
        "loaded_at": fetched_at.isoformat(),
        "asset_key": asset_key,
        **cursor_extra,
    }
    membership = await _exact_sync_membership(
        context,
        client,
        boundary="feature_sync_state",
        provider=provider,
        dataset_key=dataset_key,
    )
    await client.record_sync_success_for_operation_membership(
        membership=membership,
        cursor=cursor,
    )

    # Provider sync 성공과 stale close 권한은 별개다(#911). source 전체 관측과 finding
    # durable 기록을 증명한 typed receipt가 없으면 absence를 부정 증거로 쓰지 않는다.
    if observation_receipt is None or not observation_receipt.permits_stale_close:
        return

    close_stale = getattr(client, "close_stale_address_validation_findings", None)
    run_id = _dagster_run_id(context)
    if callable(close_stale) and run_id:
        try:
            closed = await close_stale(
                provider=provider,
                dataset_key=dataset_key,
                run_id=run_id,
                receipt=DurableIntegrityObservationReceipt(
                    authoritative_snapshot_complete=(
                        observation_receipt.authoritative_snapshot_complete
                    ),
                    source_observations=observation_receipt.source_observations,
                    findings_observed=observation_receipt.findings_observed,
                    findings_unique=observation_receipt.findings_unique,
                    findings_upserted=observation_receipt.findings_upserted,
                    finding_persistence_complete=(
                        observation_receipt.finding_persistence_complete
                    ),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            context.log.warning(f"finding close 생략 (provider={provider}): {exc!r}")
        else:
            if closed:
                context.log.info(
                    f"이번 run이 관측하지 않은 finding {closed}건을 닫았다 "
                    f"(provider={provider}, dataset={dataset_key})"
                )


async def _record_list(context: AssetExecutionContext, resource_key: str) -> list[Any]:
    records: list[Any] = []
    async for batch in _record_batches(context, resource_key):
        records.extend(batch)
    return records


async def _record_batches(
    context: AssetExecutionContext,
    resource_key: str,
    *,
    batch_size: int = MOIS_RECORD_BATCH_SIZE,
) -> AsyncIterator[list[Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    value = await _resource_value(context, resource_key)
    if isinstance(value, str | bytes):
        raise TypeError(f"{resource_key} resource는 문자열이 아니라 record iterable이어야 함.")
    if isinstance(value, AsyncIterable):
        batch: list[Any] = []
        async for item in value:
            batch.append(item)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
        return
    if isinstance(value, Iterable):
        batch = []
        for item in value:
            batch.append(item)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
        return
    raise TypeError(f"{resource_key} resource는 iterable이어야 함.")


async def _fetched_at(context: AssetExecutionContext) -> datetime:
    value = await _resource_value(context, "fetched_at", default=None)
    if value is None:
        return datetime.now(_KST)
    if not isinstance(value, datetime):
        raise TypeError("fetched_at resource는 datetime이어야 함.")
    return value


class _GeoRunInputs(TypedDict):
    geo_applied: GeoApplied
    current_dataset: DatasetRef | None
    geo_stats: GeoCallStats | None


async def _geo_run_inputs(
    context: AssetExecutionContext, geo_applied: GeoApplied
) -> _GeoRunInputs:
    """적재 wrapper에 넘길 run의 geo 입력 — 사용 신호·run-scoped 현재 토큰·관측 계수(ADR-109).

    현재 토큰은 resource ``kor_travel_geo_dataset``의 handle이 처음 쓰일 때 한 번 읽는다 — 큐
    runner도 같은 resource를 common resource로 넘긴다. geo 콜러블을 하나도 넘기지 않은 run은
    읽지 않는다(쓸 데가 없고, geo가 꺼져 있으면 connect 상한만큼 기다리게 된다). 키가 배선되지
    않은 context는 "geo 장애"와 구별되도록 WARNING을 남긴다.
    """
    current: DatasetRef | None = None
    if geo_applied.reverse or geo_applied.geocode:
        current = await _current_geo_dataset(context)
    stats: GeoCallStats | None = None
    if geo_applied.reverse:
        stats = cast("GeoCallStats | None", getattr(_reverse_geocoder(context), "stats", None))
    return {"geo_applied": geo_applied, "current_dataset": current, "geo_stats": stats}


async def _current_geo_dataset(context: AssetExecutionContext) -> DatasetRef | None:
    """run-scoped 현재 토큰 — resource handle이 처음 읽은 값(이후 같은 값). 키 미배선은 WARNING."""
    handle = _resource_object(context, "kor_travel_geo_dataset", default=None)
    if handle is None:
        log = getattr(context, "log", None)  # 직접 호출 테스트 대역에는 log가 없을 수 있다
        if log is not None:
            log.warning(
                "resource kor_travel_geo_dataset가 이 context에 없다(배선 누락) — 현재 토큰 "
                "None으로 진행"
            )
        return None
    return await cast("GeoDatasetHandle", handle).current()


class _TokenFirstReverseGeocoder:
    """첫 역지오코딩 **전에** run의 현재 토큰을 읽게 하는 감싸개(ADR-109 결정 2, #1327 최종 리뷰).

    ``_load`` 경로는 변환(지오코딩)이 끝난 뒤에야 적재 wrapper로 들어가므로, 현재 토큰을 거기서 처음
    읽으면 run 도중 geo가 데이터셋을 바꿨을 때 옛 데이터로 해석한 행이 **새** 토큰으로 봉인될 수
    있다 (위험한 방향). 이 감싸개는 처음 불릴 때 handle을 먼저 읽고 그 뒤에 지오코딩한다 — handle이
    값을 기억하므로 적재 wrapper가 나중에 읽는 값은 지오코딩 **전** 값이다. 계수(``stats``)는 그대로
    보인다.
    """

    def __init__(self, inner: Any, before: Callable[[], Awaitable[object]]) -> None:
        self._inner = inner
        self._before = before
        self._ready = False

    @property
    def stats(self) -> GeoCallStats | None:
        return cast("GeoCallStats | None", getattr(self._inner, "stats", None))

    async def _ensure_token(self) -> None:
        if not self._ready:
            await self._before()
            self._ready = True

    async def __call__(self, coord: Any) -> Any:
        await self._ensure_token()
        return await self._inner(coord)


class _TokenFirstObservedReverseGeocoder(_TokenFirstReverseGeocoder):
    """``observe``가 있는 역지오코더용(``ObservedReverseGeocoder`` 프로토콜을 유지한다)."""

    async def observe(self, coord: Any) -> Any:
        await self._ensure_token()
        return await self._inner.observe(coord)


def _reverse_geocoder(context: AssetExecutionContext) -> ReverseGeocoder | None:
    inner = _resource_object(context, "reverse_geocoder", default=None)
    if inner is None or _resource_object(context, "kor_travel_geo_dataset", default=None) is None:
        return cast("ReverseGeocoder | None", inner)
    wrapper_type = (
        _TokenFirstObservedReverseGeocoder
        if callable(getattr(inner, "observe", None))
        else _TokenFirstReverseGeocoder
    )
    return cast(
        "ReverseGeocoder",
        wrapper_type(inner, lambda: _current_geo_dataset(context)),
    )


async def _transform_reusing_geo(
    context: AssetExecutionContext,
    transform: Callable[..., Awaitable[list[Any]]],
    records: Iterable[Any],
    /,
    **kwargs: Any,
) -> list[Any]:
    """provider 변환을 저장값 재사용과 함께 돌린다(ADR-116) — 역지오코딩 asset의 공통 자리.

    호출 모양은 ``transform(records, **kwargs)``와 같다(``reverse_geocoder=``는 호출자가
    그대로 넘긴다). run의 현재 geo 토큰이 있으면 payload·좌표·스탬프가 그대로인 행은 geo를
    부르지 않고 저장 주소 열을 답으로 쓴다
    (:func:`kortravelmap.dagster.geo_reuse.transform_reusing_stored_geo`). 토큰이 없거나
    (비교 기준이 없다) 역지오코더가 없거나 client가 재사용 조회를 모르면 원래 호출 그대로다.

    현재 토큰은 **첫 지오코딩 전에** 읽는다(ADR-109 결정 2 —
    :class:`_TokenFirstReverseGeocoder`와 같은 순서). ``transform``은 같은 입력에 몇 번
    불려도 같은 결과를 내야 한다 — 그래서 ``records``를 목록으로 고정한다.
    """
    live = cast("ReverseGeocoder | None", kwargs.pop("reverse_geocoder", None))
    rows = records if isinstance(records, Sequence) else list(records)
    client = _resource_object(context, "kor_travel_map_client", default=None)
    read = getattr(client, "read_reusable_geo_columns", None)
    if (
        live is None
        or not callable(read)
        # 키 미배선 경고는 적재 wrapper가 run에 한 번 낸다(_geo_run_inputs) — batch마다 내지 않는다.
        or _resource_object(context, "kor_travel_geo_dataset", default=None) is None
    ):
        return await transform(rows, reverse_geocoder=live, **kwargs)
    current = await _current_geo_dataset(context)
    token = current.data_token if current is not None else None
    if token is None:
        return await transform(rows, reverse_geocoder=live, **kwargs)

    async def _lookup(bundles: Sequence[Any]) -> Mapping[str, Mapping[str, Any]] | None:
        return cast(
            "Mapping[str, Mapping[str, Any]] | None",
            await read(bundles, current_data_token=token),
        )

    async def _transform(geocoder: ReverseGeocoder) -> list[Any]:
        return await transform(rows, reverse_geocoder=geocoder, **kwargs)

    stats = cast("GeoCallStats | None", getattr(live, "stats", None))
    recheck = getattr(
        _resource_object(context, "kor_travel_geo_dataset", default=None), "recheck", None
    )

    async def _observe_current() -> None:
        # 저장값만으로 끝난 변환도 run 도중의 릴리스 전환을 보게 한다(코드 리뷰 A MED-1).
        if stats is not None and callable(recheck):
            stats.observe_dataset(cast("DatasetRef | None", await recheck()))

    return await transform_reusing_stored_geo(
        _transform,
        live=live,
        lookup=_lookup,
        stats=stats,
        after_reuse=_observe_current,
        prefetch_concurrency=KorTravelMapSettings().reverse_geocode_concurrency,
    )


def _resource_object(
    context: AssetExecutionContext,
    name: str,
    *,
    default: object = _MISSING,
) -> object:
    resources = cast(Any, context.resources)
    if not hasattr(resources, name):
        if default is not _MISSING:
            return default
        raise AttributeError(f"Dagster resource 없음: {name}")
    return getattr(resources, name)


async def _resource_value(
    context: AssetExecutionContext,
    name: str,
    *,
    default: object = _MISSING,
) -> object:
    value = _resource_object(context, name, default=default)
    if callable(value):
        value = value()
    if inspect.isawaitable(value):
        return await cast(Awaitable[object], value)
    return value
