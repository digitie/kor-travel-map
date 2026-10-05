"""Dagster resource factory.

운영 배포는 이 module의 기본 resource를 그대로 쓰거나, 테스트/특수 배포에서
``Definitions(..., resources={...})``로 교체한다.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, cast

import httpx
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.geocoding import (
    GeoCallStats,
    KorTravelGeoRestClient,
    kor_travel_geo_reverse_geocoder,
)
from kortravelmap.infra.db import make_async_engine, require_pg_dsn
from kortravelmap.infra.file_store import (
    S3ObjectStore,
    build_s3_object_store,
    create_s3_client,
)
from kortravelmap.providers.knps import (
    KNPS_GEOMETRY_DATASET_KEYS,
    KNPS_POINT_DATASET_KEYS,
)
from kortravelmap.settings import KorTravelMapSettings

from dagster import Field as DagsterField
from dagster import InitResourceContext, ResourceDefinition, resource

from .feature_operation_tracking import (
    ensure_feature_operation_guard_for_provider,
    feature_operation_guard_resource,
)
from .mois_source_sync import ensure_mois_source_db_fresh
from .provider_fetchers import (
    fetch_datagokr_cultural_festivals,
    fetch_datagokr_file_data_records,
    fetch_khoa_beaches,
    fetch_knps_geometry_records,
    fetch_knps_point_records,
    fetch_kor_travel_concierge_youtube_features,
    fetch_krforest_arboretums,
    fetch_krforest_dulle_trails,
    fetch_krforest_landslide_forecast_issues,
    fetch_krforest_mountain_trails,
    fetch_krforest_recreation_forests,
    fetch_krheritage_events,
    fetch_krheritage_items,
    fetch_mcst_culture_records,
    fetch_mois_license_records,
    fetch_standard_museums,
    fetch_standard_parking_lots,
    fetch_standard_special_streets,
    fetch_standard_tourist_attractions,
    fetch_transport_airports,
    fetch_transport_fuel_stations,
    fetch_transport_highway_incidents,
    fetch_transport_rest_area_fuel_prices,
    fetch_transport_rest_areas,
    fetch_visitkorea_festival_events,
)

__all__ = [
    "PROVIDER_RECORD_RESOURCE_DEFINITIONS",
    "PROVIDER_RECORD_RESOURCE_SPECS",
    "ProviderRecordResourceSpec",
    "build_offline_upload_store_from_settings",
    "build_provider_record_guard_resource",
    "build_provider_record_live_resource",
    "create_s3_client_from_settings",
    "datagokr_file_data_dataset_key_resource",
    "feature_operation_guard_resource",
    "kor_travel_map_client_resource",
    "offline_upload_store_resource",
    "reverse_geocoder_resource",
]


_LOGGER = logging.getLogger(__name__)
"""geo 경계 계수를 Dagster event stream까지 나르는 표준 logger.

