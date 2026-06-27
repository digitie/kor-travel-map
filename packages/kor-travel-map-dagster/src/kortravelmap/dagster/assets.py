"""kor-travel-map 소유 provider Feature 적재 Dagster asset."""

import inspect
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Iterable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Final, cast

from kortravelmap.client import FestivalEnrichmentReviewRefreshResult
from kortravelmap.geocoding import ReverseGeocoder
from kortravelmap.infra.feature_repo import AirQualityLoadResult
from kortravelmap.infra.price_repo import PriceFeatureLoadResult
from kortravelmap.providers.airkorea import (
    AIRKOREA_PROVIDER_NAME,
    DATASET_KEY_AIR_QUALITY,
    air_quality_stations_to_bundles,
    air_quality_to_weather_values,
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
    kor_travel_concierge_inactive_entity_ids,
    kor_travel_concierge_items_to_bundles,
)
from kortravelmap.providers.krairport import (
    DATASET_KEY_AIRPORTS,
    KRAIRPORT_PROVIDER_NAME,
    airports_to_bundles,
)
from kortravelmap.providers.krex import (
    KREX_PROVIDER_NAME,
    REST_AREA_DATASET_KEY,
    REST_AREA_PRICES_DATASET_KEY,
    REST_AREA_SOURCE_ENTITY_TYPE,
    REST_AREA_WEATHER_DATASET_KEY,
    TRAFFIC_NOTICES_DATASET_KEY,
    rest_area_fuel_price_records_to_features_and_values,
    rest_area_place_locator_from_rows,
    rest_area_weather_records_to_bundles,
    rest_area_weather_records_to_values,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_ARBORETUMS as KRFOREST_ARBORETUMS_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_RECREATION_FORESTS as KRFOREST_RECREATION_FORESTS_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    KRFOREST_PROVIDER_NAME,
    arboretums_to_bundles,
    recreation_forests_to_bundles,
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
from kortravelmap.providers.mois import (
    license_records_to_bundles,
)
from kortravelmap.providers.opinet import (
    OPINET_PRICE_DATASET_KEY,
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
    station_details_to_price_features_and_values,
    stations_to_bundles,
    stations_to_price_features_and_values,
)
from kortravelmap.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    DATASET_KEY_MUSEUMS,
    DATASET_KEY_PARKING_LOTS,
    DATASET_KEY_TOURIST_ATTRACTIONS,
    STANDARD_DATA_PROVIDER_NAME,
    cultural_festivals_to_bundles,
    museums_to_bundles,
    parking_lots_to_bundles,
    tourist_attractions_to_bundles,
)

from dagster import AssetExecutionContext, Backoff, RetryPolicy, asset

from .etl import (
    DagsterFeatureLoadResult,
    _add_output_metadata,
    load_feature_bundles_for_dagster,
)

if TYPE_CHECKING:
    from kortravelmap.client import AsyncKorTravelMapClient

DATAGOKR_STANDARD_PROVIDER_NAME: Final[str] = "data.go.kr-standard"
"""전국 표준데이터 provider canonical name."""

FEATURE_LOAD_RETRY_POLICY: Final[RetryPolicy] = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=Backoff.EXPONENTIAL,
)
"""provider Feature load asset 공통 retry policy."""

MOIS_RECORD_BATCH_SIZE: Final[int] = 1000
"""MOIS bulk record를 FeatureBundle로 변환하기 전에 끊어 읽는 record batch 크기."""

_KST = timezone(timedelta(hours=9))
_MISSING: Final = object()
_COMMON_RESOURCE_KEYS: Final[set[str]] = {
    "kor_travel_map_client",
    "reverse_geocoder",
    "fetched_at",
    "strict_address",
}


