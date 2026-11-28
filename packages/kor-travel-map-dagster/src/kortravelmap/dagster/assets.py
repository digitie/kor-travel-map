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

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.core.venue_match import (
    VenueCandidate,
    VenueMatch,
    VenueResolver,
    match_venue,
)
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.geocoding import (
    AddressGeocoder,
    GeoCallStats,
    ReverseGeocoder,
    cached_address_geocoder,
)
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    NoticeFeatureLoadResult,
    NoticeReconcileResult,
    SupersededSourceEntities,
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
    KNPS_SOURCE_ENTITY_TYPE,
    KNPS_TRAIL_COURSE_ENTITY_TYPE,
    KNPS_TRAIL_SEGMENT_ENTITY_TYPE,
    knps_geometry_records_to_bundles,
    knps_geometry_snapshot_retires_absent,
    knps_national_park_anchors,
    knps_point_records_to_bundles,
    knps_trail_courses_to_bundles,
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
    DATASET_KEY_FERRY_PORTS,
    DATASET_KEY_FUEL_STATIONS,
    DATASET_KEY_RAIL_STATIONS,
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
    MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE,
    MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE,
    arboretums_to_bundles,
    dulle_trails_to_bundles,
    mountain_trail_courses_to_bundles,
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
    EVENT_SOURCE_ENTITY_TYPE as KRHERITAGE_EVENT_ENTITY_TYPE,
)
from kortravelmap.providers.krheritage import (
    PROVIDER_NAME as KRHERITAGE_PROVIDER_NAME,
)
from kortravelmap.providers.krheritage import (
    cached_venue_resolver,
    heritage_events_to_bundles,
    heritage_items_to_bundles,
    is_legacy_heritage_event_key,
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
    DATASET_KEY_MUSEUMS,
    DATASET_KEY_PARKING_LOTS,
    DATASET_KEY_SPECIAL_STREETS,
    DATASET_KEY_TOURIST_ATTRACTIONS,
    DATASET_KEY_TRADITIONAL_MARKETS,
    STANDARD_DATA_PROVIDER_NAME,
    museums_to_bundles,
    parking_lots_to_bundles,
    special_streets_to_bundles,
    tourist_attractions_to_bundles,
    traditional_markets_to_bundles,
)
from kortravelmap.providers.transport_reference_places import (
    ferry_ports_to_bundles,
    rail_stations_to_bundles,
)
from kortravelmap.providers.visitkorea import (
    DATASET_KEY_VISITKOREA_FESTIVALS,
    FESTIVAL_SOURCE_ENTITY_TYPE,
    VISITKOREA_PROVIDER_NAME,
    tourapi_festivals_to_bundles,
)
from kortravelmap.providers.visitkorea_attractions import (
    DATASET_KEY_VISITKOREA_ATTRACTIONS,
    TOURAPI_DETAIL_OPS,
    TourApiDetailOp,
    merge_tourapi_detail_ops,
    plan_attraction_details,
    plan_tourapi_detail_ops,
    tourapi_attractions_to_bundles,
)
from kortravelmap.settings import KorTravelMapSettings

from dagster import AssetExecutionContext, Backoff, Failure, Jitter, RetryPolicy, asset