`docker/dagster.yaml`의 `managed_python_loggers`에 이 모듈 이름이 있어야 실린다 —
`provider_fetchers`가 같은 방식으로 H45 재시도 경고를 내보낸다.
"""


@dataclass(frozen=True, slots=True)
class ProviderRecordResourceSpec:
    """Feature load asset용 provider record resource guard 사양."""

    resource_key: str
    provider_package: str
    dataset_key: str
    setting_names: tuple[str, ...] = ()
    source_env_names: tuple[str, ...] = ()
    note: str = ""

    @property
    def kor_travel_map_env_names(self) -> tuple[str, ...]:
        return tuple(f"KOR_TRAVEL_MAP_{name.upper()}" for name in self.setting_names)


@dataclass(frozen=True, slots=True)
class _ProviderRecordIterable:
    """Dagster가 sync generator를 resource setup generator로 오해하지 않게 감싼다."""

    records: Iterator[Any]

    def __iter__(self) -> Iterator[Any]:
        return self.records


PROVIDER_RECORD_RESOURCE_SPECS: tuple[ProviderRecordResourceSpec, ...] = (
    ProviderRecordResourceSpec(
        resource_key="datagokr_cultural_festivals",
        provider_package="python-datagokr-api",
        dataset_key="datagokr_cultural_festivals",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
    ),
    ProviderRecordResourceSpec(
        resource_key="transport_fuel_stations",
        provider_package="kor-travel-transport",
        dataset_key="transport_fuel_stations",
        setting_names=("kor_travel_transport_base_url", "kor_travel_transport_service_token"),
        note=(
            "오피넷 전국 주유소 + 유종별 최신 가격(transport 브라우저 수집본). "
            "place·price 두 job이 같이 쓴다."
        ),
    ),
    ProviderRecordResourceSpec(
        resource_key="transport_rest_areas",
        provider_package="kor-travel-transport",
        dataset_key="transport_rest_areas",
        setting_names=("kor_travel_transport_base_url", "kor_travel_transport_service_token"),
        note="고속도로 휴게소 기준정보(data.go.kr 표준데이터, transport 수집).",
    ),
    ProviderRecordResourceSpec(
        resource_key="transport_rest_area_fuel_prices",
        provider_package="kor-travel-transport",
        dataset_key="transport_rest_area_fuel_prices",
        setting_names=("kor_travel_transport_base_url", "kor_travel_transport_service_token"),
        note="휴게소 주유소 현재 유가(EX curStateStation, transport 수집).",
    ),
    ProviderRecordResourceSpec(
        resource_key="transport_highway_incidents",
        provider_package="kor-travel-transport",
        dataset_key="transport_highway_incidents",
        setting_names=("kor_travel_transport_base_url", "kor_travel_transport_service_token"),
        note="마지막 성공 수집의 고속도로 돌발 활성 집합(transport 5분 수집).",
    ),
    ProviderRecordResourceSpec(
        resource_key="transport_airports",
        provider_package="kor-travel-transport",
        dataset_key="transport_airports",
        setting_names=("kor_travel_transport_base_url", "kor_travel_transport_service_token"),
        note="국내 운영 공항 전체(transport의 krairport 번들 메타데이터).",
    ),
    ProviderRecordResourceSpec(
        resource_key="krheritage_items",
        provider_package="python-krheritage-api",
        dataset_key="krheritage_heritage_features",
        note=(
            "국가유산 search/detail(khs.go.kr)은 keyless — provider transport는 "
            "apis.data.go.kr URL에만 serviceKey를 주입한다. scope는 settings "
            "krheritage_kind_codes, run당 상한은 krheritage_max_items_per_run."
        ),
    ),
    ProviderRecordResourceSpec(
        resource_key="krheritage_events",
        provider_package="python-krheritage-api",
        dataset_key="krheritage_event_list",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
    ),
    ProviderRecordResourceSpec(
        resource_key="mois_license_records",
        provider_package="python-mois-api",
        dataset_key="mois_license_features_bulk",
        setting_names=("mois_source_db_path",),
        note="MOIS는 LOCALDATA file download/source DB refresh 후 PlaceRecord stream이 필요하다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="knps_point_records",
        provider_package="python-knps-api",
        dataset_key="knps_visitor_centers",
        note="KNPS는 keyless file dataset이며 parser/typed record resource wiring이 필요하다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="knps_geometry_records",
        provider_package="python-knps-api",
        dataset_key="knps_trails",
        note="KNPS geometry는 SHP/CSV parser가 WGS84 WKT typed record를 제공해야 한다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="krforest_recreation_forests",
        provider_package="python-krforest-api",
        dataset_key="krforest_recreation_forests",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
    ),
    ProviderRecordResourceSpec(
        resource_key="krforest_arboretums",
        provider_package="python-krforest-api",
        dataset_key="krforest_arboretums",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note="수목원은 SHP file 다운로드/파싱(provider geo extra 필요할 수 있음).",
    ),
    ProviderRecordResourceSpec(
        resource_key="krforest_mountain_trails",
        provider_package="python-krforest-api",
        dataset_key="krforest_mountain_trails",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note="PBD0000041 중첩 SHP aggregate를 route geometry로 파싱한다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="krforest_dulle_trails",
        provider_package="python-krforest-api",
        dataset_key="krforest_dulle_trails",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note="PBD0000031 SHP aggregate를 route geometry로 파싱한다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="krforest_landslide_forecast_issues",
        provider_package="python-krforest-api",
        dataset_key="krforest_landslide_forecast_issues",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note="산사태 예보발령·해제 notice snapshot을 6회/일 적재한다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="standard_museums",
        provider_package="python-datagokr-api",
        dataset_key="datagokr_museums",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
    ),
    ProviderRecordResourceSpec(
        resource_key="standard_tourist_attractions",
        provider_package="python-datagokr-api",
        dataset_key="datagokr_tourist_attractions",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
    ),
    ProviderRecordResourceSpec(
        resource_key="standard_parking_lots",
        provider_package="python-datagokr-api",
        dataset_key="datagokr_parking_lots",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
    ),
    ProviderRecordResourceSpec(
        resource_key="standard_special_streets",
        provider_package="python-datagokr-api",
        dataset_key="standard_special_streets",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
    ),
    ProviderRecordResourceSpec(
        resource_key="datagokr_file_data_records",
        provider_package="python-datagokr-api",
        dataset_key="datagokr_file_data",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note=(
            "curated fileData 4종 공용 resource. Dagster asset은 "
            "datagokr_file_data_dataset_key resource로 실제 dataset_key를 받는다. "
            "서울 책방만 원천이 서울 열린데이터광장(OA-21062)으로 옮겨져 "
            "SEOUL_OPEN_DATA_API_KEY를 쓴다 — 여기 setting_names에 넣지 않는 것은 "
            "나머지 3종이 그 키 없이도 돌아야 하기 때문이고, 없을 때는 fetcher가 "
            "ProviderCredentialMissing으로 정확히 말한다."
        ),
    ),
    ProviderRecordResourceSpec(
        resource_key="khoa_beaches",
        provider_package="python-khoa-api",
        dataset_key="khoa_beaches",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note="khoa 해수욕장정보는 시도별 페이지네이션으로 전국을 순회한다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="visitkorea_festival_events",
        provider_package="python-visitkorea-api",
        dataset_key="visitkorea_festival_events",
        setting_names=("data_go_kr_service_key",),
        source_env_names=("DATA_GO_KR_SERVICE_KEY",),
        note="visitkorea는 datagokr 축제(1차) 적재 후 enrichment(2차)로 매칭/적재된다.",
    ),
    ProviderRecordResourceSpec(
        resource_key="kor_travel_concierge_youtube_features",
        provider_package="kor-travel-concierge",
        dataset_key="youtube_place_candidates",
        setting_names=("kor_travel_concierge_base_url", "kor_travel_concierge_api_key"),
        note=(
            "kor-travel-concierge의 /api/v1/features/{snapshot|changes} REST export를 "
            "pull한다. kor-travel-concierge에서 발급한 DB read scope 키를 "
            "kor-travel-map API key로 주입하며 source env API_KEYS는 공유하지 않는다."
        ),
    ),
    ProviderRecordResourceSpec(
        resource_key="mcst_culture_records",
        provider_package="python-mcst-api",
        dataset_key="mcst_file_datasets",
        note=(
            "MCST 파일데이터 CSV 등록 dataset을 (slug, row) 튜플로 stream — "
            "asset이 slug별 분리 적재(dataset_key mcst_<slug>). CSV 다운로드는 "
            "keyless(다운로드 페이지 스크레이핑, provider #6/#7 — #395)."
        ),
    ),
)
"""Feature load asset provider record resource별 env/package 매핑."""


def _provider_guard_message(
    spec: ProviderRecordResourceSpec,
    *,
    has_required_settings: bool,
) -> str:
    krtour_env = ", ".join(spec.kor_travel_map_env_names) or "auth env 없음"
    source_env = ", ".join(spec.source_env_names) or "auth env 없음"
    reason = (
        "credential 환경변수가 설정되지 않았음"
        if spec.setting_names and not has_required_settings
        else "provider public client live fetcher가 아직 연결되지 않았음"
    )
    note = f" {spec.note}" if spec.note else ""
    return (
        f"Dagster provider record resource {spec.resource_key!r}는 기본 실행 비활성 상태: "
        f"{reason}. provider={spec.provider_package}, dataset={spec.dataset_key}. "
        f"kor-travel-map env: {krtour_env}; source env: {source_env}. "
        "운영 실행은 provider public client wiring PR 또는 Definitions resource override가 "
        f"필요하다.{note}"
    )


def build_provider_record_guard_resource(
    spec: ProviderRecordResourceSpec,
) -> ResourceDefinition:
    """Provider record resource의 env 매핑을 보존하는 비실행 guard."""

    @resource(
        required_resource_keys={
            "feature_operation_guard",
            "kor_travel_map_client",
        },
        description=(
            f"{spec.resource_key} provider record guard "
            f"({spec.provider_package}, {spec.dataset_key})."
        )
    )
    def _resource(context: InitResourceContext) -> object:
        ensure_feature_operation_guard_for_provider(
            context,
            boundary=spec.resource_key,
        )
        settings = KorTravelMapSettings()
        has_required_settings = all(
            getattr(settings, setting_name) is not None for setting_name in spec.setting_names
        )
        raise RuntimeError(
            _provider_guard_message(spec, has_required_settings=has_required_settings)
        )

    return _resource


def build_provider_record_live_resource(
    spec: ProviderRecordResourceSpec,
    fetch: Callable[[KorTravelMapSettings], Iterable[Any] | AsyncIterator[Any]],
) -> ResourceDefinition:
    """provider public client live fetcher를 resource value로 노출한다.

    credential이 없으면 guard와 동일한 helpful message로 ``RuntimeError``를
    던져 missing-credential 동작을 graceful하게 유지한다. credential이 있으면
    ``fetch(settings)``가 반환한 record iterable(sync ``Iterable`` 또는 async
    generator)을 asset이 소비할 resource value로 돌려준다(여기서 소비하지 않음 —
    asset의 ``_record_batches``가 sync/async 모두 lazy하게 iterate).

    주의: Dagster는 ``@resource`` 함수가 sync generator object를 반환하면 이를
    setup/teardown resource generator로 해석한다. 따라서 sync ``Iterator``는 얇은
    iterable wrapper로 감싸고, list/tuple 같은 일반 ``Iterable``과 ``AsyncIterator``는
    그대로 둔다.
    """

    @resource(
        required_resource_keys={
            "feature_operation_guard",
            "kor_travel_map_client",
        },
        description=(
            f"{spec.resource_key} provider record live fetcher "
            f"({spec.provider_package}, {spec.dataset_key})."
        )
    )
    def _resource(context: InitResourceContext) -> Iterable[Any] | AsyncIterator[Any]:
        ensure_feature_operation_guard_for_provider(
            context,
            boundary=spec.resource_key,
        )
        settings = KorTravelMapSettings()
        has_required_settings = all(
            getattr(settings, setting_name) is not None for setting_name in spec.setting_names
        )
        if not has_required_settings:
            raise RuntimeError(
                _provider_guard_message(spec, has_required_settings=False)
            )
        records = fetch(settings)
        if isinstance(records, Iterator):
            return _ProviderRecordIterable(records)
        return records

    return _resource


_DATAGOKR_FILE_DATA_CONFIG_SCHEMA = {
    "dataset_key": DagsterField(
        str,
        default_value="",
        is_required=False,
        description=(
            "실행할 data.go.kr curated fileData dataset_key. 비어 있으면 "
            "KorTravelMapSettings.datagokr_file_data_dataset_key를 사용한다."
        ),
    )
}

_KNPS_DATASET_CONFIG_SCHEMA = {
    "dataset_key": DagsterField(
        str,
        default_value="",
        is_required=False,
        description=(
            "operation registry가 launch 시 고정한 KNPS dataset key. "
            "비어 있으면 settings 값을 사용한다."
        ),
    )
}


def _build_knps_record_resource(
    spec: ProviderRecordResourceSpec,
    fetch: Callable[[KorTravelMapSettings], Iterable[Any] | AsyncIterator[Any]],
    *,
    setting_name: str,
    allowed_dataset_keys: frozenset[str],
) -> ResourceDefinition:
    """registry가 고정한 KNPS dataset snapshot으로 fetcher를 실행한다."""

    @resource(
        required_resource_keys={
            "feature_operation_guard",
            "kor_travel_map_client",
        },
        config_schema=_KNPS_DATASET_CONFIG_SCHEMA,
        description=(
            f"{spec.resource_key} provider record live fetcher "
            f"({spec.provider_package}, launch-time dataset snapshot)."
        ),
    )
    def _resource(context: InitResourceContext) -> Iterable[Any] | AsyncIterator[Any]:
        ensure_feature_operation_guard_for_provider(
            context,
            boundary=spec.resource_key,
        )
        settings = KorTravelMapSettings()
        configured = context.resource_config.get("dataset_key")
        dataset_key = str(configured or getattr(settings, setting_name))
        if dataset_key not in allowed_dataset_keys:
            raise RuntimeError(
                f"KNPS operation registry에 없는 dataset snapshot: {dataset_key!r}"
            )
        resolved_settings = settings.model_copy(update={setting_name: dataset_key})
        records = fetch(resolved_settings)
        if isinstance(records, Iterator):
            return _ProviderRecordIterable(records)
        return records

    return _resource


def _datagokr_file_data_dataset_key(
    context: InitResourceContext, settings: KorTravelMapSettings
) -> str:
    configured = context.resource_config.get("dataset_key")
    return str(configured or settings.datagokr_file_data_dataset_key)


@resource(
    required_resource_keys={"feature_operation_guard", "kor_travel_map_client"},
    config_schema=_DATAGOKR_FILE_DATA_CONFIG_SCHEMA,
    description=(
        "data.go.kr curated fileData dataset_key 값. Schedule run_config가 있으면 "
        "그 값을 우선하고, 없으면 KorTravelMapSettings 기본값을 쓴다."
    ),
)
def datagokr_file_data_dataset_key_resource(
    context: InitResourceContext,
) -> str:
    ensure_feature_operation_guard_for_provider(
        context,
        boundary="datagokr_file_data_dataset_key",
    )
    return _datagokr_file_data_dataset_key(context, KorTravelMapSettings())


PROVIDER_RECORD_RESOURCE_DEFINITIONS: dict[str, ResourceDefinition] = {
    spec.resource_key: build_provider_record_guard_resource(spec)
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
}
"""기본 code location에서 provider key별로 등록되는 resource 정의.

