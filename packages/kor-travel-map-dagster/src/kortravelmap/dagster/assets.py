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
from typing import TYPE_CHECKING, Any, Final, cast

from kortravelmap.client import FestivalEnrichmentReviewRefreshResult
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.geocoding import ReverseGeocoder
from kortravelmap.infra.feature_repo import (
    AirQualityLoadResult,
    FeatureLoadResult,
    NoticeFeatureLoadResult,
)
from kortravelmap.infra.integrity_violation_repo import (
    IntegrityObservationReceipt as DurableIntegrityObservationReceipt,
)
from kortravelmap.infra.price_repo import PriceFeatureLoadResult
from kortravelmap.providers.airkorea import (
    AIRKOREA_PROVIDER_NAME,
    DATASET_KEY_AIR_QUALITY,
    air_quality_stations_to_bundles,
    air_quality_to_weather_values,
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

OPINET_API_POOL: Final[str] = "opinet_api"
"""OpiNet 호출 asset을 인스턴스 전체에서 직렬화하는 Dagster pool."""

OPINET_PROVIDER_RUN_LOCK: Final[str] = "provider-run:python-opinet-api"
"""OpiNet fetch→load를 모든 실행 경로에서 직렬화하는 PostgreSQL lock key."""

KREX_NOTICE_SNAPSHOT_POOL: Final[str] = "krex_notice_snapshot"
"""KREX notice snapshot의 load/reconcile 순서를 직렬화하는 Dagster pool."""

KREX_NOTICE_PROVIDER_RUN_LOCK: Final[str] = "provider-run:python-krex-api:krex_traffic_notices"
"""KREX notice fetch→reconcile을 모든 실행 경로에서 직렬화하는 DB lock key."""

MOIS_RECORD_BATCH_SIZE: Final[int] = 1000
"""MOIS bulk record를 FeatureBundle로 변환하기 전에 끊어 읽는 record batch 크기."""

_KST = timezone(timedelta(hours=9))
_MISSING: Final = object()
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
)
async def feature_event_datagokr_cultural_festivals(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_event_datagokr_cultural_festivals
    )


async def run_feature_place_opinet_stations(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """OpiNet 주유소를 DB lock + KST 일일 coalescing 안에서 적재한다."""
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    async with client.provider_run_lock(OPINET_PROVIDER_RUN_LOCK):
        fetched_at = await _fetched_at(context)
        if await _skip_opinet_if_already_succeeded_today(
            context,
            client,
            dataset_key=OPINET_STATION_DATASET_KEY,
            fetched_at=fetched_at,
        ):
            return await _load(
                context,
                provider=OPINET_PROVIDER_NAME,
                dataset_key=OPINET_STATION_DATASET_KEY,
                bundles=[],
                authoritative_snapshot_complete=False,
                record_sync_state=False,
            )
        return await _run_feature_place_opinet_stations_locked(
            context,
            fetched_at=fetched_at,
        )


async def _run_feature_place_opinet_stations_locked(
    context: AssetExecutionContext,
    *,
    fetched_at: datetime,
) -> DagsterFeatureLoadResult:
    """OpiNet 주유소 record를 place Feature로 적재한다."""
    records = await _record_list(context, "opinet_stations")
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
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"opinet_stations"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=OPINET_API_POOL,
)
async def feature_place_opinet_stations(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_opinet_stations)