from .etl import (
    _DATASET_LOSS_DROP_RATIO,
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
from .provider_fetchers import (
    fetch_visitkorea_attraction_details,
    fetch_visitkorea_detail_ops,
    fetch_visitkorea_service_members,
)
from .source_replay import (
    apply_replay_provenance,
    ensure_replay_complete,
    is_replay,
    prefetch_replay,
)

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient

    from .resources import GeoDatasetHandle

FEATURE_LOAD_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=Backoff.EXPONENTIAL,
    # 같은 순간 실패한 asset들이 같은 순간 다시 묻지 않게 간격을 흔든다(2026-11-23 감사 P2).
    # Dagster PLUS_MINUS는 ±delay(60초)다 — 지수 간격 60·180·420초가 0~120·120~240·360~480초가 된다.
    jitter=Jitter.PLUS_MINUS,
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
    required_resource_keys=_COMMON_RESOURCE_KEYS
    | {"transport_rest_areas"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_transport_rest_areas(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_transport_rest_areas)


async def _current_source_entity_ids(
    context: AssetExecutionContext, provider: str, dataset_key: str
) -> frozenset[str]:
    """dataset에 이미 적재된(primary Feature active) source entity id — 읽기 전용.

    client가 이 읽기를 모르면(테스트 대역 등) 빈 집합이다 — 그때 철도역 anchor는 자연키 최소
    규칙으로만 정해진다(첫 적재와 같다).
    """
    client = _resource_object(context, "kor_travel_map_client", default=None)
    read = getattr(client, "read_current_source_records", None)
    if not callable(read):
        return frozenset()
    records, _expected = await read(provider=provider, dataset_key=dataset_key)
    return frozenset(record.source_entity_id for record in records)


async def run_feature_place_transport_rail_stations(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """도시·광역철도 역(transport 기준정보 export)을 역마다 place Feature 하나로 적재한다(ADR-120).

    원천은 노선마다 한 행이라 변환기가 같은 역을 묶는다 — 묶음은 전체 집합을 봐야 하므로 batch로
    나누지 않고 한 번에 변환한다(전국 약 1천 행).
    """
    records = await _record_list(context, "transport_rail_stations")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        rail_stations_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
        existing_natural_keys=await _current_source_entity_ids(
            context, KOR_TRAVEL_TRANSPORT_PROVIDER_NAME, DATASET_KEY_RAIL_STATIONS
        ),
    )
    return await _load(
        context,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_RAIL_STATIONS,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        # transport가 뺀 역(또는 anchor가 바뀐 옛 자연키)은 이번 완전 snapshot에 없으므로 퇴역한다.
        source_entity_type="rail_station",
        retire_absent_from_snapshot=True,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"transport_rail_stations"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_transport_rail_stations(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_transport_rail_stations)


async def run_feature_place_transport_ferry_ports(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """여객선 항구(transport 기준정보 export)를 place Feature로 적재한다(ADR-120)."""
    records = await _record_list(context, "transport_ferry_ports")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        ferry_ports_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_FERRY_PORTS,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        source_entity_type="ferry_port",
        retire_absent_from_snapshot=True,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"transport_ferry_ports"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_transport_ferry_ports(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_transport_ferry_ports)


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
        address_geocoder=_address_geocoder(context),
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
    """국가유산 행사 회차 record를 행사(프로그램)마다 event Feature 하나로 적재한다(#1468 D).

    좌표는 장소 이름이 같은 시군구의 좌표 있는 장소 Feature(``_venue_resolver``), 그다음 장소
    조각의 번지 주소 정지오코딩(``_address_geocoder``)으로 채운다.

    회차별 옛 자연키(``program::`` 접두가 없는 것)로 남은 행사 Feature는 이번 snapshot이 비지
    않았을 때만 retired로 내린다 — 같은 행사는 이번 적재가 묶은 Feature로 다시 선다. 창 밖으로
    지난 회차만 있던 옛 행사는 대체 없이 내려간다(지난 행사다). 빈 snapshot은 아무것도 내리지
    않는다(받기 실패를 "행사 없음"으로 읽지 않는다).
    """
    records = await _record_list(context, "krheritage_events")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        heritage_events_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
        address_geocoder=_address_geocoder(context),
        venue_resolver=_venue_resolver(context),
    )
    legacy = (
        {
            entity_id
            for entity_id in await _current_source_entity_ids(
                context, KRHERITAGE_PROVIDER_NAME, KRHERITAGE_EVENT_DATASET_KEY
            )
            if is_legacy_heritage_event_key(entity_id)
        }
        if bundles
        else set()
    )
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    retired = 0

    async def _load_and_retire_legacy(
        snapshot_bundles: Sequence[Any],
        geo: GeoLoadContext | None,
    ) -> FeatureLoadResult:
        nonlocal retired
        load, retired = await client.load_authoritative_feature_snapshot(
            snapshot_bundles,
            provider=KRHERITAGE_PROVIDER_NAME,
            dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
            source_entity_type=KRHERITAGE_EVENT_ENTITY_TYPE,
            retired_source_entity_ids=legacy,
            geo=geo,
        )
        return load

    result = await _load(
        context,
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        load_all=_load_and_retire_legacy,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )
    if retired:
        context.log.info("국가유산 행사 회차별 옛 Feature %d건 retired 전이", retired)
    return result


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
        # 원천 좌표가 없는 행(2026-11-09 숙박·민박 영업중 4,170행)의 점 보강 — 같은 geo client.
        address_geocoder=_address_geocoder(context),
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


async def _resolve_knps_national_park_anchors(
    records: Sequence[Any],
    *,
    dataset_key: str,
    live: ReverseGeocoder | None,
) -> dict[str, Any]:
    """국립공원 대표점(해상 공원은 면 위 후보점)을 변환 **밖**에서 푼다.

    변환 안에서 후보를 돌면 ADR-116 재사용 pass 0이 행 좌표 밖을 물어 dataset 전체의 재사용이
    꺼진다. 여기서 고른 점을 변환에 넘기면 변환은 행마다 그 점 하나(= 행 좌표)만 재사용 경로로
    묻는다. 이 사전 조회는 변환이 아니라 국립공원 행(23)의 후보점 탐색이라 재사용 helper를 거치지
    않는다(``tests/lint/test_reverse_geocoding_assets_reuse_stored_geo.py`` 허용 목록).
    """
    if live is None:
        return {}
    return await knps_national_park_anchors(
        records, dataset_key=dataset_key, reverse_geocoder=live
    )


async def run_feature_geometry_knps_records(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """KNPS route/area geometry record를 Feature로 적재한다."""
    dataset_key = str(
        await _resource_value(context, "knps_geometry_dataset_key", default="knps_trails")
    )
    if dataset_key not in KNPS_GEOMETRY_DATASETS:
        raise KeyError(f"KNPS geometry dataset_key가 아님: {dataset_key!r}")
    spec = KNPS_GEOMETRY_DATASETS[dataset_key]
    if spec.unloaded_reason is not None:
        # 싣지 않기로 한 dataset(#1450) — 원천을 받지도 않는다. 0건 성공으로 끝내야
        # 누가 갱신 요청을 넣어도 빨간 run이 쌓이지 않는다.
        context.log.warning("KNPS %s는 적재하지 않는다: %s", dataset_key, spec.unloaded_reason)
        records: list[Any] = []
    else:
        records = await _record_list(context, "knps_geometry_records")
    fetched_at = await _fetched_at(context)
    if dataset_key == "knps_trails":
        # 탐방로는 구간이 아니라 원천 탐방 코스 단위로 싣는다(ADR-128).
        course_bundles = await _transform_reusing_geo(
            context,
            knps_trail_courses_to_bundles,
            records,
            fetched_at=fetched_at,
            reverse_geocoder=_reverse_geocoder(context),
        )
        covered = _covered_course_segments(
            context,
            provider=KNPS_PROVIDER_NAME,
            dataset_key=dataset_key,
            course_bundles=course_bundles,
            source_segment_count=len(records),
        )
        course_result = await _load(
            context,
            provider=KNPS_PROVIDER_NAME,
            dataset_key=dataset_key,
            bundles=course_bundles,
            authoritative_snapshot_complete=True,
            source_entity_type=KNPS_TRAIL_COURSE_ENTITY_TYPE,
            retire_absent_from_snapshot=True,
            superseded=SupersededSourceEntities(
                source_entity_type=KNPS_TRAIL_SEGMENT_ENTITY_TYPE,
                source_entity_ids=frozenset(covered),
            ),
            record_sync_state=False,
            geo_applied=GeoApplied(reverse=True, geocode=False),
            address_failure_mode=spec.address_failure_mode,
        )
        return await _record_course_sync(
            context,
            provider=KNPS_PROVIDER_NAME,
            dataset_key=dataset_key,
            covered=covered,
            source_segment_count=len(records),
            course_count=len(course_bundles),
            result=course_result,
        )
    reverse_geocoder = _reverse_geocoder(context)
    # 후보점 사전 조회 — 변환이 아니다(아래 helper docstring). 키워드 이름이 다른 것은 의도다.
    anchors = await _resolve_knps_national_park_anchors(
        records, dataset_key=dataset_key, live=reverse_geocoder
    )
    bundles = await _transform_reusing_geo(
        context,
        knps_geometry_records_to_bundles,
        records,
        dataset_key=dataset_key,
        fetched_at=fetched_at,
        reverse_geocoder=reverse_geocoder,
        national_park_anchors=anchors,
    )
    retires_absent = knps_geometry_snapshot_retires_absent(spec)
    if retires_absent and spec.unloaded_reason is None and not bundles:
        # 싣는 area dataset의 빈 snapshot은 "원천이 비었다"가 아니라 "변환이 무너졌다"일 수 있다
        # (헤더 변경·이름 디코딩 회귀·SHP 0건). 은퇴 전에 멈춘다 — 빈 snapshot 은퇴는
        # unloaded dataset(버퍼 은퇴)에만 허용한다(적대 리뷰 F3).
        raise Failure(
            description=(
                f"KNPS {dataset_key}: 원천 {len(records)}행에서 bundle 0건 — 빈 snapshot으로 "
                "기존 면을 은퇴시키지 않는다. 원천 헤더·디코딩·변환을 확인할 것."
            ),
            metadata={"source_records": len(records)},
        )
    return await _load(
        context,
        provider=KNPS_PROVIDER_NAME,
        dataset_key=dataset_key,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        source_entity_type=KNPS_SOURCE_ENTITY_TYPE if retires_absent else None,
        retire_absent_from_snapshot=retires_absent,
        geo_applied=GeoApplied(reverse=True, geocode=False),
        address_failure_mode=spec.address_failure_mode,
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
    """산림청 등산로 SHP를 등산 코스 route로 적재한다(C05A → ADR-128).

    원천 행은 코스가 아니라 구간(중앙값 233 m)이다. 구간을 코스로 묶어 적재하고, 예전에
    구간 그대로 실었던 Feature는 코스가 대신하므로 은퇴시킨다(원문은 코스 계보에 남는다).
    """
    records = await _record_list(context, "krforest_mountain_trails")
    fetched_at = await _fetched_at(context)
    bundles = await _transform_reusing_geo(
        context,
        mountain_trail_courses_to_bundles,
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    covered = _covered_course_segments(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_MOUNTAIN_TRAILS_DATASET_KEY,
        course_bundles=bundles,
        source_segment_count=len(records),
    )
    result = await _load(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_MOUNTAIN_TRAILS_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        source_entity_type=MOUNTAIN_TRAIL_COURSE_ENTITY_TYPE,
        retire_absent_from_snapshot=True,
        superseded=SupersededSourceEntities(
            source_entity_type=MOUNTAIN_TRAIL_SEGMENT_ENTITY_TYPE,
            source_entity_ids=frozenset(covered),
        ),
        record_sync_state=False,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )
    return await _record_course_sync(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_MOUNTAIN_TRAILS_DATASET_KEY,
        covered=covered,
        source_segment_count=len(records),
        course_count=len(bundles),
        result=result,
    )


COURSE_SEGMENT_COVERAGE_MIN: Final[float] = 0.5
"""코스가 덮은 원천 구간 비율의 하한. 이보다 낮으면 원천 모양이 바뀐 것으로 보고 멈춘다."""


def _course_segment_ids(bundles: Sequence[Any]) -> set[str]:
    """코스 bundle들이 계보로 가진 원천 구간 id(``payload.segment_source_ids``)의 합집합."""
    covered: set[str] = set()
    for bundle in bundles:
        detail = getattr(bundle.feature, "detail", None)
        payload = getattr(detail, "payload", None)
        if isinstance(payload, dict):
            covered.update(str(value) for value in payload.get("segment_source_ids", ()))
    return covered


def _covered_course_segments(
    context: AssetExecutionContext,
    *,
    provider: str,
    dataset_key: str,
    course_bundles: Sequence[Any],
    source_segment_count: int,
) -> set[str]:
    """코스가 덮은 원천 구간 id. 덮은 비율이 하한 미만이면 적재 전에 멈춘다(ADR-128).

    은퇴 대상은 **이 집합만**이다 — 코스가 만들어지지 않은 구간(산 코드·코스명 없음, geometry
    결함 구간뿐인 묶음)은 손대지 않아 원천 일부가 바뀌어도 지도에서 길이 통째로 사라지지 않는다.
    """
    covered = _course_segment_ids(course_bundles)
    if source_segment_count and len(covered) < COURSE_SEGMENT_COVERAGE_MIN * source_segment_count:
        raise Failure(
            description=(
                f"{provider}/{dataset_key}: 코스가 원천 구간 {source_segment_count}건 중 "
                f"{len(covered)}건만 덮었다 — 원천 모양이 바뀌었는지 확인할 것(적재하지 않음)."
            )
        )
    context.log.info(
        "%s/%s: 코스 %d건이 원천 구간 %d건 중 %d건을 덮는다",
        provider,
        dataset_key,
        len(course_bundles),
        source_segment_count,
        len(covered),
    )
    return covered


async def _record_course_sync(
    context: AssetExecutionContext,
    *,
    provider: str,
    dataset_key: str,
    covered: set[str],
    source_segment_count: int,
    course_count: int,
    result: DagsterFeatureLoadResult,
) -> DagsterFeatureLoadResult:
    """코스 적재의 sync 성공을 코스 계수와 함께 기록한다(ADR-128).

    코스가 덮은 구간 route의 은퇴는 코스 적재와 **같은 transaction**에서 seal 전에 끝났다
    (``_load(superseded=...)`` → ``load_authoritative_feature_snapshot``). 예전에는 은퇴를 별도
    transaction으로 돌려, 적재 transaction이 잡은 seal 기대값(은퇴 전)이 child 완료 seal(은퇴
    후)과 어긋나 은퇴가 있는 첫 run마다 ``provider load input changed before child
    completion``으로 실패했다. 이제 결과의 seal 값이 은퇴까지 반영한 최종 상태다.
    """
    retired = result.load.superseded_retired
    context.log.info(
        "%s/%s: 코스 %d건 적재와 같은 transaction에서 구간 route %d건 은퇴",
        provider,
        dataset_key,
        course_count,
        retired,
    )
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    await _record_feature_sync_success(
        context,
        client,
        provider=provider,
        dataset_key=dataset_key,
        cursor_extra={
            **_feature_result_cursor_extra(result),
            "course_segments_covered": len(covered),
            "course_segments_source": source_segment_count,
            "segment_routes_retired": retired,
        },
        observation_receipt=result.observation_receipt,
    )
    return result


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
    # batch마다 새로 만들지 않는다 — 같은 주소를 다시 묻지 않게 run 동안 한 캐시(#1459 §4).
    address_geocoder = _address_geocoder(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "standard_parking_lots", batch_size=100):
            yield apply_replay_provenance(
                source,
                await _transform_reusing_geo(
                    context,
                    parking_lots_to_bundles,
                    records,
                    fetched_at=fetched_at,
                    reverse_geocoder=_reverse_geocoder(context),
                    address_geocoder=address_geocoder,
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


def _refuse_empty_conversion(
    bundles: Sequence[Any], records: Sequence[Any], *, replay: bool, label: str
) -> None:
    """원천 행은 있는데 변환 결과가 0건이면 은퇴 적재 전에 멈춘다(적대 리뷰 A2).

    값 수준 회귀(이름·주소 열이 전부 빈 값)는 header 검산에 걸리지 않는다. 그 snapshot을
    ``retire_absent_from_snapshot``으로 적재하면 기존 장소가 전부 내려간다.
    """
    if records and not bundles and not replay:
        raise Failure(
            description=(
                f"{label}: 원천 {len(records)}행이 변환 뒤 0건이다 — 전부 은퇴시키지 않도록 "
                "적재를 멈춘다(원천 컬럼 값을 확인할 것)."
            )
        )


async def run_feature_place_standard_special_streets(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국지역특화거리표준데이터(공개 파일) record를 place anchor Feature로 적재한다.

    원천은 포털 공개 파일 전량(274행 안팎)이다 — provider가 선언 건수·페이지 길이·전후
    메타데이터를 검산한 snapshot만 내주므로 ``retire_absent_from_snapshot``으로 적재한다.
    0행은 "없음"이 아니라 "못 받았음"이라 은퇴 전에 실패시킨다. replay는 은퇴·봉인·sync 성공
    기록을 하지 않는다(전통시장과 같다).
    """
    source = await _resource_value(context, "standard_special_streets")
    await prefetch_replay(source)
    replay = is_replay(source)
    fetched_at = await _fetched_at(context)
    records = await _record_list(context, "standard_special_streets")
    if not records and not replay:
        raise Failure(
            description=(
                "전국지역특화거리표준데이터 snapshot이 0행이다 — 기존 거리를 전부 은퇴시키지 "
                "않도록 적재를 멈춘다(포털 공개 파일 상태를 확인할 것)."
            )
        )
    bundles = apply_replay_provenance(
        source,
        await _transform_reusing_geo(
            context,
            special_streets_to_bundles,
            records,
            fetched_at=fetched_at,
            reverse_geocoder=_reverse_geocoder(context),
            address_geocoder=_address_geocoder(context),
        ),
    )
    ensure_replay_complete(source)
    _refuse_empty_conversion(bundles, records, replay=replay, label="전국지역특화거리표준데이터")
    return await _load(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_SPECIAL_STREETS,
        bundles=bundles,
        authoritative_snapshot_complete=not replay,
        source_entity_type="special_street",
        retire_absent_from_snapshot=not replay,
        record_sync_state=not replay,
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


async def run_feature_place_standard_traditional_markets(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국전통시장표준데이터 record를 전통시장 place Feature로 적재한다(#1459).

    원천은 포털 공개 파일 전량(1,393행, 서비스키 불필요)이다. snapshot을 한 번에 받아
    ``retire_absent_from_snapshot``으로 적재한다 — 다음 적재에 없는 시장은 은퇴한다
    (krforest와 같은 경로). 0행 snapshot은 "없음"이 아니라 "못 받았음"이므로 은퇴 전에
    실패시킨다. replay는 원천을 관측하지 않은 run이라 은퇴·봉인·sync 성공 기록을 하지 않는다.
    """
    source = await _resource_value(context, "standard_traditional_markets")
    await prefetch_replay(source)
    replay = is_replay(source)
    fetched_at = await _fetched_at(context)
    records = await _record_list(context, "standard_traditional_markets")
    if not records and not replay:
        raise Failure(
            description=(
                "전국전통시장표준데이터 snapshot이 0행이다 — 기존 시장을 전부 은퇴시키지 않도록 "
                "적재를 멈춘다(포털 공개 파일 상태를 확인할 것)."
            )
        )
    bundles = apply_replay_provenance(
        source,
        await _transform_reusing_geo(
            context,
            traditional_markets_to_bundles,
            records,
            fetched_at=fetched_at,
            reverse_geocoder=_reverse_geocoder(context),
            address_geocoder=_address_geocoder(context),
        ),
    )
    ensure_replay_complete(source)
    _refuse_empty_conversion(bundles, records, replay=replay, label="전국전통시장표준데이터")
    return await _load(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_TRADITIONAL_MARKETS,
        bundles=bundles,
        authoritative_snapshot_complete=not replay,
        source_entity_type="traditional_market",
        retire_absent_from_snapshot=not replay,
        record_sync_state=not replay,
        geo_applied=GeoApplied(reverse=True, geocode=False),
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_traditional_markets"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_standard_traditional_markets(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_place_standard_traditional_markets
    )


#: TourAPI ``detailCommon2``의 하루 상한 기본값 — data.go.kr 한도는 **오퍼레이션마다** 걸리고 이
#: 오퍼레이션의 일일 한도는 개발계정 1,000이다(``docs/etl/upstream-quota.md``). 관광지(매일)와
#: 축제(매일) 두 dataset이 같은 오퍼레이션을 쓰므로 두 run 예산의 합이 이 값 아래여야 한다(테스트가
#: 고정한다).
#: 100은 수동 실행·재현 조회 몫으로 남긴다. 운영 값은 settings
#: ``visitkorea_detail_common_daily_budget``(env)이 덮는다 — 운영계정 증설 뒤 설정만 바꾼다.
VISITKOREA_DETAIL_DAILY_BUDGET: Final = 900

#: 관광지 run 예산 기본값(2026-11-27 600 → 850). 첫 적재는 상세 없이 전량이 들어가고, 상세는 run마다
#: 이만큼씩 채워진다(12·14·28 18,894건 ≈ 22 run). **step 재시도는 상세를 받지 않는다** — 받은 상세는
#: 적재가 커밋돼야 남으므로, 재시도마다 받으면 한 run이 한도를 넘긴다. env
#: ``visitkorea_detail_common_attraction_budget``이 덮는다.
VISITKOREA_ATTRACTION_DETAIL_BUDGET: Final = 850

#: 축제 run 예산 기본값(2026-11-27 300 → 50). 창 안 축제(실측 879)의 상세는 이미 찼고 하루 새·수정
#: 건은 4~6건이라 50이면 넉넉하다. env ``visitkorea_detail_common_festival_budget``이 덮는다.
VISITKOREA_FESTIVAL_DETAIL_BUDGET: Final = 50

#: 상세 op(ADR-126) 하루 상한 기본값 — op마다 개발계정 1,000 − 수동 조회 100.
TOURAPI_DETAIL_OP_DEFAULT_DAILY_BUDGET: Final = 900

#: Dagster instance KV 장부 key 머리 — ``<머리>/<op>/<KST 날짜>`` → 그날 쓴(예약한) 호출 수.
_DETAIL_LEDGER_PREFIX: Final = "kor_travel_map/tourapi_detail_calls"

#: 축제의 법정동 미해석 허용 상한 — 축제는 900건 안팎이고 원천 좌표가 모두 육지 행사장이라
#: 관광지(30)보다 좁게 둔다. 버린 행은 은퇴하지 않지만(snapshot 부재 은퇴에서 빠진다) 갱신도 못
#: 받으므로, geo 장애가 한 run에 축제 수십 건을 낡은 채로 두지 않게 한다.
VISITKOREA_FESTIVAL_UNRESOLVED_FLOOR: Final = 5

#: 역지오코딩이 법정동을 못 낸 행의 허용 상한 — ``max(이 수, 전체의 1%)``. 해상 등대·무인도처럼
#: 늘 비는 행만 버리고(주소 검증 ``drop``), 그보다 많으면 geo 장애로 보고 은퇴 적재 전에 멈춘다.
#: drop된 행은 snapshot에서 빠져 **은퇴**하기 때문이다.
VISITKOREA_ATTRACTION_UNRESOLVED_FLOOR: Final = 30


def _setting_or(value: int | None, default: int) -> int:
    return default if value is None else value


def _detail_common_run_budget(settings: KorTravelMapSettings, dataset_key: str) -> int:
    """``detailCommon2`` run 예산 — 설정값(env)이 있으면 그것, 없으면 모듈 기본값."""
    if dataset_key == DATASET_KEY_VISITKOREA_FESTIVALS:
        return _setting_or(
            settings.visitkorea_detail_common_festival_budget, VISITKOREA_FESTIVAL_DETAIL_BUDGET
        )
    return _setting_or(
        settings.visitkorea_detail_common_attraction_budget, VISITKOREA_ATTRACTION_DETAIL_BUDGET
    )


class _DetailCallLedger:
    """TourAPI 상세 오퍼레이션의 KST 날짜별 호출 장부(Dagster instance KV, ADR-126).

    run 예산만으로는 하루 한도를 지킬 수 없다 — 큐 runner·실패 재실행·수동 launch가 같은 날 다시
    돌고, 받은 상세는 적재가 커밋돼야 남아서 실패한 run의 호출도 한도를 쓴다. 그래서 호출 **전에**
    그날 장부에 예약한다(실패해도 센다 — 보수적). 동시에 두 run이 돌면 예약이 겹칠 수 있다
    (관광지 job은 하루 한 번 schedule이라 드물다) — 그때도 원천 한도 응답(``rate_limit``)에서
    그 op만 멈춘다.
    """

    def __init__(self, storage: Any, day: str) -> None:
        self._storage = storage
        self._day = day

    @classmethod
    def of(cls, context: AssetExecutionContext) -> "_DetailCallLedger | None":
        storage = getattr(getattr(context, "instance", None), "run_storage", None)
        get = getattr(storage, "kvs_get", None)
        put = getattr(storage, "kvs_set", None)
        if not (callable(get) and callable(put)):
            return None
        return cls(storage, datetime.now(_KST).date().isoformat())

    def _key(self, op: str) -> str:
        return f"{_DETAIL_LEDGER_PREFIX}/{op}/{self._day}"

    def used(self, op: str) -> int:
        raw = self._storage.kvs_get({self._key(op)}).get(self._key(op))
        try:
            return max(int(raw), 0) if raw is not None else 0
        except (TypeError, ValueError):
            return 0

    def remaining(self, op: str, daily: int, run_budget: int) -> int:
        return max(min(run_budget, daily - self.used(op)), 0)

    def reserve(self, op: str, count: int) -> None:
        self._storage.kvs_set({self._key(op): str(self.used(op) + count)})


async def _read_stored_raw(
    context: AssetExecutionContext, dataset_key: str
) -> dict[str, Mapping[str, Any]]:
    """dataset current 원본(``raw_data``) — 상세 이어 쓰기의 근거. 못 읽으면 멈춘다(fail-closed).

    빈 저장값으로 계속하면 저장 상세가 전부 빠진 bundle이 적재돼 소개·방문 안내가 지워진다.
    """
    client = _resource_object(context, "kor_travel_map_client", default=None)
    read = getattr(client, "read_current_source_records", None)
    if not callable(read):
        raise Failure(
            description=(
                f"{dataset_key}: current 원본을 읽을 수 없다(client에 read_current_source_records "
                "없음) — 저장 상세를 잃지 않도록 적재를 멈춘다."
            )
        )
    current, _expected = await read(provider=VISITKOREA_PROVIDER_NAME, dataset_key=dataset_key)
    return {record.source_entity_id: record.raw_data for record in current}


def _retry_number(context: AssetExecutionContext) -> int:
    try:
        return int(context.retry_number)
    except Exception:  # noqa: BLE001 — 큐 runner 대역 등 retry_number가 없는 context
        return 0


async def _attach_attraction_details(
    context: AssetExecutionContext,
    records: Sequence[Any],
    *,
    dataset_key: str = DATASET_KEY_VISITKOREA_ATTRACTIONS,
    budget: int | None = None,
    label: str = "TourAPI 관광지",
    stored: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Any]:
    """저장 상세를 이어 쓰고, 예산 안에서 새·수정 항목의 상세를 받아 record에 얹는다.

    관광지와 축제가 같은 규칙을 쓴다(``dataset_key``·``budget``만 다르다).

    저장값은 dataset의 current 원본(``raw_data``)이다 — 목록 ``modified_time``이 같으면 상세를
    다시 받지 않는다. 상세 받기가 한도·장애로 멈추면 남은 항목은 상세 없이(``None``) 적재되고
    다음 run이 다시 고른다. record는 provider ``TourItem``(frozen pydantic)이라 ``model_copy``로
    얹는다.
    """
    if stored is None:
        stored = await _read_stored_raw(context, dataset_key)
    settings = KorTravelMapSettings()
    # 기본값은 호출 시점의 모듈 값이다(def 시점에 묶으면 예산을 바꾼 테스트·운영 보정이 안 닿는다).
    if budget is None:
        budget = _detail_common_run_budget(settings, dataset_key)
    budget = budget if _retry_number(context) == 0 else 0
    ledger = _DetailCallLedger.of(context)
    daily = _setting_or(
        settings.visitkorea_detail_common_daily_budget, VISITKOREA_DETAIL_DAILY_BUDGET
    )
    if ledger is None:
        # 장부가 없는 실행(큐 runner의 직접 context 등)은 하루 한도를 지킬 수 없다 — 받지 않는다
        # (fail-closed). 상세는 schedule run이 장부 안에서 채운다.
        if budget > 0:
            context.log.warning(f"{label} 상세: 호출 장부(instance KV)가 없어 받지 않는다.")
        budget = 0
    else:
        budget = ledger.remaining("common", daily, budget)
    plan = plan_attraction_details(records, stored, budget=budget)
    if ledger is not None and plan.fetch:
        ledger.reserve("common", len(plan.fetch))
    fetched: Mapping[str, tuple[str, str]] = (
        await fetch_visitkorea_attraction_details(KorTravelMapSettings(), plan.fetch)
        if plan.fetch
        else {}
    )
    context.log.info(
        f"{label} 상세: 재사용 {len(plan.reuse)} · 요청 {len(plan.fetch)} · "
        f"수신 {len(fetched)} · 예산 밖 {plan.deferred} · 예산 {budget}"
    )
    attached: list[Any] = []
    for record in records:
        content_id = str(getattr(record, "content_id", "") or "").strip()
        pair = fetched.get(content_id) or plan.reuse.get(content_id)
        if pair is None:
            attached.append(record)
        else:
            attached.append(
                record.model_copy(update={"overview": pair[0], "homepage": pair[1]})
            )
    return attached


def tourapi_detail_op_budgets(settings: KorTravelMapSettings) -> dict[TourApiDetailOp, int]:
    """op별 하루 상한(설정값, 없으면 :data:`TOURAPI_DETAIL_OP_DEFAULT_DAILY_BUDGET`, ADR-126).

    네 op은 축제 적재가 쓰지 않으므로(축제는 ``detailCommon2``뿐) 관광지 run이 전부 쓴다. 실제 run
    예산은 그날 장부의 남은 몫으로 더 줄어든다(:class:`_DetailCallLedger`).
    """
    default = TOURAPI_DETAIL_OP_DEFAULT_DAILY_BUDGET
    return {
        "intro": _setting_or(settings.visitkorea_detail_intro_daily_budget, default),
        "images": _setting_or(settings.visitkorea_detail_image_daily_budget, default),
        "pet": _setting_or(settings.visitkorea_detail_pet_daily_budget, default),
        "accessibility": _setting_or(
            settings.visitkorea_detail_accessibility_daily_budget, default
        ),
    }


#: 무장애·반려동물은 그 서비스에 실린 관광지만 묻는다 — 1만 9천 건을 다 물으면 대부분 빈 답이다.
_MEMBER_SERVICE_BY_OP: Final[dict[TourApiDetailOp, str]] = {
    "accessibility": "with",
    "pet": "pet",
}


async def _tourapi_detail_ops(
    context: AssetExecutionContext,
    records: Sequence[Any],
    *,
    replay: bool,
    stored: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """관광지 상세 op 묶음(contentid → op 묶음) — 저장값을 잇고 예산 안에서 새로 받는다.

    - replay와 step 재시도는 받지 않는다(예산 0) — 저장값만 이어 쓴다.
    - 하루 상한은 KST 날짜별 장부로 run을 넘어 지킨다(:class:`_DetailCallLedger`). 장부가 없으면
      (instance KV 없음 — 큐 runner의 직접 context) 받지 않는다(fail-closed).
    - 무장애·반려동물은 그 서비스 목록에 있는 contentid만 묻는다. 목록을 못 받으면 그 op은
      이번 run에 받지 않는다(서비스 활용신청이 없으면 목록부터 실패한다).
    - 우선순위 점수는 client가 읽는다(큐레이션 포함 + 검색 인지도). 못 읽으면 우선순위 없이
      관광타입·contentid 순이다.
    """
    if stored is None:
        stored = await _read_stored_raw(context, DATASET_KEY_VISITKOREA_ATTRACTIONS)
    client = _resource_object(context, "kor_travel_map_client", default=None)
    settings = KorTravelMapSettings()
    daily = tourapi_detail_op_budgets(settings)
    budgets: dict[TourApiDetailOp, int] = dict(daily)
    if replay or _retry_number(context) != 0:
        budgets = dict.fromkeys(TOURAPI_DETAIL_OPS, 0)
    ledger = _DetailCallLedger.of(context) if any(budgets.values()) else None
    if ledger is not None:
        budgets = {op: ledger.remaining(op, daily[op], budgets[op]) for op in TOURAPI_DETAIL_OPS}
    elif any(budgets.values()):
        # 큐 runner의 직접 context 등 — 하루 한도를 지킬 수 없으니 받지 않는다(fail-closed).
        context.log.warning("TourAPI 상세 장부(instance KV)가 없어 상세 op을 받지 않는다.")
        budgets = dict.fromkeys(TOURAPI_DETAIL_OPS, 0)
    members: dict[TourApiDetailOp, frozenset[str]] = {}
    for op, service in _MEMBER_SERVICE_BY_OP.items():
        if budgets[op] <= 0:
            continue
        listed = await fetch_visitkorea_service_members(settings, service)
        if listed is None:
            context.log.warning(
                f"TourAPI {service} 목록을 못 받았다 — 이번 run은 {op}를 받지 않는다."
            )
            budgets[op] = 0
        else:
            members[op] = listed
    priority: Mapping[str, int] = {}
    read_priority = getattr(client, "read_detail_priority_scores", None)
    if any(budgets.values()) and callable(read_priority):
        try:
            priority = await read_priority(
                provider=VISITKOREA_PROVIDER_NAME,
                dataset_key=DATASET_KEY_VISITKOREA_ATTRACTIONS,
            )
        except Exception as exc:  # noqa: BLE001 — 우선순위는 보조 신호다. 적재를 막지 않는다.
            context.log.warning(
                f"TourAPI 상세 우선순위를 못 읽었다 — 우선순위 없이 받는다: {exc!r}"
            )
    plan = plan_tourapi_detail_ops(
        records, stored, budgets=budgets, priority=priority, members=members
    )
    if ledger is not None:
        for op in TOURAPI_DETAIL_OPS:
            if plan.fetch[op]:
                ledger.reserve(op, len(plan.fetch[op]))
    fetched: Mapping[TourApiDetailOp, Mapping[str, Any]] = (
        await fetch_visitkorea_detail_ops(settings, plan.fetch)
        if any(plan.fetch.values())
        else {}
    )
    for op in TOURAPI_DETAIL_OPS:
        member_note = f" · 서비스 목록 {len(members[op])}" if op in members else ""
        context.log.info(
            f"TourAPI 상세 {op}: 요청 {len(plan.fetch[op])} · "
            f"수신 {len(fetched.get(op, {}))} · 예산 밖 {plan.deferred[op]} · "
            f"예산 {budgets[op]}/{daily[op]}{member_note}"
        )
    modified_times = {
        str(getattr(record, "content_id", "") or "").strip(): _iso_or_none(
            getattr(record, "modified_time", None)
        )
        for record in records
    }
    return merge_tourapi_detail_ops(plan, fetched, modified_times)


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _ensure_geo_resolved_enough(
    bundles: Sequence[Any],
    *,
    label: str = "TourAPI 관광지",
    floor: int | None = None,
) -> None:
    """좌표가 있는데 법정동이 비는 행이 상한을 넘으면 은퇴 적재 전에 멈춘다(geo 장애 방어)."""
    unresolved = sum(
        1
        for bundle in bundles
        if bundle.feature.coord is not None and bundle.feature.address.bjd_code is None
    )
    floor = VISITKOREA_ATTRACTION_UNRESOLVED_FLOOR if floor is None else floor
    limit = max(floor, len(bundles) // 100)
    if unresolved > limit:
        raise Failure(
            description=(
                f"{label} {len(bundles)}건 중 {unresolved}건이 법정동을 못 받았다"
                f"(상한 {limit}) — geo 장애로 보고 은퇴 적재를 멈춘다."
            )
        )


async def run_feature_place_visitkorea_tourist_attractions(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """TourAPI 관광지(12)·문화시설(14)·레포츠(28) 목록을 place Feature로 적재한다(#1459).

    전국 1만 9천여 건을 한 snapshot으로 받아 ``retire_absent_from_snapshot``으로 적재한다 —
    목록에서 빠진 관광지는 은퇴한다. 0행 목록은 "없음"이 아니라 "못 받았음"이라 은퇴 전에
    실패시킨다. 상세(overview·homepage)는 :func:`_attach_attraction_details`가 예산 안에서 얹는다.
    replay는 저장 원본(상세 포함)을 그대로 쓰고 은퇴·봉인·sync 성공을 기록하지 않는다.
    """
    source = await _resource_value(context, "visitkorea_tourist_attractions")
    await prefetch_replay(source)
    replay = is_replay(source)
    fetched_at = await _fetched_at(context)
    records = await _record_list(context, "visitkorea_tourist_attractions")
    if not records and not replay:
        raise Failure(
            description=(
                "TourAPI 관광지 목록이 0행이다 — 기존 관광지를 전부 은퇴시키지 않도록 적재를 "
                "멈춘다(서비스키 활용신청·원천 상태를 확인할 것)."
            )
        )
    # current 원본은 한 번만 읽어 overview 상세와 상세 op이 같이 쓴다(1만 9천 행).
    stored = await _read_stored_raw(context, DATASET_KEY_VISITKOREA_ATTRACTIONS)
    if not replay:
        records = await _attach_attraction_details(context, records, stored=stored)
    details = await _tourapi_detail_ops(context, records, replay=replay, stored=stored)
    bundles = apply_replay_provenance(
        source,
        await _transform_reusing_geo(
            context,
            tourapi_attractions_to_bundles,
            records,
            fetched_at=fetched_at,
            reverse_geocoder=_reverse_geocoder(context),
            details=details,
        ),
    )
    ensure_replay_complete(source)
    if not replay:  # replay는 은퇴시키지 않는다
        _ensure_geo_resolved_enough(bundles)
    return await _load(
        context,
        provider=VISITKOREA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_VISITKOREA_ATTRACTIONS,
        bundles=bundles,
        authoritative_snapshot_complete=not replay,
        source_entity_type="tourist_attraction",
        retire_absent_from_snapshot=not replay,
        record_sync_state=not replay,
        geo_applied=GeoApplied(reverse=True, geocode=False),
        # 1만 9천 건 중 역지오코딩이 법정동을 못 내는 행(해상 등대·무인도 등)이 하나만 있어도
        # strict는 run 전체를 되감는다. 그 행만 버리고 기록한다(#1450과 같은 선택). 버린 행은
        # 은퇴하므로 그 수는 위 `_ensure_geo_resolved_enough`가 먼저 묶는다.
        address_failure_mode="drop",
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"visitkorea_tourist_attractions"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_visitkorea_tourist_attractions(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_place_visitkorea_tourist_attractions
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
    required_resource_keys=_COMMON_RESOURCE_KEYS
    | {"transport_airports"},
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


async def run_feature_event_visitkorea_festivals(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """TourAPI 축제·공연·행사(``searchFestival2``)를 1차 event Feature로 적재한다.

    2026-11-10 소유자 결정으로 표준데이터 축제를 쓰지 않는다 — 이것이 유일한 축제 원천이다
    (``docs/etl/event-feature-etl.md``). 수집 창(한 해 전 그달 1일 이후에 끝나는 행사) 전체를 한
    snapshot으로 받아 ``retire_absent_from_snapshot``으로 적재한다 — 창에서 밀려나거나 원천에서
    빠진 행사는 은퇴한다. 0행 목록은 "못 받았음"이라 은퇴 전에 실패시킨다. 상세(overview·
    homepage)는 :data:`VISITKOREA_FESTIVAL_DETAIL_BUDGET` 안에서 얹는다(관광지와 같은 오퍼레이션
    한도를 나눠 쓴다). replay는 저장 원본(상세 포함)을 그대로 쓰고 은퇴·sync 성공을 기록하지 않는다.
    """
    source = await _resource_value(context, "visitkorea_festivals")
    await prefetch_replay(source)
    replay = is_replay(source)
    fetched_at = await _fetched_at(context)
    records = await _record_list(context, "visitkorea_festivals")
    if not records and not replay:
        raise Failure(
            description=(
                "TourAPI 축제 목록이 0행이다 — 기존 축제를 전부 은퇴시키지 않도록 적재를 멈춘다"
                "(서비스키 활용신청·원천 상태를 확인할 것)."
            )
        )
    if not replay:
        records = await _attach_attraction_details(
            context,
            records,
            dataset_key=DATASET_KEY_VISITKOREA_FESTIVALS,
            label="TourAPI 축제",
        )
    bundles = apply_replay_provenance(
        source,
        await _transform_reusing_geo(
            context,
            tourapi_festivals_to_bundles,
            records,
            fetched_at=fetched_at,
            reverse_geocoder=_reverse_geocoder(context),
        ),
    )
    ensure_replay_complete(source)
    if not replay:  # replay는 은퇴시키지 않는다
        _ensure_geo_resolved_enough(
            bundles, label="TourAPI 축제", floor=VISITKOREA_FESTIVAL_UNRESOLVED_FLOOR
        )
    return await _load(
        context,
        provider=VISITKOREA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_VISITKOREA_FESTIVALS,
        bundles=bundles,
        authoritative_snapshot_complete=not replay,
        source_entity_type=FESTIVAL_SOURCE_ENTITY_TYPE,
        retire_absent_from_snapshot=not replay,
        record_sync_state=not replay,
        geo_applied=GeoApplied(reverse=True, geocode=False),
        # 역지오코딩이 법정동을 못 내는 행 하나가 run 전체를 되감지 않게 그 행만 버린다(관광지와
        # 같은 선택). 버린 행은 은퇴하지 않고 이번 갱신만 빠진다 — 그 수는 위
        # `_ensure_geo_resolved_enough`가 묶는다.
        address_failure_mode="drop",
    )


@asset(
    group_name="features_event",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"visitkorea_festivals"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_event_visitkorea_festivals(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_event_visitkorea_festivals
    )


FEATURE_LOAD_ASSETS: Final = [
    feature_place_transport_fuel_stations,
    feature_place_transport_rest_areas,
    feature_place_transport_rail_stations,
    feature_place_transport_ferry_ports,
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
    feature_place_standard_traditional_markets,
    feature_place_visitkorea_tourist_attractions,
    feature_place_datagokr_file_data,
    feature_place_khoa_beaches,
    feature_place_transport_airports,
    feature_place_kor_travel_concierge_youtube,
    feature_event_visitkorea_festivals,
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


def _effective_address_validation(configured: bool | str, dataset_mode: str) -> bool | str:
    """dataset이 ``drop``을 고르면 운영자 ``strict``만 ``drop``으로 완화한다(#1450).

    ``off``·``drop``은 그대로 둔다 — dataset은 완화만 하고 조이지 않는다. 바다 centroid처럼
    행 단위로 법정동이 없을 수밖에 없는 dataset이 run 전체를 롤백하지 않게 한다. 버린 행은
    drop 경로가 metadata와 ``ops.data_integrity_violations``에 센다(소실 하한도 그대로다).
    """
    if dataset_mode == "drop" and configured in (True, "strict"):
        return "drop"
    return configured


def _dataset_empty_reverse_ratio(dataset_mode: str) -> float | None:
    """drop dataset의 run 빈 답 가드 문턱 — 소실 하한과 같은 값(#1450).

    그 dataset에서 빈 답 행은 곧 버린 행이고 소실 하한(:data:`etl._DATASET_LOSS_DROP_RATIO`)이
    이미 센다. 5% 문턱으로 한 번 더 세면 drop을 골라도 run이 죽는다(실측 450건 중 49건).
    geo 전면 장애는 여전히 잡힌다 — 전 행이 비면 두 가드 모두 넘는다.
    """
    return _DATASET_LOSS_DROP_RATIO if dataset_mode == "drop" else None


async def _load(
    context: AssetExecutionContext,
    *,
    provider: str,
    dataset_key: str,
    bundles: list[Any],
    authoritative_snapshot_complete: bool,
    source_entity_type: str | None = None,
    retire_absent_from_snapshot: bool = False,
    superseded: SupersededSourceEntities | None = None,
    record_sync_state: bool = True,
    load_all: Callable[[Sequence[Any], GeoLoadContext | None], Awaitable[FeatureLoadResult]]
    | None = None,
    geo_applied: GeoApplied,
    address_failure_mode: str = "strict",
) -> DagsterFeatureLoadResult:
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    # bool(True/False) 하위호환 + settings 모드 문자열(strict/drop/off, #376).
    strict_address = _effective_address_validation(
        cast(
            "bool | str",
            await _resource_value(context, "strict_address", default="strict"),
        ),
        address_failure_mode,
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
        superseded=superseded,
        load_all=load_all,
        empty_reverse_ratio=_dataset_empty_reverse_ratio(address_failure_mode),
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


def _address_geocoder(context: AssetExecutionContext) -> AddressGeocoder | None:
    """원천 좌표 결측 fallback(#1459 §4) — ``reverse_geocoder`` resource의 ``geocode_address``.

    같은 kor-travel-geo client·경계 계수를 쓴다(새 resource 키 없음). 첫 호출 전에 run-scoped
    현재 토큰을 읽고(ADR-109 결정 2 — ``_TokenFirstReverseGeocoder``와 같은 순서), 답은 run 동안
    주소 쌍으로 기억한다 — 저장값 재사용(ADR-116)이 변환을 여러 번 돌려도 geo는 주소당 한 번이다.
    resource가 정지오코딩을 모르면(테스트 대역 등) None이다.
    """
    inner = _resource_object(context, "reverse_geocoder", default=None)
    geocode = getattr(inner, "geocode_address", None)
    if not callable(geocode):
        return None
    token_first = _resource_object(context, "kor_travel_geo_dataset", default=None) is not None

    async def _geocode(address: Any) -> Any:
        if token_first:
            await _current_geo_dataset(context)
        return await geocode(address)

    return cached_address_geocoder(cast("AddressGeocoder", _geocode))


def _venue_resolver(context: AssetExecutionContext) -> VenueResolver | None:
    """행사 장소 이름 → 같은 시군구의 좌표 있는 장소 Feature(#1468 D).

    후보는 ``kor_travel_map_client.find_venue_candidates``(이름 trigram 읽기)로 읽고, 고르는
    규칙은 :func:`kortravelmap.core.venue_match.match_venue`다(국가유산 본체 우선). 답은 run 동안
    ``(조각, 시도, 시군구)``로 기억한다. client가 이 읽기를 모르면(테스트 대역 등) None이다.
    """
    client = _resource_object(context, "kor_travel_map_client", default=None)
    find = getattr(client, "find_venue_candidates", None)
    if not callable(find):
        return None

    async def _resolve(piece: str, sido: str | None, gugun: str | None) -> VenueMatch | None:
        candidates = cast(list[VenueCandidate], await find(piece))
        return match_venue(
            piece, sido, gugun, candidates, prefer_dataset_key=KRHERITAGE_DATASET_KEY
        )

    return cached_venue_resolver(_resolve)


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
