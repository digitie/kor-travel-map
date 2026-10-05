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
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, cast

from kortravelmap.client import FestivalEnrichmentReviewRefreshResult
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import SourceRecord
from kortravelmap.geocoding import ReverseGeocoder
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    NoticeFeatureLoadResult,
    NoticeReconcileResult,
)
from kortravelmap.infra.integrity_violation_repo import (
    IntegrityObservationReceipt as DurableIntegrityObservationReceipt,
)
from kortravelmap.infra.price_repo import PriceFeatureLoadResult
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
    DATASET_KEY_FUEL_PRICES,
    DATASET_KEY_FUEL_STATIONS,
    DATASET_KEY_HIGHWAY_INCIDENTS,
    DATASET_KEY_REST_AREA_FUEL_PRICES,
    DATASET_KEY_REST_AREAS,
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
)
from kortravelmap.providers.krairport import airports_to_bundles
from kortravelmap.providers.krex import (
    REST_AREA_SOURCE_ENTITY_TYPE,
    rest_area_fuel_price_records_to_features_and_values,
    rest_area_place_locator_from_rows,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
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
from kortravelmap.providers.mois import (
    license_records_to_bundles,
)
from kortravelmap.providers.opinet import (
    OPINET_STATION_SOURCE_ENTITY_TYPE,
    fuel_station_place_locator_from_rows,
    station_prices_to_features_and_values,
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

MAP_POOL_PREFIX: Final[str] = "kor_travel_map."
"""Map pool 이름의 접두사.

pool 이름공간과 ``concurrency.pools.default_limit``은 Dagster **instance 전역**이다.
여러 프로젝트가 한 instance를 쓰는 공유 plane에서 접두사 없는 이름(``kor_travel_geo`` 등)은
다른 프로젝트의 같은 이름 pool과 슬롯을 나눠 서로를 막는다.
그래서 Map pool은 전부 이 접두사로 시작한다(tag key ``kor_travel_map.*``와 같은 규칙).
"""

HIGHWAY_INCIDENT_SNAPSHOT_POOL: Final[str] = f"{MAP_POOL_PREFIX}highway_incident_snapshot"
"""고속도로 돌발 notice 활성 집합의 load/reconcile 순서를 직렬화하는 Dagster pool."""

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

`docker/dagster.yaml`의 `concurrency.pools`가 `default_limit: 1`,
`granularity: run`이므로 **이 이름을 선언하는 것만으로** 인스턴스 전역에서 한
번에 하나만 돈다(`HIGHWAY_INCIDENT_SNAPSHOT_POOL`과 같은 기제).

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

HIGHWAY_INCIDENT_PROVIDER_RUN_LOCK: Final[str] = (
    f"provider-run:{KOR_TRAVEL_TRANSPORT_PROVIDER_NAME}:{DATASET_KEY_HIGHWAY_INCIDENTS}"
)
"""고속도로 돌발 fetch→reconcile을 모든 실행 경로에서 직렬화하는 DB lock key."""

MOIS_RECORD_BATCH_SIZE: Final[int] = 1000
"""MOIS bulk record를 FeatureBundle로 변환하기 전에 끊어 읽는 record batch 크기."""

_KST = timezone(timedelta(hours=9))
_MISSING: Final = object()


def _response_payload_value(value: Any) -> Any:
    """provider raw response를 source-record JSON 값으로 좁혀 보존한다.

    ``make_payload_hash``의 canonical 값 규칙은 이미 저장된 source record의 hash
    약속이므로 넓히지 않는다. 대신 Dagster ingress에서 provider dataclass가 가진
    시간·금액 scalar를 명시적으로 JSON 값으로 바꾼다.
    """

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    # provider dataclass는 ``raw``를 MappingProxyType 등 불변 map으로 들고 올 수 있다.
    # ``dataclasses.asdict`` deep-copies those maps and fails before ingress can
    # canonicalize them.  Walk dataclass fields directly, preserving the same
    # visible field payload without requiring values to be pickleable.
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _response_payload_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    "provider response payload dict key must be str "
                    f"(got {type(key).__name__}: {key!r})"
                )
            normalized[key] = _response_payload_value(item)
        return normalized
    if isinstance(value, list | tuple):
        return [_response_payload_value(item) for item in value]
    raise TypeError(
        "provider response payload must be JSON-preservable "
        f"(got {type(value).__name__}: {value!r})"
    )


def _response_payload_item(item: Any) -> dict[str, Any]:
    """provider response item을 source record에 보존할 canonical JSON object로 만든다."""

    if is_dataclass(item) and not isinstance(item, type):
        return cast(dict[str, Any], _response_payload_value(item))
    raw = getattr(item, "raw", None)
    if isinstance(raw, Mapping):
        return cast(dict[str, Any], _response_payload_value(raw))
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, dict):
            return cast(dict[str, Any], _response_payload_value(dumped))
    if isinstance(item, dict):
        return cast(dict[str, Any], _response_payload_value(item))
    raise TypeError(f"provider response item cannot be preserved as JSON: {type(item).__name__}")