async def run_feature_event_datagokr_cultural_festivals(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국문화축제표준데이터 record를 event Feature로 적재한다."""
    records = await _record_list(context, "datagokr_cultural_festivals")
    fetched_at = await _fetched_at(context)
    bundles = await cultural_festivals_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=DATAGOKR_STANDARD_PROVIDER_NAME,
        dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
        bundles=bundles,
    )


@asset(
    group_name="features_event",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"datagokr_cultural_festivals"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_event_datagokr_cultural_festivals(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_event_datagokr_cultural_festivals(context)


async def run_feature_place_opinet_stations(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """OpiNet 주유소 record를 place Feature로 적재한다."""
    records = await _record_list(context, "opinet_stations")
    fetched_at = await _fetched_at(context)
    bundles = await stations_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=OPINET_PROVIDER_NAME,
        dataset_key=OPINET_STATION_DATASET_KEY,
        bundles=bundles,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"opinet_stations"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_opinet_stations(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_opinet_stations(context)


async def run_feature_price_opinet_stations(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    """OpiNet 주유소 상세 가격을 price Feature + PriceValue로 적재한다."""
    records = await _record_list(context, "opinet_station_price_details")
    fetched_at = await _fetched_at(context)
    reverse_geocoder = _reverse_geocoder(context)
    if any(hasattr(record, "prices") for record in records):
        bundles, values = await station_details_to_price_features_and_values(
            records,
            fetched_at=fetched_at,
            reverse_geocoder=reverse_geocoder,
        )
    else:
        bundles, values = await stations_to_price_features_and_values(
            records,
            fetched_at=fetched_at,
            reverse_geocoder=reverse_geocoder,
        )
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    result = await client.load_price_features(bundles, values)
    _add_output_metadata(
        context,
        {
            "provider": OPINET_PROVIDER_NAME,
            "dataset_key": OPINET_PRICE_DATASET_KEY,
            **result.as_metadata(),
        },
    )
    await _record_feature_sync_success(
        context,
        client,
        provider=OPINET_PROVIDER_NAME,
        dataset_key=OPINET_PRICE_DATASET_KEY,
        cursor_extra=result.as_metadata(),
    )
    return result


@asset(
    group_name="features_price",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"opinet_station_price_details"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_price_opinet_stations(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    return await run_feature_price_opinet_stations(context)


async def run_feature_place_krex_rest_areas(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """KREX 휴게소 record를 place Feature로 적재한다."""
    records = await _record_list(context, "krex_rest_areas")
    fetched_at = await _fetched_at(context)
    bundles = await rest_areas_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_DATASET_KEY,
        bundles=bundles,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krex_rest_areas"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_krex_rest_areas(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_krex_rest_areas(context)


async def run_feature_price_krex_rest_areas(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    """KREX 휴게소 유가 snapshot을 price Feature + PriceValue로 적재한다.

    #547 — ``restarea.fuel_prices`` row에는 lon/lat가 없어 유가 feature가
    coord=None이면 지도/bbox 쿼리에서 누락된다. 이미 적재된 휴게소 place feature의
    자연키→좌표 locator를 조회해 유가 feature가 place 좌표·``parent_feature_id``를
    상속하게 한다(geocoding 미경유 — 좌표 출처는 place feature). place가 아직
    없으면(첫 실행 등) locator가 비어 유가는 coordless로 적재되고, 후속 실행에서
    place가 적재된 뒤 좌표가 회복된다.
    """
    records = await _record_list(context, "krex_rest_area_fuel_prices")
    fetched_at = await _fetched_at(context)
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    locator_rows = await client.list_primary_place_locator(
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_DATASET_KEY,
        source_entity_type=REST_AREA_SOURCE_ENTITY_TYPE,
    )
    place_locator = rest_area_place_locator_from_rows(locator_rows)
    bundles, values = rest_area_fuel_price_records_to_features_and_values(
        records,
        fetched_at=fetched_at,
        place_locator=place_locator,
    )
    result = await client.load_price_features(bundles, values)
    _add_output_metadata(
        context,
        {
            "provider": KREX_PROVIDER_NAME,
            "dataset_key": REST_AREA_PRICES_DATASET_KEY,
            **result.as_metadata(),
        },
    )
    await _record_feature_sync_success(
        context,
        client,
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_PRICES_DATASET_KEY,
        cursor_extra=result.as_metadata(),
    )
    return result


@asset(
    group_name="features_price",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krex_rest_area_fuel_prices"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_price_krex_rest_areas(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    return await run_feature_price_krex_rest_areas(context)


async def run_feature_notice_krex_traffic_notices(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """KREX 교통 공지 record를 notice Feature로 적재한다."""
    records = await _record_list(context, "krex_traffic_notices")
    fetched_at = await _fetched_at(context)
    bundles = await traffic_notices_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KREX_PROVIDER_NAME,
        dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
        bundles=bundles,
    )


@asset(
    group_name="features_notice",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krex_traffic_notices"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_notice_krex_traffic_notices(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_notice_krex_traffic_notices(context)


async def run_feature_place_krheritage_items(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """국가유산 item record를 place/area Feature로 적재한다."""
    records = await _record_list(context, "krheritage_items")
    fetched_at = await _fetched_at(context)
    bundles = await heritage_items_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    result = await _load(
        context,
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_DATASET_KEY,
        bundles=bundles,
    )
    client = cast(
        "AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client")
    )
    inactivated = await client.inactivate_geometryless_area_features_by_source(
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_DATASET_KEY,
        source_entity_type="heritage",
    )
    if inactivated:
        context.log.info(
            "krheritage geometry 없는 area feature %d건 inactive 전환",
            inactivated,
        )
    return result


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krheritage_items"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_krheritage_items(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_krheritage_items(context)


async def run_feature_event_krheritage_events(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """국가유산 행사 record를 event Feature로 적재한다."""
    records = await _record_list(context, "krheritage_events")
    fetched_at = await _fetched_at(context)
    bundles = await heritage_events_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_EVENT_DATASET_KEY,
        bundles=bundles,
    )


@asset(
    group_name="features_event",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krheritage_events"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_event_krheritage_events(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_event_krheritage_events(context)


async def run_feature_place_mois_licenses(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """MOIS 인허가 record를 place Feature로 적재한다."""
    fetched_at = await _fetched_at(context)
    dataset_key = await _resource_value(
        context, "mois_dataset_key", default=MOIS_BULK_DATASET_KEY
    )
    result: DagsterFeatureLoadResult | None = None
    async for records in _record_batches(
        context, "mois_license_records", batch_size=MOIS_RECORD_BATCH_SIZE
    ):
        bundles = await license_records_to_bundles(
            records,
            fetched_at=fetched_at,
            dataset_key=str(dataset_key),
            reverse_geocoder=_reverse_geocoder(context),
        )
        batch_result = await _load(
            context,
            provider=MOIS_PROVIDER_NAME,
            dataset_key=str(dataset_key),
            bundles=bundles,
            record_sync_state=False,
        )
        result = batch_result if result is None else result.merge(batch_result)

    if result is not None:
        client = cast(
            "AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client")
        )
        await _record_feature_sync_success(
            context,
            client,
            provider=MOIS_PROVIDER_NAME,
            dataset_key=str(dataset_key),
            cursor_extra=_feature_result_cursor_extra(result),
        )
        return result
    return await _load(
        context,
        provider=MOIS_PROVIDER_NAME,
        dataset_key=str(dataset_key),
        bundles=[],
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS
    | {"mois_license_records", "mois_dataset_key"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_mois_licenses(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_mois_licenses(context)


async def run_feature_place_knps_points(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """KNPS point/place record를 place Feature로 적재한다."""
    records = await _record_list(context, "knps_point_records")
    fetched_at = await _fetched_at(context)
    dataset_key = str(
        await _resource_value(
            context, "knps_point_dataset_key", default="knps_visitor_centers"
        )
    )
    if dataset_key not in KNPS_PLACE_DATASETS:
        raise KeyError(f"KNPS point dataset_key가 아님: {dataset_key!r}")
    bundles = await knps_point_records_to_bundles(
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
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS
    | {"knps_point_records", "knps_point_dataset_key"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_knps_points(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_knps_points(context)


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
    bundles = await knps_geometry_records_to_bundles(
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
    )


@asset(
    group_name="features_geometry",
    required_resource_keys=_COMMON_RESOURCE_KEYS
    | {"knps_geometry_records", "knps_geometry_dataset_key"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_geometry_knps_records(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_geometry_knps_records(context)


async def run_feature_place_krforest_recreation_forests(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국자연휴양림 record를 place Feature로 적재한다(ADR-034 8단계)."""
    records = await _record_list(context, "krforest_recreation_forests")
    fetched_at = await _fetched_at(context)
    bundles = await recreation_forests_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_RECREATION_FORESTS_DATASET_KEY,
        bundles=bundles,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krforest_recreation_forests"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_krforest_recreation_forests(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_krforest_recreation_forests(context)


async def run_feature_place_krforest_arboretums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """휴양림 수목원(SHP) record를 place Feature로 적재한다."""
    records = await _record_list(context, "krforest_arboretums")
    fetched_at = await _fetched_at(context)
    bundles = await arboretums_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_ARBORETUMS_DATASET_KEY,
        bundles=bundles,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krforest_arboretums"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_krforest_arboretums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_krforest_arboretums(context)


async def run_feature_place_standard_museums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국박물관미술관표준데이터 record를 place Feature로 적재한다(ADR-034 9단계)."""
    records = await _record_list(context, "standard_museums")
    fetched_at = await _fetched_at(context)
    bundles = await museums_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_MUSEUMS,
        bundles=bundles,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_museums"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_standard_museums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_standard_museums(context)


async def run_feature_place_standard_tourist_attractions(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국관광지표준데이터 record를 place Feature로 적재한다(ADR-034 보조)."""
    records = await _record_list(context, "standard_tourist_attractions")
    fetched_at = await _fetched_at(context)
    bundles = await tourist_attractions_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_TOURIST_ATTRACTIONS,
        bundles=bundles,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_tourist_attractions"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_standard_tourist_attractions(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_standard_tourist_attractions(context)


async def run_feature_place_standard_parking_lots(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """전국주차장표준데이터 record를 place Feature로 적재한다(ADR-034 보조)."""
    records = await _record_list(context, "standard_parking_lots")
    fetched_at = await _fetched_at(context)
    bundles = await parking_lots_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_PARKING_LOTS,
        bundles=bundles,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_parking_lots"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_standard_parking_lots(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_standard_parking_lots(context)


async def run_feature_place_khoa_beaches(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """해양수산부 해수욕장정보 record를 place Feature로 적재한다(ADR-034 보조)."""
    records = await _record_list(context, "khoa_beaches")
    fetched_at = await _fetched_at(context)
    bundles = await beaches_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KHOA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_BEACHES,
        bundles=bundles,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"khoa_beaches"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_khoa_beaches(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_khoa_beaches(context)


async def run_feature_place_krairport_airports(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """공항 메타데이터 record를 place Feature로 적재한다(ADR-034 보조)."""
    records = await _record_list(context, "krairport_airports")
    fetched_at = await _fetched_at(context)
    bundles = await airports_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KRAIRPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_AIRPORTS,
        bundles=bundles,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krairport_airports"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_krairport_airports(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_krairport_airports(context)


async def run_feature_place_kor_travel_concierge_youtube(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """kor-travel-concierge YouTube 장소 후보 export를 place Feature로 적재한다.

    ``operation=upsert``는 bundle 적재, ``reject``/``tombstone``은 대응 feature를
    ``status='inactive'``로 전환한다(ADR-050 #4, T-217b — MOIS Step C 동형).
    """
    records = await _record_list(context, "kor_travel_concierge_youtube_features")
    fetched_at = await _fetched_at(context)
    bundles = await kor_travel_concierge_items_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    result = await _load(
        context,
        provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
        dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
        bundles=bundles,
    )
    inactive_ids = kor_travel_concierge_inactive_entity_ids(records)
    if inactive_ids:
        client = cast(
            "AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client")
        )
        inactivated = await client.inactivate_features_by_source(
            provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
            dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
            source_entity_type=KOR_TRAVEL_CONCIERGE_SOURCE_ENTITY_TYPE,
            source_entity_ids=inactive_ids,
        )
        context.log.info(
            "kor-travel-concierge reject/tombstone %d건 → feature %d건 inactive 전환",
            len(inactive_ids),
            inactivated,
        )
    return result


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"kor_travel_concierge_youtube_features"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_kor_travel_concierge_youtube(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_feature_place_kor_travel_concierge_youtube(context)


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
    context.add_output_metadata(result.as_metadata())
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
    return await run_feature_event_visitkorea_enrichment(context)


async def run_feature_weather_airkorea_air_quality(
    context: AssetExecutionContext,
) -> AirQualityLoadResult:
    """대기질 측정소를 weather feature로, 측정값을 air_quality WeatherValue로 적재한다.

    측정소(``airkorea_stations``)와 측정값(``airkorea_air_quality``) 두 record stream을
    읽어 (1) 측정소를 weather-kind ``FeatureBundle``로 변환·매핑(station_name→feature_id),
    (2) 측정값을 오염물질별 ``WeatherValue``로 변환, (3) ``client.load_air_quality``로
    한 transaction에 적재한다(ADR-010 — 대기질은 place가 아니라 측정값).
    """
    stations = await _record_list(context, "airkorea_stations")
    measurements = await _record_list(context, "airkorea_air_quality")
    fetched_at = await _fetched_at(context)
    bundles = await air_quality_stations_to_bundles(
        stations,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    station_feature_ids = {
        bundle.source_record.source_entity_id: bundle.feature.feature_id
        for bundle in bundles
    }
    values = air_quality_to_weather_values(
        measurements, station_feature_ids=station_feature_ids
    )
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    result = await client.load_air_quality(bundles, values)
    _add_output_metadata(
        context,
        {
            "provider": AIRKOREA_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_AIR_QUALITY,
            **result.as_metadata(),
        },
    )
    await _record_feature_sync_success(
        context,
        client,
        provider=AIRKOREA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_AIR_QUALITY,
        cursor_extra=result.as_metadata(),
    )
    return result


@asset(
    group_name="features_weather",
    required_resource_keys=(
        _COMMON_RESOURCE_KEYS | {"airkorea_stations", "airkorea_air_quality"}
    ),
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_weather_airkorea_air_quality(
    context: AssetExecutionContext,
) -> AirQualityLoadResult:
    return await run_feature_weather_airkorea_air_quality(context)


async def run_feature_weather_krex_rest_areas(
    context: AssetExecutionContext,
) -> AirQualityLoadResult:
    """고속도로 휴게소 관측 기상을 weather feature로, 지표를 WeatherValue로 적재한다.

    ``krex_rest_area_weather`` record stream(``RestAreaWeather`` wide row)을 읽어
    (1) 휴게소를 weather-kind ``FeatureBundle``로 변환·매핑(unit_code→feature_id),
    (2) 지표(기온/습도/풍속/강수)를 metric별 ``WeatherValue``로 melt, (3)
    ``client.load_air_quality``(weather feature + value 한 transaction 적재 — 도메인
    무관)로 적재한다. airkorea 대기질 패턴과 동일(ADR-010 — 관측값은 place 아님).
    de-rep(#496): 휴게소당 1 feature, 복제 없음 — ``temperature→T1H``라 KMA 기온
    빈틈(고속도로 농촌 구간)을 nearest-temp로 메운다.
    """
    records = await _record_list(context, "krex_rest_area_weather")
    fetched_at = await _fetched_at(context)
    bundles = await rest_area_weather_records_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    station_feature_ids = {
        bundle.source_record.source_entity_id: bundle.feature.feature_id
        for bundle in bundles
    }
    values = rest_area_weather_records_to_values(
        records, station_feature_ids=station_feature_ids
    )
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    result = await client.load_air_quality(bundles, values)
    _add_output_metadata(
        context,
        {
            "provider": KREX_PROVIDER_NAME,
            "dataset_key": REST_AREA_WEATHER_DATASET_KEY,
            **result.as_metadata(),
        },
    )
    await _record_feature_sync_success(
        context,
        client,
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_WEATHER_DATASET_KEY,
        cursor_extra=result.as_metadata(),
    )
    return result


@asset(
    group_name="features_weather",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krex_rest_area_weather"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_weather_krex_rest_areas(
    context: AssetExecutionContext,
) -> AirQualityLoadResult:
    return await run_feature_weather_krex_rest_areas(context)


FEATURE_LOAD_ASSETS: Final = [
    feature_event_datagokr_cultural_festivals,
    feature_place_opinet_stations,
    feature_price_opinet_stations,
    feature_place_krex_rest_areas,
    feature_price_krex_rest_areas,
    feature_notice_krex_traffic_notices,
    feature_place_krheritage_items,
    feature_event_krheritage_events,
    feature_place_mois_licenses,
    feature_place_knps_points,
    feature_geometry_knps_records,
    feature_place_krforest_recreation_forests,
    feature_place_krforest_arboretums,
    feature_place_standard_museums,
    feature_place_standard_tourist_attractions,
    feature_place_standard_parking_lots,
    feature_place_khoa_beaches,
    feature_place_krairport_airports,
    feature_place_kor_travel_concierge_youtube,
    feature_weather_airkorea_air_quality,
    feature_weather_krex_rest_areas,
    feature_event_visitkorea_enrichment,
]
"""현재 구현 완료된 Feature provider 적재 asset 목록."""


async def _load(
    context: AssetExecutionContext,
    *,
    provider: str,
    dataset_key: str,
    bundles: list[Any],
    record_sync_state: bool = True,
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
    )
    if record_sync_state:
        await _record_feature_sync_success(
            context,
            client,
            provider=provider,
            dataset_key=dataset_key,
            cursor_extra=_feature_result_cursor_extra(result),
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


async def _record_feature_sync_success(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
    *,
    provider: str,
    dataset_key: str,
    cursor_extra: dict[str, object],
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
    await record_sync_success(
        provider=provider,
        dataset_key=dataset_key,
        cursor=cursor,
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


def _reverse_geocoder(context: AssetExecutionContext) -> ReverseGeocoder | None:
    return cast(
        "ReverseGeocoder | None",
        _resource_object(context, "reverse_geocoder", default=None),
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