live fetcher가 연결된 provider는 아래에서 guard를 live resource로 교체한다;
나머지는 비실행 guard로 남는다(later PR에서 점진 연결).
"""

_DATAGOKR_CULTURAL_FESTIVALS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "datagokr_cultural_festivals"
)
"""datagokr 축제 spec 참조 (live resource override용)."""

PROVIDER_RECORD_RESOURCE_DEFINITIONS["datagokr_cultural_festivals"] = (
    build_provider_record_live_resource(
        _DATAGOKR_CULTURAL_FESTIVALS_SPEC,
        fetch_datagokr_cultural_festivals,
    )
)

_TRANSPORT_FUEL_STATIONS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "transport_fuel_stations"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["transport_fuel_stations"] = (
    build_provider_record_live_resource(
        _TRANSPORT_FUEL_STATIONS_SPEC,
        fetch_transport_fuel_stations,
    )
)

_TRANSPORT_REST_AREAS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "transport_rest_areas"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["transport_rest_areas"] = (
    build_provider_record_live_resource(
        _TRANSPORT_REST_AREAS_SPEC,
        fetch_transport_rest_areas,
    )
)

_TRANSPORT_REST_AREA_FUEL_PRICES_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "transport_rest_area_fuel_prices"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["transport_rest_area_fuel_prices"] = (
    build_provider_record_live_resource(
        _TRANSPORT_REST_AREA_FUEL_PRICES_SPEC,
        fetch_transport_rest_area_fuel_prices,
    )
)

_TRANSPORT_HIGHWAY_INCIDENTS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "transport_highway_incidents"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["transport_highway_incidents"] = (
    build_provider_record_live_resource(
        _TRANSPORT_HIGHWAY_INCIDENTS_SPEC,
        fetch_transport_highway_incidents,
    )
)

_TRANSPORT_AIRPORTS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "transport_airports"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["transport_airports"] = (
    build_provider_record_live_resource(
        _TRANSPORT_AIRPORTS_SPEC,
        fetch_transport_airports,
    )
)

_KRHERITAGE_EVENTS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krheritage_events"
)
"""krheritage 행사 spec 참조 (live resource override용)."""

PROVIDER_RECORD_RESOURCE_DEFINITIONS["krheritage_events"] = (
    build_provider_record_live_resource(
        _KRHERITAGE_EVENTS_SPEC,
        fetch_krheritage_events,
    )
)

_KRHERITAGE_ITEMS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krheritage_items"
)
"""krheritage 국가유산 본체 spec 참조 (live resource override용, #380).

khs.go.kr search/detail은 keyless라 spec.setting_names가 비어 있어 live guard
활성 판정(all(...) over empty)은 항상 True — knps file dataset과 동일 패턴.
"""

PROVIDER_RECORD_RESOURCE_DEFINITIONS["krheritage_items"] = (
    build_provider_record_live_resource(
        _KRHERITAGE_ITEMS_SPEC,
        fetch_krheritage_items,
    )
)

_MOIS_LICENSE_RECORDS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "mois_license_records"
)
"""MOIS 인허가 spec 참조 (live resource override용)."""


def _sync_then_fetch_mois_license_records(
    settings: KorTravelMapSettings,
) -> Iterable[Any]:
    """MOIS Phase A source DB가 stale/missing일 때만 sync한 뒤 Phase B record를 읽는다.

    #617 리뷰: 매 read마다 전국 Phase A sync를 돌리지 않고 freshness 게이트를 통과한
    경우에만 sync한다(``ensure_mois_source_db_fresh``).
    """
    ensure_mois_source_db_fresh(settings)
    return fetch_mois_license_records(settings)

PROVIDER_RECORD_RESOURCE_DEFINITIONS["mois_license_records"] = (
    build_provider_record_live_resource(
        _MOIS_LICENSE_RECORDS_SPEC,
        _sync_then_fetch_mois_license_records,
    )
)

_KNPS_POINT_RECORDS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "knps_point_records"
)
_KNPS_GEOMETRY_RECORDS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "knps_geometry_records"
)
# KNPS file dataset은 keyless(공개) — spec.setting_names가 비어 있어 live guard
# 활성 판정(all(...) over empty)은 항상 True. provider(python-knps-api>=0.2)가
# 헤더 정규화 typed record(KnpsPlaceRecord/KnpsGeoRecord)를 노출하므로 krtour는
# best-guess 컬럼 매핑 없이 그대로 소비한다.
PROVIDER_RECORD_RESOURCE_DEFINITIONS["knps_point_records"] = (
    _build_knps_record_resource(
        _KNPS_POINT_RECORDS_SPEC,
        fetch_knps_point_records,
        setting_name="knps_point_dataset_key",
        allowed_dataset_keys=KNPS_POINT_DATASET_KEYS,
    )
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["knps_geometry_records"] = (
    _build_knps_record_resource(
        _KNPS_GEOMETRY_RECORDS_SPEC,
        fetch_knps_geometry_records,
        setting_name="knps_geometry_dataset_key",
        allowed_dataset_keys=KNPS_GEOMETRY_DATASET_KEYS,
    )
)

_KRFOREST_RECREATION_FORESTS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krforest_recreation_forests"
)
_KRFOREST_ARBORETUMS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krforest_arboretums"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["krforest_recreation_forests"] = (
    build_provider_record_live_resource(
        _KRFOREST_RECREATION_FORESTS_SPEC,
        fetch_krforest_recreation_forests,
    )
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["krforest_arboretums"] = (
    build_provider_record_live_resource(
        _KRFOREST_ARBORETUMS_SPEC,
        fetch_krforest_arboretums,
    )
)

_KRFOREST_MOUNTAIN_TRAILS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krforest_mountain_trails"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["krforest_mountain_trails"] = (
    build_provider_record_live_resource(
        _KRFOREST_MOUNTAIN_TRAILS_SPEC,
        fetch_krforest_mountain_trails,
    )
)

_KRFOREST_DULLE_TRAILS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krforest_dulle_trails"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["krforest_dulle_trails"] = (
    build_provider_record_live_resource(
        _KRFOREST_DULLE_TRAILS_SPEC,
        fetch_krforest_dulle_trails,
    )
)

_KRFOREST_LANDSLIDE_FORECAST_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "krforest_landslide_forecast_issues"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["krforest_landslide_forecast_issues"] = (
    build_provider_record_live_resource(
        _KRFOREST_LANDSLIDE_FORECAST_SPEC,
        fetch_krforest_landslide_forecast_issues,
    )
)

_STANDARD_MUSEUMS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "standard_museums"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["standard_museums"] = (
    build_provider_record_live_resource(
        _STANDARD_MUSEUMS_SPEC,
        fetch_standard_museums,
    )
)

_STANDARD_TOURIST_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "standard_tourist_attractions"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["standard_tourist_attractions"] = (
    build_provider_record_live_resource(
        _STANDARD_TOURIST_SPEC,
        fetch_standard_tourist_attractions,
    )
)

_STANDARD_PARKING_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "standard_parking_lots"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["standard_parking_lots"] = (
    build_provider_record_live_resource(
        _STANDARD_PARKING_SPEC,
        fetch_standard_parking_lots,
    )
)

_STANDARD_SPECIAL_STREETS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "standard_special_streets"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["standard_special_streets"] = (
    build_provider_record_live_resource(
        _STANDARD_SPECIAL_STREETS_SPEC,
        fetch_standard_special_streets,
    )
)

_DATAGOKR_FILE_DATA_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "datagokr_file_data_records"
)


@resource(
    required_resource_keys={"feature_operation_guard", "kor_travel_map_client"},
    config_schema=_DATAGOKR_FILE_DATA_CONFIG_SCHEMA,
    description=(
        "datagokr_file_data_records provider record live fetcher "
        "(python-datagokr-api, datagokr_file_data)."
    ),
)
def _datagokr_file_data_records_resource(
    context: InitResourceContext,
) -> Iterable[Any] | AsyncIterator[Any]:
    ensure_feature_operation_guard_for_provider(
        context,
        boundary="datagokr_file_data_records",
    )
    settings = KorTravelMapSettings()
    has_required_settings = all(
        getattr(settings, setting_name) is not None
        for setting_name in _DATAGOKR_FILE_DATA_SPEC.setting_names
    )
    if not has_required_settings:
        raise RuntimeError(
            _provider_guard_message(
                _DATAGOKR_FILE_DATA_SPEC,
                has_required_settings=False,
            )
        )
    records = fetch_datagokr_file_data_records(
        settings,
        dataset_key=_datagokr_file_data_dataset_key(context, settings),
    )
    if isinstance(records, Iterator):
        return _ProviderRecordIterable(records)
    return records


PROVIDER_RECORD_RESOURCE_DEFINITIONS["datagokr_file_data_records"] = (
    _datagokr_file_data_records_resource
)

_KHOA_BEACHES_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "khoa_beaches"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["khoa_beaches"] = (
    build_provider_record_live_resource(
        _KHOA_BEACHES_SPEC,
        fetch_khoa_beaches,
    )
)

_VISITKOREA_FESTIVAL_EVENTS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "visitkorea_festival_events"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["visitkorea_festival_events"] = (
    build_provider_record_live_resource(
        _VISITKOREA_FESTIVAL_EVENTS_SPEC,
        fetch_visitkorea_festival_events,
    )
)

_KOR_TRAVEL_CONCIERGE_YOUTUBE_FEATURES_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "kor_travel_concierge_youtube_features"
)
PROVIDER_RECORD_RESOURCE_DEFINITIONS["kor_travel_concierge_youtube_features"] = (
    build_provider_record_live_resource(
        _KOR_TRAVEL_CONCIERGE_YOUTUBE_FEATURES_SPEC,
        fetch_kor_travel_concierge_youtube_features,
    )
)

_MCST_CULTURE_RECORDS_SPEC: ProviderRecordResourceSpec = next(
    spec
    for spec in PROVIDER_RECORD_RESOURCE_SPECS
    if spec.resource_key == "mcst_culture_records"
)
"""MCST 파일데이터 spec 참조 (live resource override용, #395).

CSV 파일 다운로드는 keyless라 spec.setting_names가 비어 있어 live guard
활성 판정(all(...) over empty)은 항상 True — knps/krheritage items와 동일 패턴.
"""

PROVIDER_RECORD_RESOURCE_DEFINITIONS["mcst_culture_records"] = (
    build_provider_record_live_resource(
        _MCST_CULTURE_RECORDS_SPEC,
        fetch_mcst_culture_records,
    )
)


def build_offline_upload_store_from_settings(
    settings: KorTravelMapSettings,
    *,
    s3_client: Any | None = None,
) -> S3ObjectStore:
    """설정에서 offline upload bucket용 S3 store를 만든다."""
    return build_s3_object_store(
        s3_client=s3_client,
        bucket=settings.offline_upload_bucket,
        region_name=settings.object_store_region,
        endpoint_url=settings.object_store_endpoint_url,
        access_key_id=(
            settings.object_store_access_key_id.get_secret_value()
            if settings.object_store_access_key_id is not None
            else None
        ),
        secret_access_key=(
            settings.object_store_secret_access_key.get_secret_value()
            if settings.object_store_secret_access_key is not None
            else None
        ),
        public_base_url=None,
    )


def create_s3_client_from_settings(settings: KorTravelMapSettings) -> Any:
    """boto3 S3 호환 client를 설정에서 생성한다."""
    return create_s3_client(
        region_name=settings.object_store_region,
        endpoint_url=settings.object_store_endpoint_url,
        access_key_id=(
            settings.object_store_access_key_id.get_secret_value()
            if settings.object_store_access_key_id is not None
            else None
        ),
        secret_access_key=(
            settings.object_store_secret_access_key.get_secret_value()
            if settings.object_store_secret_access_key is not None
            else None
        ),
    )


async def _await_resource_teardown(awaitable: Awaitable[object]) -> None:
    await awaitable


def _run_async_resource_teardown(awaitable: Awaitable[object]) -> None:
    """Dagster sync generator resource teardown에서 async cleanup을 실행한다."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_await_resource_teardown(awaitable))
        return

    raised: list[BaseException] = []

    def _runner() -> None:
        try:
            asyncio.run(_await_resource_teardown(awaitable))
        except BaseException as exc:  # pragma: no cover - 아래 re-raise 경로 검증
            raised.append(exc)

    thread = threading.Thread(
        target=_runner,
        name="kor-travel-map-dagster-resource-teardown",
    )
    thread.start()
    thread.join()
    if raised:
        raise raised[0]


def _dispose_async_engine(engine: Any) -> None:
    sync_engine = getattr(engine, "sync_engine", None)
    sync_dispose = getattr(sync_engine, "dispose", None)
    if sync_dispose is not None:
        sync_dispose(close=False)
        return

    dispose_result = engine.dispose()
    if inspect.isawaitable(dispose_result):
        _run_async_resource_teardown(cast("Awaitable[object]", dispose_result))


@resource(description="admin offline upload 원본 파일을 읽는 RustFS/S3 store.")
def offline_upload_store_resource(_context: InitResourceContext) -> S3ObjectStore:
    """Dagster ``offline_upload_store`` 기본 resource."""
    return build_offline_upload_store_from_settings(KorTravelMapSettings())


@resource(
    description=(
        "KorTravelMapSettings.kor_travel_geo_base_url 기반 kor-travel-geo reverse_geocoder. "
        "base URL이 없으면 **실패**한다(ADR-058/F-01 — geocoder 필수, feature_id 결정성)."
    ),
)
def reverse_geocoder_resource(_context: InitResourceContext) -> Iterator[Any]:
    """Dagster ``reverse_geocoder`` 기본 resource.

    ADR-058(F-01): geocoded ``bjd_code``가 ``make_feature_id``에 박히므로 geocoder가
    None이면 같은 record가 run마다 ``f_global_``↔``f_<bjd>_``로 갈려 feature_id가
    비멱등이 된다. base URL 미설정 시 조용히 None을 주지 않고 **즉시 실패**시켜
    geocoder를 필수화한다(결정성 보장, 전 feature DB re-key 없이 — 사용자 결정 B).
    """
    settings = KorTravelMapSettings()
    if settings.kor_travel_geo_base_url is None:
        raise RuntimeError(
            "reverse_geocoder가 필수다(ADR-058/F-01 — feature_id 결정성). "
            "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL을 설정하라."
        )

    http = httpx.AsyncClient(
        base_url=settings.kor_travel_geo_base_url.get_secret_value(),
        timeout=settings.kor_travel_geo_timeout_seconds,
    )
    # **이 resource가 geo 경계 계수의 소유자다.** 아래 `region_fallback_radius_km`이
    # 켜져 있어서 좌표 하나가 왕복 1회일 수도 2회일 수도 있는데, 그 비율이 오늘
    # 어디에도 기록되지 않는다. 계수는 아무것도 바꾸지 않고 세기만 한다.
    stats = GeoCallStats()
    try:
        client = KorTravelGeoRestClient(
            http,
            api_key=settings.kor_travel_geo_api_key,
            stats=stats,
        )
        yield kor_travel_geo_reverse_geocoder(
            client,
            region_fallback_radius_km=0.1,
        )
    finally:
        # **`add_output_metadata`가 아니라 로그로 낸다.** 실패한 step은 output을 내지
        # 못하므로(`feature_operation_tracking._log_spend_on_failure`가 같은 이유를
        # 적어 두었다), metadata로만 내면 **정확히 증거가 가장 필요한 run에서 수가
        # 사라진다.** 2026-09-19의 증상이 "3시간 동안 이벤트 0건"이었다.
        #
        # WARNING인 이유는 `docker/dagster.yaml`의 `python_log_level: WARNING`이다 —
        # INFO로 내면 Dagster event stream에 실리지 않아 조용해진다.
        _LOGGER.warning("%s", stats.summary())
        _run_async_resource_teardown(http.aclose())


@resource(description="kor-travel-map app DB에 연결된 AsyncKorTravelMapClient.")
def kor_travel_map_client_resource(
    _context: InitResourceContext,
) -> Iterator[AsyncKorTravelMapClient]:
    """Dagster ``kor_travel_map_client`` 기본 resource."""
    settings = KorTravelMapSettings()
    engine = make_async_engine(
        require_pg_dsn(settings),
        pool_size=1,
        max_overflow=0,
        server_settings={"statement_timeout": "600000", "lock_timeout": "30000"},
    )
    try:
        yield AsyncKorTravelMapClient(engine, settings=settings)
    finally:
        _dispose_async_engine(engine)