def _value_response_source_record(
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    source_entity_id: str,
    records: Sequence[Any],
    fetched_at: datetime,
) -> SourceRecord:
    """value producer dataset이 소유하는 immutable response source record를 만든다.

    날씨 grid/station Feature의 source entity와 value를 만든 provider response는
    서로 다를 수 있다. 따라서 response 자체를 producer dataset에 귀속한 별도
    source entity로 보존하고, fact는 이 record만 lineage로 참조한다.
    """

    raw_data = {
        "source_entity_id": source_entity_id,
        "records": [_response_payload_item(record) for record in records],
    }
    payload_hash = make_payload_hash(raw_data)
    return SourceRecord(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=make_source_record_key(
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
        ),
    )


_COMMON_RESOURCE_KEYS: Final[set[str]] = {
    "feature_operation_guard",
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
        authoritative_snapshot_complete=True,
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
    bundles = await stations_to_bundles(
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


async def run_feature_price_transport_fuel_stations(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    """오피넷 주유소 유종별 최신 가격(transport export)을 price Feature + PriceValue로 적재한다.

    주유소 place를 다시 만들거나 역지오코딩하지 않는다(ADR-106 리뷰 M5) — 그것은 주간 place
    job의 몫이고 geo-heavy pool 아래서 돈다. 가격 feature의 부모는 이미 적재된 place의
    locator로 찾고, 좌표는 transport가 넘긴 WGS84를 그대로 쓴다. export가 0건·낡음이면 fetcher가
    먼저 실패한다(``TransportExportEmpty``/``TransportExportNotCurrent``).
    """
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    records = await _record_list(context, "transport_fuel_stations")
    fetched_at = await _fetched_at(context)
    locator_rows = await client.list_primary_place_locator(
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_FUEL_STATIONS,
        source_entity_type=OPINET_STATION_SOURCE_ENTITY_TYPE,
    )
    bundles, values = station_prices_to_features_and_values(
        records,
        fetched_at=fetched_at,
        place_locator=fuel_station_place_locator_from_rows(locator_rows),
    )
    if not values:
        # 주유소는 있는데 판매가가 하나도 없으면 원천 drift다 — 성공으로 기록하지 않는다.
        raise RuntimeError(
            "kor-travel-transport 주유소 export에서 PriceValue를 0건 변환했다. "
            "transport 최신 유가와 export 계약을 확인하라."
        )
    latest_observed_at = max(value.observed_at for value in values).astimezone(_KST)
    membership = await _exact_sync_membership(
        context,
        client,
        boundary="transport_fuel_price_value_write",
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_FUEL_PRICES,
    )
    result = await client.load_price_features(
        bundles,
        values,
        provider_dataset_id=membership.provider_dataset_id,
        source_record=_value_response_source_record(
            provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
            dataset_key=DATASET_KEY_FUEL_PRICES,
            source_entity_type="price_response",
            source_entity_id=f"run:{fetched_at.isoformat()}",
            records=[
                {"uni_id": record.uni_id, "prices": [dict(row.raw) for row in record.prices]}
                for record in records
            ],
            fetched_at=fetched_at,
        ),
    )
    load_metadata = {
        **result.as_metadata(),
        "records_fetched": len(records),
        "latest_observed_at": latest_observed_at.isoformat(),
    }
    _add_output_metadata(
        context,
        {
            "provider": KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_FUEL_PRICES,
            **load_metadata,
        },
    )
    await _record_feature_sync_success(
        context,
        client,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_FUEL_PRICES,
        cursor_extra=load_metadata,
    )
    return result


@asset(
    group_name="features_price",
    # price feature의 parent_feature_id는 주유소 place feature를 가리킨다 → place asset을
    # 상류 의존(deps)으로 선언해 계보·backfill 순서를 보장한다. 런타임에는 이미 적재된 place만
    # locator로 부모 삼는다(place가 없는 새 주유소는 부모 없이 적재되고 다음 실행에 붙는다).
    deps=[feature_place_transport_fuel_stations],
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"transport_fuel_stations"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_price_transport_fuel_stations(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_price_transport_fuel_stations)


async def run_feature_place_transport_rest_areas(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """고속도로 휴게소(transport export)를 place Feature로 적재한다."""
    records = await _record_list(context, "transport_rest_areas")
    fetched_at = await _fetched_at(context)
    bundles = await rest_areas_to_bundles(
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


async def run_feature_price_transport_rest_areas(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    """휴게소 주유소 현재 유가(transport export)를 price Feature + PriceValue로 적재한다.

    #547 — 유가 row에는 lon/lat가 없어 이미 적재된 휴게소 place feature의 자연키→좌표 locator로
    좌표·``parent_feature_id``를 상속한다(geocoding 미경유). place가 아직 없으면 유가는
    coordless로 적재되고 다음 실행에서 회복된다.
    """
    records = await _record_list(context, "transport_rest_area_fuel_prices")
    fetched_at = await _fetched_at(context)
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    locator_rows = await client.list_primary_place_locator(
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_REST_AREAS,
        source_entity_type=REST_AREA_SOURCE_ENTITY_TYPE,
    )
    place_locator = rest_area_place_locator_from_rows(locator_rows)
    bundles, values = rest_area_fuel_price_records_to_features_and_values(
        records,
        fetched_at=fetched_at,
        place_locator=place_locator,
    )
    membership = await _exact_sync_membership(
        context,
        client,
        boundary="transport_rest_area_price_value_write",
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_REST_AREA_FUEL_PRICES,
    )
    result = await client.load_price_features(
        bundles,
        values,
        provider_dataset_id=membership.provider_dataset_id,
        source_record=_value_response_source_record(
            provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
            dataset_key=DATASET_KEY_REST_AREA_FUEL_PRICES,
            source_entity_type="price_response",
            source_entity_id=f"run:{fetched_at.isoformat()}",
            records=[dict(record.raw) for record in records],
            fetched_at=fetched_at,
        ),
    )
    _add_output_metadata(
        context,
        {
            "provider": KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_REST_AREA_FUEL_PRICES,
            **result.as_metadata(),
        },
    )
    await _record_feature_sync_success(
        context,
        client,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_REST_AREA_FUEL_PRICES,
        cursor_extra=result.as_metadata(),
    )
    return result


@asset(
    group_name="features_price",
    # 유가 price feature는 휴게소 place feature를 parent로 삼고 place 좌표를 locator로 상속한다.
    deps=[feature_place_transport_rest_areas],
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"transport_rest_area_fuel_prices"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_price_transport_rest_areas(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_price_transport_rest_areas)


async def run_feature_notice_transport_highway_incidents(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """고속도로 돌발 활성 집합을 provider 전역 DB lock 안에서 반영한다."""
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    async with client.provider_run_lock(HIGHWAY_INCIDENT_PROVIDER_RUN_LOCK):
        return await _run_feature_notice_transport_highway_incidents_locked(context, client)


async def _run_feature_notice_transport_highway_incidents_locked(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
) -> DagsterFeatureLoadResult:
    """고속도로 돌발을 notice Feature로 적재하고 활성 집합에 없는 계보를 닫는다.

    transport export는 **마지막 성공 수집이 본 사건 전체**다(transport ADR-013). 수집이 실패했거나
    30분 넘게 성공하지 못했으면 transport가 503을 내고 fetcher가 실패한다 — 그때는 아무것도
    닫지 않는다. 적재 직후 reconcile(#632): 같은 계보의 중복 feature를 soft-delete하고, 이번
    집합에 없는 계보의 latest feature는 ``valid_end_time=fetched_at``으로 닫는다. 다시 나타난
    계보는 이전 종료 시각을 지워 active로 복구한다.
    """
    fetched_at = await _fetched_at(context)
    await _guard_notice_snapshot_watermark(
        context,
        client,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_HIGHWAY_INCIDENTS,
        source_entity_type="traffic_notice",
        fetched_at=fetched_at,
    )
    records = await _record_list(context, "transport_highway_incidents")
    bundles = await traffic_notices_to_bundles(
        records,
        fetched_at=fetched_at,
        # 10분 freshness 경로에서 row별 reverse geocoding을 수행하면 snapshot 반영보다 주소
        # 보강이 더 오래 걸린다. 원천 좌표는 converter가 Feature.coord/SourceRecord에 보존한다.
        reverse_geocoder=None,
    )
    active_lineage_keys = {
        bundle.source_record.source_entity_id for bundle in bundles
    }
    reconciled: Any | None = None

    async def load_snapshot_atomically(
        validated_bundles: Sequence[Any],
    ) -> FeatureLoadResult:
        nonlocal reconciled
        atomic_load = getattr(client, "load_authoritative_notice_snapshot", None)
        if not callable(atomic_load):
            raise RuntimeError(
                "고속도로 돌발 snapshot은 atomic snapshot load client가 필요하다."
            )
        outcome = cast(
            "NoticeFeatureLoadResult",
            await atomic_load(
                bundles=validated_bundles,
                provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
                dataset_key=DATASET_KEY_HIGHWAY_INCIDENTS,
                source_entity_type="traffic_notice",
                active_lineage_keys=active_lineage_keys,
                observed_at=fetched_at,
            ),
        )
        reconciled = outcome.reconcile
        return outcome.load

    result = await _load(
        context,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_HIGHWAY_INCIDENTS,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        record_sync_state=False,
        load_all=load_snapshot_atomically,
    )
    if reconciled is None:
        raise RuntimeError("고속도로 돌발 atomic load가 reconcile 결과를 반환하지 않았다.")
    if reconciled.superseded or reconciled.closed or reconciled.reopened:
        context.log.info(
            "고속도로 돌발 reconcile — 중복 soft-delete %d건, 집합 소멸 닫음 %d건, "
            "재등장 복구 %d건.",
            reconciled.superseded,
            reconciled.closed,
            reconciled.reopened,
        )
    # load 성공만으로 sync cursor를 전진시키지 않는다. reconcile까지 성공한 뒤에만
    # snapshot 전체 처리를 성공으로 기록한다.
    await _record_feature_sync_success(
        context,
        client,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_HIGHWAY_INCIDENTS,
        cursor_extra={
            **_feature_result_cursor_extra(result),
            "notices_superseded": reconciled.superseded,
            "notices_closed": reconciled.closed,
            "notices_reopened": reconciled.reopened,
            "snapshot_applied_at": fetched_at.isoformat(),
        },
        observation_receipt=result.observation_receipt,
    )
    return result


async def _guard_notice_snapshot_watermark(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    fetched_at: datetime,
) -> None:
    """이미 반영한 snapshot보다 과거인 run의 destructive reconcile을 막는다.

    Dagster pool이 정상 경로를 직렬화하지만, 배포 이전 queued run이나 pool 설정이
    반영되지 않은 실행까지 방어하도록 persisted sync cursor를 watermark로 쓴다.
    """
    get_sync_state = getattr(client, "get_sync_state_for_operation_membership", None)
    if not callable(get_sync_state):
        raise RuntimeError(
            "notice snapshot은 get_sync_state_for_operation_membership을 "
            "제공하는 client가 필요하다."
        )
    if not callable(
        getattr(client, "record_sync_success_for_operation_membership", None)
    ):
        raise RuntimeError(
            "notice snapshot은 record_sync_success_for_operation_membership을 "
            "제공하는 client가 필요하다."
        )
    watermarks: list[datetime] = []
    get_scope_watermark = getattr(client, "get_notice_snapshot_watermark", None)
    if callable(get_scope_watermark):
        scope_watermark = await get_scope_watermark(
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
        )
        if scope_watermark is not None:
            if (
                scope_watermark.tzinfo is None
                or scope_watermark.utcoffset() is None
            ):
                raise RuntimeError("notice scope watermark는 timezone-aware datetime이어야 한다.")
            watermarks.append(scope_watermark)

    membership = await _exact_sync_membership(
        context,
        client,
        boundary="notice_snapshot_watermark",
        provider=provider,
        dataset_key=dataset_key,
    )
    state = await get_sync_state(membership=membership)
    if state is not None:
        cursor = getattr(state, "cursor", None)
        if not isinstance(cursor, dict):
            raise RuntimeError("notice snapshot sync cursor가 object가 아니다.")
        raw_watermark = cursor.get("snapshot_applied_at") or cursor.get("loaded_at")
        if raw_watermark is not None:
            watermarks.append(_parse_snapshot_watermark(raw_watermark))
    if not watermarks:
        return
    watermark = max(watermarks)
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise RuntimeError("notice snapshot fetched_at은 timezone-aware datetime이어야 한다.")
    # 동일 watermark는 core의 fingerprint CAS가 exact replay인지 충돌인지
    # 판정한다. 여기서 막으면 누락된 member state를 replay로 self-heal할 수 없다.
    if fetched_at < watermark:
        raise RuntimeError(
            "notice snapshot이 이미 반영한 watermark보다 과거다: "
            f"fetched_at={fetched_at.isoformat()}, watermark={watermark.isoformat()}"
        )


def _parse_snapshot_watermark(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("notice snapshot watermark가 비어 있거나 문자열이 아니다.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("notice snapshot watermark가 ISO-8601 datetime이 아니다.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("notice snapshot watermark는 timezone-aware datetime이어야 한다.")
    return parsed


@asset(
    group_name="features_notice",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"transport_highway_incidents"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=HIGHWAY_INCIDENT_SNAPSHOT_POOL,
)
async def feature_notice_transport_highway_incidents(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_notice_transport_highway_incidents
    )


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
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    retired = 0

    async def _load_and_retire(
        snapshot_bundles: Sequence[Any],
    ) -> FeatureLoadResult:
        nonlocal retired
        load, retired = await client.load_authoritative_feature_snapshot(
            snapshot_bundles,
            provider=KRHERITAGE_PROVIDER_NAME,
            dataset_key=KRHERITAGE_DATASET_KEY,
            source_entity_type="heritage",
            retire_geometryless_areas=True,
        )
        return load

    result = await _load(
        context,
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        load_all=_load_and_retire,
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
        authoritative_snapshot_complete=True,
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
    """MOIS 인허가 record를 place Feature로 적재한다."""
    fetched_at = await _fetched_at(context)
    dataset_key = await _resource_value(context, "mois_dataset_key", default=MOIS_BULK_DATASET_KEY)
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    strict_address = cast(
        "bool | str",
        await _resource_value(context, "strict_address", default="strict"),
    )

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(
            context, "mois_license_records", batch_size=MOIS_RECORD_BATCH_SIZE
        ):
            # 변환 결과도 현재 1,000-record batch만 유지한다. 전체 snapshot은
            # 아래 client transaction에서 순차 적재되고 마지막에 한 번 봉인된다.
            yield await license_records_to_bundles(
                records,
                fetched_at=fetched_at,
                dataset_key=str(dataset_key),
                reverse_geocoder=_reverse_geocoder(context),
            )

    async def _load_all(
        batches: AsyncIterable[Sequence[Any]],
    ) -> FeatureLoadResult:
        return await client.load_feature_bundle_batches(
            batches,
            curation_dataset=(MOIS_PROVIDER_NAME, str(dataset_key)),
        )

    result = await load_feature_bundle_batches_for_dagster(
        context=context,
        client=client,
        batches=_bundle_batches(),
        provider=MOIS_PROVIDER_NAME,
        dataset_key=str(dataset_key),
        strict_address=strict_address,
        load_all=_load_all,
    )
    await _record_feature_sync_success(
        context,
        client,
        provider=MOIS_PROVIDER_NAME,
        dataset_key=str(dataset_key),
        cursor_extra=_feature_result_cursor_extra(result),
        observation_receipt=result.observation_receipt,
    )
    return result


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"mois_license_records", "mois_dataset_key"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
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
        authoritative_snapshot_complete=True,
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
        authoritative_snapshot_complete=True,
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
            yield await recreation_forests_to_bundles(
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_RECREATION_FORESTS_DATASET_KEY,
        batches=_bundle_batches(),
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
            yield await arboretums_to_bundles(
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=KRFOREST_ARBORETUMS_DATASET_KEY,
        batches=_bundle_batches(),
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
    bundles = await mountain_trails_to_bundles(
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
    bundles = await dulle_trails_to_bundles(
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
    ) -> FeatureLoadResult:
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
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "standard_museums", batch_size=100):
            yield await museums_to_bundles(
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_MUSEUMS,
        batches=_bundle_batches(),
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
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(
            context, "standard_tourist_attractions", batch_size=100
        ):
            yield await tourist_attractions_to_bundles(
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_TOURIST_ATTRACTIONS,
        batches=_bundle_batches(),
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
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "standard_parking_lots", batch_size=100):
            yield await parking_lots_to_bundles(
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_PARKING_LOTS,
        batches=_bundle_batches(),
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
    fetched_at = await _fetched_at(context)

    async def _bundle_batches() -> AsyncIterator[Sequence[Any]]:
        async for records in _record_batches(context, "standard_special_streets", batch_size=100):
            yield await special_streets_to_bundles(
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_SPECIAL_STREETS,
        batches=_bundle_batches(),
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
    records = await _record_list(context, "datagokr_file_data_records")
    fetched_at = await _fetched_at(context)
    bundles = await file_data_rows_to_bundles(
        records,
        dataset_key=dataset_key,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=DATAGOKR_FILEDATA_PROVIDER_NAME,
        dataset_key=dataset_key,
        bundles=bundles,
        authoritative_snapshot_complete=True,
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
            yield await beaches_to_bundles(
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=KHOA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_BEACHES,
        batches=_bundle_batches(),
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
            yield await airports_to_bundles(
                records, fetched_at=fetched_at, reverse_geocoder=_reverse_geocoder(context)
            )

    return await _load_snapshot_batches(
        context,
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_AIRPORTS,
        batches=_bundle_batches(),
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
    bundles = await kor_travel_concierge_items_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
        quarantine=quarantined,
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
    ) -> FeatureLoadResult:
        nonlocal retired
        load, retired = await client.load_authoritative_feature_snapshot(
            snapshot_bundles,
            provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
            dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
            source_entity_type=KOR_TRAVEL_CONCIERGE_SOURCE_ENTITY_TYPE,
            retired_source_entity_ids=retired_entity_ids,
        )
        return load

    result = await _load(
        context,
        provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
        dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        load_all=_load_and_retire,
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
    feature_price_transport_fuel_stations,
    feature_place_transport_rest_areas,
    feature_price_transport_rest_areas,
    feature_notice_transport_highway_incidents,
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


async def _load_snapshot_batches(
    context: AssetExecutionContext,
    *,
    provider: str,
    dataset_key: str,
    batches: AsyncIterable[Sequence[Any]],
) -> DagsterFeatureLoadResult:
    """전체 snapshot을 보관하지 않고 기존 단일 transaction·봉인 계약으로 적재한다."""
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    strict_address = cast(
        "bool | str", await _resource_value(context, "strict_address", default="strict")
    )

    async def _load_all(items: AsyncIterable[Sequence[Any]]) -> FeatureLoadResult:
        return await client.load_feature_bundle_batches(
            items, curation_dataset=(provider, dataset_key)
        )

    result = await load_feature_bundle_batches_for_dagster(
        context=context,
        client=client,
        batches=batches,
        provider=provider,
        dataset_key=dataset_key,
        strict_address=strict_address,
        load_all=_load_all,
    )
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
    load_all: Callable[[Sequence[Any]], Awaitable[FeatureLoadResult]] | None = None,
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
