"""krtour-map 소유 provider Feature 적재 Dagster asset."""

import inspect
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Iterable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Final, cast

from dagster import AssetExecutionContext, Backoff, RetryPolicy, asset
from krtour.map.geocoding import ReverseGeocoder
from krtour.map.providers.knps import (
    KNPS_GEOMETRY_DATASETS,
    KNPS_PLACE_DATASETS,
    knps_geometry_records_to_bundles,
    knps_point_records_to_bundles,
)
from krtour.map.providers.knps import (
    PROVIDER_NAME as KNPS_PROVIDER_NAME,
)
from krtour.map.providers.krex import (
    KREX_PROVIDER_NAME,
    REST_AREA_DATASET_KEY,
    TRAFFIC_NOTICES_DATASET_KEY,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from krtour.map.providers.krheritage import (
    DATASET_KEY_EVENT as KRHERITAGE_EVENT_DATASET_KEY,
)
from krtour.map.providers.krheritage import (
    DATASET_KEY_HERITAGE as KRHERITAGE_DATASET_KEY,
)
from krtour.map.providers.krheritage import (
    PROVIDER_NAME as KRHERITAGE_PROVIDER_NAME,
)
from krtour.map.providers.krheritage import (
    heritage_events_to_bundles,
    heritage_items_to_bundles,
)
from krtour.map.providers.mois import (
    DATASET_KEY_BULK as MOIS_BULK_DATASET_KEY,
)
from krtour.map.providers.mois import (
    PROVIDER_NAME as MOIS_PROVIDER_NAME,
)
from krtour.map.providers.mois import (
    license_records_to_bundles,
)
from krtour.map.providers.opinet import (
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
    stations_to_bundles,
)
from krtour.map.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    cultural_festivals_to_bundles,
)

from .etl import DagsterFeatureLoadResult, load_feature_bundles_for_dagster

if TYPE_CHECKING:
    from krtour.map.client import AsyncKrtourMapClient

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
    "krtour_map_client",
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
    return await _load(
        context,
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_DATASET_KEY,
        bundles=bundles,
    )


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
        )
        result = batch_result if result is None else result.merge(batch_result)

    if result is not None:
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


FEATURE_LOAD_ASSETS: Final = [
    feature_event_datagokr_cultural_festivals,
    feature_place_opinet_stations,
    feature_place_krex_rest_areas,
    feature_notice_krex_traffic_notices,
    feature_place_krheritage_items,
    feature_event_krheritage_events,
    feature_place_mois_licenses,
    feature_place_knps_points,
    feature_geometry_knps_records,
]
"""현재 구현 완료된 Feature provider 적재 asset 목록."""


async def _load(
    context: AssetExecutionContext,
    *,
    provider: str,
    dataset_key: str,
    bundles: list[Any],
) -> DagsterFeatureLoadResult:
    client = cast("AsyncKrtourMapClient", _resource_object(context, "krtour_map_client"))
    strict_address = bool(await _resource_value(context, "strict_address", default=True))
    return await load_feature_bundles_for_dagster(
        context=context,
        client=client,
        bundles=bundles,
        provider=provider,
        dataset_key=dataset_key,
        strict_address=strict_address,
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