async def run_feature_price_opinet_stations(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    """OpiNet 가격을 DB lock + KST 일일 coalescing 안에서 적재한다."""
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    async with client.provider_run_lock(OPINET_PROVIDER_RUN_LOCK):
        fetched_at = await _fetched_at(context)
        if await _skip_opinet_if_already_succeeded_today(
            context,
            client,
            dataset_key=OPINET_PRICE_DATASET_KEY,
            fetched_at=fetched_at,
        ):
            return PriceFeatureLoadResult(features=FeatureLoadResult(), price_values=0)
        return await _run_feature_price_opinet_stations_locked(
            context,
            client,
            fetched_at=fetched_at,
        )


async def _run_feature_price_opinet_stations_locked(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
    *,
    fetched_at: datetime,
) -> PriceFeatureLoadResult:
    """OpiNet 주유소 상세 가격을 price Feature + PriceValue로 적재한다."""
    records = await _record_list(context, "opinet_station_price_details")
    if not records:
        # enabled scope에서 0건을 RUN_SUCCESS로 기록하면 마지막 성공 cursor만
        # 전진하고 실제 갱신 중단은 감춰진다. 개별 area/product의 no-data는 fetcher가
        # 계속 허용하되, whole-run zero는 provider/scope 장애로 취급한다.
        raise RuntimeError(
            "OpiNet 가격 조회가 전체 scope에서 0건을 반환했다. "
            "provider 응답·쿼터·scope 설정을 확인하라."
        )
    reverse_geocoder = _reverse_geocoder(context)
    has_station_details = any(hasattr(record, "prices") for record in records)
    if has_station_details:
        station_bundles, bundles, values = await station_details_to_price_features_and_values(
            records,
            fetched_at=fetched_at,
            reverse_geocoder=reverse_geocoder,
        )
    else:
        station_bundles, bundles, values = await stations_to_price_features_and_values(
            records,
            fetched_at=fetched_at,
            reverse_geocoder=reverse_geocoder,
        )
    if not values:
        # raw station record가 있어도 가격 필드 누락/스키마 drift로 모든 row가
        # 정규화 단계에서 탈락할 수 있다. 이를 성공으로 기록하면 cursor만 전진해
        # 실제 OpiNet 가격 갱신 중단을 숨기므로 load 전에 명시적으로 실패한다.
        raise RuntimeError(
            "OpiNet 가격 record를 PriceValue로 0건 변환했다. "
            "provider 응답 스키마와 제품 가격 필드를 확인하라."
        )
    latest_observed_at = max(value.observed_at for value in values).astimezone(_KST)
    today_kst = fetched_at.astimezone(_KST).date()
    today_values_count = sum(
        value.observed_at.astimezone(_KST).date() == today_kst for value in values
    )
    # 가격 feature의 parent_feature_id가 가리키는 주유소 place feature를 가격보다
    # 먼저 upsert한다. 가격 detail에만 있고 stations 목록 asset에는 없는 주유소
    # (endpoint coverage 불일치)의 부모 place도 보장돼, price INSERT가 FK 제약
    # ``fk_features_parent_feature_id_features``을 위반하지 않는다.
    if station_bundles:
        await client.load_feature_bundles(station_bundles)
    result = await client.load_price_features(bundles, values)
    coverage = "configured_scope" if has_station_details else "rotating_partial"
    load_metadata = {
        **result.as_metadata(),
        "records_fetched": len(records),
        "coverage": coverage,
        "latest_observed_at": latest_observed_at.isoformat(),
        "today_values_count": today_values_count,
    }
    _add_output_metadata(
        context,
        {
            "provider": OPINET_PROVIDER_NAME,
            "dataset_key": OPINET_PRICE_DATASET_KEY,
            **load_metadata,
        },
    )
    await _record_feature_sync_success(
        context,
        client,
        provider=OPINET_PROVIDER_NAME,
        dataset_key=OPINET_PRICE_DATASET_KEY,
        cursor_extra=load_metadata,
    )
    return result


async def _skip_opinet_if_already_succeeded_today(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
    *,
    dataset_key: str,
    fetched_at: datetime,
) -> bool:
    """같은 OpiNet dataset의 KST 당일 성공이 있으면 API fetch 전에 합친다.

    request scope를 반영할 수 없는 targeted 경로는 runner가 호출 전에 생략한다.
    이 함수는 남은 schedule/manual/provider-wide 경로를 provider DB lock 안에서
    persisted sync state로 합쳐, place/price의 불필요한 당일 중복 호출을 줄인다.
    실패 run은 success 시각을 전진시키지 않아 같은 날 재시도할 수 있다.
    """
    membership = await _exact_sync_membership(
        context,
        client,
        boundary="opinet_sync_state",
        provider=OPINET_PROVIDER_NAME,
        dataset_key=dataset_key,
    )
    state = await client.get_sync_state_for_operation_membership(membership=membership)
    last_success_at = state.last_success_at if state is not None else None
    if last_success_at is None:
        return False
    cursor = getattr(state, "cursor", None)
    raw_loaded_at = cursor.get("loaded_at") if isinstance(cursor, Mapping) else None
    loaded_at = _aware_datetime_or_none(raw_loaded_at)
    if loaded_at is None:
        return False
    if last_success_at.tzinfo is None or last_success_at.utcoffset() is None:
        raise RuntimeError("OpiNet sync state last_success_at은 timezone-aware여야 한다.")
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise RuntimeError("OpiNet fetched_at은 timezone-aware datetime이어야 한다.")
    # last_success_at은 DB commit 시각이라 자정을 넘긴 run에서는 다음 KST 날짜가
    # 된다. cursor의 run-start loaded_at과 현재 run-start를 비교해야 다음 날
    # schedule을 잘못 막지 않는다.
    if loaded_at.astimezone(_KST).date() != fetched_at.astimezone(_KST).date():
        return False
    if dataset_key == OPINET_PRICE_DATASET_KEY:
        today_values_count = (
            cursor.get("today_values_count") if isinstance(cursor, Mapping) else None
        )
        price_values_upserted = (
            cursor.get("price_values_upserted") if isinstance(cursor, Mapping) else None
        )
        latest_observed_at = _aware_datetime_or_none(
            cursor.get("latest_observed_at") if isinstance(cursor, Mapping) else None
        )
        if (
            not isinstance(today_values_count, int)
            or isinstance(today_values_count, bool)
            or today_values_count <= 0
            or not isinstance(price_values_upserted, int)
            or isinstance(price_values_upserted, bool)
            or today_values_count != price_values_upserted
            or latest_observed_at is None
            or latest_observed_at.astimezone(_KST).date()
            != loaded_at.astimezone(_KST).date()
        ):
            # 오전 수동 run이 전일/혼합 가격을 받아도 last_success_at은 오늘이 된다.
            # 이를 당일 성공으로 합치면 18:18 정식 run까지 건너뛰므로, 적재한 모든
            # 값이 오늘 observed_at인 성공만 price 일일 coalescing 근거로 쓴다.
            return False

    metadata = {
        "provider": OPINET_PROVIDER_NAME,
        "dataset_key": dataset_key,
        "skipped": True,
        "skip_reason": "already_succeeded_today_kst",
        "last_success_at": last_success_at.astimezone(_KST).isoformat(),
    }
    _add_output_metadata(context, metadata)
    context.log.info(
        "OpiNet %s는 KST 당일 이미 성공해 중복 API fetch를 생략함(last_success_at=%s).",
        dataset_key,
        metadata["last_success_at"],
    )
    return True


def _aware_datetime_or_none(value: object) -> datetime | None:
    """ISO-8601 aware datetime만 파싱하고 legacy/손상 cursor는 합치지 않는다."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


@asset(
    group_name="features_price",
    # price feature의 parent_feature_id는 주유소 place feature를 가리킨다 →
    # place asset을 dagster 상류 의존(deps)으로 선언해 계보·backfill 순서를 보장한다.
    # 단, place는 월 1회/price는 일 1회 스케줄이라(OpiNet 일일 한도) 스케줄 자체는
    # 분리하고, 런타임 정합성은 price asset의 parent place co-load(#605)가 보장한다.
    deps=[feature_place_opinet_stations],
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"opinet_station_price_details"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=OPINET_API_POOL,
)
async def feature_price_opinet_stations(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_price_opinet_stations)


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
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krex_rest_areas"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_krex_rest_areas(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_krex_rest_areas)


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
    # 유가 price feature는 휴게소 place feature를 parent로 삼고 place 좌표를 locator로
    # 상속한다 → place asset을 상류 의존(deps)으로 선언(place 먼저 적재 시 좌표 회복).
    # place 월 1회/price 일 2회라 스케줄은 분리하고, place 미적재 시 price는
    # coordless·parentless로 degrade한다(FK 위반 없음).
    deps=[feature_place_krex_rest_areas],
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krex_rest_area_fuel_prices"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_price_krex_rest_areas(
    context: AssetExecutionContext,
) -> PriceFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_price_krex_rest_areas)


async def run_feature_notice_krex_traffic_notices(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """KREX notice snapshot을 provider 전역 DB lock 안에서 반영한다."""
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
    async with client.provider_run_lock(KREX_NOTICE_PROVIDER_RUN_LOCK):
        return await _run_feature_notice_krex_traffic_notices_locked(context, client)


async def _run_feature_notice_krex_traffic_notices_locked(
    context: AssetExecutionContext,
    client: "AsyncKorTravelMapClient",
) -> DagsterFeatureLoadResult:
    """KREX 교통 공지 record를 notice Feature로 적재한다.

    적재 직후 reconcile(#632): 같은 계보의 중복 feature(identity 스킴 변경으로
    재키잉된 구세대 등)를 soft-delete하고, 이번 feed에 없는 계보의 latest
    feature는 ``valid_end_time=fetched_at``으로 닫는다 — 실시간 돌발 feed에서
    사라진 사건이 영구 active로 남지 않게. 다시 나타난 계보는 이전 종료 시각을
    지워 active 상태로 복구한다.
    """
    fetched_at = await _fetched_at(context)
    await _guard_notice_snapshot_watermark(
        context,
        client,
        provider=KREX_PROVIDER_NAME,
        dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
        source_entity_type="traffic_notice",
        fetched_at=fetched_at,
    )
    records = await _record_list(context, "krex_traffic_notices")
    bundles = await traffic_notices_to_bundles(
        records,
        fetched_at=fetched_at,
        # 10분 freshness 경로에서 row별 reverse geocoding을 수행하면 snapshot
        # 수집보다 주소 보강이 더 오래 걸린다. 원천 좌표는 converter가 그대로
        # Feature.coord/SourceRecord에 보존하므로 lifecycle 반영에는 geocoder가 없다.
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
                "KREX notice snapshot은 atomic snapshot load client가 필요하다."
            )
        outcome = cast(
            "NoticeFeatureLoadResult",
            await atomic_load(
                bundles=validated_bundles,
                provider=KREX_PROVIDER_NAME,
                dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
                source_entity_type="traffic_notice",
                active_lineage_keys=active_lineage_keys,
                observed_at=fetched_at,
            ),
        )
        reconciled = outcome.reconcile
        return outcome.load

    result = await _load(
        context,
        provider=KREX_PROVIDER_NAME,
        dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
        record_sync_state=False,
        load_all=load_snapshot_atomically,
    )
    if reconciled is None:
        raise RuntimeError("KREX notice atomic load가 reconcile 결과를 반환하지 않았다.")
    if reconciled.superseded or reconciled.closed or reconciled.reopened:
        context.log.info(
            "KREX notice reconcile — 중복 soft-delete %d건, feed 소멸 닫음 %d건, 재등장 복구 %d건.",
            reconciled.superseded,
            reconciled.closed,
            reconciled.reopened,
        )
    # load 성공만으로 sync cursor를 전진시키지 않는다. reconcile까지 성공한 뒤에만
    # snapshot 전체 처리를 성공으로 기록한다.
    await _record_feature_sync_success(
        context,
        client,
        provider=KREX_PROVIDER_NAME,
        dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
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
            "KREX notice snapshot은 get_sync_state_for_operation_membership을 "
            "제공하는 client가 필요하다."
        )
    if not callable(
        getattr(client, "record_sync_success_for_operation_membership", None)
    ):
        raise RuntimeError(
            "KREX notice snapshot은 record_sync_success_for_operation_membership을 "
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
            "KREX notice snapshot이 이미 반영한 watermark보다 과거다: "
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
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krex_traffic_notices"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=KREX_NOTICE_SNAPSHOT_POOL,
)
async def feature_notice_krex_traffic_notices(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_notice_krex_traffic_notices
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
    result = await _load(
        context,
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_DATASET_KEY,
        bundles=bundles,
        authoritative_snapshot_complete=True,
    )
    client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
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
            authoritative_snapshot_complete=False,
            record_sync_state=False,
        )
        result = batch_result if result is None else result.merge(batch_result)

    if result is not None:
        result = result.complete_authoritative_snapshot()
        client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
        await _record_feature_sync_success(
            context,
            client,
            provider=MOIS_PROVIDER_NAME,
            dataset_key=str(dataset_key),
            cursor_extra=_feature_result_cursor_extra(result),
            observation_receipt=result.observation_receipt,
        )
        return result
    return await _load(
        context,
        provider=MOIS_PROVIDER_NAME,
        dataset_key=str(dataset_key),
        bundles=[],
        authoritative_snapshot_complete=False,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"mois_license_records", "mois_dataset_key"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
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
)
async def feature_geometry_knps_records(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_geometry_knps_records)


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
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krforest_recreation_forests"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
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
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krforest_arboretums"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_krforest_arboretums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_krforest_arboretums)


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
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_museums"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_standard_museums(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_standard_museums)


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
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_tourist_attractions"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
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
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_parking_lots"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
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
    records = await _record_list(context, "standard_special_streets")
    fetched_at = await _fetched_at(context)
    bundles = await special_streets_to_bundles(
        records,
        fetched_at=fetched_at,
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_SPECIAL_STREETS,
        bundles=bundles,
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"standard_special_streets"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
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
)
async def feature_place_datagokr_file_data(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_datagokr_file_data)


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
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"khoa_beaches"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_khoa_beaches(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_khoa_beaches)


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
        authoritative_snapshot_complete=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"krairport_airports"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_krairport_airports(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    return await run_tracked_feature_asset(context, run_feature_place_krairport_airports)


async def run_feature_place_kor_travel_concierge_youtube(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult:
    """kor-travel-concierge YouTube 장소 후보 export를 place Feature로 적재한다.

    ``operation=upsert``는 bundle 적재, ``reject``/``tombstone``은 대응 feature를
    ``status='inactive'``로 전환한다(ADR-050 #4, T-217b — MOIS Step C 동형).
    적재 후 inactivate 순서가 mid-run 검수 전이(되돌리기)의 구 operation으로 신
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
        context.add_output_metadata(
            {
                "concierge_quarantined_count": len(quarantined),
                "concierge_quarantined_item_keys": [
                    entry.item_key for entry in quarantined[:20]
                ],
                "concierge_quarantined_reasons": [
                    f"{entry.reason_code}: {entry.message}"[:300]
                    for entry in quarantined[:20]
                ],
            }
        )
    result = await _load(
        context,
        provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
        dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
        bundles=bundles,
        authoritative_snapshot_complete=True,
    )
    inactive_ids = kor_travel_concierge_inactive_entity_ids(records)
    if inactive_ids:
        client = cast("AsyncKorTravelMapClient", _resource_object(context, "kor_travel_map_client"))
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
    return await run_tracked_feature_asset(
        context, run_feature_event_visitkorea_enrichment
    )


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
        bundle.source_record.source_entity_id: bundle.feature.feature_id for bundle in bundles
    }
    values = air_quality_to_weather_values(measurements, station_feature_ids=station_feature_ids)
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
    required_resource_keys=(_COMMON_RESOURCE_KEYS | {"airkorea_stations", "airkorea_air_quality"}),
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_weather_airkorea_air_quality(
    context: AssetExecutionContext,
) -> AirQualityLoadResult:
    return await run_tracked_feature_asset(
        context, run_feature_weather_airkorea_air_quality
    )


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
        bundle.source_record.source_entity_id: bundle.feature.feature_id for bundle in bundles
    }
    values = rest_area_weather_records_to_values(records, station_feature_ids=station_feature_ids)
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
    return await run_tracked_feature_asset(context, run_feature_weather_krex_rest_areas)


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
    feature_place_standard_special_streets,
    feature_place_datagokr_file_data,
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
    authoritative_snapshot_complete: bool,
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

    획득 경로는 ``kma_weather._exact_kma_sync_membership``과 같은 계약이다:
    queue worker가 request를 claim할 때 고정한 typed membership resource가 있으면
    그것을 쓰고, 없으면 feature-operation guard의 operation key로 다시 조회해
    guard snapshot과 동일한 enabled membership 하나만 허용한다.
    **provider나 dataset label에서 membership을 역산하는 fallback은 두지 않는다** —
    그렇게 하면 guard가 고정한 실행 대상과 다른 행에 cursor를 쓸 수 있다.
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
    memberships = await client.resolve_feature_operation_memberships(
        operation_key=guard.operation_key,
    )
    if memberships != guard.memberships:
        raise FeatureOperationGuardUnavailable(
            boundary=boundary,
            reason="membership_snapshot_changed",
        )
    # 한 operation이 여러 dataset을 다루는 경우가 있다(예: KNPS point는 5개).
    # 그래서 "정확히 하나"로는 고를 수 없고, **이번 호출이 적재한 dataset**으로
    # 좁힌다. operation은 여전히 guard가 준 것이므로 label에서 역산하는 것이
    # 아니다 — guard가 고정한 membership 집합 안에서 고르기만 한다.
    membership = await client.resolve_feature_operation_dataset_membership(
        operation_key=guard.operation_key,
        provider=provider,
        dataset_key=dataset_key,
    )
    if membership not in memberships:
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
